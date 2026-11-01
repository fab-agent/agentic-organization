"""ADR-0027: signed workspace manifest - trust chain, replay/rollback, tamper cases."""

import base64
import copy
import json
import pathlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import services.workspace_manifest as wm
from services.workspace_manifest import (
    ClientState,
    Expected,
    ManifestError,
    issue_crl,
    issue_signing_cert,
    sign_manifest,
    verify_manifest,
)

NOW = 1_800_000_000
VECTORS = pathlib.Path(__file__).parent / "vectors" / "workspace_manifest_vectors.json"


def _key(seed_byte: int) -> tuple[str, str]:
    """Deterministic key (fixed seed) so signatures are reproducible vectors."""
    priv = Ed25519PrivateKey.from_private_bytes(bytes([seed_byte]) * 32)
    raw = priv.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode(), base64.b64encode(pub).decode()


ROOT_PRIV, ROOT_PUB = _key(1)
SIGN_PRIV, SIGN_PUB = _key(2)
EVIL_PRIV, EVIL_PUB = _key(9)
EXPECT = Expected("co1", "p1", "herdr-provisioner", "1.0.0")
SHA = "a" * 64


def _cert(**kw):
    args = dict(not_before=NOW - 3600, not_after=NOW + 30 * 86400, serial=1)
    args.update(kw)
    return issue_signing_cert(ROOT_PRIV, SIGN_PUB, **args)


def _body(**kw):
    p = {
        "company_id": "co1",
        "person_id": "p1",
        "aud": "herdr-provisioner",
        "generation": 5,
        "issued_at": NOW - 60,
        "expires_at": NOW + 3600,
        "min_client_version": "1.0.0",
        "gateway_url": "https://gw.example.test",
        "layout": {"id": "finance-v2", "sha256": SHA},
        "mods": [
            {
                "name": "finance-dashboard",
                "version": "1.2.0",
                "files": [{"path": "main.js", "sha256": SHA, "size": 10}],
            }
        ],
    }
    p.update(kw)
    return p


def _env(**kw):
    return sign_manifest(SIGN_PRIV, _cert(), _body(**kw))


def _verify(env, state=None, crl=None, expected=EXPECT, now=NOW):
    return verify_manifest(
        env,
        root_pub_b64=ROOT_PUB,
        expected=expected,
        now=now,
        state=state or ClientState(),
        crl=crl,
    )


def _code(env, **kw):
    with pytest.raises(ManifestError) as e:
        _verify(env, **kw)
    return e.value.code


# ── happy path ───────────────────────────────────────────────────────────────


def test_valid_manifest_verifies_and_advances_state():
    payload, st = _verify(_env())
    assert payload["generation"] == 5
    assert st.generations["co1:p1"]["generation"] == 5


# ── tampering ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["mods"][0]["files"][0].__setitem__("sha256", "b" * 64),
        lambda p: p["mods"][0]["files"].append(
            {"path": "extra.js", "sha256": SHA, "size": 1}
        ),
        lambda p: p["layout"].__setitem__("sha256", "c" * 64),
        lambda p: p.__setitem__("gateway_url", "https://evil.example.test"),
        lambda p: p.__setitem__("generation", 99),
        lambda p: p.__setitem__("expires_at", p["expires_at"] + 1),
    ],
)
def test_any_payload_change_breaks_the_signature(mutate):
    env = _env()
    t = copy.deepcopy(env)
    mutate(t["payload"])
    assert _code(t) == "bad_signature"


def test_cert_fields_cannot_be_altered():
    env = _env()
    t = copy.deepcopy(env)
    t["cert"]["payload"]["not_after"] += 86400
    assert _code(t) == "bad_signature"


# ── the old wellknown re-pin attack ──────────────────────────────────────────


def test_attacker_key_with_own_cert_and_forged_issuer_is_rejected():
    """Attacker signs a cert with their own 'root' and claims the real root's kid."""
    evil_cert = issue_signing_cert(
        EVIL_PRIV, EVIL_PUB, not_before=NOW - 10, not_after=NOW + 1000, serial=1
    )
    evil_cert["payload"]["issuer_kid"] = wm.key_id(ROOT_PUB)  # claim to be the root
    env = sign_manifest(EVIL_PRIV, evil_cert, _body())
    assert _code(env) == "bad_signature"


def test_attacker_signing_key_without_a_root_cert_is_rejected():
    forged_cert = {
        "payload": {**_cert()["payload"], "pub": EVIL_PUB, "kid": wm.key_id(EVIL_PUB)},
        "sig": _cert()["sig"],
    }
    env = {
        "cert": forged_cert,
        "payload": {"typ": "fab-workspace-manifest", "v": 1, **_body()},
    }
    env["sig"] = wm._sign(EVIL_PRIV, "manifest", env["payload"])
    assert _code(env) == "bad_signature"


def test_cert_kid_is_recomputed_not_trusted():
    cp = _cert()["payload"]
    cp["kid"] = wm.key_id(EVIL_PUB)  # kid no longer matches pub
    cert = {"payload": cp, "sig": wm._sign(ROOT_PRIV, "cert", cp)}  # root-signed lie
    body = {"typ": "fab-workspace-manifest", "v": 1, **_body()}
    envelope = {
        "cert": cert,
        "payload": body,
        "sig": wm._sign(SIGN_PRIV, "manifest", body),
    }
    assert _code(envelope) == "bad_cert"


def test_wrong_root_pinned_rejects_everything():
    _, other_root_pub = _key(7)
    with pytest.raises(ManifestError) as e:
        verify_manifest(
            _env(),
            root_pub_b64=other_root_pub,
            expected=EXPECT,
            now=NOW,
            state=ClientState(),
        )
    assert e.value.code == "bad_signature"


def test_signatures_are_domain_separated():
    """A CRL signature must not verify as a cert, and so on."""
    crl = issue_crl(ROOT_PRIV, number=1, revoked_kids=[], issued_at=NOW)
    cert = {"payload": crl["payload"], "sig": crl["sig"]}
    with pytest.raises(ManifestError):
        wm._verify_sig(ROOT_PUB, "cert", cert["payload"], cert["sig"])


# ── bindings ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expected",
    [
        Expected("co2", "p1", "herdr-provisioner", "1.0.0"),
        Expected("co1", "p2", "herdr-provisioner", "1.0.0"),
        Expected("co1", "p1", "other-client", "1.0.0"),
    ],
)
def test_manifest_for_someone_else_is_rejected(expected):
    assert _code(_env(), expected=expected) == "wrong_binding"


def test_old_client_is_told_to_update():
    assert _code(_env(min_client_version="2.0.0")) == "client_too_old"


# ── time ─────────────────────────────────────────────────────────────────────


def test_expired_manifest_is_rejected():
    assert _code(_env(), now=NOW + 3600 + 301) == "expired"


def test_clock_skew_is_tolerated_but_bounded():
    _verify(_env(), now=NOW + 3600 + 100)  # inside skew
    assert _code(_env(issued_at=NOW + 1000, expires_at=NOW + 2000)) == "not_yet_valid"


def test_lifetime_over_24h_cannot_even_be_signed():
    with pytest.raises(ManifestError) as e:
        _env(expires_at=NOW + 3 * 86400)
    assert e.value.code == "bad_lifetime"


def test_expired_cert_is_rejected():
    cert = _cert(not_before=NOW - 10000, not_after=NOW - 5000)
    env = sign_manifest(
        SIGN_PRIV, cert, _body(issued_at=NOW - 9000, expires_at=NOW - 8000)
    )
    assert _code(env) == "cert_not_valid_now"


def test_manifest_outside_cert_window_is_rejected():
    cert = _cert(not_after=NOW + 600)
    env = sign_manifest(SIGN_PRIV, cert, _body(expires_at=NOW + 3600))
    assert _code(env) == "outside_cert_window"


def test_cert_lifetime_over_90_days_cannot_be_issued():
    with pytest.raises(ManifestError):
        _cert(not_after=NOW + 91 * 86400)


# ── replay / rollback ────────────────────────────────────────────────────────


def test_older_generation_is_rejected_after_a_newer_one():
    _, st = _verify(_env(generation=7))
    assert _code(_env(generation=6), state=st) == "rollback"


def test_same_generation_same_content_is_idempotent():
    env = _env(generation=7)
    _, st = _verify(env)
    _verify(env, state=st)


def test_same_generation_different_content_is_a_conflict():
    _, st = _verify(_env(generation=7))
    other = _env(generation=7, gateway_url="https://gw2.example.test")
    assert _code(other, state=st) == "generation_conflict"


def test_generation_is_tracked_per_person():
    _, st = _verify(_env(generation=9))
    other_person = Expected("co1", "p2", "herdr-provisioner", "1.0.0")
    _verify(_env(person_id="p2", generation=1), state=st, expected=other_person)


# ── rotation and revocation ──────────────────────────────────────────────────


def test_rotation_is_a_new_root_signed_cert_and_old_manifests_still_verify():
    new_priv, new_pub = _key(3)
    new_cert = issue_signing_cert(
        ROOT_PRIV, new_pub, not_before=NOW - 3600, not_after=NOW + 86400, serial=2
    )
    new_env = sign_manifest(new_priv, new_cert, _body(generation=6))
    old_env = _env(generation=5)
    _verify(old_env)
    _verify(new_env)


def test_revoked_signing_key_is_rejected_even_with_a_valid_signature():
    crl = issue_crl(
        ROOT_PRIV, number=1, revoked_kids=[wm.key_id(SIGN_PUB)], issued_at=NOW
    )
    assert _code(_env(), crl=crl) == "cert_revoked"


def test_revocation_persists_in_state_across_calls():
    crl = issue_crl(
        ROOT_PRIV, number=1, revoked_kids=[wm.key_id(SIGN_PUB)], issued_at=NOW
    )
    st = wm.verify_crl(crl, ROOT_PUB, ClientState())
    assert _code(_env(), state=st) == "cert_revoked"


def test_crl_rollback_is_rejected():
    st = wm.verify_crl(
        issue_crl(ROOT_PRIV, number=5, revoked_kids=[], issued_at=NOW),
        ROOT_PUB,
        ClientState(),
    )
    old = issue_crl(ROOT_PRIV, number=4, revoked_kids=[], issued_at=NOW)
    with pytest.raises(ManifestError) as e:
        wm.verify_crl(old, ROOT_PUB, st)
    assert e.value.code == "crl_rollback"


def test_crl_signed_by_anyone_but_root_is_rejected():
    evil = issue_crl(EVIL_PRIV, number=9, revoked_kids=["x"], issued_at=NOW)
    with pytest.raises(ManifestError) as e:
        wm.verify_crl(evil, ROOT_PUB, ClientState())
    assert e.value.code == "bad_signature"


def test_revocation_cannot_be_undone_by_a_later_crl():
    st = wm.verify_crl(
        issue_crl(ROOT_PRIV, number=1, revoked_kids=["k1"], issued_at=NOW),
        ROOT_PUB,
        ClientState(),
    )
    st = wm.verify_crl(
        issue_crl(ROOT_PRIV, number=2, revoked_kids=[], issued_at=NOW), ROOT_PUB, st
    )
    assert "k1" in st.revoked


# ── body validation ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "../x.js",
        "/etc/passwd",
        "a/../b.js",
        "a//b.js",
        "a\\b.js",
        "C:/x.js",
        "",
        ".",
        "a/./b",
        "x\x00y",
    ],
)
def test_unsafe_mod_paths_cannot_be_signed(path):
    mods = [
        {
            "name": "m",
            "version": "1.0.0",
            "files": [{"path": path, "sha256": SHA, "size": 1}],
        }
    ]
    with pytest.raises(ManifestError) as e:
        _env(mods=mods)
    assert e.value.code == "bad_path"


def test_case_colliding_paths_are_rejected():
    files = [
        {"path": "A.js", "sha256": SHA, "size": 1},
        {"path": "a.js", "sha256": SHA, "size": 1},
    ]
    with pytest.raises(ManifestError) as e:
        _env(mods=[{"name": "m", "version": "1.0.0", "files": files}])
    assert e.value.code == "duplicate_path"


def test_duplicate_mod_names_and_non_https_gateway_are_rejected():
    m = {
        "name": "m",
        "version": "1.0.0",
        "files": [{"path": "a.js", "sha256": SHA, "size": 1}],
    }
    with pytest.raises(ManifestError):
        _env(mods=[m, m])
    with pytest.raises(ManifestError):
        _env(gateway_url="http://gw.example.test")


def test_unsafe_paths_in_a_hand_made_envelope_fail_verification_too():
    """A hostile server that signs a bad body with a valid key is still refused."""
    body = {"typ": "fab-workspace-manifest", "v": 1, **_body()}
    body["mods"][0]["files"][0]["path"] = "../../.ssh/authorized_keys"
    env = {
        "cert": _cert(),
        "payload": body,
        "sig": wm._sign(SIGN_PRIV, "manifest", body),
    }
    assert _code(env) == "bad_path"


# ── canonical form ───────────────────────────────────────────────────────────


def test_floats_and_huge_ints_have_no_canonical_form():
    for bad in ({"a": 1.5}, {"a": 2**60}, {"a": float("nan")}, {1: "x"}):
        with pytest.raises(ManifestError):
            wm.canonical_bytes(bad)


def test_canonical_bytes_are_ascii_sorted_and_compact():
    assert wm.canonical_bytes({"b": 1, "a": "é"}) == b'{"a":"\\u00e9","b":1}'


# ── file verification ────────────────────────────────────────────────────────


def test_file_verification_checks_size_and_hash():
    import hashlib

    data = b"console.log(1)"
    entry = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    wm.verify_file(data, entry)
    with pytest.raises(ManifestError) as e:
        wm.verify_file(data + b" ", entry)
    assert e.value.code == "size_mismatch"
    with pytest.raises(ManifestError) as e:
        wm.verify_file(b"console.log(2)", entry)
    assert e.value.code == "hash_mismatch"


# ── cross-language vectors ───────────────────────────────────────────────────


def _vectors():
    cert = _cert()
    env = _env()
    crl = issue_crl(ROOT_PRIV, number=3, revoked_kids=["bb", "aa"], issued_at=NOW)
    return {
        "note": "Ed25519 is deterministic; keys are fixed-seed test keys. A second implementation must verify these.",
        "now": NOW,
        "root_pub": ROOT_PUB,
        "signing_pub": SIGN_PUB,
        "expected": {
            "company_id": EXPECT.company_id,
            "person_id": EXPECT.person_id,
            "aud": EXPECT.aud,
            "client_version": EXPECT.client_version,
        },
        "canonical": [
            {
                "input": {"b": 1, "a": "é", "c": [True, None]},
                "bytes": wm.canonical_bytes(
                    {"b": 1, "a": "é", "c": [True, None]}
                ).decode(),
            }
        ],
        "cert": cert,
        "manifest": env,
        "manifest_digest": wm.digest(env["payload"]),
        "crl": crl,
    }


def test_vectors_file_matches_the_implementation():
    got = _vectors()
    if not VECTORS.exists():
        VECTORS.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n")
    assert json.loads(VECTORS.read_text()) == got


# ── key tooling ──────────────────────────────────────────────────────────────


def test_key_tooling_end_to_end_and_private_keys_are_not_printed(tmp_path, capsys):
    from scripts import manifest_keys as mk

    root_f, sign_f = tmp_path / "root.key", tmp_path / "sign.key"
    assert mk.main(["root-init", "--out", str(root_f)]) == 0
    root_out = json.loads(capsys.readouterr().out)
    assert mk.main(["signing-init", "--out", str(sign_f)]) == 0
    sign_out = json.loads(capsys.readouterr().out)
    assert oct(root_f.stat().st_mode & 0o777) == "0o600"
    assert root_f.read_text().strip() not in json.dumps(root_out)

    cert_f = tmp_path / "cert.json"
    mk.main(
        [
            "issue-cert",
            "--root",
            str(root_f),
            "--signing-pub",
            sign_out["public_key"],
            "--serial",
            "1",
            "--out",
            str(cert_f),
        ]
    )
    capsys.readouterr()
    now = __import__("time").time()
    cert = json.loads(cert_f.read_text())
    body = _body(issued_at=int(now) - 60, expires_at=int(now) + 3600)
    env = sign_manifest(sign_f.read_text().strip(), cert, body)
    _, _ = verify_manifest(
        env,
        root_pub_b64=root_out["public_key"],
        expected=EXPECT,
        now=int(now),
        state=ClientState(),
    )


def test_key_tooling_refuses_to_overwrite_a_key(tmp_path):
    from scripts import manifest_keys as mk

    f = tmp_path / "k"
    mk.main(["root-init", "--out", str(f)])
    with pytest.raises(FileExistsError):
        mk.main(["root-init", "--out", str(f)])
