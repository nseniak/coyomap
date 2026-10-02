#!/usr/bin/env python3
"""coyomap structural pre-index — sizes and locates the codebase BEFORE the structural harvest.

Emits ``.coyomap/preindex.json`` with five products (see internal/docs/scaling-to-large-codebases.md,
finding G1):

  1. weight  — a directory tree with LOC, file count and git churn (all languages). The signal that
               turns "65 plugins" into "65 plugins = X% of the tree, all alive" -> drill, don't collapse.
  2. symbols — class/function definitions -> file:line + kind, ALL matches (ambiguity surfaced).
  3. imports — for component pairs the agent already NAMED (--pairs), the import edges between them,
               a lower-bound cross-check (absence != no-dependency).
  4. granularity — the code-derived component expectation E (whole-repo + per-slice), the LEAF-count
               zoom anchor the harvest plan hands each agent (method.md's component-granularity rule).
  5. coverage— what the tool could NOT see (GR3): unparsed = unknown, never empty.

This is an ADVISORY INPUT the build agent reconciles (accept/reject/abstract) — never rows copied
into the map verbatim (GR2). Weight is a hint to where to look, never a decision to drill (GR5). The
validator never reads this file; it re-measures (GR4).

Usage:
  coyomap preindex [--root .] [--out .coyomap/preindex.json] [--since <rev|date>]
                   [--pairs pairs.json] [--max-depth N]
  coyomap preindex --report [--root <repo> | --in <path>] [--depth N] [--top N | --dirs a,b,c]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from coyomap.ignorefile import bad_line_disclosure, ignore_report
from coyomap.preindex_lib import (
    GRANULARITY_BAND_PCT,
    GRANULARITY_FILE_CAP,
    GRANULARITY_LOC_CAP,
    SYMBOL_LANGS,
    ImportRef,
    Symbol,
    count_loc,
    expected_components,
    git_churn,
    granularity_band,
    imports_for,
    iter_source_files,
    lang_of,
    median_file_loc,
    slice_expectations,
    symbols_for,
    ts_available,
)


def _arg(argv: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


# --------------------------------------------------------------------------------------
# 1. weight tree (directory-level; files aggregated, not listed, so the artifact stays small)
# --------------------------------------------------------------------------------------

def build_weight(files: list[Path], root: Path, churn: dict[str, int],
                 max_depth: int | None) -> tuple[dict, dict[str, int]]:
    """Nested directory tree, each node carrying aggregated loc/file_count/churn + lang mix.
    Also returns per-language file counts (for the coverage block)."""
    root = root.resolve()
    tree: dict = {"path": ".", "loc": 0, "file_count": 0, "churn": 0,
                  "lang": None, "langs": {}, "children": {}}
    lang_counts: dict[str, int] = {}

    for f in files:
        rel = f.relative_to(root)
        loc = count_loc(f)
        lang = lang_of(f) or "other"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        c = churn.get(str(rel), 0)
        parts = rel.parts[:-1]  # directory chain (exclude the filename)
        if max_depth is not None:
            parts = parts[:max_depth]
        node = tree
        node["loc"] += loc
        node["file_count"] += 1
        node["churn"] += c
        node["langs"][lang] = node["langs"].get(lang, 0) + 1
        cur = root
        for part in parts:
            cur = cur / part
            child = node["children"].get(part)
            if child is None:
                child = {"path": str(cur.relative_to(root)), "loc": 0, "file_count": 0,
                         "churn": 0, "lang": None, "langs": {}, "children": {}}
                node["children"][part] = child
            child["loc"] += loc
            child["file_count"] += 1
            child["churn"] += c
            child["langs"][lang] = child["langs"].get(lang, 0) + 1
            node = child

    return _finalize_weight(tree), lang_counts


def _finalize_weight(node: dict) -> dict:
    """Turn children dicts into lists sorted by LOC desc (heaviest first = the scoping signal),
    and set each node's dominant language."""
    children = [_finalize_weight(c) for c in node["children"].values()]
    children.sort(key=lambda n: n["loc"], reverse=True)
    node["children"] = children
    if node["langs"]:
        node["lang"] = max(node["langs"].items(), key=lambda kv: kv[1])[0]
    return node


# --------------------------------------------------------------------------------------
# 2 + 3. symbols and imports
# --------------------------------------------------------------------------------------

def build_symbols(files: list[Path], root: Path) -> tuple[dict, dict]:
    root = root.resolve()
    by_name: dict[str, list[dict]] = {}
    # Per-file symbol EXTENTS — `{file: [[start, end, name, kind], ...]}` sorted by start line.
    # The impact engine's symbol-resolution rung reads these (an anchor's enclosing definition
    # interval); by_name keeps its shape so existing consumers (serve's symbol search) are untouched.
    extents: dict[str, list[list[object]]] = {}
    parsed = 0
    failures: list[dict] = []
    langs_with: set[str] = set()
    langs_without: dict[str, int] = {}

    for f in files:
        lang = lang_of(f)
        if lang is None:
            continue
        rel = str(f.relative_to(root))
        if lang not in SYMBOL_LANGS:
            langs_without[lang] = langs_without.get(lang, 0) + 1
            continue
        try:
            syms: list[Symbol] = symbols_for(f, rel, lang)
        except Exception as exc:
            failures.append({"file": rel, "lang": lang, "error": f"{type(exc).__name__}: {exc}"})
            continue
        parsed += 1
        langs_with.add(lang)
        for s in syms:
            by_name.setdefault(s.name, []).append({"file": s.file, "line": s.line, "kind": s.kind})
            if s.end is not None:
                extents.setdefault(s.file, []).append([s.line, s.end, s.name, s.kind])
    for rows in extents.values():
        rows.sort(key=lambda r: (r[0], -(r[1] if isinstance(r[1], int) else 0)))

    ambiguous = sorted(n for n, defs in by_name.items() if len(defs) > 1)
    meta = {
        "files_parsed": parsed,
        "parse_failures": failures,
        "languages_with_symbols": sorted(langs_with),
        "languages_seen_without_extractor": dict(sorted(langs_without.items())),
    }
    return {"by_name": by_name, "ambiguous": ambiguous, "extents": extents}, meta


def _matches_target(module: str, target_prefixes: list[str]) -> bool:
    """Lower-bound match: does an import's module text reference one of the target's paths, on
    PATH-SEGMENT boundaries? A lower bound must produce no false edges (only false negatives), so
    matching is boundary-only — exact, prefix (the module lives *under* the target path), or the
    target appearing as a whole segment-run inside the module path. Raw-substring matches are
    deliberately excluded, so `core` does NOT match `scoreboard` and `api` does NOT match `rapidjson`."""
    norm = module.replace(".", "/").strip().strip("/")
    bounded = f"/{norm}/"
    for pre in target_prefixes:
        p = pre.strip().strip("/")
        if not p:
            continue
        if norm == p or norm.startswith(p + "/") or f"/{p}/" in bounded:
            return True
    return False


def build_imports(files: list[Path], root: Path, pairs_path: str | None) -> tuple[dict, dict]:
    root = root.resolve()
    semantics = "lower-bound; absence != no-dependency (dynamic/string/plugin loading is invisible)"
    if not pairs_path:
        return ({"mode": "pairs", "semantics": semantics, "pairs": [],
                 "note": "no --pairs given; rerun with named component->path mapping to get edges"},
                {"pairs_checked": 0, "files_scanned": 0, "parse_failures": []})

    mapping: dict[str, list[str]] = json.loads(Path(pairs_path).read_text())
    # index imports per file once
    file_imports: dict[str, list[ImportRef]] = {}
    failures: list[dict] = []
    scanned = 0
    for f in files:
        lang = lang_of(f)
        if lang is None or lang not in SYMBOL_LANGS:
            continue
        rel = str(f.relative_to(root))
        try:
            file_imports[rel] = imports_for(f, rel, lang)
            scanned += 1
        except Exception as exc:
            failures.append({"file": rel, "error": f"{type(exc).__name__}: {exc}"})

    def files_under(prefixes: list[str]) -> list[str]:
        pres = [p.strip().strip("/") for p in prefixes]
        return [rel for rel in file_imports
                if any(rel == p or rel.startswith(p + "/") for p in pres)]

    pairs_out: list[dict] = []
    comps = list(mapping.items())
    for a_id, a_paths in comps:
        a_files = files_under(a_paths)
        for b_id, b_paths in comps:
            if a_id == b_id:
                continue
            edges: list[dict] = []
            for rel in a_files:
                for imp in file_imports[rel]:
                    if _matches_target(imp.module, b_paths):
                        edges.append({"file": imp.file, "line": imp.line, "imported": imp.module})
            if edges:
                pairs_out.append({"from": a_id, "to": b_id, "count": len(edges),
                                  "import_edges": edges[:25]})

    return ({"mode": "pairs", "semantics": semantics, "pairs": pairs_out},
            {"pairs_checked": len(pairs_out), "files_scanned": scanned, "parse_failures": failures})


# --------------------------------------------------------------------------------------
# 4. granularity expectation E (the leaf anchor — see method.md's component-granularity rule)
# --------------------------------------------------------------------------------------

def build_granularity(root: Path) -> dict:
    """The code-derived component expectation E — whole-repo plus per-slice — surfaced to the
    BUILDER. Integrity-safe by construction: E derives from the code tree the blinded builder
    already sees, never from any map. `validate --check-coverage` and the eval RE-COMPUTE it from
    the tree at check time (shared code, never this JSON — GR4)."""
    tree = expected_components(root)
    lo, hi = granularity_band(tree.expected)
    # WHICH CAP BOUND E. E is `max(files/file_cap, loc/loc_cap)` per directory, so on a codebase of
    # many small files (a file-per-UI-component frontend) the FILE cap fires long before the LOC cap
    # and E climbs well above what the LOC mass suggests. Three of four live builds disagreed with E
    # by 2-4x and had to spend a `granularity` exception on it — with no way to see WHY. Reporting
    # both ceilings turns a blind disagreement into an informed altitude decision (GR2/GR5).
    by_files = -(-tree.files // GRANULARITY_FILE_CAP)
    by_loc = -(-tree.loc // GRANULARITY_LOC_CAP)
    return {
        "counted_files": tree.files,
        "counted_loc": tree.loc,
        "ceiling_by_file_count": by_files,
        "ceiling_by_loc": by_loc,
        "bound_by": ("file-count" if by_files > by_loc else
                     "LOC" if by_loc > by_files else "both equally"),
        "median_file_loc": median_file_loc(root),
        "rule": ("one component ≈ one module-/folder-sized unit "
                 f"(≤ ~{GRANULARITY_FILE_CAP} source files / ≤ ~{GRANULARITY_LOC_CAP} LOC); "
                 "component-shaped dir → stop (leaf), subsystem-shaped → recurse"),
        "file_cap": GRANULARITY_FILE_CAP,
        "loc_cap": GRANULARITY_LOC_CAP,
        "expected_components": tree.expected,
        "band_pct": GRANULARITY_BAND_PCT,
        "band": [lo, hi],
        "per_dir": slice_expectations(tree),
        "note": ("Advisory zoom anchor for the LEAF decision only — subsystem count/nesting stays "
                 "yours. Landing far under the band means subsystem-shaped dirs were folded into "
                 "single components; far over means module-sized units were split. Derived from the "
                 "code tree alone (docs/config/tests excluded); reconcile like any pre-index signal "
                 "(GR2), the checkers re-measure it independently (GR4)."),
    }


# --------------------------------------------------------------------------------------
# 5. --report — the READ path over an existing pre-index
# --------------------------------------------------------------------------------------

def _fmt_int(n: object) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def _weight_lines(node: dict, depth: int, max_depth: int, out: list[str]) -> None:
    """The directory weight tree, heaviest child first (the JSON is already sorted by LOC desc)."""
    pad = "  " * depth
    path = node.get("path") or "."
    out.append(f"{pad}{path}  loc={_fmt_int(node.get('loc'))} "
               f"files={_fmt_int(node.get('file_count'))} "
               f"churn={_fmt_int(node.get('churn'))} lang={node.get('lang')}")
    if depth >= max_depth:
        kids = node.get("children") or []
        if kids:
            out.append(f"{pad}  … {len(kids)} more child dir(s) — raise --depth to see them")
        return
    for child in node.get("children") or []:
        _weight_lines(child, depth + 1, max_depth, out)


def report(argv: list[str]) -> int:
    """Print an existing `preindex.json` as the summary the build actually needs.

    The stderr summary of a BUILD run carries only the top-5 dirs and the whole-repo E, but the
    harvest plan needs the weight tree and the PER-SLICE E (`granularity.per_dir`) — which live
    only inside the JSON. Without this, every build hand-writes throwaway JSON-parsing code, which
    is exactly what method.md's "don't reverse-engineer the JSON" tells it not to do.

    WHICH PRE-INDEX. The method tells build agents to run the CLI from the coyomap clone, so the
    CWD is routinely NOT the analysed repo. `--report` therefore honours `--root` exactly as the
    build path does: `<root>/.coyomap/preindex.json`. Precedence is explicit `--in` > `--root` >
    the CWD default, so a bare `--report` behaves as it always did. Before this, `--root` was
    accepted and dropped, and the current repo's pre-index was printed under the other repo's
    name — measured on two of four real builds, which burned 2-4 calls recovering."""
    # Build-only flags are REJECTED, never silently swallowed: `--report` reads an artifact and
    # writes nothing, so there is no honest reading of "report, but with --max-depth 3". Accepting
    # and ignoring is the failure mode with no visible symptom (tests/test_method_contract.py).
    for flag in ("--out", "--since", "--pairs", "--max-depth"):
        if flag in argv:
            sys.stderr.write(
                f"preindex --report: {flag} applies to the BUILD, not the report.\n"
                "  --report only READS an existing pre-index; it writes nothing and re-measures "
                "nothing.\n"
                f"  build with it:   coyomap preindex --root <repo> {flag} <value>\n"
                "  then report it:  coyomap preindex --report --root <repo>\n")
            return 2

    # Precedence: an explicit --in wins (it names the file outright), else --root names the repo
    # whose pre-index to read, else the CWD default (unchanged behaviour when neither is passed).
    explicit_in = _arg(argv, "--in")
    root_arg = _arg(argv, "--root")
    if explicit_in is not None:
        in_path = Path(explicit_in)
    elif root_arg is not None:
        in_path = Path(root_arg) / ".coyomap" / "preindex.json"
    else:
        in_path = Path(".coyomap") / "preindex.json"
    try:
        depth = int(_arg(argv, "--depth", "2") or 2)
        top = int(_arg(argv, "--top", "40") or 40)
        raw_dirs = _arg(argv, "--dirs", "") or ""
        dirs = [d.strip().rstrip("/") for d in raw_dirs.split(",") if d.strip()]
    except ValueError:
        sys.stderr.write("preindex --report: --depth and --top take an integer\n")
        return 2
    if not in_path.is_file():
        sys.stderr.write(f"preindex --report: no pre-index at {in_path}\n"
                         "  build one first: coyomap preindex --root <repo>\n"
                         "  then report it:  coyomap preindex --report --root <repo>\n")
        return 2
    try:
        doc = json.loads(in_path.read_text())
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"preindex --report: cannot read {in_path}: {exc}\n")
        return 2

    weight = doc.get("weight") or {}
    gran = doc.get("granularity") or {}
    cov = doc.get("coverage") or {}
    syms = doc.get("symbols") or {}
    out: list[str] = [f"pre-index {in_path}  (root {doc.get('root')})", "", f"WEIGHT TREE (depth {depth}, heaviest first)"]
    _weight_lines(weight, 0, depth, out)

    band = gran.get("band") or [None, None]
    out += ["", f"GRANULARITY — expected components E={gran.get('expected_components')} "
                f"(band {band[0]}–{band[1]}; caps {gran.get('file_cap')} files / "
                f"{_fmt_int(gran.get('loc_cap'))} LOC per component)"]
    if gran.get("bound_by"):
        out += [f"  bound by {gran['bound_by']}: file-count ceiling {gran.get('ceiling_by_file_count')} "
                f"vs LOC ceiling {gran.get('ceiling_by_loc')} "
                f"over {_fmt_int(gran.get('counted_files'))} files / "
                f"{_fmt_int(gran.get('counted_loc'))} LOC "
                f"(median file {gran.get('median_file_loc')} LOC)"]
        if gran.get("bound_by") == "file-count" and int(gran.get("median_file_loc") or 0) < 80:
            # The escape used to be written for ONE direction only — "if you build under the band"
            # — and a build that landed 27% ABOVE E, against the note's own stated expectation, hit
            # nothing: the band is wide (±40%), so no gate fired and no record was asked for. The
            # note is a DIRECTION, not a band, and a build that goes the other way owes the same
            # sentence. Say both, and say it about the note rather than about the band.
            out += ["  NOTE: the FILE cap binds and files are small, so E counts many tiny files as",
                    "        unit-sized mass. Expect the honest altitude to sit BELOW E here.",
                    "        Record the literal `granularity` under a 'Balance exceptions' extras",
                    "        heading, with the why, if you land OUTSIDE the band in either direction",
                    "        — or ABOVE E at all, which is the opposite of what this note expects",
                    "        and is the case the band is too wide to catch."]
    per = gran.get("per_dir") or {}
    out.append("  Hand each harvest agent ITS slice's number — never a gut estimate (method.md).")
    if dirs:
        # A RANKING cannot answer "E for the slices I chose". The lead picks slices by product
        # boundary, and the small ones it needs most are never in a top-N — one build asked for 32
        # directories of which several score 1, so it hand-parsed the JSON instead, which is the one
        # thing `--report` exists to stop. Lookup order is the ORDER ASKED, not by size.
        # NORMALISED, and honest about what "not found" means. The lookup is against the slice set
        # the pre-index RECORDED, not the disk — so `./eval` and `EVAL` missed a directory that is
        # right there, and a bare dash is exactly the prompt for the gut estimate this feature
        # exists to remove. A directory that exists but scores nothing is a different answer from
        # one the pre-index never saw, and the reader needs to tell them apart.
        norm = {k.strip("./").lower(): k for k in per}
        root_dir = Path(_arg(argv, "--root", ".") or ".")
        out.append(f"  per-directory E for the {len(dirs)} director(y/ies) you named:")
        for d in dirs:
            key = norm.get(d.strip("./").lower())
            if key is not None:
                out.append(f"    {per[key]:6d}  {key}" + ("" if key == d else f"   (matched {d})"))
            elif (root_dir / d).is_dir():
                out.append(f"         0  {d}   (exists, but anchors no component-forming source)")
            else:
                out.append(f"         -  {d}   (not a directory under {root_dir})")
    else:
        out.append("  per-directory E (top %d):" % top)
        for k, v in sorted(per.items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
            out.append(f"    {v:6d}  {k}")
        if len(per) > top:
            out.append(f"    … {len(per) - top} more dir(s) — raise --top, or name them with "
                       f"--dirs a,b,c")

    out += ["", "COVERAGE — what the pre-index could NOT see (unparsed = UNKNOWN, not empty)",
            f"  files counted: {_fmt_int(cov.get('files_counted'))} "
            f"(skipped/excluded {_fmt_int(cov.get('files_skipped_excluded'))})",
            f"  git={cov.get('git_available')} tree-sitter={cov.get('tree_sitter_available')} "
            f"symbol files parsed={_fmt_int(cov.get('symbol_files_parsed'))}",
            f"  ambiguous symbol names: {len(syms.get('ambiguous') or [])}",
            f"  languages seen WITHOUT a symbol extractor: "
            f"{list(cov.get('languages_seen_without_extractor') or {})}"]
    fails = cov.get("symbol_parse_failure_count") or 0
    if fails:
        out.append(f"  symbol parse failures: {fails}")
    # The one input that can hide a real gap from the check built to find gaps — so the report
    # NAMES the patterns, never just the count. A reader who disagrees with the map's coverage can
    # see immediately whether the tree or the ignore file is the reason. The unusable lines are
    # named too, in validate's words, and open the block on their own when no line was usable.
    ignored_n = cov.get("files_skipped_ignored") or 0
    ignore_pats = list(cov.get("ignore_patterns") or [])
    ignore_unused = list(cov.get("ignore_patterns_unused") or [])
    ignore_unusable = list(cov.get("ignore_lines_unusable") or [])
    if ignore_pats or ignore_unusable:
        out += ["", f"IGNORED BY .coyomap/.ignore — {_fmt_int(ignored_n)} file(s), "
                    f"{len(ignore_pats)} pattern(s). These are OUT of the weight tree, out of E, "
                    f"and out of the coverage check."]
        out += [f"    {p}" for p in ignore_pats]
        if ignore_unused:
            out += [f"    ^ {len(ignore_unused)} pattern(s) decided NOTHING: "
                    f"{', '.join(ignore_unused)} — a typo, a moved tree, or already covered by a "
                    f"built-in exclusion."]
        out += [f"    ^ {line}" for line in bad_line_disclosure(ignore_unusable)]
    out += ["", "Reconcile every item — this is advisory INPUT, never rows for the map (GR2);",
            "weight sets attention, your judgement sets altitude (GR5)."]
    print("\n".join(out))
    return 0


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------

USAGE = """usage: coyomap preindex [--root .] [--out .coyomap/preindex.json] [--since <rev|date>]
                        [--pairs pairs.json] [--max-depth N]
       coyomap preindex --report [--root <repo> | --in <path>] [--depth N] [--top N | --dirs a,b,c]

Build the structural pre-index, or (--report) print an existing one as a readable summary:
the weight tree, the per-directory component expectation E, and the coverage block.
--report READS the JSON and writes nothing.
--dirs a,b,c prints E for exactly those directories, in the order asked, instead of the
top-N ranking — a ranking cannot answer "E for the slices I chose", and the small slices a
harvest plan needs are never in it.

--report picks the file to read as: --in <path> if given, else <root>/.coyomap/preindex.json
if --root is given, else ./.coyomap/preindex.json. Pass --root (or --in) whenever you run the
CLI from somewhere other than the analysed repo — otherwise you read the CWD repo's pre-index.
The build-only flags (--out, --since, --pairs, --max-depth) are rejected under --report."""


def _gr1_status(root: Path, out_path: Path) -> str:
    """Whether a behavioral draft exists yet — GR1, checked instead of only announced.

    The GR1 line above has been printed on every run for as long as it has existed, and a live
    build read it and went straight into a 14-agent structural harvest anyway; its behavioral
    fragment was written 79 turns later. The ordering matters because the behavioral layer is what
    the structural slices are supposed to serve, and it is stated once, at method.md:582, in the
    seam between two paged Reads of a 1553-line file.

    A printed rule nobody reads is fixed by checking it, not by printing it louder. This is
    deliberately a LOUD WARNING and not a refusal: `preindex` is also run outside a build (to size
    a repo, to re-read a report), and a hard failure there would be wrong. What it removes is the
    ability to walk past GR1 without being told, by name, that it has not been met.
    """
    # Keyed off the SCANNED ROOT, not `--out`'s parent: `--out` is routinely pointed somewhere
    # else (a scratch path, a report copy), and keying off it reported "no build-fragments" for a
    # repo that had 33 of them. The out-path's own `.coyomap/` is still consulted as a fallback for
    # the case where the two genuinely differ.
    candidates = [root / ".coyomap" / "build-fragments", out_path.parent / "build-fragments"]
    frags = next((c for c in candidates if c.is_dir()), candidates[0])
    if not frags.is_dir():
        return ("  GR1 NOT MET: no .coyomap/build-fragments/ yet, so no behavioral draft exists. "
                "Draft Goal -> Glossary -> Roles -> Use cases -> Happy-Path skeleton FIRST; the "
                "structural slices exist to serve it.\n")
    # By CONTENT, not by filename. `behavioral.json` is a habit, not a contract — the method names
    # no such file, so a build that called it `L1-usecases.json` would get a false "NOT MET", which
    # teaches readers to ignore the warning: exactly the failure this check is about. It is also
    # trivially satisfied by an empty file. The behavioral layer IS these sections.
    behavioral = []
    for f in sorted(frags.glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and any(doc.get(k) for k in
                                         ("use_cases", "happy_path", "roles", "glossary")):
            behavioral.append(f.name)
    if behavioral:
        return f"  GR1 met: behavioral draft present ({', '.join(behavioral)}).\n"
    return ("  GR1 NOT MET: no fragment in .coyomap/build-fragments/ carries use_cases, happy_path, "
            "roles or glossary. A live build read this same NOTE, harvested 14 structural slices "
            "anyway, and wrote its behavioral layer 79 turns later.\n")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `--help` must never RUN the pre-index: it writes `.coyomap/preindex.json`, so a help request
    # would clobber the artifact (and walk a 3M-LOC tree). Every other subcommand guards this.
    if "-h" in argv or "--help" in argv:
        print(USAGE)
        return 0
    if "--report" in argv:
        return report(argv)
    # Reject unknown options. `preindex` accepted anything and exited 0, so `--outt out.json` (a
    # one-letter typo) silently dropped the flag, wrote to the DEFAULT path and reported success —
    # rewriting a committed artifact the caller never meant to touch. It was the last command in the
    # package that did not refuse, and the only one where the silence is destructive.
    known = {"--root", "--out", "--since", "--pairs", "--max-depth", "--report", "--in", "--depth",
             "--top", "--dirs"}
    unknown = [a for a in argv if a.startswith("-") and a not in known]
    if unknown:
        print(f"ERROR: unknown option(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    # A BARE POSITIONAL was silently discarded, and this command defaults `--root` to the CWD — so
    # `coyomap preindex <some/repo>` scanned wherever you happened to be standing and said nothing.
    # Live: it printed `GR1 met: behavioral draft present` for a path holding no fragments at all,
    # having read a different repo. Assertion 22 calls that GR1 line the authoritative signal, so a
    # silently-wrong root corrupts a measurement two layers away. The refusal above exists for
    # exactly this class; it only ever looked at `-`-prefixed tokens.
    valued = {"--root", "--out", "--since", "--pairs", "--max-depth", "--in", "--depth", "--top"}
    positionals: list[str] = []
    skip = False
    for i, a in enumerate(argv):
        if skip:
            skip = False
            continue
        if a in valued:
            skip = True
        elif not a.startswith("-"):
            positionals.append(a)
    if positionals:
        print(f"ERROR: unexpected argument(s): {', '.join(positionals)} — this command takes "
              f"options only. Did you mean `--root {positionals[0]}`?", file=sys.stderr)
        return 2
    root = Path(_arg(argv, "--root", ".") or ".").resolve()
    out_path = Path(_arg(argv, "--out", str(root / ".coyomap" / "preindex.json")) or "")
    since = _arg(argv, "--since")
    pairs_path = _arg(argv, "--pairs")
    md = _arg(argv, "--max-depth")
    max_depth = int(md) if md else None

    walk = iter_source_files(root)
    # Per-pattern, shared with validate's advisory and the viewer's tree so one ignore file cannot
    # be described three different ways. Built on every run, since an absent file gives an empty
    # report: gating on the patterns hid the file whose EVERY line is unusable, which has none.
    ignore_rep = ignore_report(walk.ignore, walk.ignore_hits)
    churn, git_ok = git_churn(root, since)
    weight, lang_counts = build_weight(walk.files, root, churn, max_depth)
    symbols, sym_meta = build_symbols(walk.files, root)
    imports, imp_meta = build_imports(walk.files, root, pairs_path)
    granularity = build_granularity(root)

    ts_ok = ts_available()
    coverage = {
        "files_total_walked": len(walk.files) + walk.skipped_excluded + walk.skipped_ignored,
        "files_counted": len(walk.files),
        "files_skipped_excluded": walk.skipped_excluded,
        # The repo's own `.coyomap/.ignore`, recorded in the artifact so a reader of the map can
        # always see what the tree measurement was told to leave out, and on what patterns. Per
        # PATTERN, not just the total: a pattern that removed nothing is a typo or a moved tree, and
        # the total is exactly where that disappears.
        "files_skipped_ignored": walk.skipped_ignored,
        "ignore_patterns": list(ignore_rep.per_rule),
        "ignore_patterns_unused": list(ignore_rep.unused),
        # Lines that parsed to nothing, as written. Each excludes nothing although its author meant
        # it to, and the per-pattern list cannot show that: those lines never became patterns.
        "ignore_lines_unusable": list(ignore_rep.bad_lines),
        "languages_seen": dict(sorted(lang_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "languages_with_symbols": sym_meta["languages_with_symbols"],
        "languages_seen_without_extractor": sym_meta["languages_seen_without_extractor"],
        "symbol_files_parsed": sym_meta["files_parsed"],
        "symbol_parse_failures": sym_meta["parse_failures"][:50],
        "symbol_parse_failure_count": len(sym_meta["parse_failures"]),
        "import_pairs_checked": imp_meta["pairs_checked"],
        "git_available": git_ok,
        "tree_sitter_available": ts_ok,
        "used_git_ls_files": walk.used_git,
        "note": ("Unparsed regions are UNKNOWN, not empty — read them. Symbol/import data is deep "
                 "for Python (ast); other languages need the tree-sitter grammar pack. "
                 "Weight is a hint to where to look, never a decision to drill (GR5)."),
    }

    doc = {
        "tool": "coyomap preindex",
        "root": str(root),
        "weight": weight,
        "symbols": symbols,
        "imports": imports,
        "granularity": granularity,
        "coverage": coverage,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2))

    # one-line human summary to stderr (GR1 reminder + GR3 coverage at a glance)
    top = weight["children"][:5]
    sys.stderr.write(
        f"preindex -> {out_path}\n"
        + (f"  .coyomap/.ignore: {walk.skipped_ignored} file(s) excluded by "
           f"{len(walk.ignore.rules)} pattern(s) — this narrows the tree the coverage check "
           f"re-measures too\n" if walk.ignore else "")
        + (f"  .coyomap/.ignore: {len(ignore_rep.unused)} pattern(s) decided NOTHING — "
           f"{', '.join(ignore_rep.unused)}\n" if ignore_rep.unused else "")
        + "".join(f"  {line}\n" for line in bad_line_disclosure(ignore_rep.bad_lines))
        + f"  {coverage['files_counted']} files, {weight['loc']} LOC; "
        f"git={'yes' if git_ok else 'NO'}, tree-sitter={'yes' if ts_ok else 'NO'}\n"
        f"  heaviest top-level: " + ", ".join(f"{c['path']}({c['loc']})" for c in top) + "\n"
        f"  symbols: {sym_meta['files_parsed']} files parsed, "
        f"{len(symbols['ambiguous'])} ambiguous names; "
        f"languages without symbols: {list(coverage['languages_seen_without_extractor'])}\n"
        f"  granularity: expect ~{granularity['expected_components']} components "
        f"(band {granularity['band'][0]}–{granularity['band'][1]}, bound by "
        f"{granularity['bound_by']}, median file {granularity['median_file_loc']} LOC)\n"
        # Name the artifact this run just wrote. A bare `coyomap preindex --report` reads the
        # CWD's pre-index, and the method has builds run the CLI from the coyomap clone — so a
        # pathless hint is a copy-paste that silently reads the wrong repo whenever the CWD is
        # not the analysed one. Echoing the path makes the suggested command always correct.
        f"  READ IT: coyomap preindex --report --in {out_path}   "
        f"(weight tree + per-slice E + coverage — do NOT hand-parse the JSON)\n"
        "  NOTE: draft the behavioral layer BEFORE using this (GR1); reconcile every item, "
        "never copy verbatim (GR2).\n"
    )
    sys.stderr.write(_gr1_status(Path(root), out_path))
    if not ts_ok:
        sys.stderr.write(
            "  HINT: tree-sitter is not installed, so non-Python languages get no symbols/imports.\n"
            "        Install the pre-index extra into the coyomap venv to enable polyglot support:\n"
            "          <coyomap-home>/.venv/bin/pip install -e '<coyomap-home>[preindex]'\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
