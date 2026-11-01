"""ADR-0026 gate: execute_skill must not run a tool when policy cannot decide
or when an enforcing decision cannot be audited."""

import asyncio
from types import SimpleNamespace

import pytest

import api.mcp_server as mcp
import services.agent_runtime as rt
import services.policy_engine as pe


def _skill():
    return SimpleNamespace(
        name="probe",
        skill_type="builtin",
        config_json='{"function_name": "probe_fn"}',
    )


@pytest.fixture
def ran(monkeypatch):
    calls = []

    async def fake_builtin(fn, args, session_id=None, agent_id=None):
        calls.append(fn)
        return "ran"

    monkeypatch.setattr(rt, "execute_builtin", fake_builtin)
    return calls


def _run():
    return asyncio.run(rt.execute_skill("probe", {}, [_skill()], agent_id="p1"))


def _decision(effect="allow", mode="dry_run", enforced=False):
    return pe.PolicyDecision(effect, "r", None, mode, enforced)


def test_engine_exception_blocks_tool(monkeypatch, ran):
    def boom(req):
        raise RuntimeError("engine down")

    monkeypatch.setattr(pe, "decide", boom)
    out = _run()
    assert "Policy unavailable" in out
    assert ran == []


def test_enforce_mode_audit_failure_blocks_tool(monkeypatch, ran):
    monkeypatch.setattr(pe, "decide", lambda r: _decision(mode="enforce"))
    monkeypatch.setattr(pe, "audit_decision", lambda r, d: False)
    out = _run()
    assert "audit unavailable" in out
    assert ran == []


@pytest.mark.parametrize("mode", ["off", "dry_run", "enforce"])
def test_audit_failure_blocks_in_every_mode(monkeypatch, ran, mode):
    monkeypatch.setattr(pe, "decide", lambda r: _decision(mode=mode))
    monkeypatch.setattr(pe, "audit_decision", lambda r, d: False)
    assert "audit unavailable" in _run()
    assert ran == []


def test_enforced_deny_blocks_tool(monkeypatch, ran):
    monkeypatch.setattr(
        pe, "decide", lambda r: _decision("deny", "enforce", enforced=True)
    )
    monkeypatch.setattr(pe, "audit_decision", lambda r, d: True)
    assert "Policy denied" in _run()
    assert ran == []


def test_healthy_allow_runs_tool(monkeypatch, ran):
    monkeypatch.setattr(pe, "decide", lambda r: _decision(mode="enforce"))
    monkeypatch.setattr(pe, "audit_decision", lambda r, d: True)
    assert _run() == "ran"


def test_audit_decision_returns_false_when_record_raises(monkeypatch):
    import services.audit_chain as ac

    def boom(**kw):
        raise OSError("disk full")

    monkeypatch.setattr(ac, "record", boom)
    req = pe.PolicyDecisionRequest(tool="x", args={})
    assert pe.audit_decision(req, _decision()) is False


def test_audit_decision_false_when_record_returns_none(monkeypatch):
    import services.audit_chain as ac

    monkeypatch.setattr(ac, "record", lambda **kw: None)
    req = pe.PolicyDecisionRequest(tool="x", args={})
    assert pe.audit_decision(req, _decision()) is False


def test_real_append_failure_blocks_tool(monkeypatch, ran, db_session):
    """Real decide -> real audit_decision -> real record; only the append fails."""
    import services.audit_chain as ac
    from tests.conftest import make_company, make_personnel

    co = make_company(db_session)
    persona = make_personnel(db_session, co.id)
    db_session.commit()

    def disk_full(**kw):
        raise OSError("disk full")

    monkeypatch.setattr(ac, "append", disk_full)
    out = asyncio.run(rt.execute_skill("probe", {}, [_skill()], agent_id=persona.id))
    assert "audit unavailable" in out
    assert ran == []


def test_real_chain_healthy_runs_tool_once(ran, db_session):
    from tests.conftest import make_company, make_personnel

    co = make_company(db_session)
    persona = make_personnel(db_session, co.id)
    db_session.commit()
    out = asyncio.run(rt.execute_skill("probe", {}, [_skill()], agent_id=persona.id))
    assert out == "ran"
    assert ran == ["probe_fn"]


# ── policy resolution failures are not "no policy" ───────────────────────────


def _db_down(monkeypatch):
    import database

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(database, "get_session", boom)


def test_decide_denies_when_policy_config_unreadable(monkeypatch):
    _db_down(monkeypatch)
    d = pe.decide(pe.PolicyDecisionRequest(tool="probe", persona_id="p1"))
    assert (d.effect, d.enforced, d.fail_closed) == ("deny", True, True)


def test_tool_blocked_when_policy_unresolvable(monkeypatch, ran):
    _db_down(monkeypatch)
    monkeypatch.setattr(pe, "audit_decision", lambda r, d: True)
    assert "Policy denied" in _run()
    assert ran == []


def test_invalid_mode_is_an_error_not_dry_run(monkeypatch):
    monkeypatch.setattr(pe, "_config", lambda k, f: "bogus" if "mode" in k else f)
    with pytest.raises(pe.PolicyResolutionError):
        pe.resolve_mode(None, None, None)


# ── malformed executable policy blocks ───────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        "```policy\n[{broken\n```",
        '```policy\n{"match":{"tool":"probe"},"effect":"deny"}\n```',
        '```policy\n["not-a-rule"]\n```',
        '```json\n["not-a-rule"]\n```',
    ],
)
def test_malformed_policy_block_fails_closed(body):
    rules = pe.load_ruleset([body])
    d = pe.evaluate(
        pe.PolicyDecisionRequest(tool="probe"), rules, default_effect="allow"
    )
    assert d.effect == "deny" and d.fail_closed


def test_illustrative_unparseable_json_fence_is_still_ignored():
    rules = pe.load_ruleset(["```json\n{not json at all\n```"])
    d = pe.evaluate(
        pe.PolicyDecisionRequest(tool="probe"), rules, default_effect="allow"
    )
    assert d.effect == "allow"


# ── flow runner goes through the same gate ───────────────────────────────────


def test_flow_tool_blocked_by_policy(monkeypatch):
    import services.flow_runner as fr
    import services.mcp_client as mc

    called = []

    async def spy(*a, **k):
        called.append(a)
        return "searched"

    monkeypatch.setattr(mc, "execute_builtin", spy)
    monkeypatch.setattr(
        pe, "decide", lambda r: _decision("deny", "enforce", enforced=True)
    )
    monkeypatch.setattr(pe, "audit_decision", lambda r, d: True)
    assert "Policy denied" in fr._execute_flow_tool("web_search", {"q": "x"}, "p1")
    assert called == []


def test_flow_tool_blocked_when_audit_down(monkeypatch):
    import services.flow_runner as fr
    import services.mcp_client as mc

    called = []

    async def spy(*a, **k):
        called.append(a)
        return "searched"

    monkeypatch.setattr(mc, "execute_builtin", spy)
    monkeypatch.setattr(pe, "decide", lambda r: _decision(mode="dry_run"))
    monkeypatch.setattr(pe, "audit_decision", lambda r, d: False)
    assert "audit unavailable" in fr._execute_flow_tool("web_search", {"q": "x"}, "p1")
    assert called == []


# ── persona not found / stale principal ──────────────────────────────────────


def test_unknown_persona_is_resolution_error():
    with pytest.raises(pe.PolicyResolutionError):
        pe.resolve_scope("does-not-exist")


def test_no_persona_means_no_scope_not_an_error():
    assert pe.resolve_scope(None) == (None, None, None)


def test_decide_denies_unknown_persona(ran):
    d = pe.decide(pe.PolicyDecisionRequest(tool="probe", persona_id="ghost"))
    assert (d.effect, d.enforced, d.fail_closed) == ("deny", True, True)


def test_tool_blocked_for_unknown_persona(ran):
    out = asyncio.run(rt.execute_skill("probe", {}, [_skill()], agent_id="ghost"))
    assert "Policy denied" in out
    assert ran == []


def test_persona_without_department_still_resolves(db_session):
    from tests.conftest import make_company, make_personnel

    co = make_company(db_session)
    p = make_personnel(db_session, co.id)
    db_session.commit()
    c, d, a = pe.resolve_scope(p.id)
    assert c == co.id and d is None and a is None


# ── each resolver stage fails independently ──────────────────────────────────


def test_mode_read_failure_alone_denies(monkeypatch):
    monkeypatch.setattr(pe, "resolve_scope", lambda pid: ("c", "d", "a"))

    def boom(*a, **k):
        raise pe.PolicyResolutionError("config down")

    monkeypatch.setattr(pe, "resolve_mode", boom)
    d = pe.decide(pe.PolicyDecisionRequest(tool="probe", persona_id="p1"))
    assert d.enforced and d.fail_closed and d.mode == "unresolved"


def test_policy_read_failure_alone_denies_even_in_enforce(monkeypatch):
    monkeypatch.setattr(pe, "resolve_scope", lambda pid: ("c", "d", "a"))
    monkeypatch.setattr(pe, "resolve_mode", lambda c, d, a: ("enforce", "allow"))

    def boom(*a, **k):
        raise pe.PolicyResolutionError("policies down")

    monkeypatch.setattr(pe, "applicable_policy_contents", boom)
    d = pe.decide(pe.PolicyDecisionRequest(tool="probe", persona_id="p1"))
    assert d.enforced and d.fail_closed


# ── unterminated / rule-like fences ──────────────────────────────────────────


def _verdict(body):
    rules = pe.load_ruleset([body])
    return pe.evaluate(
        pe.PolicyDecisionRequest(tool="probe"), rules, default_effect="allow"
    )


@pytest.mark.parametrize(
    "body",
    [
        "```policy\n[{broken",
        '```policy\n[{"match": {"tool": "probe"}, "effect": "deny"}]',
        '```json\n[{"match": {"tool": "probe"}, "effect": "deny"}',
        '```json\n[{broken, "effect": "deny"\n```',
        "```yaml\n- match: [broken\n  effect: deny\n```",
        "intro\n```policy\n[]\n```\nlater\n```policy\n[{x",
    ],
)
def test_unterminated_or_broken_rule_blocks_fail_closed(body):
    v = _verdict(body)
    assert v.effect == "deny" and v.fail_closed


def test_well_formed_blocks_still_work():
    body = (
        'text\n```policy\n[{"id": "r", "match": {"tool": "probe"}, '
        '"effect": "deny", "reason": "no"}]\n```\nmore\n```json\n{"a": 1}\n```'
    )
    v = _verdict(body)
    assert v.effect == "deny" and not v.fail_closed and v.matched_rule == "r"


def test_prose_json_without_rule_shape_is_ignored():
    assert _verdict("```json\n{oops, not json\n```").effect == "allow"


# ── MCP org_policies passes the same gate ────────────────────────────────────


def _mcp_org_policies():
    principal = SimpleNamespace(persona_id="p1", company_id="c1")
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "org_policies", "arguments": {}},
    }
    return asyncio.run(mcp._handle(msg, principal))["result"]


def test_org_policies_blocked_by_policy(monkeypatch):
    monkeypatch.setattr(
        pe, "decide", lambda r: _decision("deny", "enforce", enforced=True)
    )
    monkeypatch.setattr(pe, "audit_decision", lambda r, d: True)
    monkeypatch.setattr(mcp, "applicable_policy_contents", lambda *a: ["SECRET"])
    monkeypatch.setattr(mcp, "resolve_scope", lambda pid: ("c", None, None))
    r = _mcp_org_policies()
    assert r.get("isError") and "SECRET" not in str(r)


def test_org_policies_blocked_when_audit_down(monkeypatch):
    monkeypatch.setattr(pe, "decide", lambda r: _decision(mode="dry_run"))
    monkeypatch.setattr(pe, "audit_decision", lambda r, d: False)
    monkeypatch.setattr(mcp, "applicable_policy_contents", lambda *a: ["SECRET"])
    monkeypatch.setattr(mcp, "resolve_scope", lambda pid: ("c", None, None))
    r = _mcp_org_policies()
    assert r.get("isError") and "SECRET" not in str(r)


def test_org_policies_unknown_persona_is_error(monkeypatch):
    monkeypatch.setattr(pe, "audit_decision", lambda r, d: True)
    r = _mcp_org_policies()
    assert r.get("isError")
    assert "No policies apply" not in str(r)


# ── API contract: 503, not 500 ───────────────────────────────────────────────


def test_policy_resolution_error_maps_to_503():
    import main

    resp = asyncio.run(main._policy_unresolved(None, pe.PolicyResolutionError("x")))
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "5"
    body = resp.body.decode()
    assert "policy_unavailable" in body and "error_id" in body
    assert "x" not in body.replace("policy_unavailable", "").replace("error_id", "")


# ── fence contract (Codex round 3 matrix) ────────────────────────────────────

_DENY = '[{"id": "r", "match": {"tool": "probe"}, "effect": "deny", "reason": "no"}]'


def _fenced(info, body, ticks="```", nl="\n"):
    return f"{ticks}{info}{nl}{body}{nl}{ticks}"


def _is_rule_deny(body):
    v = _verdict(body)
    return v.effect == "deny" and not v.fail_closed and v.matched_rule == "r"


@pytest.mark.parametrize("nl", ["\n", "\r\n"])
@pytest.mark.parametrize("info", ["policy", "Policy", "POLICY", "json", "JSON"])
def test_valid_rule_list_executes_for_any_case_and_newline(info, nl):
    assert _is_rule_deny(_fenced(info, _DENY, nl=nl))


def test_four_backtick_block_with_matching_closer_executes():
    assert _is_rule_deny(_fenced("policy", _DENY, ticks="````"))


def test_four_backtick_opener_with_short_closer_is_unterminated():
    v = _verdict("````policy\n" + _DENY + "\n```")
    assert v.effect == "deny" and v.fail_closed


def test_example_inside_outer_text_fence_is_not_executed():
    body = "````text\n" + _fenced("policy", _DENY) + "\n````"
    assert _verdict(body).effect == "allow"


def test_backticks_inside_json_string_do_not_close_block():
    rule = '[{"id": "r", "match": {"tool": "probe"}, "effect": "deny", "reason": "a ``` b"}]'
    assert _is_rule_deny(_fenced("policy", rule))


@pytest.mark.parametrize(
    "body",
    [
        '{"match": {"tool": "probe"}, "effect": "deny"}',
        '{"\\u0065ffect": "deny", "match": {"tool": "probe"}}',
    ],
)
def test_rule_object_outside_a_list_fails_closed(body):
    for fence in ("json", "yaml"):
        v = _verdict(_fenced(fence, body))
        assert v.effect == "deny" and v.fail_closed, fence


def test_yaml_dict_root_fails_closed():
    v = _verdict(_fenced("yaml", "match: {tool: probe}\neffect: deny"))
    assert v.effect == "deny" and v.fail_closed


def test_yaml_list_of_rules_executes():
    assert _is_rule_deny(
        _fenced("yaml", "- id: r\n  match: {tool: probe}\n  effect: deny\n  reason: no")
    )


def test_oversized_block_is_malformed():
    big = (
        "["
        + ",".join(['{"id":"x","match":{"tool":"zzz"},"effect":"allow"}'] * 2000)
        + "]"
    )
    assert len(big) > pe.MAX_POLICY_BLOCK_BYTES
    v = _verdict(_fenced("policy", big))
    assert v.effect == "deny" and v.fail_closed


def test_prose_with_effect_word_is_not_a_rule():
    assert (
        _verdict("```json\n{note: the sideeffect: is documented\n```").effect == "allow"
    )


def test_validate_policy_content_reports_problems():
    assert pe.validate_policy_content(_fenced("policy", _DENY)) == []
    assert pe.validate_policy_content("```policy\n[{broken\n```")


# ── bad policies are refused at save time ────────────────────────────────────


def test_save_time_guard_rejects_malformed_policy():
    from fastapi import HTTPException

    from api.policies import _reject_malformed

    _reject_malformed("plain prose")
    _reject_malformed(_fenced("policy", _DENY))
    with pytest.raises(HTTPException) as e:
        _reject_malformed("```policy\n[{broken\n```")
    assert e.value.status_code == 422
