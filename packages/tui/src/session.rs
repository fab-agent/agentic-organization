//! Stored login session: `~/.config/fab/session.json` (mode 600).
//! `FAB_SESSION_FILE` overrides the path (tests, CI).

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::io::{BufRead, Write};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    pub base_url: String,
    pub token: String,
}

pub fn path() -> PathBuf {
    if let Ok(p) = std::env::var("FAB_SESSION_FILE") {
        return p.into();
    }
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("fab")
        .join("session.json")
}

pub fn load() -> Option<Session> {
    serde_json::from_slice(&std::fs::read(path()).ok()?).ok()
}

pub fn save(s: &Session) -> Result<()> {
    let p = path();
    if let Some(dir) = p.parent() {
        std::fs::create_dir_all(dir)?;
    }
    std::fs::write(&p, serde_json::to_vec_pretty(s)?)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o600))?;
    }
    Ok(())
}

pub fn clear() -> Result<()> {
    match std::fs::remove_file(path()) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e.into()),
    }
}

fn prompt(label: &str) -> Result<String> {
    print!("{label}: ");
    std::io::stdout().flush()?;
    let mut line = String::new();
    std::io::stdin().lock().read_line(&mut line)?;
    Ok(line.trim().to_string())
}

pub fn login_interactive() -> Result<()> {
    let default = load().map(|s| s.base_url).unwrap_or_default();
    let mut base = prompt(&format!("Platform URL [{default}]"))?;
    if base.is_empty() {
        base = default;
    }
    if base.is_empty() {
        bail!("platform URL is required");
    }
    let base = base.trim_end_matches('/').to_string();
    let email = prompt("Email")?;
    let password = rpassword::prompt_password("Password: ")?;
    let token = crate::api::login(&base, &email, &password).context("login failed")?;
    save(&Session {
        base_url: base,
        token,
    })?;
    println!("Signed in. Run `fab` to open the workspace.");
    Ok(())
}
