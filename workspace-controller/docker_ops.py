"""The only code that talks to Docker (ADR-0018 §1).

Every argument is built from validated ids and fixed settings; nothing from a request
is ever used as an image name, a mount, a network or a free path. Commands run as argv
lists (no shell). Secrets go through the child's environment, not argv.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import subprocess
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ENV_ALLOW = {"FABAGENT_BASE_URL", "FABAGENT_TOKEN", "OPENCODE_MODEL"}
AREAS = ("in", "out")
AGENT_UID = 10001
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_LIST_BYTES = 400 * 1024 * 1024
NETWORK = "fab-ws-internal"
EGRESS = "fab-ws-egress"

# (args, stdin, extra env) -> stdout bytes; raises DockerError on failure.
Runner = Callable[[list[str], bytes | None, dict[str, str] | None], bytes]


class DockerError(Exception):
    pass


class BadInput(ValueError):
    pass


def check_id(workspace_id: str) -> str:
    if not isinstance(workspace_id, str) or not UUID_RE.fullmatch(workspace_id):
        raise BadInput("workspace id must be a UUID")
    return workspace_id


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
        res = subprocess.run(
            ["docker", *args],
            input=stdin,
            capture_output=True,
            env=full_env,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DockerError(type(e).__name__) from e
    if res.returncode != 0:
        # stderr can name paths and images, never secrets (those are in env only)
        raise DockerError(res.stderr.decode("utf-8", "replace").strip()[:300])
    return res.stdout


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
    def __init__(self, cfg: Config, run: Runner = default_runner):
        self.cfg = cfg
        self.run = run

    # names ---------------------------------------------------------------
    @staticmethod
    def cname(wid: str) -> str:
        return f"fab-ws-{check_id(wid)}"

    @staticmethod
    def vol(wid: str, kind: str) -> str:
        return f"fab-ws-{check_id(wid)}-{kind}"

    # infrastructure ------------------------------------------------------
    def ensure_infra(self, base_url: str) -> None:
        """The internal-only network and the filtering egress proxy (idempotent)."""
        if not self._exists("network", NETWORK):
            self.run(["network", "create", "--internal", NETWORK], None, None)
        if self.status_of(EGRESS) == "missing":
            env = {"FABAGENT_BASE_URL": base_url}
            self.run(
                [
                    "run",
                    "-d",
                    "--name",
                    EGRESS,
                    "--restart",
                    "unless-stopped",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--memory",
                    "128m",
                    "--pids-limit",
                    "64",
                    "-e",
                    "FABAGENT_BASE_URL",
                    self.cfg.egress_image,
                ],
                None,
                env,
            )
            self.run(["network", "connect", NETWORK, EGRESS], None, None)
        elif self.status_of(EGRESS) == "stopped":
            self.run(["start", EGRESS], None, None)

    def _exists(self, kind: str, name: str) -> bool:
        try:
            self.run([kind, "inspect", name], None, None)
            return True
        except DockerError:
            return False

    # lifecycle -----------------------------------------------------------
    def create(self, wid: str, env: dict[str, str]) -> None:
        for k, v in env.items():
            if (
                k not in ENV_ALLOW
                or not isinstance(v, str)
                or "\n" in v
                or len(v) > 4000
            ):
                raise BadInput(f"environment {k!r} is not allowed")
        name = self.cname(wid)
        if self.status_of(name) != "missing":
            return  # idempotent
        self.ensure_infra(env.get("FABAGENT_BASE_URL", self.cfg.public_base_url))
        for kind in ("home", "files"):
            self.run(["volume", "create", self.vol(wid, kind)], None, None)
        child_env = dict(env)
        args = [
            "run",
            "-d",
            "--name",
            name,
            "--network",
            NETWORK,
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
        self.run(args, None, child_env)

    def start(self, wid: str) -> None:
        self.run(["start", self.cname(wid)], None, None)

    def recreate(self, wid: str, env: dict[str, str]) -> None:
        """Replace the container (same volumes) so it starts with a fresh environment."""
        self.run(["stop", "-t", "20", self.cname(wid)], None, None) if self.status(
            wid
        ) == "running" else None
        self.remove(wid)
        self.create(wid, env)

    def stop(self, wid: str) -> None:
        self.run(["stop", "-t", "20", self.cname(wid)], None, None)

    def remove(self, wid: str) -> None:
        try:
            self.run(["rm", "-f", self.cname(wid)], None, None)
        except DockerError:
            if self.status_of(self.cname(wid)) != "missing":
                raise

    def restore(self, wid: str, env: dict[str, str]) -> None:
        for kind in ("home", "files"):
            if not self._exists("volume", self.vol(wid, kind)):
                raise DockerError("volume already purged")
        self.create_on_volumes(wid, env)

    def create_on_volumes(self, wid: str, env: dict[str, str]) -> None:
        # same as create, volumes already exist (volume create is idempotent)
        self.create(wid, env)

    def purge_volume(self, wid: str) -> None:
        for kind in ("home", "files"):
            try:
                self.run(["volume", "rm", self.vol(wid, kind)], None, None)
            except DockerError:
                if self._exists("volume", self.vol(wid, kind)):
                    raise

    def status_of(self, name: str) -> str:
        try:
            out = self.run(["inspect", "-f", "{{.State.Running}}", name], None, None)
        except DockerError:
            return "missing"
        return "running" if out.strip() == b"true" else "stopped"

    def status(self, wid: str) -> str:
        return self.status_of(self.cname(wid))

    # files ---------------------------------------------------------------
    def list_files(self, wid: str, area: str) -> list[dict]:
        if area not in AREAS:
            raise BadInput("area must be in or out")
        try:
            blob = self.run(
                ["cp", f"{self.cname(wid)}:/workspace/{area}/.", "-"], None, None
            )
        except DockerError as e:
            raise DockerError(f"cannot list: {e}") from e
        if len(blob) > MAX_LIST_BYTES:
            raise DockerError("area too large to list")
        out = []
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            for m in tar:
                if not m.isreg():  # symlinks, devices, directories are never reported
                    continue
                rel = m.name.removeprefix("./")
                data = tar.extractfile(m).read()  # type: ignore[union-attr]
                out.append(
                    {
                        "path": f"{area}/{rel}",
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "mtime_ns": int(m.mtime * 1_000_000_000),
                    }
                )
        return sorted(out, key=lambda f: f["path"])

    def read_file(self, wid: str, path: str) -> bytes:
        safe_rel(path)
        try:
            blob = self.run(
                ["cp", f"{self.cname(wid)}:/workspace/{path}", "-"], None, None
            )
        except DockerError as e:
            if "Could not find the file" in str(e):
                raise FileNotFoundError(path) from None
            raise
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            members = [m for m in tar if m.isreg()]
            if len(members) != 1:
                raise FileNotFoundError(path)
            data = tar.extractfile(members[0]).read()  # type: ignore[union-attr]
        if len(data) > MAX_FILE_BYTES:
            raise DockerError("file too large")
        return data

    def write_file(self, wid: str, path: str, data: bytes) -> None:
        safe_rel(path)
        if not path.startswith("in/"):
            raise BadInput("uploads go to in/")
        if len(data) > MAX_FILE_BYTES:
            raise BadInput("file too large")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            parts = path.split("/")
            for i in range(1, len(parts)):  # explicit dirs owned by the agent user
                d = tarfile.TarInfo("/".join(parts[:i]))
                d.type, d.mode, d.uid, d.gid, d.mtime = (
                    tarfile.DIRTYPE,
                    0o755,
                    AGENT_UID,
                    AGENT_UID,
                    int(time.time()),
                )
                tar.addfile(d)
            f = tarfile.TarInfo(path)
            f.size, f.mode, f.uid, f.gid, f.mtime = (
                len(data),
                0o644,
                AGENT_UID,
                AGENT_UID,
                int(time.time()),
            )
            tar.addfile(f, io.BytesIO(data))
        self.run(["cp", "-", f"{self.cname(wid)}:/workspace"], buf.getvalue(), None)
