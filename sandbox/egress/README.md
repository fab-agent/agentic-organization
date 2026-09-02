# sandbox/egress/

Filtering forward proxy for the workstation sandbox — ADR-0002 (network) and
ADR-0010 layer 3 (egress allowlist, the main data-exfiltration channel).

## How it works

`sandbox/compose.yaml` runs two containers:

- **`sandbox`** — opencode + the org plugin, on an `internal: true` Docker
  network. It has **no route to the internet**.
- **`egress`** — this image. On both the internal network and a normal external
  one. The sandbox's `HTTPS_PROXY` points at it.

`egress` runs `tinyproxy` with `FilterDefaultDeny Yes`: a request is forwarded
only if the target host matches `/etc/tinyproxy/filter`. HTTPS (`CONNECT`) is
filtered on the target host too. Everything else — and DNS for non-allowlisted
names — is refused. Because the network has no other route, a tool that ignores
`*_PROXY` still cannot reach anything.

## The allowlist

`entrypoint.sh` renders the filter at startup (`render-filter.sh`) from:

| Source | Purpose |
|--------|---------|
| `base-allowlist.txt` (baked in) | GitHub + npm + PyPI defaults |
| `$EGRESS_ALLOWLIST` (comma/space/newline separated) | per-deployment additions; `3pa run` (ADR-0009) will fill this from managed config |
| host of `$FABAGENT_BASE_URL` | the LLM gateway (ADR-0004), added automatically |

Matching is **suffix**: `github.com` allows `github.com` and `*.github.com`, not
`evilgithub.com`. A leading `*.` / `.` is ignored; `#` comments and blank lines
are skipped.

## Test

```sh
python -m pytest sandbox/egress/test_render_filter.py
```

## Not done yet

- Per-company vs per-project allowlist scoping (ADR-0010 open question) — today
  it is one list per `3pa run`.
- Signature verification of the allowlist bundle (ADR-0011).
- Output/response scanning (ADR-0010 layer 6).
