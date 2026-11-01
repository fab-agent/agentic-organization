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


def test_dry_run_audit_failure_still_runs(monkeypatch, ran):
    monkeypatch.setattr(pe, "decide", lambda r: _decision(mode="dry_run"))
    monkeypatch.setattr(pe, "audit_decision", lambda r, d: False)
    assert _run() == "ran"
    assert ran == ["probe_fn"]


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


def test_audit_decision_returns_false_when_chain_fails(monkeypatch):
    import services.audit_chain as ac

    def boom(**kw):
        raise OSError("disk full")

    monkeypatch.setattr(ac, "record", boom)
    req = pe.PolicyDecisionRequest(tool="x", args={})
    assert pe.audit_decision(req, _decision()) is False
