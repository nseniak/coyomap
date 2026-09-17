#!/usr/bin/env python3
"""The change log of one map update — what the product now does differently, in entries that name
the boxes they are about, and the map edits each entry makes.

WHY A FORMAT. The change-impact report was prose: six headlines in 58 lines naming one box, then
246 per-element blocks naming no headline, then 242 line moves written by hand. Nothing could read
it back: no screen could draw it, no check could say whether it covered the map's change, and the
"mechanical" accept was an agent editing JSON by hand. This file is the report as DATA, written by
the agent that analyzed the code, and four tools read it:

  lint    the file is well formed, every entry names at least one box, every id exists (or the
          entry adds it), every `was` matches the map it is written against
  render  the same log as markdown for people: entries under Product / Under the hood, boxes by name
  apply   the entries' edits, additions and removals written into the map, the pin bumped
  check   the completeness gate: every box the map's own diff says changed is named by an entry or
          waived, and every box an entry names exists — the two-way rule, enforced. It runs BEFORE
          the write, on the log applied to a copy of the map (`--map`), and again after it, on the
          map before and after (`--old`/`--new`), so a gap costs nothing to close

ADDRESSING. An edit names a box by id and a field by a path inside its row: `risk`,
`sites[0].where`, `steps[n=4].phrase` (a step by its number), `fields[name=size].type` (an item by
a key). A use case's flow is the row `flow:<UC id>`; a shared sub-flow's steps are on its own row.
Never a JSON pointer with an array index into the whole map: those broke the moment a row above
moved.

WHAT IS NOT HERE. Code-link moves: `coyomap reanchor` computes them from git and writes them
itself, so an entry never lists them, and `check` ignores link-only changes. Stdlib-only.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from coyomap import subverb_help
from coyomap.mapdiff import KIND_OF, KINDS, diff_maps, field_spec, looks_like_map
from coyomap.model import ModelError, ProjectModel, load_model
from coyomap.prose import Finding, field_findings, iter_prose_fields
from coyomap.validate_model import validate_model

FORMAT = "coyomap-changes"
VERSION = 1
#: Rows that carry no authored id get one from their key, so an entry can name them and `check`
#: can gate them — the same ids the impact engine mints (`glossary:<term>`, `run:<action>`, `net:<name>`).
SYNTH_PREFIX = {"glossary": "glossary:", "run_commands": "run:", "config": "config:",
                "deployment": "deployment:", "observability": "observability:", "non_entity_types": "net:"}
#: The map's own header (title, goal, …) is a box too: `map`, with its scalar fields as keys.
MAP_ID = "map"
MAP_BOOKKEEPING = frozenset({"format", "version", "commit", "committed", "built"})
CONFIDENCE_WORDS = ("verified", "likely", "inferred")
HEADLINE_WORDS_MAX = 14

USAGE = """usage: coyomap changes <verb> [options]

  lint <log> --map <map>
        is the log well formed against this map? Every id exists, every `was` matches, and the
        whole apply runs on a copy through the loader and the validator's blocking checks; every
        sentence the log changes or adds faces the readability check, as a warning
  render <log> --map <map> [--out <file.md>]
        the log as markdown for people: entries under Product / Under the hood, boxes by name
  apply <log> --map <map> [--out <map>] [--date <YYYY-MM-DD>]
        write the entries into the map and bump its pin (--date: the to-commit's date, into
        `committed`); refuses a log that does not lint clean
  check <log> --map <map> [--touched <impact.json>] [--json]
        the completeness gate BEFORE the write: the log, applied to a copy of this map, explains
        every change it makes, and names or waives every box the code touched (--touched)
        --old <map> --new <map> in place of --map: the same gate AFTER apply, on the map before
        and after it

The log is `.coyomap/changes/<from>-<to>.json`, written by the agent that analyzed the code.
Every verb is read-only except `apply`, which writes the map it is given (or `--out`).
`coyomap changes <verb> --help` prints that verb's block alone.
"""

Change = Literal["added", "removed", "modified"]


# ── the format ────────────────────────────────────────────────────────────────────────────────────

@dataclass
class FieldEdit:
    id: str            # the box (an authored id, `flow:<UC>` for a use case's flow)
    key: str           # a path inside its row: `risk`, `sites[0].where`, `steps[n=4].phrase`
    was: Any           # None when the field did not exist
    now: Any           # None removes the field


@dataclass
class Addition:
    kind: str          # the array the row goes into: `rules`, `entry_points`, …
    row: dict[str, Any]


@dataclass
class Entry:
    id: str
    headline: str                       # one line, in product words
    sentence: str                       # what a user can now do, or what the machine now does
    elements: list[str]                 # every box this entry is about, by id
    edits: list[FieldEdit] = field(default_factory=list)
    added: list[Addition] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)      # ids of rows the entry takes out
    evidence: list[str] = field(default_factory=list)     # the code files the claim rests on
    confidence: str = "verified"                          # verified | likely | inferred

    def ids_edited(self) -> set[str]:
        """The boxes this entry writes to. An edit on a use case's flow (`flow:<UC>`) is an edit
        on the use case: the flow is how the use case happens, not a box of its own."""
        out = {e.id[len(FLOW_PREFIX):] if e.id.startswith(FLOW_PREFIX) else e.id for e in self.edits} | set(self.removed)
        for a in self.added:
            rid = a.row.get("id")
            if isinstance(rid, str):
                out.add(rid)
        return out


@dataclass
class Waiver:
    id: str
    why: str


@dataclass
class ChangeLog:
    from_commit: str
    to_commit: str
    date: str                           # the day the log was written, YYYY-MM-DD
    entries: list[Entry]
    waived: list[Waiver] = field(default_factory=list)   # boxes the code touched with no change of meaning
    notes: str = ""                     # the honesty footer: resolution reached, gaps, seams

    def named(self) -> set[str]:
        return {i for e in self.entries for i in e.elements}


@dataclass
class Problems:
    """What lint or check found. `errors` block; `warnings` are advisory and never block."""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ── reading and writing the file ──────────────────────────────────────────────────────────────────

def load_log(text: str) -> ChangeLog:
    """A ChangeLog out of its JSON text. Shape problems raise ValueError naming the path."""
    doc = json.loads(text)
    if not isinstance(doc, dict):
        raise ValueError("the log is not an object")
    if doc.get("format") != FORMAT:
        raise ValueError(f"format: expected {FORMAT!r}, got {doc.get('format')!r}")
    if doc.get("version") != VERSION:
        raise ValueError(f"version: expected {VERSION}, got {doc.get('version')!r}")
    for key in ("from_commit", "to_commit", "date", "entries"):
        if key not in doc:
            raise ValueError(f"missing field: {key}")

    def a_list(value: Any, where: str) -> list[Any]:
        if not isinstance(value, list):
            raise ValueError(f"{where} is not a list")
        return value

    def a_dict(value: Any, where: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{where} is not an object")
        return value

    def need(d: dict[str, Any], keys: tuple[str, ...], where: str) -> None:
        for k in keys:
            if k not in d:
                raise ValueError(f"{where} is missing {k}")

    entries: list[Entry] = []
    for i, raw in enumerate(a_list(doc["entries"], "entries")):
        where = f"entries[{i}]"
        raw = a_dict(raw, where)
        need(raw, ("id", "headline", "sentence", "elements"), where)
        edits: list[FieldEdit] = []
        for j, e in enumerate(a_list(raw.get("edits", []), f"{where}.edits")):
            e = a_dict(e, f"{where}.edits[{j}]")
            need(e, ("id", "key"), f"{where}.edits[{j}]")
            edits.append(FieldEdit(str(e["id"]), str(e["key"]), e.get("was"), e.get("now")))
        added: list[Addition] = []
        for j, a in enumerate(a_list(raw.get("added", []), f"{where}.added")):
            a = a_dict(a, f"{where}.added[{j}]")
            need(a, ("kind", "row"), f"{where}.added[{j}]")
            added.append(Addition(str(a["kind"]), dict(a_dict(a["row"], f"{where}.added[{j}].row"))))
        entries.append(Entry(str(raw["id"]), str(raw["headline"]), str(raw["sentence"]),
                             [str(x) for x in a_list(raw["elements"], f"{where}.elements")], edits, added,
                             [str(x) for x in a_list(raw.get("removed", []), f"{where}.removed")],
                             [str(x) for x in a_list(raw.get("evidence", []), f"{where}.evidence")],
                             str(raw.get("confidence") or "verified")))
    waived: list[Waiver] = []
    for i, w in enumerate(a_list(doc.get("waived", []), "waived")):
        w = a_dict(w, f"waived[{i}]")
        need(w, ("id",), f"waived[{i}]")
        waived.append(Waiver(str(w["id"]), str(w.get("why") or "")))
    return ChangeLog(str(doc["from_commit"]), str(doc["to_commit"]), str(doc["date"]), entries,
                     waived, str(doc.get("notes") or ""))


def dump_log(log: ChangeLog) -> str:
    doc: dict[str, Any] = {"format": FORMAT, "version": VERSION}
    doc.update(asdict(log))
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


# ── addressing boxes and fields in the raw map ────────────────────────────────────────────────────

FLOW_PREFIX = "flow:"
_STEP = re.compile(r"^([A-Za-z_][\w]*)(?:\[(?:(\d+)|([\w]+)=([^\]]*))\])?$")


def synthetic_id(array: str, row: dict[str, Any]) -> str | None:
    """The id a keyed row goes by: `glossary:<term>`, `run:<action>`, `config:<key>`… — the row's
    NAME field, the same spelling the impact engine mints, so a touched run command and a changed
    one are one box."""
    prefix = SYNTH_PREFIX.get(array)
    spec = KIND_OF.get(array)
    if not prefix or not spec:
        return None
    for f in spec.name:
        value = row.get(f)
        if isinstance(value, str) and value.strip():
            return f"{prefix}{value.strip()}"
    return None


def index_map(doc: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Every row a log can name, by id → (array, row): authored ids, a use case's flow under
    `flow:<UC>`, keyed rows under their synthetic id, and the map's own header under `map`."""
    out: dict[str, tuple[str, dict[str, Any]]] = {MAP_ID: (MAP_ID, doc)}
    for array, value in doc.items():
        if not isinstance(value, list):
            continue
        for row in value:
            if not isinstance(row, dict):
                continue
            rid = row.get("id")
            if isinstance(rid, str) and rid and array != "flows":
                out.setdefault(rid, (array, row))
            elif array == "flows" and isinstance(row.get("uc"), str):
                out[FLOW_PREFIX + row["uc"]] = (array, row)
            else:
                sid = synthetic_id(array, row)
                if sid:
                    out.setdefault(sid, (array, row))
    return out


def _walk(row: Any, key: str, create: bool = False) -> tuple[Any, str | int] | None:
    """The container and the final key/index a path names, or None when the path does not exist."""
    node: Any = row
    parts = key.split(".")
    for i, part in enumerate(parts):
        m = _STEP.match(part)
        if not m:
            raise ValueError(f"bad key path: {key!r}")
        name, idx, sel_key, sel_val = m.group(1), m.group(2), m.group(3), m.group(4)
        last = i == len(parts) - 1
        if not isinstance(node, dict):
            return None
        if idx is None and sel_key is None:
            if last:
                return node, name
            if name not in node:
                if not create:
                    return None
                node[name] = {}
            node = node[name]
            continue
        items = node.get(name)
        if not isinstance(items, list):
            return None
        if idx is not None:
            pos = int(idx)
        else:
            pos = next((k for k, it in enumerate(items)
                        if isinstance(it, dict) and str(it.get(sel_key)) == sel_val), -1)
        if last and create and idx is not None and pos == len(items):
            return items, pos                 # one past the end: the caller appends the item
        if pos < 0 or pos >= len(items):
            return None
        if last:
            return items, pos
        node = items[pos]
    return None


_INDEXED = re.compile(r"^(.*)\[(\d+)\]$")


def _append_slot(row: dict[str, Any], key: str) -> tuple[str, list[Any], int] | None:
    """When `key` ends in a positional index (`sites[2]`), the list it names in this row, as
    (list path, the list, the index); None for any other key or when the path is not a list."""
    m = _INDEXED.match(key)
    if not m:
        return None
    path, pos = m.group(1), int(m.group(2))
    hit = _walk(row, path)
    if hit is None:
        return None
    container, at = hit
    items = container[int(at)] if isinstance(container, list) else container.get(at)
    return (path, items, pos) if isinstance(items, list) else None


def get_field(row: dict[str, Any], key: str) -> Any:
    hit = _walk(row, key)
    if hit is None:
        return None
    container, at = hit
    if isinstance(container, list):
        return container[int(at)]
    return container.get(at)


def _put(container: Any, at: str | int, value: Any) -> None:
    """Write one resolved target: set it, append it (a list position at or past the end), or with
    `None` remove it."""
    if isinstance(container, list):
        pos = int(at)
        if value is None:
            del container[pos]
        elif pos >= len(container):
            container.append(value)
        else:
            container[pos] = value
    elif value is None:
        container.pop(at, None)
    else:
        container[at] = value


def set_field(row: dict[str, Any], key: str, value: Any) -> None:
    """Set a path to `value`; `None` removes the field (a list item is removed too). A positional
    index one past the end of a list appends the item — the one way to add a site, a step or a
    field row without rewriting the whole list. A path the row does not have is a ValueError in
    words: the bare `KeyError: 'sites[2]'` it used to raise reached the reader as the whole message."""
    hit = _walk(row, key, create=value is not None)
    if hit is None:
        raise ValueError(f"{key}: no such field or item")
    _put(hit[0], hit[1], value)


def _chain(row: dict[str, Any], key: str, ahead: int = 0) -> list[tuple[int, str | int]] | None:
    """The containers a key passes through, by identity, down to the field or item it names:
    `sites[1].why` → [(id(row), "sites"), (id(sites), 1), (id(site), "why")]. Two edits whose
    chains nest — one a prefix of the other — write into each other, whatever their spelling:
    `fields[1]` and `fields[name=size]` reach one item, a whole `sites` and `sites[1].why` the same
    words. A field not there yet continues with placeholders, so `store` and `store.notes` still
    nest; an append one past the end (`ahead` earlier appends counted) ends at the list and its
    position. None when the path cannot be resolved."""
    node: Any = row
    out: list[tuple[int, str | int]] = []
    parts = key.split(".")
    for i, part in enumerate(parts):
        m = _STEP.match(part)
        if not m:
            raise ValueError(f"bad key path: {key!r}")
        name, idx, sel_key, sel_val = m.group(1), m.group(2), m.group(3), m.group(4)
        last = i == len(parts) - 1
        if not isinstance(node, dict):
            return None
        out.append((id(node), name))
        if idx is None and sel_key is None:
            if last:
                return out
            if name not in node:
                out.extend((0, rest) for rest in parts[i + 1:])
                return out
            node = node[name]
            continue
        items = node.get(name)
        if not isinstance(items, list):
            return None
        if idx is not None:
            pos = int(idx)
        else:
            pos = next((k for k, it in enumerate(items)
                        if isinstance(it, dict) and str(it.get(sel_key)) == sel_val), -1)
        if pos < 0 or pos >= len(items):
            if last and idx is not None and pos == len(items) + ahead:
                out.append((id(items), pos))
                return out
            return None
        out.append((id(items), pos))
        if last:
            return out
        node = items[pos]
    return None


# ── lint: is the log well formed against this map? ───────────────────────────────────────────────

def _commit_matches(a: str | None, b: str | None) -> bool:
    """Two commit spellings name one commit when one is a prefix of the other (`-dirty` dropped)."""
    x, y = (a or "").removesuffix("-dirty"), (b or "").removesuffix("-dirty")
    return bool(x) and bool(y) and (x.startswith(y) or y.startswith(x))


def _addition_problem(a: Addition, doc: dict[str, Any], index: dict[str, tuple[str, dict[str, Any]]]) -> str | None:
    """Why this row cannot be added, or None. A box needs its id; a keyed row its key; a flow its
    use case; a counted-only row (tests, extras) or any other array of the map takes the row as is."""
    spec = KIND_OF.get(a.kind)
    rid = a.row.get("id")
    if spec is not None and spec.key is None:
        if not isinstance(rid, str) or not rid:
            return f"adds a row with no id to {a.kind}"
        if rid in index:
            return f"adds {rid}, which the map already has"
        return None
    if spec is not None and spec.key:
        missing = [k for k in spec.key if not a.row.get(k)]
        if missing:
            return f"adds a {spec.word} without its {', '.join(missing)}"
        sid = synthetic_id(a.kind, a.row)
        return f"adds {sid}, which the map already has" if sid and sid in index else None
    if spec is not None:
        return None                                   # counted only: no identity to clash on
    if a.kind == "flows":
        uc = a.row.get("uc")
        return None if isinstance(uc, str) and uc else "adds a flow without its use case (`uc`)"
    if isinstance(doc.get(a.kind), list):
        return None
    return f"adds a row to {a.kind!r}, which is not a map array"


def _added_ids(log: ChangeLog) -> set[str]:
    out: set[str] = set()
    for e in log.entries:
        for a in e.added:
            rid = a.row.get("id")
            if isinstance(rid, str) and rid:
                out.add(rid)
            elif a.kind == "flows" and isinstance(a.row.get("uc"), str):
                out.add(FLOW_PREFIX + a.row["uc"])
            else:
                sid = synthetic_id(a.kind, a.row)
                if sid:
                    out.add(sid)
    return out


def lint(log: ChangeLog, doc: dict[str, Any]) -> Problems:
    p = Problems()
    index = index_map(doc)
    added_ids = _added_ids(log)
    removed_ids = {r for e in log.entries for r in e.removed}
    prose: list[tuple[str, str, str]] = []   # (label, box, text) of every edit a reader will meet as words
    appends: dict[tuple[str, str], int] = {}  # (box, list path) → items this log has already appended
    chains: list[tuple[Entry, FieldEdit, list[tuple[int, str | int]]]] = []   # every edit's target, by identity
    removed_by: dict[str, str] = {}           # row id → the entry that removes it
    pin = doc.get("commit")
    if isinstance(pin, str) and pin and not _commit_matches(log.from_commit, pin):
        p.errors.append(f"the log starts from {log.from_commit}, the map is pinned to {pin}")
    seen: set[str] = set()
    seen_edits: dict[tuple[str, str], str] = {}
    for e in log.entries:
        where = f"entry {e.id}"
        if e.id in seen:
            p.errors.append(f"{where}: id used twice")
        seen.add(e.id)
        if not e.headline.strip():
            p.errors.append(f"{where}: empty headline")
        elif len(e.headline.split()) > HEADLINE_WORDS_MAX:
            p.warnings.append(f"{where}: headline is {len(e.headline.split())} words; keep it under {HEADLINE_WORDS_MAX}")
        if not e.sentence.strip():
            p.errors.append(f"{where}: empty sentence")
        if not e.elements:
            p.errors.append(f"{where}: names no box — an entry is about at least one")
        if e.confidence not in CONFIDENCE_WORDS:
            p.errors.append(f"{where}: confidence {e.confidence!r} is not one of {', '.join(CONFIDENCE_WORDS)}")
        for i in e.elements:
            if i not in index and i not in added_ids:
                p.errors.append(f"{where}: names {i}, which is not in the map and no entry adds it")
        for i in sorted(e.ids_edited() - set(e.elements)):
            p.errors.append(f"{where}: edits {i} without naming it among its boxes")
        for ed in e.edits:
            if (ed.id, ed.key) in seen_edits:
                p.errors.append(f"{where}: {ed.id}.{ed.key} is also edited by entry {seen_edits[(ed.id, ed.key)]}; one edit per field")
            seen_edits[(ed.id, ed.key)] = e.id
            if ed.id in added_ids:
                p.errors.append(f"{where}: edits {ed.id}, which this log adds — put the value in the added row")
                continue
            if ed.id in removed_ids:
                p.errors.append(f"{where}: edits {ed.id}, which an entry removes")
                continue
            hit = index.get(ed.id)
            if hit is None:
                p.errors.append(f"{where}: edits {ed.id}, which is not in the map")
                continue
            if ed.id == MAP_ID and ("[" in ed.key or "." in ed.key or ed.key in MAP_BOOKKEEPING
                                    or isinstance(doc.get(ed.key), (list, dict))):
                p.errors.append(f"{where}: `map` edits take one header field (title, goal…), not {ed.key}")
                continue
            try:
                found = _walk(hit[1], ed.key)
                current = get_field(hit[1], ed.key)
            except ValueError as exc:
                p.errors.append(f"{where}: {exc}")
                continue
            if found is None and ed.was is not None:
                p.errors.append(f"{where}: {ed.id}.{ed.key} — no such field or item in the map")
                continue
            ahead = 0
            if found is None:
                slot = _append_slot(hit[1], ed.key)
                if slot is not None:
                    path, items, pos = slot
                    ahead = appends.get((ed.id, path), 0)
                    if pos != len(items) + ahead:
                        p.errors.append(f"{where}: {ed.id}.{ed.key} — no such item in the map; the list has "
                                        f"{len(items)} item(s) and this log appends {ahead} before it, so "
                                        f"{path}[{len(items) + ahead}] is the index that appends")
                        continue
                    appends[(ed.id, path)] = ahead + 1
                elif _walk(json.loads(json.dumps(hit[1])), ed.key, create=True) is None:
                    indexed = _INDEXED.match(ed.key)
                    if indexed and not isinstance(get_field(hit[1], indexed.group(1)), list):
                        p.errors.append(f"{where}: {ed.id}.{ed.key} — {ed.id} has no `{indexed.group(1)}` list; "
                                        f"add it whole, as `{indexed.group(1)}` with `was: null`")
                    else:
                        p.errors.append(f"{where}: {ed.id}.{ed.key} — no such item in the map; a new item goes at "
                                        f"the index one past the end of its list, which appends it")
                    continue
            chain = _chain(hit[1], ed.key, ahead)
            if chain is not None:
                chains.append((e, ed, chain))
            if current != ed.was:
                p.errors.append(f"{where}: {ed.id}.{ed.key} — the map holds {json.dumps(current, ensure_ascii=False)[:80]}, "
                                f"the log says was {json.dumps(ed.was, ensure_ascii=False)[:80]}")
            if ed.was == ed.now:
                p.errors.append(f"{where}: {ed.id}.{ed.key} — was and now are the same")
            # The words a reader meets on the box's page face the map's own readability check.
            last = ed.key.split(".")[-1].split("[")[0]
            if isinstance(ed.now, str) and field_spec(last).cls == "wording":
                box = ed.id[len(FLOW_PREFIX):] if ed.id.startswith(FLOW_PREFIX) else ed.id
                prose.append((f"{where} {ed.id}.{ed.key}", box, ed.now))
        for a in e.added:
            problem = _addition_problem(a, doc, index)
            if problem:
                p.errors.append(f"{where}: {problem}")
        for rid in e.removed:
            if rid not in index:
                p.errors.append(f"{where}: removes {rid}, which is not in the map")
            elif rid in removed_by:
                p.errors.append(f"{where}: removes {rid}, which entry {removed_by[rid]} also removes")
            removed_by.setdefault(rid, e.id)
        for f in field_findings(f"{where} sentence", e.sentence):
            p.warnings.append(_finding_line(f))
    # Two edits whose targets nest write into each other: a whole list and one of its items, a
    # dict and a field in it, one item under two spellings (`fields[1]`, `fields[name=size]`), an
    # item and the removal that takes it out. One would land and vanish, or land on the wrong
    # words; both are refused, whatever the spelling and whatever `now` is.
    for i, (ea, eda, cha) in enumerate(chains):
        for eb, edb, chb in chains[i + 1:]:
            if eda.id != edb.id or eda.key == edb.key:
                continue
            if cha == chb:
                p.errors.append(f"entry {eb.id}: {edb.id}.{edb.key} names the same field or item as "
                                f"entry {ea.id}'s {eda.key}")
            elif chb[:len(cha)] == cha:
                p.errors.append(f"entry {eb.id}: edits {edb.id}.{edb.key}, inside {eda.key}, which entry "
                                f"{ea.id} {'removes' if eda.now is None else 'edits'}")
            elif cha[:len(chb)] == chb:
                p.errors.append(f"entry {ea.id}: edits {eda.id}.{eda.key}, inside {edb.key}, which entry "
                                f"{eb.id} {'removes' if edb.now is None else 'edits'}")
    for w in log.waived:
        if w.id not in index:
            p.warnings.append(f"waived {w.id} is not in the map")
        if not w.why.strip():
            p.errors.append(f"waived {w.id}: says no why")
    # The last check is the whole apply, on a copy, through the model's loader AND the validator's
    # blocking checks — so a row of an older shape, or a site that says `no_call_site` and carries a
    # `where`, is refused here with the field named, not by the close step after the write.
    model: ProjectModel | None = None
    if p.ok:
        try:
            new = _applied(log, doc)
        except ValueError as exc:
            p.errors.append(f"the log cannot be applied: {exc}")
            new = None
        try:
            model = load_model(json.dumps(new)) if new is not None else None
        except ModelError as exc:
            p.errors.append(f"the map would not load after apply: {exc}")
        if model is not None:
            problems, _warnings = validate_model(model, None, disclose_records=False)
            for problem in problems:
                p.errors.append(f"the map would not validate after apply: {problem}")
    p.warnings.extend(_prose_warnings(log, doc, model, prose))
    return p


def _finding_line(f: Finding) -> str:
    return f"{f.where}: {f.kind} — {f.detail}"


def _walk_box(where: str) -> str:
    """The box a label of the validator's field walk is about: its first word (`BR1 risk`,
    `UC1 step 2 phrase`), or the synthetic id of a glossary term (`glossary 'guild'`)."""
    if where.startswith("glossary '") and where.endswith("'"):
        return "glossary:" + where[len("glossary '"):-1]
    return where.split(" ", 1)[0]


def _prose_warnings(log: ChangeLog, doc: dict[str, Any], after: ProjectModel | None,
                    edits: list[tuple[str, str, str]]) -> list[str]:
    """The readability check over every reader-facing sentence the log puts in the map that was not
    there before — an edit's new words, an added rule's risk, a new way in's trigger, a new step's
    phrase — through the SAME field walk `validate` reads at the close step, so the advice arrives
    before the write and not first from the validator after it. A sentence the map already held is
    not judged again. An edited wording field the walk does not read (a name, a title, an arrow's
    why) is judged from the edit itself; one the walk reads is judged once, by the walk. A finding on
    a walked field is named by the entry that owns the box. `after` is None when the applied map did
    not load: then only the edits are judged."""
    out: list[str] = []
    walked: set[tuple[str, str]] = set()
    if after is not None:
        try:
            held: set[tuple[str, str]] | None = set(iter_prose_fields(load_model(json.dumps(doc))))
        except ModelError:
            held = None          # the map before the log does not load: judge the log's own boxes only
        owner: dict[str, str] = {}
        for e in log.entries:
            for i in set(e.elements) | e.ids_edited():
                owner.setdefault(i, e.id)
        terms = [g.term for g in after.glossary]
        for where, text in iter_prose_fields(after):
            box = _walk_box(where)
            walked.add((box, text))
            if (held is not None and (where, text) in held) or (held is None and box not in owner):
                continue
            label = f"entry {owner[box]} {where}" if box in owner else where
            out.extend(_finding_line(f) for f in field_findings(label, text, terms=terms))
    for label, box, text in edits:
        if (box, text) in walked:
            continue
        out.extend(_finding_line(f) for f in field_findings(label, text))
    return out


# ── apply: the entries written into the map ──────────────────────────────────────────────────────

@dataclass
class Applied:
    edits: int = 0
    added: int = 0
    removed: int = 0


def _applied(log: ChangeLog, doc: dict[str, Any], done: Applied | None = None) -> dict[str, Any]:
    """A copy of the map with every entry written in — no checks; `apply` and `lint` both run it.
    Every address in the log is read in the frame of the map as it was: each edit's target is
    resolved on the copy, by object identity, BEFORE anything is written, so the order edits land
    in cannot change what a later one names — a selector (`steps[n=2]`) still finds its step after
    another edit renumbered it, and a removal in one entry never shifts what an index in another
    names (the first version ordered removals last within each entry only, and an edit in a later
    entry landed on the shifted list). Then the sets land in log order (a second append on one
    list after the first) and the removals (`now: null`) last, each list's from the highest index
    down. Lint refuses the pairs that would still collide: nested targets. Raises ValueError for a
    path the map does not have."""
    new = json.loads(json.dumps(doc))
    index = index_map(new)
    done = done or Applied()
    sets: list[tuple[Any, str | int, Any]] = []
    drops: list[tuple[Any, str | int]] = []
    for e in log.entries:
        for ed in e.edits:
            row = index[ed.id][1]
            slot = _append_slot(row, ed.key) if ed.now is not None else None
            if slot is not None and slot[2] >= len(slot[1]):
                sets.append((slot[1], slot[2], ed.now))      # an append: the end of the list, in log order
                continue
            hit = _walk(row, ed.key, create=ed.now is not None)
            if hit is None:
                raise ValueError(f"{ed.id}.{ed.key}: no such field or item")
            if ed.now is None:
                drops.append(hit)
            else:
                sets.append((hit[0], hit[1], ed.now))
        for a in e.added:
            rows = new.setdefault(a.kind, [])
            rows.append(json.loads(json.dumps(a.row)))
            done.added += 1
        for rid in e.removed:
            array, row = index[rid]
            new[array] = [r for r in new[array] if r is not row]
            done.removed += 1
    for container, at, value in sets:
        _put(container, at, value)
        done.edits += 1
    for container, at in sorted(drops, key=lambda d: -(d[1] if isinstance(d[1], int) else -1)):
        _put(container, at, None)
        done.edits += 1
    new["commit"] = log.to_commit
    return new


def apply(log: ChangeLog, doc: dict[str, Any], to_date: str | None = None) -> tuple[dict[str, Any], Applied]:
    """A copy of the map with every entry applied, and the pin bumped to the log's `to_commit`.
    Refuses (ValueError) when the log does not lint clean against this map — a stale `was` would
    silently overwrite someone else's change, and a row of the wrong shape would leave a map that
    does not load."""
    problems = lint(log, doc)
    if not problems.ok:
        raise ValueError("the log does not fit this map:\n  " + "\n  ".join(problems.errors))
    done = Applied()
    new = _applied(log, doc, done)
    if to_date:
        new["committed"] = to_date
    return new, done


# ── check: the completeness gate ─────────────────────────────────────────────────────────────────

_SYNTH = re.compile(r"^(step|rule|edge|ep|security|glossary|net|run):(.*)$")


def element_of(eid: str) -> str | None:
    """The box a hit lands on: a step's use case or sub-flow, a site's rule, an arrow's source;
    None for the anchors that belong to no box (a way in, a glossary term, a run command)."""
    m = _SYNTH.match(eid)
    if not m:
        return eid
    kind, rest = m.group(1), m.group(2)
    if kind in ("step", "rule"):
        return rest.split(":", 1)[0]
    if kind == "edge":
        return rest.split(">", 1)[0]
    return None


def gated_box(eid: str, imp: Any) -> str | None:
    """The box the gate counts this `coyomap impact` hit under, or None: a direct hit at line or
    symbol resolution, or any link into a deleted file — never a drift, never the file rung (which
    lights every anchor in a changed file), and never an anchor that belongs to no box. ONE
    predicate: `check --touched` reads it and `coyomap impact` marks the same hits in its text, so
    the agent reads the list the gate will count."""
    if not isinstance(imp, dict) or imp.get("cause") != "direct":
        return None
    if imp.get("change") == "drifted":
        return None
    if imp.get("change") != "deleted" and imp.get("resolution") not in ("line", "symbol"):
        return None
    return element_of(eid)


def touched_ids(impact: dict[str, Any]) -> set[str]:
    """The boxes a code diff touched, read off `coyomap impact --json` through `gated_box`."""
    out: set[str] = set()
    for eid, imp in (impact.get("impacts") or {}).items():
        box = gated_box(str(eid), imp)
        if box:
            out.add(box)
    return out


def check(log: ChangeLog, old_doc: dict[str, Any], new_doc: dict[str, Any],
          impact: dict[str, Any] | None = None) -> Problems:
    """The two-way rule between the log and the map's own change.
    Errors: a box the map diff says changed (wording or structure) that no entry names and no
    waiver covers — a keyed row (a glossary term, a run command…) counts under its synthetic id and
    the map's header under `map`; a box an entry names that the new map does not hold; a `to_commit`
    that is not the new map's pin. Warnings: a box the code touched that nobody names or waives, and
    a waiver on a box that did not change — nor, when `--touched` is given, was touched."""
    p = Problems()
    new_pin = new_doc.get("commit")
    if isinstance(new_pin, str) and new_pin and not _commit_matches(log.to_commit, new_pin):
        p.errors.append(f"the log ends at {log.to_commit}, the new map is pinned to {new_pin}")
    delta = diff_maps(old_doc, new_doc)
    changed: dict[str, str] = {}
    for e in delta.elements:
        if e.change == "modified" and e.classes == ["link"]:
            continue
        box = e.id_new or e.id_old
        if not box:
            name = e.name_new or e.name_old
            box = f"{SYNTH_PREFIX[e.kind]}{name}" if e.kind in SYNTH_PREFIX and name else None
        if box:
            # A keyed row that came and went under one name (a run command whose command line
            # changed) is one box, modified.
            changed[box] = "modified" if box in changed and changed[box] != e.change else e.change
    for a in delta.arrows:
        if a.change != "modified" or a.classes != ["link"]:
            changed.setdefault(a.src, f"an arrow {a.change}")
    header = [k for k in set(old_doc) | set(new_doc)
              if k not in MAP_BOOKKEEPING and not isinstance(old_doc.get(k, new_doc.get(k)), (list, dict))
              and old_doc.get(k) != new_doc.get(k)]
    if header:
        changed[MAP_ID] = "modified (" + ", ".join(sorted(header)) + ")"
    named = log.named()
    waived = {w.id for w in log.waived}
    for box, what in sorted(changed.items()):
        if box not in named and box not in waived:
            p.errors.append(f"{box} {what} in the map, and no entry names it")
    new_index = index_map(new_doc)
    removed = {r for e in log.entries for r in e.removed}
    for box in sorted(named):
        if box not in new_index and box not in removed:
            p.errors.append(f"an entry names {box}, which the new map does not hold")
    touched = touched_ids(impact) if impact is not None else set()
    for w in log.waived:
        if w.id not in changed and w.id not in touched:
            p.warnings.append(f"waived {w.id} did not change in the map"
                              + (" and the code did not touch it" if impact is not None else ""))
    for box in sorted(touched - named - waived):
        p.warnings.append(f"the code touched {box} and no entry names or waives it")
    return p


def check_before_write(log: ChangeLog, doc: dict[str, Any],
                       impact: dict[str, Any] | None = None) -> Problems:
    """The same gate BEFORE the write: the log applied to a copy of the map in memory, and `check`
    between the map as it is and that copy. Lint's errors come first, because the apply assumes a
    log that fits; its warnings are lint's own to print. A gap here costs a trip back to the log and
    nothing else — the map on disk has not moved."""
    fit = lint(log, doc)
    if not fit.ok:
        return Problems(errors=[f"lint: {e}" for e in fit.errors])
    return check(log, doc, _applied(log, doc), impact)


# ── render: the log for people ────────────────────────────────────────────────────────────────────

def _names(doc: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {MAP_ID: "the map"}
    for rid, (array, row) in index_map(doc).items():
        if rid == MAP_ID:
            continue
        spec = KIND_OF.get(array)
        for f in (spec.name if spec else ()) or ("name",):
            v = row.get(f)
            if isinstance(v, str) and v.strip():
                out[rid] = v.strip()
                break
    return out


def _row_name(kind: str, row: dict[str, Any]) -> str | None:
    spec = KIND_OF.get(kind)
    for f in (spec.name if spec else ()) or ("name",):
        v = row.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _group_of(rid: str, doc_index: dict[str, tuple[str, dict[str, Any]]], added_kind: dict[str, str]) -> str:
    array = added_kind.get(rid) or (doc_index[rid][0] if rid in doc_index else "")
    if rid.startswith(FLOW_PREFIX):
        array = "use_cases"
    spec = KIND_OF.get(array)
    return spec.group if spec else "hood"


def _text(v: Any, names: dict[str, str] | None = None) -> str:
    if v is None:
        return "—"
    if isinstance(v, str):
        return (names or {}).get(v, v)
    if isinstance(v, list):
        return ", ".join(_text(x, names) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_text(x, names)}" for k, x in v.items())
    return json.dumps(v, ensure_ascii=False)


def _edit_text(ed: FieldEdit, names: dict[str, str]) -> str:
    """One edit as a reader reads it: a list by what came and went, by name; anything else as
    was → now. Never an id: a way in reads by its trigger, a box by its name."""
    if isinstance(ed.was, list) or isinstance(ed.now, list):
        was = [_text(x, names) for x in (ed.was if isinstance(ed.was, list) else [])]
        now = [_text(x, names) for x in (ed.now if isinstance(ed.now, list) else [])]
        bits = [f"+ {x}" for x in now if x not in was] + [f"− {x}" for x in was if x not in now]
        return "; ".join(bits) if bits else "reordered"
    return f"{_text(ed.was, names)} → {_text(ed.now, names)}"


def _edit_label(key: str) -> str:
    """`steps[n=3].where` reads as `step 3 · Code link`; `sites[0].where` as `Enforced at`."""
    parts = key.split(".")
    head = parts[0].split("[")[0]
    sel = parts[0][len(head):]
    last = parts[-1].split("[")[0]
    label = field_spec(last).label
    if head == "steps" and sel.startswith("[n="):
        return f"step {sel[3:-1]} · {label}"
    if len(parts) > 1 and head != last:
        return f"{field_spec(head).label} · {label}"
    return label


def render(log: ChangeLog, doc: dict[str, Any]) -> str:
    """Markdown: the header, then each entry under the group its boxes belong to (Product first),
    with its boxes by name and its edits as label: was → now. An entry whose boxes span both groups
    appears under both."""
    names = _names(doc)
    for rid in list(names):
        names.setdefault(FLOW_PREFIX + rid, names[rid])   # a flow reads by its use case's name
    index = index_map(doc)
    added_kind: dict[str, str] = {}
    for e in log.entries:
        for a in e.added:
            rid = a.row.get("id") if isinstance(a.row.get("id"), str) else synthetic_id(a.kind, a.row)
            if rid:
                added_kind[rid] = a.kind
    for e in log.entries:
        for a in e.added:
            rid = a.row.get("id") if isinstance(a.row.get("id"), str) else synthetic_id(a.kind, a.row)
            name = _row_name(a.kind, a.row)
            if rid and name:
                names.setdefault(rid, name)
    lines = [f"# What changed: {log.from_commit[:10]} → {log.to_commit[:10]} ({log.date})", ""]
    n_add = sum(len(e.added) for e in log.entries)
    n_rem = sum(len(e.removed) for e in log.entries)
    n_edit = sum(len(e.edits) for e in log.entries)
    def count(n: int, one: str, many: str) -> str:
        return f"{n} {one if n == 1 else many}"
    lines.append(f"{count(len(log.entries), 'entry', 'entries')} · {count(n_add, 'box', 'boxes')} added · "
                 f"{n_rem} removed · {count(n_edit, 'field', 'fields')} edited"
                 + (f" · {len(log.waived)} touched without a change of meaning" if log.waived else ""))
    # An entry is told in full once, under the first group it touches; under the other group it is
    # a headline and the boxes of that group, so a reader of Under the hood still sees it.
    told: set[str] = set()
    for group, heading in (("product", "Product"), ("hood", "Under the hood")):
        section: list[str] = []
        for e in log.entries:
            here = [i for i in e.elements if _group_of(i, index, added_kind) == group]
            if not here:
                continue
            box = lambda i: f"{names.get(i, i)}" + (" (new)" if i in added_kind else "") + (" (removed)" if i in e.removed else "")
            if e.id in told:
                section += ["", f"### {e.headline}", "", "Also here: " + ", ".join(box(i) for i in here)]
                continue
            told.add(e.id)
            section += ["", f"### {e.headline}", "", e.sentence, ""]
            section.append("Boxes: " + ", ".join(box(i) for i in e.elements))
            for ed in e.edits:
                section.append(f"- {names.get(ed.id, ed.id)} · {_edit_label(ed.key)}: {_edit_text(ed, names)}")
            if e.evidence:
                section.append("- Evidence: " + ", ".join(f"`{f}`" for f in e.evidence))
            if e.confidence != "verified":
                section.append(f"- Confidence: {e.confidence}")
        if section:
            lines += ["", f"## {heading}", *section]
    if log.waived:
        lines += ["", "## Touched by the code, no change of meaning", ""]
        lines += [f"- {names.get(w.id, w.id)}: {w.why}" for w in log.waived]
    if log.notes.strip():
        lines += ["", "## Notes", "", log.notes.strip()]
    return "\n".join(lines) + "\n"


# ── the command ───────────────────────────────────────────────────────────────────────────────────

def _read_map(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not looks_like_map(doc):
        raise ValueError(f"{path}: not a map")
    return doc


def _opt(args: list[str], name: str) -> str | None:
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args) or args[i + 1].startswith("--"):
            raise ValueError(f"{name} needs a value")
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if args else 2
    verb = args[0]
    rest = args[1:]
    if verb not in ("lint", "render", "apply", "check"):
        print(f"ERROR: unknown verb '{verb}'\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    helped = subverb_help.handle(USAGE, verb, rest)
    if helped is not None:
        return helped
    try:
        as_json = "--json" in rest
        if as_json:
            rest.remove("--json")
        map_opt = _opt(rest, "--map")
        old_opt = _opt(rest, "--old")
        new_opt = _opt(rest, "--new")
        out_opt = _opt(rest, "--out")
        touched_opt = _opt(rest, "--touched")
        date_opt = _opt(rest, "--date")
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    bad = [a for a in rest if a.startswith("-")]
    if bad:
        print(f"ERROR: unknown option '{bad[0]}'\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    if len(rest) != 1:
        print("ERROR: give exactly one log path\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    log_path = Path(rest[0])
    try:
        log = load_log(log_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"ERROR: {log_path}: {e}", file=sys.stderr)
        return 2
    try:
        if verb == "check":
            if map_opt and (old_opt or new_opt):
                print("ERROR: check takes --map <map> (before the write) or --old <map> --new <map> "
                      "(after it), not both", file=sys.stderr)
                return 2
            if not map_opt and not (old_opt and new_opt):
                print("ERROR: check needs --map <map> (before the write) or --old <map> --new <map> "
                      "(after it)", file=sys.stderr)
                return 2
            impact = json.loads(Path(touched_opt).read_text(encoding="utf-8")) if touched_opt else None
            if map_opt:
                p = check_before_write(log, _read_map(Path(map_opt)), impact)
            else:
                p = check(log, _read_map(Path(old_opt or "")), _read_map(Path(new_opt or "")), impact)
            if as_json:
                print(json.dumps({"kind": "coyomap-changes-check", "ok": p.ok, "errors": p.errors,
                                  "warnings": p.warnings}, indent=2, ensure_ascii=False))
            else:
                for w in p.warnings:
                    print(f"warning: {w}")
                for e in p.errors:
                    print(f"error: {e}")
                if p.ok:
                    print("check: the log explains every change in the map")
                elif any(e.startswith("lint: ") for e in p.errors):
                    print("check: the log does not fit the map; lint's errors come first")
                else:
                    print(f"check: {len(p.errors)} gap(s) between the log and the map")
            return 0 if p.ok else 1
        if not map_opt:
            print(f"ERROR: {verb} needs --map <map>", file=sys.stderr)
            return 2
        doc = _read_map(Path(map_opt))
        if verb == "lint":
            p = lint(log, doc)
            for w in p.warnings:
                print(f"warning: {w}")
            for e in p.errors:
                print(f"error: {e}")
            print(f"lint: {len(log.entries)} entries, {len(p.errors)} error(s), {len(p.warnings)} warning(s)")
            return 0 if p.ok else 1
        if verb == "render":
            text = render(log, doc)
            if out_opt:
                Path(out_opt).write_text(text, encoding="utf-8")
                print(f"wrote {out_opt}")
            else:
                print(text, end="")
            return 0
        new_doc, done = apply(log, doc, date_opt)
        target = Path(out_opt) if out_opt else Path(map_opt)
        target.write_text(json.dumps(new_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"applied {len(log.entries)} entries to {target}: {done.edits} fields edited, "
              f"{done.added} boxes added, {done.removed} removed; pin → {log.to_commit[:10]}")
        return 0
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except KeyError as e:
        # Nothing here should raise one any more (a missing path is a ValueError in words); if one
        # does, the reader still gets a sentence and not the bare quoted key.
        print(f"ERROR: the log names {e.args[0] if e.args else e!r}, which the map does not hold", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
