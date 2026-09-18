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
    Addition, ChangeLog, Entry, FieldEdit, Waiver, _prose_warnings, apply, check, check_before_write, dump_log,
    get_field, lint, load_log, render, set_field, touched_ids,
)
from coyomap.model import load_model

from test_mapdiff import make_edge, make_map, make_rule, make_steps


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


def test_the_viewer_s_form_names_every_box_with_its_kind_group_and_what_the_entry_did_to_it():
    """`to_view` is what the Changes tabs draw: a box by name, kind and group, with the entry's act on
    it; an edit by its field's label, its words, and the word spans the map's own diff uses. A removed
    box is named from the map as it was, and has no name without it."""
    doc = make_doc(components=[{"id": "C1", "name": "Server", "source": "srv.py:10", "purpose": "serves the map",
                                "files": ["srv.py"]}])
    old = copy(doc)
    old["components"].append({"id": "C2", "name": "Worker", "source": "w.py:1", "purpose": "runs the queue"})
    log = make_log(make_entry(elements=["BR1", "C1", "BR2", "C2", "UC1"],
                              edits=[FieldEdit("BR1", "risk", "a team is left open", "a team is locked out"),
                                     FieldEdit("BR1", "statement", "A token is checked", "A token is checked twice"),
                                     FieldEdit("flow:UC1", "steps[n=2].phrase", "does thing 2", "does the second thing"),
                                     FieldEdit("C1", "files", ["srv.py"], ["srv.py", "cli.py"])],
                              added=[Addition("rules", make_rule("BR2", "A token expires"))], removed=["C2"],
                              evidence=["srv.py"], confidence="likely"))
    view = changelog.to_view(log, doc, old)
    assert (view["from"], view["to"], view["date"]) == ("aaaaaaa", "bbbbbbb", "2026-09-17")
    (e,) = view["entries"]
    assert (e["headline"], e["confidence"], e["evidence"]) == ("The reader sees a plainer rule", "likely", ["srv.py"])
    assert [(b["name"], b["kind"], b["word"], b["group"], b["state"]) for b in e["boxes"]] == [
        ("A token is checked", "rules", "rule", "product", "modified"),
        ("Server", "components", "component", "hood", "modified"),
        ("A token expires", "rules", "rule", "product", "added"),
        ("Worker", "components", "component", "hood", "removed"),
        ("Open the map", "use_cases", "use case", "product", "modified"),
    ]
    risk, statement, step, files = e["edits"]
    assert (risk["box"], risk["name"], risk["label"], risk["cls"]) == ("BR1", "A token is checked", "Risk", "structure")
    assert (risk["old"], risk["new"], risk["spans"]) == ("a team is left open", "a team is locked out", [])
    assert statement["cls"] == "wording", "a sentence gets its changed words marked"
    assert "".join(sp["text"] for sp in statement["spans"] if sp["op"] != "ins") == "A token is checked"
    assert "".join(sp["text"] for sp in statement["spans"] if sp["op"] != "del") == "A token is checked twice"
    assert (step["box"], step["name"], step["label"]) == ("UC1", "Open the map", "step 2 · Phrase")
    assert (files["added"], files["removed"], files["cls"]) == (["cli.py"], [], "structure")
    # Without the map as it was, the removed box keeps its kind and group from nowhere: null name, no group known.
    bare = changelog.to_view(log, doc)
    worker = bare["entries"][0]["boxes"][3]
    assert worker["name"] is None and worker["state"] == "removed"


def test_a_list_whose_items_only_moved_in_the_code_is_a_link_move_and_a_step_reads_by_its_phrase():
    """The review's first finding: a site whose line moved read as "reordered", and an appended step
    as its file. The engine's own words apply: a code-link row with no words on either side, a step
    by its phrase, and "reordered" only for the same items in another order."""
    site = {"where": "a.py:1", "why": "guards"}
    moved = changelog.edit_view(FieldEdit("BR1", "sites", [site], [{"where": "a.py:9", "why": "guards"}]), {})
    assert (moved["cls"], moved["old"], moved["new"], moved["added"], moved["removed"]) == ("link", None, None, [], [])
    assert not moved.get("reordered")
    assert changelog._edit_text(FieldEdit("BR1", "sites", [site], [{"where": "a.py:9", "why": "guards"}]), {}) == "code links moved"
    one = FieldEdit("BR1", "sites[0]", site, {"where": "a.py:9", "why": "guards"})
    assert changelog.edit_view(one, {})["cls"] == "link" and changelog._edit_text(one, {}) == "code links moved"
    step = FieldEdit("flow:UC1", "steps[3]", None, {"n": 4, "src": "R1", "dst": "C1", "phrase": "confirms the email", "where": "srv.py:30"})
    assert changelog.edit_view(step, {})["added"] == ["confirms the email"]
    assert changelog._edit_text(step, {}) == "+ confirms the email"
    sub = FieldEdit("flow:UC1", "steps[3]", None, {"n": 4, "src": "R1", "dst": "C1", "phrase": None, "subflow": "SF1"})
    assert changelog.edit_view(sub, {"SF1": "Warn the person"})["added"] == ["runs Warn the person"]
    other = {"where": "b.py:2", "why": "checks"}
    swapped = FieldEdit("BR1", "sites", [site, other], [other, site])
    assert changelog.edit_view(swapped, {})["reordered"] is True and changelog._edit_text(swapped, {}) == "reordered"


def test_a_use_case_named_by_its_flow_keys_the_use_case_and_the_map_and_a_role_have_their_place():
    doc = make_doc()
    log = make_log(make_entry(elements=["flow:UC1", "map", "R1"],
                              edits=[FieldEdit("flow:UC1", "steps[n=2].phrase", "does thing 2", "does the second thing"),
                                     FieldEdit("map", "title", "t", "The map")]))
    (e,) = changelog.to_view(log, doc)["entries"]
    assert [(b["id"], b["name"], b["kind"], b["group"], b["state"]) for b in e["boxes"]] == [
        ("UC1", "Open the map", "use_cases", "product", "modified"),   # the flow IS the use case
        ("map", "the map", "map", "product", "modified"),             # its page is the Overview
        ("R1", "Reader", "roles", "product", "named"),
    ]
    assert e["boxes"][1]["word"] == "the map"


def test_a_removed_box_with_no_old_map_is_told_by_the_letters_of_its_id():
    log = make_log(make_entry(elements=["UC99"], removed=["UC99"]))
    (box,) = changelog.to_view(log, make_doc())["entries"][0]["boxes"]
    assert (box["name"], box["kind"], box["word"], box["group"], box["state"]) == (None, "use_cases", "use case", "product", "removed")
    assert changelog.array_of_id("BR209") == "rules" and changelog.array_of_id("glossary:term") is None


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
        assert changelog.main(["check", good, "--map", old, "--json"]) == 0, "the same gate before the write"
        assert json.loads(capsys.readouterr().out)["ok"] is True
        assert json.loads(Path(old).read_text()) == doc, "…and it writes nothing"
        assert changelog.main(["check", good, "--map", old, "--old", old, "--new", out]) == 2
        assert "not both" in capsys.readouterr().err
        assert changelog.main(["render", good, "--map", old]) == 0
        assert "### The reader sees a plainer rule" in capsys.readouterr().out


def test_the_command_refuses_a_bad_verb_a_bad_option_and_a_missing_map(capsys):
    assert changelog.main(["nope"]) == 2 and "unknown verb" in capsys.readouterr().err
    with tempfile.TemporaryDirectory() as td:
        good = write(td, "g.json", dump_log(make_log(make_entry())))
        assert changelog.main(["lint", good, "--bogus"]) == 2 and "unknown option" in capsys.readouterr().err
        assert changelog.main(["lint", good]) == 2 and "needs --map" in capsys.readouterr().err
        assert changelog.main(["check", good, "--old", good]) == 2 and "--map <map>" in capsys.readouterr().err
    assert changelog.main(["--help"]) == 0 and "usage: coyomap changes" in capsys.readouterr().out
    assert changelog.main([]) == 2


def test_each_verb_prints_its_own_help(capsys):
    """`changes lint --help` printed the generic usage; a reader wanting one verb read all four."""
    assert changelog.main(["check", "--help"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("  check <log> --map <map>") and "--old <map> --new <map>" in out
    assert "lint <log>" not in out and "render <log>" not in out
    assert changelog.main(["lint", "-h"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("  lint <log> --map <map>") and "check <log>" not in out


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


def test_the_new_words_of_an_edit_must_not_tell_the_map_s_history():
    """The map is a snapshot: "since the last-admin rule … no longer" in a rule's risk was the story
    of one update, written where a reader a year on meets it as the product. Lint warns on the new
    words — an edit's `now` and an added row alike — and never on words the map already held."""
    doc = make_doc()
    story = "Only the screens hold this back. Since the last-admin rule, such a call can no longer leave the team."
    log = make_log(make_entry(edits=[FieldEdit("BR1", "risk", "a team is left open", story)],
                              elements=["BR1", "BR2"],
                              added=[Addition("rules", make_rule("BR2", "A token expires", risk="a session now outlives its owner"))]))
    p = lint(log, doc)
    assert p.ok
    assert any(w.startswith("entry e1 BR1 risk: history word — says Since the, no longer") for w in p.warnings), p.warnings
    assert any(w.startswith("entry e1 BR2 risk: history word — says now") for w in p.warnings), p.warnings
    plain = make_log(make_entry(edits=[FieldEdit("BR1", "risk", "a team is left open",
                                                 "the store refuses the call that would leave the team without an admin")]))
    assert not any("history word" in w for w in lint(plain, doc).warnings)


def test_the_new_words_of_an_edit_face_the_readability_check():
    """F15: the reader meets the `now` text on the box's page, so a long one warns at lint — once,
    though two checks read it; and a rule's risk warns too, though the diff engine files `risk` as
    structure: the validator's own field walk is what decides what a reader meets."""
    doc = make_doc()
    long = " ".join(["word"] * 24) + "."
    risky = " ".join(["risk"] * 22) + "."
    log = make_log(make_entry(edits=[FieldEdit("BR1", "statement", "A token is checked", long),
                                     FieldEdit("BR1", "risk", "a team is left open", risky)]))
    p = lint(log, doc)
    assert p.ok and any(w.startswith("entry e1 BR1 statement: long sentence") for w in p.warnings), p.warnings
    assert sum("long sentence" in w and "word word" in w for w in p.warnings) == 1, p.warnings
    assert any(w.startswith("entry e1 BR1 risk: long sentence") for w in p.warnings), p.warnings
    # A wording field the walk does not read is judged from the edit itself, named by its key.
    named = make_log(make_entry(edits=[FieldEdit("BR1", "name", "A token is checked", long)]))
    assert any(w.startswith("entry e1 BR1.name: long sentence") for w in lint(named, doc).warnings)


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


# --- the rehearsal's findings (2026-09-17), each pinned -------------------------------------

def test_an_index_one_past_the_end_appends_and_beyond_it_is_refused_in_words(capsys):
    """The rehearsal's `sites[2]` with `was: null` on a two-site rule crashed lint with the bare
    message `ERROR: 'sites[2]'`. Now it appends; an index further out, or a field of an item that
    is not there, is refused with the append rule in the message."""
    doc = make_doc()                                      # BR1 has one site
    site = {"where": "srv.py:9", "why": "guards the second door"}
    log = make_log(make_entry(edits=[FieldEdit("BR1", "sites[1]", None, site)]))
    p = lint(log, doc)
    assert p.ok, p.errors
    new, done = apply(log, doc)
    assert new["rules"][0]["sites"] == [{"where": "a.py:1", "why": "guards"}, site] and done.edits == 1
    beyond = make_log(make_entry(edits=[FieldEdit("BR1", "sites[5]", None, site)]))
    assert lint(beyond, doc).errors == ["entry e1: BR1.sites[5] — no such item in the map; the list has 1 item(s) "
                                        "and this log appends 0 before it, so sites[1] is the index that appends"]
    nested = make_log(make_entry(edits=[FieldEdit("BR1", "sites[1].why", None, "w")]))
    assert any("BR1.sites[1].why — no such item" in e for e in lint(nested, doc).errors)
    with pytest.raises(ValueError, match="sites\\[3\\]: no such field or item"):
        set_field({"sites": []}, "sites[3]", site)
    with tempfile.TemporaryDirectory() as td:
        old = write(td, "old.json", json.dumps(doc))
        bad = write(td, "bad.json", dump_log(beyond))
        assert changelog.main(["lint", bad, "--map", old]) == 1
        text = capsys.readouterr()
        assert "no such item in the map" in text.out and "KeyError" not in text.err and "'sites[5]'" not in text.err


def test_a_log_may_append_several_items_to_one_list_and_removals_never_shift_another_entry_s_edit():
    """Two appends on one list, in one entry or two, land in order; the second is addressed one
    past the end the first left. A removal in one entry and an edit by index in another read the
    map as it was: the removals land last across the whole log, so `sites[1].why` still names B
    after another entry removed `sites[0]`. An edit inside an item a removal takes out is refused,
    because it would land and vanish."""
    doc = make_doc()
    doc["rules"][0]["sites"] = [{"where": "srv.py:1", "why": "A"}, {"where": "srv.py:2", "why": "B"}]
    c, d = {"where": "srv.py:3", "why": "C"}, {"where": "srv.py:4", "why": "D"}
    log = make_log(make_entry("e1", edits=[FieldEdit("BR1", "sites[2]", None, c), FieldEdit("BR1", "sites[3]", None, d)]))
    assert lint(log, doc).ok, lint(log, doc).errors
    assert [x["why"] for x in apply(log, doc)[0]["rules"][0]["sites"]] == ["A", "B", "C", "D"]
    two = make_log(make_entry("e1", edits=[FieldEdit("BR1", "sites[2]", None, c)]),
                   make_entry("e2", edits=[FieldEdit("BR1", "sites[3]", None, d)]))
    assert lint(two, doc).ok and [x["why"] for x in apply(two, doc)[0]["rules"][0]["sites"]] == ["A", "B", "C", "D"]
    skip = make_log(make_entry("e1", edits=[FieldEdit("BR1", "sites[2]", None, c), FieldEdit("BR1", "sites[4]", None, d)]))
    assert lint(skip, doc).errors == ["entry e1: BR1.sites[4] — no such item in the map; the list has 2 item(s) and "
                                      "this log appends 1 before it, so sites[3] is the index that appends"]
    shifted = make_log(make_entry("e1", edits=[FieldEdit("BR1", "sites[0]", {"where": "srv.py:1", "why": "A"}, None)]),
                       make_entry("e2", edits=[FieldEdit("BR1", "sites[1].why", "B", "B2"), FieldEdit("BR1", "sites[2]", None, c)]))
    assert lint(shifted, doc).ok, lint(shifted, doc).errors
    assert [x["why"] for x in apply(shifted, doc)[0]["rules"][0]["sites"]] == ["B2", "C"]
    inside = make_log(make_entry("e1", edits=[FieldEdit("BR1", "sites[1]", {"where": "srv.py:2", "why": "B"}, None)]),
                      make_entry("e2", edits=[FieldEdit("BR1", "sites[1].why", "B", "B2")]))
    assert lint(inside, doc).errors == ["entry e2: edits BR1.sites[1].why, inside sites[1], which entry e1 removes"]


def test_two_edits_whose_targets_nest_are_refused_whatever_their_spelling_and_the_rest_land_by_identity():
    """The review's F1: a whole list and one of its items, an item removed by index and edited by
    selector, a dict removed and a field in it edited — each pair used to lint clean and lose one
    edit, or crash lint out of apply with a message naming the wrong cause. Now every pair is
    refused at lint, and edits that do not nest land on the item they named even after another
    edit renumbered it."""
    doc = make_doc(entities=[make_entity("E1", "Thing")])
    doc["rules"][0]["sites"] = [{"where": "srv.py:1", "why": "A"}, {"where": "srv.py:2", "why": "B"}]
    doc["entities"][0]["store"] = {"notes": "kept in a file"}
    whole = [{"where": "srv.py:9", "why": "Z"}]
    cases = [
        (make_log(make_entry("e1", edits=[FieldEdit("BR1", "sites[1].why", "B", "B2")]),
                  make_entry("e2", edits=[FieldEdit("BR1", "sites", doc["rules"][0]["sites"], whole)])),
         "entry e1: edits BR1.sites[1].why, inside sites, which entry e2 edits"),
        (make_log(make_entry("e1", elements=["E1"], edits=[FieldEdit("E1", "fields[0]", {"name": "id", "type": "str"}, None)]),
                  make_entry("e2", elements=["E1"], edits=[FieldEdit("E1", "fields[name=id].type", "str", "int")])),
         "entry e2: edits E1.fields[name=id].type, inside fields[0], which entry e1 removes"),
        (make_log(make_entry("e1", elements=["E1"], edits=[FieldEdit("E1", "store", {"notes": "kept in a file"}, None)]),
                  make_entry("e2", elements=["E1"], edits=[FieldEdit("E1", "store.notes", "kept in a file", "kept in memory")])),
         "entry e2: edits E1.store.notes, inside store, which entry e1 removes"),
        (make_log(make_entry("e1", elements=["E1"], edits=[FieldEdit("E1", "fields[0].type", "str", "int")]),
                  make_entry("e2", elements=["E1"], edits=[FieldEdit("E1", "fields[name=id].type", "str", "text")])),
         "entry e2: E1.fields[name=id].type names the same field or item as entry e1's fields[0].type"),
        (make_log(make_entry("e1", edits=[FieldEdit("BR1", "sites", doc["rules"][0]["sites"], whole)]),
                  make_entry("e2", edits=[FieldEdit("BR1", "sites[2]", None, {"where": "srv.py:3", "why": "C"})])),
         "entry e2: edits BR1.sites[2], inside sites, which entry e1 edits"),
    ]
    for log, message in cases:
        assert lint(log, doc).errors == [message], (lint(log, doc).errors, message)
    # A renumbered step is still found by the selector: targets are resolved before anything lands.
    renumber = make_log(make_entry("e1", elements=["UC1"], edits=[FieldEdit("flow:UC1", "steps[n=2].n", 2, 5)]),
                        make_entry("e2", elements=["UC1"], edits=[FieldEdit("flow:UC1", "steps[n=2].phrase", "does thing 2", "does the fifth")]))
    p = lint(renumber, doc)
    assert not any("cannot be applied" in e for e in p.errors), p.errors
    new = apply(renumber, doc)[0] if p.ok else None
    if new is not None:
        assert new["flows"][0]["steps"][1] == {"n": 5, "src": "R1", "dst": "C1", "phrase": "does the fifth", "where": "srv.py:21"}
    # A whole-list replacement and a nested edit, through the command: JSON with ok false, exit 1.
    with tempfile.TemporaryDirectory() as td:
        old = write(td, "old.json", json.dumps(doc))
        bad = write(td, "bad.json", dump_log(cases[0][0]))
        import io, contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = changelog.main(["check", bad, "--map", old, "--json"])
        payload = json.loads(out.getvalue())
        assert code == 1 and payload["ok"] is False and payload["errors"][0].startswith("lint: entry e1: edits BR1.sites[1].why")
        with contextlib.redirect_stdout(out):
            assert changelog.main(["check", bad, "--map", old]) == 1
        assert "check: the log does not fit the map; lint's errors come first" in out.getvalue()


def test_the_review_s_nits_each_pinned():
    """F6 a glossary term with an apostrophe keeps its whole name in the box label; F8 a map that
    does not load before the log still gets only the log's own boxes judged; F9 a row removed
    twice and an index into a list the row does not have are plain errors."""
    doc = make_doc(glossary=[{"term": "o'brien", "meaning": "a kind of team", "source": "m.py:1"}])
    long = " ".join(["word"] * 24) + "."
    log = make_log(make_entry(elements=["glossary:o'brien"], edits=[FieldEdit("glossary:o'brien", "meaning", "a kind of team", long)]))
    p = lint(log, doc)
    assert p.ok and sum("long sentence" in w for w in p.warnings) == 1, p.warnings
    assert any(w.startswith("entry e1 glossary 'o'brien': long sentence") for w in p.warnings), p.warnings
    after = load_model(json.dumps(apply(log, doc)[0]))
    warns = _prose_warnings(log, {"nonsense": 1}, after, [])
    assert warns and all("o'brien" in w for w in warns), warns
    twice = make_log(make_entry("e1", elements=["E1"], removed=["E1"]), make_entry("e2", elements=["E1"], removed=["E1"]))
    assert "entry e2: removes E1, which entry e1 also removes" in lint(twice, doc).errors
    nolist = make_log(make_entry(edits=[FieldEdit("BR1", "sites[0]", None, {"where": "srv.py:9", "why": "w"})]))
    doc2 = make_doc()
    del doc2["rules"][0]["sites"]
    assert lint(nolist, doc2).errors == ["entry e1: BR1.sites[0] — BR1 has no `sites` list; add it whole, as `sites` with `was: null`"]


def test_a_useless_waiver_warns_whatever_the_flags():
    """The warning was skipped whenever `--touched` was given, so a waiver on a box the code never
    touched and the map never changed passed silently."""
    old = make_doc()
    new = copy(old)
    impact = {"impacts": {"C1": {"cause": "direct", "change": "modified", "resolution": "line"}}}
    log = make_log(make_entry(elements=["BR1"]), waived=[Waiver("C1", "a rename"), Waiver("E1", "nothing at all")])
    p = check(log, old, new, impact)
    assert p.ok and p.warnings == ["waived E1 did not change in the map and the code did not touch it"]
    assert check(log, old, new).warnings == ["waived C1 did not change in the map", "waived E1 did not change in the map"]


def test_the_sentences_of_an_added_row_face_the_readability_check():
    """Added rows were never read by lint's readability check: the rehearsal met its new rule's
    long risk and em dash only at validate, after apply and commit. Lint now reads the validator's
    own field walk over what the log puts in the map, so a rule's risk and a way in's trigger count
    (the diff engine files both as structure), and the sentences the map already held are not
    judged again."""
    doc = make_doc()
    long = " ".join(["word"] * 24) + "."
    row = make_rule("BR2", "A guard holds", risk=long)
    row["statement"] = "A guard holds — always."
    ep = {"id": "EP2", "kind": "cli", "trigger": " ".join(["step"] * 23) + ".", "component": "C1", "source": "srv.py:12",
          "activation": "external", "runs_in": [], "cadence": "", "cadence_source": ""}
    log = make_log(make_entry(elements=["BR2", "EP2"], added=[Addition("rules", row), Addition("entry_points", ep)]))
    p = lint(log, doc)
    assert p.ok, p.errors
    warns = "\n".join(p.warnings)
    assert "entry e1 BR2 risk: long sentence" in warns, warns
    assert "entry e1 BR2 statement: em dash" in warns, warns
    assert "entry e1 EP2 trigger: long sentence" in warns, warns
    assert "BR1" not in warns and "C1 purpose" not in warns, "what the map already held is not judged again"


def test_the_gate_runs_before_the_write_on_the_log_applied_to_a_copy():
    """`check --map`: the same gate before `apply`, so a gap costs a trip back to the log and not a
    restore of the map — the rehearsal found "back to step 3" impossible once apply had moved the
    pin, because lint and apply then refused the log."""
    doc = make_doc()
    before = copy(doc)
    arrow = Addition("edges", make_edge("C1", "reads", "E1", "srv.py:12"))
    unnamed = make_log(make_entry(elements=["BR1"], added=[arrow]))
    p = check_before_write(unnamed, doc)
    assert p.errors == ["C1 an arrow added in the map, and no entry names it"] and doc == before
    impact = {"impacts": {"C1": {"cause": "direct", "change": "modified", "resolution": "line"},
                          "E1": {"cause": "direct", "change": "modified", "resolution": "symbol"}}}
    named = make_log(make_entry(elements=["BR1", "C1"], added=[arrow]))
    p = check_before_write(named, doc, impact)
    assert p.ok and p.warnings == ["the code touched E1 and no entry names or waives it"] and doc == before
    unfit = make_log(make_entry(edits=[FieldEdit("BR1", "risk", "stale", "new")]))
    assert check_before_write(unfit, doc).errors == [
        "lint: entry e1: BR1.risk — the map holds \"a team is left open\", the log says was \"stale\""]
    new, _ = apply(named, doc)
    after = check(named, doc, new, impact)
    assert after.ok and after.warnings == p.warnings, "the gate after the write agrees with the one before"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
