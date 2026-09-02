"""Workstation tool-event ingest (ADR-0001 plugin surface, ADR-0006 audit)."""

import json

from sqlmodel import select

from models import AuditLog
from services.gateway_auth import AUD_AUDIT, create_persona_token
from tests.conftest import make_agent_config, make_personnel


def _persona(db_session, company):
    person = make_personnel(db_session, company.id, name="Ada", slug="ada")
    make_agent_config(db_session, person.id, model="qwen-turbo")
    db_session.commit()
    return person


def test_tool_event_needs_persona_token(client):
    r = client.post("/workstation/tool-event", json={"phase": "before", "tool": "bash"})
    assert r.status_code == 401


def test_tool_event_rejects_web_jwt(auth_client):
    r = auth_client.post(
        "/workstation/tool-event", json={"phase": "before", "tool": "bash"}
    )
    assert r.status_code == 401


def test_tool_event_written_to_audit(auth_client, db_session):
    person = _persona(db_session, auth_client._test_company)
    token = create_persona_token(person.id, auth_client._test_company.id)

    r = auth_client.post(
        "/workstation/tool-event",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "phase": "before",
            "tool": "bash",
            "session_ref": "sess_123",
            "args_preview": {"command": "git status"},
            "client_ts": "2026-09-01T18:00:00Z",
        },
    )
    assert r.status_code == 202
    assert r.json() == {"accepted": True}

    rows = db_session.exec(
        select(AuditLog).where(AuditLog.action == "tool_event")
    ).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.entity_name == "bash"
    assert row.entity_id == person.id
    assert row.company_id == auth_client._test_company.id
    details = json.loads(row.details_json)
    assert details["phase"] == "before"
    assert details["session_ref"] == "sess_123"
    assert "git status" in details["args_preview"]


def test_tool_event_audit_only_audience_also_works(auth_client, db_session):
    person = _persona(db_session, auth_client._test_company)
    token = create_persona_token(
        person.id, auth_client._test_company.id, audience=AUD_AUDIT
    )
    r = auth_client.post(
        "/workstation/tool-event",
        headers={"Authorization": f"Bearer {token}"},
        json={"phase": "after", "tool": "webfetch", "result_preview": "200 OK"},
    )
    assert r.status_code == 202
