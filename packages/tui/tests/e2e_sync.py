#!/usr/bin/env python3
"""End-to-end check of `fab sync` against a real backend (FastAPI + FakeRuntime).

Starts the backend in-process (so the script can seed the FakeRuntime's `out/`),
then runs the real `fab` binary against it and checks the local folder.

Run with the backend's Python environment, after `cargo build`:

    cd packages/tui && cargo build
    ../../backend/.venv/bin/python tests/e2e_sync.py      # or any venv with backend deps

Env: FAB_BIN (default target/debug/fab), BACKEND_DIR (default ../../backend).
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = Path(os.environ.get("BACKEND_DIR", HERE.parent.parent.parent / "backend")).resolve()
FAB = os.environ.get("FAB_BIN", str(HERE.parent / "target" / "debug" / "fab"))

tmp = Path(tempfile.mkdtemp(prefix="fab-e2e-"))
os.environ.update(
    DATABASE_URL=f"sqlite:///{tmp}/app.db",
    SCHEDULER_ENABLED="false",
    JWT_SECRET="e2e-secret-e2e-secret-e2e-secret-0123456789",
    WORKSPACE_RUNTIME="fake",
)
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

import requests  # noqa: E402
import uvicorn  # noqa: E402

import database  # noqa: E402
import models  # noqa: E402
from main import app  # noqa: E402
from services import workspace_runtime as wr  # noqa: E402

PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"
server = uvicorn.Server(uvicorn.Config(app, port=PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    try:
        requests.get(BASE + "/auth/setup-status", timeout=1)
        break
    except Exception:
        time.sleep(0.2)
else:
    sys.exit("backend did not start")

failures = []


def check(cond, msg):
    print(("ok:   " if cond else "FAIL: ") + msg)
    if not cond:
        failures.append(msg)


# ── setup: company, a person linked to a user, their workspace ───────────────
tok = requests.post(
    BASE + "/auth/setup",
    json={"name": "Ayse", "email": "ayse@e2e.test", "password": "Passw0rd!123", "company_name": "E2E Co"},
).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}
me = requests.get(BASE + "/auth/me", headers=H).json()
cid = me["companies"][0]["company_id"]
p = requests.post(
    BASE + "/personnel",
    json={"name": "Ayse", "slug": "ayse", "type": "human", "company_id": cid},
    headers=H,
).json()
with database.get_session() as s:
    row = s.get(models.Personnel, p["id"])
    row.user_id = me["id"]
    s.add(row)
    s.commit()
fake = wr._fake

session_file = tmp / "session.json"
session_file.write_text(f'{{"base_url": "{BASE}", "token": "{tok}"}}')
folder = tmp / "Fabrika"
env = {**os.environ, "FAB_SESSION_FILE": str(session_file), "FAB_FOLDER": str(folder), "LANG": "en_US.UTF-8"}


def fab_sync():
    return subprocess.run([FAB, "sync"], env=env, capture_output=True, text=True, timeout=60)


def fab_ws():
    return subprocess.run([FAB, "workspace"], env=env, capture_output=True, text=True, timeout=90)


def current():
    r = requests.get(BASE + "/workspaces/me", headers=H)
    return r.json() if r.status_code == 200 else None


# ── 0. workspace first run: `fab sync` never creates, `fab workspace` does ────
r = fab_sync()
check("No workspace yet" in r.stdout and r.returncode == 0, "fab sync does not create a workspace")
check(current() is None, "no workspace exists after fab sync")

r = fab_ws()
check(r.returncode == 0 and "running" in r.stdout, "fab workspace creates it and reports running")
first = current()
check(first is not None and first["state"] == "running", "workspace is running on the server")
fab_ws()
check(current()["id"] == first["id"], "fab workspace is idempotent (same workspace)")

requests.post(f"{BASE}/workspaces/{first['id']}/suspend", headers=H)
check(fake.containers[first["id"]] == "stopped", "workspace suspended")
r = fab_ws()
check(r.returncode == 0 and fake.containers[first["id"]] == "running", "fab workspace resumes a suspended workspace")

# runtime failure: reported with the reason, retried on the next explicit run
requests.delete(f"{BASE}/workspaces/{first['id']}", headers=H)
fake.fail_next = "create"
r = fab_ws()
check(r.returncode == 1 and "create failed" in r.stderr, "runtime failure reported with its reason")
check(current()["state"] == "failed", "workspace recorded as failed")
r = fab_ws()
check(r.returncode == 0 and current()["state"] == "running", "next run retries the failed workspace")

# platform without a runtime: friendly 'unavailable', nothing created
requests.delete(f"{BASE}/workspaces/{current()['id']}", headers=H)
os.environ["WORKSPACE_RUNTIME"] = ""
r = fab_ws()
check(r.returncode == 1 and "unavailable" in r.stderr.lower(), "no runtime configured → 'unavailable'")
os.environ["WORKSPACE_RUNTIME"] = "fake"
r = fab_ws()
check(r.returncode == 0, "creates once the runtime is available")
wid = current()["id"]


# ── 1. outputs arrive, names with spaces / unicode survive, hostile path skipped ──
fake.write_file(wid, "out/deck.pptx", b"PPTX-1")
fake.write_file(wid, "out/summaries/2026-09-29-sales.md", "# Özet\n".encode())
fake.write_file(wid, "out/özet raporu #1.md", b"unicode name")
fake.write_file(wid, "out/../escape.txt", b"nope")  # a hostile server-side path
r = fab_sync()
print(r.stdout, r.stderr)
check(r.returncode == 0, "first sync exits 0")
check((folder / "deck.pptx").read_bytes() == b"PPTX-1", "deck.pptx downloaded")
check((folder / "summaries/2026-09-29-sales.md").read_text() == "# Özet\n", "summary in subfolder")
check((folder / "özet raporu #1.md").read_bytes() == b"unicode name", "unicode/space/# file name")
check(not (tmp / "escape.txt").exists() and not (folder / "escape.txt").exists(), "hostile ../ path not written anywhere")
check("skipped" in r.stdout, "hostile path reported as skipped")

# ── 2. nothing changes on a second pass ───────────────────────────────────────
r = fab_sync()
check("0 downloaded, 0 uploaded, 0 conflict(s), 0 error(s)" in r.stdout, "second sync is a no-op")

# ── 3. uploads: a file dropped into in/ reaches the workspace ─────────────────
(folder / "in").mkdir(exist_ok=True)
(folder / "in" / "q3 data.csv").write_text("a,b\n1,2\n")
r = fab_sync()
check(fake.files[wid].get("in/q3 data.csv", (None,))[0] == b"a,b\n1,2\n", "upload landed in workspace in/")
check("1 uploaded" in r.stdout, "upload reported")
r = fab_sync()
check("0 uploaded" in r.stdout, "unchanged upload not repeated")

# ── 4. a locally edited output is kept; the server copy goes beside it ────────
(folder / "deck.pptx").write_bytes(b"MY EDIT")
fake.write_file(wid, "out/deck.pptx", b"PPTX-2")
r = fab_sync()
check((folder / "deck.pptx").read_bytes() == b"MY EDIT", "local edit not overwritten")
check((folder / "deck (server).pptx").read_bytes() == b"PPTX-2", "server version saved as 'deck (server).pptx'")
check("1 conflict(s)" in r.stdout, "conflict reported")

# ── 5. new version by name arrives; old stays ─────────────────────────────────
fake.write_file(wid, "out/report-v2.xlsx", b"XLSX-2")
r = fab_sync()
check((folder / "report-v2.xlsx").read_bytes() == b"XLSX-2", "new version by name arrives")

# ── 6. the TUI's files strip shows the sync (needs `pyte`; skipped without it) ──
def tui_screen(rows=24, cols=110):
    import fcntl
    import pty
    import select
    import struct
    import termios

    import pyte

    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(env)
        os.environ["FAB_AGENT_CMD"] = "/bin/sh -c 'sleep 30'"
        os.execv(FAB, [FAB])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    out = b""
    end = time.time() + 4
    while time.time() < end:
        if select.select([fd], [], [], 0.1)[0]:
            try:
                out += os.read(fd, 65536)
            except OSError:
                break
    os.write(fd, b"\x0fq")  # Ctrl+O to the sidebar, q to quit
    time.sleep(0.5)
    screen = pyte.Screen(cols, rows)
    pyte.Stream(screen).feed(out.decode(errors="replace"))
    return "\n".join(screen.display)


try:
    import pyte  # noqa: F401

    screen = tui_screen()
    check("synced" in screen, "TUI files strip shows 'synced'")
    check("deck.pptx" in screen or "report-v2.xlsx" in screen, "TUI files strip lists recent files")
    check("conflict" in screen, "TUI files strip mentions the conflict")

    # first run inside the TUI: no workspace → it creates one and shows the state
    requests.delete(f"{BASE}/workspaces/{wid}", headers=H)
    check(current() is None, "workspace removed before the TUI first-run check")
    screen = tui_screen()
    check("Workspace: running" in screen, "TUI shows 'Workspace: running' after creating it")
    check(current() is not None and current()["state"] == "running", "TUI created the workspace on first run")
    wid = current()["id"]
except ImportError:
    print("skip: pyte not installed — TUI checks skipped")

# ── 7. no workspace / signed out behave sanely ────────────────────────────────
requests.delete(f"{BASE}/workspaces/{current()['id']}", headers=H)
r = fab_sync()
check("No workspace yet" in r.stdout and r.returncode == 0, "no workspace → friendly message")
session_file.write_text(f'{{"base_url": "{BASE}", "token": "bad"}}')
r = fab_sync()
check(r.returncode != 0, "invalid token → non-zero exit")

server.should_exit = True
print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'}")
sys.exit(1 if failures else 0)
