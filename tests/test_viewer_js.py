#!/usr/bin/env python3
"""Syntax gate for the hand-maintained viewer frontend bundle.

viewer.js is a large, hand-edited vanilla-JS file and the repo has no JS test harness, so a stray
syntax error (an unbalanced brace, a dangling edit) would ship silently and break the whole viewer.
`node --check` parses the file without executing it — a cheap, deterministic regression guard. Skips
when node isn't installed (e.g. a Python-only CI image), so it never turns into a spurious failure.

Conventions: top-level test functions, no classes/fixtures.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

VIEWER_DIR = Path(__file__).resolve().parent.parent / "tools" / "coyomap" / "viewer"


def _node_check(js_path: Path) -> None:
    """`node --check` on a COPY named `.mjs`, never on the file in place.

    viewer.js is an ES module (top-level await, no bundler), but node decides CJS-vs-ESM from the
    nearest package.json, and the repo has none. Checked in place, node parses it as CommonJS, hits
    the top-level `await` first, and reports THAT — so any real syntax error further down is masked by
    a line that has been fine for a year. Measured: a duplicate `const` on line 5018 was reported as
    an await error on line 156. The `.mjs` suffix removes the guessing."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed — skipping viewer JS syntax gate")
    assert js_path.exists(), f"expected {js_path} to exist"
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / (js_path.stem + ".mjs")
        probe.write_text(js_path.read_text(encoding="utf-8"), encoding="utf-8")
        result = subprocess.run([node, "--check", str(probe)], capture_output=True, text=True)
    assert result.returncode == 0, f"{js_path.name} failed `node --check`:\n{result.stderr}"


def test_viewer_js_parses() -> None:
    _node_check(VIEWER_DIR / "viewer.js")


def _run_js(snippet: str) -> str:
    """Run a snippet against the REAL `esc` / `mdInline` / `mdRefs` lifted out of viewer.js.

    The frontend has no module system (one hand-edited script, loaded whole), so the only way to
    exercise a function of it is to slice its source and evaluate that. Sliced by the marker lines
    around each definition, so a rename fails loudly here instead of silently testing nothing."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed — skipping viewer JS behaviour gate")
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    start = js.index("const esc = (s) =>")
    end = js.index("let mode = 'base';")
    lifted = js[start:end]
    assert "const mdRefs" in lifted, "mdRefs moved out of the lifted region — fix the slice"
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "probe.mjs"
        f.write_text(lifted + "\n" + snippet, encoding="utf-8")
        r = subprocess.run([node, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, f"probe failed:\n{r.stderr}"
    return r.stdout.strip()


def test_authored_prose_never_shows_a_raw_element_id() -> None:
    """The rule the whole viewer follows — ids stay internal, names go on screen — enforced where it
    was actually broken: the recorded lines, which are KEYED by id, are the only prose that carries
    them. This is a behavioural gate, not a source read: it runs the real function.

    It also pins the three things that must NOT be rewritten — an id inside a code span (the author
    is quoting), an id inside a longer token (a `path:line` anchor must stay copyable), and an id the
    map does not define (leave it exactly as written rather than half-translate it)."""
    refs = {"C54": {"id": "C54", "name": "Request Context Middleware", "node": "C54"},
            "R3": {"id": "R3", "name": "Site visitor", "node": None}}
    body = ("C54, R3: an operator surface. See `C54` and src/C54_handler.py:42 for the detail; "
            "C99 is long gone.")
    out = _run_js(f"""
const refs = {json.dumps(refs)};
const html = mdRefs({json.dumps(body)}, refs);
const text = html.replace(/<[^>]+>/g, '');
console.log(JSON.stringify({{ html, text }}));
""")
    got = json.loads(out)
    # every id the server resolved is GONE from what the reader sees, replaced by its name
    for eid, ref in refs.items():
        assert ref["name"] in got["text"], f"{eid} did not render as its name"
    assert "C54, R3:" not in got["text"], "the recorded line still opens with raw ids"
    # …and the three exceptions survive verbatim
    assert "<code>C54</code>" in got["html"], "an id inside a code span was rewritten"
    assert "src/C54_handler.py:42" in got["text"], "an id inside a longer token was rewritten"
    assert "C99 is long gone" in got["text"], "an undefined id was not left as written"


def test_glossary_matching_folds_naming_variants_without_crossing_word_boundaries() -> None:
    """The term-linking engine's whole contract: plural, possessive, case and hyphen-vs-space all
    find the term, while a term hiding INSIDE a longer word ("sandboxing") never matches — the
    difference between an in-place definition and underlined noise."""
    out = _run_js("""
const M = buildGlossMatcher([
  { term: 'Upstream MCP', meaning: 'a mounted server' },
  { term: 'Cloud mode', meaning: 'the hosted deployment' },
  { term: 'Sandbox', meaning: 'the isolated box' },
]);
const spans = (t) => matchGlossTerms(t, M).map((m) => [m.g.term, t.slice(m.start, m.end)]);
console.log(JSON.stringify({
  plural: spans('Two Upstream MCPs are mounted.'),
  possessive: spans("the sandbox\\u2019s files"),
  hyphen: spans('runs in cloud-mode today'),
  caseAndSpace: spans('CLOUD MODE only'),
  inside: spans('sandboxing is unrelated'),
  snake: spans('reads the tool_catalog collection'),
  punct: spans('a key such as cloud:<mode> is parsed'),
  sentence: spans('It runs in the cloud. Mode is not stored.'),
  dash: spans('the cloud \\u2014 mode is separate'),
  quoted: spans('run \\u2018sandboxes\\u2019 now'),
}));
""")
    got = json.loads(out)
    assert got["plural"] == [["Upstream MCP", "Upstream MCPs"]]
    assert got["possessive"] == [["Sandbox", "sandbox’s"]]
    assert got["hyphen"] == [["Cloud mode", "cloud-mode"]]
    assert got["caseAndSpace"] == [["Cloud mode", "CLOUD MODE"]]
    assert got["inside"] == [], "a term inside a longer word must not match"
    # measured over-linking on the MCP Hero map, pinned: a snake_case identifier is a CODE name,
    # never the prose phrase; and a multiword term never matches across punctuation or a sentence end
    assert got["snake"] == [], "tool_catalog is an identifier, not the phrase 'tool catalog'"
    assert got["punct"] == [], "words joined by ':<' are a key format, not a term"
    assert got["sentence"] == [], "a phrase must not match across a sentence boundary"
    assert got["dash"] == [], "an em dash is a clause break, not the hyphen inside a term"
    # a quoted plural still matches, and the link span leaves the closing quote outside
    assert got["quoted"] == [["Sandbox", "sandboxes"]]


def test_glossary_matching_longest_match_wins_and_consumes_its_words() -> None:
    """'Hosted stdio MCP' must beat both 'Upstream MCP' and a bare 'MCP' term at the same position —
    and having matched, its words are consumed, so no shorter term re-fires inside it."""
    out = _run_js("""
const M = buildGlossMatcher([
  { term: 'MCP', meaning: 'the protocol' },
  { term: 'Upstream MCP', meaning: 'a mounted server' },
  { term: 'Hosted stdio MCP', meaning: 'one kind of upstream' },
]);
const spans = (t) => matchGlossTerms(t, M).map((m) => m.g.term);
console.log(JSON.stringify({
  longest: spans('a hosted stdio MCP responds'),
  middle: spans('each upstream MCP reconnects'),
  bare: spans('the MCP handshake'),
}));
""")
    got = json.loads(out)
    assert got["longest"] == ["Hosted stdio MCP"]
    assert got["middle"] == ["Upstream MCP"]
    assert got["bare"] == ["MCP"]


def test_glossary_no_autolink_and_aliases_control_which_surfaces_link() -> None:
    """`no_autolink` takes a too-generic term name out of matching; `aliases` put real alternative
    names in — through the same folding pipeline, with longest-match-first across both."""
    out = _run_js("""
const M = buildGlossMatcher([
  { term: 'Tool', meaning: 'one callable action', no_autolink: true, aliases: ['catalog tool'] },
  { term: 'Upstream MCP', meaning: 'a mounted server', aliases: ['upstream'] },
]);
const spans = (t) => matchGlossTerms(t, M).map((m) => [m.g.term, t.slice(m.start, m.end)]);
console.log(JSON.stringify({
  generic: spans('every tool is listed'),
  viaAlias: spans('the catalog tools are listed'),
  aliasWord: spans('each upstream reconnects'),
  fullTermStillWins: spans('the upstream MCP reconnects'),
}));
""")
    got = json.loads(out)
    assert got["generic"] == [], "a no_autolink term's own name must not match"
    assert got["viaAlias"] == [["Tool", "catalog tools"]]
    assert got["aliasWord"] == [["Upstream MCP", "upstream"]]
    assert got["fullTermStillWins"] == [["Upstream MCP", "upstream MCP"]]


def test_glossary_autolink_skips_chrome_chips_code_and_the_glossary_view_itself() -> None:
    """Source-read pins on the DOM pass: the skip list keeps links out of controls, quoted
    literals, SVG box labels, route chips, bare file paths and the Glossary view; the click
    handler runs in capture phase so a linked term opens the Glossary instead of drilling the
    card it sits in; and the observer covers both prose hosts (the stage and the info pane)."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    pass_src = js[js.index("const GLOSS_MATCHER"):js.index("function glossSubjectKey")]
    for needle in ("a, button", "code", "pre", "kbd", "svg", ".tb-trig", ".glossary-wrap",
                   ".gloss-plain"):
        assert needle in pass_src, f"skip list lost {needle!r}"
    wiring = js[js.index("if (HAS_GLOSSARY && GLOSS_MATCHER.maxWords)"):][:2400]
    assert "glossMo.observe(diagram" in wiring
    assert "glossMo.observe(PANEL_HOST" in wiring
    assert "}, true);" in wiring, "the gloss-link click handler must run in capture phase"
    assert "sbGotoGlossary(a.dataset.glossTerm)" in wiring
    # one seen-map per BATCH: a panel card written as several sibling fragments is one card, and a
    # per-call map linked the same term once per fragment (found by the adversarial review)
    assert "const seenByScope = new Map();" in wiring
    # stopping propagation starves the document-level click-outside closers, so the handler closes
    # those popovers itself (also from the review)
    assert "hideUcPick();" in wiring and "closeImpactPop();" in wiring
    # a scope's seen-set starts from links it already holds, so re-inserted linked HTML cannot
    # link the next occurrence on top of the first
    assert "scope.querySelectorAll('a.gloss-link')" in js


def test_flow_step_keeps_relationship_navigation_on_the_arrow() -> None:
    """The pane stays step-specific; its arrow owns structural relationship navigation."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    start = js.index("function flowStepInfoHtml(uc, i)")
    end = js.index("\n// One actor's card", start)
    flow_step = js[start:end]

    assert 'class="flowpairref"' not in flow_step
    assert 'class="endpoints"' not in flow_step
    assert "showPairEdges(pairEdges)" not in flow_step
    assert "Rides arrow" not in flow_step
    assert "ridesref" not in flow_step
    assert 'class="flowref"' not in flow_step


def test_flow_arrows_locate_all_backbone_relationships_in_structural_views() -> None:
    js = (VIEWER_DIR / "viewer.js").read_text()
    flow_map = js[js.index("function bindFlowMap(uc)"):js.index("function syncEnvPicker")]

    # LOCATE IS A BOX'S ACTION NOW, and only a box's. The pair that answered it for an ARROW —
    # `relationshipLocateAction`, which built the action, and `relationshipLocateTarget` + `bundleAtoms`,
    # which worked out which structural view drew that relationship — existed only to feed an arrow's
    # icon, and arrows draw no icon at all. A locate an arrow cannot offer is not a locate.
    locate_action = js[js.index("function locateActionFor(id) {"):
                       js.index("\n}", js.index("function locateActionFor(id) {"))]
    assert "kind: 'locate'" in locate_action
    assert "title: 'Locate in ' + tab" in locate_action
    assert "pendingCenter = t.selectId" in locate_action, "locate exists to point at one thing among many"
    for gone in ("function relationshipLocateAction", "function relationshipLocateTarget", "function bundleAtoms"):
        assert gone not in js, gone
    # …but NOT a walk arrow on the MAP. Selecting a step already opens its own code, so a drill there
    # could only repeat the click that got you here — and what it used to do instead was leave the story
    # for the aggregate arrow between the same two elements, in another view.
    assert "relationshipLocateAction(m[1], m[2])" not in flow_map
    assert "opts: {}," in flow_map
    # AN ARROW DRAWS NO ICON AT ALL, and the machinery that drew one is gone with it: the pill builder,
    # its label-anchored variant, the arrow-midpoint fallback anchor and the hover bridge between pill
    # and label. It was the last place the icon survived after every box and every frame had let it go.
    for gone in ("function bindEdgeActionIcon", "function addLabelActionIcon", "function placeLabelBridge",
                 "function edgeMidpointAnchor", "EDGE_ICON_SEQ", "iconBridgeOverlay"):
        assert gone not in js, gone
    assert "'edge:' + e.src + '>' + e.dst + ':' + m[3]" in js


def test_only_direct_diagram_clicks_pin_selection_action_icons() -> None:
    js = (VIEWER_DIR / "viewer.js").read_text()
    selection = js[js.index("function selApply"):js.index("// The full click-gesture handler")]
    sequence = ""   # the sequence rendering was removed; the map is the one picture of a walk
    glow_edge = js[js.index("function glowEdge"):js.index("// EVERY ARROW IS DRAWN THE SAME")]
    hp_glow = js[js.index("function hpGlow"):js.index("// Glow a set of elements")]
    flow_map = js[js.index("function bindFlowMap(uc)"):js.index("function syncEnvPicker")]

    assert "d.glow(!!d.revealAction)" in selection
    assert "function selAdd(scene, desc, revealAction = false)" in selection
    assert "revealAction: !!revealAction" in selection
    assert "selToggle(scene, desc, true)" in selection
    assert "selReplace(scene, desc, true)" in selection
    # `selRevealsAction` went with the arrow pill it answered for: an arrow has no icon to reveal, so
    # `revealAction` now means only what a BOX and a Happy Path message do with it.
    assert "function selRevealsAction" not in js
    assert "glowEdge(p, label, revealAction = true)" in glow_edge
    assert "_actionIcon" not in glow_edge, "an arrow has no pill to pin or hide"
    assert "hpGlow(el, revealAction = true)" in hp_glow
    assert "el._actionIcon._selected = !!revealAction" in hp_glow
    assert "glowEdgeAt(arrow.path, arrow.label, reveal, stepNumEl(arrow.label, i))" in flow_map
    assert "flowPlay.showLocate" not in js
    assert "showLocate:" not in js


def test_node_use_cases_are_grouped_by_capability_without_a_serves_row() -> None:
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    trace = js[js.index("function tracedUseCasesFor"):js.index("// The \"Triggered by\"")]
    detail = js[js.index("function nodeDetailBodyHtml"):js.index("function bindNodeDetailHandlers")]

    assert "isAncestorOf(id, eid)" in trace
    assert "UC_NODES.filter((uc) => set.has(uc.id))" in trace
    assert "CAP_OF_UC[uc.id]" in trace
    # ONE CARD PER FEATURE, holding that feature's use cases as pills. Two shapes came before it and
    # both failed the same way: an indented <ul> of blue links, then a feature pill with a row of
    # use-case pills beside it, where nothing on screen said the second lot belonged to the first.
    assert "elementCardHtml(g.cap.id, {" in trace
    assert "detailPills(g.ucs.map(link).join(''))" in trace
    assert "itemPillHtml(uc.id, { kind: 'usecase'" in trace
    assert "used-uc-list" not in trace and "used-cap-group" not in trace, "an older shape is back"
    # A use case the map assigns to no feature gets a card that is NOT an element's: no mark, no type
    # word, nothing to open — because it names no feature.
    assert "plainCardHtml({ key: 'uc-loose'" in trace
    assert "No traced use case reaches it." in trace
    assert "servesHtml" not in js
    assert "usedInHtml(id)" in detail
    assert ".serves-chip" not in css


def test_flow_map_dims_other_numbers_on_a_selected_multi_step_arrow() -> None:
    js = (VIEWER_DIR / "viewer.js").read_text()
    start = js.index("function flowMapPaintStepLabel(label, stepIdx, current)")
    end = js.index("\n// The steps riding one arrow", start)
    label_code = js[start:end]

    assert "stepIdx.length > 1 && stepIdx.includes(current)" in label_code
    assert "active && i !== current" in label_code
    assert "flow-other-step" in label_code
    assert "createElement('strong')" not in label_code
    assert "flowPlay.active && i >= 0" in label_code
    assert "pairSelected" not in label_code
    assert "const current = stepSelected" in label_code
    assert "flowMapRefreshStepLabels();" in js[js.index("function selApply"):js.index("function selAdd")]
    assert "mapArrows: arrows" in js


def test_flow_map_arrows_reuse_complete_sequence_step_info() -> None:
    js = (VIEWER_DIR / "viewer.js").read_text()
    step = js[js.index("function flowStepInfoHtml"):js.index("// One actor's card")]
    pair = js[js.index("function showFlowPair"):js.index("function bindFlowMap")]
    binding = js[js.index("function bindFlowMap"):js.index("function syncEnvPicker")]

    assert "flowStepInfoHtml(uc, i)" in step
    assert "bindFlowStepInfo(panel, uc, i)" in step
    assert "if (steps.length === 1) { showFlowStep(uc, steps[0].i); return; }" in pair
    assert "flowStepInfoHtml(uc, i)" in pair
    # The Step pill is unconditional — the same card everywhere, single selection or bundled section.
    assert "numbered ?" not in step
    assert 'class="flow-step-separator"' in pair
    assert "Steps on this arrow" not in pair
    assert "flowstepref" not in pair
    assert "if (on.length === 1)" in binding
    assert "else showFlowPair" in binding
    assert "flowSyncCur(on[0].i); showFlowPair" not in binding


def test_flow_map_boxes_locate_the_element_in_its_structural_diagram() -> None:
    js = (VIEWER_DIR / "viewer.js").read_text()
    start = js.index("function locateActionFor(id)")
    end = js.index("\nfunction clearFocus", start)
    locate_code = js[start:end]

    assert "const t = selectTargetFor(id)" in locate_code
    assert "!t || !t.selectId" in locate_code  # actor aliases have no structural home
    assert "kind: 'locate'" in locate_code
    assert "const tab = stateTitle({ kind: topView(t.state.kind, t.state.id) })" in locate_code
    assert "title: 'Locate in ' + tab" in locate_code
    assert "sel: 'node:' + t.selectId" in locate_code
    assert "pendingCenter = t.selectId" in locate_code
    assert "if (isFlowState(s) || isDataPicture(s) || isStructurePicture(s) || (s && PAIR_PAGE[s.kind])) return;" in locate_code   # no icons on a walk, a Data or a structure picture, or a pair page
    # No icons on a walk at all — the box's NAME opens what it names. Off a walk, the icon is the
    # element's own primary action.
    assert "const action = primaryActionFor(id);" in locate_code
    assert "if (locate && isDrillClick(ev)) { locate.run(); return; }" in js
    assert "action-icon is-' + action.kind" in js
    assert "Lucide LocateFixed" in js
    assert "ACTION_ICON_TIP_DELAY_MS = 250" in js
    assert "scheduleActionIconTip(actionLabel, ev)" in js
    assert "icon.setAttribute('aria-label', actionLabel)" in js
    assert "createElementNS(SVGNS, 'title')" not in js[js.index("function addActionIcon"):js.index("function showIcon")]


def test_all_action_icons_render_in_the_foreground_overlay() -> None:
    js = (VIEWER_DIR / "viewer.js").read_text()
    action = js[js.index("function addActionIcon"):js.index("function showIcon")]

    assert "svg.appendChild(g)" in js[js.index("function ensureIconOverlay"):js.index("const ACTION_ICON_TIP_DELAY_MS")]
    assert "svg.querySelector(':scope > g')" not in js[js.index("function ensureIconOverlay"):js.index("const ACTION_ICON_TIP_DELAY_MS")]
    assert "iconOverlay.parentNode.appendChild(iconOverlay)" in js
    assert "const parent = iconOverlay || host || el" in action
    assert "const parent = host || iconOverlay || el" not in action
    # ONE ICON BUILDER IS LEFT, and it homes every icon in the overlay. The label-anchored pill and its
    # hover bridge went with the arrow icons they were built for — they were the only kind that had to
    # hang off a label instead of a box corner, and the only reason a second overlay layer existed.
    assert "coyomap-icon-bridge-overlay" not in js
    assert "function addLabelActionIcon" not in js and "function bindEdgeActionIcon" not in js


def test_a_walk_has_one_rendering_and_it_is_the_map() -> None:
    """A sequence diagram stood beside the map behind a "Flow as" switch. Two renderings of one walk
    meant every rule written twice and kept in step — the step numbers, the actor aliases, what a
    collapsed shared sub-use case shows — and the map answers strictly more: it draws each element in the
    structural views' own colour and shape, which lifelines cannot."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    for gone in ("FLOW_VIEW", "FLOWS_MM", "function bindFlow(uc)", "syncFlowPicker", "EMPTY_FLOW_MM"):
        assert gone not in js, f"{gone} is part of the removed sequence rendering"
    assert "return FLOWS_MAP[uc] || EMPTY_FLOW_MAP;" in js
    gen = (VIEWER_DIR / "gen_viewer.py").read_text(encoding="utf-8")
    for gone in ("def gen_flow_mermaid", "def flow_mermaids", "flowsMm"):
        assert gone not in gen, f"{gone} is part of the removed sequence rendering"
    # …and the step player, which shared the switch's card, is still there.
    assert "function syncFlowCard(s) {" in js
    html = (VIEWER_DIR / "viewer.html").read_text(encoding="utf-8")
    assert 'id="flowplayer"' in html and 'id="flowpicker"' in html

def test_flow_player_suspends_and_resumes_within_one_visit() -> None:
    js = (VIEWER_DIR / "viewer.js").read_text()
    start = js.index("function flowCounter()")
    end = js.index("\n// A flow step's side panel", start)
    player = js[start:end]

    # A LABEL LEADS THE CONTROL and says what pressing an arrow would do; the counter keeps the two
    # numbers. Alone, the counter read "Step – / 20" before anything was picked, and a dash where a
    # number goes is a blank.
    assert "(SUBFLOW_BY_ID[flowPlay.uc] ? 'shared sub-use case' : 'use case')" in player \
        and "flowlabel.textContent = 'Step through this '" in player
    assert "flowcount.textContent = (active ? i + 1 : '\\u2013') + ' / ' + n;" in player
    html = (VIEWER_DIR / "viewer.html").read_text(encoding="utf-8")
    body = html[html.index('<div id="flowplayer"'): html.index("</div>", html.index('id="flownext"'))]
    assert body.index('id="flowlabel"') < body.index('id="flowprev"') < body.index('id="flowcount"'), \
        "the label comes before the control it names"
    assert "flowprev.disabled = !active" in player
    assert "flownext.disabled = false" in player
    assert "flownext.title" not in player
    assert "flowPlay.active = false" in player
    assert "flowGoto(flowPlay.cur >= 0 ? flowPlay.cur : 0)" in player

    # (The live hand-off across the Map/Sequence switch is gone with the switch; the history
    # point's own snapshot is what restores a suspended step.)
    # (The Map/Sequence switch that needed a resume is gone; a walk has one rendering.)
    assert "flowSuspend();" in js[js.index("function selClear"):js.index("function selReplace")]


def test_flow_player_state_is_captured_and_restored_with_history() -> None:
    js = (VIEWER_DIR / "viewer.js").read_text()
    capture = js[js.index("function captureViewState"):js.index("function pushContentPoint")]
    transition = js[js.index("function driveTransition"):js.index("async function runDrill")]
    html = (VIEWER_DIR / "viewer.html").read_text()

    assert "history[hi].flow = flowSnapshot()" in capture
    assert "flow: c.flow" in js[js.index("function pushContentPoint"):js.index("function go(state")]
    assert "restoreFlowSnapshot(to.flow)" in transition
    assert "if (restoreFlowSnapshot(s && s.flow)) return;" in js
    assert "flowInit(s)" in js
    assert 'id="flowprev" aria-label="Previous step"' in html
    assert 'id="flownext" aria-label="Next step"' in html
    assert 'title="Previous step' not in html
    assert 'title="Next step' not in html


def test_the_ui_does_not_name_internal_model_fields():
    """The viewer speaks the reader's language, not the model's.

    A panel that says "no `runs_in`" names a JSON field the reader never sees and cannot act on from
    the UI. Naming the field is right in `validate` — that output is FOR editing the map, and the
    codebase already draws this line ("Completeness is validate's job, where it comes with the
    specific ids to fix"). It is wrong on screen.

    Checks the rendered STRINGS only: reading `ep.runs_in` in code is how the data is used, and
    backtick-to-<code> markdown of AUTHORED map text is the map's own words, not ours."""
    js = (Path(__file__).resolve().parents[1] / "tools/coyomap/viewer/viewer.js").read_text()
    fields = ("runs_in", "no_call_site", "non_entity_types", "tests_note", "where_configured",
              "cadence_source", "tech_source", "subflow", "why_refs")
    offenders = []
    for i, line in enumerate(js.splitlines(), 1):
        code = line.split("//", 1)[0] if not line.lstrip().startswith("//") else ""
        if "<code>" not in code:
            continue
        for f in fields:
            if f"<code>{f}</code>" in code:
                offenders.append(f"{i}: {line.strip()[:90]}")
    assert offenders == [], "internal field name rendered in the UI:\n" + "\n".join(offenders)


def test_source_links_are_bound_by_delegation_not_per_render():
    """One listener per container, so a new panel writer cannot ship dead source buttons.

    Source buttons used to be wired by calling `wireSrcLinks(root)` after each render, which works
    only if every panel writer remembers. `showNode` — the pane shown for any selected element — did
    not, so a deployment unit's Environments row rendered its manifest anchors as buttons that did
    nothing when clicked. Delegation makes forgetting impossible rather than merely catchable."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    code = [ln for ln in js.splitlines() if not ln.lstrip().startswith("//")]
    stale = [ln.strip() for ln in code if "wireSrcLinks" in ln]
    assert stale == [], ("per-render source-link wiring is back — it double-binds against the "
                         "delegated listener:\n" + "\n".join(stale))
    assert "closest('.srclink')" in js, "the delegated source-link listener is missing"
    # it must be attached to the STABLE panel host, not the `panel` binding, which is temporarily
    # re-pointed at individual cards while a multi-selection renders.
    assert "[PANEL_HOST, diagram].forEach" in js


def test_the_section_index_is_ONE_component_used_by_every_card_list_tab() -> None:
    """The System tab had a pinned index — all sections at a glance, click to jump, the one you are
    in lit up — and the two other card-list tabs did not, though they have the same problem the
    moment a map has more categories than fit on a screen. A second copy per tab is three places for
    the sticky-offset maths to drift, so the bar is one component all three call."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "function tabIndexHtml(secs)" in js and "function bindTabIndex(wrap)" in js
    assert "function bindSysIndex" not in js and "sys-index" not in js   # the private copy is gone
    # ONE page still stacks several groups on one scroll and therefore still needs an index: the
    # use-case list. System and Rules stopped stacking when they became cards, so they index nothing —
    # a card grid IS the index of what is behind it. The component stays shared, not re-privatised.
    body = js[js.index("function renderUseCases("):js.index("\nfunction ", js.index("function renderUseCases(") + 10)]
    assert "tabIndexHtml(" in body and "bindTabIndex(" in body
    for fn in ("renderRules", "renderSystem"):
        gone = js[js.index(f"function {fn}("):js.index("\nfunction ", js.index(f"function {fn}(") + 10)]
        assert "tabIndexHtml(" not in gone, fn
    # One section indexes nothing — no bar rather than a bar with one chip.
    assert "if (!secs || secs.length < 2) return '';" in js


def test_the_pinned_index_sticks_to_the_wrappers_top_border() -> None:
    """`position: sticky; top: 0` inside a scrolling box resolves to the CONTENT edge, so the
    wrapper's 16px top padding stayed ABOVE the bar as a transparent strip — scrolling rows slid
    through it and the bar read as floating in the middle of the list. The padding moves onto the
    bar (only where there IS one) and negative side margins take it full-bleed, so nothing scrolls
    past above or beside it. Measured in the browser: gap 0, bar width == wrapper width."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    # The padding-drop is now shared with every other wrap that holds a sticky line — see
    # test_no_scroll_wrapper_holds_a_sticky_line_below_its_own_top_padding for why they all need it.
    assert ".usecases-wrap:has(> .tab-index), .usecases-wrap.system-wrap, .usecases-wrap.glossary-wrap { padding-top: 0; }" in css
    bar = css[css.index(".usecases-wrap .tab-index {"):]
    bar = bar[:bar.index("}")]
    assert "position: sticky" in bar and "top: 0" in bar
    assert "margin: 0 -20px 12px" in bar and "padding: 12px 20px 10px" in bar


def test_the_scroll_spy_clears_the_sections_scroll_margin() -> None:
    """The spy lights the LAST section whose top is above a line just under the bar. That line has
    to clear the sections' own `scroll-margin-top`, or a section you just JUMPED to lands below the
    line and the chip that lights is the one ABOVE the one you clicked."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    spy = js[js.index("const spy = () => {"):js.index("wrap.addEventListener('scroll', spy")]
    # The bar's rect is read ONCE per pass and used twice — for this line, and for the attached test
    # below it. Two reads of the same box in one frame is a second forced layout for no new answer.
    assert "const navRect = nav.getBoundingClientRect();" in spy
    assert "const line = navRect.bottom + 12;" in spy
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "scroll-margin-top: calc(var(--tab-index-h) + 8px)" in css      # 8 < 12
    # ATTACHED, in the same pass. A sticky element has no CSS state of its own, so the reading is
    # geometric: the bar is attached when it has reached its own top and stopped moving with the page.
    # The spy CALLS the attached reading, it no longer holds it: two strips are sticky and only one
    # has sections to spy on, so the edge moved into `markStuck` where both read it the same way.
    assert "markStuck(nav, wrap);" in spy
    assert "nav.classList.toggle('tab-index-stuck'," in js[js.index("function markStuck(nav, wrap) {"):]
    assert "nav.getBoundingClientRect().top - wrap.getBoundingClientRect().top < 0.5" in \
        js[js.index("function markStuck(nav, wrap) {"):]
    assert ".usecases-wrap .tab-index-stuck { box-shadow:" in css
    assert "transition: box-shadow" in css


def test_a_text_tab_remembers_where_it_was_scrolled_to() -> None:
    """The diagram tabs remember their camera twice over — per history point (back/forward lands
    exactly) and per view (a tab switch lands there too). The text tabs were left out only because
    they have no camera; the position matters just as much on a 96-rule list. Same two places,
    saving scrollTop instead of zoom."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "const scrollByView = {};" in js
    assert "function textScroller()" in js
    # ONE selector names every text tab's scroll container — Use Cases / Business logic / the rule
    # page / System / Tests share `.usecases-wrap`; Glossary and Data have their own.
    assert "'.usecases-wrap, .glossary-wrap, .dv-content'" in js
    capture = js[js.index("function captureViewState"):js.index("function pushContentPoint")]
    assert "history[hi].scroll = sc.scrollTop" in capture
    assert "scrollByView[stateKey(history[hi])] = sc.scrollTop" in capture
    # …and it survives a right-pane navigation, like every other field the restore reads.
    assert "scroll: c.scroll" in js[js.index("function pushContentPoint"):js.index("function go(state")]
    # Every text view restores it on the way out of render().
    assert js.count("restoreTextScroll(s") >= 7
    # Clicking the tab you are already ON is a reset — it drops the remembered spot, as it drops the
    # remembered camera.
    reset = js[js.index("function resetTab(view)"):js.index("function resetTab(view)") + 400]
    assert "delete scrollByView[stateKey(root)]" in reset


def test_an_explicit_jump_beats_a_remembered_scroll_position() -> None:
    """A cross-link naming a decision area, or the crumb walking back out of a rule, asks for a SPECIFIC
    place, and a remembered scroll offset must not undo it. That used to need an escape hatch, because
    the list stacked every area on one page and the link had to scroll to a section of it. An area is
    its own page now: there is nothing to scroll to, nothing to override, and the state's own offset is
    simply correct. The hatch goes with its only producer rather than sitting there unreachable."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "function restoreTextScroll(s) {" in js
    assert "restoreTextScroll(s, " not in js, "the escape hatch outlived its only producer"
    assert "const jumped = " not in js
    rules = js[js.index("function renderRules(s)"):js.index("\nfunction ", js.index("function renderRules(s)") + 10)]
    assert "scrollIntoView" not in rules


def test_no_tab_row_can_ever_clip_a_tab_out_of_reach() -> None:
    """Both tab rows were one nowrap flex row with `overflow:hidden`, so a pane too narrow for every
    tab silently amputated the last ones. Measured in the browser at a 1280px window: the Tests tab
    had ZERO visible width and could not be clicked, and Glossary was cut mid-word. A hidden tab is a
    view the reader cannot reach and has no way to discover, so buttons keep their natural width and
    the row wraps instead. Grouping does not retire this rule — a very narrow pane can still overflow
    a four-view sub row. The mode switch now sits INLINE after the view tabs rather than pushed to the
    far edge, so the sub row itself has to wrap too: otherwise the switch is the thing a narrow pane
    cuts off, and #stage hides its overflow. Measured at a 400px pane: the row grows to two lines and
    the switch drops onto the second, whole."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    subrow = css[css.index("#stagesubrow {"): css.index("}", css.index("#stagesubrow {"))]
    assert "flex-wrap: wrap" in subrow
    assert "viewextra" not in css, "the header's mode slot is gone; the switch lives with its list"
    for row in ("#groupsw", "#viewsw"):
        rule = css[css.index(f"\n{row} {{") : css.index("}", css.index(f"\n{row} {{"))]
        assert "flex-wrap: wrap" in rule, row
        btn = css[css.index(f"\n{row} button {{") : css.index("}", css.index(f"\n{row} button {{"))]
        assert "flex: 0 0 auto" in btn and "white-space: nowrap" in btn, row


def test_every_view_declares_its_group_and_every_group_is_declared_once() -> None:
    """The grouping lives on the button it groups (`data-group`), so there is no second membership
    list to keep in step with the buttons. A view with no group would vanish from every row: its
    group tab would never light and its sub tab would never be shown."""
    html = (VIEWER_DIR / "viewer.html").read_text()
    js = (VIEWER_DIR / "viewer.js").read_text()
    buttons = re.findall(r'<button data-view="([a-z]+)" data-group="([a-z]+)">', html)
    views = re.findall(r'<button data-view="([a-z]+)"', html)
    assert len(buttons) == len(views), "a view button is missing its data-group"
    start = js.index("const VIEW_GROUPS = [")
    table = js[start : js.index("\n];", start)]
    declared = set(re.findall(r"\['([a-z]+)', '", table))
    assert {g for _, g in buttons} <= declared, "a button names a group VIEW_GROUPS does not declare"
    assert declared == {g for _, g in buttons}, "VIEW_GROUPS declares a group no view belongs to"


def test_an_empty_group_never_reaches_the_row_and_a_lone_view_draws_no_sub_tab() -> None:
    """Two ways the two-row switcher could lie. A group whose every view is gated off by THIS map's
    content would open onto nothing, so it is not built at all. And a group holding one view draws no
    sub tabs, because a lone chip repeating the group name above it says nothing — the strip still
    renders at full height, so opening that group does not shunt the diagram up and back down."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    boot = js[js.index("for (const [gid, label, question] of VIEW_GROUPS) {"):]
    assert "if (!views.length) continue;" in boot[: boot.index("\n}")]
    assert "const lone = groupViews(tg).length < 2;" in js
    assert "b.hidden = lone || b.dataset.group !== tg;" in js
    css = (VIEWER_DIR / "viewer.css").read_text()
    sub = css[css.index("#stagesubrow {"): css.index("}", css.index("#stagesubrow {"))]
    assert "min-height" in sub, "an empty sub row must still reserve its height"


def test_a_map_with_no_features_keeps_the_flat_use_case_list() -> None:
    """The overview cards are built from the map's capabilities. A map that records none would land on
    an empty screen, so that tab falls back to the flat use-case list it has always shown. The list is
    ONE function for every case — a feature's use cases, an actor's, or all of them — so the row
    markup, the Happy-Path pill, the diff badge and the flow click cannot drift between them."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "if (HAS_CAPABILITIES) renderOverview(); else renderUseCases();" in js
    assert "function renderUseCases(sel) {" in js
    assert ("renderUseCases({ cap: s.cap, actor: s.act, sec: s.sec });"
            in js), "one feature's list and the flat catalog are the same renderer scoped differently"
    # In diff mode a card carries its members' change, or dropping the use cases one level down would
    # hide every "changed" badge behind a click.
    feat = js[js.index("function renderOverview() {"): js.index("\nfunction ", js.index("function renderOverview() {") + 10)]
    assert "g.ucs.some((x) => usecaseDiffState(x.id))" in feat


def test_features_owns_the_actor_page_and_the_actors_view_is_gone() -> None:
    """The Actors tab is retired: the story diagram's cast column shows every actor with more
    context (the kind pills keep the human/software split the card grid drew, the use-case count
    keeps the count), so the tab was the same answer twice. What remains is each actor's own page —
    the journey line — reached from a cast card, hanging UNDER FEATURES: the trail reads
    Features › <actor>, the same overview → member shape a feature's page has."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    assert "UC_GROUP_BY" not in js and "ucGroupBy" not in js, "the axis is gone, not defaulted"
    assert "bindOverviewAxis" not in js and "uc-groupby" not in js
    # The view itself is gone everywhere a view exists: the tab, the state kind, the gate, the
    # renderer, the question, the text-page list.
    assert 'data-view="actors"' not in html, "the Actors tab is retired"
    assert "HAS_ACTORS" not in js and "renderActors" not in js and "actorCardsHtml" not in js
    assert "kind === 'actors'" not in js and "kind: 'actors'" not in js
    # An actor's page lives under FEATURES now, and renders the journey line.
    assert "if (kind === 'actor') return 'usecases';" in js
    assert "renderActorPage(s.act);" in js and "function renderActorPage(actorName) {" in js
    assert "if (s.kind === 'actor') return [{ kind: 'usecases' }, { kind: 'actor', act: s.act }];" in js
    assert ("if (s.kind === 'capability') return [{ kind: 'usecases' }, "
            "{ kind: 'capability', cap: s.cap, act: s.act }];") in js
    over = js[js.index("function renderOverview() {"): js.index("\nfunction ", js.index("function renderOverview() {") + 10)]
    # Two words for a capability, then three: `Category`, then `Capability` beside a tab already
    # saying Features. Both were the label of a switch that should not have existed.
    assert "'Category'" not in js and "Features grouped by" not in js
    assert "'grid'" not in over, "the matrix setting is gone, not hidden"
    assert "renderRoleGrid" not in js

def test_a_board_is_headed_by_its_subject_only_where_the_page_does_not_say_it() -> None:
    """A board's head is icon-then-name on one line, over the gutter and above both lane names. It is
    a SLOT — a feature's sparkle and a feature's name drop into the same markup an actor's figure and
    name used to — and the one line shape was chosen so that it would.

    THE ACTOR'S BOARD NO LONGER USES IT, and that is the point of this test now. Its head drew this
    actor's figure and this actor's name at the top of the frame, one line under a hero that had just
    drawn the same figure and the same name, and it never said the thing a reader needed: that the
    boxes on the board are USE CASES. The section around it says that now, in a heading and a
    sentence, so the head had nothing left to say. A feature's board lost its head the same way once
    its page got the same framed section under the same hero card.

    The head is deliberately NOT a fourth cell of the rail grid. A cell in row 1 would grow that row
    for every feature too, and each tinted box would open with 26px of empty colour above its name —
    measured. Outside the grid the boxes are untouched, and the head is sticky like the gutter under
    it, so it stays put while the board scrolls sideways.

    With the figure gone from the rail, the upper lane's name takes the rail's own height: 15.75px of
    padding puts its 13.5px line box's middle at 22.5px, which is `top: 21px` plus half of
    `height: 3px`. At the row's top it read as a heading over the band, which is what the lower
    lane's name is — and only one of the two lanes has a line to caption."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    page = js[js.index("function renderActorPage(actorName) {"):
              js.index("\nfunction ", js.index("function renderActorPage(actorName) {") + 10)]
    # THE ACTOR'S BOARD IS BARE: the section heading above it names it, and the hero above that names
    # the actor. Neither the page nor the helper it used survives.
    assert "journey-actorhead" not in page and "journeyActorHeadHtml" not in js
    assert '<div class="journey-board">${journeyRailHtml(hasPath, offLane, rail, partLane)}</div>' in page
    assert "journeyRailHtml(hasPath, offLane, rail, partLane)" in page, \
        "…and the lanes come from one place, the third one included"
    assert "hasPath ? `<div" not in page and "hasPath ? '<span" not in page, \
        "the board is not conditional on there being a happy path"
    railfn = js[js.index("function journeyRailHtml(hasPath, offLane, boxes, partLane) {"):
                js.index("\nfunction ", js.index("function journeyRailHtml(hasPath, offLane, boxes, partLane) {") + 10)]
    assert "journey-actorhead" not in railfn, "…and it never was one of the gutter's cells"
    # AND NO BOARD HEADS ITSELF ANY MORE. A feature's board named the feature with its sparkle, and the
    # hero card one section above already says `Feature: <name>` — the same words twice, 60px apart.
    # The slot went with its last caller.
    assert "journeyHeadHtml" not in js and "journey-actorhead" not in js
    assert ".journey-actorhead" not in css and ".journey-actorname" not in css, "and its styles went with it"
    # Row 1 is the feature-name row and nothing else, so the tinted boxes are untouched.
    assert ".journey-gutter-top { grid-row: 1; }" in css
    assert ".journey-zlabel { grid-row: 1; white-space: nowrap; padding-top: 8px;" in css
    # The upper lane's name sits ON the rail. The rule is at top 19.5 with height 3, so its middle
    # is 21 — where the shared step box puts its bullet (13.5px of margin plus half a 15px dot).
    assert ".journey-track::before" in css and "top: 19.5px;" in css and "height: 3px;" in css
    assert ".journey-gutter-on { grid-row: 2; padding-top: 15.75px; }" in css

def test_a_station_is_a_dot_and_a_title_and_the_actor_s_rail_adds_the_step_number() -> None:
    """A station on a rail is a dot and a title. Its number in the whole walk was drawn OVER the dot
    once, and went: a number centred on the dot starts further left the more digits it has, so the
    title had to line up with the number, an indent rule per digit count, on the title AND on the
    off-path list under it.

    The number is back on the ACTOR'S rail, drawn as the Happy Path draws it — a small line between
    the dot and the title, taking no width of its own, so no indent rule returns with it. An actor's
    rail skips the steps other actors drive, and the numbers are what say where those gaps are. The
    feature's rail zones by driver and holds every step of its feature, so it still asks for none.

    The station index stays out of the data: `actorStations` returns the walk's steps, and the number
    is read off the walk (`hpStepPos`) by the one shared step box."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    zone = js[js.index("function journeyZoneHtml(z, opts) {"):
              js.index("\nfunction ", js.index("function journeyZoneHtml(z, opts) {") + 10)]
    assert 'class="journey-n"' not in js and ".journey-n {" not in css, "no number on the dot"
    assert "journey-d1" not in js and "journey-d2" not in css, "and no per-digit indent rule"
    assert "sideIndent" not in zone, "…nor the off-path list's copy of it"
    # A STATION IS THE SHARED STEP BOX (flowStepBoxHtml), the one the Happy Path draws — so the dot, the
    # number and the title are stated once, there, and a rail says whether it wants the number.
    assert "flowStepBoxHtml(s, { actor: o.actor, marks: true, ifs, num: !!o.num })" in zone
    actor_rail = js[js.index("function renderActorPage(actorName) {"): js.index("\nfunction ", js.index("function renderActorPage(actorName) {") + 10)]
    assert "num: true," in actor_rail, "the actor's rail asks for the step number"
    feature_rail = js[js.index("function featureRailHtml(capId) {"): js.index("\nfunction ", js.index("function featureRailHtml(capId) {") + 10)]
    assert "num:" not in feature_rail, "the feature's rail asks for none"
    step = js[js.index("function flowStepBoxHtml(st, o) {"):
              js.index("\nfunction ", js.index("function flowStepBoxHtml(st, o) {") + 10)]
    assert '<span class="flow-step-dot"></span>' in step
    assert step.index('flow-step-dot') < step.index('opt.num ?') < step.index('flow-step-title'), \
        "the number sits between the dot and the title, as on the Happy Path"


def test_the_actor_pages_two_lanes_are_named_once_and_share_one_height() -> None:
    """An actor's page cuts every feature box into two lanes: the happy-path steps above a dashed
    line, everything else the actor drives below it. Six signals already separated them (dot vs
    circle, the rail, the step numbers — since removed — ink vs grey, the dashed line, the legend)
    and readers still read one stacked list, for two reasons this fixes.

    The lanes were never NAMED where the reader looks — the words "happy path" appeared only in the
    legend under the board — and the one label that did exist, "also here:", was drawn per box and
    only in a box that also had steps. So a feature the actor's happy path never enters (the Map
    reader has two on coyomap's own map) drew an unlabelled list of circles. The names now sit once
    each in a sticky gutter, and the per-box label is gone.

    And the lanes did not line up: a nested box ended where its own steps ended, so the dashed line
    sat at a different height in every feature and read as a footnote to that feature. The board is
    one grid now — name row, happy-path row, other row — with each feature contributing CELLS to
    those shared rows and a `journey-zbg` cell behind them keeping one box per feature."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    zone = js[js.index("function journeyZoneHtml(z, opts) {"):
              js.index("\nfunction ", js.index("function journeyZoneHtml(z, opts) {") + 10)]
    # Cells in one shared grid, not a nested box: every cell names its column, and the tint rides
    # the backdrop cell that spans the three rows.
    assert "journey-zone" not in js, "the nested box is gone; the box is the journey-zbg cell"
    assert 'class="journey-zbg' in zone and 'grid-column:${col}${tint}' in zone
    for cell in ("journey-zlabel", "journey-track", "journey-sides"):
        assert f'class="{cell}' in zone, cell
    assert "grid-row: 1 / -1" in css and ".journey-zbg" in css
    for row, cell in ((1, "journey-zlabel"), (2, "journey-track"), (3, "journey-sides")):
        assert f".{cell} {{ grid-row: {row};" in css, cell
    # The upper lane is drawn even with no step in it, or the box under it would climb a row and
    # the dashed line would go crooked again. Empty, it must not draw a rail.
    assert ".journey-track:empty::before { display: none; }" in css
    # The rail runs PAST the first and last boxes, so it reads as one path through them rather than
    # as a rule belonging to each; the right tip ends in an arrowhead, which is where the walk ends.
    assert ".journey-track-first::before { left: -12px; }" in css
    assert ".journey-track-last::before { right: -20px; }" in css
    assert ".journey-track-last::after" in css and "border-left: 8px solid #4f46e5;" in css
    assert ".journey-gap-before { margin-left: 32px; }" in css, "…and the arrowhead ends in clear space"
    assert "o.offLane ?" in zone, "the lower lane is drawn for every box, or for none"
    assert "journey-alsolbl" not in js and "journey-alsolbl" not in css, "the per-box label is gone"
    assert ">also here:<" not in js, "…and so is the text it drew"
    # Named once, in a gutter that survives the board's sideways scroll \u2014 and named for BOTH boards
    # in one function, so the words exist once in the file rather than once per page.
    page = js[js.index("function renderActorPage(actorName) {"):
              js.index("\nfunction ", js.index("function renderActorPage(actorName) {") + 10)]
    rail = js[js.index("function journeyRailHtml(hasPath, offLane, boxes, partLane) {"):
              js.index("\nfunction ", js.index("function journeyRailHtml(hasPath, offLane, boxes, partLane) {") + 10)]
    assert ">Happy path<" in rail and ">Off the happy path<" in rail
    assert js.count(">Happy path</div>") == 1 and js.count(">Off the happy path</div>") == 1, \
        "one label each in the whole file, so a rename cannot land on one page only"
    assert ">Happy path<" not in page, "…and neither page writes them itself"
    assert ".journey-gutter { grid-column: 1; position: sticky; left: 0;" in css
    assert ".journey-gutter-off { grid-row: 3; border-top: 1px dashed" in css, \
        "the gutter carries the same cut, so the two lanes read as one band"
    # With the lanes named, everything the legend said was a label restated or a click taught.
    assert "journey-legend" not in js and "journey-legend" not in css
    # An actor with nothing off their happy path gets no empty band and no label for it.
    assert "const offLane = onRail.concat(off).some((b) => (b.z.sides || []).length);" in page
    assert "offLane ? ' journey-has-off' : ''" in rail
    assert (".journey-rail:not(.journey-has-off):not(.journey-has-part)"
            " .journey-track { padding-bottom: 12px; }") in css, \
        "with NEITHER lower lane the upper one closes the box itself"
    # The gutter is prose-shaped, so the glossary matcher must leave it alone like the other labels.
    assert ".journey-zkind, .journey-gutter'" in js



def test_the_actor_page_says_a_thing_once_and_never_out_of_order() -> None:
    """Four things this page drew are gone, and each for its own reason.

    The hero opened with the actor's place in the story ("2nd to appear"). The rail below already
    puts this actor's steps in the walk's order, left to right, so an actor whose first station
    opens the walk was told the same fact twice in two vocabularies. (The rail said it in figures
    too, until the step numbers came out; see
    `test_a_station_is_a_dot_and_a_title_with_no_step_number`.)

    A greyed BEFORE-segment drew the steps of the role this actor used to be (a `becomes`
    predecessor). It was untrue, not merely noisy: it drew EVERY step that role drives, wherever
    those sit in the walk, under a label reading "before". On the argus map the Page owner's own
    steps are 6, 9, 11, 15, 19, 20 and the Visitor's are 1, 2, 16, so step 16 was drawn as happening
    before step 6. The role change survives in the hero's "was <role> until <use case>" line, which
    states it once and has no order to get wrong.

    An arrowhead separated the features on this actor's happy path from the rest. It is redundant:
    a trailing feature's happy-path lane is EMPTY, and the rail visibly stops.

    And the legend explained the blocks, the two glyphs and the clicks. With the lanes named, every
    line of it restated a label or taught a click a reader finds by trying it.

    What stays is the "may also do everything a <role> may do" sentence — now a sentence, with only
    the other role's name a quiet link, because a pill reads as a control and this is a fact."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "ordinalWord" not in js and "to appear in the story" not in js
    page = js[js.index("function renderActorPage(actorName) {"):
              js.index("\nfunction ", js.index("function renderActorPage(actorName) {") + 10)]
    # The ghost is gone from the page, from the box builder and from the styles alike.
    assert "journey-ghost" not in js and "journey-ghost" not in css
    assert "o.ghost" not in js and "ghost: true" not in js
    assert "becomes" not in page, "the role change is the hero's line, not a segment of the rail"
    meta = js[js.index("function actorHeroMetaHtml(actorName) {"):
              js.index("\nfunction ", js.index("function actorHeroMetaHtml(actorName) {") + 10)]
    assert "rel.kind !== 'becomes'" in meta, "…and the hero still says it"
    assert "journey-endcap" not in js and "journey-endcap" not in css
    assert "▶" not in page, "…and the page draws no arrowhead"
    # The "may also do" line: a sentence carrying a link, not a pill.
    assert "journey-incpill" not in js and "journey-incpill" not in css
    assert "lead: 'may', tail: ' also do everything a '" in meta
    # …and the row reads as a sentence: the note that OPENS it takes a capital, and only that one, or
    # a capital would land after every dot in the middle of the row.
    assert "const cap = (w) => w.charAt(0).toUpperCase() + w.slice(1);" in meta
    assert "(i === 0 ? cap(p.lead) : p.lead)" in meta
    # The row is labelled like the sentence above it, from the same slot in the shared hero.
    hero = js[js.index("function actorPageHeroHtml(actorName) {"):
              js.index("\nfunction ", js.index("function actorPageHeroHtml(actorName) {") + 10)]
    # NO LABEL on that row any more. The whole hero dropped its labels (see the trail test): a
    # description on a page named after the thing being described does not need a word saying it is
    # one, and the role change already reads as a sentence — "Was Prospect until …", "Becomes …".
    assert "metaLbl" not in js and "'Notes:'" not in js
    assert "meta: actorHeroMetaHtml(actorName)," in hero
    # The role change is drawn from BOTH ends. It was read off the predecessor only, so the role who
    # turns into another said nothing about it: MCP Hero's Visitor page was silent about becoming an
    # Organization admin while the Organization admin page carried "was Visitor until ...".
    assert "rel.kind !== 'becomes' || rel.role === role.id" in meta, "…this role's own becomes"
    assert "lead: 'becomes'" in meta and "at(rel, 'at')" in meta
    assert "lead: 'was'" in meta and "at(rel, 'until')" in meta
    assert 'class="journey-inclink"' in meta and ".journey-inclink {" in css
    # THE SURFACES BLOCK'S HALF OF THIS TEST WENT WITH THE BLOCK: its picture, its two shore
    # headings, its per-surface grid row, the step lines in its crossings column. The page draws
    # one section now — the board — and names every interface on the use case that reaches it.
    # The FUNCTIONS are gone, not merely unreferenced — the note left where they stood names them,
    # so the test asks for the definitions and the call, never the bare string.
    assert "function actorSurfacesHtml(" not in js and "function bindActorSurfaces(" not in js
    assert "bindActorSurfaces(diagram" not in js, "…and nothing calls it"
    # The RULES, not the word: the note left where they stood names the class it removed.
    assert not re.search(r"^\\s*[.#][^{}\\n]*\\.asf-", css, re.M), "…and the rules that drew it"

def test_a_feature_the_happy_path_enters_twice_gets_two_boxes() -> None:
    """A happy path may leave a feature and come back to it later, and it does: measured on the four
    maps the current viewer reads, 4 of the 15 actor pages that have steps at all.

    Filing every station of a feature under that feature's FIRST appearance made the rail run
    backwards. On this project's own map the coyomap developer's rail read 21, 25, 22, 23, 24 —
    steps 21 and 25 are "Reviewing a finished build" and 22-24 are "Judging map quality". The rail
    is the one thing on the page that claims an order, so a zone is a RUN of consecutive stations in
    one feature, not that feature's whole set, and a twice-entered feature draws two boxes.

    The side stops still hang under the FIRST of those boxes: they belong to the feature, not to a
    position in the walk, and repeating them under each box would read as two of each."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    jrn = js[js.index("function actorJourney(actorName) {"):
             js.index("\nfunction ", js.index("function actorJourney(actorName) {") + 10)]
    assert "runsOf(stations, (s) => featureOfUc(s.uc))" in jrn, \
        "a zone is a RUN of consecutive stations, cut when the FEATURE changes"
    assert "zoneOf" not in jrn and "byFid" not in jrn, "the one-zone-per-feature index is gone"
    assert "for (const z of zones) if (!(z.fid in firstOf)) firstOf[z.fid] = z;" in jrn
    # Filed by ONE routine for both lower lanes now (`lane` is all that differs between the
    # callers), so the rule that a side stop hangs under its feature's FIRST zone cannot
    # drift away from the same rule for the third lane.
    assert "if (firstOf[fid]) { firstOf[fid][lane].push(uc); return; }" in jrn
    assert "for (const uc of ucs) if (!stationUcs.has(uc.id)) file(uc, 'sides');" in jrn


def test_every_state_field_survives_a_right_pane_navigation() -> None:
    """`pushContentPoint` rebuilds the current state field by field so opening a file keeps the screen
    you are on. Maintained by hand it dropped a field three times running (`store`/`entity`, then
    `blk`/`br`, then `cap`/`act`), and the failure is silent and sticky: the crumb keeps naming the
    level you were on while the pane renders the level ABOVE it, back/forward preserves the corrupted
    point, and the tab remembers it. So the list is derived from what `stateKey` actually reads."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    key = js[js.index("function stateKey(s) {"): js.index("\n}", js.index("function stateKey(s) {"))]
    read = set(re.findall(r"s\.([a-zA-Z]+)", key)) - {"kind"}
    decl = js[js.index("const STATE_FIELDS = ["):]
    declared = set(re.findall(r"'([a-zA-Z]+)'", decl[: decl.index("]")]))
    assert read == declared, f"stateKey reads {read - declared}, STATE_FIELDS declares {declared - read}"
    push = js[js.index("function pushContentPoint(content) {"): js.index("\n}", js.index("function pushContentPoint(content) {"))]
    assert "for (const f of STATE_FIELDS)" in push


def test_a_use_cases_crumb_names_the_card_it_was_listed_on() -> None:
    """A use case has TWO homes — its feature, and every actor who drives it — and the reader's own
    path picks one. The row carries the actor whose list it was opened from, so the trail runs through
    Actors; otherwise it runs through the feature. A use case in no feature still gets a card crumb, or
    that drill is the only one in the viewer no breadcrumb can undo.

    A THIRD case went with the axis: the trail used to GUESS an actor from a global switch for a use
    case reached some other way (a search, a Happy Path step), which put a card the reader never opened
    into their trail."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    anc = js[js.index("if (s.kind === 'usecase') {"):]
    anc = anc[: anc.index("\n  }")]
    # Both homes hang under Features now: through the actor's page, or through the feature's card.
    assert "if (s.act) return [{ kind: 'usecases' }, { kind: 'actor', act: s.act }," in anc
    assert "CAP_OF_UC[s.uc] ? CAP_OF_UC[s.uc].id : '-'" in anc
    assert "actorGroupOf" not in js, "no guessing an actor the reader never chose"


def test_a_feature_found_by_search_lands_on_its_card() -> None:
    """A feature is DRAWN as no box anywhere — it groups behaviour — so nothing can be selected for it.
    Without a case of its own it fell to the default and opened Dependencies, which is a confident wrong
    answer to a search hit the index itself labels a feature. Its home view is the card list that shows
    it, so a hit lands there and the card is scrolled to and ringed: the card-list half of "show in
    context", where a diagram would select and centre a box. An actor with no cast card to pin (a
    map with no features draws no story diagram) resolves to its own page — the one place left that
    shows it."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    target = js[js.index("function selectTargetFor(id) {"):
                js.index("\nfunction ", js.index("function selectTargetFor(id) {") + 10)]
    assert "return { state: { kind: 'usecases' }, selectId: null, flashId: id };" in target
    assert "return { state: { kind: 'actor', act: n.name } };" in target
    # The flash survives the navigation: it is stashed, and consumed by the render that draws the card.
    assert "pendingFlash = t.flashId;" in js
    assert "function applyPendingFlash() {" in js and "flashCard(id);" in js
    assert "if (cur0 && stateKey(cur0) === stateKey(t.state)) { flashCard(t.flashId); return; }" in js

def test_a_use_case_named_by_two_roles_is_listed_under_both() -> None:
    """Either named role can start it, so both cards must show it. Filing it under the first hid it
    from the other; giving the pair its own group drew a third card that read as a bug ("Organization
    admin (30)" beside "Organization admin and Team member (1)"). The group sizes therefore overlap
    and no longer sum to the use-case count, which is honest for the question a group answers.
    The crumb has to survive that: the row carries the actor whose list it was opened from, or a
    recomputed group could send the reader back to a list they never opened."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    body = js[js.index("function actorGroups() {"): js.index("\nfunction ", js.index("function actorGroups() {") + 10)]
    assert "for (const [key, title, role] of entries)" in body, "a use case must file under EVERY actor"
    assert "byActor[key].ucs.push(n)" in body
    # One undeclared name still sends the whole use case to Other: a half-known pair has no per-role home.
    assert "known ? names.map((nm, i) =>" in body and "[[OTHER, 'Other', null]]" in body
    # The carrier is the actor page's side stop now: the drill still says whose page it left from.
    # The shared rail binder passes it, and ONLY the actor page supplies one — a feature page's side
    # stop passes no actor, because with none the crumb already runs through the use case's feature.
    assert "if (opts.act) to.act = opts.act;" in js
    assert "bindJourney(root, { act: actorName });" in js


def test_the_group_by_switch_and_the_slot_it_lived_in_are_both_gone() -> None:
    """It moved twice — a header strip of its own, then beside the view tabs, then down with the cards —
    and each move made it a smaller problem without making it the right thing. It switched between
    features and actors on a view named Features, and both already had a view of their own.

    The header slot it once lived in went first, and stays gone: a slot that exists to host one control
    is chrome pretending to be a feature."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    assert "viewextra" not in js and "viewextra" not in html
    assert "switchHtml" not in js and "data-gb" not in js
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert ".uc-groupby" not in css, "the switch's styling goes with the switch"
    assert ".uc-seg" in css, "…but the segmented control it shaped is still worn by the Happy Path"

def test_the_breadcrumb_starts_under_the_active_tabs_label() -> None:
    """The alignment IS the design. The view row pads 10px and each tab pads 7px inside that, so the
    breadcrumb's 17px left padding lands its first segment exactly under the active tab's label — the
    path reads as starting from the tab it belongs to, rather than floating at the page edge."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    sub = css[css.index("#stagesubrow {"): css.index("}", css.index("#stagesubrow {"))]
    assert "padding: 0 10px" in sub
    tab = css[css.index("#viewsw button {"): css.index("}", css.index("#viewsw button {"))]
    assert "padding: 8px 7px 6px" in tab
    hint = css[css.index("\n.hint {"): css.index("}", css.index("\n.hint {"))]
    assert "padding: 6px 12px 7px 17px" in hint, "10px row + 7px tab = 17px"

def test_the_active_view_is_underlined_and_the_active_group_is_a_pill() -> None:
    """Two tab rows one above the other, and if both mark their active item the same way the reader
    cannot tell which level they are reading. The group is a pale pill on a tinted ground; the view is
    an underline on white. The underline also does a second job: it is the mark the breadcrumb below
    lines up with."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    grp = css[css.index("#groupsw button.active {"): css.index("}", css.index("#groupsw button.active {"))]
    assert "#e0e7ff" in grp and "#3730a3" in grp
    view = css[css.index("#viewsw button.active {"): css.index("}", css.index("#viewsw button.active {"))]
    assert "border-bottom-color: #6366f1" in view and "background" not in view

def test_no_control_outlives_the_view_that_drew_it() -> None:
    """A view's own controls are drawn by that view's renderer into the view's own content, so moving
    to another view cannot leave one behind: the content is replaced whole. This used to need a header
    slot cleared on every render, which is the mechanism the floating flow picker also needs — and that
    one still does, because it floats over the diagram rather than living in it."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    render = js[js.index("  syncFlowCard(s);"):]
    assert "syncFlowCard(s);" in render[:400], "the step player's card is settled up front"
    assert "uc-groupby-why" not in js
    assert "function viewQuestion(view) {" in js

def test_one_question_in_one_place_on_every_view() -> None:
    """A view's question is the same sentence at every depth inside that view, read from ONE table by
    the top view, so it is a property of the VIEW and can never change as the reader drills. Where it is
    DRAWN has moved five times: the info pane (only diagrams had one, and it vanished on the first
    click), the first block of the page (read as a caption, and each page began inventing its own),
    beside the view tabs (upright at tab size, it read as a fifth disabled tab), the trail row beside the
    page title, and then two places at once — beside the title on a diagram, leading the page on prose.

    Two places was the mistake this fixes. One sentence looked like two different things depending on
    which tab you were on: 12.5px hung off an em dash next to a diagram's title, 14px on its own line
    over a page of cards. Nothing about a diagram or a page explained the difference, and beside the
    title it read as chrome ABOUT the page rather than as the page's own opening words.

    It is the last line OF the header block now, on every view: the content's own text size, left edge
    and reading cap, italic because nothing else in this app is. Inside the fixed block, so the block's
    shadow falls below it: the tabs, the trail and the question all name the VIEW, and everything under
    the shadow is the page. On a diagram that is the whole point — a question stranded under the shadow
    read as a caption floating over the map. It is still outside the content's scroll, so it can never
    become a caption for whichever block ends up under it, which is what the spec undid.

    Shown ONLY on the view's own landing screen, which is exactly a one-item trail: every trail starts at
    its view. One level in, the reader has chosen something and is past asking what the view is for."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    # ONE element, and the trail row is back to carrying nothing but the trail.
    assert "viewq" not in js and "viewq" not in html, "the second copy is deleted, not hidden"
    assert "#viewq" not in css
    crumbrow = html[html.index('<nav class="hint" id="crumbrow"'):
                    html.index("</nav>", html.index('<nav class="hint" id="crumbrow"'))]
    assert 'id="crumb"' in crumbrow and 'pageq' not in crumbrow, "the trail row is the trail alone"
    # THE FIXED BLOCK'S OWN LINE IS GONE TOO. The question is the sentence of the LANDING CARD — the
    # same card an item page leads with (name, a count pill, one sentence; no figure and no type word,
    # which is what tells a landing card from an item's) — drawn in the page by syncPageHero, so a
    # landing screen and an item page are one object. It scrolls with the page, as an item's card does.
    assert "pageq" not in html and "#pageq" not in css and "pageq" not in js, "retired, not hidden"
    chrome = js[js.index("function renderChrome(s) {"):
                js.index("\nfunction ", js.index("function renderChrome(s) {") + 10)]
    assert "const q = chain.length === 1 ? viewQuestion(tv) : '';" in chrome, \
        "a one-item trail IS the view's own landing screen"
    assert "syncPageHero(s, chain, q ? tv : '');" in chrome, "…and only that screen gets the landing card"
    landing = js[js.index("function landingHeadHtml(view) {"): js.index("\n}", js.index("function landingHeadHtml(view) {"))]
    assert "itemSectionHeadHtml(name, n, q)" in landing, "the one section-head builder: name, count, question"
    assert "LANDING_COUNT[view]" in landing, "how many of the view's things the map holds"
    assert ".landing-head .item-sec-title { font-size: 16px; }" in css, "the page's title, at an item name's size"
    sync = js[js.index("function syncPageHero(s, chain, tv) {"): js.index("\n}", js.index("function syncPageHero(s, chain, tv) {"))]
    assert "const landing = chain.length === 1 && !walk && !id ? landingHeadHtml(tv) : '';" in sync
    assert "diagram.querySelector('.usecases-wrap, .glossary-wrap')" in sync, "into the page's column…"
    assert "first.querySelector('.item-sec-strip').innerHTML = landing;" in sync, "…as its first section's strip…"
    assert "sec.className = 'item-sec item-sec-landing';" in sync, "…or wrapping loose blocks into one section…"
    assert "if (inHead) { diaghead.innerHTML = inHead; diaghead.hidden = false; }" in sync, \
        "…or above the drawing, in the walk's head host, where the landing is a picture"
    assert "#stage:has(#diaghead .item-sec-strip-stage) #diagwrap" in css, \
        "the frame joins the strip, not any head — a landing card over a picture leaves the frame whole"
    intro = js[js.index("function viewIntroHtml(view) {"):
               js.index("\nfunction ", js.index("function viewIntroHtml(view) {") + 10)]
    assert "viewQuestion" not in intro

def test_the_header_block_casts_a_shadow_so_it_reads_as_fixed() -> None:
    """The tab rows and the trail stay put while everything under them scrolls, pans and zooms. A
    hairline alone did not say so: it read as one more divider in a page full of them, and on a diagram
    the shapes simply slid under it with nothing to mark the boundary they passed.

    So the block casts a shadow onto whatever passes beneath it. The view's question is part of that
    block, not of the page: the tabs, the trail and the question all name the VIEW, so the shadow falls
    below all three and everything under it is content. The block therefore paints its own background
    across the full width, or the question's reading cap would leave a pale strip beside it."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    head = css[css.index("#stagehead {"): css.index("}", css.index("#stagehead {"))]
    assert "box-shadow" in head, "the fixed block has to say it is fixed"
    assert "z-index" in head, "…and sit above what passes under it"
    assert "background:" in head, "…and paint the whole block, not just the rows that set their own"
    block = html[html.index('<div id="stagehead">'): html.index('<div id="diagwrap">')]
    assert 'id="pagehero"' in block, "the drilled page's hero is above the shadow, with the tabs and the trail"

def test_the_page_you_drilled_into_says_what_it_is_in_the_header_not_in_the_card() -> None:
    """A page you have drilled into is ABOUT one element, and that element used to be shown by filling
    the floating selection card with it whenever nothing was selected. One floating card then carried
    two meanings — "the page you are on" and "the box you just clicked" — with nothing inside it saying
    which; deselecting swapped the content silently, and the card's close button was undone by the next
    navigation.

    So the subject moved into a PAGE HERO in the fixed header block, where the tabs and the trail already
    say where you are, and the card was left meaning exactly one thing: what you clicked.

    Its place is the block's LAST line, so #stagehead's shadow falls below it — the hero is chrome, and
    everything under the shadow is the drawing. It draws no rule of its own: a hairline one pixel above
    that shadow says the same thing twice. It never shares the line with the view's question, which is
    the landing screen's alone.

    Three subjects, and only three. The other default cards are CONTENT, not an echo of the page title:
    an arrow page's card is the list of concrete arrows it bundles, a process card carries its fields and
    its threads, the Deployment overview surfaces unplaced threads, a diff overview leads with the change
    summary. Moving those into a strip above the diagram would only shrink the drawing."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    # STUCK TO THE NAVIGATION HEADER: inside #stagehead, and its last line.
    head = html[html.index('<div id="stagehead">'): html.index('<div id="diagwrap">')]
    assert '<div id="pagehero" hidden></div>' in head, "the hero is part of the fixed block"
    assert head.index('id="pagehero"') > head.index('id="crumbrow"'), \
        "…and its last line, so the block's shadow falls below it"
    # THE SHADE IS THE BLOCK'S. The hero adds no border of its own, and the shared hero's closing rule
    # is switched off here.
    hero = css[css.index("#pagehero {"): css.index("#pagehero .ecard-extra")]
    assert "border-bottom" not in hero.split("#pagehero .page-hero {")[0], \
        "the block's shadow is the line under the hero"
    assert "#pagehero .page-hero { padding: 0; border-bottom: 0;" in css, \
        "the shared hero's own rule would sit a hairline above the shadow"
    assert "padding: 9px 20px 12px" in hero, "the question's left edge, and a bottom that closes the block"
    # ONE hero builder for the whole app: the header hero calls the same one the element pages call.
    sub = js[js.index("function heroSubjectHtml(id, chain) {"):
             js.index("\n}", js.index("function heroSubjectHtml(id, chain) {"))]
    assert "pageHeroHtml({" in sub, "one hero design, not a second one built by hand"
    assert "cardFacts(id)" in sub, "…reading the same sentence the element's own card reads"
    assert "kindPillsExtra(n)" in sub, "only what the breadcrumb's own pills did not already say"
    # THE SAME CARD every page about one element leads with: the kind's mark in the left column, the
    # type as a word before the name, the pills that vary within the kind. It repeats the breadcrumb
    # on purpose — the breadcrumb is the app's chrome and reads as a path.
    assert "type: c.type" in sub and "name: c.name" in sub and "glyph: elementHeroGlyph(n.kind)" in sub
    assert "cardPillsHtml" not in sub, "the type is the word before the name, not a pill after it"
    # FOUR element subjects, named in one place — and the lookup itself is the one the breadcrumb's pills
    # already use, so the trail and the hero cannot disagree about what a page is showing.
    kinds = js[js.index("const HERO_KINDS = new Set("):
               js.index(");", js.index("const HERO_KINDS = new Set("))]
    for kind in ("subsystem", "domsub", "usecase", "deploymentUnit"):
        assert f"'{kind}'" in kinds
    for kind in ("edge", "bridge", "deployment'"):
        assert f"'{kind}'" not in kinds, "an arrow pair is not one element"
    subj = js[js.index("function heroSubjectId(s) {"):
              js.index("\n}", js.index("function heroSubjectId(s) {"))]
    assert "pageElementId(s)" in subj, "one answer to `which element is this page about`"
    # …and the card no longer draws them.
    body = js[js.index("function applyDefaultPanelBody(s) {"):
              js.index("\n}", js.index("function applyDefaultPanelBody(s) {"))]
    assert "if (hero) {" in body and "panel.innerHTML = ''; return; }" in body, \
        "nothing selected on those pages means no card at all"
    assert "showNode(s.sid)" not in body and "showUseCase(s.uc)" not in body, \
        "the page's own subject is the hero's job now"
    assert "syncTreeToNode(hero)" in body, \
        "…but a drilled subsystem must still light its own folder in the file browser"


def test_a_process_details_page_does_not_print_the_process_name_twice() -> None:
    """A process now has two pages: the one on the Deployment view, which draws where it runs, and its
    details page, which holds everything the map records about it. The details page hangs under the page
    its element lives on — which for a process is a page about that same process. So both crumbs printed
    its name and the trail read `Deployment › api › api`: two crumbs, one word, nothing saying which is
    which.

    The second crumb says what it ADDS instead. Every other element hangs under a DIFFERENT element (a
    component under its subsystem), where the name is the right title and the trail reads as a path."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    title = js[js.index("  if (s.kind === 'element') {"):
               js.index("\n  }", js.index("  if (s.kind === 'element') {"))]
    assert "'process' ? 'Details' : elName(s.id)" in title


def test_a_page_that_draws_its_own_contents_does_not_also_list_them_in_a_card() -> None:
    """Five more pages opened with a card that restated the page. An arrow page's card was the LIST of the
    concrete arrows the drawn arrow bundles, and the page is a diagram of exactly those arrows between the
    two boxes opened up. A folded group's card was the roster of its members, and the page draws every
    member as a box. Both listed, over the top of the drawing, what the drawing was already saying.

    So all five lose the card. Each arrow still says its own detail when the reader clicks it, and each
    member still opens when its box is clicked.

    What the drawing does NOT say about a fold is what was folded and out of which view, so that sentence
    is the hero. It is not the sentence the collapsed box shows on the Dependencies view: that one ends
    "⌥-click to drill in", which told a reader who had already drilled in to do it again.

    TWO pages keep their card, because neither one's card is the page's title or the page's drawing: the
    Deployment overview surfaces the threads that landed on NO process box, and a diff render leads with
    what changed. Both are facts the reader cannot get by looking."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    body = js[js.index("function applyDefaultPanelBody(s) {"):
              js.index("\n}", js.index("function applyDefaultPanelBody(s) {"))]
    for gone in ("showContainerEdge(s.a", "showDomainContainerEdge(s.a", "showBridge(s.sid",
                 "showDeploymentUnit(s.unit)", "showLibsFold()", "showBucketFold(s.bkid)"):
        assert gone not in body, gone
    assert "showDeployment(); return;" in body, "the unplaced threads are on no box, so they keep the card"
    assert "IMPACT) showImpactSummary();" in body, "an armed impact overlay leads with what it hits"
    assert "showDiffSummary" not in js, "the baked report's summary card is gone with the report"
    # The three arrow builders live on: they are what a SELECTED arrow shows, which is the card's one job.
    for kept in ("function showContainerEdge(", "function showDomainContainerEdge(", "function showBridgeEdge(",
                 "function showLibsFold(", "function showBucketFold("):
        assert kept in js, kept
    # The fold's sentence, in one place, and without the instruction the box's own sentence carries.
    # It describes the DRAWING, so it is the strip's note now rather than the hero's — the hero carries
    # the fold's NAME, which used to be nowhere on screen at all.
    fold = js[js.index("const FOLD_NARRATIVE = {"): js.index("};", js.index("const FOLD_NARRATIVE = {"))]
    assert "libs: () =>" in fold and "bucketfold: (s) =>" in fold
    assert "drill in" not in fold, "the reader is already inside"
    assert "Dependencies view" in fold, "the reader's word for the tab, not the code's `Context`"
    # A library bucket is not an external system: one sentence for both bucket folds made `Frontend / UI`
    # — reached through `Dependencies › Libraries ›` — announce itself as external systems.
    assert "bucketFoldParent(s.bkid) === 'libs'" in fold, "each bucket fold says what it actually holds"
    assert "Libraries with one job in common" in fold and "External systems grouped by purpose" in fold
    head = js[js.index("function foldBoardHeadHtml(s) {"):
              js.index("\n}", js.index("function foldBoardHeadHtml(s) {"))]
    assert "itemSectionHeadHtml('What is folded here'" in head, "the one section-head builder"
    assert "FOLD_NARRATIVE[s.kind](s)" in head, "the sentence is the strip's note"
    assert "countLabel(n, 'dependency')" in head, "counted in the Dependencies tab's own noun"
    hero = js[js.index("function syncPageHero(s, chain, tv) {"):
              js.index("\n}", js.index("function syncPageHero(s, chain, tv) {"))]
    assert "FOLD_NARRATIVE[s && s.kind]" in hero
    assert "pageHeroHtml({ name: stateTitle(s), desc: '', noDesc: false })" in hero, \
        "the hero is the fold's name; the sentence went down to the strip"
    assert "inHead = stageStripHtml(foldBoardHeadHtml(s));" in hero


def test_an_arrow_page_opens_on_the_drawing_with_nothing_chosen_for_you() -> None:
    """Opening a bundled arrow used to carry `selCover` — the real arrows that one drawn arrow stood for —
    so the page arrived with them selected and their cards stacked over the drawing. Measured on one pair:
    2 of the 2 arrow groups on the page were selected, which marks nothing out, and the stack ran 9
    connections deep, taking 26% of the drawing area and 97% of its height.

    The page is ABOUT that arrow, so opening it is not a request to pick something on it out. All three
    arrow drills stop making a selection of the ARROWS.

    Three pre-selections are untouched, because each points at ONE thing among many: `sels`, the reader's
    own selection coming back through history, the `selCover` a LOCATE carries, and — since the arrow
    card's title became the way in — the one MEMBER a member's cross arrow names, which pairPageDrill
    selects and centres on the pair page (see test_the_subsystems_pictures_take_the_data_pictures_gestures)."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    for binder in ("function bindContainerEdge(", "function bindDomainContainerEdge(",
                   "function bindBridgeEdge("):
        body = js[js.index(binder): js.index("\n}", js.index(binder))]
        # the ASSIGNMENT, not the word — each binder's comment says what it stopped doing, and why.
        assert ".selCover =" not in body and "selCover:" not in body, binder
        assert ".sel = 'node:" not in body, binder
    # …and the two that stay.
    keys = js[js.index("function selectionKeysFor(scene, s) {"):
              js.index("\n}", js.index("function selectionKeysFor(scene, s) {"))]
    assert "s.sels" in keys and "s.selCover" in keys, "history and locate still restore a selection"
    # NOTHING WRITES `selCover` ANY MORE. The one drill that carried it was an ARROW's locate icon, and
    # arrows draw no icon at all now — so `relationshipLocateTarget` and `bundleAtoms`, which existed
    # only to build that state, are gone. The READ above is kept, guarded: it is the resolve-after-render
    # half, waiting for a future drill that stands for several arrows.
    assert "function relationshipLocateTarget" not in js and "function bundleAtoms" not in js
    # The leaf is still CENTRED on a bridge drill — putting the reader in front of what they opened is
    # not the same as choosing something for them.
    bridge = js[js.index("function bindBridgeEdge("): js.index("\n}", js.index("function bindBridgeEdge("))]
    assert "pendingCenter = leaf" in bridge


def test_every_arrow_is_drawn_the_same_and_every_arrow_answers_a_click() -> None:
    """A bundled arrow used to be dashed and a touch thicker, and to show no card at all. Both are gone.

    THE DASH WAS NOT TRUE EVERYWHERE. On the Deployment view it went on before the code decided what kind
    of arrow it was, so one dash marked an arrow standing for 25 links, one standing for 1, and one
    standing for nothing. A reader who met that view had learned the dash means nothing.

    AND THE SILENCE COST FACTS. "Its card is a list, and its page draws the same links" was true of a
    subsystem pair and never true of a Deployment arrow, whose members are drawn nowhere: 64 of those
    arrows stand for 246 links, and that list was their only home.

    So every arrow is drawn the same, and a click on any of them shows what it stands for. A click is also
    the easiest gesture on the thinnest target, so it is the one that should answer "what is this".

    What survives is the LABEL — a verb where the arrow is one link, a count where it is several. The
    generator drops a count of "1" for the same reason the dash went: measured over three maps, 1118 of
    the 1801 counts on 8012 labelled arrows said "1"."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "markSyntheticEdge" not in js and "SYN_EDGE" not in js and "data-syn" not in js
    bind = js[js.index("function bindSelectEdge(scene, p, label, e, selKey, showFn, opts) {"):
              js.index("\n}", js.index("function bindSelectEdge(scene, p, label, e, selKey, showFn, opts) {"))]
    assert "edgeDesc(scene, p, label, e, selKey, showFn, opts.anchor)" in bind, "no arrow is filtered out of its card"
    stack = js[js.index("function renderSelPanel(scene) {"):
               js.index("\n}", js.index("function renderSelPanel(scene) {"))]
    assert "if (!d.show) continue;" in stack, "kept as a guard: an empty card must never be appended"
    assert "dashed arrow" not in js, "the legend stops naming a language the drawing no longer speaks"


def test_a_line_joins_the_card_to_the_one_element_it_describes() -> None:
    """Two things already join the card to its element: the card's title is the element's name, and the
    selected element is the only bright thing left once the rest dims. Measured over 26 selections on two
    pages, the gap between them ran 11px to 915px, with a middle value of 379px — so on a wide drawing the
    reader has to carry the name across the screen. The line is the third link, for that case.

    SINGLE SELECTION ONLY. Selecting five boxes stacks five cards; five lines fanning out of a panel that
    already fills 97% of the drawing's height is worse than no line.

    Screen coordinates throughout: the card lives in the page's pixels and the element in the diagram's,
    so there is no shared space to draw in. Both are read back as client rects, and the layer is pinned
    over the drawing area to make the two comparable.

    The layer sits UNDER the card (z-index 3 against the card's 4) so the line ends at the card's edge
    rather than crossing its face, and it catches no clicks."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    wrap = html[html.index('<div id="diagwrap">'): html.index("</div>\n    </div>", html.index('<div id="diagwrap">'))]
    assert '<svg id="callout"' in wrap, "its own layer, inside the box both ends are measured in"
    assert wrap.index('id="callout"') < wrap.index('id="panel"'), "…and under the card, not over it"
    lay = css[css.index("#callout {"): css.index("}", css.index("#callout {"))]
    assert "z-index: 3" in lay and "pointer-events: none" in lay
    pan = css[css.index("#panel {"): css.index("}", css.index("#panel {"))]
    assert "z-index: 4" in pan, "the card stays above the line that reaches it"
    # ONE subject, or none. `.is-selected` is put on a box by glowNode and on an arrow by glowEdge, so
    # one query covers both — an arrow selection could not answer this before.
    sole = js[js.index("function soleSelectedEl() {"): js.index("\n}", js.index("function soleSelectedEl() {"))]
    assert "diagram.querySelectorAll('.is-selected')" in sole and "els.length === 1 ? els[0] : null" in sole
    edge = js[js.index("function glowEdge(p, label, revealAction = true) {"):
              js.index("\n}", js.index("function glowEdge(p, label, revealAction = true) {"))]
    assert "p.classList.add('is-selected')" in edge and "p.classList.remove('is-selected')" in edge
    # The `hidden` PROPERTY does not exist on an SVG element, so the attribute is set on both sides.
    hide = js[js.index("function hideCallout() {"): js.index("\n}", js.index("function hideCallout() {"))]
    assert "callout.setAttribute('hidden', '')" in hide
    draw = js[js.index("function syncCallout() {"): js.index("\n}", js.index("function syncCallout() {"))]
    assert "callout.removeAttribute('hidden')" in draw, "`callout.hidden = false` leaves the attribute on"
    assert "co-case" in draw and "co-line" in draw, "a white casing under the blue line, or it vanishes"
    assert "hideCallout(); return;" in draw, "an element scrolled out of the drawing has no end to point at"
    # It is redrawn wherever EITHER end can move — and a CAMERA move is measured a frame late on purpose.
    assert "onPan: () => scheduleCallout(false)," in js, "the element end travels with the drawing"
    zoom = js[js.index("function updateZoomLevel() {"): js.index("\n}", js.index("function updateZoomLevel() {"))]
    assert "scheduleCallout(false);" in zoom
    drag = js[js.index("PANEL_HOST.addEventListener('pointermove'"):
              js.index("});", js.index("PANEL_HOST.addEventListener('pointermove'"))]
    assert "syncCallout();" in drag and "placeCardNear" not in drag, \
        "the line follows a drag directly; the dodge must not fight the hand that is dragging"
    # The card end is pure DOM and needs no wait, which is why the drag calls syncCallout straight.
    pane = js[js.index("function syncInfoPane(_s, transient) {"):
              js.index("\n}", js.index("function syncInfoPane(_s, transient) {"))]
    assert pane.index("hideCallout();") < pane.index("if (transient) return;"), \
        "a drill animation's frames must not keep a line pointing into the diagram being replaced"


def test_the_line_never_outlives_the_card() -> None:
    """Three places took the card away and only ONE of them told the line, so deselecting left a line
    hanging off the corner of the screen pointing at nothing: clicking empty canvas, the card's own ×, and
    selecting a synthetic arrow (which has no card to show) all went through `paneSync`'s no-card return,
    which drew nothing and cleared nothing.

    They all come through one rule now. `paneSync` is the ONE function that hides the card, and it is what
    hides the line with it — the × and the navigation reset route through it instead of hiding by hand.

    Verified in the app for all three: after selecting a box, card and line both present; after a canvas
    click, after the × and after Escape, both gone and the layer emptied."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fn = js[js.index("function paneSync() {"): js.index("\n}", js.index("function paneSync() {"))]
    assert "if (!has) { hideCallout(); return; }" in fn, "no card, no line — on the path every deselect takes"
    # …and nothing else hides the card behind paneSync's back.
    assert js.count("PANEL_HOST.hidden = true") == 0, "one rule: paneSync is what takes the card away"
    close = js[js.index("if (!ev.target || !ev.target.closest || !ev.target.closest('#panelclose')) return;"):
               js.index("});", js.index("if (!ev.target || !ev.target.closest || !ev.target.closest('#panelclose')) return;"))]
    assert "PANEL_HOST.innerHTML = '';" in close and "paneSync();" in close
    pane = js[js.index("function syncInfoPane(_s, transient) {"):
              js.index("\n}", js.index("function syncInfoPane(_s, transient) {"))]
    assert "paneSync();" in pane


def test_a_camera_move_is_measured_after_it_is_painted() -> None:
    """svg-pan-zoom calls onPan / onZoom from inside setCTM and only THEN schedules the frame that paints
    the new transform — the trap `applyZoomAndCenter` already documents for zoom(). Measuring in that
    callback reads the camera the reader has already left, and nothing came along to correct it.

    Measured with the line drawn synchronously: after "Fit to screen" the dot sat 273px from the box it
    pointed at, after a drag-pan 119px, after opening the source column 255px.

    TWO frames, not one. The library registers ITS frame after ours, so a single requestAnimationFrame
    still runs before the paint; the second frame is the first that can measure it.

    The same lateness hit the DODGE: `window resize` schedules a refit and then places the card, so the
    overlap test ran against the pre-refit layout, found none, and left the card sitting on the very
    element it describes. So the deferred pass re-dodges as well as re-draws."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    sch = js[js.index("function scheduleCallout(alsoDodge) {"):
             js.index("\n}", js.index("function scheduleCallout(alsoDodge) {"))]
    assert sch.count("requestAnimationFrame") == 2, "one frame still lands before the library paints"
    assert "if (calloutRaf) return;" in sch, "coalesced to one pass per burst of camera events"
    assert "if (dodge) placeCardNear(soleSelectedEl());" in sch and "syncCallout();" in sch
    place = js[js.index("function placeCard() {"): js.index("\n}", js.index("function placeCard() {"))]
    assert "scheduleCallout(true);" in place, "…so a refit scheduled beside this one is caught too"


def test_a_click_on_the_cards_bar_is_not_a_drag() -> None:
    """`pointerdown` on the grab bar arms the gesture with no movement threshold, so a bare CLICK on the
    bar saved wherever the card happened to be — and after a dodge that is not where the reader put it.

    Measured: six taps on the bar, each after selecting a covered box, walked the stored position from
    top 60 to top 275 and left 300 to left 394. Exactly the accumulation `placeCardNear` refuses to cause,
    arriving through the one path that does save."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    move = js[js.index("PANEL_HOST.addEventListener('pointermove'"):
              js.index("});", js.index("PANEL_HOST.addEventListener('pointermove'"))]
    assert "d.moved = true;" in move, "only an actual move marks the gesture as one"
    end = js[js.index("const endPanelDrag = () => {"): js.index("\n};", js.index("const endPanelDrag = () => {"))]
    assert "const moved = panelDrag.moved;" in end and "if (moved) noteCardPlace();" in end


def test_the_line_points_at_an_arrows_own_middle_not_its_boxs() -> None:
    """A curve's bounding box is not the curve. A bowed arrow, and a self-arrow looping back to its own
    box, both leave their box centre in empty canvas. Measured over six curved arrows on one page, the
    box centre sat 3 to 88 pixels off the ink; walking the drawn geometry puts the dot on it exactly.

    A self-loop is three separate paths, so the lengths are walked as ONE — the middle of the whole
    shape, not of whichever piece comes first."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fn = js[js.index("function arrowMidpoint(el) {"): js.index("\n}", js.index("function arrowMidpoint(el) {"))]
    assert "getTotalLength" in fn and "getPointAtLength" in fn
    assert "(el && el._segs) || [el]" in fn, "a self-arrow is three paths walked as one length"
    assert "getScreenCTM()" in fn, "the path's own numbers are in the diagram's units, which pan and zoom"
    assert "if (!total) return null;" in fn, "a box has no length — the caller falls back to its border"
    draw = js[js.index("function syncCallout() {"): js.index("\n}", js.index("function syncCallout() {"))]
    assert "const mid = arrowMidpoint(el);" in draw
    assert "b = mid || borderPoint(e, pc)" in draw, "an arrow points at its middle, a box at its border"


def test_a_step_number_sits_at_the_middle_of_its_arrow() -> None:
    """The layout engine puts an arrow's label half way between the two boxes' COLUMNS, and never asks
    how far the curve travels up or down on the way. On a use case map the label IS the step number, so
    a number sat 15% along one arrow and 88% along the next — measured on mcpolis UC1, 5 of its 17
    numbers were more than 15px from the middle, 31px at worst.

    The callout already lands half way ALONG the drawn curve (arrowMidpoint), so the label is moved to
    that same point, once per render and before anything binds to it or measures it: the pill beside
    a label and the line to a number both read the label's place, so a label moved after them would
    leave both pointing at where it used to be."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fn = js[js.index("function centreEdgeLabels(root) {"): js.index("\n}", js.index("function centreEdgeLabels(root) {"))]
    assert "getPointAtLength(len / 2)" in fn, "the point half way along the curve — the same point arrowMidpoint lands on"
    assert "pointToHostSpace(p, mid.x, mid.y, label.parentNode)" in fn, "the label's translate is in its parent's space"
    assert "label.setAttribute('transform', `translate(${at.x}, ${at.y})`)" in fn
    assert "if (loops[i] || !edgeLabelHasContent(label)) return;" in fn, \
        "a self-arrow keeps the engine's place; an empty label has nothing to move"
    render = js[js.index("async function renderView(sArg, transient, seq) {"): js.index("\n}", js.index("async function renderView(sArg, transient, seq) {"))]
    assert render.index("diagram.innerHTML = svg;") < render.index("centreEdgeLabels(diagram);") < render.index("bindFor(s);"), \
        "moved after the drawing is on screen and before anything binds to it"
    channels = js[js.index("function dvRenderChannels("): js.index("function dvShow(")]
    assert "centreEdgeLabels(ph);" in channels, "the Storage tab's small pictures are drawn by the same engine"


def test_a_named_hero_sits_on_a_white_band_with_the_shared_hero_s_own_text_sizes() -> None:
    """Measured before the band, the name in an actor's hero was 16px over section headings of 14px,
    on the same ground — so the page's subject and its first section weighed the same. A named hero
    now sits on a white card with a hairline, the width of the frames under it.

    A wash of the kind's colour and a 24px name were built and dropped as too loud: the card keeps the
    shared hero's own sizes and no colour of its own. ONLY the named pages get it: an arrow page, an
    entry-point kind and the fixed block over a drawing lead with nothing, and stay plain."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    hero = js[js.index("function pageHeroHtml(o) {"): js.index("\n}", js.index("function pageHeroHtml(o) {"))]
    assert "return `<div class=\"page-hero${o.name ? ' page-hero-band' : ''}${figure ? ' page-hero-figured' : ''}\">`" in hero, \
        "the band is the NAMED hero's shape, and nothing else decides it"
    # THE FIGURE IS A COLUMN of the card, at its full height in the left margin, and the text is one
    # block beside it. Only a named hero with a figure takes this shape; the others keep one column.
    assert "const figure = o.name && o.glyph ? `<div class=\"page-hero-glyph\">${o.glyph}</div>` : '';" in hero
    assert "(figure ? figure + `<div class=\"page-hero-body\">${body}</div>` : body)" in hero
    assert ".page-hero-figured { display: flex; align-items: stretch;" in css
    assert "#diaghead .page-hero-glyph .story-glyph, #diaghead .page-hero-glyph .ibox-gly { width: 100%; height: 100%; }" in css, \
        "the figure fills its column, over the small sizes the hosts pin"
    assert "HERO_TINTS" not in js and "heroWash" not in js and "--hero-tint" not in css, "no colour of its own"
    band = css[css.index("\n.page-hero-band {"): css.index("}", css.index("\n.page-hero-band {"))]
    assert "background: #fff" in band and "border: 1px solid #cbd5e1" in band and "border-radius: 12px" in band, \
        "the same white card and hairline the section frames have"
    assert ".page-hero-band .page-hero-subject" not in css and ".page-hero-band .page-hero-purpose" not in css, \
        "the text keeps the shared hero's own sizes"
    assert "#diaghead .page-hero-band, .usecases-wrap:has(> .tab-index) > .page-hero-band { margin-top: 16px; }" in css, \
        "the hosts that keep no air above the band get the same 16px the actor page's column has"


def test_a_hero_says_its_type_in_a_word_before_the_name_not_in_a_pill_after_it() -> None:
    """`Actor: Prospect`, `Use case: Weigh up the product`. Read left to right the row says what kind
    of page this is before it says which one, and the pills that stay are the ones that vary within
    the kind (`staff`, `user service`) — the type pill went, since the word already says it.

    Every named page passes its type from the one table that names element kinds (ELEMENT_LABEL),
    and its side pills from the one function that draws a card's pills after the type one — so a
    card and the page one click later cannot name two different kinds of the same thing."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    hero = js[js.index("function pageHeroHtml(o) {"): js.index("\n}", js.index("function pageHeroHtml(o) {"))]
    assert "const kind = o.type ? `<span class=\"page-hero-kind\">${esc(sentenceCase(o.type))}:</span>` : '';" in hero
    assert "`<p class=\"page-hero-name\">${figure ? '' : (o.glyph || '')}${kind}`" in hero, "type word, then the name"
    side = js[js.index("function elementSidePillsHtml(id) {"): js.index("\n}", js.index("function elementSidePillsHtml(id) {"))]
    assert "c.type" not in side, "the pills after the type one"
    pills = js[js.index("function elementPillsHtml(id) {"): js.index("\n}", js.index("function elementPillsHtml(id) {"))]
    assert "+ elementSidePillsHtml(id)" in pills, "a card's pills are the type one plus the same side pills"
    for want in ("type: elementLabel('human'),", "type: elementLabel('capability'),", "type: elementLabel('interface'),",
                 "type: elementLabel('block'),", "type: sub ? 'shared sub-use case' : elementLabel('usecase'),"):
        assert want in js, want
    assert js.count("pills: elementSidePillsHtml(") == 3, "actor, feature and decision area draw only their side pills"
    assert "pills: sub ? '' : elementSidePillsHtml(id)" in js
    assert ".page-hero-kind { font-size: 16px; font-weight: 500;" in css, "the name's size, a quieter weight"


def test_which_interfaces_a_use_case_reaches_is_read_from_the_bundle_not_re_derived() -> None:
    """ONE RULE, decided in Python (`use_case_interfaces`, model.py) and shipped as
    `useCaseInterfaces`: a step of the use case's flow drawn at the surface, or at a dependency the
    surface stands on, sub-flows expanded. The Interfaces picture's order, an interface's use cases,
    its far side and the viewer's use case cards all read it, so none can drift from the others.

    The viewer used to re-derive it from the steps, and had already drifted: it never counted a step
    drawn at a dependency the surface stands on, which the Python did. What it still reads off the
    steps is WHO stands at each interface — a role carries no id on a step, so that is a name join,
    not the reach rule."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fn = js[js.index("function flowUcIfaces() {"): js.index("\n}", js.index("function flowUcIfaces() {"))]
    assert "const reach = FEATURES.useCaseInterfaces || {};" in fn
    assert "new Set((reach[uc].list || []).filter((id) => rank.has(id)))" in fn, "the reach, from the bundle"
    assert "new Set((reach[uc].sub || []).filter((id) => rank.has(id)))" in fn, "…and which came only from a sub-flow"
    assert "sfChips" not in fn and "if (rank.has(id)) hit.add(id)" not in fn, "no second derivation of the reach"
    assert "near(st.srcId, st.src, st.dstId);" in fn, "who stands there is still read off the steps"


def test_every_header_figure_is_sized_from_its_own_ink() -> None:
    """The figures are drawn on different squares — a sparkle that fills its 20-unit square to the
    edges, a person 27px wide in a 52px box, a record card with a margin all round — so one box size
    gave one figure 49px of ink and another 35, measured over 17 kinds on mcpolis. The eye sizes the
    ink, so each figure's box is set from what it actually draws: the larger side of its ink comes to
    HERO_INK_PX, whatever its square. Measured after: 40px on every one of 12 kinds."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    fn = js[js.index("function sizeHeroFigures() {"): js.index("\n}", js.index("function sizeHeroFigures() {"))]
    assert "const HERO_INK_PX = 40;" in js
    assert "bb = g.getBBox();" in fn and "const ink = Math.max(bb.width, bb.height);" in fn, "the ink, not the square"
    assert "const px = Math.round(HERO_INK_PX * vb.width / ink);" in fn
    assert "g.style.width = px + 'px';" in fn and "g.style.height = px + 'px';" in fn
    sync = js[js.index("function syncPageHero(s, chain, tv) {"): js.index("\n}", js.index("function syncPageHero(s, chain, tv) {"))]
    assert "sizeHeroFigures();" in sync, "after every navigation, on whichever head the page drew"
    assert ".page-hero-glyph { flex: none; width: 60px;" in css, "room for the widest box the ink calls for"
    assert ".page-hero-body { flex: 1 1 0; min-width: 0; }" in css, "a long sentence shrinks beside the figure, never drops under it"


def test_only_a_number_that_opens_a_step_lights_up_under_the_pointer() -> None:
    """The map's step numbers are doors: each opens its step, so each lights up under the pointer. The
    Happy Path writes the same class on a step's rank, which opens nothing — and it went grey under the
    pointer for no reason, because the hover rule matched the class alone. A map number is the one that
    carries `data-fstep`, so the rule keys on that."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "#diagram .flow-step-num[data-fstep]:hover {" in css
    assert "#diagram .flow-step-num:hover" not in css, "a bare-class hover lights the Happy Path's rank too"
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "number.dataset.fstep = String(i);" in js, "the map's numbers carry the attribute the rule keys on"


def test_clicking_an_arrow_points_the_line_at_its_number_not_its_middle() -> None:
    """A number is a door to its step, and so is the arrow that carries it. Clicking the number drew the
    line to the number; clicking the line beside it drew the line to the arrow's middle — the same card,
    pointed at two different places depending on which pixels the click hit. And the middle of an arrow
    carrying three steps names all three and therefore none.

    ONE helper lights an arrow and says where its line lands, and both doors go through it: the step's
    own selection hands it the number, the arrow's selection hands it the number (one step) or the row of
    numbers (a bundle, whose card describes all of them). The anchor is looked up at glow time, not at
    bind time, because the numbers are built after the arrows are bound."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    glow_at = js[js.index("function glowEdgeAt(p, label, reveal, anchor) {"): js.index("\n}", js.index("function glowEdgeAt(p, label, reveal, anchor) {"))]
    assert "const off = glowEdge(p, label, reveal);" in glow_at
    assert "anchor.classList.add('flow-step-picked'); setStepAnchor(anchor);" in glow_at
    assert "if (stepAnchorEl === anchor) setStepAnchor(null);" in glow_at, "the line goes when the selection goes"
    desc = js[js.index("function edgeDesc(scene, p, label, e, selKey, showFn, anchor) {"): js.index("\n}", js.index("function edgeDesc(scene, p, label, e, selKey, showFn, anchor) {"))]
    assert "glowEdgeAt(p, label, reveal, anchor ? anchor() : null)" in desc, "looked up at glow time"
    assert js.count("function glowEdgeAt(") == 1 and js.count("glowEdgeAt(") == 3, \
        "one helper, two doors: the step's own selection and the arrow's — nothing else lights a step"
    flow_map = js[js.index("function bindFlowMap(uc)"):js.index("function syncEnvPicker")]
    assert "bindEdges(scene, (m, p, label) => {" in flow_map
    assert "anchor: () => (on.length === 1 ? stepNumEl(label, on[0].i)" in flow_map, "a one-step arrow points at its number"
    assert ": label && label.querySelector('foreignObject p'))" in flow_map, "a bundle points at the row of them"
    bind = js[js.index("function bindEdges(scene, resolve) {"): js.index("\n}", js.index("function bindEdges(scene, resolve) {"))]
    assert "resolve(m, p, label)" in bind and "anchor: r.anchor" in bind
    # …and the dot stands BESIDE the digit. A digit is 3x8px at fit zoom, smaller than the dot, so a dot
    # on its border hid the one thing the line was there to point at.
    draw = js[js.index("function syncCallout() {"): js.index("\n}", js.index("function syncCallout() {"))]
    assert "grow(rectOf(el), isStepAnchor(el) ? NUM_DOT_CLEAR : 0)" in draw
    assert "const NUM_DOT_CLEAR = 7;" in js


def test_the_sequence_views_get_a_line_too() -> None:
    """Every use-case flow selects through `hpHighlight`, which marked nothing — so `soleSelectedEl`
    found nothing and the whole feature was silently absent on that view.

    One selection there lights SEVERAL parts: a step is its label and its arrow; an actor is its
    figure, its lifeline and every step it drives. The mark goes on ONE of them, the first, which each
    caller orders as the part that stands for the whole. Marking all of them would read as several
    selections and take the line away again.

    The Happy Path used to be the second such view. It is an HTML board now (renderHappyPath), so the
    flow is the only one left."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fn = js[js.index("function hpHighlight(scene, els, revealAction = true) {"):
            js.index("\n}", js.index("function hpHighlight(scene, els, revealAction = true) {"))]
    assert "const lead = els[0];" in fn
    assert "lead.classList.add('is-selected')" in fn and "lead.classList.remove('is-selected')" in fn


def test_everything_that_floats_over_the_drawing_states_its_layer() -> None:
    """A floater with no z-index at all lost to the callout layer at 3, which drew its line straight
    across it. Everything that floats over the drawing needs a stated place in the stack, or the last
    one added decides."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    layers = {}
    for sel in ("#callout", "#panel", "#envpicker", "#flowpicker"):
        # line-anchored, so a rule qualified by an ancestor selector cannot answer for the element.
        at = css.index("\n" + sel + " {") + 1
        block = css[at: css.index("}", at)]
        assert "z-index" in block, sel
        layers[sel] = int(block.split("z-index:")[1].split(";")[0].strip())
    assert layers["#callout"] < layers["#panel"], "the line ends at the card's edge, never across its face"
    assert layers["#callout"] < layers["#envpicker"], "…and never across a floater's face either"


def test_letting_go_of_a_selection_says_so_in_the_address() -> None:
    """Selecting restates the address in place; deselecting has to as well, or the two disagree — the
    box looks let go, the link still names it, and a reload or a copied link brings it back selected.

    `selClear` deliberately touches neither the panel nor the address, because `selReplace` calls it on
    its way to a NEW selection and the address would then be written twice. `resetScene` is the path
    that ends with nothing selected — an empty-canvas click, Escape, a back/forward with no selection
    to replay — so it is the one that owes the address an answer.

    Verified in the app on argus UC5: selecting a box put `&sel=node:I4` in the address, and a click on
    the empty canvas took it away with nothing left selected."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    reset = js[js.index("function resetScene(scene) {"): js.index("\n}", js.index("function resetScene(scene) {"))]
    assert "if (scene === mainScene && !renderingTransient) refreshUrl();" in reset
    # The same guard `selApply` uses: never during a drill animation's throwaway scene, which IS
    # `mainScene` while it is on screen.
    apply_ = js[js.index("function selApply(scene"): js.index("\nfunction selAdd")]
    assert "if (scene === mainScene && !renderingTransient) refreshUrl();" in apply_
    # …and selClear stays silent, or a plain click on a new box would write the address twice.
    clear = js[js.index("function selClear(scene) {"): js.index("\n}", js.index("function selClear(scene) {"))]
    assert "refreshUrl" not in clear


def test_the_card_comes_to_what_you_picked_and_stays_put_while_it_can() -> None:
    """The card used to open in the top-right corner whatever you clicked, and only stepped aside when it
    happened to land ON the thing. On a wide map that made the line run the width of the screen, and the
    reader's eye made that trip on every click.

    Four rules, in order: as close as it can get and never closer than one short line; never over the
    thing itself, nor — for a step — over its arrow or either box it joins; up and to the right of the
    point the line lands on unless a rule above says otherwise; and where it already stands wins while
    it still passes those and its line is not too long. The fourth is what stops the card hopping around
    the screen while a reader clicks along a walk.

    NOT SAVED, EVER. The card's place belongs to what you selected, not to the reader, so a place written
    down would be one the very next click overrules. A drag writes only to `lastCardPlace`, which rule
    four then honours for as long as it holds."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fn = js[js.index("function placeCardNear(el) {"): js.index("\n}", js.index("function placeCardNear(el) {"))]
    assert "if (cardBoxOk(box, w, keep0, a, e) && cardLineLen(box, a, e) <= CARD_MAX_LINE)" in fn, \
        "rule four, and it is tried FIRST — against the strictest set"
    # The floor is on the line that will actually be DRAWN — to a box's border, an arrow's middle.
    ln = js[js.index("function cardLineLen(box, a, e) {"):
            js.index("\n}", js.index("function cardLineLen(box, a, e) {"))]
    assert "const to = e ? borderPoint(e, bc) : a;" in ln
    assert "for (let d = CARD_MIN_LINE; d <= far; d += CARD_RING)" in fn, "rings, closest first"
    assert "for (const [ux, uy] of CARD_DIRS)" in fn
    assert "const CARD_DIRS = [[1, -1], [1, 0], [0, -1], [1, 1], [-1, -1], [0, 1], [-1, 0], [-1, 1]];" in js, \
        "up-and-right is the first direction tried, so it is the default"
    assert "storePanelBox" not in fn and "savePanelBox" not in fn, "a placement is not a gesture"
    # A step keeps its arrow AND both boxes clear; anything else keeps only itself.
    keep = js[js.index("function cardKeepSets(el) {"): js.index("\n}", js.index("function cardKeepSets(el) {"))]
    # A step's line points at its NUMBER, a few pixels of text — so the number carries its arrow, or
    # keeping clear of the number alone lets the card sit over the box the step comes from.
    assert "const arrow = (el && el.__cyArrow) || el;" in keep and "num.__cyArrow = p;" in js
    # THREE SETS, tried in order: nothing fits every rule on a crowded map, and the answer to that used
    # to be a bare corner with every rule dropped at once — which is how a card came to cover the very
    # box its step comes from. The BOXES are what survives to the last set.
    assert "[...g([...own, rectOf(arrow), ...ends]), ...fixed]" in keep
    assert "[...g([...own, ...ends]), ...fixed]" in keep
    assert "[...g(ends), ...fixed]" in keep
    # `fixed` is the zoom control, in every one of the three: the sets give up shapes of the DRAWING as
    # they widen, and a control over the drawing is not one of those.
    assert "for (let s = 0; s < sets.length; s++) {" in fn
    # The three steps happen in one order, from one function, so no caller can do them out of turn.
    card = js[js.index("function placeCard() {"): js.index("\n}", js.index("function placeCard() {"))]
    assert card.index("placeCardNear(") < card.index("syncCallout();") < card.index("scheduleCallout(true)")


def test_the_controls_left_the_bottom_edge() -> None:
    """THE CONTROLS LEFT THE BOTTOM EDGE. The environment filter and the flow player used to line the
    bottom, each anchored to a corner of its own and each moving on every selection: unrelated things
    moving on every click. They share one flex column at the top-left now, so no coordinate depends on
    another's height, and a click moves ONE thing.

    The top-left is also the cheaper corner. Measured over four views, a box this size covers 17 of the
    drawn shapes at the bottom-right, and 10 at the top-left. The top-right is emptier still, at 7, but
    the card lives there."""
    html = (VIEWER_DIR / "viewer.html").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    # ONE column, and the controls are in it rather than anchored to corners of their own.
    wrap = html[html.index('<div id="overlays">'): html.index("</div>", html.index('id="flowpicker"'))]
    for cid in ('id="envpicker"', 'id="flowpicker"'):
        assert cid in wrap, cid
    col = css[css.index("#overlays {"): css.index("}", css.index("#overlays {"))]
    assert "left: 12px; top: 12px;" in col and "flex-direction: column" in col
    assert "pointer-events: none;" in col, "its empty space must not swallow clicks on the drawing"
    assert "#overlays > * { position: relative; pointer-events: auto; }" in css
    for sel in ("\n#envpicker {", "\n#flowpicker {"):
        block = css[css.index(sel) + 1: css.index("}", css.index(sel))]
        assert "bottom:" not in block and "position: absolute" not in block, sel


def test_closing_the_panel_is_not_deselecting() -> None:
    """The × used to clear the whole selection, so putting the details away to look at the drawing
    underneath also lost the reader's place: the glow went, the dimming went, and the box they were
    reading about became one of forty again.

    It puts the PANEL away and leaves the selection standing. Clicking that same element brings it back —
    a plain click replaces the selection with itself, and `selReplace` clears and re-adds, so the panel is
    rebuilt exactly as the first click built it.

    TWO GESTURES, TWO MEANINGS. The × hides what the selection SAYS; Escape ends the selection itself. The
    button's own tooltip said "Close (Esc)" while the two did the same thing, and it no longer claims that.

    Verified in both shapes: select → panel up and one element marked; close → panel away and the element
    still marked; click it again → panel back; Escape → panel away and nothing marked."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    close = js[js.index("if (!ev.target || !ev.target.closest || !ev.target.closest('#panelclose')) return;"):
               js.index("});", js.index("if (!ev.target || !ev.target.closest || !ev.target.closest('#panelclose')) return;"))]
    assert "resetScene" not in close, "closing the panel must not clear the selection"
    assert "PANEL_HOST.innerHTML = '';" in close and "paneSync();" in close
    # Escape is still the gesture that ends a selection.
    assert "if (e.key === 'Escape' && mainScene) resetScene(mainScene);" in js
    # …and re-clicking the same element rebuilds the panel, because a plain click replaces the selection
    # with itself rather than noticing it is already there.
    rep = js[js.index("function selReplace(scene, desc, revealAction = false) {"):
             js.index("\n", js.index("function selReplace(scene, desc, revealAction = false) {"))]
    assert "selClear(scene); selAdd(scene, desc, revealAction);" in rep
    bar = js[js.index("function stampPanelBar() {"): js.index("\n}", js.index("function stampPanelBar() {"))]
    assert "Close (Esc)" not in bar, "the two gestures differ now, so the tooltip stops equating them"
    assert "the selection stays" in bar


def test_a_composite_deployment_arrow_opens_what_it_stands_for() -> None:
    """Every other bundled arrow opens its own page on ⌥-click. The Deployment arrow was the exception,
    and it cost real facts: measured over three maps, 64 Deployment arrows stand for 246 links, 245 of
    which carry a reason and 246 a code link.

    It matters more here than anywhere else. A subsystem pair's page DRAWS the links it bundles, so
    dropping its card lost nothing. The Deployment view draws one arrow per pair and never draws its
    members, so that page is the only place those 246 facts appear — and the only door to it was a button
    inside the card that a bundled arrow no longer shows.

    COMPOSITE means two or more. An arrow standing for a single link keeps what it had, which for a store
    arrow is a jump to that store's section on the Data tab — a better destination than a page with one
    row. Of the 64, thirty stand for exactly one link.

    The page carries the store onward for the ones that used to jump there, so nothing is lost: what the
    arrow stands for first, where that store lives second.

    Verified in the app: ⌥-clicking the `25 calls` arrow lands on `Deployment › dashboard → api` with 25
    rows and 25 code links; the single-channel `mio-automations` arrow still opens Storage."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fn = js[js.index("function markDeploymentEdge(scene, p, label, a, b) {"):
            js.index("\n}", js.index("function markDeploymentEdge(scene, p, label, a, b) {"))]
    assert "const page = { kind: 'depedge', a, b };" in fn
    assert "const composite = (n) => n >= 2;" in fn, "one definition of composite, used by both kinds"
    assert "composite(chans.length + xproc.length) ? page : channelDrillFor(chans)" in fn
    assert "composite(calls.length) ? page : dataDrillFor(b)" in fn
    # …and the ⌥-hover preview names what the page will hold, in the arrow's own words.
    tip = js[js.index("function actionTipDepEdge(a, b) {"): js.index("\n}", js.index("function actionTipDepEdge(a, b) {"))]
    assert "deploymentEdgeRows(a, b)" in tip, "the same wording the page and the card use"
    # The destination the page replaced rides along, under the list.
    page = js[js.index("function renderDeploymentEdgePage(s) {"):
              js.index("\n}", js.index("function renderDeploymentEdgePage(s) {"))]
    assert "depEdgeStoreLinkHtml(s.b)" in page and "bindNodeDetailHandlers(diagram);" in page
    link = js[js.index("function depEdgeStoreLinkHtml(b) {"): js.index("\n}", js.index("function depEdgeStoreLinkHtml(b) {"))]
    assert "dataDrillFor(b)" in link and "dv-seelink" in link


def test_the_bars_closing_rule_runs_under_its_close_button() -> None:
    """The × rides the bar absolutely and is taller than the grip the bar was sized for, so it hung out of
    the bottom and the bar's border-bottom crossed its face.

    The bar is now at least as tall as the button, and the button sits on the bar's own centre line.
    Measured in the app: a 24px bar holding a 21px button, top 782 to bottom 803 inside 781 to 805, and the
    rule below both."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    bar = css[css.index("#panelbar { position: sticky"): css.index("}", css.index("#panelbar { position: sticky"))]
    assert "min-height: 24px" in bar and "border-bottom" in bar
    btn = css[css.index("#panelclose { position: absolute"): css.index("}", css.index("#panelclose { position: absolute"))]
    assert "top: 50%; transform: translateY(-50%)" in btn, "on the bar's centre line, whatever its height"


def test_a_process_keeps_all_its_depth_on_a_details_page() -> None:
    """A process is the one page subject with more to say than a hero can hold: where it runs, what it is
    exposed as, where its config comes from, which environments it varies by, and every thread it hosts.
    That depth used to sit in the floating card, which is where nothing belongs any more.

    So the hero carries the process's narrative — the `Runs on` sentence its card already led with — plus
    one door, and everything else moved to the element's own details page. Every other subject's depth was
    already on that page; a process simply had none.

    The threads it hosts are read off the map's entry points rather than off the process's own fields, so
    the generic details body cannot build them. They ride the details page under the fields, in the one
    builder both the old card and the page share."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "function showDeploymentUnit(" not in js, "the process card is gone"
    threads = js[js.index("function unitThreadsHtml(unit) {"):
                 js.index("\n}", js.index("function unitThreadsHtml(unit) {"))]
    assert "Threads / loops" in threads and "threadRowsHtml(eps)" in threads
    assert "if (!eps.length) return '';" in threads, "no threads is not an empty heading"
    det = js[js.index("function renderElementDetails(id) {"):
             js.index("\n}", js.index("function renderElementDetails(id) {"))]
    assert "${nodeDetailBodyHtml(id, true)}${unitThreadsHtml(n.unit)}" in det, "under the fields, on the same page"
    # The door, and only for a process — every other subject's page is reached from its card elsewhere.
    sub = js[js.index("function heroSubjectHtml(id, chain) {"):
             js.index("\n}", js.index("function heroSubjectHtml(id, chain) {"))]
    assert "n.kind === 'process' ? heroDetailsLinkHtml(id) : ''" in sub
    link = js[js.index("function heroDetailsLinkHtml(id) {"):
              js.index("\n}", js.index("function heroDetailsLinkHtml(id) {"))]
    assert "data-goelement" in link
    hero = js[js.index("function syncPageHero(s, chain, tv) {"):
              js.index("\n}", js.index("function syncPageHero(s, chain, tv) {"))]
    assert "go({ kind: 'element', id: b.getAttribute('data-goelement') })" in hero
    assert ".hero-details {" in css and "text-decoration: underline" in css
    # Redrawn by the same call that redraws the tabs and the trail, so it cannot outlive its page.
    chrome = js[js.index("function renderChrome(s) {"):
                js.index("\nfunction ", js.index("function renderChrome(s) {") + 10)]
    assert "syncPageHero(s, chain, q ? tv : '');" in chrome
    # The `In feature` line is dropped when the trail already names that feature — which it does on every
    # use case reached through a feature card. Under the crumb it would print the same words twice. It
    # lives in the WALK's head now, the one builder a use case's page goes through.
    walk = js[js.index("function walkHeadHtml(s, chain) {"):
              js.index("\n}", js.index("function walkHeadHtml(s, chain) {"))]
    assert "inTrail || sub ? '' : useCaseFeatureFootHtml(id)" in walk
    assert "useCaseFeatureFootHtml" not in sub, "a use case never comes through the fixed-block hero"

def test_a_code_link_looks_the_same_on_every_screen_that_draws_one() -> None:
    """`srcCell` builds one code link and eight screens call it: the Glossary, the Storage table, an
    entity's page, the System reference tables, a flow step's call site, the deployment rows. Its style
    rule was scoped to `.glossary`, so SEVEN of the eight rendered the raw browser button — grey fill, a
    2px bevelled border, 13.3px black text — while the eighth looked like a link.

    One unscoped rule now. Measured after: the Storage chip and the Glossary chip are both 12px
    monospace, #2563eb, no background and no border."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "\n.src { font-family: ui-monospace" in css, "the rule is not scoped to one table"
    assert ".glossary .src {" not in css

def test_the_source_column_has_one_header_over_both_panes() -> None:
    """It was two headers, one per pane, each visible only in one state. So the switch between them was
    two different buttons, with two different names and two different icons, in two different places:
    `☰ Files` in the code viewer's header, `</> Source` in the browser's. A control that changes its name,
    its icon AND its location is not one control, and nothing on screen said the two were the same switch.

    One header now, above both panes, and it never moves. It holds, left to right: the switch with BOTH
    halves visible and the current one lit; the file; the pin; open-externally; and the one × for the
    column. The switch doubles as the column's title, so opening from the rail lands on the rail's own two
    words rather than on an unnamed pane.

    THE FILE IS THE FILENAME, first, with its folder muted beneath it. The old single line held six things
    in 542px and gave the path 298 of the 477 it needed — so the part that truncated was the END, which is
    the filename, and what showed was the folders nobody asked for. Measured after: the name fits in full.

    The element pill is gone from both sides. It named a thing the floating card and the breadcrumb name
    already, and it took 66 of the header's 542 pixels — width the filename needed and did not have."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    # One header, one column, the panes under it.
    for el in ("srccol", "srchead", "srcpanes", "srcswitch", "srcfile", "srcdir"):
        assert f'id="{el}"' in html, el
    assert html.index('id="srchead"') < html.index('id="srcpanes"'), "the header is above both panes"
    for gone in ("cvhead", "treehead", "cvfilesbtn", "treecodebtn"):
        assert f'id="{gone}"' not in html, gone
    # The switch: both halves, the live one lit. ONE PANE AT A TIME — showing both at once was a third
    # state with its own control, its own saved flag and its own guard in nine places, and it made the
    # switch meaningless, since there was then nothing to switch between.
    assert 'id="srcsw-code"' in html and 'id="srcsw-files"' in html
    state = js[js.index("function applyTreeState() {"): js.index("\n}", js.index("function applyTreeState() {"))]
    assert "srcSwCode.classList.toggle('on', !treeBrowsing)" in state
    assert "srcSwFiles.classList.toggle('on', treeBrowsing)" in state
    assert "treePinned" not in js, "showing both panes at once was a third state with its own control"
    assert "#srcswitch button.on" in css, "the live half is lit, not merely un-dimmed"
    # TWO ROWS, because one row could not hold both jobs. The top row is about the COLUMN — which pane you
    # are looking at, and what to do with the column. The second is about the FILE. Sharing one row left
    # the filename 266px of a 542px header, beside a switch and three icon buttons.
    assert 'id="srchead-top"' in html
    assert html.index('id="srchead-top"') < html.index('id="srcfile"'), "controls first, then the file"
    # Each control rides the row of the thing it acts on: the switch and the fold-away chevron act on the
    # COLUMN, so they are on the top row; open-externally acts on the FILE, so it is on the file's row.
    for ctl in ('id="srcswitch"', 'id="cvclose"'):
        assert html.index(ctl) < html.index('id="srcfile"'), ctl
    assert html.index('id="cvopen"') > html.index('id="srcfile"'), "open-externally rides the file's row"
    # …and both icons sit at the far end of their own row. That push came from the pin button's
    # `margin-left: auto` and went with it, so the two bunched up against the switch.
    for btn in ("#cvclose {", "#cvopen {"):
        blk = css[css.index(btn): css.index("}", css.index(btn))]
        assert "margin-left: auto" in blk, btn
    # The file row belongs to the CODE pane, so it is not drawn while the browser is the pane on screen:
    # it would name a file the reader cannot see.
    assert "body.tree-browsing #srcfile { display: none; }" in css
    # And within that row the FOLDER gives way first. Left equal, a narrow column truncated both — measured
    # at 518px with the worst path on these maps, the name showed 200 of the 246 it needed while the folder
    # still had 293 of 354. The name is the thing the reader came for.
    d = css[css.index("#srcdir {"): css.index("}", css.index("#srcdir {"))]
    assert "flex: 0 100 auto" in d, "the folder shrinks 100x faster than the filename"
    # The FILENAME, not the path; the folder beside it, muted.
    head = js[js.index("function renderCvHeader() {"): js.index("\n}", js.index("function renderCvHeader() {"))]
    assert "(cvPath || '').split('/').pop()" in head, "the name, which is what a reader recognises"
    assert "srcdir.textContent = cvPath ? (cvPath.split('/').slice(0, -1).join('/')" in head
    assert "elementPill(cvElement)" not in head, "the pill took the width the filename needed"
    assert "renderTreeHeadPill() {}" in js, "…and it is gone from the browser's side too"

def test_the_source_is_one_control_on_the_edge_and_none_on_the_cards() -> None:
    """An element card shows what an element IS. It carries no way to open the code, and neither does the
    panel its card floats in: code is the reader's LAST priority, and a per-element control put it on
    every card in the app to say once per box what one control says once per screen.

    A `</>` on the panel's bar was tried and removed. It was the lightest thing on the screen — 11px, grey
    #9ca3af, 28px wide, against a 14px name and a 10px bold type pill — a symbol rather than a word, and
    it existed only in the popup, never in a grid or a list.

    THE RAIL replaces it: a 30px strip down the right edge of the window, standing exactly where the
    source column appears when it opens, so the control shows its own result before the click. It is there
    when the column is shut and gone when it is up, so the edge of the window always says one of two
    things — "the source is here", or the source.

    The title bar's toggle stays beside it. It is the one control that shows STATE and can also put the
    column away, which the rail cannot: the rail is gone while the column is up."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    assert 'id="srcrail"' in html and "#srcrail {" in css
    assert "srcRail.addEventListener('click', () => setCodeOpen(true));" in js
    assert "rail.hidden = !SERVED || codePaneOpen();" in js, \
        "there when the column is shut, gone when it is up"
    rail = css[css.index("#srcrail {"): css.index("}", css.index("#srcrail {"))]
    assert "flex: 0 0 30px" in rail, "the strip stands where the column will"
    assert "writing-mode: vertical-rl" in css, "a word on an edge, not a symbol"
    # …and nothing on the card, nor on the panel that holds it.
    assert "panelsrc" not in js and "panelsrc" not in css, "the bar's button is gone"
    assert "data-gosrc" not in js, "and the card grew none of its own"
    card = js[js.index("function elementCardHtml(id, opts) {"):
              js.index("\n}", js.index("function elementCardHtml(id, opts) {"))]
    assert "srclink" not in card and "localRef" not in card

def test_a_page_about_one_element_says_what_it_is_beside_its_name() -> None:
    """A card puts an element's name and its pills on ONE line. Its own page split them across two rows
    with a rule between, so the page drew the element in a shape no card uses. Measured over the three
    maps: of the 1189 pages whose last breadcrumb item is one element, 796 drew a pill block, and on 629
    of them (every entity, component and process) that block held ONE word and nothing else — a 48px
    strip saying `entity` between the page's title and its first sentence.

    They ride the HERO's name row. They sat on the breadcrumb for a while, beside its last item, and
    the trail is the wrong home for them: it says WHERE YOU ARE, one step per level, and a word
    describing the thing at the end of it is not a step. The hero names its own subject now, so the
    name and its pills sit on one line there, exactly as a card reads.

    THE SAME PILLS THE CARD SHOWS, from `cardFacts` — its type, and the few extras its type earns. Not
    the page's full detail: a dependency's card says `dependency` and `service`, while its page also
    records a purpose bucket and the roles derived from its incoming edges. Five words hung off a trail
    is a wall rather than a trail, so those two stay on the page, below.

    EVERY page about one element, diagram or prose. A drilled diagram was excluded for one round, on the
    grounds that its card already floats over the drawing — but that card can be closed and moved, and
    once it is, the page said nothing about what it was showing. `Features › Organizations and team ›
    Create an organization` never said the last item was a use case, while every other page of the trail
    did. One rule with no exception beats a rule the reader has to learn the edge of.

    A page about a PAIR (an arrow, a bridge) or a FOLD (Libraries, a dependency bucket) is not about one
    element and gets nothing: there is no card to read, and a fold's stored kind is a way of drawing
    rather than a word the map records.

    Plain text, never a control. Clicking a type pill means "show this in context", and the context of
    the page you are already on is the page you are already on."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    which = js[js.index("function pageElementId(s) {"):
               js.index("\n}", js.index("function pageElementId(s) {"))]
    assert "TEXT_PAGES" not in which, "a drilled diagram is a page about one element too"
    for kind in ("element", "capability", "rule", "rules", "actor",
                 "usecase", "subsystem", "domsub", "deploymentUnit"):
        assert f"'{kind}'" in which, kind
    for pair in ("edge", "domedge", "bridge", "depedge", "libs", "bucketfold"):
        assert f"'{pair}'" not in which, f"{pair} is a pair or a fold, not one element"
    pills = js[js.index("function elementPillsHtml(id) {"):
               js.index("\n}", js.index("function elementPillsHtml(id) {"))]
    assert "cardFacts(id)" in pills, "the same pills the card shows, from the same function"
    assert "<button" not in pills, "plain text: the pill's destination is the page you are on"
    assert "crumbPillsHtml" not in js and "crumbpill" not in js and "crumbpill" not in css, \
        "the trail draws none of them"
    # Every page about one element asks that one function; a surface has no node to ask it about and
    # builds its own words (`our surface`, its shape, who it faces).
    # A page hero says the type in a word before the name and draws the pills AFTER the type one,
    # through the same facts (`elementSidePillsHtml`, which `elementPillsHtml` itself calls).
    assert js.count("elementPillsHtml(") == 1 and js.count("elementSidePillsHtml(") == 6, \
        "the two helpers, and the actor, feature, decision-area and use case pages through the side one"
    # …and the body no longer draws what the trail carries.
    extra = js[js.index("function kindPillsExtra(n) {"):
               js.index("\n}", js.index("function kindPillsExtra(n) {"))]
    assert "n.kind !== 'dep'" in extra, "only a dependency has axes its card does not carry"
    assert ".filter((w) => w !== kind)" in extra, \
        "a role whose word IS the kind says nothing twice — 32 of the 153 dependencies"
    # The element page leads with the same card every page about one element leads with, whatever is
    # left for the pills — the card carries the mark, the type word, the name and the sentence.
    assert "pills: extra," in js and "nodeDetailBodyHtml(id, true)" in js, \
        "the card, and a body that no longer repeats the card's sentence"

def test_a_text_view_has_no_selection_card_and_a_diagram_only_has_one_when_it_says_something() -> None:
    """Per the spec a card list, a card grid and a details page carry no info pane: a pane beside a page
    of prose only repeated it, and it stole a third of the height from the content it described.

    A DIAGRAM no longer keeps a standing pane either. It was a fixed 300px band under every diagram,
    there whether or not anything was selected. Measured over 60 states on the three maps: with nothing
    selected it held 76px of content on four of the five views, and one selected shape held 67-184px, so
    about three quarters of it stood empty nearly all the time. The diagram was left with 447px of an
    860px window, which is 32% of the screen for the thing the page is about. It is now 752px.

    What you selected floats over the drawing instead, and `paneSync` is the ONE place that decides
    whether it is on screen: it is there when it has something to say and gone when it has not. Every
    caller just writes; nothing has to remember to show or hide.

    And a card belongs to the page on screen, so EVERY navigation starts with no card: `syncInfoPane`
    clears it before the page renders, and the page puts one back only if it has one to show — its own
    subject, or the selection history is restoring. Enforced by construction rather than by a check per
    navigation path, because a card that outlives its page describes something no longer on screen.
    A transient render is exempt: those are the intermediate frames of a drill animation, and clearing on
    each one blinks the card off and back for one navigation the reader has not finished making."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "function syncInfoPane(_s, transient) {" in js
    assert "  if (transient) return;" in js, "a drill animation's own frames must not blink the card"
    # `render` is the degrade wrapper now; `renderView` is the body every screen goes through.
    assert "syncInfoPane(s, transient);" in js[js.index("async function renderView(sArg, transient, seq) {"):][:1200]
    assert "showViewIntro" not in js, "one mechanism clears the card, not two"
    pages = js[js.index("const TEXT_PAGES = new Set(["):]
    pages = pages[: pages.index("]);")]
    # `hp` is on the list: the Happy Path is an HTML board now (renderHappyPath), not a diagram.
    for kind in ("usecases", "capability", "actor", "hp", "rules", "system", "glossary"):
        assert f"'{kind}'" in pages, kind
    assert "'usecase'," not in pages, "a diagram is not a page of prose"
    # ONE rule, called from both paths that fill the card: a selection, and a page's own default.
    sync = js[js.index("function paneSync() {"): js.index("\n}", js.index("function paneSync() {"))]
    assert "PANEL_HOST.hidden = !has;" in sync
    assert "stampPanelBar();" in sync, "the bar is stamped from the one place, so no card is stuck open"
    bar = js[js.index("function stampPanelBar() {"): js.index("\n}", js.index("function stampPanelBar() {"))]
    assert 'id="panelclose"' in bar and 'id="panelbar"' in bar, "…and it carries the × in either shape"
    assert "paneSync();" in js[js.index("function renderSelPanel(scene) {"):
                                js.index("\n}", js.index("function renderSelPanel(scene) {"))]
    assert "paneSync();" in js[js.index("function applyDefaultPanel(s) {"):
                                js.index("\n}", js.index("function applyDefaultPanel(s) {"))]
    # It floats over the drawing, and #diagwrap is what it floats in.
    pane = css[css.index("#panel {"): css.index("}", css.index("#panel {"))]
    assert "position: absolute" in pane and "top: 12px" in pane and "right: 12px" in pane, \
        "top-right: #envpicker owns the bottom-left corner"
    assert "max-height" in pane, "a few states run long and must scroll rather than fill the screen"
    assert '<div id="diagwrap">' in (VIEWER_DIR / "viewer.html").read_text()
    # The 300px band, its drag handle and its stored height are gone, not merely hidden.
    assert "vsplit" not in js and "vsplit" not in css
    assert "panelH" not in js, "there is no pane height left to remember"

def test_an_arrow_card_holds_three_calls_and_drills_for_the_rest() -> None:
    """An arrow stands for anything from one call to 33. In the old 300px pane its list ran from 73px to
    1983px, and 16 of the 32 arrows sampled were taller than the pane they were drawn in.

    Measured across the three maps: 873 drawn arrows, of which 481 (55%) stand for exactly ONE call and
    718 (82%) for three or fewer. So the card holds three, which finishes four arrows in five where the
    reader clicked, and the 155 that hold more offer a drill to the arrow's own page.

    ONE builder, because four panels drew this shape by hand and each capped it differently, which is to
    say none of them capped it.

    ONE case is never cut: an arrow with no page to drill to (a Deployment arrow has none yet) shows
    everything, because a card that hides rows and offers no way to them would be worse than a long card.
    There used to be a second — the arrow's OWN page asked for the whole list — and it went with that
    page's card, since the page draws the very arrows the list enumerated."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "const ARROW_CARD_ROWS = 3;" in js
    fn = js[js.index("function arrowCardHtml(o) {"): js.index("\n}", js.index("function arrowCardHtml(o) {"))]
    assert "const full = !o.drill;" in fn, "no page to go to means nothing is hidden"
    assert "o.full" not in js, "nothing asks for the whole list any more"
    assert "rows.slice(0, ARROW_CARD_ROWS)" in fn
    assert "class=\"xmore\" data-drill=" in fn
    for caller in ("function showContainerEdge(a, b, drawn) {",
                   "function showDomainContainerEdge(a, b, drawn) {",
                   # The bridge card takes the arrow's own target, because it cannot always work one
                   # out: on a subsystem's card neither drawn end IS the subsystem, so it found none
                   # and drew a plain heading — and with the arrow's magnifier gone, that heading was
                   # the door that was not there.
                   "function showBridgeEdge(drawn, target) {"):
        assert caller in js, caller
        body = js[js.index(caller): js.index("\n}", js.index(caller))]
        assert "arrowCardHtml({" in body, caller
    assert "drill: (target && target.kind) ? target :" in js, "the arrow's own page wins over any guess"
    assert "showBridgeEdge(drawn, tgt)" in js, "…and the binder is what hands it over"
    assert "closest('[data-drill]')" in js, "the way to the rest is delegated, not wired per render"

def test_a_deployment_arrow_has_a_page_like_every_other_arrow() -> None:
    """A Deployment arrow was the last kind with nowhere to drill. Subsystem pairs, entity pairs and
    subsystem-to-subdomain bridges each already had a page; a Deployment arrow's list of calls existed
    only in the pane. So its card was the one that could not be cut, and about 25 of the 78 deployment
    arrows in the three maps stand for more than three calls — the worst for 25.

    It gets a page now, and the page is PROSE, not a diagram: the thing it shows is a list. That is why
    `depedge` joins TEXT_PAGES, which is also what takes the floating card and the zoom controls
    off it.

    ONE function builds the rows for both the card and the page. They were written twice before, for the
    two arrow shapes a Deployment view draws (process to process, process to infrastructure), and the two
    copies had already drifted on their count line."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "function deploymentEdgeRows(a, b) {" in js
    for fn in ("function showDeploymentEdge(a, b, full) {",
               "function showDeploymentInfraEdge(a, b, full) {",
               "function renderDeploymentEdgePage(s) {"):
        assert fn in js, fn
        body = js[js.index(fn): js.index("\n}", js.index(fn))]
        assert "deploymentEdgeRows(" in body, fn
    for card in ("function showDeploymentEdge(a, b, full) {", "function showDeploymentInfraEdge(a, b, full) {"):
        body = js[js.index(card): js.index("\n}", js.index(card))]
        assert "drill: { kind: 'depedge', a, b }" in body, card
    pages = js[js.index("const TEXT_PAGES = new Set(["):]
    assert "'depedge'" in pages[: pages.index("]);")], "an arrow's list is a page of prose"
    assert "if (s.kind === 'depedge') return [{ kind: 'deployment' }, { kind: 'depedge', a: s.a, b: s.b }];" in js, \
        "the trail reads Deployment > A to B; an arrow joins two processes and belongs under neither"
    assert "kind === 'depedge') return 'deployment'" in js, "and it lives under the Deployment tab"

def test_the_card_is_dragged_by_its_bar_and_sized_by_nothing() -> None:
    """The card is dragged by its BAR, and by nothing else: dragging on its own text would fight
    selecting that text, and a reader copying a call site out of a row should be able to. A
    double-click on the bar puts it home, because a floating thing needs a way back or one bad drag on
    a small window loses it.

    IT HAS NO SIZE TO SET. A corner grip and a remembered box used to live here, and both became a
    contradiction the moment the card's height became its CONTENT's: a height set on one card is empty
    white under the next one, on every selection after it, until the reader finds the grip again. The
    width is one number in the stylesheet; the height is whatever is in it, capped so a tall card cannot
    cover the drawing it floats over."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "closest('#panelbar')" in js, "the bar is the handle"
    assert "panelBox" not in js and "appliedBox" not in js, "the remembered box is back"
    assert "coyomap.panelBox" not in js, "…and so is the key it was written under"
    pane = css[css.index("#panel {"): css.index("}", css.index("#panel {"))]
    assert "resize:" not in pane, "the corner grip is back"
    assert "overflow: auto" in pane, "a card past its ceiling scrolls inside itself"
    assert "min-width" in pane, "it must not shrink to an unreadable stub sideways"
    # NO min-height. It was 90px, which padded a short card with empty white; a card is as tall as
    # what is in it, and the ceiling is what stops a tall one covering the drawing.
    assert "min-height" not in pane
    assert "max(200px, 55%)" in pane, "the drawing keeps the larger half"
    # …and the whole thing is capped, because the 200px floor IS a floor: on a drawing shorter than
    # that (a 900x420 window leaves 203px) the card ran out through the bottom edge, which #diagwrap
    # clips. The cap tightens again when the zoom control takes the top of this corner — see
    # test_the_zoom_control_is_absent_on_a_page_with_no_diagram for the sibling rule that does it.
    assert "max-height: min(max(200px, 55%), calc(100% - 24px));" in pane
    bar = css[css.index("#panelbar { position: sticky"): css.index("}", css.index("#panelbar { position: sticky"))]
    assert "position: sticky" in bar, "the handle and the close button stay reachable in a scrolled card"

def test_the_source_column_is_optional_on_every_page_including_a_diagram() -> None:
    """Code is the reader's LAST priority — the spec's reading order is the narrative, then the
    implementation facts, then the code — so it does not get a fixed column on a screen the reader never
    asked it for.

    Text pages lost the standing column first. Measured on three maps at 1440px: it held 542px, 38% of the
    window, on EVERY view, and on the seven text views nothing on the page could fill it, so the screen the
    map lands on spent more than a third of itself on "Select a node or file to view its source".

    A DIAGRAM kept it, on the grounds that a click on a shape loaded that shape's file so the pane was
    live. That reason was the problem: SELECTING A SHAPE IS NOT A REQUEST FOR CODE. It says "tell me about
    this box", and the card answers that. So the column is optional everywhere now, and a selection only
    REMEMBERS the file — the diagram went from 893px wide to the full 1440.

    Three ways in, and one of them has to be visible on every page, so the title bar carries a toggle
    beside the legend's. The others are any file anchor the reader clicks (loadCode / openInCodeViewer),
    and a pinned file browser, which is a choice they already saved.

    Opening it shows what was SELECTED while it was shut, or it opens on whichever file it happened to
    hold last, which is never the box the reader is looking at. And the choice is remembered across views
    and across reloads: it says what this reader wants to see, not which screen they are on."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    fn = js[js.index("function syncCodePane(s) {"): js.index("\n}", js.index("function syncCodePane(s) {"))]
    assert "TEXT_PAGES" not in fn, "a diagram's column is optional too"
    assert "document.body.classList.toggle('code-hidden', !codePaneOpen());" in fn
    assert "close.hidden = false;" in fn, "the way out is offered everywhere the column can be open"
    assert "function codePaneOpen() { return codeOpen; }" in js, "one flag, one answer"
    # …and it runs for every state, before render's early returns, exactly like syncInfoPane.
    # Searched over the whole of `renderView`, not a byte window into it: the window was 1400 and a
    # one-line comment added at the top of the function pushed the call past it, which is a test that
    # fails on prose rather than on the thing it guards.
    body = js[js.index("async function renderView(sArg, transient, seq) {"):]
    assert "syncCodePane(s);" in body[: body.index("\n// ")]
    # A file anchor is a request for code, wherever it is clicked — and it opens the column through the
    # SAME door the toggle does. It used to set the flag itself, which changed the layout without
    # re-framing the drawing: measured on MCP Hero's "Create an organization" flow, the diagram kept the
    # 1442px-wide transform it had at full width and ran on underneath the code viewer in an 892px box,
    # while the same column opened by the toggle rescaled to 900px and fitted.
    assert "noteCodeAsked();" in js[js.index("async function loadCode(path, line) {"):][:900]
    assert "noteCodeAsked();" in js[js.index("function openInCodeViewer(file, line) {"):][:900]
    asked = js[js.index("function noteCodeAsked() {"): js.index("\n}", js.index("function noteCodeAsked() {"))]
    assert "setCodeOpen(true);" in asked, "one door, so one re-frame"
    assert "codeOpen = true;" not in asked, "…and no second copy of it that forgets to re-frame"
    # A SELECTION is not. It remembers the file so the toggle can open on it.
    view = js[js.index("function syncCodeView(file, line, files) {"):
              js.index("\n}", js.index("function syncCodeView(file, line, files) {"))]
    assert "if (!codePaneOpen()) { pendingCode =" in view
    opener = js[js.index("function setCodeOpen(on) {"): js.index("\n}", js.index("function setCodeOpen(on) {"))]
    assert "lsSet(LS.codeOpen" in opener, "the choice is remembered"
    assert "pendingCode" in opener and "loadCode(p.file, p.line)" in opener, \
        "opening shows what was selected while it was shut"
    assert "codeOpen = lsGet(LS.codeOpen) === '1';" in js, "…and it survives a reload"
    # Opening or closing the column is the SAME size change as dragging its bar, so the drawing is
    # re-framed the same way: the reader's zoom kept, and the point under the centre kept under it. A
    # fresh fit would throw a reader who had zoomed into one corner back to the whole map for pressing a
    # toggle. The floating card is measured in the drawing's own box, so it is re-clamped too — without
    # overwriting where the reader parked it, so it returns there when there is room again.
    resized = js[js.index("function codePaneResized() {"):
                 js.index("\n}", js.index("function codePaneResized() {"))]
    assert "resizeStagePreserve();" in resized and "placeCard();" in resized
    opener2 = js[js.index("function setCodeOpen(on) {"): js.index("\n}", js.index("function setCodeOpen(on) {"))]
    assert "slideCodePane();" in opener2, "the toggle hands the column to the slide"
    # THE SLIDE is what re-frames now, and it does it on every frame rather than once: the column's width
    # is moving for a quarter of a second, so the drawing's box is moving with it, exactly as it does
    # under a drag of the bar. Doing it only at the end would leave the drawing at its old size while a
    # third of the window changed underneath it.
    slide = js[js.index("function slideCodePane() {"): js.index("\n}\n", js.index("function slideCodePane() {"))]
    assert "requestAnimationFrame(tick);" in slide and "codePaneResized();" in slide
    assert "resyncCodePane(); codePaneResized();" in slide, "…and no motion still lands in the end state"
    # The rule that hides the column must not fire mid-slide: every render passes through syncCodePane,
    # and one landing between the slide's two frames would snap the column to its end width.
    sync = js[js.index("function syncCodePane(s) {"): js.index("\n}", js.index("function syncCodePane(s) {"))]
    assert "if (srcSliding) return;" in sync
    assert sync.index("if (srcSliding) return;") < sync.index("classList.toggle('code-hidden'")
    # TWO CLASSES, and the split is the whole trick. `code-sliding` PUTS the three widths at the start of
    # the move; `code-slide-go`, one frame later, is the only thing that carries a transition. Arming the
    # move in the same breath as placing it sent the rail travelling towards its own starting value
    # instead of away from it — it comes back from `display: none` at 30px, so "put it at 0" became a
    # quarter-second journey to 0 that the slide then reversed, and the rail never moved at all.
    css = (VIEWER_DIR / "viewer.css").read_text()
    placed = css[css.index("body.code-sliding #srccol {"): css.index("body.code-slide-go #srccol,")]
    for sel in ("#srccol", "#resizer", "#srcrail"):
        rule = placed[placed.index("body.code-sliding " + sel + " {"):]
        rule = rule[: rule.index("}")]
        assert "flex: 0 0 var(--" in rule, sel
        assert "min-width: 0;" in rule, sel + " must be free to reach zero"
        assert "transition" not in rule, sel + ": placing a width must never animate it"
    assert "body.code-slide-go #srccol,\nbody.code-slide-go #resizer,\nbody.code-slide-go #srcrail" in css
    assert "requestAnimationFrame(() => {" in slide and "classList.add('code-slide-go');" in slide, \
        "…and the arming class lands a frame after the placing one"
    # All three carry the SAME duration and curve: they are one move, and three different speeds on one
    # edge would read as three things happening at once.
    assert "transition: flex-basis .24s cubic-bezier(.2, .8, .2, 1);" in css
    # The page column is free for those frames, so it takes the space back one frame at a time instead
    # of in one jump when the slide ends.
    assert "body.code-sliding #leftcol { flex: 1 1 auto; width: auto !important; }" in css
    # …and a reader who asked the system for less motion gets the end state with no travel.
    reduced = css[css.index("@media (prefers-reduced-motion: reduce) {", css.index("body.code-slide-go")):]
    reduced = reduced[: reduced.index("}\n}")]
    for sel in ("#srccol", "#resizer", "#srcrail"):
        assert "body.code-slide-go " + sel in reduced, sel
    assert "codePaneResized();" in js
    assert "window.addEventListener('resize', placeCard);" in js, "so does the window itself"
    # `placeCard` is the three steps that depend on where the card landed: it comes to the element it
    # describes, then redraws the line to it. One order, so no caller can do them out of turn.
    card = js[js.index("function placeCard() {"): js.index("\n}", js.index("function placeCard() {"))]
    assert card.index("placeCardNear(") < card.index("syncCallout();") < card.index("scheduleCallout(true)")
    # FIT TO SCREEN has to measure the box it is fitting into. `reset()` only sets zoom back to 1 and pan
    # back to the values svg-pan-zoom recorded when it was CONSTRUCTED, so on any view whose box has since
    # changed size — a column opened, a window resized — it restored a stale fit rather than computing a
    # new one. Measured on the Subsystems map: the content stood at 107% of the box height and pressing
    # the button left it there; it now comes back at 101%.
    assert "zoomlevel.addEventListener('click', () => { if (mainPz) refitStage(); });" in js
    assert "mainPz.reset()" not in js, "reset restores the fit from construction time, not the current one"
    # NOTHING WATCHES THE CARD'S OWN SIZE, and there is no size to watch: it has no grip and no
    # remembered box, so its height is its content's and its width is one number in the stylesheet.
    # The ban is on watching THE CARD, not on the API. Spelled as `"ResizeObserver(() =>" not in js`
    # it only ever caught the inline-arrow form — the two observers already in the file (a scroller
    # each) pass a named callback and always slipped through, and the drawing's own box now needs one
    # too (stageRoomWatch: a map built before the drawing had room must re-fit the moment it gets
    # some, and most of the routes room arrives by call no re-fit path at all). So the check is on the
    # TARGET and on what the callback saves, which is what the measurement above was really about.
    rs_names = set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=[^;]*?new ResizeObserver\(", js))
    rs_targets = re.findall(r"new ResizeObserver\((?:[^()]|\([^()]*\))*\)\.observe\(\s*([^,)]+)", js)
    rs_targets += [t for n in rs_names for t in re.findall(r"\b" + n + r"\.observe\(\s*([^,)]+)", js)]
    assert rs_targets, "no observer target could be read — this check no longer guards anything"
    for target in rs_targets:
        assert "panel" not in target.lower(), f"the card's own size is watched again: {target}"
    # …and NOTHING about the card is saved any more. Its place comes from what you selected and its
    # height from what is in it, so a saved box could only be one the very next click overrules.
    assert "savePanelBox" not in js and "storePanelBox" not in js
    # The two visible ways out, and the one visible way in.
    # ONE × for the whole column, in the ONE header above both panes, so it is in the same place whichever
    # pane is showing. It used to live in the code viewer's header only, and browsing hides the code viewer
    # outright — so opening the column with nothing selected landed on the file browser with no way out of
    # it but the title bar's toggle.
    # Closing also UNPINS: a pinned browser holds the column open by itself, so leaving the pin set would
    # make the × look broken.
    assert "body.tree-browsing #codeview { display: none; }" in css, \
        "…which is why a × inside the code viewer was not enough"
    assert 'id="treeclose"' not in html, "one ×, not one per pane"
    cc = js[js.index("if (cvCloseBtn) cvCloseBtn.addEventListener('click', () => {"):]
    cc = cc[: cc.index("\n});") + 4]
    assert "setCodeOpen(false)" in cc
    assert 'id="cvclose"' in html
    # ONE way in: the rail. The title bar carried a `</>` toggle as well, from before the rail existed —
    # two controls for one thing, one of them a glyph among five other glyphs.
    assert 'id="codebtn"' not in html and "codebtn" not in css and "codeBtn" not in js
    # A static map has no column to open, and SERVED is decided ASYNCHRONOUSLY — initServerMode awaits a
    # fetch — so it cannot be read at boot. It was, and the control stayed hidden on every served map. It
    # is read where every render passes, and initServerMode resyncs once the answer is settled.
    assert "rail.hidden = !SERVED || codePaneOpen();" in js, "a static map has no column to open"
    served = js[js.index("  SERVED = true;"):]
    assert "resyncCodePane();" in served[:700], "…and everything gated on it is decided again here"
    # Hiding is the whole column in one go — it is one element now, header and both panes — plus the
    # width going back to the page.
    for pane in ("#srccol", "#resizer"):
        assert f"body.code-hidden {pane}" in css, pane
    assert "body.code-hidden #leftcol { flex: 1 1 auto; width: auto !important; }" in css

def test_a_page_and_its_title_share_one_left_edge() -> None:
    """The reading-width cap on a card page only bites once the source column is closed and the page has
    the whole window. Centring the remainder put the content 153px right of the breadcrumb — and the
    breadcrumb IS the page's title, since no page draws a heading of its own. A title floating 153px
    from the thing it titles reads as belonging to nothing, so the capped wrappers are pinned left."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    for block in ("max-width: 1100px; margin: 0;", "max-width: 1100px; margin: 0 0 14px;"):
        assert block in css, block
    assert "margin: 0 auto" not in css, "a capped wrapper centred away from the breadcrumb is back"

def test_the_card_dodges_the_hand_that_opened_it_and_never_the_one_that_moved_after() -> None:
    """The card keeps clear of the pointer so it never lands under the hand that just clicked. That is
    right for the FIRST placement and wrong for every one after it.

    The card is re-placed by things with nothing to do with the reader's hand: the source column
    sliding open (`codePaneResized` on EVERY frame for 240ms), a camera ease landing 420ms later, a
    window resize, the deferred dodge two frames on. Each of those read the LIVE pointer, so a card
    that had settled jumped the moment the reader moved the mouse over where it sat — which is exactly
    where a reader moves the mouse, onto the thing they just opened.

    Measured with the pointer parked in two places and the same placement forced twice, same map, same
    selection, same box: x=702 with the pointer away, x=222 with the pointer on the card. Frozen, both
    are 702."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    place = js[js.index("function placeCardNear(el) {"):
               js.index("\n}", js.index("function placeCardNear(el) {"))]
    assert "const hand = handAt" in place, "the hand is the frozen one"
    assert "pointerAt" not in place, "the live pointer is back in the placement"
    # …frozen at the ONE place a card is put up for a new selection, so the hand it dodges is the hand
    # that opened it.
    sync = js[js.index("function paneSync("): js.index("\n}", js.index("function paneSync("))]
    assert "handAt = pointerAt ? { ...pointerAt } : null;" in sync
    assert sync.index("handAt = pointerAt") < sync.index("placeCard();"), "frozen before it is used"


def test_a_flow_arrow_opens_the_step_it_names_not_the_pair_it_crosses() -> None:
    """The popup over a flow arrow shows ONE step, and its title opens that step's own page. The page
    was the PAIR's first, and that was the wrong answer to the question asked at a flow arrow: a reader
    clicked one step of one story, and a page about every story touching those two boxes is a different
    question. The pair keeps its page and is offered at the foot of the step's, where it belongs.

    THE ADDRESS NAMES THE STEP BY ITS NUMBER — the number on the board and in the popup, not an index —
    and resolves it through `flowStepIndex`, the one lookup the step chips already use, so the number a
    reader clicks and the step they land on cannot disagree."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    step = js[js.index("function flowStepInfoHtml(uc, i) {"):
              js.index("\nfunction ", js.index("function flowStepInfoHtml(uc, i) {") + 10)]
    assert "const mine = { kind: 'step', uc, sn: st.n };" in step
    assert "{ kind: 'edge', a: st.srcId, b: st.dstId }" not in step, "the pair was the first, wrong, door"
    assert "data-gosf" in step, "a step that runs a shared sub-flow keeps its own, more specific door"
    assert "'sn'];" in js, "the address can name a step"
    assert "if (s.kind === 'step') {" in js
    assert "flowStepIndex(uc, uc, Number(sn))" in js, "one lookup, and an address carries strings"
    assert "if (s.kind === 'step') return 'Step ' + s.sn;" in js, "the crumb is the number, not the phrase"
    # ONE `data-drill` HANDLER, for the card AND the page. It was written on the card alone, and the
    # first page to draw a drill button looked live and went nowhere.
    assert "PANEL_HOST.addEventListener('click', drillFrom);" in js
    assert "diagram.addEventListener('click', drillFrom);" in js


def test_a_pair_of_leaves_is_a_page_of_steps_not_an_empty_drawing() -> None:
    """`#v=edge&a=..&b=..` rendered "This view could not be rendered." for every pair of LEAF elements —
    a component and a record, two components — because the baked pair diagrams are minted for CONTAINER
    pairs only. The breadcrumb answered perfectly well over the empty stage ("Map assembly → Project
    map"), which is how it went unseen.

    IT IS A LIST, NOT A DRAWING. A container pair's diagram shows both subsystems, the components inside
    each and the arrows crossing, and that IS the answer there. Two leaves have nothing inside to draw,
    so the picture would be two boxes and a line — less than the breadcrumb above it.

    WHAT RUNS BETWEEN THEM is the answer instead. Measured on this repo's own map: 131 pairs are named
    by a flow step and only 33 have an authored arrow behind them, so for 97 the steps are the only
    record that anything passes; and 27 pairs carry more than one step. That last set is why the page
    exists — one pair appears in several steps meaning different things, which is exactly why the step
    popup shows only its own step and cannot speak for the pair."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fn = js[js.index("function renderLeafPair(a, b) {"):
            js.index("\n}", js.index("function renderLeafPair(a, b) {"))]
    assert "detailSec('runs', 'What runs between them'" in fn
    # A CARD PER USE CASE holding its own steps — the shape a component's page uses for its features.
    assert "elementCardHtml(g.uc, {" in fn and "lp-steps" in fn
    # The authored arrow is a DIFFERENT fact, and 97 of 131 pairs do not have one, so it is drawn only
    # where there is something to draw.
    assert "detailSec('wired', 'The connection behind it'" in fn
    assert "The map records nothing running between these two." in fn
    # The branch that reaches it: no baked card, AND both ends are kinds a flow step can name. As
    # narrow as the sentence it prints — `#v=edge` naming two SUBDOMAINS is a wrong-kind link, and a
    # confident "Pair: A -> B" over one would be worse than the blank it replaced.
    assert ("if (s.kind === 'edge' && !MERMAID_EDGE_CARD[s.a + '>' + s.b] && isLeafPair(s.a, s.b)) {"
            in js)
    assert "PAIR_LEAF_KINDS = new Set(['component', 'entity', 'interface', 'dep'])" in js
    # IT IS REACHED FROM A STEP'S PAGE, not from the popup. The popup's title opens THE STEP — a reader
    # at a flow arrow clicked one step of one story, and a page about every story touching those two
    # boxes answers a question they did not ask. The pair is offered at the foot of the step's page,
    # where it is a real second question (27 of this map's 131 pairs carry more than one step).
    stepfn = js[js.index("function renderFlowStepPage(uc, sn) {"):
                js.index("\n}", js.index("function renderFlowStepPage(uc, sn) {"))]
    assert "detailSec('pair', 'Also between these two'" in stepfn
    assert "pair.length > 1" in stepfn, "no line where this step is the only one between the two"


def test_the_zoom_control_is_absent_on_a_page_with_no_diagram() -> None:
    """The zoom control acts on the diagram's pan-zoom, which a page of HTML has none of. It used to sit
    in the title bar and go DIM there — chrome the whole app shares, carrying a control that did nothing
    on 9 of the 13 view tabs. It floats over the drawing now and is simply absent everywhere else.

    ASKED OF THE SCREEN, NOT OF A LIST. Two hand-kept lists answered this in turn and both drifted: the
    first named `usecases`, so a use-case FLOW (boxes, cylinders and an actor figure) counted as prose;
    TEXT_PAGES replaced it and never learned `interfaces`, so the Interfaces tab drew a card list with
    three lit buttons over it and every press moved nothing. `mainPz` IS the pan/zoom map — destroyed at
    the top of every renderView, rebuilt only by the branch that draws shapes — so there is no list left
    to drift."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "TEXT_VIEWS" not in js, "the second list of text views is back"
    fn = js[js.index("function syncZoomControls() {"):
            js.index("\n}", js.index("function syncZoomControls() {"))]
    assert "zoomctl.hidden = !mainPz" in fn, "the screen answers, not a list of page kinds"
    assert "TEXT_PAGES" not in fn, "a list of page kinds cannot answer what is drawn"
    # It floats over the drawing, in the TOP-RIGHT corner, and it is gone from the title bar — whose
    # dimming rules went with it. Its own corner, not a place in the #overlays column on the left: that
    # column's members change what the diagram SAYS (an environment filter, a step player) while this one
    # only moves the camera.
    assert "#zoomctl { position: absolute; right: 12px; top: 12px;" in css
    overlays = html[html.index('<div id="overlays">'): html.index('id="envpicker"')]
    assert "zoomctl" not in overlays, "it has a corner of its own, not a slot in the left column"
    header = html[html.index("<header>"): html.index("</header>")]
    assert "zoomctl" not in header and "zoomin" not in header
    assert "header button:disabled" not in css, "nothing in the title bar dims any more"
    assert "#zoomctl[hidden] { display: none; }" in css
    # THE SELECTION CARD KEEPS OFF IT. They share this corner, and up-and-right is the card's own first
    # choice (CARD_DIRS), so without this the card landed straight on the control: measured at 1440x900,
    # card top 27 against a control at 12. It is a KEEP-CLEAR SHAPE in placeCardNear's own machinery,
    # never a CSS offset — the stylesheet's `top` is overwritten by `put()` a moment later, which is
    # exactly how the first attempt at this failed.
    keep = js[js.index("function cardKeepSets(el) {"): js.index("\n}", js.index("function cardKeepSets(el) {"))]
    assert "zoomctl && !zoomctl.hidden" in keep, "no shape at all on a page that has no control"
    assert keep.count("...fixed") == 4, "in every set: a control is never the concession to make"
    # Its ceiling keeps it inside the box #diagwrap clips; the placement, not the ceiling, is what
    # keeps it off the control.
    pane = css[css.index("#panel {"): css.index("}", css.index("#panel {"))]
    assert "calc(100% - 24px)" in pane, "the card must stay inside the drawing #diagwrap clips"

def test_a_sentence_is_never_set_as_a_pill() -> None:
    """A collection's NOTE was rendered with `.dv-tag`, the pill class, which is `white-space: nowrap`
    because a tag is one word. A note is not: over the three real maps its 135 rows run to a median 78
    characters and a longest of 221. So on the Storage table one un-wrappable note demanded 513px and
    the browser paid for it out of the MEANING column beside it, which fell to 99px — the plain-English
    sentence the reader came for, set one word per line, while two further columns were pushed off the
    right edge. The same pill wrapped the same note in the entity info pane.

    Notes are prose (`.dv-note`); only `mode`, which really is one word, keeps a pill. And both sentence
    columns carry a min-width, because with `table-layout: auto` the widest cell in ANOTHER column is
    otherwise free to decide how little they get."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert 'class="dv-tag">${esc(st.notes)}' not in js and 'class="dv-tag">${esc(r.notes)}' not in js, \
        "a note is back in a pill that cannot wrap"
    assert 'class="dv-note">${esc(st.notes)}' in js and 'class="dv-note">${esc(r.notes)}' in js
    assert 'class="dv-tag">${esc(st.mode)}' in js and 'class="dv-tag">${esc(r.mode)}' in js, \
        "a one-word mode is a real tag and keeps its pill"
    assert "white-space: nowrap" not in css[css.index(".dv-note {"): css.index(".dv-note {") + 200]
    assert "min-width: 24ch" in css[css.index(".dv-meaning {"): css.index(".dv-meaning {") + 140]
    assert "min-width: 22ch" in css[css.index(".dv-notes {"): css.index(".dv-notes {") + 140]
    assert 'class="dv-notes"' in js, "the notes column needs its own class to carry that floor"

def test_the_system_tab_is_cards_over_one_builder() -> None:
    """It used to stack every collection on one scrolling page under a chip bar: on a real map that is
    664 entry points, 43 commands, 48 config keys, 32 types and 8 notes in a single scroll, and the
    chip bar was the only thing that said what was down there. Now it is the same card level the
    Features tab uses, with one collection per card. Cards and drill read ONE builder, so a card can
    never name a section the drill does not render, and the counts on the cards cannot drift from what
    opens. The bands exist because this tab holds three different kinds of thing, and are drawn only
    when there is more than one to tell apart."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "function systemSections() {" in js
    for fn in ("renderSystem", "renderSystemSection"):
        body = js[js.index(f"function {fn}("): js.index("\nfunction ", js.index(f"function {fn}(") + 10)] \
            if f"\nfunction " in js[js.index(f"function {fn}("):] else js[js.index(f"function {fn}("):]
        assert "systemSections()" in body, fn
    assert "plainCardHtml({ key: s.id, name: s.title" in js   # the ONE card component, as everywhere
    assert "go({ kind: 'sysSection', sys:" in js
    assert "const head = live.length > 1 ?" in js       # one band draws no label
    # The drill is a real level: keyed, titled, and reachable back up by breadcrumb.
    assert "const base = [{ kind: 'system' }, { kind: 'sysSection', sys: s.sys }];" in js
    assert "return s.epk ? base.concat([{ kind: 'sysSection', sys: s.sys, epk: s.epk }]) : base;" in js
    assert "'gid', 'sys', 'epk', 'iface', 'id', 'sec'," in js                 # …and its keys survive a right-pane navigation


def test_the_only_pinned_lines_are_the_ones_that_still_say_something() -> None:
    """The System section header was sticky back when nine collections shared one scrolling page and it
    told you which one you had scrolled into. Each collection has its own page now, its title sits at
    the top of it, and the breadcrumb names it permanently — so a sticky copy repeated a label already
    on screen and pushed the column headers further down. What still earns a pin is the index bar
    (which kind am I in) and the table's own COLUMN headers (what is this cell)."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    js = (VIEWER_DIR / "viewer.js").read_text()
    # The header is gone entirely now, not just unpinned: the breadcrumb's last item IS this page's
    # name, so a heading here printed it twice, inside a box that was a card wrapped round a table.
    assert ".system-wrap .uc-actor" not in css and ".system-wrap .uc-group" not in css
    sec = js[js.index("function renderSystemSection(sysId, epk) {"):
             js.index("\nfunction ", js.index("function renderSystemSection(sysId, epk) {") + 10)]
    assert "uc-group" not in sec and "uc-actor" not in sec
    assert "pageHeroHtml({" in sec, "the same hero a role's page and a feature's page use"
    assert "noDesc: false," in sec, "an entry-point kind is a bare word, not a missing sentence"
    th = css[css.index(".system-wrap .glossary thead th {"): css.index("}", css.index(".system-wrap .glossary thead th {"))]
    assert "top: var(--tab-index-h)" in th, "column headers pin directly under the bar, or to the top"
    assert "--sys-header-h" not in css, "the second offset died with the sticky header it measured"


def test_a_page_with_no_index_bar_reserves_no_room_for_one() -> None:
    """`--tab-index-h` defaulted to 40px in the stylesheet and was only ever overwritten when a bar was
    found. Seven of the System tab's ten collections have no bar, so their sticky column headers pinned
    40px down from the top and floated over the rows with an empty strip above them."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "--tab-index-h: 0px; }" in css
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = js[js.index("function bindTabIndex(wrap) {"): js.index("\n}", js.index("function bindTabIndex(wrap) {"))]
    assert "if (!nav) { wrap.style.setProperty('--tab-index-h', '0px'); return; }" in bind


def test_the_index_bar_is_a_direct_child_of_the_scroll_wrapper() -> None:
    """Its sticky geometry is written against the wrapper: negative side margins take it full-bleed, and
    the wrapper drops its own top padding only when it HAS a bar (`:has(> .tab-index)`). Nested one level
    down inside the section card, that selector missed and the wrapper kept a 16px transparent strip
    above the bar that rows scrolled visibly through. So the System drill emits the bar beside the
    section, not inside it, and the kinds it jumps to carry the scroll-margin that clears it."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    # The Entry points collection went one level deeper for the same reason the tab did: 311 rows under
    # a chip bar wrapping onto three lines is a flat list with pills. It carries its KINDS as data and
    # the page draws cards from them, so the cards and the table cannot disagree about a count.
    assert "kinds.push({ key: k, count: byKind[k].length" in js
    assert "if (found.kinds && !epk) {" in js
    assert "bindPlainCards(diagram, (key) => go({ kind: 'sysSection', sys: sysId, epk: key }));" in js
    assert "'gid', 'sys', 'epk', 'iface', 'id', 'sec'," in js


def test_no_scroll_wrapper_holds_a_sticky_line_below_its_own_top_padding() -> None:
    """A scroll container's top padding is not part of the scrollport: a sticky `top: 0` child pins to
    the PADDING box, so the padding stays open as a transparent strip that rows scroll visibly through
    ABOVE the pinned line. Measured on the Run commands page — column headers pinned 16px down with a
    table cell painted above them — and the same on Tests and on the Glossary tab. Every wrap holding a
    sticky line drops the padding; the breathing room becomes a MARGIN on the first child, which scrolls
    away like content instead of holding the gap open forever. Verified after: every page still rests
    16px down, every sticky line pins at 0, and the topmost thing while scrolled is the sticky line."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    # `.usecases-wrap.system-wrap`, not `.system-wrap`: the base class sets `padding` as a SHORTHAND
    # later in the file, and at equal specificity that shorthand puts the 16px back.
    assert ".usecases-wrap:has(> .tab-index), .usecases-wrap.system-wrap, .usecases-wrap.glossary-wrap { padding-top: 0; }" in css
    assert ".system-wrap > :first-child, .glossary-wrap > :first-child { margin-top: 16px; }" in css
    assert ".system-wrap > .tab-index:first-child { margin-top: 0; }" in css   # the bar carries its own
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "glossary-wrap\" style=\"padding-top" not in js, "an inline top padding reopens the strip"


# --- feature-led views (plan/80) ----------------------------------------------------------------

def _run_js_region(start_marker: str, end_marker: str, snippet: str) -> str:
    """Run `snippet` against a REGION of viewer.js lifted verbatim between two markers.

    Same trick as `_run_js`, which lifts the escaping helpers: the frontend has no module system, so
    a pure function of it is exercised by slicing its source and evaluating it. Sliced by marker
    lines, so a rename fails loudly here rather than silently testing an empty string."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed — skipping viewer JS behaviour gate")
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    lifted = js[js.index(start_marker): js.index(end_marker)]
    assert lifted.strip(), "the lifted region is empty — fix the markers"
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "probe.mjs"
        f.write_text(lifted + "\n" + snippet, encoding="utf-8")
        r = subprocess.run([node, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, f"probe failed:\n{r.stderr}"
    return r.stdout.strip()


def _run_js_regions(regions: list[tuple[str, str]], snippet: str) -> str:
    """`_run_js_region` for a function whose helpers live elsewhere in the file: lift SEVERAL slices,
    in the order given, and run the snippet against all of them. Same marker discipline."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed — skipping viewer JS behaviour gate")
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    lifted = []
    for start, end in regions:
        part = js[js.index(start): js.index(end)]
        assert part.strip(), f"the region {start!r} lifted nothing — fix the markers"
        lifted.append(part)
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "probe.mjs"
        f.write_text("\n".join(lifted) + "\n" + snippet, encoding="utf-8")
        r = subprocess.run([node, str(f)], capture_output=True, text=True)
    assert r.returncode == 0, f"probe failed:\n{r.stderr}"
    return r.stdout.strip()


def test_one_feature_reads_as_three_levels_and_not_seven_equal_rows() -> None:
    """A feature was a label on a use case: to answer "what does Billing & credits do, decide, know and
    run on?" you read four other views and joined them by hand. The first page that answered it put all
    seven answers in ONE definition list, so the purpose weighed the same as the component list, the use
    cases (which ARE the feature) were one row reading "10 use cases", and three rows were folded
    disclosures opening onto thirty unordered chips.

    Three levels now. A header answers "what is this" — name, label, purpose, who drives it. The use
    cases are the page's body. The rest of the map, filtered to this feature, follows as sections in
    reading order: the doors, the decisions, the data, the code. Order on the page IS order of
    importance, and every section carries its count in its heading, so nothing must be opened to be
    counted."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    head = js[js.index("function featureHeadHtml(capId) {"):
              js.index("\nfunction ", js.index("function featureHeadHtml(capId) {") + 10)]
    assert "pageHeroHtml({" in head
    # No `Used by` row: it listed the feature's actors as buttons, and the rail one line below names
    # every one of them on its boxes — the walk's drivers, and since the side stops moved under their
    # own driver, the off-walk ones too. Two rows of the same names is what the rail exists to remove.
    # NO LEAD WORD HERE. `Feature objective` rode this sentence and earned nothing: the sentence
    # already describes the feature the page is named after. An actor's goal is the one case that
    # needs one, and it is the only caller that passes `descLbl`.
    assert "descLbl" not in head, "an actor's goal is the one sentence that needs a lead word"
    assert "glyph: storyFeatureGlyphSvg()," in head and "name: f.name," in head
    css = (VIEWER_DIR / "viewer.css").read_text()
    hero = js[js.index("function pageHeroHtml(o) {"):
              js.index("\nfunction ", js.index("function pageHeroHtml(o) {") + 10)]
    # NO UPPERCASE LABELS ANYWHERE IN THE HERO. Two louder forms were built and dropped — a label
    # riding each line, and a label column beside them — and both told the reader they could not tell
    # a description from anything else on a page named after the thing being described.
    assert "page-hero-lbl" not in js and "page-hero-lbl" not in css
    assert "o.lbl" not in hero and "o.metaLbl" not in hero
    assert ".page-hero-meta { display: flex; align-items: baseline;" in css
    # …and the width cap is gone, so the line runs the full column.
    assert "max-width: 68ch" not in css
    assert '<span class="page-hero-lbl">Used by</span>' not in head
    assert "featrole" not in js, "the row's buttons went with it"
    assert "f.rules" not in head and "f.components" not in head, "the header holds no counts"
    # A feature's page and a decision area's page are the same shape, so they are the same function.
    assert "function pageHeroHtml(o) {" in js
    assert "pageHeroHtml({" in js[js.index("function renderRules(s) {"):]
    secs = js[js.index("function featurePanels(capId) {"):
              js.index("\nfunction ", js.index("function featurePanels(capId) {") + 10)]
    # A RETURNED LIST now, not a run of section calls: the strip SWITCHES between the panels instead
    # of scrolling to them, so each is a screen of its own that the address can name.
    order = re.findall(r"featPanel\('(\w+)', '([^']+)'", secs)
    # TWO SECTIONS WENT, and the page is stronger for it. "How you reach it" listed authored
    # addresses nothing checks (measured: 6 rows across mcpolis claim an address their own flow never
    # reaches) and cannot be derived instead (the tightest line test keeps 35 of 121 rows). "What it
    # reaches out to" was a SUBSET of the interface pills the use cases above already carry, on all
    # 15 features of the two live maps — the box-does-not-repeat-its-picture rule.
    # THE TITLES SAY WHAT THE LINK IS, and no more. "Rules it uses" and "Components that implement
    # it" were both tried and rejected on the map's own numbers: a rule is specified UNDER a feature
    # (authored, and the field's comment records that deriving it failed), and 15 of CAP1's 19
    # components are shared with other features, one of them with seven.
    # NAMED FOR THEIR TABS. A panel shows the same kind of thing its tab does, filtered to one
    # feature, so it wears the same word; what makes it this feature's is said in the sentence
    # under the title, where there is room to be accurate about it.
    assert [t for _, t in order] == ["Rules", "Data", "Components"], order
    # The use cases are emitted by the one list renderer, not by a second copy. On a feature's PAGE
    # they are the BOARD, drawn bare above the chip bar; the title below is the fallback for a list
    # that has no board (the "not assigned to a feature" one).
    assert "const title = page ? 'What you can do'" in js
    # The strip is built from the PANELS themselves, so it and the page cannot disagree about what
    # this feature has or how much of it.
    assert "panels.map((x) =>" in js, "the strip is built from the panels themselves"
    # NOTHING FOLDS ANY MORE. The code section folded because it was the last of five stacked
    # sections and the page was long; each is a panel of its own now, so there is nothing below it
    # to push down and a reader who picked that panel has already said they want the parts.
    region = js[js.index("// \u2500\u2500 the feature page"): js.index("function bindFeaturePage(root) {")]
    assert region.count("<details") == 0 and "feat-fold" not in js


def test_the_section_chips_carry_the_counts_and_the_headings_do_not() -> None:
    """The chip bar is the page's contents AND its summary: "15 rules, 7 entities" answered before any
    scrolling, from the one list the sections register themselves in. Each count is stated ONCE \u2014 a
    heading repeating it read as a second fact on a page where every section has a number. The count
    stays optional per section, so the tabs indexing untallied things are untouched."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    sec = js[js.index("function featSection(secs, key, title, n, body, glyph) {"):
             js.index("\nfunction ", js.index("function featSection(secs, key, title, n, body, glyph) {") + 10)]
    assert "itemSectionHtml(secs, 'feat-' + key, title, n, '', body, glyph)" in sec, \
        "one framed section with a strip head, the shape every item page draws"
    assert "uc-actor-wants" not in sec, "the heading states no count"
    idx = js[js.index("function tabIndexHtml(secs) {"):
             js.index("\nfunction ", js.index("function tabIndexHtml(secs) {") + 10)]
    assert "sec.count ?" in idx and "tab-index-n" in idx, "the count rides the chip, when there is one"
    # The use-case section is emitted by the list renderer, so it drops its own heading count only on
    # a feature's PAGE \u2014 the "not assigned to a feature" list is not that page and keeps it.
    assert "(page ? '' : `<span class=\"uc-actor-wants\">${count}</span>`)" in js
    assert "function featCount(" not in js, "the heading's count helper went with the heading's count"
    assert ".tab-index-n" in (VIEWER_DIR / "viewer.css").read_text()


def test_a_feature_page_draws_the_walk_as_a_rail_not_a_grid() -> None:
    """The map knows the ORDER of what a feature does \u2014 "Building a map" owns steps 2 to 7 of the walk
    \u2014 and the card grid threw it away, drawing eight cards in model order that said nothing about
    which came first. The rail is the actor page's board with the two keys swapped: stations in walk
    order, side stops under the dashed cut, zoned by DRIVER instead of by feature."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fj = js[js.index("function featureJourney(capId) {"):
            js.index("\nfunction ", js.index("function featureJourney(capId) {") + 10)]
    assert "actorsOfStep(" in fj, "the walk's own record of who drives a step"
    assert "stations: run.items" in fj, "a station IS the walk step, the shape the actor rail uses"
    # …and that record is read in ONE place, in the authored name space, by all three boards. It was
    # written out at each of them, and the copies had begun to drift.
    aos = js[js.index("function actorsOfStep(stepId) {"):
             js.index("\n}", js.index("function actorsOfStep(stepId) {"))]
    assert "HP_ACTORS_OF_STEP[stepId]" in aos and "authoredActorName(d.name)" in aos
    rail = js[js.index("function featureRailHtml(capId) {"):
              js.index("\nfunction ", js.index("function featureRailHtml(capId) {") + 10)]
    assert "journeyZoneHtml(z, {" in rail, "the same cells the actor rail is built from"
    assert "data-cap=" not in rail, "a zone is named by its driver here, never by the feature"
    assert "tint: featureTint(capId)" in rail, "one feature, so one colour for every zone"
    lbl = js[js.index("function journeyDriverLabelHtml(acts) {"):
             js.index("\nfunction ", js.index("function journeyDriverLabelHtml(acts) {") + 10)]
    assert "data-act=" in lbl and "storyGlyphSvg(roleKindOfName(act))" in lbl
    # EVERY interchangeable driver of the box is named, each with its OWN glyph: a box naming a person
    # and a program cannot draw one figure for both, and picking the first one's figure is the same
    # silent deletion that naming only the leftmost driver made.
    assert "list.map(one).join(" in lbl and "journey-zor" in lbl
    assert "actorNodeId(act)" in lbl, "…and a name is a door only when it leads somewhere"
    # `Other` is the bucket an undeclared actor falls in, and it names no page \u2014 the same test the
    # use-case card's driver pill already makes before it lets its name be clicked.
    assert "journey-zkind" in lbl
    assert ".journey-zor {" in (VIEWER_DIR / "viewer.css").read_text()
    # The caller draws the board BARE, above the chip bar, and keeps the grid only for a list with no
    # board of its own.
    assert "featureRailHtml(page), itemGlyphSvg('usecase'))" in js, "the rail, as the page's first section"
    assert "if (board) return '';" in js, "the use-case group emits nothing when the board draws"
    assert '<div class="usecases-wrap">${head}${board}${index}' in js


def test_a_feature_board_wears_no_section_frame() -> None:
    """The feature board was wrapped in a "What you can do" section, and all three parts of that wrapper
    said something the page already says. The frame was a card containing a card, the shape this viewer
    removes everywhere it appears. The heading named the page's own subject under a breadcrumb that is
    the page's title. The chip jumped to the top of the page, where the reader already was.

    The actor board never had any of the three, so the two pages drew one picture two ways. They draw it
    one way now: bare, under the hero, with the chip bar indexing the four sections that follow it."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    # The board is not registered as a section, so it gets no chip and no heading.
    ren = js[js.index("function renderUseCases(sel) {"):
             js.index("\nfunction ", js.index("function renderUseCases(sel) {") + 10)]
    assert ren.count("secs.push({ id: secId, title, count: ids.length });") == 1, \
        "the one push left is the no-board fallback's"
    assert "${board}${index}" in ren, "the board leads the page, the chip bar indexes what follows"
    # …and the board keeps its own frame, because there is no section around it to be the card.
    assert ".hp-board, .journey-board, .ifd-wrap, .story-wrap, #diagwrap {" in css


def test_a_side_stop_hangs_under_the_actor_who_drives_it() -> None:
    """An off-walk use case used to be dumped into `zones[0]`, whose box belongs to whoever drives the
    FIRST step of the feature. So on any feature with more than one driver \u2014 4 of the 7 on this
    project's own map \u2014 the rail said that actor does things they never do. It is the mirror of a
    bug the actor page never had: there a side stop hangs under its own FEATURE, not under the first.

    The driver comes from `actorGroups()`, the one grouping the actor page and the cast cards already
    read, so three screens cannot disagree about who drives a use case. Two of its rules come along and
    both are wanted: a use case naming several INTERCHANGEABLE actors is listed under every one of them,
    and one undeclared name sends the whole use case to `Other` rather than to a half-known home.

    A driver the walk never reaches opens a TRAILING zone, drawn exactly like the others \u2014 the actor
    page's rule for a feature it never enters, with the two keys swapped. They order by the story
    diagram's CAST column, the one derived actor order every screen agrees on."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fj = js[js.index("function featureJourney(capId) {"):
            js.index("\nfunction ", js.index("function featureJourney(capId) {") + 10)]
    assert "zones[0].sides" not in js, "a side stop is not filed under whoever drives step one"
    assert "for (const g of actorGroups()) for (const n of g.ucs)" in fj, \
        "one grouping answers who drives a use case"
    assert "if (onWalk.has(id)) continue;" in fj
    # A driver's FIRST zone takes them, the rule the actor page applies to a feature entered twice.
    # A box naming several interchangeable drivers is the box for each of them.
    assert "for (const z of zones) for (const a of z.acts) if (a && !(a in firstOf)) firstOf[a] = z;" in fj
    # Once per ACTOR, and at most once per BOX: a use case naming two interchangeable actors belongs
    # to both, but one box naming both of them must not draw the same circle twice.
    assert "const placed = new Set();" in fj and "if (placed.has(z)) continue;" in fj
    # ...and a driver with no zone gets one after the rail, in cast order.
    assert "offZones.push(offByActor[a] = { acts: [a], stations: [], sides: [] })" in fj
    assert "((FEATURES.story || {}).cast || []).map((rid) => roleName(rid))" in fj
    assert "offZones.sort((a, b) => pos(a) - pos(b));" in fj
    # Side stops read in the FEATURE's own use-case order, not in the order the groups were built.
    assert "for (const id of f.useCases || []) {" in fj
    # The zone's name is the AUTHORED one. The walk records the folded spelling the diagrams draw, and
    # every other reader of `act` \u2014 the label, the link, roleKindOfName, the actorGroups match \u2014
    # speaks the authored space. One table crosses the two, which is what ROLE_BY_NAME's comment asks.
    assert "actorsOfStep(" in fj
    aos = js[js.index("function actorsOfStep(stepId) {"):
             js.index("\n}", js.index("function actorsOfStep(stepId) {"))]
    assert "map((d) => authoredActorName(d.name))" in aos
    auth = js[js.index("function authoredActorName(drawn) {"):
              js.index("\nfunction ", js.index("function authoredActorName(drawn) {") + 10)]
    assert "ROLE_BY_SAFENAME[String(drawn || '').trim().toLowerCase()]" in auth
    assert "ROLE_BY_SAFENAME[safeMsgName(r.name || '').toLowerCase()] = r;" in js


def test_a_feature_the_walk_never_enters_still_draws_the_board() -> None:
    """The feature page used to drop the rail and draw a card grid when the walk never enters the
    feature, so the page changed shape depending on the map. The actor page answers the same situation
    (argus's Page owner never appears on the walk) by drawing the board with ONE lane, because
    "everything here is off the happy path" is an answer, not an absence. The feature page now does the
    same, and the gutter still names the lane it kept.

    The cost is real: a card carried each use case's sentence and a side stop does not. What the board
    buys instead is the one thing the grid could never say, which is who drives what. Only a feature
    with no use cases at all draws nothing."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    rail = js[js.index("function featureRailHtml(capId) {"):
              js.index("\nfunction ", js.index("function featureRailHtml(capId) {") + 10)]
    assert "if (!zones.length && !offZones.length) return '';" in rail, \
        "only a feature with no use cases at all draws nothing"
    assert "const hasPath = zones.some((z) => z.stations.length);" in rail
    # The two lanes are switched on and off in ONE place, shared with the actor board.
    assert "journeyRailHtml(hasPath, offLane, boxes(zones, true) + boxes(offZones, false))" in rail
    shared = js[js.index("function journeyRailHtml(hasPath, offLane, boxes, partLane) {"):
                js.index("\nfunction ", js.index("function journeyRailHtml(hasPath, offLane, boxes, partLane) {") + 10)]
    assert "hasPath ? '<div class=\"journey-gutter journey-gutter-on\">Happy path</div>' : ''" in shared
    assert "hasPath ? '' : ' journey-no-path'" in shared, "one lane, and no cut to draw"
    assert ".journey-no-path .journey-sides, .journey-no-path .journey-gutter-off" in css
    assert "gapBefore: !lead && i === 0 && zones.length," in rail


def test_the_rail_keeps_the_marks_the_cards_carried() -> None:
    """The rail replaced the use-case cards on a feature's page, and it took both of their marks with
    it: in change-impact mode the page could no longer say which use cases changed, and an untraced use
    case stopped being distinguishable from a phantom one. Both are back, on a station and on a side
    stop, read from the SAME two sources the card reads so the two can never disagree."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    marks = js[js.index("function journeyMarksHtml(ucId) {"):
               js.index("\nfunction ", js.index("function journeyMarksHtml(ucId) {") + 10)]
    assert "mode === 'diff' && hasDiff() && usecaseDiffState(ucId)" in marks
    assert "(FLOWS_NARR && FLOWS_NARR[ucId]) ? ''" in marks
    zone = js[js.index("function journeyZoneHtml(z, opts) {"):
              js.index("\nfunction ", js.index("function journeyZoneHtml(z, opts) {") + 10)]
    step = js[js.index("function flowStepBoxHtml(st, o) {"):
              js.index("\nfunction ", js.index("function flowStepBoxHtml(st, o) {") + 10)]
    # A STATION carries them through the shared box, which draws them when its caller asks; a SIDE
    # STOP still draws its own, because a stop is not a step. Both, which is what this pins.
    assert "opt.marks ? journeyMarksHtml(st.uc) : ''" in step
    assert "marks: true" in zone, "…and the rail is the caller that asks"
    assert "${journeyMarksHtml(uc.id)}" in zone, "a side stop carries them too"
    # The card's own two colours, so one mark means one thing wherever it is drawn.
    assert ".journey-mark-changed { background: #fff8c5; color: #9a6700; }" in css
    assert ".journey-mark-untraced { background: #fef3c7; color: #92400e; }" in css
    assert ".badge.modified { background: #fff8c5; color: #9a6700; }" in css
    assert "background: #fef3c7; color: #92400e; }" in css[css.index(".uc-untraced"):]


def test_a_feature_rail_breaks_a_zone_on_a_new_driver_and_on_nothing_else() -> None:
    """A new box on a change of DRIVER, and on nothing else \u2014 the actor page's rule with the two keys
    swapped, which is what makes the two boards one picture drawn twice.

    It also cut on a GAP in the walk, meaning the walk left this feature and came back. That cut was
    unreadable here and readable on the actor page, for the same reason: a cut is only legible when the
    two boxes it makes carry different names. On the actor page they always do, because the thing that
    changed IS the box's name. Here the driver has not changed, so the reader met two boxes with one
    name, side by side, and nothing between them saying why \u2014 the reason lived on a page they were
    not on. Measured across the four maps the viewer reads: 5 of the 34 features drew such a pair, MCP
    Hero's "Tool access through the gateway" among them (its steps 13 and 15, with step 14 in another
    feature between them).

    Nothing is lost that the page ever showed. The stations stay in walk order, and no station has
    carried its position in the walk since the step numbers were dropped, so a box claims the ORDER of
    its stations and never their adjacency. A driver who really does return after somebody else still
    gets two boxes, because the driver changed in between: on the Mio map "Paying for Mio" draws
    Workspace admin, Payment provider, Workspace admin, and that picture explains itself."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fj = js[js.index("function featureJourney(capId) {"):
            js.index("\nfunction ", js.index("function featureJourney(capId) {") + 10)]
    assert "runsOf(mine, (st) => zoneKey(actorsOfStep(st.id)))" in fj, \
        "a new zone on a change of the whole driver SET, and on nothing else"
    assert "function zoneKey(acts) {" in js, "a zone's identity is the SET of its drivers"
    # One rule under all three boards: consecutive items answering a key the same way. Each board
    # brings its own key — the feature, the drivers, or both — and none of them keeps a loop.
    runs = js[js.index("function runsOf(items, keyOf) {"):
              js.index("\n}", js.index("function runsOf(items, keyOf) {"))]
    assert "if (last && last.key === key) last.items.push(it);" in runs
    assert js.count("let run = null;") == 0, "no board keeps a run loop of its own"
    assert "prev + 1" not in fj and "prev = i" not in fj, \
        "the walk position is not compared any more, so it is not tracked"
    # …and the actor rail's own rule is the mirror: a new box on a change of FEATURE, never on a gap,
    # because on that page a gap is only other people acting.
    aj = js[js.index("function actorJourney(actorName) {"):
            js.index("\nfunction ", js.index("function actorJourney(actorName) {") + 10)]
    assert "runsOf(stations, (s) => featureOfUc(s.uc))" in aj
    assert 'class="journey-n"' not in js, "no rail numbers its stations"


def test_one_board_and_one_binder_serve_both_rails() -> None:
    """The actor page and the feature page draw the same picture of the same walk, so the cells, the
    grid and the clicks exist once. Which id a zone's name carries is what says which page it is \u2014
    the same branch the story cards' name handler makes \u2014 rather than a flag passed down."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = js[js.index("function bindJourney(root, o) {"):
              js.index("\nfunction ", js.index("function bindJourney(root, o) {") + 10)]
    assert "if (cap) go({ kind: 'capability', cap });" in bind
    assert "go({ kind: 'actor', act: b.getAttribute('data-act') })" in bind
    assert "function bindActorPage(root, actorName) {" in js and "bindJourney(root, { act: actorName });" in js
    feat = js[js.index("function bindFeaturePage(root) {"):
              js.index("\nfunction ", js.index("function bindFeaturePage(root) {") + 10)]
    assert "bindJourney(root, {});" in feat, "the feature page wires its rail with the same binder"
    # ONE zone renderer, and the tint is the only thing the two pages disagree on.
    zone = js[js.index("function journeyZoneHtml(z, opts) {"):
              js.index("\nfunction ", js.index("function journeyZoneHtml(z, opts) {") + 10)]
    assert "o.tint || (z.fid ? featureTint(z.fid) : '')" in zone
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert ".usecases-wrap:has(.journey-board)" in css, "a board earns the same measure on both pages"
    # Neither board is nested in a section, so neither needs the rule that used to strip its frame.
    assert ".uc-group > .journey-board" not in css


def test_a_long_list_on_the_feature_page_is_grouped_not_dumped() -> None:
    """One live feature is built from 55 components and another from 31. As one flat run of chips that
    is a wall that says nothing about shape. Grouped under the subsystem each component lives in, the
    same list answers which parts of the machine the feature occupies. Entities group the same way, by
    subdomain, because both ride the same `parent` pointer. One group is not a grouping — a single
    heading repeating the section heading above it is drawn plain instead."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    grp = js[js.index("function featComponentGroupsHtml(ids) {"):
             js.index("\nfunction ", js.index("function featComponentGroupsHtml(ids) {") + 10)]
    assert "(GRAPH.nodes[id] || {}).parent" in grp
    assert "if (order.length < 2) return chips(ids);" in grp
    # A feature's rules are cut by DECISION AREA, the same cut the Rules tab makes.
    # IT USED TO BE SHARED with a component's page, which listed the rules enforced in it under the
    # same areas. That section is gone: the rules are a tab of their own, and each rule's own page
    # names every component it is enforced in, so the component->rules direction was the third place
    # one join was drawn. `rulesByBlock` is now the Features page's alone.
    assert "function rulesByBlock(ids) {" in js
    assert "function decidesHtml(" not in js, "the component's copy of this list is back"


def test_a_record_page_says_who_owns_it_only_when_the_map_does() -> None:
    """The field's day-one consumer, so an authored owner cannot sit in the map unread. It reads the
    EFFECTIVE owner the server derived from the authored field (the record's own, else its area's) —
    a record absent from that table is one nobody decided for, and the row is not drawn."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fn = js[js.index("function ownedByHtml(id) {"):js.index("\nfunction persistedInHtml(id) {")]
    assert "ENTITY_OWNERS[id]" in fn
    assert "if (!own.length) return '';" in fn, "no decision, no row"
    assert "own.map((c) => itemPillHtml(c))" in fn, "each owner is a door, in the shared pill"
    assert "ENTITY_OWNERS = FEATURES.entityOwners || {};" in js
    assert "runByHtml(id) + ownedByHtml(id) + persistedInHtml(id)" in js
    assert "detailSec('owner', 'Owned by'" in fn, "one framed section, like every other row"



def test_a_feature_page_never_claims_more_certainty_than_the_join_has() -> None:
    """Two silences the page must break. Rules enforced where NO use-case walk passes cannot be placed
    on any feature (27 of 66 on one live map, 47 of 96 on another), so a page listing only the joined
    ones claims the feature decides less than it does. And with no code index a rule is linked only on
    an exact line match, which makes every rule list a floor. Both notes sit directly under the count
    they qualify, not somewhere in the middle of the page."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    notes = js[js.index("function featRuleNotes() {"):
               js.index("\nfunction ", js.index("function featRuleNotes() {") + 10)]
    assert "FEAT_COVERAGE.rulesUnjoined" in notes and "no use-case walk passes" in notes
    assert "FEATURES.ruleJoinUsesExtents === false" in notes and "floor" in notes
    secs = js[js.index("function featurePanels(capId) {"):
              js.index("\nfunction ", js.index("function featurePanels(capId) {") + 10)]
    assert "featRuleNotes()" not in secs, "a product page carries no coyomap statistic"
    # A feature deciding nothing still says so. The section draws DECISION AREAS now, so the silence
    # it must name is the area-level one: an area carries the authored list of features it is
    # specified under, and on coyomap's own map 0 of 11 areas carry one at all.
    assert "featEmpty('Not recorded: no decision area says it is specified under this feature.')" in secs
    # The notes still exist — on the System tab, with every other fact about coyomap's own analysis.
    cov = js[js.index("function unreachedHtml() {"):
             js.index("\nfunction ", js.index("function unreachedHtml() {") + 10)]
    assert "featRuleNotes()" in cov and "coverageLineHtml()" in cov


def test_the_feature_page_reads_the_python_join_and_never_redoes_it() -> None:
    """`coyomap.features` joins a feature to its rules through `validate_model.rule_steps` — the SAME
    reader the Rules view uses, so the two screens cannot disagree about what one rule governs. A
    second join written in JS would drift from both. The page therefore reads the shipped lists and
    counts nothing itself."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    secs = js[js.index("function featurePanels(capId) {"):
              js.index("\nfunction ", js.index("function featurePanels(capId) {") + 10)]
    assert "FEAT_BY_ID[capId]" in secs
    for field in ("f.rules", "f.entities", "f.components"):
        assert field in secs, field
    assert "USES_BY_NODE" not in secs, "the component join lives in Python only"
    assert "FEATURES = b.features || {};" in js, "the derivation is shipped, not recomputed"


def test_a_row_is_only_a_use_case_when_it_names_one() -> None:
    """The feature page draws its RULES as rows of the same shape as the use cases above them, on
    purpose: two lists on one page should read as the same kind of thing. But the use-case binder
    claimed every `.uc-row` in the view, so clicking a rule opened `{kind:'usecase', uc:null}` and
    landed the reader on a screen with no name and no crumb. The selector asks for the attribute that
    makes a row a use case, not for the class that makes it look like one."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "diagram.querySelectorAll('.uc-row')" not in js, "a bare row selector claims other pages' rows"
    # The lists are element CARDS now, and the same rule holds one level up: the shared binder acts on
    # `.ecard[data-id]`, and a caller's own control inside a card opts out with `data-card-own`.
    # Only the BINDER half is pinned: the opt-out has no producer since the use-case Happy-Path pill
    # was removed, and pinning a producer that no longer exists would fail on the next honest edit.
    bind = js[js.index("function bindElementCards(root, onDrill) {"):
              js.index("\nfunction ", js.index("function bindElementCards(root, onDrill) {") + 10)]
    assert "root.querySelectorAll('.ecard[data-id]')" in bind
    assert "ev.target.closest('[data-card-own]')" in bind


def test_every_name_on_the_feature_page_resolves_its_view_at_runtime() -> None:
    """`selectTargetFor` is the ONE function that answers "which view draws this id". Regrouping the
    tabs, and the pointing layer being designed beside this, both change where an element lives — so a
    link that hardcoded a tab name would rot silently. Every element name on the page goes through it;
    a ROLE is not an element and has no node, so it opens its own list instead."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = js[js.index("function bindFeaturePage(root) {"):
              js.index("\nfunction ", js.index("function bindFeaturePage(root) {") + 10)]
    # The element names on this page are ITEM PILLS, and `drillInto` is the same kind of single answer
    # on the other side of the click: it switches on the element's own kind, so no caller names a tab.
    assert "bindItemPills(root);" in bind
    pills = js[js.index("function bindItemPills(root) {"):
               js.index("\n}", js.index("function bindItemPills(root) {"))]
    assert "itemPillTarget(id)(id);" in pills, "one destination, resolved by kind"
    assert "kind: '" not in pills, "and no tab named at the call site"
    # …and the kind is what picks between the element's own PAGE and the diagram that DRAWS it.
    target = js[js.index("function itemPillTarget(id) {"):
                js.index("\n}", js.index("function itemPillTarget(id) {"))]
    assert "n.kind === 'entity' || n.kind === 'component'" in target
    assert "showInContext" in target and "drillInto" in target
    assert "kind: 'container'" not in bind and "kind: 'domain'" not in bind
    # The role links on this page are the RAIL's zone names now, wired by the binder both boards share
    # rather than by a second handler of this page's own.
    assert "bindJourney(root, {});" in bind
    jbind = js[js.index("function bindJourney(root, o) {"):
               js.index("\nfunction ", js.index("function bindJourney(root, o) {") + 10)]
    assert "go({ kind: 'actor', act: b.getAttribute('data-act') })" in jbind
    # A feature has no box on any diagram, so its home is its own page — without this case a feature
    # id fell through to the default and opened Dependencies.
    target = js[js.index("function selectTargetFor(id) {"):
                js.index("\nfunction ", js.index("function selectTargetFor(id) {") + 10)]
    assert "case 'capability':" in target


def test_a_grouped_card_list_is_one_component_used_by_its_screens() -> None:
    """A third shape, between the flat card list and the card grid: the SAME cards, cut into sections by
    a heading. It earns its place where a set has a natural cut that is not a level — a rule page's
    decision areas, the unreached components' four groups. Three screens had hand-rolled the shape,
    which is the drift the spec's "centralize the card designs" exists to stop. (The grid variant left
    with its one user, the Actors card grid — the shape is a LIST again, full stop.)

    The section is NOT a card. It was, in a tinted frame containing its members, and two nested card
    shapes on one screen read as two levels of thing when there is only one — the reader had to work out
    whether the frame was itself something to click. So the cards keep the plain look and width, and the
    break is carried by a heading, space and a hairline."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    body = js[js.index("function elementCardGroupsHtml(groups) {"):
              js.index("\nfunction ", js.index("function elementCardGroupsHtml(groups) {") + 10)]
    # A group names its members by id, or brings them already DRAWN (`cards`) — the Changes tab lists
    # removed boxes and arrows, which are no element of this map — and the section is the same either way.
    assert "csec" in body and "body(g.ids, g.per, g.cards)" in body and "cards !== undefined ? cards" in body
    # A count and a description are OFFERED, not automatic. The callers that DO pass a count give it
    # a noun ("8 rules"), which is information — and the count goes in the SHARED count pill, so a
    # group's count over a card list and the same count on a card are one badge, not two.
    assert "(g.count ? countPillOf(g.count) : '')" in body
    assert "mcard" not in js and "mcard" not in css, "the boxed section is gone, not shadowed"
    sec = css[css.index(".csec-head {"): css.index("}", css.index(".csec-head {"))]
    assert "border-bottom" in sec
    for boxed in ("border-radius", "background"):
        rule = css[css.index("\n.csec {") : css.index("}", css.index("\n.csec {"))] if "\n.csec {" in css else ""
        assert boxed not in rule, "a section must not draw itself as a card"
    # An empty group is dropped, and a lone group draws no frame: one heading repeating the page title
    # says nothing.
    assert "filter((g) => (g.ids && g.ids.length) || g.cards)" in body
    assert "if (live.length === 1) return body(live[0].ids, live[0].per, live[0].cards);" in body
    for caller in ("function ruleAnalysisGapsHtml() {", "function unreachedHtml() {"):
        fn = js[js.index(caller): js.index("\nfunction ", js.index(caller) + 10)]
        assert "elementCardGroupsHtml(" in fn, caller
    assert "feat-rulegroup" not in js, "the hand-rolled group shape is gone, not shadowed"

def test_an_actors_goal_keeps_the_grammar_its_author_wrote() -> None:
    """The goal sentence is only ever capitalised. Its leading `to` used to be stripped, and that was
    right for exactly as long as a `Wants to` label stood in front of it and would otherwise have
    said the word twice. No caller draws that label any more, and the strip went on rewriting the
    author's grammar.

    IT BREAKS ON A SECOND INFINITIVE. "to find out what Meerbot does, and to decide whether to sign
    up" came out as "Find out what Meerbot does, and to decide whether to sign up", which is not a
    sentence — the two halves stopped being parallel. Measured across the six mapped projects: 22 of
    the 28 goals open with `to`, and 4 of those carry a second one.

    NOTHING IS CHANGED AT ALL NOW, not even the first letter. Raising it was the next attempt, and it
    is unnecessary once a label leads the line — and unsafe in the other direction, since lowering it
    would eat the capital on "Mio set up for the whole team". Mixed case across maps costs nothing:
    no screen shows two maps, and each of the six is internally consistent."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fn = js[js.index("function wantsSentence(wants) {"):
            js.index("\n}", js.index("function wantsSentence(wants) {"))]
    # THE LABEL LIVES HERE, not at the six call sites. An actor's goal is drawn on six screens, and a
    # label added per screen is a label one screen forgets.
    assert "return 'Goal: ' + s;" in fn
    assert "replace(" not in fn and "toUpperCase" not in fn, "the sentence is the author's, untouched"
    assert js.count("wantsSentence(") == 8, \
        "the function, the six screens that draw a goal, and the item box's own spec builder"
    # …and the hero's own lead-word slot went with it: it had exactly one user, and it applied the
    # word to the recorded-nothing case too — "Goal: This map does not say what this actor wants."
    assert "descLbl" not in js and "page-hero-lead" not in js
    assert "page-hero-lead" not in (VIEWER_DIR / "viewer.css").read_text()
    # …and no caller has put a `wants`-style label back in front of it, which is the only thing that
    # would make the word redundant again. Checked on what is DRAWN, not on the comments that record
    # why it went.
    drawn = "".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))
    assert "Wants to" not in drawn and "Wants:" not in drawn


def test_an_actors_side_is_one_pill_the_card_and_its_page_agree_on() -> None:
    """The card said `SERVICE`; the actor's own page, one click later, said `service` + `STAFF-OWNED`
    about the same actor, and never printed a side on the card at all. Both now read ONE function.

    Four readings:
        person  + user      ->  (nothing)          a person on the customer's side is the ordinary case
        person  + internal  ->  STAFF
        program + internal  ->  INTERNAL SERVICE   a machine the company runs, or pays a vendor to run
        program + user      ->  USER SERVICE       a machine the CUSTOMER set up

    Two words for one stored value, on purpose, and the rule that picks between them is THE READER'S
    WORD MUST FIT THE THING IT LABELS. `staff` is right about a person and wrong about a scheduler or a
    bought payment provider, which is exactly why the model stopped storing it. `internal` is right
    about all three. So the model stores `internal` and each card prints the word that fits what it
    describes. `staff service` was proposed and dropped: it says a program is staff, which is the one
    thing the rename fixed. The two words never meet on one card, and each says "ours".

    Leaving the company's own machines silent hid the single thing the vendor rule exists to settle:
    Mio Coworker's Stripe webhook was authored as the customer's, and a card reading plain `SERVICE`
    looks the same whether that is right or wrong.

    A PERSON stays silent on the customer's side. An actor is a person on the customer's side unless it
    says otherwise — the same rule that drops `human` from every actor card and `user` from a feature
    card. Printing `USER` on every person was tried for one round and undone: it makes the axis look
    complete beside the programs, but the cure is a word on eleven cards that only restates the default.

    `staff` is the reader's word on a FEATURE too, since only human roles vote for its audience."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    fn = js[js.index("function actorSidePills(kind, audience) {"):
            js.index("\nfunction ", js.index("function actorSidePills(kind, audience) {") + 10)]
    assert "text: side ? `${side} ${w}` : w" in fn, "a program always prints its side"
    # …AND SO DOES AN AI AGENT. Leaving the side off one was tried and undone by this very rule: for a
    # program the side is the whole point, because it says whether the CUSTOMER set it up or we did.
    # One branch covers every program, so a fourth kind cannot quietly get different treatment.
    assert fn.count("isMachineActor(kind)") == 1, \
        "ONE branch for every program, so the side can never be dropped for one kind of them"
    assert "actorKindWord(kind)" in fn, "only the WORD varies by kind; `ai-agent` is not a reader's word"
    assert "audienceWord(side)" in fn and "staff service" not in fn, "a program is never called staff"
    assert "kind === 'human' && side === 'internal'" in fn, \
        "a person prints a side only when it is the company's"
    # Colour says WHAT it is, the words say whose: both program readings keep the one program colour.
    assert fn.count("ecard-pill-service") == 1 and "cls: `uc-aud-${side}`" in fn
    # The card and the page draw the SAME pills — the page must not compute its own. It draws none at all
    # now: an element page's pills ride the breadcrumb beside the name, read from cardFacts, so the
    # surfaces cannot disagree by construction. Every renderer that shows the pills goes through this
    # one helper: cardFacts, and the story diagram's actor card.
    code = "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))
    # The dead form is `staff-owned` — the word the rename removed, aimed exactly. A blanket ban on
    # `-owned` stood here until an unrelated CSS class (`story-area-owned`, on a data area whose
    # owning FEATURE is authored) tripped it: a guard that fires on any word containing "owned"
    # stops being a statement about the actor vocabulary.
    assert "staff-owned" not in code.lower(), "the page's second form for a machine is back"
    assert "OWNED" not in "".join(l for l in code.splitlines() if "ecard-pill" in l), \
        "no pill prints an -OWNED word"
    assert js.count("actorSidePills(") == 4, \
        ("the helper itself, cardFacts, the story actor card, and the interface page's far-side card. "
         "Nothing else — an actor page's hero asks `cardFacts` through `elementPillsHtml`, which is "
         "this same helper one call further down, and the actor card its surfaces picture used to "
         "draw is gone. A ROLE is not in `GRAPH.nodes`, so `elementCardHtml` cannot draw one, and "
         "every one of these renderers must ask this helper rather than decide for itself which pill "
         "an actor wears")
    head = js[js.index("function actorPageHeroHtml(actorName) {"):
              js.index("\n}", js.index("function actorPageHeroHtml(actorName) {"))]
    head = "\n".join(l for l in head.splitlines() if not l.lstrip().startswith("//"))
    assert "pills: elementSidePillsHtml(actorNodeId(actorName))," in head, \
        ("…from the ONE builder every element page uses. `of its own` is the guard that still "
         "matters: no hand-built pill list here, so a card and this page cannot disagree")
    # The reader's word is applied in ONE place, and only where the side is about people.
    assert "function audienceWord(side) {" in js
    # `.ecard-pill` sets a grey background LATER in the file than `.uc-aud-*` sets its own, so a
    # single-class rule loses the cascade and the side pill comes out the same grey as `ACTOR` beside
    # it — present, and easy to read as absent. Both classes, or it silently has no colour.
    assert ".ecard-pill.uc-aud-internal {" in css and ".ecard-pill.uc-aud-user {" in css
    assert "ecard-pill-side" not in css and "ecard-pill-side" not in js
    assert "audienceWord(a)" in js, "the feature card, which is now the only place that draws the word"

def test_a_screen_you_choose_from_is_a_grid_wherever_it_is() -> None:
    """A list is the shape for a set to be READ; a grid is the shape for a set to be CHOSEN between.
    Features and Rules are grids; a feature page's rules and the unreached components are read, so
    they stay lists. (The Actors card grid retired with its view — actors are chosen from the story
    diagram's cast column now — and `elementCardGroupsHtml`'s grid option left with it.)"""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "function cardGridHtml(cards) {" in js and "function elementCardGridHtml(ids, per) {" in js
    # The grid class is typed ONCE. Five screens each wrote the div themselves before.
    assert js.count('class="ecard-grid"') == 1, "a hand-rolled card grid is back"
    assert "grid: true" not in js, "the grouped list is a LIST; its grid variant left with Actors"

def test_no_kind_quietly_joins_the_pill_repeats_the_drill_set() -> None:
    """`TYPE_PILL_REPEATS_DRILL` is a fact ABOUT two other functions: the kinds where the pill's
    destination and the card's destination are the same page. Nothing stopped a later edit to either
    switch from adding a fifth such kind while the Set stayed at four, and the symptom is silent — a
    pill that looks live and repeats a click the reader already made.

    So the Set is checked against the code it describes: every kind it names must resolve the same way
    in both switches, and the four `{ state: { kind:` lines it rests on must still be there."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    sel = js[js.index("function selectTargetFor(id) {"):
             js.index("\nfunction ", js.index("function selectTargetFor(id) {") + 10)]
    drill = js[js.index("function drillInto(id) {"):
               js.index("\nfunction ", js.index("function drillInto(id) {") + 10)]
    for kind, target in (("usecase", "{ kind: 'usecase', uc: id }"), ("block", "{ kind: 'rules', blk: id }"),
                         ("rule", "{ kind: 'rule', br: id }"),
                         ("process", "{ kind: 'deploymentUnit', unit: n.unit }")):
        assert f"case '{kind}':" in sel and target in sel, kind
        assert f"case '{kind}':" in drill and target in drill, kind


def test_the_audience_pill_prints_only_what_it_distinguishes() -> None:
    """`user` is 22 of the 27 features on the three reference maps, so the pill sat on eight cards in
    nine saying what the ninth already implied. It is the same argument the actor cards make for
    dropping their type pill and `human` for dropping its kind pill: a word that is nearly always
    there distinguishes nothing.

    The rule is about the SET, not the word. `user` survives BESIDE `staff`, because "both sides act
    here" is the one thing this pair exists to say, and a lone `staff` would read as "staff only"."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fn = js[js.index("function shownAudience(list) {"):
            js.index("\n}", js.index("function shownAudience(list) {"))]
    assert "list.length === 1 && list[0] === 'user'" in fn and "? [] : list" in fn
    # ONE surface draws it now: the card. A feature's page used to call this too, for a pill row of its
    # own; those pills ride the breadcrumb beside the name, read from cardFacts, so the page and the card
    # cannot print different sets.
    assert js.count("shownAudience(") == 3, \
        "one definition, two callers: cardFacts, and the story feature card"
    head = js[js.index("function featureHeadHtml(capId) {"):
              js.index("\n}", js.index("function featureHeadHtml(capId) {"))]
    head = "\n".join(l for l in head.splitlines() if not l.lstrip().startswith("//"))
    assert "pills: elementSidePillsHtml(capId)," in head, \
        ("…and it draws them from the ONE builder every element page uses, rather than deciding for "
         "itself. `of its own` is the guard that still matters: no hand-built pill list here")


def test_a_name_sits_beside_its_pill_wherever_the_box_is_drawn() -> None:
    """One box, one answer. `.ecard .ibox-name { flex-basis: 100% }` used to break the pills onto their
    own line under the name — on the card list, the card grid and the card that floats over a diagram,
    and nowhere else. It was written for a GRID, where cards are read across a row and a pill sitting a
    line lower on one of them reads as ragged, and then extended to "every card, everywhere".

    It never got there. The Interfaces picture's box and the card you get by clicking that same door on
    a walk are ONE box out of ONE builder, differing only in which variant is asked for — and the rule
    hung off the card's class alone. So the same door had its name beside its pill in one place and
    above it in the other, one click apart.

    What was left of the original argument is small: a card grid is a CSS grid, so every cell in a row
    is already the same height; only the pill's own y still varies."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert ".ecard .ibox-name { flex-basis: 100%; }" not in css, "the split is back"
    assert ".ecard-grid .ecard-name" not in css, "and it is not a grid rule either"
    # The pills still wrap AMONG THEMSELVES when there are many — that is the title row's own doing,
    # shared with every picture. Line-anchored: the card states its own baseline alignment above.
    at = css.index("\n.ibox-title {") + 1
    head = css[at: css.index("}", at)]
    assert "flex-wrap: wrap" in head

def test_the_other_axis_is_a_labelled_line_and_not_a_bare_pill() -> None:
    """A use-case card carries the OTHER axis: which feature it belongs to on an actor's page, who drives
    it on a feature's page. It rode the title line as a bare pill, and there `CONVERSATIONAL ASSISTANCE`
    sat beside `use case` in the same grey at the same size — measured, the two differed by 4% of
    background and nothing else. Nothing said one was what the card IS and the other a feature's name, and
    a reader meeting the map for the first time could not tell.

    The fix is the LABEL, and a label only fits below, so the fact earns a line of its own: `In feature`
    on an actor's page, `Driven by` on a feature's page. Which of the two appears also says which axis the
    screen is not already sorted by.

    In a GRID the line is pushed to the bottom of the card. Cards in a row are the same height but their
    sentences are not the same length, so the line landed at a different y in every card and the row read
    as ragged. Same rule as the name and the pills: in a grid you compare across, so a fact has to be
    findable in the same place on every card."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    ucs = js[js.index("function renderUseCases(sel) {"):
             js.index("\nfunction ", js.index("function renderUseCases(sel) {") + 10)]
    assert '<span class="ecard-lbl">Driven by</span>' in ucs
    assert "foot: cross" in ucs, "it is the card's FOOT line, under the sentence — not a title-line pill"
    # The `In feature` line has ONE builder, because it is drawn in two places: a grid, and the card
    # floating over a diagram. Two copies would eventually word it two ways.
    foot = js[js.index("function useCaseFeatureFootHtml(uc) {"):
              js.index("\n}", js.index("function useCaseFeatureFootHtml(uc) {"))]
    assert '<span class="ecard-lbl">In feature</span>' in foot
    assert js.count("useCaseFeatureFootHtml(") == 4, "one definition, three callers"
    card = js[js.index("function elementCardHtml(id, opts) {"):
              js.index("\n}", js.index("function elementCardHtml(id, opts) {"))]
    assert "foot: o.foot || ''," in card, "the card hands its labelled line to the one builder"
    # …which puts it after the sentence, once, for every box in the product.
    box = js[js.index("function itemBoxHtml(spec, variant, opts) {"):
             js.index("\nfunction ", js.index("function itemBoxHtml(spec, variant, opts) {") + 10)]
    assert box.index("if (o.foot) out.push(o.foot);") > box.index('class="ibox-what'), \
        "the labelled line comes after the sentence"
    grid = css[css.index(".ecard-grid .ecard {"):]
    grid = grid[: grid.index("\n\n")] if "\n\n" in grid else grid[:600]
    assert "margin-top: auto" in grid, "one height for the labelled line across a row"
    # …and the NAME on that line is a door: the feature's own list of use cases, or the actor's. It earns
    # the click by the rule every pill is held to — it goes where neither the card's own click nor the
    # page already open goes.
    # The FEATURE pill has a builder of its own, because two card foots name a feature: the use case's
    # here, and the Rules board's "also under". They were one copied string, and a pill worded two ways
    # is a pill that starts behaving two ways.
    #
    # It ACTS only where the feature is nowhere else on screen, which is the same rule every pill is
    # held to. Here it is the only way to the feature, so it is a door. On the Rules board that feature
    # has a card of its own a few lines away, so the pill there is plain and the board asks for it.
    pill = js[js.index("function itemPillHtml(id, opts) {"):
              js.index("\n}", js.index("function itemPillHtml(id, opts) {"))]
    assert 'data-item="' in pill and "o.plain" in pill, "one builder, a door and a plain form"
    assert "featurePillHtml(cap.id)" in foot, "the In feature line is the door form"
    board = js[js.index("function ruleAreaCardHtml(g, others) {"):
               js.index("\n}", js.index("function ruleAreaCardHtml(g, others) {"))]
    assert "featurePillHtml(f)" in board, "…and the Rules board's Also under is a door too"
    # BOTH FEET DRAW THE SAME PILL. The actor's is `itemPillHtml` too, so "who drives it" and "which
    # feature it is in" are one component wearing two different kinds' colours, not two components.
    assert "itemPillHtml(actorPage, {" in ucs
    binder = js[js.index("function bindElementCards(root, onDrill) {"):
                js.index("\n}", js.index("function bindElementCards(root, onDrill) {"))]
    assert "bindItemPills(root);" in binder, "bound where every card is bound, not per screen"
    assert "data-gofeat" in binder, "…and the section-head door stays bound here too"
    assert binder.count("ev.stopPropagation();") >= 2, "a click on the door is not the card's drill"
    # An ACTOR name is a door only when it names ONE actor. A use case driven by a pair reads "Team member
    # and Organization admin" and one the map never declared reads "Other"; neither is a page, and a pill
    # that looks live and goes nowhere teaches a reader to distrust the ones that work. `plain` is how
    # the shared pill says that, and it is the same word the Rules board uses for its own reason.
    assert "const actorPage = actorNodeId(actorText);" in ucs
    assert "plain: !actorPage" in ucs

def test_one_card_design_reaches_the_card_that_floats_over_a_diagram() -> None:
    """The spec asks for one card design in every place an element appears, and for a card's actions to be
    the same whether it sits in a list or beside a diagram. Two element kinds had quietly kept a second
    design of their own, built by hand in the info pane: a USE CASE and an ACTOR.

    Measured on the same use case, in a grid and in the overlay: 14px name against 16px, the type word
    grey-on-near-white against indigo-on-pale-indigo, a 13px sentence against 14px, and the other axis as
    a bare slate badge instead of a labelled line you could click. Six differences, and the overlay was
    the poorer of the two — it had neither the label nor the door.

    Both read `elementCardHtml` now. An actor's overlay is the card and nothing else: the `Drives` list it
    kept under the card restated, in words, the numbered steps the map beside it already lights up.

    The remaining hand-built panels are not elements and have no card to reuse: an arrow, a bridge, a flow
    step, and the Libraries / bucket folds."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    uc = js[js.index("function showUseCaseSummary(uc) {"):
            js.index("\n}", js.index("function showUseCaseSummary(uc) {"))]
    assert "elementCardHtml(uc," in uc and "pane-card" in uc, "the same card a grid draws"
    assert "bindElementCards(panel);" in uc, "…with the same actions"
    assert "badge kind" not in uc and "class=\"explain\"" not in uc, "the hand-built design is gone"
    ap = js[js.index("function actorPanelHtml(a) {"):
            js.index("\n}", js.index("function actorPanelHtml(a) {"))]
    assert "elementCardHtml(id, { bare: true })" in ap and "pane-card" in ap
    # `bare` is an OPTION on the box, never three declarations reaching in from its container.
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert ".ibox-bare { border-color: transparent; background: transparent; padding: 0; }" in css
    assert "#panel .pane-card .ecard {" not in css
    assert "Drives" not in ap and "driveRows" not in js, \
        "the steps it drives are on the map the card floats over, not listed again under it"
    # The pane must not resize the card either: one card, one size, wherever a reader meets it.
    assert "#panel .pane-card .ecard-name { font-size" not in css
    # The panels that stay hand-built are the ones with no card to reuse.
    for fn in ("showContextEdge", "flowStepInfoHtml", "showLibsFold", "showBucketFold"):
        assert f"function {fn}(" in js, fn
    # `showBridge` was on that list until the bridge page stopped drawing a card by itself. It printed
    # two subsystems' names and purposes, which the page's two framed boxes and the breadcrumb say.
    assert "function showBridge(" not in js

def test_a_page_about_one_thing_draws_no_section_for_that_thing() -> None:
    """A role's page used to open with a bordered block whose heading was the page's own title, with the
    use-case cards inside it: the name twice (breadcrumb, then heading) and a card containing cards.
    Both shapes were removed everywhere else in this viewer, and this page had kept them.

    What the role IS moves to the SHARED page hero — the same one a feature's page and a decision area's
    page use. Sections survive where they are a real cut: one per role on the flat catalog a map with no
    features falls back to.

    The cards are a GRID, wherever use cases are listed. Every one of them is a door to that use case's
    flow, which is what a grid is for, and it is the same job the actor, feature and decision-area cards
    do on the three screens the reader lands on. A list made the shape flip at the drill for no reason a
    reader could name, and it cost room: measured on Mio Coworker, a use-case card ran 1060px one per row
    while its sentence used 769-917px, so a quarter of every row stood empty and Workspace member's twenty
    cards ran 1674px of scroll. As a grid the same twenty run 1388px."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    ucs = js[js.index("function renderUseCases(sel) {"):
             js.index("\nfunction ", js.index("function renderUseCases(sel) {") + 10)]
    assert "const solo = one === '-';" in ucs
    assert "if (solo) return elementCardGridHtml(ids, per);" in ucs
    assert "elementCardListHtml(" not in ucs, "every use-case list on this screen is a grid"
    # …and the flat catalog still cuts by role, so the guard is not "always drop the section".
    assert "const kinds = new Set((g.roles || []).map" in ucs
    # An actor's page has its own renderer now (the journey line) with the SAME shared hero.
    head = js[js.index("function actorPageHeroHtml(actorName) {"):
              js.index("\nfunction ", js.index("function actorPageHeroHtml(actorName) {") + 10)]
    assert "pageHeroHtml({" in head, "one hero builder, shared with the feature and rule-area pages"
    # THE ONE PAGE THAT NAMES ITSELF IN ITS BODY, and it does it as a labelled ROW rather than as a
    # heading. Every other hero leaves the name to the breadcrumb, and on this page that was not
    # enough: the body is a timeline and a picture of surfaces, and nothing in it said whose page you
    # were on. See the trail test for the heading that stays banned.
    assert "name: actorName," in head and "pills: elementSidePillsHtml(actorNodeId(actorName))," in head
    # NO LEAD WORD IN THE HERO. An actor's goal does need a word saying it is a goal, and that word
    # belongs to the SENTENCE — it is drawn on six screens and only one of them is this hero, so
    # `wantsSentence` carries it and all six say the same thing.
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "descLbl" not in head and "wantsSentence(role.wants)" in head
    # The "Other" bucket is not a role: no kind, nothing it wants, and the hero says so.
    assert "g.roles.length === 1 ? g.roles[0] : null" in head
    # …and it hands the shared hero the actor's own figure, from the ONE actor-figure function, so the
    # hero, the board head and the cast card cannot draw three different people.
    assert "glyph: storyGlyphSvg(role && role.kind)," in head
    hero = js[js.index("function pageHeroHtml(o) {"):
              js.index("\nfunction ", js.index("function pageHeroHtml(o) {") + 10)]
    # THE FIGURE IS OPTIONAL, and for a harder reason than taste: only two element kinds own a drawing
    # of themselves. An actor is a person or a hexagon and a feature is a sparkle; a decision area, a
    # surface and a Deployment arrow have none, and no colour stands in for it either — the map gives
    # a feature and a decision area no tint. So the row is built to read without one.
    assert '<div class="page-hero-glyph">${o.glyph}</div>' in hero, "the figure, as a column of the card"
    assert "page-hero-callout" not in js and "page-hero-callout" not in css, \
        "no box: it sat directly above a board that opens with the same figure and the same name"


def test_every_card_says_what_it_is_and_only_the_dead_click_goes() -> None:
    """The type pill names what an element IS and, clicked, shows it in its home view. It used to be
    DROPPED on that home view, which left the feature cards as the one card shape in the viewer with
    no identity line, on the very screen a reader meets first.

    Both jobs are separable. The WORD is the card's identity and belongs on every card in a list that
    MIXES kinds: without it a card reads as a different kind of object than the cards beside it. The
    ACTION is a control only where it goes somewhere the CARD does not, and it fails that two ways:
    structurally, for four kinds whose pill and whose drill open the same page (a decision area's card
    was found carrying one), and positionally, when the card already sits on the page the pill travels
    to. Both render the word as plain text: no hover, no pointer, no keyboard stop.

    ONE LIST DROPS THE WORD ALTOGETHER, and it is the case the rule above does not cover: the Rules
    board, where every card is a decision area, each wears the area's own mark, and the page says so
    in its first line. There `DECISION AREA` on all of them is the heading printed once per card, and
    `noType` is what the caller says to drop it. Pinned to ONE caller, because the argument for it is
    "every card here is the same kind" and a second list claiming that is a design question, not an
    edit."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    card = js[js.index("function elementCardHtml(id, opts) {"):
              js.index("\nfunction ", js.index("function elementCardHtml(id, opts) {") + 10)]
    assert "const typeHtml = o.noType ? '' : (o.homeType || TYPE_PILL_REPEATS_DRILL.has(c.kind))" in card
    assert "wordHtml: typeHtml," in card, "the card's own pill replaces the box's default word"
    # The four are exactly the kinds whose `selectTargetFor` and `drillInto` answer the same page.
    assert "const TYPE_PILL_REPEATS_DRILL = new Set(['usecase', 'block', 'rule', 'process']);" in js
    assert 'class="ecard-type ecard-type-plain"' in card, "same word, same slot"
    assert "<span" in card.split("o.homeType")[1].split(":")[0], "plain text, not a button"
    assert 'data-ctx="${esc(id)}"' in card, "…and everywhere else it still acts"
    for caller in ("function renderOverview() {",):
        body = js[js.index(caller): js.index("\nfunction ", js.index(caller) + 10)]
        assert "return { homeType: true," in body, caller
    ucs = js[js.index("function renderUseCases(sel) {"):
             js.index("\nfunction ", js.index("function renderUseCases(sel) {") + 10)]
    assert "return { homeType: !page, extra:" in ucs
    # ONE SWITCH, and every caller of it is a list whose cards are all one kind with the page saying
    # which: the Rules board (every card a decision area) and one area's own page (every card a rule,
    # in a section called Rules). A third list claiming it is a design question, not an edit.
    # TWO askers, named in the comment above, since the feature page's own rule list went: it draws
    # the Rules board's area cards now, through the board's own builder, so it adds no third ask.
    assert js.count("o.noType") == 1 and js.count("noType: true") == 2, \
        "the switch has one definition and only same-kind lists may ask for it"
    assert "noType: true" in js[js.index("function ruleAreaCardHtml(g, others) {"):
                                js.index("\n}", js.index("function ruleAreaCardHtml(g, others) {"))]
    area = js[js.index("function renderRules(s) {"):
              js.index("\nfunction ", js.index("function renderRules(s) {") + 10)]
    assert "noType: true, foot: ruleWhyFootHtml(id)" in area, \
        "the area page's rule cards drop the word and carry the reason"
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert ".ecard-type-plain { cursor: default; }" in css


def test_the_coverage_line_reports_reach_and_never_certainty() -> None:
    """"How much of the code does a feature explain" and "how sure is this map" are different
    questions, and only the first is answered here. The second is invisible today: `confidence` and
    `evidence` sit on elements that no view renders, and 381 elements across four live maps say
    `verified` with no skeptic having opened them. One sentence holding both would let a map read as
    well-grounded because its features have wide reach."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    start = js.index("function coverageLineHtml() {")
    line = js[start: js.index("\n}", start)]
    body = "\n".join(ln for ln in line.splitlines() if not ln.strip().startswith("//"))
    assert "reaches" in body
    for word in ("confidence", "verified", "evidence", "sure", "certain"):
        assert word not in body.lower(), word
    assert "componentsUnreached" in line
    # It is a fact about coyomap's own analysis, so it lives on the System tab under "About this map",
    # never on a product view. The reader looking at what the product does did not ask for it.
    assert "sec('map', 'Functional coverage', unreachedHtml()," in js
    assert "coverageLineHtml()" not in js[js.index("function renderOverview() {"):
                                          js.index("\nfunction ", js.index("function renderOverview() {") + 10)]


def test_the_unreached_drill_separates_the_finding_from_the_expected() -> None:
    """The components no feature and no rule reaches are not one pile. Measured on one live map's 13:
    build and deploy tooling took 8, interface contracts 1, shared screen parts 0, and 4 were left
    over. Only the LAST group is a finding, and it is labelled "not classified" rather than "a
    problem" — the map may be incomplete or the code may be dead, and this screen cannot tell which."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    table = js[js.index("const UNREACHED_GROUPS = ["): js.index("\n];", js.index("const UNREACHED_GROUPS = ["))]
    assert [k for k in re.findall(r"\['([a-z]+)',", table)] == ["contracts", "screen", "tooling", "other"]
    assert "'Not classified'" in table
    for bad in ("problem", "dead code", "unused", "wrong"):
        assert bad not in table.lower(), bad


def test_an_unreached_component_is_classified_by_its_whole_path() -> None:
    """One path can match two groups, so the order they are TESTED in is a decision of its own. A live
    map has a bundled demo server whose own folder holds five `widgets/` files beside three others: by
    weight of files alone it read as the product's shared screen parts, when everything under `dev/`
    is scaffolding. The enclosing tree wins over the leaf folder. Below half the files agreeing,
    nothing is claimed at all — the component lands in "not classified" instead of being filed under
    whichever path happened to come first."""
    probe = """
const cases = {
  demo: ['backend/src/x/dev/demo_server.py', 'backend/src/x/dev/README.md',
         'backend/src/x/dev/widgets/a.js', 'backend/src/x/dev/widgets/b.js',
         'backend/src/x/dev/widgets/c.js'],
  widgets: ['frontend/src/components/ui/button.tsx', 'frontend/src/components/ui/dialog.tsx'],
  ports: ['backend/src/x/domain/ports/__init__.py', 'backend/src/x/domain/ports/account.py'],
  shell: ['start.sh', 'stop.sh'],
  compose: ['docker-compose.yml', 'docker/nginx.conf'],
  product: ['tools/coyomap/grammar.py', 'tools/coyomap/anchors.py'],
  split: ['scripts/a.py', 'backend/src/x/service.py', 'backend/src/y/other.py'],
};
const GRAPH = { nodes: {} };
const out = {};
for (const k in cases) { GRAPH.nodes[k] = { files: cases[k] }; out[k] = unreachedClassOf(k); }
console.log(JSON.stringify(out));
"""
    got = json.loads(_run_js_region("const UNREACHED_GROUPS = [",
                                    "// The code no feature and no rule reaches", probe))
    assert got == {"demo": "tooling", "widgets": "screen", "ports": "contracts", "shell": "tooling",
                   "compose": "tooling", "product": "other", "split": "other"}, got


def test_a_map_lands_on_what_the_product_does() -> None:
    """The map should read as WHAT THE PRODUCT DOES first, with code as the evidence you drill into. So
    a reader arriving from the root page lands on the Overview, the product description (2026-09-12),
    then Features, which lists everything the product does. Each fallback is the next thing down the
    product row, and only then the machine.

    The description had a tab of its own for one round. A tab is the wrong home for three sentences: the
    reader visits it once and never returns. As the lead of the landing page it cannot be missed and
    costs nothing to scroll past."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    # The boot call now reads the URL first and falls back to LANDING, so the end marker is the fallback
    # itself, searched from the table — `{ kind: LANDING }` also appears in the URL-adopt path above.
    start = js.index("const LANDING =")
    landing = js[start: js.index("{ kind: LANDING });", start)]
    assert landing.index("HAS_OVERVIEW ? 'overview'") < landing.index("HAS_USECASES ? 'usecases'"), \
        "the description is the first thing a reader meets"
    assert "HAS_HP ? 'hp'" in landing
    assert "'actors'" not in landing, "the Actors view left the fallback chain with its tab"
    assert "HAS_DIFF" not in js, "the baked report path is gone: change mode is armed by the reader, not by a file"
    assert "'goal'" not in js and "renderGoal" not in js, "the Goal tab is gone, not hidden"
    # …and the description leads the Features page, above a labelled block of feature cards.
    over = js[js.index("function renderOverview() {"): js.index("\nfunction ", js.index("function renderOverview() {") + 10)]
    # THE DESCRIPTION HAS A TAB OF ITS OWN NOW, Overview, first under Product; the Features landing
    # leads with its diagram.
    assert "productLeadHtml" not in over, "the description left the Features landing"
    tab = js[js.index("function renderOverviewTab() {"): js.index("\n}", js.index("function renderOverviewTab() {"))]
    assert "productLeadHtml([])" in tab and "overviewDigestHtml" not in js, "the tab is the description alone"
    html = (VIEWER_DIR / "viewer.html").read_text()
    assert html.index('data-view="overview" data-group="product"') < html.index('data-view="usecases" data-group="product"'), \
        "first tab under Product"
    assert "if (b.dataset.view === 'overview' && !HAS_OVERVIEW)" in js, "hidden on a map with no description"
    assert "'<p class=\"block-lbl\">Product features</p>' + grid" in over
    assert "GRAPH.nodes.SYS" in js[js.index("function productLeadHtml(secs) {"):]


def test_code_and_operations_read_as_one_question() -> None:
    """Five group tabs, three of which answered the same second question — how is this thing built and
    run. Product and Data are what the thing IS; everything else is the machine, so Code and Operations
    are one group. Membership rides each button's `data-group`, so the merge is one attribute per
    button and there is no second list to keep in step."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    table = js[js.index("const VIEW_GROUPS = ["): js.index("\n];", js.index("const VIEW_GROUPS = ["))]
    # Product and Under the hood, then TIME: the Change log is one timeline of the map's versions,
    # neither a product view nor a machine view, so it is a group of its own (2026-09-18).
    assert [g for g in re.findall(r"\['([a-z]+)', '", table)] == ["product", "hood", "changelog"], \
        "three groups: Data and Glossary sit under Product now, Storage under the hood, the updates under Change log"
    assert "'Under the hood'" in table and "'Change log'" in table
    hood = re.findall(r'<button data-view="(\w+)" data-group="hood">', html)
    # Storage is a machine fact — where the data physically lives — so it sits under the hood too.
    assert set(hood) == {"container", "data", "context", "tests", "deployment", "system"}, hood
    assert re.findall(r'<button data-view="(\w+)" data-group="changelog">', html) == ["updates"]


def test_a_component_says_how_many_features_it_serves() -> None:
    """On the code views a component serving four features looked exactly like one serving none. The
    count comes from `componentFeatures` — the Python join — and is never re-counted from the grouped
    list beside it, which is the same join written twice over. Each feature heading is now the way back
    out of the code and into what the product does."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    cnt = js[js.index("function featureCountHtml(id) {"):
             js.index("\nfunction ", js.index("function featureCountHtml(id) {") + 10)]
    assert "COMP_FEATURES[id]" in cnt and "Serves " in cnt
    used = js[js.index("function usedInHtml(id) {"):
              js.index("\nfunction ", js.index("function usedInHtml(id) {") + 10)]
    assert "featureCountHtml(id)" in used
    # THE FEATURE IS A CARD, holding its own use cases as pills. It was a pill with the use cases in a
    # row beside it, and the two read as one flat run of tags that happened to wear different marks —
    # nothing on screen said the second lot belonged to the first. The card is still a door to the
    # feature's page, which the pill was.
    assert "elementCardHtml(g.cap.id, {" in used, "a feature heading is the shared card"
    assert "<span class=\"ecard-lbl\">Use cases</span>" in used
    assert "selectFromTree(b.getAttribute('data-id'))" in js[js.index("function bindNodeDetailHandlers(root) {"):]


def test_the_path_starts_at_the_view_and_never_at_a_level_inside_it() -> None:
    """The trail always begins with the view. It briefly dropped that first item as an echo of the lit
    tab, and the cost showed one level in: a page began mid-path, and the only way back to the view's
    own landing screen was the tab — which reads as leaving the trail rather than going up it. The
    GROUP is still never here ("Product" is a set of tabs, not a page you can be on).

    The last item is the page's own name, rendered as the document's h1, so NO page draws a heading of
    its own — the duplication every earlier arrangement kept reintroducing somewhere else."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    crumbs = js[js.index("  crumb.innerHTML = '';"):]
    crumbs = crumbs[: crumbs.index("\n}")]
    # NO TRAIL ROW. The path is the HEAD's first line (pagePathHtml, placed by syncPageHero): every
    # ancestor from the view down to the parent, each a link, then a closing › — the page itself is the
    # head's name line. The row stays in the document, collapsed, holding the page's name as the h1 a
    # screen reader hears. A row of its own repeated the name 36px above the head, and a row showing
    # only the middle of the path came and went between screens.
    assert "classList.add('hint-empty')" in crumbs and "h.className = 'crumbseg cur sr-only';" in crumbs
    assert "crumbsep" not in crumbs and "createElement('button')" not in crumbs, "the row draws no path"
    path = js[js.index("function pagePathHtml(chain) {"): js.index("\n}", js.index("function pagePathHtml(chain) {"))]
    assert "const parents = (chain || []).slice(0, -1);" in path, "parents only: the page is the name line"
    assert "if (!parents.length) return '';" in path, "a landing has no parents and draws no line"
    place = js[js.index("function placePagePath(chain) {"): js.index("\n}", js.index("function placePagePath(chain) {"))]
    assert "#diaghead .page-hero, #pagehero .page-hero, #diagram .page-hero" in place, "whichever head the page drew"
    assert "hero.insertAdjacentHTML('beforebegin', html);" in place, "…on the page ground just above it"
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert ".hint.hint-empty { padding: 0; border-bottom: 0; }" in css and ".sr-only {" in css
    # No page draws its own name.
    head = js[js.index("function viewHeadHtml(_title, desc) {"):
              js.index("\nfunction ", js.index("function viewHeadHtml(_title, desc) {") + 10)]
    assert "view-title" not in head and "_title" in head
    hero = js[js.index("function pageHeroHtml(o) {"):
              js.index("\nfunction ", js.index("function pageHeroHtml(o) {") + 10)]
    assert "view-title" not in js
    # THE HERO NAMES ITS OWN SUBJECT, and that is not the banned heading coming back. The ban is on a
    # page drawing a SECOND h1 under the breadcrumb's; this is a card's shape — the name, then what
    # kind of thing it is — set at 16px in the body of the page, where the breadcrumb reads as the
    # app's chrome and left the body saying nothing about what you were looking at.
    #
    # It stays OPTIONAL, and its absence still costs nothing: a page with no name to give (a
    # Deployment arrow, an entry-point kind, the info pane's subject) keeps its pills on a row of
    # their own, exactly as before.
    assert 'o.name\n    ? `<p class="page-hero-name">' in hero
    assert ": (o.pills ? `<p class=\"page-hero-pills\">${o.pills}</p>` : '');" in hero
    assert ".page-hero-subject { font-size: 16px;" in css, "a name in the body, not a second title"
    assert "<h1" not in hero and "<h2" not in hero
    for fn in ("renderRule", "renderElementDetails"):
        body = js[js.index(f"function {fn}("): js.index("\nfunction ", js.index(f"function {fn}(") + 10)]
        assert "ruleTitle(r)}</h3>" not in body and "view-title" not in body, fn
    # One heading per page: the app's own name is a brand mark.
    html = (VIEWER_DIR / "viewer.html").read_text()
    import re as _re
    assert not _re.search(r"<h1[ >]", html), "the only h1 is built at runtime, in the breadcrumb"
    assert 'class="brand"' in html

def test_the_title_bar_holds_every_utility_and_wraps_before_it_clips() -> None:
    """Two controls, both of them things you do to the WHOLE map rather than places you go: search and
    settings. Search used to sit in the group row, which made that row two things at once. They are
    quiet icon buttons on the navy ground — filled chips would read as destinations.

    THREE THINGS LEFT THIS BAR, all for one reason: the title bar is chrome the whole app shares, so
    what sits in it must work on every screen. A "?" opened a first-run overlay of the map's gestures —
    both gone, the overlay because it interrupted the first screen a reader ever saw. The zoom control
    went to the drawing it acts on: it did nothing on 9 of the 13 view tabs.

    Back and Forward are NOT here either. The bar carried its own ◀ ▶ pair from before the URL named the
    screen; the browser's own buttons do that walk now, and a second pair could only disagree with them.

    At a narrow column the bar wraps into two lines, identity then controls, rather than squeezing."""
    html = (VIEWER_DIR / "viewer.html").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    head = html[html.index("<header>"): html.index("</header>")]
    for control in ("searchbtn", "setbtn"):
        assert f'id="{control}"' in head, control
    for gone in ("zoomctl", "zoomin", "zoomout", "zoomlevel", "helpbtn"):
        assert gone not in head, gone
    for gone in ("helpbtn", "coachok", "coach-list"):
        assert gone not in html and gone not in css, gone
    assert "stageheadutil" not in html and "stageheadutil" not in css
    btn = css[css.index("header button {"): css.index("}", css.index("header button {"))]
    assert "width: 26px" in btn and "height: 26px" in btn and "background: transparent" in btn
    assert "background: rgba(255,255,255,.12)" in css
    assert "@media (max-width: 480px)" in css and "header .brand { flex: 1 0 100%; }" in css

def test_a_page_never_repeats_the_tab_it_was_opened_from() -> None:
    """Six pages printed a title identical to the tab you had just clicked, one line below it. The tab
    is where the page is named; the page does not name it again. A title that says something ELSE —
    an actor, a System collection, "Use cases" on a map recording no features — is information, not an
    echo, and stays. One rule, in the one function every page head goes through."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    head = js[js.index("function viewHeadHtml(_title, desc) {"):
              js.index("\nfunction ", js.index("function viewHeadHtml(_title, desc) {") + 10)]
    # A head with no description of its own is not drawn at all: the page's name is the breadcrumb's
    # last item, and there is nothing else for a head to say.
    assert "return desc ?" in head


def test_the_question_reads_as_a_sentence_and_not_as_a_control() -> None:
    """Set upright at the tabs' own size, right after them, the question read as a fifth disabled tab —
    and the ambiguity is what made it invisible, not the contrast. Italic fixes what it IS before fixing
    how loud it is: nothing else in this app is italic, so one glance says sentence, not control.

    Everything that framed it is gone with the places it used to sit. The dividing rule after the last
    tab went when it left the tab row. The em dash went when it left the page title's line: a dash joins
    two things on one line, and alone at the start of a line it is a stray tick. It has no rule, no
    background and no border either — anything that boxes a sentence turns it back into a bar."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "has-after" not in js and "has-after" not in css, "the tab-row rule is gone, not shadowed"
    # The sentence is the landing card's now, set in the hero's own sentence style: upright, dark,
    # inside the card and beneath the name, exactly as an item page's sentence is. Nothing joins it to
    # a title on its line, and the card is the only thing around it.
    assert "#pageq" not in css and "pageq" not in js
    landing = js[js.index("function landingHeadHtml(view) {"): js.index("\n}", js.index("function landingHeadHtml(view) {"))]
    assert "itemSectionHeadHtml(name, n, q)" in landing, "the stored string is the pure question"
    note = css[css.index(".item-sec-note {"): css.index("}", css.index(".item-sec-note {"))]
    assert "italic" not in note and "\\2014" not in note

def test_the_app_name_is_a_working_way_back_to_all_maps() -> None:
    """It was an <h1> with a click handler, and became a plain span when the page's one heading moved to
    the breadcrumb — which silently took the link with it. A span with a click handler is not a control:
    no keyboard tab stop, no Enter, nothing announced. So it carries a link role, a tab stop and its own
    key handling, and a home icon says what it does before you hover it."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert 'class="brand-home"' in html and 'aria-hidden="true"' in html
    block = js[js.index("const brand = document.querySelector('header .brand');"):]
    block = block[: block.index("\n  }") + 4]
    assert "brand.setAttribute('role', 'link');" in block
    assert "brand.setAttribute('tabindex', '0');" in block
    assert "e.key === 'Enter' || e.key === ' '" in block
    assert "brand.addEventListener('click', home);" in block
    assert "header .brand.home-link { cursor: pointer; }" in css


def test_an_arrow_from_a_box_to_itself_is_one_arrow_made_of_three_pieces() -> None:
    """A flow step where one box acts on itself draws a loop. Mermaid does not draw that loop as one
    line: it routes it through two invisible helper boxes and emits THREE paths, named
    `<diagram>-<box>-cyclic-special-1 | -mid | -2` — none of which spells `L_<src>_<dst>_<i>`. The
    viewer read only that one spelling, so the loop was painted and then never picked up: no hover, no
    click, no highlight, and the step player froze on the step it carried.

    The reader now reports the loop ONCE (on `-mid`, the piece Mermaid keeps the label on) as an arrow
    whose two ends are the same box, and hands over all three pieces so everything that paints or
    hit-tests an arrow covers the whole loop. The two arrows after it pin the other half of the bug
    class: Mermaid emits one label per PATH — two of them empty — so the index pairing that gives every
    LATER arrow its label must count all three pieces, not one."""
    out = _run_js_region(
        "function eachEdge(root, fn) {",
        "// Stroke an edge's path + glow its label",
        """
const mk = (id) => ({ id, style: {} });
const paths = ['g-C50-cyclic-special-1', 'g-C50-cyclic-special-mid', 'g-C50-cyclic-special-2',
               'g-L_C50_E55_0', 'g-L_U_0_U_15_0'].map(mk);
const labels = ['', '6', '', '7', '8'].map((text) => ({ text }));
const root = { querySelectorAll: (sel) => (sel.includes('edgePaths') ? paths : labels) };
const seen = [];
eachEdge(root, (p, label, m) => seen.push(
  { label: label && label.text, src: m[1], dst: m[2], i: m[3], segs: (p._segs || [p]).map((s) => s.id) }));
console.log(JSON.stringify(seen));
""",
    )
    seen = json.loads(out)
    assert [(s["src"], s["dst"]) for s in seen] == [("C50", "C50"), ("C50", "E55"), ("U_0", "U_15")]
    loop = seen[0]
    assert loop["label"] == "6" and loop["i"] == "0"
    assert loop["segs"] == ["g-C50-cyclic-special-1", "g-C50-cyclic-special-mid",
                            "g-C50-cyclic-special-2"], "all three pieces travel with the arrow"
    # The arrows drawn AFTER the loop still get their own labels — the pairing counted three, not one.
    assert [s["label"] for s in seen[1:]] == ["7", "8"]
    # An ordinary arrow is still one piece, so nothing else pays for the loop.
    assert seen[1]["segs"] == ["g-L_C50_E55_0"]


def test_a_step_the_diagram_cannot_draw_never_traps_the_walk() -> None:
    """Pressing Next used to sit on one step for ever. A step whose arrow this rendering did not draw
    has no selector, so the player resets the diagram — and the reset also SUSPENDS the player. A
    suspended player answers the next press by re-entering the SAME index, so the counter stopped
    dead and every further press repeated the same nothing.

    The step keeps its number and shows nothing, but the walk goes on. Run against the real
    flowGoto/flowStepBy with the middle step of three left undrawn: the counter must reach the last
    step and wrap, not stick at the undrawn one."""
    out = _run_js_region(
        "function flowGoto(i) {",
        "// Called from render() once svg-pan-zoom exists.",
        """
let flowPlay = { uc: 'UC1', steps: [{}, {}, {}], msgEls: [[], [], []], cur: -1, active: false };
// Selecting a drawn step ends in flowSyncCur, which is what re-activates the player after the
// selClear inside flowGoto. Step 2 of 3 (index 1) has NO selector: undrawn in this rendering.
const flowSyncCur = () => { flowPlay.active = true; };
const mainScene = { selectors: { 'flowstep:UC1:0': flowSyncCur, 'flowstep:UC1:2': flowSyncCur } };
function flowSuspend() { flowPlay.active = false; }
function selClear() { flowSuspend(); }
function resetScene() { selClear(); }
function flowReveal() {}
function flowCounter() {}
const walked = [];
for (let k = 0; k < 6; k++) { flowStepBy(1); walked.push(flowPlay.cur); }
console.log(JSON.stringify(walked));
""",
    )
    assert json.loads(out) == [0, 1, 2, 0, 1, 2], "the walk must pass the undrawn step, not sit on it"


def test_the_domain_view_reads_a_self_arrow_through_the_same_one_reader() -> None:
    """The same bug, one view over: an entity related to ITSELF (a parent/child link) is drawn by the
    class diagram as the same three pieces, under the same id spelling — which matches neither the
    flowchart's `L_<src>_<dst>_<i>` nor the class diagram's own `id_<src>_<dst>_<i>`. Found by sweeping
    for the bug class after fixing the flow map, and confirmed against a real Mermaid 11 render.

    So both views read the loop through ONE function. This runs the Domain view's real edge reader over
    a class diagram holding a self relation and two ordinary ones: the loop must come back once, as a
    relation whose two ends are the same entity, and the relations after it must keep their own
    labels."""
    out = _run_js_regions(
        [("function selfArrowParts(paths) {", "// An arrow's screen box:"),
         ("function eachClassEdge(root, fn) {", "// Mermaid's classDiagram markers default")],
        """
const mk = (id) => ({ id });
const paths = ['d-E1-cyclic-special-1', 'd-E1-cyclic-special-mid', 'd-E1-cyclic-special-2',
               'd-id_E1_E2_2', 'd-id_E2_E1_3'].map(mk);
const labels = ['', 'parent', '', 'holds', 'lives in'].map((text) => ({ text }));
const root = { querySelectorAll: (sel) => (sel.includes('relation') ? paths : labels) };
const seen = [];
eachClassEdge(root, (p, label, src, dst) => seen.push(
  { label: label && label.text, src, dst, segs: (p._segs || [p]).map((s) => s.id) }));
console.log(JSON.stringify(seen));
""",
    )
    seen = json.loads(out)
    assert [(s["src"], s["dst"]) for s in seen] == [("E1", "E1"), ("E1", "E2"), ("E2", "E1")]
    assert seen[0]["label"] == "parent"
    assert seen[0]["segs"] == ["d-E1-cyclic-special-1", "d-E1-cyclic-special-mid",
                               "d-E1-cyclic-special-2"]
    assert [s["label"] for s in seen[1:]] == ["holds", "lives in"]


def test_a_code_link_has_exactly_one_shape_and_one_builder() -> None:
    """A code link is a pill: the file's NAME plus its line, as one clickable button. The flow step
    card was the single exception in the product. It hand-rolled its own `<a>` and printed the whole
    path, so the most-read card in the viewer was the one place a code link looked unlike every other.

    Two gates, so the exception cannot come back by a different route. First, the step card goes
    through the shared builder and never prints its raw anchor again. Second, `srcCell` stays the ONLY
    place that emits a source-link button, which is also what makes the one delegated pane listener
    enough to serve every link in the app."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    # THE STEP'S CARD CARRIES NO CALL SITE any more — the card is a glance at what the step does, and
    # a `SOURCE path:line` row was the only line on it a reader could not read as a sentence. The
    # anchor is on the step's own PAGE, which the card's title opens, and there it goes through the
    # shared builder like every other code link.
    step = js[js.index("function flowStepInfoHtml(uc, i) {"):
              js.index("\nfunction ", js.index("function flowStepInfoHtml(uc, i) {") + 10)]
    assert "srcCell(" not in step, "the card's call-site row is back"
    assert "srcCell(where)" in js[js.index("function heroSourceLine(where) {"):][:400], \
        "a hero's code line is the shared pill"
    assert "esc(st.where)" not in step, "the step card never prints its raw anchor"
    # The hand-rolled link and its per-render click handler are gone, markup and stylesheet alike.
    css = (VIEWER_DIR / "viewer.css").read_text(encoding="utf-8")
    assert "stepwhere" not in js and "stepwhere" not in css
    # ONE builder emits a source-link button. A second one would also escape the delegated listener's
    # contract, which is what silently broke a row of manifest anchors once before.
    assert js.count('class="src srclink"') == 1
    emitter = js[js.index("function srcCell(where) {"):
                 js.index("\nfunction ", js.index("function srcCell(where) {") + 10)]
    assert 'class="src srclink"' in emitter, "that one emitter is srcCell"


def test_the_source_pill_names_the_file_not_the_path() -> None:
    """What the pill actually says, run against the real builder: the file's own name and its line,
    never the folders above it. Pinned because the whole point of the shared shape is that a reader
    recognises a code link by its shape, and a full path reads as prose."""
    out = _run_js_region(
        "function srcCell(where) {",
        "function srcListCell(joined) {",
        """
function whereNode(w) { const m = String(w).match(/^(.*?):(\\d+)$/); return m ? { file: m[1], line: +m[2] } : { file: String(w), line: null }; }
function localRef(w) { return !String(w).startsWith('http'); }
function cleanPath(file) { return file; }
const esc = (s) => String(s);
console.log(JSON.stringify([
  srcCell('backend/src/mcpolis/adapters/event_stream_redis.py:47'),
  srcCell('README.md'),
]));
""",
    )
    pill, noline = json.loads(out)
    shown = re.search(r">([^<>]*)</button>", pill)
    assert shown and shown.group(1) == "event_stream_redis.py:47", pill
    assert "/" not in shown.group(1), "no folder reaches the words on screen"
    # The whole anchor is still carried, on the attribute the delegated listener reads.
    assert 'data-where="backend/src/mcpolis/adapters/event_stream_redis.py:47"' in pill
    assert 'class="src srclink"' in pill
    shown2 = re.search(r">([^<>]*)</button>", noline)
    assert shown2 and shown2.group(1) == "README.md", "an anchor with no line still reads as a name"


def test_an_entry_point_row_says_what_it_is_and_where_it_lives() -> None:
    """A component's entry points render in TWO places: the info pane, and the component's own details
    page. Every rule that gave the rows their shape named `#panel`, so the PAGE got none of them. The
    kind chip lost its box and ran into the trigger — one live map printed `http-routeDELETE
    /api/admin/gateway/users/{email}` — the rows lost the pointer that says they can be clicked, and a
    selected row lit up nothing.

    The rows also carried no call site at all, on the reasoning that selecting one reveals the source.
    Nothing on screen said so, and the very same fact is already a pill in the Deployment card's
    "Threads / loops" table. On one map that is 188 entry points, all 188 holding an anchor and none
    showing it. Each row now carries the shared pill, and selecting the row still works.

    THREE COLUMNS, one per question every row answers: which kind of way in, what starts it, where the
    code is. As spans on one line the three never lined up — a long trigger sentence pushed its code
    link to the right edge while the next row's sat mid-line — so only the kind word could be scanned
    down the list. `Kind of way in`, never a bare `Kind`: four different things in this viewer carry a
    kind and the vocabularies do not overlap."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    js = (VIEWER_DIR / "viewer.js").read_text()
    for rule in (".tb-list {", ".tb-ep {", ".tb-ep:hover td {", ".tb-ep.sel td {", ".tb-kind {"):
        assert rule in css, f"{rule} must exist unscoped, so the page gets it too"
        assert "#panel " + rule not in css, f"{rule} may not be scoped to the info pane"
    assert "<th>Kind of way in</th><th>What starts it</th><th>Code</th>" in js
    assert ".tb-c-kind, .tb-c-src { white-space: nowrap;" in css, "only the trigger column wraps"
    # The crossings page hand-copied one of those rules; one rule, one home.
    assert ".xlist-page .tb-kind" not in css
    tb = js[js.index("function triggeredByHtml(id) {"):
            js.index("\nfunction ", js.index("function triggeredByHtml(id) {") + 10)]
    assert "srcCell(e.source)" in tb, "the row's call site is the shared pill"
    assert "data-where=" in tb, "…and the row itself stays selectable, as it was"


def test_a_field_that_is_nothing_but_a_code_anchor_becomes_a_code_link() -> None:
    """The `Entry point` field held `backend/src/.../roles.py:63` and printed it as prose — the last
    place in the viewer where a link to code did not look like one. A field whose WHOLE value is an
    anchor is now the shared pill.

    The test that matters is what it REFUSES. The rule reads a field value with no idea what the field
    means, so it must never turn a version number or a pair of words into a link to a file that does not
    exist. It fires only on one token that ends in `:<line>` after a file extension, or ends in `/`."""
    out = _run_js_region(
        "function bareAnchor(v) {",
        "// A node's full detail as an HTML string",
        """
const localRef = (f) => !!f && !/^[a-z][a-z0-9+.-]*:\\/\\//i.test(String(f));
const cases = ['backend/src/mcpolis/entrypoints/routes/dashboard/roles.py:63', 'roles.py:63',
               'roles.py:63-70', 'roles.py#L63',
               'backend/src/mcpolis/adapters/', '1.2.3', 'read/write', 'app.py', 'v2.0',
               'https://example.com/a.py:1', 'see roles.py:63 for the detail', '', null];
console.log(JSON.stringify(cases.map((c) => [c, bareAnchor(c)])));
""",
    )
    got = dict((k or "", v) for k, v in json.loads(out))
    # Fires on a real anchor, with or without folders, and on a directory ref.
    assert got["backend/src/mcpolis/entrypoints/routes/dashboard/roles.py:63"]
    assert got["roles.py:63"] == "roles.py:63"
    assert got["backend/src/mcpolis/adapters/"]
    # Every line-marker spelling the rest of the viewer reads (whereNode), so one anchor cannot be a
    # pill in a Source cell and prose in a field.
    assert got["roles.py:63-70"] == "roles.py:63-70"
    assert got["roles.py#L63"] == "roles.py#L63"
    # …and on nothing else.
    for never in ("1.2.3", "read/write", "app.py", "v2.0", "https://example.com/a.py:1",
                  "see roles.py:63 for the detail", ""):
        assert got[never] == "", f"{never!r} is not a code link"


def test_a_self_arrow_is_framed_as_the_whole_loop_and_not_as_one_third_of_it() -> None:
    """Jumping straight to one step of a flow — a rule's "enforced at" chip does this — selects the
    step's arrow AND moves the camera onto it, or the arrow is a thin line lost somewhere in a big map.

    A self-arrow is three paths, and the step's element list carries all three so the reveal pan can see
    the whole loop. Framing must take the piece that carries the other two (`_segs`), whose measured box
    is the union of the three. Taking the first drawn piece instead measured a third of the loop and
    zoomed to 1214%: the window filled with one blue band and the deep link arrived on a picture of
    nothing. 12 steps in one live map are reachable by such a chip.

    Runs the real frameFlowStep over a step whose three pieces are listed in drawing order, so the
    representative is NOT first."""
    out = _run_js_region(
        "function frameFlowStep(i) {",
        "// Every taggable item in the shown file",
        """
const box = (w, h) => ({ getBoundingClientRect: () => ({ width: w, height: h }) });
const seg1 = { name: 'seg1', ...box(112, 37) };
const mid  = { name: 'mid',  ...box(112, 37) };
const seg2 = { name: 'seg2', ...box(112, 37) };
mid._segs = [seg1, mid, seg2];              // only the representative carries the loop's other pieces
const label = { name: 'label', ...box(20, 12) };
const plain = { name: 'plain', ...box(181, 58) };
const nothing = { name: 'undrawn', ...box(0, 0) };
let mainPz = {}, framed = [];
function frameArrow(el) { framed.push(el.name); }
let flowPlay = { msgEls: [[seg1, mid, seg2, label], [plain, label], [nothing], []] };
[0, 1, 2, 3].forEach(frameFlowStep);
console.log(JSON.stringify(framed));
""",
    )
    # The loop frames its representative, never the first piece. An ordinary arrow is unchanged. A step
    # with nothing drawn moves no camera at all.
    assert json.loads(out) == ["mid", "plain"]


# --- the story diagram (the Features view's choosing layer) -----------------------

def _story_fn(js: str, name: str) -> str:
    start = js.index(f"function {name}(")
    return js[start: js.index("\nfunction ", start + 10)]


def test_the_story_diagram_rides_the_features_landing_and_replaces_the_grid() -> None:
    """The diagram is the page's choosing layer; the grid repeated every one of its features
    sentence for sentence, so it hides whenever the diagram draws. It survives in exactly two
    shapes: diff mode (its "changed" badges live only there) and a map recording no features at
    all. The loose-use-cases card survives alone — the diagram has no column for it."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    over = js[js.index("function renderOverview() {"):
              js.index("\nfunction ", js.index("function renderOverview() {") + 10)]
    assert "const drawn = storyDiagramHtml();" in over and "bindStoryDiagram(diagram)" in over
    assert "itemSectionHtml(secs, 'story', 'Feature overview', ids.length, '', drawn)" in over, \
        "the diagram is a titled, framed section like every block of an item page"
    assert "const below = (!story || (mode === 'diff' && hasDiff()))" in over
    assert ": cardGridHtml(looseCard);" in over, "the loose card outlives the hidden grid"
    assert "+ story + below + '</div>';" in over
    html = _story_fn(js, "storyDiagramHtml")
    assert "if (!storyDiagramDraws()) return '';" in html
    # ONE features column in the derived story order, the cast beside it — and a feature the walk
    # skips draws the SAME card as any other. Its position in the trailing block is what says the
    # walk misses it, so no card spends a word on it. The demoted third column read as an importance
    # ranking, which walk membership never was.
    # The headers NAME the columns and claim nothing else — no spelled-out order, and so nothing
    # that has to be switched off on a map with no walk.
    assert "<p class=\"story-colhead\">Features</p>" in html
    assert "<p class=\"story-colhead\">Actors</p>" in html
    assert "Features \u00b7 story order" not in html, "the header states no ordering rule"
    assert "Actors \u00b7 in order of appearance" not in html
    # An explicit one-argument call, never a bare `.map(storyFeatureCardHtml)`: map hands its
    # callback the index and the array too, which is a trap the day the card takes a second flag.
    assert "(st.column || []).map((id) => storyFeatureCardHtml(id))" in html
    assert "Off the happy path" not in html and "story-offnote" not in js
    card = _story_fn(js, "storyFeatureCardHtml")
    assert "story-walkoff" not in card and "not in the walk" not in card
    assert "story-walkoff" not in js
    assert "story-walkoff" not in (VIEWER_DIR / "viewer.css").read_text()
    assert "story-offf" not in js, "the demoted card styling is gone, not shadowed"


def test_a_walk_less_map_still_draws_the_diagram() -> None:
    """The arrows never needed the happy path — they derive from the use cases — so a map with no
    walk still draws the columns (the derived column is map order there). The headers need no
    walk-aware branch: they name the columns, and a name is true on every map. The labels then
    explain instead of navigating."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = _story_fn(js, "storyDiagramHtml")
    assert "walk ?" not in html, "no header switches on whether the map has a walk"
    bind = _story_fn(js, "bindStoryDiagram")
    assert "'This map has no happy path'" in bind
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "story-stage-2col" not in css and "story-stage-2col" not in js


def test_the_three_columns_read_left_to_right_with_the_features_in_the_middle() -> None:
    """Actors | Features | Data areas, and the grid tracks must AGREE with the column order in the
    markup: the two are written in different files, and a swap in one alone silently draws every
    wire backwards. A map whose sub-domains hold no saved records keeps the three-track grid, so the
    data column is added, never faked."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = _story_fn(js, "storyDiagramHtml")
    assert html.index("story-col-cast") < html.index("story-col-spine") < html.index("story-col-areas")
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "grid-template-columns: 300px 130px 420px;" in css
    assert ".story-stage.story-has-areas { grid-template-columns: 300px 130px 420px 130px 270px; }" in css
    assert ".story-col-cast { grid-column: 1;" in css
    assert ".story-col-spine { grid-column: 3;" in css
    # The side columns still spread over the pillar's height — but from their FIRST card down: the
    # first actor and the first data area sit under their heads at the first feature's height (the
    # three heads share the pillar's 15px of top padding and border), and the cards after them take
    # the free space with auto margins, so the last still meets the pillar's foot.
    assert ".story-col-areas { grid-column: 5; justify-content: flex-start; padding-top: 15px; }" in css
    assert ".story-col-cast { grid-column: 1; justify-content: flex-start; padding-top: 15px; }" in css
    assert ".story-col-cast > .story-card + .story-card, .story-col-areas > .story-card + .story-card { margin-top: auto; }" in css
    # The pillar carries its own ground: the middle column has to stay the thing the eye lands on
    # once there is a column on each side of it.
    spine = css[css.index(".story-col-spine {"):]
    assert "background:" in spine[:spine.index("}")]
    # The pillar ends at its LAST FEATURE — a grid item stretches to the row by default, so it took the
    # height of whichever side column ran longest and left a slab of empty indigo under the last card.
    assert "align-self: start" in spine[:spine.index("}")]
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    # …and the two side columns then spread over the PILLAR's height, not the grid row's, which is what
    # both comments beside them always claimed. Measured, because only the browser knows either height.
    assert "function fitSideColumnsToPillar(stage) {" in js
    bind = js[js.index("function bindStoryDiagram(root) {"):]
    bind = bind[:bind.index("const st = FEATURES.story")]
    assert "fitSideColumnsToPillar(stage);" in bind, "run it BEFORE any wire is measured off a card"


def test_the_outer_frame_is_the_drawing_s_and_a_page_of_cards_does_not_get_one() -> None:
    """The frame is the DRAWING's frame. A map page puts its drawing straight inside `#diagwrap`, so
    the white ground and the 1px rule are that drawing's own. A page of text and cards puts a scrolling
    column in there instead, and that column already carries its own ground and its own framed board —
    so Features, Happy Path and Interfaces drew a rounded box around the whole page for nothing, and
    the reader met a frame inside a frame inside a frame."""
    css = (VIEWER_DIR / "viewer.css").read_text(encoding="utf-8")
    assert ("#diagwrap:has(.usecases-wrap, .glossary-wrap) { background: none; border: 0; border-radius: 0; margin: 0; }" in css)
    # The MARGIN goes with the frame: bare, it left a strip of the pane under the header for the
    # header's shadow to land on, which reads as a solid band over the page rather than an edge.
    # It is still ON the shared board rule: a map page is exactly where it earns the frame.
    assert ".hp-board, .journey-board, .ifd-wrap, .story-wrap, #diagwrap {" in css


def test_a_name_wears_its_kind_as_one_small_mark_and_never_as_a_block() -> None:
    """A chip is a plain box with a grey hairline, and its GLYPH is the only thing on it carrying the
    kind. The chip used to be filled and outlined in that kind's colour, on pictures that already
    rotate a colour per interface and per feature — a coloured block per name, saying what the mark
    beside it already said.

    The same mark leads the person heading an interface's box, at the same 11px, from the same one
    builder — so a section headed by a name says human, AI agent or software service without the
    reader carrying the kind over from the card."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    css = (VIEWER_DIR / "viewer.css").read_text(encoding="utf-8")
    # No per-kind rule for the in-a-box pill: the injected sheet styles the tinted box, the kind pill
    # and the identity edge, and stops there. The pill takes its kind's colour from its own two custom
    # properties, set by the builder, so no page-wide rule has to know the kinds at all.
    assert ".item-pill.ibox-k-" not in css and "`.item-pill.ibox-k-" not in js
    assert "`.ibox-k-${k} .ibox-pill{background:${t.fill};color:${t.stroke}}`" in js, \
        "the KIND pill keeps its colour — that is the one tag whose job IS the kind"
    # The glyph colours itself with an attribute, not `currentColor`, so a neutral pill keeps its mark.
    gly = js[js.index("function itemGlyphSvg(k, ikind) {"):]
    assert 'stroke="${esc(t.stroke)}"' in gly[:gly.index("\nfunction ")]
    # …and the person heading the interface box takes that same builder.
    assert "itemGlyphSvg(itemSpecRole(nm).k), nm);" in js
    # …and that name is a DOOR to the person's own page, the same treatment the use cases beside it have.
    assert 'class="ifd-elabel-who"' in js and "go({ kind: 'actor', act: who })" in js
    assert ".ifd-elabel-who:hover { text-decoration: underline;" in css
    # ONE size for the small mark, stated once for every place it appears.
    assert ("#diagram .ibox-band .item-pill .ibox-gly, #diagram .journey-ifs .item-pill .ibox-gly,\n"
            "#diagram .ifd-elabel-dir .ibox-gly { width: 11px; height: 11px; }") in css


def test_a_picture_with_a_natural_width_is_framed_at_that_width() -> None:
    """The frame is as wide as the DRAWING, never as wide as the pane. Both of these pictures have a
    natural width, so on a wide window the white board ran on past the last card and left a slab of
    empty white beside it, saying the drawing carried on when it did not. The happy path and the walk
    map are deliberately NOT hugged: their content has no natural width, and hugging it would take away
    the sideways scroll the strip is built on.

    The hug goes on the WRAPPER `bindHFade` inserts, because that is the box it places its edge shades
    against — a board narrower than that wrapper draws its shades out over the page instead of on its
    own edge."""
    css = (VIEWER_DIR / "viewer.css").read_text(encoding="utf-8")
    assert ".hfade-wrap:has(> .story-wrap) { width: max-content; max-width: 100%; }" in css
    # NOT max-content for the Interfaces picture: its gutters are `1fr` so a narrow window can squeeze
    # them, and under max-content sizing an `1fr` track collapses to its own 60px minimum.
    assert ".hfade-wrap:has(> .ifd-wrap) { width: calc(var(--ifd-stage-w) + 2px); max-width: 100%; }" in css
    # ONE number for the drawing's rest width: the stage may not grow past it, and while the source
    # column is open it may not shrink below it either.
    assert ":root { --ifd-stage-w: calc(320px + 130px + 160px + 130px + 320px); }" in css
    assert "max-width: var(--ifd-stage-w);" in css
    assert "body:not(.code-hidden) .ifd-stage { min-width: var(--ifd-stage-w); }" in css
    # …and the Interfaces page earns the same measure as the other picture pages, so the page's own
    # ground runs the width of the pane behind the hugged board instead of stopping in bare white.
    assert (".usecases-wrap:has(.hp-board), .usecases-wrap:has(.ifd-wrap) { max-width: 1440px; }"
            in css)


def test_every_wire_flows_left_to_right_through_one_drawer() -> None:
    """Both hops (actor→feature, feature→area) are drawn by the same function, so their shape,
    their hover keys and their label placement cannot drift apart. Every wire leaves a RIGHT edge
    and lands on a LEFT edge — that is what makes a stake label read in sentence order, which it
    did not when the actors sat on the right."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    assert "const wire = (fromEl, toEl, keys, wireCls, fromKey, toKey) => {" in bind
    assert "side(fromEl, 'right')" in bind and "side(toEl, 'left')" in bind
    assert "wire(a, f, { sactor: e.actor, sfeat: e.feature }, '', 'sactor', 'sfeat')" in bind
    assert "{ sfeat: t.feature, sarea: a.id }" in bind
    assert "'story-ref'" in bind
    # The drawer places the label and never fills it: one hop's label is a stake sentence, the
    # other's is a list of doors, and a shared `textContent` would make the second impossible.
    assert "lab.textContent = text;" not in bind


def test_a_story_label_stands_at_the_far_end_of_its_wire() -> None:
    """A label used to sit at its wire's MIDPOINT, on one nowrap line: nothing tied it to a card, and
    at full text width it lay over the two boxes its own wire joined.

    It stands at the FAR end now — the end whose card is not the one you picked. Picking a card
    lights every wire it touches and they all meet at that card, so a near-end label would put the
    whole set on one point; at the far end each lands beside a different box, and that box is what
    says which arrow you are reading. Which end that is therefore depends on WHAT IS LIT, so the
    drawer only records both ends and the placer chooses."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    assert "lab.style.left = ((sx + tx) / 2) + 'px';" not in bind
    # Both ends and the card at each ride the ELEMENT as data — so the rule is readable straight off
    # the page, which is what the browser gate checks.
    assert "lab.dataset.labsx = String(sx); lab.dataset.labsy = String(sy);" in bind
    assert "lab.dataset.labtx = String(tx); lab.dataset.labty = String(ty);" in bind
    assert "lab.dataset.labfrom = fromKey; lab.dataset.labto = toKey;" in bind
    # Capped to the gutter it crosses, which is what keeps it off the boxes on either side. Fixed at
    # build time, because both ends of a wire sit on the same gutter.
    assert "lab.style.maxWidth = Math.max(70, Math.abs(tx - sx) - 2 * LAB_PAD) + 'px';" in bind
    # The far end: lit BY the card at the tail means the label goes to the head, and the reverse.
    assert "const atHead = l.dataset.labfrom === key;" in bind
    assert "const x = parseFloat(atHead ? l.dataset.labtx : l.dataset.labsx);" in bind
    assert "const y = parseFloat(atHead ? l.dataset.labty : l.dataset.labsy);" in bind
    # ABOVE that end, always. A label under a downward arrow's head read as belonging to whatever
    # came next down the column.
    assert "at.set(l, { h, top: y - LAB_DROP - h, x, atHead });" in bind
    # Pinned by the edge facing the far box, and the unused offset CLEARED: a label placed both ways
    # keeps the stale one otherwise and stretches across the whole gutter.
    assert "l.style.right = a.atHead ? (stage.offsetWidth - (a.x - LAB_PAD)) + 'px' : '';" in bind
    assert "l.style.left = a.atHead ? '' : (a.x + LAB_PAD) + 'px';" in bind
    # …and it is re-decided on every repaint of the picture, since the answer moves with what is lit.
    assert "placeLabels(key);" in bind
    css = (VIEWER_DIR / "viewer.css").read_text()
    block = css[css.index(".story-elabel {"):css.index(".story-elabel.story-lab-on")]
    # A wrapped pill needs no nowrap and no recentring transform — one EDGE is pinned, not the middle.
    assert "white-space: nowrap" not in block, block
    assert "transform:" not in block, block


def test_two_story_labels_lit_together_stack_instead_of_piling_up() -> None:
    """Far-end placement spreads a lit card's labels over the boxes on the other side, but two of
    those boxes can still sit close enough for two wrapped labels to meet. One stack per gutter edge,
    swept bottom to top, each pushed clear of the one before — which only ever moves a label further
    above its own end, never below it."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    assert "const k = (atHead ? 'H' : 'T') + x;" in bind, "one stack per gutter edge"
    assert "a.top = Math.min(a.top, ceil - a.h);" in bind   # never below the one before it
    assert "ceil = a.top - LAB_STACK;" in bind
    # Heights read first, tops written after: one browser layout, not one per label.
    assert bind.index("const h = l.offsetHeight;") < bind.index("l.style.top = a.top + 'px';")


def test_a_record_named_on_a_reference_arrow_is_a_door() -> None:
    """The arrow's label is the one place on this page that names a single saved record, so the name
    opens it — shown in context, selected on the view that draws it. A name the reader cannot follow
    is a claim they have to take on trust. The "+N more" tail stays plain text: no single record."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    fill = _story_fn(js, "fillAreaTouchLabel")
    assert "showInContext(id);" in fill
    assert "ev.stopPropagation();" in fill, "the record's door is not the label's, nor the unpin"
    assert "story-elabel-ent" in fill
    # An id the graph does not hold draws its name as TEXT — a button opening nothing is worse
    # than a word.
    assert "if (!GRAPH.nodes[id]) { line.textContent = name; lab.appendChild(line); return; }" in fill
    # ONE RECORD PER LINE, and no commas. They ran as a comma-separated sentence, which hides where
    # one name ends and the next begins — and every one of them is a door, so a reader had to find a
    # name's edges before they could click it. The tail joins the list as its own last line.
    assert 'line.className = "story-elabel-line"'.replace('"', "'") in fill
    assert "', '" not in fill, "no comma between two records"
    assert '<span class="story-elabel-line">${tail}</span>' in fill
    # …and its tail comes from the ONE tail component, with NO door: no single page holds the rest of
    # the entities a feature touches in a data area, and a tail that leads nowhere should not look
    # like one that leads somewhere.
    assert "moreTailHtml((t.entities || []).length - ids.length)" in fill
    assert "data-more-iface" not in fill
    assert ".story-elabel-ent" in (VIEWER_DIR / "viewer.css").read_text()


def test_the_story_block_scrolls_sideways_only_and_never_clips_the_pillar() -> None:
    """Two faces of one bug, both seen on screen. `overflow-x: auto` makes the OTHER axis a scroll
    box too (a `visible` sibling axis computes to `auto`), so the block grew its own VERTICAL
    scrollbar beside the page's, and sliced the raised pillar's top edge and drop shadow off at its
    edge. `overflow-y: hidden` gives one scrollbar, the horizontal one — and once the box clips,
    the box has to hold everything: the wrap carries padding for the shadow, and the pillar may not
    use a negative margin to sit above the stage."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    wrap = css[css.index("\n.story-wrap {"):]
    wrap = wrap[:wrap.index("}")]
    assert "overflow-x: auto" in wrap and "overflow-y: hidden" in wrap
    assert "padding: 10px 20px 22px" in wrap, \
        "the raised panel's shadow needs room inside the clip, and its cards need room off the rule"
    spine = css[css.index(".story-col-spine {"):]
    spine = spine[:spine.index("}")]
    assert "margin:" not in spine, "a negative margin here is clipped away by the wrap"


def test_the_data_column_never_invents_an_owner() -> None:
    """The area box draws on every map, authored owners or not — which records a feature's walks
    reach is a derived fact, and who the data is FOR is authored. The box may state the AUTHORED
    answer (`a.owners`); it must never read one off `touchedBy`, which is the derivation this
    design was measured out of. One inbound arrow is not ownership."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    card = _story_fn(js, "storyAreaCardHtml")
    own = _story_fn(js, "storyAreaOwner")
    # ONE place works the answer out, and the box and the wire both read it — the two used to carry
    # a copy each and disagreed on screen. The helper is where the never-invent rule lives now:
    # the OWNER comes off `a.owners` alone, and `touchedBy` only ever answers "is there evidence".
    assert "const owners = (a.owners || []).filter((c) => FEAT_BY_ID[c]);" in own
    assert "const sole = owners.length === 1 ? owners[0] : null;" in own
    assert "const touch = sole ? touched.find((x) => x.feature === sole) : null;" in own
    assert "const touched = a.touchedBy || [];" in own
    # `touched` may only ever answer "does one of the AUTHORED owners reach this", never supply one.
    tail = own.split("const touched")[1]
    assert "owners.some((c) => touched.some((x) => x.feature === c))" in tail
    assert "touched[0]" not in tail and "touched.map" not in tail, \
        "an owner is never read off the arrows landing on the box"
    assert "storyAreaOwner(a)" in card, "the box asks the one derivation, it does not redo it"
    assert "touchedBy" not in card, "an owner is never read off the arrows landing on the box"
    assert "a.owners" not in card, "the box reads the authored answer through the shared helper"
    assert "data-sarea=" in card
    assert 'go({ kind: \'domsub\', sd });' in _story_fn(js, "bindStoryDiagram")


def test_an_ownership_wire_is_drawn_only_where_exactly_one_owner_is_authored() -> None:
    """The map's authored claim, and the one line that carries it. A SHARED area (several owners)
    deliberately gets no wire — the design draws sharing as the shape of several inbound arrows and
    names the owners on the box — and an area the map never decided gets nothing. The owning pair
    also loses its reference arrow, or the reader is told one feature both owns and merely visits
    the same data."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    assert "const o = storyAreaOwner(a);" in bind, "the wire asks the same one derivation the box does"
    assert "const sole = o.sole;" in bind
    assert "if (sole && featEl[sole])" in bind
    assert "if (!from || t.feature === sole) continue;" in bind, \
        "the owning pair draws ONE line, not two"
    assert "'story-own'" in bind
    # The class MARKS the wire; it must not STYLE it. At rest every wire in the gutter is the same
    # grey, because the diagram at rest is for choosing — a line that shouts before the reader has
    # picked anything spends the page's one loud voice on it.
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "path.story-own {" not in css, "an ownership wire takes no look of its own at rest"
    assert ".story-elabel-own" not in css and ".story-elabel-own" not in js
    assert "'owns'" not in bind, "the wire carries the records it reaches, not the word"
    # An owner NO walk reaches has no record names to list, so its label used to render EMPTY — a
    # pill that reads as a rendering fault rather than as the defect it is. The screen must not be
    # the one place `validate`'s "owner with no evidence" hides; the change's own retro-check calls
    # that a regression.
    assert "'no step of it reaches this'" in bind
    assert "'no step reaches this'" not in bind, \
        "the qualifier is load-bearing: another feature's arrow may reach this box"
    # ONE NAME FOR ONE THING. The box's foot and this label are the same thing seen twice on one
    # screen; they said it with two different nouns until the words were made to match.
    assert "no journey reaches this" not in js
    # ONE WRITER for the sentence, because it is said on the Features page and again on a record's
    # own page, and two copies drift the moment the first is edited.
    assert "function storyGapSentence(o, plural) {" in js
    assert "' reaches this data.'" in js, "the box and the label say it in the same words"
    assert "story-elabel-gap" in bind and ".story-elabel-gap" in css
    # THE PAGE NEVER SPEAKS FOR THE VALIDATOR. This label used to claim "`coyomap validate` reports
    # this as an owner with no evidence" — false on all four live maps, because every one of those
    # areas is recorded and `validate` reports nothing. Say what the MAP says.
    code = "\n".join(l for l in bind.splitlines() if not l.lstrip().startswith("//"))
    assert "coyomap validate" not in code
    # A SHARED area draws no ownership wire and says its owners in WORDS instead. No dashed border:
    # dashed already means "a container, open it" on every diagram in this viewer.
    # The two feet a data area can carry ride ONE rule, because they are the same kind of sentence:
    # what the wire into this box could not say (`Shared by …` / `Said to exist for …`).
    assert ".story-shared, .story-gap {" in css, "a shared area says its owners in words"
    assert "border-style: dashed" not in css[css.index(".ibox.story-area-owned"):
                                             css.index(".story-shared")]
    # The two NORMAL lines stay SOLID: at rest the gutter speaks one visual language, and a reader
    # should not have to learn a dash code before the diagram has told them anything. Scoped to the
    # story wires — other diagrams on other screens use a dash for their own reasons.
    # EXACTLY ONE EXCEPTION, and it is not a category the reader has to learn: the unevidenced
    # ownership claim (its own test below), which the box it lands on explains in words.
    wires = [l for l in css.splitlines() if l.startswith("svg.story-wires path")]
    dashed = [l for l in wires if "dasharray" in l]
    assert [l.split("{")[0].strip() for l in dashed] == ["svg.story-wires path.story-own-gap"], \
        f"a story wire is dashed for some other reason: {wires}"



def test_a_claim_no_step_reaches_is_marked_whether_or_not_the_map_records_why() -> None:
    """12 of the 30 ownership wires across the four live maps are claims the map cannot back: a
    feature named as the reason a data area exists, with no step of that feature reaching a single
    record in it. reminderrepo 5 of 9, coyomap's own map 5 of 8, mcpolis 2 of 7, argus 0 of 6. They
    reached the page in exactly the same ink as the ones the map CAN back.

    THREE STATES, and a RECORDED EXCEPTION IS STILL A GAP. The record silences `validate`, whose
    reader is the build lead; the person reading this page never sees it. So both gap states take
    the SAME mark — one line style, no dash code to learn — and the WORDS say which and why. Marking
    only the unrecorded ones would take the page back to identical wires, because every gap on every
    live map today is a recorded one (12 of 12).

    The visible half of this is measured in tests/test_viewer_browser.py, not here: a source string
    cannot see a line that renders fainter than the one it stands out from."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    own = _story_fn(js, "storyAreaOwner")
    # A GAP IS ABOUT THE OWNERS, not about how many there are — it was `!!sole && !touch`, which
    # left a SHARED area whose owners are ALL blind (mcpolis SD3, live) with no mark at all.
    assert "const gap = owners.length > 0 " \
           "&& !owners.some((c) => touched.some((x) => x.feature === c));" in own
    assert "answered: gap && !!why" in own and "unanswered: gap && !why" in own
    # The recorded reason is READ, never derived, and it is never evidence: it says who looked.
    assert "(FEATURES.ownerRecords || {})[a.id]" in own

    # THE WIRE: one mark for both gap states.
    bind = _story_fn(js, "bindStoryDiagram")
    assert "const ownCls = 'story-own' + (o.gap ? ' story-own-gap' : '');" in bind
    assert "wire(featEl[sole], to, { sfeat: sole, sarea: a.id }, ownCls, 'sfeat', 'sarea')" in bind
    rule = css[css.index("svg.story-wires path.story-own-gap {"):]
    rule = rule[:rule.index("}")]
    assert "stroke-dasharray" in rule
    assert "opacity: 1" in rule, "a faded exception is the one thing this line must not be"

    # THE BOX: the settled mark only where the map can back it, and the words for both gap states.
    card = _story_fn(js, "storyAreaCardHtml")
    assert "(own.sole && own.touch ? ' story-area-owned' : '')" in card
    assert "(own.gap ? ' story-area-gap' : '')" in card
    assert "(own.unanswered ? ' story-area-gap-open' : '')" in card
    # THE OWNER IS NOT NAMED where a wire in the same picture already joins it — `a box does not
    # repeat its picture`, whose stated reason is this page. A SHARED area has no wire, so it names
    # its owners and adds the gap sentence after them.
    assert "Said to exist for" not in card, "the wire in this picture already says whose it is"
    assert "storyGapSentence(own, false)" in card and "storyGapSentence(own, true)" in card
    gapfn = _story_fn(js, "storyGapSentence")
    assert "'No step of ' + (plural ? 'any of them' : 'it') + ' reaches this data.'" in gapfn
    assert "The map says why: ' + mdInline(o.why)" in gapfn, \
        "the reason is a prose field like every other, so a backtick renders"
    assert "' The map does not say why.'" in gapfn
    assert "esc(own.why)" not in card and "esc(o.why)" not in gapfn
    assert "{ foot: foot," in card
    # THE REASON IS PRINTED WHOLE, and clamped by CSS instead. It was cut to its first sentence,
    # which on the four live maps lost the load-bearing half on 7 of 12 boxes: reminderrepo's five
    # kept a restatement of the finding and dropped the actual reason, and mcpolis's two ended
    # mid-clause on a dangling determiner. The page holds the only complete copy in the product —
    # a record's area page carries neither the reason nor the gap — so a cut string loses it for good.
    assert "firstSentence(own.why)" not in card
    clamp = css[css.index("\n.story-gap {"):]
    clamp = clamp[:clamp.index("}")]
    assert "-webkit-line-clamp" in clamp and "overflow: hidden" in clamp, \
        "the DRAWN height is capped; the sentence stays in the DOM"
    # A RECORD'S OWN PAGE says the same thing, through the same sentence and the same derivation:
    # 85 of the 237 "Owned by" rows across the four live maps sit in an area no owner's step reaches,
    # and it used to state the claim flatly. A record carrying `owners` of its own is left alone —
    # the area's gap says nothing about an answer that record overrode.
    owned = _story_fn(js, "ownedByHtml")
    assert "storyAreaOfRecord(id)" in owned and "storyAreaOwner(area)" in owned
    assert "storyGapSentence(o, own.length > 1)" in owned
    assert "const inherited = !!o && o.owners.length === own.length" in owned
    assert "dv-note-gap" in owned and ".dv-note-gap" in css
    assert ".story-shared, .story-gap {" in css and "\n.story-gap {" in css
    italic = css[css.index("\n.story-gap {"):]
    assert "font-style: italic" in italic[:italic.index("}")]


def test_the_recorded_reasons_are_parsed_once_where_every_other_reader_parses_them() -> None:
    """A `<key>: <why>` line is read by ONE module, after four separate parsers each silently
    over-suppressed in its own way. The page needs those lines, so they are parsed server-side
    through that module and shipped as data — a fifth parser, in JavaScript, would be the fifth scar.
    Same heading and same key vocabulary as the validator's own skip, so the two can never disagree
    about which areas are answered."""
    gen = (VIEWER_DIR / "gen_viewer.py").read_text()
    assert "def owner_records(m: ProjectModel) -> dict[str, str]:" in gen
    assert "records.spec_of(DATA_OWNER_EXCEPTIONS_HEADING)" in gen
    assert "records.lines(m, DATA_OWNER_EXCEPTIONS_HEADING)" in gen
    assert "records.why_of(DATA_OWNER_EXCEPTIONS_HEADING, line)" in gen
    assert "records.keys_on_line(line, spec.key, spec.seps, spec.lead, spec.strict_multi)" in gen
    assert 'feature_block["ownerRecords"] = owner_records(model)' in gen
    # No second parser in the browser: the page reads the shipped answer and nothing else.
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "Data owner exceptions" not in js, "the heading is parsed server-side, never here"


def test_a_page_s_own_title_is_never_linked_to_the_glossary() -> None:
    """A page about one element is not decorated with a link to itself. `glossSubjectKey` covers the
    case where the WHOLE title is one term ("Contact"); it cannot cover a title that merely CONTAINS
    one, and the headings skip could not either — a page's title is drawn as a `p`, because the
    breadcrumb is what names the page. So the feature page for "Activities and schedules" underlined
    both halves of its own name, the actor page for "Reminder owner" underlined its first word, and
    the rule "Named person or group" underlined its last. Measured in the live DOM: 2, 1 and 1."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    skip = js[js.index("const GLOSS_SKIP ="): js.index(";", js.index("const GLOSS_SKIP ="))]
    assert ".page-hero-name" in skip, "a page's own title is not a link to itself"
    # The title lives inside it, so skipping the row covers the kind word and the subject at once.
    assert 'class="page-hero-name"' in js and 'class="page-hero-subject"' in js
    # And ONLY the title: the hero's sentence is prose and keeps its links.
    assert ".page-hero-purpose" not in skip and ".page-hero-meta" not in skip

def test_the_arrow_head_sits_at_the_line_end_and_takes_the_line_s_colour() -> None:
    """Two faults in one marker, both seen on screen.

    A marker scales with its line's STROKE WIDTH by default, so the head grew and shifted every time
    a wire went grey (1.4) → lit (2.2) → glowing (3.2), which is what made the join look broken.
    `userSpaceOnUse` fixes its size, and `refX` at the TIP (8, the triangle's point, not 7) puts
    that point exactly where the line ends instead of a unit past it.

    And ONE marker is shared by every path, so a fixed `fill` left a selected indigo wire ending in
    a grey point. `context-stroke` takes the colour of the line the head sits on — every state, one
    marker."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = _story_fn(js, "storyDiagramHtml")
    assert 'refX="8"' in html and 'markerUnits="userSpaceOnUse"' in html
    assert 'refX="7"' not in html
    css = (VIEWER_DIR / "viewer.css").read_text()
    marker = css[css.index("svg.story-wires marker path {"):]
    marker = marker[:marker.index("}")]
    assert "context-stroke" in marker, "the head takes the colour of the line it sits on"
    assert "#c3c8d9" not in marker, "no fixed colour: a lit wire would end in a grey point"


def test_hovering_a_label_glows_the_one_wire_it_names() -> None:
    """A lit card lights ALL its wires, and its labels sit over a gutter several of them cross —
    without this there is no way to tell from the page which of a feature's five arrows a given
    label belongs to. The pairing is set where BOTH are made, never inferred from array position:
    the label is appended by the caller, after the path, so index-pairing is one refactor away from
    glowing the wrong wire."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    assert "const pathOfLabel = new Map();" in bind
    assert "pathOfLabel.set(lab, path);" in bind
    assert "p.classList.add('story-glow');" in bind
    assert "p.classList.remove('story-glow');" in bind
    # a new picture (a pin, or clearing) must never leave a stale wire singled out
    assert "'story-hot', 'story-cold', 'story-glow'" in bind
    assert "p.classList.remove('story-glow');   // a new picture starts with no wire singled out" in bind
    assert "svg.story-wires path.story-glow {" in (VIEWER_DIR / "viewer.css").read_text()


def test_a_wire_arrives_flat_however_far_it_has_to_climb() -> None:
    """The curve leaves and arrives HORIZONTALLY, because that is the direction the arrow head is
    oriented in. With a fixed handle, a wire whose ends are far apart vertically had to swing from
    near-vertical to horizontal inside those few pixels — a kink right where the head sits, which
    read as the head being detached from its line. The handle scales with the climb instead."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    assert "const dx = Math.max(60, Math.min(Math.abs(ty - sy) * 0.55, Math.abs(tx - sx) * 0.9));" in bind
    assert "const dx = 60;" not in bind


def test_a_feature_s_colour_is_for_reading_not_for_naming() -> None:
    """A feature's wash has ONE job: two features drawn NEXT TO EACH OTHER must read as two things —
    down the Features column, and along the happy path where a run of steps in one feature is a band
    of colour. It is not a name. Two features at opposite ends of a board may share a wash.

    THAT IS WHAT MAKES FIVE ENOUGH, and sixteen were needed only while the colour was trying to be a
    name — which it could not be: every wash pale enough to read a sentence on sits within 20 of a
    kind colour, because the pale band is a narrow slice of the colour space. Colouring the NEIGHBOUR
    GRAPH needs 4 on MCP Hero (10 features, 14 bands) and 3 on argus and on coyomap.

    SO FEATURES STAY PALE, and the rule the rest of the map keeps is untouched: a deeper wash means a
    CONTAINER (a subsystem at 0.888 lightness, a data area at 0.906) and a very pale one a leaf.

    ONE FEATURE IS ONE COLOUR ON ONE BOARD. The happy path draws some features twice, so the colour
    is a property of the feature and never of the position — the greedy colouring runs once per map."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert js.count("const ROTATING_TINTS = [") == 1, "one palette, not a second copy"
    tints = js[js.index("const ROTATING_TINTS = ["):js.index("]", js.index("const ROTATING_TINTS = ["))]
    assert tints.count("#") == 10, "ten washes — as many as the pale band holds"
    assert "FEATURE_EDGES" not in js and "FEATURE_TINTS" not in js, \
        "the saturated companion is gone with the edge it was for, and the palette is shared now"
    # WHO IS NEXT TO WHOM: the Features column, and two runs of the happy path that follow each other.
    nb = js[js.index("function featureNeighbours() {"):js.index("\n}", js.index("function featureNeighbours() {"))]
    assert "(FEATURES.story || {}).column" in nb and "GRAPH.happy_path" in nb
    # SEPARATION IS A FLOOR, NOT A TARGET, and both ways of getting that backwards were tried and
    # measured: the plain greedy colouring piled 7 of MCP Hero's 10 features onto two washes, and
    # maximising the distance from a neighbour drove every pick to the palette's extremes for the
    # same result. A modest bar plus "the least-used that clears it" uses all 10 on all 10.
    hue = js[js.index("function rotateTints(order, adj) {"):
              js.index("\n}", js.index("function rotateTints(order, adj) {"))]
    assert "const ROTATE_GAP_STEPS = [45," in js, "one modest bar, then relaxations"
    assert "used[b] < used[a]" in hue, "the least-used wash that clears the bar"
    # A FRESH COLOUR BEATS A LOWER BAR: every bar is tried against the unused washes first. Without
    # that pass a board of eight features spent seven washes and repeated one while two sat unused.
    assert "(!fresh || used[i] === 0)" in hue
    assert "FEATURE_COLOUR_OF = null;" in js, "recoloured when a new map arrives"
    # THE CARD wears it as its BACKGROUND, and carries no stripe.
    card = _story_fn(js, "storyFeatureCardHtml")
    assert "fill: featureTint(id)" in card and "edge:" not in card
    # …and the two columns BESIDE it are white. Painting every box its kind's colour was one rule too
    # many for this picture: the headings already say what each column is, and the fills then
    # competed with the one colour that carries information here. The kind still says itself in the
    # glyph and the pills, and the fill stays the kind's on every other picture.
    for fn in ("storyActorCardHtml", "storyAreaCardHtml"):
        assert "tinted" not in _story_fn(js, fn), f"{fn}: white, not its kind's wash"
    # THE INTERFACES PICTURE ROTATES TOO, off the same palette and the same picker. Every box there
    # is a door, so the door's amber said nothing and made a column of sixteen a wall; the kind word
    # beside the name still says WHICH door it is. The rule both pictures now follow: on a high-level
    # picture only the one kind the picture is ABOUT carries a colour, and it rotates.
    assert "fill: ifaceTint(i.id)" in _story_fn(js, "ifaceBoxHtml")
    assert "function rotateTints(order, adj) {" in js, "one picker, not two"
    assert js.count("const ROTATE_GAP_STEPS = [") == 1 \
        and js.count("const ROTATING_TINTS = [") == 1, "one palette and one ladder, not two"
    for fn in ("featureHue", "ifaceTint"):
        assert "rotateTints(" in _story_fn(js, fn), f"{fn} asks the shared picker"
    # …and so does every LABEL that belongs to that feature, which is what makes a lit card's several
    # labels read as that feature's voice rather than as one anonymous pill repeated.
    bind = _story_fn(js, "bindStoryDiagram")
    assert "if (keys.sfeat) lab.style.background = featureTint(keys.sfeat);" in bind
    assert "story-elabel-feat" not in js and "story-elabel-feat" not in (VIEWER_DIR / "viewer.css").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "background: #fff" not in css[css.index(".story-col-spine > .story-card"):
                                         css.index(".story-col-spine > .story-card") + 200], \
        "the pillar must not paint over a card's own colour"


def test_a_card_name_is_the_door_that_does_not_steal_the_pin() -> None:
    """The card's own click PINS; its NAME is the one control leaving this screen — the feature's
    details page, the actor's, or the data area's — so the name must not fire the pin too. ONE
    handler serves all three columns, branching on which id the name carries."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    name = bind[bind.index(".story-card .ibox-name"):]
    assert "ev.stopPropagation();" in name
    assert "if (cap) go({ kind: 'capability', cap });" in name
    assert "go({ kind: 'actor', act: b.getAttribute('data-actor') });" in name
    for fn, attr in (("storyFeatureCardHtml", "data-cap"), ("storyActorCardHtml", "data-actor")):
        card = _story_fn(js, fn)
        assert "nameAttrs:" in card, f"{fn}: the name is the door"
        # The item box writes the title on every name it draws, so the card no longer says it.
        assert '`<button type="button" class="${ncls}"' in js \
            and 'title="Open ${nm}"' in js, "the name says where it goes"
        link = card[card.index("nameAttrs:"):]
        assert attr in link[:200], f"{fn}: the name carries the id its branch reads"


def test_no_count_under_a_story_card_is_a_door() -> None:
    """A card carries exactly ONE door and it is the name. The counts under the sentence — use
    cases on both columns, rules on the feature — are labels: three targets on one small card made
    a count read as a place to go rather than a fact about the element."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    for cls in ("story-ucpill", "story-rulespill"):
        assert cls not in js and cls not in css, f"{cls}: the door class is gone, not shadowed"
    for fn in ("storyFeatureCardHtml", "storyActorCardHtml"):
        src = _story_fn(js, fn)
        # A COUNT IS A STRING THE CARD HANDS THE BOX, never markup it writes itself. The card writes
        # NO control at all now: the item box draws the one door, on the name, so a count cannot
        # become a control on one card and a label on the next.
        assert "<button" not in src, f"{fn}: the card writes no control of its own"
        assert "countLabel(n, 'use case')" in src, f"{fn}: the card still states its count"
    assert '<span class="ibox-count">' in js and ".ibox-count:hover" not in css, \
        "a count is a plain label and offers no hover affordance"


def test_a_stake_label_names_its_step_and_is_not_a_door() -> None:
    """A stake label was a door: it opened the Happy Path with this edge's first step selected. What
    it cost was the picture — a reader hovering a card to read its stakes was one stray click from
    losing the page they were reading. The step is still reachable and still selectable on the Happy
    Path itself, which is the view whose subject that is.

    It still NAMES the step, by title and never by number: no step number appears on this view. And a
    click on it is swallowed rather than ignored, or it would clear the pinned card underneath."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    assert "go({ kind: 'hp'" not in bind, "the label leaves the page no more"
    assert "lab.title = hp ? (hpStepText(hp) || 'On the happy path')" in bind
    assert "'Not on the happy path'" in bind
    assert "lab.addEventListener('click', (ev) => ev.stopPropagation());" in bind
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "story-elabel-live" not in css and "story-elabel-live" not in js, \
        "the door class is gone, not shadowed"


def test_a_pin_stays_on_the_page_and_never_opens_the_panel() -> None:
    """The panel only ever repeated the card the reader had just clicked; the one thing it added,
    the door to an actor's page, is the card's NAME now. A pin lights the wires and labels and
    touches nothing else."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    code = "\n".join(l for l in bind.splitlines() if not l.lstrip().startswith("//"))
    for banned in ("showNode(", "paneSync(", "PANEL_HOST"):
        assert banned not in code, f"a pin must not touch the panel ({banned})"
    assert 'data-actor="${esc(r.name' in _story_fn(js, "storyActorCardHtml"), \
        "the actor card carries its own door instead"


def test_search_and_show_in_context_pin_the_card_in_the_diagram() -> None:
    """A feature or an actor found by search lands on the Features diagram with its card pinned and
    its arrows lit — the richest context the app has for either. The flash-a-grid-card landing
    survives only as the fallback for a map whose diagram cannot draw."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    target = js[js.index("function selectTargetFor(id) {"):
                js.index("\nfunction ", js.index("function selectTargetFor(id) {") + 10)]
    assert "storyPin: { key: 'sfeat', id }" in target
    assert "storyPin: { key: 'sactor', id: role.id }" in target
    assert target.count("if (storyDiagramDraws())") + target.count("storyDiagramDraws())") >= 2
    # The fallbacks stay behind the guard: a feature flashes its grid card; an actor, with no card
    # grid left to flash, opens its own page.
    assert "return { state: { kind: 'usecases' }, selectId: null, flashId: id };" in target
    assert "return { state: { kind: 'actor', act: n.name } };" in target
    # The one-shot survives the navigation, and the in-place case uses the fresh render's applier.
    assert "pendingStoryPin = t.storyPin;" in js
    assert "if (storyPinApply) storyPinApply(t.storyPin);" in js
    bind = _story_fn(js, "bindStoryDiagram")
    assert "storyPinApply = (p) => {" in bind and "scrollIntoView" in bind
    # …and it takes only the keys IT draws. The Interfaces picture pins through the same one-shot and
    # the same `sel` field, so an unguarded consumer here swallowed a surface's pin and dropped it.
    assert "if (pendingStoryPin && pendingStoryPin.key !== IFACE_PIN_KEY) {" in bind


def test_story_chrome_never_term_links_but_card_prose_does() -> None:
    """Names, pills, column heads and the stake labels are labels or controls, not prose; the card
    sentences (purpose, wants) stay linkable like every other card's."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    skip = js[js.index("const GLOSS_SKIP ="): js.index(";", js.index("const GLOSS_SKIP ="))]
    for cls in (".ibox-name", ".ibox-pill", ".ibox-count", ".item-pill",
                ".story-pill", ".story-colhead", ".story-elabel"):
        assert cls in skip, f"{cls} must not term-link"
    assert ".story-desc" not in skip, "card prose participates in term-linking"


def test_the_story_stage_scrolls_inside_its_own_wrap_never_the_page() -> None:
    css = (VIEWER_DIR / "viewer.css").read_text()
    wrap = css[css.index("\n.story-wrap {"): css.index("}", css.index("\n.story-wrap {"))]
    assert "overflow-x: auto" in wrap
    stage = css[css.index(".story-stage {"): css.index("}", css.index(".story-stage {"))]
    assert "width: max-content" in stage


def test_the_wires_measure_cards_not_their_own_paths_and_ignore_transforms() -> None:
    """Two live-found bugs, pinned. (1) Wires and labels carry the same data attributes the hover
    machinery keys on, so a bare attribute query inside the edge loop matched the PREVIOUS edge's
    own path and drew NaN wires — the card maps must exist before any wire does. (2) A render can
    arrive mid drill-animation, whose ancestor transform skews getBoundingClientRect card by card;
    offsets read the settled layout regardless."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    assert "const actorEl = {}, featEl = {}, areaEl = {};" in bind
    assert bind.index("actorEl[el.dataset.sactor] = el") < bind.index("for (const e of (st.edges || []))")
    code = "\n".join(l for l in bind.splitlines() if not l.lstrip().startswith("//"))
    assert "el.offsetLeft" in code and "getBoundingClientRect" not in code
    # The glyph must out-specify the pane-wide `#diagram svg { width: 100% }` rule, or every actor
    # card draws a card-wide stick figure.
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "#diagram .story-glyph" in css


def test_enter_on_the_focused_name_does_not_also_pin_the_card() -> None:
    """The keydown listener sits on the card, so Enter on the focused NAME bubbles to it; the
    browser then fires the button's own click. Without the target check the pin, the panel write
    and the tree sync all ride along before the navigation."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    assert "if (ev.key === 'Enter' && ev.target === card) pick(ev);" in bind


def test_hover_never_takes_the_picture_away_from_a_pin() -> None:
    """A pin is the reader's explicit choice; a stray pass of the pointer over another card must
    not switch the shown arrows to the hovered card. Hover previews only while nothing is pinned."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    bind = _story_fn(js, "bindStoryDiagram")
    assert "card.addEventListener('mouseenter', () => { if (!selected) show(key, id); });" in bind


def test_a_feature_card_counts_its_joined_rules_and_hides_a_zero() -> None:
    """The rule join is a floor, not a total: "0 rules" would read as "decides nothing" when it can
    only mean "nothing joined", so zero draws no pill. Both counts are LABELS — a plain span with
    no handler behind it — so the card has exactly one door and it is the name."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    card = _story_fn(js, "storyFeatureCardHtml")
    assert "const nr = (f.rules || []).length;" in card
    assert "nr ? " in card and "countLabel(nr, 'rule')" in card
    assert "story-rulespill" not in js
    assert "story-rulespill" not in (VIEWER_DIR / "viewer.css").read_text()
    assert "<button" not in card.split("band:")[1], "no count pill is a button"
    bind = _story_fn(js, "bindStoryDiagram")
    assert "featsec-rules" not in bind, "no count opens a section of the feature page"
    assert "'feat-' + key" in js, "the feature page's sections keep their own keys"


# --- the URL carries the screen -----------------------------------------------------------------

def test_the_url_carries_every_field_that_names_a_screen_and_reads_it_back() -> None:
    """A shared link, and a reload, have to land on the screen you were on. So the part of the URL after
    `#` carries the screen: its kind, every field `stateKey` tells screens apart by, and the selection.

    The encoder READS STATE_FIELDS rather than listing the fields again. That list has silently dropped a
    field three times when it was maintained by hand (see the comment on `pushContentPoint`), so the
    round-trip below sets every field STATE_FIELDS names and demands all of them back: a field added
    there is carried by the URL with no second edit, and cannot be forgotten here."""
    every = "Object.fromEntries([['kind', 'rules']].concat(STATE_FIELDS.map((f) => [f, 'X_' + f])))"
    got = json.loads(_run_js_regions(
        [("let CMP = null;", "let CMP_INDEX = null;"),   # the comparison rider the encoder reads (none armed here)
         ("const STATE_FIELDS = [", "function stateKey(s) {"),
         ("const URL_WORD = {", "// `history` (the app's own stack) SHADOWS")],
        """
const trip = (s) => stateFromUrl('#' + urlFromState(s, false));
console.log(JSON.stringify({
  plain: trip({ kind: 'usecases' }),
  drill: trip({ kind: 'subsystem', sid: 'SUB_A' }),
  edge: trip({ kind: 'edge', a: 'C1', b: 'C2' }),
  sels: trip({ kind: 'container', sels: ['C1', 'C1>C2'] }),
  one: trip({ kind: 'container', sel: 'C9' }),
  every: trip(""" + every + """),
  odd: trip({ kind: 'actor', act: 'Owner & friend / other' }),
  word: urlFromState({ kind: 'usecases' }, false),
  internalName: stateFromUrl('#v=usecases'),
  nohash: stateFromUrl(''),
  junk: stateFromUrl('#nothing=here'),
}));
"""))
    # The LINK says `features`, the word on the tab; the kind keeps its internal name. That internal
    # name is NOT a link word: one word per screen, so a link cannot be read two ways.
    assert got["word"] == "v=features"
    assert got["internalName"] is None
    assert got["plain"] == {"kind": "usecases"}
    assert got["drill"] == {"kind": "subsystem", "sid": "SUB_A"}
    assert got["edge"] == {"kind": "edge", "a": "C1", "b": "C2"}
    assert got["sels"] == {"kind": "container", "sels": ["C1", "C1>C2"]}
    # A single requested key (a focus-drill / flow-step link) comes back as the general list.
    assert got["one"] == {"kind": "container", "sels": ["C9"]}
    # An actor's name is the state field, and names carry spaces, `&` and `/`.
    assert got["odd"] == {"kind": "actor", "act": "Owner & friend / other"}
    # No hash, and a hash naming no view, both mean "no screen" — the caller falls back to LANDING.
    assert got["nohash"] is None and got["junk"] is None
    js = (VIEWER_DIR / "viewer.js").read_text()
    fields = re.findall(r"'(\w+)'", js[js.index("const STATE_FIELDS = ["): js.index("function stateKey(s) {")])
    assert got["every"] == {"kind": "rules", **{f: "X_" + f for f in fields}}, got["every"]


def test_the_features_pages_pinned_card_is_part_of_where_you_are() -> None:
    """The Features page is HTML, so it has no scene and `mainScene` is null on it. What is selected
    there is the PINNED story card, and while the selection could only be read off a scene, the pin
    reached neither the URL nor the history point: a link lost it, a reload lost it, and a tab switch
    away and back lost it too.

    One function answers "what is selected on this screen" for both kinds of screen, so `captureViewState`
    and `urlFromState` cannot disagree about it — they did, which is how the pin fell through both.

    The pin rides the SAME `sel` field a diagram's selection uses, in the same `<what>:<id>` shape, so
    there is no second concept in the URL. The key half is checked against the three card kinds the page
    draws, so a hand-edited URL cannot ask for a card kind that does not exist."""
    got = json.loads(_run_js_region(
        "let storyPinNow = null;", "function urlFromState(s, live) {",
        """
console.log(JSON.stringify({
  feat: storyPinFromKey(storyPinKey({ key: 'sfeat', id: 'CAP2' })),
  actor: storyPinFromKey(storyPinKey({ key: 'sactor', id: 'R1' })),
  area: storyPinFromKey(storyPinKey({ key: 'sarea', id: 'SD3' })),
  colonInId: storyPinFromKey('sfeat:a:b'),
  none: storyPinKey(null),
  junkKind: storyPinFromKey('node:S2'),
  noColon: storyPinFromKey('sfeat'),
  empty: storyPinFromKey(''),
  undef: storyPinFromKey(undefined),
}));
"""))
    assert got["feat"] == {"key": "sfeat", "id": "CAP2"}
    assert got["actor"] == {"key": "sactor", "id": "R1"}
    assert got["area"] == {"key": "sarea", "id": "SD3"}
    # Only the FIRST colon splits, so an id carrying one survives the round trip.
    assert got["colonInId"] == {"key": "sfeat", "id": "a:b"}
    assert got["none"] is None
    # A scene's own key shape is not a story pin, and neither is anything malformed.
    assert got["junkKind"] is None and got["noColon"] is None
    assert got["empty"] is None and got["undef"] is None

    js = (VIEWER_DIR / "viewer.js").read_text()
    # ONE function answers the question, and both readers call it.
    assert js.count("function liveSelKeys() {") == 1
    assert "const sels = live\n    ? liveSelKeys()" in js
    assert "const keys = liveSelKeys();" in js and "history[hi].sels = keys.length ? keys : null;" in js
    # The pin is mirrored out of bindStoryDiagram's closure, and both ends restate the URL in place.
    bind = js[js.index("function bindStoryDiagram(root) {"): js.index("function renderOverview() {")]
    assert "storyPinNow = { key, id };" in bind and "storyPinNow = null;" in bind
    assert bind.count("refreshUrl();") == 2, "pin and unpin, and nothing else"
    # A render of any other screen leaves no pin behind…
    assert "storyPinNow = null;   // a pin belongs to the Features page" in js
    # …and arriving on Features restores the remembered one, without overriding a "show in context" pin.
    assert "if (!transient && !pendingStoryPin && storyDiagramDraws()) {" in js
    assert "pendingStoryPin = storyPinFromKey((s.sels || [])[0]);" in js


def test_back_and_forward_belong_to_the_browser_alone() -> None:
    """Two Back buttons that keep separate lists can disagree, and the one that is wrong is whichever
    the reader pressed. Every screen has a URL now, so the browser's own buttons already walk the map:
    the title bar's ◀ ▶ pair, its click handlers and its ⌘←/⌘→ binding are all gone, and `popstate` is
    the single way a step arrives.

    The pair was the weaker of the two. After a reload the app has no record of your path, so its arrows
    went grey while the browser's still worked and the trail still offered the way up. Its key binding
    was worse than useless: `preventDefault` ran before the guard, so at the map's first screen — which
    every reload lands on — it blocked the browser's identical shortcut and then did nothing. Measured
    in a browser: one ⌘← on a freshly reloaded drilled screen moved nothing at all.

    The internal stack stays the source of truth: each browser entry only names the point it stands for.
    An entry from an earlier page load carries an index that means nothing to this load's stack, so the
    match is on the load stamp too — without it, Back after a reload would jump to an unrelated screen."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    for gone in ("navback", "navfwd"):
        assert gone not in js and gone not in html and gone not in css, gone
    assert "#nav {" not in css, "the pair's own layout rule went with it"
    # No handler claims ⌘/⌥ + an arrow any more, so the browser's own shortcut reaches the browser.
    assert "e.metaKey || e.altKey" not in js
    keydown = js[js.index("document.addEventListener('keydown', (e) => {"):]
    keydown = keydown[: keydown.index("\n});") + 4]
    assert "back()" not in keydown and "fwd()" not in keydown
    # …while the flow player keeps its BARE arrows, which are a different binding on a different screen.
    assert "if (e.key === 'ArrowLeft') { e.preventDefault(); flowStepBy(-1); return; }" in keydown
    # popstate is the one way in, and it reads the entry's stamp before trusting its index.
    assert "const target = (st && st.load === URL_LOAD && typeof st.coy === 'number') ? st.coy : null;" in js
    assert js.count("window.addEventListener('popstate'") == 1


def test_a_dive_plays_only_between_a_container_and_what_it_holds() -> None:
    """The zoom-in / zoom-out dive says "you went down into this box" or "you came back up out of it".
    So it plays only between two views of ONE family of containers — the Subsystems overview and its
    cards, the Data overview and its cards, the Deployment overview and its process cards — and only
    when one view's container sits inside the other's. Everything else cuts straight, even when it lands
    on a container's card: a neighbour's card, the pair page, a component's page back to its subsystem.

    Before this, any page with no container of its own counted as "the overview": a jump from a
    component's page to its subsystem's card played the zoom-IN dive for a step back OUT."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    fam = js[js.index("function containerFamily(s) {"): js.index("\n}", js.index("function containerFamily(s) {"))]
    assert "if (s.kind === 'container' || s.kind === 'subsystem') return 'subsystem';" in fam
    assert "if (s.kind === 'domain' || s.kind === 'domsub') return 'subdomain';" in fam
    assert "if (s.kind === 'deployment' || s.kind === 'deploymentUnit') return 'process';" in fam
    assert "return null;" in fam, "a pair page, an element's page, a rule, a feature: no family, no dive"
    drive = js[js.index("function driveTransition(from, instant) {"): js.index("async function runDrill(")]
    assert "const related = !!fam && fam === containerFamily(to);" in drive
    assert "const inChain = related ? drillChain(fromF, toF) : null;" in drive   # down: into what the view holds
    assert "const isOut = related && !!fromF && !!drillChain(toF, fromF);" in drive   # up: out to what holds it
    assert "fromKind === 'subsystem' && to.kind === 'container'" not in drive, "the per-kind overview list is gone: the family says it"
    assert "render();  // lateral / unrelated navigation — no dive" in drive


def test_no_way_up_chooses_anything_for_you() -> None:
    """A climb out of a container used to arrive with the container you came out of selected — its
    card open, the rest dimmed, `sel=` in the link — so the reader "kept their place". That is a
    selection nobody made, and the browser's Back gave a different screen (as it was left) from the
    breadcrumb (marked). Every way up now returns the wider view with exactly the selection the reader
    had there before going down, or none: Back restores it from history, a fresh climb starts clean."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    assert "selectLeftContainer" not in js, "the marker is gone, with its callers"
    drive = js[js.index("function driveTransition(from, instant) {"): js.index("async function runDrill(")]
    assert "if (REDUCE_MOTION || !from) { render(); return; }" in drive
    assert "if (isOut) { runDrillOut(my).catch(" in drive
    out = js[js.index("async function runDrillOut(my) {"): js.index("\n}", js.index("async function runDrillOut(my) {"))]
    assert "selectNode" not in out and "selAdd" not in out
    # what a screen shows on return is what history saved for it, and nothing else
    # What a screen shows on return is what history saved for it, and nothing else — and the CAMERA is
    # no longer decided inside that branch, so a drill can centre what it opened without also choosing it.
    assert "restoreSelection(mainScene, s);" in js
    assert "if (!transient && pendingCenter && mainScene.nodeEls[pendingCenter]) pendingCenterId" in js
    assert "s.sel === 'node:' + pendingCenter" not in js, "centring is not gated on a selection"


def test_the_drill_zoom_survives_the_browser_buttons() -> None:
    """The zoom-in / zoom-out between two screens is decided by `driveTransition` from the screen being
    LEFT and the screen ARRIVING, and by nothing else — not by the history stack. So a step driven by the
    browser plays the same animation as the app's own button, as long as it passes the leaving screen.

    A jump of more than one screen has no meaningful zoom between its two ends, and the browser can make
    one (hold Back down, or pick from the history menu). Those cut straight there, on the same instant
    path a tab click already uses."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    pop = js[js.index("window.addEventListener('popstate'"): js.index("window.addEventListener('hashchange'")]
    assert "const from = history[hi];" in pop and "captureViewState();" in pop
    assert "const jump = Math.abs(target - hi);" in pop
    assert "driveTransition(from, jump > 1);" in pop
    # The animation reads only the two states, which is why it needs no change at all here.
    drive = js[js.index("function driveTransition(from, instant) {"): js.index("async function runDrill(")]
    assert "history" not in drive.replace("history[hi]", ""), "the zoom must not read the stack"


def test_a_selection_restates_the_url_and_never_grows_the_back_button() -> None:
    """Clicking a box is part of where you are, so it belongs in the URL. It is NOT a navigation: it
    makes no history point, and it must make no browser entry either, or the Back button would fill up
    with selections and stop meaning "the previous screen".

    One `pushState` exists in the whole file, inside `pushUrl`, which is called only where a history
    point is created. Everything else restates the entry in place."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert len(re.findall(r"window\.history\.pushState", js)) == 1, "pushState belongs to pushUrl alone"
    assert js.count("pushUrl();") == 2, "one per history point: go() and pushContentPoint()"
    sel = js[js.index("function selApply(scene) {"): js.index("function flowSuspendIfDeselected")]
    # `mainScene` IS the throwaway scene during a drill animation's intermediate flash, so the identity
    # test alone would pass there and write the destination's fields beside the intermediate's selection.
    assert "if (scene === mainScene && !renderingTransient) refreshUrl();" in sel
    # …and the one place every render ends, so a drill's own fields land in the URL once it has settled.
    chrome = js[js.index("function renderChrome(s) {"):]
    assert "if (s === history[hi]) refreshUrl();" in chrome[: chrome.index("\n}\n")]


def test_a_url_from_before_this_page_load_starts_a_fresh_stack() -> None:
    """A reload, or a link pasted into a tab already showing a map, lands on a browser entry the app has
    no record of. It starts a fresh stack at the screen the URL names rather than appending to the one it
    has: appending would leave the app's own Back button pointing at a screen the BROWSER would not go
    to, so the button would lie. With a fresh stack `hi` is 0, the button is honestly disabled, and the
    browser's own Back keeps working from there."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    adopt = js[js.index("function adoptUrlState(from) {"):]
    adopt = adopt[: adopt.index("\n}\n")]
    assert "const s = stateFromUrl(location.hash) || { kind: LANDING };" in adopt
    assert "history = [s];" in adopt and "hi = 0;" in adopt
    assert "driveTransition(from);" in adopt, "the zoom still plays: it reads the two screens only"
    # A hash typed into the address bar fires hashchange and never popstate, so it routes here too.
    assert "window.addEventListener('hashchange'" in js


def test_a_browser_step_arrives_once_not_twice() -> None:
    """A history step between two entries with different fragments fires popstate AND hashchange. Both
    handlers move the view, so without a guard every Back arrived twice: once as the step it is, and
    once as "a reader typed a new hash", which throws the internal stack away. Measured in a browser
    before the guard: one Back collapsed the stack to a single point, and the next Forward then showed
    the right screen under a stale index, so a later Back did nothing at all.

    The guard is the hash this file last wrote or claimed. Recomputing the expected hash instead does
    not work: at hashchange time the new screen has not rendered, so the recomputed hash still carries
    the previous screen's selection and never matches."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "let urlLast = null;" in js
    pop = js[js.index("window.addEventListener('popstate'"): js.index("window.addEventListener('hashchange'")]
    assert "urlLast = location.hash;" in pop, "popstate must claim the hash before hashchange sees it"
    hc = js[js.index("window.addEventListener('hashchange'"):]
    hc = hc[: hc.index("\n});") + 4]
    assert "if (location.hash === urlLast) return;" in hc
    # Every writer keeps it current, or the next reader edit would be mistaken for one of our own.
    for fn in ("function pushUrl() {", "function refreshUrl() {", "function adoptUrlState(from) {"):
        body = js[js.index(fn):]
        assert "urlLast = " in body[: body.index("\n}\n")], fn


def test_a_map_opened_as_a_plain_file_syncs_no_url() -> None:
    """`pushState` on a `file://` page is rejected by the browser, the same reason API_BASE is null
    there. So the whole mechanism is off for a map opened as a file, and Back / Forward step the internal
    stack directly, exactly as they did before. Every call is wrapped as well, so a browser that refuses
    anyway leaves the URL alone instead of half-syncing it."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "const URL_SYNC = /^https?:$/.test(location.protocol);" in js
    for fn in ("function pushUrl() {", "function refreshUrl() {"):
        body = js[js.index(fn):]
        body = body[: body.index("\n}\n")]
        assert "if (!URL_SYNC" in body and "try {" in body and "catch (_)" in body


def test_a_new_stack_gets_a_new_stamp_so_old_entries_stop_matching() -> None:
    """A browser entry names the internal point it stands for by INDEX, so it must also say which stack
    that index counts in. The stamp was keyed on the page LOAD, and that is not the same thing: a hash
    typed into the address bar reaches `adoptUrlState`, which throws the stack away and starts again at
    one point, all without a page load. The entries behind it kept a stamp that still matched, so
    popstate trusted their stale indexes.

    Measured by an adversarial review, in a real browser: after one address-bar paste, Back rendered the
    wrong screens AND `refreshUrl` wrote each wrong screen's hash over the entry, so the screens those
    entries named became unreachable by Back for the life of the tab.

    `adoptUrlState` now regenerates the stamp, so every older entry fails the test and falls through to
    `adoptUrlState` itself — which reads that entry's own hash, and is right by construction."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "let URL_LOAD = newStackStamp();" in js, "a generation, so it must be reassignable"
    assert "const URL_LOAD" not in js
    adopt = js[js.index("function adoptUrlState(from) {"):]
    adopt = adopt[: adopt.index("\n}\n")]
    assert "URL_LOAD = newStackStamp();" in adopt
    # …and the new stamp must be in force BEFORE the entry is restamped, or this entry keeps the old one.
    assert adopt.index("URL_LOAD = newStackStamp();") < adopt.index("window.history.replaceState")


def test_a_url_value_can_never_be_an_inherited_property_name() -> None:
    """Several screens use a state field as a lookup key into a plain object (`GRAPH.nodes[s.id]`,
    `FEAT_BY_ID[s.cap]`, `FOLD_NARRATIVE[s.kind]`, `scene.selectors[k]`). A fragment is text a reader can
    type, so a value like `constructor` or `__proto__` finds an INHERITED property: the lookup reads as a
    hit and the screen throws on it, or draws something that is not an element at all. An adversarial
    review reached four such throws, and `sel=constructor` even CALLED the inherited function.

    The boundary is the one place to stop it. `x in {}` is exactly the dangerous set, so one test in
    `stateFromUrl` retires the whole class — rather than a hasOwnProperty guard per lookup, added at four
    sites today and forgotten at the fifth tomorrow."""
    got = json.loads(_run_js_regions(
        [("const STATE_FIELDS = [", "function stateKey(s) {"),
         ("const URL_WORD = {", "// `history` (the app's own stack) SHADOWS")],
        """
console.log(JSON.stringify({
  proto: stateFromUrl('#v=__proto__'),
  ctor: stateFromUrl('#v=constructor'),
  ctorField: stateFromUrl('#v=capability&cap=constructor'),
  ctorSel: stateFromUrl('#v=container&sel=constructor'),
  toStr: stateFromUrl('#v=element&id=toString'),
  hasOwn: stateFromUrl('#v=element&id=hasOwnProperty'),
  ok: stateFromUrl('#v=element&id=C1'),
  mixed: stateFromUrl('#v=container&sel=__proto__&sel=node:S1'),
}));
"""))
    # A kind naming an inherited member is not a kind, so the whole state is refused and the caller
    # falls back to the landing view.
    assert got["proto"] is None and got["ctor"] is None
    # A FIELD naming one is dropped, leaving a state that is still a legal screen.
    assert got["ctorField"] == {"kind": "capability"}
    assert got["toStr"] == {"kind": "element"} and got["hasOwn"] == {"kind": "element"}
    # …and so is a selection key, without losing the good keys beside it.
    assert got["ctorSel"] == {"kind": "container"}
    assert got["mixed"] == {"kind": "container", "sels": ["node:S1"]}
    # An ordinary id is untouched.
    assert got["ok"] == {"kind": "element", "id": "C1"}


def test_every_screen_degrades_and_none_of_them_throws() -> None:
    """The safety net wrapped the mermaid step alone, which was enough while every state was built from
    live data. A URL can name anything now, and a throw inside a TEXT renderer aborted the render before
    `renderChrome`: the page kept the previous screen's group tab, view tab, breadcrumb and question over
    blank content, and on the boot path it had no trail at all. An adversarial review reached that state
    from four fragments, one of them just `#v=data&store=%29`.

    The whole body is inside the net now. The stale-render check is in the net too, so a throw from an
    abandoned render cannot paint over the screen a newer one already drew."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    wrap = js[js.index("async function render(sArg, transient) {"):
              js.index("async function renderView(sArg, transient, seq) {")]
    assert "await renderView(sArg, transient, seq);" in wrap
    assert "} catch (err) {" in wrap
    assert "if (seq !== renderSeq) return;" in wrap, "a stale render must not paint over a newer one"
    assert "This view could not be rendered." in wrap
    assert "renderChrome(s);" in wrap, "the trail has to survive, or nothing says where you are"
    # `seq` is minted once, by the wrapper, and passed down — two counters would break the stale check.
    assert js.count("const seq = ++renderSeq;") == 1
    # An id straight from a URL cannot hold every character an id SELECTOR can, so the lookup that used
    # `'#' + id` (and threw on a bracket or a paren) is an attribute match through CSS.escape.
    assert "diagram.querySelector('#' + paneId(" not in js
    assert 'diagram.querySelector(`[id="${CSS.escape(paneId(s.store))}"]`)' in js


def test_a_stale_link_names_no_internal_id_on_screen() -> None:
    """The viewer shows element NAMES; ids are internal and belong in the markup. Every id-to-name lookup
    fell back to the id itself, which was unreachable while every state came from live data. A stale link
    — one built against a map that has since been rebuilt — reaches it, and an adversarial review found 8
    fragments that printed a raw id straight into the breadcrumb.

    One phrase for the miss, in one constant, so the trail, a card and a tooltip cannot describe the same
    miss differently. `stateTitle` had four hand-rolled copies of the same lookup, each with the id as its
    fallback; they are gone in favour of `elName`."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "const UNKNOWN_NAME = 'Not in this map';" in js
    assert "function elName(id) { return (GRAPH.nodes[id] || {}).name || UNKNOWN_NAME; }" in js
    assert "|| (GRAPH.nodes[fid] || {}).name || UNKNOWN_NAME;" in js          # featureName
    assert "function roleName(rid) { return (ROLE_BY_ID[rid] || {}).name || UNKNOWN_NAME; }" in js
    assert "return b ? b.name : UNKNOWN_NAME; }" in js                        # bucketFoldName
    title = js[js.index("function stateTitle(s) {"): js.index("function groupChain(")]
    assert "GRAPH.nodes[id] ? GRAPH.nodes[id].name : id" not in title, "no hand-rolled copy is left"
    for line in ("if (s.kind === 'domsub') return elName(s.sd);",
                 "if (s.kind === 'usecase') return elName(s.uc);",
                 "if (s.kind === 'subsystem') return elName(s.sid);",
                 "if (s.kind === 'depedge') return elName(s.a) + ' → ' + elName(s.b);",
                 "if (s.kind === 'bridge') return elName(s.sid) + ' → ' + elName(s.sd);"):
        assert line in title, line
    assert "const nm = featureName(s.cap);" in title


def test_a_refused_push_keeps_the_url_and_the_screen_agreeing() -> None:
    """`pushState` can be refused: a browser rate-limits it, a sandboxed frame rejects it outright. `hi`
    has already advanced by then, so returning empty-handed left the browser's newest entry naming the
    point BEFORE this one, and Back silently skipped a screen. With the title bar's own arrows gone there
    is nothing to fall back on.

    Restating the current entry instead keeps the URL and the screen agreeing about where you are. It
    costs the one point that got no entry of its own, which is the smaller wrong."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    push = js[js.index("function pushUrl() {"):]
    push = push[: push.index("\n}\n")]
    assert "try { window.history.replaceState(stamp, '', h); } catch (_e) { return; }" in push
    assert push.index("catch (_)") < push.index("urlStarted = true;")
    """The screen rides in the part of the URL after `#`, which a browser never sends to the server. So
    serve.py keeps its `/coyomap/<slug>/` routes and needs no change to make a link shareable."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "'#' + urlFromState(history[hi], false)" in js
    assert "'#' + urlFromState(history[hi], true)" in js
    serve = (VIEWER_DIR / "serve.py").read_text()
    assert "urlFromState" not in serve and "coy=" not in serve


def test_the_drawing_s_floor_is_the_same_number_in_both_files() -> None:
    """The height the drawing is never allowed to go below is written twice: as a CSS rule that
    enforces it, and as a JS constant used as the stand-in size when a map has to be built before the
    drawing has room. They mean the same thing, and if they drift the JS one silently stops matching
    what the reader actually gets. Nothing but this keeps them in step."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    in_js = re.search(r"const STAGE_FLOOR_PX = (\d+);", js)
    # ANCHORED to #diagwrap's OWN rule. The shared board rule's selector list ends in `#diagwrap {`
    # too, and a `min-height` added there would silently make this read the wrong number.
    in_css = re.search(r"\n#diagwrap \{[^}]*min-height: (\d+)px", css, re.S)
    assert in_js, "STAGE_FLOOR_PX is gone from viewer.js"
    assert in_css, "#diagwrap lost its min-height in viewer.css"
    assert in_js.group(1) == in_css.group(1), (in_js.group(1), in_css.group(1))


def test_a_record_inside_another_one_is_used_wherever_its_holder_is():
    """The panel and the check must not disagree about one record. `validate` counts an embedded
    record as storied when its container is reached — a record lives in its holder's row, so a story
    that writes the holder writes the piece — and before this the panel said "No traced use case
    reaches it" on exactly those records."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    fn = js[js.index("function tracedUseCasesFor(id, seen) {"):
            js.index("\n}", js.index("function tracedUseCasesFor(id, seen) {"))]
    assert "GRAPH.record_parents" in fn, "the holder chain must be walked, not just the node itself"
    assert "guard.has(id)" in fn, "containment is authored; a cycle must not hang the panel"


def test_the_inspector_finds_an_arrow_through_its_HIT_PATH():
    """Every arrow answered "nothing under the cursor is an element of the stored map", on every
    diagram, for every click.

    `attachEdgeHandlers` lays a wide transparent clone over each visible edge and STRIPS its class
    and id — so what a click lands on is not a `.flowchart-link`, and it is a SIBLING of the one
    that is, while the resolver climbs ANCESTORS. Nitsan reported it as "I can't inspect a link".

    Matched on the HANDLE'S SHAPE, not on a type marker: a first fix keyed on `data-et="edge"`,
    which the hit path carries and the label's group does not, so the line answered and its own
    number still did not."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    at = js[js.index("function inspAt(el) {"):js.index("function inspEdge(pathEl)")]
    assert "INSP_ARROW_RE" in at, "the arrow is recognised by its handle, not by a class"
    assert "data-id" in at.split("INSP_ARROW_RE")[0][-200:], "the clone's handle is read first"
    miss = js[js.index("function inspMiss(target) {"):js.index("function inspHandles(target)")]
    assert "INSP_ARROW_RE" in miss, \
        "the miss message must recognise an arrow the same way, or it never explains one"


def test_a_use_case_map_arrow_resolves_to_its_WALK_STEPS():
    """An arrow there is not a backbone `edges[]` row — its ends can be an actor or a surface, which
    no edge has. It stands for the walk steps between those two boxes, and those are stored.

    It must call `flowMapSteps`, never re-implement it: a first version compared the arrow's ends to
    the narration's directly and always missed, because a box id is `FA0` and the narration holds
    that actor's NAME."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    fn = js[js.index("function inspFlowArrow(el, handle) {"):js.index("// One step of a walk.")]
    assert "flowMapSteps(uc, m[1], m[2])" in fn, "the picture's own lookup, not a second one"
    assert "isFlowState(here)" in fn, \
        "guarded to the use case map: a stale uc would answer for a backbone arrow"
    assert "parts.length === 1) return parts[0]" in fn, \
        "one step answers as itself; several answer as all of them"
    # EVERY step an arrow carries, not the first with a count. A reader asking what an arrow is
    # wants what it is — and the second step is often in a different container entirely, so the
    # first is not even a representative sample of it.
    assert "parts: parts.map(" in fn, "every step, not the first with a count"


def test_the_popup_renders_EVERY_record_an_arrow_carries():
    """`note` used to render only when there was NO record, and the multi-step case then showed the
    first step with a line saying there were more — the inspector answering "here is some of it".

    Each part gets its OWN path line, and the head loses its: printing the first part's path twice
    read as if it were the arrow's own record."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    css = (VIEWER_DIR / "viewer.css").read_text(encoding="utf-8")
    body = js[js.index("inspPop.innerHTML = `<div class=\"insp-head\">"):]
    head = body[:body.index("inspPop.hidden = false;")]
    assert "insp-note" in head and head.index("insp-note") < head.index("insp-json"), \
        "the note leads the records it qualifies"
    assert "hit.parts.map(" in head, "every part is rendered, not just the first"
    assert "insp-subpath" in head and "insp-sep" in head, \
        "each part under its own path, ruled off from the next"
    assert "hit.parts && hit.parts.length ? ''" in head, "and the head drops its duplicate path"
    for cls in (".insp-note", ".insp-sep", ".insp-subpath"):
        assert cls in css, f"{cls} is styled"


def test_the_inspector_path_is_a_TRAIL_you_can_walk():
    """`project-map.json › flows[7].steps[7]` reads like an address and was inert text. Every prefix
    of it names a real value in the file, so each segment opens what it names: `flows` the list,
    `[7]` that walk, `steps` its steps.

    An INDEX, never the full JSON, for a list or the whole map — `flows` alone runs to thousands of
    lines and the map to tens of thousands, so a naive drill would hang the popup on the first
    click."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    css = (VIEWER_DIR / "viewer.css").read_text(encoding="utf-8")
    trail = js[js.index("function inspTrailHtml(path, cls) {"):js.index("function inspGoPath(prefix)")]
    assert 'data-path=""' in trail, "the root is a segment too — it opens the whole map"
    assert "inspPathParts(path)" in trail, "one parser, shared with the walker"
    go = js[js.index("function inspGoPath(prefix) {"):js.index("function inspOpen(hit)")]
    assert "Array.isArray(v) || !prefix" in go, "a list and the root open as an index"
    assert "index: v" in go and "rec: v" in go, "a list carries `index`, a record carries `rec`"
    body = js[js.index("inspPop.innerHTML = `<div class=\"insp-head\">"):]
    head = body[:body.index("inspPop.hidden = false;")]
    assert "inspIndexHtml(hit.path, hit.index)" in head, "and the index is rendered before the JSON branch"
    assert "'.insp-seg, .insp-row'" in js, "a path segment and an index row share one handler"
    for cls in (".insp-seg", ".insp-index", ".insp-row", ".insp-row-lead"):
        assert cls in css, f"{cls} is styled"


def test_an_index_row_is_named_the_way_the_map_names_it():
    """`[7]` alone is unreadable. A row carries the record's own id and title, so a list of 32 walks
    reads as the walks rather than as 32 numbers."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    fn = js[js.index("function inspRowLabel(x) {"):js.index("function inspVal(v, pad)")]
    for field in ("x.id", "x.uc", "x.name", "x.title", "x.term"):
        assert field in fn, f"{field} is one of the names a row can take"


def test_the_path_walker_and_the_path_parser_read_the_SAME_shape():
    """Two readings of one grammar is how a trail comes to point somewhere the walker cannot reach."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    assert js.count("INSP_SEG_RE") >= 3, "one regex, used by the parser, the walker and the kind label"
    walk = js[js.index("function inspWalk(prefix) {"):js.index("function inspPathKind(prefix, v)")]
    assert "INSP_SEG_RE.lastIndex = 0" in walk, \
        "a /g regex keeps its cursor between calls; not resetting it makes every other walk miss"


def test_a_path_that_names_nothing_is_not_drawn_as_a_trail():
    """A miss carries `—`, which parses to no segments. Walking it printed `project-map.json ›` and
    then silence, so the panel read as a path that got CUT OFF rather than one that does not exist.
    Caught by a browser test asserting the literal `—`, not by the source tests here."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    fn = js[js.index("function inspTrailHtml(path, cls) {"):js.index("function inspGoPath(prefix)")]
    assert "if (!parts.length) return" in fn, "no segments, no trail — print the text as it stands"


def test_a_step_that_runs_a_shared_walk_is_drawn_to_that_walk_s_box() -> None:
    """A use case map draws a shared sub-use case as ONE box and never its insides, so the step that runs it goes
    to that box — not to its own `dst`, which names a component inside the walk that this map does not
    draw at all. Both consumers must agree: the arrow's own lookup, and the step player's.

    Get it wrong and the step lights nothing and the player scrolls to a box that is not on screen."""
    snippet = """
globalThis.FLOW_ACTORS = { UC1: [] };
globalThis.FLOWS_NARR = { UC1: [
  { srcId: 'C1', dstId: 'C2', src: 'Viewer', dst: 'Store' },
  { srcId: 'C1', dstId: 'C9', src: 'Viewer', dst: 'Inside', sf: 'SF1', sfName: 'N', sfSteps: 6 },
  { srcId: 'C1', dstId: 'C2', src: 'Viewer', dst: 'Store' },
] };
console.log(JSON.stringify({
  onWalkBox:  flowMapSteps('UC1', 'C1', 'SF1').map((x) => x.i),
  onPlainPair: flowMapSteps('UC1', 'C1', 'C2').map((x) => x.i),
  notItsOwnDst: flowMapSteps('UC1', 'C1', 'C9').map((x) => x.i),
  arrowOfRefStep: flowMapStepArrow('UC1', 1, FLOWS_NARR.UC1[1]),
  arrowOfPlainStep: flowMapStepArrow('UC1', 0, FLOWS_NARR.UC1[0]),
  boxes: flowMapSubflows('UC1').map((st) => st.sf),
}));
"""
    got = json.loads(_run_js_region("function flowMapToken(uc, mid) {",
                                    "function showFlowPair(uc, a, b) {", snippet))
    assert got["onWalkBox"] == [1]
    assert got["onPlainPair"] == [0, 2]      # the walk's own steps, and only those
    assert got["notItsOwnDst"] == []         # nothing is drawn to the component inside the walk
    assert got["arrowOfRefStep"] == ["C1", "SF1"]
    assert got["arrowOfPlainStep"] == ["C1", "C2"]
    assert got["boxes"] == ["SF1"]


def test_the_same_shared_walk_run_twice_is_one_box_carrying_both_numbers() -> None:
    """One shared sub-use case is one box on the map, however many times the walk runs it — the map draws one box
    per thing, and the arrow's label lists every step riding it, exactly as it does for any other pair."""
    snippet = """
globalThis.FLOW_ACTORS = { UC1: [] };
globalThis.FLOWS_NARR = { UC1: [
  { srcId: 'C1', dstId: 'C9', src: 'A', dst: 'X', sf: 'SF1', sfName: 'N' },
  { srcId: 'C1', dstId: 'C2', src: 'A', dst: 'B' },
  { srcId: 'C1', dstId: 'C9', src: 'A', dst: 'X', sf: 'SF1', sfName: 'N' },
] };
console.log(JSON.stringify({
  both: flowMapSteps('UC1', 'C1', 'SF1').map((x) => x.i),
  boxes: flowMapSubflows('UC1').map((st) => st.sf),
}));
"""
    got = json.loads(_run_js_region("function flowMapToken(uc, mid) {",
                                    "function showFlowPair(uc, a, b) {", snippet))
    assert got["both"] == [0, 2] and got["boxes"] == ["SF1"]


def test_one_function_says_which_arrow_a_step_is_on() -> None:
    """`flowMapStepArrow` is the ONE door from a step to the map arrow that carries it, because a use-case
    map no longer draws every step's own endpoints — a step inside a collapsed shared sub-use case rides the arrow
    into that walk's box instead. Anything re-deriving the pair from `st.srcId`/`st.dstId` disagrees with
    the drawing: it glows nothing, or it scrolls to a box that is not there.

    Both regressions were real. The step player lit no arrow for a collapsed step, and `flowReveal`
    scrolled to endpoints with nothing on screen. Pinning the call sites is what keeps the next caller
    from re-deriving it a third time."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    callers = [ln.strip() for ln in js.splitlines()
               if "flowMapBoxId(" in ln and not ln.startswith("function flowMapBoxId")]
    # The two that are NOT re-derivations: a shared sub-use case's box shows the run behind it, on click and on
    # hover, and both need the box the run was called from.
    assert callers == ["return [flowMapBoxId(uc, st.srcId, st.src),",
                       "st.sf || flowMapBoxId(uc, st.dstId, st.dst)];",
                       "show: () => showFlowPair(uc, flowMapBoxId(uc, ref.srcId, ref.src), sid) });",
                       "previewOnHover(scene, el, () => showFlowPair(uc, flowMapBoxId(uc, ref.srcId, "
                       "ref.src), sid));"], \
        f"call flowMapStepArrow instead of re-deriving the pair: {callers}"


def test_only_an_actor_s_card_gets_an_actor_s_words() -> None:
    """`isMachineActor` answers "anything that is not a person", which is right INSIDE the actor
    vocabulary and wrong as a test of what kind of ELEMENT a card is about. Asked about element kinds it
    called a component, an entity, a door and a dependency machine actors, and two things followed for
    every one of them — 735 cards across the two live maps:

      * a second pill in the SERVICE-ACTOR colour repeating the card's own type word ("component"
        twice), or, for kinds the actor table has no English for, printing the CODE word (`dep`,
        `usecase`) — the one thing that table exists to prevent;
      * the description run through the actor sentence and returned prefixed "Goal:", so a component's
        purpose read as an actor's wants.

    `elementLabel` is the one table that says which kinds read as "actor", so it decides."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    fn = js[js.index("function cardFacts(id) {"):js.index("\n}", js.index("function cardFacts(id) {"))]
    assert "const isActor = elementLabel(n.kind) === 'actor';" in fn
    assert "if (isActor) desc = wantsSentence(desc);" in fn
    assert "if (isActor) for (const p of actorSidePills(" in fn
    # …and the loose predicate is never the one that decides it
    assert "isMachineActor(n.kind)) desc" not in fn


def test_every_box_wears_one_glyph_from_one_function() -> None:
    """FIVE glyph functions drew the marks on this viewer, and two of them drew the SAME stick figure
    in two hands — the code said so in its own comment. `itemGlyphSvg` is the one that is left, and
    every box on every picture reads it.

    TWO PAIRS, and the pairing is the meaning: one gear is a component and two are a subsystem, one
    class box is a record and two are a data area. "One, and several" reads without a caption.

    THE GLYPH IS SIZED TWICE, AND BOTH ARE NEEDED. `#diagram svg { width: 100% }` sizes the drawing
    canvas and reaches every inline SVG under it, so an unscoped rule loses inside a diagram and a 17px
    mark renders 400px tall. But a box is MEASURED off-screen, outside `#diagram`, where only the
    unscoped rule applies. The two must agree or every box is laid out at one size and drawn at
    another."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    assert "function itemGlyphSvg(k, ikind) {" in js
    assert "IFACE_GLYPH_D[IFACE_GLYPH[ikind] || 'doc']" in js   # ONE door table, shared with Interfaces
    mark = js[js.index("function itemMarkD(k, fill) {"):js.index("function itemGlyphSvg(")]
    assert "itemCogPath(9, 9, 7.4, 5.2, 6)" in mark              # a component: one gear
    assert mark.count("itemCogPath(") == 3                       # …and a subsystem: two of them
    assert "if (k === 'entity') return" in mark and "const box = (x, y) =>" in mark  # one box, and two
    css = (VIEWER_DIR / "viewer.css").read_text(encoding="utf-8")
    assert "\n.ibox-gly { width: 17px; height: 17px;" in css     # for the off-screen measurement
    assert "#diagram .ibox-gly { width: 17px; height: 17px; }" in css   # …and inside a diagram
    assert "#diagram .ibox-figure .ibox-gly { width: 46px; height: 46px; }" in css


def test_the_first_walk_a_reader_opens_shows_them_the_code_column() -> None:
    """A use case map is the one screen whose every box and arrow points at a place in the code, and the
    rail that opens the column is a thin strip on the far edge. Once, remembered, and never argued with
    after the reader closes it.

    DECIDED IN `syncCodePane`, not at the navigation: `SERVED` is settled by a fetch still in flight at
    boot, and syncCodePane is the one place that runs again once it lands. Deciding it at the navigation
    left the column shut on the very first walk — the one arrival the rule exists for."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    fn = js[js.index("function openCodeOnFirstFlow(s) {"):
            js.index("\n}", js.index("function openCodeOnFirstFlow(s) {"))]
    assert "if (!SERVED || !isFlowState(s)) return;" in fn        # a walk, on a served map
    # ARRIVING IS THE EVENT, open or not. Returning early on an already-open column left the flag
    # unset, so the reader's × — which comes back through here — met a shut column and an unset flag
    # and forced it open again. The × was dead for anyone who had ever left the column open.
    assert "if (!codePaneOpen()) setCodeOpen(true);" in fn
    assert "lsGet(LS.flowCode) === '1'" in fn and "lsSet(LS.flowCode, '1')" in fn
    sync = js[js.index("function syncCodePane(s) {"):js.index("\n}", js.index("function syncCodePane(s) {"))]
    assert "openCodeOnFirstFlow(s);" in sync, "decided where SERVED is re-read, not at the navigation"


def test_the_name_is_the_words_and_every_box_s_name_opens_a_page() -> None:
    """A box's LABEL is not its name. An item box carries a glyph, a type word, a sentence and a band of
    chips beside it; targeting the label made the whole box a link and left nothing to select on. The
    NAME is its own control, and that control is what a click and the hover underline read.

    TWO CLASSES, ONE QUESTION. `.ibox-name` is the item box's name; `.cyname` is what the generators
    still wrap a name in on the pictures that have not moved onto the item box yet. `nameClick` is the
    one place that asks, so neither can drift into a second answer.

    And all three kinds open something: an element opens its own page, an actor theirs, a shared sub-use case
    its own screen. Before this an actor's box could not be opened from a map at all."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    assert "t.closest('.ibox-name, .cyname')" in js
    assert "if (nameClick(ev)) { drillInto(id); return; }" in js                    # an element
    assert "if (nameClick(ev)) { go({ kind: 'actor', act: a.name }); return; }" in js  # an actor
    assert "if (open && (nameClick(ev) || isDrillClick(ev)))" in js                 # a shared sub-use case
    # THE NAME IS A BUTTON, so it is a keyboard stop and it says on hover that it is a door.
    assert '`<button type="button" class="${ncls}"' in js
    css = (VIEWER_DIR / "viewer.css").read_text(encoding="utf-8")
    assert ".ibox-name:hover { text-decoration: underline;" in css
    assert ".ibox-name:focus-visible {" in css


def test_the_subsystems_pictures_take_the_data_pictures_gestures() -> None:
    """The Subsystems overview, a subsystem's card and a pair of subsystems offer the same three gestures
    the Data pictures do: rest on a box or an arrow to read its card, click to pin it, a box's NAME to
    open it. No corner icon on a box, and no ⌥ / double-click drill on an arrow: the arrow card's title
    is the one door to the pair's page."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    # the overview asks bindGroupContainer for the resting-pointer card, exactly as the Data overview does
    assert ("function bindContainer() { bindGroupContainer((id) => ({ kind: 'subsystem', sid: id }), "
            "bindContainerEdge, null, { hover: true }); }") in js
    assert ("function bindDomainContainer() { bindGroupContainer((id) => ({ kind: 'domsub', sd: id }), "
            "bindDomainContainerEdge, null, { hover: true }); }") in js
    # an inter-subsystem arrow: hover card, no drill gesture, the card's title leads to the pair's page
    edge = js[js.index("function bindContainerEdge(scene, p, label, a, b, focusE) {"):
              js.index("\n}", js.index("function bindContainerEdge(scene, p, label, a, b, focusE) {"))]
    assert "{ hover: true }" in edge and "onDrill" not in edge and "actionFn" not in edge
    card = js[js.index("function showContainerEdge(a, b, drawn) {"):
              js.index("\n}", js.index("function showContainerEdge(a, b, drawn) {"))]
    assert "drill: pairPageDrill('edge', 'component', a, b, drawn)," in card
    # …and the Data arrow card asks the SAME rule, so the two families cannot drift apart
    dcard = js[js.index("function showDomainContainerEdge(a, b, drawn) {"):
               js.index("\n}", js.index("function showDomainContainerEdge(a, b, drawn) {"))]
    assert "drill: pairPageDrill('domedge', 'entity', a, b, drawn)," in dcard
    drill = js[js.index("function pairPageDrill(kind, leaf, a, b, drawn) {"):
               js.index("\n}", js.index("function pairPageDrill(kind, leaf, a, b, drawn) {"))]
    # NO WAY IN CHOOSES ANYTHING FOR YOU EITHER. A member's cross arrow used to land with that member
    # SELECTED — a ring, a card over the drawing, and a hint about faded boxes on a page with none —
    # which is the selection nobody made that the climb out already stopped drawing. It CENTRES the
    # member and chooses nothing; a box↔box arrow names no member and centres nothing.
    assert "return member ? { kind, a, b, center: member } : { kind, a, b };" in drill
    assert "sel: 'node:' + member" not in js
    assert "efocus" not in js, "the field that promised a focus nothing read is gone"
    assert "containerEdgeDrill" not in js and "domainEdgeDrill" not in js   # the twins are gone
    # …and the drill handler turns the centre hint into the one-shot pendingCenter, off the state.
    # ONE handler, delegated from the card AND the page: it was written on the card alone, and the first
    # page to draw a drill button (a step's "Also between these two") looked live and went nowhere.
    handler = js[js.index("function drillFrom(ev) {"): js.index("\n}", js.index("function drillFrom(ev) {"))]
    assert "PANEL_HOST.addEventListener('click', drillFrom);" in js
    assert "diagram.addEventListener('click', drillFrom);" in js
    assert "const center = to.center; delete to.center;" in handler
    assert "if (center) pendingCenter = center;" in handler
    assert "selClear(mainScene); mainScene.selectors[to.sel]();" in handler   # already on the page: select in place
    # every box on a card or a pair: one binder, hover card, the name opens, a container drills
    boxes = js[js.index("function bindStructureBoxes() {"):
               js.index("\n}", js.index("function bindStructureBoxes() {"))]
    assert "previewOnHover(mainScene, el, () => showNode(id));" in boxes
    assert "if (nameClick(ev) || (box && isDrillClick(ev))) { drillInto(id); return; }" in boxes
    for fn in ("function bindSubsystem(sid) {", "function bindEdgePair(a, b) {"):
        body = js[js.index(fn): js.index("\n}", js.index(fn))]
        assert "bindStructureBoxes();" in body, fn
        assert "Object.assign({}, r.opts || {}, { hover: true })" in body, fn   # a member arrow's card on hover too
    assert "{ kind: 'bridge', sid: sid, sd: sd }, true);" in js   # the bridge arrow in a subsystem card, hover too
    # no corner icons on a structure picture, as on a walk and a Data picture
    assert ("function isStructurePicture(s) { return !!(s && (s.kind === 'container' || s.kind === 'subsystem' "
            "|| s.kind === 'edge')); }") in js


def test_a_container_box_border_holds_its_own_on_a_frame_of_its_colour() -> None:
    """A collapsed subsystem (or subdomain) box has its kind's deep fill, and inside a drilled frame of
    the same kind it sits on that very colour: at the members' pale border mix its dashed line vanished
    into the frame. Container tints are the ones carrying a stroke width, and they take a darker mix —
    still lighter and duller than the one hover/picked blue, so the three states keep their weights."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    assert "const MEMBER_BORDER_MIX = 34;" in js and "const CONTAINER_BORDER_MIX = 65;" in js
    fn = js[js.index("function injectItemTintCss() {"): js.index("\n}", js.index("function injectItemTintCss() {"))]
    assert "const mix = t.strokeWidth ? CONTAINER_BORDER_MIX : MEMBER_BORDER_MIX;" in fn
    assert "color-mix(in srgb, ${t.stroke} ${mix}%, #fff)" in fn
    # the discriminator is real: only the container styles carry a stroke width in the tint table
    from coyomap.viewer import gen_viewer
    with_width = {k for k, v in gen_viewer.ELEMENT_TINT.items() if v.get("strokeWidth")}
    assert {"subsystem", "subdomain"} <= with_width
    assert not ({"component", "entity", "dep", "interface"} & with_width)


def test_a_pointer_that_did_not_move_is_not_hovering() -> None:
    """A new drawing lands under a cursor that may be sitting on one of its boxes or arrows — after a
    drill, a link, the browser's Back — and the browser reports that as an entry: the card opened and
    the border lit for a thing nobody pointed at. Until the pointer MOVES, a hover on the new drawing
    is not a hover; the enters denied meanwhile are delivered on the move, so the reader need not
    leave the box and come back. Movement, not events: a re-reported cursor at the same place does
    not count."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    css = (VIEWER_DIR / "viewer.css").read_text(encoding="utf-8")
    scene = js[js.index("function makeScene(root, defaultPanel) {"): js.index("\n}", js.index("function makeScene(root, defaultPanel) {"))]
    assert "holdPointer();" in scene, "every new drawing holds the pointer"
    hold = js[js.index("function holdPointer() {"): js.index("\n}", js.index("function holdPointer() {"))]
    assert "pointerFresh = false;" in hold and "cursorHeldAt = pointerAt ? { ...pointerAt } : { x: NaN, y: NaN };" in hold
    assert "diagram.classList.add('pointer-held')" in hold
    mv = js[js.index("document.addEventListener('mousemove', (e) => {\n  const still = cursorHeldAt"):]
    mv = mv[: mv.index("}, true);")]
    assert "Math.abs(e.clientX - cursorHeldAt.x) < POINTER_MOVE_PX" in mv, "a move is a change of place, not an event"
    assert "if (!pointerFresh && !still) releasePointer();" in mv
    # the three hovers read the gate, keep the denied enter, and drop it on a leave
    for fn, enter in (("function previewOnHover(scene, els, show, anchor) {", "whenPointerMoves(enter)"),
                      ("function bindHoverGlow(scene, el, id) {", "whenPointerMoves(on)"),
                      ("function attachEdgeHandlers(p, label, onClick, hoverOn, hoverOff, onDrill, actionFn) {", "whenPointerMoves(on)")):
        body = js[js.index(fn): js.index("\n}", js.index(fn))]
        assert "if (!pointerFresh) { " + enter + "; return; }" in body, fn
        assert "forgetPointerMove(" in body, fn
    rel = js[js.index("function releasePointer() {"): js.index("\n}", js.index("function releasePointer() {"))]
    assert "for (const fn of pendingHovers.splice(0)) fn();" in rel, "the move delivers the hover the box is owed"
    # …and the stylesheet's own :hover reads the same gate, through the resting-colour variable
    assert "--ibox-rest: #dcdff0; border: 1.5px solid var(--ibox-rest);" in css
    assert "#diagram.pointer-held .ibox:hover:not(.ibox-picked) { border-color: var(--ibox-rest); }" in css
    assert "#diagram.pointer-held .ibox-name:hover, #diagram.pointer-held .cyname:hover { text-decoration: none; }" in css
    assert "{--ibox-rest:color-mix(in srgb, ${t.stroke} ${mix}%, #fff)}" in js, "the per-kind resting line is the variable"


def test_a_walk_draws_no_corner_icons() -> None:
    """The icon floating in a box's corner was the older way of saying "this opens something", in a
    language no other screen speaks. The name says it now, and it says it the way a card's title does."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    fn = js[js.index("function decorateActionIcons(scene, s) {"):
            js.index("\n}", js.index("function decorateActionIcons(scene, s) {"))]
    assert "if (isFlowState(s) || isDataPicture(s) || isStructurePicture(s) || (s && PAIR_PAGE[s.kind])) return;" in fn
    assert "addActionIcon(el, sid, open)" not in js, "the shared sub-use case's box lost its icon too"
    # The two picture tests each name ONE TAB's drawings, so the bridge — a subsystem crossed with a
    # subdomain — was in neither and kept the icon after every page around it had let it go.
    # `PAIR_PAGE` names every pair page, so a fourth kind cannot fall through the same gap.


def test_hovering_a_box_shows_its_card_and_leaving_puts_back_what_was_there() -> None:
    """Clicking every box to find out what it is, is the older way. A short delay so crossing a box on
    the way somewhere else flashes nothing, and leaving restores the selection — so a card you PINNED
    with a click survives the pointer passing over its neighbours.

    The LINE follows the pointer too: it would otherwise point at the last thing clicked while the card
    described something else."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    fn = js[js.index("function previewOnHover(scene, els, show, anchor) {"):
            js.index("\n}", js.index("function previewOnHover(scene, els, show, anchor) {"))]
    assert "HOVER_CARD_MS" in fn and "if (panelDrag || srcSliding) return;" in fn
    # A DELAYED leave, cancelled by a re-enter: moving from an arrow's line onto its own number fires
    # leave-then-enter, and restoring in between blinked the card on a pointer that never left.
    assert "HOVER_LEAVE_MS" in fn and "clearTimeout(outTimer); outTimer = null;" in fn
    assert "paneSync();" in fn, "writing the HTML is not enough — one rule decides if the card shows"
    assert "selApply(scene);" in fn and "hoverPreview = null;" in fn
    sole = js[js.index("function soleSelectedEl() {"):js.index("\n}", js.index("function soleSelectedEl() {"))]
    assert "if (hoverPreview && hoverPreview.isConnected) return hoverPreview;" in sole


def test_hovering_a_step_shows_its_card_too() -> None:
    """A box answers on hover; so does an arrow. But an arrow can carry SEVERAL steps, and every number
    on it is its own thing to hover, pick and point a line at — so each number is a target of its own,
    and its line goes to that number.

    THE ARROW ITSELF elects the first step it carries. Its transparent hit clones are that target (the
    numbers have their own), and its line goes to the first number too, so hovering the line and
    hovering its leading number answer the same and point at the same place.

    The clones are findable only because the path keeps them: every edge's clones are appended into the
    SAME parent group, so a sibling query would return the other arrows' clones as well.

    And a hover renders the card ALONE. `showFlowStep` also moves the code viewer to the step's own
    line, which is right for a click and wrong for a pointer crossing a map — the column would jump on
    every arrow it passed."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    assert "p.__cyHits = hits;" in js and "h.classList.add('cy-edgehit')" in js
    assert "previewOnHover(scene, [num], () => previewFlowStep(uc, i), num);" in js, \
        "one number, one target, and the line points at it"
    assert ("previewOnHover(scene, [...(p.__cyHits || [])], () => previewFlowStep(uc, on[0].i),\n"
            "                   stepNumEl(label, on[0].i) || p);") in js, \
        "the arrow elects its first step and points at that step's number"
    prev = js[js.index("function previewFlowStep(uc, i) {"):
              js.index("\n}", js.index("function previewFlowStep(uc, i) {"))]
    assert "flowStepInfoHtml(uc, i)" in prev and "bindFlowStepInfo(panel, uc, i)" in prev
    assert "syncCodeView(" not in prev, "a hover must not drag the code viewer across the map"


def test_the_interfaces_picture_scrolls_in_the_same_board_the_other_two_do() -> None:
    """One board, one behaviour: a white card with a 1px rule and a 10px radius, and an edge shade shown
    only while there is something that way to scroll to. The Interfaces picture bled to the page edge on
    a negative margin instead, which reads as a picture that ENDS at the window rather than one carrying
    on past it — and it had no shades at all, so nothing said there was more."""
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    assert "'.hp-strip, .journey-board, .story-wrap, .ifd-wrap'" in js
    css = (VIEWER_DIR / "viewer.css").read_text(encoding="utf-8")
    wrap = css[css.index(".ifd-wrap { margin: 4px"):]
    wrap = wrap[:wrap.index("}")]
    # THE LOOK IS STATED ONCE, for every drawing in the product — see `.cy-board`.
    assert ".hp-board, .journey-board, .ifd-wrap, .story-wrap, #diagwrap {" in css
    assert "background: #fff; border: 1px solid #e4e6ef; border-radius: 10px;" in css
    assert "overflow-x: auto" in wrap
    # VERTICAL padding only. A card's name sits half above the stage and would be clipped without it —
    # but horizontal padding MOVES the stage, and the wires are computed once, before the board's own
    # box has settled. 16px a side landed every wire 17px short of the product's circle.
    assert "padding: 16px 0" in wrap
    # THE BLEED IS ON THE WRAPPER, not on the board. `bindHFade` places the two shades against the
    # wrapper it inserts, so a board wider than that wrapper drew its own shades inside itself, over the
    # cards — a stain on the content instead of an edge the content passes under.
    assert ".hfade-wrap:has(> .ifd-wrap) { margin: 0 -1px; }" in css


def test_the_in_a_box_pill_is_one_component_that_no_page_restyles() -> None:
    """The tag naming one thing INSIDE a box — a shared sub-flow's dashed box, a door card's far side,
    a station on any board — is the SAME pill every other screen draws, at the size a dense board can
    carry. It used to be a second component called a chip, and the two drifted into looking alike while
    behaving differently: one opened what it named, the other was inert and the box around it opened.
    A reader could not tell which they were pointing at, and the hand cursor pointed the wrong way.

    It stopped being one component once before, the moment a lane wrote a rule of its own for it and
    put the mark 1.7px above where the same tag drew it on a card. So the STYLESHEET is what this pins:
    sharing a builder buys nothing while a page can re-style what comes out. Every selector naming the
    in-a-box pill has to be the component's own, and a new page-scoped one fails here rather than on
    somebody's eye."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    sels = [" ".join(m.group(2).split()).split("*/")[-1].strip()
            for m in re.finditer(r"(^|\})\s*([^{}@]*\.item-pill[^{}]*)\{", css, re.M)]
    assert sorted(sels) == sorted([
        ".item-pill",                                     # the tag itself
        ".item-pill .ibox-gly, .item-pill .story-glyph",  # …and its mark
        ".item-pill-door",                                # the form that acts
        ".item-pill-door:hover",                          # …and the only thing hover changes
        "#diagram .item-pill .ibox-gly, #diagram .item-pill .story-glyph, "
        "#panel .item-pill .ibox-gly, #panel .item-pill .story-glyph",   # one size on a diagram
        ".ibox-band .item-pill, .journey-ifs .item-pill",                # …and one inside a box
        ".ibox-band .item-pill .ibox-gly, .ibox-band .item-pill .story-glyph, "
        ".journey-ifs .item-pill .ibox-gly",
        "#diagram .ibox-band .item-pill .ibox-gly, #diagram .journey-ifs .item-pill .ibox-gly, "
        "#diagram .ifd-elabel-dir .ibox-gly",
        # The one line it takes as a feature heading — in the selection card AND on an element's own
        # page, which draws the same groups. ONE rule for both, not a second rule for the page: this
        # test's whole point is that a page may not re-style the tag, and sharing the rule is how the
        # page gets the same tag rather than its own.
        "#panel .used-cap-group > .item-pill, .edetail .used-cap-group > .item-pill",
    ]), sels
    # THE NAME WRAPS AND THE MARK CENTRES ON THE WHOLE TAG, stated on the component so no box has to say
    # it. Inside a box the tag is clamped to the box's width, and without wrapping the name ran straight
    # out through the border — measured at 161px of name in a 120px tag. The mark sat on the first line
    # for a while and read as a bullet beside a paragraph; centred, a two-line tag stays one object, and
    # it is what the tag outside a box already does.
    box = css[css.index(".ibox-band .item-pill, .journey-ifs .item-pill {"):]
    box = box[:box.index("}")]
    assert "align-items: center" in box and "line-height: 12px" in box
    assert "white-space: normal" in box and "overflow-wrap: anywhere" in box, "the name wraps in a box"
    assert "max-width: 100%" in box, "a tag fits its container wherever it is drawn"

def test_a_drawn_element_s_page_heads_its_drawing_with_the_same_strip_a_walk_s_board_wears() -> None:
    """A subsystem's, a subdomain's and a process's page keep their hero in the fixed block; the drawing
    under it wore a bare frame where a use case's board and every landing picture wear the grey strip
    saying what the drawing is. The three take the strip from the one head builder, over the same frame."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    board = js[js.index("const BOARD_HEAD = {"): js.index("\n}", js.index("function boardHeadHtml(s, id) {"))]
    assert "subsystem: (id) => ['Subsystem map', memberCount('component', id, 'component')," in board
    assert "domsub: (id) => ['Subdomain map', memberCount('entity', id, 'entity', 'entities')," in board
    assert "deploymentUnit: () => ['Process map', ''," in board, "a process's card has no one kind of member to count"
    assert "itemSectionHeadHtml(spec[0], spec[1], spec[2], elementHeroGlyph(GRAPH.nodes[id].kind))" in board, \
        "the one section-head builder, with the element's own glyph"
    count = js[js.index("function memberCount(kind, parent, noun, plural) {"):
               js.index("\n}", js.index("function memberCount(kind, parent, noun, plural) {"))]
    assert "x.kind === kind && x.parent === parent" in count, "the boxes inside the frame: direct members only"
    sync = js[js.index("function syncPageHero(s, chain, tv) {"): js.index("\n}", js.index("function syncPageHero(s, chain, tv) {"))]
    assert "} else if (id) {" in sync and "const board = boardHeadHtml(s, id);" in sync
    assert "if (board) inHead = stageStripHtml(board);" in sync, "in the walk's head host, over the drawing's frame"
    assert sync.count("stageStripHtml(") == 4, \
        "landing, board, pair and fold: ONE wrapper, so the frame joins every head the same way"


def test_a_walk_s_head_is_page_text_built_from_the_actor_page_s_own_pieces() -> None:
    """The use case page's hero and section head are drawn in the page (#diaghead), between the fixed
    block and the frame, by one builder — and that builder assembles the SAME pieces the actor page
    uses: the shared hero, the element's pills from the one function that decides them, and the section
    head factored out of `itemSectionHtml` so the words over a frame have one source. The two hosts are
    filled by one call, and the one not in use is emptied, so neither can outlive its page."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    html = (VIEWER_DIR / "viewer.html").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    stage = html[html.index('<div id="stagehead">'): html.index('<div id="diagwrap">')]
    assert stage.index('<div id="diaghead" hidden></div>') > stage.index('<div id="pagehero" hidden></div>'), \
        "in the page, under the fixed block's shadow — never inside it"
    head = js[js.index("function walkHeadHtml(s, chain) {"):
              js.index("\n}", js.index("function walkHeadHtml(s, chain) {"))]
    assert "pageHeroHtml({" in head and "elementSidePillsHtml(id)" in head, "the actor page's own hero and pills"
    assert "itemGlyphSvg(sub ? 'subflow' : 'usecase')" in head, "the element's own glyph on the name row"
    assert "itemSectionHeadHtml(" in head, "the section head, from the one builder"
    assert "(FLOWS_NARR[id] || []).length" in head, "the count is the walk's own steps"
    sec = js[js.index("function itemSectionHtml(secs, key, title, count, note, body, glyph, titleHtml) {"):
             js.index("\n}", js.index("function itemSectionHtml(secs, key, title, count, note, body, glyph, titleHtml) {"))]
    assert "itemSectionHeadHtml(title, count, note, glyph, titleHtml)" in sec, "…which the framed section uses too"
    sync = js[js.index("function syncPageHero(s, chain, tv) {"):
              js.index("\n}", js.index("function syncPageHero(s, chain, tv) {"))]
    assert "const walk = isFlowState(s);" in sync and "walk ? walkHeadHtml(s, chain)" in sync
    assert "other.innerHTML = ''; other.hidden = true;" in sync, "the host not in use is emptied"
    # The frame under the head is #diagwrap, restyled to the section frame's own colours while it shows.
    # The strip in the head and the drawing's frame are ONE framed section: no gap, no top border on
    # the frame, one rounded box between them.
    assert "#stage:has(#diaghead .item-sec-strip-stage) #diagwrap { margin: 0 20px 24px; border-color: #cbd5e1; border-top: 0;" in css
    assert "#diaghead .item-sec-strip-stage { border: 1px solid #cbd5e1; border-bottom: 1px solid #e2e8f0;" in css
    assert "return hero + stageStripHtml(" in head, "the same strip every section wears"
    assert "#diaghead { flex: 0 0 auto; padding: 0 20px; }" in css, "the actor page's left edge"


def test_one_count_pill_is_the_badge_every_count_wears() -> None:
    """A count wore four different badges. The Features page put it in a pale green pill, the Rules
    cards in a grey one, a framed section's head in a grey-blue one two pixels larger, and a card
    group in plain grey text with no pill at all — so the same fact looked like four different kinds
    of fact depending on which screen you were on.

    One builder emits it now and one rule styles it. `countPillHtml` takes the number and the singular
    noun; `countPillOf` takes a count someone else already worded, for the heads that are handed a
    string. Nothing else may draw a count badge of its own."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "function countPillHtml(n, noun) { return countPillOf(countLabel(n, noun)); }" in js
    assert 'function countPillOf(text) { return `<span class="count-pill">${esc(text)}</span>`; }' in js
    # THE FOUR OLD BADGES ARE GONE from the markup. `.ibox-count` and `.story-pill` survive as class
    # names on the shared rule, because a box's band and a story card put the pill there themselves.
    for dead in ('class="csec-count"', 'class="item-sec-n"'):
        assert dead not in js, f"{dead} still draws a count of its own"
    # …and one rule paints it, with the band and the story card sharing that rule rather than copying it.
    assert ".count-pill, .ibox-count, .story-pill {" in css
    assert css.count("background: #eef7f0; color: #166534;") == 1, "one count colour, in one place"


def test_a_count_is_worded_in_one_place_and_never_at_a_call_site() -> None:
    """`${n} rule${n === 1 ? '' : 's'}` was written out 37 times in this file. Three of those counted
    the same thing on two different screens, and each irregular one — `entity`, `dependency` — had to
    remember its own spelling where it was used, so a fourth screen counting entities would have had
    to know that too.

    One function words a count now, and the noun a caller passes is always SINGULAR: making the plural
    is the function's whole job, and the irregular ones live in one table beside it. `countNoun` is the
    same answer without the number, for the two places that set the number apart in its own bold.

    What is NOT counted here is verb agreement — `is`/`are`, `it`/`them`. Those are sentences the
    count appears in, not the count, and three of them stay at their call site on purpose."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "function countLabel(n, noun)" in js and "function countNoun(n, noun)" in js
    assert "function countPillHtml(n, noun)" in js, "and the pill a count rides in"
    # The irregular plurals are a table, not a call site's problem.
    assert "const COUNT_PLURALS = {" in js
    for irregular in ("entities", "dependencies"):
        assert irregular in js[js.index("const COUNT_PLURALS = {"):js.index("function countNoun")], \
            f"{irregular} belongs in the table"
    # NO CALL SITE MAKES ITS OWN PLURAL. The three survivors are verb agreement, matched out by name.
    left = [m.group(0) for m in re.finditer(r"=== 1 \? '(?:|y|[a-z]+)' : '(?:s|ies|[a-z]+)'", js)]
    agreement = [x for x in left if "'is' : 'are'" in x or "'it' : 'them'" in x]
    assert len(left) - len(agreement) == 0, \
        f"a call site is still wording its own plural: {[x for x in left if x not in agreement]}"


def test_one_pill_names_one_thing_wherever_a_screen_names_it() -> None:
    """Six shapes drew "this pill names that element" and no two agreed. A decision area on a rule's
    page was a 12px indigo pill; the entities and components beside it a near-white one; a feature chip
    a white one at another radius; an actor on a use-case card a 10px uppercase one; a feature on a card
    foot a grey one. Five click handlers sent the reader to two different kinds of destination, so a
    component named on a rule's page and the same component's card landed somewhere different.

    ONE BUILDER, ONE RULE, ONE BINDER now. The kind supplies the mark and the colour from the table the
    diagrams already paint their boxes with, so an entity's pill and an entity's box are visibly the
    same thing. `plain` is the no-click form, for a thing already on the reader's screen and for one
    the map no longer holds.

    NOT swept in, and each for a stated reason: the Happy Path's band name is a heading over a region
    rather than a tag inside a card; the Data page's chips carry a read/write verb, so they say more
    than a name; a `sys-ref` sits inside a sentence, where a pill would break the line."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert "function itemPillHtml(id, opts) {" in js and "function bindItemPills(root) {" in js
    # THE FIVE OLD SHAPES ARE GONE, markup and stylesheet both.
    for dead in ("br-blk", "br-ent", "br-comp", "featref", "ecard-pill-link"):
        assert dead not in js, f"{dead} still draws a pill of its own"
        assert dead not in css, f"{dead} still styles a pill of its own"
    # …and what they left behind went with them.
    for dead in ("function roleKindOf(n)", "data-goactor"):
        assert dead not in js, f"{dead} has no caller left"
    # ONE RULE PAINTS IT, and it paints a quiet box: the kind is said by the MARK, in that kind's own
    # colour from the diagrams' own table. The box carried that colour for a while and it was too much —
    # a row of tags each behind a saturated wash reads as a warning rather than as a list.
    assert ".item-pill { display: inline-flex;" in css
    assert "background: #fbfbfe; color: #374151; border: 1px solid #dfe2ec; }" in css
    assert "--pill-fill" not in css and "--pill-line" not in css, "no per-kind wash on the box"
    pill = js[js.index("function itemPillHtml(id, opts) {"):
              js.index("\n}", js.index("function itemPillHtml(id, opts) {"))]
    assert "itemMarkHtml(kind, o.ikind)" in pill, "the mark is where the kind is said"
    gly = js[js.index("function itemGlyphSvg(k, ikind) {"):
             js.index("\n}", js.index("function itemGlyphSvg(k, ikind) {"))]
    assert "itemTint(k)" in gly, "…and its colour comes from the diagrams' own table"


def test_every_pin_an_address_carries_puts_its_target_on_the_screen() -> None:
    """A shareable link can name a box, and the whole point of sending one is that the person opening it
    sees the thing you meant. There are TWO places that take such a pin — the Features board and the
    Interfaces board, which share the `sel` field and split it by key — and only one of them scrolled to
    what it pinned. The other landed at the top of a board 1270px tall: measured on a 900px window, the
    pinned box sat at 849px with only its top edge showing, and everything saying it was pinned (its
    border, its lit wire, the label counting the use cases that reach it) was below the fold.

    Pinned on the SOURCE, not in a browser, because the committed fixture map records no interfaces at
    all — that board cannot be rendered from it, which is also why nothing caught this."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    # The Features board's own pin, which had it all along.
    apply_ = js[js.index("  storyPinApply = (p) => {"):]
    apply_ = apply_[:apply_.index("\n  };")]
    assert "card.scrollIntoView({ block: 'center' });" in apply_
    # …and the Interfaces board's, which did not.
    iface = js[js.index("  if (pendingStoryPin && pendingStoryPin.key === IFACE_PIN_KEY) {"):]
    iface = iface[:iface.index("\n  }")]
    assert "box.scrollIntoView({ block: 'center' });" in iface, \
        "a pinned box the reader cannot see is the address not being honoured"


def test_only_the_file_tree_asks_for_the_zoom_that_matches_the_sidebar_text() -> None:
    """Selecting a box can carry a camera move: zoom until the box's own label reads at the size of the
    sidebar's text. It exists because a tree row has no modifier key to gate it on, unlike a click on
    the canvas — so it is the FILE TREE's gesture, and the code viewer's beside it.

    `selectFromTree` is what every other route also calls: an item pill, a type pill, a search hit, a
    reference in prose. All of them mean "show me that box", and being shown it means landing where the
    box's own address lands. They inherited the zoom instead, so one destination played a move on one
    route and not on the other: measured on mcpolis, a pill reached `domsub SD4` at 0.67 zoom by its
    address and at 0.88 by the pill.

    The flag says WHICH gesture asked, and it is off by default — a new caller gets the plain landing
    rather than a move it never asked for."""
    js = (VIEWER_DIR / "viewer.js").read_text()
    assert "function selectFromTree(nodeId, fromTree) {" in js
    body = js[js.index("function selectFromTree(nodeId, fromTree) {"):
              js.index("\nfunction selectFromTreeAnchors")]
    assert "if (el && !alreadySelected && fromTree) matchTextSize(el);" in body
    assert "pendingMatchText = !!fromTree;" in body, "…and the navigating route carries the same answer"
    # The render honours it, and clears it whether or not it fired.
    assert "const wantsZoom = pendingMatchText; pendingMatchText = false;" in js
    assert "if (el && wantsZoom) pendingMatchTextId = id;" in js
    # EXACTLY the tree and the code viewer ask for it. Every other caller passes nothing.
    assert js.count("selectFromTree(e.node, true)") == 1
    assert js.count("selectFromTreeAnchors([e.node, ...e.others], true)") == 2
    assert js.count("selectFromTree(e.sel, true)") == 1
    assert js.count("selectFromTree(id, true)") == 1
    assert "showInContext(id) { selectFromTree(id); }" in js, "showing is not the tree's gesture"


def test_the_focus_ring_stays_off_the_box_the_reader_already_picked() -> None:
    """Clicking a box focuses it and draws no ring; the next key press — Shift on its own will do it —
    puts the browser into keyboard mode and the ring appears on top of that box's own picked border. One
    box, marked twice, in two ways, for two reasons that are the same reason there.

    THE RING STAYS EVERYWHERE ELSE. Tab moves focus WITHOUT picking, and there the ring is the only
    thing saying where the keyboard is, so the rule turns it off for the picked box alone.

    Pinned on POSITION as well as on the selector: a dozen components set their own `:focus-visible`
    colour and offset, each at the weight of a bare class, so an override of the same weight placed
    above them loses and one new component rule below would quietly undo it."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    rule = "#diagram .ibox-picked:focus-visible"
    assert rule in css, "the picked box drops the ring"
    assert css.index(rule) > css.rindex(":focus-visible { outline: 2px solid"), \
        "the override has to sit after every component's own ring rule"
    off = css[css.index(rule):]
    assert "outline: none; }" in off[:off.index("\n\n") + 1 if "\n\n" in off else len(off)]
    # …and the plain ring is still there for everything that is focused without being picked.
    assert ":focus-visible { outline: 3px solid #818cf8; outline-offset: 2px; }" in css


def test_a_step_number_is_a_type_and_its_layout_belongs_to_what_carries_it() -> None:
    """One class numbers a step on TWO things, and they lay out differently. On a board's station the
    number sits on its own line above the title. On a map arrow's label the numbers riding one pair read
    along a line — `8, 9` — because a pair a flow crosses twice draws one arrow carrying both steps.

    `display: block` was on the CLASS, so the arrow's label stacked the two numbers and the comma into a
    box Mermaid had measured at 4px wide: it painted `8`, and step 9 appeared nowhere on that picture
    while its card insisted the arrow carried it. The type stays shared — same size, weight and colour,
    so a number reads as a number wherever it is — and the stacking moved to the station that wants it."""
    css = (VIEWER_DIR / "viewer.css").read_text()
    assert ".flow-step-num { font-size: 10px; font-weight: 700; color: #8a90a4; }" in css, \
        "the class carries type only"
    assert ".flow-step .flow-step-num { display: block; }" in css, \
        "…and the station, which stacks it above the title, asks for that itself"


def test_text_with_blank_lines_is_drawn_as_paragraphs_and_a_single_newline_is_a_wrap() -> None:
    """The product overview is written as two to four paragraphs (method.md, T0 Goal). Before this
    helper the viewer handed the whole text to one inline renderer and HTML collapsed the blank lines,
    so a three-paragraph goal came out as one block. Runs the real function."""
    out = _run_js("""
      const three = 'First one.\\n\\nSecond `one`.\\n  \\nThird one.';
      const refs = {C54: {id: 'C54', name: 'Request Context Middleware', node: 'C54'}};
      console.log(JSON.stringify([
        proseBlocksHtml(three, mdInline),
        proseBlocksHtml('one line.\\nsame paragraph.', mdInline),
        proseBlocksHtml('', mdInline),
        proseBlocksHtml('Alpha.\\r\\n\\r\\nBeta.', mdInline),
        proseBlocksHtml('See C54.\\n\\nAlso C54 here.', (p) => mdRefs(p, refs)),
      ]));
    """)
    paras, wrapped, empty, crlf, linked = json.loads(out)
    assert crlf == '<p class="prose-para">Alpha.</p><p class="prose-para">Beta.</p>'   # CRLF is a blank line too
    assert linked.count('class="sys-ref"') == 2 and linked.startswith('<p class="prose-para">See <button')
    assert paras == ('<p class="prose-para">First one.</p><p class="prose-para">Second <code>one</code>.</p>'
                     '<p class="prose-para">Third one.</p>')
    assert wrapped == "one line.\nsame paragraph."      # no <p>: the text renders exactly as before
    assert empty == ""


def test_the_overview_and_the_detail_rows_both_draw_paragraphs_through_the_one_helper() -> None:
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    assert "proseBlocksHtml(overview, (p) => mdRefs(p, GRAPH.nodes))" in js
    assert "proseBlocksHtml(v, mdInline)" in js
