"""Model routing + custom OpenAI-compatible endpoints (ADR-0016)."""

import json
from unittest.mock import patch

import pytest

from core.security import encrypt
from models import ProviderKey
from services.gateway_auth import create_persona_token
from services.model_routing import (
    ModelRoutingError,
    infer_provider,
    resolve_model,
    split_model_reference,
)
from tests.conftest import make_agent_config, make_personnel, make_provider_key


def _custom(session, slug="vllm", base_url="http://vllm.local:8000/v1", models=()):
    row = ProviderKey(
        provider=f"custom:{slug}",
        encrypted_key=encrypt("tok-custom"),
        status="active",
        base_url=base_url,
        display_name=slug,
        models_json=json.dumps(list(models)),
    )
    session.add(row)
    session.flush()
    return row


# ── infer / split ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-4-6", "anthropic"),
        ("gpt-4o-mini", "openai"),
        ("o3-mini", "openai"),
        ("gemini-2.5-pro", "google"),
        ("mistral-large-latest", "mistral"),
        ("codestral-latest", "mistral"),
        ("qwen-max", "qwen"),
        ("deepseek-v3", "qwen"),
        ("llama-3.1-70b", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_infer_provider(model, expected):
    assert infer_provider(model) == expected


def test_split_model_reference_only_for_known_prefix():
    known = {"custom:vllm", "ollama"}
    assert split_model_reference("custom:vllm/meta-llama/Llama-3.1-8B", known) == (
        "custom:vllm",
        "meta-llama/Llama-3.1-8B",
    )
    assert split_model_reference("ollama/llama3.1", known) == ("ollama", "llama3.1")
    # A slash inside a plain model id is not a reference.
    assert split_model_reference("meta-llama/Llama-3.1-8B", known) == (
        None,
        "meta-llama/Llama-3.1-8B",
    )


# ── resolve_model ────────────────────────────────────────────────────────────


def test_resolve_prefix_inferred_openai(db_session):
    make_provider_key(db_session, provider="openai", plain_key="sk-o")
    db_session.commit()
    r = resolve_model("gpt-4o-mini")
    assert (r.provider, r.protocol, r.model) == ("openai", "openai", "gpt-4o-mini")
    assert r.api_key == "sk-o"
    assert r.base_url == "https://api.openai.com/v1"


def test_resolve_native_protocols(db_session):
    make_provider_key(db_session, provider="anthropic", plain_key="sk-a")
    db_session.commit()
    r = resolve_model("claude-sonnet-4-6")
    assert r.protocol == "anthropic"
    assert r.base_url is None


def test_resolve_mistral_no_longer_falls_to_google(db_session):
    make_provider_key(db_session, provider="mistral", plain_key="sk-m")
    db_session.commit()
    r = resolve_model("mistral-large-latest")
    assert r.provider == "mistral"
    assert r.base_url == "https://api.mistral.ai/v1"


def test_resolve_explicit_provider_wins(db_session):
    _custom(db_session)
    db_session.commit()
    # A gpt-looking name served by the org's own endpoint.
    r = resolve_model("gpt-4o-mini", provider="custom:vllm")
    assert r.provider == "custom:vllm"
    assert r.base_url == "http://vllm.local:8000/v1"
    assert r.api_key == "tok-custom"


def test_resolve_model_reference_strips_prefix(db_session):
    _custom(db_session)
    db_session.commit()
    r = resolve_model("custom:vllm/meta-llama/Llama-3.1-8B")
    assert r.provider == "custom:vllm"
    assert r.model == "meta-llama/Llama-3.1-8B"


def test_resolve_bare_model_found_in_endpoint_list(db_session):
    _custom(db_session, models=["llama-3.1-70b"])
    db_session.commit()
    r = resolve_model("llama-3.1-70b")
    assert r.provider == "custom:vllm"


def test_resolve_local_provider_uses_stored_base_url(db_session):
    db_session.add(
        ProviderKey(
            provider="ollama",
            encrypted_key=encrypt("local"),
            status="active",
            base_url="http://gpu-box:11434/v1",
        )
    )
    db_session.commit()
    r = resolve_model("llama3.1", provider="ollama")
    assert r.base_url == "http://gpu-box:11434/v1"


def test_resolve_no_cross_provider_fallback(db_session):
    # Only an Anthropic key: a GPT model must not be sent to Anthropic.
    make_provider_key(db_session, provider="anthropic")
    db_session.commit()
    with pytest.raises(ModelRoutingError, match="openai"):
        resolve_model("gpt-4o")


def test_resolve_inactive_endpoint_is_ignored(db_session):
    row = _custom(db_session, models=["llama-3.1-70b"])
    row.status = "invalid"
    db_session.commit()
    with pytest.raises(ModelRoutingError):
        resolve_model("llama-3.1-70b")


# ── custom endpoint API ─────────────────────────────────────────────────────


def test_create_custom_endpoint_lists_models(auth_client):
    with patch(
        "api.providers.list_openai_compatible_models", return_value=["m-a", "m-b"]
    ):
        r = auth_client.post(
            "/providers/custom",
            json={
                "name": "Our vLLM",
                "base_url": "https://llm.example.com/v1/chat/completions",
                "api_key": "tok",
            },
        )
    assert r.status_code == 201
    body = r.json()
    assert body["provider"] == "custom:our-vllm"
    assert body["base_url"] == "https://llm.example.com/v1"
    assert body["status"] == "active"
    assert body["models"] == ["m-a", "m-b"]
    assert body["has_key"] is True

    listed = auth_client.get("/providers/custom").json()
    assert [e["slug"] for e in listed] == ["our-vllm"]

    with patch("services.provider_service.fetch_live_models", return_value=None):
        models = auth_client.get("/providers/models").json()
    assert {"provider": "custom:our-vllm", "id": "m-a"}.items() <= next(
        m for m in models if m["id"] == "m-a"
    ).items()


def test_create_custom_endpoint_falls_back_to_completion_probe(auth_client):
    with (
        patch("api.providers.list_openai_compatible_models", return_value=None),
        patch("api.providers.probe_chat_completion", return_value=True) as probe,
    ):
        r = auth_client.post(
            "/providers/custom",
            json={
                "name": "gw",
                "base_url": "http://gw.internal",
                "models": ["house-model"],
            },
        )
    assert r.status_code == 201
    assert r.json()["status"] == "active"
    assert r.json()["models"] == ["house-model"]
    assert r.json()["has_key"] is False
    probe.assert_called_once_with("http://gw.internal", "", "house-model")


def test_create_custom_endpoint_unreachable_is_invalid(auth_client):
    with patch("api.providers.list_openai_compatible_models", return_value=None):
        r = auth_client.post(
            "/providers/custom", json={"name": "down", "base_url": "http://down"}
        )
    assert r.status_code == 201
    assert r.json()["status"] == "invalid"


def test_create_custom_endpoint_rejects_bad_url(auth_client):
    r = auth_client.post(
        "/providers/custom", json={"name": "x", "base_url": "ftp://nope"}
    )
    assert r.status_code == 422


def test_delete_custom_endpoint_named_key(auth_client):
    # "key" must not collide with DELETE /providers/{provider}/key.
    with patch("api.providers.list_openai_compatible_models", return_value=[]):
        auth_client.post(
            "/providers/custom", json={"name": "key", "base_url": "http://k"}
        )
    assert auth_client.delete("/providers/custom/key").status_code == 204
    assert auth_client.get("/providers/custom").json() == []


# ── AgentConfig.provider ─────────────────────────────────────────────────────


def test_agent_config_provider_set_and_clear(auth_client, db_session):
    co = auth_client._test_company
    person = make_personnel(db_session, co.id, name="Ada", slug="ada")
    make_agent_config(db_session, person.id, model="llama-3.1-70b")
    db_session.commit()

    r = auth_client.patch(
        f"/personnel/{person.id}/agent-config", json={"provider": "custom:vllm"}
    )
    assert r.status_code == 200
    assert r.json()["provider"] == "custom:vllm"

    # Omitting provider leaves it; sending null clears it.
    r = auth_client.patch(
        f"/personnel/{person.id}/agent-config", json={"status": "active"}
    )
    assert r.json()["provider"] == "custom:vllm"
    r = auth_client.patch(
        f"/personnel/{person.id}/agent-config", json={"provider": None}
    )
    assert r.json()["provider"] is None


# ── gateway ──────────────────────────────────────────────────────────────────


def test_gateway_routes_custom_reference_and_strips_prefix(auth_client, db_session):
    from tests.test_gateway import _FakeAsyncClient

    co = auth_client._test_company
    person = make_personnel(db_session, co.id, name="Ada", slug="ada")
    make_agent_config(db_session, person.id, model="qwen-turbo")
    _custom(db_session)
    db_session.commit()
    token = create_persona_token(person.id, co.id)

    with patch("api.gateway.httpx.AsyncClient", _FakeAsyncClient):
        r = auth_client.post(
            "/v1/chat/completions",
            json={
                "model": "custom:vllm/meta-llama/Llama-3.1-8B",
                "messages": [{"role": "user", "content": "selam"}],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    call = _FakeAsyncClient.last_call
    assert call["url"] == "http://vllm.local:8000/v1/chat/completions"
    assert call["json"]["model"] == "meta-llama/Llama-3.1-8B"
    assert call["headers"]["Authorization"] == "Bearer tok-custom"
