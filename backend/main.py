import logging
import os
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from version import VERSION

# Load .env if present (dev convenience)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from core.logging import setup_logging

setup_logging()
logger = logging.getLogger("app")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from api.a2a import router as a2a_router
from api.audit import router as audit_router
from api.auth import router as auth_router
from api.backup import router as backup_router
from api.change_requests import router as cr_router
from api.companies import router as companies_router
from api.dashboard import router as dashboard_router
from api.database import router as database_router
from api.departments import router as dept_router
from api.flows import router as flows_router
from api.git_sync import router as git_router
from api.inbox import router as inbox_router
from api.journal import router as journal_router
from api.onboarding import router as onboarding_router
from api.personnel import router as personnel_router
from api.policies import router as policies_router
from api.providers import router as providers_router
from api.sessions import router as sessions_router
from api.skills import router as skills_router
from api.social_media import router as social_media_router
from api.system import router as system_router
from api.task_requests import router as task_router
from api.telegram_bot import router as telegram_bot_router
from api.telegram_config import router as telegram_router
from api.users import router as users_router
from database import get_session, init_db
from seed import run_seed, seed_company_skills

app = FastAPI(
    title="3rdParty Agent Organization API",
    version="0.2.0",
    description="Self-hosted agentic organization management platform",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request, call_next):
    import time

    t0 = time.monotonic()
    response = await call_next(request)
    ms = round((time.monotonic() - t0) * 1000)
    level = logging.WARNING if response.status_code >= 400 else logging.INFO
    logger.log(
        level,
        "http",
        extra={
            "extra": {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": ms,
            }
        },
    )
    return response


app.include_router(auth_router)
app.include_router(users_router)
app.include_router(companies_router)
app.include_router(dept_router)
app.include_router(personnel_router)
app.include_router(providers_router)
app.include_router(git_router)
app.include_router(sessions_router)
app.include_router(a2a_router)
app.include_router(cr_router)
app.include_router(flows_router)
app.include_router(inbox_router)
app.include_router(task_router)
app.include_router(audit_router)
app.include_router(backup_router)
app.include_router(social_media_router)
app.include_router(journal_router)
app.include_router(database_router)
app.include_router(telegram_router)
app.include_router(telegram_bot_router)
app.include_router(dashboard_router)
app.include_router(skills_router)
app.include_router(policies_router)
app.include_router(onboarding_router)
app.include_router(system_router)


# ── Scheduler ─────────────────────────────────────────────────────────────────

_scheduler = BackgroundScheduler(timezone="UTC")


def _reload_flow_schedules():
    """Load all enabled flows from DB and schedule them."""
    from models import Flow
    from services.flow_runner import run_flow

    _scheduler.remove_all_jobs()
    with get_session() as session:
        flows = session.exec(select(Flow).where(Flow.enabled == True)).all()
        for flow in flows:
            try:
                parts = flow.schedule.split()
                if len(parts) == 5:
                    minute, hour, day, month, day_of_week = parts
                    _scheduler.add_job(
                        run_flow,
                        CronTrigger(
                            minute=minute,
                            hour=hour,
                            day=day,
                            month=month,
                            day_of_week=day_of_week,
                        ),
                        args=[flow.id],
                        id=flow.id,
                        replace_existing=True,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to schedule flow",
                    extra={"extra": {"flow_id": flow.id, "error": str(e)}},
                )
    logger.info("Flows scheduled", extra={"extra": {"count": len(flows)}})


# ── Startup ────────────────────────────────────────────────────────────────────


@app.on_event("startup")
def on_startup():
    init_db()
    run_seed()
    seed_company_skills()
    _sync_env_config()
    _sync_env_provider_keys()
    _reload_flow_schedules()

    # RAG: init DB and schedule incremental indexing every 15 minutes
    try:
        from services.rag_service import index_new_records, init_rag_db

        init_rag_db()
        _scheduler.add_job(
            index_new_records,
            "interval",
            minutes=15,
            id="rag_indexer",
            replace_existing=True,
        )
    except Exception as e:
        logger.warning("RAG init failed", extra={"extra": {"error": str(e)}})

    _scheduler.start()
    from api.telegram_bot import start_polling

    start_polling()
    logger.info("Application started")


@app.on_event("shutdown")
def on_shutdown():
    _scheduler.shutdown(wait=False)
    from api.telegram_bot import stop_polling

    stop_polling()
    logger.info("Application shutdown")


def _sync_env_config():
    """Import company settings from .env into AppConfig table (first run only)."""
    from models import AppConfig

    mapping = {
        "company_name": os.getenv("COMPANY_NAME", ""),
        "company_sector": os.getenv("COMPANY_SECTOR", ""),
        "company_website": os.getenv("COMPANY_WEBSITE", ""),
    }

    with get_session() as session:
        changed = False
        for key, value in mapping.items():
            if not value:
                continue
            if not session.get(AppConfig, key):
                session.add(AppConfig(key=key, value=value))
                changed = True
        if changed:
            session.commit()


def _sync_env_provider_keys():
    """Encrypt and store provider keys from .env (first run only, won't overwrite)."""
    from core.security import encrypt
    from models import ProviderKey
    from services.provider_service import SUPPORTED_PROVIDERS, test_provider_key

    env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "qwen": "QWEN_API_KEY",
    }

    with get_session() as session:
        changed = False
        for provider in SUPPORTED_PROVIDERS:
            plain_key = os.getenv(env_map.get(provider, ""), "").strip()
            if not plain_key:
                continue
            exists = session.exec(
                select(ProviderKey).where(ProviderKey.provider == provider)
            ).first()
            if exists:
                continue  # already configured via UI — don't overwrite

            valid = test_provider_key(provider, plain_key)
            session.add(
                ProviderKey(
                    provider=provider,
                    encrypted_key=encrypt(plain_key),
                    status="active" if valid else "invalid",
                    last_tested=datetime.utcnow(),
                )
            )
            print(f"  → provider sync: {provider} {'✓' if valid else '✗'}")
            changed = True
        if changed:
            session.commit()


# ── Root ───────────────────────────────────────────────────────────────────────


@app.get("/")
def root():
    return {"message": "Agentic Company API", "version": VERSION, "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
