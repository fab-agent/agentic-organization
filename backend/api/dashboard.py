from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlmodel import func, select

from api.auth import get_current_user
from database import get_session
from models import (
    A2ARequest,
    AgentConfig,
    AgentMemory,
    AgentSession,
    CompanyMember,
    Flow,
    Personnel,
    SessionMessage,
    TaskRequest,
    User,
)
from services import authz

router = APIRouter(tags=["dashboard"])


def _today_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/dashboard/stats")
def company_stats(
    company_id: str | None = None, user: User = Depends(get_current_user)
):
    with get_session() as session:
        # Resolve company_id
        if not company_id:
            first_mem = session.exec(
                select(CompanyMember).where(CompanyMember.user_id == user.id)
            ).first()
            company_id = first_mem.company_id if first_mem else None
        if not company_id:
            return {}
        authz.require_member(session, user.id, company_id)
        authz.deny_assistant(session, user.id, company_id)

        # All personnel in company
        people = session.exec(
            select(Personnel).where(Personnel.company_id == company_id)
        ).all()
        human_count = sum(1 for p in people if p.type == "human")
        agent_count = sum(1 for p in people if p.type == "agent")
        personnel_ids = [p.id for p in people]

        # Active agents (agent_config.status == "active")
        active_agents = (
            session.exec(
                select(func.count(AgentConfig.id))
                .join(Personnel, AgentConfig.personnel_id == Personnel.id)
                .where(Personnel.company_id == company_id)
                .where(AgentConfig.status == "active")
            ).one()
            or 0
        )

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
            1 for s in all_sessions if s.created_at.replace(tzinfo=UTC) >= today
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
                if m.created_at.replace(tzinfo=UTC) >= today:
                    today_tokens += t

        # Long-term memories count
        memory_count = 0
        if personnel_ids:
            memory_count = (
                session.exec(
                    select(func.count(AgentMemory.id)).where(
                        AgentMemory.personnel_id.in_(personnel_ids)
                    )
                ).one()
                or 0
            )

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
def my_dashboard(company_id: str | None = None, user: User = Depends(get_current_user)):
    """Returns the current user's personal telemetry (linked personnel record)."""
    with get_session() as session:
        # Resolve company_id
        if not company_id:
            first_mem = session.exec(
                select(CompanyMember).where(CompanyMember.user_id == user.id)
            ).first()
            company_id = first_mem.company_id if first_mem else None
        if company_id:
            authz.require_member(session, user.id, company_id)

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

        # Own chats, plus chats with agents this user is responsible for.
        cond = AgentSession.user_id == user.id
        if agent_personnel_ids and not authz.is_assistant_only(
            session, user.id, company_id
        ):
            cond = cond | AgentSession.personnel_id.in_(agent_personnel_ids)
        sessions_q = session.exec(
            select(AgentSession).where(cond).order_by(AgentSession.updated_at.desc())
        ).all()

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
                if m.created_at.replace(tzinfo=UTC) >= today:
                    today_tokens += t

        # Memories for those agents
        memories = session.exec(
            select(AgentMemory)
            .where(
                AgentMemory.personnel_id.in_(agent_personnel_ids)
                if agent_personnel_ids
                else AgentMemory.personnel_id == ""
            )
            .order_by(AgentMemory.created_at.desc())
        ).all()

        return {
            "linked": True,
            "personnel_id": person.id,
            "personnel_name": person.name,
            "personnel_title": person.title,
            "total_sessions": len(sessions_q),
            "today_sessions": sum(
                1 for s in sessions_q if s.created_at.replace(tzinfo=UTC) >= today
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


@router.get("/dashboard/agent-sla")
def agent_sla(company_id: str | None = None, user: User = Depends(get_current_user)):
    """Per-agent SLA metrics: sessions, tokens, flow success rate, task completion."""
    with get_session() as session:
        if not company_id:
            first_mem = session.exec(
                select(CompanyMember).where(CompanyMember.user_id == user.id)
            ).first()
            company_id = first_mem.company_id if first_mem else None
        if not company_id:
            return {"agents": []}
        authz.require_role(session, user.id, company_id, authz.MANAGERS)

        agents = session.exec(
            select(Personnel)
            .where(Personnel.company_id == company_id)
            .where(Personnel.type == "agent")
        ).all()

        results = []
        for agent in agents:
            cfg = session.exec(
                select(AgentConfig).where(AgentConfig.personnel_id == agent.id)
            ).first()

            agent_sessions = session.exec(
                select(AgentSession).where(AgentSession.personnel_id == agent.id)
            ).all()
            session_ids = [s.id for s in agent_sessions]

            total_tokens = 0
            if session_ids:
                msgs = session.exec(
                    select(SessionMessage).where(
                        SessionMessage.session_id.in_(session_ids)
                    )
                ).all()
                total_tokens = sum(m.tokens_used or 0 for m in msgs)

            flows = session.exec(
                select(Flow).where(Flow.personnel_id == agent.id)
            ).all()
            flow_success = sum(1 for f in flows if f.last_run_status == "success")
            flow_error = sum(1 for f in flows if f.last_run_status == "error")

            tasks = session.exec(
                select(TaskRequest).where(TaskRequest.assigned_agent_id == agent.id)
            ).all()
            task_total = len(tasks)
            task_completed = sum(1 for t in tasks if t.status == "completed")

            # Count A2A delegations initiated by this agent as additional tasks
            a2a_reqs = session.exec(
                select(A2ARequest).where(A2ARequest.from_agent_id == agent.id)
            ).all()
            task_total += len(a2a_reqs)
            task_completed += sum(1 for r in a2a_reqs if r.status == "completed")

            total_ops = flow_success + flow_error + task_total
            completed_ops = flow_success + task_completed
            success_rate = (
                round(completed_ops / total_ops * 100, 1) if total_ops > 0 else None
            )

            results.append(
                {
                    "id": agent.id,
                    "name": agent.name,
                    "title": agent.title,
                    "status": cfg.status if cfg else "draft",
                    "total_sessions": len(agent_sessions),
                    "active_sessions": sum(
                        1 for s in agent_sessions if s.status == "active"
                    ),
                    "total_tokens": total_tokens,
                    "flow_count": len(flows),
                    "flow_success": flow_success,
                    "flow_error": flow_error,
                    "task_total": task_total,
                    "task_completed": task_completed,
                    "success_rate": success_rate,
                }
            )

        return {"agents": results}
