---
sidebar_position: 5
---

# Persona Identity and Tokens

> ADR-0007 · `backend/api/workstation.py`, `backend/services/persona_revocation.py`,
> `backend/api/deps.py`, `backend/services/oidc.py`

While a developer persona works on the workstation, it connects to the platform with a **short-lived** identity. No long-lived API key is kept on the workstation; if one leaks, its effect is limited to minutes and it can be revoked instantly.

---

## Two tokens

| Token | `typ` | Lifetime | Use |
|---|---|---|---|
| Access | `persona` | ~60 min | Gateway and `/workstation/*` calls |
| Refresh | `persona_refresh` (`aud=refresh`) | ~12 h | Getting a new access token |

Both carry a `jti` (unique token id). `3pa login` gets the pair and writes it to `~/.config/3pa/session.json`; `3pa refresh` renews the access token.

---

## Endpoints

| Method | Path | Who |
|---|---|---|
| `GET`  | `/workstation/personas` | Owner: the personas they can manage |
| `POST` | `/workstation/persona-token` | Owner: a token pair for a persona |
| `POST` | `/workstation/persona-token/refresh` | The holder of the refresh token |
| `POST` | `/workstation/persona-token/revoke` | The owner **or** the persona itself |
| `POST` | `/workstation/oidc/exchange` | OIDC ID token → persona token (optional) |

---

## Revocation: fail-closed

On every protected request `api/deps.py` performs a revocation check. The check is **fail-closed**: if the DB cannot be reached the request is rejected.

| Mechanism | What it does |
|---|---|
| `RevokedToken` | A specific `jti` is blacklisted |
| `PersonaTokenState` | A **not-before** mark for the persona: all tokens produced before this moment are invalid (bulk revocation) |

`revoke_jti()` revokes a single token, `revoke_all()` all of a persona's tokens.

---

## Automatic maintenance

The `revocation_maintenance` APScheduler job:

- Automatically revokes the tokens of sessions that have not sent a heartbeat for a long time (**stale**).
- Cleans up `RevokedToken` rows long expired (so the table does not bloat).

---

## OIDC (optional)

`services/oidc.py` converts the ID token of a corporate OIDC provider into a persona token (signature verification with JWKS). It is **off** unless `oidc.enabled`; it **does not automatically create an account** for a user it does not know.

---

## Open items

- Token rotation for runs longer than 60 minutes inside the sandbox.
- Device registration: matching known workstations with a device identity.
