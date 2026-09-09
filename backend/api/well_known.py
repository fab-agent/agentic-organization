"""
`/.well-known/opencode` — the org's opencode config, signed (ADR-0011).

`3pa` fetches this, verifies the Ed25519 signature against a pinned public key,
and writes the `config` into the sandbox's managed opencode settings. Serving it
dynamically means org policy (gateway URL, disabled providers, MCP servers,
enforcement hint) can change without re-provisioning laptops.

Also serves the agent-discovery documents (RFC 9727 / A2A / Auth.md):
`/.well-known/api-catalog`, `/.well-known/agent-card.json`, `/auth.md`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from fastapi import APIRouter, Request, Response

from database import get_session
from models import AppConfig
from services import wellknown_sign
from version import VERSION

router = APIRouter(tags=["well-known"])

# Public origin for the discovery documents. Prefer the operator-set value, then
# an env override, then whatever the request came in on (behind the proxy this is
# the external host once forwarded headers are honoured).
_DEFAULT_PUBLIC_BASE = "https://agent.fab.engineering"
_SOURCE_REPO = "https://github.com/fab-agent/agentic-organization"
_DOCS_URL = "https://docs.fab.engineering"


def public_base_url(request: Request) -> str:
    with get_session() as session:
        configured = _cfg(session, "workstation.base_url")
    env = os.getenv("PUBLIC_BASE_URL") or os.getenv("WORKSTATION_BASE_URL")
    if configured:
        return configured.rstrip("/")
    if env:
        return env.rstrip("/")
    host = request.headers.get("host", "")
    if host and "localhost" not in host and "127.0.0.1" not in host:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        return f"{proto}://{host}"
    return _DEFAULT_PUBLIC_BASE


def _cfg(session, key: str, default: str = "") -> str:
    row = session.get(AppConfig, key)
    return row.value if row and row.value else default


def _build_config(request: Request) -> dict:
    with get_session() as session:
        base_url = _cfg(session, "workstation.base_url") or os.getenv(
            "WORKSTATION_BASE_URL", ""
        )
        if not base_url:
            base_url = str(request.base_url).rstrip("/")
        disabled = [
            p.strip()
            for p in _cfg(session, "workstation.disabled_providers").split(",")
            if p.strip()
        ]
        policy_mode = _cfg(session, "policy.mode", "dry_run")

    # opencode-shaped config (a subset; ADR-0011). The plugin path is resolved
    # inside the sandbox image.
    config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "share": "disabled",
        "plugin": ["/opt/agent-plugin/src/index.ts"],
        # Org operating rules (ADR-0010) — the file is baked into the sandbox
        # image; naming it here keeps the served config a complete drop-in
        # replacement for the baked managed-settings.json (ADR-0011).
        "instructions": ["/etc/opencode/base-prompt.md"],
        "provider": {
            "fabagent": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Agentic Organization Gateway",
                "options": {
                    "baseURL": f"{base_url}/v1",
                    "apiKey": "{env:FABAGENT_TOKEN}",
                },
            }
        },
        "mcp": {
            "fabagent": {
                "type": "remote",
                "url": f"{base_url}/mcp",
                "headers": {"Authorization": "Bearer {env:FABAGENT_TOKEN}"},
            }
        },
        "permission": {
            "webfetch": "ask",
            "bash": {"git *": "allow", "npm *": "allow", "rm *": "ask", "*": "ask"},
        },
        # Org-specific extras the plugin / 3pa read:
        "x-fabagent": {
            "base_url": base_url,
            "disabled_providers": disabled,
            "policy_mode": policy_mode,
            # When enforce, 3pa/plugin should run fail-closed (ADR-0003/0006).
            "fail_closed": policy_mode == "enforce",
        },
    }
    return config


@router.get("/.well-known/opencode")
def well_known_opencode(request: Request):
    config = _build_config(request)
    return {
        "config": config,
        "signature": wellknown_sign.sign_config(config),
        "key_id": wellknown_sign.key_id(),
        "algorithm": "ed25519",
        "issued_at": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/.well-known/opencode/pubkey")
def well_known_pubkey():
    """
    The Ed25519 public key `3pa` pins. During a rotation grace window
    `previous_key_id` is also served so a client pinned to the old key accepts
    the transition and re-pins (ADR-0011).
    """
    return {
        "algorithm": "ed25519",
        "public_key_b64": wellknown_sign.public_key_b64(),
        "key_id": wellknown_sign.key_id(),
        "previous_key_id": wellknown_sign.previous_key_id(),
    }


# ── Agent discovery: RFC 9727 API Catalog / A2A Agent Card / Auth.md ──────────


def _api_catalog(request: Request) -> dict:
    base = public_base_url(request)
    return {
        "linkset": [
            {
                "anchor": base,
                "service-desc": [
                    {
                        "href": f"{base}/openapi.json",
                        "type": "application/json",
                        "title": "Agentic Organization API — OpenAPI 3.1",
                    }
                ],
                "service-doc": [
                    {
                        "href": _SOURCE_REPO,
                        "type": "text/html",
                        "title": "Source, ADRs and self-host guide",
                    },
                    {
                        "href": _DOCS_URL,
                        "type": "text/html",
                        "title": "Documentation",
                    },
                ],
                "service-meta": [
                    {
                        "href": f"{base}/.well-known/agent-card.json",
                        "type": "application/json",
                        "title": "A2A / MCP agent card",
                    },
                    {
                        "href": f"{base}/auth.md",
                        "type": "text/markdown",
                        "title": "Agent authentication & provisioning",
                    },
                ],
                "status": [{"href": f"{base}/health", "type": "application/json"}],
            },
            {
                "anchor": f"{base}/mcp",
                "service-desc": [
                    {
                        "href": f"{base}/.well-known/agent-card.json",
                        "type": "application/json",
                        "title": "MCP endpoint — JSON-RPC 2.0, protocol 2025-06-18",
                    }
                ],
            },
        ]
    }


def _agent_card(request: Request) -> dict:
    base = public_base_url(request)
    mcp = f"{base}/mcp"
    return {
        "protocolVersion": "0.3.0",
        "name": "Agentic Organization",
        "description": (
            "Self-hosted agentic organization management platform. Gives an "
            "agent persona its organizational context — task delegation (A2A), "
            "a working journal, read-only queries against operator-registered "
            "databases, and policy read-back — exposed as MCP tools over a "
            "single JSON-RPC endpoint. Open source; every deployment is operated "
            "independently and issues its own credentials."
        ),
        "version": VERSION,
        "url": mcp,
        "preferredTransport": "JSONRPC",
        "supportedInterfaces": [{"url": mcp, "transport": "JSONRPC"}],
        "additionalInterfaces": [{"url": mcp, "transport": "JSONRPC"}],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
            "extensions": [
                {
                    "uri": "https://modelcontextprotocol.io",
                    "description": (
                        "The endpoint speaks MCP (protocol 2025-06-18): "
                        "initialize, tools/list, tools/call."
                    ),
                }
            ],
        },
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "securitySchemes": {
            "personaToken": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": (
                    "Persona token issued by the deployment operator via "
                    "POST /workstation/persona-token. See /auth.md."
                ),
            }
        },
        "security": [{"personaToken": []}],
        "skills": [
            {
                "id": "org_policies",
                "name": "Read org policies",
                "description": (
                    "Return the company, department and agent-scope policies "
                    "that currently constrain this persona."
                ),
                "tags": ["governance", "policy"],
            },
            {
                "id": "delegate_to_agent",
                "name": "Delegate to another agent",
                "description": (
                    "Hand a sub-task to a specialist agent in the same "
                    "organization and wait for a human-approved result (A2A)."
                ),
                "tags": ["a2a", "delegation"],
            },
            {
                "id": "journal_write",
                "name": "Write to journal",
                "description": "Append a markdown entry to the persona's working journal.",
                "tags": ["memory"],
            },
            {
                "id": "db_query",
                "name": "Query a registered database",
                "description": (
                    "Run a read-only SQL query against a database the operator "
                    "registered for this agent."
                ),
                "tags": ["data"],
            },
            {
                "id": "web_search",
                "name": "Web search",
                "description": "Search the web for a query.",
                "tags": ["research"],
            },
        ],
        "documentationUrl": _SOURCE_REPO,
        "provider": {
            "organization": "Fabrika Yazılım Ticaret Limited Şirketi",
            "url": "https://fab.limited",
        },
    }


_AUTH_MD = """\
# auth.md

`agent.fab.engineering` runs the open-source **Agentic Organization** platform
(<https://github.com/fab-agent/agentic-organization>). It is self-hosted: this
deployment is operated independently and issues its own agent credentials.

## Audience

External and laptop agents that need this organization's context — delegation,
journal, registered-database queries, policy read-back — served as MCP tools at
`POST /mcp` (JSON-RPC 2.0, protocol `2025-06-18`).

## Registration / provisioning

There is no open self-service sign-up. An operator (the responsible human for a
persona) provisions access:

1. `GET /workstation/personas` — operator lists the agent personas they own.
2. `POST /workstation/persona-token` — operator mints a persona token for one
   persona and audience (`gateway` for the LLM gateway, `audit` for the MCP /
   tool-event surface).
3. `POST /workstation/persona-token/refresh` and `.../revoke` — rotate or revoke.

Tokens are short-lived JWTs bound to a persona, company and audience, with
server-side revocation (spent `jti`, per-persona revoke-all marker).

## Using the credential

Send the token as a bearer header on every call:

```
Authorization: Bearer <persona-token>
```

No cookie or query-parameter authentication is accepted.

## OAuth / OIDC

Standard OAuth2 metadata is not published — this deployment has no shared
authorization server. When the operator enables OIDC (`oidc.enabled`), an
external IdP token can be exchanged for a persona token at
`POST /workstation/oidc/exchange`; ask the operator for the IdP issuer and
audience.

## Contact

Fabrika Yazılım Ticaret Limited Şirketi — bilgi@kuntaykunt.com
"""


@router.get("/.well-known/api-catalog")
def well_known_api_catalog(request: Request):
    return Response(
        json.dumps(_api_catalog(request), indent=2),
        media_type="application/linkset+json",
    )


@router.get("/.well-known/agent-card.json")
def well_known_agent_card(request: Request):
    return _agent_card(request)


@router.get("/auth.md")
def auth_md():
    return Response(_AUTH_MD, media_type="text/markdown; charset=utf-8")
