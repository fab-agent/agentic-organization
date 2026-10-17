"""Run diagnosis: which layer should we look at? (ADR-0023, stage 1)

A pure reader over the audit events of one run. It turns the signals the platform
already records into *findings*, each tied to a layer, and names a suspect layer.

These are signals, not proof. They say where to look first; confirming a cause
needs replay (ADR-0023 stage 3). The module never reads message or document
text: it uses event kinds, statuses, counts and names only.

Events are dicts with `action`, `target`, `reason`, `payload`, `chain_key`, `seq`
(the shape of `AuditEvent`, payload already decoded).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

LAYERS = ("model", "prompt", "tool", "policy")

# How much a finding counts towards its layer. A hard failure outweighs a note.
_WEIGHT = {"high": 3, "medium": 2, "low": 1}


@dataclass(frozen=True)
class Finding:
    layer: str
    kind: str
    severity: str  # high | medium | low
    detail: str
    evidence: tuple[str, int] | None = None  # (chain_key, seq)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = list(self.evidence) if self.evidence else None
        return d


@dataclass
class Diagnosis:
    run_id: str | None
    findings: list[Finding] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)
    suspect_layer: str | None = None
    # With nothing to go on we say so instead of implying a healthy run.
    events_seen: int = 0

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "suspect_layer": self.suspect_layer,
            "scores": self.scores,
            "events_seen": self.events_seen,
            "findings": [f.as_dict() for f in self.findings],
            "note": "Signals from the audit trail, not proof; confirm by replay.",
        }


def _ev(e: dict) -> tuple[str, int] | None:
    if e.get("chain_key") is not None and e.get("seq") is not None:
        return (e["chain_key"], e["seq"])
    return None


def _payload(e: dict) -> dict[str, Any]:
    p = e.get("payload")
    return p if isinstance(p, dict) else {}


def diagnose(events: Iterable[dict], run_id: str | None = None) -> Diagnosis:
    events = list(events)
    out = Diagnosis(run_id=run_id, events_seen=len(events))
    tool_errors: Counter[str] = Counter()
    tool_error_ev: dict[str, tuple[str, int] | None] = {}

    for e in events:
        action = e.get("action")
        p = _payload(e)

        if action == "gateway_call":
            status = p.get("upstream_status")
            model = p.get("model") or e.get("target") or "?"
            if isinstance(status, int) and status >= 400:
                sev = "high" if status >= 500 or status in (401, 403, 429) else "medium"
                out.findings.append(
                    Finding(
                        "model",
                        "upstream_error",
                        sev,
                        f"{model}: HTTP {status}",
                        _ev(e),
                    )
                )
            elif p.get("tokens_out") == 0:
                out.findings.append(
                    Finding(
                        "model",
                        "empty_output",
                        "medium",
                        f"{model}: no tokens out",
                        _ev(e),
                    )
                )

        elif action == "context_served":
            prompt = p.get("prompt") or {}
            dropped = prompt.get("dropped") or []
            if dropped:
                names = ", ".join(str(d.get("name")) for d in dropped)
                tokens = sum(int(d.get("tokens") or 0) for d in dropped)
                out.findings.append(
                    Finding(
                        "prompt",
                        "sections_dropped",
                        "medium",
                        f"budget dropped {len(dropped)} section(s): {names} ({tokens} tokens)",
                        _ev(e),
                    )
                )
            if prompt.get("over_budget"):
                out.findings.append(
                    Finding(
                        "prompt",
                        "over_budget",
                        "low",
                        "required sections exceed the budget",
                        _ev(e),
                    )
                )

        elif action == "policy_decision":
            effect = p.get("effect")
            if effect in ("deny", "ask"):
                rule = p.get("matched_rule") or "no rule"
                sev = "high" if effect == "deny" and p.get("enforced") else "medium"
                out.findings.append(
                    Finding(
                        "policy",
                        f"{effect}_decision",
                        sev,
                        f"{e.get('target')}: {effect} by {rule}"
                        + (" (fail-closed)" if p.get("fail_closed") else ""),
                        _ev(e),
                    )
                )

        elif action == "tool_event":
            tool = e.get("target") or "?"
            if p.get("error"):
                tool_errors[tool] += 1
                tool_error_ev.setdefault(tool, _ev(e))
                out.findings.append(
                    Finding("tool", "tool_error", "medium", f"{tool} failed", _ev(e))
                )

    for tool, n in tool_errors.items():
        if n >= 2:
            out.findings.append(
                Finding(
                    "tool",
                    "repeated_failure",
                    "high",
                    f"{tool} failed {n} times in one run",
                    tool_error_ev.get(tool),
                )
            )

    scores = {layer: 0 for layer in LAYERS}
    for f in out.findings:
        scores[f.layer] += _WEIGHT[f.severity]
    out.scores = scores
    top = max(scores.values(), default=0)
    if top > 0:
        # Ties are reported as no single suspect: guessing would hide the ambiguity.
        leaders = [layer for layer, s in scores.items() if s == top]
        out.suspect_layer = leaders[0] if len(leaders) == 1 else None
    return out
