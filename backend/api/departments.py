from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
import json

from api.audit import log_action
from api.auth import check_company_membership, get_current_user
from database import get_session
from models import CompanyMember, Department, DepartmentPolicyLink, Policy, User
from schemas import DepartmentCreate, DepartmentUpdate, PolicyLinkSet

router = APIRouter(prefix="/departments", tags=["departments"])


def dept_to_dict(d: Department, linked_policies: list = None, parent_name: Optional[str] = None) -> dict:
    policies = linked_policies or []
    return {
        "id": d.id,
        "company_id": d.company_id,
        "parent_id": d.parent_id,
        "parent_name": parent_name,
        "name": d.name,
        "slug": d.slug,
        "description": d.description,
        "goals": d.goals,
        "policy_ids": [p.id for p in policies],
        "policies": [p.name for p in policies],
        "status": d.status,
        "created_at": d.created_at.isoformat(),
    }


def _load_dept_policies_map(session, dept_ids: list[str]) -> dict[str, list]:
    """Returns {dept_id: [Policy, ...]} for all given dept IDs."""
    if not dept_ids:
        return {}
    rows = session.exec(
        select(DepartmentPolicyLink, Policy)
        .join(Policy, DepartmentPolicyLink.policy_id == Policy.id)
        .where(DepartmentPolicyLink.department_id.in_(dept_ids))
        .where(Policy.is_active == True)
    ).all()
    result: dict[str, list] = {}
    for link, policy in rows:
        result.setdefault(link.department_id, []).append(policy)
    return result


@router.get("")
def list_departments(company_id: Optional[str] = None,
                     current_user: User = Depends(get_current_user)):
    with get_session() as session:
        if company_id:
            check_company_membership(current_user.id, company_id, session)
            q = select(Department).where(Department.company_id == company_id)
        else:
            memberships = session.exec(
                select(CompanyMember).where(CompanyMember.user_id == current_user.id)
            ).all()
            user_company_ids = [m.company_id for m in memberships]
            q = select(Department).where(Department.company_id.in_(user_company_ids))
        depts = session.exec(q).all()
        name_map = {d.id: d.name for d in depts}
        policies_map = _load_dept_policies_map(session, [d.id for d in depts])
        return [
            dept_to_dict(d, policies_map.get(d.id, []), name_map.get(d.parent_id) if d.parent_id else None)
            for d in depts
        ]


@router.post("", status_code=201)
def create_department(body: DepartmentCreate, company_id: Optional[str] = None,
                      current_user: User = Depends(get_current_user)):
    with get_session() as session:
        if company_id:
            check_company_membership(current_user.id, company_id, session)
        parent_name = None
        if body.parent_id:
            parent = session.get(Department, body.parent_id)
            if not parent:
                raise HTTPException(status_code=404, detail="Parent department not found")
            parent_name = parent.name
        dept = Department(
            company_id=company_id,
            parent_id=body.parent_id,
            name=body.name,
            slug=body.slug,
            description=body.description,
            goals=body.goals,
            status=body.status,
        )
        session.add(dept)
        log_action(session, "create", "department", entity_id=dept.id, entity_name=dept.name,
                   company_id=dept.company_id or company_id)
        session.commit()
        session.refresh(dept)
        return dept_to_dict(dept, [], parent_name)


@router.get("/{dept_id}")
def get_department(dept_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        dept = session.get(Department, dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        if dept.company_id:
            check_company_membership(current_user.id, dept.company_id, session)
        parent_name = None
        if dept.parent_id:
            parent = session.get(Department, dept.parent_id)
            parent_name = parent.name if parent else None
        policies_map = _load_dept_policies_map(session, [dept_id])
        return dept_to_dict(dept, policies_map.get(dept_id, []), parent_name)


@router.patch("/{dept_id}")
def update_department(dept_id: str, body: DepartmentUpdate,
                      current_user: User = Depends(get_current_user)):
    with get_session() as session:
        dept = session.get(Department, dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        if dept.company_id:
            check_company_membership(current_user.id, dept.company_id, session)
        if body.name is not None:        dept.name = body.name
        if body.slug is not None:        dept.slug = body.slug
        if body.description is not None: dept.description = body.description
        if body.goals is not None:       dept.goals = body.goals
        if body.status is not None:      dept.status = body.status
        if "parent_id" in body.model_fields_set:
            if body.parent_id and body.parent_id == dept_id:
                raise HTTPException(status_code=400, detail="Department cannot be its own parent")
            dept.parent_id = body.parent_id
        session.add(dept)
        log_action(session, "update", "department", entity_id=dept.id, entity_name=dept.name,
                   company_id=dept.company_id)
        session.commit()
        session.refresh(dept)
        parent_name = None
        if dept.parent_id:
            parent = session.get(Department, dept.parent_id)
            parent_name = parent.name if parent else None
        policies_map = _load_dept_policies_map(session, [dept_id])
        return dept_to_dict(dept, policies_map.get(dept_id, []), parent_name)


@router.put("/{dept_id}/policies")
def set_department_policies(dept_id: str, body: PolicyLinkSet,
                            current_user: User = Depends(get_current_user)):
    """Replace the full set of linked policies for a department."""
    with get_session() as session:
        dept = session.get(Department, dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        if dept.company_id:
            check_company_membership(current_user.id, dept.company_id, session)
        # Remove existing links
        existing = session.exec(
            select(DepartmentPolicyLink).where(DepartmentPolicyLink.department_id == dept_id)
        ).all()
        for link in existing:
            session.delete(link)
        # Create new links
        for policy_id in body.policy_ids:
            session.add(DepartmentPolicyLink(department_id=dept_id, policy_id=policy_id))
        # Keep policies_json in sync for any legacy readers
        if body.policy_ids:
            names = [p.name for p in session.exec(
                select(Policy).where(Policy.id.in_(body.policy_ids))
            ).all()]
        else:
            names = []
        dept.policies_json = json.dumps(names, ensure_ascii=False)
        session.add(dept)
        log_action(session, "update", "department", entity_id=dept.id, entity_name=dept.name,
                   company_id=dept.company_id)
        session.commit()
        policies_map = _load_dept_policies_map(session, [dept_id])
        parent_name = None
        if dept.parent_id:
            parent = session.get(Department, dept.parent_id)
            parent_name = parent.name if parent else None
        return dept_to_dict(dept, policies_map.get(dept_id, []), parent_name)


@router.delete("/{dept_id}", status_code=204)
def delete_department(dept_id: str, current_user: User = Depends(get_current_user)):
    with get_session() as session:
        dept = session.get(Department, dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        if dept.company_id:
            check_company_membership(current_user.id, dept.company_id, session)
        children = session.exec(select(Department).where(Department.parent_id == dept_id)).all()
        for child in children:
            child.parent_id = None
            session.add(child)
        # Clean up policy links before delete
        existing = session.exec(
            select(DepartmentPolicyLink).where(DepartmentPolicyLink.department_id == dept_id)
        ).all()
        for link in existing:
            session.delete(link)
        log_action(session, "delete", "department", entity_id=dept.id, entity_name=dept.name,
                   company_id=dept.company_id)
        session.delete(dept)
        session.commit()


@router.get("/tree/root")
def get_department_tree(company_id: Optional[str] = None,
                        current_user: User = Depends(get_current_user)):
    with get_session() as session:
        if company_id:
            check_company_membership(current_user.id, company_id, session)
            q = select(Department).where(Department.company_id == company_id)
        else:
            memberships = session.exec(
                select(CompanyMember).where(CompanyMember.user_id == current_user.id)
            ).all()
            user_company_ids = [m.company_id for m in memberships]
            q = select(Department).where(Department.company_id.in_(user_company_ids))
        depts = session.exec(q).all()
        policies_map = _load_dept_policies_map(session, [d.id for d in depts])
        dept_map = {d.id: dept_to_dict(d, policies_map.get(d.id, [])) for d in depts}
        for d in dept_map.values():
            d["children"] = []
        roots = []
        for d in dept_map.values():
            if d["parent_id"] and d["parent_id"] in dept_map:
                dept_map[d["parent_id"]]["children"].append(d)
            else:
                roots.append(d)
        return roots
