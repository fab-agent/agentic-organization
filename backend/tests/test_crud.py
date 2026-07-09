"""CRUD endpoint tests: companies, departments, personnel, sessions."""
from tests.conftest import make_company_for_user, make_personnel, make_agent_config
import models


# ── Companies ─────────────────────────────────────────────────────────────────

def test_list_companies_empty(auth_client, db_session):
    r = auth_client.get("/companies")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_company(auth_client):
    r = auth_client.post("/companies", json={"name": "Yeni Şirket", "slug": "yeni-sirket"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Yeni Şirket"
    assert data["slug"] == "yeni-sirket"
    assert "id" in data


def test_get_company(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user, name="Fabrika", slug="fabrika")
    db_session.commit()
    r = auth_client.get(f"/companies/{co.id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Fabrika"


def test_get_company_not_found(auth_client):
    r = auth_client.get("/companies/nonexistent-id")
    assert r.status_code in (403, 404)


def test_update_company(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user, name="Eski Ad", slug="eski-ad")
    db_session.commit()
    r = auth_client.patch(f"/companies/{co.id}", json={"name": "Yeni Ad"})
    assert r.status_code == 200
    assert r.json()["name"] == "Yeni Ad"


def test_delete_company(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user, name="Silinecek", slug="silinecek")
    db_session.commit()
    r = auth_client.delete(f"/companies/{co.id}")
    assert r.status_code in (200, 204)
    r2 = auth_client.get(f"/companies/{co.id}")
    assert r2.status_code in (403, 404)


# ── Departments ───────────────────────────────────────────────────────────────

def test_create_department(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user, name="Dept Corp", slug="dept-corp")
    db_session.commit()
    r = auth_client.post(f"/departments?company_id={co.id}", json={
        "name": "Yazılım",
        "slug": "yazilim",
    })
    assert r.status_code == 201
    assert r.json()["name"] == "Yazılım"


def test_list_departments_by_company(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user, name="Filter Corp", slug="filter-corp")
    db_session.commit()
    auth_client.post(f"/departments?company_id={co.id}", json={"name": "QA", "slug": "qa"})
    auth_client.post(f"/departments?company_id={co.id}", json={"name": "Dev", "slug": "dev"})
    r = auth_client.get(f"/departments?company_id={co.id}")
    assert r.status_code == 200
    assert len(r.json()) == 2


# ── Personnel ─────────────────────────────────────────────────────────────────

def test_create_personnel(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user)
    db_session.commit()
    r = auth_client.post("/personnel", json={
        "company_id": co.id,
        "name": "Ahmet Yılmaz",
        "slug": "ahmet-yilmaz",
        "type": "human",
        "title": "Developer",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Ahmet Yılmaz"
    assert data["type"] == "human"


def test_list_personnel(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user)
    make_personnel(db_session, co.id, name="P1", slug="p1")
    make_personnel(db_session, co.id, name="P2", slug="p2")
    db_session.commit()
    r = auth_client.get(f"/personnel?company_id={co.id}")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "P1" in names
    assert "P2" in names


def test_filter_agents_only(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user)
    make_personnel(db_session, co.id, name="Human1", slug="human1", type="human")
    make_personnel(db_session, co.id, name="Agent1", slug="agent1", type="agent")
    db_session.commit()
    r = auth_client.get(f"/personnel?company_id={co.id}&type=agent")
    assert r.status_code == 200
    assert all(p["type"] == "agent" for p in r.json())


def test_get_personnel_by_id(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user)
    p = make_personnel(db_session, co.id, name="Birisi", slug="birisi")
    db_session.commit()
    r = auth_client.get(f"/personnel/{p.id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Birisi"


def test_update_personnel(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user)
    p = make_personnel(db_session, co.id, name="Eski", slug="eski")
    db_session.commit()
    r = auth_client.patch(f"/personnel/{p.id}", json={"name": "Yeni", "title": "Senior Dev"})
    assert r.status_code == 200
    assert r.json()["name"] == "Yeni"


def test_delete_personnel(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user)
    p = make_personnel(db_session, co.id, name="Silinecek", slug="silinecek-kisi")
    db_session.commit()
    r = auth_client.delete(f"/personnel/{p.id}")
    assert r.status_code in (200, 204)
    r2 = auth_client.get(f"/personnel/{p.id}")
    assert r2.status_code == 404


# ── Agent sessions ────────────────────────────────────────────────────────────

def test_create_session(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user)
    agent = make_personnel(db_session, co.id, name="Bot", slug="bot", type="agent")
    make_agent_config(db_session, agent.id)
    db_session.commit()
    r = auth_client.post("/sessions", json={
        "personnel_id": agent.id,
        "company_id": co.id,
    })
    assert r.status_code == 201
    data = r.json()
    assert data["personnel_id"] == agent.id
    assert data["status"] == "active"


def test_list_sessions(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user)
    agent = make_personnel(db_session, co.id, name="Bot", slug="bot2", type="agent")
    make_agent_config(db_session, agent.id)
    db_session.commit()
    auth_client.post("/sessions", json={"personnel_id": agent.id, "company_id": co.id})
    auth_client.post("/sessions", json={"personnel_id": agent.id, "company_id": co.id})
    r = auth_client.get(f"/sessions?personnel_id={agent.id}")
    assert r.status_code == 200
    assert len(r.json()) >= 2


def test_delete_session(auth_client, db_session):
    co = make_company_for_user(db_session, auth_client._test_user)
    agent = make_personnel(db_session, co.id, name="Bot3", slug="bot3", type="agent")
    make_agent_config(db_session, agent.id)
    db_session.commit()
    sess = auth_client.post("/sessions", json={"personnel_id": agent.id, "company_id": co.id}).json()
    r = auth_client.delete(f"/sessions/{sess['id']}")
    assert r.status_code in (200, 204)
