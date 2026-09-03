"""
External anchoring for the tamper-evident audit chain (ADR-0006).

`audit_chain.verify()` proves a chain is *internally* consistent, but someone
with DB + backend access could rebuild a shorter consistent chain (drop the
embarrassing tail, re-hash). Anchoring defends against that: a scheduled job
records each chain's `(seq, head_hash)` to

  1. an append-only local log  `data/audit_anchors.jsonl`  (always), and
  2. an S3 object (optionally WORM / Object-Lock) reusing the `backup_*`
     `AppConfig` settings — when `backup_bucket` is set.

`check_anchors()` then flags a chain whose current `seq` is **below** the last
anchored seq (truncation) or whose head at the anchored seq has **changed**
(rewrite) — neither of which `verify()` can catch.
"""

from __future__ import annotations

import json
import logging
import pathlib
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from database import get_session
from models import AppConfig, AuditEvent

logger = logging.getLogger("app")

_ANCHOR_FILE = pathlib.Path("data/audit_anchors.jsonl")
GLOBAL_CHAIN = "__global__"


# ── chain heads ─────────────────────────────────────────────────────────────


def _chain_heads() -> dict[str, dict]:
    """{chain_key: {"seq": int, "head": str}} — the last event of every chain."""
    heads: dict[str, dict] = {}
    with get_session() as session:
        keys = list(session.exec(select(AuditEvent.chain_key).distinct()).all())
        for k in keys:
            row = session.exec(
                select(AuditEvent)
                .where(AuditEvent.chain_key == k)
                .order_by(AuditEvent.seq.desc())
            ).first()
            if row:
                heads[k] = {"seq": row.seq, "head": row.hash}
    return heads


# ── S3 (optional) ───────────────────────────────────────────────────────────


def _s3_cfg() -> dict | None:
    with get_session() as session:

        def g(k: str) -> str:
            r = session.get(AppConfig, k)
            return r.value if r and r.value else ""

        bucket = g("backup_bucket")
        if not bucket:
            return None
        from core.security import decrypt

        secret_enc = g("backup_secret_key_encrypted")
        return {
            "bucket": bucket,
            "prefix": g("backup_prefix") or "backups/",
            "region": g("backup_region") or "us-east-1",
            "endpoint_url": g("backup_endpoint_url") or None,
            "access_key": g("backup_access_key"),
            "secret_key": decrypt(secret_enc) if secret_enc else "",
            "lock_days": int(g("audit_anchor_lock_days") or "0"),
        }


def _push_s3(cfg: dict, body: bytes) -> None:
    import boto3
    from botocore.config import Config as BotoConfig

    kwargs: dict = {
        "aws_access_key_id": cfg["access_key"],
        "aws_secret_access_key": cfg["secret_key"],
        "region_name": cfg["region"],
        "config": BotoConfig(retries={"max_attempts": 2}),
    }
    if cfg["endpoint_url"]:
        kwargs["endpoint_url"] = cfg["endpoint_url"]
    s3 = boto3.client("s3", **kwargs)
    key = f"{cfg['prefix']}audit-anchors/audit_anchors.jsonl".lstrip("/")
    put: dict = {
        "Bucket": cfg["bucket"],
        "Key": key,
        "Body": body,
        "ContentType": "application/x-ndjson",
    }
    if cfg["lock_days"] > 0:
        put["ObjectLockMode"] = "COMPLIANCE"
        put["ObjectLockRetainUntilDate"] = datetime.now(timezone.utc) + timedelta(
            days=cfg["lock_days"]
        )
    try:
        s3.put_object(**put)
    except Exception as e:  # noqa: BLE001 — lock not enabled on the bucket etc.
        if "ObjectLockMode" in put:
            put.pop("ObjectLockMode")
            put.pop("ObjectLockRetainUntilDate")
            s3.put_object(**put)
            logger.warning("audit anchor: bucket has no Object Lock — pushed unlocked")
        else:
            raise e


# ── public API ──────────────────────────────────────────────────────────────


def anchor_heads() -> dict:
    """Append the current chain heads to the local log + push to S3 if configured."""
    heads = _chain_heads()
    if not heads:
        return {"anchored": 0}
    ts = datetime.now(timezone.utc).isoformat()
    lines = [
        json.dumps({"ts": ts, "chain_key": k, "seq": v["seq"], "head": v["head"]})
        for k, v in sorted(heads.items())
    ]
    try:
        _ANCHOR_FILE.parent.mkdir(exist_ok=True)
        with _ANCHOR_FILE.open("a") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:  # noqa: BLE001
        logger.warning("audit anchor: local write failed: %s", e)

    pushed = False
    cfg = _s3_cfg()
    if cfg:
        try:
            _push_s3(cfg, _ANCHOR_FILE.read_bytes())
            pushed = True
        except Exception as e:  # noqa: BLE001
            logger.warning("audit anchor: S3 push failed: %s", e)

    return {"anchored": len(heads), "s3": pushed}


def _last_anchored() -> dict[str, dict]:
    """{chain_key: {"seq", "head", "ts"}} from the tail of the local log."""
    out: dict[str, dict] = {}
    if not _ANCHOR_FILE.exists():
        return out
    for line in _ANCHOR_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            out[rec["chain_key"]] = rec
        except (ValueError, KeyError):  # skip a corrupt line
            pass
    return out


def check_anchors() -> dict:
    """
    Compare live chain heads to the last anchored ones. An issue = the chain
    shrank (truncation) or its head at the anchored seq changed (rewrite).
    """
    from services import audit_chain

    live = _chain_heads()
    anchored = _last_anchored()
    issues: list[dict] = []
    chains: dict[str, dict] = {}

    for k, a in anchored.items():
        cur = live.get(k)
        state = "ok"
        if cur is None:
            state, issue = "missing", "chain vanished since last anchor"
        elif cur["seq"] < a["seq"]:
            state, issue = "truncated", f"seq {cur['seq']} < anchored {a['seq']}"
        elif cur["seq"] == a["seq"] and cur["head"] != a["head"]:
            state, issue = "rewritten", "head changed at the anchored seq"
        else:
            issue = None
        chains[k] = {
            "anchored_seq": a["seq"],
            "live_seq": cur["seq"] if cur else None,
            "state": state,
            "anchored_at": a.get("ts"),
        }
        if issue:
            issues.append({"chain_key": k, "issue": issue})

    internal = audit_chain.verify_all()
    return {
        "ok": not issues and internal["ok"],
        "chains": chains,
        "issues": issues,
        "internal_verify_ok": internal["ok"],
        "anchor_count": sum(1 for _ in _ANCHOR_FILE.read_text().splitlines())
        if _ANCHOR_FILE.exists()
        else 0,
    }
