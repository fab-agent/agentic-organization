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

#[derive(Debug, Clone, Deserialize, PartialEq, Default)]
pub struct DayEntry {
    pub day: String,
    #[serde(default)]
    pub signals: BTreeMap<String, i64>,
    #[serde(default)]
    pub tags: BTreeMap<String, BTreeMap<String, i64>>,
    #[serde(default)]
    pub notes: Vec<Note>,
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
    AddNote { day: String, text: String },
    DeleteNote { id: String },
}

#[derive(Debug, Clone)]
pub struct ReviewState {
    pub open: bool,
    pub view: View,
    pub selected: usize,
    pub window: u32,
    /// The note being typed, if any.
    pub input: Option<String>,
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
            req_id: 0,
            notice: None,
        }
    }
}

impl ReviewState {
    pub fn open(&mut self) -> Action {
        self.open = true;
        self.selected = 0;
        self.input = None;
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

    /// The day a new note goes on: the selected day, else today (UTC).
    fn note_day(&self) -> String {
        self.days()
            .get(self.selected)
            .map(|d| d.day.clone())
            .unwrap_or_else(today_utc)
    }

    pub fn on_key(&mut self, k: KeyEvent) -> Action {
        if let Some(buf) = self.input.as_mut() {
            match k.code {
                KeyCode::Esc => self.input = None,
                KeyCode::Enter => {
                    let text = buf.trim().to_string();
                    self.input = None;
                    if !text.is_empty() {
                        return Action::AddNote {
                            day: self.note_day(),
                            text,
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
                Action::None
            }
            KeyCode::Down | KeyCode::Char('j') => {
                let max = self.days().len().saturating_sub(1);
                self.selected = (self.selected + 1).min(max);
                Action::None
            }
            KeyCode::Char('w') => {
                let i = WINDOWS.iter().position(|w| *w == self.window).unwrap_or(0);
                self.window = WINDOWS[(i + 1) % WINDOWS.len()];
                self.selected = 0;
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
}

#[derive(Debug)]
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

pub fn totals_lines(r: &Review, t: &T) -> Vec<Line<'static>> {
    let mut lines = signals_lines(&r.totals.signals, t, "  ");
    lines.extend(tags_lines(&r.totals.tags, t, "  "));
    if lines.is_empty() {
        lines.push(Line::styled(
            format!("  {}", t.rv_nothing),
            Style::default().fg(Color::DarkGray),
        ));
    }
    lines
}

pub fn day_row(d: &DayEntry, selected: bool) -> Line<'static> {
    let denied = d.signals.get("policy_denied").copied().unwrap_or(0);
    let asked = d.signals.get("approval_asked").copied().unwrap_or(0);
    let mark = if d.notes.is_empty() { "" } else { " ✎" };
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

pub fn detail_lines(d: &DayEntry, t: &T) -> Vec<Line<'static>> {
    let mut lines = vec![Line::styled(
        d.day.clone(),
        Style::default().add_modifier(Modifier::BOLD),
    )];
    lines.extend(signals_lines(&d.signals, t, "  "));
    lines.extend(tags_lines(&d.tags, t, "  "));
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

    let line = if let Some(buf) = &s.input {
        let day = s.note_day();
        Line::from(vec![
            Span::styled(
                format!("{}: ", fill(t.rv_note_for, "{day}", day)),
                Style::default().fg(Color::Cyan),
            ),
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
        Constraint::Length((totals_lines(r, t).len() as u16 + 2).min(8)),
        Constraint::Min(4),
        Constraint::Length(dh.min(10)),
    ])
    .areas(area);

    f.render_widget(
        Paragraph::new(totals_lines(r, t)).block(
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
                Paragraph::new(detail_lines(d, t)).wrap(Wrap { trim: false }),
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
        let d = text(&detail_lines(&review().days[0], &t));
        assert!(d.contains("2026-09-29") && d.contains("✎ first") && d.contains("✎ second"));
        let empty = text(&detail_lines(&review().days[1], &t));
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
}
