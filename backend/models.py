import json
import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel


class Company(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str
    slug: str
    sector: str | None = None
    website: str | None = None
    ai_onboarded: bool = Field(default=False)
    metadata_json: str | None = None  # JSON: {vision, mission, values, goals}
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Department(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str | None = Field(default=None, foreign_key="company.id")
    parent_id: str | None = Field(default=None, foreign_key="department.id")
    name: str
    slug: str
    description: str | None = None
    goals: str | None = None  # newline-separated goal strings
    policies_json: str | None = None  # JSON array of policy name strings
    status: str = Field(default="Active")  # "Active" | "Inactive"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def policies(self) -> list[str]:
        if not self.policies_json:
            return []
        return json.loads(self.policies_json)


class Personnel(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str | None = Field(default=None, foreign_key="company.id")
    department_id: str | None = Field(default=None, foreign_key="department.id")
    name: str
    slug: str
    title: str | None = None
    role: str | None = None
    type: str = Field(default="human")  # "human" | "agent"
    email: str | None = None
    user_id: str | None = None  # linked User.id (no FK — soft link)
    manager_id: str | None = Field(default=None, foreign_key="personnel.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentConfig(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    personnel_id: str = Field(foreign_key="personnel.id", unique=True)
    model: str
    model_version: str | None = None
    status: str = Field(default="draft")  # "active" | "draft" | "inactive"
    responsible_id: str | None = Field(default=None, foreign_key="personnel.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Skill(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    agent_id: str = Field(foreign_key="agentconfig.id")
    name: str
    version: str
    description: str | None = None
    # F6A: executable skill fields
    skill_type: str = Field(default="builtin")  # builtin | mcp | http | function
    config_json: str | None = None  # JSON — type-specific connection config
    is_active: bool = Field(default=True)


class AppConfig(SQLModel, table=True):
    """Platform-wide key-value settings (company name, setup state, etc.)."""

    key: str = Field(primary_key=True)
    value: str


class ProviderKey(SQLModel, table=True):
    """AES-256 encrypted API key per AI provider."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    provider: str = Field(unique=True)  # "anthropic" | "openai" | "google" | "mistral"
    encrypted_key: str
    status: str = Field(default="unconfigured")  # "active" | "invalid" | "unconfigured"
    base_url: str | None = None  # override endpoint (e.g. dashscope-intl vs dashscope)
    last_tested: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GitConfig(SQLModel, table=True):
    """Per-company git repository connection settings."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str | None = Field(default=None, foreign_key="company.id", index=True)
    provider: str  # "github" | "gitlab" | "gitea"
    repo_url: str  # https://github.com/owner/repo
    branch: str = Field(default="main")
    encrypted_token: str
    sync_interval: int = Field(default=30)  # minutes — used by scheduler (F6)
    auto_pr: bool = Field(default=False)  # create PR instead of direct push
    last_synced: datetime | None = None
    last_commit_sha: str | None = None
    status: str = Field(default="connected")  # "connected" | "error" | "disconnected"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TelegramConfig(SQLModel, table=True):
    """Per-company Telegram bot configuration for notifications."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str | None = Field(default=None, foreign_key="company.id", index=True)
    encrypted_token: str  # Bot token from BotFather (AES encrypted)
    admin_chat_id: str  # Chat/group ID where system alerts are sent
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SyncLog(SQLModel, table=True):
    """Record of every pull/push sync operation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    direction: str  # "pull" | "push"
    files_changed: int = Field(default=0)
    commit_sha: str | None = None
    pr_url: str | None = None
    status: str  # "success" | "error" | "no_changes"
    message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentSession(SQLModel, table=True):
    """A chat session between a human user and an agent."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    personnel_id: str = Field(foreign_key="personnel.id")
    title: str | None = None
    status: str = Field(default="active")  # "active" | "closed"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SessionMessage(SQLModel, table=True):
    """Single message within an agent session."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="agentsession.id")
    role: str  # "user" | "assistant"
    content: str  # text content
    tool_calls_json: str | None = None  # JSON array of tool calls made
    tool_results_json: str | None = None  # JSON array of tool results received
    tokens_used: int | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Auth & User ───────────────────────────────────────────────────────────────


class User(SQLModel, table=True):
    """Platform user — separate from Personnel (org chart)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    email: str = Field(unique=True, index=True)
    name: str
    password_hash: str | None = None  # null until invite accepted
    is_active: bool = Field(default=True)
    # Invite flow
    invite_token: str | None = None
    invite_expires_at: datetime | None = None
    must_change_password: bool = Field(default=False)
    # Password reset
    reset_token: str | None = None
    reset_expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: datetime | None = None


class CompanyMember(SQLModel, table=True):
    """Maps a User to a Company with a role and optional scope (dept/agent)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    # founder | executive | dept_head | agent_owner | user
    role: str = Field(default="user")
    # For executive/dept_head: department_id they manage (null = entire company)
    # For agent_owner: personnel_id of the agent they own
    scope_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Change Request ────────────────────────────────────────────────────────────


class ChangeRequest(SQLModel, table=True):
    """A proposed edit to an agent's config/skills/policy requiring two-stage approval."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    personnel_id: str = Field(foreign_key="personnel.id")  # the agent being changed
    # What is being changed: "agent_config" | "skill" | "policy"
    change_type: str
    # Human-readable title
    title: str
    # JSON snapshot of proposed values (what will be committed to GitHub)
    proposed_json: str
    # Original values before change (for diff display)
    original_json: str | None = None
    # Status lifecycle:
    # draft → submitted → dept_head_approved → admin_approved → committed → rejected
    status: str = Field(default="submitted")
    # Stage 1: dept_head approval
    dept_head_id: str | None = Field(default=None, foreign_key="personnel.id")
    dept_head_approved_at: datetime | None = None
    dept_head_rejected_at: datetime | None = None
    dept_head_note: str | None = None
    # Stage 2: admin (founder/executive) approval
    admin_id: str | None = Field(default=None, foreign_key="user.id")
    admin_approved_at: datetime | None = None
    admin_rejected_at: datetime | None = None
    admin_note: str | None = None
    # GitHub commit result
    commit_sha: str | None = None
    commit_url: str | None = None
    # Who created the CR
    created_by_user_id: str | None = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── A2A ───────────────────────────────────────────────────────────────────────


class A2ARequest(SQLModel, table=True):
    """Agent-to-Agent delegation request with two-stage human approval."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    from_session_id: str | None = Field(default=None, foreign_key="agentsession.id")
    from_agent_id: str = Field(foreign_key="personnel.id")  # requesting agent
    to_agent_id: str = Field(foreign_key="personnel.id")  # target agent
    task: str  # task description for target agent
    context: str | None = None  # additional context / attached data
    # Status lifecycle: pending_approval → approved → running → pending_result_approval → completed | rejected
    status: str = Field(default="pending_approval")
    result: str | None = None  # final result from target agent
    # Approver = responsible human of the TARGET agent
    approver_id: str | None = Field(default=None, foreign_key="personnel.id")
    approved_at: datetime | None = None
    result_approved_at: datetime | None = None
    rejection_reason: str | None = None
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
    source_id: str | None = None  # flow_run_id or task_request_id
    title: str
    body: str  # markdown content
    read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Autonomous Flows ──────────────────────────────────────────────────────────


class Flow(SQLModel, table=True):
    """Scheduled autonomous flow — cron-triggered agent task."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    personnel_id: str = Field(foreign_key="personnel.id")  # the agent to run
    name: str
    description: str | None = None
    schedule: str  # cron expression e.g. "0 9 * * *"
    prompt: str  # task prompt sent to the agent
    enabled: bool = Field(default=True)
    last_run_at: datetime | None = None
    last_run_status: str | None = None  # "success" | "error"
    last_run_output: str | None = None  # truncated output
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Task Request ──────────────────────────────────────────────────────────────


class TaskRequest(SQLModel, table=True):
    """A user-submitted task routed to the nearest matching agent."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    requester_user_id: str = Field(foreign_key="user.id")
    # Routing
    department_id: str | None = Field(default=None, foreign_key="department.id")
    skill_filter: str | None = None  # skill name to match
    # Assigned agent and their responsible human
    assigned_agent_id: str | None = Field(default=None, foreign_key="personnel.id")
    responsible_user_id: str | None = Field(default=None, foreign_key="user.id")
    title: str
    body: str
    # Responsible human's comment before triggering
    human_note: str | None = None
    # Status: pending → assigned → running → completed | rejected
    status: str = Field(default="pending")
    result: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Audit Log ─────────────────────────────────────────────────────────────────


class AuditEvent(SQLModel, table=True):
    """
    Hash-chained, append-only audit record (ADR-0006). Tamper-evident: each row
    carries `prev_hash` and a `hash` over its canonical body (incl. `chain_key`
    and `seq`), so deletion or modification of any row breaks its chain from that
    point on, and rows cannot be moved between chains.

    One chain per tenant: `chain_key` is the company id, or "__global__" for
    events with no company. `seq` is monotonic *within a chain*, assigned by
    `services.audit_chain.append()`. Agent and human actions are the same record
    type (the buzz pattern).
    """

    chain_key: str = Field(primary_key=True)
    seq: int = Field(primary_key=True)
    prev_hash: str
    hash: str = Field(index=True)
    actor_type: str  # "human" | "agent" | "system"
    actor_id: str | None = Field(default=None, index=True)
    company_id: str | None = Field(default=None, index=True)
    action: str
    target: str | None = None
    reason: str | None = None
    payload_json: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLog(SQLModel, table=True):
    """Immutable record of every significant platform action."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str | None = Field(default=None, foreign_key="company.id", index=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    action: (
        str  # "create" | "update" | "delete" | "approve" | "reject" | "test" | "sync"
    )
    entity_type: str  # "department" | "personnel" | "agent_config" | "skill" | "flow" | "change_request" | "provider_key" | "git_config"
    entity_id: str | None = None
    entity_name: str | None = None
    details_json: str | None = None  # JSON with relevant before/after or context
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Agent Memory ──────────────────────────────────────────────────────────────


class AgentMemory(SQLModel, table=True):
    """LLM-generated summary of a closed session, used as long-term agent memory."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    personnel_id: str = Field(foreign_key="personnel.id", index=True)
    session_id: str | None = Field(default=None, foreign_key="agentsession.id")
    summary: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkJournalEntry(SQLModel, table=True):
    """Agent-authored or human-authored work log entry."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    personnel_id: str = Field(foreign_key="personnel.id", index=True)
    session_id: str | None = Field(default=None, foreign_key="agentsession.id")
    # author: "agent" | "human"
    author: str = Field(default="agent")
    title: str | None = None
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CompanySkill(SQLModel, table=True):
    """Company-level skill library — assignable to multiple agents."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    name: str
    slug: str
    description: str | None = None
    content: str | None = None  # markdown — what this skill does, how to use it
    skill_type: str = Field(
        default="builtin"
    )  # builtin | mcp | http | function | database
    config_json: str | None = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentSkillLink(SQLModel, table=True):
    """Junction: which CompanySkills are active for which AgentConfig."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    agent_config_id: str = Field(foreign_key="agentconfig.id", index=True)
    company_skill_id: str = Field(foreign_key="companyskill.id", index=True)


class DepartmentPolicyLink(SQLModel, table=True):
    """Many-to-many: which Policy records apply to a Department."""

    department_id: str = Field(foreign_key="department.id", primary_key=True)
    policy_id: str = Field(foreign_key="policy.id", primary_key=True)


class AgentPolicyLink(SQLModel, table=True):
    """Many-to-many: agent-specific Policy records (beyond dept inheritance)."""

    agent_config_id: str = Field(foreign_key="agentconfig.id", primary_key=True)
    policy_id: str = Field(foreign_key="policy.id", primary_key=True)


class Policy(SQLModel, table=True):
    """Markdown policy document — scoped to company, department, or agent."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    department_id: str | None = Field(default=None, foreign_key="department.id")
    agent_config_id: str | None = Field(default=None, foreign_key="agentconfig.id")
    name: str
    slug: str
    content: str = Field(default="")  # full markdown body
    # scope: "company" | "department" | "agent"
    scope: str = Field(default="company")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PolicyConfig(SQLModel, table=True):
    """
    Policy Engine enforcement settings, scoped like everything else in the org
    (ADR-0005). Resolution is most-specific-wins:
    agent → department → company → global AppConfig → hardcoded default.
    A null field means "inherit from the next level up".
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True)
    # "company" | "department" | "agent"
    scope: str = Field(default="company")
    # department.id or agentconfig.id; null for company scope
    scope_id: str | None = Field(default=None, index=True)
    mode: str | None = None  # "off" | "dry_run" | "enforce"
    default_effect: str | None = None  # "allow" | "ask" | "deny"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DatabaseConnection(SQLModel, table=True):
    """External database connection with semantic annotations."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str | None = Field(default=None, foreign_key="company.id", index=True)
    name: str  # Human-friendly label
    db_type: str  # "sqlite" | "postgresql" | "mysql"
    # Connection string encrypted (e.g. postgresql://user:pass@host/db)
    encrypted_dsn: str
    # JSON: {tables: {table_name: {description, columns: {col: description}, row_count}}}
    schema_json: str | None = None
    # JSON: [{sql, description}] — user-provided example queries
    examples_json: str | None = None
    status: str = Field(default="unchecked")  # "ok" | "error" | "unchecked"
    last_checked: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DemoOtp(SQLModel, table=True):
    """6-digit OTP for passwordless demo tenant login."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    email: str = Field(index=True)
    code: str
    expires_at: datetime
    used: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OnboardingSession(SQLModel, table=True):
    """Persists AI onboarding progress so power/connection loss doesn't reset everything."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="company.id", index=True, unique=True)
    phase: str = Field(default="search")  # search | chat | preview | done
    search_context: str | None = None  # raw DDG result text
    messages_json: str | None = None  # JSON list of {role, content}
    structure_json: str | None = None  # JSON org structure
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TelegramBotState(SQLModel, table=True):
    """Per-chat state for the Telegram bot: selected agent, active session."""

    chat_id: str = Field(primary_key=True)
    user_id: str | None = None  # Platform User.id if linked
    company_id: str | None = None  # Active company
    selected_agent_id: str | None = None  # Personnel.id of chosen agent
    selected_agent_name: str | None = None
    active_session_id: str | None = None  # AgentSession.id (persists history)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
