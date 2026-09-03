"""`/.well-known/opencode` signed org config (ADR-0011)."""

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from services import wellknown_sign


def test_pubkey_endpoint(client):
    r = client.get("/.well-known/opencode/pubkey")
    assert r.status_code == 200
    body = r.json()
    assert body["algorithm"] == "ed25519"
    assert len(base64.b64decode(body["public_key_b64"])) == 32
    assert body["key_id"] == wellknown_sign.key_id()


def test_config_is_signed_and_verifies(client):
    r = client.get("/.well-known/opencode")
    assert r.status_code == 200
    body = r.json()

    config = body["config"]
    assert config["provider"]["fabagent"]["options"]["baseURL"].endswith("/v1")
    assert config["share"] == "disabled"
    assert "x-fabagent" in config

    pub = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(
            client.get("/.well-known/opencode/pubkey").json()["public_key_b64"]
        )
    )
    # Must verify over the exact canonical form the server signed.
    pub.verify(
        base64.b64decode(body["signature"]), wellknown_sign.canonical(config).encode()
    )


def test_config_has_instructions_and_plugin(client):
    """The served config is a complete drop-in for the baked managed-settings.json."""
    config = client.get("/.well-known/opencode").json()["config"]
    assert config["plugin"] == ["/opt/agent-plugin/src/index.ts"]
    assert config["instructions"] == ["/etc/opencode/base-prompt.md"]


def test_pubkey_carries_previous_key_id_after_rotation(tmp_path, monkeypatch):
    monkeypatch.setattr(wellknown_sign, "_KEY_FILE", tmp_path / "k")
    monkeypatch.setattr(wellknown_sign, "_PREV_KEY_FILE", tmp_path / "k.prev")

    assert wellknown_sign.previous_key_id() is None
    kid0 = wellknown_sign.key_id()

    res = wellknown_sign.rotate_key()
    assert res["previous_key_id"] == kid0
    assert res["key_id"] != kid0
    assert wellknown_sign.previous_key_id() == kid0
    assert wellknown_sign.key_id() == res["key_id"]

    # a config signed with the NEW key verifies with the new pubkey
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    cfg = {"a": 1}
    sig = wellknown_sign.sign_config(cfg)
    pub = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(wellknown_sign.public_key_b64())
    )
    pub.verify(base64.b64decode(sig), wellknown_sign.canonical(cfg).encode())

    assert wellknown_sign.drop_previous_key() is True
    assert wellknown_sign.previous_key_id() is None


def test_config_reflects_policy_mode(client, db_session):
    from models import AppConfig

    db_session.add(AppConfig(key="policy.mode", value="enforce"))
    db_session.commit()

    body = client.get("/.well-known/opencode").json()
    assert body["config"]["x-fabagent"]["policy_mode"] == "enforce"
    assert body["config"]["x-fabagent"]["fail_closed"] is True


def test_tampered_config_fails_verification(client):
    body = client.get("/.well-known/opencode").json()
    tampered = {**body["config"], "share": "enabled"}  # flip a field
    pub = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(
            client.get("/.well-known/opencode/pubkey").json()["public_key_b64"]
        )
    )
    import pytest

    with pytest.raises(Exception):
        pub.verify(
            base64.b64decode(body["signature"]),
            wellknown_sign.canonical(tampered).encode(),
        )
