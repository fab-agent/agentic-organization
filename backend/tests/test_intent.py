"""
Intent breakdown with TypeSafe Jev (ADR-0020), using the real `typesafe-sdk` over a
fake HTTP transport — no network. The first test pins the SDK's wire format to the
request/response example TypeSafe documented.
"""

import json
import logging
import sys

import httpx2
import pytest
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

import models
from services import intent
from services.context_assembly import assemble
from services.intent import (
    ALL_OPTIONAL,
    Intent,
    JevClassifier,
    sections_to_skip,
    worth_it,
)
from tests.conftest import make_company, make_personnel

TICKET = (
    "Hi, I've been trying to connect my Stripe account for 3 days and the "
    "integration keeps failing. I'm losing sales. Please help ASAP."
)

# The example from TypeSafe's documentation.
DOC_REQUEST = {
    "state": TICKET,
    "model": "jev-latest",
    "questions": {
        "department": {
            "type": "choice",
            "instructions": "Which team should handle this",
            "criteria": {
                "billing": "Payment or subscription issues",
                "technical": "Bugs or integration problems",
                "sales": "Pricing or account questions",
            },
        },
        "frustration": {
            "type": "score",
            "instructions": "How frustrated the customer appears",
            "criteria": [
                "Calm, just stating facts",
                "Frustrated but civil",
                "Very angry, strong language",
            ],
        },
        "is_urgent": {
            "type": "noul",
            "instructions": "The message conveys urgency or time-sensitivity",
        },
    },
}
DOC_RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "department": {
            "type": "choice",
            "choice": "technical",
            "confidence": 0.78,
            "probabilities": {"technical": 0.85, "sales": 0.0, "billing": 0.15},
        },
        "frustration": {
            "type": "score",
            "score": 1.0,
            "confidence": 1.0,
            "legend": {
                "0": "Calm, just stating facts",
                "1": "Frustrated but civil",
                "2": "Very angry, strong language",
            },
            "probabilities": {"0": 0.0, "1": 1.0, "2": 0.0},
        },
        "is_urgent": {"type": "noul", "noul": 1.0},
    },
    "usage": {"input_tokens": 392, "output_tokens": 65},
}


class Fake:
    """Records requests and answers with whatever `respond` returns."""

    def __init__(self, respond):
        self.respond = respond
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.respond(request)

    def body(self, i=-1):
        return json.loads(self.requests[i].content)


def client_for(fake: Fake) -> TypeSafeClient:
    return TypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(fake))


def ok(payload):
    return lambda request: httpx2.Response(200, json=payload)


def our_answers(**over):
    a = {
        "task": {
            "type": "choice",
            "choice": "analysis",
            "confidence": 0.9,
            "probabilities": {"analysis": 0.9},
        },
        "needs_company_knowledge": {"type": "noul", "noul": 0.9},
        "sensitivity": {
            "type": "choice",
            "choice": "financial",
            "confidence": 0.8,
            "probabilities": {"financial": 0.8},
        },
    }
    a.update(over)
    return {
        "model": "jev-1.13.0",
        "answers": a,
        "usage": {"input_tokens": 400, "output_tokens": 60},
    }


# ── the documented wire format ────────────────────────────────────────────────


def test_sdk_request_matches_the_documented_example_and_parses_its_response():
    fake = Fake(ok(DOC_RESPONSE))
    resp = client_for(fake).system_one(
        state=TICKET,
        questions={
            "department": Choice(
                instructions="Which team should handle this",
                criteria={
                    "billing": "Payment or subscription issues",
                    "technical": "Bugs or integration problems",
                    "sales": "Pricing or account questions",
                },
            ),
            "frustration": Score(
                instructions="How frustrated the customer appears",
                criteria=[
                    "Calm, just stating facts",
                    "Frustrated but civil",
                    "Very angry, strong language",
                ],
            ),
            "is_urgent": Noul(
                instructions="The message conveys urgency or time-sensitivity"
            ),
        },
    )
    (req,) = fake.requests
    assert req.url.path == "/v1/systemone" and req.method == "POST"
    assert req.headers["authorization"] == "Bearer test-key"
    assert fake.body() == DOC_REQUEST

    assert resp.answers["department"].choice == "technical"
    assert resp.answers["department"].confidence == 0.78
    assert resp.answers["frustration"].score == 1.0
    assert resp.answers["is_urgent"].noul == 1.0
    assert (resp.usage.input_tokens, resp.usage.output_tokens) == (392, 65)
    assert resp.model == "jev-1.13.0"


# ── our classifier ────────────────────────────────────────────────────────────


def test_classifier_sends_our_question_set_and_parses_the_answers():
    fake = Fake(ok(our_answers()))
    got = JevClassifier(client=client_for(fake)).classify(TICKET)
    body = fake.body()
    assert body["state"] == TICKET
    assert set(body["questions"]) == {"task", "needs_company_knowledge", "sensitivity"}
    assert body["questions"]["task"]["type"] == "choice"
    assert body["questions"]["needs_company_knowledge"]["type"] == "noul"
    assert set(body["questions"]["task"]["criteria"]) == set(intent.TASKS)

    assert got == Intent(
        task="analysis",
        task_confidence=0.9,
        needs_company_knowledge=0.9,
        sensitivity="financial",
        sensitivity_confidence=0.8,
        model="jev-1.13.0",
        input_tokens=400,
        output_tokens=60,
    )
    assert got.tags() == {
        "task": "analysis",
        "sensitivity": "financial",
        "needs_company_knowledge": 0.9,
    }


def test_domain_question_is_built_from_the_companys_departments():
    fake = Fake(
        ok(
            our_answers(
                domain={
                    "type": "choice",
                    "choice": "finance",
                    "confidence": 0.8,
                    "probabilities": {"finance": 0.8},
                }
            )
        )
    )
    got = JevClassifier(client=client_for(fake)).classify(
        "close the books",
        domains={"finance": "Accounting and treasury", "sales": "Revenue"},
    )
    q = fake.body()["questions"]["domain"]
    assert q["criteria"] == {"finance": "Accounting and treasury", "sales": "Revenue"}
    assert got.domain == "finance" and got.tags()["domain"] == "finance"


def test_domains_are_capped():
    fake = Fake(ok(our_answers()))
    JevClassifier(client=client_for(fake)).classify(
        "x", domains={f"d{i}": "desc" for i in range(40)}
    )
    assert len(fake.body()["questions"]["domain"]["criteria"]) == intent.MAX_DOMAINS


def test_low_confidence_choices_become_unknown():
    low = {
        "type": "choice",
        "choice": "action",
        "confidence": 0.4,
        "probabilities": {"action": 0.4},
    }
    got = JevClassifier(client=client_for(Fake(ok(our_answers(task=low))))).classify(
        "x"
    )
    assert got.task is None and got.task_confidence == 0.4
    assert "task" not in got.tags()


def test_only_a_capped_message_is_sent():
    fake = Fake(ok(our_answers()))
    JevClassifier(client=client_for(fake)).classify("é" * 5000)
    assert len(fake.body()["state"]) == intent.MAX_MESSAGE_CHARS


def test_empty_message_makes_no_request():
    fake = Fake(ok(our_answers()))
    assert JevClassifier(client=client_for(fake)).classify("   ") is None
    assert JevClassifier(client=client_for(fake)).classify("") is None
    assert fake.requests == []


def test_missing_answers_are_tolerated():
    got = JevClassifier(
        client=client_for(Fake(ok({"model": "m", "answers": {}, "usage": {}})))
    ).classify("x")
    assert got == Intent(model="m")
    assert sections_to_skip(got) == frozenset()


# ── failing open ──────────────────────────────────────────────────────────────


def _err(status):
    return lambda request: httpx2.Response(status, json={"error": "nope"})


def _raise(exc):
    def h(request):
        raise exc(request=request, message="boom") if exc is not None else None

    return h


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 500, 502, 503])
def test_http_errors_give_none_and_are_not_retried(status):
    fake = Fake(_err(status))
    assert JevClassifier(client=client_for(fake)).classify("x") is None
    assert len(fake.requests) == 1, "a slow / failing classifier must not be retried"


@pytest.mark.parametrize(
    "exc", [httpx2.ConnectError, httpx2.ReadTimeout, httpx2.ConnectTimeout]
)
def test_network_errors_give_none_and_are_not_retried(exc):
    fake = Fake(_raise(exc))
    assert JevClassifier(client=client_for(fake)).classify("x") is None
    assert len(fake.requests) == 1


def test_garbage_and_invalid_responses_give_none():
    for h in (
        lambda r: httpx2.Response(200, content=b"<html>not json</html>"),
        lambda r: httpx2.Response(200, json={"unexpected": True}),
        lambda r: httpx2.Response(
            200,
            json={"model": "m", "answers": {"task": {"type": "choice"}}, "usage": {}},
        ),
    ):
        assert JevClassifier(client=client_for(Fake(h))).classify("x") is None


def test_failures_never_log_the_message_or_the_key(caplog):
    secret = "SECRET-CUSTOMER-TEXT"
    with caplog.at_level(logging.DEBUG):
        JevClassifier(client=client_for(Fake(_err(500)))).classify(secret)
        JevClassifier(client=client_for(Fake(_raise(httpx2.ConnectError)))).classify(
            secret
        )
    assert any(r.msg == "intent_classify_failed" for r in caplog.records)
    blob = " ".join(
        f"{r.getMessage()} {getattr(r, 'extra', '')}" for r in caplog.records
    )
    assert secret not in blob and "test-key" not in blob


def test_the_timeout_is_short_and_configurable(monkeypatch):
    fake = Fake(ok(our_answers()))
    JevClassifier(client=client_for(fake)).classify("x")
    assert fake.requests[0].extensions["timeout"]["read"] == 1.5
    monkeypatch.setenv("INTENT_TIMEOUT_SECONDS", "0.7")
    fake2 = Fake(ok(our_answers()))
    JevClassifier(client=client_for(fake2)).classify("x")
    assert fake2.requests[0].extensions["timeout"]["read"] == 0.7
    monkeypatch.setenv("INTENT_TIMEOUT_SECONDS", "banana")
    assert intent._timeout() == 1.5


# ── what an intent may change ─────────────────────────────────────────────────


def test_chitchat_skips_every_optional_section_and_never_the_required_ones():
    skip = sections_to_skip(Intent(task="chitchat"))
    assert skip == ALL_OPTIONAL
    assert not skip & {"identity", "rules", "closing"}


def test_low_knowledge_need_skips_only_retrieved_knowledge():
    assert sections_to_skip(Intent(task="analysis", needs_company_knowledge=0.1)) == {
        "knowledge"
    }
    assert (
        sections_to_skip(Intent(task="analysis", needs_company_knowledge=0.25))
        == frozenset()
    )
    assert (
        sections_to_skip(Intent(task="analysis", needs_company_knowledge=0.9))
        == frozenset()
    )
    assert (
        sections_to_skip(Intent(task="analysis", needs_company_knowledge=None))
        == frozenset()
    )


def test_no_intent_means_the_full_prompt():
    assert sections_to_skip(None) == frozenset()


def test_an_intent_can_only_narrow_never_add(client, db_session):
    co = make_company(db_session)
    co.metadata_json = json.dumps({"mission": "M"})
    db_session.add(co)
    p = make_personnel(db_session, co.id, name="Ada", slug="ada", title="A")
    db_session.commit()
    kw = dict(memories=["m"], company_id=co.id)
    full = {s.name for s in assemble(p, None, [], ["P"], **kw).sections}
    chit = {
        s.name
        for s in assemble(
            p, None, [], ["P"], skip=sections_to_skip(Intent(task="chitchat")), **kw
        ).sections
    }
    assert chit < full and {"identity", "rules", "closing"} <= chit
    unknown = {
        s.name
        for s in assemble(
            p, None, [], ["P"], skip=sections_to_skip(None), **kw
        ).sections
    }
    assert unknown == full


def test_worth_it_gate(monkeypatch):
    monkeypatch.delenv("INTENT_MIN_PROMPT_TOKENS", raising=False)
    assert worth_it(800) and not worth_it(799)
    monkeypatch.setenv("INTENT_MIN_PROMPT_TOKENS", "100")
    assert worth_it(100) and not worth_it(99)
    monkeypatch.setenv("INTENT_MIN_PROMPT_TOKENS", "banana")
    assert worth_it(800) and not worth_it(799)


# ── opt-in gating ─────────────────────────────────────────────────────────────


def test_classifier_is_off_by_default(client, db_session, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert intent.get_classifier() is None
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    assert intent.get_classifier() is None  # key alone is not enough: needs opt-in


def test_classifier_needs_key_and_opt_in(client, db_session, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    db_session.add(models.AppConfig(key="intent.enabled", value="true"))
    db_session.commit()
    assert isinstance(intent.get_classifier(), JevClassifier)
    monkeypatch.delenv("TYPESAFE_API_KEY")
    assert intent.get_classifier() is None


def test_classifier_is_none_when_the_sdk_is_missing(client, db_session, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    db_session.add(models.AppConfig(key="intent.enabled", value="on"))
    db_session.commit()
    monkeypatch.setitem(sys.modules, "typesafe_sdk", None)  # import raises
    assert intent.get_classifier() is None
