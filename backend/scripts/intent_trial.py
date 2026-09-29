#!/usr/bin/env python3
"""Trial of the intent classifier (ADR-0020) against the real TypeSafe Jev API, and
of the token estimator against a real tokenizer.

Run it once the environment can reach the services:

    cd backend
    TYPESAFE_API_KEY=...  python scripts/intent_trial.py [--repeat 3]

Optional, for the token-estimate calibration, any OpenAI-compatible endpoint:

    OPENAI_COMPAT_BASE_URL=https://.../v1 OPENAI_COMPAT_API_KEY=... \\
    OPENAI_COMPAT_MODEL=qwen-turbo  python scripts/intent_trial.py --calibrate

It sends only the synthetic messages below (no company data) and never prints keys.
The report answers the open questions in ADR-0020: latency, the fixed cost of the
questions, how often a choice is confident, whether chit-chat is recognised without
ever mistaking real work for it (the harmful direction), and how the `noul`
probability separates "needs company knowledge" from "does not".
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.context_assembly import estimate_tokens  # noqa: E402
from services.intent import Intent, sections_to_skip  # noqa: E402


@dataclass(frozen=True)
class Case:
    text: str
    lang: str  # "en" | "tr"
    task: str  # expected: chitchat | lookup | analysis | document | action
    sensitivity: str  # expected: public | internal | personal | financial
    needs_knowledge: bool  # expected: does a good answer need company knowledge?


# Synthetic — no real names, customers or figures.
CASES: tuple[Case, ...] = (
    Case("Hi! Thanks, that was helpful.", "en", "chitchat", "public", False),
    Case("Good morning, how are you today?", "en", "chitchat", "public", False),
    Case(
        "What is the status of the Q3 supplier aging report?",
        "en",
        "lookup",
        "financial",
        True,
    ),
    Case(
        "Which of our policies covers travel expenses above 500 euros?",
        "en",
        "lookup",
        "internal",
        True,
    ),
    Case(
        "Compare last six months of sales with the previous three years and flag anomalies.",
        "en",
        "analysis",
        "financial",
        True,
    ),
    Case(
        "Summarise this contract clause about payment terms.",
        "en",
        "analysis",
        "financial",
        False,
    ),
    Case(
        "Prepare a 10 slide deck from the sales analysis results.",
        "en",
        "document",
        "internal",
        True,
    ),
    Case(
        "Write a one page memo announcing the new expense policy.",
        "en",
        "document",
        "internal",
        True,
    ),
    Case(
        "Send the overdue invoice reminder to all customers in the list.",
        "en",
        "action",
        "financial",
        True,
    ),
    Case(
        "Delete the salary column from the shared spreadsheet and email it to HR.",
        "en",
        "action",
        "personal",
        True,
    ),
    Case("Merhaba, günaydın!", "tr", "chitchat", "public", False),
    Case("Teşekkürler, çok işime yaradı.", "tr", "chitchat", "public", False),
    Case(
        "Tedarikçi yaşlandırma raporunun son durumu nedir?",
        "tr",
        "lookup",
        "financial",
        True,
    ),
    Case(
        "Yurt içi seyahat harcamalarını hangi politika düzenliyor?",
        "tr",
        "lookup",
        "internal",
        True,
    ),
    Case(
        "Son altı ayın satışlarını önceki üç yılla karşılaştır ve sapmaları işaretle.",
        "tr",
        "analysis",
        "financial",
        True,
    ),
    Case(
        "Bu sözleşmedeki ödeme koşulları maddesini özetle.",
        "tr",
        "analysis",
        "financial",
        False,
    ),
    Case(
        "Satış analizi sonuçlarından 10 slaytlık bir sunum hazırla.",
        "tr",
        "document",
        "internal",
        True,
    ),
    Case(
        "Yeni harcama politikasını duyuran tek sayfalık bir not yaz.",
        "tr",
        "document",
        "internal",
        True,
    ),
    Case(
        "Listedeki tüm müşterilere gecikmiş fatura hatırlatması gönder.",
        "tr",
        "action",
        "financial",
        True,
    ),
    Case(
        "Ortak tablodan maaş sütununu sil ve İK'ya e-posta ile gönder.",
        "tr",
        "action",
        "personal",
        True,
    ),
)


@dataclass
class Record:
    case: Case
    intent: Intent | None
    seconds: float
    error: str | None = None  # exception type when the call failed


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))
    return ordered[k]


def run_jev(classifier, cases=CASES, repeat: int = 1) -> list[Record]:
    out: list[Record] = []
    for _ in range(repeat):
        for c in cases:
            t = time.perf_counter()
            intent = classifier.classify(c.text)
            out.append(
                Record(
                    c,
                    intent,
                    time.perf_counter() - t,
                    getattr(classifier, "last_error", None) if intent is None else None,
                )
            )
    return out


BUDGET_SECONDS = 1.5  # the production timeout (INTENT_TIMEOUT_SECONDS default)


def summarize_jev(records: list[Record], budget: float = BUDGET_SECONDS) -> dict:
    n = len(records)
    got = [r for r in records if r.intent is not None]
    lat = [r.seconds for r in records]

    def acc(field: str, expected: str) -> dict:
        answered = [r for r in got if getattr(r.intent, field) is not None]
        right = [
            r for r in answered if getattr(r.intent, field) == getattr(r.case, expected)
        ]
        return {
            "answered": len(answered),
            "unknown": len(got) - len(answered),
            "correct_when_answered": len(right),
            "accuracy_when_answered": round(len(right) / len(answered), 3)
            if answered
            else None,
        }

    # The harmful direction: real work treated as chit-chat would strip its context.
    work = [r for r in got if r.case.task != "chitchat"]
    false_skip = [
        r for r in work if sections_to_skip(r.intent) >= {"company", "knowledge"}
    ]
    chat = [r for r in got if r.case.task == "chitchat"]
    chat_skipped = [r for r in chat if sections_to_skip(r.intent)]
    # Knowledge-only skips on work that did need company knowledge.
    knowledge_skip_wrong = [
        r
        for r in work
        if r.case.needs_knowledge and "knowledge" in sections_to_skip(r.intent)
    ]

    def noul_mean(flag: bool):
        v = [
            r.intent.needs_company_knowledge
            for r in got
            if r.case.needs_knowledge is flag
            and r.intent.needs_company_knowledge is not None
        ]
        return round(statistics.mean(v), 3) if v else None

    tokens = [r.intent.input_tokens for r in got if r.intent.input_tokens]
    return {
        "requests": n,
        "failed_open": n - len(got),
        "failure_reasons": dict(
            Counter(r.error or "unknown" for r in records if r.intent is None)
        ),
        # The trial runs with a generous timeout so slow answers are measured, not
        # lost. In production anything slower than the budget would fail open.
        "calls_slower_than_production_budget": (
            f"{sum(1 for r in records if r.seconds > budget)}/{n} (> {budget}s)"
        ),
        "latency_seconds": {
            "p50": round(percentile(lat, 50), 3) if lat else None,
            "p95": round(percentile(lat, 95), 3) if lat else None,
            "max": round(max(lat), 3) if lat else None,
        },
        "input_tokens": {
            "min": min(tokens) if tokens else None,
            "mean": round(statistics.mean(tokens), 1) if tokens else None,
        },
        "task": acc("task", "task"),
        "sensitivity": acc("sensitivity", "sensitivity"),
        "chitchat_recognised_and_trimmed": f"{len(chat_skipped)}/{len(chat)}",
        "work_wrongly_trimmed_like_chitchat": f"{len(false_skip)}/{len(work)}",
        "needed_knowledge_but_knowledge_skipped": f"{len(knowledge_skip_wrong)}/{sum(1 for r in work if r.case.needs_knowledge)}",
        "noul_mean_when_knowledge_needed": noul_mean(True),
        "noul_mean_when_not_needed": noul_mean(False),
    }


def calibrate_estimates(pairs: list[tuple[str, str, int]]) -> dict:
    """pairs = (lang, text, actual_prompt_tokens) → how far `estimate_tokens` is off."""
    by_lang: dict[str, list[float]] = {}
    for lang, text, actual in pairs:
        est = estimate_tokens(text)
        if est and actual:
            by_lang.setdefault(lang, []).append(actual / est)
    return {
        lang: {
            "samples": len(v),
            "actual_over_estimate_mean": round(statistics.mean(v), 2),
            "note": "1.0 = exact; >1 means the estimate is too low",
        }
        for lang, v in by_lang.items()
    }


CALIBRATION_TEXTS = {
    "en": "You are an assistant for the finance team. Summarise the quarterly report, "
    "list the three largest risks, and keep the answer short and factual. " * 6,
    "tr": "Finans ekibi için bir asistansın. Üç aylık raporu özetle, en büyük üç riski "
    "listele ve cevabı kısa ve gerçekçi tut. " * 6,
}


def run_calibration(
    base_url: str, api_key: str, model: str
) -> list[tuple[str, str, int]]:
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=30)
    pairs = []
    for lang, text in CALIBRATION_TEXTS.items():
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": text}],
            max_tokens=1,
        )
        pairs.append((lang, text, resp.usage.prompt_tokens))
    return pairs


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--repeat", type=int, default=1, help="passes over the cases (latency)"
    )
    ap.add_argument(
        "--calibrate", action="store_true", help="also calibrate estimate_tokens"
    )
    args = ap.parse_args(argv)

    if not os.getenv("TYPESAFE_API_KEY"):
        print("TYPESAFE_API_KEY is not set.", file=sys.stderr)
        return 2
    from services.intent import JevClassifier

    # Preflight (free: lists models): tell "cannot reach / bad key" apart from a
    # classifier that merely answered slowly or not at all.
    try:
        from typesafe_sdk import TypeSafeClient

        models = TypeSafeClient(timeout=15).models.list()
        print(f"Reached TypeSafe: {models}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(
            f"Cannot use the TypeSafe API: {type(e).__name__}: {str(e)[:200]}\n"
            "If this is a 403 on connect, the environment's network policy blocks "
            "api.typesafe.ai (allow it under the environment's Network access).",
            file=sys.stderr,
        )
        return 3

    # A generous timeout here (measure slow answers); production uses 1.5 s.
    trial = JevClassifier(timeout=args.timeout)
    report: dict = {
        "trial_timeout_seconds": args.timeout,
        "jev": summarize_jev(run_jev(trial, repeat=args.repeat)),
    }
    if args.calibrate:
        base, key = (
            os.getenv("OPENAI_COMPAT_BASE_URL"),
            os.getenv("OPENAI_COMPAT_API_KEY"),
        )
        if not (base and key):
            print(
                "OPENAI_COMPAT_BASE_URL / OPENAI_COMPAT_API_KEY are not set.",
                file=sys.stderr,
            )
            return 2
        model = os.getenv("OPENAI_COMPAT_MODEL", "qwen-turbo")
        report["token_estimate"] = calibrate_estimates(
            run_calibration(base, key, model)
        )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
