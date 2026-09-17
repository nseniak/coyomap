#!/usr/bin/env python3
"""Package-wide CLI honesty contracts, generalised from defects this project actually shipped.

Every check here is a CLASS, not an instance. Each was written after a specific bug slipped a
per-command test, so the guard is applied to every command at once — the same reason
`tests/test_method_contract.py` audits the prose↔tool seam in bulk rather than one flag at a time.

Run either way: `python3 tests/test_cli_contract.py` or `pytest tests/test_cli_contract.py`.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: command name -> implementing module, DERIVED from `cli.py`'s own USAGE. The first version of this
#: file hard-coded ten entries while its comment claimed exactly this derivation — and the three it
#: omitted included `preindex`, which was a live instance of the bug these contracts exist to catch.
#: A new command must join automatically or the contract is decoration.
COMMAND_MODULE: dict[str, str] = {
    "preindex": "preindex", "validate": "validate_model", "audit": "audit_model",
    "render": "viewer.render", "serve": "viewer.serve", "assemble": "assemble",
    "lint-fragment": "lint_fragment", "anchor-drift": "anchor_drift", "fix": "fix",
    "dump": "dump", "diff": "mapdiff", "reconcile": "reconcile_build",
    "changes": "changelog", "impact": "impact_cmd", "reanchor": "reanchor",
    "balance": "balance", "finalize": "finalize",
    "grounding": "grounding", "record": "record", "scope": "scope",
    "provenance": "provenance", "contract": "contract", "ship": "ship",
    "timings": "timings", "context": "context", "url": "viewer.url",
    "export": "viewer.export",
}


def make_cli_commands() -> tuple[str, ...]:
    """The command names `coyomap --help` advertises, read from USAGE itself."""
    from coyomap.cli import USAGE
    body = USAGE.split("Commands:", 1)[1].split("\nGlobal:", 1)[0]
    return tuple(ln.split()[0] for ln in body.splitlines()
                 if ln.startswith("  ") and ln.strip() and not ln.startswith("    "))


def test_the_command_table_covers_every_command_the_cli_advertises():
    """The guard on the guard. If this list drifts, every contract below silently stops covering
    whatever fell out — which is precisely how `preindex` was exempt while it was broken."""
    advertised = set(make_cli_commands())
    assert advertised == set(COMMAND_MODULE), (
        f"missing: {sorted(advertised - set(COMMAND_MODULE))}; "
        f"stale: {sorted(set(COMMAND_MODULE) - advertised)}")


#: Commands these probes may not CALL, with the reason. `serve` is a daemon: invoking its `main`
#: binds a port and blocks. Named explicitly and pinned by a test, because "exempt by omission" is the
#: exact failure that left `preindex` uncovered while it was broken.
UNPROBEABLE: dict[str, str] = {"serve": "a long-running HTTP daemon — calling main() binds a port"}


def test_the_unprobeable_list_stays_minimal_and_justified():
    """An exemption is a hole in every contract below it, so it needs a reason and a test."""
    assert set(UNPROBEABLE) <= set(COMMAND_MODULE)
    assert set(UNPROBEABLE) == {"serve"}, (
        "a new exemption was added — every command that can be called must be, or the contracts "
        f"stop covering it: {sorted(UNPROBEABLE)}")


def make_command_mains() -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for cmd in sorted(set(COMMAND_MODULE) - set(UNPROBEABLE)):
        mod = importlib.import_module(f"coyomap.{COMMAND_MODULE[cmd]}")
        if hasattr(mod, "main"):
            out.append((cmd, mod.main))
    return out


#: An absolute map path, so a probe's exit code reflects FLAG HANDLING and not the process CWD. With a
#: relative default, `audit`/`balance` only reached the offending code path when pytest happened to run
#: from the repo root — both production bugs went green from any other directory.
#:
#: The FROZEN copy, not `.coyomap/project-map.json`: a probe of flag handling has no business
#: reading a map another session may be rebuilding mid-run.
MAP = REPO_ROOT / "tests" / "fixtures" / "own-map" / "project-map.json"


def run_main(main, argv: list[str]) -> tuple[int, str]:
    """Call a command in-process, returning `(exit code, everything it printed)`."""
    out, err = io.StringIO(), io.StringIO()
    code: int = 2
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = int(main(argv) or 0)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 2)
    return code, out.getvalue() + err.getvalue()


def test_every_command_refuses_an_unknown_option():
    """A silently-ignored flag is a request the caller believes was honoured.

    `coyomap audit --jsonn` used to print the HUMAN report and exit 0, so a build asking for JSON got
    prose and had no way to notice the typo. `balance` did the same. Every other command already
    refused, which is exactly why a per-command test never caught these two."""
    assert MAP.is_file(), "coyomap's own map is the fixture for every probe here"
    offenders: list[str] = []
    for name, main in make_command_mains():
        code, _text = run_main(main, [str(MAP), "--definitely-not-a-real-flag"])
        if code == 0:
            offenders.append(name)
    assert not offenders, (
        "command(s) that accept an unknown option and exit 0, so a typo'd flag is undetectable: "
        + ", ".join(offenders))


def test_no_command_prints_an_error_and_then_claims_success():
    """The whole session's recurring failure, as a contract: output that says something went wrong
    while the exit status says nothing did. A caller reads one or the other, never both."""
    # The package reports failure in several vocabularies, not just `ERROR:` — `fix` and `cli` say
    # "unknown verb", `validate` says "VALIDATION FAILED", `assemble` "ASSEMBLY FAILED". Matching only
    # `ERROR` would have missed three of them.
    failed = re.compile(r"\bERROR\b|\bFAILED\b|unknown (?:option|verb|command|argument)",
                        re.IGNORECASE)
    liars: list[str] = []
    for name, main in make_command_mains():
        code, text = run_main(main, ["/nonexistent/path/to/a/map.json"])
        if code == 0 and failed.search(text):
            liars.append(f"{name} (missing file)")
    assert not liars, ("command(s) reporting a failure while exiting 0: " + ", ".join(liars))


#: The commands whose stdout is a MACHINE contract, with the argv that exercises it. An explicit
#: table, not a source-literal heuristic: the first version gated on `'"--json"' in src`, which
#: exempted `dump` — the one command whose entire stdout is JSON and therefore the most important
#: member — and silently dropped three more via a bare `except: continue`.
JSON_COMMANDS: dict[str, list[str]] = {
    "validate": ["--json"],
    "audit": ["--json"],
    "balance": ["--json"],
    "dump": [],                      # no flag: `dump`'s whole stdout IS the machine contract
    "anchor-drift": ["--map", "@MAP", "--repo", "@REPO", "--json"],
    "url": ["--map", "@MAP", "UC1", "--json"],   # the id is the positional; the map rides a flag
}


def test_every_machine_readable_command_emits_only_json_on_stdout():
    """`--json` is a contract with a program. A stray human line breaks `json.load` for the caller, and
    this project has already shipped a `--json` mode that leaked a truncated list into its own payload.

    Failures are COLLECTED, never skipped: an earlier version wrapped each call in
    `except Exception: continue`, so a total crash of `audit --json` — the payload the method tells
    Phase-4 builds to consume — left the test green."""
    assert MAP.is_file()
    broken: list[str] = []
    for cmd, extra in sorted(JSON_COMMANDS.items()):
        mod = importlib.import_module(f"coyomap.{COMMAND_MODULE[cmd]}")
        argv = [a.replace("@MAP", str(MAP)).replace("@REPO", str(REPO_ROOT)) for a in extra]
        if "@MAP" not in " ".join(extra):
            argv = [str(MAP), *argv]
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                mod.main(argv)
        except SystemExit:
            pass
        except Exception as e:                       # a crash is a FINDING, not a skip
            broken.append(f"{cmd}: raised {type(e).__name__}: {e}")
            continue
        text = out.getvalue().strip()
        if not text:
            broken.append(f"{cmd}: wrote nothing to stdout (stderr: {err.getvalue().strip()[:120]})")
            continue
        try:
            json.loads(text)
        except ValueError as e:
            broken.append(f"{cmd}: stdout is not parseable JSON — {e}")
    assert not broken, "machine-readable stdout is broken for:\n  " + "\n  ".join(broken)


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all CLI contract tests passed")


def _l2(map_path: Path):
    from coyomap.audit_model import l2_worklist_model
    from coyomap.model import load_model
    return l2_worklist_model(load_model(map_path.read_text(encoding='utf-8')))


def test_a_flag_advertised_as_repeatable_reads_every_occurrence():
    """`usage: … [--verdicts <f>]...` is a promise. A scalar rebind silently keeps only the LAST.

    `anchor-drift` bound `verdicts_path = argv[i]`, so a themed Phase-4 fan-out that passed its 13
    per-batch verdict files got a pass computed over the LAST file — 9% of the evidence — while
    `finalize` printed that the verdict-based drift leg had run. "The gate did not run" read exactly
    like "the gate passed", the single thing `finalize` exists to prevent, reintroduced through flag
    arity. `fix apply-drift` carried the identical bug, and fixing only one would have been worse
    than fixing neither: drift reported over the union, corrections written from one file.

    Driven through `main()` on purpose. An earlier version of this test called `load_verdicts`
    directly and stayed green with `main()`'s arity reverted to the scalar — it tested the helper,
    not the flag."""
    import json as _json
    import tempfile

    from coyomap import anchor_drift as ad
    from coyomap import fix as fx

    claims = [w.claim for w in _l2(MAP)]
    assert len(claims) >= 2, "need two claims to split across two files"
    with tempfile.TemporaryDirectory() as td:
        # `fix apply-drift` WRITES the map in place, so it must never be pointed at the repo's own
        # committed one. An earlier version of this test did exactly that and rewrote two security
        # anchors to `nowhere/at/all.py`, which `validate --check-sources` then failed on.
        target = Path(td) / "map.json"
        target.write_text(MAP.read_text(encoding="utf-8"), encoding="utf-8")
        a, b = Path(td) / "a.json", Path(td) / "b.json"
        a.write_text(_json.dumps({"grounding": [
            {"claim": claims[0], "grounded": True, "evidence": "nowhere/at/all.py:1"}]}))
        b.write_text(_json.dumps({"grounding": [
            {"claim": claims[1], "grounded": True, "evidence": "nowhere/at/all.py:2"}]}))
        for name, main, argv in (
            ("anchor-drift", ad.main,
             ["--map", str(target), "--verdicts", str(a), "--verdicts", str(b)]),
            ("fix apply-drift", fx.apply_drift,
             ["--map", str(target), "--verdicts", str(a), "--verdicts", str(b)]),
        ):
            code, text = run_main(main, argv)
            assert code == 0, f"{name} exited {code}"
            if name == "anchor-drift":
                # The coverage line counts BOTH files' claims, so it proves both were read.
                assert "challenged 2 of" in text, (
                    f"{name} read {text.splitlines()[0] if text else '(nothing)'} — a repeatable "
                    f"flag that keeps only the last occurrence")


# --- the shape that hides a swap (retro 2026-08-14) -----------------------------------------------
# `load_fragment_paths` returned two same-typed `list[str]`s positionally, and a caller took them the
# wrong way round: `notes` (advisory) was checked as fatal, `errors` (fatal) were dropped. That made a
# safety guard inert in the direction that loses data. NOTHING could catch it — same-typed slots
# type-check in any order, and the swap is invisible whenever both are empty, which is every test
# that builds clean input. Re-introducing it and running the whole suite: 1914 passed.
#
# The sharpened criterion, measured rather than assumed:
#   * `validate_model` returns `(problems, warnings)` — swapping it fails 210 tests. COVERED, because
#     the suite routinely asserts both lists NON-empty.
#   * `_duplicate_relations` returned `(same_card, reciprocal)` — swapping it passed all 1916. Both
#     are empty on a healthy map, so no clean fixture can tell them apart. NAMED, like the loader.
#
# So the risk is not "two same-typed slots"; it is "two same-typed slots that are BOTH EMPTY on the
# happy path". A static test cannot decide that, so this records the population instead: a NEW
# function of this shape has to be considered rather than merged by omission — which is the same
# reason `COMMAND_MODULE` above is pinned.

SAME_TYPED_COLLECTION_RETURNS: frozenset[str] = frozenset({
    # The `(problems, warnings)` convention — one uniform family, proven covered by the swap test.
    "tools/coyomap/validate_model.py::validate_model",
    "tools/coyomap/validate_model.py::_check_flows",
    "tools/coyomap/validate_model.py::check_rules_model",
    "tools/coyomap/validate_model.py::_check_dep_buckets",
    "tools/coyomap/validate_model.py::_check_messaging",
    "tools/coyomap/validate_model.py::_check_states",
    "tools/coyomap/validate_model.py::_check_group_tech",
    "tools/coyomap/validate_model.py::_check_edges",
    "tools/coyomap/validate_model.py::check_domain_relations",
    "tools/coyomap/validate_model.py::_check_domain_cards",
    "tools/coyomap/validate_model.py::_check_extra_conventions",
    "tools/coyomap/validate_model.py::_check_interfaces",
    "tools/coyomap/validate_analysis.py::check_hierarchy",
    # Pure builders with one call site each, consumed immediately at that site.
    "tools/coyomap/audit_model.py::_touch_sets",
    "tools/coyomap/preindex.py::build_symbols",
    "tools/coyomap/preindex.py::build_imports",
    "tools/coyomap/viewer/gen_viewer.py::_deployment_edges",
    "tools/coyomap/views.py::_component_headers",
    "tools/coyomap/views.py::_dep_headers",
})


_COLLECTION_TYPES = ("list", "dict", "set", "frozenset", "tuple")


def _slots_repeat_a_collection(types: list[str]) -> bool:
    import collections

    return any(n > 1 and t.split("[")[0] in _COLLECTION_TYPES
               for t, n in collections.Counter(types).items())


def _same_typed_collection_returns() -> set[str]:
    """Every function whose RETURN is two or more same-typed collection slots, positionally.

    Four escape routes were found by review and are all closed here, because a guard with a hole is
    worse than none — a reader trusts it. `async def` was skipped entirely; a module-level
    `X = tuple[list[str], list[str]]` alias hid the shape behind a Name; the key was the file's
    BASENAME, so two `views.py` in different packages collided into one entry; and — the ironic
    one — a `NamedTuple` with two same-typed collection fields passed, though a NamedTuple is
    positionally unpackable and is exactly what `assemble.FragmentLoad`'s docstring says not to use.
    """
    import ast

    found: set[str] = set()
    roots = [REPO_ROOT / "tools" / "coyomap", REPO_ROOT / "eval" / "tools"]
    for root in roots:
        for f in sorted(root.rglob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            key_prefix = f.relative_to(REPO_ROOT).as_posix()
            # Module-level `X = tuple[...]` aliases, so a return annotated with the alias is seen.
            aliases: dict[str, list[str]] = {}
            for node in tree.body:
                if (isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                        and isinstance(node.value, ast.Subscript)
                        and ast.unparse(node.value.value) == "tuple"):
                    sl = node.value.slice
                    aliases[node.targets[0].id] = [ast.unparse(e) for e in
                                                   (sl.elts if isinstance(sl, ast.Tuple) else [sl])]
            for node in ast.walk(tree):
                # A NamedTuple IS positionally unpackable — the shape this guard is about.
                if isinstance(node, ast.ClassDef) and any(
                        ast.unparse(b).split(".")[-1] == "NamedTuple" for b in node.bases):
                    fields = [ast.unparse(st.annotation) for st in node.body
                              if isinstance(st, ast.AnnAssign)]
                    if _slots_repeat_a_collection(fields):
                        found.add(f"{key_prefix}::{node.name}")
                    continue
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                r = node.returns
                if r is None:
                    continue
                if isinstance(r, ast.Name) and r.id in aliases:
                    types = aliases[r.id]
                elif isinstance(r, ast.Subscript) and ast.unparse(r.value) == "tuple":
                    types = [ast.unparse(e) for e in
                             (r.slice.elts if isinstance(r.slice, ast.Tuple) else [r.slice])]
                else:
                    continue
                if _slots_repeat_a_collection(types):
                    found.add(f"{key_prefix}::{node.name}")
    return found


def test_no_new_function_returns_two_same_typed_collections_unnamed():
    found = _same_typed_collection_returns()
    new = sorted(found - SAME_TYPED_COLLECTION_RETURNS)
    assert not new, (
        f"new function(s) returning two or more same-typed collection slots positionally: {new}. "
        f"If BOTH are empty on the happy path, no test can tell a swap from correct behaviour — "
        f"return a small named dataclass instead (see `assemble.FragmentLoad`). If one is normally "
        f"non-empty, the suite can cover it: prove that with a swap test, then add it to the list.")
    gone = sorted(SAME_TYPED_COLLECTION_RETURNS - found)
    assert not gone, f"listed but no longer of this shape (remove from the list): {gone}"


# --- the child process reads the SAME checkout as this one -------------------------------

def test_a_subprocess_test_reads_the_same_tools_this_run_reads() -> None:
    """Seventeen test files start a python CHILD, and only two hand it an environment of their own.
    The rest inherit `PYTHONPATH=tools` — a RELATIVE path — and most run the child with `cwd=` set to
    a fixture directory, where no `tools` exists. The import then falls through to the editable
    install, which points at whichever checkout was installed.

    In the main checkout the two agree and nothing shows. In a WORKTREE they do not, and a whole
    day's subprocess tests were green about code that was not under edit: `test_assembly_fixture`
    passed against a stale pinned fixture because the child was assembling with the OTHER checkout's
    model. It surfaced only at merge, after several honest-looking green runs.

    `conftest.py` re-anchors every relative `PYTHONPATH` entry on the repo root. This is the guard
    that says so out loud if that is ever undone — it reproduces the exact shape that hid the bug:
    a child started somewhere else entirely.
    """
    import subprocess
    root = Path(__file__).resolve().parent.parent
    elsewhere = root / "eval" / "fixtures" / "trapdoor"
    if not elsewhere.is_dir():                      # the fixture moved; any other dir proves it too
        elsewhere = root.parent
    child = subprocess.run(
        [sys.executable, "-c", "import coyomap, sys; sys.stdout.write(coyomap.__file__)"],
        cwd=elsewhere, capture_output=True, text=True)
    assert child.returncode == 0, f"the child could not import coyomap at all:\n{child.stderr}"
    import coyomap
    assert child.stdout.strip() == str(Path(coyomap.__file__).resolve()), (
        "a child process started outside the repo root reads a DIFFERENT coyomap than this test "
        f"run does.\n  this run: {coyomap.__file__}\n  the child: {child.stdout.strip()}\n"
        "Every subprocess test in the suite is then asserting against the wrong checkout. "
        "`conftest.py` makes PYTHONPATH absolute to prevent exactly this; check it is still there.")
