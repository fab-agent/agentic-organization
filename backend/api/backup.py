"""On-demand database backup to S3-compatible storage."""

import io
import json
import logging
import sqlite3
import tempfile
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user, require_manager
from core.security import decrypt, encrypt
from database import get_session
from models import AppConfig, User

logger = logging.getLogger("app")
router = APIRouter(prefix="/backup", tags=["backup"])

# AppConfig keys used for backup settings
_KEY_ENDPOINT = "backup_endpoint_url"
_KEY_BUCKET = "backup_bucket"
_KEY_PREFIX = "backup_prefix"
_KEY_REGION = "backup_region"
_KEY_ACCESS_KEY = "backup_access_key"
_KEY_SECRET_ENC = "backup_secret_key_encrypted"
_KEY_HISTORY = "backup_history_json"


def _get_cfg(session, key: str) -> str | None:
    row = session.get(AppConfig, key)
    return row.value if row else None


def _set_cfg(session, key: str, value: str) -> None:
    existing = session.get(AppConfig, key)
    if existing:
        existing.value = value
        session.add(existing)
    else:
        session.add(AppConfig(key=key, value=value))


# ── Schemas ───────────────────────────────────────────────────────────────────


class BackupConfig(BaseModel):
    endpoint_url: str | None = None  # None = AWS S3; provide URL for R2/MinIO
    bucket: str
    prefix: str = "backups/"
    region: str = "us-east-1"
    access_key: str
    secret_key: str  # plain on write, redacted on read


class BackupConfigResponse(BaseModel):
    configured: bool
    endpoint_url: str | None = None
    bucket: str | None = None
    prefix: str | None = None
    region: str | None = None
    access_key_hint: str | None = None  # first 4 + ***


class BackupEntry(BaseModel):
    ts: str
    filename: str
    size_bytes: int
    status: str
    message: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_history(session) -> list[dict]:
    raw = _get_cfg(session, _KEY_HISTORY)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def _save_history(session, entries: list[dict]) -> None:
    _set_cfg(session, _KEY_HISTORY, json.dumps(entries[-20:]))  # keep last 20


def _make_backup_stream(db_path: str) -> bytes:
    """Create an in-memory copy of the SQLite database."""
    src = sqlite3.connect(db_path)
    buf = io.BytesIO()
    # sqlite3 online backup API — safe while DB is in use
    dst = sqlite3.connect(":memory:")
    src.backup(dst)
    src.close()
    # Serialize to bytes via temp file (can't do :memory: → bytes directly)
    with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tmp:
        dst_file = sqlite3.connect(tmp.name)
        dst.backup(dst_file)
        dst_file.close()
        dst.close()
        tmp.flush()
        with open(tmp.name, "rb") as f:
            return f.read()


def _upload_to_s3(data: bytes, filename: str, cfg: dict) -> None:
    import boto3
    from botocore.config import Config as BotoConfig

    kwargs: dict = {
        "aws_access_key_id": cfg["access_key"],
        "aws_secret_access_key": cfg["secret_key"],
        "region_name": cfg.get("region", "us-east-1"),
        "config": BotoConfig(retries={"max_attempts": 2}),
    }
    if cfg.get("endpoint_url"):
        kwargs["endpoint_url"] = cfg["endpoint_url"]

    s3 = boto3.client("s3", **kwargs)
    key = f"{cfg.get('prefix', 'backups/')}{filename}".lstrip("/")
    s3.put_object(
        Bucket=cfg["bucket"], Key=key, Body=data, ContentType="application/octet-stream"
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/config", response_model=BackupConfigResponse)
def get_backup_config(_: User = Depends(get_current_user)):
    with get_session() as session:
        bucket = _get_cfg(session, _KEY_BUCKET)
        if not bucket:
            return BackupConfigResponse(configured=False)
        ak = _get_cfg(session, _KEY_ACCESS_KEY) or ""
        hint = (ak[:4] + "***") if len(ak) >= 4 else ("***" if ak else None)
        return BackupConfigResponse(
            configured=True,
            endpoint_url=_get_cfg(session, _KEY_ENDPOINT),
            bucket=bucket,
            prefix=_get_cfg(session, _KEY_PREFIX) or "backups/",
            region=_get_cfg(session, _KEY_REGION) or "us-east-1",
            access_key_hint=hint,
        )


@router.put("/config")
def save_backup_config(body: BackupConfig, _: User = Depends(require_manager)):
    with get_session() as session:
        _set_cfg(session, _KEY_ENDPOINT, body.endpoint_url or "")
        _set_cfg(session, _KEY_BUCKET, body.bucket)
        _set_cfg(session, _KEY_PREFIX, body.prefix)
        _set_cfg(session, _KEY_REGION, body.region)
        _set_cfg(session, _KEY_ACCESS_KEY, body.access_key)
        _set_cfg(session, _KEY_SECRET_ENC, encrypt(body.secret_key))
        session.commit()
    return {"ok": True}


@router.delete("/config", status_code=204)
def delete_backup_config(_: User = Depends(require_manager)):
    keys = [
        _KEY_ENDPOINT,
        _KEY_BUCKET,
        _KEY_PREFIX,
        _KEY_REGION,
        _KEY_ACCESS_KEY,
        _KEY_SECRET_ENC,
    ]
    with get_session() as session:
        for k in keys:
            row = session.get(AppConfig, k)
            if row:
                session.delete(row)
        session.commit()


@router.post("/now")
def backup_now(_: User = Depends(require_manager)):
    """Trigger an on-demand backup — uploads to S3 if configured, otherwise returns error."""
    with get_session() as session:
        bucket = _get_cfg(session, _KEY_BUCKET)
        if not bucket:
            raise HTTPException(
                status_code=422,
                detail="Yedekleme yapılandırılmamış. Önce depolama ayarlarını yapın.",
            )

        secret_enc = _get_cfg(session, _KEY_SECRET_ENC)
        cfg = {
            "endpoint_url": _get_cfg(session, _KEY_ENDPOINT) or None,
            "bucket": bucket,
            "prefix": _get_cfg(session, _KEY_PREFIX) or "backups/",
            "region": _get_cfg(session, _KEY_REGION) or "us-east-1",
            "access_key": _get_cfg(session, _KEY_ACCESS_KEY) or "",
            "secret_key": decrypt(secret_enc) if secret_enc else "",
        }

        history = _load_history(session)

    ts = datetime.now(UTC)
    filename = f"app_{ts.strftime('%Y%m%d_%H%M%S')}.db"

    try:
        import os

        db_path = os.getenv("DATABASE_URL", "sqlite:///./data/app.db").replace(
            "sqlite:///", ""
        )
        data = _make_backup_stream(db_path)
        _upload_to_s3(data, filename, cfg)
        status = "success"
        message = None
        size = len(data)
        logger.info(
            "Backup completed", extra={"extra": {"filename": filename, "size": size}}
        )
    except Exception as e:
        status = "error"
        message = str(e)
        size = 0
        logger.error("Backup failed", extra={"extra": {"error": message}})

    entry = {
        "ts": ts.isoformat(),
        "filename": filename,
        "size_bytes": size,
        "status": status,
        "message": message,
    }
    history.append(entry)

    with get_session() as session:
        _save_history(session, history)
        session.commit()

    if status == "error":
        raise HTTPException(status_code=502, detail=f"Yükleme başarısız: {message}")

    return {"filename": filename, "size_bytes": size, "ts": ts.isoformat()}


@router.get("/history")
def backup_history(_: User = Depends(get_current_user)):
    with get_session() as session:
        entries = _load_history(session)
    return list(reversed(entries))  # newest first
