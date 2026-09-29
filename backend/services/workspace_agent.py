"""The one agent persona every person gets with their workspace (ADR-0019 §1).

It is a normal agent `Personnel` + `AgentConfig`, so token minting, the policy
engine, gateway quotas and audit attribution all keep working unchanged. What
makes it "the workspace agent" is `AgentConfig.is_workspace_agent`, unique per
responsible human at the database level.

Authority: the agent sits in its owner's department and reports to them, so it
resolves the same company + department policies the owner is bound by; it can
only gain restrictions on top (agent-scope policies), never lose any (ADR-0019 §3).
"""

from __future__ import annotations

import os

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from models import AgentConfig, AppConfig, Personnel

FALLBACK_MODEL = "gpt-4o-mini"


def agent_model(session, company_id: str) -> str:
    """Model for a new workspace agent: `workspace.agent_model[:<company>]` in
    AppConfig, else `WORKSPACE_AGENT_MODEL`, else a conservative default."""
    for key in (f"workspace.agent_model:{company_id}", "workspace.agent_model"):
        row = session.get(AppConfig, key)
        if row and row.value:
            return row.value
    return os.getenv("WORKSPACE_AGENT_MODEL", "").strip() or FALLBACK_MODEL


def find_workspace_agent(session, personnel_id: str) -> Personnel | None:
    return session.exec(
        select(Personnel)
        .join(AgentConfig, AgentConfig.personnel_id == Personnel.id)
        .where(AgentConfig.responsible_id == personnel_id)
        .where(AgentConfig.is_workspace_agent == True)  # noqa: E712
    ).first()


def _unique_slug(session, company_id: str, base: str) -> str:
    taken = {
        s
        for s in session.exec(
            select(Personnel.slug).where(Personnel.company_id == company_id)
        ).all()
    }
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def ensure_workspace_agent(session, person: Personnel) -> Personnel:
    """Return the person's workspace agent, creating it if needed (idempotent).

    Also re-syncs the agent's department to its owner's, so a transfer never
    leaves the agent under the old department's policies.
    """
    agent = find_workspace_agent(session, person.id)
    if agent is None:
        try:
            # A savepoint: losing a creation race must not roll back the caller's work.
            with session.begin_nested():
                agent = Personnel(
                    company_id=person.company_id,
                    department_id=person.department_id,
                    name=f"{person.name} — Agent",
                    slug=_unique_slug(
                        session, person.company_id, f"{person.slug}-agent"
                    ),
                    title="Workspace Agent",
                    type="agent",
                    manager_id=person.id,
                )
                session.add(agent)
                session.flush()
                session.add(
                    AgentConfig(
                        personnel_id=agent.id,
                        model=agent_model(session, person.company_id),
                        status="active",
                        responsible_id=person.id,
                        is_workspace_agent=True,
                    )
                )
                session.flush()
        except IntegrityError:
            agent = find_workspace_agent(session, person.id)
            if agent is None:
                raise
    if agent.department_id != person.department_id:
        agent.department_id = person.department_id
        session.add(agent)
    return agent
