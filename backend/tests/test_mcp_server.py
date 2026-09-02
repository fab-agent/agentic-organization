"""Backend MCP server (ADR-0001) — JSON-RPC over POST /mcp."""

import json

from services.gateway_auth import create_persona_token
from tests.conftest import make_agent_config, make_personnel


def _persona(auth_client, db_session):
    co = auth_client._test_company
    person = make_personnel(db_session, co.id, name="Ada", slug="ada")
    cfg = make_agent_config(db_session, person.id)
    db_session.commit()
    return create_persona_token(person.id, co.id), person, cfg


def _rpc(client, token, method, params=None, req_id=1):
    return client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}},
    )


def test_mcp_needs_persona_token(client):
    assert (
        client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        ).status_code
        == 401
    )


def test_initialize(auth_client, db_session):
    token, *_ = _persona(auth_client, db_session)
    r = _rpc(auth_client, token, "initialize")
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["serverInfo"]["name"] == "agentic-organization"
    assert "protocolVersion" in body["result"]


def test_tools_list_includes_org_policies(auth_client, db_session):
    token, *_ = _persona(auth_client, db_session)
    tools = _rpc(auth_client, token, "tools/list").json()["result"]["tools"]
    assert any(t["name"] == "org_policies" for t in tools)
    for t in tools:
        assert "inputSchema" in t


def test_tools_list_includes_agent_skills(auth_client, db_session):
    token, person, cfg = _persona(auth_client, db_session)
    import models

    db_session.add(
        models.Skill(
            agent_id=cfg.id,
            name="journal write",
            version="1",
            skill_type="builtin",
            config_json=json.dumps({"function_name": "journal_write"}),
        )
    )
    db_session.commit()

    tools = _rpc(auth_client, token, "tools/list").json()["result"]["tools"]
    assert any(t["name"] == "journal_write" for t in tools)


def test_call_org_policies_returns_applicable(auth_client, db_session):
    token, person, cfg = _persona(auth_client, db_session)
    import models

    p = models.Policy(
        company_id=person.company_id,
        scope="company",
        name="No secrets",
        slug="no-secrets",
        content="Never exfiltrate credentials.",
    )
    db_session.add(p)
    db_session.commit()

    r = _rpc(
        auth_client, token, "tools/call", {"name": "org_policies", "arguments": {}}
    )
    text = r.json()["result"]["content"][0]["text"]
    assert "exfiltrate" in text


def test_call_unknown_tool_errors(auth_client, db_session):
    token, *_ = _persona(auth_client, db_session)
    r = _rpc(auth_client, token, "tools/call", {"name": "nope", "arguments": {}})
    assert r.json()["error"]["code"] == -32602


def test_unknown_method(auth_client, db_session):
    token, *_ = _persona(auth_client, db_session)
    r = _rpc(auth_client, token, "does/notexist")
    assert r.json()["error"]["code"] == -32601


def test_notification_gets_no_response_body(auth_client, db_session):
    token, *_ = _persona(auth_client, db_session)
    r = auth_client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert r.status_code == 200
