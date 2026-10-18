"""workspace-controller: the single component with container-runtime access (ADR-0018 §1).

Run it where Docker is, reach it only from the backend over an internal network, and
put a verb-filtering socket proxy in front of the Docker socket in production. It has
no user-facing endpoints: every call carries the shared secret, every id is a UUID.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from docker_ops import BadInput, Config, Docker, DockerError

MIN_SECRET = 32


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    env: dict[str, str] = Field(default_factory=dict)


def build_app(docker: Docker | None = None, secret: str | None = None) -> FastAPI:
    secret = (
        secret if secret is not None else os.getenv("WORKSPACE_CONTROLLER_SECRET", "")
    )
    if len(secret) < MIN_SECRET:
        raise RuntimeError("WORKSPACE_CONTROLLER_SECRET must be at least 32 characters")
    docker = docker or Docker(
        Config(
            image=os.environ["WORKSPACE_IMAGE"],
            egress_image=os.environ["WORKSPACE_EGRESS_IMAGE"],
            memory=os.getenv("WORKSPACE_MEMORY", "4g"),
            cpus=os.getenv("WORKSPACE_CPUS", "2"),
            public_base_url=os.getenv("FABAGENT_BASE_URL", ""),
        )
    )
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
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="not found")
        except DockerError as e:
            raise HTTPException(status_code=502, detail=str(e)[:200])

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
        return {"files": guarded(lambda: docker.list_files(wid, area))}

    @app.get("/v1/workspaces/{wid}/file", dependencies=[Depends(auth)])
    def read(wid: str, path: str):
        data = guarded(lambda: docker.read_file(wid, path))
        return Response(content=data, media_type="application/octet-stream")

    @app.put("/v1/workspaces/{wid}/file", dependencies=[Depends(auth)])
    async def write(wid: str, path: str, request: Request):
        data = await request.body()
        guarded(lambda: docker.write_file(wid, path, data))
        return {"ok": True, "size": len(data)}

    return app
