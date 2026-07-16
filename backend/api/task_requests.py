"""
Task Request API — user submits a task, system routes to nearest agent.

Routing logic:
  1. Filter agents in company by skill_filter (if given)
  2. Prefer agents in the requested department, then parent departments
  3. Assign to first match → notify responsible human via Inbox
"""

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import select

from api.auth import get_current_user
from core.security import decrypt
from database import get_session
from models import (
    AgentConfig,
    AgentSkillLink,
    CompanySkill,
    Department,
    InboxMessage,
    Personnel,
    ProviderKey,
    Skill,
    TaskRequest,
    User,
)
from services.flow_runner import _build_system_prompt, _call_llm_streaming

router = APIRouter(prefix="/task-requests", tags=["task-requests"])

# Per-task SSE queues: task_id → asyncio.Queue
# Populated when a client opens /task-requests/{id}/stream before or during run.
_task_queues: dict[str, asyncio.Queue] = {}


async def _emit(task_id: str, event: dict) -> None:
    """Push an event to the task's SSE queue if a client is listening."""
    q = _task_queues.get(task_id)
    if q:
        await q.put(event)


def _model_to_provider(model: str) -> str:
    m = model.lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt-", "o1", "o3", "dall-e")):
        return "openai"
    if m.startswith("gemini"):
        return "google"
    if m.startswith(("mistral", "codestral")):
        return "mistral"
    if m.startswith(("qwen", "wanx", "flux")):
        return "qwen"
    return ""


class TaskRequestCreate(BaseModel):
    company_id: str
    department_id: str | None = None
    skill_filter: str | None = None
    title: str
    body: str


class TaskRequestAction(BaseModel):
    human_note: str | None = None


def _to_dict(t: TaskRequest) -> dict:
    return {
        "id": t.id,
        "company_id": t.company_id,
        "requester_user_id": t.requester_user_id,
        "department_id": t.department_id,
        "skill_filter": t.skill_filter,
        "assigned_agent_id": t.assigned_agent_id,
        "responsible_user_id": t.responsible_user_id,
        "title": t.title,
        "body": t.body,
        "human_note": t.human_note,
        "status": t.status,
        "result": t.result,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def _route_agent(
    session, company_id: str, department_id: str | None, skill_filter: str | None
) -> AgentConfig | None:
    """Find best matching agent. Dept first → parent dept → company-wide."""
    dept_ids_to_try: list[str | None] = []
    if department_id:
        dept_ids_to_try.append(department_id)
        # Walk up parent chain
        dept = session.get(Department, department_id)
        while dept and dept.parent_id:
            dept_ids_to_try.append(dept.parent_id)
            dept = session.get(Department, dept.parent_id)
    dept_ids_to_try.append(None)  # company-wide fallback

    for dept_id in dept_ids_to_try:
        q = (
            select(AgentConfig)
            .join(Personnel, AgentConfig.personnel_id == Personnel.id)
            .where(Personnel.company_id == company_id)
            .where(Personnel.type == "agent")
            .where(AgentConfig.status == "active")
        )
        if dept_id:
            q = q.where(Personnel.department_id == dept_id)
        else:
            pass  # company-wide

        candidates = session.exec(q).all()

        if skill_filter:
            matched = []
            for cfg in candidates:
                # Check legacy Skill table
                skills = session.exec(
                    select(Skill)
                    .where(Skill.agent_id == cfg.id)
                    .where(Skill.is_active == True)
                ).all()
                # Also check CompanySkill assignments via AgentSkillLink
                company_skills = session.exec(
                    select(CompanySkill)
                    .join(
                        AgentSkillLink,
                        AgentSkillLink.company_skill_id == CompanySkill.id,
                    )
                    .where(AgentSkillLink.agent_config_id == cfg.id)
                    .where(CompanySkill.is_active == True)
                ).all()
                all_skill_names = [s.name for s in skills] + [
                    s.name for s in company_skills
                ]
                if any(skill_filter.lower() in n.lower() for n in all_skill_names):
                    matched.append(cfg)
            candidates = matched

        if candidates:
            return candidates[0]

    return None


@router.get("")
def list_task_requests(
    company_id: str | None = None,
    status: str | None = None,
    current_user: User = Depends(get_current_user),
):
    with get_session() as session:
        q = select(TaskRequest)
        # Show tasks the user submitted OR tasks assigned to them as responsible
        q = q.where(
            (TaskRequest.requester_user_id == current_user.id)
            | (TaskRequest.responsible_user_id == current_user.id)
        )
        if company_id:
            q = q.where(TaskRequest.company_id == company_id)
        if status:
            q = q.where(TaskRequest.status == status)
        q = q.order_by(TaskRequest.created_at.desc())
        return [_to_dict(t) for t in session.exec(q).all()]


@router.post("", status_code=201)
def create_task_request(
    body: TaskRequestCreate, current_user: User = Depends(get_current_user)
):
    with get_session() as session:
        agent_cfg = _route_agent(
            session, body.company_id, body.department_id, body.skill_filter
        )

        responsible_user_id: str | None = None
        if agent_cfg:
            if agent_cfg.responsible_id:
                resp_personnel = session.get(Personnel, agent_cfg.responsible_id)
                if resp_personnel and resp_personnel.user_id:
                    responsible_user_id = resp_personnel.user_id

        task = TaskRequest(
            company_id=body.company_id,
            requester_user_id=current_user.id,
            department_id=body.department_id,
            skill_filter=body.skill_filter,
            assigned_agent_id=agent_cfg.personnel_id if agent_cfg else None,
            responsible_user_id=responsible_user_id,
            title=body.title,
            body=body.body,
            status="assigned" if agent_cfg else "pending",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(task)
        session.commit()
        session.refresh(task)

        # Notify responsible human via inbox
        if responsible_user_id and agent_cfg:
            agent = session.get(Personnel, agent_cfg.personnel_id)
            msg = InboxMessage(
                company_id=body.company_id,
                recipient_user_id=responsible_user_id,
                source_type="task_request",
                source_id=task.id,
                title=f"[İş Talebi] {body.title}",
                body=f"**Talep:** {body.title}\n\n{body.body}\n\n---\n*Ajan: {agent.name if agent else '?'}*",
                created_at=datetime.utcnow(),
            )
            session.add(msg)
            session.commit()

        return _to_dict(task)


@router.post("/{task_id}/run")
async def run_task(
    task_id: str,
    body: TaskRequestAction,
    current_user: User = Depends(get_current_user),
):
    """Responsible human reviews, optionally adds a note, and triggers agent execution."""
    with get_session() as session:
        task = session.get(TaskRequest, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.responsible_user_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Only the responsible user can trigger this task",
            )
        if task.status not in ("assigned", "pending"):
            raise HTTPException(
                status_code=400, detail=f"Task is in '{task.status}' status"
            )

        if body.human_note:
            task.human_note = body.human_note

        task.status = "running"
        task.updated_at = datetime.utcnow()
        session.add(task)
        session.commit()

        await _emit(
            task_id,
            {"type": "step", "step": "starting", "label": "Ajan başlatılıyor..."},
        )

        try:
            agent = session.get(Personnel, task.assigned_agent_id)
            agent_cfg = session.exec(
                select(AgentConfig).where(
                    AgentConfig.personnel_id == task.assigned_agent_id
                )
            ).first()
            if not agent or not agent_cfg:
                raise ValueError("Agent or config not found")

            # Find active provider key — prefer agent's own provider, then fallback list
            provider_key = None
            agent_provider = _model_to_provider(agent_cfg.model or "")
            for prov in ([agent_provider] if agent_provider else []) + [
                "anthropic",
                "openai",
                "google",
                "mistral",
                "qwen",
            ]:
                if not prov:
                    continue
                pk = session.exec(
                    select(ProviderKey)
                    .where(ProviderKey.provider == prov)
                    .where(ProviderKey.status == "active")
                ).first()
                if pk:
                    provider_key = pk
                    break

            if not provider_key:
                raise ValueError("No active provider key")

            await _emit(
                task_id,
                {
                    "type": "step",
                    "step": "model_ready",
                    "label": f"Model: {agent_cfg.model} · Provider: {provider_key.provider}",
                },
            )

            api_key = decrypt(provider_key.encrypted_key)
            system_prompt = _build_system_prompt(agent, agent_cfg)
            user_prompt = task.body
            if task.human_note:
                user_prompt += f"\n\n**Sorumlu notu:** {task.human_note}"

            await _emit(
                task_id,
                {
                    "type": "step",
                    "step": "calling_llm",
                    "label": "LLM çağrısı yapılıyor...",
                },
            )

            # Stream tokens to SSE queue while collecting full result
            loop = asyncio.get_event_loop()
            chunks: list[str] = []

            def on_chunk(text: str) -> None:
                chunks.append(text)
                asyncio.run_coroutine_threadsafe(
                    _emit(task_id, {"type": "chunk", "text": text}), loop
                )

            result = await asyncio.to_thread(
                _call_llm_streaming,
                provider_key.provider,
                agent_cfg.model,
                system_prompt,
                user_prompt,
                api_key,
                on_chunk,
            )

            task.result = result
            task.status = "completed"
            task.updated_at = datetime.utcnow()
            session.add(task)

            # Deliver result to requester's inbox
            msg = InboxMessage(
                company_id=task.company_id,
                recipient_user_id=task.requester_user_id,
                source_type="task_result",
                source_id=task.id,
                title=f"[Sonuç] {task.title}",
                body=result,
                created_at=datetime.utcnow(),
            )
            session.add(msg)
            session.commit()
            session.refresh(task)

            await _emit(task_id, {"type": "done", "status": "completed"})

        except Exception as e:
            task.status = "assigned"  # revert to allow retry
            task.result = f"Hata: {str(e)}"
            task.updated_at = datetime.utcnow()
            session.add(task)
            session.commit()
            session.refresh(task)
            await _emit(task_id, {"type": "error", "message": str(e)})

        return _to_dict(task)


@router.get("/{task_id}/stream")
async def stream_task(task_id: str, current_user: User = Depends(get_current_user)):
    """SSE stream for task execution events. Open before or right after calling /run."""
    q: asyncio.Queue = asyncio.Queue()
    _task_queues[task_id] = q

    async def event_gen():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=180)
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'timeout'})}\n\n"
                    break
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "error", "timeout"):
                    break
        finally:
            _task_queues.pop(task_id, None)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/{task_id}/reject")
def reject_task(
    task_id: str,
    body: TaskRequestAction,
    current_user: User = Depends(get_current_user),
):
    with get_session() as session:
        task = session.get(TaskRequest, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.responsible_user_id != current_user.id:
            raise HTTPException(
                status_code=403, detail="Only the responsible user can reject this task"
            )
        task.status = "rejected"
        task.human_note = body.human_note
        task.updated_at = datetime.utcnow()
        session.add(task)
        session.commit()
        session.refresh(task)
        return _to_dict(task)
