//! Event loop and state.

use crate::api::Client;
use crate::i18n::{self, Lang};
use crate::model::Snapshot;
use crate::session;
use crate::ui;
use anyhow::{bail, Result};
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
use std::time::Duration;

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Focus {
    Sidebar,
    Agent,
}

pub struct App {
    pub lang: Lang,
    pub focus: Focus,
    pub snapshot: Snapshot,
    pub error: Option<String>,
    pub should_quit: bool,
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

    fn on_key(&mut self, code: KeyCode, mods: KeyModifiers) {
        match code {
            KeyCode::Char('q') => self.should_quit = true,
            KeyCode::Char('c') if mods.contains(KeyModifiers::CONTROL) => self.should_quit = true,
            KeyCode::Char('r') => self.refresh(),
            KeyCode::Tab => {
                self.focus = match self.focus {
                    Focus::Sidebar => Focus::Agent,
                    Focus::Agent => Focus::Sidebar,
                }
            }
            _ => {}
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
            client: Client::new(session::Session { base_url: String::new(), token: String::new() }),
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
        client: Client::new(sess),
    };
    app.refresh();

    let mut terminal = ratatui::init();
    let result = (|| -> Result<()> {
        while !app.should_quit {
            terminal.draw(|f| ui::draw(f, &app))?;
            if event::poll(Duration::from_millis(250))? {
                if let Event::Key(k) = event::read()? {
                    if k.kind == KeyEventKind::Press {
                        app.on_key(k.code, k.modifiers);
                    }
                }
            }
        }
        Ok(())
    })();
    ratatui::restore();
    result
}
