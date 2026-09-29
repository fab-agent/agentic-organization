"""
Prompt assembly (ADR-0020): sections, tiers, token budget, the per-section
report, company / owner context, and stable-first ordering for prompt caching.
"""

import json
import logging

import pytest

import models
from services.context_assembly import (
    DROP_ORDER,
    assemble,
    clip,
    company_text,
    estimate_tokens,
)
from tests.conftest import make_agent_config, make_company, make_personnel


def _person(db_session, co, name="Ada", slug="ada", **kw):
    p = make_personnel(db_session, co.id, name=name, slug=slug, title="Analyst", **kw)
    db_session.commit()
    return p


def _meta(db_session, co, **meta):
    co.metadata_json = json.dumps(meta)
    db_session.add(co)
    db_session.commit()


def _names(a):
    return [s.name for s in a.sections]


# ── estimation ────────────────────────────────────────────────────────────────


def test_estimate_tokens_grows_with_text_and_is_zero_for_empty():
    assert estimate_tokens("") == 0
    assert 0 < estimate_tokens("hello") < estimate_tokens("hello " * 100)


def test_accented_text_counts_more_tokens_per_character():
    plain = "a" * 300
    turkish = "ş" * 300
    assert estimate_tokens(turkish) > estimate_tokens(plain)


def test_clip_collapses_whitespace_and_marks_truncation():
    assert clip("a   b\n c", 50) == "a b c"
    out = clip("x" * 100, 10)
    assert len(out) == 10 and out.endswith("…")


# ── company context ───────────────────────────────────────────────────────────


def test_company_section_from_metadata(client, db_session):
    co = make_company(db_session)
    _meta(
        db_session,
        co,
        mission="Make finance calm",
        vision="Every team has an agent",
        values=["Customer first", "Own it"],
        goals=["Grow ARR 20%", "Cut close time to 3 days"],
    )
    text = company_text(db_session, co.id)
    assert text.startswith("Company: Test Corp")
    for want in (
        "Mission: Make finance calm",
        "Vision:",
        "Values: Customer first, Own it",
        "- Grow ARR 20%",
    ):
        assert want in text


def test_company_metadata_is_capped(client, db_session):
    co = make_company(db_session)
    _meta(
        db_session,
        co,
        mission="m" * 5000,
        values=[f"value-{i}" for i in range(50)],
        goals=[f"goal {i} " + "z" * 500 for i in range(50)],
    )
    text = company_text(db_session, co.id)
    assert text.count("\n  - ") == 5  # at most 5 goals
    assert text.count("value-") == 8  # at most 8 values
    assert len(text) < 1800
    assert estimate_tokens(text) < 500


def test_company_text_accepts_newline_string_goals(client, db_session):
    co = make_company(db_session)
    _meta(db_session, co, goals="first\nsecond\n\nthird")
    assert "  - second" in company_text(db_session, co.id)


def test_no_metadata_or_unknown_company_gives_no_section(client, db_session):
    co = make_company(db_session)
    assert company_text(db_session, co.id) is None
    assert company_text(db_session, "nope") is None
    assert company_text(db_session, None) is None
    co.metadata_json = "{not json"
    db_session.add(co)
    db_session.commit()
    assert company_text(db_session, co.id) is None


# ── sections and ordering ─────────────────────────────────────────────────────


def test_minimal_prompt_keeps_the_previous_wording(client, db_session):
    co = make_company(db_session)
    p = _person(db_session, co)
    a = assemble(p, None, [], company_id=co.id)
    assert _names(a) == ["identity", "closing"]
    assert a.text() == (
        "You are Ada.\nTitle: Analyst\n"
        "\nRespond helpfully and concisely. Use tools when they would help."
    )


def test_stable_sections_come_before_per_turn_ones(client, db_session):
    co = make_company(db_session)
    _meta(db_session, co, mission="M")
    p = _person(db_session, co)
    dept = models.Department(name="Finance", slug="fin", goals="close fast")
    a = assemble(
        p,
        dept,
        [],
        ["Expense policy"],
        memories=["prev"],
        knowledge=[
            {
                "created_at": "2026-09-01T00:00",
                "source_type": "task_result",
                "chunk_text": "k",
            }
        ],
        company_id=co.id,
    )
    assert _names(a) == [
        "identity",
        "company",
        "department",
        "rules",
        "closing",
        "memory",
        "knowledge",
    ]
    tiers = [s.tier for s in a.sections if s.name in ("memory", "knowledge")]
    assert tiers == [2, 2]
    # nothing varying per turn precedes the last stable section
    last_stable = max(i for i, s in enumerate(a.sections) if s.tier < 2)
    first_dynamic = min(i for i, s in enumerate(a.sections) if s.tier == 2)
    assert last_stable < first_dynamic


def test_prompt_prefix_is_identical_when_only_per_turn_text_changes(client, db_session):
    co = make_company(db_session)
    _meta(db_session, co, mission="M", goals=["g"])
    p = _person(db_session, co)
    one = assemble(p, None, [], ["P"], memories=["one"], company_id=co.id).text()
    two = assemble(p, None, [], ["P"], memories=["two"], company_id=co.id).text()
    cut = one.index("Context from your previous sessions")
    assert one[:cut] == two[:cut] and one != two


def test_policy_list_is_capped(client, db_session):
    co = make_company(db_session)
    p = _person(db_session, co)
    a = assemble(p, None, [], [f"policy {i}" for i in range(30)], company_id=co.id)
    rules = next(s for s in a.sections if s.name == "rules").text
    assert rules.count("  - policy") == 20 and "(+10 more apply)" in rules


# ── the person's own job (workspace agents only) ──────────────────────────────


def test_workspace_agent_gets_its_owners_job(client, db_session):
    co = make_company(db_session)
    human = _person(db_session, co, name="Ayşe", slug="ayse", type="human")
    human.job_description = "Accounts payable: invoice matching."
    human.title = "AP Specialist"
    db_session.add(human)
    agent = _person(db_session, co, name="Ayşe Agent", slug="ayse-agent")
    cfg = make_agent_config(db_session, agent.id, responsible_id=human.id)
    cfg.is_workspace_agent = True
    db_session.add(cfg)
    db_session.commit()

    job = next(
        s
        for s in assemble(agent, None, [], company_id=co.id).sections
        if s.name == "job"
    )
    assert "You work for Ayşe, AP Specialist." in job.text
    assert "Accounts payable: invoice matching." in job.text


def test_a_manual_agent_does_not_inherit_its_responsibles_job(client, db_session):
    co = make_company(db_session)
    human = _person(db_session, co, name="H", slug="h", type="human")
    human.job_description = "secret duties"
    db_session.add(human)
    agent = _person(db_session, co, name="Bot", slug="bot")
    make_agent_config(
        db_session, agent.id, responsible_id=human.id
    )  # not a workspace agent
    db_session.commit()
    assert "job" not in _names(assemble(agent, None, [], company_id=co.id))


# ── budget and skipping ───────────────────────────────────────────────────────


def _big(db_session, co):
    _meta(db_session, co, mission="M" * 200, goals=["g" * 150] * 5)
    p = _person(db_session, co)
    dept = models.Department(name="Fin", slug="f", goals="\n".join(["dg" * 60] * 6))
    know = [
        {
            "created_at": "2026-09-01T00:00",
            "source_type": "task_result",
            "chunk_text": "k" * 300,
        }
        for _ in range(4)
    ]
    return p, dept, know


def test_over_budget_drops_optional_sections_in_order(client, db_session):
    co = make_company(db_session)
    p, dept, know = _big(db_session, co)
    kw = dict(memories=["m" * 200] * 3, knowledge=know, company_id=co.id)
    full = assemble(p, dept, [], ["Policy"], budget=10_000, **kw)
    assert full.dropped == []

    # squeeze just under the full size: only the first item in DROP_ORDER goes
    tight = assemble(p, dept, [], ["Policy"], budget=full.total_tokens - 1, **kw)
    assert [s.name for s in tight.dropped] == [DROP_ORDER[0]]
    assert tight.total_tokens <= full.total_tokens - 1

    # a very small budget drops every optional section but never required ones
    tiny = assemble(p, dept, [], ["Policy"], budget=1, **kw)
    assert {"identity", "rules", "closing"} <= set(_names(tiny))
    assert not {"knowledge", "memory", "department", "job", "company"} & set(
        _names(tiny)
    )
    assert tiny.report()["over_budget"] is True  # required text alone exceeds 1 token


def test_required_sections_survive_even_if_the_drop_order_lists_them(
    client, db_session, monkeypatch
):
    """Defence in depth: a future edit that adds a required section to DROP_ORDER
    must not be able to drop it."""
    from services import context_assembly

    monkeypatch.setattr(
        context_assembly, "DROP_ORDER", ("rules", "identity", "closing", "company")
    )
    co = make_company(db_session)
    _meta(db_session, co, mission="M" * 200)
    p = _person(db_session, co)
    a = assemble(p, None, [], ["Policy"], budget=1, company_id=co.id)
    assert {"identity", "rules", "closing"} <= set(_names(a))
    assert "company" not in _names(a)  # the optional one did go


def test_skip_leaves_sections_out_but_never_required_ones(client, db_session):
    co = make_company(db_session)
    p, dept, know = _big(db_session, co)
    a = assemble(
        p,
        dept,
        [],
        ["Policy"],
        knowledge=know,
        company_id=co.id,
        skip={"knowledge", "company", "rules", "identity"},
    )
    names = _names(a)
    assert "knowledge" not in names and "company" not in names
    assert "rules" in names and "identity" in names
    assert {s.name for s in a.dropped} == {"knowledge", "company"}


# ── the report ────────────────────────────────────────────────────────────────


def test_report_lists_sizes_but_never_text(client, db_session):
    co = make_company(db_session)
    _meta(db_session, co, mission="TOP-SECRET-MISSION")
    p = _person(db_session, co)
    a = assemble(p, None, [], memories=["PRIVATE-MEMORY"], company_id=co.id)
    rep = a.report()
    assert rep["method"] == "estimate"
    assert rep["total_tokens"] == sum(s["tokens"] for s in rep["sections"])
    assert [s["name"] for s in rep["sections"]] == _names(a)
    blob = json.dumps(rep)
    assert "TOP-SECRET-MISSION" not in blob and "PRIVATE-MEMORY" not in blob


def test_budget_comes_from_the_environment(client, db_session, monkeypatch):
    co = make_company(db_session)
    p = _person(db_session, co)
    monkeypatch.setenv("PROMPT_BUDGET_TOKENS", "123")
    assert assemble(p, None, [], company_id=co.id).budget == 123
    monkeypatch.setenv("PROMPT_BUDGET_TOKENS", "banana")
    assert assemble(p, None, [], company_id=co.id).budget == 2000


# ── wired into the chat path ──────────────────────────────────────────────────


def test_build_system_prompt_logs_the_breakdown_without_text(
    client, db_session, caplog
):
    from services.agent_runtime import build_system_prompt

    co = make_company(db_session)
    _meta(db_session, co, mission="LOGGED-MISSION")
    p = _person(db_session, co)
    with caplog.at_level(logging.INFO, logger="app"):
        text = build_system_prompt(p, None, [], company_id=co.id)
    assert "LOGGED-MISSION" in text  # company context now reaches the prompt
    rec = next(r for r in caplog.records if r.msg == "prompt_assembled")
    assert rec.extra["persona"] == p.id
    assert "LOGGED-MISSION" not in json.dumps(rec.extra)
    assert any(s["name"] == "company" for s in rec.extra["prompt"]["sections"])


@pytest.mark.parametrize("name", DROP_ORDER)
def test_drop_order_names_are_real_section_names(name):
    # guards against renaming a section and silently disabling its budget drop
    assert name in {"knowledge", "memory", "department", "job", "company"}


# ── stable_only: the context document for a client with its own prompt ─────────


def test_stable_only_has_no_tools_closing_or_per_turn_text(client, db_session):
    co = make_company(db_session)
    _meta(db_session, co, mission="M")
    p = _person(db_session, co)
    skill = models.Skill(
        agent_id="a", name="web_search", skill_type="builtin", is_active=True
    )
    kw = dict(
        memories=["MEM"],
        knowledge=[
            {"created_at": "2026-09-01T00:00", "source_type": "t", "chunk_text": "K"}
        ],
        company_id=co.id,
    )
    a = assemble(p, None, [skill], ["P"], stable_only=True, **kw)
    assert _names(a) == ["identity", "company", "rules"]
    assert "Respond helpfully" not in a.text() and "web_search" not in a.text()
    assert "MEM" not in a.text()
    # identical whatever the per-turn inputs are
    b = assemble(
        p, None, [], ["P"], stable_only=True, memories=["OTHER"], company_id=co.id
    )
    assert a.text() == b.text()
    # the normal prompt is unchanged
    assert {"closing", "skills", "memory", "knowledge"} <= set(
        _names(assemble(p, None, [skill], ["P"], **kw))
    )
