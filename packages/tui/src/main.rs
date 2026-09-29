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
mod review;
mod session;
mod sync;
mod ui;
mod workspace;

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
        Some("workspace") => cli_workspace(),
        Some("-h") | Some("--help") | Some("help") => {
            println!("fab — terminal workspace\n\nUSAGE:\n  fab            open the workspace\n  fab login      sign in to a platform\n  fab logout     forget the stored session\n  fab workspace  create / resume your workspace and show its state\n  fab sync       sync the local workspace folder once (FAB_FOLDER, default ~/Fabrika)");
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
    match sync::sync_existing(&client, &folder)? {
        None => println!("No workspace yet — run `fab workspace` (or open `fab`) to create it."),
        Some(report) => {
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

/// `fab workspace`: create / resume the workspace and report its state. Waits a
/// short while if it is still starting.
fn cli_workspace() -> Result<()> {
    use workspace::Status;
    let Some(sess) = session::load() else {
        anyhow::bail!("not signed in — run `fab login` first");
    };
    let client = api::Client::new(sess);
    let me = client.me()?;
    let Some(co) = me.companies.first() else {
        anyhow::bail!("this account belongs to no company");
    };
    let api = workspace::ClientApi {
        client: &client,
        company: co.company_id.clone(),
    };
    let mut status = workspace::ensure(&api, true)?;
    for _ in 0..10 {
        if !matches!(status, Status::Starting(_)) {
            break;
        }
        std::thread::sleep(std::time::Duration::from_secs(3));
        status = workspace::ensure(&api, false)?;
    }
    match status {
        Status::Ready(w) => {
            println!("Workspace {}: running", w.id);
            Ok(())
        }
        Status::Starting(w) => {
            println!("Workspace {}: still starting — try again in a moment", w.id);
            std::process::exit(1);
        }
        Status::Failed(w) => {
            eprintln!(
                "Workspace failed: {}",
                w.error.unwrap_or_else(|| "unknown error".into())
            );
            std::process::exit(1);
        }
        Status::Unavailable(why) => {
            eprintln!("Workspaces are unavailable: {why}");
            std::process::exit(1);
        }
    }
}
