# ADR-0002: Execution model — laptop + mandatory local sandbox

- **Status:** accepted
- **Date:** 2026-09-01
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0001, ADR-0003, ADR-0010

## Context and problem

**Where** will the agent's tool calls (`bash`, `edit`, `write`, `webfetch`) run?
Two requirements conflict:

1. The experience should feel like the developer running `opencode` on their own
   machine — local repo, local tooling, low latency.
2. Company machines **must not crash or be misused** as a result of an agent bug
   or prompt injection.

opencode has **no** sandbox of its own; it runs commands directly in the user's
shell (SSH keys, cloud credentials, prod access included).

## Options considered

- **A — bare execution on the laptop** (opencode's default). Simplest, but the
  blast radius is the user's entire machine. Rejected.
- **B — per-user container on the server side.** Real isolation and central
  control, but we lose the "opencode on the laptop" experience, and it brings file
  sync/latency issues and serious infrastructure. Rejected for now (it may become
  an optional deployment model later).
- **C — execution on the laptop + a mandatory local sandbox.** opencode runs
  inside a container/VM: repo mounted, network egress allowlisted, no access to
  the host FS and credentials. If there is no sandbox, the agent **does not start**.

## Decision

**C.** Execution stays on the laptop, but the `3pa` wrapper (ADR-0009) starts
opencode inside a managed sandbox:

- **Isolation unit:** one container per project (Linux: Podman/Docker; macOS:
  Podman/Colima VM; compatible with the devcontainer spec).
- **File system:** only the project worktree + named cache volumes are mounted.
  `$HOME`, SSH keys, and cloud credential files are not mounted.
- **Network:** egress through an egress-proxy; only (a) the LLM gateway (ADR-0004),
  (b) approved git remotes, (c) allowlisted package registries and hosts. DNS and
  arbitrary hosts are blocked (ADR-0010).
- **Credentials:** only short-lived, narrowly scoped tokens are injected into the
  sandbox (ADR-0007).
- **Enforcement:** `3pa run` errors out and does not start opencode if the sandbox
  runtime is missing or the policy signature cannot be verified.

## Consequences

- **Positive:** Accidental damage and injection blast radius are bounded by the
  container. The experience is still "local". Devcontainer compatibility opens the
  door to VS Code integration.
- **Negative / cost:** A container runtime must be installed on every workstation.
  On macOS the VM adds RAM/CPU. Some local development flows (host services, USB,
  etc.) hit friction — escape hatches must be granted explicitly via policy.
- **Accepted residual risk:** The container is not `--privileged`, but container
  escapes and misconfigured mounts are possible. A determined user can bypass
  `3pa` and run opencode by hand — ADR-0003 addresses this.
- **Follow-ups:** `sandbox/` image + egress-proxy config; a `fabctl.yml` CI smoke
  test for "the sandbox comes up, egress is blocked, it does not start outside the
  sandbox".
