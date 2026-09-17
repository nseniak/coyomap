#!/usr/bin/env python3
"""What changed between two maps, as a reader would ask it.

ONE ENGINE, THREE READERS. `diff_maps` turns two maps into one change document (`MapDelta`), and
three renderers read it: `to_text` for the building agent (ids, terse, the line shapes the method
quotes), `to_markdown` for people (names and words, pasteable into a PR), and `to_json` for the
viewer's change mode (the Changes tabs, the badges, the "What changed" block on a box's page).

WHAT THE OLD ENGINE GOT WRONG, and this one does not:
  * a use case's steps were counted, never compared — a changed step was invisible. Here the two
    step lists are ALIGNED like lines of text (same actor, target and phrase = the same step), so an
    inserted step reads as one addition and the steps after it as renumbered, not as changed.
  * an arrow was keyed by its code line, so a line shift read as removed plus added. Here an arrow
    is keyed by its two ends and its verb; the line is a detail, and a moved line is a moved code
    link. Two arrows with the same ends at two call sites stay two rows: within one triple, rows
    pair by their call site (exact, then same file, then position), so `dedup-edge`'s pairs survive.
  * a box was matched by id only, so a box that kept its name under a new id read as removed plus
    added. Here the rows left over after the id pass pair by name, then by code file, and are
    reported as the same box under a new id (`reidentified`).
  * the output was ids and field keys. The text form still is, for the agent; the markdown and the
    JSON carry names, reader labels and the changed words.

CHANGE CLASSES. Every changed field is one of three: `wording` (a sentence moved), `structure` (a
relation, a list, a kind, a step), `link` (a code anchor or a confidence mark). The viewer filters on
them, and the count line separates boxes that only moved in the code from boxes that changed.

SCOPE. Two maps of the same lineage: an old map and the one made from it by an accept or a hand fix.
Two independent builds of one repo do not agree on ids or wording — measured on two builds one day
apart, 11 use cases shared an id and 1 of them kept its name — so `diff_maps` measures that and
warns when the maps look like separate builds. The rows are still reported: name and code-file
matching recover the records and components (63 of 74 records matched by name on the same pair),
which is more than nothing, and the warning says how much to trust the rest.

Works on the RAW parsed JSON, not the typed model, so a map an older coyomap wrote still compares as
far as its fields overlap — the point of comparing with a map out of git history. A field the model
does not know is still compared; that is where a hand-written extra would otherwise go quiet.

Stdlib-only.
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from coyomap.model import ID_ARRAYS

USAGE = """usage: coyomap diff <old-map> <new-map> [--json | --md] [--only <array>]

What changed between two maps: boxes ADDED, REMOVED and MODIFIED, with the fields that moved; a use
case's steps aligned (added / removed / reworded / renumbered); arrows by their ends. Read-only.

  --json          the whole change document as data — parse this, never the text
  --md            the same, for people: names, reader labels, the changed words
  --only <array>  restrict to one array (rules, components, edges, use_cases, …)

Line shapes of the text form:  - removed   + added   ~ modified [fields]   ≈ code links only [fields]
                               ⇒ old-id → new-id  the same box under a new id   ! identity held twice

SCOPE: two maps of the same lineage — an old map and the one made from it. Two independent builds
do not agree on ids or wording; the report says so when the maps look like that.
"""

ChangeClass = Literal["wording", "structure", "link"]
Change = Literal["added", "removed", "modified"]
Group = Literal["product", "hood"]

CLASS_ORDER: tuple[ChangeClass, ...] = ("wording", "structure", "link")


# ── what each array IS, for the reader ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class KindSpec:
    """One map array as the reader meets it: its word, which group tab lists it, how its rows are
    identified, and which fields carry its name and its one sentence."""
    array: str
    word: str
    plural: str
    group: Group
    #: How rows are matched. None = by the authored `id`; a tuple of fields = by their content;
    #: an empty tuple = no identity worth pairing on, counted only.
    key: tuple[str, ...] | None
    name: tuple[str, ...]
    sentence: tuple[str, ...]


KINDS: list[KindSpec] = [
    # Product — the map's own reading order: the ways in first, then the edge of the product.
    KindSpec("capabilities", "feature", "features", "product", None, ("name",), ("purpose",)),
    KindSpec("use_cases", "use case", "use cases", "product", None, ("name",), ("trigger_outcome",)),
    KindSpec("happy_path", "happy path step", "happy path steps", "product", None, (), ("why",)),
    KindSpec("subflows", "shared sub-flow", "shared sub-flows", "product", None, ("name",), ()),
    KindSpec("roles", "actor", "actors", "product", None, ("name",), ("wants",)),
    KindSpec("rules", "rule", "rules", "product", None, ("name", "statement"), ("statement",)),
    KindSpec("blocks", "decision area", "decision areas", "product", None, ("name",), ("purpose",)),
    KindSpec("interfaces", "interface", "interfaces", "product", None, ("name",), ("what",)),
    # A way in is keyed by WHAT it is (its trigger, its component, its kind), not by where its code
    # is: a package rename moved every anchor on a live map, and 97 of 97 ways in read as replaced.
    # Its anchor pairs the rows that share a key, the way an arrow's call site does.
    KindSpec("entry_points", "way in", "ways in", "product", ("trigger", "component", "kind"), ("trigger",), ()),
    KindSpec("entities", "record", "records", "product", None, ("name",), ("meaning",)),
    KindSpec("subdomains", "data area", "data areas", "product", None, ("name",), ("purpose",)),
    KindSpec("glossary", "glossary term", "glossary terms", "product", ("term",), ("term",), ("meaning",)),
    # Under the hood.
    KindSpec("subsystems", "subsystem", "subsystems", "hood", None, ("name",), ("purpose",)),
    KindSpec("components", "component", "components", "hood", None, ("name",), ("purpose",)),
    KindSpec("deps", "dependency", "dependencies", "hood", None, ("name",), ("used_for",)),
    KindSpec("edges", "arrow", "arrows", "hood", ("src", "verb", "dst"), (), ("why",)),
    KindSpec("deployment", "deployment unit", "deployment units", "hood", ("unit",), ("unit",), ()),
    KindSpec("config", "config key", "config keys", "hood", ("key",), ("key",), ("purpose",)),
    KindSpec("observability", "signal", "signals", "hood", ("signal",), ("signal",), ()),
    KindSpec("non_entity_types", "other type", "other types", "hood", ("name",), ("name",), ("why",)),
    KindSpec("run_commands", "run command", "run commands", "hood", ("command",), ("command",), ("action",)),
    KindSpec("tests", "test group", "test groups", "hood", (), ("label",), ()),
    KindSpec("extras", "extra section", "extra sections", "hood", (), ("heading",), ()),
]
KIND_OF: dict[str, KindSpec] = {k.array: k for k in KINDS}

#: A use case's flow is not a kind of its own: its steps are the use case's steps, and its changes
#: land on the use case's row. Keyed by the use case it belongs to.
FLOWS = "flows"


# ── what each field IS: its reader label and its change class ──────────────────────────────────────

@dataclass(frozen=True)
class FieldSpec:
    label: str
    cls: ChangeClass


FIELDS: dict[str, FieldSpec] = {
    # wording — a sentence the reader meets
    "name": FieldSpec("Name", "wording"),
    "title": FieldSpec("Title", "wording"),
    "term": FieldSpec("Term", "wording"),
    "purpose": FieldSpec("Purpose", "wording"),
    "meaning": FieldSpec("Meaning", "wording"),
    "statement": FieldSpec("Statement", "wording"),
    "what": FieldSpec("What", "wording"),
    "trigger_outcome": FieldSpec("Trigger → Outcome", "wording"),
    "wants": FieldSpec("Wants", "wording"),
    "story": FieldSpec("Story", "wording"),
    "stakes": FieldSpec("Stakes", "wording"),
    "why": FieldSpec("Why", "wording"),
    "phrase": FieldSpec("Phrase", "wording"),
    "note": FieldSpec("Note", "wording"),
    "used_for": FieldSpec("Used for", "wording"),
    "alternative": FieldSpec("Alternative", "wording"),
    "tech": FieldSpec("Tech", "wording"),
    "action": FieldSpec("Action", "wording"),
    "gap": FieldSpec("Gap", "wording"),
    "aliases": FieldSpec("Aliases", "wording"),
    "body": FieldSpec("Body", "wording"),
    "heading": FieldSpec("Heading", "wording"),
    # structure — what the box is joined to, or what kind of thing it is
    "actors": FieldSpec("Actors", "structure"),
    "capability": FieldSpec("Feature", "structure"),
    "entry_points": FieldSpec("Ways in", "structure"),
    "ways_in": FieldSpec("Ways in", "structure"),
    "subsystem": FieldSpec("Subsystem", "structure"),
    "parent": FieldSpec("Parent", "structure"),
    "depends_on": FieldSpec("Depends on", "structure"),
    "runs_in": FieldSpec("Runs in", "structure"),
    "states": FieldSpec("States", "structure"),
    "fields": FieldSpec("Fields", "structure"),
    "relations": FieldSpec("Relations", "structure"),
    "owners": FieldSpec("Owners", "structure"),
    "store": FieldSpec("Store", "structure"),
    "subdomain": FieldSpec("Data area", "structure"),
    "kind": FieldSpec("Kind", "structure"),
    "type": FieldSpec("Type", "structure"),
    "facing": FieldSpec("Facing", "structure"),
    "side": FieldSpec("Side", "structure"),
    "access": FieldSpec("Access", "structure"),
    "risk": FieldSpec("Risk", "structure"),
    "block": FieldSpec("Decision area", "structure"),
    "package": FieldSpec("Package", "structure"),
    "bucket": FieldSpec("Bucket", "structure"),
    "interfaces": FieldSpec("Interfaces", "structure"),
    "deployment_linked": FieldSpec("Deployment linked", "structure"),
    "not_an_interface": FieldSpec("Not an interface", "structure"),
    "happy_path": FieldSpec("Happy path", "structure"),
    "direction": FieldSpec("Direction", "structure"),
    "subflow": FieldSpec("Sub-flow", "structure"),
    "src": FieldSpec("From", "structure"),
    "dst": FieldSpec("To", "structure"),
    "uc": FieldSpec("Use case", "structure"),
    "drives": FieldSpec("Drives", "structure"),
    "audience": FieldSpec("Audience", "structure"),
    "trigger": FieldSpec("Trigger", "structure"),
    "component": FieldSpec("Component", "structure"),
    "activation": FieldSpec("Activation", "structure"),
    "cadence": FieldSpec("Cadence", "structure"),
    "variants": FieldSpec("Variants", "structure"),
    "exposed_as": FieldSpec("Exposed as", "structure"),
    "runs_on": FieldSpec("Runs on", "structure"),
    "unit": FieldSpec("Unit", "structure"),
    "per_env": FieldSpec("Per environment", "structure"),
    "default": FieldSpec("Default", "structure"),
    "key": FieldSpec("Key", "structure"),
    "signal": FieldSpec("Signal", "structure"),
    "alerts": FieldSpec("Alerts", "structure"),
    "targets": FieldSpec("Targets", "structure"),
    "tested": FieldSpec("Tested", "structure"),
    "tests": FieldSpec("Tests", "structure"),
    "label": FieldSpec("Label", "structure"),
    "command": FieldSpec("Command", "structure"),
    "no_autolink": FieldSpec("No auto-link", "structure"),
    "extra": FieldSpec("Extra", "structure"),
    "verb": FieldSpec("Verb", "structure"),
    "n": FieldSpec("Number", "structure"),
    # link — a code anchor or a bookkeeping mark
    "source": FieldSpec("Code link", "link"),
    "where": FieldSpec("Code link", "link"),
    "evidence": FieldSpec("Evidence", "link"),
    "files": FieldSpec("Files", "link"),
    "sites": FieldSpec("Enforced at", "link"),
    "tech_source": FieldSpec("Tech code link", "link"),
    "where_configured": FieldSpec("Configured at", "link"),
    "where_emitted": FieldSpec("Emitted at", "link"),
    "where_viewed": FieldSpec("Viewed at", "link"),
    "config_source": FieldSpec("Config code link", "link"),
    "cadence_source": FieldSpec("Cadence code link", "link"),
    "confidence": FieldSpec("Confidence", "link"),
    "no_call_site": FieldSpec("No call site", "link"),
    "entry_point": FieldSpec("Code link", "link"),   # the pre-2026-09-14 name of a component's `source`
}


def field_spec(key: str) -> FieldSpec:
    """The reader label and class of a field, with a plain fallback for a field this table does not
    know: its key with the underscores taken out, filed as structure."""
    return FIELDS.get(key) or FieldSpec(key.replace("_", " ").capitalize(), "structure")


# ── the change document ────────────────────────────────────────────────────────────────────────────

@dataclass
class Span:
    """One run of a sentence: kept (`eq`), taken out (`del`) or put in (`ins`)."""
    op: Literal["eq", "del", "ins"]
    text: str


@dataclass
class FieldDelta:
    key: str
    label: str
    cls: ChangeClass
    old: str | None            # display text on each side; None = the field is absent there
    new: str | None
    spans: list[Span] = field(default_factory=list)      # word runs, wording strings only
    added: list[str] = field(default_factory=list)       # list-valued fields: items that came
    removed: list[str] = field(default_factory=list)     # … and items that went


@dataclass
class StepDelta:
    """One step of a use case or a shared sub-flow, as the alignment saw it. Kept steps are not
    emitted; a step that only got a new number is `renumbered`."""
    state: Literal["added", "removed", "modified", "renumbered"]
    n_old: int | None
    n_new: int | None
    phrase_old: str | None
    phrase_new: str | None
    src: str | None            # the step's ends, new-side ids (old-side for a removed step)
    dst: str | None
    spans: list[Span] = field(default_factory=list)
    fields: list[FieldDelta] = field(default_factory=list)
    #: The shared sub-flow this step runs, by name — such a step has no phrase of its own.
    subflow: str | None = None
    #: The change classes this step carries: `structure` for a step come, gone or renumbered,
    #: `wording` for a reworded phrase, and its fields' own classes — so a step whose only change is
    #: a moved code line is a `link` change, hidden and counted like any other.
    classes: list[ChangeClass] = field(default_factory=list)


@dataclass
class ElementDelta:
    kind: str                  # the array name
    change: Change
    id_old: str | None
    id_new: str | None
    name_old: str | None
    name_new: str | None
    reidentified: bool         # paired by name or code file under a different id
    classes: list[ChangeClass]
    fields: list[FieldDelta]
    steps: list[StepDelta]
    summary: str               # one phrase for the card
    sentence_old: str | None   # the old card's sentence, for a removed box and for context
    sentence_new: str | None
    source_old: str | None     # the card's code link on each side
    source_new: str | None

    @property
    def key(self) -> str:
        return self.id_new or self.id_old or self.name_new or self.name_old or "?"


@dataclass
class ArrowDelta:
    change: Change
    src: str
    verb: str
    dst: str
    classes: list[ChangeClass]
    fields: list[FieldDelta]
    summary: str
    where_old: str | None
    where_new: str | None


@dataclass
class KindCount:
    kind: str
    before: int
    after: int
    added: int = 0
    removed: int = 0
    modified: int = 0          # wording or structure moved
    link_only: int = 0         # only code links or bookkeeping moved
    collisions: list[str] = field(default_factory=list)   # identities held by more than one row

    @property
    def quiet(self) -> bool:
        return not (self.added or self.removed or self.modified or self.link_only
                    or self.collisions or self.before != self.after)


@dataclass
class MapDelta:
    old_label: str
    new_label: str
    elements: list[ElementDelta]
    arrows: list[ArrowDelta]
    counts: list[KindCount]
    warnings: list[str]
    idmap: dict[str, str]      # old id → new id, for the boxes re-identified


# ── small readers over raw rows ────────────────────────────────────────────────────────────────────

_ID_TOKEN = re.compile(r"\b(?:%s|EP)\d+\b" % "|".join(sorted(set(ID_ARRAYS.values()), key=len, reverse=True)))
_ANCHOR_TAIL = re.compile(r"(?:#L\d+(?:-L?\d+)?|:\d+(?:-\d+)?)$")
_WORDS = re.compile(r"\s+|\S+")


def _norm(s: object) -> str:
    return " ".join(str(s if s is not None else "").split()).lower()


def _rows(doc: dict[str, Any], array: str) -> list[dict[str, Any]]:
    value = doc.get(array)
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def _anchor_path(v: object) -> str | None:
    """The file of a `path:line` / `path#Lline` anchor, or None when the value is not one."""
    if not isinstance(v, str) or not v.strip():
        return None
    return _ANCHOR_TAIL.sub("", v.strip()) or None


def _translate(v: Any, idmap: dict[str, str]) -> Any:
    """An old-side value with re-identified ids rewritten to their new ids, so a box that merely
    changed id does not make every row naming it read as changed."""
    if not idmap:
        return v
    if isinstance(v, str):
        return _ID_TOKEN.sub(lambda m: idmap.get(m.group(0), m.group(0)), v)
    if isinstance(v, list):
        return [_translate(x, idmap) for x in v]
    if isinstance(v, dict):
        return {k: _translate(x, idmap) for k, x in v.items()}
    return v


def _name_ids(v: Any, names: dict[str, str]) -> Any:
    """A value with every id it names read as that thing's name — for DISPLAY only, after the
    comparison: a reader never meets `R2` or `CAP3` on screen, and a page about a removed use case says
    who drove it, not which row number did."""
    if not names:
        return v
    if isinstance(v, str):
        return _ID_TOKEN.sub(lambda m: names.get(m.group(0), m.group(0)), v)
    if isinstance(v, list):
        return [_name_ids(x, names) for x in v]
    if isinstance(v, dict):
        return {k: _name_ids(x, names) for k, x in v.items()}
    return v


_ITEM_NAME_KEYS = ("name", "term", "label", "key", "unit", "signal", "command", "trigger", "id")


def _item_text(item: Any) -> str:
    """One list item as a short reader string — the text a list delta names it by."""
    if isinstance(item, dict):
        if "verb" in item and "target" in item:                       # a record's relation
            return f"{item.get('verb')} {item.get('target')}"
        if "where" in item and "why" in item:                         # a rule's enforcement site
            path = _anchor_path(item.get("where")) or ""
            return f"{item.get('why')} ({path})" if path else str(item.get("why"))
        for k in _ITEM_NAME_KEYS:
            if item.get(k):
                text = str(item[k])
                if k == "name" and item.get("type"):
                    text += f" ({item['type']})"
                return text
        first = next((str(v) for v in item.values() if isinstance(v, str) and v.strip()), None)
        return first or json.dumps(item, sort_keys=True, ensure_ascii=False)
    return str(item)


def _text(v: Any) -> str | None:
    """A field's display text: None for an absent or empty value, a flat string otherwise."""
    if v is None or v == "" or v == [] or v == {}:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return ", ".join(_item_text(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_text(x) or '—'}" for k, x in v.items())
    return str(v)


def word_spans(old: str, new: str) -> list[Span]:
    """The two sentences as one run of kept / taken out / put in words. Whitespace rides with the
    words so the spans rejoin to the exact texts."""
    a, b = _WORDS.findall(old), _WORDS.findall(new)
    out: list[Span] = []

    def push(op: Literal["eq", "del", "ins"], text: str) -> None:
        if not text:
            return
        if out and out[-1].op == op:
            out[-1].text += text
        else:
            out.append(Span(op, text))

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            push("eq", "".join(a[i1:i2]))
        else:
            push("del", "".join(a[i1:i2]))
            push("ins", "".join(b[j1:j2]))
    return out


# ── pairing rows ───────────────────────────────────────────────────────────────────────────────────

@dataclass
class Pair:
    old: dict[str, Any] | None
    new: dict[str, Any] | None
    reidentified: bool = False


def _key(spec: KindSpec, row: dict[str, Any], idmap: dict[str, str]) -> str | None:
    if spec.key is None:
        rid = row.get("id")
        return rid if isinstance(rid, str) and rid else None
    if not spec.key:
        return None
    parts = [_norm(_translate(row.get(f), idmap)) for f in spec.key]
    return " · ".join(parts) if any(parts) else None


def _name(spec: KindSpec, row: dict[str, Any], doc: dict[str, Any]) -> str | None:
    if spec.array == "happy_path":          # a happy path step is named by its use case
        uc = row.get("uc")
        for u in _rows(doc, "use_cases"):
            if u.get("id") == uc:
                return _text(u.get("name"))
        return _text(uc)
    for f in spec.name:
        t = _text(row.get(f))
        if t:
            return t
    return None


def _sentence(spec: KindSpec, row: dict[str, Any]) -> str | None:
    for f in spec.sentence:
        t = _text(row.get(f))
        if t:
            return t
    return None


def _source(row: dict[str, Any]) -> str | None:
    for f in ("source", "where", "tech_source", "where_configured"):
        t = row.get(f)
        if isinstance(t, str) and t.strip():
            return t.strip()
    return None


def _anchor_of(row: dict[str, Any]) -> object:
    """The code anchor a row is placed by: an arrow's call site, a way in's source."""
    return row.get("where") if "where" in row else row.get("source")


def _pair_within(group_old: list[dict[str, Any]], group_new: list[dict[str, Any]],
                 idmap: dict[str, str]) -> list[Pair]:
    """Rows sharing one identity, paired by their anchor and reason, then anchor alone, then same
    file, then position. Two arrows with the same ends at two call sites are two rows, a moved line
    keeps its pair, and two no-call-site arrows told apart by their reason keep theirs."""
    old_left, new_left = list(group_old), list(group_new)
    pairs: list[Pair] = []

    def take(pred: Any) -> None:
        for o in list(old_left):
            for n in list(new_left):
                if pred(o, n):
                    pairs.append(Pair(o, n))
                    old_left.remove(o)
                    new_left.remove(n)
                    break

    take(lambda o, n: _norm(_translate(_anchor_of(o), idmap)) == _norm(_anchor_of(n))
         and _norm(o.get("why")) == _norm(n.get("why")))
    take(lambda o, n: _norm(_translate(_anchor_of(o), idmap)) == _norm(_anchor_of(n)))
    take(lambda o, n: _anchor_path(_anchor_of(o)) is not None
         and _anchor_path(_anchor_of(o)) == _anchor_path(_anchor_of(n)))
    while old_left and new_left:
        pairs.append(Pair(old_left.pop(0), new_left.pop(0)))
    pairs += [Pair(o, None) for o in old_left]
    pairs += [Pair(None, n) for n in new_left]
    return pairs


def pair_rows(spec: KindSpec, rows_old: list[dict[str, Any]], rows_new: list[dict[str, Any]],
              idmap: dict[str, str]) -> tuple[list[Pair], list[str]]:
    """Every row of both sides paired, or left alone as added / removed. Returns the pairs and the
    identities held by more than one row on a side of an id-keyed array (a map defect: reported,
    never paired field by field)."""
    by_old: dict[str, list[dict[str, Any]]] = {}
    by_new: dict[str, list[dict[str, Any]]] = {}
    for r in rows_old:
        k = _key(spec, r, idmap)
        if k:
            by_old.setdefault(k, []).append(r)
    for r in rows_new:
        k = _key(spec, r, {})
        if k:
            by_new.setdefault(k, []).append(r)
    pairs: list[Pair] = []
    collisions: list[str] = []
    for k in sorted(set(by_old) | set(by_new)):
        o, n = by_old.get(k, []), by_new.get(k, [])
        if spec.key is None and (len(o) > 1 or len(n) > 1):
            collisions.append(k)
            pairs += [Pair(x, None) for x in o[len(n):]] + [Pair(None, x) for x in n[len(o):]]
            continue
        pairs += _pair_within(o, n, idmap)
    if spec.key is None:
        pairs = _reidentify(spec, pairs)
    return pairs, collisions


def _reidentify(spec: KindSpec, pairs: list[Pair]) -> list[Pair]:
    """The rows left over after the id pass, paired by name and then by code file — each only when
    the match is unique on both sides, so a guess never pairs two different boxes."""
    loose_old = [p for p in pairs if p.new is None and p.old is not None]
    loose_new = [p for p in pairs if p.old is None and p.new is not None]
    if not loose_old or not loose_new:
        return pairs
    kept = [p for p in pairs if p.old is not None and p.new is not None]

    def pass_by(sig: Any) -> None:
        nonlocal loose_old, loose_new
        so: dict[str, list[Pair]] = {}
        sn: dict[str, list[Pair]] = {}
        for p in loose_old:
            assert p.old is not None
            s = sig(p.old)
            if s:
                so.setdefault(s, []).append(p)
        for p in loose_new:
            assert p.new is not None
            s = sig(p.new)
            if s:
                sn.setdefault(s, []).append(p)
        for s in sorted(set(so) & set(sn)):
            if len(so[s]) == 1 and len(sn[s]) == 1:
                o, n = so[s][0], sn[s][0]
                kept.append(Pair(o.old, n.new, reidentified=True))
                loose_old = [p for p in loose_old if p is not o]
                loose_new = [p for p in loose_new if p is not n]

    pass_by(lambda r: _norm(_text(next((r.get(f) for f in spec.name if r.get(f)), None))) or None)
    pass_by(lambda r: _anchor_path(r.get("source")))
    return kept + loose_old + loose_new


# ── comparing a pair ───────────────────────────────────────────────────────────────────────────────

_SKIP_FIELDS = frozenset({"id", "steps"})


def field_deltas(old: dict[str, Any], new: dict[str, Any], idmap: dict[str, str],
                 skip: frozenset[str] = _SKIP_FIELDS, names_old: dict[str, str] | None = None,
                 names_new: dict[str, str] | None = None) -> list[FieldDelta]:
    """Every field that differs between two paired rows, with its reader label, its class, the two
    display texts, and — for a sentence — the changed words, for a list — the items that came and
    went. A list whose items all match but whose code lines moved is a code-link move, not a change."""
    out: list[FieldDelta] = []
    for key in sorted(set(old) | set(new)):
        if key in skip:
            continue
        a, b = _translate(old.get(key), idmap), new.get(key)
        if a == b:
            continue
        spec = field_spec(key)
        da, db = _name_ids(a, names_old or {}), _name_ids(b, names_new or {})   # display forms
        ta, tb = _text(da), _text(db)
        d = FieldDelta(key, spec.label, spec.cls, ta, tb)
        if isinstance(a, list) or isinstance(b, list):
            ia = [_item_text(x) for x in da] if isinstance(da, list) else []
            ib = [_item_text(x) for x in db] if isinstance(db, list) else []
            d.added = [x for x in ib if x not in ia]
            d.removed = [x for x in ia if x not in ib]
            if not d.added and not d.removed:
                raw_a = sorted(json.dumps(x, sort_keys=True) for x in (a if isinstance(a, list) else []))
                raw_b = sorted(json.dumps(x, sort_keys=True) for x in (b if isinstance(b, list) else []))
                if raw_a == raw_b:
                    continue                      # reordered only: the same items, nothing to say
                d.cls = "link"                    # the same items by name, their code lines moved
                d.old = d.new = None
        elif isinstance(da, str) and isinstance(db, str) and spec.cls == "wording":
            d.spans = word_spans(da, db)
        out.append(d)
    return out


def _step_sig(st: dict[str, Any], idmap: dict[str, str]) -> tuple[str, str, str, str]:
    return (_norm(_translate(st.get("src"), idmap)), _norm(_translate(st.get("dst"), idmap)),
            _norm(st.get("phrase")), _norm(st.get("subflow")))


def _n(v: object) -> int | None:
    try:
        return int(str(v)) if v is not None and str(v).strip() else None
    except ValueError:
        return None


def _step_pair(o: dict[str, Any], n: dict[str, Any], idmap: dict[str, str],
               names_old: dict[str, str], names_new: dict[str, str]) -> StepDelta | None:
    """Two aligned steps compared: None when identical, `renumbered` when only the number moved."""
    fields = field_deltas(o, n, idmap, skip=frozenset({"n", "phrase"}), names_old=names_old, names_new=names_new)
    n_old, n_new = _n(o.get("n")), _n(n.get("n"))
    reworded = _norm(o.get("phrase")) != _norm(n.get("phrase"))
    if not fields and not reworded and n_old == n_new:
        return None
    state: Literal["modified", "renumbered"] = "modified" if (fields or reworded) else "renumbered"
    have: set[ChangeClass] = {f.cls for f in fields}
    if reworded:
        have.add("wording")
    if state == "renumbered":
        have.add("structure")
    return StepDelta(state, n_old, n_new, _text(o.get("phrase")), _text(n.get("phrase")),
                     _text(n.get("src")), _text(n.get("dst")),
                     word_spans(str(o.get("phrase") or ""), str(n.get("phrase") or "")) if reworded else [],
                     fields, _text(_name_ids(n.get("subflow"), names_new)),
                     [c for c in CLASS_ORDER if c in have])


def align_steps(old_steps: list[dict[str, Any]], new_steps: list[dict[str, Any]],
                idmap: dict[str, str], names_old: dict[str, str] | None = None,
                names_new: dict[str, str] | None = None) -> list[StepDelta]:
    """The two step lists aligned like lines of text: the same actor, target and phrase is the same
    step. A step inserted in the middle is one addition, and the steps after it are renumbered.
    Inside a replaced run, an old and a new step with the same ends pair up as a rewording."""
    no, nn = names_old or {}, names_new or {}
    sa = [_step_sig(s, idmap) for s in old_steps]
    sb = [_step_sig(s, {}) for s in new_steps]
    out: list[StepDelta] = []

    def removed(s: dict[str, Any]) -> StepDelta:
        return StepDelta("removed", _n(s.get("n")), None, _text(s.get("phrase")), None,
                         _text(_translate(s.get("src"), idmap)), _text(_translate(s.get("dst"), idmap)),
                         subflow=_text(_name_ids(s.get("subflow"), no)), classes=["structure"])

    def added(s: dict[str, Any]) -> StepDelta:
        return StepDelta("added", None, _n(s.get("n")), None, _text(s.get("phrase")),
                         _text(s.get("src")), _text(s.get("dst")),
                         subflow=_text(_name_ids(s.get("subflow"), nn)), classes=["structure"])

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, sa, sb, autojunk=False).get_opcodes():
        if tag == "equal":
            for o, n in zip(old_steps[i1:i2], new_steps[j1:j2]):
                d = _step_pair(o, n, idmap, no, nn)
                if d:
                    out.append(d)
        elif tag == "delete":
            out += [removed(s) for s in old_steps[i1:i2]]
        elif tag == "insert":
            out += [added(s) for s in new_steps[j1:j2]]
        else:
            width = min(i2 - i1, j2 - j1)
            for k in range(width):
                o, n = old_steps[i1 + k], new_steps[j1 + k]
                if sa[i1 + k][:2] == sb[j1 + k][:2]:      # the same ends: a rewording, not a swap
                    d = _step_pair(o, n, idmap, no, nn)
                    if d:
                        out.append(d)
                else:
                    out += [removed(o), added(n)]
            out += [removed(s) for s in old_steps[i1 + width:i2]]
            out += [added(s) for s in new_steps[j1 + width:j2]]
    return out


# ── phrasing ───────────────────────────────────────────────────────────────────────────────────────

def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _steps_phrase(steps: list[StepDelta]) -> str:
    """`2 steps added`, or `steps: 1 added, 2 reworded, 5 moved in the code` — a modified step reads
    by what moved in it: its words, something structural, or only its code line."""
    def is_(s: StepDelta, state: str, cls: ChangeClass | None = None) -> bool:
        if s.state != state:
            return False
        return cls is None or (cls in s.classes if cls != "link" else s.classes == ["link"])
    kinds: list[tuple[str, int]] = [
        ("added", sum(1 for s in steps if is_(s, "added"))),
        ("removed", sum(1 for s in steps if is_(s, "removed"))),
        ("reworded", sum(1 for s in steps if is_(s, "modified", "wording"))),
        ("changed", sum(1 for s in steps if is_(s, "modified", "structure") and "wording" not in s.classes)),
        ("moved in the code", sum(1 for s in steps if is_(s, "modified", "link"))),
        ("renumbered", sum(1 for s in steps if is_(s, "renumbered"))),
    ]
    parts = [f"{k} {word}" for word, k in kinds if k]
    if len(parts) == 1:
        return f"{_count(len(steps), 'step')} {parts[0].split(' ', 1)[1]}"
    return "steps: " + ", ".join(parts)


def _fields_phrase(fields: list[FieldDelta], renamed_from: str | None) -> list[str]:
    parts: list[str] = []
    if renamed_from:
        parts.append(f"renamed from {renamed_from}")
    wording = [f.label for f in fields if f.cls == "wording" and f.key != "name"]
    structure = [f.label for f in fields if f.cls == "structure"]
    links = [f for f in fields if f.cls == "link"]
    parts += [f"{label.lower()} reworded" for label in wording]
    parts += [f"{label.lower()} changed" for label in structure]
    if links:
        parts.append("code link moved" if len(links) == 1 else f"{len(links)} code links moved")
    return parts


def _join_parts(parts: list[str], cap: int = 3) -> str:
    if len(parts) <= cap:
        return " · ".join(parts)
    return " · ".join(parts[:cap]) + f" · {len(parts) - cap} more"


def _classes(fields: list[FieldDelta], steps: list[StepDelta]) -> list[ChangeClass]:
    have: set[ChangeClass] = {f.cls for f in fields}
    for s in steps:
        have.update(s.classes)
    return [c for c in CLASS_ORDER if c in have]


# ── the whole document ─────────────────────────────────────────────────────────────────────────────

def _element(spec: KindSpec, p: Pair, idmap: dict[str, str], old_doc: dict[str, Any],
             new_doc: dict[str, Any], names_old: dict[str, str], names_new: dict[str, str],
             steps: list[StepDelta] | None = None,
             flow_fields: list[FieldDelta] | None = None) -> ElementDelta | None:
    old, new = p.old, p.new
    steps = steps or []
    fields = list(flow_fields or [])
    if old is not None and new is not None:
        fields = field_deltas(old, new, idmap, names_old=names_old, names_new=names_new) + fields
        if not fields and not steps and not p.reidentified:
            return None
        change: Change = "modified"
    else:
        # A row come or gone carries EVERY field it has, one-sided: that is what a removed box's page
        # shows ("as it was in the old map"), and what a new box's block can say beyond "new".
        change = "removed" if new is None else "added"
        fields = field_deltas(old or {}, new or {}, idmap, names_old=names_old, names_new=names_new) + fields
    name_old = _name(spec, old, old_doc) if old is not None else None
    name_new = _name(spec, new, new_doc) if new is not None else None
    if change == "added":
        summary = _sentence(spec, new or {}) or "new"
    elif change == "removed":
        summary = "removed"
    else:
        parts: list[str] = []
        if steps:
            parts.append(_steps_phrase(steps))
        renamed = name_old if (name_old and name_new and _norm(name_old) != _norm(name_new)) else None
        parts += _fields_phrase(fields, renamed)
        if p.reidentified:
            parts.append(f"same {spec.word} under a new id")
        summary = _join_parts(parts) or "changed"
    return ElementDelta(
        kind=spec.array, change=change,
        id_old=_text((old or {}).get("id")), id_new=_text((new or {}).get("id")),
        name_old=name_old, name_new=name_new, reidentified=p.reidentified,
        classes=_classes(fields, steps), fields=fields, steps=steps, summary=summary,
        sentence_old=_sentence(spec, old) if old is not None else None,
        sentence_new=_sentence(spec, new) if new is not None else None,
        source_old=_source(old) if old is not None else None,
        source_new=_source(new) if new is not None else None)


def _flows_by_uc(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in _rows(doc, FLOWS):
        uc = f.get("uc")
        if isinstance(uc, str) and uc:
            out[uc] = f
    return out


def _arrows(old_doc: dict[str, Any], new_doc: dict[str, Any], idmap: dict[str, str],
            names: dict[str, str]) -> tuple[list[ArrowDelta], KindCount]:
    spec = KIND_OF["edges"]
    rows_old, rows_new = _rows(old_doc, "edges"), _rows(new_doc, "edges")
    pairs, collisions = pair_rows(spec, rows_old, rows_new, idmap)
    count = KindCount("edges", len(rows_old), len(rows_new), collisions=collisions)
    out: list[ArrowDelta] = []
    for p in pairs:
        old, new = p.old, p.new
        side = new if new is not None else _translate(old, idmap)
        assert side is not None
        src, verb, dst = _text(side.get("src")) or "?", _text(side.get("verb")) or "?", _text(side.get("dst")) or "?"
        if old is not None and new is not None:
            fields = field_deltas(old, new, idmap)
            if not fields:
                continue
            classes = _classes(fields, [])
            if classes == ["link"]:
                count.link_only += 1
            else:
                count.modified += 1
            summary = _join_parts(_fields_phrase(fields, None)) or "changed"
            change: Change = "modified"
        else:
            fields, classes = [], []
            change = "removed" if new is None else "added"
            if change == "added":
                count.added += 1
            else:
                count.removed += 1
            summary = f"{names.get(src, src)} {verb} {names.get(dst, dst)}"
        out.append(ArrowDelta(change, src, verb, dst, classes, fields, summary,
                              _text((old or {}).get("where")), _text((new or {}).get("where"))))
    return out, count


def _names(doc: dict[str, Any]) -> dict[str, str]:
    """Every id-bearing row's name — the boxes, and the ways in by their trigger — so a reference
    field and an arrow can be phrased with names."""
    out: dict[str, str] = {}
    for spec in KINDS:
        if spec.key is None or spec.array == "entry_points":
            for r in _rows(doc, spec.array):
                rid, name = r.get("id"), _name(spec, r, doc)
                if isinstance(rid, str) and rid and name:
                    out[rid] = name
    return out


def _separate_builds_warning(old_doc: dict[str, Any], new_doc: dict[str, Any]) -> str | None:
    """Two builds of one repo reuse ids for different things. Measured on use cases: when fewer than
    half the ids shared by both maps keep their name, the comparison is by id and mostly meaningless."""
    spec = KIND_OF["use_cases"]
    old = {r["id"]: r for r in _rows(old_doc, "use_cases") if isinstance(r.get("id"), str)}
    new = {r["id"]: r for r in _rows(new_doc, "use_cases") if isinstance(r.get("id"), str)}
    shared = sorted(set(old) & set(new))
    if len(shared) < 3:
        return None
    kept = sum(1 for i in shared if _norm(_name(spec, old[i], old_doc)) == _norm(_name(spec, new[i], new_doc)))
    if kept * 2 >= len(shared):
        return None
    return (f"The two maps look like separate builds: {kept} of {len(shared)} use cases sharing an id "
            f"keep their name. Rows are matched by id, then by name and code file; treat the rest "
            f"as approximate.")


def diff_maps(old_doc: dict[str, Any], new_doc: dict[str, Any], old_label: str = "old",
              new_label: str = "new", only: str | None = None) -> MapDelta:
    """The change document for two raw maps. `only` restricts the rows to one array."""
    warnings: list[str] = []
    fo, fn = old_doc.get("format"), new_doc.get("format")
    if fo != fn and isinstance(fo, str) and isinstance(fn, str):
        warnings.append(f"The old map is in an older format ({fo}); fields the new format dropped "
                        f"or renamed read as removed or added.")
    w = _separate_builds_warning(old_doc, new_doc)
    if w:
        warnings.append(w)
    # Pass 1: pair every id-keyed kind, collecting the re-identifications; they feed pass 2, where
    # every reference to an old id is read as its new id.
    idmap: dict[str, str] = {}
    paired: dict[str, tuple[list[Pair], list[str]]] = {}
    for spec in KINDS:
        if spec.key is None:
            pairs, collisions = pair_rows(spec, _rows(old_doc, spec.array), _rows(new_doc, spec.array), {})
            paired[spec.array] = (pairs, collisions)
            for p in pairs:
                if p.reidentified and p.old is not None and p.new is not None:
                    idmap[str(p.old.get("id"))] = str(p.new.get("id"))
    elements: list[ElementDelta] = []
    counts: list[KindCount] = []
    old_flows, new_flows = _flows_by_uc(old_doc), _flows_by_uc(new_doc)
    names_old, names_new = _names(old_doc), _names(new_doc)
    for spec in KINDS:
        if only and spec.array != only:
            continue
        if spec.array == "edges":
            continue
        rows_old, rows_new = _rows(old_doc, spec.array), _rows(new_doc, spec.array)
        count = KindCount(spec.array, len(rows_old), len(rows_new))
        if spec.key == ():
            counts.append(count)
            continue
        if spec.key is None:
            pairs, collisions = paired[spec.array]
        else:
            pairs, collisions = pair_rows(spec, rows_old, rows_new, idmap)
        count.collisions = collisions
        for p in pairs:
            steps: list[StepDelta] = []
            flow_fields: list[FieldDelta] = []
            if spec.array == "use_cases":
                uc_old = str(p.old.get("id")) if p.old is not None else None
                uc_new = str(p.new.get("id")) if p.new is not None else None
                fl_old = old_flows.get(uc_old or "", {})
                fl_new = new_flows.get(uc_new or "", {})
                so = [s for s in fl_old.get("steps", []) if isinstance(s, dict)] if isinstance(fl_old.get("steps"), list) else []
                sn = [s for s in fl_new.get("steps", []) if isinstance(s, dict)] if isinstance(fl_new.get("steps"), list) else []
                # A use case come or gone brings its whole flow, every step one-sided, for its page.
                steps = align_steps(so, sn, idmap, names_old, names_new)
                flow_fields = field_deltas({k: v for k, v in fl_old.items() if k not in ("steps", "uc")},
                                           {k: v for k, v in fl_new.items() if k not in ("steps", "uc")}, idmap,
                                           names_old=names_old, names_new=names_new)
            elif spec.array == "subflows":
                o_steps, n_steps = (p.old or {}).get("steps"), (p.new or {}).get("steps")
                so = [s for s in o_steps if isinstance(s, dict)] if isinstance(o_steps, list) else []
                sn = [s for s in n_steps if isinstance(s, dict)] if isinstance(n_steps, list) else []
                steps = align_steps(so, sn, idmap, names_old, names_new)
            d = _element(spec, p, idmap, old_doc, new_doc, names_old, names_new, steps, flow_fields)
            if d is None:
                continue
            elements.append(d)
            if d.change == "added":
                count.added += 1
            elif d.change == "removed":
                count.removed += 1
            elif d.classes == ["link"]:
                count.link_only += 1
            else:
                count.modified += 1
        counts.append(count)
    arrows: list[ArrowDelta] = []
    if not only or only == "edges":
        arrows, edge_count = _arrows(old_doc, new_doc, idmap, names_new | names_old)
        counts.append(edge_count)
    order = {k.array: i for i, k in enumerate(KINDS)}
    counts.sort(key=lambda c: order.get(c.kind, 99))
    return MapDelta(old_label, new_label, elements, arrows, [c for c in counts if not c.quiet],
                    warnings, idmap)


# ── renderers ──────────────────────────────────────────────────────────────────────────────────────

def to_json(delta: MapDelta) -> dict[str, Any]:
    return {"kind": "coyomap-map-diff", "version": 2,
            "old": delta.old_label, "new": delta.new_label,
            "elements": [asdict(e) for e in delta.elements],
            "arrows": [asdict(a) for a in delta.arrows],
            "counts": [asdict(c) for c in delta.counts],
            "warnings": delta.warnings, "idmap": delta.idmap,
            # The kinds in the reader's order, with their words and group tab, so the viewer's
            # Changes tabs cut the list the way this table says and invent no second one.
            "kinds": [{"array": k.array, "word": k.word, "plural": k.plural, "group": k.group}
                      for k in KINDS]}


def _count_line(c: KindCount) -> str:
    delta = c.after - c.before
    return f"  {c.kind}: {c.before} → {c.after}" + (f" ({delta:+d})" if delta else "")


def to_text(delta: MapDelta) -> str:
    """The agent's form: ids and field keys, one line per row, the shapes the method quotes."""
    lines = [f"map diff — {delta.old_label} → {delta.new_label}"]
    if not delta.counts and not delta.elements and not delta.arrows:
        lines.append("  no row changed.")
    by_kind: dict[str, list[ElementDelta]] = {}
    for e in delta.elements:
        by_kind.setdefault(e.kind, []).append(e)
    for c in delta.counts:
        lines.append(_count_line(c))
        if c.kind == "edges":
            for a in delta.arrows:
                key = f"{a.src} {a.verb} {a.dst}"
                if a.change == "removed":
                    lines.append(f"    - {key}")
                elif a.change == "added":
                    lines.append(f"    + {key}")
                else:
                    mark = "≈" if a.classes == ["link"] else "~"
                    lines.append(f"    {mark} {key}  [{', '.join(f.key for f in a.fields)}]")
        for e in by_kind.get(c.kind, []):
            if e.change == "removed":
                lines.append(f"    - {e.id_old or e.name_old}")
            elif e.change == "added":
                lines.append(f"    + {e.id_new or e.name_new}")
            else:
                keys = [f.key for f in e.fields]
                if e.steps:
                    keys.append("steps " + " ".join(f"{sign}{k}" for sign, k in (
                        ("+", sum(1 for s in e.steps if s.state == "added")),
                        ("−", sum(1 for s in e.steps if s.state == "removed")),
                        ("~", sum(1 for s in e.steps if s.state == "modified")),
                        ("#", sum(1 for s in e.steps if s.state == "renumbered"))) if k))
                head = (f"⇒ {e.id_old} → {e.id_new}" if e.reidentified
                        else ("≈ " if e.classes == ["link"] else "~ ") + str(e.id_new or e.name_new))
                lines.append(f"    {head}  [{', '.join(keys)}]" if keys else f"    {head}")
        for k in c.collisions:
            lines.append(f"    ! {k}  (identity held by more than one row — reported by count, not paired)")
        if c.kind in KIND_OF and KIND_OF[c.kind].key == () and c.before != c.after:
            lines.append(f"    (counted only — {c.kind} rows carry no stable identity to match on)")
    for w in delta.warnings:
        lines.append(f"  ! {w}")
    return "\n".join(lines)


def _md_spans(spans: list[Span]) -> str:
    """The spans as markdown: taken-out words struck, put-in words bold, whitespace outside the marks."""
    out: list[str] = []
    for s in spans:
        if s.op == "eq":
            out.append(s.text)
            continue
        lead = s.text[:len(s.text) - len(s.text.lstrip())]
        trail = s.text[len(s.text.rstrip()):]
        core = s.text.strip()
        mark = "~~" if s.op == "del" else "**"
        out.append(f"{lead}{mark}{core}{mark}{trail}" if core else s.text)
    return "".join(out)


def _md_field(f: FieldDelta) -> str:
    if f.spans:
        return f"{f.label}: {_md_spans(f.spans)}"
    if f.added or f.removed:
        bits = [f"+ {x}" for x in f.added] + [f"− {x}" for x in f.removed]
        return f"{f.label}: " + "; ".join(bits)
    if f.old is None:
        return f"{f.label}: {f.new}"
    if f.new is None:
        return f"{f.label}: ~~{f.old}~~"
    return f"{f.label}: {f.old} → {f.new}"


def _step_words(phrase: str | None, subflow: str | None) -> str:
    return phrase or (f"runs {subflow}" if subflow else "")


def _md_step(s: StepDelta) -> str:
    if s.state == "added":
        return f"+ step {s.n_new}: {_step_words(s.phrase_new, s.subflow)}"
    if s.state == "removed":
        return f"− step {s.n_old}: {_step_words(s.phrase_old, s.subflow)}"
    if s.state == "renumbered":
        return f"step {s.n_old} → {s.n_new}: renumbered"
    body = _md_spans(s.spans) if s.spans else _step_words(s.phrase_new, s.subflow)
    extra = "; ".join(_md_field(f) for f in s.fields)
    return f"~ step {s.n_new}: {body}" + (f" ({extra})" if extra else "")


def to_markdown(delta: MapDelta) -> str:
    """The reader's form: names, reader labels, the changed words, in the map's own order."""
    lines = [f"# What changed: {delta.old_label} → {delta.new_label}", ""]
    for w in delta.warnings:
        lines.append(f"> {w}")
    if delta.warnings:
        lines.append("")
    totals = {"added": 0, "removed": 0, "modified": 0, "link_only": 0}
    for c in delta.counts:
        for k in totals:
            totals[k] += getattr(c, k)
    lines.append(f"{_count(totals['added'], 'box', 'boxes')} added · {totals['removed']} removed · "
                 f"{totals['modified']} modified · {totals['link_only']} moved in the code only")
    by_kind: dict[str, list[ElementDelta]] = {}
    for e in delta.elements:
        by_kind.setdefault(e.kind, []).append(e)
    for group, heading in (("product", "Product"), ("hood", "Under the hood")):
        section: list[str] = []
        for spec in KINDS:
            if spec.group != group:
                continue
            if spec.array == "edges":
                rows = [f"- {a.change}: {a.summary}" + (f" — {'; '.join(_md_field(f) for f in a.fields)}" if a.fields else "")
                        for a in delta.arrows]
            else:
                rows = []
                for e in by_kind.get(spec.array, []):
                    name = e.name_new or e.name_old or e.key
                    rows.append(f"- **{name}** ({e.change}): {e.summary}")
                    rows += [f"  - {_md_field(f)}" for f in e.fields]
                    rows += [f"  - {_md_step(s)}" for s in e.steps]
            if rows:
                section += ["", f"### {spec.plural.capitalize()}", *rows]
        if section:
            lines += ["", f"## {heading}", *section]
    return "\n".join(lines) + "\n"


# ── the command ────────────────────────────────────────────────────────────────────────────────────

KNOWN_ARRAYS: frozenset[str] = frozenset(k.array for k in KINDS) | {FLOWS}


def looks_like_map(doc: object) -> bool:
    """A parsed document that is a map: an object with the map's format word, or failing that any of
    the arrays a map is made of. Older formats pass; a list or an unrelated object does not."""
    if not isinstance(doc, dict):
        return False
    fmt = doc.get("format")
    if isinstance(fmt, str) and fmt.startswith("coyo"):
        return True
    return any(isinstance(doc.get(a), list) for a in ("use_cases", "components", "entities", "rules"))


def _read(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not looks_like_map(doc):
        raise ValueError(f"{path}: not a map (no format word and none of a map's arrays)")
    return doc


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if args else 2
    only: str | None = None
    mode = "text"
    positional: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--only":
            i += 1
            if i >= len(args):
                print("ERROR: --only needs an array name", file=sys.stderr)
                return 2
            only = args[i]
            if only.startswith("--"):
                print(f"ERROR: --only was given '{only}', which is another flag", file=sys.stderr)
                return 2
        elif a == "--json":
            mode = "json"
        elif a == "--md":
            mode = "md"
        elif a.startswith("-"):
            print(f"ERROR: unknown option '{a}'\n", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2
        else:
            positional.append(a)
        i += 1
    if len(positional) != 2:
        print("ERROR: give exactly two map paths — the old one and the new one\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    old, new = Path(positional[0]), Path(positional[1])
    for p in (old, new):
        if not p.is_file():
            print(f"ERROR: {p} not found", file=sys.stderr)
            return 2
    try:
        before, after = _read(old), _read(new)
    except (ValueError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if only is not None:
        known = sorted({k for k, v in (*before.items(), *after.items()) if isinstance(v, list)})
        if only not in known:
            print(f"ERROR: --only '{only}' is not an array in either map. Known: "
                  f"{', '.join(known)}", file=sys.stderr)
            return 2
    delta = diff_maps(before, after, str(old), str(new), only)
    if mode == "json":
        print(json.dumps(to_json(delta), indent=2, ensure_ascii=False))
    elif mode == "md":
        print(to_markdown(delta), end="")
    else:
        print(to_text(delta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
