#!/usr/bin/env python3
"""`coyomap scope` — the briefing shown BEFORE any coyomap work starts.

Its whole value is that a user cannot miss two facts: what will be read, and what the map's commit
pin will mean. So the tests here are about what the text SAYS, not about return codes — a silent
success is the failure mode this command exists to remove.

The git-repo builder is shared with `test_source_walk_git` (the scope report is a reading of that
same walk, so a second builder would let the two drift).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from coyomap import validate_analysis
from coyomap.scope import read_pin, scope_report
from test_source_walk_git import make_git_repo, run_git, write


# --- builders -------------------------------------------------------------------
def report(root: Path) -> str:
    return "\n".join(scope_report(root.resolve()))


def make_dirty_repo(tmp: Path) -> Path:
    """A repo whose committed file has an uncommitted edit."""
    root = make_git_repo(tmp)
    (root / "src" / "tracked.py").write_text("def tracked():\n    return 2\n")
    return root


def make_ignore_repo(tmp: Path, ignore: str) -> Path:
    """A repo (one committed file, `src/tracked.py`) whose `.coyomap/.ignore` holds `ignore`."""
    root = make_git_repo(tmp)
    write(root, ".coyomap/.ignore", ignore)
    return root


# --- what will be analyzed ------------------------------------------------------
def test_it_says_where_the_file_list_comes_from():
    with tempfile.TemporaryDirectory() as td:
        text = report(make_git_repo(Path(td)))
        assert "Files come from git" in text
        assert ".gitignore is left out" in text


def test_it_counts_the_files_that_will_be_analyzed():
    with tempfile.TemporaryDirectory() as td:
        root = make_git_repo(Path(td))
        write(root, "src/extra.py")
        assert "2 file(s) will be analyzed" in report(root)


def test_a_gitignored_tree_is_absent_from_the_count():
    with tempfile.TemporaryDirectory() as td:
        root = make_git_repo(Path(td))
        write(root, ".gitignore", "generated/\n")
        write(root, "generated/a.py")
        write(root, "generated/b.py")
        assert "2 file(s) will be analyzed" in report(root)  # tracked.py + .gitignore, not generated/


def test_the_ignore_file_is_reported_per_pattern():
    """A bare total would let an over-broad pattern pass as a number. The pattern that removed
    nothing is named too — the author believes it is describing the tree and it is not."""
    with tempfile.TemporaryDirectory() as td:
        text = report(make_ignore_repo(Path(td), "src/\nnowhere/\n"))
        assert "src/ (removed 1 file(s))" in text
        assert "nowhere/ (removed 0 file(s))" in text
        assert "removed nothing: nowhere/" in text


def test_unusable_ignore_lines_are_named_beside_the_patterns():
    """A line that parses to nothing excludes nothing, so the author believes a tree is out of the
    map that is in it. The briefing is where a build learns that BEFORE it starts, so it names each
    such line, quoted exactly, beside the patterns that did work."""
    with tempfile.TemporaryDirectory() as td:
        text = report(make_ignore_repo(Path(td), "src/\ninternal/  # private runbooks\n/\n"))
        assert "src/ (removed 1 file(s))" in text
        assert "2 unusable line(s), DROPPED" in text
        assert "'internal/  # private runbooks', '/'" in text


def test_an_ignore_file_of_only_unusable_lines_still_gets_its_block():
    """The worst case: every line is unusable, so there is no pattern to list. Gating the block on
    the patterns made this file invisible, which is the exact file the warning exists for."""
    with tempfile.TemporaryDirectory() as td:
        text = report(make_ignore_repo(Path(td), "src/  # the fixture\n"))
        assert "0 file(s) removed by .coyomap/.ignore:" in text
        assert "1 unusable line(s), DROPPED" in text and "'src/  # the fixture'" in text
        assert "1 file(s) will be analyzed" in text     # the line removed nothing, as it says


def test_scope_and_validate_say_the_same_thing_about_unusable_lines():
    """One ignore file, one story: the briefing before the build and validate during it carry the
    same sentence, word for word, so a reader never has to reconcile two descriptions."""
    with tempfile.TemporaryDirectory() as td:
        for i, ignore in enumerate(("src/  # the fixture\n", "src/\n/\n")):
            root = make_ignore_repo(Path(td) / f"case{i}", ignore)
            said = [s for s in validate_analysis.ignore_disclosure(root) if "unusable" in s]
            assert len(said) == 1, said
            assert said[0] in report(root)


def test_a_folder_without_git_says_gitignore_does_not_apply():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "plain"
        (root / "src").mkdir(parents=True)
        (root / "src" / "a.py").write_text("def a():\n    return 1\n")
        text = report(root)
        assert "not a git repository" in text
        assert "cannot be pinned" in text


# --- what the map will be pinned to ---------------------------------------------
def test_a_clean_repo_says_the_map_and_the_commit_match():
    with tempfile.TemporaryDirectory() as td:
        text = report(make_git_repo(Path(td)))
        assert "Your code is committed" in text
        assert "changed but not committed" not in text


def test_uncommitted_code_is_named_with_the_dirty_pin_consequence():
    with tempfile.TemporaryDirectory() as td:
        root = make_dirty_repo(Path(td))
        text = report(root)
        assert "1 file(s) in your code are changed but not committed" in text
        assert "src/tracked.py" in text
        assert "-dirty" in text


def test_coyomap_own_files_do_not_count_as_dirty_code():
    """`.coyomap/` is always in flux — the workflow writes and commits it. Counting it would make
    every single run warn, which is how a warning stops being read."""
    with tempfile.TemporaryDirectory() as td:
        root = make_git_repo(Path(td))
        write(root, ".coyomap/project-map.json", "{}\n")
        assert read_pin(root).dirty == ()
        assert "Your code is committed" in report(root)


def test_an_untracked_source_file_counts_as_dirty_code():
    """It is IN the map (the walk reads it) and in no commit — exactly the state the pin cannot
    describe, so the briefing must raise it."""
    with tempfile.TemporaryDirectory() as td:
        root = make_git_repo(Path(td))
        write(root, "src/brand_new.py")
        assert read_pin(root).dirty == ("src/brand_new.py",)


def test_a_gitignored_file_is_not_dirty_code():
    with tempfile.TemporaryDirectory() as td:
        root = make_git_repo(Path(td))
        write(root, ".gitignore", "scratch/\n")
        run_git(root, "add", "-A")
        run_git(root, "commit", "-qm", "ignore")
        write(root, "scratch/notes.py")
        assert read_pin(root).dirty == ()
