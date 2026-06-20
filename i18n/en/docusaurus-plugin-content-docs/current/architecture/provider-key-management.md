# Provider Key Management (F2)

This page describes the system for securely managing **provider API keys** in the 3rdParty Agent Organization platform.

## Overview

Since the platform works with multiple AI providers (Anthropic, OpenAI, Google, Mistral, etc.), securely storing and managing the API keys for these providers is critically important.

## Architecture

### Components

- **core/security.py**: Fernet (AES)-based encryption and decryption operations.
- **services/provider_service.py**: Testing provider API keys (live calls via httpx).
- **api/providers.py**: Provider key CRUD and test endpoints.

### Data Model

- `ProviderKey` table:
  - `provider` (string, unique)
  - `encrypted_key` (string)
  - `is_active` (boolean)
  - `last_tested` (datetime)
  - `status` (active / invalid)

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/providers/{provider}/key` | Saves and tests the encrypted key |
| GET | `/providers/status` | Real-time status of all providers |
| GET | `/providers/models` | Models from active providers only |
| DELETE | `/providers/{provider}/key` | Delete a key |

## Security

- All API keys are stored encrypted with **Fernet (AES-128)**.
- The encryption key is stored in a `.secret` file (can also be managed via `.env` or an environment variable).
- Keys are never returned in plaintext.

## Usage Flow

1. The user (Admin) adds a provider key.
2. The system encrypts and saves the key.
3. The key is tested (via a real API call).
4. The result is marked as `active` or `invalid`.

## Related Sprint

- **Sprint 2** — F2 (Provider Key Management) was completed as part of this sprint.

---
*Last updated: June 1, 2026*
