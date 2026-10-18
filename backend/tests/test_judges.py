"""Judges (ADR-0023 stage 2): verdicts, abstention, the Wilson interval, the summary API."""

from dataclasses import dataclass

from services.judges import (
    TextCriterion,
    judge_run,
    judge_text,
    success_interval,
    verdict_from_p,
)
from services.run_diagnosis import Diagnosis, Finding


def _crit(i):
    return TextCriterion(id=i, question=f"q {i}?")


def test_probability_bands_and_abstention():
    assert verdict_from_p("c", 0.95).value == "yes"
    assert verdict_from_p("c", 0.05).value == "no"
    assert verdict_from_p("c", 0.5).value == "unclear"
    assert verdict_from_p("c", None).value == "unclear"
    assert verdict_from_p("c", 1.7).value == "unclear"  # out of range is not trusted


@dataclass
class _Result:
    p_yes: dict


class _Rater:
    def __init__(self, p):
        self.p, self.seen = p, None

    def rate(self, text, criteria):
        self.seen = text
        return None if self.p is None else _Result(self.p)


def test_text_judge_redacts_before_asking_and_abstains_on_failure():
    r = _Rater({"a": 0.9, "b": 0.5})
    out = judge_text(
        r,
        "mail me at ceo@example.com key sk-abcdefghijklmnopqrstuvwxyz",
        [_crit("a"), _crit("b")],
    )
    assert [v.value for v in out] == ["yes", "unclear"]
    assert "ceo@example.com" not in r.seen and "sk-abcdef" not in r.seen
    # no model / no answer / no text: abstain, never a pass
    for rater, text in ((None, "x"), (_Rater(None), "x"), (_Rater({"a": 1}), "  ")):
        assert [v.value for v in judge_text(rater, text, [_crit("a")])] == ["unclear"]


def _d(*findings, events=3):
    return Diagnosis(run_id="r", findings=list(findings), events_seen=events)


def test_run_judges_follow_the_diagnosis():
    ok = {v.criterion_id: v.value for v in judge_run(_d())}
    assert ok == {"answered": "yes", "no_tool_error": "yes", "no_policy_block": "yes"}
    bad = {
        v.criterion_id: v.value
        for v in judge_run(
            _d(
                Finding("model", "transport_failure", "high", "x"),
                Finding("tool", "tool_error", "medium", "x"),
                Finding("policy", "deny_decision", "low", "x"),
            )
        )
    }
    assert bad == {"answered": "no", "no_tool_error": "no", "no_policy_block": "no"}
    assert {v.value for v in judge_run(_d(events=0))} == {"unclear"}
    hung_up = {
        v.criterion_id: v.value
        for v in judge_run(_d(Finding("model", "client_closed", "info", "x")))
    }
    assert hung_up["answered"] == "unclear"


def test_wilson_interval_is_wide_for_few_runs():
    assert success_interval(0, 0)["share"] is None
    few = success_interval(3, 3)
    many = success_interval(300, 300)
    assert few["share"] == many["share"] == 1.0
    assert few["low"] < 0.5 < many["low"]  # three clean runs prove little
    mid = success_interval(5, 10)
    assert mid["low"] < 0.5 < mid["high"]


def test_summary_endpoint_counts_verdicts_and_labels_suspects(auth_client, db_session):
    import json

    from models import RunDiagnosis
    from tests.conftest import make_agent_config, make_personnel

    co = auth_client._test_company
    agent = make_personnel(db_session, co.id, name="J", slug="j", type="agent")
    make_agent_config(db_session, agent.id)
    for i, (suspect, findings) in enumerate(
        [
            (None, []),
            (
                "model",
                [
                    {
                        "layer": "model",
                        "kind": "transport_failure",
                        "severity": "high",
                        "detail": "x",
                        "evidence": None,
                    }
                ],
            ),
        ]
    ):
        db_session.add(
            RunDiagnosis(
                company_id=co.id,
                persona_id=agent.id,
                run_id=f"r{i}",
                suspect_layer=suspect,
                scores_json="{}",
                findings_json=json.dumps(findings),
                events_seen=2,
                ignored_client_claims=0,
                invalid_events=0,
                truncated=False,
                diagnoser_version=1,
            )
        )
    db_session.commit()
    r = auth_client.get(f"/eval/personas/{agent.id}/summary")
    assert r.status_code == 200
    d = r.json()
    assert d["runs"] == 2
    assert (
        d["criteria"]["answered"]["yes"] == 1 and d["criteria"]["answered"]["no"] == 1
    )
    assert d["suspect_counts"] == {"model": 1}
    assert "hypotheses" in d["note"]


def test_summary_is_not_visible_to_outsiders(auth_client, db_session):
    from services.auth import create_access_token
    from tests.conftest import make_agent_config, make_personnel, make_user

    co = auth_client._test_company
    agent = make_personnel(db_session, co.id, name="K", slug="k", type="agent")
    make_agent_config(db_session, agent.id)
    outsider = make_user(db_session, email="x@y.com", name="X")
    db_session.commit()
    h = {"Authorization": f"Bearer {create_access_token(outsider.id)}"}
    assert (
        auth_client.get(f"/eval/personas/{agent.id}/summary", headers=h).status_code
        == 404
    )
