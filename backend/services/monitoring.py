"""One company's operational picture (ADR-0034): existing views combined, nothing new measured.

Every section is computed on its own and reports a status (`ok` / `warn` / `fail` / `unknown`).
A section that cannot be computed answers `unknown` with a short stable reason code - never an
exception text, a path or key material - and does not take the others down. All queries are
bounded by the company id given by the caller, whose right to see it is decided by the endpoint.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import select

from api.system import APP_VERSION
from database import get_session
from models import (
    AuditEvent,
    GatewayUsage,
    Personnel,
    RunDiagnosis,
    WorkspaceClientReport,
    WorkspaceManifestState,
)

logger = logging.getLogger("app")

STALE_DAYS = 7
MAX_DRIFT_NAMES = 20
ORDER = {"ok": 0, "unknown": 1, "warn": 2, "fail": 3}
CERT_WARN_SECONDS = 14 * 24 * 3600
EVAL_DAYS = 30
TOP_AGENTS = 5


def worst(statuses: list[str]) -> str:
    return max(statuses, key=lambda s: ORDER[s]) if statuses else "unknown"


# The only reasons ever shown for an unavailable signer: every code `workspace_service` can raise,
# plus its `signing_` / `manifest_` families of manifest error codes. A test scans the sources and
# fails when a code appears that is not listed here, so the list cannot silently go stale.
_REASONS = frozenset(
    {
        "bad_hash",
        "catalog_changed",
        "catalog_special_file",
        "catalog_symlink",
        "catalog_too_deep",
        "catalog_too_large",
        "catalog_unreadable",
        "crl_contention",
        "crl_highwater_invalid",
        "crl_invalid",
        "file_changed",
        "file_invalid",
        "file_unreadable",
        "generation_contention",
        "generation_exhausted",
        "layout_name_invalid",
        "manifest_bad_binding",
        "manifest_bad_cert",
        "manifest_bad_client_version",
        "manifest_bad_clock",
        "manifest_bad_crl",
        "manifest_bad_encoding",
        "manifest_bad_epoch",
        "manifest_bad_gateway_url",
        "manifest_bad_generation",
        "manifest_bad_hash",
        "manifest_bad_json",
        "manifest_bad_key",
        "manifest_bad_kid",
        "manifest_bad_layout",
        "manifest_bad_lifetime",
        "manifest_bad_mod",
        "manifest_bad_mod_files",
        "manifest_bad_mods",
        "manifest_bad_name",
        "manifest_bad_path",
        "manifest_bad_signature",
        "manifest_bad_size",
        "manifest_bad_string",
        "manifest_bad_time",
        "manifest_bad_version",
        "manifest_below_floor",
        "manifest_bootstrap_floor_required",
        "manifest_cert_key_mismatch",
        "manifest_cert_lifetime",
        "manifest_cert_not_valid_now",
        "manifest_cert_revoked",
        "manifest_client_too_old",
        "manifest_clock_rollback",
        "manifest_crl_below_floor",
        "manifest_crl_conflict",
        "manifest_crl_from_future",
        "manifest_crl_not_cumulative",
        "manifest_crl_required",
        "manifest_crl_rollback",
        "manifest_crl_stale",
        "manifest_duplicate_key",
        "manifest_duplicate_mod",
        "manifest_duplicate_path",
        "manifest_epoch_mismatch",
        "manifest_epoch_needs_new_key",
        "manifest_epoch_rollback",
        "manifest_expired",
        "manifest_float_not_allowed",
        "manifest_generation_conflict",
        "manifest_hash_mismatch",
        "manifest_int_out_of_range",
        "manifest_malformed",
        "manifest_negative_zero",
        "manifest_non_string_key",
        "manifest_not_yet_valid",
        "manifest_outside_cert_window",
        "manifest_path_conflict",
        "manifest_rollback",
        "manifest_size_mismatch",
        "manifest_too_deep",
        "manifest_too_large",
        "manifest_unsupported_type",
        "manifest_wire_too_large",
        "manifest_wrong_binding",
        "mod_missing",
        "mod_name_invalid",
        "no_profile",
        "profiles_invalid",
        "signing_bad_binding",
        "signing_bad_cert",
        "signing_bad_client_version",
        "signing_bad_clock",
        "signing_bad_crl",
        "signing_bad_encoding",
        "signing_bad_epoch",
        "signing_bad_gateway_url",
        "signing_bad_generation",
        "signing_bad_hash",
        "signing_bad_json",
        "signing_bad_key",
        "signing_bad_kid",
        "signing_bad_layout",
        "signing_bad_lifetime",
        "signing_bad_mod",
        "signing_bad_mod_files",
        "signing_bad_mods",
        "signing_bad_name",
        "signing_bad_path",
        "signing_bad_signature",
        "signing_bad_size",
        "signing_bad_string",
        "signing_bad_time",
        "signing_bad_version",
        "signing_below_floor",
        "signing_bootstrap_floor_required",
        "signing_cert_expired",
        "signing_cert_key_mismatch",
        "signing_cert_lifetime",
        "signing_cert_not_valid_now",
        "signing_cert_revoked",
        "signing_client_too_old",
        "signing_clock_rollback",
        "signing_crl_below_floor",
        "signing_crl_conflict",
        "signing_crl_from_future",
        "signing_crl_not_cumulative",
        "signing_crl_required",
        "signing_crl_rollback",
        "signing_crl_stale",
        "signing_duplicate_key",
        "signing_duplicate_mod",
        "signing_duplicate_path",
        "signing_epoch_behind_state",
        "signing_epoch_mismatch",
        "signing_epoch_needs_new_key",
        "signing_epoch_rollback",
        "signing_expired",
        "signing_float_not_allowed",
        "signing_generation_conflict",
        "signing_hash_mismatch",
        "signing_int_out_of_range",
        "signing_key_cert_mismatch",
        "signing_key_permissions",
        "signing_key_revoked",
        "signing_malformed",
        "signing_material_invalid",
        "signing_negative_zero",
        "signing_non_string_key",
        "signing_not_yet_valid",
        "signing_outside_cert_window",
        "signing_path_conflict",
        "signing_rollback",
        "signing_size_mismatch",
        "signing_too_deep",
        "signing_too_large",
        "signing_unsupported_type",
        "signing_wire_too_large",
        "signing_wrong_binding",
        "state_unavailable",
    }
)


def _safe_code(text: str) -> str:
    """A listed code or the fixed `signing_unavailable`: nothing the loader says that is not on
    the list (a message, a path, hex that looks like a code) can reach the response."""
    return text if text in _REASONS else "signing_unavailable"


def _guard(name: str, fn):
    try:
        return fn()
    except Exception:  # one broken section must not hide the others
        logger.exception("monitoring section %s failed", name)
        return {"status": "unknown", "reason": "section_failed"}


def _service() -> dict:
    with get_session() as session:
        session.exec(select(1)).one()
    return {"status": "ok", "version": APP_VERSION, "database": "ok"}


def _audit(company_id: str, deep: bool) -> dict:
    from services import audit_anchor, audit_chain

    with get_session() as session:
        head = session.exec(
            select(func.max(AuditEvent.seq)).where(AuditEvent.chain_key == company_id)
        ).one()
    out: dict = {"events": head or 0}
    # Anchors compare the live head with the append-only external record: cheap, and the one
    # check that catches a rebuilt shorter chain. The full re-hash reads every event: on request.
    anchors = audit_anchor.check_anchors(only={company_id}, verify_internal=False)
    mine = anchors["chains"].get(company_id)
    out["anchor"] = mine["state"] if mine else "none_recorded"
    out["anchor_issues"] = len(anchors["issues"])
    status = "ok"
    if anchors["issues"]:
        status = "fail"
    elif not mine and out["events"]:
        status = "warn"  # a chain nobody has anchored yet is not protected against truncation
    if deep:
        v = audit_chain.verify(company_id)
        out["verified"] = bool(v["ok"])
        if not v["ok"]:
            out["broken_at"] = v.get("broken_at")
            status = "fail"
    else:
        out["verified"] = None  # not checked in this request
    out["status"] = status
    return out


def _gateway(company_id: str, now: datetime) -> dict:
    day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    with get_session() as session:
        # A row belongs to the company recorded ON THE ROW when it was written. A row with no
        # company (legacy) has no proof of ownership and is left out rather than attributed to
        # whichever company the persona belongs to today; a persona that changed company keeps its
        # past usage with the company that incurred it. (A row spans a period and is not split if
        # the persona moves mid-period: a limit of the writer, noted in ADR-0034.)
        rows = session.exec(
            select(GatewayUsage).where(
                GatewayUsage.company_id == company_id,
                GatewayUsage.period.in_([day, month]),
            )
        ).all()
        names = {
            p.id: p.name
            for p in session.exec(
                select(Personnel).where(Personnel.company_id == company_id)
            ).all()
        }
    totals = {
        "day": {"requests": 0, "tokens_in": 0, "tokens_out": 0},
        "month": {"requests": 0, "tokens_in": 0, "tokens_out": 0},
    }
    today = []
    for r in rows:
        key = "day" if r.period == day else "month"
        t = totals[key]
        t["requests"] += r.requests
        t["tokens_in"] += r.tokens_in
        t["tokens_out"] += r.tokens_out
        if key == "day":
            today.append(
                {
                    "persona_id": r.persona_id,
                    "name": names.get(r.persona_id),
                    "requests": r.requests,
                    "tokens": r.tokens_in + r.tokens_out,
                }
            )
    today.sort(key=lambda a: a["tokens"], reverse=True)
    return {"status": "ok", **totals, "top_agents_today": today[:TOP_AGENTS]}


def _eval(company_id: str, now: datetime) -> dict:
    since = now - timedelta(days=EVAL_DAYS)
    with get_session() as session:
        rows = session.exec(
            select(RunDiagnosis).where(
                RunDiagnosis.company_id == company_id, RunDiagnosis.created_at >= since
            )
        ).all()
    layers: dict[str, int] = {}
    for r in rows:
        if r.suspect_layer:
            layers[r.suspect_layer] = layers.get(r.suspect_layer, 0) + 1
    return {
        "status": "ok",
        "days": EVAL_DAYS,
        "runs": len(rows),
        "suspect_counts": layers,  # stage-1 hypotheses, not fault rates (ADR-0023)
        "truncated": sum(1 for r in rows if r.truncated),
        "invalid_events": sum(r.invalid_events for r in rows),
    }


def _workspace(company_id: str, now_s: int) -> dict:
    from services import workspace_service as ws

    out: dict = {}
    status = "ok"
    try:
        signer = ws.load_signer(now_s)
        # the verified payload of the certificate envelope {payload, sig}
        not_after = int(signer.cert["payload"]["not_after"])
        out.update(signer="ok", epoch=signer.epoch, crl_number=signer.crl_number)
        out["signing_cert_days_left"] = max(0, (not_after - now_s) // 86400)
        if not_after - now_s < CERT_WARN_SECONDS:
            status = "warn"
    except ws.WorkspaceUnavailable as e:
        # the stable code only; the reason text could name a file
        out.update(signer="unavailable", reason=_safe_code(str(e)))
        status = "fail"
    with get_session() as session:
        states = session.exec(
            select(WorkspaceManifestState).where(
                WorkspaceManifestState.company_id == company_id
            )
        ).all()
    out["people_issued"] = len(states)
    out["last_issued"] = (
        max(s.updated_at for s in states).isoformat() + "Z" if states else None
    )
    out["status"] = status
    return out


def _clients(company_id: str, now: datetime) -> dict:
    """Self-reported by the clients (ADR-0035): a diagnostic claim, never proof. Counts only."""
    with get_session() as session:
        issued = {
            s.person_id: s
            for s in session.exec(
                select(WorkspaceManifestState).where(
                    WorkspaceManifestState.company_id == company_id
                )
            ).all()
        }
        reports = {
            r.person_id: r
            for r in session.exec(
                select(WorkspaceClientReport).where(
                    WorkspaceClientReport.company_id == company_id
                )
            ).all()
        }
        names = {
            p.id: p.name
            for p in session.exec(
                select(Personnel).where(Personnel.company_id == company_id)
            ).all()
        }
    # Only people who were issued a workspace count; a report from anyone else is ignored.
    mine = {pid: reports[pid] for pid in issued if pid in reports}
    cutoff = now - timedelta(days=STALE_DAYS)
    out: dict = {
        "self_reported": True,
        "issued": len(issued),
        "reporting": len(mine),
        # never reported: no clock can say "silent" about someone who was never heard from
        "never_reported": len(issued) - len(mine),
        # reported before, but not within the last STALE_DAYS (a missing heartbeat)
        "silent": sum(1 for r in mine.values() if r.received_at < cutoff),
        "not_reported_for_days": STALE_DAYS,
    }
    if not mine:
        return {**out, "status": "unknown", "reason": "no_reports"}
    # Versions order by (epoch, generation): a new signing epoch restarts the generation count,
    # so a high generation of an older epoch is still behind.
    behind = sum(
        1
        for pid, r in mine.items()
        if (r.epoch, r.generation) < (issued[pid].epoch, issued[pid].generation)
    )
    drifting = [
        (pid, r)
        for pid, r in mine.items()
        if r.interrupted or r.missing or r.modified or r.extra or r.unmanaged
    ]
    drifting.sort(key=lambda t: names.get(t[0]) or "")
    out.update(
        behind=behind,
        drifting=len(drifting),
        drifting_people=[
            {
                "name": names.get(pid),
                "missing": r.missing,
                "modified": r.modified,
                "extra": r.extra,
                "unmanaged": r.unmanaged,
                "interrupted": r.interrupted,
            }
            for pid, r in drifting[:MAX_DRIFT_NAMES]
        ],
        status="warn" if drifting else "ok",
    )
    return out


def summary(company_id: str, *, deep: bool = False) -> dict:
    now = datetime.utcnow()
    sections = {
        "service": _guard("service", _service),
        "audit": _guard("audit", lambda: _audit(company_id, deep)),
        "gateway": _guard("gateway", lambda: _gateway(company_id, now)),
        "eval": _guard("eval", lambda: _eval(company_id, now)),
        "workspace": _guard(
            "workspace", lambda: _workspace(company_id, int(time.time()))
        ),
        "clients": _guard("clients", lambda: _clients(company_id, now)),
    }
    return {
        "company_id": company_id,
        "generated_at": now.isoformat() + "Z",
        "status": worst([s["status"] for s in sections.values()]),
        "sections": sections,
    }
