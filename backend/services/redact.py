"""Filter stage of the work-review pipeline: redact identifiers before text is sent to a
scoring model (ADR-0019 §6 step 1, ADR-0021).

Pure and deterministic — no model call. It removes what can be recognised by shape:
secrets and tokens, e-mail addresses, URLs, card numbers (Luhn), IBANs (mod 97),
Turkish national ids (checksum), phone numbers and IP addresses. Each is replaced by a
tag such as ``[email]`` so the text keeps its meaning.

**It is a floor, not a guarantee.** It does not recognise people's names, addresses,
health or salary details written in prose, or anything without a fixed shape. That is
why rating stays off by default and per company (ADR-0021 *Implementation status*), and
why counsel review stays required before it is enabled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Redacted:
    text: str
    counts: dict[str, int] = field(default_factory=dict)


def _luhn(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_ok(raw: str) -> bool:
    s = re.sub(r"\s", "", raw).upper()
    if not 15 <= len(s) <= 34:
        return False
    moved = s[4:] + s[:4]
    try:
        n = int("".join(str(int(c, 36)) for c in moved))
    except ValueError:
        return False
    return n % 97 == 1


def _tckn_ok(s: str) -> bool:
    if len(s) != 11 or s[0] == "0" or not s.isdigit():
        return False
    d = [int(c) for c in s]
    if ((sum(d[0:9:2]) * 7) - sum(d[1:8:2])) % 10 != d[9]:
        return False
    return sum(d[:10]) % 10 == d[10]


_SECRET = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}|[A-Fa-f0-9]{32,})\b"
)
_BEARER = re.compile(
    r"(?i)\b(bearer|token|api[_-]?key|password|parola|şifre)\b(\s*[:=]?\s*)(\S{6,})"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')]+", re.I)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")
_LONG_DIGITS = re.compile(r"(?<![\w.])\d(?:[ -]?\d){10,18}(?![\w])")
_PHONE = re.compile(r"(?<![\w.])(?:\+|00)?\d[\d ().-]{8,}\d(?![\w])")
_IPV4 = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)


def redact(text: str) -> Redacted:
    """Return `text` with recognisable identifiers replaced, and how many of each."""
    counts: dict[str, int] = {}

    def bump(kind: str) -> str:
        counts[kind] = counts.get(kind, 0) + 1
        return f"[{kind}]"

    out = text or ""
    out = _SECRET.sub(lambda m: bump("secret"), out)
    out = _BEARER.sub(lambda m: f"{m.group(1)}{m.group(2)}{bump('secret')}", out)
    out = _EMAIL.sub(lambda m: bump("email"), out)
    out = _URL.sub(lambda m: bump("url"), out)
    out = _IBAN.sub(lambda m: bump("iban") if _iban_ok(m.group(0)) else m.group(0), out)

    def digits(m: re.Match) -> str:
        raw = re.sub(r"\D", "", m.group(0))
        if _tckn_ok(raw):
            return bump("national-id")
        if _luhn(raw):
            return bump("card")
        return m.group(0)

    out = _LONG_DIGITS.sub(digits, out)
    out = _IPV4.sub(lambda m: bump("ip"), out)

    def phone(m: re.Match) -> str:
        n = len(re.sub(r"\D", "", m.group(0)))
        return bump("phone") if 10 <= n <= 15 else m.group(0)

    out = _PHONE.sub(phone, out)
    return Redacted(out, counts)
