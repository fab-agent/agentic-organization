from pydantic import BaseModel, field_validator
from typing import Optional


# ── Auth ────────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class SetupRequest(BaseModel):
    name: str
    email: str
    password: str
    company_name: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Şifre en az 8 karakter olmalı")
        return v


class ChangePasswordRequest(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("En az 8 karakterli şifre gerekli")
        return v


class InviteRequest(BaseModel):
    email: str
    name: str
    company_id: str
    role: str = "user"
    scope_id: Optional[str] = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


# ── Company ────────────────────────────────────────────────────────────────────

class CompanyCreate(BaseModel):
    name: str
    slug: str
    sector: Optional[str] = None
    website: Optional[str] = None


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    sector: Optional[str] = None
    website: Optional[str] = None


# ── Department ─────────────────────────────────────────────────────────────────

class DepartmentCreate(BaseModel):
    name: str
    slug: str
    parent_id: Optional[str] = None
    description: Optional[str] = None
    goals: Optional[str] = None
    policies: list[str] = []
    status: str = "Active"

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("Active", "Inactive"):
            raise ValueError("status must be 'Active' or 'Inactive'")
        return v


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    parent_id: Optional[str] = None
    description: Optional[str] = None
    goals: Optional[str] = None
    policies: Optional[list[str]] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("Active", "Inactive"):
            raise ValueError("status must be 'Active' or 'Inactive'")
        return v


# ── Personnel ──────────────────────────────────────────────────────────────────

class PersonnelCreate(BaseModel):
    name: str
    slug: str
    title: Optional[str] = None
    role: Optional[str] = None
    type: str = "human"
    email: Optional[str] = None
    company_id: Optional[str] = None
    department_id: Optional[str] = None
    manager_id: Optional[str] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("human", "agent"):
            raise ValueError("type must be 'human' or 'agent'")
        return v


class PersonnelUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    title: Optional[str] = None
    role: Optional[str] = None
    type: Optional[str] = None
    email: Optional[str] = None
    department_id: Optional[str] = None
    manager_id: Optional[str] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("human", "agent"):
            raise ValueError("type must be 'human' or 'agent'")
        return v


# ── AgentConfig ────────────────────────────────────────────────────────────────

class AgentConfigCreate(BaseModel):
    model: str
    model_version: Optional[str] = None
    status: str = "draft"
    responsible_id: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("active", "draft", "inactive"):
            raise ValueError("status must be 'active', 'draft', or 'inactive'")
        return v


class AgentConfigUpdate(BaseModel):
    model: Optional[str] = None
    model_version: Optional[str] = None
    status: Optional[str] = None
    responsible_id: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("active", "draft", "inactive"):
            raise ValueError("status must be 'active', 'draft', or 'inactive'")
        return v


# ── Skill ──────────────────────────────────────────────────────────────────────

SKILL_TYPES = ("builtin", "mcp", "http", "function")

class McpConfig(BaseModel):
    """Config for skill_type='mcp'"""
    transport: str = "sse"           # sse | stdio | http
    url: str                          # MCP server URL
    auth_type: str = "none"          # none | api_key | bearer | oauth2
    auth_value: Optional[str] = None  # stored encrypted in config_json

class HttpConfig(BaseModel):
    """Config for skill_type='http'"""
    url: str
    method: str = "POST"
    headers: dict[str, str] = {}
    input_schema: Optional[dict] = None

class BuiltinConfig(BaseModel):
    """Config for skill_type='builtin'"""
    function_name: str  # web_search | code_execution | file_read | text_to_chart

class FunctionConfig(BaseModel):
    """Config for skill_type='function'"""
    language: str = "python"
    code: str

class SkillCreate(BaseModel):
    name: str
    version: str
    description: Optional[str] = None
    skill_type: str = "builtin"
    config: Optional[dict] = None    # typed per skill_type, stored as config_json
    is_active: bool = True

    @field_validator("skill_type")
    @classmethod
    def validate_skill_type(cls, v: str) -> str:
        if v not in SKILL_TYPES:
            raise ValueError(f"skill_type must be one of {SKILL_TYPES}")
        return v

class SkillUpdate(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    skill_type: Optional[str] = None
    config: Optional[dict] = None
    is_active: Optional[bool] = None


# ── Provider ───────────────────────────────────────────────────────────────────

class SetProviderKey(BaseModel):
    key: str


class ConfigPatch(BaseModel):
    data: dict[str, str]


# ── Git ────────────────────────────────────────────────────────────────────────

class GitConfigCreate(BaseModel):
    provider: str
    repo_url: str
    branch: str = "main"
    token: str
    sync_interval: int = 30
    auto_pr: bool = False

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        if v not in ("github", "gitlab", "gitea"):
            raise ValueError("provider must be 'github', 'gitlab', or 'gitea'")
        return v


class GitConfigUpdate(BaseModel):
    branch: Optional[str] = None
    token: Optional[str] = None
    sync_interval: Optional[int] = None
    auto_pr: Optional[bool] = None


class PushRequest(BaseModel):
    message: str = ""


# ── Sessions ───────────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    personnel_id: str
    title: Optional[str] = None


class MessageCreate(BaseModel):
    content: str


# ── Change Request ─────────────────────────────────────────────────────────────

class ChangeRequestCreate(BaseModel):
    personnel_id: str
    change_type: str     # "agent_config" | "skill" | "policy"
    title: str
    proposed: dict       # will be JSON-serialized
    original: Optional[dict] = None


class ChangeRequestApprove(BaseModel):
    note: Optional[str] = None


class ChangeRequestReject(BaseModel):
    note: Optional[str] = None


# ── A2A ────────────────────────────────────────────────────────────────────────

class A2ARequestCreate(BaseModel):
    from_session_id: Optional[str] = None
    from_agent_id: str
    to_agent_id: str
    task: str
    context: Optional[str] = None


class A2AApprove(BaseModel):
    approver_id: str


class A2AReject(BaseModel):
    approver_id: str
    reason: Optional[str] = None


class A2AResultApprove(BaseModel):
    approver_id: str
