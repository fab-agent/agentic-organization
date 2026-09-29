//! Layout from ADR-0014 §3: sidebar (identity / recurring / recent runs) on the
//! left; agent pane and files strip on the right; key hint bar at the bottom.

use crate::app::{App, Focus};
use crate::i18n::strings;
use crate::model::{RunState, Sidebar};
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
        Constraint::Length(6),
        Constraint::Percentage(40),
        Constraint::Min(3),
    ])
    .areas(left);
    let [agent, files] = Layout::vertical([Constraint::Min(3), Constraint::Length(3)]).areas(right);

    draw_identity(f, ident, &sb, app);
    draw_recurring(f, recurring, &sb, app);
    draw_runs(f, runs, &sb, app);

    let agent_block = block(format!(" {} ", t.agent_pane), app.focus == Focus::Agent);
    f.render_widget(
        Paragraph::new(t.agent_pane_hint)
            .wrap(Wrap { trim: true })
            .style(Style::default().fg(Color::DarkGray))
            .block(agent_block),
        agent,
    );
    f.render_widget(
        Paragraph::new(t.no_files)
            .style(Style::default().fg(Color::DarkGray))
            .block(block(format!(" {} ", t.files), false)),
        files,
    );

    let status = match &app.error {
        Some(e) => Span::styled(
            format!(" {}: {e} ", t.loading_failed),
            Style::default().fg(Color::Red),
        ),
        None => Span::styled(t.keys, Style::default().add_modifier(Modifier::DIM)),
    };
    f.render_widget(Paragraph::new(Line::from(status)), keys);
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
        for want in ["Recurring", "Recent runs", "Agent session", "Files", "quit"] {
            assert!(text.contains(want), "missing {want}");
        }
    }
}
