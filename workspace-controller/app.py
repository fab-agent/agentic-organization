"""workspace-controller: the single component with container-runtime access (ADR-0018 §1).

Run it where Docker is, reach it only from the backend over an internal network, and
put a verb-filtering socket proxy in front of the Docker socket in production. It has
no user-facing endpoints: every call carries the shared secret, every id is a UUID.
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
import time

from docker_ops import MAX_FILE_BYTES, BadInput, Config, Docker, DockerError, TooLarge
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

MIN_SECRET = 32
log = logging.getLogger("workspace-controller")


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    env: dict[str, str] = Field(default_factory=dict)


def build_app(
    docker: Docker | None = None,
    secret: str | None = None,
    reap_interval: float | None = None,
) -> FastAPI:
    secret = (
        secret if secret is not None else os.getenv("WORKSPACE_CONTROLLER_SECRET", "")
    )
    if len(secret) < MIN_SECRET or len(set(secret)) < 12:
        raise RuntimeError(
            "WORKSPACE_CONTROLLER_SECRET must be a random secret of at least 32 characters"
        )
    if reap_interval is None and docker is None:  # a real controller sweeps by default
        reap_interval = float(os.getenv("WORKSPACE_REAP_SECONDS", "60"))
    docker = docker or Docker(
        Config(
            image=os.environ["WORKSPACE_IMAGE"],
            egress_image=os.environ["WORKSPACE_EGRESS_IMAGE"],
            memory=os.getenv("WORKSPACE_MEMORY", "4g"),
            cpus=os.getenv("WORKSPACE_CPUS", "2"),
            public_base_url=os.getenv("FABAGENT_BASE_URL", ""),
        )
    )
    if reap_interval and reap_interval > 0:

        def reaper():
            while True:
                try:
                    n = docker.reap_helpers()
                    if n:
                        log.warning("removed %d orphaned helper container(s)", n)
                except Exception:  # noqa: BLE001 - a failed sweep must never stop the next
                    log.exception("helper sweep failed")
                time.sleep(reap_interval)

        threading.Thread(target=reaper, name="helper-reaper", daemon=True).start()
    app = FastAPI(
        title="workspace-controller", docs_url=None, redoc_url=None, openapi_url=None
    )

    def auth(x_controller_secret: str | None = Header(None)) -> None:
        if not x_controller_secret or not hmac.compare_digest(
            x_controller_secret.encode(), secret.encode()
        ):
            raise HTTPException(status_code=401, detail="unauthorized")

    def guarded(fn):
        try:
            return fn()
        except BadInput as e:
            raise HTTPException(status_code=422, detail=str(e))
        except TooLarge:
            raise HTTPException(status_code=413, detail="too large")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="not found")
        except DockerError as e:
            # a stable, secret-free message; Docker's own text stays in the controller log
            log.warning("docker error: %s | %s", e.public, e.detail)
            raise HTTPException(status_code=502, detail=e.public)

    transfers = threading.BoundedSemaphore(
        int(os.getenv("WORKSPACE_MAX_TRANSFERS", "4"))
    )

    def hold_slot():
        if not transfers.acquire(timeout=30):
            raise HTTPException(status_code=503, detail="busy")

    def transfer(fn):
        """At most a few file transfers at once: each can hold up to the size cap."""
        if not transfers.acquire(timeout=30):
            raise HTTPException(status_code=503, detail="busy")
        try:
            return fn()
        finally:
            transfers.release()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/v1/workspaces/{wid}", dependencies=[Depends(auth)])
    def create(wid: str, body: CreateBody):
        guarded(lambda: docker.create(wid, body.env))
        return {"status": docker.status(wid)}

    @app.post("/v1/workspaces/{wid}/restore", dependencies=[Depends(auth)])
    def restore(wid: str, body: CreateBody):
        guarded(lambda: docker.restore(wid, body.env))
        return {"status": docker.status(wid)}

    @app.post("/v1/workspaces/{wid}/start", dependencies=[Depends(auth)])
    def start(wid: str, body: CreateBody | None = None):
        # With an env the container is recreated on its volumes so the persona token
        # is fresh (files and home are kept; the tmux session starts anew).
        if body is not None and body.env:
            guarded(lambda: docker.recreate(wid, body.env))
        else:
            guarded(lambda: docker.start(wid))
        return {"ok": True}

    for verb in ("stop", "remove", "purge"):

        def make(verb=verb):
            def handler(wid: str):
                fn = {
                    "stop": docker.stop,
                    "remove": docker.remove,
                    "purge": docker.purge_volume,
                }[verb]
                guarded(lambda: fn(wid))
                return {"ok": True}

            return handler

        app.post(f"/v1/workspaces/{{wid}}/{verb}", dependencies=[Depends(auth)])(make())

    @app.get("/v1/workspaces/{wid}/status", dependencies=[Depends(auth)])
    def status(wid: str):
        return {"status": guarded(lambda: docker.status(wid))}

    @app.get("/v1/workspaces/{wid}/files", dependencies=[Depends(auth)])
    def files(wid: str, area: str = "out"):
        return {
            "files": transfer(lambda: guarded(lambda: docker.list_files(wid, area)))
        }

    @app.get("/v1/workspaces/{wid}/file", dependencies=[Depends(auth)])
    def read(wid: str, path: str):
        # The slot is kept until the bytes have been sent, so buffered downloads are
        # bounded by the number of slots, not by how slowly clients read.
        hold_slot()
        try:
            data = guarded(lambda: docker.read_file(wid, path))
        except BaseException:
            transfers.release()
            raise
        return Response(
            content=data,
            media_type="application/octet-stream",
            background=BackgroundTask(transfers.release),
        )

    @app.put("/v1/workspaces/{wid}/file", dependencies=[Depends(auth)])
    async def write(wid: str, path: str, request: Request):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="too large")
        from starlette.concurrency import run_in_threadpool

        # The slot is taken before the body is read, so the number of bodies held in
        # memory is bounded by the number of slots, not by the number of callers.
        if not await run_in_threadpool(lambda: transfers.acquire(timeout=30)):
            raise HTTPException(status_code=503, detail="busy")
        try:
            chunks, size = [], 0
            async for chunk in request.stream():  # bounded while it is read
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail="too large")
                chunks.append(chunk)
            data = b"".join(chunks)
            await run_in_threadpool(
                lambda: guarded(lambda: docker.write_file(wid, path, data))
            )
        finally:
            transfers.release()
        return {"ok": True, "size": len(data)}

    return app
