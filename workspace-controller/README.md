# workspace-controller

The only component with container-runtime access (ADR-0018 §1). The backend calls it
over a management network through `ControllerRuntime` (`WORKSPACE_RUNTIME=controller`,
`WORKSPACE_CONTROLLER_URL`, `WORKSPACE_CONTROLLER_SECRET`, `WORKSPACE_PUBLIC_BASE_URL`);
it has no user-facing endpoints.

## What it enforces

- every privileged call carries `X-Controller-Secret` (a random secret, ≥ 32 characters
  with real variety, or it will not start); `GET /health` is the only unauthenticated
  route and returns liveness only. The secret is a bearer secret, not a signed request:
  keep the channel private (TLS or an isolated network) and rotate it;
- ids are UUIDs; container, volume and network names are derived from them, never taken
  from input; the image comes from the controller's own environment, never a request;
- the agent environment is an allowlist (`FABAGENT_BASE_URL`, `FABAGENT_TOKEN`,
  `OPENCODE_MODEL`), values without NUL/CR/LF; values reach Docker through the child's
  environment, not argv (they are still visible in `docker inspect` to Docker admins and to
  the agent itself);
- each workspace gets **its own internal-only network**; the shared egress proxy
  (`fab-ws-egress`, `sandbox/egress`) is attached to each of them and sits on a separate
  external network. Workspaces cannot reach each other, the host or the controller
  (verified on real Docker). The controller and backend must stay off these networks;
- containers run with `--cap-drop ALL`, `no-new-privileges`, memory/CPU/pid limits and the
  image's non-root user (uid 10001);
- files: only `in/` (upload) and `out/` (list, download). They are handled by a throw-away
  **helper container** (`fileio.py`: workspace image, `--network none`, the agent's uid,
  read-only root, the volume mounted `:ro` for reads): every path component is opened with
  `O_NOFOLLOW` relative to its parent, so a link anywhere on the path (even a replaced
  `out/` directory) is refused; only regular files; a 100 MB cap per file; at most four
  transfers at a time; uploads are written to a temp name and renamed. Docker's error text
  is logged, never returned;
- lifecycle calls for one workspace are serialised; restore never recreates a purged
  volume; purge needs the container gone first; the proxy and the external network are
  verified (label, image, internal flag) and replaced if they are not what is expected.

## Not enforced here (deployment responsibilities)

- **Disk quotas** on volumes and the root filesystem (a workspace can fill the host disk);
- a **body-aware Docker policy**: a verb-only socket proxy cannot tell a privileged
  `run` from a safe one. Put the controller on a host/user whose Docker is rootless or
  filtered by a policy that checks the create body;
- the controller's own network exposure and a host firewall;
- DLP on the allowlisted egress hosts (the proxy filters by host, not by content).

## Run

```sh
docker build -f sandbox/workspace/Dockerfile -t fab-workspace .
docker build -t fab-egress sandbox/egress
WORKSPACE_CONTROLLER_SECRET=$(python3 -c "import secrets;print(secrets.token_urlsafe(32))") \
WORKSPACE_IMAGE=fab-workspace WORKSPACE_EGRESS_IMAGE=fab-egress \
FABAGENT_BASE_URL=https://agents.example.com \
  uvicorn --factory app:build_app --port 8090      # from this directory
```

## Tests

`pytest workspace-controller/tests` (fake Docker runner and helper), and the opt-in live
test `backend/tests/test_workspace_controller_live.py` against a real Docker.
