"""Training-need signals (ADR-0021 §6): the unit is read first, the person second, and
the person's own signal is shown to the person before anyone else."""

import json
from datetime import timedelta

import pytest
from sqlmodel import select

import models
from services import rating as rt
from services import rubric as rb
from services import training_need as tn
from services import work_review as wr
from tests.test_work_rating_views import RUBRIC, _rating, _role
from tests.test_work_review import (  # noqa: F401
    TODAY,
    _as,
    _cheap_password_hash,
    _get,
    on,
    org,
)


def _many(o, who, met=0, not_met=0, unclear=0, **kw):
    for verdict, n in (("met", met), ("not_met", not_met), ("unclear", unclear)):
        for _ in range(n):
            _rating(o, who.person, verdict=verdict, **kw)


def _signals(o, who):
    return tn.person_signals(o.db, who.person)


# ── the person's signal ──────────────────────────────────────────────────────


def test_a_person_needs_enough_rated_work_and_a_high_enough_not_met_share(on):
    _many(on, on.ayse, met=4, not_met=6)  # 10 decided, 60 %
    (s,) = _signals(on, on.ayse)
    assert (s["criterion_id"], s["rated"], s["not_met"], s["not_met_share"]) == (
        "G1",
        10,
        6,
        0.6,
    )
    assert s["window_days"] == 30
    _many(on, on.bora, met=3, not_met=6)  # 9 decided: not enough
    assert _signals(on, on.bora) == []
    _many(on, on.cem, met=6, not_met=4)  # 40 %: below the bar
    assert _signals(on, on.cem) == []


def test_the_bar_is_inclusive(on):
    _many(on, on.ayse, met=5, not_met=5)  # exactly 50 %
    assert len(_signals(on, on.ayse)) == 1


def test_only_live_uncontested_decided_ratings_in_the_window_count(on):
    a = on.ayse
    _many(on, a, not_met=6, unclear=10)  # unclear answers are not evidence
    assert _signals(on, a) == []
    _many(on, a, not_met=10, status="shadow")  # a trial criterion never counts
    assert _signals(on, a) == []
    from datetime import datetime

    for _ in range(10):
        _rating(on, a.person, verdict="not_met", contested_at=datetime.utcnow())
    assert _signals(on, a) == []
    for _ in range(10):
        _rating(on, a.person, verdict="not_met", day=TODAY - timedelta(days=45))
    assert _signals(on, a) == []
    _many(on, a, not_met=4)  # now 10 live, decided, recent
    assert len(_signals(on, a)) == 1


def test_criterion_versions_are_counted_apart(on):
    _many(on, on.ayse, not_met=6, chash="old")
    _many(on, on.ayse, not_met=6, chash="new")
    assert _signals(on, on.ayse) == []  # 6 + 6 must not add up to 12
    _many(on, on.ayse, not_met=4, chash="new")
    (s,) = _signals(on, on.ayse)
    assert s["criterion_hash"] == "new" and s["rated"] == 10


def test_another_persons_ratings_do_not_count(on):
    _many(on, on.bora, not_met=20)
    assert _signals(on, on.ayse) == []


# ── the company sets the bar ─────────────────────────────────────────────────


def _put(o, user, **body):
    _as(o.client, user)
    return o.client.put("/work-review/training-need/settings", json=body)


def test_the_company_can_change_the_minimum_and_the_bar(on):
    _many(on, on.ayse, met=4, not_met=1)  # 5 decided, 20 %
    assert _signals(on, on.ayse) == []
    assert _put(on, on.founder, min_rated=5, bar=0.2).status_code == 200
    on.db.expire_all()
    assert len(_signals(on, on.ayse)) == 1
    assert _put(on, on.founder, bar=0.5).json() == {
        "min_rated": 5,
        "bar": 0.5,
        "window_days": 30,
    }
    _as(on.client, on.founder)
    assert on.client.get("/work-review/training-need/settings").json()["min_rated"] == 5


@pytest.mark.parametrize(
    "body", [{"min_rated": 2}, {"min_rated": 201}, {"bar": 0.0}, {"bar": 1.5}]
)
def test_settings_are_validated(on, body):
    assert _put(on, on.founder, **body).status_code == 422


def test_only_the_founder_touches_the_settings_and_it_is_audited(on):
    for who in (on.dana, on.mert, on.ayse):
        assert _put(on, who.user, bar=0.9).status_code == 403
        _as(on.client, who.user)
        assert on.client.get("/work-review/training-need/settings").status_code == 403
    _put(on, on.founder, bar=0.9)
    ev = on.db.exec(
        select(models.AuditEvent).where(
            models.AuditEvent.action == "work_review_settings_changed"
        )
    ).all()
    assert any(e.reason == "training_need" for e in ev)


def test_unusable_stored_settings_fall_back_to_the_defaults(on):
    for key, junk in (
        ("min_rated", "x"),
        ("min_rated", "1"),
        ("bar", "nan"),
        ("bar", "7"),
    ):
        wr._put(on.db, f"work_review.training.{key}:{on.co.id}", junk)
    on.db.commit()
    assert tn.min_rated(on.db, on.co.id) == tn.DEFAULT_MIN_RATED
    assert tn.bar(on.db, on.co.id) == tn.DEFAULT_BAR


# ── the unit finding ─────────────────────────────────────────────────────────


def _accounting(o):
    return wr.department_members(o.db, o.accounting)


def test_a_unit_finding_needs_the_pattern_across_several_people(on):
    for who in (on.ayse, on.bora, on.cem):
        _many(on, who, met=1, not_met=3)  # 12 decided, 9 not met, 3 people
    (f,) = tn.unit_findings(on.db, _accounting(on))
    assert f["criterion_id"] == "G1" and f["rated"] == 12 and f["not_met"] == 9
    assert (f["n_people"], f["n_people_not_met"], f["reading"]) == (
        3,
        3,
        "rule_or_training_unclear",
    )
    assert f["not_met_share"] == 0.75


def test_two_strugglers_are_not_a_unit_finding(on):
    _many(on, on.ayse, not_met=6)
    _many(on, on.bora, not_met=6)
    _many(on, on.cem, met=6)  # three people rated, but only two had a not-met
    assert tn.unit_findings(on.db, _accounting(on)) == []


def test_many_ratings_from_two_people_are_not_a_unit_finding(on):
    _many(on, on.ayse, not_met=20)
    _many(on, on.bora, not_met=20)
    assert tn.unit_findings(on.db, _accounting(on)) == []


def test_a_low_share_is_not_a_finding_even_with_many_strugglers(on):
    for who in (on.ayse, on.bora, on.cem):
        _many(on, who, met=8, not_met=1)  # 27 decided, 3 not met: 11 %
    assert tn.unit_findings(on.db, _accounting(on)) == []


def test_a_unit_below_the_group_floor_says_nothing(on):
    assert tn.unit_findings(on.db, wr.department_members(on.db, on.finance)) is None


def test_trial_and_contested_ratings_do_not_make_a_unit_finding(on):
    from datetime import datetime

    for who in (on.ayse, on.bora, on.cem):
        _many(on, who, not_met=4, status="shadow")
    assert tn.unit_findings(on.db, _accounting(on)) == []
    for who in (on.ayse, on.bora, on.cem):
        for _ in range(4):
            _rating(on, who.person, verdict="not_met", contested_at=datetime.utcnow())
    assert tn.unit_findings(on.db, _accounting(on)) == []


# ── the API ──────────────────────────────────────────────────────────────────


def test_the_person_sees_their_own_signal_and_nobody_else_does(on):
    wr._put(on.db, f"work_review.rubric:{on.co.id}", RUBRIC)
    on.db.commit()
    current = rb.criterion_hash(rt.load_rubric(on.db, on.co.id)[0].criteria[0])
    _many(on, on.ayse, met=3, not_met=7, chash=current)
    mine = _get(on, "/me", on.ayse.user).json()
    (s,) = mine["training_need"]
    assert s["not_met_share"] == 0.7 and s["unit_wide"] is False
    assert s["question"] == "Does this work advance recurring revenue?"
    # the direct manager, the team and department aggregates and a peer see none of it
    theirs = _get(on, f"/people/{on.ayse.person.id}", on.mert.user).json()
    assert "training_need" not in theirs
    assert "training_need" not in json.dumps(_get(on, "/teams", on.dana.user).json())
    assert "training_need" not in json.dumps(
        _get(on, "/departments", on.founder).json()
    )
    assert _get(on, "/me", on.bora.user).json()["training_need"] == []


def test_a_signal_is_marked_unit_wide_when_colleagues_show_the_same_pattern(on):
    for who in (on.ayse, on.bora, on.cem):
        _many(on, who, met=1, not_met=9)
    mine = _get(on, "/me", on.ayse.user).json()["training_need"]
    assert mine and mine[0]["unit_wide"] is True
    # ...and the flag reveals no counts about the colleagues
    assert set(mine[0]) >= {"rated", "not_met", "not_met_share", "unit_wide"}
    assert "n_people" not in mine[0]


def test_rubric_owners_get_unit_findings_without_names(on):
    for who in (on.ayse, on.bora, on.cem):
        _many(on, who, met=1, not_met=3)
    _role(on, on.dana, "dept_head", on.finance.id)  # Accounting sits under Finance
    res = _get(on, "/training-need/units", on.dana.user)
    assert res.status_code == 200
    by = {d["department"]["name"]: d for d in res.json()}
    acc = by["Accounting"]
    assert acc["suppressed"] is False and len(acc["findings"]) == 1
    assert acc["findings"][0]["reading"] == "rule_or_training_unclear"
    assert by["Finance"]["suppressed"] is True and by["Finance"]["findings"] == []
    blob = json.dumps(res.json())
    for name in ("Ayşe", "Bora", "Cem", on.ayse.person.id):
        assert name not in blob


def test_unit_findings_are_not_for_plain_users_or_team_leaders(on):
    for who in (on.ayse, on.mert):  # a team leader is not a rubric owner
        assert _get(on, "/training-need/units", who.user).status_code == 403


def test_the_founder_reads_every_department_and_the_read_is_audited(on):
    for who in (on.ayse, on.bora, on.cem):
        _many(on, who, met=1, not_met=3)
    res = _get(on, "/training-need/units", on.founder)
    assert res.status_code == 200
    assert {d["department"]["name"] for d in res.json()} == {"Finance", "Accounting"}
    ev = on.db.exec(
        select(models.AuditEvent).where(
            models.AuditEvent.action == "work_review_viewed"
        )
    ).all()
    assert any(e.reason == "training_units" for e in ev)
    assert "G1" not in "".join(e.payload_json or "" for e in ev)


def test_nothing_is_served_while_work_review_is_off(org):
    _many(org, org.ayse, not_met=12)
    assert _get(org, "/me", org.ayse.user).status_code == 404
    assert _get(org, "/training-need/units", org.founder).status_code == 404


def test_signals_never_carry_a_score_or_a_ranking(on):
    _many(on, on.ayse, not_met=12)
    blob = json.dumps(_get(on, "/me", on.ayse.user).json()["training_need"])
    assert not any(k in blob for k in ("score", "rank", "grade", "percentile"))


def test_unclear_answers_do_not_inflate_the_count_that_clears_the_minimum(on):
    # 6 decided not-met + 5 unclear: 11 rows, but only 6 decided (< 10). Counting the
    # unclear ones would both pass the minimum and keep the share above the bar.
    _many(on, on.ayse, not_met=6, unclear=5)
    assert _signals(on, on.ayse) == []


def test_unclear_answers_do_not_inflate_a_units_count_either(on):
    # 9 decided not-met (< 10) plus 3 unclear: 12 rows would clear the minimum, and the
    # share of not-met among all rows (75 %) would still be above the bar.
    for who in (on.ayse, on.bora, on.cem):
        _many(on, who, not_met=3, unclear=1)
    assert tn.unit_findings(on.db, _accounting(on)) == []


def test_a_criterion_version_is_counted_apart_in_a_unit_too(on):
    for who in (on.ayse, on.bora, on.cem):
        _many(on, who, not_met=2, chash="old")
        _many(on, who, not_met=2, chash="new")
    # 6 + 6 not-met, but neither wording alone reaches the minimum of 10
    assert tn.unit_findings(on.db, _accounting(on)) == []
