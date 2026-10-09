#!/usr/bin/env python3
"""A map whose pin is behind the code it sits beside says so: `impact_git.pin_lag` counts the
commits since the pin that change the product, and `validate` warns. The 2026-10-09 mcpolis rebuild
was built at 65bb4722 in a worktree and committed 25 commits later with no warning. Real temp git
repos, explicit make_* builders, no fixtures/classes."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path

from coyomap import validate_model
from coyomap.impact_git import pin_lag
from coyomap.model import to_canonical_json

from test_impact import commit, make_model


def make_pinned_repo(root: Path) -> str:
    """One product commit; the map, pinned to it, committed after it. Returns the pin."""
    pin = commit(root, {"svc/a.py": "x = 1\n"}, msg="product")
    write_map(root, pin)
    commit(root, {}, msg="the map")
    return pin


def write_map(root: Path, pin: str) -> Path:
    path = root / ".coyomap" / "project-map.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_canonical_json(make_model(pin)), encoding="utf-8")
    return path


def run_validate(map_path: Path) -> list[str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        validate_model.main([str(map_path), "--json"])
    return json.loads(out.getvalue())["warnings"]


def stale_warnings(map_path: Path) -> list[str]:
    return [w for w in run_validate(map_path) if "the map is pinned to" in w]


def test_a_commit_that_only_touches_the_map_folder_is_not_lag():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pin = make_pinned_repo(root)
        lag = pin_lag(root, pin)
        assert lag is not None and lag.known and lag.commits == 0
        assert stale_warnings(root / ".coyomap" / "project-map.json") == []


def test_validate_warns_when_the_code_moved_past_the_pin():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pin = make_pinned_repo(root)
        commit(root, {"svc/a.py": "x = 2\n"}, msg="more product")
        commit(root, {"svc/b.py": "y = 1\n"}, msg="and more")
        lag = pin_lag(root, pin)
        assert lag is not None and lag.commits == 2
        warns = stale_warnings(root / ".coyomap" / "project-map.json")
        assert len(warns) == 1 and "2 commit(s) past it that change the product" in warns[0], warns


def test_a_pin_the_repo_does_not_have_is_named_and_no_repo_is_silence():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make_pinned_repo(root)
        path = write_map(root, "0123abc")
        warns = stale_warnings(path)
        assert len(warns) == 1 and "not a commit of this repo" in warns[0], warns
    with tempfile.TemporaryDirectory() as td:
        path = write_map(Path(td), "0123abc")
        assert pin_lag(Path(td), "0123abc") is None and stale_warnings(path) == []
