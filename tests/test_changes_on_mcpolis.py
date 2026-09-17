#!/usr/bin/env python3
"""The whole update chain on the one real case: the mcpolis report of 2026-09-15, re-expressed as a
log (tests/fixtures/mcpolis-changes-2026-09-15.json, converted by hand from the report), run against
the mcpolis baseline map on this machine. Skipped where that repo is absent or its map has moved on.

What it proves: reanchor reproduces the report's 242 hand-written line moves and lists the two the
report resolved by hand; the log lints clean against the re-anchored map, applies, passes the gate
against the touched boxes, and leaves a map that loads."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from coyomap.changelog import apply, check, check_before_write, lint, load_log
from coyomap.impact_git import ImpactError, compute_impact, load_map_extents, resolve_ref
from coyomap.impact_ripple import RippleOptions, build_impact_result
from coyomap.model import ModelError, load_model
from coyomap.reanchor import reanchor
from coyomap.validate_model import validate_model

REPO = Path.home() / "mee6" / "repos" / "mcpolis"
MAP = REPO / ".coyomap" / "project-map.json"
LOG = Path(__file__).parent / "fixtures" / "mcpolis-changes-2026-09-15.json"
PIN, TO = "3a9e901", "1b77f52"


def make_case() -> tuple[Path, dict]:
    if not MAP.is_file():
        pytest.skip("the mcpolis repo is not on this machine")
    doc = json.loads(MAP.read_text(encoding="utf-8"))
    if str(doc.get("commit") or "")[:7] != PIN:
        pytest.skip(f"the mcpolis map moved on from {PIN}")
    try:
        load_model(json.dumps(doc))
    except ModelError as e:
        pytest.skip(f"the mcpolis map on disk is in an older shape than this tool reads: {e}")
    try:
        resolve_ref(REPO, TO)
    except ImpactError:
        pytest.skip(f"commit {TO} is not in the mcpolis clone")
    return MAP, doc


def test_the_update_chain_on_the_real_mcpolis_report():
    map_path, old_doc = make_case()
    log = load_log(LOG.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "project-map.json"
        shutil.copy(map_path, work)
        m = load_model(work.read_text(encoding="utf-8"))
        r = reanchor(m, REPO, TO)
        assert len(r.moved) == 242, "the report's appendix counted 242 line moves"
        assert sorted(u.eid for u in r.unmapped) == ["step:UC6:3", "step:UC7:3"], "the two the report resolved by hand"
        from coyomap.assemble import dump_preserving
        work.write_text(dump_preserving(m, None), encoding="utf-8")
        work_doc = json.loads(work.read_text(encoding="utf-8"))
        p = lint(log, work_doc)
        assert p.ok, p.errors
        # The report's own sentences are long, in its entries and in the gap of a tests row it adds;
        # the readability check says so, as advice.
        assert all(w.startswith(("entry ", "tests row ")) for w in p.warnings), p.warnings
        assert any("BR209 risk: bare pointer" in w for w in p.warnings), "what validate used to find first"
        # The impact file is step 1's: read off the map AT ITS PIN, before reanchor moved the links.
        model = load_model(json.dumps(old_doc))
        core = compute_impact(REPO, model, load_map_extents(map_path), "", TO)
        impact = build_impact_result(model, core, RippleOptions(), None, load_map_extents(map_path))
        # The gate before the write, on the log applied to a copy: the same verdict as after it.
        pre = check_before_write(log, work_doc, impact)
        assert pre.ok, pre.errors
        new_doc, done = apply(log, work_doc, "2026-09-15")
        assert (done.edits, done.added, done.removed) == (10, 5, 0)
        assert new_doc["commit"] == TO
        problems, _warnings = validate_model(load_model(json.dumps(new_doc)), None, disclose_records=False)
        assert problems == [], problems
        g = check(log, old_doc, new_doc, impact)
        assert g.ok, g.errors
        assert pre.warnings == g.warnings, "the gate on the copy and the gate on the written map agree"
        # The touched set depends on the pre-index beside the map (symbol resolution); with it, a few
        # boxes whose definitions grew are touched and unnamed. Those are the agent's to waive or
        # name, and advisory here: the gate holds, the warnings say where to look.
        assert "the code touched UC8 and no entry names or waives it" in g.warnings
        # The report waived a dependency the code reached only at file resolution: a waiver nobody
        # asked for, which the gate now says so about.
        assert "waived D22 did not change in the map and the code did not touch it" in g.warnings
        assert all(w.startswith(("the code touched ", "waived ")) for w in g.warnings), g.warnings


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
