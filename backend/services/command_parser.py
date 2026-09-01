"""
Shell command parsing for the Policy Engine (ADR-0005).

Glob patterns over a raw command string are trivially bypassed
(`rm  -rf  /`, `$(echo rm) -rf /`, `RM=rm; $RM ...`). This module parses the
command into an AST (`bashlex`) and exposes the *resolved* programs and args, so
a policy rule can match on structure instead of spelling.

`parse_command()` raises `CommandParseError` on anything it cannot analyse — a
rule that relies on command structure then fails closed (deny).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Programs that wrap another command; the real program is the next word.
_WRAPPERS = {
    "sudo",
    "doas",
    "env",
    "command",
    "nohup",
    "time",
    "stdbuf",
    "nice",
    "ionice",
    "setsid",
    "timeout",
    "xargs",
}


class CommandParseError(Exception):
    """Raised when a command string cannot be parsed / analysed."""


@dataclass
class ParsedCommand:
    # Every simple command, wrappers stripped: [(program_basename, [args...]), ...]
    commands: list[tuple[str, list[str]]] = field(default_factory=list)
    # All program basenames seen anywhere (including inside substitutions / pipes).
    programs: set[str] = field(default_factory=set)
    # Each pipeline as an ordered list of program basenames.
    pipelines: list[list[str]] = field(default_factory=list)


def _basename(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def parse_command(command: str) -> ParsedCommand:
    if not isinstance(command, str) or not command.strip():
        raise CommandParseError("empty command")
    try:
        import bashlex
    except Exception as e:  # pragma: no cover - dependency wiring only
        raise CommandParseError(f"bashlex unavailable: {e}") from e

    try:
        trees = bashlex.parse(command)
    except Exception as e:
        raise CommandParseError(f"unparseable: {e}") from e

    result = ParsedCommand()

    def _words_of(node) -> list[str]:
        words: list[str] = []
        for part in getattr(node, "parts", []):
            kind = getattr(part, "kind", None)
            if kind == "word":
                w = getattr(part, "word", "")
                # A word can itself contain a command substitution ($(...), `...`).
                for sub in getattr(part, "parts", []):
                    if getattr(sub, "kind", None) == "commandsubstitution":
                        _visit(getattr(sub, "command", sub))
                if w:
                    words.append(w)
            elif kind in ("commandsubstitution", "processsubstitution"):
                _visit(getattr(part, "command", part))
        return words

    def _simple_command(node) -> None:
        words = _words_of(node)
        if not words:
            return
        # Strip leading VAR=value assignments and wrapper programs, repeatedly
        # (e.g. `env FOO=bar sudo cmd`).
        prog_words = list(words)
        changed = True
        while changed and prog_words:
            changed = False
            while (
                prog_words
                and "=" in prog_words[0]
                and not prog_words[0].startswith("-")
                and "/" not in prog_words[0].split("=", 1)[0]
            ):
                prog_words = prog_words[1:]
                changed = True
            if prog_words and _basename(prog_words[0]) in _WRAPPERS:
                prog_words = prog_words[1:]
                changed = True
        if not prog_words:
            return
        program = _basename(prog_words[0])
        args = prog_words[1:]
        result.commands.append((program, args))
        result.programs.add(program)
        return program

    def _visit(node) -> None:
        kind = getattr(node, "kind", None)
        if kind == "command":
            _simple_command(node)
        elif kind == "pipeline":
            stages: list[str] = []
            for part in getattr(node, "parts", []):
                if getattr(part, "kind", None) == "command":
                    prog = _simple_command(part)
                    if prog:
                        stages.append(prog)
                else:
                    _visit(part)
            if stages:
                result.pipelines.append(stages)
        else:
            for part in getattr(node, "parts", []):
                _visit(part)
            # compound / list nodes also carry `.list` in some bashlex versions
            for part in getattr(node, "list", []) or []:
                _visit(part)

    for tree in trees:
        _visit(tree)

    if not result.commands and not result.pipelines:
        raise CommandParseError("no command found")
    return result
