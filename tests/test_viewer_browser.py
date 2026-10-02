#!/usr/bin/env python3
"""The gate that can see a browser bug.

Every other viewer test reads `viewer.js` as TEXT and asserts on its source. That catches a renamed
function and a dropped line; it cannot catch a screen that renders wrong, a history step that lands
somewhere else, or a page that throws. Two real defects in the URL work shipped past 2104 green
tests and were caught only by a person driving a browser by hand.

This file closes that hole. It starts the real server on a real port, opens real Chromium, clicks,
and reads what is on screen. `playwright` is optional: without it the whole file skips, so a
Python-only environment still gets a clean run, the same bargain `test_viewer_js.py` makes with node.

Conventions: top-level test functions, no classes/fixtures (helpers are `make_*` / `_*`).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit
from urllib.request import urlopen

import pytest

from browser_harness import new_page
from coyomap.model import load_model
from coyomap.viewer.gen_viewer import gen_arch_views
from coyomap.viewer.recents import RecentsStore
from coyomap.viewer.serve import Handler, build_projects
from coyomap.views import model_to_graph

_FIXTURE_MAP = Path(__file__).resolve().parent / "fixtures" / "mcpolis-project-map.json"


def make_served_map(parent: Path, name: str) -> Path:
    """`parent/name` holding the committed fixture map, ready for `build_projects`."""
    d = parent / name
    (d / ".coyomap").mkdir(parents=True)
    shutil.copy(_FIXTURE_MAP, d / ".coyomap" / "project-map.json")
    return d


@contextmanager
def _served_map(mutate: Any, beside: Any = None) -> Iterator[str]:
    """The same server, over a map this test has changed first — for the shapes the committed
    fixture cannot hold (a step with no use case behind it, say). `beside`, when given, is called
    with the map's `.coyomap/` folder, for a file the viewer reads next to the map."""
    import json
    with tempfile.TemporaryDirectory() as td:
        folder = make_served_map(Path(td), "alpha")
        f = folder / ".coyomap" / "project-map.json"
        m = json.loads(f.read_text())
        mutate(m)
        f.write_text(json.dumps(m))
        if beside is not None:
            beside(folder / ".coyomap")
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


@contextmanager
def _served() -> Iterator[str]:
    """The real HTTP server on an ephemeral port, yielding the map's base URL."""
    with tempfile.TemporaryDirectory() as td:
        folder = make_served_map(Path(td), "alpha")
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


@contextmanager
def _page(url: str, stylesheet: str | None = None) -> Iterator[Any]:
    """A Chromium page on `url`, with JS errors collected.

    Errors are attached as `page.js_errors`: a viewer that throws while rendering has failed, even
    when the assertion under test would otherwise pass.

    `stylesheet` serves that text in place of the viewer's own, from the FIRST layout on — the only
    way to test what the viewer does when its stylesheet cannot give the drawing room."""
    # ONE browser per process, a fresh PAGE per test (see tests/browser_harness.py). The page is
    # what has to be new: it carries its own localStorage, and the viewer remembers a reader's
    # settings and tab there, so a shared one would leak state from test to test.
    page = new_page(stylesheet)
    page.goto(url)
    page.wait_for_selector("#crumb h1", state="attached")
    try:
        yield page
    finally:
        page.close()


def _crumb(page: Any) -> str:
    return str(page.evaluate("() => (document.getElementById('crumb').textContent || '').trim()"))


def _settle(page: Any) -> None:
    """Let a navigation's render (and its drill animation) finish before reading the screen."""
    page.wait_for_timeout(700)


def test_a_reload_comes_back_to_the_screen_you_were_on() -> None:
    """The whole point of the change: the URL names the screen, so a reload keeps your place."""
    with _served() as url, _page(url) as page:
        page.evaluate("() => document.querySelector('button[data-view=\"glossary\"]').click()")
        _settle(page)
        assert page.evaluate("() => location.hash") == "#v=glossary"
        page.reload()
        page.wait_for_selector("#crumb h1", state="attached")
        _settle(page)
        assert page.evaluate("() => location.hash") == "#v=glossary"
        assert "Glossary" in _crumb(page)
        assert not page.js_errors, page.js_errors


def test_back_after_an_address_bar_paste_walks_the_real_screens() -> None:
    """The review's exact repro. A pasted hash starts a NEW stack without a page load, so every entry
    behind it belongs to the stack just thrown away. While the entry stamp was keyed on the page load
    those stale indexes still matched: Back rendered whatever now sat at that index, and the URL was
    then rewritten over the entry, losing the screen it named for the life of the tab.

    Read the steps as a walk: Tests, then Glossary, then the landing screen, the Overview since
    2026-09-12 (Features before). Before the fix it was Tests, then Subsystems, then Tests."""
    with _served() as url, _page(url) as page:
        page.evaluate("() => document.querySelector('button[data-view=\"glossary\"]').click()")
        _settle(page)
        page.evaluate("() => { location.hash = '#v=tests'; }")
        _settle(page)
        page.evaluate("() => document.querySelector('button[data-view=\"container\"]').click()")
        _settle(page)

        walked = []
        for _ in range(3):
            page.go_back()
            _settle(page)
            walked.append(page.evaluate("() => location.hash"))
        assert walked == ["#v=tests", "#v=glossary", "#v=overview"], walked
        assert "Overview" in _crumb(page)
        assert not page.js_errors, page.js_errors


@pytest.mark.parametrize("fragment", [
    "#v=data&store=%29",              # a paren: `'#' + id` was not a valid selector, querySelector threw
    "#v=capability&cap=constructor",  # an inherited property name read as a lookup HIT
    "#v=__proto__",                   # …the same, as the view kind itself
    "#v=container&sel=__proto__",     # …and as a selection key, which was then CALLED
    "#v=subsystem&sid=S99",           # an ordinary stale id: the map was rebuilt under the link
])
def test_a_crafted_or_stale_link_still_draws_a_page_with_a_trail(fragment: str) -> None:
    """A link is text a reader can type or keep from an older map. Whatever it says, the viewer owes
    them a page that says where they are. Each fragment below aborted the render before the trail was
    drawn; opened cold, the page had no breadcrumb and no lit tab at all."""
    with _served() as url, _page(url + fragment) as page:
        _settle(page)
        assert _crumb(page), f"no trail at all for {fragment}"
        assert page.evaluate("() => !!document.querySelector('button[data-view].active')"), fragment
        assert not page.js_errors, page.js_errors


def test_a_stale_link_shows_no_internal_id_on_screen() -> None:
    """The viewer shows names; ids are internal. Every id-to-name lookup fell back to the id, which a
    stale link reaches — an adversarial review found 8 fragments that printed one into the trail."""
    with _served() as url, _page(url) as page:
        for fragment, gone in (("#v=subsystem&sid=S99", "S99"),
                               ("#v=element&id=C999", "C999"),
                               ("#v=usecase&uc=UC99", "UC99")):
            page.evaluate("(h) => { location.hash = h; }", fragment)
            _settle(page)
            crumb = _crumb(page)
            assert gone not in crumb, f"{fragment} put the id in the trail: {crumb!r}"
            assert "Not in this map" in crumb, crumb
        assert not page.js_errors, page.js_errors


def test_the_happy_path_draws_one_line_broken_at_every_change_of_person() -> None:
    """The Happy Path board, which replaced a sequence diagram Mermaid shrank to 9.5px of step text
    on this very map. Three things make it the walk rather than a list of steps:

      * a BOX is a run of consecutive steps sharing one feature AND one person, so the fixture's 14
        steps draw 11 boxes;
      * the line BREAKS wherever the person changes, and that person stands in the break — 6 of
        them here, one per hand-over;
      * the line WRAPS: every row but the last ends in an elbow that turns down, and every row but
        the first opens with a hook coming in from above. Only the walk's final row ends in the
        arrow head, because only there does the walk actually stop.

    Read from the rendered page, not from the source: every other viewer test asserts on text."""
    with _served() as url, _page(url + "#v=hp") as page:
        _settle(page)
        counts = page.evaluate("""() => ({
            steps: document.querySelectorAll('.flow-step').length,
            boxes: document.querySelectorAll('.hp-box').length,
            hands: document.querySelectorAll('.hp-hand').length,
            elbows: document.querySelectorAll('.hp-elbow').length,
            hooks: document.querySelectorAll('.hp-hook').length,
            closed: document.querySelectorAll('.hp-box.hp-closes').length
        })""")
        assert counts == {"steps": 14, "boxes": 11, "hands": 6,
                          "elbows": 5, "hooks": 5, "closed": 1}, counts
        # …and no sequence diagram is left anywhere on the page.
        assert page.evaluate("() => !document.querySelector('#diagram svg .actor-line')")
        assert not page.js_errors, page.js_errors


def test_every_bullet_of_the_walk_sits_on_the_line() -> None:
    """A BUTTON centres its own content box, and as a stretched flex item every step is as tall as
    the tallest — which put the bullet of a step with a short title 8px below the line it is meant to
    sit on. Measured, never eyeballed: the bullet's centre, the line's centre and the centre of the
    person's glyph must all be one number."""
    with _served() as url, _page(url + "#v=hp") as page:
        _settle(page)
        # Per ROW, because each row draws its own line: every bullet on it, and the person naming it,
        # must share that line's centre to the decimal.
        off = page.evaluate("""() => {
            const mid = (el) => { const r = el.getBoundingClientRect(); return +(r.top + r.height / 2).toFixed(1); };
            const bad = [];
            [...document.querySelectorAll('.hp-row')].forEach((row, i) => {
                const line = +(row.querySelector('.hp-line').getBoundingClientRect().top + 21).toFixed(1);
                const dots = [...new Set([...row.querySelectorAll('.flow-step-dot')].map(mid))];
                // The person's BLOCK is what sits on the line: an icon with the name under it, so the
                // line runs between the two. And where two people share a row, the little "or"
                // between them sits on their ICONS, not on their block — its own middle would fall
                // in the names, and it would read as a word joining them rather than a choice.
                const one = row.querySelector('.hp-one, .flow-step-numowho');
                const or = row.querySelector('.hp-or');
                const ico = row.querySelector('.hp-ico');
                if (dots.length !== 1 || dots[0] !== line) bad.push({ row: i, dots, line });
                else if (one && Math.abs(mid(one) - line) > 1) bad.push({ row: i, one: mid(one), line });
                else if (or && Math.abs((or.getBoundingClientRect().top + 10.5) - mid(ico)) > 1.5) {
                    bad.push({ row: i, or: +(or.getBoundingClientRect().top + 10.5).toFixed(1),
                               ico: mid(ico) });
                }
            });
            return bad;
        }""")
        assert off == [], off
        assert not page.js_errors, page.js_errors


def test_the_walk_has_three_doors_and_each_opens_that_thing_s_own_page() -> None:
    """A step opens the flow of the use case it realizes — the same flow the Features tab drills to,
    so a use case keeps ONE home. A feature's name opens that feature's page, a person's name theirs.

    THE STEP ITSELF IS THE DOOR, and nothing pops up when it is clicked: the board is a picture to
    read across, and a card over it is in the way. What says "this one" is the step's own BOX, which
    lights on hover and stays lit when a link arrives here naming a step.
    """
    with _served() as url, _page(url + "#v=hp") as page:
        _settle(page)
        page.evaluate("() => document.querySelector('.flow-step').click()")
        _settle(page)
        assert page.evaluate("() => location.hash").startswith("#v=usecase&uc="), \
            page.evaluate("() => location.hash")

        page.evaluate("() => { location.hash = '#v=hp'; }")
        _settle(page)
        page.evaluate("() => document.querySelector('.hp-fname').click()")
        _settle(page)
        assert page.evaluate("() => location.hash").startswith("#v=capability&cap=")

        page.evaluate("() => { location.hash = '#v=hp'; }")
        _settle(page)
        page.evaluate("() => document.querySelector('.hp-one').click()")
        _settle(page)
        assert page.evaluate("() => location.hash").startswith("#v=actor&act=")
        assert not page.js_errors, page.js_errors


def test_a_link_naming_one_step_arrives_scrolled_to_it() -> None:
    """A station on an actor's rail, a feature's rail and a story arrow's label all navigate here
    naming one step. The board has no scene to select into, so it scrolls that step into view and
    rings it — the same answer a card list gives to "show in context". The walk is a stack of rows
    now, so the step is brought into view inside ITS OWN row, which is the only thing that scrolls."""
    with _served() as url, _page(url + "#v=hp&sel=hpstep:HP12") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const el = document.querySelector('.flow-step[data-step="HP12"]');
            if (!el) return null;
            const strip = el.closest('.hp-strip');
            const r = el.getBoundingClientRect(), b = strip.getBoundingClientRect();
            return { onScreen: r.left >= b.left - 1 && r.right <= b.right + 1,
                     row: strip.querySelectorAll('.flow-step').length > 0 };
        }""")
        assert seen == {"onScreen": True, "row": True}, seen
        assert not page.js_errors, page.js_errors


def test_every_feature_box_is_the_same_height_and_the_line_bridges_the_gap() -> None:
    """Two claims the eye makes about the board, and neither is safe to eyeball.

    Every box is as tall as the tallest step title in the WHOLE walk, not as tall as its own: a
    short feature's tint used to end above its neighbours and read as a stub. And the 14px gap the
    boxes now stand apart does not cut the line — a box whose person carries on into the next
    reaches half that gap on each side, so the two read as one line running through them. Only a
    change of PERSON breaks it, and that break carries an arrow head."""
    with _served() as url, _page(url + "#v=hp") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const all = [...document.querySelectorAll('.hp-box')];
            const heights = [...new Set(all.map((b) => Math.round(b.getBoundingClientRect().height)))];
            const px = (el, k) => parseFloat(getComputedStyle(el).getPropertyValue(k)) || 0;
            // Pairs WITHIN a row: two boxes of one person, so the line must cross the gap. Across
            // rows there is nothing to bridge — the row break is the hand-over.
            const gaps = [];
            for (const row of document.querySelectorAll('.hp-row')) {
                const boxes = [...row.querySelectorAll('.hp-box')];
                for (let i = 0; i < boxes.length - 1; i++) {
                    const a = boxes[i].querySelector('.hp-line').getBoundingClientRect();
                    const b = boxes[i + 1].querySelector('.hp-line').getBoundingClientRect();
                    const reach = -px(boxes[i], '--hp-r') - px(boxes[i + 1], '--hp-l');
                    gaps.push({ joined: reach >= b.left - a.right,
                                closes: boxes[i].classList.contains('hp-closes') });
                }
            }
            // …and every part of the wrap must sit ON the line it continues, never near it.
            const off = [];
            document.querySelectorAll('.hp-row').forEach((row, i) => {
                const bs = [...row.querySelectorAll('.hp-box')];
                const f = bs[0].querySelector('.hp-line').getBoundingClientRect();
                const l = bs[bs.length - 1].querySelector('.hp-line').getBoundingClientRect();
                const left = f.left + px(bs[0], '--hp-l');
                const right = l.right + px(bs[bs.length - 1], '--hp-r');
                const mid = f.top + 21;
                const el = row.querySelector('.hp-elbow'), hk = row.querySelector('.hp-hook');
                if (el) {
                    const b = el.getBoundingClientRect();
                    if (Math.abs(b.left - right) > 1 || Math.abs(b.top + 1.5 - mid) > 1) off.push(i);
                }
                if (hk) {
                    const b = hk.getBoundingClientRect();
                    if (Math.abs(b.left + 1.5 - left) > 1.5 || Math.abs(b.bottom - 1.5 - mid) > 1) off.push(i);
                }
            });
            return { heights, gaps, off,
                     rows: document.querySelectorAll('.hp-row').length,
                     arrows: all.filter((b) => b.classList.contains('hp-closes')).length };
        }""")
        assert len(seen["heights"]) == 1, seen["heights"]
        # inside a row the line always crosses, and no box but the last of a row closes
        assert all(g["joined"] and not g["closes"] for g in seen["gaps"]), seen
        # ONE arrow head on the whole board: the walk stops once, at the end
        assert seen["arrows"] == 1 and seen["rows"] == 6, seen
        # every elbow starts at its row's line end, every hook lands on its row's line start
        assert seen["off"] == [], seen
        assert not page.js_errors, page.js_errors


def test_a_board_that_scrolls_sideways_shades_the_edge_there_is_more_on() -> None:
    """A board cut off at the window edge looks like a board that ENDS there. Each edge wears a
    shade, and each is shown only while there is something that way to scroll to — a shade that is
    always there says "more" at the end of the board too, which is a lie about the one thing it
    exists to answer. Walk the board from one end to the other and read which shade is up."""
    with _served() as url, _page(url + "#v=hp") as page:
        # Narrow, so a row HAS something to scroll to. At a wide window every row of the fixture's
        # walk fits, which is the point of the row break — and then there is no shadow to look at.
        page.set_viewport_size({"width": 700, "height": 720})
        _settle(page)
        seen = page.evaluate("""async () => {
            // the WIDEST row: the only one with anything to scroll to
            const board = [...document.querySelectorAll('.hp-strip')]
                .reduce((a, b) => (b.scrollWidth - b.clientWidth > a.scrollWidth - a.clientWidth ? b : a));
            const wrap = board.parentElement;
            // the shades are synced on the board's own scroll event, which is asynchronous
            const settle = () => new Promise((r) => setTimeout(r, 80));
            const at = () => ({ l: wrap.classList.contains('hfade-on-l'),
                                r: wrap.classList.contains('hfade-on-r') });
            const out = { wrapped: wrap.classList.contains('hfade-wrap'),
                          shades: wrap.querySelectorAll('.hfade').length, start: at() };
            board.scrollLeft = Math.round((board.scrollWidth - board.clientWidth) / 2);
            await settle();
            out.middle = at();
            board.scrollLeft = board.scrollWidth;
            await settle();
            out.end = at();
            return out;
        }""")
        assert seen == {"wrapped": True, "shades": 2,
                        "start": {"l": False, "r": True},
                        "middle": {"l": True, "r": True},
                        "end": {"l": True, "r": False}}, seen
        assert not page.js_errors, page.js_errors


def test_a_lane_with_a_fixed_left_part_shadows_it_instead_of_fading_it() -> None:
    """The journey rail's gutter names the two lanes and stays put while the boxes slide under it.
    Fading it out would fade the one thing that is not moving, so it gets no fade over it: it casts
    a shadow to its right instead, and only once the lane has been scrolled. Same signal, drawn the
    way a fixed thing should be."""
    with _served() as url, _page(url + "#v=actor&act=Org%20admin") as page:
        _settle(page)
        seen = page.evaluate("""async () => {
            const board = document.querySelector('.journey-board');
            const wrap = board.parentElement;
            const gutter = board.querySelector('.journey-gutter');
            const read = () => ({
                onL: wrap.classList.contains('hfade-on-l'),
                leftFade: getComputedStyle(wrap.querySelector('.hfade-l')).display,
                shadow: getComputedStyle(gutter).boxShadow !== 'none'
            });
            const out = { start: read() };
            board.scrollLeft = 600;
            await new Promise((r) => setTimeout(r, 80));
            out.scrolled = read();
            return out;
        }""")
        # the left fade is off on this lane at BOTH ends: the gutter answers for that edge
        assert seen["start"] == {"onL": False, "leftFade": "none", "shadow": False}, seen
        assert seen["scrolled"] == {"onL": True, "leftFade": "none", "shadow": True}, seen
        assert not page.js_errors, page.js_errors


def test_the_walk_keeps_the_step_a_link_named_in_the_address() -> None:
    """A link that names one step must still name it once you are there. The board rings the step and
    then the address was rewritten from the page's own state, which for a page with no diagram was
    "nothing selected" — so the address fell back to a bare `#v=hp`, and the link you copied, or a
    reload, came back to step 1. The step is claimed BEFORE the chrome writes the address."""
    with _served() as url, _page(url + "#v=hp&sel=hpstep:HP12") as page:
        _settle(page)
        assert page.evaluate("() => location.hash") == "#v=hp&sel=hpstep%3AHP12"
        page.reload()
        page.wait_for_selector("#crumb h1", state="attached")
        _settle(page)
        seen = page.evaluate("""() => {
            const el = document.querySelector('.flow-step[data-step="HP12"]');
            const b = el.closest('.hp-strip');
            const r = el.getBoundingClientRect(), br = b.getBoundingClientRect();
            return { hash: location.hash, inside: r.left >= br.left - 1 && r.right <= br.right + 1 };
        }""")
        assert seen == {"hash": "#v=hp&sel=hpstep%3AHP12", "inside": True}, seen
        assert not page.js_errors, page.js_errors


def test_back_from_a_step_returns_to_that_step_not_to_the_start_of_the_walk() -> None:
    """Clicking a step and pressing Back put the reader at the start of the walk, screens away from
    where they were, because nothing remembered the place. The step you leave by is now the step you
    come back to: the address names it, and the page arrives scrolled to it."""
    with _served() as url, _page(url + "#v=hp") as page:
        _settle(page)
        left_by = page.evaluate("""() => {
            // a step near the END of the walk, so coming back to the top of the page would miss it
            const all = [...document.querySelectorAll('.flow-step[data-uc]')];
            const el = all[all.length - 1];
            el.scrollIntoView({ block: 'center' });
            el.click();
            return el.dataset.step;
        }""")
        _settle(page)
        assert page.evaluate("() => location.hash").startswith("#v=usecase")
        page.go_back()
        _settle(page)
        seen = page.evaluate("""(step) => {
            const el = document.querySelector(`.flow-step[data-step="${step}"]`);
            const wrap = document.querySelector('.usecases-wrap');
            const r = el.getBoundingClientRect(), w = wrap.getBoundingClientRect();
            return { hash: location.hash, scrolled: wrap.scrollTop > 0,
                     onScreen: r.top >= w.top - 1 && r.bottom <= w.bottom + 1 };
        }""", left_by)
        assert seen == {"hash": "#v=hp&sel=hpstep%3A" + left_by,
                        "scrolled": True, "onScreen": True}, seen
        assert not page.js_errors, page.js_errors


def test_the_walk_offers_no_door_it_cannot_open() -> None:
    """A step the map records with no use case behind it. The generator then invents a driver called
    "Actor", whom the map never declares. Both were drawn as live links: the person to a page that
    knows nothing about them, the step to "Not in this map" under a title promising to open
    something. Both are still DRAWN — the walk really does pass through them — and neither is a
    door. The guard is the one `journeyDriverLabelHtml` has always applied."""
    def strip_the_last_step(m: Any) -> None:
        m["happy_path"][-1]["uc"] = None

    with _served_map(strip_the_last_step) as url, _page(url + "#v=hp") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const person = document.querySelector('.hp-one-dead');
            const step = document.querySelector('.flow-step-dead');
            return {
                personDrawn: !!person, personIsButton: person ? person.tagName === 'BUTTON' : null,
                personName: person ? person.textContent.trim() : null,
                stepDrawn: !!step, stepIsDoor: step ? step.hasAttribute('data-uc') : null,
                stepTitle: step ? step.getAttribute('title') : null,
                liveButtons: document.querySelectorAll('.hp-one').length
            };
        }""")
        assert seen["personDrawn"] and seen["personIsButton"] is False, seen
        assert seen["personName"] == "Actor", seen
        assert seen["stepDrawn"] and seen["stepIsDoor"] is False, seen
        assert seen["stepTitle"] == "This map does not say how this step works", seen
        assert not page.js_errors, page.js_errors


def test_the_arrow_head_that_turns_the_line_down_is_centred_on_it() -> None:
    """An absolutely positioned child is placed against its parent's PADDING box, and the elbow's
    padding box stops inside its own 3px right border. Offset from there, the head sat 3px left of
    the line it ends, which at a 4x zoom is plainly a head beside a line rather than on it.

    Measured, not eyeballed: the head's own centre against the border's own middle, on every elbow."""
    with _served() as url, _page(url + "#v=hp") as page:
        _settle(page)
        off = page.evaluate("""() => {
            const bad = [];
            [...document.querySelectorAll('.hp-elbow')].forEach((el, i) => {
                const b = el.getBoundingClientRect();
                const cs = getComputedStyle(el, '::after');
                const lineX = b.right - 1.5;                       // the 3px border's own middle
                const headRight = (b.right - 3) - parseFloat(cs.right);   // …from the PADDING box
                const headCx = headRight
                    - (parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth)) / 2;
                if (Math.abs(headCx - lineX) > 0.6) {
                    bad.push({ i, headCx: +headCx.toFixed(2), lineX: +lineX.toFixed(2) });
                }
            });
            return bad;
        }""")
        assert off == [], off
        assert page.evaluate("() => document.querySelectorAll('.hp-elbow').length") == 5
        assert not page.js_errors, page.js_errors


def test_the_walk_counts_the_features_it_touches_out_of_all_there_are() -> None:
    """The walk is usually a selection, and the page should say so. It cannot say so in WORDS: on the
    four maps this viewer reads it is 9 of 10 and 8 of 10, but on the other two it is 7 of 7, every
    feature there is — and on any small product the walk naturally covers everything. "A subset of
    the features" would be a plain lie on half of them.

    So it is a count, and the "of N" appears only when there is something left out. The fixture's
    walk misses one feature, so it says "of"; a map whose walk reaches them all says only how many.
    """
    with _served() as url, _page(url + "#v=hp") as page:
        _settle(page)
        # THE COUNT IS THE LANDING HEAD'S, in the strip over the board: "14 steps". The board's own
        # "N steps through M of K features" line went — the head says the steps and the board the
        # features, and a line between the two was a box in a box.
        got = page.evaluate("""() => ({
            count: document.querySelector('.landing-head .count-pill').textContent.trim(),
            ownLine: !!document.querySelector('.item-sec-body > .block-lbl') })""")
        assert got["count"] == "14 steps" and not got["ownLine"], got
        assert not page.js_errors, page.js_errors


# ── the surface's SHAPE, and who is on the far side ─────────────────────────────────────────────
# The committed fixture records no interface at all, which is the empty case the tab is hidden on.
# Both screens below need one, so they mutate the map — the shapes the fixture cannot hold.

def _with_interface(kind: str) -> Any:
    """A `theirs` surface of `kind`, standing on the dependency UC1's walk already steps at (`D4`).

    That step is what the derivation reads on a `theirs` surface — and reads ONLY when the kind
    means a person goes there, which is the whole point of gating it."""
    def mutate(m: dict) -> None:
        m["interfaces"] = [{
            "id": "I1", "name": "Google sign-in", "what": "Where a person proves who they are.",
            "side": "theirs", "facing": "user", "kind": kind
            }]
        for d in m["deps"]:
            if d["id"] == "D4":
                d["interfaces"] = ["I1"]
    return mutate


def test_a_surface_card_says_what_shape_it_is() -> None:
    """"Show me every API this product exposes" was a question a reader answered off the surface's
    NAME, and no tool could answer at all.

    The picture answers it with a GLYPH now, not the word: eleven kinds is more than a reader learns,
    so eight drawings cover them and three groupings are genuinely one thing. `hosted-screen` and
    `screen` are both a browser window, which is what this asserts — the kind is not lost by being
    folded, it is drawn. The WORD is still on the surface's own page, where there is room to read."""
    for kind in ("hosted-screen", "screen"):
        with _served_map(_with_interface(kind)) as url, _page(url + "#v=interfaces") as page:
            _settle(page)
            # `FEATURES` is module-scoped inside viewer.js and unreachable from `evaluate`, so the
            # STORED kind is read back off the served bundle — same origin, so a plain fetch does it.
            box = page.evaluate("""async () => {
                const b = document.querySelector('.ifd-box[data-iface="I1"]');
                const g = b.querySelector('.ibox-head .ibox-gly');
                const v = await (await fetch('api/view')).json();
                return { d: [...g.querySelectorAll('circle, ellipse, rect, path')].map(e =>
                            e.getAttribute('d') || e.tagName.toLowerCase()).join('|'),
                         w: g.getBoundingClientRect().width,
                         word: b.querySelector('.ibox-pill:not(.ibox-pill-alt)').textContent,
                         kind: v.features.interfaces.find(x => x.id === 'I1').kind };
            }""")
            # the GLOBE drawing: a circle, the meridian ellipse across it, and two lines of latitude.
            # It replaced a browser window — a rounded rect with one line near its top, which is the
            # record's own mark at another size, so the two kinds were told apart by colour alone.
            assert box["d"] == "circle|ellipse|M2.3 6.6h13.4M2.3 11.4h13.4", box
            assert 12 <= box["w"] <= 18, box       # sized by CSS, not by the tag's attributes
            # …and the WORD beside it, which is where the glyph stops being enough. `screen` shows as
            # WEBSITE: the map defines the kind as "anything served to a browser", so that is what it
            # has always meant, and "screen" was a word the reader had to translate. The stored kind
            # is untouched — asserted here, since a rename that reached the model would break every
            # map on disk and nothing else in the suite would notice.
            assert box["word"] == ("their website" if kind == "hosted-screen" else "website"), box
            assert box["kind"] == kind, box
            assert not page.js_errors, page.js_errors


def test_a_surface_a_person_goes_to_draws_the_person_and_one_we_merely_call_draws_nobody() -> None:
    """The same surface, the same walk, the same dependency — only the KIND differs, and it decides
    whether anyone is on the far side. Ungated, the join puts human roles behind a server.

    And the empty answer is a SENTENCE, not a blank: "nobody goes there" is the correct answer for a
    crash reporter, and a page that just stopped would read as unfinished."""
    with _served_map(_with_interface("hosted-screen")) as url, \
            _page(url + "#v=interfaces&iface=I1") as page:
        _settle(page)
        names = page.evaluate(
            "() => [...document.querySelectorAll('.ecard[data-key] .ibox-name')]"
            ".map(e => e.textContent)")
        assert "Org creator" in names, names
        assert not page.js_errors, page.js_errors
    with _served_map(_with_interface("api")) as url, \
            _page(url + "#v=interfaces&iface=I1") as page:
        _settle(page)
        names = page.evaluate(
            "() => [...document.querySelectorAll('.ecard[data-key] .ibox-name')]"
            ".map(e => e.textContent)")
        assert names == [], names
        text = page.evaluate("() => document.querySelector('.usecases-wrap').textContent")
        assert "no person goes there" in text, text
        assert not page.js_errors, page.js_errors


def _door_named_ways_in(m: dict) -> None:
    """EVERY CROSSING TAKES A DOOR — the map's own gate, applied to a test map. A mutator that links a
    use case to a surface by naming one of its ways in gets the door step the gate would demand:
    `<the use case's actor> → <the surface>`, at the start of that use case's flow. Since the reach
    rule became the flow alone (`use_case_interfaces`), a way in named without a door reaches
    nothing, exactly as it would on a real map that failed the gate."""
    owner = {ep: i["id"] for i in m.get("interfaces", []) for ep in (i.get("ways_in") or [])}
    flows = {fl["uc"]: fl for fl in m.setdefault("flows", [])}
    for u in m.get("use_cases", []):
        ifaces = sorted({owner[ep] for ep in (u.get("entry_points") or []) if ep in owner})
        actor = (u.get("actors") or [None])[0]
        if not ifaces or not actor:
            continue
        fl = flows.get(u["id"])
        if fl is None:
            fl = {"uc": u["id"], "title": u.get("name", u["id"]), "steps": []}
            m["flows"].append(fl); flows[u["id"]] = fl
        for k, iid in enumerate(ifaces):
            fl["steps"].insert(k, {"n": -1 - k, "src": actor, "dst": iid, "phrase": "opens it", "note": "",
                                   "where": None, "no_call_site": False, "subflow": None})


def _doored(mutate: Any) -> Any:
    """A mutator, then the doors its named ways in owe (see `_door_named_ways_in`)."""
    def both(m: dict) -> None:
        mutate(m)
        _door_named_ways_in(m)
    return both


def _two_sided_interfaces() -> Any:
    """Two surfaces, one on each shore, and BOTH SHAPES the page has to draw: one people come to, one
    only the product reaches.

    I1 holds a way in, so use cases and the people driving them derive onto it. I2 stands on a dep a
    walk step is drawn at, so journeys reach it with nobody at the far side — 5 of MCP Hero's 16 are
    like that, and the box says something different for each."""
    def mutate(m: dict) -> None:
        m["entry_points"][0]["id"] = "EP1"
        for u in m["use_cases"]:
            if u["id"] in ("UC1", "UC2"):
                u["entry_points"] = ["EP1"]
        m["interfaces"] = [
            {"id": "I1", "name": "The dashboard", "what": "Screens a person signs in to.",
             "side": "ours", "facing": "user", "kind": "screen", "ways_in": ["EP1"]
             },
            {"id": "I2", "name": "Crash reporting", "what": "Where a crash is reported.",
             "side": "theirs", "facing": "operator", "kind": "api"
             },
        ]
        for d in m["deps"]:
            if d["id"] == "D4":
                d["interfaces"] = ["I2"]
    return _doored(mutate)


def test_every_surface_draws_one_plain_line_to_the_product() -> None:
    """ONE LINE PER SURFACE, and it says only that this surface is one of the places the product
    meets the outside.

    NO HEADS. They carried the crossings' `in` and `out`, and the page stopped reading the crossings:
    what data moves turned out to be a written summary of what the walks already show, so the page
    reads the walks instead. Deriving a head from the walks would be a guess dressed as a fact —
    they disagree with the map's own answer on one of MCP Hero's sixteen surfaces."""
    with _served_map(_two_sided_interfaces()) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        got = page.evaluate("""() => {
            const out = {};
            for (const p of document.querySelectorAll('#ifdstage path[data-iface]'))
                (out[p.dataset.iface] = out[p.dataset.iface] || []).push({
                    start: !!p.getAttribute('marker-start'),
                    end: !!p.getAttribute('marker-end') });
            return { wires: out,
                     cards: [...document.querySelectorAll('.ifd-box')].map(b => b.dataset.iface) };
        }""")
        # EVERY card is joined, including one no use case reaches — the line is membership, not traffic
        for iid in got["cards"]:
            assert len(got["wires"].get(iid, [])) == 1, (iid, got)
            assert got["wires"][iid][0] == {"start": False, "end": False}, (iid, got)
        assert not page.js_errors, page.js_errors


def test_hovering_a_surface_lights_its_line_and_says_who_comes_and_what_for() -> None:
    """At rest every line is grey and unlabelled. Hover makes ONE surface the picture, and its box
    answers the page's question for that surface: who comes here, and what brings them.

    It used to say what DATA crosses. That is authored on the surface, and it is a written summary of
    what the walks already show — so the page reads the walks, and the two can no longer drift."""
    with _served_map(_two_sided_interfaces()) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        page.hover('.ifd-box[data-iface="I1"]')
        page.wait_for_timeout(250)
        shown = page.evaluate("""() => {
            const on = [...document.querySelectorAll('.ifd-elabel.ifd-lab-on')];
            return {
                hot: [...document.querySelectorAll('#ifdstage path.ifd-hot')]
                        .map(p => p.dataset.iface),
                cold: [...document.querySelectorAll('#ifdstage path.ifd-cold')]
                        .map(p => p.dataset.iface),
                labels: on.length,
                heads: on.flatMap(l => [...l.querySelectorAll('.ifd-elabel-dir')]
                                        .map(e => e.textContent)),
                doors: on.flatMap(l => [...l.querySelectorAll('.ifd-elabel-uc')]
                                        .map(e => e.textContent))
            };
        }""")
        assert set(shown["hot"]) == {"I1"}, shown
        assert set(shown["cold"]) == {"I2"}, shown
        assert shown["labels"] == 1, shown
        # a heading per person, naming them and counting what brings them
        assert shown["heads"] and all("use case" in h for h in shown["heads"]), shown
        # …and each use case under it is a door
        assert shown["doors"], shown
        assert not page.js_errors, page.js_errors


def test_what_we_own_holds_the_product_and_our_surfaces_and_keeps_its_distance() -> None:
    """The dashed box makes a claim, and it is asserted as a claim rather than as a drawing: the
    product and every surface we define are inside it, every surface we use is outside.

    A ring around the CIRCLE alone was built first and was false — the map's own words say an
    our-surface is one whose shape we define, so our dashboard and our command line ARE the product,
    and a ring left them outside it.

    AND IT KEEPS ITS DISTANCE. Stretched to the grid it drew its left border exactly on the cards'
    left edge and its top border through the `We define` heading, and its own title fell off the top
    of what the page will paint. `.ifd-wrap` is what clips the picture, so the room it needs had to
    come from there without moving the stage — the cards still share the breadcrumb's left edge.

    Three widths, because the gutters are `1fr`: a fixed width was right at 1440 and ran across the
    cards at 1024."""
    with _served_map(_two_sided_interfaces()) as url, _page(url + "#v=interfaces") as page:
        for width in (1440, 1280, 1024):
            page.set_viewport_size({"width": width, "height": 900})
            _settle(page)
            m = page.evaluate("""() => {
                const own = document.querySelector('.ifd-own');
                const o = own.getBoundingClientRect();
                const inside = (r) => r.left >= o.left && r.right <= o.right
                                   && r.top >= o.top && r.bottom <= o.bottom;
                const rects = (sel) => [...document.querySelectorAll(sel + ' .ifd-box')]
                    .map(c => c.getBoundingClientRect());
                const t = rects('.ifd-col-theirs');
                const stage = document.getElementById('ifdstage');
                const wrap = stage.parentElement;
                const w = wrap.getBoundingClientRect();
                const title = own.querySelector('span').getBoundingClientRect();
                const card = rects('.ifd-col-ours')[0];
                const head = document.querySelector('.ifd-col-ours .ifd-colhead')
                    .getBoundingClientRect();
                return {
                    holdsHub: inside(document.getElementById('ifdhub').getBoundingClientRect()),
                    ours: rects('.ifd-col-ours').map(inside),
                    // a their-surface must be wholly clear of it, not merely not-contained
                    theirsClear: t.every(r => r.left >= o.right),
                    hits: getComputedStyle(own).pointerEvents,
                    gapLeft: card.left - o.left,
                    gapRight: t.length ? t[0].left - o.right : 99,
                    belowHeading: o.top - head.bottom,
                    cardsSetTheTop:
                        document.querySelector('.ifd-col-ours .ifd-box').offsetTop
                        <= document.getElementById('ifdhub').offsetTop,
                    aboveFirstCard: card.top - o.top,
                    // `.ifd-wrap` is what clips, so "drawn whole" means inside ITS box
                    titleWhole: title.top >= w.top && title.bottom <= w.bottom
                             && title.left >= w.left && title.right <= w.right,
                    noScroll: wrap.scrollWidth === wrap.clientWidth
                           && wrap.scrollHeight === wrap.clientHeight,
                    // …and the picture still starts where the rest of the page does
                    stageLeft: Math.round(stage.getBoundingClientRect().left)
                };
            }""")
            assert m["holdsHub"], (width, m)
            assert m["ours"] and all(m["ours"]), (width, m)
            assert m["theirsClear"], (width, m)
            assert m["hits"] == "none", (width, m)   # it must not eat the click that drops the pin
            assert m["gapLeft"] >= 10, (width, m)
            assert m["gapRight"] >= 10, (width, m)
            assert m["aboveFirstCard"] >= 6, (width, m)
            # THE HEADING IS ONLY CLEARED WHERE THE CARDS SET THE TOP. On a picture this short the
            # circle is the tallest thing in it and starts at the stage's own edge, so holding the
            # product wins and the heading ends up inside the box — which is not wrong, since the
            # surfaces `We define` heads are the product too.
            if m["cardsSetTheTop"]:
                assert m["belowHeading"] >= 6, (width, m)
            assert m["titleWhole"], (width, m)
            assert m["noScroll"], (width, m)
        assert not page.js_errors, page.js_errors


def test_the_picture_fits_without_pushing_the_page_sideways() -> None:
    """Five columns against the Features page's three. Five columns of CARDS would be about 1900px
    and would not fit 1440, which is why the product is a narrow spine and the two outer columns
    hold chips. MEASURED, never eyeballed."""
    with _served_map(_two_sided_interfaces()) as url, _page(url + "#v=interfaces") as page:
        for width in (1440, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            _settle(page)
            m = page.evaluate("""() => {
                const st = document.getElementById('ifdstage');
                const wrap = st.parentElement;
                return { doc: document.documentElement.scrollWidth, win: window.innerWidth,
                         overflows: wrap.scrollWidth > wrap.clientWidth };
            }""")
            assert m["doc"] <= m["win"], (width, m)
            assert not m["overflows"], (width, m)
        assert not page.js_errors, page.js_errors


def test_a_surface_with_no_kind_still_draws_a_box() -> None:
    """Degrading: no `kind` recorded means the default outline and no word. The picture still
    draws — it is never allowed to invent a shape the map did not author."""
    def mutate(m: dict) -> None:
        _two_sided_interfaces()(m)
        m["interfaces"][0]["kind"] = ""
    with _served_map(mutate) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        got = page.evaluate("""() => {
            const b = document.querySelector('.ifd-box[data-iface="I1"]');
            return { name: b.querySelector('.ibox-name').textContent,
                     glyphs: b.querySelectorAll('.ibox-head .ibox-gly').length };
        }""")
        # It draws, it is named, and it takes the FALLBACK glyph rather than none: a box with a hole
        # where every sibling has a mark reads as a rendering fault, not as a missing field.
        assert got["name"] == "The dashboard", got
        assert got["glyphs"] == 1, got
        assert not page.js_errors, page.js_errors


def test_the_picture_is_the_list_and_there_is_no_second_copy_under_it() -> None:
    """This REPLACES a test that asserted the opposite, and the reason it flipped is the picture.

    There were two card lists under it, "Our surfaces" and "Their surfaces", on the rule that a
    picture is not a replacement for a list you can read down. That rule was right about the old
    picture, whose boxes were a name and two words. It is not right about this one: the boxes ARE
    cards, in a stated order, carrying the same sentence the list carried. Keeping both drew every
    surface twice on one page — and those two headings were the last place the words "our surface"
    and "their surface" survived."""
    with _served_map(_two_sided_interfaces()) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        got = page.evaluate("""() => ({
            boxes: [...document.querySelectorAll('.ifd-box')].map(
                b => b.querySelector('.ibox-name').textContent),
            sentences: [...document.querySelectorAll('.ifd-box .ibox-what')].map(e => e.textContent),
            cards: document.querySelectorAll('.usecases-wrap .ecard[data-key]').length,
            text: document.querySelector('.usecases-wrap').textContent
        })""")
        assert sorted(got["boxes"]) == ["Crash reporting", "The dashboard"], got
        assert "Screens a person signs in to." in got["sentences"], got
        assert got["cards"] == 0, got                       # no second copy
        assert "Our surfaces" not in got["text"], got       # and the words are gone with it
        assert "Their surfaces" not in got["text"], got
        assert not page.js_errors, page.js_errors


def _both_shores_carry_people_and_a_pipe() -> Any:
    """One surface on EACH shore that has both a person standing at it and a pipe it is reached
    through — the shape the picture used to draw only half of.

    The person on the `ours` surface arrives through a DOOR (`R1 → I1`), which is the arm that fills
    the far side on most surfaces and the reason this shape is now common: 9 chips across the two
    live maps were derived and undrawn. The person on the `theirs` surface comes from the walk
    reaching `D4`, gated on a kind that means a person goes there."""
    def mutate(m: dict) -> None:
        # A WAY IN on the dashboard, because that is what a screen people come to HAS. `opens` is
        # derived from it, and `opens` is what the actor page cuts its two groups by — a surface with
        # no address anything outside can invoke is one the product starts the exchange at.
        m["entry_points"] = (m.get("entry_points") or []) + [
            {"id": "EP900", "kind": "HTTP route", "trigger": "`GET /dashboard`",
             "source": "backend/src/mcpolis/entrypoints/app.py:1", "component": "C1"}]
        m["interfaces"] = [
            {"id": "I1", "name": "The dashboard", "what": "Screens a person signs in to.",
             "side": "ours", "facing": "user", "kind": "screen", "ways_in": ["EP900"]
             },
            {"id": "I2", "name": "Google sign-in", "what": "Where a person proves who they are.",
             "side": "theirs", "facing": "user", "kind": "hosted-screen"
             },
        ]
        for d in m["deps"]:
            if d["id"] == "D4":
                d["interfaces"] = ["I2"]
            if d["id"] == "D6":
                d["interfaces"] = ["I1"]
        for f in m["flows"]:
            if f["uc"] == "UC1":
                f["steps"].insert(0, {"n": 0, "src": "R1", "dst": "I1",
                                      "phrase": "opens the dashboard", "note": "", "where": None,
                                      "no_call_site": False, "subflow": None})
                # …and a step at the `theirs` surface, naming NOBODY. The left column of this
                # picture is the walk now, so a surface with no step there has an empty cell and
                # draws one wire, not two — and an unattributed step is what the fallback shows.
                f["steps"].insert(1, {"n": -1, "src": "C1", "dst": "I2",
                                      "phrase": "sends them to Google to sign in", "note": "",
                                      "where": "backend/src/mcpolis/entrypoints/app.py:4",
                                      "no_call_site": False, "subflow": None})
    return mutate


def test_the_picture_draws_the_people_and_the_pipe_on_both_shores() -> None:
    """The two shores were drawing DIFFERENT HALVES of the same fact: `ours` drew the people and
    dropped the pipes, `theirs` drew the pipes and dropped the people. Nine things the two live maps
    state went undrawn — coyomap's Agent skill reaches three agent hosts, its GitHub and code-editor
    handoffs each have a reader standing at them, mcpolis mails through a service and sends three
    people to Google. Every one of them was already on the surface's own page.

    Both now live INSIDE the card, so the two halves cannot drift apart again — there is no longer a
    per-shore builder to get wrong. The ORDER is still asserted, and it is the same on both shores:
    the far side is the answer, the pipe is only how it is reached, so the person is never second."""
    with _served_map(_both_shores_carry_people_and_a_pipe()) as url, \
            _page(url + "#v=interfaces") as page:
        _settle(page)
        cells = page.evaluate("""() => {
            const out = {};
            for (const b of document.querySelectorAll('.ifd-box')) {
                out[b.dataset.iface] = [
                    ...[...b.querySelectorAll('.item-pill')].map(e => 'who:' + e.textContent),
                    ...[...b.querySelectorAll('.ifd-prov')].map(e => 'pipe:' + e.textContent)];
            }
            return out;
        }""")
        assert cells["I1"] == ["who:Org creator", "pipe:SMTP / Google Workspace"], cells
        assert cells["I2"] == ["who:Org creator", "who:Team member",
                               "pipe:Google OAuth IdP"], cells
        assert not page.js_errors, page.js_errors


# ── the map inspector (Ctrl+Shift) ───────────────────────────────────────────────────────────────
# These are browser tests because the whole feature IS browser behaviour: which DOM element the
# cursor is over, which listener sees the click first, and what the popup then says. A source-text
# assertion could not tell any of that apart from a resolver that silently finds nothing.

_INSPECT_JS = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return { error: 'no element for ' + sel };
  const opts = { bubbles: true, cancelable: true, view: window, ctrlKey: true, shiftKey: true };
  el.dispatchEvent(new MouseEvent('mousemove', opts));
  el.dispatchEvent(new MouseEvent('click', opts));
  return { ok: true };
}
"""
_READ_POP_JS = """
() => {
  const pop = document.querySelector('.insp-pop');
  if (!pop || pop.hidden) return { open: false };
  return {
    open: true,
    kind: pop.querySelector('.insp-kind').textContent,
    path: pop.querySelector('.insp-path').textContent.replace('project-map.json › ', ''),
    body: pop.textContent,
    refs: [...pop.querySelectorAll('.insp-ref')].map((r) => r.textContent)
  };
}
"""


def _inspect(page: Any, selector: str) -> dict:
    """Ctrl+Shift+click `selector` and read the popup. The wait covers the stored map's own fetch:
    the first such click of a session lands before /api/rawmap has answered, and the handler holds
    the click until it does."""
    started = page.evaluate(_INSPECT_JS, selector)
    assert "error" not in started, started
    page.wait_for_timeout(700)
    return dict(page.evaluate(_READ_POP_JS))


def test_the_inspector_answers_with_the_record_the_map_stores() -> None:
    """The whole point: the popup says WHICH slot of the stored file drew this box, and what that
    slot holds — not what the view bundle made of it."""
    with _served() as url, _page(url + "#v=features") as page:
        _settle(page)
        got = _inspect(page, ".story-card.story-feature[data-sfeat]")
        assert got["open"], got
        assert got["kind"] == "feature", got
        assert re.fullmatch(r"capabilities\[\d+\]", got["path"]), got
        assert '"id"' in got["body"] and '"purpose"' in got["body"], got
        assert not page.js_errors, page.js_errors


def test_a_click_without_both_keys_is_an_ordinary_click() -> None:
    """The inspector overlaps two bindings that already exist (⌘ multi-selects, Shift frames), so
    the one thing it must never do is change what a plain click means."""
    with _served() as url, _page(url + "#v=features") as page:
        _settle(page)
        page.click(".story-card.story-feature[data-sfeat] button")
        _settle(page)
        pop = page.evaluate(_READ_POP_JS)
        assert not pop["open"], pop
        # The way here reads in the head's path line: this feature's page sits under Features.
        assert page.evaluate("() => [...document.querySelectorAll('.page-path-seg')].map((e) => e.textContent)") == ["Features"]
        assert not page.js_errors, page.js_errors


def test_the_smaller_things_answer_too_not_just_the_boxes() -> None:
    """A step of the happy path and a way in are drawn from records of their own, and neither carries
    an id on screen: the step is found by its id attribute, the way in by its POSITION in one
    component's list. Both were invisible to a resolver that only knew about drawn boxes."""
    with _served() as url, _page(url + "#v=hp") as page:
        _settle(page)
        step = _inspect(page, ".flow-step[data-step]")
        assert step["open"] and step["kind"] == "happy-path step", step
        assert re.fullmatch(r"happy_path\[\d+\]", step["path"]), step
        assert not page.js_errors, page.js_errors
    # A component's own details page is where a way in is drawn ("Triggered by"); the info pane
    # beside a diagram carries only the card.
    with _served() as url, _page(url + "#v=element&id=C1") as page:
        _settle(page)
        way = _inspect(page, ".tb-ep[data-ep-idx]")
        assert way["open"] and way["kind"] == "way in", way
        assert re.fullmatch(r"entry_points\[\d+\]", way["path"]), way
        assert not page.js_errors, page.js_errors


def test_an_id_inside_a_record_opens_that_record_and_back_returns() -> None:
    """A record is mostly ids pointing at other records, and reading one by hand meant scrolling the
    file. Following one must also be undoable, or the popup is a one-way trip."""
    with _served() as url, _page(url + "#v=hp") as page:
        _settle(page)
        first = _inspect(page, ".flow-step[data-step]")
        assert first["open"], first
        moved = page.evaluate("""
            () => {
              const pop = document.querySelector('.insp-pop');
              const r = [...pop.querySelectorAll('.insp-ref')].find((x) => /^UC\\d+$/.test(x.textContent));
              if (!r) return { error: 'no use-case id in the step record' };
              r.click();
              return { ok: true };
            }""")
        assert "error" not in moved, moved
        page.wait_for_timeout(300)
        after = dict(page.evaluate(_READ_POP_JS))
        assert after["kind"] == "use case", after
        assert re.fullmatch(r"use_cases\[\d+\]", after["path"]), after
        page.click(".insp-pop .insp-back")
        page.wait_for_timeout(300)
        back = dict(page.evaluate(_READ_POP_JS))
        assert back["path"] == first["path"], (back, first)
        assert not page.js_errors, page.js_errors


def test_a_click_on_something_the_map_does_not_store_says_so() -> None:
    """Silence is the one answer a debug tool must not give: it makes a resolver gap and a broken
    tool look identical. A miss reports what the click landed on instead."""
    with _served() as url, _page(url + "#v=features") as page:
        _settle(page)
        got = _inspect(page, "#crumb")
        assert got["open"], got
        assert got["kind"] == "not stored", got
        assert got["path"] == "—", got
        assert "Nothing under the cursor" in got["body"], got
        assert not page.js_errors, page.js_errors


def test_the_stored_map_is_served_byte_for_byte() -> None:
    """The path the popup prints is only useful if it names a slot in the file on disk, which needs
    the endpoint to hand over that file rather than a re-serialisation of the model."""
    import urllib.request
    with _served() as url:
        with urllib.request.urlopen(url + "api/rawmap") as r:
            body = r.read()
        assert body == _FIXTURE_MAP.read_bytes()


def test_the_secondary_click_opens_it_too_and_no_native_menu_appears() -> None:
    """macOS makes Control-click the SECONDARY click: the system turns it into a context menu and no
    ordinary click is ever produced. Held to `click` alone, the gesture opened the browser's own menu
    and nothing else — on the one platform this tool is written for."""
    with _served() as url, _page(url + "#v=features") as page:
        _settle(page)
        prevented = page.evaluate("""
            () => {
              const el = document.querySelector('.story-card.story-feature[data-sfeat]');
              const e = new MouseEvent('contextmenu',
                { bubbles: true, cancelable: true, view: window, ctrlKey: true, shiftKey: true });
              el.dispatchEvent(e);
              return e.defaultPrevented;
            }""")
        assert prevented, "the native context menu was left to open"
        page.wait_for_timeout(700)
        got = dict(page.evaluate(_READ_POP_JS))
        assert got["open"] and got["kind"] == "feature", got
        assert not page.js_errors, page.js_errors


def test_while_the_two_keys_are_held_the_page_itself_is_deaf() -> None:
    """The gesture overlaps two live bindings (⌘ multi-selects on ctrlKey, the arrow handlers on
    shiftKey), and panning, wheel-zoom, hover and the double-click drill all went on running under
    the inspector. Held, the page must receive nothing; released, it must receive everything."""
    probe = """
        () => {
          window.__seen = [];
          for (const t of ['mousedown', 'mouseup', 'click', 'dblclick', 'contextmenu', 'wheel'])
            document.addEventListener(t, (e) => window.__seen.push(t), false);
        }"""
    fire = """
        (held) => {
          const el = document.querySelector('.story-card.story-feature[data-sfeat]');
          const mods = held ? { ctrlKey: true, shiftKey: true } : {};
          const o = { bubbles: true, cancelable: true, view: window, ...mods };
          for (const t of ['mousedown', 'mouseup', 'dblclick', 'contextmenu'])
            el.dispatchEvent(new MouseEvent(t, o));
          el.dispatchEvent(new WheelEvent('wheel', { ...o, deltaY: -240 }));
          return window.__seen.slice();
        }"""
    with _served() as url, _page(url + "#v=features") as page:
        _settle(page)
        page.evaluate(probe)
        held = page.evaluate(fire, True)
        assert held == [], held
        page.evaluate("() => { window.__seen = []; }")
        free = page.evaluate(fire, False)
        assert set(free) == {"mousedown", "mouseup", "dblclick", "contextmenu", "wheel"}, free
        assert not page.js_errors, page.js_errors


def test_the_pinned_section_bar_casts_a_shadow_only_once_it_is_attached() -> None:
    """A sticky bar looks identical pinned and at rest, so nothing on screen says whether the page is
    running underneath it or has simply ended there. A shadow falling from its grey line is what says
    it — and only while it is attached, or the shadow becomes decoration on a strip sitting in the
    flow with the page's own top edge right above it.

    A sticky element has no CSS state of its own, so the reading is geometric: the bar is attached
    exactly when it has reached its own `top: 0` and stopped travelling with the page.

    The TRANSITION is suppressed for the measurement. It is 150ms of real animation, and a headless
    run reads a frame partway through it — the shadow then computes as a transparent zero and the
    test fails on timing rather than on the rule."""
    # THE LONGEST PANEL, because the strip only pins on a page that scrolls. The feature page draws
    # ONE panel now — the strip switches between them rather than stacking them — so the use-case
    # panel it used to open on is no longer tall enough to push the strip to its own top at any
    # window this test can set. Components is the long one (measured: 1262px for 28 parts in 11
    # containers), and it is where a reader most wants to switch away without scrolling back.
    with _served() as url, _page(url + "#v=capability&cap=CAP2&sec=comps") as page:
        # A SHORT WINDOW, so the page is taller than the pane and the bar can pin at all. The default
        # is tall enough to hold this panel, and a bar that never reaches its own top tests nothing.
        page.set_viewport_size({"width": 1280, "height": 520})
        _settle(page)
        out = page.evaluate("""() => {
            const w = document.querySelector('.usecases-wrap');
            const nav = w.querySelector('.tab-index');
            if (!nav) return {noBar: true};
            nav.style.transition = 'none';
            const read = () => ({stuck: nav.classList.contains('tab-index-stuck'),
                                 shadow: getComputedStyle(nav).boxShadow});
            w.scrollTop = 0; w.dispatchEvent(new Event('scroll'));
            const rest = read();
            // How far this page must scroll before the bar reaches its own top at all.
            const reach = nav.getBoundingClientRect().top - w.getBoundingClientRect().top;
            w.scrollTop = w.scrollHeight; w.dispatchEvent(new Event('scroll'));
            const stuck = read();
            w.scrollTop = 0; w.dispatchEvent(new Event('scroll'));
            const back = read();
            nav.style.transition = '';
            return {rest, stuck, back, reach, room: w.scrollHeight - w.clientHeight};
        }""")
        assert not out.get("noBar"), out
        assert out["room"] > out["reach"], ("the page must be tall enough to pin the bar at all", out)
        assert out["rest"] == {"stuck": False, "shadow": "none"}, out
        assert out["stuck"]["stuck"] and out["stuck"]["shadow"] != "none", out
        # …and it is cast DOWNWARD only: a positive y with a negative spread, so it never haloes the
        # bar's own sides, where it would read as a floating panel rather than an edge.
        assert "0px 5px" in out["stuck"]["shadow"] and "-6px" in out["stuck"]["shadow"], out
        assert out["back"] == {"stuck": False, "shadow": "none"}, ("…and it lets go", out)
        assert not page.js_errors, page.js_errors


def test_an_item_pages_sections_each_say_what_they_are_and_what_is_in_them() -> None:
    """A page about one element is a stack of sections, and each one has to answer three questions on
    its own: what is this, how much of it is there, and what am I looking at. The actor page answered
    none of them. Its board carried the actor's own figure and name — which the hero one line above
    had just drawn — and nothing said the boxes were USE CASES, or which use cases were in there and
    which were not.

    Three parts, and none of them is decoration: the heading names the section, the count states its
    size, and the sentence says what is in it. A pinned chip bar indexes them, so a reader knows what
    the page holds before scrolling and can jump between the parts.

    NO HEIGHT CAP anywhere. The picture inside a section is drawn as tall as it needs to be, so
    nothing scrolls vertically inside itself; the page scrolls, once. Sideways is a different matter —
    the board is genuinely wider than any window, and that scroll stays."""
    with _served_map(_both_shores_carry_people_and_a_pipe()) as url, \
            _page(url + "#v=actor&act=Org creator") as page:
        _settle(page)
        secs = page.evaluate("""() => [...document.querySelectorAll('.item-sec')].map((s) => ({
            // The title's own words: its mark (an svg) leads it, its count pill follows it.
            title: [...s.querySelector('.item-sec-title').childNodes].filter((n) => n.nodeType === 3)
                     .map((n) => n.textContent).join('').trim(),
            strip: !!s.querySelector('.item-sec-frame > .item-sec-strip .item-sec-title'),
            mark: !!s.querySelector('.item-sec-title .ibox-gly'),
            count: s.querySelector('.count-pill').textContent,
            note: s.querySelector('.item-sec-note').textContent.slice(0, 24)
        }))""")
        # ONE section. The Interfaces block under it went, and with it the chip strip that only
        # exists to index several — the board names every interface on the use case itself now.
        assert [s["title"] for s in secs] == ["Use cases"], secs
        # A BOARD'S HEAD RIDES ITS FRAME, led by the use case mark: as page text it sat between the hero
        # card and the frame, 22px under one and 9px over the other, belonging to neither.
        assert all(s["strip"] and s["mark"] for s in secs), secs
        assert all(s["note"] and s["count"] != "" for s in secs), secs
        # NO BAR. It indexed several sections and there is one; `tabIndexHtml` returns nothing below
        # two, and the page no longer asks it. The mechanism itself is pinned on a page that has
        # several — see the actor-page test that checks a feature's page still builds one.
        chips = page.evaluate("() => document.querySelectorAll('.tab-index-chip').length")
        assert chips == 0, chips
        # …and the actor's name is drawn ONCE in the page body, by the hero.
        names = page.evaluate(
            "() => [...document.querySelectorAll('#diagram .page-hero-subject,"
            " #diagram .journey-actorname')].map((e) => e.textContent)")
        assert names == ["Org creator"], names
        # NOTHING SCROLLS VERTICALLY inside a section — not the frame, not anything in it.
        tall = page.evaluate("""() => {
            const bad = [];
            for (const f of document.querySelectorAll('.item-sec-frame'))
              for (const el of [f, ...f.querySelectorAll('*')])
                if (el.scrollHeight > el.clientHeight + 1
                    && ['auto', 'scroll'].includes(getComputedStyle(el).overflowY))
                  bad.push(el.className);
            return bad;
        }""")
        assert tall == [], tall
        # The hero's rule went with them: the page is a stack of announced sections now. The hero is a
        # BAND — a wash of its kind's colour with a hairline all the way round — so what is not there
        # is a rule UNDER it: any border it has is the same on every side.
        hero = page.evaluate(
            "() => { const cs = getComputedStyle(document.querySelector('#diagram .page-hero'));"
            "  return {b: cs.borderBottomWidth, t: cs.borderTopWidth, bg: cs.backgroundColor,"
            "          p: parseFloat(cs.paddingTop)}; }")
        assert hero["b"] == hero["t"] and hero["p"] >= 14, hero
        assert hero["bg"] != "rgba(0, 0, 0, 0)", "a named hero sits on a band of its kind's colour"
        # …and the GREY LINE is between the sections, with room on both sides of it. Never above the
        # first: the chip bar draws its own line under itself and a second one below it is two rules
        # for one boundary.
        rules = page.evaluate("""() => [...document.querySelectorAll('.item-sec')].map((s) => {
            const cs = getComputedStyle(s);
            return {top: parseFloat(cs.borderTopWidth), pad: parseFloat(cs.paddingTop),
                    below: parseFloat(cs.marginBottom)};
        })""")
        assert rules[0]["top"] == 0, rules
        # THE MULTI-SECTION PROMISES LEFT THIS TEST WITH THE SECOND SECTION. The grey rule between
        # two of them, the air above and below it, and a chip landing on the title it names are all
        # promises about a STACK, and this page is one section now. They are NOT re-checked here
        # against a feature's page: driving a second view out of this fixture inside one browser
        # context did not render its sections, and a check that silently sees zero of them is worse
        # than none. `test_the_pinned_bar_...` still exercises the bar itself on a feature's page.
        # Written down rather than quietly dropped: this spacing has no test right now.
        assert not page.js_errors, page.js_errors
        assert not page.js_errors, page.js_errors


# SIX TESTS OF THE ACTOR PAGE'S INTERFACES BLOCK WERE HERE, and they went with the block: the
# shores it cut by, the features column beside each surface, the picture's wires and their
# behaviour on a resize, the leak of another person's step into a cell, and the sentence an actor
# at no surface got. Each pinned a promise the page no longer makes — the board names every
# interface on the use case that reaches it, and the surfaces themselves are the Interfaces
# view's subject, whose own tests are untouched below.

def _walk_ordered_interfaces() -> Any:
    """Four surfaces the walk reaches in a KNOWN order, and two it never reaches.

    UC1 is the fixture's first happy-path use case and its flow steps at `D4`; UC2 comes later.

    THE IDS DISAGREE WITH THE WALK ON PURPOSE. "First" is `I9` and "Second" is `I2`, so a build that
    lost the walk order and fell back to sorting by id would put them the other way round. Without
    that the test passes against no ordering at all — which it did, until a mutation said so."""
    def mutate(m: dict) -> None:
        m["interfaces"] = [
            {"id": "I3", "name": "Late and staffy", "what": "Never on the walk, operator-facing.",
             "side": "ours", "facing": "operator", "kind": "screen"
             },
            {"id": "I2", "name": "Second", "what": "Reached later on the walk.",
             "side": "ours", "facing": "user", "kind": "screen"
             },
            {"id": "I5", "name": "Never", "what": "Never on the walk, user-facing.",
             "side": "ours", "facing": "user", "kind": "screen"
             },
            {"id": "I9", "name": "First", "what": "Reached at the start of the walk.",
             "side": "ours", "facing": "user", "kind": "screen"
             },
            {"id": "I4", "name": "Theirs on the walk", "what": "Stands on the dep UC1 steps at.",
             "side": "theirs", "facing": "user", "kind": "api"
             },
        ]
        for d in m["deps"]:
            if d["id"] == "D4":
                d["interfaces"] = ["I4"]
        door = {"phrase": "opens it", "note": "", "where": None, "no_call_site": False,
                "subflow": None}
        for f in m["flows"]:
            if f["uc"] == "UC1":
                f["steps"].insert(0, dict(door, n=0, src="R1", dst="I9"))
            if f["uc"] == "UC2":
                f["steps"].insert(0, dict(door, n=0, src="R2", dst="I2"))
    return mutate


def test_the_picture_reads_down_in_the_order_the_walk_touches_each_surface() -> None:
    """The same rule the Features page's column uses, applied to surfaces: first touch on the happy
    path, unbroken, then the ones the walk never reaches in a block after it.

    On MCP Hero that reads as the product's own story — a prospect reads the public website, signs up
    on the dashboard, a member uses the gateway, an operator the console — and it puts the one staff
    surface last WITHOUT a staff rule, because the operator's steps are the end of the walk. The
    untouched block keeps user-before-staff, since the walk has nothing to say about a surface it
    never reaches."""
    with _served_map(_walk_ordered_interfaces()) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        got = page.evaluate("""() => ({
            ours: [...document.querySelectorAll('.ifd-col-ours .ibox-name')].map(e => e.textContent),
            theirs: [...document.querySelectorAll('.ifd-col-theirs .ibox-name')].map(e => e.textContent)
        })""")
        assert got["ours"] == ["First", "Second", "Never", "Late and staffy"], got
        assert got["theirs"] == ["Theirs on the walk"], got
        assert not page.js_errors, page.js_errors


def test_the_people_at_a_surface_are_ordered_by_the_happy_path() -> None:
    """Surfaces are sorted by where the product's own story first reaches them, and so are the people
    inside each one. On MCP Hero's dashboard that is Visitor, then Organization admin, then Team
    member — the sequence the story takes, not the alphabet and not who is busiest.

    Ordering by size was tried first and reads as a ranking, which is a claim the map does not make.
    The story order is a fact it does."""
    def mutate(m: dict) -> None:
        # Two of the fixture's own use cases on one surface, driven by two different people. The
        # happy path takes UC1 (Org creator) before UC2 (Org admin), and the ALPHABET takes them the
        # other way round — so a page sorted by name and a page sorted by the story disagree here.
        m["entry_points"][0]["id"] = "EP1"
        for u in m["use_cases"]:
            if u["id"] in ("UC1", "UC2"):
                u["entry_points"] = ["EP1"]
        m["interfaces"] = [
            {"id": "I1", "name": "The door", "what": "One surface.", "side": "ours",
             "facing": "user", "kind": "screen", "ways_in": ["EP1"] },
        ]
    with _served_map(_doored(mutate)) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        page.hover('.ifd-box[data-iface="I1"]')
        page.wait_for_timeout(250)
        got = page.evaluate("""() => ({
            chips: [...document.querySelectorAll('.ifd-box[data-iface="I1"] .item-pill')]
                     .map(e => e.textContent.trim()),
            heads: [...document.querySelectorAll('.ifd-elabel.ifd-lab-on .ifd-elabel-dir')]
                     .map(e => e.textContent)
        })""")
        # `Org admin` wins the alphabet; `Org creator` comes first on the story, and wins here.
        assert got["chips"] == ["Org creator", "Org admin"], got
        # The name is its own button now, so the space before the dot is a flex gap rather than a
        # character: split on the dot itself.
        assert [h.split("·")[0].strip() for h in got["heads"]] == ["Org creator", "Org admin"], got
        assert not page.js_errors, page.js_errors


def test_a_surface_no_use_case_reaches_is_drawn_quiet_and_sorted_last() -> None:
    """Three of MCP Hero's sixteen surfaces are named by no use case at all. A surface off the happy
    path but used by some journey is still part of the product's work; one no journey names is a
    different thing, and both the order and the drawing say so.

    Zero is A REAL ANSWER, said in words rather than as an empty space."""
    def mutate(m: dict) -> None:
        m["entry_points"][0]["id"] = "EP1"
        for u in m["use_cases"]:
            if u["id"] == "UC1":
                u["entry_points"] = ["EP1"]
        m["interfaces"] = [
            {"id": "I1", "name": "Untouched", "what": "No journey names it.", "side": "ours",
             "facing": "user", "kind": "screen" },
            {"id": "I2", "name": "Used", "what": "A journey comes here.", "side": "ours",
             "facing": "user", "kind": "screen", "ways_in": ["EP1"] },
        ]
    with _served_map(_doored(mutate)) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        got = page.evaluate("""() => ({
            order: [...document.querySelectorAll('.ifd-col-ours .ifd-box')]
                     .map(b => b.dataset.iface),
            quiet: [...document.querySelectorAll('.ifd-col-ours .ifd-box')]
                     .map(b => b.classList.contains('ifd-box-quiet')),
            pills: [...document.querySelectorAll('.ifd-col-ours .ifd-box')]
                     .map(b => { const e = b.querySelector('.ibox-count');
                                 return e ? e.textContent : null; })
        })""")
        # the used one leads, the untouched one is last and drawn quiet
        assert got["order"] == ["I2", "I1"], got
        assert got["quiet"] == [False, True], got
        # …and NONE draws no pill at all: a label for an absence is one more thing to read
        assert got["pills"] == ["1 use case", None], got
        assert not page.js_errors, page.js_errors


def test_a_surfaces_wire_reaches_its_card_and_lands_on_the_product() -> None:
    """Both ends of the line are asserted, because both used to be wrong in their own way.

    AT THE CARD: no gap. A line that stops short of the thing it points at is a line the reader has
    to join up themselves. 14px of clearance was tried and Nitsan reversed it twice. What made the
    clearance seem necessary was the BRACKET — the picked card's 2px indigo border closing a
    surface's TWO wires into one line bent twice — and a surface draws ONE wire now, so the bracket
    cannot form at all.

    AT THE PRODUCT: on the circle's edge, along a radius. Aimed anywhere else the lines would cross
    inside the shape, and a hub with lines crossing through it stops reading as one thing.

    AND NO HEADS AT EITHER END. They carried the crossings' two directions, and the page no longer
    reads those — a head derived instead from the walks would be a guess dressed as a fact."""
    def mutate(m: dict) -> None:
        # A WAY IN, so a use case reaches it: the box is drawn for what comes through a surface, and
        # a surface nothing reaches is given no box at all.
        m["entry_points"][0]["id"] = "EP1"
        for u in m["use_cases"]:
            if u["id"] == "UC1":
                u["entry_points"] = ["EP1"]
        m["interfaces"] = [
            {"id": "I1", "name": "Both ways", "what": "It answers as well as asks.",
             "side": "ours", "facing": "user", "kind": "screen", "ways_in": ["EP1"]
             },
        ]
    with _served_map(mutate) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        page.eval_on_selector('.ifd-box[data-iface="I1"]', "e => e.click()")
        page.wait_for_timeout(300)
        got = page.evaluate("""() => {
            const b = document.querySelector('.ifd-box[data-iface="I1"]');
            const right = b.offsetLeft + b.offsetWidth;
            const hub = document.getElementById('ifdhub');
            const cx = hub.offsetLeft + hub.offsetWidth / 2;
            const cy = hub.offsetTop + hub.offsetHeight / 2;
            const r = hub.offsetWidth / 2;
            const ps = [...document.querySelectorAll('#ifdstage path[data-iface="I1"]')];
            const n = ps[0].getAttribute('d').match(/-?[\\d.]+/g).map(Number);
            return { wires: ps.length,
                     startGap: Math.abs(n[0] - right),
                     endOffCircle: Math.abs(Math.hypot(n[n.length - 2] - cx,
                                                       n[n.length - 1] - cy) - r),
                     heads: [!!ps[0].getAttribute('marker-start'),
                             !!ps[0].getAttribute('marker-end')],
                     ring: getComputedStyle(b).boxShadow };
        }""")
        assert got["wires"] == 1, got
        assert got["heads"] == [False, False], got   # a plain line: membership, not traffic
        # It REACHES its card — no gap to join up by eye.
        assert got["startGap"] <= 1, got
        # …and it LANDS ON the product, on the circle itself rather than short of it or inside it.
        assert got["endOffCircle"] <= 1, got
        # …and the picked card really is wearing the shared picked edge — its border plus a painted
        # inset ring, which takes no room — so the single line above is leaving from inside the span
        # that used to close the bracket.
        assert "inset" in got["ring"] and "rgb(79, 70, 229)" in got["ring"], got
        assert not page.js_errors, page.js_errors

def _wire_ends_on_the_product(page: Any) -> dict:
    """How far the worst wire's far end is from the product's rim, in the layout on screen NOW.

    ONLY the wires. The same drawing holds the picture's own frame, and measuring that against a
    circle it was never aimed at reports a number in the hundreds that means nothing at all."""
    return dict(page.evaluate("""() => {
        const st = document.getElementById('ifdstage');
        const hub = document.getElementById('ifdhub');
        const cx = hub.offsetLeft + hub.offsetWidth / 2;
        const cy = hub.offsetTop + hub.offsetHeight / 2;
        const r = hub.offsetWidth / 2;
        let worst = 0, wires = 0;
        for (const p of st.querySelectorAll('svg.ifd-wires path[data-iface]')) {
          const n = p.getAttribute('d').match(/-?[0-9.]+/g).map(Number);
          const d = Math.abs(Math.hypot(n[n.length - 2] - cx, n[n.length - 1] - cy) - r);
          if (d > worst) worst = d;
          wires++;
        }
        return { wires, offCircle: +worst.toFixed(1), stage: st.offsetWidth };
    }"""))


def test_a_surfaces_wire_lands_on_the_product_in_a_NARROW_window() -> None:
    """The picture was laid out ONCE, against a stage that had not finished settling.

    `#srcrail` is a 30px button the page unhides AFTER the view has rendered, so that one pass
    measured a stage 30px wider than the one the reader ends up looking at, and every wire ended
    that far off the circle: 35px at a 900px window, 14px at 1024. From 1152 up the stage is at its
    width cap in both layouts, which is why the picture looked right on the machine it was built on
    and wrong on a laptop.

    A RELOAD, not a resize: the defect is in the first layout, and only a fresh document has one.
    And only a browser has one at all, which is why no source test caught this."""
    with _served_map(_two_sided_interfaces()) as url, _page(url + "#v=interfaces") as page:
        page.set_viewport_size({"width": 900, "height": 900})
        page.reload()
        page.wait_for_selector("#crumb h1", state="attached")
        _settle(page)
        got = _wire_ends_on_the_product(page)
        assert got["wires"] == 2, got
        assert got["offCircle"] <= 1, got
        assert not page.js_errors, page.js_errors


def test_a_surfaces_wire_follows_the_product_when_the_WINDOW_RESIZES() -> None:
    """Nothing recomputed on a resize at all — the wires stayed where the opening width put them.
    Measured on MCP Hero, opened at 1400 and dragged narrower: 25px off at 1100, 63px at 1024, 135px
    at 900, which is a spoke pointing into open space beside a circle it never touches.

    AND THE PICK SURVIVES IT. The re-layout builds the wires and the boxes fresh, so a surface the
    reader had picked has to be lit again on the new ones. Otherwise widening the window puts their
    pick out, and the picture answers for nothing while a card still wears the picked edge."""
    with _served_map(_two_sided_interfaces()) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        page.eval_on_selector('.ifd-box[data-iface="I1"]', "e => e.click()")
        page.wait_for_timeout(300)
        for width in (1900, 1152, 1024, 900):
            page.set_viewport_size({"width": width, "height": 900})
            _settle(page)
            got = _wire_ends_on_the_product(page)
            assert got["wires"] == 2, (width, got)
            assert got["offCircle"] <= 1, (width, got)
        lit = page.evaluate("""() => {
            const st = document.getElementById('ifdstage');
            const ids = (sel) => [...st.querySelectorAll(sel)].map((e) => e.dataset.iface).sort();
            return { hot: ids('svg.ifd-wires path.ifd-hot'),
                     cold: ids('svg.ifd-wires path.ifd-cold'),
                     labelled: ids('.ifd-elabel.ifd-lab-on') };
        }""")
        assert lit == {"hot": ["I1"], "cold": ["I2"], "labelled": ["I1"]}, lit
        assert not page.js_errors, page.js_errors


def test_a_surface_card_has_one_door_and_it_is_the_name() -> None:
    """The people and the providers are FACTS about a surface, not places to go.

    They were buttons — a chip opened that actor's page, a provider line opened that dependency in
    the tree — which put three kinds of target on one small card and made a fact read as somewhere to
    click. The same split every other card on this viewer makes: the name leaves, the body pins.

    The glossary links inside the SENTENCE are exempt and deliberately not counted: they are an
    app-wide treatment on every sentence the viewer draws, not a control this card invented."""
    with _served_map(_both_shores_carry_people_and_a_pipe()) as url, \
            _page(url + "#v=interfaces") as page:
        _settle(page)
        got = page.evaluate("""() => [...document.querySelectorAll('.ifd-box')].map(b => ({
            name: b.querySelector('.ibox-name').textContent,
            doors: [...b.querySelectorAll('button, a, [role=button]')]
                     .filter(e => !e.classList.contains('gloss-link'))
                     .map(e => e.className),
            chips: b.querySelectorAll('.item-pill').length,
            provs: b.querySelectorAll('.ifd-prov').length
        }))""")
        assert got, got
        for card in got:
            assert card["doors"] == ["ibox-name"], card
        # …and the facts are still drawn, so this is not passing by them having disappeared.
        assert sum(c["chips"] for c in got) > 0, got
        assert sum(c["provs"] for c in got) > 0, got
        assert not page.js_errors, page.js_errors


def test_a_story_label_stands_at_the_far_box_and_covers_nothing() -> None:
    """A stake label used to ride its wire's MIDPOINT on one nowrap line. Two faults followed: the
    pill was wider than the gutter it crossed, so it lay over the actor box and the feature box at
    both ends of its own wire; and nothing but its colour said which of a card's several arrows it
    belonged to.

    It stands at the FAR end of its wire now — beside the box that is not the one you picked, which
    is the box that identifies it — always above that end, and capped to the gutter so it wraps
    instead of reaching any card. Every card on the page is picked in turn, so all three cases are
    measured: an actor's labels land on the features, an area's on the features, and a feature's go
    out both ways at once."""
    with _served() as url, _page(url + "#v=features") as page:   # the board, not the landing
        _settle(page)
        got = page.evaluate("""() => {
            const st = document.getElementById('storystage');
            const sb = st.getBoundingClientRect();
            const R = (e) => { const r = e.getBoundingClientRect();
                return { l: r.left - sb.left, t: r.top - sb.top,
                         r: r.right - sb.left, b: r.bottom - sb.top }; };
            const ov = (a, b) => !(a.r <= b.l || b.r <= a.l || a.b <= b.t || b.b <= a.t);
            let shown = 0, onCard = 0, onLabel = 0, notAbove = 0, offFarBox = 0;
            let wrapped = 0, atHead = 0, atTail = 0, offTop = 0;
            for (const c of st.querySelectorAll('.story-card')) {
                const key = c.dataset.sfeat ? 'sfeat' : c.dataset.sactor ? 'sactor' : 'sarea';
                c.click();
                const cards = [...st.querySelectorAll('.story-card')].map(R);
                const labs = [...st.querySelectorAll('.story-elabel.story-lab-on')];
                for (const l of labs) {
                    const r = R(l);
                    const head = l.dataset.labfrom === key;   // lit by the tail card -> far end is the head
                    const ax = parseFloat(head ? l.dataset.labtx : l.dataset.labsx);
                    const ay = parseFloat(head ? l.dataset.labty : l.dataset.labsy);
                    shown++;
                    if (head) atHead++; else atTail++;
                    if (r.b - r.t > 26) wrapped++;               // more than one line of text
                    if (r.b > ay + 0.5) notAbove++;              // never below its own end
                    // …and pinned by the edge facing that end, within a pixel.
                    if (Math.abs(head ? r.r - (ax - 8) : r.l - (ax + 8)) > 1) offFarBox++;
                    if (r.t < 0) offTop++;                       // never pushed off the stage
                    if (cards.some((k) => ov(r, k))) onCard++;
                    if (labs.some((m) => m !== l && ov(r, R(m)))) onLabel++;
                }
            }
            return { shown, onCard, onLabel, notAbove, offFarBox, wrapped, atHead, atTail, offTop };
        }""")
        assert got["shown"] > 20, got            # the fixture really does light labels
        assert got["atHead"] > 0 and got["atTail"] > 0, got   # …reaching both ways
        assert got["wrapped"] > 0, got           # …and the cap really does wrap a long one
        assert got["onCard"] == 0, got           # nothing covers a box
        assert got["onLabel"] == 0, got          # nothing covers another label
        assert got["notAbove"] == 0, got         # each sits above the end it hangs off
        assert got["offFarBox"] == 0, got        # …pinned to the box that identifies it
        assert got["offTop"] == 0, got           # …and inside the stage
        assert not page.js_errors, page.js_errors


def test_a_crossings_sentence_never_covers_the_card_it_belongs_to() -> None:
    """The label used to straddle its wire's midpoint. At 320px against a 155px gutter that put 75px
    of it over the very box the reader had just picked, hiding the name and the people.

    It now starts where its line starts and grows AWAY from the card, overhanging the middle and the
    far column instead — both dimmed while it shows, and neither is what the reader is looking at.
    ONE box per interface, so what is asserted is that the single box clears the card on both
    shores."""
    def mutate(m: dict) -> None:
        # ONE ON EACH SHORE, each with a way in so a use case reaches it — an interface nothing
        # reaches gets no box, and this test is about where a box goes.
        m["entry_points"][0]["id"] = "EP1"
        m["entry_points"][1]["id"] = "EP2"
        m["use_cases"][0]["entry_points"] = ["EP1"]
        m["use_cases"][1]["entry_points"] = ["EP2"]
        m["interfaces"] = [
            {"id": "I1", "name": "Ours", "what": "On our shore.", "side": "ours",
             "facing": "user", "kind": "screen", "ways_in": ["EP1"] },
            {"id": "I2", "name": "Theirs", "what": "On theirs.", "side": "theirs",
             "facing": "user", "kind": "hosted-screen", "ways_in": ["EP2"] },
        ]
    with _served_map(_doored(mutate)) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        for iid in ("I1", "I2"):     # one on each shore: they grow in opposite directions
            page.eval_on_selector(f'.ifd-box[data-iface="{iid}"]', "e => e.click()")
            page.wait_for_timeout(250)
            got = page.evaluate("""(iid) => {
                const b = document.querySelector(`.ifd-box[data-iface="${iid}"]`);
                const br = b.getBoundingClientRect();
                const ls = [...document.querySelectorAll('.ifd-elabel.ifd-lab-on')];
                return { shown: ls.length,
                         over: ls.filter(l => { const r = l.getBoundingClientRect();
                                   return r.left < br.right && r.right > br.left; }).length };
            }""", iid)
            assert got["shown"] == 1, (iid, got)
            assert got["over"] == 0, (iid, got)
        assert not page.js_errors, page.js_errors


def _crossing_naming_a_record() -> Any:
    """One surface whose two crossings name real records of the fixture map."""
    def mutate(m: dict) -> None:
        m["interfaces"] = [
            {"id": "I1", "name": "Both ways", "what": "It answers as well as asks.",
             "side": "ours", "facing": "user", "kind": "screen"
             },
        ]
    return mutate


def test_a_use_case_on_the_box_is_a_door_and_the_rest_are_counted() -> None:
    """The box lists what brings each person here, and every one of them is a screen of its own — the
    same treatment the records it used to list already had.

    CAPPED AT THREE, with a tail that SAYS how many are held back. MCP Hero's dashboard brings its
    admin through 27 use cases; a box that listed them all would be taller than the picture, and one
    that showed three and stopped would be lying by omission. The tail is the shared `+n more`, the
    one look every capped list in this viewer uses."""
    def mutate(m: dict) -> None:
        # Five use cases through one surface, all driven by the same person: more than the cap.
        m["entry_points"][0]["id"] = "EP1"
        for u in m["use_cases"]:
            if u["id"] in ("UC2", "UC3", "UC4", "UC5", "UC6"):
                u["entry_points"] = ["EP1"]
        m["interfaces"] = [
            {"id": "I1", "name": "Busy", "what": "One person, many journeys.", "side": "ours",
             "facing": "user", "kind": "screen", "ways_in": ["EP1"] },
        ]
    with _served_map(_doored(mutate)) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        page.eval_on_selector('.ifd-box[data-iface="I1"]', "e => e.click()")
        page.wait_for_timeout(300)
        got = page.evaluate("""() => {
            const l = document.querySelector('.ifd-elabel.ifd-lab-on');
            return { head: l.querySelector('.ifd-elabel-dir').textContent,
                     doors: [...l.querySelectorAll('.ifd-elabel-uc')].map(e => e.textContent),
                     tail: (l.querySelector('.ifd-what-more') || {}).textContent || '' };
        }""")
        assert "5 use cases" in got["head"], got        # the head counts them all…
        assert len(got["doors"]) == 3, got              # …the list shows three…
        assert got["tail"].strip().startswith("+2"), got   # …and the tail names the rest
        # …and a door really opens its use case
        page.click(".ifd-elabel-uc")
        page.wait_for_timeout(300)
        assert "uc=" in page.evaluate("() => location.hash"), page.evaluate("() => location.hash")
        assert not page.js_errors, page.js_errors


def test_the_pinned_surface_is_part_of_where_you_are() -> None:
    """A pinned card is not a passing highlight, it is WHERE YOU ARE: the address restates it, so a
    link carries it, and leaving the view and coming back finds the picture as you left it.

    It rides the same `sel` field the Features page's pin uses. The two pages share the field and not
    their ids, so each takes only the keys it draws — asserted here by the key in the address."""
    with _served_map(_two_sided_interfaces()) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        page.eval_on_selector('.ifd-box[data-iface="I2"]', "e => e.click()")
        page.wait_for_timeout(300)
        assert "sel=siface%3AI2" in page.evaluate("() => location.hash"), page.evaluate(
            "() => location.hash")
        # leave the view entirely, then come back
        page.evaluate("() => document.querySelector('button[data-view=\\\"glossary\\\"]').click()")
        _settle(page)
        page.evaluate("() => document.querySelector('button[data-view=\\\"interfaces\\\"]').click()")
        _settle(page)
        back = page.evaluate("""() => ({
            picked: [...document.querySelectorAll('.ifd-box.ifd-picked')].map(e => e.dataset.iface),
            labels: document.querySelectorAll('.ifd-elabel.ifd-lab-on').length })""")
        assert back["picked"] == ["I2"], back
        assert back["labels"] >= 1, back        # …and its sentences came back lit with it
        assert not page.js_errors, page.js_errors


def test_a_click_that_is_not_on_a_box_drops_the_pin() -> None:
    """One rule, and it needs saying because there was no rule at all before: the picture had no
    outside-click handler, and what looked like one working was the gutter happening to clear the
    class. The product's own shape, a column heading and the page below the diagram each left a
    surface pinned for good.

    The listener also has to be REMOVED between renders. It lives on `document`, which outlives the
    diagram, so every re-render would otherwise leave another behind — each holding a dead render's
    closure and each still writing to the address bar."""
    with _served_map(_two_sided_interfaces()) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        # every one of these is outside a box, and every one must mean the same thing
        for where in ("#ifdhub", ".ifd-col-ours .ifd-colhead", ".ifd-stage", ".usecases-wrap"):
            page.eval_on_selector('.ifd-box[data-iface="I1"]', "e => e.click()")
            page.wait_for_timeout(200)
            assert page.evaluate(
                "() => document.querySelectorAll('.ifd-box.ifd-picked').length") == 1, where
            page.eval_on_selector(where, "e => e.click()")
            page.wait_for_timeout(200)
            got = page.evaluate("""() => ({
                picked: document.querySelectorAll('.ifd-box.ifd-picked').length,
                hash: location.hash })""")
            assert got["picked"] == 0, (where, got)
            assert "sel=" not in got["hash"], (where, got)
        assert not page.js_errors, page.js_errors


def test_the_leader_meets_its_arrow_at_a_right_angle_clear_of_the_head() -> None:
    """The leader is the placement made visible, so it is asserted as geometry, not as a decoration.

    PERPENDICULAR, and A CONSTANT LENGTH. It used to be drawn straight down and always 14px, and
    these arrows run from nearly flat to very steep — slopes 0.05 to 2.34 on MCP Hero — so the gap a
    reader actually saw ranged 5.5px to 14px across sixteen surfaces. Boxes on steep arrows looked
    glued on and boxes on flat ones looked loose.

    AND CLEAR OF THE HEAD. The anchor used to be wherever box and arrow came closest, which on four
    of those sixteen was within 2px of the arrow's end at the card — landing on the very arrowhead
    the box is moved aside to keep visible.

    All three are read back from the laid-out page: where the leader starts, how long it is, which
    way it is turned. A dashed line that merely EXISTS would pass a test that only looked for one."""
    # AS LONG AS THE REAL MAPS GET, not longer. MCP Hero's dashboard is the tallest box on any of
    # the three live maps at 378px — two sentences a direction, each wrapping three or four lines.
    # A fixture beyond that is a picture no build produces, and the box would be shrunk to fit,
    # which tests the ceiling rather than the rule.
    with _served_map(_sixteen_surfaces) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        got = page.evaluate("""() => {
            return [...document.querySelectorAll('.ifd-elabel')].map(l => {
                const [x0, y0, x1, y1] = String(l.dataset.wire).split(' ').map(Number);
                const bl = parseFloat(l.style.left), bt = parseFloat(l.style.top);
                // laid out to read its width: a `display: none` element measures 0, and the corner
                // the leader leaves from is either 0 or the box's full width across.
                l.style.visibility = 'hidden'; l.style.display = 'block';
                const w = l.offsetWidth;
                l.style.display = ''; l.style.visibility = '';
                const cs = getComputedStyle(l);
                const num = (k) => parseFloat(cs.getPropertyValue(k));
                const len = num('--lead-len');
                // where it starts (the box's own corner) and where it ends, from the same three
                // numbers the stylesheet draws it with: a line straight down, then rotated.
                const qx = bl + num('--lead-x'), qy = bt + num('--lead-y');
                const rot = num('--lead-rot') * Math.PI / 180;
                const ex = qx - len * Math.sin(rot), ey = qy + len * Math.cos(rot);
                const dx = x1 - x0, dy = y1 - y0, seg = Math.hypot(dx, dy);
                const t = ((ex - x0) * dx + (ey - y0) * dy) / (seg * seg);
                return {
                    clamped: !!l.dataset.clamped, len,
                    // how far the far end misses the arrow by
                    offArrow: Math.hypot(ex - (x0 + dx * t), ey - (y0 + dy * t)),
                    // 0 when the leader and the arrow meet at a right angle
                    cosine: Math.abs((ex - qx) * dx + (ey - qy) * dy) / (len * seg),
                    along: t * seg,
                    // …and the corner it leaves from is a corner OF THE BOX
                    onBox: Math.abs(num('--lead-x')) < 1 || Math.abs(num('--lead-x') - w) < 1
                };
            });
        }""")
        assert got, got
        drawn = [g for g in got if not g["clamped"]]
        assert drawn, got                      # or this asserts nothing at all
        for g in drawn:
            assert abs(g["len"] - 14) < 0.5, g          # the constant, not whatever fitted
            assert g["cosine"] < 0.02, g                # a right angle
            assert g["offArrow"] < 0.5, g               # …ending ON the arrow
            assert g["along"] >= 27.5, g                # …and never on its head
            assert g["onBox"], g
        for g in got:
            # A CLAMPED BOX HAS NO LEADER, and must not have one: the picture was too short to hold
            # it off its arrow, so it is ON the line and there is no gap to draw across.
            if g["clamped"]:
                assert g["len"] == 0, g
        # …AND ON THIS FIXTURE NOTHING MAY CLAMP AT ALL. Everything above only checked the boxes that
        # WERE placed, so it passed just as happily when one box was clamped as when all sixteen were
        # — and one of them was, on the live map: MCP Hero's dashboard, the interface a reader opens
        # first, sat on its own arrow with no leader through every green run of this file.
        assert not [g for g in got if g["clamped"]], got
        assert not page.js_errors, page.js_errors


def _ifd_boxes(page: Any) -> list[dict]:
    """Where every surface's floating box ended up, and which step of the placement put it there."""
    return list(page.evaluate("""() => {
        const stage = document.querySelector('.ifd-stage');
        const co = stage.querySelector('.ifd-col-ours'), ct = stage.querySelector('.ifd-col-theirs');
        const gutterFrom = co.offsetLeft + co.offsetWidth, gutterTo = ct.offsetLeft;
        return [...document.querySelectorAll('.ifd-elabel')].map(l => {
            const body = l.querySelector('.ifd-elabel-body');
            l.style.visibility = 'hidden'; l.style.display = 'block';
            const h = l.offsetHeight, w = l.offsetWidth;
            const scrolls = body ? body.scrollHeight > body.clientHeight + 1 : false;
            l.style.display = ''; l.style.visibility = '';
            const bl = parseFloat(l.style.left), ours = l.dataset.side === 'ours';
            return {
                id: l.dataset.iface, ours, h, w, left: bl, anchor: parseFloat(l.dataset.anchor),
                len: parseFloat(getComputedStyle(l).getPropertyValue('--lead-len')),
                clamped: !!l.dataset.clamped, capped: l.dataset.capped ? +l.dataset.capped : 0,
                scrolls,
                // how far it reaches into the column on the OTHER shore, and 0 when it stays home
                over: ours ? Math.max(0, (bl + w) - gutterTo) : Math.max(0, gutterFrom - bl),
            };
        });
    }"""))


def _stylesheet_with_giant_boxes(url: str) -> str:
    """The viewer's real stylesheet, with every row of a surface's floating box made 3000px tall — so
    the boxes are several times the height of the picture that has to hold them, which no real map
    produces and no window size can undo."""
    parts = urlsplit(url)
    css = urlopen(f"{parts.scheme}://{parts.netloc}/static/viewer.css").read().decode()
    return css + "\n.ifd-elabel-row{min-height:3000px;}"


def _sixteen_surfaces(m: dict) -> None:
    """Sixteen surfaces on the served map, each reached by one use case.

    SIXTEEN is the size of the largest live map. The stage's height comes from the number of cards,
    and the room a box has to get off its line comes from the stage, so eight surfaces make a 500px
    picture a 300px box cannot be placed in. A WAY IN EACH, because a surface nothing reaches gets
    no box at all, and every test using this shape is about where the boxes go."""
    for n, ep in enumerate(m["entry_points"][:16], start=1):
        ep["id"] = f"EP{n}"
    for n, u in enumerate(m["use_cases"][:16], start=1):
        u["entry_points"] = [f"EP{n}"]
    m["interfaces"] = [
        {"id": f"I{n}", "name": f"Surface {n}", "what": "One of several.",
         "side": "ours" if n % 2 else "theirs", "facing": "user", "kind": "screen",
         "ways_in": [f"EP{n}"]}
        for n in range(1, 17)
    ]
    _door_named_ways_in(m)


def test_a_box_with_no_room_beside_its_arrow_takes_the_far_column_before_it_gives_up() -> None:
    """STEP 2 OF THE PLACEMENT, and the reason it exists.

    MCP Hero's dashboard box is 353px tall — the tallest of the 27 across the two live maps — and
    300px of box in a 380px gutter leaves 76px of sideways play. 250 spots were tried beside its
    arrow and every one was rejected: 142 out of the sideways bound, 47 outside the picture, 61
    landing on the arrow. So the box fell to the last resort, sat ON its own arrow, and lost its
    leader — on the one interface a reader opens first.

    A TALLER PICTURE WAS NEVER THE ANSWER, which is what says the sideways bound is the binding one:
    the same scan against a 2000px stage still finds nothing, and the stage is a fixed 1060px at
    every window from 1280 to 2200. So the room has to come from the far column.

    WHAT STEP 2 MAY NOT DO is cover the card the reader just picked. The box grows away from its own
    card, and only the FAR bound is given up — asserted here, because a bound dropped one line too
    far would put the box straight back over the thing it is describing."""
    with _served_map(_sixteen_surfaces) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        got = _ifd_boxes(page)
        assert got
        for g in got:
            assert not g["clamped"], g              # every box placed…
            assert abs(g["len"] - 14) < 0.5, g      # …and every box still joined to its own arrow
            # …on its own side of its own card, whatever room it had to borrow on the other shore
            if g["ours"]:
                assert g["left"] >= g["anchor"], g
            else:
                assert g["left"] + g["w"] <= g["anchor"], g
        assert not page.js_errors, page.js_errors


def test_a_box_too_tall_for_the_picture_gets_a_ceiling_and_scrolls_rather_than_losing_its_leader()\
        -> None:
    """STEP 3, forced. No live map has ever reached it: MCP Hero's dashboard, the worst real case,
    is placed by step 2 with 70 spots to choose from. So the fixture makes every row 3000px tall,
    which is several times the whole picture and which no build produces.

    The point is that the LAST RESORT stays unreachable. A box that cannot be placed at its natural
    height is shrunk until it can be, and the rows it can no longer show scroll under the ceiling.
    That is a worse box than a whole one, and a better picture than a box sitting on its own arrow
    with nothing joining the two.

    THE CEILING IS ON THE ROWS, NOT ON THE BOX, and that is not tidiness: the leader is the box's own
    `::after` and points OUT of it, so a box that scrolls clips its own leader off at the edge. The
    assertion that the leader is still 14px is what would catch that."""
    with _served_map(_sixteen_surfaces) as url:
        with _page(url + "#v=interfaces", stylesheet=_stylesheet_with_giant_boxes(url)) as page:
            _settle(page)
            got = _ifd_boxes(page)
            assert got
            shrunk = [g for g in got if g["capped"]]
            assert shrunk, got            # or the fixture stopped forcing the step it is here for
            for g in shrunk:
                assert not g["clamped"], g
                assert abs(g["h"] - g["capped"]) < 1, g   # exactly the ceiling it was given
                assert g["scrolls"], g                    # …with the rest reachable, not lost
                assert abs(g["len"] - 14) < 0.5, g        # …and the leader not clipped away
            assert not page.js_errors, page.js_errors


def _stage_state(page: Any) -> dict:
    """What the drawing and its pan/zoom machinery think they are, right now.

    NaN and Infinity do not survive the trip out of the page intact, so every number that could be
    one is reduced to a yes/no in the page itself."""
    return dict(page.evaluate("""() => {
        const stage = document.getElementById('stage');
        const d = document.getElementById('diagram');
        const svg = d.querySelector('svg');
        // svgPanZoom() on an element it already owns hands back that same instance. It BUILDS one on
        // an svg it does not own, so only ever call this where the first svg is the map itself — a
        // card view's first svg is a decoration, and this would quietly pan-zoom that instead.
        const pz = (svg && window.svgPanZoom) ? window.svgPanZoom(svg) : null;
        const sizes = pz ? pz.getSizes() : null;
        const zoom = pz ? pz.getZoom() : null;
        return {
            drawingHeight: Math.round(d.getBoundingClientRect().height),
            // the pan/zoom base scale: 0 is the poisoned state, and nothing recovers from it
            baseScaleIsReal: !!(sizes && sizes.realZoom > 0 && Number.isFinite(sizes.realZoom)),
            fittedHeight: sizes ? Math.round(sizes.height) : 0,
            zoomIsReal: Number.isFinite(zoom),
            reading: (document.getElementById('zoomlevel').textContent || '').trim(),
            paneScrolls: stage.scrollHeight > stage.clientHeight + 1
        };
    }"""))


def test_a_pane_too_short_for_its_header_still_draws_the_map() -> None:
    """A window short enough that the tabs, the trail and the feature's own heading fill the whole
    graph pane used to leave the drawing exactly 0 tall — and 0 is worse than small. The pan/zoom
    machinery DIVIDES BY that height with no floor of its own, so the map went blank, the zoom control
    over the drawing read "NaN%", and it never came back: widening the window again fed the same NaN into
    every later move instead of re-fitting. Measured on this map at 529x265, the header alone was
    218px inside a 161px pane. The drawing now keeps a floor and the pane scrolls to reach it.

    This one is about the FLOOR: at the size it uses, the old code left the drawing 1px tall rather
    than 0, so it was starved but not yet poisoned. The two tests below cover the poisoning itself."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        page.set_viewport_size({"width": 560, "height": 240})
        _settle(page)
        short = _stage_state(page)
        assert short["drawingHeight"] >= 160, short      # the floor, not the 0 the header left
        assert short["baseScaleIsReal"], short
        assert short["zoomIsReal"], short
        assert re.fullmatch(r"\d+%", short["reading"]), short   # never "NaN%"
        assert short["paneScrolls"], short               # …because the header no longer eats the map

        # The move that used to do the poisoning: a resize while the drawing has no room. Every
        # re-fit path in the viewer goes through this one, so a window resize covers them all.
        page.set_viewport_size({"width": 560, "height": 210})
        _settle(page)
        assert _stage_state(page)["zoomIsReal"], _stage_state(page)

        # …and the map comes BACK when the window does. This is the half that stayed broken before:
        # the fit is re-measured against the new pane instead of dividing by a stale NaN.
        page.set_viewport_size({"width": 1200, "height": 820})
        _settle(page)
        wide = _stage_state(page)
        assert wide["baseScaleIsReal"], wide
        assert abs(wide["fittedHeight"] - wide["drawingHeight"]) <= 2, wide
        assert not wide["paneScrolls"], wide
        assert not page.js_errors, page.js_errors


def test_the_graph_pane_scrolls_only_when_its_header_cannot_fit() -> None:
    """The floor under the drawing is paid for by letting the graph pane scroll. That must cost
    nothing at a size anybody actually uses: at a normal window the drawing is far taller than its
    floor, so the pane has nothing below its own bottom edge and never offers a scrollbar. It had 29
    unreachable pixels down there before, from the selection card — invisible only because the pane
    clipped instead of scrolling, and a scrollbar on every normal window the moment it stopped."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        for width, height in ((1400, 900), (1100, 760), (960, 620)):
            page.set_viewport_size({"width": width, "height": height})
            _settle(page)
            seen = _stage_state(page)
            assert not seen["paneScrolls"], (width, height, seen)
            assert seen["baseScaleIsReal"], (width, height, seen)
        assert not page.js_errors, page.js_errors


def test_a_drawing_squeezed_to_nothing_does_not_poison_the_map_for_good() -> None:
    """The floor is one guard, and this is the other — the one that still holds if the floor ever
    moves. Take the floor away by hand so the drawing really does measure nothing, then resize the
    window on top of it. The pan/zoom machinery has to SKIP that move: measuring a box with no height
    is what set its base scale to 0, and from 0 the zoom is 0/0 and every later fit divides by that
    NaN instead of recovering. Give the drawing its room back and the map fits again."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        page.set_viewport_size({"width": 900, "height": 700})
        _settle(page)
        assert _stage_state(page)["baseScaleIsReal"]

        page.evaluate("() => { document.getElementById('diagwrap').style.minHeight = '0px'; }")
        page.set_viewport_size({"width": 560, "height": 210})
        _settle(page)
        squeezed = _stage_state(page)
        assert squeezed["drawingHeight"] == 0, squeezed        # the box really is gone…
        assert squeezed["zoomIsReal"], squeezed                # …and the map is still not poisoned
        assert re.fullmatch(r"\d+%", squeezed["reading"]), squeezed

        page.evaluate("() => { document.getElementById('diagwrap').style.minHeight = ''; }")
        page.set_viewport_size({"width": 1200, "height": 820})
        _settle(page)
        back = _stage_state(page)
        assert back["baseScaleIsReal"], back
        assert abs(back["fittedHeight"] - back["drawingHeight"]) <= 2, back
        assert not page.js_errors, page.js_errors


def _stylesheet_with_no_room(url: str) -> str:
    """The viewer's real stylesheet, with the floor under the drawing taken out and a header too tall
    for any window — so the drawing measures nothing from the first layout, before anything else has
    had a chance to render. Removing the floor alone is not enough to test this: the drawing still has
    room at the moment the map is built, and only loses it once the feature's heading fills in."""
    parts = urlsplit(url)
    css = urlopen(f"{parts.scheme}://{parts.netloc}/static/viewer.css").read().decode()
    out = css.replace("min-width: 0; min-height: 160px; display: flex;",
                      "min-width: 0; min-height: 0; display: flex;")
    assert out != css, "the floor rule moved — this test no longer takes it out"
    return out + "\n#stagehead{min-height:2000px;}"


def test_a_map_built_with_no_room_at_all_still_comes_back() -> None:
    """The worst version of the same fault, and the one the floor alone does not cover: the map is
    BUILT while the drawing has no room, not merely squeezed afterwards. The pan/zoom machinery
    measures that box once, at birth, and divides by it — so a 0 there used to be permanent. Verified
    against the old code through this exact test: the map stayed blank at "NaN%" and threw
    "the matrix is not invertible", and making the window large again did not bring it back, because
    every later fit divided by the NaN the first measurement produced."""
    with _served() as url:
        with _page(url + "#v=usecase&uc=UC1", stylesheet=_stylesheet_with_no_room(url)) as page:
            page.wait_for_timeout(1200)
            blind = _stage_state(page)
            assert blind["drawingHeight"] == 0, blind          # built with nothing at all…
            assert blind["zoomIsReal"], blind                  # …and still not poisoned
            assert re.fullmatch(r"\d+%", blind["reading"]), blind

            # room back: the header stops being impossible, and the map must FIT, not stay broken
            page.evaluate("""() => {
                for (const sheet of document.styleSheets) {
                    try {
                        for (let i = sheet.cssRules.length - 1; i >= 0; i--) {
                            if (String(sheet.cssRules[i].cssText).includes('min-height: 2000px')) {
                                sheet.deleteRule(i);
                            }
                        }
                    } catch (e) { /* a cross-origin sheet has no readable rules */ }
                }
            }""")
            page.set_viewport_size({"width": 1200, "height": 820})
            page.wait_for_timeout(1200)
            back = _stage_state(page)
            assert back["baseScaleIsReal"], back
            assert abs(back["fittedHeight"] - back["drawingHeight"]) <= 2, back
            assert not page.js_errors, page.js_errors


def test_a_map_poisoned_behind_the_viewer_s_back_still_never_throws() -> None:
    """The last line of defence, and the only test that reaches it. The two guards above stop the map
    from ever being measured against a box with no room — so the code that copes with a map that WAS
    measured that way is never reached by any normal route, and a test that only drives the viewer
    cannot tell whether it still works. So reach past the viewer and poison the map directly, the way
    the drawing library itself used to: re-measure and re-fit it against a box with no height. From
    there the map's scale is 0, and dividing by it is what put an Infinity into a drawing coordinate
    and left a shape whose position cannot be worked back — the two errors originally reported. The
    viewer must survive it silently: nothing thrown, and the zoom still a real number."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        page.set_viewport_size({"width": 1100, "height": 760})
        _settle(page)
        assert _stage_state(page)["baseScaleIsReal"]

        poisoned = page.evaluate("""() => {
            document.getElementById('diagwrap').style.minHeight = '0px';
            const svg = document.getElementById('diagram').querySelector('svg');
            const pz = window.svgPanZoom(svg);
            document.getElementById('stagehead').style.minHeight = '4000px';   // the drawing is now 0 tall
            // exactly what the viewer's own re-fit does — but with its guard bypassed
            pz.resize(); pz.fit(); pz.center();
            return { drawingHeight: Math.round(document.getElementById('diagram')
                                                .getBoundingClientRect().height),
                     baseScale: pz.getSizes().realZoom };
        }""")
        assert poisoned["drawingHeight"] == 0, poisoned
        assert poisoned["baseScale"] == 0, poisoned    # the map really is poisoned now

        # …and now use it. Every one of these went through the coordinate maths that used to throw.
        page.mouse.move(400, 300)
        page.mouse.move(500, 360)
        page.wait_for_timeout(200)
        page.evaluate("() => window.dispatchEvent(new Event('resize'))")
        page.set_viewport_size({"width": 900, "height": 700})
        _settle(page)
        # The map's own scale stays 0 — the drawing library cannot be talked out of that, and this
        # test deliberately never gives the room back (the two tests above cover recovery). What is
        # being asserted is the ONLY thing the viewer still owes here: it does not throw.
        assert not page.js_errors, page.js_errors


def test_a_record_inside_another_one_lists_the_use_cases_that_reach_its_holder() -> None:
    """The panel and the check must not disagree about one record.

    `validate` counts an embedded record as storied when its container is reached — it lives in the
    holder's row, so a story that writes the holder writes the piece. The panel walked no holder
    chain, so it said "No traced use case reaches it" on exactly those records: the screen calling a
    gap what the check calls fine, about the same record, on the same map.

    E2 is embedded in E1, and only E1 is ever named by a step."""
    def mutate(m: dict) -> None:
        m["entities"] = [e for e in m["entities"] if e["id"] in ("E1", "E2")]
        e1, e2 = (next(e for e in m["entities"] if e["id"] == i) for i in ("E1", "E2"))
        e1["store"] = {"dep": "D1", "container": "orders", "mode": "collection", "notes": ""}
        e2["store"] = {"dep": "D1", "container": "orders", "mode": "embedded", "notes": ""}
        e1["relations"] = [{"verb": "contains", "target": "E2", "src_card": "1", "dst_card": "*",
                            "display": e2["name"], "how": None, "keyed_by": []}]
        e2["relations"] = []
        for f in m["flows"]:
            if f["uc"] == "UC1":
                f["steps"] = [{"n": 1, "src": "C1", "dst": "E1", "phrase": "writes the record",
                               "note": "", "where": "backend/src/mcpolis/entrypoints/app.py:1",
                               "no_call_site": False, "subflow": None, "direction": "out"}]
        m["subflows"] = []
        for f in m["flows"]:
            if f["uc"] != "UC1":
                f["steps"] = [s for s in f["steps"] if not (s["src"].startswith("E")
                                                            or s["dst"].startswith("E"))]
    with _served_map(mutate) as url, _page(url + "#v=element&id=E2") as page:
        _settle(page)
        text = page.evaluate("() => document.body.innerText")
        assert "IN USE CASES" in text.upper(), text[:400]
        assert "No traced use case reaches it" not in text, \
            "E2 is inside E1, and E1 is storied — the holder's stories are its stories"
        assert not page.js_errors, page.js_errors


def _with_shared_walk(m: Any) -> None:
    """UC1 runs a shared sub-use case that keeps a record — the shape the committed fixture has none of."""
    m["subflows"] = [{
        "id": "SF1", "name": "Keep the organization",
        "steps": [{"n": 1, "src": "C101", "dst": "E1", "phrase": "writes the organization",
                   "note": "", "where": None, "no_call_site": False, "subflow": None},
                  {"n": 2, "src": "E1", "dst": "C101", "phrase": "hands back what it stored",
                   "note": "", "where": None, "no_call_site": False, "subflow": None}],
    }]
    steps = m["flows"][0]["steps"]
    steps[2:2] = [{"n": 99, "src": "C101", "dst": "C15", "phrase": "", "note": "", "where": None,
                   "no_call_site": False, "subflow": "SF1"}]


def test_a_use_case_walk_counts_its_own_steps_not_the_shared_walk_s() -> None:
    """A use case that runs a shared sub-use case used to count that walk's steps as its own — so the counter,
    the numbers on the map and the numbers in the Sequence view all described a walk longer than the one
    the map stores. The reference is one step now, and BOTH pictures say so: they are read against each
    other by number, so a disagreement would make the toggle between them land somewhere else."""
    with _served_map(_with_shared_walk) as url, _page(url + "#v=usecase&uc=UC1") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const chips = [...document.querySelectorAll('#diagram .item-pill')].map((c) =>
              ({ t: c.textContent, k: c.getAttribute('data-kind') || '' }));
            const box = [...document.querySelectorAll('#diagram g.node')]
              .find((n) => /SF1/.test(n.id));
            return { counter: document.querySelector('.flowplay-count, .stepcount, .flow-count')?.textContent
                       || document.getElementById('flowcount')?.textContent.match(/\\/\\s*(\\d+)/)?.[1],
                     chips, hasBox: !!box,
                     steps: [...document.querySelectorAll('#diagram .ibox-count')].map((e) => e.textContent),
                     arrows: [...document.querySelectorAll('#diagram .edgeLabel')]
                       .map((e) => e.textContent.trim()).filter(Boolean) };
        }""")
        assert seen["hasBox"], "the shared sub-use case is drawn as its own box"
        assert seen["chips"] == [{"t": "Organization", "k": "entity"}], seen["chips"]
        # HOW MANY STEPS THE SHARED SUB-USE CASE HOLDS IS NOT ON ITS BOX. The box is a door to the walk's own
        # screen, where its steps are numbered from 1 and belong to it; a count here answered a
        # question this picture is not about, and it was the one number on a box that carries chips.
        assert seen["steps"] == [], seen["steps"]
        # 12 = the fixture's own 11 steps plus the one reference. Expanded it would have read 13.
        assert seen["counter"] == "12", seen
        assert "3" in seen["arrows"] and "13" not in seen["arrows"], seen["arrows"]
        assert not page.js_errors, page.js_errors


def test_the_shared_walk_s_box_opens_the_walk_itself() -> None:
    """A shared sub-use case belongs to every use case that runs it, so it has a screen of its own rather than a
    home inside one of them. Drilling the box opens it: its steps numbered from 1, its own two pictures,
    and a trail that still leads back the way the reader came."""
    with _served_map(_with_shared_walk) as url, _page(url + "#v=usecase&uc=UC1") as page:
        _settle(page)
        page.evaluate("""() => {
            const box = [...document.querySelectorAll('#diagram g.node')].find((n) => /SF1/.test(n.id));
            box.dispatchEvent(new MouseEvent('click', { bubbles: true, altKey: true }));
        }""")
        page.wait_for_function("() => location.hash.includes('subflow')")
        _settle(page)
        seen = page.evaluate("""() => ({
            hash: location.hash,
            crumbs: [...document.querySelectorAll('#crumb *')].map((e) => e.textContent.trim())
                      .filter(Boolean),
            counter: document.getElementById('flowcount')?.textContent.match(/\\/\\s*(\\d+)/)?.[1],
        })""")
        assert "v=subflow" in seen["hash"] and "sf=SF1" in seen["hash"], seen["hash"]
        assert seen["counter"] == "2", seen           # its own two steps, numbered from 1
        assert seen["crumbs"][-1] == "Keep the organization", seen["crumbs"]
        assert "SF1" not in " ".join(seen["crumbs"]), "an id must never reach the screen"
        assert not page.js_errors, page.js_errors


def test_the_first_walk_opens_the_code_column_and_then_leaves_it_alone() -> None:
    """The rail that opens the source column is a thin strip on the far edge, and nothing on a use case
    map says the two are joined — while every box and every arrow on it points at a place in the code.
    So the first walk opens it. ONCE: a reader who then shuts it is not argued with on the next walk.

    A source test cannot see this. The rule is decided inside `syncCodePane`, and whether it fires at all
    depends on a fetch that is still in flight when the first render runs."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        _settle(page)
        assert page.evaluate("() => !document.body.classList.contains('code-hidden')"), \
            "the first walk shows the reader the column exists"
        page.evaluate("() => document.getElementById('cvclose').click()")
        page.wait_for_timeout(600)
        page.goto(url + "#v=usecase&uc=UC2")
        _settle(page)
        assert page.evaluate("() => document.body.classList.contains('code-hidden')"), \
            "closed once is closed for good — the rule fires on the FIRST walk only"
        assert not page.js_errors, page.js_errors


def test_a_selected_box_gets_a_card_with_a_line_to_it() -> None:
    """Every other screen puts what it is describing beside what you clicked, and the map does too: a
    card by the box, with a leader line to it."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        _settle(page)
        page.evaluate("""() => {
            const n = [...document.querySelectorAll('#diagram g.node')][1];
            n.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        }""")
        page.wait_for_timeout(800)
        assert page.evaluate("() => !document.getElementById('callout').hasAttribute('hidden')"), \
            "the card points at what it describes"
        assert not page.js_errors, page.js_errors


def test_a_box_s_name_opens_it_and_the_box_around_the_name_selects_it() -> None:
    """Features and Interfaces open a thing by clicking its title. On the map that gesture existed only
    one step removed — click the box, then click the card that appears — while the box itself offered a
    corner icon that does something else entirely (locate this element in a structural view).

    The name opens it now, in one click. The box AROUND the name still selects, so the two acts stay
    apart: the name goes somewhere, the box stays here and tells you about itself. Measured on mcpolis
    UC30, a component's name is a quarter to a half of its box, so both targets are real."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        _settle(page)
        spot = page.evaluate("""() => {
            const n = [...document.querySelectorAll('#diagram g.node')].find((x) => /C15/.test(x.id));
            // THE VISIBLE BOX, not the node group. The drawing engine pads a node well past its
            // label, and that padding is transparent and takes no clicks — a point inside the group
            // can be outside the box a reader can see. Every coordinate here is the box's own, and
            // the second one is its top-left corner: inside the box, inside its own padding, and
            // clear of the name however long the name runs.
            const b = n.querySelector('.ibox').getBoundingClientRect();
            const l = n.querySelector('.ibox-name').getBoundingClientRect();
            return { nameX: l.left + l.width / 2, nameY: l.top + l.height / 2,
                     edgeX: b.left + 3, edgeY: b.top + 3 };
        }""")
        page.mouse.click(spot["nameX"], spot["nameY"])
        page.wait_for_function("() => location.hash.includes('v=element')")
        assert "id=C15" in page.evaluate("() => location.hash")
        page.goto(url + "#v=usecase&uc=UC1")
        _settle(page)
        page.mouse.click(spot["edgeX"], spot["edgeY"])
        page.wait_for_timeout(700)
        seen = page.evaluate("""() => ({ hash: location.hash,
                                         card: !!document.querySelector('#panel .ecard[data-id]') })""")
        assert "v=usecase" in seen["hash"] and "node%3AC15" in seen["hash"], seen
        assert seen["card"], "the box around the name still selects and shows its card"
        assert not page.js_errors, page.js_errors


def test_hovering_a_box_shows_its_card_with_a_line_to_it() -> None:
    """A reader scanning a walk wants to know what each box is. Hover answers, with the same card a
    click pins and the same leader line pointing at the box — and leaving takes it away again.

    Only a browser can see this: the card's visibility is decided by one rule after the HTML is written,
    and writing the HTML alone left the card rendered but hidden."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        _settle(page)
        spot = page.evaluate("""() => {
            const n = [...document.querySelectorAll('#diagram g.node')].find((x) => /C15/.test(x.id));
            const c = n.querySelector('.ibox-name').getBoundingClientRect();
            return { x: c.left + c.width / 2, y: c.top + c.height / 2 };
        }""")
        page.mouse.move(spot["x"], spot["y"])
        page.wait_for_timeout(600)
        seen = page.evaluate("""() => ({
            card: !document.getElementById('panel').hidden,
            line: !document.getElementById('callout').hasAttribute('hidden'),
        })""")
        assert seen == {"card": True, "line": True}, seen
        page.mouse.move(4, 4)
        page.wait_for_timeout(600)
        assert page.evaluate("() => document.getElementById('panel').hidden"), \
            "leaving puts back what was there — nothing was selected, so nothing shows"
        assert not page.js_errors, page.js_errors


def test_opening_the_source_narrows_what_you_see_of_the_interfaces_picture_not_the_picture() -> None:
    """Every other diagram keeps its size when the source column opens, and the area around it shrinks.
    The Interfaces picture alone re-laid itself out: measured on mcpolis, 1060px wide became 890px the
    moment the column opened, squeezing the gutters the wires need room to turn in.

    Its wrapper already scrolled, so a floor under the stage was all it took. The floor is the five
    tracks at rest: two 320px cards, two 130px gutters, a 160px hub.

    ONLY while the column is open — the picture is also built to FIT a narrow window on its own, which
    `test_what_we_own_holds_the_product_and_our_surfaces_and_keeps_its_distance` asserts down to 1024.
    An unconditional floor made that window scroll for no reason. The column is what must not resize
    the drawing; a small screen still gets a drawing sized for it."""
    with _served_map(_two_sided_interfaces()) as url, _page(url + "#v=interfaces") as page:
        _settle(page)
        page.evaluate("""() => { if (document.body.classList.contains('code-hidden'))
                                   document.getElementById('srcrail').click(); }""")
        page.wait_for_timeout(1200)
        opened = page.evaluate("""() => {
            const s = document.getElementById('ifdstage'), w = s.closest('.ifd-wrap');
            // The board is the landing's section frame now; the wrap inside it draws no frame of its own.
            const wrap = w.parentElement, cs = getComputedStyle(w.closest('.item-sec-frame') || w);
            return { stage: Math.round(s.getBoundingClientRect().width),
                     scrolls: w.scrollWidth > w.clientWidth + 1,
                     board: { radius: cs.borderTopLeftRadius, border: cs.borderTopWidth },
                     shadeRight: wrap.classList.contains('hfade-on-r'),
                     shadeLeft: wrap.classList.contains('hfade-on-l') };
        }""")
        page.evaluate("() => { const c = document.getElementById('cvclose'); if (c) c.click(); }")
        page.wait_for_timeout(1200)
        closed = page.evaluate("""() => Math.round(
            document.getElementById('ifdstage').getBoundingClientRect().width)""")
        assert opened["stage"] == closed, f"the picture must not resize: {opened['stage']} vs {closed}"
        assert opened["scrolls"], "…and what you see of it scrolls instead"
        # …in the SAME board the Happy Path and a feature's timeline scroll in: a rule, a radius, and
        # the edge shade that says there is more that way. Only the right one, having not scrolled yet.
        assert opened["board"] == {"radius": "12px", "border": "1px"}, opened
        assert opened["shadeRight"] and not opened["shadeLeft"], opened
        assert not page.js_errors, page.js_errors


def _three_ways_to_reach_a_surface() -> Any:
    """The three shapes the interface rule has to tell apart, on one map.

    `I1` the flow OPENS at, with the person drawn there — the plain door.
    `I2` the flow reaches with NO person at either end (a component calls it), which is how a product
         reaches an analytics or an upstream service: the use case goes there, nobody stands there.
    `I3` is reached only inside a shared SUB-FLOW, which cannot name a person at all — `SF1` here is
         run by two use cases with different drivers, exactly as `Sign in with Google` is on the live
         map, so no door can be drawn in it and the caller's own driver is the strongest claim.

    The committed fixture has no interfaces and no sub-flows, so all of it is built here."""
    def mutate(m: dict) -> None:
        m["interfaces"] = [
            {"id": "I1", "name": "The dashboard", "what": "Screens a person signs in to.",
             "side": "ours", "facing": "user", "kind": "screen", "ways_in": ["EP1"]},
            {"id": "I2", "name": "Usage analytics", "what": "Where page views are sent.",
             "side": "theirs", "facing": "operator", "kind": "api"},
            {"id": "I3", "name": "Google sign-in", "what": "Where a person proves who they are.",
             "side": "theirs", "facing": "user", "kind": "hosted-screen"},
        ]
        m["entry_points"][0]["id"] = "EP1"
        for u in m["use_cases"]:
            if u["id"] in ("UC1", "UC2"):
                u["entry_points"] = ["EP1"]
        m["subflows"] = [{"id": "SF1", "name": "Sign in with Google", "steps": [
            {"n": 1, "src": "C15", "dst": "I3", "phrase": "redirect the browser to Google",
             "note": "", "where": None, "no_call_site": False, "subflow": None},
            {"n": 2, "src": "I3", "dst": "C15", "phrase": "return the visitor with a code",
             "note": "", "where": None, "no_call_site": False, "subflow": None}]}]
        step = lambda n, a, b, ph, sub=None: {
            "n": n, "src": a, "dst": b, "phrase": ph, "note": "", "where": None,
            "no_call_site": False, "subflow": sub}
        for f in m["flows"]:
            if f["uc"] == "UC1":            # driven by R1 "Org creator"
                nxt = len(f["steps"])
                f["steps"] += [step(nxt + 1, "R1", "I1", "open the dashboard"),
                               step(nxt + 2, "C15", "I2", "send the page-view event"),
                               step(nxt + 3, "C15", "C15", "sign in", "SF1")]
            if f["uc"] == "UC2":            # driven by R2 "Org admin" — the sub-flow's second caller
                nxt = len(f["steps"])
                f["steps"] += [step(nxt + 1, "C15", "C15", "sign in", "SF1")]
    return mutate


def _a_door_for_a_bystander(long_title: bool = False) -> Any:
    """One `ours` surface, reached two ways, because the actor board has to answer two questions.

    Its ways in put it behind the use cases the Org admin drives, so those stations get chips. Its
    DOOR — one flow step `R3 -> I1` inside UC1 — puts the Team member at it in a use case the Org
    creator drives, which is the only shape the third lane exists for and one the committed fixture
    holds nowhere.

    `long_title` stretches ONE happy-path label (its use case's name) past the rest, so the levelling pass has a station
    that must keep its own height rather than be padded to the majority."""
    admin_ucs = ("UC2", "UC3", "UC4", "UC5", "UC6", "UC13")

    def mutate(m: dict) -> None:
        m["interfaces"] = [{
            "id": "I1", "name": "Sign-in page", "what": "Where a person proves who they are.",
            "side": "ours", "facing": "user", "kind": "screen", "ways_in": ["EP1"]}]
        m["entry_points"][0]["id"] = "EP1"
        for u in m["use_cases"]:
            if u["id"] in admin_ucs or u["id"] == "UC1":
                u["entry_points"] = ["EP1"]
        # DRAWN, not merely addressed. A tag comes off the steps now, so every use case that should
        # show this surface needs a step at it — the bystander's door included.
        for f in m["flows"]:
            nxt = len(f["steps"]) + 1
            if f["uc"] == "UC1":
                f["steps"].append({
                    "n": nxt, "src": "R3", "dst": "I1",
                    "phrase": "reads the invite that brought them here",
                    "note": "", "where": None, "no_call_site": False, "subflow": None})
            elif f["uc"] in admin_ucs:
                f["steps"].append({
                    "n": nxt, "src": "R2", "dst": "I1", "phrase": "work on the dashboard",
                    "note": "", "where": None, "no_call_site": False, "subflow": None})
        if long_title:
            # A step is labelled with its use case's name, so the stretch goes on the use case.
            for u in m["use_cases"]:
                if u["id"] == "UC4":
                    u["name"] = ("Connect and start every upstream MCP server the organization "
                                 "has mounted so far")
    return mutate


def test_the_board_says_where_each_use_case_happens() -> None:
    """The board said what an actor does and never where they do it, while the Interfaces section
    under it held the same fact filed by surface — so "where does THIS use case happen" meant reading
    the whole section and inverting it in your head.

    CHIPS, and not the eight marks alone. The marks cover 13 kinds between them, so two surfaces on
    one step are routinely one drawing twice: on the mcpolis map, 12 of the 13 use cases that touch
    two surfaces or more would have drawn a repeat. The chip carries the NAME, and it is the same
    chip a shared sub-use case's box and a surface card already draw."""
    with _served_map(_a_door_for_a_bystander()) as url, \
            _page(url + "#v=actor&act=Org%20admin") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const st = [...document.querySelectorAll('.journey-track .flow-step')];
            return { stations: st.length,
                     withChips: st.filter((s) => s.querySelector('.journey-ifs')).length,
                     names: [...new Set([...document.querySelectorAll(
                         '.journey-ifs .item-pill')].map((c) => c.textContent.trim()))],
                     // The SHARED chip, mark and all — not a second drawing of the same idea.
                     marks: [...document.querySelectorAll(
                         '.journey-ifs .item-pill .ibox-gly')].length,
                     // …and inert. The station is the door; a chip inside it would be a second one.
                     clickable: document.querySelectorAll('.journey-ifs button, .journey-ifs a').length,
                     sentence: (document.querySelector('.item-sec-note')
                                || {}).textContent || '' };
        }""")
        assert seen["withChips"] >= 5, seen
        assert seen["names"] == ["Sign-in page"], seen
        assert seen["marks"] == seen["withChips"], "every chip carries its kind's mark"
        assert seen["clickable"] == 0, "a chip is never clickable — the box it sits on is"
        assert "interfaces they meet in each" in seen["sentence"], seen["sentence"]
        assert not page.js_errors, page.js_errors


def test_a_use_case_this_actor_is_in_without_driving_gets_its_own_lane() -> None:
    """The page dropped these entirely. It counted only the use cases an actor DRIVES, under a
    sentence promising "drives or takes part in", beside an Interfaces section that named the others
    all along — so the Team member's page read "5 use cases" over a board of five while the section
    below it named nine.

    THEIR OWN LANE, not the lower one. A side stop means something this actor CAN DO, and a member
    cannot refresh somebody else's credential — so the box would have stated something untrue. The
    lane names the difference, and each box leads with a chip saying who does drive it."""
    with _served_map(_a_door_for_a_bystander()) as url, \
            _page(url + "#v=actor&act=Team%20member") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const parts = [...document.querySelectorAll('.journey-part')];
            return { lane: (document.querySelector('.journey-gutter-part') || {}).textContent || '',
                     parts: parts.map((p) => ({
                         drivers: [...p.querySelectorAll('.journey-drivers .item-pill')]
                                    .map((c) => c.textContent.trim()),
                         // The driver's chip is the FIRST thing in the box's text column.
                         first: p.querySelector('.journey-sidet').firstElementChild.className,
                         uc: p.getAttribute('data-uc') })),
                     // …and it is NOT filed with the things this actor can do.
                     sides: document.querySelectorAll('.journey-side:not(.journey-part)').length,
                     count: (document.body.innerText.match(/Use cases\\s*(\\d+)/) || [])[1] };
        }""")
        assert seen["lane"] == "Takes part in, doesn’t drive", seen["lane"]
        assert [p["uc"] for p in seen["parts"]] == ["UC1"], seen
        assert seen["parts"][0]["drivers"] == ["Org creator"], seen
        assert seen["parts"][0]["first"] == "journey-drivers", seen
        # Three stations on the happy path, and the one they take part in — counted, because the
        # heading sits eight pixels above a board that now draws all four.
        assert seen["count"] == "4", seen
        assert not page.js_errors, page.js_errors


def test_the_third_lane_belongs_to_the_actor_page_alone() -> None:
    """A feature's board is the actor board's mirror and shares its builder, so a lane added to one
    lands on both unless the caller decides. It must not: a feature's box zones by DRIVER and can
    name several actors, so "which use cases does this actor not drive" has no single answer there."""
    with _served_map(_a_door_for_a_bystander()) as url, \
            _page(url + "#v=capability&cap=CAP1") as page:
        _settle(page)
        seen = page.evaluate("""() => ({
            board: !!document.querySelector('.journey-board'),
            stations: document.querySelectorAll('.journey-track .flow-step').length,
            lane: document.querySelectorAll('.journey-gutter-part').length,
            parts: document.querySelectorAll('.journey-part').length,
            chips: document.querySelectorAll('.journey-ifs').length })""")
        assert seen["board"] and seen["stations"] >= 1, seen
        assert seen["lane"] == 0 and seen["parts"] == 0, seen
        # The chips are a different matter: a feature's board shows where each use case happens, as the
        # Happy Path does — the WHOLE use case's interfaces, whoever holds that stretch.
        assert seen["chips"] >= 1, "where each use case happens, as the Happy Path draws it"
        assert not page.js_errors, page.js_errors


def test_every_box_on_a_board_carries_its_use_case_own_sentence() -> None:
    """A box named a use case and stopped there, so "what do I get out of this" was only answerable
    by leaving the board. Worse in the lower lane: a side stop HAD carried that sentence on the card
    the rail replaced, so the rail bought who-drives-what by taking the sentence away.

    THE SAME SENTENCE the use case's own card shows, read through `cardFacts` — one field chosen in
    one table, so the words on a box and the words on a card cannot drift. And NOT CLAMPED: a cut
    sentence loses its end, and the end is the outcome, which is the half the name has not already
    said."""
    # THE PUNCTUATION CASES, planted here because the committed fixture happens to write every
    # trigger as a fragment with no stop at all, so the rule the card applies would go untested.
    def punctuate(m: dict) -> None:
        _a_door_for_a_bystander()(m)
        for u in m["use_cases"]:
            if u["id"] == "UC1":                       # a stop the arrow would say twice…
                u["trigger"] = "An invited person opens the link."
                u["outcome"] = "They land inside the organization."   # …and one nothing follows
            if u["id"] == "UC13":                      # …and one the arrow cannot say for it
                u["trigger"] = "Did the admin approve?"

    with _served_map(punctuate) as url, \
            _page(url + "#v=capability&cap=CAP1") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const boxes = [...document.querySelectorAll('.journey-track .flow-step, .journey-side')];
            const read = (b) => {
                const w = b.querySelector('.flow-step-what');
                return { uc: b.getAttribute('data-uc'),
                         text: w ? w.textContent.trim() : null,
                         // The sentence sits between the name and the chips, never after them.
                         afterTitle: !!w && w.previousElementSibling
                                     && w.previousElementSibling.className === 'flow-step-title',
                         // Nothing hidden: an unclamped run shows everything it holds.
                         clipped: !!w && w.scrollHeight > w.clientHeight + 1 };
            };
            return { boxes: boxes.length, rows: boxes.map(read),
                     stations: document.querySelectorAll('.journey-track .flow-step').length,
                     stops: document.querySelectorAll('.journey-side').length };
        }""")
        assert seen["stations"] >= 1 and seen["stops"] >= 1, seen
        # EVERY box, in both lanes.
        assert all(r["text"] for r in seen["rows"]), seen
        assert all(r["afterTitle"] for r in seen["rows"]), seen
        assert not any(r["clipped"] for r in seen["rows"]), seen
        # …and it is the map's own words for that use case, joined by the arrow, since the map holds
        # a trigger and an outcome apart. THE ARROW IS THE PUNCTUATION: the trigger's own full stop
        # would land hard against it and say the stop twice, so the join drops it — and only it. A
        # "?" survives, because the arrow does not say what a question mark says, and the outcome
        # keeps its stop, because nothing follows it.
        said = {r["uc"]: r["text"] for r in seen["rows"]}
        ucs = {u["id"]: u for u in json.loads(_FIXTURE_MAP.read_text())["use_cases"]}
        ucs["UC1"]["trigger"] = "An invited person opens the link."
        ucs["UC1"]["outcome"] = "They land inside the organization."
        ucs["UC13"]["trigger"] = "Did the admin approve?"
        wanted = {i: " \u2192 ".join(x for x in (u["trigger"].strip().removesuffix("."),
                                                u["outcome"].strip()) if x)
                  for i, u in ucs.items()}
        assert said and all(said[uc] == wanted[uc] for uc in said), (said, wanted)
        # The two planted cases, stated outright so a future edit cannot pass by matching itself.
        assert said["UC1"].startswith("An invited person opens the link \u2192"), said["UC1"]
        assert said["UC13"].startswith("Did the admin approve? \u2192"), said["UC13"]
        assert said["UC1"].endswith("."), "the outcome keeps the stop that ends the card"
        assert not page.js_errors, page.js_errors


def test_the_chips_line_up_on_one_band_and_a_longer_title_keeps_its_own_text() -> None:
    """The chips start after the station's two runs of text — its use case's name, then that use
    case's own sentence — so on a board where either run varies the chips sat at as many heights as
    there were stations, and the row read as a ragged edge instead of a band.

    TWO FLOORS, one per run. The TITLE takes the majority, not the tallest: one long title would
    otherwise open a blank line under every other station to make room for the exception. The
    SENTENCE then takes whatever is left over, so the pair of runs measures the same in every station
    and the chips land on one line. That is what lets the long title keep its own text AND stay on
    the band — it was the one station whose chips hung a line below everyone else's, which is the
    ragged edge the pass exists to remove rather than a fact worth showing.

    A floor, never a height: no run is ever cut, which is what makes this safe to point at a
    sentence the box does not clamp."""
    with _served_map(_a_door_for_a_bystander(long_title=True)) as url, \
            _page(url + "#v=actor&act=Org%20admin") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const st = [...document.querySelectorAll('.journey-track .flow-step')];
            const rows = st.map((s) => {
                const t = s.querySelector('.flow-step-title'), w = s.querySelector('.flow-step-what');
                const f = s.querySelector('.journey-ifs');
                return { floor: t.style.minHeight,
                         h: Math.round(t.getBoundingClientRect().height),
                         // A floor never cuts: the run is at least as tall as the floor it was given.
                         whole: w.getBoundingClientRect().height + 1
                                >= parseFloat(w.style.minHeight || 0),
                         top: f ? Math.round(f.getBoundingClientRect().top) : null };
            });
            const floor = Math.round(parseFloat(rows[0].floor));
            const withChips = rows.filter((r) => r.top !== null);
            return { floors: [...new Set(rows.map((r) => r.floor))], floor,
                     withChips: withChips.length,
                     tops: [...new Set(withChips.map((r) => r.top))],
                     overCount: rows.filter((r) => r.h > floor + 1).length,
                     cut: rows.filter((r) => !r.whole).length };
        }""")
        # ONE title floor for the whole board, and it is the majority: the long title stands over it.
        assert len(seen["floors"]) == 1 and seen["floors"][0], seen
        assert seen["overCount"] >= 1, "the long title must actually have outgrown the majority"
        # …and EVERY station's chips land on one line, the long-titled one included.
        assert seen["withChips"] >= 4 and len(seen["tops"]) == 1, seen
        # Nothing was cut to get there.
        assert seen["cut"] == 0, seen
        assert not page.js_errors, page.js_errors


def test_every_use_case_on_a_board_is_picked_and_put_down_the_same_way() -> None:
    """A pick was the happy-path step's alone. A side stop and a takes-part box opened the same use
    case by the same click and lit nothing, so two thirds of the board answered a gesture the other
    third answered visibly — and none of them could be put DOWN: the ring stayed, and stayed in the
    address, so a copied link carried a choice its reader had already abandoned.

    ONE KEY for all three (`data-pick`), because a stop has no step behind it and a bare step id
    could not have said which kind of box it named. `hpstep:` is untouched, so a link shared before
    any of this still lands on its step."""
    with _served_map(_a_door_for_a_bystander()) as url, \
            _page(url + "#v=actor&act=Team%20member") as page:
        _settle(page)
        keys = page.evaluate("""() => [...document.querySelectorAll('.pickbox')]
            .map((b) => b.getAttribute('data-pick'))""")
        assert any(k.startswith("hpstep:") for k in keys), keys
        assert any(k.startswith("ucstop:") for k in keys), keys
        # PICK A STOP — the lane that could not be picked at all — and come back to it.
        picked = page.evaluate("""async () => {
            const stop = document.querySelector('.journey-side.pickbox');
            const key = stop.getAttribute('data-pick');
            stop.click();
            await new Promise((r) => setTimeout(r, 500));
            const went = location.hash;
            history.back();
            await new Promise((r) => setTimeout(r, 800));
            const lit = document.querySelector('.pickbox.ibox-picked');
            return { key, went, back: location.hash,
                     lit: lit && lit.getAttribute('data-pick') };
        }""")
        assert picked["went"].startswith("#v=usecase&uc="), picked
        assert picked["lit"] == picked["key"], picked
        assert "sel=ucstop" in picked["back"].replace("%3A", ":"), picked
        # …and the BACKGROUND puts it down, in the ring and in the address together.
        after = page.evaluate("""async () => {
            document.querySelector('.journey-board')
                .dispatchEvent(new MouseEvent('click', { bubbles: true }));
            await new Promise((r) => setTimeout(r, 250));
            return { lit: !!document.querySelector('.pickbox.ibox-picked'), hash: location.hash };
        }""")
        assert not after["lit"] and "sel=" not in after["hash"], after
        assert not page.js_errors, page.js_errors


def test_leaving_the_page_is_not_the_gesture_that_puts_a_box_down() -> None:
    """The clearing click is scoped to the view. A click on a view TAB is also a click on `document`,
    and unscoped it dropped the pick a moment before the navigation that was meant to remember it —
    the bug the Interfaces picture's own outside click was written to avoid, repeated here."""
    with _served_map(_a_door_for_a_bystander()) as url, \
            _page(url + "#v=actor&act=Team%20member") as page:
        _settle(page)
        kept = page.evaluate("""async () => {
            document.querySelector('.pickbox[data-uc]').click();
            await new Promise((r) => setTimeout(r, 500));
            history.back();
            await new Promise((r) => setTimeout(r, 800));
            const before = location.hash;
            // a click on the app's own chrome, outside #diagram
            document.querySelector('header, #crumb, .tabrow, body')
                .dispatchEvent(new MouseEvent('click', { bubbles: true }));
            await new Promise((r) => setTimeout(r, 250));
            return { before, after: location.hash,
                     lit: !!document.querySelector('.pickbox.ibox-picked') };
        }""")
        assert "sel=" in kept["before"], kept
        assert kept["lit"] and kept["after"] == kept["before"], kept
        assert not page.js_errors, page.js_errors


def test_a_use_case_reads_the_same_wherever_the_board_draws_it() -> None:
    """Three lanes drew one sentence three ways. A step's title was 11.5px near-black; a stop's name
    was 11px grey, eight pixels below it. And a step's title starts life as a walk title with its
    leading actor designator stripped, so it opened lower case — "wires their AI client" under
    "Import several MCPs", which reads as two kinds of thing rather than as two use cases.

    ONE CLASS carries the text now (`.flow-step-title`), on every lane, and the capital is put on in the
    builder rather than by `::first-letter` — a rule no test could read back, and a second place to
    keep in step with this one."""
    with _served_map(_a_door_for_a_bystander()) as url, \
            _page(url + "#v=actor&act=Org%20admin") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const ts = [...document.querySelectorAll('.flow-step-title')];
            const style = (e) => { const c = getComputedStyle(e);
                                   return [c.fontSize, c.color, c.lineHeight].join('|'); };
            const texts = ts.map((t) => t.textContent.trim()).filter(Boolean);
            return { lanes: { steps: document.querySelectorAll('.journey-track .flow-step-title').length,
                              stops: document.querySelectorAll('.journey-sides .flow-step-title').length },
                     styles: [...new Set(ts.map(style))],
                     lower: texts.filter((t) => t[0] !== t[0].toUpperCase()) };
        }""")
        # Both lanes actually drawn, or the comparison below proves nothing.
        assert seen["lanes"]["steps"] >= 1 and seen["lanes"]["stops"] >= 1, seen
        assert len(seen["styles"]) == 1, seen["styles"]
        assert seen["lower"] == [], seen["lower"]
        # …and the words are the door, so hovering underlines them wherever they are.
        hover = page.evaluate("""() => {
            const rule = [...document.styleSheets].flatMap((ss) => {
                try { return [...ss.cssRules]; } catch (e) { return []; } })
                .filter((r) => r.selectorText && /\\.pickbox:hover \\.flow-step-title/.test(r.selectorText));
            return rule.map((r) => r.style.textDecorationLine || r.style.textDecoration);
        }""")
        assert hover and any("underline" in h for h in hover), hover
        assert not page.js_errors, page.js_errors


def test_a_chip_draws_its_mark_in_the_same_place_on_a_board_as_on_a_card() -> None:
    """The rendered half of the same promise. The stylesheet test beside this one pins that no page
    re-styles the chip; this measures that the chip therefore LOOKS the same in both places, which is
    the thing a reader actually sees and the thing that was wrong.

    Measured, not eyeballed: the mark's top edge against the chip's own top edge, on a chip in a use
    case lane and on a chip on a surface card, on one screen. They were 3.5px and 1.8px apart."""
    with _served_map(_a_door_for_a_bystander()) as url, \
            _page(url + "#v=actor&act=Org%20admin") as page:
        _settle(page)
        # TWO SCREENS, because the actor page no longer carries a card: its Interfaces block went, and
        # the chip on a card now lives on the Interfaces view. Same document, same stylesheet, so the
        # comparison is the same one — a chip in a use case lane against a chip on a surface card.
        seen = page.evaluate("""async () => {
            const at = (sel) => [...document.querySelectorAll(sel)].map((c) => {
                const g = c.querySelector('.ibox-gly');
                if (!g || !c.getBoundingClientRect) return null;
                const cr = c.getBoundingClientRect(), gr = g.getBoundingClientRect();
                if (!cr.height || !gr.height) return null;   // not laid out on this screen
                return { top: Math.round((gr.top - cr.top) * 10) / 10,
                         h: Math.round(cr.height * 10) / 10 };
            }).filter(Boolean);
            const lane = at('.journey-ifs .item-pill');
            location.hash = '#v=interfaces';
            await new Promise((r) => setTimeout(r, 800));
            const card = at('.ifd-box .item-pill');
            return { laneTops: [...new Set(lane.map((x) => x.top))],
                     cardTops: [...new Set(card.map((x) => x.top))],
                     laneOne: [...new Set(lane.filter((x) => x.h < 22).map((x) => x.h))],
                     cardOne: [...new Set(card.map((x) => x.h))],
                     counts: { lane: lane.length, card: card.length } };
        }""")
        # Both places actually drawn, or there is nothing to compare.
        assert seen["counts"]["lane"] >= 1 and seen["counts"]["card"] >= 1, seen
        # ONE mark position, across both places and including a chip whose name wrapped.
        assert seen["laneTops"] == seen["cardTops"] and len(seen["laneTops"]) == 1, seen
        # …and a one-line chip is the same height wherever it stands.
        assert seen["laneOne"] == seen["cardOne"] and len(seen["laneOne"]) == 1, seen
        assert not page.js_errors, page.js_errors


def test_a_use_case_names_the_interfaces_its_own_flow_reaches() -> None:
    """The tags used to come from the ADDRESSES a use case is entered at: a surface we define claimed
    every use case reachable at one of its ways in, whether or not the story ever went there. On the
    live map that put a Dashboard tag on "Weigh up the product before signing up", whose ten interface
    steps are nine at the Product website and one at Usage analytics and none at the Dashboard.
    Measured against the steps, the address rule made 77 claims to the steps' 72 — it added nothing
    true and five that were false.

    Read off the steps, a tag cannot outrun the picture the reader is looking at."""
    with _served_map(_three_ways_to_reach_a_surface()) as url, _page(url + "#v=hp") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const at = {};
            for (const s of document.querySelectorAll('.flow-step[data-uc]')) {
                at[s.getAttribute('data-uc')] = [...s.querySelectorAll('.journey-ifs .item-pill')]
                    .map((c) => c.textContent.trim()).sort();
            }
            return at;
        }""")
        # UC1's flow draws all three shapes, so the whole-story rule shows all three.
        assert seen.get("UC1") == ["Google sign-in", "The dashboard", "Usage analytics"], seen
        # UC2 reaches the surface ONLY through the shared sub-flow, and still names it.
        assert seen.get("UC2") == ["Google sign-in"], seen
        assert not page.js_errors, page.js_errors


def test_an_actor_s_page_keeps_only_the_interfaces_that_actor_meets() -> None:
    """A use case page asks "where does this happen"; an actor's page asks "where does THIS PERSON
    meet the product in it". The product calls an analytics service by itself, with nobody at either
    end, so that surface belongs on the first answer and not on the second.

    A SHARED SUB-FLOW is the exception, and it is not a loophole: a sub-flow cannot name a person —
    `SF1` here is run by two use cases with different drivers, as `Sign in with Google` is on the live
    map — so no door can ever be drawn inside one, and "the person this run is for" is the strongest
    claim the map can make. Without it the two use cases that reach that surface show it nowhere."""
    with _served_map(_three_ways_to_reach_a_surface()) as url, \
            _page(url + "#v=actor&act=Org%20creator") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const at = {};
            for (const s of document.querySelectorAll('.pickbox[data-uc]')) {
                at[s.getAttribute('data-uc')] = [...s.querySelectorAll('.journey-ifs .item-pill')]
                    .map((c) => c.textContent.trim()).sort();
            }
            return at;
        }""")
        # the door survives, the sub-flow's surface survives, the one nobody stands at does not
        assert seen.get("UC1") == ["Google sign-in", "The dashboard"], seen
        assert "Usage analytics" not in (seen.get("UC1") or []), seen
        assert not page.js_errors, page.js_errors


def test_an_actor_s_page_is_the_board_and_nothing_else() -> None:
    """The page carried an Interfaces block under the board — the same surfaces the board now names on
    the use cases themselves, drawn three columns wide at 1295px against the board's 421, so 61% of
    the page restated what a tag says. Worse, it did it by the ADDRESS rule the board had just stopped
    using, so the two halves contradicted each other on five rows of the live map.

    The chip strip went with it: a contents bar listing one section is a label with extra steps. The
    MECHANISM stays, and this pins that too — a feature's page still builds one."""
    with _served_map(_three_ways_to_reach_a_surface()) as url, \
            _page(url + "#v=actor&act=Org%20creator") as page:
        _settle(page)
        gone = page.evaluate("""() => ({
            interfacesBlock: document.querySelectorAll('.asf-stage').length,
            indexChips: document.querySelectorAll('.tab-index-chip').length,
            board: document.querySelectorAll('.journey-board').length,
            sections: document.querySelectorAll('.item-sec-note').length })""")
        assert gone == {"interfacesBlock": 0, "indexChips": 0, "board": 1, "sections": 1}, gone
        # …and the pages that still have several sections still get the strip.
        kept = page.evaluate("""async () => {
            location.hash = '#v=capability&cap=CAP1';
            await new Promise((r) => setTimeout(r, 800));
            return document.querySelectorAll('.tab-index-chip').length;
        }""")
        assert kept >= 2, kept


def test_a_use_case_page_is_the_same_page_as_an_actor_s_a_named_hero_over_a_framed_section() -> None:
    """A use case's page drew its sentence in the fixed block under the trail, with no name and no glyph,
    and the map ran straight under the shadow with nothing saying what it was. An actor's page, one click
    away, names the actor on a hero and announces its board as a section. The two are the same kind of
    screen — one element, with its board under it — so the use case's page now draws the same two blocks,
    IN THE PAGE: a hero carrying the use case's glyph, name and pill, and a section head over the frame
    whose count is the step player's own total. The board itself stays in the drawing area, because the
    pan/zoom, the floating controls and the card all measure against that box."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const q = (s) => document.querySelector(s);
            const box = (e) => { const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top)]; };
            const wrap = q('#diagwrap'), cs = getComputedStyle(wrap);
            return {
                headShown: !q('#diaghead').hidden, fixedHeroShown: !q('#pagehero').hidden,
                name: q('#diaghead .page-hero-subject').textContent,
                glyph: !!q('#diaghead .page-hero-glyph .ibox-gly'),
                pills: [...document.querySelectorAll('#diaghead .ecard-pill')].map((e) => e.textContent),
                kind: (q('#diaghead .page-hero-kind') || {}).textContent,
                sentence: q('#diaghead .page-hero-purpose').textContent.length,
                title: [...q('#diaghead .item-sec-title').childNodes].filter((n) => n.nodeType === 3)
                         .map((n) => n.textContent).join('').trim(),
                count: q('#diaghead .count-pill').textContent,
                note: q('#diaghead .item-sec-note').textContent.length,
                player: q('#flowcount').textContent,
                headAboveFrame: q('#diaghead').getBoundingClientRect().bottom <= wrap.getBoundingClientRect().top,
                frame: {radius: cs.borderRadius, border: cs.borderLeftColor},   // the top edge is the strip's
                left: [box(q('#diaghead .page-hero')), box(wrap)].map((b) => b[0]),
                mapInFrame: !!q('#diagram svg') && wrap.contains(q('#diagram svg')),
            };
        }""")
        assert seen["headShown"] and not seen["fixedHeroShown"], seen
        assert seen["name"] and seen["glyph"] and seen["kind"] == "Use case:" and seen["pills"] == [], \
            "the type is a word before the name, not a pill after it: " + str(seen)
        assert seen["sentence"] > 0 and seen["note"] > 0, seen
        assert seen["title"] == "Use case flow", seen
        assert seen["player"].endswith(" / " + seen["count"].split(" ")[0]), \
            "the section counts what the player steps through"
        assert seen["count"].endswith(" steps"), "the count keeps its noun"
        assert seen["headAboveFrame"] and seen["mapInFrame"], seen
        # The frame is the section frame's own: the actor page's colours, not the drawing's old ones.
        # The frame's top corners are square: the strip above it carries the rounded top, and the
        # two are one box.
        assert seen["frame"] == {"radius": "0px 0px 12px 12px", "border": "rgb(203, 213, 225)"}, seen
        assert seen["left"] == [20, 20], "the hero band and the frame share the actor page's left edge"
        # …and the actor's page is untouched, which is the whole point: it stays the reference.
        page.goto(url + "#v=actor&act=Org creator")
        _settle(page)
        other = page.evaluate("""() => ({
            headShown: !document.getElementById('diaghead').hidden,
            headEmpty: document.getElementById('diaghead').innerHTML === '',
            margin: getComputedStyle(document.getElementById('diagwrap')).margin })""")
        assert not other["headShown"] and other["headEmpty"], other
        assert other["margin"] == "0px", other    # a text page's own rule, unchanged
        assert not page.js_errors, page.js_errors


def test_a_shared_sub_use_case_s_page_draws_the_same_head_from_its_own_words() -> None:
    """A shared sub-use case is not a graph node, so the fixed-block hero never had anything to say about
    it and its page opened straight on the map. It gets the same head as a use case, from the subflow
    itself: its name, its own word for a pill, no sentence (it has none), and its own step count."""
    with _served_map(_with_shared_walk) as url, _page(url + "#v=subflow&sf=SF1&uc=UC1") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const q = (s) => document.querySelector(s);
            return {
                name: q('#diaghead .page-hero-subject').textContent,
                pills: [...document.querySelectorAll('#diaghead .ecard-pill')].map((e) => e.textContent),
                kind: (q('#diaghead .page-hero-kind') || {}).textContent,
                sentence: !!q('#diaghead .page-hero-purpose'),
                foot: !!q('#diaghead .ecard-extra'),
                title: [...q('#diaghead .item-sec-title').childNodes].filter((n) => n.nodeType === 3)
                         .map((n) => n.textContent).join('').trim(),
                count: q('#diaghead .count-pill').textContent,
                player: q('#flowcount').textContent,
            };
        }""")
        assert seen["name"] == "Keep the organization", seen
        assert seen["kind"] == "Shared sub-use case:" and seen["pills"] == [], seen
        assert not seen["sentence"] and not seen["foot"], "nothing is drawn where the map has nothing"
        assert seen["title"] == "Shared sub-use case flow" and seen["count"] == "2 steps", seen
        assert seen["player"] == "\u2013 / 2", seen
        assert not page.js_errors, page.js_errors


def test_a_step_number_sits_at_the_middle_of_its_arrow_on_screen() -> None:
    """The layout engine puts a label half way between the two boxes' columns and ignores how far the
    curve climbs or drops on the way: on mcpolis UC1 a number sat 15% along one arrow and 88% along the
    next. Only a browser draws the curves, so only a browser can measure where the numbers landed."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        _settle(page)
        off = page.evaluate("""() => {
            const root = document.getElementById('diagram');
            const paths = [...root.querySelectorAll('.edgePaths path.flowchart-link')];
            const labels = [...root.querySelectorAll('.edgeLabels > g.edgeLabel')];
            const out = [];
            paths.forEach((p, i) => {
              const L = labels[i];
              if (!L || !L.textContent.trim()) return;
              const len = p.getTotalLength(), m = p.getScreenCTM(), pt = p.getPointAtLength(len / 2);
              const mid = { x: pt.x * m.a + pt.y * m.c + m.e, y: pt.x * m.b + pt.y * m.d + m.f };
              const r = L.getBoundingClientRect();
              out.push(Math.hypot(mid.x - (r.left + r.right) / 2, mid.y - (r.top + r.bottom) / 2));
            });
            return out;
        }""")
        assert len(off) >= 5, "the fixture's first use case draws labelled arrows"
        assert max(off) < 2, f"every number within 2px of its arrow's middle, got {[round(x) for x in off]}"
        assert not page.js_errors, page.js_errors


def test_clicking_an_arrow_beside_its_number_still_points_the_line_at_the_number() -> None:
    """Click the number: the line went to the number. Click the arrow's line a little way from it: the
    line jumped to the arrow's middle. Both clicks select the same step and show the same card, so the
    line must land in the same place — on the number, which is the one thing that says which step."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        _settle(page)
        seen = page.evaluate("""async () => {
            const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
            const root = document.getElementById('diagram');
            const wrap = document.getElementById('diagwrap').getBoundingClientRect();
            const end = () => { const c = document.querySelector('#callout circle');
                                return c ? { x: +c.getAttribute('cx') + wrap.left, y: +c.getAttribute('cy') + wrap.top } : null; };
            // ON the number means BESIDE it: the dot stands off the digit by NUM_DOT_CLEAR (7px, up to
            // 10px at a corner) so the digit stays readable, and never on the digit's own pixels.
            const inside = (pt, r, by) => pt.x >= r.left - by && pt.x <= r.right + by && pt.y >= r.top - by && pt.y <= r.bottom + by;
            const on = (pt, r) => !!pt && inside(pt, r, 11) && !inside(pt, r, 0);
            // A press, then a click, at the same spot: a click with no press before it reads as a drag.
            const press = (el, x, y) => { for (const type of ['mousedown', 'click'])
              el.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX: x, clientY: y })); };
            // A one-step arrow: a number whose row holds only itself.
            const num = [...root.querySelectorAll('.flow-step-num')].find((n) => n.parentNode.children.length === 1);
            const arrow = num.__cyArrow;
            const r0 = num.getBoundingClientRect();
            press(num, (r0.left + r0.right) / 2, (r0.top + r0.bottom) / 2);
            await sleep(500);
            const byNumber = { hash: location.hash, onNumber: on(end(), num.getBoundingClientRect()) };
            // Then the arrow's own hit area, a fifth of the way along — well clear of the number.
            const len = arrow.getTotalLength(), m = arrow.getScreenCTM(), q = arrow.getPointAtLength(len / 5);
            const x = q.x * m.a + q.y * m.c + m.e, y = q.x * m.b + q.y * m.d + m.f;
            press(arrow.__cyHits[0], x, y);
            await sleep(500);
            const r = num.getBoundingClientRect();
            const byArrow = { hash: location.hash, onNumber: on(end(), r),
                              clickToNumber: Math.hypot(x - (r.left + r.right) / 2, y - (r.top + r.bottom) / 2),
                              line: !document.getElementById('callout').hasAttribute('hidden') };
            return { byNumber, byArrow };
        }""")
        assert "flowstep%3A" in seen["byNumber"]["hash"] and seen["byNumber"]["onNumber"], seen
        assert "flowpair%3A" in seen["byArrow"]["hash"], seen
        assert seen["byArrow"]["clickToNumber"] > 15, "the click was well clear of the number"
        assert seen["byArrow"]["line"] and seen["byArrow"]["onNumber"], \
            f"the line ends on the number whichever pixels of the arrow were clicked: {seen}"
        assert not page.js_errors, page.js_errors


def test_a_page_about_a_pair_names_the_pair_and_heads_its_drawing() -> None:
    """A pair page's subject is a RELATION, not one element, so the hero's "which element is this page
    about" lookup answered nothing for it — and all three of these drew NOTHING above the drawing: no
    name, no path back, and no strip saying what the picture was of. The page's whole title lived in the
    collapsed crumb row, which is there for a screen reader and is never on screen, so following an arrow
    landed the reader on two framed groups with not a word saying which two.

    Each now wears what every other drilled page wears: the path, a hero naming the pair (`Subsystem
    pair: A -> B`), and the grey strip over the frame with the crossings counted. The count comes from
    the SAME list the arrow's own card counts, so the card that offered the page and the page it opens
    cannot report two different numbers."""
    want = [
        ("#v=edge&a=S1&b=S10", "Subsystem pair:", "What crosses between them", "connection", True),
        ("#v=domedge&a=SD3&b=SD2", "Subdomain pair:", "What crosses between them", "relation", True),
        # A bridge's two ends are different kinds, so neither mark stands for the page and it draws none.
        ("#v=bridge&sid=S13&sd=SD3", "Subsystem and subdomain:", "What this subsystem reaches", "link", False),
    ]
    with _served() as url, _page(url) as page:
        for hash_, kind, title, noun, glyph in want:
            page.goto(url + hash_)
            _settle(page)
            seen = page.evaluate("""() => {
                const q = (s) => document.querySelector(s);
                const hero = q('#pagehero .page-hero');
                const strip = q('#diaghead .item-sec-strip-stage');
                return {
                    kind: (q('#pagehero .page-hero-kind') || {}).textContent || '',
                    name: (q('#pagehero .page-hero-subject') || {}).textContent || '',
                    band: !!hero && hero.classList.contains('page-hero-band'),
                    glyph: !!q('#pagehero .page-hero-glyph'),
                    sentence: !!q('#pagehero .page-hero-purpose'),
                    path: (q('.page-path') || {}).textContent || '',
                    title: strip ? [...strip.querySelectorAll('.item-sec-title')[0].childNodes]
                             .filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim() : '',
                    count: strip ? (strip.querySelector('.count-pill') || {}).textContent || '' : '',
                    note: strip ? ((strip.querySelector('.item-sec-note') || {}).textContent || '').length : 0,
                    h1: (q('#crumb h1') || {}).textContent || '',
                    drawn: !!q('#diagram svg'),
                };
            }""")
            assert seen["kind"] == kind, (hash_, seen)
            # The pair is named on screen, and it is the SAME words the document's own h1 carries.
            assert " → " in seen["name"] and seen["name"] == seen["h1"], (hash_, seen)
            assert seen["band"] and not seen["sentence"], \
                f"the named hero's card, and no sentence — the map records none about a pair: {seen}"
            assert seen["glyph"] is glyph, (hash_, seen)
            assert seen["path"].strip(), f"the way back up is drawn: {seen}"
            assert seen["title"] == title, (hash_, seen)
            assert re.fullmatch(rf"\d+ {noun}s?", seen["count"]), \
                f"the count keeps its noun: {seen}"
            assert seen["note"] > 0 and seen["drawn"], (hash_, seen)
        assert not page.js_errors, page.js_errors


def test_the_pair_page_counts_the_whole_pair_however_the_reader_arrived() -> None:
    """The page's strip counts THE PAIR. Its number is the unfiltered list, whichever arrow the reader
    came through — which is the fact worth pinning, because a card can legitimately say something else.

    An arrow drawn from a MEMBER filters the same list to the one component that was clicked, so the
    card can read 4 where the page reads 11. Both are right about their own subject. The earlier test
    here asserted the two are always EQUAL, and only ever checked the overview arrow, where both ends
    are whole subsystems and nothing is filtered — so the one case that can disagree was the one case
    it could not see."""
    with _served() as url, _page(url + "#v=container") as page:
        _settle(page)
        seen = page.evaluate("""async () => {
            const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
            const strip = () => (document.querySelector('#diaghead .count-pill') || {}).textContent || '';
            const card = () => (document.querySelector('#panel .xcount') || {}).textContent || '';
            const out = {};
            // The pair's own page: the number every route to it must show.
            location.hash = '#v=edge&a=S1&b=S3';
            await sleep(900);
            out.page = strip();
            // Reached through the OVERVIEW arrow, where both ends are whole subsystems: nothing is
            // filtered, so the card agrees.
            location.hash = '#v=container&sel=sedge%3AS1%3ES3';
            await sleep(900);
            out.wholeArrowCard = card();
            // …and reached through a MEMBER's arrow on a subsystem's own page, which filters.
            location.hash = '#v=subsystem&sid=S1';
            await sleep(900);
            const hit = [...document.querySelectorAll('#diagram .cy-edgehit')][0];
            if (hit) {
              const r = hit.getBoundingClientRect();
              for (const t of ['mousedown', 'click'])
                hit.dispatchEvent(new MouseEvent(t, {bubbles: true, detail: 1,
                  clientX: (r.left + r.right) / 2, clientY: (r.top + r.bottom) / 2}));
              await sleep(700);
              out.memberArrowCard = card();
            }
            return out;
        }""")
        assert re.fullmatch(r"\d+ connections?", seen["page"]), seen
        assert seen["wholeArrowCard"] == seen["page"], \
            f"an arrow between two whole subsystems filters nothing, so its card agrees: {seen}"
        # A member arrow's card is a SUBSET of the pair — never larger than the page's own count.
        if seen.get("memberArrowCard"):
            n = lambda s: int(s.split(" ")[0])
            assert n(seen["memberArrowCard"]) <= n(seen["page"]), \
                f"a member's card counts its own share of the pair, never more: {seen}"
        assert not page.js_errors, page.js_errors


#: What a FOLD PAGE's head says — read once, by both fold tests, so they cannot drift into
#: checking two different things about one screen.
_FOLD_HEAD_JS = """() => {
    const q = (s) => document.querySelector(s);
    const strip = q('#diaghead .item-sec-strip-stage');
    return {
        name: (q('#pagehero .page-hero-subject') || {}).textContent || '',
        heroSentence: !!q('#pagehero .page-hero-purpose'),
        h1: (q('#crumb h1') || {}).textContent || '',
        title: strip ? [...strip.querySelector('.item-sec-title').childNodes]
                 .filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim() : '',
        count: strip ? (strip.querySelector('.count-pill') || {}).textContent || '' : '',
        note: strip ? (strip.querySelector('.item-sec-note') || {}).textContent || '' : '',
        drawn: !!q('#diagram svg'),
    };
}"""


def _with_external_bucket(m: Any) -> None:
    """Five external systems sharing one purpose, which is what collapses a bucket into a count box —
    the committed fixture has no bucket fold at all, and so has neither live map."""
    m["deps"] = list(m["deps"]) + [
        {"id": f"D9{i}", "name": f"Partner API {i}", "kind": "service", "type": "REST API",
         "used_for": "One of the partner systems this test needs a bucket of",
         "bucket": "Partner systems", "where_configured": "", "confidence": "inferred",
         "deployment_linked": False}
        for i in range(5)]


def test_a_folded_group_is_named_and_its_drawing_headed() -> None:
    """The same mistake one page over: a hero built with no `name` has no visible title at all, because
    the crumb row that used to carry it is collapsed. A fold page opened on a bare sentence — nothing
    said WHICH fold you had drilled into — and the picture under it wore a bare frame.

    The two blocks are split the way every other drawn page splits them: the hero is the fold's name,
    and the sentence (which describes the DRAWING) is the strip's note, with the fold's own count."""
    with _served() as url, _page(url + "#v=libs") as page:
        _settle(page)
        seen = page.evaluate(_FOLD_HEAD_JS)
        assert seen["name"] == "Libraries" == seen["h1"], seen
        assert not seen["heroSentence"], f"the sentence is the strip's now, not the hero's: {seen}"
        assert seen["title"] == "What is folded here", seen
        assert re.fullmatch(r"\d+ dependenc(y|ies)", seen["count"]), seen
        assert seen["note"].startswith("Frameworks and libraries linked into the process,"), seen
        assert "drill in" not in seen["note"], "the reader is already inside"
        assert seen["drawn"], seen
        assert not page.js_errors, page.js_errors


def test_a_bucket_fold_says_what_it_actually_holds() -> None:
    """One sentence served BOTH bucket folds, so a library bucket announced itself as external systems:
    on the live map `Frontend / UI` — React, Vite, TanStack Query, reached through
    `Dependencies > Libraries >` — contradicted its own trail two lines above it. Each bucket reads the
    fold it sits in now. Neither live map has an external bucket, so this one is built."""
    with _served_map(_with_external_bucket) as url:
        buckets = json.loads(urlopen(url + "api/view").read().decode())["foldedBuckets"]
        external = [b for b in buckets if b.get("parent") != "libs"]
        assert external, f"the mutation did not fold an external bucket: {[b['id'] for b in buckets]}"
        b = external[0]
        with _page(url + "#v=bucketfold&bkid=" + b["id"]) as page:
            _settle(page)
            seen = page.evaluate(_FOLD_HEAD_JS)
            assert seen["name"] == b["name"] == seen["h1"], seen
            assert seen["title"] == "What is folded here", seen
            assert seen["count"] == f"{len(b['members'])} dependencies", seen
            assert seen["note"].startswith("External systems grouped by purpose,"), seen
            assert not page.js_errors, page.js_errors


def _with_deployment_arrow(m: Any) -> None:
    """Put the component that reaches the store INTO a process, which is what draws a coupling-point
    arrow. The committed fixture places no component in any process, so it draws no arrow at all."""
    store = next(e for e in m["edges"]
                 if any(d["id"] == e["dst"] and d["kind"] == "datastore" for d in m["deps"]))
    for c in m["components"]:
        if c["id"] == store["src"]:
            c["runs_in"] = [m["deployment"][0]["unit"]]


def test_a_deployment_arrow_page_names_its_two_ends() -> None:
    """The same missing `name`, on the one arrow page that is a list instead of a drawing: it opened on a
    pill and a count with nothing saying which two ends the arrow joins. It gets no strip, having no
    picture to head."""
    with _served_map(_with_deployment_arrow) as url:
        view = json.loads(urlopen(url + "api/view").read().decode())
        pairs = list(view.get("deploymentEdges") or {}) + list(view.get("deploymentInfraEdges") or {})
        assert pairs, "the mutation did not draw a Deployment arrow"
        a, b = pairs[0].split(">")
        with _page(url + f"#v=depedge&a={a}&b={b}") as page:
            _settle(page)
            seen = page.evaluate("""() => ({
                name: (document.querySelector('#diagram .page-hero-subject') || {}).textContent || '',
                h1: (document.querySelector('#crumb h1') || {}).textContent || '',
                pill: (document.querySelector('#diagram .ecard-pill') || {}).textContent || '',
                meta: (document.querySelector('#diagram .page-hero-meta') || {}).textContent || '',
                strip: !!document.querySelector('#diaghead .item-sec-strip-stage'),
            })""")
            assert " \u2192 " in seen["name"] and seen["name"] == seen["h1"], seen
            assert seen["pill"] and seen["meta"], f"the kind of link and how many, as before: {seen}"
            assert not seen["strip"], "a list page has no drawing to head"
            assert not page.js_errors, page.js_errors


def test_a_pair_page_offers_its_frames_by_name_not_by_a_floating_magnifier() -> None:
    """Every box on a walk, a Data picture and a Structure picture had already lost its corner
    magnifier — "the icon was the older way of saying so, a control floating in the corner of a box, in
    a language no other screen speaks". The three pair pages kept theirs: two came from the frames
    (bindFrameDrill added one per frame), and the bridge's boxes kept one too, because the two
    picture-family tests each name ONE TAB's drawings and a subsystem crossed with a subdomain is in
    neither. So a reader arriving from a subsystem's own card — which draws no such icon — met a
    gesture that page had dropped.

    A frame's NAME is the door now, underlined on hover, exactly as a box's name is everywhere else."""
    pages = ["#v=edge&a=S1&b=S10", "#v=domedge&a=SD3&b=SD2", "#v=bridge&sid=S13&sd=SD3"]
    with _served() as url, _page(url) as page:
        for hash_ in pages:
            page.goto(url + hash_)
            _settle(page)
            seen = page.evaluate("""() => ({
                icons: document.querySelectorAll('#diagram .action-icon').length,
                frames: document.querySelectorAll('#diagram g.cluster').length,
                doors: document.querySelectorAll('#diagram g.cluster .cluster-label.cyname').length,
            })""")
            assert seen["icons"] == 0, f"no floating control on a pair page: {hash_} {seen}"
            assert seen["frames"] and seen["doors"] == seen["frames"], \
                f"every frame offers itself by name: {hash_} {seen}"
        # …and the name is a door that says so, and opens what it names.
        page.goto(url + "#v=edge&a=S1&b=S10")
        _settle(page)
        lab = page.locator("#diagram g.cluster .cluster-label").first
        deco = ("() => getComputedStyle(document.querySelector('#diagram g.cluster .cluster-label p'))"
                ".textDecorationLine")
        assert page.evaluate(deco) == "none", "resting, a name is plain"
        lab.hover()
        page.wait_for_timeout(250)
        # The underline has to reach the HTML Mermaid puts inside the label's foreignObject: set on the
        # SVG group alone it computes and shows nothing, which is a door with no sign on it.
        assert page.evaluate(deco) == "underline", "hovered, it says it is a door"
        lab.click()
        _settle(page)
        assert page.evaluate("() => location.hash") in ("#v=subsystem&sid=S1", "#v=subsystem&sid=S10"), \
            "a plain click on the name opens that subsystem"
        assert not page.js_errors, page.js_errors


def test_no_arrow_draws_a_magnifier_and_every_drillable_one_keeps_a_door() -> None:
    """The arrow was the LAST place the corner magnifier survived, after every box and every frame had
    let it go, so one drawing taught two languages at once: open a box by its name, open an arrow by a
    control that appears at the pointer. It is gone from every arrow.

    THE DOOR HAD TO SURVIVE IT, and on one arrow it did not: a bridge arrow drawn on a subsystem's own
    card runs from a member COMPONENT to a subdomain frame, so the card — which re-derived its own
    target from the two drawn ends — found no subsystem, drew a plain heading, and left the magnifier
    as the arrow's only visible way in. The binder already knew the page; it hands it over now.

    So this walks EVERY drillable arrow the map draws and demands two things at once: no magnifier
    anywhere, and a door in every one of their cards."""
    views = ["#v=container", "#v=subsystem&sid=S1", "#v=subsystem&sid=S2", "#v=edge&a=S1&b=S10",
             "#v=domain", "#v=domsub&sd=SD1", "#v=bridge&sid=S13&sd=SD3", "#v=deployment"]
    sweep = """() => new Promise(async (resolve) => {
        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
        const seen = new Set(); const out = [];
        for (const h of [...document.querySelectorAll('#diagram .cy-edgehit.drill')]) {
          const r = h.getBoundingClientRect();
          for (const t of ['mousedown', 'click'])
            h.dispatchEvent(new MouseEvent(t, {bubbles: true, detail: 1,
              clientX: (r.left + r.right) / 2, clientY: (r.top + r.bottom) / 2}));
          await sleep(200);
          const title = (document.querySelector('#panel .pane-title h2') || {}).textContent || '';
          if (!title || seen.has(title)) continue;
          seen.add(title);
          out.push({title: title.slice(0, 60),
                    door: !!document.querySelector('#panel .pane-title-link')
                       || !!document.querySelector('#panel .xmore')});
        }
        resolve(out);
      })"""
    with _served() as url, _page(url) as page:
        arrows = 0
        for hash_ in views:
            page.goto(url + hash_)
            _settle(page)
            # Every icon still on the page is anchored to a BOX corner; none belongs to an arrow.
            on_arrow = page.evaluate("""() => {
                const boxes = [...document.querySelectorAll('#diagram g.node')];
                return [...document.querySelectorAll('#diagram .action-icon')].filter((i) => {
                  const r = i.getBoundingClientRect(), cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
                  return !boxes.some((b) => { const q = b.getBoundingClientRect();
                    return Math.hypot(q.left - cx, q.top - cy) < 22; });
                }).length; }""")
            assert on_arrow == 0, f"an arrow still draws a magnifier on {hash_}"
            rows = page.evaluate(sweep)
            arrows += len(rows)
            for r in rows:
                assert r["door"], f"a drillable arrow with no door in its card, on {hash_}: {r}"
        assert arrows > 0, "the sweep found no drillable arrow to check at all"
        assert not page.js_errors, page.js_errors


def test_a_bridge_arrow_opens_the_same_page_by_gesture_and_by_its_card() -> None:
    """Three ways in, one destination — pinned together, because the card's target used to be worked out
    separately from the arrow's and the two could disagree without anything saying so."""
    click = """(alt) => {
        const h = [...document.querySelectorAll('#diagram .cy-edgehit.drill')][0];
        const r = h.getBoundingClientRect();
        for (const t of ['mousedown', 'click'])
          h.dispatchEvent(new MouseEvent(t, Object.assign({bubbles: true,
            clientX: (r.left + r.right) / 2, clientY: (r.top + r.bottom) / 2},
            alt ? {altKey: true} : {detail: 1})));
      }"""
    # S13's card draws exactly one drillable arrow, and it is the shape this test is about: a member
    # COMPONENT to a subdomain frame, where neither drawn end is the subsystem the page opens.
    with _served() as url, _page(url + "#v=subsystem&sid=S13") as page:
        _settle(page)
        assert page.evaluate("() => document.querySelectorAll('#diagram .cy-edgehit.drill').length") == 1
        page.evaluate(click, True)
        _settle(page)
        by_gesture = page.evaluate("() => location.hash")
        assert by_gesture.startswith("#v=bridge"), by_gesture

        page.goto(url + "#v=subsystem&sid=S13")
        _settle(page)
        page.evaluate(click, False)
        page.wait_for_timeout(400)
        link = page.locator("#panel .pane-title-link")
        assert link.count() == 1, "the arrow's card names its door"
        link.click()
        _settle(page)
        assert page.evaluate("() => location.hash") == by_gesture, \
            "the card's title opens exactly where the drill gesture goes"
        assert not page.js_errors, page.js_errors


def test_a_folds_card_and_its_page_say_the_same_sentence() -> None:
    """The sentence was written twice and the two copies drifted. The PAGE was taught the reader's word
    for the tab ('Dependencies', not the code's 'Context') and that a library bucket is not an external
    system; the CARD, one click away on the same screen, went on saying 'External systems grouped by
    purpose' over React and Vite, 'folded out of the Context view'.

    Both read `FOLD_NARRATIVE` now. The card adds the gesture, because from a card you have not drilled
    in yet; the page drops it, because there you have."""
    with _served() as url, _page(url + "#v=libs") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const strip = (document.querySelector('#diaghead .item-sec-note') || {}).textContent || '';
            const box = [...document.querySelectorAll('#diagram g.node')].find((n) => n.__cyId || true);
            return {strip}; }""")
        assert "Dependencies view" in seen["strip"], seen
        assert "Context view" not in seen["strip"], "the reader's word for the tab, not the code's"
        # …and the card for the same fold, opened from the Dependencies view that draws its box.
        page.goto(url + "#v=context")
        _settle(page)
        card = page.evaluate("""() => {
            const el = [...document.querySelectorAll('#diagram g.node')]
              .find((n) => (n.textContent || '').includes('Libraries'));
            if (!el) return null;
            el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
            return new Promise((r) => setTimeout(() =>
              r((document.querySelector('#panel .empty') || {}).textContent || ''), 700)); }""")
        if card:
            assert "Context view" not in card, f"the card said the code's word for the tab: {card!r}"
            assert "folded out of the Dependencies view" in card, card
            assert "drill in" in card, "a card is offered BEFORE you drill, so it keeps the gesture"
        assert not page.js_errors, page.js_errors


def test_a_pair_page_refuses_a_link_whose_ends_are_the_wrong_kind() -> None:
    """The guard checked that both ids EXIST, not that they are what the page is about — so a stale or
    hand-typed link printed a confident wrong word: `#v=domedge` naming two RECORDS announced them as
    `Subdomain pair: Organization → Membership`. These pages drew no words at all before this change,
    so a wrong one is worse than what it replaced: the guard has to be as narrow as the sentence."""
    wrong = ["#v=domedge&a=E1&b=E2",          # two records, not two data areas
             "#v=bridge&sid=S1&sd=S3",        # two subsystems, not a subsystem and a data area
             "#v=edge&a=SD1&b=SD5"]           # two data areas, not two subsystems
    right = ["#v=edge&a=S1&b=S10", "#v=domedge&a=SD3&b=SD2", "#v=bridge&sid=S13&sd=SD3"]
    read = """() => ({
        kind: (document.querySelector('.page-hero-kind') || {}).textContent || '',
        name: (document.querySelector('.page-hero-subject') || {}).textContent || '',
      })"""
    with _served() as url, _page(url) as page:
        for hash_ in wrong:
            page.goto(url + hash_)
            _settle(page)
            seen = page.evaluate(read)
            assert not seen["kind"] and not seen["name"], \
                f"{hash_} named a pair it is not: {seen}"
        for hash_ in right:
            page.goto(url + hash_)
            _settle(page)
            seen = page.evaluate(read)
            assert seen["kind"] and " → " in seen["name"], f"{hash_} lost its header: {seen}"
        assert not page.js_errors, page.js_errors


def test_the_faded_boxes_note_waits_for_a_faded_box() -> None:
    """The note explains the fade to a first-time reader, and it is shown ONCE in a reader's lifetime —
    the flag is set the first time it fires. It used to fire on every focus, faded or not, and a focus
    often fades nothing: on a pair page drawn as two boxes and one arrow, selecting that arrow keeps
    both boxes lit and the note still announced "faded boxes are just unrelated" over a page where none
    were. So the one explanation could be spent on the one screen that had nothing to explain.

    Each `_page` is a fresh browser, which is a fresh lifetime — so the two halves cannot borrow each
    other's flag."""
    read = ("() => ({dim: document.querySelectorAll('#diagram .dim').length,"
            " note: document.querySelectorAll('#dimnote').length})")
    # NOTHING FADES: selecting the one arrow on a pair page keeps both of its boxes lit.
    # S1>S3 draws exactly two boxes and one arrow, so its focus keeps both lit and fades nothing.
    with _served() as url, _page(url + "#v=edge&a=S1&b=S3") as page:
        _settle(page)
        page.evaluate("""() => { const h = [...document.querySelectorAll('#diagram .cy-edgehit')][0];
            if (!h) return; const r = h.getBoundingClientRect();
            for (const t of ['mousedown', 'click'])
              h.dispatchEvent(new MouseEvent(t, {bubbles: true, detail: 1,
                clientX: (r.left + r.right) / 2, clientY: (r.top + r.bottom) / 2})); }""")
        page.wait_for_timeout(600)
        seen = page.evaluate(read)
        assert seen["dim"] == 0, f"this page is the one where a focus fades nothing: {seen}"
        assert seen["note"] == 0, f"…so the note has nothing to explain and stays silent: {seen}"
        assert not page.js_errors, page.js_errors

    # A REAL FADE: the note still appears, which is the half that must not be lost.
    with _served() as url, _page(url + "#v=container") as page:
        _settle(page)
        got = None
        for i in range(8):
            box = page.evaluate(f"""() => {{ const x = [...document.querySelectorAll('#diagram g.node')][{i}];
                if (!x) return null; const r = x.getBoundingClientRect();
                return [(r.left + r.right) / 2, (r.top + r.bottom) / 2]; }}""")
            if not box:
                break
            page.mouse.move(box[0] - 25, box[1] - 25)
            page.wait_for_timeout(80)
            page.mouse.click(box[0], box[1])
            page.wait_for_timeout(450)
            seen = page.evaluate(read)
            if seen["dim"]:
                got = seen
                break
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        assert got, "no selection on this view faded a box, so the test proved nothing"
        assert got["note"] == 1, f"a real fade still gets its one explanation: {got}"
        assert not page.js_errors, page.js_errors


def _with_rules(m: Any) -> None:
    """A decision area holding three rules, anchored in a file a component claims. The committed
    fixture carries no rules at all, so the Rules tab does not even appear on it."""
    f = "backend/src/mcpolis/domain/services/policy_engine.py"
    m["components"][0]["files"] = [f]
    m["blocks"] = [{"id": "BLK1", "name": "Who may call which tool",
                    "purpose": "How a team's permission sets decide whether one tool call goes out.",
                    "parent": None, "happy_path": "", "stakes": [], "story": None, "owners": None,
                    "source": None, "confidence": "verified", "tech": "", "tech_source": ""}]
    m["rules"] = [
        {"id": f"BR{i}", "name": name, "statement": stmt, "block": "BLK1", "access": True,
         "risk": "A permissive fallback would open every shared server.", "confidence": "verified",
         "sites": [{"where": f"{f}:{100 + i}", "why": "refuses the call", "no_call_site": False}]}
        for i, (name, stmt) in enumerate([
            ("No role, no access", "A caller whose role cannot be found is refused every tool."),
            ("Admin comes from a flag", "Any role marked as an admin role grants admin power."),
            ("Argument values gate the call", "A role may refuse a call whose argument is forbidden."),
        ], start=1)]


def test_a_rule_wears_a_scale_and_its_area_a_scroll() -> None:
    """A business rule and a decision area were the only element kinds with nothing in the figure
    column: outside the mark vocabulary, so no glyph, and outside the colour table, so the neutral
    slate every unknown kind falls back to.

    Both marks are Lucide paths (ISC), vendored — the viewer loads no icon library. They are the one
    pair here that is NOT "the member drawn twice": a scroll is not made of scales, so the colour is
    what carries the family resemblance instead. That was raised against a doubled diamond that does
    obey the rule, and chosen anyway.

    Pinned: the two marks are DIFFERENT from each other, and each is the same mark wherever its kind
    appears — a card, a page hero, the head of the section that holds it. A count of paths is not
    pinned; that is the icon's business and would break on any redraw."""
    marks = ("() => [...document.querySelectorAll('#diagram .ibox-gly')]"
             ".map((s) => ({stroke: s.getAttribute('stroke'),"
             " d: [...s.querySelectorAll('path')].map((q) => q.getAttribute('d')).join('|')}))")
    with _served_map(_with_rules) as url, _page(url + "#v=rules") as page:
        _settle(page)
        seen = page.evaluate(marks)
        assert seen, "the decision areas draw no mark at all"
        area_d = {m["d"] for m in seen}
        assert len(area_d) == 1, f"every card here is an area, so every mark is the same: {seen}"
        assert {m["stroke"] for m in seen} == {"#be123c"}, f"one colour, its own: {seen}"
        assert not page.js_errors, page.js_errors

    with _served_map(_with_rules) as url, _page(url + "#v=rules&blk=BLK1") as page:
        _settle(page)
        seen = page.evaluate("""() => {
            const d = (el) => el ? [...el.querySelectorAll('path')]
              .map((q) => q.getAttribute('d')).join('|') : '';
            return {
              hero: d(document.querySelector('#diagram .page-hero-glyph .ibox-gly')),
              strip: d(document.querySelector('#diagram .item-sec-title .ibox-gly')),
              cards: [...document.querySelectorAll('#diagram .item-sec-body .ibox-gly')].map(d),
            }; }""")
        assert seen["hero"] and seen["strip"] and seen["cards"], f"a mark is missing: {seen}"
        # The AREA's own mark leads the page; the section under it is headed by the mark of what it
        # HOLDS, which is the same mark every rule card in it wears.
        assert seen["hero"] != seen["strip"], "the area and the rule must not share one mark"
        assert set(seen["cards"]) == {seen["strip"]}, \
            f"the section head and its rule cards wear one mark: {seen}"
        assert not page.js_errors, page.js_errors

    with _served_map(_with_rules) as url, _page(url + "#v=rule&br=BR1") as page:
        _settle(page)
        d = page.evaluate("""() => { const el = document.querySelector('#diagram .page-hero-glyph .ibox-gly');
            return el ? [...el.querySelectorAll('path')].map((q) => q.getAttribute('d')).join('|') : ''; }""")
        assert d, "a rule's own page leads with no mark"
        assert not page.js_errors, page.js_errors


def _with_specified_rules(m: Any) -> None:
    """Four decision areas, three of them SPECIFIED UNDER a feature — the shape the Rules board cuts
    its sections by. One area names TWO features (drawn under both), one names none (the trailing
    section). The features chosen straddle the fixture's story column: `Audit & oversight` is CAP6 and
    sits BEFORE `Secrets & variables`, CAP5, so map order and story order disagree and the test can
    tell which one the board used."""
    _with_rules(m)
    base = m["blocks"][0]

    def area(bid: str, name: str, under: list[str]) -> dict:
        return dict(base, id=bid, name=name, purpose=f"What {name[0].lower()}{name[1:]} settles.",
                    specified_under=list(under) or None)

    m["blocks"] = [
        area("BLK1", "Who may call which tool", ["CAP3"]),
        area("BLK2", "What gets recorded", ["CAP6"]),
        area("BLK3", "Protecting stored secrets", ["CAP5", "CAP2"]),
        area("BLK4", "Plan caps", []),
    ]


#: The Rules board as the reader sees it: every feature card in page order with its door, its mark
#: and the area cards inside it. Shared by the grouped test and the ungrouped one, so "no cards" is
#: read by the same probe that reads the cards rather than by a second one that could drift.
_RULES_BOARD_JS = """() => {
  const wrap = document.querySelector('#diagram');
  const secs = [...wrap.querySelectorAll('.item-sec[id^=\\"itemsec-feat-\\"]')].map((sec) => {
    const head = sec.querySelector('.item-sec-title');
    const door = head.querySelector('.item-sec-door');
    return {
      title: (door || head).textContent.trim(),
      fid: door ? door.getAttribute('data-gofeat') : '',
      mark: !!head.querySelector('svg'),
      counts: head.querySelectorAll('.count-pill').length,
      areas: [...sec.querySelectorAll('.item-sec-body .ecard')].map((c) => ({
        name: (c.querySelector('.ibox-name') || {}).textContent || '',
        also: [...c.querySelectorAll('.ecard-extra .item-pill')]
                .map((b) => b.getAttribute('data-item')),
      })),
    };
  });
  return { secs, grids: wrap.querySelectorAll('.ecard-grid').length,
           cards: wrap.querySelectorAll('.ecard').length,
           typePills: wrap.querySelectorAll('.ecard .ecard-type').length,
           footDoors: wrap.querySelectorAll('.ecard-extra .item-pill-door').length };
}"""


def test_the_rules_board_cuts_its_areas_by_the_feature_they_are_specified_under() -> None:
    """Eleven decision areas in one grid is a bulk list: nothing says which to read first, and nothing
    gives two neighbours a shared context. The board gives each feature a CARD of its own, holding the
    areas specified under it, in the order the Features page already reads.

    Six things are pinned, and each is a way the cut could go wrong:
      * the feature cards follow the STORY COLUMN, not the map's own order — CAP6 is declared after
        CAP5 and must be drawn before it;
      * an area under two features is drawn under BOTH, and each copy names the OTHER feature, so
        neither copy depends on which one the reader met first;
      * an area under no feature lands in one trailing card rather than vanishing;
      * every feature card's name is a DOOR to that feature's page, and wears the feature's own mark;
      * no card counts its areas — the cards under the name are the count;
      * no area card says `decision area` — every card on this page is one."""
    with _served_map(_with_specified_rules) as url, _page(url + "#v=rules") as page:
        _settle(page)
        board = page.evaluate(_RULES_BOARD_JS)
        assert [s["title"] for s in board["secs"]] == [
            "Upstream MCPs", "Access control", "Audit & oversight", "Secrets & variables",
            "Not specified under any feature"], f"wrong cut or wrong order: {board['secs']}"
        assert [s["fid"] for s in board["secs"]] == ["CAP2", "CAP3", "CAP6", "CAP5", ""], \
            f"every feature card is a door, the trailing one is not: {board['secs']}"
        assert [s["mark"] for s in board["secs"]] == [True, True, True, True, False], \
            f"a feature card wears the feature's mark, the trailing one names none: {board['secs']}"
        assert [s["counts"] for s in board["secs"]] == [0, 0, 0, 0, 0], \
            f"the cards under the name are the count: {board['secs']}"
        by = {s["title"]: s for s in board["secs"]}
        # The shared area, drawn twice, each copy pointing at the other feature.
        assert by["Upstream MCPs"]["areas"] == [
            {"name": "Protecting stored secrets", "also": ["CAP5"]}], by["Upstream MCPs"]
        assert by["Secrets & variables"]["areas"] == [
            {"name": "Protecting stored secrets", "also": ["CAP2"]}], by["Secrets & variables"]
        # An area under ONE feature names no other place, and the featureless one still gets a card.
        assert by["Access control"]["areas"] == [
            {"name": "Who may call which tool", "also": []}], by["Access control"]
        assert [a["name"] for a in by["Not specified under any feature"]["areas"]] == ["Plan caps"]
        assert board["cards"] == 5, f"four areas, one of them twice: {board}"
        assert board["typePills"] == 0, "every card here is a decision area; saying so 5 times is noise"
        # EVERY item pill acts. Both `Also under` pills open the feature they name.
        assert board["footDoors"] == 2, f"the Also under pills are doors: {board}"
        assert not page.js_errors, page.js_errors


def test_a_feature_card_head_is_a_door_to_the_feature_it_names() -> None:
    """The card names a feature, and that feature has a page. A heading that reads like a link and goes
    nowhere teaches a reader to stop trying the ones that work."""
    with _served_map(_with_specified_rules) as url, _page(url + "#v=rules") as page:
        _settle(page)
        page.click("#diagram .item-sec-title .item-sec-door[data-gofeat='CAP6']")
        _settle(page)
        assert "v=capability" in page.url and "cap=CAP6" in page.url, page.url
        assert not page.js_errors, page.js_errors


def test_a_map_that_names_no_feature_keeps_one_flat_grid_of_areas() -> None:
    """Two of the three live maps answer `specified_under` nowhere. There the board has no cut to
    make, and ONE card headed "not specified under any feature" holding every area would read as
    an accusation about the map rather than as a grouping. So the page falls back to the plain grid
    it drew before the cut existed."""
    with _served_map(_with_rules) as url, _page(url + "#v=rules") as page:
        _settle(page)
        board = page.evaluate(_RULES_BOARD_JS)
        assert board["secs"] == [], f"nothing to cut by, so no feature cards: {board}"
        assert board["grids"] == 1 and board["cards"] == 1, f"one grid, every area in it: {board}"
        assert not page.js_errors, page.js_errors



# ── a link from `coyomap url` lands on the element it names ──────────────────────────────────────
# The grammar in url.py mirrors two functions of this file's subject (`drillInto`, `selectTargetFor`),
# and nothing but a browser can tell whether the mirror is true: a link that opens the right SCREEN
# with nothing selected is the likely failure, and it looks fine from the outside. So every kind, in
# both gestures, is opened cold here — a fresh page on the pasted address, the way a chat's reader
# opens it — and the element named is looked for on the screen, by its own id.

def _every_kind() -> Any:
    """Every element kind on one map: the three-surfaces map (I1-I3, SF1, EP1) plus the rules."""
    three = _three_ways_to_reach_a_surface()

    def mutate(m: dict) -> None:
        three(m)
        _with_rules(m)
    return mutate


def _every_kind_model() -> Any:
    from coyomap.model import load_model
    m = json.loads(_FIXTURE_MAP.read_text(encoding="utf-8"))
    _every_kind()(m)
    return load_model(json.dumps(m))


#: (element id, in context?, how the screen is checked, what it must show). `crumb`: the trail's
#: last item names the element AND the address restates the element (the page adopted it — a
#: fallback screen would show a trail too). `css`: the element's own box wears the selection.
#: `node`: the ONE selected box on the diagram is this element's — read the way `idOf` reads a box,
#: since a flowchart box carries `cy-<id>` and a class-diagram box (an entity) only its mermaid id.
_LINK_CASES: list[tuple[str, bool, str, str]] = [
    ("CAP1", False, "crumb", "Organizations & teams"),
    ("UC1", False, "crumb", "Sign up and create an organization"),
    ("R1", False, "crumb", "Org creator"),
    ("S1", False, "crumb", "App bootstrap & runtime wiring"),
    ("C1", False, "crumb", "App factory / wiring spine"),
    ("D1", False, "crumb", "MongoDB"),
    ("SD1", False, "crumb", "Tenancy & access policy"),
    ("E1", False, "crumb", "Organization"),
    ("I1", False, "crumb", "The dashboard"),
    ("SF1", False, "crumb", "Sign in with Google"),
    ("BLK1", False, "crumb", "Who may call which tool"),
    ("BR1", False, "crumb", "No role, no access"),
    ("HP12", False, "css", ".flow-step[data-step='HP12'].ibox-picked"),
    ("EP1", False, "css", "tr.pickbox[data-ep='EP1'].ibox-picked"),
    ("CAP1", True, "css", ".story-card.story-selected[data-sfeat='CAP1']"),
    ("R1", True, "css", ".story-card.story-selected[data-sactor='R1']"),
    ("C1", True, "node", "C1"),
    ("S1", True, "node", "S1"),
    ("S13", True, "node", "S13"),
    ("SD1", True, "node", "SD1"),
    ("E1", True, "node", "E1"),
    ("D1", True, "node", "D1"),
    ("D14", True, "node", "D14"),
    ("I1", True, "css", ".ifd-box.ifd-picked[data-iface='I1']"),
]


#: The ids of the selected boxes on the diagram, read the way viewer.js's `idOf` reads a box.
_SELECTED_NODE_IDS = """[...document.querySelectorAll('#diagram g.node.is-selected')].map((el) => {
    const cls = [...el.classList].find((c) => c.startsWith('cy-'));
    if (cls) return cls.slice(3);
    if (el.getAttribute('data-id')) return el.getAttribute('data-id');
    const m = (el.id || '').match(/(?:^|-)((?:UC|HP|SD|C|D|E|I|S)\\d+)(?:-|$)/);
    return m ? m[1] : null; })"""


@pytest.mark.parametrize("eid,context,how,want", _LINK_CASES,
                         ids=[f"{e}{'-context' if c else ''}" for e, c, _h, _w in _LINK_CASES])
def test_a_link_from_coyomap_url_lands_on_the_element_it_names(eid: str, context: bool, how: str,
                                                              want: str) -> None:
    from coyomap.viewer.url import link_for
    link = link_for(_every_kind_model(), eid, context)
    assert link is not None, eid
    with _served_map(_every_kind()) as url, _page(url + "#" + link.fragment) as page:
        _settle(page)
        if how == "css":
            page.wait_for_selector(want, state="attached", timeout=8000)
            assert page.evaluate(f"() => document.querySelectorAll({want!r}).length") == 1, want
        elif how == "node":
            page.wait_for_function(_SELECTED_NODE_IDS + ".length > 0", timeout=8000)
            assert page.evaluate(_SELECTED_NODE_IDS) == [want], page.evaluate(_SELECTED_NODE_IDS)
        else:
            crumb = _crumb(page)
            assert want in crumb, f"{eid}: the trail does not name it: {crumb!r}"
            assert "Not in this map" not in crumb, crumb
            # The page RESTATED the element in the address — the pair that names it survived the
            # render, so this is that element's screen and not a fallback that happens to mention it.
            key, value = [p for p in link.fragment.split("&") if not p.startswith("v=")][0].split("=", 1)
            assert f"{key}={value}" in page.evaluate("() => location.hash"), page.evaluate(
                "() => location.hash")
        assert not page.js_errors, page.js_errors


def test_an_entry_point_link_rings_its_row_and_keeps_it_in_the_address() -> None:
    """The System tab could open the table of an entry point's kind and point at nothing. Now the
    row is a picked box like a step on the walk: lit on arrival, scrolled into view, and restated in
    the address so the copied link and a reload come back to it."""
    link_fragment = None
    from coyomap.viewer.url import link_for
    link = link_for(_every_kind_model(), "EP1")
    assert link is not None
    link_fragment = link.fragment
    with _served_map(_every_kind()) as url, _page(url + "#" + link_fragment) as page:
        _settle(page)
        page.wait_for_selector("tr.pickbox[data-ep='EP1'].ibox-picked", state="attached", timeout=8000)
        seen = page.evaluate("""() => {
            const row = document.querySelector("tr.pickbox[data-ep='EP1']");
            const r = row.getBoundingClientRect();
            const bar = getComputedStyle(row.querySelector('td')).boxShadow;
            return { picked: row.classList.contains('ibox-picked'),
                     onScreen: r.top >= 0 && r.bottom <= window.innerHeight,
                     bar: bar !== 'none', hash: location.hash,
                     others: document.querySelectorAll('tr.pickbox.ibox-picked').length };
        }""")
        assert seen["picked"] and seen["onScreen"] and seen["bar"], seen
        assert seen["others"] == 1, seen
        assert "sel=ep%3AEP1" in seen["hash"], seen
        page.reload()
        page.wait_for_selector("tr.pickbox[data-ep='EP1'].ibox-picked", state="attached", timeout=8000)
        assert not page.js_errors, page.js_errors


# ── the Overview tab: the goal as paragraphs, held to a readable width ──────────────────────────

_VIEWER_CSS = Path(__file__).resolve().parent.parent / "tools" / "coyomap" / "viewer" / "viewer.css"


def _three_long_paragraphs(m: dict) -> None:
    """About 65 words a paragraph: long enough that the full column breaks 80 characters a line."""
    m["goal"] = (
        "Alpha puts a team's tool servers behind one address, so every person on the team reaches the "
        "same servers through one place instead of wiring each server into each of their own clients by "
        "hand, with credentials copied around between machines and no record kept of what was called by "
        "whom and when.\n\n"
        "An admin mounts each server once, either a remote one reached at a web address or a command "
        "style one that Alpha runs for the team inside an isolated sandbox, and then writes roles that "
        "decide which servers, which tools and which tool arguments each person on the team may use "
        "from their own client.\n\n"
        "A teammate points one AI client at the team's single address, signs in with the team account, "
        "and sees exactly the tools their role allows, while software with no browser presents a "
        "revocable token instead and gets the same treatment, and every call and every connection is "
        "recorded for the admin to read later.")


_MEASURE = """() => {
  const el = document.querySelector('.view-lead-body');
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const tops = new Set(); let chars = 0; let node;
  while ((node = walker.nextNode())) {        // TEXT rects only: a <p>'s own box would count as a line
    if (!node.textContent.trim()) continue;
    chars += node.textContent.length;
    const r = document.createRange(); r.selectNodeContents(node);
    for (const x of r.getClientRects()) tops.add(Math.round(x.top));
  }
  return { width: el.getBoundingClientRect().width, lines: tops.size, chars,
           paragraphs: el.querySelectorAll('p').length };
}"""


def test_the_overview_draws_the_goal_as_its_paragraphs_at_a_readable_width() -> None:
    """A goal written as three paragraphs (method.md, T0 Goal) used to render as ONE block: HTML
    collapses the blank lines. And at full column width a 1440px screen ran 137 characters a line,
    twice what body text is readable at, which was the first reason the text read as a block.

    The second half proves the first: the same page served with the width cap stripped from the
    stylesheet must break 80 characters a line, or the assertion above would pass for any CSS."""
    with _served_map(_three_long_paragraphs) as base:
        with _page(base + "#v=overview") as page:
            page.set_viewport_size({"width": 1440, "height": 900})
            _settle(page)
            held = page.evaluate(_MEASURE)
            assert held["paragraphs"] == 3, held
            assert held["width"] < 700 and held["chars"] / held["lines"] <= 80, held
            assert page.js_errors == []
        css = _VIEWER_CSS.read_text(encoding="utf-8")
        cap = ".overview-wrap > .item-sec { max-width: 660px; }"
        assert css.count(cap) == 1, "the overview column's cap moved — update this test"
        with _page(base + "#v=overview", stylesheet=css.replace(cap, "")) as page:
            page.set_viewport_size({"width": 1440, "height": 900})
            _settle(page)
            loose = page.evaluate(_MEASURE)
            assert loose["width"] > 900 and loose["chars"] / loose["lines"] > 80, loose


def test_a_goal_with_no_blank_line_still_draws_as_one_run_of_text() -> None:
    assert "\n\n" not in json.loads(_FIXTURE_MAP.read_text())["goal"], "the fixture goal grew paragraphs"
    with _served() as base, _page(base + "#v=overview") as page:
        _settle(page)
        assert page.evaluate("() => document.querySelectorAll('.view-lead-body p').length") == 0
        assert page.evaluate("() => document.querySelector('.view-lead-body').textContent.length") > 100
        assert page.js_errors == []


def _component_with_two_paragraph_notes(m: dict) -> None:
    m["components"][0]["extra"] = {"Notes": "First note, on its own.\n\nSecond note, on its own."}


def test_a_detail_row_holding_blank_lines_draws_paragraphs_too() -> None:
    """The same helper serves the element page's rows, so a field an author breaks into paragraphs
    reads as paragraphs there as well — checked on screen, not in the source."""
    with _served_map(_component_with_two_paragraph_notes) as base, \
            _page(base + "#v=element&id=C1") as page:
        _settle(page)
        got = page.evaluate("() => Array.from(document.querySelectorAll('dd p.prose-para'))"
                            ".map((p) => p.textContent.trim())")
        assert got == ["First note, on its own.", "Second note, on its own."]
        assert page.js_errors == []



def test_a_tab_left_below_its_top_wears_the_head_path_chevron_and_no_label_moves() -> None:
    """A tab you are NOT on that would reopen a page below its top says so, with the › the page head
    showed while you were inside — and says so OUT OF THE FLOW: every label and every tab box sits
    where it sat before the mark came. The lit tab wears none, because the head's path is that mark;
    a tab left at its overview wears none, because it reopens the overview."""
    labels = """() => [...document.querySelectorAll('button[data-view]')].filter((b) => !b.hidden)
        .map((b) => { const r = document.createRange(); r.selectNodeContents(b);
                      const t = r.getBoundingClientRect(); const x = b.getBoundingClientRect();
                      return [b.dataset.view, Math.round(t.left * 10), Math.round(t.right * 10),
                              Math.round(x.left * 10), Math.round(x.right * 10)]; })"""
    marks = """() => [...document.querySelectorAll('button[data-view]')].filter((b) => !b.hidden)
        .map((b) => [b.dataset.view, b.classList.contains('held'),
                     getComputedStyle(b, '::after').content, b.title])"""
    with _served() as url, _page(url + "#v=capability&cap=CAP1") as page:
        _settle(page)
        before = page.evaluate(labels)
        assert [m[0] for m in page.evaluate(marks) if m[1]] == [], "nothing is held before a tab is left"
        page.evaluate("() => document.querySelector('button[data-view=\"domain\"]').click()")
        _settle(page)
        assert page.evaluate(labels) == before, "the mark moved a label or widened a tab"
        got = {m[0]: m[1:] for m in page.evaluate(marks)}
        assert got["usecases"][0] is True and got["usecases"][1] == '"›"', got["usecases"]
        assert got["usecases"][2].startswith("Reopens at "), got["usecases"]
        assert [v for v, m in got.items() if m[0]] == ["usecases"], got
        # back to Features: it reopens the feature, and the lit tab wears no mark of its own
        page.evaluate("() => document.querySelector('button[data-view=\"usecases\"]').click()")
        _settle(page)
        assert "cap=CAP1" in page.evaluate("() => location.hash")
        got = {m[0]: m[1:] for m in page.evaluate(marks)}
        assert got["usecases"][0] is False and got["usecases"][2] == "Back to Features", got["usecases"]
        # the lit tab again resets it to its overview; leave once more: nothing below the top, no mark
        page.evaluate("() => document.querySelector('button[data-view=\"usecases\"]').click()")
        _settle(page)
        page.evaluate("() => document.querySelector('button[data-view=\"domain\"]').click()")
        _settle(page)
        assert [m[0] for m in page.evaluate(marks) if m[1]] == [], "a tab at its overview holds nothing"
        assert page.evaluate(labels) == before
        assert page.js_errors == []


# ── Ownership: backed, answered, unanswered, and shared-with-nobody-reaching ─────────────────────

#: The reason two areas share, on ONE recorded line. Every recorded reason that reaches a box on the
#: three live maps that record anything rides a multi-key line (12 of 12) — that form is why the
#: record format exists, so an author writes a shared reason once instead of seventeen times. A
#: fixture with only single-key lines leaves the path production actually uses uncovered.
_SHARED_REASON = "the rows are written by a discovery loop that no use case narrates, and the walk " \
                 "that causes them narrates the connect rather than the write"


def make_owner_states_map(m: dict) -> None:
    """One data area in each state the page has to tell apart, on one screen.

      SD1 `Tenancy & access policy`  BACKED      owned by CAP1, and a step of CAP1 reaches a record.
      SD4 `Tool catalog`             ANSWERED    owned by CAP4, nothing reaches it, reason RECORDED.
      SD5 `Audit & events`           ANSWERED    owned by CAP6, same — through the SECOND key of the
                                                 same recorded line, which is the form live maps use.
      SD3 `Credentials & secrets`    UNANSWERED  owned by CAP5, nothing reaches it, nothing recorded.
      SD2 `Upstream & transport`     SHARED, and EVERY owner blind — the sibling that drew no mark at
                                                 all until the gap stopped being asked only of an
                                                 area with exactly one owner (mcpolis SD3, live).

    The committed fixture draws no data column at all (no entity in it is SAVED), so every one of
    these has to be built."""
    subs = {g["id"]: g for g in m["subdomains"]}
    subs["SD1"]["owners"] = ["CAP1"]
    subs["SD4"]["owners"] = ["CAP4"]
    subs["SD5"]["owners"] = ["CAP6"]
    subs["SD3"]["owners"] = ["CAP5"]
    subs["SD2"]["owners"] = ["CAP2", "CAP3"]
    ents = {e["id"]: e for e in m["entities"]}
    for eid in ("E1", "E26", "E35", "E16", "E10"):
        ents[eid]["store"] = {"dep": None, "container": "rows", "mode": "collection", "notes": ""}
    flow = next(f for f in m["flows"] if f["uc"] == "UC1")     # UC1 belongs to CAP1
    step = dict(flow["steps"][-1])
    step.update({"n": len(flow["steps"]) + 1, "src": "C15", "dst": "E1",
                 "phrase": "writes the organization row"})
    flow["steps"].append(step)
    # Nothing is added for E26, E35, E16 or E10: no flow of their owners ever reaches them.
    m["extras"] = list(m.get("extras") or []) + [
        {"heading": "Data owner exceptions", "body": f"SD4, SD5: {_SHARED_REASON}"}]


def _owner_screen(page: Any) -> dict:
    """Everything the states put on screen, MEASURED rather than read off a class list.

    The CONTRAST is computed from the wire's own stroke blended with its opacity, because a rule that
    lowers opacity can take a line below the floor of visible while every class assertion still
    passes — which is how the first version shipped at 1.25:1, fainter than the ordinary wire it was
    meant to stand out from. `footClipped` is the same kind of guard for the words: a clamped
    paragraph must keep the whole sentence in the DOM."""
    return page.evaluate("""() => {
        const lum = (rgb) => { const p = rgb.match(/\\d+/g).map(Number);
          const f = (v) => { v /= 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
          return 0.2126 * f(p[0]) + 0.7152 * f(p[1]) + 0.0722 * f(p[2]); };
        const blend = (rgb, op) => 'rgb(' + rgb.match(/\\d+/g)
            .map(v => Math.round(Number(v) * op + 255 * (1 - op))).join(', ') + ')';
        const wire = (sd) => {
          const p = document.querySelector(`path.story-own[data-sarea="${sd}"]`);
          if (!p) return null;
          const cs = getComputedStyle(p);
          const eff = blend(cs.stroke, Number(cs.opacity));
          return { dash: cs.strokeDasharray, gap: p.classList.contains('story-own-gap'),
                   contrast: Math.round((1.05 / (lum(eff) + 0.05)) * 100) / 100 };
        };
        const box = (sd) => {
          const b = document.querySelector(`.story-area[data-sarea="${sd}"]`);
          const f = b.querySelector('.story-shared, .story-gap');
          return { owned: b.classList.contains('story-area-owned'),
                   gap: b.classList.contains('story-area-gap'),
                   open: b.classList.contains('story-area-gap-open'),
                   shared: b.classList.contains('story-area-shared'),
                   border: getComputedStyle(b).borderColor,
                   foot: f ? f.textContent : '',
                   footClipped: f ? f.scrollHeight > f.clientHeight + 1 : false };
        };
        const ids = ['SD1', 'SD4', 'SD5', 'SD3', 'SD2'];
        return { wires: Object.fromEntries(ids.map(i => [i, wire(i)])),
                 boxes: Object.fromEntries(ids.map(i => [i, box(i)])),
                 pageText: document.body.innerText };
    }""")


def test_a_claim_no_step_reaches_is_marked_whether_or_not_the_map_records_why() -> None:
    """All the ownership wires used to arrive in the same ink — 12 of the 30 across the four live
    maps are claims the map cannot back, and a reader had no way to tell which.

    A RECORDED EXCEPTION IS STILL A GAP. It silences `validate`, whose reader is the build lead; the
    person reading this page never sees the record. Both gap states take the same mark and the WORDS
    say which — mark only the unrecorded ones and the page goes back to identical wires, because
    every gap on every live map today is a recorded one (12 of 12)."""
    with _served_map(make_owner_states_map) as url, _page(url + "#v=features") as page:
        _settle(page)
        w = _owner_screen(page)["wires"]
        assert w["SD1"]["dash"] == "none" and not w["SD1"]["gap"], w["SD1"]
        for sd in ("SD4", "SD5", "SD3"):
            assert w[sd]["gap"] and w[sd]["dash"] != "none", (sd, w[sd])
        # ONE mark for every gap: no dash code for the reader to learn.
        assert w["SD4"]["dash"] == w["SD3"]["dash"], w
        assert w["SD2"] is None, "a shared area draws no ownership wire, recorded or not"
        assert not page.js_errors, page.js_errors


def test_the_line_carrying_the_exception_is_not_the_faintest_thing_on_the_page() -> None:
    """Measured, not asserted by class. The first version dashed the wire AND dropped it to opacity
    .45 — rgb(228,230,238) on white, 1.25:1, BELOW the ordinary wire's own 1.45:1. Every class
    assertion passed and the line carrying the page's one exception was the hardest thing to see."""
    with _served_map(make_owner_states_map) as url, _page(url + "#v=features") as page:
        _settle(page)
        w = _owner_screen(page)["wires"]
        for sd in ("SD4", "SD3"):
            assert w[sd]["contrast"] >= w["SD1"]["contrast"], (sd, w[sd], w["SD1"])
            assert w[sd]["contrast"] >= 2.0, (sd, w[sd]["contrast"])
        assert not page.js_errors, page.js_errors


def test_the_settled_owned_mark_actually_draws() -> None:
    """`.story-area-owned { border-color }` sat ~900 lines above `.ibox { border: … }` at the SAME
    specificity, and `.ibox` wins by order and resets the colour with a shorthand. The rule had never
    once applied: an owned box computed rgb(220,223,240), byte-identical to every other box. Nothing
    caught it because the test asserted the CLASS was on the element, never that it drew."""
    with _served_map(make_owner_states_map) as url, _page(url + "#v=features") as page:
        _settle(page)
        b = _owner_screen(page)["boxes"]
        assert b["SD1"]["owned"] and not b["SD1"]["gap"], b["SD1"]
        assert b["SD1"]["border"] != b["SD4"]["border"], b
        assert b["SD4"]["border"] == b["SD3"]["border"], \
            "a gap keeps the plain border whether or not it is recorded"
        assert not page.js_errors, page.js_errors


def test_a_gap_says_who_looked_and_the_whole_of_what_they_said() -> None:
    """The reader gets the mark AND the reason: the author's own recorded sentence, WHOLE.

    It was cut to its first sentence, and measured against every real recorded reason on the four
    live maps that cut lost the load-bearing half on 7 of 12 boxes. There is no other complete copy
    in the product — a record's area page carries neither the reason nor the gap — so the string is
    never cut; `.story-gap` clamps the DRAWN height and the sentence stays in the DOM.

    SD5 gets its reason from the SECOND key of the recorded line, which is the form every live
    recorded reason uses."""
    with _served_map(make_owner_states_map) as url, _page(url + "#v=features") as page:
        _settle(page)
        b = _owner_screen(page)["boxes"]
        assert b["SD1"]["foot"] == "", b["SD1"]
        for sd in ("SD4", "SD5"):
            foot = b[sd]["foot"]
            assert foot.startswith("No step of it reaches this data."), (sd, foot)
            assert _SHARED_REASON in foot, (sd, foot)      # WHOLE, not a first sentence
            assert not b[sd]["footClipped"], (sd, "the sentence must stay in the DOM")
            assert b[sd]["gap"] and not b[sd]["open"], (sd, b[sd])
        un = b["SD3"]["foot"]
        assert un == "No step of it reaches this data. The map does not say why.", un
        assert b["SD3"]["open"], b["SD3"]
        assert not page.js_errors, page.js_errors


def test_a_shared_area_no_owner_reaches_is_marked_too() -> None:
    """The same defect one branch over. The gap used to be asked only of an area with exactly ONE
    owner, so a SHARED area whose owners are ALL blind — mcpolis `SD3 Plan caps`, two features named,
    neither reaching a record — drew a plain "Shared by …" foot, a plain border and no mark at all.
    A shared area draws no wire by design, so the mark and the words both land on the box, and the
    owners ARE named here because nothing else on the page joins them to it."""
    with _served_map(make_owner_states_map) as url, _page(url + "#v=features") as page:
        _settle(page)
        b = _owner_screen(page)["boxes"]["SD2"]
        assert b["shared"] and b["gap"], b
        assert b["foot"].startswith("Shared by Upstream MCPs, Access control."), b["foot"]
        assert "No step of any of them reaches this data." in b["foot"], b["foot"]
        assert not page.js_errors, page.js_errors


def test_the_box_does_not_repeat_what_its_own_picture_already_draws() -> None:
    """The foot opened "Said to exist for <feature>" while the wire in the SAME picture already
    joined that feature to this box — the case `a box does not repeat its picture` is written for,
    whose stated reason is literally this page. The new half is what nothing else says: that no step
    reaches the data. A SHARED area is the exception and keeps its owners' names, because it draws no
    wire for anything to read them off."""
    with _served_map(make_owner_states_map) as url, _page(url + "#v=features") as page:
        _settle(page)
        b = _owner_screen(page)["boxes"]
        # The foot is THERE and says the gap — without this the assertions below pass on a page that
        # draws no foot at all, which is where this started.
        assert b["SD4"]["foot"].startswith("No step of it reaches this data."), b["SD4"]["foot"]
        assert "Said to exist for" not in b["SD4"]["foot"], b["SD4"]["foot"]
        assert "Tool access via gateway" not in b["SD4"]["foot"], b["SD4"]["foot"]
        assert "Upstream MCPs" in b["SD2"]["foot"], "a shared area has no wire to name its owners"
        assert not page.js_errors, page.js_errors


def test_the_page_never_speaks_for_a_tool_it_is_not_running() -> None:
    """The gap label used to claim "`coyomap validate` reports this as an owner with no evidence" —
    a sentence that is FALSE on all four live maps, because every one of those areas is recorded and
    `validate` therefore reports nothing at all. The page says what the MAP says.

    The label also has to keep its qualifier: "no step reaches this" is simply false on a box a
    reference arrow from ANOTHER feature also lands on (mcpolis SD11, live)."""
    with _served_map(make_owner_states_map) as url, _page(url + "#v=features") as page:
        _settle(page)
        assert "validate" not in _owner_screen(page)["pageText"]
        labels = page.evaluate("""() => [...document.querySelectorAll('.story-elabel-gap')]
            .map(l => [l.textContent, l.title])""")
        assert labels, "a gap wire carries its label"
        for text, title in labels:
            assert text == "no step of it reaches this", text
            assert "validate" not in title, title
            assert ("The map says why:" in title or "the map does not say why" in title), title
        assert not page.js_errors, page.js_errors


def test_a_records_own_page_says_whether_anything_backs_its_owner() -> None:
    """The OTHER place the same claim is made. 85 of the 237 records that draw an "Owned by" row
    across the four live maps sit in an area whose owners no step reaches, and the row said it
    flatly: `E44 SandboxPersistedRef` reads "Owned by: Hosted stdio MCPs" directly above an "In use
    cases" row naming a different feature — the contradiction on one screen, unmarked.

    A record carrying `owners` of ITS OWN is left alone: the area's gap says nothing about an answer
    the record overrode, so the two sets are compared rather than assumed equal."""
    with _served_map(make_owner_states_map) as url, _page(url + "#v=element&id=E26") as page:
        _settle(page)
        got = page.evaluate("""() => {
            const sec = [...document.querySelectorAll('.item-sec')]
                .find(s => (s.querySelector('h2') || {}).textContent === 'Owned by');
            const body = sec && sec.querySelector('.item-sec-body');
            return { row: body ? body.textContent : '(no row)',
                     note: document.querySelectorAll('.dv-note-gap').length };
        }""")
        assert "Tool access via gateway" in got["row"], got
        assert "No step of it reaches this data." in got["row"], got
        assert _SHARED_REASON in got["row"], got
        assert got["note"] == 1, got
        assert not page.js_errors, page.js_errors
    # …and a record whose owner IS backed says nothing extra.
    with _served_map(make_owner_states_map) as url, _page(url + "#v=element&id=E1") as page:
        _settle(page)
        got = page.evaluate("""() => ({
            row: (() => { const sec = [...document.querySelectorAll('.item-sec')]
                    .find(s => (s.querySelector('h2') || {}).textContent === 'Owned by');
                  const bd = sec && sec.querySelector('.item-sec-body');
                  return bd ? bd.textContent : '(no row)'; })(),
            note: document.querySelectorAll('.dv-note-gap').length })""")
        assert "No step of" not in got["row"], got
        assert got["note"] == 0, got
        assert not page.js_errors, page.js_errors



def test_a_pages_own_title_carries_no_glossary_link() -> None:
    """A page about one element is not decorated with a link to itself. The skip list covered
    headings, and a page's title is not one — it is a `p`, because the breadcrumb is what names the
    page — so a title that CONTAINS a glossary term underlined its own words. Here "Tool access via
    gateway" linked both "Tool" and "Gateway" to their definitions.

    The sentence under the title is prose and keeps its links: this turns off the title, not the
    glossary."""
    with _served() as url, _page(url + "#v=capability&cap=CAP4") as page:
        _settle(page)
        got = page.evaluate("""() => ({
            title: (document.querySelector('.page-hero-name') || {}).textContent || '',
            inTitle: document.querySelectorAll('.page-hero-name .gloss-link').length,
            onPage: document.querySelectorAll('.gloss-link').length,
        })""")
        assert "Tool access via gateway" in got["title"], got
        assert got["inTitle"] == 0, got
        assert got["onPage"] > 0, "the page's prose still links its terms"
        assert not page.js_errors, page.js_errors


# --- the Architecture view: one feature first, one story followed, one box's steps ------------------

def _arch_ready(page: Any) -> None:
    page.wait_for_selector("#diagram .edgePaths path.flowchart-link", state="attached")
    _settle(page)


def test_the_architecture_view_opens_on_the_first_feature_and_all_is_one_click_away() -> None:
    """The whole product is the picture with the most lines, so the view opens on the first feature
    the Features page lists, and `All` is a button that names itself in the address."""
    with _served() as url, _page(url + "#v=arch") as page:
        _arch_ready(page)
        seen = page.evaluate("""() => ({
            lit: document.querySelector('.archwho.on').dataset.archcap,
            buttons: [...document.querySelectorAll('.archwho')].map((b) => b.dataset.archcap) })""")
        assert seen["buttons"][0] == "all"
        assert seen["lit"] == seen["buttons"][1], seen
        page.evaluate("() => document.querySelector('.archwho[data-archcap=\"all\"]').click()")
        page.wait_for_function("() => location.hash.includes('cap=all')")
        _arch_ready(page)
        assert page.evaluate("() => document.querySelector('.archwho.on').dataset.archcap") == "all"
        assert not page.js_errors, page.js_errors


def test_the_happy_path_switch_is_on_a_features_picture_and_not_on_all() -> None:
    """The whole product is every story; its happy path alone is a feature's question. The switch sits
    over a feature's picture, and the whole product's has none: an address asking for it there draws
    the whole product."""
    with _served() as url, _page(url + "#v=arch") as page:
        _arch_ready(page)
        assert page.evaluate("() => !document.getElementById('archhp').hidden"), "a feature's picture keeps it"
        page.goto(url + "#v=arch&cap=all&scope=happy")
        page.reload()
        _arch_ready(page)
        assert page.evaluate("() => document.getElementById('archhp').hidden")
        whole = page.evaluate("() => document.querySelectorAll('#diagram .edgePaths path.flowchart-link').length")
        page.goto(url + "#v=arch&cap=all")
        page.reload()
        _arch_ready(page)
        assert page.evaluate("() => document.querySelectorAll('#diagram .edgePaths path.flowchart-link').length") == whole
        assert not page.js_errors, page.js_errors


# A line's card, read off the screen: the address's pick, the card's title and badge, its use case rows.
LINE_CARD = """(card) => { const c = document.querySelector(card);
    return { hash: decodeURIComponent(location.hash), shown: !c.hidden,
             title: (c.querySelector('.pane-title h2') || {}).textContent || '',
             badge: (c.querySelector('.pane-title .badge') || {}).textContent || '',
             ucs: [...c.querySelectorAll('.archuc .archuc-name')].map((x) => x.dataset.ucopen),
             }; }"""


def _arch_line(text: dict[str, Any], hash_: str) -> dict[str, Any]:
    pick = hash_.split("sel=arch:")[1].split("&")[0]
    src, dst = pick.split(">")
    return next(e for e in text["lines"] if (e["srcBox"], e["dstBox"]) == (src, dst))


def test_a_line_on_the_architecture_picture_is_picked_and_its_card_names_its_use_cases() -> None:
    """A click on a line picks it, as a click on a box does: the address keeps it, and its card names its
    two ends and the use cases that take it, by feature, and not the code's verb. A use case's name opens
    its own map, with the steps this line draws selected there."""
    text = make_whole_product_text(lambda m: None)
    assert not text.get("layerLines"), "the fixture's whole product must not be crowded"
    with _served() as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        page.evaluate("""() => document.querySelector('#diagram .cy-edgehit')
            .dispatchEvent(new MouseEvent('click', { bubbles: true }))""")
        page.wait_for_function("() => location.hash.includes('sel=arch')")
        seen = page.evaluate(LINE_CARD, "#panel")
        e = _arch_line(text, seen["hash"])
        named = {uc for x in e["sentences"] for uc in x["ucs"]}
        assert seen["shown"] and seen["title"] == f"{e['src']} \u2192 {e['dst']}", seen
        assert seen["badge"] == ("keeps records" if e["store"] else ""), "no shared step number: " + str(seen)
        assert set(seen["ucs"]) == named, (seen, named)
        assert not page.evaluate("() => document.querySelector('#panel .archcard-via')") or e["via"], \
            "the card says no verb"
        # a reload keeps the pick, as it keeps a box's
        page.reload()
        _arch_ready(page)
        assert page.evaluate(LINE_CARD, "#panel")["title"] == seen["title"]
        # a use case's name opens its own map
        uc, ns = page.evaluate("""() => { const btn = document.querySelector('#panel .archuc .archuc-name');
            btn.click(); return [btn.dataset.ucopen, btn.dataset.ucsteps]; }""")
        page.wait_for_function(f"() => location.hash.includes('v=usecase') && location.hash.includes('uc={uc}')")
        # …with this line's steps of it selected there
        assert ns.split(",") == [str(n) for n in e["steps"][uc]], (ns, e["steps"])
        page.wait_for_timeout(600)
        picked = page.evaluate("() => decodeURIComponent(location.hash).split('&').filter((x) => x.startsWith('sel=flowstep:')).length")
        assert picked == len(e["steps"][uc]), (picked, e["steps"][uc])
        # …and the map lights those steps, each its own badge
        lit = page.evaluate("() => [...document.querySelectorAll('#diagram .flow-step-num.flow-step-picked')].map((n) => +n.textContent)")
        assert sorted(lit) == sorted(e["steps"][uc]), (lit, e["steps"][uc])
        assert not page.js_errors, page.js_errors


def test_on_a_features_picture_a_lines_card_lists_its_use_cases_with_no_feature_over_them() -> None:
    """On a feature's picture every use case is that feature's, so the card lists them directly; the
    whole product's lists them by feature."""
    with _served() as url, _page(url + "#v=arch") as page:
        _arch_ready(page)
        page.evaluate("""() => document.querySelector('#diagram .cy-edgehit')
            .dispatchEvent(new MouseEvent('click', { bubbles: true }))""")
        page.wait_for_function("() => location.hash.includes('sel=arch')")
        seen = page.evaluate("""() => ({ feats: document.querySelectorAll('#panel .archuc-feat').length,
            ucs: document.querySelectorAll('#panel .archuc').length,
            head: document.querySelector('#panel .archcard-lbl').textContent })""")
        assert seen["feats"] == 0 and seen["ucs"] > 0 and seen["head"] == "Use cases using this line", seen
        assert not page.js_errors, page.js_errors


def test_hovering_a_line_while_one_is_picked_shows_its_card_beside_the_picked_one() -> None:
    """A picked line keeps its card. Resting on another line shows that one's card in the second card,
    beside it, and the picked card stays."""
    with _served() as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        page.evaluate("""() => document.querySelector('#diagram .cy-edgehit')
            .dispatchEvent(new MouseEvent('click', { bubbles: true }))""")
        page.wait_for_function("() => location.hash.includes('sel=arch')")
        picked = page.evaluate(LINE_CARD, "#panel")["title"]
        # the middle of another line, on screen and clear of both cards
        at = page.evaluate("""() => {
            const cards = ['#panel', '#peekcard'].map((s) => document.querySelector(s))
              .filter((c) => !c.hidden).map((c) => c.getBoundingClientRect());
            const free = (x, y) => !cards.some((r) => x > r.left && x < r.right && y > r.top && y < r.bottom);
            for (const p of document.querySelectorAll('#diagram .edgePaths path.flowchart-link')) {
              if (p.classList.contains('is-selected') || !p.__cyHits) continue;
              const L = p.getTotalLength(), m = p.getScreenCTM();
              for (const f of [0.5, 0.35, 0.65]) {
                const q = p.getPointAtLength(L * f), x = m.a * q.x + m.c * q.y + m.e, y = m.b * q.x + m.d * q.y + m.f;
                const el = document.elementFromPoint(x, y);
                if (free(x, y) && el && p.__cyHits.includes(el)) return { x, y };
              }
            }
            return null; }""")
        assert at, "no other line to rest on"
        page.mouse.move(at["x"] - 30, at["y"] - 30)
        page.mouse.move(at["x"], at["y"], steps=4)
        page.wait_for_function("() => !document.getElementById('peekcard').hidden")
        peek = page.evaluate(LINE_CARD, "#peekcard")
        assert peek["title"] and peek["title"] != picked and peek["ucs"], peek
        assert page.evaluate(LINE_CARD, "#panel")["title"] == picked
        assert not page.js_errors, page.js_errors


def test_a_line_names_its_use_cases_by_feature() -> None:
    """A line says which use cases take it, by feature: the use case is what a line is for, and the
    feature is what a reader knows the product by. Each feature has a count and opens to its use cases;
    each use case shows its own step sentence under its name, and follows its story."""
    text = make_whole_product_text(lambda m: None)
    def ucs(e: dict[str, Any]) -> set[str]:
        return {u for x in e["sentences"] for u in x["ucs"]}
    busy = [e for e in text["lines"] if not e["store"] and len(ucs(e)) > 3]
    assert busy, "the fixture's whole product needs a line taken by more than 3 use cases"
    with _served() as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        # EVERY LINE'S CARD, one click each: the card is what tells a line's use cases.
        seen = page.evaluate("""() => [...document.querySelectorAll('#diagram .edgePaths path.flowchart-link')]
          .filter((p) => p.__cyHits && p.__cyHits.length).map((p) => {
            p.__cyHits[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
            const [src, dst] = decodeURIComponent(location.hash).split('sel=arch:')[1].split('&')[0].split('>');
            const l = document.getElementById('panel');
            return { src, dst,
              feats: [...l.querySelectorAll('.archuc-feat > summary .archuc-count')].map((c) => +c.textContent),
              ucs: l.querySelectorAll('.archuc').length,
              follows: l.querySelectorAll('.archuc .archuc-name[data-ucopen]').length,
              sents: l.querySelectorAll('.archuc .archuc-sent').length }; })""")
        by = {(r["src"], r["dst"]): r for r in seen}
        assert len(by) == len(text["lines"]), "every line of the picture has a card"
        for e in [e for e in text["lines"] if not e["store"]]:
            r = by[(e["srcBox"], e["dstBox"])]
            assert r["ucs"] == len(ucs(e)) == r["follows"], (e["srcBox"], e["dstBox"], r)
            assert r["sents"] >= r["ucs"], r   # every use case opens to the sentence it says here
            # by feature when several use it; one feature's use cases are listed with no fold over them
            assert (sum(r["feats"]) == r["ucs"] and len(r["feats"]) > 1) or (not r["feats"] and r["ucs"]), r
        assert any(r["feats"] for r in seen), "a line from several features is grouped by feature"
        assert not page.js_errors, page.js_errors


# A POINT ON AN ARCHITECTURE BOX'S OWN BODY, clear of its name (which opens it) and its part tags
# (which open a part): the first spot inside a box, scanned from its bottom-right corner, that the box
# itself answers for. A box says no sentence there, so there is no line of text to aim at instead.
ARCH_BOX_BODY = """() => {
    for (const n of document.querySelectorAll('#diagram g.node')) {
      const b = n.querySelector('.ibox-map');
      if (!b) continue;
      const r = b.getBoundingClientRect();
      for (let y = r.bottom - 3; y > r.top; y -= 3) for (let x = r.right - 3; x > r.left; x -= 3) {
        const e = document.elementFromPoint(x, y);
        if (e && b.contains(e) && !e.closest('button, a, .ibox-name, .item-pill'))
          return { x, y, name: n.querySelector('.ibox-name').textContent.trim() };
      }
    }
    return null;
}"""


def test_a_click_on_a_box_picks_it_and_escape_lets_go_of_it() -> None:
    """The box around the name selects it and steps back what does not touch it, with no tag naming it
    a third time; Escape lets go."""
    with _served() as url, _page(url + "#v=arch") as page:
        _arch_ready(page)
        spot = page.evaluate(ARCH_BOX_BODY)
        page.mouse.click(spot["x"], spot["y"])
        page.wait_for_timeout(700)
        seen = page.evaluate("""() => ({
            dim: document.querySelectorAll('#diagram g.node.dim').length,
            tag: !!document.getElementById('archthrough') })""")
        assert seen["dim"] > 0 and not seen["tag"], seen
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        seen = page.evaluate("""() => ({ hash: location.hash, dim: document.querySelectorAll('#diagram g.node.dim').length })""")
        assert not seen["dim"] and "sel=" not in seen["hash"], seen
        assert not page.js_errors, page.js_errors


def test_an_architecture_box_and_a_person_take_every_other_pictures_gestures() -> None:
    """Four gestures every other picture has, which the Architecture picture lacked: resting on a box
    shows its card and no corner magnifier, a person's box picks like any other box and lights its
    lines, and a click on empty space lets go of the box."""
    with _served() as url, _page(url + "#v=arch") as page:
        _arch_ready(page)
        box = page.evaluate(ARCH_BOX_BODY)
        page.mouse.move(box["x"], box["y"])
        page.mouse.move(box["x"] + 1, box["y"])
        page.wait_for_timeout(600)
        seen = page.evaluate("""() => ({ icons: document.querySelectorAll('.action-icon').length,
                                         card: document.querySelector('#panel').textContent })""")
        assert seen["icons"] == 0, "no corner magnifier on any box"
        assert box["name"] in seen["card"], (box, seen["card"][:200])
        # A PERSON: on the figure, clear of the name, which opens their page.
        person = page.evaluate("""() => {
            const n = [...document.querySelectorAll('#diagram g.node')].find((x) => /-CYP/.test(x.id));
            const r = n.getBoundingClientRect();
            return { x: r.left + 6, y: r.top + 6 };
        }""")
        page.mouse.click(person["x"], person["y"])
        page.wait_for_timeout(700)
        seen = page.evaluate("""() => ({ hash: location.hash,
            dim: document.querySelectorAll('#diagram g.node.dim').length })""")
        assert "sel=node%3ACYP" in seen["hash"], seen
        assert seen["dim"] > 0, seen
        # EMPTY SPACE: a point of the drawing with nothing drawn under it.
        empty = page.evaluate("""() => {
            const svg = document.querySelector('#diagram svg'), r = svg.getBoundingClientRect();
            for (let y = r.top + 8; y < r.bottom; y += 12) for (let x = r.left + 8; x < r.right; x += 12)
              if (document.elementFromPoint(x, y) === svg) return { x, y };
            return null;
        }""")
        assert empty, "the drawing has no empty spot"
        page.mouse.click(empty["x"], empty["y"])
        page.wait_for_timeout(500)
        seen = page.evaluate("""() => ({ hash: location.hash,
            selected: document.querySelectorAll('#diagram .is-selected').length })""")
        assert "sel=" not in seen["hash"] and seen["selected"] == 0, seen
        assert not page.js_errors, page.js_errors


def test_a_long_box_name_wraps_inside_its_box() -> None:
    """The drawing engine sets `nowrap` on every label, and a box inherited it: a name longer than the
    box's ceiling ran past its right edge. It wraps now, whole, never cut and never an ellipsis."""
    def make_long_names(m: dict[str, Any]) -> None:
        for key in ("subsystems", "components", "dependencies"):
            for x in m.get(key, []):
                x["name"] = x["name"] + " with a tail that runs well past any box's ceiling"
    with _served_map(make_long_names) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        seen = page.evaluate("""() => [...document.querySelectorAll('#diagram .ibox')].map((b) => {
            const n = b.querySelector('.ibox-name'), r = b.getBoundingClientRect();
            const t = n ? n.getBoundingClientRect() : r;
            return { name: n ? n.textContent : '', out: t.right > r.right + 0.5,
                     cut: n ? getComputedStyle(n).textOverflow : '' }; })""")
        assert any("well past" in s["name"] for s in seen), "the long name is drawn"
        assert not [s for s in seen if s["out"]], [s for s in seen if s["out"]]
        assert all(s["cut"] != "ellipsis" for s in seen)
        assert not page.js_errors, page.js_errors


def test_picking_a_box_changes_nothing_inside_it() -> None:
    """A click marks a box; it does not lay it out again. The pick drew a wider border and shrank the
    padding to match, and the browser rounds the two borders differently, so a box lost a pixel inside
    and a pill that fitted exactly dropped to a new line. Every box, every part of it, to the half pixel."""
    snap = """(b) => { const r0 = b.getBoundingClientRect();
        return [r0.width, r0.height, ...[...b.querySelectorAll('*')].map((e) => {
          const r = e.getBoundingClientRect();
          return Math.round((r.left - r0.left) * 2) / 2 + ',' + Math.round((r.top - r0.top) * 2) / 2; })]; }"""
    with _served() as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        boxes = page.locator("#diagram g.node .ibox")
        assert boxes.count() > 5
        for i in range(boxes.count()):
            box = boxes.nth(i)
            before = box.evaluate(snap)
            box.evaluate("(b) => b.dispatchEvent(new MouseEvent('click', { bubbles: true }))")
            assert box.evaluate("(b) => b.classList.contains('ibox-picked')")
            assert box.evaluate(snap) == before, box.evaluate("(b) => b.textContent")
        assert not page.js_errors, page.js_errors


def test_a_part_tag_shows_its_own_card_beside_the_box_card() -> None:
    """Resting on a part's tag inside its subsystem's box shows the PART's card as a second card, and the
    box's card stays: the part is read in its box's context. Each card has its own line, the second one
    pointing at the tag. Back on the box's own body, the part's card goes and the box's stays."""
    with _served_map(make_every_part_do_work) as url, _page(url + "#v=arch") as page:
        _arch_ready(page)
        cards = """() => { const n = (c) => { const e = document.querySelector(c);
            return !e || e.hidden ? '' : ((e.querySelector('.ibox-name') || {}).textContent || '').trim(); };
          const r = (c) => { const e = document.querySelector(c); return e && !e.hidden ? e.getBoundingClientRect() : null; };
          const a = r('#panel'), b = r('#peekcard');
          return { box: n('#panel'), tag: n('#peekcard'), lines: document.querySelectorAll('#callout .co-line').length,
                   overlap: !!(a && b && a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) }; }"""
        # A BOX ON SCREEN, top and bottom: the picture is wider and taller than the window.
        k = page.evaluate("""() => [...document.querySelectorAll('#diagram g.node .ibox-map')].findIndex((b) => {
            const r = b.getBoundingClientRect(), d = document.querySelector('#diagram').getBoundingClientRect();
            return b.querySelector('.item-pill[data-item]') && r.top > d.top + 10 && r.bottom < d.bottom - 150
              && r.left > d.left + 10 && r.right < d.right - 10; })""")
        assert k >= 0, "no box with a tag fully on screen"
        box = page.locator("#diagram g.node .ibox-map").nth(k)
        tag = box.locator(".item-pill[data-item]").first
        sub_name = box.locator(".ibox-name").first.text_content().strip()
        part_name = tag.text_content().strip()
        bb, tb = box.bounding_box(), tag.bounding_box()
        assert bb and tb
        body = (bb["x"] + bb["width"] - 3, bb["y"] + 4)
        page.mouse.move(body[0] - 1, body[1])
        page.mouse.move(*body)
        page.wait_for_timeout(500)
        assert page.evaluate(cards) == {"box": sub_name, "tag": "", "lines": 1, "overlap": False}
        page.mouse.move(tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] / 2, steps=4)
        page.wait_for_timeout(500)
        assert page.evaluate(cards) == {"box": sub_name, "tag": part_name, "lines": 2, "overlap": False}
        # the second line lands on the tag, not on the box around it
        ends = page.evaluate("""() => [...document.querySelectorAll('#callout .co-line')].map((l) => {
            const m = l.getScreenCTM(), v = (k) => l[k].baseVal.value;
            return [m.a * v('x2') + m.e, m.d * v('y2') + m.f]; })""")
        near = lambda pt: (tb["x"] - 3 <= pt[0] <= tb["x"] + tb["width"] + 3
                           and tb["y"] - 3 <= pt[1] <= tb["y"] + tb["height"] + 3)
        assert any(near(pt) for pt in ends), (ends, tb)
        page.mouse.move(*body, steps=4)
        page.wait_for_timeout(500)
        assert page.evaluate(cards) == {"box": sub_name, "tag": "", "lines": 1, "overlap": False}
        assert not page.js_errors, page.js_errors


def test_more_on_a_group_box_opens_it_to_list_every_part() -> None:
    """A group box names its first parts and says "+N more" for the rest. Clicking that opens THAT box:
    the picture is drawn again with its every part named, the address says which box is open, and Back
    closes it. Only the clicked box opens: one subsystem has a box in each layer it has parts in, and
    opening by subsystem opened all of them. The camera stays: the clicked box where it stood on screen,
    at the same size."""
    groups = make_whole_product_text(make_every_part_do_work)["cells"]
    assert [g for g in groups.values() if len(g["parts"]) > 4], "the changed map must have a big group"
    with _served_map(make_every_part_do_work) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        closed = "() => [...document.querySelectorAll('#diagram .ibox-more')].map((b) => b.closest('g.node').id.split('-').slice(-2, -1)[0])"
        before_closed = page.evaluate(closed)
        box_id = before_closed[0]
        where = f"""() => {{ const n = [...document.querySelectorAll('#diagram g.node')].find((x) => x.id.includes('-{box_id}-'));
            const r = n.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.width)]; }}"""
        before = page.evaluate(where)   # the width is the scale on screen
        page.evaluate("() => document.querySelector('#diagram .ibox-more').click()")
        page.wait_for_function(f"() => location.hash.includes('open={box_id}')")
        _arch_ready(page)
        page.wait_for_timeout(300)
        assert page.evaluate(where) == before, (box_id, before, page.evaluate(where))
        tags = page.evaluate(f"""() => [...document.querySelectorAll('#diagram g.node')].find((x) => x.id.includes('-{box_id}-'))
            .querySelectorAll('.item-pill[data-item]').length""")
        assert tags == len(groups[box_id]["parts"]), (box_id, tags, groups[box_id])
        assert page.evaluate(closed) == before_closed[1:], "every other box stays as it was"
        page.go_back()
        page.wait_for_function("() => !location.hash.includes('open=')")
        assert not page.js_errors, page.js_errors


def test_a_two_line_name_opens_only_from_its_words() -> None:
    """A name that wraps is a button two lines tall, and the space beside its shorter line was the
    button too: a click there opened the thing. Only the words open it now; the space picks the box."""
    def make_long_names(m: dict[str, Any]) -> None:
        for x in m.get("subsystems", []):
            x["name"] = x["name"] + " and a tail long enough to wrap"
    with _served_map(make_long_names) as url, _page(url + "#v=arch") as page:
        _arch_ready(page)
        spot = page.evaluate("""() => { for (const n of document.querySelectorAll('#diagram .ibox-map .ibox-name')) {
            const range = document.createRange(); range.selectNodeContents(n); const rs = [...range.getClientRects()];
            const b = n.getBoundingClientRect(), last = rs[rs.length - 1];
            if (rs.length < 2 || b.right - last.right < 15) continue;
            return { blank: [last.right + (b.right - last.right) / 2, (last.top + last.bottom) / 2],
                     words: [(rs[0].left + rs[0].right) / 2, (rs[0].top + rs[0].bottom) / 2] }; } return null; }""")
        assert spot, "no two-line name with space beside its second line"
        # …and the underline says the same: none on the blank, one on the words
        under = "() => { const n = document.querySelector('#diagram .ibox-name:hover'); return n ? getComputedStyle(n).textDecorationLine : ''; }"
        page.mouse.move(spot["blank"][0] - 1, spot["blank"][1])
        page.mouse.move(*spot["blank"])
        assert page.evaluate(under) == "none"
        page.mouse.move(*spot["words"])
        assert page.evaluate(under) == "underline"
        before = page.evaluate("() => location.hash")
        page.mouse.click(*spot["blank"])
        page.wait_for_timeout(600)
        after = page.evaluate("() => location.hash")
        assert after.split("&sel=")[0] == before.split("&sel=")[0] and "sel=" in after, (before, after)
        page.mouse.click(*spot["words"])
        page.wait_for_function("() => !location.hash.startsWith('#v=arch')")
        assert not page.js_errors, page.js_errors


def test_a_floating_card_opens_from_its_title_alone_and_draws_no_frame() -> None:
    """A floating card is read, not chosen from a list: hovering it draws no frame, a click on its body
    leaves the screen as it is, and its title opens the thing's page. A card in a list still opens from
    anywhere on it."""
    with _served() as url, _page(url + "#v=container&sel=node%3AS4") as page:
        _settle(page)
        body = page.evaluate("""() => { const r = document.querySelector('#panel .ecard').getBoundingClientRect();
            return { x: r.right - 12, y: r.bottom - 6 }; }""")
        page.mouse.move(body["x"], body["y"])
        page.wait_for_timeout(300)
        seen = page.evaluate("""() => { const e = document.querySelector('#panel .ecard'), c = getComputedStyle(e);
            return { border: c.borderColor, stop: e.hasAttribute('tabindex'), title: e.querySelector('.ibox-name').tagName }; }""")
        assert seen == {"border": "rgba(0, 0, 0, 0)", "stop": False, "title": "BUTTON"}, seen
        before = page.evaluate("() => location.hash")
        page.mouse.click(body["x"], body["y"])
        page.wait_for_timeout(500)
        assert page.evaluate("() => location.hash") == before, "a click on the card's body opened something"
        page.click("#panel .ecard .ibox-name")
        page.wait_for_function("() => location.hash.includes('v=subsystem')")
        page.goto(url + "#v=element&id=S4")   # an element's page lists its parts as cards
        page.reload()
        _settle(page)
        before = page.evaluate("() => location.hash")
        page.evaluate("""() => { const c = document.querySelector('#diagram .ecard[data-id]');
            c.dispatchEvent(new MouseEvent('click', { bubbles: true })); }""")
        page.wait_for_function(f"() => location.hash !== {before!r}")
        assert not page.js_errors, page.js_errors


def test_a_hover_while_something_is_picked_shows_its_card_beside_the_pick() -> None:
    """A pick used to silence every hover: the reader had to let go of what they picked to ask about
    its neighbour. The picked card stays and the hovered thing's card shows beside it, the second card,
    with its own line; leaving takes only that one away. The same on every picture, because every
    picture's hover goes through one function."""
    spot = """(i) => { const n = [...document.querySelectorAll('#diagram g.node')][i]; const r = n.getBoundingClientRect();
        for (let y = r.bottom - 3; y > r.top; y -= 3) for (let x = r.right - 3; x > r.left; x -= 3) {
          const e = document.elementFromPoint(x, y);
          if (e && n.contains(e) && !e.closest('button, a, .ibox-name, .cyname, .item-pill')) return { x, y }; }
        return null; }"""
    cards = """() => { const n = (c) => { const e = document.querySelector(c);
        return !e || e.hidden ? '' : ((e.querySelector('.ibox-name') || {}).textContent || '').trim(); };
      return { picked: n('#panel'), peek: n('#peekcard'), lines: document.querySelectorAll('#callout .co-line').length }; }"""
    with _served() as url, _page(url + "#v=container") as page:
        _settle(page)
        a, b = page.evaluate(spot, 0), page.evaluate(spot, 1)
        page.mouse.click(a["x"], a["y"])
        page.wait_for_timeout(400)
        picked = page.evaluate(cards)["picked"]
        assert picked
        page.mouse.move(b["x"] - 1, b["y"])
        page.mouse.move(b["x"], b["y"])
        page.wait_for_timeout(500)
        seen = page.evaluate(cards)
        assert seen["picked"] == picked and seen["peek"] and seen["peek"] != picked and seen["lines"] == 2, seen
        page.mouse.move(3, 3, steps=3)
        page.wait_for_timeout(500)
        assert page.evaluate(cards) == {"picked": picked, "peek": "", "lines": 1}
        assert not page.js_errors, page.js_errors


def test_picking_what_the_second_card_shows_keeps_the_card_where_it_was() -> None:
    """With something picked, a hover shows the hovered thing's card beside it. Picking that thing used to
    move its card to wherever the picked card went, so the reader had to find it again: the card takes
    the second card's place now, its contents exactly where they were read."""
    spot = """(i) => { const n = [...document.querySelectorAll('#diagram g.node')][i]; const r = n.getBoundingClientRect();
        for (let y = r.top + 4; y < r.bottom; y += 3) for (let x = r.right - 3; x > r.left; x -= 3) {
          const e = document.elementFromPoint(x, y);
          if (e && n.contains(e) && !e.closest('button, a, .ibox-name, .cyname, .item-pill')) return { x, y }; }
        return null; }"""
    name = """(c) => { const e = document.querySelector(c); if (e.hidden) return null;
        const b = e.querySelector('.ibox-name').getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top)]; }"""
    with _served() as url, _page(url + "#v=container") as page:
        _settle(page)
        a, b = page.evaluate(spot, 0), page.evaluate(spot, 1)
        page.mouse.click(a["x"], a["y"])
        page.wait_for_timeout(400)
        page.mouse.move(b["x"] - 1, b["y"])
        page.mouse.move(b["x"], b["y"])
        page.wait_for_timeout(500)
        before = page.evaluate(name, "#peekcard")
        assert before, "the hover shows its card beside the pick"
        page.mouse.click(b["x"], b["y"])
        page.wait_for_timeout(800)
        assert page.evaluate(name, "#panel") == before
        assert page.evaluate("() => document.querySelector('#peekcard').hidden")
        assert not page.js_errors, page.js_errors


def test_a_lines_card_points_where_the_pointer_met_the_line() -> None:
    """A line's card points where the pointer met the line, not at its middle: a line on a crowded
    picture runs most of the screen's width."""
    text = make_whole_product_text(make_parts_in_every_layer)
    ends = [x for e in text["lines"] for x in (e["srcBox"], e["dstBox"]) if not x.startswith("CYP")]
    box = max(set(ends), key=ends.count)
    with _served_map(make_parts_in_every_layer) as url, _page(url + f"#v=arch&cap=all&sel=node%3A{box}") as page:
        _settle(page)
        page.wait_for_selector(".arch-ov-hit", state="attached")
        at = page.evaluate("""() => { const d = document.getElementById('diagram').getBoundingClientRect();
            const ls = [...document.querySelectorAll('.arch-ov-line')].sort((a, b) => b.getTotalLength() - a.getTotalLength());
            for (const l of ls) { const L = l.getTotalLength(), m = l.getScreenCTM();
              for (const f of [0.2, 0.25, 0.8, 0.75]) { const q = l.getPointAtLength(L * f), x = m.a * q.x + m.e, y = m.d * q.y + m.f;
                const e = document.elementFromPoint(x, y);
                if (x > d.left && x < d.right && y > d.top && y < d.bottom && e && e.classList.contains('arch-ov-hit')) return { x, y }; } }
            return null; }""")
        assert at, "no long line on screen"
        page.mouse.move(at["x"] - 2, at["y"] - 2)
        page.mouse.move(at["x"], at["y"], steps=3)
        page.mouse.click(at["x"], at["y"])
        page.wait_for_timeout(800)
        dot = page.evaluate("""() => { const c = document.querySelector('#callout .co-dot'), w = document.getElementById('diagwrap').getBoundingClientRect();
            return c ? { x: +c.getAttribute('cx') + w.left, y: +c.getAttribute('cy') + w.top } : null; }""")
        assert dot and abs(dot["x"] - at["x"]) < 12 and abs(dot["y"] - at["y"]) < 12, (dot, at)
        assert not page.js_errors, page.js_errors


def test_picking_a_line_whose_card_is_the_second_one_keeps_the_card_where_it_was() -> None:
    """The same for a line drawn on a crowded picture: with its box picked, resting on one of its lines
    shows the line's card beside the box's, and picking the line keeps that card where it was read. A
    line's card has a title rather than a box's name, and was measured by the name alone, so it moved
    down by the main card's bar; and a second card that had given up a few lines to fit was held to
    every line once picked, and jumped across the drawing."""
    title = """(c) => { const e = document.querySelector(c); if (e.hidden) return null;
        const b = e.querySelector('.pane-title').getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top)]; }"""
    text = make_whole_product_text(make_parts_in_every_layer)
    ends = [x for e in text["lines"] for x in (e["srcBox"], e["dstBox"]) if not x.startswith("CYP")]
    box = max(set(ends), key=ends.count)
    with _served_map(make_parts_in_every_layer) as url, _page(url + f"#v=arch&cap=all&sel=node%3A{box}") as page:
        _settle(page)
        page.wait_for_selector(".arch-ov-hit", state="attached")
        at = page.evaluate("""() => { const d = document.getElementById('diagram').getBoundingClientRect();
            for (const l of document.querySelectorAll('.arch-ov-line')) { const L = l.getTotalLength(), m = l.getScreenCTM();
              for (const f of [0.5, 0.4, 0.6, 0.3, 0.7]) { const q = l.getPointAtLength(L * f), x = m.a * q.x + m.e, y = m.d * q.y + m.f;
                const e = document.elementFromPoint(x, y);
                if (x > d.left && x < d.right && y > d.top && y < d.bottom && e && e.classList.contains('arch-ov-hit')) return { x, y }; } }
            return null; }""")
        assert at, "no line of the picked box on screen"
        page.mouse.move(at["x"] - 2, at["y"] - 2)
        page.mouse.move(at["x"], at["y"], steps=3)
        page.wait_for_timeout(500)
        before = page.evaluate(title, "#peekcard")
        assert before, "the hover shows the line's card beside the box's"
        page.mouse.click(at["x"], at["y"])
        page.wait_for_timeout(800)
        after = page.evaluate(title, "#panel")
        assert after and abs(after[0] - before[0]) <= 1 and abs(after[1] - before[1]) <= 1, (before, after)
        assert not page.js_errors, page.js_errors


def make_every_part_do_work(m: dict[str, Any]) -> None:
    """Every component doing the work: the Architecture picture is then layered, and each subsystem's
    parts are one box of the work layer."""
    for c in m["components"]:
        c["kind"] = "logic"


def make_one_part_a_screen(m: dict[str, Any]) -> None:
    """Every component doing the work but the dashboard's API router, kinded a screen: the work layer
    then calls up into the top layer."""
    for c in m["components"]:
        c["kind"] = "screen" if c["id"] == "C14" else "logic"


def make_whole_product_text(mutate: Any) -> dict[str, Any]:
    """What the view knows of the whole-product picture (its lines and cards), for the fixture map changed by `mutate`."""
    m = json.loads(_FIXTURE_MAP.read_text())
    mutate(m)
    return gen_arch_views(model_to_graph(load_model(json.dumps(m))))[1]["all|"]


def test_a_group_of_parts_names_its_parts_shows_its_subsystem_and_keeps_its_own_steps() -> None:
    """A group of parts is its subsystem's box on the layered picture. It names the parts it holds,
    each a tag that opens that part, with no sentence and no type word: every box inside the product
    is a subsystem on this picture, and its card is one hover away. The box around the name
    selects it and shows the subsystem's card; the name
    opens the subsystem."""
    groups = make_whole_product_text(make_every_part_do_work)["cells"]
    with _served_map(make_every_part_do_work) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        # A GROUP BOX A READER CAN CLICK: a point inside the box, clear of its name, its tags and the
        # drill icon on its top-left corner, and not under a line or a label: its bottom-right corner.
        spot = page.evaluate("""() => {
            const at = (n) => { const b = n.querySelector('.ibox').getBoundingClientRect();
                                return { x: b.right - 4, y: b.bottom - 4 }; };
            const hit = (n) => { const p = at(n); const el = document.elementFromPoint(p.x, p.y);
                                 return !!el && n.contains(el); };
            const n = [...document.querySelectorAll('#diagram g.node')]
              .find((x) => [...x.classList].some((c) => c.startsWith('cy-CYG')) && hit(x));
            const l = n.querySelector('.ibox-name').getBoundingClientRect();
            return { id: [...n.classList].find((c) => c.startsWith('cy-CYG')).slice(3), ...at(n),
                     tags: [...n.querySelectorAll('.item-pill')].map((t) => t.dataset.item),
                     more: (n.querySelector('.ibox-band .ibox-count') || {}).textContent || '',
                     sentence: !!n.querySelector('.ibox-what'),
                     word: [...n.querySelectorAll('.ibox-head .ibox-pill')].map((p) => p.textContent),
                     nameX: l.left + l.width / 2, nameY: l.top + l.height / 2 };
        }""")
        group = groups[spot["id"]]
        named = group["parts"] if len(group["parts"]) <= 4 else group["parts"][:3]
        assert spot["tags"] == named and not spot["sentence"] and not spot["word"], (spot, group)
        assert spot["more"] == ("" if len(group["parts"]) <= 4 else f"+{len(group['parts']) - 3} more"), spot
        page.mouse.click(spot["x"], spot["y"])
        page.wait_for_timeout(700)
        seen = page.evaluate("""() => ({ hash: location.hash,
            card: (document.querySelector('#panel .ecard[data-id]') || { dataset: {} }).dataset.id || '' })""")
        assert "node%3A" + spot["id"] in seen["hash"], seen
        assert seen["card"] == group["sub"], seen
        # A TAG OPENS ITS PART, not the box around it.
        page.evaluate(f"""() => document.querySelector('#diagram g.cy-{spot["id"]} .item-pill-door').click()""")
        page.wait_for_function(f"() => location.hash.includes('node%3A{named[0]}')")
        page.goto(url + "#v=arch&cap=all")
        _arch_ready(page)
        page.mouse.click(spot["nameX"], spot["nameY"])
        page.wait_for_function("() => location.hash.includes('v=subsystem')")
        assert f"sid={group['sub']}" in page.evaluate("() => location.hash")
        assert not page.js_errors, page.js_errors


def make_parts_in_every_layer(m: dict[str, Any]) -> None:
    """Each component in turn a screen, an API, logic and a store: the whole-product picture then has
    more lines than a picture draws one by one."""
    for i, c in enumerate(m["components"]):
        c["kind"] = ("screen", "api", "logic", "store")[i % 4]


# The lines between layers the drawing shows, and the box lines the view draws on top of it.
VISIBLE_LINES = """() => {
    const vis = (el) => { const cs = getComputedStyle(el); return cs.display !== 'none' && cs.opacity !== '0'; };
    const ps = [...document.querySelectorAll('#diagram .edgePaths path.flowchart-link')];
    return { layer: ps.filter((p) => p.classList.contains('arch-layerline') && vis(p)).length,
             box: document.querySelectorAll('#diagram .arch-overlay .arch-ov-line').length };
}"""


def test_a_crowded_picture_shows_lines_between_layers_and_a_boxs_own_lines_on_a_click() -> None:
    """A picture with more lines than a reader can follow draws one line per pair of layers that most of
    its layer takes, with no number, and none of its boxes' own. A layer line is drawing only: it takes
    no click and has no card. A click on a box draws its own lines on top of the picture."""
    text = make_whole_product_text(make_parts_in_every_layer)
    assert len(text["lines"]) > 40 and text["layerLines"], "the changed map must crowd the picture"
    rest = 0
    with _served_map(make_parts_in_every_layer) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        assert page.evaluate(VISIBLE_LINES) == {"layer": len(text["layerLines"]), "box": rest}
        # a layer line carries no number: on a picture that is not crowded, a number is a step
        labels = page.evaluate("""() => [...document.querySelectorAll('#diagram .edgeLabel.arch-layerline')]
            .map((l) => l.textContent.trim())""")
        assert labels and not any(labels), labels
        # THICK AT ANY ZOOM: 3 screen pixels of mid slate grey, whatever the picture's size.
        drawn = page.evaluate("""() => document.querySelectorAll('#diagram path.flowchart-link.arch-layerline')
            .values().map((p) => { const cs = getComputedStyle(p);
              return [cs.stroke, Math.round(parseFloat(cs.strokeWidth) * p.getScreenCTM().a * 10) / 10]; })
            .toArray()""")
        assert drawn and all(d == ["rgb(100, 116, 139)", 3.0] for d in drawn), drawn
        # …and painted ABOVE the frames, or a frame painted after them covers the end that meets its border
        on_top = page.evaluate("""() => { const p = document.querySelector('#diagram .edgePaths path.arch-layerline');
            const g = p.parentNode, top = g.parentNode, kids = [...top.children];
            return kids.indexOf(g) > kids.indexOf(top.querySelector(':scope > .nodes')); }""")
        assert on_top, "the layer lines are not the last thing their drawing paints"
        # A LAYER LINE IS DRAWING ONLY: no card, no lines of its own, and a click goes to what is behind it
        seen = page.evaluate("""() => { const p = document.querySelector('#diagram path.arch-layerline');
            return { hits: (p.__cyHits || []).length, events: getComputedStyle(p).pointerEvents }; }""")
        assert seen == {"hits": 0, "events": "none"}, seen
        # THE BOX WITH THE MOST LINES, clicked on its body: the picture is wider than the window, so a
        # point on screen cannot be counted on, and a click on the box's body is what a reader makes.
        people = {e["srcBox"] for e in text["lines"] if e["srcBox"].startswith("CYP")}
        ends = [x for e in text["lines"] for x in (e["srcBox"], e["dstBox"]) if x not in people]
        box = max(set(ends), key=ends.count)
        page.evaluate(f"""() => document.querySelector('#diagram g.cy-{box} .ibox')
            .dispatchEvent(new MouseEvent('click', {{ bubbles: true }}))""")
        page.wait_for_timeout(300)
        own = sum(1 for e in text["lines"] if box in (e["srcBox"], e["dstBox"]))
        assert own and page.evaluate(VISIBLE_LINES)["box"] == own, (box, own)
        # the boxes at the other end of those lines stay lit, as a picked box's neighbours do
        other = next(e["dstBox"] if e["srcBox"] == box else e["srcBox"] for e in text["lines"]
                     if box in (e["srcBox"], e["dstBox"]) and not {e["srcBox"], e["dstBox"]} & people)
        assert not page.evaluate(f"() => document.querySelector('#diagram g.cy-{other}').classList.contains('dim')")
        assert not page.js_errors, page.js_errors


def test_a_line_drawn_on_a_crowded_picture_is_picked_and_shows_its_card() -> None:
    """The box lines a crowded picture draws on top of itself, a picked box's here, are picked like any
    line: a click lights the line, names it in the address and shows its card."""
    text = make_whole_product_text(make_parts_in_every_layer)
    with _served_map(make_parts_in_every_layer) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        ends = [x for e in text["lines"] for x in (e["srcBox"], e["dstBox"]) if not x.startswith("CYP")]
        box = max(set(ends), key=ends.count)
        page.evaluate(f"""() => document.querySelector('#diagram g.cy-{box} .ibox')
            .dispatchEvent(new MouseEvent('click', {{ bubbles: true }}))""")
        page.wait_for_timeout(300)
        page.evaluate("""() => document.querySelector('#diagram .arch-ov-hit')
            .dispatchEvent(new MouseEvent('click', { bubbles: true }))""")
        page.wait_for_function("() => location.hash.includes('sel=arch')")
        seen = page.evaluate(LINE_CARD, "#panel")
        e = _arch_line(text, seen["hash"])
        assert seen["shown"] and seen["title"] == f"{e['src']} \u2192 {e['dst']}", seen
        lit = page.evaluate("""() => [...document.querySelectorAll('#diagram .arch-ov-line.arch-ov-picked')]
            .map((l) => [l.dataset.src, l.dataset.dst])""")
        assert lit == [[e["srcBox"], e["dstBox"]]], lit
        # the overlay's other lines are still drawn: picking one line does not take its neighbours away
        assert page.evaluate(VISIBLE_LINES)["box"] > 1
        assert not page.js_errors, page.js_errors


def test_with_a_box_picked_resting_on_another_shows_its_card_and_draws_none_of_its_lines() -> None:
    """With a box picked, its lines are what the reader is reading: resting on another box shows that
    box's card beside the picked one's, and draws none of its lines."""
    with _served_map(make_parts_in_every_layer) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        boxes = page.evaluate("""() => { const d = document.getElementById('diagram').getBoundingClientRect(); const out = [];
            for (const n of document.querySelectorAll('#diagram g.node')) {
              const b = n.querySelector('.ibox-map'); if (!b) continue; const r = b.getBoundingClientRect();
              if (r.right - 3 < d.left || r.right - 3 > d.right) continue;
              for (let y = Math.min(r.bottom, d.bottom) - 3; y > Math.max(r.top, d.top); y -= 3) { const e = document.elementFromPoint(r.right - 3, y);
                if (e && b.contains(e) && !e.closest('button, a, .ibox-name, .item-pill')) { out.push({ x: r.right - 3, y }); break; } }
              if (out.length === 2) break; }
            return out; }""")
        assert len(boxes) == 2, boxes
        page.mouse.click(boxes[0]["x"], boxes[0]["y"])
        page.wait_for_timeout(500)
        count = "() => document.querySelectorAll('#diagram .arch-ov-line').length"
        picked = page.evaluate(count)
        assert picked > 0
        page.mouse.move(boxes[1]["x"] - 1, boxes[1]["y"])
        page.mouse.move(boxes[1]["x"], boxes[1]["y"])
        page.wait_for_timeout(500)
        assert page.evaluate(count) == picked, "the hovered box drew its lines"
        assert page.evaluate("() => !document.getElementById('peekcard').hidden"), "its card shows beside the pick"
        assert not page.js_errors, page.js_errors


def test_resting_on_a_box_of_a_picture_that_draws_every_line_lights_its_own() -> None:
    """On a picture that draws every line, resting on a box lights the lines it takes part in, and only
    those, until the pointer leaves."""
    with _served() as url, _page(url + "#v=arch") as page:
        _arch_ready(page)
        spot = page.evaluate(ARCH_BOX_BODY)
        page.mouse.move(spot["x"] - 1, spot["y"])
        page.mouse.move(spot["x"], spot["y"])
        page.wait_for_timeout(300)
        lit = page.evaluate("""() => [...document.querySelectorAll('#diagram path.flowchart-link.arch-preview-on')].length""")
        total = page.evaluate("() => document.querySelectorAll('#diagram path.flowchart-link').length")
        assert 0 < lit < total, (lit, total)
        page.mouse.move(2, 2)
        page.wait_for_timeout(500)
        assert page.evaluate("() => document.querySelectorAll('#diagram .arch-preview-on').length") == 0
        assert not page.js_errors, page.js_errors


def test_resting_on_a_box_of_a_crowded_picture_draws_its_lines_while_the_pointer_is_on_it_or_them() -> None:
    """Resting on a box draws its lines, as resting on a line between layers does. They stay while the
    pointer moves from the box onto one of them, and go when it leaves both."""
    with _served_map(make_parts_in_every_layer) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        spot = page.evaluate(ARCH_BOX_BODY)
        assert spot
        page.mouse.move(spot["x"] - 1, spot["y"])
        page.mouse.move(spot["x"], spot["y"])
        page.wait_for_timeout(300)
        n = page.evaluate("() => document.querySelectorAll('#diagram .arch-ov-line').length")
        assert n > 0
        at = page.evaluate("""() => { const d = document.getElementById('diagram').getBoundingClientRect();
            for (const l of document.querySelectorAll('.arch-ov-line')) {
              const L = l.getTotalLength(), m = l.getScreenCTM();
              for (const f of [0.3, 0.5, 0.7]) { const q = l.getPointAtLength(L * f);
                const x = m.a * q.x + m.e, y = m.d * q.y + m.f;
                if (x > d.left && x < d.right && y > d.top && y < d.bottom) return { x, y }; } }
            return null; }""")
        assert at, "no line on screen"
        page.mouse.move(at["x"], at["y"], steps=10)
        page.wait_for_timeout(500)
        assert page.evaluate("() => document.querySelectorAll('#diagram .arch-ov-line').length") == n
        page.mouse.move(2, 2)
        page.wait_for_timeout(500)
        assert page.evaluate("() => document.querySelectorAll('#diagram .arch-ov-line').length") == 0
        assert not page.js_errors, page.js_errors


def test_a_picked_box_from_its_address_draws_its_lines_over_the_top_with_true_heads() -> None:
    """A box picked by the ADDRESS draws its lines on a crowded picture, as a click does. A line between
    two boxes of one row goes over the top, top to top, rather than out of one's bottom and into the
    other's, through the row below. And every line arrives straight into its box: its last stretch
    points the way its head does."""
    text = make_whole_product_text(make_parts_in_every_layer)
    ends = [x for e in text["lines"] for x in (e["srcBox"], e["dstBox"]) if not x.startswith("CYP")]
    box = max(set(ends), key=ends.count)
    with _served_map(make_parts_in_every_layer) as url, \
            _page(url + f"#v=arch&cap=all&sel=node%3A{box}") as page:
        _settle(page)   # not `_arch_ready`: the text is filtered to this box's steps, so its first line is hidden
        page.wait_for_selector(".arch-ov-line", state="attached")
        page.wait_for_timeout(500)
        seen = page.evaluate("""() => {
            const rect = (id) => { const n = [...document.querySelectorAll('#diagram g.node')].find((x) => x.getAttribute('class').includes('cy-' + id + ' '));
                                   return (n.querySelector('.ibox') || n).getBoundingClientRect(); };
            return [...document.querySelectorAll('.arch-ov-line')].map((l) => {
              const L = l.getTotalLength(), m = l.getScreenCTM(), at = (t) => { const q = l.getPointAtLength(t); return [m.a * q.x + m.e, m.d * q.y + m.f]; };
              const s = rect(l.dataset.src), d = rect(l.dataset.dst), [x0, y0] = at(0), [xa, ya] = at(L - 6), [xz, yz] = at(L);
              return { sameRow: s.top < d.bottom && d.top < s.bottom,
                       fromTop: Math.abs(y0 - s.top) < 2, intoTop: Math.abs(yz - d.top) < 6,
                       steep: Math.abs(yz - ya) > Math.abs(xz - xa) }; }); }""")
        own = sum(1 for e in text["lines"] if box in (e["srcBox"], e["dstBox"]))
        assert len(seen) == own, (box, own, seen)
        assert all(x["steep"] for x in seen), seen
        assert all(x["fromTop"] and x["intoTop"] for x in seen if x["sameRow"]), seen
        assert not page.js_errors, page.js_errors


def test_a_line_up_the_layers_points_the_way_it_runs_and_is_picked_the_way_it_runs() -> None:
    """A line from a lower layer up to a higher one is written the other way round, so the layers stay
    stacked. On screen it keeps one head, at the box it goes to, and a click on it picks the line the
    way it runs."""
    up = [(e["srcBox"], e["dstBox"]) for e in make_whole_product_text(make_one_part_a_screen)["lines"]
          if e.get("up")]
    assert up, "the changed map must draw a line up the layers"
    with _served_map(make_one_part_a_screen) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        seen = page.evaluate("""() => {
            const flipped = [...document.querySelectorAll('#diagram .edgePaths path[data-cy-flip]')];
            return { n: flipped.length,
                     heads: flipped.map((p) => [!!p.getAttribute('marker-start'), !!p.getAttribute('marker-end')]) };
        }""")
        assert seen["n"] == len(up), (seen, up)
        assert all(h == [True, False] for h in seen["heads"]), seen
        # an arrow's invisible click area keeps no head of its own, at either end
        assert page.evaluate("() => document.querySelectorAll('#diagram .cy-edgehit[marker-start], #diagram .cy-edgehit[marker-end]').length") == 0
        page.evaluate("""() => document.querySelector('#diagram .edgePaths path[data-cy-flip]').__cyHits[0]
            .dispatchEvent(new MouseEvent('click', { bubbles: true }))""")
        on = page.evaluate("""() => { const h = decodeURIComponent(location.hash).split('sel=arch:')[1];
            return h ? h.split('&')[0].split('>') : null; }""")
        assert on is not None and tuple(on) in up, (on, up)
        assert not page.js_errors, page.js_errors


def test_a_subsystem_box_counts_its_components_and_its_popup_also_names_their_kinds() -> None:
    """A subsystem's box on a picture says how many components it holds, nested subsystems included,
    the way a subdomain's box counts its entities. The kinds of those components took a lot of the
    box's room for little a reader scanning the picture needs, so only the subsystem's popup and card
    name them, after the same count."""
    read = """() => ({
        box: Object.fromEntries([...document.querySelectorAll('#diagram g.node .ibox[data-id]')].map((b) =>
          [b.dataset.id, [...b.querySelectorAll('.ibox-band .ibox-count')].map((x) => x.textContent)])),
        popup: [...document.querySelectorAll('#panel .pane-card .ibox-band .ibox-count')].map((x) => x.textContent),
    })"""
    with _served_map(make_one_part_a_screen) as url, _page(url + "#v=container&sel=node%3AS4") as page:
        _settle(page)
        seen = page.evaluate(read)
        assert seen["box"]["S5"] == ["21 components"], f"every component under it, nested ones too: {seen}"
        assert seen["box"]["S4"] == ["3 components"], f"the count alone, and no kinds: {seen}"
        assert seen["popup"] == ["3 components", "UI · logic"], f"the same count, then the kinds: {seen}"
        assert not page.js_errors, page.js_errors


def test_a_component_s_kind_is_its_type_pill() -> None:
    """A component's kind ("UI", "logic") stands where its type pill said "component", on its popup
    and on its box, once. A component the map gives no kind still says "component"."""
    read = """() => ({
        popup: [...document.querySelectorAll('#panel .pane-card .ecard-type, #panel .pane-card .ibox-pill')]
          .map((x) => x.textContent),
        box: [...document.querySelectorAll('#diagram g.node .ibox[data-id="C14"] .ibox-pill')].map((x) => x.textContent),
        line: [...document.querySelectorAll('#diagram g.node .ibox[data-id="C14"] .ibox-kindline .ibox-pill')]
          .map((x) => x.textContent),
    })"""
    with _served_map(make_one_part_a_screen) as url, _page(url + "#v=subsystem&sid=S4&sel=node%3AC14") as page:
        _settle(page)
        seen = page.evaluate(read)
        assert seen["popup"] == ["UI"], f"the kind, in place of the word component: {seen}"
        assert seen["box"] == ["UI"], f"the box says the kind once: {seen}"
        assert seen["line"] == ["UI"], f"…on a line of its own, under the name: {seen}"
        assert not page.js_errors, page.js_errors
    with _served() as url, _page(url + "#v=subsystem&sid=S4&sel=node%3AC14") as page:
        _settle(page)
        assert page.evaluate(read)["popup"] == ["component"], "no kind in the map, so the word stays"
        assert not page.js_errors, page.js_errors


def test_a_component_page_shows_its_kind_beside_its_name() -> None:
    """A component's page shows its kind beside its name, the way an actor's page shows "staff"."""
    read = "() => [...document.querySelectorAll('.page-hero-name .ecard-pill')].map((p) => p.textContent)"
    with _served_map(make_one_part_a_screen) as url, _page(url + "#v=element&id=C14") as page:
        _settle(page)
        assert page.evaluate(read) == ["UI"], page.evaluate(read)
        rows = page.evaluate("() => [...document.querySelectorAll('dt')].map((d) => d.textContent)")
        assert "Kind" not in rows, f"the kind is said once, beside the name: {rows}"
        assert not page.js_errors, page.js_errors


def make_one_part_a_widget(m: dict[str, Any]) -> None:
    """The dashboard API router a screen, and one of its neighbours a minted "widget" acting as one."""
    make_one_part_a_screen(m)
    m["component_kinds"] = [{"word": "widget", "meaning": "a piece of a screen", "acts_as": "screen"}]
    for c in m["components"]:
        if c["id"] == "C17":
            c["kind"] = "widget"


def test_a_subsystem_s_popup_lists_the_kinds_in_its_boxes_own_words() -> None:
    """A minted kind ("widget") is listed as itself in its subsystem's popup, the word its box says,
    placed where the known word it acts as goes."""
    with _served_map(make_one_part_a_widget) as url, _page(url + "#v=container&sel=node%3AS4") as page:
        _settle(page)
        popup = page.evaluate("""() => [...document.querySelectorAll('#panel .pane-card .ibox-band .ibox-count')]
            .map((x) => x.textContent)""")
        assert popup == ["3 components", "UI · widget · logic"], popup
        assert not page.js_errors, page.js_errors


def test_a_use_case_map_draws_no_start_or_end_mark() -> None:
    """The start circle and end bar belong to a story followed on the Architecture view only."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        _settle(page)
        assert page.evaluate("() => document.querySelectorAll('#diagram g.node').length") > 0
        assert page.evaluate("() => document.querySelectorAll('.ucm-mark').length") == 0
        assert not page.js_errors, page.js_errors


_PICTURES_SHARING_THE_DRAWING_CODE = ["#v=container", "#v=usecase&uc=UC1", "#v=domain", "#v=subsystem&sid=S1"]


def _lit_label_near_its_line(page: Any) -> dict[str, Any]:
    """Hover each line's hit area in turn and report, per line, how many labels light with it and how far
    the lit label sits from the line. Run in the page: the pairing lives in the drawing."""
    return dict(page.evaluate("""() => {
        const lit = (el) => !!(el && el.style && el.style.filter);
        const labels = [...document.querySelectorAll('#diagram .edgeLabels > g.edgeLabel')];
        const paths = [...document.querySelectorAll('#diagram .edgePaths path.flowchart-link')];
        const out = { checked: 0, wrong: [] };
        // A pointer that has not moved since the drawing appeared is not hovering (`holdPointer`): move it once.
        for (const t of ['pointermove', 'mousemove'])
          document.dispatchEvent(new MouseEvent(t, { clientX: 1, clientY: 1, bubbles: true }));
        for (const hit of [...document.querySelectorAll('#diagram .cy-edgehit')].slice(0, 12)) {
          hit.dispatchEvent(new MouseEvent('mouseenter'));
          const on = labels.filter((l) => lit(l) && (l.textContent || '').trim());
          const path = paths.find(lit);
          hit.dispatchEvent(new MouseEvent('mouseleave'));
          if (!path || !on.length) continue;          // a line with no words has no label to light
          out.checked += 1;
          // How far the lit label's centre is from the lit line, in screen pixels.
          const r = on[0].getBoundingClientRect(), cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
          const m = path.getScreenCTM(), len = path.getTotalLength();
          let best = Infinity;
          for (let i = 0; i <= 60; i++) {
            const q = path.getPointAtLength(len * i / 60);
            const x = m.a * q.x + m.c * q.y + m.e, y = m.b * q.x + m.d * q.y + m.f;
            best = Math.min(best, Math.hypot(x - cx, y - cy));
          }
          if (on.length !== 1 || best > 30) out.wrong.push({ labels: on.length, text: on[0].textContent.trim(), px: Math.round(best) });
        }
        return out;
    }"""))


@pytest.mark.parametrize("where", _PICTURES_SHARING_THE_DRAWING_CODE)
def test_on_every_picture_a_line_lights_its_own_label(where: str) -> None:
    """The line code every picture shares (eachEdge, attachEdgeHandlers) was reshaped for the Architecture
    picture's reversed lines. On every other picture, hovering a line must still light one label, its own:
    the one sitting on that line."""
    with _served() as url, _page(url + where) as page:
        _settle(page)
        seen = _lit_label_near_its_line(page)
        assert seen["checked"] >= 1, f"no labelled line was hovered, so this proved nothing: {seen}"
        assert not seen["wrong"], seen
        assert not page.js_errors, page.js_errors


@pytest.mark.parametrize("where", _PICTURES_SHARING_THE_DRAWING_CODE)
def test_on_every_picture_a_box_selects_and_shows_itself(where: str) -> None:
    """The box code every picture shares (bindNodes) learnt that a box may stand for another element, for
    the Architecture picture's groups of parts. On every other picture a box still stands for itself: a
    click on its edge selects it, and the card that appears is that box's own."""
    with _served() as url, _page(url + where) as page:
        _settle(page)
        # A PERSON's figure stands for that person under an id of the picture's own, by design; every
        # other box is drawn under its element's id.
        boxes = page.evaluate("""() => [...document.querySelectorAll('#diagram g.node')]
            .map((n) => [n, n.querySelector('.ibox[data-id]')]).filter(([n, b]) => b && n.id.includes(b.dataset.id))
            .map(([, b]) => b).filter((b) => { const r = b.getBoundingClientRect();
              return r.left > 0 && r.top > 0 && r.right < innerWidth - 40 && r.bottom < innerHeight; }).slice(0, 3)
            .map((b) => { const r = b.getBoundingClientRect(); return { id: b.dataset.id, x: r.left + 3, y: r.top + 3 }; })""")
        assert boxes, "no box to click on this picture"
        for b in boxes:
            # A FRESH picture per box: the previous box's popup can sit over the next one. The box is
            # measured again there, since a fresh picture can be fitted differently.
            page.goto(url + where.replace("#", "?fresh=" + b["id"] + "#"))
            _settle(page)
            b = page.evaluate("""(id) => { const r = document.querySelector(`#diagram .ibox[data-id="${id}"]`)
                .getBoundingClientRect(); return { id, x: r.left + 3, y: r.top + 3 }; }""", b["id"])
            page.mouse.click(b["x"], b["y"])
            page.wait_for_timeout(500)
            seen = page.evaluate("""() => ({ hash: location.hash,
                card: (document.querySelector('#panel .pane-card [data-id]') || {}).dataset?.id || '' })""")
            assert f"node%3A{b['id']}" in seen["hash"], (b, seen)
            assert seen["card"] == b["id"], (b, seen)
        assert not page.js_errors, page.js_errors


def test_no_story_is_followed_on_the_architecture_picture() -> None:
    """Following one story on the picture is gone: an old link that named a story opens the plain
    picture, drops the story from the address, and marks no start or end."""
    with _served() as url, _page(url + "#v=arch&story=UC1") as page:
        _arch_ready(page)
        seen = page.evaluate("""() => ({ story: location.hash.includes('story='),
            marks: document.querySelectorAll('#diagram .ucm-mark').length,
            lit: document.querySelectorAll('#diagram .arch-story-on').length })""")
        assert seen == {"story": False, "marks": 0, "lit": 0}, seen
        assert not page.js_errors, page.js_errors


def test_picking_a_feature_on_the_architecture_view_moves_no_button() -> None:
    """The button in force is marked without changing its width, so picking one leaves every button
    where it was."""
    where = "() => [...document.querySelectorAll('.archwho')].map((b) => Math.round(b.getBoundingClientRect().left))"
    with _served() as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        before = page.evaluate(where)
        page.evaluate("() => document.querySelectorAll('.archwho')[1].click()")
        page.wait_for_function("() => !location.hash.includes('cap=all')")
        _arch_ready(page)
        after = page.evaluate(where)
        assert after[:len(before)] == before, (before, after)
        assert not page.js_errors, page.js_errors


def test_a_line_drawn_on_a_crowded_picture_passes_behind_the_boxes_it_crosses() -> None:
    """A line drawn on top of a crowded picture is cut out where it crosses a box other than its two
    ends: it passes behind the box, and the box, not the line, answers the pointer there."""
    text = make_whole_product_text(make_parts_in_every_layer)
    ends = [x for e in text["lines"] for x in (e["srcBox"], e["dstBox"]) if not x.startswith("CYP")]
    over = """() => { let n = 0; const boxes = [...document.querySelectorAll('#diagram g.node')];
      for (const l of document.querySelectorAll('.arch-ov-line')) { const L = l.getTotalLength(), m = l.getScreenCTM();
        for (const b of boxes) { const c = [...b.classList].find((x) => x.startsWith('cy-')); if (!c) continue;
          if (c.slice(3) === l.dataset.src || c.slice(3) === l.dataset.dst) continue;
          const r = (b.querySelector('.ibox') || b).getBoundingClientRect();
          for (let k = 1; k < 60; k++) { const q = l.getPointAtLength(L * k / 60), x = m.a * q.x + m.e, y = m.d * q.y + m.f;
            if (x > r.left + 4 && x < r.right - 4 && y > r.top + 4 && y < r.bottom - 4) {
              const e = document.elementFromPoint(x, y);
              if (e && (e.classList.contains('arch-ov-hit') || e.classList.contains('arch-ov-line'))) n++;
              break; } } } }
      return n; }"""
    with _served_map(make_parts_in_every_layer) as url, _page(url) as page:
        for box in sorted(set(ends), key=ends.count, reverse=True)[:6]:
            page.goto(url + f"#v=arch&cap=all&sel=node%3A{box}")
            page.reload()
            _settle(page)
            page.wait_for_selector(".arch-ov-line", state="attached")
            assert page.evaluate(over) == 0, box
        assert not page.js_errors, page.js_errors


# ── From the independent review of 2026-10-02: each of these failed on 03ee2656 ──────────────────

# Points inside boxes that a click or a rest lands on: inside the box, clear of its name and tags.
BOX_POINTS = """() => { const d = document.getElementById('diagram').getBoundingClientRect(); const out = [];
  for (const n of document.querySelectorAll('#diagram g.node')) {
    const id = [...n.classList].find((c) => c.startsWith('cy-')); if (!id || id.startsWith('cy-CYP')) continue;
    const b = n.querySelector('.ibox') || n; const r = b.getBoundingClientRect();
    let hit = null;
    for (let y = Math.min(r.bottom, d.bottom) - 3; y > Math.max(r.top, d.top) && !hit; y -= 3)
      for (let x = Math.min(r.right, d.right) - 3; x > Math.max(r.left, d.left) && !hit; x -= 3) {
        const e = document.elementFromPoint(x, y);
        if (e && b.contains(e) && !e.closest('button, a, .ibox-name, .item-pill')) hit = { x, y };
      }
    if (hit) out.push({ id: id.slice(3), ...hit });
  }
  return out; }"""
# A point on a drawn-on-top line that the line itself answers, clear of both cards.
LINE_POINT = """() => { const d = document.getElementById('diagram').getBoundingClientRect();
  const cards = ['#panel', '#peekcard'].map((s) => document.querySelector(s)).filter((c) => !c.hidden).map((c) => c.getBoundingClientRect());
  const free = (x, y) => !cards.some((r) => x > r.left - 4 && x < r.right + 4 && y > r.top - 4 && y < r.bottom + 4);
  for (const l of document.querySelectorAll('.arch-ov-line')) { const L = l.getTotalLength(), m = l.getScreenCTM();
    for (const f of [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8]) { const q = l.getPointAtLength(L * f);
      const x = m.a * q.x + m.c * q.y + m.e, y = m.b * q.x + m.d * q.y + m.f; const e = document.elementFromPoint(x, y);
      if (x > d.left && x < d.right && y > d.top && y < d.bottom && free(x, y) && e && e.classList.contains('arch-ov-hit'))
        return { x, y, src: l.dataset.src, dst: l.dataset.dst }; } }
  return null; }"""
DRAWN = "() => [...document.querySelectorAll('#diagram .arch-overlay .arch-ov-line')].map((l) => [l.dataset.src, l.dataset.dst])"
PICKED = "() => [...document.querySelectorAll('#diagram .arch-ov-line.arch-ov-picked')].map((l) => [l.dataset.src, l.dataset.dst])"


def _rest(page: Any, at: dict[str, Any], ms: int = 700) -> None:
    page.mouse.move(at["x"] - 2, at["y"], steps=3)
    page.mouse.move(at["x"], at["y"], steps=3)
    page.wait_for_timeout(ms)


def test_moving_from_one_box_to_the_next_keeps_the_next_boxs_lines() -> None:
    """Resting on box A draws A's lines; moving to box B and resting there draws B's lines, and they
    stay while the pointer rests on B (on the branch they show for ~30 ms, then go)."""
    with _served_map(make_parts_in_every_layer) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        boxes = page.evaluate(BOX_POINTS)
        a, b = boxes[0], boxes[1]
        page.mouse.move(2, 2)
        _rest(page, a)
        assert page.evaluate(DRAWN), "resting on the first box draws its lines"
        _rest(page, b, 900)
        drawn = page.evaluate(DRAWN)
        assert drawn and all(b["id"] in pair for pair in drawn), (b["id"], drawn)
        assert not page.js_errors, page.js_errors


def test_a_line_picked_from_a_preview_stays_drawn_when_the_pointer_leaves() -> None:
    """Rest on a box, click one of its lines: the line is picked. Moving the pointer away must not take
    the picked line off the picture while its card stays open."""
    with _served_map(make_parts_in_every_layer) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        page.mouse.move(2, 2)
        for b in page.evaluate(BOX_POINTS):
            _rest(page, b)
            if page.evaluate(DRAWN):
                break
        at = page.evaluate(LINE_POINT)
        assert at, "no line of the rested box on screen"
        page.mouse.move(at["x"], at["y"], steps=8)
        page.wait_for_timeout(300)
        page.mouse.click(at["x"], at["y"])
        page.wait_for_timeout(600)
        assert "sel=arch" in page.evaluate("() => decodeURIComponent(location.hash)")
        page.mouse.move(2, 300, steps=6)
        page.wait_for_timeout(900)
        assert page.evaluate(PICKED) == [[at["src"], at["dst"]]], "the picked line left the picture"
        assert not page.js_errors, page.js_errors


def test_a_picked_line_of_a_crowded_picture_survives_a_reload() -> None:
    """The address names the picked line; a reload, a shared link or Back must bring back its card and
    draw it lit (on the branch the pick is dropped from the address)."""
    text = make_whole_product_text(make_parts_in_every_layer)
    e = text["lines"][0]
    with _served_map(make_parts_in_every_layer) as url, _page(url) as page:
        page.goto(url + f"#v=arch&cap=all&sel=arch%3A{e['srcBox']}%3E{e['dstBox']}")
        page.reload()
        _arch_ready(page)
        _settle(page)
        seen = page.evaluate("""() => ({ hash: decodeURIComponent(location.hash),
            title: (document.querySelector('#panel .pane-title h2') || {}).textContent || '' })""")
        assert f"sel=arch:{e['srcBox']}>{e['dstBox']}" in seen["hash"], seen
        assert seen["title"] == f"{e['src']} → {e['dst']}", seen
        assert page.evaluate(PICKED) == [[e["srcBox"], e["dstBox"]]]
        assert not page.js_errors, page.js_errors


def test_picking_a_box_again_after_one_of_its_lines_draws_its_lines() -> None:
    """Box picked, then one of its lines, then the box again: the box is picked, so its lines are drawn
    (on the branch they are toggled off)."""
    text = make_whole_product_text(make_parts_in_every_layer)
    ends = [x for e in text["lines"] for x in (e["srcBox"], e["dstBox"]) if not x.startswith("CYP")]
    box = max(set(ends), key=ends.count)
    with _served_map(make_parts_in_every_layer) as url, _page(url + f"#v=arch&cap=all&sel=node%3A{box}") as page:
        _settle(page)
        page.wait_for_selector(".arch-ov-hit", state="attached")
        n = len(page.evaluate(DRAWN))
        at = page.evaluate(LINE_POINT)
        assert at, "no line of the picked box on screen"
        page.mouse.move(at["x"], at["y"], steps=4)
        page.mouse.click(at["x"], at["y"])
        page.wait_for_timeout(600)
        spot = next((b for b in page.evaluate(BOX_POINTS) if b["id"] == box), None)
        assert spot, "the box's body is not on screen"
        page.mouse.move(spot["x"], spot["y"], steps=6)
        page.mouse.click(spot["x"], spot["y"])
        page.wait_for_timeout(700)
        assert f"sel=node:{box}" in page.evaluate("() => decodeURIComponent(location.hash)")
        assert len(page.evaluate(DRAWN)) == n, "the box is picked but its lines are not drawn"
        assert not page.js_errors, page.js_errors


def make_repeated_step(m: dict[str, Any]) -> None:
    """The first use case takes its second step's arrow again, as its last step."""
    steps = m["flows"][0]["steps"]
    again = dict(steps[1])
    again["n"] = max(int(s["n"]) for s in steps) + 1
    steps.append(again)


def test_letting_go_of_two_steps_on_one_arrow_puts_the_arrow_back() -> None:
    """A line's card opens a use case with every step the line draws selected, and two of them can sit
    on one arrow of the use case map. Letting go must leave no arrow blue, thick or with a blue head."""
    with _served_map(make_repeated_step) as url, _page(url) as page:
        pick = page.evaluate("""async () => { const b = await fetch('api/view').then((r) => r.json());
            for (const [uc, steps] of Object.entries(b.flowsNarr)) {
              const seen = {};
              for (let i = 0; i < steps.length; i++) { const s = steps[i];
                const k = (s.srcId || s.src) + '>' + (s.sf || s.dstId || s.dst);
                if (k in seen) return { uc, i: seen[k], j: i }; seen[k] = i; } }
            return null; }""")
        assert pick, "the fixture has no use case with two steps on one arrow"
        uc, i, j = pick["uc"], pick["i"], pick["j"]
        page.goto(url + f"#v=usecase&uc={uc}&sel=flowstep%3A{uc}%3A{i}&sel=flowstep%3A{uc}%3A{j}")
        page.reload()
        page.wait_for_selector("#crumb h1", state="attached")
        _settle(page)
        assert page.evaluate("() => document.querySelectorAll('#diagram .flow-step-picked').length") == 2
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        left = page.evaluate("""() => [...document.querySelectorAll('#diagram .edgePaths path.flowchart-link')]
            .filter((p) => p.style.getPropertyValue('stroke') || /cypicked/.test((p.getAttribute('marker-end') || '') + (p.getAttribute('marker-start') || '')))
            .map((p) => p.id)""")
        assert not left, left
        assert not page.js_errors, page.js_errors


def make_two_people_at_one_page(m: dict[str, Any]) -> None:
    """The picture tests' small map (interfaces and people), with a Visitor who uses the same web page
    in a use case of a second feature."""
    from test_architecture_view import make_arch_map
    doc = make_arch_map()
    doc["roles"].append({"id": "R3", "name": "Visitor", "kind": "human", "audience": "user", "wants": "z",
                         "drives": "UC3"})
    doc["capabilities"].append({"id": "CAP2", "name": "Looking around", "purpose": "looks",
                                "happy_path": "excluded", "story": {"place": "after", "feature": "CAP1"}})
    doc["use_cases"].append({"id": "UC3", "name": "Look at a thing", "actors": ["R3"], "capability": "CAP2",
                             "trigger": "The visitor looks.", "outcome": "The visitor has seen it."})
    doc["flows"].append({"uc": "UC3", "title": "Look at a thing", "steps": [
        {"n": 1, "src": "R3", "dst": "I1", "phrase": "open the page"},
        {"n": 2, "src": "I1", "dst": "C1", "phrase": "show the thing", "where": "src/page.ts:3"},
        {"n": 3, "src": "I1", "dst": "R3", "phrase": "present the thing"}]})
    m.clear()
    m.update(doc)


def test_an_interfaces_card_drops_only_the_people_this_picture_joins_to_it() -> None:
    """An interface's card on the Architecture picture drops a person only when the picture draws a line
    from that person to the interface. On one feature's picture the other feature's Visitor keeps their
    tag; on the whole product both are joined and both go; a use case map keeps every one."""
    people = """() => { const c = document.querySelector('#panel .ecard'); return c ? [...c.querySelectorAll('.item-pill')]
        .filter((p) => ['human', 'service', 'ai-agent'].includes(p.dataset.kind)).map((p) => p.textContent.trim()).sort() : null; }"""
    with _served_map(make_two_people_at_one_page) as url, _page(url) as page:
        for address, want in (("#v=arch&cap=CAP1&sel=node%3AI1", ["Visitor"]),
                              ("#v=arch&cap=all&sel=node%3AI1", []),
                              ("#v=usecase&uc=UC1&sel=node%3AI1", ["Admin", "Visitor"])):
            page.goto(url + address)
            page.reload()
            _settle(page)
            page.wait_for_selector("#panel .ecard", state="attached")
            assert page.evaluate(people) == want, (address, page.evaluate(people))
        assert not page.js_errors, page.js_errors


def test_the_zoom_number_reads_100_where_each_view_opens_and_after_a_click_on_it() -> None:
    """100% is where a view opens, whatever the stage did after its first fit, and a click on the number
    (a fit) reads 100% again."""
    with _served() as url, _page(url) as page:
        for view in ("#v=arch", "#v=container", "#v=context", "#v=deployment", "#v=usecase&uc=UC1"):
            page.goto(url + view)
            page.reload()
            _settle(page)
            page.wait_for_timeout(500)
            level = "() => document.getElementById('zoomlevel').textContent"
            assert page.evaluate(level) == "100%", (view, page.evaluate(level))
            page.click("#zoomin")
            page.wait_for_timeout(300)
            assert page.evaluate(level) != "100%", view
            page.click("#zoomlevel")
            page.wait_for_timeout(700)
            assert page.evaluate(level) == "100%", (view, page.evaluate(level))
        assert not page.js_errors, page.js_errors


def test_the_happy_path_switch_is_only_on_a_feature_with_a_happy_path_picture() -> None:
    """A feature none of whose use cases is on the happy path has no switch, and an address asking for
    its happy path draws the feature whole. A stale happy path in the whole product's address does not
    switch the next feature on."""
    drawings = gen_arch_views(model_to_graph(load_model(_FIXTURE_MAP.read_text())))[0]
    assert "happy|" not in drawings, "the whole product has no happy-path picture"
    bare = next(k.split("|")[1] for k in drawings if k.startswith("all|CAP") and "happy|" + k.split("|")[1] not in drawings)
    seen = """() => ({ hidden: document.getElementById('archhp').hidden,
        on: (document.querySelector('.archwho.on') || { dataset: {} }).dataset.archcap })"""
    with _served() as url, _page(url) as page:
        for address in (f"#v=arch&cap={bare}", f"#v=arch&cap={bare}&scope=happy"):
            page.goto(url + address)
            page.reload()
            _arch_ready(page)
            assert page.evaluate(seen) == {"hidden": True, "on": bare}, (address, page.evaluate(seen))
        page.goto(url + "#v=arch&cap=all&scope=happy")
        page.reload()
        _arch_ready(page)
        page.evaluate("() => document.querySelectorAll('.archwho')[1].click()")
        page.wait_for_function("() => !location.hash.includes('cap=all')")
        assert "scope=happy" not in page.evaluate("() => location.hash")
        assert not page.js_errors, page.js_errors


def test_a_click_on_an_arrows_label_points_the_card_at_the_label() -> None:
    """The label answers for its arrow: a click on it points the card's line at it, not at a point an
    earlier hover left on the arrow."""
    with _served() as url, _page(url + "#v=container") as page:
        _settle(page)
        spots = page.evaluate("""() => { const d = document.getElementById('diagram').getBoundingClientRect();
            const labels = [...document.querySelectorAll('#diagram .edgeLabels > g.edgeLabel')];
            const paths = [...document.querySelectorAll('#diagram .edgePaths path.flowchart-link')];
            for (let i = 0; i < paths.length; i++) { const p = paths[i], l = labels[i];
              if (!l || !l.textContent.trim() || !p.__cyHits) continue;
              const r = l.getBoundingClientRect(), lx = (r.left + r.right) / 2, ly = (r.top + r.bottom) / 2;
              const L = p.getTotalLength(), m = p.getScreenCTM(), q = p.getPointAtLength(L * 0.15);
              const hx = m.a * q.x + m.c * q.y + m.e, hy = m.b * q.x + m.d * q.y + m.f;
              const inside = (x, y) => x > d.left && x < d.right && y > d.top && y < d.bottom;
              const he = document.elementFromPoint(hx, hy), le = document.elementFromPoint(lx, ly);
              if (Math.hypot(hx - lx, hy - ly) > 60 && inside(hx, hy) && inside(lx, ly)
                  && he && p.__cyHits.includes(he) && le && l.contains(le)) return { hx, hy, lx, ly }; }
            return null; }""")
        assert spots, "no labelled arrow with room between its label and its start"
        page.mouse.move(spots["hx"] - 2, spots["hy"])
        page.mouse.move(spots["hx"], spots["hy"])
        page.wait_for_timeout(300)
        page.mouse.move(2, 2, steps=4)
        page.mouse.click(spots["lx"], spots["ly"])
        page.wait_for_timeout(800)
        dot = page.evaluate("""() => { const c = document.querySelector('#callout .co-dot'), w = document.getElementById('diagwrap').getBoundingClientRect();
            return c ? { x: +c.getAttribute('cx') + w.left, y: +c.getAttribute('cy') + w.top } : null; }""")
        assert dot and abs(dot["x"] - spots["lx"]) < 15 and abs(dot["y"] - spots["ly"]) < 15, (dot, spots)
        assert not page.js_errors, page.js_errors


def test_a_picked_arrows_head_turns_with_it_and_comes_back() -> None:
    """A picked arrow's head takes the arrow's blue, and letting go puts the head the drawing gave it
    back; on a crowded picture's drawn-on-top line too."""
    with _served() as url, _page(url + "#v=container") as page:
        _settle(page)
        before = page.evaluate("""() => { const p = [...document.querySelectorAll('#diagram .edgePaths path.flowchart-link')]
            .find((x) => x.__cyHits && x.getAttribute('marker-end'));
            window.__probe = p; return p.getAttribute('marker-end'); }""")
        page.evaluate("() => window.__probe.__cyHits[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))")
        page.wait_for_timeout(300)
        picked = page.evaluate("""() => { const m = window.__probe.getAttribute('marker-end');
            const head = document.querySelector(m.slice(4, -1)); return [m, head ? getComputedStyle(head.querySelector('path')).fill : '']; }""")
        assert picked[0].endswith("-cypicked)") and picked[1] == "rgb(37, 99, 235)", picked
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        assert page.evaluate("() => window.__probe.getAttribute('marker-end')") == before
    text = make_whole_product_text(make_parts_in_every_layer)
    ends = [x for e in text["lines"] for x in (e["srcBox"], e["dstBox"]) if not x.startswith("CYP")]
    box = max(set(ends), key=ends.count)
    with _served_map(make_parts_in_every_layer) as url, _page(url + f"#v=arch&cap=all&sel=node%3A{box}") as page:
        _settle(page)
        page.wait_for_selector(".arch-ov-hit", state="attached")
        page.evaluate("() => document.querySelector('#diagram .arch-ov-hit').dispatchEvent(new MouseEvent('click', { bubbles: true }))")
        page.wait_for_timeout(300)
        assert page.evaluate("() => document.querySelector('.arch-ov-line.arch-ov-picked').getAttribute('marker-end')") == "url(#arch-ov-head-picked)"
        assert not page.js_errors, page.js_errors


def test_a_use_case_maps_step_badges_are_whole_on_their_arrows() -> None:
    """A step badge is bigger than the box the drawing engine sized for the old text, and is drawn whole:
    the pointer meets the badge itself just inside each of its four edges. Clipped to that box, the
    top and bottom of every one-digit badge went missing."""
    with _served() as url, _page(url + "#v=usecase&uc=UC1") as page:
        _settle(page)
        seen = page.evaluate("""() => [...document.querySelectorAll('#diagram .flow-step-num[data-fstep]')].map((n) => {
            const r = n.getBoundingClientRect(), cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
            const on = (x, y) => { const e = document.elementFromPoint(x, y); return !!e && (e === n || n.contains(e)); };
            return { h: n.offsetHeight, edges: [on(r.left + 2, cy), on(r.right - 2, cy), on(cx, r.top + 2), on(cx, r.bottom - 2)]
                .filter(Boolean).length }; })""")
        assert len(seen) >= 5 and all(x["h"] == 17 for x in seen), seen
        assert sum(1 for x in seen if x["edges"] == 4) >= len(seen) - 1, seen   # one sits under a box
        assert not page.js_errors, page.js_errors


def make_a_feature_named_by_a_glossary_term(m: dict[str, Any]) -> None:
    """A glossary term that the first feature's name contains, so a card naming that feature can link it."""
    m["glossary"].append({"term": "teams", "meaning": "the groups an organization is made of", "source": "README.md:1"})


def test_a_line_cards_feature_rows_carry_no_glossary_link() -> None:
    """A feature row on a line's card opens and closes on a click, so a glossary link inside it took the
    click away. The card's other text still links its terms."""
    with _served_map(make_a_feature_named_by_a_glossary_term) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        # The links are put in after the card is written (a watcher on the page), so each card is read
        # a moment after its click.
        seen = page.evaluate("""async () => { const out = [];
            for (const p of [...document.querySelectorAll('#diagram .edgePaths path.flowchart-link')].filter((x) => x.__cyHits)) {
              p.__cyHits[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
              await new Promise((r) => setTimeout(r, 50));
              const rows = [...document.querySelectorAll('#panel .archuc-feat > summary')];
              if (rows.some((r) => /teams/i.test(r.textContent)))
                out.push({ inRows: document.querySelectorAll('#panel summary .gloss-link').length,
                           all: document.querySelectorAll('#panel .gloss-link').length }); }
            return out; }""")
        assert seen and all(x["inRows"] == 0 for x in seen), seen
        assert any(x["all"] for x in seen), "the card's other text links its terms"
        assert not page.js_errors, page.js_errors


# A POINT ON EACH BOX'S OWN BODY that the box itself answers for, clear of its name, its tags and its
# buttons, and inside the drawing: where a reader rests the pointer to see that box's card.
BOX_BODIES = """() => { const d = document.getElementById('diagram').getBoundingClientRect(); const out = [];
  for (const n of document.querySelectorAll('#diagram g.node')) { const r = n.getBoundingClientRect();
    for (let y = r.top + 6; y < r.bottom - 2; y += 3) { let hit = null;
      for (let x = r.right - 4; x > r.left + 2; x -= 3) { const e = document.elementFromPoint(x, y);
        if (x > d.left && x < d.right && y > d.top && y < d.bottom && e && n.contains(e)
            && !e.closest('button, a, .ibox-name, .cyname, .item-pill')) { hit = { x, y }; break; } }
      if (hit) { out.push({ id: n.id, ...hit }); break; } } }
  return out; }"""


def _sized_page(url: str, width: int, height: int) -> Any:
    """`_page` at a screen size of its own, set before the first drawing: a size set afterwards keeps
    the camera the first one chose."""
    page = new_page()
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url)
    page.wait_for_selector("#crumb h1", state="attached")
    _settle(page)
    return page


def _pick_then_rest_on(page: Any, a: dict[str, Any], b: dict[str, Any]) -> None:
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    page.mouse.move(a["x"], a["y"], steps=3)
    page.mouse.click(a["x"], a["y"])
    page.wait_for_timeout(450)
    page.mouse.move(b["x"] - 1, b["y"])
    page.mouse.move(b["x"], b["y"])
    page.wait_for_timeout(450)


def test_the_second_card_never_lands_on_the_main_card_or_on_the_box_under_the_pointer() -> None:
    """With no free place, the last resort pushed the second card inside the drawing whatever it covered:
    the main card and its ×, or the very box the pointer rested on, so a click on that box landed on the
    card. It goes beside the main card instead, or with no room there it is not shown."""
    seen = """([x, y]) => { const p = document.getElementById('peekcard'), m = document.getElementById('panel');
        const a = p.getBoundingClientRect(), b = m.getBoundingClientRect(), e = document.elementFromPoint(x, y);
        return { shown: !p.hidden, placed: p.dataset.placed, under: !!e && p.contains(e),
                 onMain: !p.hidden && !m.hidden && !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top) }; }"""
    with _served() as url:
        for frag, (w, h) in [("#v=container", (800, 560)), ("#v=arch", (1280, 720))]:
            page = _sized_page(url + frag, w, h)
            try:
                boxes = page.evaluate(BOX_BODIES)
                assert len(boxes) >= 3, (frag, boxes)
                res = []
                for b in boxes[1:]:
                    _pick_then_rest_on(page, boxes[0], b)
                    res.append(page.evaluate(seen, [b["x"], b["y"]]))
                assert not any(r["onMain"] or r["under"] for r in res), (frag, res)
                # the case is met: some hover had no free place, and went beside the main card or away
                assert any(r["placed"] == "beside" or not r["shown"] for r in res), (frag, res)
                assert not page.js_errors, page.js_errors
            finally:
                page.close()


def test_where_no_place_clears_a_boxs_lines_its_card_lies_on_the_fewest() -> None:
    """The card of a picked box keeps clear of the lines drawn for it. Where no place clears all of them,
    it takes the place covering the fewest; giving them up all at once let it lie on a quarter of them."""
    covered = """() => { const c = document.getElementById('panel'), r = c.getBoundingClientRect(); let n = 0, all = 0;
        for (const l of document.querySelectorAll('#diagram .arch-ov-line')) { const L = l.getTotalLength(), m = l.getScreenCTM();
          for (let s = 0; s <= L; s += 6) { const q = l.getPointAtLength(s), x = m.a * q.x + m.c * q.y + m.e, y = m.b * q.x + m.d * q.y + m.f;
            all++; if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) n++; } }
        return { covered: n, all, placed: c.dataset.placed, shown: !c.hidden }; }"""
    with _served_map(make_parts_in_every_layer) as url:
        page = _sized_page(url + "#v=arch&cap=all", 1280, 720)
        try:
            _arch_ready(page)
            res = []
            for b in [b for b in page.evaluate(BOX_BODIES) if "CYP" not in b["id"]]:
                page.mouse.move(b["x"], b["y"], steps=3)
                page.mouse.click(b["x"], b["y"])
                page.wait_for_timeout(600)
                res.append(page.evaluate(covered))
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
            tight = [r for r in res if r["shown"] and r["placed"] == "1"]   # no place cleared every line
            assert tight, res
            assert all(r["covered"] <= r["all"] * 0.15 for r in tight), tight
            assert not page.js_errors, page.js_errors
        finally:
            page.close()


def test_a_picture_drawn_again_under_a_resting_pointer_previews_nothing() -> None:
    """"+N more" draws the picture again, and the box it opened lands under a pointer that has not moved.
    That is not a hover: no lines are drawn until the pointer moves, and then they are."""
    more = """() => { const d = document.getElementById('diagram').getBoundingClientRect();
      for (const b of document.querySelectorAll('#diagram .ibox-more')) { const r = b.getBoundingClientRect();
        const x = (r.left + r.right) / 2, y = (r.top + r.bottom) / 2, e = document.elementFromPoint(x, y);
        if (x > d.left && x < d.right && y > d.top && y < d.bottom && e && b.contains(e)) return { x, y }; }
      return null; }"""
    lines = "() => document.querySelectorAll('#diagram .arch-ov-line').length"
    with _served_map(make_parts_in_every_layer) as url:
        page = _sized_page(url + "#v=arch&cap=all", 1600, 1300)
        try:
            _arch_ready(page)
            at = page.evaluate(more)
            assert at, "a box's \"+N more\" on screen"
            page.mouse.move(at["x"] - 2, at["y"])
            page.mouse.move(at["x"], at["y"])
            page.wait_for_timeout(500)
            page.mouse.click(at["x"], at["y"])
            page.wait_for_timeout(1500)
            assert "open=" in page.evaluate("() => decodeURIComponent(location.hash)")
            assert page.evaluate(lines) == 0
            page.mouse.move(at["x"] + 6, at["y"] + 6)   # a jitter under 2 px is not a move
            page.wait_for_timeout(600)
            assert page.evaluate(lines) > 0, "a move is a hover, and previews the box under the pointer"
            assert not page.js_errors, page.js_errors
        finally:
            page.close()


def make_one_use_case_with_no_words(m: dict[str, Any]) -> None:
    """UC1's steps say nothing: a step with no words still draws its line."""
    for f in m["flows"]:
        if f["uc"] == "UC1":
            for st in f["steps"]:
                st["phrase"] = ""


def test_a_use_case_whose_step_has_no_words_is_still_on_the_lines_card() -> None:
    """A line's card lists every use case whose steps the line draws. One whose step had no sentence was
    left off, while the line was drawn for it."""
    text = make_whole_product_text(make_one_use_case_with_no_words)
    quiet = [e for e in text["lines"] if "UC1" in e["steps"]]
    assert quiet and all("UC1" not in x["ucs"] for e in quiet for x in e["sentences"]), "UC1 says nothing on its lines"
    with _served_map(make_one_use_case_with_no_words) as url, _page(url + "#v=arch&cap=all") as page:
        _arch_ready(page)
        seen = page.evaluate("""() => [...document.querySelectorAll('#diagram .edgePaths path.flowchart-link')]
          .filter((p) => p.__cyHits && p.__cyHits.length).map((p) => {
            p.__cyHits[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
            const [src, dst] = decodeURIComponent(location.hash).split('sel=arch:')[1].split('&')[0].split('>');
            return { src, dst, ucs: [...document.querySelectorAll('#panel .archuc-name[data-ucopen]')].map((b) => b.dataset.ucopen) }; })""")
        by = {(r["src"], r["dst"]): r["ucs"] for r in seen}
        for e in quiet:
            assert "UC1" in by[(e["srcBox"], e["dstBox"])], (e["srcBox"], e["dstBox"], by[(e["srcBox"], e["dstBox"])])
        assert not page.js_errors, page.js_errors


def test_picking_what_the_second_card_shows_keeps_its_contents_in_place_near_the_drawings_top() -> None:
    """The second card leaves room above it for the main card's bar: picking what it shows puts the main
    card in its place, standing higher by that bar. Against the drawing's top edge it could not, and the
    contents dropped by the bar's height (on this picture, the second card of the first person's
    neighbour stood 16 px from the top)."""
    name = """(c) => { const e = document.querySelector(c); if (e.hidden) return null;
        const b = e.querySelector('.ibox-name').getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top)]; }"""
    with _served() as url:
        page = _sized_page(url + "#v=arch", 1280, 720)
        try:
            boxes = page.evaluate(BOX_BODIES)
            moved, shown = [], 0
            for b in boxes[1:]:
                _pick_then_rest_on(page, boxes[0], b)
                before = page.evaluate(name, "#peekcard")
                if not before:
                    continue
                shown += 1
                page.mouse.click(b["x"], b["y"])
                page.wait_for_timeout(700)
                after = page.evaluate(name, "#panel")
                if after != before:
                    moved.append((b["id"], before, after))
            assert shown >= 4 and not moved, (shown, moved)
            assert not page.js_errors, page.js_errors
        finally:
            page.close()


def make_committed_sources(coyomap_dir: Path) -> None:
    """The project beside the map as a git repository holding every file the map points at, and the map
    pinned to that commit: the file browser lists files only from git, at the map's commit."""
    root = coyomap_dir.parent
    f = coyomap_dir / "project-map.json"
    m = json.loads(f.read_text())
    paths = sorted(set(re.findall(r'"((?:[\w.-]+/)*[\w.-]+\.(?:py|ts|tsx|js|md|json|ya?ml|toml|html|css|sh))(?::\d+)?"', f.read_text())))
    for p in paths:
        q = root / p
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_text("\n" * 400)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    def git(*a: str) -> str:
        return subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, env=env).stdout.decode().strip()
    git("init", "-q")
    git("add", *paths)
    git("commit", "-q", "-m", "sources")
    m["commit"] = git("rev-parse", "HEAD")
    f.write_text(json.dumps(m))


def test_the_second_card_leaves_the_file_tree_to_what_is_picked() -> None:
    """The file browser shows where the picked box lives. A hover beside the pick filled the second card,
    and moved the file browser to the hovered box."""
    tree = "() => [...document.querySelectorAll('.trow.sel')].map((r) => r.textContent.trim())"
    with _served_map(lambda m: None, make_committed_sources) as url:
        page = _sized_page(url + "#v=container", 1600, 1000)
        try:
            page.evaluate("() => document.getElementById('srcrail').click()")
            page.wait_for_timeout(800)
            boxes = page.evaluate(BOX_BODIES)
            page.mouse.move(boxes[0]["x"], boxes[0]["y"], steps=3)
            page.mouse.click(boxes[0]["x"], boxes[0]["y"])
            page.wait_for_timeout(700)
            picked = page.evaluate(tree)
            assert picked, "the picked box's folder is selected in the file browser"
            shown = 0
            for b in boxes[1:]:
                page.mouse.move(b["x"], b["y"], steps=4)
                page.wait_for_timeout(500)
                shown += page.evaluate("() => !document.getElementById('peekcard').hidden")
                assert page.evaluate(tree) == picked
            assert shown >= 3, shown
            assert not page.js_errors, page.js_errors
        finally:
            page.close()

