#!/usr/bin/env python3
"""Prove the viewer's tests still guard the fixes of the 2026-10-02 Architecture review.

For each fix: take it out of a COPY of the repo (never this folder, which other chats share), run the
tests that should catch it, put it back. A fix whose tests still pass with it gone is guarded by
nothing, and the run says MISSED. About 2 minutes for all of them.

    python tests/fix_guards.py              # every fix
    python tests/fix_guards.py no-fewest    # one fix, by name

Run it with the interpreter that runs the gates (the main checkout's `.venv`). Not a test file, so
pytest does not collect it.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent


class Edit(NamedTuple):
    path: str   # repo-relative
    old: str    # must occur exactly once
    new: str


class Guard(NamedTuple):
    edits: list[Edit]
    tests: list[str]   # pytest node ids, repo-relative


V, C, G = "tools/coyomap/viewer/viewer.js", "tools/coyomap/viewer/viewer.css", "tools/coyomap/viewer/gen_viewer.py"
B, A = "tests/test_viewer_browser.py", "tests/test_architecture_view.py"
GUARDS: dict[str, Guard] = {
  "gloss-in-summary": Guard(edits=[Edit(V, "'a, button, summary, code,", "'a, button, code,")], tests=[f"{B}::test_a_line_cards_feature_rows_carry_no_glossary_link"]),
  "hit-copy-marker-start": Guard(edits=[Edit(V, "h.removeAttribute('marker-end'); h.removeAttribute('marker-start');", "h.removeAttribute('marker-end');")], tests=[f"{B}::test_a_line_up_the_layers_points_the_way_it_runs_and_is_picked_the_way_it_runs"]),
  "subflow-own-n": Guard(edits=[Edit(G, 'emit(x, str(x["src"]), str(x["dst"]), str(x.get("phrase") or "").strip(), n)', 'emit(x, str(x["src"]), str(x["dst"]), str(x.get("phrase") or "").strip(), int(x.get("n") or 0))')], tests=[f"{A}::test_a_line_inside_a_shared_sub_use_case_carries_the_step_that_runs_it"]),
  "preview-while-picked": Guard(edits=[Edit(V, "  if (mainScene && mainScene.selection.length) return;\n  archPreviewWatch();", "  archPreviewWatch();")], tests=[f"{B}::test_with_a_box_picked_resting_on_another_shows_its_card_and_draws_none_of_its_lines"]),
  "picked-head-not-blue": Guard(edits=[Edit(V, "if (blue) { heads.push({ seg, attr, was }); seg.setAttribute(attr, blue); }", "if (false) { heads.push({ seg, attr, was }); seg.setAttribute(attr, blue); }")], tests=[f"{B}::test_a_picked_arrows_head_turns_with_it_and_comes_back"]),
  "overlay-head-not-swapped": Guard(edits=[Edit(V, "line.setAttribute('marker-end', on ? 'url(#arch-ov-head-picked)' : 'url(#arch-ov-head)');", "line.setAttribute('marker-end', 'url(#arch-ov-head)');")], tests=[f"{B}::test_a_picked_arrows_head_turns_with_it_and_comes_back"]),
  "badge-clipped": Guard(edits=[Edit(C, "#diagram g.edgeLabel:has(p[data-fsteps]) foreignObject { overflow: visible; }", "")], tests=[f"{B}::test_a_use_case_maps_step_badges_are_whole_on_their_arrows"]),
  "no-fewest": Guard(edits=[Edit(V, "sets.fewest = { at: 1, of: g(lines.along) };", "")], tests=[f"{B}::test_where_no_place_clears_a_boxs_lines_its_card_lies_on_the_fewest"]),
  "no-top-room": Guard(edits=[Edit(V, "  const bar = !PANEL_HOST.hidden && document.getElementById('panelbar');\n  if (!bar) return 20;", "  return 0;\n  const bar = null;")], tests=[f"{B}::test_picking_what_the_second_card_shows_keeps_its_contents_in_place_near_the_drawings_top"]),
  "clamp-over-main": Guard(edits=[Edit(V, "if (!placePeekBesideMain(under)) { hidePeekCard(); return; }", "")], tests=[f"{B}::test_the_second_card_never_lands_on_the_main_card_or_on_the_box_under_the_pointer"]),
  "clamp-over-pointer": Guard(edits=[Edit(V, "if ((main.length && rectsOverlap(at, rectOf(PANEL_HOST))) || rectsOverlap(at, under)) {", "if (main.length && rectsOverlap(at, rectOf(PANEL_HOST))) {")], tests=[f"{B}::test_the_second_card_never_lands_on_the_main_card_or_on_the_box_under_the_pointer"]),
  "redraw-previews": Guard(edits=[Edit(V, "      if (!pointerFresh) { whenPointerMoves(enter); return; }\n", "")], tests=[f"{B}::test_a_picture_drawn_again_under_a_resting_pointer_previews_nothing"]),
  "wordless-use-case-dropped": Guard(edits=[Edit(V, "  for (const uc of Object.keys(e.steps || {})) if (!said.has(uc)) said.set(uc, []);\n", "")], tests=[f"{B}::test_a_use_case_whose_step_has_no_words_is_still_on_the_lines_card"]),
  "one-feature-folded": Guard(edits=[Edit(V, "|| feats.size <= 1;", ";")], tests=[f"{B}::test_a_line_names_its_use_cases_by_feature"]),
  "second-card-moves-tree": Guard(edits=[Edit(V, "  // THE SECOND CARD leaves the file tree and the code to what is picked: a hover beside a pick moved\n  // the tree to the hovered box.\n  if (panel === PEEK_CARD) return;\n", "")], tests=[f"{B}::test_the_second_card_leaves_the_file_tree_to_what_is_picked"]),
  "drops-every-actor": Guard(edits=[Edit(V, " && joined.has(c.name + '>' + id) };", " };")], tests=[f"{B}::test_an_interfaces_card_drops_only_the_people_this_picture_joins_to_it"]),
  "card-ignores-drop": Guard(edits=[Edit(V, "  panel.innerHTML = paneCardHtml(id, cardOpts);", "  panel.innerHTML = paneCardHtml(id);")], tests=[f"{B}::test_an_interfaces_card_drops_only_the_people_this_picture_joins_to_it"]),
  "zoom-from-getZoom": Guard(edits=[Edit(V, "  const home = usableScale(homeReal) ? homeReal : homeRealZoom(), real = mainPz.getSizes().realZoom;", "  const home = NaN, real = NaN;")], tests=[f"{B}::test_the_zoom_number_reads_100_where_each_view_opens_and_after_a_click_on_it"]),
  "switch-on-any-feature": Guard(edits=[Edit(V, "  const show = !!f && !!MERMAID_ARCH_BY['happy|' + f];", "  const show = !!f;")], tests=[f"{B}::test_the_happy_path_switch_is_only_on_a_feature_with_a_happy_path_picture"]),
}


def run_guard(root: Path, name: str, guard: Guard, env: dict[str, str]) -> bool:
    """True when the guard's tests FAIL with the fix taken out, which is what a guard is for."""
    pristine = {e.path: (root / e.path).read_text() for e in guard.edits}
    texts = dict(pristine)
    for e in guard.edits:
        if texts[e.path].count(e.old) != 1:
            raise SystemExit(f"{name}: the fix's text is not found once in {e.path}; update this list")
        texts[e.path] = texts[e.path].replace(e.old, e.new)
    try:
        for path, text in texts.items():
            (root / path).write_text(text)
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *guard.tests],
                           cwd=root, env=env, capture_output=True, text=True, timeout=1200)
    finally:
        for path, text in pristine.items():
            (root / path).write_text(text)
    tail = (re.findall(r"^(\d+ (?:passed|failed).*)$", r.stdout, re.M) or [r.stdout[-200:]])[-1]
    print(f"{'CAUGHT' if r.returncode else 'MISSED'}  {name}: {tail}", flush=True)
    return r.returncode != 0


def main(names: list[str]) -> int:
    unknown = [n for n in names if n not in GUARDS]
    if unknown:
        raise SystemExit(f"unknown fix: {', '.join(unknown)}; known: {', '.join(GUARDS)}")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "repo"
        shutil.copytree(REPO, root, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".claude", "node_modules"))
        env = dict(os.environ, PYTHONPATH=f"{root}/tools:{root}/eval/tools")
        caught = [run_guard(root, n, GUARDS[n], env) for n in (names or list(GUARDS))]
    print(f"{sum(caught)} of {len(caught)} fixes caught by a test")
    return 0 if all(caught) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
