"""Learned harness artifacts (ADR-0022 §2): typed, approved, versioned.

What a change request of type `harness` may carry is an allowlist, enforced here:

* kinds: prompt text, memory entry, tool *guidance*, skill *instructions*;
* never: policy rules or precedence, tool ACLs, identity/token scopes, egress,
  approval gates, data-sharing limits, executable code. The proposal model forbids
  unknown fields, and content that looks like a credential is refused;
* the proposal names its base version and a content hash; approval binds to both, so
  if the base moved or the content changed it is rejected (fail closed) and must be
  proposed again;
* evidence is a list of references (kind + id), never text.

Activation is the approval itself (the two-stage change-request path); the row is
immutable afterwards. A new version supersedes the active one atomically, and
rollback writes a new version that restores the previous content. Each prompt
assembly reports the artifact versions it used.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import select, update

from models import HarnessArtifact, Personnel
from services.redact import redact

KINDS = ("prompt_text", "memory_entry", "tool_guidance", "skill_instructions")
LEVELS = ("person", "department", "company")
MAX_CONTENT = 4000
_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")

# Rendering order and headings in the assembled prompt.
_HEADINGS = {
    "prompt_text": "Guidance learned from your team",
    "memory_entry": "Things to remember",
    "tool_guidance": "How to use your tools",
    "skill_instructions": "Skill instructions",
}


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["correction", "thumbs", "contest", "review"]
    ref: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")


class HarnessProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["person", "department", "company"]
    target_id: str = Field(min_length=1, max_length=64)
    kind: Literal["prompt_text", "memory_entry", "tool_guidance", "skill_instructions"]
    key: str = "main"
    content: str = Field(min_length=1, max_length=MAX_CONTENT)
    base_version: int = Field(ge=0)
    content_hash: str
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_proposal(proposed: dict) -> HarnessProposal:
    """Strictly typed, or a 422 naming the first problem (never the content)."""
    try:
        p = HarnessProposal.model_validate(proposed)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first["loc"])
        raise HTTPException(
            status_code=422, detail=f"harness proposal: {loc}: {first['type']}"
        )
    if not _KEY.fullmatch(p.key):
        raise HTTPException(status_code=422, detail="harness proposal: key")
    if p.content_hash != content_hash(p.content):
        raise HTTPException(
            status_code=422, detail="harness proposal: content_hash mismatch"
        )
    if redact(p.content).counts.get("secret"):
        raise HTTPException(
            status_code=422, detail="harness proposal: content looks like a credential"
        )
    return p


def check_target(session, company_id: str, p: HarnessProposal) -> None:
    """The artifact's target must belong to the request's company."""
    from models import Department

    if p.level == "company":
        ok = p.target_id == company_id
    elif p.level == "department":
        d = session.get(Department, p.target_id)
        ok = bool(d and d.company_id == company_id)
    else:
        person = session.get(Personnel, p.target_id)
        ok = bool(person and person.company_id == company_id)
    if not ok:
        raise HTTPException(status_code=422, detail="harness proposal: target")


def current(session, company_id: str, p: HarnessProposal) -> HarnessArtifact | None:
    return session.exec(
        select(HarnessArtifact).where(
            HarnessArtifact.company_id == company_id,
            HarnessArtifact.level == p.level,
            HarnessArtifact.target_id == p.target_id,
            HarnessArtifact.kind == p.kind,
            HarnessArtifact.key == p.key,
            HarnessArtifact.status == "active",
        )
    ).first()


class HarnessError(Exception):
    """Approval cannot be stored (stale base, bad target); the request stays approved
    but not committed, and must be proposed again."""


def apply(
    session, company_id: str, proposed: dict, cr_id: str | None
) -> HarnessArtifact:
    p = parse_proposal(proposed)
    check_target(session, company_id, p)
    cur = current(session, company_id, p)
    cur_version = cur.version if cur else 0
    if p.base_version != cur_version:
        raise HarnessError(
            f"stale base: proposal was made on v{p.base_version}, current is v{cur_version}"
        )
    if cur is not None:
        session.exec(
            update(HarnessArtifact)
            .where(HarnessArtifact.id == cur.id, HarnessArtifact.status == "active")
            .values(status="superseded")
        )
    art = HarnessArtifact(
        company_id=company_id,
        level=p.level,
        target_id=p.target_id,
        kind=p.kind,
        key=p.key,
        version=cur_version + 1,
        base_version=p.base_version,
        content=p.content,
        content_hash=p.content_hash,
        status="active",
        source_cr_id=cr_id,
        evidence_json=json.dumps([e.model_dump() for e in p.evidence]),
    )
    session.add(art)
    return art


def rollback(session, art: HarnessArtifact) -> HarnessArtifact:
    """Restore the version before `art` as a new, active version."""
    prev = session.exec(
        select(HarnessArtifact)
        .where(
            HarnessArtifact.company_id == art.company_id,
            HarnessArtifact.level == art.level,
            HarnessArtifact.target_id == art.target_id,
            HarnessArtifact.kind == art.kind,
            HarnessArtifact.key == art.key,
            HarnessArtifact.version < art.version,
        )
        .order_by(HarnessArtifact.version.desc())
    ).first()
    if prev is None:
        raise HTTPException(status_code=409, detail="Nothing to roll back to")
    if art.status != "active":
        raise HTTPException(
            status_code=409, detail="Only the active version can be rolled back"
        )
    session.exec(
        update(HarnessArtifact)
        .where(HarnessArtifact.id == art.id)
        .values(status="superseded")
    )
    restored = HarnessArtifact(
        company_id=art.company_id,
        level=art.level,
        target_id=art.target_id,
        kind=art.kind,
        key=art.key,
        version=art.version + 1,
        base_version=art.version,
        content=prev.content,
        content_hash=prev.content_hash,
        status="active",
        source_cr_id=None,
        evidence_json=json.dumps(
            [{"kind": "review", "ref": f"rollback-of-v{art.version}"}]
        ),
    )
    session.add(restored)
    return restored


# ── reading for prompt assembly ──────────────────────────────────────────────


def active_for(
    session, person: Personnel, dept_chain: list[str]
) -> list[HarnessArtifact]:
    """Active artifacts for one person, least specific first (company, departments
    from the top down, the person), so the more specific text comes last."""
    rows: list[HarnessArtifact] = []
    if not person.company_id:
        return rows
    levels = [("company", person.company_id)]
    levels += [("department", d) for d in dept_chain]
    levels.append(("person", person.id))
    for level, target in levels:
        rows += session.exec(
            select(HarnessArtifact)
            .where(
                HarnessArtifact.company_id == person.company_id,
                HarnessArtifact.level == level,
                HarnessArtifact.target_id == target,
                HarnessArtifact.status == "active",
            )
            .order_by(HarnessArtifact.kind, HarnessArtifact.key)
        ).all()
    return rows


def section_text(artifacts: list[HarnessArtifact]) -> str | None:
    """Plain, labelled text for the prompt; grouped by kind in a fixed order."""
    if not artifacts:
        return None
    out: list[str] = []
    for kind in KINDS:
        items = [a.content.strip() for a in artifacts if a.kind == kind]
        if items:
            out.append(f"\n{_HEADINGS[kind]}:")
            out += [f"  - {t}" for t in items]
    return "\n".join(out)


def versions(artifacts: list[HarnessArtifact]) -> list[dict]:
    """What a run used: ids and versions only, never the text."""
    return [
        {
            "id": a.id,
            "level": a.level,
            "kind": a.kind,
            "key": a.key,
            "version": a.version,
        }
        for a in artifacts
    ]
