#!/usr/bin/env python3
"""The Architecture picture's merged texts: which lines want one, how a text is checked by rule, what
`record` keeps, and that the viewer's text carries a kept one.

Conventions: top-level test functions, no classes/fixtures (helpers are `make_*`).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from coyomap import line_texts, line_texts_cmd
from coyomap.contract import render, slots
from coyomap.line_texts import Line
from coyomap.model import load_model
from coyomap.viewer import gen_viewer as gv
from coyomap.viewer.build_graph import GraphDict
from coyomap.views import model_to_graph

from test_architecture_view import make_arch_map


# --- builders -------------------------------------------------------------------

def make_two_story_map() -> dict[str, Any]:
    """The Architecture test map, plus a third story the admin runs through the same page and the
    same client: deleting a thing. Its line from the client into the server says "send the delete",
    so that line carries two different sentences."""
    doc = copy.deepcopy(make_arch_map())
    doc["roles"][0]["drives"] = "UC1, UC3"
    doc["use_cases"].append({"id": "UC3", "name": "Delete a thing", "actors": ["R1"],
                             "capability": "CAP1", "trigger": "The admin deletes a thing.",
                             "outcome": "The thing is gone."})
    doc["flows"].append({"uc": "UC3", "title": "Delete a thing", "steps": [
        {"n": 1, "src": "R1", "dst": "I1", "phrase": "pick the thing"},
        {"n": 2, "src": "I1", "dst": "C1", "phrase": "carry the pick in", "where": "src/page.ts:3"},
        {"n": 3, "src": "C1", "dst": "C2", "phrase": "ask for the delete", "where": "src/page.ts:20"},
        {"n": 4, "src": "C2", "dst": "C3", "phrase": "send the delete", "where": "src/client.ts:9"},
        {"n": 5, "src": "C3", "dst": "C5", "phrase": "remove the thing", "where": "src/api.py:50"},
        {"n": 6, "src": "C5", "dst": "E1", "phrase": "delete the row", "where": "src/save.py:9"}]})
    return doc


def make_graph() -> GraphDict:
    return model_to_graph(load_model(json.dumps(make_two_story_map())))


def make_line(key: str = "k1", sentences: tuple[str, ...] = ("post the thing", "send the delete")
              ) -> Line:
    return Line(key=key, src="Screens", dst="Server", sentences=sentences)


def make_map_folder(parent: Path) -> Path:
    """A `.coyomap/` folder holding the two-story map, as `record` reads it."""
    folder = parent / ".coyomap"
    folder.mkdir()
    (folder / "project-map.json").write_text(json.dumps(make_two_story_map()), encoding="utf-8")
    return folder


# --- which lines want a text, and their key ----------------------------------------

def test_the_key_is_the_distinct_sentences_whatever_their_order():
    one = line_texts.line_key(["send the delete", "post the thing"])
    assert one == line_texts.line_key(["post the thing", "send the delete", "post the thing"])
    assert one != line_texts.line_key(["post the thing", "send the delete!"])


def test_a_line_wants_a_text_only_when_it_carries_two_different_sentences():
    assert line_texts.wants_text(["post the thing", "send the delete"])
    assert not line_texts.wants_text(["post the thing", "post the thing"])
    assert not line_texts.wants_text(["post the thing", ""])


def test_the_lines_are_the_ones_the_pictures_draw_once_per_key():
    lines = line_texts_cmd.drawn_lines(make_graph())
    assert lines, "the delete story shares a line with the save story"
    assert len({ln.key for ln in lines}) == len(lines)
    shared = [ln for ln in lines if "send the delete" in ln.sentences]
    assert shared and "post the thing" in shared[0].sentences, [ln.to_json() for ln in lines]
    for ln in lines:
        assert ln.key == line_texts.line_key(ln.sentences)


def test_a_map_whose_stories_never_share_a_line_wants_no_text():
    assert line_texts_cmd.drawn_lines(model_to_graph(load_model(json.dumps(make_arch_map())))) == []


# --- the rules no reader is needed for ----------------------------------------------

def test_a_clean_text_has_no_fault():
    assert line_texts.text_faults("post a thing or send its delete", ["post the thing"]) == []


def test_each_rule_names_its_fault():
    said = ["post the thing", "send the delete"]
    cases = {
        "": "no text",
        "Post the thing. Send the delete.": "more than one sentence",
        " ".join(["word"] * 21): "21 words",
        "post the thing — or send the delete": "a dash",
        "post the thing; send the delete": "a semicolon",
        "post the thing, then send the delete": '"then"',
        "It posts the thing or sends the delete": 'opens with "It"',
        "call post_thing() or send the delete": "code-shaped",
    }
    for text, fault in cases.items():
        found = line_texts.text_faults(text, said)
        assert any(fault in f for f in found), (text, found)


def test_a_word_its_own_sentences_use_is_not_held_against_it():
    said = ["check the token, then open the stream", "open the stream"]
    assert line_texts.text_faults("check the token, then open the stream", said) == []


def test_lint_names_a_missing_text_and_a_text_for_no_line():
    faults = line_texts.lint([make_line("k1"), make_line("k2")], {"k1": "post or delete a thing",
                                                                   "k9": "something"})
    assert faults == {"k2": ["no text for this line"], "k9": ["no line has this key"]}


# --- what record keeps --------------------------------------------------------------

def test_only_a_text_the_check_passed_and_the_rules_allow_is_kept():
    lines = [make_line("k1"), make_line("k2"), make_line("k3"), make_line("k4")]
    texts = {"k1": "post the thing or send the delete", "k2": "delete a role",
             "k3": "post the thing; send the delete", "k4": "post or delete the thing"}
    verdicts: dict[str, dict[str, object]] = {
        "k1": {"verdict": "ok"},
        "k2": {"verdict": "reject", "says_more": ["delete a role"], "leaves_out": ["post the thing"]},
        "k3": {"verdict": "ok"}}
    choice = line_texts.choose(lines, {}, texts, verdicts)
    assert choice.kept == {"k1": "post the thing or send the delete"}
    assert choice.rejected == {"k2": ["says more: delete a role", "leaves out: post the thing"]}
    assert list(choice.faulty) == ["k3"]
    assert choice.unchecked == ["k4"]


def test_an_old_text_stays_while_its_line_is_drawn_and_goes_when_it_is_not():
    choice = line_texts.choose([make_line("k1")], {"k1": "old words", "gone": "older words"}, {}, {})
    assert choice.kept == {"k1": "old words"}
    assert choice.dropped == ["gone"]


def test_record_writes_the_kept_texts_beside_the_map(tmp_path: Path):
    folder = make_map_folder(tmp_path)
    lines = line_texts_cmd.drawn_lines(make_graph())
    written = {ln.key: "post the thing or send the delete" for ln in lines}
    (tmp_path / "written.json").write_text(json.dumps(written))
    (tmp_path / "verdicts.json").write_text(json.dumps({k: {"verdict": "ok"} for k in written}))
    code = line_texts_cmd.main(["record", "--map", str(folder / "project-map.json"),
                                "--texts", str(tmp_path / "written.json"),
                                "--verdicts", str(tmp_path / "verdicts.json")])
    assert code == 0
    assert line_texts.load(folder) == written
    # …and a second `pending` has nothing left to write.
    out = tmp_path / "pending.json"
    assert line_texts_cmd.main(["pending", "--map", str(folder / "project-map.json"),
                                "--out", str(out)]) == 0
    assert json.loads(out.read_text()) == []


def test_a_texts_file_that_is_not_an_object_of_texts_is_refused(tmp_path: Path):
    (tmp_path / line_texts.FILE_NAME).write_text("[1, 2]")
    try:
        line_texts.load(tmp_path)
    except ValueError as exc:
        assert line_texts.FILE_NAME in str(exc)
    else:
        raise AssertionError("a list must not read as no texts")


# --- the viewer's text carries the kept text -----------------------------------------

def test_the_text_beside_the_picture_carries_the_merged_text_of_a_line_that_has_one():
    graph = make_graph()
    line = line_texts_cmd.drawn_lines(graph)[0]
    _drawings, texts = gv.gen_arch_views(graph, {line.key: "post or delete the thing"})
    entries = [e for t in texts.values() for e in t["lines"]]
    same = [e for e in entries if line_texts.line_key(x["text"] for x in e["sentences"]) == line.key]
    assert same, "the line is drawn on at least one picture"
    assert all(e.get("merged") == "post or delete the thing" for e in same)
    assert all(not e.get("merged") for e in entries if e not in same)


def test_a_line_with_one_sentence_never_carries_a_merged_text():
    graph = make_graph()
    _drawings, texts = gv.gen_arch_views(graph, {line_texts.line_key(["post the thing"]): "x"})
    assert not [e for t in texts.values() for e in t["lines"] if e.get("merged")]


# --- the two briefs -------------------------------------------------------------------

def test_the_writer_brief_names_its_slots_and_its_own_check():
    assert set(slots("line-texts")) == {"LINES", "OUT", "AGENT_ID", "COYOMAP_HOME"}
    text = render("line-texts")
    assert "line-texts lint --lines «LINES» «OUT»" in text
    assert "never with \"then\"" in text


def test_the_check_brief_reads_only_the_texts_and_never_the_code():
    assert set(slots("line-texts-check")) == {"TEXTS", "OUT", "AGENT_ID"}
    text = render("line-texts-check")
    assert "never the code" in text
    assert '"says_more"' in text and '"leaves_out"' in text
