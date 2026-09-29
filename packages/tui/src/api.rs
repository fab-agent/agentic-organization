//! Thin blocking client over the existing backend APIs (ADR-0014 §3).

use crate::model::{Department, Flow, InboxItem, Me, Person};
use crate::session::Session;
use anyhow::{anyhow, Result};
use serde::de::DeserializeOwned;
use std::time::Duration;

fn agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(10))
        .build()
}

fn error_from(e: ureq::Error) -> anyhow::Error {
    match e {
        ureq::Error::Status(code, resp) => {
            let detail = resp
                .into_json::<serde_json::Value>()
                .ok()
                .and_then(|v| v.get("detail").and_then(|d| d.as_str().map(String::from)));
            anyhow!(detail.unwrap_or_else(|| format!("HTTP {code}")))
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
}
