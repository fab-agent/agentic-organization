"""
Shared test fixtures.

Strategy:
- Each test gets a fresh in-memory SQLite DB (function scope).
- database.engine is monkeypatched so all app code hits the test DB.
- create_all() is called explicitly in patch_engine so tables always exist.
- run_seed / _sync_env_provider_keys are mocked out (no demo data noise).
- A logged-in `auth_client` fixture provides an authenticated TestClient.
"""
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlmodel import SQLModel, Session
from fastapi.testclient import TestClient

from sqlalchemy.pool import StaticPool

import database
import models
from services.auth import hash_password, create_access_token


# ── DB fixture ────────────────────────────────────────────────────────────────

@pytest.fixture()
def test_engine():
    # StaticPool: all connections share a single in-memory SQLite DB
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def patch_engine(test_engine, monkeypatch):
    """Redirect all DB access to the in-memory test engine."""
    monkeypatch.setattr(database, "engine", test_engine)
    # Belt-and-suspenders: ensure tables exist even if ordering varies
    SQLModel.metadata.create_all(test_engine)


# ── App / TestClient ──────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    """TestClient with seed and env-key sync suppressed."""
    from main import app
    with patch("main.run_seed"), \
         patch("main._sync_env_config"), \
         patch("main._sync_env_provider_keys"):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ── Direct DB session ─────────────────────────────────────────────────────────

@pytest.fixture()
def db_session(test_engine):
    with Session(test_engine) as s:
        yield s


# ── Seed helpers ──────────────────────────────────────────────────────────────

def make_company(session, name="Test Corp", slug="test-corp"):
    co = models.Company(name=name, slug=slug)
    session.add(co)
    session.flush()
    return co


def make_user(session, email="admin@test.com", name="Admin",
              password="test1234", is_active=True):
    u = models.User(email=email, name=name,
                    password_hash=hash_password(password), is_active=is_active)
    session.add(u)
    session.flush()
    return u


def make_member(session, user_id, company_id, role="founder"):
    m = models.CompanyMember(user_id=user_id, company_id=company_id, role=role)
    session.add(m)
    session.flush()
    return m


def make_company_for_user(session, user, name="Test Corp", slug="test-corp", role="founder"):
    """Create a company and immediately add user as a member (mirrors the API create flow)."""
    co = make_company(session, name=name, slug=slug)
    make_member(session, user.id, co.id, role=role)
    return co


def make_personnel(session, company_id, name="BotAgent", slug="bot-agent",
                   type="agent", title="Test Agent"):
    p = models.Personnel(name=name, slug=slug, type=type,
                          title=title, company_id=company_id)
    session.add(p)
    session.flush()
    return p


def make_agent_config(session, personnel_id, model="gpt-4o-mini",
                      responsible_id=None):
    cfg = models.AgentConfig(personnel_id=personnel_id, model=model,
                              status="active", responsible_id=responsible_id)
    session.add(cfg)
    session.flush()
    return cfg


def make_provider_key(session, provider="openai", plain_key="sk-test"):
    from core.security import encrypt
    pk = models.ProviderKey(provider=provider,
                             encrypted_key=encrypt(plain_key), status="active")
    session.add(pk)
    session.flush()
    return pk


# ── Authenticated client ──────────────────────────────────────────────────────

@pytest.fixture()
def auth_client(client, db_session):
    """TestClient pre-configured with a valid Authorization header."""
    co = make_company(db_session)
    u = make_user(db_session)
    make_member(db_session, u.id, co.id)
    db_session.commit()

    token = create_access_token(u.id)
    client.headers.update({"Authorization": f"Bearer {token}"})
    client._test_company = co
    client._test_user = u
    return client
