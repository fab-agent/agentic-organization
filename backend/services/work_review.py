"""Work review: hard signals and tags, and who may see them (ADR-0019 §6).

First slice — no model calls. What it holds, per accountable *human* and UTC day:

* **hard signals** from the audit chain: policy refusals and approvals asked, kept
  apart from "would have" (dry-run) so a rule that is only being observed is not
  counted as a refusal; and
* **tags** from intent classification (task / sensitivity / domain).

These say where a person or a team may need training or clearer rules. They are not a
performance score and never measure keystrokes, time on task or screenshots. What is
*not* built: rating fit against company goals and values (needs a rubric and typed
questions), counting corrections, and a UI.

Guardrails enforced here (each tested):

* **Off by default, per company** (`work_review.enabled:<company_id>`): while off,
  nothing is computed or stored for that company.
* **Visibility by hierarchy.** A person sees their own review in full; their *direct*
  manager sees the same per-person view (no hidden ratings — one function builds both);
  the manager above sees per-team aggregates only; department heads see per-department
  aggregates only; groups smaller than `WORK_REVIEW_MIN_GROUP` are suppressed.
* **Person-first.** The person can annotate a day; the note travels with the view.
* **Retention and erasure.** Rows expire after the company's window (default 365 days),
  and are erased with the person.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete
from sqlmodel import select

from database import get_session
from models import (
    AgentConfig,
    AppConfig,
    AuditEvent,
    Company,
    CompanyMember,
    Department,
    Personnel,
    WorkNote,
    WorkRating,
    WorkSignal,
    WorkTrainingShare,
)
from services.workspaces import MANAGER_ROLES, _in_scope

logger = logging.getLogger("app")

DEFAULT_RETENTION_DAYS = 365
DEFAULT_MIN_GROUP = 3
SIGNAL_KINDS = (
    "policy_denied",
    "policy_would_deny",
    "approval_asked",
    "policy_would_ask",
)
TAG_KINDS = ("task", "sensitivity", "domain")
_SOURCE_ACTIONS = ("policy_decision", "intent_classified")
_TRUE = ("1", "true", "yes", "on")


# ── settings ──────────────────────────────────────────────────────────────────


def _get(session, key: str) -> str | None:
    row = session.get(AppConfig, key)
    return row.value if row and row.value is not None else None


def _put(session, key: str, value: str) -> None:
    row = session.get(AppConfig, key)
    if row is None:
        row = AppConfig(key=key, value=value)
    else:
        row.value = value
    session.add(row)


def enabled(session, company_id: str) -> bool:
    """Per company and off unless set: there is deliberately no global switch."""
    v = _get(session, f"work_review.enabled:{company_id}")
    return v is not None and v.strip().lower() in _TRUE


def set_enabled(session, company_id: str, on: bool) -> None:
    _put(session, f"work_review.enabled:{company_id}", "true" if on else "false")


def retention_days(session, company_id: str) -> int:
    try:
        n = int(_get(session, f"work_review.retention_days:{company_id}") or "")
    except ValueError:
        return DEFAULT_RETENTION_DAYS
    return n if n >= 1 else DEFAULT_RETENTION_DAYS


def set_retention_days(session, company_id: str, days: int) -> None:
    _put(session, f"work_review.retention_days:{company_id}", str(int(days)))


def min_group() -> int:
    """Smallest group whose aggregate may be shown (never below 2: a group of one is
    a person)."""
    try:
        return max(2, int(os.getenv("WORK_REVIEW_MIN_GROUP", DEFAULT_MIN_GROUP)))
    except ValueError:
        return DEFAULT_MIN_GROUP


# ── deriving signals from the audit chain ─────────────────────────────────────


def increments(action: str, payload: dict) -> list[tuple[str, str]]:
    """`(kind, value)` counts one audit event contributes, or nothing."""
    if action == "policy_decision":
        if payload.get("fail_closed"):
            return []  # a broken policy config is a system fault, not the person's doing
        effect, enforced = payload.get("effect"), bool(payload.get("enforced"))
        if effect == "deny":
            return [("policy_denied" if enforced else "policy_would_deny", "")]
        if effect == "ask":
            return [("approval_asked" if enforced else "policy_would_ask", "")]
        return []
    if action == "intent_classified":
        tags = payload.get("tags")
        if not isinstance(tags, dict):
            return []
        return [
            (f"tag_{k}", tags[k].strip()[:80])
            for k in TAG_KINDS
            if isinstance(tags.get(k), str) and tags[k].strip()
        ]
    return []


def owner_map(session, company_id: str) -> dict[str, str]:
    """agent persona id → the human accountable for it (its responsible person)."""
    humans = {
        pid
        for pid in session.exec(
            select(Personnel.id).where(
                Personnel.company_id == company_id, Personnel.type == "human"
            )
        ).all()
    }
    rows = session.exec(
        select(AgentConfig.personnel_id, AgentConfig.responsible_id)
        .join(Personnel, Personnel.id == AgentConfig.personnel_id)
        .where(Personnel.company_id == company_id)
        .where(AgentConfig.responsible_id.is_not(None))
    ).all()
    return {agent: owner for agent, owner in rows if owner in humans}


def rollup_day(session, company_id: str, day: date) -> int:
    """Recompute one company-day from the audit chain, replacing that day's rows (so
    re-running never double counts). Returns the rows written."""
    start = datetime.combine(day, time.min)
    events = session.exec(
        select(AuditEvent)
        .where(AuditEvent.company_id == company_id)
        .where(AuditEvent.action.in_(_SOURCE_ACTIONS))
        .where(AuditEvent.created_at >= start)
        .where(AuditEvent.created_at < start + timedelta(days=1))
    ).all()
    owners = owner_map(session, company_id)
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for ev in events:
        owner = owners.get(ev.actor_id or "")
        if not owner:
            continue
        try:
            payload = json.loads(ev.payload_json) if ev.payload_json else {}
        except ValueError:
            continue
        for kind, value in increments(
            ev.action, payload if isinstance(payload, dict) else {}
        ):
            counts[(owner, kind, value)] += 1

    d = day.isoformat()
    session.execute(
        delete(WorkSignal).where(
            WorkSignal.company_id == company_id, WorkSignal.day == d
        )
    )
    now = datetime.utcnow()
    for (owner, kind, value), n in counts.items():
        session.add(
            WorkSignal(
                personnel_id=owner,
                day=d,
                kind=kind,
                value=value,
                company_id=company_id,
                count=n,
                updated_at=now,
            )
        )
    session.commit()
    return len(counts)


def rollup_recent(days: int = 2, today: date | None = None) -> dict:
    """Scheduler job: refresh the last `days` days for every company that enabled work
    review. Companies that did not are never touched."""
    today = today or datetime.utcnow().date()
    done = rows = 0
    with get_session() as session:
        for cid in session.exec(select(Company.id)).all():
            if not enabled(session, cid):
                continue
            try:
                for i in range(days):
                    rows += rollup_day(session, cid, today - timedelta(days=i))
                done += 1
            except Exception as e:  # noqa: BLE001 - one company must not stop the rest
                session.rollback()
                logger.warning(
                    "work_review_rollup_failed",
                    extra={"extra": {"error": type(e).__name__}},
                )
    return {"companies": done, "rows": rows}


def purge_expired(today: date | None = None) -> int:
    """Delete signals, notes and ratings older than each company's retention window (also for
    companies that have since switched work review off). Returns rows deleted."""
    today = today or datetime.utcnow().date()
    n = 0
    with get_session() as session:
        for cid in session.exec(select(Company.id)).all():
            cutoff = (today - timedelta(days=retention_days(session, cid))).isoformat()
            for model in (WorkSignal, WorkNote, WorkRating):
                res = session.execute(
                    delete(model).where(model.company_id == cid, model.day < cutoff)
                )
                n += res.rowcount or 0
            cutoff_at = datetime.combine(
                today - timedelta(days=retention_days(session, cid)), time.min
            )
            res = session.execute(
                delete(WorkTrainingShare).where(
                    WorkTrainingShare.company_id == cid,
                    WorkTrainingShare.shared_at < cutoff_at,
                )
            )
            n += res.rowcount or 0
        session.commit()
    return n


def erase_person(session, personnel_id: str) -> int:
    """Erase everything work review holds (signals, notes, ratings) about one person. The caller commits."""
    n = 0
    for model in (WorkSignal, WorkNote, WorkRating, WorkTrainingShare):
        n += (
            session.execute(
                delete(model).where(model.personnel_id == personnel_id)
            ).rowcount
            or 0
        )
    return n


# ── views ─────────────────────────────────────────────────────────────────────


def _first_day(days: int, today: date | None) -> str:
    today = today or datetime.utcnow().date()
    return (today - timedelta(days=days - 1)).isoformat()


def _totals(rows) -> dict:
    signals: dict[str, int] = defaultdict(int)
    tags: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        if r.kind.startswith("tag_"):
            t = tags[r.kind[4:]]
            t[r.value] = t.get(r.value, 0) + r.count
        else:
            signals[r.kind] += r.count
    return {"signals": dict(signals), "tags": {k: dict(v) for k, v in tags.items()}}


def _open_contest(r: WorkRating) -> bool:
    return r.contested_at is not None and r.resolved_at is None


def _rating_entry(r: WorkRating) -> dict:
    return {
        "id": r.id,
        "criterion_id": r.criterion_id,
        "criterion_hash": r.criterion_hash,
        "status": r.criterion_status,
        "verdict": r.verdict,
        "contested": _open_contest(r),
        "resolved": r.resolved_at is not None,
        "contest_note": r.contest_note,
    }


def person_view(
    session,
    subject: Personnel,
    days: int = 30,
    today: date | None = None,
    *,
    as_subject: bool = False,
) -> dict:
    """One person's review. The person and their direct manager get the same view,
    with two deliberate differences in *fit ratings* (ADR-0021 §5–6): ratings of a
    criterion still in `shadow` are shown only to the person, and a rating the person
    has contested stays out of everyone else's view until it is resolved. `as_subject`
    is therefore False by default: the safe view is the one with less in it."""
    first = _first_day(days, today)
    rows = session.exec(
        select(WorkSignal).where(
            WorkSignal.personnel_id == subject.id, WorkSignal.day >= first
        )
    ).all()
    notes = session.exec(
        select(WorkNote)
        .where(WorkNote.personnel_id == subject.id, WorkNote.day >= first)
        .order_by(WorkNote.created_at)
    ).all()
    ratings = session.exec(
        select(WorkRating)
        .where(WorkRating.personnel_id == subject.id, WorkRating.day >= first)
        .order_by(WorkRating.created_at)
    ).all()
    if not as_subject:
        ratings = [
            r for r in ratings if r.criterion_status == "live" and not _open_contest(r)
        ]
    by_day: dict[str, dict] = defaultdict(
        lambda: {"signals": {}, "tags": {}, "notes": [], "ratings": []}
    )
    for r in rows:
        if r.kind.startswith("tag_"):
            by_day[r.day]["tags"].setdefault(r.kind[4:], {})[r.value] = r.count
        else:
            by_day[r.day]["signals"][r.kind] = r.count
    for n in notes:
        by_day[n.day]["notes"].append(
            {"id": n.id, "text": n.text, "created_at": n.created_at.isoformat()}
        )
    for r in ratings:
        by_day[r.day]["ratings"].append(_rating_entry(r))
    return {
        "personnel_id": subject.id,
        "name": subject.name,
        "window_days": days,
        "days": [{"day": d, **by_day[d]} for d in sorted(by_day, reverse=True)],
        "totals": _totals(rows),
        "ratings": _rating_totals(ratings),
    }


def _rating_totals(ratings: list[WorkRating]) -> list[dict]:
    """Counts per criterion version. No score, no average (ADR-0021 §2)."""
    out: dict[tuple[str, str], dict] = {}
    for r in ratings:  # oldest first, so the last status wins
        e = out.setdefault(
            (r.criterion_id, r.criterion_hash),
            {
                "criterion_id": r.criterion_id,
                "criterion_hash": r.criterion_hash,
                "met": 0,
                "not_met": 0,
                "unclear": 0,
                "contested": 0,
            },
        )
        e["status"] = r.criterion_status
        if r.verdict in ("met", "not_met", "unclear"):
            e[r.verdict] += 1
        if _open_contest(r):
            e["contested"] += 1
    return sorted(out.values(), key=lambda e: (e["criterion_id"], e["criterion_hash"]))


def aggregate(
    session, members: list[Personnel], days: int = 30, today: date | None = None
) -> dict:
    """A group's totals, or just its size when it is too small to be anonymous."""
    n = len(members)
    floor = min_group()
    if n < floor:
        return {
            "n_people": n,
            "suppressed": True,
            "reason": f"fewer than {floor} people",
        }
    first = _first_day(days, today)
    rows = session.exec(
        select(WorkSignal).where(
            WorkSignal.personnel_id.in_([m.id for m in members]),
            WorkSignal.day >= first,
        )
    ).all()
    totals = _totals(rows)
    ratings, hidden = _group_ratings(session, [m.id for m in members], first, floor)
    return {
        "n_people": n,
        "suppressed": False,
        "window_days": days,
        **totals,
        "per_person_average": {
            k: round(v / n, 2) for k, v in totals["signals"].items()
        },
        "ratings": ratings,
        "ratings_hidden": hidden,
    }


def _group_ratings(
    session, member_ids: list[str], first: str, floor: int
) -> tuple[list[dict], int]:
    """Fit ratings of a group (ADR-0021 §6): counts per criterion version, from `live`
    and uncontested ratings only — never `shadow`, never one under contest — and only
    for a criterion that at least `floor` different people have been rated on, so a
    criterion cannot single a person out. Returns (rows, number of rows held back)."""
    rows = session.exec(
        select(WorkRating).where(
            WorkRating.personnel_id.in_(member_ids),
            WorkRating.day >= first,
            WorkRating.criterion_status == "live",
        )
    ).all()
    groups: dict[tuple[str, str], dict] = {}
    for r in rows:
        if _open_contest(r):
            continue
        g = groups.setdefault(
            (r.criterion_id, r.criterion_hash),
            {
                "criterion_id": r.criterion_id,
                "criterion_hash": r.criterion_hash,
                "status": "live",
                "met": 0,
                "not_met": 0,
                "unclear": 0,
                "people": set(),
            },
        )
        if r.verdict in ("met", "not_met", "unclear"):
            g[r.verdict] += 1
        g["people"].add(r.personnel_id)
    out, hidden = [], 0
    for key in sorted(groups):
        g = groups[key]
        n_people = len(g.pop("people"))
        if n_people < floor:
            hidden += 1
            continue
        out.append({**g, "n_people": n_people})
    return out, hidden


def direct_reports(session, manager: Personnel) -> list[Personnel]:
    return list(
        session.exec(
            select(Personnel).where(
                Personnel.manager_id == manager.id,
                Personnel.company_id == manager.company_id,
                Personnel.type == "human",
            )
        ).all()
    )


def is_direct_manager(viewer: Personnel, subject: Personnel) -> bool:
    return (
        subject.type == "human"
        and subject.manager_id == viewer.id
        and subject.company_id == viewer.company_id
    )


def visible_teams(
    session, viewer: Personnel
) -> list[tuple[Personnel, list[Personnel]]]:
    """Teams led by the viewer's direct reports: `(leader, the leader's own reports)`."""
    out = []
    for leader in direct_reports(session, viewer):
        members = direct_reports(session, leader)
        if members:
            out.append((leader, members))
    return out


def departments_in_scope(session, user, company_id: str) -> list[Department]:
    """Departments this user may see aggregates for: all of them for a founder or an
    unscoped executive / department head, else the subtrees they are scoped to."""
    members = session.exec(
        select(CompanyMember).where(
            CompanyMember.user_id == user.id,
            CompanyMember.company_id == company_id,
            CompanyMember.role.in_(MANAGER_ROLES),
        )
    ).all()
    if not members:
        return []
    depts = session.exec(
        select(Department).where(Department.company_id == company_id)
    ).all()
    if any(m.role == "founder" or not m.scope_id for m in members):
        return list(depts)
    scopes = [m.scope_id for m in members]
    return [d for d in depts if any(_in_scope(session, d.id, sc) for sc in scopes)]


def department_members(session, dept: Department) -> list[Personnel]:
    return list(
        session.exec(
            select(Personnel).where(
                Personnel.department_id == dept.id, Personnel.type == "human"
            )
        ).all()
    )
