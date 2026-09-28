"""Process-level runtime settings: environment, CORS origins, background-job leader.

Everything here is read from environment variables at call time so tests can
monkeypatch them.
"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# Placeholder secrets shipped in .env.example files — never valid in production.
INSECURE_JWT_SECRETS = frozenset(
    {
        "",
        "change-me-in-production-please",
        "change-me-before-going-to-production",
    }
)
MIN_JWT_SECRET_LENGTH = 32

_DEV_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development").strip().lower() == "production"


def check_jwt_secret(secret: str) -> str | None:
    """Return why `secret` is unsafe for production, or None if it is fine."""
    if secret in INSECURE_JWT_SECRETS:
        return "JWT_SECRET is unset or still the example placeholder"
    if len(secret) < MIN_JWT_SECRET_LENGTH:
        return f"JWT_SECRET is shorter than {MIN_JWT_SECRET_LENGTH} characters"
    return None


def cors_origins() -> list[str]:
    """Allowed browser origins for cross-origin API calls.

    CORS_ORIGINS (comma-separated) wins when set. Otherwise: APP_URL, plus the
    Vite dev-server origins outside production. The production compose stacks
    serve the UI and API from one origin behind nginx, so they need no entries.
    """
    raw = os.getenv("CORS_ORIGINS")
    if raw is not None:
        return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    origins = [] if is_production() else list(_DEV_CORS_ORIGINS)
    app_url = os.getenv("APP_URL", "").strip().rstrip("/")
    if app_url and app_url not in origins:
        origins.append(app_url)
    return origins


@contextmanager
def startup_lock() -> Iterator[None]:
    """Serialize DB init + seeding across workers of one deployment.

    Without it, N workers starting on an empty database race on CREATE TABLE and
    uvicorn stops the whole process when one of them fails.
    """
    try:
        import fcntl
    except ImportError:  # Windows dev run — single process
        yield
        return
    path = Path(os.getenv("STARTUP_LOCK_FILE", "data/startup.lock"))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the lock


# ── Background-job leader ─────────────────────────────────────────────────────
#
# uvicorn/gunicorn with --workers N imports the app N times. APScheduler and
# Telegram long-polling must run in exactly one of them, otherwise every cron
# flow fires N times and Telegram rejects the concurrent getUpdates calls.
# The first worker to take an exclusive flock on the lock file becomes the
# leader; the OS releases the lock if that process dies, and the restarted
# worker takes it again.

_lock_fd: int | None = None


def acquire_job_leader() -> bool:
    """True if this process should run the scheduler and Telegram polling."""
    global _lock_fd
    if os.getenv("SCHEDULER_ENABLED", "true").strip().lower() in ("0", "false", "no"):
        return False
    if _lock_fd is not None:
        return True
    try:
        import fcntl
    except ImportError:  # Windows dev run — single process, no locking needed
        return True

    path = Path(os.getenv("SCHEDULER_LOCK_FILE", "data/scheduler.lock"))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    _lock_fd = fd
    return True


def is_job_leader() -> bool:
    return _lock_fd is not None
