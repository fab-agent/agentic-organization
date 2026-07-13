"""
Policy CRUD, scope-filtering, and change-request proposal tests.
"""
from tests.conftest import make_personnel
import models


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_policy(client, company_id, **overrides):
    payload = {
        "company_id": company_id,
        "name": overrides.pop("name", "Default Policy"),
        "slug": overrides.pop("slug", "default-policy"),
        "content": overrides.pop("content", "Be helpful and honest."),
        "scope": overrides.pop("scope", "company"),
        **overrides,
    }
    return client.post("/policies", json=payload)


# ── Create ────────────────────────────────────────────────────────────────────

def test_create_policy_201(auth_client):
    co = auth_client._test_company
    r = _create_policy(auth_client, co.id)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Default Policy"
    assert data["scope"] == "company"
    assert data["is_active"] is True
    assert data["company_id"] == co.id


def test_create_policy_requires_auth(client):
    r = client.post("/policies", json={
        "company_id": "x", "name": "X", "slug": "x", "scope": "company"
    })
    assert r.status_code == 401


def test_create_department_scoped_policy(auth_client, db_session):
    co = auth_client._test_company
    dept = models.Department(name="Engineering", slug="engineering", company_id=co.id)
    db_session.add(dept)
    db_session.commit()
    r = _create_policy(auth_client, co.id, name="Eng Policy", slug="eng-policy",
                       scope="department", department_id=dept.id)
    assert r.status_code == 201
    data = r.json()
    assert data["scope"] == "department"
    assert data["department_id"] == dept.id


# ── List ──────────────────────────────────────────────────────────────────────

def test_list_policies_empty(auth_client):
    co = auth_client._test_company
    r = auth_client.get(f"/policies?company_id={co.id}")
    assert r.status_code == 200
    assert r.json() == []


def test_list_policies(auth_client):
    co = auth_client._test_company
    _create_policy(auth_client, co.id, name="Policy A", slug="pol-a")
    _create_policy(auth_client, co.id, name="Policy B", slug="pol-b")
    r = auth_client.get(f"/policies?company_id={co.id}")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "Policy A" in names
    assert "Policy B" in names


def test_list_policies_by_scope(auth_client):
    co = auth_client._test_company
    _create_policy(auth_client, co.id, name="Company P", slug="cp", scope="company")
    _create_policy(auth_client, co.id, name="Agent P", slug="ap", scope="agent")
    r = auth_client.get(f"/policies?company_id={co.id}&scope=company")
    assert r.status_code == 200
    assert all(p["scope"] == "company" for p in r.json())


# ── Get ───────────────────────────────────────────────────────────────────────

def test_get_policy(auth_client):
    co = auth_client._test_company
    pid = _create_policy(auth_client, co.id).json()["id"]
    r = auth_client.get(f"/policies/{pid}")
    assert r.status_code == 200
    assert r.json()["id"] == pid


def test_get_policy_not_found(auth_client):
    r = auth_client.get("/policies/nonexistent")
    assert r.status_code == 404


# ── Update ────────────────────────────────────────────────────────────────────

def test_update_policy_content(auth_client):
    co = auth_client._test_company
    pid = _create_policy(auth_client, co.id).json()["id"]
    r = auth_client.put(f"/policies/{pid}", json={"content": "Updated content."})
    assert r.status_code == 200
    assert r.json()["content"] == "Updated content."


def test_update_company_policy_ignores_is_active(auth_client):
    co = auth_client._test_company
    pid = _create_policy(auth_client, co.id, scope="company").json()["id"]
    # company-scoped policies can't be deactivated directly
    r = auth_client.put(f"/policies/{pid}", json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is True  # unchanged


def test_update_policy_not_found(auth_client):
    r = auth_client.put("/policies/bad-id", json={"name": "X"})
    assert r.status_code == 404


def test_update_policy_propose_cr(auth_client, db_session):
    co = auth_client._test_company
    p = make_personnel(db_session, co.id, name="PolicyAgent", slug="pol-agent")
    db_session.commit()
    pid = _create_policy(auth_client, co.id).json()["id"]
    r = auth_client.put(
        f"/policies/{pid}?propose=true&personnel_id={p.id}",
        json={"content": "New guideline"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "change_request_id" in data
    assert data["status"] == "submitted"


# ── Delete ────────────────────────────────────────────────────────────────────

def test_delete_policy(auth_client):
    co = auth_client._test_company
    pid = _create_policy(auth_client, co.id).json()["id"]
    r = auth_client.delete(f"/policies/{pid}")
    assert r.status_code == 204
    assert auth_client.get(f"/policies/{pid}").status_code == 404


def test_delete_policy_not_found(auth_client):
    r = auth_client.delete("/policies/bad-id")
    assert r.status_code == 404
