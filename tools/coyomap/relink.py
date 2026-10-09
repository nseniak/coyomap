#!/usr/bin/env python3
"""`coyomap changes relink` — an update keeps the more precise line its skeptics read.

WHY. A skeptic who confirms a statement cites the line it read. When that line is in the same file
and close to the map's link (the link sits on a function header, a `try:`, or one or two lines off),
the build's closing step moves the link there (`fix apply-drift`). An update had no such step: on
the 2026-10-09 mcpolis update 12 confirmed verdicts cited a better line, and all 12 were dropped.

WHAT IT DOES. After the wave and its closer, before `changes apply`:

  for each confirmed statement whose skeptics read a better line (same file, the move allowed):
    the link sits in a row the log adds      → corrected inside that added row
    an entry of the log edits that link      → corrected in that edit's new value
    otherwise                                → one row in the log's `relinked` list (link-only)
    the statement's text changes with its link (a rule site names its line), so this wave's
      verdicts and batches are re-keyed to the new text, the old text kept in `claim_was`

The corrections are planned by `fix.plan_drift_corrections`, the same planner `fix apply-drift`
uses: the strict majority, the drift exceptions the map records, the refusal of a move that leaves
the definition, the refusal of a file neither end of an arrow lists. Without `--write` it prints and
writes nothing. Stdlib-only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coyomap.audit_model import l2_worklist_model, resolve_claim
from coyomap.challenge import pin_for, read_rows, rekey_rows, wave_files
from coyomap.changelog import (ChangeLog, Relink, _applied, dump_log, edge_id, edge_ids, get_field,
                               index_map, load_log, set_field)
from coyomap.fix import plan_drift_corrections
from coyomap.grounding import worklist_is_behavioural
from coyomap.impact_git import Extents
from coyomap.model import load_model

TOLERANCE = 2


@dataclass
class Relinked:
    log: ChangeLog
    moved: list[str] = field(default_factory=list)       # one line per correction, where it went
    skipped: list[str] = field(default_factory=list)     # corrections no log address can carry
    renames: dict[str, str] = field(default_factory=dict)  # statement text before → after


def _address(applied: dict[str, Any], claim: str) -> tuple[str, str, dict[str, Any], int] | str:
    """(box id, key, the row, the site's index) of the link a claim's anchor lives in, in the map
    with the log written in; or why it has none a log can name. The id and key are in the APPLIED
    map's frame: `_place` maps them back to the frame the log is written in."""
    m = load_model(json.dumps(applied))
    match = resolve_claim(m, claim)
    t = match.target
    if t is None:
        return f"{match.count} rows make this statement" if match.count else "no row makes this statement"
    if t.kind == "edge":
        row = (applied.get("edges") or [])[t.idx]
        eid = next((i for i, r in edge_ids(applied.get("edges") or []) if r is row), None)
        return (eid, "where", row, -1) if eid else "the arrow has no id"
    if t.kind == "rule_site":
        row = applied["rules"][t.idx]
        return (str(row["id"]), f"sites[{t.sub}].where", row, t.sub)
    if t.kind == "cadence":
        row = applied["entry_points"][t.idx]
        epid = str(row.get("id") or "")
        return (epid, "cadence_source", row, -1) if epid else "the way in has no id"
    if t.kind == "lifecycle":
        row = (applied["entities"] if t.sub == 0 else applied["components"])[t.idx]
        return (str(row["id"]), "states.source", row, -1)
    return f"a {t.kind} row has no address in a change log"


def _place(log: ChangeLog, doc: dict[str, Any], box: str, key: str, stored: str,
           corrected: str, why: str) -> str:
    """Write the correction into the log where the link's value comes from, and say where; raise
    ValueError when the log's own frame cannot carry it safely. The address came from the map with
    the log applied, and an entry that removes or inserts items of the same list, or one twin of an
    arrow, numbers that list differently from the map the log is written against, so a correction
    is written only where both frames agree:
      a row the log adds         its own list, as it lands in the map
      an entry edits the link     that edit's new value
      an entry replaces the list  that edit's new list, which is the list as it lands
      nothing in the log touches the row's list, or the arrow's twins   a `relinked` row"""
    base = box.split("#", 1)[0]
    head = key.split(".")[0].split("[")[0]
    for e in log.entries:
        for a in e.added:
            rid = edge_id(a.row) if a.kind == "edges" else a.row.get("id")
            if rid == base:
                if box != base:
                    raise ValueError("the log adds an arrow with twins; correct its line in the entry by hand")
                if get_field(a.row, key) != stored:
                    raise ValueError(f"the row entry {e.id} adds holds {get_field(a.row, key)!r} there")
                set_field(a.row, key, corrected)
                return f"inside the row entry {e.id} adds"
    touching = [(e, ed) for e in log.entries for ed in e.edits
                if ed.id == box and ed.key.split(".")[0].split("[")[0] == head]
    if box.startswith("edge:"):
        if box != base or any(r.startswith(base + "#") or r == base for e in log.entries for r in e.removed):
            raise ValueError("the arrow has twins or the log removes one; correct its line by hand")
    if not touching:
        if box not in index_map(doc) or get_field(index_map(doc)[box][1], key) != stored:
            raise ValueError(f"{box}.{key} does not hold {stored!r} in the map the log is written for")
        log.relinked.append(Relink(box, key, stored, corrected, why))
        return "as a relinked row"
    if len(touching) == 1:
        e, ed = touching[0]
        if ed.key == key and ed.now == stored:
            ed.now = corrected
            return f"in entry {e.id}'s edit of {ed.key}"
        if ed.key == head and "[" not in ed.key:
            # The whole list (`sites`) or field (`states`) replaced: its new value is what lands.
            holder = {"x": ed.now}
            rest = "x" + key[len(ed.key):]
            if get_field(holder, rest) == stored:
                set_field(holder, rest, corrected)
                ed.now = holder["x"]
                return f"in entry {e.id}'s edit of {ed.key}"
    raise ValueError(f"an entry edits {box}'s {head} item by item, so the map and the log number it "
                     f"differently; correct this line in that entry by hand")


def relink(log: ChangeLog, doc: dict[str, Any], verify: Path, extents: Extents | None) -> Relinked:
    """The corrections this update's wave calls for, written into a copy of the log. `doc` is the map
    the log is written against; nothing on disk is touched. A correction the log cannot carry
    safely is listed in `skipped`, and the others still go."""
    # A deep copy through the file format: the log this run writes, never the caller's.
    out = Relinked(load_log(dump_log(log)))
    update = f"{log.from_commit}-{log.to_commit}"
    rows: list[dict[str, Any]] = []
    for f in wave_files(verify, update):
        rows.extend(read_rows(f)[1])
    before = _applied(out.log, doc)
    plan = plan_drift_corrections(load_model(json.dumps(before)), rows, TOLERANCE, extents)
    stored = {r["claim"]: r["stored"] for r in plan.records}
    for claim, corrected in plan.corrections:
        where = _address(before, claim)
        if isinstance(where, str):
            out.skipped.append(f"{claim[:100]}: {where}; re-point it by hand")
            continue
        box, key, row, site = where
        old = stored.get(claim) or ""
        if site >= 0 and any(i != site and isinstance(x, dict) and x.get("where") == corrected
                             and x.get("why") == row["sites"][site].get("why")
                             for i, x in enumerate(row.get("sites") or [])):
            out.skipped.append(f"{claim[:100]}: another site of {box} already says this line; the two "
                               f"statements would become one, so decide by hand")
            continue
        try:
            placed = _place(out.log, doc, box, key, old, corrected, f"read there by {update}'s skeptics")
        except ValueError as exc:
            out.skipped.append(f"{box}.{key} {old} → {corrected}: {exc}")
            continue
        out.moved.append(f"{box}.{key}: {old} → {corrected} ({placed})")
    for theme, claim in plan.not_applicable + plan.unparseable:
        out.skipped.append(f"{theme}: {claim[:100]}: a kind no writer moves; re-point it by hand")
    out.skipped += [f"{r['claim'][:100]}: REFUSED, {r['refusal']}" for r in plan.refused_moves]
    out.skipped += plan.cross_file
    if out.moved:
        out.renames = _renames(before, _applied(out.log, doc), verify, log)
    return out


def fresh_extents(extents: Extents, changed: set[str]) -> Extents:
    """The pre-index's symbol table without the files the update changed. The pre-index beside the
    map is rebuilt at the close step, so during the wave it numbers those files as the from-commit
    did, while the links and the skeptics' lines are the to-commit's: a definition there is at the
    wrong lines. Without them `_move_refusal` falls back to its distance bound alone."""
    return {path: rows for path, rows in extents.items() if path not in changed}


def _renames(before: dict[str, Any], after: dict[str, Any], verify: Path, log: ChangeLog) -> dict[str, str]:
    """Statement text before the corrections → after, paired by position as `shift_renames` pairs
    them: a link move changes no structure. Checked before it is trusted; on a mismatch nothing is
    renamed, and the next `challenge` re-batches the moved statements instead."""
    pin = pin_for(verify, log)
    behavioural = worklist_is_behavioural(pin) if pin.is_file() else False
    a = l2_worklist_model(load_model(json.dumps(before)), behavioural=behavioural)
    b = l2_worklist_model(load_model(json.dumps(after)), behavioural=behavioural)
    if [(x.theme, x.elements) for x in a] != [(y.theme, y.elements) for y in b]:
        return {}
    return {x.claim: y.claim for x, y in zip(a, b) if x.claim != y.claim}


def rekey_wave(verify: Path, log: ChangeLog, renames: dict[str, str]) -> int:
    """Rename this update's verdicts and claims batches to the moved statements' new text, the old
    text kept in `claim_was`. The verdict was cast on the line it now names: the skeptic cited it."""
    update = f"{log.from_commit}-{log.to_commit}"
    n = 0
    for f in wave_files(verify, update):
        payload, rows = read_rows(f)
        moved = rekey_rows(rows, renames, f"{update} relink")
        if moved:
            f.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            n += moved
    for f in sorted(verify.glob(f"claims-{update}-*.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        claims = payload.get("claims") if isinstance(payload, dict) else None
        changed = False
        for c in claims or []:
            if isinstance(c, dict) and c.get("claim") in renames:
                c.setdefault("claim_was", c["claim"])
                c["claim"] = renames[c["claim"]]
                changed = True
        if changed:
            f.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return n
