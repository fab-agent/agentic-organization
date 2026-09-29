//! First-run / return flow for the person's server-side workspace (ADR-0014,
//! ADR-0018): create it if there is none, resume it if suspended, wait while it
//! starts, and surface failures without hammering a broken runtime.

use crate::api::{status_of, Client};
use anyhow::Result;
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct Ws {
    pub id: String,
    pub state: String,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Status {
    /// Running: files can sync (and, later, the agent can attach).
    Ready(Ws),
    /// Being created; check again shortly.
    Starting(Ws),
    /// Failed. Not retried automatically — the person retries with `r`.
    Failed(Ws),
    /// The platform cannot provide workspaces right now (runtime not configured).
    Unavailable(String),
}

impl Status {
    pub fn ready(&self) -> Option<&Ws> {
        match self {
            Status::Ready(w) => Some(w),
            _ => None,
        }
    }
}

/// What `ensure` needs from the backend (a trait so it is tested without a network).
pub trait WorkspaceApi {
    fn current(&self) -> Result<Option<Ws>>;
    fn create(&self) -> Result<Ws>;
    fn resume(&self, id: &str) -> Result<Ws>;
}

pub struct ClientApi<'a> {
    pub client: &'a Client,
    pub company: String,
}

impl WorkspaceApi for ClientApi<'_> {
    fn current(&self) -> Result<Option<Ws>> {
        self.client.workspace_current(&self.company)
    }
    fn create(&self) -> Result<Ws> {
        self.client.workspace_create(&self.company)
    }
    fn resume(&self, id: &str) -> Result<Ws> {
        self.client.workspace_resume(id)
    }
}

fn classify(r: Result<Ws>) -> Result<Status> {
    match r {
        Ok(ws) => Ok(match ws.state.as_str() {
            "running" => Status::Ready(ws),
            "creating" => Status::Starting(ws),
            _ => Status::Failed(ws),
        }),
        Err(e) => match status_of(&e) {
            Some(503) => Ok(Status::Unavailable(e.to_string())),
            // The runtime refused (backend marked the workspace failed / left it as is).
            Some(502) | Some(409) => Ok(Status::Failed(Ws {
                id: String::new(),
                state: "failed".into(),
                error: Some(e.to_string()),
            })),
            _ => Err(e),
        },
    }
}

/// Bring the workspace to a usable state.
///
/// `retry_failed` is true for the first pass after launch and for an explicit
/// retry, false for timer passes.
pub fn ensure(api: &dyn WorkspaceApi, retry_failed: bool) -> Result<Status> {
    let Some(ws) = api.current()? else {
        return classify(api.create());
    };
    match ws.state.as_str() {
        "running" => Ok(Status::Ready(ws)),
        "suspended" => classify(api.resume(&ws.id)),
        "creating" => Ok(Status::Starting(ws)),
        "failed" if retry_failed => classify(api.create()),
        _ => Ok(Status::Failed(ws)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::ApiError;
    use std::cell::RefCell;

    fn ws(state: &str) -> Ws {
        Ws {
            id: "w1".into(),
            state: state.into(),
            error: (state == "failed").then(|| "boom".into()),
        }
    }

    #[derive(Default)]
    struct Fake {
        current: Option<Ws>,
        create_result: RefCell<Option<Result<Ws>>>,
        resume_result: RefCell<Option<Result<Ws>>>,
        calls: RefCell<Vec<&'static str>>,
    }

    impl WorkspaceApi for Fake {
        fn current(&self) -> Result<Option<Ws>> {
            Ok(self.current.clone())
        }
        fn create(&self) -> Result<Ws> {
            self.calls.borrow_mut().push("create");
            self.create_result
                .borrow_mut()
                .take()
                .unwrap_or_else(|| Ok(ws("running")))
        }
        fn resume(&self, _id: &str) -> Result<Ws> {
            self.calls.borrow_mut().push("resume");
            self.resume_result
                .borrow_mut()
                .take()
                .unwrap_or_else(|| Ok(ws("running")))
        }
    }

    fn api_err(status: u16, detail: &str) -> anyhow::Error {
        anyhow::Error::new(ApiError {
            status,
            detail: detail.into(),
        })
    }

    #[test]
    fn none_is_created() {
        let f = Fake::default();
        assert_eq!(ensure(&f, false).unwrap(), Status::Ready(ws("running")));
        assert_eq!(*f.calls.borrow(), vec!["create"]);
    }

    #[test]
    fn running_needs_no_calls() {
        let f = Fake {
            current: Some(ws("running")),
            ..Default::default()
        };
        assert!(ensure(&f, true).unwrap().ready().is_some());
        assert!(f.calls.borrow().is_empty());
    }

    #[test]
    fn suspended_is_resumed() {
        let f = Fake {
            current: Some(ws("suspended")),
            ..Default::default()
        };
        assert!(ensure(&f, false).unwrap().ready().is_some());
        assert_eq!(*f.calls.borrow(), vec!["resume"]);
    }

    #[test]
    fn creating_waits() {
        let f = Fake {
            current: Some(ws("creating")),
            ..Default::default()
        };
        assert_eq!(ensure(&f, true).unwrap(), Status::Starting(ws("creating")));
        assert!(f.calls.borrow().is_empty());
    }

    #[test]
    fn failed_is_retried_only_when_asked() {
        let f = Fake {
            current: Some(ws("failed")),
            ..Default::default()
        };
        assert_eq!(ensure(&f, false).unwrap(), Status::Failed(ws("failed")));
        assert!(f.calls.borrow().is_empty());
        assert!(ensure(&f, true).unwrap().ready().is_some());
        assert_eq!(*f.calls.borrow(), vec!["create"]);
    }

    #[test]
    fn missing_runtime_is_unavailable() {
        let f = Fake::default();
        *f.create_result.borrow_mut() = Some(Err(api_err(503, "runtime not configured")));
        assert_eq!(
            ensure(&f, false).unwrap(),
            Status::Unavailable("runtime not configured".into())
        );
    }

    #[test]
    fn runtime_failure_becomes_failed_with_the_reason() {
        let f = Fake::default();
        *f.create_result.borrow_mut() = Some(Err(api_err(502, "Workspace runtime error: no disk")));
        match ensure(&f, false).unwrap() {
            Status::Failed(w) => {
                assert_eq!(w.error.as_deref(), Some("Workspace runtime error: no disk"))
            }
            other => panic!("{other:?}"),
        }
        let f = Fake {
            current: Some(ws("suspended")),
            ..Default::default()
        };
        *f.resume_result.borrow_mut() = Some(Err(api_err(502, "start failed")));
        assert!(matches!(ensure(&f, false).unwrap(), Status::Failed(_)));
    }

    #[test]
    fn other_errors_propagate() {
        let f = Fake::default();
        *f.create_result.borrow_mut() = Some(Err(anyhow::anyhow!("connection refused")));
        assert!(ensure(&f, false).is_err());
        let f = Fake::default();
        *f.create_result.borrow_mut() = Some(Err(api_err(401, "Token gerekli")));
        assert!(ensure(&f, false).is_err());
    }
}
