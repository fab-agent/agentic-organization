"""Tamper-evident, per-tenant audit chain (ADR-0006)."""

from services import audit_chain
from services.gateway_auth import create_persona_token
from tests.conftest import make_agent_config, make_personnel

CO = "co-1"


def _append_a_few(n=5, company_id=CO):
    for i in range(n):
        audit_chain.append(
            actor_type="agent",
            actor_id=f"agent-{i}",
            company_id=company_id,
            action="tool_event",
            target="bash",
            reason="before",
            payload={"i": i},
        )


def test_chain_links_and_verifies(client, db_session):
    _append_a_few(6)
    result = audit_chain.verify(CO)
    assert result["ok"] is True
    assert result["count"] == 6
    assert len(result["head"]) == 64


def test_first_event_links_to_genesis(client, db_session):
    ev = audit_chain.append(actor_type="system", action="startup", company_id=CO)
    assert ev.seq == 1
    assert ev.chain_key == CO
    assert ev.prev_hash == audit_chain.GENESIS_HASH


def test_sequence_is_monotonic_within_a_chain(client, db_session):
    seqs = [
        audit_chain.append(actor_type="system", action="x", company_id=CO).seq
        for _ in range(4)
    ]
    assert seqs == [1, 2, 3, 4]


def test_chains_are_isolated_per_tenant(client, db_session):
    _append_a_few(3, company_id="co-A")
    _append_a_few(2, company_id="co-B")
    a = audit_chain.verify("co-A")
    b = audit_chain.verify("co-B")
    assert a["count"] == 3 and b["count"] == 2
    assert a["head"] != b["head"]

    allr = audit_chain.verify_all()
    assert allr["ok"] is True
    assert set(allr["chains"]) == {"co-A", "co-B"}


def test_events_without_company_go_to_global_chain(client, db_session):
    audit_chain.append(actor_type="system", action="startup")
    r = audit_chain.verify()  # no company_id → global
    assert r["chain_key"] == audit_chain.GLOBAL_CHAIN
    assert r["count"] == 1


def test_verify_detects_modified_payload(client, db_session):
    from models import AuditEvent

    _append_a_few(4)
    row = db_session.get(AuditEvent, (CO, 3))
    row.payload_json = '{"i": 999}'  # tamper, without recomputing the hash
    db_session.add(row)
    db_session.commit()

    result = audit_chain.verify(CO)
    assert result["ok"] is False
    assert result["broken_at"] == 3
    assert "altered" in result["detail"]


def test_verify_detects_deleted_row(client, db_session):
    from models import AuditEvent

    _append_a_few(5)
    db_session.delete(db_session.get(AuditEvent, (CO, 3)))
    db_session.commit()

    result = audit_chain.verify(CO)
    assert result["ok"] is False
    assert result["broken_at"] == 4  # row 4 now sits where seq 3 is expected


def test_record_also_writes_legacy_auditlog(client, db_session):
    from sqlmodel import select

    from models import AuditLog

    audit_chain.record(
        actor_type="agent",
        actor_id="a1",
        company_id=CO,
        action="policy_decision",
        target="bash",
        reason="deny (enforce)",
        payload={"effect": "deny"},
    )
    logs = db_session.exec(
        select(AuditLog).where(AuditLog.action == "policy_decision")
    ).all()
    assert len(logs) == 1
    assert logs[0].entity_name == "bash"
    assert audit_chain.verify(CO)["ok"] is True


# ── endpoints ───────────────────────────────────────────────────────────────


def _agent_token(auth_client, db_session):
    co = auth_client._test_company
    person = make_personnel(db_session, co.id, name="Ada", slug="ada")
    make_agent_config(db_session, person.id, model="qwen-turbo")
    db_session.commit()
    return create_persona_token(person.id, co.id), person.id


def test_audit_ingest_batch(auth_client, db_session):
    token, persona_id = _agent_token(auth_client, db_session)
    r = auth_client.post(
        "/audit/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {"action": "sandbox_start", "target": "my-project"},
                {"action": "heartbeat", "payload": {"digest": "abc"}},
                {"target": "no-action-ignored"},
            ]
        },
    )
    assert r.status_code == 202
    assert r.json() == {"accepted": 2}
    assert audit_chain.verify(auth_client._test_company.id)["count"] == 2


def test_audit_ingest_needs_persona_token(client):
    r = client.post("/audit/ingest", json={"events": []})
    assert r.status_code == 401


def test_chain_verify_endpoint(client, auth_client, db_session):
    assert client.post("/audit/chain/verify").status_code in (401, 405)
    audit_chain.append(actor_type="system", action="x", company_id="co-x")
    r = auth_client.get("/audit/chain/verify")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "co-x" in r.json()["chains"]

    r2 = auth_client.get("/audit/chain/verify", params={"company_id": "co-x"})
    assert r2.json()["ok"] is True and r2.json()["count"] == 1
