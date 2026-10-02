"""Tests for `tools/break_check.py`, which breaks one behaviour at a time in a scratch copy of the
checkout and says which tests notice.

Each test builds a tiny checkout whose one "test file" is run by a fake pytest written next to it, so
what each break does to each test is known in advance, and no browser starts:
  test_answer  fails when tools/app.js no longer says `answer = 42`
  test_blind   never fails, whatever the break
  test_flaky   fails in a batch, but passes alone, when tools/app.js says `flaky on`
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

BREAK_CHECK = Path(__file__).resolve().parent.parent / "tools" / "break_check.py"

FAKE_PYTEST = '''
import sys
from pathlib import Path

ids, skip = [], False
for a in sys.argv[1:]:
    if skip:
        skip = False
    elif a in ("-p", "-n"):
        skip = True
    elif not a.startswith("-"):
        ids.append(a)
FILE = "tests/test_viewer_fake.py"
ALL = [FILE + "::test_answer", FILE + "::test_blind", FILE + "::test_flaky"]
wanted = [t for i in ids for t in (ALL if i == FILE else [i])]
app = Path("tools/app.js").read_text()
failed = [t for t in wanted
          if (t.endswith("::test_answer") and "answer = 42" not in app)
          or (t.endswith("::test_flaky") and len(wanted) > 1 and "flaky on" in app)]
for t in failed:
    print("FAILED " + t + " - AssertionError")
print(f"{len(failed)} failed, {len(wanted) - len(failed)} passed" if failed else f"{len(wanted)} passed")
sys.exit(1 if failed else 0)
'''


def make_checkout(app: str = "const answer = 42;\n") -> Path:
    """A checkout with history, one source file and one viewer test file, and the fake pytest beside it."""
    root = Path(tempfile.mkdtemp(prefix="break-check-test-"))
    repo = root / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / "tools" / "app.js").write_text(app)
    (repo / "tests" / "test_viewer_fake.py").write_text("# run by the fake pytest\n")
    (root / "fake_pytest.py").write_text(FAKE_PYTEST)
    return repo


def make_breaks_file(repo: Path, breaks: list[dict[str, object]]) -> Path:
    path = repo.parent / "breaks.json"
    path.write_text(json.dumps(breaks))
    return path


def make_break(name: str, old: str, new: str) -> dict[str, object]:
    return {"name": name, "edits": [{"file": "tools/app.js", "old": old, "new": new}]}


def check(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    runner = f"{sys.executable} {repo.parent / 'fake_pytest.py'}"
    return subprocess.run([sys.executable, str(BREAK_CHECK), "--runner", runner, *args],
                          cwd=repo, capture_output=True, text=True)


def test_a_break_a_test_notices_is_named_with_that_test() -> None:
    repo = make_checkout()
    done = check(repo, "--file", "tools/app.js", "--old", "answer = 42", "--new", "answer = 41")
    assert done.returncode == 0, done.stderr
    assert "noticed by test_answer" in done.stdout, done.stdout
    assert "1 of 1 breaks noticed" in done.stdout


def test_a_break_no_test_notices_is_named_and_fails_the_check() -> None:
    repo = make_checkout()
    done = check(repo, "--file", "tools/app.js", "--old", "const", "--new", "let", "--name", "let for const")
    assert done.returncode == 1, done.stderr
    assert "let for const: NOT NOTICED by any test" in done.stdout, done.stdout
    assert "0 of 1 breaks noticed; not noticed: let for const" in done.stdout


def test_a_failure_that_passes_alone_counts_for_nothing() -> None:
    """The unbroken copy still runs, and the break is still not noticed: test_flaky failed in the
    batch for the load, not for the break."""
    repo = make_checkout("const answer = 42; // flaky on\n")
    done = check(repo, "--file", "tools/app.js", "--old", "const", "--new", "let")
    assert done.returncode == 1, done.stderr
    assert "unbroken: " in done.stdout and "NOT NOTICED" in done.stdout, done.stdout


def test_every_break_must_apply_before_any_test_runs() -> None:
    repo = make_checkout()
    breaks = make_breaks_file(repo, [make_break("good", "answer = 42", "answer = 41"),
                                     make_break("typo", "answer = 24", "answer = 41")])
    done = check(repo, "--breaks", str(breaks))
    assert done.returncode == 2
    assert "typo: the text to replace appears 0 times in tools/app.js, not once" in done.stderr, done.stderr
    assert "unbroken" not in done.stdout, "a test ran before every break was known to apply"


def test_text_that_appears_twice_is_refused() -> None:
    repo = make_checkout("const answer = 42; const answer = 42;\n")
    done = check(repo, "--file", "tools/app.js", "--old", "answer = 42", "--new", "answer = 41")
    assert done.returncode == 2
    assert "appears 2 times" in done.stderr, done.stderr


def test_a_red_checkout_stops_the_check() -> None:
    """A test that already fails would look like it noticed every break."""
    repo = make_checkout("const answer = 41;\n")
    done = check(repo, "--file", "tools/app.js", "--old", "const", "--new", "let")
    assert done.returncode == 2
    assert "not green" in done.stderr and "test_answer" in done.stderr, done.stderr


def test_breaks_run_in_order_and_the_count_says_how_many_were_noticed() -> None:
    repo = make_checkout()
    breaks = make_breaks_file(repo, [make_break("caught", "answer = 42", "answer = 41"),
                                     make_break("missed", "const", "let")])
    done = check(repo, "--breaks", str(breaks))
    assert done.returncode == 1, done.stderr
    assert "[1/2] caught: noticed by test_answer" in done.stdout, done.stdout
    assert "[2/2] missed: NOT NOTICED by any test" in done.stdout
    assert "1 of 2 breaks noticed; not noticed: missed" in done.stdout


def test_the_checkout_is_never_touched_and_the_copy_has_no_history() -> None:
    repo = make_checkout()
    done = check(repo, "--keep", "--file", "tools/app.js", "--old", "answer = 42", "--new", "answer = 41")
    assert done.returncode == 0, done.stderr
    assert (repo / "tools" / "app.js").read_text() == "const answer = 42;\n"
    kept = Path(done.stdout.split("kept: ")[1].strip()) / "repo"
    assert not (kept / ".git").exists(), "the copy carries the checkout's history"
    assert (kept / "tools" / "app.js").read_text() == "const answer = 42;\n", "the break was not put back"


def test_a_malformed_breaks_file_stops_the_check() -> None:
    repo = make_checkout()
    breaks = make_breaks_file(repo, [{"name": "no edits"}])
    done = check(repo, "--breaks", str(breaks))
    assert done.returncode == 2
    assert "break 1 needs edits with file, old and new" in done.stderr, done.stderr
