//! Event loop and state.

use crate::api::Client;
use crate::i18n::{self, Lang};
use crate::model::Snapshot;
use crate::pty::{self, Pty};
use crate::session;
use crate::sync::{self, Outcome};
use crate::ui;
use anyhow::{bail, Result};
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use std::path::PathBuf;
use std::sync::mpsc::{Receiver, Sender};
use std::time::{Duration, Instant};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Focus {
    Sidebar,
    Agent,
}

/// State of the local-folder sync shown in the files strip.
#[derive(Default)]
pub struct SyncStatus {
    pub folder: PathBuf,
    pub last: Option<Instant>,
    pub changed: usize,
    pub conflicts: usize,
    pub no_workspace: bool,
    pub error: Option<String>,
    pub recent: Vec<String>,
}

pub struct App {
    pub lang: Lang,
    pub focus: Focus,
    pub snapshot: Snapshot,
    pub error: Option<String>,
    pub should_quit: bool,
    pub pty: Option<Pty>,
    pub sync: SyncStatus,
    sync_rx: Option<Receiver<Result<Outcome, String>>>,
    sync_poke: Option<Sender<()>>,
    client: Client,
}

impl App {
    fn refresh(&mut self) {
        match load(&self.client) {
            Ok(s) => {
                self.snapshot = s;
                self.error = None;
            }
            Err(e) => self.error = Some(e.to_string()),
        }
    }

    /// Apply any finished background sync passes.
    fn poll_sync(&mut self) {
        let Some(rx) = &self.sync_rx else { return };
        while let Ok(res) = rx.try_recv() {
            self.sync.last = Some(Instant::now());
            match res {
                Ok(Outcome::NoWorkspace) => {
                    self.sync.no_workspace = true;
                    self.sync.error = None;
                }
                Ok(Outcome::Synced { report, recent }) => {
                    self.sync.no_workspace = false;
                    self.sync.changed = report.changed();
                    self.sync.conflicts = report.pending_conflicts.len();
                    self.sync.error = report.errors.first().cloned();
                    self.sync.recent = recent;
                }
                Err(e) => self.sync.error = Some(e),
            }
        }
    }

    fn start_agent(&mut self) {
        match Pty::spawn(&pty::default_command(), 80, 24) {
            Ok(p) => {
                self.pty = Some(p);
                self.error = None;
            }
            Err(e) => self.error = Some(format!("{e:#}")),
        }
    }

    pub fn agent_ended(&self) -> bool {
        self.pty.as_ref().is_none_or(|p| !p.is_alive())
    }

    fn toggle_focus(&mut self) {
        self.focus = match self.focus {
            Focus::Sidebar => Focus::Agent,
            Focus::Agent => Focus::Sidebar,
        };
    }

    fn on_key(&mut self, k: KeyEvent) {
        let ctrl_o = k.code == KeyCode::Char('o') && k.modifiers.contains(KeyModifiers::CONTROL);
        if ctrl_o {
            self.toggle_focus();
            return;
        }
        match self.focus {
            Focus::Agent => {
                if self.agent_ended() {
                    if k.code == KeyCode::Enter {
                        self.start_agent();
                    }
                } else if let Some(p) = &self.pty {
                    p.write(&pty::encode_key(k));
                }
            }
            Focus::Sidebar => match k.code {
                KeyCode::Char('q') => self.should_quit = true,
                KeyCode::Char('c') if k.modifiers.contains(KeyModifiers::CONTROL) => {
                    self.should_quit = true
                }
                KeyCode::Char('r') => {
                    self.refresh();
                    if let Some(p) = &self.sync_poke {
                        let _ = p.send(());
                    }
                }
                KeyCode::Tab | KeyCode::Enter => self.focus = Focus::Agent,
                _ => {}
            },
        }
    }
}

#[cfg(test)]
impl App {
    pub fn test_default() -> Self {
        App {
            lang: Lang::En,
            focus: Focus::Agent,
            snapshot: Snapshot::default(),
            error: None,
            should_quit: false,
            pty: None,
            sync: SyncStatus::default(),
            sync_rx: None,
            sync_poke: None,
            client: Client::new(session::Session {
                base_url: String::new(),
                token: String::new(),
            }),
        }
    }
}

fn load(c: &Client) -> Result<Snapshot> {
    let me = c.me()?;
    let Some(co) = me.companies.first().map(|c| c.company_id.clone()) else {
        bail!("this account belongs to no company");
    };
    Ok(Snapshot {
        departments: c.departments(&co)?,
        personnel: c.personnel(&co)?,
        flows: c.flows(&co)?,
        inbox: c.inbox(&co).unwrap_or_default(),
        me: Some(me),
    })
}

pub fn run() -> Result<()> {
    let Some(sess) = session::load() else {
        bail!("not signed in — run `fab login` first");
    };
    let mut app = App {
        lang: i18n::detect(),
        focus: Focus::Agent,
        snapshot: Snapshot::default(),
        error: None,
        should_quit: false,
        pty: None,
        sync: SyncStatus {
            folder: sync::default_folder(),
            ..SyncStatus::default()
        },
        sync_rx: None,
        sync_poke: None,
        client: Client::new(sess.clone()),
    };
    let (rx, poke) = sync::spawn_loop(sess, app.sync.folder.clone(), Duration::from_secs(30));
    app.sync_rx = Some(rx);
    app.sync_poke = Some(poke);
    app.refresh();
    app.start_agent();

    let mut terminal = ratatui::init();
    let result = (|| -> Result<()> {
        while !app.should_quit {
            app.poll_sync();
            terminal.draw(|f| ui::draw(f, &app))?;
            if event::poll(Duration::from_millis(250))? {
                if let Event::Key(k) = event::read()? {
                    if k.kind == KeyEventKind::Press {
                        app.on_key(k);
                    }
                }
            }
        }
        Ok(())
    })();
    ratatui::restore();
    result
}
