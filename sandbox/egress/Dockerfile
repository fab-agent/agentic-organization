# Egress proxy image for the workstation sandbox (ADR-0002 / ADR-0010 layer 3).
#
# A filtering forward proxy (tinyproxy) with FilterDefaultDeny: the sandbox
# reaches only the hosts in base-allowlist.txt (+ $EGRESS_ALLOWLIST + the LLM
# gateway from $FABAGENT_BASE_URL). Everything else — and DNS for arbitrary
# hosts — is refused.

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tinyproxy-bin ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY base-allowlist.txt /etc/egress/base-allowlist.txt
COPY render-filter.sh /usr/local/bin/render-filter.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/render-filter.sh /usr/local/bin/entrypoint.sh \
    && chown nobody /etc/tinyproxy

USER nobody
EXPOSE 8888
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
