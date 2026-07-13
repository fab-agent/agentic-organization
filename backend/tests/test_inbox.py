"""
Inbox endpoint tests.
InboxMessages are created directly in the DB (no create endpoint).
"""
from datetime import datetime
from tests.conftest import make_company, make_user, make_member
import models


# ── Fixture helper ────────────────────────────────────────────────────────────

def _make_inbox_msg(db_session, recipient_user_id, company_id, **overrides):
    msg = models.InboxMessage(
        company_id=company_id,
        recipient_user_id=recipient_user_id,
        source_type=overrides.pop("source_type", "task_request"),
        source_id=overrides.pop("source_id", "task-001"),
        title=overrides.pop("title", "Test Message"),
        body=overrides.pop("body", "This is a test."),
        read=overrides.pop("read", False),
        created_at=datetime.utcnow(),
        **overrides,
    )
    db_session.add(msg)
    db_session.flush()
    return msg


# ── List ──────────────────────────────────────────────────────────────────────

def test_list_inbox_empty(auth_client):
    r = auth_client.get("/inbox")
    assert r.status_code == 200
    assert r.json() == []


def test_list_inbox_returns_own_messages(auth_client, db_session):
    user = auth_client._test_user
    co = auth_client._test_company
    _make_inbox_msg(db_session, user.id, co.id, title="Msg 1")
    _make_inbox_msg(db_session, user.id, co.id, title="Msg 2")
    db_session.commit()
    r = auth_client.get("/inbox")
    assert r.status_code == 200
    titles = [m["title"] for m in r.json()]
    assert "Msg 1" in titles
    assert "Msg 2" in titles


def test_list_inbox_does_not_return_others_messages(auth_client, db_session):
    co = auth_client._test_company
    other_user = make_user(db_session, email="other@t.com")
    db_session.commit()
    _make_inbox_msg(db_session, other_user.id, co.id, title="Other msg")
    db_session.commit()
    r = auth_client.get("/inbox")
    assert r.status_code == 200
    assert all(m["title"] != "Other msg" for m in r.json())


def test_list_inbox_unread_only(auth_client, db_session):
    user = auth_client._test_user
    co = auth_client._test_company
    _make_inbox_msg(db_session, user.id, co.id, title="Unread", read=False)
    _make_inbox_msg(db_session, user.id, co.id, title="Already read", read=True)
    db_session.commit()
    r = auth_client.get("/inbox?unread_only=true")
    assert r.status_code == 200
    data = r.json()
    assert all(not m["read"] for m in data)
    assert any(m["title"] == "Unread" for m in data)


def test_list_inbox_by_company(auth_client, db_session):
    user = auth_client._test_user
    co = auth_client._test_company
    _make_inbox_msg(db_session, user.id, co.id, title="For company")
    db_session.commit()
    r = auth_client.get(f"/inbox?company_id={co.id}")
    assert r.status_code == 200
    assert any(m["title"] == "For company" for m in r.json())


# ── Unread count ──────────────────────────────────────────────────────────────

def test_unread_count_zero(auth_client):
    r = auth_client.get("/inbox/unread-count")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_unread_count(auth_client, db_session):
    user = auth_client._test_user
    co = auth_client._test_company
    _make_inbox_msg(db_session, user.id, co.id, read=False)
    _make_inbox_msg(db_session, user.id, co.id, read=False)
    _make_inbox_msg(db_session, user.id, co.id, read=True)
    db_session.commit()
    r = auth_client.get("/inbox/unread-count")
    assert r.json()["count"] == 2


# ── Mark read ─────────────────────────────────────────────────────────────────

def test_mark_read(auth_client, db_session):
    user = auth_client._test_user
    co = auth_client._test_company
    msg = _make_inbox_msg(db_session, user.id, co.id, read=False)
    db_session.commit()
    r = auth_client.post(f"/inbox/{msg.id}/read")
    assert r.status_code == 200
    assert r.json()["read"] is True


def test_mark_read_wrong_user(auth_client, db_session):
    co = auth_client._test_company
    other = make_user(db_session, email="other2@t.com")
    db_session.commit()
    msg = _make_inbox_msg(db_session, other.id, co.id)
    db_session.commit()
    r = auth_client.post(f"/inbox/{msg.id}/read")
    assert r.status_code == 404


def test_mark_all_read(auth_client, db_session):
    user = auth_client._test_user
    co = auth_client._test_company
    _make_inbox_msg(db_session, user.id, co.id, read=False)
    _make_inbox_msg(db_session, user.id, co.id, read=False)
    db_session.commit()
    r = auth_client.post("/inbox/read-all")
    assert r.status_code == 200
    assert r.json()["marked"] == 2
    count = auth_client.get("/inbox/unread-count").json()["count"]
    assert count == 0


# ── Delete ────────────────────────────────────────────────────────────────────

def test_delete_message(auth_client, db_session):
    user = auth_client._test_user
    co = auth_client._test_company
    msg = _make_inbox_msg(db_session, user.id, co.id)
    db_session.commit()
    r = auth_client.delete(f"/inbox/{msg.id}")
    assert r.status_code == 204
    r2 = auth_client.get("/inbox")
    assert all(m["id"] != msg.id for m in r2.json())


def test_delete_message_wrong_user(auth_client, db_session):
    co = auth_client._test_company
    other = make_user(db_session, email="other3@t.com")
    db_session.commit()
    msg = _make_inbox_msg(db_session, other.id, co.id)
    db_session.commit()
    r = auth_client.delete(f"/inbox/{msg.id}")
    assert r.status_code == 404
