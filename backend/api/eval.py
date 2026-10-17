"""Run diagnosis API (ADR-0023). Read access follows the persona rule of the
workstation: a user sees diagnoses only for personas they may act as (founder /
executive of the company, the responsible human, or the agent's owner). Unknown and
unauthorised objects get the same 404."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from api.auth import get_current_user
from api.workstation import _personas_for_user
from database import get_session
from models import RunDiagnosis, User
from services.run_reader import diagnose_and_store, to_dict

router = APIRouter(prefix="/eval", tags=["eval"])

_MAX_LIST = 100


def _allowed_persona(session, user: User, persona_id: str) -> dict:
    for persona in _personas_for_user(session, user):
        if persona["personnel_id"] == persona_id:
            return persona
    raise HTTPException(status_code=404, detail="Not found")


@router.get("/personas/{persona_id}/runs")
def list_runs(persona_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        persona = _allowed_persona(session, user, persona_id)
        rows = session.exec(
            select(RunDiagnosis)
            .where(
                RunDiagnosis.company_id == persona["company_id"],
                RunDiagnosis.persona_id == persona_id,
            )
            .order_by(RunDiagnosis.updated_at.desc())
            .limit(_MAX_LIST)
        ).all()
        return [to_dict(r) for r in rows]


@router.get("/personas/{persona_id}/runs/{run_id}")
def get_run(persona_id: str, run_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        persona = _allowed_persona(session, user, persona_id)
        row = session.get(RunDiagnosis, (persona["company_id"], persona_id, run_id))
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return to_dict(row)


@router.post("/personas/{persona_id}/runs/{run_id}/diagnose")
def diagnose_run(persona_id: str, run_id: str, user: User = Depends(get_current_user)):
    """(Re)compute and store the diagnosis of one run from the audit chain."""
    with get_session() as session:
        persona = _allowed_persona(session, user, persona_id)
        row = diagnose_and_store(session, persona["company_id"], persona_id, run_id)
        return to_dict(row)
