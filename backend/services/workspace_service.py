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
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import update
from sqlmodel import select

from models import CompanyMember, Department, Personnel, WorkspaceManifestState
from services import workspace_manifest as wm

DEFAULT_TTL = 6 * 3600
MAX_FILE_BYTES = 16 * 1024 * 1024


class WorkspaceUnavailable(Exception):
    """Cannot issue a manifest. `reason` is a stable, value-free code (503)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def workspace_dir() -> Path:
    return Path(os.getenv("WORKSPACE_DIR", "data/workspace"))


# ── safe file access ─────────────────────────────────────────────────────────


def _read_regular(
    path: Path, *, private: bool = False, limit: int = MAX_FILE_BYTES
) -> bytes:
    """Open once with O_NOFOLLOW and check the descriptor we read (no swap window)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise WorkspaceUnavailable("file_unreadable") from e
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            raise WorkspaceUnavailable("file_invalid")
        if private and (st.st_mode & 0o077 or st.st_uid != os.geteuid()):
            raise WorkspaceUnavailable("signing_key_permissions")
        return f.read(limit + 1)[:limit]


def _walk_files(base: Path) -> list[tuple[str, Path]]:
    """(relative posix path, file) under `base`; any symlink or special file refuses."""
    out: list[tuple[str, Path]] = []
    stack = [base]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError as e:
            raise WorkspaceUnavailable("catalog_unreadable") from e
        for e in entries:
            if e.is_symlink():
                raise WorkspaceUnavailable("catalog_symlink")
            if e.is_dir(follow_symlinks=False):
                stack.append(Path(e.path))
            elif e.is_file(follow_symlinks=False):
                out.append((Path(e.path).relative_to(base).as_posix(), Path(e.path)))
            else:
                raise WorkspaceUnavailable("catalog_special_file")
    return sorted(out)


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


def load_signer(now: int) -> Signer:
    base = workspace_dir()
    root_pub = os.getenv("WORKSPACE_ROOT_PUB")
    if not root_pub:
        root_pub = _read_regular(base / "root.pub", limit=4096).decode().strip()
    try:
        priv = (
            _read_regular(base / "signing.key", private=True, limit=4096)
            .decode()
            .strip()
        )
        cert = json.loads(_read_regular(base / "signing.cert.json", limit=65536))
        cp = wm.check_certificate(cert, root_pub, now)
        pub = base64.b64encode(wm._pub_raw(wm.load_private(priv))).decode()
    except WorkspaceUnavailable:
        raise
    except (wm.ManifestError, ValueError, TypeError) as e:
        code = e.code if isinstance(e, wm.ManifestError) else "signing_material_invalid"
        raise WorkspaceUnavailable(f"signing_{code}") from e
    if wm.key_id(pub) != cp["kid"]:
        raise WorkspaceUnavailable("signing_key_cert_mismatch")

    crl, crl_number = None, 0
    crl_path = base / "crl.json"
    if crl_path.exists():
        try:
            crl = json.loads(_read_regular(crl_path, limit=1024 * 1024))
            st = wm.verify_crl(crl, root_pub, wm.ClientState(), now)
        except (wm.ManifestError, ValueError) as e:
            raise WorkspaceUnavailable("crl_invalid") from e
        if cp["kid"] in st.revoked:
            raise WorkspaceUnavailable("signing_key_revoked")
        crl_number = st.crl_number
    return Signer(priv, cert, root_pub, cp["epoch"], cp["kid"], crl, crl_number)


# ── catalog and profiles ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Profile:
    id: str
    layout: str
    mods: tuple[tuple[str, str], ...]
    min_client_version: str


def _load_profiles() -> dict:
    raw = _read_regular(
        workspace_dir() / "catalog" / "profiles.json", limit=1024 * 1024
    )
    try:
        doc = wm.parse_wire(raw, max_bytes=1024 * 1024)
    except wm.ManifestError as e:
        raise WorkspaceUnavailable("profiles_invalid") from e
    if not isinstance(doc, dict) or not wm._v1(doc.get("v")):
        raise WorkspaceUnavailable("profiles_invalid")
    return doc


def _profile_from(d: object, pid: str) -> Profile:
    if not isinstance(d, dict) or not isinstance(d.get("layout"), str):
        raise WorkspaceUnavailable("profiles_invalid")
    mods = []
    for m in d.get("mods", []):
        if (
            not isinstance(m, dict)
            or not isinstance(m.get("name"), str)
            or not isinstance(m.get("version"), str)
        ):
            raise WorkspaceUnavailable("profiles_invalid")
        mods.append((m["name"], m["version"]))
    mcv = d.get("min_client_version", "0.0.0")
    if not isinstance(mcv, str):
        raise WorkspaceUnavailable("profiles_invalid")
    return Profile(pid, d["layout"], tuple(mods), mcv)


def person_context(session, user_id: str, person: Personnel, company_id: str) -> dict:
    """Who the person is for matching: membership roles, department ids and slugs
    (the department and its ancestors), company id. Taken from the database only."""
    from services.policy_engine import _department_chain

    roles = {
        m.role
        for m in session.exec(
            select(CompanyMember).where(
                CompanyMember.user_id == user_id, CompanyMember.company_id == company_id
            )
        ).all()
    } or {"user"}
    ids = _department_chain(session, person.department_id)
    slugs = {d.slug for d in (session.get(Department, i) for i in ids) if d}
    return {"roles": roles, "departments": set(ids) | slugs, "company": company_id}


def resolve_profile(ctx: dict) -> Profile:
    doc = _load_profiles()
    for i, p in enumerate(doc.get("profiles", [])):
        match = p.get("match", {}) if isinstance(p, dict) else None
        if not isinstance(match, dict) or set(match) - {
            "roles",
            "departments",
            "companies",
        }:
            raise WorkspaceUnavailable("profiles_invalid")
        ok = True
        for key, have in (
            ("roles", ctx["roles"]),
            ("departments", ctx["departments"]),
            ("companies", {ctx["company"]}),
        ):
            if key in match:
                want = match[key]
                if not isinstance(want, list) or not all(
                    isinstance(x, str) for x in want
                ):
                    raise WorkspaceUnavailable("profiles_invalid")
                ok = ok and bool(have & set(want))
        if ok:
            return _profile_from(p, str(p.get("id", f"profile-{i}")))
    if "defaults" in doc:
        return _profile_from(doc["defaults"], "default")
    raise WorkspaceUnavailable("no_profile")


@dataclass(frozen=True)
class Resolved:
    profile: Profile
    layout: dict  # {"id","sha256","size"}
    mods: list[dict]  # manifest `mods` entries
    files: dict[str, Path]  # sha256 -> file (served by the files endpoint)


def resolve_content(profile: Profile) -> Resolved:
    base = workspace_dir() / "catalog"
    layout_path = base / "layouts" / f"{profile.layout}.json"
    if not wm._NAME.fullmatch(profile.layout):
        raise WorkspaceUnavailable("layout_name_invalid")
    data = _read_regular(layout_path)
    files: dict[str, Path] = {}
    sha = hashlib.sha256(data).hexdigest()
    files[sha] = layout_path
    layout = {"id": profile.layout, "sha256": sha, "size": len(data)}
    mods = []
    for name, version in profile.mods:
        if not wm._NAME.fullmatch(name) or not wm._VERSION.fullmatch(version):
            raise WorkspaceUnavailable("mod_name_invalid")
        root = base / "mods" / name / version
        if not root.is_dir() or root.is_symlink():
            raise WorkspaceUnavailable("mod_missing")
        entries = []
        for rel, path in _walk_files(root):
            blob = _read_regular(path)
            h = hashlib.sha256(blob).hexdigest()
            files[h] = path
            entries.append({"path": rel, "sha256": h, "size": len(blob)})
        mods.append({"name": name, "version": version, "files": entries})
    return Resolved(profile, layout, mods, files)


# ── generation and issuance ──────────────────────────────────────────────────


def allocate_generation(session, company_id: str, person_id: str, epoch: int) -> int:
    """Next generation for this person, never reused, safe under concurrent requests
    (compare-and-set on the stored value; a unique key stops double creation)."""
    from sqlalchemy.exc import IntegrityError

    for _ in range(8):
        row = session.exec(
            select(WorkspaceManifestState).where(
                WorkspaceManifestState.company_id == company_id,
                WorkspaceManifestState.person_id == person_id,
            )
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
    raise WorkspaceUnavailable("generation_contention")


def manifest_ttl() -> int:
    try:
        return max(
            300, min(int(os.getenv("WORKSPACE_MANIFEST_TTL", DEFAULT_TTL)), 86400)
        )
    except ValueError:
        return DEFAULT_TTL


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
    ctx = person_context(session, user_id, person, company_id)
    resolved = resolve_content(resolve_profile(ctx))

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
        # signed-in session, not through the signature, and they never lower anything.
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
    """Bytes of one catalog file, only if it belongs to this person's own profile."""
    if not wm._SHA256.fullmatch(sha256):
        raise WorkspaceUnavailable("bad_hash")
    ctx = person_context(session, user_id, person, company_id)
    resolved = resolve_content(resolve_profile(ctx))
    path = resolved.files.get(sha256)
    if path is None:
        raise KeyError(sha256)
    data = _read_regular(path)
    if hashlib.sha256(data).hexdigest() != sha256:  # changed since it was listed
        raise WorkspaceUnavailable("file_changed")
    return data
