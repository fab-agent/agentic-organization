"""
`sandbox/workspace/context-sync.sh` (ADR-0020) against a real backend over a real
socket: the workspace fetches its agent's company context into the file opencode
reads, caches with ETag, and — on any failure — keeps the previous content.
Also guards the workspace opencode config against drifting from the sandbox's.
"""

import http.server
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
from sqlmodel import select

import models
from services.gateway_auth import create_persona_token
from services.workspace_agent import ensure_workspace_agent
from tests.conftest import make_company

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "sandbox" / "workspace" / "context-sync.sh"
CTX_PATH = "/home/agent/.config/fab/context.md"

pytestmark = pytest.mark.skipif(
    shutil.which("curl") is None, reason="curl not installed"
)


# ── static guards ─────────────────────────────────────────────────────────────


def test_workspace_config_is_the_sandbox_config_plus_the_context_file():
    base = json.loads((ROOT / "sandbox" / "opencode.json").read_text())
    ws = json.loads((ROOT / "sandbox" / "workspace" / "opencode.json").read_text())
    assert set(ws) == set(base)
    assert ws["instructions"] == base["instructions"] + [CTX_PATH]
    for key in base:
        if key != "instructions":
            assert ws[key] == base[key], f"'{key}' drifted from sandbox/opencode.json"


def test_the_image_and_entrypoint_are_wired_up():
    docker = (ROOT / "sandbox" / "workspace" / "Dockerfile").read_text()
    assert "curl" in docker.split("apt-get install")[1].split("&&")[0]
    assert "context-sync.sh /usr/local/bin/workspace-context-sync" in docker
    assert "COPY sandbox/workspace/opencode.json /etc/opencode/opencode.json" in docker
    assert "COPY sandbox/opencode.json" not in docker
    assert (
        "workspace-context-sync"
        in (ROOT / "sandbox" / "workspace" / "entrypoint.sh").read_text()
    )


# ── a real backend on a real socket ───────────────────────────────────────────


@pytest.fixture()
def live(patch_engine, monkeypatch):
    from unittest.mock import patch

    import uvicorn

    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    patches = [
        patch("main.run_seed"),
        patch("main._sync_env_config"),
        patch("main._sync_env_provider_keys"),
        patch("main.init_db"),
    ]
    for p in patches:
        p.start()
    from main import app

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("backend did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)
    for p in patches:
        p.stop()


@pytest.fixture()
def agent(db_session):
    co = make_company(db_session)
    co.metadata_json = json.dumps(
        {"mission": "Make finance calm", "goals": ["Close in 3 days"]}
    )
    db_session.add(co)
    dept = models.Department(
        company_id=co.id, name="Accounting", slug="acc", goals="Match invoices"
    )
    db_session.add(dept)
    db_session.flush()
    human = models.Personnel(
        company_id=co.id,
        department_id=dept.id,
        name="Ayşe",
        slug="ayse",
        type="human",
        title="AP Specialist",
        job_description="Accounts payable: invoice matching.",
    )
    db_session.add(human)
    db_session.commit()
    a = ensure_workspace_agent(db_session, human)
    db_session.commit()
    return {
        "co": co,
        "human": human,
        "agent": a,
        "token": create_persona_token(a.id, co.id),
    }


def _run(base, token, file, extra_env=None, path=None):
    env = {
        **os.environ,
        "FABAGENT_BASE_URL": base,
        "FABAGENT_TOKEN": token,
        "CONTEXT_FILE": str(file),
    }
    env.update(extra_env or {})
    if path:
        env["PATH"] = path
    return subprocess.run(
        ["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30
    )


def _served(db):
    db.expire_all()
    return len(
        db.exec(
            select(models.AuditEvent).where(
                models.AuditEvent.action == "context_served"
            )
        ).all()
    )


# ── behaviour ─────────────────────────────────────────────────────────────────


def test_first_run_writes_the_context_and_the_next_is_a_304(
    live, agent, db_session, tmp_path
):
    f = tmp_path / "ctx.md"
    r = _run(live, agent["token"], f)
    assert r.returncode == 0, r.stderr
    text = f.read_text()
    for want in (
        "Mission: Make finance calm",
        "Department: Accounting",
        "You work for Ayşe, AP Specialist.",
        "invoice matching",
    ):
        assert want in text
    assert (tmp_path / "ctx.md.etag").read_text().startswith('"')
    assert _served(db_session) == 1

    before = f.stat().st_mtime_ns
    r2 = _run(live, agent["token"], f)
    assert r2.returncode == 0 and r2.stdout == ""  # 304: nothing to report
    assert f.stat().st_mtime_ns == before and f.read_text() == text
    assert _served(db_session) == 1, "a 304 must not be served (or audited) again"


def test_a_changed_fact_reaches_the_file(live, agent, db_session, tmp_path):
    f = tmp_path / "ctx.md"
    _run(live, agent["token"], f)
    old_etag = (tmp_path / "ctx.md.etag").read_text()
    human = db_session.get(models.Personnel, agent["human"].id)
    human.job_description = "Now: treasury."
    db_session.add(human)
    db_session.commit()

    r = _run(live, agent["token"], f)
    assert r.returncode == 0 and "updated" in r.stdout
    assert "Now: treasury." in f.read_text() and "invoice matching" not in f.read_text()
    assert (tmp_path / "ctx.md.etag").read_text() != old_etag
    assert _served(db_session) == 2


def test_a_rejected_token_keeps_the_previous_context_and_never_prints_the_token(
    live, agent, tmp_path
):
    f = tmp_path / "ctx.md"
    _run(live, agent["token"], f)
    good = f.read_text()
    r = _run(live, "not-a-valid-token", f)
    assert r.returncode != 0 and "401" in r.stderr
    assert f.read_text() == good
    assert (
        "not-a-valid-token" not in r.stdout + r.stderr
        and agent["token"] not in r.stdout + r.stderr
    )


def test_an_unreachable_server_keeps_the_file_and_creates_it_when_missing(tmp_path):
    f = tmp_path / "sub" / "dir" / "ctx.md"
    r = _run("http://127.0.0.1:9", "tok", f)  # port 9: nothing listens
    assert r.returncode != 0
    assert (
        f.exists() and f.read_text() == ""
    )  # opencode is pointed at this path: it must exist

    f.write_text("PREVIOUS CONTEXT")
    assert _run("http://127.0.0.1:9", "tok", f).returncode != 0
    assert f.read_text() == "PREVIOUS CONTEXT"


def test_missing_configuration_is_reported_and_the_file_still_exists(tmp_path):
    f = tmp_path / "ctx.md"
    env = {k: v for k, v in os.environ.items() if not k.startswith("FABAGENT_")}
    env["CONTEXT_FILE"] = str(f)
    r = subprocess.run(
        ["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30
    )
    assert r.returncode != 0 and "not set" in r.stderr and f.exists()


# ── a hostile or broken server ────────────────────────────────────────────────


@pytest.fixture()
def fake_server():
    servers = []

    def start(body: bytes, status=200):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(status)
                self.send_header("ETag", '"fake"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    yield start
    for s in servers:
        s.shutdown()


@pytest.mark.parametrize(
    "body,status",
    [
        pytest.param(b"x" * 70_000, 200, id="oversized"),
        pytest.param(b"", 200, id="empty"),
        pytest.param(b"oops", 500, id="server-error"),
        pytest.param(b"nope", 403, id="forbidden"),
    ],
)
def test_bad_replies_never_replace_the_previous_context(
    fake_server, tmp_path, body, status
):
    f = tmp_path / "ctx.md"
    f.write_text("PREVIOUS CONTEXT")
    r = _run(fake_server(body, status), "tok", f)
    assert r.returncode != 0
    assert f.read_text() == "PREVIOUS CONTEXT"
    assert not (tmp_path / "ctx.md.etag").exists()
    leftovers = [
        p.name
        for p in tmp_path.iterdir()
        if p.name.startswith("ctx.md.") and p.name != "ctx.md.etag"
    ]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_the_token_is_on_stdin_not_on_the_command_line(fake_server, tmp_path):
    real = shutil.which("curl")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "curl"
    wrapper = bindir / "curl"
    wrapper.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}.args"\ntee "{log}.stdin" | {real} "$@"\n'
    )
    wrapper.chmod(0o755)
    f = tmp_path / "ctx.md"
    r = _run(
        fake_server(b"hello context"),
        "SUPER-SECRET-TOKEN",
        f,
        path=f"{bindir}:{os.environ['PATH']}",
    )
    assert r.returncode == 0 and f.read_text() == "hello context"
    assert "SUPER-SECRET-TOKEN" not in (tmp_path / "curl.args").read_text()
    assert "SUPER-SECRET-TOKEN" in (tmp_path / "curl.stdin").read_text()
