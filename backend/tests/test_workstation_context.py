"""
`GET /workstation/context` (ADR-0020): the stable context document a workspace agent
reads as instructions — company, department, its owner's job, and the policies the
engine enforces — plus the policy-set change it depends on.
"""

import json

import pytest
from sqlmodel import select

import models
from core.security import encrypt
from services import audit_chain
from services.auth import create_access_token
from services.policy_engine import applicable_policies, applicable_policy_contents
from tests.test_workspaces import _create, rt, world  # noqa: F401 (fixtures)


def _bearer(t):
    return {"Authorization": f"Bearer {t}"}


def _policy(
    db, co, name, *, scope="company", dept=None, cfg=None, active=True, content="rule"
):
    p = models.Policy(
        company_id=co.id,
        name=name,
        slug=name.lower().replace(" ", "-"),
        content=content,
        scope=scope,
        is_active=active,
    )
    db.add(p)
    db.flush()
    if dept is not None:
        db.add(models.DepartmentPolicyLink(department_id=dept.id, policy_id=p.id))
    if cfg is not None:
        db.add(models.AgentPolicyLink(agent_config_id=cfg.id, policy_id=p.id))
    db.commit()
    return p


def _agent_cfg(db, agent_id):
    return db.exec(
        select(models.AgentConfig).where(models.AgentConfig.personnel_id == agent_id)
    ).first()


@pytest.fixture()
def ctx(world, rt, db_session):
    """Alice's workspace agent (Accounting ⊂ Finance) with a rich company setup."""
    co = world["co"]
    co.metadata_json = json.dumps(
        {
            "mission": "Make finance calm",
            "vision": "An agent for every team",
            "values": ["Own it"],
            "goals": ["Close in 3 days"],
        }
    )
    db_session.add(co)
    world["finance"].goals = "Accurate books"
    world["accounting"].goals = "Match invoices fast"
    for d in (world["finance"], world["accounting"]):
        db_session.add(d)
    alice = db_session.get(models.Personnel, world["p_alice"].id)
    alice.job_description = "Accounts payable: invoice matching."
    alice.title = "AP Specialist"
    db_session.add(alice)
    db_session.commit()

    agent_id = _create(world).json()["agent_persona_id"]
    cfg = _agent_cfg(db_session, agent_id)
    r = world["client"].post(
        "/workstation/persona-token", json={"personnel_id": agent_id}
    )
    return {
        **world,
        "agent": agent_id,
        "cfg": cfg,
        "token": r.json()["token"],
        "db": db_session,
    }


def _get(ctx, token=None, **headers):
    return ctx["client"].get(
        "/workstation/context", headers={**_bearer(token or ctx["token"]), **headers}
    )


# ── access ────────────────────────────────────────────────────────────────────


def test_needs_a_persona_token(ctx):
    c = ctx["client"]
    assert c.get("/workstation/context").status_code == 401
    assert c.get("/workstation/context", headers=_bearer("nope")).status_code == 401
    # the web session JWT is not a persona token
    jwt = c.headers["Authorization"].split(" ", 1)[1]
    assert c.get("/workstation/context", headers=_bearer(jwt)).status_code == 401


# ── content ───────────────────────────────────────────────────────────────────


def test_carries_company_department_job_and_every_enforced_policy(ctx):
    db, co = ctx["db"], ctx["co"]
    _policy(db, co, "Company code of conduct")
    _policy(db, co, "Finance close rules", scope="department", dept=ctx["finance"])
    _policy(db, co, "AP approval limits", scope="department", dept=ctx["accounting"])
    _policy(db, co, "Agent extra caution", scope="agent", cfg=ctx["cfg"])
    _policy(db, co, "Retired policy", active=False)
    _policy(db, co, "Empty policy", content="")
    _policy(db, co, "Sales discount rules", scope="department", dept=ctx["sales"])

    body = _get(ctx).json()
    text = body["text"]
    for want in (
        "Company: Test Corp",
        "Mission: Make finance calm",
        "Values: Own it",
        "Close in 3 days",
        "Department: Accounting",
        "Match invoices fast",
        "You work for Alice, AP Specialist.",
        "Accounts payable: invoice matching.",
        "Company code of conduct",
        "Finance close rules",
        "AP approval limits",
        "Agent extra caution",
    ):
        assert want in text, want
    for unwanted in ("Retired policy", "Empty policy", "Sales discount rules"):
        assert unwanted not in text, unwanted
    # least → most specific, as the engine orders them
    order = [
        text.index(n)
        for n in (
            "Company code of conduct",
            "Finance close rules",
            "AP approval limits",
            "Agent extra caution",
        )
    ]
    assert order == sorted(order)


def test_holds_nothing_that_varies_per_turn(ctx):
    db = ctx["db"]
    db.add(
        models.AgentMemory(
            personnel_id=ctx["agent"], company_id=ctx["co"].id, summary="MEMORY-XYZ"
        )
    )
    db.commit()
    text = _get(ctx).json()["text"]
    assert "MEMORY-XYZ" not in text
    assert "Respond helpfully" not in text and "Available tools" not in text
    names = [s["name"] for s in _get(ctx).json()["report"]["sections"]]
    assert names == ["identity", "company", "department", "job"]
    assert all(s["tier"] < 2 for s in _get(ctx).json()["report"]["sections"])


def test_json_shape_and_markdown_negotiation(ctx):
    body = _get(ctx).json()
    assert set(body) == {"persona_id", "etag", "text", "report"}
    assert body["persona_id"] == ctx["agent"] and body["report"]["over_budget"] is False

    md = _get(ctx, accept="text/markdown")
    assert md.status_code == 200 and md.headers["content-type"].startswith(
        "text/markdown"
    )
    assert md.text == body["text"] and md.headers["etag"] == body["etag"]


# ── caching ───────────────────────────────────────────────────────────────────


def test_etag_is_stable_and_304s(ctx):
    first = _get(ctx)
    etag = first.headers["etag"]
    assert etag == first.json()["etag"] and etag == _get(ctx).headers["etag"]
    r = _get(ctx, **{"If-None-Match": etag})
    assert r.status_code == 304 and r.content == b"" and r.headers["etag"] == etag
    assert _get(ctx, **{"If-None-Match": '"stale"'}).status_code == 200
    assert _get(ctx, **{"If-None-Match": f'"other", {etag}'}).status_code == 304


def test_etag_changes_when_the_facts_change(ctx):
    db = ctx["db"]
    e1 = _get(ctx).headers["etag"]

    alice = db.get(models.Personnel, ctx["p_alice"].id)
    alice.job_description = "Now: treasury."
    db.add(alice)
    db.commit()
    e2 = _get(ctx).headers["etag"]
    assert e2 != e1 and _get(ctx, **{"If-None-Match": e1}).status_code == 200

    _policy(db, ctx["co"], "New rule")
    e3 = _get(ctx).headers["etag"]
    assert e3 not in (e1, e2)


def test_agent_only_sees_itself_not_other_personas(ctx, db_session, world):
    def act_as(user):
        world["client"].headers["Authorization"] = "Bearer " + create_access_token(
            user.id
        )

    bob = db_session.get(
        models.Personnel,
        next(
            p.id
            for p in db_session.exec(select(models.Personnel)).all()
            if p.slug == "bob"
        ),
    )
    bob.job_description = "Sales: renewals."
    db_session.add(bob)
    db_session.commit()
    act_as(world["bob"])
    bob_agent = world["client"].post("/workspaces").json()["agent_persona_id"]
    bob_token = (
        world["client"]
        .post("/workstation/persona-token", json={"personnel_id": bob_agent})
        .json()["token"]
    )

    mine = _get(ctx, token=bob_token).json()["text"]
    assert "Sales: renewals." in mine and "invoice matching" not in mine
    assert "invoice matching" in _get(ctx).json()["text"]


def test_a_subagent_run_token_can_read_it_and_is_attributed(ctx, db_session):
    run = (
        ctx["client"]
        .post(
            "/workstation/run-token",
            json={"role": "analysis"},
            headers=_bearer(ctx["token"]),
        )
        .json()
    )
    r = _get(ctx, token=run["token"])
    assert r.status_code == 200
    ev = db_session.exec(
        select(models.AuditEvent).where(models.AuditEvent.action == "context_served")
    ).all()
    assert json.loads(ev[-1].payload_json)["run"]["run_id"] == run["run_id"]


# ── audit ─────────────────────────────────────────────────────────────────────


def _served(db):
    db.expire_all()
    return db.exec(
        select(models.AuditEvent).where(models.AuditEvent.action == "context_served")
    ).all()


def test_a_served_version_is_audited_without_its_text_and_a_304_is_not(ctx):
    db = ctx["db"]
    etag = _get(ctx).headers["etag"]
    (ev,) = _served(db)
    payload = json.loads(ev.payload_json)
    assert payload["etag"] == etag.strip('"') and ev.target == etag.strip('"')
    blob = ev.payload_json
    for private in ("Make finance calm", "invoice matching", "Alice"):
        assert private not in blob
    assert any(s["name"] == "company" for s in payload["prompt"]["sections"])

    _get(ctx, **{"If-None-Match": etag})
    assert len(_served(db)) == 1
    assert audit_chain.verify(ctx["co"].id)["ok"] is True


# ── the policy set is the enforced one ────────────────────────────────────────


def test_applicable_policies_order_dedupe_and_filters(ctx):
    db, co = ctx["db"], ctx["co"]
    a = _policy(db, co, "A company", scope="company")
    b = _policy(db, co, "B finance", scope="department", dept=ctx["finance"])
    c = _policy(db, co, "C accounting", scope="department", dept=ctx["accounting"])
    d = _policy(db, co, "D agent", scope="agent", cfg=ctx["cfg"])
    db.add(
        models.DepartmentPolicyLink(department_id=ctx["accounting"].id, policy_id=b.id)
    )  # linked twice
    db.commit()
    _policy(db, co, "off", active=False)
    _policy(db, co, "empty", content="")
    got = applicable_policies(co.id, ctx["accounting"].id, ctx["cfg"].id)
    assert [n for n, _ in got] == [a.name, b.name, c.name, d.name]
    assert applicable_policy_contents(co.id, ctx["accounting"].id, ctx["cfg"].id) == [
        body for _, body in got
    ]
    assert applicable_policies(None, None, None) == []
    # a department outside the chain is not inherited
    assert "B finance" not in [
        n for n, _ in applicable_policies(co.id, ctx["sales"].id, None)
    ]


def test_the_chat_prompt_now_names_the_policies_the_engine_enforces(ctx, monkeypatch):
    """Before: only the department's *direct* links and the agent's. The engine also
    enforces company-scope and ancestor-department policies, so the prompt now lists them."""
    import asyncio
    from unittest.mock import MagicMock, patch

    from services import agent_runtime

    db, co = ctx["db"], ctx["co"]
    _policy(db, co, "Company code of conduct")
    _policy(db, co, "Finance close rules", scope="department", dept=ctx["finance"])
    sess = models.AgentSession(personnel_id=ctx["agent"])
    db.add(sess)
    db.add(
        models.ProviderKey(
            provider="openai",
            encrypted_key=encrypt("sk-x"),
            status="active",
        )
    )
    cfg = _agent_cfg(db, ctx["agent"])
    cfg.model = "gpt-4o-mini"
    db.add(cfg)
    db.commit()

    seen = []
    real = agent_runtime.build_system_prompt
    monkeypatch.setattr(
        agent_runtime,
        "build_system_prompt",
        lambda *a, **k: (seen.append(a[3]), real(*a, **k))[1],
    )
    choice = MagicMock()
    choice.message.content = "ok"
    choice.message.tool_calls = None
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage.prompt_tokens = resp.usage.completion_tokens = (
        resp.usage.total_tokens
    ) = 1

    async def go():
        return [e async for e in agent_runtime.run_session(sess.id, "hello")]

    with patch("openai.OpenAI") as M:
        M.return_value.chat.completions.create.return_value = resp
        asyncio.run(go())
    assert seen and set(seen[0]) >= {"Company code of conduct", "Finance close rules"}
