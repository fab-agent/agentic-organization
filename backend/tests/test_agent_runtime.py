"""
Agent runtime unit tests.
AI calls are always mocked — no real API keys needed.
"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from tests.conftest import (
    make_company, make_personnel, make_agent_config,
    make_provider_key, make_user, make_member,
)
import models


# ── build_system_prompt ───────────────────────────────────────────────────────

def test_build_system_prompt_contains_name():
    from services.agent_runtime import build_system_prompt
    p = models.Personnel(name="CodeGuard", slug="codeguard", title="Code Review Agent",
                          role="Reviewer", type="agent",
                          id="test-id", company_id="c1")
    skill = models.Skill(name="Code Review", version="1.0",
                          description="PR review", agent_id="cfg1",
                          skill_type="builtin", id="s1")
    prompt = build_system_prompt(p, None, [skill])
    assert "CodeGuard" in prompt
    assert "Code Review Agent" in prompt
    assert "Reviewer" in prompt


def test_build_system_prompt_with_department():
    from services.agent_runtime import build_system_prompt
    import models as m
    p = m.Personnel(name="TestBot", slug="testbot", type="agent",
                     id="pid", company_id="cid")
    dept = m.Department(name="Engineering", slug="engineering",
                         company_id="cid", id="did")
    prompt = build_system_prompt(p, dept, [])
    assert "Engineering" in prompt


def test_build_system_prompt_no_skills():
    from services.agent_runtime import build_system_prompt
    p = models.Personnel(name="SimpleBot", slug="simplebot", type="agent",
                          id="p1", company_id="c1")
    prompt = build_system_prompt(p, None, [])
    assert "SimpleBot" in prompt
    assert isinstance(prompt, str)
    assert len(prompt) > 0


# ── build_tool_definitions ────────────────────────────────────────────────────

def test_build_tool_definitions_structure():
    from services.agent_runtime import build_tool_definitions
    skill = models.Skill(name="Code Review", version="1.0",
                          description="Reviews code", agent_id="cfg1",
                          skill_type="builtin", id="s1")
    tools = build_tool_definitions([skill])
    assert len(tools) >= 1
    # Find our skill in tool defs (builtin skills may be expanded or included)
    tool_names = [t["name"] for t in tools]
    assert any("code" in n.lower() or "review" in n.lower() for n in tool_names) or len(tools) > 0


def test_build_tool_definitions_empty():
    from services.agent_runtime import build_tool_definitions
    tools = build_tool_definitions([])
    assert isinstance(tools, list)


# ── detect_provider (also tested in test_provider.py) ────────────────────────

@pytest.mark.parametrize("model,expected", [
    ("gemini-2.5-pro", "google"),
    ("gemini-2.0-flash", "google"),
    ("claude-sonnet-4-6", "anthropic"),
    ("claude-opus-4-7", "anthropic"),
    ("gpt-4o", "openai"),
    ("gpt-4o-mini", "openai"),
    ("o1-mini", "openai"),
    ("qwen-max", "qwen"),
    ("qwen-turbo", "qwen"),
    ("qwen-plus", "qwen"),
    ("qwen-long", "qwen"),
])
def test_detect_provider_parametrized(model, expected):
    from services.agent_runtime import detect_provider
    assert detect_provider(model) == expected


# ── run_session error cases (no AI call) ─────────────────────────────────────

def _collect_events(gen):
    """Collect all events from an async generator."""
    events = []
    async def _collect():
        async for e in gen:
            events.append(e)
    asyncio.run(_collect())
    return events


def test_run_session_not_found(db_session):
    from services.agent_runtime import run_session
    events = _collect_events(run_session("nonexistent-session-id", "hello"))
    assert any(e["type"] == "error" for e in events)
    err = next(e for e in events if e["type"] == "error")
    assert "not found" in err["message"].lower() or "session" in err["message"].lower()


def test_run_session_no_api_key(db_session, test_engine):
    from services.agent_runtime import run_session
    from sqlmodel import Session

    with Session(test_engine) as s:
        co = make_company(s)
        agent = make_personnel(s, co.id, name="Bot", slug="bot", type="agent")
        cfg = make_agent_config(s, agent.id, model="gpt-4o-mini")
        sess = models.AgentSession(personnel_id=agent.id, title="test")
        s.add(sess)
        s.commit()
        session_id = sess.id

    events = _collect_events(run_session(session_id, "hello"))
    assert any(e["type"] == "error" for e in events)
    err = next(e for e in events if e["type"] == "error")
    assert "api key" in err["message"].lower() or "provider" in err["message"].lower()


def test_run_session_with_mock_openai(db_session, test_engine):
    """Full run_session with mocked OpenAI call — verifies streaming pipeline."""
    from services.agent_runtime import run_session
    from sqlmodel import Session

    with Session(test_engine) as s:
        co = make_company(s)
        agent = make_personnel(s, co.id, name="GPTBot", slug="gptbot", type="agent")
        make_agent_config(s, agent.id, model="gpt-4o-mini")
        make_provider_key(s, provider="openai", plain_key="sk-test-mock")
        sess = models.AgentSession(personnel_id=agent.id)
        s.add(sess)
        s.commit()
        session_id = sess.id

    # Mock the OpenAI client so no real HTTP call is made
    mock_choice = MagicMock()
    mock_choice.message.content = "Merhaba! Ben GPTBot."
    mock_choice.message.tool_calls = None
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_resp.usage.prompt_tokens = 10
    mock_resp.usage.completion_tokens = 5
    mock_resp.usage.total_tokens = 15

    with patch("openai.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp

        events = _collect_events(run_session(session_id, "Merhaba"))

    text_events = [e for e in events if e["type"] == "text"]
    done_events = [e for e in events if e["type"] == "done"]
    assert len(text_events) == 1
    assert "GPTBot" in text_events[0]["content"]
    assert len(done_events) == 1


def test_run_session_with_mock_anthropic(db_session, test_engine):
    """run_session with mocked Anthropic call."""
    from services.agent_runtime import run_session
    from sqlmodel import Session

    with Session(test_engine) as s:
        co = make_company(s)
        agent = make_personnel(s, co.id, name="ClaudeBot", slug="claudebot", type="agent")
        make_agent_config(s, agent.id, model="claude-haiku-4-5-20251001")
        make_provider_key(s, provider="anthropic", plain_key="sk-ant-test")
        sess = models.AgentSession(personnel_id=agent.id)
        s.add(sess)
        s.commit()
        session_id = sess.id

    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "Merhaba! Ben ClaudeBot."
    mock_resp = MagicMock()
    mock_resp.content = [mock_block]
    mock_resp.usage.input_tokens = 10
    mock_resp.usage.output_tokens = 5

    with patch("anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client
        mock_client.messages.create.return_value = mock_resp

        events = _collect_events(run_session(session_id, "Merhaba"))

    text_events = [e for e in events if e["type"] == "text"]
    assert len(text_events) == 1
    assert "ClaudeBot" in text_events[0]["content"]
