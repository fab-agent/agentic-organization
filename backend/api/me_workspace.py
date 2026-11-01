"""Signed workspace manifest for the signed-in person (ADR-0028).

The caller is the human behind the session; the person, company, roles and department
are read from the database, never from the request. The company is only checked for
membership. Nothing is signed unless the signing material and catalog are valid
(503 `workspace_unavailable`, with a value-free reason).
"""

import os
import time

from fastapi import APIRouter, Depends, HTTPException, Response

from api.auth import get_current_user
from api.well_known import _cfg
from database import get_session
from models import User
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
    return {k: out[k] for k in ("manifest", "bootstrap")}


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
    try:
        signer = ws.load_signer(int(time.time()))
    except ws.WorkspaceUnavailable as e:
        raise _unavailable(e) from e
    if signer.crl is None:
        raise HTTPException(status_code=404, detail="No revocation list published")
    return signer.crl
