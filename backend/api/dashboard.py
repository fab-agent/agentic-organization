from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import func, select

from api.auth import get_current_user
from database import get_session
from models import (
    AgentConfig, AgentMemory, AgentSession, Company, CompanyMember,
    Personnel, SessionMessage, User,
)

router = APIRouter(tags=["dashboard"])


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/dashboard/stats")
def company_stats(company_id: Optional[str] = None, user: User = Depends(get_current_user)):
    with get_session() as session:
        # Resolve company_id
        if not company_id:
            first_mem = session.exec(
                select(CompanyMember).where(CompanyMember.user_id == user.id)
            ).first()
            company_id = first_mem.company_id if first_mem else None
        if not company_id:
            return {}

        # All personnel in company
        people = session.exec(
            select(Personnel).where(Personnel.company_id == company_id)
        ).all()
        human_count = sum(1 for p in people if p.type == "human")
        agent_count = sum(1 for p in people if p.type == "agent")
        personnel_ids = [p.id for p in people]

        # Active agents (agent_config.status == "active")
        active_agents = session.exec(
            select(func.count(AgentConfig.id))
            .join(Personnel, AgentConfig.personnel_id == Personnel.id)
            .where(Personnel.company_id == company_id)
            .where(AgentConfig.status == "active")
        ).one() or 0

        # Sessions today and totals
        today = _today_start()
        if personnel_ids:
            all_sessions = session.exec(
                select(AgentSession).where(AgentSession.personnel_id.in_(personnel_ids))
            ).all()
        else:
            all_sessions = []

        total_sessions = len(all_sessions)
        today_sessions = sum(
            1 for s in all_sessions
            if s.created_at.replace(tzinfo=timezone.utc) >= today
        )
        active_sessions = sum(1 for s in all_sessions if s.status == "active")

        # Token usage
        session_ids = [s.id for s in all_sessions]
        total_tokens = 0
        today_tokens = 0
        if session_ids:
            msgs = session.exec(
                select(SessionMessage).where(SessionMessage.session_id.in_(session_ids))
            ).all()
            for m in msgs:
                t = m.tokens_used or 0
                total_tokens += t
                if m.created_at.replace(tzinfo=timezone.utc) >= today:
                    today_tokens += t

        # Long-term memories count
        memory_count = 0
        if personnel_ids:
            memory_count = session.exec(
                select(func.count(AgentMemory.id))
                .where(AgentMemory.personnel_id.in_(personnel_ids))
            ).one() or 0

        return {
            "company_id": company_id,
            "human_count": human_count,
            "agent_count": agent_count,
            "total_personnel": human_count + agent_count,
            "active_agents": active_agents,
            "total_sessions": total_sessions,
            "today_sessions": today_sessions,
            "active_sessions": active_sessions,
            "total_tokens": total_tokens,
            "today_tokens": today_tokens,
            "memory_count": memory_count,
        }


@router.get("/dashboard/me")
def my_dashboard(company_id: Optional[str] = None, user: User = Depends(get_current_user)):
    """Returns the current user's personal telemetry (linked personnel record)."""
    with get_session() as session:
        # Resolve company_id
        if not company_id:
            first_mem = session.exec(
                select(CompanyMember).where(CompanyMember.user_id == user.id)
            ).first()
            company_id = first_mem.company_id if first_mem else None

        # Find personnel record linked to this user
        person = None
        if company_id:
            person = session.exec(
                select(Personnel)
                .where(Personnel.user_id == user.id)
                .where(Personnel.company_id == company_id)
            ).first()

        if not person:
            return {"linked": False}

        today = _today_start()

        # Find agents this user is responsible for
        responsible_agent_cfgs = session.exec(
            select(AgentConfig).where(AgentConfig.responsible_id == person.id)
        ).all()
        agent_personnel_ids = [a.personnel_id for a in responsible_agent_cfgs]

        # If user has no responsible agents, fall back to all company agents
        if not agent_personnel_ids and company_id:
            all_company_people = session.exec(
                select(Personnel)
                .where(Personnel.company_id == company_id)
                .where(Personnel.type == "agent")
            ).all()
            agent_personnel_ids = [p.id for p in all_company_people]

        # Sessions for those agents
        if agent_personnel_ids:
            sessions_q = session.exec(
                select(AgentSession)
                .where(AgentSession.personnel_id.in_(agent_personnel_ids))
                .order_by(AgentSession.updated_at.desc())
            ).all()
        else:
            sessions_q = []

        total_tokens = 0
        today_tokens = 0
        session_ids = [s.id for s in sessions_q]
        if session_ids:
            msgs = session.exec(
                select(SessionMessage).where(SessionMessage.session_id.in_(session_ids))
            ).all()
            for m in msgs:
                t = m.tokens_used or 0
                total_tokens += t
                if m.created_at.replace(tzinfo=timezone.utc) >= today:
                    today_tokens += t

        # Memories for those agents
        memories = session.exec(
            select(AgentMemory)
            .where(AgentMemory.personnel_id.in_(agent_personnel_ids) if agent_personnel_ids else AgentMemory.personnel_id == "")
            .order_by(AgentMemory.created_at.desc())
        ).all()

        return {
            "linked": True,
            "personnel_id": person.id,
            "personnel_name": person.name,
            "personnel_title": person.title,
            "total_sessions": len(sessions_q),
            "today_sessions": sum(
                1 for s in sessions_q
                if s.created_at.replace(tzinfo=timezone.utc) >= today
            ),
            "active_sessions": sum(1 for s in sessions_q if s.status == "active"),
            "total_tokens": total_tokens,
            "today_tokens": today_tokens,
            "recent_sessions": [
                {
                    "id": s.id,
                    "title": s.title,
                    "status": s.status,
                    "updated_at": s.updated_at.isoformat(),
                    "created_at": s.created_at.isoformat(),
                }
                for s in sessions_q[:5]
            ],
            "memories": [
                {
                    "id": m.id,
                    "summary": m.summary,
                    "session_id": m.session_id,
                    "created_at": m.created_at.isoformat(),
                }
                for m in memories[:10]
            ],
        }
