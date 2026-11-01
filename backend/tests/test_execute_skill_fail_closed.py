"""ADR-0026 gate: execute_skill must not run a tool when policy cannot decide
or when an enforcing decision cannot be audited."""

import asyncio
from types import SimpleNamespace

import pytest

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


def test_real_append_failure_blocks_tool(monkeypatch, ran):
    """Real decide -> real audit_decision -> real record; only append fails."""
    import services.audit_chain as ac

    def disk_full(**kw):
        raise OSError("disk full")

    monkeypatch.setattr(ac, "append", disk_full)
    monkeypatch.setattr(pe, "decide", lambda r: _decision(mode="enforce"))
    assert "audit unavailable" in _run()
    assert ran == []


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
