#!/usr/bin/env python3
"""Change mode in a real browser: the viewer compared with a map file on disk, through the Updates list.

The served map is the NEW side; the OLD side is a file on disk named by a `path:` ref, which is what
a temp folder with no git history can offer. The old copy holds one use case the new map lost, and
the new copy renames a use case, inserts a step into its flow, rewords a component's purpose and
moves another component's code line — one change of each kind the screens must tell apart.

Same harness as tests/test_viewer_browser.py: one browser per process, a fresh page per test, JS
errors collected. Explicit make_* builders, no fixtures/classes.
"""
from __future__ import annotations

import json
import tempfile
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from coyomap.viewer.recents import RecentsStore
from coyomap.viewer.serve import Handler, build_projects

from test_viewer_browser import _crumb, _page, _settle, make_served_map

OLD_UC = "Archive an organization"
NEW_NAME = "Sign up and create a workspace"
OLD_NAME = "Sign up and create an organization"
NEW_STEP = "confirms the email the browser sent"


def make_old_map(doc: dict[str, Any]) -> dict[str, Any]:
    """The fixture plus a use case the new map no longer has, with a two-step flow of its own."""
    old = json.loads(json.dumps(doc))
    old["use_cases"].append({"id": "UC99", "name": OLD_UC, "actors": ["R2"], "capability": "CAP1",
                             "trigger_outcome": "An org admin archives an organization nobody uses."})
    old["flows"].append({"uc": "UC99", "title": OLD_UC, "steps": [
        {"n": 1, "src": "R2", "dst": "C15", "phrase": "opens the organization's settings", "where": None},
        {"n": 2, "src": "C15", "dst": "C1", "phrase": "marks the organization archived", "where": None}]})
    return old


def make_new_map(doc: dict[str, Any]) -> None:
    """The served map, edited in place: a rename, an inserted step, a reworded purpose, a moved line."""
    uc = next(u for u in doc["use_cases"] if u["id"] == "UC1")
    uc["name"] = NEW_NAME
    flow = next(f for f in doc["flows"] if f["uc"] == "UC1")
    steps = flow["steps"]
    steps.insert(1, {"n": 2, "src": "R1", "dst": "C15", "phrase": NEW_STEP, "note": "", "where": None,
                     "no_call_site": False, "subflow": None})
    for i, st in enumerate(steps):
        st["n"] = i + 1
    c1 = next(c for c in doc["components"] if c["id"] == "C1")
    c1["purpose"] = c1["purpose"] + " Fast."
    c2 = next(c for c in doc["components"] if c["id"] == "C2")
    c2["source"] = (c2.get("source") or "app/gateway.py:1").rsplit(":", 1)[0] + ":999"


@contextmanager
def _served_pair() -> Iterator[tuple[str, str]]:
    """The server over the edited map, and the old map's path on disk."""
    with tempfile.TemporaryDirectory() as td:
        folder = make_served_map(Path(td), "alpha")
        f = folder / ".coyomap" / "project-map.json"
        doc = json.loads(f.read_text())
        old_path = Path(td) / "old-map.json"
        old_path.write_text(json.dumps(make_old_map(doc)), encoding="utf-8")
        make_new_map(doc)
        f.write_text(json.dumps(doc), encoding="utf-8")
        projects = build_projects([str(folder)])
        slug = next(iter(projects))
        Handler.store = RecentsStore()
        Handler.projects = projects
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}/coyomap/{slug}/", str(old_path)
        finally:
            httpd.shutdown()
            httpd.server_close()


def _file_page(url: str, old_path: str) -> str:
    return f"{url}#v=updates&at=file&cmp=path:{old_path}"


def _marked(url: str, old_path: str, screen: str) -> str:
    return f"{url}#{screen}&cmp=path:{old_path}"


def _text(page: Any, selector: str) -> str:
    return str(page.evaluate(f"() => (document.querySelector({selector!r}) || {{textContent: ''}}).textContent.trim()"))


def _texts(page: Any, selector: str) -> str:
    """Every match's text, joined — a reworded sentence is several struck and marked runs."""
    return str(page.evaluate(f"() => [...document.querySelectorAll({selector!r})].map((e) => e.textContent).join(' ')"))


def _screen_text(page: Any) -> str:
    return str(page.evaluate("() => document.getElementById('diagram').innerText"))


def _hash(page: Any) -> str:
    return str(page.evaluate("() => decodeURIComponent(location.hash)"))


def test_a_link_naming_a_map_file_opens_its_comparison_under_updates_and_keeps_the_file_in_the_address() -> None:
    with _served_pair() as (url, old), _page(_file_page(url, old)) as page:
        _settle(page)
        assert _crumb(page) == "A map file"
        assert "Compared with" in _text(page, ".cmp-head") and old in _text(page, ".cmp-head")
        assert "Stop marking" in _text(page, ".cmp-head"), "a comparison named by the link is marked on the map"
        assert f"cmp=path:{old}" in _hash(page)
        assert not page.js_errors, page.js_errors


def test_the_file_page_lists_each_change_with_its_summary_and_opens_the_box() -> None:
    with _served_pair() as (url, old), _page(_file_page(url, old)) as page:
        _settle(page)
        card = _text(page, '.ecard[data-id="UC1"]')
        assert NEW_NAME in card and "1 added" in card and f"renamed from {OLD_NAME}" in card
        assert "modified" in card, "the card wears the change badge"
        page.click('.ecard[data-id="UC1"]')
        _settle(page)
        assert _crumb(page) == NEW_NAME
        block = _text(page, ".cmpsec")
        assert block.startswith("What changed")
        assert "organization" in _texts(page, ".cmpsec del") and "workspace" in _texts(page, ".cmpsec ins")
        assert NEW_STEP in block and "renumbered" in block
        assert not page.js_errors, page.js_errors


def test_a_removed_box_opens_as_it_was_in_the_old_map_and_shows_no_id() -> None:
    with _served_pair() as (url, old), _page(_file_page(url, old)) as page:
        _settle(page)
        card = _text(page, '.ecard[data-key="removed:UC99"]')
        assert OLD_UC in card and "removed" in card
        page.click('.ecard[data-key="removed:UC99"]')
        _settle(page)
        assert _crumb(page) == OLD_UC
        text = _screen_text(page)
        assert "Not in the current map" in text
        assert "Org admin" in text and "marks the organization archived" in text
        for internal in ("UC99", "R2", "C15", "CAP1"):
            assert internal not in text, f"an id on screen: {internal}"
        assert "at=file" in _hash(page) and "cmp=path:" in _hash(page)
        assert not page.js_errors, page.js_errors


def test_a_moved_code_line_hides_behind_its_filter_and_the_count_follows() -> None:
    with _served_pair() as (url, old), _page(_file_page(url, old)) as page:
        _settle(page)
        assert not page.query_selector('.ecard[data-id="C2"]'), "a moved line is hidden while code links are off"
        assert _text(page, 'button.cmp-filter[data-cls="link"]') == "code links 1", "what is hidden is counted where it is hidden"
        page.click('button.cmp-filter[data-cls="link"]')
        _settle(page)
        assert "code link moved" in _text(page, '.ecard[data-id="C2"]')
        assert not page.js_errors, page.js_errors


def test_every_changed_box_wears_a_badge_on_a_diagram_and_in_a_list_once_marked() -> None:
    with _served_pair() as (url, old), _page(_marked(url, old, "v=container")) as page:
        _settle(page)
        assert page.evaluate("() => document.querySelectorAll('#diagram .diff-badge').length") >= 1, \
            "the subsystem holding the reworded component is badged on the overview"
        page.goto(_marked(url, old, "v=features"))
        _settle(page)
        assert _crumb(page) == "Features"
        assert page.evaluate("() => document.querySelectorAll('#diagram .badge.modified').length") >= 1, \
            "the feature holding the renamed use case says it changed"
        assert not page.js_errors, page.js_errors


def test_stop_marking_drops_the_badges_and_the_link_and_the_file_page_says_so() -> None:
    with _served_pair() as (url, old), _page(_file_page(url, old)) as page:
        _settle(page)
        page.click("button.cmp-stop")
        _settle(page)
        assert "cmp=" not in _hash(page)
        assert "No map file is being compared" in _screen_text(page)
        page.goto(url + "#v=features")
        _settle(page)
        assert not page.evaluate("() => document.querySelectorAll('#diagram .badge.modified').length")
        assert not page.js_errors, page.js_errors


def test_the_updates_list_says_when_the_map_has_no_history_and_the_foot_takes_a_file() -> None:
    with _served_pair() as (url, old), _page(url + "#v=updates") as page:
        _settle(page)
        assert _crumb(page) == "Updates"
        text = _screen_text(page)
        assert "No update yet" in text and "No committed version" in text, "a folder with no git and no log says so"
        page.fill("#tlPath", old)
        page.press("#tlPath", "Enter")
        _settle(page)
        assert _crumb(page) == "A map file"
        assert f"cmp=path:{old}" in _hash(page) and "at=file" in _hash(page)
        assert page.query_selector('.ecard[data-id="UC1"]')
        assert not page.js_errors, page.js_errors


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
