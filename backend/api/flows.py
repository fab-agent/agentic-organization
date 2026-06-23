from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from api.audit import log_action
from api.auth import get_current_user
from database import get_session
from models import Flow, User

router = APIRouter(prefix="/flows", tags=["flows"])


class FlowCreate(BaseModel):
    personnel_id: str
    name: str
    description: Optional[str] = None
    schedule: str       # cron: "0 9 * * 1-5"
    prompt: str
    enabled: bool = True


class FlowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    schedule: Optional[str] = None
    prompt: Optional[str] = None
    enabled: Optional[bool] = None


def _to_dict(f: Flow) -> dict:
    return {
        "id": f.id,
        "company_id": f.company_id,
        "personnel_id": f.personnel_id,
        "name": f.name,
        "description": f.description,
        "schedule": f.schedule,
        "prompt": f.prompt,
        "enabled": f.enabled,
        "last_run_at": f.last_run_at.isoformat() if f.last_run_at else None,
        "last_run_status": f.last_run_status,
        "last_run_output": f.last_run_output,
        "created_at": f.created_at.isoformat(),
        "updated_at": f.updated_at.isoformat(),
    }


@router.get("")
def list_flows(company_id: Optional[str] = None, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        q = select(Flow)
        if company_id:
            q = q.where(Flow.company_id == company_id)
        return [_to_dict(f) for f in session.exec(q.order_by(Flow.created_at.desc())).all()]


@router.get("/{flow_id}")
def get_flow(flow_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        flow = session.get(Flow, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        return _to_dict(flow)


@router.post("", status_code=201)
def create_flow(body: FlowCreate, company_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        flow = Flow(
            company_id=company_id,
            personnel_id=body.personnel_id,
            name=body.name,
            description=body.description,
            schedule=body.schedule,
            prompt=body.prompt,
            enabled=body.enabled,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(flow)
        log_action(session, "create", "flow", entity_id=flow.id, entity_name=flow.name, company_id=flow.company_id, user_id=current_user.id)
        session.commit()
        session.refresh(flow)
        # Reload scheduler
        try:
            from main import _reload_flow_schedules
            _reload_flow_schedules()
        except Exception:
            pass
        return _to_dict(flow)


@router.patch("/{flow_id}")
def update_flow(flow_id: str, body: FlowUpdate, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        flow = session.get(Flow, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        if body.name is not None:        flow.name = body.name
        if body.description is not None: flow.description = body.description
        if body.schedule is not None:    flow.schedule = body.schedule
        if body.prompt is not None:      flow.prompt = body.prompt
        if body.enabled is not None:     flow.enabled = body.enabled
        flow.updated_at = datetime.utcnow()
        session.add(flow)
        log_action(session, "update", "flow", entity_id=flow.id, entity_name=flow.name, company_id=flow.company_id, user_id=current_user.id)
        session.commit()
        session.refresh(flow)
        try:
            from main import _reload_flow_schedules
            _reload_flow_schedules()
        except Exception:
            pass
        return _to_dict(flow)


@router.delete("/{flow_id}", status_code=204)
def delete_flow(flow_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        flow = session.get(Flow, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        log_action(session, "delete", "flow", entity_id=flow.id, entity_name=flow.name, company_id=flow.company_id, user_id=current_user.id)
        session.delete(flow)
        session.commit()
        try:
            from main import _reload_flow_schedules
            _reload_flow_schedules()
        except Exception:
            pass


@router.post("/{flow_id}/run")
def run_flow_now(flow_id: str, current_user: User = Depends(get_current_user)):
    """Manually trigger a flow immediately."""
    from services.flow_runner import run_flow
    with get_session() as session:
        flow = session.get(Flow, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
    run_flow(flow_id)
    with get_session() as session:
        flow = session.get(Flow, flow_id)
        log_action(session, "run", "flow", entity_id=flow.id, entity_name=flow.name, company_id=flow.company_id, user_id=current_user.id, details={"status": flow.last_run_status})
        session.commit()
        return _to_dict(flow)
