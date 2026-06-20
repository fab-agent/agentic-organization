---
sidebar_position: 5
---

# Company-Reactive Data Loading

The platform can manage multiple companies. When the user switches the active company, all pages must reload their data relative to that company. This behavior is implemented with a consistent Svelte 5 `$effect` pattern.

---

## Why Are Both Required?

SvelteKit pages load data inside `onMount`. However, `onMount` only runs when the page is first opened; when the user changes the company, `onMount` is not triggered again. For this reason it is used together with `$effect`.

---

## onMount + $effect Pattern

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { companyStore } from '$lib/stores/company.svelte';

  let data = $state([]);

  // Initial load
  onMount(load);

  // Reload on company change
  $effect(() => {
    if (companyStore.active) load();
  });

  async function load() {
    data = await api.list({ company_id: companyStore.active?.id });
  }
</script>
```

`onMount` runs for the initial render, while `$effect` runs every time `companyStore.active` changes. The `company_id` filter is added to the API call so that only data belonging to that company is returned.

---

## Behavior Comparison

| Scenario | `onMount` | `$effect` |
|---|---|---|
| Page first opened | Runs | Runs (companyStore already set) |
| Company changed | Does not run | Runs |
| Company changed while page is already open | Does not run | Runs |

If only `$effect` were used, `companyStore.active` might not yet be loaded during SSR. If only `onMount` were used, company changes would not be captured. Together they cover all scenarios.

:::note $effect and reactivity
The Svelte 5 rune system tracks changes to any `$state` variable read inside a `$effect` block. Since `companyStore.active` is a `$state` object, the effect re-runs the moment it changes.
:::

---

## Pages Using This Pattern

| Page | Route | Data Loaded |
|---|---|---|
| Structure | `/` | Department + personnel summary |
| Departments | `/departments` | Department list |
| People | `/personnel` | Personnel list |
| Agents | `/agents` | Agent list |
| Org Chart | `/org-chart` | Hierarchical tree data |
| Jobs | `/chat` | Sessions + agent list |
| Delegation | `/a2a` | A2A request list |

The sidebar component also uses the same pattern for the pending delegation count.

---

## Sidebar: Pending Counter

The sidebar (`+layout.svelte`) tracks the delegation count as follows:

```svelte
let pendingCount = $state(0);

onMount(loadPendingCount);

$effect(() => {
  if (companyStore.active) loadPendingCount();
});

async function loadPendingCount() {
  const { count } = await a2aApi.pendingCount({
    company_id: companyStore.active?.id
  });
  pendingCount = count;
}
```

When `pendingCount > 0`:
- An amber badge appears next to the **Delegation** item in the menu
- An amber pulse dot appears on the company card

---

## API Filter: company_id

All list endpoints support the `company_id` query parameter. If the parameter is not specified, data for all companies is returned (for development/testing purposes):

```bash
GET /personnel?company_id=<uuid>&type=agent
GET /departments?company_id=<uuid>
GET /sessions?personnel_id=<uuid>
GET /a2a/requests?company_id=<uuid>
GET /a2a/requests/pending-count?company_id=<uuid>
```

---

## When Writing a New Page

When adding a new page to the platform, use the following template:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { companyStore } from '$lib/stores/company.svelte';
  import { myApi } from '$lib/api/my-module';

  let items = $state([]);
  let loading = $state(true);

  onMount(load);
  $effect(() => { if (companyStore.active) load(); });

  async function load() {
    loading = true;
    try {
      items = await myApi.list({ company_id: companyStore.active?.id });
    } finally {
      loading = false;
    }
  }
</script>
```

No page requires a manual `window.location.reload()` or page redirect after a company change.

---

## Related Docs

- [3rdParty Agent Org Architecture](./3rdparty-agent-org.md)
- [Jobs Page](../platform/chat-ui.md)
- [A2A Delegation](../platform/a2a-delegation.md)
