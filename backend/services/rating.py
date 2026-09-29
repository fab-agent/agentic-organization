"""Fit rating: score one run's summary against the rubric (ADR-0021).

What is here: storing a company's rubric behind the linter, choosing which criteria
apply to a run, sampling, the filter stage (`services.redact`, applied inside
`rate_run` so no caller can skip it), one Jev call per run, writing `WorkRating` rows,
and an hourly job (`rate_recent_sessions`) that rates the LLM summaries of recently
closed agent sessions. Off unless the company enabled work review **and** switched
rating on separately, and a scoring key is configured.

What is *not* here, on purpose:

* **The filter recognises identifiers by shape only** — not names or prose details —
  so it is a floor (see `services.redact`); the summary still leaves the premises with
  Jev.
* **No reasons.** TypeSafe answers are probabilities, not text, so a rating carries no
  free-text reason (which also keeps personal data out of stored rows).
* **No views, aggregates, contest endpoint or training-need signal.** Ratings are
  therefore visible to nobody, which trivially keeps shadow ratings from anyone but
  their subject.

Fail open: any scoring failure stores nothing and never blocks the work.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlmodel import select

from database import get_session
from models import (
    AgentMemory,
    AuditEvent,
    Company,
    Department,
    Personnel,
    WorkRating,
)
from services import rubric as rb
from services import work_review as wr
from services.intent import quiet_sdk_logs
from services.redact import redact

logger = logging.getLogger("app")

DEFAULT_SAMPLE_RATE = 0.2
MAX_SUMMARY_CHARS = 4000
MAX_CRITERIA_PER_CALL = 12
RATED_STATUSES = ("shadow", "live")


# ── settings ──────────────────────────────────────────────────────────────────


def rating_enabled(session, company_id: str) -> bool:
    """Work review must be on for the company, and rating switched on separately."""
    if not wr.enabled(session, company_id):
        return False
    v = wr._get(session, f"work_review.rating.enabled:{company_id}")
    return v is not None and v.strip().lower() in wr._TRUE


def set_rating_enabled(session, company_id: str, on: bool) -> None:
    wr._put(
        session, f"work_review.rating.enabled:{company_id}", "true" if on else "false"
    )


def sample_rate(session, company_id: str) -> float:
    try:
        r = float(
            wr._get(session, f"work_review.rating.sample_rate:{company_id}") or ""
        )
    except ValueError:
        return DEFAULT_SAMPLE_RATE
    return r if 0.0 <= r <= 1.0 else DEFAULT_SAMPLE_RATE


# ── the company's rubric ──────────────────────────────────────────────────────


def _rubric_key(company_id: str) -> str:
    return f"work_review.rubric:{company_id}"


def rubric_version(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def set_rubric(session, company_id: str, text: str) -> list[rb.Finding]:
    """Store the rubric only if it parses and passes the linter; return the findings
    (empty = stored). An unreadable file raises `RubricError`. The caller commits."""
    rubric = rb.parse_rubric(text)
    slugs = set(
        session.exec(
            select(Department.slug).where(Department.company_id == company_id)
        ).all()
    )
    findings = rb.lint(
        rubric, rb.collect_sources(session, company_id), department_slugs=slugs
    )
    if not findings:
        wr._put(session, _rubric_key(company_id), text)
    return findings


def load_rubric(session, company_id: str) -> tuple[rb.Rubric, str] | None:
    """(rubric, version) or None when there is none or it no longer parses."""
    text = wr._get(session, _rubric_key(company_id))
    if not text:
        return None
    try:
        return rb.parse_rubric(text), rubric_version(text)
    except rb.RubricError:
        return None


# ── the scoring model ─────────────────────────────────────────────────────────


@dataclass
class RatingResult:
    p_yes: dict[str, float | None]  # criterion id → probability of "yes"
    model: str | None = None


class Rater(Protocol):
    def rate(
        self, summary: str, criteria: list[rb.Criterion]
    ) -> RatingResult | None: ...


class JevRater:
    """`Rater` backed by the TypeSafe SDK: one yes/no (`Noul`) question per criterion."""

    def __init__(self, client: Any = None, timeout: float = 3.0):
        quiet_sdk_logs()
        self._client = client
        self._timeout = timeout
        self.last_error: str | None = None

    def _get_client(self):
        if self._client is None:
            from typesafe_sdk import TypeSafeClient

            self._client = TypeSafeClient()
        return self._client

    def rate(self, summary: str, criteria: list[rb.Criterion]) -> RatingResult | None:
        text = (summary or "").strip()[:MAX_SUMMARY_CHARS]
        crit = criteria[:MAX_CRITERIA_PER_CALL]
        if not text or not crit:
            return None
        quiet_sdk_logs()
        try:
            from typesafe_sdk import Noul, RetryPolicy

            resp = self._get_client().system_one(
                state=text,
                questions={
                    f"q{i}": Noul(instructions=c.question) for i, c in enumerate(crit)
                },
                timeout=self._timeout,
                retry=RetryPolicy(max_retries=0, timeout=self._timeout),
            )
            out: dict[str, float | None] = {}
            for i, c in enumerate(crit):
                a = resp.answers.get(f"q{i}")
                ok = a is not None and getattr(a, "type", None) == "noul"
                out[c.id] = float(a.noul) if ok else None
            self.last_error = None
            return RatingResult(p_yes=out, model=getattr(resp, "model", None))
        except Exception as e:  # noqa: BLE001 - any failure means "no rating"
            self.last_error = type(e).__name__
            logger.warning(
                "work_rating_failed", extra={"extra": {"error": type(e).__name__}}
            )
            return None


def get_rater() -> Rater | None:
    """The configured rater, or None (no key, or no SDK)."""
    if not os.getenv("TYPESAFE_API_KEY"):
        return None
    try:
        import typesafe_sdk  # noqa: F401
    except Exception:  # noqa: BLE001
        return None
    return JevRater()


# ── rating a run ──────────────────────────────────────────────────────────────


def sampled(run_id: str, rate: float) -> bool:
    """Deterministic per run, so a retry never re-rolls the dice."""
    h = int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16) / 2**32
    return h < rate


def rate_run(
    session,
    *,
    person: Personnel,
    run_id: str,
    summary: str,
    tags: dict[str, Any],
    rater: Rater | None,
    day: str | None = None,
) -> list[WorkRating]:
    """Rate one run's summary (redacted here, before it reaches the rater); returns the
    rows written.

    Nothing is written — and the rater is not called — unless: the person is a human
    of a company that enabled work review *and* rating, a rubric is stored, some
    shadow/live criterion applies, the run is sampled (every personal-data run is),
    and there is a summary. The caller passes tags from the intent classification.
    """
    cid = person.company_id
    if not cid or person.type != "human" or rater is None:
        return []
    if not (summary or "").strip() or not rating_enabled(session, cid):
        return []
    loaded = load_rubric(session, cid)
    if loaded is None:
        return []
    rubric, version = loaded
    dept = (
        session.get(Department, person.department_id) if person.department_id else None
    )
    slug = dept.slug if dept else None
    eligible = [
        c
        for c in rubric.criteria
        if c.status in RATED_STATUSES and rb.applies(c, tags, slug)
    ]
    if not eligible:
        return []
    if tags.get("sensitivity") != "personal" and not sampled(
        run_id, sample_rate(session, cid)
    ):
        return []
    done = {
        (r.criterion_id, r.criterion_hash)
        for r in session.exec(
            select(WorkRating).where(
                WorkRating.personnel_id == person.id, WorkRating.run_id == run_id
            )
        ).all()
    }
    todo = [c for c in eligible if (c.id, rb.criterion_hash(c)) not in done]
    if not todo:
        return []
    result = rater.rate(redact(summary).text, todo)
    if result is None:
        return []
    day = day or datetime.utcnow().date().isoformat()
    rows = []
    for c in todo[:MAX_CRITERIA_PER_CALL]:
        p = result.p_yes.get(c.id)
        p = p if isinstance(p, (int, float)) and not isinstance(p, bool) else None
        row = WorkRating(
            company_id=cid,
            personnel_id=person.id,
            day=day,
            run_id=run_id,
            criterion_id=c.id,
            criterion_hash=rb.criterion_hash(c),
            rubric_version=version,
            criterion_status=c.status,
            verdict=rb.verdict(c, p),
            probability=p,
            model=result.model,
        )
        session.add(row)
        rows.append(row)
    session.commit()
    return rows


# ── the hourly job ────────────────────────────────────────────────────────────


def _session_tags(session, company_id: str, agent_id: str, session_id: str) -> dict:
    """Tags of the latest intent classification of this session (audit, not content)."""
    ev = session.exec(
        select(AuditEvent)
        .where(
            AuditEvent.company_id == company_id,
            AuditEvent.action == "intent_classified",
            AuditEvent.actor_id == agent_id,
            AuditEvent.target == session_id,
        )
        .order_by(AuditEvent.created_at.desc())
    ).first()
    if ev is None or not ev.payload_json:
        return {}
    try:
        tags = json.loads(ev.payload_json).get("tags")
    except (ValueError, AttributeError):
        return {}
    return tags if isinstance(tags, dict) else {}


def rate_recent_sessions(
    rater: Rater | None = None, now: datetime | None = None, hours: int = 48
) -> int:
    """Rate the summaries of agent sessions closed in the last `hours`, for every
    company that switched rating on. Returns the rows written. A no-op without a
    scoring key; one bad session never stops the rest. Re-running is safe (rows are
    idempotent per run and criterion)."""
    rater = rater or get_rater()
    if rater is None:
        return 0
    since = (now or datetime.utcnow()) - timedelta(hours=hours)
    written = 0
    with get_session() as session:
        for cid in session.exec(select(Company.id)).all():
            if not rating_enabled(session, cid):
                continue
            owners = wr.owner_map(session, cid)
            memories = session.exec(
                select(AgentMemory)
                .join(Personnel, Personnel.id == AgentMemory.personnel_id)
                .where(
                    Personnel.company_id == cid,
                    AgentMemory.created_at >= since,
                    AgentMemory.session_id.is_not(None),
                )
            ).all()
            for m in memories:
                try:
                    owner = session.get(Personnel, owners.get(m.personnel_id, ""))
                    if owner is None:
                        continue
                    rows = rate_run(
                        session,
                        person=owner,
                        run_id=m.session_id,
                        summary=m.summary,
                        tags=_session_tags(session, cid, m.personnel_id, m.session_id),
                        rater=rater,
                        day=m.created_at.date().isoformat(),
                    )
                    written += len(rows)
                except Exception as e:  # noqa: BLE001 - keep going with the others
                    session.rollback()
                    logger.warning(
                        "work_rating_session_failed",
                        extra={"extra": {"error": type(e).__name__}},
                    )
    return written
