# Landing (agent.fab.engineering)

Static page + Cloudflare Worker (`worker.js`, `/api/lead`, D1 binding `DB`). Part of the `agentic-organization` monorepo; deployed from `apps/landing` on every change to this folder (`npx wrangler deploy`).

`.assetsignore` keeps `worker.js`, `schema.sql`, `wrangler.jsonc` and Markdown out of the public assets. Preview and production share one D1 database: mark test rows `TEST ... delete` and remove them.
