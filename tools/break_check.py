#!/usr/bin/env python3
"""Break one behaviour at a time in a scratch copy, and see which tests notice. FOR SOMEONE WORKING
ON COYOMAP, not for users.

A green suite can guard nothing: a test that reads the code's text instead of the screen, or one that
passes for the wrong reason. The review of the Architecture viewer change (2026-10-02) broke 30 new
behaviours one at a time, and no test noticed 13 of them. This script runs that check:

  1. Copy the checkout to a scratch folder, without .git or caches. The checkout is never touched.
  2. Run the tests once on the unbroken copy. A red copy stops here: a test that already fails would
     count as "noticed" for every break.
  3. For each break: replace its text (it must appear exactly once in its file), run the tests,
     re-run each failure alone (browser tests fail at random under load), and put the text back.
  4. Say which tests noticed each break, and which breaks no test noticed.

Every break is applied once before any test runs, so a typo stops the check at once rather than
after twenty minutes of tests.

A breaks file is a JSON list:
  [{"name": "no blue head", "edits": [{"file": "tools/coyomap/viewer/viewer.js",
                                       "old": "<text as it is>", "new": "<text that breaks it>"}]}]
One break can also be given on the command line with --file, --old and --new.

Usage: break_check.py (--breaks FILE | --file PATH --old TEXT [--new TEXT] [--name NAME])
                      [--tests TEST ...] [--runner "COMMAND"] [-n WORKERS] [--keep]
  --tests   default: every tests/test_viewer*.py, plus tests/test_architecture_view.py if present
  --runner  the command that runs pytest; default: the main checkout's .venv python -m pytest,
            with this checkout's tools/ and eval/tools/ on PYTHONPATH
Exit codes: 0 every break noticed, 1 at least one break not noticed, 2 the check could not run.
About 100 seconds per break for the viewer's tests at 6 workers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from land import LandError, main_checkout

#: What the scratch copy leaves out: history, caches, sessions, and anything installed.
SKIP = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".claude", ".venv", "node_modules")
#: A failed test or a collection error in pytest's short summary (`-rfE`).
FAILED_LINE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.M)
PASSED_COUNT = re.compile(r"(\d+) passed")


class BreakCheckError(Exception):
    """Why the check could not run (exit code 2)."""


@dataclass(frozen=True)
class Edit:
    file: str   # relative to the checkout
    old: str    # must appear exactly once in the file
    new: str


@dataclass(frozen=True)
class Break:
    name: str
    edits: list[Edit]


@dataclass(frozen=True)
class Run:
    code: int
    output: str


@dataclass
class Outcome:
    name: str
    noticed_by: list[str] = field(default_factory=list)
    run_broke: bool = False   # pytest could not even collect or start: the break is noticed

    @property
    def noticed(self) -> bool:
        return self.run_broke or bool(self.noticed_by)


def load_breaks(path: Path) -> list[Break]:
    """The breaks a JSON file lists; a malformed entry stops the check before anything runs."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BreakCheckError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise BreakCheckError(f"{path}: expected a non-empty list of breaks")
    out: list[Break] = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise BreakCheckError(f"{path}: break {i} is not an object with a name and edits")
        try:
            edits = [Edit(file=str(e["file"]), old=str(e["old"]), new=str(e["new"])) for e in item["edits"]]
        except (KeyError, TypeError) as exc:
            raise BreakCheckError(f"{path}: break {i} needs edits with file, old and new ({exc})") from exc
        if not edits:
            raise BreakCheckError(f"{path}: break {i} has no edit")
        out.append(Break(name=str(item.get("name") or f"break {i}"), edits=edits))
    return out


def make_copy(repo: Path, where: Path) -> Path:
    copy = where / repo.name
    shutil.copytree(repo, copy, ignore=SKIP, symlinks=True)
    return copy


def apply_break(copy: Path, brk: Break) -> dict[Path, str]:
    """Write the break into the copy and return each touched file's text as it was. Nothing is
    written unless every edit's text appears exactly once."""
    before: dict[Path, str] = {}
    after: dict[Path, str] = {}
    for e in brk.edits:
        path = copy / e.file
        if not path.is_file():
            raise BreakCheckError(f"{brk.name}: there is no file {e.file}")
        if path not in after:
            before[path] = after[path] = path.read_text(encoding="utf-8")
        n = after[path].count(e.old)
        if n != 1:
            raise BreakCheckError(f"{brk.name}: the text to replace appears {n} times in {e.file}, not once")
        after[path] = after[path].replace(e.old, e.new)
    for path, text in after.items():
        path.write_text(text, encoding="utf-8")
    return before


def restore(before: dict[Path, str]) -> None:
    for path, text in before.items():
        path.write_text(text, encoding="utf-8")


#: A test run that takes longer than this is stopped. A break that hangs the tests is noticed.
RUN_LIMIT_S = 3600


def run_tests(runner: list[str], copy: Path, tests: list[str], workers: int) -> Run:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(copy / "tools"), str(copy / "eval" / "tools")])
    spread = ["-n", str(workers)] if workers > 1 and len(tests) > 1 else []
    try:
        done = subprocess.run([*runner, "-q", "-p", "no:cacheprovider", "-rfE", *spread, *tests],
                              cwd=copy, env=env, capture_output=True, text=True, timeout=RUN_LIMIT_S)
    except subprocess.TimeoutExpired:
        return Run(code=124, output=f"the tests ran past {RUN_LIMIT_S} s and were stopped")
    return Run(code=done.returncode, output=done.stdout + done.stderr)


def failed_ids(run: Run) -> list[str]:
    return sorted(set(FAILED_LINE.findall(run.output)))


def failing_alone(runner: list[str], copy: Path, ids: list[str]) -> list[str]:
    """The failures that fail again when run alone. One that passes alone failed for the load."""
    return [t for t in ids if run_tests(runner, copy, [t], 1).code != 0]


def check_unbroken(runner: list[str], copy: Path, tests: list[str], workers: int) -> str:
    """How the unbroken copy did, or the reason the check cannot go on."""
    run = run_tests(runner, copy, tests, workers)
    red = failing_alone(runner, copy, failed_ids(run))
    if red:
        raise BreakCheckError("the unbroken copy is not green, so every break would look noticed: "
                              + ", ".join(red))
    if run.code not in (0, 1):
        raise BreakCheckError(f"the tests did not run on the unbroken copy (exit {run.code}):\n"
                              + run.output[-2000:])
    found = PASSED_COUNT.search(run.output)
    return f"{found.group(1)} passed" if found else "green"


def check_break(runner: list[str], copy: Path, tests: list[str], workers: int, brk: Break) -> Outcome:
    before = apply_break(copy, brk)
    try:
        run = run_tests(runner, copy, tests, workers)
        ids = failed_ids(run)
        if run.code not in (0, 1) and not ids:
            return Outcome(brk.name, run_broke=True)
        return Outcome(brk.name, noticed_by=failing_alone(runner, copy, ids))
    finally:
        restore(before)


def default_tests(repo: Path) -> list[str]:
    tests = sorted(str(p.relative_to(repo)) for p in (repo / "tests").glob("test_viewer*.py"))
    arch = repo / "tests" / "test_architecture_view.py"
    if arch.is_file():
        tests.append(str(arch.relative_to(repo)))
    if not tests:
        raise BreakCheckError("no viewer tests under tests/; name them with --tests")
    return tests


def default_runner(repo: Path) -> list[str]:
    """pytest from the main checkout's venv, which a worktree does not have; this python otherwise."""
    try:
        venv: Path | None = main_checkout(repo) / ".venv" / "bin" / "python"
    except (LandError, OSError, IndexError):
        venv = None
    python = str(venv) if venv is not None and venv.is_file() else sys.executable
    return [python, "-m", "pytest"]


def said(outcome: Outcome) -> str:
    if outcome.run_broke:
        return "noticed: the test run itself broke"
    if outcome.noticed_by:
        return "noticed by " + ", ".join(t.split("::")[-1] for t in outcome.noticed_by)
    return "NOT NOTICED by any test"


def check_all(repo: Path, breaks: list[Break], tests: list[str], runner: list[str], workers: int,
              keep: bool) -> int:
    where = Path(tempfile.mkdtemp(prefix="break-check-"))
    try:
        copy = make_copy(repo, where)
        print(f"copy: {copy}", flush=True)
        for brk in breaks:
            restore(apply_break(copy, brk))
        print(f"unbroken: {check_unbroken(runner, copy, tests, workers)}", flush=True)
        outcomes: list[Outcome] = []
        for i, brk in enumerate(breaks, 1):
            outcomes.append(check_break(runner, copy, tests, workers, brk))
            print(f"[{i}/{len(breaks)}] {brk.name}: {said(outcomes[-1])}", flush=True)
        missed = [o.name for o in outcomes if not o.noticed]
        print(f"{len(outcomes) - len(missed)} of {len(outcomes)} breaks noticed"
              + (f"; not noticed: {', '.join(missed)}" if missed else ""), flush=True)
        return 1 if missed else 0
    finally:
        if keep:
            print(f"kept: {where}", flush=True)
        else:
            shutil.rmtree(where, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--breaks", type=Path, help="a JSON file listing the breaks")
    what.add_argument("--file", help="the file to break, relative to the checkout")
    parser.add_argument("--old", help="with --file: the text to replace, which must appear once")
    parser.add_argument("--new", default="", help="with --file: the text to put instead (default: none)")
    parser.add_argument("--name", default="", help="with --file: a name for the break")
    parser.add_argument("--tests", nargs="+", help="test files or ids to run (default: the viewer's)")
    parser.add_argument("--runner", help="the command that runs pytest (default: the main checkout's venv)")
    parser.add_argument("-n", "--workers", type=int, default=6, help="parallel test workers (default: 6)")
    parser.add_argument("--keep", action="store_true", help="keep the scratch copy and say where it is")
    args = parser.parse_args(argv)
    repo = Path.cwd()
    try:
        if args.breaks is not None:
            breaks = load_breaks(args.breaks)
        elif args.old is None:
            raise BreakCheckError("--file needs --old, the text to replace")
        else:
            breaks = [Break(name=args.name or args.file, edits=[Edit(args.file, args.old, args.new)])]
        tests = args.tests or default_tests(repo)
        runner = shlex.split(args.runner) if args.runner else default_runner(repo)
        return check_all(repo, breaks, tests, runner, args.workers, args.keep)
    except BreakCheckError as exc:
        print(f"break-check: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
