"""Fit rating (ADR-0021): rubric storage, which criteria apply, sampling, the Jev call,
and what is written. The scoring model is always faked — no network, no keys."""

import json
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx2
import pytest
from sqlmodel import Session, select
from typesafe_sdk import TypeSafeClient

import models
from services import rating as rt
from services import rubric as rb
from services import work_review as wr
from tests.conftest import make_company, make_personnel

RUBRIC = """
version: 1
criteria:
  - id: G1-revenue
    question: Does this work advance recurring revenue?
    good_answer: "yes"
    source: {kind: goal, ref: company.goals.1, quote: "recurring revenue"}
    scope: {departments: [sales]}
    applies_when: {tasks: [analysis]}
    status: live
  - id: P-purpose
    question: Does the output expose personal customer data beyond the task?
    good_answer: "no"
    source: {kind: policy, ref: policy.kvkk, quote: "stated purpose"}
    scope: {company: true}
    applies_when: {sensitivities: [personal]}
    status: shadow
  - id: D-draft
    question: Is this a draft criterion?
    good_answer: "yes"
    source: {kind: goal, ref: company.goals.1, quote: "recurring revenue"}
    scope: {company: true}
    status: draft
"""


class FakeRater:
    def __init__(self, p=0.9, model="fake-1", answers=None):
        self.p, self.model, self.answers = p, model, answers
        self.calls: list[tuple[str, list[str]]] = []

    def rate(self, summary, criteria):
        self.calls.append((summary, [c.id for c in criteria]))
        if self.answers == "fail":
            return None
        p = self.answers if isinstance(self.answers, dict) else {}
        return rt.RatingResult(
            p_yes={c.id: p.get(c.id, self.p) for c in criteria}, model=self.model
        )


@pytest.fixture
def world(db_session, test_engine):
    with Session(test_engine) as s:
        co = make_company(s)
        co.metadata_json = json.dumps({"goals": ["Grow recurring revenue 20%"]})
        s.add(co)
        s.add(models.Department(company_id=co.id, name="Sales", slug="sales"))
        s.add(models.Department(company_id=co.id, name="Legal", slug="legal"))
        s.add(
            models.Policy(
                company_id=co.id,
                name="KVKK",
                slug="kvkk",
                content="Personal data is used only for the stated purpose.",
                is_active=True,
            )
        )
        s.flush()
        sales = s.exec(
            select(models.Department).where(models.Department.slug == "sales")
        ).one()
        ayse = make_personnel(s, co.id, name="Ayse", slug="ayse", type="human")
        ayse.department_id = sales.id
        s.add(ayse)
        s.commit()
        assert rt.set_rubric(s, co.id, RUBRIC, gates=False) == []
        wr.set_enabled(s, co.id, True)
        rt.set_rating_enabled(s, co.id, True)
        rt.wr._put(s, f"work_review.rating.sample_rate:{co.id}", "1")
        s.commit()
        yield SimpleNamespace(db=s, co=co, ayse=ayse)


def rate(w, rater, run="r1", tags=None, summary="Analysed renewals.", person=None):
    return rt.rate_run(
        w.db,
        person=person or w.ayse,
        run_id=run,
        summary=summary,
        tags=tags
        if tags is not None
        else {"task": "analysis", "sensitivity": "internal"},
        rater=rater,
    )


def stored(w):
    return w.db.exec(select(models.WorkRating)).all()


# ── switches ─────────────────────────────────────────────────────────────────


def test_rating_needs_work_review_and_its_own_switch(world):
    w = world
    assert rt.rating_enabled(w.db, w.co.id)
    rt.set_rating_enabled(w.db, w.co.id, False)
    assert not rt.rating_enabled(w.db, w.co.id)
    rt.set_rating_enabled(w.db, w.co.id, True)
    wr.set_enabled(w.db, w.co.id, False)
    assert not rt.rating_enabled(w.db, w.co.id)  # rating alone is not enough


def test_a_second_company_is_unaffected(world):
    other = make_company(world.db, name="Other", slug="other")
    assert not rt.rating_enabled(world.db, other.id)


def test_sample_rate_setting_is_validated(world):
    w = world
    assert rt.sample_rate(w.db, w.co.id) == 1.0
    for bad in ("2", "-1", "x", ""):
        wr._put(w.db, f"work_review.rating.sample_rate:{w.co.id}", bad)
        assert rt.sample_rate(w.db, w.co.id) == rt.DEFAULT_SAMPLE_RATE


# ── rubric storage ───────────────────────────────────────────────────────────


def test_a_rubric_that_fails_the_linter_is_not_stored(world):
    w = world
    before = wr._get(w.db, f"work_review.rubric:{w.co.id}")
    bad = RUBRIC.replace(
        'quote: "recurring revenue"}\n    scope: {departments',
        'quote: "halve costs"}\n    scope: {departments',
    )
    findings = rt.set_rubric(w.db, w.co.id, bad, gates=False)
    assert [f.code for f in findings] == ["quote_not_in_source"]
    assert wr._get(w.db, f"work_review.rubric:{w.co.id}") == before


def test_unknown_department_is_refused_and_garbage_raises(world):
    w = world
    ghost = RUBRIC.replace("departments: [sales]", "departments: [ghost]")
    assert "unknown_department" in {
        f.code for f in rt.set_rubric(w.db, w.co.id, ghost, gates=False)
    }
    with pytest.raises(rb.RubricError):
        rt.set_rubric(w.db, w.co.id, "- nope", gates=False)


def test_load_rubric_tolerates_missing_and_corrupt_text(world):
    w = world
    rubric, version = rt.load_rubric(w.db, w.co.id)
    assert len(rubric.criteria) == 3 and version == rt.rubric_version(RUBRIC)
    wr._put(w.db, f"work_review.rubric:{w.co.id}", "a: [")
    assert rt.load_rubric(w.db, w.co.id) is None
    assert rt.load_rubric(w.db, "no-such-company") is None


# ── rating a run ─────────────────────────────────────────────────────────────


def test_a_run_is_rated_against_the_applicable_criteria_only(world):
    w = world
    rater = FakeRater(p=0.9)
    rows = rate(w, rater)
    # G1 applies (sales + analysis, live). P-purpose needs personal data; the draft is skipped.
    assert [r.criterion_id for r in rows] == ["G1-revenue"]
    r = rows[0]
    assert (r.verdict, r.probability, r.model) == ("met", 0.9, "fake-1")
    assert r.criterion_status == "live" and r.personnel_id == w.ayse.id
    assert r.rubric_version == rt.rubric_version(RUBRIC)
    assert r.criterion_hash == rb.criterion_hash(
        rt.load_rubric(w.db, w.co.id)[0].criteria[0]
    )
    assert r.day == datetime.utcnow().date().isoformat()
    assert rater.calls == [("Analysed renewals.", ["G1-revenue"])]


def test_verdicts_follow_the_criterions_own_direction(world):
    w = world
    tags = {"task": "analysis", "sensitivity": "personal"}
    rows = rate(w, FakeRater(answers={"G1-revenue": 0.5, "P-purpose": 0.05}), tags=tags)
    by = {r.criterion_id: r for r in rows}
    assert by["G1-revenue"].verdict == "unclear"
    assert by["P-purpose"].verdict == "met"  # good answer is "no"; p_yes 0.05
    assert by["P-purpose"].criterion_status == "shadow"


def test_rating_the_same_run_twice_asks_and_writes_nothing_more(world):
    w = world
    rater = FakeRater()
    assert len(rate(w, rater)) == 1
    assert rate(w, rater) == []
    assert len(rater.calls) == 1 and len(stored(w)) == 1


def test_a_reworded_criterion_is_rated_again_and_old_rows_stay(world):
    w = world
    rater = FakeRater()
    rate(w, rater)
    reworded = RUBRIC.replace("advance recurring revenue", "grow recurring revenue")
    assert rt.set_rubric(w.db, w.co.id, reworded, gates=False) == []
    rows = rate(w, rater)
    assert len(rows) == 1
    old, new = sorted(stored(w), key=lambda r: r.created_at)
    assert old.criterion_hash != new.criterion_hash
    assert old.rubric_version != new.rubric_version


@pytest.mark.parametrize(
    "case",
    [
        "work_review_off",
        "rating_off",
        "agent",
        "no_rater",
        "empty_summary",
        "no_rubric",
        "nothing_applies",
        "other_department",
        "no_department",
    ],
)
def test_nothing_is_rated_or_sent_when_a_precondition_fails(world, case):
    w = world
    rater = FakeRater()
    person, tags, summary = w.ayse, None, "Analysed renewals."
    if case == "work_review_off":
        wr.set_enabled(w.db, w.co.id, False)
    elif case == "rating_off":
        rt.set_rating_enabled(w.db, w.co.id, False)
    elif case == "agent":
        # in the right department with matching tags, so only the type can exclude it
        person = make_personnel(w.db, w.co.id, name="Bot", slug="bot", type="agent")
        person.department_id = w.ayse.department_id
        w.db.add(person)
    elif case == "no_rater":
        rater = None
    elif case == "empty_summary":
        summary = "   "
    elif case == "no_rubric":
        w.db.delete(w.db.get(models.AppConfig, f"work_review.rubric:{w.co.id}"))
    elif case == "nothing_applies":
        tags = {"task": "chitchat"}
    elif case == "other_department":
        legal = w.db.exec(
            select(models.Department).where(models.Department.slug == "legal")
        ).one()
        w.ayse.department_id = legal.id
    elif case == "no_department":
        w.ayse.department_id = None
    w.db.commit()
    assert rate(w, rater, person=person, tags=tags, summary=summary) == []
    assert stored(w) == []
    if rater:
        assert rater.calls == []


def test_sampling_skips_runs_but_never_a_personal_data_run(world):
    w = world
    wr._put(w.db, f"work_review.rating.sample_rate:{w.co.id}", "0")
    w.db.commit()
    rater = FakeRater()
    assert rate(w, rater) == [] and rater.calls == []
    personal = {"task": "analysis", "sensitivity": "personal"}
    assert len(rate(w, rater, run="r2", tags=personal)) == 2


def test_sampled_is_deterministic_and_respects_the_extremes():
    assert all(rt.sampled(f"r{i}", 1.0) for i in range(50))
    assert not any(rt.sampled(f"r{i}", 0.0) for i in range(50))
    assert rt.sampled("abc", 0.5) == rt.sampled("abc", 0.5)
    share = sum(rt.sampled(f"run-{i}", 0.2) for i in range(2000)) / 2000
    assert 0.15 < share < 0.25


def test_a_failed_rater_writes_nothing(world):
    assert rate(world, FakeRater(answers="fail")) == [] and stored(world) == []


@pytest.mark.parametrize("bad", [None, True, "0.9", float("nan")])
def test_a_missing_or_garbage_probability_is_stored_as_unclear(world, bad):
    rows = rate(world, FakeRater(answers={"G1-revenue": bad}))
    assert rows[0].verdict == "unclear"
    assert rows[0].probability is None or rows[0].probability != rows[0].probability


# ── retention and erasure ────────────────────────────────────────────────────


def _old_rating(w, days):
    day = (datetime.utcnow().date() - timedelta(days=days)).isoformat()
    w.db.add(
        models.WorkRating(
            company_id=w.co.id,
            personnel_id=w.ayse.id,
            day=day,
            run_id=f"old{days}",
            criterion_id="G1-revenue",
            criterion_hash="h",
            rubric_version="v",
            criterion_status="live",
            verdict="met",
        )
    )
    w.db.commit()


def test_ratings_expire_with_the_retention_window(world):
    w = world
    _old_rating(w, 400)
    _old_rating(w, 10)
    assert wr.purge_expired() == 1
    w.db.expire_all()
    assert [r.run_id for r in stored(w)] == ["old10"]


def test_ratings_are_erased_with_the_person(world):
    w = world
    rate(w, FakeRater())
    assert stored(w)
    assert wr.erase_person(w.db, w.ayse.id) >= 1
    w.db.commit()
    assert stored(w) == []


# ── the Jev rater ────────────────────────────────────────────────────────────


def _crit(i, q=None):
    return rb.Criterion.model_validate(
        {
            "id": f"C{i}",
            "question": q or f"Does this work advance goal {i}?",
            "good_answer": "yes",
            "source": {"kind": "goal", "ref": "company.goals.1", "quote": "x"},
            "scope": {"company": True},
        }
    )


def _client(respond):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return respond(request)

    return TypeSafeClient(
        api_key="test-key", transport=httpx2.MockTransport(handler)
    ), seen


def _answers(n, p=0.8):
    return {
        "model": "jev-1.13.0",
        "answers": {f"q{i}": {"type": "noul", "noul": p} for i in range(n)},
        "usage": {"input_tokens": 300, "output_tokens": 20},
    }


def test_jev_rater_sends_one_noul_question_per_criterion_and_parses_them():
    client, seen = _client(lambda r: httpx2.Response(200, json=_answers(2, 0.8)))
    out = rt.JevRater(client=client).rate("the summary", [_crit(1), _crit(2)])
    assert out.p_yes == {"C1": 0.8, "C2": 0.8} and out.model == "jev-1.13.0"
    body = seen[0]
    assert body["state"] == "the summary"
    qs = body["questions"]
    assert set(qs) == {"q0", "q1"}
    assert qs["q0"]["instructions"] == "Does this work advance goal 1?"
    assert all(q["type"] == "noul" for q in qs.values())


def test_jev_rater_caps_summary_and_criteria_and_skips_empty():
    client, seen = _client(
        lambda r: httpx2.Response(200, json=_answers(rt.MAX_CRITERIA_PER_CALL))
    )
    crits = [_crit(i) for i in range(rt.MAX_CRITERIA_PER_CALL + 5)]
    out = rt.JevRater(client=client).rate("x" * 10_000, crits)
    assert len(seen[0]["state"]) == rt.MAX_SUMMARY_CHARS
    assert len(seen[0]["questions"]) == rt.MAX_CRITERIA_PER_CALL
    assert len(out.p_yes) == rt.MAX_CRITERIA_PER_CALL
    assert rt.JevRater(client=client).rate("  ", [_crit(1)]) is None
    assert rt.JevRater(client=client).rate("text", []) is None
    assert len(seen) == 1


def test_jev_rater_tolerates_a_missing_or_wrongly_typed_answer():
    payload = _answers(1)
    payload["answers"]["q1"] = {
        "type": "score",
        "score": 1.0,
        "confidence": 1.0,
        "legend": {"0": "a"},
        "probabilities": {"0": 1.0},
    }
    client, _ = _client(lambda r: httpx2.Response(200, json=payload))
    out = rt.JevRater(client=client).rate("s", [_crit(1), _crit(2), _crit(3)])
    assert out.p_yes == {"C1": 0.8, "C2": None, "C3": None}


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_jev_failures_give_none_and_are_not_retried(status):
    client, seen = _client(lambda r: httpx2.Response(status, json={"error": "x"}))
    rater = rt.JevRater(client=client)
    assert rater.rate("s", [_crit(1)]) is None
    assert len(seen) == 1 and rater.last_error


def test_jev_failures_never_log_the_summary(caplog):
    client, _ = _client(
        lambda r: httpx2.Response(500, json={"error": "SECRET-SUMMARY"})
    )
    with caplog.at_level(logging.DEBUG):
        rt.JevRater(client=client).rate(
            "SECRET-SUMMARY about Ayse's salary", [_crit(1)]
        )
    assert "SECRET-SUMMARY" not in caplog.text and "salary" not in caplog.text


def test_get_rater_needs_a_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert rt.get_rater() is None
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    assert isinstance(rt.get_rater(), rt.JevRater)
