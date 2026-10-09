#!/usr/bin/env python3
"""`coyomap changes relink` — an update keeps the more precise line its skeptics read: the link moves
inside the row the log adds, or as a `relinked` row, the wave's verdicts follow the statement's new
text, and `ground` finds every vote. Real temp git repos (the update of tests/test_challenge.py),
explicit make_* builders, no fixtures/classes."""
from __future__ import annotations

import json
import tempfile
from typing import Any

from coyomap import challenge as ch
from coyomap import relink
from coyomap import changelog
from coyomap.changelog import Entry, FieldEdit, Relink, apply, lint

from test_challenge import make_update, make_verdict, rule_claim

#: The statements the wave confirms, and the line each skeptic read when it is not the map's.
BETTER = {"C2 calls C3": "svc/b.py:7",
          rule_claim("svc/b.py:4", "The beta list holds at most ten items.", "refuses the eleventh"): "svc/b.py:8"}


def make_better_wave(inputs: ch.Inputs) -> None:
    """Every batch answered and confirmed; the two statements of BETTER cited at another line."""
    for claims_file in sorted(inputs.verify.glob(f"claims-{inputs.log.from_commit}-*.json")):
        batch = claims_file.stem[len("claims-"):]
        claims: list[dict[str, Any]] = json.loads(claims_file.read_text(encoding="utf-8"))["claims"]
        rows = [make_verdict(c["claim"], BETTER.get(c["claim"]) or c.get("anchor") or "svc/b.py:1", skeptic=batch)
                for c in claims]
        (inputs.verify / f"verdicts-{batch}.json").write_text(json.dumps({"grounding": rows}), encoding="utf-8")


def test_a_better_line_moves_the_link_where_its_value_comes_from_and_ground_finds_every_vote():
    """mcpolis 2026-10-09: 12 confirmed verdicts cited a more precise line, and all 12 were dropped."""
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        ch.run_challenge(inputs, cap=40, floor=0)
        make_better_wave(inputs)
        r = relink.relink(inputs.log, inputs.map_doc, inputs.verify, None)
        assert len(r.moved) == 2 and r.skipped == [], (r.moved, r.skipped)
        added = r.log.entries[1].added[0].row
        assert added["sites"][0]["where"] == "svc/b.py:8", "the new rule's site, inside the row the log adds"
        assert [(x.id, x.key, x.was, x.now) for x in r.log.relinked] == [
            ("edge:C2>calls>C3", "where", "svc/b.py:3", "svc/b.py:7")], "an arrow the log does not touch"
        assert inputs.log.relinked == [], "the caller's log is not touched"
        assert lint(r.log, inputs.map_doc).ok, lint(r.log, inputs.map_doc).errors
        new_claim = rule_claim("svc/b.py:8", "The beta list holds at most ten items.", "refuses the eleventh")
        assert r.renames == {rule_claim("svc/b.py:4", "The beta list holds at most ten items.",
                                        "refuses the eleventh"): new_claim}
        assert relink.rekey_wave(inputs.verify, inputs.log, r.renames) == 1
        inputs.log = r.log
        applied, _ = apply(r.log, inputs.map_doc, "2026-09-19")
        assert applied["edges"][1]["where"] == "svc/b.py:7"
        inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
        inputs.map_doc = applied
        fold = ch.run_ground(inputs, "one wave", dry_run=True)
        assert not fold.errors, fold.errors
        voted = {str(x.get("claim")) for x in fold.wave_rows}
        assert new_claim in voted


def test_nothing_moves_when_the_skeptics_read_the_maps_own_line():
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        ch.run_challenge(inputs, cap=40, floor=0)
        for claims_file in sorted(inputs.verify.glob(f"claims-{inputs.log.from_commit}-*.json")):
            batch = claims_file.stem[len("claims-"):]
            claims = json.loads(claims_file.read_text(encoding="utf-8"))["claims"]
            rows = [make_verdict(c["claim"], c.get("anchor") or "svc/b.py:1", skeptic=batch) for c in claims]
            (inputs.verify / f"verdicts-{batch}.json").write_text(json.dumps({"grounding": rows}), encoding="utf-8")
        r = relink.relink(inputs.log, inputs.map_doc, inputs.verify, None)
        assert r.moved == [] and r.log.relinked == [] and r.renames == {}


def test_the_command_prints_without_write_and_writes_the_log_and_the_wave_with_it(capsys):
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        ch.run_challenge(inputs, cap=40, floor=0)
        make_better_wave(inputs)
        before = inputs.log_path.read_text(encoding="utf-8")
        assert changelog.main(["relink", str(inputs.log_path), "--map", str(inputs.map_path)]) == 0
        assert "2 link(s) moved" in capsys.readouterr().out and inputs.log_path.read_text(encoding="utf-8") == before
        assert changelog.main(["relink", str(inputs.log_path), "--map", str(inputs.map_path), "--write"]) == 0
        assert "1 verdict row(s) re-keyed" in capsys.readouterr().out
        written = json.loads(inputs.log_path.read_text(encoding="utf-8"))
        assert written["relinked"][0]["id"] == "edge:C2>calls>C3"
        assert changelog.main(["relink", str(inputs.log_path), "--map", str(inputs.map_path)]) == 0
        assert "0 link(s) moved" in capsys.readouterr().out, "a second run finds nothing left to move"


def make_rule_doc(inputs: ch.Inputs, sites: list[dict[str, str]]) -> None:
    """BR4, a rule of the map the log is written against, with these sites."""
    inputs.map_doc["rules"].append({"id": "BR4", "name": "A fourth guard", "statement": "A fourth guard holds.",
                                    "block": "BLK1", "sites": sites})


def test_a_site_list_an_entry_edits_item_by_item_is_left_for_the_lead_and_the_rest_still_moves():
    """Review finding: an entry removing an earlier site renumbered the list, so relink moved the
    wrong site and re-keyed the wrong statement's vote, silently."""
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        make_rule_doc(inputs, [{"where": "svc/b.py:2", "why": "zero"}, {"where": "svc/b.py:4", "why": "one"},
                               {"where": "svc/b.py:5", "why": "two"}])
        inputs.log.entries.append(Entry("e3", "A guard loses a check", "One check is gone.", ["BR4"],
                                        [FieldEdit("BR4", "sites[0]", {"where": "svc/b.py:2", "why": "zero"}, None)]))
        two = rule_claim("svc/b.py:5", "A fourth guard holds.", "two")
        BETTER[two] = "svc/b.py:9"
        try:
            ch.run_challenge(inputs, cap=40, floor=0)
            make_better_wave(inputs)
            r = relink.relink(inputs.log, inputs.map_doc, inputs.verify, None)
        finally:
            del BETTER[two]
        assert any("BR4" in line and "by hand" in line for line in r.skipped), r.skipped
        assert not any(x.id == "BR4" for x in r.log.relinked)
        assert any(line.startswith("edge:C2>calls>C3") for line in r.moved), "the other corrections still go"


def test_a_move_onto_a_line_another_site_holds_is_left_for_the_lead():
    """Review finding: two sites with one reason on one line become one statement, and a vote lost."""
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        make_rule_doc(inputs, [{"where": "svc/b.py:4", "why": "w"}, {"where": "svc/b.py:9", "why": "w"}])
        first = rule_claim("svc/b.py:4", "A fourth guard holds.", "w")
        inputs.log.entries.append(Entry("e3", "A guard is named", "It reads plainly.", ["BR4"],
                                        [FieldEdit("BR4", "name", "A fourth guard", "The fourth guard")]))
        BETTER[first] = "svc/b.py:9"
        try:
            ch.run_challenge(inputs, cap=40, floor=0)
            make_better_wave(inputs)
            r = relink.relink(inputs.log, inputs.map_doc, inputs.verify, None)
        finally:
            del BETTER[first]
        assert any("already says this line" in line for line in r.skipped), r.skipped


def test_a_hand_written_relinked_row_puts_its_statement_in_scope_and_stays_in_its_file():
    """Review finding: a relinked row moved an arrow's link with no entry, and its statement was
    carried on a verdict cast at the old line."""
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        log = inputs.log
        log.relinked = [Relink("edge:C3>uses>D1", "where", "svc/b.py:6", "svc/b.py:2")]
        applied, _ = apply(log, inputs.map_doc)
        scope = ch.scope_update(log, inputs.before_text, applied, inputs.impact, inputs.verify, inputs.repo)
        assert "C3 uses D1" in {s.item.claim for s in scope.in_scope}
        log.relinked = [Relink("edge:C3>uses>D1", "where", "svc/b.py:6", "svc/a.py:1")]
        assert any("a relink stays in its file" in e for e in lint(log, inputs.map_doc).errors)
