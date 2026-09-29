//! Layout from ADR-0014 §3: sidebar (identity / recurring / recent runs) on the
//! left; agent pane and files strip on the right; key hint bar at the bottom.

use crate::app::{App, Focus};
use crate::i18n::strings;
use crate::model::{RunState, Sidebar};
use crate::review;
use crate::workspace::Status;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Paragraph, Wrap};
use ratatui::Frame;

fn block(title: String, focused: bool) -> Block<'static> {
    let style = if focused {
        Style::default().fg(Color::Cyan)
    } else {
        Style::default().fg(Color::DarkGray)
    };
    Block::default()
        .borders(Borders::ALL)
        .border_style(style)
        .title(title)
}

pub fn draw(f: &mut Frame, app: &App) {
    let t = strings(app.lang);
    let sb = app.snapshot.sidebar();

    let [main, keys] =
        Layout::vertical([Constraint::Min(3), Constraint::Length(1)]).areas(f.area());
    let [left, right] =
        Layout::horizontal([Constraint::Length(34), Constraint::Min(20)]).areas(main);
    let [ident, recurring, runs] = Layout::vertical([
        Constraint::Length(7),
        Constraint::Percentage(40),
        Constraint::Min(3),
    ])
    .areas(left);
    let [agent, files] = Layout::vertical([Constraint::Min(3), Constraint::Length(4)]).areas(right);

    draw_identity(f, ident, &sb, app);
    draw_recurring(f, recurring, &sb, app);
    draw_runs(f, runs, &sb, app);

    let ended = app.agent_ended();
    let title = if ended && app.pty.is_some() {
        format!(" {} — {} ", t.agent_pane, t.ended)
    } else {
        format!(" {} ", t.agent_pane)
    };
    let agent_block = block(title, app.focus == Focus::Agent);
    let inner = agent_block.inner(agent);
    f.render_widget(agent_block, agent);
    match &app.pty {
        Some(p) => p.render(inner, f.buffer_mut(), app.focus == Focus::Agent),
        None => f.render_widget(
            Paragraph::new(t.agent_pane_hint)
                .wrap(Wrap { trim: true })
                .style(Style::default().fg(Color::DarkGray)),
            inner,
        ),
    }
    f.render_widget(
        Paragraph::new(files_lines(app)).block(block(format!(" {} ", t.files), false)),
        files,
    );

    let status = match &app.error {
        Some(e) => Span::styled(
            format!(" {}: {e} ", t.loading_failed),
            Style::default().fg(Color::Red),
        ),
        None => Span::styled(
            if app.focus == Focus::Agent {
                t.keys_agent
            } else {
                t.keys_sidebar
            },
            Style::default().add_modifier(Modifier::DIM),
        ),
    };
    f.render_widget(Paragraph::new(Line::from(status)), keys);

    // "My work review" is a full-screen view above everything else.
    if app.review.open {
        review::draw(f, f.area(), &app.review, app.lang);
    }
}

fn ago(secs: u64, word: &str) -> String {
    if secs < 60 {
        format!("{secs}s {word}")
    } else {
        format!("{}m {word}", secs / 60)
    }
}

/// The two lines of the files strip: sync status, then the newest files.
pub fn files_lines(app: &App) -> Vec<Line<'static>> {
    let t = strings(app.lang);
    let dim = Style::default().fg(Color::DarkGray);
    let s = &app.sync;
    let red = Style::default().fg(Color::Red);
    let first = if let Some(Status::Failed(w)) = &s.workspace {
        let why = w.error.as_deref().unwrap_or("?");
        Line::styled(format!("{}: {why}", t.workspace), red)
    } else if let Some(Status::Unavailable(why)) = &s.workspace {
        Line::styled(format!("{} {}: {why}", t.workspace, t.ws_unavailable), red)
    } else if let Some(Status::Starting(_)) = &s.workspace {
        Line::styled(format!("{} {}", t.workspace, t.ws_starting), dim)
    } else if let Some(e) = &s.error {
        Line::styled(format!("{}: {e}", t.sync_error), red)
    } else if let Some(at) = s.last {
        let mut parts = vec![
            s.folder.display().to_string(),
            format!("{} {}", t.synced, ago(at.elapsed().as_secs(), t.ago)),
        ];
        if s.changed > 0 {
            parts.push(format!("{} {}", s.changed, t.new_files));
        }
        if s.conflicts > 0 {
            parts.push(format!("{} {}", s.conflicts, t.conflicts));
        }
        let color = if s.conflicts > 0 {
            Color::Yellow
        } else {
            Color::Reset
        };
        Line::styled(parts.join(" · "), Style::default().fg(color))
    } else {
        Line::styled(s.folder.display().to_string(), dim)
    };
    let second = if s.recent.is_empty() {
        Line::styled(t.no_files.to_string(), dim)
    } else {
        Line::from(s.recent.join("  "))
    };
    vec![first, second]
}

fn draw_identity(f: &mut Frame, area: Rect, sb: &Sidebar, app: &App) {
    let t = strings(app.lang);
    let mut lines = vec![Line::styled(
        format!("▸ {}", sb.department.as_deref().unwrap_or("—")),
        Style::default().add_modifier(Modifier::BOLD),
    )];
    if let Some(r) = &sb.role {
        lines.push(Line::from(format!("  {}: {r}", t.role)));
    }
    if let Some(m) = &sb.manager {
        lines.push(Line::from(format!("  {}: {m}", t.reports_to)));
    }
    lines.push(Line::from(format!(
        "  {}: {} {}, {} {}",
        t.team, sb.humans, t.people, sb.agents, t.agents
    )));
    let (word, color) = match &app.sync.workspace {
        None => (t.ws_checking, Color::DarkGray),
        Some(Status::Ready(_)) => (t.ws_running, Color::Green),
        Some(Status::Starting(_)) => (t.ws_starting, Color::Yellow),
        Some(Status::Failed(_)) => (t.ws_failed, Color::Red),
        Some(Status::Unavailable(_)) => (t.ws_unavailable, Color::Red),
    };
    lines.push(Line::from(vec![
        Span::raw(format!("  {}: ", t.workspace)),
        Span::styled(word, Style::default().fg(color)),
    ]));
    f.render_widget(
        Paragraph::new(lines).block(block(
            format!(" {} ", sb.company),
            app.focus == Focus::Sidebar,
        )),
        area,
    );
}

fn draw_recurring(f: &mut Frame, area: Rect, sb: &Sidebar, app: &App) {
    let t = strings(app.lang);
    let lines: Vec<Line> = if sb.recurring.is_empty() {
        vec![Line::styled(t.empty, Style::default().fg(Color::DarkGray))]
    } else {
        sb.recurring
            .iter()
            .map(|r| {
                let dot = if r.enabled { "●" } else { "○" };
                Line::from(format!("{dot} {} {}", r.when, r.name))
            })
            .collect()
    };
    f.render_widget(
        Paragraph::new(lines).block(block(format!(" {} ", t.recurring), false)),
        area,
    );
}

fn draw_runs(f: &mut Frame, area: Rect, sb: &Sidebar, app: &App) {
    let t = strings(app.lang);
    let lines: Vec<Line> = if sb.runs.is_empty() {
        vec![Line::styled(t.empty, Style::default().fg(Color::DarkGray))]
    } else {
        sb.runs
            .iter()
            .map(|r| {
                let (glyph, color) = match r.state {
                    RunState::Ok => ("✓", Color::Green),
                    RunState::Failed => ("✗", Color::Red),
                    RunState::Pending => ("⧗", Color::Yellow),
                };
                Line::from(vec![
                    Span::styled(glyph, Style::default().fg(color)),
                    Span::raw(format!(" {} {}", r.when, r.text).replace("  ", " ")),
                ])
            })
            .collect()
    };
    f.render_widget(
        Paragraph::new(lines).block(block(format!(" {} ", t.recent_runs), false)),
        area,
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::app::App;
    use ratatui::{backend::TestBackend, Terminal};

    #[test]
    fn draws_layout_without_data() {
        let app = App::test_default();
        let mut term = Terminal::new(TestBackend::new(100, 20)).unwrap();
        term.draw(|f| draw(f, &app)).unwrap();
        let text: String = term
            .backend()
            .buffer()
            .content()
            .iter()
            .map(|c| c.symbol())
            .collect();
        for want in [
            "Recurring",
            "Recent runs",
            "Agent session",
            "Files",
            "Ctrl+O",
        ] {
            assert!(text.contains(want), "missing {want}");
        }
    }

    fn text(lines: &[Line]) -> String {
        lines
            .iter()
            .map(|l| l.to_string())
            .collect::<Vec<_>>()
            .join("\n")
    }

    #[test]
    fn files_strip_states() {
        let mut app = App::test_default();
        app.sync.folder = "/home/a/Fabrika".into();
        assert!(text(&files_lines(&app)).contains("/home/a/Fabrika"));

        let w = |state: &str, err: Option<&str>| crate::workspace::Ws {
            id: "w1".into(),
            state: state.into(),
            error: err.map(Into::into),
        };
        app.sync.workspace = Some(Status::Starting(w("creating", None)));
        assert!(text(&files_lines(&app)).contains("starting"));
        app.sync.workspace = Some(Status::Failed(w("failed", Some("no disk"))));
        assert!(text(&files_lines(&app)).contains("Workspace: no disk"));
        app.sync.workspace = Some(Status::Unavailable("not configured".into()));
        assert!(text(&files_lines(&app)).contains("unavailable: not configured"));

        app.sync.workspace = Some(Status::Ready(w("running", None)));
        app.sync.last = Some(std::time::Instant::now());
        app.sync.changed = 2;
        app.sync.conflicts = 1;
        app.sync.recent = vec!["deck.pptx".into(), "summaries/x.md".into()];
        let t = text(&files_lines(&app));
        assert!(t.contains("synced") && t.contains("2 new") && t.contains("1 conflict"));
        assert!(t.contains("deck.pptx  summaries/x.md"));

        app.sync.error = Some("boom".into());
        assert!(text(&files_lines(&app)).contains("sync error: boom"));
    }
}
