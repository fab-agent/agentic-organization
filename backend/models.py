from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional
import uuid
import json


class Company(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    slug: str
    sector: Optional[str] = None
    website: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Department(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: Optional[str] = Field(default=None, foreign_key="company.id")
    parent_id: Optional[str] = Field(default=None, foreign_key="department.id")
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
    company_id: Optional[str] = Field(default=None, foreign_key="company.id")
    department_id: Optional[str] = Field(default=None, foreign_key="department.id")
    name: str
    slug: str
    title: Optional[str] = None
    role: Optional[str] = None
    type: str = Field(default="human")   # "human" | "agent"
    email: Optional[str] = None
    user_id: Optional[str] = None        # linked User.id (no FK — soft link)
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
    # F6A: executable skill fields
    skill_type: str = Field(default="builtin")   # builtin | mcp | http | function
    config_json: Optional[str] = None            # JSON — type-specific connection config
    is_active: bool = Field(default=True)


class AppConfig(SQLModel, table=True):
    """Platform-wide key-value settings (company name, setup state, etc.)."""
    key: str = Field(primary_key=True)
    value: str


class ProviderKey(SQLModel, table=True):
    """AES-256 encrypted API key per AI provider."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    provider: str = Field(unique=True)          # "anthropic" | "openai" | "google" | "mistral"
    encrypted_key: str
    status: str = Field(default="unconfigured") # "active" | "invalid" | "unconfigured"
    last_tested: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GitConfig(SQLModel, table=True):
    """Per-company git repository connection settings."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: Optional[str] = Field(default=None, foreign_key="company.id", index=True)
    provider: str                        # "github" | "gitlab" | "gitea"
    repo_url: str                        # https://github.com/owner/repo
    branch: str = Field(default="main")
    encrypted_token: str
    sync_interval: int = Field(default=30)  # minutes — used by scheduler (F6)
    auto_pr: bool = Field(default=False)    # create PR instead of direct push
    last_synced: Optional[datetime] = None
    last_commit_sha: Optional[str] = None
    status: str = Field(default="connected")  # "connected" | "error" | "disconnected"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SyncLog(SQLModel, table=True):
    """Record of every pull/push sync operation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    direction: str                       # "pull" | "push"
    files_changed: int = Field(default=0)
    commit_sha: Optional[str] = None
    pr_url: Optional[str] = None
    status: str                          # "success" | "error" | "no_changes"
    message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentSession(SQLModel, table=True):
    """A chat session between a human user and an agent."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    personnel_id: str = Field(foreign_key="personnel.id")
    title: Optional[str] = None
    status: str = Field(default="active")   # "active" | "closed"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SessionMessage(SQLModel, table=True):
    """Single message within an agent session."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="agentsession.id")
    role: str                            # "user" | "assistant"
    content: str                         # text content
    tool_calls_json: Optional[str] = None   # JSON array of tool calls made
    tool_results_json: Optional[str] = None # JSON array of tool results received
    tokens_used: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Auth & User ───────────────────────────────────────────────────────────────

class User(SQLModel, table=True):
    """Platform user — separate from Personnel (org chart)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    email: str = Field(unique=True, index=True)
    name: str
    password_hash: Optional[str] = None       # null until invite accepted
    is_active: bool = Field(default=True)
    # Invite flow
    invite_token: Optional[str] = None
    invite_expires_at: Optional[datetime] = None
    must_change_password: bool = Field(default=False)
    # Password reset
    reset_token: Optional[str] = None
    reset_expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = None


class CompanyMember(SQLModel, table=True):
    """Maps a User to a Company with a role and optional scope (dept/agent)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    # founder | executive | dept_head | agent_owner | user
    role: str = Field(default="user")
    # For executive/dept_head: department_id they manage (null = entire company)
    # For agent_owner: personnel_id of the agent they own
    scope_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Change Request ────────────────────────────────────────────────────────────

class ChangeRequest(SQLModel, table=True):
    """A proposed edit to an agent's config/skills/policy requiring two-stage approval."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    personnel_id: str = Field(foreign_key="personnel.id")   # the agent being changed
    # What is being changed: "agent_config" | "skill" | "policy"
    change_type: str
    # Human-readable title
    title: str
    # JSON snapshot of proposed values (what will be committed to GitHub)
    proposed_json: str
    # Original values before change (for diff display)
    original_json: Optional[str] = None
    # Status lifecycle:
    # draft → submitted → dept_head_approved → admin_approved → committed → rejected
    status: str = Field(default="submitted")
    # Stage 1: dept_head approval
    dept_head_id: Optional[str] = Field(default=None, foreign_key="personnel.id")
    dept_head_approved_at: Optional[datetime] = None
    dept_head_rejected_at: Optional[datetime] = None
    dept_head_note: Optional[str] = None
    # Stage 2: admin (founder/executive) approval
    admin_id: Optional[str] = Field(default=None, foreign_key="user.id")
    admin_approved_at: Optional[datetime] = None
    admin_rejected_at: Optional[datetime] = None
    admin_note: Optional[str] = None
    # GitHub commit result
    commit_sha: Optional[str] = None
    commit_url: Optional[str] = None
    # Who created the CR
    created_by_user_id: Optional[str] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── A2A ───────────────────────────────────────────────────────────────────────

class A2ARequest(SQLModel, table=True):
    """Agent-to-Agent delegation request with two-stage human approval."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    from_session_id: Optional[str] = Field(default=None, foreign_key="agentsession.id")
    from_agent_id: str = Field(foreign_key="personnel.id")   # requesting agent
    to_agent_id: str = Field(foreign_key="personnel.id")     # target agent
    task: str                            # task description for target agent
    context: Optional[str] = None        # additional context / attached data
    # Status lifecycle: pending_approval → approved → running → pending_result_approval → completed | rejected
    status: str = Field(default="pending_approval")
    result: Optional[str] = None         # final result from target agent
    # Approver = responsible human of the TARGET agent
    approver_id: Optional[str] = Field(default=None, foreign_key="personnel.id")
    approved_at: Optional[datetime] = None
    result_approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Inbox ─────────────────────────────────────────────────────────────────────

class InboxMessage(SQLModel, table=True):
    """A message delivered to a user's inbox (from flows, task results, or system)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    recipient_user_id: str = Field(foreign_key="user.id", index=True)
    # Source: "flow" | "task_request" | "task_result" | "system"
    source_type: str
    source_id: Optional[str] = None          # flow_run_id or task_request_id
    title: str
    body: str                                 # markdown content
    read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Autonomous Flows ──────────────────────────────────────────────────────────

class Flow(SQLModel, table=True):
    """Scheduled autonomous flow — cron-triggered agent task."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    personnel_id: str = Field(foreign_key="personnel.id")   # the agent to run
    name: str
    description: Optional[str] = None
    schedule: str                             # cron expression e.g. "0 9 * * *"
    prompt: str                               # task prompt sent to the agent
    enabled: bool = Field(default=True)
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None     # "success" | "error"
    last_run_output: Optional[str] = None     # truncated output
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Task Request ──────────────────────────────────────────────────────────────

class TaskRequest(SQLModel, table=True):
    """A user-submitted task routed to the nearest matching agent."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    requester_user_id: str = Field(foreign_key="user.id")
    # Routing
    department_id: Optional[str] = Field(default=None, foreign_key="department.id")
    skill_filter: Optional[str] = None        # skill name to match
    # Assigned agent and their responsible human
    assigned_agent_id: Optional[str] = Field(default=None, foreign_key="personnel.id")
    responsible_user_id: Optional[str] = Field(default=None, foreign_key="user.id")
    title: str
    body: str
    # Responsible human's comment before triggering
    human_note: Optional[str] = None
    # Status: pending → assigned → running → completed | rejected
    status: str = Field(default="pending")
    result: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLog(SQLModel, table=True):
    """Immutable record of every significant platform action."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: Optional[str] = Field(default=None, foreign_key="company.id", index=True)
    user_id: Optional[str] = Field(default=None, foreign_key="user.id", index=True)
    action: str          # "create" | "update" | "delete" | "approve" | "reject" | "test" | "sync"
    entity_type: str     # "department" | "personnel" | "agent_config" | "skill" | "flow" | "change_request" | "provider_key" | "git_config"
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    details_json: Optional[str] = None  # JSON with relevant before/after or context
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Agent Memory ──────────────────────────────────────────────────────────────

class AgentMemory(SQLModel, table=True):
    """LLM-generated summary of a closed session, used as long-term agent memory."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    personnel_id: str = Field(foreign_key="personnel.id", index=True)
    session_id: Optional[str] = Field(default=None, foreign_key="agentsession.id")
    summary: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkJournalEntry(SQLModel, table=True):
    """Agent-authored or human-authored work log entry."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    personnel_id: str = Field(foreign_key="personnel.id", index=True)
    session_id: Optional[str] = Field(default=None, foreign_key="agentsession.id")
    # author: "agent" | "human"
    author: str = Field(default="agent")
    title: Optional[str] = None
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DatabaseConnection(SQLModel, table=True):
    """External database connection with semantic annotations."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: Optional[str] = Field(default=None, foreign_key="company.id", index=True)
    name: str                          # Human-friendly label
    db_type: str                       # "sqlite" | "postgresql" | "mysql"
    # Connection string encrypted (e.g. postgresql://user:pass@host/db)
    encrypted_dsn: str
    # JSON: {tables: {table_name: {description, columns: {col: description}, row_count}}}
    schema_json: Optional[str] = None
    # JSON: [{sql, description}] — user-provided example queries
    examples_json: Optional[str] = None
    status: str = Field(default="unchecked")  # "ok" | "error" | "unchecked"
    last_checked: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
