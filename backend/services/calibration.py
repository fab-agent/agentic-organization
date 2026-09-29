"""Calibration of a rubric criterion before it may rate anyone (ADR-0021 §5).

The criterion's author labels a small sample of work summaries (`expected: met` or
`not_met`, judged against the criterion's own good answer). The scoring model rates
the same texts; this module measures how far the two agree, and records a result that
`rating.set_rubric` requires before a criterion can leave `draft`.

Only decided answers are held to the agreement bar; the share the model leaves
`unclear` is bounded separately, so a model that shrugs at everything cannot pass by
never being wrong. Texts are redacted exactly as in production before they are sent.
Reports carry counts and per-example verdicts, never the texts.

Thresholds are the ADR's starting *proposals* and are parameters, not facts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from services import rubric as rb
from services.redact import redact

MIN_EXAMPLES = 20
MIN_PER_CLASS = 5
MIN_AGREEMENT = 0.85
MAX_UNCLEAR = 0.30
MAX_SAMPLE_BYTES = 200_000


class CalibrationError(ValueError):
    """The samples file cannot be used."""


class Example(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    expected: Literal["met", "not_met"]


class Samples(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion: str
    examples: list[Example]


def parse_samples(text: str) -> Samples:
    if len(text.encode("utf-8")) > MAX_SAMPLE_BYTES:
        raise CalibrationError("samples file is too large")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise CalibrationError(f"not valid YAML: {type(e).__name__}") from e
    if not isinstance(data, dict):
        raise CalibrationError("samples are a mapping with 'criterion' and 'examples'")
    try:
        return Samples.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        raise CalibrationError(
            f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
        ) from e


@dataclass
class Report:
    criterion_id: str
    criterion_hash: str
    n: int
    decided: int
    correct: int
    unclear: int
    errors: int  # the scorer gave no answer (counted as unclear)
    agreement: float | None  # correct / decided; None when nothing was decided
    unclear_rate: float
    per_class: dict[str, int]
    passes: bool
    reasons: list[str] = field(default_factory=list)
    # (expected, verdict) per example, in order — no texts
    results: list[tuple[str, str]] = field(default_factory=list)
    created_at: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate(
    criterion: rb.Criterion,
    examples: list[Example],
    rater,
    *,
    min_examples: int = MIN_EXAMPLES,
    min_per_class: int = MIN_PER_CLASS,
    min_agreement: float = MIN_AGREEMENT,
    max_unclear: float = MAX_UNCLEAR,
) -> Report:
    """Rate every example with the criterion and compare with the author's label."""
    results: list[tuple[str, str]] = []
    errors = 0
    for ex in examples:
        res = rater.rate(redact(ex.text).text, [criterion])
        if res is None:
            errors += 1
            verdict = "unclear"
        else:
            verdict = rb.verdict(criterion, res.p_yes.get(criterion.id))
        results.append((ex.expected, verdict))

    n = len(results)
    decided = [(e, v) for e, v in results if v != "unclear"]
    correct = sum(1 for e, v in decided if e == v)
    unclear = n - len(decided)
    agreement = correct / len(decided) if decided else None
    unclear_rate = unclear / n if n else 1.0
    per_class = {
        "met": sum(1 for e, _ in results if e == "met"),
        "not_met": sum(1 for e, _ in results if e == "not_met"),
    }
    reasons: list[str] = []
    if n < min_examples:
        reasons.append(f"only {n} examples; at least {min_examples} are needed")
    for cls, count in per_class.items():
        if count < min_per_class:
            reasons.append(
                f"only {count} '{cls}' examples; at least {min_per_class} of each are needed"
            )
    if agreement is None:
        reasons.append("the model decided none of the examples")
    elif agreement < min_agreement:
        reasons.append(
            f"agreement {agreement:.0%} on decided examples is below {min_agreement:.0%}"
        )
    if unclear_rate > max_unclear:
        reasons.append(
            f"{unclear_rate:.0%} of answers were unclear; the limit is {max_unclear:.0%}"
        )
    return Report(
        criterion_id=criterion.id,
        criterion_hash=rb.criterion_hash(criterion),
        n=n,
        decided=len(decided),
        correct=correct,
        unclear=unclear,
        errors=errors,
        agreement=agreement,
        unclear_rate=unclear_rate,
        per_class=per_class,
        passes=not reasons,
        reasons=reasons,
        results=results,
        created_at=datetime.utcnow().isoformat(),
    )


# ── the record `set_rubric` reads ────────────────────────────────────────────


def _key(company_id: str, criterion_id: str, criterion_hash: str) -> str:
    return f"work_review.calibration:{company_id}:{criterion_id}:{criterion_hash}"


def record(session, company_id: str, report: Report) -> None:
    """Store the outcome for this exact criterion version. The caller commits."""
    from services import work_review as wr

    wr._put(
        session,
        _key(company_id, report.criterion_id, report.criterion_hash),
        json.dumps(
            {
                "passes": report.passes,
                "n": report.n,
                "agreement": report.agreement,
                "unclear_rate": report.unclear_rate,
                "created_at": report.created_at,
            }
        ),
    )


def latest(session, company_id: str, criterion: rb.Criterion) -> dict | None:
    from services import work_review as wr

    raw = wr._get(session, _key(company_id, criterion.id, rb.criterion_hash(criterion)))
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def is_calibrated(session, company_id: str, criterion: rb.Criterion) -> bool:
    """True only if the criterion's *current wording* passed calibration."""
    v = latest(session, company_id, criterion)
    return bool(v and v.get("passes") is True)


def run(
    session, company_id: str, samples_text: str, rater, *, save: bool = False
) -> Report:
    """Calibrate the criterion named in `samples_text` against the company's stored
    rubric (it may still be `draft` — that is the point) and optionally record the
    outcome. Nothing is stored unless `save`; the caller commits."""
    from services import rating as rt  # rating imports this module

    samples = parse_samples(samples_text)
    loaded = rt.load_rubric(session, company_id)
    if loaded is None:
        raise CalibrationError("this company has no stored rubric")
    criterion = next((c for c in loaded[0].criteria if c.id == samples.criterion), None)
    if criterion is None:
        raise CalibrationError(f"the rubric has no criterion '{samples.criterion}'")
    report = evaluate(criterion, samples.examples, rater)
    if save:
        record(session, company_id, report)
    return report
