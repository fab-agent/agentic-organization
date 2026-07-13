"""
Change Request tests — two-stage approval flow ending in a GitHub commit.

Lifecycle:
  submitted → dept_head_approved → admin_approved → committed
           ↘ rejected (at any stage by the responsible stage)
"""
import pytest
from unittest.mock import patch
from tests.conftest import make_personnel


# ── Helpers ───────────────────────────────────────────────────────────────────

def _post_cr(client, company_id, personnel_id, **overrides):
    """POST /change-requests with sensible defaults."""
    payload = {
        "personnel_id": personnel_id,
        "change_type": overrides.pop("change_type", "skill"),
        "title": overrides.pop("title", "Add web_search skill"),
        "proposed": overrides.pop("proposed", {"name": "web_search", "version": "1.0"}),
        **overrides,
    }
    return client.post(f"/change-requests?company_id={company_id}", json=payload)


def _dept_approve(client, cr_id, note="LGTM"):
    return client.post(f"/change-requests/{cr_id}/dept-approve", json={"note": note})


def _dept_reject(client, cr_id, note="Not now"):
    return client.post(f"/change-requests/{cr_id}/dept-reject", json={"note": note})


def _admin_approve(client, cr_id, company_id, note="Approved"):
    return client.post(
        f"/change-requests/{cr_id}/admin-approve?company_id={company_id}",
        json={"note": note},
    )


def _admin_reject(client, cr_id, note="Rejected"):
    return client.post(f"/change-requests/{cr_id}/admin-reject", json={"note": note})


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def cr_setup(auth_client, db_session):
    """Company + one agent personnel ready to receive change requests."""
    co = auth_client._test_company
    agent = make_personnel(db_session, co.id, name="ChangeBot",
                           slug="changebot", type="agent", title="Test Agent")
    db_session.commit()
    return {"company_id": co.id, "personnel_id": agent.id}


# ── Create ────────────────────────────────────────────────────────────────────

def test_create_cr_returns_submitted(auth_client, cr_setup):
    r = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"])
    assert r.status_code == 201
    d = r.json()
    assert d["status"] == "submitted"
    assert d["change_type"] == "skill"
    assert d["title"] == "Add web_search skill"
    assert d["proposed"] == {"name": "web_search", "version": "1.0"}
    assert d["original"] is None
    assert d["dept_head_approved_at"] is None
    assert d["commit_sha"] is None
    assert d["created_by_user_id"] is not None


def test_create_cr_with_original_snapshot(auth_client, cr_setup):
    r = _post_cr(
        auth_client, cr_setup["company_id"], cr_setup["personnel_id"],
        change_type="agent_config",
        title="Switch model",
        proposed={"model": "claude-sonnet-4-6"},
        original={"model": "gpt-4o-mini"},
    )
    assert r.status_code == 201
    d = r.json()
    assert d["original"] == {"model": "gpt-4o-mini"}
    assert d["proposed"] == {"model": "claude-sonnet-4-6"}


def test_create_cr_policy_type(auth_client, cr_setup):
    r = _post_cr(
        auth_client, cr_setup["company_id"], cr_setup["personnel_id"],
        change_type="policy",
        title="No PII logging policy",
        proposed={"content": "Agents must not log PII."},
    )
    assert r.status_code == 201
    assert r.json()["change_type"] == "policy"


def test_create_cr_invalid_personnel(auth_client, cr_setup):
    r = _post_cr(auth_client, cr_setup["company_id"], "nonexistent-personnel-id")
    assert r.status_code == 404


# ── Get & List ────────────────────────────────────────────────────────────────

def test_get_cr_by_id(auth_client, cr_setup):
    created = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    r = auth_client.get(f"/change-requests/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]
    assert r.json()["title"] == created["title"]


def test_get_cr_not_found(auth_client):
    r = auth_client.get("/change-requests/nonexistent-id")
    assert r.status_code == 404


def test_list_crs_returns_all(auth_client, cr_setup):
    _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"], title="CR 1")
    _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"], title="CR 2")
    r = auth_client.get("/change-requests")
    assert r.status_code == 200
    assert len(r.json()) >= 2


def test_list_filter_by_company(auth_client, cr_setup):
    _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"])
    r = auth_client.get(f"/change-requests?company_id={cr_setup['company_id']}")
    assert r.status_code == 200
    assert all(cr["company_id"] == cr_setup["company_id"] for cr in r.json())


def test_list_filter_by_status(auth_client, cr_setup):
    _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"])
    r = auth_client.get("/change-requests?status=submitted")
    assert r.status_code == 200
    assert all(cr["status"] == "submitted" for cr in r.json())


def test_list_filter_by_personnel(auth_client, cr_setup):
    _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"])
    r = auth_client.get(f"/change-requests?personnel_id={cr_setup['personnel_id']}")
    assert r.status_code == 200
    assert all(cr["personnel_id"] == cr_setup["personnel_id"] for cr in r.json())


def test_list_ordered_newest_first(auth_client, cr_setup):
    _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"], title="First")
    _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"], title="Second")
    crs = auth_client.get("/change-requests").json()
    # Most recently created should appear first
    assert crs[0]["title"] == "Second"


# ── Stage 1: Dept Head Approval ───────────────────────────────────────────────

def test_dept_approve_transitions_status(auth_client, cr_setup):
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    r = _dept_approve(auth_client, cr["id"], note="Looks good to me")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "dept_head_approved"
    assert d["dept_head_approved_at"] is not None
    assert d["dept_head_note"] == "Looks good to me"
    assert d["dept_head_id"] is not None


def test_dept_approve_without_note(auth_client, cr_setup):
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    r = auth_client.post(f"/change-requests/{cr['id']}/dept-approve", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "dept_head_approved"


def test_dept_approve_wrong_status_returns_400(auth_client, cr_setup):
    """Double-approving at dept stage must fail with 400."""
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    _dept_approve(auth_client, cr["id"])
    r = _dept_approve(auth_client, cr["id"])  # already dept_head_approved
    assert r.status_code == 400


def test_dept_approve_already_rejected_returns_400(auth_client, cr_setup):
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    _dept_reject(auth_client, cr["id"])
    r = _dept_approve(auth_client, cr["id"])
    assert r.status_code == 400


def test_dept_reject_transitions_status(auth_client, cr_setup):
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    r = _dept_reject(auth_client, cr["id"], note="No budget this quarter")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "rejected"
    assert d["dept_head_rejected_at"] is not None
    assert d["dept_head_note"] == "No budget this quarter"


def test_dept_reject_wrong_status_returns_400(auth_client, cr_setup):
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    _dept_reject(auth_client, cr["id"])
    r = _dept_reject(auth_client, cr["id"])  # already rejected
    assert r.status_code == 400


# ── Stage 2: Admin Approval ───────────────────────────────────────────────────

def test_admin_approve_without_git_config(auth_client, cr_setup):
    """No GitConfig → status=committed but commit_sha is None."""
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    _dept_approve(auth_client, cr["id"])
    r = _admin_approve(auth_client, cr["id"], cr_setup["company_id"], note="Ship it")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "committed"
    assert d["admin_approved_at"] is not None
    assert d["admin_note"] == "Ship it"
    assert d["admin_id"] is not None
    assert d["commit_sha"] is None


def test_admin_approve_wrong_status_returns_400(auth_client, cr_setup):
    """Admin cannot approve a CR that hasn't passed dept stage."""
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    r = _admin_approve(auth_client, cr["id"], cr_setup["company_id"])
    assert r.status_code == 400


def test_admin_approve_rejected_cr_returns_400(auth_client, cr_setup):
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    _dept_approve(auth_client, cr["id"])
    _admin_reject(auth_client, cr["id"])
    r = _admin_approve(auth_client, cr["id"], cr_setup["company_id"])
    assert r.status_code == 400


def test_admin_reject_transitions_status(auth_client, cr_setup):
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    _dept_approve(auth_client, cr["id"])
    r = _admin_reject(auth_client, cr["id"], note="Legal review needed")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "rejected"
    assert d["admin_rejected_at"] is not None
    assert d["admin_note"] == "Legal review needed"
    # Stage 1 record must still be present
    assert d["dept_head_approved_at"] is not None


def test_admin_reject_wrong_status_returns_400(auth_client, cr_setup):
    """Admin cannot reject a CR that hasn't passed dept stage."""
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    r = _admin_reject(auth_client, cr["id"])
    assert r.status_code == 400


# ── GitHub commit integration ─────────────────────────────────────────────────

def test_admin_approve_with_git_config_commits(auth_client, cr_setup, db_session):
    """With a GitConfig present, admin approve should call commit_change_request."""
    from models import GitConfig
    from core.security import encrypt

    git_cfg = GitConfig(
        company_id=cr_setup["company_id"],
        provider="github",
        repo_url="https://github.com/test/repo",
        branch="main",
        encrypted_token=encrypt("ghp_fake_token"),
    )
    db_session.add(git_cfg)
    db_session.commit()

    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"],
                  title="Policy: no PII").json()
    _dept_approve(auth_client, cr["id"])

    with patch("api.change_requests.commit_change_request",
               return_value=("deadbeef", "https://github.com/test/repo/commit/deadbeef")):
        r = _admin_approve(auth_client, cr["id"], cr_setup["company_id"])

    d = r.json()
    assert d["status"] == "committed"
    assert d["commit_sha"] == "deadbeef"
    assert d["commit_url"] == "https://github.com/test/repo/commit/deadbeef"


def test_admin_approve_commit_failure_saved_in_note(auth_client, cr_setup, db_session):
    """If commit_change_request raises, the error is appended to admin_note."""
    from models import GitConfig
    from core.security import encrypt

    git_cfg = GitConfig(
        company_id=cr_setup["company_id"],
        provider="github",
        repo_url="https://github.com/test/repo",
        branch="main",
        encrypted_token=encrypt("ghp_fake_token"),
    )
    db_session.add(git_cfg)
    db_session.commit()

    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"],
                  title="Failing CR").json()
    _dept_approve(auth_client, cr["id"])

    with patch("api.change_requests.commit_change_request",
               side_effect=Exception("GitHub rate limit exceeded")):
        r = _admin_approve(auth_client, cr["id"], cr_setup["company_id"],
                           note="Approved despite error")

    d = r.json()
    assert d["status"] == "admin_approved"
    assert "COMMIT ERROR" in d["admin_note"]
    assert "GitHub rate limit exceeded" in d["admin_note"]
    assert d["commit_sha"] is None


# ── Full happy-path flows ─────────────────────────────────────────────────────

def test_full_flow_no_git(auth_client, cr_setup):
    """submitted → dept_head_approved → committed (no git config)."""
    cr = _post_cr(
        auth_client, cr_setup["company_id"], cr_setup["personnel_id"],
        change_type="policy",
        title="Data retention policy",
        proposed={"retention_days": 90},
        original={"retention_days": 365},
    ).json()
    assert cr["status"] == "submitted"

    r = _dept_approve(auth_client, cr["id"], note="Reviewed and approved")
    assert r.json()["status"] == "dept_head_approved"

    r = _admin_approve(auth_client, cr["id"], cr_setup["company_id"], note="Final sign-off")
    d = r.json()
    assert d["status"] == "committed"
    assert d["dept_head_note"] == "Reviewed and approved"
    assert d["admin_note"] == "Final sign-off"
    assert d["commit_sha"] is None


def test_full_flow_with_github_commit(auth_client, cr_setup, db_session):
    """Complete flow with mocked GitHub commit → commit_sha set."""
    from models import GitConfig
    from core.security import encrypt

    db_session.add(GitConfig(
        company_id=cr_setup["company_id"],
        provider="github",
        repo_url="https://github.com/fab/org",
        branch="main",
        encrypted_token=encrypt("ghp_test"),
    ))
    db_session.commit()

    cr = _post_cr(
        auth_client, cr_setup["company_id"], cr_setup["personnel_id"],
        change_type="agent_config",
        title="Upgrade agent model",
        proposed={"model": "claude-opus-4-8"},
        original={"model": "gpt-4o"},
    ).json()

    _dept_approve(auth_client, cr["id"])

    with patch("api.change_requests.commit_change_request",
               return_value=("c0ffee42", "https://github.com/fab/org/commit/c0ffee42")):
        r = _admin_approve(auth_client, cr["id"], cr_setup["company_id"])

    d = r.json()
    assert d["status"] == "committed"
    assert d["commit_sha"] == "c0ffee42"
    assert "c0ffee42" in d["commit_url"]


def test_reject_at_dept_stage_flow(auth_client, cr_setup):
    """submitted → rejected (at dept stage)."""
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    r = _dept_reject(auth_client, cr["id"], note="Needs more detail")
    d = r.json()
    assert d["status"] == "rejected"
    assert d["dept_head_rejected_at"] is not None
    assert d["admin_approved_at"] is None

    # Confirm it's visible in the rejected filter
    listed = auth_client.get("/change-requests?status=rejected").json()
    assert any(c["id"] == cr["id"] for c in listed)


def test_reject_at_admin_stage_flow(auth_client, cr_setup):
    """submitted → dept_head_approved → rejected (at admin stage)."""
    cr = _post_cr(auth_client, cr_setup["company_id"], cr_setup["personnel_id"]).json()
    _dept_approve(auth_client, cr["id"])
    r = _admin_reject(auth_client, cr["id"], note="Security audit required first")
    d = r.json()
    assert d["status"] == "rejected"
    assert d["dept_head_approved_at"] is not None  # stage 1 preserved
    assert d["admin_rejected_at"] is not None
    assert d["commit_sha"] is None
