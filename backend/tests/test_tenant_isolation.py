"""A manager of company B must have no reach into company A (Codex review, 2026-10-18).

`require_manager` alone only proves a managing role *somewhere*; every tenant-owned
resource is checked against the company that owns it.
"""

import pytest

from models import (
    CompanyMember,
    CompanySkill,
    Department,
    Flow,
    Policy,
)
from services.auth import create_access_token
from tests.conftest import (
    make_agent_config,
    make_company,
    make_member,
    make_personnel,
    make_user,
)


def _h(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def tenants(auth_client, db_session):
    """auth_client's company is the victim A; `attacker` founds company B."""
    a = auth_client._test_company
    dept = Department(company_id=a.id, name="Fin", slug="fin")
    db_session.add(dept)
    db_session.flush()
    agent = make_personnel(db_session, a.id, name="Bot", slug="bot", type="agent")
    agent.department_id = dept.id
    db_session.add(agent)
    cfg = make_agent_config(db_session, agent.id)
    pol = Policy(company_id=a.id, name="P", slug="p", content="secret rules")
    skill = CompanySkill(company_id=a.id, name="S", slug="s")
    db_session.add_all([pol, skill])
    db_session.flush()
    flow = Flow(
        company_id=a.id,
        personnel_id=agent.id,
        name="f",
        schedule="0 9 * * 1",
        prompt="do the secret thing",
    )
    db_session.add(flow)

    b = make_company(db_session, name="B Corp", slug="b-corp")
    attacker = make_user(db_session, email="atk@b.com", name="Atk")
    make_member(db_session, attacker.id, b.id, role="founder")

    plain = make_user(db_session, email="plain@a.com", name="Plain")
    make_member(db_session, plain.id, a.id, role="user")
    db_session.commit()
    return {
        "a": a.id,
        "b": b.id,
        "dept": dept.id,
        "agent": agent.id,
        "cfg": cfg.id,
        "policy": pol.id,
        "skill": skill.id,
        "flow": flow.id,
        "atk": _h(attacker),
        "plain": _h(plain),
        "attacker": attacker,
        "plain_user": plain,
    }


# ── policies ─────────────────────────────────────────────────────────────────


def test_outsider_cannot_read_or_touch_policies(auth_client, tenants):
    t = tenants
    h = t["atk"]
    assert auth_client.get(f"/policies/{t['policy']}", headers=h).status_code == 404
    assert (
        auth_client.get(f"/policies?company_id={t['a']}", headers=h).status_code == 404
    )
    assert auth_client.get("/policies", headers=h).json() == []
    assert (
        auth_client.put(
            f"/policies/{t['policy']}", json={"content": "x"}, headers=h
        ).status_code
        == 404
    )
    assert auth_client.delete(f"/policies/{t['policy']}", headers=h).status_code == 404
    body = {"company_id": t["a"], "name": "n", "slug": "n"}
    assert auth_client.post("/policies", json=body, headers=h).status_code == 404
    cfg = {"company_id": t["a"], "scope": "company", "mode": "off"}
    assert auth_client.put("/policies/config", json=cfg, headers=h).status_code == 404
    assert (
        auth_client.get(f"/policies/config?company_id={t['a']}", headers=h).status_code
        == 404
    )


def test_plain_member_cannot_write_policies_or_switch_mode(auth_client, tenants):
    t = tenants
    h = t["plain"]
    assert auth_client.get(f"/policies/{t['policy']}", headers=h).status_code == 200
    assert (
        auth_client.put(
            f"/policies/{t['policy']}", json={"content": "x"}, headers=h
        ).status_code
        == 403
    )
    assert auth_client.delete(f"/policies/{t['policy']}", headers=h).status_code == 403
    cfg = {"company_id": t["a"], "scope": "company", "mode": "off"}
    assert auth_client.put("/policies/config", json=cfg, headers=h).status_code == 403


def test_policy_target_must_be_same_company(auth_client, tenants, db_session):
    t = tenants
    other = Department(company_id=t["b"], name="X", slug="x")
    db_session.add(other)
    db_session.commit()
    body = {
        "company_id": t["a"],
        "name": "n",
        "slug": "n",
        "scope": "department",
        "department_id": other.id,
    }
    assert auth_client.post("/policies", json=body).status_code == 422


# ── company skills ───────────────────────────────────────────────────────────


def test_outsider_cannot_touch_company_skills(auth_client, tenants):
    t = tenants
    h = t["atk"]
    assert (
        auth_client.get(f"/company-skills/{t['skill']}", headers=h).status_code == 404
    )
    assert auth_client.get("/company-skills", headers=h).json() == []
    assert (
        auth_client.put(
            f"/company-skills/{t['skill']}", json={"name": "x"}, headers=h
        ).status_code
        == 404
    )
    assert (
        auth_client.delete(f"/company-skills/{t['skill']}", headers=h).status_code
        == 404
    )
    assign = f"/company-skills/{t['skill']}/assign/{t['cfg']}"
    assert auth_client.post(assign, headers=h).status_code == 404
    assert auth_client.delete(assign, headers=h).status_code == 404
    body = {"company_id": t["a"], "name": "n", "slug": "n", "skill_type": "builtin"}
    assert auth_client.post("/company-skills", json=body, headers=h).status_code == 404


# ── departments ──────────────────────────────────────────────────────────────


def test_departments_are_tenant_scoped(auth_client, tenants):
    t = tenants
    for h, code in ((t["atk"], 404), (t["plain"], 403)):
        assert (
            auth_client.patch(
                f"/departments/{t['dept']}", json={"name": "x"}, headers=h
            ).status_code
            == code
        )
        assert (
            auth_client.put(
                f"/departments/{t['dept']}/policies", json={"policy_ids": []}, headers=h
            ).status_code
            == code
        )
        assert (
            auth_client.delete(f"/departments/{t['dept']}", headers=h).status_code
            == code
        )
    assert (
        auth_client.get(f"/departments/{t['dept']}", headers=t["atk"]).status_code
        == 404
    )


def test_department_creation_needs_company_and_same_company_parent(
    auth_client, tenants
):
    t = tenants
    body = {"name": "N", "slug": "n"}
    assert auth_client.post("/departments", json=body).status_code == 422  # no company
    # parent from another company
    b_parent = auth_client.post(
        f"/departments?company_id={t['b']}", json=body, headers=t["atk"]
    ).json()["id"]
    r = auth_client.post(
        f"/departments?company_id={t['a']}",
        json={**body, "slug": "m", "parent_id": b_parent},
    )
    assert r.status_code == 404
    # cycle: dept -> its own child
    a1 = auth_client.post(
        f"/departments?company_id={t['a']}", json={"name": "A1", "slug": "a1"}
    ).json()["id"]
    a2 = auth_client.post(
        f"/departments?company_id={t['a']}",
        json={"name": "A2", "slug": "a2", "parent_id": a1},
    ).json()["id"]
    r = auth_client.patch(f"/departments/{a1}", json={"parent_id": a2})
    assert r.status_code == 400


def test_policy_must_belong_to_the_department_company(auth_client, tenants, db_session):
    t = tenants
    foreign = Policy(company_id=t["b"], name="F", slug="f", content="x")
    db_session.add(foreign)
    db_session.commit()
    r = auth_client.put(
        f"/departments/{t['dept']}/policies", json={"policy_ids": [foreign.id]}
    )
    assert r.status_code == 422


# ── users & memberships ──────────────────────────────────────────────────────


def test_founder_of_b_cannot_administer_a_users(auth_client, tenants, db_session):
    t = tenants
    h = t["atk"]
    victim = t["plain_user"]
    assert auth_client.get(f"/users?company_id={t['a']}", headers=h).status_code == 404
    assert auth_client.get(f"/users/{victim.id}", headers=h).status_code == 404
    assert (
        auth_client.patch(
            f"/users/{victim.id}", json={"is_active": False}, headers=h
        ).status_code
        == 404
    )
    assert auth_client.delete(f"/users/{victim.id}", headers=h).status_code == 404
    mid = db_session.query(CompanyMember).filter_by(user_id=victim.id).first().id
    assert (
        auth_client.patch(
            f"/users/memberships/{mid}", json={"role": "founder"}, headers=h
        ).status_code
        == 404
    )
    assert auth_client.delete(f"/users/memberships/{mid}", headers=h).status_code == 404
    assert auth_client.get(f"/users/{victim.id}/memberships", headers=h).json() == []


def test_membership_rules_for_the_owning_founder(auth_client, tenants, db_session):
    t = tenants
    mid = (
        db_session.query(CompanyMember).filter_by(user_id=t["plain_user"].id).first().id
    )
    assert (
        auth_client.patch(
            f"/users/memberships/{mid}", json={"role": "boss"}
        ).status_code
        == 422
    )
    # agent_owner needs an agent scope; a department is not one
    r = auth_client.patch(
        f"/users/memberships/{mid}", json={"role": "agent_owner", "scope_id": t["dept"]}
    )
    assert r.status_code == 422
    r = auth_client.patch(
        f"/users/memberships/{mid}",
        json={"role": "agent_owner", "scope_id": t["agent"]},
    )
    assert r.status_code == 200
    # the last founder cannot be demoted or removed
    founder = (
        db_session.query(CompanyMember)
        .filter_by(company_id=t["a"], role="founder")
        .first()
    )
    assert (
        auth_client.patch(
            f"/users/memberships/{founder.id}", json={"role": "user"}
        ).status_code
        == 409
    )
    assert auth_client.delete(f"/users/memberships/{founder.id}").status_code == 409


# ── onboarding ───────────────────────────────────────────────────────────────


def test_onboarding_is_setup_authority_of_the_own_company(auth_client, tenants):
    t = tenants
    structure = {"structure": {}, "company_id": t["a"]}
    assert (
        auth_client.post(
            "/onboarding/create", json=structure, headers=t["atk"]
        ).status_code
        == 404
    )
    assert (
        auth_client.post(
            "/onboarding/create", json=structure, headers=t["plain"]
        ).status_code
        == 403
    )
    assert (
        auth_client.get(f"/onboarding/status/{t['a']}", headers=t["atk"]).status_code
        == 404
    )


# ── flows ────────────────────────────────────────────────────────────────────


def test_flows_need_authority_over_the_agent(auth_client, tenants):
    t = tenants
    body = {
        "personnel_id": t["agent"],
        "name": "x",
        "schedule": "0 9 * * *",
        "prompt": "p",
    }
    for h, code in ((t["atk"], 403), (t["plain"], 403)):
        # create: outsider is not a member (403 from membership gate), member lacks authority
        r = auth_client.post(f"/flows?company_id={t['a']}", json=body, headers=h)
        assert r.status_code in (403, 404)
        assert auth_client.get(f"/flows/{t['flow']}", headers=h).status_code == 404
        assert (
            auth_client.patch(
                f"/flows/{t['flow']}", json={"prompt": "x"}, headers=h
            ).status_code
            == 404
        )
        assert auth_client.delete(f"/flows/{t['flow']}", headers=h).status_code == 404
        assert auth_client.post(f"/flows/{t['flow']}/run", headers=h).status_code == 404
    assert (
        auth_client.get(f"/flows?company_id={t['a']}", headers=t["plain"]).json() == []
    )
    assert auth_client.get("/flows", headers=t["atk"]).json() == []


def test_flow_agent_must_belong_to_the_company(auth_client, tenants):
    t = tenants
    body = {
        "personnel_id": t["agent"],
        "name": "x",
        "schedule": "0 9 * * *",
        "prompt": "p",
    }
    # founder of A naming company B in the query: not a member -> refused
    r = auth_client.post(f"/flows?company_id={t['b']}", json=body)
    assert r.status_code in (403, 404)


# ── sessions ─────────────────────────────────────────────────────────────────


def test_sessions_belong_to_their_owner_and_the_agents_managers(
    auth_client, tenants, db_session
):
    t = tenants
    mine = auth_client.post(
        "/sessions", json={"personnel_id": t["agent"]}, headers=t["plain"]
    )
    assert mine.status_code == 201
    sid = mine.json()["id"]
    # the founder (manages the agent) sees it; an outsider and another plain member do not
    assert auth_client.get(f"/sessions/{sid}").status_code == 200
    assert auth_client.get(f"/sessions/{sid}", headers=t["atk"]).status_code == 404
    other = make_user(db_session, email="o@a.com", name="O")
    make_member(db_session, other.id, t["a"], role="user")
    db_session.commit()
    assert auth_client.get(f"/sessions/{sid}", headers=_h(other)).status_code == 404
    assert all(
        s["id"] != sid for s in auth_client.get("/sessions", headers=_h(other)).json()
    )
    assert any(
        s["id"] == sid for s in auth_client.get("/sessions", headers=t["plain"]).json()
    )
    # outsiders cannot even start one
    assert (
        auth_client.post(
            "/sessions", json={"personnel_id": t["agent"]}, headers=t["atk"]
        ).status_code
        == 404
    )
    # memories summarise everyone's chats: managers only
    assert (
        auth_client.get(
            f"/sessions/memories?personnel_id={t['agent']}", headers=t["plain"]
        ).json()
        == []
    )


def test_a_draft_agent_cannot_be_chatted_with_or_minted(
    auth_client, tenants, db_session
):
    from models import AgentConfig

    t = tenants
    cfg = db_session.get(AgentConfig, t["cfg"])
    cfg.status = "draft"
    db_session.add(cfg)
    db_session.commit()
    assert (
        auth_client.post("/sessions", json={"personnel_id": t["agent"]}).status_code
        == 409
    )
    assert (
        auth_client.post(
            "/gateway/persona-token", params={"personnel_id": t["agent"]}
        ).status_code
        == 409
    )
    personas = auth_client.get("/workstation/personas").json()["personas"]
    assert all(p["personnel_id"] != t["agent"] for p in personas)


# ── gateway token minting & usage ────────────────────────────────────────────


def test_persona_token_and_usage_are_scoped_to_the_agents_company(auth_client, tenants):
    t = tenants
    r = auth_client.post(
        "/gateway/persona-token", params={"personnel_id": t["agent"]}, headers=t["atk"]
    )
    assert r.status_code == 404
    assert (
        auth_client.get(f"/gateway/usage/{t['agent']}", headers=t["atk"]).status_code
        == 404
    )
    assert (
        auth_client.post(
            "/gateway/persona-token",
            params={"personnel_id": t["agent"]},
            headers=t["plain"],
        ).status_code
        == 404
    )


# ── invites ──────────────────────────────────────────────────────────────────


def _human(db_session, company_id, email, department_id=None):
    p = make_personnel(
        db_session, company_id, name=email, slug=email.split("@")[0], type="human"
    )
    p.email = email
    p.department_id = department_id
    db_session.add(p)
    return p


def test_scoped_grantors_cannot_mint_company_wide_managers(
    auth_client, tenants, db_session
):
    t = tenants
    scoped = make_user(db_session, email="se@a.com", name="SE")
    m = make_member(db_session, scoped.id, t["a"], role="executive")
    m.scope_id = t["dept"]
    db_session.add(m)
    target = _human(db_session, t["a"], "new@a.com", t["dept"])
    db_session.commit()
    inv = f"/personnel/{target.id}/invite"
    # company-wide dept_head needs a company-wide grantor
    r = auth_client.post(inv, json={"role": "dept_head"}, headers=_h(scoped))
    assert r.status_code == 403
    # ...but a dept_head scoped to the executive's own department is fine
    r = auth_client.post(
        inv, json={"role": "dept_head", "scope_id": t["dept"]}, headers=_h(scoped)
    )
    assert r.status_code == 201
    # and one scoped to a department outside its remit is not
    other = Department(company_id=t["a"], name="Other", slug="other-d")
    db_session.add(other)
    db_session.commit()
    r = auth_client.post(
        inv, json={"role": "dept_head", "scope_id": other.id}, headers=_h(scoped)
    )
    assert r.status_code == 403
    # invalid scope kinds are refused
    r = auth_client.post(inv, json={"role": "agent_owner", "scope_id": t["dept"]})
    assert r.status_code == 422


def test_inviting_an_account_of_another_tenant_keeps_its_password(
    auth_client, tenants, db_session
):
    from models import User

    t = tenants
    victim = t["attacker"]  # lives in company B, has a password
    before = db_session.get(User, victim.id).password_hash
    target = _human(db_session, t["a"], victim.email)
    db_session.commit()
    r = auth_client.post(f"/personnel/{target.id}/invite", json={"role": "user"})
    assert r.status_code == 201
    db_session.expire_all()
    assert db_session.get(User, victim.id).password_hash == before
    assert "şifre değişmedi" in r.json()["message"]


# ── change request visibility: role and scope on the same membership ─────────


def test_cr_visibility_does_not_mix_roles_and_scopes(auth_client, tenants, db_session):
    t = tenants
    cr = auth_client.post(
        f"/change-requests?company_id={t['a']}",
        json={
            "personnel_id": t["agent"],
            "change_type": "skill",
            "title": "t",
            "proposed": {"name": "n", "version": "1"},
        },
    )
    assert cr.status_code == 201
    cr_id = cr.json()["id"]
    # one membership: plain user scoped to the agent's department (meaningless scope);
    # another: dept_head scoped to a different department.
    other_dept = Department(company_id=t["a"], name="HR", slug="hr")
    db_session.add(other_dept)
    db_session.flush()
    u = make_user(db_session, email="mix@a.com", name="Mix")
    m1 = make_member(db_session, u.id, t["a"], role="user")
    m1.scope_id = t["dept"]
    m2 = make_member(db_session, u.id, t["a"], role="dept_head")
    m2.scope_id = other_dept.id
    db_session.add_all([m1, m2])
    db_session.commit()
    assert (
        auth_client.get(f"/change-requests/{cr_id}", headers=_h(u)).status_code == 404
    )
