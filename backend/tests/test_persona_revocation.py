"""Persona token refresh + server-side revocation (ADR-0007)."""

import time

from services.gateway_auth import (
    AUD_GATEWAY,
    create_persona_refresh_token,
    create_persona_token,
    decode_persona_token,
)
from services.persona_revocation import is_revoked, revoke_all, revoke_jti
from tests.conftest import make_agent_config, make_personnel, make_user


def _agent(db_session, company, name="Ada", slug="ada"):
    p = make_personnel(db_session, company.id, name=name, slug=slug)
    make_agent_config(db_session, p.id)
    return p


# ── revocation service ──────────────────────────────────────────────────────


def test_is_revoked_false_for_a_clean_token(client, db_session):
    from datetime import datetime

    assert is_revoked("jti-1", "persona-1", datetime.utcnow()) is False


def test_revoke_jti_blacklists_one_token(client, db_session):
    from datetime import datetime

    revoke_jti("jti-x", "persona-1", "co-1", "test")
    assert is_revoked("jti-x", "persona-1", datetime.utcnow()) is True
    assert is_revoked("jti-y", "persona-1", datetime.utcnow()) is False


def test_revoke_all_kills_tokens_issued_before_the_marker(client, db_session):
    from datetime import datetime, timedelta

    old = datetime.utcnow() - timedelta(minutes=5)
    revoke_all("persona-1", "co-1", "laptop lost")
    # a token minted 5 min ago is dead
    assert is_revoked("any", "persona-1", old) is True
    # a token minted now (after the marker) survives
    assert (
        is_revoked("any", "persona-1", datetime.utcnow() + timedelta(seconds=1))
        is False
    )
    # a different persona is unaffected
    assert is_revoked("any", "persona-2", old) is False


# ── /workstation/persona-token → pair ───────────────────────────────────────


def test_mint_returns_access_and_refresh(auth_client, db_session):
    agent = _agent(db_session, auth_client._test_company)
    db_session.commit()

    body = auth_client.post(
        "/workstation/persona-token", json={"personnel_id": agent.id}
    ).json()
    assert body["token"] and body["refresh_token"]
    assert body["expires_in"] > 0
    principal = decode_persona_token(body["token"], expected_audience=AUD_GATEWAY)
    assert principal.persona_id == agent.id
    assert principal.jti


# ── /workstation/persona-token/refresh ──────────────────────────────────────


def test_refresh_rotates_and_revokes_the_old_token(auth_client, db_session):
    agent = _agent(db_session, auth_client._test_company)
    db_session.commit()
    pair = auth_client.post(
        "/workstation/persona-token", json={"personnel_id": agent.id}
    ).json()

    time.sleep(1)  # ensure a distinct iat
    r = auth_client.post(
        "/workstation/persona-token/refresh",
        json={"refresh_token": pair["refresh_token"]},
    )
    assert r.status_code == 201
    fresh = r.json()
    assert fresh["token"] != pair["token"]
    assert fresh["refresh_token"] != pair["refresh_token"]

    # the spent refresh token is now rejected
    again = auth_client.post(
        "/workstation/persona-token/refresh",
        json={"refresh_token": pair["refresh_token"]},
    )
    assert again.status_code == 401


def test_refresh_rejects_an_access_token(auth_client, db_session):
    agent = _agent(db_session, auth_client._test_company)
    db_session.commit()
    access = create_persona_token(agent.id, auth_client._test_company.id)
    r = auth_client.post(
        "/workstation/persona-token/refresh", json={"refresh_token": access}
    )
    assert r.status_code == 401


def test_refreshed_access_token_works_on_the_gateway(auth_client, db_session):
    agent = _agent(db_session, auth_client._test_company)
    db_session.commit()
    pair = auth_client.post(
        "/workstation/persona-token", json={"personnel_id": agent.id}
    ).json()
    fresh = auth_client.post(
        "/workstation/persona-token/refresh",
        json={"refresh_token": pair["refresh_token"]},
    ).json()

    r = auth_client.get(
        "/v1/models", headers={"Authorization": f"Bearer {fresh['token']}"}
    )
    assert r.status_code == 200


# ── /workstation/persona-token/revoke + enforcement in deps ─────────────────


def test_revoke_all_blocks_an_existing_token_on_the_gateway(auth_client, db_session):
    agent = _agent(db_session, auth_client._test_company)
    db_session.commit()
    token = create_persona_token(agent.id, auth_client._test_company.id)

    ok = auth_client.get("/v1/models", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200

    time.sleep(1)
    rv = auth_client.post(
        "/workstation/persona-token/revoke", json={"personnel_id": agent.id}
    )
    assert rv.status_code == 202

    blocked = auth_client.get(
        "/v1/models", headers={"Authorization": f"Bearer {token}"}
    )
    assert blocked.status_code == 401


def test_revoke_rejects_unowned_persona(client, db_session):
    from services.auth import create_access_token
    from tests.conftest import make_company, make_member

    co = make_company(db_session)
    u = make_user(db_session, email="z@z.com", name="Z")
    make_member(db_session, u.id, co.id, role="user")
    agent = _agent(db_session, co)
    db_session.commit()

    client.headers.update({"Authorization": f"Bearer {create_access_token(u.id)}"})
    r = client.post(
        "/workstation/persona-token/revoke", json={"personnel_id": agent.id}
    )
    assert r.status_code == 403


def test_revoke_needs_auth(client, db_session):
    assert (
        client.post(
            "/workstation/persona-token/revoke", json={"personnel_id": "x"}
        ).status_code
        == 401
    )


def test_persona_can_self_revoke_with_its_own_token(client, db_session):
    from tests.conftest import make_company

    co = make_company(db_session)
    agent = _agent(db_session, co)
    db_session.commit()
    token = create_persona_token(agent.id, co.id)

    time.sleep(1)
    r = client.post(
        "/workstation/persona-token/revoke",
        json={"personnel_id": agent.id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 202
    # the token that triggered the revoke is now itself rejected
    blocked = client.get("/v1/models", headers={"Authorization": f"Bearer {token}"})
    assert blocked.status_code == 401


def test_persona_token_cannot_revoke_a_different_persona(client, db_session):
    from tests.conftest import make_company

    co = make_company(db_session)
    mine = _agent(db_session, co, name="Mine", slug="mine")
    other = _agent(db_session, co, name="Other", slug="other")
    db_session.commit()
    my_token = create_persona_token(mine.id, co.id)

    r = client.post(
        "/workstation/persona-token/revoke",
        json={"personnel_id": other.id},
        headers={"Authorization": f"Bearer {my_token}"},
    )
    assert r.status_code == 403


def test_revoked_refresh_token_cannot_refresh(auth_client, db_session):
    agent = _agent(db_session, auth_client._test_company)
    db_session.commit()
    refresh = create_persona_refresh_token(agent.id, auth_client._test_company.id)

    time.sleep(1)
    revoke_all(agent.id, auth_client._test_company.id, "test")

    r = auth_client.post(
        "/workstation/persona-token/refresh", json={"refresh_token": refresh}
    )
    assert r.status_code == 401
