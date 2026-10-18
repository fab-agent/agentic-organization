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
from services import authz
from services.judges import judge_run, success_interval
from services.run_reader import RUN_ID, diagnose_and_store, diagnosis_from_row, to_dict

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
    # The department view is not a management role (ADR-0022 §7): being "responsible"
    # for one's own assistant does not open agent-wide diagnoses.
    allowed = bool(
        my_person
        and cfg.responsible_id == my_person.id
        and not authz.is_assistant_only(session, user.id, person.company_id)
    )
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


GROUP_FLOOR = 3  # people; below it only "not enough data" is shown (ADR-0021)


def _feedback(session, company_id: str, persona_id: str) -> dict:
    """Counts of human signals on this persona's answers over 30 days. No text, no
    names; below the group floor of distinct people the numbers are withheld so a
    single person's opinion cannot be read off."""
    from datetime import datetime, timedelta

    from models import LearningSignal
    from services import work_review as wr

    if not wr.enabled(session, company_id):
        # Review switched off: collected feedback is not shown either.
        return {"enough": False, "people": None}
    since = datetime.utcnow() - timedelta(days=30)
    rows = session.exec(
        select(LearningSignal.kind, LearningSignal.user_id).where(
            LearningSignal.withdrawn_at.is_(None),
            LearningSignal.company_id == company_id,
            LearningSignal.persona_id == persona_id,
            LearningSignal.created_at >= since,
        )
    ).all()
    people = len({u for _, u in rows})
    if people < max(GROUP_FLOOR, wr.min_group()):
        return {"enough": False, "people": people if people == 0 else None}
    count = lambda k: sum(1 for kind, _ in rows if kind == k)  # noqa: E731
    return {
        "enough": True,
        "people": people,
        "thumbs_up": count("thumbs_up"),
        "thumbs_down": count("thumbs_down"),
        "corrections": count("correction"),
        "days": 30,
    }


@router.get("/personas/{persona_id}/summary")
def persona_summary(persona_id: str, user: User = Depends(get_current_user)):
    """Success and suspect-layer counts over the stored diagnoses of one persona.

    Success comes from deterministic judges over the stage-1 diagnosis; abstentions
    are counted apart, never as passes. The suspect layers are hypotheses (stage 1),
    not fault rates: those need replay confirmation (ADR-0023).
    """
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
    criteria: dict[str, dict[str, int]] = {}
    suspects: dict[str, int] = {}
    for r in rows:
        d = diagnosis_from_row(r)
        for v in judge_run(d):
            c = criteria.setdefault(v.criterion_id, {"yes": 0, "no": 0, "unclear": 0})
            c[v.value] += 1
        if r.suspect_layer:
            suspects[r.suspect_layer] = suspects.get(r.suspect_layer, 0) + 1
    with get_session() as session:
        feedback = _feedback(session, company_id, persona_id)
    return {
        "feedback": feedback,
        "runs": len(rows),
        "criteria": {
            cid: {**c, "success": success_interval(c["yes"], c["yes"] + c["no"])}
            for cid, c in criteria.items()
        },
        "suspect_counts": suspects,
        "note": "Suspect layers are stage-1 hypotheses, not fault rates.",
    }


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
