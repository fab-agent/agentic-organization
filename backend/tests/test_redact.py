"""The filter stage: identifiers are removed by shape, ordinary work text is kept."""

import pytest

from services.redact import redact

CARD = "4111 1111 1111 1111"  # a standard test card number (passes Luhn)
IBAN = "TR33 0006 1005 1978 6457 8413 26"  # the documented TR example (mod 97 = 1)
TCKN = "10000000146"  # a checksum-valid test id


@pytest.mark.parametrize(
    "text,kind",
    [
        ("mail ayse@firma.com.tr about it", "email"),
        (f"card {CARD} was charged", "card"),
        (f"paid to {IBAN} today", "iban"),
        (f"kimlik {TCKN} verified", "national-id"),
        ("call +90 532 123 45 67 tomorrow", "phone"),
        ("call 0532 123 45 67 tomorrow", "phone"),
        ("see https://x.example.com/a?token=abc123 for it", "url"),
        ("see www.example.com/report", "url"),
        ("host 10.0.12.200 is down", "ip"),
        ("key sk-abcdefghijklmnopqrstuvwx used", "secret"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdEFGH end", "secret"),
        ("hash " + "a1" * 20 + " end", "secret"),
        ("password: hunter22222", "secret"),
        ("Bearer abcdefghijklmnop1234", "secret"),
    ],
)
def test_each_kind_is_replaced_by_a_tag(text, kind):
    r = redact(text)
    assert f"[{kind}]" in r.text and r.counts.get(kind, 0) >= 1
    # nothing of the original identifier survives
    for frag in (
        "ayse@",
        "4111",
        "TR33",
        "10000000146",
        "532 123",
        "token=abc",
        "10.0.12.200",
        "sk-abc",
        "hunter",
        "abcdefghijklmnop1234",
    ):
        assert frag not in r.text


def test_the_rest_of_the_sentence_is_kept():
    r = redact("Sent the Q3 renewal analysis to ayse@firma.com and closed the deal.")
    assert r.text == "Sent the Q3 renewal analysis to [email] and closed the deal."


@pytest.mark.parametrize(
    "text",
    [
        "Revenue grew 20% to 1,250,000 TRY in 2026.",
        "Invoice 2026-0912 for 4500.75 was matched.",
        "Meeting on 2026-09-29 at 14:30",
        "",
    ],
)
def test_ordinary_work_text_is_not_touched(text):
    r = redact(text)
    assert r.text == text and r.counts == {}


def test_a_dotted_quad_is_treated_as_an_ip():
    # indistinguishable from a version number; over-redacting is the safe side
    assert redact("Version 1.2.3.4 released").counts == {"ip": 1}


@pytest.mark.parametrize(
    "text",
    [
        "Order 12345678901234 shipped",  # 14 digits, fails Luhn
        "ID 12345678901 is not a valid national id",  # fails the checksum
        "TR33 0006 1005 1978 6457 8413 27 is not an iban",  # fails mod 97
    ],
)
def test_long_numbers_failing_their_checksum_are_not_labelled_as_that_kind(text):
    # They may still be swept up as phone-shaped digit runs (safe side), but never
    # claimed to be a card, national id or IBAN.
    kinds = set(redact(text).counts)
    assert not kinds & {"card", "national-id", "iban"}


def test_counts_are_per_kind():
    r = redact("a@b.co and c@d.co, call +90 532 123 45 67")
    assert r.counts == {"email": 2, "phone": 1}


def test_a_bad_checksum_number_is_not_mistaken_for_a_card_or_id():
    r = redact("ref 4111 1111 1111 1112")  # last digit breaks Luhn
    assert "card" not in r.counts and "national-id" not in r.counts


def test_none_and_non_text_are_safe():
    assert redact(None).text == ""  # type: ignore[arg-type]
    assert redact("").counts == {}


def test_it_is_idempotent():
    once = redact(f"{CARD} {IBAN} ayse@x.co +90 532 123 45 67").text
    assert redact(once).text == once
