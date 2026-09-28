"""
Model routing — which endpoint serves a model (ADR-0016).

One resolver for every LLM caller (web chat runtime, flows, task requests,
session summaries, the workstation gateway). Order:

  1. an explicit provider (AgentConfig.provider), or a `<provider>/<model>`
     reference whose prefix is a configured provider — e.g. `ollama/llama3.1`,
     `custom:vllm/meta-llama/Llama-3.1-70B`;
  2. the provider implied by a well-known model-name prefix (claude-, gpt-, …);
  3. an active custom / local endpoint whose last-seen model list contains the
     model id;
  4. the legacy default (`detect_provider`, which falls back to Google).

The resolved provider must have an active ProviderKey; there is no silent
fallback to another provider's key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlmodel import select

from core.security import decrypt
from database import get_session
from models import ProviderKey
from services.provider_service import LOCAL_PROVIDERS, is_custom_provider

# Base URLs for providers spoken over the OpenAI protocol, used when the
# ProviderKey row has no explicit base_url.
DEFAULT_OPENAI_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "mistral": "https://api.mistral.ai/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
}

# Providers with their own (non-OpenAI) client in agent_runtime / flow_runner.
_NATIVE_PROTOCOLS = {"anthropic": "anthropic", "google": "google"}


class ModelRoutingError(Exception):
    """No usable endpoint for the requested model."""


@dataclass
class ResolvedModel:
    provider: str  # ProviderKey.provider, e.g. "openai", "ollama", "custom:vllm"
    protocol: str  # "anthropic" | "google" | "openai"
    model: str  # model id to send upstream (reference prefix stripped)
    api_key: str
    base_url: str | None  # always set for "openai"; native only if configured


def infer_provider(model: str | None) -> str:
    """Provider implied by a well-known model-name prefix, or "" if unknown."""
    m = (model or "").lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3", "dall-e")):
        return "openai"
    if m.startswith("gemini"):
        return "google"
    if m.startswith(("mistral", "codestral")):
        return "mistral"
    if m.startswith(("qwen", "wanx", "flux", "stable-diffusion", "deepseek", "kimi")):
        return "qwen"
    return ""


def _active_rows(session) -> list[ProviderKey]:
    return list(
        session.exec(select(ProviderKey).where(ProviderKey.status == "active")).all()
    )


def _row_models(row: ProviderKey) -> list[str]:
    try:
        data = json.loads(row.models_json or "[]")
    except (ValueError, TypeError):
        return []
    return [m for m in data if isinstance(m, str)]


def split_model_reference(
    model: str, known_providers: set[str]
) -> tuple[str | None, str]:
    """`<provider>/<model>` → (provider, model) when the prefix is a known provider."""
    if "/" in model:
        head, rest = model.split("/", 1)
        if head in known_providers and rest:
            return head, rest
    return None, model


def resolve_model(model: str | None, provider: str | None = None) -> ResolvedModel:
    """Find the endpoint, key and upstream model id for `model`."""
    model = (model or "").strip()
    with get_session() as session:
        active = _active_rows(session)
        by_name = {r.provider: r for r in active}

        if not provider and model:
            ref_provider, ref_model = split_model_reference(model, set(by_name))
            if ref_provider:
                provider, model = ref_provider, ref_model

        if not provider:
            provider = infer_provider(model)

        if not provider and model:
            for row in active:
                if (
                    is_custom_provider(row.provider) or row.provider in LOCAL_PROVIDERS
                ) and model in _row_models(row):
                    provider = row.provider
                    break

        if not provider:
            from services.agent_runtime import detect_provider

            provider = detect_provider(model)

        row = by_name.get(provider)
        if not row:
            raise ModelRoutingError(
                f"No active API key for provider '{provider}'. "
                "Configure it in Settings → AI Sağlayıcılar."
            )

        protocol = _NATIVE_PROTOCOLS.get(provider, "openai")
        # Native providers keep an explicit base_url only if the org set one (the
        # gateway can forward to an OpenAI-compatible proxy in front of them).
        base_url = (
            row.base_url or DEFAULT_OPENAI_BASE_URLS.get(provider) or ""
        ).rstrip("/") or None
        if protocol == "openai" and not base_url:
            raise ModelRoutingError(f"No base URL configured for '{provider}'")

        return ResolvedModel(
            provider=provider,
            protocol=protocol,
            model=model,
            api_key=decrypt(row.encrypted_key) if row.encrypted_key else "",
            base_url=base_url,
        )
