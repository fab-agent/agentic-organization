"""Structure and agent-config writes: who may write directly (ADR-0022 precondition).

Plain members propose through change requests; only company-wide founder/executive
write agent settings directly; people/structure edits need a managing role.
"""

import pytest

from models import Department, Policy
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
def world(auth_client, db_session):
    co = auth_client._test_company
    dept_a = Department(company_id=co.id, name="A", slug="a")
    dept_b = Department(company_id=co.id, name="B", slug="b")
    db_session.add_all([dept_a, dept_b])
    db_session.flush()
    agent = make_personnel(
        db_session, co.id, name="Bot", slug="bot", type="agent", title="t"
    )
    agent.department_id = dept_a.id
    db_session.add(agent)
    cfg = make_agent_config(db_session, agent.id)
    cfg.status = "active"
    db_session.add(cfg)
    from models import Skill

    sk = Skill(agent_id=cfg.id, name="s", version="1")
    db_session.add(sk)

    def member(email, role, scope=None):
        u = make_user(db_session, email=email, name=email)
        m = make_member(db_session, u.id, co.id, role=role)
        m.scope_id = scope
        db_session.add(m)
        return u

    users = {
        "user": member("u@t.com", "user"),
        "owner": member("o@t.com", "agent_owner"),
        "dept_a": member("da@t.com", "dept_head", dept_a.id),
        "dept_b": member("db@t.com", "dept_head", dept_b.id),
        "dept_all": member("dall@t.com", "dept_head"),
        "exec": member("e@t.com", "executive"),
        "exec_scoped": member("es@t.com", "executive", dept_a.id),
    }
    other = make_company(db_session, name="Other", slug="other")
    foreign_dept = Department(company_id=other.id, name="F", slug="f")
    foreign_policy = Policy(company_id=other.id, name="p", slug="p", content="x")
    db_session.add_all([foreign_dept, foreign_policy])
    db_session.commit()
    return {
        "co": co.id,
        "agent": agent.id,
        "cfg": cfg.id,
        "skill": sk.id,
        "dept_a": dept_a.id,
        "dept_b": dept_b.id,
        "foreign_dept": foreign_dept.id,
        "foreign_policy": foreign_policy.id,
        "users": users,
    }


def _patch_person(c, w, who, **body):
    return c.patch(f"/personnel/{w['agent']}", json=body, headers=_h(w["users"][who]))


@pytest.mark.parametrize("who", ["user", "owner", "dept_b", "exec_scoped"])
def test_unprivileged_members_cannot_edit_people(auth_client, world, who):
    r = _patch_person(auth_client, world, who, title="CEO")
    # dept_b: other department; exec_scoped: scoped to A but the move below is separate
    if who == "exec_scoped":
        assert r.status_code == 200
    else:
        assert r.status_code == 403


def test_department_head_edits_only_own_department(auth_client, world):
    assert _patch_person(auth_client, world, "dept_a", title="ok").status_code == 200
    # moving the person into a department the head does not run is refused
    r = _patch_person(auth_client, world, "dept_a", department_id=world["dept_b"])
    assert r.status_code == 403
    assert _patch_person(auth_client, world, "dept_all", title="ok2").status_code == 200


def test_cross_company_department_is_rejected(auth_client, world):
    r = auth_client.patch(
        f"/personnel/{world['agent']}",
        json={"department_id": world["foreign_dept"]},
        headers=_h(world["users"]["dept_all"]),
    )
    assert r.status_code == 422


def test_create_requires_company_and_managing_role(auth_client, world):
    body = {"name": "N", "slug": "n", "title": "t", "role": "r", "type": "human"}
    r = auth_client.post("/personnel", json=body, headers=_h(world["users"]["user"]))
    assert r.status_code == 422  # no company
    r = auth_client.post(
        "/personnel",
        json={**body, "company_id": world["co"]},
        headers=_h(world["users"]["user"]),
    )
    assert r.status_code == 403
    r = auth_client.post(
        "/personnel",
        json={**body, "company_id": world["co"]},
        headers=_h(world["users"]["dept_all"]),
    )
    assert r.status_code == 201


@pytest.mark.parametrize("who", ["user", "dept_b"])
def test_delete_and_archive_need_a_manager_of_that_person(auth_client, world, who):
    h = _h(world["users"][who])
    assert (
        auth_client.post(f"/personnel/{world['agent']}/archive", headers=h).status_code
        == 403
    )
    assert (
        auth_client.delete(f"/personnel/{world['agent']}", headers=h).status_code == 403
    )


@pytest.mark.parametrize("who", ["user", "owner", "dept_a", "dept_all", "exec_scoped"])
def test_agent_settings_cannot_be_written_directly_below_final_approvers(
    auth_client, world, who
):
    h = _h(world["users"][who])
    p = f"/personnel/{world['agent']}"
    assert (
        auth_client.patch(
            p + "/agent-config", json={"status": "inactive"}, headers=h
        ).status_code
        == 403
    )
    assert (
        auth_client.post(
            p + "/skills", json={"name": "x", "version": "1"}, headers=h
        ).status_code
        == 403
    )
    assert (
        auth_client.patch(
            p + f"/skills/{world['skill']}", json={"name": "y"}, headers=h
        ).status_code
        == 403
    )
    assert (
        auth_client.delete(p + f"/skills/{world['skill']}", headers=h).status_code
        == 403
    )
    assert (
        auth_client.put(
            p + "/agent-policies", json={"policy_ids": []}, headers=h
        ).status_code
        == 403
    )


def test_company_wide_executive_and_founder_can_write_directly(auth_client, world):
    p = f"/personnel/{world['agent']}"
    r = auth_client.patch(
        p + "/agent-config",
        json={"status": "inactive"},
        headers=_h(world["users"]["exec"]),
    )
    assert r.status_code == 200
    r = auth_client.patch(p + "/agent-config", json={"status": "active"})  # founder
    assert r.status_code == 200


def test_skill_id_must_belong_to_the_persons_agent(auth_client, world, db_session):
    other = make_personnel(
        db_session, world["co"], name="B2", slug="b2", type="agent", title="t"
    )
    cfg2 = make_agent_config(db_session, other.id)
    from models import Skill

    foreign = Skill(agent_id=cfg2.id, name="theirs", version="1")
    db_session.add(foreign)
    db_session.commit()
    p = f"/personnel/{world['agent']}/skills/{foreign.id}"
    assert auth_client.patch(p, json={"name": "hacked"}).status_code == 404
    assert auth_client.delete(p).status_code == 404


def test_responsible_and_policy_must_belong_to_the_company(
    auth_client, world, db_session
):
    p = f"/personnel/{world['agent']}"
    r = auth_client.put(
        p + "/agent-policies", json={"policy_ids": [world["foreign_policy"]]}
    )
    assert r.status_code == 422
    foreign_person = make_personnel(
        db_session,
        make_company(db_session, name="C3", slug="c3").id,
        name="Z",
        slug="z",
    )
    db_session.commit()
    r = auth_client.patch(
        p + "/agent-config", json={"responsible_id": foreign_person.id}
    )
    assert r.status_code == 422


def test_managers_can_set_up_a_draft_agent_but_not_activate_it(
    auth_client, world, db_session
):
    from sqlmodel import select

    from models import AgentConfig

    cfg = db_session.exec(
        select(AgentConfig).where(AgentConfig.id == world["cfg"])
    ).one()
    cfg.status = "draft"
    db_session.add(cfg)
    db_session.commit()
    p = f"/personnel/{world['agent']}"
    head = _h(world["users"]["dept_a"])
    assert (
        auth_client.patch(
            p + "/agent-config", json={"model": "gpt-4o"}, headers=head
        ).status_code
        == 200
    )
    assert (
        auth_client.post(
            p + "/skills", json={"name": "x", "version": "1"}, headers=head
        ).status_code
        == 201
    )
    # going live is a change request
    assert (
        auth_client.patch(
            p + "/agent-config", json={"status": "active"}, headers=head
        ).status_code
        == 403
    )
    # other departments and plain members never
    assert (
        auth_client.patch(
            p + "/agent-config",
            json={"model": "m"},
            headers=_h(world["users"]["dept_b"]),
        ).status_code
        == 403
    )
    assert (
        auth_client.patch(
            p + "/agent-config", json={"model": "m"}, headers=_h(world["users"]["user"])
        ).status_code
        == 403
    )


def test_creating_an_agent_config_is_draft_only_for_managers(
    auth_client, world, db_session
):
    fresh = make_personnel(
        db_session, world["co"], name="Fresh", slug="fresh", type="agent", title="t"
    )
    fresh.department_id = world["dept_a"]
    db_session.add(fresh)
    db_session.commit()
    p = f"/personnel/{fresh.id}/agent-config"
    head = _h(world["users"]["dept_a"])
    assert (
        auth_client.post(
            p, json={"model": "m", "status": "active"}, headers=head
        ).status_code
        == 403
    )
    assert (
        auth_client.post(
            p, json={"model": "m", "status": "draft"}, headers=head
        ).status_code
        == 201
    )
    other = make_personnel(
        db_session, world["co"], name="Other", slug="oth", type="agent", title="t"
    )
    db_session.commit()
    r = auth_client.post(
        f"/personnel/{other.id}/agent-config",
        json={"model": "m"},
        headers=_h(world["users"]["user"]),
    )
    assert r.status_code == 403
