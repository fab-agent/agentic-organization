"""
Server side of the signed workspace manifest (ADR-0028, building on ADR-0027).

For one signed-in person this resolves the role-based profile (layout + mods) from an
on-disk catalog, allocates the next generation atomically, signs a manifest with the
server's signing key, and says what a fresh client must require (bootstrap floors).

Fail closed: if the root public key, the signing key, its root-signed certificate or the
catalog is missing or invalid, nothing is signed (`WorkspaceUnavailable`). The server
never creates a root key or a certificate for itself.

On disk, under WORKSPACE_DIR (default `data/workspace`):

    root.pub                      base64 root public key (or env WORKSPACE_ROOT_PUB)
    signing.key                   base64 Ed25519 private key, mode 0600, owner only
    signing.cert.json             certificate for that key, issued offline by the root
    crl.json                      optional cumulative revocation list from the root
    catalog/profiles.json         which role/department gets which layout and mods
    catalog/layouts/<id>.json     layout files
    catalog/mods/<name>/<ver>/..  mod files (any depth)

Every file is reached by walking from the WORKSPACE_DIR descriptor one component at a
time with O_NOFOLLOW (`openat` style), so a symlink anywhere below it, a directory swapped
while we read, or a special file cannot lead outside the tree. The catalog must be a
regular tree: symlinks, special files and hard-linked files are refused.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import select

from models import (
    AppConfig,
    CompanyMember,
    Department,
    Personnel,
    WorkspaceManifestState,
)
from services import workspace_manifest as wm

DEFAULT_TTL = 6 * 3600
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_CATALOG_DEPTH = 8
MAX_ENTRIES_PER_DIR = 2048
MAX_VISITS = 8192  # directory entries looked at for one profile
_SAFE_MAX_GENERATION = 2**53 - 1
_CRL_HIGHWATER_KEY = "workspace.crl_highwater"

_O_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_O_FILE = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)


class WorkspaceUnavailable(Exception):
    """Cannot issue a manifest. `reason` is a stable, value-free code (503)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def workspace_dir() -> str:
    return os.path.realpath(os.getenv("WORKSPACE_DIR", "data/workspace"))


# ── confined file access ─────────────────────────────────────────────────────


def _open_dir(parent_fd: int | None, name: str) -> int:
    try:
        return os.open(name, _O_DIR, dir_fd=parent_fd)
    except OSError as e:
        raise WorkspaceUnavailable("catalog_unreadable") from e


def _walk_to(root_fd: int, parts: list[str]) -> int:
    """Descend one component at a time; every step refuses a symlink."""
    fd = os.dup(root_fd)
    try:
        for p in parts:
            nxt = _open_dir(fd, p)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_fd(
    dir_fd: int, name: str, *, private: bool = False, limit: int = MAX_FILE_BYTES
) -> bytes:
    """Read one regular file by name from an open directory. Never blocks on a FIFO,
    refuses a hard-linked file, and rejects (never truncates) a file that is or grows
    beyond `limit`."""
    try:
        fd = os.open(name, _O_FILE, dir_fd=dir_fd)
    except OSError as e:
        raise WorkspaceUnavailable("file_unreadable") from e
    try:
        with os.fdopen(fd, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size > limit or st.st_nlink != 1:
                raise WorkspaceUnavailable("file_invalid")
            if private and (st.st_mode & 0o077 or st.st_uid != os.geteuid()):
                raise WorkspaceUnavailable("signing_key_permissions")
            data = f.read(limit + 1)
    except OSError as e:  # fstat / read / close failing is an IO fault, not a crash
        raise WorkspaceUnavailable("file_unreadable") from e
    if len(data) > limit:
        raise WorkspaceUnavailable("file_invalid")
    return data


def _read_rel(
    root_fd: int, rel: str, *, private: bool = False, limit: int = MAX_FILE_BYTES
) -> bytes:
    parts = rel.split("/")
    dfd = _walk_to(root_fd, parts[:-1])
    try:
        return _read_fd(dfd, parts[-1], private=private, limit=limit)
    finally:
        os.close(dfd)


def _lexists(root_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True  # present but not inspectable: treat as present, then fail on read


def _scan(
    dir_fd: int,
    prefix: str,
    depth: int,
    budget: dict,
) -> list[tuple[str, str, os.stat_result]]:
    """(relative path, path from the catalog root, stat) for every file below an open
    directory. Entries, counts, depth and bytes are limited as we go, before anything is
    read; a file that vanishes or is swapped mid-walk is a controlled 503."""
    if depth > MAX_CATALOG_DEPTH:
        raise WorkspaceUnavailable("catalog_too_deep")
    out: list[tuple[str, str, os.stat_result]] = []
    entries = []
    try:
        with os.scandir(dir_fd) as it:
            for e in it:
                entries.append(e)
                if len(entries) > MAX_ENTRIES_PER_DIR:
                    raise WorkspaceUnavailable("catalog_too_large")
    except OSError as e:
        raise WorkspaceUnavailable("catalog_changed") from e
    budget["visits"] = budget.get("visits", 0) + len(entries)
    if budget["visits"] > MAX_VISITS:
        raise WorkspaceUnavailable("catalog_too_large")
    for e in sorted(entries, key=lambda x: x.name):
        try:
            st = os.stat(e.name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError as err:
            raise WorkspaceUnavailable("catalog_changed") from err
        rel = f"{prefix}{e.name}"
        if stat.S_ISLNK(st.st_mode):
            raise WorkspaceUnavailable("catalog_symlink")
        if stat.S_ISDIR(st.st_mode):
            child = _open_dir(dir_fd, e.name)
            try:
                out += _scan(child, rel + "/", depth + 1, budget)
            finally:
                os.close(child)
        elif stat.S_ISREG(st.st_mode):
            budget["files"] += 1
            budget["bytes"] += st.st_size
            if (
                budget["files"] > wm.MAX_FILES_PER_MOD
                or budget["bytes"] > wm.MAX_TOTAL_BYTES
                or st.st_size > MAX_FILE_BYTES
            ):
                raise WorkspaceUnavailable("catalog_too_large")
            out.append((rel, rel, st))
        else:
            raise WorkspaceUnavailable("catalog_special_file")
    return out


# ── signer ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Signer:
    private_b64: str
    cert: dict
    root_pub: str
    epoch: int
    kid: str
    crl: dict | None
    crl_number: int


@dataclass(frozen=True)
class CrlView:
    """The published revocation list and its number, independent of the signing key: a
    revoked signing key must not stop clients from learning that it is revoked."""

    crl: dict | None
    crl_number: int


def _load_crl(
    root_fd: int, root_pub: str, now: int
) -> tuple[dict | None, int, frozenset]:
    crl, number, revoked = None, 0, frozenset()
    if _lexists(root_fd, "crl.json"):  # a dangling link or odd file is not "absent"
        try:
            crl = json.loads(_read_fd(root_fd, "crl.json", limit=1024 * 1024))
            st = wm.verify_crl(crl, root_pub, wm.ClientState(), now)
        except WorkspaceUnavailable:
            raise WorkspaceUnavailable("crl_invalid") from None
        except (wm.ManifestError, ValueError) as e:
            raise WorkspaceUnavailable("crl_invalid") from e
        number, revoked = st.crl_number, st.revoked
    return crl, number, revoked


def load_crl(now: int) -> CrlView:
    """Read the root public key and the CRL only (no signing key needed)."""
    root_fd = _open_dir(None, workspace_dir())
    try:
        try:
            root_pub = (
                os.getenv("WORKSPACE_ROOT_PUB")
                or _read_fd(root_fd, "root.pub", limit=4096).decode().strip()
            )
        except WorkspaceUnavailable:
            raise
        except (ValueError, UnicodeDecodeError) as e:
            raise WorkspaceUnavailable("signing_material_invalid") from e
        except OSError as e:
            raise WorkspaceUnavailable("file_unreadable") from e
        crl, number, _ = _load_crl(root_fd, root_pub, now)
        return CrlView(crl, number)
    finally:
        os.close(root_fd)


def load_signer(now: int) -> Signer:
    root_fd = _open_dir(None, workspace_dir())
    try:
        try:
            root_pub = (
                os.getenv("WORKSPACE_ROOT_PUB")
                or _read_fd(root_fd, "root.pub", limit=4096).decode().strip()
            )
            priv = (
                _read_fd(root_fd, "signing.key", private=True, limit=4096)
                .decode()
                .strip()
            )
            cert = json.loads(_read_fd(root_fd, "signing.cert.json", limit=65536))
            cp = wm.check_certificate(cert, root_pub, now)
            pub = base64.b64encode(wm._pub_raw(wm.load_private(priv))).decode()
        except WorkspaceUnavailable:
            raise
        except wm.ManifestError as e:
            raise WorkspaceUnavailable(f"signing_{e.code}") from e
        except (ValueError, TypeError, UnicodeDecodeError) as e:
            raise WorkspaceUnavailable("signing_material_invalid") from e
        except OSError as e:
            raise WorkspaceUnavailable("file_unreadable") from e
        if wm.key_id(pub) != cp["kid"]:
            raise WorkspaceUnavailable("signing_key_cert_mismatch")

        crl, crl_number, revoked = _load_crl(root_fd, root_pub, now)
        if cp["kid"] in revoked:
            raise WorkspaceUnavailable("signing_key_revoked")
        return Signer(priv, cert, root_pub, cp["epoch"], cp["kid"], crl, crl_number)
    finally:
        os.close(root_fd)


def _parse_highwater(value: object) -> int:
    """ASCII decimal within the protocol's safe-integer range, or an error. (str.isdigit
    accepts characters int() rejects, and a very long digit string trips Python's
    int-conversion limit - both used to escape as a 500.)"""
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdigit()
        or not 1 <= len(value) <= 16
    ):
        raise WorkspaceUnavailable("crl_highwater_invalid")
    n = int(value)
    if n > _SAFE_MAX_GENERATION:
        raise WorkspaceUnavailable("crl_highwater_invalid")
    return n


def enforce_crl_highwater(session, signer: Signer | CrlView) -> None:
    """The highest valid revocation list this server has ever served never goes
    backwards, and once one was served it cannot silently disappear (a restored old file
    or a deleted one would otherwise lower the bootstrap checkpoint). The mark is raised
    with a compare-and-set, so two processes can never lower each other's value.

    Recovery after serving a wrong (but root-signed) high number is NOT to lower the
    mark: the root publishes a corrective list with a still higher number."""
    new = signer.crl_number
    try:
        for _ in range(8):
            row = session.get(AppConfig, _CRL_HIGHWATER_KEY)
            if row is not None:
                session.refresh(row)  # never decide on a stale identity-map value
            if row is None:
                if new == 0:
                    return
                session.add(AppConfig(key=_CRL_HIGHWATER_KEY, value=str(new)))
                try:
                    session.commit()
                    return
                except IntegrityError:
                    session.rollback()
                    continue
            seen = _parse_highwater(row.value)  # corrupt state is not "zero"
            if new < seen:
                raise WorkspaceUnavailable(
                    "crl_rollback" if signer.crl is not None else "crl_missing"
                )
            if new == seen:
                return
            res = session.exec(
                update(AppConfig)
                .where(
                    AppConfig.key == _CRL_HIGHWATER_KEY, AppConfig.value == row.value
                )
                .values(value=str(new))
            )
            session.commit()
            if res.rowcount == 1:
                return
            session.rollback()
    except SQLAlchemyError as e:
        session.rollback()
        raise WorkspaceUnavailable("state_unavailable") from e
    raise WorkspaceUnavailable("crl_contention")


# ── catalog and profiles (closed schema) ─────────────────────────────────────


@dataclass(frozen=True)
class Profile:
    id: str
    layout: str
    mods: tuple[tuple[str, str], ...]
    min_client_version: str


def _bad() -> WorkspaceUnavailable:
    return WorkspaceUnavailable("profiles_invalid")


def _only(d: object, allowed: set[str]) -> dict:
    if not isinstance(d, dict) or set(d) - allowed:
        raise _bad()
    return d


def _str_list(v: object) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise _bad()
    return v


_PROFILE_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _name(v: object) -> str:
    try:
        return wm._check_name(v)
    except wm.ManifestError as e:
        raise _bad() from e


def _profile_from(d: object, pid: str, *, allow_match: bool = True) -> Profile:
    allowed = {"layout", "mods", "min_client_version"}
    if allow_match:
        allowed |= {"id", "match"}
    d = _only(d, allowed)
    raw_id = d.get("id", pid)
    if not isinstance(raw_id, str) or not _PROFILE_ID.fullmatch(raw_id):
        raise _bad()
    layout = _name(d.get("layout"))
    raw_mods = d.get("mods", [])
    if not isinstance(raw_mods, list) or len(raw_mods) > wm.MAX_MODS:
        raise _bad()
    mods = []
    for m in raw_mods:
        m = _only(m, {"name", "version"})
        version = m.get("version")
        if not isinstance(version, str) or not wm._VERSION.fullmatch(version):
            raise _bad()
        mods.append((_name(m.get("name")), version))
    if len({n for n, _v in mods}) != len(
        mods
    ):  # the manifest forbids a repeated mod name
        raise _bad()
    mcv = d.get("min_client_version", "0.0.0")
    if not isinstance(mcv, str) or not wm._VERSION.fullmatch(mcv):
        raise _bad()
    return Profile(raw_id, layout, tuple(mods), mcv)


def _validate_profile(p: object, pid: str) -> Profile:
    p = _only(p, {"id", "match", "layout", "mods", "min_client_version"})
    match = _only(p.get("match", {}), {"roles", "departments", "companies"})
    for key in match:
        _str_list(match[key])
    return _profile_from(p, pid)


def _load_profiles(root_fd: int) -> dict:
    raw = _read_rel(root_fd, "catalog/profiles.json", limit=1024 * 1024)
    try:
        doc = wm.parse_wire(raw, max_bytes=1024 * 1024)
    except wm.ManifestError as e:
        raise _bad() from e
    doc = _only(doc, {"v", "profiles", "defaults"})
    if not wm._v1(doc.get("v")):
        raise _bad()
    if not isinstance(doc.get("profiles", []), list):
        raise _bad()
    # Validate the whole file, not only the entry this person happens to reach: a broken
    # `defaults` or a later profile is a configuration error for everyone.
    ids: set[str] = set()
    for i, p in enumerate(doc.get("profiles", [])):
        prof = _validate_profile(p, f"profile-{i}")
        if prof.id in ids or prof.id == "default":  # audit reasons must be unambiguous
            raise _bad()
        ids.add(prof.id)
    if "defaults" in doc:
        _profile_from(doc["defaults"], "default", allow_match=False)
    return doc


def person_context(session, user_id: str, person: Personnel, company_id: str) -> dict:
    """Who the person is for matching: membership roles, department ids and slugs
    (the department and its ancestors), company id. Taken from the database only. A
    scoped membership (a department head of ANOTHER department) does not count as a
    role of this person's profile."""
    from services.policy_engine import _department_chain

    ids = _department_chain(session, person.department_id)

    def counts(m) -> bool:
        if m.role == "agent_owner":
            # Only a membership scoped to an AGENT of this company counts
            # (authz.scope_valid). A null, department or human scope is invalid for this
            # role, so it must not pass as a general company or department scope below.
            if not m.scope_id:
                return False
            agent = session.get(Personnel, m.scope_id)
            return bool(
                agent and agent.type == "agent" and agent.company_id == company_id
            )
        return m.scope_id is None or m.scope_id in ids

    roles = {
        m.role
        for m in session.exec(
            select(CompanyMember).where(
                CompanyMember.user_id == user_id, CompanyMember.company_id == company_id
            )
        ).all()
        if counts(m)
    } or {"user"}  # no relevant membership: the plain `user` role (a product default)
    slugs = {d.slug for d in (session.get(Department, i) for i in ids) if d}
    return {"roles": roles, "departments": set(ids) | slugs, "company": company_id}


def resolve_profile(root_fd: int, ctx: dict) -> Profile:
    doc = _load_profiles(root_fd)
    for i, p in enumerate(doc.get("profiles", [])):
        match = p.get("match", {})
        ok = True
        for key, have in (
            ("roles", ctx["roles"]),
            ("departments", ctx["departments"]),
            ("companies", {ctx["company"]}),
        ):
            if key in match:
                ok = ok and bool(have & set(_str_list(match[key])))
        if ok:
            return _validate_profile(p, f"profile-{i}")
    if "defaults" in doc:
        return _profile_from(doc["defaults"], "default", allow_match=False)
    raise WorkspaceUnavailable("no_profile")


@dataclass(frozen=True)
class Resolved:
    profile: Profile
    layout: dict  # {"id","sha256","size"}
    mods: list[dict]  # manifest `mods` entries
    files: dict[str, str]  # sha256 -> path below the catalog root


_cache: OrderedDict[tuple, Resolved] = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_MAX = 64


def _stat_signature(root_fd: int, profile: Profile) -> tuple:
    """Cheap fingerprint of every file the profile uses (no reads, no hashing): changes
    whenever one is replaced, rewritten or resized."""
    sig: list[tuple] = []
    cat = _walk_to(root_fd, ["catalog"])
    try:
        lay = _walk_to(cat, ["layouts"])
        try:
            st = os.stat(f"{profile.layout}.json", dir_fd=lay, follow_symlinks=False)
            sig.append(
                ("layout", st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            )
        except OSError as e:
            raise WorkspaceUnavailable("file_unreadable") from e
        finally:
            os.close(lay)
        shared = {"bytes": 0}
        for name, version in profile.mods:
            if not wm._NAME.fullmatch(name) or not wm._VERSION.fullmatch(version):
                raise WorkspaceUnavailable("mod_name_invalid")
            try:
                mfd = _walk_to(cat, ["mods", name, version])
            except WorkspaceUnavailable:
                raise WorkspaceUnavailable("mod_missing") from None
            try:
                budget = {
                    "files": 0,
                    "bytes": shared["bytes"],
                    "visits": shared.get("visits", 0),
                }
                for rel, _p, st in _scan(mfd, "", 0, budget):
                    sig.append(
                        (
                            name,
                            rel,
                            st.st_ino,
                            st.st_size,
                            st.st_mtime_ns,
                            st.st_ctime_ns,
                        )
                    )
                shared["bytes"] = budget["bytes"]
                shared["visits"] = budget["visits"]
            finally:
                os.close(mfd)
    finally:
        os.close(cat)
    return (profile, tuple(sig))


def _validate_catalog(profile: Profile, layout: dict, mods: list[dict]) -> None:
    """The same shape and limit checks the manifest gets, so issuing and downloading
    reject exactly the same catalogs (names, portable paths, counts, total size)."""
    body = {
        "typ": "fab-workspace-manifest",
        "v": 1,
        "epoch": 1,
        "company_id": "c",
        "person_id": "p",
        "aud": "herdr-provisioner",
        "generation": 1,
        "issued_at": 1,
        "expires_at": 2,
        "min_client_version": profile.min_client_version,
        "gateway_url": "https://example.test",
        "layout": layout,
        "mods": mods,
    }
    try:
        wm._validate_body(body)
    except wm.ManifestError as e:
        raise WorkspaceUnavailable(f"manifest_{e.code}") from e


def resolve_content(root_fd: int, profile: Profile) -> Resolved:
    if not wm._NAME.fullmatch(profile.layout):
        raise WorkspaceUnavailable("layout_name_invalid")
    if len(profile.mods) > wm.MAX_MODS:
        raise WorkspaceUnavailable("catalog_too_large")
    key = _stat_signature(root_fd, profile)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit

    files: dict[str, str] = {}
    data = _read_rel(root_fd, f"catalog/layouts/{profile.layout}.json")
    sha = hashlib.sha256(data).hexdigest()
    files[sha] = f"catalog/layouts/{profile.layout}.json"
    layout = {"id": profile.layout, "sha256": sha, "size": len(data)}
    mods = []
    shared = {"bytes": len(data)}
    for name, version in profile.mods:
        mfd = _walk_to(root_fd, ["catalog", "mods", name, version])
        try:
            entries = []
            budget = {
                "files": 0,
                "bytes": shared["bytes"],
                "visits": shared.get("visits", 0),
            }
            for rel, _p, _st in _scan(mfd, "", 0, budget):
                blob = _read_rel(mfd, rel)
                h = hashlib.sha256(blob).hexdigest()
                files[h] = f"catalog/mods/{name}/{version}/{rel}"
                entries.append({"path": rel, "sha256": h, "size": len(blob)})
            shared["bytes"] = budget["bytes"]
            shared["visits"] = budget["visits"]
        finally:
            os.close(mfd)
        mods.append({"name": name, "version": version, "files": entries})
    _validate_catalog(profile, layout, mods)
    resolved = Resolved(profile, layout, mods, files)
    with _cache_lock:
        _cache[key] = resolved
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return resolved


# ── generation and issuance ──────────────────────────────────────────────────


def allocate_generation(session, company_id: str, person_id: str, epoch: int) -> int:
    """Next generation for this person, never reused while the state row exists, safe
    under concurrent requests (compare-and-set on the stored value; a unique key stops
    double creation). Losing the row (restore, manual delete) is recovered by raising
    the signing epoch (ADR-0027), which restarts every client's floor."""
    try:
        for _ in range(8):
            # populate_existing: after a lost compare-and-set another connection has changed the
            # row, and a session that does not expire on commit would hand back its old copy, so
            # every retry would lose again (ADR-0028).
            row = session.exec(
                select(WorkspaceManifestState)
                .where(
                    WorkspaceManifestState.company_id == company_id,
                    WorkspaceManifestState.person_id == person_id,
                )
                .execution_options(populate_existing=True)
            ).first()
            if row is None:
                session.add(
                    WorkspaceManifestState(
                        company_id=company_id,
                        person_id=person_id,
                        epoch=epoch,
                        generation=1,
                    )
                )
                try:
                    session.commit()
                    return 1
                except IntegrityError:
                    session.rollback()
                    continue
            if row.epoch > epoch:
                raise WorkspaceUnavailable("signing_epoch_behind_state")
            new_gen = 1 if row.epoch < epoch else row.generation + 1
            if new_gen > _SAFE_MAX_GENERATION:
                raise WorkspaceUnavailable("generation_exhausted")
            res = session.exec(
                update(WorkspaceManifestState)
                .where(
                    WorkspaceManifestState.id == row.id,
                    WorkspaceManifestState.epoch == row.epoch,
                    WorkspaceManifestState.generation == row.generation,
                )
                .values(epoch=epoch, generation=new_gen)
            )
            session.commit()
            if res.rowcount == 1:
                return new_gen
            session.rollback()
    except SQLAlchemyError as e:
        session.rollback()
        raise WorkspaceUnavailable("state_unavailable") from e
    raise WorkspaceUnavailable("generation_contention")


def manifest_ttl() -> int:
    try:
        return max(
            300, min(int(os.getenv("WORKSPACE_MANIFEST_TTL", DEFAULT_TTL)), 86400)
        )
    except ValueError:
        return DEFAULT_TTL


def _resolve_for(
    session, root_fd: int, user_id: str, person: Personnel, company_id: str
):
    ctx = person_context(session, user_id, person, company_id)
    try:
        return resolve_content(root_fd, resolve_profile(root_fd, ctx))
    except (TypeError, KeyError, AttributeError, ValueError) as e:
        raise _bad() from e  # a shape error in config is a 503, never a 500
    except OSError as e:
        raise WorkspaceUnavailable("catalog_changed") from e  # raced with a publisher


def issue_manifest(
    session,
    *,
    user_id: str,
    person: Personnel,
    company_id: str,
    gateway_url: str,
    now: int | None = None,
) -> dict:
    """The signed manifest for this person plus the bootstrap floors for a fresh
    client. Raises WorkspaceUnavailable; signs nothing in that case."""
    now = int(time.time()) if now is None else now
    signer = load_signer(now)
    enforce_crl_highwater(session, signer)
    root_fd = _open_dir(None, workspace_dir())
    try:
        resolved = _resolve_for(session, root_fd, user_id, person, company_id)
    finally:
        os.close(root_fd)

    cp = signer.cert["payload"]
    issued = max(now, cp["not_before"])
    expires = min(issued + manifest_ttl(), cp["not_after"])
    if expires <= issued:
        raise WorkspaceUnavailable("signing_cert_expired")

    generation = allocate_generation(session, company_id, person.id, signer.epoch)
    body = {
        "company_id": company_id,
        "person_id": person.id,
        "aud": "herdr-provisioner",
        "generation": generation,
        "issued_at": issued,
        "expires_at": expires,
        "min_client_version": resolved.profile.min_client_version,
        "gateway_url": gateway_url,
        "layout": resolved.layout,
        "mods": resolved.mods,
    }
    try:
        envelope = wm.sign_manifest(signer.private_b64, signer.cert, body)
    except wm.ManifestError as e:
        raise WorkspaceUnavailable(f"manifest_{e.code}") from e
    return {
        "manifest": envelope,
        # Floors a client with no history must require. They authenticate through the
        # signed-in session, not through the signature. The generation is the one just
        # issued, the epoch is the signing epoch, and the CRL number never goes below
        # the highest list this server has served (enforce_crl_highwater).
        "bootstrap": {
            "min_generation": generation,
            "min_epoch": signer.epoch,
            "min_crl_number": signer.crl_number,
        },
        "profile": resolved.profile.id,
    }


def file_for_person(
    session, *, user_id: str, person: Personnel, company_id: str, sha256: str
) -> bytes:
    """Bytes of one catalog file, only if it belongs to this person's own profile.
    Uses the cached, validated index (a stat per file, one read for the requested file)."""
    if not wm._SHA256.fullmatch(sha256):
        raise WorkspaceUnavailable("bad_hash")
    root_fd = _open_dir(None, workspace_dir())
    try:
        resolved = _resolve_for(session, root_fd, user_id, person, company_id)
        rel = resolved.files.get(sha256)
        if rel is None:
            raise KeyError(sha256)
        data = _read_rel(root_fd, rel)
    finally:
        os.close(root_fd)
    if hashlib.sha256(data).hexdigest() != sha256:  # changed since it was listed
        raise WorkspaceUnavailable("file_changed")
    return data
