"""Compare the served map with an old one: the pieces of `api/mapcommits` and `api/compare` that need
no git and no disk, so they can be tested on strings.

THE OLD MAP comes from one of two places, named by one `ref` string the viewer carries in its link:
  * a commit sha — a version out of the map file's own git history (`api/mapcommits` lists them);
  * `path:<file>` — a map file on disk, typed into the picker (a backup, a rebuild, another checkout).
The served map is always the NEW side: the file on disk, uncommitted edits included, so the first
history row answers "what did my accept change?" before it is committed.

THE CHANGE DOCUMENT is `mapdiff.diff_maps` verbatim (one engine, three readers), wrapped with the two
labels the viewer shows. `serve.py` owns the git calls and the routes; this module owns the parsing
and the shape.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from coyomap.mapdiff import diff_maps, looks_like_map, to_json

_SHA = re.compile(r"^[0-9a-f]{7,40}$")
PATH_PREFIX = "path:"
#: `git log` field separator — a unit separator, which no subject line contains.
LOG_FORMAT = "%H%x1f%h%x1f%cs%x1f%s"


@dataclass(frozen=True)
class MapVersion:
    """One commit that changed the map file: when, what the commit said, and where the file was then
    (the folder was `.coyodex/` before 2026-09-13, and `--follow` keeps the trail across the rename)."""
    sha: str
    short: str
    date: str
    subject: str
    path: str


def parse_history(text: str) -> list[MapVersion]:
    """`git log --follow --format=<LOG_FORMAT> --name-only -- <map>` → the map's versions, newest
    first. Each commit is one header line, a blank, then the file's path at that commit."""
    out: list[MapVersion] = []
    head: tuple[str, str, str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if "\x1f" in line:
            parts = line.split("\x1f")
            if len(parts) == 4:
                head = (parts[0], parts[1], parts[2], parts[3])
            else:
                head = None
            continue
        if line and head is not None:
            out.append(MapVersion(*head, path=line))
            head = None
    return out


def parse_ref(ref: str) -> tuple[str, str] | None:
    """The viewer's `ref` → ("commit", sha) or ("path", file), or None when it is neither."""
    ref = (ref or "").strip()
    if ref.startswith(PATH_PREFIX):
        p = ref[len(PATH_PREFIX):].strip()
        return ("path", p) if p and "\x00" not in p else None
    return ("commit", ref) if _SHA.match(ref) else None


def load_map_doc(text: str, what: str) -> dict[str, Any]:
    """A map document out of file text, or a ValueError naming what was handed over instead."""
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise ValueError(f"{what} is not JSON: {e}") from None
    if not looks_like_map(doc):
        raise ValueError(f"{what} is not a coyomap map")
    return doc


def version_label(v: MapVersion) -> str:
    return f"{v.date} · {v.subject}"


def compare_payload(new_doc: dict[str, Any], old_doc: dict[str, Any], ref: str,
                    old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """The change document the viewer's change mode reads: the engine's JSON plus the two sides'
    labels. `old` / `new` carry `label` and whatever else the picker showed (sha, date, path)."""
    delta = diff_maps(old_doc, new_doc, str(old.get("label") or "old map"),
                      str(new.get("label") or "current map"))
    payload = to_json(delta)
    payload.update({"ref": ref, "old": old, "new": new})
    return payload


def history_payload(versions: list[MapVersion], dirty: bool) -> dict[str, Any]:
    """`api/mapcommits`: the versions, newest first, and whether the file on disk has edits the last
    commit does not — then the first row is "the last committed map", the comparison an accept wants."""
    return {"versions": [{**asdict(v), "label": version_label(v)} for v in versions], "dirty": dirty}
