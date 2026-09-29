"""Workspace lifecycle rules (ADR-0018): access, path safety, retention.

HTTP-free so the rules can be tested and reused by scheduler jobs.
"""

from __future__ import annotations

import posixpath
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlmodel import select

from models import CompanyMember, Department, Personnel, User, Workspace
from services.workspace_runtime import WorkspaceRuntime, WorkspaceRuntimeError

RETENTION = timedelta(days=7)
STALE_CREATING = timedelta(minutes=5)
MANAGER_ROLES = {"founder", "executive", "dept_head"}
LIVE_STATES = ("creating", "running", "suspended", "failed")


# ── paths ─────────────────────────────────────────────────────────────────────


def safe_relpath(path: str) -> str:
    """Normalise a client-supplied relative path or raise 400.

    Rejects absolute paths, `..`, backslashes, NUL and empty / overlong paths so a
    client can never address anything outside the area the API prefixes to it.
    """
    if not path or len(path) > 512 or "\x00" in path or "\\" in path:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")
    norm = posixpath.normpath(path)
    parts = norm.split("/")
    if norm in (".", "") or any(p in ("", ".", "..") for p in parts):
        raise HTTPException(status_code=400, detail="Invalid file path")
    return norm


# ── who is calling ────────────────────────────────────────────────────────────


def resolve_company_id(session, user: User, company_id: str | None = None) -> str:
    """The company a request is about: the one asked for (membership checked), or the
    caller's only one. HTTP errors otherwise."""
    members = session.exec(
        select(CompanyMember).where(CompanyMember.user_id == user.id)
    ).all()
    ids = {m.company_id for m in members}
    if company_id:
        if company_id not in ids:
            raise HTTPException(status_code=403, detail="Not a member of this company")
        return company_id
    if not ids:
        raise HTTPException(status_code=404, detail="No company membership")
    if len(ids) > 1:
        raise HTTPException(status_code=400, detail="company_id is required")
    return next(iter(ids))


def person_for_user(
    session, user: User, company_id: str | None = None
) -> tuple[Personnel, str]:
    """The caller's human Personnel record and company, or an HTTP error."""
    cid = resolve_company_id(session, user, company_id)
    person = session.exec(
        select(Personnel).where(
            Personnel.user_id == user.id,
            Personnel.company_id == cid,
            Personnel.type == "human",
        )
    ).first()
    if not person:
        raise HTTPException(
            status_code=404, detail="No personnel record is linked to this account"
        )
    return person, cid


def _in_scope(session, dept_id: str | None, scope_id: str) -> bool:
    """True if `dept_id` is `scope_id` or one of its sub-departments."""
    seen = 0
    while dept_id and seen < 20:
        if dept_id == scope_id:
            return True
        dept = session.get(Department, dept_id)
        dept_id = dept.parent_id if dept else None
        seen += 1
    return False


def can_manage(session, user: User, ws: Workspace) -> bool:
    """Managers may list / suspend / delete / restore within their scope."""
    members = session.exec(
        select(CompanyMember).where(
            CompanyMember.user_id == user.id,
            CompanyMember.company_id == ws.company_id,
            CompanyMember.role.in_(MANAGER_ROLES),
        )
    ).all()
    if not members:
        return False
    person = session.get(Personnel, ws.personnel_id)
    for m in members:
        if m.role == "founder" or not m.scope_id:
            return True
        if person and _in_scope(session, person.department_id, m.scope_id):
            return True
    return False


def is_owner(ws: Workspace, user: User) -> bool:
    return ws.user_id is not None and ws.user_id == user.id


def to_dict(ws: Workspace) -> dict:
    def iso(d):
        return d.isoformat() if d else None

    return {
        "id": ws.id,
        "company_id": ws.company_id,
        "personnel_id": ws.personnel_id,
        "state": ws.state,
        "error": ws.error,
        "created_at": iso(ws.created_at),
        "last_active_at": iso(ws.last_active_at),
        "suspended_at": iso(ws.suspended_at),
        "deleted_at": iso(ws.deleted_at),
        "purge_after": iso(ws.purge_after),
    }


def live_workspace(session, personnel_id: str) -> Workspace | None:
    return session.exec(
        select(Workspace).where(
            Workspace.personnel_id == personnel_id, Workspace.state != "deleted"
        )
    ).first()


# ── background jobs (wired to the scheduler separately) ───────────────────────


def suspend_idle(
    session, runtime: WorkspaceRuntime, now: datetime, idle_minutes: int = 30
) -> int:
    """Suspend running workspaces idle longer than `idle_minutes`.

    NOTE: does not yet know about a running agent turn or a scheduled flow, which
    ADR-0018 says must block suspension — needs the attach heartbeat / run state.
    """
    cutoff = now - timedelta(minutes=idle_minutes)
    n = 0
    for ws in session.exec(
        select(Workspace).where(
            Workspace.state == "running", Workspace.last_active_at < cutoff
        )
    ).all():
        try:
            runtime.stop(ws.id)
        except WorkspaceRuntimeError:
            continue
        ws.state = "suspended"
        ws.suspended_at = now
        ws.updated_at = now
        session.add(ws)
        n += 1
    session.commit()
    return n


def purge_expired(session, runtime: WorkspaceRuntime, now: datetime) -> int:
    """Purge volumes of deleted workspaces past their retention window."""
    n = 0
    for ws in session.exec(
        select(Workspace).where(
            Workspace.state == "deleted",
            Workspace.purge_after.is_not(None),
            Workspace.purge_after < now,
        )
    ).all():
        try:
            runtime.purge_volume(ws.id)
        except WorkspaceRuntimeError:
            continue
        ws.purge_after = None
        ws.updated_at = now
        session.add(ws)
        n += 1
    session.commit()
    return n
