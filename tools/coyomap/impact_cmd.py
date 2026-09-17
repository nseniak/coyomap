#!/usr/bin/env python3
"""`coyomap impact` — the boxes a code change touches, from the map's code links.

The engine behind it (`impact_git` + `impact_ripple`) has served the viewer's hidden Impact explorer
since the M2/M3 work and was reachable nowhere else, so the agent analyzing a change read the whole
diff with no bound on what the map says it reaches. This is the same projection as a command:
per box, the change git saw at its code link (modified / added / deleted, or a drift — the text
moved, nothing changed), the resolution it was resolved at (line / symbol / file), and the boxes
it ripples to through the map's own relations.

Its JSON is what `coyomap changes check --touched` reads: a log that names or waives every box
touched at line or symbol resolution (or whose file is gone) has covered what the code says it
changed. The text marks those hits `*`, through the gate's own predicate, so the agent reads the
list the gate will count; a hit at file resolution only says the file changed somewhere, and is
listed for reading. The map's own folder is left out of the file count (a rehearsal read "308
files changed" of which 290 were the map), and a way in shows its EP id, the one `dump --id`
resolves, instead of the engine's `ep:<file>:<line>`. Stdlib-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from coyomap.changelog import gated_box
from coyomap.dump import resolve_id
from coyomap.impact_git import WORKTREE, ImpactError, compute_impact, load_map_extents
from coyomap.impact_ripple import RippleOptions, build_impact_result
from coyomap.model import OLD_MAP_FOLDER, ModelError, ProjectModel, load_model_path

USAGE = """usage: coyomap impact --map <project-map.json> [--repo <root>] [--base <ref>] [--target <ref>|WORKTREE]
                      [--reads] [--entity-graph] [--callgraph] [--json]

Which boxes a code change touches, read off the map's code links: the direct hits (with the
resolution each was found at) and what they ripple to. Defaults: base = the map's pin, target = HEAD.
A hit marked `*` is one `coyomap changes check --touched` counts: a line or symbol hit, or a link
into a deleted file. A file-resolution hit is listed for reading and needs no waiver.

  --repo <root>     the repo (default: the folder above the map's .coyomap/)
  --base <ref>      the older commit (default: the map's pin)
  --target <ref>    the newer commit, or WORKTREE for the files on disk (default HEAD)
  --reads / --entity-graph / --callgraph   follow more of the map's relations when rippling
  --json            the full result as data — what `coyomap changes check --touched` reads
"""

_LABEL = {"subsystems": "Subsystems", "components": "Components", "deps": "Dependencies",
          "entities": "Records", "subdomains": "Data areas", "use_cases": "Use cases",
          "capabilities": "Features", "happy_path": "Happy path", "flow_steps": "Flow steps",
          "subflows": "Shared sub-flows", "edges": "Arrows", "entry_points": "Ways in",
          "blocks": "Decision areas", "rules": "Rules", "rule_sites": "Rule sites",
          "glossary": "Glossary", "security": "Security", "run_commands": "Run commands",
          "non_entity_types": "Other types", "interfaces": "Interfaces", "other": "Other"}


def _name(m: ProjectModel, eid: str) -> str:
    """A box by its name; a synthetic id by what it stands for: a step by its use case and number,
    a site by its rule, an arrow by its ends, a way in by its trigger."""
    if eid.startswith("step:"):
        _, owner, n = eid.split(":", 2)
        return f"{_name(m, owner)} · step {n}"
    if eid.startswith("rule:"):
        return _name(m, eid.split(":")[1]) + " · a site"
    if eid.startswith("edge:"):
        src, verb, dst = eid[5:].split(">", 2)
        return f"{_name(m, src)} {verb} {_name(m, dst)}"
    if eid.startswith("ep:"):
        source = eid[3:]
        for ep in m.entry_points:
            if ep.source == source:
                return ep.trigger
        return eid
    row = resolve_id(m, eid)
    if row:
        for f in ("name", "title", "term", "trigger"):
            v = row.get(f)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return eid


def format_result(m: ProjectModel, result: dict[str, Any], map_dir: str | None = None) -> str:
    """The text for the agent. `map_dir` is the map's own folder, repo-relative: its files are
    changed by every update (the map, its view, the pre-index) and say nothing about the code, so
    they are counted apart."""
    spec = result.get("spec") or {}
    counts = result.get("counts") or {}
    impacts = result.get("impacts") or {}
    short = (lambda r: "working tree" if r == WORKTREE else str(r or "")[:10])
    files = result.get("files") or []
    # The map's own folder, under its name today and its former one (a rename of the folder is a
    # change to every file in it, and none of them is code).
    own_dirs = [d for d in (map_dir, OLD_MAP_FOLDER) if d]
    own = [f for f in files if any(str(f.get(side) or "").startswith(d + "/")
                                   for d in own_dirs for side in ("path", "p_path"))]
    skipped = [d for d in own_dirs if any(str(f.get(side) or "").startswith(d + "/")
                                          for f in own for side in ("path", "p_path"))]
    gated = {str(eid): box for eid, imp in impacts.items() if (box := gated_box(str(eid), imp))}
    lines = [f"impact — {short(spec.get('base'))} → {short(spec.get('target'))}: "
             f"{len(files) - len(own)} file(s) changed, {counts.get('direct', 0)} box(es) hit, "
             f"{len(gated)} hit(s) on {len(set(gated.values()))} box(es) count at the gate (*), "
             f"{counts.get('ripple', 0)} reached through the map"
             + (f"; {len(own)} file(s) under {' and '.join(d + '/' for d in skipped)} not counted" if own else "")]
    for w in result.get("warnings") or []:
        lines.append(f"  ! {w}")
    ep_ids = {f"ep:{ep.source}": ep.id for ep in m.entry_points if ep.id}
    for t, ids in (result.get("byType") or {}).items():
        rows = []
        for eid in ids:
            imp = impacts.get(eid) or {}
            if imp.get("cause") == "direct":
                what = f"{imp.get('change')} at {imp.get('resolution')} resolution"
            else:
                what = "reached" + (f" via {', '.join(h.get('from', '?') for h in imp.get('via') or [])}" if imp.get("via") else "")
            mark = "* " if gated_box(str(eid), imp) else "  "
            rows.append(f"  {mark}{ep_ids.get(eid, eid):<18} {_name(m, eid)[:50]:<50} {what}")
        if rows:
            lines.append(f"  {_LABEL.get(t, t)}:")
            lines.extend(rows)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if args else 2
    map_path: Path | None = None
    repo: Path | None = None
    base: str | None = None
    target = "HEAD"
    as_json = False
    opts = RippleOptions()
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--map", "--repo", "--base", "--target"):
            i += 1
            if i >= len(args) or args[i].startswith("-"):
                print(f"ERROR: {a} needs a value", file=sys.stderr)
                return 2
            v = args[i]
            if a == "--map":
                map_path = Path(v)
            elif a == "--repo":
                repo = Path(v)
            elif a == "--base":
                base = v
            else:
                target = v
        elif a == "--json":
            as_json = True
        elif a == "--reads":
            opts.reads = True
        elif a == "--entity-graph":
            opts.entity_graph = True
        elif a == "--callgraph":
            opts.callgraph = True
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
        extents = load_map_extents(map_path)
        core = compute_impact(repo, m, extents, base or "", target)
        result = build_impact_result(m, core, opts, None, extents)
    except (ModelError, ImpactError, OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        try:
            map_dir = map_path.resolve().parent.relative_to(repo.resolve()).as_posix()
        except ValueError:
            # A copy of the map kept outside the repo (a rehearsal, a test): the repo's own
            # `.coyomap/` is still the map's folder.
            map_dir = ".coyomap"
        print(format_result(m, result, map_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
