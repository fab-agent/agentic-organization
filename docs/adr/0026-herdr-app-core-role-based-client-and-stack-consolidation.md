# ADR-0026: Herdr app/core as the role-based client; consolidating the stack into three installable deliverables

- **Status:** proposed (revised 2026-11-01 after Codex review `CODEX-ADR0026`)
- **Date:** 2026-10-31
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0001, ADR-0004, ADR-0005, ADR-0006, ADR-0008, ADR-0014, ADR-0016, ADR-0022, `docs/architecture/herdr-plugin-spec.md`

## Context and problem

The platform has grown overlapping pieces: the Python backend with its own harness
(`services/harness.py`), the opencode workstation client (ADR-0001), a frozen Go TUI
(`packages/tui`), the `3pa` CLI, the SvelteKit frontend, the workspace controller,
and a herdr plugin specification (ADR-0022 §6). A company that only wants
*accountable AI use* (who does what, under whose responsibility, with what quality
evidence) has to understand all of them.

What the herdr repositories say (read 2026-10-31; no runtime test yet):

- **herdr-core** (`hc`) runs terminals and agents, keeps them alive, reaches other
  machines over SSH, and draws nothing. **herdr-app** is the desktop window. Both are
  Apache-2.0. The app runs on macOS (Apple Silicon), Linux (x64, ARM64; needs a desktop
  session and Vulkan) and Windows (x64), and installs the core if missing.
  After a reboot or core crash, panes get fresh shells, not their old programs.
- **Layouts** (JSON tree arranging the window) and **mods** (JavaScript drawing panels,
  menus, dialogs) live in a per-user app home and reload on save. Shipped files update
  on start; personal copies do not.
- `fetch` is a documented global with unrestricted network access
  (`defaults/AGENTS.md:928-930`). Async re-rendering is documented
  (`cx.spawn` + `cx.notify()`). Request headers, response-body streaming (SSE),
  cancellation and backpressure are **not** documented.

Limits (`docs/security.md`) that shape the design:

- Mods are trusted, unsandboxed code with the user's access; no permission model.
- Update manifests carry a checksum from the same service, not an independent
  signature; platform package signing (Apple Developer ID, Azure) is conditional.
  Nothing documented signs layouts or mods.
- `HERDR_APP_HOME` can point the app at a managed home, but that does not stop the
  same user from starting another instance or adding mods. There is no managed-only mode.
- Telemetry is on by default in release builds; the app home is unencrypted; app and
  core update separately; a local control socket sits in the app home.

## Findings about our own backend (these gate acceptance)

From the review, verified against code:

- `services/agent_runtime.py` (~517-542) swallows policy import/wiring/decision errors
  and **continues to execute the tool**; `policy_engine.py` (~691-716) writes audit
  best-effort. "Every action is enforced and audited server-side" is therefore **not
  true today**. `/api/.../gateway.py` returns a decision for workstation tools and
  leaves blocking to the plugin; backend chat paths call provider SDKs directly, not
  through `/v1`.
- The CLI re-pins a rotated signing key when the server supplies a matching
  `previous_key_id` (`packages/cli/src/utils/wellknown.ts`), which a response-modifying
  attacker can forge; first contact is trust-on-first-use.

## Decision

1. **Herdr app + core is the daily interface and runtime.** Power users get the stock
   terminal layout; non-developers get a role layout (chat, inbox/approvals, a small
   dashboard). Until the chat/isolation spike passes, the **web fallback
   (`assistant_user`, ADR-0022 §7) stays the primary path for non-developers**.
2. **Enforcement becomes a prerequisite, not an assumption.** Before this ADR can be
   accepted: (a) policy infrastructure errors **fail closed**; (b) a side-effecting
   action requires a durable audit record first (or a transactional outbox); (c) backend
   model calls go through the shared limit/audit layer; (d) negative tests: client
   omits policy/event reports, MCP policy failure, audit outage, revoked persona,
   wrong tenant/role. Out of scope and stated plainly: what a user does locally on
   their own OS or with their own API keys is not preventable by Herdr or the server;
   that needs OS/egress policy.
3. **Signed workspace manifest** (`GET /me/workspace`) with a protocol we design, not
   the `wellknown` re-pin flow. Signed envelope fields: purpose, schema, issuer, company,
   person, audience, key id, `issued_at`, `expires_at`, monotonic generation, minimum
   client/runtime version, and SHA-256 of the layout **and every file of every mod**.
   The Ed25519 primitive of `wellknown_sign.py` may be reused; trust root is distributed
   by installer/MDM; key rotation is signed by the previous trusted key with a bounded
   overlap; offline root plus a separate workspace signing key is the target; the `.prev`
   private-key file is removed or time-boxed. The client keeps the last accepted
   generation and rejects older ones. Canonical JSON test vectors are shared across
   Python and TypeScript. Archive extraction rejects traversal and symlinks and
   activates atomically.
4. **A thin provisioner (`3pa`) applies the manifest** to a managed app home chosen by
   the launcher/MDM environment, writes `telemetry: false` **before first launch**, and
   reports **drift as a diagnostic signal, not attestation**: all hashes of known
   packages, layout/key/program references, and missing heartbeat. A same-user report is
   not device proof; stronger guarantees need OS-level application control.
5. **Non-developer credential is narrow.** Department mode uses the person-scoped
   assistant API (ADR-0022 §7) or an equivalent narrow token, never persona/developer
   credentials. Manifest fields are not an authority; the server re-checks person,
   tenant and role on every object, download, reconnect and approval. Tokens are not
   stored in mod files or shared state.
6. **SvelteKit** keeps administration, sign-in, evidence viewer, and the fallback
   assistant route. **opencode** is an optional adapter for engineering roles.
   `packages/tui` is removed only after ADR-0022 §6 conditions pass.
7. **Version pinning means installer, updater, core and mod-API compatibility together.**
   Define the approved update channel and verify (not assume) whether auto-update can be
   disabled upstream before shipping signed mods.
8. **Three deliverables** (packaging goals, *after* the gates above): server installer,
   monitoring, user installers. "Monitoring" here **combines existing views** (health,
   gateway usage, audit-chain verification, eval/failure attribution, drift) into one
   screen; it is not the new observability product ADR-0022 §11 excluded.

## Relationship to ADR-0022

Until this ADR is accepted nothing is superseded. On acceptance it **partly supersedes**
ADR-0022 §6 (upstream and integration choice) and §7 (primary client for departments).
It **keeps** §6's security gates (pinned version, licence, permission list, no
gateway/policy/audit bypass, person isolation, token revoke, signed-command checks), §7's
least-disclosure, personal-rights and status-filtering rules, and §8's file-transfer rules.

## Options considered

- **A. Keep opencode + SvelteKit primary.** Binds non-developers to a developer tool and
  keeps two UI stacks. Rejected.
- **B. Own desktop client.** Large long-lived effort herdr mostly covers. Revisit if the
  spike fails.
- **C. Herdr app/core with backend-defined layouts (chosen),** behind the gates above.

## Order of work (from the review)

1. Backend fail-closed and personal authority boundary (decision 2, 5).
2. Trust root, rotation, replay protection, update chain (decision 3, 7).
3. Spike: Authorization-header POST, SSE first-token latency, UTF-8 chunk boundaries,
   cancellation, reconnect/revoke, long markdown scroll; `herdr-app check` covers only the
   first render, so headless CI is verified separately.
4. OS installers, signing and MDM (decision 8).
5. Monitoring merge and TUI removal.

## Consequences

- Acceptance requires the gates in decision 2, a shipped manifest protocol with negative
  tests (forged `previous_key_id`, replay of an old manifest, tampered mod file), and the
  spike results. Until then the status stays *proposed*.
- Installer matrix must list Linux desktop/Vulkan, Windows curl/tar and minimum OS
  versions, third-party notices, and the pinned app+core pair.

## Progress (2026-11-01)

Decision 2 (enforcement prerequisite) is partly implemented on branch
`fix/policy-fail-closed`, reviewed over seven Codex rounds (`CODEX-ADR0026`,
`CODEX-FAILCLOSED` 1-7, last verdict GO):

- one gate (`agent_runtime.policy_gate`) for backend tool calls, flow tools, MCP
  `org_policies` and `/policy/decide`; an engine error, an unreadable policy, an
  unknown persona or a failed audit write each deny, in every mode except `off`;
- strict policy-block contract (`docs/architecture/policy-block-contract.md`),
  refused at save time, fail-closed at runtime, `scripts/policy_inventory.py` for rollout;
- `PolicyResolutionError` maps to `503 policy_unavailable`.

Still open for acceptance of this ADR (each was kept out of scope on purpose):
heartbeat "alive" vs "policy ready" (`api/workstation.py`); policy change requests are
validated but not applied to the Policy table; backend chat paths that call provider
SDKs outside the shared gateway layer; the signed-manifest protocol (decision 3),
non-developer credential (decision 5), update chain (decision 7), and the chat/SSE
spike. Upgrade note: a stored policy that no longer parses, or an audit chain that
cannot be written, now blocks tool calls - run `policy_inventory.py` before upgrading.
