"""Run diagnosis API (ADR-0023): object-level access, run joining, trust rules."""

import pytest

from models import AgentConfig
from services import audit_chain
from services.auth import create_access_token
from tests.conftest import make_company, make_member, make_personnel, make_user


@pytest.fixture()
def world(auth_client, db_session):
    co = auth_client._test_company  # the client user is its founder
    agent = make_personnel(db_session, co.id, name="A1", slug="a1", type="agent")
    db_session.add(AgentConfig(personnel_id=agent.id, model="m", status="active"))
    other_agent = make_personnel(db_session, co.id, name="A2", slug="a2", type="agent")
    db_session.add(AgentConfig(personnel_id=other_agent.id, model="m", status="active"))
    plain = make_user(db_session, email="plain@test.com", name="Plain")
    make_member(db_session, plain.id, co.id, role="user")
    foreign_co = make_company(db_session, name="Foreign", slug="foreign")
    foreign_user = make_user(db_session, email="f@test.com", name="F")
    make_member(db_session, foreign_user.id, foreign_co.id, role="founder")
    db_session.commit()
    return {
        "co": co.id,
        "agent": agent.id,
        "other": other_agent.id,
        "plain": {"Authorization": f"Bearer {create_access_token(plain.id)}"},
        "foreign": {"Authorization": f"Bearer {create_access_token(foreign_user.id)}"},
    }


def _emit(world, persona, run_id, action, target=None, origin=None, **payload):
    p = {**payload, "run": {"run_id": run_id}}
    if origin:
        p["origin"] = origin
    audit_chain.append(
        actor_type="agent",
        actor_id=persona,
        company_id=world["co"],
        action=action,
        target=target,
        payload=p,
    )


def _diagnose(client, persona, run_id, headers=None):
    return client.post(
        f"/eval/personas/{persona}/runs/{run_id}/diagnose", headers=headers or {}
    )


def test_diagnose_joins_only_this_runs_events(auth_client, world):
    _emit(world, world["agent"], "r1", "gateway_call", "gpt", upstream_status=503)
    _emit(world, world["agent"], "r2", "gateway_call", "gpt", upstream_status=200)
    _emit(world, world["other"], "r1", "gateway_call", "gpt", upstream_status=500)
    r = _diagnose(auth_client, world["agent"], "r1")
    assert r.status_code == 200
    d = r.json()
    assert d["suspect_layer"] == "model" and d["events_seen"] == 1
    assert _diagnose(auth_client, world["agent"], "r2").json()["findings"] == []


def test_policy_decision_with_verified_run_reaches_the_policy_layer(auth_client, world):
    _emit(
        world,
        world["agent"],
        "r1",
        "policy_decision",
        "bash",
        effect="deny",
        matched_rule="no-rm",
        enforced=True,
    )
    d = _diagnose(auth_client, world["agent"], "r1").json()
    assert d["suspect_layer"] == "policy"
    assert "no-rm" in d["findings"][0]["detail"]


def test_client_origin_claims_are_ignored_and_counted(auth_client, world):
    _emit(
        world,
        world["agent"],
        "r1",
        "gateway_call",
        "m",
        origin="client",
        upstream_status=503,
    )
    d = _diagnose(auth_client, world["agent"], "r1").json()
    assert d["findings"] == [] and d["ignored_client_claims"] == 1


def test_events_without_a_verified_run_stamp_are_not_part_of_any_run(
    auth_client, world
):
    audit_chain.append(
        actor_type="agent",
        actor_id=world["agent"],
        company_id=world["co"],
        action="policy_decision",
        target="bash",
        payload={"effect": "deny", "enforced": True, "session_ref": "r1"},
    )
    assert _diagnose(auth_client, world["agent"], "r1").json()["events_seen"] == 0


def test_get_and_list_return_the_stored_result(auth_client, world):
    _emit(world, world["agent"], "r1", "gateway_call", "gpt", upstream_status=500)
    _diagnose(auth_client, world["agent"], "r1")
    one = auth_client.get(f"/eval/personas/{world['agent']}/runs/r1")
    assert one.status_code == 200 and one.json()["suspect_layer"] == "model"
    assert [
        x["run_id"]
        for x in auth_client.get(f"/eval/personas/{world['agent']}/runs").json()
    ] == ["r1"]


def test_diagnose_is_idempotent(auth_client, world):
    _emit(world, world["agent"], "r1", "gateway_call", "gpt", upstream_status=500)
    a = _diagnose(auth_client, world["agent"], "r1").json()
    b = _diagnose(auth_client, world["agent"], "r1").json()
    assert a["findings"] == b["findings"]
    assert len(auth_client.get(f"/eval/personas/{world['agent']}/runs").json()) == 1


def test_other_company_and_plain_member_get_the_same_404(auth_client, world):
    _emit(world, world["agent"], "r1", "gateway_call", "gpt", upstream_status=500)
    _diagnose(auth_client, world["agent"], "r1")
    for who in ("foreign", "plain"):
        h = world[who]
        for call in (
            auth_client.get(f"/eval/personas/{world['agent']}/runs", headers=h),
            auth_client.get(f"/eval/personas/{world['agent']}/runs/r1", headers=h),
            _diagnose(auth_client, world["agent"], "r1", headers=h),
        ):
            assert call.status_code == 404
    unknown = auth_client.get("/eval/personas/nope/runs/r1")
    assert unknown.status_code == 404


def test_unauthenticated_is_rejected(client):
    assert client.get("/eval/personas/x/runs").status_code == 401


def test_policy_audit_carries_the_verified_run_block(auth_client, world, db_session):
    from sqlmodel import select

    from models import AuditEvent
    from services.policy_engine import PolicyDecisionRequest, audit_decision, decide

    req = PolicyDecisionRequest(
        tool="bash",
        args={"command": "ls"},
        source="workstation",
        persona_id=world["agent"],
        company_id=world["co"],
        run={"run_id": "r9", "depth": 1},
    )
    audit_decision(req, decide(req))
    ev = db_session.exec(
        select(AuditEvent).where(AuditEvent.action == "policy_decision")
    ).first()
    assert ev is not None and '"run_id": "r9"' in ev.payload_json
