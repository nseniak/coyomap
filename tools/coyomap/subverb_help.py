#!/usr/bin/env python3
"""`--help` for a SUB-VERB, in one place, because two dispatchers had the same hole.

`coyomap fix` and `coyomap grounding` both take a verb and then hand the rest of the argv to a
per-verb parser. Every one of those parsers treats an unrecognised flag as a usage error, so the
first thing a reader tries — `coyomap fix dedup-edge --help` — answered
`ERROR: unknown argument '--help'`. Six surfaces did this: the four `fix` verbs and both
`grounding` verbs. A live build hit it on `dedup-edge`, fell back to running the bare verb to see
the usage block, and spent seven turns discovering an interface the tool already documented.

The fix belongs ABOVE the per-verb parsers rather than inside each of them: a parser that must
remember to special-case `--help` is a parser that will forget, which is how four of them forgot at
once. `handle(usage, verb, argv)` is called once per dispatcher, before the verb runs.

It prints the verb's OWN block when it can find one in the dispatcher's usage text, and the whole
usage otherwise — never nothing. Slicing is deliberately forgiving: a block starts at the first line
whose first token is the verb, and runs to the next line at the same indent that starts a different
verb. If the usage text is reformatted and the slice misses, the reader still gets the full text,
which is what they had before. A help that is occasionally too long beats a help that errors.
"""
from __future__ import annotations

HELP_FLAGS = ("-h", "--help")


def wants_help(argv: list[str]) -> bool:
    """True when the reader asked for help anywhere in a sub-verb's arguments."""
    return any(a in HELP_FLAGS for a in argv)


def verb_block(usage: str, verb: str) -> str | None:
    """The lines of `usage` describing `verb`, or None when it cannot be located."""
    lines = usage.splitlines()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.split(" ")[0:1] == [verb] or stripped.startswith(f"{verb} "):
            start = i
            break
    if start is None:
        return None
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            continue
        this_indent = len(line) - len(line.lstrip())
        # A sibling verb: same indent, and not the continuation prose that sits deeper. A line
        # that starts with the SAME verb is another form of it (`record --lines-from …` under
        # `record --slice …`), so it stays in the block.
        if (this_indent <= indent and not line.strip().startswith("-")
                and line.strip().split(" ")[0] != verb):
            end = j
            break
    return "\n".join(lines[start:end]).rstrip()


def handle(usage: str, verb: str, argv: list[str]) -> int | None:
    """Print help for `verb` and return 0 when help was asked for; None to carry on parsing."""
    if not wants_help(argv):
        return None
    block = verb_block(usage, verb)
    print(block if block else usage)
    return 0


def usage_error(usage: str, verb: str, message: str, stream: object = None) -> int:
    """Print an argument error for a sub-verb TOGETHER WITH that verb's usage block. Returns 2.

    A bare `ERROR: unknown option '--src'` names the mistake and withholds the answer. A live build
    guessed `drop-edge --src C1 --verb reads --dst E24`, got exactly that line five times in a row,
    and had to spend a turn on `--help` to learn the arguments are positional — the same round trip
    `wants_help` above was added to remove, arriving from the other direction. The usage text already
    exists and the dispatcher already knows the verb; withholding it is a choice, not a constraint.

    Every argument-error site in a dispatched verb goes through here, so no parser can be written
    that reports the error without the cure — the six `--help` holes above were six parsers each
    forgetting the same thing separately.
    """
    import sys
    out = stream if stream is not None else sys.stderr
    print(f"ERROR: {message}", file=out)                            # type: ignore[arg-type]
    print("", file=out)                                             # type: ignore[arg-type]
    print(verb_block(usage, verb) or usage, file=out)                # type: ignore[arg-type]
    return 2
