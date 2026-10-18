"""Success judges for agent runs (ADR-0023 stage 2, first slice).

A *verdict* answers one yes/no criterion about a run:

* **Deterministic** judges read the stage-1 diagnosis (did the model answer, was a
  tool or policy block involved). They need no model and no text.
* **Text** judges ask a TypeSafe yes/no model (`Noul`, through the same `Rater` the
  fit rating uses) a question about *redacted* text. They abstain (`unclear`) when no
  scoring model is configured, when the model gives no answer, or when its probability
  is between the two thresholds. An abstention is never counted as a pass or a fail.

Verdicts carry a value, the probability when there is one, and the basis; never the
text. Thresholds are proposals (the same ones the ADR-0021 calibration measures
against) and a text criterion is only trusted after `services.calibration` has
measured its agreement on labelled samples; this module does not decide that.

Reported measures: `success_interval` gives the Wilson interval of a pass share, so a
handful of runs is shown as the wide, uncertain number it is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from services.redact import redact
from services.run_diagnosis import Diagnosis

YES_AT = 0.8
NO_AT = 0.2

Value = Literal["yes", "no", "unclear"]


@dataclass(frozen=True)
class TextCriterion:
    """One yes/no question about a text (duck-compatible with `rating.JevRater`)."""

    id: str
    question: str


@dataclass(frozen=True)
class Verdict:
    criterion_id: str
    value: Value
    p_yes: float | None = None
    basis: Literal["deterministic", "typesafe"] = "deterministic"


def verdict_from_p(criterion_id: str, p_yes: float | None) -> Verdict:
    """Map a probability of "yes" to a verdict; the middle band abstains."""
    if p_yes is None or not 0.0 <= p_yes <= 1.0:
        return Verdict(criterion_id, "unclear", None, "typesafe")
    if p_yes >= YES_AT:
        return Verdict(criterion_id, "yes", p_yes, "typesafe")
    if p_yes <= NO_AT:
        return Verdict(criterion_id, "no", p_yes, "typesafe")
    return Verdict(criterion_id, "unclear", p_yes, "typesafe")


# ── deterministic judges over a stage-1 diagnosis ────────────────────────────

_MODEL_FAILURES = {
    "transport_failure",
    "upstream_error",
    "empty_output",
    "content_filtered",
}


def judge_run(d: Diagnosis) -> list[Verdict]:
    """Built-in criteria from the diagnosis. No events means nothing can be said."""
    if d.events_seen == 0:
        return [
            Verdict(c, "unclear")
            for c in ("answered", "no_tool_error", "no_policy_block")
        ]
    kinds = {f.kind for f in d.findings}
    if any(f.kind == "client_closed" for f in d.findings) and not (
        kinds & _MODEL_FAILURES
    ):
        answered: Value = "unclear"  # the caller left; neither a pass nor a fault
    else:
        answered = "no" if kinds & _MODEL_FAILURES else "yes"
    return [
        Verdict("answered", answered),
        Verdict(
            "no_tool_error",
            "no" if kinds & {"tool_error", "repeated_failure"} else "yes",
        ),
        Verdict(
            "no_policy_block",
            "no" if kinds & {"deny_decision", "config_fault"} else "yes",
        ),
    ]


# ── text judges (TypeSafe Noul) ──────────────────────────────────────────────


def judge_text(rater, text: str, criteria: list[TextCriterion]) -> list[Verdict]:
    """Ask yes/no questions about `text` after redaction; abstain on any failure."""
    cleaned = redact(text or "").text
    if rater is None or not cleaned.strip() or not criteria:
        return [Verdict(c.id, "unclear", None, "typesafe") for c in criteria]
    result = rater.rate(cleaned, criteria)
    if result is None:
        return [Verdict(c.id, "unclear", None, "typesafe") for c in criteria]
    return [verdict_from_p(c.id, result.p_yes.get(c.id)) for c in criteria]


# ── reported measure ─────────────────────────────────────────────────────────


def success_interval(passes: int, decided: int, z: float = 1.96) -> dict:
    """Wilson score interval of the pass share among *decided* verdicts."""
    if decided <= 0:
        return {"n": 0, "share": None, "low": None, "high": None}
    p = passes / decided
    denom = 1 + z * z / decided
    centre = (p + z * z / (2 * decided)) / denom
    half = (
        z * math.sqrt(p * (1 - p) / decided + z * z / (4 * decided * decided)) / denom
    )
    return {
        "n": decided,
        "share": round(p, 4),
        "low": round(max(0.0, centre - half), 4),
        "high": round(min(1.0, centre + half), 4),
    }
