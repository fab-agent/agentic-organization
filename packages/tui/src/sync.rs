//! Local workspace folder sync (ADR-0019 §8, ADR-0018 files API).
//!
//! The folder root mirrors the workspace's `out/` (what the agent produced, incl.
//! `summaries/`); `<root>/in/` is the upload area. Rules:
//!
//! * Outputs are one-way, server → laptop. A file the person edited locally is
//!   **never overwritten**: the server version is written next to it as
//!   `name (server).ext` and the conflict is reported.
//! * The server is not trusted with paths: anything that could leave the folder
//!   (`..`, absolute, backslash, `:`, symlinked components) is skipped.
//! * Downloads are verified against the manifest's SHA-256 before being written,
//!   and written atomically.
//! * The cursor only advances past files that were processed, so a failed file is
//!   retried on the next run.
//!
//! The sync core talks to a `Remote` trait, so it is tested without a network.

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};

pub const STATE_FILE: &str = ".fab-sync.json";
pub const UPLOAD_DIR: &str = "in";

#[derive(Debug, Clone, Deserialize)]
pub struct FileEntry {
    pub path: String,
    pub size: u64,
    pub sha256: String,
    pub mtime_ns: i64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Manifest {
    pub files: Vec<FileEntry>,
    pub cursor: i64,
}

pub trait Remote {
    fn manifest(&self, since: i64) -> Result<Manifest>;
    fn download(&self, path: &str, max_bytes: u64) -> Result<Vec<u8>>;
    fn upload(&self, path: &str, data: &[u8]) -> Result<()>;
}

#[derive(Debug, Clone, Copy)]
pub struct Limits {
    pub download: u64,
    pub upload: u64,
}

impl Limits {
    pub fn from_env() -> Self {
        let mb = |name: &str, default: u64| {
            std::env::var(name)
                .ok()
                .and_then(|v| v.parse::<u64>().ok())
                .unwrap_or(default)
                * 1024
                * 1024
        };
        Self {
            download: mb("FAB_MAX_DOWNLOAD_MB", 200),
            upload: mb("FAB_MAX_UPLOAD_MB", 50),
        }
    }
}

/// Where the local workspace folder lives: `FAB_FOLDER`, else `~/Fabrika`.
pub fn default_folder() -> PathBuf {
    if let Ok(p) = std::env::var("FAB_FOLDER") {
        if !p.is_empty() {
            return p.into();
        }
    }
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("Fabrika")
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct State {
    /// Server manifest cursor (`mtime_ns`) everything up to which was processed.
    cursor: i64,
    /// Downloaded outputs by relative path.
    files: BTreeMap<String, Synced>,
    /// Uploaded inputs: relative path (under `in/`) → sha256 last uploaded.
    uploaded: BTreeMap<String, String>,
    /// "(server)" copies written for conflicts and not yet resolved (deleted or
    /// renamed by the person). Persisted so the warning outlives the pass and the
    /// process that created it.
    #[serde(default)]
    conflicts: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Synced {
    server_sha256: String,
    /// SHA-256 of the local file as of the last sync; empty = the local file has
    /// diverged from the server (a conflict), so it must never be overwritten.
    local_sha256: String,
}

impl State {
    fn load(root: &Path) -> Result<State> {
        let p = root.join(STATE_FILE);
        match fs::read(&p) {
            Ok(b) => match serde_json::from_slice(&b) {
                Ok(s) => Ok(s),
                Err(_) => {
                    // Keep the unreadable file for inspection and start over: with
                    // no records, identical files are re-recorded and differing
                    // ones become conflicts — nothing is overwritten.
                    let _ = fs::rename(&p, root.join(format!("{STATE_FILE}.corrupt")));
                    Ok(State::default())
                }
            },
            Err(e) if e.kind() == ErrorKind::NotFound => Ok(State::default()),
            Err(e) => Err(e).context("read sync state"),
        }
    }

    fn save(&self, root: &Path) -> Result<()> {
        write_atomic(&root.join(STATE_FILE), &serde_json::to_vec_pretty(self)?)
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Report {
    pub downloaded: Vec<String>,
    /// "(server)" copies written by *this* pass because the local file had changed.
    pub conflicts: Vec<String>,
    /// Every "(server)" copy still on disk from this or earlier passes; a conflict
    /// is resolved when the person deletes or renames its copy.
    pub pending_conflicts: Vec<String>,
    pub uploaded: Vec<String>,
    /// Server paths ignored for safety or size, with the reason.
    pub skipped: Vec<String>,
    pub errors: Vec<String>,
}

impl Report {
    pub fn changed(&self) -> usize {
        self.downloaded.len() + self.conflicts.len() + self.uploaded.len()
    }
}

pub fn sha256_hex(data: &[u8]) -> String {
    Sha256::digest(data)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// Map a server-supplied relative path to a path inside `root`, or explain why not.
pub fn local_path(root: &Path, rel: &str) -> Result<PathBuf> {
    if rel.is_empty() || rel.len() > 512 || rel.starts_with('/') || rel.contains(['\0', '\\', ':'])
    {
        bail!("unsafe path");
    }
    let parts: Vec<&str> = rel.split('/').collect();
    if parts
        .iter()
        .any(|p| p.is_empty() || *p == "." || *p == "..")
    {
        bail!("unsafe path");
    }
    if parts[0].starts_with(".fab-sync") {
        bail!("reserved name");
    }
    if parts[0] == UPLOAD_DIR {
        bail!("`{UPLOAD_DIR}/` is the upload area");
    }
    let mut cur = root.to_path_buf();
    for p in &parts {
        cur.push(p);
        match fs::symlink_metadata(&cur) {
            Ok(m) if m.file_type().is_symlink() => bail!("symlink in path"),
            Ok(_) => {}
            Err(e) if e.kind() == ErrorKind::NotFound => break,
            Err(e) => return Err(e.into()),
        }
    }
    Ok(root.join(parts.join("/")))
}

fn write_atomic(target: &Path, data: &[u8]) -> Result<()> {
    let parent = target.parent().ok_or_else(|| anyhow!("no parent"))?;
    fs::create_dir_all(parent)?;
    let name = target
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| anyhow!("bad file name"))?;
    let tmp = parent.join(format!(".{name}.fab-tmp"));
    fs::write(&tmp, data)?;
    fs::rename(&tmp, target).inspect_err(|_| {
        let _ = fs::remove_file(&tmp);
    })?;
    Ok(())
}

/// `dir/name (server).ext`, or `(server 2)`… if that exists.
fn conflict_path(target: &Path) -> PathBuf {
    let dir = target.parent().unwrap_or_else(|| Path::new("."));
    let stem = target
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("file");
    let ext = target.extension().and_then(|s| s.to_str());
    let mut n = 1;
    loop {
        let tag = if n == 1 {
            "(server)".to_string()
        } else {
            format!("(server {n})")
        };
        let name = match ext {
            Some(e) => format!("{stem} {tag}.{e}"),
            None => format!("{stem} {tag}"),
        };
        let p = dir.join(name);
        if !p.exists() {
            return p;
        }
        n += 1;
    }
}

enum FetchErr {
    Skip(String),
    Fail(anyhow::Error),
}

fn fetch_one(
    root: &Path,
    remote: &dyn Remote,
    state: &mut State,
    e: &FileEntry,
    limits: Limits,
    report: &mut Report,
) -> std::result::Result<(), FetchErr> {
    let target = local_path(root, &e.path).map_err(|x| FetchErr::Skip(x.to_string()))?;
    if state
        .files
        .get(&e.path)
        .is_some_and(|s| s.server_sha256 == e.sha256)
    {
        return Ok(()); // already handled this exact server version
    }
    if e.size > limits.download {
        return Err(FetchErr::Skip("too large".into()));
    }
    let data = remote
        .download(&e.path, limits.download)
        .map_err(FetchErr::Fail)?;
    if sha256_hex(&data) != e.sha256 {
        return Err(FetchErr::Fail(anyhow!("checksum mismatch")));
    }

    let local = match fs::symlink_metadata(&target) {
        Ok(m) if m.is_dir() => return Err(FetchErr::Skip("a folder is in the way".into())),
        Ok(m) if !m.is_file() => return Err(FetchErr::Skip("not a regular file".into())),
        Ok(_) => Some(fs::read(&target).map_err(|x| FetchErr::Fail(x.into()))?),
        Err(x) if x.kind() == ErrorKind::NotFound => None,
        Err(x) => return Err(FetchErr::Fail(x.into())),
    };
    let write = |path: &Path| write_atomic(path, &data).map_err(FetchErr::Fail);

    let local_after = match local {
        None => {
            write(&target)?;
            report.downloaded.push(e.path.clone());
            e.sha256.clone()
        }
        Some(cur) => {
            let cur_sha = sha256_hex(&cur);
            if cur_sha == e.sha256 {
                cur_sha // already identical
            } else if state
                .files
                .get(&e.path)
                .is_some_and(|s| !s.local_sha256.is_empty() && s.local_sha256 == cur_sha)
            {
                write(&target)?; // untouched since last sync: take the new version
                report.downloaded.push(e.path.clone());
                e.sha256.clone()
            } else {
                // Local edit (or unknown history): keep it, put the server copy beside it.
                let copy = conflict_path(&target);
                write(&copy)?;
                let shown = copy
                    .strip_prefix(root)
                    .unwrap_or(&copy)
                    .to_string_lossy()
                    .replace('\\', "/");
                report.conflicts.push(shown);
                String::new() // diverged: never overwrite this file automatically
            }
        }
    };
    state.files.insert(
        e.path.clone(),
        Synced {
            server_sha256: e.sha256.clone(),
            local_sha256: local_after,
        },
    );
    Ok(())
}

fn collect_uploads(dir: &Path, base: &Path, out: &mut Vec<(String, PathBuf)>) -> Result<()> {
    let mut entries: Vec<_> = fs::read_dir(dir)?.collect::<std::io::Result<_>>()?;
    entries.sort_by_key(|e| e.file_name());
    for e in entries {
        let name = e.file_name();
        let name_s = name.to_string_lossy();
        if name_s.starts_with('.') {
            continue; // hidden / temp files
        }
        let ft = e.file_type()?;
        if ft.is_symlink() {
            continue;
        }
        let path = e.path();
        if ft.is_dir() {
            collect_uploads(&path, base, out)?;
        } else if ft.is_file() {
            let rel = path
                .strip_prefix(base)?
                .components()
                .map(|c| c.as_os_str().to_string_lossy().into_owned())
                .collect::<Vec<_>>()
                .join("/");
            out.push((rel, path));
        }
    }
    Ok(())
}

fn upload_pending(
    root: &Path,
    remote: &dyn Remote,
    state: &mut State,
    limits: Limits,
    report: &mut Report,
) {
    let base = root.join(UPLOAD_DIR);
    let mut files = Vec::new();
    if let Err(e) = collect_uploads(&base, &base, &mut files) {
        report.errors.push(format!("scan {UPLOAD_DIR}/: {e}"));
        return;
    }
    for (rel, path) in files {
        let result = (|| -> Result<Option<String>> {
            if fs::metadata(&path)?.len() > limits.upload {
                bail!("too large");
            }
            let data = fs::read(&path)?;
            let sha = sha256_hex(&data);
            if state.uploaded.get(&rel) == Some(&sha) {
                return Ok(None);
            }
            remote.upload(&rel, &data)?;
            Ok(Some(sha))
        })();
        match result {
            Ok(Some(sha)) => {
                state.uploaded.insert(rel.clone(), sha);
                report.uploaded.push(rel);
            }
            Ok(None) => {}
            Err(e) => report.errors.push(format!("{UPLOAD_DIR}/{rel}: {e:#}")),
        }
    }
}

/// One sync pass. `Err` only when the pass cannot run at all (manifest / state);
/// per-file problems are collected in the report.
pub fn sync(root: &Path, remote: &dyn Remote, limits: Limits) -> Result<Report> {
    fs::create_dir_all(root.join(UPLOAD_DIR)).context("create workspace folder")?;
    let mut state = State::load(root)?;
    let mut report = Report::default();

    let manifest = remote.manifest(state.cursor).context("fetch file list")?;
    let mut files = manifest.files;
    files.sort_by(|a, b| (a.mtime_ns, &a.path).cmp(&(b.mtime_ns, &b.path)));

    let mut first_failure: Option<i64> = None;
    for e in &files {
        match fetch_one(root, remote, &mut state, e, limits, &mut report) {
            Ok(()) => {}
            Err(FetchErr::Skip(why)) => report.skipped.push(format!("{}: {why}", e.path)),
            Err(FetchErr::Fail(err)) => {
                report.errors.push(format!("{}: {err:#}", e.path));
                first_failure.get_or_insert(e.mtime_ns);
            }
        }
    }
    for c in &report.conflicts {
        if !state.conflicts.contains(c) {
            state.conflicts.push(c.clone());
        }
    }
    state.conflicts.retain(|c| root.join(c).exists());
    report.pending_conflicts = state.conflicts.clone();

    state.cursor = match first_failure {
        // Retry the failed file (and everything after it) next time.
        Some(m) => state.cursor.max(m - 1),
        None => state.cursor.max(manifest.cursor),
    };

    upload_pending(root, remote, &mut state, limits, &mut report);
    state.save(root)?;
    Ok(report)
}

/// Most recently changed files in the folder root (outputs), newest first, for the UI.
pub fn recent_files(root: &Path, n: usize) -> Vec<String> {
    fn walk(dir: &Path, base: &Path, out: &mut Vec<(std::time::SystemTime, String)>) {
        let Ok(rd) = fs::read_dir(dir) else { return };
        for e in rd.flatten() {
            let name = e.file_name().to_string_lossy().into_owned();
            if name.starts_with('.') {
                continue;
            }
            let Ok(ft) = e.file_type() else { continue };
            let p = e.path();
            if ft.is_dir() {
                if dir == base && name == UPLOAD_DIR {
                    continue;
                }
                walk(&p, base, out);
            } else if ft.is_file() {
                if let (Ok(m), Ok(rel)) = (
                    e.metadata().and_then(|m| m.modified()),
                    p.strip_prefix(base),
                ) {
                    out.push((m, rel.to_string_lossy().replace('\\', "/")));
                }
            }
        }
    }
    let mut v = Vec::new();
    walk(root, root, &mut v);
    v.sort_by(|a, b| b.0.cmp(&a.0));
    v.into_iter().take(n).map(|(_, p)| p).collect()
}

/// What one background pass produced, for the UI.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Outcome {
    /// The person has no workspace yet.
    NoWorkspace,
    Synced {
        report: Report,
        recent: Vec<String>,
    },
}

/// Resolve the caller's workspace and sync the folder with it.
pub fn sync_workspace(client: &crate::api::Client, root: &Path) -> Result<Outcome> {
    let me = client.me()?;
    let company = me
        .companies
        .first()
        .map(|c| c.company_id.clone())
        .ok_or_else(|| anyhow!("this account belongs to no company"))?;
    let Some(workspace_id) = client.my_workspace(&company)? else {
        return Ok(Outcome::NoWorkspace);
    };
    let remote = crate::api::WorkspaceRemote {
        client,
        workspace_id,
    };
    let report = sync(root, &remote, Limits::from_env())?;
    Ok(Outcome::Synced {
        report,
        recent: recent_files(root, 4),
    })
}

/// Background sync: runs once immediately, then every `interval` or when poked.
/// Returns (results, poke). Dropping the poke sender stops the thread.
pub fn spawn_loop(
    session: crate::session::Session,
    root: PathBuf,
    interval: std::time::Duration,
) -> (
    std::sync::mpsc::Receiver<std::result::Result<Outcome, String>>,
    std::sync::mpsc::Sender<()>,
) {
    let (tx, rx) = std::sync::mpsc::channel();
    let (poke, wake) = std::sync::mpsc::channel::<()>();
    std::thread::spawn(move || {
        let client = crate::api::Client::new(session);
        loop {
            let res = sync_workspace(&client, &root).map_err(|e| format!("{e:#}"));
            if tx.send(res).is_err() {
                break;
            }
            match wake.recv_timeout(interval) {
                Ok(()) | Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
                Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
            }
        }
    });
    (rx, poke)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    #[derive(Default)]
    struct FakeRemote {
        files: RefCell<BTreeMap<String, (Vec<u8>, i64)>>,
        uploads: RefCell<Vec<(String, Vec<u8>)>>,
        fail_download: RefCell<Vec<String>>,
        corrupt: RefCell<Vec<String>>,
        downloads: RefCell<Vec<String>>,
    }

    impl FakeRemote {
        fn put(&self, path: &str, data: &[u8], mtime: i64) {
            self.files
                .borrow_mut()
                .insert(path.into(), (data.to_vec(), mtime));
        }
    }

    impl Remote for FakeRemote {
        fn manifest(&self, since: i64) -> Result<Manifest> {
            let files: Vec<FileEntry> = self
                .files
                .borrow()
                .iter()
                .filter(|(_, (_, m))| *m > since)
                .map(|(p, (d, m))| FileEntry {
                    path: p.clone(),
                    size: d.len() as u64,
                    sha256: sha256_hex(d),
                    mtime_ns: *m,
                })
                .collect();
            let cursor = files
                .iter()
                .map(|f| f.mtime_ns)
                .max()
                .unwrap_or(since)
                .max(since);
            Ok(Manifest { files, cursor })
        }
        fn download(&self, path: &str, _max: u64) -> Result<Vec<u8>> {
            self.downloads.borrow_mut().push(path.into());
            if self.fail_download.borrow().iter().any(|p| p == path) {
                bail!("network down");
            }
            let mut d = self.files.borrow()[path].0.clone();
            if self.corrupt.borrow().iter().any(|p| p == path) {
                d.push(b'!');
            }
            Ok(d)
        }
        fn upload(&self, path: &str, data: &[u8]) -> Result<()> {
            self.uploads.borrow_mut().push((path.into(), data.to_vec()));
            Ok(())
        }
    }

    const LIM: Limits = Limits {
        download: 1 << 20,
        upload: 1 << 20,
    };

    fn read(root: &Path, rel: &str) -> String {
        fs::read_to_string(root.join(rel)).unwrap()
    }

    #[test]
    fn downloads_new_files_including_subfolders_and_skips_unchanged() {
        let d = tempfile::tempdir().unwrap();
        let r = FakeRemote::default();
        r.put("deck.pptx", b"v1", 10);
        r.put("summaries/2026-09-29-x.md", b"# s", 20);
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.downloaded.len(), 2);
        assert_eq!(read(d.path(), "summaries/2026-09-29-x.md"), "# s");
        assert!(d.path().join("in").is_dir());

        let n = r.downloads.borrow().len();
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.changed(), 0);
        assert_eq!(r.downloads.borrow().len(), n, "nothing re-downloaded");
    }

    #[test]
    fn new_version_by_name_arrives_and_old_file_is_kept() {
        let d = tempfile::tempdir().unwrap();
        let r = FakeRemote::default();
        r.put("report.xlsx", b"1", 10);
        sync(d.path(), &r, LIM).unwrap();
        r.put("report-v2.xlsx", b"2", 20);
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.downloaded, vec!["report-v2.xlsx"]);
        assert_eq!(read(d.path(), "report.xlsx"), "1");
    }

    #[test]
    fn server_update_overwrites_an_untouched_local_copy() {
        let d = tempfile::tempdir().unwrap();
        let r = FakeRemote::default();
        r.put("a.txt", b"one", 10);
        sync(d.path(), &r, LIM).unwrap();
        r.put("a.txt", b"two", 20);
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.downloaded, vec!["a.txt"]);
        assert_eq!(read(d.path(), "a.txt"), "two");
    }

    #[test]
    fn locally_edited_file_is_never_overwritten() {
        let d = tempfile::tempdir().unwrap();
        let r = FakeRemote::default();
        r.put("a.txt", b"one", 10);
        sync(d.path(), &r, LIM).unwrap();
        fs::write(d.path().join("a.txt"), "my edit").unwrap();

        r.put("a.txt", b"two", 20);
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(read(d.path(), "a.txt"), "my edit");
        assert_eq!(rep.conflicts, vec!["a (server).txt"]);
        assert_eq!(read(d.path(), "a (server).txt"), "two");

        // and a later server change still must not clobber the diverged file
        r.put("a.txt", b"three", 30);
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(read(d.path(), "a.txt"), "my edit");
        assert_eq!(rep.conflicts, vec!["a (server 2).txt"]);
    }

    #[test]
    fn conflict_stays_pending_until_the_copy_is_resolved() {
        let d = tempfile::tempdir().unwrap();
        let r = FakeRemote::default();
        r.put("a.txt", b"one", 10);
        sync(d.path(), &r, LIM).unwrap();
        fs::write(d.path().join("a.txt"), "my edit").unwrap();
        r.put("a.txt", b"two", 20);

        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.conflicts, vec!["a (server).txt"]);
        assert_eq!(rep.pending_conflicts, vec!["a (server).txt"]);

        // later passes report nothing new but the conflict is still pending
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert!(rep.conflicts.is_empty());
        assert_eq!(rep.pending_conflicts, vec!["a (server).txt"]);

        // the person resolves it by deleting the copy
        fs::remove_file(d.path().join("a (server).txt")).unwrap();
        assert!(sync(d.path(), &r, LIM)
            .unwrap()
            .pending_conflicts
            .is_empty());
    }

    #[test]
    fn unknown_history_with_different_local_content_is_a_conflict() {
        let d = tempfile::tempdir().unwrap();
        fs::write(d.path().join("a.txt"), "mine").unwrap();
        let r = FakeRemote::default();
        r.put("a.txt", b"theirs", 10);
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(read(d.path(), "a.txt"), "mine");
        assert_eq!(rep.conflicts.len(), 1);
    }

    #[test]
    fn identical_local_file_is_just_recorded() {
        let d = tempfile::tempdir().unwrap();
        fs::write(d.path().join("a.txt"), "same").unwrap();
        let r = FakeRemote::default();
        r.put("a.txt", b"same", 10);
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.changed(), 0);
        assert!(rep.errors.is_empty());
    }

    #[test]
    fn hostile_paths_are_skipped_and_nothing_escapes() {
        let d = tempfile::tempdir().unwrap();
        let outer = d.path().join("folder");
        let r = FakeRemote::default();
        for (i, p) in [
            "../evil.txt",
            "/abs.txt",
            "a/../../evil.txt",
            "a\\b.txt",
            "c:evil",
            "in/x.txt",
            ".fab-sync.json",
            "a//b.txt",
        ]
        .iter()
        .enumerate()
        {
            r.put(p, b"x", 10 + i as i64);
        }
        r.put("ok.txt", b"fine", 99);
        let rep = sync(&outer, &r, LIM).unwrap();
        assert_eq!(rep.downloaded, vec!["ok.txt"]);
        assert_eq!(rep.skipped.len(), 8);
        assert!(!d.path().join("evil.txt").exists());
        assert!(!outer.join("in/x.txt").exists());
        assert!(rep.errors.is_empty());
    }

    #[cfg(unix)]
    #[test]
    fn symlinked_folder_cannot_redirect_writes() {
        let d = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        let root = d.path().join("f");
        fs::create_dir_all(&root).unwrap();
        std::os::unix::fs::symlink(outside.path(), root.join("docs")).unwrap();
        let r = FakeRemote::default();
        r.put("docs/steal.txt", b"x", 10);
        let rep = sync(&root, &r, LIM).unwrap();
        assert_eq!(rep.skipped.len(), 1);
        assert!(!outside.path().join("steal.txt").exists());
    }

    #[test]
    fn checksum_mismatch_is_rejected_and_retried() {
        let d = tempfile::tempdir().unwrap();
        let r = FakeRemote::default();
        r.put("a.txt", b"good", 10);
        r.corrupt.borrow_mut().push("a.txt".into());
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.errors.len(), 1);
        assert!(!d.path().join("a.txt").exists());

        r.corrupt.borrow_mut().clear();
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.downloaded, vec!["a.txt"]);
    }

    #[test]
    fn failed_file_holds_the_cursor_back_but_later_files_are_not_lost() {
        let d = tempfile::tempdir().unwrap();
        let r = FakeRemote::default();
        r.put("a.txt", b"a", 10);
        r.put("b.txt", b"b", 20);
        r.put("c.txt", b"c", 30);
        r.fail_download.borrow_mut().push("b.txt".into());
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.errors.len(), 1);
        assert!(d.path().join("a.txt").exists() && d.path().join("c.txt").exists());
        assert!(!d.path().join("b.txt").exists());

        r.fail_download.borrow_mut().clear();
        r.downloads.borrow_mut().clear();
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.downloaded, vec!["b.txt"]);
        // c.txt was re-listed but already recorded → not downloaded again
        assert_eq!(*r.downloads.borrow(), vec!["b.txt".to_string()]);
    }

    #[test]
    fn oversize_files_are_skipped_not_failed() {
        let d = tempfile::tempdir().unwrap();
        let r = FakeRemote::default();
        r.put("big.bin", &[0u8; 100], 10);
        let lim = Limits {
            download: 10,
            upload: 10,
        };
        let rep = sync(d.path(), &r, lim).unwrap();
        assert_eq!(rep.skipped.len(), 1);
        assert!(rep.errors.is_empty());
    }

    #[test]
    fn uploads_new_and_changed_files_once() {
        let d = tempfile::tempdir().unwrap();
        let r = FakeRemote::default();
        fs::create_dir_all(d.path().join("in/data")).unwrap();
        fs::write(d.path().join("in/q3.csv"), "a,b").unwrap();
        fs::write(d.path().join("in/data/x.txt"), "x").unwrap();
        fs::write(d.path().join("in/.hidden"), "no").unwrap();

        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.uploaded, vec!["data/x.txt", "q3.csv"]);
        assert_eq!(rep.uploaded.len(), 2);

        assert_eq!(sync(d.path(), &r, LIM).unwrap().uploaded.len(), 0);
        fs::write(d.path().join("in/q3.csv"), "a,b,c").unwrap();
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(rep.uploaded, vec!["q3.csv"]);
        assert_eq!(r.uploads.borrow().len(), 3);
    }

    #[test]
    fn oversize_upload_is_reported() {
        let d = tempfile::tempdir().unwrap();
        fs::create_dir_all(d.path().join("in")).unwrap();
        fs::write(d.path().join("in/big"), vec![0u8; 100]).unwrap();
        let r = FakeRemote::default();
        let rep = sync(
            d.path(),
            &r,
            Limits {
                download: 10,
                upload: 10,
            },
        )
        .unwrap();
        assert_eq!(rep.errors.len(), 1);
        assert!(r.uploads.borrow().is_empty());
    }

    #[test]
    fn corrupt_state_starts_over_without_overwriting_anything() {
        let d = tempfile::tempdir().unwrap();
        let r = FakeRemote::default();
        r.put("a.txt", b"server", 10);
        sync(d.path(), &r, LIM).unwrap();
        fs::write(d.path().join("a.txt"), "edited").unwrap();
        fs::write(d.path().join(STATE_FILE), "{not json").unwrap();
        let rep = sync(d.path(), &r, LIM).unwrap();
        assert_eq!(read(d.path(), "a.txt"), "edited");
        assert_eq!(rep.conflicts.len(), 1);
        assert!(d.path().join(format!("{STATE_FILE}.corrupt")).exists());
    }

    #[test]
    fn recent_files_are_newest_first_and_skip_upload_area_and_hidden() {
        let d = tempfile::tempdir().unwrap();
        fs::create_dir_all(d.path().join("in")).unwrap();
        fs::create_dir_all(d.path().join("summaries")).unwrap();
        fs::write(d.path().join("in/up.txt"), "x").unwrap();
        fs::write(d.path().join(STATE_FILE), "{}").unwrap();
        fs::write(d.path().join("old.txt"), "x").unwrap();
        std::thread::sleep(std::time::Duration::from_millis(30));
        fs::write(d.path().join("summaries/new.md"), "x").unwrap();
        assert_eq!(
            recent_files(d.path(), 5),
            vec!["summaries/new.md", "old.txt"]
        );
    }
}
