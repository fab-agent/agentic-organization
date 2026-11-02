"""End to end: the real backend signs a workspace, the real `3pa workspace sync` verifies
it and installs it (ADR-0029). Two independent implementations (Python signer, TypeScript
verifier) and the real HTTP in between. Skipped when node or the CLI dependencies are
missing."""

import json
import os
import pathlib
import shutil
import socket
import subprocess
import threading
import time
from unittest.mock import patch

import pytest
import uvicorn

import services.workspace_manifest as wm
from models import Department
from services.auth import create_access_token
from tests.conftest import make_company, make_member, make_personnel, make_user
from tests.test_me_workspace import Env  # catalog + signing material builder

CLI = pathlib.Path(__file__).resolve().parents[2] / "packages" / "cli"
TSX = CLI / "node_modules" / ".bin" / "tsx"
pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not TSX.exists(),
    reason="node or the CLI dependencies are not installed",
)


@pytest.fixture()
def live(monkeypatch, tmp_path, db_session):
    env = Env(tmp_path, monkeypatch)
    co = make_company(db_session)
    fin = Department(company_id=co.id, name="Finance", slug="finance")
    db_session.add(fin)
    db_session.flush()
    user = make_user(db_session, email="ap@test.com", name="AP")
    make_member(db_session, user.id, co.id, role="user")
    person = make_personnel(db_session, co.id, name="AP Clerk", slug="ap", type="human")
    person.user_id, person.department_id = user.id, fin.id
    db_session.add(person)
    db_session.commit()

    from main import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    patches = [
        patch("main.run_seed"),
        patch("main._sync_env_config"),
        patch("main._sync_env_provider_keys"),
        patch("main.init_db"),
    ]
    for p in patches:
        p.start()
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "server did not start"
    yield {
        "env": env,
        "co": co,
        "person": person,
        "token": create_access_token(user.id),
        "base": f"http://localhost:{port}",
        "tmp": tmp_path,
    }
    server.should_exit = True
    t.join(timeout=10)
    for p in patches:
        p.stop()


def sync(live, *extra, root_pub=None, token=None, sub="sync"):
    home = live["tmp"]
    cmd = [
        str(TSX),
        "src/index.ts",
        "workspace",
        sub,
        "--base",
        live["base"],
        "--company",
        live["co"].id,
        *extra,
    ]
    env = {
        **os.environ,
        "HOME": str(home),
        "FABAGENT_WEB_TOKEN": token or live["token"],
        "FABAGENT_WORKSPACE_ROOT_PUB": root_pub or live["env"].root_pub,
        "THREEPA_WORKSPACE_DIR": str(home / "state"),
        "HERDR_APP_HOME": str(home / "app"),
    }
    return subprocess.run(
        cmd, cwd=CLI, env=env, capture_output=True, text=True, timeout=90
    )


def test_signed_workspace_goes_from_the_real_server_into_the_app_home(live):
    r = sync(live)
    assert r.returncode == 0, r.stdout + r.stderr
    app = live["tmp"] / "app"
    assert (app / "layouts" / "finance-v2.json").read_bytes() == b'{"id":"finance"}'
    assert (
        app / "mods" / "finance-dashboard" / "main.js"
    ).read_bytes() == b"export default 1;\n"
    assert (
        app / "mods" / "finance-dashboard" / "assets" / "icon.svg"
    ).read_bytes() == b"<svg/>"
    assert json.loads((app / "settings.json").read_text()) == {"telemetry": False}
    state = json.loads((live["tmp"] / "state" / "state.json").read_text())
    assert state["identity"] == {
        "company_id": live["co"].id,
        "person_id": live["person"].id,
    }
    assert state["client"]["epoch"] == 1 and state["installed"]["generation"] == 1
    assert "up to date" not in r.stdout

    again = sync(live)
    assert again.returncode == 0 and "already up to date" in again.stdout
    assert (
        json.loads((live["tmp"] / "state" / "state.json").read_text())["installed"][
            "generation"
        ]
        == 2
    )


def test_a_different_pinned_root_installs_nothing(live):
    other = wm.generate_key()[1]
    r = sync(live, root_pub=other)
    assert r.returncode == 1, r.stdout + r.stderr
    assert (
        "manifest_bad_signature" in r.stdout + r.stderr
        or "bad_signature" in r.stdout + r.stderr
    )
    assert not (live["tmp"] / "app" / "layouts" / "finance-v2.json").exists()


def test_a_revoked_signing_key_installs_nothing(live):
    env = live["env"]
    now = int(time.time())
    crl = wm.issue_crl(
        env.root_priv,
        number=1,
        revoked_kids=[wm.key_id(env.sign_pub)],
        issued_at=now - 10,
        next_update=now + 86400,
    )
    (env.dir / "crl.json").write_text(json.dumps(crl))
    r = sync(live)
    # the server itself refuses to sign with a revoked key, and says why
    assert r.returncode == 1 and "signing_key_revoked" in r.stdout + r.stderr
    assert not (live["tmp"] / "app" / "layouts" / "finance-v2.json").exists()


def test_a_file_changed_on_the_server_is_picked_up_and_old_one_is_replaced(live):
    assert sync(live).returncode == 0
    mods = live["env"].dir / "catalog" / "mods" / "finance-dashboard" / "1.2.0"
    (mods / "main.js").write_bytes(b"export default 2;\n")
    r = sync(live)
    assert r.returncode == 0 and "updated" in r.stdout.lower()
    assert (
        live["tmp"] / "app" / "mods" / "finance-dashboard" / "main.js"
    ).read_bytes() == b"export default 2;\n"


def test_the_wrong_person_cannot_receive_this_persons_workspace(live, db_session):
    other = make_user(db_session, email="x@test.com", name="X")
    make_member(db_session, other.id, live["co"].id, role="user")
    db_session.commit()  # a member with no linked person
    r = sync(live, token=create_access_token(other.id))
    assert r.returncode == 1 and not (live["tmp"] / "app" / "layouts").exists()


def _report_row(live, db_session):
    from sqlmodel import select

    from models import WorkspaceClientReport

    db_session.expire_all()
    return db_session.exec(
        select(WorkspaceClientReport).where(
            WorkspaceClientReport.person_id == live["person"].id
        )
    ).first()


def test_the_client_reports_its_own_drift_as_counts_only(live, db_session):
    from datetime import datetime, timedelta

    r = sync(live)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "status report sent" in r.stdout
    row = _report_row(live, db_session)
    assert row and (row.generation, row.missing, row.modified, row.extra) == (
        1,
        0,
        0,
        0,
    )
    assert not row.interrupted and row.company_id == live["co"].id

    # an edit by hand shows up in the next report as a count, and nothing names the file
    (live["tmp"] / "app" / "mods" / "finance-dashboard" / "main.js").write_bytes(
        b"evil"
    )
    # (the platform limits reports to one per 30 s: pretend the first one was a while ago)
    row.received_at = datetime.utcnow() - timedelta(seconds=60)
    db_session.add(row)
    db_session.commit()
    again = sync(live, sub="report")
    assert again.returncode == 0, again.stdout + again.stderr
    row = _report_row(live, db_session)
    assert row.modified == 1 and row.missing == 0
    assert "main.js" not in again.stdout + again.stderr

    # the monitoring page sees it, labelled as a self-report
    token = create_access_token(live["founder_id"]) if "founder_id" in live else None
    if token:
        import httpx

        j = httpx.get(
            f"{live['base']}/admin/monitoring?company_id={live['co'].id}",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        assert j["sections"]["clients"]["self_reported"] is True


def test_a_failed_report_never_fails_the_sync_and_can_be_turned_off(
    live, db_session, monkeypatch
):
    r = sync(live, "--no-report")
    assert r.returncode == 0 and "status report" not in r.stdout
    assert _report_row(live, db_session) is None

    import api.me_workspace as mw

    def boom(*a, **k):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(mw, "WorkspaceClientReport", boom)
    r = sync(live)  # the platform now fails the report with a 500
    assert r.returncode == 0, r.stdout + r.stderr  # the sync is not its result
    assert "status report not sent [http_500]" in r.stdout
    assert "already up to date" in r.stdout
    assert "database exploded" not in r.stdout + r.stderr
    # and the explicit command says so and fails (that is its whole job)
    again = sync(live, sub="report")
    assert again.returncode == 1 and "http_500" in again.stdout + again.stderr
