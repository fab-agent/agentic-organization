"""revocation_maintenance() — prune expired rows, auto-revoke stale sessions (ADR-0007/0009)."""

from datetime import datetime, timedelta

from services.persona_revocation import is_revoked, revocation_maintenance


def test_prunes_old_revoked_tokens(client, db_session):
    from models import RevokedToken

    db_session.add(
        RevokedToken(
            jti="old",
            persona_id="p",
            revoked_at=datetime.utcnow() - timedelta(hours=30),
        )
    )
    db_session.add(RevokedToken(jti="fresh", persona_id="p"))
    db_session.commit()

    res = revocation_maintenance()
    assert res["pruned"] == 1
    assert db_session.get(RevokedToken, "old") is None
    assert db_session.get(RevokedToken, "fresh") is not None


def test_autorevoke_off_by_default(client, db_session):
    from models import PersonaHeartbeat

    db_session.add(
        PersonaHeartbeat(
            persona_id="p1",
            company_id="c1",
            last_seen=datetime.utcnow() - timedelta(minutes=30),
        )
    )
    db_session.commit()

    res = revocation_maintenance()
    assert res["revoked"] == 0
    assert db_session.get(PersonaHeartbeat, "p1") is not None


def test_autorevoke_kills_stale_session_when_enabled(client, db_session):
    from models import AppConfig, PersonaHeartbeat

    db_session.add(AppConfig(key="heartbeat.autorevoke", value="true"))
    db_session.add(
        PersonaHeartbeat(
            persona_id="p1",
            company_id="c1",
            last_seen=datetime.utcnow() - timedelta(minutes=30),
        )
    )
    db_session.add(
        PersonaHeartbeat(
            persona_id="p2",
            company_id="c1",
            last_seen=datetime.utcnow(),  # fresh — untouched
        )
    )
    db_session.commit()

    res = revocation_maintenance()
    assert res["revoked"] == 1
    assert db_session.get(PersonaHeartbeat, "p1") is None
    assert db_session.get(PersonaHeartbeat, "p2") is not None
    # p1's tokens issued before now are dead
    assert is_revoked(None, "p1", datetime.utcnow() - timedelta(minutes=1)) is True
    assert is_revoked(None, "p2", datetime.utcnow() - timedelta(minutes=1)) is False


def test_respects_custom_stale_minutes(client, db_session):
    from models import AppConfig, PersonaHeartbeat

    db_session.add(AppConfig(key="heartbeat.autorevoke", value="true"))
    db_session.add(AppConfig(key="heartbeat.stale_minutes", value="60"))
    db_session.add(
        PersonaHeartbeat(
            persona_id="p1",
            company_id="c1",
            last_seen=datetime.utcnow() - timedelta(minutes=30),  # < 60, still ok
        )
    )
    db_session.commit()

    res = revocation_maintenance()
    assert res["revoked"] == 0
    assert db_session.get(PersonaHeartbeat, "p1") is not None
