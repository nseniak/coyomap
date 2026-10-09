#!/usr/bin/env python3
"""`coyomap changes merge` — one change log out of the drafts several helpers wrote in parallel.

WHY. A large diff is read by several agents at once, each writing the entries for its own share of
the commits. On the 2026-10-09 mcpolis update (31 commits, 303 files) six helpers wrote drafts, and
the lead did the rest by hand: reserved id ranges per helper for new rows, merged the drafts,
renumbered the new ids to the next free numbers, and found three pairs of entries editing the same
field. This does that part, and only that part.

PLACEHOLDERS. A helper never guesses the next free number: two helpers would both pick `BR232`. A
box a draft adds goes by a placeholder, its kind's letters, `?`, the helper's letter and a number:
`BR?a1`, `EP?b2`, `UC?c1`. Every other draft may name it by the same spelling, in any field, in any
id it is part of (`flow:UC?c1`, `edge:C?a1>calls>C3`, `rule:BR?a1:0`). The merge gives each
placeholder the next free number of its kind in the map, in the order the drafts are given, and
writes that number everywhere the placeholder stood. A placeholder two drafts add, or one no draft
adds, is refused: one is a clash, the other a box nobody wrote.

WHAT IS JOINED. Entries in draft order, renumbered `e1`…; waivers by box, their reasons joined;
notes in draft order. Two entries editing the same field with the same new words are one edit,
kept in the first. Two entries editing it with different words are a decision the merge cannot
make: both are kept, the clash is listed with the two drafts named, and the command exits 1 so the
lead resolves it before `lint`, which refuses the pair too. Stdlib-only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from coyomap.changelog import FORMAT, VERSION, commit_matches, index_map
from coyomap.model import ID_ARRAYS

#: A placeholder id: the kind's letters, `?`, then a tag starting with a lowercase letter.
PLACEHOLDER = re.compile(r"\b([A-Z]+)\?([a-z][A-Za-z0-9_]*)")
_NUMBERED = re.compile(r"^([A-Z]+)(\d+)$")


@dataclass
class Merged:
    log: dict[str, Any]
    numbered: dict[str, str] = field(default_factory=dict)     # placeholder → the id it became
    clashes: list[str] = field(default_factory=list)           # blocking: the lead decides
    joined: list[str] = field(default_factory=list)            # repeats the merge folded, for the record


def _strings(node: Any) -> list[str]:
    """Every string in a JSON value, keys included."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in (k, *_strings(v))]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def _swap(node: Any, numbered: dict[str, str]) -> Any:
    """`node` with every placeholder replaced by its number, wherever it stands in a string."""
    if isinstance(node, str):
        return PLACEHOLDER.sub(lambda m: numbered.get(m.group(0), m.group(0)), node)
    if isinstance(node, dict):
        return {_swap(k, numbered): _swap(v, numbered) for k, v in node.items()}
    if isinstance(node, list):
        return [_swap(v, numbered) for v in node]
    return node


def _added_row_ids(draft: dict[str, Any]) -> list[str]:
    """The `id` of every row a draft adds. A flow's `uc` names the use case it belongs to and adds
    nothing of its own, so it is not here."""
    out: list[str] = []
    for e in draft.get("entries") or []:
        for a in (e.get("added") or []) if isinstance(e, dict) else []:
            row = a.get("row") if isinstance(a, dict) else None
            value = row.get("id") if isinstance(row, dict) else None
            if isinstance(value, str) and value not in out:
                out.append(value)
    return out


def _added_placeholders(draft: dict[str, Any]) -> list[str]:
    return [i for i in _added_row_ids(draft) if PLACEHOLDER.fullmatch(i)]


def _next_free(doc: dict[str, Any], drafts: list[tuple[str, dict[str, Any]]]) -> dict[str, int]:
    """The next free number of every kind of id, above the map's AND every id a draft adds by its
    number: a draft that wrote `BR255` itself must not see a placeholder become `BR255` too."""
    top: dict[str, int] = {}
    for rid in [*index_map(doc), *(i for _n, d in drafts for i in _added_row_ids(d))]:
        m = _NUMBERED.match(rid)
        if m:
            top[m.group(1)] = max(top.get(m.group(1), 0), int(m.group(2)))
    return {k: v + 1 for k, v in top.items()}


def _kinds(doc: dict[str, Any]) -> set[str]:
    """The letters an id of this map can start with: a placeholder is one of them, `?`, a tag. An
    all-caps word before a `?` in a sentence or an address (`/sso/SAML?relay=…`) is not."""
    return set(ID_ARRAYS.values()) | {"EP", "HP"} | {m.group(1) for rid in index_map(doc)
                                                     if (m := _NUMBERED.match(rid))}


def merge(drafts: list[tuple[str, dict[str, Any]]], doc: dict[str, Any]) -> Merged:
    """One log out of `(name, draft)` pairs, against the map they were written for. Raises
    ValueError for drafts that cannot be one log: different commits, a placeholder added twice or
    by nobody."""
    if not drafts:
        raise ValueError("no drafts to merge")
    first = drafts[0][1]
    for name, d in drafts:
        if d.get("format") != FORMAT or d.get("version") != VERSION:
            raise ValueError(f"{name}: not a change log ({FORMAT} version {VERSION})")
        if not (commit_matches(d.get("from_commit"), first.get("from_commit"))
                and commit_matches(d.get("to_commit"), first.get("to_commit"))):
            raise ValueError(f"{name}: covers {d.get('from_commit')}..{d.get('to_commit')}, the first draft "
                             f"{first.get('from_commit')}..{first.get('to_commit')}")
    adder: dict[str, str] = {}
    for name, d in drafts:
        for ph in _added_placeholders(d):
            if ph in adder:
                raise ValueError(f"{ph} is added by both {adder[ph]} and {name}: give one of them another tag")
            adder[ph] = name
    kinds = _kinds(doc)
    named = sorted({m.group(0) for _name, d in drafts for s in _strings(d) for m in PLACEHOLDER.finditer(s)
                    if m.group(1) in kinds})
    orphans = [ph for ph in named if ph not in adder]
    if orphans:
        raise ValueError(f"{', '.join(orphans)} named but added by no draft: a placeholder is a box a "
                         f"draft adds")
    free = _next_free(doc, drafts)
    numbered: dict[str, str] = {}
    for ph in adder:                                     # draft order, then the order each adds them
        kind = ph.split("?", 1)[0]
        numbered[ph] = f"{kind}{free.get(kind, 1)}"
        free[kind] = free.get(kind, 1) + 1
    out = Merged({"format": FORMAT, "version": VERSION, "from_commit": first.get("from_commit"),
                  "to_commit": first.get("to_commit"),
                  "date": max(str(d.get("date") or "") for _n, d in drafts), "entries": [],
                  "waived": [], "notes": ""}, numbered)
    edited: dict[tuple[str, str], tuple[str, str, Any, dict[str, Any]]] = {}   # (box, key) → draft, entry, now, edit
    waivers: dict[str, list[str]] = {}
    notes: list[str] = []
    for name, raw in drafts:
        d = _swap(raw, numbered)
        for e in d.get("entries") or []:
            entry = dict(e)
            entry["id"] = f"e{len(out.log['entries']) + 1}"
            kept: list[dict[str, Any]] = []
            for ed in entry.get("edits") or []:
                key = (str(ed.get("id")), str(ed.get("key")))
                if key in edited:
                    other, other_entry, now, _first = edited[key]
                    if now == ed.get("now"):
                        out.joined.append(f"{key[0]}.{key[1]}: the same edit in {other} ({other_entry}) and "
                                          f"{name} ({entry['id']}); kept once, in {other_entry}")
                        continue
                    out.clashes.append(f"{key[0]}.{key[1]} is edited by {other} ({other_entry}) and by "
                                       f"{name} ({entry['id']}) with different words: keep one, or write "
                                       f"one edit that says both")
                else:
                    edited[key] = (name, entry["id"], ed.get("now"), ed)
                kept.append(ed)
            entry["edits"] = kept
            out.log["entries"].append(entry)
        for w in d.get("waived") or []:
            why = str(w.get("why") or "").strip()
            whys = waivers.setdefault(str(w.get("id")), [])
            if why and why not in whys:
                whys.append(why)
        if str(d.get("notes") or "").strip():
            notes.append(str(d["notes"]).strip())
    out.log["waived"] = [{"id": i, "why": " / ".join(whys)} for i, whys in waivers.items()]
    out.log["notes"] = "\n\n".join(notes)
    return out


def format_merged(m: Merged, drafts: int) -> str:
    lines = [f"merge — {drafts} draft(s) → {len(m.log['entries'])} entries, {len(m.log['waived'])} waiver(s), "
             f"{len(m.numbered)} new id(s) numbered, {len(m.clashes)} clash(es)"]
    lines += [f"  {ph} → {rid}" for ph, rid in m.numbered.items()]
    lines += [f"  joined: {j}" for j in m.joined]
    lines += [f"  CLASH: {c}" for c in m.clashes]
    if m.clashes:
        lines.append("  Resolve each clash in the merged log, then `changes lint`: lint refuses a field "
                     "edited twice.")
    return "\n".join(lines)


def dump(m: Merged) -> str:
    return json.dumps(m.log, indent=2, ensure_ascii=False) + "\n"
