"""
render-filter.sh — the sandbox egress allowlist renderer (ADR-0002 / ADR-0010).

Pure-shell script; we exercise it via subprocess. No backend imports, so this
runs from a bare `python -m pytest sandbox/egress/`.
"""

import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
SCRIPT = HERE / "render-filter.sh"
BASE = HERE / "base-allowlist.txt"


def render(base=BASE, **env) -> list[str]:
    full_env = {"PATH": "/usr/bin:/bin"}
    full_env.update({k: v for k, v in env.items() if v is not None})
    out = subprocess.run(
        ["sh", str(SCRIPT), str(base)],
        capture_output=True,
        text=True,
        env=full_env,
        check=True,
    )
    return [ln for ln in out.stdout.splitlines() if ln]


def test_base_allowlist_becomes_anchored_suffix_regexes():
    lines = render()
    assert r"(^|\.)github\.com$" in lines
    assert r"(^|\.)registry\.npmjs\.org$" in lines
    # comments / blank lines are dropped
    assert not any(ln.startswith("#") for ln in lines)
    assert all(ln.startswith("(^|\\.)") and ln.endswith("$") for ln in lines)


def test_regex_matches_subdomain_not_lookalike():
    import re

    pat = re.compile(r"(^|\.)github\.com$")
    assert pat.search("github.com")
    assert pat.search("api.github.com")
    assert not pat.search("evilgithub.com")
    assert not pat.search("github.com.evil.net")


def test_gateway_host_is_extracted_from_base_url():
    lines = render(FABAGENT_BASE_URL="https://user@agents.example.com:8443/v1/")
    assert r"(^|\.)agents\.example\.com$" in lines


def test_env_allowlist_is_split_on_comma_space_newline():
    lines = render(EGRESS_ALLOWLIST="a.com, b.com c.com\nd.com")
    for host in ("a", "b", "c", "d"):
        assert rf"(^|\.){host}\.com$" in lines


def test_wildcard_and_leading_dot_are_stripped():
    lines = render(EGRESS_ALLOWLIST="*.corp.internal,.example.org")
    assert r"(^|\.)corp\.internal$" in lines
    assert r"(^|\.)example\.org$" in lines


def test_duplicates_collapse_case_insensitively():
    lines = render(EGRESS_ALLOWLIST="GitHub.com, github.com")
    assert lines.count(r"(^|\.)github\.com$") == 1


def test_empty_base_and_no_env_yields_nothing(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("# just a comment\n\n")
    assert render(base=empty) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
