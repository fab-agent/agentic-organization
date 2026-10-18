"""Learned harness artifacts: typed proposals, two-stage approval, versions, rollback."""

import json

import pytest

from models import AgentSession, Department, HarnessArtifact
from services import harness as h
from services.auth import create_access_token
from tests.conftest import (
    make_agent_config,
    make_member,
    make_personnel,
    make_user,
)


def _hdr(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def world(auth_client, db_session):
    co = auth_client._test_company
    dept = Department(company_id=co.id, name="Acc", slug="acc")
    db_session.add(dept)
    db_session.flush()
    agent = make_personnel(db_session, co.id, name="Bot", slug="bot", type="agent")
    agent.department_id = dept.id
    db_session.add(agent)
    make_agent_config(db_session, agent.id)
    proposer = make_user(db_session, email="p@a.com", name="P")
    make_member(db_session, proposer.id, co.id, role="user")
    head = make_user(db_session, email="h@a.com", name="H")
    make_member(db_session, head.id, co.id, role="dept_head")
    db_session.commit()
    return {
        "co": co.id,
        "agent": agent.id,
        "dept": dept.id,
        "proposer": _hdr(proposer),
        "head": _hdr(head),
        # the founder is the auth_client default header
    }


def _proposal(w, content="Always cite the invoice number.", base=0, **over):
    p = {
        "level": "person",
        "target_id": w["agent"],
        "kind": "prompt_text",
        "key": "main",
        "content": content,
        "base_version": base,
        "content_hash": h.content_hash(content),
        "evidence": [{"kind": "correction", "ref": "msg-1"}],
    }
    p.update(over)
    return p


def _submit(client, w, proposed):
    return client.post(
        f"/change-requests?company_id={w['co']}",
        json={
            "personnel_id": w["agent"],
            "change_type": "harness",
            "title": "learned",
            "proposed": proposed,
        },
        headers=w["proposer"],
    )


def _approve(client, w, cr_id):
    assert (
        client.post(
            f"/change-requests/{cr_id}/dept-approve", json={}, headers=w["head"]
        ).status_code
        == 200
    )
    r = client.post(f"/change-requests/{cr_id}/admin-approve", json={})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_typed_proposal_becomes_an_active_version_after_two_approvals(
    auth_client, world, db_session
):
    r = _submit(auth_client, world, _proposal(world))
    assert r.status_code == 201, r.text
    cr = _approve(auth_client, world, r.json()["id"])
    assert cr["status"] == "committed"
    art = db_session.query(HarnessArtifact).one()
    assert art.version == 1 and art.status == "active" and art.source_cr_id == cr["id"]
    assert art.content_hash == h.content_hash("Always cite the invoice number.")


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "policy_rule"},  # not on the allowlist
        {"kind": "tool_acl"},
        {"scope": "company"},  # unknown field
        {"token_scope": "admin"},
        {"content_hash": "0" * 64},  # hash does not match
        {"content": "x" * 4001},
        {
            "content": "use key sk-abcdefghijklmnopqrstuvwxyz0123"
        },  # looks like a credential
        {"level": "everything"},
        {"evidence": [{"kind": "document", "ref": "x"}]},  # evidence kinds are fixed
        {"key": "Not Valid!"},
    ],
)
def test_forbidden_or_malformed_proposals_are_refused(auth_client, world, bad):
    p = _proposal(world)
    if "content" in bad and "content_hash" not in bad:
        bad = {**bad, "content_hash": h.content_hash(bad["content"])}
    p.update(bad)
    r = _submit(auth_client, world, p)
    assert r.status_code == 422, (bad, r.text)


def test_target_must_belong_to_the_company(auth_client, world, db_session):
    other = Department(company_id="nope", name="X", slug="x")
    p = _proposal(world, level="department", target_id="not-a-department")
    assert _submit(auth_client, world, p).status_code == 422


def test_a_stale_base_fails_closed(auth_client, world, db_session):
    first = _submit(auth_client, world, _proposal(world, "one"))
    second = _submit(auth_client, world, _proposal(world, "two"))  # both based on v0
    _approve(auth_client, world, first.json()["id"])
    cr = _approve(auth_client, world, second.json()["id"])
    assert cr["status"] == "admin_approved" and "stale base" in cr["admin_note"]
    versions = db_session.query(HarnessArtifact).all()
    assert [a.content for a in versions if a.status == "active"] == ["one"]
    # proposing again on the current base works and supersedes
    third = _submit(auth_client, world, _proposal(world, "three", base=1))
    _approve(auth_client, world, third.json()["id"])
    db_session.expire_all()
    rows = {a.version: a.status for a in db_session.query(HarnessArtifact).all()}
    assert rows == {1: "superseded", 2: "active"}


def test_the_prompt_uses_active_guidance_and_reports_versions_only(
    auth_client, world, db_session
):
    from models import Personnel
    from services.context_assembly import assemble

    cr = _submit(auth_client, world, _proposal(world, "Greet in Turkish."))
    _approve(auth_client, world, cr.json()["id"])
    person = db_session.get(Personnel, world["agent"])
    dept = db_session.get(Department, world["dept"])
    arts = h.active_for(db_session, person, [dept.id])
    a = assemble(
        person, dept, [], None, company_id=person.company_id, harness_artifacts=arts
    )
    assert "Greet in Turkish." in a.text()
    rep = a.report()
    assert rep["harness"][0]["version"] == 1 and "Greet" not in json.dumps(rep)
    # without artifacts the prompt is unchanged
    assert (
        "harness"
        not in assemble(person, dept, [], None, company_id=person.company_id).report()
    )


def test_more_specific_guidance_comes_last(auth_client, world, db_session):
    from models import Personnel

    for level, target, text in (
        ("person", world["agent"], "person rule"),
        ("company", world["co"], "company rule"),
        ("department", world["dept"], "department rule"),
    ):
        db_session.add(
            HarnessArtifact(
                company_id=world["co"],
                level=level,
                target_id=target,
                kind="prompt_text",
                content=text,
                content_hash=h.content_hash(text),
            )
        )
    db_session.commit()
    person = db_session.get(Personnel, world["agent"])
    text = h.section_text(h.active_for(db_session, person, [world["dept"]]))
    assert (
        text.index("company rule")
        < text.index("department rule")
        < text.index("person rule")
    )


def test_a_running_chat_keeps_the_version_it_started_with(
    auth_client, world, db_session
):
    from models import Personnel
    from services.agent_runtime import _load_harness

    cr = _submit(auth_client, world, _proposal(world, "v1 text"))
    _approve(auth_client, world, cr.json()["id"])
    person = db_session.get(Personnel, world["agent"])
    dept = db_session.get(Department, world["dept"])
    sess = AgentSession(personnel_id=person.id)
    db_session.add(sess)
    db_session.commit()
    first = _load_harness(person, dept, sess.id)
    assert [a.content for a in first] == ["v1 text"]
    cr2 = _submit(auth_client, world, _proposal(world, "v2 text", base=1))
    _approve(auth_client, world, cr2.json()["id"])
    again = _load_harness(person, dept, sess.id)
    assert [a.content for a in again] == ["v1 text"]  # pinned
    fresh = AgentSession(personnel_id=person.id)
    db_session.add(fresh)
    db_session.commit()
    assert [a.content for a in _load_harness(person, dept, fresh.id)] == ["v2 text"]


def test_rollback_restores_the_previous_content_as_a_new_version(
    auth_client, world, db_session
):
    for text, base in (("old", 0), ("new", 1)):
        cr = _submit(auth_client, world, _proposal(world, text, base=base))
        _approve(auth_client, world, cr.json()["id"])
    active = db_session.query(HarnessArtifact).filter_by(status="active").one()
    assert active.content == "new"
    # only a final approver may roll back
    assert (
        auth_client.post(
            f"/harness/{active.id}/rollback", headers=world["head"]
        ).status_code
        == 403
    )
    r = auth_client.post(f"/harness/{active.id}/rollback")
    assert (
        r.status_code == 201
        and r.json()["content"] == "old"
        and r.json()["version"] == 3
    )
    db_session.expire_all()
    assert [
        a.version for a in db_session.query(HarnessArtifact).filter_by(status="active")
    ] == [3]
    # a version that is not active cannot be rolled back again
    assert auth_client.post(f"/harness/{active.id}/rollback").status_code == 409


def test_reading_is_limited_to_the_targets_managers(auth_client, world, db_session):
    cr = _submit(auth_client, world, _proposal(world, "secret-ish guidance"))
    _approve(auth_client, world, cr.json()["id"])
    art = db_session.query(HarnessArtifact).one()
    outsider = make_user(db_session, email="o@b.com", name="O")
    db_session.commit()
    assert (
        auth_client.get(f"/harness/{art.id}", headers=_hdr(outsider)).status_code == 404
    )
    assert (
        auth_client.get(f"/harness/{art.id}", headers=world["proposer"]).status_code
        == 404
    )
    assert (
        auth_client.get(f"/harness/{art.id}", headers=world["head"]).status_code == 200
    )
    assert (
        auth_client.get(
            f"/harness?company_id={world['co']}", headers=world["proposer"]
        ).json()
        == []
    )
    assert len(auth_client.get(f"/harness?company_id={world['co']}").json()) == 1
