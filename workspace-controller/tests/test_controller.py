"""Controller behaviour with a fake docker runner (no Docker needed)."""

import io
import sys
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import build_app  # noqa: E402
from docker_ops import Config, Docker, DockerError, safe_rel  # noqa: E402

WID = "11111111-2222-3333-4444-555555555555"
SECRET = "s" * 40
H = {"X-Controller-Secret": SECRET}


class Fake:
    def __init__(self):
        self.calls = []
        self.state = {}  # name -> running|stopped
        self.tar_out = b""

    def __call__(self, args, stdin=None, env=None):
        self.calls.append((list(args), env))
        a = args
        if a[:2] == ["network", "inspect"] or a[:2] == ["volume", "inspect"]:
            if a[1] == "inspect" and a[2] in self.state:
                return b""
            raise DockerError("no such")
        if a[0] == "inspect":
            name = a[-1]
            if name not in self.state:
                raise DockerError("no such")
            return b"true" if self.state[name] == "running" else b"false"
        if a[:2] == ["network", "create"]:
            self.state[a[-1]] = "net"
            return b""
        if a[:2] == ["volume", "create"]:
            self.state[a[-1]] = "vol"
            return b""
        if a[0] == "run":
            self.state[a[a.index("--name") + 1]] = "running"
            return b"cid"
        if a[0] == "start":
            self.state[a[-1]] = "running"
            return b""
        if a[0] == "stop":
            self.state[a[-1]] = "stopped"
            return b""
        if a[0] == "rm":
            self.state.pop(a[-1], None)
            return b""
        if a[:2] == ["volume", "rm"]:
            self.state.pop(a[-1], None)
            return b""
        if a[:2] == ["network", "connect"]:
            return b""
        if a[0] == "cp":
            return self.tar_out
        raise AssertionError(a)


@pytest.fixture()
def ctl():
    fake = Fake()
    docker = Docker(Config(image="ws:test", egress_image="eg:test"), run=fake)
    return TestClient(build_app(docker, SECRET)), fake


def test_a_short_secret_refuses_to_start():
    with pytest.raises(RuntimeError):
        build_app(Docker(Config("i", "e"), run=Fake()), "short")


def test_every_call_needs_the_secret(ctl):
    c, _ = ctl
    assert c.post(f"/v1/workspaces/{WID}", json={}).status_code == 401
    assert (
        c.post(
            f"/v1/workspaces/{WID}", json={}, headers={"X-Controller-Secret": "x" * 40}
        ).status_code
        == 401
    )
    assert c.get("/health").status_code == 200


def test_ids_must_be_uuids_and_nothing_else_reaches_docker(ctl):
    c, fake = ctl
    for bad in ("../etc", "abc", f"{WID};rm", "ZZZZ"):
        assert c.post(f"/v1/workspaces/{bad}/start", headers=H).status_code in (
            404,
            422,
        ), bad
    assert fake.calls == []


def test_create_is_hardened_idempotent_and_keeps_the_token_out_of_argv(ctl):
    c, fake = ctl
    env = {
        "FABAGENT_BASE_URL": "https://agents.example",
        "FABAGENT_TOKEN": "tok-secret",
    }
    r = c.post(f"/v1/workspaces/{WID}", json={"env": env}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "running"
    run = next(a for a, _ in fake.calls if a[0] == "run" and f"fab-ws-{WID}" in a)
    assert "--cap-drop" in run and "ALL" in run and "no-new-privileges:true" in run
    assert "--network" in run and "fab-ws-internal" in run
    assert not any(
        x.startswith("/var/run/docker.sock") or x == "--privileged" for x in run
    )
    assert "tok-secret" not in " ".join(run)  # passed through the child's environment
    child_env = next(e for a, e in fake.calls if a == run)
    assert child_env["FABAGENT_TOKEN"] == "tok-secret"
    n = len(fake.calls)
    c.post(
        f"/v1/workspaces/{WID}", json={"env": env}, headers=H
    )  # again: no second container
    assert sum(1 for a, _ in fake.calls if a[0] == "run" and f"fab-ws-{WID}" in a) == 1
    assert len(fake.calls) > n  # it only looked


def test_environment_is_an_allowlist(ctl):
    c, _ = ctl
    for key in ("PATH", "LD_PRELOAD", "DOCKER_HOST", "FABAGENT_TOKEN\nX"):
        r = c.post(f"/v1/workspaces/{WID}", json={"env": {key: "x"}}, headers=H)
        assert r.status_code == 422, key
    assert (
        c.post(
            f"/v1/workspaces/{WID}", json={"env": {"FABAGENT_TOKEN": "a\nb"}}, headers=H
        ).status_code
        == 422
    )
    assert (
        c.post(f"/v1/workspaces/{WID}", json={"image": "evil"}, headers=H).status_code
        == 422
    )  # extra field


def test_lifecycle_status_and_restore_needs_the_volume(ctl):
    c, fake = ctl
    c.post(f"/v1/workspaces/{WID}", json={"env": {}}, headers=H)
    assert c.get(f"/v1/workspaces/{WID}/status", headers=H).json() == {
        "status": "running"
    }
    c.post(f"/v1/workspaces/{WID}/stop", headers=H)
    assert c.get(f"/v1/workspaces/{WID}/status", headers=H).json() == {
        "status": "stopped"
    }
    c.post(f"/v1/workspaces/{WID}/remove", headers=H)
    assert c.get(f"/v1/workspaces/{WID}/status", headers=H).json() == {
        "status": "missing"
    }
    assert (
        c.post(f"/v1/workspaces/{WID}/restore", json={"env": {}}, headers=H).status_code
        == 200
    )
    c.post(f"/v1/workspaces/{WID}/remove", headers=H)
    c.post(f"/v1/workspaces/{WID}/purge", headers=H)
    assert (
        c.post(f"/v1/workspaces/{WID}/restore", json={"env": {}}, headers=H).status_code
        == 502
    )


@pytest.mark.parametrize(
    "p",
    [
        "../x",
        "/etc/passwd",
        "out/../../x",
        "out//x",
        "tmp/x",
        "out",
        "out/a\x00b",
        "in/.",
        "out/" + "a" * 300,
    ],
)
def test_paths_are_plain_segments_under_in_or_out(p):
    with pytest.raises(Exception):
        safe_rel(p)


def test_only_regular_files_are_listed_and_hidden_names_survive(ctl):
    c, fake = ctl
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, kind, data in (
            ("./", tarfile.DIRTYPE, b""),
            ("./.env", tarfile.REGTYPE, b"x"),
            ("./a.txt", tarfile.REGTYPE, b"hello"),
            ("./link", tarfile.SYMTYPE, b""),
        ):
            ti = tarfile.TarInfo(name)
            ti.type = kind
            ti.size = len(data)
            if kind == tarfile.SYMTYPE:
                ti.linkname = "/etc/passwd"
            t.addfile(ti, io.BytesIO(data) if data else None)
    fake.tar_out = buf.getvalue()
    r = c.get(f"/v1/workspaces/{WID}/files?area=out", headers=H).json()["files"]
    assert [f["path"] for f in r] == ["out/.env", "out/a.txt"]
    assert c.get(f"/v1/workspaces/{WID}/files?area=etc", headers=H).status_code == 422


def test_uploads_go_to_in_only_as_agent_owned_files(ctl):
    c, fake = ctl
    r = c.put(
        f"/v1/workspaces/{WID}/file?path=in/sub/a.txt", content=b"data", headers=H
    )
    assert r.status_code == 200
    args, _ = fake.calls[-1]
    assert args[0] == "cp" and args[1] == "-" and args[2].endswith(":/workspace")
    assert (
        c.put(
            f"/v1/workspaces/{WID}/file?path=out/a.txt", content=b"x", headers=H
        ).status_code
        == 422
    )
    assert (
        c.put(
            f"/v1/workspaces/{WID}/file?path=in/../../x", content=b"x", headers=H
        ).status_code
        == 422
    )


def test_start_with_an_environment_recreates_the_container_on_its_volumes(ctl):
    c, fake = ctl
    c.post(f"/v1/workspaces/{WID}", json={"env": {"FABAGENT_TOKEN": "old"}}, headers=H)
    fake.calls.clear()
    r = c.post(
        f"/v1/workspaces/{WID}/start",
        json={"env": {"FABAGENT_TOKEN": "fresh"}},
        headers=H,
    )
    assert r.status_code == 200
    verbs = [a[0] for a, _ in fake.calls]
    assert "rm" in verbs and "run" in verbs  # replaced, volumes untouched
    assert not any(a[:2] == ["volume", "rm"] for a, _ in fake.calls)
    run_env = next(e for a, e in fake.calls if a[0] == "run" and f"fab-ws-{WID}" in a)
    assert run_env["FABAGENT_TOKEN"] == "fresh"
    # without an environment it is a plain start
    c.post(f"/v1/workspaces/{WID}/stop", headers=H)
    fake.calls.clear()
    c.post(f"/v1/workspaces/{WID}/start", headers=H)
    assert [a[0] for a, _ in fake.calls] == ["start"]
