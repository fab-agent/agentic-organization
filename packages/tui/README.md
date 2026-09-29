# packages/tui — `fab`, the terminal workspace client

Rust + Ratatui client for the department workspace (ADR-0014). Status: early
skeleton — sign-in, org sidebar, a **local** PTY agent pane, and local-folder sync.
The agent pane will attach to the server-side workspace once the controller and
attach endpoint exist (ADR-0018).

```sh
cargo build --release          # binary: target/release/fab
fab login                      # platform URL, email, password
fab                            # open the workspace
fab workspace                  # create / resume your server-side workspace, show its state
fab sync                       # sync the local folder once (never creates a workspace)
fab logout
```

Keys: in the agent pane every key goes to the agent; `Ctrl+O` switches to the
sidebar, where `r` refreshes (and syncs now), `v` opens **My review**,
`Enter`/`Tab`/`Ctrl+O` returns to the agent, `q` quits. `Ctrl+C` always quits.

## My review (ADR-0019 §6)

`v` in the sidebar shows the person their *own* work review: totals and per-day
signals for the last 7 / 30 / 90 days (`w` cycles), what is collected, what is never
collected, who can see it, the minimum group size and the retention period. `n` adds
a note (to the selected day, else today; max 1000 characters), `d` deletes the
newest note of the selected day, `r` reloads, `Esc`/`v`/`q` closes. While it is open
it takes every key. If the company has not enabled work review it says so plainly:
nothing is collected about the person. Limitation: the disclosure sentences come
from the server in English; the TUI's own labels are TR/EN.

**Fit ratings** (ADR-0021) appear in the same view when the company has switched rating
on: counts per criterion in the totals (never a score), and per day the rating of each
piece of work with its criterion's question, `live` or `trial`, and its verdict. Trial
ratings are shown only to the person; the view says so. `←`/`→` pick a rating, `c`
contests it with a reason (it then leaves everyone else's view until a department head
resolves it), `u` withdraws a contest. A day with a contested rating is marked `!`.

Environment: `FAB_SESSION_FILE`, `FAB_AGENT_CMD` (default `opencode`, else `$SHELL`),
`FAB_LANG` (`tr`/`en`), `FAB_FOLDER`, `FAB_MAX_DOWNLOAD_MB` (200), `FAB_MAX_UPLOAD_MB` (50).

## First run and the workspace (ADR-0018)

Opening `fab` brings the person's server-side workspace up by itself: none yet →
it is created; suspended → resumed; still starting → checked again every 3 s;
running → files sync. The sidebar shows `Workspace: running / starting… / failed /
unavailable`. A **failed** workspace is not retried on a timer (that would hammer a
broken runtime) — press `r` to retry. `unavailable` means the platform has no
workspace runtime configured yet (HTTP 503). `fab workspace` does the same from the
command line and exits non-zero unless the workspace is running.

The agent pane is still a **local** PTY: it does not attach to the workspace yet
(that needs the controller and the attach endpoint).

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
