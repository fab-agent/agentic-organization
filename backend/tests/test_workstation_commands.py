"""Signed command channel (ADR-0010 layer 5)."""

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from services import wellknown_sign
from services.gateway_auth import create_persona_token
from tests.conftest import make_agent_config, make_personnel


def _agent(db_session, company, name="Ada", slug="ada"):
    p = make_personnel(db_session, company.id, name=name, slug=slug)
    make_agent_config(db_session, p.id, model="qwen-turbo")
    db_session.commit()
    return p, create_persona_token(p.id, company.id)


def test_issue_needs_auth(client):
    assert (
        client.post(
            "/workstation/commands", json={"personnel_id": "x", "kind": "stop"}
        ).status_code
        == 401
    )


def test_issue_rejects_unknown_kind(auth_client, db_session):
    agent, _ = _agent(db_session, auth_client._test_company)
    r = auth_client.post(
        "/workstation/commands", json={"personnel_id": agent.id, "kind": "selfdestruct"}
    )
    assert r.status_code == 422


def test_owner_issues_persona_polls_verifies(auth_client, db_session):
    agent, token = _agent(db_session, auth_client._test_company)

    r = auth_client.post(
        "/workstation/commands",
        json={"personnel_id": agent.id, "kind": "message", "payload": {"text": "hi"}},
    )
    assert r.status_code == 201

    poll = auth_client.get(
        "/workstation/commands", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert len(poll["commands"]) == 1
    wrapped = poll["commands"][0]
    cmd = wrapped["command"]
    assert cmd["kind"] == "message" and cmd["payload"] == {"text": "hi"}
    assert cmd["issued_by"].startswith("user:")

    # signature verifies over the canonical command JSON
    pub = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(
            auth_client.get("/.well-known/opencode/pubkey").json()["public_key_b64"]
        )
    )
    pub.verify(
        base64.b64decode(wrapped["signature"]),
        wellknown_sign.canonical(cmd).encode(),
    )

    # a second poll is empty (marked delivered)
    poll2 = auth_client.get(
        "/workstation/commands", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert poll2["commands"] == []

    # ack
    ack = auth_client.post(
        f"/workstation/commands/{cmd['id']}/ack",
        headers={"Authorization": f"Bearer {token}"},
        json={"result": "shown"},
    )
    assert ack.status_code == 202
    from models import PersonaCommand

    row = db_session.get(PersonaCommand, cmd["id"])
    assert row.acked_at is not None and row.result == "shown"


def test_persona_can_self_issue(client, db_session):
    from tests.conftest import make_company

    co = make_company(db_session)
    agent, token = _agent(db_session, co)

    r = client.post(
        "/workstation/commands",
        headers={"Authorization": f"Bearer {token}"},
        json={"personnel_id": agent.id, "kind": "stop"},
    )
    assert r.status_code == 201
    assert r.json()["issued_by"] == f"persona:{agent.id}"


def test_persona_cannot_command_another_persona(client, db_session):
    from tests.conftest import make_company

    co = make_company(db_session)
    mine, my_token = _agent(db_session, co, name="Mine", slug="mine")
    other, _ = _agent(db_session, co, name="Other", slug="other")

    r = client.post(
        "/workstation/commands",
        headers={"Authorization": f"Bearer {my_token}"},
        json={"personnel_id": other.id, "kind": "stop"},
    )
    assert r.status_code == 403


def test_ack_scoped_to_own_persona(auth_client, db_session):
    a1, t1 = _agent(db_session, auth_client._test_company, "A1", "a1")
    _a2, t2 = _agent(db_session, auth_client._test_company, "A2", "a2")
    auth_client.post(
        "/workstation/commands", json={"personnel_id": a1.id, "kind": "stop"}
    )
    cmd = auth_client.get(
        "/workstation/commands", headers={"Authorization": f"Bearer {t1}"}
    ).json()["commands"][0]["command"]

    # a2's token cannot ack a1's command
    r = auth_client.post(
        f"/workstation/commands/{cmd['id']}/ack",
        headers={"Authorization": f"Bearer {t2}"},
        json={},
    )
    assert r.status_code == 404
