# Workstation sandbox image (ADR-0002).
#
# opencode runs INSIDE this container: the project worktree is bind-mounted at
# /work, the host filesystem / SSH keys / cloud credentials are not. Network
# egress is meant to go through an egress-proxy (ADR-0010) — not configured in
# this v0 image, see sandbox/README.md.
#
# Phase 0: roughest form. `sandbox/run.sh` is a stand-in for `3pa run` (ADR-0009).

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

# Managed opencode config. On a host where the user is root this still cannot be
# edited, because it lives inside the image (ADR-0011).
COPY sandbox/managed-settings.json /etc/opencode/managed-settings.json

# Non-root. The agent's blast radius is this user inside this container.
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /work && chown agent:agent /work
USER agent
WORKDIR /work

# FABAGENT_BASE_URL / FABAGENT_TOKEN / model are injected at `docker run` time.
ENTRYPOINT ["opencode"]
