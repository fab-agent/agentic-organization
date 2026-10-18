"""Opt-in: the real controller against a real Docker (the image built from
sandbox/workspace). Run with

  WORKSPACE_LIVE_CONTROLLER_URL=http://localhost:8090 WORKSPACE_LIVE_CONTROLLER_SECRET=... \
  pytest tests/test_workspace_controller_live.py
"""

import os
import uuid

import pytest

URL = os.getenv("WORKSPACE_LIVE_CONTROLLER_URL")
SECRET = os.getenv("WORKSPACE_LIVE_CONTROLLER_SECRET", "")

pytestmark = pytest.mark.skipif(not URL, reason="no live controller configured")


def test_full_lifecycle_against_real_docker():
    import time

    from services.workspace_runtime import (
        ControllerRuntime,
        FileNotFound,
        WorkspaceSpec,
    )

    rt = ControllerRuntime(URL, SECRET)
    wid = str(uuid.uuid4())
    env = {"FABAGENT_BASE_URL": "http://127.0.0.1:9", "FABAGENT_TOKEN": "live-test"}
    try:
        rt.create(WorkspaceSpec(wid, "c", "p", env=env))
        time.sleep(5)
        assert rt.status(wid) == "running"
        rt.write_file(wid, "in/sub/a.txt", b"hello")
        assert rt.list_files(wid, "in")[0].path == "in/sub/a.txt"
        with pytest.raises(FileNotFound):
            rt.read_file(wid, "out/nothing.txt")
        rt.stop(wid)
        assert rt.status(wid) == "stopped"
        rt.start(wid, {"FABAGENT_TOKEN": "fresh"})  # recreated on its volumes
        time.sleep(5)
        assert rt.status(wid) == "running"
        assert rt.read_file(wid, "in/sub/a.txt") == b"hello"  # files survived
        rt.remove(wid)
        assert rt.status(wid) == "missing"
        rt.restore(wid, env)
        time.sleep(4)
        assert rt.read_file(wid, "in/sub/a.txt") == b"hello"
    finally:
        rt.remove(wid)  # a failed cleanup must show up, not leave volumes behind
        rt.purge_volume(wid)


def test_planted_module_is_not_imported_by_the_file_helper():
    """A `hashlib.py` the agent leaves in its own tree must not run in the helper."""
    import subprocess
    import time

    from services.workspace_runtime import ControllerRuntime, WorkspaceSpec

    rt = ControllerRuntime(URL, SECRET)
    wid = str(uuid.uuid4())
    env = {"FABAGENT_BASE_URL": "http://127.0.0.1:9", "FABAGENT_TOKEN": "live-test"}
    try:
        rt.create(WorkspaceSpec(wid, "c", "p", env=env))
        time.sleep(5)
        names = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"name={wid}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert names, "workspace container not found"
        plant = "import pathlib;pathlib.Path('/workspace/out/PWNED').write_text('x')\n"
        for target in (
            "/workspace/hashlib.py",
            "/workspace/out/hashlib.py",
            "/hashlib.py",
        ):
            subprocess.run(
                ["docker", "exec", names[0], "sh", "-c", f"cat > {target}"],
                input=plant,
                text=True,
            )
        rt.write_file(wid, "in/a.txt", b"x")
        rt.list_files(wid, "in")
        rt.read_file(wid, "in/a.txt")
        assert not [f for f in rt.list_files(wid, "out") if f.path.endswith("PWNED")]
        left = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "name=fab-ws-helper"],
            capture_output=True,
            text=True,
        ).stdout.split()
        assert left == [], "helper containers were left behind"
    finally:
        rt.remove(wid)
        rt.purge_volume(wid)
