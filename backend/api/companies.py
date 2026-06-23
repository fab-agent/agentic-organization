from fastapi import APIRouter, HTTPException
from sqlmodel import select, func

from api.audit import log_action
from database import get_session
from models import Company, Department, Personnel, AgentConfig
from schemas import CompanyCreate, CompanyUpdate

router = APIRouter(prefix="/companies", tags=["companies"])


def _company_to_dict(company: Company, session) -> dict:
    dept_count = session.exec(
        select(func.count()).where(Department.company_id == company.id)
    ).one()
    personnel_count = session.exec(
        select(func.count()).where(Personnel.company_id == company.id)
    ).one()
    agent_count = session.exec(
        select(func.count(AgentConfig.id))
        .join(Personnel, AgentConfig.personnel_id == Personnel.id)
        .where(Personnel.company_id == company.id)
    ).one()
    return {
        "id": company.id,
        "name": company.name,
        "slug": company.slug,
        "sector": company.sector,
        "website": company.website,
        "created_at": company.created_at.isoformat(),
        "stats": {
            "departments": dept_count,
            "personnel": personnel_count,
            "agents": agent_count,
        },
    }


@router.get("")
def list_companies():
    with get_session() as session:
        companies = session.exec(select(Company)).all()
        return [_company_to_dict(c, session) for c in companies]


@router.post("", status_code=201)
def create_company(body: CompanyCreate):
    with get_session() as session:
        company = Company(
            name=body.name,
            slug=body.slug,
            sector=body.sector,
            website=body.website,
        )
        session.add(company)
        log_action(session, "create", "company", entity_id=company.id, entity_name=company.name)
        session.commit()
        session.refresh(company)
        return _company_to_dict(company, session)


@router.get("/{company_id}")
def get_company(company_id: str):
    with get_session() as session:
        company = session.get(Company, company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        return _company_to_dict(company, session)


@router.patch("/{company_id}")
def update_company(company_id: str, body: CompanyUpdate):
    with get_session() as session:
        company = session.get(Company, company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        if body.name is not None:    company.name    = body.name
        if body.slug is not None:    company.slug    = body.slug
        if body.sector is not None:  company.sector  = body.sector
        if body.website is not None: company.website = body.website
        session.add(company)
        log_action(session, "update", "company", entity_id=company.id, entity_name=company.name)
        session.commit()
        session.refresh(company)
        return _company_to_dict(company, session)


@router.delete("/{company_id}", status_code=204)
def delete_company(company_id: str):
    with get_session() as session:
        company = session.get(Company, company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        log_action(session, "delete", "company", entity_id=company.id, entity_name=company.name)
        session.delete(company)
        session.commit()
