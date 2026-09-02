"""Workstation LLM Gateway (ADR-0004) — persona tokens + OpenAI-compatible proxy."""

import json
from unittest.mock import patch

import pytest
from sqlmodel import select

from models import AuditLog
from services.gateway_auth import (
    AUD_AUDIT,
    AUD_GATEWAY,
    create_persona_token,
    decode_persona_token,
)
from tests.conftest import (
    make_agent_config,
    make_personnel,
    make_provider_key,
)

# ── gateway_auth unit ─────────────────────────────────────────────────────────


def test_persona_token_roundtrip():
    tok = create_persona_token("p1", "c1", scope="dept:eng")
    principal = decode_persona_token(tok, expected_audience=AUD_GATEWAY)
    assert principal.persona_id == "p1"
    assert principal.company_id == "c1"
    assert principal.scope == "dept:eng"


def test_persona_token_wrong_audience_rejected():
    tok = create_persona_token("p1", "c1", audience=AUD_GATEWAY)
    with pytest.raises(Exception):
        decode_persona_token(tok, expected_audience=AUD_AUDIT)


def test_persona_token_expired_rejected():
    tok = create_persona_token("p1", "c1", ttl_minutes=-1)
    with pytest.raises(Exception):
        decode_persona_token(tok, expected_audience=AUD_GATEWAY)


# ── persona-token minting endpoint ───────────────────────────────────────────


def test_mint_persona_token_requires_manager(client, db_session):
    r = client.post("/gateway/persona-token", params={"personnel_id": "x"})
    assert r.status_code == 401


def test_mint_persona_token_for_agent(auth_client, db_session):
    co = auth_client._test_company
    person = make_personnel(db_session, co.id, name="Ada", slug="ada")
    make_agent_config(db_session, person.id, model="qwen-turbo")
    db_session.commit()

    r = auth_client.post("/gateway/persona-token", params={"personnel_id": person.id})
    assert r.status_code == 201
    body = r.json()
    assert body["persona_id"] == person.id
    principal = decode_persona_token(body["token"], expected_audience=AUD_GATEWAY)
    assert principal.company_id == co.id


def test_mint_persona_token_missing_personnel(auth_client, db_session):
    r = auth_client.post("/gateway/persona-token", params={"personnel_id": "nope"})
    assert r.status_code == 404


def test_mint_persona_token_personnel_without_agent_config(auth_client, db_session):
    co = auth_client._test_company
    person = make_personnel(db_session, co.id, name="Bob", slug="bob", type="human")
    db_session.commit()
    r = auth_client.post("/gateway/persona-token", params={"personnel_id": person.id})
    assert r.status_code == 400


# ── /v1/chat/completions ─────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload


class _FakeStreamCtx:
    """Stand-in for httpx.AsyncClient.stream()'s async context manager."""

    def __init__(self, chunks: list[bytes], status_code: int = 200):
        self._chunks = chunks
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_raw(self):
        for c in self._chunks:
            yield c


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient (non-streaming `post` + streaming `stream`)."""

    last_call: dict = {}
    stream_chunks: list[bytes] = [
        b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":5,'
        b'"total_tokens":12}}\n\n',
        b"data: [DONE]\n\n",
    ]

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.last_call = {"url": url, "json": json, "headers": headers}
        return _FakeResponse(
            {
                "id": "chatcmpl-fake",
                "choices": [{"message": {"role": "assistant", "content": "merhaba"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            }
        )

    def stream(self, method, url, json=None, headers=None):
        _FakeAsyncClient.last_call = {
            "method": method,
            "url": url,
            "json": json,
            "headers": headers,
        }
        return _FakeStreamCtx(list(_FakeAsyncClient.stream_chunks))


@pytest.fixture()
def agent_persona(auth_client, db_session):
    co = auth_client._test_company
    person = make_personnel(db_session, co.id, name="Ada", slug="ada")
    make_agent_config(db_session, person.id, model="qwen-turbo")
    db_session.commit()
    token = create_persona_token(person.id, co.id)
    return person, token


def _chat_body():
    return {
        "model": "qwen-turbo",
        "messages": [{"role": "user", "content": "selam"}],
    }


def test_chat_completions_needs_persona_token(client):
    r = client.post("/v1/chat/completions", json=_chat_body())
    assert r.status_code == 401


def test_chat_completions_rejects_web_session_jwt(auth_client):
    # auth_client already carries a normal user JWT in its headers.
    r = auth_client.post("/v1/chat/completions", json=_chat_body())
    assert r.status_code == 401


def test_chat_completions_rejects_non_agent_persona(auth_client, db_session):
    co = auth_client._test_company
    human = make_personnel(db_session, co.id, name="Cem", slug="cem", type="human")
    db_session.commit()
    token = create_persona_token(human.id, co.id)
    r = auth_client.post(
        "/v1/chat/completions",
        json=_chat_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_chat_completions_502_when_no_upstream(auth_client, agent_persona):
    _, token = agent_persona
    r = auth_client.post(
        "/v1/chat/completions",
        json=_chat_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 502


def test_chat_completions_forwards_and_audits(auth_client, agent_persona, db_session):
    _, token = agent_persona
    make_provider_key(db_session, provider="qwen", plain_key="sk-upstream")
    db_session.commit()

    with patch("api.gateway.httpx.AsyncClient", _FakeAsyncClient):
        r = auth_client.post(
            "/v1/chat/completions",
            json=_chat_body(),
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "merhaba"

    # upstream URL came from the qwen ProviderKey default base_url
    assert _FakeAsyncClient.last_call["url"].endswith("/chat/completions")
    assert (
        _FakeAsyncClient.last_call["headers"]["Authorization"] == "Bearer sk-upstream"
    )

    # an audit row was written for this call
    rows = db_session.exec(
        select(AuditLog).where(AuditLog.action == "gateway_call")
    ).all()
    assert len(rows) == 1
    details = json.loads(rows[0].details_json)
    assert details["model"] == "qwen-turbo"
    assert details["tokens_in"] == 11
    assert details["tokens_out"] == 3
    assert "prompt_sha256" in details


# ── streaming: parse the usage chunk (ADR-0004) ──────────────────────────────


def test_sse_usage_helper():
    from api.gateway import _sse_usage

    assert _sse_usage(
        b'data: {"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}'
    ) == {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
    assert _sse_usage(b"data: [DONE]") is None
    assert _sse_usage(b": keep-alive comment") is None
    assert _sse_usage(b'data: {"choices":[{"delta":{"content":"x"}}]}') is None
    assert _sse_usage(b"data: not-json") is None
    assert _sse_usage(b'data:  {"usage":{"total_tokens":9}}\r') == {"total_tokens": 9}


def test_streaming_parses_usage_and_meters(auth_client, agent_persona, db_session):
    from models import GatewayUsage

    person, token = agent_persona
    make_provider_key(db_session, provider="qwen", plain_key="sk-upstream")
    db_session.commit()

    with patch("api.gateway.httpx.AsyncClient", _FakeAsyncClient):
        r = auth_client.post(
            "/v1/chat/completions",
            json={**_chat_body(), "stream": True},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert b"[DONE]" in r.content  # raw passthrough intact

    # the client sent no stream_options -> the gateway asked the upstream for usage
    assert _FakeAsyncClient.last_call["json"]["stream_options"] == {
        "include_usage": True
    }

    row = db_session.exec(
        select(AuditLog).where(AuditLog.action == "gateway_call")
    ).all()[-1]
    d = json.loads(row.details_json)
    assert d["streamed"] is True
    assert d["tokens_in"] == 7
    assert d["tokens_out"] == 5

    usage = db_session.exec(
        select(GatewayUsage).where(GatewayUsage.persona_id == person.id)
    ).all()
    assert usage and all(u.tokens_in == 7 and u.tokens_out == 5 for u in usage)


def test_streaming_keeps_client_supplied_stream_options(
    auth_client, agent_persona, db_session
):
    _, token = agent_persona
    make_provider_key(db_session, provider="qwen", plain_key="sk-upstream")
    db_session.commit()

    with patch("api.gateway.httpx.AsyncClient", _FakeAsyncClient):
        auth_client.post(
            "/v1/chat/completions",
            json={
                **_chat_body(),
                "stream": True,
                "stream_options": {"include_usage": False},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert _FakeAsyncClient.last_call["json"]["stream_options"] == {
        "include_usage": False
    }


# ── /policy/decide (ADR-0005) ────────────────────────────────────────────────


def test_policy_decide_needs_persona_token(client):
    r = client.post("/policy/decide", json={"tool": "bash", "args": {"command": "ls"}})
    assert r.status_code == 401


def test_policy_decide_dry_run_reports_without_enforcing(
    auth_client, agent_persona, db_session
):
    _, token = agent_persona
    r = auth_client.post(
        "/policy/decide",
        headers={"Authorization": f"Bearer {token}"},
        json={"tool": "bash", "args": {"command": "rm -rf /"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["effect"] == "deny"  # baseline safety rule
    assert body["mode"] == "dry_run"
    assert body["enforced"] is False

    rows = db_session.exec(
        select(AuditLog).where(AuditLog.action == "policy_decision")
    ).all()
    assert len(rows) == 1
    assert rows[0].entity_name == "bash"


def test_policy_decide_enforce_mode(auth_client, agent_persona, db_session):
    from models import AppConfig

    db_session.add(AppConfig(key="policy.mode", value="enforce"))
    db_session.commit()
    _, token = agent_persona
    r = auth_client.post(
        "/policy/decide",
        headers={"Authorization": f"Bearer {token}"},
        json={"tool": "bash", "args": {"command": "rm -rf /"}},
    )
    body = r.json()
    assert body["effect"] == "deny"
    assert body["enforced"] is True
