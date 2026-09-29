"""
Run tokens for subagents (ADR-0019 §3-4): narrowing-only derivation, depth cap,
revocation, and attribution of audit events from the *verified* token.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

import models
from services import audit_chain
from services.gateway_auth import (
    PersonaPrincipal,
    create_persona_refresh_token,
    create_persona_token,
    create_run_token,
    decode_persona_token,
    sanitize_role,
)
from services.persona_revocation import revoke_all
from tests.test_workspaces import _create, rt, world  # noqa: F401 (fixtures)

# ── helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def root(world, rt):
    """The alice-workspace agent persona and a root (depth 0) persona token."""
    agent_id = _create(world).json()["agent_persona_id"]
    r = world["client"].post(
        "/workstation/persona-token", json={"personnel_id": agent_id}
    )
    tok = r.json()["token"]
    return {
        "client": world["client"],
        "persona": agent_id,
        "company": world["co"].id,
        "token": tok,
        "refresh": r.json()["refresh_token"],
    }


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _mint(root, parent_token, role=None):
    return root["client"].post(
        "/workstation/run-token",
        json={"role": role} if role is not None else {},
        headers=_bearer(parent_token),
    )


def _events(db_session, action):
    db_session.expire_all()
    rows = db_session.exec(
        select(models.AuditEvent).where(models.AuditEvent.action == action)
    ).all()
    return [json.loads(r.payload_json) if r.payload_json else {} for r in rows]


# ── derivation ────────────────────────────────────────────────────────────────


def test_run_token_is_the_same_persona_one_level_deeper(root):
    r = _mint(root, root["token"], "sales analysis")
    assert r.status_code == 201
    body = r.json()
    p = decode_persona_token(body["token"], "gateway")
    assert p.persona_id == root["persona"] and p.company_id == root["company"]
    assert (p.depth, p.parent_run_id, p.role) == (1, None, "sales analysis")
    assert p.run_id == body["run_id"] and len(p.run_id) == 32
    assert (
        decode_persona_token(body["token"], "audit").run_id == p.run_id
    )  # both audiences


def test_nested_runs_link_to_their_parent(root):
    d1 = _mint(root, root["token"], "analysis").json()
    d2 = _mint(root, d1["token"], "chart").json()
    p2 = decode_persona_token(d2["token"], "gateway")
    assert (p2.depth, p2.parent_run_id) == (2, d1["run_id"])
    assert p2.run_id not in (d1["run_id"], None)


def test_depth_is_capped(root, monkeypatch):
    d1 = _mint(root, root["token"]).json()
    d2 = _mint(root, d1["token"]).json()
    r = _mint(root, d2["token"])
    assert r.status_code == 403 and "depth" in r.json()["detail"]

    monkeypatch.setenv("RUN_MAX_DEPTH", "3")
    assert _mint(root, d2["token"]).status_code == 201

    monkeypatch.setenv("RUN_MAX_DEPTH", "0")  # subagents disabled entirely
    assert _mint(root, root["token"]).status_code == 403


def test_bad_depth_setting_falls_back_to_the_default(root, monkeypatch):
    monkeypatch.setenv("RUN_MAX_DEPTH", "banana")
    d1 = _mint(root, root["token"]).json()
    assert _mint(root, d1["token"]).status_code == 201


def test_a_run_never_outlives_its_parent():
    now = datetime.utcnow()
    parent = PersonaPrincipal("p", "c", None, expires_at=now + timedelta(minutes=5))
    token, run = create_run_token(parent)  # default ttl is 60 min
    assert 0 < run["expires_in"] <= 5 * 60
    child = decode_persona_token(token, "gateway")
    assert child.expires_at <= parent.expires_at + timedelta(seconds=1)


def test_an_expired_parent_cannot_spawn():
    parent = PersonaPrincipal(
        "p", "c", None, expires_at=datetime.utcnow() - timedelta(seconds=1)
    )
    with pytest.raises(ValueError, match="expired"):
        create_run_token(parent)


def test_scope_and_company_are_inherited_not_chosen():
    parent = PersonaPrincipal(
        "p", "c", "read-only", expires_at=datetime.utcnow() + timedelta(hours=1)
    )
    child = decode_persona_token(create_run_token(parent)[0], "gateway")
    assert (child.persona_id, child.company_id, child.scope) == ("p", "c", "read-only")


def test_only_a_valid_access_token_can_spawn(root):
    assert root["client"].post("/workstation/run-token", json={}).status_code in (
        401,
        422,
    )
    assert _mint(root, "not-a-token").status_code == 401
    # a refresh token has the wrong audience/type and must not work
    assert _mint(root, root["refresh"]).status_code == 401
    # nor the web session JWT
    assert root["client"].post("/workstation/run-token", json={}).status_code != 201


# ── role label ────────────────────────────────────────────────────────────────


def test_role_is_sanitised():
    assert sanitize_role("  sales\n\tanalysis\x00  ") == "sales analysis"
    assert sanitize_role("x" * 500) == "x" * 80
    assert sanitize_role("") is None and sanitize_role(None) is None
    assert sanitize_role("\x00\x01") is None


def test_role_over_the_request_limit_is_rejected(root):
    assert _mint(root, root["token"], "x" * 501).status_code == 422


# ── revocation ────────────────────────────────────────────────────────────────


def test_revoking_the_persona_kills_its_run_tokens(root):
    run = _mint(root, root["token"]).json()["token"]
    ok = root["client"].post(
        "/workstation/tool-event",
        json={"phase": "before", "tool": "bash"},
        headers=_bearer(run),
    )
    assert ok.status_code == 202

    revoke_all(root["persona"], root["company"], "laptop lost")
    dead = root["client"].post(
        "/workstation/tool-event",
        json={"phase": "before", "tool": "bash"},
        headers=_bearer(run),
    )
    assert dead.status_code == 401
    assert _mint(root, run).status_code == 401  # and it cannot spawn either


# ── attribution comes from the verified token ─────────────────────────────────


def test_run_start_is_audited_with_its_parent(root, db_session):
    d1 = _mint(root, root["token"], "analysis").json()
    d2 = _mint(root, d1["token"], "chart").json()
    starts = _events(db_session, "run_start")
    assert [e["run"]["depth"] for e in starts] == [1, 2]
    assert starts[1]["run"]["parent_run_id"] == d1["run_id"]
    assert starts[1]["run"]["run_id"] == d2["run_id"]
    assert starts[1]["run"]["role"] == "chart"
    assert audit_chain.verify(root["company"])["ok"] is True


def test_tool_events_carry_the_run_only_when_the_token_does(root, db_session):
    ev = {"phase": "before", "tool": "bash"}
    run = _mint(root, root["token"], "analysis").json()
    root["client"].post(
        "/workstation/tool-event", json=ev, headers=_bearer(root["token"])
    )
    root["client"].post(
        "/workstation/tool-event", json=ev, headers=_bearer(run["token"])
    )
    plain, attributed = _events(db_session, "tool_event")
    assert "run" not in plain
    assert attributed["run"] == {
        "run_id": run["run_id"],
        "parent_run_id": None,
        "depth": 1,
        "role": "analysis",
    }
    assert audit_chain.verify(root["company"])["ok"] is True


def test_a_client_cannot_claim_a_run_in_a_tool_event(root, db_session):
    spoof = {"phase": "before", "tool": "bash", "extra": {"run": {"run_id": "fake"}}}
    root["client"].post(
        "/workstation/tool-event", json=spoof, headers=_bearer(root["token"])
    )
    (event,) = _events(db_session, "tool_event")
    assert "run" not in event  # nested under `extra`, never promoted to attribution


def test_batch_ingest_discards_client_supplied_runs(root, db_session):
    fake = {"run_id": "spoofed", "parent_run_id": None, "depth": 0, "role": "x"}
    batch = {"events": [{"action": "note", "payload": {"run": fake, "k": 1}}]}

    root["client"].post("/audit/ingest", json=batch, headers=_bearer(root["token"]))
    (plain,) = _events(db_session, "note")
    assert "run" not in plain and plain["k"] == 1  # stripped from a root token

    run = _mint(root, root["token"], "analysis").json()
    root["client"].post("/audit/ingest", json=batch, headers=_bearer(run["token"]))
    _, attributed = _events(db_session, "note")
    assert attributed["run"]["run_id"] == run["run_id"]  # replaced with the token's
    assert attributed["k"] == 1
    assert batch["events"][0]["payload"]["run"] == fake  # caller's data not mutated


def test_gateway_calls_are_attributed_to_the_run(root, db_session):
    from api.gateway import _audit_gateway_call

    parent = decode_persona_token(root["token"], "gateway")
    run = decode_persona_token(
        _mint(root, root["token"], "analysis").json()["token"], "gateway"
    )
    for p in (parent, run):
        _audit_gateway_call(
            p,
            "gpt-4o-mini",
            {"messages": []},
            status=200,
            tokens_in=1,
            tokens_out=2,
            latency_ms=3,
            streamed=False,
        )
    plain, attributed = _events(db_session, "gateway_call")
    assert "run" not in plain
    assert attributed["run"]["run_id"] == run.run_id and attributed["run"]["depth"] == 1


def test_subagents_share_the_personas_budget(root):
    """Quota and rate limits are keyed by persona; a run token is the same persona,
    so spawning subagents cannot multiply the budget."""
    run = decode_persona_token(_mint(root, root["token"]).json()["token"], "gateway")
    parent = decode_persona_token(root["token"], "gateway")
    assert run.persona_id == parent.persona_id


def test_plain_persona_token_has_no_run():
    p = decode_persona_token(create_persona_token("p", "c"), "gateway")
    assert (p.run_id, p.parent_run_id, p.depth, p.role) == (None, None, 0, None)
    assert p.expires_at is not None
    # refresh tokens are untouched by all of this
    assert create_persona_refresh_token("p", "c")
