"""The fit rubric: file format, linter and verdict mapping (ADR-0021).

A rubric is a YAML file in the company's policy repo: a list of *criteria*, each one
yes/no question about a piece of work, tied to text the company wrote. This module is
pure (no database, no model calls) apart from `collect_sources`, which only reads.

What it does:

* `parse_rubric` — text → `Rubric`, or `RubricError` with a message a person can act on.
* `lint` — the blocking floor from ADR-0021 §3: every criterion needs a source quote
  that really occurs in the cited source, one question, nothing about the person's
  traits, nothing outside "work, not activity", and the per-department caps.
* `criterion_hash`, `verdict`, `applies` — the identity, the yes/no/unclear mapping and
  the applicability filter that the scoring job will use.

The linter is a floor, not a judge of quality: a bad rubric can still pass it
(ADR-0021, accepted residual risk). Nothing here rates any work.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlmodel import select

MAX_RUBRIC_BYTES = 200_000
MAX_QUESTION_CHARS = 300
MAX_LIVE_PER_DEPARTMENT = 12
MAX_CRITERIA_TOTAL = 30

Status = Literal["draft", "shadow", "live", "retired"]
SOURCE_KINDS = ("goal", "value", "dept_scope", "policy")
# Keys of `applies_when` are the plural of the intent tags (services/intent.py).
APPLIES_KEYS = {"tasks": "task", "sensitivities": "sensitivity", "domains": "domain"}


class RubricError(ValueError):
    """The file cannot be read as a rubric (not a lint finding)."""


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["goal", "value", "dept_scope", "policy"]
    ref: str
    quote: str = ""


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: bool = False
    departments: list[str] = Field(default_factory=list)


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    met: float = 0.7
    not_met: float = 0.3


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    question: str
    good_answer: Literal["yes", "no"]
    source: Source
    scope: Scope
    applies_when: dict[str, list[str]] = Field(default_factory=dict)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    status: Status = "draft"

    @field_validator("good_answer", mode="before")
    @classmethod
    def _yaml_bool(cls, v: Any) -> Any:
        # YAML 1.1 reads an unquoted `yes` / `no` as a boolean.
        if v is True:
            return "yes"
        if v is False:
            return "no"
        return v


class Rubric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    criteria: list[Criterion] = Field(default_factory=list)


@dataclass(frozen=True)
class Finding:
    criterion_id: str  # "" for a finding about the whole rubric
    code: str
    message: str


def parse_rubric(text: str) -> Rubric:
    if len(text.encode("utf-8")) > MAX_RUBRIC_BYTES:
        raise RubricError("rubric file is too large")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise RubricError(f"not valid YAML: {type(e).__name__}") from e
    if not isinstance(data, dict):
        raise RubricError("a rubric is a mapping with a 'criteria' list")
    try:
        return Rubric.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise RubricError(f"{where}: {first['msg']}") from e


# ── sources ──────────────────────────────────────────────────────────────────


def _as_list(v: Any) -> list[str]:
    if isinstance(v, str):
        return [x.strip() for x in v.splitlines() if x.strip()]
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def collect_sources(session, company_id: str) -> dict[str, str]:
    """The texts a criterion may quote, by ref.

    ``company.mission`` · ``company.vision`` · ``company.values.N`` · ``company.goals.N``
    (N from 1) · ``department.<slug>.description`` · ``department.<slug>.goals.N`` ·
    ``policy.<slug>``. Refs are positional, so reordering goals changes them — the
    linter then reports the criterion instead of silently pointing at another goal.
    """
    from models import Company, Department, Policy

    out: dict[str, str] = {}
    co = session.get(Company, company_id)
    if co and co.metadata_json:
        try:
            meta = json.loads(co.metadata_json)
        except ValueError:
            meta = {}
        for key in ("mission", "vision"):
            if isinstance(meta.get(key), str) and meta[key].strip():
                out[f"company.{key}"] = meta[key]
        for key in ("values", "goals"):
            for i, item in enumerate(_as_list(meta.get(key)), 1):
                out[f"company.{key}.{i}"] = item
    for d in session.exec(
        select(Department).where(Department.company_id == company_id)
    ).all():
        if d.description:
            out[f"department.{d.slug}.description"] = d.description
        for i, item in enumerate(_as_list(d.goals), 1):
            out[f"department.{d.slug}.goals.{i}"] = item
    for p in session.exec(
        select(Policy).where(Policy.company_id == company_id, Policy.is_active == True)  # noqa: E712
    ).all():
        out[f"policy.{p.slug}"] = p.content
    return out


# ── lint ─────────────────────────────────────────────────────────────────────

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")

# Activity, not work (ADR-0019 §6) — and characteristics no criterion may touch.
_ACTIVITY = re.compile(
    r"\b(keystrokes?|typing speed|screenshots?|mouse|idle|time on task|hours worked|"
    r"working hours|attendance|punctual\w*|late arrival|"
    r"tuş\w*|ekran görüntüsü|mesai|devamsızlık|devam durumu|boşta)\b",
    re.I,
)
_PROTECTED = re.compile(
    r"\b(gender|sex|sexual\w*|age|religio\w*|ethnic\w*|race|racial|pregnan\w*|disabilit\w*|"
    r"marital|political\w*|union|nationality|"
    r"cinsiyet\w*|yaş\w*|din|dini|etnik\w*|ırk\w*|hamile\w*|engelli\w*|medeni|siyasi|"
    r"sendika\w*|uyruk\w*)\b",
    re.I,
)
# A question about the person, not the work.
_PERSON = re.compile(
    r"\b(employee|person|worker|he|she|his|her|personality|attitude|character|motivat\w*|"
    r"lazy|loyal\w*|çalışan\w*|kişi|kişilik\w*|tutum\w*|karakter\w*|tembel\w*|sadık\w*)\b",
    re.I,
)
_MULTI = re.compile(r"(\band/or\b|/or\b|\bve/veya\b|\?.+\?)", re.I | re.S)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def lint(
    rubric: Rubric,
    sources: dict[str, str],
    *,
    department_slugs: set[str] | None = None,
) -> list[Finding]:
    """Blocking findings; an empty list means the rubric passes the floor."""
    out: list[Finding] = []

    def add(c: Criterion | None, code: str, msg: str) -> None:
        out.append(Finding(c.id if c else "", code, msg))

    seen: set[str] = set()
    normed = {ref: _norm(text) for ref, text in sources.items()}
    for c in rubric.criteria:
        if not _ID.match(c.id):
            add(c, "bad_id", "id must be 2–64 letters, digits, '.', '_' or '-'")
        if c.id in seen:
            add(c, "duplicate_id", "id is used twice; ids are never reused")
        seen.add(c.id)

        q = c.question.strip()
        if not q:
            add(c, "empty_question", "the question is empty")
        elif len(q) > MAX_QUESTION_CHARS:
            add(
                c,
                "long_question",
                f"the question is over {MAX_QUESTION_CHARS} characters",
            )
        elif not q.endswith("?"):
            add(c, "not_a_question", "write it as one closed question ending in '?'")
        if _MULTI.search(q):
            add(
                c,
                "several_questions",
                "ask one thing; split 'and/or' into two criteria",
            )
        if _ACTIVITY.search(q):
            add(
                c,
                "activity_not_work",
                "criteria rate work, never activity or attendance",
            )
        if _PROTECTED.search(q):
            add(
                c,
                "protected_characteristic",
                "a criterion may not touch personal characteristics",
            )
        if _PERSON.search(q):
            add(c, "about_the_person", "ask about the work, not about the person")

        src = c.source
        quote = _norm(src.quote)
        if not quote:
            add(c, "no_source_quote", "a criterion needs the exact text it comes from")
        elif src.ref not in normed:
            add(
                c,
                "unknown_source",
                f"no source '{src.ref}' exists (refs are positional)",
            )
        elif quote not in normed[src.ref]:
            add(c, "quote_not_in_source", f"the quote does not occur in '{src.ref}'")

        t = c.thresholds
        if not (0.0 < t.not_met < t.met < 1.0):
            add(c, "bad_thresholds", "need 0 < not_met < met < 1")

        if not c.scope.company and not c.scope.departments:
            add(c, "no_scope", "set scope.company or scope.departments")
        if department_slugs is not None:
            for d in c.scope.departments:
                if d not in department_slugs:
                    add(c, "unknown_department", f"department '{d}' does not exist")
        for key, vals in c.applies_when.items():
            if key not in APPLIES_KEYS:
                add(
                    c,
                    "bad_applies_key",
                    f"applies_when key '{key}' is not one of {sorted(APPLIES_KEYS)}",
                )
            elif not vals or any(not isinstance(v, str) or not v.strip() for v in vals):
                add(c, "bad_applies_value", f"applies_when.{key} needs a list of names")
        if (
            "personal" in c.applies_when.get("sensitivities", [])
            and src.kind != "policy"
        ):
            add(
                c,
                "personal_without_policy",
                "rating personal-data work needs a policy as its source",
            )

    active = [c for c in rubric.criteria if c.status != "retired"]
    if len(active) > MAX_CRITERIA_TOTAL:
        add(
            None, "too_many", f"{len(active)} criteria; the cap is {MAX_CRITERIA_TOTAL}"
        )
    live = [c for c in rubric.criteria if c.status == "live"]
    company_live = sum(1 for c in live if c.scope.company)
    per_dept: dict[str, int] = {}
    for c in live:
        for d in c.scope.departments:
            per_dept[d] = per_dept.get(d, 0) + 1
    for d, n in sorted(per_dept.items()):
        if n + company_live > MAX_LIVE_PER_DEPARTMENT:
            add(
                None,
                "too_many_for_department",
                f"department '{d}' would have {n + company_live} live criteria; the cap is {MAX_LIVE_PER_DEPARTMENT}",
            )
    if company_live > MAX_LIVE_PER_DEPARTMENT:
        add(
            None,
            "too_many_for_department",
            f"{company_live} company-wide live criteria; the cap is {MAX_LIVE_PER_DEPARTMENT}",
        )
    return out


# ── identity, applicability, verdict ─────────────────────────────────────────


def criterion_hash(c: Criterion) -> str:
    """Identity for comparison: wording, good answer and thresholds (ADR-0021 §4)."""
    body = "\x1f".join(
        [
            _norm(c.question),
            c.good_answer,
            f"{c.thresholds.met:.4f}",
            f"{c.thresholds.not_met:.4f}",
        ]
    )
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def applies(c: Criterion, tags: dict[str, Any], department_slug: str | None) -> bool:
    """Is this piece of work in scope for the criterion? Not applicable ≠ not met."""
    if not c.scope.company and department_slug not in c.scope.departments:
        return False
    for key, wanted in c.applies_when.items():
        tag = APPLIES_KEYS.get(key)
        if tag is None:
            return False
        if tags.get(tag) not in wanted:
            return False
    return True


def verdict(c: Criterion, p_yes: float | None) -> Literal["met", "not_met", "unclear"]:
    """Map the model's probability of "yes" to a verdict; unclear is never rounded."""
    if p_yes is None or isinstance(p_yes, bool) or not (0.0 <= p_yes <= 1.0):
        return "unclear"
    good = p_yes if c.good_answer == "yes" else 1.0 - p_yes
    if good >= c.thresholds.met:
        return "met"
    if good <= c.thresholds.not_met:
        return "not_met"
    return "unclear"
