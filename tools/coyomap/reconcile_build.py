#!/usr/bin/env python3
"""`coyomap reconcile` — expand path RULES into an explicit `reconcile.json`.

`assemble --reconcile` already applies the synthesis assignments declaratively, but AUTHORING that
file is the part that does not scale: it wants explicit id lists, and on a large map that is hundreds
of ids nobody types. A live 429-component build wrote a throwaway generator script for exactly this,
and the script had the predictable bug — it resolved zero components while reporting 429 assignments,
because nothing checked the ids it emitted against the map.

So this command does the expansion and the checking: rules match elements by SOURCE PATH (the fact a
lead actually knows — "everything under mee6/plugins/ is the Plugins subsystem"), ids are resolved
against real elements, and every rule that matches nothing is reported rather than silently emitting
an empty assignment. Output is an ordinary reconcile file, so `assemble --reconcile` stays the one
code path that writes.

Read the FRAGMENTS during a build (the synthesis pass), a MAP when re-assigning on a built one:

    coyomap reconcile --rules rules.json --fragments .coyomap/build-fragments/*.json \\
                      --out .coyomap/reconcile.json [--dry-run] [--only-unmatched]

    coyomap reconcile --rules rules.json --map .coyomap/project-map.json \\
                      --out .coyomap/reconcile.json [--dry-run] [--only-unmatched]

`--fragments` exists because `--map` alone made this command unreachable at the one moment a build
needs it. The reconcile file is an INPUT to `assemble`, and `assemble` is what produces the map — so
requiring a map first is a circular dependency, and nine consecutive builds resolved it the only way
left to them: by hand-writing the file the command exists to generate. Nothing was lost by reading
fragments instead; `assemble` mints no ids, so the `(id, source)` pairs the rules match against are
byte-identical in both.

rules.json:
    {"rules": [
       {"source_glob": "mee6/plugins/*",   "subsystem": "S12"},
       {"source_glob": "gateway/**",       "runs_in": ["gateway"]},
       {"ids": ["E7", "E8"],               "subdomain": "SD2"},
       {"source_glob": "mee6/memberships/**", "subsystem": "S30", "runs_in": ["api", "worker"]}
    ]}

Later rules win on the same (element, field), so a broad rule can be followed by a narrow override.
Stdlib-only (the cli.py firewall).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from coyomap.anchors import strip_anchor
from coyomap.assemble import expand_directories, load_fragment_paths, merge_fragments
from coyomap.model import (
    Interface,
    BusinessRule,
    Component,
    Dep,
    Entity,
    EntryPoint,
    ProjectModel,
    UseCase,
    load_model_path,
)
from coyomap.pathmatch import matches
from coyomap.reporting import shown

_DEFAULT_MAP = ".coyomap/project-map.json"
_DEFAULT_RECONCILE = ".coyomap/reconcile.json"

# field → the element type it may be set on. MIRRORS `reconcile._SET_FIELD_OWNER`, which validates
# the emitted file again at assemble time — this is the early, friendlier report. The comment used
# to claim that and be false: `capability` and `entry_points` were consumer-only, so the generator
# rejected the one assignment the method prescribes for a use case, and two real builds hand-wrote
# their reconcile file and shipped `entry_points: []` on EVERY use case (43 of 43, 40 of 40).
# `test_the_generator_accepts_every_field_the_consumer_sets` now holds the two dicts together.
_FIELD_OWNER: dict[str, type] = {
    "subsystem": Component,
    "runs_in": Component,
    "subdomain": Entity,
    "bucket": Dep,
    "block": BusinessRule,
    "capability": UseCase,
    "entry_points": UseCase,
    "owners": Entity,
    "ways_in": Interface,
    "interfaces": Dep,
    "interface_kind": Interface,
    # An `EPn`'s owning `C` id. Here for the same reason `ways_in` is, one field over: `EPn` ids are
    # MINTED BY `assemble` from content, so no fragment can name them, and the owning component is
    # only decidable once every fragment's components exist. Without this entry the only way to set
    # it was a hand-written heredoc over the assembled map — the 2026-09-01 argus build did exactly
    # that for 88 entry points, outside every check `reconcile` applies.
    "component": EntryPoint,
}


class RuleError(Exception):
    """A malformed rules file — raised before anything is written."""


def _elements(m: ProjectModel) -> list[object]:
    """Every element a rule may target. `m.use_cases` was missing, so even once `capability` and
    `entry_points` are legal fields there is nothing to assign them to.

    NOTE for authors: a `UseCase` has no `source`, so `_source_of` returns "" for one and a
    `source_glob` rule can never match it. `capability` / `entry_points` rules are addressed by
    `ids` in practice. An `EntryPoint` DOES carry a `source`, so a `component` rule can be written
    as a `source_glob` — which is the point: assigning 88 of them by id was what drove the
    2026-09-01 argus build to a hand-written heredoc."""
    return [*m.components, *m.entities, *m.deps, *m.rules, *m.use_cases, *m.interfaces,
            *m.entry_points]


def _source_of(el: object) -> str:
    """The element's repo-relative source path, anchor suffix stripped ('' when it has none).

    A business RULE has no `source` — its location is its sites, and it may have several. The FIRST
    anchored site stands in, so `source_glob` can sweep a directory's rules the way it sweeps its
    components; a rule spanning several directories is placed by whichever one its first site names,
    which is why `ids` is the reliable form for `block` (and what `coyomap reconcile` reports)."""
    raw = getattr(el, "source", "") or getattr(el, "where_configured", "") or ""
    if not raw and isinstance(el, BusinessRule):
        raw = next(((s.where or "") for s in el.sites if (s.where or "").strip()), "")
    return strip_anchor(raw).rstrip("/") if raw else ""


# The glob matcher moved to `coyomap.pathmatch` when `.coyomap/.ignore` grew the second caller —
# one implementation, so the two path-rule surfaces can never drift apart. Re-exported under the
# old private name: it is this module's matching contract, and tests reach for it here.
_matches = matches


def load_rules(path: Path) -> list[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuleError(f"cannot read rules file {path}: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("rules"), list):
        raise RuleError("rules file must be an object with a 'rules' array")
    for i, r in enumerate(doc["rules"]):
        if not isinstance(r, dict):
            raise RuleError(f"rules[{i}]: expected an object")
        if "source_glob" not in r and "ids" not in r:
            raise RuleError(f"rules[{i}]: needs 'source_glob' or 'ids'")
        assigned = [k for k in r if k in _FIELD_OWNER]
        if not assigned:
            raise RuleError(f"rules[{i}]: assigns nothing "
                            f"(expected one of {', '.join(sorted(_FIELD_OWNER))})")
    return doc["rules"]


def unresolved_ids(m: ProjectModel, rules: list[dict]) -> list[str]:
    """Every id a rule NAMES that the map does not define.

    One function, called by `expand`'s per-rule report line and by the summary, so the two cannot
    disagree. The summary previously re-read `expand`'s own sentence with a regex — parsing your own
    output — and a rule naming 190 ids of which 111 are absent is not "matched NOTHING", so it read
    "479 clean" on a run that assigned 111 of its ids to no element at all."""
    by_id = {getattr(el, "id") for el in _elements(m)}
    return [eid for r in rules for eid in r.get("ids", []) if eid not in by_id]


def expand(m: ProjectModel, rules: list[dict]) -> tuple[dict, list[str]]:
    """(reconcile document, report lines). Later rules override earlier ones per (element, field)."""
    by_id = {getattr(el, "id"): el for el in _elements(m)}
    assign: dict[str, dict[str, object]] = {}          # element id → {field: value}
    report: list[str] = []
    for i, r in enumerate(rules):
        fields = {k: v for k, v in r.items() if k in _FIELD_OWNER}
        by_id_rule = "ids" in r
        if by_id_rule:
            targets, unknown = [], []
            for eid in r["ids"]:
                (targets if eid in by_id else unknown).append(eid)
            if unknown:
                report.append(f"rules[{i}]: {len(unknown)} id(s) are not in the map: "
                              f"{shown(unknown, 8)}")
        else:
            targets = [getattr(el, "id") for el in _elements(m)
                       if _matches(r["source_glob"], _source_of(el))]
        # A field may only land on its owning element type. A path glob naturally sweeps the
        # entities and deps living in the same directory, so skipping those is the rule working as
        # intended — silent. Naming an id explicitly is different: the author meant THAT element,
        # so a type mismatch there is a mistake worth reporting.
        kept: list[str] = []
        for eid in targets:
            el = by_id[eid]
            bad = [f for f in fields if not isinstance(el, _FIELD_OWNER[f])]
            if bad:
                if by_id_rule:
                    report.append(f"rules[{i}]: {eid} is a {type(el).__name__}, so "
                                  f"{', '.join(bad)} does not apply to it — skipped")
                continue
            assign.setdefault(eid, {}).update(fields)
            kept.append(eid)
        where = r.get("source_glob") or f"{len(r.get('ids', []))} id(s)"
        if not kept:
            report.append(f"rules[{i}]: '{where}' matched NOTHING — wrong path prefix, or the "
                          "elements carry no source anchor")
        else:
            report.append(f"rules[{i}]: '{where}' → {len(kept)} element(s) "
                          f"[{', '.join(sorted(fields))}]")

    # THE TARGET must exist too, not just the source. A rule may name a perfectly good glob and
    # assign it to a group nobody declared — `subdomain: SD9` while `subdomains` holds SD1..SD8 —
    # and the dry run reported three clean passes over exactly that before `assemble` died with
    # "E62 parent SD9 is undefined … ASSEMBLY FAILED", four turns later. Checking the source and
    # not the destination is half a check.
    declared: dict[str, set[str]] = {
        "subsystem": {g.id for g in m.subsystems},
        "subdomain": {g.id for g in m.subdomains},
        "block": {g.id for g in m.blocks},
        "capability": {g.id for g in m.capabilities},
        "runs_in": {u.unit for u in (m.deployment or [])},
        "entry_points": {ep.id for ep in m.entry_points if ep.id},
        "ways_in": {ep.id for ep in m.entry_points if ep.id},
        "interfaces": {i.id for i in m.interfaces},
    }
    label = {"runs_in": "deployment unit", "ways_in": "entry point", "interfaces": "interface"}
    for i, r in enumerate(rules):
        for f, space in declared.items():
            if f not in r:
                continue
            vals = r[f] if isinstance(r[f], list) else [r[f]]
            missing = [v for v in vals if v not in space]
            if not missing:
                continue
            # An EMPTY declared space is the case this check was written for, not a reason to skip.
            # Groups are declared in the synthesis fragment, so a reconcile over harvest fragments
            # alone sees every space empty — which is exactly when `assemble` later refuses. The
            # earlier `not space: continue` disabled the check precisely on the `--fragments` path.
            # It cannot distinguish "declared nowhere" from "declared in a fragment not passed
            # here", so it says both.
            where = ("nothing in this input declares any " + label.get(f, f) + " at all"
                     if not space else "nothing declares it")
            report.append(f"rules[{i}]: assigns {f}={', '.join(map(str, missing))} — {where}. "
                          f"`assemble` REFUSES an undeclared target, so either it is declared in a "
                          f"fragment not passed here, or this will fail assembly.")

    # WITNESS every entry-point id with the anchor it has right now. `EPn` is minted by `assemble`
    # from harvested content: order-independent, but it RENUMBERS when a surface is added, so a file
    # authored against an older harvest re-points a use case at a different front door while every
    # id still resolves. `validate_reconcile` compares the witness and refuses. Emitted here so the
    # check is one the normal path satisfies by default rather than one only a careful hand can meet.
    ep_source = {ep.id: (ep.source or "").strip() for ep in m.entry_points if ep.id}
    for fields in assign.values():
        eps = fields.get("entry_points")
        if not isinstance(eps, list):
            continue
        fields["entry_points"] = [
            {"id": e, "source": ep_source[e]} if isinstance(e, str) and ep_source.get(e) else e
            for e in eps]

    # collapse to the compact `set` shape: one entry per distinct field-value combination
    groups: dict[str, list[str]] = {}
    for eid, fields in assign.items():
        groups.setdefault(json.dumps(fields, sort_keys=True), []).append(eid)
    sets = [{"ids": sorted(ids, key=lambda s: (s[0], int(s[1:]) if s[1:].isdigit() else 0)),
             **json.loads(key)} for key, ids in sorted(groups.items())]
    return {"set": sets}, report


def coverage_report(m: ProjectModel, doc: dict) -> list[str]:
    """What the rules did NOT reach — the half a hand-rolled script never prints."""
    touched = {eid for s in doc.get("set", []) for eid in s.get("ids", [])}
    out: list[str] = []
    for label, elements, fieldname in (("component", m.components, "subsystem"),
                                       ("entity", m.entities, "subdomain"),
                                       ("business rule", m.rules, "block")):
        missing = [el.id for el in elements
                   if el.id not in touched and not getattr(el, fieldname, None)]
        if missing:
            out.append(f"{len(missing)} {label}(s) still have no {fieldname} and match no rule: "
                       f"{shown(missing, 10)}")
    unplaced = [c.id for c in m.components if not c.runs_in and c.id not in touched]
    if unplaced and m.deployment:
        out.append(f"{len(unplaced)} component(s) have no runs_in and match no rule: "
                   f"{shown(unplaced, 10)}")
    return out


def _arg(argv: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def _args_after(argv: list[str], flag: str) -> list[str]:
    """Every value following `flag` up to the next option — so a shell glob can be passed whole
    (`--fragments .coyomap/build-fragments/*.json` arrives already expanded into N arguments)."""
    if flag not in argv:
        return []
    out: list[str] = []
    for a in argv[argv.index(flag) + 1:]:
        if a.startswith("-"):
            break
        out.append(a)
    return out


def count_fragment_files(frag_paths: list[str]) -> int:
    """How many fragment FILES the arguments name, expanding a bare directory the way the shared
    loader does — so the reported count matches what was actually read. Counting argv entries made
    `--fragments <dir>` over 31 real fragments report "reading 1 fragment(s)"."""
    return len(expand_directories([Path(p) for p in frag_paths], []))


def load_elements(map_path: str | None, frag_paths: list[str],
                  want_fragments: bool = False) -> tuple[ProjectModel, list[str]]:
    """The model the rules resolve against, from FRAGMENTS or from an assembled MAP.

    Returns `(model, notes)`. Raises `RuleError` with a message the lead can act on — including the
    one that matters most: a missing map during synthesis is not a broken build, it is the wrong
    flag, because the map does not exist yet at that point by construction.

    `want_fragments` is whether `--fragments` was GIVEN, which is not the same as whether it
    resolved. Branching on the resolved list instead is a silent-corruption bug: under `nullglob` a
    glob matching nothing leaves the flag with zero paths, the fragment intent evaporates, and the
    command reads the default map — the STALE one from the previous build, still committed next to
    the code. Ids restart at C1 every build, so its C1 resolves and means something else entirely;
    every stage exits 0 and the assignments land on the wrong components."""
    if want_fragments and not frag_paths:
        raise RuleError("--fragments was given but expanded to no paths — the glob matched nothing "
                        "(wrong directory, or the harvest fragments are not written yet). Refusing "
                        "rather than falling back to the map, which during a build is the previous "
                        "build's and whose ids mean something else.")
    if frag_paths:
        # A bare DIRECTORY argument is expanded by `load_fragment_paths` — the loader BOTH commands
        # share, so `assemble` and `reconcile` cannot drift on what an argument means. It was
        # briefly duplicated here, which is exactly the shape that lets two readers of the same
        # fragments disagree about the file set.
        loaded = load_fragment_paths([Path(p) for p in frag_paths])
        parts, notes, errors = loaded.parts, loaded.notes, loaded.errors
        if errors:
            raise RuleError("cannot read the fragments:\n  " + "\n  ".join(errors))
        if not parts:
            raise RuleError(f"--fragments matched no readable fragment ({len(frag_paths)} path(s) "
                            "given; a directory argument is expanded to its *.json children)")
        model, problems = merge_fragments(parts)
        if problems:
            raise RuleError("the fragments do not merge:\n  " + "\n  ".join(problems))
        return model, notes
    path = Path(map_path or _DEFAULT_MAP)
    if not path.exists():
        frag_dir = path.parent / "build-fragments"
        hint = (f"\n  During a build the map does not exist yet — the reconcile file is an INPUT to "
                f"`assemble`, which is what writes the map. Read the fragments instead:\n"
                f"    coyomap reconcile --rules <rules.json> --fragments {frag_dir}/*.json"
                if frag_dir.is_dir() else "")
        raise RuleError(f"{path} not found{hint}")
    return load_model_path(str(path)), []


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    rules_path = _arg(argv, "--rules")
    map_path = _arg(argv, "--map")
    frag_paths = _args_after(argv, "--fragments")
    out_path = _arg(argv, "--out", _DEFAULT_RECONCILE) or _DEFAULT_RECONCILE
    dry = "--dry-run" in argv
    only_unmatched = "--only-unmatched" in argv
    if not rules_path:
        print("ERROR: --rules is required", file=sys.stderr)
        return 2
    if map_path and frag_paths:
        print("ERROR: pass --fragments OR --map, not both — they are two sources for the same "
              "elements (fragments during a build, a map when re-assigning on a built one)",
              file=sys.stderr)
        return 2
    try:
        rules = load_rules(Path(rules_path))
        m, notes = load_elements(map_path, frag_paths, want_fragments="--fragments" in argv)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for note in notes:
        print(note, file=sys.stderr)
    # Say which source was read. Two inputs that resolve the same id space differently is exactly
    # the class of mistake that stays invisible when the tool is silent about its own input — so
    # count the FRAGMENTS, not the argv entries. Once a bare directory could be passed, `--fragments
    # <dir>` over 31 real fragments reported "reading 1 fragment(s)", which is the same silence.
    print(f"reading {count_fragment_files(frag_paths)} fragment(s)" if frag_paths
          else f"reading map {map_path or _DEFAULT_MAP}", file=sys.stderr)

    doc, report = expand(m, rules)
    # One line per rule and no summary meant "which rules matched nothing" could only be answered by
    # re-running the command and grepping it — a live build ran it four times to get there. The
    # summary answers it once; `--only-unmatched` prints just those lines for a rules file being
    # iterated on.
    # By RULE, not by line: one rule with two bad fields printed two lines and the summary counted
    # it twice, then called it "matched" as well — a rule that will kill assembly reported as fine.
    def _rule_ids(pred) -> set[str]:
        return {l.split(":", 1)[0] for l in report if pred(l)}
    unmatched_rules = _rule_ids(lambda l: "matched NOTHING" in l)
    undeclared_rules = _rule_ids(lambda l: "REFUSES an undeclared target" in l)
    unmatched = [l for l in report if "matched NOTHING" in l]
    undeclared = [l for l in report if "REFUSES an undeclared target" in l]
    shown_lines = (unmatched + undeclared) if only_unmatched else report
    for line in shown_lines:
        print(("  " if "→" in line else "  WARN ") + line, file=sys.stderr)
    for line in coverage_report(m, doc):
        print("  WARN " + line, file=sys.stderr)
    unknown_ids = len(unresolved_ids(m, rules))
    bad = unmatched_rules | undeclared_rules
    # COUNT THE IDS THAT RESOLVED TO NOTHING, not only the rules that matched nothing at all. A rule
    # naming 190 ids of which 111 are absent still assigns the other 79, so it is not "matched
    # NOTHING" and the summary called the whole run clean: on the 2026-09-02 mcpolis build the block
    # directives carried 111 unresolvable rule ids and this line read "479 clean". The per-rule
    # detail was printed above and scrolled past; the SUMMARY is the line a build reads.
    # DERIVED, not re-parsed. The summary used to read its own report sentence back with a regex,
    # so a one-word rewording would silently zero the count and send the summary back to calling a
    # run with 111 unresolved ids "clean" — the very bug it exists to report.
    print(f"  SUMMARY: {len(rules)} rule(s) — {len(rules) - len(bad)} clean, "
          f"{len(unmatched_rules)} matched nothing"
          + (f" ({', '.join(sorted(unmatched_rules))})" if unmatched_rules else "") + ", "
          f"{len(undeclared_rules)} assign an undeclared target."
          + (f"  {unknown_ids} NAMED ID(S) ARE NOT IN THE MAP and were assigned nothing — a rule "
             f"that resolves SOME of its ids is not a clean rule." if unknown_ids else "")
          + ("" if not (unmatched or undeclared) else
             "  Re-run with --only-unmatched to see just those."), file=sys.stderr)
    total = sum(len(s["ids"]) for s in doc["set"])
    if total == 0:
        print("ERROR: no element matched any rule — nothing written (check the source_glob "
              "prefixes against the map's anchors)", file=sys.stderr)
        return 1
    if dry:
        print(json.dumps(doc, indent=2))
        print(f"\n(dry run — {total} assignment(s) in {len(doc['set'])} group(s); "
              f"re-run without --dry-run to write {out_path})", file=sys.stderr)
        return 0
    # CARRY FORWARD the directives this command does not author. It writes only `set`, and the
    # write is whole-file — so a `set_anchors` / `keep_edges` / `drop_edges` block recorded by
    # `fix apply-drift --to-reconcile` or `fix dedup-edge --to-reconcile` was silently deleted by
    # the next ordinary `coyomap reconcile`, into the SAME default file. The map then reverted to
    # the drifted anchors or the restored duplicates with nothing said, which is precisely the
    # durability those flags exist to provide.
    out = Path(out_path)
    carried: dict[str, object] = {}
    if out.exists():
        try:
            prior = json.loads(out.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"ERROR: {out_path} already exists and is not valid JSON ({e}) — refusing to "
                  f"overwrite it. Fix or delete it, then re-run.", file=sys.stderr)
            return 2
        if isinstance(prior, dict):
            carried = {k: v for k, v in prior.items() if k != "set" and v}
    # THE CARRY-FORWARD IS KEYED ON `--out`, so a temp path silently loses it. A live build ran
    # `--out /tmp/reconcile-new.json` while `.coyomap/reconcile.json` held keep_edges (5),
    # drop_edges and set_anchors, got no carry-forward because the temp file did not exist, and
    # hand-merged the three keys back in python. The tool's own `Next:` hint then echoed the temp
    # path into the suggested `assemble` line, reinforcing it. Say it, rather than let the absence
    # of a message read as "there was nothing to carry".
    if not carried and str(out) != _DEFAULT_RECONCILE:
        live = Path(_DEFAULT_RECONCILE)
        if live.exists():
            try:
                prior_live = json.loads(live.read_text(encoding="utf-8"))
            except ValueError:
                prior_live = None
            if isinstance(prior_live, dict):
                stranded = {k: v for k, v in prior_live.items() if k != "set" and v}
                if stranded:
                    print("WARNING: --out is " + str(out) + ", but " + _DEFAULT_RECONCILE
                          + " already holds " + ", ".join(
                              f"{k} ({len(v) if isinstance(v, list) else 1})"
                              for k, v in sorted(stranded.items()))
                          + ". The carry-forward is keyed on --out, so those directives are NOT in "
                            "the file being written and `assemble --reconcile " + str(out)
                          + "` would drop them. Write to " + _DEFAULT_RECONCILE
                          + " instead, or merge them yourself.", file=sys.stderr)
    if carried:
        doc.update(carried)
        print("reconcile: carried forward " + ", ".join(
            f"{k} ({len(v) if isinstance(v, list) else 1})" for k, v in sorted(carried.items()))
            + f" already recorded in {out_path} — only `set` is regenerated.", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"reconcile -> {out_path}  ({total} assignment(s) in {len(doc['set'])} group(s))")
    print(f"Next: coyomap assemble <fragments…> --out .coyomap --reconcile {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
