#!/usr/bin/env python3
"""Tests for `coyomap fix` — the in-place reconcile verbs (apply-drift / drop-edge / dedup-relation).

Run either way (needs an editable install: `make deps`):
    python3 tests/test_fix.py
    pytest tests/test_fix.py
"""
from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

from coyomap import audit_model, fix
from coyomap.model import FORMAT, load_model_path


# --- builders -------------------------------------------------------------------

def make_map(edges: list[dict], *, security: list[dict] | None = None,
             flows: list[dict] | None = None, entities: list[dict] | None = None) -> dict:
    return {
        "format": FORMAT, "title": "t", "goal": "g",
        "use_cases": [{"id": "UC1", "name": "Do"}],
        "components": [{"id": "C1", "name": "A", "source": "a.py:1"}],
        "entities": entities if entities is not None else [{"id": "E1", "name": "Thing"},
                                                           {"id": "E2", "name": "Other"}],
        "edges": edges,
        "security": security or [],
        "flows": flows or [],
    }


def make_vote(claim: str, grounded: bool, evidence: str) -> dict:
    return {"claim": claim, "grounded": grounded, "evidence": evidence}


def write(td: str, m: dict, verdicts: dict | None = None) -> tuple[str, str]:
    mp = Path(td) / "map.json"
    mp.write_text(json.dumps(m), encoding="utf-8")
    vp = Path(td) / "verdicts.json"
    if verdicts is not None:
        vp.write_text(json.dumps(verdicts), encoding="utf-8")
    return str(mp), str(vp)


# --- apply-drift ----------------------------------------------------------------

def test_apply_drift_does_not_swap_paired_persists_reads_edges():
    # THE headline regression: two edges share endpoints (C1↔E1) but differ in verb. The old hand
    # script matched on (src,dst) only and swapped their anchors. Matching the FULL (src,verb,dst)
    # triple keeps each on its own corrected line.
    m = make_map([
        {"src": "C1", "verb": "persists", "dst": "E1", "where": "a.py:10"},
        {"src": "C1", "verb": "reads", "dst": "E1", "where": "a.py:20"}])
    verdicts = {"grounding": [
        make_vote("C1 persists E1", True, "a.py:15"), make_vote("C1 persists E1", True, "a.py:15"),
        make_vote("C1 reads E1", True, "a.py:25"), make_vote("C1 reads E1", True, "a.py:25")]}
    with tempfile.TemporaryDirectory() as td:
        mp, vp = write(td, m, verdicts)
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0"]) == 0
        out = load_model_path(mp)
        where = {e.verb: e.where for e in out.edges}
        assert where["persists"] == "a.py:15"     # each edge got ITS OWN corrected line
        assert where["reads"] == "a.py:25"         # NOT swapped


def test_apply_drift_rewrites_drifted_security_source():
    # The worklist carries a security claim ("Auth surface '…' is protected by: …") whose bare
    # `source` anchor is an L2 grounding claim. When the skeptics confirm it drifted, apply-drift now
    # rewrites `security[].source` (WS5) — same treatment as a drifted edge `where`.
    m = make_map([], security=[{"surface": "POST /pay", "who": "admin", "source": "a.py:5"}])
    claim_prefix = "Auth surface 'POST /pay' is protected by:"
    with tempfile.TemporaryDirectory() as td:
        mp, vp = write(td, m, {"grounding": []})
        # find the exact security claim string the worklist builds, then drift it
        from coyomap.audit_model import l2_worklist_model
        sec_claim = next(w.claim for w in l2_worklist_model(load_model_path(mp))
                         if w.claim.startswith(claim_prefix))
        Path(vp).write_text(json.dumps({"grounding": [
            make_vote(sec_claim, True, "a.py:99"), make_vote(sec_claim, True, "a.py:99")]}),
            encoding="utf-8")
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0"]) == 0
        assert load_model_path(mp).security[0].source == "a.py:99"   # rewritten to the skeptics' line


def test_apply_drift_rewrites_security_and_leaves_a_paired_edge_untouched():
    # A drifted security anchor AND a same-file edge whose anchor is NOT in the verdicts: only the
    # security `source` moves; the edge's `where` stays put (apply-drift touches only drifted claims).
    m = make_map([{"src": "C1", "verb": "reads", "dst": "E1", "where": "a.py:10"}],
                 security=[{"surface": "POST /pay", "who": "admin", "source": "a.py:5"}])
    with tempfile.TemporaryDirectory() as td:
        mp, vp = write(td, m)
        from coyomap.audit_model import l2_worklist_model
        sec_claim = next(w.claim for w in l2_worklist_model(load_model_path(mp))
                         if w.claim.startswith("Auth surface 'POST /pay'"))
        Path(vp).write_text(json.dumps({"grounding": [
            make_vote(sec_claim, True, "a.py:88"), make_vote(sec_claim, True, "a.py:88")]}),
            encoding="utf-8")
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0"]) == 0
        out = load_model_path(mp)
        assert out.security[0].source == "a.py:88"                  # security anchor rewritten
        assert out.edges[0].where == "a.py:10"                      # the edge (not in verdicts) untouched


def make_preindex(td: str, extents: dict[str, list[list]]) -> None:
    """The pre-index committed beside a map, holding the symbol table this command reads to tell a
    nudge inside one definition from a re-anchor onto another."""
    Path(td, "preindex.json").write_text(json.dumps({"symbols": {"extents": extents}}),
                                         encoding="utf-8")


def test_apply_drift_refuses_a_correction_onto_a_different_definition(capsys):
    """The 2026-09-13 reminderrepo build wrote a 174-line move onto an unrelated statement inside an
    unattended `ship`, because drift had a lower bound only and the writer applied whatever was
    reported. A correction that leaves the definition the stored anchor sits in is now REPORTED with
    both anchors and left unwritten — the map keeps its old anchor until a human decides."""
    m = make_map([{"src": "C1", "verb": "persists", "dst": "E1", "where": "a.py:10"}])
    verdicts = {"grounding": [make_vote("C1 persists E1", True, "a.py:60"),
                              make_vote("C1 persists E1", True, "a.py:60")]}
    with tempfile.TemporaryDirectory() as td:
        mp, vp = write(td, m, verdicts)
        make_preindex(td, {"a.py": [[5, 20, "save", "function"], [50, 70, "render", "function"]]})
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0"]) == 0
        assert load_model_path(mp).edges[0].where == "a.py:10"   # NOT moved
        out = capsys.readouterr()
    assert "REFUSED" in out.err and "save" in out.err and "render" in out.err
    assert "a.py:10" in out.err and "a.py:60" in out.err, "both anchors must be named"
    assert "REFUSED as a re-anchor" in out.out.splitlines()[-1], "the count must survive a `tail`"


def test_apply_drift_still_writes_a_correction_inside_the_same_definition(capsys):
    """The control for the test above, and the reason the cut is not an upper distance bound: 50
    lines inside ONE function is the header-to-operative-line nudge this command exists for."""
    m = make_map([{"src": "C1", "verb": "persists", "dst": "E1", "where": "a.py:10"}])
    verdicts = {"grounding": [make_vote("C1 persists E1", True, "a.py:60"),
                              make_vote("C1 persists E1", True, "a.py:60")]}
    with tempfile.TemporaryDirectory() as td:
        mp, vp = write(td, m, verdicts)
        make_preindex(td, {"a.py": [[5, 70, "save", "function"]]})
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0"]) == 0
        assert load_model_path(mp).edges[0].where == "a.py:60"
    assert "REFUSED as a re-anchor" not in capsys.readouterr().out


def test_apply_drift_to_reconcile_does_not_record_a_refused_move(capsys):
    """A refused correction must reach NEITHER write path. `set_anchors` is replayed by every
    `assemble --reconcile`, so one recorded there would re-apply the wrong anchor on every rebuild —
    durably, and out of sight of the run that decided it."""
    m = make_map([{"src": "C1", "verb": "persists", "dst": "E1", "where": "a.py:10"},
                  {"src": "C1", "verb": "reads", "dst": "E1", "where": "a.py:12"}])
    verdicts = {"grounding": [
        make_vote("C1 persists E1", True, "a.py:60"), make_vote("C1 persists E1", True, "a.py:60"),
        make_vote("C1 reads E1", True, "a.py:16"), make_vote("C1 reads E1", True, "a.py:16")]}
    with tempfile.TemporaryDirectory() as td:
        mp, vp = write(td, m, verdicts)
        make_preindex(td, {"a.py": [[5, 20, "save", "function"], [50, 70, "render", "function"]]})
        rec = Path(td) / "reconcile.json"
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0",
                         "--to-reconcile", str(rec)]) == 0
        recorded = json.loads(rec.read_text(encoding="utf-8"))["set_anchors"]
        out = capsys.readouterr()
    assert [a["claim"] for a in recorded] == ["C1 reads E1"]     # the in-definition nudge only
    assert "REFUSED" in out.err and "C1 persists E1" in out.err
    assert "REFUSED as a re-anchor" in out.out.splitlines()[-1], "the count must survive a `tail`"


def test_apply_drift_to_reconcile_warns_on_a_far_move_it_does_write(capsys):
    """The far-move warning was dead on the path every build uses. It lives in the IN-PLACE writer,
    and `ship` step 3 runs `--to-reconcile` — so the 2026-09-13 reminderrepo run recorded a 174-line
    move with no note at all. A long move INSIDE one definition is legitimate (a header anchor
    corrected onto the operative line), so it is still written; it just no longer lands in silence."""
    m = make_map([{"src": "C1", "verb": "persists", "dst": "E1", "where": "a.py:10"}])
    verdicts = {"grounding": [make_vote("C1 persists E1", True, "a.py:200"),
                              make_vote("C1 persists E1", True, "a.py:200")]}
    with tempfile.TemporaryDirectory() as td:
        mp, vp = write(td, m, verdicts)
        make_preindex(td, {"a.py": [[5, 300, "save", "function"]]})
        rec = Path(td) / "reconcile.json"
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0",
                         "--to-reconcile", str(rec)]) == 0
        recorded = json.loads(rec.read_text(encoding="utf-8"))["set_anchors"]
        out = capsys.readouterr().out
    assert [a["corrected"] for a in recorded] == ["a.py:200"]    # written: one definition
    assert "moved 190 lines" in out, out                         # and said so


def test_apply_drift_skips_ambiguous_multi_where_edge():
    # Two edges share (src,verb,dst) but different call sites → one worklist claim matches 2 edges.
    # Blind-writing both is wrong, so apply-drift skips them.
    m = make_map([
        {"src": "C1", "verb": "persists", "dst": "E1", "where": "a.py:10"},
        {"src": "C1", "verb": "persists", "dst": "E1", "where": "b.py:10"}])
    verdicts = {"grounding": [make_vote("C1 persists E1", True, "a.py:50"),
                              make_vote("C1 persists E1", True, "a.py:50")]}
    with tempfile.TemporaryDirectory() as td:
        mp, vp = write(td, m, verdicts)
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0"]) == 0
        wheres = sorted(e.where or "" for e in load_model_path(mp).edges)
        assert wheres == ["a.py:10", "b.py:10"]    # both untouched


# --- drop-edge ------------------------------------------------------------------

def _flow_map() -> dict:
    return make_map(
        [{"src": "C1", "verb": "persists", "dst": "E1", "where": "a.py:10"}],
        flows=[{"uc": "UC1", "title": "Do", "steps": [
            {"n": 1, "src": "C1", "dst": "E1", "phrase": "writes it", "where": "a.py:10"}]}])


def test_drop_edge_removes_edge_and_reports_riding_steps():
    with tempfile.TemporaryDirectory() as td:
        mp, _ = write(td, _flow_map())
        assert fix.main(["drop-edge", "--map", mp, "C1", "persists", "E1"]) == 0
        out = load_model_path(mp)
        assert out.edges == []                          # edge gone
        assert out.flows[0].steps[0].dst == "E1"        # step left in place for a hand reconcile


def test_drop_edge_repoint_heals_the_riding_step():
    with tempfile.TemporaryDirectory() as td:
        mp, _ = write(td, _flow_map())
        assert fix.main(["drop-edge", "--map", mp, "C1", "persists", "E1", "--repoint", "E2"]) == 0
        out = load_model_path(mp)
        assert out.edges == []
        assert out.flows[0].steps[0].dst == "E2"        # step re-pointed


def test_drop_edge_missing_edge_errors():
    with tempfile.TemporaryDirectory() as td:
        mp, _ = write(td, _flow_map())
        assert fix.main(["drop-edge", "--map", mp, "C1", "reads", "E1"]) == 1


# --- dedup-relation -------------------------------------------------------------

def _reciprocal_map() -> dict:
    return make_map([], entities=[
        {"id": "E1", "name": "Org", "relations": [{"verb": "contains", "target": "E2"}]},
        {"id": "E2", "name": "Member", "relations": [{"verb": "references", "target": "E1"}]}])


def test_dedup_relation_lists_then_drops_chosen_side():
    with tempfile.TemporaryDirectory() as td:
        mp, _ = write(td, _reciprocal_map())
        assert fix.main(["dedup-relation", "--map", mp]) == 0            # list mode
        assert fix.main(["dedup-relation", "--map", mp, "--drop", "E2:references:E1"]) == 0
        out = load_model_path(mp)
        assert out.entities[1].relations == []                          # dropped side
        assert len(out.entities[0].relations) == 1                      # kept side intact


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")


def test_a_drifted_cadence_anchor_is_written_not_refused(capsys):
    """Two defects, one fixture. FIRST: a cadence claim fell through to the security branch and was
    reported as a security surface matching 0 rows, while the summary said "no drifted edge or
    security anchors to rewrite" — two true statements that together told the operator nothing.
    THEN, once it was named correctly, it was still REFUSED: `cadence_source` is a real schema field
    and `apply-drift` had no writer for it, so a live build had five cadence drifts handed back and
    re-typed them through a bespoke script."""
    m = make_map([], entities=[{"id": "E1", "name": "Thing"}])
    m["entry_points"] = [{"kind": "job", "trigger": "nightly sweep", "component": "C1",
                          "source": "a.py:1", "cadence": "every 24h", "cadence_source": "a.py:2"}]
    claim = "Entry point [job] nightly sweep runs on cadence 'every 24h'"
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
        mp, vp = write(td, m, {"grounding": [make_vote(claim, True, "a.py:30")]})
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp]) == 0
        out = capsys.readouterr()
        assert load_model_path(Path(mp)).entry_points[0].cadence_source == "a.py:30"
    combined = out.out + out.err
    assert "matches 0 security surfaces" not in combined, combined
    assert "cadence_source" in combined and "1 cadence anchor(s)" in combined


def make_lifecycle_map() -> dict:
    return make_map([], entities=[{"id": "E1", "name": "Thing", "states": {
        "source": "a.py:2", "states": ["NEW", "DONE"],
        "transitions": [{"src": "NEW", "dst": "DONE", "on": "finish"}]}}])


LIFECYCLE_CLAIM = "E1 (Thing) has states [NEW, DONE] with 1 transition(s)"


def test_the_not_applicable_count_rides_the_final_line(capsys):
    """A live build read this output with `| tail -12`, so a total that is not on the last line is a
    total the reader never sees — the same lesson as assemble's unhealed-riding-step count.

    Driven by an UNPARSEABLE edge claim: this used to use a lifecycle drift, which is no longer
    not-applicable now that it has a writer."""
    m = make_map([{"src": "C1", "verb": "writes to", "dst": "E1", "why": "w", "where": "a.py:1"}])
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
        mp, vp = write(td, m, {"grounding": [make_vote("C1 writes to E1", True, "a.py:30")]})
        fix.main(["apply-drift", "--map", mp, "--verdicts", vp])
        out = capsys.readouterr()
    last = [ln for ln in out.out.splitlines() if ln.strip()][-1]
    assert "NOT APPLICABLE" in last and "1 drift(s)" in last, last


def test_a_drifted_lifecycle_anchor_is_written_not_refused(capsys):
    """`lifecycle` was drift-ELIGIBLE with no writer, so every confirmed lifecycle drift was
    re-authored by hand — verbatim the `cadence` gap this same function was extended to close."""
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
        mp, vp = write(td, make_lifecycle_map(),
                       {"grounding": [make_vote(LIFECYCLE_CLAIM, True, "a.py:30")]})
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp]) == 0
        out = capsys.readouterr()
        m2 = json.loads(Path(mp).read_text())
    assert m2["entities"][0]["states"]["source"] == "a.py:30"
    assert "1 lifecycle anchor(s)" in out.out, out.out
    assert "NOT APPLICABLE" not in out.out, out.out


def test_a_lifecycle_correction_on_a_component_lands_on_the_component(capsys):
    """The target is `states.source` on an entity OR a component, so the write has to carry WHICH."""
    m = make_map([])
    m["components"] = [{"id": "C1", "name": "A", "source": "a.py:1", "states": {
        "source": "a.py:2", "states": ["OPEN", "SHUT"], "transitions": []}}]
    claim = "C1 (A) has states [OPEN, SHUT]"
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
        mp, vp = write(td, m, {"grounding": [make_vote(claim, True, "a.py:31")]})
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp]) == 0
        capsys.readouterr()
        m2 = json.loads(Path(mp).read_text())
    assert m2["components"][0]["states"]["source"] == "a.py:31"


def test_a_lifecycle_claim_matching_two_elements_is_skipped_not_blind_written(capsys):
    """Same multiplicity rule as every other writer: picking 'the first' is how a hand script
    overwrote a claim nobody meant to touch."""
    # Same id text in the claim from two different arrays is impossible (ids are prefix-typed), so
    # the collision is built the way it really occurs: two entities whose claim strings are equal.
    m = make_map([], entities=[
        {"id": "E1", "name": "Thing", "states": {"source": "a.py:2", "states": ["NEW"],
                                                 "transitions": []}},
        {"id": "E1", "name": "Thing", "states": {"source": "a.py:3", "states": ["NEW"],
                                                 "transitions": []}}])
    claim = "E1 (Thing) has states [NEW]"
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
        mp, vp = write(td, m, {"grounding": [make_vote(claim, True, "a.py:30")]})
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp]) == 0
        out = capsys.readouterr()
        m2 = json.loads(Path(mp).read_text())
    assert "matches 2 lifecycles" in (out.out + out.err)
    assert m2["entities"][0]["states"]["source"] == "a.py:2", "must not be blind-written"


def test_an_edge_anchor_is_still_rewritten_and_says_so_on_the_last_line(capsys):
    """The other half: the kinds it CAN write must keep working, and the summary stays truthful."""
    m = make_map([{"src": "C1", "verb": "reads", "dst": "E1", "why": "w", "where": "a.py:1"}])
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
        mp, vp = write(td, m, {"grounding": [make_vote("C1 reads E1", True, "a.py:30")]})
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp]) == 0
        out = capsys.readouterr()
        assert load_model_path(Path(mp)).edges[0].where == "a.py:30"
    last = [ln for ln in out.out.splitlines() if ln.strip()][-1]
    assert "rewrote 1 edge" in last and "NOT APPLICABLE" not in last, last


def make_model_touching_every_theme():
    """A model carrying at least one claim of EVERY theme the audit emits, so the partition test can
    ask the audit which themes it declares report-only instead of being told in a literal."""
    from coyomap.model import load_model

    doc = make_map([{"src": "C1", "verb": "reads", "dst": "E1", "why": "w", "where": "a.py:1"},
                    {"src": "C1", "verb": "uses", "dst": "D1", "why": "w", "where": "a.py:2"},
                    {"src": "C1", "verb": "persists", "dst": "E1", "why": "w", "where": "a.py:3"}])
    # A `purpose` on one of them, so the `description` theme is touched too — the fixture's whole
    # job is to carry one claim of EVERY theme, and a tier it misses becomes a silent exemption.
    doc["components"] = [{"id": "C1", "name": "A", "source": "a.py:1",
                          "purpose": "Reads the thing and writes it back."},
                         {"id": "C2", "name": "B", "source": "b.py:1"}]
    doc["edges"].append({"src": "C1", "verb": "calls", "dst": "C2", "why": "w", "where": "a.py:4"})
    doc["deps"] = [{"id": "D1", "name": "redis", "kind": "library"}]
    doc["entities"] = [
        {"id": "E1", "name": "Thing", "source": "a.py:9",
         "store": {"dep": "D1", "container": "things", "mode": "collection"},
         "states": {"source": "a.py:2", "states": ["NEW", "DONE"], "transitions": []}},
        {"id": "E2", "name": "Other"}]
    doc["rules"] = [{"id": "BR1", "name": "A token", "statement": "A token is checked",
                     "risk": "r", "access": True,
                     "sites": [{"where": "a.py:5", "why": "guards the API"}]},
                    {"id": "BR2", "name": "A plan", "statement": "A plan has a cap", "risk": "r",
                     "sites": [{"where": "a.py:6", "why": "caps the plan"}]}]
    doc["entry_points"] = [{"kind": "cron", "trigger": "nightly sweep", "source": "a.py:7",
                            "component": "C1", "cadence": "daily", "cadence_source": "a.py:8"}]
    doc["messaging"] = [{"name": "jobs", "kind": "queue", "publishers": ["C1"],
                         "consumers": ["C2"], "payload": "a job", "source": "a.py:10"}]
    doc["interfaces"] = [{"id": "I1", "name": "Web search", "side": "theirs", "facing": "user",
                          "source": "a.py:11"}]
    # A flow with a phrased step, so the OPT-IN `behaviour` tier is touched too. The fixture's whole
    # job is to carry one claim of EVERY theme, and a tier it misses becomes a silent exemption.
    doc["use_cases"] = [{"id": "UC1", "name": "Do the thing", "actors": ["R1"],
                         "trigger_outcome": "asks -> gets", "capability": "CAP1"}]
    doc["capabilities"] = [{"id": "CAP1", "name": "Doing", "purpose": "The thing gets done."}]
    doc["roles"] = [{"id": "R1", "name": "A person", "wants": "the thing"}]
    doc["flows"] = [{"uc": "UC1", "title": "Do the thing", "steps": [
        {"n": 1, "src": "R1", "dst": "C1", "phrase": "asks for the thing", "where": "a.py:1"}]}]
    return load_model(json.dumps(doc))


def test_the_writable_theme_partition_covers_every_theme_the_audit_emits():
    """F10's pin. `_WRITABLE_THEMES` partitions `audit_model._THEMES`, in a different module, with no
    guard — so a new claim kind would silently become "not applicable", and if it were writable
    `apply-drift` would quietly stop applying it. Same shape as the `_THEMES` closed-set test."""
    from coyomap import audit_model
    known = set(audit_model._THEMES)
    assert fix._WRITABLE_THEMES <= known, fix._WRITABLE_THEMES - known
    # Every theme is on exactly one side, and the split is the documented one.
    unwritable = known - fix._WRITABLE_THEMES
    # The list is NOT a hand-written allow-list any more. A theme is unwritable only when the audit
    # itself declares its claims report-only (`drift_eligible=False`), which is a statement about the
    # CLAIM — the skeptic is sent to a different kind of line than the anchor holds, so a difference
    # there is not evidence of drift. `lifecycle` sat in a hand-written exception list for months
    # while being drift-ELIGIBLE, so every confirmed lifecycle drift was re-typed by hand; the same
    # thing had already happened to `cadence`. Twice is a pattern, so the test now derives the split.
    # `behavioural=True` so the OPT-IN tier is in the partition too. It is off by default (it
    # roughly doubles the worklist), and a theme the audit can emit but this test never sees is
    # exactly the silent "not applicable" this test exists to prevent.
    ineligible = {w.theme for w in audit_model.l2_worklist_model(
                      make_model_touching_every_theme(), behavioural=True)
                  if not w.drift_eligible}
    assert unwritable <= ineligible, (
        f"theme(s) whose claims ARE drift-eligible but have no writer: {sorted(unwritable - ineligible)}")


def test_an_unparseable_edge_claim_is_not_reported_as_a_missing_security_row(capsys):
    """`validate` accepts a multi-word verb, which `_EDGE_CLAIM`'s `(\\S+)` cannot match. Such a claim
    is edge-THEMED, so the theme gate passes it — and it used to reach the security writer and be
    reported as "matches 0 security surfaces", the very mislabelling this dispatch exists to kill."""
    m = make_map([{"src": "C1", "verb": "writes to", "dst": "E1", "why": "w", "where": "a.py:1"}])
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
        mp, vp = write(td, m, {"grounding": [make_vote("C1 writes to E1", True, "a.py:30")]})
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp]) == 0
        out = capsys.readouterr()
    combined = out.out + out.err
    assert "matches 0 security surfaces" not in combined, combined
    assert "could not parse back to an edge" in combined
    last = [ln for ln in out.out.splitlines() if ln.strip()][-1]
    assert "NOT APPLICABLE" in last, last


# --- fix dedup-edge -------------------------------------------------------------------------
#
# `validate` warned about (src, verb, dst) declared at DIFFERING call sites and no verb resolved it,
# so a live build hand-wrote a 40-line script for 24 of them and dropped 29 rows unreviewed —
# against this tool's own claim that these mechanical edits are never hand-scripted.


def make_dup_edge_map(tmp: str) -> Path:
    p = Path(tmp) / "project-map.json"
    p.write_text(json.dumps({
        "format": FORMAT, "title": "T", "goal": "g",
        "components": [{"id": "C1", "name": "A", "source": "src/a.py:1"},
                       {"id": "C2", "name": "B", "source": "src/b.py:1"}],
        "edges": [{"src": "C1", "verb": "calls", "dst": "C2", "why": "w", "where": "src/a.py:10"},
                  {"src": "C1", "verb": "calls", "dst": "C2", "why": "w", "where": "tests/a.py:99"}],
    }), encoding="utf-8")
    return p


def test_dedup_edge_lists_the_conflict_and_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        before = p.read_text()
        assert fix.main(["dedup-edge", "--map", str(p)]) == 0
        assert p.read_text() == before, "listing must not edit the map"


def test_dedup_edge_keeps_the_named_anchor_and_drops_the_rest():
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        assert fix.main(["dedup-edge", "--map", str(p),
                         "--keep", "C1:calls:C2:src/a.py:10"]) == 0
        edges = load_model_path(p).edges
        assert len(edges) == 1 and edges[0].where == "src/a.py:10"


def test_dedup_edge_refuses_an_anchor_none_of_the_occurrences_has():
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        assert fix.main(["dedup-edge", "--map", str(p), "--keep", "C1:calls:C2:src/z.py:1"]) == 1
        assert len(load_model_path(p).edges) == 2, "nothing may be dropped on a bad --keep"


def test_dedup_edge_is_silent_when_there_is_no_duplicate():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.json"
        p.write_text(json.dumps({
            "format": FORMAT, "title": "T", "goal": "g",
            "components": [{"id": "C1", "name": "A", "source": "src/a.py:1"}],
            "edges": [],
        }), encoding="utf-8")
        assert fix.main(["dedup-edge", "--map", str(p)]) == 0


def test_apply_drift_accepts_the_repo_flag_its_sibling_requires():
    """`anchor-drift` REQUIRES --repo and the two run back-to-back on the same inputs; rejecting it
    here cost a live build a turn on `unknown argument '--repo'`."""
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        v = Path(tmp) / "verdicts.json"
        v.write_text(json.dumps({"grounding": []}), encoding="utf-8")
        assert fix.main(["apply-drift", "--map", str(p), "--verdicts", str(v),
                         "--repo", tmp]) == 0


# ── the retro findings: a sub-verb that answers --help, and an intent the flags could not express ──

def test_every_fix_sub_verb_answers_help_instead_of_erroring(capsys):
    """Four verbs answered `ERROR: unknown argument '--help'` because each per-verb parser treats an
    unknown flag as a usage error. A live build lost seven turns to this on `dedup-edge`."""
    for verb in ("apply-drift", "drop-edge", "dedup-relation", "dedup-edge"):
        assert fix.main([verb, "--help"]) == 0, verb
        out = capsys.readouterr().out
        assert verb in out and out.strip(), f"{verb} printed no help"


def test_dedup_edge_json_is_parseable_and_says_whether_repo_ranked():
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        before = p.read_text()
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert fix.main(["dedup-edge", "--map", str(p), "--json"]) == 0
        payload = json.loads(buf.getvalue())
        assert payload["repo_ranked"] is False
        assert len(payload["conflicts"]) == 1
        c = payload["conflicts"][0]
        assert (c["src"], c["verb"], c["dst"]) == ("C1", "calls", "C2")
        assert c["keep_token"].startswith("C1:calls:C2:")
        assert c["suggested"] in c["anchors"]
        assert p.read_text() == before, "--json must not edit the map"


def test_dedup_edge_accept_suggested_resolves_every_conflict():
    """"Take every suggestion" was the intent behind all four failed shell harvests; it had no flag."""
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        assert fix.main(["dedup-edge", "--map", str(p), "--accept-suggested"]) == 0
        edges = load_model_path(p).edges
        assert len(edges) == 1, "every duplicated triple must be resolved to one row"


def test_dedup_edge_says_when_suggestions_are_unranked_for_want_of_repo(capsys):
    """Without --repo the 'exists in the repo' rank term is constant, so the sort degrades to
    shortest-path. A live build passed --repo to the listing it discarded and omitted it from the
    listing it applied, and nothing in the output said the ranking had changed."""
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        assert fix.main(["dedup-edge", "--map", str(p)]) == 0
        assert "no --repo" in capsys.readouterr().out


def test_json_and_accept_suggested_are_refused_as_conflicting_intents():
    """`--json` lists without writing, `--accept-suggested` writes. Together they printed the
    listing, wrote nothing and exited 0 — a script asking to apply and report got a no-op that
    looked like success."""
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        before = p.read_text()
        assert fix.main(["dedup-edge", "--map", str(p), "--json", "--accept-suggested"]) == 2
        assert p.read_text() == before


def test_accept_suggested_never_silently_overrides_an_explicit_keep():
    """A wrong drop is unrecoverable, so the blanket flag must not quietly beat a named choice."""
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        before = p.read_text()
        assert fix.main(["dedup-edge", "--map", str(p), "--accept-suggested",
                         "--keep", "C1:calls:C2:src/b.py:20"]) == 2
        assert p.read_text() == before, "nothing may be dropped while the intent is ambiguous"


def test_grounding_sub_verbs_also_answer_help(capsys):
    """The same hole lived in a second dispatcher; only the `fix` half was covered by a test."""
    from coyomap import grounding
    for verb in ("write", "report"):
        assert grounding.main([verb, "--help"]) == 0, verb
        assert capsys.readouterr().out.strip(), f"grounding {verb} printed no help"


def test_a_verb_s_other_forms_stay_in_its_help_block():
    """`timings record` is documented as three command lines, each starting with the verb; the
    block used to stop at the second one, so `record --help` printed one line of three."""
    from coyomap import subverb_help
    usage = "usage: x <a | b>\n\n  a --one\n  a --two\n      what a does\n\n  b --three\n      what b does\n"
    assert subverb_help.verb_block(usage, "a") == "  a --one\n  a --two\n      what a does"
    assert subverb_help.verb_block(usage, "b") == "  b --three\n      what b does"


def test_subverb_help_falls_back_to_the_whole_usage_when_no_block_matches():
    """The fallback is the branch production actually takes for 2 of the 6 surfaces, so it is the
    one that must never print nothing."""
    from coyomap import subverb_help
    usage = "usage: tool <verb>\n\n  alpha --x\n      does alpha\n  beta --y\n      does beta\n"
    alpha = subverb_help.verb_block(usage, "alpha")
    assert alpha is not None and alpha.strip().startswith("alpha")
    assert subverb_help.verb_block(usage, "nosuchverb") is None
    assert subverb_help.handle(usage, "nosuchverb", ["--help"]) == 0
    assert subverb_help.handle(usage, "alpha", []) is None, "no help asked for → carry on parsing"


def test_dedup_edge_can_record_its_decision_where_assemble_will_reread_it():
    """Writing the choice into the assembled map is what made a shipped map irreproducible from its
    own sources: 365 edges committed, 416 when its committed fragments were re-assembled, the
    difference being 49 duplicates the next assemble silently restored."""
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        before = p.read_text()
        rec = Path(tmp) / "reconcile.json"
        assert fix.main(["dedup-edge", "--map", str(p), "--accept-suggested",
                         "--to-reconcile", str(rec)]) == 0
        assert p.read_text() == before, "--to-reconcile must NOT edit the map"
        doc = json.loads(rec.read_text())
        assert len(doc["keep_edges"]) == 1
        k = doc["keep_edges"][0]
        assert (k["src"], k["verb"], k["dst"]) == ("C1", "calls", "C2") and k["where"]


def test_to_reconcile_merges_into_an_existing_file_without_duplicating():
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        rec = Path(tmp) / "reconcile.json"
        rec.write_text(json.dumps({"set": [{"ids": ["C1"], "subsystem": "S1"}]}), encoding="utf-8")
        assert fix.main(["dedup-edge", "--map", str(p), "--accept-suggested",
                         "--to-reconcile", str(rec)]) == 0
        assert fix.main(["dedup-edge", "--map", str(p), "--accept-suggested",
                         "--to-reconcile", str(rec)]) == 0
        doc = json.loads(rec.read_text())
        assert doc["set"], "an existing directive must survive"
        assert len(doc["keep_edges"]) == 1, "the same triple must not be recorded twice"


def test_the_in_place_dedup_now_says_the_edit_is_not_durable(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        assert fix.main(["dedup-edge", "--map", str(p), "--accept-suggested"]) == 0
        assert "next assemble REBUILDS" in capsys.readouterr().out


def test_to_reconcile_refuses_to_record_an_anchorless_winner():
    """`(no call site)` is the listing's DISPLAY text; `apply_reconcile` matches the stored `where`,
    which is empty for such an edge. Recording the placeholder makes a directive that can never
    match — a permanent no-op warning "none of … is anchored at '(no call site)'" on every
    assemble, phrased as drift rather than as the tool bug it is."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.json"
        p.write_text(json.dumps({
            "format": FORMAT, "title": "T", "goal": "g",
            "components": [{"id": "C1", "name": "A", "source": "backend/src/a.py:1"},
                           {"id": "C2", "name": "B", "source": "backend/src/b.py:1"}],
            # The sibling path must sort LONGER than "(no call site)" (14 chars), or the ranking
            # never selects the placeholder and this test passes without entering the branch —
            # which is exactly how it first shipped.
            "edges": [{"src": "C1", "verb": "calls", "dst": "C2", "no_call_site": True},
                      {"src": "C1", "verb": "calls", "dst": "C2", "where": "backend/src/a.py:10"}],
        }), encoding="utf-8")
        rec = Path(tmp) / "reconcile.json"
        # NON-ZERO: every conflict in this map was skipped, so nothing was recorded and the
        # duplicates remain. Exit 0 with an empty file is what a script reads as success.
        assert fix.main(["dedup-edge", "--map", str(p), "--accept-suggested",
                         "--to-reconcile", str(rec)]) == 1
        recorded = json.loads(rec.read_text()).get("keep_edges", [])
        assert all(k["where"] != "(no call site)" for k in recorded), recorded
        assert not recorded, "the only conflict here has an anchorless winner — nothing to record"


def test_to_reconcile_updates_a_triple_instead_of_silently_keeping_the_old_anchor(capsys):
    """Re-running with a different anchor printed `kept … at <new>` and then wrote nothing — a
    durable record asserting what the artifact did not support."""
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        rec = Path(tmp) / "reconcile.json"
        assert fix.main(["dedup-edge", "--map", str(p), "--to-reconcile", str(rec),
                         "--keep", "C1:calls:C2:src/a.py:10"]) == 0
        assert fix.main(["dedup-edge", "--map", str(p), "--to-reconcile", str(rec),
                         "--keep", "C1:calls:C2:tests/a.py:99"]) == 0
        out = capsys.readouterr().out
        keeps = json.loads(rec.read_text())["keep_edges"]
        assert len(keeps) == 1 and keeps[0]["where"] == "tests/a.py:99", keeps
        assert "UPDATED" in out


def test_to_reconcile_refuses_when_there_is_no_decision_to_record(capsys):
    """`--to-reconcile` names an OUTPUT, and the listing path returned early without ever looking at
    it: a live build ran `dedup-edge --map … --repo … --to-reconcile <file>`, got exit 0 and a full
    conflict listing, and the file was untouched. It only noticed because it read the file back
    afterwards; a build trusting the exit code ships a map whose fragments re-assemble to a
    different edge count — the exact failure this flag exists to prevent."""
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        rec = Path(tmp) / "reconcile.json"
        assert fix.main(["dedup-edge", "--map", str(p), "--to-reconcile", str(rec)]) == 2
        assert not rec.exists(), "nothing may be written when the run is refused"
        err = capsys.readouterr().err
        assert "--accept-suggested" in err and "--keep" in err, err


def test_to_reconcile_refuses_alongside_json(capsys):
    """Same shape as the existing `--json --accept-suggested` refusal: one flag lists, the other
    writes, and `--json` returns before the write path is ever reached."""
    with tempfile.TemporaryDirectory() as tmp:
        p = make_dup_edge_map(tmp)
        rec = Path(tmp) / "reconcile.json"
        assert fix.main(["dedup-edge", "--map", str(p), "--json",
                         "--to-reconcile", str(rec)]) == 2
        assert not rec.exists()
        assert "--json" in capsys.readouterr().err


def test_a_map_with_no_conflicts_is_not_an_error_whatever_the_flags(capsys):
    """The refusal was placed ABOVE the map load, so the healthy end state — nothing left to
    de-duplicate — exited 2. A pipeline that runs the dedup step unconditionally (which is what a
    durable-decision step should do) then broke precisely when the map was correct, and the message
    pushed the operator toward `--accept-suggested` on a map with nothing to accept."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "clean.json"
        p.write_text(json.dumps(make_map([
            {"src": "C1", "verb": "calls", "dst": "C2", "why": "w", "where": "src/a.py:10"},
        ])), encoding="utf-8")
        rec = Path(tmp) / "reconcile.json"
        assert fix.main(["dedup-edge", "--map", str(p), "--to-reconcile", str(rec)]) == 0
        assert "no (src, verb, dst) edge is declared more than once" in capsys.readouterr().out


# --- security-row ---------------------------------------------------------------
# The regression these two verbs exist for: a hand script selected a refuted security row with
# `'admin' in surface.lower() and source.startswith(…)`, matched TWO rows, and overwrote a
# CONFIRMED claim with the refuted one's replacement text. Only `grounding report` caught it.


def make_security_map(rows: list[dict]) -> dict:
    return make_map([{"src": "C1", "verb": "calls", "dst": "C1", "where": "a.py:1"}], security=rows)


def test_security_row_refuses_a_selector_matching_two_rows(capsys):
    """THE headline regression, as a refusal. Two DIFFERENT surfaces share one anchor — legal — and
    a selector that cannot tell them apart must write nothing rather than take the first."""
    m = make_security_map([
        {"surface": "Admin pages", "source": "ui/Sidebar.tsx:97", "risk": "hidden only"},
        {"surface": "Role-gated navigation", "source": "ui/Sidebar.tsx:97", "risk": "real"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        assert fix.main(["security-row", "--map", str(p), "--at", "ui/Sidebar.tsx:97",
                         "--set-risk", "rewritten"]) == 2
        err = capsys.readouterr().err
        assert "matches 2 security row(s)" in err
        after = load_model_path(p)
        assert [s.risk for s in after.security] == ["hidden only", "real"]


def test_security_row_writes_one_row_when_the_selector_is_unambiguous(capsys):
    m = make_security_map([
        {"surface": "Admin pages", "source": "ui/Sidebar.tsx:97", "risk": "hidden only"},
        {"surface": "Role-gated navigation", "source": "ui/Sidebar.tsx:97", "risk": "real"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        assert fix.main(["security-row", "--map", str(p), "--at", "ui/Sidebar.tsx:97",
                         "--surface", "Admin pages", "--set-source", "api/routes.py:12",
                         "--set-risk", "backend 403 is the real gate"]) == 0
        after = load_model_path(p)
        admin = [s for s in after.security if s.surface == "Admin pages"][0]
        other = [s for s in after.security if s.surface == "Role-gated navigation"][0]
        assert admin.source == "api/routes.py:12"
        assert admin.risk == "backend 403 is the real gate"
        # The claim that must NOT have moved.
        assert (other.source, other.risk) == ("ui/Sidebar.tsx:97", "real")
        assert "grounding record no longer names it" in capsys.readouterr().out


def test_security_row_selects_by_the_exact_l2_claim(capsys):
    """The claim string is what a skeptic verdict carries back, so it is the natural selector —
    and it is unique per row even when surfaces or anchors collide."""
    m = make_security_map([
        {"surface": "Admin pages", "source": "ui/Sidebar.tsx:97"},
        {"surface": "Admin pages", "source": "api/routes.py:12"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        claim = fix._security_claim("Admin pages", "ui/Sidebar.tsx:97")
        assert fix.main(["security-row", "--map", str(p), "--claim", claim,
                         "--set-risk", "nothing guards the route"]) == 0
        after = load_model_path(p)
        by_anchor = {s.source: s.risk for s in after.security}
        assert by_anchor["ui/Sidebar.tsx:97"] == "nothing guards the route"
        assert by_anchor["api/routes.py:12"] == ""


def test_security_row_refuses_a_set_with_no_selector(capsys):
    m = make_security_map([{"surface": "Admin pages", "source": "ui/Sidebar.tsx:97"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        assert fix.main(["security-row", "--map", str(p), "--set-risk", "x"]) == 2
        assert "needs a row to write to" in capsys.readouterr().err


# --- dedup-security -------------------------------------------------------------


def test_dedup_security_keys_on_the_surface_not_the_anchor(capsys):
    """Two surfaces sharing one anchor is LEGAL and must not be offered for de-duplication —
    treating it as duplication is what made a hand script delete a real claim."""
    m = make_security_map([
        {"surface": "Admin pages", "source": "ui/Sidebar.tsx:97"},
        {"surface": "Role-gated navigation", "source": "ui/Sidebar.tsx:97"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        assert fix.main(["dedup-security", "--map", str(p)]) == 0
        out = capsys.readouterr().out
        assert "no security surface is authored more than once" in out
        assert "carry MORE THAN ONE surface" in out          # reported, never dropped
        assert len(load_model_path(p).security) == 2


def test_dedup_security_drops_the_duplicate_surface_and_keeps_the_chosen_anchor(capsys):
    m = make_security_map([
        {"surface": "Admin pages", "source": "ui/Sidebar.tsx:97"},
        {"surface": "Admin pages", "source": "api/routes.py:12", "risk": "the real gate"},
        {"surface": "Login", "source": "api/auth.py:5"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        assert fix.main(["dedup-security", "--map", str(p),
                         "--keep", "Admin pages::api/routes.py:12"]) == 0
        after = load_model_path(p)
        assert [(s.surface, s.source) for s in after.security] == [
            ("Admin pages", "api/routes.py:12"), ("Login", "api/auth.py:5")]


def test_dedup_security_refuses_an_anchor_that_names_no_row(capsys):
    m = make_security_map([
        {"surface": "Admin pages", "source": "ui/Sidebar.tsx:97"},
        {"surface": "Admin pages", "source": "api/routes.py:12"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        assert fix.main(["dedup-security", "--map", str(p),
                         "--keep", "Admin pages::nowhere.py:1"]) == 2
        assert "names no duplicate row" in capsys.readouterr().err
        assert len(load_model_path(p).security) == 2


# --- apply-drift --to-reconcile --------------------------------------------------
# An anchor written into the ASSEMBLED map is discarded by the next assemble. A live build
# corrected 14 anchors, re-assembled to pick up one fragment edit, lost all 14, and re-typed them
# by hand out of the human-readable listing.


def test_apply_drift_to_reconcile_records_instead_of_editing_the_map():
    m = make_map([{"src": "C1", "verb": "reads", "dst": "E1", "why": "w", "where": "a.py:1"}])
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
        mp, vp = write(td, m, {"grounding": [make_vote("C1 reads E1", True, "a.py:30")]})
        rec = Path(td) / "reconcile.json"
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp,
                         "--to-reconcile", str(rec)]) == 0
        # the MAP is untouched …
        assert load_model_path(Path(mp)).edges[0].where == "a.py:1"
        # … and the decision is durable
        doc = json.loads(rec.read_text(encoding="utf-8"))
        assert doc["set_anchors"] == [{"claim": "C1 reads E1", "corrected": "a.py:30"}]


def test_a_recorded_anchor_is_applied_by_the_reconcile_pass():
    """The round trip: what `--to-reconcile` records, `assemble --reconcile` must apply — through
    the SAME writer, so the durable record and the in-place edit cannot disagree."""
    from coyomap.model import load_model
    from coyomap.reconcile import apply_reconcile, load_reconcile
    m = load_model(json.dumps(make_map(
        [{"src": "C1", "verb": "reads", "dst": "E1", "why": "w", "where": "a.py:1"}])))
    rec = load_reconcile(json.dumps(
        {"set_anchors": [{"claim": "C1 reads E1", "corrected": "a.py:30"}]}), "rec")
    apply_reconcile(m, rec, {})
    assert m.edges[0].where == "a.py:30"


def test_a_recorded_anchor_whose_claim_is_gone_notes_and_never_fails():
    """A reconcile file must not rot when a later fragment edit rewrites the claim it was keyed on —
    the same 0-match rule `drop_edges` and `keep_edges` already follow."""
    from coyomap.model import load_model
    from coyomap.reconcile import apply_reconcile, load_reconcile
    m = load_model(json.dumps(make_map(
        [{"src": "C1", "verb": "reads", "dst": "E1", "why": "w", "where": "a.py:1"}])))
    rec = load_reconcile(json.dumps(
        {"set_anchors": [{"claim": "Auth surface 'gone' is protected by: nothing",
                          "corrected": "b.py:9"}]}), "rec")
    notes = apply_reconcile(m, rec, {})
    assert m.edges[0].where == "a.py:1"
    assert any("matches no edge, security surface, rule site," in n
               for n in notes)


def test_dedup_security_resolves_rows_that_share_surface_AND_anchor(capsys):
    """The ORDINARY duplicate: two fragments harvested one auth check, so the rows agree on
    everything. Refusing it made the command unable to resolve the case it exists for — and
    `validate`'s advisory points the operator straight here, with no other answer than the hand
    script this replaces."""
    m = make_security_map([
        {"surface": "Admin pages", "source": "ui/Sidebar.tsx:97", "risk": "hidden only"},
        {"surface": "Admin pages", "source": "ui/Sidebar.tsx:97", "risk": "hidden only"},
        {"surface": "Login", "source": "api/auth.py:5"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        assert fix.main(["dedup-security", "--map", str(p), "--accept-suggested"]) == 0
        after = load_model_path(p)
        assert [(s.surface, s.source) for s in after.security] == [
            ("Admin pages", "ui/Sidebar.tsx:97"), ("Login", "api/auth.py:5")]
        assert "identical rows" in capsys.readouterr().out


def test_dedup_security_refuses_same_anchor_rows_that_differ(capsys):
    """Byte-identical rows are not a choice; rows differing in `who`/`risk` still are."""
    m = make_security_map([
        {"surface": "Admin pages", "source": "ui/Sidebar.tsx:97", "risk": "hidden only"},
        {"surface": "Admin pages", "source": "ui/Sidebar.tsx:97", "risk": "the real gate"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        assert fix.main(["dedup-security", "--map", str(p), "--accept-suggested"]) == 2
        assert "IS a decision" in capsys.readouterr().err
        assert len(load_model_path(p).security) == 2


def test_a_keep_token_never_drops_a_row_of_another_surface(capsys):
    """`partition("::")` read the token the tool ITSELF printed for surface `A::B` as surface `A`,
    dropped a row under `A`, and reported success — the original wrong-row-deletion bug class,
    reproduced inside its own fix. Tokens are resolved against the real candidates now."""
    m = make_security_map([
        {"surface": "A", "source": "n.ts:1"},
        {"surface": "A", "source": "B::m.ts:2"},
        {"surface": "A::B", "source": "m.ts:2"},
        {"surface": "A::B", "source": "z.ts:3"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        assert fix.main(["dedup-security", "--map", str(p), "--keep", "A::B::m.ts:2"]) == 2
        assert "ambiguous" in capsys.readouterr().err
        assert len(load_model_path(p).security) == 4      # nothing dropped


def test_dedup_security_json_with_a_decision_is_refused(capsys):
    m = make_security_map([{"surface": "A", "source": "a.ts:1"},
                           {"surface": "A", "source": "b.ts:2"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        assert fix.main(["dedup-security", "--map", str(p), "--json",
                         "--keep", "A::a.ts:1"]) == 2
        assert "Pick one" in capsys.readouterr().err
        assert len(load_model_path(p).security) == 2


def test_apply_drift_to_reconcile_names_the_drifts_it_cannot_write(capsys):
    """The tail said "N drift(s) NOT APPLICABLE … (see above)" with nothing above: the report ran
    only on the in-place path, so the claims needing a hand re-anchor were counted, never named."""
    m = make_map([{"src": "C1", "verb": "writes to", "dst": "E1", "why": "w", "where": "a.py:1"}])
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
        mp, vp = write(td, m, {"grounding": [make_vote("C1 writes to E1", True, "a.py:30")]})
        rec = Path(td) / "reconcile.json"
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp,
                         "--to-reconcile", str(rec)]) == 0
        out = capsys.readouterr()
    combined = out.out + out.err
    assert "NOT APPLICABLE" in combined
    assert "C1 writes to E1" in combined


def test_apply_drift_to_reconcile_leaves_the_file_alone_when_there_is_nothing_to_record(capsys):
    m = make_map([{"src": "C1", "verb": "reads", "dst": "E1", "why": "w", "where": "a.py:30"}])
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "a.py").write_text("x = 1\n" * 40, encoding="utf-8")
        mp, vp = write(td, m, {"grounding": [make_vote("C1 reads E1", True, "a.py:30")]})
        rec = Path(td) / "reconcile.json"
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp,
                         "--to-reconcile", str(rec)]) == 0
        assert not rec.exists()
        assert "was not touched" in capsys.readouterr().out


def test_security_row_refuses_an_empty_surface(capsys):
    """The surface is the row's identity; an unset shell variable would anonymise it silently."""
    m = make_security_map([{"surface": "/signup", "source": "api/signup.py:1"}])
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(m), encoding="utf-8")
        assert fix.main(["security-row", "--map", str(p), "--surface", "/signup",
                         "--set-surface", ""]) == 2
        assert "cannot be empty" in capsys.readouterr().err
        assert load_model_path(p).security[0].surface == "/signup"


def test_two_corrections_landing_on_one_row_are_both_refused():
    """A single-pass writer matched against the model it was mutating, so the outcome depended on
    worklist order: one order applied both corrections, the other skipped the second and left two
    byte-identical security rows behind."""
    from coyomap.audit_model import apply_anchor_corrections, security_claim
    from coyomap.model import load_model
    m = load_model(json.dumps(make_security_map([
        {"surface": "S", "source": "a.py:1"}, {"surface": "S", "source": "b.py:2"}])))
    c0 = (security_claim("S", "a.py:1"), "b.py:2")
    c1 = (security_claim("S", "b.py:2"), "c.py:3")
    counts, notes = apply_anchor_corrections(m, [c0, c1])
    assert counts["security"] == 2
    assert [s.source for s in m.security] == ["b.py:2", "c.py:3"]
    # and the reverse order gives the SAME map
    m2 = load_model(json.dumps(make_security_map([
        {"surface": "S", "source": "a.py:1"}, {"surface": "S", "source": "b.py:2"}])))
    apply_anchor_corrections(m2, [c1, c0])
    assert [s.source for s in m2.security] == ["b.py:2", "c.py:3"]


def test_two_corrections_targeting_the_same_element_are_skipped_not_ordered():
    from coyomap.audit_model import apply_anchor_corrections
    from coyomap.model import load_model
    m = load_model(json.dumps(make_map(
        [{"src": "C1", "verb": "reads", "dst": "E1", "why": "w", "where": "a.py:1"}])))
    counts, notes = apply_anchor_corrections(
        m, [("C1 reads E1", "b.py:2"), ("C1 reads E1", "c.py:3")])
    assert counts["edge"] == 0
    assert m.edges[0].where == "a.py:1"
    assert any("accident of order" in n for n in notes)


# --- drop-edge --to-reconcile ---------------------------------------------------

def test_drop_edge_to_reconcile_records_the_drop_and_leaves_the_map_alone():
    """The durable form `drop-edge` never had. A fragment-level drop is re-derived by the next
    assemble, so an in-place drop has to be redone after every one — one real build hand-wrote the
    same drop three times. `drop_edges` was already a first-class reconcile directive; only the
    writer was missing."""
    m = make_map([{"src": "C1", "verb": "calls", "dst": "E1", "where": "a.py:10"}])
    with tempfile.TemporaryDirectory() as td:
        mp, _ = write(td, m)
        rc = str(Path(td) / "reconcile.json")
        assert fix.drop_edge(["--map", mp, "C1", "calls", "E1", "--to-reconcile", rc]) == 0
        doc = json.loads(Path(rc).read_text(encoding="utf-8"))
        assert doc["drop_edges"] == [{"src": "C1", "verb": "calls", "dst": "E1"}], doc
        assert len(load_model_path(mp).edges) == 1, "the MAP must not be edited"


def test_drop_edge_to_reconcile_refuses_an_edge_the_map_does_not_have():
    """`drop_edges` only WARNS on a 0-match at assemble time, so a directive naming a missing edge
    would rot silently. It is verified against the map when it is written instead."""
    m = make_map([{"src": "C1", "verb": "calls", "dst": "E1", "where": "a.py:10"}])
    with tempfile.TemporaryDirectory() as td:
        mp, _ = write(td, m)
        rc = str(Path(td) / "reconcile.json")
        assert fix.drop_edge(["--map", mp, "C1", "reads", "E2", "--to-reconcile", rc]) == 1
        assert not Path(rc).exists(), "nothing may be written for an edge that is not there"


def test_drop_edge_to_reconcile_updates_rather_than_duplicating():
    """Re-running with a heal must not leave two directives for one edge, which assemble would apply
    twice."""
    m = make_map([{"src": "C1", "verb": "calls", "dst": "E1", "where": "a.py:10"}])
    with tempfile.TemporaryDirectory() as td:
        mp, _ = write(td, m)
        rc = str(Path(td) / "reconcile.json")
        fix.drop_edge(["--map", mp, "C1", "calls", "E1", "--to-reconcile", rc])
        fix.drop_edge(["--map", mp, "C1", "calls", "E1", "--to-reconcile", rc, "--drop-steps"])
        doc = json.loads(Path(rc).read_text(encoding="utf-8"))
        assert len(doc["drop_edges"]) == 1, doc
        assert doc["drop_edges"][0]["drop_steps"] is True


def test_drop_edge_to_reconcile_emits_a_directive_the_real_loader_accepts():
    """The file is input to `assemble --reconcile`, so it must load through the real parser — the
    `reconcile --dry-run` class of defect is a writer emitting something the consumer rejects."""
    from coyomap.reconcile import load_reconcile
    m = make_map([{"src": "C1", "verb": "calls", "dst": "E1", "where": "a.py:10"}])
    with tempfile.TemporaryDirectory() as td:
        mp, _ = write(td, m)
        rc = str(Path(td) / "reconcile.json")
        fix.drop_edge(["--map", mp, "C1", "calls", "E1", "--to-reconcile", rc, "--repoint", "E2"])
        doc = load_reconcile(Path(rc).read_text(encoding="utf-8"), "reconcile.json")
        assert [(d.src, d.verb, d.dst, d.repoint) for d in doc.drop_edges] == [
            ("C1", "calls", "E1", "E2")]


def test_drop_edge_to_reconcile_preserves_directives_another_writer_left():
    """Three commands write this one file; a writer that clobbered the others would silently undo an
    anchor correction."""
    m = make_map([{"src": "C1", "verb": "calls", "dst": "E1", "where": "a.py:10"}])
    with tempfile.TemporaryDirectory() as td:
        mp, _ = write(td, m)
        rc = Path(td) / "reconcile.json"
        rc.write_text(json.dumps({"set": [{"ids": ["C1"], "subsystem": "S1"}]}), encoding="utf-8")
        fix.drop_edge(["--map", mp, "C1", "calls", "E1", "--to-reconcile", str(rc)])
        doc = json.loads(rc.read_text(encoding="utf-8"))
        assert doc["set"] == [{"ids": ["C1"], "subsystem": "S1"}], doc
        assert len(doc["drop_edges"]) == 1


# --- an argument error carries the cure (retro 2026-08-14) ---------------------------------------
# A live build guessed `drop-edge --src C1 --verb reads --dst E24`, got a bare
# `ERROR: unknown option '--src'` five times, and spent a turn on `--help` to learn the arguments
# are positional. The usage text existed and the dispatcher knew the verb; withholding it was a
# choice. Every dispatched verb now answers through `subverb_help.usage_error`.

def test_an_unknown_option_prints_that_verbs_usage_block(capsys):
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.json"
        m.write_text(json.dumps(make_map([{"src": "C1", "verb": "reads", "dst": "E1",
                                           "where": "a.py:1"}])), encoding="utf-8")
        assert fix.main(["drop-edge", "--map", str(m), "--src", "C1"]) == 2
        err = capsys.readouterr().err
        assert "unknown option '--src'" in err, err
        assert "drop-edge --map <map> <src> <verb> <dst>" in err, err


def test_the_usage_block_shown_is_the_one_for_the_verb_that_failed(capsys):
    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.json"
        m.write_text(json.dumps(make_map([{"src": "C1", "verb": "reads", "dst": "E1",
                                           "where": "a.py:1"}])), encoding="utf-8")
        assert fix.main(["dedup-relation", "--map", str(m), "--nope"]) == 2
        err = capsys.readouterr().err
        assert "dedup-relation" in err
        assert "drop-edge --map <map> <src> <verb> <dst>" not in err, "showed another verb's block"


def test_every_dispatched_fix_verb_answers_an_unknown_option_with_usage(capsys):
    """The six `--help` holes were six parsers forgetting the same thing separately. This is the pin
    that stops a seventh parser being written without the cure."""
    from coyomap.subverb_help import verb_block

    with tempfile.TemporaryDirectory() as td:
        m = Path(td) / "m.json"
        m.write_text(json.dumps(make_map([{"src": "C1", "verb": "reads", "dst": "E1",
                                           "where": "a.py:1"}])), encoding="utf-8")
        for verb in ("apply-drift", "drop-edge", "dedup-relation", "dedup-edge",
                     "security-row", "dedup-security"):
            assert fix.main([verb, "--map", str(m), "--definitely-not-a-flag"]) == 2, verb
            err = capsys.readouterr().err
            assert "unknown" in err, (verb, err)
            block = verb_block(fix._USAGE, verb)
            assert block and block.splitlines()[0].strip() in err, (verb, err)


# --- fix row: the writer for a row's own text, in its owning fragment (retro 2026-08-14) ----------
# Half a real map's L2 worklist (192 of 373 claims) is rules with no repair path. `fix security-row`
# was built for exactly this failure and the T7 fold moved auth surfaces out of the array it reaches.

def make_frag_dir(td: str, **files: dict) -> Path:
    d = Path(td) / "frags"
    d.mkdir(parents=True, exist_ok=True)
    (d / "header.json").write_text(json.dumps({"format": FORMAT, "title": "t", "goal": "g"}),
                                   encoding="utf-8")
    for name, doc in files.items():
        (d / f"{name}.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return d


def make_rule(rid: str, statement: str, *, where: str = "a.py:1", risk: str = "r") -> dict:
    return {"id": rid, "name": statement[:20], "statement": statement, "risk": risk,
            "sites": [{"where": where, "why": "guards the API"}]}


def test_row_rewrites_the_field_in_the_owning_fragment():
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1",
                         "--set-risk", "an unguarded surface leaks"]) == 0
        doc = json.loads((d / "r1.json").read_text())
        assert doc["rules"][0]["risk"] == "an unguarded surface leaks"
        assert doc["rules"][0]["statement"] == "A token is checked", "only the named field moves"


def test_row_can_set_several_fields_at_once():
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1",
                         "--set-risk", "R2", "--set-name", "Token gate"]) == 0
        doc = json.loads((d / "r1.json").read_text())
        assert (doc["rules"][0]["risk"], doc["rules"][0]["name"]) == ("R2", "Token gate")


def test_row_refuses_an_edit_that_would_SPLIT_a_merged_row(capsys):
    """`assemble` merges rules on normalised statement + site set, so rewording one mints an id that
    did not exist before — and the digest used to say `ops: none` while it happened."""
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td,
                          r1={"rules": [make_rule("BR1", "A token is checked")]},
                          r2={"rules": [make_rule("BR9", "A token is checked")]})
        before = (d / "r1.json").read_text()
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1",
                         "--set-statement", "A token is verified"]) == 2
        err = capsys.readouterr().err
        assert "would APPEAR: BR9" in err, err
        assert (d / "r1.json").read_text() == before, "nothing may be written on a refusal"


def test_row_refuses_an_edit_that_would_RETIRE_an_id(capsys):
    """The inverse: text that comes to match another row collapses two into one, and every reference
    to the retired id is silently re-pointed."""
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td,
                          r1={"rules": [make_rule("BR1", "A token is checked")]},
                          r2={"rules": [make_rule("BR9", "A plan has a cap")]})
        before = (d / "r2.json").read_text()
        assert fix.main(["row", "--fragments", str(d), "--id", "BR9",
                         "--set-statement", "A token is checked"]) == 2
        err = capsys.readouterr().err
        assert "would DISAPPEAR: BR9" in err, err
        assert (d / "r2.json").read_text() == before


def test_row_refuses_an_id_declared_by_two_fragments(capsys):
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td,
                          r1={"rules": [make_rule("BR1", "A token is checked")]},
                          r2={"rules": [make_rule("BR1", "A plan has a cap")]})
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1", "--set-risk", "x"]) == 2
        err = capsys.readouterr().err
        assert "declared by 2 fragment rows" in err, err
        assert "r1.json" in err and "r2.json" in err


def test_row_says_why_an_entry_point_id_cannot_be_addressed(capsys):
    """EP ids are MINTED at assemble and re-sorted by content — one anchor edit moved 22 of 104 on a
    real map — so an index keyed on them would address the wrong row. The verb reaches authored ids
    only, and says so rather than reporting a bare 'not found'."""
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, h1={"entry_points": [
            {"kind": "cli", "trigger": "run it", "source": "a.py:1", "component": "C1"}]})
        assert fix.main(["row", "--fragments", str(d), "--id", "EP1", "--set-trigger", "x"]) == 2
        err = capsys.readouterr().err
        assert "MINTED at assemble" in err, err


def test_row_refuses_an_anchor_field_and_names_the_verb_that_owns_it(capsys):
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, h1={"components": [{"id": "C1", "name": "A", "source": "a.py:1"}]})
        assert fix.main(["row", "--fragments", str(d), "--id", "C1", "--set-source", "b.py:2"]) == 2
        assert "apply-drift" in capsys.readouterr().err


def test_row_refuses_a_reconcile_owned_field_and_names_reconcile(capsys):
    """On one real map ALL 66 rules take their `block` from reconcile.json and no fragment carries
    one, so writing it here would be overwritten by the next assemble without a word."""
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        for field_name in ("block", "subsystem", "capability", "runs_in", "subdomain"):
            assert fix.main(["row", "--fragments", str(d), "--id", "BR1",
                             f"--set-{field_name}", "X"]) == 2, field_name
            assert "reconcile.json" in capsys.readouterr().err, field_name


def test_row_never_invents_a_field_the_row_does_not_carry(capsys):
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1", "--set-porpoise", "x"]) == 2
        err = capsys.readouterr().err
        # One check, one message. `row` used to run the same test twice — an early pass printing
        # "Present:" and a later one printing "Present fields:" — and the batch refactor kept the
        # second, so the refusal is one line instead of two identical ones.
        assert "has no field(s) porpoise" in err and "Present fields:" in err


def test_row_is_a_no_op_when_the_text_already_says_that(capsys):
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked", risk="r")]})
        before = (d / "r1.json").read_text()
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1", "--set-risk", "r"]) == 0
        assert "already says that" in capsys.readouterr().out
        assert (d / "r1.json").read_text() == before


def test_row_warns_that_a_text_edit_invalidates_the_skeptics_verdicts(capsys):
    """A claim is keyed by its rendered TEXT and `grounding.live_claims_digest` is a hash over them,
    so a statement edit strands every verdict for that row. `finalize` refuses on the stale digest."""
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1",
                         "--set-statement", "A token is verified against its issuer"]) == 0
        out = capsys.readouterr().out
        assert "grounding write" in out and "live_claims_digest" in out, out


def test_row_refuses_when_the_fragments_do_not_assemble_as_they_stand(capsys):
    """The guard cannot say what an edit changes if the baseline is already broken — so it refuses
    rather than writing blind."""
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td,
                          r1={"rules": [make_rule("BR1", "A token is checked")]},
                          r2={"rules": [make_rule("BR1", "A plan has a cap")]})
        (d / "r2.json").write_text(json.dumps({"rules": [make_rule("BR2", "A plan has a cap")],
                                               "components": [{"id": "C1", "name": "A",
                                                               "source": "a.py:1"}]}),
                                   encoding="utf-8")
        (d / "r3.json").write_text(json.dumps({"components": [{"id": "C1", "name": "B",
                                                               "source": "b.py:1"}]}),
                                   encoding="utf-8")
        rc = fix.main(["row", "--fragments", str(d), "--id", "BR1", "--set-risk", "x"])
        capsys.readouterr()
        assert rc == 2


def test_row_edits_a_single_named_fragment_file_too():
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        assert fix.main(["row", "--fragments", str(d / "r1.json"), "--id", "BR1",
                         "--set-risk", "R9"]) == 0
        assert json.loads((d / "r1.json").read_text())["rules"][0]["risk"] == "R9"


def test_row_requires_at_least_one_set_flag(capsys):
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1"]) == 2
        assert "at least one --set-" in capsys.readouterr().err


def test_row_edits_survive_a_re_assemble_which_is_the_whole_point():
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1", "--set-risk", "durable"]) == 0
        from coyomap import assemble as _asm
        assert _asm.main([*[str(p) for p in sorted(d.glob("*.json"))], "--out", str(d.parent)]) == 0
        m = json.loads((d.parent / "project-map.json").read_text())
        assert m["rules"][0]["risk"] == "durable"


# --- dedup-relation can finally record its answer (retro 2026-08-14) ------------------------------

def make_relation_map_doc(relations: list[dict]) -> dict:
    return {"format": FORMAT, "title": "t", "goal": "g",
            "use_cases": [{"id": "UC1", "name": "Do"}],
            "components": [{"id": "C1", "name": "A", "source": "a.py:1"}],
            "entities": [{"id": "E1", "name": "Thing", "relations": relations},
                         {"id": "E2", "name": "Other"}]}


def test_dedup_relation_records_the_drop_and_leaves_the_map_alone():
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "map.json"
        mp.write_text(json.dumps(make_relation_map_doc(
            [{"verb": "has", "target": "E2"}, {"verb": "has", "target": "E2"}])), encoding="utf-8")
        before = mp.read_text()
        rec = Path(td) / "reconcile.json"
        assert fix.main(["dedup-relation", "--map", str(mp), "--drop", "E1:has:E2",
                         "--to-reconcile", str(rec)]) == 0
        assert mp.read_text() == before, "the MAP must not be edited on the recording path"
        assert json.loads(rec.read_text())["drop_relations"] == [
            {"entity": "E1", "verb": "has", "target": "E2"}]


def test_dedup_relation_merges_into_an_existing_reconcile_file():
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "map.json"
        mp.write_text(json.dumps(make_relation_map_doc(
            [{"verb": "has", "target": "E2"}, {"verb": "has", "target": "E2"}])), encoding="utf-8")
        rec = Path(td) / "reconcile.json"
        rec.write_text(json.dumps({"drop_edges": [{"src": "C1", "verb": "reads", "dst": "E2"}]}),
                       encoding="utf-8")
        assert fix.main(["dedup-relation", "--map", str(mp), "--drop", "E1:has:E2",
                         "--to-reconcile", str(rec)]) == 0
        doc = json.loads(rec.read_text())
        assert doc["drop_edges"] and doc["drop_relations"], doc


def test_dedup_relation_records_each_drop_a_relation_actually_needs(capsys):
    """A relation declared twice needs TWO drop tokens, and the listing prints the token twice.
    Presence-based dedup silently refused the second while still printing "recorded" and exiting 0,
    so an operator following the listing one token at a time shipped a map that still blocked."""
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "map.json"
        mp.write_text(json.dumps(make_relation_map_doc(
            [{"verb": "has", "target": "E2"}, {"verb": "has", "target": "E2"}])), encoding="utf-8")
        rec = Path(td) / "reconcile.json"
        for _ in range(2):
            assert fix.main(["dedup-relation", "--map", str(mp), "--drop", "E1:has:E2",
                             "--to-reconcile", str(rec)]) == 0
        capsys.readouterr()
        assert len(json.loads(rec.read_text())["drop_relations"]) == 2


def test_dedup_relation_refuses_to_record_more_drops_than_the_map_declares(capsys):
    """The ceiling is what the map actually declares — beyond it a repeat is a mistake worth naming,
    not a silent no-op that reads as success."""
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "map.json"
        mp.write_text(json.dumps(make_relation_map_doc(
            [{"verb": "has", "target": "E2"}, {"verb": "has", "target": "E2"}])), encoding="utf-8")
        rec = Path(td) / "reconcile.json"
        for _ in range(2):
            fix.main(["dedup-relation", "--map", str(mp), "--drop", "E1:has:E2",
                      "--to-reconcile", str(rec)])
        capsys.readouterr()
        assert fix.main(["dedup-relation", "--map", str(mp), "--drop", "E1:has:E2",
                         "--to-reconcile", str(rec)]) == 2
        err = capsys.readouterr().err
        assert "already records 2 drop(s)" in err, err
        assert len(json.loads(rec.read_text())["drop_relations"]) == 2, "the file must be unchanged"


def test_dedup_relation_to_reconcile_refuses_when_there_is_no_decision(capsys):
    """`--to-reconcile` on its own would print the listing, write nothing and exit 0 — which reads as
    success. `dedup-edge` was fixed for exactly this; the sibling verb inherits the rule."""
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "map.json"
        mp.write_text(json.dumps(make_relation_map_doc(
            [{"verb": "has", "target": "E2"}, {"verb": "has", "target": "E2"}])), encoding="utf-8")
        rec = Path(td) / "reconcile.json"
        assert fix.main(["dedup-relation", "--map", str(mp), "--to-reconcile", str(rec)]) == 2
        assert "needs a decision" in capsys.readouterr().err
        assert not rec.exists()


def test_the_in_place_dedup_relation_now_says_the_edit_is_not_durable(capsys):
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "map.json"
        mp.write_text(json.dumps(make_relation_map_doc(
            [{"verb": "has", "target": "E2"}, {"verb": "has", "target": "E2"}])), encoding="utf-8")
        assert fix.main(["dedup-relation", "--map", str(mp), "--drop", "E1:has:E2"]) == 0
        out = capsys.readouterr().out
        assert "BLOCKS" in out and "--to-reconcile" in out, out


# --- regressions from the adversarial review of `fix row` (2026-08-14) ----------------------------
# Every one of these was a defect the first version shipped.

def test_row_refuses_when_a_SIBLING_fragment_fails_to_load():
    """THE critical one. `load_fragment_paths` returns `(parts, notes, errors)`; unpacking it as
    `(parts, problems, notes)` threw the errors away, so a fragment that failed to load was silently
    DROPPED from the set the guard assembled — and an edit that merged two rules away reported
    nothing and exited 0."""
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td,
                          r1={"rules": [make_rule("BR1", "A token is checked")]},
                          r2={"rules": [make_rule("BR9", "A plan has a cap")]})
        (d / "broken.json").write_text(json.dumps({"extras": "a string, not a list"}),
                                       encoding="utf-8")
        before = (d / "r1.json").read_text()
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1",
                         "--set-statement", "A plan has a cap"]) == 2
        assert (d / "r1.json").read_text() == before, "an unverifiable edit must not be written"


def test_a_draft_fragment_is_a_NOTE_and_must_not_block_an_edit():
    """The mirror failure of the same unpack: `assemble` deliberately SKIPS a `*.draft.json` (the
    harvest contract tells agents to write one), and reading notes as problems refused every edit in
    the directory while `assemble` itself was perfectly happy."""
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        (d / "half-written.draft.json").write_text('{"rules": []}', encoding="utf-8")
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1", "--set-risk", "R"]) == 0


def test_row_refuses_a_coyomap_dir_and_never_edits_the_assembled_map(capsys):
    """Pointing `--fragments` at `.coyomap/` instead of `.coyomap/build-fragments/` is the obvious
    slip, and it used to edit `project-map.json` — the build product the verb exists to avoid."""
    with tempfile.TemporaryDirectory() as td:
        coy = Path(td) / ".coyomap"
        coy.mkdir()
        (coy / "project-map.json").write_text(json.dumps(
            {**make_map([]), "rules": [make_rule("BR1", "A token is checked")]}), encoding="utf-8")
        (coy / "reconcile.json").write_text("{}", encoding="utf-8")
        before = (coy / "project-map.json").read_text()
        assert fix.main(["row", "--fragments", str(coy), "--id", "BR1", "--set-risk", "R"]) == 2
        assert "build-fragments" in capsys.readouterr().err
        assert (coy / "project-map.json").read_text() == before


def test_row_leaves_no_check_file_behind_in_the_fragment_directory():
    """A leftover `*.fixrow-check.json` breaks every later assemble with a duplicate-id conflict, and
    the `.draft.json` skip does not cover that name."""
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1", "--set-risk", "R"]) == 0
        assert sorted(p.name for p in d.glob("*.json")) == ["header.json", "r1.json"]


def test_row_refuses_a_missing_value_that_is_another_flag(capsys):
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1",
                         "--set-name", "--set-risk", "x"]) == 2
        assert "another flag" in capsys.readouterr().err


def test_row_refuses_to_blank_a_field(capsys):
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token is checked")]})
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1", "--set-risk", "   "]) == 2
        assert "deletes the text" in capsys.readouterr().err


def test_row_keeps_an_ascii_escaped_fragment_ascii_escaped():
    """A one-field edit used to rewrite every `\\uXXXX` in the file, burying the real change."""
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, r1={"rules": [make_rule("BR1", "A token — checked")]})
        assert (d / "r1.json").read_bytes().isascii()
        assert fix.main(["row", "--fragments", str(d), "--id", "BR1", "--set-risk", "R"]) == 0
        assert (d / "r1.json").read_bytes().isascii(), "escaping style must be preserved"


# --- the duplicate-relation listing is labelled by SHAPE, and the labels are pinned ---------------
# Found by sweeping for the shape that hid the loader bug: two same-typed lists, returned
# positionally, BOTH EMPTY on a healthy map — so a swap is invisible to every clean-fixture test.
# Verified before fixing: swapping this function's two returns passed all 1916 tests.

def make_relation_model(entities: list[dict]):
    from coyomap.model import load_model
    return load_model(json.dumps({**make_map([]), "entities": entities}))


def test_a_relation_declared_twice_on_one_card_is_labelled_same_card():
    m = make_relation_model([{"id": "E1", "name": "Thing",
                              "relations": [{"verb": "has", "target": "E2"},
                                            {"verb": "has", "target": "E2"}]},
                             {"id": "E2", "name": "Other"}])
    dupes = fix._duplicate_relations(m)
    assert dupes.same_card == ["E1:has:E2"]
    assert dupes.reciprocal == []


def test_a_pair_authored_from_both_cards_is_labelled_reciprocal():
    m = make_relation_model([{"id": "E1", "name": "Thing",
                              "relations": [{"verb": "has", "target": "E2"}]},
                             {"id": "E2", "name": "Other",
                              "relations": [{"verb": "belongs to", "target": "E1"}]}])
    dupes = fix._duplicate_relations(m)
    assert dupes.reciprocal == ["E1:has:E2"]
    assert dupes.same_card == []


def test_a_healthy_map_reports_neither_shape():
    m = make_relation_model([{"id": "E1", "name": "Thing",
                              "relations": [{"verb": "has", "target": "E2"}]},
                             {"id": "E2", "name": "Other"}])
    dupes = fix._duplicate_relations(m)
    assert (dupes.same_card, dupes.reciprocal) == ([], [])


def test_the_two_shapes_are_reachable_only_by_name():
    m = make_relation_model([{"id": "E1", "name": "Thing", "relations": []}])
    try:
        _a, _b = fix._duplicate_relations(m)          # type: ignore[misc]
    except TypeError:
        return
    raise AssertionError("the result is still unpackable — a swap stays writable")


def test_the_listing_prints_each_shape_under_its_own_heading(capsys):
    """The two shapes need different operator action, so a silent swap mislabels the listing the
    operator acts on — which is what made this worth naming rather than merely documenting."""
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "map.json"
        mp.write_text(json.dumps({**make_map([]), "entities": [
            {"id": "E1", "name": "Thing", "relations": [{"verb": "has", "target": "E2"},
                                                        {"verb": "has", "target": "E2"}]},
            {"id": "E2", "name": "Other", "relations": [{"verb": "belongs to", "target": "E1"}]}]}),
            encoding="utf-8")
        assert fix.main(["dedup-relation", "--map", str(mp)]) == 0
        out = capsys.readouterr().out
    same_at = out.index("Same-card duplicates")
    recip_at = out.index("Reciprocal")
    assert out.index("E1:has:E2", same_at) < recip_at, out


def test_drop_all_refuses_to_make_a_reciprocal_judgement_for_you():
    """`--drop-all` exists because passing 33 printed tokens back as 33 flags cost five turns of
    shell quoting. It must NOT extend to reciprocal pairs: which of two cards keeps the relation is
    a modelling judgement, and `fix`'s own header warns that a wrong drop deletes a real domain
    fact. Sweeping those silently would trade a quoting problem for a correctness one."""
    import json, tempfile, os
    from coyomap.fix import main
    m = {"format": "coyomap-map", "title": "t", "goal": "g",
         "entities": [
             {"id": "E1", "name": "Order", "source": "a.py:1", "meaning": "m",
              "store": {"dep": "D1", "container": "o", "mode": "collection"},
              "relations": [{"target": "E2", "verb": "hasMany", "how": "oid"}]},
             {"id": "E2", "name": "Line", "source": "b.py:1", "meaning": "m",
              "store": {"dep": "D1", "container": "l", "mode": "collection"},
              "relations": [{"target": "E1", "verb": "belongsTo", "how": "oid"}]},
         ],
         "deps": [{"id": "D1", "name": "db", "kind": "datastore"}]}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "m.json")
        with open(p, "w") as fh:
            json.dump(m, fh)
        assert main(["dedup-relation", "--map", p, "--drop-all"]) == 2
        # and the map is untouched
        with open(p) as fh:
            after = json.load(fh)
        assert len(after["entities"][0]["relations"]) == 1
        assert len(after["entities"][1]["relations"]) == 1


def _frag_dir(tmp, doc):
    import json, os
    d = os.path.join(tmp, "frags")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "domain.json"), "w") as fh:
        json.dump(doc, fh)
    return d


def _entity_doc():
    return {"deps": [{"id": "D1", "name": "db", "kind": "datastore"}],
            "entities": [{"id": "E1", "name": "Order", "source": "a.py:1", "meaning": "an order",
                          "store": {"dep": "D1", "container": "o", "mode": "collection"},
                          "states": {"states": ["new", "done"],
                                     "transitions": [{"src": "new", "dst": "done", "on": "finish"}],
                                     "source": "a.py:9"}}]}


def test_a_structured_field_can_be_rewritten_without_a_hand_script():
    """`--set-<field> <text>` writes a STRING, which is right for a meaning or a statement and
    useless for the rest: an entity's `states` block, a lifecycle `states.source`, a messaging row's
    consumers, a rule's sites. Those are exactly the four edits builds hand-scripted into fragments
    with `python3 - <<'PY'` — the failure `fix` exists to remove — and the reason they hand-scripted
    them is that no flag could express a nested value."""
    import json, tempfile, os
    from coyomap.fix import main
    with tempfile.TemporaryDirectory() as tmp:
        d = _frag_dir(tmp, _entity_doc())
        new = {"states": ["open", "closed"],
               "transitions": [{"src": "open", "dst": "closed", "on": "resolve"}],
               "source": "b.py:3"}
        assert main(["row", "--fragments", d, "--id", "E1",
                     "--set-json-states", json.dumps(new)]) == 0
        with open(os.path.join(d, "domain.json")) as fh:
            assert json.load(fh)["entities"][0]["states"] == new


def test_a_structured_edit_that_would_break_assembly_is_refused_like_a_text_one():
    """The JSON path must inherit every guard the text path has — it is the same write."""
    import json, tempfile, os
    from coyomap.fix import main
    with tempfile.TemporaryDirectory() as tmp:
        d = _frag_dir(tmp, _entity_doc())
        before = open(os.path.join(d, "domain.json")).read()
        assert main(["row", "--fragments", d, "--id", "E1", "--set-json-states", '"not an object"']) == 2
        assert open(os.path.join(d, "domain.json")).read() == before, "nothing may be written"


def test_a_field_the_row_does_not_have_is_refused_rather_than_invented():
    """Adding a key is a schema change, not a correction — and a typo'd field name would otherwise
    write a new one silently and pass every downstream check."""
    import tempfile
    from coyomap.fix import main
    with tempfile.TemporaryDirectory() as tmp:
        d = _frag_dir(tmp, _entity_doc())
        assert main(["row", "--fragments", d, "--id", "E1", "--set-json-staets", "[]"]) == 2


# --- addressing an EDGE, which carries no id ---------------------------------------
# A fragment edge's identity is its `(src, verb, dst)` triple, so `--id` could never reach one. That
# is the whole reason three heredocs on one build rewrote an edge's `why` by hand — two turns after
# using `fix row` correctly on a component. The verb existed; the ADDRESS did not.

def _edge_fragment(tmp: Path, why: str = "reads the settings") -> Path:
    d = tmp / "build-fragments"
    d.mkdir(parents=True, exist_ok=True)
    (d / "t1.json").write_text(json.dumps({
        "components": [{"id": "C1", "name": "A", "purpose": "does a thing.",
                        "files": ["a.py"], "source": "a.py:1"},
                       {"id": "C2", "name": "B", "purpose": "does another thing.",
                        "files": ["b.py"], "source": "b.py:1"}],
        "edges": [{"src": "C1", "verb": "calls", "dst": "C2", "why": why, "where": "a.py:9"}],
    }), encoding="utf-8")
    return d


def _edge_why(d: Path) -> str:
    doc = json.loads((d / "t1.json").read_text(encoding="utf-8"))
    return doc["edges"][0]["why"]


def test_an_edge_why_is_addressable_by_its_triple(tmp_path: Path) -> None:
    from coyomap.fix import main
    d = _edge_fragment(tmp_path)
    assert main(["row", "--fragments", str(d), "--edge", "C1:calls:C2",
                 "--set-why", "hands the request on"]) == 0
    assert _edge_why(d) == "hands the request on"


def test_a_triple_that_matches_nothing_is_refused_not_guessed(tmp_path: Path) -> None:
    from coyomap.fix import main
    d = _edge_fragment(tmp_path)
    assert main(["row", "--fragments", str(d), "--edge", "C1:reads:C2", "--set-why", "x"]) == 2
    assert _edge_why(d) == "reads the settings", "nothing may be written on a failed resolve"


def test_a_malformed_triple_is_a_usage_error(tmp_path: Path) -> None:
    from coyomap.fix import main
    d = _edge_fragment(tmp_path)
    assert main(["row", "--fragments", str(d), "--edge", "C1:calls", "--set-why", "x"]) == 2
    assert main(["row", "--fragments", str(d), "--edge", "C1::C2", "--set-why", "x"]) == 2


def test_id_and_edge_are_not_combinable(tmp_path: Path) -> None:
    """They address different things; guessing which one the caller meant is the failure mode every
    other resolver here refuses."""
    from coyomap.fix import main
    d = _edge_fragment(tmp_path)
    assert main(["row", "--fragments", str(d), "--id", "C1", "--edge", "C1:calls:C2",
                 "--set-why", "x"]) == 2


def test_neither_id_nor_edge_is_a_usage_error(tmp_path: Path) -> None:
    from coyomap.fix import main
    d = _edge_fragment(tmp_path)
    assert main(["row", "--fragments", str(d), "--set-why", "x"]) == 2


# --- `fix rows`: the batch form ------------------------------------------------------------------
#
# One build made 37 single `fix row` calls and 8 identical hand edits beside them — twelve
# consecutive turns rewriting one file, eight of them the same one-word verb change on eight arrows
# into one box. Each call re-read every fragment and re-ran the assembly check, and each cost a turn.

def make_edge(src: str, verb: str, dst: str, *, why: str = "w", where: str = "a.py:1") -> dict:
    return {"src": src, "verb": verb, "dst": dst, "why": why, "where": where}


def make_component(cid: str, name: str) -> dict:
    return {"id": cid, "name": name, "purpose": f"{name} does a thing", "source": "a.py:1"}


def make_edits_file(td: str, edits: list) -> Path:
    p = Path(td) / "edits.json"
    p.write_text(json.dumps(edits), encoding="utf-8")
    return p


def make_edge_dir(td: str) -> Path:
    return make_frag_dir(td, e1={
        "components": [make_component("C1", "one"), make_component("C2", "two"),
                       make_component("C3", "three")],
        "edges": [make_edge("C1", "emits", "C2"), make_edge("C1", "emits", "C3")]})


def read_edges(d: Path) -> list[tuple]:
    doc = json.loads((d / "e1.json").read_text(encoding="utf-8"))
    return [(e["src"], e["verb"], e["dst"]) for e in doc["edges"]]


def test_one_call_changes_the_verb_on_every_arrow_in_the_batch() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = make_edge_dir(td)
        edits = make_edits_file(td, [{"edge": "C1:emits:C2", "set": {"verb": "queues"}},
                                     {"edge": "C1:emits:C3", "set": {"verb": "queues"}}])
        assert fix.main(["rows", "--fragments", str(d), "--edits", str(edits)]) == 0
        assert read_edges(d) == [("C1", "queues", "C2"), ("C1", "queues", "C3")]


def test_a_batch_reports_every_fault_at_once_and_writes_nothing(capsys) -> None:
    """A batch of twenty that reports its faults one run at a time is the loop this verb ends."""
    with tempfile.TemporaryDirectory() as td:
        d = make_edge_dir(td)
        before = read_edges(d)
        edits = make_edits_file(td, [{"id": "NOPE1", "set": {"purpose": "x"}},
                                     {"edge": "C1:nope:C2", "set": {"why": "y"}},
                                     {"edge": "C1:emits:C3", "set": {"why": "  "}}])
        assert fix.main(["rows", "--fragments", str(d), "--edits", str(edits)]) == 2
        err = capsys.readouterr().err
        assert "3 problem(s)" in err and "nothing was written" in err
        assert read_edges(d) == before


def test_moving_an_edge_onto_a_triple_that_exists_is_refused(capsys) -> None:
    """That is a merge, not a rewrite — `assemble` would hold the same relation twice."""
    with tempfile.TemporaryDirectory() as td:
        d = make_edge_dir(td)
        edits = make_edits_file(td, [{"edge": "C1:emits:C3", "set": {"dst": "C2"}}])
        assert fix.main(["rows", "--fragments", str(d), "--edits", str(edits)]) == 2
        assert "collides with an edge that already exists" in capsys.readouterr().err
        assert read_edges(d) == [("C1", "emits", "C2"), ("C1", "emits", "C3")]


def test_two_edits_that_would_become_the_same_edge_are_refused(capsys) -> None:
    with tempfile.TemporaryDirectory() as td:
        d = make_edge_dir(td)
        edits = make_edits_file(td, [{"edge": "C1:emits:C2", "set": {"verb": "queues"}},
                                     {"edge": "C1:emits:C3", "set": {"verb": "queues",
                                                                     "dst": "C2"}}])
        assert fix.main(["rows", "--fragments", str(d), "--edits", str(edits)]) == 2
        assert "one batch cannot make two edges the same edge" in capsys.readouterr().err


def test_two_edits_addressing_one_row_are_refused(capsys) -> None:
    """Two edits to one row in one batch is an order that is not written down."""
    with tempfile.TemporaryDirectory() as td:
        d = make_edge_dir(td)
        edits = make_edits_file(td, [{"edge": "C1:emits:C2", "set": {"why": "first"}},
                                     {"edge": "C1:emits:C2", "set": {"why": "second"}}])
        assert fix.main(["rows", "--fragments", str(d), "--edits", str(edits)]) == 2
        assert "same row as" in capsys.readouterr().err


def test_the_batch_keeps_every_guard_row_has(capsys) -> None:
    """`row` grew four guards over four builds. A second batch path starting fresh would have none."""
    with tempfile.TemporaryDirectory() as td:
        d = make_edge_dir(td)
        edits = make_edits_file(td, [{"edge": "C1:emits:C2", "set": {"where": "b.py:9"}}])
        assert fix.main(["rows", "--fragments", str(d), "--edits", str(edits)]) == 2
        assert "not writable here" in capsys.readouterr().err


def test_a_batch_whose_edits_are_all_no_ops_writes_nothing(capsys) -> None:
    with tempfile.TemporaryDirectory() as td:
        d = make_edge_dir(td)
        stamp = (d / "e1.json").stat().st_mtime_ns
        edits = make_edits_file(td, [{"edge": "C1:emits:C2", "set": {"why": "w"}}])
        assert fix.main(["rows", "--fragments", str(d), "--edits", str(edits)]) == 0
        assert "already says that" in capsys.readouterr().out
        assert (d / "e1.json").stat().st_mtime_ns == stamp


def test_edits_may_come_from_stdin(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        d = make_edge_dir(td)
        monkeypatch.setattr(
            "sys.stdin", io.StringIO(json.dumps([{"edge": "C1:emits:C2",
                                                  "set": {"verb": "queues"}}])))
        assert fix.main(["rows", "--fragments", str(d), "--edits", "-"]) == 0
        assert ("C1", "queues", "C2") in read_edges(d)


def test_an_edits_list_that_is_not_a_list_is_refused(capsys) -> None:
    with tempfile.TemporaryDirectory() as td:
        d = make_edge_dir(td)
        edits = make_edits_file(td, {"edge": "C1:emits:C2"})       # type: ignore[arg-type]
        assert fix.main(["rows", "--fragments", str(d), "--edits", str(edits)]) == 2
        assert "non-empty JSON LIST" in capsys.readouterr().err


def test_an_unknown_key_in_an_edit_is_refused_with_the_real_keys(capsys) -> None:
    with tempfile.TemporaryDirectory() as td:
        d = make_edge_dir(td)
        edits = make_edits_file(td, [{"edge": "C1:emits:C2", "sets": {"why": "x"}}])
        assert fix.main(["rows", "--fragments", str(d), "--edits", str(edits)]) == 2
        assert "unknown key(s) sets" in capsys.readouterr().err


def test_a_structured_value_in_set_is_sent_to_set_json(capsys) -> None:
    with tempfile.TemporaryDirectory() as td:
        d = make_edge_dir(td)
        edits = make_edits_file(td, [{"id": "C1", "set": {"purpose": ["a", "b"]}}])
        assert fix.main(["rows", "--fragments", str(d), "--edits", str(edits)]) == 2
        assert "goes in 'set_json'" in capsys.readouterr().err


def test_row_and_rows_reach_the_same_writer() -> None:
    """`row` is the one-element case, so a guard added for either is a guard for both."""
    with tempfile.TemporaryDirectory() as td:
        one = make_edge_dir(td)
        assert fix.main(["row", "--fragments", str(one), "--edge", "C1:emits:C2",
                         "--set-verb", "queues"]) == 0
        assert ("C1", "queues", "C2") in read_edges(one)
    with tempfile.TemporaryDirectory() as td:
        many = make_edge_dir(td)
        edits = make_edits_file(td, [{"edge": "C1:emits:C2", "set": {"verb": "queues"}}])
        assert fix.main(["rows", "--fragments", str(many), "--edits", str(edits)]) == 0
        assert ("C1", "queues", "C2") in read_edges(many)


# --- a field a GATE asked the build to add ----------------------------------------------------
# `audit` ends a finding with "state its prerequisite" and `validate` with "give it a `why`" —
# asking for a field the row does not have — and the verb that exists to apply a finding refused it:
# `HP22: has no field(s) why — a new key here is a schema change, not a correction`. On the
# 2026-08-29 mcpolis build that sent eleven Happy-Path `why` lines through a python heredoc.

def _rows_edit(d, edits: list[dict]) -> int:
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = fix.main(["rows", "--fragments", str(d), "--edits", "-"])
    return rc


def test_a_gate_requested_field_may_be_added(monkeypatch, capsys):
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, hp={"happy_path": [{"id": "HP1", "uc": "UC1"}]})
        monkeypatch.setattr("sys.stdin", io.StringIO(
            json.dumps([{"id": "HP1", "set": {"why": "the caller has no session yet"}}])))
        rc = fix.main(["rows", "--fragments", str(d), "--edits", "-"])
        body = json.loads((d / "hp.json").read_text(encoding="utf-8"))
    assert rc == 0, capsys.readouterr()
    assert body["happy_path"][0]["why"] == "the caller has no session yet", body


def test_a_field_nobody_asked_for_is_still_refused(monkeypatch, capsys):
    """The general rule is unchanged: a key that is not on a row is usually a typo."""
    with tempfile.TemporaryDirectory() as td:
        d = make_frag_dir(td, hp={"happy_path": [{"id": "HP1", "uc": "UC1"}]})
        monkeypatch.setattr("sys.stdin", io.StringIO(
            json.dumps([{"id": "HP1", "set": {"porpoise": "x"}}])))
        rc = fix.main(["rows", "--fragments", str(d), "--edits", "-"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "has no field(s) porpoise" in err, err
    assert "may be ADDED" in err, "the refusal should name the fields that CAN be added"


def test_apply_drift_refuses_a_correction_into_a_file_neither_end_of_the_edge_lists(capsys):
    """One live build rewrote 22 anchors with no file opened, and one landed `C99 tests C41` in a
    file a third component lists. A corrected file that neither end of the edge lists in `files`
    is refused before either write path; a file the far end lists is a legitimate cross-file move."""
    m = make_map([{"src": "C1", "verb": "reads", "dst": "C2", "where": "a.py:10"}])
    m["components"] = [{"id": "C1", "name": "A", "source": "a.py:1", "files": ["a.py"]},
                       {"id": "C2", "name": "B", "source": "b.py:1", "files": ["b.py"]}]
    stray = {"grounding": [make_vote("C1 reads C2", True, "z.py:3"),
                           make_vote("C1 reads C2", True, "z.py:3")]}
    with tempfile.TemporaryDirectory() as td:
        mp, vp = write(td, m, stray)
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0"]) == 0
        assert load_model_path(mp).edges[0].where == "a.py:10", "a stray file must not be written"
        err = capsys.readouterr().err
        assert "REFUSED" in err and "z.py:3" in err and "C1, C2" in err, err
        rec = Path(td) / "reconcile.json"
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0",
                         "--to-reconcile", str(rec)]) == 0
        assert not (rec.exists() and "z.py" in rec.read_text()), "nor recorded for assemble to replay"
    far_end = {"grounding": [make_vote("C1 reads C2", True, "b.py:3"),
                             make_vote("C1 reads C2", True, "b.py:3")]}
    with tempfile.TemporaryDirectory() as td:
        mp, vp = write(td, m, far_end)
        assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0"]) == 0
        assert load_model_path(mp).edges[0].where == "b.py:3"


def test_both_write_paths_count_a_cross_file_refusal_on_their_last_line(capsys):
    """The two write paths keep drifting apart on what their final line says. The cross-file clause
    was appended by the IN-PLACE path only, so `--to-reconcile` — the path `ship` step 3 actually
    runs — ended without it, and a reader on `| tail` saw a refusal that was never counted."""
    m = make_map([{"src": "C1", "verb": "reads", "dst": "C2", "where": "a.py:10"}])
    m["components"] = [{"id": "C1", "name": "A", "source": "a.py:1", "files": ["a.py"]},
                       {"id": "C2", "name": "B", "source": "b.py:1", "files": ["b.py"]}]
    stray = {"grounding": [make_vote("C1 reads C2", True, "z.py:3"),
                           make_vote("C1 reads C2", True, "z.py:3")]}
    for extra in ([], ["--to-reconcile", "REC"]):
        with tempfile.TemporaryDirectory() as td:
            mp, vp = write(td, m, stray)
            argv = [a.replace("REC", str(Path(td) / "reconcile.json")) for a in extra]
            assert fix.main(["apply-drift", "--map", mp, "--verdicts", vp, "--tolerance", "0",
                             *argv]) == 0
            last = capsys.readouterr().out.splitlines()[-1]
        assert "1 cross-file correction(s) REFUSED" in last, f"{extra or 'in place'}: {last}"
