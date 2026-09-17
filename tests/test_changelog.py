#!/usr/bin/env python3
"""`coyomap changes` — the change log of one map update, and its four readers.

lint: the log fits the map it was written against. apply: the entries land in the map, the pin
moves. check: the two-way rule between the log and the map's own diff. render: the log for people,
by name, under Product and Under the hood. Explicit make_* builders, no fixtures/classes.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from coyomap import changelog
from coyomap.changelog import (
    Addition, ChangeLog, Entry, FieldEdit, Waiver, apply, check, dump_log, get_field, lint, load_log,
    render, set_field, touched_ids,
)
from coyomap.model import load_model

from test_mapdiff import make_map, make_rule, make_steps


def make_entry(eid: str = "e1", elements: list[str] | None = None, **kw: Any) -> Entry:
    return Entry(eid, kw.pop("headline", "The reader sees a plainer rule"),
                 kw.pop("sentence", "A rule's statement now says its condition in one sentence."),
                 elements if elements is not None else ["BR1"], **kw)


def make_log(*entries: Entry, **kw: Any) -> ChangeLog:
    return ChangeLog(kw.pop("from_commit", "aaaaaaa"), kw.pop("to_commit", "bbbbbbb"),
                     kw.pop("date", "2026-09-17"), list(entries), **kw)


def make_doc(**overrides: Any) -> dict[str, Any]:
    return make_map(rules=[make_rule("BR1", "A token is checked", risk="a team is left open")], **overrides)


def copy(doc: Any) -> Any:
    return json.loads(json.dumps(doc))


# --- the file ---------------------------------------------------------------------------

def test_the_log_round_trips_through_its_file():
    log = make_log(make_entry(edits=[FieldEdit("BR1", "risk", "a team is left open", "a team is locked")],
                              evidence=["a.py"]), waived=[Waiver("C1", "a rename, no meaning moved")], notes="n")
    again = load_log(dump_log(log))
    assert again == log
    assert json.loads(dump_log(log))["format"] == "coyomap-changes"


def test_a_malformed_log_names_its_missing_field():
    with pytest.raises(ValueError, match="format"):
        load_log('{"format": "nope", "version": 1}')
    with pytest.raises(ValueError, match="version"):
        load_log('{"format": "coyomap-changes", "version": 2}')
    with pytest.raises(ValueError, match="missing field: entries"):
        load_log('{"format": "coyomap-changes", "version": 1, "from_commit": "a", "to_commit": "b", "date": "d"}')
    with pytest.raises(ValueError, match=r"entries\[0\] is missing headline"):
        load_log(json.dumps({"format": "coyomap-changes", "version": 1, "from_commit": "a", "to_commit": "b",
                             "date": "d", "entries": [{"id": "e1", "sentence": "s", "elements": []}]}))


# --- addressing --------------------------------------------------------------------------

def test_a_field_is_addressed_by_a_path_inside_its_row():
    row = {"risk": "r", "sites": [{"where": "a.py:1", "why": "w"}],
           "fields": [{"name": "id", "type": "str"}, {"name": "size", "type": "int"}],
           "steps": [{"n": 1, "phrase": "one"}, {"n": 2, "phrase": "two"}]}
    assert get_field(row, "risk") == "r"
    assert get_field(row, "sites[0].where") == "a.py:1"
    assert get_field(row, "fields[name=size].type") == "int"
    assert get_field(row, "steps[n=2].phrase") == "two"
    assert get_field(row, "steps[n=9].phrase") is None and get_field(row, "nothing") is None
    set_field(row, "steps[n=2].phrase", "deux")
    set_field(row, "fields[name=id]", None)
    set_field(row, "risk", None)
    assert row["steps"][1]["phrase"] == "deux" and row["fields"] == [{"name": "size", "type": "int"}] and "risk" not in row
    with pytest.raises(ValueError, match="bad key path"):
        get_field(row, "sites[")


# --- lint ------------------------------------------------------------------------------------

def test_a_clean_log_lints_clean():
    doc = make_doc()
    log = make_log(make_entry(edits=[FieldEdit("BR1", "risk", "a team is left open", "a team is locked")]))
    p = lint(log, doc)
    assert p.ok and p.warnings == []


def test_lint_names_every_way_a_log_can_be_wrong():
    doc = make_doc()
    long = " ".join(["word"] * 24) + "."
    log = make_log(
        make_entry("e1", elements=[]),
        make_entry("e1", elements=["BR9"]),
        make_entry("e3", elements=["BR1"], edits=[FieldEdit("C1", "purpose", "serves the map", "x")]),
        make_entry("e4", elements=["BR1"], edits=[FieldEdit("BR1", "risk", "stale", "new")]),
        make_entry("e5", elements=["BR1"], edits=[FieldEdit("BR1", "risk", "a team is left open", "a team is left open")]),
        make_entry("e6", elements=["BR1"], confidence="sure"),
        make_entry("e7", elements=["BR1"], headline=" ".join(["w"] * 15), sentence=long),
        make_entry("e8", elements=["BR1"], added=[Addition("entities", {"id": "E1"}), Addition("nope", {"id": "X1"})]),
        make_entry("e9", elements=["BR1"], removed=["E9"]),
        waived=[Waiver("Z9", "")])
    p = lint(log, doc)
    errs = "\n".join(p.errors)
    assert "entry e1: names no box" in errs
    assert "id used twice" in errs
    assert "names BR9, which is not in the map" in errs
    assert "entry e3: edits C1 without naming it" in errs
    assert "the map holds \"a team is left open\", the log says was \"stale\"" in errs
    assert "was and now are the same" in errs
    assert "confidence 'sure' is not one of verified, likely, inferred" in errs
    assert "adds E1, which the map already has" in errs and "adds a row to 'nope'" in errs
    assert "removes E9, which is not in the map" in errs
    assert "waived Z9: says no why" in errs
    warns = "\n".join(p.warnings)
    assert "headline is 15 words" in warns and "waived Z9 is not in the map" in warns
    assert "entry e7 sentence" in warns, "a 24-word sentence gets the readability warning"


def test_an_entry_may_name_a_box_another_entry_adds():
    doc = make_doc()
    log = make_log(make_entry("e1", elements=["BR2"], added=[Addition("rules", make_rule("BR2", "new rule"))]),
                   make_entry("e2", elements=["BR2", "BR1"]))
    assert lint(log, doc).ok


# --- apply -----------------------------------------------------------------------------------

def make_entity(eid: str, name: str) -> dict[str, Any]:
    return {"id": eid, "name": name, "meaning": f"one {name.lower()}", "source": "m.py:3",
            "fields": [{"name": "id", "type": "str"}]}


def test_apply_edits_adds_removes_and_moves_the_pin_without_touching_the_input():
    doc = make_doc(entities=[make_entity("E1", "Thing"), make_entity("E2", "Gone")])
    before = copy(doc)
    log = make_log(
        make_entry("e1", elements=["BR1", "UC1"],       # an edit on the flow is an edit on the use case
                   edits=[FieldEdit("BR1", "risk", "a team is left open", "a team is locked"),
                          FieldEdit("flow:UC1", "steps[n=2].phrase", "does thing 2", "does the second thing")]),
        make_entry("e2", elements=["BR2", "E2"], added=[Addition("rules", make_rule("BR2", "new rule"))],
                   removed=["E2"]))
    new, done = apply(log, doc, "2026-09-17")
    assert doc == before, "apply works on a copy"
    assert (done.edits, done.added, done.removed) == (2, 1, 1)
    assert new["rules"][0]["risk"] == "a team is locked" and new["rules"][1]["id"] == "BR2"
    assert new["flows"][0]["steps"][1]["phrase"] == "does the second thing"
    assert [e["id"] for e in new["entities"]] == ["E1"]
    assert new["commit"] == "bbbbbbb" and new["committed"] == "2026-09-17"


def test_a_row_the_map_cannot_load_is_caught_by_lint_with_its_field_named():
    """The real mcpolis report added a way in with four fields of an older shape; every check before
    this one passed it, and the written map did not load."""
    doc = make_doc()
    log = make_log(make_entry("e1", elements=["EP9"], added=[Addition("entry_points", {
        "id": "EP9", "kind": "cli", "trigger": "run it", "component": "C1", "source": "a.py:1", "address": None})]))
    p = lint(log, doc)
    assert len(p.errors) == 1 and "would not load after apply" in p.errors[0] and "address" in p.errors[0]
    with pytest.raises(ValueError, match="would not load"):
        apply(log, doc)


def test_apply_refuses_a_log_that_does_not_fit_the_map():
    doc = make_doc()
    log = make_log(make_entry(edits=[FieldEdit("BR1", "risk", "stale", "new")]))
    with pytest.raises(ValueError, match="does not fit this map"):
        apply(log, doc)


# --- check: the completeness gate ---------------------------------------------------------------

def test_a_changed_box_no_entry_names_is_a_gap_and_a_waiver_covers_it():
    old = make_doc()
    new = copy(old)
    new["rules"][0]["risk"] = "a team is locked"
    new["components"][0]["purpose"] = "serves the map faster"
    log = make_log(make_entry(elements=["BR1"]))
    p = check(log, old, new)
    assert p.errors == ["C1 modified in the map, and no entry names it"]
    assert check(make_log(make_entry(elements=["BR1"]), waived=[Waiver("C1", "wording only")]), old, new).ok


def test_a_code_link_move_needs_no_entry():
    old = make_doc()
    new = copy(old)
    new["components"][0]["source"] = "srv.py:99"
    assert check(make_log(), old, new).ok


def test_an_entry_naming_a_box_the_new_map_lacks_is_a_gap_unless_the_entry_removed_it():
    old = make_doc(entities=[make_entity("E1", "Thing"), make_entity("E2", "Gone")])
    new = copy(old)
    new["entities"] = new["entities"][:1]
    p = check(make_log(make_entry(elements=["E2", "E9"])), old, new)
    assert "E9, which the new map does not hold" in "\n".join(p.errors)
    assert check(make_log(make_entry(elements=["E2"], removed=["E2"])), old, new).ok


def test_an_arrow_that_came_or_went_is_explained_by_naming_its_source():
    old = make_doc()
    new = copy(old)
    new["edges"] = [{"src": "C1", "verb": "reads", "dst": "E1", "where": "srv.py:12"}]
    assert check(make_log(make_entry(elements=["BR1"])), old, new).errors == ["C1 an arrow added in the map, and no entry names it"]
    assert check(make_log(make_entry(elements=["C1"])), old, new).ok


def test_the_code_s_touch_is_a_warning_when_nobody_names_or_waives_the_box():
    old = make_doc()
    new = copy(old)
    impact = {"impacts": {
        "C1": {"cause": "direct", "change": "modified", "resolution": "line"},
        "step:UC1:2": {"cause": "direct", "change": "modified", "resolution": "symbol"},
        "rule:BR1:0": {"cause": "direct", "change": "modified", "resolution": "line"},
        "edge:C1>reads>E1": {"cause": "direct", "change": "modified", "resolution": "line"},
        "E1": {"cause": "direct", "change": "drifted", "resolution": "symbol"},
        "D1": {"cause": "direct", "change": "modified", "resolution": "file"},
        "R1": {"cause": "ripple", "change": "affected", "resolution": None},
        "ep:a.py:1": {"cause": "direct", "change": "modified", "resolution": "line"},
    }}
    assert touched_ids(impact) == {"C1", "UC1", "BR1"}
    p = check(make_log(make_entry(elements=["BR1"]), waived=[Waiver("UC1", "a rename")]), old, new, impact)
    assert p.ok and p.warnings == ["the code touched C1 and no entry names or waives it"]


# --- render ---------------------------------------------------------------------------------

def test_a_list_edit_renders_as_what_came_and_went_by_name():
    doc = make_doc(roles=[{"id": "R1", "name": "Reader"}, {"id": "R2", "name": "Admin"}])
    log = make_log(make_entry(elements=["UC1"], edits=[FieldEdit("UC1", "actors", ["R1"], ["R1", "R2"]),
                                                       FieldEdit("flow:UC1", "steps[n=2].where", "srv.py:21", "srv.py:40")]))
    md = render(log, doc)
    assert "- Open the map · Actors: + Admin" in md and "R2" not in md
    assert "- Open the map · step 2 · Code link: srv.py:21 → srv.py:40" in md


def test_the_rendering_names_boxes_and_puts_each_entry_under_its_group():
    doc = make_doc()
    log = make_log(
        make_entry("e1", elements=["BR1"], edits=[FieldEdit("BR1", "risk", "a team is left open", "a team is locked")],
                   evidence=["a.py"]),
        make_entry("e2", elements=["UC1", "C1"], headline="Opening the map is faster", sentence="The server answers at once.",
                   confidence="likely"),
        waived=[Waiver("E1", "a rename, no meaning moved")], notes="Nothing was run.")
    md = render(log, doc)
    assert md.startswith("# What changed: aaaaaaa → bbbbbbb (2026-09-17)")
    assert "2 entries · 0 boxes added · 0 removed · 1 field edited · 1 touched without a change of meaning" in md
    assert md.index("## Product") < md.index("### The reader sees a plainer rule") < md.index("## Under the hood")
    assert md.count("### Opening the map is faster") == 2, "an entry spanning both groups appears under both"
    assert "Also here: Server" in md, "…told in full once, and by its boxes of that group the second time"
    assert "Boxes: A token is checked" in md and "BR1" not in md.split("Boxes:", 1)[1].split("\n")[0]
    assert "- A token is checked · Risk: a team is left open → a team is locked" in md
    assert "- Evidence: `a.py`" in md and "- Confidence: likely" in md
    assert "## Touched by the code, no change of meaning" in md and "- Thing: a rename, no meaning moved" in md
    assert md.rstrip().endswith("## Notes\n\nNothing was run.")


# --- the command ------------------------------------------------------------------------------

def write(td: str, name: str, text: str) -> str:
    p = Path(td) / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_the_verbs_answer_with_exit_codes_and_check_json_is_json_only(capsys):
    with tempfile.TemporaryDirectory() as td:
        doc = make_doc()
        old = write(td, "old.json", json.dumps(doc))
        good = write(td, "good.json", dump_log(make_log(make_entry(
            edits=[FieldEdit("BR1", "risk", "a team is left open", "a team is locked")]))))
        bad = write(td, "bad.json", dump_log(make_log(make_entry(elements=[]))))
        out = str(Path(td) / "new.json")
        assert changelog.main(["lint", good, "--map", old]) == 0
        assert changelog.main(["lint", bad, "--map", old]) == 1
        assert "names no box" in capsys.readouterr().out
        assert changelog.main(["apply", good, "--map", old, "--out", out, "--date", "2026-09-17"]) == 0
        assert json.loads(Path(old).read_text()) == doc, "apply with --out leaves the input alone"
        assert json.loads(Path(out).read_text())["commit"] == "bbbbbbb"
        capsys.readouterr()
        assert changelog.main(["check", good, "--old", old, "--new", out, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == {"kind": "coyomap-changes-check", "ok": True, "errors": [], "warnings": []}
        assert changelog.main(["render", good, "--map", old]) == 0
        assert "### The reader sees a plainer rule" in capsys.readouterr().out


def test_the_command_refuses_a_bad_verb_a_bad_option_and_a_missing_map(capsys):
    assert changelog.main(["nope"]) == 2 and "unknown verb" in capsys.readouterr().err
    with tempfile.TemporaryDirectory() as td:
        good = write(td, "g.json", dump_log(make_log(make_entry())))
        assert changelog.main(["lint", good, "--bogus"]) == 2 and "unknown option" in capsys.readouterr().err
        assert changelog.main(["lint", good]) == 2 and "needs --map" in capsys.readouterr().err
        assert changelog.main(["check", good, "--old", good]) == 2
    assert changelog.main(["--help"]) == 0 and "usage: coyomap changes" in capsys.readouterr().out
    assert changelog.main([]) == 2


# --- the review's findings, each pinned ------------------------------------------------------

def test_lint_runs_the_validator_s_blocking_checks_on_the_applied_map():
    """F1: a site that says `no_call_site` and carries a `where` loads but does not validate; the
    real mcpolis log shipped two of them, and only the close step would have said so."""
    doc = make_doc()
    row = make_rule("BR2", "A guard holds")
    row["sites"] = [{"where": "srv.py:3", "why": "guards", "no_call_site": True}]
    log = make_log(make_entry("e1", elements=["BR2"], added=[Addition("rules", row)]))
    p = lint(log, doc)
    assert len(p.errors) == 1 and "would not validate after apply" in p.errors[0] and "no_call_site" in p.errors[0]


def test_a_keyed_row_and_the_map_s_header_are_boxes_the_gate_sees():
    """F2: a glossary term, a run command and the map's goal changed with no entry are gaps; naming
    them by their synthetic id, or `map`, covers them; an entry can edit them the same way."""
    old = make_doc(glossary=[{"term": "guild", "meaning": "a team", "source": "m.py:1"}],
                   run_commands=[{"action": "serve", "command": "make serve", "source": "Makefile:3"}])
    new = copy(old)
    new["glossary"][0]["meaning"] = "a team of readers"
    new["run_commands"][0]["command"] = "make start"
    new["goal"] = "a plainer goal"
    p = check(make_log(), old, new)
    assert p.errors == ["glossary:guild modified in the map, and no entry names it",
                        "map modified (goal) in the map, and no entry names it",
                        "run:serve modified in the map, and no entry names it"]
    named = make_log(make_entry(elements=["glossary:guild", "map", "run:serve"]))
    assert check(named, old, new).ok, check(named, old, new).errors
    edit = make_log(make_entry(elements=["map", "glossary:guild"],
                               edits=[FieldEdit("map", "goal", "g", "a plainer goal"),
                                      FieldEdit("glossary:guild", "meaning", "a team", "a team of readers")]))
    assert lint(edit, old).ok
    applied, _ = apply(edit, old)
    assert applied["goal"] == "a plainer goal" and applied["glossary"][0]["meaning"] == "a team of readers"
    bad = make_log(make_entry(elements=["map"], edits=[FieldEdit("map", "rules[0].risk", "x", "y")]))
    assert any("`map` edits take one header field" in e for e in lint(bad, old).errors)


def test_a_new_use_case_brings_its_flow():
    """F4: the most common product change, a new story, is expressible: the use case row and its
    flow row are both additions of one entry."""
    doc = make_doc()
    uc = {"id": "UC2", "name": "Close the map", "actors": ["R1"], "trigger_outcome": "The reader closes the map."}
    flow = {"uc": "UC2", "title": "Close the map", "steps": [{"n": 1, "src": "R1", "dst": "C1", "phrase": "closes it", "where": "srv.py:30"}]}
    log = make_log(make_entry("e1", elements=["UC2"], added=[Addition("use_cases", uc), Addition("flows", flow)]))
    p = lint(log, doc)
    assert p.ok, p.errors
    new, done = apply(log, doc)
    assert done.added == 2 and [f["uc"] for f in new["flows"]] == ["UC1", "UC2"]
    assert check(log, doc, new).ok
    bad = make_log(make_entry("e1", elements=["UC2"], added=[Addition("use_cases", uc), Addition("flows", {"steps": []})]))
    assert any("adds a flow without its use case" in e for e in lint(bad, doc).errors)


def test_removing_a_list_item_never_shifts_another_edit_in_the_same_entry():
    """F5: sites [A, B, C]; remove sites[0] and reword sites[1] in one entry → B is reworded, C is
    untouched, whatever order the edits are written in."""
    doc = make_doc()
    doc["rules"][0]["sites"] = [{"where": "srv.py:1", "why": "A"}, {"where": "srv.py:2", "why": "B"}, {"where": "srv.py:3", "why": "C"}]
    log = make_log(make_entry(edits=[FieldEdit("BR1", "sites[0]", {"where": "srv.py:1", "why": "A"}, None),
                                     FieldEdit("BR1", "sites[1].why", "B", "B2")]))
    assert lint(log, doc).ok
    new, _ = apply(log, doc)
    assert [(x["where"], x["why"]) for x in new["rules"][0]["sites"]] == [("srv.py:2", "B2"), ("srv.py:3", "C")]


def test_a_deleted_file_s_anchors_are_touched_whatever_the_resolution():
    """F6: a deleted file is the strongest sign a box is gone; the file rung must not hide it."""
    impact = {"impacts": {"C1": {"cause": "direct", "change": "deleted", "resolution": "file"},
                          "C2": {"cause": "direct", "change": "added", "resolution": "file"}}}
    assert touched_ids(impact) == {"C1"}


def test_a_malformed_log_names_the_path_of_the_bad_field():
    """F7: five shapes that used to escape as a traceback."""
    base = {"format": "coyomap-changes", "version": 1, "from_commit": "a", "to_commit": "b", "date": "d"}
    cases = [
        ({**base, "entries": {}}, "entries is not a list"),
        ({**base, "entries": [{"id": "e1", "headline": "h", "sentence": "s", "elements": [], "edits": [{"id": "BR1"}]}]}, r"entries\[0\].edits\[0\] is missing key"),
        ({**base, "entries": [{"id": "e1", "headline": "h", "sentence": "s", "elements": [], "added": [{"kind": "rules"}]}]}, r"entries\[0\].added\[0\] is missing row"),
        ({**base, "entries": [{"id": "e1", "headline": "h", "sentence": "s", "elements": [], "edits": "no"}]}, r"entries\[0\].edits is not a list"),
        ({**base, "entries": [], "waived": ["C1"]}, r"waived\[0\] is not an object"),
    ]
    for doc, message in cases:
        with pytest.raises(ValueError, match=message):
            load_log(json.dumps(doc))


def test_the_log_s_commits_must_match_the_maps_pins():
    """F11: a log written for another pin is refused; a new map whose pin is not the log's end fails
    the gate."""
    doc = make_doc(commit="1234567")
    assert any("starts from aaaaaaa, the map is pinned to 1234567" in e for e in lint(make_log(make_entry()), doc).errors)
    assert lint(make_log(make_entry(), from_commit="1234567abc"), doc).ok, "a longer or shorter spelling of one commit is the same commit"
    new = copy(doc)
    new["commit"] = "bbbbbbb"
    assert check(make_log(make_entry(), from_commit="1234567"), doc, new).ok
    new["commit"] = "fffffff"
    assert any("ends at bbbbbbb, the new map is pinned to fffffff" in e for e in check(make_log(make_entry(), from_commit="1234567"), doc, new).errors)


def test_two_entries_may_not_edit_one_field():
    """F12: the last write would win and the first entry's claim would be false."""
    doc = make_doc()
    log = make_log(make_entry("e1", edits=[FieldEdit("BR1", "risk", "a team is left open", "B")]),
                   make_entry("e2", edits=[FieldEdit("BR1", "risk", "a team is left open", "C")]))
    assert any("BR1.risk is also edited by entry e1" in e for e in lint(log, doc).errors)


def test_an_added_way_in_renders_by_its_trigger():
    """F13: a way in has no name; its trigger is what the reader knows it by."""
    doc = make_doc()
    ep = {"id": "EP2", "kind": "cli", "trigger": "the reader asks for the bare address", "component": "C1",
          "source": "srv.py:12", "activation": "external", "runs_in": [], "cadence": "", "cadence_source": ""}
    log = make_log(make_entry(elements=["EP2", "UC1"], added=[Addition("entry_points", ep)],
                              edits=[FieldEdit("UC1", "entry_points", [], ["EP2"])]))
    md = render(log, doc)
    assert "the reader asks for the bare address (new)" in md and "Ways in: + the reader asks for the bare address" in md
    assert "EP2" not in md


def test_the_new_words_of_an_edit_face_the_readability_check():
    """F15: the reader meets the `now` text on the box's page, so a long one warns at lint."""
    doc = make_doc()
    long = " ".join(["word"] * 24) + "."
    log = make_log(make_entry(edits=[FieldEdit("BR1", "statement", "A token is checked", long)]))
    p = lint(log, doc)
    assert p.ok and any("BR1.statement" in w and "long sentence" in w for w in p.warnings)


def test_lint_refuses_a_path_that_is_not_there_and_edits_on_rows_that_come_or_go():
    """F17: a missing list position, an edit on a row another entry removes, an edit on a row this
    log adds — each a plain error, never a traceback or a silent write."""
    doc = make_doc(entities=[make_entity("E1", "Thing"), make_entity("E2", "Gone")])
    log = make_log(
        make_entry("e1", elements=["BR1"], edits=[FieldEdit("BR1", "sites[5].where", "x", "y")]),
        make_entry("e2", elements=["E2"], removed=["E2"]),
        make_entry("e3", elements=["E2"], edits=[FieldEdit("E2", "meaning", "one gone", "z")]),
        make_entry("e4", elements=["BR2"], added=[Addition("rules", make_rule("BR2", "new rule"))],
                   edits=[FieldEdit("BR2", "risk", "r", "s")]))
    errs = "\n".join(lint(log, doc).errors)
    assert "entry e1: BR1.sites[5].where — no such field or item in the map" in errs
    assert "entry e3: edits E2, which an entry removes" in errs
    assert "entry e4: edits BR2, which this log adds — put the value in the added row" in errs


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
