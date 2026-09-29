"""
The one agent every person gets with their workspace (ADR-0019 §1) and the
`job_description` field that feeds its context (ADR-0019 §3).
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

import models
from services.gateway_auth import decode_persona_token
from services.workspace_agent import FALLBACK_MODEL, agent_model
from tests.test_workspaces import _as, _create, rt, world  # noqa: F401 (fixtures)


def _agents(db_session):
    return db_session.exec(
        select(models.Personnel).where(models.Personnel.type == "agent")
    ).all()


def _cfg(db_session, personnel_id):
    return db_session.exec(
        select(models.AgentConfig).where(
            models.AgentConfig.personnel_id == personnel_id
        )
    ).first()


# ── creation ──────────────────────────────────────────────────────────────────


def test_workspace_creation_creates_the_persons_agent(world, rt, db_session):
    r = _create(world)
    assert r.status_code == 201
    agent_id = r.json()["agent_persona_id"]

    agent = db_session.get(models.Personnel, agent_id)
    assert agent.type == "agent" and agent.title == "Workspace Agent"
    assert agent.name == "Alice — Agent"
    assert agent.company_id == world["co"].id
    # sits in the owner's department and reports to them: same policy scope
    assert agent.department_id == world["accounting"].id
    assert agent.manager_id == world["p_alice"].id

    cfg = _cfg(db_session, agent.id)
    assert cfg.responsible_id == world["p_alice"].id
    assert cfg.is_workspace_agent is True and cfg.status == "active"
    assert cfg.model == FALLBACK_MODEL


def test_it_is_idempotent_across_calls_and_workspace_recreation(world, rt, db_session):
    first = _create(world).json()
    again = _create(world)
    assert again.status_code == 200
    assert again.json()["agent_persona_id"] == first["agent_persona_id"]

    world["client"].delete(f"/workspaces/{first['id']}")
    fresh = world["client"].post("/workspaces").json()
    assert fresh["id"] != first["id"]
    assert fresh["agent_persona_id"] == first["agent_persona_id"]
    assert len(_agents(db_session)) == 1


def test_me_reports_the_agent_without_creating_one(world, rt, db_session):
    _create(world)
    me = world["client"].get("/workspaces/me").json()
    assert me["agent_persona_id"] is not None

    # a workspace that predates this feature has no agent yet; `me` must not invent one
    for a in _agents(db_session):
        cfg = _cfg(db_session, a.id)
        db_session.delete(cfg)
        db_session.delete(a)
    db_session.commit()
    assert world["client"].get("/workspaces/me").json()["agent_persona_id"] is None
    assert _agents(db_session) == []
    # …and the next create heals it
    assert _create(world).json()["agent_persona_id"] is not None


def test_failed_workspace_creation_does_not_create_an_agent(world, rt, db_session):
    rt.fail_next = "create"
    assert _create(world).status_code == 502
    assert _agents(db_session) == []
    assert _create(world).json()["agent_persona_id"] is not None
    assert len(_agents(db_session)) == 1


def test_each_person_gets_their_own_agent(world, rt, db_session):
    a = _create(world, "alice").json()["agent_persona_id"]
    b = _create(world, "bob").json()["agent_persona_id"]
    assert a != b
    assert db_session.get(models.Personnel, b).department_id == world["sales"].id


def test_agent_follows_its_owner_to_a_new_department(world, rt, db_session):
    _create(world)
    alice = db_session.get(models.Personnel, world["p_alice"].id)
    alice.department_id = world["sales"].id
    db_session.add(alice)
    db_session.commit()

    agent_id = _create(world).json()["agent_persona_id"]
    db_session.expire_all()
    assert db_session.get(models.Personnel, agent_id).department_id == world["sales"].id


def test_slug_collision_gets_a_suffix(world, rt, db_session):
    db_session.add(
        models.Personnel(
            company_id=world["co"].id, name="x", slug="alice-agent", type="human"
        )
    )
    db_session.commit()
    agent_id = _create(world).json()["agent_persona_id"]
    assert db_session.get(models.Personnel, agent_id).slug == "alice-agent-2"


# ── the database enforces "one per person" ────────────────────────────────────


def test_db_allows_one_workspace_agent_per_human(world, db_session):
    def make_cfg(flag):
        p = models.Personnel(
            company_id=world["co"].id,
            name="a",
            slug=f"a-{flag}-{id(flag)}",
            type="agent",
        )
        db_session.add(p)
        db_session.flush()
        db_session.add(
            models.AgentConfig(
                personnel_id=p.id,
                model="m",
                responsible_id=world["p_alice"].id,
                is_workspace_agent=flag,
            )
        )
        db_session.flush()

    make_cfg(False)
    make_cfg(False)  # ordinary agents are unrestricted
    make_cfg(True)
    with pytest.raises(IntegrityError):
        make_cfg(True)
    db_session.rollback()


# ── model choice ──────────────────────────────────────────────────────────────


def test_model_precedence_company_then_global_then_env_then_fallback(
    world, db_session, monkeypatch
):
    cid = world["co"].id
    monkeypatch.delenv("WORKSPACE_AGENT_MODEL", raising=False)
    assert agent_model(db_session, cid) == FALLBACK_MODEL

    monkeypatch.setenv("WORKSPACE_AGENT_MODEL", "env-model")
    assert agent_model(db_session, cid) == "env-model"

    db_session.add(models.AppConfig(key="workspace.agent_model", value="global-model"))
    db_session.commit()
    assert agent_model(db_session, cid) == "global-model"

    db_session.add(
        models.AppConfig(key=f"workspace.agent_model:{cid}", value="company-model")
    )
    db_session.commit()
    assert agent_model(db_session, cid) == "company-model"
    assert agent_model(db_session, "other-company") == "global-model"


# ── it plugs into the existing persona-token flow ─────────────────────────────


def test_owner_can_mint_a_persona_token_for_their_agent(world, rt):
    agent_id = _create(world).json()["agent_persona_id"]
    r = world["client"].post(
        "/workstation/persona-token", json={"personnel_id": agent_id}
    )
    assert r.status_code == 201
    principal = decode_persona_token(r.json()["token"], "gateway")
    assert principal.persona_id == agent_id and principal.depth == 0


def test_someone_else_cannot(world, rt):
    agent_id = _create(world).json()["agent_persona_id"]
    _as(world["client"], world["bob"])
    r = world["client"].post(
        "/workstation/persona-token", json={"personnel_id": agent_id}
    )
    assert r.status_code == 403


# ── job_description ───────────────────────────────────────────────────────────


def test_job_description_roundtrip(auth_client):
    co = auth_client._test_company.id
    r = auth_client.post(
        "/personnel",
        json={
            "name": "Ayşe",
            "slug": "ayse",
            "company_id": co,
            "job_description": "Accounts payable: invoice matching and supplier aging.",
        },
    )
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["job_description"].startswith("Accounts payable")
    assert (
        auth_client.get(f"/personnel/{pid}")
        .json()["job_description"]
        .startswith("Accounts")
    )

    r = auth_client.patch(
        f"/personnel/{pid}", json={"job_description": "Now: treasury."}
    )
    assert r.json()["job_description"] == "Now: treasury."
    # omitted → unchanged; empty string → cleared
    assert (
        auth_client.patch(f"/personnel/{pid}", json={"title": "x"}).json()[
            "job_description"
        ]
        == "Now: treasury."
    )
    assert (
        auth_client.patch(f"/personnel/{pid}", json={"job_description": ""}).json()[
            "job_description"
        ]
        is None
    )


def test_job_description_defaults_to_none(auth_client):
    r = auth_client.post(
        "/personnel",
        json={"name": "B", "slug": "b", "company_id": auth_client._test_company.id},
    )
    assert r.json()["job_description"] is None
