"""
Flow CRUD and run tests.
_reload_flow_schedules is wrapped in try/except in flows.py so no mock needed.
"""
import pytest
from unittest.mock import patch
from tests.conftest import (
    make_company, make_personnel, make_user, make_member,
)
import models


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_flow(client, company_id, personnel_id, **overrides):
    payload = {
        "personnel_id": personnel_id,
        "name": overrides.pop("name", "Morning Digest"),
        "schedule": overrides.pop("schedule", "0 9 * * 1-5"),
        "prompt": overrides.pop("prompt", "Summarise yesterday's activity."),
        **overrides,
    }
    return client.post(f"/flows?company_id={company_id}", json=payload)


def _flow_setup(auth_client, db_session):
    co = auth_client._test_company
    p = make_personnel(db_session, co.id, name="FlowBot", slug="flowbot")
    db_session.commit()
    return co.id, p.id


# ── Create ────────────────────────────────────────────────────────────────────

def test_create_flow_201(auth_client, db_session):
    company_id, personnel_id = _flow_setup(auth_client, db_session)
    r = _make_flow(auth_client, company_id, personnel_id)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Morning Digest"
    assert data["schedule"] == "0 9 * * 1-5"
    assert data["enabled"] is True
    assert data["company_id"] == company_id


def test_create_flow_requires_auth(client, db_session):
    co = make_company(db_session)
    u = make_user(db_session, email="u@t.com")
    p = make_personnel(db_session, co.id, name="B", slug="b")
    db_session.commit()
    r = client.post(f"/flows?company_id={co.id}", json={
        "personnel_id": p.id, "name": "X", "schedule": "* * * * *", "prompt": "go"
    })
    assert r.status_code == 401


def test_create_flow_disabled(auth_client, db_session):
    company_id, personnel_id = _flow_setup(auth_client, db_session)
    r = _make_flow(auth_client, company_id, personnel_id, enabled=False)
    assert r.status_code == 201
    assert r.json()["enabled"] is False


# ── List ──────────────────────────────────────────────────────────────────────

def test_list_flows_empty(auth_client, db_session):
    company_id, _ = _flow_setup(auth_client, db_session)
    r = auth_client.get(f"/flows?company_id={company_id}")
    assert r.status_code == 200
    assert r.json() == []


def test_list_flows(auth_client, db_session):
    company_id, personnel_id = _flow_setup(auth_client, db_session)
    _make_flow(auth_client, company_id, personnel_id, name="Flow A")
    _make_flow(auth_client, company_id, personnel_id, name="Flow B")
    r = auth_client.get(f"/flows?company_id={company_id}")
    assert r.status_code == 200
    names = [f["name"] for f in r.json()]
    assert "Flow A" in names
    assert "Flow B" in names


def test_list_flows_without_company_filter(auth_client, db_session):
    company_id, personnel_id = _flow_setup(auth_client, db_session)
    _make_flow(auth_client, company_id, personnel_id)
    r = auth_client.get("/flows")
    assert r.status_code == 200
    assert len(r.json()) >= 1


# ── Get ───────────────────────────────────────────────────────────────────────

def test_get_flow(auth_client, db_session):
    company_id, personnel_id = _flow_setup(auth_client, db_session)
    created = _make_flow(auth_client, company_id, personnel_id).json()
    r = auth_client.get(f"/flows/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]
    assert r.json()["name"] == "Morning Digest"


def test_get_flow_not_found(auth_client):
    r = auth_client.get("/flows/nonexistent-id")
    assert r.status_code == 404


# ── Update ────────────────────────────────────────────────────────────────────

def test_update_flow_name(auth_client, db_session):
    company_id, personnel_id = _flow_setup(auth_client, db_session)
    flow_id = _make_flow(auth_client, company_id, personnel_id).json()["id"]
    r = auth_client.patch(f"/flows/{flow_id}", json={"name": "Evening Report"})
    assert r.status_code == 200
    assert r.json()["name"] == "Evening Report"


def test_update_flow_disable(auth_client, db_session):
    company_id, personnel_id = _flow_setup(auth_client, db_session)
    flow_id = _make_flow(auth_client, company_id, personnel_id).json()["id"]
    r = auth_client.patch(f"/flows/{flow_id}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_update_flow_not_found(auth_client):
    r = auth_client.patch("/flows/bad-id", json={"name": "X"})
    assert r.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────────

def test_delete_flow(auth_client, db_session):
    company_id, personnel_id = _flow_setup(auth_client, db_session)
    flow_id = _make_flow(auth_client, company_id, personnel_id).json()["id"]
    r = auth_client.delete(f"/flows/{flow_id}")
    assert r.status_code == 204
    assert auth_client.get(f"/flows/{flow_id}").status_code == 404


def test_delete_flow_not_found(auth_client):
    r = auth_client.delete("/flows/bad-id")
    assert r.status_code == 404


# ── Manual run ────────────────────────────────────────────────────────────────

def test_run_flow_now(auth_client, db_session):
    company_id, personnel_id = _flow_setup(auth_client, db_session)
    flow_id = _make_flow(auth_client, company_id, personnel_id).json()["id"]
    with patch("services.flow_runner.run_flow") as mock_run:
        mock_run.return_value = None
        r = auth_client.post(f"/flows/{flow_id}/run")
    assert r.status_code == 200
    mock_run.assert_called_once_with(flow_id)


def test_run_flow_not_found(auth_client):
    r = auth_client.post("/flows/nonexistent/run")
    assert r.status_code == 404
