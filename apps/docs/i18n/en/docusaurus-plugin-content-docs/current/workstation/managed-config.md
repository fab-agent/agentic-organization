---
sidebar_position: 9
---

# Managed opencode Configuration

> ADR-0011 · `backend/api/well_known.py`, `backend/services/wellknown_sign.py`,
> `sandbox/opencode.json`

It is the **platform**, not the persona, that determines opencode's behavior (which provider, which plugin, which permissions). This configuration is served signed and sits **above** user settings inside the sandbox.

---

## Distribution channel

| Endpoint | Description |
|---|---|
| `GET /.well-known/opencode` | The signed managed configuration (JSON + signature) |
| `GET /.well-known/opencode/pubkey` | The Ed25519 public key for verification (+ `previous_key_id`) |

`3pa run` fetches the configuration, verifies the signature against the public key and places it in the sandbox container as `/etc/opencode/opencode.json`. On Linux, opencode reads this path as the **managed config** (`managedConfigDir()`), so a project or user `opencode.json` cannot override it.

---

## Signing

`services/wellknown_sign.py`:

- The Ed25519 key pair is in `data/.wellknown_ed25519`.
- Canonical JSON = `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)`: the verifying side must apply exactly the same canonicalization.
- For the raw public key the SPKI prefix is `302a300506032b6570032100`.

### Key rotation

`rotate_key()` generates a new pair; the old key's id is published as `previous_key_id`, so old signatures can still be verified for a while during the transition.

---

## What is in the configuration

The `sandbox/opencode.json` template:

```json
{
  "plugin": ["/opt/agent-plugin/src/index.ts"],
  "instructions": ["/etc/opencode/base-prompt.md"],
  "share": "disabled",
  "provider": {
    "fabagent": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "{env:FABAGENT_BASE_URL}/v1",
        "apiKey": "{env:FABAGENT_TOKEN}"
      }
    }
  },
  "permission": {
    "webfetch": "ask",
    "bash": { "git *": "allow", "npm *": "allow", "rm *": "ask", "*": "ask" }
  }
}
```

- `plugin`: the policy + audit hooks are loaded mandatorily.
- `instructions`: the guardrail prompt (injection defense layer 2).
- `share: disabled`: session sharing is off.
- `permission`: conservative defaults; the policy engine sits on top of this.

Because `entrypoint.sh` clears all `OPENCODE_*` environment variables, these settings cannot be bypassed through the environment. See [Sandbox](./sandbox.md).

---

## Open items

- Hardening of the remaining bypass surfaces such as `OPENCODE_PERMISSION` + a runtime assert in the plugin.
- An operator interface for key rotation.
