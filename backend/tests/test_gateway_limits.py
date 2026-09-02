"""LLM gateway guardrails (ADR-0004): allow-list, rate limit, token quota."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from services import gateway_limits as gl
from tests.conftest import make_agent_config, make_personnel, make_provider_key
from tests.test_gateway import _chat_body, _FakeAsyncClient


@pytest.fixture(autouse=True)
def _clear_rl():
    gl._rl_hits.clear()
    yield
    gl._rl_hits.clear()


# ── model allow-list ────────────────────────────────────────────────────────


def test_model_allowlist_default_allows_all():
    gl.check_model_allowed("anything-1", None, None)  # no raise


def test_model_allowlist_blocks_off_list(client, db_session):
    from models import AppConfig

    db_session.add(AppConfig(key="gateway.model_allow", value="qwen-*,gpt-4o*"))
    db_session.commit()
    gl.check_model_allowed("qwen-turbo", None, None)
    with pytest.raises(HTTPException) as e:
        gl.check_model_allowed("claude-opus-4-7", None, None)
    assert e.value.status_code == 403


def test_agents_own_model_always_allowed(client, db_session):
    from models import AppConfig

    db_session.add(AppConfig(key="gateway.model_allow", value="qwen-*"))
    db_session.commit()
    gl.check_model_allowed("claude-sonnet-4-6", None, agent_model="claude-sonnet-4-6")


def test_company_override_beats_global(client, db_session):
    from models import AppConfig

    db_session.add(AppConfig(key="gateway.model_allow", value="*"))
    db_session.add(AppConfig(key="gateway.model_allow:co1", value="qwen-*"))
    db_session.commit()
    with pytest.raises(HTTPException):
        gl.check_model_allowed("gpt-4o", "co1", None)


# ── rate limit ──────────────────────────────────────────────────────────────


def test_rate_limit(client, db_session):
    from models import AppConfig

    db_session.add(AppConfig(key="gateway.rpm_limit", value="3"))
    db_session.commit()
    for _ in range(3):
        gl.check_rate_limit("p1", None)
    with pytest.raises(HTTPException) as e:
        gl.check_rate_limit("p1", None)
    assert e.value.status_code == 429
    gl.check_rate_limit("p2", None)  # a different persona is unaffected


# ── token quota ─────────────────────────────────────────────────────────────


def test_token_quota(client, db_session):
    from models import AppConfig

    db_session.add(AppConfig(key="gateway.daily_token_limit", value="100"))
    db_session.commit()

    gl.check_token_quota("p1", None)  # nothing used yet
    gl.record_usage("p1", None, 60, 50)  # 110 > 100
    with pytest.raises(HTTPException) as e:
        gl.check_token_quota("p1", None)
    assert e.value.status_code == 429


def test_record_usage_increments_day_and_month(client, db_session):
    from datetime import datetime

    from models import GatewayUsage

    gl.record_usage("p1", "co1", 10, 5)
    gl.record_usage("p1", "co1", 3, 2)

    day = datetime.utcnow().strftime("%Y-%m-%d")
    month = datetime.utcnow().strftime("%Y-%m")
    d = db_session.get(GatewayUsage, ("p1", day))
    m = db_session.get(GatewayUsage, ("p1", month))
    assert d.requests == 2 and d.tokens_in == 13 and d.tokens_out == 7
    assert m.requests == 2


# ── end to end through /v1/chat/completions ────────────────────────────────


def _persona(auth_client, db_session, model="qwen-turbo"):
    from services.gateway_auth import create_persona_token

    co = auth_client._test_company
    p = make_personnel(db_session, co.id, name="Ada", slug="ada")
    make_agent_config(db_session, p.id, model=model)
    make_provider_key(db_session, provider="qwen", plain_key="sk-up")
    db_session.commit()
    return create_persona_token(p.id, co.id), p


def test_chat_completions_blocks_disallowed_model(auth_client, db_session):
    from models import AppConfig

    db_session.add(AppConfig(key="gateway.model_allow", value="gpt-4o"))
    db_session.commit()
    token, _ = _persona(auth_client, db_session, model="qwen-turbo")

    with patch("api.gateway.httpx.AsyncClient", _FakeAsyncClient):
        r = auth_client.post(
            "/v1/chat/completions",
            json={**_chat_body(), "model": "qwen-plus"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 403


def test_chat_completions_records_usage(auth_client, db_session):
    token, person = _persona(auth_client, db_session)
    with patch("api.gateway.httpx.AsyncClient", _FakeAsyncClient):
        r = auth_client.post(
            "/v1/chat/completions",
            json=_chat_body(),
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200

    u = auth_client.get("/gateway/usage", params={"personnel_id": person.id}).json()
    assert u["day"]["requests"] == 1
    assert u["day"]["tokens_in"] == 11  # from _FakeAsyncClient's usage block
