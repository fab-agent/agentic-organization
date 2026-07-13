from datetime import datetime
from typing import Optional
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from api.auth import get_current_user, require_manager
from database import get_session
from models import AgentConfig, AgentSkillLink, ChangeRequest, CompanySkill, Personnel, User

router = APIRouter(tags=["skills"])

# ── Platform builtin tool registry ───────────────────────────────────────────
# Single source of truth for all tools the platform can execute natively.
# Frontend fetches this list instead of hardcoding it.
PLATFORM_BUILTIN_TOOLS = [
    {
        "value": "web_search",
        "label_tr": "Web Arama",
        "label_en": "Web Search",
        "description_tr": "DuckDuckGo ile internet araması yapar",
        "description_en": "Search the web using DuckDuckGo",
        "icon": "🔍",
    },
    {
        "value": "text_to_chart",
        "label_tr": "Grafik Üretimi",
        "label_en": "Chart Generation",
        "description_tr": "JSON/CSV verisinden grafik üretir",
        "description_en": "Generate a chart from JSON or CSV data",
        "icon": "📊",
    },
    {
        "value": "journal_write",
        "label_tr": "Günlük Yaz",
        "label_en": "Write Journal",
        "description_tr": "Oturum gününlüğüne markdown girişi ekler",
        "description_en": "Append a markdown entry to the session journal",
        "icon": "📝",
    },
    {
        "value": "delegate_to_agent",
        "label_tr": "Ajan Delegasyonu",
        "label_en": "Delegate to Agent",
        "description_tr": "Görevi başka bir ajana iletir (A2A)",
        "description_en": "Route a task to another agent (A2A)",
        "icon": "🤝",
    },
    {
        "value": "instagram_post",
        "label_tr": "Instagram Gönderi",
        "label_en": "Instagram Post",
        "description_tr": "Instagram Business hesabına gönderi paylaşır",
        "description_en": "Publish a post to an Instagram Business account",
        "icon": "📸",
    },
    {
        "value": "whatsapp_send",
        "label_tr": "WhatsApp Mesaj",
        "label_en": "WhatsApp Message",
        "description_tr": "WhatsApp Business API ile mesaj gönderir",
        "description_en": "Send a message via WhatsApp Business API",
        "icon": "💬",
    },
]


@router.get("/builtin-tools")
def list_builtin_tools(_: User = Depends(get_current_user)):
    """Return all platform-implemented builtin tools. Model-agnostic — any provider
    that supports function calling can use these tools."""
    return PLATFORM_BUILTIN_TOOLS


class SkillCreate(BaseModel):
    company_id: str
    name: str
    slug: str
    description: Optional[str] = None
    content: Optional[str] = None
    skill_type: str = "builtin"
    config_json: Optional[str] = None


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    skill_type: Optional[str] = None
    config_json: Optional[str] = None
    is_active: Optional[bool] = None


def _skill_dict(s: CompanySkill, assigned_agents: list[str] | None = None) -> dict:
    return {
        "id": s.id,
        "company_id": s.company_id,
        "name": s.name,
        "slug": s.slug,
        "description": s.description,
        "content": s.content,
        "skill_type": s.skill_type,
        "config_json": s.config_json,
        "is_active": s.is_active,
        "assigned_agents": assigned_agents or [],
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


@router.get("/company-skills")
def list_skills(company_id: Optional[str] = None, _: User = Depends(get_current_user)):
    with get_session() as session:
        q = select(CompanySkill)
        if company_id:
            q = q.where(CompanySkill.company_id == company_id)
        skills = session.exec(q.order_by(CompanySkill.name)).all()
        result = []
        for s in skills:
            links = session.exec(
                select(AgentSkillLink).where(AgentSkillLink.company_skill_id == s.id)
            ).all()
            result.append(_skill_dict(s, [l.agent_config_id for l in links]))
        return result


@router.post("/company-skills", status_code=201)
def create_skill(body: SkillCreate, user: User = Depends(require_manager)):
    with get_session() as session:
        skill = CompanySkill(
            company_id=body.company_id,
            name=body.name,
            slug=body.slug,
            description=body.description,
            content=body.content,
            skill_type=body.skill_type,
            config_json=body.config_json,
        )
        session.add(skill)
        session.commit()
        session.refresh(skill)
        return _skill_dict(skill)


@router.get("/company-skills/{skill_id}")
def get_skill(skill_id: str, _: User = Depends(get_current_user)):
    with get_session() as session:
        skill = session.get(CompanySkill, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        links = session.exec(
            select(AgentSkillLink).where(AgentSkillLink.company_skill_id == skill_id)
        ).all()
        return _skill_dict(skill, [l.agent_config_id for l in links])


@router.put("/company-skills/{skill_id}")
def update_skill(
    skill_id: str,
    body: SkillUpdate,
    propose: bool = False,
    personnel_id: Optional[str] = None,
    user: User = Depends(require_manager),
):
    """
    Direct update (managers+) or propose a change request.
    If propose=true, creates a CR instead of applying directly.
    """
    with get_session() as session:
        skill = session.get(CompanySkill, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")

        if propose and personnel_id:
            original = {
                "name": skill.name,
                "description": skill.description,
                "content": skill.content,
                "skill_type": skill.skill_type,
                "config_json": skill.config_json,
            }
            proposed = {k: v for k, v in body.model_dump().items() if v is not None}
            cr = ChangeRequest(
                company_id=skill.company_id,
                personnel_id=personnel_id,
                change_type="skill",
                title=f"Yetenek güncelleme: {skill.name}",
                proposed_json=json.dumps({"skill_id": skill_id, **proposed}),
                original_json=json.dumps(original),
                status="submitted",
            )
            session.add(cr)
            session.commit()
            session.refresh(cr)
            return {"change_request_id": cr.id, "status": "submitted"}

        for field, val in body.model_dump(exclude_none=True).items():
            setattr(skill, field, val)
        skill.updated_at = datetime.utcnow()
        session.add(skill)
        session.commit()
        session.refresh(skill)
        links = session.exec(
            select(AgentSkillLink).where(AgentSkillLink.company_skill_id == skill_id)
        ).all()
        return _skill_dict(skill, [l.agent_config_id for l in links])


@router.delete("/company-skills/{skill_id}", status_code=204)
def delete_skill(skill_id: str, _: User = Depends(require_manager)):
    with get_session() as session:
        skill = session.get(CompanySkill, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        links = session.exec(
            select(AgentSkillLink).where(AgentSkillLink.company_skill_id == skill_id)
        ).all()
        for link in links:
            session.delete(link)
        session.delete(skill)
        session.commit()


@router.post("/company-skills/{skill_id}/assign/{agent_config_id}", status_code=201)
def assign_skill(skill_id: str, agent_config_id: str, _: User = Depends(require_manager)):
    with get_session() as session:
        if not session.get(CompanySkill, skill_id):
            raise HTTPException(status_code=404, detail="Skill not found")
        if not session.get(AgentConfig, agent_config_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        existing = session.exec(
            select(AgentSkillLink)
            .where(AgentSkillLink.company_skill_id == skill_id)
            .where(AgentSkillLink.agent_config_id == agent_config_id)
        ).first()
        if existing:
            return {"status": "already_assigned"}
        link = AgentSkillLink(agent_config_id=agent_config_id, company_skill_id=skill_id)
        session.add(link)
        session.commit()
        return {"status": "assigned"}


@router.delete("/company-skills/{skill_id}/assign/{agent_config_id}", status_code=204)
def unassign_skill(skill_id: str, agent_config_id: str, _: User = Depends(require_manager)):
    with get_session() as session:
        link = session.exec(
            select(AgentSkillLink)
            .where(AgentSkillLink.company_skill_id == skill_id)
            .where(AgentSkillLink.agent_config_id == agent_config_id)
        ).first()
        if link:
            session.delete(link)
            session.commit()
