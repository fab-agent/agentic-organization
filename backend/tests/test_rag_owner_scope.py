"""What a chat may recall is its own person's work (Codex review, signals #1)."""

import numpy as np
import pytest

from models import AgentMemory, AgentSession, SessionMessage
from tests.conftest import make_agent_config, make_member, make_personnel, make_user


def _fake_embed(text: str) -> np.ndarray:
    arr = np.zeros(384, dtype=np.float32)
    for i, ch in enumerate(text):
        arr[i % 384] += ord(ch) / 10000.0
    n = np.linalg.norm(arr)
    return (arr / n if n else arr).astype(np.float32)


@pytest.fixture()
def shared_agent(auth_client, db_session, monkeypatch):
    import services.rag_service as rs

    monkeypatch.setattr(rs, "embed", _fake_embed)
    monkeypatch.setattr(rs, "MIN_RECORDS_FOR_SEARCH", 1)
    rs.init_rag_db()
    co = auth_client._test_company
    agent = make_personnel(
        db_session, co.id, name="Shared", slug="shared", type="agent"
    )
    make_agent_config(db_session, agent.id)
    a = make_user(db_session, email="a@a.com", name="A")
    b = make_user(db_session, email="b@a.com", name="B")
    for u in (a, b):
        make_member(db_session, u.id, co.id, role="user")
    sa_ = AgentSession(personnel_id=agent.id, user_id=a.id)
    sb = AgentSession(personnel_id=agent.id, user_id=b.id)
    legacy = AgentSession(personnel_id=agent.id, user_id=None)
    db_session.add_all([sa_, sb, legacy])
    db_session.flush()
    texts = {
        "A": "Ali's salary will be reduced next quarter, keep this private",
        "B": "Budget review for the logistics department finished today",
        "L": "Legacy channel note about the shipping schedule for Friday",
    }
    for sess, key in ((sa_, "A"), (sb, "B"), (legacy, "L")):
        db_session.add(
            SessionMessage(session_id=sess.id, role="assistant", content=texts[key])
        )
    db_session.add(
        AgentMemory(
            personnel_id=agent.id,
            session_id=sa_.id,
            summary="A summary: salary talk with the CEO",
        )
    )
    db_session.add(
        AgentMemory(
            personnel_id=agent.id,
            session_id=sb.id,
            summary="B summary: logistics budget decisions",
        )
    )
    db_session.commit()
    rs.index_new_records()
    return {"rs": rs, "agent": agent.id, "co": co.id, "a": a.id, "b": b.id}


def test_records_carry_their_owner(shared_agent, db_session):
    from models import EmbeddingRecord

    owners = {
        r.chunk_text[:5]: r.owner_user_id
        for r in db_session.query(EmbeddingRecord).all()
    }
    assert owners["Ali's"] == shared_agent["a"] and owners["Budge"] == shared_agent["b"]
    assert owners["Legac"] is None


def test_a_chat_recalls_only_its_own_persons_work(shared_agent):
    rs = shared_agent["rs"]
    q = "salary reduced quarter private budget logistics shipping"
    kw = dict(company_id=shared_agent["co"], personnel_id=shared_agent["agent"], k=10)
    mine_b = rs.search(q, viewer=shared_agent["b"], **kw)
    assert mine_b and all("salary" not in h["chunk_text"] for h in mine_b)
    mine_a = rs.search(q, viewer=shared_agent["a"], **kw)
    assert any("salary" in h["chunk_text"] for h in mine_a)
    assert all("logistics" not in h["chunk_text"] for h in mine_a)
    # an ownerless session (channel, A2A) reads only the ownerless tier
    shared = rs.search(q, viewer=None, **kw)
    assert [h["chunk_text"][:6] for h in shared] == ["Legacy"]


def test_memories_follow_the_same_rule(shared_agent):
    from services.memory_service import load_agent_memories

    b = load_agent_memories(shared_agent["agent"], viewer=shared_agent["b"])
    assert b == ["B summary: logistics budget decisions"]
    assert load_agent_memories(shared_agent["agent"], viewer=None) == []
    assert (
        len(load_agent_memories(shared_agent["agent"])) == 2
    )  # system callers: unfiltered
