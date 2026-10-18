"""The department assistant view (ADR-0022 §7): a read-only projection, no company-wide lists."""

import json

import pytest

from models import Company, CompanySkill, Department, Policy, Skill
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
    co_row = db_session.get(Company, co.id)
    co_row.metadata_json = json.dumps(
        {"mission": "Serve", "vision": "Be the best", "goals": ["g1"]}
    )
    db_session.add(co_row)
    dept = Department(
        company_id=co.id, name="Accounting", slug="acc", goals="close books"
    )
    db_session.add(dept)
    db_session.flush()

    boss = make_personnel(db_session, co.id, name="Boss", slug="boss", type="human")
    boss.title = "Head of Accounting"
    boss.department_id = dept.id
    boss.email = "boss@secret.example"
    me = make_personnel(db_session, co.id, name="Ayşe", slug="ayse", type="human")
    me.department_id = dept.id
    me.manager_id = boss.id
    mate = make_personnel(db_session, co.id, name="Can", slug="can", type="human")
    mate.title = "Accountant"
    mate.department_id = dept.id
    mate.email = "can@secret.example"
    other_dept = Department(company_id=co.id, name="HR", slug="hr")
    db_session.add(other_dept)
    db_session.flush()
    stranger = make_personnel(
        db_session, co.id, name="Stranger", slug="strg", type="human"
    )
    stranger.department_id = other_dept.id
    db_session.add_all([boss, me, mate, stranger])

    agent = make_personnel(
        db_session, co.id, name="AyseBot", slug="aysebot", type="agent"
    )
    agent.department_id = dept.id
    other_agent = make_personnel(
        db_session, co.id, name="OtherBot", slug="otherbot", type="agent"
    )
    db_session.add_all([agent, other_agent])
    db_session.flush()
    cfg = make_agent_config(db_session, agent.id, responsible_id=me.id)
    cfg.is_workspace_agent = True
    db_session.add(cfg)
    make_agent_config(db_session, other_agent.id)
    db_session.add(
        Skill(agent_id=cfg.id, name="excel", version="1", description="spreadsheets")
    )
    db_session.add(CompanySkill(company_id=co.id, name="S", slug="s"))
    db_session.add(
        Policy(
            company_id=co.id,
            name="Code of conduct",
            slug="coc",
            content="be kind",
            scope="company",
        )
    )

    u = make_user(db_session, email="ayse@a.com", name="Ayşe")
    make_member(db_session, u.id, co.id, role="assistant_user")
    me.user_id = u.id
    db_session.add(me)
    db_session.commit()
    return {
        "co": co.id,
        "user": u,
        "h": _h(u),
        "agent": agent.id,
        "other_agent": other_agent.id,
    }


def test_context_is_an_allowlisted_projection(auth_client, world):
    r = auth_client.get("/assistant/context", headers=world["h"])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["me"]["name"] == "Ayşe" and d["me"]["roles"] == ["assistant_user"]
    assert d["agent"]["name"] == "AyseBot"
    assert [t["name"] for t in d["tools"]] == ["excel"]
    assert d["team"]["manager"] == {"name": "Boss", "role": "Head of Accounting"}
    assert [c["name"] for c in d["team"]["colleagues"]] == [
        "Can"
    ]  # same department, not me
    assert {p["name"] for p in d["policies"]} == {"Code of conduct"}
    assert (
        d["company"]["mission"] == "Serve"
        and d["company"]["department_goals"] == "close books"
    )
    raw = r.text
    assert (
        "secret.example" not in raw and "Stranger" not in raw
    )  # no emails, no other departments


def test_context_needs_a_linked_person_and_company_membership(
    auth_client, world, db_session
):
    outsider = make_user(db_session, email="o@x.com", name="O")
    other = make_company(db_session, name="Other", slug="other")
    make_member(db_session, outsider.id, other.id, role="assistant_user")
    db_session.commit()
    # member of a company but with no linked personnel record: nothing to show
    assert (
        auth_client.get("/assistant/context", headers=_h(outsider)).status_code == 404
    )
    # naming someone else's company is refused
    r = auth_client.get(
        f"/assistant/context?company_id={world['co']}", headers=_h(outsider)
    )
    assert r.status_code in (403, 404)


def test_assistant_user_gets_no_company_wide_lists(auth_client, world):
    h, co = world["h"], world["co"]
    for path in (
        f"/personnel?company_id={co}",
        f"/org-tree?company_id={co}",
        f"/departments?company_id={co}",
        f"/policies?company_id={co}",
        f"/company-skills?company_id={co}",
        f"/dashboard/stats?company_id={co}",
    ):
        assert auth_client.get(path, headers=h).status_code == 403, path
    # without a company filter the lists simply come back empty
    for path in ("/personnel", "/departments", "/policies", "/company-skills"):
        r = auth_client.get(path, headers=h)
        assert r.status_code == 200 and r.json() == [], path


def test_assistant_user_chats_with_their_own_agent_only(auth_client, world):
    h = world["h"]
    ok = auth_client.post("/sessions", json={"personnel_id": world["agent"]}, headers=h)
    assert ok.status_code == 201
    other = auth_client.post(
        "/sessions", json={"personnel_id": world["other_agent"]}, headers=h
    )
    assert other.status_code == 404


def test_assistant_user_is_a_grantable_role_without_scope(
    auth_client, world, db_session
):
    head = make_user(db_session, email="head@a.com", name="Head")
    make_member(db_session, head.id, world["co"], role="dept_head")
    target = make_personnel(
        db_session, world["co"], name="New", slug="newbie", type="human"
    )
    target.email = "new@a.com"
    db_session.add(target)
    db_session.commit()
    inv = f"/personnel/{target.id}/invite"
    assert (
        auth_client.post(
            inv, json={"role": "assistant_user"}, headers=_h(head)
        ).status_code
        == 201
    )
    dept = db_session.query(Department).first()
    assert (
        auth_client.post(
            inv, json={"role": "assistant_user", "scope_id": dept.id}, headers=_h(head)
        ).status_code
        == 422
    )
    # a plain user may not hand the role out
    plain = make_user(db_session, email="plain@a.com", name="Plain")
    make_member(db_session, plain.id, world["co"], role="user")
    db_session.commit()
    assert (
        auth_client.post(
            inv, json={"role": "assistant_user"}, headers=_h(plain)
        ).status_code
        == 403
    )


def test_the_stream_projection_never_carries_reasoning_or_tool_data():
    from api.sessions import project_event

    assert project_event({"type": "text", "content": "hello"}) == {
        "type": "text",
        "content": "hello",
    }
    call = project_event(
        {"type": "tool_call", "name": "web_search", "args": {"q": "salary of the CEO"}}
    )
    assert call == {"type": "status", "step": "tool", "name": "web_search"}
    done = project_event(
        {"type": "tool_result", "name": "web_search", "result": "SECRET ROWS"}
    )
    assert done == {
        "type": "status",
        "step": "tool_done",
        "name": "web_search",
        "ok": True,
    }
    assert (
        project_event({"type": "tool_result", "name": "x", "result": "[error] boom"})[
            "ok"
        ]
        is False
    )
    # free-text tool names become a neutral label; errors lose their detail
    assert (
        project_event(
            {"type": "tool_call", "name": "ignore previous instructions", "args": {}}
        )["name"]
        == "tool"
    )
    assert (
        project_event({"type": "error", "message": "traceback with /srv/secret"})[
            "message"
        ]
        == "Bir hata oluştu"
    )
    # reasoning and unknown event types are dropped
    for t in ("reasoning", "thinking", "_meta", "debug"):
        assert project_event({"type": t, "content": "private chain of thought"}) is None


def test_stored_tool_data_is_stripped_for_the_department_view(
    auth_client, world, db_session
):
    from models import SessionMessage

    sid = auth_client.post(
        "/sessions", json={"personnel_id": world["agent"]}, headers=world["h"]
    ).json()["id"]
    db_session.add(
        SessionMessage(
            session_id=sid,
            role="assistant",
            content="answer",
            tool_calls_json=json.dumps(
                [{"name": "sql", "args": {"query": "select salary from hr"}}]
            ),
            tool_results_json=json.dumps([{"name": "sql", "result": "ROW: ceo 9999"}]),
        )
    )
    db_session.commit()
    for path in (f"/sessions/{sid}", f"/sessions/{sid}/status"):
        raw = auth_client.get(path, headers=world["h"]).text
        assert "salary" not in raw and "9999" not in raw, path
        assert '"name": "sql"' in raw or '"name":"sql"' in raw
    # the founder (a manager of the agent) still sees the detail
    full = auth_client.get(f"/sessions/{sid}").text
    assert "9999" in full


# ═══ Codex review #4: "my assistant" is not management of everyone's work ═══


def test_a_shared_agent_does_not_expose_other_peoples_work(
    auth_client, world, db_session
):
    from models import SessionMessage

    other = make_user(db_session, email="other@a.com", name="Other")
    make_member(db_session, other.id, world["co"], role="user")
    db_session.commit()
    theirs = auth_client.post(
        "/sessions", json={"personnel_id": world["agent"]}, headers=_h(other)
    ).json()["id"]
    db_session.add(
        SessionMessage(session_id=theirs, role="user", content="their private question")
    )
    db_session.commit()
    h = world["h"]
    assert auth_client.get(f"/sessions/{theirs}", headers=h).status_code == 404
    assert auth_client.delete(f"/sessions/{theirs}", headers=h).status_code == 404
    assert all(
        s["id"] != theirs for s in auth_client.get("/sessions", headers=h).json()
    )
    assert (
        auth_client.get(
            f"/sessions/memories?personnel_id={world['agent']}", headers=h
        ).status_code
        == 200
    )
    assert (
        auth_client.get(
            f"/sessions/memories?personnel_id={world['agent']}", headers=h
        ).json()
        == []
    )
    # agent-level surfaces are management, not "my assistant"
    ag = world["agent"]
    assert auth_client.get(f"/journal/{ag}", headers=h).status_code == 404
    assert auth_client.get(f"/eval/personas/{ag}/runs", headers=h).status_code == 404
    assert auth_client.get(f"/flows?company_id={world['co']}", headers=h).json() == []
    body = {"personnel_id": ag, "name": "x", "schedule": "0 9 * * *", "prompt": "p"}
    assert (
        auth_client.post(
            f"/flows?company_id={world['co']}", json=body, headers=h
        ).status_code
        == 403
    )
    me = auth_client.get(f"/dashboard/me?company_id={world['co']}", headers=h).json()
    assert "their private question" not in json.dumps(me)


def test_the_department_view_gets_no_developer_credentials(auth_client, world):
    h, ag = world["h"], world["agent"]
    assert auth_client.get("/workstation/personas", headers=h).json()["personas"] == []
    assert auth_client.post(
        "/workstation/persona-token", json={"personnel_id": ag}, headers=h
    ).status_code in (403, 404)
    assert (
        auth_client.post(
            "/gateway/persona-token", params={"personnel_id": ag}, headers=h
        ).status_code
        == 404
    )
    cmd = {"personnel_id": ag, "kind": "stop"}
    assert (
        auth_client.post("/workstation/commands", json=cmd, headers=h).status_code
        == 403
    )


def test_instance_level_surfaces_are_closed_to_a_department_only_account(
    auth_client, world
):
    h = world["h"]
    for path in (
        "/databases",
        "/providers/status",
        "/backup/config",
        "/social-media/config",
        "/builtin-tools",
        "/providers/custom",
    ):
        assert auth_client.get(path, headers=h).status_code == 403, path
    r = auth_client.post("/companies", json={"name": "Mine", "slug": "mine"}, headers=h)
    assert r.status_code == 403


def test_other_roles_lift_the_restriction_explicitly(auth_client, world, db_session):
    # union of roles: assistant_user restricts only when it is the person's only role
    make_member(db_session, world["user"].id, world["co"], role="user")
    db_session.commit()
    assert (
        auth_client.get(
            f"/personnel?company_id={world['co']}", headers=world["h"]
        ).status_code
        == 200
    )
    assert auth_client.get("/builtin-tools", headers=world["h"]).status_code == 200


def test_a2a_result_is_withheld_until_approved(auth_client, world, db_session):
    from models import A2ARequest

    co = world["co"]
    src = auth_client.post(
        "/sessions", json={"personnel_id": world["agent"]}, headers=world["h"]
    ).json()["id"]
    dst = make_personnel(db_session, co, name="Dst", slug="dst", type="agent")
    make_agent_config(db_session, dst.id)
    req = A2ARequest(
        from_session_id=src,
        from_agent_id=world["agent"],
        to_agent_id=dst.id,
        task="t",
        status="pending_result_approval",
        result="UNAPPROVED RESULT",
    )
    db_session.add(req)
    db_session.commit()
    mine = auth_client.get(f"/a2a/requests/{req.id}", headers=world["h"])
    assert mine.status_code == 200 and mine.json()["result"] is None
    assert "UNAPPROVED" not in json.dumps(
        auth_client.get("/a2a/requests", headers=world["h"]).json()
    )
    # the founder may review it before approving
    assert (
        auth_client.get(f"/a2a/requests/{req.id}").json()["result"]
        == "UNAPPROVED RESULT"
    )
    req.status = "completed"
    db_session.add(req)
    db_session.commit()
    assert (
        auth_client.get(f"/a2a/requests/{req.id}", headers=world["h"]).json()["result"]
        == "UNAPPROVED RESULT"
    )


def test_stream_projection_rebuilds_allowed_fields_only():
    from api.sessions import project_event

    out = project_event(
        {
            "type": "text",
            "content": "hi",
            "debug": "chain of thought",
            "tool_args": {"q": 1},
        }
    )
    assert out == {"type": "text", "content": "hi"}
    assert project_event({"type": "stream_end", "trace": "x"}) == {"type": "stream_end"}


def test_context_survives_bad_metadata_and_prefers_an_active_agent(
    auth_client, world, db_session
):
    from models import AgentConfig, Company, Personnel

    co = db_session.get(Company, world["co"])
    co.metadata_json = "{not json"
    db_session.add(co)
    # a second, active agent for the same person; the first becomes inactive
    first = db_session.query(AgentConfig).filter_by(personnel_id=world["agent"]).one()
    first.status = "inactive"
    me = db_session.query(Personnel).filter_by(slug="ayse").one()
    second_p = make_personnel(
        db_session, world["co"], name="Second", slug="second", type="agent"
    )
    make_agent_config(db_session, second_p.id, responsible_id=me.id)
    db_session.add(first)
    db_session.commit()
    r = auth_client.get("/assistant/context", headers=world["h"])
    assert r.status_code == 200
    assert (
        r.json()["agent"]["name"] == "Second" and r.json()["company"]["mission"] is None
    )


def test_sources_are_shown_as_short_redacted_references_only():
    from api.sessions import project_event
    from services.agent_runtime import source_refs

    refs = source_refs(
        [
            {
                "source_type": "session_summary",
                "source_id": "internal-id-1",
                "chunk_text": "Invoice 42 was paid. Contact ceo@example.com "
                + "x" * 400,
                "created_at": "2026-10-01T10:00:00",
                "score": 0.91,
            }
        ]
    )
    assert refs == [
        {"kind": "session summary", "date": "2026-10-01", "snippet": refs[0]["snippet"]}
    ]
    assert (
        "ceo@example.com" not in refs[0]["snippet"] and len(refs[0]["snippet"]) <= 160
    )
    ev = project_event(
        {
            "type": "sources",
            "items": refs + [{"kind": "k", "score": 1, "source_id": "s"}] * 20,
        }
    )
    assert ev["type"] == "sources" and len(ev["items"]) == 8
    assert all(set(i) == {"kind", "date", "snippet"} for i in ev["items"])
