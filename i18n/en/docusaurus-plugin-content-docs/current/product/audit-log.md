---
sidebar_position: 12
---

# Audit Log

Every significant action on the platform is automatically recorded. The Audit Log lets you track who did what and when.

---

## What Gets Recorded?

| Action | Description |
|---|---|
| `create` | New record created (department, personnel, agent, flow, etc.) |
| `update` | Existing record updated |
| `delete` | Record deleted |
| `approve` | Change request or task approved |
| `reject` | Approval rejected |
| `test` | AI provider key tested |
| `sync` | Git sync performed |

---

## Where to View It

**Settings → Audit Log** tab.

- **Filter by entity type**: Department, personnel, agent config, skill, flow, change request, provider key
- **Color-coded actions**: Green (create), red (delete), blue (approve), orange (reject), grey (other)
- Shows the most recent 100 records by default

---

## API

```http
GET /audit
```

| Parameter | Type | Description |
|---|---|---|
| `company_id` | string | Filter by company |
| `entity_type` | string | Filter by entity type |
| `action` | string | Filter by action |
| `user_id` | string | Filter by user |
| `limit` | int | Max records (default: 100) |

**Example response:**
```json
[
  {
    "id": "uuid",
    "action": "create",
    "entity_type": "department",
    "entity_id": "uuid",
    "entity_name": "Software Development",
    "company_id": "uuid",
    "user_id": "uuid",
    "details": null,
    "created_at": "2026-06-19T10:00:00"
  }
]
```

---

## Data Model

The `AuditLog` table stores per entry:

- **action** — type of action performed
- **entity_type** — category of affected entity
- **entity_id / entity_name** — which record was affected
- **company_id** — which company context
- **user_id** — who performed the action
- **details_json** — additional context (before/after values)
- **created_at** — timestamp

Audit log entries are **immutable** — there is no delete or update endpoint.
