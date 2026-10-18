"""Gateway transport failures are audited with a bounded, typed `failure` (ADR-0023 f/u 0)."""

import json
from unittest.mock import patch

import httpx
from sqlmodel import select

from models import AuditLog
from services.run_diagnosis import diagnose
from tests.conftest import make_provider_key
from tests.test_gateway import (  # noqa: F401  (fixtures + fakes)
    _chat_body,
    _FakeAsyncClient,
    _FakeResponse,
    _FakeStreamCtx,
    agent_persona,
)


def _details(db_session):
    row = db_session.exec(
        select(AuditLog).where(AuditLog.action == "gateway_call")
    ).all()[-1]
    return json.loads(row.details_json)


def _call(auth_client, token, **extra):
    return auth_client.post(
        "/v1/chat/completions",
        json={**_chat_body(), **extra},
        headers={"Authorization": f"Bearer {token}"},
    )


def _setup(db_session):
    make_provider_key(db_session, provider="qwen", plain_key="sk-upstream")
    db_session.commit()


class _Timeout(_FakeAsyncClient):
    async def post(self, *a, **kw):
        raise httpx.ReadTimeout("slow")


class _Down(_FakeAsyncClient):
    async def post(self, *a, **kw):
        raise httpx.ConnectError("refused")


class _BadJson(_FakeAsyncClient):
    async def post(self, *a, **kw):
        r = _FakeResponse({})
        r.content = b"<html>oops</html>"

        def boom():
            raise ValueError("no json")

        r.json = boom
        return r


def test_timeout_is_audited_and_returns_504(auth_client, agent_persona, db_session):
    _, token = agent_persona
    _setup(db_session)
    with patch("api.gateway.httpx.AsyncClient", _Timeout):
        r = _call(auth_client, token)
    assert r.status_code == 504
    d = _details(db_session)
    assert d["failure"] == "timeout" and d["upstream_status"] == 0


def test_connection_error_is_audited_as_transport(
    auth_client, agent_persona, db_session
):
    _, token = agent_persona
    _setup(db_session)
    with patch("api.gateway.httpx.AsyncClient", _Down):
        r = _call(auth_client, token)
    assert r.status_code == 502
    assert _details(db_session)["failure"] == "transport"


def test_unparseable_upstream_body_is_audited_as_parse(
    auth_client, agent_persona, db_session
):
    _, token = agent_persona
    _setup(db_session)
    with patch("api.gateway.httpx.AsyncClient", _BadJson):
        r = _call(auth_client, token)
    assert r.status_code == 502
    assert _details(db_session)["failure"] == "parse"


def test_success_records_finish_reason_and_output(
    auth_client, agent_persona, db_session
):
    _, token = agent_persona
    _setup(db_session)

    class _Ok(_FakeAsyncClient):
        async def post(self, *a, **kw):
            return _FakeResponse(
                {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "hi"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            )

    with patch("api.gateway.httpx.AsyncClient", _Ok):
        assert _call(auth_client, token).status_code == 200
    d = _details(db_session)
    assert (
        d["failure"] is None
        and d["finish_reason"] == "stop"
        and d["has_output"] is True
    )


def test_stream_cut_without_done_is_flagged(auth_client, agent_persona, db_session):
    _, token = agent_persona
    _setup(db_session)

    class _Cut(_FakeAsyncClient):
        def stream(self, *a, **kw):
            return _FakeStreamCtx(
                [b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n']
            )

    with patch("api.gateway.httpx.AsyncClient", _Cut):
        _call(auth_client, token, stream=True)
    d = _details(db_session)
    assert d["failure"] == "cut" and d["has_output"] is True


def test_complete_stream_has_no_failure(auth_client, agent_persona, db_session):
    _, token = agent_persona
    _setup(db_session)
    with patch("api.gateway.httpx.AsyncClient", _FakeAsyncClient):
        _call(auth_client, token, stream=True)
    d = _details(db_session)
    assert d["failure"] is None and d["has_output"] is True


def test_stream_transport_error_midway(auth_client, agent_persona, db_session):
    _, token = agent_persona
    _setup(db_session)

    class _Ctx(_FakeStreamCtx):
        async def aiter_raw(self):
            yield b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n'
            raise httpx.ReadError("reset")

    class _Reset(_FakeAsyncClient):
        def stream(self, *a, **kw):
            return _Ctx([])

    with patch("api.gateway.httpx.AsyncClient", _Reset):
        _call(auth_client, token, stream=True)
    assert _details(db_session)["failure"] == "transport"


# ── diagnosis ──────────────────────────────────────────────────────────────


def _ev(seq, **payload):
    return {
        "chain_key": "c",
        "seq": seq,
        "action": "gateway_call",
        "target": "m",
        "payload": payload,
    }


def test_diagnosis_scores_transport_failures_and_ignores_client_hangups():
    d = diagnose([_ev(1, model="m", upstream_status=0, failure="timeout")])
    assert d.suspect_layer == "model" and d.findings[0].kind == "transport_failure"
    d = diagnose([_ev(1, model="m", upstream_status=200, failure="client_closed")])
    assert d.suspect_layer is None and d.findings[0].severity == "info"


def test_diagnosis_flags_empty_output_and_length_but_not_tool_calls():
    empty = diagnose(
        [_ev(1, model="m", upstream_status=200, has_output=False, finish_reason="stop")]
    )
    assert empty.findings[0].kind == "empty_output"
    tools = diagnose(
        [
            _ev(
                1,
                model="m",
                upstream_status=200,
                has_output=False,
                finish_reason="tool_calls",
            )
        ]
    )
    assert tools.findings == []
    length = diagnose(
        [
            _ev(
                1,
                model="m",
                upstream_status=200,
                has_output=True,
                finish_reason="length",
            )
        ]
    )
    assert (
        length.findings[0].kind == "truncated_output"
        and length.findings[0].severity == "low"
    )
