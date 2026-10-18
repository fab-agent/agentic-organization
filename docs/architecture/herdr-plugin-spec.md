# Herdr plugin specification (ADR-0022 §6)

Status: **specification, not built.** It fixes what the plugin may do and what must
be shown before power users are moved off `packages/tui`. The migration conditions of
ADR-0022 §6 are the checklist at the end.

## 1. Stock herdr, pinned

| Item | Value |
|---|---|
| Upstream | `herdrdev/herdr` (stock; a fork only if a patch is unavoidable and recorded in an ADR) |
| Pinned version | `v0.9.5` (tag commit `7573e821895d32c8d1f78b3f6c9a2f85a46df4ac`, released 2026-10-14) |
| Licence at the pin | Apache-2.0 (`LICENSE` read at the tag on 2026-10-18; this closes the question left open by the ADR-0014 spike) |
| Update source | GitHub releases of `herdrdev/herdr` only; no preview tags |
| Update rule | a new version is adopted by a reviewed change that re-runs the acceptance tests below and re-reads `LICENSE` at the new tag |

Herdr runs a plugin as **ordinary code with the user's permissions**: its commands
inherit the environment, can call the whole herdr CLI, and are not sandboxed or
reviewed by herdr. There is no permission model to rely on. The plugin's
permissions are therefore *ours to declare and test* (section 3).

## 2. What the plugin does

The plugin (`fab-agent/agentic-org-herdr`, manifest `herdr-plugin.toml`,
`min_herdr_version = "0.9.5"`) is a thin layer over the existing `3pa` CLI and the
platform APIs; it adds no new server surface.

| Action | Does | Uses |
|---|---|---|
| `login` | sign in and select a persona (OIDC device flow) | `3pa login`, `POST /workstation/persona-token` |
| `agent` | open the agent in a herdr pane with the managed config and gateway env | `3pa run`, `GET /.well-known/opencode` |
| `status` | show policy mode, today's usage, last run diagnosis | `GET /gateway/usage`, `GET /eval/personas/{id}/runs` |
| `context` | show "my context" (read-only) | `GET /assistant/context` |
| `propose` | propose a change from a run (a `harness` change request) | `POST /change-requests` |
| `send-file` | send one explicitly chosen file to the agent | `POST /sessions/{id}/files` |
| `logout` | revoke this laptop's persona tokens | `POST /workstation/persona-token/revoke` |

Chat between people stays in the separate community plugin; this one never reads
or writes it.

## 3. Declared permissions

The plugin may do only what is listed here; each line has a test (section 5).

- **Network:** the configured platform base URL only. No other host, no telemetry.
- **Herdr CLI:** `workspace create|list`, `pane run|read` **for panes it created**,
  `plugin` introspection of itself. No `pane send-text` into panes it did not create;
  no reading other panes; no `integration` changes.
- **Files:** its own plugin state directory (config, token cache, mode 0600, owned by
  the user) and the *Assistant folder* under ADR-0022 §8. Nothing else.
- **Environment passed on:** `FABAGENT_TOKEN` and the gateway URL to the agent process
  it starts; nothing else from its own environment. Tokens are never written to
  logs, panes' scrollback, or shell history.
- **Processes:** `3pa` and the agent runtime it launches. No shell string execution;
  argv arrays only.

## 4. Requirements that come from the platform

1. **No bypass.** The agent always talks to the platform gateway; the plugin refuses
   to start an agent with a different model endpoint or without the managed config.
   Policy decisions and audit events keep flowing from the plugin-started process.
2. **Per-person isolation.** Each person's workspace, token cache and Assistant folder
   are private to their OS user; the plugin checks the owner and mode on every start.
3. **Revocation.** A revoked persona token stops the agent at the next call; `logout`
   revokes server-side, not only locally.
4. **Signed commands.** The plugin verifies the Ed25519 signature of control commands
   (`stop`, `pause`, `refresh`, `message`) against the key served by
   `/.well-known/opencode/pubkey` and ignores unsigned or mismatched ones.
5. **Assistant folder** (ADR-0022 §8): explicit file selection with a transfer preview;
   canonical-path checks that reject symlinks, junctions, reparse points and path
   traversal, re-checked at open time; safe download (no overwrite, no auto-open,
   macro/script files flagged). Nothing syncs automatically in either direction.
6. **Untrusted output.** Anything the plugin prints from a remote source (summaries,
   findings, context text) is escaped for the terminal: no raw control sequences.

## 5. Acceptance tests (all must pass on the pinned version)

| # | Claim | How it is shown |
|---|---|---|
| 1 | No gateway/policy/audit bypass | start the agent via the plugin; make a denied tool call; the platform shows a `policy_decision` and a `gateway_call` for it. Repeat with `OPENAI_BASE_URL` set to another host: the plugin refuses |
| 2 | Per-person workspace isolation | two OS users on one host; user B cannot read user A's token cache or Assistant folder; the plugin exits if the mode or owner is wrong |
| 3 | Token revocation | `revoke` on the server; the running agent's next call fails with 401 within one call |
| 4 | Signed-command verification | a command with a bad signature, an old timestamp and a different persona is ignored; a correct one is applied |
| 5 | Folder safety | symlink, junction/reparse point, `..` segment, and a file swapped between preview and open are all refused; a download never overwrites |
| 6 | No secrets in output | grep pane scrollback, plugin logs and shell history for the token after a full session |
| 7 | CLI surface | the set of `herdr ...` subcommands the plugin invokes equals the list in section 3 (recorded by a test wrapper around `HERDR_BIN_PATH`) |

## 6. ADR-0022 §6 checklist

- [x] herdr version pinned with a defined update source (section 1)
- [x] full-version licence review: Apache-2.0 at the pinned tag (repeat per update)
- [x] plugin permissions listed (section 3)
- [ ] acceptance tests 1-7 implemented and green (not started)
- [ ] plugin repository, release workflow and attestation (follow the community plugin's routine)

## 7. Open questions

- Windows: herdr supports named pipes, but the Assistant-folder checks for reparse
  points need a Windows implementation and test before the plugin is offered there.
- Whether the plugin should use the OS keychain instead of a 0600 file for the token
  cache (cost: a native dependency per platform).
