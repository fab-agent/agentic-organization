"""ADR-0039: one account is one human in a company. Never guess which of two is the caller."""

import api.me_workspace as mw  # noqa: F401
from models import Department
from tests.conftest import make_member, make_personnel, make_user
from tests.test_me_workspace import _get, _h, env, people  # noqa: F401


def _second_human(db, people_, dept_slug="ops"):
    ops = Department(company_id=people_["co"].id, name="Ops", slug=dept_slug)
    db.add(ops)
    db.flush()
    twin = make_personnel(
        db, people_["co"].id, name="AP Twin", slug="ap-twin", type="human"
    )
    twin.user_id, twin.department_id = people_["emp_user"].id, ops.id
    db.add(twin)
    db.commit()
    return twin


def test_two_humans_for_one_account_are_refused_on_every_workspace_endpoint(
    client,
    env,
    people,
    db_session,  # noqa: F811
):
    u = people["emp_user"]
    assert _get(client, u).status_code == 200  # fine while there is one
    sha = _get(client, u).json()["manifest"]["payload"]["layout"]["sha256"]
    _second_human(db_session, people)
    assert _get(client, u).status_code == 409
    r = client.get(f"/me/workspace/files/{sha}", headers=_h(u))
    assert r.status_code == 409
    body = {
        "client_version": "1.0",
        "epoch": 1,
        "generation": 1,
        "missing": 0,
        "modified": 0,
        "extra": 0,
        "unmanaged": 0,
        "interrupted": False,
    }
    assert (
        client.post("/me/workspace/report", headers=_h(u), json=body).status_code == 409
    )


def test_the_other_account_is_unaffected(client, env, people, db_session):  # noqa: F811
    _second_human(db_session, people)
    assert _get(client, people["founder"]).status_code == 200


def test_an_agent_record_on_the_same_account_is_not_a_second_human(
    client,
    env,
    people,
    db_session,  # noqa: F811
):
    a = make_personnel(
        db_session, people["co"].id, name="Bot", slug="bot", type="agent"
    )
    a.user_id = people["emp_user"].id
    db_session.add(a)
    db_session.commit()
    assert _get(client, people["emp_user"]).status_code == 200


def test_one_account_may_be_a_person_in_two_companies(
    client,
    env,
    people,
    db_session,  # noqa: F811
):
    from tests.conftest import make_company

    other = make_company(db_session, name="Other", slug="other-co")
    make_member(db_session, people["emp_user"].id, other.id, role="user")
    p = make_personnel(
        db_session, other.id, name="AP Elsewhere", slug="ape", type="human"
    )
    p.user_id = people["emp_user"].id
    db_session.add(p)
    db_session.commit()
    # two companies, one person each: still resolved by the explicit company
    assert (
        _get(client, people["emp_user"], company_id=people["co"].id).status_code == 200
    )
    assert _get(client, people["emp_user"]).status_code == 400  # which company?


def test_inviting_a_second_person_onto_a_linked_account_is_refused(
    auth_client, db_session
):
    co = auth_client._test_company
    u = make_user(db_session, email="dup@test.com", name="Dup")
    make_member(db_session, u.id, co.id, role="user")
    first = make_personnel(db_session, co.id, name="First", slug="first", type="human")
    first.user_id, first.email = u.id, "dup@test.com"
    second = make_personnel(
        db_session, co.id, name="Second", slug="second", type="human"
    )
    second.email = "dup@test.com"
    db_session.add_all([first, second])
    db_session.commit()
    from models import Personnel, User

    before = db_session.get(User, u.id).password_hash
    r = auth_client.post(f"/personnel/{second.id}/invite", json={"role": "user"})
    assert r.status_code == 409
    db_session.expire_all()
    assert db_session.get(Personnel, second.id).user_id is None
    assert db_session.get(User, u.id).password_hash == before  # nothing was rewritten


def test_a_request_field_cannot_choose_the_profile(client, env, people):  # noqa: F811
    """The founder asks, in the query, to be a plain finance user: the session's membership wins."""
    r = _get(
        client,
        people["founder"],
        role="user",
        department_id=people["fin"].id,
        person_id=people["emp"].id,
    )
    assert r.status_code == 200
    p = r.json()["manifest"]["payload"]
    assert p["layout"]["id"] == "terminals" and p["mods"] == []  # the managers profile
    assert r.json()["identity"]["person_id"] != people["emp"].id


def test_two_invites_at_once_link_the_account_to_only_one_person(
    auth_client, db_session, test_engine
):
    """Both invites pass through the same barrier right before linking: exactly one wins."""
    import threading

    from fastapi import HTTPException
    from sqlmodel import Session, select

    from api.personnel import link_human
    from models import Personnel

    co = auth_client._test_company
    u = make_user(db_session, email="race@test.com", name="Race")
    # no membership in this company on purpose: the lock must not depend on one existing
    a = make_personnel(db_session, co.id, name="A", slug="ra", type="human")
    b = make_personnel(db_session, co.id, name="B", slug="rb", type="human")
    db_session.commit()
    ids, uid, cid = [a.id, b.id], u.id, co.id

    barrier, out, errors = threading.Barrier(2), [], []

    def worker(pid):
        try:
            with Session(test_engine, expire_on_commit=False) as s:
                person = s.get(Personnel, pid)
                barrier.wait()
                try:
                    link_human(s, person, uid, cid)
                    out.append("linked")
                except HTTPException as e:
                    out.append(e.status_code)
        except Exception as e:  # a worker that died must fail the test
            errors.append(repr(e))

    ts = [threading.Thread(target=worker, args=(i,)) for i in ids]
    [t.start() for t in ts]
    [t.join(timeout=60) for t in ts]
    assert not errors, errors
    assert sorted(map(str, out)) == ["409", "linked"]
    db_session.expire_all()
    linked = db_session.exec(select(Personnel).where(Personnel.user_id == uid)).all()
    assert len(linked) == 1


def test_two_invites_for_the_same_new_email_do_not_end_in_a_500(
    auth_client, db_session, test_engine
):
    """The account is created by whichever invite gets there first; the other is a clean 409
    (or succeeds), never an unhandled IntegrityError."""
    import threading

    co = auth_client._test_company
    a = make_personnel(db_session, co.id, name="NA", slug="na", type="human")
    b = make_personnel(db_session, co.id, name="NB", slug="nb", type="human")
    a.email = b.email = "brand-new@test.com"
    db_session.add_all([a, b])
    db_session.commit()

    barrier, codes = threading.Barrier(2), []

    def hit(pid):
        barrier.wait()
        codes.append(
            auth_client.post(
                f"/personnel/{pid}/invite", json={"role": "user"}
            ).status_code
        )

    ts = [threading.Thread(target=hit, args=(p,)) for p in (a.id, b.id)]
    [t.start() for t in ts]
    [t.join(timeout=60) for t in ts]
    assert len(codes) == 2 and 500 not in codes, codes
    assert codes.count(201) >= 1
    from models import Personnel

    db_session.expire_all()
    linked = [
        p
        for p in (db_session.get(Personnel, a.id), db_session.get(Personnel, b.id))
        if p.user_id
    ]
    assert len(linked) == 1  # one account, one person
