"""
AgentSession CRUD, status polling, close, and SSE message tests.
LLM calls are always mocked.
"""
import json
import pytest
from unittest.mock import patch
from tests.conftest import make_personnel, make_agent_config, make_provider_key
import models


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session(client, personnel_id, title="Test Session"):
    return client.post("/sessions", json={"personnel_id": personnel_id, "title": title})


def _setup(auth_client, db_session):
    co = auth_client._test_company
    agent = make_personnel(db_session, co.id, name="ChatBot", slug="chatbot")
    make_agent_config(db_session, agent.id, model="gpt-4o-mini")
    make_provider_key(db_session, provider="openai")
    db_session.commit()
    return agent.id


# ── Create ────────────────────────────────────────────────────────────────────

def test_create_session_201(auth_client, db_session):
    agent_id = _setup(auth_client, db_session)
    r = _make_session(auth_client, agent_id)
    assert r.status_code == 201
    data = r.json()
    assert data["personnel_id"] == agent_id
    assert data["title"] == "Test Session"
    assert data["status"] in ("idle", "active")
    assert data["messages"] == []


def test_create_session_invalid_personnel(auth_client):
    r = _make_session(auth_client, "nonexistent-agent-id")
    assert r.status_code == 404


def test_create_session_requires_auth(client, db_session):
    co = models.Company(name="Co", slug="co")
    db_session.add(co)
    agent = make_personnel(db_session, co.id if False else "x", name="A", slug="a")
    # Just check 401 without valid token
    r = client.post("/sessions", json={"personnel_id": "any-id"})
    assert r.status_code == 401


# ── List ──────────────────────────────────────────────────────────────────────

def test_list_sessions_empty(auth_client, db_session):
    _setup(auth_client, db_session)
    r = auth_client.get("/sessions")
    assert r.status_code == 200
    assert r.json() == []


def test_list_sessions(auth_client, db_session):
    agent_id = _setup(auth_client, db_session)
    _make_session(auth_client, agent_id, title="S1")
    _make_session(auth_client, agent_id, title="S2")
    r = auth_client.get("/sessions")
    assert r.status_code == 200
    titles = [s["title"] for s in r.json()]
    assert "S1" in titles
    assert "S2" in titles


def test_list_sessions_by_personnel(auth_client, db_session):
    agent_id = _setup(auth_client, db_session)
    _make_session(auth_client, agent_id, title="Filtered")
    r = auth_client.get(f"/sessions?personnel_id={agent_id}")
    assert r.status_code == 200
    assert all(s["personnel_id"] == agent_id for s in r.json())


# ── Get ───────────────────────────────────────────────────────────────────────

def test_get_session_detail(auth_client, db_session):
    agent_id = _setup(auth_client, db_session)
    sess_id = _make_session(auth_client, agent_id).json()["id"]
    r = auth_client.get(f"/sessions/{sess_id}")
    assert r.status_code == 200
    assert r.json()["id"] == sess_id
    assert "messages" in r.json()


def test_get_session_not_found(auth_client):
    r = auth_client.get("/sessions/nonexistent")
    assert r.status_code == 404


# ── Status ────────────────────────────────────────────────────────────────────

def test_get_session_status(auth_client, db_session):
    agent_id = _setup(auth_client, db_session)
    sess_id = _make_session(auth_client, agent_id).json()["id"]
    r = auth_client.get(f"/sessions/{sess_id}/status")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "is_running" in data
    assert "messages" in data
    assert data["is_running"] is False


def test_get_session_status_not_found(auth_client):
    r = auth_client.get("/sessions/bad-id/status")
    assert r.status_code == 404


# ── Close ─────────────────────────────────────────────────────────────────────

def test_close_session(auth_client, db_session):
    agent_id = _setup(auth_client, db_session)
    sess_id = _make_session(auth_client, agent_id).json()["id"]
    with patch("services.memory_service.generate_session_summary"):
        r = auth_client.delete(f"/sessions/{sess_id}")
    assert r.status_code == 204

    status = auth_client.get(f"/sessions/{sess_id}/status").json()
    assert status["status"] == "closed"


def test_close_session_not_found(auth_client):
    with patch("services.memory_service.generate_session_summary"):
        r = auth_client.delete("/sessions/nonexistent")
    assert r.status_code == 404


# ── Memories ──────────────────────────────────────────────────────────────────

def test_list_memories_empty(auth_client):
    r = auth_client.get("/sessions/memories")
    assert r.status_code == 200
    assert r.json() == []


def test_list_memories_by_personnel(auth_client, db_session):
    agent_id = _setup(auth_client, db_session)
    mem = models.AgentMemory(personnel_id=agent_id, session_id="sess-1", summary="Liked Python")
    db_session.add(mem)
    db_session.commit()
    r = auth_client.get(f"/sessions/memories?personnel_id={agent_id}")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["summary"] == "Liked Python"


# ── Message send (SSE) ────────────────────────────────────────────────────────

async def _mock_run_success(session_id, content, attachments=None):
    yield {"type": "text", "content": "Hello from mock agent!"}


def test_send_message_streams_sse(auth_client, db_session):
    agent_id = _setup(auth_client, db_session)
    sess_id = _make_session(auth_client, agent_id).json()["id"]

    with patch("api.sessions.run_session", new=_mock_run_success):
        with auth_client.stream("POST", f"/sessions/{sess_id}/messages",
                                json={"content": "Hello"}) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            lines = [l for l in r.iter_lines() if l.startswith("data: ")]
    assert len(lines) >= 1
    # At minimum one data event
    event = json.loads(lines[0][6:])  # strip "data: "
    assert "type" in event


def test_send_message_closed_session(auth_client, db_session):
    agent_id = _setup(auth_client, db_session)
    sess_id = _make_session(auth_client, agent_id).json()["id"]
    with patch("services.memory_service.generate_session_summary"):
        auth_client.delete(f"/sessions/{sess_id}")
    r = auth_client.post(f"/sessions/{sess_id}/messages", json={"content": "Hi"})
    assert r.status_code == 409


def test_send_message_not_found(auth_client):
    r = auth_client.post("/sessions/bad-id/messages", json={"content": "Hi"})
    assert r.status_code == 404
