#!/usr/bin/env python3
"""Land a worktree branch on main: merge main in, run the gates, fast-forward main — and again if
main moved meanwhile. FOR SOMEONE WORKING ON COYOMAP in a git worktree, not for users.

Run it with `make land` from inside the worktree. The order is the one that keeps every conflict
inside the checkout nobody else is typing in:

  1. `git merge main` INTO the worktree branch. A conflict stops here with the files named:
     resolve, commit, run again. The merge is left in place, never aborted.
  2. The full gates on the merge result — a COMMITTED tree, because the checks that read the
     working tree fail on a mid-merge one.
  3. `git merge --ff-only <branch>` run FROM the main checkout, so its ref, index and files move
     together. Moving the ref alone (`update-ref`) leaves that folder's files behind, and its
     `git status` then shows the landed work as deletions.
  4. Main moved while the gates ran? Six minutes is long enough: it moved twice on 2026-09-12,
     once into the very file being landed. Back to step 1, bounded by --attempts.

KNOWN FAILURES. `tests/known-failures.txt` lists the tests that already fail on main and are being
fixed elsewhere, one pytest test id per line, then ` # ` and why it is there. The gates skip exactly
those (pytest `--deselect`, through PYTEST_ADDOPTS, so any gate command that runs pytest honours
it). Then the listed tests run alone: one that passes stops the landing until its line is removed,
so the list only ever shrinks to the truth. A line that is not a single test (no `::`), names a
file that does not exist, or gives no reason is refused before anything runs: a whole file
skipped by a typo is how a list like this would hide a new failure.

Usage: land.py [--target main] [--attempts 3] [--gates "<shell command>"] [--python <path>]
               [--known-failures tests/known-failures.txt]
  --gates replaces the gate command (the tests pass `true`); the default is `make gates` with the
  main checkout's venv and this worktree's tools on PYTHONPATH, which is what a worktree needs.
  --python is the interpreter that re-runs the known failures (default: the main checkout's venv).
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

VIEWER_DIR = "tools/coyomap/viewer/"
KNOWN_FAILURES = "tests/known-failures.txt"
_PASSED = re.compile(r"^PASSED (\S.*?)\s*$")   # a pytest `-rA` summary line for a test that passed


class LandError(Exception):
    """Why landing stopped, and the exit code that says so: 1 preflight, 2 conflict, 3 gates,
    4 the main checkout refused the fast-forward, 5 main kept moving, 6 the known-failures list is
    out of date (a listed test passes, or a line is malformed)."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def git_out(*args: str, cwd: Path) -> str:
    done = git(*args, cwd=cwd)
    if done.returncode != 0:
        raise LandError(f"git {' '.join(args)} failed: {done.stderr.strip()}", 1)
    return done.stdout.strip()


def main_checkout(repo: Path) -> Path:
    """The first entry of `git worktree list` is the main worktree: the folder this one branched from."""
    first = git_out("worktree", "list", "--porcelain", cwd=repo).splitlines()[0]
    if not first.startswith("worktree "):
        raise LandError(f"cannot read the worktree list: {first!r}", 1)
    return Path(first[len("worktree "):])


def preflight(repo: Path, target: str) -> tuple[str, Path]:
    """The branch to land and the main checkout to land it in — or the reason nothing can start."""
    branch = git_out("branch", "--show-current", cwd=repo)
    if not branch:
        raise LandError("not on a branch (detached HEAD)", 1)
    if branch == target:
        raise LandError(f"on {target} itself; land runs from a worktree branch", 1)
    if git_out("status", "--porcelain", cwd=repo):
        raise LandError("this worktree has uncommitted changes; commit them first", 1)
    main = main_checkout(repo)
    if main.resolve() == repo.resolve():
        raise LandError("this is the main checkout, not a worktree", 1)
    if git_out("branch", "--show-current", cwd=main) != target:
        raise LandError(f"the main checkout is not on {target}", 4)
    return branch, main


def merge_target_in(repo: Path, target: str) -> bool:
    """Merge the target into the branch. True when HEAD moved. A conflict stops with the files
    named and the merge left in place for the person to resolve."""
    before = git_out("rev-parse", "HEAD", cwd=repo)
    done = git("merge", "--no-edit", target, cwd=repo)
    if done.returncode != 0:
        conflicted = git_out("diff", "--name-only", "--diff-filter=U", cwd=repo).splitlines()
        detail = "\n  ".join(conflicted) if conflicted else done.stderr.strip()
        raise LandError(f"merging {target} in stopped on conflicts — resolve them in this worktree, "
                        f"commit, and run again:\n  {detail}", 2)
    return git_out("rev-parse", "HEAD", cwd=repo) != before


@dataclass(frozen=True)
class KnownFailure:
    test: str      # a pytest test id: `tests/test_x.py::test_name`
    why: str       # the reason it is on the list


def read_known_failures(repo: Path, rel: str) -> list[KnownFailure]:
    """The known-failures list as it stands in this checkout (after main was merged in, so a list
    main carries counts). No file is an empty list. A malformed line stops landing with its number."""
    path = repo / rel
    if not path.is_file():
        return []
    found: list[KnownFailure] = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        test, sep, why = line.partition(" # ")
        test, why = test.strip(), why.strip()
        file_part = test.split("::", 1)[0]
        if not sep or not why:
            raise LandError(f"{rel} line {n}: say why the test is listed, after ' # '", 6)
        if "::" not in test:
            raise LandError(f"{rel} line {n}: {test!r} is not one test; a whole file would be skipped", 6)
        if not (repo / file_part).is_file():
            raise LandError(f"{rel} line {n}: {file_part} does not exist", 6)
        found.append(KnownFailure(test, why))
    return found


def gate_env(repo: Path, known: list[KnownFailure]) -> dict[str, str]:
    """The environment the gates run in: this worktree's packages first, and every known failure
    deselected through PYTEST_ADDOPTS, kept after whatever the caller already set there."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "tools"), str(repo / "eval" / "tools")])
    skips = " ".join(f"--deselect {shlex.quote(k.test)}" for k in known)
    if skips:
        env["PYTEST_ADDOPTS"] = " ".join(part for part in (env.get("PYTEST_ADDOPTS", ""), skips) if part)
    return env


def run_gates(repo: Path, main: Path, command: str | None, known: list[KnownFailure],
              known_rel: str = KNOWN_FAILURES) -> None:
    """The gates on the tree as it stands, output streamed. The exit code decides, never the banner."""
    cmd = command or f"make gates VENV={main / '.venv'}"
    print(f"gates: {cmd}", flush=True)
    if known:
        print(f"gates: skipping {len(known)} known failure(s) listed in {known_rel}", flush=True)
    done = subprocess.run(cmd, cwd=repo, shell=True, env=gate_env(repo, known))
    if done.returncode != 0:
        raise LandError(f"gates failed (exit {done.returncode}); nothing landed", 3)


def passing_tests(pytest_output: str) -> list[str]:
    """The test ids a `pytest -rA` run reports as passed, read off its summary lines."""
    return [m.group(1) for line in pytest_output.splitlines() if (m := _PASSED.match(line.strip()))]


def check_known_failures(repo: Path, python: str, known: list[KnownFailure], rel: str) -> None:
    """Run the listed tests alone, without the deselection. One that passes is fixed, so its line
    must go before anything lands; one that cannot run at all (a typo in its name) stops too."""
    if not known:
        return
    env = gate_env(repo, [])
    env.pop("PYTEST_ADDOPTS", None)
    print(f"known failures: re-running the {len(known)} listed test(s) alone", flush=True)
    done = subprocess.run([python, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider",
                           *[k.test for k in known]], cwd=repo, env=env, capture_output=True, text=True)
    passed = [t for t in passing_tests(done.stdout) if t in {k.test for k in known}]
    if passed:
        raise LandError(f"{len(passed)} known failure(s) now pass; remove them from {rel} and run "
                        "again:\n  " + "\n  ".join(passed), 6)
    if done.returncode not in (0, 1):     # 1 = tests failed, as listed; anything else = they did not run
        tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-5:])
        raise LandError(f"the known failures in {rel} could not be run (pytest exit "
                        f"{done.returncode}):\n{tail}", 6)


def target_moved(repo: Path, target: str) -> bool:
    """Has the target gained commits this branch does not hold?"""
    return git("merge-base", "--is-ancestor", target, "HEAD", cwd=repo).returncode != 0


def fast_forward(main: Path, branch: str) -> bool:
    """Run from the main checkout so ref, index and files move together. False when the target
    moved on since the check (try again); any other refusal stops landing."""
    done = git("merge", "--ff-only", branch, cwd=main)
    if done.returncode == 0:
        return True
    if "fast-forward" in done.stderr.lower():
        return False
    raise LandError(f"the main checkout refused the fast-forward: {done.stderr.strip()}", 4)


def land(repo: Path, target: str, attempts: int, gates_command: str | None,
         python: str | None = None, known_rel: str = KNOWN_FAILURES) -> int:
    branch, main = preflight(repo, target)
    for attempt in range(1, attempts + 1):
        moved = merge_target_in(repo, target)
        print(f"[{attempt}] {target} merged into {branch}: "
              f"{'a new merge commit' if moved else 'already up to date'}", flush=True)
        known = read_known_failures(repo, known_rel)
        run_gates(repo, main, gates_command, known, known_rel)
        check_known_failures(repo, python or str(main / ".venv" / "bin" / "python"), known, known_rel)
        if target_moved(repo, target):
            print(f"[{attempt}] {target} moved while the gates ran; merging it in again", flush=True)
            continue
        old_target = git_out("rev-parse", target, cwd=repo)
        if not fast_forward(main, branch):
            print(f"[{attempt}] {target} moved between the gates and the fast-forward; again", flush=True)
            continue
        head = git_out("rev-parse", "--short", "HEAD", cwd=repo)
        print(f"landed: {target} is at {head} — ref, index and files together", flush=True)
        changed = git_out("diff", "--name-only", f"{old_target}..HEAD", cwd=repo).splitlines()
        if any(f.startswith(VIEWER_DIR) for f in changed):
            print("viewer files landed: the dev server keeps the viewer.js it started with — restart it",
                  flush=True)
        return 0
    raise LandError(f"{target} kept moving through {attempts} attempt(s); nothing landed", 5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", default="main", help="the branch to land on (default: main)")
    parser.add_argument("--attempts", type=int, default=3, help="how often to retry when the target moves")
    parser.add_argument("--gates", default=None, help="shell command to run as the gates (default: make gates)")
    parser.add_argument("--python", default=None,
                        help="interpreter that re-runs the known failures (default: the main checkout's venv)")
    parser.add_argument("--known-failures", default=KNOWN_FAILURES,
                        help=f"the list of tests that already fail on main (default: {KNOWN_FAILURES})")
    args = parser.parse_args(argv)
    try:
        return land(Path.cwd(), args.target, args.attempts, args.gates, args.python, args.known_failures)
    except LandError as exc:
        print(f"land: {exc}", file=sys.stderr, flush=True)
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
