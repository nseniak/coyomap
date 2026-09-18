"""The update logs as the viewer reads them: the pieces of `api/changes` that need no git and no disk,
so they can be tested on strings and dicts.

A MAP CARRIES ITS LOGS beside it, one file per update (`.coyomap/changes/<from>-<to>.json`; see
method/change-impact.md, "The log"). The viewer lists them newest first and shows the newest one on its
Changes tabs without anyone arming a comparison. When a reader picks one, change mode is armed with
the log as the STORY — what the product now does differently, entry by entry, each naming its boxes —
and the map version at the log's from-commit as the EVIDENCE: the mechanical diff underneath, which
says what the map's rows did. The viewer carries the choice as `cmp=log:<from>-<to>`.

`serve.py` owns the git calls and the routes; this module owns the file names, the order and the pin.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from coyomap.changelog import commit_matches

#: A log's name is the two commits it runs between, as the file is named.
LOG_NAME = re.compile(r"^[0-9a-f]{7,40}-[0-9a-f]{7,40}$")
LOG_PREFIX = "log:"
#: What the update leaves beside a log until step 7 is clean; never a log.
SCRATCH_SUFFIXES = (".before.json", ".impact.json")


@dataclass(frozen=True)
class LogHead:
    """One update log as the list names it: which commits, when it was written, how many entries."""
    name: str
    from_commit: str
    to_commit: str
    date: str
    entries: int


def log_name(path: Path) -> str | None:
    """The update a file is the log of, or None for anything else in the folder: the scratch copies
    the update keeps beside a log until it is clean, the rendered markdown, an editor's swap file."""
    name = path.name
    if not name.endswith(".json") or name.endswith(SCRATCH_SUFFIXES) or name.startswith("."):
        return None
    stem = name[: -len(".json")]
    return stem if LOG_NAME.match(stem) else None


def parse_log_ref(ref: str) -> str | None:
    """The viewer's `log:<from>-<to>` → the log's name, or None for any other ref."""
    ref = (ref or "").strip()
    if not ref.startswith(LOG_PREFIX):
        return None
    name = ref[len(LOG_PREFIX):]
    return name if LOG_NAME.match(name) else None


def order_logs(heads: list[LogHead], pin: str | None) -> list[LogHead]:
    """Newest first. The map's pin names the newest log — the one whose to-commit moved the pin there
    — and each log's from-commit names the one before it. A log off that chain (an abandoned line, a
    map whose pin moved by hand) follows, by date."""
    rest = list(heads)
    out: list[LogHead] = []
    at = pin
    while at:
        # Two logs may end at one commit (a revert cycle, a log rewritten under a new from): the
        # newest by date is the one that moved the pin there, and a tie on the day goes by name.
        ending_here = [h for h in rest if commit_matches(h.to_commit, at)]
        if not ending_here:
            break
        head = max(ending_here, key=lambda h: (h.date, h.name))
        out.append(head)
        rest.remove(head)
        at = head.from_commit
    out.extend(sorted(rest, key=lambda h: (h.date, h.name), reverse=True))
    return out


_PIN = re.compile(r'^  "commit": "([^"]*)"', re.M)


def pin_of(text: str) -> str | None:
    """The map's own pin out of its file text — the commit the map describes, `-dirty` dropped. The
    canonical file puts the header first, indented two spaces, so the first kilobytes answer without
    parsing a megabyte; a file in any other spelling is parsed whole."""
    m = _PIN.search(text[:4096])
    if m:
        return m.group(1).removesuffix("-dirty") or None
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    v = doc.get("commit") if isinstance(doc, dict) else None
    return (v.removesuffix("-dirty") or None) if isinstance(v, str) else None
