"""GET /admin/monitoring (ADR-0034): one company's picture, only for its founders/executives."""

import json
from datetime import datetime, timedelta

import pytest

import services.monitoring as monitoring
from models import (
    AuditEvent,
    GatewayUsage,
    RunDiagnosis,
    WorkspaceManifestState,
)
from services import audit_anchor, audit_chain
from services.auth import create_access_token
from tests.conftest import make_company, make_member, make_personnel, make_user


def _h(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def world(db_session, tmp_path, monkeypatch):
    """Two companies; a founder of A, an executive of A, an employee of A, a founder of B."""
    monkeypatch.setattr(audit_anchor, "_ANCHOR_FILE", tmp_path / "anchors.jsonl")
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "no-workspace"))
    a, b = make_company(db_session, "A", "a"), make_company(db_session, "B", "b")
    w = type("W", (), {})()
    w.a, w.b = a, b
    w.founder = make_user(db_session, "f@a.test", "Founder")
    w.exec = make_user(db_session, "e@a.test", "Exec")
    w.employee = make_user(db_session, "u@a.test", "Employee")
    w.outsider = make_user(db_session, "o@b.test", "Outsider")
    make_member(db_session, w.founder.id, a.id, "founder")
    make_member(db_session, w.exec.id, a.id, "executive")
    make_member(db_session, w.employee.id, a.id, "user")
    make_member(db_session, w.outsider.id, b.id, "founder")
    w.bot_a = make_personnel(db_session, a.id, "BotA", "bot-a")
    w.bot_b = make_personnel(db_session, b.id, "BotB", "bot-b")
    db_session.commit()
    return w


def get(client, user, company_id, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(
        f"/admin/monitoring?company_id={company_id}" + (f"&{q}" if q else ""),
        headers=_h(user) if user else {},
    )


def test_authorisation_wrong_company_wrong_role_and_anonymous(client, world):
    assert get(client, None, world.a.id).status_code == 401
    assert (
        get(client, world.outsider, world.a.id).status_code == 404
    )  # not a member of A
    assert (
        get(client, world.founder, world.b.id).status_code == 404
    )  # A's founder, not B's
    assert (
        get(client, world.employee, world.a.id).status_code == 403
    )  # a member without the role
    assert get(client, world.founder, "no-such-company").status_code == 404
    for user in (world.founder, world.exec):
        assert get(client, user, world.a.id).status_code == 200


def test_a_department_scoped_executive_is_not_company_wide(client, db_session, world):
    scoped = make_user(db_session, "s@a.test", "Scoped")
    m = make_member(db_session, scoped.id, world.a.id, "executive")
    m.scope_id = "some-department"
    db_session.add(m)
    db_session.commit()
    assert get(client, scoped, world.a.id).status_code == 403


def test_shape_and_no_secret_material(client, world):
    r = get(client, world.founder, world.a.id)
    body = r.json()
    assert set(body["sections"]) == {
        "service",
        "audit",
        "gateway",
        "eval",
        "workspace",
        "clients",
    }
    assert body["status"] in {"ok", "unknown", "warn", "fail"}
    assert body["sections"]["service"]["database"] == "ok"
    assert body["sections"]["clients"] == {
        "status": "unknown",
        "reason": "drift_not_reported",
    }
    text = json.dumps(body).lower()
    for forbidden in ("private", "password", "secret", "traceback", "begin "):
        assert forbidden not in text, forbidden
    # an unconfigured workspace is a failed section with a code, not an exception or a path
    ws = body["sections"]["workspace"]
    assert (
        ws["status"] == "fail"
        and ws["signer"] == "unavailable"
        and len(ws["reason"]) <= 48
    )
    assert "no-workspace" not in text


def test_gateway_counts_only_this_companys_agents(client, db_session, world):
    day = datetime.utcnow().strftime("%Y-%m-%d")
    db_session.add(
        GatewayUsage(
            persona_id=world.bot_a.id,
            period=day,
            requests=3,
            tokens_in=10,
            tokens_out=5,
        )
    )
    db_session.add(
        GatewayUsage(
            persona_id=world.bot_b.id,
            period=day,
            requests=99,
            tokens_in=1000,
            tokens_out=1000,
        )
    )
    db_session.commit()
    g = get(client, world.founder, world.a.id).json()["sections"]["gateway"]
    assert g["day"] == {"requests": 3, "tokens_in": 10, "tokens_out": 5}
    assert [a["persona_id"] for a in g["top_agents_today"]] == [world.bot_a.id]
    assert "BotB" not in json.dumps(g)


def test_eval_counts_only_this_company_and_the_window(client, db_session, world):
    old = datetime.utcnow() - timedelta(days=60)
    db_session.add(
        RunDiagnosis(
            company_id=world.a.id,
            persona_id=world.bot_a.id,
            run_id="r1",
            suspect_layer="tool",
        )
    )
    db_session.add(
        RunDiagnosis(
            company_id=world.a.id,
            persona_id=world.bot_a.id,
            run_id="r2",
            suspect_layer="tool",
            created_at=old,
        )
    )
    db_session.add(
        RunDiagnosis(
            company_id=world.b.id,
            persona_id=world.bot_b.id,
            run_id="r3",
            suspect_layer="model",
        )
    )
    db_session.commit()
    e = get(client, world.founder, world.a.id).json()["sections"]["eval"]
    assert e["runs"] == 1 and e["suspect_counts"] == {"tool": 1}


def _event(company_id, action="tool_event"):
    audit_chain.record(
        actor_type="agent",
        actor_id="a",
        company_id=company_id,
        action=action,
        target="bash",
        reason="before",
    )


def test_audit_section_states(client, db_session, world):
    def sec(**p):
        return get(client, world.founder, world.a.id, **p).json()["sections"]["audit"]

    a = sec()
    assert a["events"] == 0 and a["status"] == "ok" and a["verified"] is None
    _event(world.a.id)
    _event(world.a.id)
    a = sec()
    assert (
        a["events"] == 2 and a["anchor"] == "none_recorded" and a["status"] == "warn"
    )  # unprotected
    audit_anchor.anchor_heads()
    a = sec()
    assert a["anchor"] == "ok" and a["status"] == "ok" and a["verified"] is None
    # a full re-hash only on request
    assert sec(deep="true")["verified"] is True
    # tampering with a stored event: invisible to the cheap check by design, found by deep
    row = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.chain_key == world.a.id, AuditEvent.seq == 1)
        .one()
        if hasattr(db_session, "query")
        else None
    )
    from sqlmodel import select

    row = db_session.exec(
        select(AuditEvent).where(
            AuditEvent.chain_key == world.a.id, AuditEvent.seq == 1
        )
    ).one()
    row.reason = "changed afterwards"
    db_session.add(row)
    db_session.commit()
    d = sec(deep="true")
    assert d["verified"] is False and d["broken_at"] == 1 and d["status"] == "fail"


def test_audit_truncation_is_a_failure_and_other_companies_chains_are_not_included(
    client, db_session, world
):
    from sqlmodel import delete

    _event(world.a.id)
    _event(world.a.id)
    _event(world.b.id)
    audit_anchor.anchor_heads()
    db_session.exec(
        delete(AuditEvent).where(
            AuditEvent.chain_key == world.a.id, AuditEvent.seq == 2
        )
    )
    db_session.commit()
    a = get(client, world.founder, world.a.id).json()["sections"]["audit"]
    assert (
        a["status"] == "fail" and a["anchor"] == "truncated" and a["anchor_issues"] == 1
    )
    b = get(client, world.outsider, world.b.id).json()["sections"]["audit"]
    assert (
        b["status"] == "ok" and b["events"] == 1
    )  # B is untouched, and sees only its own


def test_workspace_section_counts_people_and_not_other_companies(
    client, db_session, world
):
    db_session.add(
        WorkspaceManifestState(
            company_id=world.a.id, person_id=world.bot_a.id, epoch=1, generation=4
        )
    )
    db_session.add(
        WorkspaceManifestState(
            company_id=world.b.id, person_id=world.bot_b.id, epoch=1, generation=9
        )
    )
    db_session.commit()
    w = get(client, world.founder, world.a.id).json()["sections"]["workspace"]
    assert w["people_issued"] == 1 and w["last_issued"]


def test_one_failing_section_does_not_hide_the_others(client, world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail /var/lib/x")

    monkeypatch.setattr(monitoring, "_gateway", boom)
    r = get(client, world.founder, world.a.id)
    assert r.status_code == 200
    s = r.json()["sections"]
    assert s["gateway"] == {"status": "unknown", "reason": "section_failed"}
    assert s["service"]["status"] == "ok"
    assert "secret internal detail" not in r.text and "/var/lib" not in r.text


def test_worst_status_wins():
    assert monitoring.worst(["ok", "unknown"]) == "unknown"
    assert monitoring.worst(["ok", "warn", "unknown"]) == "warn"
    assert monitoring.worst(["warn", "fail", "ok"]) == "fail"
    assert monitoring.worst([]) == "unknown"
