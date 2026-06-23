from typing import Optional
from fastapi import APIRouter, HTTPException
from sqlmodel import select
import json

from api.audit import log_action
from database import get_session
from models import Department
from schemas import DepartmentCreate, DepartmentUpdate

router = APIRouter(prefix="/departments", tags=["departments"])


def dept_to_dict(d: Department, parent_name: Optional[str] = None) -> dict:
    return {
        "id": d.id,
        "company_id": d.company_id,
        "parent_id": d.parent_id,
        "parent_name": parent_name,
        "name": d.name,
        "slug": d.slug,
        "description": d.description,
        "goals": d.goals,
        "policies": d.policies(),
        "status": d.status,
        "created_at": d.created_at.isoformat(),
    }


@router.get("")
def list_departments(company_id: Optional[str] = None):
    with get_session() as session:
        q = select(Department)
        if company_id:
            q = q.where(Department.company_id == company_id)
        depts = session.exec(q).all()
        # Build id→name map for parent lookup
        name_map = {d.id: d.name for d in depts}
        return [dept_to_dict(d, name_map.get(d.parent_id) if d.parent_id else None) for d in depts]


@router.post("", status_code=201)
def create_department(body: DepartmentCreate, company_id: Optional[str] = None):
    with get_session() as session:
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
            policies_json=json.dumps(body.policies),
            status=body.status,
        )
        session.add(dept)
        log_action(session, "create", "department", entity_id=dept.id, entity_name=dept.name, company_id=dept.company_id or company_id)
        session.commit()
        session.refresh(dept)
        return dept_to_dict(dept, parent_name)


@router.get("/{dept_id}")
def get_department(dept_id: str):
    with get_session() as session:
        dept = session.get(Department, dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        parent_name = None
        if dept.parent_id:
            parent = session.get(Department, dept.parent_id)
            parent_name = parent.name if parent else None
        return dept_to_dict(dept, parent_name)


@router.patch("/{dept_id}")
def update_department(dept_id: str, body: DepartmentUpdate):
    with get_session() as session:
        dept = session.get(Department, dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        if body.name is not None:        dept.name = body.name
        if body.slug is not None:        dept.slug = body.slug
        if body.description is not None: dept.description = body.description
        if body.goals is not None:       dept.goals = body.goals
        if body.policies is not None:    dept.policies_json = json.dumps(body.policies)
        if body.status is not None:      dept.status = body.status
        # parent_id can be set to null explicitly
        if "parent_id" in body.model_fields_set:
            if body.parent_id and body.parent_id == dept_id:
                raise HTTPException(status_code=400, detail="Department cannot be its own parent")
            dept.parent_id = body.parent_id
        session.add(dept)
        log_action(session, "update", "department", entity_id=dept.id, entity_name=dept.name, company_id=dept.company_id)
        session.commit()
        session.refresh(dept)
        parent_name = None
        if dept.parent_id:
            parent = session.get(Department, dept.parent_id)
            parent_name = parent.name if parent else None
        return dept_to_dict(dept, parent_name)


@router.delete("/{dept_id}", status_code=204)
def delete_department(dept_id: str):
    with get_session() as session:
        dept = session.get(Department, dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        # Clear parent_id on children before deleting
        children = session.exec(select(Department).where(Department.parent_id == dept_id)).all()
        for child in children:
            child.parent_id = None
            session.add(child)
        log_action(session, "delete", "department", entity_id=dept.id, entity_name=dept.name, company_id=dept.company_id)
        session.delete(dept)
        session.commit()


@router.get("/tree/root")
def get_department_tree(company_id: Optional[str] = None):
    """Returns departments as a nested tree structure."""
    with get_session() as session:
        q = select(Department)
        if company_id:
            q = q.where(Department.company_id == company_id)
        depts = session.exec(q).all()
        dept_map = {d.id: dept_to_dict(d) for d in depts}
        for d in dept_map.values():
            d["children"] = []
        roots = []
        for d in dept_map.values():
            if d["parent_id"] and d["parent_id"] in dept_map:
                dept_map[d["parent_id"]]["children"].append(d)
            else:
                roots.append(d)
        return roots
