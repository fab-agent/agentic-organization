"""
`/.well-known/opencode` — the org's opencode config, signed (ADR-0011).

`3pa` fetches this, verifies the Ed25519 signature against a pinned public key,
and writes the `config` into the sandbox's managed opencode settings. Serving it
dynamically means org policy (gateway URL, disabled providers, MCP servers,
enforcement hint) can change without re-provisioning laptops.
"""

from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Request

from database import get_session
from models import AppConfig
from services import wellknown_sign

router = APIRouter(tags=["well-known"])


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
