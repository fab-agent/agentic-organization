"""Learning signals: verified, owner-only, opt-in, redacted, capped, erasable."""

import pytest

from models import AgentSession, LearningSignal, SessionMessage
from services import learning
from services import work_review as wr
from services.auth import create_access_token
from tests.conftest import make_agent_config, make_member, make_personnel, make_user


def _h(u):
    return {"Authorization": f"Bearer {create_access_token(u.id)}"}


@pytest.fixture()
def world(auth_client, db_session):
    co = auth_client._test_company
    agent = make_personnel(db_session, co.id, name="Bot", slug="bot", type="agent")
    make_agent_config(db_session, agent.id)
    user = make_user(db_session, email="p@a.com", name="P")
    make_member(db_session, user.id, co.id, role="user")
    human = make_personnel(db_session, co.id, name="P H", slug="p-h", type="human")
    human.user_id = user.id
    db_session.add(human)
    sess = AgentSession(personnel_id=agent.id, user_id=user.id)
    db_session.add(sess)
    db_session.flush()
    answer = SessionMessage(session_id=sess.id, role="assistant", content="the answer")
    ask = SessionMessage(session_id=sess.id, role="user", content="q")
    db_session.add_all([answer, ask])
    wr.set_enabled(db_session, co.id, True)
    db_session.commit()
    return {
        "co": co.id,
        "user": user,
        "h": _h(user),
        "answer": answer.id,
        "ask": ask.id,
        "sess": sess.id,
        "human": human.id,
        "agent": agent.id,
    }


def _give(c, w, kind="thumbs_down", note=None, mid=None, h=None):
    return c.post(
        "/learning/signals",
        json={"message_id": mid or w["answer"], "kind": kind, "note": note},
        headers=h or w["h"],
    )


def test_a_person_can_give_and_withdraw_a_signal(auth_client, world, db_session):
    r = _give(
        auth_client,
        world,
        "correction",
        "Use the new invoice template. Mail ceo@example.com",
    )
    assert r.status_code == 201
    assert "ceo@example.com" not in r.json()["note"]
    mine = auth_client.get("/learning/signals/me", headers=world["h"]).json()
    assert [s["kind"] for s in mine] == ["correction"]
    assert (
        auth_client.delete(
            f"/learning/signals/{world['answer']}/correction", headers=world["h"]
        ).status_code
        == 204
    )
    assert auth_client.get("/learning/signals/me", headers=world["h"]).json() == []


def test_a_thumb_keeps_no_text_and_is_deduplicated(auth_client, world, db_session):
    _give(auth_client, world, "thumbs_down", "free text that is dropped")
    _give(auth_client, world, "thumbs_down", "again")
    rows = db_session.query(LearningSignal).all()
    assert len(rows) == 1 and rows[0].note is None


def test_only_the_owner_about_an_assistant_answer(auth_client, world, db_session):
    other = make_user(db_session, email="o@a.com", name="O")
    make_member(db_session, other.id, world["co"], role="user")
    db_session.commit()
    assert _give(auth_client, world, h=_h(other)).status_code == 404  # not their chat
    assert (
        _give(auth_client, world, mid=world["ask"]).status_code == 404
    )  # a user message
    assert _give(auth_client, world, mid="nope").status_code == 404
    assert (
        auth_client.post(
            "/learning/signals",
            json={"message_id": world["answer"], "kind": "love"},
            headers=world["h"],
        ).status_code
        == 422
    )
    assert (
        _give(auth_client, world, "correction").status_code == 422
    )  # a correction needs a note


def test_it_is_off_unless_the_company_switched_review_on(
    auth_client, world, db_session
):
    wr.set_enabled(db_session, world["co"], False)
    db_session.commit()
    assert _give(auth_client, world).status_code == 409
    assert db_session.query(LearningSignal).count() == 0


def test_a_person_needs_a_person_record_and_has_a_daily_cap(
    auth_client, world, db_session, monkeypatch
):
    nolink = make_user(db_session, email="n@a.com", name="N")
    make_member(db_session, nolink.id, world["co"], role="user")
    s2 = AgentSession(personnel_id=world["agent"], user_id=nolink.id)
    db_session.add(s2)
    db_session.flush()
    m2 = SessionMessage(session_id=s2.id, role="assistant", content="x")
    db_session.add(m2)
    db_session.commit()
    assert _give(auth_client, world, mid=m2.id, h=_h(nolink)).status_code == 409
    monkeypatch.setattr(learning, "MAX_PER_DAY", 1)
    assert _give(auth_client, world, "thumbs_up").status_code == 201
    assert _give(auth_client, world, "thumbs_down").status_code == 429


def test_erasing_a_person_erases_their_signals(auth_client, world, db_session):
    from services.work_review import erase_person

    _give(auth_client, world, "thumbs_up")
    assert db_session.query(LearningSignal).count() == 1
    erase_person(db_session, world["human"])
    db_session.commit()
    assert db_session.query(LearningSignal).count() == 0


def test_feedback_counts_reach_the_eval_summary_only_above_the_group_floor(
    auth_client, world, db_session
):
    _give(auth_client, world, "thumbs_down")
    s = auth_client.get(f"/eval/personas/{world['agent']}/summary").json()
    assert s["feedback"] == {"enough": False, "people": None}  # one person: withheld
    for i in range(2):
        u = make_user(db_session, email=f"x{i}@a.com", name=f"X{i}")
        make_member(db_session, u.id, world["co"], role="user")
        h = make_personnel(
            db_session, world["co"], name=f"H{i}", slug=f"h{i}", type="human"
        )
        h.user_id = u.id
        sess = AgentSession(personnel_id=world["agent"], user_id=u.id)
        db_session.add_all([h, sess])
        db_session.flush()
        m = SessionMessage(session_id=sess.id, role="assistant", content="a")
        db_session.add(m)
        db_session.commit()
        assert (
            _give(
                auth_client,
                world,
                "thumbs_up" if i else "thumbs_down",
                mid=m.id,
                h=_h(u),
            ).status_code
            == 201
        )
    s = auth_client.get(f"/eval/personas/{world['agent']}/summary").json()["feedback"]
    assert (
        s["enough"]
        and s["people"] == 3
        and s["thumbs_down"] == 2
        and s["thumbs_up"] == 1
    )
