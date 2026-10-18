"""Controller behaviour with a fake docker runner and a fake file helper (no Docker)."""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import build_app  # noqa: E402
from docker_ops import BadInput, Config, Docker, DockerError, safe_rel  # noqa: E402

WID = "11111111-2222-3333-4444-555555555555"
WID2 = "99999999-2222-3333-4444-555555555555"
SECRET = "aB3dE5gH7jK9mN1pQ3sT5vW7yZ0bC2dE4fG6"
H = {"X-Controller-Secret": SECRET}
IMG, EGR = "ws:test", "eg:test"


class Fake:
    """Just enough of Docker: containers, volumes, networks."""

    def __init__(self):
        self.calls = []
        self.containers = {}  # name -> dict(running, image, label)
        self.volumes = set()
        self.networks = {}  # name -> dict(internal, members)

    def __call__(self, args, stdin=None, env=None):
        self.calls.append((list(args), env))
        a = args
        if a[1:3] == ["inspect", "-f"] or (len(a) > 2 and a[1] == "inspect"):
            kind, fmt, name = a[0], a[3], a[4]
            if kind == "container":
                c = self.containers.get(name)
                if c is None:
                    raise DockerError(
                        "docker command failed", "Error: No such container"
                    )
                if fmt == "{{.State.Running}}":
                    return b"true" if c["running"] else b"false"
                return f"{'true' if c['running'] else 'false'}|{c['image']}|{c['label']}".encode()
            if kind == "volume":
                if name not in self.volumes:
                    raise DockerError("docker command failed", "Error: No such volume")
                return name.encode()
            if kind == "network":
                n = self.networks.get(name)
                if n is None:
                    raise DockerError("docker command failed", "Error: No such network")
                if fmt == "{{.Internal}}":
                    return b"true" if n["internal"] else b"false"
                if "Containers" in fmt:
                    return (" ".join(sorted(n["members"])) + " ").encode()
                return name.encode()
        if a[:2] == ["network", "create"]:
            self.networks[a[-1]] = {"internal": "--internal" in a, "members": set()}
            return b""
        if a[:2] == ["network", "connect"]:
            self.networks[a[2]]["members"].add(a[3])
            return b""
        if a[:2] == ["network", "disconnect"]:
            self.networks[a[2]]["members"].discard(a[3])
            return b""
        if a[:2] == ["network", "rm"]:
            self.networks.pop(a[2], None)
            return b""
        if a[:2] == ["volume", "create"]:
            self.volumes.add(a[-1])
            return b""
        if a[:2] == ["volume", "rm"]:
            self.volumes.discard(a[2])
            return b""
        if a[0] == "run":
            name = a[a.index("--name") + 1]
            net = a[a.index("--network") + 1]
            self.containers[name] = {
                "running": True,
                "image": a[-1],
                "label": "workspace-controller",
            }
            if net in self.networks:
                self.networks[net]["members"].add(name)
            return b"cid"
        if a[0] == "start":
            self.containers[a[1]]["running"] = True
            return b""
        if a[0] == "stop":
            self.containers[a[-1]]["running"] = False
            return b""
        if a[0] == "rm":
            self.containers.pop(a[-1], None)
            return b""
        raise AssertionError(a)


class Helper:
    def __init__(self):
        self.calls = []
        self.reply = (0, b"")

    def __call__(self, args, stdin=None, max_out=0):
        self.calls.append((list(args), stdin, max_out))
        return self.reply


@pytest.fixture()
def ctl():
    fake, helper = Fake(), Helper()
    docker = Docker(Config(image=IMG, egress_image=EGR), run=fake, helper=helper)
    return TestClient(build_app(docker, SECRET)), fake, helper


def test_a_weak_secret_refuses_to_start():
    for weak in ("short", "a" * 40, "ab" * 20):
        with pytest.raises(RuntimeError):
            build_app(Docker(Config("i", "e"), run=Fake(), helper=Helper()), weak)


def test_every_privileged_call_needs_the_secret(ctl):
    c, *_ = ctl
    assert c.post(f"/v1/workspaces/{WID}", json={}).status_code == 401
    assert (
        c.post(
            f"/v1/workspaces/{WID}", json={}, headers={"X-Controller-Secret": "x" * 40}
        ).status_code
        == 401
    )
    assert c.get(f"/v1/workspaces/{WID}/files").status_code == 401
    assert c.get("/health").status_code == 200  # liveness only


def test_ids_must_be_uuids_and_nothing_else_reaches_docker(ctl):
    c, fake, _ = ctl
    for bad in ("../etc", "abc", f"{WID};rm", "ZZZZ"):
        assert c.post(f"/v1/workspaces/{bad}/start", headers=H).status_code in (
            404,
            422,
        ), bad
    assert fake.calls == []


def test_create_is_hardened_isolated_idempotent_and_keeps_the_token_out_of_argv(ctl):
    c, fake, _ = ctl
    env = {
        "FABAGENT_BASE_URL": "https://agents.example",
        "FABAGENT_TOKEN": "tok-secret",
    }
    r = c.post(f"/v1/workspaces/{WID}", json={"env": env}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "running"
    run = next(a for a, _ in fake.calls if a[0] == "run" and f"fab-ws-{WID}" in a)
    assert "--cap-drop" in run and "ALL" in run and "no-new-privileges:true" in run
    assert run[run.index("--network") + 1] == f"fab-ws-{WID}-net"  # its own network
    assert not any(x == "--privileged" or "docker.sock" in x for x in run)
    assert "tok-secret" not in " ".join(run)
    assert next(e for a, e in fake.calls if a == run)["FABAGENT_TOKEN"] == "tok-secret"
    # the workspace network is internal and carries the proxy; the proxy itself sits on the external one
    assert fake.networks[f"fab-ws-{WID}-net"]["internal"] is True
    assert "fab-ws-egress" in fake.networks[f"fab-ws-{WID}-net"]["members"]
    c.post(f"/v1/workspaces/{WID}", json={"env": env}, headers=H)
    assert sum(1 for a, _ in fake.calls if a[0] == "run" and f"fab-ws-{WID}" in a) == 1


def test_two_workspaces_never_share_a_network(ctl):
    c, fake, _ = ctl
    c.post(f"/v1/workspaces/{WID}", json={"env": {}}, headers=H)
    c.post(f"/v1/workspaces/{WID2}", json={"env": {}}, headers=H)
    a, b = fake.networks[f"fab-ws-{WID}-net"], fake.networks[f"fab-ws-{WID2}-net"]
    assert f"fab-ws-{WID}" in a["members"] and f"fab-ws-{WID}" not in b["members"]
    assert f"fab-ws-{WID2}" in b["members"] and f"fab-ws-{WID2}" not in a["members"]


def test_environment_is_an_allowlist_with_clean_values(ctl):
    c, fake, _ = ctl
    for key in ("PATH", "LD_PRELOAD", "DOCKER_HOST", "FABAGENT_TOKEN\nX"):
        assert (
            c.post(
                f"/v1/workspaces/{WID}", json={"env": {key: "x"}}, headers=H
            ).status_code
            == 422
        ), key
    for bad in ("a\nb", "a\x00b", "a\rb"):
        assert (
            c.post(
                f"/v1/workspaces/{WID}",
                json={"env": {"FABAGENT_TOKEN": bad}},
                headers=H,
            ).status_code
            == 422
        )
    assert (
        c.post(f"/v1/workspaces/{WID}", json={"image": "evil"}, headers=H).status_code
        == 422
    )
    assert fake.calls == []


def test_a_bad_environment_is_rejected_before_anything_is_removed(ctl):
    c, fake, _ = ctl
    c.post(f"/v1/workspaces/{WID}", json={"env": {"FABAGENT_TOKEN": "old"}}, headers=H)
    fake.calls.clear()
    assert (
        c.post(
            f"/v1/workspaces/{WID}/start", json={"env": {"LD_PRELOAD": "x"}}, headers=H
        ).status_code
        == 422
    )
    assert fake.calls == [] and f"fab-ws-{WID}" in fake.containers


def test_lifecycle_restore_never_recreates_a_purged_volume(ctl):
    c, fake, _ = ctl
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
    # purge needs the container gone first, then removes volumes and the network
    assert c.post(f"/v1/workspaces/{WID}/purge", headers=H).status_code == 502
    c.post(f"/v1/workspaces/{WID}/remove", headers=H)
    assert c.post(f"/v1/workspaces/{WID}/purge", headers=H).status_code == 200
    assert (
        not [v for v in fake.volumes if WID in v]
        and f"fab-ws-{WID}-net" not in fake.networks
    )
    n = len(fake.volumes)
    r = c.post(f"/v1/workspaces/{WID}/restore", json={"env": {}}, headers=H)
    assert r.status_code == 502 and r.json()["detail"] == "volume already purged"
    assert len(fake.volumes) == n  # nothing was created on the way


def test_foreign_or_weakened_infrastructure_is_replaced_not_trusted(ctl):
    c, fake, _ = ctl
    fake.networks["fab-ws-external"] = {"internal": False, "members": set()}
    fake.containers["fab-ws-egress"] = {
        "running": True,
        "image": "somebody/else",
        "label": "",
    }
    fake.networks[f"fab-ws-{WID}-net"] = {
        "internal": False,
        "members": set(),
    }  # not isolated
    r = c.post(f"/v1/workspaces/{WID}", json={"env": {}}, headers=H)
    assert r.status_code == 502  # an existing non-internal workspace network is refused
    assert (
        fake.containers["fab-ws-egress"]["image"] == EGR
    )  # the stranger proxy was replaced


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
    with pytest.raises(BadInput):
        safe_rel(p)


def test_files_go_through_a_locked_down_helper_container(ctl):
    c, fake, helper = ctl
    c.post(f"/v1/workspaces/{WID}", json={"env": {}}, headers=H)
    helper.reply = (
        0,
        json.dumps(
            [{"path": ".env", "size": 1, "sha256": "x", "mtime_ns": 5}]
        ).encode(),
    )
    r = c.get(f"/v1/workspaces/{WID}/files?area=out", headers=H).json()["files"]
    assert [f["path"] for f in r] == ["out/.env"]
    args, _, _cap = helper.calls[-1]
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--user") + 1] == "10001:10001"
    assert "--read-only" in args and "--cap-drop" in args
    assert any(x.endswith(":/workspace:ro") for x in args)  # reads cannot write
    helper.reply = (0, b"hello")
    assert (
        c.get(f"/v1/workspaces/{WID}/file?path=out/a.txt", headers=H).content
        == b"hello"
    )
    assert any(x.endswith(":/workspace:ro") for x in helper.calls[-1][0])
    helper.reply = (0, b"")
    c.put(f"/v1/workspaces/{WID}/file?path=in/sub/a.txt", content=b"data", headers=H)
    wargs, stdin, _ = helper.calls[-1]
    assert stdin == b"data" and not any(x.endswith(":ro") for x in wargs)
    assert wargs[-2:] == ["write", "in/sub/a.txt"]


def test_helper_exit_codes_map_to_http(ctl):
    c, _, helper = ctl
    c.post(f"/v1/workspaces/{WID}", json={"env": {}}, headers=H)
    for code, http in ((3, 404), (4, 413), (5, 422)):
        helper.reply = (code, b"")
        assert (
            c.get(f"/v1/workspaces/{WID}/file?path=out/x", headers=H).status_code
            == http
        )


def test_a_missing_volume_is_not_created_by_a_file_call(ctl):
    c, fake, helper = ctl
    r = c.get(f"/v1/workspaces/{WID}/file?path=out/a.txt", headers=H)
    assert r.status_code == 404 and helper.calls == []
    assert not any(a[:2] == ["volume", "create"] for a, _ in fake.calls)


def test_uploads_only_to_in_and_bounded(ctl):
    c, _, helper = ctl
    c.post(f"/v1/workspaces/{WID}", json={"env": {}}, headers=H)
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
    from docker_ops import MAX_FILE_BYTES

    big = c.put(
        f"/v1/workspaces/{WID}/file?path=in/big",
        content=b"x" * 10,
        headers={**H, "content-length": str(MAX_FILE_BYTES + 1)},
    )
    assert big.status_code in (413, 400)


def test_docker_text_is_not_returned_to_the_caller(ctl):
    c, fake, _ = ctl

    def boom(args, stdin=None, env=None):
        if args[0] == "run":
            raise DockerError(
                "docker command failed",
                "image registry.internal/secret-name: pull access denied",
            )
        return Fake.__call__(fake, args, stdin, env)

    c.app.state  # noqa: B018 - touch app
    docker = Docker(Config(IMG, EGR), run=boom, helper=Helper())
    client = TestClient(build_app(docker, SECRET))
    r = client.post(f"/v1/workspaces/{WID}", json={"env": {}}, headers=H)
    assert r.status_code == 502 and "registry.internal" not in r.text
