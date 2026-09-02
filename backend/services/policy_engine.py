"""
Policy Engine — fail-closed tool-call decision engine (ADR-0005).

Two layers:

  1. `evaluate(request, ruleset)` — pure. Ordered rules, last match wins. Any
     evaluation error, or a malformed request, resolves to `deny` (the buzz
     `PermissionDecision` pattern: anything that is not a clean allow is a deny).

  2. `decide(...)` — for a given persona, resolves scope (company → department →
     agent), the applicable `Policy` bodies (same gathering as
     `agent_runtime.run_session`: company-scoped + DepartmentPolicyLink +
     AgentPolicyLink), and the rollout mode, then evaluates.

Rollout mode — resolved most-specific-wins from `PolicyConfig`
(agent → department → company), then global AppConfig `policy.mode`, default
`dry_run`:
  - `off`      — engine not consulted (decide() short-circuits to allow)
  - `dry_run`  — a clean matched deny/ask is audited but NOT applied
  - `enforce`  — a clean matched deny/ask is applied

A **fail-closed** verdict (bad rule / malformed request / bad default_effect)
is `enforced` in every mode, `dry_run` included — a broken policy config must
never silently pass.

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
    # "trusted" | "untrusted" (ADR-0010). The opencode plugin marks a session
    # "untrusted" once it has run a tool whose output is attacker-controllable
    # (web fetch / search); the backend runtime can set it per-argument.
    provenance: str = "trusted"
    # "backend" | "workstation" — where the call originates.
    source: str = "backend"
    persona_id: str | None = None
    # Scope — resolved from persona_id by decide() when not supplied.
    company_id: str | None = None
    department_id: str | None = None
    agent_config_id: str | None = None
    session_ref: str | None = None


@dataclass
class PolicyDecision:
    effect: Effect
    reason: str
    matched_rule: str | None
    mode: str
    # True when the caller must actually block / prompt. This is the case when
    # `mode == "enforce"` and the effect is not "allow", OR whenever `fail_closed`
    # is set — a broken policy config blocks in every mode, dry_run included.
    enforced: bool
    # True when this decision came from a fail-closed path (bad rule, malformed
    # request, bad default_effect). Operators should be alerted.
    fail_closed: bool = False

    def as_dict(self) -> dict:
        return {
            "effect": self.effect,
            "reason": self.reason,
            "matched_rule": self.matched_rule,
            "mode": self.mode,
            "enforced": self.enforced,
            "fail_closed": self.fail_closed,
        }


# ── Baseline safety rules ─────────────────────────────────────────────────────
#
# Always evaluated first, so an org rule can still override them (last match
# wins). These are catastrophic-command guards, not a substitute for real org
# policy. Kept deliberately small and specific to avoid false positives.

_SYSTEM_DIRS = [
    "bin",
    "boot",
    "dev",
    "etc",
    "home",
    "lib",
    "lib32",
    "lib64",
    "opt",
    "proc",
    "root",
    "run",
    "sbin",
    "srv",
    "sys",
    "usr",
    "var",
]
# Exact targets only — "/*" would cross "/" under fnmatch and over-match, and a
# bare "*" would match the "-rf" flag itself. "/", "~", "$HOME", and each system
# dir (with/without trailing slash, and one level of children).
_ROOT_TARGETS = (
    ["/", "~", "$HOME", "--no-preserve-root"]
    + [f"/{d}" for d in _SYSTEM_DIRS]
    + [f"/{d}/" for d in _SYSTEM_DIRS]
    + [f"/{d}/*" for d in _SYSTEM_DIRS]
)

BASELINE_RULES: list[dict] = [
    {
        # ADR-0010 layer 4: a high-risk tool on a turn that has ingested
        # untrusted content (web fetch / search results, uploaded files, A2A
        # output) is the main injection-driven exfil / unauthorised-action
        # channel. Downgrade it to `ask`. Placed first so the catastrophic
        # `deny` rules below still win under last-match-wins, and so an org rule
        # can still relax or tighten it.
        "id": "baseline:untrusted-high-risk",
        "match": {
            "tool": ["bash", "webfetch", "fetch", "write", "edit", "patch"],
            "provenance": "untrusted",
        },
        "effect": "ask",
        "reason": "High-risk tool on a turn that ingested untrusted content (ADR-0010)",
    },
    {
        "id": "baseline:rm-rf-root",
        # AST-based: program `rm`, a recursive flag, targeting a top-level path.
        # Immune to spacing / quoting / `sudo` / `$(...)` (ADR-0005).
        "match": {
            "tool": "bash",
            "command": {
                "program": ["rm"],
                "args_all_of": ["-*[rR]*"],
                "args_any_of": _ROOT_TARGETS,
            },
        },
        "effect": "deny",
        "reason": "Recursive delete of a root path",
    },
    {
        "id": "baseline:disk-format",
        "match": {
            "tool": "bash",
            "command": {"any_program": ["mkfs", "mkfs.*", "fdisk", "parted", "wipefs"]},
        },
        "effect": "deny",
        "reason": "Disk partition / format tool",
    },
    {
        "id": "baseline:dd-to-device",
        "match": {
            "tool": "bash",
            "command": {"program": ["dd"], "args_any_of": ["of=/dev/*"]},
        },
        "effect": "deny",
        "reason": "Raw write to a block device",
    },
    {
        "id": "baseline:fork-bomb",
        # Structural parse of `:(){ ... }` is unreliable — keep the literal glob.
        "match": {"tool": "bash", "args": {"command": "*:(){*:|:&*};:*"}},
        "effect": "deny",
        "reason": "Fork bomb",
    },
    {
        "id": "baseline:curl-pipe-shell",
        "match": {
            "tool": "bash",
            "command": {
                "any_program": ["curl", "wget", "fetch"],
                "pipes_into": [
                    "sh",
                    "bash",
                    "zsh",
                    "dash",
                    "python",
                    "python3",
                    "perl",
                    "ruby",
                ],
            },
        },
        "effect": "ask",
        "reason": "Piping a downloaded script straight into an interpreter",
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


def _match_command_spec(spec: dict, parsed) -> bool:
    """
    Structural match against a parsed shell command (ADR-0005). Keys:
      program      — glob(s); at least one parsed command's program must match
      args_all_of  — every glob must match SOME arg of that command
      args_any_of  — at least one glob must match some arg of that command
      any_program  — glob(s) against every program seen (incl. substitutions/pipes)
      pipes_into   — glob(s) against a non-first stage of any pipeline
    """
    if not isinstance(spec, dict):
        raise _RuleError("'match.command' must be an object")

    if "any_program" in spec:
        pats = _as_patterns(spec["any_program"])
        if not any(_glob_any(p, pats) for p in parsed.programs):
            return False

    if "pipes_into" in spec:
        pats = _as_patterns(spec["pipes_into"])
        if not any(
            _glob_any(prog, pats)
            for pipeline in parsed.pipelines
            for idx, prog in enumerate(pipeline)
            if idx > 0
        ):
            return False

    if "program" in spec:
        prog_pats = _as_patterns(spec["program"])
        all_of = _as_patterns(spec.get("args_all_of", []))
        any_of = _as_patterns(spec.get("args_any_of", []))
        ok = False
        for program, args in parsed.commands:
            if not _glob_any(program, prog_pats):
                continue
            if all_of and not all(
                any(fnmatch.fnmatch(a, pat) for a in args) for pat in all_of
            ):
                continue
            if any_of and not any(_glob_any(a, any_of) for a in args):
                continue
            ok = True
        if not ok:
            return False

    return True


def _match_rule(
    rule: dict,
    req: PolicyDecisionRequest,
    parsed_cmd=None,
    parse_error: str | None = None,
) -> bool:
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

    # command: structural match against the parsed shell command.
    if "command" in match:
        if parse_error:
            # A command string was given but could not be analysed → fail closed.
            raise _RuleError(f"command not analysable: {parse_error}")
        if parsed_cmd is None:
            # No `command` argument on this call — nothing for this rule to match.
            return False
        if not _match_command_spec(match["command"], parsed_cmd):
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
            "deny",
            "Malformed request: missing tool",
            None,
            "raw",
            True,
            fail_closed=True,
        )
    if default_effect not in VALID_EFFECTS:
        return PolicyDecision(
            "deny",
            f"Fail-closed: bad default_effect {default_effect!r}",
            None,
            "raw",
            True,
            fail_closed=True,
        )

    # Parse the shell command once if any rule needs structural matching.
    parsed_cmd = None
    parse_error: str | None = None
    if any(
        isinstance(r, dict)
        and isinstance(r.get("match"), dict)
        and "command" in r["match"]
        for r in ruleset
    ):
        raw_cmd = (req.args or {}).get("command")
        if raw_cmd is not None:
            try:
                from services.command_parser import parse_command

                parsed_cmd = parse_command(str(raw_cmd))
            except Exception as e:  # noqa: BLE001 — any parse failure → fail closed
                parse_error = str(e)

    winner: dict | None = None
    for rule in ruleset:
        try:
            if _match_rule(rule, req, parsed_cmd, parse_error):
                winner = rule
        except _RuleError as e:
            return PolicyDecision(
                "deny",
                f"Fail-closed: bad rule {rule.get('id', '?')}: {e}",
                None,
                "raw",
                True,
                fail_closed=True,
            )
        except Exception as e:  # noqa: BLE001 — fail closed on anything unexpected
            return PolicyDecision(
                "deny",
                f"Fail-closed: rule evaluation error: {e}",
                None,
                "raw",
                True,
                fail_closed=True,
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


VALID_MODES = ("off", "dry_run", "enforce")


def resolve_scope(persona_id: str | None) -> tuple[str | None, str | None, str | None]:
    """persona_id → (company_id, department_id, agent_config_id)."""
    if not persona_id:
        return None, None, None
    try:
        from sqlmodel import select

        from database import get_session
        from models import AgentConfig, Personnel

        with get_session() as session:
            person = session.get(Personnel, persona_id)
            if not person:
                return None, None, None
            cfg = session.exec(
                select(AgentConfig).where(AgentConfig.personnel_id == persona_id)
            ).first()
            return (
                person.company_id,
                person.department_id,
                cfg.id if cfg else None,
            )
    except Exception:
        return None, None, None


def applicable_policy_contents(
    company_id: str | None,
    department_id: str | None,
    agent_config_id: str | None,
) -> list[str]:
    """
    The policy bodies that apply to one agent, gathered the same way
    `agent_runtime.run_session` gathers policy names: company-scoped policies +
    department-linked (DepartmentPolicyLink) + agent-linked (AgentPolicyLink),
    active only, de-duplicated.
    """
    if not company_id:
        return []
    try:
        from sqlmodel import select

        from database import get_session
        from models import AgentPolicyLink, DepartmentPolicyLink, Policy

        contents: list[str] = []
        seen: set[str] = set()

        def _add(rows):
            for p in rows:
                if p.id not in seen and p.is_active and p.content:
                    seen.add(p.id)
                    contents.append(p.content)

        with get_session() as session:
            _add(
                session.exec(
                    select(Policy).where(
                        Policy.company_id == company_id,
                        Policy.scope == "company",
                        Policy.is_active == True,  # noqa: E712
                    )
                ).all()
            )
            if department_id:
                _add(
                    session.exec(
                        select(Policy)
                        .join(
                            DepartmentPolicyLink,
                            DepartmentPolicyLink.policy_id == Policy.id,
                        )
                        .where(DepartmentPolicyLink.department_id == department_id)
                        .where(Policy.is_active == True)  # noqa: E712
                    ).all()
                )
            if agent_config_id:
                _add(
                    session.exec(
                        select(Policy)
                        .join(AgentPolicyLink, AgentPolicyLink.policy_id == Policy.id)
                        .where(AgentPolicyLink.agent_config_id == agent_config_id)
                        .where(Policy.is_active == True)  # noqa: E712
                    ).all()
                )
        return contents
    except Exception:
        return []


def resolve_mode(
    company_id: str | None,
    department_id: str | None,
    agent_config_id: str | None,
) -> tuple[str, Effect]:
    """
    (mode, default_effect), most-specific-wins:
    agent PolicyConfig → department PolicyConfig → company PolicyConfig →
    global AppConfig (policy.mode / policy.default_effect) → hardcoded defaults.
    A null field on a PolicyConfig row inherits from the next level.
    """
    mode: str | None = None
    default_effect: str | None = None

    try:
        from sqlmodel import select

        from database import get_session
        from models import PolicyConfig

        chain: list[tuple[str, str | None]] = [
            ("agent", agent_config_id),
            ("department", department_id),
            ("company", None),
        ]
        with get_session() as session:
            for scope, scope_id in chain:
                if scope != "company" and not scope_id:
                    continue
                q = select(PolicyConfig).where(
                    PolicyConfig.scope == scope,
                    PolicyConfig.company_id == company_id,
                )
                q = (
                    q.where(PolicyConfig.scope_id == scope_id)
                    if scope != "company"
                    else q.where(PolicyConfig.scope_id.is_(None))
                )
                row = session.exec(q).first()
                if row:
                    if mode is None and row.mode:
                        mode = row.mode
                    if default_effect is None and row.default_effect:
                        default_effect = row.default_effect
                if mode and default_effect:
                    break
    except Exception:
        pass

    if mode is None:
        mode = _config("policy.mode", DEFAULT_MODE)
    if default_effect is None:
        default_effect = _config("policy.default_effect", DEFAULT_EFFECT)

    if mode not in VALID_MODES:
        mode = DEFAULT_MODE
    return mode, default_effect


def audit_decision(req: PolicyDecisionRequest, decision: PolicyDecision) -> None:
    """
    Audit one policy decision into the tamper-evident chain (ADR-0005/0006).
    Recorded in every mode, so `dry_run` shows operators what *would* be blocked
    before they flip to `enforce`. Best-effort — never crashes the caller.
    """
    try:
        from services import audit_chain

        audit_chain.record(
            actor_type="agent" if req.source == "workstation" else "system",
            actor_id=req.persona_id,
            company_id=req.company_id,
            action="policy_decision",
            target=req.tool,
            reason=f"{decision.effect} ({decision.mode})",
            payload={
                **decision.as_dict(),
                "source": req.source,
                "provenance": req.provenance,
                "session_ref": req.session_ref,
            },
        )
    except Exception:
        pass


def decide(req: PolicyDecisionRequest) -> PolicyDecision:
    """
    Resolve scope + mode + the applicable ruleset for this persona, evaluate, and
    set real enforcement.

    A fail-closed verdict (bad rule / malformed request / bad default_effect)
    blocks in every mode, `dry_run` included. A clean matched deny/ask is only
    applied in `enforce`.
    """
    # Fill scope from the persona when the caller did not supply it.
    if req.persona_id and not (
        req.company_id and req.department_id and req.agent_config_id
    ):
        c, d, a = resolve_scope(req.persona_id)
        req.company_id = req.company_id or c
        req.department_id = req.department_id or d
        req.agent_config_id = req.agent_config_id or a

    mode, default_effect = resolve_mode(
        req.company_id, req.department_id, req.agent_config_id
    )

    if mode == "off":
        return PolicyDecision("allow", "Policy engine off", None, "off", False)

    ruleset = load_ruleset(
        applicable_policy_contents(
            req.company_id, req.department_id, req.agent_config_id
        )
    )

    raw = evaluate(req, ruleset, default_effect=default_effect)
    enforced = raw.fail_closed or (mode == "enforce" and raw.effect != "allow")
    return PolicyDecision(
        effect=raw.effect,
        reason=raw.reason,
        matched_rule=raw.matched_rule,
        mode=mode,
        enforced=enforced,
        fail_closed=raw.fail_closed,
    )
