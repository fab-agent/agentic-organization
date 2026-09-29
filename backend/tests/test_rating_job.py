"""Fit rating: the redaction inside `rate_run` and the hourly session job (ADR-0021)."""

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

import models
from services import audit_chain
from services import rating as rt
from services import work_review as wr
from tests.conftest import make_agent_config, make_personnel
from tests.test_rating import FakeRater, rate, stored, world  # noqa: F401


def _agent_with_memory(
    w,
    *,
    session_id="s1",
    summary="Analysed renewals.",
    age_hours=1,
    responsible=True,
    tags=None,
    slug="bot",
):
    agent = make_personnel(w.db, w.co.id, name=slug, slug=slug, type="agent")
    make_agent_config(w.db, agent.id, responsible_id=w.ayse.id if responsible else None)
    w.db.add(models.AgentSession(id=session_id, personnel_id=agent.id, status="closed"))
    w.db.flush()
    w.db.add(
        models.AgentMemory(
            personnel_id=agent.id,
            session_id=session_id,
            summary=summary,
            created_at=datetime.utcnow() - timedelta(hours=age_hours),
        )
    )
    w.db.commit()
    if tags is not None:
        audit_chain.record(
            actor_type="system",
            actor_id=agent.id,
            company_id=w.co.id,
            action="intent_classified",
            target=session_id,
            reason="t",
            payload={"tags": tags},
        )
    return agent


ANALYSIS = {"task": "analysis", "sensitivity": "internal"}


def test_the_summary_is_redacted_before_it_reaches_the_rater(world):  # noqa: F811
    rater = FakeRater()
    rate(
        world,
        rater,
        summary="Mailed ayse@firma.com the card 4111 1111 1111 1111 receipt.",
    )
    sent = rater.calls[0][0]
    assert "[email]" in sent and "[card]" in sent
    assert "ayse@" not in sent and "4111" not in sent


def test_the_job_rates_a_recent_summary_with_the_sessions_tags(world):  # noqa: F811
    w = world
    _agent_with_memory(w, tags=ANALYSIS)
    rater = FakeRater(p=0.9)
    assert rt.rate_recent_sessions(rater=rater) == 1
    w.db.expire_all()
    (r,) = stored(w)
    assert (r.criterion_id, r.verdict, r.run_id, r.personnel_id) == (
        "G1-revenue",
        "met",
        "s1",
        w.ayse.id,
    )
    assert r.day == datetime.utcnow().date().isoformat()


def test_running_the_job_again_writes_and_asks_nothing_more(world):  # noqa: F811
    w = world
    _agent_with_memory(w, tags=ANALYSIS)
    rater = FakeRater()
    assert rt.rate_recent_sessions(rater=rater) == 1
    assert rt.rate_recent_sessions(rater=rater) == 0
    assert len(rater.calls) == 1


def test_a_session_without_a_classification_only_meets_unfiltered_criteria(world):  # noqa: F811
    w = world
    _agent_with_memory(w)  # no intent_classified event → no tags
    rater = FakeRater()
    assert rt.rate_recent_sessions(rater=rater) == 0  # G1 needs task=analysis
    assert rater.calls == []


def test_only_the_latest_classification_of_the_session_counts(world):  # noqa: F811
    w = world
    agent = _agent_with_memory(w, tags={"task": "chitchat"})
    audit_chain.record(
        actor_type="system",
        actor_id=agent.id,
        company_id=w.co.id,
        action="intent_classified",
        target="s1",
        reason="t",
        payload={"tags": ANALYSIS},
    )
    assert rt.rate_recent_sessions(rater=FakeRater()) == 1


def test_old_summaries_are_left_alone(world):  # noqa: F811
    w = world
    _agent_with_memory(w, tags=ANALYSIS, age_hours=100)
    rater = FakeRater()
    assert rt.rate_recent_sessions(rater=rater) == 0 and rater.calls == []
    assert rt.rate_recent_sessions(rater=rater, hours=200) == 1


def test_an_agent_nobody_is_responsible_for_is_skipped(world):  # noqa: F811
    _agent_with_memory(world, tags=ANALYSIS, responsible=False)
    rater = FakeRater()
    assert rt.rate_recent_sessions(rater=rater) == 0 and rater.calls == []


@pytest.mark.parametrize("off", ["rating", "work_review"])
def test_a_company_that_switched_it_off_is_not_touched(world, off):  # noqa: F811
    w = world
    _agent_with_memory(w, tags=ANALYSIS)
    if off == "rating":
        rt.set_rating_enabled(w.db, w.co.id, False)
    else:
        wr.set_enabled(w.db, w.co.id, False)
    w.db.commit()
    rater = FakeRater()
    assert rt.rate_recent_sessions(rater=rater) == 0 and rater.calls == []


def test_without_a_scoring_key_the_job_does_nothing(world, monkeypatch):  # noqa: F811
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    _agent_with_memory(world, tags=ANALYSIS)
    assert rt.rate_recent_sessions() == 0
    assert stored(world) == []


def test_one_failing_session_does_not_stop_the_others(world):  # noqa: F811
    w = world
    _agent_with_memory(w, session_id="bad", tags=ANALYSIS, slug="bot1")
    _agent_with_memory(w, session_id="good", tags=ANALYSIS, slug="bot2")

    class Flaky(FakeRater):
        def rate(self, summary, criteria):
            if not self.calls:
                self.calls.append((summary, []))
                raise RuntimeError("boom")
            return super().rate(summary, criteria)

    assert rt.rate_recent_sessions(rater=Flaky()) == 1
    w.db.expire_all()
    assert len(stored(w)) == 1


def test_the_job_is_scheduled_at_startup():
    import main

    src = open(main.__file__).read()
    assert "rate_recent_sessions" in src and 'id="work_rating"' in src


def test_no_criteria_are_sent_for_agent_personas(world):  # noqa: F811
    w = world
    agent = make_personnel(w.db, w.co.id, name="Bot", slug="botx", type="agent")
    agent.department_id = w.ayse.department_id
    w.db.add(agent)
    w.db.commit()
    rater = FakeRater()
    assert rate(w, rater, person=agent) == [] and rater.calls == []
    assert w.db.exec(select(models.WorkRating)).all() == []


def test_another_sessions_classification_is_not_borrowed(world):  # noqa: F811
    w = world
    # One agent, two sessions: only "a" was classified as analysis.
    agent = _agent_with_memory(w, session_id="a", tags=ANALYSIS)
    w.db.add(models.AgentSession(id="b", personnel_id=agent.id, status="closed"))
    w.db.flush()
    w.db.add(
        models.AgentMemory(personnel_id=agent.id, session_id="b", summary="Other work.")
    )
    w.db.commit()
    assert rt.rate_recent_sessions(rater=FakeRater()) == 1
    w.db.expire_all()
    assert [r.run_id for r in stored(w)] == ["a"]
