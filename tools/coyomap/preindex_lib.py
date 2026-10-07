#!/usr/bin/env python3
"""Shared helpers for the coyomap structural pre-index.

Two consumers, sharing CODE but never DATA (guardrail GR4 — generation != verification):
  - ``preindex.py`` runs the full walk + symbol/import extraction and writes
    ``.coyomap/preindex.json`` (the structural input the build agent reconciles).
  - ``validate_analysis.py`` reuses ONLY the walk/LOC helpers here for its
    compression-coverage check; it re-measures the tree itself and never reads the
    generated JSON. So the validator stays independent of the pre-index.

Language scope (a deliberate, scoped exception to the "Python side is stdlib-only" rule —
confined to the pre-index): the directory tree, LOC and git churn are language-agnostic and
need only stdlib + git. Symbols and imports are deep for Python via stdlib ``ast``; other
languages go through tree-sitter when the grammar pack is installed. When tree-sitter is
absent or a grammar is missing, the affected files are reported as uncovered (GR3) — never
silently counted as empty.
"""
from __future__ import annotations

import ast
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coyomap.ignorefile import IgnoreSpec, load_ignore

from coyomap.pysrc import parse_python

# --------------------------------------------------------------------------------------
# Language detection
# --------------------------------------------------------------------------------------

# extension (no dot, lowercased) -> language name (tree-sitter grammar name where applicable)
LANG_BY_EXT: dict[str, str] = {
    "py": "python", "pyi": "python",
    "js": "javascript", "jsx": "javascript", "mjs": "javascript", "cjs": "javascript",
    "ts": "typescript", "tsx": "tsx",
    "go": "go",
    "rs": "rust",
    "java": "java",
    "rb": "ruby",
    "ex": "elixir", "exs": "elixir",
    "c": "c", "h": "c",
    "cc": "cpp", "cpp": "cpp", "cxx": "cpp", "hpp": "cpp", "hh": "cpp",
    "cs": "c_sharp",
    "php": "php",
    "swift": "swift",
    "kt": "kotlin", "kts": "kotlin",
    "scala": "scala",
    "sh": "bash", "bash": "bash",
    # text-ish (counted for LOC/weight, no symbol extraction)
    "md": "markdown", "rst": "text", "txt": "text",
    "json": "json", "yaml": "yaml", "yml": "yaml", "toml": "toml",
    "html": "html", "css": "css", "scss": "css", "sql": "sql",
}

# Languages we extract symbols/imports for via tree-sitter (python is handled by ast).
TS_DEF_TYPES: dict[str, dict[str, str]] = {
    "javascript": {"class_declaration": "class", "function_declaration": "function",
                   "generator_function_declaration": "function", "method_definition": "method"},
    "typescript": {"class_declaration": "class", "abstract_class_declaration": "class",
                   "function_declaration": "function", "method_definition": "method",
                   "interface_declaration": "interface", "enum_declaration": "enum",
                   "type_alias_declaration": "type"},
    "go": {"function_declaration": "function", "method_declaration": "method",
           "type_spec": "type"},
    "rust": {"function_item": "function", "struct_item": "struct", "enum_item": "enum",
             "trait_item": "trait", "mod_item": "module"},
    "java": {"class_declaration": "class", "interface_declaration": "interface",
             "method_declaration": "method", "enum_declaration": "enum"},
    "ruby": {"class": "class", "module": "module", "method": "method",
             "singleton_method": "method"},
    "c": {"function_definition": "function", "struct_specifier": "struct"},
    "cpp": {"function_definition": "function", "class_specifier": "class",
            "struct_specifier": "struct"},
    "c_sharp": {"class_declaration": "class", "method_declaration": "method",
                "interface_declaration": "interface", "struct_declaration": "struct"},
    "php": {"class_declaration": "class", "function_definition": "function",
            "method_declaration": "method", "interface_declaration": "interface"},
}
# tsx shares typescript's node types
TS_DEF_TYPES["tsx"] = TS_DEF_TYPES["typescript"]

TS_IMPORT_TYPES: dict[str, set[str]] = {
    "javascript": {"import_statement"},
    "typescript": {"import_statement"},
    "tsx": {"import_statement"},
    "go": {"import_spec"},
    "rust": {"use_declaration"},
    "java": {"import_declaration"},
    "ruby": {"call"},  # require/require_relative — filtered to those names below
    "c": {"preproc_include"},
    "cpp": {"preproc_include"},
    "c_sharp": {"using_directive"},
    "php": {"namespace_use_declaration"},
}

# --------------------------------------------------------------------------------------
# Excludes (generated / vendored / lockfiles) — weight should reflect authored code
# --------------------------------------------------------------------------------------

DEFAULT_EXCLUDE_DIRS: set[str] = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "vendor", "third_party",
    "dist", "build", "out", "target", ".next", ".nuxt", ".svelte-kit",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache", ".pytest_cache",
    ".gradle", ".idea", ".vscode", "coverage", ".coyomap", ".coyomap-eval",
}
DEFAULT_EXCLUDE_SUFFIXES: tuple[str, ...] = (
    ".min.js", ".min.css", ".map", ".lock", ".lock.json",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".pdf", ".zip", ".gz", ".tar", ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".class", ".o", ".a",
)
DEFAULT_EXCLUDE_NAMES: set[str] = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock",
    "Cargo.lock", "composer.lock", "go.sum", ".DS_Store",
}

# Conventional NON-PRODUCT directory basenames: test trees have their own completeness section and
# `internal/`/`docs/`-style dirs are deliberately unmapped, so neither should count toward map-fidelity
# signals (coverage's absent-module warning, the granularity expectation E). Shared with
# `validate_analysis.compression_coverage_from_refs` — one list, one convention.
NON_PRODUCT_DIRS: frozenset[str] = frozenset({
    "tests", "test", "e2e", "internal", "docs", "__pycache__", "node_modules", ".git",
})

# ASSET trees — excluded from the granularity expectation E ONLY, never from the coverage checks.
# They hold no behavior to map, but a file-per-icon convention makes them huge by FILE COUNT, which
# is what drives E (a live monorepo: 679 of 5,007 granularity-counted files, 13.6%, moving E from
# 994 to 911). They are kept OUT of `NON_PRODUCT_DIRS` on purpose: that set also gates
# `validate_analysis`'s absent-module and file-level coverage checks, where excluding a dir means
# "never warn that this code is unmapped" — and real `.ts`/`.js` does live under `static/` and
# `locales/` in some repos. Sizing and coverage are different questions; they get different lists.
# Deliberately conservative: `public/` and `lang/` are in neither (too often real code).
GRANULARITY_ASSET_DIRS: frozenset[str] = frozenset({
    "assets", "icons", "img", "images", "fonts", "static", "locales", "translations",
})
GRANULARITY_SKIP_DIRS: frozenset[str] = NON_PRODUCT_DIRS | GRANULARITY_ASSET_DIRS


def lang_of(path: Path) -> str | None:
    return LANG_BY_EXT.get(path.suffix.lstrip(".").lower())


def _excluded(rel: Path) -> bool:
    if any(part in DEFAULT_EXCLUDE_DIRS for part in rel.parts):
        return True
    if rel.name in DEFAULT_EXCLUDE_NAMES:
        return True
    return rel.name.lower().endswith(DEFAULT_EXCLUDE_SUFFIXES)


@dataclass
class WalkResult:
    files: list[Path]            # absolute paths of counted source files
    root: Path
    used_git: bool               # True if the file set came from git (`_git_rels`) rather than a walk
    skipped_excluded: int        # files dropped by the exclude rules
    # `.coyomap/.ignore` — counted SEPARATELY from the built-in excludes on purpose. The built-ins
    # are conventions nobody chose; these are a repo's own declaration, and the one input that can
    # hide a real gap from the coverage check whose job is to find gaps. Callers report it.
    skipped_ignored: int = 0
    ignore: IgnoreSpec = field(default_factory=lambda: IgnoreSpec())
    # Per-rule DECIDING-match count, index-aligned with `ignore.rules`: how many files each pattern
    # actually removed (or, for a `!` rule, put back). The total alone cannot show a pattern that
    # matched nothing — and a dead pattern reads as coverage the author never got, so every
    # disclosing surface reports these through `ignorefile.ignore_report`.
    ignore_hits: tuple[int, ...] = ()


def _git_rels(root: Path) -> list[Path] | None:
    """Repo-relative paths git accounts for, or None when ``root`` is not a usable git repo.

    TRACKED **plus** UNTRACKED-not-ignored — the same two questions `impact_git.diff_changes`
    asks for a WORKTREE target, so building a map and analysing a change see one file set. Tracked
    alone was the older rule and it silently dropped a file the author had created but never
    `git add`-ed: invisible to the sizing and to the coverage checks (whose whole job is finding
    unmapped code), yet visible to `analyze` as an addition. Ignoring is left entirely to git via
    `--exclude-standard`, so every form of it holds — nested `.gitignore`, negations, the user's
    global excludes file, `.git/info/exclude` — with no second implementation to drift from it.

    Index entries are filtered to paths that EXIST: a file deleted from the working tree without
    the delete being staged is still listed by `ls-files`, and every caller here goes on to read
    the file.
    """
    def ls(*args: str) -> list[str] | None:
        try:
            out = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", *args],
                capture_output=True, text=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.split("\0") if out.returncode == 0 else None

    tracked = ls()
    if tracked is None:
        return None
    untracked = ls("--others", "--exclude-standard") or []
    seen: set[str] = set()
    rels: list[Path] = []
    for p in [*tracked, *untracked]:
        if p and p not in seen:
            seen.add(p)
            if (root / p).is_file():
                rels.append(Path(p))
    return rels or None


def iter_source_files(root: Path) -> WalkResult:
    """Enumerate authored source files under ``root``.

    Prefers git (see ``_git_rels``: tracked + untracked, minus everything git ignores, so
    generated output never inflates weight); falls back to an ``os.walk`` with the default
    exclude list when ``root`` is not a git repo — that mode cannot honor `.gitignore`, since
    there is no git to ask. The exclude rules apply in both modes, so the file set is the same
    shape either way.
    """
    root = root.resolve()
    rels = _git_rels(root)
    used_git = rels is not None
    if rels is None:
        rels = _walk_rels(root)

    ignore = load_ignore(root)
    files: list[Path] = []
    skipped = 0
    ignored = 0
    # Per-rule tally, filled as we go. Kept HERE and not on the (frozen, process-CACHED) IgnoreSpec:
    # a counter living on the shared spec would accumulate across every walk in a session and report
    # numbers belonging to some other tree.
    hits = [0] * len(ignore.rules)
    for rel in rels:
        if _excluded(rel):
            skipped += 1
            continue
        # The repo's own declaration, applied last so it is always visible as its own count rather
        # than blended into the built-in excludes. The DECIDING rule (last match wins) is recorded,
        # so a pattern that never decides anything is detectable as unused.
        idx = ignore.match_index(rel.as_posix()) if ignore else None
        if idx is not None:
            hits[idx] += 1
            if not ignore.rules[idx][0]:   # a positive rule decided -> the file leaves the tree
                ignored += 1
                continue
        files.append(root / rel)
    return WalkResult(files=files, root=root, used_git=used_git, skipped_excluded=skipped,
                      skipped_ignored=ignored, ignore=ignore, ignore_hits=tuple(hits))


def _walk_rels(root: Path) -> list[Path]:
    import os
    rels: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS]
        for fn in filenames:
            abs_p = Path(dirpath) / fn
            try:
                rels.append(abs_p.relative_to(root))
            except ValueError:
                continue
    return rels


def count_loc(path: Path) -> int:
    """Newline count of a text file; 0 for unreadable/binary files."""
    try:
        with path.open("rb") as fh:
            data = fh.read()
        if b"\0" in data[:4096]:  # crude binary guard
            return 0
        return data.count(b"\n")
    except OSError:
        return 0


def git_churn(root: Path, since: str | None) -> tuple[dict[str, int], bool]:
    """Map of repo-relative path -> number of commits touching it (optionally since a rev/date).

    One ``git log --numstat`` pass (not per-file ``--follow``), so cost is bounded by history
    length, not file count. Returns ({}, False) when ``root`` is not a git repo.
    """
    cmd = ["git", "-C", str(root), "log", "--numstat", "--format=%x00", "--no-renames"]
    if since:
        cmd.append(f"--since={since}")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return {}, False
    if out.returncode != 0:
        return {}, False
    churn: dict[str, int] = {}
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line or line == "\0" or line.startswith("\0"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        path = parts[2]
        churn[path] = churn.get(path, 0) + 1
    return churn, True


# --------------------------------------------------------------------------------------
# Symbols & imports
# --------------------------------------------------------------------------------------

@dataclass
class Symbol:
    name: str
    kind: str
    file: str   # repo-relative
    line: int
    end: int | None = None  # last line of the definition (extent), when the parser provides it


@dataclass
class ImportRef:
    file: str   # repo-relative
    line: int
    module: str  # raw imported module/path text (lower-bound matching uses substring)


def py_symbols(path: Path, rel: str) -> list[Symbol]:
    """Top-level + nested class/function definitions in a Python file, via stdlib ast."""
    try:
        tree = parse_python(path.read_text(encoding="utf-8", errors="replace"), str(path))
    except (OSError, SyntaxError, ValueError):
        raise
    out: list[Symbol] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            out.append(Symbol(node.name, "class", rel, node.lineno, node.end_lineno))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(Symbol(node.name, "function", rel, node.lineno, node.end_lineno))
    return out


def py_imports(path: Path, rel: str) -> list[ImportRef]:
    """Import targets in a Python file, via stdlib ast. Dynamic imports are NOT captured
    (they land nowhere) — that is the 'lower-bound' honesty of the advisory."""
    try:
        tree = parse_python(path.read_text(encoding="utf-8", errors="replace"), str(path))
    except (OSError, SyntaxError, ValueError):
        raise
    out: list[ImportRef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(ImportRef(rel, node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = ("." * (node.level or 0)) + (node.module or "")
            out.append(ImportRef(rel, node.lineno, mod))
    return out


# ---- tree-sitter path (optional; only loaded when needed) ----

_TS_PARSERS: dict[str, Any] = {}  # cached tree-sitter parsers (typed Any: no top-level ts import)
_TS_IMPORT_ERROR: str | None = None


def ts_available() -> bool:
    return _ts_get_parser("python") is not None or _try_import_ts()


def _try_import_ts() -> bool:
    global _TS_IMPORT_ERROR
    try:
        import tree_sitter_language_pack  # noqa: F401
        return True
    except Exception as exc:  # pragma: no cover - environment dependent
        _TS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        return False


def _ts_get_parser(lang: str) -> Any:
    # Build the parser the documented way (tree_sitter.Parser(get_language(...))). The pack's own
    # get_parser() returns an incompatible wrapper on some tree-sitter builds (root_node unusable),
    # so we go through get_language + the stdlib-style Parser, which is stable across 0.21–0.25.
    if lang in _TS_PARSERS:
        return _TS_PARSERS[lang]
    parser = None
    try:
        from tree_sitter import Parser
        from tree_sitter_language_pack import get_language
        parser = Parser(get_language(lang))
    except Exception:
        parser = None
    _TS_PARSERS[lang] = parser
    return parser


def _node_text(src: bytes, node) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _node_name(src: bytes, node) -> str | None:
    field = node.child_by_field_name("name")
    if field is not None:
        return _node_text(src, field)
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "field_identifier",
                           "constant", "name"):
            return _node_text(src, child)
    # C/C++: a function_definition's name is nested inside its declarator chain
    # (function_declarator -> identifier / qualified_identifier / field_identifier). Follow the
    # `declarator` field down; a qualified name (`Guild::rename`) is kept whole — the out-of-line
    # method body then gets its own symbol extent, distinct from the class declaration's.
    decl = node.child_by_field_name("declarator")
    seen = 0
    while decl is not None and seen < 8:
        if decl.type in ("identifier", "qualified_identifier", "field_identifier",
                         "operator_name", "destructor_name"):
            return _node_text(src, decl)
        nxt = decl.child_by_field_name("declarator")
        if nxt is None:
            for child in decl.children:
                if child.type in ("identifier", "qualified_identifier", "field_identifier"):
                    return _node_text(src, child)
            return None
        decl = nxt
        seen += 1
    return None


def ts_symbols(path: Path, rel: str, lang: str) -> list[Symbol]:
    """Class/function-like definitions for a non-Python language via tree-sitter.
    Raises if the parser/grammar is unavailable so the caller records it under coverage."""
    def_types = TS_DEF_TYPES.get(lang)
    if def_types is None:
        raise LookupError(f"no symbol extractor for language {lang!r}")
    parser = _ts_get_parser(lang)
    if parser is None:
        raise LookupError(f"tree-sitter grammar for {lang!r} unavailable")
    src = path.read_bytes()
    tree = parser.parse(src)
    out: list[Symbol] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        kind = def_types.get(node.type)
        if kind is not None:
            # C/C++ `struct_specifier`/`class_specifier`/`enum_specifier` nodes also appear at
            # type-REFERENCE sites (`struct point p`); only the defining occurrence has a body.
            # Without this, a reference site mints a bogus 1-line extent that innermost-extent
            # resolution can pick over the real enclosing function.
            if node.type.endswith("_specifier") and node.child_by_field_name("body") is None:
                stack.extend(node.children)
                continue
            name = _node_name(src, node)
            if name:
                out.append(Symbol(name, kind, rel, node.start_point[0] + 1,
                                  node.end_point[0] + 1))
        stack.extend(node.children)
    return out


def ts_imports(path: Path, rel: str, lang: str) -> list[ImportRef]:
    """Import statements for a non-Python language via tree-sitter (raw module text)."""
    imp_types = TS_IMPORT_TYPES.get(lang)
    if imp_types is None:
        raise LookupError(f"no import extractor for language {lang!r}")
    parser = _ts_get_parser(lang)
    if parser is None:
        raise LookupError(f"tree-sitter grammar for {lang!r} unavailable")
    src = path.read_bytes()
    tree = parser.parse(src)
    out: list[ImportRef] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in imp_types:
            text = _node_text(src, node).strip()
            if lang == "ruby":
                # only require / require_relative calls
                if not text.startswith(("require", "load")):
                    stack.extend(node.children)
                    continue
            out.append(ImportRef(rel, node.start_point[0] + 1, text))
        stack.extend(node.children)
    return out


def symbols_for(path: Path, rel: str, lang: str) -> list[Symbol]:
    """Dispatch to the right extractor. Raises on unsupported/failed parse (caller records it)."""
    if lang == "python":
        return py_symbols(path, rel)
    return ts_symbols(path, rel, lang)


def imports_for(path: Path, rel: str, lang: str) -> list[ImportRef]:
    if lang == "python":
        return py_imports(path, rel)
    return ts_imports(path, rel, lang)


SYMBOL_LANGS: set[str] = {"python", *TS_DEF_TYPES.keys()}


# --------------------------------------------------------------------------------------
# Component-granularity expectation E (the leaf anchor)
# --------------------------------------------------------------------------------------
# One component ≈ one module-/folder-/deployable-sized unit. E is the deterministic count of leaves
# an explicit stop rule yields on the code tree alone: recurse while a directory exceeds the
# component-size caps; at/below the caps it is component-shaped → one leaf; an oversized FLAT dir
# (no source subdirs) counts ceil(size/cap) — it should be split by cohesive file groups. E pins the
# LEAF decision only — how the leaves are grouped into subsystems (nesting) stays free.
#
# Two consumers, sharing CODE but never DATA (GR4): `preindex.py` SURFACES E (+ per-slice E) to the
# builder at generation time; `validate --check-coverage` and the eval profiler RE-COMPUTE it from
# the tree at check time — they never read the pre-index JSON.
#
# The caps are PRINCIPLED defaults (a component ≈ a ≤10-file / ≤3-kLOC cohesive unit is defensible
# on its own) — deliberately NOT calibrated to reproduce any observed map's count, which would bake
# one map's zoom in as truth. The ±40% band is generous on purpose: E anchors the ZOOM, it does not
# decree the exact number.
GRANULARITY_FILE_CAP = 10      # a component-shaped dir holds ≤ ~10 source files …
GRANULARITY_LOC_CAP = 3000     # … or ≤ ~3 kLOC of source
GRANULARITY_BAND_PCT = 0.40    # the generous advisory band around E (both directions)
# Loose files sitting directly in a recursed (subsystem-shaped) dir form one residual unit — but only
# when they are real code, not packaging glue (an `__init__.py` re-export must not add a component).
GRANULARITY_RESIDUAL_MIN_LOC = 40
# Languages that don't form components: docs and configuration describe the system, they aren't units
# of it. (Unknown extensions are skipped too — lang_of returns None.)
GRANULARITY_TEXT_LANGS: frozenset[str] = frozenset({"markdown", "text", "json", "yaml", "toml"})


@dataclass
class DirExpectation:
    """The granularity expectation of one directory subtree. `children` is non-empty only when the
    stop rule RECURSED here (the dir is subsystem-shaped); a component-shaped dir is a leaf."""
    path: str                          # repo-relative ("." for the root)
    files: int                         # recursive source-file count (granularity-counted files only)
    loc: int                           # recursive LOC of those files
    expected: int                      # E for this subtree
    children: list["DirExpectation"]


def granularity_files(root: Path) -> list[Path]:
    """The files E is counted from, as absolute paths in walk order: the pre-index's walk
    (`iter_source_files`) narrowed to code in a known language (no docs or config text, no unknown
    extension) with no test, docs, internal or asset folder at any depth above it.

    ONE rule, because three answers read it and must agree: E itself (`expected_components`), the
    median file size that explains a file-cap-bound E (`median_file_loc`), and the harvest slot check
    that names every such file no component-writing slice holds
    (`contract.sources_in_no_component_slice`). Each carried its own copy of these tests, and a copy
    that drifted would check the slices against a different file set than the E they were cut by."""
    walk = iter_source_files(root)
    out: list[Path] = []
    for f in walk.files:
        lang = lang_of(f)
        if lang is None or lang in GRANULARITY_TEXT_LANGS:
            continue
        if any(part in GRANULARITY_SKIP_DIRS for part in f.relative_to(walk.root).parts[:-1]):
            continue
        out.append(f)
    return out


def median_file_loc(root: Path) -> int:
    """Median LOC of the files E is computed over (`granularity_files`). The companion to
    `bound_by`: when the file cap binds AND the median file is small, E is counting many tiny files
    as if each were a unit's worth of mass — the signal that E is high for a structural reason, not
    because the repo really holds that many components."""
    sizes = sorted(count_loc(f) for f in granularity_files(root))
    return sizes[len(sizes) // 2] if sizes else 0


def _ceil_units(files: int, loc: int, file_cap: int, loc_cap: int) -> int:
    """The oversized-flat-group rule: how many cohesive units this much mass should split into —
    the larger of the two cap-relative ceilings, never less than one."""
    return max(1, -(-files // file_cap), -(-loc // loc_cap))


def expected_components(root: Path, *, file_cap: int = GRANULARITY_FILE_CAP,
                        loc_cap: int = GRANULARITY_LOC_CAP) -> DirExpectation:
    """Compute the component-granularity expectation E for a repo tree. Deterministic and derived
    from the code alone: the files are `granularity_files` (the pre-index's walk, narrowed to
    component-forming source: no docs/config text, no conventional non-product trees)."""
    root = root.resolve()
    # dir node: {"loc": direct LOC, "files": direct file count, "dirs": {name: node}}
    def new_node() -> dict:
        return {"loc": 0, "files": 0, "dirs": {}}
    tree = new_node()
    for f in granularity_files(root):
        rel = f.relative_to(root)
        node = tree
        for part in rel.parts[:-1]:
            node = node["dirs"].setdefault(part, new_node())
        node["files"] += 1
        node["loc"] += count_loc(f)

    def totals(node: dict) -> tuple[int, int]:
        tf, tl = node["files"], node["loc"]
        for sub in node["dirs"].values():
            sf, sl = totals(sub)
            tf += sf
            tl += sl
        return tf, tl

    def build(path: str, node: dict) -> DirExpectation:
        tf, tl = totals(node)
        if tf == 0:
            return DirExpectation(path, 0, 0, 0, [])
        if tf <= file_cap and tl <= loc_cap:
            return DirExpectation(path, tf, tl, 1, [])            # component-shaped → stop (leaf)
        # Glue-sized subdirs (a 2-LOC `__init__` package) are not units — fold their mass into the
        # dir's own residual instead of counting a leaf each.
        residual_files, residual_loc = node["files"], node["loc"]
        substantial: dict[str, dict] = {}
        for name, sub in node["dirs"].items():
            sf, sl = totals(sub)
            if sf == 0:
                continue
            if sl < GRANULARITY_RESIDUAL_MIN_LOC:
                residual_files += sf
                residual_loc += sl
            else:
                substantial[name] = sub
        if not substantial:                                       # oversized FLAT dir → ceil(size/cap)
            return DirExpectation(path, tf, tl, _ceil_units(tf, tl, file_cap, loc_cap), [])
        children = [build(name if path == "." else f"{path}/{name}", sub)
                    for name, sub in sorted(substantial.items())]  # subsystem-shaped → recurse
        e = sum(c.expected for c in children)
        if residual_files and residual_loc >= GRANULARITY_RESIDUAL_MIN_LOC:
            # the dir's own loose files are a real residual unit (or several, if oversized)
            if residual_files <= file_cap and residual_loc <= loc_cap:
                e += 1
            else:
                e += _ceil_units(residual_files, residual_loc, file_cap, loc_cap)
        return DirExpectation(path, tf, tl, e, children)

    return build(".", tree)


def granularity_band(expected: int, band_pct: float = GRANULARITY_BAND_PCT) -> tuple[int, int]:
    """The advisory band around E: (low, high), inclusive, at ±band_pct."""
    return math.floor(expected * (1 - band_pct)), math.ceil(expected * (1 + band_pct))


def slice_expectations(tree: DirExpectation) -> dict[str, int]:
    """`{repo-relative dir: E}` for the root plus every dir the stop rule visited (each recursed dir
    and each leaf) — the per-slice expectations the harvest plan hands its agents."""
    out = {tree.path: tree.expected}
    for c in tree.children:
        out.update(slice_expectations(c))
    return out
