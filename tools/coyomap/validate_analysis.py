#!/usr/bin/env python3
"""Shared helpers behind `coyomap validate`'s semantic checks (`tools/coyomap/validate_model.py`):
  - `check_hierarchy` — grouping/nesting: right-kind parent, defined, no cycles, deep-nest advisory.
  - anchor/source resolution — `strip_anchor`, `_where_href`, `_source_roots`, `_resolve_source_file`.
  - coverage/granularity advisories — `compression_coverage_from_refs` (peer-level compression +
    absent modules, re-measuring the repo tree) and `granularity_advisory` (component count vs the
    code-derived expectation E), plus the domain-coverage building blocks (`_is_non_entity_type`,
    `_type_covered`, the `_ISOLATED_*`/`_UNCOVERED_*` thresholds) and the altitude-hint building
    blocks (`_LIST_ITEM`, `_ALTITUDE_MIN`) `validate_model.py` runs against `ProjectModel` fields.
  - `ignore_disclosure` — the UNCONDITIONAL advisory naming what `.coyomap/.ignore` removed, per
    pattern (the one input able to hide a gap from the checks above, so it runs on every validate,
    not only under `--check-coverage`).
Stdlib-only.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Sequence
from pathlib import Path

# Grammar (regexes, membership rule) lives in grammar, shared with the parser — one grammar.
from coyomap.anchors import FILE_ANCHOR as _BARE_PATH, LINE_ANCHOR, strip_anchor
from coyomap.grammar import DEEP_NEST_WARN
# Stdlib-only, and free of the pre-index code path, so importing it at module load keeps the core
# gate's dependency firewall intact (tests/test_cli.py). The per-rule wording lives there so
# validate, the pre-index and the viewer tell the SAME story about one ignore file, and so does the
# unusable-line sentence, which `coyomap scope` and `coyomap preindex` print too.
from coyomap.ignorefile import bad_line_disclosure, ignore_report, load_ignore
from coyomap.reporting import capped, shown


def _is_subsystem_id(i: str) -> bool:  # an `S` id, never a subdomain (`SD1` also starts with "S")
    return i.startswith("S") and not i.startswith("SD")


def _expected_parent_kind(child: str) -> str:
    """The KIND a child's parent must be: entities (`E`) and subdomains (`SD`) nest under a SUBDOMAIN;
    use cases (`UC`) and capabilities (`CAP`) nest under a CAPABILITY; business rules (`BR`) and
    blocks (`BLK`) nest under a BLOCK; components (`C`) and subsystems (`S`) nest under a SUBSYSTEM.
    Prefix order matters: `CAP1` also starts with "C" and `EP1` with "E", so the multi-letter
    namespaces are tested first (an entry point never has a parent, but it must not be mistaken
    for an entity if one is ever passed in)."""
    if child.startswith(("CAP", "UC")):
        return "capability"
    if child.startswith(("BLK", "BR")):
        return "block"
    if child.startswith("EP"):
        return "subsystem"       # entry points do not nest; never treat `EP1` as an entity
    return "subdomain" if child.startswith(("E", "SD")) else "subsystem"


def _is_parent_kind(par: str, kind: str) -> bool:  # par's id-prefix matches the expected parent kind
    if kind == "capability":
        return par.startswith("CAP")
    if kind == "block":
        return par.startswith("BLK")
    return par.startswith("SD") if kind == "subdomain" else _is_subsystem_id(par)


#: The wrong-parent message, per expected kind. A hard-coded "subdomain else subsystem" ternary
#: already mis-reported a use case parented to a subsystem as "is not a subsystem (S…)"; a fourth
#: forest makes that failure mode certain rather than merely present.
_PARENT_KIND_LABEL = {"subdomain": "subdomain (SD…)", "capability": "capability (CAP…)",
                      "block": "block (BLK…)", "subsystem": "subsystem (S…)"}


def check_hierarchy(parents: dict[str, str], defined: set[str]) -> tuple[list[str], list[str]]:
    """Returns ``(problems, warnings)``. Parent must be the right KIND for the child
    (component/subsystem -> `S`; entity/subdomain -> `SD`; use case/capability -> `CAP`;
    rule/block -> `BLK`) and defined, with no nesting cycles — all
    BLOCKING. Nesting deeper than `DEEP_NEST_WARN` is a non-blocking ADVISORY: arbitrary depth is allowed
    (the viewer renders it), and the cycle check — not a depth cap — is what makes the walk terminate.
    The forests share one walk — their id spaces are disjoint, so a chain never crosses between them.
    The kind check is EXACT, not a bare prefix test: `SD` starts with `S`, so a component pointed at a
    subdomain must still be flagged."""
    problems: list[str] = []
    for child, par in parents.items():
        want = _expected_parent_kind(child)
        if not _is_parent_kind(par, want):
            label = _PARENT_KIND_LABEL[want]
            problems.append(f"{child} parent {par} is not a {label}")
        elif par not in defined:
            problems.append(f"{child} parent {par} is undefined")
    # Walk only well-formed (right-kind) pointers, so a wrong-type parent reported above does not
    # also surface as a spurious "cycle" line.
    valid = {c: p for c, p in parents.items() if _is_parent_kind(p, _expected_parent_kind(c))}
    deep: set[str] = set()
    for start in valid:
        chain, cur, depth = [start], start, 0
        while cur in valid:
            cur = valid[cur]
            depth += 1
            if cur in chain:
                problems.append(f"Nesting cycle: {' -> '.join(chain)} -> {cur}")
                break
            chain.append(cur)
            if depth > DEEP_NEST_WARN:
                deep.add(" -> ".join(chain))  # the over-deep chain (top → leaf), deduped across walks
                break
    warnings = [f"Deep nesting (> {DEEP_NEST_WARN} levels) — is each level pulling its weight? {d}"
                for d in sorted(deep)]
    return problems, warnings


_LIST_ITEM = re.compile(r"^[a-z][a-z0-9_]+$")  # a bare lowercase identifier — a likely sub-unit (dir/module) name
_ALTITUDE_MIN = 6  # this many bare-identifier items in one cell reads as a list of sub-units, not a purpose


_COMPRESSION_MIN = 8      # this many sibling source subdirs folded into ~one box reads as lost signal
_ABSENT_MIN_FILES = 25    # a top-level dir this large with nothing referenced is a likely unmapped module
_ABSENT_DIR_CAP = 8       # unmapped-module findings emitted before the count-only disclosure below
# The conventional NON-PRODUCT directory basenames (test trees, internal/docs) live in
# `preindex_lib.NON_PRODUCT_DIRS` — one list shared with the granularity expectation E; pulled via
# the same local import the coverage check already uses (the core gate stays import-independent).
_REF_LINK = re.compile(r"\]\(([^)\s#]+)")                         # markdown link target ](path...)
_REF_INLINE = re.compile(r"(?<![\w/])((?:[\w.\-]+/)+[\w.\-]+)")   # inline a/b/c path
# A BARE token — no directory part. `_REF_INLINE` requires at least one `/`, so a repo-root file
# (`Makefile`, `manage.py`, `deploy.sh`) could never be seen as referenced, and the map's own
# anchors for them read as unmapped. `_REF_LINK` cannot rescue them either: it only matches markdown
# links, which method.md forbids for anchors ("a bare `path:line`, never a markdown link") — so the
# only pattern that could see a root file was the one the method bans. Bare tokens are matched by
# NAME against the repo root's real entries (never by shape), so this adds no false positives.
_REF_BARE = re.compile(r"(?<![\w/.\-])([\w][\w.\-]*)")
# Monorepo container roots — under these, a fold one level deeper is still an altitude decision
# (`packages/app/plugins`), so look one level further. Under an ordinary package it is not, so a leaf
# component's internal subdirs (`mee6/plugins/achievements/`) stay abstracted (GR6).
_MONOREPO_ROOTS = {"packages", "apps", "services", "libs", "modules", "projects", "workspaces", "crates"}


def _fold_depth_ok(dpath: str) -> bool:
    """Inspect folds at the top/second level — one deeper under a recognized monorepo container."""
    first = dpath.split("/", 1)[0]
    return dpath.count("/") <= (2 if first in _MONOREPO_ROOTS else 1)


def compression_coverage_from_refs(refs: set[str], root: Path,
                                   skip_dirs: frozenset[str] = frozenset()) -> list[str]:
    """Advisory (non-blocking, opt-in via --check-coverage): the map-fidelity counterpart to the
    referential checks, from an already-extracted set of repo-relative referenced paths. Flags two
    *lost-signal* shapes by RE-MEASURING the repo tree (never reading the pre-index's JSON — GR4):
      - peer-level COMPRESSION — a top/second-level directory whose many sibling source subdirs are
        folded into ~one map box (the 65-plugins-as-one-component failure). Only top/second level,
        because a leaf component's internal subdirs are SUPPOSED to be abstracted (GR6).
      - significant ABSENT modules — a top-level dir with many source files that the map never
        references at all.
    Both self-report their denominator. Intentional abstraction is a feature, so this only ever
    WARNS, never blocks (GR6)."""
    # Local import: keep the CORE GATE independent of the advisory pre-index module — the validator
    # imports nothing from it at load time, only this opt-in check pulls the shared (stdlib) walk
    # helper. Reuses CODE, never the pre-index's JSON DATA (GR4: generation != verification).
    from coyomap.preindex_lib import NON_PRODUCT_DIRS, iter_source_files

    root = root.resolve()
    walk = iter_source_files(root)
    dir_children: dict[str, set[str]] = {}
    dir_filecount: dict[str, int] = {}
    for f in walk.files:
        parts = f.relative_to(root).parts
        for i in range(len(parts)):
            dpath = "/".join(parts[:i]) if i else "."
            dir_filecount[dpath] = dir_filecount.get(dpath, 0) + 1
            if i + 1 < len(parts):
                dir_children.setdefault(dpath, set()).add("/".join(parts[:i + 1]))

    def covered_under(prefix: str) -> bool:
        return any(r == prefix or r.startswith(prefix + "/") for r in refs)

    def recorded(dpath: str) -> bool:
        # a 'Coverage exceptions' dir silences this dpath if it is AT OR UNDER the recorded dir
        # (boundary-aware, same rule as covered_under): the operator's conscious coarse-altitude fold.
        return any(dpath == d or dpath.startswith(d + "/") for d in skip_dirs)

    out: list[str] = []
    flagged: set[str] = set()
    for dpath, subs in sorted(dir_children.items()):
        n = len(subs)
        if (dpath == "." or not _fold_depth_ok(dpath) or n < _COMPRESSION_MIN
                or not covered_under(dpath) or recorded(dpath)):
            continue
        covered_subs = sum(1 for s in subs if covered_under(s))
        if covered_subs * 4 < n:  # the map individually represents fewer than ~a quarter of the peers
            flagged.add(dpath)
            out.append(
                f"Compression: {dpath}/ holds {n} sibling source subdirs but the map references paths "
                f"in only {covered_subs} of them — up to {n - covered_subs} peer modules folded into "
                f"~one box; if distinct, drill {dpath}/ into a subsystem ({n} subdirs, measured at "
                f"validate time)"
            )
    # Absent / under-referenced: a dir the map never references that is either large (>= _ABSENT_MIN_FILES
    # files) OR has many sibling subdirs (>= _COMPRESSION_MIN) — the latter catches a small-but-fanned
    # fold the compression pass skips because the map references nothing inside it.
    absent: list[tuple[int, str]] = []
    for dpath, fc in dir_filecount.items():
        if (dpath == "." or not _fold_depth_ok(dpath) or dpath in flagged or covered_under(dpath)
                or recorded(dpath)
                or dpath.rsplit("/", 1)[-1] in NON_PRODUCT_DIRS):  # skip test / internal / docs trees
            continue
        n_subs = len(dir_children.get(dpath, ()))
        if fc >= _ABSENT_MIN_FILES or n_subs >= _COMPRESSION_MIN:
            absent.append((fc, dpath))
    # A per-item cap cannot carry an inline `+N more`, so the dropped count is disclosed below —
    # silently dropping four unmapped modules is worse than a visible tail, because neither a reader
    # nor a `--json` consumer can tell it happened.
    kept, dropped = capped(sorted(absent, reverse=True), _ABSENT_DIR_CAP)
    for fc, dpath in kept:
        n_subs = len(dir_children.get(dpath, ()))
        out.append(
            f"Coverage: {dpath}/ ({fc} source files, {n_subs} subdirs) has no path referenced in the "
            f"map — likely an unmapped module (measured at validate time)"
        )
    if dropped:
        out.append(f"Coverage: {dropped} further directory/directories have no path referenced in the "
                   f"map and are NOT listed above (only the {_ABSENT_DIR_CAP} largest are) — read them "
                   f"all with `validate --check-coverage --json`.")
    return out


_FILE_COVERAGE_DIR_CAP = 12  # directories to list before eliding — grouped, so the reader sees the shape


def file_level_coverage(refs: set[str], root: Path,
                        skip_dirs: frozenset[str] = frozenset()) -> list[str]:
    """Advisory (opt-in via --check-coverage): a CODE source file that no component references — the
    true file-level slice-seam gap the directory-granular `compression_coverage_from_refs` misses (loose
    files inside an otherwise-covered dir slip every harvest slice and validate stays silent).
    Exclusions keep it from flooding on a normal repo (S6):
      1. a file under any referenced DIRECTORY is covered — a dir-anchored `component.source` covers its
         whole subtree, so we test dir-prefix membership, not only an exact path match;
      2. code files only — the granularity source filter (`lang_of` present and not a text lang) drops
         README / yaml / toml / json / markdown, which `iter_source_files` returns but no component owns;
      3. `NON_PRODUCT_DIRS` (test / docs / internal trees) and coyomap's own `.coyomap` / `.coyomap-eval`
         artifacts skipped — both live in `iter_source_files`'s exclude sets;
      4. `__init__.py` package markers skipped — they are (near-always) empty and never a standalone
         component; they only bury the real signal (a non-empty one is a rare, accepted miss).
    The finding is GROUPED BY DIRECTORY (the by-dir shape a lead otherwise re-walks the tree to build —
    a live build did exactly that), capped by directory count. Honors the same 'Coverage exceptions'
    recorded dirs as the compression pass."""
    from coyomap.preindex_lib import (
        GRANULARITY_TEXT_LANGS,
        NON_PRODUCT_DIRS,
        iter_source_files,
        lang_of,
    )

    root = root.resolve()
    # `referenced_paths` already dropped non-existent paths, so an existing ref that is a DIRECTORY on
    # disk is a dir anchor covering its subtree; the rest are exact file refs.
    ref_dirs = {r for r in refs if (root / r).is_dir()}

    def covered(rel: str) -> bool:
        return rel in refs or any(rel == d or rel.startswith(d + "/") for d in ref_dirs)

    def recorded(rel: str) -> bool:
        return any(rel == d or rel.startswith(d + "/") for d in skip_dirs)

    by_dir: dict[str, list[str]] = {}
    total = 0
    for f in iter_source_files(root).files:
        rel = f.relative_to(root)
        if rel.name == "__init__.py":                              # exclusion 4 — empty package markers
            continue
        lang = lang_of(f)
        if lang is None or lang in GRANULARITY_TEXT_LANGS:          # exclusion 2 — code files only
            continue
        if any(part in NON_PRODUCT_DIRS for part in rel.parts[:-1]):  # exclusion 3 — skip non-product trees
            continue
        relstr = "/".join(rel.parts)
        if covered(relstr) or recorded(relstr):                    # exclusion 1 (+ recorded escape)
            continue
        dpath = "/".join(rel.parts[:-1]) or "(root)"               # loose root-level files group under (root)
        by_dir.setdefault(dpath, []).append(rel.name)
        total += 1
    if not by_dir:
        return []
    dirs = sorted(by_dir)
    # Through the shared helper, so `--json` widens this too. It did NOT, and this is the site that
    # made the JSON mode's completeness guarantee false: it is reached under `--check-coverage`, the
    # flag the method tells every build to run right after synthesis, so a machine consumer read
    # `+N more dir(s)` from a payload that had just promised whole lists.
    lines = shown([f"{dpath}/ ({len(by_dir[dpath])}): {', '.join(sorted(by_dir[dpath]))}"
                   for dpath in dirs], _FILE_COVERAGE_DIR_CAP, sep="\n    ", unit="dir(s)").split("\n    ")
    return [f"{total} code source file(s) no component references — a slice-seam gap (loose files inside "
            f"an otherwise-covered dir escape every harvest slice), by directory:\n    "
            + "\n    ".join(lines)
            + "\n  Add each to a component's `files`/`source`, or record its dir under a "
            "'Coverage exceptions' heading."]


def ignore_disclosure(root: Path, mapped_sources: Sequence[str] = ()) -> list[str]:
    """Advisory (non-blocking, and UNCONDITIONAL — not gated on `--check-coverage`): say out loud
    that `.coyomap/.ignore` narrowed the tree.

    Every other coverage check here re-measures the repo INDEPENDENTLY of the pre-index (GR4), so a
    map cannot look complete just because generation said it was. An ignore file is the one input
    that breaks that: the checker and the checked now read the same declaration, so an over-broad
    pattern hides a real gap from BOTH. The feature is still worth having — a trap fixture or a
    vendored tree genuinely is not part of what the map describes — but it must never be silent, or
    it becomes the "advisory waved through" failure one level down: the map reads complete because
    the evidence of incompleteness was excluded before anyone looked.

    Its caller therefore runs it on EVERY validate, including the cheap `--check-sources` pass the
    method tells a lead to run first: a disclosure only the expensive pass emits is a disclosure the
    common invocation does not have.

    So this fires whenever the file is in effect and names each pattern with what it actually did.
    Two failure shapes are called out separately, because both mean the author believes something is
    excluded that is not: a pattern that DECIDED NOTHING on this tree (a typo, a tree that moved, or
    a path a built-in exclusion already covered), and a line that parsed to nothing at all."""
    from coyomap.preindex_lib import iter_source_files

    root = root.resolve()
    # Cheap gate FIRST (a stat, then a cached parse): this now runs on every validate, including the
    # bare gate, and the overwhelmingly common case is no ignore file at all. Walking the tree only
    # to discover there was nothing to disclose would tax every run for a repo that declared nothing.
    #
    # `IgnoreSpec.__bool__` is `bool(rules)` — "does this file remove anything" — so a file whose
    # EVERY line is unusable is falsy. Gating on truthiness alone therefore made the worst case
    # silent: a build that wrote all three of its patterns with trailing comments got zero output
    # instead of a report naming all three, which is the exact input this disclosure exists for.
    # Bad lines are disclosed on their own, before any walk (there is nothing to walk).
    spec0 = load_ignore(root)
    if not spec0:
        return bad_line_disclosure(spec0.bad_lines)
    walk = iter_source_files(root)
    spec = walk.ignore
    if not spec:      # raced away between the two reads — nothing to disclose
        return bad_line_disclosure(spec.bad_lines)
    rep = ignore_report(spec, walk.ignore_hits)
    out: list[str] = [
        f"`.coyomap/.ignore` is in effect: {walk.skipped_ignored} file(s) removed from the analysed "
        f"tree by {len(spec.rules)} pattern(s) — {', '.join(rep.per_rule)}. These are out of the "
        f"weight tree, out of the component expectation E, and out of every coverage check, so those "
        f"checks cannot report a gap inside them. Confirm the patterns still describe code the map "
        f"is not meant to cover."
    ]
    if rep.unused:
        out.append(f"`.coyomap/.ignore` has {len(rep.unused)} pattern(s) that decided nothing on "
                   f"this tree: {', '.join(rep.unused)} — nothing removed (and for a `!` line, "
                   f"nothing put back). A typo, a tree that moved, or a path already covered by a "
                   f"built-in exclusion; either way it reads as coverage the author never got.")
    out.extend(_partly_mapped_disclosure(spec.patterns, mapped_sources))
    out.extend(bad_line_disclosure(rep.bad_lines))
    return out


def _pattern_prefix(pattern: str) -> str:
    """The path this pattern is ABOUT — everything up to its first wildcard, as a directory prefix.

    `frontend/src/**/*.test.ts` -> `frontend/src/`, `a/b` -> `a/b/`, `build` -> `build/`.

    Three shapes were wrong in the first version and each produced a false or missing report:
    `a/b` yielded `a/` (its PARENT), so the warning counted three elements under `a/c` and `a/d`
    that the pattern hides none of; `build` and `tests` yielded "" and were skipped silently, which
    is the common case of a whole tree being excluded; and a `!` line — which PUTS BACK rather than
    hides — produced a warning saying it hides something."""
    if pattern.lstrip().startswith("!"):
        return ""                      # a negation un-excludes; it hides nothing
    head = pattern.strip().lstrip("/").split("*", 1)[0].split("?", 1)[0].split("[", 1)[0]
    if not head:
        return ""                      # a bare wildcard says nothing about WHERE
    if not head.endswith("/"):
        # A trailing fragment is only a directory when the wildcard was cut mid-name
        # (`frontend/src/**` -> `frontend/src/`, but `a/b` -> `a/b/`). Cutting back to the parent
        # is what made the prefix over-broad, so keep the whole fixed part.
        head = head + "/" if head == pattern.strip().lstrip("/").rstrip("/") else head.rsplit(
            "/", 1)[0] + "/"
    return head if head != "/" else ""


def _partly_mapped_disclosure(patterns: Sequence[str], mapped_sources: Sequence[str]) -> list[str]:
    """A pattern that hides part of a tree the map DESCRIBES the rest of.

    An exclusion carries a reason, and the reason is usually about a KIND of code — "test trees are
    out of scope". The map is the thing that can refute it: on the 2026-09-02 mcpolis map the ignore
    file removed one test tree on exactly that reason while the map carried four test components
    from elsewhere. So the map says tests ARE in scope and the ignore file says they are not, and
    nothing put the two sentences side by side.

    Says only what it can prove: this prefix is both excluded and mapped. Whether that is right is
    the author's call — a vendored copy of a mapped library is a legitimate example — but it must be
    a decision rather than a thing nobody noticed."""
    if not mapped_sources:
        return []
    out: list[str] = []
    for pattern in patterns:
        prefix = _pattern_prefix(pattern)
        if not prefix:
            continue
        inside = [src for src in mapped_sources if src.startswith(prefix)]
        if inside:
            out.append(
                f"`.coyomap/.ignore` pattern {pattern!r} hides part of `{prefix}`, and the map "
                f"DESCRIBES {len(inside)} element(s) from that same tree. The exclusion's reason is "
                f"usually about a kind of code ('tests are out of scope'), and the map is what can "
                f"refute it — one live map excluded a test tree on that reason while carrying four "
                f"test components. Confirm the two agree, or narrow the pattern.")
    return out


def granularity_advisory(n_components: int, root: Path) -> list[str]:
    """Advisory (non-blocking, opt-in via --check-coverage): the map's COMPONENT (leaf) count vs the
    code-derived granularity expectation E — the leaf anchor (one component ≈ one ≤10-file/≤3-kLOC
    module-sized unit; see method.md). Fires only when the count sits OUTSIDE the generous ±40% band;
    silent within it. Like every coverage check it RE-COMPUTES E from the tree (shared code in
    `preindex_lib`, never the pre-index's JSON — GR4). Never checks the subsystem count — nesting is
    the builder's free output; only the leaf decision is anchored."""
    # Local import, same rule as the coverage check above: the core gate stays import-independent of
    # the pre-index module; this opt-in check reuses its CODE, never its generated DATA (GR4).
    from coyomap.preindex_lib import (
        GRANULARITY_BAND_PCT,
        GRANULARITY_FILE_CAP,
        GRANULARITY_LOC_CAP,
        expected_components,
        granularity_band,
    )

    if n_components <= 0:
        return []
    tree = expected_components(root.resolve())
    if tree.expected <= 0:
        return []  # no component-forming source measured — nothing to anchor against
    lo, hi = granularity_band(tree.expected)
    if lo <= n_components <= hi:
        return []
    if n_components < lo:
        hint = ("possibly folding subsystem-shaped dirs into single components — consider promoting "
                "them to subsystems")
    else:
        hint = "possibly splitting module-sized units too fine — consider merging cohesive siblings"
    return [
        f"Granularity: {n_components} components vs a code-derived ~{tree.expected} "
        f"(band {lo}–{hi} at ±{GRANULARITY_BAND_PCT:.0%}; a component ≈ ≤{GRANULARITY_FILE_CAP} files / "
        f"≤{GRANULARITY_LOC_CAP} LOC) — {hint}. This is a rough zoom anchor, NOT a verdict: a "
        f"deliberately high-altitude map of a large repo, or a very modular clean-architecture repo, "
        f"legitimately sits outside the band — ignore if the chosen altitude is intentional."
    ]


# A `Where` / anchor cell is a SOURCE LOCATION (the call site a flow arrow opens): a file ref with an
# optional `:line`/`:line-line` (extension optional — `Dockerfile:1` is valid), shared from
# `coyomap.anchors` so format lives in one place. A markdown link is not a valid `Where`/anchor shape —
# `_check_anchor_format` (validate_model.py) rejects it rather than this function extracting its href.
# `strip_anchor` / `_LINE_ANCHOR` live in `coyomap.anchors` (one anchor home); re-exported here so the
# existing `from coyomap.validate_analysis import strip_anchor` importers keep working.
_LINE_ANCHOR = LINE_ANCHOR


def _where_href(cell: str) -> str | None:
    """The file location a `Where` / anchor cell points to: the cell itself when it is a bare
    `path.ext[:line]` token. None for an empty / prose / non-anchor-shaped cell."""
    cell = cell.strip()
    if not cell:
        return None
    return cell if _BARE_PATH.match(cell) else None


def _source_roots(map_path: Path, repo_root: Path | None = None) -> list[Path]:
    """The roots a map's SOURCE / anchor paths resolve against. By default the map's own dir and its
    parent (the repo root for a `.coyomap/` map). An explicit `repo_root` (the `--repo` flag) is tried
    FIRST — a map validated from outside its repo (e.g. an eval's deep run dir) resolves its
    repo-root-relative anchors against the real tree; the map-derived roots stay as fallback so
    in-repo behavior is unchanged. Shared by every repo-reading check so this resolution rule lives in
    one place."""
    base = map_path.resolve().parent
    roots = [base, base.parent]
    if repo_root is not None:
        roots.insert(0, repo_root.resolve())
    return roots


def _resolve_source_file(source: str, roots: list[Path]) -> Path | None:
    """The real file a card's SOURCE points at — its line anchor stripped, resolved against
    `roots`. None when it doesn't resolve (a placeholder, or a run outside the repo), so a repo-reading
    check skips it instead of false-flagging."""
    rel = strip_anchor(source)
    return next((r / rel for r in roots if (r / rel).is_file()), None)


# NON-ENTITY types the under-harvest count must exclude (V2): infrastructure / plumbing classes that
# legitimately live in a domain dir but are not domain entities, so no entity card should represent
# them. Matched by NAME SUFFIX (a `UserRepository` is persistence machinery, not a second User) and by
# BASE (an `ABC` / `Protocol` subclass is an interface contract, not a stored thing). Without this
# filter a repository/provider-heavy domain dir reads as "62 unmodelled types" when the model is fine.
_NON_ENTITY_SUFFIXES = ("Repository", "Store", "Provider", "Protocol", "Error", "Exception",
                        "Middleware")
_NON_ENTITY_BASES = frozenset({"ABC", "Protocol"})


def _base_name(base: ast.expr) -> str | None:
    """The bare class name of a base expression: `ABC` -> 'ABC', `abc.ABC` -> 'ABC',
    `Protocol[T]` -> 'Protocol'. None for anything else (a call, a computed base)."""
    if isinstance(base, ast.Subscript):  # Protocol[T] / Generic[T] — look at the subscripted name
        base = base.value
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


def _is_non_entity_type(node: ast.ClassDef) -> bool:
    """True for a class the domain-coverage count should skip: a plumbing suffix in its name, or an
    `ABC` / `Protocol` base (an abstract contract is not an entity)."""
    if node.name.endswith(_NON_ENTITY_SUFFIXES):
        return True
    return any(_base_name(b) in _NON_ENTITY_BASES for b in node.bases)


def _type_covered(type_name: str, entity_names: list[str]) -> bool:
    """True if a code type is represented by some entity card — the same lenient, case-insensitive
    substring match the entity-sources check uses to ground an entity in its file, run in reverse: an
    entity's identifier token appears in the type name, or the type name appears in the entity name.
    Tolerant on purpose (an abbreviated / compound / suffixed card name still counts as covering)."""
    t = type_name.lower()
    for name in entity_names:
        low = name.lower()
        if t in low or low in t:
            return True
        if any(tok.lower() in t for tok in re.findall(r"[A-Za-z_]\w{2,}", name)):
            return True
    return False


# Domain-model coverage thresholds (advisory). Calibrated against the two real mcpolis runs so the
# thin-domain regression (the new run: 8/33 entities isolated, 62/103 source-dir types unmodelled)
# warns while the richer run (6/37 isolated) stays quiet — see method retrospective. They are not a
# blocking gate; intentional abstraction is allowed (GR6), so an over-trip is a nudge, never a failure.
_ISOLATED_FRACTION = 0.20  # warn when MORE than this share of entity cards have zero E↔E relations
_ISOLATED_MIN = 3          # …and at least this many are isolated (floor — quiets tiny/young models)
_ISOLATED_MIN_ENTITIES = 5  # …and the model has at least this many entities at all
_UNCOVERED_FRACTION = 0.40  # warn when AT LEAST this share of source-dir types have no entity card
_UNCOVERED_MIN = 10         # …and at least this many are uncovered (floor — a strong signal only)
_COVERAGE_SAMPLE = 12       # cap the entity / type list in a warning so it stays readable
