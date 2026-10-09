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
                               lint, load_log, set_field)
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


def _address(applied: dict[str, Any], claim: str) -> tuple[str, str] | str:
    """(box id, key) of the link a claim's anchor lives in, in the map with the log written in; or
    why it has none a log can name."""
    m = load_model(json.dumps(applied))
    match = resolve_claim(m, claim)
    t = match.target
    if t is None:
        return f"{match.count} rows make this statement" if match.count else "no row makes this statement"
    if t.kind == "edge":
        row = (applied.get("edges") or [])[t.idx]
        eid = next((i for i, r in edge_ids(applied.get("edges") or []) if r is row), None)
        return (eid, "where") if eid else "the arrow has no id"
    if t.kind == "rule_site":
        return (str(applied["rules"][t.idx]["id"]), f"sites[{t.sub}].where")
    if t.kind == "cadence":
        epid = str(applied["entry_points"][t.idx].get("id") or "")
        return (epid, "cadence_source") if epid else "the way in has no id"
    if t.kind == "lifecycle":
        rows = applied["entities"] if t.sub == 0 else applied["components"]
        return (str(rows[t.idx]["id"]), "states.source")
    return f"a {t.kind} row has no address in a change log"


def _place(log: ChangeLog, box: str, key: str, stored: str, corrected: str) -> str | None:
    """Write the correction into the log where the link's value comes from; return where, or None
    when the log does not carry it (then it is a `relinked` row)."""
    for e in log.entries:
        for a in e.added:
            rid = edge_id(a.row) if a.kind == "edges" else a.row.get("id")
            if rid == box.split("#", 1)[0] or rid == box:
                if get_field(a.row, key) != stored:
                    raise ValueError(f"{box}.{key}: the row entry {e.id} adds holds "
                                     f"{get_field(a.row, key)!r}, not {stored!r}")
                set_field(a.row, key, corrected)
                return f"inside the row entry {e.id} adds"
        for ed in e.edits:
            if ed.id != box or not (key == ed.key or key.startswith(ed.key + ".") or key.startswith(ed.key + "[")):
                continue
            if key == ed.key:
                if ed.now != stored:
                    raise ValueError(f"{box}.{key}: entry {e.id}'s edit writes {ed.now!r}, not {stored!r}")
                ed.now = corrected
            else:
                holder = {"x": ed.now}
                rest = "x" + key[len(ed.key):]
                if get_field(holder, rest) != stored:
                    raise ValueError(f"{box}.{key}: entry {e.id}'s edit of {ed.key} holds "
                                     f"{get_field(holder, rest)!r} there, not {stored!r}")
                set_field(holder, rest, corrected)
                ed.now = holder["x"]
            return f"in entry {e.id}'s edit of {ed.key}"
    return None


def relink(log: ChangeLog, doc: dict[str, Any], verify: Path, extents: Extents | None) -> Relinked:
    """The corrections this update's wave calls for, written into a copy of the log. `doc` is the map
    the log is written against; nothing on disk is touched."""
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
        box, key = where
        old = stored.get(claim) or ""
        placed = _place(out.log, box, key, old, corrected)
        if placed is None:
            out.log.relinked.append(Relink(box, key, old, corrected, f"read there by {update}'s skeptics"))
            placed = "as a relinked row"
        out.moved.append(f"{box}.{key}: {old} → {corrected} ({placed})")
    for theme, claim in plan.not_applicable + plan.unparseable:
        out.skipped.append(f"{theme}: {claim[:100]}: a kind no writer moves; re-point it by hand")
    out.skipped += [f"{r['claim'][:100]}: REFUSED, {r['refusal']}" for r in plan.refused_moves]
    out.skipped += plan.cross_file
    if out.moved:
        out.renames = _renames(before, _applied(out.log, doc), verify, log)
    return out


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


def check_relinked(r: Relinked, doc: dict[str, Any]) -> list[str]:
    """The corrected log must still lint clean against the map: every relinked `was` is the map's."""
    return lint(r.log, doc).errors
