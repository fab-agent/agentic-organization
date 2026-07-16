"""
Task request routing, creation, run (mocked LLM + streaming), and rejection tests.
"""

import asyncio
from unittest.mock import patch

import pytest

import models
from tests.conftest import (
    make_agent_config,
    make_member,
    make_personnel,
    make_provider_key,
    make_user,
)


def _streaming_mock(result: str):
    """Build a _call_llm_streaming side_effect that calls on_chunk once and returns result."""

    def _mock(
        provider, model, system_prompt, user_prompt, api_key, on_chunk, base_url=None
    ):
        on_chunk(result)
        return result

    return _mock


_LLM_RESULT = "Q1 sales were strong."
_MOCK_STREAMING = _streaming_mock(_LLM_RESULT)

# ── Setup helper ──────────────────────────────────────────────────────────────


def _full_agent_setup(auth_client, db_session):
    """
    Creates a responsible human personnel linked to auth_client._test_user,
    an agent with that responsible, and a provider key.
    Returns (company_id, agent_personnel_id, responsible_personnel_id, agent_cfg_id).
    """
    co = auth_client._test_company
    user = auth_client._test_user

    # Responsible person (linked to the test user)
    responsible = make_personnel(
        db_session, co.id, name="Responsible Human", slug="responsible-h", type="human"
    )
    responsible.user_id = user.id
    db_session.add(responsible)

    # Agent
    agent = make_personnel(
        db_session, co.id, name="TaskBot", slug="taskbot", type="agent"
    )
    cfg = make_agent_config(
        db_session, agent.id, model="gpt-4o-mini", responsible_id=responsible.id
    )
    make_provider_key(db_session, provider="openai")
    db_session.commit()
    return co.id, agent.id, responsible.id, cfg.id


def _post_task(client, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "title": overrides.pop("title", "Analyse Q1 sales"),
        "body": overrides.pop("body", "Please summarise Q1 sales data."),
        **overrides,
    }
    return client.post("/task-requests", json=payload)


# ── Create ────────────────────────────────────────────────────────────────────


def test_create_task_no_agent(auth_client):
    co = auth_client._test_company
    r = _post_task(auth_client, co.id)
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "pending"
    assert data["assigned_agent_id"] is None


def test_create_task_with_agent_assigned(auth_client, db_session):
    company_id, agent_id, _, _ = _full_agent_setup(auth_client, db_session)
    r = _post_task(auth_client, company_id)
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "assigned"
    assert data["assigned_agent_id"] == agent_id
    assert data["responsible_user_id"] == auth_client._test_user.id


def test_create_task_requires_auth(client):
    r = client.post(
        "/task-requests", json={"company_id": "x", "title": "T", "body": "B"}
    )
    assert r.status_code == 401


def test_create_task_with_skill_filter(auth_client, db_session):
    company_id, _, _, cfg_id = _full_agent_setup(auth_client, db_session)
    # Add a skill to the agent
    skill = models.CompanySkill(
        company_id=company_id,
        name="data_analysis",
        slug="data-analysis",
        skill_type="builtin",
    )
    db_session.add(skill)
    db_session.flush()
    link = models.AgentSkillLink(agent_config_id=cfg_id, company_skill_id=skill.id)
    db_session.add(link)
    db_session.commit()

    r = _post_task(auth_client, company_id, skill_filter="data_analysis")
    assert r.status_code == 201
    assert r.json()["status"] == "assigned"


def test_create_task_skill_filter_no_match(auth_client, db_session):
    _full_agent_setup(auth_client, db_session)
    company_id = auth_client._test_company.id
    # Request a skill that no agent has
    r = _post_task(auth_client, company_id, skill_filter="nonexistent_skill")
    assert r.status_code == 201
    assert r.json()["status"] == "pending"


# ── List ──────────────────────────────────────────────────────────────────────


def test_list_task_requests(auth_client, db_session):
    company_id, _, _, _ = _full_agent_setup(auth_client, db_session)
    _post_task(auth_client, company_id, title="Task 1")
    _post_task(auth_client, company_id, title="Task 2")
    r = auth_client.get("/task-requests")
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()]
    assert "Task 1" in titles
    assert "Task 2" in titles


def test_list_task_requests_by_status(auth_client, db_session):
    company_id, _, _, _ = _full_agent_setup(auth_client, db_session)
    _post_task(auth_client, company_id)
    r = auth_client.get(f"/task-requests?company_id={company_id}&status=assigned")
    assert r.status_code == 200
    assert all(t["status"] == "assigned" for t in r.json())


# ── Run ───────────────────────────────────────────────────────────────────────


def test_run_task_completes(auth_client, db_session):
    company_id, _, _, _ = _full_agent_setup(auth_client, db_session)
    task = _post_task(auth_client, company_id).json()
    assert task["status"] == "assigned"

    with patch("api.task_requests._call_llm_streaming", side_effect=_MOCK_STREAMING):
        r = auth_client.post(f"/task-requests/{task['id']}/run", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert _LLM_RESULT in data["result"]


def test_run_task_delivers_inbox_message(auth_client, db_session):
    company_id, _, _, _ = _full_agent_setup(auth_client, db_session)
    task = _post_task(auth_client, company_id).json()

    with patch(
        "api.task_requests._call_llm_streaming",
        side_effect=_streaming_mock("Analysis done."),
    ):
        auth_client.post(f"/task-requests/{task['id']}/run", json={})

    # Requester should have an inbox message with the result
    inbox = auth_client.get("/inbox").json()
    assert any("Sonuç" in m["title"] or "Analysis done" in m["body"] for m in inbox)


def test_run_task_not_responsible(auth_client, db_session):
    co = auth_client._test_company
    # Agent with no responsible user → responsible_user_id=None on the task
    agent = make_personnel(
        db_session, co.id, name="NoResp", slug="no-resp", type="agent"
    )
    make_agent_config(db_session, agent.id, model="gpt-4o-mini")
    db_session.commit()

    # Task ends up pending (no responsible_user_id)
    task = _post_task(auth_client, co.id).json()
    # The auth_client user is NOT the responsible_user_id → 403 or we set wrong user
    # Create a task with a different user as requester to trigger the 403 path
    other_user = make_user(db_session, email="other_resp@t.com")
    make_member(db_session, other_user.id, co.id)
    db_session.commit()

    # Try to run a task where responsible_user_id is null → 403
    r = auth_client.post(f"/task-requests/{task['id']}/run", json={})
    assert r.status_code == 403


def test_run_task_wrong_status(auth_client, db_session):
    company_id, _, _, _ = _full_agent_setup(auth_client, db_session)
    task = _post_task(auth_client, company_id).json()

    # Complete it first
    with patch(
        "api.task_requests._call_llm_streaming", side_effect=_streaming_mock("Done.")
    ):
        auth_client.post(f"/task-requests/{task['id']}/run", json={})

    # Try running again
    r = auth_client.post(f"/task-requests/{task['id']}/run", json={})
    assert r.status_code == 400


def test_run_task_llm_error_reverts_to_assigned(auth_client, db_session):
    company_id, _, _, _ = _full_agent_setup(auth_client, db_session)
    task = _post_task(auth_client, company_id).json()

    with patch(
        "api.task_requests._call_llm_streaming", side_effect=Exception("Rate limit")
    ):
        r = auth_client.post(f"/task-requests/{task['id']}/run", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "assigned"  # reverted to allow retry
    assert "Rate limit" in data["result"] or "Hata" in data["result"]


# ── Reject ────────────────────────────────────────────────────────────────────


def test_reject_task(auth_client, db_session):
    company_id, _, _, _ = _full_agent_setup(auth_client, db_session)
    task = _post_task(auth_client, company_id).json()

    r = auth_client.post(
        f"/task-requests/{task['id']}/reject",
        json={"human_note": "Not enough context."},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "rejected"
    assert data["human_note"] == "Not enough context."


def test_reject_task_not_responsible(auth_client, db_session):
    co = auth_client._test_company
    # Make a task where responsible is another user
    other_user = make_user(db_session, email="resp_owner@t.com")
    make_member(db_session, other_user.id, co.id)
    responsible = make_personnel(
        db_session, co.id, name="Owner", slug="owner-p", type="human"
    )
    responsible.user_id = other_user.id
    db_session.add(responsible)
    agent = make_personnel(db_session, co.id, name="Bot", slug="bot-t", type="agent")
    make_agent_config(db_session, agent.id, responsible_id=responsible.id)
    db_session.commit()

    task = _post_task(auth_client, co.id).json()
    # auth_client user is the requester, not the responsible_user_id
    # responsible_user_id = other_user.id → auth_client user gets 403
    r = auth_client.post(f"/task-requests/{task['id']}/reject", json={})
    assert r.status_code == 403


# ── SSE / streaming ───────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_emit_delivers_to_queue():
    """_emit pushes events into the per-task queue."""
    from api.task_requests import _emit, _task_queues

    task_id = "emit-unit-test"
    q: asyncio.Queue = asyncio.Queue()
    _task_queues[task_id] = q

    try:
        await _emit(task_id, {"type": "step", "step": "starting"})
        await _emit(task_id, {"type": "chunk", "text": "Hello"})
        await _emit(task_id, {"type": "done"})

        events = []
        while not q.empty():
            events.append(q.get_nowait())

        assert len(events) == 3
        assert events[0] == {"type": "step", "step": "starting"}
        assert events[1] == {"type": "chunk", "text": "Hello"}
        assert events[2] == {"type": "done"}
    finally:
        _task_queues.pop(task_id, None)


@pytest.mark.anyio
async def test_emit_noop_without_listener():
    """_emit silently does nothing when no client is connected."""
    from api.task_requests import _emit

    await _emit("nonexistent-task-id", {"type": "done"})  # must not raise


def test_run_task_emits_chunks(auth_client, db_session):
    """run_task calls on_chunk, result accumulates and is persisted."""
    company_id, _, _, _ = _full_agent_setup(auth_client, db_session)
    task = _post_task(auth_client, company_id).json()

    chunks_received: list[str] = []

    def _capturing_mock(
        provider, model, system_prompt, user_prompt, api_key, on_chunk, base_url=None
    ):
        chunks = ["Chunk A. ", "Chunk B. ", "Chunk C."]
        for c in chunks:
            chunks_received.append(c)
            on_chunk(c)
        return "".join(chunks)

    with patch("api.task_requests._call_llm_streaming", side_effect=_capturing_mock):
        r = auth_client.post(f"/task-requests/{task['id']}/run", json={})

    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["result"] == "Chunk A. Chunk B. Chunk C."
    assert chunks_received == ["Chunk A. ", "Chunk B. ", "Chunk C."]
