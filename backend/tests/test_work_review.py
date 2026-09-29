"""
Work review (ADR-0019 §6), first slice: hard signals and tags from the audit chain,
and who may see them. The guardrails are what is under test: off by default, hierarchy
visibility, no separate manager view, small-group suppression, notes, audit of every
read, retention and erasure.
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import select

import models
from services import audit_chain
from services import work_review as wr
from services.auth import create_access_token
from services.workspace_agent import ensure_workspace_agent
from tests.conftest import (
    make_agent_config,
    make_company,
    make_member,
    make_personnel,
    make_user,
)

TODAY = datetime.utcnow().date()


@pytest.fixture(autouse=True)
def _cheap_password_hash(monkeypatch):
    """These tests mint JWTs directly and never log in, so skip bcrypt (9+ users per test)."""
    monkeypatch.setattr("tests.conftest.hash_password", lambda password: "x")


def _as(client, user):
    client.headers["Authorization"] = f"Bearer {create_access_token(user.id)}"


def _event(co, persona_id, action, payload, actor_type="agent"):
    audit_chain.record(
        actor_type=actor_type,
        actor_id=persona_id,
        company_id=co.id,
        action=action,
        payload=payload,
    )


def _decision(co, agent, effect, enforced, **kw):
    _event(
        co,
        agent.id,
        "policy_decision",
        {"effect": effect, "enforced": enforced, "fail_closed": False, **kw},
    )


def _tags(co, agent, **tags):
    _event(co, agent.id, "intent_classified", {"tags": tags}, actor_type="system")


@pytest.fixture()
def org(auth_client, db_session):
    """Finance ⊃ Accounting. Dana (director) → Mert (manager, 3 reports: Ayşe, Bora, Cem)
    and Lale (manager, 2 reports: Efe, Gül). Everyone has a user and a workspace agent."""
    co, founder = auth_client._test_company, auth_client._test_user
    finance = models.Department(company_id=co.id, name="Finance", slug="finance")
    db_session.add(finance)
    db_session.flush()
    accounting = models.Department(
        company_id=co.id, name="Accounting", slug="acc", parent_id=finance.id
    )
    db_session.add(accounting)
    db_session.flush()

    def human(name, manager=None, dept=None):
        slug = name.lower().replace("ş", "s").replace("ü", "u")
        user = make_user(db_session, f"{slug}@t.com", name)
        make_member(db_session, user.id, co.id, "user")
        p = models.Personnel(
            company_id=co.id,
            name=name,
            slug=slug,
            type="human",
            user_id=user.id,
            manager_id=manager.person.id if manager else None,
            department_id=dept.id if dept else None,
        )
        db_session.add(p)
        db_session.flush()
        agent = ensure_workspace_agent(db_session, p)
        db_session.commit()
        return SimpleNamespace(user=user, person=p, agent=agent, name=name)

    o = SimpleNamespace(
        client=auth_client,
        co=co,
        founder=founder,
        finance=finance,
        accounting=accounting,
        db=db_session,
    )
    o.dana = human("Dana", None, finance)
    o.mert = human("Mert", o.dana, accounting)
    o.ayse, o.bora, o.cem = (
        human(n, o.mert, accounting) for n in ("Ayşe", "Bora", "Cem")
    )
    o.lale = human("Lale", o.dana, accounting)
    o.efe, o.gul = (human(n, o.lale, accounting) for n in ("Efe", "Gül"))
    return o


@pytest.fixture()
def on(org):
    wr.set_enabled(org.db, org.co.id, True)
    org.db.commit()
    return org


def _seed(o):
    """Ayşe: 2 refusals, 1 would-be refusal, 1 approval asked, tags. Bora: 1 refusal. Efe: 5."""
    for _ in range(2):
        _decision(o.co, o.ayse.agent, "deny", True)
    _decision(o.co, o.ayse.agent, "deny", False)
    _decision(o.co, o.ayse.agent, "ask", True)
    _tags(o.co, o.ayse.agent, task="analysis", sensitivity="financial", domain="acc")
    _tags(o.co, o.ayse.agent, task="analysis")
    _decision(o.co, o.bora.agent, "deny", True)
    for _ in range(5):
        _decision(o.co, o.efe.agent, "deny", True)
    wr.rollup_day(o.db, o.co.id, TODAY)


def _get(o, path, user=None, **params):
    if user is not None:
        _as(o.client, user)
    return o.client.get(f"/work-review{path}", params=params)


# ── deriving signals ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action,payload,expected",
    [
        (
            "policy_decision",
            {"effect": "deny", "enforced": True},
            [("policy_denied", "")],
        ),
        (
            "policy_decision",
            {"effect": "deny", "enforced": False},
            [("policy_would_deny", "")],
        ),
        (
            "policy_decision",
            {"effect": "ask", "enforced": True},
            [("approval_asked", "")],
        ),
        (
            "policy_decision",
            {"effect": "ask", "enforced": False},
            [("policy_would_ask", "")],
        ),
        ("policy_decision", {"effect": "allow", "enforced": False}, []),
        (
            "policy_decision",
            {"effect": "deny", "enforced": True, "fail_closed": True},
            [],
        ),
        (
            "intent_classified",
            {
                "tags": {
                    "task": "analysis",
                    "sensitivity": "financial",
                    "domain": "acc",
                    "x": "y",
                }
            },
            [
                ("tag_task", "analysis"),
                ("tag_sensitivity", "financial"),
                ("tag_domain", "acc"),
            ],
        ),
        ("intent_classified", {"tags": {"task": "  "}}, []),
        ("intent_classified", {"tags": {"task": 5}}, []),
        ("intent_classified", {"tags": "nope"}, []),
        ("gateway_call", {"tokens_in": 9}, []),
        ("tool_event", {}, []),
    ],
)
def test_increments(action, payload, expected):
    assert wr.increments(action, payload) == expected


def test_tag_values_are_clipped():
    ((kind, value),) = wr.increments(
        "intent_classified", {"tags": {"domain": "d" * 500}}
    )
    assert kind == "tag_domain" and len(value) == 80


def test_events_roll_up_to_the_responsible_human(on):
    _seed(on)
    rows = {
        (r.personnel_id, r.kind, r.value): r.count
        for r in on.db.exec(select(models.WorkSignal)).all()
    }
    assert rows[(on.ayse.person.id, "policy_denied", "")] == 2
    assert rows[(on.ayse.person.id, "policy_would_deny", "")] == 1
    assert rows[(on.ayse.person.id, "approval_asked", "")] == 1
    assert rows[(on.ayse.person.id, "tag_task", "analysis")] == 2
    assert rows[(on.ayse.person.id, "tag_sensitivity", "financial")] == 1
    assert rows[(on.bora.person.id, "policy_denied", "")] == 1
    assert rows[(on.efe.person.id, "policy_denied", "")] == 5
    assert not any(r[0] == on.cem.person.id for r in rows)


def test_agents_with_no_responsible_human_and_other_companies_are_ignored(on):
    loose = make_personnel(
        on.db, on.co.id, name="Loose", slug="loose"
    )  # an agent with no owner
    make_agent_config(on.db, loose.id)
    other = make_company(on.db, name="Other", slug="other")
    on.db.commit()
    _decision(on.co, loose, "deny", True)
    _event(
        other, on.ayse.agent.id, "policy_decision", {"effect": "deny", "enforced": True}
    )
    wr.rollup_day(on.db, on.co.id, TODAY)
    assert on.db.exec(select(models.WorkSignal)).all() == []


def test_rollup_is_idempotent_and_replaces_the_day(on):
    _seed(on)
    first = sorted(
        (r.personnel_id, r.kind, r.value, r.count)
        for r in on.db.exec(select(models.WorkSignal)).all()
    )
    stale = models.WorkSignal(
        personnel_id=on.cem.person.id,
        day=TODAY.isoformat(),
        kind="policy_denied",
        company_id=on.co.id,
        count=99,
    )
    on.db.add(stale)
    on.db.commit()
    wr.rollup_day(on.db, on.co.id, TODAY)
    wr.rollup_day(on.db, on.co.id, TODAY)
    again = sorted(
        (r.personnel_id, r.kind, r.value, r.count)
        for r in on.db.exec(select(models.WorkSignal)).all()
    )
    assert again == first, "re-running must neither double count nor keep stale rows"


def test_rollup_only_touches_companies_that_enabled_it(org):
    _decision(org.co, org.ayse.agent, "deny", True)
    assert wr.rollup_recent() == {"companies": 0, "rows": 0}
    assert org.db.exec(select(models.WorkSignal)).all() == []
    wr.set_enabled(org.db, org.co.id, True)
    org.db.commit()
    out = wr.rollup_recent()
    assert out["companies"] == 1 and out["rows"] >= 1


# ── settings ──────────────────────────────────────────────────────────────────


def test_off_by_default_and_there_is_no_global_switch(org):
    assert wr.enabled(org.db, org.co.id) is False
    org.db.add(models.AppConfig(key="work_review.enabled", value="true"))
    org.db.commit()
    assert wr.enabled(org.db, org.co.id) is False


def test_retention_and_min_group_settings(org, monkeypatch):
    assert wr.retention_days(org.db, org.co.id) == 365
    wr.set_retention_days(org.db, org.co.id, 90)
    assert wr.retention_days(org.db, org.co.id) == 90
    org.db.merge(
        models.AppConfig(key=f"work_review.retention_days:{org.co.id}", value="banana")
    )
    assert wr.retention_days(org.db, org.co.id) == 365
    monkeypatch.delenv("WORK_REVIEW_MIN_GROUP", raising=False)
    assert wr.min_group() == 3
    monkeypatch.setenv("WORK_REVIEW_MIN_GROUP", "1")
    assert wr.min_group() == 2, "a group of one is a person"
    monkeypatch.setenv("WORK_REVIEW_MIN_GROUP", "x")
    assert wr.min_group() == 3


# ── retention and erasure ─────────────────────────────────────────────────────


def _row(o, person, day, count=1, kind="policy_denied"):
    o.db.add(
        models.WorkSignal(
            personnel_id=person.person.id,
            day=day.isoformat(),
            kind=kind,
            company_id=o.co.id,
            count=count,
        )
    )


def test_purge_expired_respects_each_companys_retention(on):
    old, recent = TODAY - timedelta(days=400), TODAY - timedelta(days=10)
    _row(on, on.ayse, old)
    _row(on, on.ayse, recent, kind="approval_asked")
    on.db.add(
        models.WorkNote(
            personnel_id=on.ayse.person.id,
            company_id=on.co.id,
            day=old.isoformat(),
            text="old",
        )
    )
    on.db.add(
        models.WorkNote(
            personnel_id=on.ayse.person.id,
            company_id=on.co.id,
            day=recent.isoformat(),
            text="new",
        )
    )
    on.db.commit()
    assert wr.purge_expired(TODAY) == 2
    assert [r.day for r in on.db.exec(select(models.WorkSignal)).all()] == [
        recent.isoformat()
    ]
    assert [n.text for n in on.db.exec(select(models.WorkNote)).all()] == ["new"]

    wr.set_retention_days(on.db, on.co.id, 5)
    on.db.commit()
    assert wr.purge_expired(TODAY) == 2  # now the 10-day-old rows expire too


def test_purge_also_covers_a_company_that_switched_it_off(on):
    _row(on, on.ayse, TODAY - timedelta(days=500))
    wr.set_enabled(on.db, on.co.id, False)
    on.db.commit()
    assert wr.purge_expired(TODAY) == 1


def test_deleting_a_person_erases_their_review(on):
    _row(on, on.ayse, TODAY)
    _row(on, on.bora, TODAY)
    on.db.add(
        models.WorkNote(
            personnel_id=on.ayse.person.id,
            company_id=on.co.id,
            day=TODAY.isoformat(),
            text="n",
        )
    )
    on.db.commit()
    _as(on.client, on.founder)
    assert on.client.delete(f"/personnel/{on.ayse.person.id}").status_code == 204
    on.db.expire_all()
    left = on.db.exec(select(models.WorkSignal)).all()
    assert [r.personnel_id for r in left] == [on.bora.person.id]
    assert on.db.exec(select(models.WorkNote)).all() == []


# ── a person's own review ─────────────────────────────────────────────────────


def test_a_person_sees_their_full_review_and_what_is_collected(on):
    _seed(on)
    v = _get(on, "/me", on.ayse.user).json()
    assert v["name"] == "Ayşe" and v["window_days"] == 30
    (day,) = v["days"]
    assert day["day"] == TODAY.isoformat()
    assert day["signals"] == {
        "policy_denied": 2,
        "policy_would_deny": 1,
        "approval_asked": 1,
    }
    assert day["tags"] == {
        "task": {"analysis": 2},
        "sensitivity": {"financial": 1},
        "domain": {"acc": 1},
    }
    assert v["totals"]["signals"]["policy_denied"] == 2
    d = v["disclosure"]
    assert set(d["collected"]["signals"]) == set(wr.SIGNAL_KINDS)
    assert (
        "keystrokes" in d["never_collected"] and "screenshots" in d["never_collected"]
    )
    assert d["minimum_group_size"] == 3 and d["retention_days"] == 365
    assert any("direct manager" in s for s in d["visible_to"])


def test_the_window_limits_what_is_shown(on):
    _row(on, on.ayse, TODAY, 1)
    _row(on, on.ayse, TODAY - timedelta(days=40), 7)
    on.db.commit()
    assert _get(on, "/me", on.ayse.user, days=30).json()["totals"]["signals"] == {
        "policy_denied": 1
    }
    assert _get(on, "/me", on.ayse.user, days=90).json()["totals"]["signals"] == {
        "policy_denied": 8
    }
    assert _get(on, "/me", on.ayse.user, days=0).status_code == 422
    assert _get(on, "/me", on.ayse.user, days=91).status_code == 422


def test_nothing_is_reachable_while_it_is_off(org):
    _as(org.client, org.ayse.user)
    for path in ("/me", "/teams", f"/people/{org.bora.person.id}"):
        assert org.client.get(f"/work-review{path}").status_code == 404, path
    _as(org.client, org.founder)
    assert org.client.get("/work-review/departments").status_code == 404
    assert org.client.post("/work-review/rollup").status_code == 404
    _as(org.client, org.ayse.user)
    assert (
        org.client.post(
            "/work-review/me/notes", json={"day": TODAY.isoformat(), "text": "x"}
        ).status_code
        == 404
    )


# ── who may see a person ──────────────────────────────────────────────────────


def test_only_the_direct_manager_sees_a_person_and_it_is_the_same_view(on):
    _seed(on)
    pid = on.ayse.person.id
    own = _get(on, "/me", on.ayse.user).json()
    theirs = _get(on, f"/people/{pid}", on.mert.user)
    assert theirs.status_code == 200
    own.pop("disclosure")
    assert theirs.json() == own, (
        "a manager must see exactly what the person sees — no richer view"
    )

    for who in (
        on.bora,
        on.ayse,
        on.dana,
        on.lale,
        on.efe,
    ):  # peer, self, skip-level, other team
        assert _get(on, f"/people/{pid}", who.user).status_code == 403, who.name
    assert _get(on, f"/people/{pid}", on.founder).status_code in (
        403,
        404,
    )  # not a person, not the manager
    assert _get(on, "/people/nobody", on.mert.user).status_code == 403


def test_a_manager_cannot_see_someone_elses_report_or_a_non_human(on):
    assert _get(on, f"/people/{on.efe.person.id}", on.mert.user).status_code == 403
    assert (
        _get(on, f"/people/{on.ayse.agent.id}", on.mert.user).status_code == 403
    )  # an agent persona


# ── team and department aggregates ────────────────────────────────────────────


def test_the_manager_above_sees_team_totals_never_people(on):
    _seed(on)
    teams = _get(on, "/teams", on.dana.user).json()
    by_leader = {t["leader"]["name"]: t for t in teams}
    assert set(by_leader) == {"Mert", "Lale"}
    mert = by_leader["Mert"]
    assert mert["n_people"] == 3 and mert["suppressed"] is False
    assert mert["signals"]["policy_denied"] == 3  # Ayşe 2 + Bora 1
    assert mert["per_person_average"]["policy_denied"] == 1.0
    blob = json.dumps(teams)
    for name in ("Ayşe", "Bora", "Cem", on.ayse.person.id):
        assert name not in blob, f"a team aggregate must not identify {name}"


def test_small_groups_are_suppressed(on):
    _seed(on)
    lale = {t["leader"]["name"]: t for t in _get(on, "/teams", on.dana.user).json()}[
        "Lale"
    ]
    assert lale == {
        "leader": {"id": on.lale.person.id, "name": "Lale"},
        "n_people": 2,
        "suppressed": True,
        "reason": "fewer than 3 people",
    }
    assert "signals" not in lale  # Efe's five refusals are not derivable from this


def test_the_group_floor_is_configurable_but_never_below_two(on, monkeypatch):
    _seed(on)
    monkeypatch.setenv("WORK_REVIEW_MIN_GROUP", "2")
    lale = {t["leader"]["name"]: t for t in _get(on, "/teams", on.dana.user).json()}[
        "Lale"
    ]
    assert lale["suppressed"] is False and lale["signals"]["policy_denied"] == 5
    monkeypatch.setenv("WORK_REVIEW_MIN_GROUP", "10")
    assert all(t["suppressed"] for t in _get(on, "/teams", on.dana.user).json())
    monkeypatch.setenv("WORK_REVIEW_MIN_GROUP", "1")
    assert {
        t["leader"]["name"]: t["suppressed"]
        for t in _get(on, "/teams", on.dana.user).json()
    }["Lale"] is False


def test_people_without_managed_teams_see_no_teams(on):
    for who in (on.mert, on.ayse, on.efe):
        assert _get(on, "/teams", who.user).json() == [], who.name


def test_department_heads_see_department_totals_within_their_scope(on):
    _seed(on)
    head = make_user(on.db, "head@t.com", "Head")
    m = make_member(on.db, head.id, on.co.id, "dept_head")
    m.scope_id = on.accounting.id
    on.db.add(m)
    fin_head = make_user(on.db, "fhead@t.com", "FHead")
    m2 = make_member(on.db, fin_head.id, on.co.id, "dept_head")
    m2.scope_id = on.finance.id
    on.db.add(m2)
    on.db.commit()

    acc = _get(on, "/departments", head).json()
    assert [d["department"]["name"] for d in acc] == ["Accounting"]
    assert acc[0]["n_people"] == 7 and acc[0]["suppressed"] is False
    assert acc[0]["signals"]["policy_denied"] == 2 + 1 + 5

    both = {
        d["department"]["name"]: d for d in _get(on, "/departments", fin_head).json()
    }
    assert set(both) == {"Finance", "Accounting"}  # the scope includes sub-departments
    assert (
        both["Finance"]["suppressed"] is True and both["Finance"]["n_people"] == 1
    )  # only Dana
    assert "Ayşe" not in json.dumps(both)

    everyone = {
        d["department"]["name"] for d in _get(on, "/departments", on.founder).json()
    }
    assert everyone == {"Finance", "Accounting"}
    assert _get(on, "/departments", on.ayse.user).status_code == 403  # a plain user


# ── the person's notes ────────────────────────────────────────────────────────


def _note(o, user, day=None, text="This was a training exercise."):
    _as(o.client, user)
    return o.client.post(
        "/work-review/me/notes", json={"day": (day or TODAY).isoformat(), "text": text}
    )


def test_a_note_travels_with_the_review_to_the_person_and_the_manager(on):
    _seed(on)
    r = _note(on, on.ayse.user)
    assert r.status_code == 201
    mine = _get(on, "/me", on.ayse.user).json()["days"][0]["notes"]
    theirs = _get(on, f"/people/{on.ayse.person.id}", on.mert.user).json()["days"][0][
        "notes"
    ]
    assert mine == theirs and mine[0]["text"] == "This was a training exercise."
    assert "Ayşe" not in json.dumps(
        _get(on, "/teams", on.dana.user).json()
    )  # never in aggregates


def test_a_note_can_land_on_a_day_without_signals(on):
    _note(on, on.cem.user, TODAY - timedelta(days=3), "Onboarding week")
    (day,) = _get(on, "/me", on.cem.user).json()["days"]
    assert day["signals"] == {} and day["notes"][0]["text"] == "Onboarding week"


@pytest.mark.parametrize(
    "day,text",
    [
        ((TODAY + timedelta(days=1)).isoformat(), "future"),
        ((TODAY - timedelta(days=91)).isoformat(), "too old"),
        ("29-09-2026", "bad format"),
        (TODAY.isoformat(), ""),
        (TODAY.isoformat(), "x" * 1001),
    ],
)
def test_note_validation(on, day, text):
    _as(on.client, on.ayse.user)
    assert (
        on.client.post(
            "/work-review/me/notes", json={"day": day, "text": text}
        ).status_code
        == 422
    )


def test_only_the_owner_can_delete_a_note(on):
    note = _note(on, on.ayse.user).json()
    _as(on.client, on.bora.user)
    assert on.client.delete(f"/work-review/me/notes/{note['id']}").status_code == 404
    _as(on.client, on.mert.user)  # not even the manager
    assert on.client.delete(f"/work-review/me/notes/{note['id']}").status_code == 404
    _as(on.client, on.ayse.user)
    assert on.client.delete(f"/work-review/me/notes/{note['id']}").status_code == 204
    assert _get(on, "/me", on.ayse.user).json()["days"] == []


# ── every look is audited, without content ────────────────────────────────────


def _viewed(o):
    o.db.expire_all()
    return [
        (e.actor_id, e.target, json.loads(e.payload_json)["scope"], e.payload_json)
        for e in o.db.exec(
            select(models.AuditEvent).where(
                models.AuditEvent.action == "work_review_viewed"
            )
        ).all()
    ]


def test_looks_are_audited_but_a_persons_own_view_is_not(on):
    _seed(on)
    _get(on, "/me", on.ayse.user)
    assert _viewed(on) == []
    _get(on, f"/people/{on.ayse.person.id}", on.mert.user)
    _get(on, "/teams", on.dana.user)
    _get(on, "/departments", on.founder)
    seen = _viewed(on)
    assert [(a, t, s) for a, t, s, _ in seen] == [
        (on.mert.person.id, on.ayse.person.id, "person"),
        (on.dana.person.id, on.dana.person.id, "teams"),
        (on.founder.id, on.co.id, "departments"),
    ]
    assert not any("policy_denied" in blob or "Ayşe" in blob for *_, blob in seen), (
        "the fact of looking, not what was seen"
    )
    assert audit_chain.verify(on.co.id)["ok"] is True


def test_a_refused_look_is_not_recorded_as_a_view(on):
    _get(on, f"/people/{on.ayse.person.id}", on.bora.user)  # 403
    assert _viewed(on) == []


# ── the company switch ────────────────────────────────────────────────────────


def _put(o, user, **body):
    _as(o.client, user)
    return o.client.put("/work-review/settings", json=body)


def test_only_a_founder_may_touch_the_switch(org):
    for who in (org.dana, org.mert, org.ayse):
        _as(org.client, who.user)
        assert org.client.get("/work-review/settings").status_code == 403
        assert (
            _put(org, who.user, enabled=True, acknowledge_notice=True).status_code
            == 403
        )
    assert wr.enabled(org.db, org.co.id) is False


def test_enabling_needs_an_explicit_acknowledgement_and_is_audited(org):
    r = _put(org, org.founder, enabled=True)
    assert r.status_code == 422 and "informed" in r.json()["detail"]
    org.db.expire_all()
    assert wr.enabled(org.db, org.co.id) is False, (
        "a refused request must not switch it on"
    )

    ok = _put(org, org.founder, enabled=True, acknowledge_notice=True)
    assert ok.status_code == 200 and ok.json() == {
        "enabled": True,
        "retention_days": 365,
    }
    org.db.expire_all()
    assert wr.enabled(org.db, org.co.id) is True
    ev = org.db.exec(
        select(models.AuditEvent).where(
            models.AuditEvent.action == "work_review_settings_changed"
        )
    ).all()
    assert (
        len(ev) == 1 and ev[0].reason == "enabled" and ev[0].actor_id == org.founder.id
    )
    p = json.loads(ev[0].payload_json)
    assert (
        p["before"]["enabled"] is False
        and p["after"]["enabled"] is True
        and p["notice_acknowledged"] is True
    )

    off = _put(org, org.founder, enabled=False)  # switching off needs no ceremony
    assert off.status_code == 200 and off.json()["enabled"] is False


def test_retention_is_validated_and_persisted(on):
    for bad in (0, -5, 1826):
        assert _put(on, on.founder, retention_days=bad).status_code == 422
    assert _put(on, on.founder, retention_days=90).json()["retention_days"] == 90
    _as(on.client, on.founder)
    assert on.client.get("/work-review/settings").json() == {
        "enabled": True,
        "retention_days": 90,
        "minimum_group_size": 3,
    }


def test_rollup_endpoint_is_founder_only_and_idempotent(on):
    _seed(on)
    on.db.exec(models.WorkSignal.__table__.delete())
    on.db.commit()
    for who in (on.dana, on.mert):
        _as(on.client, who.user)
        assert on.client.post("/work-review/rollup").status_code == 403
    _as(on.client, on.founder)
    first = on.client.post("/work-review/rollup", params={"days": 2}).json()
    again = on.client.post("/work-review/rollup", params={"days": 2}).json()
    assert first == again and first["rows"] >= 3
    assert on.client.post("/work-review/rollup", params={"days": 0}).status_code == 422
    assert on.client.post("/work-review/rollup", params={"days": 32}).status_code == 422
