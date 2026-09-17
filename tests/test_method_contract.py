#!/usr/bin/env python3
"""L1 — the prose<->tool contract, checked statically.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_method_contract.py
    pytest tests/test_method_contract.py

**Why this layer exists.** The 894 tests that came before it all assert what the code does WHEN
CALLED. A build agent reads only `method.md` and the `method/` docs, so a command the method
never names is unreachable no matter how well it is tested — `coyomap reconcile` shipped fully
working, fully tested, and ran ZERO times across four measured builds while every one of them
hand-wrote the file it generates (one was 24 KB, 139 rules, 882 id assignments). That is a
defect no unit test can see, because nothing is wrong with the unit.

So this file checks the SEAM, not the behaviour:

  (a) every command (and `fix` verb) the CLI offers is named somewhere in the method docs
  (b) every CLI flag the method tells a build to pass is accepted by that command
  (b2) …and is actually READ — not merely parsed and thrown away — by the code path that runs
       for that command form
  (c) every advisory the validator prints names a way to record the decision, or is allowlisted,
      and every escape a message NAMES is actually read by the check that prints it
  (d) every extras heading the method tells a lead to write is read by some tool

Pure text + AST. No fixture, no LLM, ~1 second. This is the cheapest layer and it would have
caught the worst defect in the study.

**What a static layer can and cannot prove.** Every assertion here is about the SHAPE of the
code — a literal in a parser, a call in a check, a name in a doc. That is enough to catch a
seam that was never wired, and it is NOT enough to catch a seam that is wired to the wrong
thing. Where the difference matters the claim is stated narrowly in the test's own docstring
and the behavioural half is named: `tests/test_trapdoor_tools.py` runs the real tools against a
real tree and is the layer that proves the wiring WORKS. A static test that oversold itself is
the same prose-vs-reality gap this layer exists to close, so the docstrings below say only what
they check.

**History.** Three of these tests failed when the layer landed; the failures were the
deliverable. All three findings have since been fixed in the CLI, the method docs and the
validator (`coyomap dump` / `reconcile` / `fix dedup-relation` are named in the method,
`preindex --report` honours `--root`, and the unowned-entity advisory carries a real escape),
so the suite is green and each test is now a standing regression gate on the fix.
"""
from __future__ import annotations

import ast
import tempfile
import json
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from coyomap import balance_lib

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS = REPO_ROOT / "tools" / "coyomap"

#: Every doc a build agent actually reads. `internal/` is explicitly NOT the method.
METHOD_DOCS: tuple[Path, ...] = (
    (REPO_ROOT / "method.md"),
    *sorted((REPO_ROOT / "method").glob("*.md")),
    (REPO_ROOT / "skill" / "coyomap" / "SKILL.md"),
)

#: command name -> the module implementing it, as `cli.py` dispatches.
COMMAND_MODULE: dict[str, str] = {
    "preindex": "preindex", "validate": "validate_model", "audit": "audit_model",
    "contract": "contract",
    "render": "viewer/render", "serve": "viewer/serve", "assemble": "assemble",
    "lint-fragment": "lint_fragment", "anchor-drift": "anchor_drift", "fix": "fix",
    "dump": "dump", "diff": "mapdiff", "reconcile": "reconcile_build",
    "changes": "changelog", "impact": "impact_cmd", "reanchor": "reanchor",
    "balance": "balance",
    "finalize": "finalize", "grounding": "grounding", "record": "record",
    "scope": "scope", "ship": "ship", "timings": "timings", "context": "context",
    "url": "viewer/url", "export": "viewer/export",
    # `provenance` was missing, and an unlisted command does not merely go unchecked: attribution
    # runs from one recognised command to the NEXT one, so every flag the method passes to an
    # unlisted command is charged to whichever listed command preceded it. The moment
    # `provenance stamp` was given `--mode` / `--update-header` in the closing-sequence block, both
    # were reported against `assemble` — a failure naming the wrong command and the wrong module.
    "provenance": "provenance",
}

#: The extras headings some tool actually READS (the escape tokens that silence an advisory).
#: Derived below from the source, never hard-coded into an assertion.
#: Every tool file that DECIDES an advisory and therefore may name an extras heading as its escape.
#: ONE list, because three separate scans below used to hand-write their own file tuple: `finalize.py`
#: was in none of them, and it shipped an advisory naming a heading whose key vocabulary could not
#: carry its key AND that nothing read. Twenty records were written against it on one live build and
#: every one was inert. A file added here joins all three checks at once.
ADVISORY_TOOL_FILES: tuple[str, ...] = (
    "validate_model.py", "balance_lib.py", "audit_model.py", "anchor_drift.py", "finalize.py",
)

MACHINE_READ_HEADINGS: tuple[str, ...] = (
    "audit exceptions", "balance exceptions", "coverage exceptions",
    "accepted duplications", "entry-point coverage", "happy path coverage",
    "audience exceptions", "stake exceptions",
    "persistence exceptions", "data owner exceptions", "decision area exceptions",
    "access baseline exceptions",
    "unclaimed surfaces", "drift exceptions", "interface exceptions",
    "bucket vocabulary", "sweep debt", "naming exceptions",
    "missing surfaces", "walk jumps",
)


# --- builders -------------------------------------------------------------------------

def make_method_text() -> str:
    """Every method doc concatenated — the whole surface a build agent can read."""
    return "\n".join(p.read_text(encoding="utf-8") for p in METHOD_DOCS if p.is_file())


def make_cli_commands() -> tuple[str, ...]:
    """The command names `coyomap --help` advertises, read from the USAGE text itself so a new
    command joins this test automatically."""
    from coyomap.cli import USAGE
    body = USAGE.split("Commands:", 1)[1].split("\nGlobal:", 1)[0]
    names: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^  ([a-z][a-z-]+)\s{2,}\S", line)
        if m:
            names.append(m.group(1))
    return tuple(names)


def make_fix_verbs() -> tuple[str, ...]:
    """The second-level verbs `coyomap fix` dispatches, read from its own verb table."""
    from coyomap.fix import _VERBS
    return tuple(sorted(_VERBS))


def make_doc_flag_pairs() -> tuple[tuple[str, str, str], ...]:
    """(command, flag, "doc:line") for every flag the method tells a build to PASS.

    Attribution is span-scoped, never proximity-scoped: a flag counts for a command only when
    both appear inside the SAME code span (a fenced block or one inline-code run). Proximity
    attribution mis-assigns `git status --porcelain` to whatever coyomap command was mentioned
    last, which is how a contract test starts reporting noise and stops being read."""
    cmd_pat = re.compile(r"coyomap\s+(" + "|".join(map(re.escape, COMMAND_MODULE)) + r")\b")
    span_pat = re.compile(r"```[a-z]*\n(.*?)```|`([^`]+)`", re.S)
    pairs: list[tuple[str, str, str]] = []
    for doc in METHOD_DOCS:
        if not doc.is_file():
            continue
        text = doc.read_text(encoding="utf-8")
        rel = doc.relative_to(REPO_ROOT).as_posix()
        for span in span_pat.finditer(text):
            body = (span.group(1) or span.group(2) or "").replace("\n", " ")
            line = text.count("\n", 0, span.start()) + 1
            hits = list(cmd_pat.finditer(body))
            for i, hit in enumerate(hits):
                tail = body[hit.end():hits[i + 1].start() if i + 1 < len(hits) else len(body)]
                for flag in re.findall(r"--[a-z][a-z0-9-]*", tail):
                    pairs.append((hit.group(1), flag, f"{rel}:{line}"))
    return tuple(sorted(set(pairs)))


def make_module_source(command: str) -> str:
    return (TOOLS / f"{COMMAND_MODULE[command]}.py").read_text(encoding="utf-8")


def make_code_flag_literals(command: str) -> frozenset[str]:
    """Every `--flag` literal that appears in EXECUTABLE code in a command's module.

    Deliberately not a text search over the file: every command module carries a `USAGE` string
    that spells out its whole flag vocabulary, so "the flag appears in the source" is satisfied by
    the help text alone — a flag that was documented and then never wired would pass. Counting
    only literals inside a function body is what makes the check about the parser."""
    src = make_module_source(command)
    found: set[str] = set()
    for fn in ast.walk(ast.parse(src)):
        if not isinstance(fn, ast.FunctionDef):
            continue
        found.update(n.value for n in ast.walk(fn)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)
                     and n.value.startswith("--"))
    return frozenset(found)


# --- the tools' own shape, shared by the flag audit and the escape audit ----------------

_BLOCKS = (ast.If, ast.For, ast.While, ast.With, ast.Try)

#: The one function that is a 200-line ORCHESTRATOR rather than a focused check. Escape wiring
#: found anywhere inside it belongs to some other rule, so an advisory it prints is credited only
#: with the wiring in its own enclosing block. Without this, deleting the escape a message
#: advertises would still "pass" against an unrelated escape 200 lines away.
ORCHESTRATOR = "validate_model"


@dataclass(frozen=True)
class ToolFunction:
    """One function defined in the tools: its source and the names it calls."""

    name: str
    src: str
    calls: frozenset[str]


def _src_of(node: ast.AST, src_lines: list[str]) -> str:
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", None) or start
    return "\n".join(src_lines[start - 1:end])


def _called_names(node: ast.AST) -> frozenset[str]:
    """Every name invoked under `node` — `f(...)` as `f`, `x.f(...)` as `f`."""
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                names.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                names.add(n.func.attr)
    return frozenset(names)


def make_tool_functions(*files: str) -> dict[str, ToolFunction]:
    """name -> the function's source and call targets, across the named tool modules.

    Keyed by bare name because the checks below follow calls the way a reader does (`_exceptions(m)`
    reads the same whether it was imported or defined here). The tools define no two functions
    under one name; a collision keeps the first and is a fixture bug, not a silent merge."""
    out: dict[str, ToolFunction] = {}
    for f in files:
        src = (TOOLS / f).read_text(encoding="utf-8")
        lines = src.splitlines()
        for fn in ast.walk(ast.parse(src)):
            if isinstance(fn, ast.FunctionDef) and fn.name not in out:
                out[fn.name] = ToolFunction(name=fn.name, src=_src_of(fn, lines),
                                            calls=_called_names(fn))
    return out


def make_dispatch_tables(src: str) -> dict[str, frozenset[str]]:
    """table name -> the tool functions it names as values.

    A producer reached through a module-level DISPATCH TABLE is not an `ast.Call` anywhere, so the
    call graph alone cannot see it. `_RUNS_IN_FAMILY` is the live case: it pairs each `runs-in`
    producer with a label, and one wrapper walks the table and applies the escape once — which is
    precisely the fix that made the suppression countable. Without this, every producer in such a
    table reads as "advertises a heading nothing reads"."""
    out: dict[str, set[str]] = {}
    for node in ast.parse(src).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if not names:
            continue
        referenced = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
        for name in names:
            out.setdefault(name, set()).update(referenced)
    return {k: frozenset(v) for k, v in out.items() if v}


def make_tool_callers(fns: dict[str, ToolFunction], tables: dict[str, frozenset[str]] | None = None
                      ) -> dict[str, frozenset[str]]:
    """callee name -> the functions that call it. The inverse of the call table above.

    A function that walks a dispatch table counts as a caller of every tool function that table
    names — otherwise table-driven wiring reads as no wiring at all."""
    out: dict[str, set[str]] = {}
    for fn in fns.values():
        for callee in fn.calls:
            out.setdefault(callee, set()).add(fn.name)
        for table, members in (tables or {}).items():
            if re.search(rf"\b{re.escape(table)}\b", fn.src):
                for member in members & fns.keys():
                    out.setdefault(member, set()).add(fn.name)
    return {k: frozenset(v) for k, v in out.items()}


def make_heading_constants() -> dict[str, str]:
    """Every `*_HEADING = "…"` constant the advisory tools define, by name.

    A heading reaches a message and a reader call through a constant as often as through a
    literal now (`MISSING_SURFACES_HEADING`, `WALK_JUMPS_HEADING`), and a scan that sees only
    literals filed both as unread and unadvertised — one of them while its advisory shipped
    with the escape the tools refused."""
    src = "\n".join((TOOLS / f).read_text(encoding="utf-8") for f in ADVISORY_TOOL_FILES)
    return dict(re.findall(r'([A-Z_]+_HEADING)\s*=\s*"([^"]+)"', src))


def _render_str(node: ast.AST) -> str:
    """The literal skeleton of a message expression — f-string holes become `{}`, except a
    hole that names a heading constant, which renders as that heading."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(_render_str(v) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        if isinstance(node.value, ast.Name) and node.value.id.endswith("_HEADING"):
            return make_heading_constants().get(node.value.id, "{}")
        return "{}"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _render_str(node.left) + _render_str(node.right)
    return ""


#: Names whose presence in a check's own source means SOME escape mechanism is wired to it,
#: even when the message text never mentions one.
_ESCAPE_MACHINERY = ("_exceptions(", "_recorded_ids(", "cov_dirs", "deployment_linked",
                     "_deployment_quality_warnings")


@dataclass(frozen=True)
class AdvisorySite:
    """One advisory the validator can PRINT, with everything the audits below need."""

    line: int
    function: str
    message: str
    #: some escape machinery is present in the check's own source (see `_ESCAPE_MACHINERY`).
    wired: bool
    #: The region that must hold the wiring for an escape this message NAMES. For a focused check
    #: that is the whole function; inside the ORCHESTRATOR it is the advisory's own enclosing
    #: block, so an unrelated escape elsewhere in the orchestrator cannot stand in for it.
    scope_src: str
    #: The names called inside `scope_src` — the roots of the transitive "does this read the
    #: heading?" walk.
    scope_calls: frozenset[str]


def make_advisory_sites() -> tuple[AdvisorySite, ...]:
    """Every advisory the validator can PRINT.

    An advisory is a string appended to a warnings list, or returned as the first element of a
    warning function's literal list. Read by AST rather than by regex so a reformatted call
    still counts. `wired` separates two different failures: a check with NO escape at all, and a
    check that HAS one whose message never tells the reader about it."""
    src = (TOOLS / "validate_model.py").read_text(encoding="utf-8")
    src_lines = src.splitlines()
    sites: list[AdvisorySite] = []
    for fn in ast.walk(ast.parse(src)):
        if not isinstance(fn, ast.FunctionDef):
            continue
        fn_src = _src_of(fn, src_lines)
        # `validate_model` is the 200-line ORCHESTRATOR, not a check: escape machinery anywhere
        # inside it belongs to some other rule, so crediting its warnings with it would label a
        # real gap as a wording problem. Every focused check is its own function.
        wired = fn.name != ORCHESTRATOR and any(tok in fn_src for tok in _ESCAPE_MACHINERY)
        for node in ast.walk(fn):
            msg = ""
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("append", "extend")
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in ("warnings", "warns", "out") and node.args):
                arg = node.args[0]
                msg = _render_str(arg)
                if not msg and isinstance(arg, ast.List) and arg.elts:
                    msg = _render_str(arg.elts[0])
            elif (isinstance(node, ast.Return) and fn.name.endswith("_warnings")
                  and isinstance(node.value, ast.List) and node.value.elts):
                msg = _render_str(node.value.elts[0])
            if len(msg) > 25:
                scope = _escape_scope(fn, node, src_lines)
                sites.append(AdvisorySite(line=getattr(node, "lineno", fn.lineno),
                                          function=fn.name, message=msg, wired=wired,
                                          scope_src=scope[0], scope_calls=scope[1]))
    return tuple(sorted(set(sites), key=lambda s: (s.line, s.function, s.message)))


def _escape_scope(fn: ast.FunctionDef, node: ast.AST,
                  src_lines: list[str]) -> tuple[str, frozenset[str]]:
    """The region an escape named by `node`'s message has to be wired in.

    A focused check is small enough that the whole function is the honest scope. The ORCHESTRATOR
    is not: it prints a handful of advisories of its own and also reads escapes on behalf of other
    rules, so an advisory inside it is scoped to its own top-level block. That is the difference
    between "this heading is read SOMEWHERE in a 200-line function" (which deleting the wiring
    would survive) and "this heading is read by the code that decides THIS advisory"."""
    if fn.name != ORCHESTRATOR:
        return _src_of(fn, src_lines), _called_names(fn)
    line = getattr(node, "lineno", 0)
    for stmt in fn.body:
        if isinstance(stmt, _BLOCKS) and stmt.lineno <= line <= (stmt.end_lineno or stmt.lineno):
            return _src_of(stmt, src_lines), _called_names(stmt)
    return _src_of(fn, src_lines), _called_names(fn)


def _function_node(module: str, function: str) -> ast.FunctionDef:
    src = (TOOLS / f"{module}.py").read_text(encoding="utf-8")
    for fn in ast.walk(ast.parse(src)):
        if isinstance(fn, ast.FunctionDef) and fn.name == function:
            return fn
    raise AssertionError(f"{module}.py has no function {function}()")


def _loaded_names(fn: ast.FunctionDef) -> frozenset[str]:
    """Every name READ inside `fn` — assignment targets do not count."""
    return frozenset(n.id for n in ast.walk(fn)
                     if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load))


def _flag_sites(fn: ast.FunctionDef) -> tuple[tuple[str, bool], ...]:
    """(flag, the value this occurrence produces is consumed) for every `--flag` literal in `fn`.

    coyomap parses argv by hand (no argparse anywhere — see `cli.py`'s dependency firewall), so
    "the parser accepts it" is "the flag literal is in the code that runs". The literal alone is
    not enough: `_ignored_root = _arg(argv, "--root")` mentions the flag and throws the answer
    away, which is EXACTLY the measured defect. So an occurrence sitting in an assignment whose
    targets are plain names that the function never reads back is marked discarded."""
    live = _loaded_names(fn)
    dead_lines: set[int] = set()
    for stmt in ast.walk(fn):
        targets: list[ast.expr] = []
        if isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets = [stmt.target]
        else:
            continue
        if targets and all(isinstance(t, ast.Name) and t.id not in live for t in targets):
            value = stmt.value
            if value is not None:
                dead_lines.update(range(value.lineno, (value.end_lineno or value.lineno) + 1))
    sites: list[tuple[str, bool]] = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("--"):
            sites.append((n.value, n.lineno not in dead_lines))
    return tuple(sites)


def make_flags_read_by(module: str, function: str) -> frozenset[str]:
    """Every `--flag` one function both names AND consumes.

    Scoping to ONE function is what makes the difference between accepted-and-used and
    accepted-and-ignored visible; scoping to a CONSUMED occurrence is what stops the original
    defect from passing its own regression test."""
    sites = _flag_sites(_function_node(module, function))
    return frozenset(flag for flag, used in sites if used)


def make_flags_discarded_by(module: str, function: str) -> frozenset[str]:
    """Flags this function parses and then throws away — named nowhere else in it. A strictly
    worse state than not accepting the flag: the code LOOKS like it honours it."""
    sites = _flag_sites(_function_node(module, function))
    return frozenset(flag for flag, _ in sites) - make_flags_read_by(module, function)


# --- (a) every command the CLI offers is reachable from the method --------------------

def test_every_cli_command_is_named_in_the_method():
    """A command the method never names cannot be reached: the build agent reads the method,
    not `--help`. Failed when this layer landed, on `dump` and `reconcile`; both are named in the
    method now, so this is the standing gate on the next command that forgets to be."""
    text = make_method_text()
    missing = [c for c in make_cli_commands() if f"coyomap {c}" not in text]
    assert not missing, (
        "CLI commands named nowhere in the method docs, so no build can reach them: "
        + ", ".join(missing)
        + " — every one of these is a working, tested command that a build agent has no way to "
          "learn about. `coyomap reconcile` is the measured case: four builds hand-wrote the "
          "file it generates instead of running it.")


def test_every_fix_verb_is_named_in_the_method():
    """`coyomap fix` dispatches three verbs and the method must name every one. Failed when this
    layer landed, on `dedup-relation` — which resolves a BLOCKING validate error, so a lead who
    hit that error had no documented way out and hand-edited the model instead. Now documented."""
    text = make_method_text()
    missing = [v for v in make_fix_verbs() if v not in text]
    assert not missing, (
        "`coyomap fix` verbs named nowhere in the method docs: " + ", ".join(missing))


# --- (b) every flag the method tells a build to pass is accepted ----------------------

def test_every_flag_the_method_prescribes_is_accepted_by_that_command():
    """The doc must not tell a build to pass a flag the command rejects. Passes today: the flag
    vocabulary in the method is in sync with the parsers. Kept as a standing gate — it is the
    cheap half of the contract, and it is the half that silently rots when a flag is renamed.

    The flag must appear in EXECUTABLE code, not merely somewhere in the file. This used to be a
    text search for the quoted literal anywhere in the module, which a comment or a docstring
    quoting the flag would have answered just as well as a parser. No module does that today, so
    this is a tightening with no finding behind it — taken because it is the same weakness as the
    mode-flag test below (a string standing in for behaviour), one step earlier in the chain."""
    bad: list[str] = []
    for cmd, flag, loc in make_doc_flag_pairs():
        if flag not in make_code_flag_literals(cmd):
            bad.append(f"{loc}: `coyomap {cmd} {flag}` — no executable code in "
                       f"{COMMAND_MODULE[cmd]}.py names it (a comment, a docstring or the USAGE "
                       "text does not count)")
    assert not bad, "Flags the method prescribes that the command does not accept:\n  " + "\n  ".join(bad)


def test_a_mode_flag_does_not_silently_swallow_the_flags_its_mode_ignores():
    """The other half of (b), and the one that bites: a flag can be *accepted* by the command
    and *ignored* by the mode.

    `coyomap preindex --report --root <other-repo>` is the measured case. `preindex.py` reads
    `--root` in `main()`, so the flag-existence check above passes — but `--report` branched into
    `report()`, which read only `--in`, so `--root` was silently dropped and the CWD's pre-index
    was reported instead of the named repo's. Silently using the wrong repo is worse than
    erroring: the output looks exactly right.

    FIXED, and this pins the fix. Two shapes are caught, and both are the original defect:
      ABSENT    — the mode's function never names the flag at all.
      DISCARDED — it parses the flag and throws the value away (`_ignored = _arg(argv, "--root")`).
                  The first version of this test looked only for the literal, so re-introducing
                  the measured bug in exactly this shape passed it. It does not any more.

    WHAT THIS DOES NOT PROVE. It is a static check: it proves the value is consumed, never that it
    is consumed CORRECTLY. `root_arg` read and then used to build the wrong path would pass here.
    The behavioural half is
    `tests/test_trapdoor_tools.py::test_preindex_report_honours_root_over_the_cwd_repo`, which
    runs the command against two real repos and reads the output."""
    main_flags = make_flags_read_by("preindex", "main")
    report_flags = make_flags_read_by("preindex", "report")
    discarded = make_flags_discarded_by("preindex", "report")
    # `--report` itself and the help flags are the mode switch, not mode input.
    switches = {"--report", "--help", "--in", "--depth", "--top"}
    ignored = sorted((main_flags - report_flags) - switches)
    assert not ignored, (
        "`coyomap preindex --report` accepts these flags and silently ignores them: "
        + ", ".join(f"{f} (parsed, then discarded)" if f in discarded else f"{f} (never read)"
                    for f in ignored)
        + " — `--root` is the one that matters: if --report reads only `--in` (a CWD-relative "
          "path), `preindex --report --root <other-repo>` reports the CURRENT repo's pre-index "
          "under the other repo's name. Either make report() honour --root, or reject the flag; "
          "accepting-and-ignoring is the failure mode with no visible symptom.")


# --- (c) every advisory offers a way to record the decision ---------------------------

#: Advisory message prefixes that legitimately need NO recordable escape, each with the reason.
#: An entry here is a claim: "this is always fixable at the point it fires, so an operator never
#: has to live with it." Adding a line to this list is a design decision, not a formality.
KNOWN_NO_ESCAPE: dict[str, str] = {
    # There is no legitimate way to owe a direction and not give one, so there is nothing to
    # record. The field is owed only where the map's OWN CODE touches a surface or a record, and a
    # door — a role standing at a surface, a human action with no product end — is already exempt
    # by the rule rather than by an escape. An operator who thinks a step needs no direction is
    # telling us the step is not a crossing, and the fix is the step, not a recorded line.
    "{} step(s) touch a surface or a record and say no `direction`":
        "the finding IS a missing answer; the fix is to answer it, or to fix the step's endpoints",
    # A META-advisory: its subject is a recorded exception that silences nothing, so "record an
    # exception to silence it" is circular — the remedy is to delete the dead line or fix the key.
    # Unsilenceable for the same reason the suppression-COUNT line is: a silence you cannot see is
    # indistinguishable from having no findings.
    "recorded `runs_in` exception(s) currently suppressing nothing":
        "the finding IS a dead record; recording another one cannot answer it",
    # The same META shape: both of these have a RECORD as their subject. Recording an exception to
    # silence a complaint about the shape of your records is circular; the remedy is to rewrite the
    # lines the finding names (collapse the repeats onto one line / fix the malformed key list).
    "'{}' repeats one reason across several records":
        "the finding IS the record's shape; the fix is to write the reason once with every id on it",
    "'{}' has a line that tries to be a record and adjudicates NOTHING":
        "a line that records nothing cannot be answered by recording another one; fix the key list",
    # The third of the same META family, and the counterweight to the first: merging kills the wall,
    # and one sentence stretched over 25 keys is a judgement made once and applied 25 times. Its
    # subject is a record, so recording another to silence it is circular — and an escape here would
    # let one line silence every finding it names and then silence the line saying so.
    "'{}' has one record answering {} findings with one sentence":
        "the finding IS the record's shape; split the line into the groups it is really about",
    # The map's own vocabulary, not a fact about the code: two boxes under one name are
    # indistinguishable on every diagram and in every sentence about them, and the remedy is a
    # rename. There is no state of the world in which "deliberately identical" helps a reader, so
    # there is nothing to record.
    "component name '{}' is used by {} components":
        "the finding IS the name; rename one box to the purpose that distinguishes it",
    # Row-local well-formedness: the fix is mechanical and local, there is no judgement to record.
    "{}: `no_call_site` is set but a `where` is present":
        "contradictory row; drop one field",
    "{} → {}: `no_call_site` is set but a `Where` is present":
        "contradictory row; drop one field",
    "{} → {}: the '{}' edge is declared {} times":
        "one edge, one primary call site; merge them",
    # A role INCLUSION's grant line: both shapes are mechanical and BLOCKING, so there is no
    # judgement to record. A `source` that is not a `path:line` makes the minted claim read "granted
    # at <prose>", telling a skeptic the grant is anchored and handing it nothing to open — worse
    # than the null it should be. A `source` on a `becomes` says nothing about a hat change.
    "{} relations[{}]: `source` is for `includes`":
        "a grant line says nothing about a hat change; drop the field",
    "{} relations[{}]: `source` is '{}', which is not a `path:line`":
        "leave it null instead — that states plainly that nobody anchored it, which is the fact",
    "{}: '{}' does not resolve to a":
        "a nonexistent path is never a judgement call",
    "{}: '{}' cites a line the file does not have":
        "the file is shorter than the citation, so the citation cannot be true of it at this commit "
        "— arithmetic, not judgement. Its sibling above ('does not resolve') is unrecordable for the "
        "same reason: both are BLOCKING problems from the existence gate, not advisories to live with",
    "{}: '{}' points at {} — anchor the operative statement":
        "the anchor moves to the acting line; nothing to record",
    "{} states: {} of {} state name(s) do not appear in the cited source":
        "either the names or the citation is wrong; both are fixable",
    "{}: state(s) with no transition in or out":
        "a typo'd state name or a missing transition; both fixable",
    "{} state machine(s) cite no `source`":
        "cite the declaring line, or drop the machine — the method forbids an uncited one",
    "{} ({}) is {}ed by {} ({}), which runs in {}":
        "a hard invariant of the code: a base cannot be absent from a process loading its subclass. "
        "Re-examined when the check grew its wholly-untagged-base arm: still no judgement. The rule "
        "only fires once the SUBCLASS is already placed, so the map itself determines the base's "
        "correct tag — the remedy is to copy it, not to decide anything. Escaping it via `runs-in` "
        "would let a map hide the exact defect it exists for (a missing base tag drew eight false "
        "process arrows on a live map)",
    # Row-completeness on a T4 row: an entry point runs INSIDE some component the map already
    # traces, so the owning C id exists to be named. Until it is, the row is invisible to the
    # entry-surface coverage check — an unrecordable state, not a recordable decision.
    "entry_points[{}] [{}] {}: externally activated but owned by no component":
        "name the owning C id; the row is incomplete, not adjudicable",
    # An element with nothing behind it — the same class as 'Subsystems with no members' below:
    # back it or delete it, and DELETING IT is the record.
    "{} ({}) has no T6 flow":
        "trace it or drop it — an untraced use case is a claim with nothing behind it",
    "{} ({}) drives no use case and appears in no flow":
        "trace it or drop it — a role nothing exercises is a claim with nothing behind it",
    # The messaging twin of the allowlisted `unbacked_entity_steps` rule below: the component IS a
    # publisher/consumer, so the C→broker edge is a fact of the code, always authorable.
    "{}: {}(s) {} carry no backbone edge to {}":
        "author the C→broker edge; a recorded participant provably talks to the broker",
    # The honesty record. Both are FACTS about how much of the claim surface was challenged, and an
    # escape would be a switch for making an unverified map look verified — the one thing the
    # grounding feature exists to prevent. Authoring the `grounding` block is the only answer, and
    # it is a structured one (like `deployment_linked`), not an extras token.
    "No `grounding` record":
        "record `grounding` (the block itself IS the escape); an extras token would defeat the feature",
    # The same shape from the other side: claims the pinned worklist held that the shipped map no
    # longer makes. Both honest answers are structured — re-state the claim, or re-pin the surface
    # with `audit` — and re-pinning IS the record, exactly as authoring `grounding` is above. An
    # extras token here would let a build delete a claim and then delete the line saying so.
    "{} claim(s) the skeptics were given are GONE from the shipped map":
        "re-state the claim, or re-pin the surface with `coyomap audit` — the re-pin IS the record",
    # Arithmetic between the record and the closer's own files. There is no judgement to record:
    # either the record is stale (re-run `grounding write`) or `verify/` has lost files (restore
    # them). An extras token would be a switch for asserting an appeal that never happened, which is
    # exactly what the check exists to stop — the same reason `No 'grounding' record' is allowlisted.
    "`grounding`'s appeal counts disagree with the closer's files":
        "re-run `grounding write` over every closer file, or restore the verify files — an escape "
        "here would let a map assert an appeal nothing backs",
    "Grounding is partial":
        "a measured share of the claim surface — ground more claims; nothing else can honestly quiet it",
    # Closed two-word vocabulary: the fix is to write `verified` or `inferred`, never a judgement.
    "{} row(s) carry a `confidence` outside the vocabulary":
        "use one of the two words the template asks for; there is nothing to adjudicate",
    # Vocabulary nudges: reuse the seed spelling or mint deliberately; the map records the choice.
    "{} bucket '{}' is long (>40 chars)": "shorten the label",
    "Library bucket '{}' is minted (not a seed)": "the minted name IS the record",
    "External bucket '{}' is minted (not a seed)": "the minted name IS the record",
    "The '{}' catch-all among {} holds {} deps": "splitting the bucket is the fix",
    "Many purpose buckets among {}": "merging near-duplicates is the fix",
    "entry-point kind '{}' ({} row(s)) is a drift spelling": "write the canonical spelling",
    "entry-point kind(s) minted (not a seed)": "the minted kind IS the record",
    "{} C→D edge(s) name no role (generic verb)": "a role-revealing verb is always available",
    # Cadence / actor / flow shape: each names the concrete edit that clears it.
    "entry_points[{} {}] records cadence '{}' but is externally activated": "drop the cadence",
    "entry_points[{} {}] cites a `cadence_source` but records no `cadence`": "record the cadence",
    "{} entry-point cadence value(s) cite no `cadence_source`": "anchor the declaring line",
    "{} ({}) mixes a human actor [{}] with a service actor [{}]": "the service is the delivery mechanism; drop it",
    "{} ({}) is referenced {} time(s)": "advisory on the fragment channel by design; inline or leave",
    "{}: broker {} ({}) classifies as '{}'": "re-classify the dep or re-point the channel",
    "Domain card {}: relation '{} … {}' is not backed by a field": "mark the FK marker",
    "Domain card {}: relation '{} … {}' is field-less but its note": "mark the FK marker",
    "{} extra.{}: looks like deployment/config info": "move the row to its real array",
    # Grouping hygiene: pure regrouping, free and view-only by the method's own contract.
    "Groups whose only child is another group of the same kind": "inline the wrapper level",
    "Subsystems with no members": "delete the empty group or give it members",
    "Subdomains with no entities": "delete the empty group or give it members",
    "Entities with no SUBDOMAIN (ungrouped / top-level)": "assign the subdomain",
    # These carry a STRUCTURED escape instead of an extras token — a field on the row, which is
    # a better record than a heading because it travels with the thing it describes.
    "External deps with no incoming edge": "`deployment_linked: true` on the dep is the escape",
    "Deps marked `deployment_linked` but which are a code call target": "drop the marker",
    "{} deployment advisory/advisories suppressed by recorded scoped exception(s)":
        "this IS the escape being reported; it must never be silenceable itself",
    "recorded `runs_in` exception key(s) no check reads":
        "the opposite of an advisory needing an escape — it reports that the escape the operator "
        "wrote is a typo, and names the five that work",
    # The same line one generation on, for a `/scope` word instead of a literal: it reports that the
    # record the operator wrote silences nothing, and names the scopes that do work. Recording
    # another escape to answer it would be recording a second dead line.
    "{} recorded '{}' key(s) name a scope no check reads":
        "the finding IS a record that silences nothing, and it names the scopes that do; another "
        "record cannot answer it",
    "a bare `runs-in` exception is recorded and silences NOTHING":
        "the opposite of an advisory needing an escape — it exists to say the escape the operator "
        "wrote does not work, and names the five scoped lines that do",
    "{} store-hygiene advisory/advisories suppressed by the recorded `store` exception":
        "same shape as the `runs-in` count above — a suppression report that can itself be "
        "suppressed reports nothing",
    # Fill-in-the-field advisories. There is nothing for an operator to ACCEPT: "deliberately no
    # expectation" is what `excluded` means, and "deliberately no audience" is not a state a role can
    # be in. A record here would rebuild the exact hole the old three-value `label` had, where an
    # empty value silently read as "off the walk".
    "{} ({}) has no `happy_path` expectation": "answer it — `excluded` IS the recorded decision",
    "Role(s) with no `audience`: {}": "answer it — there is no third state for a role to be in",
    # Deliberately un-escapable: the whole point is that a suppressed count stays visible.
    "{} {}: {} → {} claims entity use the backbone doesn't": "author the edge; the safety net derives it",
    # The same shape one level down: this line IS the disclosure of an already-recorded exception,
    # so recording another to silence it would re-create the hole it exists to close. Before it
    # existed, 32 excused ways in produced no output at all and a clean run could not be told from
    # a run with 32 doors belonging to nothing.
    "{} externally-activated way(s) in are suppressed by a recorded":
        "the finding IS the disclosure of a record; silencing it restores the silence it fixes",
    # Same family: this line discloses an excuse the CODE grants (name matches a system dep), not
    # one an operator recorded. Letting it be silenced would restore the silence that shipped a map
    # saying the product's dashboard has no production host.
    "{} deployment unit(s) host no component and are excused because the":
        "the finding IS the disclosure of a built-in excuse; check the unit's build file instead",
}


def _has_escape(message: str) -> bool:
    low = message.lower()
    return (any(h in low for h in MACHINE_READ_HEADINGS)
            or "record the literal" in low or "extras heading" in low)


def _allowlisted(message: str) -> bool:
    return any(message.startswith(prefix) for prefix in KNOWN_NO_ESCAPE)


def test_every_validator_advisory_names_a_way_to_record_the_decision():
    """An advisory an operator decides to LIVE WITH must be recordable, or it re-fires at every
    validate forever and gets waved through — the "advisory waved through" failure the method
    names in its own words.

    Failed when this layer landed. The headline was trap P1 — "Entities with no owning component"
    — where three separate live leads independently invented a `Persistence exceptions` heading
    that existed but was read only by the persistence-COVERAGE rule (which filters `Cn` ids) and
    silenced nothing here. Every residue has since been answered or allowlisted.

    SCOPE. This reads the MESSAGE TEXT only: it proves an operator is TOLD where to record the
    decision. Whether the escape the message names is wired to anything is the next test's job,
    and whether recording it actually silences the advisory is proven at runtime by
    `tests/test_trapdoor_tools.py` (traps P1 and P2) against the real fixture map.

    The report separates two failure shapes, because they need different fixes:
      NO-ESCAPE   — nothing anywhere can silence it; the fix is to add an escape token.
      UNNAMED     — an escape IS wired to the check, but its message never says so; the fix is
                    one sentence in the message. Cheap, and the difference between an operator
                    recording a decision and an operator ignoring a line forever."""
    orphans = [s for s in make_advisory_sites()
               if not _has_escape(s.message) and not _allowlisted(s.message)]
    detail = "\n  ".join(
        f"{'UNNAMED  ' if s.wired else 'NO-ESCAPE'} validate_model.py:{s.line} ({s.function}): "
        f"{s.message[:105]}" for s in orphans)
    assert not orphans, (
        f"{len(orphans)} validator advisory/advisories offer no recordable escape in their text "
        "and are not allowlisted — an operator who decides the finding is acceptable has nowhere "
        "to say so:\n  " + detail)


def _reads_heading(src: str, heading: str) -> bool:
    """Does this source READ the extras heading — not merely mention it in a message?

    A read is a call into the readers the tools own (`_recorded_ids` / `extras_bodies` /
    `_recorded_line_keys`, and the shared `records` module they now all delegate to) with the
    heading as its literal argument. 'Balance exceptions' is also reachable through `balance_lib`'s
    own `_exceptions()`, which carries the heading in a module constant.

    `_recorded_line_keys` joined the list when the duplicate-security and bucket-vocabulary escapes
    moved to exact prefix-and-colon keying: it wraps `extras_bodies` and takes the heading as a
    PARAMETER, so neither the direct pattern nor the transitive walk could see the literal, which
    sits at the call site. `records.recorded_keys` / `records.lines` joined it when the four
    per-family line parsers were folded into one shared reader."""
    readers = r"(?:_recorded_ids|extras_bodies|_recorded_line_keys|records\.recorded_keys|records\.lines)"
    reader = re.compile(readers + r"\(\s*\w+\s*,\s*[\"']" + re.escape(heading) + r"[\"']", re.I)
    if reader.search(src):
        return True
    # …or a constant that carries it: `records.recorded_keys(m, WALK_JUMPS_HEADING)`.
    constants = make_heading_constants()
    for name in re.findall(readers + r"\(\s*\w+\s*,\s*([A-Z_]+_HEADING)\b", src):
        if constants.get(name, "").lower() == heading.lower():
            return True
    return heading == "balance exceptions" and "_exceptions(" in src


def _reads_heading_via_calls(names: frozenset[str], heading: str,
                             fns: dict[str, ToolFunction], seen: set[str]) -> bool:
    """The same question, followed through the tools' own calls — a check that delegates its
    filtering to a helper (`unexplained_persistence_pairs`) is wired just as truly as one that
    inlines it."""
    for name in sorted(names):
        fn = fns.get(name)
        if fn is None or name in seen:
            continue
        seen.add(name)
        if _reads_heading(fn.src, heading) or _reads_heading_via_calls(fn.calls, heading, fns, seen):
            return True
    return False


def _passes_a_reader_result_into(caller: ToolFunction, callee: str, heading: str,
                                 fns: dict[str, ToolFunction]) -> bool:
    """Does `caller` read the heading and hand the RESULT to `callee` as an argument?

    The escape for a check that takes its exceptions as a parameter lives at the call site, not
    inside the check — `validate_model` reads the recorded 'Coverage exceptions' dirs and passes
    them into `check_domain_coverage_model`. Matching on the argument NAME (bound from a reader)
    keeps that legitimate shape from reading as a gap."""
    tree = ast.parse(textwrap.dedent(caller.src))
    passed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == callee:
            passed.update(a.id for a in node.args if isinstance(a, ast.Name))
            passed.update(k.value.id for k in node.keywords if isinstance(k.value, ast.Name))
    if not passed:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or node.value is None:
            continue
        if not any(isinstance(t, ast.Name) and t.id in passed for t in node.targets):
            continue
        if (_reads_heading(ast.unparse(node.value), heading)
                or _reads_heading_via_calls(_called_names(node.value), heading, fns, set())):
            return True
    return False


def _escape_is_wired(site: AdvisorySite, heading: str, fns: dict[str, ToolFunction],
                     callers: dict[str, frozenset[str]]) -> bool:
    if _reads_heading(site.scope_src, heading):
        return True
    if _reads_heading_via_calls(site.scope_calls, heading, fns, set()):
        return True
    # A wrapper that applies the escape to this check's OUTPUT, or a caller that supplies it as
    # input. `_deployment_quality_warnings` is the first shape (it collapses its `_raw` twin's
    # findings once `runs-in` is recorded); the orchestrator passing `cov_dirs` is the second.
    for name in sorted(callers.get(site.function, frozenset())):
        caller = fns.get(name)
        if caller is None:
            continue
        if name != ORCHESTRATOR and _reads_heading(caller.src, heading):
            return True
        if _passes_a_reader_result_into(caller, site.function, heading, fns):
            return True
    return False


def test_every_advertised_escape_is_wired_to_the_check_that_prints_it():
    """An advisory whose message NAMES an extras heading is making a promise: record this and I
    will go quiet. Nothing generic used to hold that promise to the code — the message text and
    the wiring were two independent facts, and the check above only ever read the text. Deleting
    the `_recorded_ids(m, "persistence exceptions", ("E",))` line behind the unowned-entity
    advisory, while leaving the sentence that advertises it, passed the whole suite.

    This closes it generically: for every advisory that names a heading, the code that DECIDES
    that advisory must actually read it — directly, through a helper it calls, through the
    wrapper that filters its output, or from a caller that hands it the recorded ids. A new
    advisory that advertises an escape it does not have fails here on the day it is written.

    SCOPE. Static: it proves the reader is called, not that the answer changes. The behavioural
    proof for the two measured cases is `tests/test_trapdoor_tools.py` traps P1 and P2, which
    record the heading on a real map and assert the advisory actually goes quiet."""
    fns = make_tool_functions("validate_model.py", "balance_lib.py")
    tables: dict[str, frozenset[str]] = {}
    for mod in ("validate_model.py", "balance_lib.py"):
        tables.update(make_dispatch_tables((TOOLS / mod).read_text(encoding="utf-8")))
    callers = make_tool_callers(fns, tables)
    gaps: list[str] = []
    for site in make_advisory_sites():
        low = site.message.lower()
        for heading in MACHINE_READ_HEADINGS:
            if heading in low and not _escape_is_wired(site, heading, fns, callers):
                gaps.append(f"validate_model.py:{site.line} ({site.function}) tells the operator "
                            f"to record '{heading}' — nothing in the code that decides this "
                            f"advisory reads that heading: {site.message[:90]}")
    assert not gaps, (
        f"{len(gaps)} advisory/advisories advertise an extras heading that does not silence "
        "them — prose promising a tool that is not there, which is the exact class this layer "
        "exists to catch:\n  " + "\n  ".join(gaps))


def test_the_no_escape_allowlist_has_no_dead_entries():
    """An allowlist entry that matches nothing is a claim about code that no longer exists —
    it hides the next advisory that grows into that shape. This one PASSES today and is the
    guard that keeps the list above honest."""
    messages = [s.message for s in make_advisory_sites()]
    dead = [p for p in KNOWN_NO_ESCAPE if not any(m.startswith(p) for m in messages)]
    assert not dead, "KNOWN_NO_ESCAPE entries matching no advisory today:\n  " + "\n  ".join(dead)


# --- (d) every heading the method prescribes is read by a tool ------------------------

def make_documented_headings() -> tuple[str, ...]:
    """Extras headings the method tells a lead to WRITE, read out of the docs' own quoting
    convention (a quoted Title Case phrase followed by the words `extras heading`)."""
    # Collapse ALL whitespace first: the docs wrap mid-phrase, and a heading read as
    # "balance   exceptions" would fail against a tool that reads "balance exceptions" —
    # a false finding, which is the one thing a contract test must never produce.
    text = re.sub(r"\s+", " ", make_method_text())
    pat = re.compile(r"[\"'“]([A-Z][A-Za-z -]{3,30})[\"'”]\*{0,2} extras heading")
    found = {" ".join(m.group(1).split()).lower() for m in pat.finditer(text)}
    return tuple(sorted(found))


def test_every_extras_heading_the_method_prescribes_is_read_by_a_tool():
    """A heading a lead is told to write but nothing reads is prose that silences nothing — the
    same class as an unreachable command, one level down.

    Scanned across EVERY advisory-owning tool (`ADVISORY_TOOL_FILES`), not just `validate_model`:
    an advisory does not have to live there to name an escape, and `finalize`'s access-baseline one
    named a heading nothing read for as long as this scan looked at two files."""
    src = "\n".join((TOOLS / f).read_text(encoding="utf-8")
                    for f in ADVISORY_TOOL_FILES).lower()
    unread = [h for h in make_documented_headings() if f'"{h}"' not in src]
    assert not unread, (
        "Extras headings the method tells a lead to write that NO tool reads: "
        + ", ".join(unread))


def test_every_machine_read_heading_is_documented_in_the_method():
    """The converse: a heading the validator honours but the method never names is an escape
    nobody can use. PASSES today."""
    text = make_method_text().lower()
    undocumented = [h for h in MACHINE_READ_HEADINGS if h not in text]
    assert not undocumented, (
        "Extras headings the validator reads but the method never names: " + ", ".join(undocumented))


def test_the_machine_read_heading_list_matches_the_validator():
    """MACHINE_READ_HEADINGS is used by the escape-token audit above, so it must not drift from
    the source. Re-derived here from the tools' own call sites — including `balance_lib`, which
    owns the 'Balance exceptions' constant that `validate_model` reaches through a helper, and
    `audit_model`, which owns 'Audit exceptions', and `anchor_drift`, which owns 'Drift exceptions'.
    `audit` read no extras heading at all until that one landed, so every one of its six advisory
    families was permanently unanswerable; a file missing from this list is a family whose escape
    nothing here audits."""
    src = "\n".join((TOOLS / f).read_text(encoding="utf-8")
                    for f in ADVISORY_TOOL_FILES)
    # Case-folded: `extras_bodies` matches headings case-insensitively, so a constant written in
    # title case ("Audit exceptions") and a call-site literal in lower case name the same heading.
    found = {h.lower() for h in
             re.findall(r'(?:extras_bodies\(m,|_recorded_ids\(m,|_recorded_line_keys\(m,'
                        r'|records\.recorded_keys\(m,|records\.lines\(m,)'
                        r'\s*"([^"]+)"', src)}
    # Any `*_HEADING = "…"` constant, not only the `_EXCEPTIONS_` ones: "Missing surfaces" and
    # "Walk jumps" are read through `MISSING_SURFACES_HEADING` / `WALK_JUMPS_HEADING`, and the
    # narrower pattern let both drop out of this list without a word.
    found |= {h.lower() for h in re.findall(r'[A-Z_]+_HEADING\s*=\s*"([^"]+)"', src)}
    assert found == set(MACHINE_READ_HEADINGS), (
        f"MACHINE_READ_HEADINGS is stale: the tools read {sorted(found)}")


def _main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}\n  {exc}\n")
    print(f"{len(fns) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())


def test_every_advertised_command_has_a_module_in_the_flag_audit_table():
    """COMMAND_MODULE parity with `coyomap --help`.

    `finalize` shipped absent from this table, so the flag audit below silently skipped the two flags
    method.md prescribes for it. A missing row does not fail anything — it just stops auditing — which
    is the quietest way for this layer to lose coverage."""
    advertised = set(make_cli_commands())
    missing = sorted(advertised - set(COMMAND_MODULE))
    assert not missing, f"command(s) advertised by --help but absent from COMMAND_MODULE: {missing}"


def make_prescribed_balance_literals() -> tuple[str, ...]:
    """Every literal the method tells a lead to record under a 'Balance exceptions' heading.

    Read out of the prose, so a new instruction joins this audit automatically."""
    text = make_method_text()
    near = re.compile(r"balance exceptions", re.IGNORECASE)
    # Two shapes the method actually uses, and the first version of this test caught only one — so it
    # did not detect `security-granularity`, the literal it was written for. That is the same
    # near-vacuous-test failure this layer keeps finding elsewhere.
    #   (a) "the literal `runs-in`" / "record the literal `store`"  — a silencing escape
    #   (b) "`security-granularity: <value>`"                        — a declaration
    escape_form = re.compile(r"literal\s+\*{0,2}`([a-z][a-z/-]+)`", re.IGNORECASE)
    # The declaration form requires a HYPHEN: every literal in this vocabulary is hyphenated
    # (`security-granularity`, `channel-ends`, `entity-flows`, `runs-in`), while the un-hyphenated
    # backtick-plus-colon hits nearby are field names and prose (`dep:`, `path:`, `why:`, `step:`).
    declare_form = re.compile(r"`([a-z]+(?:[-/][a-z]+)+)\s*:")
    found: set[str] = set()
    for para in re.split(r"\n\s*\n", text):
        if not near.search(para):
            continue
        found |= set(escape_form.findall(para))
        found |= set(declare_form.findall(para))
    return tuple(sorted(found))


def test_every_balance_exceptions_literal_the_method_prescribes_is_read_by_a_tool():
    """The heading-level twin of this already exists; this is the LITERAL level, and it was missing.

    `security-granularity` shipped as the first literal the method told a build to record under a
    machine-read heading that no tool read — so a build would have written a line nothing consumed,
    and a typo in it would have been undetectable. That is the `coyomap reconcile` failure class (a
    working, tested, unreachable thing) one rung down, and the heading-level test could not see it
    because the HEADING was read; only this literal was not.

    A literal counts as read if `balance_lib._LITERAL_ESCAPES` silences an advisory with it, or some
    tool reads it by name for another purpose (the granularity DECLARATION silences nothing — it is
    echoed beside the security-row count it explains)."""
    src = "\n".join((TOOLS / f).read_text(encoding="utf-8")
                    for f in ("validate_model.py", "balance_lib.py", "audit_model.py",
                              "assemble.py", "balance.py"))
    escapes = set(balance_lib._LITERAL_ESCAPES)
    unread = [lit for lit in make_prescribed_balance_literals()
              if lit not in escapes and lit not in src]
    assert not unread, (
        "literal(s) the method tells a build to record under 'Balance exceptions' that no tool reads: "
        + ", ".join(unread) + " — a record nothing consumes is a decision the build cannot act on, "
        "and a typo in it is undetectable")


def make_documented_json_blocks() -> list[tuple[str, str, str]]:
    """(source, kind, RAW TEXT) for every ```json block in the method docs that a build copies.

    The raw text, not a re-serialized parse: an earlier version parsed each block and handed
    `json.dumps(obj)` to the loader, which normalized away every purely textual defect — a trailing
    comma, a smart quote, an inline `//`. It read the real file and then threw the file's text away.

    Kind comes from the surrounding PROSE (which loader the doc names), never from the loader's own
    key allowlist. Classifying by allowlist meant a misspelled top-level key — exactly the defect worth
    catching — silently reclassified the block as "other" and removed it from scope."""
    out: list[tuple[str, str, str]] = []
    for doc in METHOD_DOCS:
        if not doc.is_file():
            continue
        text = doc.read_text(encoding="utf-8")
        for hit in re.finditer(r"```json\n(.*?)```", text, re.S):
            before = text[max(0, hit.start() - 800):hit.start()].lower()
            if "--rules" in before or "coyomap reconcile" in before:
                kind = "reconcile-rules"
            elif "reconcile" in before or "drop_edges" in before:
                kind = "reconcile"
            else:
                kind = "other"
            out.append((f"{doc.name}:{text[:hit.start()].count(chr(10)) + 1}", kind, hit.group(1)))
    return out


def test_every_documented_json_block_is_valid_json():
    """The most basic doc defect, and the one the loader tests used to EXEMPT: a fenced ```json block
    a build copies that is not JSON at all. The earlier `except ValueError: continue` was justified as
    skipping "elided sketches"; there are none, so its only live effect was to hide real syntax
    errors."""
    bad: list[str] = []
    for src, _kind, raw in make_documented_json_blocks():
        try:
            json.loads(raw)
        except ValueError as e:
            bad.append(f"{src}: {e}")
    assert not bad, "```json block(s) a build copies that are not valid JSON:\n  " + "\n  ".join(bad)


def test_every_reconcile_example_in_the_method_loads_through_the_real_loader():
    """A build copies these blocks verbatim, so a shape the loader rejects is a doc-shaped bug.

    This is the class the `.coyomap/.ignore` example proved: the method showed `pattern  # comment`,
    the parser treated the whole line as one pattern, three live patterns matched nothing, and the
    build deleted the file instead of fixing the syntax. The fix was worth little until a test read the
    example out of the REAL doc — so the same discipline applies to the JSON the method teaches, and
    `drop_edges`'s shape was undocumented until a build read `reconcile.py`'s source to find it."""
    from coyomap.reconcile import ReconcileError, load_reconcile

    examples = [(src, raw) for src, kind, raw in make_documented_json_blocks()
                if kind == "reconcile"]
    assert len(examples) >= 2, f"expected the `set` and `drop_edges` examples, found {examples}"
    for src, raw in examples:
        try:
            rec = load_reconcile(raw, src)          # the RAW text a build copies
        except ReconcileError as e:
            raise AssertionError(f"{src} is not loadable by `assemble --reconcile`: {e}") from e
        assert not rec.is_empty(), f"{src} parsed to an EMPTY reconcile — the example teaches nothing"


def test_every_reconcile_rules_example_in_the_method_is_accepted_by_the_generator():
    """The `coyomap reconcile --rules` input shape, same reasoning. It ran 0 times in 3 measured
    builds, so its documented example is the only thing a build has to go on."""
    from coyomap.reconcile_build import RuleError, load_rules

    examples = [(src, raw) for src, kind, raw in make_documented_json_blocks()
                if kind == "reconcile-rules"]
    assert examples, "expected the --rules example the method documents"
    for src, raw in examples:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rules.json"
            p.write_text(raw, encoding="utf-8")     # the RAW text a build copies
            try:
                rules = load_rules(p)
            except RuleError as e:
                raise AssertionError(f"{src} is not loadable by `coyomap reconcile --rules`: {e}") from e
        assert rules, f"{src} parsed to zero rules — the example teaches nothing"


def test_every_scoped_runs_in_literal_appears_in_the_method_prose():
    """The REVERSE direction of the audit above, and the gap that let a contract change ship half
    done: the tool stopped honouring a bare `runs-in`, and `method.md` / `method/model.md` went on
    teaching it for another commit. Build agents read those files on every run, so a lead following
    the method would have written the dead literal, silenced nothing, and gained an advisory.

    The existing test only checks method-literal -> tool. `runs-in` is still a recognised literal
    (it is what the "silences nothing" complaint keys off), so that direction stayed green."""
    from coyomap.balance_lib import RUNS_IN_SCOPES
    prose = "\n".join((REPO_ROOT / rel).read_text(encoding="utf-8")
                      for rel in ("method.md", "method/model.md"))
    missing = [scope for scope in RUNS_IN_SCOPES if f"`{scope}`" not in prose]
    assert not missing, (
        f"scoped `runs_in` literal(s) the tool honours but the method never names: {missing} — a "
        f"build cannot record an escape it has never been told about")


def test_every_worklist_theme_is_named_in_the_method():
    """The method tells a build to batch Phase 4 on `theme`, so the closed set it prints must be the
    set the tool emits. It was not: `rule` was added to `_THEMES` by the T7 fold and `method.md` went
    on listing eight themes for two releases, so a lead batching by the method's list had no bucket
    for the decision layer. Nothing caught it — the flag audit checks commands and flags, not the
    vocabulary the payload carries."""
    from coyomap.audit_model import _THEMES
    prose = (REPO_ROOT / "method.md").read_text(encoding="utf-8")
    marker = "closed, most-dangerous-first set ("
    at = prose.find(marker)
    assert at != -1, f"method.md no longer introduces the theme set with {marker!r}"
    # Read the PARENTHESISED LIST ONLY. Two weaker versions of this test both passed while the list
    # was missing `rule`: a document-wide substring check (every theme name is also an ordinary word
    # somewhere in method.md) and a whole-paragraph check (the prose right after the list explains
    # what `rule` means, which is enough to satisfy the search). The list is the thing under
    # contract, so the list is what gets read.
    open_at = at + len(marker) - 1
    close_at = prose.find(")", open_at)
    assert close_at != -1, "the theme set's parenthesis is never closed"
    listing = prose[open_at:close_at + 1]
    missing = [t for t in _THEMES if f"`{t}`" not in listing]
    assert not missing, (
        f"worklist theme(s) the tool emits but the method's printed set omits: {missing} — a build "
        f"told to batch on `theme` cannot bucket a value it has never been shown")


def test_the_method_no_longer_teaches_the_bare_runs_in_escape():
    """It silences nothing now, and a doc that still prescribes it costs a build an advisory plus
    the turns spent working out why the record did not take."""
    prose = "\n".join((REPO_ROOT / rel).read_text(encoding="utf-8")
                      for rel in ("method.md", "method/model.md"))
    for dead in ("the literal **`runs-in`** silences", "the literal `runs-in` silences"):
        assert dead not in prose, dead


# --- (e) the writing rules reach the agents that write the text -------------------------------
#
# The six rules govern the prose a READER meets in the viewer. The agents that author it are
# fan-out workers, and a worker reads its contract, never method.md — so a rule that lives only in
# method.md reaches the lead and nobody else. These four tests pin the seam: the rules exist in one
# file, that file is appended to every contract whose agents author reader-facing prose, and no
# second copy exists to drift out of step.

WRITING_RULES = REPO_ROOT / "method" / "templates" / "writing-rules.md"

# Contracts whose agents author a reader-facing prose field, and the field that makes it so.
_AUTHORING_CONTRACTS = (("harvest-contract.md", "components[].purpose"),
                        ("rules-contract.md", "rules[].statement and rules[].risk"))

_WRITING_RULE_HEADS = ("One idea per sentence", "No em dash", "No code in plain text",
                       "Every reference resolves inside the same box", "Use a glossary word",
                       "Plain words at the SAME precision")


def test_the_writing_rules_file_exists_and_carries_all_six_rules():
    """One file is the whole point of the extraction. If a rule is missing here it is missing from
    every contract at once, which is the failure mode worth having: loud, not silent-per-slice."""
    assert WRITING_RULES.exists(), f"{WRITING_RULES} is the single source of the writing rules"
    text = WRITING_RULES.read_text(encoding="utf-8")
    missing = [head for head in _WRITING_RULE_HEADS if head not in text]
    assert not missing, f"writing rule(s) absent from the shared file: {missing}"
    for n in range(1, 7):
        assert f"{n}. **" in text, f"rule {n} is not a numbered item — the contract quotes them by number"


def test_the_method_hands_every_contract_over_with_the_verb_not_a_copy():
    """The lead must never handle a template. A `cp` or a `cat` puts the file in the lead's hands,
    and that is how a build sent the WHOLE skeptic template to ten skeptics: they read the lead's
    instructions as their own, and four were told to open a claims file that does not exist.

    Read the sentence that names the scratch file, not the whole document: method.md mentions the
    verb elsewhere, and a document-wide search would pass while one command still said `cp`."""
    flat = " ".join((REPO_ROOT / "method.md").read_text(encoding="utf-8").split())
    # Either shape of the verb counts: the redirect that hands over the agent's half, or the
    # `--slots` / `--fill` / `--from-batches` forms that write the brief (and, for harvest, record
    # the budget — a hand-filled copy records nothing, which is why the method prescribes them).
    for name in ("harvest", "trace", "rules", "skeptic", "tests"):
        hits = re.findall(rf"coyomap contract {name}(?: >|\s+--(?:slots|fill|from-batches))", flat)
        assert hits, f"method.md never hands the {name} contract over with the verb"


def test_the_method_no_longer_teaches_copying_a_template_by_hand():
    """Both shapes of the old instruction, so neither can come back quietly."""
    prose = (REPO_ROOT / "method.md").read_text(encoding="utf-8")
    for dead in ("cp COYOMAP_HOME/method/templates", "cat COYOMAP_HOME/method/templates"):
        assert dead not in prose, f"method.md still teaches `{dead}`"


def test_the_six_rules_are_stated_in_exactly_one_place():
    """DRY, checked rather than intended. A contract that restates a rule is a second copy, and the
    copy that drifts is always the one nobody re-read."""
    others = [p for p in REPO_ROOT.glob("method/templates/*.md") if p != WRITING_RULES]
    others.append(REPO_ROOT / "method.md")
    for path in others:
        text = path.read_text(encoding="utf-8")
        restated = [head for head in _WRITING_RULE_HEADS if head in text]
        assert not restated, (
            f"{path.relative_to(REPO_ROOT)} restates writing rule(s) {restated} — append "
            f"writing-rules.md instead, so there is one source to change")


def test_the_method_points_the_lead_at_the_shared_writing_rules_file():
    """The lead has to know the file exists to append it, and a pointer is not a restatement."""
    prose = (REPO_ROOT / "method.md").read_text(encoding="utf-8")
    assert "method/templates/writing-rules.md" in prose


# --- retro 2026-08-18: findings 7, 14, 19 --------------------------------------------

def test_the_method_says_whether_a_T7_agent_may_own_more_than_one_block():
    """"One agent per block" was stated and nothing said what bundling costs.

    A build gave four of its five rule agents two or three blocks each. Its `BR` ranges stayed
    contiguous so nothing failed, and the property the fan-out exists for — fresh context PER
    block — was spent without anyone deciding to spend it.
    """
    text = (REPO_ROOT / "method.md").read_text(encoding="utf-8")
    assert "One block per agent is the rule" in text, "the rule must be stated, not implied"
    para = text.split("One block per agent is the rule", 1)[1][:1200]
    assert "fresh context" in para, "it must say what bundling costs"
    assert "Balance exceptions" in para, "it must say where a deliberate bundle is recorded"


def test_dispatch_says_the_briefing_comes_before_the_first_tool_call():
    """"First message" was read as "somewhere early".

    One build ran `scope` at turn 6 and emitted two user-facing messages in its first seventy
    turns, neither of them the briefing and neither naming the mode. The operator learned what the
    map had covered only once the map was finished.
    """
    text = (REPO_ROOT / "method" / "dispatch.md").read_text(encoding="utf-8")
    assert "before the first tool call" in text, (
        "'first message' needs a definition a build cannot read as 'somewhere early'")


def test_the_retro_method_defines_all_three_finding_tags_and_the_LOW_gate():
    """A ranked list of prose collapses three different questions into one impression.

    Severity is what the defect costs the MAP, fix class is whether there is one right answer, and
    risk is what applying the fix could break. They do not correlate: on the run this came from,
    the two biggest map-quality defects were also two of the cheapest, safest fixes, and both were
    buried in a flat ranking.
    """
    text = (REPO_ROOT / "eval" / "retro" / "method.md").read_text(encoding="utf-8")
    for tag in ("`severity`", "`fix_class`", "`risk`"):
        assert tag in text, f"{tag} must be defined in the finding shape"
    assert "The gate for LOW is testability" in text, (
        "LOW risk has to be earned by a test, or it is just a feeling")
    assert "Name that test file on every LOW row" in text
    assert "HIGH severity at LOW risk" in text, "the ordering quadrant must be stated"
    assert "A PROPOSAL IS NEVER A MAP REPAIR" in text, (
        "the taxonomy is tools, method and assertions; a map repair is not a retro proposal")
    assert "severity | fix class | risk" in text, (
        "the report skeleton must ask for the at-a-glance table, not just prose")


def test_the_retro_method_carries_the_four_habits_that_produced_its_own_corrections():
    """Each of these caught a real defect in a real retro, and none was written down.

    A claim-level refuter cannot find what nobody claimed; the operator's decision is the one input
    the carry-forward cannot compute; a per-agent pass that names what it read and not what it
    skipped reads as complete; and a number from a throwaway script is a draft.
    """
    text = (REPO_ROOT / "eval" / "retro" / "method.md").read_text(encoding="utf-8")
    assert "## Step 5b — Send one reader at the FINISHED report" in text, (
        "Step 5 refutes claims mid-draft; the finished report needs its own reader")
    assert "What the retro MISSED" in text, "that is the reason Step 5b exists"
    assert "write the answer into `findings.json` as each row's `decision`" in text, (
        "an unrecorded decision leaves every row `proposed` and the carry-forward inert")
    assert "state the per-agent read COVERAGE as a fraction" in text
    assert "is a draft until a second signal agrees with it" in text, (
        "the hand-rolled-scan rule is the most common way a retro publishes something false")


def test_the_build_method_names_every_capability_shipped_for_it():
    """A capability the method never names is unreachable, however well it is tested.

    This file's docstring already records the shape: `coyomap reconcile` shipped fully working and
    fully tested and ran ZERO times across four measured builds, while every one of them hand-wrote
    the file it generates. Check (b) tests one direction — a flag the method names is accepted.
    This is the other direction, for the capabilities added because a build could not do without
    them, and it is the direction that bites.
    """
    method = (REPO_ROOT / "method.md").read_text(encoding="utf-8")
    for phrase, why in (
        ("--expect", "grounding lint cannot see a batch that produced no file without it"),
        ("ADDED SINCE THE PIN", "the post-pin claims were hand-diffed in python for want of this"),
        ("REFUTED BUT NOT SUPERSEDED", "two refuted claims shipped in a map because nobody read it"),
        ("NOTE FACTS", "a note said 'Eighteen skeptics' of a build that dispatched 17"),
        ("--note-file", "a ~1,900-character note was retyped inline three times"),
    ):
        assert phrase in method, f"method.md never names `{phrase}` — {why}"

    contracts = [p for p in (REPO_ROOT / "method" / "templates").glob("*-contract.md")
                 if "lint-fragment" in p.read_text(encoding="utf-8")]
    assert contracts, "no contract tells an agent to self-check — the fixture is wrong"
    for p in contracts:
        assert "anchor drift" in p.read_text(encoding="utf-8"), (
            f"{p.name} tells an agent to lint and never says the verdict now carries a drift count")


def test_every_map_section_the_validator_checks_is_in_the_BUILD_ORDER():
    """A section documented but never SEQUENCED is a section no build authors.

    T2b (interfaces) shipped with its element definition, its checks, its screens and its model
    reference — and with no step in `method.md`'s build order saying who writes it or when. The first
    real build after it landed produced ZERO interfaces on a map with 13 external systems and 249
    ways in: the dependency worker correctly refused (it sees one slice and cannot group a surface),
    wrote a note that the field was the lead's, and no step ever sent the lead back. Documenting WHAT
    a thing is, without saying WHEN it is authored, is the gap this pins."""
    prose = (REPO_ROOT / "method.md").read_text(encoding="utf-8")
    order = prose[prose.index("**Build order (internal)"):]
    order = order[:order.index("**Pre-index (structural input).**")]
    for table in ("T1", "T2", "T2b", "T3", "T4", "T5", "T6"):
        assert table in order, f"{table} is documented but never sequenced in the build order"


def test_the_build_and_test_pipeline_is_kept_out_of_the_entry_points_at_harvest():
    """T2b already says the pipeline that builds and tests the product is not a product interface.
    That rule reaches the agent that GROUPS surfaces and nobody else, so one live map harvested its
    test runners, type checker, icon generators and local start/stop scripts as ways in, grouped 32
    of them into a 36-way "Command line" surface, and then drew 31 "no use case" advisories on rows
    that were never product behaviour. 15 of them already had a `run_commands` row citing the same
    `path:line`, so the map recorded the same command twice.

    The cut has to be stated where the rows are MINTED, and a harvest agent reads its contract,
    never method.md — so both files carry it or neither does. The anti-delete clause is pinned with
    it: a rule that says a row does not belong here, without naming where it does belong, is read as
    permission to drop the command from the map entirely."""
    # Whitespace-flattened: both files wrap these clauses across lines, and a raw substring search
    # would pass or fail on where the line happened to break.
    def flat(path: Path) -> str:
        # Strip the blockquote marker first: the contract is one long `> ` quote, and joining on
        # whitespace alone leaves a stray `>` inside every clause that wraps across lines.
        lines = [ln[2:] if ln.startswith("> ") else ln.lstrip(">")
                 for ln in path.read_text(encoding="utf-8").splitlines()]
        return " ".join(" ".join(lines).split())

    method = flat(REPO_ROOT / "method.md")
    contract = flat(REPO_ROOT / "method" / "templates" / "harvest-contract.md")
    for name, text in (("method.md", method), ("harvest-contract.md", contract)):
        assert "acts on the DEPLOYED product" in text, (
            f"{name} no longer states the T4 cut, or no longer states it as a test about what the "
            f"command ACTS ON")
        assert "Being a test exempts nothing" in text, (
            f"{name} lost the tie-breaker. The first draft banned a test outright AND said what the "
            f"command acts on decides; a release smoke test against the live site satisfies both, "
            f"and two fresh agents each dropped that row and named the pair")
        assert "is a WRITE, not a decision" in text, (
            f"{name} states the cut without making the move an obligation. The first wording — "
            f"'Move it, never drop it' as a closing clause — did not hold: 11 of the 36 command "
            f"files the previous map carried as ways in landed in NEITHER array on the first build "
            f"under the rule, the backend lint command among them")
        assert "count" in text and "moved" in text, (
            f"{name} no longer asks the agent to COUNT what it moved. A row that was never written "
            f"leaves no trace, so the count is the only thing that makes the second half visible")
        # The three cuts, each one a row a partial run got wrong.
        assert "is not a NEW entry point" in text or "is not a NEW way in" in text, (
            f"{name} lost the cut for a command that merely CALLS one of the product's own "
            f"addresses — without it a caller is minted as a duplicate of the address")
        assert "wrapper and the command it wraps" in text, (
            f"{name} lost the wrapper cut — two readers then disagree on the row count")
        assert "declares for ITSELF" in text, (
            f"{name} lost the cut for what a container declares for itself — those produced 2 of "
            f"one run's 9 rows")
        assert "a command wherever it is written down" in text, (
            f"{name} lost the guard on that cut. Read broadly it eats a real deploy command written "
            f"as a comment inside the compose file, which on one live map was its ONLY launch")
        assert "what was there BEFORE the command ran" in text, (
            f"{name} lost the precedence line. Both sides fire on a dev launcher whose stack a "
            f"public tunnel exposes, and on a deploy that builds an image and replaces the site")
        assert "Reading" in text and "counts" in text, (
            f"{name} no longer says whether reading live data counts")
    # The destination is named in each file's own vocabulary: the lead's prose says T3, the
    # harvesting agent's contract says the array it actually authors.
    assert "T3 row and only a T3 row" in method
    assert "`run_commands` row" in contract, (
        "the harvest contract no longer names the array a moved command lands in, so the agent is "
        "told where a row does NOT belong and not where it does")
    # …and the invitation that produced the rows no longer offers a bare "a command".
    assert "a command that acts on the running product" in contract


def test_the_app_shell_routes_have_a_surface_to_belong_to():
    """The "every way in belongs to a surface" advisory fired on both live maps with no fix that
    would ever satisfy it: the built-asset route and the single-page catch-all were treated as
    plumbing that could belong nowhere. Neither carries a `kind` of its own, so no filter could
    exclude them either. A check nobody can clear is a check people stop reading.

    Both halves are pinned. method.md must say where the two rows GO, and the validator's plumbing
    set must not grow a claim that they belong nowhere: the old comment there said they "can never
    belong to one", which is what sent the advisory into a loop it could not leave."""
    method = " ".join((REPO_ROOT / "method.md").read_text(encoding="utf-8").split())
    assert "belong to the web surface they serve" in method, (
        "method.md no longer says where the built-asset route and the single-page catch-all go, so "
        "the advisory that flags them has no fix that satisfies it")
    guard = (REPO_ROOT / "tools" / "coyomap"
             / "validate_model.py").read_text(encoding="utf-8")
    at = guard.index("_PLUMBING_EP_KINDS = frozenset(")
    note = " ".join(guard[at:at + 1400].split())
    assert "can never belong to one" not in note or "used to name them here was the defect" in note, (
        "the plumbing note claims the app-shell routes can belong to no surface again — that claim "
        "is what method.md's T2b now contradicts")


def test_the_absence_of_an_outside_edge_is_reported_not_silent():
    """The other half of the same bug. Every interface check is gated on `m.interfaces` being
    non-empty — correct, since they need one to check — which made a WHOLLY ABSENT section the one
    state nothing said a word about. A half-authored section was flagged; a missing one was silent."""
    from coyomap.model import Dep, EntryPoint, ProjectModel
    from coyomap.validate_model import _check_interfaces
    m = ProjectModel(title="T", goal="G")
    m.deps = [Dep(id="D1", name="Stripe", kind="service", type="payments")]
    m.entry_points = [EntryPoint(id="EP1", kind="http-route", activation="external",
                                 source="a.py:1")]
    _problems, warnings = _check_interfaces(m)
    assert any("No interfaces recorded" in w for w in warnings)
    # …and a product that genuinely has no outside edge is not nagged forever.
    m.deps, m.entry_points = [], []
    assert not _check_interfaces(m)[1]


#: Id-prefix registries that DELIBERATELY list only some of the vocabulary, and why. A site not here
#: must carry every prefix in `ID_ARRAYS`. Adding a new element type then fails this test at every
#: table that forgot it — which is the list an adversarial review had to hand over by hand when
#: `interfaces` was added, one prefix at a time, and two sites still slipped through afterwards.
PARTIAL_ID_REGISTRIES: dict[tuple[str, frozenset[str]], str] = {
    ("coyomap/grammar.py", frozenset({"BLK", "BR", "CAP", "HP", "R", "SF"})):
        "_STEP_ENDPOINT_ID: a flow STEP endpoint is a backbone element or a surface — never a "
        "capability, a happy-path step, a sub-flow or a role (a role is classified by is_role_id, "
        "separately, and teaching this one `R` would blank the actor-attribution check)",
    ("coyomap/records.py", frozenset({"BLK", "BR", "D", "S", "SD", "SF"})):
        "ID_KEY: the adjudication vocabulary — only the families that HAVE a recordable advisory",
    ("coyomap/records.py", frozenset({"D", "S", "SD"})):
        "BALANCE_KEY: ID_KEY plus `BLK`, `BR` and `SF`, for the 'Balance exceptions' family alone — "
        "the granularity checks adjudicate a thin block, a rule in no block and a "
        "single-reference sub-flow, none of which ID_KEY can key. Its own key rather than a wider "
        "ID_KEY, for the reason IFACE_KEY states one entry down",
    ("coyomap/records.py", frozenset({"BLK", "BR", "D", "S", "SD"})):
        "IFACE_KEY: ID_KEY plus `SF`, for the 'Interface exceptions' family alone. Shared machinery "
        "can carry a step naming a pipe, and the edit goes on the SUB-FLOW under its own id, so that "
        "family must be able to adjudicate one. Its own key rather than a wider ID_KEY, which would "
        "let every other family adjudicate a sub-flow it has no check for",
    ("coyomap/impact_ripple.py", frozenset({"R"})):
        "_ID_RE: change-impact targets. A ROLE carries no anchor of its own (only a relation's "
        "grant line does), so it is never a ripple target",
    # idOf and the broker-diagram binder both parse ids out of DRAWN mermaid node ids. A capability,
    # a rule, a role and a sub-flow are drawn as no such box; the binder additionally draws no
    # happy-path step, which is why the two gaps differ by `HP`.
    ("coyomap/viewer/viewer.js", frozenset({"BLK", "BR", "CAP", "R", "SF"})): "idOf",
    ("coyomap/viewer/viewer.js", frozenset({"BLK", "BR", "CAP", "HP", "R", "SF"})): "broker binder",
}


def _id_registry_sites() -> dict[str, set[str]]:
    """Every literal in tools/ that enumerates id prefixes — a regex alternation or a prefix table.

    Discovered, not listed: a registry nobody remembered to add to a hand-written list is exactly the
    failure this guards, so the test must find the sites itself."""
    from coyomap.model import ID_ARRAYS
    known = set(ID_ARRAYS.values())
    out: dict[str, set[str]] = {}
    for path in sorted([*(TOOLS.rglob("*.py")), *(TOOLS.rglob("*.js"))]):
        rel = path.relative_to(TOOLS.parent).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if line.lstrip().startswith(("#", "//", "*")):
                continue                                  # a comment ABOUT a registry is not one
            if "\\d+" not in line:
                continue   # a REGISTRY writes `\\d+` after the prefix; prose that lists them does not
            found = set(re.findall(r"\b(CAP|BLK|BR|SD|SF|EP|UC|HP|C|D|E|I|R|S)\b", line))
            inside = set(re.findall(r"\[([A-Z]+)\]", line))          # a char class: [CDEIRS]
            found |= {c for grp in inside for c in grp}
            if len(found & known) >= 6:
                out[f"{rel}:{n}"] = found & known
    return out


def test_every_id_prefix_registry_carries_the_whole_vocabulary():
    """A new element type is registered in ~16 hand-written tables, and one missed is SILENT: a
    prose ref dropped on merge, a dump that answers "unknown", an edit that ripples nowhere.

    Each site either carries every `ID_ARRAYS` prefix or says in `PARTIAL_ID_REGISTRIES` why it does
    not. This is the list that had to be assembled by hand when `interfaces` landed."""
    from coyomap.model import ID_ARRAYS
    known = set(ID_ARRAYS.values())
    gaps = []
    for site, found in _id_registry_sites().items():
        if found == known:
            continue
        if (site.rsplit(":", 1)[0], frozenset(known - found)) in PARTIAL_ID_REGISTRIES:
            continue
        gaps.append(f"{site} carries {len(found)}/{len(known)}, missing {sorted(known - found)}")
    assert not gaps, (
        "id-prefix registr(y/ies) missing part of the vocabulary — add the prefix, or record the "
        "site in PARTIAL_ID_REGISTRIES with the reason it is partial:\n  " + "\n  ".join(gaps))


def test_every_populated_map_section_reaches_the_rendered_view():
    """The committed `project-map.md` is the half of the map a person reads IN THE REPO. A section
    can exist in the model, be checked by `validate`, draw its own tab in the viewer, and be missing
    from that file — `interfaces` shipped exactly like that, and the file carried 23 sections and no
    outside edge at all until someone opened it.

    Runtime, not a grep: it renders the repo's own map and looks for each list's first row in the
    output. A `m.interfaces` mentioned only in a comment would satisfy a grep and fail this."""
    import dataclasses
    import os

    from coyomap.model import ProjectModel, load_model_path
    from coyomap.views import model_to_markdown

    # This test READS THE CLONE'S OWN MAP on purpose, which `resolve_map_path` refuses without the
    # opt-in — the refusal exists because two builds reached that map by accident after a `cd`.
    # Setting it here is the same statement of intent a deliberate self-map run makes.
    os.environ["COYOMAP_SELF_MAP"] = "1"
    try:
        m = load_model_path(REPO_ROOT / ".coyomap" / "project-map.json")
    finally:
        os.environ.pop("COYOMAP_SELF_MAP", None)
    md = model_to_markdown(m)
    #: The fields a row can be FOUND BY in the rendered table, most identifying first. An entry
    #: point renders no id (the T4 table is Kind | Trigger | Code entity | …), so it is found by its
    #: trigger — which is the point: this asks whether the ROWS reach the page, not their ids.
    keys = ("id", "name", "term", "key", "unit", "signal", "action", "surface", "uc", "heading",
            "statement", "title", "trigger", "source")
    gaps = []
    for f in dataclasses.fields(ProjectModel):
        if not str(f.type).startswith("list["):
            continue
        rows = getattr(m, f.name)
        if not rows:
            continue                      # an empty list renders nothing, correctly
        found = [v for k in keys if isinstance(v := getattr(rows[0], k, None), str) and len(v) > 2]
        if found and not any(v in md for v in found):
            gaps.append(f"{f.name} ({len(rows)} row(s)) — nothing of its first row is on the page")
    assert not gaps, (
        "map section(s) the renderer never puts in project-map.md — the committed half of the map "
        "is missing them:\n  " + "\n  ".join(gaps))


# --- rules every fan-out agent needs, in every contract that dispatches one -------------------
# Both of these lived in exactly one contract while applying to all five, and both were measured
# failing on the 2026-08-29 mcpolis build: 71 of 101 sub-agent lint runs were narrowed by a pipe
# (the rule was in `gapfill-contract.md` alone), and one trace agent opened the previous archived
# map nine times (the rule was in `method/dispatch.md`, which only the LEAD reads).

_AGENT_CONTRACTS = ("harvest-contract.md", "trace-contract.md", "rules-contract.md",
                    "skeptic-contract.md", "gapfill-contract.md", "tests-contract.md")


def _contract_agent_half(name: str) -> str:
    from coyomap.contract import agent_half
    from pathlib import Path as _P
    root = _P(__file__).resolve().parent.parent
    return agent_half((root / "method" / "templates" / name).read_text(encoding="utf-8"))


def test_every_agent_contract_forbids_narrowing_its_own_lint_output():
    missing = [n for n in _AGENT_CONTRACTS
               if "do not pipe it through" not in _contract_agent_half(n).lower()]
    assert not missing, (
        f"the anti-narrowing rule is missing from {missing}. It sat in gapfill-contract.md alone "
        f"across two builds; the second scored 71 of 101 sub-agent lint runs narrowed.")


def test_every_agent_contract_forbids_opening_a_previous_map():
    missing = [n for n in _AGENT_CONTRACTS
               if "do not open a previous map" not in _contract_agent_half(n).lower()]
    assert not missing, (
        f"the independence rule is missing from {missing}. It lives in method/dispatch.md, which "
        f"only the lead reads, and a trace agent opened `.coyomap/dev-rebuilds/` nine times.")


def test_the_skeptic_contract_sends_a_reader_to_a_guards_callers():
    """Reading the guard line alone confirmed a guard its only caller switches off, 2 votes to 1."""
    half = _contract_agent_half("skeptic-contract.md").lower()
    assert "call site" in half and "caller" in half, half[-600:]


# --- an escape must survive the merge the tool itself advises (adversarial review, 2026-09-02) ----
# `recorded_line_warnings` tells the operator to write each reason ONCE and name every element it
# answers on that line. The id-keyed escapes read the line with a free-text PREFIX test, which reads
# one key per line and drops every key on a merged list — so a record written on the tool's own
# advice silently stopped adjudicating, with nothing saying so.

def _map_with_record(heading: str, body: str):
    from coyomap.model import ExtraSection, ProjectModel
    m = ProjectModel(title="t", goal="g")
    m.extras = [ExtraSection(heading=heading, body=body)]
    return m


def test_a_MERGED_balance_record_adjudicates_every_key_on_the_line():
    from coyomap import records
    m = _map_with_record("Balance exceptions",
                         "- SF3, SF9, BLK2, BR7: one reason, four elements\n")
    keys = records.recorded_keys(m, "balance exceptions")
    assert {"SF3", "SF9", "BLK2", "BR7"} <= keys, keys


def test_a_MERGED_naming_record_adjudicates_every_key_on_the_line():
    from coyomap import records
    m = _map_with_record("Naming exceptions", "- D3, D7, D9: nothing they do reveals a role\n")
    assert {"D3", "D7", "D9"} <= records.recorded_keys(m, "naming exceptions")




# --- the wrong-map guard covers every door (adversarial review, 2026-09-02) -----------------------
# The guard shipped on 4 readers of ~12, while `method.md` told the lead it "catches the verbs".
# `audit`, `balance`, `anchor-drift`, `grounding` and `context` all read a map directly, and
# `assemble` WRITES one — the destructive half of the incident the guard exists for.

def test_every_map_reader_goes_through_the_guard():
    """A guard on one of two doors is not a guard. This is a source scan on purpose: the failure is
    a NEW reader added later that reads the file itself, which no runtime test would notice."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "tools" / "coyomap"
    raw_read = re.compile(r"load_model\(\s*(?:Path\()?[\w.]+\)?\.read_text\(")
    # The VIEWER is exempt, by design. `coyomap serve` displays every registered project INCLUDING
    # coyomap's own, and reading your own map to draw it is the normal case there, not an accident.
    # The guard exists for BUILD verbs, where the map being read is supposed to be the analysed
    # repo's and a `cd` can silently make it the tool's.
    exempt_dirs = {"viewer"}
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if set(path.relative_to(root).parts[:-1]) & exempt_dirs:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # `resolved` is the name `resolve_map_path` returns into — the guard already ran.
            if raw_read.search(line) and "resolve_map_path" not in line and "resolved." not in line:
                offenders.append(f"{path.relative_to(root)}:{n}: {line.strip()[:80]}")
    assert not offenders, (
        "map read(s) bypassing `resolve_map_path` — a build whose shell folder drifted into the "
        "clone reads coyomap's own map through these and gets a healthy answer about the wrong "
        "product:\n  " + "\n  ".join(offenders))


def test_the_refusal_is_one_line_at_every_door_not_a_traceback():
    """`ModelError` subclasses `ValueError`, so a per-command handler could not catch the refusal
    without swallowing schema errors — and a dozen `main`s would each have to grow one. `cli.py`
    catches `WrongMapError` once."""
    import io, contextlib, os
    from coyomap import cli
    was = os.environ.pop("COYOMAP_SELF_MAP", None)
    try:
        for argv in (["dump", ".coyomap/project-map.json"],
                     ["balance", ".coyomap/project-map.json"],
                     ["validate", ".coyomap/project-map.json"]):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(argv)
            assert code == 1, argv
            assert err.getvalue().lstrip().startswith("ERROR: refusing to read"), (argv, err.getvalue()[:200])
            assert "Traceback" not in err.getvalue(), argv
    finally:
        if was is not None:
            os.environ["COYOMAP_SELF_MAP"] = was


def test_a_deliberate_self_map_is_still_allowed_at_every_door():
    import io, contextlib, os
    from coyomap import cli
    os.environ["COYOMAP_SELF_MAP"] = "1"
    try:
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            assert cli.main(["dump", ".coyomap/project-map.json", "--id", "C1"]) == 0
    finally:
        os.environ.pop("COYOMAP_SELF_MAP", None)


# --- the closing verb has to be REACHABLE (build review, 2026-09-02) ------------------------------
# `coyomap ship` ran ZERO times on a build that then hand-typed its thirteen steps over 57 turns.
# It was never avoided for a bad reason: it was named once, in a document read 540 turns earlier and
# never reopened, and sat on help line 62 under the lead's own `head -60`.

def test_ship_is_in_the_first_lines_of_the_help():
    """A build reads `coyomap --help | head -60`. That is a fact about how it reads, not a thing to
    argue with."""
    from coyomap.cli import USAGE
    lines = USAGE.splitlines()
    at = next(i for i, l in enumerate(lines) if l.startswith("  ship "))
    assert at < 20, f"`ship` is at help line {at + 1}; a `head -60` reader must meet it"


def test_the_report_the_note_is_written_from_names_the_closing_verb():
    """`grounding report` is where the lead stands at the start of the close. A build follows the
    `Next:` lines the tools print — and none of them said `ship`."""
    import io, contextlib, json, tempfile
    from pathlib import Path
    from coyomap.grounding import main
    with tempfile.TemporaryDirectory() as td:
        wl = Path(td) / "w.json"
        wl.write_text(json.dumps({"worklist": [{"claim": "c1"}]}), encoding="utf-8")
        v = Path(td) / "v.json"
        v.write_text(json.dumps({"grounding": [
            {"claim": "c1", "grounded": True, "evidence": "a.py:1", "skeptic": "s"}]}),
            encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            assert main(["report", "--worklist", str(wl), "--verdicts", str(v)]) == 0
    assert "Next: coyomap ship" in out.getvalue(), out.getvalue()[-300:]


def test_the_closing_step_list_carries_no_pasteable_commands():
    """The thirteen steps used to sit as ready-to-paste lines directly under "…and `coyomap ship`
    RUNS it", and that is what the build copied. A reference must not read as a script."""
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "method.md").read_text(encoding="utf-8")
    block = text[text.index("Ordering — ONE sequence"):]
    block = block[:block.index("13. commit the map")]
    # The two `ship` invocations are the point of the block and stay runnable; nothing else does.
    runnable = [l.strip() for l in block.splitlines()
                if "coyomap " in l and "ship" not in l and l.strip().startswith(("coyomap", "."))]
    assert not runnable, f"pasteable alternatives under the ship paragraph: {runnable}"


def test_the_skeptic_contracts_worked_example_is_not_a_live_repos_code():
    """The caller-discipline example used to be one mapped repo's own guard, identifiers and all;
    every skeptic of that repo was handed the refutation the build then counted as found three
    times independently. The example stays, as a shape; the repo's names do not."""
    text = (REPO_ROOT / "method" / "templates" / "skeptic-contract.md").read_text(encoding="utf-8")
    assert "A guard's truth lives at its CALLERS" in text
    for real in ("allow_in_cloud", "settings.mode", "DevStubOAuthProvider"):
        assert real not in text, real
