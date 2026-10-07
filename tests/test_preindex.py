#!/usr/bin/env python3
"""Tests for the structural pre-index (coyomap.preindex + coyomap.preindex_lib).

Stdlib-only — no pytest required. Run either way (needs an editable install: `make deps`):
    python3 tests/test_preindex.py
    pytest tests/test_preindex.py

Non-Python symbol tests are gated on the tree-sitter grammar pack being installed
(the `preindex` extra); they assert graceful self-reported coverage (GR3) when it is absent.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from coyomap import buildstate, preindex, preindex_lib, validate_analysis  # tool #4: compression-coverage check
from coyomap.ignorefile import bad_line_disclosure
from coyomap.validate_analysis import _REF_INLINE, _REF_LINK, strip_anchor


# --- builders -------------------------------------------------------------------
def refs_from_markdown(text: str, root: Path) -> set[str]:
    """Repo-relative paths (files AND dirs) a markdown snippet points at — markdown link targets +
    inline paths, kept only when they actually exist under root. Mirrors what the retired v1 map
    reader used to hand `check_compression_coverage`; `compression_coverage_from_refs` is the real
    (kept) entry point, so tests build the ref set directly instead of parsing markdown for it."""
    cands: set[str] = set(_REF_LINK.findall(text)) | set(_REF_INLINE.findall(text))
    rootstr = str(root)
    refs: set[str] = set()
    for c in cands:
        c = strip_anchor(c.strip())
        if c.startswith("file://"):
            c = c[7:]
        if c.startswith(rootstr):
            c = c[len(rootstr):]
        c = c.strip("/")
        if c and not c.startswith(".coyomap") and (root / c).exists():
            refs.add(c)
    return refs


def check_compression_coverage(text: str, root: Path) -> list[str]:
    root = root.resolve()
    return validate_analysis.compression_coverage_from_refs(refs_from_markdown(text, root), root)



def make_temp_repo(files: dict[str, str], git: bool = True) -> Path:
    """Write a throwaway tree; optionally make it a git repo with one commit."""
    root = Path(tempfile.mkdtemp(prefix="coyomap_preindex_"))
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    if git:
        env = ["-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(root), *env, "commit", "-q", "-m", "init"], check=True)
    return root


def find_node(tree: dict, path: str) -> dict | None:
    """Locate a directory node by its repo-relative path in the weight tree."""
    if tree["path"] == path:
        return tree
    for child in tree["children"]:
        hit = find_node(child, path)
        if hit is not None:
            return hit
    return None


def weight_of(root: Path, git: bool = False):
    walk = preindex_lib.iter_source_files(root)
    churn, _ = preindex_lib.git_churn(root, None) if git else ({}, False)
    return preindex.build_weight(walk.files, root, churn, None)


# --- tool #1: weight + churn ----------------------------------------------------
def test_weight_counts_loc_and_files() -> None:
    root = make_temp_repo({"a.py": "x\ny\nz\n", "sub/b.py": "1\n2\n"}, git=False)
    tree, langs = weight_of(root)
    assert tree["loc"] == 5, tree["loc"]
    assert tree["file_count"] == 2, tree["file_count"]
    sub = find_node(tree, "sub")
    assert sub is not None and sub["loc"] == 2, sub
    assert langs.get("python") == 2, langs


def test_weight_excludes_vendored_and_lockfiles() -> None:
    root = make_temp_repo({
        "app.py": "a\n",
        "node_modules/dep/index.js": "junk\n" * 100,
        "package-lock.json": "{}\n" * 100,
    }, git=False)
    tree, _ = weight_of(root)
    assert tree["file_count"] == 1, tree["file_count"]  # only app.py
    assert find_node(tree, "node_modules") is None


def test_weight_churn_unavailable_without_git() -> None:
    root = make_temp_repo({"a.py": "x\n"}, git=False)
    churn, ok = preindex_lib.git_churn(root, None)
    assert ok is False and churn == {}, (ok, churn)


def test_weight_collapsed_plugins_are_visible() -> None:
    """The MEE6 regression in miniature: a plugins/ dir with 8 sibling subunits must show
    as 8 children with real LOC — the mass the collapsed map hid."""
    files = {f"plugins/p{i}/feature.py": f"# plugin {i}\n" + "line\n" * (i + 2)
             for i in range(8)}
    root = make_temp_repo(files, git=False)
    tree, _ = weight_of(root)
    plugins = find_node(tree, "plugins")
    assert plugins is not None, "plugins node missing"
    assert len(plugins["children"]) == 8, len(plugins["children"])
    assert all(c["loc"] > 0 for c in plugins["children"])


# --- tool #3: symbols -----------------------------------------------------------
def test_symbols_all_matches_for_ambiguous_name() -> None:
    root = make_temp_repo({
        "levels/player.py": "class Player:\n    pass\n",
        "economy/player.py": "class Player:\n    pass\n",
    }, git=False)
    walk = preindex_lib.iter_source_files(root)
    syms, _ = preindex.build_symbols(walk.files, root)
    assert len(syms["by_name"]["Player"]) == 2, syms["by_name"]["Player"]
    assert "Player" in syms["ambiguous"]


def test_symbols_kind_and_line() -> None:
    root = make_temp_repo({"m.py": "def foo():\n    pass\n\nclass Bar:\n    pass\n"}, git=False)
    walk = preindex_lib.iter_source_files(root)
    syms, _ = preindex.build_symbols(walk.files, root)
    foo = syms["by_name"]["foo"][0]
    bar = syms["by_name"]["Bar"][0]
    assert foo["kind"] == "function" and foo["line"] == 1, foo
    assert bar["kind"] == "class" and bar["line"] == 4, bar


def test_symbols_parse_failure_recorded_not_silent() -> None:
    root = make_temp_repo({"ok.py": "class Ok:\n    pass\n", "broken.py": "def (:\n"}, git=False)
    walk = preindex_lib.iter_source_files(root)
    syms, meta = preindex.build_symbols(walk.files, root)
    assert "Ok" in syms["by_name"]                      # the good file still parsed
    failed = [f["file"] for f in meta["parse_failures"]]
    assert any(f.endswith("broken.py") for f in failed), meta["parse_failures"]


# --- tool #2: import-edge advisory ----------------------------------------------
def test_imports_reports_named_pair_edge() -> None:
    root = make_temp_repo({
        "pkga/mod.py": "from pkgb import thing\n",
        "pkgb/thing.py": "x = 1\n",
    }, git=False)
    pairs = root / "pairs.json"
    pairs.write_text(json.dumps({"CA": ["pkga"], "CB": ["pkgb"]}))
    walk = preindex_lib.iter_source_files(root)
    imps, _ = preindex.build_imports(walk.files, root, str(pairs))
    edges = [p for p in imps["pairs"] if p["from"] == "CA" and p["to"] == "CB"]
    assert edges and edges[0]["count"] >= 1, imps["pairs"]


def test_imports_dynamic_not_captured_lower_bound() -> None:
    root = make_temp_repo({
        "pkgc/d.py": "__import__('pkgd')\n",
        "pkgd/x.py": "y = 1\n",
    }, git=False)
    pairs = root / "pairs.json"
    pairs.write_text(json.dumps({"CC": ["pkgc"], "CD": ["pkgd"]}))
    walk = preindex_lib.iter_source_files(root)
    imps, _ = preindex.build_imports(walk.files, root, str(pairs))
    dyn = [p for p in imps["pairs"] if p["from"] == "CC" and p["to"] == "CD"]
    assert not dyn, "dynamic __import__ must NOT surface as a static edge (lower-bound)"


# --- GR3: self-reported coverage ------------------------------------------------
def test_coverage_reports_language_without_symbol_extractor() -> None:
    root = make_temp_repo({"a.py": "x\n", "notes.txt": "hello\n"}, git=False)
    walk = preindex_lib.iter_source_files(root)
    _, meta = preindex.build_symbols(walk.files, root)
    assert "text" in meta["languages_seen_without_extractor"], meta


def test_full_run_emits_coverage_block() -> None:
    root = make_temp_repo({"a.py": "class A:\n    pass\n"}, git=True)
    out = root / ".coyomap" / "preindex.json"
    walk = preindex_lib.iter_source_files(root)
    churn, git_ok = preindex_lib.git_churn(root, None)
    weight, _ = preindex.build_weight(walk.files, root, churn, None)
    symbols, sym_meta = preindex.build_symbols(walk.files, root)
    imports, _ = preindex.build_imports(walk.files, root, None)
    doc = {"weight": weight, "symbols": symbols, "imports": imports,
           "coverage": {"git_available": git_ok,
                        "languages_with_symbols": sym_meta["languages_with_symbols"]}}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc))
    loaded = json.loads(out.read_text())
    assert loaded["coverage"]["git_available"] is True
    assert "python" in loaded["coverage"]["languages_with_symbols"]


# --- non-Python (tree-sitter): present if installed, gracefully absent if not ----
def test_non_python_symbols_present_or_self_reported() -> None:
    root = make_temp_repo({"s.js": "class Foo {}\nfunction bar() {}\n"}, git=False)
    walk = preindex_lib.iter_source_files(root)
    syms, meta = preindex.build_symbols(walk.files, root)
    if preindex_lib.ts_available():
        assert "Foo" in syms["by_name"], "tree-sitter installed but JS symbols missing"
    else:
        # GR3: the gap is recorded (a parse failure for s.js), never a silent empty
        failed = [f["file"] for f in meta["parse_failures"]]
        assert any(f.endswith("s.js") for f in failed), meta["parse_failures"]


# --- tool #4: compression-coverage (validator check, re-measures the tree) -------
def make_plugin_repo(n_plugins: int, n_files_each: int = 2) -> Path:
    files = {"core.py": "x\n"}
    for i in range(n_plugins):
        for j in range(n_files_each):
            files[f"plugins/p{i}/f{j}.py"] = "x\n" * 5
    return make_temp_repo(files, git=False)


def test_compression_flags_collapsed_plugins() -> None:
    root = make_plugin_repo(12)
    collapsed = "| **C1** | Plugins | S1 | all ~12 plugins as one box | [plugins/](plugins/) | |\n"
    ws = check_compression_coverage(collapsed, root)
    comp = [w for w in ws if w.startswith("Compression") and "plugins/ holds" in w]
    assert comp, ws
    assert "12 subdirs, measured at validate time" in comp[0], comp[0]  # self-reported denominator


def test_compression_quiet_when_plugins_drilled() -> None:
    root = make_plugin_repo(12)
    drilled = "\n".join(
        f"| **C{i}** | P{i} | S1 | one plugin | [f](plugins/p{i}/f0.py) | |" for i in range(12)
    )
    ws = check_compression_coverage(drilled, root)
    plug = [w for w in ws if "plugins/ holds" in w]
    assert not plug, f"drilled plugins must not warn (GR6 — abstraction is a feature): {plug}"


def test_compression_is_advisory_only_returns_list() -> None:
    # never raises, never blocks — it returns warnings the validator appends to `warnings` (GR6).
    root = make_temp_repo({"a.py": "x\n"}, git=False)
    assert isinstance(check_compression_coverage("", root), list)


def test_validator_does_not_read_preindex_json_gr4() -> None:
    """GR4 tripwire: a poisoned preindex.json present in the tree must NOT change the check's output —
    the validator re-measures and never consumes the generated artifact."""
    root = make_plugin_repo(12)
    collapsed = "| **C1** | Plugins | S1 | one box | [plugins/](plugins/) | |\n"
    before = check_compression_coverage(collapsed, root)
    (root / ".coyomap").mkdir(exist_ok=True)
    (root / ".coyomap" / "preindex.json").write_text(
        json.dumps({"weight": {"path": ".", "children": []}, "LIE": "plugins fully drilled"})
    )
    after = check_compression_coverage(collapsed, root)
    assert before == after, "validator output changed when preindex.json present — GR4 violated"


def test_imports_no_false_positive_on_substring() -> None:
    """H1 regression: a module that merely shares a substring with a target path must NOT produce an
    edge — a lower-bound advisory has no false edges. `import scoreboard` ≠ a dep on `core/`."""
    root = make_temp_repo({
        "scoreui/view.py": "import scoreboard\n",
        "core/x.py": "y = 1\n",
        "scoreboard/s.py": "z = 1\n",
    }, git=False)
    pairs = root / "pairs.json"
    pairs.write_text(json.dumps({"ScoreUI": ["scoreui"], "Core": ["core"]}))
    walk = preindex_lib.iter_source_files(root)
    imps, _ = preindex.build_imports(walk.files, root, str(pairs))
    bogus = [p for p in imps["pairs"] if p["from"] == "ScoreUI" and p["to"] == "Core"]
    assert not bogus, f"substring 'core' in 'scoreboard' must not fabricate an edge: {bogus}"


def test_compression_flags_monorepo_layout() -> None:
    """M2: a fold one level deeper, under a recognized monorepo container root, is still caught."""
    files = {f"packages/app/plugins/p{i}/f.py": "x\n" * 3 for i in range(10)}
    files["packages/app/main.py"] = "x\n"
    root = make_temp_repo(files, git=False)
    m = "| **C1** | Plugins | S1 | one box | [plugins/](packages/app/plugins/) | |\n"
    ws = check_compression_coverage(m, root)
    assert any("packages/app/plugins/ holds" in w for w in ws), ws


def test_compression_skips_leaf_internals_under_ordinary_package() -> None:
    """GR6: deep subdirs of a single mapped component (NOT under a monorepo root) stay abstracted."""
    files = {f"mee6/plugins/achievements/sub{i}/f.py": "x\n" for i in range(10)}
    files["mee6/plugins/achievements/achievements.py"] = "x\n"
    root = make_temp_repo(files, git=False)
    m = "| **C1** | Achievements | S1 | one plugin | [a](mee6/plugins/achievements/achievements.py) | |\n"
    ws = check_compression_coverage(m, root)
    assert not any("achievements/ holds" in w for w in ws), ws


def test_compression_flags_small_unreferenced_fold() -> None:
    """M3: a small-but-fanned fold the map references nothing inside is still surfaced (not silent)."""
    files = {f"services/s{i}/main.py": "x\n" for i in range(10)}
    files["core/x.py"] = "x\n"
    root = make_temp_repo(files, git=False)
    m = "| **C1** | Core | S1 | x | [c](core/x.py) | |\n"  # references nothing under services/
    ws = check_compression_coverage(m, root)
    assert any("services/" in w and "subdirs" in w for w in ws), ws


def test_compression_skips_non_product_dirs() -> None:
    """Item 7: a conventional non-product tree (tests / internal / docs) the map never references must
    NOT trip the absent-module warning — they have their own completeness section / are deliberately
    unmapped — while a genuine unmapped PRODUCT module still surfaces."""
    files = {"core/x.py": "x\n"}
    for i in range(30):
        files[f"tests/t{i}.py"] = "x\n"       # large unreferenced test tree — must be skipped
        files[f"internal/i{i}.py"] = "x\n"    # deliberately-unmapped internal tree — must be skipped
        files[f"billing/b{i}.py"] = "x\n"     # a real unmapped product module — must still surface
    root = make_temp_repo(files, git=False)
    m = "| **C1** | Core | S1 | x | [c](core/x.py) | |\n"  # references only core/
    ws = check_compression_coverage(m, root)
    assert not any("tests/" in w for w in ws), ws
    assert not any("internal/" in w for w in ws), ws
    assert any("billing/" in w for w in ws), ws


# --- --report: WHICH pre-index does it read? ------------------------------------
# The method has build agents run the CLI from the coyomap clone, so the CWD is routinely not
# the analysed repo. `--report` used to read only `--in` (a CWD-relative default) while
# accepting-and-dropping `--root`, so it printed the CURRENT repo's pre-index under the other
# repo's name — right-looking output, wrong repo, no visible symptom.

def make_report_artifact(root: Path, marker: str, expected: int) -> Path:
    """A minimal but real-shaped `<root>/.coyomap/preindex.json`, tagged with a distinctive
    `root` marker and E so any report can be traced back to the file it actually read."""
    out = root / ".coyomap" / "preindex.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "tool": "coyomap preindex", "root": marker,
        "weight": {"path": ".", "loc": 1, "file_count": 1, "churn": 0,
                   "lang": "python", "children": []},
        "granularity": {"expected_components": expected, "band": [1, 2], "per_dir": {}},
        "symbols": {}, "coverage": {}}))
    return out


def run_preindex(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """Run `coyomap preindex` and return (exit code, everything it printed to stdout+stderr).
    Stdlib only and no pytest fixture (house style), so the redirect and the chdir are explicit
    and local; the chdir is always undone, since a leaked CWD would corrupt every later test."""
    buf = io.StringIO()
    here = Path.cwd()
    try:
        if cwd is not None:
            os.chdir(cwd)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = preindex.main(args)
    finally:
        os.chdir(here)
    return code, buf.getvalue()


def run_report(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """`run_preindex` for `--report`, which reads an existing pre-index and writes nothing."""
    return run_preindex(["--report", *args], cwd)


def test_report_root_reads_the_named_repos_preindex_not_the_cwds() -> None:
    """THE DEFECT. Run from repo A, `--report --root B` must report B. The hard case is a CWD
    that HAS its own pre-index, because then the wrong answer looks completely right."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        make_report_artifact(tmp / "other-repo", "/other-repo", 999)
        make_report_artifact(tmp / "cwd-repo", "/cwd-repo", 7)
        code, out = run_report(["--root", str(tmp / "other-repo")], cwd=tmp / "cwd-repo")
    assert code == 0, out
    assert "/other-repo" in out and "E=999" in out, out[:400]
    assert "/cwd-repo" not in out and "E=7" not in out, (
        "--report fell back to the CWD's pre-index while --root named another repo")


def test_report_in_wins_over_root() -> None:
    """Precedence: an explicit `--in` names the file outright, so it beats `--root`."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        named = make_report_artifact(tmp / "named-repo", "/named-repo", 3)
        make_report_artifact(tmp / "root-repo", "/root-repo", 999)
        code, out = run_report(["--in", str(named), "--root", str(tmp / "root-repo")])
    assert code == 0, out
    assert "/named-repo" in out and "E=3" in out, out[:400]
    assert "/root-repo" not in out and "E=999" not in out, out[:400]


def test_report_without_in_or_root_still_reads_the_cwd() -> None:
    """The fallback is unchanged: neither flag means `./.coyomap/preindex.json`, so every
    existing invocation from inside the analysed repo keeps working exactly as before."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        make_report_artifact(tmp / "cwd-repo", "/cwd-repo", 5)
        code, out = run_report([], cwd=tmp / "cwd-repo")
    assert code == 0, out
    assert "/cwd-repo" in out and "E=5" in out, out[:400]


def test_report_rejects_every_build_only_flag() -> None:
    """`--report` reads an artifact and writes nothing, so there is no honest reading of
    "report, but with --max-depth 3". Each build-only flag must ERROR and name itself —
    accepting-and-ignoring is the failure mode with no visible symptom."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        artifact = make_report_artifact(tmp / "repo", "/repo", 4)
        for flag, value in (("--out", str(tmp / "x.json")), ("--since", "HEAD~1"),
                            ("--pairs", str(tmp / "pairs.json")), ("--max-depth", "3")):
            code, out = run_report(["--in", str(artifact), flag, value])
            assert code != 0, f"{flag} was silently accepted by --report:\n{out}"
            assert flag in out, f"the error for {flag} does not name the flag:\n{out}"
            assert "BUILD" in out, f"the error for {flag} does not say it is a build flag:\n{out}"
            assert "WEIGHT TREE" not in out, f"{flag} errored but the report still ran:\n{out}"


def test_report_missing_preindex_names_the_path_it_looked_for() -> None:
    """A "no pre-index" error that does not say WHERE it looked is unactionable — and under
    `--root` the path is derived, so the user cannot infer it."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "empty-repo").mkdir()
        code, out = run_report(["--root", str(tmp / "empty-repo")])
    assert code == 2, out
    assert str(tmp / "empty-repo" / ".coyomap" / "preindex.json") in out, out


# --- the ignore file's unusable lines: the summary, the artifact, --report ---------
def make_ignore_repo(ignore: str) -> Path:
    """A git repo holding `src/a.py` and `junk/b.py`, whose `.coyomap/.ignore` holds `ignore`."""
    return make_temp_repo({"src/a.py": "def a():\n    return 1\n",
                           "junk/b.py": "def b():\n    return 2\n",
                           ".coyomap/.ignore": ignore})


def test_unusable_ignore_lines_are_named_by_the_summary_the_artifact_and_the_report() -> None:
    """A line that parses to nothing excludes nothing, although its author meant it to. The
    build's summary, the saved pre-index and `--report` (the read a build is told to use) each
    name it, in the sentence `validate` and `scope` print, beside the pattern that did work."""
    root = make_ignore_repo("junk/\ninternal/  # private runbooks\n/\n")
    artifact = root / ".coyomap" / "preindex.json"
    said = bad_line_disclosure(("internal/  # private runbooks", "/"))[0]
    code, summary = run_preindex(["--root", str(root), "--out", str(artifact)])
    assert code == 0, summary
    assert said in summary
    cov = json.loads(artifact.read_text())["coverage"]
    assert cov["ignore_patterns"] == ["junk/ (removed 1 file(s))"]
    assert cov["ignore_lines_unusable"] == ["internal/  # private runbooks", "/"]
    code, report = run_report(["--in", str(artifact)])
    assert code == 0, report
    assert "junk/ (removed 1 file(s))" in report and said in report


def test_an_ignore_file_of_only_unusable_lines_is_still_named() -> None:
    """The worst case: no line is usable, so there is no pattern at all. Every place that first
    asked "any patterns?" said nothing about a file its author believes works."""
    root = make_ignore_repo("junk/  # the fixture\n")
    artifact = root / ".coyomap" / "preindex.json"
    said = bad_line_disclosure(("junk/  # the fixture",))[0]
    code, summary = run_preindex(["--root", str(root), "--out", str(artifact)])
    assert code == 0, summary
    assert said in summary
    cov = json.loads(artifact.read_text())["coverage"]
    assert cov["ignore_patterns"] == [] and cov["files_skipped_ignored"] == 0
    assert cov["ignore_lines_unusable"] == ["junk/  # the fixture"]
    code, report = run_report(["--in", str(artifact)])
    assert code == 0, report
    assert "IGNORED BY .coyomap/.ignore — 0 file(s), 0 pattern(s)" in report and said in report


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


# ── GR1, checked instead of only announced ───────────────────────────────────────────────────────

def make_repo_with_fragments(*names: str) -> Path:
    """A repo whose `.coyomap/build-fragments/` holds the named fragments."""
    root = Path(tempfile.mkdtemp())
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    frags = root / ".coyomap" / "build-fragments"
    frags.mkdir(parents=True)
    for n in names:
        body = ({"use_cases": [{"id": "UC1", "name": "Do it"}]}
                if "behavioral" in n else {"components": []})
        (frags / n).write_text(json.dumps(body), encoding="utf-8")
    return root


def test_gr1_reports_not_met_when_no_behavioral_draft_exists():
    """The NOTE has been printed on every run for as long as it has existed, and a live build read
    it and went straight into a 14-agent structural harvest; its behavioral fragment landed 79
    turns later. A printed rule nobody reads is fixed by checking it."""
    from coyomap.preindex import _gr1_status
    root = make_repo_with_fragments("ep-routes.json", "sec.json")
    status = _gr1_status(root, root / ".coyomap" / "preindex.json")
    assert "GR1 NOT MET" in status


def test_gr1_is_decided_by_content_not_by_filename():
    """`behavioral.json` is a habit, not a contract — the method names no such file. Keying on the
    name gives a false NOT MET to a build that called it something else, which teaches readers to
    ignore the warning, and is satisfied by an empty file."""
    from coyomap.preindex import _gr1_status
    root = make_repo_with_fragments("sec.json")
    frags = root / ".coyomap" / "build-fragments"
    (frags / "L1-usecases.json").write_text(
        json.dumps({"happy_path": [{"n": 1, "uc": "UC1", "text": "t"}]}), encoding="utf-8")
    assert "GR1 met" in _gr1_status(root, root / ".coyomap" / "preindex.json")
    (frags / "empty-behavioral.json").write_text("{}", encoding="utf-8")
    root2 = make_repo_with_fragments("behavioral.json")
    (root2 / ".coyomap" / "build-fragments" / "behavioral.json").write_text("{}", encoding="utf-8")
    assert "GR1 NOT MET" in _gr1_status(root2, root2 / ".coyomap" / "preindex.json")


def test_gr1_reports_met_when_the_behavioral_fragment_is_present():
    from coyomap.preindex import _gr1_status
    root = make_repo_with_fragments("behavioral.json", "sec.json")
    status = _gr1_status(root, root / ".coyomap" / "preindex.json")
    assert "GR1 met" in status and "behavioral.json" in status


def test_gr1_reads_the_scanned_root_not_the_out_path():
    """`--out` is routinely pointed at a scratch path; keying off its parent reported
    "no build-fragments" for a repo holding 33 of them."""
    from coyomap.preindex import _gr1_status
    root = make_repo_with_fragments("behavioral.json")
    elsewhere = Path(tempfile.mkdtemp()) / "scratch" / "preindex.json"
    assert "GR1 met" in _gr1_status(root, elsewhere)


# ── the build state keeps E (round 1 of the context work, 2026-10-07) ────────────────────────────

def test_preindex_appends_E_and_its_band():
    """After a summary the number the lead read off this run is gone; `state show` sums the harvest
    briefs' budgets against the E this line keeps."""
    root = make_temp_repo({"a.py": "x = 1\n", "sub/b.py": "y = 2\n"}, git=False)
    buildstate.start(root)
    code, out = run_preindex(["--root", str(root)])
    gran = json.loads((root / ".coyomap" / "preindex.json").read_text())["granularity"]
    log = buildstate.state_path(root).read_text(encoding="utf-8").splitlines()
    state = buildstate.read_state(root)
    assert code == 0, out
    budget = [line for line in log if " budget   " in line]
    assert len(budget) == 1, log
    assert budget[0].endswith(f"E {gran['expected_components']} · band {gran['band'][0]}-"
                              f"{gran['band'][1]} · bound by {gran['bound_by']}"), budget[0]
    assert state is not None
    view = "\n".join(buildstate.show_lines(state, root, root))
    assert f"preindex E {gran['expected_components']} · band" in view, view
