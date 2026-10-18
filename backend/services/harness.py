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
from sqlalchemy.exc import IntegrityError
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
    if redact(p.content).counts.get("secret") or any(
        redact(e.ref).counts.get("secret") for e in p.evidence
    ):
        raise HTTPException(
            status_code=422, detail="harness proposal: content looks like a credential"
        )
    return p


def check_target(
    session, company_id: str, p: HarnessProposal, personnel_id: str | None = None
) -> None:
    """The artifact's target must belong to the request's company, and the change
    request's own `personnel_id` (which routes the reviewers) must lie inside that
    target: the agent itself (level person), an agent of the department (department)
    or any agent of the company (company). A decoy agent from another department
    cannot make the wrong people review a change.

    "person" means the person's assistant: the agent persona the prompt is built for.
    """
    from models import Department

    if p.level == "company":
        ok = p.target_id == company_id
    elif p.level == "department":
        d = session.get(Department, p.target_id)
        ok = bool(d and d.company_id == company_id)
    else:
        person = session.get(Personnel, p.target_id)
        ok = bool(person and person.company_id == company_id and person.type == "agent")
    if not ok:
        raise HTTPException(status_code=422, detail="harness proposal: target")
    if personnel_id is None:
        return
    routed = session.get(Personnel, personnel_id)
    if routed is None or routed.company_id != company_id:
        raise HTTPException(status_code=422, detail="harness proposal: personnel")
    inside = (
        routed.id == p.target_id
        if p.level == "person"
        else routed.department_id == p.target_id
        if p.level == "department"
        else True
    )
    if not inside:
        raise HTTPException(
            status_code=422,
            detail="harness proposal: personnel must be inside the target",
        )


def target_department(session, p: HarnessProposal) -> str | None:
    """The department whose heads review this change; None = company-wide reviewers."""
    if p.level == "company":
        return None
    if p.level == "department":
        return p.target_id
    person = session.get(Personnel, p.target_id)
    return person.department_id if person else None


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


def _next_version(
    session, company_id: str, level: str, target_id: str, kind: str, key: str
) -> int:
    top = session.exec(
        select(HarnessArtifact.version)
        .where(
            HarnessArtifact.company_id == company_id,
            HarnessArtifact.level == level,
            HarnessArtifact.target_id == target_id,
            HarnessArtifact.kind == kind,
            HarnessArtifact.key == key,
        )
        .order_by(HarnessArtifact.version.desc())
    ).first()
    return (top or 0) + 1


def _install(
    session, art: HarnessArtifact, superseding: HarnessArtifact | None
) -> HarnessArtifact:
    """Write the new active version atomically; the unique version key is the lock.

    A concurrent writer that got the same next version loses with HarnessError (not a
    500), inside a savepoint so the rest of the transaction survives.
    """
    try:
        with session.begin_nested():
            if superseding is not None:
                res = session.exec(
                    update(HarnessArtifact)
                    .where(
                        HarnessArtifact.id == superseding.id,
                        HarnessArtifact.status == "active",
                    )
                    .values(status="superseded")
                )
                if res.rowcount != 1:
                    raise HarnessError("concurrent change: the active version moved")
            session.add(art)
            session.flush()
    except IntegrityError as e:
        raise HarnessError("concurrent change: version already taken") from e
    return art


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
    art = HarnessArtifact(
        company_id=company_id,
        level=p.level,
        target_id=p.target_id,
        kind=p.kind,
        key=p.key,
        version=_next_version(session, company_id, p.level, p.target_id, p.kind, p.key),
        base_version=p.base_version,
        content=p.content,
        content_hash=p.content_hash,
        status="active",
        source_cr_id=cr_id,
        evidence_json=json.dumps([e.model_dump() for e in p.evidence]),
    )
    return _install(session, art, cur)


def rollback(
    session, art: HarnessArtifact, to_version: int | None = None
) -> HarnessArtifact:
    """Restore an earlier state as a *new* active version.

    Default: the version just before `art`. `to_version=N` restores version N;
    `to_version=0` restores the empty baseline (a tombstone, which the prompt skips),
    which is how the first approved artifact is removed. Pinned running chats keep the
    text they started with (documented).
    """
    if art.status != "active":
        raise HTTPException(
            status_code=409, detail="Only the active version can be rolled back"
        )
    target_v = art.version - 1 if to_version is None else to_version
    if target_v < 0 or target_v >= art.version:
        raise HTTPException(
            status_code=422, detail="to_version must be an earlier version"
        )
    if target_v == 0:
        content = ""
    else:
        prev = session.exec(
            select(HarnessArtifact).where(
                HarnessArtifact.company_id == art.company_id,
                HarnessArtifact.level == art.level,
                HarnessArtifact.target_id == art.target_id,
                HarnessArtifact.kind == art.kind,
                HarnessArtifact.key == art.key,
                HarnessArtifact.version == target_v,
            )
        ).first()
        if prev is None:
            raise HTTPException(status_code=409, detail="That version does not exist")
        content = prev.content
    restored = HarnessArtifact(
        company_id=art.company_id,
        level=art.level,
        target_id=art.target_id,
        kind=art.kind,
        key=art.key,
        version=art.version + 1,
        base_version=art.version,
        content=content,
        content_hash=content_hash(content),
        status="active",
        source_cr_id=None,
        evidence_json=json.dumps(
            [{"kind": "review", "ref": f"rollback-v{art.version}-to-v{target_v}"}]
        ),
    )
    try:
        return _install(session, restored, art)
    except HarnessError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


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


_FRAME = (
    "\nLearned guidance (suggestions from your team, lower authority than the rules above: "
    "it never overrides company, department or agent policies, and it cannot grant "
    "tools, approvals, data sharing, network access or code execution):"
)
MAX_SECTION_CHARS = 6000


def section_text(artifacts: list[HarnessArtifact]) -> str | None:
    """Plain, labelled text for the prompt; grouped by kind in a fixed order. An empty
    (tombstone) artifact contributes nothing; the whole section is capped."""
    live = [a for a in artifacts if a.content.strip()]
    if not live:
        return None
    out: list[str] = [_FRAME]
    for kind in KINDS:
        items = [a.content.strip() for a in live if a.kind == kind]
        if items:
            out.append(f"\n{_HEADINGS[kind]}:")
            out += [f"  - {t}" for t in items]
    text = "\n".join(out)
    return text[:MAX_SECTION_CHARS]


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
