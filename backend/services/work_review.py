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
    WorkSignal,
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
    """Delete signals and notes older than each company's retention window (also for
    companies that have since switched work review off). Returns rows deleted."""
    today = today or datetime.utcnow().date()
    n = 0
    with get_session() as session:
        for cid in session.exec(select(Company.id)).all():
            cutoff = (today - timedelta(days=retention_days(session, cid))).isoformat()
            for model in (WorkSignal, WorkNote):
                res = session.execute(
                    delete(model).where(model.company_id == cid, model.day < cutoff)
                )
                n += res.rowcount or 0
        session.commit()
    return n


def erase_person(session, personnel_id: str) -> int:
    """Erase everything work review holds about one person. The caller commits."""
    n = 0
    for model in (WorkSignal, WorkNote):
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


def person_view(
    session, subject: Personnel, days: int = 30, today: date | None = None
) -> dict:
    """One person's review, in full. The person and their direct manager both get
    exactly this — there is no separate, richer manager view."""
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
    by_day: dict[str, dict] = defaultdict(
        lambda: {"signals": {}, "tags": {}, "notes": []}
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
    return {
        "personnel_id": subject.id,
        "name": subject.name,
        "window_days": days,
        "days": [{"day": d, **by_day[d]} for d in sorted(by_day, reverse=True)],
        "totals": _totals(rows),
    }


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
    return {
        "n_people": n,
        "suppressed": False,
        "window_days": days,
        **totals,
        "per_person_average": {
            k: round(v / n, 2) for k, v in totals["signals"].items()
        },
    }


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
