#!/usr/bin/env python3
"""`coyomap reanchor` — move every code link whose line only shifted, from git's own line mapping.

WHY. After a week of commits most of a map's code links point a few lines off: a function grew
above them, a file was renamed. The change-impact report of 2026-09-15 on mcpolis carried 242 such
moves, written out by hand as an appendix, "computed mechanically by matching unchanged lines" —
an agent doing what git already knows. This does that part, and only that part:

  * a link whose line is OUTSIDE every changed hunk between the map's pin and `--to` moves by the
    net lines added and removed above it, and follows the file's rename;
  * a link whose line is INSIDE a changed hunk is left alone and reported: the code there changed,
    so what the link means is the agent's question, not git's;
  * a link into a deleted file is left alone and reported the same way.

It never judges meaning, so it runs before the agent reads anything, and the agent's log then
carries no line moves at all (`changelog.py` ignores link-only changes on purpose). Reads git
through `impact_git`; walks the map's links through `impact_lib.link_index`, the one list of
where a code link can live (the impact report's anchors and the links that seed no hit, such as an
entry point's `cadence_source`). Stdlib-only.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from coyomap.anchors import parse_anchor
from coyomap.assemble import dump_preserving
from coyomap.impact_git import WORKTREE, ImpactError, rename_map, resolve_ref, tree_paths, u0_diff
from coyomap.impact_lib import AnchorRef, Hunk, link_index
from coyomap.model import ModelError, ProjectModel, group_forests, load_model_path

USAGE = """usage: coyomap reanchor --map <project-map.json> [--repo <root>] [--to <ref>] [--write] [--json]

Move every code link whose line only shifted between the map's pin and <ref> (default HEAD), from
git's line mapping; leave alone, and list, every link into a line the code changed or a file that
is gone — those are the agent's to read. Reports without --write; --write rewrites the map.

  --repo <root>   the repo (default: the folder above the map's .coyomap/)
  --to <ref>      the commit to move to (default HEAD)
  --write         write the moved links into the map
  --json          the report as data — parse this, never the text
"""


@dataclass
class Move:
    eid: str
    field: str
    old: str
    new: str


@dataclass
class Unmapped:
    eid: str
    field: str
    anchor: str
    why: str          # "line changed" | "file gone" | "no line"


@dataclass
class ReanchorReport:
    pin: str
    to: str
    files: int = 0                       # anchored files git says changed
    moved: list[Move] = field(default_factory=list)
    unmapped: list[Unmapped] = field(default_factory=list)


# ── the mapping ───────────────────────────────────────────────────────────────────────────────────

def line_mapper(hunks: list[Hunk]) -> Callable[[int], int | None]:
    """P-line → T-line for one file, from its `-U0` hunks. None for a line a hunk replaced or
    deleted: git has no answer for where that line went."""
    spans = sorted((h.p_lo, h.p_len, len(h.plus)) for h in hunks)

    def to_t(line: int) -> int | None:
        offset = 0
        for lo, p_len, t_len in spans:
            if p_len and lo <= line <= lo + p_len - 1:
                return None
            if (p_len and lo + p_len - 1 < line) or (not p_len and lo < line):
                offset += t_len - p_len
        return line + offset

    return to_t


def _anchor_text(path: str, lo: int, hi: int | None) -> str:
    return f"{path}:{lo}" + (f"-{hi}" if hi is not None and hi != lo else "")


def _same(raw: str | None, ref: AnchorRef) -> bool:
    """Does this stored anchor string name the ref's place? Compared parsed, not as text, so
    `a.py:3` and `a.py#L3` are one anchor."""
    if not raw:
        return False
    loc = parse_anchor(raw.strip())
    return loc is not None and loc.path == ref.path and loc.lo == ref.lo and loc.hi == ref.hi


#: One place a link is stored: an object and the attribute holding it, or a list and the index.
Slot = tuple[object, str | int]


def _slots(m: ProjectModel, ref: AnchorRef) -> Iterator[Slot]:
    """Every place in the model holding `ref`'s link — the mirror of `impact_lib.link_index`, case
    by case, matched by the stored string's PLACE, so `a.py:3` and `a.py#L3` are one link."""
    k, f, eid = ref.kind, ref.field, ref.eid

    def at(holder: object, attr: str) -> Iterator[Slot]:
        value = getattr(holder, attr, None)
        if isinstance(value, str) and _same(value, ref):
            yield (holder, attr)

    def among(items: list[str]) -> Iterator[Slot]:
        for i, x in enumerate(items):
            if _same(x, ref):
                yield (items, i)

    if f == "states.source" and k in ("component", "entity"):
        for el in (m.components if k == "component" else m.entities):
            if el.id == eid and el.states is not None:
                yield from at(el.states, "source")
        return
    if k == "component":
        for c in m.components:
            if c.id == eid:
                if f == "source":
                    yield from at(c, "source")
                elif f == "files":
                    yield from among(c.files)
                elif f == "evidence":
                    for ev in c.evidence:
                        yield from at(ev, "file")
    elif k in ("dep", "interface"):
        for row in (m.deps if k == "dep" else m.interfaces):
            if row.id == eid:
                if f in ("where_configured", "source"):
                    yield from at(row, f)
                else:
                    for ev in row.evidence:
                        yield from at(ev, "file")
    elif k == "entity":
        for e in m.entities:
            if e.id == eid:
                yield from at(e, "source")
    elif k == "non_entity_type":
        for n in m.non_entity_types:
            if eid == f"net:{n.name}":
                yield from at(n, "source")
    elif k == "glossary":
        for g in m.glossary:
            if eid == f"glossary:{g.term}":
                yield from at(g, "source")
    elif k == "entry_point" and f == "cadence_source":
        for ep in m.entry_points:
            if (ep.id or f"ep:{ep.source}") == eid and ep.component == ref.owner:
                yield from at(ep, "cadence_source")
    elif k == "entry_point":
        for ep in m.entry_points:
            if ep.component == ref.owner:
                yield from at(ep, "source")
    elif k == "edge":
        for ed in m.edges:
            if f"edge:{ed.src}>{ed.verb}>{ed.dst}" == eid:
                yield from at(ed, "where")
    elif k == "flow_step":
        for owner, steps in ([(fl.uc, fl.steps) for fl in m.flows] + [(sf.id, sf.steps) for sf in m.subflows]):
            for st in steps:
                if f"step:{owner}:{st.n}" == eid:
                    yield from at(st, "where")
    elif k == "security":
        for sec in m.security:
            if eid == f"security:{sec.surface}":
                yield from at(sec, "source")
    elif k == "role":
        for r in m.roles:
            if r.id == eid:
                for rel in (r.relations or []):
                    yield from at(rel, "source")
    elif k == "rule_site":
        for br in m.rules:
            for i, site in enumerate(br.sites):
                if f"rule:{br.id}:{i}" == eid:
                    yield from at(site, "where")
    elif k == "run_command":
        for rc in m.run_commands:
            if eid == f"run:{rc.action}":
                yield from at(rc, "source")
    elif k == "group":
        for grp in group_forests(m):
            if grp.id == eid and f in ("source", "tech_source"):
                yield from at(grp, f)
    elif k == "messaging":
        for mr in m.messaging:
            if eid == f"messaging:{mr.name}":
                yield from at(mr, "source")
    elif k == "deployment":
        for d in m.deployment:
            if eid == f"deployment:{d.unit}":
                for v in d.variants:
                    if f == f"variants[env={v.env}].source":
                        yield from at(v, "source")
    elif k == "tests":
        for i, tr in enumerate(m.tests):
            if eid == f"tests[{i}]":
                for j, ev in enumerate(tr.tests):
                    if f == f"tests[{j}].file":
                        yield from at(ev, "file")


def locate_anchor(m: ProjectModel, ref: AnchorRef, taken: set[tuple[int, str | int]]) -> Slot | None:
    """The one place `ref`'s link is stored that no earlier ref of this run has claimed. Two rows
    that hold the same link (twin arrows at one line, two ways in at one source) each get their own."""
    for slot in _slots(m, ref):
        key = (id(slot[0]), slot[1])
        if key not in taken:
            taken.add(key)
            return slot
    return None


def _write(slot: Slot, new: str) -> None:
    holder, at = slot
    if isinstance(holder, list):
        holder[int(at)] = new
    else:
        setattr(holder, str(at), new)


def set_anchor(m: ProjectModel, ref: AnchorRef, new: str) -> bool:
    """Write `new` where `ref` was read from. True when written. A run moving many links locates
    them all before writing any (`reanchor`): writing one at a time let a moved link match the next
    ref's old place, so two arrows sharing their ends two lines apart swapped links, and the gate
    read the swap as no change."""
    slot = locate_anchor(m, ref, set())
    if slot is not None:
        _write(slot, new)
    return slot is not None


# ── the run ───────────────────────────────────────────────────────────────────────────────────────

def reanchor(m: ProjectModel, repo: Path, to: str = "HEAD") -> ReanchorReport:
    """Move the map's code links from its pin to `to`, in place. Raises ImpactError when the map
    carries no pin or a ref does not resolve."""
    pin = (m.commit or "").removesuffix("-dirty")
    if not pin:
        raise ImpactError("the map carries no commit pin")
    if to == WORKTREE:
        raise ImpactError("reanchor moves links to a COMMIT; the working tree has no line map "
                          "(commit first, then reanchor to that commit)")
    pin_sha = resolve_ref(repo, pin)
    to_sha = resolve_ref(repo, to)
    report = ReanchorReport(pin_sha, to_sha)
    if pin_sha == to_sha:
        return report
    renamed_to = {old: new for new, old in rename_map(repo, pin_sha, to_sha).items()}
    present = tree_paths(repo, to_sha)
    by_path: dict[str, list[AnchorRef]] = {}
    for ref in link_index(m):
        if not ref.is_dir:
            by_path.setdefault(ref.path, []).append(ref)
    # LOCATE EVERY LINK BEFORE WRITING ANY: a link written early could match a later ref's old place.
    taken: set[tuple[int, str | int]] = set()
    writes: list[tuple[Slot, Move]] = []
    for path in sorted(by_path):
        new_path = renamed_to.get(path, path)
        refs = by_path[path]
        if new_path not in present:
            for ref in refs:
                report.unmapped.append(Unmapped(ref.eid, ref.field, _anchor_text(path, ref.lo or 0, ref.hi), "file gone"))
            continue
        hunks = u0_diff(repo, pin_sha, path, to_sha, new_path).hunks
        if not hunks and new_path == path:
            continue
        report.files += 1
        to_t = line_mapper(hunks)
        for ref in refs:
            old = _anchor_text(path, ref.lo or 0, ref.hi)
            if ref.lo is None:
                if new_path != path and (slot := locate_anchor(m, ref, taken)) is not None:
                    writes.append((slot, Move(ref.eid, ref.field, path, new_path)))
                continue
            lo = to_t(ref.lo)
            hi = to_t(ref.hi) if ref.hi is not None else None
            if lo is None or (ref.hi is not None and hi is None):
                report.unmapped.append(Unmapped(ref.eid, ref.field, old, "line changed"))
                continue
            new = _anchor_text(new_path, lo, hi)
            if new == old:
                continue
            if (slot := locate_anchor(m, ref, taken)) is not None:
                writes.append((slot, Move(ref.eid, ref.field, old, new)))
    for slot, move in writes:
        _write(slot, move.new)
        report.moved.append(move)
    return report


def format_report(r: ReanchorReport, written: bool) -> str:
    lines = [f"reanchor — {r.pin[:10]} → {r.to[:10]}: {r.files} anchored file(s) changed, "
             f"{len(r.moved)} link(s) moved, {len(r.unmapped)} left for the agent"
             + (" — written" if written else " — not written (add --write)")]
    for u in r.unmapped:
        lines.append(f"  ? {u.eid} {u.field} {u.anchor}  ({u.why})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if args else 2
    map_path: Path | None = None
    repo: Path | None = None
    to = "HEAD"
    write = as_json = False
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--map", "--repo", "--to"):
            i += 1
            if i >= len(args) or args[i].startswith("-"):
                print(f"ERROR: {a} needs a value", file=sys.stderr)
                return 2
            if a == "--map":
                map_path = Path(args[i])
            elif a == "--repo":
                repo = Path(args[i])
            else:
                to = args[i]
        elif a == "--write":
            write = True
        elif a == "--json":
            as_json = True
        elif a.startswith("-"):
            print(f"ERROR: unknown option '{a}'\n", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2
        else:
            print(f"ERROR: unexpected argument '{a}'\n", file=sys.stderr)
            print(USAGE, file=sys.stderr)
            return 2
        i += 1
    if map_path is None:
        print("ERROR: --map <project-map.json> is required\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    if repo is None:
        repo = map_path.resolve().parent.parent
    try:
        m = load_model_path(map_path)
        report = reanchor(m, repo, to)
    except (ModelError, ImpactError, OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if write and report.moved:
        map_path.write_text(dump_preserving(m, None), encoding="utf-8")
    if as_json:
        print(json.dumps({"kind": "coyomap-reanchor", "written": bool(write and report.moved),
                          **asdict(report)}, indent=2, ensure_ascii=False))
    else:
        print(format_report(report, bool(write and report.moved)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
