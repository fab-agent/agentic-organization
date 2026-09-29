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
mod session;
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
        Some("-h") | Some("--help") | Some("help") => {
            println!("fab — terminal workspace\n\nUSAGE:\n  fab            open the workspace\n  fab login      sign in to a platform\n  fab logout     forget the stored session");
            Ok(())
        }
        None => app::run(),
        Some(other) => anyhow::bail!("unknown command `{other}` (try `fab help`)"),
    }
}
