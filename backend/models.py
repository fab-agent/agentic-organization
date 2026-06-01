from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional
import uuid
import json


class Department(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    slug: str
    description: Optional[str] = None
    goals: Optional[str] = None        # newline-separated goal strings
    policies_json: Optional[str] = None  # JSON array of policy name strings
    status: str = Field(default="Active")  # "Active" | "Inactive"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def policies(self) -> list[str]:
        if not self.policies_json:
            return []
        return json.loads(self.policies_json)


class Personnel(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    department_id: Optional[str] = Field(default=None, foreign_key="department.id")
    name: str
    slug: str
    title: Optional[str] = None
    role: Optional[str] = None
    type: str = Field(default="human")   # "human" | "agent"
    manager_id: Optional[str] = Field(default=None, foreign_key="personnel.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentConfig(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    personnel_id: str = Field(foreign_key="personnel.id", unique=True)
    model: str
    model_version: Optional[str] = None
    status: str = Field(default="draft")   # "active" | "draft" | "inactive"
    responsible_id: Optional[str] = Field(default=None, foreign_key="personnel.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Skill(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    agent_id: str = Field(foreign_key="agentconfig.id")
    name: str
    version: str
    description: Optional[str] = None
