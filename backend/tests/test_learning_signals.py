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


def test_an_identical_signal_inserted_meanwhile_is_idempotent(
    auth_client, world, db_session, monkeypatch
):

    # the first insert happens "behind our back" after the existence check
    real = db_session.exec
    state = {"done": False}

    _give(auth_client, world, "thumbs_up")
    existing = db_session.query(LearningSignal).one()
    db_session.delete(existing)
    db_session.commit()

    orig_record = learning.record

    def racy(session, user, mid, kind, note):
        if not state["done"]:
            state["done"] = True
            session.add(
                LearningSignal(
                    company_id=world["co"],
                    personnel_id=world["human"],
                    persona_id=world["agent"],
                    user_id=user.id,
                    session_id=world["sess"],
                    message_id=mid,
                    kind=kind,
                )
            )
            session.commit()
        return orig_record(session, user, mid, kind, note)

    monkeypatch.setattr("api.learning.learning.record", racy)
    r = _give(auth_client, world, "thumbs_up")
    assert r.status_code == 201
    assert db_session.query(LearningSignal).count() == 1


def test_withdrawing_frees_no_daily_quota_and_rewrites_are_bounded(
    auth_client, world, db_session, monkeypatch
):
    monkeypatch.setattr(learning, "MAX_PER_DAY", 1)
    assert _give(auth_client, world, "thumbs_up").status_code == 201
    auth_client.delete(
        f"/learning/signals/{world['answer']}/thumbs_up", headers=world["h"]
    )
    assert (
        _give(auth_client, world, "thumbs_down").status_code == 429
    )  # the withdrawn one still counts
    monkeypatch.setattr(learning, "MAX_PER_DAY", 50)
    for i in range(learning.MAX_REVISIONS):
        assert _give(auth_client, world, "correction", f"note {i}").status_code == 201
    assert (
        _give(auth_client, world, "correction", "one more").status_code == 201
    )  # creation, revision 0
    for i in range(learning.MAX_REVISIONS):
        _give(auth_client, world, "correction", f"rev {i}")
    assert _give(auth_client, world, "correction", "too many").status_code == 429


def test_a_thumb_is_one_mutually_exclusive_vote(auth_client, world, db_session):
    _give(auth_client, world, "thumbs_up")
    _give(auth_client, world, "thumbs_down")
    live = [
        s["kind"]
        for s in auth_client.get("/learning/signals/me", headers=world["h"]).json()
    ]
    assert live == ["thumbs_down"]


def test_a_person_removed_from_the_company_cannot_contribute(
    auth_client, world, db_session
):
    from models import CompanyMember

    db_session.query(CompanyMember).filter_by(user_id=world["user"].id).delete()
    db_session.commit()
    assert _give(auth_client, world, "thumbs_up").status_code == 404


def test_switching_review_off_hides_collected_feedback_and_retention_purges(
    auth_client, world, db_session
):
    from datetime import datetime, timedelta

    for i in range(3):
        u = make_user(db_session, email=f"q{i}@a.com", name=f"Q{i}")
        make_member(db_session, u.id, world["co"], role="user")
        h = make_personnel(
            db_session, world["co"], name=f"QH{i}", slug=f"qh{i}", type="human"
        )
        h.user_id = u.id
        sess = AgentSession(personnel_id=world["agent"], user_id=u.id)
        db_session.add_all([h, sess])
        db_session.flush()
        m = SessionMessage(session_id=sess.id, role="assistant", content="a")
        db_session.add(m)
        db_session.commit()
        assert (
            _give(auth_client, world, "thumbs_up", mid=m.id, h=_h(u)).status_code == 201
        )
    assert (
        auth_client.get(f"/eval/personas/{world['agent']}/summary").json()["feedback"][
            "enough"
        ]
        is True
    )
    wr.set_enabled(db_session, world["co"], False)
    db_session.commit()
    assert (
        auth_client.get(f"/eval/personas/{world['agent']}/summary").json()["feedback"][
            "enough"
        ]
        is False
    )
    # retention: old signals are purged even though review is off
    for r in db_session.query(LearningSignal).all():
        r.created_at = datetime.utcnow() - timedelta(days=4000)
        db_session.add(r)
    db_session.commit()
    wr.purge_expired()
    db_session.expire_all()
    assert db_session.query(LearningSignal).count() == 0


def test_erasing_the_agent_persona_erases_feedback_about_it(
    auth_client, world, db_session
):
    _give(auth_client, world, "thumbs_up")
    wr.erase_person(db_session, world["agent"])
    db_session.commit()
    assert db_session.query(LearningSignal).count() == 0
