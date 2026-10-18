"""The department assistant view (ADR-0022 §7): "my context", read-only.

Everything is derived from the caller's own Personnel record and returned as an
allowlisted projection (names, roles, departments; never the full personnel record,
emails, tokens or other people's configuration). The role `assistant_user` sees no
company-wide lists elsewhere in the API (`authz.deny_assistant`).
"""

import json

from fastapi import APIRouter, Depends
from sqlmodel import select

from api.auth import get_current_user
from database import get_session
from models import (
    AgentConfig,
    AgentSkillLink,
    Company,
    CompanySkill,
    Department,
    Personnel,
    Skill,
    User,
)
from services import authz
from services.policy_engine import applicable_policies
from services.workspaces import person_for_user

router = APIRouter(prefix="/assistant", tags=["assistant"])

_MAX_COLLEAGUES = 50
_MAX_POLICY_CHARS = 4000


def _my_agent(session, person: Personnel) -> tuple[Personnel, AgentConfig] | None:
    """The caller's own agent: their workspace agent, else one they are responsible for."""
    rows = session.exec(
        select(Personnel, AgentConfig)
        .join(AgentConfig, AgentConfig.personnel_id == Personnel.id)
        .where(
            Personnel.company_id == person.company_id,
            Personnel.type == "agent",
            AgentConfig.responsible_id == person.id,
        )
        .order_by(AgentConfig.is_workspace_agent.desc(), Personnel.name)
    ).all()
    return rows[0] if rows else None


@router.get("/context")
def my_context(company_id: str | None = None, user: User = Depends(get_current_user)):
    with get_session() as session:
        person, cid = person_for_user(session, user, company_id)
        company = session.get(Company, cid)
        meta = (
            json.loads(company.metadata_json)
            if company and company.metadata_json
            else {}
        )
        dept = (
            session.get(Department, person.department_id)
            if person.department_id
            else None
        )
        manager = (
            session.get(Personnel, person.manager_id) if person.manager_id else None
        )

        mine = _my_agent(session, person)
        agent, cfg = mine if mine else (None, None)

        tools: list[dict] = []
        if cfg:
            for s in session.exec(
                select(Skill).where(Skill.agent_id == cfg.id, Skill.is_active == True)
            ).all():  # noqa: E712
                tools.append({"name": s.name, "description": s.description})
            for cs in session.exec(
                select(CompanySkill)
                .join(
                    AgentSkillLink, AgentSkillLink.company_skill_id == CompanySkill.id
                )
                .where(
                    AgentSkillLink.agent_config_id == cfg.id,
                    CompanySkill.company_id == cid,
                    CompanySkill.is_active == True,  # noqa: E712
                )
            ).all():
                tools.append({"name": cs.name, "description": cs.description})

        colleagues: list[dict] = []
        if dept:
            for c in session.exec(
                select(Personnel)
                .where(
                    Personnel.company_id == cid,
                    Personnel.department_id == dept.id,
                    Personnel.type == "human",
                    Personnel.id != person.id,
                    Personnel.id != (person.manager_id or ""),
                )
                .order_by(Personnel.name)
                .limit(_MAX_COLLEAGUES)
            ).all():
                colleagues.append({"name": c.name, "role": c.title or c.role})

        policies = [
            {"name": name, "content": body[:_MAX_POLICY_CHARS]}
            for name, body in applicable_policies(
                cid, person.department_id, cfg.id if cfg else None
            )
        ]

        return {
            "me": {
                "name": person.name,
                "title": person.title,
                "department": dept.name if dept else None,
                "roles": sorted(
                    {m.role for m in authz.memberships(session, user.id, cid)}
                ),
            },
            "agent": {"id": agent.id, "name": agent.name, "status": cfg.status}
            if agent and cfg
            else None,
            "tools": tools,
            "team": {
                "department": dept.name if dept else None,
                "manager": {"name": manager.name, "role": manager.title or manager.role}
                if manager
                else None,
                "colleagues": colleagues,
            },
            "policies": policies,
            "company": {
                "name": company.name if company else None,
                "mission": meta.get("mission"),
                "vision": meta.get("vision"),
                "goals": meta.get("goals"),
                "department_goals": dept.goals if dept else None,
            },
        }
