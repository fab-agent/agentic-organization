"""Assemble an agent's system prompt from sections, with a token budget and a
per-section report (ADR-0020).

Why sections: the prompt used to be one string built inline, so nobody could say
where its tokens went. Every part is now a named `Section` with a tier and a token
estimate, so growth is visible and bounded, and a caller (later: an intent
classifier) can leave sections out.

Ordering is deliberate: text that is identical from one turn to the next comes
first, per-turn text (memory, retrieved knowledge) last, so providers' prompt
caching can reuse the long stable prefix.

Tiers: 0 = always, tiny; 1 = stable (company / department / job / rules);
2 = varies per turn (memory, knowledge).

This is guidance for the model, not enforcement: policies are enforced at tool-call
time by the policy engine (ADR-0005), so leaving something out of a prompt can make
the agent less helpful but never less safe.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

from sqlmodel import select

from database import get_session
from models import AgentConfig, Company, Department, Personnel, Skill

# When the budget is exceeded, optional sections go in this order (largest, most
# per-turn first). Sections not listed here, and `required` ones, are never dropped.
DROP_ORDER = ("knowledge", "memory", "department", "job", "company")

_DEFAULT_BUDGET = 2000  # tokens; a starting value to tune from real reports


def estimate_tokens(text: str) -> int:
    """Rough token count (no tokenizer is installed): ~4 characters per token for
    mostly-ASCII text, ~3 when accented characters are common (e.g. Turkish).
    Good for comparing sections and spotting growth, not for billing."""
    if not text:
        return 0
    non_ascii = sum(1 for c in text if ord(c) > 127)
    per_token = 3.0 if non_ascii / len(text) > 0.05 else 4.0
    return math.ceil(len(text) / per_token)


def clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class Section:
    name: str
    text: str
    tier: int
    required: bool = False
    tokens: int = field(default=0, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tokens", estimate_tokens(self.text))


@dataclass
class Assembled:
    sections: list[Section]
    dropped: list[Section]
    budget: int

    @property
    def total_tokens(self) -> int:
        return sum(s.tokens for s in self.sections)

    def text(self) -> str:
        return "\n".join(s.text for s in self.sections)

    def report(self) -> dict:
        """Names and sizes only — never the text (it can contain private memory)."""
        return {
            "method": "estimate",
            "budget": self.budget,
            "total_tokens": self.total_tokens,
            "over_budget": self.total_tokens > self.budget,
            "sections": [
                {"name": s.name, "tier": s.tier, "tokens": s.tokens}
                for s in self.sections
            ],
            "dropped": [{"name": s.name, "tokens": s.tokens} for s in self.dropped],
        }


def _budget() -> int:
    try:
        return max(1, int(os.getenv("PROMPT_BUDGET_TOKENS", _DEFAULT_BUDGET)))
    except ValueError:
        return _DEFAULT_BUDGET


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [ln.strip() for ln in value.splitlines() if ln.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


def company_text(session, company_id: str | None) -> str | None:
    """Mission, vision, values and top goals from the company's stored metadata,
    compacted with hard caps (no model call)."""
    if not company_id:
        return None
    co = session.get(Company, company_id)
    if not co:
        return None
    try:
        meta = json.loads(co.metadata_json) if co.metadata_json else {}
    except ValueError:
        meta = {}
    lines = [f"Company: {co.name}"]
    if meta.get("mission"):
        lines.append(f"Mission: {clip(meta['mission'], 240)}")
    if meta.get("vision"):
        lines.append(f"Vision: {clip(meta['vision'], 240)}")
    values = _as_list(meta.get("values"))
    if values:
        lines.append("Values: " + ", ".join(clip(v, 40) for v in values[:8]))
    goals = _as_list(meta.get("goals"))
    if goals:
        lines.append("Company goals:")
        lines.extend(f"  - {clip(g, 160)}" for g in goals[:5])
    return "\n".join(lines) if len(lines) > 1 else None


def owner_job_text(session, person: Personnel) -> str | None:
    """For a workspace agent: who it works for and what their job is (ADR-0019 §3)."""
    cfg = session.exec(
        select(AgentConfig).where(AgentConfig.personnel_id == person.id)
    ).first()
    if not cfg or not cfg.is_workspace_agent or not cfg.responsible_id:
        return None
    owner = session.get(Personnel, cfg.responsible_id)
    if not owner:
        return None
    head = f"You work for {owner.name}" + (f", {owner.title}" if owner.title else "")
    if owner.job_description:
        return f"{head}.\nTheir work: {clip(owner.job_description, 600)}"
    return f"{head}." if owner.title else None


def _skills_text(skills: list[Skill]) -> str | None:
    import json as _json

    active = [s for s in skills if s.is_active]
    if not active:
        return None
    delegate = [
        s
        for s in active
        if s.skill_type == "builtin"
        and s.config_json
        and _json.loads(s.config_json).get("function_name") == "delegate_to_agent"
    ]
    if not delegate:
        return "\nAvailable tools/skills: " + ", ".join(s.name for s in active)
    lines = [
        "\nYou are an orchestrator agent. When given a task, you MUST call your "
        "delegation tools to assign sub-tasks to specialist agents — do NOT just "
        "describe what you would do.",
        "Delegation tools available (call these):",
    ]
    lines += [f"  - {s.name}: {s.description or s.name}" for s in delegate]
    other = [s for s in active if s not in delegate]
    if other:
        lines.append("Other tools: " + ", ".join(s.name for s in other))
    return "\n".join(lines)


def assemble(
    person: Personnel,
    dept: Department | None,
    skills: list[Skill],
    policy_names: list[str] | None = None,
    *,
    memories: list[str] | None = None,
    knowledge: list[dict] | None = None,
    company_id: str | None = None,
    skip: frozenset[str] | set[str] = frozenset(),
    budget: int | None = None,
) -> Assembled:
    """Build the sections, apply `skip`, then enforce the budget.

    `skip` names sections to leave out (an intent classifier will fill this in);
    required sections (`identity`, `rules`, `closing`) are never skipped or dropped.
    """
    budget = budget or _budget()
    secs: list[Section] = []

    ident = [f"You are {person.name}."]
    if person.title:
        ident.append(f"Title: {person.title}")
    if person.role:
        ident.append(f"Role: {person.role}")
    secs.append(Section("identity", "\n".join(ident), 0, required=True))

    with get_session() as session:
        ctext = company_text(session, company_id)
        jtext = owner_job_text(session, person)
    if ctext:
        secs.append(Section("company", "\n" + ctext, 1))
    if dept:
        d = [f"Department: {dept.name}"]
        if dept.goals:
            d.append("\nDepartment Goals:\n" + "\n".join(_as_list(dept.goals)[:6]))
        secs.append(Section("department", "\n".join(d), 1))
    if jtext:
        secs.append(Section("job", "\n" + jtext, 1))
    if policy_names:
        names = policy_names[:20]
        lines = ["\nPolicies you must follow:"] + [f"  - {p}" for p in names]
        if len(policy_names) > len(names):
            lines.append(f"  (+{len(policy_names) - len(names)} more apply)")
        secs.append(Section("rules", "\n".join(lines), 1, required=True))
    stext = _skills_text(skills)
    if stext:
        secs.append(Section("skills", stext, 1))
    secs.append(
        Section(
            "closing",
            "\nRespond helpfully and concisely. Use tools when they would help.",
            0,
            required=True,
        )
    )
    # Per-turn text last, after everything that is identical between turns.
    if memories:
        mem = ["\nContext from your previous sessions:"] + [
            f"  - {m}" for m in memories
        ]
        secs.append(Section("memory", "\n".join(mem), 2))
    if knowledge:
        kn = ["\n--- Relevant knowledge from past work ---"]
        for hit in knowledge:
            date = hit["created_at"][:10]
            source = hit["source_type"].replace("_", " ")
            snippet = hit["chunk_text"][:300].replace("\n", " ")
            kn.append(f"[{date}] ({source}) {snippet}")
        kn.append("--- End of relevant knowledge ---")
        secs.append(Section("knowledge", "\n".join(kn), 2))

    dropped = [s for s in secs if s.name in skip and not s.required]
    kept = [s for s in secs if s not in dropped]
    for name in DROP_ORDER:
        if sum(s.tokens for s in kept) <= budget:
            break
        for s in [s for s in kept if s.name == name and not s.required]:
            kept.remove(s)
            dropped.append(s)
    return Assembled(sections=kept, dropped=dropped, budget=budget)
