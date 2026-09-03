# Workstation sandbox image (ADR-0002).
#
# opencode runs INSIDE this container: the project worktree is bind-mounted at
# /work, the host filesystem / SSH keys / cloud credentials are not.
#
# Network egress: `sandbox/compose.yaml` puts this container on an internal-only
# network with the `egress` proxy as its only way out (ADR-0002 / ADR-0010). The
# bare `sandbox/run.sh` path has no such restriction — use compose for isolation.
#
# Phase 0: roughest form. `sandbox/run.sh` / `compose.yaml` stand in for `3pa
# run` (ADR-0009).

FROM node:22-bookworm-slim

# TODO(ADR-0012): pin opencode. `latest` is a Phase 0 placeholder only.
ARG OPENCODE_VERSION=latest

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates ripgrep less \
    && rm -rf /var/lib/apt/lists/*

# opencode CLI (its own runtime is bundled in the npm package).
RUN npm install -g "opencode-ai@${OPENCODE_VERSION}" \
    && npm cache clean --force

# Org plugin — copied in and referenced by absolute path from the managed config.
COPY packages/agent-plugin /opt/agent-plugin
RUN cd /opt/agent-plugin && npm install --omit=dev --no-audit --no-fund

# Managed opencode config + the org operating rules it injects as instructions
# (ADR-0010). The .json here is a **fallback** — `3pa run` fetches the signed
# `/.well-known/opencode` config, verifies it, and bind-mounts it over this path
# (ADR-0011); the baked copy is only used with `--no-verify` / offline.
# base-prompt.md is always baked (the served config references it by path).
COPY sandbox/opencode.json /etc/opencode/opencode.json
COPY sandbox/base-prompt.md /etc/opencode/base-prompt.md
COPY sandbox/entrypoint.sh /usr/local/bin/sandbox-entrypoint.sh
RUN chmod +x /usr/local/bin/sandbox-entrypoint.sh

# Non-root. The agent's blast radius is this user inside this container.
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /work && chown agent:agent /work
USER agent
WORKDIR /work

# FABAGENT_BASE_URL / FABAGENT_TOKEN / model are injected at `docker run` time.
# The entrypoint scrubs OPENCODE_* overrides before exec'ing opencode (ADR-0002).
ENTRYPOINT ["/usr/local/bin/sandbox-entrypoint.sh"]
