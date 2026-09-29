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
def tui_screen(rows=24, cols=110, keys=None):
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
    if keys is None:
        os.write(fd, b"\x0fq")  # Ctrl+O to the sidebar, q to quit
        time.sleep(0.5)
    else:
        for chunk in keys:  # scripted keys; screen is read before quitting
            os.write(fd, chunk)
            end = time.time() + 1.5
            while time.time() < end:
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        out += os.read(fd, 65536)
                    except OSError:
                        break
        os.write(fd, b"\x03")  # Ctrl+C always quits
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

    # ── 6b. "My work review" (v in the sidebar) ───────────────────────────────
    screen = tui_screen(keys=[b"\x0f", b"v"])
    check("My work review" in screen and "not enabled" in screen, "review view says plainly that work review is off")
    check("nothing is collected" in screen, "…and that nothing is collected about the person")

    r = requests.put(
        f"{BASE}/work-review/settings", headers=H, json={"enabled": True, "acknowledge_notice": True}
    )
    check(r.status_code == 200, "founder enables work review")
    screen = tui_screen(keys=[b"\x0f", b"v"])
    check("never" in screen.lower() or "Never" in screen, "review view shows what is never collected")
    check("Ayse" in screen, "review view is titled with the person's name")

    screen = tui_screen(keys=[b"\x0f", b"v", b"n", b"e2e note from tui", b"\r"])
    notes = requests.get(f"{BASE}/work-review/me", headers=H).json()
    texts = [n["text"] for d in notes.get("days", []) for n in d.get("notes", [])]
    check("e2e note from tui" in texts, "a note typed in the TUI reached the server")
    check("e2e note from tui" in screen, "the saved note is shown after the reload")

    screen = tui_screen(keys=[b"\x0f", b"v", b"d"])
    notes = requests.get(f"{BASE}/work-review/me", headers=H).json()
    texts = [n["text"] for d in notes.get("days", []) for n in d.get("notes", [])]
    check("e2e note from tui" not in texts, "d in the TUI deletes the person's own note")

    # ── 6c. fit ratings and contesting them (ADR-0021) ────────────────────────
    from datetime import datetime as _dt

    day = _dt.utcnow().date().isoformat()
    with database.get_session() as s:
        for crit, status, verdict in (("G1", "live", "met"), ("G2", "shadow", "not_met")):
            s.add(models.WorkRating(
                company_id=cid, personnel_id=p["id"], day=day, run_id=f"e2e-{crit}",
                criterion_id=crit, criterion_hash="h", rubric_version="v",
                criterion_status=status, verdict=verdict))
        s.commit()
    screen = tui_screen(keys=[b"\x0f", b"v"])
    check("Fit ratings" in screen, "review view lists fit ratings")
    check("trial" in screen and "only to you" in screen, "trial ratings say only the person sees them")

    def ratings_now():
        r = requests.get(f"{BASE}/work-review/me", headers=H).json()
        return {e["criterion_id"]: e for d in r["days"] for e in d["ratings"]}

    # contest the first rating (G1): c, a reason, Enter
    tui_screen(keys=[b"\x0f", b"v", b"c", b"rehearsal only", b"\r"])
    g1 = ratings_now()["G1"]
    check(g1["contested"] and g1["contest_note"] == "rehearsal only", "c in the TUI contests the rating with a reason")
    screen = tui_screen(keys=[b"\x0f", b"v"])
    check("contested" in screen, "the contested rating is marked in the TUI")

    # withdraw it: u
    tui_screen(keys=[b"\x0f", b"v", b"u"])
    check(not ratings_now()["G1"]["contested"], "u in the TUI withdraws the contest")

    # ── 6d. the person's own training-need signal (ADR-0021 §6) ────────────────
    screen = tui_screen(keys=[b"\x0f", b"v"])
    check("Where more support may help" not in screen, "no signal without enough rated work")
    with database.get_session() as s:
        for i in range(10):
            s.add(models.WorkRating(
                company_id=cid, personnel_id=p["id"], day=day, run_id=f"e2e-tn-{i}",
                criterion_id="G3", criterion_hash="h", rubric_version="v",
                criterion_status="live", verdict="not_met"))
        s.commit()
    me = requests.get(f"{BASE}/work-review/me", headers=H).json()
    check(any(t["criterion_id"] == "G3" for t in me["training_need"]), "the server returns the signal to the person")
    screen = tui_screen(keys=[b"\x0f", b"v"], rows=40)
    check("Where more support may help" in screen and "only you see this" in screen,
          "the TUI shows the training-need signal and says only the person sees it")
    check("10 rated work did not meet it" in screen or "of 10 rated" in screen, "the signal is shown as counts")

    # ── 6e. sharing the signal with the manager: off by default, then y-confirmed ──
    def shared_now():
        me = requests.get(f"{BASE}/work-review/me", headers=H).json()
        return [t for t in me["training_need"] if t["criterion_id"] == "G3"][0]["shared"]

    tui_screen(keys=[b"\x0f", b"v", b"s", b"y"], rows=40)
    check(not shared_now(), "with sharing off, s and y share nothing")
    screen = tui_screen(keys=[b"\x0f", b"v", b"s"], rows=40)
    check("has not enabled sharing" in screen, "the TUI says the company has not enabled sharing")
    requests.put(f"{BASE}/work-review/training-need/settings", headers=H, json={"sharing_enabled": True})
    screen = tui_screen(keys=[b"\x0f", b"v"], rows=40)
    check("not shared" in screen and "s shares it with your manager" in screen, "the TUI offers to share once allowed")
    screen = tui_screen(keys=[b"\x0f", b"v", b"s"], rows=40)
    check("Share this with your manager?" in screen, "s asks for confirmation first")
    check(not shared_now(), "asking shares nothing")
    tui_screen(keys=[b"\x0f", b"v", b"s", b"n"], rows=40)
    check(not shared_now(), "declining shares nothing")
    tui_screen(keys=[b"\x0f", b"v", b"s", b"y"], rows=40)
    check(shared_now(), "y shares the signal")
    screen = tui_screen(keys=[b"\x0f", b"v"], rows=40)
    check("shared with your manager" in screen, "the TUI shows it as shared")
    tui_screen(keys=[b"\x0f", b"v", b"s"], rows=40)
    check(not shared_now(), "s withdraws it at once")
    requests.put(f"{BASE}/work-review/settings", headers=H, json={"enabled": False})
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
