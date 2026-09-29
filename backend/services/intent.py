"""Intent breakdown of a user request with TypeSafe Jev (ADR-0020).

Jev answers typed questions (choice / score / noul) about a text with calibrated
probabilities. Here it turns "what is this request?" into a small `Intent` record
used for two things: deciding which prompt sections to leave out
(`sections_to_skip`) and tagging the work for review (`Intent.tags`).

Rules this module holds to:

* **Never a security control.** An intent can only *narrow what the prompt shows*,
  never widen what is allowed (policies are enforced at tool-call time, ADR-0005).
  A wrong or missing answer costs helpfulness, not safety.
* **Fail open, fast.** A short timeout, no retries, and any failure returns `None`,
  which means "assemble the normal, complete prompt".
* **Send only the user's message** (capped) plus the question set. Jev bills per
  input token, and the questions alone are a few hundred tokens, so it must not be
  called for prompts too small to gain from it (`worth_it`).
* **No text in logs.** Errors log the exception type only.

The TypeSafe SDK is imported lazily: the app runs without it and without
`TYPESAFE_API_KEY`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger("app")


class _DropBodies(logging.Filter):
    """The SDK logs full request/response bodies at DEBUG — that is the user's
    message. Drop those records; keep the rest of the SDK's logging."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "body=" not in record.getMessage()


def quiet_sdk_logs() -> None:
    """Idempotent: make sure the TypeSafe SDK never logs message text."""
    sdk = logging.getLogger("typesafe_sdk")
    if not any(isinstance(f, _DropBodies) for f in sdk.filters):
        sdk.addFilter(_DropBodies())


MAX_MESSAGE_CHARS = 2000
MAX_DOMAINS = 12
MIN_CONFIDENCE = 0.6  # choice answers below this are treated as "unknown"
LOW_KNOWLEDGE_NEED = 0.15  # below this, skip retrieved knowledge (ADR-0020 trial)

# Per-turn and stable sections an intent may leave out (never the required ones).
ALL_OPTIONAL = frozenset({"knowledge", "memory", "department", "job", "company"})

TASKS = {
    "chitchat": "A greeting, thanks or small talk with no work to do",
    "lookup": "Asks for a fact or status from company data or past work",
    "analysis": "Asks to analyse, compare or summarise data or documents",
    "document": "Asks to produce a document, spreadsheet or presentation",
    "action": "Asks to send, change, spend or delete something",
}
SENSITIVITY = {
    "public": "Nothing confidential",
    "internal": "Internal company information",
    "personal": "Personal data about a person",
    "financial": "Financial figures, prices, contracts or payments",
}


@dataclass(frozen=True)
class Intent:
    task: str | None = None
    task_confidence: float = 0.0
    needs_company_knowledge: float | None = None  # probability, 0..1
    sensitivity: str | None = None
    sensitivity_confidence: float = 0.0
    domain: str | None = None  # a department slug
    domain_confidence: float = 0.0
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def tags(self) -> dict[str, Any]:
        """Structured tags for the work-review pipeline (ADR-0019 §6)."""
        out: dict[str, Any] = {}
        if self.task:
            out["task"] = self.task
        if self.sensitivity:
            out["sensitivity"] = self.sensitivity
        if self.domain:
            out["domain"] = self.domain
        if self.needs_company_knowledge is not None:
            out["needs_company_knowledge"] = round(self.needs_company_knowledge, 2)
        return out


def sections_to_skip(intent: Intent | None) -> frozenset[str]:
    """Prompt sections this intent lets us leave out. `None` (no / failed
    classification) leaves out nothing."""
    if intent is None:
        return frozenset()
    if intent.task == "chitchat":
        return ALL_OPTIONAL
    need = intent.needs_company_knowledge
    if need is not None and need < LOW_KNOWLEDGE_NEED:
        return frozenset({"knowledge"})
    return frozenset()


def worth_it(prompt_tokens: int) -> bool:
    """Only classify when the prompt is big enough for savings to beat the fixed
    cost of the questions (`INTENT_MIN_PROMPT_TOKENS`, default 1500: about three
    times the ~520 input tokens Jev measured per call in the ADR-0020 trial)."""
    try:
        floor = int(os.getenv("INTENT_MIN_PROMPT_TOKENS", "1500"))
    except ValueError:
        floor = 1500
    return prompt_tokens >= floor


class IntentClassifier(Protocol):
    def classify(
        self, message: str, *, domains: dict[str, str] | None = None
    ) -> Intent | None: ...


def _timeout() -> float:
    try:
        return max(0.1, float(os.getenv("INTENT_TIMEOUT_SECONDS", "1.5")))
    except ValueError:
        return 1.5


class JevClassifier:
    """`IntentClassifier` backed by the TypeSafe SDK."""

    def __init__(self, client: Any = None, timeout: float | None = None):
        quiet_sdk_logs()
        self._client = client
        # Exception type of the last failure (None after a success). Type only —
        # used by the trial harness to tell "blocked" from "slow" from "invalid".
        self.last_error: str | None = None
        self._timeout = timeout or _timeout()

    def _get_client(self):
        if self._client is None:
            from typesafe_sdk import TypeSafeClient

            self._client = TypeSafeClient()
        return self._client

    def _questions(self, domains: dict[str, str] | None) -> dict:
        from typesafe_sdk import Choice, Noul

        q: dict[str, Any] = {
            "task": Choice(
                instructions="What kind of request is this",
                criteria=dict(TASKS),
            ),
            "needs_company_knowledge": Noul(
                instructions=(
                    "Answering well needs company documents, policies or past work"
                ),
            ),
            "sensitivity": Choice(
                instructions="How sensitive is the information in this request",
                criteria=dict(SENSITIVITY),
            ),
        }
        if domains:
            q["domain"] = Choice(
                instructions="Which area of the company does this belong to",
                criteria=dict(list(domains.items())[:MAX_DOMAINS]),
            )
        return q

    def classify(
        self, message: str, *, domains: dict[str, str] | None = None
    ) -> Intent | None:
        text = (message or "").strip()[:MAX_MESSAGE_CHARS]
        if not text:
            return None
        quiet_sdk_logs()
        try:
            from typesafe_sdk import RetryPolicy

            resp = self._get_client().system_one(
                state=text,
                questions=self._questions(domains),
                timeout=self._timeout,
                retry=RetryPolicy(max_retries=0, timeout=self._timeout),
            )
            intent = _parse(resp)
            self.last_error = None
            return intent
        except Exception as e:  # noqa: BLE001 - any failure means "no intent"
            self.last_error = type(e).__name__
            # Type only: the message and the API key must never reach the logs.
            logger.warning(
                "intent_classify_failed",
                extra={"extra": {"error": type(e).__name__}},
            )
            return None


def _choice(answers: dict, key: str) -> tuple[str | None, float]:
    a = answers.get(key)
    if a is None or getattr(a, "type", None) != "choice":
        return None, 0.0
    if a.confidence < MIN_CONFIDENCE:
        return None, float(a.confidence)
    return a.choice, float(a.confidence)


def _parse(resp: Any) -> Intent:
    answers = resp.answers
    task, task_c = _choice(answers, "task")
    sens, sens_c = _choice(answers, "sensitivity")
    dom, dom_c = _choice(answers, "domain")
    need = answers.get("needs_company_knowledge")
    need_p = float(need.noul) if need is not None and need.type == "noul" else None
    usage = getattr(resp, "usage", None)
    return Intent(
        task=task,
        task_confidence=task_c,
        needs_company_knowledge=need_p,
        sensitivity=sens,
        sensitivity_confidence=sens_c,
        domain=dom,
        domain_confidence=dom_c,
        model=getattr(resp, "model", None),
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
    )


def get_classifier() -> IntentClassifier | None:
    """The configured classifier, or None (feature off, no key, or no SDK).

    Off unless `TYPESAFE_API_KEY` is set and AppConfig `intent.enabled` is true —
    documents and requests leave the premises with Jev, so it is an explicit,
    per-install opt-in (ADR-0015 / ADR-0016).
    """
    if not os.getenv("TYPESAFE_API_KEY"):
        return None
    try:
        from database import get_session
        from models import AppConfig

        with get_session() as session:
            row = session.get(AppConfig, "intent.enabled")
        if not row or str(row.value).strip().lower() not in ("1", "true", "yes", "on"):
            return None
        import typesafe_sdk  # noqa: F401
    except Exception:  # noqa: BLE001
        return None
    return JevClassifier()
