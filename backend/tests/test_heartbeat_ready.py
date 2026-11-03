"""ADR-0038: a session can be alive and still not policy-ready; the two are reported apart."""

import re
from datetime import datetime, timedelta

from models import AppConfig, PersonaHeartbeat, Policy
from services import monitoring
from services import policy_engine as pe
from services.gateway_auth import create_persona_token
from tests.conftest import (
    create_access_token,
    make_agent_config,
    make_company,
    make_personnel,
)

BAD = "```policy\n[{broken\n```"


def _persona(db, company, slug="ada"):
    p = make_personnel(db, company.id, name=slug.title(), slug=slug)
    make_agent_config(db, p.id, model="qwen-turbo")
    db.commit()
    return p, create_persona_token(p.id, company.id)


def _beat(client, token):
    return client.post(
        "/workstation/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )


def _bad_policy(db, company):
    db.add(
        Policy(
            company_id=company.id, name="bad", slug="bad", content=BAD, scope="company"
        )
    )
    db.commit()


# ── check_ready ──────────────────────────────────────────────────────────────


def test_a_readable_policy_is_ready(auth_client, db_session):
    p, _ = _persona(db_session, auth_client._test_company)
    r = pe.check_ready(p.id)
    assert r["ready"] is True and r["reason"] is None and r["mode"] == "dry_run"


def test_a_malformed_policy_block_is_not_ready(auth_client, db_session):
    p, _ = _persona(db_session, auth_client._test_company)
    _bad_policy(db_session, auth_client._test_company)
    r = pe.check_ready(p.id)
    assert (r["ready"], r["reason"]) == (False, "policy_malformed")


def test_an_invalid_mode_is_not_ready(auth_client, db_session):
    p, _ = _persona(db_session, auth_client._test_company)
    db_session.add(AppConfig(key="policy.mode", value="banana"))
    db_session.commit()
    r = pe.check_ready(p.id)
    assert (r["ready"], r["reason"]) == (False, "invalid_mode")


def test_an_unknown_persona_is_not_ready(auth_client):
    r = pe.check_ready("no-such-persona")
    assert (r["ready"], r["reason"]) == (False, "scope_unreadable")


def test_a_database_error_is_not_ready_and_leaks_nothing(
    auth_client, db_session, monkeypatch
):
    p, _ = _persona(db_session, auth_client._test_company)

    def boom(*a, **k):
        raise RuntimeError("secret connection string")

    monkeypatch.setattr(pe, "applicable_policy_contents", boom)
    r = pe.check_ready(p.id)
    assert r["ready"] is False and r["reason"] == "policy_unreadable"
    assert "secret" not in repr(r)


def test_policy_off_counts_as_ready_and_says_off(auth_client, db_session):
    p, _ = _persona(db_session, auth_client._test_company)
    db_session.add(AppConfig(key="policy.mode", value="off"))
    db_session.commit()
    r = pe.check_ready(p.id)
    assert r["ready"] is True and r["mode"] == "off"


# ── the heartbeat ────────────────────────────────────────────────────────────


def test_the_ping_is_recorded_even_when_the_policy_is_not_ready(
    auth_client, db_session
):
    p, token = _persona(db_session, auth_client._test_company)
    _bad_policy(db_session, auth_client._test_company)
    r = _beat(auth_client, token)
    assert r.status_code == 202
    body = r.json()
    assert body["ok"] is True and body["policy_ready"] is False
    assert body["policy_reason"] == "policy_malformed"
    assert body["fail_closed"] is True  # the gate denies, and the answer says so
    row = db_session.get(PersonaHeartbeat, p.id)
    assert row.policy_ready is False and row.policy_reason == "policy_malformed"


def test_a_ready_policy_is_reported_and_replaces_an_earlier_failure(
    auth_client, db_session
):
    p, token = _persona(db_session, auth_client._test_company)
    _bad_policy(db_session, auth_client._test_company)
    assert _beat(auth_client, token).json()["policy_ready"] is False
    pol = db_session.query(Policy).first()
    pol.content = "plain prose"
    db_session.add(pol)
    db_session.commit()
    body = _beat(auth_client, token).json()
    assert body["policy_ready"] is True and body["policy_reason"] is None
    db_session.expire_all()
    assert db_session.get(PersonaHeartbeat, p.id).policy_ready is True


# ── monitoring ───────────────────────────────────────────────────────────────


def _founder_view(client, db_session, company, user):
    return client.get(
        f"/admin/monitoring?company_id={company.id}",
        headers={"Authorization": f"Bearer {create_access_token(user.id)}"},
    )


def test_sessions_section_separates_alive_from_ready(auth_client, db_session):
    co = auth_client._test_company
    a, ta = _persona(db_session, co, "ada")
    b, tb = _persona(db_session, co, "bob")
    _beat(auth_client, ta)
    _bad_policy(db_session, co)
    _beat(auth_client, tb)
    s = monitoring._sessions(co.id, datetime.utcnow())
    # ada pinged before the policy broke (still counted ready as of her last ping), bob after
    assert (s["alive"], s["ready"], s["not_ready"]) == (2, 1, 1)
    assert [n["name"] for n in s["not_ready_sessions"]] == ["Bob"]
    assert s["status"] == "warn"
    assert {n["reason"] for n in s["not_ready_sessions"]} == {"policy_malformed"}


def test_a_session_that_stopped_pinging_is_not_alive(auth_client, db_session):
    co = auth_client._test_company
    p, tok = _persona(db_session, co)
    _beat(auth_client, tok)
    row = db_session.get(PersonaHeartbeat, p.id)
    row.last_seen = datetime.utcnow() - timedelta(minutes=30)
    db_session.add(row)
    db_session.commit()
    s = monitoring._sessions(co.id, datetime.utcnow())
    assert s["alive"] == 0 and s["seen_ever"] == 1
    assert (s["status"], s["reason"]) == ("unknown", "no_live_sessions")


def test_an_old_session_without_the_check_is_unknown_never_ready(
    auth_client, db_session
):
    co = auth_client._test_company
    p, _ = _persona(db_session, co)
    db_session.add(
        PersonaHeartbeat(persona_id=p.id, company_id=co.id, last_seen=datetime.utcnow())
    )
    db_session.commit()
    s = monitoring._sessions(co.id, datetime.utcnow())
    assert (s["alive"], s["ready"], s["unchecked"]) == (1, 0, 1)
    assert (s["status"], s["reason"]) == ("unknown", "policy_not_checked")


def test_another_companys_sessions_are_never_counted(auth_client, db_session):
    mine = auth_client._test_company
    other = make_company(db_session, name="Other", slug="other")
    p, tok = _persona(db_session, other, "zed")
    _beat(auth_client, tok)
    s = monitoring._sessions(mine.id, datetime.utcnow())
    assert s["alive"] == 0 and s["seen_ever"] == 0


def test_a_stored_reason_outside_the_list_is_shown_as_unreadable(
    auth_client, db_session
):
    co = auth_client._test_company
    p, _ = _persona(db_session, co)
    db_session.add(
        PersonaHeartbeat(
            persona_id=p.id,
            company_id=co.id,
            last_seen=datetime.utcnow(),
            policy_ready=False,
            policy_reason="/etc/passwd: secret path",
        )
    )
    db_session.commit()
    s = monitoring._sessions(co.id, datetime.utcnow())
    assert s["not_ready_sessions"][0]["reason"] == "policy_unreadable"
    assert "passwd" not in repr(s)


def test_the_endpoint_carries_the_section_and_stays_founder_only(
    auth_client, db_session
):
    co = auth_client._test_company
    _, tok = _persona(db_session, co)
    _beat(auth_client, tok)
    r = auth_client.get(f"/admin/monitoring?company_id={co.id}")
    assert r.status_code == 200
    assert r.json()["sections"]["sessions"]["alive"] == 1
    anon = auth_client.get(
        f"/admin/monitoring?company_id={co.id}", headers={"Authorization": ""}
    )
    assert anon.status_code in (401, 403)


def test_the_migration_matches_the_model():
    text = open("migrations/versions/d5a1b7c3f024_heartbeat_policy_ready.py").read()
    for col in ("policy_ready", "policy_reason", "policy_mode"):
        assert col in PersonaHeartbeat.__table__.columns.keys()
        assert re.search(rf'"{col}"', text), col
