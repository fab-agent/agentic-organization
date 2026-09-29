# packages/tui — `fab`, the terminal workspace client

Rust + Ratatui client for the department workspace (ADR-0014). Status: early
skeleton — sign-in, org sidebar, a **local** PTY agent pane, and local-folder sync.
The agent pane will attach to the server-side workspace once the controller and
attach endpoint exist (ADR-0018).

```sh
cargo build --release          # binary: target/release/fab
fab login                      # platform URL, email, password
fab                            # open the workspace
fab sync                       # sync the local folder once
fab logout
```

Keys: in the agent pane every key goes to the agent; `Ctrl+O` switches to the
sidebar, where `r` refreshes (and syncs now), `Enter`/`Tab`/`Ctrl+O` returns to the
agent, `q` quits.

Environment: `FAB_SESSION_FILE`, `FAB_AGENT_CMD` (default `opencode`, else `$SHELL`),
`FAB_LANG` (`tr`/`en`), `FAB_FOLDER`, `FAB_MAX_DOWNLOAD_MB` (200), `FAB_MAX_UPLOAD_MB` (50).

## Local workspace folder (ADR-0019 §8)

`FAB_FOLDER` (default `~/Fabrika` — a placeholder; the location is an open question
in ADR-0019) mirrors the workspace's `out/`: what the agent produced (documents,
tables, report summaries, `summaries/…` session notes). `<folder>/in/` is the upload
area. The TUI syncs in the background every 30 s; `fab sync` does one pass.

- **Outputs are one-way** (server → laptop). A file you edited locally is never
  overwritten: the server version is saved beside it as `name (server).ext`, the
  files strip shows the conflict, and it stays flagged until you delete or rename
  the copy.
- **The server is not trusted with paths.** Anything that could leave the folder
  (`..`, absolute, backslash, `:`, symlinked components, the reserved `in/` and
  `.fab-sync*` names) is skipped and reported. Downloads are checked against the
  manifest's SHA-256 and written atomically.
- A failed file is retried next pass; later files are not lost.
- Uploads go from `in/` (unchanged files are not re-sent). Deletions are not
  synced in either direction.
- State lives in `<folder>/.fab-sync.json`.

Limitations: files are held in memory while transferring (size caps above); only
the user's first company is used; file names containing `:` or `\` are skipped.

## Tests

```sh
cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
```

End-to-end (real backend + real `fab`; needs the backend's Python dependencies, and
`pyte` for the TUI check):

```sh
cargo build
python tests/e2e_sync.py
```

`ci/` is gone: the CI workflow is `.github/workflows/tui.yml`.
