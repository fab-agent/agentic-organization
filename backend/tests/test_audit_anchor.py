"""External audit-chain anchoring (ADR-0006)."""

import pathlib

import pytest


@pytest.fixture(autouse=True)
def _tmp_anchor(tmp_path, monkeypatch):
    from services import audit_anchor

    monkeypatch.setattr(audit_anchor, "_ANCHOR_FILE", tmp_path / "audit_anchors.jsonl")
    yield


def _event(company_id="c1", action="tool_event"):
    from services import audit_chain

    audit_chain.record(
        actor_type="agent",
        actor_id="a",
        company_id=company_id,
        action=action,
        target="bash",
        reason="before",
    )


def test_anchor_and_clean_check(client, db_session):
    from services import audit_anchor

    _event()
    _event()
    res = audit_anchor.anchor_heads()
    assert res["anchored"] == 1  # one chain

    check = audit_anchor.check_anchors()
    assert check["ok"] is True
    assert check["issues"] == []
    assert check["chains"]["c1"]["state"] == "ok"


def test_growth_since_anchor_is_ok(client, db_session):
    from services import audit_anchor

    _event()
    audit_anchor.anchor_heads()
    _event()  # chain grew
    check = audit_anchor.check_anchors()
    assert check["ok"] is True
    assert check["chains"]["c1"]["state"] == "ok"
    assert check["chains"]["c1"]["live_seq"] > check["chains"]["c1"]["anchored_seq"]


def test_truncation_is_flagged(client, db_session, monkeypatch):
    from services import audit_anchor

    _event()
    _event()
    _event()
    audit_anchor.anchor_heads()  # anchored at seq 3

    # simulate a rollback: live heads report a lower seq
    monkeypatch.setattr(
        audit_anchor,
        "_chain_heads",
        lambda: {"c1": {"seq": 1, "head": "deadbeef"}},
    )
    check = audit_anchor.check_anchors()
    assert check["ok"] is False
    assert check["chains"]["c1"]["state"] == "truncated"
    assert any("seq 1 <" in i["issue"] for i in check["issues"])


def test_rewrite_at_anchored_seq_is_flagged(client, db_session, monkeypatch):
    from services import audit_anchor

    _event()
    _event()
    audit_anchor.anchor_heads()  # anchored at seq 2 with the real head

    monkeypatch.setattr(
        audit_anchor,
        "_chain_heads",
        lambda: {"c1": {"seq": 2, "head": "tampered-hash"}},
    )
    check = audit_anchor.check_anchors()
    assert check["ok"] is False
    assert check["chains"]["c1"]["state"] == "rewritten"


def test_anchor_endpoints(auth_client, db_session):
    _event()
    r = auth_client.post("/audit/chain/anchors")
    assert r.status_code == 202
    assert r.json()["anchored"] == 1

    g = auth_client.get("/audit/chain/anchors")
    assert g.status_code == 200
    assert g.json()["ok"] is True


def test_anchor_file_is_append_only_ndjson(client, db_session):
    from services import audit_anchor

    _event()
    audit_anchor.anchor_heads()
    audit_anchor.anchor_heads()
    lines = pathlib.Path(audit_anchor._ANCHOR_FILE).read_text().splitlines()
    assert len(lines) == 2  # one line per chain per run
