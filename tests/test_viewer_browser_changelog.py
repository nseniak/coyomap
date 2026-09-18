#!/usr/bin/env python3
"""The update log on screen, in a real browser: the Changes tabs read the log, the map's own diff
sits under it as evidence.

The served folder is a git repo whose one commit holds the map as it was (pinned to `aaaaaaa`); on
disk the map has moved on (pinned to `bbbbbbb`, the same edits tests/test_viewer_browser_compare.py
makes) and the log of that update sits beside it, uncommitted — the state after `coyomap update` and
before its commit. Two entries: one renames a use case and rewords a component, one removes a use
case. Same harness as tests/test_viewer_browser.py. Explicit make_* builders, no fixtures/classes.
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

from test_impact import commit
from test_viewer_browser import _crumb, _page, _settle, make_served_map
from test_viewer_browser_compare import NEW_NAME, OLD_NAME, OLD_UC, _texts, _visible_tabs, make_new_map, make_old_map

OLD_PIN, NEW_PIN, LATER_PIN = "aaaaaaa", "bbbbbbb", "ccccccc"
LOG = f"{OLD_PIN}-{NEW_PIN}"
LOG_2 = f"{NEW_PIN}-{LATER_PIN}"
HEADLINE_3 = "The gateway answers faster"
BLOCK = {"id": "BLK1", "name": "Team lifecycle", "purpose": "Who may do what to a team."}
RULE = {"id": "BR1", "name": "A team keeps its founder", "statement": "A team keeps its founder.",
        "risk": "a team is left with nobody who can run it", "block": "BLK1",
        "sites": [{"where": "app/team.py:4", "why": "guards"}]}
HEADLINE_1 = "Signing up now creates a workspace"
SENTENCE_1 = "A new person gets a workspace of their own, and the sign-up confirms their email first."
HEADLINE_2 = "Archiving an organization is gone"
SENTENCE_2 = "Nobody can archive an organization any more; an unused one is simply left alone."


def make_log(doc: dict[str, Any]) -> dict[str, Any]:
    c1 = next(c for c in doc["components"] if c["id"] == "C1")
    return {"format": "coyomap-changes", "version": 1, "from_commit": OLD_PIN, "to_commit": NEW_PIN, "date": "2026-09-17",
            "entries": [
                {"id": "e1", "headline": HEADLINE_1, "sentence": SENTENCE_1, "elements": ["UC1", "C1", "BR1", "UC2"],
                 "edits": [{"id": "UC1", "key": "name", "was": OLD_NAME, "now": NEW_NAME},
                           {"id": "C1", "key": "purpose", "was": c1["purpose"], "now": c1["purpose"] + " Fast."},
                           {"id": "BR1", "key": "risk", "was": RULE["risk"], "now": "a team is locked"}],
                 "added": [], "removed": [], "evidence": ["app/signup.py"], "confidence": "verified"},
                {"id": "e2", "headline": HEADLINE_2, "sentence": SENTENCE_2, "elements": ["UC99"],
                 "edits": [], "added": [], "removed": ["UC99"], "evidence": [], "confidence": "likely"}],
            "waived": [], "notes": ""}


def make_later_log(doc: dict[str, Any]) -> dict[str, Any]:
    """A second update after the first: the gateway component's purpose reworded, nothing else."""
    c2 = next(c for c in doc["components"] if c["id"] == "C2")
    return {"format": "coyomap-changes", "version": 1, "from_commit": NEW_PIN, "to_commit": LATER_PIN, "date": "2026-09-18",
            "entries": [{"id": "e1", "headline": HEADLINE_3, "sentence": "Requests through the gateway now take half the time.",
                         "elements": ["C2"], "edits": [{"id": "C2", "key": "purpose", "was": c2["purpose"], "now": c2["purpose"] + " Faster."}],
                         "added": [], "removed": [], "evidence": ["app/gateway.py"], "confidence": "verified"}],
            "waived": [], "notes": ""}


@contextmanager
def _served_update(git: bool = True, later: bool = False) -> Iterator[str]:
    """The server over the updated map, with the map as it was committed behind it and the log beside
    it. `git=False`: no history at all, so the log has no evidence. `later`: a second update on top,
    committed map in between, so the first log is no longer the latest."""
    with tempfile.TemporaryDirectory() as td:
        folder = make_served_map(Path(td), "alpha")
        f = folder / ".coyomap" / "project-map.json"
        doc = json.loads(f.read_text())
        doc["blocks"], doc["rules"] = [BLOCK], [json.loads(json.dumps(RULE))]
        old = make_old_map(doc)
        old["commit"] = OLD_PIN
        if git:
            commit(folder, {".coyomap/project-map.json": json.dumps(old, indent=1)}, msg="Map the codebase")
        log = make_log(doc)
        make_new_map(doc)
        doc["rules"][0]["risk"] = "a team is locked"
        doc["commit"] = NEW_PIN
        (folder / ".coyomap" / "changes").mkdir()
        (folder / ".coyomap" / "changes" / f"{LOG}.json").write_text(json.dumps(log), encoding="utf-8")
        if later:
            commit(folder, {".coyomap/project-map.json": json.dumps(doc, indent=1), f".coyomap/changes/{LOG}.json": json.dumps(log)},
                   msg="Map update: sign-up creates a workspace")
            log2 = make_later_log(doc)
            next(c for c in doc["components"] if c["id"] == "C2")["purpose"] += " Faster."
            doc["commit"] = LATER_PIN
            (folder / ".coyomap" / "changes" / f"{LOG_2}.json").write_text(json.dumps(log2), encoding="utf-8")
        f.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        projects = build_projects([str(folder)])
        slug = next(iter(projects))
        Handler.store = RecentsStore()
        Handler.projects = projects
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}/coyomap/{slug}/"
        finally:
            httpd.shutdown()
            httpd.server_close()


def _text(page: Any, selector: str) -> str:
    # textContent, not innerText: a label is uppercased by the stylesheet, and the words asserted here
    # are the words the markup carries.
    return str(page.evaluate(f"() => (document.querySelector({selector!r}) || {{textContent: ''}}).textContent.trim()"))


def _screen_text(page: Any) -> str:
    return str(page.evaluate("() => document.getElementById('diagram').textContent"))


def _hash(page: Any) -> str:
    return str(page.evaluate("() => decodeURIComponent(location.hash)"))


def _armed(page: Any) -> bool:
    return bool(page.evaluate("() => document.getElementById('comparebtn').classList.contains('armed')"))


def test_a_map_with_a_log_opens_with_its_changes_tabs_and_nothing_armed() -> None:
    with _served_update() as url, _page(url + "#v=features") as page:
        _settle(page)
        assert _crumb(page) == "Features"
        assert "changes" in _visible_tabs(page), "the tabs are there without any comparison armed"
        assert _text(page, '#viewsw button[data-view="changes"] .count-pill') == "2", "both entries name a product box"
        assert not _armed(page) and "cmp=" not in _hash(page)
        assert not page.evaluate("() => document.querySelectorAll('#diagram .badge.modified, #diagram .badge.named').length"), \
            "the newest log marks nothing until asked"
        assert not page.js_errors, page.js_errors


def test_the_changes_tab_tells_each_entry_and_a_pill_opens_the_box() -> None:
    with _served_update() as url, _page(url + "#v=changes") as page:
        _settle(page)
        assert _crumb(page) == "Changes"
        head = _text(page, ".cmp-head")
        assert f"Update {OLD_PIN} → {NEW_PIN}" in head and "2026-09-17" in head and "2 entries" in head
        assert "Mark this update on the map" in head, "the newest log offers to mark the map, and there is nothing to stop"
        cards = page.evaluate("() => [...document.querySelectorAll('.ecard-entry')].map((c) => c.textContent)")
        assert len(cards) == 2 and HEADLINE_1 in cards[0] and SENTENCE_1 in cards[0] and HEADLINE_2 in cards[1]
        assert "app/signup.py" in cards[0] or "signup.py" in cards[0], "the evidence is on the foot line"
        assert "verified" in cards[0] and "likely" in cards[1]
        assert "The map’s own diff" in _screen_text(page) and not page.evaluate("() => document.querySelector('details.cmp-evidence').open")
        text = _screen_text(page)
        for internal in ("UC1", "UC99", "C1", "e1", "e2"):
            assert f" {internal}" not in text and not text.startswith(internal), f"an id on screen: {internal}"
        page.click('.ecard-entry .item-pill[data-item="UC1"]')
        _settle(page)
        assert _crumb(page) == NEW_NAME
        assert not page.query_selector(".cmpsec"), "unmarked, a box's page tells no story"
        assert not page.js_errors, page.js_errors


def test_a_link_naming_the_update_marks_the_map_and_a_box_s_page_says_why() -> None:
    with _served_update() as url, _page(f"{url}#v=usecase&uc=UC1&cmp=log:{LOG}") as page:
        _settle(page)
        assert _crumb(page) == NEW_NAME
        assert _armed(page)
        block = _text(page, ".cmpsec")
        assert block.startswith("What changed") and f"in the update {OLD_PIN} → {NEW_PIN}" in block
        assert "Changed because" in block and HEADLINE_1 in block and SENTENCE_1 in block
        assert "modified" in block.lower()
        assert "organization" in _texts(page, ".cmpsec del") and "workspace" in _texts(page, ".cmpsec ins"), \
            "the log's own edit, old words struck and new words marked"
        assert "The map’s own diff" in block, "the evidence follows the story"
        page.reload()
        page.wait_for_selector("#crumb h1", state="attached")
        _settle(page)
        assert f"cmp=log:{LOG}" in _hash(page) and _armed(page)
        assert not page.js_errors, page.js_errors


def test_marking_the_update_badges_every_box_it_names_and_stopping_returns_to_the_unmarked_log() -> None:
    with _served_update() as url, _page(url + "#v=changes") as page:
        _settle(page)
        page.click("button.cmp-mark")
        _settle(page)
        assert _armed(page) and f"cmp=log:{LOG}" in _hash(page)
        assert "Stop comparing" in _text(page, ".cmp-head")
        page.goto(f"{url}#v=features&cmp=log:{LOG}")
        _settle(page)
        assert page.evaluate("() => document.querySelectorAll('#diagram .badge.modified').length") >= 1, \
            "the feature holding the renamed use case says it changed"
        page.goto(f"{url}#v=changes&cmp=log:{LOG}")
        _settle(page)
        page.click("button.cmp-stop")
        _settle(page)
        assert _crumb(page) == "Changes", "the tab stays: the map still carries its log"
        assert not _armed(page) and "cmp=" not in _hash(page)
        assert "Mark this update on the map" in _text(page, ".cmp-head")
        assert not page.js_errors, page.js_errors


def test_a_removed_box_opens_from_the_entry_s_pill_as_it_was_and_says_why_it_went() -> None:
    with _served_update() as url, _page(f"{url}#v=changes&cmp=log:{LOG}") as page:
        _settle(page)
        page.click(f'.cmp-log-pill[data-key="removed:UC99"]')
        _settle(page)
        assert _crumb(page) == OLD_UC
        text = _screen_text(page)
        assert "Removed because" in text and HEADLINE_2 in text and SENTENCE_2 in text
        assert "Not in the current map" in text and "marks the organization archived" in text, "the old map's own words follow"
        for internal in ("UC99", "R2", "C15"):
            assert internal not in text, f"an id on screen: {internal}"
        assert not page.js_errors, page.js_errors


def test_the_picker_lists_the_update_first_and_the_evidence_holds_the_filters() -> None:
    with _served_update() as url, _page(f"{url}#v=hood-changes&cmp=log:{LOG}") as page:
        _settle(page)
        assert _text(page, '#viewsw button[data-view="hoodchanges"] .count-pill') == "1", "one entry names a box under the hood"
        cards = page.evaluate("() => [...document.querySelectorAll('.ecard-entry')].map((c) => c.textContent)")
        assert len(cards) == 1 and "Also here" in cards[0] and SENTENCE_1 not in cards[0], "told in full under Product, named here"
        assert not page.query_selector(".cmp-head button.cmp-filter"), "the filters read the diff, so they sit with it"
        page.click("details.cmp-evidence > summary")
        _settle(page)
        assert page.query_selector("details.cmp-evidence button.cmp-filter") and page.query_selector('details.cmp-evidence .ecard[data-id="C1"]')
        page.click("#comparebtn")
        page.wait_for_selector("#cmplogs .diffcommit", state="attached")
        rows = page.evaluate("() => [...document.querySelectorAll('#cmplogs .diffcommit')].map((b) => b.textContent)")
        assert len(rows) == 1 and "latest" in rows[0] and f"{OLD_PIN} → {NEW_PIN}" in rows[0] and "2 entries" in rows[0]
        assert not page.js_errors, page.js_errors


def test_an_older_log_credits_nothing_that_came_after_it() -> None:
    """The review's third finding: under an older log, a box only a LATER update changed said
    "in the update A → B". Its block now says "since <the version>", and the tab's head says the
    update is not the latest."""
    with _served_update(later=True) as url, _page(url + "#v=hood-changes") as page:
        _settle(page)
        cards = page.evaluate("() => [...document.querySelectorAll('.ecard-entry')].map((c) => c.textContent)")
        assert len(cards) == 1 and HEADLINE_3 in cards[0], "the newest log is the second one"
        page.goto(f"{url}#v=hood-changes&cmp=log:{LOG}")
        _settle(page)
        assert "not the latest update" in _text(page, ".cmp-head")
        page.click("details.cmp-evidence > summary")
        _settle(page)
        page.click('details.cmp-evidence .ecard[data-id="C2"]')
        _settle(page)
        block = _text(page, ".cmpsec")
        assert block.startswith("What changed") and "since" in block and "in the update" not in block, block
        assert HEADLINE_3 not in block and HEADLINE_1 not in block
        assert not page.js_errors, page.js_errors


def test_the_rules_landing_marks_the_area_of_an_edited_rule() -> None:
    """The review's sixth finding: a decision area wears its rules' change, as a feature wears its
    use cases', or the change hides behind a click."""
    with _served_update() as url, _page(f"{url}#v=rules&cmp=log:{LOG}") as page:
        _settle(page)
        assert _crumb(page) == "Rules"
        assert "modified" in _text(page, '#diagram [data-id="BLK1"] .badge'), "the area of the edited rule is badged"
        assert not page.js_errors, page.js_errors


def test_without_git_the_removed_box_s_page_still_tells_its_story() -> None:
    """The review's fourth finding: a folder with no history has no evidence, and the removed box's
    page was empty in the unmarked state. It is the story's page, so the story is told there always,
    and the box is named by its kind when no old map names it."""
    with _served_update(git=False) as url, _page(url + "#v=changes") as page:
        _settle(page)
        assert "cannot be shown" in _screen_text(page), "no committed version: the fold says so"
        page.click('.cmp-log-pill[data-key="removed:UC99"]')
        _settle(page)
        assert "removed use case" in _crumb(page)
        text = _screen_text(page)
        assert "Removed because" in text and HEADLINE_2 in text and SENTENCE_2 in text
        assert "UC99" not in text
        assert not page.js_errors, page.js_errors


def test_a_box_the_entry_only_names_is_named_in_the_story_not_changed_by_it() -> None:
    """The review's fifth finding: a box the entry only names read "Changed because", under a head
    saying "in this update in the update A → B"."""
    with _served_update() as url, _page(f"{url}#v=changes&cmp=log:{LOG}") as page:
        _settle(page)
        page.click('.ecard-entry .item-pill[data-item="UC2"]')
        _settle(page)
        block = _text(page, ".cmpsec")
        assert "Named in" in block and HEADLINE_1 in block and "Changed because" not in block
        assert block.count("in the update") == 1 and "in this update" not in block
        assert not page.js_errors, page.js_errors


def test_after_stop_comparing_the_button_and_the_address_always_agree() -> None:
    """Back and Forward walk the browser's own history; whatever screen they land on, the Compare…
    button is lit exactly when the address carries a comparison."""
    with _served_update() as url, _page(f"{url}#v=features&cmp=log:{LOG}") as page:
        _settle(page)
        page.click('#viewsw button[data-view="changes"]')
        _settle(page)
        page.click("button.cmp-stop")
        _settle(page)
        assert not _armed(page) and "cmp=" not in _hash(page)
        for step in ("back", "forward"):
            getattr(page, f"go_{step}")()
            _settle(page)
            assert _armed(page) == ("cmp=" in _hash(page)), (step, _hash(page))
        assert not page.js_errors, page.js_errors


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
