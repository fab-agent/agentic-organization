"""Fit ratings in the review views (ADR-0021 §5–6): the person sees everything, others
see only live and uncontested ratings, contests, resolution, and the company switch."""

import json
from datetime import datetime

import pytest
from sqlmodel import select

import models
from services import rating as rt
from services import rubric as rb
from services import work_review as wr
from tests.test_work_review import (  # noqa: F401
    TODAY,
    _as,
    _cheap_password_hash,
    _get,
    _put,
    on,
    org,
)

RUBRIC = """
version: 1
criteria:
  - id: G1
    question: Does this work advance recurring revenue?
    good_answer: "yes"
    source: {kind: goal, ref: company.goals.1, quote: "x"}
    scope: {company: true}
    status: live
"""


def _rating(
    o, person, cid="G1", chash="h1", status="live", verdict="met", day=None, **kw
):
    r = models.WorkRating(
        company_id=o.co.id,
        personnel_id=person.id,
        day=(day or TODAY).isoformat(),
        run_id=f"run-{cid}-{chash}-{status}-{verdict}-{datetime.utcnow().timestamp()}",
        criterion_id=cid,
        criterion_hash=chash,
        rubric_version="v",
        criterion_status=status,
        verdict=verdict,
        **kw,
    )
    o.db.add(r)
    o.db.commit()
    return r


def _ids(view):
    return {e["id"] for d in view["days"] for e in d["ratings"]}


@pytest.fixture()
def rated(on):
    on.live = _rating(on, on.ayse.person)
    on.shadow = _rating(
        on, on.ayse.person, cid="G2", status="shadow", verdict="not_met"
    )
    on.contested_live = _rating(
        on,
        on.ayse.person,
        verdict="unclear",
        contested_at=datetime.utcnow(),
        contest_note="wrong context",
    )
    return on


# ── who sees which rating ────────────────────────────────────────────────────


def test_the_person_sees_every_rating_including_shadow_and_contested(rated):
    o = rated
    v = _get(o, "/me", o.ayse.user).json()
    assert _ids(v) == {o.live.id, o.shadow.id, o.contested_live.id}
    by = {e["id"]: e for d in v["days"] for e in d["ratings"]}
    assert by[o.shadow.id]["status"] == "shadow"
    assert by[o.contested_live.id]["contested"] is True
    assert by[o.contested_live.id]["contest_note"] == "wrong context"


def test_the_direct_manager_sees_only_live_uncontested_ratings(rated):
    o = rated
    v = _get(o, f"/people/{o.ayse.person.id}", o.mert.user).json()
    assert _ids(v) == {o.live.id}
    crit = {(e["criterion_id"], e["status"]): e for e in v["ratings"]}
    assert set(crit) == {("G1", "live")}
    assert (crit[("G1", "live")]["met"], crit[("G1", "live")]["unclear"]) == (1, 0)


def test_person_view_defaults_to_the_safe_manager_view(rated):
    o = rated
    safe = wr.person_view(o.db, o.ayse.person)
    assert {e["id"] for d in safe["days"] for e in d["ratings"]} == {o.live.id}
    full = wr.person_view(o.db, o.ayse.person, as_subject=True)
    assert len({e["id"] for d in full["days"] for e in d["ratings"]}) == 3


def test_totals_are_counts_per_criterion_version_and_never_a_score(rated):
    o = rated
    _rating(o, o.ayse.person, verdict="not_met")
    v = _get(o, "/me", o.ayse.user).json()
    g1 = [e for e in v["ratings"] if e["criterion_id"] == "G1"][0]
    assert (g1["met"], g1["not_met"], g1["unclear"], g1["contested"]) == (1, 1, 1, 1)
    assert not any(k in json.dumps(v) for k in ("score", "average"))


def test_a_reworded_criterion_is_a_separate_row_in_the_totals(on):
    _rating(on, on.ayse.person, chash="old")
    _rating(on, on.ayse.person, chash="new")
    v = _get(on, "/me", on.ayse.user).json()
    assert {e["criterion_hash"] for e in v["ratings"]} == {"old", "new"}


def test_the_question_is_shown_only_for_the_current_criterion_version(on):
    wr._put(on.db, f"work_review.rubric:{on.co.id}", RUBRIC)
    on.db.commit()
    current = rb.criterion_hash(rt.load_rubric(on.db, on.co.id)[0].criteria[0])
    _rating(on, on.ayse.person, chash=current)
    _rating(on, on.ayse.person, chash="stale")
    for who, path in (
        (on.ayse.user, "/me"),
        (on.mert.user, f"/people/{on.ayse.person.id}"),
    ):
        v = _get(on, path, who).json()
        q = {e["criterion_hash"]: e["question"] for e in v["ratings"]}
        assert q[current] == "Does this work advance recurring revenue?"
        assert q["stale"] is None


def test_ratings_of_a_company_with_work_review_off_are_not_served(org):
    _rating(org, org.ayse.person)
    assert _get(org, "/me", org.ayse.user).status_code == 404


# ── contesting ───────────────────────────────────────────────────────────────


def _contest(o, user, rating_id, note="This was a rehearsal."):
    _as(o.client, user)
    return o.client.post(
        f"/work-review/me/ratings/{rating_id}/contest", json={"note": note}
    )


def test_contesting_hides_the_rating_from_the_manager_and_is_audited_without_the_note(
    on,
):
    r = _rating(on, on.ayse.person)
    assert _ids(_get(on, f"/people/{on.ayse.person.id}", on.mert.user).json()) == {r.id}
    res = _contest(on, on.ayse.user, r.id, "SECRET-REASON")
    assert res.status_code == 200 and res.json()["contested"] is True
    assert _ids(_get(on, f"/people/{on.ayse.person.id}", on.mert.user).json()) == set()
    mine = _get(on, "/me", on.ayse.user).json()
    assert _ids(mine) == {r.id}
    ev = on.db.exec(
        select(models.AuditEvent).where(
            models.AuditEvent.action == "work_rating_contested"
        )
    ).all()
    assert len(ev) == 1 and ev[0].actor_id == on.ayse.user.id
    assert "SECRET-REASON" not in (ev[0].payload_json or "") + (ev[0].reason or "")


def test_withdrawing_a_contest_puts_the_rating_back(on):
    r = _rating(on, on.ayse.person)
    _contest(on, on.ayse.user, r.id)
    _as(on.client, on.ayse.user)
    assert (
        on.client.delete(f"/work-review/me/ratings/{r.id}/contest").status_code == 204
    )
    assert _ids(_get(on, f"/people/{on.ayse.person.id}", on.mert.user).json()) == {r.id}
    on.db.expire_all()
    row = on.db.get(models.WorkRating, r.id)
    assert row.contest_note is None and row.contested_at is None


def test_nobody_can_contest_someone_elses_rating(on):
    r = _rating(on, on.ayse.person)
    for who in (on.bora, on.mert, on.dana):
        assert _contest(on, who.user, r.id).status_code == 404
    assert _contest(on, on.ayse.user, "no-such-rating").status_code == 404
    _as(on.client, on.bora.user)
    assert (
        on.client.delete(f"/work-review/me/ratings/{r.id}/contest").status_code == 404
    )


@pytest.mark.parametrize("note", ["", "x" * 1001])
def test_contest_note_validation(on, note):
    r = _rating(on, on.ayse.person)
    assert _contest(on, on.ayse.user, r.id, note).status_code == 422


def test_contesting_needs_work_review_to_be_on(org):
    r = _rating(org, org.ayse.person)
    assert _contest(org, org.ayse.user, r.id).status_code == 404


# ── resolving ────────────────────────────────────────────────────────────────


def _resolve(o, user, rating_id):
    _as(o.client, user)
    return o.client.post(f"/work-review/ratings/{rating_id}/resolve")


def _role(o, who, role, scope_id=None):
    m = o.db.exec(
        select(models.CompanyMember).where(
            models.CompanyMember.user_id == who.user.id,
            models.CompanyMember.company_id == o.co.id,
        )
    ).one()
    m.role, m.scope_id = role, scope_id
    o.db.add(m)
    o.db.commit()


def test_a_department_head_above_the_person_resolves_and_the_rating_rejoins(on):
    r = _rating(on, on.ayse.person)
    _contest(on, on.ayse.user, r.id, "It was a rehearsal.")
    _role(on, on.dana, "dept_head", on.finance.id)  # Accounting sits under Finance
    res = _resolve(on, on.dana.user, r.id)
    assert res.status_code == 200 and res.json()["resolved"] is True
    seen = _get(on, f"/people/{on.ayse.person.id}", on.mert.user).json()
    (entry,) = [e for d in seen["days"] for e in d["ratings"]]
    assert (
        entry["id"] == r.id
        and entry["contested"] is False
        and entry["resolved"] is True
    )
    assert entry["contest_note"] == "It was a rehearsal."  # the note travels with it
    assert (
        len(
            on.db.exec(
                select(models.AuditEvent).where(
                    models.AuditEvent.action == "work_rating_resolved"
                )
            ).all()
        )
        == 1
    )


def test_the_direct_manager_and_the_person_cannot_resolve_even_as_dept_head(on):
    r = _rating(on, on.ayse.person)
    _contest(on, on.ayse.user, r.id)
    _role(on, on.mert, "dept_head", on.finance.id)
    _role(on, on.ayse, "dept_head", on.finance.id)
    assert _resolve(on, on.mert.user, r.id).status_code == 403
    assert _resolve(on, on.ayse.user, r.id).status_code == 403


def test_a_plain_user_or_a_head_of_another_department_cannot_resolve(on):
    r = _rating(on, on.ayse.person)
    _contest(on, on.ayse.user, r.id)
    assert _resolve(on, on.dana.user, r.id).status_code == 403  # role "user"
    other = models.Department(company_id=on.co.id, name="Legal", slug="legal")
    on.db.add(other)
    on.db.commit()
    _role(on, on.dana, "dept_head", other.id)
    assert _resolve(on, on.dana.user, r.id).status_code == 403


def test_resolving_something_not_under_contest_is_a_conflict(on):
    r = _rating(on, on.ayse.person)
    _role(on, on.dana, "dept_head", on.finance.id)
    assert _resolve(on, on.dana.user, r.id).status_code == 409
    assert _resolve(on, on.dana.user, "no-such-rating").status_code == 404
    _contest(on, on.ayse.user, r.id)
    assert _resolve(on, on.dana.user, r.id).status_code == 200
    assert _resolve(on, on.dana.user, r.id).status_code == 409  # already resolved


def test_contesting_again_after_resolution_reopens_it(on):
    r = _rating(on, on.ayse.person)
    _contest(on, on.ayse.user, r.id)
    _role(on, on.dana, "dept_head", on.finance.id)
    _resolve(on, on.dana.user, r.id)
    assert _contest(on, on.ayse.user, r.id, "New evidence.").json()["contested"] is True
    assert _ids(_get(on, f"/people/{on.ayse.person.id}", on.mert.user).json()) == set()


# ── the company switch ───────────────────────────────────────────────────────


def test_rating_needs_work_review_first_and_its_own_acknowledgement(org):
    r = _put(org, org.founder, rating_enabled=True, acknowledge_notice=True)
    assert r.status_code == 422 and "work review" in r.json()["detail"]
    _put(org, org.founder, enabled=True, acknowledge_notice=True)
    r = _put(org, org.founder, rating_enabled=True)
    assert r.status_code == 422 and "scoring model" in r.json()["detail"]
    org.db.expire_all()
    assert rt.rating_enabled(org.db, org.co.id) is False
    ok = _put(org, org.founder, rating_enabled=True, acknowledge_notice=True)
    assert ok.status_code == 200 and ok.json()["rating_enabled"] is True
    org.db.expire_all()
    assert rt.rating_enabled(org.db, org.co.id) is True
    p = json.loads(
        org.db.exec(
            select(models.AuditEvent)
            .where(models.AuditEvent.action == "work_review_settings_changed")
            .order_by(models.AuditEvent.created_at.desc())
        )
        .first()
        .payload_json
    )
    assert (
        p["before"]["rating_enabled"] is False and p["after"]["rating_enabled"] is True
    )


def test_switching_rating_off_needs_no_ceremony_and_get_reports_it(on):
    _put(on, on.founder, rating_enabled=True, acknowledge_notice=True)
    off = _put(on, on.founder, rating_enabled=False)
    assert off.status_code == 200 and off.json()["rating_enabled"] is False
    _as(on.client, on.founder)
    assert on.client.get("/work-review/settings").json()["rating_enabled"] is False


def test_turning_work_review_off_stops_rating_too(on):
    _put(on, on.founder, rating_enabled=True, acknowledge_notice=True)
    _put(on, on.founder, enabled=False)
    on.db.expire_all()
    assert rt.rating_enabled(on.db, on.co.id) is False


# ── team and department aggregates ───────────────────────────────────────────


def _team(o, leader="Mert"):
    teams = {t["leader"]["name"]: t for t in _get(o, "/teams", o.dana.user).json()}
    return teams[leader]


def _rows(agg):
    return {(e["criterion_id"], e["criterion_hash"]): e for e in agg["ratings"]}


def _three_raters(o, verdicts=("met", "met", "not_met"), **kw):
    return [
        _rating(o, who.person, verdict=v, **kw)
        for who, v in zip((o.ayse, o.bora, o.cem), verdicts)
    ]


def test_team_aggregate_counts_live_ratings_per_criterion_version(on):
    _three_raters(on)
    a = _team(on)
    (row,) = a["ratings"]
    assert (row["criterion_id"], row["met"], row["not_met"], row["unclear"]) == (
        "G1",
        2,
        1,
        0,
    )
    assert row["n_people"] == 3 and row["status"] == "live"
    assert a["ratings_hidden"] == 0


def test_shadow_and_contested_ratings_never_reach_an_aggregate(on):
    _three_raters(on)
    _rating(on, on.ayse.person, status="shadow", verdict="not_met")
    _rating(on, on.bora.person, verdict="unclear", contested_at=datetime.utcnow())
    (row,) = _team(on)["ratings"]
    assert (row["met"], row["not_met"], row["unclear"]) == (2, 1, 0)


def test_a_criterion_rated_on_fewer_than_the_floor_of_people_is_held_back(on):
    _rating(on, on.ayse.person)
    _rating(on, on.ayse.person, verdict="not_met")  # many ratings, but one person
    _rating(on, on.bora.person)
    a = _team(on)
    assert a["ratings"] == [] and a["ratings_hidden"] == 1
    _rating(on, on.cem.person)
    a = _team(on)
    assert len(a["ratings"]) == 1 and a["ratings_hidden"] == 0


def test_a_contest_can_pull_a_criterion_below_the_floor(on):
    rs = _three_raters(on)
    assert len(_team(on)["ratings"]) == 1
    _contest(on, on.cem.user, rs[2].id)
    a = _team(on)
    assert a["ratings"] == [] and a["ratings_hidden"] == 1


def test_the_floor_setting_applies_to_criteria_too(on, monkeypatch):
    _rating(on, on.ayse.person)
    _rating(on, on.bora.person)
    assert _team(on)["ratings_hidden"] == 1
    monkeypatch.setenv("WORK_REVIEW_MIN_GROUP", "2")
    assert len(_team(on)["ratings"]) == 1


def test_a_suppressed_small_team_has_no_ratings_at_all(on):
    _rating(on, on.efe.person)
    _rating(on, on.gul.person)
    lale = _team(on, "Lale")  # two people: the whole team is suppressed
    assert lale["suppressed"] is True
    assert "ratings" not in lale and "ratings_hidden" not in lale


def test_aggregates_do_not_identify_anyone_or_mix_in_other_teams(on):
    _three_raters(on)
    for who in (on.efe, on.gul):  # Lale's team, different criterion
        _rating(on, who.person, cid="OTHER")
    blob = json.dumps(_team(on))
    for name in ("Ayşe", "Bora", "Cem", on.ayse.person.id, on.bora.person.id):
        assert name not in blob
    assert "OTHER" not in blob
    assert not any(k in blob for k in ("score", "average_rating"))


def test_old_ratings_fall_outside_the_window(on):
    from datetime import timedelta

    old = TODAY - timedelta(days=40)
    for who in (on.ayse, on.bora, on.cem):
        _rating(on, who.person, day=old)
    assert _team(on)["ratings"] == []
    _as(on.client, on.dana.user)
    wide = on.client.get("/work-review/teams", params={"days": 90}).json()
    mert = {t["leader"]["name"]: t for t in wide}["Mert"]
    assert len(mert["ratings"]) == 1


def test_team_and_department_aggregates_carry_the_current_question(on):
    wr._put(on.db, f"work_review.rubric:{on.co.id}", RUBRIC)
    on.db.commit()
    current = rb.criterion_hash(rt.load_rubric(on.db, on.co.id)[0].criteria[0])
    for who in (on.ayse, on.bora, on.cem):
        _rating(on, who.person, chash=current)
    (row,) = _team(on)["ratings"]
    assert row["question"] == "Does this work advance recurring revenue?"
    dept = {
        d["department"]["name"]: d for d in _get(on, "/departments", on.founder).json()
    }
    assert dept["Accounting"]["ratings"][0]["question"] == row["question"]


def test_department_aggregate_counts_everyone_in_the_department(on):
    for who in (on.ayse, on.bora, on.efe):  # two teams, one department
        _rating(on, who.person)
    dept = {
        d["department"]["name"]: d for d in _get(on, "/departments", on.founder).json()
    }
    (row,) = dept["Accounting"]["ratings"]
    assert row["met"] == 3 and row["n_people"] == 3
    assert dept["Finance"]["suppressed"] is True  # only Dana: nothing to show


def test_aggregate_reads_are_audited_without_content(on):
    _three_raters(on)
    _team(on)
    ev = on.db.exec(
        select(models.AuditEvent).where(
            models.AuditEvent.action == "work_review_viewed"
        )
    ).all()
    assert len(ev) >= 1 and "G1" not in "".join(e.payload_json or "" for e in ev)


def test_another_teams_ratings_cannot_lift_a_criterion_over_this_teams_floor(on):
    # Mert's team: 2 raters of G1 (below the floor of 3). Lale's team: 2 more raters of
    # the same criterion. If other teams leaked in, Mert's team would show 4.
    _rating(on, on.ayse.person)
    _rating(on, on.bora.person)
    for who in (on.efe, on.gul):
        _rating(on, who.person)
    a = _team(on)
    assert a["ratings"] == [] and a["ratings_hidden"] == 1
    # and the counts of a shown criterion are this team's own
    _rating(on, on.cem.person)
    (row,) = _team(on)["ratings"]
    assert row["met"] == 3 and row["n_people"] == 3
