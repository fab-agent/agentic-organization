//! `fab` — terminal workspace client (ADR-0014).
//!
//! Skeleton scope (ADR-0014 follow-up 3): login, org sidebar from existing
//! APIs, one placeholder agent pane. The agent pane will attach to the
//! server-side workspace once the lifecycle API exists (follow-up 2).

mod api;
mod app;
mod cron;
mod i18n;
mod model;
mod pty;
mod session;
mod sync;
mod ui;

use anyhow::Result;

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("login") => session::login_interactive(),
        Some("logout") => {
            session::clear()?;
            println!("Signed out.");
            Ok(())
        }
        Some("sync") => cli_sync(),
        Some("-h") | Some("--help") | Some("help") => {
            println!("fab — terminal workspace\n\nUSAGE:\n  fab            open the workspace\n  fab login      sign in to a platform\n  fab logout     forget the stored session\n  fab sync       sync the local workspace folder once (FAB_FOLDER, default ~/Fabrika)");
            Ok(())
        }
        None => app::run(),
        Some(other) => anyhow::bail!("unknown command `{other}` (try `fab help`)"),
    }
}

fn cli_sync() -> Result<()> {
    let Some(sess) = session::load() else {
        anyhow::bail!("not signed in — run `fab login` first");
    };
    let folder = sync::default_folder();
    let client = api::Client::new(sess);
    match sync::sync_workspace(&client, &folder)? {
        sync::Outcome::NoWorkspace => println!("No workspace yet — nothing to sync."),
        sync::Outcome::Synced { report, .. } => {
            println!("Folder: {}", folder.display());
            for p in &report.downloaded {
                println!("  ↓ {p}");
            }
            for p in &report.uploaded {
                println!("  ↑ in/{p}");
            }
            for p in &report.pending_conflicts {
                println!("  ! your edit was kept; the server version is saved as {p}");
            }
            for p in &report.skipped {
                println!("  - skipped {p}");
            }
            for p in &report.errors {
                eprintln!("  ✗ {p}");
            }
            println!(
                "{} downloaded, {} uploaded, {} conflict(s), {} error(s)",
                report.downloaded.len(),
                report.uploaded.len(),
                report.pending_conflicts.len(),
                report.errors.len()
            );
            if !report.errors.is_empty() {
                std::process::exit(1);
            }
        }
    }
    Ok(())
}
