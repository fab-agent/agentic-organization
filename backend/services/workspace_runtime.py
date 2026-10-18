"""Workspace runtime interface (ADR-0018 §1).

The backend never touches a container runtime directly: it talks to a
`WorkspaceRuntime`. The production implementation is a client for the separate
`workspace-controller` service and does not exist yet; `FakeRuntime` is the
in-memory implementation used by tests and local development
(`WORKSPACE_RUNTIME=fake`).
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException


class WorkspaceRuntimeError(Exception):
    """The runtime could not do what was asked (maps to 502 at the API)."""


class FileNotFound(WorkspaceRuntimeError):
    """The requested file does not exist in the workspace (maps to 404)."""


@dataclass(frozen=True)
class WorkspaceSpec:
    workspace_id: str
    company_id: str
    personnel_id: str
    # Environment for the agent process (persona token, gateway URL, model). Never logged.
    env: dict | None = None


@dataclass(frozen=True)
class FileInfo:
    path: str  # relative to the workspace root, e.g. "out/report.xlsx"
    size: int
    sha256: str
    mtime_ns: int


class WorkspaceRuntime(Protocol):
    def create(self, spec: WorkspaceSpec) -> None:
        """Create the volume + container and start it."""

    def start(self, workspace_id: str, env: dict | None = None) -> None:
        """Start (resume). With `env` the container is recreated on its volumes so the
        agent starts with a fresh persona token."""

    def stop(self, workspace_id: str) -> None: ...

    def remove(self, workspace_id: str) -> None:
        """Remove the container, KEEP the volume (restorable for 7 days)."""

    def restore(self, workspace_id: str, env: dict | None = None) -> None:
        """Recreate the container on the kept volume and start it."""

    def purge_volume(self, workspace_id: str) -> None: ...

    def status(self, workspace_id: str) -> str:
        """'running' | 'stopped' | 'missing'."""

    def list_files(self, workspace_id: str, area: str) -> list[FileInfo]: ...

    def read_file(self, workspace_id: str, path: str) -> bytes: ...

    def write_file(self, workspace_id: str, path: str, data: bytes) -> None: ...


class FakeRuntime:
    """In-memory runtime. `fail_next` makes the next call raise (for tests)."""

    def __init__(self) -> None:
        self.containers: dict[str, str] = {}  # id -> running | stopped
        self.volumes: set[str] = set()
        self.files: dict[str, dict[str, tuple[bytes, int]]] = {}
        self.fail_next: str | None = None
        self.calls: list[tuple[str, str]] = []

    def _enter(self, op: str, wid: str) -> None:
        self.calls.append((op, wid))
        if self.fail_next == op:
            self.fail_next = None
            raise WorkspaceRuntimeError(f"{op} failed")

    def create(self, spec: WorkspaceSpec) -> None:
        self._enter("create", spec.workspace_id)
        self.volumes.add(spec.workspace_id)
        self.files.setdefault(spec.workspace_id, {})
        self.containers[spec.workspace_id] = "running"

    def start(self, workspace_id: str, env: dict | None = None) -> None:
        self._enter("start", workspace_id)
        if workspace_id not in self.containers:
            raise WorkspaceRuntimeError("no such container")
        self.containers[workspace_id] = "running"

    def stop(self, workspace_id: str) -> None:
        self._enter("stop", workspace_id)
        if workspace_id not in self.containers:
            raise WorkspaceRuntimeError("no such container")
        self.containers[workspace_id] = "stopped"

    def remove(self, workspace_id: str) -> None:
        self._enter("remove", workspace_id)
        self.containers.pop(workspace_id, None)

    def restore(self, workspace_id: str, env: dict | None = None) -> None:
        self._enter("restore", workspace_id)
        if workspace_id not in self.volumes:
            raise WorkspaceRuntimeError("volume already purged")
        self.containers[workspace_id] = "running"

    def purge_volume(self, workspace_id: str) -> None:
        self._enter("purge_volume", workspace_id)
        self.volumes.discard(workspace_id)
        self.files.pop(workspace_id, None)

    def status(self, workspace_id: str) -> str:
        return self.containers.get(workspace_id, "missing")

    def list_files(self, workspace_id: str, area: str) -> list[FileInfo]:
        prefix = area.strip("/") + "/"
        out = []
        for path, (data, mtime_ns) in sorted(self.files.get(workspace_id, {}).items()):
            if path.startswith(prefix):
                out.append(
                    FileInfo(
                        path, len(data), hashlib.sha256(data).hexdigest(), mtime_ns
                    )
                )
        return out

    def read_file(self, workspace_id: str, path: str) -> bytes:
        try:
            return self.files[workspace_id][path][0]
        except KeyError:
            raise FileNotFound(path) from None

    def write_file(self, workspace_id: str, path: str, data: bytes) -> None:
        self._enter("write_file", workspace_id)
        if workspace_id not in self.volumes:
            raise WorkspaceRuntimeError("no such volume")
        self.files.setdefault(workspace_id, {})[path] = (data, time.time_ns())


class ControllerRuntime:
    """Client of the separate `workspace-controller` (ADR-0018 §1).

    The backend never touches Docker; it calls the controller over the internal
    network with a shared secret. Every failure becomes `WorkspaceRuntimeError`.
    """

    def __init__(self, url: str, secret: str, client=None, timeout: float = 120.0):
        import httpx

        if len(secret) < 32:
            raise WorkspaceRuntimeError("WORKSPACE_CONTROLLER_SECRET is too short")
        self._url = url.rstrip("/")
        self._h = {"X-Controller-Secret": secret}
        self._c = client or httpx.Client(timeout=timeout)

    def _call(self, method: str, path: str, **kw):
        import httpx

        try:
            r = self._c.request(method, f"{self._url}{path}", headers=self._h, **kw)
        except httpx.HTTPError as e:
            raise WorkspaceRuntimeError(
                f"controller unreachable: {type(e).__name__}"
            ) from e
        if r.status_code == 404:
            raise FileNotFound(path)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = None
            raise WorkspaceRuntimeError(
                f"controller {r.status_code}: {str(detail)[:200]}"
            )
        return r

    def create(self, spec: WorkspaceSpec) -> None:
        self._call(
            "POST", f"/v1/workspaces/{spec.workspace_id}", json={"env": spec.env or {}}
        )

    def start(self, workspace_id: str, env: dict | None = None) -> None:
        self._call(
            "POST", f"/v1/workspaces/{workspace_id}/start", json={"env": env or {}}
        )

    def stop(self, workspace_id: str) -> None:
        self._call("POST", f"/v1/workspaces/{workspace_id}/stop")

    def remove(self, workspace_id: str) -> None:
        self._call("POST", f"/v1/workspaces/{workspace_id}/remove")

    def restore(self, workspace_id: str, env: dict | None = None) -> None:
        self._call(
            "POST", f"/v1/workspaces/{workspace_id}/restore", json={"env": env or {}}
        )

    def purge_volume(self, workspace_id: str) -> None:
        self._call("POST", f"/v1/workspaces/{workspace_id}/purge")

    def status(self, workspace_id: str) -> str:
        return self._call("GET", f"/v1/workspaces/{workspace_id}/status").json()[
            "status"
        ]

    def list_files(self, workspace_id: str, area: str) -> list[FileInfo]:
        r = self._call(
            "GET", f"/v1/workspaces/{workspace_id}/files", params={"area": area}
        )
        return [
            FileInfo(f["path"], f["size"], f["sha256"], f["mtime_ns"])
            for f in r.json()["files"]
        ]

    def read_file(self, workspace_id: str, path: str) -> bytes:
        return self._call(
            "GET", f"/v1/workspaces/{workspace_id}/file", params={"path": path}
        ).content

    def write_file(self, workspace_id: str, path: str, data: bytes) -> None:
        self._call(
            "PUT",
            f"/v1/workspaces/{workspace_id}/file",
            params={"path": path},
            content=data,
        )


_fake = FakeRuntime()
_controller: ControllerRuntime | None = None


def get_runtime() -> WorkspaceRuntime:
    """FastAPI dependency. Fails closed (503) until a runtime is configured."""
    kind = os.getenv("WORKSPACE_RUNTIME", "").strip().lower()
    if kind == "fake":
        return _fake
    if kind == "controller":
        global _controller
        if _controller is None:
            url = os.getenv("WORKSPACE_CONTROLLER_URL", "")
            secret = os.getenv("WORKSPACE_CONTROLLER_SECRET", "")
            if not url or not secret:
                raise HTTPException(
                    status_code=503,
                    detail="WORKSPACE_CONTROLLER_URL / _SECRET are not set",
                )
            try:
                _controller = ControllerRuntime(url, secret)
            except WorkspaceRuntimeError as e:
                raise HTTPException(status_code=503, detail=str(e))
        return _controller
    raise HTTPException(
        status_code=503,
        detail="Workspace runtime is not configured (WORKSPACE_RUNTIME)",
    )
