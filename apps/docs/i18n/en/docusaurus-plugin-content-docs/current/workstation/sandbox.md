---
sidebar_position: 7
---

# Isolated Execution Environment (Sandbox)

> ADR-0002 · `sandbox/` (`Dockerfile`, `compose.yaml`, `entrypoint.sh`,
> `run.sh`, `egress/`)

opencode does not run **directly** on the workstation but inside a mandatory local sandbox container. The agent's blast radius is this container: file access is limited to the mounted project directory, network access to a single filtering proxy.

---

## Network topology

```
  sandbox container             egress container
  ┌───────────────┐   internal  ┌──────────────┐  external
  │  opencode     │────network─►│  tinyproxy   │──────────► internet
  │  (no route    │             │  allowlist   │            (only allowed
  │   to internet)│             └──────────────┘             hosts)
  └───────────────┘
```

- `sandbox` is on an `internal: true` Docker network: it has **no route** to the internet.
- The only exit is `egress`: it rejects everything except `egress/base-allowlist.txt` + `$EGRESS_ALLOWLIST` + the gateway host in `$FABAGENT_BASE_URL`.
- The `HTTP(S)_PROXY` environment variables are set; **but** even if a tool ignores them, it cannot reach anywhere because the network has no other route.

The `egress` proxy runs with `tinyproxy`: `FilterDefaultDeny On` + an extended regex allowlist (`FilterExtended On`).

---

## Isolation hardening

The `sandbox` service in `compose.yaml`:

| Setting | Value | Why |
|---|---|---|
| `cap_drop` | `ALL` | No Linux capabilities |
| `security_opt` | `no-new-privileges:true` | No privilege escalation with setuid |
| `pids_limit` | `512` | Fork bomb limit |
| `mem_limit` | `2g` | Memory ceiling |
| `cpus` | `2.0` | CPU ceiling |
| `volumes` | `${PROJECT_DIR}:/work` | Only the project directory is visible |

Before opencode starts, `entrypoint.sh` **clears** all `OPENCODE_*` environment variables, so a caller cannot override the [managed configuration](./managed-config.md) or permission settings by injecting environment variables.

---

## Container contents

| Path | Content |
|---|---|
| `/opt/agent-plugin/src/index.ts` | The opencode plugin: policy + audit hooks |
| `/etc/opencode/opencode.json` | Managed configuration (gateway provider, permissions) |
| `/etc/opencode/base-prompt.md` | Permanent guardrail system directives |
| `/work` | The mounted project directory |

The model is preconfigured: `OPENCODE_MODEL=${FABAGENT_MODEL:-fabagent/qwen-turbo}`, provider `fabagent` → `{FABAGENT_BASE_URL}/v1`, apiKey `{FABAGENT_TOKEN}`.

---

## Running

Normally `3pa run` orchestrates it. Directly:

```bash
FABAGENT_BASE_URL=https://agent.example.com \
FABAGENT_TOKEN=<persona token> \
PROJECT_DIR=~/code/my-project \
docker compose -f sandbox/compose.yaml run --rm sandbox
```

---

## Open items

- A read-only root file system.
- Lightweight VM isolation for macOS (instead of a container).
