from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, create_engine, Session, select
import os
from datetime import datetime

from models import Organization, Personnel

app = FastAPI(
    title="3rdParty Agent Organization API",
    version="0.1.0",
    description="Self-hosted agentic organization management platform"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)
    print("✅ Database initialized")

@app.get("/")
def root():
    return {"message": "3rdParty Agent Organization API", "status": "ok"}

@app.get("/health")
def health():
    return {"status": "healthy"}

# Organization Endpoints
@app.post("/organizations")
def create_organization(name: str, slug: str, description: str = None):
    with Session(engine) as session:
        org = Organization(name=name, slug=slug, description=description)
        session.add(org)
        session.commit()
        session.refresh(org)
        return org

@app.get("/organizations")
def list_organizations():
    with Session(engine) as session:
        orgs = session.exec(select(Organization)).all()
        return orgs

@app.get("/organizations/{org_id}")
def get_organization(org_id: str):
    with Session(engine) as session:
        org = session.get(Organization, org_id)
        return org

# Personnel Endpoints
@app.post("/personnel")
def create_personnel(organization_id: str, name: str, slug: str, role: str):
    with Session(engine) as session:
        person = Personnel(
            organization_id=organization_id,
            name=name,
            slug=slug,
            role=role
        )
        session.add(person)
        session.commit()
        session.refresh(person)
        return person

@app.get("/organizations/{org_id}/personnel")
def list_personnel(org_id: str):
    with Session(engine) as session:
        personnel = session.exec(
            select(Personnel).where(Personnel.organization_id == org_id)
        ).all()
        return personnel

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)