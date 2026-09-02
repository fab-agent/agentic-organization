# @3rdpartyagent/agent-plugin

opencode plugin that connects a developer workstation to the
**agentic-organization** backend.

See [`docs/architecture/agentic-os.md`](../../docs/architecture/agentic-os.md) and
ADR-0001 / ADR-0005 / ADR-0006.

## What it does

| Phase | Behaviour |
|-------|-----------|
| **0** | Observe. Every tool-call lifecycle event (`tool.execute.before` / `.after`, `permission.asked`) is POSTed to `POST /workstation/tool-event` for audit. |
| **1 (now)** | `tool.execute.before` also calls the gateway `POST /policy/decide` (ADR-0005). When the decision is `enforced` and the effect is `deny`/`ask`, the call is aborted (opencode has no "return ask" hook, so an enforced `ask` is a conservative block). Decisions are audited server-side. Rollout is gated by `policy.mode` on the backend — `dry_run` by default, so nothing blocks until an operator flips it to `enforce`. |
| 1 (ADR-0006) | With `FABAGENT_FAIL_CLOSED=1`, an unreachable audit/policy sink aborts the tool call. |

## Configuration (environment)

`3pa run` (ADR-0009) injects these into the sandbox:

| Var | Meaning | Default |
|-----|---------|---------|
| `FABAGENT_BASE_URL` | Backend base URL, e.g. `https://agents.example.com` | — (no-op if unset) |
| `FABAGENT_TOKEN` | Persona bearer token (`aud` includes `audit`) | — (no-op if unset) |
| `FABAGENT_REPORT_TIMEOUT_MS` | Per-report HTTP timeout | `3000` |
| `FABAGENT_FAIL_CLOSED` | `1` → abort tool calls when the sink is unreachable | `0` |
| `FABAGENT_DEBUG` | `1` → one stderr line per reported event | `0` |

If `FABAGENT_BASE_URL` / `FABAGENT_TOKEN` are missing the plugin loads in no-op
mode (a single stderr warning) so it is safe outside a managed workstation.

## opencode config

```jsonc
// managed-settings.json (written inside the sandbox image, ADR-0011)
{
  "plugin": ["@3rdpartyagent/agent-plugin"],
  "provider": {
    "fabagent": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "{env:FABAGENT_BASE_URL}/v1",
        "apiKey": "{env:FABAGENT_TOKEN}"
      }
    }
  }
}
```

## Develop

```sh
npm install
npm run typecheck
npm test          # node --test, no external test framework
```

Requires Node ≥ 22.6 (uses `--experimental-strip-types` to run the TS tests
directly). The plugin itself is plain ESM TypeScript loaded by opencode's Bun
runtime in production.
