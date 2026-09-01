"""Workstation LLM Gateway (ADR-0004) — persona tokens + OpenAI-compatible proxy."""

import json
from unittest.mock import patch

import pytest

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


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient in the non-streaming path."""

    last_call: dict = {}

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
    from sqlmodel import select

    from models import AuditLog

    rows = db_session.exec(
        select(AuditLog).where(AuditLog.action == "gateway_call")
    ).all()
    assert len(rows) == 1
    details = json.loads(rows[0].details_json)
    assert details["model"] == "qwen-turbo"
    assert details["tokens_in"] == 11
    assert details["tokens_out"] == 3
    assert "prompt_sha256" in details
