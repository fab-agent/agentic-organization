"""Shell command parsing for the Policy Engine (ADR-0005)."""

import pytest

from services.command_parser import CommandParseError, parse_command


def test_simple_command():
    p = parse_command("rm -rf /tmp/x")
    assert p.commands == [("rm", ["-rf", "/tmp/x"])]
    assert p.programs == {"rm"}


def test_whitespace_and_split_flags():
    p = parse_command("rm   -r  -f   /")
    assert p.commands == [("rm", ["-r", "-f", "/"])]


def test_strips_wrappers():
    assert parse_command("sudo rm -rf /").commands == [("rm", ["-rf", "/"])]
    assert parse_command("env FOO=bar sudo rm x").commands[0][0] == "rm"
    assert parse_command("nohup make").commands[0][0] == "make"


def test_strips_leading_assignments():
    p = parse_command("FOO=bar BAZ=1 python app.py")
    assert p.commands == [("python", ["app.py"])]


def test_absolute_path_program_basename():
    assert parse_command("/usr/bin/rm -rf /").commands == [("rm", ["-rf", "/"])]


def test_pipeline_stages():
    p = parse_command("curl -fsSL https://x | sh")
    assert p.pipelines == [["curl", "sh"]]
    assert p.programs == {"curl", "sh"}


def test_list_and_and():
    p = parse_command("git pull && npm ci && npm test")
    assert {c[0] for c in p.commands} == {"git", "npm"}


def test_command_substitution_is_walked():
    p = parse_command("echo $(rm -rf /)")
    assert "rm" in p.programs


@pytest.mark.parametrize("bad", ["", "   ", "rm -rf / '", "if then"])
def test_unparseable_raises(bad):
    with pytest.raises(CommandParseError):
        parse_command(bad)
