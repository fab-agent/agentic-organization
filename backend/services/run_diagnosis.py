"""Run diagnosis: which layer should we look at? (ADR-0023, stage 1)

A pure reader over the audit events of one run. It turns the signals the platform
already records into *findings*, each tied to a layer, and names a suspect layer.

These are signals, not proof. They say where to look first; confirming a cause
needs replay (ADR-0023 stage 3). The module never reads message or document
text: it uses event kinds, statuses, counts and names only.

Events are dicts with `action`, `target`, `reason`, `payload`, `chain_key`, `seq`
(the shape of `AuditEvent`, payload already decoded).

Trust. The chain proves an event was not altered, not that it is true. Events that
a workstation reported carry `payload.origin == "client"` (set by the server).
Client-reported claims of server-observed facts (gateway_call, policy_decision,
context_served) are ignored and counted; tool errors are client-side by nature and
are kept, capped below the severity of server-observed failures. Free-text fields
are never copied: names are shown only if they look like bounded identifiers.

Scope. The caller selects the events: one company, one verified persona, one run.
This module does not group or join events itself (policy decisions carry no run id
yet, ADR-0023), so mixed input gives a mixed diagnosis.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

LAYERS = ("model", "prompt", "tool", "policy")

# How much a finding counts towards its layer. "info" is shown but never scored: it
# describes something observed that does not by itself explain a failure.
_WEIGHT = {"high": 3, "medium": 2, "low": 1, "info": 0}
_SERVER_ONLY = {"gateway_call", "policy_decision", "context_served"}
MAX_EVENTS = 5000
_IDENT = re.compile(r"[A-Za-z][A-Za-z0-9._:/-]{0,47}")
# Shapes that look like credentials or opaque keys even though they are identifier-
# shaped: provider key prefixes, long unbroken alphanumerics, UUIDs.
_SECRETISH = re.compile(
    r"(?i)^(sk-|ghp_|gho_|xox|akia|eyj|bearer)|[A-Za-z0-9]{24,}|"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def _ident(value: Any) -> str:
    """A name we may print: short and identifier-shaped, else a placeholder.

    A shape filter is not anonymisation: a deliberately crafted name can still pass.
    Findings are therefore treated as untrusted data by every consumer, and only
    registry-known names should ever be trusted (ADR-0023 follow-up).
    """
    if (
        isinstance(value, str)
        and _IDENT.fullmatch(value)
        and not _SECRETISH.search(value)
    ):
        return value
    return "[unrecognised]"


@dataclass(frozen=True)
class Finding:
    layer: str
    kind: str
    severity: str  # high | medium | low | info
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
    ignored_client_claims: int = 0
    invalid_events: int = 0
    truncated: bool = False

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "suspect_layer": self.suspect_layer,
            "scores": self.scores,
            "events_seen": self.events_seen,
            "ignored_client_claims": self.ignored_client_claims,
            "invalid_events": self.invalid_events,
            "truncated": self.truncated,
            "findings": [f.as_dict() for f in self.findings],
            "note": "Signals from the audit trail, not proof; confirm by replay.",
        }


def _ev(e: dict) -> tuple[str, int] | None:
    ck, seq = e.get("chain_key"), e.get("seq")
    if isinstance(ck, str) and isinstance(seq, int):
        return (ck, seq)
    return None


def _payload(e: dict) -> dict[str, Any]:
    p = e.get("payload")
    return p if isinstance(p, dict) else {}


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


_FAILURE_SEVERITY = {
    "timeout": "high",
    "transport": "high",
    "parse": "medium",
    "cut": "medium",
}


def _gateway(e: dict, p: dict, out: Diagnosis) -> None:
    status = _int(p.get("upstream_status"))
    model = _ident(p.get("model") or e.get("target"))
    failure = p.get("failure")
    finish = p.get("finish_reason")
    if failure == "client_closed":
        # The caller hung up; not a model fault. Shown, never scored.
        out.findings.append(
            Finding("model", "client_closed", "info", f"{model}: caller closed", _ev(e))
        )
        return
    if failure in _FAILURE_SEVERITY:
        out.findings.append(
            Finding(
                "model",
                "transport_failure",
                _FAILURE_SEVERITY[failure],
                f"{model}: {failure}",
                _ev(e),
            )
        )
        return
    if status is not None and status >= 400:
        sev = "high" if status >= 500 or status in (401, 403, 429) else "medium"
        out.findings.append(
            Finding("model", "upstream_error", sev, f"{model}: HTTP {status}", _ev(e))
        )
    elif finish == "content_filter":
        out.findings.append(
            Finding(
                "model",
                "content_filtered",
                "medium",
                f"{model}: content filter",
                _ev(e),
            )
        )
    elif p.get("has_output") is False and finish != "tool_calls":
        out.findings.append(
            Finding("model", "empty_output", "medium", f"{model}: no output", _ev(e))
        )
    elif finish == "length":
        # Output hit the token limit: a limit/config signal, weak as a model fault.
        out.findings.append(
            Finding(
                "model", "truncated_output", "low", f"{model}: hit length limit", _ev(e)
            )
        )
    elif _int(p.get("tokens_out")) == 0:
        # Provider usage counters can be wrong or missing; zero is a hint only.
        out.findings.append(
            Finding(
                "model",
                "zero_usage",
                "low",
                f"{model}: provider reported 0 tokens out",
                _ev(e),
            )
        )


def _context(e: dict, p: dict, out: Diagnosis) -> None:
    prompt = p.get("prompt")
    prompt = prompt if isinstance(prompt, dict) else {}
    dropped = prompt.get("dropped")
    budget_cut: list[str] = []
    tokens = 0
    for d in dropped if isinstance(dropped, list) else []:
        if not isinstance(d, dict):
            out.invalid_events += 1
            continue
        # Sections left out on purpose for the intent are not a fault.
        if d.get("reason") == "intent":
            continue
        budget_cut.append(_ident(d.get("name")))
        tokens += _int(d.get("tokens")) or 0
    if budget_cut:
        out.findings.append(
            Finding(
                "prompt",
                "sections_dropped",
                "medium",
                f"budget dropped {len(budget_cut)} section(s): {', '.join(budget_cut)} ({tokens} tokens)",
                _ev(e),
            )
        )
    if prompt.get("over_budget") is True:
        out.findings.append(
            Finding(
                "prompt",
                "over_budget",
                "low",
                "required sections exceed the budget",
                _ev(e),
            )
        )


def _policy(e: dict, p: dict, out: Diagnosis) -> None:
    effect = p.get("effect")
    if effect not in ("deny", "ask"):
        return
    target = _ident(e.get("target"))
    rule = _ident(p.get("matched_rule")) if p.get("matched_rule") else "no rule"
    if p.get("fail_closed") is True:
        # A broken rule or malformed request blocked the call: configuration fault.
        out.findings.append(
            Finding(
                "policy",
                "config_fault",
                "high",
                f"{target}: blocked fail-closed",
                _ev(e),
            )
        )
    elif p.get("enforced") is not True:
        out.findings.append(
            Finding(
                "policy",
                f"{effect}_not_enforced",
                "info",
                f"{target}: {effect} by {rule} (dry run)",
                _ev(e),
            )
        )
    elif effect == "deny":
        # A correct block is not a defect; it is worth a look when the run failed.
        out.findings.append(
            Finding(
                "policy",
                "deny_decision",
                "medium",
                f"{target}: denied by {rule}",
                _ev(e),
            )
        )
    else:
        out.findings.append(
            Finding(
                "policy",
                "ask_decision",
                "low",
                f"{target}: needed approval by {rule}",
                _ev(e),
            )
        )


def diagnose(events: Iterable[dict], run_id: str | None = None) -> Diagnosis:
    out = Diagnosis(run_id=run_id)
    seen: set[tuple[str, int]] = set()
    tool_errors: Counter[str] = Counter()
    tool_error_ev: dict[str, tuple[str, int] | None] = {}

    for n, e in enumerate(events):
        if n >= MAX_EVENTS:
            out.truncated = True
            break
        if not isinstance(e, dict):
            out.invalid_events += 1
            continue
        key = _ev(e)
        if key is not None:
            if key in seen:  # the same chain row delivered twice
                continue
            seen.add(key)
        out.events_seen += 1
        action = e.get("action")
        p = _payload(e)

        if action in _SERVER_ONLY and p.get("origin") == "client":
            out.ignored_client_claims += 1
            continue
        try:
            if action == "gateway_call":
                _gateway(e, p, out)
            elif action == "context_served":
                _context(e, p, out)
            elif action == "policy_decision":
                _policy(e, p, out)
            elif (
                action == "tool_event"
                and p.get("error")
                and e.get("reason") != "before"
            ):
                tool = _ident(e.get("target"))
                tool_errors[tool] += 1
                tool_error_ev.setdefault(tool, key)
                out.findings.append(
                    Finding("tool", "tool_error", "medium", f"{tool} failed", key)
                )
        except (TypeError, ValueError, AttributeError):
            out.invalid_events += 1

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

    # Tool findings come from the workstation (a client claim). They never outrank
    # a server-observed failure: if the server saw any scored fault, client-reported
    # tool errors stay listed but do not count towards the suspect layer.
    client_kinds = {"tool_error", "repeated_failure"}
    server_seen = any(
        f.kind not in client_kinds and _WEIGHT[f.severity] > 0 for f in out.findings
    )
    scores = {layer: 0 for layer in LAYERS}
    for f in out.findings:
        if server_seen and f.kind in client_kinds:
            continue
        scores[f.layer] += _WEIGHT[f.severity]
    out.scores = scores
    top = max(scores.values(), default=0)
    if top > 0:
        # Ties are reported as no single suspect: guessing would hide the ambiguity.
        leaders = [layer for layer, s in scores.items() if s == top]
        out.suspect_layer = leaders[0] if len(leaders) == 1 else None
    return out
