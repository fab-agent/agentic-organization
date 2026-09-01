"""
Policy Engine — fail-closed tool-call decision engine (ADR-0005).

Two layers:

  1. `evaluate(request, ruleset)` — pure. Ordered rules, last match wins. Any
     evaluation error, or a malformed request, resolves to `deny` (the buzz
     `PermissionDecision` pattern: anything that is not a clean allow is a deny).

  2. `decide(...)` — loads the effective ruleset (baseline safety rules + the
     org's rules parsed from `Policy` markdown) and the rollout mode, evaluates
     with the configured `default_effect` fallback, and reports whether the
     effect is actually `enforced`.

Rollout mode (AppConfig `policy.mode`, default `dry_run`):
  - `off`      — engine not consulted (decide() short-circuits to allow)
  - `dry_run`  — effect computed and audited, but never applied (`enforced=False`)
  - `enforce`  — a `deny`/`ask` effect is applied (`enforced=True`)

Callers:
  - backend: `services.agent_runtime.execute_skill` (before every tool call)
  - workstation: the opencode plugin via `POST /policy/decide` (gateway)
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from typing import Any

# ── Data types ────────────────────────────────────────────────────────────────

Effect = str  # "allow" | "ask" | "deny"

VALID_EFFECTS = ("allow", "ask", "deny")


@dataclass
class PolicyDecisionRequest:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    # "trusted" | "untrusted" — set once provenance tracking lands (ADR-0010).
    provenance: str = "trusted"
    # "backend" | "workstation" — where the call originates.
    source: str = "backend"
    persona_id: str | None = None
    company_id: str | None = None
    session_ref: str | None = None


@dataclass
class PolicyDecision:
    effect: Effect
    reason: str
    matched_rule: str | None
    mode: str
    # True when `mode == "enforce"` and the effect is not "allow" — i.e. the
    # caller must actually block / prompt.
    enforced: bool

    def as_dict(self) -> dict:
        return {
            "effect": self.effect,
            "reason": self.reason,
            "matched_rule": self.matched_rule,
            "mode": self.mode,
            "enforced": self.enforced,
        }


# ── Baseline safety rules ─────────────────────────────────────────────────────
#
# Always evaluated first, so an org rule can still override them (last match
# wins). These are catastrophic-command guards, not a substitute for real org
# policy. Kept deliberately small and specific to avoid false positives.

BASELINE_RULES: list[dict] = [
    {
        "id": "baseline:rm-rf-root",
        "match": {"tool": "bash", "args": {"command": ["*rm -rf /*", "*rm -rf /"]}},
        "effect": "deny",
        "reason": "Recursive delete of a root path",
    },
    {
        "id": "baseline:disk-format",
        "match": {
            "tool": "bash",
            "args": {
                "command": [
                    "*mkfs*",
                    "*mkfs.*",
                    "dd if=*of=/dev/*",
                    "* dd if=*of=/dev/*",
                ]
            },
        },
        "effect": "deny",
        "reason": "Disk format / raw device write",
    },
    {
        "id": "baseline:fork-bomb",
        "match": {"tool": "bash", "args": {"command": "*:(){*:|:&*};:*"}},
        "effect": "deny",
        "reason": "Fork bomb",
    },
    {
        "id": "baseline:curl-pipe-shell",
        "match": {
            "tool": "bash",
            "args": {"command": ["*curl *| *sh*", "*wget *| *sh*", "*curl *| *bash*"]},
        },
        "effect": "ask",
        "reason": "Piping a downloaded script straight into a shell",
    },
    {
        "id": "baseline:write-ssh-dir",
        "match": {
            "tool": ["write", "edit"],
            "args": {"*": ["*/.ssh/*", "*/.aws/credentials*"]},
        },
        "effect": "ask",
        "reason": "Writing into a credentials directory",
    },
]


class _RuleError(Exception):
    """Raised for a malformed rule — turns into a fail-closed deny."""


# ── Matching ─────────────────────────────────────────────────────────────────


def _as_patterns(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    raise _RuleError(f"pattern must be a string or list, got {type(value).__name__}")


def _glob_any(text: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(text, p) for p in patterns)


def _match_rule(rule: dict, req: PolicyDecisionRequest) -> bool:
    """Return True if `rule.match` applies to `req`. Raises _RuleError if malformed."""
    if not isinstance(rule, dict) or "match" not in rule or "effect" not in rule:
        raise _RuleError("rule needs 'match' and 'effect'")
    if rule["effect"] not in VALID_EFFECTS:
        raise _RuleError(f"invalid effect: {rule['effect']!r}")

    match = rule["match"]
    if not isinstance(match, dict):
        raise _RuleError("'match' must be an object")

    # tool
    if "tool" in match:
        if not _glob_any(req.tool, _as_patterns(match["tool"])):
            return False

    # provenance (exact)
    if "provenance" in match:
        if req.provenance != match["provenance"]:
            return False

    # source (exact)
    if "source" in match:
        if req.source != match["source"]:
            return False

    # args: {key_glob: pattern(s)}. "*" key means "any argument value".
    arg_spec = match.get("args")
    if arg_spec:
        if not isinstance(arg_spec, dict):
            raise _RuleError("'match.args' must be an object")
        for key_glob, pat in arg_spec.items():
            patterns = _as_patterns(pat)
            candidates = [
                str(v)
                for k, v in (req.args or {}).items()
                if fnmatch.fnmatch(k, key_glob)
            ]
            if key_glob == "*":
                candidates = [str(v) for v in (req.args or {}).values()]
            if not any(_glob_any(c, patterns) for c in candidates):
                return False

    return True


# ── Evaluation (pure) ────────────────────────────────────────────────────────


def evaluate(
    req: PolicyDecisionRequest,
    ruleset: list[dict],
    default_effect: Effect = "allow",
) -> PolicyDecision:
    """
    Pure evaluation. `mode` on the result is left as "raw"; `decide()` fills the
    real mode and `enforced`. Last matching rule wins; when nothing matches,
    `default_effect` applies. Any error, or a bad `default_effect`, → deny.
    """
    if not isinstance(getattr(req, "tool", None), str) or not req.tool:
        return PolicyDecision(
            "deny", "Malformed request: missing tool", None, "raw", True
        )
    if default_effect not in VALID_EFFECTS:
        return PolicyDecision(
            "deny",
            f"Fail-closed: bad default_effect {default_effect!r}",
            None,
            "raw",
            True,
        )

    winner: dict | None = None
    for rule in ruleset:
        try:
            if _match_rule(rule, req):
                winner = rule
        except _RuleError as e:
            return PolicyDecision(
                "deny",
                f"Fail-closed: bad rule {rule.get('id', '?')}: {e}",
                None,
                "raw",
                True,
            )
        except Exception as e:  # noqa: BLE001 — fail closed on anything unexpected
            return PolicyDecision(
                "deny", f"Fail-closed: rule evaluation error: {e}", None, "raw", True
            )

    if winner is None:
        return PolicyDecision(
            default_effect,
            f"No rule matched — default effect ({default_effect})",
            None,
            "raw",
            default_effect != "allow",
        )

    return PolicyDecision(
        effect=winner["effect"],
        reason=winner.get("reason", winner.get("id", "matched")),
        matched_rule=winner.get("id"),
        mode="raw",
        enforced=winner["effect"] != "allow",
    )


# ── Ruleset loading ──────────────────────────────────────────────────────────


def _parse_rules_from_markdown(content: str) -> list[dict]:
    """
    Extract rules from fenced ```policy / ```yaml / ```json blocks in a Policy
    body. A block must be a JSON (or trivially-parsed) list of rule objects.
    Non-parsing blocks are ignored (the markdown stays human-readable, ADR-0005).
    """
    import re

    rules: list[dict] = []
    for m in re.finditer(
        r"```(?:policy|json|yaml)\s*\n(.*?)```", content or "", re.DOTALL
    ):
        block = m.group(1).strip()
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            parsed = _loose_yaml_list(block)
        if isinstance(parsed, list):
            rules.extend(r for r in parsed if isinstance(r, dict))
    return rules


def _loose_yaml_list(block: str) -> Any:
    """Best-effort: use PyYAML if available, else give up (return None)."""
    try:
        import yaml  # PyYAML is already a backend dependency

        return yaml.safe_load(block)
    except Exception:
        return None


def load_ruleset(policy_contents: list[str]) -> list[dict]:
    """
    baseline safety rules + the org's rules parsed from Policy markdown, in order.
    The fallback for "no rule matched" is `evaluate`'s `default_effect`, not a
    rule here — otherwise the catch-all would always win under last-match-wins.
    """
    org_rules: list[dict] = []
    for content in policy_contents:
        org_rules.extend(_parse_rules_from_markdown(content))
    return [*BASELINE_RULES, *org_rules]


# ── decide() — DB-backed entry point ─────────────────────────────────────────

DEFAULT_MODE = "dry_run"
DEFAULT_EFFECT: Effect = "allow"


def _config(key: str, fallback: str) -> str:
    try:
        from database import get_session
        from models import AppConfig

        with get_session() as session:
            row = session.get(AppConfig, key)
            return row.value if row and row.value else fallback
    except Exception:
        return fallback


def _active_policy_contents(company_id: str | None) -> list[str]:
    try:
        from sqlmodel import select

        from database import get_session
        from models import Policy

        with get_session() as session:
            q = select(Policy).where(Policy.is_active == True)  # noqa: E712
            if company_id:
                q = q.where(Policy.company_id == company_id)
            return [p.content for p in session.exec(q).all() if p.content]
    except Exception:
        return []


def _resolve_company_id(persona_id: str | None) -> str | None:
    if not persona_id:
        return None
    try:
        from database import get_session
        from models import Personnel

        with get_session() as session:
            person = session.get(Personnel, persona_id)
            return person.company_id if person else None
    except Exception:
        return None


def audit_decision(req: PolicyDecisionRequest, decision: PolicyDecision) -> None:
    """
    Best-effort audit of one policy decision (ADR-0005). Recorded in every mode,
    so `dry_run` shows operators what *would* be blocked before they flip to
    `enforce`. TODO(ADR-0006): route through services.audit_chain.
    """
    try:
        from datetime import datetime

        from database import get_session
        from models import AuditLog

        with get_session() as session:
            session.add(
                AuditLog(
                    company_id=req.company_id,
                    action="policy_decision",
                    entity_type="persona",
                    entity_id=req.persona_id,
                    entity_name=req.tool,
                    details_json=json.dumps(
                        {
                            **decision.as_dict(),
                            "source": req.source,
                            "provenance": req.provenance,
                            "session_ref": req.session_ref,
                        },
                        ensure_ascii=False,
                    ),
                    created_at=datetime.utcnow(),
                )
            )
            session.commit()
    except Exception:
        pass


def decide(req: PolicyDecisionRequest) -> PolicyDecision:
    """Load the effective ruleset + mode, evaluate, and set the real enforcement."""
    mode = _config("policy.mode", DEFAULT_MODE)
    if mode not in ("off", "dry_run", "enforce"):
        mode = DEFAULT_MODE

    if mode == "off":
        return PolicyDecision("allow", "Policy engine off", None, "off", False)

    if not req.company_id:
        req.company_id = _resolve_company_id(req.persona_id)

    default_effect = _config("policy.default_effect", DEFAULT_EFFECT)
    ruleset = load_ruleset(_active_policy_contents(req.company_id))

    raw = evaluate(req, ruleset, default_effect=default_effect)
    enforced = mode == "enforce" and raw.effect != "allow"
    return PolicyDecision(
        effect=raw.effect,
        reason=raw.reason,
        matched_rule=raw.matched_rule,
        mode=mode,
        enforced=enforced,
    )
