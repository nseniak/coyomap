#!/usr/bin/env python3
"""The update log on screen, in a real browser: the Update log's Updates list reads the log, and the
map's own diff for that step sits under it as evidence.

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

OLD_UC = "Archive an organization"
NEW_NAME = "Sign up and create a workspace"
OLD_NAME = "Sign up and create an organization"
NEW_STEP = "confirms the email the browser sent"
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


def make_old_map(doc: dict[str, Any]) -> dict[str, Any]:
    """The fixture plus a use case the new map no longer has, with a two-step flow of its own."""
    old = json.loads(json.dumps(doc))
    old["use_cases"].append({"id": "UC99", "name": OLD_UC, "actors": ["R2"], "capability": "CAP1",
                             "trigger": "An org admin archives an organization nobody uses.", "outcome": "The organization is gone from every list."})
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


def make_log(doc: dict[str, Any]) -> dict[str, Any]:
    c1 = next(c for c in doc["components"] if c["id"] == "C1")
    return {"format": "coyomap-changes", "version": 1, "from_commit": OLD_PIN, "to_commit": NEW_PIN, "date": "2026-09-17",
            "entries": [
                {"id": "e1", "headline": HEADLINE_1, "sentence": SENTENCE_1, "elements": ["UC1", "C1", "BR1", "UC2", "R1", "E1"],
                 "edits": [{"id": "UC1", "key": "name", "was": OLD_NAME, "now": NEW_NAME},
                           {"id": "C1", "key": "purpose", "was": c1["purpose"], "now": c1["purpose"] + " Fast."},
                           {"id": "BR1", "key": "risk", "was": RULE["risk"], "now": "a team is locked"}],
                 "added": [], "removed": [], "evidence": ["app/signup.py"], "confidence": "verified"},
                {"id": "e2", "headline": HEADLINE_2, "sentence": SENTENCE_2, "elements": ["UC99"],
                 "edits": [], "added": [], "removed": ["UC99"], "evidence": [], "confidence": "likely"}],
            "waived": [{"id": "C2", "why": "only its tests moved; the gateway itself did not change"}],
            "notes": "Resolution: step precision on both screens; the sign-up seam read from the router."}


def make_later_log(doc: dict[str, Any]) -> dict[str, Any]:
    """A second update after the first: one component's purpose reworded, nothing else. C3, not C2:
    the first update moved C2's code line, so C2 has a step of its own there."""
    c3 = next(c for c in doc["components"] if c["id"] == "C3")
    return {"format": "coyomap-changes", "version": 1, "from_commit": NEW_PIN, "to_commit": LATER_PIN, "date": "2026-09-18",
            "entries": [{"id": "e1", "headline": HEADLINE_3, "sentence": "Requests through the gateway now take half the time.",
                         "elements": ["C3"], "edits": [{"id": "C3", "key": "purpose", "was": c3["purpose"], "now": c3["purpose"] + " Faster."}],
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
            next(c for c in doc["components"] if c["id"] == "C3")["purpose"] += " Faster."
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


def _texts(page: Any, selector: str) -> str:
    """Every match's text, joined: a reworded sentence is several struck and marked runs."""
    return str(page.evaluate(f"() => [...document.querySelectorAll({selector!r})].map((e) => e.textContent).join(' ')"))


def _hash(page: Any) -> str:
    return str(page.evaluate("() => decodeURIComponent(location.hash)"))


def _marked(page: Any) -> bool:
    return "cmp=" in _hash(page)


def _cards(page: Any, selector: str = ".ecard") -> list[str]:
    return list(page.evaluate(f"() => [...document.querySelectorAll({selector!r})].map((c) => c.textContent)"))


def _ready(page: Any) -> None:
    """Let the screen settle, then wait for a version's page to hold its document: the page draws
    its head at once and reads the map's own diff after, which under a loaded test run takes longer
    than the settle. On any other screen the wait returns at once."""
    _settle(page)
    page.wait_for_function("() => !document.getElementById('diagram').textContent.includes('Reading the map')", timeout=15000)


def _open_update(page: Any) -> None:
    """From the Updates list, open the newest update."""
    page.click('#diagram .ecard[data-key]')
    _ready(page)


def test_the_updates_list_holds_the_updates_and_nothing_else() -> None:
    with _served_update() as url, _page(url + "#v=updates") as page:
        _ready(page)
        assert _crumb(page) == "Updates"
        assert [b for b in page.evaluate("() => [...document.querySelectorAll('#groupsw button')].map((b) => b.textContent)")] \
            == ["Product", "Under the hood", "Update log"]
        rows = _cards(page)
        assert len(rows) == 1, "one row per run of coyomap update; the map's committed versions are not rows"
        assert f"Update {OLD_PIN} → {NEW_PIN}" in rows[0] and HEADLINE_1 in rows[0] and HEADLINE_2 in rows[0]
        assert "not committed yet" in rows[0], "the update sits on disk"
        assert "Map the codebase" not in _screen_text(page), "the commit that built the map is not the product's history"
        assert "1 update" in _text(page, ".landing-head")
        assert not _marked(page)
        assert not page.js_errors, page.js_errors


def _feature_of(doc: dict[str, Any], uc: str) -> str:
    cap = next(u for u in doc["use_cases"] if u["id"] == uc)["capability"]
    return next(c for c in doc["capabilities"] if c["id"] == cap)["name"]


def test_an_update_s_page_tells_the_log_by_feature_with_its_waivers_and_notes() -> None:
    """The reader asks "what changed in feature X": a section per feature the update touches, each
    entry told in full under it with that feature's boxes; the boxes no feature claims under "Across
    the product"; the machine boxes under the hood, where an entry already told comes back as its
    headline and pills; then the waivers and the notes, and the fold with the map's own diff."""
    with _served_update() as url, _page(url + "#v=updates") as page:
        _ready(page)
        doc = json.loads((Path(__file__).resolve().parent / "fixtures" / "mcpolis-project-map.json").read_text())
        feature = _feature_of(doc, "UC1")
        _open_update(page)
        assert _crumb(page) == f"Update {OLD_PIN} → {NEW_PIN}"
        head = _text(page, ".cmp-head")
        assert "2026-09-17" in head and "2 entries" in head and "Mark this update on the map" in head
        titles = page.evaluate("() => [...document.querySelectorAll('.item-sec')].map((s) => s.querySelector('.item-sec-strip').textContent.trim())")
        assert titles[0].startswith(feature), f"the renamed use case's feature leads: {titles}"
        assert any(t.startswith("Across the product") for t in titles), "the removed use case belongs to no feature the map still has"
        assert titles[-1].startswith("Under the hood")
        first = page.evaluate(f"() => document.querySelector('.item-sec[id$=\"upd-feat-{doc['use_cases'][0]['capability']}\"] .ecard-entry').textContent")
        assert HEADLINE_1 in first and SENTENCE_1 in first and NEW_NAME in first and "signup.py" in first and "verified" in first
        assert "App factory" not in first, "a machine box is not this feature's pill"
        hood = page.evaluate("() => [...document.querySelectorAll('.item-sec[id$=\"upd-hood\"] .ecard-entry')].map((c) => c.textContent)")
        assert len(hood) == 1 and HEADLINE_1 in hood[0] and "Also here" in hood[0] and "App factory" in hood[0] and SENTENCE_1 not in hood[0]
        text = _screen_text(page)
        assert HEADLINE_2 in text and SENTENCE_2 in text and "likely" in text
        assert "Touched by the code, no change of meaning" in text and "only its tests moved" in text
        assert "Notes" in text and "step precision on both screens" in text
        assert "The map’s own diff" in text and not page.evaluate("() => document.querySelector('details.cmp-evidence').open")
        for internal in ("UC1", "UC99", "C1", "C2", "e1", "e2"):
            assert f" {internal}" not in text, f"an id on screen: {internal}"
        page.click('.item-sec-door[data-gofeat]')
        _ready(page)
        assert _crumb(page) == feature, "the section's name is a door to the feature"
        assert not page.js_errors, page.js_errors


def test_a_pill_opens_the_box_and_an_unmarked_page_tells_no_story() -> None:
    with _served_update() as url, _page(f"{url}#v=updates&at={LOG}") as page:
        _ready(page)
        page.click('.ecard-entry .item-pill[data-item="UC1"]')
        _ready(page)
        assert _crumb(page) == NEW_NAME
        assert not page.query_selector(".cmpsec"), "unmarked, a box's page tells no story"
        assert not page.js_errors, page.js_errors


def test_marking_the_update_badges_every_box_it_names_and_a_box_s_page_says_why() -> None:
    with _served_update() as url, _page(f"{url}#v=updates&at={LOG}") as page:
        _ready(page)
        page.click("button.cmp-mark")
        _ready(page)
        assert f"cmp=log:{LOG}" in _hash(page) and "Stop marking" in _text(page, ".cmp-head")
        assert "on today’s map" in _text(page, ".cmp-head"), "the marks are on today's map, and the head says so"
        page.goto(f"{url}#v=features&cmp=log:{LOG}")
        _ready(page)
        assert page.evaluate("() => document.querySelectorAll('#diagram .badge.modified').length") >= 1, \
            "the feature holding the renamed use case says it changed"
        page.goto(f"{url}#v=usecase&uc=UC1&cmp=log:{LOG}")
        _ready(page)
        block = _text(page, ".cmpsec")
        assert block.startswith("What changed") and f"in the update {OLD_PIN} → {NEW_PIN}" in block
        assert "Changed because" in block and HEADLINE_1 in block and SENTENCE_1 in block
        assert "organization" in _texts(page, ".cmpsec del") and "workspace" in _texts(page, ".cmpsec ins")
        assert "The map’s own diff" in block, "the evidence follows the story"
        page.reload()
        page.wait_for_selector("#crumb h1", state="attached")
        _ready(page)
        assert f"cmp=log:{LOG}" in _hash(page) and page.query_selector(".cmpsec")
        page.goto(f"{url}#v=updates&at={LOG}&cmp=log:{LOG}")
        _ready(page)
        page.click("button.cmp-stop")
        _ready(page)
        assert not _marked(page) and "Mark this update on the map" in _text(page, ".cmp-head")
        assert not page.js_errors, page.js_errors


def test_a_box_the_entry_only_names_is_named_in_the_story_not_changed_by_it() -> None:
    with _served_update() as url, _page(f"{url}#v=usecase&uc=UC2&cmp=log:{LOG}") as page:
        _ready(page)
        block = _text(page, ".cmpsec")
        assert "Named in" in block and HEADLINE_1 in block and "Changed because" not in block
        assert block.count("in the update") == 1 and "in this update" not in block
        assert not page.js_errors, page.js_errors


def test_a_removed_box_opens_from_the_entry_s_pill_as_it_was_and_says_why_it_went() -> None:
    with _served_update() as url, _page(f"{url}#v=updates&at={LOG}") as page:
        _ready(page)
        page.click('.cmp-log-pill[data-key="removed:UC99"]')
        _ready(page)
        assert _crumb(page) == OLD_UC
        text = _screen_text(page)
        assert "Removed because" in text and HEADLINE_2 in text and SENTENCE_2 in text
        assert "Not in the current map" in text and "marks the organization archived" in text, "the old map's own words follow"
        for internal in ("UC99", "R2", "C15"):
            assert internal not in text, f"an id on screen: {internal}"
        assert f"at={LOG}" in _hash(page)
        assert not page.js_errors, page.js_errors


def test_without_git_the_update_still_has_a_page_and_its_removed_box_a_story() -> None:
    with _served_update(git=False) as url, _page(url + "#v=updates") as page:
        _ready(page)
        rows = _cards(page)
        assert len(rows) == 1 and HEADLINE_1 in rows[0]
        _open_update(page)
        assert "cannot be shown" in _screen_text(page), "no committed version: the fold says so"
        page.click('.cmp-log-pill[data-key="removed:UC99"]')
        _ready(page)
        assert "removed use case" in _crumb(page)
        text = _screen_text(page)
        assert "Removed because" in text and HEADLINE_2 in text and "UC99" not in text
        assert not page.js_errors, page.js_errors


def test_an_older_update_s_evidence_is_its_own_step_and_credits_nothing_that_came_after() -> None:
    """Two updates: the first committed, the second on disk. The first update's page shows the diff
    from the version before it to the version it made, so the later update's change is not in it,
    and marked on the map it says nothing on that box's page."""
    with _served_update(later=True) as url, _page(url + "#v=updates") as page:
        _ready(page)
        rows = _cards(page)
        assert len(rows) == 2 and HEADLINE_3 in rows[0] and HEADLINE_1 in rows[1]
        assert "not committed yet" in rows[0] and "landed" in rows[1].lower()
        page.click(f'#diagram .ecard[data-key="at:{LOG}"]')
        _ready(page)
        assert _crumb(page) == f"Update {OLD_PIN} → {NEW_PIN}"
        assert "from the version before this update to the version it made" in _text(page, "details.cmp-evidence > summary")
        page.click("details.cmp-evidence > summary")
        _ready(page)
        assert page.query_selector('details.cmp-evidence .ecard[data-id="C1"]')
        assert not page.query_selector('details.cmp-evidence .ecard[data-id="C3"]'), "the later update's change is not this step's"
        page.goto(f"{url}#v=element&id=C3&cmp=log:{LOG}")
        _ready(page)
        assert not page.query_selector(".cmpsec"), "under the older update the later-changed box's page tells nothing"
        assert not page.js_errors, page.js_errors


def test_a_read_that_fails_is_said_on_the_page_and_can_be_tried_again() -> None:
    """The page kept "Reading the map's own diff…" for ever when the server was away for a moment
    (a restart right after a link was sent). It says what went wrong now, and a click reads again."""
    with _served_update() as url, _page(url + "#v=updates") as page:
        _ready(page)
        broken = {"on": True}
        page.route("**/api/compare*", lambda route: route.fulfill(status=500, body="the map server is away") if broken["on"] else route.continue_())
        _open_update(page)
        _ready(page)
        text = _screen_text(page)
        assert "the map server is away" in text and "Reading the map" not in text
        assert page.query_selector("button.cmp-retry")
        broken["on"] = False
        page.click("button.cmp-retry")
        _ready(page)
        assert HEADLINE_1 in _screen_text(page) and not page.query_selector("button.cmp-retry")
        assert not page.js_errors, page.js_errors


def test_a_link_naming_an_update_the_map_does_not_have_says_so_at_once() -> None:
    with _served_update() as url, _page(url + "#v=updates&at=deadbee-cafe000") as page:
        _ready(page)
        text = _screen_text(page)
        assert "not beside this map" in text and "Reading the map" not in text
        assert not page.js_errors, page.js_errors


def test_the_evidence_fold_lists_each_changed_row_with_its_summary_and_the_filters_read_it() -> None:
    """The map's own diff under an update: a renamed use case's card says so and opens its page with
    the old words struck and the new marked; a component whose code line only moved hides behind the
    code-links filter, and is counted where it hides."""
    with _served_update() as url, _page(f"{url}#v=updates&at={LOG}&cmp=log:{LOG}") as page:
        _ready(page)
        page.click("details.cmp-evidence > summary")
        _ready(page)
        card = _text(page, 'details.cmp-evidence .ecard[data-id="UC1"]')
        assert NEW_NAME in card and "1 added" in card and f"renamed from {OLD_NAME}" in card
        assert not page.query_selector('details.cmp-evidence .ecard[data-id="C2"]'), "a moved line is hidden while code links are off"
        assert _text(page, 'button.cmp-filter[data-cls="link"]') == "code links 1", "what is hidden is counted where it is hidden"
        page.click('button.cmp-filter[data-cls="link"]')
        _ready(page)
        assert "code link moved" in _text(page, 'details.cmp-evidence .ecard[data-id="C2"]')
        page.click('details.cmp-evidence .ecard[data-id="UC1"]')
        _ready(page)
        assert _crumb(page) == NEW_NAME
        block = _text(page, ".cmpsec")
        assert "organization" in _texts(page, ".cmpsec del") and "workspace" in _texts(page, ".cmpsec ins")
        assert NEW_STEP in block and "renumbered" in block
        assert not page.js_errors, page.js_errors


def test_a_marked_update_badges_the_subsystem_holding_a_changed_component() -> None:
    with _served_update() as url, _page(f"{url}#v=container&cmp=log:{LOG}") as page:
        _ready(page)
        assert page.evaluate("() => document.querySelectorAll('#diagram .diff-badge').length") >= 1, \
            "the subsystem holding the reworded component is badged on the overview"
        assert not page.js_errors, page.js_errors


def test_a_map_with_no_update_shows_the_tab_with_what_it_is_for_and_how_to_get_one() -> None:
    """The tab is always there. A map that has no update yet says what the tab holds and how an
    update comes to be, in the reader's words, rather than an empty screen."""
    with tempfile.TemporaryDirectory() as td:
        folder = make_served_map(Path(td), "alpha")
        projects = build_projects([str(folder)])
        slug = next(iter(projects))
        Handler.store = RecentsStore()
        Handler.projects = projects
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with _page(f"http://127.0.0.1:{httpd.server_address[1]}/coyomap/{slug}/#v=updates") as page:
                _ready(page)
                assert _crumb(page) == "Updates"
                assert "Update log" in page.evaluate("() => [...document.querySelectorAll('#groupsw button')].map((b) => b.textContent)")
                text = _screen_text(page)
                assert "No update yet" in text and "update log" in text and "/coyomap update" in text and "coyomap update" in text
                assert "0 update" not in _text(page, ".landing-head"), "a count of nothing is not drawn"
                assert not page.js_errors, page.js_errors
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_every_kind_of_box_is_filed_under_its_own_feature() -> None:
    """The review found actors never filed (their join is a table of counts, not a list) and sub-flows
    never filed (a narrated step names its sub-flow under `sf`). Each kind the fixture holds is now
    pinned: an actor under the features they drive, a record under its owner, a rule under its
    area's authored features, a use case under its own."""
    with _served_update() as url, _page(url + "#v=updates") as page:
        _ready(page)
        doc = json.loads((Path(__file__).resolve().parent / "fixtures" / "mcpolis-project-map.json").read_text())
        _open_update(page)
        placed = page.evaluate("""() => {
          const out = {};
          for (const sec of document.querySelectorAll('.item-sec')) {
            const title = sec.querySelector('.item-sec-strip').textContent.trim().replace(/\s+/g, ' ');
            for (const pill of sec.querySelectorAll('.item-pill')) (out[pill.textContent.trim()] = out[pill.textContent.trim()] || []).push(title.slice(0, 30));
          }
          return out;
        }""")
        cap = {c["id"]: c["name"] for c in doc["capabilities"]}
        uc1 = next(u for u in doc["use_cases"] if u["id"] == "UC1")["capability"]
        uc2 = next(u for u in doc["use_cases"] if u["id"] == "UC2")["capability"]
        assert any(t.startswith(cap[uc1][:30]) for t in placed[NEW_NAME]), placed
        uc2_name = next(u for u in doc["use_cases"] if u["id"] == "UC2")["name"]
        assert any(t.startswith(cap[uc2][:30]) for t in placed[uc2_name]), placed
        assert "Org creator" in placed and not any(t.startswith("Across the product") for t in placed["Org creator"]), \
            f"an actor is filed under the features they drive: {placed.get('Org creator')}"
        assert "Organization" in placed and not any(t.startswith("Across the product") for t in placed["Organization"]), \
            f"a record is filed under its owner feature: {placed.get('Organization')}"
        assert not page.js_errors, page.js_errors


def test_a_box_the_update_only_names_is_not_a_change_on_its_feature_card() -> None:
    """A use case the update names without editing it did not change, so its feature's card does
    not say "changed" — the fixture's second use case sits in another feature than the renamed one."""
    with _served_update() as url, _page(f"{url}#v=features&cmp=log:{LOG}") as page:
        _ready(page)
        doc = json.loads((Path(__file__).resolve().parent / "fixtures" / "mcpolis-project-map.json").read_text())
        uc2_cap = next(u for u in doc["use_cases"] if u["id"] == "UC2")["capability"]
        uc1_cap = next(u for u in doc["use_cases"] if u["id"] == "UC1")["capability"]
        assert uc2_cap != uc1_cap
        badged = page.evaluate("() => [...document.querySelectorAll('#diagram .ecard')].filter((c) => c.querySelector('.badge.modified')).map((c) => c.getAttribute('data-id'))")
        assert uc1_cap in badged and uc2_cap not in badged, badged
        assert not page.js_errors, page.js_errors


def test_a_failed_list_is_said_on_the_tab_and_can_be_tried_again() -> None:
    """The list is asked for at boot. A failed answer used to leave an empty list, which the tab
    told as "No update yet" with instructions to run one: a wrong statement. It says the failure now,
    and reads again on request."""
    with _served_update() as url, _page(url + "#v=features") as page:
        _ready(page)
        broken = {"on": True}
        page.route("**/api/changes", lambda route: route.fulfill(status=500, body="git is away") if broken["on"] else route.continue_())
        page.goto(url + "?again=1#v=updates")   # a fresh load, so the list is asked for behind the broken route
        page.wait_for_selector("#crumb h1", state="attached")
        _ready(page)
        text = _screen_text(page)
        assert "could not be read" in text and "git is away" in text and "No update yet" not in text
        broken["on"] = False
        page.click("button.cmp-retry-logs")
        _ready(page)
        assert HEADLINE_1 in _screen_text(page)
        assert not page.js_errors, page.js_errors


def test_a_page_opened_while_its_document_is_still_on_its_way_draws_when_it_arrives() -> None:
    """The review's race: a removed box's page opened while the update's diff was being read stayed
    on "Reading…" for ever, since only the page that asked was redrawn. Whatever page now reads that
    document is redrawn when it arrives."""
    with _served_update() as url, _page(url + "#v=features") as page:
        _ready(page)
        page.route("**/api/compare*", lambda route: (page.wait_for_timeout(2500), route.continue_()))
        page.goto(f"{url}#v=updates&at={LOG}")
        page.wait_for_timeout(300)
        page.goto(f"{url}#v=removed&id=UC99&at={LOG}")
        page.wait_for_function("() => !document.getElementById('diagram').textContent.includes('Reading the map')", timeout=15000)
        assert _crumb(page) == OLD_UC and "Removed because" in _screen_text(page)
        assert not page.js_errors, page.js_errors


def test_the_rules_landing_marks_the_area_of_an_edited_rule() -> None:
    with _served_update() as url, _page(f"{url}#v=rules&cmp=log:{LOG}") as page:
        _ready(page)
        assert _crumb(page) == "Rules"
        assert "modified" in _text(page, '#diagram [data-id="BLK1"] .badge'), "the area of the edited rule is badged"
        assert not page.js_errors, page.js_errors


def test_after_stop_marking_the_address_never_carries_a_comparison_the_screen_does_not_show() -> None:
    """Back and Forward walk the browser's own history; whatever screen they land on, badges are on
    exactly when the address carries a comparison."""
    with _served_update() as url, _page(f"{url}#v=features&cmp=log:{LOG}") as page:
        _ready(page)
        page.click('#groupsw button[data-group="changelog"]')
        _ready(page)
        page.click('#diagram .ecard[data-key]')
        _ready(page)
        page.click("button.cmp-stop")
        _ready(page)
        assert not _marked(page)
        # The mark is the session's: once stopped, Back lands unmarked, and the address it lands on
        # says so too (the viewer restates it), so no screen wears badges its address does not carry.
        page.go_back()
        _ready(page)
        assert not _marked(page) and not page.query_selector("button.cmp-stop, #diagram .badge.modified, #diagram .badge.named"), _hash(page)
        page.go_forward()
        _ready(page)
        assert not _marked(page), _hash(page)
        assert not page.js_errors, page.js_errors


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
