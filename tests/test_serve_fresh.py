#!/usr/bin/env python3
"""Tests for `serve.ensure_fresh` — the map-staleness check: a map edited while the server runs
(a Direct map change, an Accept, a re-balance) must be picked up on the next request instead of
being masked by the per-process view-bundle cache. (Found dogfooding the balance feature: the
viewer kept serving the pre-rebalance mcpolis map until a manual restart.)

Also covers the other staleness, which no cache-drop can fix: an edit to this tool's own Python is
already imported, so the server can only TELL you to restart. `viewer.js`/`viewer.css` need neither —
they are read from disk per request and sent `no-store`.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_serve_fresh.py
    pytest tests/test_serve_fresh.py
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from coyomap.model import Component, ProjectModel, to_canonical_json
from coyomap.viewer import serve as serve_mod
from coyomap.viewer.serve import ensure_fresh, load_project, project_view


# --- builders -------------------------------------------------------------------

def write_map(root: Path, title: str, component_name: str, mtime_ns: int) -> None:
    """Write a minimal map (no git pin needed — the view path never reads git) with a forced
    mtime, so edits are distinguishable regardless of filesystem timestamp granularity."""
    (root / ".coyomap").mkdir(parents=True, exist_ok=True)
    model = ProjectModel(title=title, components=[
        Component(id="C1", name=component_name, purpose="does things")])
    p = root / ".coyomap" / "project-map.json"
    p.write_text(to_canonical_json(model), encoding="utf-8")
    os.utime(p, ns=(mtime_ns, mtime_ns))


def bundle_text(proj) -> str:  # noqa: ANN001 — ViewBundle shape is the viewer's concern, not ours
    return json.dumps(project_view(proj), default=str)


# --- tests ------------------------------------------------------------------------

def test_edited_map_is_served_after_ensure_fresh() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_map(root, title="Old title", component_name="OldBox", mtime_ns=1_000_000_000)
        proj = load_project(str(root))
        assert proj is not None
        assert "OldBox" in bundle_text(proj)           # bundle now cached
        write_map(root, title="New title", component_name="NewBox", mtime_ns=2_000_000_000)
        ensure_fresh(proj)
        assert proj.view is None and proj.tree is None and proj.symbols is None
        assert proj.title == "New title"
        assert "NewBox" in bundle_text(proj) and "OldBox" not in bundle_text(proj)


def test_unchanged_map_keeps_the_cached_bundle() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_map(root, title="T", component_name="Box", mtime_ns=1_000_000_000)
        proj = load_project(str(root))
        assert proj is not None
        first = project_view(proj)
        ensure_fresh(proj)
        assert proj.view is first                      # same object — no rebuild


def test_broken_edit_keeps_serving_the_old_bundle_and_retries() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_map(root, title="T", component_name="Box", mtime_ns=1_000_000_000)
        proj = load_project(str(root))
        assert proj is not None
        first = project_view(proj)
        p = root / ".coyomap" / "project-map.json"
        p.write_text("{ not json", encoding="utf-8")   # caught mid-write / newly invalid
        os.utime(p, ns=(2_000_000_000, 2_000_000_000))
        ensure_fresh(proj)
        assert proj.view is first and proj.title == "T"   # old bundle survives
        write_map(root, title="Fixed", component_name="FixedBox", mtime_ns=3_000_000_000)
        ensure_fresh(proj)                             # mtime stayed stale -> retried and reloaded
        assert proj.title == "Fixed" and "FixedBox" in bundle_text(proj)


def test_missing_file_keeps_the_cached_bundle() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_map(root, title="T", component_name="Box", mtime_ns=1_000_000_000)
        proj = load_project(str(root))
        assert proj is not None
        first = project_view(proj)
        (root / ".coyomap" / "project-map.json").unlink()
        ensure_fresh(proj)
        assert proj.view is first                      # unstat-able -> serve what we have


# --- the stale-PROCESS guard ------------------------------------------------------
# The map-staleness check above cannot help here: an edit to this tool's own Python is already
# imported, so no cache-drop reaches it. A restart is the only fix, and the server's job is to say so.

def set_stale_state(started: int) -> None:
    """Point the guard at a given startup stamp and clear its throttle + report memory."""
    serve_mod._STARTED_STAMP = started
    serve_mod._LAST_STALE_CHECK = 0
    serve_mod._STALE_REPORTED = 0


def test_a_server_running_current_code_says_nothing(capsys) -> None:
    set_stale_state(serve_mod._sources_stamp())
    try:
        assert serve_mod.warn_if_code_changed() is False
        assert capsys.readouterr().err == ""
    finally:
        set_stale_state(serve_mod._sources_stamp())


def test_a_python_edit_since_startup_is_reported_once(capsys) -> None:
    """Once per change, not once per request: a line repeated on every page load is a line nobody
    reads, and this one has to be noticed the first time."""
    set_stale_state(0)          # as if every source were edited after startup
    try:
        assert serve_mod.warn_if_code_changed() is True
        first = capsys.readouterr().err
        assert "running OLD code" in first and "RESTART" in first
        serve_mod._LAST_STALE_CHECK = 0        # defeat the throttle, not the once-per-change memory
        assert serve_mod.warn_if_code_changed() is True
        assert capsys.readouterr().err == "", "the warning repeated for an unchanged source tree"
    finally:
        set_stale_state(serve_mod._sources_stamp())


def test_the_guard_only_walks_the_tree_now_and_then(capsys) -> None:
    """It runs on every project request; a full `rglob` per request would be a real cost."""
    set_stale_state(0)
    try:
        serve_mod.warn_if_code_changed()
        capsys.readouterr()
        calls = 0
        real = serve_mod._sources_stamp

        def counting() -> int:
            nonlocal calls
            calls += 1
            return real()

        serve_mod._sources_stamp = counting
        try:
            for _ in range(5):
                serve_mod.warn_if_code_changed()
        finally:
            serve_mod._sources_stamp = real
        assert calls == 0, f"walked the source tree {calls} extra time(s) inside the throttle window"
    finally:
        set_stale_state(serve_mod._sources_stamp())


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ok — {len(tests)} tests")
