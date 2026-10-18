# workspace-controller

The only component with container-runtime access (ADR-0018 §1). The backend calls it
over an internal network through `ControllerRuntime` (`WORKSPACE_RUNTIME=controller`,
`WORKSPACE_CONTROLLER_URL`, `WORKSPACE_CONTROLLER_SECRET`); it has no user-facing
endpoints.

## What it enforces

- every call carries `X-Controller-Secret` (≥ 32 characters or it will not start);
- ids are UUIDs; container and volume names are derived from them, never taken from input;
- the image comes from the controller's own environment (`WORKSPACE_IMAGE`,
  `WORKSPACE_EGRESS_IMAGE`), never from a request;
- the agent environment is an allowlist (`FABAGENT_BASE_URL`, `FABAGENT_TOKEN`,
  `OPENCODE_MODEL`); values reach Docker through the child's environment, not argv;
- containers run non-root with `--cap-drop ALL`, `no-new-privileges`, memory/CPU/pid
  limits, on an **internal-only** network; the only way out is the filtering egress proxy
  (`fab-ws-egress`, `sandbox/egress`);
- files: only `in/` (upload) and `out/` (list, download); plain path segments; symlinks
  and other non-regular files are never listed or read; transfers use `docker cp` tar
  streams, no shell.

## Run

```sh
docker build -f sandbox/workspace/Dockerfile -t fab-workspace .
docker build -t fab-egress sandbox/egress
WORKSPACE_CONTROLLER_SECRET=<32+ chars> WORKSPACE_IMAGE=fab-workspace \
WORKSPACE_EGRESS_IMAGE=fab-egress FABAGENT_BASE_URL=https://agents.example.com \
  uvicorn --factory app:build_app --port 8090      # from this directory
```

In production put a verb-filtering Docker socket proxy (create / start / stop / rm / cp,
no privileged or host-mount options) between the controller and Docker, and run the
controller on a network only the backend can reach.

## Tests

`pytest workspace-controller/tests` (fake Docker runner), and the opt-in live test
`backend/tests/test_workspace_controller_live.py` against a real Docker.
