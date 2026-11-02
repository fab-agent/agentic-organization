"""POST /me/workspace/report (ADR-0035) and the monitoring `clients` section."""

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from models import WorkspaceClientReport, WorkspaceManifestState
from services.auth import create_access_token
from tests.conftest import make_company, make_member, make_personnel, make_user

GOOD = {
    "client_version": "1.4.2",
    "epoch": 1,
    "generation": 5,
    "missing": 0,
    "modified": 0,
    "extra": 0,
    "unmanaged": 0,
    "interrupted": False,
}


def _h(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def world(db_session):
    a, b = make_company(db_session, "A", "a"), make_company(db_session, "B", "b")
    w = type("W", (), {})()
    w.a, w.b = a, b
    w.founder = make_user(db_session, "f@a.test", "Founder")
    w.alice = make_user(db_session, "alice@a.test", "Alice")
    w.bob = make_user(db_session, "bob@a.test", "Bob")
    w.carol = make_user(db_session, "carol@b.test", "Carol")
    w.nolink = make_user(db_session, "n@a.test", "Nolink")
    for u, c, role in (
        (w.founder, a, "founder"),
        (w.alice, a, "user"),
        (w.bob, a, "user"),
        (w.carol, b, "founder"),
        (w.nolink, a, "user"),
    ):
        make_member(db_session, u.id, c.id, role)
    w.p_alice = make_personnel(db_session, a.id, "Alice", "alice", type="human")
    w.p_bob = make_personnel(db_session, a.id, "Bob", "bob", type="human")
    w.p_carol = make_personnel(db_session, b.id, "Carol", "carol", type="human")
    w.p_alice.user_id, w.p_bob.user_id, w.p_carol.user_id = (
        w.alice.id,
        w.bob.id,
        w.carol.id,
    )
    for p in (w.p_alice, w.p_bob, w.p_carol):
        db_session.add(p)
    db_session.commit()
    return w


def post(client, user, body=None, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return client.post(
        "/me/workspace/report" + (f"?{qs}" if qs else ""),
        json=GOOD if body is None else body,
        headers=_h(user) if user else {},
    )


def rows(db_session):
    db_session.expire_all()
    return db_session.exec(select(WorkspaceClientReport)).all()


def test_a_report_is_stored_for_the_caller_only(client, db_session, world):
    assert post(client, None).status_code == 401
    r = post(client, world.alice, {**GOOD, "missing": 2, "modified": 1})
    assert r.status_code == 204
    (row,) = rows(db_session)
    assert (row.person_id, row.company_id) == (world.p_alice.id, world.a.id)
    assert (row.missing, row.modified, row.generation) == (2, 1, 5)


def test_identity_comes_from_the_session_never_the_body(client, db_session, world):
    # a person id in the body is an unknown field: refused, nothing stored
    r = post(client, world.alice, {**GOOD, "person_id": world.p_bob.id})
    assert r.status_code == 422 and rows(db_session) == []
    r = post(client, world.alice, {**GOOD, "company_id": world.b.id})
    assert r.status_code == 422 and rows(db_session) == []
    # a company the caller does not belong to (query) is not reachable
    assert post(client, world.alice, company_id=world.b.id).status_code in (403, 404)
    assert rows(db_session) == []
    # an account without a personnel record has nothing to report for
    assert post(client, world.nolink).status_code == 404


@pytest.mark.parametrize(
    "patch",
    [
        {"extra_field": 1},
        {"missing": -1},
        {"modified": 100001},
        {"generation": 2**53},
        {"epoch": 2**31},
        {"interrupted": "maybe"},
        {"client_version": ""},
        {"client_version": "x" * 33},
        {"client_version": "1.0; drop table"},
        {"missing": 1.5},
        {"unmanaged": "3"},
    ],
)
def test_strict_body(client, db_session, world, patch):
    assert post(client, world.alice, {**GOOD, **patch}).status_code == 422
    assert rows(db_session) == []


def test_missing_fields_are_refused(client, db_session, world):
    body = dict(GOOD)
    body.pop("missing")
    assert post(client, world.alice, body).status_code == 422


def test_replace_not_append_and_at_most_one_report_per_30_seconds(
    client, db_session, world
):
    assert post(client, world.alice).status_code == 204
    r = post(client, world.alice, {**GOOD, "missing": 9})
    assert r.status_code == 429 and r.headers["retry-after"] == "30"
    (row,) = rows(db_session)
    assert row.missing == 0  # the refused one wrote nothing
    row.received_at = datetime.utcnow() - timedelta(seconds=31)
    db_session.add(row)
    db_session.commit()
    assert post(client, world.alice, {**GOOD, "missing": 9}).status_code == 204
    (row,) = rows(db_session)
    assert row.missing == 9
    # another person is not affected by Alice's limit
    assert post(client, world.bob).status_code == 204
    assert len(rows(db_session)) == 2


def _clients(client, world):
    r = client.get(
        f"/admin/monitoring?company_id={world.a.id}", headers=_h(world.founder)
    )
    assert r.status_code == 200
    return r.json()["sections"]["clients"]


def _issue(db_session, company, person, generation):
    db_session.add(
        WorkspaceManifestState(
            company_id=company.id, person_id=person.id, epoch=1, generation=generation
        )
    )
    db_session.commit()


def test_monitoring_clients_section(client, db_session, world):
    c = _clients(client, world)
    assert c["status"] == "unknown" and c["reason"] == "no_reports" and c["issued"] == 0
    _issue(db_session, world.a, world.p_alice, 5)
    _issue(db_session, world.a, world.p_bob, 7)
    assert (
        _clients(client, world)["reason"] == "no_reports"
    )  # issued, nobody has reported
    # Alice: current and clean. Bob (generation 7 issued) reports 6 with drift.
    assert post(client, world.alice).status_code == 204
    assert (
        post(
            client,
            world.bob,
            {**GOOD, "generation": 6, "modified": 2, "interrupted": True},
        ).status_code
        == 204
    )
    c = _clients(client, world)
    assert c["self_reported"] is True
    assert (c["issued"], c["reporting"], c["behind"], c["silent"], c["drifting"]) == (
        2,
        2,
        1,
        0,
        1,
    )
    assert c["status"] == "warn"
    assert c["drifting_people"] == [
        {
            "name": "Bob",
            "missing": 0,
            "modified": 2,
            "extra": 0,
            "unmanaged": 0,
            "interrupted": True,
        }
    ]
    # a clean Bob: ok
    row = [r for r in rows(db_session) if r.person_id == world.p_bob.id][0]
    row.modified, row.interrupted, row.generation = 0, False, 7
    db_session.add(row)
    db_session.commit()
    assert _clients(client, world)["status"] == "ok"
    # silence for 7 days is shown as information, not a warning
    row.received_at = datetime.utcnow() - timedelta(days=8)
    db_session.add(row)
    db_session.commit()
    c = _clients(client, world)
    assert c["silent"] == 1 and c["status"] == "ok"


def test_other_companies_and_unissued_people_never_count(client, db_session, world):
    _issue(db_session, world.a, world.p_alice, 5)
    _issue(db_session, world.b, world.p_carol, 5)
    assert (
        post(client, world.carol, {**GOOD, "missing": 50}).status_code == 204
    )  # B's person
    assert (
        post(client, world.bob, {**GOOD, "missing": 50}).status_code == 204
    )  # A, but never issued
    assert _clients(client, world)["reporting"] == 0
    assert post(client, world.alice).status_code == 204
    c = _clients(client, world)
    assert c["reporting"] == 1 and c["drifting"] == 0 and "Carol" not in str(c)


def test_the_drifting_list_is_capped(client, db_session, world):
    from services import monitoring

    _issue(db_session, world.a, world.p_alice, 1)
    for i in range(monitoring.MAX_DRIFT_NAMES + 5):
        u = make_user(db_session, f"x{i}@a.test", f"X{i}")
        make_member(db_session, u.id, world.a.id, "user")
        p = make_personnel(db_session, world.a.id, f"P{i:02d}", f"p{i}", type="human")
        _issue(db_session, world.a, p, 1)
        db_session.add(
            WorkspaceClientReport(
                company_id=world.a.id, person_id=p.id, generation=1, missing=1
            )
        )
    db_session.commit()
    c = _clients(client, world)
    assert c["drifting"] == monitoring.MAX_DRIFT_NAMES + 5
    assert len(c["drifting_people"]) == monitoring.MAX_DRIFT_NAMES


def test_the_migration_matches_the_model(tmp_path):
    """The table in the migration has every column of the model."""
    import re

    from models import WorkspaceClientReport as M

    text = open("migrations/versions/b7e3a9c1d452_workspace_client_report.py").read()
    for col in M.__table__.columns.keys():
        assert re.search(rf'"{col}"', text), col
