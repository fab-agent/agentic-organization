"""`3pa` heartbeat / policy / audit-verify workstation endpoints (ADR-0009)."""

from services.gateway_auth import create_persona_token
from tests.conftest import make_agent_config, make_personnel


def _persona(db_session, company):
    p = make_personnel(db_session, company.id, name="Ada", slug="ada")
    make_agent_config(db_session, p.id, model="qwen-turbo")
    db_session.commit()
    return p, create_persona_token(p.id, company.id)


# ── /workstation/heartbeat ──────────────────────────────────────────────────


def test_heartbeat_needs_persona_token(client):
    assert client.post("/workstation/heartbeat", json={}).status_code == 401


def test_heartbeat_upserts_and_returns_policy_mode(auth_client, db_session):
    from models import PersonaHeartbeat

    person, token = _persona(db_session, auth_client._test_company)

    r = auth_client.post(
        "/workstation/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_ref": "s1", "opencode_version": "1.18.26"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["ok"] is True
    assert body["policy_mode"] == "dry_run"  # default
    assert body["fail_closed"] is False

    row = db_session.get(PersonaHeartbeat, person.id)
    assert row and row.opencode_version == "1.18.26" and row.session_ref == "s1"

    # second ping updates the same row
    first_seen = row.last_seen
    auth_client.post(
        "/workstation/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_ref": "s2"},
    )
    db_session.refresh(row)
    assert row.session_ref == "s2"
    assert row.last_seen >= first_seen


def test_heartbeat_reflects_enforce_mode(auth_client, db_session):
    from models import AppConfig

    _, token = _persona(db_session, auth_client._test_company)
    db_session.add(AppConfig(key="policy.mode", value="enforce"))
    db_session.commit()

    body = auth_client.post(
        "/workstation/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    ).json()
    assert body["policy_mode"] == "enforce"
    assert body["fail_closed"] is True


# ── /workstation/policy ─────────────────────────────────────────────────────


def test_policy_endpoint_returns_ruleset(auth_client, db_session):
    _, token = _persona(db_session, auth_client._test_company)
    r = auth_client.get(
        "/workstation/policy", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "dry_run"
    assert body["default_effect"] == "allow"
    # baseline safety rules are always present
    ids = {rule.get("id") for rule in body["rules"]}
    assert "baseline:rm-rf-root" in ids
    assert "baseline:untrusted-high-risk" in ids


def test_policy_endpoint_includes_org_rules(auth_client, db_session):
    from models import Policy

    _, token = _persona(db_session, auth_client._test_company)
    db_session.add(
        Policy(
            company_id=auth_client._test_company.id,
            name="No curl",
            slug="no-curl",
            scope="company",
            is_active=True,
            content='```policy\n[{"id":"org:no-curl","match":{"tool":"bash","args":{"command":"*curl*"}},"effect":"ask","reason":"x"}]\n```',
        )
    )
    db_session.commit()

    body = auth_client.get(
        "/workstation/policy", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert body["org_policy_count"] == 1
    assert any(r.get("id") == "org:no-curl" for r in body["rules"])


# ── /workstation/audit/verify ───────────────────────────────────────────────


def test_audit_verify_persona_scoped(auth_client, db_session):
    from services import audit_chain

    _, token = _persona(db_session, auth_client._test_company)
    audit_chain.record(
        actor_type="agent",
        actor_id="x",
        company_id=auth_client._test_company.id,
        action="tool_event",
        target="bash",
        reason="before",
    )

    r = auth_client.get(
        "/workstation/audit/verify", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["chain_key"] == auth_client._test_company.id
    assert body["count"] >= 1
