# Department workspace image (ADR-0014, ADR-0018).
#
# One long-lived container per person on the server side. The agent (opencode +
# the org plugin) runs inside a tmux session so a dropped client connection only
# detaches; the `fab` client attaches with `docker exec -it <ctr> workspace-attach`
# (done by the workspace-controller, never by the backend directly).
#
# Same hardening intent as sandbox/Dockerfile (ADR-0002): non-root, no host
# mounts, managed config baked in — plus the work toolchain for non-developers:
# LibreOffice (headless), a PDF toolkit, headless Chromium, and optionally
# Docling. Build from the REPO ROOT:
#
#   docker build -f sandbox/workspace/Dockerfile -t fab-workspace .
#   docker build -f sandbox/workspace/Dockerfile --build-arg WITH_DOCLING=1 -t fab-workspace:docling .

FROM node:22-bookworm-slim

# Keep in step with sandbox/Dockerfile (ADR-0012).
ARG OPENCODE_VERSION=1.18.26
# Docling pulls PyTorch and OCR models (multi-GB), so it is opt-in. Without it the
# agent still converts documents with LibreOffice / poppler; ADR-0015's ingest
# worker runs Docling server-side.
ARG WITH_DOCLING=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates ripgrep less procps tini tmux \
        libreoffice-writer libreoffice-calc libreoffice-impress \
        poppler-utils qpdf \
        chromium \
        fonts-noto-core fonts-noto-color-emoji fonts-liberation fonts-dejavu-core \
        python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "opencode-ai@${OPENCODE_VERSION}" \
    && npm cache clean --force

# Optional Docling in its own venv (CPU-only PyTorch).
RUN if [ "${WITH_DOCLING}" = "1" ]; then \
        python3 -m venv /opt/docling \
        && /opt/docling/bin/pip install --no-cache-dir \
            --extra-index-url https://download.pytorch.org/whl/cpu docling \
        && ln -s /opt/docling/bin/docling /usr/local/bin/docling; \
    fi

# Org plugin + managed opencode config (same files the sandbox uses).
COPY packages/agent-plugin /opt/agent-plugin
RUN cd /opt/agent-plugin && npm install --omit=dev --no-audit --no-fund
COPY sandbox/opencode.json /etc/opencode/opencode.json
COPY sandbox/base-prompt.md /etc/opencode/base-prompt.md

COPY sandbox/workspace/entrypoint.sh /usr/local/bin/workspace-entrypoint.sh
COPY sandbox/workspace/attach.sh /usr/local/bin/workspace-attach
COPY sandbox/workspace/session-start.sh /usr/local/bin/workspace-session-start
COPY sandbox/workspace/chrome-headless.sh /usr/local/bin/chrome-headless
RUN chmod +x /usr/local/bin/workspace-entrypoint.sh \
        /usr/local/bin/workspace-attach /usr/local/bin/workspace-session-start \
        /usr/local/bin/chrome-headless

# Non-root. /home/agent is a per-person volume; /workspace/in and /workspace/out
# are the upload / download areas the lifecycle API exposes (ADR-0018).
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /workspace/in /workspace/out \
    && chown -R agent:agent /workspace
USER agent
WORKDIR /workspace
ENV HOME=/home/agent \
    LANG=C.UTF-8 \
    TERM=xterm-256color \
    CHROME_BIN=/usr/local/bin/chrome-headless

# tini reaps the zombies that LibreOffice / Chromium leave behind.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/workspace-entrypoint.sh"]
