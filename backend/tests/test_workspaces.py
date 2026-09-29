"""
Workspace lifecycle API tests (ADR-0018) against the in-memory FakeRuntime.

Covers: create (idempotent, failure, retry), state machine, ownership vs manager
access (company / department scope incl. sub-departments), 7-day retention and
restore, the scheduler-facing jobs, files (manifest cursor, path safety, size
caps, owner-only), and the fail-closed 503 without a configured runtime.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

import models
from services import workspaces as wsvc
from services.auth import create_access_token
from services.workspace_runtime import FakeRuntime, get_runtime
from tests.conftest import make_member, make_user

# ── fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture()
def rt(client):
    from main import app

    runtime = FakeRuntime()
    app.dependency_overrides[get_runtime] = lambda: runtime
    yield runtime
    app.dependency_overrides.pop(get_runtime, None)


def _as(client, user):
    client.headers["Authorization"] = f"Bearer {create_access_token(user.id)}"


def _person(session, company_id, user, dept_id=None, slug=None):
    p = models.Personnel(
        company_id=company_id,
        name=user.name,
        slug=slug or user.email.split("@")[0],
        type="human",
        user_id=user.id,
        department_id=dept_id,
    )
    session.add(p)
    session.flush()
    return p


def _dept(session, company_id, name, parent_id=None):
    d = models.Department(
        company_id=company_id, name=name, slug=name.lower(), parent_id=parent_id
    )
    session.add(d)
    session.flush()
    return d


@pytest.fixture()
def world(auth_client, db_session):
    """Company with: alice (owner, dept Accounting under Finance), bob (plain user),
    a founder (the auth_client user), and departments Finance ⊃ Accounting, Sales."""
    co = auth_client._test_company
    founder = auth_client._test_user
    finance = _dept(db_session, co.id, "Finance")
    accounting = _dept(db_session, co.id, "Accounting", finance.id)
    sales = _dept(db_session, co.id, "Sales")
    alice = make_user(db_session, "alice@test.com", "Alice")
    bob = make_user(db_session, "bob@test.com", "Bob")
    make_member(db_session, alice.id, co.id, role="user")
    make_member(db_session, bob.id, co.id, role="user")
    p_alice = _person(db_session, co.id, alice, accounting.id)
    _person(db_session, co.id, bob, sales.id)
    db_session.commit()
    return {
        "client": auth_client,
        "co": co,
        "founder": founder,
        "alice": alice,
        "bob": bob,
        "p_alice": p_alice,
        "finance": finance,
        "accounting": accounting,
        "sales": sales,
    }


def _create(w, user="alice"):
    _as(w["client"], w[user])
    return w["client"].post("/workspaces")


def _dept_head(w, db_session, scope_id, email="head@test.com"):
    u = make_user(db_session, email, "Head")
    m = make_member(db_session, u.id, w["co"].id, role="dept_head")
    m.scope_id = scope_id
    db_session.add(m)
    db_session.commit()
    return u


# ── create ────────────────────────────────────────────────────────────────────


def test_create_is_idempotent_and_audited(world, rt, db_session):
    r = _create(world)
    assert r.status_code == 201
    ws = r.json()
    assert ws["state"] == "running"
    assert ws["personnel_id"] == world["p_alice"].id
    assert rt.containers[ws["id"]] == "running"

    r2 = _create(world)
    assert r2.status_code == 200 and r2.json()["id"] == ws["id"]
    assert [c for c in rt.calls if c[0] == "create"] == [("create", ws["id"])]

    logs = db_session.exec(
        select(models.AuditLog).where(models.AuditLog.entity_type == "workspace")
    ).all()
    assert [entry.action for entry in logs] == ["workspace_create"]
    assert logs[0].user_id == world["alice"].id


def test_create_requires_a_personnel_record(auth_client, rt):
    # the founder from auth_client has no Personnel row
    assert auth_client.post("/workspaces").status_code == 404


def test_create_runtime_failure_marks_failed_then_retry_works(world, rt):
    rt.fail_next = "create"
    r = _create(world)
    assert r.status_code == 502
    me = world["client"].get("/workspaces/me").json()
    assert me["state"] == "failed" and "create failed" in me["error"]

    r = _create(world)
    assert r.status_code == 201 and r.json()["state"] == "running"
    assert r.json()["id"] == me["id"]  # same row, retried


def test_stale_creating_is_retried(world, rt, db_session):
    ws = _create(world).json()
    row = db_session.get(models.Workspace, ws["id"])
    row.state = "creating"
    row.updated_at = datetime.utcnow() - timedelta(minutes=10)
    db_session.add(row)
    db_session.commit()
    r = _create(world)
    assert r.json()["state"] == "running"


def test_db_allows_one_live_workspace_per_person(world, db_session):
    a = models.Workspace(company_id=world["co"].id, personnel_id=world["p_alice"].id)
    db_session.add(a)
    db_session.commit()
    db_session.add(
        models.Workspace(company_id=world["co"].id, personnel_id=world["p_alice"].id)
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    a.state = "deleted"  # a deleted one does not block a new live one
    db_session.add(a)
    db_session.add(
        models.Workspace(company_id=world["co"].id, personnel_id=world["p_alice"].id)
    )
    db_session.commit()


def test_me_404_without_workspace(world, rt):
    _as(world["client"], world["alice"])
    assert world["client"].get("/workspaces/me").status_code == 404


# ── state machine ─────────────────────────────────────────────────────────────


def test_suspend_resume_cycle(world, rt):
    ws = _create(world).json()
    c = world["client"]
    r = c.post(f"/workspaces/{ws['id']}/suspend")
    assert r.status_code == 200 and r.json()["state"] == "suspended"
    assert rt.containers[ws["id"]] == "stopped"
    assert c.post(f"/workspaces/{ws['id']}/suspend").json()["state"] == "suspended"

    r = c.post(f"/workspaces/{ws['id']}/resume")
    assert r.json()["state"] == "running" and r.json()["suspended_at"] is None
    assert rt.containers[ws["id"]] == "running"
    assert c.post(f"/workspaces/{ws['id']}/resume").json()["state"] == "running"


def test_runtime_error_on_suspend_leaves_state_unchanged(world, rt):
    ws = _create(world).json()
    rt.fail_next = "stop"
    r = world["client"].post(f"/workspaces/{ws['id']}/suspend")
    assert r.status_code == 502
    assert world["client"].get(f"/workspaces/{ws['id']}").json()["state"] == "running"


def test_invalid_transitions_409(world, rt):
    ws = _create(world).json()
    c = world["client"]
    assert c.delete(f"/workspaces/{ws['id']}").status_code == 204
    assert c.post(f"/workspaces/{ws['id']}/suspend").status_code == 409
    assert c.post(f"/workspaces/{ws['id']}/resume").status_code == 409
    assert c.delete(f"/workspaces/{ws['id']}").status_code == 409


# ── access control ────────────────────────────────────────────────────────────


def test_other_users_cannot_touch_a_workspace(world, rt):
    ws = _create(world).json()
    _as(world["client"], world["bob"])
    c = world["client"]
    for call in (
        c.get(f"/workspaces/{ws['id']}"),
        c.post(f"/workspaces/{ws['id']}/suspend"),
        c.post(f"/workspaces/{ws['id']}/resume"),
        c.delete(f"/workspaces/{ws['id']}"),
    ):
        assert call.status_code == 403
    assert c.get("/workspaces/nope").status_code == 404


def test_founder_manages_but_cannot_resume_or_read_files(world, rt):
    ws = _create(world).json()
    _as(world["client"], world["founder"])
    c = world["client"]
    assert c.get(f"/workspaces/{ws['id']}").status_code == 200
    assert c.post(f"/workspaces/{ws['id']}/suspend").status_code == 200
    assert c.post(f"/workspaces/{ws['id']}/resume").status_code == 403
    assert c.get(f"/workspaces/{ws['id']}/files").status_code == 403


def test_dept_head_scope_includes_sub_departments_only(world, rt, db_session):
    ws = _create(world).json()  # alice is in Accounting, under Finance
    finance_head = _dept_head(world, db_session, world["finance"].id, "fh@test.com")
    sales_head = _dept_head(world, db_session, world["sales"].id, "sh@test.com")
    c = world["client"]
    _as(c, finance_head)
    assert c.get(f"/workspaces/{ws['id']}").status_code == 200
    _as(c, sales_head)
    assert c.get(f"/workspaces/{ws['id']}").status_code == 403


def test_list_is_manager_only_and_scoped(world, rt, db_session):
    ws_alice = _create(world, "alice").json()
    ws_bob = _create(world, "bob").json()
    c = world["client"]

    _as(c, world["alice"])
    assert c.get("/workspaces").status_code == 403

    _as(c, world["founder"])
    assert {w["id"] for w in c.get("/workspaces").json()} == {
        ws_alice["id"],
        ws_bob["id"],
    }

    _as(c, _dept_head(world, db_session, world["finance"].id))
    assert [w["id"] for w in c.get("/workspaces").json()] == [ws_alice["id"]]


# ── delete, retention, restore ────────────────────────────────────────────────


def test_delete_keeps_volume_for_seven_days(world, rt):
    ws = _create(world).json()
    assert world["client"].delete(f"/workspaces/{ws['id']}").status_code == 204
    got = world["client"].get(f"/workspaces/{ws['id']}").json()
    assert got["state"] == "deleted"
    purge = datetime.fromisoformat(got["purge_after"])
    assert timedelta(days=6, hours=23) < purge - datetime.utcnow() <= timedelta(days=7)
    assert ws["id"] not in rt.containers and ws["id"] in rt.volumes

    # the person can start over: a new workspace, a new id
    again = world["client"].post("/workspaces")
    assert again.status_code == 201 and again.json()["id"] != ws["id"]


def test_manager_restores_within_window(world, rt):
    ws = _create(world).json()
    c = world["client"]
    c.delete(f"/workspaces/{ws['id']}")

    assert c.post(f"/workspaces/{ws['id']}/restore").status_code == 403  # owner
    _as(c, world["founder"])
    r = c.post(f"/workspaces/{ws['id']}/restore")
    assert r.status_code == 200 and r.json()["state"] == "running"
    assert r.json()["purge_after"] is None
    assert rt.containers[ws["id"]] == "running"
    assert c.post(f"/workspaces/{ws['id']}/restore").status_code == 409  # not deleted


def test_restore_blocked_when_person_has_new_workspace(world, rt):
    old = _create(world).json()
    world["client"].delete(f"/workspaces/{old['id']}")
    _create(world)  # new live workspace
    _as(world["client"], world["founder"])
    assert world["client"].post(f"/workspaces/{old['id']}/restore").status_code == 409


def test_restore_after_retention_or_purge_is_409(world, rt, db_session):
    ws = _create(world).json()
    world["client"].delete(f"/workspaces/{ws['id']}")
    row = db_session.get(models.Workspace, ws["id"])
    row.purge_after = datetime.utcnow() - timedelta(seconds=1)
    db_session.add(row)
    db_session.commit()

    _as(world["client"], world["founder"])
    assert world["client"].post(f"/workspaces/{ws['id']}/restore").status_code == 409

    assert wsvc.purge_expired(db_session, rt, datetime.utcnow()) == 1
    assert ws["id"] not in rt.volumes
    db_session.refresh(row)
    assert row.purge_after is None
    assert wsvc.purge_expired(db_session, rt, datetime.utcnow()) == 0  # not repeated


# ── scheduler-facing jobs ─────────────────────────────────────────────────────


def test_suspend_idle_only_touches_idle_running(world, rt, db_session):
    idle = _create(world, "alice").json()
    fresh = _create(world, "bob").json()
    row = db_session.get(models.Workspace, idle["id"])
    row.last_active_at = datetime.utcnow() - timedelta(minutes=45)
    db_session.add(row)
    db_session.commit()

    assert wsvc.suspend_idle(db_session, rt, datetime.utcnow(), idle_minutes=30) == 1
    assert rt.containers[idle["id"]] == "stopped"
    assert rt.containers[fresh["id"]] == "running"
    db_session.refresh(row)
    assert row.state == "suspended" and row.suspended_at is not None


# ── files ─────────────────────────────────────────────────────────────────────


def test_upload_lands_in_in_area_only(world, rt):
    ws = _create(world).json()
    r = world["client"].put(
        f"/workspaces/{ws['id']}/files/data/q3.csv", content=b"a,b\n1,2\n"
    )
    assert r.status_code == 201 and r.json()["size"] == 8
    assert rt.files[ws["id"]]["in/data/q3.csv"][0] == b"a,b\n1,2\n"

    # a client cannot aim at out/ — the prefix is forced
    world["client"].put(f"/workspaces/{ws['id']}/files/out/x.txt", content=b"x")
    assert "in/out/x.txt" in rt.files[ws["id"]]
    assert "out/x.txt" not in rt.files[ws["id"]]


def test_manifest_cursor_returns_only_changes(world, rt):
    ws = _create(world).json()
    c = world["client"]
    rt.write_file(ws["id"], "out/a.xlsx", b"1")
    rt.write_file(ws["id"], "out/summaries/2026-09-29-x.md", b"# s")
    rt.write_file(ws["id"], "in/secret.txt", b"not listed")

    m = c.get(f"/workspaces/{ws['id']}/files").json()
    assert sorted(f["path"] for f in m["files"]) == [
        "a.xlsx",
        "summaries/2026-09-29-x.md",
    ]
    assert all(len(f["sha256"]) == 64 for f in m["files"])

    assert (
        c.get(f"/workspaces/{ws['id']}/files?since={m['cursor']}").json()["files"] == []
    )
    rt.write_file(ws["id"], "out/a-v2.xlsx", b"22")
    later = c.get(f"/workspaces/{ws['id']}/files?since={m['cursor']}").json()
    assert [f["path"] for f in later["files"]] == ["a-v2.xlsx"]
    assert later["cursor"] > m["cursor"]


def test_download_and_audit(world, rt, db_session):
    ws = _create(world).json()
    rt.write_file(ws["id"], "out/report.pdf", b"%PDF-1")
    c = world["client"]
    r = c.get(f"/workspaces/{ws['id']}/files/report.pdf")
    assert r.status_code == 200 and r.content == b"%PDF-1"
    assert "report.pdf" in r.headers["content-disposition"]
    assert c.get(f"/workspaces/{ws['id']}/files/missing.pdf").status_code == 404
    # the in/ area is not downloadable through this route
    rt.write_file(ws["id"], "in/mine.txt", b"x")
    assert c.get(f"/workspaces/{ws['id']}/files/mine.txt").status_code == 404
    actions = [
        entry.action
        for entry in db_session.exec(select(models.AuditLog)).all()
        if entry.entity_type == "workspace"
    ]
    assert "workspace_file_download" in actions


def test_path_traversal_rejected(world, rt):
    ws = _create(world).json()
    c = world["client"]
    # (plain `../` is collapsed by the HTTP client before sending, so use the
    # percent-encoded form; `safe_relpath` itself is covered by its unit tests)
    for bad in ("a/%2e%2e/%2e%2e/etc/passwd", "%2e%2e/x"):
        assert c.get(f"/workspaces/{ws['id']}/files/{bad}").status_code == 400
        assert (
            c.put(f"/workspaces/{ws['id']}/files/{bad}", content=b"x").status_code
            == 400
        )


@pytest.mark.parametrize(
    "bad", ["", "/abs", "../x", "a/../../x", "a\\b", "a\x00b", ".", "a/./..", "x" * 600]
)
def test_safe_relpath_rejects(bad):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        wsvc.safe_relpath(bad)
    assert e.value.status_code == 400


def test_safe_relpath_normalises_harmless_paths():
    assert wsvc.safe_relpath("a/b/../c.txt") == "a/c.txt"
    assert wsvc.safe_relpath("summaries/2026-09-29-x.md") == "summaries/2026-09-29-x.md"


def test_size_caps(world, rt, monkeypatch):
    ws = _create(world).json()
    c = world["client"]
    monkeypatch.setenv("WORKSPACE_MAX_UPLOAD_MB", "0")
    assert c.put(f"/workspaces/{ws['id']}/files/a.bin", content=b"x").status_code == 413
    monkeypatch.setenv("WORKSPACE_MAX_DOWNLOAD_MB", "0")
    rt.write_file(ws["id"], "out/big.bin", b"x")
    assert c.get(f"/workspaces/{ws['id']}/files/big.bin").status_code == 413


def test_files_unavailable_for_deleted_workspace(world, rt):
    ws = _create(world).json()
    world["client"].delete(f"/workspaces/{ws['id']}")
    assert world["client"].get(f"/workspaces/{ws['id']}/files").status_code == 409


# ── runtime not configured ────────────────────────────────────────────────────


def test_fails_closed_without_a_runtime(world, monkeypatch):
    monkeypatch.delenv("WORKSPACE_RUNTIME", raising=False)
    _as(world["client"], world["alice"])
    r = world["client"].post("/workspaces")
    assert r.status_code == 503
    assert world["client"].get("/workspaces/me").status_code == 404  # nothing created
