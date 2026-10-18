"""File access inside a workspace volume, without following links.

Runs *inside* a throw-away container (the workspace image, `--network none`, the agent's
uid, read-only root, the files volume mounted at /workspace) so that:
  * the work is done with the agent's own permissions, not the daemon's (nothing that is
    only root-readable in the container can be reached);
  * every path component is opened with O_NOFOLLOW relative to the parent directory fd, so
    a link anywhere on the path (or a replaced `out/` directory) is refused, and a link
    swapped in during the walk cannot redirect it;
  * only regular files are listed, read or written; sizes are capped before any data moves.

Exit codes: 0 ok, 3 not found / not a regular file, 4 too large, 5 refused (bad path/link).
"""

SCRIPT = r"""
import hashlib, json, os, stat, sys

ROOT = "/workspace"
CAP = int(os.environ.get("CAP", "104857600"))
MAX_ENTRIES = 5000
FLAGS_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def die(code):
    sys.exit(code)


def open_dir(parts):
    fd = os.open(ROOT, FLAGS_DIR)
    try:
        for p in parts:
            nfd = os.open(p, FLAGS_DIR, dir_fd=fd)
            os.close(fd)
            fd = nfd
        return fd
    except OSError:
        os.close(fd)
        die(3)


def open_file(rel):
    parts = rel.split("/")
    dfd = open_dir(parts[:-1])
    try:
        ffd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    except OSError:
        die(3)
    finally:
        os.close(dfd)
    st = os.fstat(ffd)
    if not stat.S_ISREG(st.st_mode):
        die(3)
    if st.st_size > CAP:
        die(4)
    return ffd, st


def walk(dfd, prefix, out, budget):
    with os.scandir(dfd) as it:
        entries = sorted(it, key=lambda e: e.name)
    for e in entries:
        if len(out) >= MAX_ENTRIES:
            die(4)
        st = os.stat(e.name, dir_fd=dfd, follow_symlinks=False)
        if stat.S_ISDIR(st.st_mode):
            try:
                sub = os.open(e.name, FLAGS_DIR, dir_fd=dfd)
            except OSError:
                continue
            try:
                walk(sub, prefix + e.name + "/", out, budget)
            finally:
                os.close(sub)
        elif stat.S_ISREG(st.st_mode):
            try:
                fd = os.open(e.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
            except OSError:
                continue
            if st.st_size > CAP:
                # listed (so the person sees it) but never read: no hash, download is refused
                os.close(fd)
                out.append({"path": prefix + e.name, "size": st.st_size, "sha256": "",
                            "mtime_ns": st.st_mtime_ns})
                continue
            h = hashlib.sha256()
            n = 0
            with os.fdopen(fd, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    n += len(chunk)
                    budget[0] -= len(chunk)
                    if budget[0] < 0 or n > CAP:
                        die(4)
                    h.update(chunk)
            out.append({"path": prefix + e.name, "size": n, "sha256": h.hexdigest(),
                        "mtime_ns": st.st_mtime_ns})


def main():
    mode, rel = sys.argv[1], sys.argv[2]
    if mode == "list":
        out = []
        walk(open_dir([rel]), "", out, [int(os.environ.get("LIST_BUDGET", "419430400"))])
        sys.stdout.write(json.dumps(out))
    elif mode == "read":
        ffd, st = open_file(rel)
        with os.fdopen(ffd, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)
    elif mode == "write":
        parts = rel.split("/")
        fd = os.open(ROOT, FLAGS_DIR)
        for p in parts[:-1]:
            try:
                os.mkdir(p, 0o755, dir_fd=fd)
            except FileExistsError:
                pass
            try:
                nfd = os.open(p, FLAGS_DIR, dir_fd=fd)  # a link here is refused
            except OSError:
                die(5)
            os.close(fd)
            fd = nfd
        tmp = ".upload-" + os.urandom(6).hex()
        wfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
        total = 0
        try:
            with os.fdopen(wfd, "wb") as f:
                while True:
                    chunk = sys.stdin.buffer.read(1 << 20)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > CAP:
                        raise OverflowError
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
            os.rename(tmp, parts[-1], src_dir_fd=fd, dst_dir_fd=fd)  # replaces, never follows
        except OverflowError:
            os.unlink(tmp, dir_fd=fd)
            die(4)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=fd)
            except OSError:
                pass
            raise
    else:
        die(5)


main()
"""
