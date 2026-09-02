#!/bin/sh
# Render the allowlist into a tinyproxy filter file, then run tinyproxy in the
# foreground. See sandbox/egress/README.md (ADR-0002 / ADR-0010).
set -eu

mkdir -p /etc/tinyproxy
/usr/local/bin/render-filter.sh /etc/egress/base-allowlist.txt > /etc/tinyproxy/filter

if [ ! -s /etc/tinyproxy/filter ]; then
  echo "egress: refusing to start with an empty allowlist" >&2
  exit 1
fi

echo "egress: allowlist (FilterDefaultDeny — everything else is blocked):" >&2
sed 's/^/  /' /etc/tinyproxy/filter >&2

exec tinyproxy -d -c /etc/tinyproxy/tinyproxy.conf
