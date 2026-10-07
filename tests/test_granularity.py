#!/usr/bin/env python3
"""Tests for the component-granularity expectation E — the leaf anchor.

Covers the shared computation in `coyomap.preindex_lib` (stop rule, flat-oversized rule,
exclusions, per-slice, determinism), the pre-index surfacing (`granularity` block in
preindex.json), the validate advisory (`granularity_advisory` — fires far outside E, silent
within band), and the docs (method.md carries the leaf rule; the harvest-prompt template
carries the per-slice E line).

Stdlib-only — no pytest required. Run either way (needs an editable install: `make deps`):
    python3 tests/test_granularity.py
    pytest tests/test_granularity.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from coyomap import preindex
from coyomap.preindex_lib import (
    GRANULARITY_BAND_PCT,
    GRANULARITY_FILE_CAP,
    GRANULARITY_LOC_CAP,
    expected_components,
    granularity_band,
    granularity_files,
    median_file_loc,
    slice_expectations,
)
from coyomap.validate_analysis import granularity_advisory

METHOD_MD = Path(__file__).resolve().parent.parent / "method.md"


# --- builders -------------------------------------------------------------------

def make_tree(files: dict[str, int]) -> Path:
    """Write a throwaway source tree: {repo-relative path: LOC}. Not a git repo — the walk
    falls back to os.walk with the same exclude rules, which is what these tests exercise."""
    root = Path(tempfile.mkdtemp(prefix="coyomap_granularity_"))
    for rel, loc in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n" * loc)
    return root


def make_plugin_tree(n_plugins: int, files_each: int = 3, loc_each: int = 100) -> Path:
    """The canonical subsystem-shaped tree: n small plugin dirs (each under the caps → one leaf
    each) plus a small core dir — E = n_plugins + 1."""
    files = {f"plugins/p{i}/f{j}.py": loc_each
             for i in range(n_plugins) for j in range(files_each)}
    files["core/a.py"] = 60
    files["core/b.py"] = 60
    return make_tree(files)


# --- the stop rule --------------------------------------------------------------

def test_e_small_repo_is_one_component() -> None:
    """A repo at/below the caps is component-shaped at the root — one leaf, no recursion."""
    root = make_tree({"pkg/a.py": 50, "pkg/b.py": 50, "top.py": 50})
    tree = expected_components(root)
    assert tree.expected == 1, tree
    assert tree.children == [], "a component-shaped root must not recurse"


def test_e_recurses_subsystem_shaped_tree() -> None:
    root = make_plugin_tree(6)
    tree = expected_components(root)
    assert tree.expected == 7, tree  # 6 plugins + core


def test_e_flat_oversized_dir_counts_ceil_by_files() -> None:
    """25 small files, no subdirs → ceil(25/10) = 3 cohesive groups, not one box."""
    root = make_tree({f"flat/f{i}.py": 10 for i in range(25)})
    assert expected_components(root).expected == 3


def test_e_flat_oversized_dir_counts_ceil_by_loc() -> None:
    """2 files but 7 kLOC, no subdirs → the LOC cap drives: ceil(7000/3000) = 3."""
    root = make_tree({"big/a.py": 3500, "big/b.py": 3500})
    assert expected_components(root).expected == 3


def test_e_pins_leaves_never_subsystem_count() -> None:
    """The same leaves under one extra grouping level yield the same E — nesting is free."""
    flat = make_plugin_tree(6)
    files = {f"backend/plugins/p{i}/f{j}.py": 100 for i in range(6) for j in range(3)}
    files["backend/core/a.py"] = 60
    files["backend/core/b.py"] = 60
    nested = make_tree(files)
    assert expected_components(flat).expected == expected_components(nested).expected


# --- exclusions -----------------------------------------------------------------

def test_e_excludes_vendored_docs_config_and_tests() -> None:
    """Vendored trees, docs/config text and conventional non-product dirs must not add
    components — E counts component-forming source only."""
    base = make_plugin_tree(6)
    inflated_files = {f"plugins/p{i}/f{j}.py": 100 for i in range(6) for j in range(3)}
    inflated_files.update({
        "core/a.py": 60, "core/b.py": 60,
        "node_modules/dep/index.js": 9000,          # vendored — walk-excluded
        "docs/guide.md": 9000,                      # docs — non-product dir
        "tests/t1.py": 9000,                        # test tree — non-product dir
        "config/settings.yaml": 9000,               # config text — not component-forming
        ".github/workflows/ci.yml": 500,
    })
    inflated = make_tree(inflated_files)
    assert expected_components(inflated).expected == expected_components(base).expected == 7


def test_e_and_the_median_count_one_file_set() -> None:
    """`granularity_files` is the one rule: E's file and LOC totals and the median file size are
    all counted over exactly its files."""
    root = make_tree({
        "src/a.py": 10, "src/b.ts": 30, "lib/c.go": 50,       # code
        "src/notes.md": 900, "src/conf.yaml": 900,            # docs and config text
        "src/Makefile": 900,                                   # no known language
        "src/assets/icon.ts": 900,                             # an asset folder
        "lib/internal/y.py": 900,                              # a non-product folder below the top
        "tests/test_a.py": 900, "node_modules/m.js": 900,      # a test tree, a vendored tree
    })
    counted = sorted(f.relative_to(root.resolve()).as_posix() for f in granularity_files(root))
    assert counted == ["lib/c.go", "src/a.py", "src/b.ts"], counted
    tree = expected_components(root)
    assert (tree.files, tree.loc) == (3, 90), tree
    assert median_file_loc(root) == 30


def test_e_glue_only_subdir_is_not_a_leaf() -> None:
    """A package holding only a tiny __init__.py is packaging glue, not a unit."""
    files = {f"plugins/p{i}/f{j}.py": 100 for i in range(6) for j in range(3)}
    files["core/a.py"] = 60
    files["core/b.py"] = 60
    files["glue/__init__.py"] = 2
    root = make_tree(files)
    assert expected_components(root).expected == 7  # glue/ adds nothing


def test_e_real_residual_module_counts() -> None:
    """Loose files with real mass directly in a recursed dir form one residual unit."""
    files = {f"app/sub{i}/f{j}.py": 200 for i in range(2) for j in range(8)}  # 2 leaves
    base = expected_components(make_tree(dict(files))).expected
    files["app/core.py"] = 400  # a real loose module next to the subdirs
    with_residual = expected_components(make_tree(files)).expected
    assert (base, with_residual) == (2, 3), (base, with_residual)


# --- per-slice + determinism + band ----------------------------------------------

def test_e_per_slice_expectations() -> None:
    root = make_plugin_tree(6)
    slices = slice_expectations(expected_components(root))
    assert slices["."] == 7
    assert slices["plugins"] == 6
    assert slices["core"] == 1
    assert slices["plugins/p0"] == 1


def test_e_deterministic() -> None:
    root = make_plugin_tree(9)
    a = slice_expectations(expected_components(root))
    b = slice_expectations(expected_components(root))
    assert a == b


def test_band_is_generous_both_directions() -> None:
    assert granularity_band(100) == (60, 140)
    lo, hi = granularity_band(7)
    assert lo <= 5 and hi >= 9, (lo, hi)


# --- pre-index surfacing (builder-facing) -----------------------------------------

def test_preindex_json_carries_granularity_block() -> None:
    root = make_plugin_tree(6)
    out = root / ".coyomap" / "preindex.json"
    rc = preindex.main(["--root", str(root), "--out", str(out)])
    assert rc == 0
    doc = json.loads(out.read_text())
    g = doc["granularity"]
    assert g["expected_components"] == 7, g
    assert g["band"] == list(granularity_band(7)), g
    assert g["per_dir"]["plugins"] == 6, g
    assert g["file_cap"] == GRANULARITY_FILE_CAP and g["loc_cap"] == GRANULARITY_LOC_CAP
    assert g["band_pct"] == GRANULARITY_BAND_PCT


# --- the validate advisory (checker-facing, re-computed — GR4) --------------------

def test_advisory_fires_far_under_e() -> None:
    root = make_plugin_tree(9)  # E = 10
    ws = granularity_advisory(2, root)
    assert ws and "Granularity" in ws[0], ws
    assert "folding" in ws[0], ws[0]  # the under-direction hint


def test_advisory_fires_far_over_e() -> None:
    root = make_tree({"pkg/a.py": 100})  # E = 1
    ws = granularity_advisory(9, root)
    assert ws and "splitting" in ws[0], ws


def test_advisory_silent_within_band() -> None:
    root = make_plugin_tree(9)  # E = 10, band 6–14
    for n in (6, 10, 14):
        assert granularity_advisory(n, root) == [], n


def test_advisory_silent_with_no_components_or_no_source() -> None:
    assert granularity_advisory(0, make_plugin_tree(3)) == []
    empty = make_tree({"README.md": 100})  # no component-forming source → nothing to anchor
    assert granularity_advisory(5, empty) == []


def test_advisory_ignores_poisoned_preindex_json_gr4() -> None:
    """GR4 tripwire: a lying preindex.json in the tree must not change the advisory — the
    checker re-computes E from the tree, never reads the generated artifact."""
    root = make_plugin_tree(9)
    before = granularity_advisory(2, root)
    (root / ".coyomap").mkdir(exist_ok=True)
    (root / ".coyomap" / "preindex.json").write_text(
        json.dumps({"granularity": {"expected_components": 2, "LIE": "2 is fine"}}))
    after = granularity_advisory(2, root)
    assert before == after and after, (before, after)


# --- docs presence ----------------------------------------------------------------

def test_method_states_the_leaf_rule() -> None:
    text = METHOD_MD.read_text(encoding="utf-8")
    assert "Component granularity — the leaf rule" in text
    assert "±40% band" in text
    assert "leaf decision only" in text  # the anchor pins leaves, never the subsystem count


def test_harvest_prompt_carries_the_per_slice_expectation() -> None:
    # The harvest contract moved OUT of method.md into method/templates/, so agents copy a file
    # instead of retyping prose. This guard follows it: the E placeholder must survive the move, in
    # whichever of the two documents now carries the prompt skeleton.
    method = METHOD_MD.read_text(encoding="utf-8")
    templates = "".join(p.read_text(encoding="utf-8")
                        for p in sorted((METHOD_MD.parent / "method" / "templates").glob("*.md")))
    text = method + templates
    # The slot NAME and the pointer are checked apart, because they are now two things. The slot
    # used to BE the sentence — `«the slice's E from the pre-index `granularity.per_dir`»` — and a
    # key nobody can type gets filled by position instead, silently: all four brief generators on
    # the 2026-09-01 argus build bound their slots positionally, across 51 of 55 briefs. So the key
    # is a bare token and the explanation sits beside it, where the lead still reads it.
    assert "«EXPECTED_COMPONENTS»" in text
    assert "the slice's E from the pre-index `granularity.per_dir`" in text
    # …and the unified under-delivery guidance points at the same E, not the old rough ratios
    assert "judge each return against its E" in text
    assert "1 component per 3–5 kLOC" not in text  # the pre-anchor heuristic was unified away


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception as e:  # noqa: BLE001 — test runner reports every failure
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
