import json as _json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from api.audit import log_action
from api.auth import check_company_membership, get_current_user
from database import get_session
from models import AgentConfig, AgentPolicyLink, AgentSkillLink, Company, CompanyMember, CompanySkill, Department, DepartmentPolicyLink, Personnel, Policy, Skill, User
from schemas import AgentConfigCreate, AgentConfigUpdate, PersonnelCreate, PersonnelUpdate, PolicyLinkSet, SkillCreate, SkillUpdate
from services.auth import generate_temp_password, hash_password
from services.email import send_invite

TEMP_PASSWORD_TTL_MINUTES = 30

router = APIRouter(tags=["personnel"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _skill_to_dict(s: Skill) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "version": s.version,
        "description": s.description,
        "skill_type": s.skill_type,
        "config": _json.loads(s.config_json) if s.config_json else None,
        "is_active": s.is_active,
    }


def _personnel_to_dict(p: Personnel, session) -> dict:
    dept = session.get(Department, p.department_id) if p.department_id else None
    manager = session.get(Personnel, p.manager_id) if p.manager_id else None
    cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == p.id)).first()

    result = {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "title": p.title,
        "role": p.role,
        "type": p.type,
        "email": p.email,
        "user_id": p.user_id,
        "has_user": bool(p.user_id),
        "department_id": p.department_id,
        "department_name": dept.name if dept else None,
        "manager_id": p.manager_id,
        "manager_name": manager.name if manager else None,
        "created_at": p.created_at.isoformat(),
    }

    if cfg:
        responsible = session.get(Personnel, cfg.responsible_id) if cfg.responsible_id else None
        skills = session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all()
        # Also include CompanySkill records linked via AgentSkillLink
        linked = session.exec(
            select(AgentSkillLink, CompanySkill)
            .join(CompanySkill, AgentSkillLink.company_skill_id == CompanySkill.id)
            .where(AgentSkillLink.agent_config_id == cfg.id)
        ).all()
        company_skills = [
            {"id": cs.id, "name": cs.name, "slug": cs.slug, "description": cs.description}
            for _, cs in linked
        ]
        # Agent-specific policy links
        agent_policy_rows = session.exec(
            select(AgentPolicyLink, Policy)
            .join(Policy, AgentPolicyLink.policy_id == Policy.id)
            .where(AgentPolicyLink.agent_config_id == cfg.id)
            .where(Policy.is_active == True)
        ).all()
        agent_policy_ids = [p.id for _, p in agent_policy_rows]
        result["agent_config"] = {
            "id": cfg.id,
            "model": cfg.model,
            "model_version": cfg.model_version,
            "status": cfg.status,
            "responsible_id": cfg.responsible_id,
            "responsible_name": responsible.name if responsible else None,
            "skills": [_skill_to_dict(s) for s in skills],
            "company_skills": company_skills,
            "agent_policy_ids": agent_policy_ids,
        }

    return result


def _get_person_and_check_membership(person_id: str, user_id: str, session) -> Personnel:
    """Fetch personnel and verify caller is a member of the person's company."""
    person = session.get(Personnel, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Personnel not found")
    if person.company_id:
        check_company_membership(user_id, person.company_id, session)
    return person


# ── Personnel CRUD ─────────────────────────────────────────────────────────────

@router.get("/personnel")
def list_personnel(current_user: User = Depends(get_current_user),
                   department_id: Optional[str] = None,
                   type: Optional[str] = None,
                   company_id: Optional[str] = None):
    with get_session() as session:
        if company_id:
            check_company_membership(current_user.id, company_id, session)
            q = select(Personnel).where(Personnel.company_id == company_id)
        else:
            memberships = session.exec(
                select(CompanyMember).where(CompanyMember.user_id == current_user.id)
            ).all()
            user_company_ids = [m.company_id for m in memberships]
            q = select(Personnel).where(Personnel.company_id.in_(user_company_ids))
        if department_id:
            q = q.where(Personnel.department_id == department_id)
        if type:
            q = q.where(Personnel.type == type)
        people = session.exec(q).all()
        return [_personnel_to_dict(p, session) for p in people]


@router.post("/personnel", status_code=201)
def create_personnel(body: PersonnelCreate, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        if body.company_id:
            check_company_membership(current_user.id, body.company_id, session)
        person = Personnel(
            name=body.name,
            slug=body.slug,
            title=body.title,
            role=body.role,
            type=body.type,
            company_id=body.company_id,
            department_id=body.department_id,
            manager_id=body.manager_id,
        )
        session.add(person)
        log_action(session, "create", "personnel", entity_id=person.id,
                   entity_name=person.name, company_id=person.company_id)
        session.commit()
        session.refresh(person)
        return _personnel_to_dict(person, session)


@router.get("/personnel/{person_id}")
def get_personnel(person_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        person = _get_person_and_check_membership(person_id, current_user.id, session)
        return _personnel_to_dict(person, session)


@router.patch("/personnel/{person_id}")
def update_personnel(person_id: str, body: PersonnelUpdate,
                     current_user: User = Depends(get_current_user)):
    with get_session() as session:
        person = _get_person_and_check_membership(person_id, current_user.id, session)
        if body.name is not None:          person.name = body.name
        if body.slug is not None:          person.slug = body.slug
        if body.title is not None:         person.title = body.title
        if body.role is not None:          person.role = body.role
        if body.type is not None:          person.type = body.type
        if body.department_id is not None: person.department_id = body.department_id
        if body.manager_id is not None:    person.manager_id = body.manager_id
        if body.email is not None:         person.email = body.email or None
        session.add(person)
        log_action(session, "update", "personnel", entity_id=person.id,
                   entity_name=person.name, company_id=person.company_id)
        session.commit()
        session.refresh(person)
        return _personnel_to_dict(person, session)


@router.post("/personnel/{person_id}/invite", status_code=201)
def invite_personnel(person_id: str, body: dict,
                     current_user: User = Depends(get_current_user)):
    role: str = body.get("role", "user")
    scope_id: Optional[str] = body.get("scope_id")

    with get_session() as session:
        person = _get_person_and_check_membership(person_id, current_user.id, session)
        if not person.email:
            raise HTTPException(status_code=422, detail="Bu personelin e-posta adresi yok")
        if person.type != "human":
            raise HTTPException(status_code=422, detail="Sadece insan personele davet gönderilebilir")

        company = session.get(Company, person.company_id) if person.company_id else None
        if not company:
            raise HTTPException(status_code=404, detail="Şirket bulunamadı")

        existing = session.exec(select(User).where(User.email == person.email)).first()
        user = existing or User(email=person.email, name=person.name)
        if not existing:
            session.add(user)
            session.flush()

        temp_pw = generate_temp_password()
        user.password_hash = hash_password(temp_pw)
        user.must_change_password = True
        user.invite_expires_at = datetime.utcnow() + timedelta(minutes=TEMP_PASSWORD_TTL_MINUTES)
        user.invite_token = None
        user.reset_token = None
        user.reset_expires_at = None
        session.add(user)

        existing_member = session.exec(
            select(CompanyMember).where(
                CompanyMember.user_id == user.id,
                CompanyMember.company_id == company.id,
            )
        ).first()
        if existing_member:
            existing_member.role = role
            existing_member.scope_id = scope_id
            session.add(existing_member)
        else:
            session.add(CompanyMember(
                user_id=user.id,
                company_id=company.id,
                role=role,
                scope_id=scope_id,
            ))

        person.user_id = user.id
        session.add(person)
        session.commit()
        user_id = user.id

    send_invite(to=person.email, name=person.name, company_name=company.name, temp_password=temp_pw)
    return {"message": "Davet emaili gönderildi", "user_id": user_id}


@router.delete("/personnel/{person_id}", status_code=204)
def delete_personnel(person_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        person = _get_person_and_check_membership(person_id, current_user.id, session)
        log_action(session, "delete", "personnel", entity_id=person.id,
                   entity_name=person.name, company_id=person.company_id)
        session.delete(person)
        session.commit()


# ── Agent Config ───────────────────────────────────────────────────────────────

@router.get("/personnel/{person_id}/agent-config")
def get_agent_config(person_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        _get_person_and_check_membership(person_id, current_user.id, session)
        cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == person_id)).first()
        if not cfg:
            raise HTTPException(status_code=404, detail="Agent config not found")
        skills = session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all()
        return {
            "id": cfg.id,
            "personnel_id": cfg.personnel_id,
            "model": cfg.model,
            "model_version": cfg.model_version,
            "status": cfg.status,
            "responsible_id": cfg.responsible_id,
            "skills": [
                {"id": s.id, "name": s.name, "version": s.version, "description": s.description}
                for s in skills
            ],
            "created_at": cfg.created_at.isoformat(),
            "updated_at": cfg.updated_at.isoformat(),
        }


@router.post("/personnel/{person_id}/agent-config", status_code=201)
def create_agent_config(person_id: str, body: AgentConfigCreate,
                        current_user: User = Depends(get_current_user)):
    with get_session() as session:
        person = _get_person_and_check_membership(person_id, current_user.id, session)
        existing = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == person_id)).first()
        if existing:
            raise HTTPException(status_code=409, detail="Agent config already exists")
        cfg = AgentConfig(
            personnel_id=person_id,
            model=body.model,
            model_version=body.model_version,
            status=body.status,
            responsible_id=body.responsible_id,
        )
        session.add(cfg)
        person.type = "agent"
        session.add(person)
        log_action(session, "create", "agent_config", entity_id=cfg.id,
                   entity_name=person.name, company_id=person.company_id)
        session.commit()
        session.refresh(cfg)
        return {
            "id": cfg.id,
            "personnel_id": cfg.personnel_id,
            "model": cfg.model,
            "model_version": cfg.model_version,
            "status": cfg.status,
            "responsible_id": cfg.responsible_id,
            "skills": [],
        }


@router.patch("/personnel/{person_id}/agent-config")
def update_agent_config(person_id: str, body: AgentConfigUpdate,
                        current_user: User = Depends(get_current_user)):
    with get_session() as session:
        _get_person_and_check_membership(person_id, current_user.id, session)
        cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == person_id)).first()
        if not cfg:
            raise HTTPException(status_code=404, detail="Agent config not found")
        if body.model is not None:          cfg.model = body.model
        if body.model_version is not None:  cfg.model_version = body.model_version
        if body.status is not None:         cfg.status = body.status
        if body.responsible_id is not None: cfg.responsible_id = body.responsible_id
        cfg.updated_at = datetime.utcnow()
        session.add(cfg)
        log_action(session, "update", "agent_config", entity_id=cfg.id, entity_name=cfg.personnel_id)
        session.commit()
        session.refresh(cfg)
        skills = session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all()
        return {
            "id": cfg.id,
            "model": cfg.model,
            "model_version": cfg.model_version,
            "status": cfg.status,
            "responsible_id": cfg.responsible_id,
            "skills": [
                {"id": s.id, "name": s.name, "version": s.version, "description": s.description}
                for s in skills
            ],
        }


# ── Skills ────────────────────────────────────────────────────────────────────

@router.get("/personnel/{person_id}/skills")
def list_skills(person_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        _get_person_and_check_membership(person_id, current_user.id, session)
        cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == person_id)).first()
        if not cfg:
            raise HTTPException(status_code=404, detail="Agent config not found")
        skills = session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all()
        return [_skill_to_dict(s) for s in skills]


@router.post("/personnel/{person_id}/skills", status_code=201)
def add_skill(person_id: str, body: SkillCreate, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        _get_person_and_check_membership(person_id, current_user.id, session)
        cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == person_id)).first()
        if not cfg:
            raise HTTPException(status_code=404, detail="Agent config not found")
        skill = Skill(
            agent_id=cfg.id,
            name=body.name,
            version=body.version,
            description=body.description,
            skill_type=body.skill_type,
            config_json=_json.dumps(body.config) if body.config else None,
            is_active=body.is_active,
        )
        session.add(skill)
        log_action(session, "create", "skill", entity_id=skill.id, entity_name=skill.name)
        session.commit()
        session.refresh(skill)
        return _skill_to_dict(skill)


@router.patch("/personnel/{person_id}/skills/{skill_id}")
def update_skill(person_id: str, skill_id: str, body: SkillUpdate,
                 current_user: User = Depends(get_current_user)):
    with get_session() as session:
        _get_person_and_check_membership(person_id, current_user.id, session)
        skill = session.get(Skill, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        if body.name is not None:        skill.name = body.name
        if body.version is not None:     skill.version = body.version
        if body.description is not None: skill.description = body.description
        if body.skill_type is not None:  skill.skill_type = body.skill_type
        if body.config is not None:      skill.config_json = _json.dumps(body.config)
        if body.is_active is not None:   skill.is_active = body.is_active
        session.add(skill)
        log_action(session, "update", "skill", entity_id=skill.id, entity_name=skill.name)
        session.commit()
        session.refresh(skill)
        return _skill_to_dict(skill)


@router.delete("/personnel/{person_id}/skills/{skill_id}", status_code=204)
def delete_skill(person_id: str, skill_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        _get_person_and_check_membership(person_id, current_user.id, session)
        skill = session.get(Skill, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        log_action(session, "delete", "skill", entity_id=skill.id, entity_name=skill.name)
        session.delete(skill)
        session.commit()


# ── Agent Policy Links ────────────────────────────────────────────────────────

@router.put("/personnel/{person_id}/agent-policies")
def set_agent_policies(person_id: str, body: PolicyLinkSet,
                       current_user: User = Depends(get_current_user)):
    """Replace the full set of agent-specific policy links for a personnel's agent config."""
    with get_session() as session:
        person = _get_person_and_check_membership(person_id, current_user.id, session)
        cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == person_id)).first()
        if not cfg:
            raise HTTPException(status_code=404, detail="Agent config not found")
        existing = session.exec(
            select(AgentPolicyLink).where(AgentPolicyLink.agent_config_id == cfg.id)
        ).all()
        for link in existing:
            session.delete(link)
        for policy_id in body.policy_ids:
            session.add(AgentPolicyLink(agent_config_id=cfg.id, policy_id=policy_id))
        log_action(session, "update", "agent_config", entity_id=cfg.id, entity_name=person.name)
        session.commit()
        return {"ok": True, "policy_ids": body.policy_ids}


# ── Org Tree ──────────────────────────────────────────────────────────────────

@router.get("/org-tree")
def get_org_tree(company_id: Optional[str] = None,
                 current_user: User = Depends(get_current_user)):
    with get_session() as session:
        if company_id:
            check_company_membership(current_user.id, company_id, session)
            q = select(Personnel).where(Personnel.company_id == company_id)
        else:
            memberships = session.exec(
                select(CompanyMember).where(CompanyMember.user_id == current_user.id)
            ).all()
            user_company_ids = [m.company_id for m in memberships]
            q = select(Personnel).where(Personnel.company_id.in_(user_company_ids))

        all_personnel = session.exec(q).all()
        all_configs   = session.exec(select(AgentConfig)).all()
        all_skills    = session.exec(select(Skill)).all()
        all_depts     = session.exec(select(Department)).all()
        # Load CompanySkill links for the agent detail panel
        linked_rows = session.exec(
            select(AgentSkillLink, CompanySkill)
            .join(CompanySkill, AgentSkillLink.company_skill_id == CompanySkill.id)
        ).all()
        # Load department policy links
        dept_policy_rows = session.exec(
            select(DepartmentPolicyLink, Policy)
            .join(Policy, DepartmentPolicyLink.policy_id == Policy.id)
            .where(Policy.is_active == True)
        ).all()
        # Load agent-specific policy links
        agent_policy_rows = session.exec(
            select(AgentPolicyLink, Policy)
            .join(Policy, AgentPolicyLink.policy_id == Policy.id)
            .where(Policy.is_active == True)
        ).all()

        dept_map = {d.id: d for d in all_depts}
        cfg_map  = {c.personnel_id: c for c in all_configs}
        skills_by_agent: dict[str, list] = {}
        for s in all_skills:
            skills_by_agent.setdefault(s.agent_id, []).append(
                {"name": s.name, "version": s.version, "description": s.description}
            )
        # Index CompanySkill by agent_config_id
        company_skills_by_cfg: dict[str, list] = {}
        for link, cs in linked_rows:
            company_skills_by_cfg.setdefault(link.agent_config_id, []).append(
                {"id": cs.id, "name": cs.name, "slug": cs.slug, "description": cs.description}
            )
        # Index dept policies by dept_id → [{id, name}]
        dept_policies_by_id: dict[str, list] = {}
        for link, policy in dept_policy_rows:
            dept_policies_by_id.setdefault(link.department_id, []).append(
                {"id": policy.id, "name": policy.name}
            )
        # Index agent policies by cfg_id → [{id, name}]
        agent_policies_by_cfg: dict[str, list] = {}
        for link, policy in agent_policy_rows:
            agent_policies_by_cfg.setdefault(link.agent_config_id, []).append(
                {"id": policy.id, "name": policy.name}
            )

        def build_node(p: Personnel) -> dict:
            cfg = cfg_map.get(p.id)
            responsible_name = None
            if cfg and cfg.responsible_id:
                r = next((x for x in all_personnel if x.id == cfg.responsible_id), None)
                responsible_name = r.name if r else None

            dept = dept_map.get(p.department_id) if p.department_id else None
            node: dict = {
                "id": p.id,
                "name": p.name,
                "title": p.title or p.role or "",
                "type": p.type,
                "department": dept.name if dept else None,
                "children": [],
            }
            if cfg:
                node["model"]            = cfg.model
                node["modelVersion"]     = cfg.model_version
                node["agentStatus"]      = cfg.status
                node["responsibleHuman"] = responsible_name
                # Prefer CompanySkill links; fall back to legacy per-agent Skill records
                cs_list = company_skills_by_cfg.get(cfg.id, [])
                node["skills"]           = cs_list if cs_list else skills_by_agent.get(cfg.id, [])
                node["company_skills"]   = cs_list
                # Policies from join tables
                dept_pols = dept_policies_by_id.get(dept.id, []) if dept else []
                agent_pols = agent_policies_by_cfg.get(cfg.id, [])
                node["dept_policies"]  = dept_pols    # [{id, name}] — inherited, not editable
                node["agent_policies"] = agent_pols   # [{id, name}] — agent-specific
                node["policies"]       = [p["name"] for p in dept_pols] + [p["name"] for p in agent_pols]

            return node

        nodes = {p.id: build_node(p) for p in all_personnel}

        roots: list[dict] = []
        for p in all_personnel:
            node = nodes[p.id]
            if p.manager_id and p.manager_id in nodes:
                nodes[p.manager_id]["children"].append(node)
            else:
                roots.append(node)

        return roots
