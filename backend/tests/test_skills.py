"""
Company skill CRUD and agent-assignment tests.
"""
from tests.conftest import make_company, make_personnel, make_agent_config
import models


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_skill(client, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "name": overrides.pop("name", "Web Search"),
        "slug": overrides.pop("slug", "web-search"),
        "description": overrides.pop("description", "Search the web"),
        "skill_type": overrides.pop("skill_type", "builtin"),
        **overrides,
    }
    return client.post("/company-skills", json=payload)


# ── Create ────────────────────────────────────────────────────────────────────

def test_create_skill_201(auth_client):
    co = auth_client._test_company
    r = _create_skill(auth_client, co.id)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Web Search"
    assert data["slug"] == "web-search"
    assert data["company_id"] == co.id
    assert data["is_active"] is True
    assert data["assigned_agents"] == []


def test_create_skill_requires_auth(client):
    r = client.post("/company-skills", json={
        "company_id": "x", "name": "X", "slug": "x", "skill_type": "builtin"
    })
    assert r.status_code == 401


def test_create_skill_with_content(auth_client):
    co = auth_client._test_company
    r = _create_skill(auth_client, co.id, name="Custom Skill", slug="custom",
                      skill_type="custom", content="Do something useful")
    assert r.status_code == 201
    assert r.json()["content"] == "Do something useful"
    assert r.json()["skill_type"] == "custom"


# ── List ──────────────────────────────────────────────────────────────────────

def test_list_skills_empty(auth_client):
    r = auth_client.get(f"/company-skills?company_id={auth_client._test_company.id}")
    assert r.status_code == 200
    assert r.json() == []


def test_list_skills(auth_client):
    co = auth_client._test_company
    _create_skill(auth_client, co.id, name="Skill A", slug="skill-a")
    _create_skill(auth_client, co.id, name="Skill B", slug="skill-b")
    r = auth_client.get(f"/company-skills?company_id={co.id}")
    assert r.status_code == 200
    names = [s["name"] for s in r.json()]
    assert "Skill A" in names
    assert "Skill B" in names


def test_list_skills_no_filter(auth_client):
    co = auth_client._test_company
    _create_skill(auth_client, co.id)
    r = auth_client.get("/company-skills")
    assert r.status_code == 200
    assert len(r.json()) >= 1


# ── Get ───────────────────────────────────────────────────────────────────────

def test_get_skill(auth_client):
    co = auth_client._test_company
    skill_id = _create_skill(auth_client, co.id).json()["id"]
    r = auth_client.get(f"/company-skills/{skill_id}")
    assert r.status_code == 200
    assert r.json()["id"] == skill_id


def test_get_skill_not_found(auth_client):
    r = auth_client.get("/company-skills/nonexistent")
    assert r.status_code == 404


# ── Update ────────────────────────────────────────────────────────────────────

def test_update_skill(auth_client):
    co = auth_client._test_company
    skill_id = _create_skill(auth_client, co.id).json()["id"]
    r = auth_client.put(f"/company-skills/{skill_id}", json={"name": "Web Search Pro"})
    assert r.status_code == 200
    assert r.json()["name"] == "Web Search Pro"


def test_update_skill_deactivate(auth_client):
    co = auth_client._test_company
    skill_id = _create_skill(auth_client, co.id).json()["id"]
    r = auth_client.put(f"/company-skills/{skill_id}", json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_update_skill_not_found(auth_client):
    r = auth_client.put("/company-skills/bad-id", json={"name": "X"})
    assert r.status_code == 404


def test_update_skill_propose_cr(auth_client, db_session):
    co = auth_client._test_company
    p = make_personnel(db_session, co.id, name="Agent", slug="agent-s")
    db_session.commit()
    skill_id = _create_skill(auth_client, co.id).json()["id"]
    r = auth_client.put(
        f"/company-skills/{skill_id}?propose=true&personnel_id={p.id}",
        json={"description": "Updated description"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "change_request_id" in data
    assert data["status"] == "submitted"


# ── Delete ────────────────────────────────────────────────────────────────────

def test_delete_skill(auth_client):
    co = auth_client._test_company
    skill_id = _create_skill(auth_client, co.id).json()["id"]
    r = auth_client.delete(f"/company-skills/{skill_id}")
    assert r.status_code == 204
    assert auth_client.get(f"/company-skills/{skill_id}").status_code == 404


def test_delete_skill_not_found(auth_client):
    r = auth_client.delete("/company-skills/bad-id")
    assert r.status_code == 404


# ── Assign / Unassign ─────────────────────────────────────────────────────────

def test_assign_skill_to_agent(auth_client, db_session):
    co = auth_client._test_company
    agent = make_personnel(db_session, co.id, name="Agent", slug="ag1")
    cfg = make_agent_config(db_session, agent.id)
    db_session.commit()

    skill_id = _create_skill(auth_client, co.id).json()["id"]
    r = auth_client.post(f"/company-skills/{skill_id}/assign/{cfg.id}")
    assert r.status_code == 201
    assert r.json()["status"] == "assigned"

    # Verify via get
    skill = auth_client.get(f"/company-skills/{skill_id}").json()
    assert cfg.id in skill["assigned_agents"]


def test_assign_skill_already_assigned(auth_client, db_session):
    co = auth_client._test_company
    agent = make_personnel(db_session, co.id, name="Agent2", slug="ag2")
    cfg = make_agent_config(db_session, agent.id)
    db_session.commit()

    skill_id = _create_skill(auth_client, co.id).json()["id"]
    auth_client.post(f"/company-skills/{skill_id}/assign/{cfg.id}")
    r = auth_client.post(f"/company-skills/{skill_id}/assign/{cfg.id}")
    assert r.status_code == 201
    assert r.json()["status"] == "already_assigned"


def test_unassign_skill(auth_client, db_session):
    co = auth_client._test_company
    agent = make_personnel(db_session, co.id, name="Agent3", slug="ag3")
    cfg = make_agent_config(db_session, agent.id)
    db_session.commit()

    skill_id = _create_skill(auth_client, co.id).json()["id"]
    auth_client.post(f"/company-skills/{skill_id}/assign/{cfg.id}")
    r = auth_client.delete(f"/company-skills/{skill_id}/assign/{cfg.id}")
    assert r.status_code == 204

    skill = auth_client.get(f"/company-skills/{skill_id}").json()
    assert cfg.id not in skill["assigned_agents"]
