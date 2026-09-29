"""
The Jev intent classifier wired into the chat prompt (ADR-0020): a fake classifier,
no network. What matters: it only ever narrows the prompt, never on later turns, never
when the prompt is too small to pay for the call, and it audits tags and tokens — never
the message text.
"""

import json

import pytest
from sqlmodel import select

import models
from services import agent_runtime, intent
from services.agent_runtime import build_system_prompt
from services.intent import Intent
from tests.test_context_assembly import _meta, _person

SECRET_MESSAGE = "SECRET-USER-MESSAGE about the quarterly numbers"


class FakeClassifier:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def classify(self, message, *, domains=None):
        self.calls.append(message)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def world(db_session, monkeypatch):
    monkeypatch.setenv("INTENT_MIN_PROMPT_TOKENS", "1")
    co = make_company_with_context(db_session)
    p = _person(db_session, co)
    searched: list[str] = []

    def fake_search(query, **kw):
        searched.append(query)
        return [
            {
                "created_at": "2026-09-29T00:00:00",
                "source_type": "work_review",
                "chunk_text": "RETRIEVED-FACT",
            }
        ]

    import services.rag_service as rag

    monkeypatch.setattr(rag, "search", fake_search)
    return co, p, searched


def make_company_with_context(db_session):
    from tests.conftest import make_company

    co = make_company(db_session)
    _meta(db_session, co, mission="WIRED-MISSION", vision="WIRED-VISION")
    return co


def use(monkeypatch, classifier):
    monkeypatch.setattr(intent, "get_classifier", lambda: classifier)
    return classifier


def prompt(p, co, **kw):
    return build_system_prompt(
        p,
        None,
        [],
        None,
        rag_query="what is the policy",
        company_id=co.id,
        session_ref="sess-1",
        **kw,
    )


def events(db_session, action="intent_classified"):
    db_session.expire_all()
    return db_session.exec(
        select(models.AuditEvent).where(models.AuditEvent.action == action)
    ).all()


def test_off_by_default_changes_nothing(world, monkeypatch):
    co, p, searched = world
    use(monkeypatch, None)
    text = prompt(p, co, intent_message="hi")
    assert "WIRED-MISSION" in text and "RETRIEVED-FACT" in text
    assert searched == ["what is the policy"]


def test_chitchat_trims_optional_sections_but_never_the_required_ones(
    world, monkeypatch
):
    co, p, searched = world
    fake = use(monkeypatch, FakeClassifier(Intent(task="chitchat")))
    text = prompt(p, co, intent_message="hi there")
    assert fake.calls == ["hi there"]
    assert "WIRED-MISSION" not in text and "RETRIEVED-FACT" not in text
    assert "Ada" in text  # identity is required
    assert searched == []  # retrieval itself is skipped, not just hidden


def test_low_knowledge_need_skips_only_retrieval(world, monkeypatch):
    co, p, searched = world
    use(
        monkeypatch,
        FakeClassifier(Intent(task="analysis", needs_company_knowledge=0.1)),
    )
    text = prompt(p, co, intent_message="summarise this clause")
    assert "WIRED-MISSION" in text and "RETRIEVED-FACT" not in text
    assert searched == []


def test_knowledge_need_above_the_measured_floor_keeps_retrieval(world, monkeypatch):
    co, p, searched = world
    # 0.19-0.24 is what real work ("proceed with the payment run") scored in the trial
    use(
        monkeypatch, FakeClassifier(Intent(task="action", needs_company_knowledge=0.19))
    )
    text = prompt(p, co, intent_message="please proceed with the payment run")
    assert "RETRIEVED-FACT" in text and searched == ["what is the policy"]


def test_later_turns_never_call_the_classifier(world, monkeypatch):
    co, p, _ = world
    fake = use(monkeypatch, FakeClassifier(Intent(task="chitchat")))
    text = prompt(p, co)  # no intent_message: not the first turn
    assert fake.calls == [] and "WIRED-MISSION" in text


def test_small_prompt_is_not_worth_the_call(world, monkeypatch):
    co, p, _ = world
    monkeypatch.setenv("INTENT_MIN_PROMPT_TOKENS", "100000")
    fake = use(monkeypatch, FakeClassifier(Intent(task="chitchat")))
    text = prompt(p, co, intent_message="hi")
    assert fake.calls == [] and "WIRED-MISSION" in text


@pytest.mark.parametrize(
    "fake",
    [
        FakeClassifier(None),
        FakeClassifier(error=TimeoutError("slow")),
        FakeClassifier(error=RuntimeError(SECRET_MESSAGE)),
    ],
)
def test_any_failure_gives_the_complete_prompt(world, monkeypatch, fake, caplog):
    co, p, searched = world
    use(monkeypatch, fake)
    text = prompt(p, co, intent_message=SECRET_MESSAGE)
    assert "WIRED-MISSION" in text and "RETRIEVED-FACT" in text
    assert searched == ["what is the policy"]
    assert SECRET_MESSAGE not in caplog.text  # only the exception type is logged


def test_audit_records_tags_and_tokens_but_never_the_text(
    world, monkeypatch, db_session
):
    co, p, _ = world
    use(
        monkeypatch,
        FakeClassifier(
            Intent(
                task="chitchat",
                needs_company_knowledge=0.05,
                sensitivity="public",
                model="jev-latest",
                input_tokens=520,
                output_tokens=120,
            )
        ),
    )
    prompt(p, co, intent_message=SECRET_MESSAGE)
    (ev,) = events(db_session)
    payload = json.loads(ev.payload_json)
    assert payload["tags"] == {
        "task": "chitchat",
        "sensitivity": "public",
        "needs_company_knowledge": 0.05,
    }
    assert payload["input_tokens"] == 520 and payload["output_tokens"] == 120
    assert "knowledge" in payload["skipped_sections"]
    assert ev.target == "sess-1" and ev.actor_id == p.id
    assert SECRET_MESSAGE not in json.dumps(payload) + (ev.reason or "")


def test_a_failed_call_writes_no_audit_event(world, monkeypatch, db_session, caplog):
    co, p, _ = world
    use(monkeypatch, FakeClassifier(None))
    prompt(p, co, intent_message="hi")
    assert events(db_session) == []
    # "no intent" is an ordinary outcome, not a wiring error to alert on
    assert "intent_wiring_failed" not in caplog.text


def test_chat_stream_passes_the_message_on_the_first_turn_only():
    import inspect

    src = inspect.getsource(agent_runtime)
    assert "intent_message=user_message if not history_rows else None" in src
