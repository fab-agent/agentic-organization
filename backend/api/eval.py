"""Run diagnosis API (ADR-0023).

Read access follows who is accountable for the persona *today*:
- founder, or an executive / department head without a department scope: every
  agent persona of the company;
- an executive / department head with a scope: personas of that department only;
- the agent's responsible human, or its agent_owner.
This is deliberately narrower than the workstation "act as" rule, which treats any
executive as company-wide. Access to a persona includes its stored history (an
explicit decision: ownership transfers history). Unknown and unauthorised objects
get the same 404.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from api.auth import get_current_user
from database import get_session
from models import AgentConfig, CompanyMember, Personnel, RunDiagnosis, User
from services.run_reader import RUN_ID, diagnose_and_store, to_dict

router = APIRouter(prefix="/eval", tags=["eval"])

_MAX_LIST = 100
_COMPANY_WIDE = {"founder", "executive", "dept_head"}


def _persona_company(session, user: User, persona_id: str) -> str:
    """company_id of an agent persona the caller may read, else 404."""
    person = session.get(Personnel, persona_id)
    cfg = (
        session.exec(
            select(AgentConfig).where(AgentConfig.personnel_id == persona_id)
        ).first()
        if person and person.type == "agent" and person.company_id
        else None
    )
    if person is None or cfg is None:
        raise HTTPException(status_code=404, detail="Not found")
    mine = session.exec(
        select(CompanyMember).where(
            CompanyMember.user_id == user.id,
            CompanyMember.company_id == person.company_id,
        )
    ).all()
    my_person = session.exec(
        select(Personnel).where(
            Personnel.user_id == user.id, Personnel.company_id == person.company_id
        )
    ).first()
    allowed = bool(my_person and cfg.responsible_id == my_person.id)
    for m in mine:
        if m.role == "founder":
            allowed = True
        elif m.role in _COMPANY_WIDE and (
            m.scope_id is None or m.scope_id == person.department_id
        ):
            allowed = True
        elif m.role == "agent_owner" and m.scope_id == persona_id:
            allowed = True
    if not allowed:
        raise HTTPException(status_code=404, detail="Not found")
    return person.company_id


def _valid_run(run_id: str) -> str:
    if not RUN_ID.fullmatch(run_id):
        raise HTTPException(status_code=404, detail="Not found")
    return run_id


@router.get("/personas/{persona_id}/runs")
def list_runs(persona_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        company_id = _persona_company(session, user, persona_id)
        rows = session.exec(
            select(RunDiagnosis)
            .where(
                RunDiagnosis.company_id == company_id,
                RunDiagnosis.persona_id == persona_id,
            )
            .order_by(RunDiagnosis.updated_at.desc())
            .limit(_MAX_LIST)
        ).all()
        return [to_dict(r) for r in rows]


@router.get("/personas/{persona_id}/runs/{run_id}")
def get_run(persona_id: str, run_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        company_id = _persona_company(session, user, persona_id)
        row = session.get(RunDiagnosis, (company_id, persona_id, _valid_run(run_id)))
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return to_dict(row)


@router.post("/personas/{persona_id}/runs/{run_id}/diagnose")
def diagnose_run(persona_id: str, run_id: str, user: User = Depends(get_current_user)):
    """(Re)compute and store the diagnosis of one run from the audit chain.

    A run with no audit events is unknown (404, nothing written); a result computed
    in the last few seconds is returned as is.
    """
    with get_session() as session:
        company_id = _persona_company(session, user, persona_id)
        row = diagnose_and_store(session, company_id, persona_id, _valid_run(run_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Not found")
        return to_dict(row)
