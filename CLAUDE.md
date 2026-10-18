# CLAUDE.md — agentic-organization

Read `docs/adr/` before changing architecture; `CONTRIBUTING.md` for checks.
- Decisions need an ADR. Accepted ADRs are never edited, only superseded.
- Every security/behaviour claim in docs must be verified against code.
- Authorisation changes need negative tests (wrong company, wrong role, same person twice).
- Never commit secrets, customer names or real company data (`.env.example` only).
- Customer-facing or outward actions (email, messages, publishing) need user confirmation.
- Backend: `cd backend && .venv/bin/pytest tests/ -q`; `ruff check` and `ruff format --check`. Frontend: `npm run check`.
- Short focused branches from `main`; delete them after merge.
- Licence is Commons Clause + MIT (see `LICENSE`); do not add dependencies that conflict with it.
