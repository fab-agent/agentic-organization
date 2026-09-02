"""
Backend MCP server (ADR-0001 / ADR-0011) — exposes an agent persona's org
context to opencode as MCP tools, so a developer's laptop agent can delegate
(A2A), write to its journal, query registered databases, read its own policies,
etc. — the same skills the web runtime gives it.

Transport: a single JSON-RPC 2.0 endpoint (`POST /mcp`), persona-token auth.
Methods: `initialize`, `tools/list`, `tools/call`.

opencode config (served via /.well-known/opencode, ADR-0011):
    "mcp": { "fabagent": { "type": "remote", "url": "https://<server>/mcp",
             "headers": { "Authorization": "Bearer {env:FABAGENT_TOKEN}" } } }
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import select

from api.deps import get_persona_audit
from database import get_session
from models import AgentConfig, Skill
from services.agent_runtime import build_tool_definitions, execute_skill
from services.gateway_auth import PersonaPrincipal
from services.policy_engine import applicable_policy_contents, resolve_scope

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSION = "2025-06-18"

# Built-in org tools that don't come from the agent's skill list.
_POLICIES_TOOL = {
    "name": "org_policies",
    "description": "Read the policies that currently apply to this agent "
    "(company + department + agent scope). Call this to check your constraints.",
    "inputSchema": {"type": "object", "properties": {}},
}


def _persona_skills(persona_id: str) -> list[Skill]:
    with get_session() as session:
        cfg = session.exec(
            select(AgentConfig).where(AgentConfig.personnel_id == persona_id)
        ).first()
        if not cfg:
            return []
        return list(session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all())


def _tools_for(persona_id: str) -> list[dict]:
    tools = [_POLICIES_TOOL]
    for td in build_tool_definitions(_persona_skills(persona_id)):
        tools.append(
            {
                "name": td["name"],
                "description": td["description"],
                "inputSchema": td.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return tools


def _rpc_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _handle(msg: dict, principal: PersonaPrincipal) -> dict | None:
    req_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return _rpc_result(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "agentic-organization", "version": "1"},
            },
        )

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None  # notifications get no response

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": _tools_for(principal.persona_id)})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}

        if name == "org_policies":
            c, d, a = resolve_scope(principal.persona_id)
            bodies = applicable_policy_contents(c, d, a)
            text = "\n\n---\n\n".join(bodies) if bodies else "No policies apply."
            return _rpc_result(req_id, {"content": [{"type": "text", "text": text}]})

        skills = _persona_skills(principal.persona_id)
        if not any(s.name.replace(" ", "_").lower() == name for s in skills):
            return _rpc_error(req_id, -32602, f"Unknown tool: {name}")
        try:
            out = await execute_skill(
                name, args, skills, session_id=None, agent_id=principal.persona_id
            )
        except Exception as e:  # noqa: BLE001
            return _rpc_result(
                req_id,
                {
                    "content": [{"type": "text", "text": f"[error] {e}"}],
                    "isError": True,
                },
            )
        return _rpc_result(req_id, {"content": [{"type": "text", "text": str(out)}]})

    return _rpc_error(req_id, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_endpoint(
    request: Request, principal: PersonaPrincipal = Depends(get_persona_audit)
):
    """JSON-RPC 2.0 — a single message or a batch array."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    if isinstance(payload, list):
        results = await asyncio.gather(*(_handle(m, principal) for m in payload))
        return [r for r in results if r is not None]
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="expected a JSON-RPC object")
    result = await _handle(payload, principal)
    return result if result is not None else {"jsonrpc": "2.0"}
