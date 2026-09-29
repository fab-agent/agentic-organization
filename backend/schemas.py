from pydantic import BaseModel, field_validator

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
    scope_id: str | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


# ── Company ────────────────────────────────────────────────────────────────────


class CompanyCreate(BaseModel):
    name: str
    slug: str
    sector: str | None = None
    website: str | None = None


class CompanyUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    sector: str | None = None
    website: str | None = None
    vision: str | None = None
    mission: str | None = None
    values: list[str] | None = None
    goals: list[dict] | None = None


# ── Department ─────────────────────────────────────────────────────────────────


class DepartmentCreate(BaseModel):
    name: str
    slug: str
    parent_id: str | None = None
    description: str | None = None
    goals: str | None = None
    policies: list[str] = []
    status: str = "Active"

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("Active", "Inactive"):
            raise ValueError("status must be 'Active' or 'Inactive'")
        return v


class DepartmentUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    parent_id: str | None = None
    description: str | None = None
    goals: str | None = None
    policies: list[str] | None = None
    status: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("Active", "Inactive"):
            raise ValueError("status must be 'Active' or 'Inactive'")
        return v


# ── Personnel ──────────────────────────────────────────────────────────────────


class PersonnelCreate(BaseModel):
    name: str
    slug: str
    title: str | None = None
    role: str | None = None
    type: str = "human"
    email: str | None = None
    company_id: str | None = None
    department_id: str | None = None
    manager_id: str | None = None
    job_description: str | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("human", "agent"):
            raise ValueError("type must be 'human' or 'agent'")
        return v


class PersonnelUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    title: str | None = None
    role: str | None = None
    type: str | None = None
    email: str | None = None
    department_id: str | None = None
    manager_id: str | None = None
    job_description: str | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("human", "agent"):
            raise ValueError("type must be 'human' or 'agent'")
        return v


# ── AgentConfig ────────────────────────────────────────────────────────────────


class AgentConfigCreate(BaseModel):
    model: str
    model_version: str | None = None
    # ProviderKey.provider serving `model` ("openai", "ollama", "custom:vllm", …);
    # None = infer from the model name.
    provider: str | None = None
    status: str = "draft"
    responsible_id: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("active", "draft", "inactive"):
            raise ValueError("status must be 'active', 'draft', or 'inactive'")
        return v


class AgentConfigUpdate(BaseModel):
    model: str | None = None
    model_version: str | None = None
    # Sending "provider": null (or "") clears it back to name-based inference.
    provider: str | None = None
    status: str | None = None
    responsible_id: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("active", "draft", "inactive"):
            raise ValueError("status must be 'active', 'draft', or 'inactive'")
        return v


# ── Skill ──────────────────────────────────────────────────────────────────────

SKILL_TYPES = ("builtin", "mcp", "http", "function")


class McpConfig(BaseModel):
    """Config for skill_type='mcp'"""

    transport: str = "sse"  # sse | stdio | http
    url: str  # MCP server URL
    auth_type: str = "none"  # none | api_key | bearer | oauth2
    auth_value: str | None = None  # stored encrypted in config_json


class HttpConfig(BaseModel):
    """Config for skill_type='http'"""

    url: str
    method: str = "POST"
    headers: dict[str, str] = {}
    input_schema: dict | None = None


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
    description: str | None = None
    skill_type: str = "builtin"
    config: dict | None = None  # typed per skill_type, stored as config_json
    is_active: bool = True

    @field_validator("skill_type")
    @classmethod
    def validate_skill_type(cls, v: str) -> str:
        if v not in SKILL_TYPES:
            raise ValueError(f"skill_type must be one of {SKILL_TYPES}")
        return v


class SkillUpdate(BaseModel):
    name: str | None = None
    version: str | None = None
    description: str | None = None
    skill_type: str | None = None
    config: dict | None = None
    is_active: bool | None = None


# ── Provider ───────────────────────────────────────────────────────────────────


class SetProviderKey(BaseModel):
    key: str
    base_url: str | None = None


class CustomEndpointCreate(BaseModel):
    """An OpenAI-compatible endpoint added by base URL + token (ADR-0016)."""

    name: str
    base_url: str
    api_key: str | None = None
    # Model ids to use when the server does not implement GET /models.
    models: list[str] | None = None


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
    branch: str | None = None
    token: str | None = None
    sync_interval: int | None = None
    auto_pr: bool | None = None


class PushRequest(BaseModel):
    message: str = ""


# ── Sessions ───────────────────────────────────────────────────────────────────


class SessionCreate(BaseModel):
    personnel_id: str
    title: str | None = None


class Attachment(BaseModel):
    type: str  # "pdf" | "image"
    filename: str
    content: str  # extracted text for PDF, base64 data URI for image
    mime_type: str | None = None


class MessageCreate(BaseModel):
    content: str
    attachments: list[Attachment] | None = None


# ── Policy links ───────────────────────────────────────────────────────────────


class PolicyLinkSet(BaseModel):
    policy_ids: list[str]


# ── Change Request ─────────────────────────────────────────────────────────────


class ChangeRequestCreate(BaseModel):
    personnel_id: str
    change_type: str  # "agent_config" | "skill" | "policy"
    title: str
    proposed: dict  # will be JSON-serialized
    original: dict | None = None


class ChangeRequestApprove(BaseModel):
    note: str | None = None


class ChangeRequestReject(BaseModel):
    note: str | None = None


# ── A2A ────────────────────────────────────────────────────────────────────────


class A2ARequestCreate(BaseModel):
    from_session_id: str | None = None
    from_agent_id: str
    to_agent_id: str
    task: str
    context: str | None = None


class A2AApprove(BaseModel):
    approver_id: str


class A2AReject(BaseModel):
    approver_id: str
    reason: str | None = None


class A2AResultApprove(BaseModel):
    approver_id: str
