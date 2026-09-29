"""The trial harness itself (scripts/intent_trial.py), against a fake transport."""

import httpx2

from scripts import intent_trial as trial
from services.intent import Intent, JevClassifier
from tests.test_intent import Fake, client_for, our_answers


def _choice(name, conf=0.9):
    return {
        "type": "choice",
        "choice": name,
        "confidence": conf,
        "probabilities": {name: conf},
    }


def test_percentile():
    assert trial.percentile([], 50) is None
    assert trial.percentile([5], 95) == 5
    assert trial.percentile([1, 2, 3, 4], 50) == 2
    assert trial.percentile([1, 2, 3, 4], 95) == 4


def test_the_case_set_is_balanced_and_bilingual():
    langs = {c.lang for c in trial.CASES}
    tasks = {c.task for c in trial.CASES}
    assert langs == {"en", "tr"} and tasks == {
        "chitchat",
        "lookup",
        "analysis",
        "document",
        "action",
    }
    for lang in langs:
        assert {c.task for c in trial.CASES if c.lang == lang} == tasks
    assert len({c.text for c in trial.CASES}) == len(trial.CASES)


def test_the_harness_runs_end_to_end_against_a_fake_jev():
    answers = lambda r: httpx2.Response(  # noqa: E731
        200,
        json=our_answers(
            task=_choice("analysis"),
            sensitivity=_choice("internal"),
            needs_company_knowledge={"type": "noul", "noul": 0.8},
        ),
    )
    fake = Fake(answers)
    records = trial.run_jev(JevClassifier(client=client_for(fake)), repeat=2)
    assert len(records) == 2 * len(trial.CASES) == len(fake.requests)
    s = trial.summarize_jev(records)
    assert s["requests"] == len(records) and s["failed_open"] == 0
    assert s["input_tokens"]["min"] == 400
    assert s["task"]["answered"] == len(records)
    assert s["latency_seconds"]["p95"] >= s["latency_seconds"]["p50"] >= 0


def _rec(task, intent, needs=True):
    case = trial.Case("x", "en", task, "internal", needs)
    return trial.Record(case, intent, 0.1)


def test_summary_counts_the_harmful_direction_separately():
    recs = [
        _rec("chitchat", Intent(task="chitchat")),  # correctly trimmed
        _rec(
            "analysis", Intent(task="chitchat")
        ),  # WRONG: work trimmed like small talk
        _rec(
            "analysis", Intent(task="analysis", needs_company_knowledge=0.05)
        ),  # knowledge skipped
        _rec("analysis", Intent(task="analysis", needs_company_knowledge=0.9)),
        _rec("lookup", None),  # failed open
    ]
    s = trial.summarize_jev(recs)
    assert s["failed_open"] == 1
    assert s["chitchat_recognised_and_trimmed"] == "1/1"
    assert s["work_wrongly_trimmed_like_chitchat"] == "1/3"
    assert (
        s["needed_knowledge_but_knowledge_skipped"] == "2/3"
    )  # chitchat-trim also drops knowledge
    assert s["task"]["correct_when_answered"] == 3 and s["task"]["answered"] == 4


def test_summary_of_an_all_failed_run_does_not_crash():
    s = trial.summarize_jev([_rec("lookup", None), _rec("action", None)])
    assert s["failed_open"] == 2 and s["input_tokens"]["min"] is None
    assert s["task"]["accuracy_when_answered"] is None


def test_noul_separation_is_reported():
    recs = [
        _rec("lookup", Intent(needs_company_knowledge=0.9), needs=True),
        _rec("lookup", Intent(needs_company_knowledge=0.7), needs=True),
        _rec("analysis", Intent(needs_company_knowledge=0.1), needs=False),
    ]
    s = trial.summarize_jev(recs)
    assert s["noul_mean_when_knowledge_needed"] == 0.8
    assert s["noul_mean_when_not_needed"] == 0.1


def test_estimate_calibration_ratio():
    from services.context_assembly import estimate_tokens

    text = "a" * 400
    est = estimate_tokens(text)
    out = trial.calibrate_estimates(
        [("en", text, est * 2), ("en", text, est * 2), ("tr", text, est)]
    )
    assert (
        out["en"]["actual_over_estimate_mean"] == 2.0
        and out["tr"]["actual_over_estimate_mean"] == 1.0
    )
    assert trial.calibrate_estimates([("en", "", 5)]) == {}


def test_main_refuses_to_run_without_a_key(monkeypatch, capsys):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert trial.main([]) == 2
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err
