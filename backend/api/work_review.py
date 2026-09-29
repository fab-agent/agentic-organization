"""Work review API (ADR-0019 §6): who may see what, and the company switch.

Every read is audited (who looked at whom, never what they saw). See
`services.work_review` for what is collected and the guardrails.
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import select

from api.auth import get_current_user
from database import get_session
from models import (
    CompanyMember,
    Department,
    Personnel,
    User,
    WorkNote,
    WorkRating,
    WorkTrainingShare,
)
from services import audit_chain
from services import rating as rt
from services import rubric as rb
from services import training_need as tn
from services import work_review as wr
from services.workspaces import (
    MANAGER_ROLES,
    _in_scope,
    person_for_user,
    resolve_company_id,
)

router = APIRouter(prefix="/work-review", tags=["work-review"])

_DAYS = Query(30, ge=1, le=90)


def _require_enabled(session, company_id: str) -> None:
    if not wr.enabled(session, company_id):
        raise HTTPException(
            status_code=404, detail="Work review is not enabled for this company"
        )


def _viewed(
    viewer_id: str, company_id: str, scope: str, target: str, days: int
) -> None:
    """Record that someone looked — the fact, not the content."""
    audit_chain.record(
        actor_type="human",
        actor_id=viewer_id,
        company_id=company_id,
        action="work_review_viewed",
        target=target,
        reason=scope,
        payload={"scope": scope, "window_days": days},
    )


def _require_founder(session, user: User, company_id: str) -> None:
    ok = session.exec(
        select(CompanyMember).where(
            CompanyMember.user_id == user.id,
            CompanyMember.company_id == company_id,
            CompanyMember.role == "founder",
        )
    ).first()
    if not ok:
        raise HTTPException(status_code=403, detail="Founder role required")


def _disclosure(session, company_id: str) -> dict:
    """What is collected and who can see it — shown to the person it is about."""
    floor = wr.min_group()
    return {
        "collected": {"signals": list(wr.SIGNAL_KINDS), "tags": list(wr.TAG_KINDS)},
        "never_collected": [
            "keystrokes",
            "time on task",
            "screenshots",
            "message contents",
        ],
        "visible_to": [
            "you, in full",
            "your direct manager, the same per-person view you see",
            f"managers above you: team and department totals only, for groups of at least {floor}",
        ],
        "minimum_group_size": floor,
        "retention_days": wr.retention_days(session, company_id),
    }


def _annotate(session, company_id: str, view: dict) -> dict:
    """Add the criterion's question wherever the company's *current* rubric still has
    that exact version (same id and hash); older versions keep just their id."""
    loaded = rt.load_rubric(session, company_id)
    known = (
        {(c.id, rb.criterion_hash(c)): c.question for c in loaded[0].criteria}
        if loaded
        else {}
    )
    for e in view.get("ratings", []):
        e["question"] = known.get((e["criterion_id"], e["criterion_hash"]))
    for d in view.get("days", []):
        for e in d.get("ratings", []):
            e["question"] = known.get((e["criterion_id"], e["criterion_hash"]))
    for key in ("training_need", "support_requests"):
        for e in view.get(key, []):
            e["question"] = known.get((e["criterion_id"], e["criterion_hash"]))
    return view


# ── the person's own review ───────────────────────────────────────────────────


@router.get("/me")
def my_review(
    company_id: str | None = None,
    days: int = _DAYS,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        _require_enabled(session, cid)
        view = wr.person_view(session, person, days, as_subject=True)
        view["training_need"] = _training_need_for(session, person)
        view["training_sharing_enabled"] = tn.sharing_enabled(session, cid)
        _annotate(session, cid, view)
        view["disclosure"] = _disclosure(session, cid)
        return view


def _training_need_for(session, person: Personnel) -> list[dict]:
    """The person's own training-need signals (ADR-0021 §6), each marked `unit_wide` when
    enough colleagues in the same department show the same pattern — then the likelier
    reading is an unclear rule, not the person."""
    signals = tn.person_signals(session, person)
    if not signals:
        return []
    unit: set[tuple[str, str]] = set()
    dept = (
        session.get(Department, person.department_id) if person.department_id else None
    )
    if dept is not None:
        found = tn.unit_findings(session, wr.department_members(session, dept)) or []
        unit = {(f["criterion_id"], f["criterion_hash"]) for f in found}
    shared = {
        (r.criterion_id, r.criterion_hash)
        for r in session.exec(
            select(WorkTrainingShare).where(WorkTrainingShare.personnel_id == person.id)
        ).all()
    }
    for e in signals:
        key = (e["criterion_id"], e["criterion_hash"])
        e["unit_wide"] = key in unit
        e["shared"] = key in shared
    return signals


class NoteBody(BaseModel):
    day: str
    text: str = Field(min_length=1, max_length=1000)


@router.post("/me/notes", status_code=201)
def add_note(
    body: NoteBody,
    company_id: str | None = None,
    user: User = Depends(get_current_user),
):
    try:
        day = date.fromisoformat(body.day)
    except ValueError:
        raise HTTPException(status_code=422, detail="day must be YYYY-MM-DD")
    today = datetime.utcnow().date()
    if not (today - timedelta(days=90) <= day <= today):
        raise HTTPException(
            status_code=422, detail="day must be within the last 90 days"
        )
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        _require_enabled(session, cid)
        note = WorkNote(
            personnel_id=person.id,
            company_id=cid,
            day=day.isoformat(),
            text=body.text.strip(),
        )
        session.add(note)
        session.commit()
        return {"id": note.id, "day": note.day, "text": note.text}


@router.delete("/me/notes/{note_id}", status_code=204)
def delete_note(
    note_id: str, company_id: str | None = None, user: User = Depends(get_current_user)
):
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        note = session.get(WorkNote, note_id)
        if not note or note.personnel_id != person.id:
            raise HTTPException(status_code=404, detail="Note not found")
        session.delete(note)
        session.commit()


class ContestBody(BaseModel):
    note: str = Field(min_length=1, max_length=1000)


def _own_rating(session, person: Personnel, rating_id: str) -> WorkRating:
    r = session.get(WorkRating, rating_id)
    if not r or r.personnel_id != person.id:
        raise HTTPException(status_code=404, detail="Rating not found")
    return r


def _audit_rating(user: User, cid: str, action: str, rating: WorkRating) -> None:
    """The fact only: who did what to whose rating — never the note."""
    audit_chain.record(
        actor_type="human",
        actor_id=user.id,
        company_id=cid,
        action=action,
        target=rating.personnel_id,
        reason=rating.criterion_id,
        payload={"rating_id": rating.id},
    )


@router.post("/me/ratings/{rating_id}/contest")
def contest_rating(
    rating_id: str,
    body: ContestBody,
    company_id: str | None = None,
    user: User = Depends(get_current_user),
):
    """Contest a fit rating (ADR-0021 §6). Until it is resolved it is left out of every
    view but the person's own, and out of all aggregates."""
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        _require_enabled(session, cid)
        r = _own_rating(session, person, rating_id)
        r.contest_note = body.note.strip()
        r.contested_at = datetime.utcnow()
        r.resolved_at = None
        session.add(r)
        session.commit()
        _audit_rating(user, cid, "work_rating_contested", r)
        return wr._rating_entry(r)


@router.delete("/me/ratings/{rating_id}/contest", status_code=204)
def withdraw_contest(
    rating_id: str,
    company_id: str | None = None,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        _require_enabled(session, cid)
        r = _own_rating(session, person, rating_id)
        r.contest_note = None
        r.contested_at = None
        r.resolved_at = None
        session.add(r)
        session.commit()
        _audit_rating(user, cid, "work_rating_contest_withdrawn", r)


def _can_resolve(session, user: User, viewer: Personnel, subject: Personnel) -> bool:
    """A department head (or executive / founder) whose scope covers the subject —
    never the subject, and never their direct manager, who sees the ratings."""
    if viewer.id == subject.id or subject.manager_id == viewer.id:
        return False
    members = session.exec(
        select(CompanyMember).where(
            CompanyMember.user_id == user.id,
            CompanyMember.company_id == subject.company_id,
            CompanyMember.role.in_(MANAGER_ROLES),
        )
    ).all()
    return any(
        m.role == "founder"
        or not m.scope_id
        or _in_scope(session, subject.department_id, m.scope_id)
        for m in members
    )


@router.post("/ratings/{rating_id}/resolve")
def resolve_contest(
    rating_id: str,
    company_id: str | None = None,
    user: User = Depends(get_current_user),
):
    """Close a contest. The rating rejoins the views (with the person's note attached)."""
    with get_session() as session:
        viewer, cid = person_for_user(session, user, company_id)
        _require_enabled(session, cid)
        r = session.get(WorkRating, rating_id)
        subject = session.get(Personnel, r.personnel_id) if r else None
        if not r or not subject or r.company_id != cid:
            raise HTTPException(status_code=404, detail="Rating not found")
        if not _can_resolve(session, user, viewer, subject):
            raise HTTPException(
                status_code=403,
                detail="Only a department head above the person, not their direct manager, can resolve this",
            )
        if r.contested_at is None or r.resolved_at is not None:
            raise HTTPException(
                status_code=409, detail="This rating is not under contest"
            )
        r.resolved_at = datetime.utcnow()
        session.add(r)
        session.commit()
        _audit_rating(user, cid, "work_rating_resolved", r)
        return wr._rating_entry(r)


# ── what a manager may see ────────────────────────────────────────────────────


@router.get("/people/{personnel_id}")
def person_review(
    personnel_id: str,
    company_id: str | None = None,
    days: int = _DAYS,
    user: User = Depends(get_current_user),
):
    """Per-person view — only for the person's *direct* manager, and exactly the view
    the person has of themselves."""
    with get_session() as session:
        viewer, cid = person_for_user(session, user, company_id)
        _require_enabled(session, cid)
        subject = session.get(Personnel, personnel_id)
        if not subject or not wr.is_direct_manager(viewer, subject):
            raise HTTPException(
                status_code=403, detail="Only a person's direct manager can view this"
            )
        view = wr.person_view(session, subject, days)
        if tn.sharing_enabled(session, cid):
            view["support_requests"] = tn.shared_signals(session, subject)
        _annotate(session, cid, view)
        _viewed(viewer.id, cid, "person", subject.id, days)
        return view


@router.get("/teams")
def team_reviews(
    company_id: str | None = None,
    days: int = _DAYS,
    user: User = Depends(get_current_user),
):
    """Aggregates for the teams led by the viewer's direct reports — totals only."""
    with get_session() as session:
        viewer, cid = person_for_user(session, user, company_id)
        _require_enabled(session, cid)
        out = [
            _annotate(
                session,
                cid,
                {
                    "leader": {"id": leader.id, "name": leader.name},
                    **wr.aggregate(session, members, days),
                },
            )
            for leader, members in wr.visible_teams(session, viewer)
        ]
        _viewed(viewer.id, cid, "teams", viewer.id, days)
        return out


@router.get("/departments")
def department_reviews(
    company_id: str | None = None,
    days: int = _DAYS,
    user: User = Depends(get_current_user),
):
    """Aggregates per department in the viewer's scope — totals only."""
    with get_session() as session:
        cid = resolve_company_id(session, user, company_id)
        _require_enabled(session, cid)
        depts = wr.departments_in_scope(session, user, cid)
        if not depts:
            raise HTTPException(status_code=403, detail="Manager role required")
        out = []
        for d in depts:
            members = wr.department_members(session, d)
            if members:
                out.append(
                    _annotate(
                        session,
                        cid,
                        {
                            "department": {"id": d.id, "name": d.name},
                            **wr.aggregate(session, members, days),
                        },
                    )
                )
        _viewed(user.id, cid, "departments", cid, days)
        return out


class ShareBody(BaseModel):
    criterion_id: str = Field(min_length=1, max_length=100)
    criterion_hash: str = Field(min_length=1, max_length=100)


def _require_sharing(session, cid: str) -> None:
    if not tn.sharing_enabled(session, cid):
        raise HTTPException(
            status_code=404,
            detail="Sharing training-need signals is not enabled for this company",
        )


@router.post("/me/training-need/share", status_code=201)
def share_training_signal(
    body: ShareBody,
    company_id: str | None = None,
    user: User = Depends(get_current_user),
):
    """Choose to share one of your own current signals with your direct manager. Only a
    signal that exists right now can be shared; it can be withdrawn at any time."""
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        _require_enabled(session, cid)
        _require_sharing(session, cid)
        current = {
            (e["criterion_id"], e["criterion_hash"])
            for e in tn.person_signals(session, person)
        }
        key = (body.criterion_id, body.criterion_hash)
        if key not in current:
            raise HTTPException(
                status_code=409, detail="You have no such signal to share"
            )
        exists = session.exec(
            select(WorkTrainingShare).where(
                WorkTrainingShare.personnel_id == person.id,
                WorkTrainingShare.criterion_id == key[0],
                WorkTrainingShare.criterion_hash == key[1],
            )
        ).first()
        if exists is None:
            session.add(
                WorkTrainingShare(
                    company_id=cid,
                    personnel_id=person.id,
                    criterion_id=key[0],
                    criterion_hash=key[1],
                )
            )
            session.commit()
            audit_chain.record(
                actor_type="human",
                actor_id=user.id,
                company_id=cid,
                action="work_training_shared",
                target=person.id,
                reason=key[0],
                payload={"with": "direct_manager"},
            )
        return {"criterion_id": key[0], "criterion_hash": key[1], "shared": True}


@router.delete("/me/training-need/share", status_code=204)
def withdraw_training_share(
    criterion_id: str = Query(min_length=1, max_length=100),
    criterion_hash: str = Query(min_length=1, max_length=100),
    company_id: str | None = None,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        _require_enabled(session, cid)
        row = session.exec(
            select(WorkTrainingShare).where(
                WorkTrainingShare.personnel_id == person.id,
                WorkTrainingShare.criterion_id == criterion_id,
                WorkTrainingShare.criterion_hash == criterion_hash,
            )
        ).first()
        if row is None:
            return
        session.delete(row)
        session.commit()
        audit_chain.record(
            actor_type="human",
            actor_id=user.id,
            company_id=cid,
            action="work_training_unshared",
            target=person.id,
            reason=criterion_id,
            payload={},
        )


@router.get("/training-need/my-team")
def training_need_my_team(
    company_id: str | None = None, user: User = Depends(get_current_user)
):
    """The unit finding for the viewer's own team (their direct reports) — counts only,
    and nothing at all for a team below the group floor. It points at a rule or its
    training, not at a person."""
    with get_session() as session:
        viewer, cid = person_for_user(session, user, company_id)
        _require_enabled(session, cid)
        n, found = tn.team_findings(session, viewer)
        if n == 0:
            raise HTTPException(status_code=403, detail="You have no direct reports")
        _viewed(viewer.id, cid, "training_team", viewer.id, tn.WINDOW_DAYS)
        if found is None:
            return {"n_people": n, "suppressed": True, "findings": []}
        return {
            "n_people": n,
            "suppressed": False,
            "findings": _annotate(session, cid, {"training_need": found})[
                "training_need"
            ],
        }


@router.get("/training-need/units")
def training_need_units(
    company_id: str | None = None, user: User = Depends(get_current_user)
):
    """Where a whole unit struggles with a criterion — for whoever owns the rubric over
    that unit (department head, executive, founder). Counts only, never names; a unit
    below the group floor says nothing."""
    with get_session() as session:
        cid = resolve_company_id(session, user, company_id)
        _require_enabled(session, cid)
        depts = wr.departments_in_scope(session, user, cid)
        if not depts:
            raise HTTPException(status_code=403, detail="Manager role required")
        out = []
        for d in depts:
            members = wr.department_members(session, d)
            if not members:
                continue
            found = tn.unit_findings(session, members)
            entry = {
                "department": {"id": d.id, "name": d.name},
                "n_people": len(members),
            }
            if found is None:
                entry |= {"suppressed": True, "findings": []}
            else:
                entry |= {
                    "suppressed": False,
                    "findings": _annotate(session, cid, {"training_need": found})[
                        "training_need"
                    ],
                }
            out.append(entry)
        _viewed(user.id, cid, "training_units", cid, tn.WINDOW_DAYS)
        return out


class TrainingSettings(BaseModel):
    sharing_enabled: bool | None = None
    min_rated: int | None = Field(
        default=None, ge=tn.MIN_RATED_RANGE[0], le=tn.MIN_RATED_RANGE[1]
    )
    bar: float | None = Field(default=None, ge=tn.BAR_RANGE[0], le=tn.BAR_RANGE[1])


@router.get("/training-need/settings")
def get_training_settings(
    company_id: str | None = None, user: User = Depends(get_current_user)
):
    with get_session() as session:
        cid = resolve_company_id(session, user, company_id)
        _require_founder(session, user, cid)
        return {
            "min_rated": tn.min_rated(session, cid),
            "bar": tn.bar(session, cid),
            "sharing_enabled": tn.sharing_enabled(session, cid),
            "window_days": tn.WINDOW_DAYS,
        }


@router.put("/training-need/settings")
def put_training_settings(
    body: TrainingSettings,
    company_id: str | None = None,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        cid = resolve_company_id(session, user, company_id)
        _require_founder(session, user, cid)
        if body.min_rated is not None:
            tn.set_min_rated(session, cid, body.min_rated)
        if body.bar is not None:
            tn.set_bar(session, cid, body.bar)
        if body.sharing_enabled is not None:
            tn.set_sharing_enabled(session, cid, body.sharing_enabled)
        session.commit()
        after = {
            "min_rated": tn.min_rated(session, cid),
            "bar": tn.bar(session, cid),
            "sharing_enabled": tn.sharing_enabled(session, cid),
        }
    audit_chain.record(
        actor_type="human",
        actor_id=user.id,
        company_id=cid,
        action="work_review_settings_changed",
        reason="training_need",
        payload={"after": after},
    )
    return {**after, "window_days": tn.WINDOW_DAYS}


# ── the company switch (founder only) ─────────────────────────────────────────


class SettingsBody(BaseModel):
    enabled: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=1825)
    # Fit rating (ADR-0021): separate from work review itself, because summaries go to
    # a scoring model. Needs work review on, and the same acknowledgement.
    rating_enabled: bool | None = None
    # Turning it on is about employees' personal data (KVKK / GDPR): the founder must
    # confirm that purpose, access and retention are defined and staff are informed.
    acknowledge_notice: bool = False


@router.get("/settings")
def get_settings(company_id: str | None = None, user: User = Depends(get_current_user)):
    with get_session() as session:
        cid = resolve_company_id(session, user, company_id)
        _require_founder(session, user, cid)
        return {
            "enabled": wr.enabled(session, cid),
            "retention_days": wr.retention_days(session, cid),
            "rating_enabled": rt.rating_enabled(session, cid),
            "minimum_group_size": wr.min_group(),
        }


@router.put("/settings")
def put_settings(
    body: SettingsBody,
    company_id: str | None = None,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        cid = resolve_company_id(session, user, company_id)
        _require_founder(session, user, cid)
        before = {
            "enabled": wr.enabled(session, cid),
            "retention_days": wr.retention_days(session, cid),
            "rating_enabled": rt.rating_enabled(session, cid),
        }
        if body.enabled and not before["enabled"] and not body.acknowledge_notice:
            raise HTTPException(
                status_code=422,
                detail="acknowledge_notice must be true to enable work review: confirm that purpose, "
                "access and retention are defined and that employees have been informed",
            )
        if body.rating_enabled:
            if not (body.enabled or before["enabled"]):
                raise HTTPException(
                    status_code=422,
                    detail="fit rating needs work review to be enabled first",
                )
            if not before["rating_enabled"] and not body.acknowledge_notice:
                raise HTTPException(
                    status_code=422,
                    detail="acknowledge_notice must be true to enable fit rating: work summaries "
                    "are sent to a scoring model, so confirm employees have been informed",
                )
        if body.enabled is not None:
            wr.set_enabled(session, cid, body.enabled)
        if body.rating_enabled is not None:
            rt.set_rating_enabled(session, cid, body.rating_enabled)
        if body.retention_days is not None:
            wr.set_retention_days(session, cid, body.retention_days)
        session.commit()
        after = {
            "enabled": wr.enabled(session, cid),
            "retention_days": wr.retention_days(session, cid),
            "rating_enabled": rt.rating_enabled(session, cid),
        }
    audit_chain.record(
        actor_type="human",
        actor_id=user.id,
        company_id=cid,
        action="work_review_settings_changed",
        reason="enabled" if after["enabled"] and not before["enabled"] else "updated",
        payload={
            "before": before,
            "after": after,
            "notice_acknowledged": body.acknowledge_notice,
        },
    )
    return after


@router.post("/rollup")
def rollup(
    company_id: str | None = None,
    days: int = Query(2, ge=1, le=31),
    user: User = Depends(get_current_user),
):
    """Recompute the last `days` days now (also runs on a schedule). Idempotent."""
    with get_session() as session:
        cid = resolve_company_id(session, user, company_id)
        _require_founder(session, user, cid)
        _require_enabled(session, cid)
        today = datetime.utcnow().date()
        rows = sum(
            wr.rollup_day(session, cid, today - timedelta(days=i)) for i in range(days)
        )
        return {"days": days, "rows": rows}
