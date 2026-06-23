from typing import Optional
from fastapi import APIRouter, HTTPException
from sqlmodel import select

from api.audit import log_action
from core.security import encrypt, decrypt
from database import get_session
from models import GitConfig, SyncLog
from schemas import GitConfigCreate, GitConfigUpdate, PushRequest
from services.git_service import git_service

router = APIRouter(prefix="/git", tags=["git"])


def _config_to_dict(cfg: GitConfig) -> dict:
    return {
        "id":              cfg.id,
        "company_id":      cfg.company_id,
        "provider":        cfg.provider,
        "repo_url":        cfg.repo_url,
        "branch":          cfg.branch,
        "sync_interval":   cfg.sync_interval,
        "auto_pr":         cfg.auto_pr,
        "status":          cfg.status,
        "last_synced":     cfg.last_synced.isoformat() if cfg.last_synced else None,
        "last_commit_sha": cfg.last_commit_sha,
        "created_at":      cfg.created_at.isoformat(),
    }


def _log_to_dict(log: SyncLog) -> dict:
    return {
        "id":            log.id,
        "direction":     log.direction,
        "files_changed": log.files_changed,
        "commit_sha":    log.commit_sha,
        "pr_url":        log.pr_url,
        "status":        log.status,
        "message":       log.message,
        "created_at":    log.created_at.isoformat(),
    }


def _get_config_or_404(session, company_id: Optional[str] = None) -> GitConfig:
    q = select(GitConfig)
    if company_id:
        q = q.where(GitConfig.company_id == company_id)
    cfg = session.exec(q).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Git bağlantısı yapılandırılmamış")
    return cfg


# ── Config CRUD ───────────────────────────────────────────────────────────────

@router.get("/config")
def get_git_config(company_id: Optional[str] = None):
    with get_session() as session:
        q = select(GitConfig)
        if company_id:
            q = q.where(GitConfig.company_id == company_id)
        cfg = session.exec(q).first()
        if not cfg:
            return None
        return _config_to_dict(cfg)


@router.post("/config", status_code=201)
def create_git_config(body: GitConfigCreate, company_id: Optional[str] = None):
    with get_session() as session:
        q = select(GitConfig)
        if company_id:
            q = q.where(GitConfig.company_id == company_id)
        existing = session.exec(q).first()
        if existing:
            raise HTTPException(status_code=409, detail="Bu şirket için zaten bir git bağlantısı mevcut. Önce silin.")

        cfg = GitConfig(
            company_id=company_id,
            provider=body.provider,
            repo_url=body.repo_url,
            branch=body.branch,
            encrypted_token=encrypt(body.token),
            sync_interval=body.sync_interval,
            auto_pr=body.auto_pr,
        )
        session.add(cfg)
        log_action(session, "create", "git_config", entity_id=cfg.id, entity_name=cfg.repo_url, company_id=cfg.company_id)
        session.commit()
        session.refresh(cfg)
        return _config_to_dict(cfg)


@router.patch("/config")
def update_git_config(body: GitConfigUpdate, company_id: Optional[str] = None):
    with get_session() as session:
        cfg = _get_config_or_404(session, company_id)
        if body.branch is not None:        cfg.branch          = body.branch
        if body.token is not None:         cfg.encrypted_token = encrypt(body.token)
        if body.sync_interval is not None: cfg.sync_interval   = body.sync_interval
        if body.auto_pr is not None:       cfg.auto_pr         = body.auto_pr
        session.add(cfg)
        log_action(session, "update", "git_config", entity_id=cfg.id, entity_name=cfg.repo_url, company_id=cfg.company_id)
        session.commit()
        session.refresh(cfg)
        return _config_to_dict(cfg)


@router.delete("/config", status_code=204)
def delete_git_config(company_id: Optional[str] = None):
    with get_session() as session:
        cfg = _get_config_or_404(session, company_id)
        log_action(session, "delete", "git_config", entity_id=cfg.id, entity_name=cfg.repo_url, company_id=cfg.company_id)
        session.delete(cfg)
        session.commit()


# ── Sync operations ───────────────────────────────────────────────────────────

@router.post("/pull")
def git_pull(company_id: Optional[str] = None):
    with get_session() as session:
        cfg = _get_config_or_404(session, company_id)
        log = git_service.pull(session, cfg)
        log_action(session, "sync", "git_config", entity_id=cfg.id, entity_name=cfg.repo_url, company_id=cfg.company_id, details={"direction": "pull", "status": log.status})
        session.commit()
        return _log_to_dict(log)


@router.post("/push")
def git_push(body: PushRequest, company_id: Optional[str] = None):
    with get_session() as session:
        cfg = _get_config_or_404(session, company_id)
        log = git_service.push(session, cfg, body.message)
        log_action(session, "sync", "git_config", entity_id=cfg.id, entity_name=cfg.repo_url, company_id=cfg.company_id, details={"direction": "push", "status": log.status})
        session.commit()
        return _log_to_dict(log)


@router.get("/diff")
def git_diff(company_id: Optional[str] = None):
    with get_session() as session:
        cfg = _get_config_or_404(session, company_id)
        return git_service.diff(session, cfg)


# ── Sync logs ─────────────────────────────────────────────────────────────────

@router.get("/logs")
def list_sync_logs(limit: int = 20):
    with get_session() as session:
        logs = session.exec(
            select(SyncLog).order_by(SyncLog.created_at.desc()).limit(limit)
        ).all()
        return [_log_to_dict(l) for l in logs]
