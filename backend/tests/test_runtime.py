"""Runtime hardening: JWT secret guard, CORS origins, background-job leader,
and flow-schedule reloads that leave the system jobs alone."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

import core.runtime as runtime
import models
from tests.conftest import make_company, make_personnel

BACKEND_DIR = Path(__file__).resolve().parent.parent

# ── JWT secret ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "change-me-in-production-please",
        "change-me-before-going-to-production",
        "short",
    ],
)
def test_check_jwt_secret_rejects_placeholders_and_short(secret):
    assert runtime.check_jwt_secret(secret) is not None


def test_check_jwt_secret_accepts_strong():
    assert runtime.check_jwt_secret("a" * 64) is None


def _import_auth(env_overrides):
    env = {
        k: v for k, v in os.environ.items() if k not in ("JWT_SECRET", "ENVIRONMENT")
    }
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import services.auth"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


def test_production_refuses_to_start_with_placeholder_secret():
    result = _import_auth({"ENVIRONMENT": "production"})
    assert result.returncode != 0
    assert "Refusing to start" in result.stderr


def test_production_starts_with_strong_secret():
    result = _import_auth({"ENVIRONMENT": "production", "JWT_SECRET": "x" * 64})
    assert result.returncode == 0, result.stderr


def test_development_only_warns_on_placeholder_secret():
    result = _import_auth({"ENVIRONMENT": "development"})
    assert result.returncode == 0, result.stderr


# ── CORS ──────────────────────────────────────────────────────────────────────


def test_cors_dev_defaults_to_vite_and_app_url(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("APP_URL", "https://app.example.com/")
    assert runtime.cors_origins() == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://app.example.com",
    ]


def test_cors_production_only_app_url(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_URL", "https://app.example.com")
    assert runtime.cors_origins() == ["https://app.example.com"]


def test_cors_explicit_list_wins(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example/ ,")
    assert runtime.cors_origins() == ["https://a.example", "https://b.example"]


def test_cors_rejects_unlisted_origin(client):
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


# ── Background-job leader ─────────────────────────────────────────────────────


def test_only_one_process_becomes_job_leader(tmp_path, monkeypatch):
    import fcntl

    lock = tmp_path / "scheduler.lock"
    monkeypatch.setenv("SCHEDULER_LOCK_FILE", str(lock))
    monkeypatch.setattr(runtime, "_lock_fd", None)

    # Another worker already holds the lock.
    other = os.open(lock, os.O_RDWR | os.O_CREAT)
    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert runtime.acquire_job_leader() is False
        assert runtime.is_job_leader() is False
    finally:
        os.close(other)  # that worker exits

    assert runtime.acquire_job_leader() is True
    assert runtime.is_job_leader() is True
    os.close(runtime._lock_fd)


def test_scheduler_can_be_disabled(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setattr(runtime, "_lock_fd", None)
    assert runtime.acquire_job_leader() is False


# ── Flow schedule reload ──────────────────────────────────────────────────────


@pytest.fixture()
def leader_scheduler(monkeypatch):
    import main

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(lambda: None, "interval", minutes=15, id="rag_indexer")
    monkeypatch.setattr(main, "_scheduler", sched)
    monkeypatch.setattr(main, "_scheduled_flows", {})
    monkeypatch.setattr(runtime, "_lock_fd", 999)  # pretend this worker leads
    return main, sched


def _flow(session, **kw):
    co = make_company(session)
    p = make_personnel(session, co.id)
    f = models.Flow(
        company_id=co.id,
        personnel_id=p.id,
        name="Digest",
        schedule=kw.get("schedule", "0 9 * * *"),
        prompt="hi",
        enabled=kw.get("enabled", True),
    )
    session.add(f)
    session.commit()
    return f


def test_reload_keeps_system_jobs(leader_scheduler, db_session):
    main, sched = leader_scheduler
    flow = _flow(db_session)

    main._reload_flow_schedules()
    assert sched.get_job(f"flow:{flow.id}") is not None
    assert sched.get_job("rag_indexer") is not None

    flow.enabled = False
    db_session.add(flow)
    db_session.commit()
    main._reload_flow_schedules()
    assert sched.get_job(f"flow:{flow.id}") is None
    assert sched.get_job("rag_indexer") is not None


def test_reload_leaves_unchanged_flow_job_in_place(leader_scheduler, db_session):
    main, sched = leader_scheduler
    flow = _flow(db_session)

    main._reload_flow_schedules()
    job = sched.get_job(f"flow:{flow.id}")
    main._reload_flow_schedules()
    assert sched.get_job(f"flow:{flow.id}") is job

    flow.schedule = "30 8 * * *"
    db_session.add(flow)
    db_session.commit()
    main._reload_flow_schedules()
    assert main._scheduled_flows[f"flow:{flow.id}"] == "30 8 * * *"


def test_reload_is_noop_outside_leader(leader_scheduler, db_session, monkeypatch):
    main, sched = leader_scheduler
    monkeypatch.setattr(runtime, "_lock_fd", None)
    flow = _flow(db_session)
    main._reload_flow_schedules()
    assert sched.get_job(f"flow:{flow.id}") is None
