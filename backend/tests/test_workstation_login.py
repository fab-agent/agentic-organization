"""3pa login — persona selection, owner-scoped token, OIDC exchange (ADR-0007)."""

from unittest.mock import patch

from services.gateway_auth import AUD_GATEWAY, decode_persona_token
from tests.conftest import make_agent_config, make_personnel, make_user


def _agent(db_session, company, *, responsible_id=None, name="Ada", slug="ada"):
    p = make_personnel(db_session, company.id, name=name, slug=slug)
    make_agent_config(db_session, p.id, responsible_id=responsible_id)
    return p


# ── personas ────────────────────────────────────────────────────────────────


def test_founder_sees_all_company_agents(auth_client, db_session):
    co = auth_client._test_company
    _agent(db_session, co, name="A1", slug="a1")
    _agent(db_session, co, name="A2", slug="a2")
    db_session.commit()

    r = auth_client.get("/workstation/personas")
    assert r.status_code == 200
    names = {p["name"] for p in r.json()["personas"]}
    assert {"A1", "A2"} <= names


def test_non_manager_sees_only_owned_agents(client, db_session):
    from services.auth import create_access_token
    from tests.conftest import make_company, make_member

    co = make_company(db_session)
    owner = make_user(db_session, email="dev@x.com", name="Dev")
    make_member(db_session, owner.id, co.id, role="user")
    owner_person = make_personnel(
        db_session, co.id, name="Dev", slug="dev-h", type="human"
    )
    owner_person.user_id = owner.id
    db_session.add(owner_person)

    mine = _agent(
        db_session, co, responsible_id=owner_person.id, name="Mine", slug="mine"
    )
    _agent(db_session, co, name="NotMine", slug="notmine")
    db_session.commit()

    client.headers.update({"Authorization": f"Bearer {create_access_token(owner.id)}"})
    personas = client.get("/workstation/personas").json()["personas"]
    assert [p["name"] for p in personas] == ["Mine"]
    assert personas[0]["personnel_id"] == mine.id


# ── persona-token ───────────────────────────────────────────────────────────


def test_mint_persona_token_for_owned_agent(auth_client, db_session):
    co = auth_client._test_company
    agent = _agent(db_session, co)
    db_session.commit()

    r = auth_client.post("/workstation/persona-token", json={"personnel_id": agent.id})
    assert r.status_code == 201
    principal = decode_persona_token(r.json()["token"], expected_audience=AUD_GATEWAY)
    assert principal.persona_id == agent.id
    assert principal.company_id == co.id


def test_mint_persona_token_rejects_unowned(client, db_session):
    from services.auth import create_access_token
    from tests.conftest import make_company, make_member

    co = make_company(db_session)
    u = make_user(db_session, email="x@x.com", name="X")
    make_member(db_session, u.id, co.id, role="user")
    agent = _agent(db_session, co)
    db_session.commit()

    client.headers.update({"Authorization": f"Bearer {create_access_token(u.id)}"})
    r = client.post("/workstation/persona-token", json={"personnel_id": agent.id})
    assert r.status_code == 403


def test_persona_token_needs_auth(client):
    assert (
        client.post(
            "/workstation/persona-token", json={"personnel_id": "x"}
        ).status_code
        == 401
    )


# ── OIDC exchange ───────────────────────────────────────────────────────────


def test_oidc_exchange_maps_email_to_user(client, db_session):
    make_user(db_session, email="alice@corp.com", name="Alice")
    db_session.commit()

    with patch(
        "services.oidc.verify_id_token",
        return_value={"email": "alice@corp.com", "email_verified": True},
    ):
        r = client.post("/workstation/oidc/exchange", json={"id_token": "fake"})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_oidc_exchange_rejects_unknown_email(client, db_session):
    with patch(
        "services.oidc.verify_id_token",
        return_value={"email": "nobody@corp.com", "email_verified": True},
    ):
        r = client.post("/workstation/oidc/exchange", json={"id_token": "fake"})
    assert r.status_code == 403


def test_oidc_exchange_rejects_when_disabled(client, db_session):
    # verify_id_token raises OIDCError when oidc.enabled is not set
    r = client.post("/workstation/oidc/exchange", json={"id_token": "fake"})
    assert r.status_code == 401
