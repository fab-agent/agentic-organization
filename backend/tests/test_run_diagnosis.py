"""Run diagnosis (ADR-0023 stage 1): findings per layer from audit-shaped events."""

from services.run_diagnosis import diagnose


def ev(action, seq, target=None, **payload):
    return {
        "action": action,
        "chain_key": "co1",
        "seq": seq,
        "target": target,
        "payload": payload,
    }


def kinds(d):
    return {(f.layer, f.kind) for f in d.findings}


def test_clean_run_has_no_findings_and_no_suspect():
    d = diagnose(
        [
            ev("context_served", 1, prompt={"dropped": [], "over_budget": False}),
            ev("gateway_call", 2, "m", upstream_status=200, tokens_out=40),
            ev("tool_event", 3, "read", phase="after", error=None),
        ],
        run_id="r1",
    )
    assert d.findings == [] and d.suspect_layer is None and d.events_seen == 3


def test_no_events_is_reported_as_unknown_not_healthy():
    d = diagnose([])
    assert d.events_seen == 0 and d.suspect_layer is None


def test_upstream_error_points_at_model():
    d = diagnose([ev("gateway_call", 1, "gpt", upstream_status=503, tokens_out=0)])
    assert ("model", "upstream_error") in kinds(d)
    assert d.suspect_layer == "model"
    assert d.findings[0].evidence == ("co1", 1)


def test_empty_output_with_ok_status_is_a_model_finding():
    d = diagnose([ev("gateway_call", 1, "gpt", upstream_status=200, tokens_out=0)])
    assert kinds(d) == {("model", "empty_output")}


def test_dropped_sections_point_at_prompt():
    d = diagnose(
        [
            ev(
                "context_served",
                1,
                prompt={
                    "dropped": [{"name": "memory", "tokens": 900}],
                    "over_budget": False,
                },
            )
        ]
    )
    assert kinds(d) == {("prompt", "sections_dropped")}
    assert "memory" in d.findings[0].detail and "900" in d.findings[0].detail
    assert d.suspect_layer == "prompt"


def test_enforced_deny_is_a_high_policy_finding_with_rule():
    d = diagnose(
        [
            ev(
                "policy_decision",
                1,
                "bash",
                effect="deny",
                matched_rule="no-rm",
                enforced=True,
                fail_closed=False,
            )
        ]
    )
    f = d.findings[0]
    assert (f.layer, f.kind, f.severity) == ("policy", "deny_decision", "high")
    assert "no-rm" in f.detail and d.suspect_layer == "policy"


def test_dry_run_deny_counts_less_than_enforced():
    enforced = diagnose([ev("policy_decision", 1, "t", effect="deny", enforced=True)])
    dry = diagnose([ev("policy_decision", 1, "t", effect="deny", enforced=False)])
    assert dry.scores["policy"] < enforced.scores["policy"]


def test_allow_decisions_are_not_findings():
    assert diagnose([ev("policy_decision", 1, "t", effect="allow")]).findings == []


def test_repeated_tool_failure_outweighs_a_single_one():
    one = diagnose([ev("tool_event", 1, "sql", error="boom")])
    three = diagnose([ev("tool_event", i, "sql", error="boom") for i in (1, 2, 3)])
    assert ("tool", "repeated_failure") in kinds(three)
    assert ("tool", "repeated_failure") not in kinds(one)
    assert three.scores["tool"] > one.scores["tool"]


def test_tied_layers_give_no_single_suspect():
    d = diagnose(
        [
            ev("gateway_call", 1, "m", upstream_status=404),  # model, medium = 2
            ev("tool_event", 2, "x", error="e"),  # tool, medium = 2
        ]
    )
    assert d.scores["model"] == d.scores["tool"] == 2
    assert d.suspect_layer is None


def test_output_never_contains_message_text():
    d = diagnose(
        [
            ev(
                "tool_event",
                1,
                "read",
                error="x",
                args_preview="SECRET-PASSWORD",
                result_preview="SECRET-BODY",
            )
        ]
    )
    assert "SECRET" not in str(d.as_dict())


def test_malformed_payload_does_not_crash():
    d = diagnose([{"action": "gateway_call", "payload": None}, {"action": "x"}])
    assert d.findings == []
