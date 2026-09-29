#!/bin/sh
# Headless Chromium for the agent (presentations, PDFs, page rendering).
#
# --no-sandbox: Chromium's own sandbox needs user namespaces / capabilities that
# the workspace container deliberately does not have (cap_drop ALL). The
# container, its non-root user and the egress proxy are the boundary (ADR-0002).
exec chromium --headless=new --no-sandbox --disable-gpu \
    --disable-dev-shm-usage "$@"
