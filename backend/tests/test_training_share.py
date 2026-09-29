"""A person may share a training-need signal with their direct manager, and a team leader
sees their own team's finding (ADR-0021 §6, option B)."""

import json
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

import models
from services import rating as rt
from services import rubric as rb
from services import training_need as tn
from services import work_review as wr
from tests.test_training_need import _many, _put
from tests.test_work_rating_views import RUBRIC
from tests.test_work_review import (  # noqa: F401
    TODAY,
    _as,
    _cheap_password_hash,
    _get,
    on,
    org,
)


def _share(o, user, crit="G1", chash="h1"):
    _as(o.client, user)
    return o.client.post(
        "/work-review/me/training-need/share",
        json={"criterion_id": crit, "criterion_hash": chash},
    )


def _unshare(o, user, crit="G1", chash="h1"):
    _as(o.client, user)
    return o.client.delete(
        "/work-review/me/training-need/share",
        params={"criterion_id": crit, "criterion_hash": chash},
    )


@pytest.fixture()
def signalled(on):
    """Ayşe has a training-need signal on G1; the company allows sharing."""
    _many(on, on.ayse, met=3, not_met=7)
    assert _put(on, on.founder, sharing_enabled=True).status_code == 200
    return on


def _support(o):
    r = _get(o, f"/people/{o.ayse.person.id}", o.mert.user)
    assert r.status_code == 200
    return r.json().get("support_requests")


# ── the company switch ───────────────────────────────────────────────────────


def test_sharing_is_off_until_the_company_turns_it_on(on):
    _many(on, on.ayse, met=3, not_met=7)
    assert _share(on, on.ayse.user).status_code == 404
    assert _get(on, "/me", on.ayse.user).json()["training_sharing_enabled"] is False
    assert _support(on) is None  # the key is absent, not empty
    _put(on, on.founder, sharing_enabled=True)
    assert _get(on, "/me", on.ayse.user).json()["training_sharing_enabled"] is True
    assert _support(on) == []


def test_only_the_founder_can_switch_sharing(on):
    for who in (on.dana, on.mert, on.ayse):
        assert _put(on, who.user, sharing_enabled=True).status_code == 403
    on.db.expire_all()
    assert tn.sharing_enabled(on.db, on.co.id) is False


def test_turning_sharing_off_hides_existing_shares_without_deleting_consent(signalled):
    o = signalled
    _share(o, o.ayse.user)
    assert len(_support(o)) == 1
    _put(o, o.founder, sharing_enabled=False)
    assert _support(o) is None
    _put(o, o.founder, sharing_enabled=True)
    assert len(_support(o)) == 1  # her earlier choice still stands


# ── sharing ──────────────────────────────────────────────────────────────────


def test_nothing_is_shared_by_default_even_when_sharing_is_allowed(signalled):
    assert _support(signalled) == []


def test_a_shared_signal_reaches_only_the_direct_manager_framed_as_a_request(signalled):
    o = signalled
    r = _share(o, o.ayse.user)
    assert r.status_code == 201 and r.json()["shared"] is True
    (s,) = _support(o)
    assert s["kind"] == "support_requested" and s["criterion_id"] == "G1"
    assert (s["rated"], s["not_met"]) == (10, 7)
    # nobody else gets it: skip-level, peer, other team, and the aggregates
    for who in (o.dana, o.bora, o.lale, o.efe):
        assert _get(o, f"/people/{o.ayse.person.id}", who.user).status_code == 403
    blob = json.dumps(_get(o, "/teams", o.dana.user).json()) + json.dumps(
        _get(o, "/departments", o.founder).json()
    )
    assert "support_requested" not in blob and "training_need" not in blob
    # and it is not the manager's copy of the person's other, unshared signals
    _many(o, o.ayse, met=3, not_met=7, cid="G9")
    assert [e["criterion_id"] for e in _support(o)] == ["G1"]


def test_the_person_sees_that_it_is_shared_and_can_withdraw(signalled):
    o = signalled
    _share(o, o.ayse.user)
    (mine,) = _get(o, "/me", o.ayse.user).json()["training_need"]
    assert mine["shared"] is True
    assert _unshare(o, o.ayse.user).status_code == 204
    assert _support(o) == []
    (mine,) = _get(o, "/me", o.ayse.user).json()["training_need"]
    assert mine["shared"] is False
    assert _unshare(o, o.ayse.user).status_code == 204  # withdrawing twice is harmless


def test_sharing_twice_is_one_share(signalled):
    o = signalled
    assert _share(o, o.ayse.user).status_code == 201
    assert _share(o, o.ayse.user).status_code == 201
    assert len(o.db.exec(select(models.WorkTrainingShare)).all()) == 1


def test_you_can_only_share_a_signal_you_currently_have(signalled):
    o = signalled
    assert _share(o, o.ayse.user, crit="G-none").status_code == 409
    assert _share(o, o.ayse.user, chash="other-wording").status_code == 409
    assert _share(o, o.bora.user).status_code == 409  # Bora has no signal
    assert o.db.exec(select(models.WorkTrainingShare)).all() == []


def test_a_signal_that_no_longer_holds_disappears_from_the_managers_view(signalled):
    o = signalled
    _share(o, o.ayse.user)
    assert len(_support(o)) == 1
    _many(o, o.ayse, met=30)  # her work improved: 7 of 40 is below the bar
    assert _support(o) == []
    o.db.expire_all()
    assert len(o.db.exec(select(models.WorkTrainingShare)).all()) == 1  # consent stays


def test_a_reworded_criterion_is_not_covered_by_the_earlier_consent(signalled):
    o = signalled
    _share(o, o.ayse.user)
    _many(o, o.ayse, met=3, not_met=7, chash="h2")  # a new wording with its own signal
    assert [e["criterion_hash"] for e in _support(o)] == ["h1"]


def test_shares_are_audited_without_content(signalled):
    o = signalled
    _share(o, o.ayse.user)
    _unshare(o, o.ayse.user)
    acts = [
        e
        for e in o.db.exec(select(models.AuditEvent)).all()
        if e.action in ("work_training_shared", "work_training_unshared")
    ]
    assert [e.action for e in acts] == [
        "work_training_shared",
        "work_training_unshared",
    ]
    assert all(e.actor_id == o.ayse.user.id for e in acts)
    assert not any(
        k in "".join(e.payload_json or "" for e in acts) for k in ("rated", "not_met")
    )


def test_the_question_is_shown_to_the_manager_for_the_current_wording(signalled):
    o = signalled
    wr._put(o.db, f"work_review.rubric:{o.co.id}", RUBRIC)
    o.db.commit()
    current = rb.criterion_hash(rt.load_rubric(o.db, o.co.id)[0].criteria[0])
    _many(o, o.ayse, met=3, not_met=7, chash=current)
    _share(o, o.ayse.user, chash=current)
    (s,) = _support(o)
    assert s["question"] == "Does this work advance recurring revenue?"


def test_shares_expire_with_retention_and_are_erased_with_the_person(signalled):
    o = signalled
    _share(o, o.ayse.user)
    row = o.db.exec(select(models.WorkTrainingShare)).one()
    row.shared_at = datetime.utcnow() - timedelta(days=400)
    o.db.add(row)
    o.db.commit()
    assert wr.purge_expired() >= 1
    o.db.expire_all()
    assert o.db.exec(select(models.WorkTrainingShare)).all() == []
    _share(o, o.ayse.user)
    assert wr.erase_person(o.db, o.ayse.person.id) >= 1
    o.db.commit()
    assert o.db.exec(select(models.WorkTrainingShare)).all() == []


def test_sharing_requires_work_review_to_be_on(org):
    assert _share(org, org.ayse.user).status_code == 404


# ── the team leader's own team ───────────────────────────────────────────────


def _team_finding(o, who):
    _as(o.client, who.user)
    return o.client.get("/work-review/training-need/my-team")


def test_a_team_leader_sees_their_teams_finding_without_names(on):
    for who in (on.ayse, on.bora, on.cem):
        _many(on, who, met=1, not_met=3)
    r = _team_finding(on, on.mert)
    assert r.status_code == 200
    body = r.json()
    assert body["suppressed"] is False and body["n_people"] == 3
    (f,) = body["findings"]
    assert f["reading"] == "rule_or_training_unclear" and f["n_people_not_met"] == 3
    blob = json.dumps(body)
    for name in ("Ayşe", "Bora", "Cem", on.ayse.person.id):
        assert name not in blob


def test_a_team_below_the_floor_says_nothing(on):
    _many(on, on.efe, not_met=12)
    _many(on, on.gul, not_met=12)
    r = _team_finding(on, on.lale)  # two reports
    assert r.json() == {"n_people": 2, "suppressed": True, "findings": []}


def test_people_without_reports_get_no_team_finding(on):
    for who in (on.ayse, on.efe):
        assert _team_finding(on, who).status_code == 403


def test_a_leader_sees_only_their_own_team(on):
    for who in (on.efe, on.gul, on.ayse):  # spread across two teams
        _many(on, who, met=1, not_met=3)
    assert _team_finding(on, on.mert).json()["findings"] == []
    assert _team_finding(on, on.lale).json()["suppressed"] is True


def test_the_team_read_is_audited_without_content(on):
    for who in (on.ayse, on.bora, on.cem):
        _many(on, who, met=1, not_met=3)
    _team_finding(on, on.mert)
    ev = on.db.exec(
        select(models.AuditEvent).where(
            models.AuditEvent.action == "work_review_viewed"
        )
    ).all()
    assert any(e.reason == "training_team" for e in ev)
    assert "G1" not in "".join(e.payload_json or "" for e in ev)


def test_nothing_is_served_while_work_review_is_off(org):
    assert _team_finding(org, org.mert).status_code == 404


def test_the_service_itself_returns_nothing_while_sharing_is_off(signalled):
    o = signalled
    _share(o, o.ayse.user)
    assert len(tn.shared_signals(o.db, o.ayse.person)) == 1
    tn.set_sharing_enabled(o.db, o.co.id, False)
    o.db.commit()
    assert tn.shared_signals(o.db, o.ayse.person) == []
