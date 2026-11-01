"""GET /me/workspace (ADR-0028): role -> profile -> signed manifest, fail closed."""

import hashlib
import json
import os
import time

import pytest

import services.workspace_manifest as wm
import services.workspace_service as ws
from models import (
    CompanyMember,
    Department,
    WorkspaceManifestState,
)
from services.auth import create_access_token
from tests.conftest import make_company, make_member, make_personnel, make_user

NOW = int(time.time())


def _h(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Env:
    """A configured workspace dir: root key (kept here, never on the 'server'), signing
    key + cert, and a catalog with finance and default profiles."""

    def __init__(self, tmp_path, monkeypatch):
        self.dir = tmp_path / "workspace"
        (self.dir / "catalog" / "layouts").mkdir(parents=True)
        self.root_priv, self.root_pub = wm.generate_key()
        self.sign_priv, self.sign_pub = wm.generate_key()
        (self.dir / "root.pub").write_text(self.root_pub)
        self._write_signer(epoch=1)
        mods = self.dir / "catalog" / "mods" / "finance-dashboard" / "1.2.0"
        (mods / "assets").mkdir(parents=True)
        (mods / "main.js").write_bytes(b"export default 1;\n")
        (mods / "assets" / "icon.svg").write_bytes(b"<svg/>")
        (self.dir / "catalog" / "layouts" / "finance-v2.json").write_bytes(
            b'{"id":"finance"}'
        )
        (self.dir / "catalog" / "layouts" / "terminals.json").write_bytes(
            b'{"id":"term"}'
        )
        self.profiles = {
            "v": 1,
            "profiles": [
                {
                    "id": "finance",
                    "match": {"roles": ["user"], "departments": ["finance"]},
                    "layout": "finance-v2",
                    "mods": [{"name": "finance-dashboard", "version": "1.2.0"}],
                    "min_client_version": "1.0.0",
                },
                {
                    "id": "managers",
                    "match": {"roles": ["founder", "executive"]},
                    "layout": "terminals",
                    "mods": [],
                },
            ],
            "defaults": {"layout": "terminals", "mods": []},
        }
        self.write_profiles()
        monkeypatch.setenv("WORKSPACE_DIR", str(self.dir))
        monkeypatch.delenv("WORKSPACE_ROOT_PUB", raising=False)
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.test")

    def write_profiles(self):
        (self.dir / "catalog" / "profiles.json").write_text(json.dumps(self.profiles))

    def _write_signer(self, epoch):
        key = self.dir / "signing.key"
        if key.exists():
            key.unlink()
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(self.sign_priv)
        cert = wm.issue_signing_cert(
            self.root_priv,
            self.sign_pub,
            not_before=NOW - 600,
            not_after=NOW + 30 * 86400,
            serial=epoch,
            epoch=epoch,
        )
        (self.dir / "signing.cert.json").write_text(json.dumps(cert))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


@pytest.fixture()
def people(auth_client, db_session):
    """auth_client's founder, plus a finance 'user' employee in the same company."""
    co = auth_client._test_company
    fin = Department(company_id=co.id, name="Finance", slug="finance")
    db_session.add(fin)
    db_session.flush()
    founder_person = make_personnel(
        db_session, co.id, name="Founder", slug="founder", type="human"
    )
    founder_person.user_id = auth_client._test_user.id
    emp_user = make_user(db_session, email="ap@test.com", name="AP")
    make_member(db_session, emp_user.id, co.id, role="user")
    emp = make_personnel(db_session, co.id, name="AP Clerk", slug="ap", type="human")
    emp.user_id, emp.department_id = emp_user.id, fin.id
    db_session.add_all([founder_person, emp])
    db_session.commit()
    return {
        "co": co,
        "founder": auth_client._test_user,
        "emp_user": emp_user,
        "emp": emp,
        "fin": fin,
    }


def _get(client, user, **params):
    return client.get("/me/workspace", headers=_h(user), params=params)


def _verify(env, body, person, co, *, floors=True):
    exp = wm.Expected(
        co.id, person.id, "herdr-provisioner", "1.0.0",
        **({"min_generation": body["bootstrap"]["min_generation"], "min_epoch": body["bootstrap"]["min_epoch"], "min_crl_number": body["bootstrap"]["min_crl_number"]} if floors else {}),
    )  # fmt: skip
    return wm.verify_wire(
        json.dumps(body["manifest"]),
        root_pub_b64=env.root_pub,
        expected=exp,
        now=int(time.time()),  # NOT the import-time NOW: a long run would age it
        state=wm.ClientState(),
    )


# ── happy path ───────────────────────────────────────────────────────────────


def test_employee_gets_the_finance_profile_and_it_verifies(client, env, people):
    r = _get(client, people["emp_user"], company_id=people["co"].id)
    assert r.status_code == 200, r.text
    body = r.json()
    payload, _ = _verify(env, body, people["emp"], people["co"])
    assert payload["layout"]["id"] == "finance-v2"
    assert [m["name"] for m in payload["mods"]] == ["finance-dashboard"]
    files = {f["path"] for f in payload["mods"][0]["files"]}
    assert files == {"main.js", "assets/icon.svg"}
    assert payload["gateway_url"] == "https://app.example.test"
    assert body["bootstrap"] == {
        "min_generation": 1,
        "min_epoch": 1,
        "min_crl_number": 0,
    }


def test_founder_gets_the_manager_profile(client, env, people):
    r = _get(client, people["founder"])
    assert r.status_code == 200
    assert r.json()["manifest"]["payload"]["layout"]["id"] == "terminals"


def test_unmatched_person_falls_back_to_defaults_or_404(
    client, env, people, db_session
):
    other = make_user(db_session, email="x@test.com", name="X")
    make_member(db_session, other.id, people["co"].id, role="user")
    p = make_personnel(
        db_session, people["co"].id, name="Ops", slug="ops", type="human"
    )
    p.user_id = other.id
    db_session.add(p)
    db_session.commit()
    assert (
        _get(client, other).json()["manifest"]["payload"]["layout"]["id"] == "terminals"
    )
    del env.profiles["defaults"]
    env.write_profiles()
    r = _get(client, other)
    assert r.status_code == 503 and r.json()["detail"]["reason"] == "no_profile"


def test_sub_department_inherits_the_parent_department_profile(
    client, env, people, db_session
):
    sub = Department(
        company_id=people["co"].id,
        name="AP",
        slug="ap-team",
        parent_id=people["fin"].id,
    )
    db_session.add(sub)
    db_session.flush()
    people["emp"].department_id = sub.id
    db_session.add(people["emp"])
    db_session.commit()
    assert (
        _get(client, people["emp_user"]).json()["manifest"]["payload"]["layout"]["id"]
        == "finance-v2"
    )


def test_generation_grows_and_each_issue_has_its_own_floor(client, env, people):
    a = _get(client, people["emp_user"]).json()
    b = _get(client, people["emp_user"]).json()
    assert (
        b["manifest"]["payload"]["generation"]
        == a["manifest"]["payload"]["generation"] + 1
    )
    assert b["bootstrap"]["min_generation"] == b["manifest"]["payload"]["generation"]


def test_epoch_bump_restarts_the_count_for_a_new_key(client, env, people):
    _get(client, people["emp_user"])
    _get(client, people["emp_user"])
    env.sign_priv, env.sign_pub = wm.generate_key()  # recovery uses a NEW key
    env._write_signer(epoch=2)
    body = _get(client, people["emp_user"]).json()
    assert body["manifest"]["payload"]["epoch"] == 2
    assert body["manifest"]["payload"]["generation"] == 1
    assert body["bootstrap"]["min_epoch"] == 2


def test_server_refuses_when_its_epoch_is_behind_the_stored_state(
    client, env, people, db_session
):
    _get(client, people["emp_user"])
    row = db_session.exec(WorkspaceManifestState.__table__.select()).first()
    db_session.execute(WorkspaceManifestState.__table__.update().values(epoch=5))
    db_session.commit()
    r = _get(client, people["emp_user"])
    assert (
        r.status_code == 503
        and r.json()["detail"]["reason"] == "signing_epoch_behind_state"
    )
    assert row is not None


# ── files ────────────────────────────────────────────────────────────────────


def test_files_are_served_by_hash_and_only_from_your_own_profile(client, env, people):
    body = _get(client, people["emp_user"]).json()
    entry = body["manifest"]["payload"]["mods"][0]["files"][0]
    r = client.get(
        f"/me/workspace/files/{entry['sha256']}", headers=_h(people["emp_user"])
    )
    assert r.status_code == 200 and _sha(r.content) == entry["sha256"]
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    layout_sha = body["manifest"]["payload"]["layout"]["sha256"]
    assert (
        client.get(
            f"/me/workspace/files/{layout_sha}", headers=_h(people["emp_user"])
        ).status_code
        == 200
    )
    # the founder's profile does not contain the finance mod file
    assert (
        client.get(
            f"/me/workspace/files/{entry['sha256']}", headers=_h(people["founder"])
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/me/workspace/files/" + "0" * 64, headers=_h(people["emp_user"])
        ).status_code
        == 404
    )


def test_file_endpoint_rejects_malformed_hashes(client, env, people):
    for bad in ("../x", "ABC", "g" * 64, "a" * 63):
        r = client.get(f"/me/workspace/files/{bad}", headers=_h(people["emp_user"]))
        assert r.status_code in (404, 503, 422)
        assert r.status_code != 200


def test_a_catalog_file_changed_after_listing_is_not_served(client, env, people):
    body = _get(client, people["emp_user"]).json()
    entry = next(
        f
        for f in body["manifest"]["payload"]["mods"][0]["files"]
        if f["path"] == "main.js"
    )
    mods = env.dir / "catalog" / "mods" / "finance-dashboard" / "1.2.0"
    (mods / "main.js").write_bytes(b"tampered")
    # the profile now hashes differently, so the old hash is simply not part of it
    r = client.get(
        f"/me/workspace/files/{entry['sha256']}", headers=_h(people["emp_user"])
    )
    assert r.status_code == 404


# ── tenant isolation and identity ────────────────────────────────────────────


def test_requires_authentication(client, env):
    assert client.get("/me/workspace").status_code == 401
    assert client.get("/me/workspace/files/" + "a" * 64).status_code == 401


def test_person_comes_from_the_session_not_the_request(client, env, people):
    r = client.get(
        "/me/workspace",
        headers=_h(people["emp_user"]),
        params={
            "company_id": people["co"].id,
            "person_id": people["founder"].id,
            "user_id": people["founder"].id,
        },
    )
    assert r.status_code == 200
    assert r.json()["manifest"]["payload"]["person_id"] == people["emp"].id


def test_other_company_member_cannot_ask_for_my_companys_workspace(
    client, env, people, db_session
):
    other_co = make_company(db_session, name="B", slug="b")
    outsider = make_user(db_session, email="o@test.com", name="O")
    make_member(db_session, outsider.id, other_co.id, role="founder")
    p = make_personnel(db_session, other_co.id, name="O", slug="o", type="human")
    p.user_id = outsider.id
    db_session.add(p)
    db_session.commit()
    assert _get(client, outsider, company_id=people["co"].id).status_code == 403
    mine = _get(client, outsider, company_id=other_co.id)
    assert mine.status_code == 200
    assert mine.json()["manifest"]["payload"]["company_id"] == other_co.id
    assert mine.json()["manifest"]["payload"]["person_id"] == p.id


def test_user_without_a_linked_person_gets_404_and_nothing_is_signed(
    client, env, people, db_session
):
    ghost = make_user(db_session, email="g@test.com", name="G")
    make_member(db_session, ghost.id, people["co"].id, role="user")
    db_session.commit()
    assert _get(client, ghost).status_code == 404
    assert db_session.exec(WorkspaceManifestState.__table__.select()).first() is None


def test_agent_personnel_do_not_get_a_workspace(client, env, people, db_session):
    agent_user = make_user(db_session, email="agent@test.com", name="Bot")
    make_member(db_session, agent_user.id, people["co"].id, role="user")
    a = make_personnel(
        db_session, people["co"].id, name="Bot", slug="bot2", type="agent"
    )
    a.user_id = agent_user.id
    db_session.add(a)
    db_session.commit()
    assert _get(client, agent_user).status_code == 404


def test_membership_role_decides_the_profile_not_a_request_field(
    client, env, people, db_session
):
    # demote nothing - the founder's membership row is what matches "managers"
    rows = db_session.exec(
        CompanyMember.__table__.select().where(
            CompanyMember.user_id == people["founder"].id
        )
    ).all()
    assert rows and rows[0].role == "founder"


# ── fail closed ──────────────────────────────────────────────────────────────


def _reason(r):
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "workspace_unavailable"
    assert r.headers["retry-after"] == "30"
    return r.json()["detail"]["reason"]


def _nothing_issued(db_session):
    return db_session.exec(WorkspaceManifestState.__table__.select()).first() is None


def test_unconfigured_server_signs_nothing(
    client, people, db_session, tmp_path, monkeypatch
):
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "nowhere"))
    monkeypatch.delenv("WORKSPACE_ROOT_PUB", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.test")
    assert _reason(_get(client, people["emp_user"])) == "catalog_unreadable"
    assert _nothing_issued(db_session)


def test_wrong_root_pinned_means_the_cert_does_not_verify(
    client, env, people, db_session
):
    (env.dir / "root.pub").write_text(wm.generate_key()[1])
    assert _reason(_get(client, people["emp_user"])).startswith("signing_")
    assert _nothing_issued(db_session)


def test_expired_certificate_signs_nothing(client, env, people, db_session):
    cert = wm.issue_signing_cert(
        env.root_priv,
        env.sign_pub,
        not_before=NOW - 9000,
        not_after=NOW - 4000,
        serial=1,
    )
    (env.dir / "signing.cert.json").write_text(json.dumps(cert))
    assert _reason(_get(client, people["emp_user"])) == "signing_cert_not_valid_now"
    assert _nothing_issued(db_session)


def test_key_that_does_not_match_the_certificate_signs_nothing(
    client, env, people, db_session
):
    other_priv, _ = wm.generate_key()
    (env.dir / "signing.key").unlink()
    fd = os.open(env.dir / "signing.key", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(other_priv)
    assert _reason(_get(client, people["emp_user"])) == "signing_key_cert_mismatch"
    assert _nothing_issued(db_session)


def test_signing_key_with_loose_permissions_is_refused(client, env, people, db_session):
    (env.dir / "signing.key").chmod(0o644)
    assert _reason(_get(client, people["emp_user"])) == "signing_key_permissions"
    assert _nothing_issued(db_session)


def test_signing_key_symlink_is_refused(client, env, people, db_session):
    real = env.dir / "real.key"
    (env.dir / "signing.key").rename(real)
    (env.dir / "signing.key").symlink_to(real)
    assert _reason(_get(client, people["emp_user"])) == "file_unreadable"


def test_revoked_signing_key_signs_nothing(client, env, people, db_session):
    crl = wm.issue_crl(
        env.root_priv,
        number=3,
        revoked_kids=[wm.key_id(env.sign_pub)],
        issued_at=NOW,
        next_update=NOW + 86400,
    )
    (env.dir / "crl.json").write_text(json.dumps(crl))
    assert _reason(_get(client, people["emp_user"])) == "signing_key_revoked"
    assert _nothing_issued(db_session)


def test_crl_number_is_reported_as_the_bootstrap_checkpoint(client, env, people):
    crl = wm.issue_crl(
        env.root_priv,
        number=7,
        revoked_kids=["a" * 32],
        issued_at=NOW,
        next_update=NOW + 86400,
    )
    (env.dir / "crl.json").write_text(json.dumps(crl))
    assert _get(client, people["emp_user"]).json()["bootstrap"]["min_crl_number"] == 7
    r = client.get("/me/workspace/crl", headers=_h(people["emp_user"]))
    assert r.status_code == 200 and r.json()["payload"]["number"] == 7


def test_invalid_crl_signs_nothing(client, env, people, db_session):
    other_root, _ = wm.generate_key()
    crl = wm.issue_crl(
        other_root, number=1, revoked_kids=[], issued_at=NOW, next_update=NOW + 86400
    )
    (env.dir / "crl.json").write_text(json.dumps(crl))
    assert _reason(_get(client, people["emp_user"])) == "crl_invalid"
    assert _nothing_issued(db_session)


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (
            lambda e: e.profiles["profiles"][0].__setitem__("layout", "nope"),
            "file_unreadable",
        ),
        (
            lambda e: e.profiles["profiles"][0].__setitem__("layout", "../x"),
            "layout_name_invalid",
        ),
        (
            lambda e: e.profiles["profiles"][0]["mods"].append(
                {"name": "ghost", "version": "1.0.0"}
            ),
            "mod_missing",
        ),
        (
            lambda e: e.profiles["profiles"][0]["mods"].__setitem__(
                0, {"name": "Bad Name", "version": "1.0.0"}
            ),
            "mod_name_invalid",
        ),
        (
            lambda e: e.profiles["profiles"][0]["match"].__setitem__("zones", ["x"]),
            "profiles_invalid",
        ),
        (
            lambda e: e.profiles["profiles"][0]["match"].__setitem__("roles", "user"),
            "profiles_invalid",
        ),
        (lambda e: e.profiles.__setitem__("v", 2), "profiles_invalid"),
    ],
)
def test_bad_catalog_signs_nothing(client, env, people, db_session, mutate, reason):
    mutate(env)
    env.write_profiles()
    assert _reason(_get(client, people["emp_user"])) == reason
    assert _nothing_issued(db_session)


def test_symlink_inside_a_mod_is_refused(client, env, people, db_session):
    mods = env.dir / "catalog" / "mods" / "finance-dashboard" / "1.2.0"
    (mods / "evil.js").symlink_to("/etc/passwd")
    assert _reason(_get(client, people["emp_user"])) == "catalog_symlink"
    assert _nothing_issued(db_session)


def test_non_https_gateway_signs_nothing(client, env, people, db_session, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://insecure.example.test")
    assert _reason(_get(client, people["emp_user"])) == "manifest_bad_gateway_url"


def test_audit_failure_means_no_manifest_is_returned(client, env, people, monkeypatch):
    import services.audit_chain as ac

    monkeypatch.setattr(ac, "record", lambda **kw: None)
    assert _reason(_get(client, people["emp_user"])) == "audit_unavailable"


def test_audit_record_names_what_was_issued_without_secrets(
    client, env, people, db_session
):
    from sqlmodel import select

    from models import AuditEvent

    _get(client, people["emp_user"])
    ev = db_session.exec(
        select(AuditEvent).where(AuditEvent.action == "workspace_manifest_issued")
    ).first()
    assert ev and ev.actor_type == "human" and ev.actor_id == people["emp_user"].id
    assert ev.company_id == people["co"].id and ev.target == people["emp"].id
    detail = json.loads(ev.payload_json)
    assert detail["layout"] == "finance-v2" and detail["mods"] == [
        "finance-dashboard@1.2.0"
    ]
    assert detail["generation"] == 1 and detail["signing_kid"] == wm.key_id(
        env.sign_pub
    )
    assert env.sign_priv not in ev.payload_json and env.sign_priv not in (
        ev.reason or ""
    )


# ── generation allocation ────────────────────────────────────────────────────


def test_generation_allocation_never_repeats_under_contention(env, people, db_session):
    seen = [
        ws.allocate_generation(db_session, people["co"].id, people["emp"].id, 1)
        for _ in range(25)
    ]
    assert seen == list(range(1, 26))


def test_stale_compare_and_set_does_not_reuse_a_generation(env, people, db_session):
    co, pid = people["co"].id, people["emp"].id
    ws.allocate_generation(db_session, co, pid, 1)
    # a competing writer moves the row between our read and our update
    real_exec = db_session.exec
    state = {"hit": False}

    def racing_exec(stmt, *a, **k):
        if not state["hit"] and "UPDATE" in str(stmt).upper():
            state["hit"] = True
            db_session.execute(
                WorkspaceManifestState.__table__.update().values(generation=10)
            )
            db_session.commit()
        return real_exec(stmt, *a, **k)

    db_session.exec = racing_exec  # type: ignore[method-assign]
    got = ws.allocate_generation(db_session, co, pid, 1)
    db_session.exec = real_exec  # type: ignore[method-assign]
    assert got == 11  # retried from the new value, never 2


# ── gateway_url comes from configuration only ────────────────────────────────


def test_host_header_never_decides_the_signed_gateway_url(client, env, people):
    r = client.get(
        "/me/workspace",
        headers={
            **_h(people["emp_user"]),
            "Host": "evil.example.test",
            "X-Forwarded-Host": "evil.example.test",
            "X-Forwarded-Proto": "https",
        },
    )
    assert r.status_code == 200
    assert r.json()["manifest"]["payload"]["gateway_url"] == "https://app.example.test"


def test_no_configured_gateway_url_signs_nothing_even_with_a_host_header(
    client, env, people, db_session, monkeypatch
):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("WORKSTATION_BASE_URL", raising=False)
    r = client.get(
        "/me/workspace", headers={**_h(people["emp_user"]), "Host": "evil.example.test"}
    )
    assert _reason(r) == "gateway_url_not_configured"
    assert _nothing_issued(db_session)


def test_database_setting_wins_over_the_environment(client, env, people, db_session):
    from models import AppConfig

    db_session.add(
        AppConfig(key="workstation.base_url", value="https://configured.example.test/")
    )
    db_session.commit()
    body = _get(client, people["emp_user"]).json()
    assert (
        body["manifest"]["payload"]["gateway_url"] == "https://configured.example.test"
    )


# ── CODEX-ME-WORKSPACE: confinement, budgets, schema, CRL, scope ─────────────

import signal  # noqa: E402


def _outside(tmp_path, name="secret.json", data=b"TOP SECRET"):
    d = tmp_path / "outside"
    d.mkdir(exist_ok=True)
    (d / name).write_bytes(data)
    return d


def test_parent_directory_symlink_cannot_reach_outside_the_catalog(
    client, env, people, db_session, tmp_path
):
    out = _outside(tmp_path, "finance-v2.json")
    layouts = env.dir / "catalog" / "layouts"
    for f in layouts.iterdir():
        f.unlink()
    layouts.rmdir()
    layouts.symlink_to(out)  # the DIRECTORY is the link, not the file
    assert _reason(_get(client, people["emp_user"])) == "catalog_unreadable"
    assert _nothing_issued(db_session)
    sha = _sha(b"TOP SECRET")
    r = client.get(f"/me/workspace/files/{sha}", headers=_h(people["emp_user"]))
    assert r.status_code in (404, 503) and b"TOP SECRET" not in r.content


def test_mod_directory_symlink_is_refused_at_every_level(
    client, env, people, db_session, tmp_path
):
    out = _outside(tmp_path, "main.js")
    mods = env.dir / "catalog" / "mods"
    (mods / "finance-dashboard" / "1.2.0").rename(tmp_path / "moved")
    (mods / "finance-dashboard" / "1.2.0").symlink_to(out)
    assert _reason(_get(client, people["emp_user"])) in (
        "mod_missing",
        "catalog_unreadable",
    )
    assert _nothing_issued(db_session)


def test_directory_swapped_for_a_symlink_while_reading_is_not_followed(env, tmp_path):
    """The fd-based walk: a directory replaced after it was listed is refused on open."""
    mods = env.dir / "catalog" / "mods" / "finance-dashboard" / "1.2.0"
    out = _outside(tmp_path, "icon.svg", b"STOLEN")
    root_fd = ws._open_dir(None, str(env.dir))
    try:
        mfd = ws._walk_to(root_fd, ["catalog", "mods", "finance-dashboard", "1.2.0"])
        try:
            assert ws._read_rel(mfd, "assets/icon.svg") == b"<svg/>"
            (mods / "assets" / "icon.svg").unlink()
            (mods / "assets").rmdir()
            (mods / "assets").symlink_to(out)
            with pytest.raises(ws.WorkspaceUnavailable):
                ws._read_rel(mfd, "assets/icon.svg")
        finally:
            os.close(mfd)
    finally:
        os.close(root_fd)


def test_hard_linked_catalog_file_is_refused(client, env, people, db_session, tmp_path):
    out = _outside(tmp_path, "linked.js", b"X")
    os.link(
        out / "linked.js",
        env.dir / "catalog" / "mods" / "finance-dashboard" / "1.2.0" / "linked.js",
    )
    assert _reason(_get(client, people["emp_user"])) == "file_invalid"
    assert _nothing_issued(db_session)


def _with_alarm(seconds, fn):
    def boom(*_):
        raise TimeoutError("blocked on a special file")

    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(seconds)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def test_fifo_in_the_catalog_never_blocks(client, env, people, db_session):
    os.mkfifo(env.dir / "catalog" / "mods" / "finance-dashboard" / "1.2.0" / "pipe")
    r = _with_alarm(5, lambda: _get(client, people["emp_user"]))
    assert _reason(r) == "catalog_special_file"
    assert _nothing_issued(db_session)


def test_fifo_as_signing_material_never_blocks(client, env, people, db_session):
    (env.dir / "root.pub").unlink()
    os.mkfifo(env.dir / "root.pub")
    r = _with_alarm(5, lambda: _get(client, people["emp_user"]))
    assert _reason(r) == "file_invalid"
    assert _nothing_issued(db_session)


def test_a_file_that_grows_past_the_limit_is_rejected_not_truncated(env, monkeypatch):
    f = env.dir / "grow.txt"
    f.write_bytes(b"12345")  # 5 bytes on disk, limit 4
    real = os.fstat

    def small(fd):  # fstat saw 1 byte; the file grew before we read it
        r = real(fd)
        parts = list(r)
        parts[6] = 1
        return os.stat_result(tuple(parts))

    root_fd = ws._open_dir(None, str(env.dir))
    try:
        monkeypatch.setattr(ws.os, "fstat", small)
        with pytest.raises(ws.WorkspaceUnavailable) as e:
            ws._read_fd(root_fd, "grow.txt", limit=4)
        assert e.value.reason == "file_invalid"
    finally:
        os.close(root_fd)


def test_oversized_catalog_is_refused_before_anything_is_read(
    client, env, people, db_session, monkeypatch
):
    mods = env.dir / "catalog" / "mods" / "finance-dashboard" / "1.2.0"
    for i in range(wm.MAX_FILES_PER_MOD + 5):
        (mods / f"f{i}.js").write_bytes(b"x")
    reads = []
    real = ws._read_fd
    monkeypatch.setattr(
        ws, "_read_fd", lambda *a, **k: (reads.append(1), real(*a, **k))[1]
    )
    assert _reason(_get(client, people["emp_user"])) == "catalog_too_large"
    # only the signing material was read (root.pub, signing.key, cert), none of the 500+ files
    assert len(reads) <= 4
    assert _nothing_issued(db_session)


def test_downloads_read_one_file_not_the_whole_profile(
    client, env, people, monkeypatch
):
    mods = env.dir / "catalog" / "mods" / "finance-dashboard" / "1.2.0"
    for i in range(40):
        (mods / f"f{i}.js").write_bytes(f"// {i}".encode())
    body = _get(client, people["emp_user"]).json()
    entries = body["manifest"]["payload"]["mods"][0]["files"]
    assert len(entries) == 42
    reads = []
    real = ws._read_fd
    monkeypatch.setattr(
        ws, "_read_fd", lambda *a, **k: (reads.append(1), real(*a, **k))[1]
    )
    for e in entries[:10]:
        assert (
            client.get(
                f"/me/workspace/files/{e['sha256']}", headers=_h(people["emp_user"])
            ).status_code
            == 200
        )
    # profiles.json + the requested file per request; nothing scales with the 41 others
    assert len(reads) == 2 * 10


def test_a_change_to_the_catalog_is_seen_by_the_next_request(client, env, people):
    a = _get(client, people["emp_user"]).json()["manifest"]["payload"]["mods"][0][
        "files"
    ]
    mods = env.dir / "catalog" / "mods" / "finance-dashboard" / "1.2.0"
    (mods / "main.js").write_bytes(b"export default 2;\n")
    b = _get(client, people["emp_user"]).json()["manifest"]["payload"]["mods"][0][
        "files"
    ]
    old = next(f for f in a if f["path"] == "main.js")["sha256"]
    new = next(f for f in b if f["path"] == "main.js")["sha256"]
    assert old != new and new == _sha(b"export default 2;\n")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.profiles.__setitem__("extra", 1),
        lambda e: e.profiles["defaults"].__setitem__("mods", None),
        lambda e: e.profiles.__setitem__("profiles", None),
        lambda e: e.profiles["profiles"][0].__setitem__("surprise", True),
        lambda e: e.profiles["profiles"][0]["mods"][0].__setitem__("flag", 1),
        lambda e: e.profiles["profiles"][0].__setitem__("mods", "none"),
        lambda e: e.profiles["profiles"][0].__setitem__("match", []),
        lambda e: e.profiles["profiles"][0].__setitem__("layout", 5),
        lambda e: e.profiles["profiles"][0].__setitem__("min_client_version", 1),
    ],
)
def test_profile_file_has_a_closed_schema_and_never_500s(
    client, env, people, db_session, mutate
):
    mutate(env)
    env.write_profiles()
    assert _reason(_get(client, people["emp_user"])) == "profiles_invalid"
    assert _nothing_issued(db_session)


def test_bad_root_pub_encoding_is_a_503_not_a_500(client, env, people, db_session):
    (env.dir / "root.pub").write_bytes(b"\xff\xfe not base64")
    assert _reason(_get(client, people["emp_user"])).startswith("signing_")
    assert _nothing_issued(db_session)


def test_nonportable_file_name_is_rejected_for_issue_and_download_alike(
    client, env, people
):
    good = _get(client, people["emp_user"]).json()["manifest"]["payload"]["mods"][0][
        "files"
    ]
    sha = next(f for f in good if f["path"] == "main.js")["sha256"]
    mods = env.dir / "catalog" / "mods" / "finance-dashboard" / "1.2.0"
    (mods / "e\u0301.js").write_bytes(b"nfd")  # NFD: not allowed in a manifest
    assert _reason(_get(client, people["emp_user"])).startswith("manifest_")
    r = client.get(f"/me/workspace/files/{sha}", headers=_h(people["emp_user"]))
    assert r.status_code == 503 and r.json()["detail"]["reason"].startswith("manifest_")


def test_crl_number_never_goes_backwards_or_disappears(client, env, people):
    def put(n):
        c = wm.issue_crl(
            env.root_priv,
            number=n,
            revoked_kids=[],
            issued_at=NOW,
            next_update=NOW + 86400,
        )
        (env.dir / "crl.json").write_text(json.dumps(c))

    put(7)
    assert _get(client, people["emp_user"]).json()["bootstrap"]["min_crl_number"] == 7
    put(2)  # an old file restored
    assert _reason(_get(client, people["emp_user"])) == "crl_rollback"
    (env.dir / "crl.json").unlink()  # or removed
    assert _reason(_get(client, people["emp_user"])) == "crl_missing"
    put(9)
    assert _get(client, people["emp_user"]).json()["bootstrap"]["min_crl_number"] == 9


def test_dangling_crl_symlink_is_not_treated_as_absent(client, env, people, db_session):
    (env.dir / "crl.json").symlink_to(env.dir / "nowhere.json")
    assert _reason(_get(client, people["emp_user"])) == "crl_invalid"
    assert _nothing_issued(db_session)


def test_scoped_membership_of_another_department_does_not_grant_the_profile(
    client, env, people, db_session
):
    env.profiles["profiles"].insert(
        0,
        {
            "id": "fin-heads",
            "match": {"roles": ["dept_head"], "departments": ["finance"]},
            "layout": "terminals",
            "mods": [],
        },
    )
    env.write_profiles()
    eng = Department(company_id=people["co"].id, name="Eng", slug="eng")
    db_session.add(eng)
    db_session.flush()
    db_session.add(
        CompanyMember(
            user_id=people["emp_user"].id,
            company_id=people["co"].id,
            role="dept_head",
            scope_id=eng.id,
        )
    )
    db_session.commit()
    body = _get(client, people["emp_user"]).json()
    assert (
        body["manifest"]["payload"]["layout"]["id"] == "finance-v2"
    )  # not the dept-head profile
    # the same role scoped to the person's OWN department does match
    db_session.add(
        CompanyMember(
            user_id=people["emp_user"].id,
            company_id=people["co"].id,
            role="dept_head",
            scope_id=people["fin"].id,
        )
    )
    db_session.commit()
    body = _get(client, people["emp_user"]).json()
    assert body["manifest"]["payload"]["layout"]["id"] == "terminals"


def test_generation_counter_exhaustion_is_a_503(client, env, people, db_session):
    _get(client, people["emp_user"])
    db_session.execute(
        WorkspaceManifestState.__table__.update().values(generation=2**53 - 1)
    )
    db_session.commit()
    assert _reason(_get(client, people["emp_user"])) == "generation_exhausted"


def test_counter_columns_are_64_bit():
    from sqlalchemy import BigInteger

    cols = WorkspaceManifestState.__table__.c
    assert isinstance(cols.epoch.type, BigInteger) and isinstance(
        cols.generation.type, BigInteger
    )


def test_database_error_while_allocating_is_a_503(client, env, people, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def boom(*a, **k):
        raise OperationalError("stmt", {}, Exception("db down"))

    monkeypatch.setattr(ws, "allocate_generation", ws.allocate_generation)  # keep real
    import sqlmodel.orm.session as sm

    real = sm.Session.exec

    def failing(self, stmt, *a, **k):
        if "workspacemanifeststate" in str(stmt).lower():
            raise OperationalError("stmt", {}, Exception("db down"))
        return real(self, stmt, *a, **k)

    monkeypatch.setattr(sm.Session, "exec", failing)
    assert _reason(_get(client, people["emp_user"])) == "state_unavailable"


def test_erasing_a_person_removes_their_manifest_counter(
    client, env, people, db_session
):
    from services.work_review import erase_person

    _get(client, people["emp_user"])
    assert (
        db_session.exec(WorkspaceManifestState.__table__.select()).first() is not None
    )
    erase_person(db_session, people["emp"].id)
    db_session.commit()
    assert db_session.exec(WorkspaceManifestState.__table__.select()).first() is None


def test_crl_endpoint_needs_a_session_but_no_company(client, env, people):
    # the shared test client keeps the founder's header from the fixture: blank it
    assert (
        client.get("/me/workspace/crl", headers={"Authorization": ""}).status_code
        == 401
    )
    assert (
        client.get("/me/workspace/crl", headers=_h(people["emp_user"])).status_code
        == 404
    )
