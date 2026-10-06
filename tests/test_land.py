"""Tests for `tools/land.py`, the landing loop for a worktree branch.

Each test builds a throwaway repository: a main checkout with one commit, and a worktree on a branch
off it. The gates are whatever shell command the test passes, so a test can make "the gates" move
main under the script's feet — the case the loop exists for.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

LAND = Path(__file__).resolve().parent.parent / "tools" / "land.py"

DEMO_TESTS = "def test_fails():\n    assert False\n\n\ndef test_passes():\n    assert True\n"


def load_land() -> ModuleType:
    """The script as a module, for the pure helpers; the loop itself is tested end to end below."""
    spec = importlib.util.spec_from_file_location("land_under_test", LAND)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module      # a dataclass resolves its annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


def make_repo() -> tuple[Path, Path]:
    """(main checkout, worktree) — main holds one commit, the worktree's branch `feature` sits on it."""
    root = Path(tempfile.mkdtemp(prefix="land-"))
    main = root / "main"
    main.mkdir()
    run(["git", "init", "-q", "-b", "main"], main)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        run(["git", "config", key, value], main)
    make_commit(main, "a.txt", "one\n", "one")
    worktree = root / "wt"
    run(["git", "worktree", "add", "-q", "-b", "feature", str(worktree)], main)
    return main, worktree


def make_commit(checkout: Path, name: str, text: str, message: str) -> None:
    (checkout / name).write_text(text, encoding="utf-8")
    run(["git", "add", name], checkout)
    run(["git", "commit", "-qm", message], checkout)


def head(checkout: Path) -> str:
    return run(["git", "rev-parse", "HEAD"], checkout).stdout.strip()


def land(worktree: Path, *extra: str, gates: str = "true") -> subprocess.CompletedProcess[str]:
    # Without the caller's PYTEST_ADDOPTS: under `make land` the suite itself runs with the real
    # list's skips there, and the throwaway landing would inherit them.
    env = {key: value for key, value in os.environ.items() if key != "PYTEST_ADDOPTS"}
    return subprocess.run([sys.executable, str(LAND), "--gates", gates, "--python", sys.executable, *extra],
                          cwd=worktree, capture_output=True, text=True, env=env)


def make_known_failures(worktree: Path, *lines: str) -> None:
    """A branch carrying two demo tests (one fails, one passes) and a known-failures list."""
    (worktree / "tests").mkdir(exist_ok=True)
    make_commit(worktree, "tests/check_demo.py", DEMO_TESTS, "demo tests")
    make_commit(worktree, "tests/known-failures.txt", "# listed\n" + "".join(f"{line}\n" for line in lines),
                "known failures")


def test_a_branch_ahead_of_main_lands_and_the_main_checkouts_files_move_with_the_ref() -> None:
    main, worktree = make_repo()
    make_commit(worktree, "b.txt", "two\n", "two")
    done = land(worktree)
    assert done.returncode == 0, done.stderr
    assert head(main) == head(worktree)
    assert (main / "b.txt").read_text() == "two\n"          # the file, not just the ref
    assert run(["git", "status", "--porcelain"], main).stdout == ""


def test_main_that_moved_is_merged_into_the_branch_first_then_landed() -> None:
    main, worktree = make_repo()
    make_commit(worktree, "b.txt", "two\n", "two")
    make_commit(main, "c.txt", "three\n", "three")
    done = land(worktree)
    assert done.returncode == 0, done.stderr
    assert "a new merge commit" in done.stdout
    assert head(main) == head(worktree)
    assert (main / "b.txt").exists() and (main / "c.txt").exists()


def test_a_conflict_stops_with_the_file_named_and_the_merge_left_to_resolve() -> None:
    main, worktree = make_repo()
    make_commit(worktree, "a.txt", "mine\n", "mine")
    make_commit(main, "a.txt", "theirs\n", "theirs")
    before = head(main)
    done = land(worktree)
    assert done.returncode == 2
    assert "a.txt" in done.stderr and "resolve" in done.stderr
    assert head(main) == before
    assert (worktree / ".git").exists()
    assert run(["git", "diff", "--name-only", "--diff-filter=U"], worktree).stdout.strip() == "a.txt"


def test_main_moving_while_the_gates_run_is_merged_in_again_and_then_lands() -> None:
    """The gates command moves main exactly once, the first time it runs."""
    main, worktree = make_repo()
    make_commit(worktree, "b.txt", "two\n", "two")
    marker = worktree / "moved.once"
    gates = f"test -e {marker} || (touch {marker} && git -C {main} commit -q --allow-empty -m moved)"
    done = land(worktree, gates=gates)
    marker.unlink()
    assert done.returncode == 0, done.stderr
    assert "moved while the gates ran" in done.stdout
    assert head(main) == head(worktree)
    assert "moved" in run(["git", "log", "--oneline"], main).stdout


def test_main_that_keeps_moving_gives_up_after_the_attempts() -> None:
    main, worktree = make_repo()
    make_commit(worktree, "b.txt", "two\n", "two")
    done = land(worktree, "--attempts", "2", gates=f"git -C {main} commit -q --allow-empty -m moved")
    assert done.returncode == 5
    assert "kept moving" in done.stderr
    assert not (main / "b.txt").exists()


def test_failing_gates_land_nothing() -> None:
    main, worktree = make_repo()
    before = head(main)
    make_commit(worktree, "b.txt", "two\n", "two")
    done = land(worktree, gates="false")
    assert done.returncode == 3
    assert head(main) == before


def test_a_test_that_failed_under_load_and_passes_alone_does_not_stop_the_landing() -> None:
    """The gates name a failed test, as a page load that timed out on a busy machine does. It passes
    alone, the gates pass once it is deselected, and the landing goes on, naming the test it re-ran."""
    main, worktree = make_repo()
    make_known_failures(worktree)
    gates = ('case "$PYTEST_ADDOPTS" in *test_passes*) true;; '
             '*) echo "FAILED tests/check_demo.py::test_passes - TimeoutError"; false;; esac')
    done = land(worktree, gates=gates)
    assert done.returncode == 0, done.stderr
    assert "passed alone" in done.stdout and "tests/check_demo.py::test_passes" in done.stdout
    assert head(main) == head(worktree)


def test_a_test_that_fails_alone_too_stops_the_landing() -> None:
    main, worktree = make_repo()
    before = head(main)
    make_known_failures(worktree)
    done = land(worktree, gates='echo "FAILED tests/check_demo.py::test_fails - boom"; false')
    assert done.returncode == 3
    assert "fail alone too" in done.stderr and "tests/check_demo.py::test_fails" in done.stderr
    assert head(main) == before


def test_gates_that_fail_again_without_the_rescued_tests_land_nothing() -> None:
    """Whatever else failed in the first run, pyright included, still fails the second, which runs
    everything but the tests that passed alone, and its exit code decides."""
    main, worktree = make_repo()
    before = head(main)
    make_known_failures(worktree)
    done = land(worktree, gates='echo "FAILED tests/check_demo.py::test_passes - TimeoutError"; false')
    assert done.returncode == 3
    assert "failed again" in done.stderr
    assert head(main) == before


def test_a_failed_test_is_read_whole_from_the_summary_even_with_a_space_in_its_id() -> None:
    """A parametrized id holds spaces. Cut at the first one, it named a test pytest could not find,
    and break-check then counted a test that only failed under load as a failure."""
    out = ("FAILED tests/a.py::test_b[x y] - TimeoutError: 30000ms\n"
           "ERROR tests/c.py - ImportError while importing\n"
           "FAILED tests/a.py::test_d\n"
           "FAILED tests/a.py::test_b[x y] - again\n"
           "GATES FAILED (pytest=1 pyright=0)\n")
    assert load_land().failed_tests(out) == ["tests/a.py::test_b[x y]", "tests/c.py", "tests/a.py::test_d"]


def test_a_dirty_worktree_and_the_main_checkout_itself_are_refused() -> None:
    main, worktree = make_repo()
    (worktree / "loose.txt").write_text("x", encoding="utf-8")
    assert land(worktree).returncode == 1
    (worktree / "loose.txt").unlink()
    assert land(main).returncode == 1


def test_a_known_failure_is_skipped_in_the_gates_and_landing_goes_on_while_it_still_fails() -> None:
    main, worktree = make_repo()
    make_known_failures(worktree, "tests/check_demo.py::test_fails # broken on main, fixed elsewhere")
    seen = worktree.parent / "addopts.txt"
    done = land(worktree, gates=f"printenv PYTEST_ADDOPTS > {seen}")
    assert done.returncode == 0, done.stderr
    assert seen.read_text().strip() == "--deselect tests/check_demo.py::test_fails"
    assert "skipping 1 known failure(s)" in done.stdout
    assert head(main) == head(worktree)


def test_a_known_failure_that_now_passes_stops_landing_until_its_line_goes() -> None:
    main, worktree = make_repo()
    before = head(main)
    make_known_failures(worktree, "tests/check_demo.py::test_fails # broken",
                        "tests/check_demo.py::test_passes # was broken, fixed since")
    done = land(worktree)
    assert done.returncode == 6, done.stderr
    assert "now pass" in done.stderr and "tests/check_demo.py::test_passes" in done.stderr
    assert "test_fails" not in done.stderr.split("now pass", 1)[1]
    assert head(main) == before


def test_a_known_failures_line_that_is_not_one_named_test_is_refused_before_the_gates() -> None:
    """A whole file, a line with no reason, a file that is gone: each would skip or hide something
    nobody chose to skip, so each stops landing before any gate runs."""
    for line, message in (("tests/check_demo.py # the whole file", "not one test"),
                          ("tests/check_demo.py::test_fails", "say why"),
                          ("tests/gone.py::test_x # gone", "does not exist")):
        main, worktree = make_repo()
        make_known_failures(worktree, line)
        marker = worktree.parent / "gates.ran"
        done = land(worktree, gates=f"touch {marker}")
        assert done.returncode == 6 and message in done.stderr, (line, done.stderr)
        assert not marker.exists(), line


def test_the_skips_ride_after_any_pytest_options_already_set() -> None:
    module = load_land()
    known = [module.KnownFailure("tests/a.py::test_b[x y]", "why")]
    env = module.gate_env(Path("/repo"), known)
    assert env["PYTEST_ADDOPTS"].endswith("--deselect 'tests/a.py::test_b[x y]'")
    assert module.passing_tests("x\nPASSED tests/a.py::test_b\nFAILED tests/a.py::test_c - boom\n") == [
        "tests/a.py::test_b"]
