//! Thin blocking client over the existing backend APIs (ADR-0014 §3).

use crate::model::{Department, Flow, InboxItem, Me, Person};
use crate::session::Session;
use crate::sync::{Manifest, Remote};
use crate::workspace::Ws;
use anyhow::{anyhow, Result};
use serde::de::DeserializeOwned;
use std::io::Read;
use std::time::Duration;

fn agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(10))
        .build()
}

/// An HTTP error response from the backend (status kept so callers can react).
#[derive(Debug)]
pub struct ApiError {
    pub status: u16,
    pub detail: String,
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.detail)
    }
}

impl std::error::Error for ApiError {}

/// The HTTP status of an error that came from the backend, if it did.
pub fn status_of(e: &anyhow::Error) -> Option<u16> {
    e.downcast_ref::<ApiError>().map(|a| a.status)
}

fn error_from(e: ureq::Error) -> anyhow::Error {
    match e {
        ureq::Error::Status(code, resp) => {
            let detail = resp
                .into_json::<serde_json::Value>()
                .ok()
                .and_then(|v| v.get("detail").and_then(|d| d.as_str().map(String::from)))
                .unwrap_or_else(|| format!("HTTP {code}"));
            anyhow::Error::new(ApiError {
                status: code,
                detail,
            })
        }
        other => anyhow!(other.to_string()),
    }
}

pub fn login(base: &str, email: &str, password: &str) -> Result<String> {
    let v: serde_json::Value = agent()
        .post(&format!("{base}/auth/token"))
        .send_json(serde_json::json!({ "email": email, "password": password }))
        .map_err(error_from)?
        .into_json()?;
    v.get("access_token")
        .and_then(|t| t.as_str())
        .map(String::from)
        .ok_or_else(|| anyhow!("no access_token in response"))
}

pub struct Client {
    s: Session,
    http: ureq::Agent,
}

impl Client {
    pub fn new(s: Session) -> Self {
        Self { s, http: agent() }
    }

    fn get<T: DeserializeOwned>(&self, path: &str) -> Result<T> {
        self.http
            .get(&format!("{}{path}", self.s.base_url))
            .set("Authorization", &format!("Bearer {}", self.s.token))
            .call()
            .map_err(error_from)?
            .into_json()
            .map_err(Into::into)
    }

    pub fn me(&self) -> Result<Me> {
        self.get("/auth/me")
    }
    pub fn departments(&self, company: &str) -> Result<Vec<Department>> {
        self.get(&format!("/departments?company_id={company}"))
    }
    pub fn personnel(&self, company: &str) -> Result<Vec<Person>> {
        self.get(&format!("/personnel?company_id={company}"))
    }
    pub fn flows(&self, company: &str) -> Result<Vec<Flow>> {
        self.get(&format!("/flows?company_id={company}"))
    }
    pub fn inbox(&self, company: &str) -> Result<Vec<InboxItem>> {
        self.get(&format!("/inbox?company_id={company}&unread_only=true"))
    }

    /// The caller's live workspace, or `None` if they have none yet.
    pub fn workspace_current(&self, company: &str) -> Result<Option<Ws>> {
        let r = self
            .http
            .get(&format!(
                "{}/workspaces/me?company_id={company}",
                self.s.base_url
            ))
            .set("Authorization", &format!("Bearer {}", self.s.token))
            .call();
        match r {
            Ok(resp) => Ok(Some(resp.into_json()?)),
            Err(ureq::Error::Status(404, _)) => Ok(None),
            Err(e) => Err(error_from(e)),
        }
    }

    fn workspace_post(&self, path: &str) -> Result<Ws> {
        self.http
            .post(&format!("{}{path}", self.s.base_url))
            .set("Authorization", &format!("Bearer {}", self.s.token))
            .call()
            .map_err(error_from)?
            .into_json()
            .map_err(Into::into)
    }

    /// Create the caller's workspace (idempotent; retries a failed one).
    pub fn workspace_create(&self, company: &str) -> Result<Ws> {
        self.workspace_post(&format!("/workspaces?company_id={company}"))
    }

    pub fn workspace_resume(&self, id: &str) -> Result<Ws> {
        self.workspace_post(&format!("/workspaces/{id}/resume"))
    }
}

/// Percent-encode each path segment (keeps `/`), so names with spaces, `#`, `?`
/// or non-ASCII characters survive the URL.
pub fn encode_path(path: &str) -> String {
    path.split('/')
        .map(|seg| {
            seg.bytes()
                .map(|b| match b {
                    b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => {
                        (b as char).to_string()
                    }
                    _ => format!("%{b:02X}"),
                })
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("/")
}

/// The workspace files API (ADR-0018) as a sync `Remote`.
pub struct WorkspaceRemote<'a> {
    pub client: &'a Client,
    pub workspace_id: String,
}

impl WorkspaceRemote<'_> {
    fn url(&self, tail: &str) -> String {
        format!(
            "{}/workspaces/{}/files{tail}",
            self.client.s.base_url, self.workspace_id
        )
    }
    fn auth(&self) -> String {
        format!("Bearer {}", self.client.s.token)
    }
}

impl Remote for WorkspaceRemote<'_> {
    fn manifest(&self, since: i64) -> Result<Manifest> {
        self.client
            .http
            .get(&self.url(&format!("?since={since}")))
            .set("Authorization", &self.auth())
            .call()
            .map_err(error_from)?
            .into_json()
            .map_err(Into::into)
    }

    fn download(&self, path: &str, max_bytes: u64) -> Result<Vec<u8>> {
        let resp = self
            .client
            .http
            .get(&self.url(&format!("/{}", encode_path(path))))
            .set("Authorization", &self.auth())
            .call()
            .map_err(error_from)?;
        let mut buf = Vec::new();
        resp.into_reader()
            .take(max_bytes + 1)
            .read_to_end(&mut buf)?;
        if buf.len() as u64 > max_bytes {
            return Err(anyhow!("file exceeds the download limit"));
        }
        Ok(buf)
    }

    fn upload(&self, path: &str, data: &[u8]) -> Result<()> {
        self.client
            .http
            .put(&self.url(&format!("/{}", encode_path(path))))
            .set("Authorization", &self.auth())
            .set("Content-Type", "application/octet-stream")
            .send_bytes(data)
            .map_err(error_from)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::encode_path;

    #[test]
    fn encodes_segments_but_keeps_slashes() {
        assert_eq!(encode_path("a b/c#d?.txt"), "a%20b/c%23d%3F.txt");
        assert_eq!(encode_path("özet/rapor.md"), "%C3%B6zet/rapor.md");
        assert_eq!(encode_path("plain-1_2.x"), "plain-1_2.x");
    }
}
