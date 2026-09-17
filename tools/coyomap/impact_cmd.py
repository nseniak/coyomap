#!/usr/bin/env python3
"""`coyomap impact` — the boxes a code change touches, from the map's code links.

The engine behind it (`impact_git` + `impact_ripple`) has served the viewer's hidden Impact explorer
since the M2/M3 work and was reachable nowhere else, so the agent analyzing a change read the whole
diff with no bound on what the map says it reaches. This is the same projection as a command:
per box, the change git saw at its code link (modified / added / deleted, or a drift — the text
moved, nothing changed), the resolution it was resolved at (line / symbol / file), and the boxes
it ripples to through the map's own relations.

Its JSON is what `coyomap changes check --touched` reads: a log that names or waives every box
touched at line or symbol resolution has covered what the code says it changed. Stdlib-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from coyomap.dump import resolve_id
from coyomap.impact_git import WORKTREE, ImpactError, compute_impact, load_map_extents
from coyomap.impact_ripple import RippleOptions, build_impact_result
from coyomap.model import ModelError, ProjectModel, load_model_path

USAGE = """usage: coyomap impact --map <project-map.json> [--repo <root>] [--base <ref>] [--target <ref>|WORKTREE]
                      [--reads] [--entity-graph] [--callgraph] [--json]

Which boxes a code change touches, read off the map's code links: the direct hits (with the
resolution each was found at) and what they ripple to. Defaults: base = the map's pin, target = HEAD.

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
                return f"way in: {ep.trigger}"
        return eid
    row = resolve_id(m, eid)
    if row:
        for f in ("name", "title", "term", "trigger"):
            v = row.get(f)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return eid


def format_result(m: ProjectModel, result: dict[str, Any]) -> str:
    spec = result.get("spec") or {}
    counts = result.get("counts") or {}
    short = (lambda r: "working tree" if r == WORKTREE else str(r or "")[:10])
    lines = [f"impact — {short(spec.get('base'))} → {short(spec.get('target'))}: "
             f"{len(result.get('files') or [])} file(s) changed, {counts.get('direct', 0)} box(es) hit, "
             f"{counts.get('ripple', 0)} reached through the map"]
    for w in result.get("warnings") or []:
        lines.append(f"  ! {w}")
    impacts = result.get("impacts") or {}
    for t, ids in (result.get("byType") or {}).items():
        rows = []
        for eid in ids:
            imp = impacts.get(eid) or {}
            if imp.get("cause") == "direct":
                what = f"{imp.get('change')} at {imp.get('resolution')} resolution"
            else:
                what = "reached" + (f" via {', '.join(h.get('from', '?') for h in imp.get('via') or [])}" if imp.get("via") else "")
            rows.append(f"    {eid:<18} {_name(m, eid)[:50]:<50} {what}")
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
        print(format_result(m, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
