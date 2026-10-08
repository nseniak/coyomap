#!/usr/bin/env python3
"""`coyomap assemble` — structured rows → the canonical model (the parallel-build assembler).

Build agents return STRUCTURED ROWS: each harvest/trace agent's output is saved verbatim as a
JSON *fragment* — a partial model holding a subset of the top-level arrays (components, edges,
entities, …) and, in at most one fragment, the header singletons (title / goal / commit /
committed / built). This command validates every fragment against the schema (one bad fragment
fails ALONE, with its file and JSON path named — the whole point of assembling with a tool),
merges them (arrays concatenate in argument order; a duplicate ID across fragments is an ERROR,
never a silent overwrite), and writes the canonical `project-map.json` plus its generated markdown
view. No HTML file is written: the interactive diagram is built on demand by `coyomap serve`. The
LLM never hand-authors the stored format: validity is guaranteed here, by the serializer.

A fragment is the model document minus the strictness that only the WHOLE map needs: `format` is
optional in a fragment, every top-level field is optional, and cross-fragment references are NOT
resolved here — that is `coyomap validate`'s job on the assembled result (the usual invariant
`validate --check-sources → audit → render` still runs after assembly). Stdlib-only.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import MISSING, dataclass, fields, is_dataclass, replace
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

from coyomap import buildstate, grammar, uncommitted
from coyomap.anchors import LINE_ANCHOR
from coyomap.model import (
    FORMAT,
    ID_ARRAYS,
    ID_SHAPE,
    ComponentKind,
    ConfigRow,
    Edge,
    EntryPoint,
    ExtraSection,
    Flow,
    FlowStep,
    MessagingRow,
    ModelError,
    ObservabilityRow,
    ProjectModel,
    guard_wrong_map,
    resolve_map_path,
    _build,
    _collect,
    _normalize_subflow_title,
    load_model,
    remap_element_ids,
    to_canonical_json,
)
from coyomap.reporting import shown as _shown
from coyomap.reconcile import (
    ReconcileError,
    apply_reconcile,
    load_reconcile,
    validate_reconcile,
)
from coyomap.validate_model import (
    rule_identity,
    unbacked_entity_steps,
    undecided_interface_pointers,
)
from coyomap.whole_file import write_whole

# Top-level NON-list fields, merged one-per-map with a conflict report. `grounding` belongs here:
# it is written by the Phase-4 reconcile as its own fragment, and omitting it meant `assemble`
# silently dropped the field on the only code path that writes a map — so the coverage record could
# never survive to the committed model, and `validate` then reported the map as never grounded.
_SINGLETONS = ("title", "goal", "commit", "committed", "built", "tool_commit",
               "tool_committed", "tests_note", "grounding")

# Phase-4 verdicts files ({"grounding": [...]}) sometimes land in build-fragments/ and get caught by
# a `*.json` glob — they are NOT fragments. Recognised so `assemble` skips them with a note instead
# of failing the whole build (the failure a fresh build hit and had to hand-fix mid-run).
_FRAGMENT_KEYS = {f.name for f in fields(ProjectModel)}

# C→E edge verb inferred from the step's LEADING verb. Entity-step phrases are action-first ("upserts
# the membership document", "reads the user record"), so the first verb IS the operation — matching it
# alone avoids the noun traps a substring scan hits ("reads the asset metadata" must not become a WRITE
# because "asset" contains "set"). A write-family verb ESTABLISHES ownership (the 'owning component'
# check reads persists/writes), so anything not clearly a write defaults to `reads` — a derived edge
# never invents ownership (the honest direction: an ownerless entity stays flagged, not falsely owned).
# The verb families live in `grammar` (the one place backbone-verb meaning is decided — DRY); this
# derivation and `grammar.edge_role` read the SAME vocabulary, so a new verb is added once.


def _infer_ce_verb(phrase: str) -> str:
    words = re.findall(r"[a-z]+", (phrase or "").lower())
    lead = words[0] if words else ""
    if lead in grammar.PERSIST_VERBS:
        return "persists"
    if lead in grammar.WRITE_VERBS:
        return "writes"
    if lead in grammar.EMIT_VERBS:
        return "emits"
    if lead in grammar.ENCRYPT_VERBS:
        return "encrypts"
    return "reads"  # a read verb or anything ambiguous → never over-claims ownership


def _is_verdicts_file(text: str) -> bool:
    """A Phase-4 verdicts file ({"grounding": [row, …]}), not a build fragment.

    The discriminator is the TYPE of `grounding`, not its presence: a verdicts file holds a LIST of
    per-claim rows, the grounding FRAGMENT `grounding write` emits holds the record OBJECT, and both
    files carry that one key and nothing else. Keying on "shares no fragment field" instead — the
    first attempt — made this unconditionally False, because `grounding` is itself a `ProjectModel`
    field and so always intersected `_FRAGMENT_KEYS`: the skip below never once fired, and a verdicts
    file swept into the glob failed the build with a confusing schema error rather than the note that
    names it. (A real fragment carrying other sections alongside a stray `grounding` is still caught
    by the second clause and treated as a fragment.)"""
    try:
        obj = json.loads(text)
    except ValueError:
        return False
    return (isinstance(obj, dict) and isinstance(obj.get("grounding"), list)
            and not (set(obj) - {"grounding"}) & _FRAGMENT_KEYS)


def _derive_entity_edges(m: ProjectModel, stats: dict[str, int]) -> list[str]:
    """Create the C→E backbone edge each unbacked entity flow-step implies. The step already carries
    the evidence (its C and E endpoints + a `where`); at scale a trace agent authors the entity STEP
    but forgets the paired edge (both fresh builds shipped ~a dozen such, leaving entities with no
    'owning component' and no impact reachability). Deriving here is IDEMPOTENT (regenerated from the
    steps on every assemble, so it survives re-assembly — unlike a post-assemble `fix`) and additive
    (only pairs no edge already carries). Verb inferred from the phrase; ambiguous → `reads`, so a
    derived edge never invents ownership. Returns a short `C verb E` log for the assemble note."""
    unbacked = unbacked_entity_steps(m)
    if not unbacked:
        return []
    ownership = {"persists", "writes"}
    chosen: dict[tuple[str, str], tuple[str, FlowStep]] = {}
    for _label, st, c_id, e_id in unbacked:
        verb = _infer_ce_verb(st.phrase)
        prev = chosen.get((c_id, e_id))
        # first step wins, but upgrade to an ownership verb if any step for this pair implies one
        if prev is None or (verb in ownership and prev[0] not in ownership):
            chosen[(c_id, e_id)] = (verb, st)
    for (c_id, e_id), (verb, st) in chosen.items():
        m.edges.append(Edge(src=c_id, verb=verb, dst=e_id,
                            why="derived from entity flow-step",
                            where=st.where, no_call_site=not bool(st.where)))
    stats["entity_edges_derived"] = len(chosen)
    return [f"{c} {v} {e}" for (c, e), (v, _st) in chosen.items()]


def _drop_answered_interface_pointers(m: ProjectModel) -> list[str]:
    """Clear the harvest pointer (`grammar.is_interface_pointer`) from every dep that now names its
    surface. Returns their ids.

    Synthesis links a dep to its surface through the reconcile file, and the pointer stayed beside
    it: the dep then named an interface AND said why it is none, which `validate` blocks. The
    2026-10-07 mcpolis lead deleted the field by hand from 7 deps. Only the POINTER goes: a real
    reason beside a named surface is a contradiction for the lead to settle, and `validate` still
    blocks on it."""
    cleared: list[str] = []
    for d in m.deps:
        if d.interfaces and grammar.is_interface_pointer(d.not_an_interface):
            d.not_an_interface = ""
            cleared.append(d.id)
    return cleared


def _fragment_data(text: str, label: str) -> dict:
    """A fragment's JSON object, with `format` defaulted and the known aliases rewritten. Raises
    ModelError when the text is not a fragment at all (bad JSON, not an object, wrong format)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ModelError(f"{label}: not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ModelError(f"{label}: top level: expected an object")
    data.setdefault("format", FORMAT)
    if data["format"] != FORMAT:
        raise ModelError(f"{label}: format: expected '{FORMAT}', got {data['format']!r}")
    _normalize_subflow_title(data)  # `subflows[].title` alias — the shape agents guess by analogy
    # with Flow; five identical lint failures in one live rebuild (see model._normalize_subflow_title)
    return data


def _id_shape_errors(data: dict, label: str) -> list[str]:
    """Every element id of the fragment that is not its array's prefix + digits. Read from the raw
    rows, so it also runs on a fragment that does not build."""
    errors: list[str] = []
    for attr, prefix in ID_ARRAYS.items():
        rows = data.get(attr)
        for i, el in enumerate(rows if isinstance(rows, list) else []):
            eid = el.get("id") if isinstance(el, dict) else None
            if not isinstance(eid, str):
                continue  # a missing or non-string id is the schema check's fault, already named
            head = re.match(r"[A-Z]+", eid)
            if not (ID_SHAPE.match(eid) and head and head.group(0) == prefix):
                errors.append(f"{label}: $.{attr}[{i}].id: '{eid}' is not a valid {prefix}-id "
                              f"(a schema id is the prefix + digits only, e.g. {prefix}3)")
    return errors


def load_fragment(text: str, label: str) -> ProjectModel:
    """A fragment parsed + structurally validated as a partial model. `format` defaults to the
    current one so agents don't have to state it; everything else validates exactly like the map —
    INCLUDING the id-shape/prefix rule (`S1a` in a fragment must die at the authoring agent's own
    `lint-fragment`, not a phase later at the lead's validate — the shift-left this module exists
    for; the rule was previously run only by `load_model`). Raises on the FIRST fault; see
    `fragment_schema_errors` for all of them."""
    data = _fragment_data(text, label)
    m = _build(data, ProjectModel, label)
    bad_ids = _id_shape_errors(data, label)
    if bad_ids:
        raise ModelError(bad_ids[0])
    return m


def fragment_schema_errors(text: str, label: str) -> list[str]:
    """EVERY schema fault of a fragment, in file order; empty when `load_fragment` would succeed.

    `lint-fragment` prints these. It used to print `load_fragment`'s one error and stop, so each
    fault cost the agent a lint round of its own: 14 of 48 harvest lint runs on the 2026-10-08
    mcpolis build failed that way."""
    try:
        data = _fragment_data(text, label)
    except ModelError as e:
        return [str(e)]
    errors: list[str] = []
    try:
        _build(data, ProjectModel, label, errors)
    except ModelError as e:
        _collect(errors, e)
    return errors + _id_shape_errors(data, label)


def load_map_or_fragment(path: Path) -> tuple[ProjectModel, frozenset[str] | None]:
    """Load either an assembled map or a build FRAGMENT, and say which it was.

    Returns `(model, present_keys)`; `present_keys` is the fragment's own top-level key set, or None
    for a full map. Read-only tools (`dump`) can ignore it; a writer (`fix`) must pass it back to
    `dump_preserving` — see why there.

    A fragment is recognised by having no `format` key: `load_fragment` defaults it, which is the
    whole reason an agent can author a partial file. This exists because there was NO read path for a
    fragment at all: `dump` and `fix` both went through `load_model`, which requires `format`, so a
    build inspecting or editing its own fragments had nothing to use and wrote `python3 - <<'EOF'`
    heredocs instead — about fifteen times in one live build, against the method's own instruction to
    use `dump`."""
    # Through the shared resolver: this is the OTHER path a verb reaches a map by, and a guard on
    # only one of two doors is not a guard. `fix` and `dump` both come in here.
    text = resolve_map_path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ModelError(f"{path.name}: not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ModelError(f"{path.name}: top level: expected an object")
    if "format" in data:
        return load_model(text), None
    return load_fragment(text, path.name), frozenset(data)


def expand_directories(paths: list[Path], notes: list[str]) -> list[Path]:
    """Replace a bare DIRECTORY argument with its sorted `*.json` children.

    A directory is what an operator types first, and both commands used to die on the raw
    `[Errno 21] Is a directory` the reader raises. `--help` shows a glob but never says a bare
    directory is refused, so the failure reads as "this command is broken" rather than "add
    `/*.json`" — a live build lost a turn to it on `reconcile`, and `assemble` (printed far more
    often in method.md) had the same edge.

    A path ENDING IN `.json` is never expanded, even when it is a directory: `inner.json/` swept up
    by the caller's own glob must keep raising, or the glob form and the bare-directory form would
    silently disagree about the file set while both exit 0.

    `sorted()` is CODEPOINT order and the shell's glob is locale collation, so the two differ on any
    name leading with an uppercase letter or `_`. Argument order is load-bearing — dedup survivors
    are first-occurrence-in-argument-order — so the expansion is REPORTED rather than claimed to
    match the shell."""
    out: list[Path] = []
    for p in paths:
        if p.is_dir() and p.suffix != ".json":
            children = sorted(p.glob("*.json"))
            out.extend(children)
            notes.append(f"note: {p} expanded to {len(children)} fragment(s), in codepoint order — "
                         f"the shell's glob may order them differently under a non-C locale, and "
                         f"argument order decides which duplicate id survives")
        else:
            out.append(p)
    return out


@dataclass(frozen=True)
class FragmentLoad:
    """What reading a set of fragment files produced: the parts, what was SKIPPED, what FAILED.

    A dataclass rather than a tuple, and deliberately not a NamedTuple — the whole point is that it
    CANNOT be unpacked positionally. `load_fragment_paths` used to return
    `tuple[list[parts], list[str], list[str]]`, and a caller unpacked the two `list[str]`s the wrong
    way round: `notes` (files deliberately skipped) landed in the variable checked as fatal, and
    `errors` (files that failed to load) were assigned to `_` and dropped.

    Both halves of that were bugs, and the dropped-errors half loses data: `fix row`'s safety guard
    re-assembles the fragments to check that an edit does not change which ids survive, and with the
    errors discarded a fragment that failed to load was silently absent from the set it checked — so
    an edit that merged two rules away reported nothing and exited 0.

    NOTHING could catch it. Three positional `list[str]`s type-check in any order, so pyright is
    happy; and the swap is invisible whenever both lists are empty, which is every test that builds
    well-formed fragments. Re-introducing the bug and running the whole suite: 1914 passed. Named
    fields make the mistake unwritable instead of merely testable, which is the only fix that holds.
    """

    parts: list[tuple[str, ProjectModel]]
    #: Files deliberately not read (a `*.draft.json`, a Phase-4 verdicts file, a directory expanded).
    #: ADVISORY — a caller that treats these as failures refuses work `assemble` itself accepts.
    notes: list[str]
    #: Files that should have loaded and did not. FATAL — a caller that ignores these is reasoning
    #: about a fragment set that is missing pieces.
    errors: list[str]


def load_fragment_paths(paths: list[Path]) -> FragmentLoad:
    """Read fragment FILES into `merge_fragments` parts. See `FragmentLoad` for the three results.

    Every path is attempted before returning, so one malformed fragment does not hide the next four —
    the lead re-pings all the guilty agents in one round instead of discovering them one build cycle
    at a time. Printing is the caller's job: `assemble` fails the build on `errors`, `reconcile` does
    the same, and both surface `notes` unchanged.

    Shared because `reconcile` reads the SAME fragments `assemble` does. It used to demand an
    assembled map, which cannot exist yet at the moment a build needs the reconcile file — the
    circular dependency that made every build hand-write `reconcile.json` instead (nine in a row).
    One loader means the verdicts-file skip and the read errors can never drift between the two."""
    parts: list[tuple[str, ProjectModel]] = []
    notes: list[str] = []
    errors: list[str] = []
    for p in expand_directories(paths, notes):
        if p.name.endswith(".draft.json"):
            # The harvest contract tells agents to write `<path>.draft.json` while a fragment is
            # half-written, promising "the draft suffix keeps it out of the assemble glob". It did
            # not: `*.draft.json` matches `*.json`, and nothing here looked at the name. A build was
            # one mistimed assemble away from merging a truncated fragment.
            notes.append(f"note: skipping {p.name} — a draft, still being written")
            continue
        if not p.exists():
            errors.append(f"{p} not found")
            continue
        try:
            # Guarded on purpose: a directory swept up by the glob, a permission error or a bad
            # encoding used to raise straight out of the loop, so every remaining path went
            # unreported and the promise above ("every path is attempted") was false.
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"{p}: cannot read: {e}")
            continue
        try:
            parts.append((p.name, load_fragment(text, p.name)))
        except ModelError as e:
            if _is_verdicts_file(text):
                notes.append(f"note: skipping {p.name} — a Phase-4 verdicts file, not a build "
                             f"fragment (keep verdicts out of build-fragments/ or feed them to "
                             f"`anchor-drift` / `fix apply-drift`, not `assemble`)")
                continue
            errors.append(str(e))
    return FragmentLoad(parts=parts, notes=notes, errors=errors)


def _element_types() -> dict[str, type]:
    """`{"components": Component, "edges": Edge, …}` — derived from `ProjectModel`'s annotations, not
    hard-coded, so a new section joins it automatically instead of silently falling back to "no
    defaults known" (which would quietly stop pruning that section)."""
    out: dict[str, type] = {}
    for name, hint in get_type_hints(ProjectModel).items():
        args = get_args(hint)
        if get_origin(hint) is list and args and isinstance(args[0], type) and is_dataclass(args[0]):
            out[name] = args[0]
    return out


def _prune_defaults(value: object, cls: type | None = None) -> object:
    """Drop keys whose value is just the dataclass default, recursively.

    Without this a fragment survives its own round-trip but every ELEMENT inside it fattens: a
    four-key component comes back with all thirteen fields, nulls and empty lists included. No value
    is lost, but a one-line `fix` then produces a diff across every row it touched, which buries the
    actual edit — and an author reading the file afterwards cannot tell what the tool changed."""
    if isinstance(value, list):
        # `cls` describes the list's ELEMENTS, so it must be carried through the recursion — dropping
        # it here silently disabled all pruning while every test but one still passed.
        return [_prune_defaults(v, cls) for v in value]
    if not isinstance(value, dict):
        return value
    defaults: dict[str, object] = {}
    if cls is not None:
        for f in fields(cls):                     # type: ignore[arg-type]
            if f.default is not MISSING:
                defaults[f.name] = f.default
            elif f.default_factory is not MISSING:  # type: ignore[misc]
                defaults[f.name] = f.default_factory()  # type: ignore[misc]
    out: dict[str, object] = {}
    for k, v in value.items():
        if k in defaults and v == defaults[k]:
            continue
        out[k] = _prune_defaults(v)
    return out


def dump_preserving(m: ProjectModel, present_keys: frozenset[str] | None) -> str:
    """Serialise `m`, keeping a fragment a FRAGMENT.

    `to_canonical_json` writes the whole model shape, so round-tripping a one-section fragment
    through it materialises all 29 sections as empty arrays. That is not cosmetic: a fragment's key
    set IS its ownership claim, and an agent's file that suddenly declares every section can make the
    merge attribute sections nobody authored. So for a fragment only the keys it already had are
    written back, and only the fields that carry a non-default value (`_prune_defaults`) — a fragment
    edit should read as the edit, not as a rewrite of every row it touched."""
    text = to_canonical_json(m)
    if present_keys is None:
        return text
    data = json.loads(text)
    types = _element_types()
    kept: dict[str, object] = {}
    for k, v in data.items():
        if k not in present_keys:
            continue
        kept[k] = _prune_defaults(v, types.get(k))
    return json.dumps(kept, indent=2, ensure_ascii=False) + "\n"


def merge_fragments(parts: list[tuple[str, ProjectModel]],
                    stats: dict[str, int] | None = None,
                    notes: list[str] | None = None) -> tuple[ProjectModel, list[str]]:
    """Merge validated fragments into one model. Returns (model, problems); problems are merge
    conflicts (duplicate IDs across fragments, a singleton stated twice with different values) —
    each names both fragments, so the lead re-pings the right agent instead of hand-fixing JSON.

    Pass a `stats` dict to receive the auto-clean pass counts (actor-endpoint edges stripped,
    duplicate components merged, duplicate edges collapsed) — `main` reports them; test callers that
    omit it are unaffected.

    Pass a `notes` list to receive the NON-blocking merge findings as ready-to-print lines — today
    the keyed-row contradictions (see `_merge_keyed_rows`), which must reach the operator without
    failing the assemble. An out-parameter, exactly like `expand_directories`' own `notes`, so the
    two callers that take neither (`fix`, `reconcile_build`) keep working unchanged."""
    out = ProjectModel()
    problems: list[str] = []
    id_owner: dict[str, str] = {}
    singleton_owner: dict[str, str] = {}
    for label, frag in parts:
        for name in _SINGLETONS:
            val = getattr(frag, name)
            if val in (None, ""):
                continue
            prev = getattr(out, name)
            if prev in (None, ""):
                setattr(out, name, val)
                singleton_owner[name] = label
            elif prev != val:
                problems.append(f"'{name}' stated by both {singleton_owner[name]} and {label} "
                                f"with different values — keep it in ONE header fragment")
        for f in fields(ProjectModel):
            if f.name in _SINGLETONS or f.name == "format":
                continue
            frag_list = getattr(frag, f.name)
            if not isinstance(frag_list, list) or not frag_list:
                continue
            getattr(out, f.name).extend(frag_list)
        seen_here: set[str] = set()
        for attr in ID_ARRAYS:
            for el in getattr(frag, attr):
                # Inside ONE fragment too: two rows with one id assembled to a map carrying both,
                # exit 0, while the help promised a refusal. `validate` blocked it downstream.
                if el.id in seen_here:
                    problems.append(f"duplicate id {el.id}: defined twice inside {label} — one id, "
                                    f"one row")
                seen_here.add(el.id)
                if el.id in id_owner and id_owner[el.id] != label:
                    problems.append(f"duplicate id {el.id}: defined by both {id_owner[el.id]} "
                                    f"and {label} — agents must keep to their pre-allocated ID ranges")
                id_owner.setdefault(el.id, label)
    deps_merged = _merge_duplicate_deps(out)
    actor_stripped = _strip_actor_edges(out)          # actors are never backbone endpoints
    comp_merged = _merge_duplicate_components(out)     # same module harvested by two slices → one
    chan_merged = _merge_duplicate_messaging(out, problems)   # two agents, same example row
    rules_merged = _merge_duplicate_rules(out)         # two block agents, same decision + same lines
    # The sections with no id and no anchor — several slices each describing one setting or one
    # signal. Reports rather than blocks; see `_merge_keyed_rows` for why.
    keyed_merged: dict[str, int] = {}
    keyed_conflicts = 0
    for section in _KEYED_SECTIONS:
        collapsed, conflicts = _merge_keyed_rows(out, section)
        keyed_merged[section.attr] = collapsed
        keyed_conflicts += len(conflicts)
        if conflicts and notes is not None:
            notes.append(_keyed_conflict_note(section, conflicts))
    edges_before_dup = len(out.edges)
    _merge_duplicate_edges(out)  # LAST: dep-merge / actor-strip / component re-point can create exact dups
    eps_before_dup = len(out.entry_points)
    _mint_entry_point_ids(out)   # after every merge, so the minted range has no gaps
    if notes is not None:        # after the minting, so a way in is named by its id
        notes.extend(_shared_anchor_notes(out))
    extras_merged = _merge_extras_headings(out)
    if stats is not None:
        stats["deps_merged"] = deps_merged
        stats["actor_edges_stripped"] = actor_stripped
        stats["components_merged"] = comp_merged
        stats["messaging_rows_collapsed"] = chan_merged
        stats["config_rows_merged"] = keyed_merged["config"]
        stats["observability_rows_merged"] = keyed_merged["observability"]
        stats["keyed_row_contradictions"] = keyed_conflicts
        stats["duplicate_rules_collapsed"] = rules_merged
        stats["duplicate_edges_collapsed"] = edges_before_dup - len(out.edges)
        stats["duplicate_entry_points_collapsed"] = eps_before_dup - len(out.entry_points)
        stats["extras_sections_merged"] = extras_merged
    return out, problems


def _merge_extras_headings(m: ProjectModel) -> int:
    """One section per heading. Returns how many duplicate sections were folded away.

    Extras arrive one per contributing fragment and were simply concatenated, so a live map shipped
    five `Entry-point coverage` sections, three `Balance exceptions` and two `Coverage exceptions`,
    each with different content. That is more than a reading annoyance:

      * `record.append_line` resolves a heading with `next(...)` — the FIRST section. With five
        sections a `--replace` aimed at a line in the third finds the first, matches no prefix and
        reports "nothing replaced", so the documented way to correct a record silently does nothing.
      * a reader of `project-map.md` meets the same heading repeatedly and has no way to know which
        copy the checks read.

    Bodies are concatenated in fragment-argument order, which is the order the reader already sees,
    and blank bodies are dropped so a placeholder section cannot leave a stray blank line. Matching
    is the same case/space-tolerant rule `record` and the readers use — deliberately shared rather
    than a third implementation of "is this the same heading"."""
    from coyomap.record import _resolve_heading
    by_key: dict[str, ExtraSection] = {}
    order: list[str] = []
    for sec in m.extras:
        canonical, _complaint = _resolve_heading(sec.heading)
        key = canonical.strip().lower()
        body = sec.body.strip("\n")
        if key not in by_key:
            by_key[key] = ExtraSection(heading=canonical, body=body)
            order.append(key)
            continue
        keep = by_key[key]
        if body:
            keep.body = f"{keep.body}\n{body}" if keep.body.strip() else body
    merged = len(m.extras) - len(order)
    m.extras = [by_key[k] for k in order]
    return merged


def _merge_duplicate_rules(m: ProjectModel) -> int:
    """Collapse business rules that state the SAME decision at the SAME lines into one, keeping the
    first, and RE-POINT every reference to the merged-away id (`remap_element_ids`). Returns the
    count.

    Two block agents stating one rule is correct input, not an error — exactly like two trace agents
    writing one channel row. Their ids come from disjoint pre-allocated ranges, so the duplicate-ID
    check sees nothing and the map ships the same decision twice. Merging here rather than blocking
    at `validate` follows `_merge_duplicate_messaging`, which exists because blocking a legitimate
    two-agent duplicate made a live build hand-merge.

    Identity is `validate_model.rule_identity` — the normalized statement PLUS the exact site set,
    one implementation shared with the check that catches a hand-edited map. Neither half alone is
    safe: two rules can legitimately share a statement at different lines (a decision enforced by
    two different guards is two rules), and two different decisions routinely share a line."""
    survivor_of: dict[tuple[str, tuple[str, ...]], str] = {}
    by_id = {r.id: r for r in m.rules}
    remap: dict[str, str] = {}
    kept = []
    for r in m.rules:
        ident = rule_identity(r)
        if not ident[0] or not ident[1]:
            kept.append(r)                 # no statement, or no anchored site: not a safe identity
            continue
        if ident in survivor_of:
            remap[r.id] = survivor_of[ident]
            # The survivor keeps its own `risk`/`name` when it has one, and INHERITS the loser's
            # when it does not: both are authored prose with no other home, so dropping one on a
            # merge would lose content the two agents between them did write. `name` matters more
            # than `risk` did — it is MANDATORY, so a survivor that ends up without one does not
            # merely render a blank, it fails `validate` on a field the map actually contained.
            keeper = by_id[survivor_of[ident]]
            if not keeper.risk.strip() and r.risk.strip():
                keeper.risk = r.risk
            if not keeper.name.strip() and r.name.strip():
                keeper.name = r.name
            continue
        survivor_of[ident] = r.id
        kept.append(r)
    if not remap:
        return 0
    m.rules = kept
    remap_element_ids(m, remap)
    return len(remap)


def _merge_duplicate_messaging(m: ProjectModel, problems: list[str]) -> int:
    """Collapse `messaging` rows that are unambiguously the SAME channel, unioning their participants.

    Two agents writing the same channel is correct input, not an error: the trace prompts for two
    different slices embedded the same literal example row, both agents dutifully wrote it, and
    `validate` then BLOCKED the build on `Duplicate messaging channel name(s)`. (`assemble` itself
    exits 0 — it is validate that blocks.) The lead hand-merged, and a hand merge picks a survivor
    where a union keeps what both agents actually found.

    IDENTITY IS `(name, broker)`, not the name alone. Two rows named `jobs` on brokers `D1` and `D9`
    are almost certainly two channels, and silently collapsing them would resolve a real conflict by
    fragment-filename order. A row with no broker is compatible with a named one (in-process is the
    default, so an unset field is "not stated" rather than "different"). Anything genuinely
    contradictory — two different non-empty `kind`, `payload` or `source` — is reported as a merge
    PROBLEM, the same way a singleton stated twice with different values already is, rather than
    guessed at. `_merge_duplicate_components` refuses an ambiguous identity for the same reason.

    Rows are rebuilt rather than mutated: `merge_fragments` extends the FRAGMENTS' own lists into the
    output, so writing through a survivor would edit the caller's fragment objects and make a second
    merge of the same parts produce a different map."""
    order: list[tuple[str, str]] = []
    groups: dict[tuple[str, str], list[MessagingRow]] = {}
    for row in m.messaging:
        name = row.name.strip()
        key = (name, row.broker.strip())
        # A broker-less row joins a named-broker group for the same channel when there is exactly one.
        if not key[1]:
            candidates = [k for k in groups if k[0] == name]
            if len(candidates) == 1:
                key = candidates[0]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    merged: list[MessagingRow] = []
    collapsed = 0
    for key in order:
        rows = groups[key]
        first = rows[0]
        if len(rows) == 1:
            merged.append(first)
            continue
        collapsed += len(rows) - 1
        pubs: list[str] = []
        cons: list[str] = []
        scalars: dict[str, str] = {}
        for row in rows:
            pubs = _union_ids(pubs, row.publishers)
            cons = _union_ids(cons, row.consumers)
            for fname in ("kind", "broker", "payload", "source"):
                val = (getattr(row, fname, "") or "").strip()
                if not val:
                    continue
                prev = scalars.get(fname)
                if prev is None:
                    scalars[fname] = val
                elif prev != val:
                    problems.append(
                        f"messaging channel '{key[0]}' is declared more than once with different "
                        f"`{fname}` values ({prev!r} vs {val!r}) — either these are two different "
                        f"channels (give them different names) or one row is wrong. `assemble` unions "
                        f"participants for the same channel but will not choose between conflicting "
                        f"{fname} values.")
        merged.append(MessagingRow(name=key[0], publishers=pubs, consumers=cons,
                                   **{f: scalars.get(f, "") for f in
                                      ("kind", "broker", "payload", "source")}))
    m.messaging = merged
    return collapsed


@dataclass(frozen=True)
class _KeyedSection:
    """One raw-merging array: which `ProjectModel` field it is, which of its row fields IS the row's
    identity, and what to call one of those keys in a message."""
    attr: str
    key_field: str
    noun: str


_KeyedRow = ConfigRow | ObservabilityRow | ComponentKind

#: The two top-level arrays whose rows are identified by the VALUE OF ONE FIELD and by nothing else:
#: no id to collide on, no anchor to pin them, and no cross-reference pointing in. `config` and
#: `observability` were the last sections in the model that merged RAW — every other array either
#: carries authored ids (caught by the duplicate-id check), or has a dedup pass of its own
#: (`_merge_duplicate_deps`/`_components`/`_messaging`/`_rules`/`_edges`, `_mint_entry_point_ids`),
#: or is blocked downstream by `validate` (a duplicate `deployment[].unit` name).
#:
#: MEASURED BEFORE CHOOSING, on the four live maps (reminderrepo · argus · mcpolis · coyomap), and
#: the measurement is what kept the list at two. Rows merged away per map:
#:
#:   config (by `key`)             18 · 0 · 106 · 8      ← reminderrepo shipped `DATABASE_URL`
#:                                                         THREE times, with three contradicting
#:                                                         defaults; mcpolis shipped one setting
#:                                                         five times
#:   observability (by `signal`)    1 · 0 ·   3 · 0      ← the same defect, smaller
#:
#: And the sections deliberately NOT here, each with the count that ruled it out:
#:
#:   run_commands  0 · 0 · 0 · 0 by `action`. By `command` there are 11/0/2/2, but one command
#:                 legitimately serves two actions, so `action` is the identity and it never repeats.
#:   tests         0 · 0 · 0 · 0 by (`targets`, `label`). By `targets` alone 0/0/1/3 — the label is
#:                 what separates two assessments of one element, so those are two real rows.
#:   deployment    0 everywhere, and `validate` already BLOCKS a duplicate `unit` (it is a `runs_in`
#:                 target, so ambiguity there is a broken view reference, not a reading annoyance).
#:   security      0 rows authored in all four maps, and `duplicate_security_warnings` +
#:                 `coyomap fix dedup-security` already own that shape.
#:   glossary · non_entity_types · environments · subdomains   0 everywhere.
#:
#: `component_kinds` (by `word`) joined later, for a different reason than a measured duplicate: every
#: harvest slice may mint a word, and two slices minting the same one is the EXPECTED case, not a
#: defect. Merging them is what makes a word mean one thing on every component that uses it; two
#: slices that disagree on what it acts as leave both answers in the cell, where `validate` blocks.
_KEYED_SECTIONS: tuple[_KeyedSection, ...] = (
    _KeyedSection(attr="config", key_field="key", noun="config key"),
    _KeyedSection(attr="observability", key_field="signal", noun="observability signal"),
    _KeyedSection(attr="component_kinds", key_field="word", noun="component kind"),
)


def _keyed_identity(row: _KeyedRow, key_field: str) -> str:
    """A keyed row's identity: its key field, whitespace-folded. CASE IS SIGNIFICANT. Empty → none.

    THIS IS THE ONE PLACE THE `_dep_identity` / `_entry_point_identity` CASE-FOLDING RULE DOES NOT
    APPLY, and the difference is the whole point. A dep's name and an entry point's trigger are
    prose; a config key is a case-sensitive IDENTIFIER — an environment variable, a YAML field —
    and `PORT` and `port` are routinely two different settings:

        {"key": "PORT", "purpose": "The port the API server listens on.",  "default": "3000"}
        {"key": "port", "purpose": "The port field of the connection block.", "default": "5432"}

    Folded, those become ONE row keyed `PORT` whose purpose, default and per_env all read
    `more than one answer was found: …`, plus a warning telling the lead to leave one answer in the
    fragments — which would delete a real setting. The map knew both answers cleanly and would have
    asserted confusion about one. Folding was justified here as "free, because no live map has such
    a pair" (still true: 0 of 29, 0 of 47, 0 of 98, 0 of 14), but that is a measurement about maps
    that exist, and the failure it permits destroys data rather than merely reading oddly.

    Whitespace still folds, because a run of spaces in an identifier is a typo and never a
    distinction. Case-folding stays where it belongs — on the ANSWER fields, in `_distinct_answers`,
    where `empty` and `Empty` really are one answer."""
    return " ".join(str(getattr(row, key_field, "") or "").split())


#: What a merged cell says when the slices gave more than one answer. Plain words, because a map
#: reader meets this sentence in the Config table and owes nothing to coyomap's vocabulary. It is
#: the whole point of the design: the cell states that the map is unsure INSTEAD of picking.
_UNSETTLED_LEAD = "more than one answer was found: "

#: Between the answers. ` · ` is already the house cell separator in `views` (the security table
#: joins its anchors with it), and it avoids `|`, which `views._esc` would have to backslash-escape
#: inside a markdown table cell.
_ANSWER_SEP = " · "

# WHY PUTTING EVERY ANSWER IN THE CELL IS AFFORDABLE AT ALL, which is load-bearing for the whole
# design and is the first thing a reader will doubt. `config` and `observability` are among the
# arrays `prose.iter_prose_fields` does NOT walk (checked on all four live maps: no field label or
# value from either section appears in the walk), so a joined cell costs the readability advisory
# and the audit's PAID reading fan-out exactly nothing. If that walk is ever widened to reach these
# two sections, THIS is the decision that has to be re-costed — nothing else here would notice.
# Every other home for these answers does cost today: recording the same content under an
# UNREGISTERED extras heading was measured at 39 → 171 readability findings on mcpolis as a bullet
# list, and still 39 → 81 flattened into one block (reminderrepo 31 → 66). A registered heading
# would be cheap again, because `records.why_of` strips the grammar — but registering one means a
# `HeadingSpec` in `records.py`, and the cell already carries the facts, so that would buy a
# `validate` check rather than rescue content.
#
# The sizes say the same thing. Of the 191 disagreeing fields across the four maps, 112 have exactly
# two answers, 50 have three, 21 have four and 8 have five. MEASURED ON THE FINISHED CELL, lead
# included, because the cell is what ships: median 165 characters, longest 536
# (`MCPOLIS_TEST_SAFE_HTTP_ALLOW_LOOPBACK.purpose`), and 23 of the 191 over 300. An earlier revision
# of this comment said 133 and 504 — it had measured the joined answers and forgotten the 32
# characters of `_UNSETTLED_LEAD` standing in front of them. The five-paraphrase case that reads
# badly is 4% of the total, and it was the case this design was first rejected on.


def _blank(value: object) -> bool:
    return not (value.strip() if isinstance(value, str) else value)


def _distinct_answers(rows: list[_KeyedRow], field_name: str) -> list[str]:
    """Every DIFFERENT non-empty answer the rows give for one field, ordered by content.

    DO NOT SIMPLIFY THIS BACK TO PICKING A SURVIVOR. It returns a LIST, and keeping every answer
    looks like over-engineering until you have the measurement, so this is the function the next
    reader will want to collapse into "take the best one". There is no best one, and that is
    measured rather than assumed:

        Across the four live maps, 191 fields disagree. A PLURALITY rule — the only principled
        tie-break available, since independent agreement between two agents really is evidence —
        finds a winner on 14 of them. The other 177 are 1-1-1 ties, because agents paraphrase and
        no two write the same sentence.

    That one number kills every "pick one" design at once, the deterministic ones included: with
    177 of 191 fields tied, any survivor rule is a coin flip, and a REPRODUCIBLE coin flip is still
    a coin flip. It is also not a hypothetical — the revision this replaced kept the first row, and
    an adversarial reader showed the winner was really decided by `sorted(dir.glob("*.json"))`,
    codepoint order of fragment FILENAMES.

    Three things then make this the whole order-independence fix. Duplicates fold on the normalized
    form, so `empty` and `Empty` are one answer and four slices that agree spend one slot. The
    result is sorted by that same normalized form. And where several spellings fold together, the
    SMALLEST is the one kept, never the first one seen — which is the last place order could still
    leak in, and it did: with `setdefault` here, two mcpolis keys (`MCPOLIS_TEST_MODE` and
    `MCPOLIS_TEST_SAFE_HTTP_ALLOW_LOOPBACK`) still produced four different tables across ten
    fragment orders, because two of their answers differ only in spacing. That leak is invisible to
    a table-level test that only compares whole rows for equality, so it is pinned separately.

    With all three, the answer list — and therefore the merged row's CONTENT — is a function of the
    SET of rows and not of the order they arrived in. (Row ORDER is the other half, and it is
    `_merge_keyed_rows` that settles it, by sorting.)

    TWO CONSEQUENCES THAT ARE CORRECT BUT SURPRISING, stated so nobody reads them as bugs:

      * "Smallest spelling" is codepoint order, so the UGLIER spelling can win: `NO DEFAULT` beats
        `No default`, and `a  b` beats `a b`. Both are deterministic, which is the property being
        bought; neither is a judgement about which reads better, and there is no basis for one.
      * Re-merging a cell that ALREADY holds an answer set nests the lead
        (`more than one answer was found: more than one answer was found: …`). It needs two rows
        that both carry a lead and disagree, so it is reachable only by feeding an assembled map
        back in as a fragment — operator error, and left unguarded rather than papered over."""
    by_norm: dict[str, str] = {}
    for row in rows:
        value = getattr(row, field_name, "")
        if not isinstance(value, str) or _blank(value):
            continue
        norm = " ".join(value.split()).lower()
        text = value.strip()
        prev = by_norm.get(norm)
        by_norm[norm] = text if prev is None else min(prev, text)
    return [by_norm[k] for k in sorted(by_norm)]


def _merge_keyed_rows(m: ProjectModel, section: _KeyedSection) -> tuple[int, list[str]]:
    """Collapse the rows of ONE keyed section that describe the same thing into one row, keeping the
    first. Returns `(rows merged away, the keys whose rows disagreed)`.

    THE DEFECT THIS EXISTS FOR. Several harvest slices each see part of one setting and each author
    a row for it, and nothing deduped them, so a live map's Config screen answered one question three
    different ways: `DATABASE_URL` shipped with `No default`, `a local development database on port
    5435 when nothing is set`, and `No default; the deploy builds it from the database name, account
    and password`, all three at once, with nothing marking them as one setting. A reader has no way
    to tell which is true, and no other check could see it — config rows carry no id to collide on
    and no anchor to pin, so neither the duplicate-id check nor `validate` had anything to read.

    THE IDENTITY IS THE KEY ALONE, and that is stronger than the identities the other five passes
    use, not weaker: `DATABASE_URL` names one setting whatever three agents wrote about it, the same
    way `deployment[].unit` names one unit (which `validate` already blocks on). There is no second
    field that could make two rows with one key into two different things, so there is no `(name,
    broker)` half to add — `_merge_duplicate_messaging` needs one because two brokers really can
    carry a channel of the same name.

    A ROW WITH NO KEY IS NEVER MERGED — the `_dep_identity` / `_component_identity` rule: an
    unidentifiable row keeps its own place rather than being folded into a neighbour.

    THE MERGED ROW IS A FUNCTION OF THE SET OF ROWS, NEVER OF THEIR ORDER, and that is the whole
    design. An earlier revision kept "the first row" and dropped the rest, which an adversarial
    reader broke in one run: the order that decides a build is `sorted(dir.glob("*.json"))` —
    codepoint order of FRAGMENT FILENAMES, which bears no relation to which agent read the
    authoritative code. Merging each live map's fragments in reversed order changed the answer on 16
    of reminderrepo's 29 config keys, 59 of mcpolis's 98 and 4 of coyomap's 14, and six random
    shuffles produced six different tables. That is worse than the defect it replaced: before it, a
    reader saw three contradicting answers and could tell something was wrong; after it, the map
    asserted ONE, confidently, chosen by `sorted()`. So every field is now computed from the whole
    group by `_distinct_answers`, and no permutation can move a merged row's CONTENT.

    AND THE ROWS ARE SORTED BY KEY, which is the second half of that and was missing. Content
    stability is not order stability: the surviving rows still came out in fragment order, so a
    second reviewer built one fragment per live config row and got TEN different tables from ten
    orders — 29 of reminderrepo's 29 row positions moved under a single reversal, 46 of argus's 47,
    97 of mcpolis's 98, 14 of coyomap's 14. `views` and the viewer both render `m.config` in array
    order, so the committed JSON and the on-screen table moved with it. Sorting here is what makes
    "no output depends on fragment order" a true sentence rather than a nearly-true one, and an
    alphabetical Config table is the better one to read anyway.

    WHAT EACH FIELD BECOMES, from the distinct answers the slices gave:

      * NONE → empty, exactly as before.
      * ONE → that answer, whichever row wrote it. This is the inheritance `_merge_duplicate_rules`
        does, and it is why merging ADDS content: a field only one slice filled is a fact the old
        map could not show beside its siblings. 31 facts arrive this way across the live maps, 6 on
        reminderrepo and 25 on mcpolis.
      * TWO OR MORE → all of them, behind `_UNSETTLED_LEAD`. The cell says the map is unsure rather
        than picking, so nothing the slices found leaves the map and nothing false is asserted.

    WHY ALL OF THEM, RATHER THAN THE BEST ONE: because no best one exists — `_distinct_answers`
    carries that measurement, and it is the one to read before changing any of this. WHY KEEPING
    ALL OF THEM IS AFFORDABLE: the comment on `_UNSETTLED_LEAD`, which measures what every other
    home for these answers would cost instead.

    IT REPORTS, IT DOES NOT BLOCK, and the measurement is the argument. `_merge_duplicate_messaging`
    makes its contradiction a merge PROBLEM, which fails the assemble and writes nothing; the same
    rule here would have failed THREE of the four live builds (16 disagreeing config keys on
    reminderrepo, 59 on mcpolis, 4 on coyomap — only argus is clean). A gate that fires on nearly
    every real build teaches the lead to route around it, which is strictly worse than the defect.
    So the finding rides the same non-blocking channel `actor_edges_stripped` uses: a WARNING on
    stderr naming the keys, plus a counter in the assemble digest — and, unlike either of those, the
    MAP now carries the finding too, in the cell itself, where a reader meets it.

    Rows are REBUILT, never mutated: `merge_fragments` extends the FRAGMENTS' own lists into the
    output, so writing a merged value through one of them would edit the caller's fragment objects
    and make a second merge of the same parts produce a different map."""
    rows: list[_KeyedRow] = list(getattr(m, section.attr))
    if not rows:
        return 0, []
    order: list[str] = []
    groups: dict[str, list[_KeyedRow]] = {}
    for n, row in enumerate(rows):
        ident = _keyed_identity(row, section.key_field)
        key = ident or f"\0{n}"          # no key → its own group, so it can never absorb a neighbour
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    merged: list[_KeyedRow] = []
    collapsed = 0
    conflicts: list[str] = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            merged.append(group[0])
            continue
        collapsed += len(group) - 1
        # Every row in a group shares this key up to a run of whitespace (identity does NOT fold
        # case — see `_keyed_identity`), so the spellings differ only in spacing and the smallest is
        # a deterministic, order-free choice among equals. Deliberately NOT `_distinct_answers`,
        # which case-folds: reaching for it here is how the key came to be folded in the first place.
        key_spellings = sorted({str(getattr(r, section.key_field, "") or "").strip()
                                for r in group} - {""})
        values: dict[str, object] = {section.key_field: key_spellings[0] if key_spellings else ""}
        unsettled: list[str] = []
        for f in fields(type(group[0])):
            if f.name == section.key_field:
                continue
            answers = _distinct_answers(group, f.name)
            if len(answers) > 1:
                unsettled.append(f.name)
                values[f.name] = _UNSETTLED_LEAD + _ANSWER_SEP.join(answers)
            else:
                values[f.name] = answers[0] if answers else ""
        merged.append(replace(group[0], **values))
        if unsettled:
            conflicts.append(f"{values[section.key_field]} ({', '.join(unsettled)})")
    # ROW ORDER, the second half of order-independence. Until this sort the rows came out in
    # fragment order, so ten fragment orders gave ten different tables even with every row's
    # CONTENT settled. Keyless rows have nothing to sort on, so they keep their authored order and
    # go last — the `_mint_entry_point_ids` rule, and for the same reason: letting an unidentifiable
    # row take a low position would shuffle the real ones around it.
    keyed = sorted((r for r in merged if _keyed_identity(r, section.key_field)),
                   key=lambda r: _keyed_identity(r, section.key_field))
    setattr(m, section.attr, keyed + [r for r in merged
                                      if not _keyed_identity(r, section.key_field)])
    return collapsed, conflicts


def _keyed_conflict_note(section: _KeyedSection, conflicts: list[str]) -> str:
    """The one WARNING line for a section whose rows disagreed. Count first, then a capped sample,
    then the remedy — `prose.summarize`'s shape, because a build that prints 59 lines prints none a
    reader gets to. Truncation goes through `reporting.shown` so whole-list mode still shows all.

    It says the map KEPT both answers, because it did. An earlier wording said the first answer was
    kept and the rest were gone, which was true of an earlier merge and is the behaviour an
    adversarial reader broke: this line is what a lead reads to decide whether to act, so it must
    describe the map that was actually written."""
    return (f"WARNING: {len(conflicts)} {section.noun}(s) were described more than once, and the "
            f"descriptions disagree. The map states EVERY answer in the field named in brackets, "
            f"so the reader sees that it is unsettled rather than one answer chosen at random: "
            f"{_shown(conflicts, 6, sep='; ', unit=f'{section.noun}(s)')}. Several harvest slices "
            f"each described one {section.noun} from the part of the code it could see — re-read the "
            f"code for the ones that matter and leave ONE answer in the fragments.")


def _union_ids(first: list[str], second: list[str]) -> list[str]:
    """First-seen order, no duplicates — a participant list is a set with a stable reading order."""
    out = list(first)
    for x in second:
        if x not in out:
            out.append(x)
    return out


def _dep_identity(d) -> tuple[str, str]:
    """A dependency's real identity: its kind + normalized name (or package). The same external dep
    discovered by several harvest agents (different ids) shares this."""
    name = (d.name or d.package or "").strip().lower()
    return ((d.kind or "").strip().lower(), name)


def _merge_duplicate_deps(m: ProjectModel) -> int:
    """Collapse deps that share a real identity (kind + normalized name) into ONE row, and RE-POINT
    every edge from the merged-away id to the survivor. Multiple agents discovering the same dependency
    is CORRECT input (not an error), so slicing harvest by directory no longer duplicates deps. Only an
    exact identity match merges — a differing kind is a different identity, left as two rows (never a
    wrong merge). Deterministic: the first occurrence is the survivor.

    Returns how many rows were merged AWAY, so the digest can report it. It used to return None and
    the count reached no reader: a dep merge re-points every C→D edge to the survivor, so a silent
    merge moves edges under a map the operator is reading. Every other auto-clean pass here reports;
    this one was the only one that could change the graph and say nothing."""
    survivor_of: dict[tuple[str, str], str] = {}
    remap: dict[str, str] = {}
    kept = []
    for d in m.deps:
        ident = _dep_identity(d)
        if not ident[1]:            # no name/package → not identifiable, keep as-is
            kept.append(d)
            continue
        if ident in survivor_of:
            remap[d.id] = survivor_of[ident]
        else:
            survivor_of[ident] = d.id
            kept.append(d)
    if not remap:
        return 0
    m.deps = kept
    for e in m.edges:               # edges are the only refs into a dep id (C→D)
        e.src = remap.get(e.src, e.src)
        e.dst = remap.get(e.dst, e.dst)
    return len(remap)


def _entry_point_identity(ep: EntryPoint) -> tuple[str, str, str, str]:
    """An entry point's CONTENT identity — the FULL anchor (line included), the trigger, the owning
    component and the kind, all normalized.

    Every part of that is load-bearing, and the first revision of this function had none of it right.
    It called `strip_anchor`, which DROPS the line (`routes.py:40` -> `routes.py`), so identity was
    really `(file, trigger)` — while the docstring claimed the trigger was there to separate rows
    "registered on the same line". Two genuinely different surfaces anywhere in one router file with
    the same trigger text therefore merged, and the survivor kept only ONE component, kind and
    activation: a `[cron] POST /jobs @ routes.py:99` on C2 vanished behind a `[http-route] POST /jobs
    @ routes.py:40` on C1. A deleted row can never be reported as unclaimed, never appears under
    "Triggered by", and never reaches `--emit-unclaimed`.

    Over-merging is the dangerous direction here — a lost surface is invisible, a duplicated one is
    merely noisy — so the key is deliberately conservative, the same "only an exact identity match
    merges" discipline `_dep_identity` uses."""
    return (ep.source.strip().lower(),
            " ".join((ep.trigger or "").split()).lower(),
            ep.component.strip(),
            " ".join((ep.kind or "").split()).lower())


def _mint_entry_point_ids(m: ProjectModel) -> None:
    """Dedup entry points by content, then assign `EPn` in surviving order.

    Entry points are the one element family whose ids are NOT authored. Harvest agents already juggle
    pre-allocated C/D/E/SF ranges, and nothing references an entry point until synthesis — the
    `use_case.entry_points` trigger link is written by `reconcile`, after this runs — so a fifth range
    would buy nothing and make an overlap a hard build failure. Instead fragments leave `id` empty and
    assembly mints it here, deterministically from argument order.

    Dedup matters independently: unlike components, deps, messaging and edges, entry points were
    simply concatenated, so two harvest slices covering the same router shipped the same route twice.

    NUMBERING IS BY CONTENT, NOT ARGUMENT ORDER. The first revision numbered survivors in
    first-occurrence order like every other dedup, and that made the ids depend on the order the
    fragments happened to be passed in. Since `use_case.entry_points` is authored SEPARATELY (via
    `reconcile`, against the ids a previous assemble produced), swapping two fragments silently
    re-pointed a use case at a different front door — measured: `POST /orders` and
    `DELETE /admin/wipe-database` traded ids, the use case claimed the wrong one, validate resolved
    it happily and the warning count did not move. Sorting by the content key removes that whole
    class: the same set of surfaces gets the same ids however the fragments are ordered.

    NOT ADD-STABLE, and that is now GUARDED rather than merely known: harvesting a new surface that
    sorts before an existing one still shifts the numbers after it, so a reconcile file authored
    against an older harvest points a use case at a different front door — with the id resolving, so
    no other check has anything to object to. The content witness this docstring used to name as the
    future fix has landed: `reconcile` emits `{"id": "EP1", "source": "orders.py:9"}` and
    `validate_reconcile` refuses a file whose witness no longer matches, naming both anchors. A bare
    id stays legal for a hand-authored file and buys no protection."""
    seen: dict[tuple[str, str, str, str], EntryPoint] = {}
    kept: list[EntryPoint] = []
    for ep in m.entry_points:
        ident = _entry_point_identity(ep)
        if not ident[0]:            # no source anchor → not identifiable, keep as its own row
            kept.append(ep)
            continue
        if ident in seen:
            continue                # exact same surface, already recorded
        seen[ident] = ep
        kept.append(ep)
    # Anchorless rows have no content key to sort by, so they keep authored order and go last —
    # they are the un-identifiable tail, and giving them low numbers would let an unanchored row
    # shuffle the ids of every real surface.
    anchored = sorted((ep for ep in kept if ep.source.strip()), key=_entry_point_identity)
    loose = [ep for ep in kept if not ep.source.strip()]
    ordered = anchored + loose
    for n, ep in enumerate(ordered, start=1):
        ep.id = f"EP{n}"
    m.entry_points = ordered


def _shared_anchor_notes(m: ProjectModel) -> list[str]:
    """WARNING lines for the near-duplicates the merges above leave in place: two parts at one
    `file:line` under different names, and two ways in of one kind at one `file:line` owned by
    different parts.

    The merges take only an exact identity, on purpose (`_component_identity`,
    `_entry_point_identity`): over-merging loses a row nobody can see. But a near-duplicate is
    then silent. On the 2026-10-08 mcpolis build two slices each wrote the dashboard's route table
    as a part, under two names at `App.tsx:189`, and two slices each wrote 6 ways in at the same
    lines of `app.py` with different owners. Neither assemble nor validate said a word; the lead
    found them by dumping all 256 ways in.

    Ways in that differ only in their trigger are not reported: one call that registers several
    routes is one line holding several ways in, all owned by one part. A part or a way in with no
    line in its anchor is not reported either: a file holds many of each."""
    def at_line(source: str | None) -> str:
        src = (source or "").strip().lower()
        return src if LINE_ANCHOR.search(src) else ""
    parts: dict[str, list[str]] = {}
    for c in m.components:
        if at_line(c.source):
            parts.setdefault(at_line(c.source), []).append(f"{c.id} '{c.name}'")
    doors: dict[tuple[str, str], list[str]] = {}
    for ep in m.entry_points:
        if at_line(ep.source):
            key = (at_line(ep.source), " ".join((ep.kind or "").split()).lower())
            doors.setdefault(key, []).append(f"{ep.id} on {ep.component or 'no part'}")
    owners = {k: v for k, v in doors.items()
              if len({row.rsplit(" on ", 1)[1] for row in v}) > 1}
    out: list[str] = []
    shared = [f"{' and '.join(v)} at {k}" for k, v in sorted(parts.items()) if len(v) > 1]
    if shared:
        out.append(f"WARNING: {len(shared)} code line(s) anchor more than one part, under "
                   f"different names: {_shown(shared, 6, sep='; ', unit='line(s)')}. Two slices "
                   f"probably harvested one part twice. Keep one: drop the other from its fragment "
                   f"and point its references at the one you keep.")
    if owners:
        rows = [f"[{kind}] {' and '.join(v)} at {src}" for (src, kind), v in sorted(owners.items())]
        out.append(f"WARNING: {len(rows)} code line(s) hold ways in of one kind owned by different "
                   f"parts: {_shown(rows, 6, sep='; ', unit='line(s)')}. Two slices probably wrote "
                   f"one way in twice. Keep the one whose part really runs it, and drop the other "
                   f"from its fragment.")
    return out


def _merge_duplicate_edges(m: ProjectModel) -> None:
    """Collapse backbone edges that are the SAME relationship at the SAME call site — identical
    `(src, verb, dst, where)` with a CONCRETE `where` — into one, keeping the first (deterministic).
    Parallel trace agents each independently emit the same `C→E`/`enforces` edge; nothing deduped
    them, so the stored map + markdown table carried the redundant rows. Merging on a real anchor is
    SAFE — the exact `file:line` pins the fact, so it is unambiguously one edge; only the `why`
    rationale varies in wording (both describe the same fact), and the backbone keeps one `why` per
    edge (the differing prose belongs in the T6 flow steps).

    A `no_call_site` edge (null `where`) is NEVER merged — with no anchor to disambiguate, a differing
    `why` may be the only signal that two DISTINCT couplings exist (two events on the same C→C pair),
    so those fall through to `validate`'s duplicate-edge warning for a human to reconcile. Likewise an
    edge that shares `(src, verb, dst)` but points at a DIFFERENT anchor is left as-is (which call
    site is the true one — a duplicate once masked a wrong anchor). Mirrors `_merge_duplicate_deps`:
    only an unambiguous identity merges, never a wrong one."""
    seen: set[tuple[str, str, str, str]] = set()
    kept = []
    for e in m.edges:
        if not e.where:                        # no concrete anchor → can't safely disambiguate; keep
            kept.append(e)                     # (validate's duplicate-triple warning surfaces these)
            continue
        key = (e.src, e.verb, e.dst, e.where)
        if key in seen:
            continue
        seen.add(key)
        kept.append(e)
    m.edges = kept


def _strip_actor_edges(m: ProjectModel) -> int:
    """Drop backbone edges whose endpoint is an actor (a Role id). The edge list connects
    components / deps / entities ONLY — an actor's participation lives in a T6 flow STEP, never the
    backbone (method.md). A trace agent that emits `R3 → C5` is a PROMPT DEFECT, not correct input
    (unlike the same dep found by two harvest agents), so `main` reports a non-zero count as a
    WARNING for the lead to fix the trace prompt at the source. Returns the number stripped."""
    role_ids = {role.id for role in m.roles}
    if not role_ids:
        return 0
    kept = [e for e in m.edges if e.src not in role_ids and e.dst not in role_ids]
    n = len(m.edges) - len(kept)
    m.edges = kept
    return n


def _component_identity(c) -> tuple[str, str] | None:
    """A component's merge identity: `(normalized FILE source anchor, normalized name)`, or None when
    it can't be safely deduped — no source, a DIRECTORY-anchor source (a shared directory is not
    identity: two different components legitimately live under one dir), or no name. Only a real file
    anchor + matching name means "the same module harvested by two overlapping slices" (the transcript
    case). Deliberately stricter than `_dep_identity`: a component key is far more consequential."""
    src = (c.source or "").strip()
    if not src or src.endswith("/"):        # missing, or a directory anchor → not a safe identity
        return None
    name = (c.name or "").strip().lower()
    if not name:
        return None
    return (src.lower(), name)


def _merge_duplicate_components(m: ProjectModel) -> int:
    """Collapse components that are the SAME module harvested twice by overlapping slices — identical
    normalized `(file source, name)` — into ONE, keeping the first (deterministic), and RE-POINT every
    reference to the merged-away id via `remap_element_ids` (the COMPLETE inbound set — edges, flow/
    sub-flow steps, entry-point owners, test targets, and `[[Cn]]` prose — so nothing is left dangling
    for `validate` to block on). Mirrors `_merge_duplicate_deps`; only an unambiguous file+name
    identity merges (a directory-anchored or nameless component is never merged). Returns the count."""
    survivor_of: dict[tuple[str, str], str] = {}
    remap: dict[str, str] = {}
    kept = []
    for c in m.components:
        ident = _component_identity(c)
        if ident is None:
            kept.append(c)
            continue
        if ident in survivor_of:
            remap[c.id] = survivor_of[ident]
        else:
            survivor_of[ident] = c.id
            kept.append(c)
    if not remap:
        return 0
    m.components = kept
    remap_element_ids(m, remap)
    return len(remap)


# Ignored inside `<out>/.gitignore`: per-run scratch, per-run reports, and the developer-only archive
# of previous maps (`dev-rebuilds/`, written by `coyomap-eval archive` — a coyomap-developer
# convention, never a user artifact, and never committed). `finalize-report.*` is
# regenerated by every `coyomap finalize`, so committing it would put a diff on every build; it is a
# working artifact to READ, not a deliverable. Listed here so the command that creates it also owns
# its lifecycle, instead of leaving it to be swept up by someone's `git add -A`.
# `fanout-timings.json` is build telemetry that `timings` keeps beside the map for the NEXT
# build's dispatch order — cross-build input, never map content, so it stays local like the
# archive does.
# The build state (`coyomap state`) and the findings the agents file (`coyomap findings`) are the
# build's own working memory: the state is archived with its map and the findings reach the
# operator through the reports, so neither is ever committed. Their names come from `uncommitted`,
# the list `finalize` and `coyomap credentials` read to tell a file no commit takes.
_GITIGNORE_KEEP: tuple[str, ...] = ("build-fragments/", "finalize-report.json",
                                   "finalize-report.md", "dev-rebuilds/", "fanout-timings.json",
                                   *uncommitted.IGNORE_LINES)
# `preindex.json` is a COMMITTED artifact (the viewer's symbol search reads it, pinned to the map's
# commit), so it must NOT be ignored. Strip any stray ignore line (an older build, a hand edit) so it
# can't drift back out of version control. Match the plain name and a root-anchored form.
_GITIGNORE_DROP = {"preindex.json", "/preindex.json"}


def ensure_fragments_ignored(out_dir: Path) -> bool:
    """Normalize `<out>/.gitignore`: ensure every per-run artifact IS ignored (`build-fragments/`, the
    agents' scratch dir, and `finalize-report.{json,md}`, rewritten on every pre-commit read) so a build
    never dirties the tree, and ensure `preindex.json` is NOT ignored so the committed pre-index the
    viewer relies on stays in version control. Any other lines are left untouched. Returns True when
    the file changed (created, an entry added, or a stray preindex ignore stripped)."""
    gi = out_dir / ".gitignore"
    old_lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    new_lines = [ln for ln in old_lines if ln.strip() not in _GITIGNORE_DROP]
    present = {ln.strip() for ln in new_lines}
    for entry in _GITIGNORE_KEEP:
        if entry not in present:
            new_lines.append(entry)
    if new_lines == old_lines:
        return False
    gi.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv or not argv:
        print("usage: coyomap assemble <fragment.json>... --out <dir> [--reconcile <file>]\n\n"
              "Merge build agents' structured-row fragments into the canonical project-map.json\n"
              "(+ the generated markdown view; the diagram is served, never written) in <dir>.\n"
              "Each fragment is a PARTIAL model (any subset of the top-level arrays; one header\n"
              "fragment may carry title/goal/commit). A malformed fragment or a duplicate ID\n"
              "fails loudly with the fragment named — nothing is silently fixed up; run\n"
              "`coyomap validate` on the result to catch anything else wrong.\n\n"
              "--reconcile <file>: a declarative reconcile input applied AFTER the merge (and after\n"
              "  entity-edge derivation), BEFORE the write — so a re-assemble always re-applies it.\n"
              "  `set` bulk-assigns subsystem/subdomain/runs_in/bucket; `drop_edges` removes refuted\n"
              "  edges and heals the flow steps that rode them. Keep this file OUTSIDE\n"
              "  build-fragments/ (e.g. .coyomap/reconcile.json) so the fragment glob does not sweep it.\n"
              "  The shape, in full (generate the `set` half with `coyomap reconcile --rules`):\n"
              "    {\n"
              '      "set": [ {"ids": ["C1","C2"], "subsystem": "S3"},\n'
              '               {"ids": ["C40"], "runs_in": ["worker"]},\n'
              '               {"ids": ["E7"], "subdomain": "SD2"},\n'
              '               {"ids": ["D5"], "bucket": "Data & storage"} ],\n'
              '      "drop_edges": [ {"src": "C21", "verb": "persists", "dst": "E33"},\n'
              '                      {"src": "C7", "verb": "calls", "dst": "C9",\n'
              '                       "drop_steps": true},\n'
              '                      {"src": "C4", "verb": "reads", "dst": "E2",\n'
              '                       "repoint": "E5"} ]\n'
              "    }\n"
              "  A `drop_edges` entry defaults to REPORTING the flow steps that rode the edge; add\n"
              "  `drop_steps: true` to remove them, or `repoint: <id>` to re-point them. A report-only\n"
              "  C→E drop leaves the step behind, and the NEXT assemble re-derives the edge from it —\n"
              "  so heal it, or the drop does not stick. Zero matches WARNS, never fails.\n\n"
              "<dir>/.gitignore gets a 'build-fragments/' entry so the scratch dir never\n"
              "dirties the tree. Then run the usual invariant: validate --check-sources → audit → render.")
        return 0 if ("-h" in argv or "--help" in argv) else 2
    out_dir: Path | None = None
    reconcile_path: Path | None = None
    frags: list[Path] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--out":
            i += 1
            if i >= len(argv):
                print("ERROR: --out needs a directory", file=sys.stderr)
                return 2
            out_dir = Path(argv[i])
        elif a == "--reconcile":
            i += 1
            if i >= len(argv):
                print("ERROR: --reconcile needs a file", file=sys.stderr)
                return 2
            reconcile_path = Path(argv[i])
        elif a.startswith("-"):
            print(f"ERROR: unknown option '{a}'", file=sys.stderr)
            return 2
        else:
            frags.append(Path(a))
        i += 1
    if out_dir is None:
        print("ERROR: --out <dir> is required", file=sys.stderr)
        return 2
    if not frags:
        print("ERROR: no fragments given", file=sys.stderr)
        return 2
    loaded = load_fragment_paths(frags)
    parts, notes, errors = loaded.parts, loaded.notes, loaded.errors
    for note in notes:
        print(note, file=sys.stderr)
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    if errors:
        print("ASSEMBLY FAILED: fix (or re-request) the fragments above; nothing was written.",
              file=sys.stderr)
        return 1
    stats: dict[str, int] = {}
    merge_notes: list[str] = []
    model, problems = merge_fragments(parts, stats, merge_notes)
    if problems:
        for pr in problems:
            print(f"ERROR: {pr}", file=sys.stderr)
        print("ASSEMBLY FAILED: merge conflicts above; nothing was written.", file=sys.stderr)
        return 1
    for note in merge_notes:          # non-blocking merge findings (keyed-row contradictions)
        print(note, file=sys.stderr)
    if stats.get("config_rows_merged") or stats.get("observability_rows_merged"):
        print(f"note: merged {stats.get('config_rows_merged', 0)} duplicate config row(s) and "
              f"{stats.get('observability_rows_merged', 0)} duplicate observability row(s) "
              f"(several harvest slices each describing one setting or one signal)")
    if stats.get("actor_edges_stripped"):
        print(f"WARNING: stripped {stats['actor_edges_stripped']} actor-endpoint edge(s) — edges "
              f"connect components/deps/entities only, never actors. This is a trace-prompt defect: "
              f"fix the prompt so agents put actor participation in flow STEPS, not the backbone.",
              file=sys.stderr)
    if stats.get("components_merged"):
        print(f"note: merged {stats['components_merged']} duplicate component(s) "
              f"(same file harvested by overlapping slices)")
    if stats.get("duplicate_edges_collapsed"):
        print(f"note: collapsed {stats['duplicate_edges_collapsed']} duplicate backbone edge(s) "
              f"(same call site)")
    derived = _derive_entity_edges(model, stats)
    if derived:
        shown = _shown(derived, 8)   # via the shared helper, so a report mode can widen it
        print(f"note: derived {len(derived)} C→E backbone edge(s) from entity flow-steps that had "
              f"none (verb inferred from the step; ambiguous → reads): {shown}")
    # `--reconcile` is applied AFTER `_derive_entity_edges` (B1): a `drop_edges` on a C→E edge must run
    # after the derive, or the derive re-creates the just-dropped edge from its surviving flow step.
    rec_stats: dict[str, object] = {}
    if reconcile_path is not None:
        if not reconcile_path.exists():
            print(f"ERROR: --reconcile {reconcile_path} not found", file=sys.stderr)
            return 1
        try:
            rec = load_reconcile(reconcile_path.read_text(encoding="utf-8"), reconcile_path.name)
        except ReconcileError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            print("ASSEMBLY FAILED: bad reconcile file; nothing was written.", file=sys.stderr)
            return 1
        rec_problems = validate_reconcile(model, rec)
        if rec_problems:
            for pr in rec_problems:
                print(f"ERROR: {pr}", file=sys.stderr)
            print("ASSEMBLY FAILED: reconcile directives above are invalid; nothing was written.",
                  file=sys.stderr)
            return 1
        rec_notes = apply_reconcile(model, rec, rec_stats)
        for note in rec_notes:
            print(note, file=sys.stderr if note.startswith("WARNING") else sys.stdout)
        sc = rec_stats.get("reconcile_set", {})
        set_summary = (", ".join(f"{k}: {v}" for k, v in sc.items() if v)
                       if isinstance(sc, dict) else "") or "nothing"
        # The unhealed-riding-step count is repeated here AND carried in `_assemble_digest`'s `ops:`
        # string. The digest is the one that matters: this note is line 9 of 13 on a fresh assemble,
        # so `| tail -4` — how a live build actually read this output — cuts it, and the two orphaned
        # steps only surfaced a round later at validate, costing a fragment edit, a re-assemble and a
        # re-run of apply-drift. Repeating it costs a clause and covers the reader who sees only the
        # head as well as the one who sees only the tail.
        unhealed = rec_stats.get("reconcile_riding_unhealed", 0)
        unhealed_tail = (
            f" {unhealed} flow step(s) still attribute a dropped edge and are NOT healed — heal them "
            f"with `drop_steps` / `repoint` (a report-only C→E drop leaves the step, which the next "
            f"assemble re-derives into the edge you just dropped)."
            if isinstance(unhealed, int) and unhealed else "")
        print(f"note: reconcile applied — set {{{set_summary}}}; "
              f"drop_edges: {rec_stats.get('reconcile_edges_dropped', 0)} edge(s); "
              f"keep_edges: {rec_stats.get('duplicate_edges_resolved', 0)} duplicate(s) resolved; "
              f"set_anchors: {rec_stats.get('anchors_corrected', 0)} anchor(s) "
              f"corrected.{unhealed_tail}")
    elif out_dir is not None and (out_dir / "reconcile.json").exists():
        # S8: a reconcile file is present but was NOT passed — an assemble without it silently reverts
        # every synthesis/trace assignment. Nudge, don't guess (the lead may have meant to omit it).
        print(f"note: {out_dir / 'reconcile.json'} exists but --reconcile was not passed — this "
              f"assemble did NOT apply it, so any subsystem/subdomain/runs_in/bucket/drop it holds is "
              f"absent from the written map. Re-run with `--reconcile {out_dir / 'reconcile.json'}`.",
              file=sys.stderr)
    # THE HARVEST POINTER, once synthesis has answered it. After `--reconcile`, which is what links a
    # dep to its surface, and on every assemble, because the fragment keeps the pointer.
    cleared = _drop_answered_interface_pointers(model)
    stats["interface_pointers_cleared"] = len(cleared)
    if cleared:
        print(f"note: dropped the harvest 'Not decided here' pointer from {len(cleared)} dep(s) "
              f"that now name their surface: {_shown(cleared, 8)}")
    if reconcile_path is not None:
        # Only once synthesis has run: before it every pointer is undecided, and rightly so.
        undecided = [d.id for d in undecided_interface_pointers(model)]
        if undecided:
            # Where the fragments ARE, never `<out>/build-fragments`: see `_fragments_folder`.
            home = _fragments_folder(frags)
            where = home if home is not None else "<the folder of the fragment that declares it>"
            print(f"note: {len(undecided)} dep(s) still carry the harvest 'Not decided here' "
                  f"pointer and name no surface: {_shown(undecided, 8)}. Decide each one: link it "
                  f"to its surface (`interfaces` in the reconcile file), or replace the pointer "
                  f"with the reason it is none (`coyomap fix row --fragments {where} --id <Dn> "
                  f"--set-not-an-interface \"<why>\"`).", file=sys.stderr)
    from coyomap.views import model_to_markdown

    _stamp_tool_build(model)

    # THE WRITE SIDE OF THE SAME GUARD, and the destructive half of the incident it exists for. A
    # read of the clone's own map produces a wrong answer; a WRITE replaces the clone's committed
    # map, which is what the 2026-09-02 build did. `assemble` is the only verb that writes one.
    guard_wrong_map(out_dir / "project-map.json")
    out_dir.mkdir(parents=True, exist_ok=True)
    # WHOLE OR NOT AT ALL: agents read the map while the lead assembles it, and a map rewritten in
    # place can be read half-written. The 2026-09-30 mcpolis lead handed its rules and tests agents a
    # copy instead, and that copy predated the gap-fill: 121 of 143 gap-fill edges were missing.
    write_whole(out_dir / "project-map.json", to_canonical_json(model))
    write_whole(out_dir / "project-map.md", model_to_markdown(model))
    # The interactive viewer is served live by `coyomap serve` (built on demand from the model), so no
    # HTML file is written here — registering the folder is enough for the server to pick it up.
    from coyomap.viewer.recents import register_project  # registers the project with `coyomap serve` (best-effort)
    register_project(out_dir)
    if ensure_fragments_ignored(out_dir):
        print(f"note: added 'build-fragments/' to {out_dir / '.gitignore'}")
    for note in _unconsumed_fragment_notes(out_dir, frags):
        print(note, file=sys.stderr)
    print(f"Assembled {len(parts)} fragment(s) -> {out_dir / 'project-map.json'} "
          f"(+ generated markdown view)")
    # WS-T2: a self-describing one-line digest of WHAT this assemble did, so a transcript audit (builds
    # alias the CLI) can see the auto-clean + reconcile effects without reverse-engineering a script.
    digest = _assemble_digest(model, stats, rec_stats)
    print(f"  {digest}")
    buildstate.append(buildstate.repo_of(out_dir), "assemble",
                      state_text(frags, len(parts), out_dir, reconcile_path, digest))
    print(f"Next: coyomap validate {out_dir / 'project-map.json'} --check-sources")
    # AND, once the skeptics have voted, the verb that runs the whole close. A build follows these
    # `Next:` lines literally; the close was hand-typed over 57 turns on a build where `ship` was
    # named nowhere it would be seen.
    # TWO LINES, both runnable. The premise of naming the next verb is that a build pastes these
    # literally, so a parenthetical inside the command (`coyomap ship . (prepare)`) is a shell
    # parse error dressed as advice. `out_dir.parent` is `.` under the documented `--out .coyomap`.
    # ONLY for a map in a `.coyomap` folder: `ship <repo>` closes `<repo>/.coyomap`, so for any other
    # `--out` the lines named a repo whose map is another one, or none (the same review as
    # `_fragments_folder`: `--out <dir>/out` was told `coyomap ship <dir>`).
    if out_dir.name != ".coyomap":
        print(f"      (`coyomap ship <repo>` closes the map at <repo>/.coyomap, so it does not close "
              f"the map at {out_dir})")
        return 0
    print(f"      then, once the verdicts are in — PREPARE, read the report it ends on:")
    print(f"        coyomap ship {out_dir.parent}")
    print(f"      then FINISH, with the note you wrote from that report:")
    print(f"        coyomap ship {out_dir.parent} --note-file <path>")
    return 0


#: Every mutation counter the assemble can record, in digest display order: the `stats` key and the
#: phrase the digest prints for it. THIS TABLE IS THE DIGEST — `_assemble_digest` iterates it and
#: hand-writes nothing, so a counter cannot be computed and then go unreported.
#:
#: It WAS a hand-written chain of `if stats.get(...)` branches, and three of the eight counters had no
#: branch at all: `duplicate_rules_collapsed`, `duplicate_entry_points_collapsed`, and `deps_merged`
#: (which did not exist — the pass returned None). Two real map changes were traced to that silence:
#: editing ONE rule's statement in a fragment splits a merged rule and mints an id that did not exist
#: before, and re-anchoring ONE entry point re-sorts the minted range so a fifth of the EP ids point at
#: a different surface. Both printed `ops: none`. `tests/test_assemble.py` parses this module for
#: `stats[...]` writes and fails when one is missing here — the half a comment cannot enforce.
_STATS_LABELS: tuple[tuple[str, str], ...] = (
    ("actor_edges_stripped", "actor-edges stripped"),
    ("deps_merged", "deps merged"),
    ("components_merged", "components merged"),
    ("duplicate_rules_collapsed", "dup-rules collapsed"),
    ("duplicate_edges_collapsed", "dup-edges collapsed"),
    ("duplicate_entry_points_collapsed", "dup-entry-points collapsed"),
    ("entity_edges_derived", "C→E edges derived"),
    ("messaging_rows_collapsed", "messaging rows collapsed"),
    ("config_rows_merged", "config rows merged"),
    ("observability_rows_merged", "observability rows merged"),
    # The number that matters most of the three: keys whose slices disagreed, so the merged cell
    # states every answer instead of one. The two counts above it are the tidy-up; this one is the
    # map's own honesty, and it rides the digest because the digest is the line a transcript audit
    # reads when the warning above has scrolled away.
    ("keyed_row_contradictions", "config/observability keys left unsettled (every answer kept)"),
    ("extras_sections_merged", "extras sections merged"),
    ("interface_pointers_cleared", "harvest interface pointers cleared"),
)

#: The same contract for the `--reconcile` counters, which live in a second dict built by
#: `reconcile.apply_reconcile`. `reconcile_set` (per-field counts) and `reconcile_riding_unhealed`
#: (a warning, not a plain count) are rendered by hand below and are named in `_REC_STATS_CUSTOM` so
#: the completeness test can see they are accounted for rather than forgotten.
_REC_STATS_LABELS: tuple[tuple[str, str], ...] = (
    ("duplicate_edges_resolved", "reconcile keep_edges"),
    ("reconcile_edges_dropped", "reconcile drop_edges"),
    ("anchors_corrected", "reconcile set_anchors"),
    ("reconcile_relations_dropped", "reconcile drop_relations"),
)

_REC_STATS_CUSTOM: frozenset[str] = frozenset({"reconcile_set", "reconcile_riding_unhealed"})


def _assemble_digest(model: ProjectModel, stats: dict[str, int], rec_stats: dict[str, object]) -> str:
    """One-line, self-describing summary of the assemble: the resulting inventory plus every mutation
    the auto-clean passes and `--reconcile` made (all zero-suppressed) — the WS-T2 transcript trail."""
    inv = {"C": len(model.components), "D": len(model.deps), "E": len(model.entities),
           "edges": len(model.edges), "S": len(model.subsystems), "SD": len(model.subdomains)}
    parts = [f"model: {', '.join(f'{k}:{v}' for k, v in inv.items() if v)}"]
    ops: list[str] = []
    for key, label in _STATS_LABELS:        # the table IS the digest — see _STATS_LABELS
        if stats.get(key):
            ops.append(f"{label} {stats[key]}")
    sc = rec_stats.get("reconcile_set", {})
    if isinstance(sc, dict) and any(sc.values()):
        ops.append("reconcile set " + "/".join(f"{k}:{v}" for k, v in sc.items() if v))
    # `keep_edges` removed 51 edges on a real map and the digest said nothing — the same silent
    # delta the directive was added to stop. `set_anchors` exists because 14 corrected anchors
    # were once lost silently; applying them silently is the same failure with the sign flipped.
    # Both are rows in `_REC_STATS_LABELS` now, so neither can be dropped by editing this loop.
    for key, label in _REC_STATS_LABELS:
        value = rec_stats.get(key)
        if isinstance(value, int) and value:
            ops.append(f"{label} {value}")
    # Unhealed riding steps belong HERE, in the digest, not on the reconcile note further up: the
    # note is line 9 of 13 on a fresh assemble, so `| tail -4` (how a live build read this output)
    # cuts it, while the digest is always in the last three lines. A report-only `drop_edges` that
    # leaves steps behind is a pending edit — the next assemble re-derives the C→E edge from the
    # surviving step — so it has to reach the reader who only sees the tail.
    if rec_stats.get("reconcile_riding_unhealed"):
        ops.append(f"UNHEALED riding steps {rec_stats['reconcile_riding_unhealed']} "
                   f"(heal with drop_steps/repoint)")
    parts.append("ops: " + ("; ".join(ops) if ops else "none"))
    return " | ".join(parts)



def state_text(frags: list[Path], count: int, out_dir: Path, reconcile_path: Path | None,
               digest: str) -> str:
    """The build-state line of one assemble: what it read, where it wrote, whether it reconciled,
    and its digest. After a summary, `--reconcile` is the flag a re-assemble most easily loses, and
    an assemble without it silently reverts every assignment the reconcile file holds."""
    folders = sorted({str(p.parent) for p in expand_directories(frags, [])})
    read = _shown([f"{folder}/*.json" for folder in folders], 3)
    rec = f"--reconcile {reconcile_path}" if reconcile_path is not None else "no --reconcile"
    return f"{count} fragments ({read}) --out {out_dir} {rec} · {digest}"


def _stamp_tool_build(model: ProjectModel) -> None:
    """Record WHICH coyomap produced this map, beside the analysed repo's own commit.

    A map is only comparable against another when you know the tool that made each. `compare`
    once reported REGRESSED for a map that was simply newer: auth surfaces had moved from their
    own table into business rules — a documented breaking change with no migration — and nothing in
    either map said which side of it that map was built on. The same blindness makes a retrospective
    quote a tool bug that was fixed hours earlier.

    Best-effort: a coyomap installed outside a git clone has no commit to report, and a map that
    predates this stamp carries nothing. Both read as unknown, never as equal.
    """
    from coyomap.provenance import git_value
    home = Path(__file__).resolve().parents[2]
    if not (home / ".git").exists():
        # An ordinary install puts the package under `site-packages/`, so there is no clone and
        # nothing honest to record. Left as None, which `compare` reports as unknown.
        return
    # `--dirty` because a development clone is the NORMAL case, and without it a map built from
    # modified working-tree code is stamped with a commit that does not contain that code. That is
    # a false provenance record, and a false one is worse than none: the whole point is to tell a
    # reader which tool produced the map.
    model.tool_commit = git_value(home, "describe", "--always", "--dirty", "--abbrev=7")
    model.tool_committed = git_value(home, "log", "-1", "--format=%cd", "--date=short")


def _fragments_folder(frags: list[Path]) -> Path | None:
    """The one folder the fragments were read from, for a command that edits them: a directory
    argument is that folder, a file argument the folder that holds it (`expand_directories` decides
    which is which). None when they came from more than one folder, so the command names no folder
    rather than the wrong one.

    Never `<out>/build-fragments`: `--out` says where the map is WRITTEN, and the fragments may sit
    anywhere. Built from `--out`, the undecided-pointer note sent an assemble with `--out <dir>/out`
    to edit `<dir>/out/build-fragments`, a folder that did not exist (the review of the 2026-10-07
    fixes)."""
    folders = {p.parent.resolve(): p.parent for p in expand_directories(frags, [])}
    return next(iter(folders.values())) if len(folders) == 1 else None


def _unconsumed_fragment_notes(out_dir: Path, consumed: list[Path]) -> list[str]:
    """Warn about fragments sitting in `<out>/build-fragments/` that were NOT passed to assemble — a
    sub-agent that wrote to the wrong folder (`voice/.coyomap/…`) or a stale file the lead forgot. A
    silently-dropped fragment reads as "assembled everything" when a whole slice is missing."""
    frag_dir = out_dir / "build-fragments"
    if not frag_dir.is_dir():
        return []
    consumed_resolved = {p.resolve() for p in consumed}
    strays = [f for f in sorted(frag_dir.glob("*.json")) if f.resolve() not in consumed_resolved]
    return [f"note: {frag_dir / f.name} is in build-fragments/ but was NOT assembled — a sub-agent may "
            "have written to the wrong path, or it is stale; pass it, delete it, or move a "
            "superseded raw fragment into build-fragments/raw/ (subdirectories are not scanned)."
            for f in strays]


if __name__ == "__main__":
    raise SystemExit(main())
