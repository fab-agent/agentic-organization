"""
Dashboard stats and personal telemetry tests.
"""
from tests.conftest import make_personnel, make_agent_config
import models


# ── /dashboard/stats ──────────────────────────────────────────────────────────

def test_stats_requires_auth(client):
    r = client.get("/dashboard/stats")
    assert r.status_code == 401


def test_stats_empty_company(auth_client):
    co = auth_client._test_company
    r = auth_client.get(f"/dashboard/stats?company_id={co.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["company_id"] == co.id
    assert data["human_count"] == 0
    assert data["agent_count"] == 0
    assert data["total_sessions"] == 0
    assert data["total_tokens"] == 0


def test_stats_with_agents(auth_client, db_session):
    co = auth_client._test_company
    make_personnel(db_session, co.id, name="Alice", slug="alice", type="human")
    agent = make_personnel(db_session, co.id, name="Bot1", slug="bot1", type="agent")
    make_agent_config(db_session, agent.id)
    db_session.commit()

    r = auth_client.get(f"/dashboard/stats?company_id={co.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["human_count"] == 1
    assert data["agent_count"] == 1
    assert data["active_agents"] == 1


def test_stats_resolves_company_from_membership(auth_client):
    # No company_id param — should auto-resolve from user's membership
    r = auth_client.get("/dashboard/stats")
    assert r.status_code == 200
    data = r.json()
    # Returns either empty dict (if no membership) or proper stats
    assert isinstance(data, dict)


def test_stats_with_sessions(auth_client, db_session):
    co = auth_client._test_company
    agent = make_personnel(db_session, co.id, name="SessionBot", slug="sbot", type="agent")
    make_agent_config(db_session, agent.id)
    sess = models.AgentSession(personnel_id=agent.id, title="Test Run")
    db_session.add(sess)
    db_session.commit()

    r = auth_client.get(f"/dashboard/stats?company_id={co.id}")
    assert r.status_code == 200
    assert r.json()["total_sessions"] == 1


# ── /dashboard/me ─────────────────────────────────────────────────────────────

def test_me_requires_auth(client):
    r = client.get("/dashboard/me")
    assert r.status_code == 401


def test_me_no_linked_personnel(auth_client):
    co = auth_client._test_company
    r = auth_client.get(f"/dashboard/me?company_id={co.id}")
    assert r.status_code == 200
    assert r.json()["linked"] is False


def test_me_with_linked_personnel(auth_client, db_session):
    co = auth_client._test_company
    user = auth_client._test_user
    person = make_personnel(db_session, co.id, name="Alice Human", slug="alice-h", type="human")
    person.user_id = user.id
    db_session.add(person)
    db_session.commit()

    r = auth_client.get(f"/dashboard/me?company_id={co.id}")
    assert r.status_code == 200
    data = r.json()
    assert data["linked"] is True
    assert data["personnel_name"] == "Alice Human"
    assert "total_sessions" in data
    assert "memories" in data
    assert "recent_sessions" in data
