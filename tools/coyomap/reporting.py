#!/usr/bin/env python3
"""How a finding LIST is rendered — the one place, so a machine-readable mode cannot lie.

Every check that names a set of ids or files truncates it, because a report a human cannot read is
not a report: `16 of 86 component(s) carry no backbone edge: C1, C12, … +8 more`. That is right for
a reader and wrong for a pipe. A live build hit exactly that line, needed the hidden eight to write
its exceptions block, and re-derived the whole list in a throwaway python script — one of about
fifteen such scripts in a run whose method told it to use the tools instead.

So truncation became a mode: `--json` sets `set_full_lists(True)` and every list is emitted whole.

**Why this is its own module.** The first version of this lived in `validate_model` and converted the
eighteen truncation sites in that file. `validate_analysis` — which `validate_model` imports, so it
cannot import back — kept two of its own, and one of them (`file_level_coverage`, reached under the
`--check-coverage` flag the method tells every build to run) emitted `+N more dir(s)` INSIDE the JSON
payload that had just promised whole lists. A machine-readable mode with a documented completeness
guarantee it does not keep is worse than no mode at all: the human reader can see the tail and knows
to look further, the program cannot. A shared module is what makes "one exit" true rather than
claimed, and it is what lets a single test walk the whole package for a hand-written truncation.

Stdlib-only (the cli.py dependency firewall).
"""
from __future__ import annotations

from collections.abc import Sequence

#: When True every list is emitted WHOLE and prose is not clipped. Process-wide, because the
#: alternative is threading a flag through ~30 check functions that exist to return `list[str]`.
#: Set once from a CLI entry point via `set_full_lists`; `reset_full_lists` exists so a test (or an
#: in-process consumer that runs a JSON pass) cannot leak the mode into everything after it.
_FULL_LISTS = False


def set_full_lists(on: bool = True) -> None:
    """Turn whole-list mode on (a `--json` entry point) or off."""
    global _FULL_LISTS
    _FULL_LISTS = on


def reset_full_lists() -> None:
    """Back to the human default. Call in a `finally` around any in-process JSON run."""
    set_full_lists(False)


def full_lists() -> bool:
    """Whether whole-list mode is on — for a caller that renders its own list."""
    return _FULL_LISTS


def shown(items: Sequence[str], limit: int, sep: str = ", ", unit: str = "") -> str:
    """`items` inline, truncated to `limit` with a `+N more` tail — unless whole-list mode is on.

    `unit` names what was elided when the count alone would read oddly ("+3 more dir(s)"). Every
    truncated list in the package goes through here; a hand-written one silently bypasses `--json`,
    which is what `test_no_hand_written_truncation_bypasses_the_helper` pins."""
    if _FULL_LISTS or len(items) <= limit:
        return sep.join(items)
    tail = f"+{len(items) - limit} more{f' {unit}' if unit else ''}"
    return sep.join([*items[:limit], tail])


def item_lines(items: Sequence[str], limit: int | None, unit: str = "") -> str:
    """`items` one per line, each opening `  - `, to follow a message's count line: every one when
    `limit` is None, else the first `limit` and a `+N more` line — unless whole-list mode is on.

    ONE ITEM PER LINE, UNDER A SHORT LINE CARRYING THE COUNT. `head`, `tail` and `cut` all read
    lines, so a list kept inside one line loses items, or the count after it, to each of them: the
    access-baseline advisory of `finalize` was one line of 6,740 characters on the 2026-10-07 mcpolis
    build, a `cut -c1-500` left 1 of its 20 lost files legible, and 6 previous access rules shipped
    lost. `finalize` and `grounding lint` each grew a private copy of these lines that day; this is
    the one both call. Empty for no items, so a caller can append it to its count line as it is."""
    if not items:
        return ""
    return "  - " + shown(items, len(items) if limit is None else limit, sep="\n  - ", unit=unit)


def capped(items: Sequence[tuple[int, str]], limit: int) -> tuple[Sequence[tuple[int, str]], int]:
    """`(kept, dropped)` for a check that emits ONE FINDING PER ITEM rather than one inline list.

    A per-item cap cannot carry a `+N more` tail inside a message, so it has to return the dropped
    count for the caller to disclose. `compression_coverage_from_refs` capped at 8 and said nothing,
    which is strictly worse than a visible tail: a reader — and a `--json` consumer — could not tell
    that four unmapped modules had been dropped on the floor."""
    if _FULL_LISTS or len(items) <= limit:
        return items, 0
    return items[:limit], len(items) - limit


def clip(text: str, n: int = 60) -> str:
    """Free prose (a trigger phrase, an endpoint description) shortened so one row cannot flood the
    report. Not clipped in whole-list mode: a clipped trigger cannot be matched back to the entry
    point it names, which is the same reason `shown` stops truncating there."""
    text = " ".join(text.split())
    if _FULL_LISTS or len(text) <= n:
        return text
    return text[:n].rstrip() + "…"
