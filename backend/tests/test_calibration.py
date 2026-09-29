"""Calibration of criteria and the gates it opens (ADR-0021 §5). The scorer is faked."""

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import models
from services import calibration as cal
from services import rating as rt
from services import rubric as rb
from services import work_review as wr
from tests.test_rating import RUBRIC, world  # noqa: F401


def crit(good="yes", **over):
    base = {
        "id": "C1",
        "question": "Does this work advance recurring revenue?",
        "good_answer": good,
        "source": {"kind": "goal", "ref": "company.goals.1", "quote": "x"},
        "scope": {"company": True},
    }
    base.update(over)
    return rb.Criterion.model_validate(base)


class ByText:
    """Scores by a rule on the text it receives; records what it was sent."""

    def __init__(self, rule):
        self.rule, self.seen = rule, []

    def rate(self, text, criteria):
        self.seen.append(text)
        p = self.rule(text)
        if p == "fail":
            return None
        return rt.RatingResult(p_yes={c.id: p for c in criteria}, model="fake")


def ex(n_met, n_not, prefix="w"):
    return [
        cal.Example(text=f"{prefix}-met-{i}", expected="met") for i in range(n_met)
    ] + [
        cal.Example(text=f"{prefix}-not-{i}", expected="not_met") for i in range(n_not)
    ]


def by_label(wrong=(), unclear=(), fail=()):
    """A scorer that is right except for the named example texts."""

    def rule(text):
        if text in fail:
            return "fail"
        if text in unclear:
            return 0.5
        right = 0.95 if "-met-" in text else 0.05
        return (1 - right) if text in wrong else right

    return rule


# ── evaluate ─────────────────────────────────────────────────────────────────


def test_a_scorer_that_agrees_passes():
    r = cal.evaluate(crit(), ex(10, 10), ByText(by_label()))
    assert r.passes and r.reasons == []
    assert (r.n, r.decided, r.correct, r.unclear) == (20, 20, 20, 0)
    assert r.agreement == 1.0 and r.unclear_rate == 0.0


def test_the_agreement_bar_is_on_decided_answers_and_is_inclusive():
    wrong3 = [f"w-met-{i}" for i in range(3)]
    r = cal.evaluate(crit(), ex(10, 10), ByText(by_label(wrong=wrong3)))
    assert r.agreement == 17 / 20 and r.passes  # exactly 85 %
    wrong4 = [f"w-met-{i}" for i in range(4)]
    r = cal.evaluate(crit(), ex(10, 10), ByText(by_label(wrong=wrong4)))
    assert not r.passes and any("agreement" in x for x in r.reasons)


def test_unclear_answers_are_not_errors_but_are_capped():
    six = [f"w-met-{i}" for i in range(6)]  # 6 of 20 = 30 %: allowed
    r = cal.evaluate(crit(), ex(10, 10), ByText(by_label(unclear=six)))
    assert r.passes and r.unclear == 6 and r.decided == 14 and r.agreement == 1.0
    seven = [f"w-met-{i}" for i in range(7)]  # 35 %
    r = cal.evaluate(crit(), ex(10, 10), ByText(by_label(unclear=seven)))
    assert not r.passes and any("unclear" in x for x in r.reasons)


def test_a_scorer_that_shrugs_at_everything_cannot_pass():
    r = cal.evaluate(crit(), ex(10, 10), ByText(lambda t: 0.5))
    assert not r.passes and r.agreement is None
    assert any("decided none" in x for x in r.reasons)


def test_failed_calls_count_as_unclear_and_are_reported():
    fails = [f"w-not-{i}" for i in range(8)]
    r = cal.evaluate(crit(), ex(10, 10), ByText(by_label(fail=fails)))
    assert r.errors == 8 and r.unclear == 8 and not r.passes


def test_a_small_or_lopsided_sample_cannot_pass_however_well_it_scores():
    r = cal.evaluate(crit(), ex(5, 5), ByText(by_label()))
    assert not r.passes and any("at least 20" in x for x in r.reasons)
    r = cal.evaluate(crit(), ex(18, 2), ByText(by_label()))
    assert not r.passes and any("'not_met'" in x for x in r.reasons)
    assert cal.evaluate(crit(), ex(5, 5), ByText(by_label()), min_examples=10).passes


def test_the_direction_of_the_criterion_is_respected():
    # good answer "no": the scorer's p(yes) is low for work that meets the criterion
    def inverted(text):
        return 0.05 if "-met-" in text else 0.95

    assert cal.evaluate(crit(good="no"), ex(10, 10), ByText(inverted)).passes
    assert not cal.evaluate(crit(good="yes"), ex(10, 10), ByText(inverted)).passes


def test_texts_are_redacted_before_they_are_sent_and_never_reported():
    examples = [cal.Example(text="Mailed ayse@firma.com the invoice", expected="met")]
    rater = ByText(lambda t: 0.9)
    r = cal.evaluate(crit(), examples, rater, min_examples=1, min_per_class=0)
    assert rater.seen == ["Mailed [email] the invoice"]
    assert "ayse" not in json.dumps(r.as_dict()) and "invoice" not in json.dumps(
        r.as_dict()
    )
    assert r.results == [("met", "met")]


def test_the_report_names_the_exact_wording_it_measured():
    r = cal.evaluate(crit(), ex(10, 10), ByText(by_label()))
    assert r.criterion_hash == rb.criterion_hash(crit())
    assert r.criterion_hash != rb.criterion_hash(
        crit(question="Does this grow revenue?")
    )


# ── samples file ─────────────────────────────────────────────────────────────

GOOD = """
criterion: G1
examples:
  - {text: "Built the renewal forecast.", expected: met}
  - {text: "Reformatted the seating plan.", expected: not_met}
"""


def test_samples_parse():
    s = cal.parse_samples(GOOD)
    assert s.criterion == "G1" and [e.expected for e in s.examples] == [
        "met",
        "not_met",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "- a",
        "criterion: G1",
        "criterion: G1\nexamples: [{text: x, expected: maybe}]",
        "criterion: G1\nexamples: [{text: x, expected: met, extra: 1}]",
        "a: [",
    ],
)
def test_unusable_samples_are_calibration_errors(text):
    with pytest.raises(cal.CalibrationError):
        cal.parse_samples(text)


def test_oversized_samples_are_refused():
    with pytest.raises(cal.CalibrationError, match="too large"):
        cal.parse_samples("x" * (cal.MAX_SAMPLE_BYTES + 1))


# ── the record ───────────────────────────────────────────────────────────────


def _report(c, passes=True):
    r = cal.evaluate(c, ex(10, 10), ByText(by_label()))
    r.passes = passes
    return r


def test_a_passing_record_calibrates_only_that_wording(world):  # noqa: F811
    w, c = world, crit()
    assert not cal.is_calibrated(w.db, w.co.id, c)
    cal.record(w.db, w.co.id, _report(c))
    w.db.commit()
    assert cal.is_calibrated(w.db, w.co.id, c)
    assert not cal.is_calibrated(
        w.db, w.co.id, crit(question="Does this grow revenue?")
    )
    assert not cal.is_calibrated(w.db, "other-company", c)
    assert cal.is_calibrated(w.db, w.co.id, crit(id="C1"))  # the id is part of the key
    assert not cal.is_calibrated(w.db, w.co.id, crit(id="C2"))


def test_a_failing_or_corrupt_record_does_not_calibrate(world):  # noqa: F811
    w, c = world, crit()
    cal.record(w.db, w.co.id, _report(c, passes=False))
    assert not cal.is_calibrated(w.db, w.co.id, c)
    key = f"work_review.calibration:{w.co.id}:C1:{rb.criterion_hash(c)}"
    for junk in ("{not json", "[]", '"yes"', '{"passes": "true"}'):
        wr._put(w.db, key, junk)
        assert not cal.is_calibrated(w.db, w.co.id, c)


# ── run ──────────────────────────────────────────────────────────────────────

SAMPLES = "criterion: G1-revenue\nexamples:\n" + "".join(
    f'  - {{text: "w-{k}-{i}", expected: {e}}}\n'
    for k, e in (("met", "met"), ("not", "not_met"))
    for i in range(10)
)


def test_run_calibrates_a_stored_criterion_and_saves_only_when_asked(world):  # noqa: F811
    w = world
    scorer = ByText(by_label())
    r = cal.run(w.db, w.co.id, SAMPLES, scorer)
    assert r.passes and r.criterion_id == "G1-revenue"
    c = rt.load_rubric(w.db, w.co.id)[0].criteria[0]
    assert not cal.is_calibrated(w.db, w.co.id, c)  # nothing saved
    cal.run(w.db, w.co.id, SAMPLES, scorer, save=True)
    w.db.commit()
    assert cal.is_calibrated(w.db, w.co.id, c)


def test_run_records_a_failure_too_and_refuses_unknown_things(world):  # noqa: F811
    w = world
    bad = ByText(lambda t: 0.5)
    r = cal.run(w.db, w.co.id, SAMPLES, bad, save=True)
    assert not r.passes
    c = rt.load_rubric(w.db, w.co.id)[0].criteria[0]
    assert not cal.is_calibrated(w.db, w.co.id, c)
    with pytest.raises(cal.CalibrationError, match="no criterion"):
        cal.run(w.db, w.co.id, SAMPLES.replace("G1-revenue", "NOPE"), bad)
    with pytest.raises(cal.CalibrationError, match="no stored rubric"):
        cal.run(w.db, "no-such-company", SAMPLES, bad)


# ── the gates in set_rubric ──────────────────────────────────────────────────


def _codes(findings):
    return sorted((f.criterion_id, f.code) for f in findings)


def test_shadow_and_live_criteria_need_a_passing_calibration(world):  # noqa: F811
    w = world
    f = rt.set_rubric(w.db, w.co.id, RUBRIC)  # G1 live, P-purpose shadow, D-draft
    codes = _codes(f)
    assert ("G1-revenue", "not_calibrated") in codes
    assert ("P-purpose", "not_calibrated") in codes
    assert not any(c[0] == "D-draft" for c in codes), "a draft is never gated"


def test_a_calibrated_shadow_criterion_is_accepted(world):  # noqa: F811
    w = world
    shadow_only = RUBRIC.replace("    status: live", "    status: shadow")
    rubric = rb.parse_rubric(shadow_only)
    for c in rubric.criteria:
        cal.record(w.db, w.co.id, _report(c))
    w.db.commit()
    assert rt.set_rubric(w.db, w.co.id, shadow_only) == []


def test_live_also_needs_a_finished_shadow_period(world):  # noqa: F811
    w = world
    rubric = rb.parse_rubric(RUBRIC)
    for c in rubric.criteria:
        cal.record(w.db, w.co.id, _report(c))
    w.db.commit()
    g1 = rubric.criteria[0]

    def shadow_rating(days_ago):
        w.db.add(
            models.WorkRating(
                company_id=w.co.id,
                personnel_id=w.ayse.id,
                day="2026-01-01",
                run_id=f"s{days_ago}",
                criterion_id=g1.id,
                criterion_hash=rb.criterion_hash(g1),
                rubric_version="v",
                criterion_status="shadow",
                verdict="met",
                created_at=datetime.utcnow() - timedelta(days=days_ago),
            )
        )
        w.db.commit()

    assert ("G1-revenue", "shadow_period_not_over") in _codes(
        rt.set_rubric(w.db, w.co.id, RUBRIC)
    )
    shadow_rating(5)  # started, but only 5 days ago
    assert ("G1-revenue", "shadow_period_not_over") in _codes(
        rt.set_rubric(w.db, w.co.id, RUBRIC)
    )
    shadow_rating(rt.SHADOW_DAYS + 1)
    assert rt.set_rubric(w.db, w.co.id, RUBRIC) == []


def test_shadow_time_of_another_wording_does_not_count(world):  # noqa: F811
    w = world
    rubric = rb.parse_rubric(RUBRIC)
    for c in rubric.criteria:
        cal.record(w.db, w.co.id, _report(c))
    g1 = rubric.criteria[0]
    w.db.add(
        models.WorkRating(
            company_id=w.co.id,
            personnel_id=w.ayse.id,
            day="2026-01-01",
            run_id="old",
            criterion_id=g1.id,
            criterion_hash="an-older-wording",
            rubric_version="v",
            criterion_status="shadow",
            verdict="met",
            created_at=datetime.utcnow() - timedelta(days=60),
        )
    )
    w.db.commit()
    assert ("G1-revenue", "shadow_period_not_over") in _codes(
        rt.set_rubric(w.db, w.co.id, RUBRIC)
    )


def test_rewording_a_calibrated_criterion_sends_it_back_to_calibration(world):  # noqa: F811
    w = world
    shadow_only = RUBRIC.replace("    status: live", "    status: shadow")
    for c in rb.parse_rubric(shadow_only).criteria:
        cal.record(w.db, w.co.id, _report(c))
    w.db.commit()
    reworded = shadow_only.replace(
        "advance recurring revenue", "grow recurring revenue"
    )
    assert ("G1-revenue", "not_calibrated") in _codes(
        rt.set_rubric(w.db, w.co.id, reworded)
    )


def test_a_refused_rubric_is_not_stored_and_the_gates_can_be_bypassed_explicitly(world):  # noqa: F811
    w = world
    key = f"work_review.rubric:{w.co.id}"
    before = wr._get(w.db, key)
    changed = RUBRIC.replace("Does this work advance", "Does this work help")
    assert rt.set_rubric(w.db, w.co.id, changed)
    assert wr._get(w.db, key) == before
    assert rt.set_rubric(w.db, w.co.id, changed, gates=False) == []
    assert wr._get(w.db, key) == changed


def test_retired_criteria_are_never_gated(world):  # noqa: F811
    retired = RUBRIC.replace("status: live", "status: retired").replace(
        "status: shadow", "status: retired"
    )
    assert rt.set_rubric(world.db, world.co.id, retired) == []


# ── the command-line tool ────────────────────────────────────────────────────


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "calibrate_rubric.py"
    spec = importlib.util.spec_from_file_location("calibrate_rubric", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_exit_codes_output_and_saving(world, monkeypatch, tmp_path, capsys):  # noqa: F811
    w = world
    mod = _script()
    f = tmp_path / "samples.yaml"
    f.write_text(SAMPLES)
    args = ["--company", w.co.id, "--samples", str(f)]

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert mod.main(args) == 2  # no key

    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setattr(mod, "get_rater", lambda: ByText(by_label()))
    assert mod.main(args + ["--save"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["passes"] is True and "w-met-0" not in out
    w.db.expire_all()
    assert cal.is_calibrated(
        w.db, w.co.id, rt.load_rubric(w.db, w.co.id)[0].criteria[0]
    )

    monkeypatch.setattr(mod, "get_rater", lambda: ByText(lambda t: 0.5))
    assert mod.main(args) == 1  # calibration failed

    assert (
        mod.main(["--company", w.co.id, "--samples", str(tmp_path / "missing.yaml")])
        == 2
    )
    f.write_text("criterion: NOPE\nexamples: []")
    assert mod.main(args) == 2
