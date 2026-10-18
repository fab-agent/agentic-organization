"""The only code that talks to Docker (ADR-0018 §1).

Every argument is built from validated ids and fixed settings; nothing from a request
is ever used as an image name, a mount, a network or a free path. Commands run as argv
lists (no shell). Secrets go through the child's environment, not argv.

Isolation model:
  * one internal-only network *per workspace*; the shared egress proxy is attached to
    each of them, so workspaces cannot reach each other and the controller/backend are on
    no workspace network at all;
  * file access goes through a throw-away helper container (see fileio.py), not through
    `docker cp`, so links are never followed and the agent's own uid is used;
  * lifecycle calls for one workspace are serialised by a lock.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from fileio import SCRIPT

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ENV_ALLOW = {"FABAGENT_BASE_URL", "FABAGENT_TOKEN", "OPENCODE_MODEL"}
AREAS = ("in", "out")
AGENT_UID = 10001
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_LIST_BYTES = 400 * 1024 * 1024
EXTERNAL = "fab-ws-external"
EGRESS = "fab-ws-egress"
LABEL = "fab.managed=workspace-controller"

# (args, stdin, extra env) -> stdout bytes; raises DockerError on failure.
Runner = Callable[[list[str], bytes | None, dict[str, str] | None], bytes]
# (args, stdin, max_out) -> (exit code, stdout); stdout never exceeds max_out+1 bytes.
Helper = Callable[[list[str], bytes | None, int], tuple[int, bytes]]


class DockerError(Exception):
    """A Docker failure. `public` is the stable, secret-free text the API may return."""

    def __init__(self, public: str, detail: str = ""):
        super().__init__(public)
        self.public = public
        self.detail = detail


class BadInput(ValueError):
    pass


class TooLarge(ValueError):
    pass


def check_id(workspace_id: str) -> str:
    if not isinstance(workspace_id, str) or not UUID_RE.fullmatch(workspace_id):
        raise BadInput("workspace id must be a UUID")
    return workspace_id


def check_env(env: dict[str, str]) -> None:
    for k, v in env.items():
        if k not in ENV_ALLOW:
            raise BadInput(f"environment {k!r} is not allowed")
        if not isinstance(v, str) or len(v) > 4000 or any(c in v for c in "\x00\r\n"):
            raise BadInput(f"environment {k!r} has an invalid value")


def safe_rel(path: str) -> str:
    """A relative path inside in/ or out/: plain segments only."""
    if not isinstance(path, str) or not path or len(path) > 400 or "\x00" in path:
        raise BadInput("bad path")
    parts = path.split("/")
    if path.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise BadInput("bad path")
    if parts[0] not in AREAS or len(parts) < 2:
        raise BadInput("path must be under in/ or out/")
    if any(len(p) > 200 or any(ord(c) < 32 for c in p) for p in parts):
        raise BadInput("bad path")
    return path


def default_runner(args, stdin=None, env=None) -> bytes:
    full_env = {**os.environ, **(env or {})}
    try:
        res = subprocess.run(  # noqa: S603 - argv of validated ids and fixed flags, no shell
            ["docker", *args],  # noqa: S607
            input=stdin,
            capture_output=True,
            env=full_env,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        raise DockerError("docker unavailable", type(e).__name__) from e
    if res.returncode != 0:
        raise DockerError(
            "docker command failed", res.stderr.decode("utf-8", "replace").strip()[:300]
        )
    return res.stdout


def default_helper(args, stdin=None, max_out=MAX_FILE_BYTES) -> tuple[int, bytes]:
    """Run a helper container with a hard cap on the bytes taken from it."""
    try:
        p = subprocess.Popen(  # noqa: S603 - argv of validated ids and fixed flags, no shell
            ["docker", *args],  # noqa: S607
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, ValueError) as e:
        raise DockerError("docker unavailable", type(e).__name__) from e
    timer = threading.Timer(300, p.kill)
    timer.start()
    try:
        if stdin is not None:
            try:
                p.stdin.write(stdin)  # type: ignore[union-attr]
                p.stdin.close()  # type: ignore[union-attr]
            except BrokenPipeError:
                pass
        chunks, total = [], 0
        while True:
            chunk = p.stdout.read(1 << 20)  # type: ignore[union-attr]
            if not chunk:
                break
            total += len(chunk)
            if total > max_out:
                p.kill()
                p.wait()
                raise TooLarge("output too large")
            chunks.append(chunk)
        p.wait()
        return p.returncode, b"".join(chunks)
    finally:
        timer.cancel()
        if p.poll() is None:
            p.kill()


@dataclass
class Config:
    image: str
    egress_image: str
    memory: str = "4g"
    cpus: str = "2"
    pids: str = "1024"
    public_base_url: str = ""
    model: str = ""


class Docker:
    def __init__(
        self, cfg: Config, run: Runner = default_runner, helper: Helper = default_helper
    ):
        self.cfg = cfg
        self.run = run
        self.helper = helper
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._infra = threading.Lock()

    def lock(self, wid: str) -> threading.Lock:
        return self._locks[check_id(wid)]

    # names ---------------------------------------------------------------
    @staticmethod
    def cname(wid: str) -> str:
        return f"fab-ws-{check_id(wid)}"

    @staticmethod
    def vol(wid: str, kind: str) -> str:
        return f"fab-ws-{check_id(wid)}-{kind}"

    @staticmethod
    def net(wid: str) -> str:
        return f"fab-ws-{check_id(wid)}-net"

    # infrastructure ------------------------------------------------------
    def _inspect(self, kind: str, name: str, fmt: str) -> str | None:
        try:
            return (
                self.run([kind, "inspect", "-f", fmt, name], None, None)
                .decode()
                .strip()
            )
        except DockerError as e:
            if "No such" in e.detail or "not found" in e.detail.lower():
                return None
            raise

    def ensure_infra(self, base_url: str) -> None:
        """The external network and the filtering egress proxy; verified, not assumed."""
        with self._infra:
            if self._inspect("network", EXTERNAL, "{{.Name}}") is None:
                self.run(["network", "create", "--label", LABEL, EXTERNAL], None, None)
            state = self._inspect(
                "container",
                EGRESS,
                '{{.State.Running}}|{{.Config.Image}}|{{index .Config.Labels "fab.managed"}}',
            )
            if state is not None:
                running, image, label = (state.split("|") + ["", "", ""])[:3]
                if label != "workspace-controller" or image != self.cfg.egress_image:
                    # not ours or out of date: replace rather than trust it
                    self.run(["rm", "-f", EGRESS], None, None)
                    state = None
            if state is None:
                env = {"FABAGENT_BASE_URL": base_url}
                self.run(
                    [
                        "run",
                        "-d",
                        "--name",
                        EGRESS,
                        "--restart",
                        "unless-stopped",
                        "--label",
                        LABEL,
                        "--network",
                        EXTERNAL,
                        "--cap-drop",
                        "ALL",
                        "--security-opt",
                        "no-new-privileges:true",
                        "--memory",
                        "128m",
                        "--cpus",
                        "0.5",
                        "--pids-limit",
                        "64",
                        "-e",
                        "FABAGENT_BASE_URL",
                        self.cfg.egress_image,
                    ],
                    None,
                    env,
                )
            elif state.split("|")[0] != "true":
                self.run(["start", EGRESS], None, None)

    def ensure_network(self, wid: str) -> None:
        """This workspace's own internal-only network, with the proxy attached."""
        name = self.net(wid)
        internal = self._inspect("network", name, "{{.Internal}}")
        if internal is None:
            self.run(
                ["network", "create", "--internal", "--label", LABEL, name], None, None
            )
        elif internal != "true":
            raise DockerError("network is not isolated", name)
        attached = (
            self._inspect("network", name, "{{range .Containers}}{{.Name}} {{end}}")
            or ""
        )
        if EGRESS not in attached.split():
            self.run(["network", "connect", name, EGRESS], None, None)

    # lifecycle -----------------------------------------------------------
    def create(
        self, wid: str, env: dict[str, str], *, new_volumes: bool = True
    ) -> None:
        check_env(env)
        with self.lock(wid):
            self._create(wid, env, new_volumes)

    def _create(self, wid: str, env: dict[str, str], new_volumes: bool) -> None:
        name = self.cname(wid)
        if self.status_of(name) != "missing":
            return  # idempotent
        self.ensure_infra(env.get("FABAGENT_BASE_URL", self.cfg.public_base_url))
        for kind in ("home", "files"):
            if new_volumes:
                self.run(
                    ["volume", "create", "--label", LABEL, self.vol(wid, kind)],
                    None,
                    None,
                )
            elif self._inspect("volume", self.vol(wid, kind), "{{.Name}}") is None:
                raise DockerError("volume already purged")
        self.ensure_network(wid)
        args = [
            "run",
            "-d",
            "--name",
            name,
            "--label",
            LABEL,
            "--network",
            self.net(wid),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--memory",
            self.cfg.memory,
            "--cpus",
            self.cfg.cpus,
            "--pids-limit",
            self.cfg.pids,
            "-v",
            f"{self.vol(wid, 'home')}:/home/agent",
            "-v",
            f"{self.vol(wid, 'files')}:/workspace",
            "-e",
            f"HTTP_PROXY=http://{EGRESS}:8888",
            "-e",
            f"HTTPS_PROXY=http://{EGRESS}:8888",
            "-e",
            f"http_proxy=http://{EGRESS}:8888",
            "-e",
            f"https_proxy=http://{EGRESS}:8888",
            "-e",
            "NO_PROXY=localhost,127.0.0.1,::1",
            "-e",
            "no_proxy=localhost,127.0.0.1,::1",
        ]
        for key in env:
            args += ["-e", key]  # value comes from the child's environment
        args.append(self.cfg.image)
        try:
            self.run(args, None, dict(env))
        except DockerError:
            # a half-made container must not be mistaken for a finished one later
            try:
                self.run(["rm", "-f", name], None, None)
            except DockerError:
                pass
            raise

    def start(self, wid: str) -> None:
        with self.lock(wid):
            self.run(["start", self.cname(wid)], None, None)

    def recreate(self, wid: str, env: dict[str, str]) -> None:
        """Replace the container (same volumes) so it starts with a fresh environment."""
        check_env(env)  # before anything destructive
        with self.lock(wid):
            name = self.cname(wid)
            if self.status_of(name) == "running":
                self.run(["stop", "-t", "20", name], None, None)
            self._remove(wid)
            self._create(wid, env, new_volumes=False)

    def stop(self, wid: str) -> None:
        with self.lock(wid):
            self.run(["stop", "-t", "20", self.cname(wid)], None, None)

    def remove(self, wid: str) -> None:
        with self.lock(wid):
            self._remove(wid)

    def _remove(self, wid: str) -> None:
        name = self.cname(wid)
        try:
            self.run(["rm", "-f", name], None, None)
        except DockerError:
            if self.status_of(name) != "missing":
                raise

    def restore(self, wid: str, env: dict[str, str]) -> None:
        check_env(env)
        with self.lock(wid):
            self._create(wid, env, new_volumes=False)  # never recreates a purged volume

    def purge_volume(self, wid: str) -> None:
        with self.lock(wid):
            if self.status_of(self.cname(wid)) != "missing":
                raise DockerError("remove the container before purging")
            for kind in ("home", "files"):
                if (
                    self._inspect("volume", self.vol(wid, kind), "{{.Name}}")
                    is not None
                ):
                    self.run(["volume", "rm", self.vol(wid, kind)], None, None)
            name = self.net(wid)
            if self._inspect("network", name, "{{.Name}}") is not None:
                try:
                    self.run(["network", "disconnect", name, EGRESS], None, None)
                except DockerError:
                    pass
                self.run(["network", "rm", name], None, None)

    def status_of(self, name: str) -> str:
        out = self._inspect("container", name, "{{.State.Running}}")
        if out is None:
            return "missing"
        return "running" if out == "true" else "stopped"

    def status(self, wid: str) -> str:
        return self.status_of(self.cname(wid))

    # files ---------------------------------------------------------------
    def _helper(
        self,
        wid: str,
        mode: str,
        rel: str,
        *,
        rw: bool,
        data: bytes | None = None,
        max_out: int = MAX_FILE_BYTES,
    ) -> bytes:
        if self._inspect("volume", self.vol(wid, "files"), "{{.Name}}") is None:
            raise FileNotFoundError(rel)  # never let `-v` create a volume
        args = [
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--user",
            f"{AGENT_UID}:{AGENT_UID}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--read-only",
            "--memory",
            "256m",
            "--pids-limit",
            "64",
            "--label",
            LABEL,
            "-e",
            f"CAP={MAX_FILE_BYTES}",
            "-e",
            f"LIST_BUDGET={MAX_LIST_BYTES}",
            "-v",
            f"{self.vol(wid, 'files')}:/workspace" + ("" if rw else ":ro"),
            "--entrypoint",
            "python3",
            self.cfg.image,
            "-c",
            SCRIPT,
            mode,
            rel,
        ]
        code, out = self.helper(
            args,
            data if data is not None else (b"" if mode == "write" else None),
            max_out,
        )
        if code == 0:
            return out
        if code == 3:
            raise FileNotFoundError(rel)
        if code == 4:
            raise TooLarge("too large")
        if code == 5:
            raise BadInput("path refused")
        raise DockerError("file operation failed", f"exit {code}")

    def list_files(self, wid: str, area: str) -> list[dict]:
        check_id(wid)
        if area not in AREAS:
            raise BadInput("area must be in or out")
        try:
            raw = self._helper(wid, "list", area, rw=False, max_out=8 * 1024 * 1024)
        except FileNotFoundError:
            return []
        files = json.loads(raw or b"[]")
        return sorted(
            (
                {
                    "path": f"{area}/{f['path']}",
                    "size": int(f["size"]),
                    "sha256": str(f["sha256"]),
                    "mtime_ns": int(f["mtime_ns"]),
                }
                for f in files
            ),
            key=lambda f: f["path"],
        )

    def read_file(self, wid: str, path: str) -> bytes:
        check_id(wid)
        safe_rel(path)
        return self._helper(wid, "read", path, rw=False, max_out=MAX_FILE_BYTES)

    def write_file(self, wid: str, path: str, data: bytes) -> None:
        check_id(wid)
        safe_rel(path)
        if not path.startswith("in/"):
            raise BadInput("uploads go to in/")
        if len(data) > MAX_FILE_BYTES:
            raise TooLarge("file too large")
        self._helper(wid, "write", path, rw=True, data=data, max_out=1024)
