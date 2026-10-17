# Contributing

Thanks for helping. This is a self-hosted platform (FastAPI backend, SvelteKit
frontend, a Rust terminal client and a TypeScript agent plugin). Please read this
page before opening a pull request.

## Ground rules

- **Security issues:** do not open a public issue; follow [SECURITY.md](SECURITY.md).
- **Architecture decisions** are recorded as ADRs in [`docs/adr/`](docs/adr/). A
  change that alters a decision needs a new ADR that supersedes the old one
  (accepted ADRs are not rewritten). The `adr-guard` workflow warns when
  architecture-significant files change without an ADR.
- **No real data.** Never commit secrets, customer names or real company data. Use
  `.env.example` for configuration examples.
- **Docs must match code.** If a document claims a behaviour, the code must do it.

## Setting up

```bash
# backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pytest tests/ -q

# frontend
cd frontend && npm ci && npm run check
```

Other packages (`packages/agent-plugin`, `packages/cli`, `packages/tui`) have their
own README and CI workflow.

## Before you open a pull request

1. Branch from `main`; keep the change focused.
2. Add or update tests. A bug fix starts with a test that fails first. Authorisation
   changes need negative tests (wrong company, wrong role, same person twice).
3. Run the same checks CI runs:
   `ruff check backend/`, `ruff format --check backend/`, `pytest tests/`,
   and `npm run check` for the frontend.
4. Fill in the pull request template, and say how you verified the change.

## Commit messages

Short imperative summary; explain the *why* in the body when it is not obvious.

## Conduct

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Licence

Contributions are accepted under the licence in [LICENSE](LICENSE).
