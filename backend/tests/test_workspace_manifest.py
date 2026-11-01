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
        "layout": {"id": "finance-v2", "sha256": SHA, "size": 50},
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
    assert st.generations[wm._binding_key("co1", "p1")]["generation"] == 5


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


# ── key tooling ──────────────────────────────────────────────────────────────


# ── round 1: canonical profile and strict wire parsing ───────────────────────


def test_keys_sort_by_utf16_code_unit_like_javascript():
    # U+E000 (BMP) sorts AFTER U+10000 (surrogate pair D800 DC00) in UTF-16 order.
    out = wm.canonical_bytes({"": 1, "\U00010000": 2})
    assert out == b'{"\\ud800\\udc00":2,"\\ue000":1}'


def test_canonical_form_is_ascii_compact_and_lowercase_escaped():
    assert wm.canonical_bytes({"b": 1, "a": "é"}) == b'{"a":"\\u00e9","b":1}'
    assert wm.canonical_bytes({"a": "x\n\x01\x7f"}) == b'{"a":"x\\n\\u0001\\u007f"}'


def test_integer_like_keys_stay_strings_in_text_order():
    assert wm.canonical_bytes({"10": 1, "9": 2, "2": 3}) == b'{"10":1,"2":3,"9":2}'


@pytest.mark.parametrize(
    "bad",
    [
        {"a": 1.5},
        {"a": 2**53},
        {"a": -(2**53)},
        {"a": float("nan")},
        {1: "x"},
        {"a": "\ud800"},
        {"\udc00": 1},
        {"a": {1, 2}},
    ],
)
def test_values_without_a_portable_canonical_form_are_rejected(bad):
    with pytest.raises(ManifestError):
        wm.canonical_bytes(bad)


def test_safe_integer_boundary_is_inclusive():
    assert wm.canonical_bytes({"a": 2**53 - 1}) == b'{"a":9007199254740991}'
    assert wm.canonical_bytes({"a": -(2**53 - 1)}) == b'{"a":-9007199254740991}'


def test_non_bmp_and_bmp_keys_that_collide_only_in_the_old_serialiser_are_rejected():
    keys = {}
    keys["\U00010000"] = 1
    keys["\ud800\udc00"] = (
        2  # same JSON escape, different Python key: must not serialise
    )
    with pytest.raises(ManifestError):
        wm.canonical_bytes(keys)


@pytest.mark.parametrize(
    "text,code",
    [
        ('{"a":1,"a":2}', "duplicate_key"),
        ('{"a":1.0}', "float_not_allowed"),
        ('{"a":1e0}', "float_not_allowed"),
        ('{"a":NaN}', "float_not_allowed"),
        ('{"a":Infinity}', "float_not_allowed"),
        ('{"a":-0}', "negative_zero"),
        ('{"a":9007199254740992}', "int_out_of_range"),
        ('{"a":"\\ud800"}', "bad_string"),
        ("{not json", "bad_json"),
        ("[" * 5000 + "]" * 5000, "too_deep"),
    ],
)
def test_wire_parser_rejects_what_parsers_resolve_differently(text, code):
    with pytest.raises(ManifestError) as e:
        wm.parse_wire(text)
    assert e.value.code == code


def test_wire_parser_caps_size_and_encoding():
    with pytest.raises(ManifestError) as e:
        wm.parse_wire('{"a":"' + "x" * wm.MAX_WIRE_BYTES + '"}')
    assert e.value.code == "wire_too_large"
    with pytest.raises(ManifestError) as e:
        wm.parse_wire(b'{"a":"\xff"}')
    assert e.value.code == "bad_encoding"


def test_a_signed_envelope_round_trips_through_the_strict_wire_parser():
    env = _env()
    wire = json.dumps(env)
    payload, _ = wm.verify_wire(
        wire, root_pub_b64=ROOT_PUB, expected=EXPECT, now=NOW, state=ClientState()
    )
    assert payload["generation"] == 5


def test_unknown_fields_are_rejected_everywhere():
    for path in (
        ("payload",),
        ("payload", "layout"),
        ("payload", "mods", 0),
        ("payload", "mods", 0, "files", 0),
        ("cert",),
        ("cert", "payload"),
    ):
        env = _env()
        node = env
        for k in path:
            node = node[k]
        node["extra"] = 1
        with pytest.raises(ManifestError):
            _verify(env)
    env = _env()
    env["extra"] = 1
    assert _code(env) == "malformed"


def test_padding_field_cannot_inflate_a_manifest():
    env = _env()
    env["payload"]["padding"] = "x" * 131072
    with pytest.raises(ManifestError):
        _verify(env)


# ── round 2: portable paths and strict fields ────────────────────────────────


def _one_file(path):
    return [
        {
            "name": "m",
            "version": "1.0.0",
            "files": [{"path": path, "sha256": SHA, "size": 1}],
        }
    ]


@pytest.mark.parametrize(
    "path",
    [
        "CON",
        "nul.txt",
        "AUX",
        "com1.js",
        "LPT9",
        "dir/Con.d/x.js",
        "a.js.",
        "a.js ",
        " a.js",
        ".. /x.js",
        "a<b",
        "a>b",
        'a"b',
        "a|b",
        "a?b",
        "a*b",
        "a:b",
        "é.js",  # NFD
        "x" * 100 + "/" + "y" * 256,
        "é" * 150 + ".js",
        "a\tb",
        "a\x7fb",
    ],
)
def test_portable_path_rules(path):
    with pytest.raises(ManifestError) as e:
        _env(mods=_one_file(path))
    assert e.value.code == "bad_path"


@pytest.mark.parametrize(
    "path", ["main.js", "dir/sub/file.min.js", "é.js", "CONSOLE.js", "a-b_c.d/e.js"]
)
def test_ordinary_paths_are_accepted(path):
    _env(mods=_one_file(path))


def test_unicode_equivalent_and_case_equivalent_paths_collide():
    files = [
        {"path": "é.js", "sha256": SHA, "size": 1},
        {"path": "É.JS", "sha256": SHA, "size": 1},
    ]
    with pytest.raises(ManifestError) as e:
        _env(mods=[{"name": "m", "version": "1.0.0", "files": files}])
    assert e.value.code == "duplicate_path"


def test_a_file_and_a_directory_of_the_same_name_cannot_coexist():
    files = [
        {"path": "a", "sha256": SHA, "size": 1},
        {"path": "a/b.js", "sha256": SHA, "size": 1},
    ]
    with pytest.raises(ManifestError) as e:
        _env(mods=[{"name": "m", "version": "1.0.0", "files": files}])
    assert e.value.code == "path_conflict"


@pytest.mark.parametrize(
    "kw,code",
    [
        ({"generation": True}, "bad_generation"),
        ({"issued_at": True}, "bad_time"),
        ({"min_client_version": "١.٠.٠"}, "bad_version"),
        ({"min_client_version": "1.0.0\n"}, "bad_version"),
        ({"company_id": "co\n"}, "bad_binding"),
        ({"company_id": "a:b"}, "bad_binding"),
        ({"aud": "Has Space"}, "bad_binding"),
        ({"gateway_url": "https://"}, "bad_gateway_url"),
        ({"gateway_url": "https://user:pw@gw.example.test"}, "bad_gateway_url"),
        ({"gateway_url": "https://gw.example.test:99999"}, "bad_gateway_url"),
        ({"gateway_url": "https://gw.example.test/#frag"}, "bad_gateway_url"),
        ({"gateway_url": "https://gw example.test"}, "bad_gateway_url"),
        ({"gateway_url": "http://gw.example.test"}, "bad_gateway_url"),
        ({"layout": {"id": 1, "sha256": SHA, "size": 1}}, "bad_name"),
        ({"layout": {"id": "ok", "sha256": SHA}}, "bad_size"),
        ({"layout": {"id": "con", "sha256": SHA, "size": 1}}, "bad_name"),
    ],
)
def test_loose_field_types_and_formats_are_rejected(kw, code):
    with pytest.raises(ManifestError) as e:
        _env(**kw)
    assert e.value.code == code


def test_mod_name_with_trailing_newline_or_reserved_name_is_rejected():
    for name in ("m\n", "con", "nul", "m."):
        with pytest.raises(ManifestError):
            _env(
                mods=[
                    {
                        "name": name,
                        "version": "1.0.0",
                        "files": [{"path": "a.js", "sha256": SHA, "size": 1}],
                    }
                ]
            )


def test_total_size_includes_the_layout_and_is_capped():
    big = wm.MAX_TOTAL_BYTES
    _env(layout={"id": "l", "sha256": SHA, "size": big - 1}, mods=_one_file("a.js"))
    with pytest.raises(ManifestError) as e:
        _env(layout={"id": "l", "sha256": SHA, "size": big}, mods=_one_file("a.js"))
    assert e.value.code == "too_large"


def test_counts_are_capped_at_the_limit():
    f = [
        {"path": f"f{i}.js", "sha256": SHA, "size": 0}
        for i in range(wm.MAX_FILES_PER_MOD)
    ]
    _env(mods=[{"name": "m", "version": "1.0.0", "files": f}])
    with pytest.raises(ManifestError):
        _env(
            mods=[
                {
                    "name": "m",
                    "version": "1.0.0",
                    "files": [*f, {"path": "x.js", "sha256": SHA, "size": 0}],
                }
            ]
        )
    mods = [
        {"name": f"m{i}", "version": "1.0.0", "files": f[:1]}
        for i in range(wm.MAX_MODS + 1)
    ]
    with pytest.raises(ManifestError):
        _env(mods=mods)


# ── round 3: revocation lists ────────────────────────────────────────────────

KID = wm.key_id(SIGN_PUB)


def _crl(number=1, kids=None, issued=NOW, next_update=NOW + 86400, key=ROOT_PRIV):
    return issue_crl(
        key,
        number=number,
        revoked_kids=kids or [],
        issued_at=issued,
        next_update=next_update,
    )


def _ingest(crl, state=None, now=NOW):
    return wm.verify_crl(crl, ROOT_PUB, state or ClientState(), now)


def test_revoked_signing_key_is_rejected_even_with_a_valid_signature():
    assert _code(_env(), crl=_crl(kids=[KID])) == "cert_revoked"


def test_revocation_persists_when_the_manifest_is_rejected():
    with pytest.raises(ManifestError) as e:
        _verify(_env(), crl=_crl(kids=[KID]))
    saved = e.value.state  # the caller persists this even though the manifest failed
    assert KID in saved.revoked and saved.crl_number == 1
    assert _code(_env(), state=saved) == "cert_revoked"


def test_crl_is_ingested_on_its_own_and_survives_a_cold_manifest_check():
    st = _ingest(_crl(kids=[KID]))
    assert _code(_env(), state=st) == "cert_revoked"


def test_crl_rollback_is_rejected():
    st = _ingest(_crl(number=5))
    with pytest.raises(ManifestError) as e:
        _ingest(_crl(number=4), st)
    assert e.value.code == "crl_rollback"


def test_crl_must_be_cumulative_and_cannot_unrevoke():
    st = _ingest(_crl(number=1, kids=[KID]))
    with pytest.raises(ManifestError) as e:
        _ingest(_crl(number=2, kids=[]), st)
    assert e.value.code == "crl_not_cumulative"
    st2 = _ingest(_crl(number=2, kids=[KID, "f" * 32]), st)
    assert KID in st2.revoked and "f" * 32 in st2.revoked


def test_number_may_skip_but_same_number_with_other_content_is_a_conflict():
    st = _ingest(_crl(number=1, kids=[KID]))
    st = _ingest(_crl(number=50, kids=[KID]), st)  # missed snapshots are normal
    with pytest.raises(ManifestError) as e:
        _ingest(_crl(number=50, kids=[KID, "e" * 32]), st)
    assert e.value.code == "crl_conflict"
    assert _ingest(_crl(number=50, kids=[KID]), st) == st  # same content: idempotent


def test_crl_signed_by_anyone_but_root_is_rejected():
    with pytest.raises(ManifestError) as e:
        _ingest(_crl(key=EVIL_PRIV, kids=["a" * 32]))
    assert e.value.code == "bad_signature"


def test_crl_shape_bool_number_and_bad_kids_and_future_issue_are_rejected():
    for crl in (
        _crl(number=True),
        _crl(kids=["short"]),
        _crl(issued=NOW + 10**6, next_update=NOW + 10**6 + 10),
    ):
        with pytest.raises(ManifestError):
            _ingest(crl)


def test_domain_separation_cert_cannot_be_presented_as_crl():
    cert = _cert()
    with pytest.raises(ManifestError):
        wm.verify_crl(
            {"payload": cert["payload"], "sig": cert["sig"]},
            ROOT_PUB,
            ClientState(),
            NOW,
        )


def test_require_crl_demands_a_fresh_list():
    with pytest.raises(ManifestError) as e:
        verify_manifest(
            _env(),
            root_pub_b64=ROOT_PUB,
            expected=EXPECT,
            now=NOW,
            state=ClientState(),
            require_crl=True,
        )
    assert e.value.code == "crl_required"
    st = _ingest(_crl(next_update=NOW + 600))
    verify_manifest(
        _env(),
        root_pub_b64=ROOT_PUB,
        expected=EXPECT,
        now=NOW,
        state=st,
        require_crl=True,
    )
    with pytest.raises(ManifestError) as e:
        verify_manifest(
            _env(),
            root_pub_b64=ROOT_PUB,
            expected=EXPECT,
            now=NOW + 600 + 301,
            state=st,
            require_crl=True,
        )
    assert e.value.code in ("crl_stale", "expired")


# ── round 4: epochs, bootstrap floors, state keys, clock ─────────────────────


def _cert_epoch(epoch, **kw):
    args = dict(not_before=NOW - 3600, not_after=NOW + 86400, serial=epoch, epoch=epoch)
    args.update(kw)
    return issue_signing_cert(ROOT_PRIV, SIGN_PUB, **args)


def test_epoch_bump_recovers_from_a_poisoned_generation_floor():
    # A stolen signing key signed generation 2**53-1; the root issues epoch 2.
    poisoned = sign_manifest(SIGN_PRIV, _cert_epoch(1), _body(generation=2**53 - 1))
    _, st = _verify(poisoned)
    assert _code(_env(generation=6), state=st) == "rollback"
    new_env = sign_manifest(SIGN_PRIV, _cert_epoch(2), _body(generation=1))
    _, st2 = _verify(new_env, state=st)
    assert st2.epoch == 2
    assert (
        _code(poisoned, state=st2) == "epoch_rollback"
    )  # old-epoch manifests are dead


def test_lower_epoch_than_seen_or_than_the_floor_is_rejected():
    _, st = _verify(sign_manifest(SIGN_PRIV, _cert_epoch(3), _body()))
    assert (
        _code(sign_manifest(SIGN_PRIV, _cert_epoch(2), _body(generation=9)), state=st)
        == "epoch_rollback"
    )
    floor = Expected("co1", "p1", "herdr-provisioner", "1.0.0", min_epoch=4)
    assert (
        _code(sign_manifest(SIGN_PRIV, _cert_epoch(3), _body()), expected=floor)
        == "epoch_rollback"
    )


def test_lost_state_cannot_be_replayed_past_a_bootstrap_floor():
    old = _env(generation=3)
    _verify(old)  # accepted only because the state was empty
    floor = Expected("co1", "p1", "herdr-provisioner", "1.0.0", min_generation=5)
    assert _code(old, expected=floor) == "below_floor"
    _verify(_env(generation=5), expected=floor)


def test_state_keys_cannot_collide_across_company_person_pairs():
    assert wm._binding_key("a", "b:c") != wm._binding_key("a:b", "c")
    with pytest.raises(ManifestError):
        _env(company_id="a:b")


def test_the_clock_cannot_be_wound_back():
    _, st = _verify(_env(), now=NOW)
    assert st.last_seen == NOW
    with pytest.raises(ManifestError) as e:
        _verify(_env(), state=st, now=NOW - 10_000)
    assert e.value.code == "clock_rollback"
    _verify(_env(), state=st, now=NOW - 100)  # small skew is fine


def test_replayed_old_payload_cannot_gain_life_from_a_new_cert():
    env = _env(generation=5)
    _, st = _verify(env)
    re_signed = sign_manifest(SIGN_PRIV, _cert_epoch(1, serial=9), env["payload"] | {})
    _verify(re_signed, state=st)  # same content, new cert: idempotent, not fresher
    assert _code(re_signed, state=st, now=NOW + 3600 + 400) == "expired"


# ── round 5: key tooling ─────────────────────────────────────────────────────


def _run(mk, *argv):
    return mk.main(list(argv))


def test_key_tooling_end_to_end_and_private_keys_are_not_printed(tmp_path, capsys):
    import time

    from scripts import manifest_keys as mk

    root_f, sign_f, cert_f = (
        tmp_path / "root.key",
        tmp_path / "sign.key",
        tmp_path / "cert.json",
    )
    assert _run(mk, "root-init", "--out", str(root_f)) == 0
    root_out = json.loads(capsys.readouterr().out)
    assert _run(mk, "signing-init", "--out", str(sign_f)) == 0
    sign_out = json.loads(capsys.readouterr().out)
    assert oct(root_f.stat().st_mode & 0o777) == "0o600"
    assert root_f.read_text().strip() not in json.dumps(root_out)

    _run(
        mk,
        "issue-cert",
        "--root",
        str(root_f),
        "--signing-pub",
        sign_out["public_key"],
        "--serial",
        "1",
        "--days",
        "30",
        "--out",
        str(cert_f),
    )
    capsys.readouterr()
    now = int(time.time())
    env = sign_manifest(
        sign_f.read_text().strip(),
        json.loads(cert_f.read_text()),
        _body(issued_at=now, expires_at=now + 3600),
    )
    verify_manifest(
        env,
        root_pub_b64=root_out["public_key"],
        expected=EXPECT,
        now=now,
        state=ClientState(),
    )


def test_key_tooling_never_overwrites_and_refuses_unsafe_inputs(tmp_path, capsys):
    from scripts import manifest_keys as mk

    root_f = tmp_path / "root.key"
    _run(mk, "root-init", "--out", str(root_f))
    out = json.loads(capsys.readouterr().out)
    with pytest.raises(FileExistsError):
        _run(mk, "root-init", "--out", str(root_f))
    keep = root_f.read_text()
    with pytest.raises(SystemExit):  # public output may not be the private input
        _run(
            mk,
            "issue-cert",
            "--root",
            str(root_f),
            "--signing-pub",
            out["public_key"],
            "--serial",
            "1",
            "--out",
            str(root_f),
        )
    assert root_f.read_text() == keep
    existing = tmp_path / "x.json"
    existing.write_text("keep")
    with pytest.raises(FileExistsError):
        _run(
            mk,
            "issue-cert",
            "--root",
            str(root_f),
            "--signing-pub",
            out["public_key"],
            "--serial",
            "1",
            "--out",
            str(existing),
        )
    assert existing.read_text() == "keep"
    loose = tmp_path / "loose.key"
    loose.write_text(keep)
    loose.chmod(0o644)
    with pytest.raises(SystemExit):
        _run(
            mk,
            "issue-cert",
            "--root",
            str(loose),
            "--signing-pub",
            out["public_key"],
            "--serial",
            "1",
            "--out",
            str(tmp_path / "c.json"),
        )
    link = tmp_path / "link.key"
    link.symlink_to(root_f)
    with pytest.raises(SystemExit):
        _run(
            mk,
            "issue-cert",
            "--root",
            str(link),
            "--signing-pub",
            out["public_key"],
            "--serial",
            "1",
            "--out",
            str(tmp_path / "c2.json"),
        )


@pytest.mark.parametrize("days", ["0", "-1", "91"])
def test_key_tooling_days_are_bounded(tmp_path, capsys, days):
    from scripts import manifest_keys as mk

    root_f = tmp_path / "root.key"
    _run(mk, "root-init", "--out", str(root_f))
    pub = json.loads(capsys.readouterr().out)["public_key"]
    with pytest.raises(SystemExit):
        _run(
            mk,
            "issue-cert",
            "--root",
            str(root_f),
            "--signing-pub",
            pub,
            "--serial",
            "1",
            "--days",
            days,
            "--out",
            str(tmp_path / "c.json"),
        )


def test_key_tooling_accepts_the_full_90_days_and_carries_crl_forward(tmp_path, capsys):
    from scripts import manifest_keys as mk

    root_f = tmp_path / "root.key"
    _run(mk, "root-init", "--out", str(root_f))
    pub = json.loads(capsys.readouterr().out)["public_key"]
    assert (
        _run(
            mk,
            "issue-cert",
            "--root",
            str(root_f),
            "--signing-pub",
            pub,
            "--serial",
            "1",
            "--days",
            "90",
            "--out",
            str(tmp_path / "c.json"),
        )
        == 0
    )
    capsys.readouterr()
    c1, c2 = tmp_path / "crl1.json", tmp_path / "crl2.json"
    _run(
        mk,
        "issue-crl",
        "--root",
        str(root_f),
        "--number",
        "1",
        "--revoke",
        "a" * 32,
        "--out",
        str(c1),
    )
    _run(
        mk,
        "issue-crl",
        "--root",
        str(root_f),
        "--number",
        "2",
        "--revoke",
        "b" * 32,
        "--previous",
        str(c1),
        "--out",
        str(c2),
    )
    kids = json.loads(c2.read_text())["payload"]["revoked_kids"]
    assert kids == ["a" * 32, "b" * 32]


# ── cross-language vectors ───────────────────────────────────────────────────

CANON_CASES = [
    {"b": 1, "a": "é", "c": [True, None]},
    {"": 1, "\U00010000": 2},
    {"10": 1, "9": 2, "2": 3},
    {"s": 'x\n\t"\\\x01\x7f '},
    {"n": [0, -1, 2**53 - 1, -(2**53 - 1)]},
    {},
    [],
]
REJECT_WIRE = [
    '{"a":1,"a":2}', '{"a":1.0}', '{"a":1e0}', '{"a":-0}', '{"a":NaN}',
    '{"a":9007199254740992}', '{"a":"\\ud800"}',
]  # fmt: skip


def _vectors():
    env = _env()
    return {
        "note": "Ed25519 is deterministic and keys are fixed-seed test keys; a second implementation must reproduce every value here.",
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
            {"input": c, "bytes": wm.canonical_bytes(c).decode()} for c in CANON_CASES
        ],
        "reject_wire": REJECT_WIRE,
        "cert": _cert(),
        "manifest": env,
        "manifest_digest": wm.digest(env["payload"]),
        "crl": _crl(number=3, kids=["b" * 32, "a" * 32]),
    }


def test_vectors_file_matches_the_implementation():
    got = _vectors()
    if not VECTORS.exists():
        VECTORS.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n")
    assert json.loads(VECTORS.read_text()) == got
    for text in REJECT_WIRE:
        with pytest.raises(ManifestError):
            wm.parse_wire(text)


def test_vectors_verify_in_an_independent_javascript_implementation():
    """Canonical bytes and every signature must also check out in Node, written from the
    spec rather than ported from the Python code. Skipped when node is not installed."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = pathlib.Path(__file__).parent / "vectors" / "verify_vectors.mjs"
    r = subprocess.run(
        [node, str(script), str(VECTORS)], capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, r.stdout + r.stderr
