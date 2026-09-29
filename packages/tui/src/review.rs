//! "My work review" (ADR-0019 §6): the person's own view of what work review holds
//! about them — the first thing that makes the person-first rule visible.
//!
//! It shows exactly what the backend's `GET /work-review/me` returns (the same view a
//! direct manager gets), what is collected and what never is, who can see it, and lets
//! the person annotate a day. When the company has not enabled work review it says
//! plainly that nothing is collected.
//!
//! The state machine is pure (keys in, `Action`s out), so it is tested without a
//! terminal or a network; `App` performs the actions on worker threads so a slow
//! server never freezes the screen.

use crate::api::Client;
use crate::i18n::{strings, Lang, T};
use crate::session::Session;
use anyhow::Result;
use ratatui::crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Wrap};
use ratatui::Frame;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::sync::mpsc::Sender;
use std::sync::Arc;

pub const WINDOWS: [u32; 3] = [7, 30, 90];
/// The backend's limit for a note.
pub const NOTE_MAX: usize = 1000;

// ── what the backend returns ──────────────────────────────────────────────────

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Note {
    pub id: String,
    pub text: String,
}

/// One fit rating of one piece of work (ADR-0021). `status` is `live` or `shadow`
/// (a trial period only the person sees).
#[derive(Debug, Clone, Deserialize, PartialEq, Default)]
pub struct RatingItem {
    pub id: String,
    pub criterion_id: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub verdict: String,
    #[serde(default)]
    pub contested: bool,
    #[serde(default)]
    pub resolved: bool,
    #[serde(default)]
    pub question: Option<String>,
}

/// Counts per criterion version — never a score.
#[derive(Debug, Clone, Deserialize, PartialEq, Default)]
pub struct RatingTotal {
    pub criterion_id: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub met: i64,
    #[serde(default)]
    pub not_met: i64,
    #[serde(default)]
    pub unclear: i64,
    #[serde(default)]
    pub contested: i64,
    #[serde(default)]
    pub question: Option<String>,
}

/// Where the person's own decided, live ratings suggest more support may help
/// (ADR-0021 §6). Shown only to the person; counts, never a score.
#[derive(Debug, Clone, Deserialize, PartialEq, Default)]
pub struct TrainingSignal {
    pub criterion_id: String,
    #[serde(default)]
    pub criterion_hash: String,
    #[serde(default)]
    pub rated: i64,
    #[serde(default)]
    pub not_met: i64,
    #[serde(default)]
    pub window_days: i64,
    /// Colleagues in the same department show the same pattern.
    #[serde(default)]
    pub unit_wide: bool,
    /// The person has chosen to share this one with their direct manager.
    #[serde(default)]
    pub shared: bool,
    #[serde(default)]
    pub question: Option<String>,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Default)]
pub struct DayEntry {
    pub day: String,
    #[serde(default)]
    pub signals: BTreeMap<String, i64>,
    #[serde(default)]
    pub tags: BTreeMap<String, BTreeMap<String, i64>>,
    #[serde(default)]
    pub notes: Vec<Note>,
    #[serde(default)]
    pub ratings: Vec<RatingItem>,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Default)]
pub struct Totals {
    #[serde(default)]
    pub signals: BTreeMap<String, i64>,
    #[serde(default)]
    pub tags: BTreeMap<String, BTreeMap<String, i64>>,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Default)]
pub struct Collected {
    #[serde(default)]
    pub signals: Vec<String>,
    #[serde(default)]
    pub tags: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Default)]
pub struct Disclosure {
    #[serde(default)]
    pub collected: Collected,
    #[serde(default)]
    pub never_collected: Vec<String>,
    #[serde(default)]
    pub visible_to: Vec<String>,
    #[serde(default)]
    pub minimum_group_size: i64,
    #[serde(default)]
    pub retention_days: i64,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Review {
    pub name: String,
    pub window_days: u32,
    #[serde(default)]
    pub days: Vec<DayEntry>,
    #[serde(default)]
    pub totals: Totals,
    #[serde(default)]
    pub ratings: Vec<RatingTotal>,
    #[serde(default)]
    pub training_need: Vec<TrainingSignal>,
    /// Whether the company lets people share a signal with their manager.
    #[serde(default)]
    pub training_sharing_enabled: bool,
    #[serde(default)]
    pub disclosure: Option<Disclosure>,
}

// One value per load, sent once through a channel: boxing the review would only
// complicate every use for no gain.
#[allow(clippy::large_enum_variant)]
#[derive(Debug, Clone, PartialEq)]
pub enum Outcome {
    Ready(Review),
    /// The company has not enabled work review: nothing is collected.
    NotEnabled,
    /// The account is not linked to a person record.
    NoPerson,
}

// ── state ─────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
// One value per load, as with `Outcome`.
#[allow(clippy::large_enum_variant)]
pub enum View {
    Loading,
    NotEnabled,
    NoPerson,
    Error(String),
    Ready(Review),
}

#[derive(Debug, Clone, PartialEq)]
pub enum Action {
    None,
    Close,
    Load,
    AddNote {
        day: String,
        text: String,
    },
    DeleteNote {
        id: String,
    },
    ContestRating {
        id: String,
        note: String,
    },
    WithdrawContest {
        id: String,
    },
    ShareSignal {
        criterion_id: String,
        criterion_hash: String,
    },
    UnshareSignal {
        criterion_id: String,
        criterion_hash: String,
    },
}

#[derive(Debug, Clone)]
pub struct ReviewState {
    pub open: bool,
    pub view: View,
    pub selected: usize,
    pub window: u32,
    /// The note being typed, if any.
    pub input: Option<String>,
    /// Set while the text being typed is the reason for contesting this rating,
    /// not a day note.
    pub contest_target: Option<String>,
    /// Which of the selected day's ratings is highlighted.
    pub sel_rating: usize,
    /// Which training signal `s` acts on.
    pub sel_signal: usize,
    /// A share waiting for the person's `y` (criterion id, hash).
    pub pending_share: Option<(String, String)>,
    /// Latest load request; answers to older ones are ignored.
    pub req_id: u64,
    pub notice: Option<String>,
}

impl Default for ReviewState {
    fn default() -> Self {
        Self {
            open: false,
            view: View::Loading,
            selected: 0,
            window: 30,
            input: None,
            contest_target: None,
            sel_rating: 0,
            sel_signal: 0,
            pending_share: None,
            req_id: 0,
            notice: None,
        }
    }
}

impl ReviewState {
    pub fn open(&mut self) -> Action {
        self.open = true;
        self.selected = 0;
        self.sel_rating = 0;
        self.sel_signal = 0;
        self.pending_share = None;
        self.input = None;
        self.contest_target = None;
        self.notice = None;
        Action::Load
    }

    /// Mark a load as started and return its id.
    pub fn begin_load(&mut self) -> u64 {
        self.req_id += 1;
        if !matches!(self.view, View::Ready(_)) {
            self.view = View::Loading;
        }
        self.req_id
    }

    pub fn apply_loaded(&mut self, id: u64, result: Result<Outcome, String>) {
        if id != self.req_id {
            return; // an answer to a request the person has already moved on from
        }
        self.view = match result {
            Ok(Outcome::Ready(r)) => View::Ready(r),
            Ok(Outcome::NotEnabled) => View::NotEnabled,
            Ok(Outcome::NoPerson) => View::NoPerson,
            Err(e) => View::Error(e),
        };
        let max = self.days().len().saturating_sub(1);
        self.selected = self.selected.min(max);
        self.sel_rating = self
            .sel_rating
            .min(self.day_ratings().len().saturating_sub(1));
        self.sel_signal = self.sel_signal.min(self.signals().len().saturating_sub(1));
        self.pending_share = None; // the ground moved: ask again rather than act on a stale question
    }

    /// After adding / deleting a note: reload on success, say why on failure.
    pub fn apply_saved(&mut self, result: Result<(), String>) -> Action {
        match result {
            Ok(()) => {
                self.notice = None;
                Action::Load
            }
            Err(e) => {
                self.notice = Some(e);
                Action::None
            }
        }
    }

    fn days(&self) -> &[DayEntry] {
        match &self.view {
            View::Ready(r) => &r.days,
            _ => &[],
        }
    }

    fn signals(&self) -> &[TrainingSignal] {
        match &self.view {
            View::Ready(r) => &r.training_need,
            _ => &[],
        }
    }

    fn sharing_enabled(&self) -> bool {
        matches!(&self.view, View::Ready(r) if r.training_sharing_enabled)
    }

    fn day_ratings(&self) -> &[RatingItem] {
        self.days()
            .get(self.selected)
            .map(|d| d.ratings.as_slice())
            .unwrap_or(&[])
    }

    fn selected_rating(&self) -> Option<&RatingItem> {
        self.day_ratings().get(self.sel_rating)
    }

    /// The day a new note goes on: the selected day, else today (UTC).
    fn note_day(&self) -> String {
        self.days()
            .get(self.selected)
            .map(|d| d.day.clone())
            .unwrap_or_else(today_utc)
    }

    pub fn on_key(&mut self, k: KeyEvent) -> Action {
        if let Some((criterion_id, criterion_hash)) = self.pending_share.take() {
            // Sharing tells someone else: only an explicit `y` does it.
            return if k.code == KeyCode::Char('y') {
                Action::ShareSignal {
                    criterion_id,
                    criterion_hash,
                }
            } else {
                Action::None
            };
        }
        if let Some(buf) = self.input.as_mut() {
            match k.code {
                KeyCode::Esc => {
                    self.input = None;
                    self.contest_target = None;
                }
                KeyCode::Enter => {
                    let text = buf.trim().to_string();
                    self.input = None;
                    let target = self.contest_target.take();
                    if !text.is_empty() {
                        return match target {
                            Some(id) => Action::ContestRating { id, note: text },
                            None => Action::AddNote {
                                day: self.note_day(),
                                text,
                            },
                        };
                    }
                }
                KeyCode::Backspace => {
                    buf.pop();
                }
                KeyCode::Char(c)
                    if !k
                        .modifiers
                        .intersects(KeyModifiers::CONTROL | KeyModifiers::ALT) =>
                {
                    if buf.chars().count() < NOTE_MAX {
                        buf.push(c);
                    }
                }
                _ => {}
            }
            return Action::None;
        }
        self.notice = None;
        let ready = matches!(self.view, View::Ready(_));
        match k.code {
            KeyCode::Esc | KeyCode::Char('v') | KeyCode::Char('q') => {
                self.open = false;
                Action::Close
            }
            KeyCode::Up | KeyCode::Char('k') => {
                self.selected = self.selected.saturating_sub(1);
                self.sel_rating = 0;
                Action::None
            }
            KeyCode::Down | KeyCode::Char('j') => {
                let max = self.days().len().saturating_sub(1);
                self.selected = (self.selected + 1).min(max);
                self.sel_rating = 0;
                Action::None
            }
            KeyCode::Left | KeyCode::Char('h') => {
                self.sel_rating = self.sel_rating.saturating_sub(1);
                Action::None
            }
            KeyCode::Right | KeyCode::Char('l') => {
                let max = self.day_ratings().len().saturating_sub(1);
                self.sel_rating = (self.sel_rating + 1).min(max);
                Action::None
            }
            KeyCode::Char('c') if ready => {
                let target = self
                    .selected_rating()
                    .filter(|r| !r.contested)
                    .map(|r| r.id.clone());
                if let Some(id) = target {
                    self.contest_target = Some(id);
                    self.input = Some(String::new());
                }
                Action::None
            }
            KeyCode::Char('t') if ready => {
                let n = self.signals().len();
                if n > 0 {
                    self.sel_signal = (self.sel_signal + 1) % n;
                }
                Action::None
            }
            KeyCode::Char('s') if ready => {
                let Some(sig) = self.signals().get(self.sel_signal).cloned() else {
                    return Action::None;
                };
                if sig.shared {
                    return Action::UnshareSignal {
                        criterion_id: sig.criterion_id,
                        criterion_hash: sig.criterion_hash,
                    };
                }
                if !self.sharing_enabled() {
                    self.notice = Some(strings(Lang::En).rv_sharing_off.to_string());
                    return Action::None;
                }
                self.pending_share = Some((sig.criterion_id, sig.criterion_hash));
                Action::None
            }
            KeyCode::Char('u') if ready => self
                .selected_rating()
                .filter(|r| r.contested)
                .map(|r| Action::WithdrawContest { id: r.id.clone() })
                .unwrap_or(Action::None),
            KeyCode::Char('w') => {
                let i = WINDOWS.iter().position(|w| *w == self.window).unwrap_or(0);
                self.window = WINDOWS[(i + 1) % WINDOWS.len()];
                self.selected = 0;
                self.sel_rating = 0;
                Action::Load
            }
            KeyCode::Char('r') => Action::Load,
            KeyCode::Char('n') if ready => {
                self.input = Some(String::new());
                Action::None
            }
            KeyCode::Char('d') if ready => self
                .days()
                .get(self.selected)
                .and_then(|d| d.notes.last())
                .map(|n| Action::DeleteNote { id: n.id.clone() })
                .unwrap_or(Action::None),
            _ => Action::None,
        }
    }
}

// ── today (UTC) without a date crate ──────────────────────────────────────────

/// `YYYY-MM-DD` for a count of days since 1970-01-01 (Howard Hinnant's algorithm).
pub fn civil_from_days(days: i64) -> String {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!("{y:04}-{m:02}-{d:02}")
}

pub fn today_utc() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    civil_from_days(secs.div_euclid(86_400))
}

// ── talking to the backend, off the UI thread ─────────────────────────────────

pub trait Backend: Send + Sync + 'static {
    fn load(&self, days: u32) -> Result<Outcome>;
    fn add_note(&self, day: &str, text: &str) -> Result<()>;
    fn delete_note(&self, id: &str) -> Result<()>;
    fn contest_rating(&self, id: &str, note: &str) -> Result<()>;
    fn withdraw_contest(&self, id: &str) -> Result<()>;
    fn share_signal(&self, criterion_id: &str, criterion_hash: &str) -> Result<()>;
    fn unshare_signal(&self, criterion_id: &str, criterion_hash: &str) -> Result<()>;
}

pub struct Http {
    pub session: Session,
}

impl Http {
    fn client(&self) -> Result<(Client, String)> {
        let c = Client::new(self.session.clone());
        let company = c.first_company_id()?;
        Ok((c, company))
    }
}

impl Backend for Http {
    fn load(&self, days: u32) -> Result<Outcome> {
        let (c, co) = self.client()?;
        c.work_review(&co, days)
    }
    fn add_note(&self, day: &str, text: &str) -> Result<()> {
        let (c, co) = self.client()?;
        c.add_work_note(&co, day, text)
    }
    fn delete_note(&self, id: &str) -> Result<()> {
        let (c, co) = self.client()?;
        c.delete_work_note(&co, id)
    }
    fn contest_rating(&self, id: &str, note: &str) -> Result<()> {
        let (c, co) = self.client()?;
        c.contest_work_rating(&co, id, note)
    }
    fn withdraw_contest(&self, id: &str) -> Result<()> {
        let (c, co) = self.client()?;
        c.withdraw_work_rating_contest(&co, id)
    }
    fn share_signal(&self, criterion_id: &str, criterion_hash: &str) -> Result<()> {
        let (c, co) = self.client()?;
        c.share_training_signal(&co, criterion_id, criterion_hash)
    }
    fn unshare_signal(&self, criterion_id: &str, criterion_hash: &str) -> Result<()> {
        let (c, co) = self.client()?;
        c.withdraw_training_share(&co, criterion_id, criterion_hash)
    }
}

#[derive(Debug)]
#[allow(clippy::large_enum_variant)]
pub enum Msg {
    Loaded(u64, Result<Outcome, String>),
    Saved(Result<(), String>),
}

fn err(e: anyhow::Error) -> String {
    format!("{e:#}")
}

pub fn spawn_load(b: Arc<dyn Backend>, tx: Sender<Msg>, id: u64, days: u32) {
    std::thread::spawn(move || {
        let _ = tx.send(Msg::Loaded(id, b.load(days).map_err(err)));
    });
}

pub fn spawn_add_note(b: Arc<dyn Backend>, tx: Sender<Msg>, day: String, text: String) {
    std::thread::spawn(move || {
        let _ = tx.send(Msg::Saved(b.add_note(&day, &text).map_err(err)));
    });
}

pub fn spawn_delete_note(b: Arc<dyn Backend>, tx: Sender<Msg>, id: String) {
    std::thread::spawn(move || {
        let _ = tx.send(Msg::Saved(b.delete_note(&id).map_err(err)));
    });
}

pub fn spawn_contest(b: Arc<dyn Backend>, tx: Sender<Msg>, id: String, note: String) {
    std::thread::spawn(move || {
        let _ = tx.send(Msg::Saved(b.contest_rating(&id, &note).map_err(err)));
    });
}

pub fn spawn_share_signal(b: Arc<dyn Backend>, tx: Sender<Msg>, crit: String, hash: String) {
    std::thread::spawn(move || {
        let _ = tx.send(Msg::Saved(b.share_signal(&crit, &hash).map_err(err)));
    });
}

pub fn spawn_unshare_signal(b: Arc<dyn Backend>, tx: Sender<Msg>, crit: String, hash: String) {
    std::thread::spawn(move || {
        let _ = tx.send(Msg::Saved(b.unshare_signal(&crit, &hash).map_err(err)));
    });
}

pub fn spawn_withdraw_contest(b: Arc<dyn Backend>, tx: Sender<Msg>, id: String) {
    std::thread::spawn(move || {
        let _ = tx.send(Msg::Saved(b.withdraw_contest(&id).map_err(err)));
    });
}

// ── rendering ─────────────────────────────────────────────────────────────────

fn signal_label<'a>(kind: &'a str, t: &'a T) -> &'a str {
    match kind {
        "policy_denied" => t.rv_policy_denied,
        "approval_asked" => t.rv_approval_asked,
        "policy_would_deny" => t.rv_policy_would_deny,
        "policy_would_ask" => t.rv_policy_would_ask,
        other => other, // a kind newer than this client: show it as it is
    }
}

fn tag_label<'a>(kind: &'a str, t: &'a T) -> &'a str {
    match kind {
        "task" => t.rv_tag_task,
        "sensitivity" => t.rv_tag_sensitivity,
        "domain" => t.rv_tag_domain,
        other => other,
    }
}

fn fill(template: &str, key: &str, value: impl std::fmt::Display) -> String {
    template.replace(key, &value.to_string())
}

fn signals_lines(signals: &BTreeMap<String, i64>, t: &T, indent: &str) -> Vec<Line<'static>> {
    // Fixed order for the known kinds; anything newer follows alphabetically.
    let order = [
        "policy_denied",
        "approval_asked",
        "policy_would_deny",
        "policy_would_ask",
    ];
    let mut kinds: Vec<&String> = signals.keys().collect();
    kinds.sort_by_key(|k| {
        (
            order
                .iter()
                .position(|o| o == &k.as_str())
                .unwrap_or(order.len()),
            (*k).clone(),
        )
    });
    kinds
        .into_iter()
        .map(|k| Line::from(format!("{indent}{}: {}", signal_label(k, t), signals[k])))
        .collect()
}

fn tags_lines(
    tags: &BTreeMap<String, BTreeMap<String, i64>>,
    t: &T,
    indent: &str,
) -> Vec<Line<'static>> {
    tags.iter()
        .map(|(kind, values)| {
            let mut v: Vec<(&String, &i64)> = values.iter().collect();
            v.sort_by(|a, b| b.1.cmp(a.1).then(a.0.cmp(b.0)));
            let list = v
                .iter()
                .map(|(name, n)| format!("{name} {n}"))
                .collect::<Vec<_>>()
                .join(" · ");
            Line::from(format!("{indent}{}: {list}", tag_label(kind, t)))
        })
        .collect()
}

fn status_label<'a>(status: &'a str, t: &'a T) -> &'a str {
    match status {
        "shadow" => t.rv_shadow,
        "live" => t.rv_live,
        other => other,
    }
}

fn verdict_label<'a>(verdict: &'a str, t: &'a T) -> &'a str {
    match verdict {
        "met" => t.rv_met,
        "not_met" => t.rv_not_met,
        "unclear" => t.rv_unclear,
        other => other,
    }
}

/// Counts per criterion. Deliberately no score and no average.
pub fn rating_totals_lines(r: &Review, t: &T) -> Vec<Line<'static>> {
    if r.ratings.is_empty() {
        return Vec::new();
    }
    let mut lines = vec![Line::styled(
        format!("  {}", t.rv_ratings),
        Style::default().add_modifier(Modifier::UNDERLINED),
    )];
    for e in &r.ratings {
        let name = e.question.clone().unwrap_or_else(|| e.criterion_id.clone());
        let contested = if e.contested > 0 {
            format!(" · {} {}", e.contested, t.rv_contested)
        } else {
            String::new()
        };
        lines.push(Line::from(format!(
            "    {name} [{}]: {} {} · {} {} · {} {}{contested}",
            status_label(&e.status, t),
            e.met,
            t.rv_met,
            e.not_met,
            t.rv_not_met,
            e.unclear,
            t.rv_unclear
        )));
    }
    lines
}

/// The person's own training-need signals: plain counts, a supportive framing, and a
/// note that nobody else sees them.
pub fn training_lines(r: &Review, t: &T, sel: usize) -> Vec<Line<'static>> {
    if r.training_need.is_empty() {
        return Vec::new();
    }
    let mut lines = vec![Line::styled(
        format!("  {} ({})", t.rv_training, t.rv_training_only_you),
        Style::default().add_modifier(Modifier::UNDERLINED),
    )];
    for (i, e) in r.training_need.iter().enumerate() {
        let name = e.question.clone().unwrap_or_else(|| e.criterion_id.clone());
        let counts = fill(
            &fill(&fill(t.rv_training_line, "{m}", e.not_met), "{n}", e.rated),
            "{d}",
            e.window_days,
        );
        let mark = if i == sel { "▸" } else { " " };
        lines.push(Line::from(format!("  {mark} {name}: {counts}")));
        if e.unit_wide {
            lines.push(Line::styled(
                format!("      {}", t.rv_training_unit_wide),
                Style::default().fg(Color::DarkGray),
            ));
        }
        let share = if e.shared {
            t.rv_share_on
        } else if r.training_sharing_enabled {
            t.rv_share_can
        } else {
            t.rv_share_none
        };
        lines.push(Line::styled(
            format!("      {share}"),
            Style::default().fg(Color::DarkGray),
        ));
    }
    lines
}

pub fn totals_lines(r: &Review, t: &T) -> Vec<Line<'static>> {
    totals_lines_sel(r, t, 0)
}

pub fn totals_lines_sel(r: &Review, t: &T, sel_signal: usize) -> Vec<Line<'static>> {
    let mut lines = signals_lines(&r.totals.signals, t, "  ");
    lines.extend(tags_lines(&r.totals.tags, t, "  "));
    if lines.is_empty() && r.ratings.is_empty() {
        lines.push(Line::styled(
            format!("  {}", t.rv_nothing),
            Style::default().fg(Color::DarkGray),
        ));
    }
    lines.extend(rating_totals_lines(r, t));
    lines.extend(training_lines(r, t, sel_signal));
    lines
}

pub fn day_row(d: &DayEntry, selected: bool) -> Line<'static> {
    let denied = d.signals.get("policy_denied").copied().unwrap_or(0);
    let asked = d.signals.get("approval_asked").copied().unwrap_or(0);
    let mark = format!(
        "{}{}",
        if d.notes.is_empty() { "" } else { " ✎" },
        if d.ratings.iter().any(|r| r.contested) {
            " !"
        } else {
            ""
        }
    );
    let text = format!(
        "{} {}  ✗{denied} ⧗{asked}{mark}",
        if selected { "▸" } else { " " },
        d.day
    );
    if selected {
        Line::styled(text, Style::default().add_modifier(Modifier::BOLD))
    } else {
        Line::from(text)
    }
}

pub fn rating_line(r: &RatingItem, selected: bool, t: &T) -> Line<'static> {
    let name = r.question.clone().unwrap_or_else(|| r.criterion_id.clone());
    let mut tail = String::new();
    if r.contested {
        tail.push_str(&format!(" · {}", t.rv_contested));
    } else if r.resolved {
        tail.push_str(&format!(" · {}", t.rv_resolved));
    }
    let text = format!(
        "{} {name} [{}]: {}{tail}",
        if selected { "▸" } else { " " },
        status_label(&r.status, t),
        verdict_label(&r.verdict, t)
    );
    if selected {
        Line::styled(text, Style::default().add_modifier(Modifier::BOLD))
    } else {
        Line::from(text)
    }
}

pub fn detail_lines(d: &DayEntry, t: &T, sel_rating: usize) -> Vec<Line<'static>> {
    let mut lines = vec![Line::styled(
        d.day.clone(),
        Style::default().add_modifier(Modifier::BOLD),
    )];
    lines.extend(signals_lines(&d.signals, t, "  "));
    lines.extend(tags_lines(&d.tags, t, "  "));
    if !d.ratings.is_empty() {
        lines.push(Line::styled(
            t.rv_ratings.to_string(),
            Style::default().add_modifier(Modifier::UNDERLINED),
        ));
        for (i, r) in d.ratings.iter().enumerate() {
            lines.push(rating_line(r, i == sel_rating, t));
        }
        if d.ratings.iter().any(|r| r.status == "shadow") {
            lines.push(Line::styled(
                format!("  {}", t.rv_shadow_hint),
                Style::default().fg(Color::DarkGray),
            ));
        }
    }
    lines.push(Line::styled(
        t.rv_notes.to_string(),
        Style::default().add_modifier(Modifier::UNDERLINED),
    ));
    if d.notes.is_empty() {
        lines.push(Line::styled(
            format!("  {}", t.rv_no_notes),
            Style::default().fg(Color::DarkGray),
        ));
    }
    for n in &d.notes {
        lines.push(Line::from(format!("  ✎ {}", n.text)));
    }
    lines
}

pub fn disclosure_lines(d: &Disclosure, t: &T) -> Vec<Line<'static>> {
    let mut lines = vec![Line::styled(
        t.rv_what.to_string(),
        Style::default().add_modifier(Modifier::UNDERLINED),
    )];
    let collected: Vec<String> = d
        .collected
        .signals
        .iter()
        .map(|k| signal_label(k, t).to_string())
        .chain(d.collected.tags.iter().map(|k| tag_label(k, t).to_string()))
        .collect();
    lines.push(Line::from(format!(
        "{}: {}",
        t.rv_collected,
        collected.join(", ")
    )));
    lines.push(Line::from(format!(
        "{}: {}",
        t.rv_never,
        d.never_collected.join(", ")
    )));
    for v in &d.visible_to {
        lines.push(Line::from(format!("• {v}")));
    }
    lines.push(Line::from(format!(
        "{} · {}",
        fill(t.rv_group, "{n}", d.minimum_group_size),
        fill(t.rv_retention, "{n}", d.retention_days)
    )));
    lines
}

fn message(f: &mut Frame, area: Rect, text: String, style: Style) {
    f.render_widget(
        Paragraph::new(text).wrap(Wrap { trim: true }).style(style),
        area,
    );
}

pub fn draw(f: &mut Frame, area: Rect, s: &ReviewState, lang: Lang) {
    let t = strings(lang);
    f.render_widget(Clear, area);
    let name = match &s.view {
        View::Ready(r) => format!(" — {}", r.name),
        _ => String::new(),
    };
    let title = format!(
        " {}{name} · {} ",
        t.rv_title,
        fill(t.rv_last_days, "{n}", s.window)
    );
    let block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(Color::Cyan))
        .title(title);
    let inner = block.inner(area);
    f.render_widget(block, area);
    let [body, bottom] = Layout::vertical([Constraint::Min(3), Constraint::Length(1)]).areas(inner);

    match &s.view {
        View::Loading => message(
            f,
            body,
            t.rv_loading.into(),
            Style::default().fg(Color::DarkGray),
        ),
        View::NotEnabled => message(f, body, t.rv_not_enabled.into(), Style::default()),
        View::NoPerson => message(f, body, t.rv_no_person.into(), Style::default()),
        View::Error(e) => message(
            f,
            body,
            format!("{}: {e}", t.rv_error),
            Style::default().fg(Color::Red),
        ),
        View::Ready(r) => draw_ready(f, body, r, s, &t),
    }

    let line = if s.pending_share.is_some() {
        Line::styled(
            format!(" {}", t.rv_share_confirm),
            Style::default().fg(Color::Yellow),
        )
    } else if let Some(buf) = &s.input {
        let prompt = match &s.contest_target {
            Some(id) => {
                let name = s
                    .day_ratings()
                    .iter()
                    .find(|r| &r.id == id)
                    .map(|r| r.question.clone().unwrap_or_else(|| r.criterion_id.clone()))
                    .unwrap_or_default();
                fill(t.rv_contest_for, "{c}", name)
            }
            None => fill(t.rv_note_for, "{day}", s.note_day()),
        };
        Line::from(vec![
            Span::styled(format!("{prompt}: "), Style::default().fg(Color::Cyan)),
            Span::raw(format!("{buf}▏")),
            Span::styled(
                format!("   {}", t.rv_note_hint),
                Style::default().add_modifier(Modifier::DIM),
            ),
        ])
    } else if let Some(n) = &s.notice {
        Line::styled(
            format!(" {}: {n}", t.rv_error),
            Style::default().fg(Color::Red),
        )
    } else {
        Line::styled(
            t.rv_keys.to_string(),
            Style::default().add_modifier(Modifier::DIM),
        )
    };
    f.render_widget(Paragraph::new(line), bottom);
}

fn draw_ready(f: &mut Frame, area: Rect, r: &Review, s: &ReviewState, t: &T) {
    let disclosure = r.disclosure.as_ref().map(|d| disclosure_lines(d, t));
    let dh = disclosure.as_ref().map(|l| l.len() as u16 + 1).unwrap_or(0);
    let [totals, mid, foot] = Layout::vertical([
        Constraint::Length((totals_lines(r, t).len() as u16 + 2).min(14)),
        Constraint::Min(4),
        Constraint::Length(dh.min(10)),
    ])
    .areas(area);

    f.render_widget(
        Paragraph::new(totals_lines_sel(r, t, s.sel_signal)).block(
            Block::default()
                .borders(Borders::BOTTOM)
                .title(format!(" {} ", t.rv_totals)),
        ),
        totals,
    );

    let [list, detail] =
        Layout::horizontal([Constraint::Length(26), Constraint::Min(10)]).areas(mid);
    if r.days.is_empty() {
        message(
            f,
            mid,
            format!(" {}", t.rv_nothing),
            Style::default().fg(Color::DarkGray),
        );
    } else {
        // Keep the selected day in view.
        let h = list.height.saturating_sub(1) as usize;
        let top = s.selected.saturating_sub(h.saturating_sub(1));
        let rows: Vec<Line> = r
            .days
            .iter()
            .enumerate()
            .skip(top)
            .take(h.max(1))
            .map(|(i, d)| day_row(d, i == s.selected))
            .collect();
        f.render_widget(
            Paragraph::new(rows).block(
                Block::default()
                    .borders(Borders::RIGHT)
                    .title(format!(" {} ", t.rv_days)),
            ),
            list,
        );
        if let Some(d) = r.days.get(s.selected) {
            f.render_widget(
                Paragraph::new(detail_lines(d, t, s.sel_rating)).wrap(Wrap { trim: false }),
                detail,
            );
        }
    }

    if let Some(lines) = disclosure {
        f.render_widget(
            Paragraph::new(lines)
                .wrap(Wrap { trim: true })
                .block(Block::default().borders(Borders::TOP)),
            foot,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::backend::TestBackend;
    use ratatui::Terminal;

    fn key(c: KeyCode) -> KeyEvent {
        KeyEvent::new(c, KeyModifiers::NONE)
    }
    fn ch(c: char) -> KeyEvent {
        key(KeyCode::Char(c))
    }

    fn day(d: &str, denied: i64, notes: &[(&str, &str)]) -> DayEntry {
        let mut signals = BTreeMap::new();
        if denied > 0 {
            signals.insert("policy_denied".to_string(), denied);
        }
        DayEntry {
            day: d.into(),
            signals,
            tags: BTreeMap::new(),
            notes: notes
                .iter()
                .map(|(id, t)| Note {
                    id: (*id).into(),
                    text: (*t).into(),
                })
                .collect(),
            ratings: vec![],
        }
    }

    fn review() -> Review {
        let mut totals = Totals::default();
        totals.signals.insert("policy_denied".into(), 3);
        totals.signals.insert("approval_asked".into(), 1);
        totals.signals.insert("policy_would_deny".into(), 2);
        totals
            .tags
            .entry("task".into())
            .or_default()
            .extend([("analysis".to_string(), 4), ("lookup".to_string(), 1)]);
        Review {
            name: "Ayşe".into(),
            window_days: 30,
            days: vec![
                day("2026-09-29", 2, &[("n1", "first"), ("n2", "second")]),
                day("2026-09-28", 1, &[]),
            ],
            totals,
            ratings: vec![],
            training_need: vec![],
            training_sharing_enabled: false,
            disclosure: Some(Disclosure {
                collected: Collected {
                    signals: vec!["policy_denied".into(), "approval_asked".into()],
                    tags: vec!["task".into()],
                },
                never_collected: vec!["keystrokes".into(), "screenshots".into()],
                visible_to: vec![
                    "you, in full".into(),
                    "your direct manager, the same per-person view you see".into(),
                ],
                minimum_group_size: 3,
                retention_days: 365,
            }),
        }
    }

    fn ready() -> ReviewState {
        let mut s = ReviewState::default();
        s.open();
        let id = s.begin_load();
        s.apply_loaded(id, Ok(Outcome::Ready(review())));
        s
    }

    fn text(lines: &[Line]) -> String {
        lines
            .iter()
            .map(|l| l.to_string())
            .collect::<Vec<_>>()
            .join("\n")
    }

    fn screen(s: &ReviewState, lang: Lang, w: u16, h: u16) -> String {
        let mut term = Terminal::new(TestBackend::new(w, h)).unwrap();
        term.draw(|f| draw(f, f.area(), s, lang)).unwrap();
        let buf = term.backend().buffer().clone();
        (0..h)
            .map(|y| {
                (0..w)
                    .map(|x| buf[(x, y)].symbol().to_string())
                    .collect::<String>()
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    // ── dates ─────────────────────────────────────────────────────────────────

    #[test]
    fn civil_dates_including_leap_days_and_the_century_edge() {
        for (days, want) in [
            (0, "1970-01-01"),
            (59, "1970-03-01"),
            (11016, "2000-02-29"),
            (19782, "2024-02-29"),
            (19783, "2024-03-01"),
            (20000, "2024-10-04"),
            (47482, "2100-01-01"),
        ] {
            assert_eq!(civil_from_days(days), want, "day {days}");
        }
        let t = today_utc();
        assert_eq!(t.len(), 10);
        assert!(t.as_str() >= "2026-01-01");
    }

    // ── parsing ───────────────────────────────────────────────────────────────

    #[test]
    fn parses_the_backends_shape_and_tolerates_missing_and_extra_fields() {
        let full = r#"{"personnel_id":"p","name":"Ayşe","window_days":30,
            "days":[{"day":"2026-09-29","signals":{"policy_denied":2},"tags":{"task":{"analysis":1}},
                     "notes":[{"id":"n","text":"hi","created_at":"2026-09-29T10:00:00"}]}],
            "totals":{"signals":{"policy_denied":2},"tags":{"task":{"analysis":1}}},
            "disclosure":{"collected":{"signals":["policy_denied"],"tags":["task"]},
              "never_collected":["keystrokes"],"visible_to":["you"],
              "minimum_group_size":3,"retention_days":365,"future_field":true}}"#;
        let r: Review = serde_json::from_str(full).unwrap();
        assert_eq!(r.days[0].notes[0].text, "hi");
        assert_eq!(r.disclosure.unwrap().retention_days, 365);
        let bare: Review = serde_json::from_str(r#"{"name":"A","window_days":7}"#).unwrap();
        assert!(bare.days.is_empty() && bare.disclosure.is_none());
    }

    // ── keys ──────────────────────────────────────────────────────────────────

    #[test]
    fn opening_asks_for_a_load_and_closing_leaves() {
        let mut s = ReviewState::default();
        assert_eq!(s.open(), Action::Load);
        assert!(s.open);
        for k in [KeyCode::Esc, KeyCode::Char('v'), KeyCode::Char('q')] {
            s.open = true;
            assert_eq!(s.on_key(key(k)), Action::Close);
            assert!(!s.open);
        }
    }

    #[test]
    fn selection_moves_within_the_days_and_clamps() {
        let mut s = ready();
        assert_eq!(s.selected, 0);
        s.on_key(key(KeyCode::Up));
        assert_eq!(s.selected, 0);
        s.on_key(ch('j'));
        s.on_key(key(KeyCode::Down));
        s.on_key(key(KeyCode::Down));
        assert_eq!(s.selected, 1, "two days: never past the last");
        s.on_key(ch('k'));
        assert_eq!(s.selected, 0);
    }

    #[test]
    fn the_window_cycles_and_reloads() {
        let mut s = ready();
        s.selected = 1;
        let mut seen = vec![s.window];
        for _ in 0..3 {
            assert_eq!(s.on_key(ch('w')), Action::Load);
            seen.push(s.window);
        }
        assert_eq!(seen, vec![30, 90, 7, 30]);
        assert_eq!(s.selected, 0);
        assert_eq!(s.on_key(ch('r')), Action::Load);
    }

    #[test]
    fn notes_can_only_be_added_or_deleted_once_a_review_is_shown() {
        let mut s = ReviewState::default();
        s.open();
        assert_eq!(s.on_key(ch('n')), Action::None);
        assert!(s.input.is_none());
        assert_eq!(s.on_key(ch('d')), Action::None);
        s.view = View::NotEnabled;
        assert_eq!(s.on_key(ch('n')), Action::None);
    }

    #[test]
    fn typing_a_note_saves_it_on_the_selected_day() {
        let mut s = ready();
        s.on_key(ch('j')); // 2026-09-28
        s.on_key(ch('n'));
        for c in "  fix me  ".chars() {
            s.on_key(ch(c));
        }
        s.on_key(key(KeyCode::Backspace));
        assert_eq!(s.input.as_deref(), Some("  fix me "));
        assert_eq!(
            s.on_key(key(KeyCode::Enter)),
            Action::AddNote {
                day: "2026-09-28".into(),
                text: "fix me".into()
            }
        );
        assert!(s.input.is_none());
    }

    #[test]
    fn a_note_with_no_days_goes_on_today() {
        let mut s = ReviewState::default();
        s.open();
        let id = s.begin_load();
        s.apply_loaded(
            id,
            Ok(Outcome::Ready(Review {
                days: vec![],
                ..review()
            })),
        );
        s.on_key(ch('n'));
        s.on_key(ch('x'));
        match s.on_key(key(KeyCode::Enter)) {
            Action::AddNote { day, .. } => assert_eq!(day, today_utc()),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn note_input_rules() {
        let mut s = ready();
        // an empty or blank note is not saved, and Esc cancels
        s.on_key(ch('n'));
        s.on_key(ch(' '));
        assert_eq!(s.on_key(key(KeyCode::Enter)), Action::None);
        assert!(s.input.is_none());
        s.on_key(ch('n'));
        s.on_key(ch('a'));
        assert_eq!(s.on_key(key(KeyCode::Esc)), Action::None);
        assert!(
            s.input.is_none() && s.open,
            "Esc cancels the note, it does not close the view"
        );
        // keys that are commands elsewhere are just text here
        s.on_key(ch('n'));
        for c in ['q', 'v', 'w', 'd', 'n'] {
            assert_eq!(s.on_key(ch(c)), Action::None);
        }
        assert_eq!(s.input.as_deref(), Some("qvwdn"));
        // control / alt combinations are not text
        s.on_key(KeyEvent::new(KeyCode::Char('z'), KeyModifiers::CONTROL));
        s.on_key(KeyEvent::new(KeyCode::Char('z'), KeyModifiers::ALT));
        assert_eq!(s.input.as_deref(), Some("qvwdn"));
        // the backend's length limit
        s.input = Some("é".repeat(NOTE_MAX));
        s.on_key(ch('x'));
        assert_eq!(s.input.as_ref().unwrap().chars().count(), NOTE_MAX);
    }

    #[test]
    fn delete_removes_the_newest_note_of_the_selected_day() {
        let mut s = ready();
        assert_eq!(s.on_key(ch('d')), Action::DeleteNote { id: "n2".into() });
        s.on_key(ch('j')); // a day without notes
        assert_eq!(s.on_key(ch('d')), Action::None);
    }

    // ── answers ───────────────────────────────────────────────────────────────

    #[test]
    fn answers_to_superseded_requests_are_ignored() {
        let mut s = ReviewState::default();
        s.open();
        let old = s.begin_load();
        let new = s.begin_load();
        s.apply_loaded(old, Ok(Outcome::Ready(review())));
        assert_eq!(
            s.view,
            View::Loading,
            "a late answer to an old request must not show"
        );
        s.apply_loaded(new, Ok(Outcome::NotEnabled));
        assert_eq!(s.view, View::NotEnabled);
    }

    #[test]
    fn a_reload_keeps_the_screen_and_the_selection_when_possible() {
        let mut s = ready();
        s.on_key(ch('j'));
        let id = s.begin_load();
        assert!(
            matches!(s.view, View::Ready(_)),
            "no flash of 'Loading' on a reload"
        );
        let mut shorter = review();
        shorter.days.truncate(1);
        s.apply_loaded(id, Ok(Outcome::Ready(shorter)));
        assert_eq!(s.selected, 0, "clamped into the new, shorter list");
    }

    #[test]
    fn every_outcome_and_error_has_a_view() {
        let mut s = ReviewState::default();
        for (res, want) in [
            (Ok(Outcome::NotEnabled), View::NotEnabled),
            (Ok(Outcome::NoPerson), View::NoPerson),
            (Err("boom".to_string()), View::Error("boom".into())),
        ] {
            let id = s.begin_load();
            s.apply_loaded(id, res);
            assert_eq!(s.view, want);
        }
    }

    #[test]
    fn a_saved_note_reloads_and_a_failed_one_says_why() {
        let mut s = ready();
        assert_eq!(s.apply_saved(Ok(())), Action::Load);
        assert_eq!(
            s.apply_saved(Err("day must be within the last 90 days".into())),
            Action::None
        );
        assert_eq!(
            s.notice.as_deref(),
            Some("day must be within the last 90 days")
        );
        s.on_key(ch('r'));
        assert!(s.notice.is_none(), "the next key clears the notice");
    }

    // ── what is drawn ─────────────────────────────────────────────────────────

    #[test]
    fn totals_and_day_detail_read_plainly() {
        let t = strings(Lang::En);
        let totals = text(&totals_lines(&review(), &t));
        for want in [
            "Policy refusals: 3",
            "Approvals asked: 1",
            "Would-be refusals (rules only observed): 2",
            "Kinds of work: analysis 4 · lookup 1",
        ] {
            assert!(totals.contains(want), "{want}\n{totals}");
        }
        assert!(totals.find("Policy refusals").unwrap() < totals.find("Would-be").unwrap());
        let d = text(&detail_lines(&review().days[0], &t, 0));
        assert!(d.contains("2026-09-29") && d.contains("✎ first") && d.contains("✎ second"));
        let empty = text(&detail_lines(&review().days[1], &t, 0));
        assert!(empty.contains("no notes — press n to add one"));
        assert_eq!(
            day_row(&review().days[0], true).to_string(),
            "▸ 2026-09-29  ✗2 ⧗0 ✎"
        );
        assert_eq!(
            day_row(&review().days[1], false).to_string(),
            "  2026-09-28  ✗1 ⧗0"
        );
        let none = text(&totals_lines(
            &Review {
                totals: Totals::default(),
                ..review()
            },
            &t,
        ));
        assert!(none.contains("Nothing recorded in this window."));
    }

    #[test]
    fn an_unknown_future_signal_is_shown_not_hidden() {
        let t = strings(Lang::En);
        let mut r = review();
        r.totals.signals.insert("brand_new_signal".into(), 7);
        assert!(text(&totals_lines(&r, &t)).contains("brand_new_signal: 7"));
    }

    #[test]
    fn the_disclosure_uses_the_servers_numbers_and_words() {
        let t = strings(Lang::En);
        let d = text(&disclosure_lines(review().disclosure.as_ref().unwrap(), &t));
        for want in [
            "Collected: Policy refusals, Approvals asked, Kinds of work",
            "Never collected: keystrokes, screenshots",
            "• you, in full",
            "• your direct manager, the same per-person view you see",
            "Groups smaller than 3 people are never shown",
            "Kept for 365 days",
        ] {
            assert!(d.contains(want), "{want}\n{d}");
        }
    }

    #[test]
    fn every_view_draws_in_both_languages() {
        for lang in [Lang::En, Lang::Tr] {
            let t = strings(lang);
            let mut s = ready();
            let full = screen(&s, lang, 100, 30);
            assert!(full.contains(t.rv_title) && full.contains("Ayşe"));
            assert!(full.contains("2026-09-29") && full.contains(t.rv_keys.trim()));
            for (view, want) in [
                (View::Loading, t.rv_loading.to_string()),
                (View::NotEnabled, t.rv_not_enabled.to_string()),
                (View::NoPerson, t.rv_no_person.to_string()),
                (View::Error("boom".into()), format!("{}: boom", t.rv_error)),
            ] {
                s.view = view;
                let out = screen(&s, lang, 110, 12).replace('\n', " ");
                let squashed = out.split_whitespace().collect::<Vec<_>>().join(" ");
                let first_words = want
                    .split_whitespace()
                    .take(4)
                    .collect::<Vec<_>>()
                    .join(" ");
                assert!(
                    squashed.contains(&first_words),
                    "{lang:?}: {first_words}\n{squashed}"
                );
            }
        }
    }

    #[test]
    fn typing_shows_the_note_prompt_and_a_failure_shows_the_reason() {
        let mut s = ready();
        s.on_key(ch('j'));
        s.on_key(ch('n'));
        s.on_key(ch('h'));
        s.on_key(ch('i'));
        let out = screen(&s, Lang::En, 100, 30);
        assert!(out.contains("Note for 2026-09-28: hi▏"), "{out}");
        assert!(out.contains("Enter save · Esc cancel"));
        s.input = None;
        s.notice = Some("nope".into());
        assert!(screen(&s, Lang::En, 100, 30).contains("Could not load: nope"));
    }

    #[test]
    fn a_long_history_keeps_the_selected_day_visible_on_a_small_screen() {
        let mut r = review();
        r.days = (1..=40)
            .map(|i| day(&format!("2026-08-{i:02}"), 0, &[]))
            .collect();
        let mut s = ReviewState::default();
        s.open();
        let id = s.begin_load();
        s.apply_loaded(id, Ok(Outcome::Ready(r)));
        for _ in 0..35 {
            s.on_key(ch('j'));
        }
        let out = screen(&s, Lang::En, 90, 22);
        assert!(
            out.contains("▸ 2026-08-36"),
            "selected day scrolled into view:\n{out}"
        );
    }

    // ── fit ratings (ADR-0021) ────────────────────────────────────────────────

    fn rating(id: &str, crit: &str, status: &str, verdict: &str, contested: bool) -> RatingItem {
        RatingItem {
            id: id.into(),
            criterion_id: crit.into(),
            status: status.into(),
            verdict: verdict.into(),
            contested,
            resolved: false,
            question: Some(format!("Question of {crit}?")),
        }
    }

    fn with_ratings(items: Vec<RatingItem>) -> ReviewState {
        let mut r = review();
        r.days[0].ratings = items;
        let mut s = ReviewState::default();
        s.open();
        let id = s.begin_load();
        s.apply_loaded(id, Ok(Outcome::Ready(r)));
        s
    }

    fn two_ratings() -> ReviewState {
        with_ratings(vec![
            rating("r1", "G1", "live", "met", false),
            rating("r2", "G2", "shadow", "not_met", true),
        ])
    }

    #[test]
    fn ratings_are_parsed_and_their_absence_is_tolerated() {
        let json = r#"{"name":"A","window_days":30,
            "days":[{"day":"2026-09-29","ratings":[
                {"id":"r1","criterion_id":"G1","status":"shadow","verdict":"unclear",
                 "contested":true,"resolved":false,"contest_note":"n","question":"Q?","future_field":1},
                {"id":"r2","criterion_id":"G2"}]},
              {"day":"2026-09-28"}],
            "ratings":[{"criterion_id":"G1","status":"live","met":2,"not_met":1,"unclear":0,
                        "contested":1,"criterion_hash":"h","question":null}]}"#;
        let r: Review = serde_json::from_str(json).unwrap();
        assert_eq!(r.days[0].ratings.len(), 2);
        assert_eq!(r.days[0].ratings[0].question.as_deref(), Some("Q?"));
        assert!(r.days[0].ratings[0].contested && !r.days[0].ratings[1].contested);
        assert_eq!(r.days[0].ratings[1].verdict, "");
        assert!(r.days[1].ratings.is_empty());
        assert_eq!(
            (
                r.ratings[0].met,
                r.ratings[0].not_met,
                r.ratings[0].contested
            ),
            (2, 1, 1)
        );
        // an older server without ratings at all
        let old: Review = serde_json::from_str(r#"{"name":"A","window_days":7}"#).unwrap();
        assert!(old.ratings.is_empty());
    }

    #[test]
    fn arrows_move_between_ratings_and_stay_in_range() {
        let mut s = two_ratings();
        s.on_key(key(KeyCode::Right));
        assert_eq!(s.sel_rating, 1);
        s.on_key(ch('l'));
        assert_eq!(s.sel_rating, 1, "clamped at the last rating");
        s.on_key(key(KeyCode::Left));
        s.on_key(ch('h'));
        assert_eq!(s.sel_rating, 0, "clamped at the first rating");
        s.on_key(key(KeyCode::Right));
        s.on_key(key(KeyCode::Down));
        assert_eq!(s.sel_rating, 0, "moving to another day resets the rating");
    }

    #[test]
    fn contesting_asks_for_a_reason_and_sends_it_for_the_selected_rating() {
        let mut s = two_ratings();
        assert_eq!(s.on_key(ch('c')), Action::None);
        assert_eq!(s.contest_target.as_deref(), Some("r1"));
        assert!(s.input.is_some());
        for c in "Rehearsal, not real work".chars() {
            s.on_key(ch(c)); // includes a 'c' and a 'u': they are text now, not commands
        }
        assert_eq!(
            s.on_key(key(KeyCode::Enter)),
            Action::ContestRating {
                id: "r1".into(),
                note: "Rehearsal, not real work".into()
            }
        );
        assert!(s.input.is_none() && s.contest_target.is_none());
    }

    #[test]
    fn an_empty_or_cancelled_contest_sends_nothing_and_does_not_leak_into_notes() {
        let mut s = two_ratings();
        s.on_key(ch('c'));
        s.on_key(ch(' '));
        assert_eq!(s.on_key(key(KeyCode::Enter)), Action::None);
        assert!(s.contest_target.is_none());
        s.on_key(ch('c'));
        s.on_key(ch('x'));
        s.on_key(key(KeyCode::Esc));
        assert!(s.input.is_none() && s.contest_target.is_none());
        // a note typed afterwards is a note, not a contest of the earlier rating
        s.on_key(ch('n'));
        s.on_key(ch('y'));
        assert!(matches!(
            s.on_key(key(KeyCode::Enter)),
            Action::AddNote { .. }
        ));
    }

    #[test]
    fn an_already_contested_rating_cannot_be_contested_again_but_can_be_withdrawn() {
        let mut s = two_ratings();
        s.on_key(key(KeyCode::Right)); // r2 is contested
        assert_eq!(s.on_key(ch('c')), Action::None);
        assert!(s.input.is_none() && s.contest_target.is_none());
        assert_eq!(
            s.on_key(ch('u')),
            Action::WithdrawContest { id: "r2".into() }
        );
        s.on_key(key(KeyCode::Left)); // r1 is not contested: nothing to withdraw
        assert_eq!(s.on_key(ch('u')), Action::None);
    }

    #[test]
    fn contest_keys_do_nothing_without_ratings_or_before_the_review_is_ready() {
        let mut none = ready();
        assert_eq!(none.on_key(ch('c')), Action::None);
        assert!(none.input.is_none());
        assert_eq!(none.on_key(ch('u')), Action::None);
        let mut loading = ReviewState::default();
        loading.open();
        assert_eq!(loading.on_key(ch('c')), Action::None);
        assert!(loading.input.is_none());
    }

    #[test]
    fn a_reload_keeps_the_rating_selection_in_range() {
        let mut s = two_ratings();
        s.on_key(key(KeyCode::Right));
        let mut r = review();
        r.days[0].ratings = vec![rating("r1", "G1", "live", "met", false)];
        let id = s.begin_load();
        s.apply_loaded(id, Ok(Outcome::Ready(r)));
        assert_eq!(s.sel_rating, 0);
    }

    #[test]
    fn ratings_show_status_verdict_and_who_sees_trial_ones_in_both_languages() {
        let s = two_ratings();
        let View::Ready(r) = &s.view else { panic!() };
        for (lang, live, shadow, unmet, contested, hint) in [
            (
                Lang::En,
                "live",
                "trial",
                "not met",
                "contested",
                "only to you",
            ),
            (
                Lang::Tr,
                "geçerli",
                "deneme",
                "karşılanmadı",
                "itiraz edildi",
                "yalnızca siz",
            ),
        ] {
            let t = strings(lang);
            let out = text(&detail_lines(&r.days[0], &t, 0));
            assert!(
                out.contains("▸ Question of G1? [") && out.contains(live),
                "{out}"
            );
            assert!(
                out.contains(shadow) && out.contains(unmet) && out.contains(contested),
                "{out}"
            );
            assert!(
                out.contains(hint),
                "trial ratings say only the person sees them:\n{out}"
            );
            // the label must sit on the right rating, not merely appear in the hint
            assert!(
                out.contains(&format!("Question of G2? [{shadow}]")),
                "{out}"
            );
            assert!(out.contains(&format!("Question of G1? [{live}]")), "{out}");
        }
    }

    #[test]
    fn a_rating_without_a_known_question_shows_its_criterion_id() {
        let mut item = rating("r1", "G7-old", "live", "met", false);
        item.question = None;
        let out = text(&[rating_line(&item, false, &strings(Lang::En))]);
        assert!(out.contains("G7-old"), "{out}");
    }

    #[test]
    fn a_resolved_contest_is_marked_as_reviewed() {
        let mut item = rating("r1", "G1", "live", "met", false);
        item.resolved = true;
        let out = text(&[rating_line(&item, false, &strings(Lang::En))]);
        assert!(
            out.contains("reviewed") && !out.contains("contested"),
            "{out}"
        );
    }

    #[test]
    fn rating_totals_are_counts_and_never_a_score() {
        let mut r = review();
        r.ratings = vec![RatingTotal {
            criterion_id: "G1".into(),
            status: "live".into(),
            met: 3,
            not_met: 1,
            unclear: 2,
            contested: 1,
            question: Some("Does this advance revenue?".into()),
        }];
        let out = text(&totals_lines(&r, &strings(Lang::En)));
        assert!(
            out.contains(
                "Does this advance revenue? [live]: 3 met · 1 not met · 2 unclear · 1 contested"
            ),
            "{out}"
        );
        assert!(
            !out.to_lowercase().contains("score") && !out.contains("average") && !out.contains('%')
        );
        assert!(rating_totals_lines(&review(), &strings(Lang::En)).is_empty());
    }

    #[test]
    fn a_day_with_a_contested_rating_is_marked_in_the_list() {
        let s = two_ratings();
        let View::Ready(r) = &s.view else { panic!() };
        assert!(day_row(&r.days[0], false).to_string().contains('!'));
        assert!(!day_row(&r.days[1], false).to_string().contains('!'));
    }

    #[test]
    fn the_contest_prompt_names_the_rating_and_the_screen_fits_a_small_terminal() {
        let mut s = two_ratings();
        s.on_key(ch('c'));
        s.on_key(ch('w'));
        let out = screen(&s, Lang::En, 90, 24);
        assert!(
            out.contains("Why do you contest \"Question of G1?\""),
            "{out}"
        );
        assert!(out.contains("w▏"));
        let tr = screen(&s, Lang::Tr, 90, 24);
        assert!(tr.contains("puanına neden itiraz ediyorsunuz"), "{tr}");
        let _ = screen(&two_ratings(), Lang::En, 40, 12); // must not panic
    }

    // ── training-need signals (ADR-0021 §6) ───────────────────────────────────

    fn signal(unit_wide: bool) -> TrainingSignal {
        TrainingSignal {
            criterion_id: "G1".into(),
            criterion_hash: "h1".into(),
            shared: false,
            rated: 10,
            not_met: 7,
            window_days: 30,
            unit_wide,
            question: Some("Does this advance revenue?".into()),
        }
    }

    fn with_signals(v: Vec<TrainingSignal>) -> Review {
        let mut r = review();
        r.training_need = v;
        r
    }

    #[test]
    fn training_signals_are_parsed_and_their_absence_is_tolerated() {
        let json = r#"{"name":"A","window_days":30,"training_need":[
            {"criterion_id":"G1","criterion_hash":"h","rated":10,"not_met":7,
             "not_met_share":0.7,"window_days":30,"unit_wide":true,"question":"Q?","x":1},
            {"criterion_id":"G2"}]}"#;
        let r: Review = serde_json::from_str(json).unwrap();
        assert_eq!(r.training_need.len(), 2);
        assert!(r.training_need[0].unit_wide && !r.training_need[1].unit_wide);
        assert_eq!(
            (r.training_need[0].rated, r.training_need[0].not_met),
            (10, 7)
        );
        let old: Review = serde_json::from_str(r#"{"name":"A","window_days":7}"#).unwrap();
        assert!(old.training_need.is_empty());
    }

    #[test]
    fn a_signal_is_shown_as_plain_counts_that_only_the_person_sees_in_both_languages() {
        let r = with_signals(vec![signal(false)]);
        for (lang, title, only, line) in [
            (
                Lang::En,
                "Where more support may help",
                "only you see this",
                "7 of 10 rated work did not meet it in the last 30 days",
            ),
            (
                Lang::Tr,
                "Daha fazla desteğin yararlı olabileceği yerler",
                "bunu yalnızca siz görürsünüz",
                "son 30 günde puanlanan 10 işten 7 tanesi bunu karşılamadı",
            ),
        ] {
            let out = text(&totals_lines(&r, &strings(lang)));
            assert!(out.contains(title) && out.contains(only), "{out}");
            assert!(
                out.contains("Does this advance revenue?") && out.contains(line),
                "{out}"
            );
        }
    }

    #[test]
    fn a_signal_never_shows_a_score_a_percentage_or_a_ranking() {
        let out = text(&totals_lines(
            &with_signals(vec![signal(true)]),
            &strings(Lang::En),
        ))
        .to_lowercase();
        for banned in ["score", "%", "rank", "grade", "percentile", "worst", "fail"] {
            assert!(!out.contains(banned), "found {banned:?} in:\n{out}");
        }
    }

    #[test]
    fn a_unit_wide_signal_says_the_rule_may_be_unclear() {
        let out = |uw| {
            text(&totals_lines(
                &with_signals(vec![signal(uw)]),
                &strings(Lang::En),
            ))
        };
        assert!(out(true).contains("the rule or its training may be unclear"));
        assert!(!out(false).contains("the rule or its training may be unclear"));
        let tr = text(&totals_lines(
            &with_signals(vec![signal(true)]),
            &strings(Lang::Tr),
        ));
        assert!(tr.contains("kural ya da eğitimi belirsiz olabilir"), "{tr}");
    }

    #[test]
    fn without_signals_the_section_is_absent() {
        let out = text(&totals_lines(&review(), &strings(Lang::En)));
        assert!(!out.contains("more support") && !out.contains("only you see this"));
        assert!(training_lines(&review(), &strings(Lang::En), 0).is_empty());
    }

    #[test]
    fn a_signal_without_a_known_question_names_its_criterion() {
        let mut sg = signal(false);
        sg.question = None;
        let out = text(&training_lines(
            &with_signals(vec![sg]),
            &strings(Lang::En),
            0,
        ));
        assert!(out.contains("G1: 7 of 10"), "{out}");
    }

    #[test]
    fn the_signal_is_on_screen_even_on_a_modest_terminal() {
        let mut r = review();
        r.training_need = vec![signal(true)];
        r.ratings = vec![RatingTotal {
            criterion_id: "G1".into(),
            status: "live".into(),
            met: 3,
            not_met: 7,
            unclear: 0,
            contested: 0,
            question: None,
        }];
        let mut s = ReviewState::default();
        s.open();
        let id = s.begin_load();
        s.apply_loaded(id, Ok(Outcome::Ready(r)));
        let out = screen(&s, Lang::En, 110, 30);
        assert!(out.contains("Where more support may help"), "{out}");
        assert!(out.contains("7 of 10 rated work"), "{out}");
        let _ = screen(&s, Lang::En, 40, 12); // must not panic
    }

    #[test]
    fn the_counts_and_window_come_from_the_signal_not_from_fixed_numbers() {
        let mut sg = signal(false);
        sg.rated = 14;
        sg.not_met = 9;
        sg.window_days = 45;
        let en = text(&training_lines(
            &with_signals(vec![sg.clone()]),
            &strings(Lang::En),
            0,
        ));
        assert!(
            en.contains("9 of 14 rated work did not meet it in the last 45 days"),
            "{en}"
        );
        let tr = text(&training_lines(
            &with_signals(vec![sg]),
            &strings(Lang::Tr),
            0,
        ));
        assert!(
            tr.contains("son 45 günde puanlanan 14 işten 9 tanesi"),
            "{tr}"
        );
    }

    // ── sharing a signal with the manager (ADR-0021 §6, option B) ─────────────

    fn sig(id: &str, shared: bool) -> TrainingSignal {
        TrainingSignal {
            criterion_id: id.into(),
            criterion_hash: format!("hash-{id}"),
            rated: 10,
            not_met: 7,
            window_days: 30,
            unit_wide: false,
            shared,
            question: None,
        }
    }

    fn sharing(enabled: bool, signals: Vec<TrainingSignal>) -> ReviewState {
        let mut r = review();
        r.training_need = signals;
        r.training_sharing_enabled = enabled;
        let mut s = ReviewState::default();
        s.open();
        let id = s.begin_load();
        s.apply_loaded(id, Ok(Outcome::Ready(r)));
        s
    }

    fn share_action(id: &str) -> Action {
        Action::ShareSignal {
            criterion_id: id.into(),
            criterion_hash: format!("hash-{id}"),
        }
    }

    #[test]
    fn sharing_needs_an_explicit_y_and_anything_else_cancels() {
        let mut s = sharing(true, vec![sig("G1", false)]);
        assert_eq!(s.on_key(ch('s')), Action::None, "s only asks");
        assert!(s.pending_share.is_some());
        assert_eq!(s.on_key(ch('y')), share_action("G1"));
        assert!(s.pending_share.is_none());
        for cancel in [
            ch('n'),
            key(KeyCode::Esc),
            key(KeyCode::Enter),
            ch('s'),
            ch('Y'),
        ] {
            let mut s = sharing(true, vec![sig("G1", false)]);
            s.on_key(ch('s'));
            assert_eq!(s.on_key(cancel), Action::None);
            assert!(s.pending_share.is_none(), "the question is gone either way");
            assert_eq!(
                s.on_key(ch('y')),
                Action::None,
                "a stray y later shares nothing"
            );
        }
    }

    #[test]
    fn the_confirmation_swallows_the_key_so_it_does_nothing_else() {
        let mut s = sharing(true, vec![sig("G1", false)]);
        s.on_key(ch('s'));
        assert_eq!(s.on_key(ch('q')), Action::None);
        assert!(
            s.open,
            "q cancelled the question; it did not close the view"
        );
    }

    #[test]
    fn a_shared_signal_is_withdrawn_at_once_without_a_question() {
        let mut s = sharing(true, vec![sig("G1", true)]);
        assert_eq!(
            s.on_key(ch('s')),
            Action::UnshareSignal {
                criterion_id: "G1".into(),
                criterion_hash: "hash-G1".into()
            }
        );
        assert!(s.pending_share.is_none());
    }

    #[test]
    fn withdrawing_still_works_after_the_company_turned_sharing_off() {
        let mut s = sharing(false, vec![sig("G1", true)]);
        assert!(matches!(s.on_key(ch('s')), Action::UnshareSignal { .. }));
    }

    #[test]
    fn when_the_company_has_not_enabled_sharing_s_explains_and_shares_nothing() {
        let mut s = sharing(false, vec![sig("G1", false)]);
        assert_eq!(s.on_key(ch('s')), Action::None);
        assert!(s.pending_share.is_none());
        assert_eq!(
            s.notice.as_deref(),
            Some("Your company has not enabled sharing these")
        );
    }

    #[test]
    fn t_picks_which_signal_s_acts_on() {
        let mut s = sharing(true, vec![sig("G1", false), sig("G2", false)]);
        s.on_key(ch('t'));
        assert_eq!(s.sel_signal, 1);
        s.on_key(ch('s'));
        assert_eq!(s.on_key(ch('y')), share_action("G2"));
        s.on_key(ch('t'));
        assert_eq!(s.sel_signal, 0, "t wraps around");
    }

    #[test]
    fn s_and_t_do_nothing_without_a_signal_or_before_the_review_is_ready() {
        let mut s = sharing(true, vec![]);
        assert_eq!(s.on_key(ch('s')), Action::None);
        assert_eq!(s.on_key(ch('t')), Action::None);
        assert!(s.pending_share.is_none());
        let mut loading = ReviewState::default();
        loading.open();
        assert_eq!(loading.on_key(ch('s')), Action::None);
        assert!(loading.pending_share.is_none());
    }

    #[test]
    fn a_reload_clears_a_pending_question_and_keeps_the_selection_in_range() {
        let mut s = sharing(true, vec![sig("G1", false), sig("G2", false)]);
        s.on_key(ch('t'));
        s.on_key(ch('s'));
        let mut r = review();
        r.training_need = vec![sig("G1", true)];
        let id = s.begin_load();
        s.apply_loaded(id, Ok(Outcome::Ready(r)));
        assert!(s.pending_share.is_none());
        assert_eq!(s.sel_signal, 0);
    }

    #[test]
    fn typing_a_note_is_not_mistaken_for_sharing() {
        let mut s = sharing(true, vec![sig("G1", false)]);
        s.on_key(ch('n'));
        for c in "sy".chars() {
            s.on_key(ch(c));
        }
        assert!(s.pending_share.is_none());
        assert!(matches!(
            s.on_key(key(KeyCode::Enter)),
            Action::AddNote { .. }
        ));
    }

    #[test]
    fn each_signal_shows_whether_and_how_it_is_shared_in_both_languages() {
        for (lang, on, can, none) in [
            (
                Lang::En,
                "shared with your manager — s withdraws it",
                "not shared — s shares it with your manager",
                "not shared with anyone",
            ),
            (
                Lang::Tr,
                "yöneticinizle paylaşıldı — s geri çeker",
                "paylaşılmadı — s yöneticinizle paylaşır",
                "kimseyle paylaşılmadı",
            ),
        ] {
            let t = strings(lang);
            let mut r = review();
            r.training_need = vec![sig("G1", true), sig("G2", false)];
            r.training_sharing_enabled = true;
            let out = text(&training_lines(&r, &t, 0));
            assert!(out.contains(on) && out.contains(can), "{out}");
            r.training_sharing_enabled = false;
            r.training_need = vec![sig("G2", false)];
            assert!(text(&training_lines(&r, &t, 0)).contains(none));
        }
    }

    #[test]
    fn the_selected_signal_is_marked() {
        let mut r = review();
        r.training_need = vec![sig("G1", false), sig("G2", false)];
        let out = text(&training_lines(&r, &strings(Lang::En), 1));
        assert!(out.contains("▸ G2:") && !out.contains("▸ G1:"), "{out}");
    }

    #[test]
    fn the_question_names_what_is_shared_and_says_it_can_be_withdrawn() {
        let mut s = sharing(true, vec![sig("G1", false)]);
        s.on_key(ch('s'));
        let out = screen(&s, Lang::En, 160, 30);
        assert!(
            out.contains("Share this with your manager? Only this one"),
            "{out}"
        );
        assert!(out.contains("you can withdraw it"), "{out}");
        let tr = screen(&s, Lang::Tr, 160, 30);
        assert!(tr.contains("Bunu yöneticinizle paylaşalım mı?"), "{tr}");
    }

    #[test]
    fn sharing_fields_are_parsed_and_default_to_off() {
        let r: Review = serde_json::from_str(
            r#"{"name":"A","window_days":30,"training_sharing_enabled":true,
                "training_need":[{"criterion_id":"G1","criterion_hash":"h","shared":true}]}"#,
        )
        .unwrap();
        assert!(r.training_sharing_enabled && r.training_need[0].shared);
        assert_eq!(r.training_need[0].criterion_hash, "h");
        let old: Review = serde_json::from_str(r#"{"name":"A","window_days":30}"#).unwrap();
        assert!(!old.training_sharing_enabled);
    }
}
