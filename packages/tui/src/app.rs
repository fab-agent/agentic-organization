//! Event loop and state.

use crate::api::Client;
use crate::i18n::{self, Lang};
use crate::model::Snapshot;
use crate::pty::{self, Pty};
use crate::review::{
    self, Action as ReviewAction, Backend as ReviewBackend, Msg as ReviewMsg, ReviewState,
};
use crate::session;
use crate::sync::{self, Pass};
use crate::ui;
use crate::workspace::Status;
use anyhow::{bail, Result};
use ratatui::crossterm::event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers};
use std::path::PathBuf;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
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
    pub workspace: Option<Status>,
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
    pub review: ReviewState,
    review_backend: Arc<dyn ReviewBackend>,
    review_tx: Sender<ReviewMsg>,
    review_rx: Receiver<ReviewMsg>,
    sync_rx: Option<Receiver<Result<Pass, String>>>,
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
                Ok(pass) => {
                    self.sync.workspace = Some(pass.status);
                    match pass.synced {
                        Some((report, recent)) => {
                            self.sync.changed = report.changed();
                            self.sync.conflicts = report.pending_conflicts.len();
                            self.sync.error = report.errors.first().cloned();
                            self.sync.recent = recent;
                        }
                        None => self.sync.error = None,
                    }
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

    /// Perform what the review state machine asked for, on worker threads.
    fn run_review_action(&mut self, a: ReviewAction) {
        match a {
            ReviewAction::None | ReviewAction::Close => {}
            ReviewAction::Load => {
                let id = self.review.begin_load();
                review::spawn_load(
                    self.review_backend.clone(),
                    self.review_tx.clone(),
                    id,
                    self.review.window,
                );
            }
            ReviewAction::AddNote { day, text } => review::spawn_add_note(
                self.review_backend.clone(),
                self.review_tx.clone(),
                day,
                text,
            ),
            ReviewAction::DeleteNote { id } => {
                review::spawn_delete_note(self.review_backend.clone(), self.review_tx.clone(), id)
            }
            ReviewAction::ContestRating { id, note } => review::spawn_contest(
                self.review_backend.clone(),
                self.review_tx.clone(),
                id,
                note,
            ),
            ReviewAction::ShareSignal {
                criterion_id,
                criterion_hash,
            } => review::spawn_share_signal(
                self.review_backend.clone(),
                self.review_tx.clone(),
                criterion_id,
                criterion_hash,
            ),
            ReviewAction::UnshareSignal {
                criterion_id,
                criterion_hash,
            } => review::spawn_unshare_signal(
                self.review_backend.clone(),
                self.review_tx.clone(),
                criterion_id,
                criterion_hash,
            ),
            ReviewAction::WithdrawContest { id } => review::spawn_withdraw_contest(
                self.review_backend.clone(),
                self.review_tx.clone(),
                id,
            ),
        }
    }

    /// Apply finished review requests.
    pub fn poll_review(&mut self) {
        while let Ok(m) = self.review_rx.try_recv() {
            match m {
                ReviewMsg::Loaded(id, res) => self.review.apply_loaded(id, res),
                ReviewMsg::Saved(res) => {
                    let next = self.review.apply_saved(res);
                    self.run_review_action(next);
                }
            }
        }
    }

    fn on_key(&mut self, k: KeyEvent) {
        if k.code == KeyCode::Char('c') && k.modifiers.contains(KeyModifiers::CONTROL) {
            self.should_quit = true;
            return;
        }
        // "My review" is a full-screen view: while it is open it gets every key.
        if self.review.open {
            let a = self.review.on_key(k);
            self.run_review_action(a);
            return;
        }
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
                KeyCode::Char('v') => {
                    let a = self.review.open();
                    self.run_review_action(a);
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
        struct Off;
        impl ReviewBackend for Off {
            fn load(&self, _: u32) -> Result<review::Outcome> {
                Ok(review::Outcome::NotEnabled)
            }
            fn add_note(&self, _: &str, _: &str) -> Result<()> {
                Ok(())
            }
            fn delete_note(&self, _: &str) -> Result<()> {
                Ok(())
            }
            fn contest_rating(&self, _: &str, _: &str) -> Result<()> {
                Ok(())
            }
            fn withdraw_contest(&self, _: &str) -> Result<()> {
                Ok(())
            }
            fn share_signal(&self, _: &str, _: &str) -> Result<()> {
                Ok(())
            }
            fn unshare_signal(&self, _: &str, _: &str) -> Result<()> {
                Ok(())
            }
        }
        Self::test_with_review(Arc::new(Off))
    }

    pub fn test_with_review(backend: Arc<dyn ReviewBackend>) -> Self {
        let (review_tx, review_rx) = channel();
        App {
            lang: Lang::En,
            focus: Focus::Sidebar,
            snapshot: Snapshot::default(),
            error: None,
            should_quit: false,
            pty: None,
            sync: SyncStatus::default(),
            review: ReviewState::default(),
            review_backend: backend,
            review_tx,
            review_rx,
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
    let (review_tx, review_rx) = channel();
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
        review: ReviewState::default(),
        review_backend: Arc::new(review::Http {
            session: sess.clone(),
        }),
        review_tx,
        review_rx,
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
            app.poll_review();
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

#[cfg(test)]
mod review_flow_tests {
    use super::*;
    use crate::review::{DayEntry, Note, Outcome, Review, View};
    use std::collections::HashMap;
    use std::sync::Mutex;

    fn k(c: KeyCode) -> KeyEvent {
        KeyEvent::new(c, KeyModifiers::NONE)
    }
    fn press(app: &mut App, s: &str) {
        for c in s.chars() {
            app.on_key(k(KeyCode::Char(c)));
        }
    }

    fn review_with_ratings() -> Review {
        let mut r = review("A");
        r.days[0].ratings = vec![
            review::RatingItem {
                id: "r1".into(),
                criterion_id: "G1".into(),
                status: "live".into(),
                verdict: "met".into(),
                ..Default::default()
            },
            review::RatingItem {
                id: "r2".into(),
                criterion_id: "G2".into(),
                status: "live".into(),
                verdict: "unclear".into(),
                contested: true,
                ..Default::default()
            },
        ];
        r
    }

    fn review(tag: &str) -> Review {
        Review {
            name: tag.into(),
            window_days: 30,
            days: vec![DayEntry {
                day: "2026-09-29".into(),
                notes: vec![Note {
                    id: "n1".into(),
                    text: "old".into(),
                }],
                ..DayEntry::default()
            }],
            totals: Default::default(),
            ratings: vec![],
            training_need: vec![],
            training_sharing_enabled: false,
            disclosure: None,
        }
    }

    #[derive(Default)]
    struct Fake {
        calls: Mutex<Vec<String>>,
        outcome: Mutex<HashMap<u32, (u64, Outcome)>>, // days -> (delay ms, result)
        fail_add: Mutex<Option<String>>,
    }
    impl Fake {
        fn calls(&self) -> Vec<String> {
            self.calls.lock().unwrap().clone()
        }
    }
    impl ReviewBackend for Fake {
        fn load(&self, days: u32) -> Result<Outcome> {
            self.calls.lock().unwrap().push(format!("load {days}"));
            let (delay, out) = self
                .outcome
                .lock()
                .unwrap()
                .get(&days)
                .cloned()
                .unwrap_or((0, Outcome::NotEnabled));
            std::thread::sleep(Duration::from_millis(delay));
            Ok(out)
        }
        fn add_note(&self, day: &str, text: &str) -> Result<()> {
            self.calls.lock().unwrap().push(format!("add {day} {text}"));
            match self.fail_add.lock().unwrap().clone() {
                Some(e) => Err(anyhow::anyhow!(e)),
                None => Ok(()),
            }
        }
        fn delete_note(&self, id: &str) -> Result<()> {
            self.calls.lock().unwrap().push(format!("delete {id}"));
            Ok(())
        }
        fn contest_rating(&self, id: &str, note: &str) -> Result<()> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("contest {id} {note}"));
            Ok(())
        }
        fn withdraw_contest(&self, id: &str) -> Result<()> {
            self.calls.lock().unwrap().push(format!("withdraw {id}"));
            Ok(())
        }
        fn share_signal(&self, c: &str, h: &str) -> Result<()> {
            self.calls.lock().unwrap().push(format!("share {c} {h}"));
            Ok(())
        }
        fn unshare_signal(&self, c: &str, h: &str) -> Result<()> {
            self.calls.lock().unwrap().push(format!("unshare {c} {h}"));
            Ok(())
        }
    }

    fn app_with(fake: &Arc<Fake>) -> App {
        App::test_with_review(fake.clone())
    }

    /// Poll finished requests until `cond` holds (or fail after two seconds).
    fn wait(app: &mut App, what: &str, cond: impl Fn(&App) -> bool) {
        let end = std::time::Instant::now() + Duration::from_secs(2);
        while std::time::Instant::now() < end {
            app.poll_review();
            if cond(app) {
                return;
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        panic!("timed out waiting for: {what}");
    }

    fn ready_app(fake: &Arc<Fake>) -> App {
        fake.outcome
            .lock()
            .unwrap()
            .insert(30, (0, Outcome::Ready(review("A"))));
        let mut app = app_with(fake);
        press(&mut app, "v");
        wait(&mut app, "ready", |a| {
            matches!(a.review.view, View::Ready(_))
        });
        app
    }

    #[test]
    fn v_from_the_sidebar_opens_and_loads_off_the_ui_thread() {
        let fake = Arc::new(Fake::default());
        let app = ready_app(&fake);
        assert!(app.review.open);
        assert_eq!(fake.calls(), vec!["load 30"]);
        assert!(matches!(&app.review.view, View::Ready(r) if r.name == "A"));
    }

    #[test]
    fn v_in_the_agent_pane_is_the_agents_key_not_the_reviews() {
        let fake = Arc::new(Fake::default());
        let mut app = app_with(&fake);
        app.focus = Focus::Agent;
        press(&mut app, "v");
        assert!(!app.review.open && fake.calls().is_empty());
    }

    #[test]
    fn q_closes_the_review_it_does_not_quit_and_ctrl_c_always_quits() {
        let fake = Arc::new(Fake::default());
        let mut app = ready_app(&fake);
        press(&mut app, "q");
        assert!(!app.review.open && !app.should_quit);
        press(&mut app, "q");
        assert!(
            app.should_quit,
            "with the review closed, q is the sidebar's quit again"
        );

        let mut app = ready_app(&fake);
        app.on_key(KeyEvent::new(KeyCode::Char('c'), KeyModifiers::CONTROL));
        assert!(app.should_quit);
    }

    #[test]
    fn while_open_the_review_gets_every_key_even_the_sidebars() {
        let fake = Arc::new(Fake::default());
        let mut app = ready_app(&fake);
        press(&mut app, "r"); // reload, not the sidebar's refresh
        app.on_key(k(KeyCode::Tab)); // not "focus the agent"
        assert_eq!(app.focus, Focus::Sidebar);
        wait(&mut app, "second load", |_| fake.calls().len() >= 2);
        assert_eq!(fake.calls(), vec!["load 30", "load 30"]);
    }

    fn rated_app(fake: &Arc<Fake>) -> App {
        fake.outcome
            .lock()
            .unwrap()
            .insert(30, (0, Outcome::Ready(review_with_ratings())));
        let mut app = app_with(fake);
        press(&mut app, "v");
        wait(&mut app, "ready", |a| {
            matches!(a.review.view, View::Ready(_))
        });
        app
    }

    #[test]
    fn contesting_a_rating_calls_the_backend_with_the_reason_then_reloads() {
        let fake = Arc::new(Fake::default());
        let mut app = rated_app(&fake);
        press(&mut app, "c");
        press(&mut app, "Rehearsal");
        app.on_key(k(KeyCode::Enter));
        wait(&mut app, "contest + reload", |_| fake.calls().len() >= 3);
        assert_eq!(
            fake.calls(),
            vec!["load 30", "contest r1 Rehearsal", "load 30"]
        );
    }

    #[test]
    fn withdrawing_a_contest_calls_the_backend_then_reloads() {
        let fake = Arc::new(Fake::default());
        let mut app = rated_app(&fake);
        app.on_key(k(KeyCode::Right)); // r2 is the contested one
        press(&mut app, "u");
        wait(&mut app, "withdraw + reload", |_| fake.calls().len() >= 3);
        assert_eq!(fake.calls(), vec!["load 30", "withdraw r2", "load 30"]);
    }

    #[test]
    fn a_contest_key_in_the_agent_pane_is_the_agents_not_the_reviews() {
        let fake = Arc::new(Fake::default());
        let mut app = app_with(&fake);
        app.focus = Focus::Agent;
        press(&mut app, "c");
        assert!(!app.review.open && fake.calls().is_empty());
    }

    fn signal_app(fake: &Arc<Fake>, shared: bool, enabled: bool) -> App {
        let mut r = review("A");
        r.training_need = vec![review::TrainingSignal {
            criterion_id: "G1".into(),
            criterion_hash: "h1".into(),
            rated: 10,
            not_met: 7,
            window_days: 30,
            unit_wide: false,
            shared,
            question: None,
        }];
        r.training_sharing_enabled = enabled;
        fake.outcome
            .lock()
            .unwrap()
            .insert(30, (0, Outcome::Ready(r)));
        let mut app = app_with(fake);
        press(&mut app, "v");
        wait(&mut app, "ready", |a| {
            matches!(a.review.view, View::Ready(_))
        });
        app
    }

    #[test]
    fn sharing_a_signal_asks_first_then_calls_the_backend_and_reloads() {
        let fake = Arc::new(Fake::default());
        let mut app = signal_app(&fake, false, true);
        press(&mut app, "s");
        assert_eq!(fake.calls(), vec!["load 30"], "s alone shares nothing");
        press(&mut app, "y");
        wait(&mut app, "share + reload", |_| fake.calls().len() >= 3);
        assert_eq!(fake.calls(), vec!["load 30", "share G1 h1", "load 30"]);
    }

    #[test]
    fn declining_the_question_sends_nothing() {
        let fake = Arc::new(Fake::default());
        let mut app = signal_app(&fake, false, true);
        press(&mut app, "s");
        press(&mut app, "n");
        press(&mut app, "y");
        std::thread::sleep(Duration::from_millis(100));
        app.poll_review();
        assert_eq!(fake.calls(), vec!["load 30"]);
    }

    #[test]
    fn withdrawing_a_share_calls_the_backend_then_reloads() {
        let fake = Arc::new(Fake::default());
        let mut app = signal_app(&fake, true, true);
        press(&mut app, "s");
        wait(&mut app, "unshare + reload", |_| fake.calls().len() >= 3);
        assert_eq!(fake.calls(), vec!["load 30", "unshare G1 h1", "load 30"]);
    }

    #[test]
    fn with_sharing_off_nothing_is_sent_and_the_person_is_told() {
        let fake = Arc::new(Fake::default());
        let mut app = signal_app(&fake, false, false);
        press(&mut app, "s");
        assert!(app.review.notice.is_some(), "the person is told why");
        press(&mut app, "y");
        std::thread::sleep(Duration::from_millis(100));
        app.poll_review();
        assert_eq!(fake.calls(), vec!["load 30"]);
    }

    #[test]
    fn adding_a_note_calls_the_backend_then_reloads() {
        let fake = Arc::new(Fake::default());
        let mut app = ready_app(&fake);
        press(&mut app, "n");
        press(&mut app, "Well done");
        app.on_key(k(KeyCode::Enter));
        wait(&mut app, "add + reload", |_| fake.calls().len() >= 3);
        assert_eq!(
            fake.calls(),
            vec!["load 30", "add 2026-09-29 Well done", "load 30"]
        );
    }

    #[test]
    fn a_failed_note_shows_the_reason_and_does_not_reload() {
        let fake = Arc::new(Fake::default());
        *fake.fail_add.lock().unwrap() = Some("day must be within the last 90 days".into());
        let mut app = ready_app(&fake);
        press(&mut app, "n");
        press(&mut app, "x");
        app.on_key(k(KeyCode::Enter));
        wait(&mut app, "notice", |a| a.review.notice.is_some());
        assert_eq!(
            app.review.notice.as_deref(),
            Some("day must be within the last 90 days")
        );
        std::thread::sleep(Duration::from_millis(50));
        app.poll_review();
        assert_eq!(
            fake.calls(),
            vec!["load 30", "add 2026-09-29 x"],
            "no reload after a failure"
        );
    }

    #[test]
    fn deleting_a_note_calls_the_backend_then_reloads() {
        let fake = Arc::new(Fake::default());
        let mut app = ready_app(&fake);
        press(&mut app, "d");
        wait(&mut app, "delete + reload", |_| fake.calls().len() >= 3);
        assert_eq!(fake.calls(), vec!["load 30", "delete n1", "load 30"]);
    }

    #[test]
    fn the_window_key_reloads_with_the_new_window() {
        let fake = Arc::new(Fake::default());
        fake.outcome
            .lock()
            .unwrap()
            .insert(90, (0, Outcome::Ready(review("B"))));
        let mut app = ready_app(&fake);
        press(&mut app, "w");
        wait(
            &mut app,
            "the 90-day review",
            |a| matches!(&a.review.view, View::Ready(r) if r.name == "B"),
        );
        assert_eq!(fake.calls(), vec!["load 30", "load 90"]);
    }

    #[test]
    fn a_slow_old_answer_never_overwrites_a_newer_one() {
        let fake = Arc::new(Fake::default());
        fake.outcome
            .lock()
            .unwrap()
            .insert(30, (250, Outcome::Ready(review("SLOW-30"))));
        fake.outcome
            .lock()
            .unwrap()
            .insert(90, (0, Outcome::Ready(review("FAST-90"))));
        let mut app = app_with(&fake);
        press(&mut app, "v"); // the slow 30-day load starts
        press(&mut app, "w"); // …and the person moves on to 90 days
        wait(
            &mut app,
            "the fast answer",
            |a| matches!(&a.review.view, View::Ready(r) if r.name == "FAST-90"),
        );
        std::thread::sleep(Duration::from_millis(350)); // the slow one lands now
        app.poll_review();
        assert!(matches!(&app.review.view, View::Ready(r) if r.name == "FAST-90"));
    }

    #[test]
    fn a_company_without_work_review_is_told_nothing_is_collected() {
        let fake = Arc::new(Fake::default()); // default outcome: NotEnabled
        let mut app = app_with(&fake);
        press(&mut app, "v");
        wait(&mut app, "not enabled", |a| {
            a.review.view == View::NotEnabled
        });
        let mut term = ratatui::Terminal::new(ratatui::backend::TestBackend::new(110, 14)).unwrap();
        term.draw(|f| crate::ui::draw(f, &app)).unwrap();
        let buf = term.backend().buffer().clone();
        let screen: String = (0..14)
            .map(|y| {
                (0..110)
                    .map(|x| buf[(x, y)].symbol().to_string())
                    .collect::<String>()
            })
            .collect::<Vec<_>>()
            .join(" ");
        assert!(
            screen.contains("nothing is collected about you"),
            "{screen}"
        );
    }

    #[test]
    fn the_overlay_only_exists_while_open() {
        let fake = Arc::new(Fake::default());
        let mut app = ready_app(&fake);
        let draw = |app: &App| {
            let mut term =
                ratatui::Terminal::new(ratatui::backend::TestBackend::new(100, 24)).unwrap();
            term.draw(|f| crate::ui::draw(f, app)).unwrap();
            let buf = term.backend().buffer().clone();
            (0..24)
                .map(|y| {
                    (0..100)
                        .map(|x| buf[(x, y)].symbol().to_string())
                        .collect::<String>()
                })
                .collect::<Vec<_>>()
                .join("\n")
        };
        assert!(draw(&app).contains("My work review"));
        press(&mut app, "q");
        let closed = draw(&app);
        assert!(!closed.contains("My work review") && closed.contains("Agent session"));
    }
}
