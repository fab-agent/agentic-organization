"""ADR-0037: manifest issuance is spaced out per person, and the spacing is the write."""

import re
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

import api.me_workspace as mw
from models import AuditEvent, WorkspaceIssueStamp
from tests.test_me_workspace import _get, env, people  # noqa: F401


@pytest.fixture()
def spaced(monkeypatch):
    monkeypatch.setattr(mw, "ISSUE_MIN_INTERVAL", timedelta(seconds=10))


def _events(db_session):
    db_session.expire_all()
    return len(
        db_session.exec(
            select(AuditEvent).where(AuditEvent.action == "workspace_manifest_issued")
        ).all()
    )


def test_a_second_request_inside_the_interval_is_refused_without_any_write(
    client,
    env,
    people,
    db_session,
    spaced,  # noqa: F811
):
    u = people["emp_user"]
    assert _get(client, u).status_code == 200
    assert _events(db_session) == 1
    for _ in range(5):
        r = _get(client, u)
        assert r.status_code == 429
        assert r.headers["Retry-After"] == "10"
        assert r.json()["detail"] == {
            "error": "rate_limited",
            "reason": "try_again_later",
        }
    assert _events(db_session) == 1  # the audit chain did not grow


def test_it_is_per_person_so_one_cannot_starve_another(
    client,
    env,
    people,
    spaced,  # noqa: F811
):
    assert _get(client, people["emp_user"]).status_code == 200
    assert _get(client, people["emp_user"]).status_code == 429
    assert _get(client, people["founder"]).status_code == 200


def test_after_the_interval_it_works_again_and_generations_keep_growing(
    client,
    env,
    people,
    db_session,
    spaced,  # noqa: F811
):
    u = people["emp_user"]
    first = _get(client, u).json()["manifest"]["payload"]["generation"]
    row = db_session.exec(select(WorkspaceIssueStamp)).first()
    row.issued_at = datetime.utcnow() - timedelta(seconds=11)
    db_session.add(row)
    db_session.commit()
    r = _get(client, u)
    assert r.status_code == 200
    assert r.json()["manifest"]["payload"]["generation"] == first + 1


def test_a_refused_request_does_not_use_up_a_generation(
    client,
    env,
    people,
    db_session,
    spaced,  # noqa: F811
):
    from models import WorkspaceManifestState

    u = people["emp_user"]
    g = _get(client, u).json()["manifest"]["payload"]["generation"]
    for _ in range(3):
        assert _get(client, u).status_code == 429
    db_session.expire_all()
    (state,) = db_session.exec(select(WorkspaceManifestState)).all()
    assert state.generation == g  # the refusals allocated and signed nothing


def test_a_platform_that_cannot_sign_answers_503_and_the_client_waits(
    client,
    env,
    people,
    spaced,  # noqa: F811
):
    u = people["emp_user"]
    (env.dir / "signing.cert.json").write_text("{}")
    r = _get(client, u)
    assert r.status_code == 503 and r.headers["Retry-After"] == "30"
    # the slot was taken by the attempt; a client honouring Retry-After is never refused
    assert _get(client, u).status_code == 429


def test_files_and_crl_are_not_spaced(client, env, people, spaced):  # noqa: F811
    u = people["emp_user"]
    body = _get(client, u).json()
    sha = body["manifest"]["payload"]["layout"]["sha256"]
    for _ in range(4):
        r = client.get(
            f"/me/workspace/files/{sha}",
            headers={
                "Authorization": f"Bearer {__import__('services.auth', fromlist=['x']).create_access_token(u.id)}"
            },
        )
        assert r.status_code == 200


def test_the_migration_matches_the_model():
    text = open("migrations/versions/c4f8a2d6e913_workspace_issue_stamp.py").read()
    for col in WorkspaceIssueStamp.__table__.columns.keys():
        assert re.search(rf'"{col}"', text), col
