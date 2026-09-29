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


def test_failures_are_explained_by_type_not_hidden():
    fake = Fake(lambda r: httpx2.Response(500, json={"error": "x"}))
    clf = JevClassifier(client=client_for(fake))
    records = trial.run_jev(clf, cases=trial.CASES[:3])
    assert [r.error for r in records] == ["TypeSafeInternalServerError"] * 3
    s = trial.summarize_jev(records)
    assert s["failed_open"] == 3
    assert s["failure_reasons"] == {"TypeSafeInternalServerError": 3}


def test_a_success_clears_the_last_error():
    calls = iter([500, 200])

    def respond(request):
        if next(calls) == 500:
            return httpx2.Response(500, json={})
        return httpx2.Response(200, json=our_answers())

    clf = JevClassifier(client=client_for(Fake(respond)))
    assert clf.classify("x") is None and clf.last_error == "TypeSafeInternalServerError"
    assert clf.classify("x") is not None and clf.last_error is None


def test_slow_calls_are_counted_against_the_production_budget():
    fast = trial.Record(trial.CASES[0], Intent(task="chitchat"), 0.4)
    slow = trial.Record(trial.CASES[1], Intent(task="chitchat"), 2.5)
    s = trial.summarize_jev([fast, slow], budget=1.5)
    assert s["calls_slower_than_production_budget"] == "1/2 (> 1.5s)"
    assert s["failure_reasons"] == {}


def test_main_stops_with_a_clear_message_when_the_api_is_unreachable(
    monkeypatch, capsys
):
    """The preflight must say why, instead of reporting 20 silent failures."""
    import typesafe_sdk

    monkeypatch.setenv("TYPESAFE_API_KEY", "k")

    class Blocked:
        def __init__(self, **kw):
            pass

        @property
        def models(self):
            raise typesafe_sdk.TypeSafeAPIConnectionError(
                "Connection error: 403 Forbidden"
            )

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", Blocked)
    assert trial.main([]) == 3
    err = capsys.readouterr().err
    assert "TypeSafeAPIConnectionError" in err and "Network access" in err


# ── the knowledge probes ──────────────────────────────────────────────────────


def test_probes_are_balanced_bilingual_and_unambiguous():
    assert {c.lang for c in trial.PROBES} == {"en", "tr"}
    assert len({c.text for c in trial.PROBES}) == len(trial.PROBES)
    assert not {c.text for c in trial.PROBES} & {c.text for c in trial.CASES}
    for lang in ("en", "tr"):
        mine = [c for c in trial.PROBES if c.lang == lang]
        assert (
            sum(c.needs_knowledge for c in mine)
            == sum(not c.needs_knowledge for c in mine)
            == 3
        )
    for c in trial.PROBES:
        quoted = "'" in c.text
        # inline-text tasks carry their text in the message; data questions carry none
        assert quoted is (not c.needs_knowledge), c.text


def _probe(lang, needs, noul):
    case = trial.Case("x", lang, "lookup", "internal", needs)
    return trial.Record(case, Intent(needs_company_knowledge=noul), 0.1)


def test_probe_summary_reports_saving_harm_and_separation_per_language():
    recs = [
        _probe("en", False, 0.05),
        _probe("en", False, 0.09),
        _probe("en", True, 0.6),
        _probe("en", True, 0.8),
        _probe("tr", False, 0.7),
        _probe("tr", False, 0.05),
        _probe("tr", True, 0.1),
        _probe("tr", True, 0.9),
    ]
    s = trial.summarize_probes(recs, threshold=0.15)
    en, tr = s["en"], s["tr"]
    assert en["inline_text_tasks"]["would_skip_knowledge"] == "2/2"
    assert en["needs_company_data"]["wrongly_would_skip_knowledge"] == "0/2"
    assert en["clean_separation"] is True
    assert tr["inline_text_tasks"]["would_skip_knowledge"] == "1/2"
    assert (
        tr["needs_company_data"]["wrongly_would_skip_knowledge"] == "1/2"
    )  # the harmful direction
    assert tr["clean_separation"] is False
    assert tr["needs_company_data"]["mean_noul"] == 0.5


def test_probe_summary_tolerates_missing_answers():
    recs = [
        trial.Record(trial.Case("x", "en", "lookup", "internal", True), None, 0.1),
        _probe("en", False, 0.2),
    ]
    s = trial.summarize_probes(recs)["en"]
    assert s["unanswered"] == 1 and s["needs_company_data"]["n"] == 0
    assert s["clean_separation"] is None


def test_probes_run_through_the_harness_against_a_fake_jev():
    fake = Fake(
        lambda r: httpx2.Response(
            200, json=our_answers(needs_company_knowledge={"type": "noul", "noul": 0.5})
        )
    )
    recs = trial.run_jev(JevClassifier(client=client_for(fake)), cases=trial.PROBES)
    assert len(recs) == len(trial.PROBES) == len(fake.requests)
    assert trial.summarize_probes(recs)["en"]["inline_text_tasks"]["n"] == 3
