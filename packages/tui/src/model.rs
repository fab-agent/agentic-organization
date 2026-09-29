//! API payloads and the derived sidebar view (pure, unit-tested).

use crate::cron;
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
pub struct Me {
    #[serde(default)]
    pub companies: Vec<MyCompany>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct MyCompany {
    pub company_id: String,
    pub company_name: String,
    pub personnel_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Department {
    pub id: String,
    pub name: String,
    pub parent_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Person {
    pub id: String,
    pub title: Option<String>,
    pub role: Option<String>,
    /// "human" | "agent"
    #[serde(rename = "type")]
    pub kind: Option<String>,
    pub department_id: Option<String>,
    pub manager_id: Option<String>,
    pub manager_name: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Flow {
    pub name: String,
    pub personnel_id: String,
    pub schedule: String,
    pub enabled: bool,
    pub last_run_at: Option<String>,
    pub last_run_status: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct InboxItem {
    pub title: String,
}

#[derive(Debug, Clone, Default)]
pub struct Snapshot {
    pub me: Option<Me>,
    pub departments: Vec<Department>,
    pub personnel: Vec<Person>,
    pub flows: Vec<Flow>,
    pub inbox: Vec<InboxItem>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunState {
    Ok,
    Failed,
    Pending,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunLine {
    pub state: RunState,
    pub when: String,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RecurringLine {
    pub enabled: bool,
    pub when: String,
    pub name: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Sidebar {
    pub company: String,
    pub department: Option<String>,
    pub role: Option<String>,
    pub manager: Option<String>,
    pub humans: usize,
    pub agents: usize,
    pub recurring: Vec<RecurringLine>,
    pub runs: Vec<RunLine>,
}

impl Snapshot {
    /// Build the sidebar for the first company of the signed-in user.
    pub fn sidebar(&self) -> Sidebar {
        let Some(co) = self.me.as_ref().and_then(|m| m.companies.first()) else {
            return Sidebar::default();
        };
        let mine = co
            .personnel_id
            .as_deref()
            .and_then(|id| self.personnel.iter().find(|p| p.id == id));

        // "My team": me, my direct reports, and (if I have none) my department.
        let mut team: Vec<&Person> = self
            .personnel
            .iter()
            .filter(|p| match (mine, p.manager_id.as_deref()) {
                (Some(m), Some(mgr)) => mgr == m.id,
                _ => false,
            })
            .collect();
        if let Some(m) = mine {
            team.push(m);
        }
        let agents = team
            .iter()
            .filter(|p| p.kind.as_deref() == Some("agent"))
            .count();
        let humans = team.len() - agents;
        let team_ids: Vec<&str> = team.iter().map(|p| p.id.as_str()).collect();

        let department = mine
            .and_then(|m| m.department_id.as_deref())
            .and_then(|id| self.departments.iter().find(|d| d.id == id))
            .map(|d| match d.parent_id.as_deref().and_then(|pid| self.departments.iter().find(|x| x.id == pid)) {
                Some(parent) => format!("{} › {}", parent.name, d.name),
                None => d.name.clone(),
            });

        let mine_flows = self
            .flows
            .iter()
            .filter(|f| team_ids.contains(&f.personnel_id.as_str()));

        let recurring = mine_flows
            .clone()
            .map(|f| RecurringLine {
                enabled: f.enabled,
                when: cron::describe(&f.schedule),
                name: f.name.clone(),
            })
            .collect();

        let mut runs: Vec<(&str, RunLine)> = mine_flows
            .filter_map(|f| {
                let at = f.last_run_at.as_deref()?;
                let state = match f.last_run_status.as_deref() {
                    Some("success") | Some("ok") | Some("completed") => RunState::Ok,
                    Some("running") | Some("pending") => RunState::Pending,
                    _ => RunState::Failed,
                };
                Some((at, RunLine { state, when: short_time(at), text: f.name.clone() }))
            })
            .collect();
        runs.sort_by(|a, b| b.0.cmp(a.0));
        let mut runs: Vec<RunLine> = runs.into_iter().map(|(_, r)| r).take(5).collect();
        runs.extend(self.inbox.iter().take(3).map(|i| RunLine {
            state: RunState::Pending,
            when: String::new(),
            text: format!("approval: {}", i.title),
        }));

        Sidebar {
            company: co.company_name.clone(),
            department,
            role: mine.and_then(|m| m.title.clone().or_else(|| m.role.clone())),
            manager: mine.and_then(|m| m.manager_name.clone()),
            humans,
            agents,
            recurring,
            runs,
        }
    }
}

/// "2026-09-28T09:00:03.123" → "09:00"
fn short_time(iso: &str) -> String {
    iso.split('T')
        .nth(1)
        .map(|t| t.chars().take(5).collect())
        .unwrap_or_else(|| iso.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn person(id: &str, kind: &str, mgr: Option<&str>) -> Person {
        Person {
            id: id.into(),
            title: Some("AP Specialist".into()),
            role: None,
            kind: Some(kind.into()),
            department_id: Some("d2".into()),
            manager_id: mgr.map(Into::into),
            manager_name: mgr.map(|_| "A. Yılmaz".into()),
        }
    }

    fn snapshot() -> Snapshot {
        Snapshot {
            me: Some(Me {
                companies: vec![MyCompany {
                    company_id: "c1".into(),
                    company_name: "Fabrika Yazılım".into(),
                    personnel_id: Some("me".into()),
                }],
            }),
            departments: vec![
                Department { id: "d1".into(), name: "Finance".into(), parent_id: None },
                Department { id: "d2".into(), name: "Accounting".into(), parent_id: Some("d1".into()) },
            ],
            personnel: vec![
                person("me", "human", Some("boss")),
                person("bot", "agent", Some("me")),
                person("other", "human", Some("boss")),
            ],
            flows: vec![
                Flow { name: "Daily cash report".into(), personnel_id: "bot".into(), schedule: "0 9 * * *".into(), enabled: true, last_run_at: Some("2026-09-28T09:00:03".into()), last_run_status: Some("success".into()) },
                Flow { name: "Not mine".into(), personnel_id: "other".into(), schedule: "0 9 * * *".into(), enabled: true, last_run_at: None, last_run_status: None },
            ],
            inbox: vec![InboxItem { title: "PO #4411".into() }],
        }
    }

    #[test]
    fn sidebar_scopes_to_my_team() {
        let s = snapshot().sidebar();
        assert_eq!(s.company, "Fabrika Yazılım");
        assert_eq!(s.department.as_deref(), Some("Finance › Accounting"));
        assert_eq!(s.role.as_deref(), Some("AP Specialist"));
        assert_eq!((s.humans, s.agents), (1, 1));
        assert_eq!(s.recurring.len(), 1);
        assert_eq!(s.runs[0].state, RunState::Ok);
        assert_eq!(s.runs[0].when, "09:00");
        assert_eq!(s.runs[1].text, "approval: PO #4411");
    }

    #[test]
    fn empty_snapshot_is_default() {
        assert_eq!(Snapshot::default().sidebar(), Sidebar::default());
    }
}
