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
    # Attribution block from the caller's *verified* token (gateway_auth.run_info);
    # lets diagnosis join a decision to its run without trusting session_ref.
    run: dict[str, Any] | None = None


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
            if not isinstance(key_glob, str):
                raise _RuleError("'match.args' keys must be text")
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


class PolicyResolutionError(Exception):
    """The policy scope/mode/ruleset could not be *read* (not "nothing found").
    `decide()` turns it into an enforced fail-closed deny in every mode (ADR-0026)."""


# A rule no evaluator accepts: any matching request is denied fail-closed.
def _malformed_block_rule(why: str) -> dict:
    return {
        "id": "malformed-policy-block",
        "match": {"tool": "*"},
        "effect": "__malformed__",
        "reason": f"Fail-closed: malformed policy block ({why})",
    }


# ── Ruleset loading ──────────────────────────────────────────────────────────


MAX_POLICY_BLOCK_BYTES = 64 * 1024  # one executable block; bounds parse cost
MAX_POLICY_DOC_BYTES = 1024 * 1024  # a whole policy document
MAX_POLICY_RULES = 500
_EXECUTABLE_FENCES = ("policy", "json", "yaml")


def _backtick_run(line: str) -> tuple[int, str]:
    """(count, rest) for a line that starts with up to 3 spaces + backticks.
    Single linear pass; no regex, so no backtracking on hostile input."""
    i = 0
    while i < len(line) and i < 3 and line[i] == " ":
        i += 1
    j = i
    while j < len(line) and line[j] == "`":
        j += 1
    return j - i, line[j:]


def _tokenize_fences(text: str):
    """
    Yield `(info, body, terminated)` for each top-level fenced block, CommonMark
    style: an opener is a line of >=3 backticks (at most 3 spaces of indent) plus
    an info string without backticks; the closer is a line of >=as many backticks
    and nothing else. Backticks inside a line (e.g. in a JSON string) never close
    a block, and a block opened by a non-executable info string (```text, a longer
    outer fence) swallows its content, so documentation examples are not executed.
    Only backtick fences are recognised (no tilde fences, list or quote context).
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        n, rest = _backtick_run(lines[i])
        if n < 3 or "`" in rest:
            i += 1
            continue
        words = rest.split()
        info = words[0].lower() if words else ""
        j = i + 1
        while j < len(lines):
            m, tail = _backtick_run(lines[j])
            if m >= n and not tail.strip():
                break
            j += 1
        terminated = j < len(lines)
        yield info, "\n".join(lines[i + 1 : j]), terminated
        i = j + 1


def _rule_schema_problem(rule: dict) -> str | None:
    """Static check of everything `_match_rule` can raise on, independent of any
    request (so a short-circuit cannot hide a bad field). Mirrors its semantics:
    `args_*_of` are only evaluated, hence only checked, when `program` is present."""
    try:
        if "match" not in rule or "effect" not in rule:
            raise _RuleError("rule needs 'match' and 'effect'")
        if rule["effect"] not in VALID_EFFECTS:
            raise _RuleError("invalid effect")
        match = rule["match"]
        if not isinstance(match, dict):
            raise _RuleError("'match' must be an object")
        if "tool" in match:
            _as_patterns(match["tool"])
        arg_spec = match.get("args")
        if arg_spec:
            if not isinstance(arg_spec, dict):
                raise _RuleError("'match.args' must be an object")
            for key, pat in arg_spec.items():
                if not isinstance(key, str):
                    raise _RuleError("'match.args' keys must be text")
                _as_patterns(pat)
        if "command" in match:
            spec = match["command"]
            if not isinstance(spec, dict):
                raise _RuleError("'match.command' must be an object")
            keys = ["any_program", "pipes_into", "program"]
            if "program" in spec:
                keys += ["args_all_of", "args_any_of"]
            for k in keys:
                if k in spec:
                    _as_patterns(spec[k])
    except _RuleError as e:
        return str(e)
    return None


def _parse_block(body: str) -> tuple[bool, Any]:
    """`(ok, value)`: JSON first, then YAML. ok=False means neither parses."""
    try:
        return True, json.loads(body)
    except json.JSONDecodeError:
        pass
    try:
        import yaml  # PyYAML is already a backend dependency

        return True, yaml.safe_load(body)
    except Exception:
        return False, None


def parse_policy_content(content: str) -> tuple[list[dict], list[str]]:
    """
    `(rules, problems)` from a Policy body. Contract (ADR-0026):

    - Fences ```policy, ```json and ```yaml are executable (info string is
      case-insensitive). Prose and examples belong in ```text (or any other info
      string), which is never executed.
    - An executable block must be closed and must parse (JSON, else YAML). It is a
      problem when unterminated, unparseable, a non-object rule in a list, or a
      rule-shaped object (has `match`/`effect`) outside a list; a ```policy block
      must also be a list. Parsed JSON/YAML that is not rule-shaped (a prose
      object, a scalar, an empty block) contributes no rules and no problem.
    - There is no "does it look like a rule" guess: unparseable means problem.
    - Limits: document, block and rule count (bounds evaluation cost).
    Problems are typed separately from user rules, so a user rule id can never
    be mistaken for a parse error.
    """
    rules: list[dict] = []
    problems: list[str] = []
    text = content or ""
    if len(text.encode("utf-8", "ignore")) > MAX_POLICY_DOC_BYTES:
        return rules, ["policy document too large"]
    for fence, body, terminated in _tokenize_fences(text):
        if fence not in _EXECUTABLE_FENCES:
            continue
        body = body.lstrip(
            "\ufeff"
        ).strip()  # leading BOM only; never touch string data
        if len(body.encode("utf-8", "ignore")) > MAX_POLICY_BLOCK_BYTES:
            problems.append("block too large")
            continue
        if not terminated:
            problems.append("unterminated block")
            continue
        ok, parsed = _parse_block(body)
        if not ok:
            problems.append("unparseable block")
        elif isinstance(parsed, list):
            for r in parsed:
                if isinstance(r, dict):
                    rules.append(r)
                else:
                    problems.append("non-object rule")
        elif fence == "policy" and parsed is not None:
            problems.append("not a list of rules")
        elif fence == "policy":
            pass  # empty ```policy block: no rules
        elif isinstance(parsed, dict) and ("match" in parsed or "effect" in parsed):
            problems.append("rule object outside a list")
    if len(rules) > MAX_POLICY_RULES:
        problems.append("too many rules")
    return rules, problems


def _parse_rules_from_markdown(content: str) -> list[dict]:
    """Rules for the evaluator: user rules plus one fail-closed sentinel per
    problem, so a broken policy denies instead of silently losing rules."""
    rules, problems = parse_policy_content(content)
    return [*rules, *(_malformed_block_rule(p) for p in problems)]


def validate_policy_content(content: str) -> list[str]:
    """Problems that would make the policy fail closed at runtime, found without
    evaluating it; empty = fine. Used to reject a bad policy when it is saved."""
    rules, problems = parse_policy_content(content)
    for i, r in enumerate(rules, 1):
        why = _rule_schema_problem(r)
        if why:
            # Index, not id/value: problems must never echo policy text.
            problems.append(f"rule #{i}: {why}")
    return problems


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
    except Exception as e:
        raise PolicyResolutionError(f"config read failed: {key}") from e


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
                # A persona was named but does not exist: not "no scope" — never
                # fall back to global defaults for an unknown/stale principal.
                raise PolicyResolutionError("persona not found")
            cfg = session.exec(
                select(AgentConfig).where(AgentConfig.personnel_id == persona_id)
            ).first()
            return (
                person.company_id,
                person.department_id,
                cfg.id if cfg else None,
            )
    except Exception as e:
        raise PolicyResolutionError("scope read failed") from e


def _department_chain(session, department_id: str | None) -> list[str]:
    """
    [department, parent, grandparent, …] — most-specific first. Cycle-safe,
    depth-capped. Used so a sub-department inherits its parents' policies
    (ADR-0005).
    """
    if not department_id:
        return []
    from models import Department

    chain: list[str] = []
    seen: set[str] = set()
    cur: str | None = department_id
    for _ in range(16):
        if not cur or cur in seen:
            break
        seen.add(cur)
        chain.append(cur)
        dept = session.get(Department, cur)
        cur = dept.parent_id if dept else None
    return chain


def applicable_policies(
    company_id: str | None,
    department_id: str | None,
    agent_config_id: str | None,
) -> list[tuple[str, str]]:
    """
    `(name, body)` of the policies that apply to one agent: company-scoped policies +
    department-linked (DepartmentPolicyLink) for the department **and every
    ancestor** (ADR-0005) + agent-linked (AgentPolicyLink), active only,
    de-duplicated. Ordered least→most specific so the more-specific rule wins
    under the ruleset's last-match-wins.
    """
    if not company_id:
        return []
    try:
        from sqlmodel import select

        from database import get_session
        from models import AgentPolicyLink, DepartmentPolicyLink, Policy

        found: list[tuple[str, str]] = []
        seen: set[str] = set()

        def _add(rows):
            for p in rows:
                if p.id not in seen and p.is_active and p.content:
                    seen.add(p.id)
                    found.append((p.name, p.content))

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
            # ancestors first, then the agent's own department (most specific last)
            for dept_id in reversed(_department_chain(session, department_id)):
                _add(
                    session.exec(
                        select(Policy)
                        .join(
                            DepartmentPolicyLink,
                            DepartmentPolicyLink.policy_id == Policy.id,
                        )
                        .where(DepartmentPolicyLink.department_id == dept_id)
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
        return found
    except Exception as e:
        raise PolicyResolutionError("policy read failed") from e


def applicable_policy_contents(
    company_id: str | None,
    department_id: str | None,
    agent_config_id: str | None,
) -> list[str]:
    """The bodies of `applicable_policies` — what the engine enforces."""
    return [
        body
        for _, body in applicable_policies(company_id, department_id, agent_config_id)
    ]


def resolve_mode(
    company_id: str | None,
    department_id: str | None,
    agent_config_id: str | None,
) -> tuple[str, Effect]:
    """
    (mode, default_effect), most-specific-wins:
    agent PolicyConfig → department PolicyConfig → company PolicyConfig →
    global AppConfig (policy.mode / policy.default_effect) → hardcoded defaults.
    A null field on a PolicyConfig row inherits from the next level. The
    department step walks the parent chain (sub-dept → parent → …, ADR-0005).
    """
    mode: str | None = None
    default_effect: str | None = None

    try:
        from sqlmodel import select

        from database import get_session
        from models import PolicyConfig

        with get_session() as session:
            chain: list[tuple[str, str | None]] = [("agent", agent_config_id)]
            chain += [
                ("department", d) for d in _department_chain(session, department_id)
            ]
            chain.append(("company", None))
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
    except Exception as e:
        raise PolicyResolutionError("policy config read failed") from e

    if mode is None:
        mode = _config("policy.mode", DEFAULT_MODE)
    if default_effect is None:
        default_effect = _config("policy.default_effect", DEFAULT_EFFECT)

    if mode not in VALID_MODES:
        raise PolicyResolutionError(f"invalid policy mode: {mode!r}")
    return mode, default_effect


def audit_decision(req: PolicyDecisionRequest, decision: PolicyDecision) -> bool:
    """
    Audit one policy decision into the tamper-evident chain (ADR-0005/0006).
    Recorded in every mode, so `dry_run` shows operators what *would* be blocked
    before they flip to `enforce`. Never raises. Returns False when the record
    could not be written, so a caller that must not act without an audit trail
    (enforce mode, ADR-0026) can refuse instead of continuing.
    """
    try:
        from services import audit_chain

        ev = audit_chain.record(
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
                **({"run": req.run} if req.run else {}),
            },
        )
        # record() swallows append errors and returns None (audit_chain.py).
        return ev is not None
    except Exception:
        return False


def decide(req: PolicyDecisionRequest) -> PolicyDecision:
    """
    Resolve scope + mode + the applicable ruleset for this persona, evaluate, and
    set real enforcement.

    A fail-closed verdict (bad rule / malformed request / bad default_effect)
    blocks in every mode, `dry_run` included. A clean matched deny/ask is only
    applied in `enforce`.
    """
    try:
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
    except PolicyResolutionError as e:
        # "could not read the policy" is not "no policy": block in every mode.
        return PolicyDecision(
            "deny",
            f"Fail-closed: policy could not be resolved ({e})",
            None,
            "unresolved",
            True,
            fail_closed=True,
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
