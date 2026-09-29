"""Fit rubric: parsing, linter, verdicts (ADR-0021). No model calls."""

import json

import pytest
from sqlmodel import Session

import models
from services import rubric as rb
from tests.conftest import make_company

SOURCES = {
    "company.goals.2": "Grow recurring revenue 20% in 2026",
    "policy.kvkk": "Personal data is used only for the stated purpose.",
}

GOOD = """
version: 1
criteria:
  - id: G2-recurring-revenue
    question: Does this work advance recurring revenue?
    good_answer: "yes"
    source: {kind: goal, ref: company.goals.2, quote: "grow recurring   revenue 20%"}
    scope: {departments: [sales]}
    applies_when: {domains: [sales, renewals]}
    status: live
  - id: P-KVKK-purpose
    question: Does the output expose personal customer data beyond what the task needs?
    good_answer: no
    source: {kind: policy, ref: policy.kvkk, quote: "used only for the stated purpose"}
    scope: {company: true}
    applies_when: {sensitivities: [personal]}
    status: shadow
"""


def crit(**over):
    base = {
        "id": "C1",
        "question": "Does this work advance recurring revenue?",
        "good_answer": "yes",
        "source": {
            "kind": "goal",
            "ref": "company.goals.2",
            "quote": "recurring revenue",
        },
        "scope": {"company": True},
    }
    base.update(over)
    return rb.Criterion.model_validate(base)


def codes(criteria, sources=SOURCES, **kw):
    return {f.code for f in rb.lint(rb.Rubric(criteria=criteria), sources, **kw)}


def test_a_good_rubric_parses_and_passes_the_floor():
    r = rb.parse_rubric(GOOD)
    assert [c.id for c in r.criteria] == ["G2-recurring-revenue", "P-KVKK-purpose"]
    # unquoted YAML `no` is read as the answer "no", not as a boolean
    assert r.criteria[1].good_answer == "no"
    assert rb.lint(r, SOURCES, department_slugs={"sales"}) == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        "- a\n- b",
        "criteria: {a: 1}",
        "criteria: [{id: x}]",
        "a: [",
        "version: 1\nextra: 1",
    ],
)
def test_unreadable_files_are_rubric_errors(text):
    with pytest.raises(rb.RubricError):
        rb.parse_rubric(text)


def test_too_large_file_is_refused():
    with pytest.raises(rb.RubricError, match="too large"):
        rb.parse_rubric("x" * (rb.MAX_RUBRIC_BYTES + 1))


def test_source_quote_rules():
    assert "no_source_quote" in codes(
        [crit(source={"kind": "goal", "ref": "company.goals.2"})]
    )
    assert "quote_not_in_source" in codes(
        [
            crit(
                source={
                    "kind": "goal",
                    "ref": "company.goals.2",
                    "quote": "halve costs",
                }
            )
        ]
    )
    assert "unknown_source" in codes(
        [
            crit(
                source={
                    "kind": "goal",
                    "ref": "company.goals.9",
                    "quote": "recurring revenue",
                }
            )
        ]
    )
    assert codes([crit()]) == set()


@pytest.mark.parametrize(
    "question,code",
    [
        ("Does this advance revenue and/or retention?", "several_questions"),
        ("Is it good? Is it fast?", "several_questions"),
        ("Does this advance revenue", "not_a_question"),
        ("Was the employee fast enough?", "about_the_person"),
        ("Does she show a good attitude?", "about_the_person"),
        ("Çalışan hedefe uygun mu çalıştı?", "about_the_person"),
        ("Did typing speed improve?", "activity_not_work"),
        ("Was the screenshot archived?", "activity_not_work"),
        ("Was the work finished within working hours?", "activity_not_work"),
        ("Does the plan favour a gender?", "protected_characteristic"),
        ("Yaş grubuna göre mi öneri yapıldı?", "protected_characteristic"),
        ("x" * 301 + "?", "long_question"),
        ("", "empty_question"),
    ],
)
def test_question_rules(question, code):
    assert code in codes([crit(question=question)])


def test_personal_data_word_is_not_mistaken_for_a_person():
    ok = crit(question="Does the output expose personal customer data?")
    assert "about_the_person" not in codes([ok])


def test_ids_thresholds_scope_and_applies_when():
    assert "bad_id" in codes([crit(id="a b")])
    assert "duplicate_id" in codes([crit(), crit()])
    assert "bad_thresholds" in codes([crit(thresholds={"met": 0.4, "not_met": 0.6})])
    assert "bad_thresholds" in codes([crit(thresholds={"met": 1.0, "not_met": 0.3})])
    assert "no_scope" in codes([crit(scope={})])
    assert "unknown_department" in codes(
        [crit(scope={"departments": ["ghost"]})], department_slugs={"sales"}
    )
    assert "bad_applies_key" in codes([crit(applies_when={"mood": ["x"]})])
    assert "bad_applies_value" in codes([crit(applies_when={"domains": []})])


def test_personal_data_criteria_need_a_policy_source():
    c = crit(applies_when={"sensitivities": ["personal"]})
    assert "personal_without_policy" in codes([c])
    p = crit(
        applies_when={"sensitivities": ["personal"]},
        source={"kind": "policy", "ref": "policy.kvkk", "quote": "stated purpose"},
    )
    assert "personal_without_policy" not in codes([p])


def test_caps_count_company_wide_criteria_in_every_department():
    live = lambda i, **k: crit(id=f"C{i}", status="live", **k)  # noqa: E731
    dept = [
        live(i, scope={"departments": ["sales"]})
        for i in range(rb.MAX_LIVE_PER_DEPARTMENT)
    ]
    assert "too_many_for_department" not in codes(dept)
    over = dept + [live(99, scope={"company": True})]
    assert "too_many_for_department" in codes(over)
    # retired and shadow criteria do not count toward the live cap
    ok = dept + [crit(id="S1", status="shadow"), crit(id="R1", status="retired")]
    assert "too_many_for_department" not in codes(ok)
    many = [crit(id=f"D{i}", status="draft") for i in range(rb.MAX_CRITERIA_TOTAL + 1)]
    assert "too_many" in codes(many)
    retired = [
        crit(id=f"D{i}", status="retired") for i in range(rb.MAX_CRITERIA_TOTAL + 5)
    ]
    assert "too_many" not in codes(retired)


def test_hash_changes_with_meaning_not_with_whitespace_or_case():
    a = crit()
    assert rb.criterion_hash(a) == rb.criterion_hash(
        crit(question="  does THIS work advance   recurring revenue?  ")
    )
    assert rb.criterion_hash(a) != rb.criterion_hash(
        crit(question="Does this grow recurring revenue?")
    )
    assert rb.criterion_hash(a) != rb.criterion_hash(crit(good_answer="no"))
    assert rb.criterion_hash(a) != rb.criterion_hash(
        crit(thresholds={"met": 0.8, "not_met": 0.3})
    )
    # the id is not part of the identity
    assert rb.criterion_hash(a) == rb.criterion_hash(crit(id="other"))


@pytest.mark.parametrize(
    "good,p,expected",
    [
        ("yes", 0.9, "met"),
        ("yes", 0.7, "met"),
        ("yes", 0.5, "unclear"),
        ("yes", 0.3, "not_met"),
        ("yes", 0.0, "not_met"),
        ("no", 0.1, "met"),
        ("no", 0.9, "not_met"),
        ("no", 0.5, "unclear"),
        ("yes", None, "unclear"),
        ("yes", 1.5, "unclear"),
        ("yes", -0.1, "unclear"),
        ("yes", float("nan"), "unclear"),
        ("yes", True, "unclear"),
    ],
)
def test_verdict_mapping(good, p, expected):
    assert rb.verdict(crit(good_answer=good), p) == expected


def test_applies_checks_scope_and_tags_and_unknown_means_not_applicable():
    c = crit(
        scope={"departments": ["sales"]},
        applies_when={"domains": ["sales"], "tasks": ["analysis"]},
    )
    assert rb.applies(c, {"domain": "sales", "task": "analysis"}, "sales")
    assert not rb.applies(c, {"domain": "sales", "task": "analysis"}, "finance")
    assert not rb.applies(c, {"domain": "sales"}, "sales")  # missing tag: not rated
    assert not rb.applies(c, {"domain": "hr", "task": "analysis"}, "sales")
    assert rb.applies(crit(), {}, None)  # company-wide, no filter


def test_collect_sources_reads_company_department_and_policy_text(
    db_session, test_engine
):
    with Session(test_engine) as s:
        co = make_company(s)
        co.metadata_json = json.dumps(
            {
                "mission": "Ship",
                "values": ["Customer first", "Own it"],
                "goals": "Grow\nSave",
            }
        )
        s.add(co)
        s.add(
            models.Department(
                company_id=co.id,
                name="Sales",
                slug="sales",
                goals="Close deals",
                description="Sells",
            )
        )
        s.add(
            models.Policy(
                company_id=co.id,
                name="KVKK",
                slug="kvkk",
                content="Body",
                is_active=True,
            )
        )
        s.add(
            models.Policy(
                company_id=co.id, name="Old", slug="old", content="x", is_active=False
            )
        )
        s.commit()
        src = rb.collect_sources(s, co.id)
    assert src["company.mission"] == "Ship"
    assert src["company.values.2"] == "Own it"
    assert src["company.goals.2"] == "Save"
    assert src["department.sales.goals.1"] == "Close deals"
    assert src["department.sales.description"] == "Sells"
    assert src["policy.kvkk"] == "Body" and "policy.old" not in src


def test_collect_sources_survives_bad_metadata(db_session, test_engine):
    with Session(test_engine) as s:
        co = make_company(s)
        co.metadata_json = "{not json"
        s.add(co)
        s.commit()
        assert rb.collect_sources(s, co.id) == {}
