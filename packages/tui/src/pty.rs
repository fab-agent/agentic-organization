//! Local PTY pane: runs a command in a pseudo-terminal, feeds its output through
//! a vt100 emulator and paints the screen into a ratatui buffer.
//!
//! This is the stand-in for the server-side workspace attach (ADR-0014
//! follow-up 2); the pane engine (input encoding, resize, rendering) is what
//! carries over when the transport becomes a WebSocket.

use anyhow::{Context, Result};
use portable_pty::{native_pty_system, Child, CommandBuilder, MasterPty, PtySize};
use ratatui::buffer::Buffer;
use ratatui::crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use std::io::{Read, Write};
use std::sync::{Arc, Mutex};

pub struct Pty {
    parser: Arc<Mutex<vt100::Parser>>,
    master: Mutex<Box<dyn MasterPty + Send>>,
    writer: Mutex<Box<dyn Write + Send>>,
    child: Mutex<Box<dyn Child + Send + Sync>>,
    size: Mutex<(u16, u16)>,
}

/// Command for the agent pane: `FAB_AGENT_CMD` (whitespace-split), else
/// `opencode` when installed, else the user's shell.
pub fn default_command() -> Vec<String> {
    if let Ok(c) = std::env::var("FAB_AGENT_CMD") {
        let parts: Vec<String> = c.split_whitespace().map(String::from).collect();
        if !parts.is_empty() {
            return parts;
        }
    }
    if which("opencode") {
        return vec!["opencode".into()];
    }
    vec![std::env::var("SHELL").unwrap_or_else(|_| "/bin/sh".into())]
}

fn which(bin: &str) -> bool {
    std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).any(|d| d.join(bin).is_file()))
        .unwrap_or(false)
}

impl Pty {
    pub fn spawn(cmd: &[String], cols: u16, rows: u16) -> Result<Self> {
        let (cols, rows) = (cols.max(2), rows.max(2));
        let pair = native_pty_system()
            .openpty(PtySize {
                rows,
                cols,
                pixel_width: 0,
                pixel_height: 0,
            })
            .context("open pty")?;
        let mut b = CommandBuilder::new(&cmd[0]);
        b.args(&cmd[1..]);
        b.env("TERM", "xterm-256color");
        if let Some(home) = dirs::home_dir() {
            b.cwd(home);
        }
        let child = pair
            .slave
            .spawn_command(b)
            .with_context(|| format!("run {}", cmd[0]))?;
        drop(pair.slave);

        let mut reader = pair.master.try_clone_reader()?;
        let writer = pair.master.take_writer()?;
        let parser = Arc::new(Mutex::new(vt100::Parser::new(rows, cols, 0)));
        let p = Arc::clone(&parser);
        std::thread::spawn(move || {
            let mut buf = [0u8; 8192];
            while let Ok(n) = reader.read(&mut buf) {
                if n == 0 {
                    break;
                }
                p.lock().unwrap().process(&buf[..n]);
            }
        });
        Ok(Self {
            parser,
            master: Mutex::new(pair.master),
            writer: Mutex::new(writer),
            child: Mutex::new(child),
            size: Mutex::new((cols, rows)),
        })
    }

    pub fn write(&self, bytes: &[u8]) {
        let mut w = self.writer.lock().unwrap();
        let _ = w.write_all(bytes);
        let _ = w.flush();
    }

    pub fn is_alive(&self) -> bool {
        matches!(self.child.lock().unwrap().try_wait(), Ok(None))
    }

    fn resize(&self, cols: u16, rows: u16) {
        let (cols, rows) = (cols.max(2), rows.max(2));
        let mut size = self.size.lock().unwrap();
        if *size == (cols, rows) {
            return;
        }
        *size = (cols, rows);
        let _ = self.master.lock().unwrap().resize(PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        });
        self.parser.lock().unwrap().set_size(rows, cols);
    }

    /// Paint the terminal screen into `area` (resizing the PTY to fit).
    pub fn render(&self, area: Rect, buf: &mut Buffer, show_cursor: bool) {
        self.resize(area.width, area.height);
        let parser = self.parser.lock().unwrap();
        let screen = parser.screen();
        for row in 0..area.height {
            for col in 0..area.width {
                let Some(cell) = screen.cell(row, col) else {
                    continue;
                };
                if cell.is_wide_continuation() {
                    continue;
                }
                let dst = &mut buf[(area.x + col, area.y + row)];
                let s = cell.contents();
                dst.set_symbol(if s.is_empty() { " " } else { &s });
                dst.set_style(cell_style(cell));
            }
        }
        if show_cursor && !screen.hide_cursor() {
            let (r, c) = screen.cursor_position();
            if r < area.height && c < area.width {
                let dst = &mut buf[(area.x + c, area.y + r)];
                dst.modifier.insert(Modifier::REVERSED);
            }
        }
    }
}

impl Drop for Pty {
    fn drop(&mut self) {
        let _ = self.child.lock().unwrap().kill();
    }
}

fn color(c: vt100::Color) -> Color {
    match c {
        vt100::Color::Default => Color::Reset,
        vt100::Color::Idx(i) => Color::Indexed(i),
        vt100::Color::Rgb(r, g, b) => Color::Rgb(r, g, b),
    }
}

fn cell_style(cell: &vt100::Cell) -> Style {
    let mut m = Modifier::empty();
    if cell.bold() {
        m |= Modifier::BOLD;
    }
    if cell.italic() {
        m |= Modifier::ITALIC;
    }
    if cell.underline() {
        m |= Modifier::UNDERLINED;
    }
    if cell.inverse() {
        m |= Modifier::REVERSED;
    }
    Style::default()
        .fg(color(cell.fgcolor()))
        .bg(color(cell.bgcolor()))
        .add_modifier(m)
}

/// Encode a key press as the bytes a terminal would send.
pub fn encode_key(k: KeyEvent) -> Vec<u8> {
    let ctrl = k.modifiers.contains(KeyModifiers::CONTROL);
    let alt = k.modifiers.contains(KeyModifiers::ALT);
    let mut out: Vec<u8> = match k.code {
        KeyCode::Char(c) if ctrl && c.is_ascii_alphabetic() => {
            vec![(c.to_ascii_lowercase() as u8) - b'a' + 1]
        }
        KeyCode::Char(c) if ctrl && matches!(c, ' ' | '@') => vec![0],
        KeyCode::Char(c) => c.to_string().into_bytes(),
        KeyCode::Enter => vec![b'\r'],
        KeyCode::Tab => vec![b'\t'],
        KeyCode::BackTab => b"\x1b[Z".to_vec(),
        KeyCode::Backspace => vec![0x7f],
        KeyCode::Esc => vec![0x1b],
        KeyCode::Up => b"\x1b[A".to_vec(),
        KeyCode::Down => b"\x1b[B".to_vec(),
        KeyCode::Right => b"\x1b[C".to_vec(),
        KeyCode::Left => b"\x1b[D".to_vec(),
        KeyCode::Home => b"\x1b[H".to_vec(),
        KeyCode::End => b"\x1b[F".to_vec(),
        KeyCode::PageUp => b"\x1b[5~".to_vec(),
        KeyCode::PageDown => b"\x1b[6~".to_vec(),
        KeyCode::Delete => b"\x1b[3~".to_vec(),
        KeyCode::Insert => b"\x1b[2~".to_vec(),
        KeyCode::F(n) => match n {
            1..=4 => vec![0x1b, b'O', b'P' + (n - 1)],
            5 => b"\x1b[15~".to_vec(),
            6..=8 => format!("\x1b[{}~", 17 + (n - 6)).into_bytes(),
            9 | 10 => format!("\x1b[{}~", 20 + (n - 9)).into_bytes(),
            11 | 12 => format!("\x1b[{}~", 23 + (n - 11)).into_bytes(),
            _ => vec![],
        },
        _ => vec![],
    };
    if alt && !out.is_empty() {
        out.insert(0, 0x1b);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(code: KeyCode, m: KeyModifiers) -> KeyEvent {
        KeyEvent::new(code, m)
    }

    #[test]
    fn encodes_keys() {
        assert_eq!(
            encode_key(key(KeyCode::Char('a'), KeyModifiers::NONE)),
            b"a"
        );
        assert_eq!(
            encode_key(key(KeyCode::Char('c'), KeyModifiers::CONTROL)),
            vec![3]
        );
        assert_eq!(
            encode_key(key(KeyCode::Char('x'), KeyModifiers::ALT)),
            b"\x1bx"
        );
        assert_eq!(encode_key(key(KeyCode::Up, KeyModifiers::NONE)), b"\x1b[A");
        assert_eq!(
            encode_key(key(KeyCode::Char('ş'), KeyModifiers::NONE)),
            "ş".as_bytes()
        );
        assert_eq!(
            encode_key(key(KeyCode::F(5), KeyModifiers::NONE)),
            b"\x1b[15~"
        );
    }

    #[test]
    fn runs_a_command_and_paints_output() {
        let pty = Pty::spawn(
            &["/bin/sh".into(), "-c".into(), "printf hello-fab".into()],
            20,
            3,
        )
        .unwrap();
        let area = Rect::new(0, 0, 20, 3);
        let mut buf = Buffer::empty(area);
        for _ in 0..50 {
            std::thread::sleep(std::time::Duration::from_millis(50));
            pty.render(area, &mut buf, false);
            let line: String = (0..20).map(|x| buf[(x, 0)].symbol().to_string()).collect();
            if line.contains("hello-fab") {
                return;
            }
        }
        panic!("output never appeared");
    }
}
