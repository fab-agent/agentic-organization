"""Signed workspace manifest for the signed-in person (ADR-0028).

The caller is the human behind the session; the person, company, roles and department
are read from the database, never from the request. The company is only checked for
membership. Nothing is signed unless the signing material and catalog are valid
(503 `workspace_unavailable`, with a value-free reason).
"""

import os
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from api.auth import get_current_user
from api.well_known import _cfg
from database import get_session
from models import User, WorkspaceClientReport
from services import audit_chain
from services import workspace_service as ws
from services.workspaces import person_for_user

router = APIRouter(prefix="/me/workspace", tags=["workspace"])


def configured_gateway_url(session) -> str:
    """Where the signed manifest sends the client. Only operator configuration counts
    (`workstation.base_url`, else PUBLIC_BASE_URL / WORKSTATION_BASE_URL): the Host header
    of the request is never trusted for a value that is then signed (ADR-0028)."""
    url = (
        _cfg(session, "workstation.base_url")
        or os.getenv("PUBLIC_BASE_URL", "")
        or os.getenv("WORKSTATION_BASE_URL", "")
    )
    if not url:
        raise ws.WorkspaceUnavailable("gateway_url_not_configured")
    return url.rstrip("/")


def _unavailable(e: ws.WorkspaceUnavailable) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"error": "workspace_unavailable", "reason": e.reason},
        headers={"Retry-After": "30"},
    )


@router.get("")
def get_workspace(
    company_id: str | None = None,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        try:
            out = ws.issue_manifest(
                session,
                user_id=user.id,
                person=person,
                company_id=cid,
                gateway_url=configured_gateway_url(session),
            )
        except ws.WorkspaceUnavailable as e:
            raise _unavailable(e) from e
        env = out["manifest"]["payload"]
        # No manifest without a record: it hands out code to run.
        ev = audit_chain.record(
            actor_type="human",
            actor_id=user.id,
            company_id=cid,
            action="workspace_manifest_issued",
            target=person.id,
            reason=out["profile"],
            payload={
                "generation": env["generation"],
                "epoch": env["epoch"],
                "layout": env["layout"]["id"],
                "mods": [f"{m['name']}@{m['version']}" for m in env["mods"]],
                "signing_kid": out["manifest"]["cert"]["payload"]["kid"],
            },
        )
        if ev is None:
            raise _unavailable(ws.WorkspaceUnavailable("audit_unavailable"))
    # `identity` is who this signed-in session is, so a client can pin it on first use and
    # refuse a manifest for anyone else later (the manifest repeats it, signed).
    return {
        "manifest": out["manifest"],
        "bootstrap": out["bootstrap"],
        "identity": {"company_id": cid, "person_id": person.id},
    }


@router.get("/files/{sha256}")
def get_workspace_file(
    sha256: str,
    company_id: str | None = None,
    user: User = Depends(get_current_user),
):
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        try:
            data = ws.file_for_person(
                session, user_id=user.id, person=person, company_id=cid, sha256=sha256
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Not part of your workspace")
        except ws.WorkspaceUnavailable as e:
            raise _unavailable(e) from e
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{sha256}"',
        },
    )


@router.get("/crl")
def get_workspace_crl(user: User = Depends(get_current_user)):
    """The root-signed revocation list. Serving it goes through the same checkpoint as
    the bootstrap floors, so this endpoint and /me/workspace can never disagree or
    lower each other."""
    try:
        view = ws.load_crl(int(time.time()))
        with get_session() as session:
            ws.enforce_crl_highwater(session, view)
    except ws.WorkspaceUnavailable as e:
        raise _unavailable(e) from e
    if view.crl is None:
        raise HTTPException(status_code=404, detail="No revocation list published")
    return view.crl


REPORT_MIN_INTERVAL = timedelta(seconds=30)


class DriftReport(BaseModel):
    """What a client says about its own app home (ADR-0035): counts only."""

    model_config = ConfigDict(extra="forbid", strict=True)

    client_version: str = Field(pattern=r"^[0-9A-Za-z.+-]{1,32}$")
    epoch: int = Field(ge=0, le=2**31 - 1)
    generation: int = Field(ge=0, le=2**53 - 1)
    missing: int = Field(ge=0, le=100000)
    modified: int = Field(ge=0, le=100000)
    extra: int = Field(ge=0, le=100000)
    unmanaged: int = Field(ge=0, le=100000)
    interrupted: bool


@router.post("/report", status_code=204)
def report_drift(
    body: DriftReport,
    company_id: str | None = None,
    user: User = Depends(get_current_user),
):
    """Store the caller's own latest drift claim. The person and company come from the
    session, never from the body. A claim: it feeds a diagnostic view and nothing else."""
    now = datetime.utcnow()
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        row = session.exec(
            select(WorkspaceClientReport).where(
                WorkspaceClientReport.company_id == cid,
                WorkspaceClientReport.person_id == person.id,
            )
        ).first()
        if row and now - row.received_at < REPORT_MIN_INTERVAL:
            raise HTTPException(
                status_code=429,
                detail="Reports are limited to one every 30 seconds",
                headers={"Retry-After": "30"},
            )
        row = row or WorkspaceClientReport(company_id=cid, person_id=person.id)
        for k, v in body.model_dump().items():
            setattr(row, k, v)
        row.received_at = now
        session.add(row)
        try:
            session.commit()
        except (
            IntegrityError
        ):  # two first reports at once: the other one won; this is "too soon"
            session.rollback()
            raise HTTPException(
                status_code=429,
                detail="Reports are limited to one every 30 seconds",
                headers={"Retry-After": "30"},
            ) from None
    return Response(status_code=204)
