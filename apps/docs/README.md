# Docs site

Docusaurus (TR default, EN under `/en`). Part of the `agentic-organization` monorepo; deployed from `apps/docs` on every change to this folder.

```bash
npm ci
npm run start     # dev server
npm run typecheck && npm run build
```

Rules: docs claims must match the code (see `docs/developer-notes/known-limits.md`); in i18n content use relative links.
