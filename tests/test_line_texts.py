#!/usr/bin/env python3
"""The Architecture picture's merged texts: which lines want one, how a text is checked by rule, what
`record` keeps, and that the viewer's text carries a kept one.

Conventions: top-level test functions, no classes/fixtures (helpers are `make_*`).
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import stat
import tempfile
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


def test_a_word_a_sentence_uses_elsewhere_does_not_license_it():
    """One story's own "then open" does not let the text join two stories with "then close", and a
    sentence's `save_row` does not make `save` a word the map uses."""
    said = ["check the token, then open the stream", "call save_row on the store"]
    assert any('"then"' in f for f in
               line_texts.text_faults("check the token, then close the stream", said))
    assert any("code-shaped" in f for f in line_texts.text_faults("call save() or open it", said))
    assert any("a dash" in f for f in line_texts.text_faults("open it -- or close it", said))


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
    choice = line_texts.choose(lines, {}, texts, verdicts, checked=texts)
    assert choice.kept == {"k1": "post the thing or send the delete"}
    assert choice.rejected == {"k2": ["says more: delete a role", "leaves out: post the thing"]}
    assert list(choice.faulty) == ["k3"]
    assert choice.unchecked == ["k4"]


def test_an_old_text_stays_while_its_line_is_drawn_and_goes_when_it_is_not():
    choice = line_texts.choose([make_line("k1")], {"k1": "old words", "gone": "older words"}, {}, {},
                               checked={})
    assert choice.kept == {"k1": "old words"}
    assert choice.dropped == ["gone"]


def test_a_recheck_that_rejects_a_kept_text_takes_it_out():
    """The kept file handed back to a checker: a text a weaker check once passed must leave when this
    one rejects it, or it stays forever, because its key only changes with its sentences."""
    old = {"k1": "post the thing or send the delete", "k2": "post or delete the thing"}
    verdicts: dict[str, dict[str, object]] = {"k1": {"verdict": "ok"},
                                              "k2": {"verdict": "reject", "says_more": ["x"]}}
    choice = line_texts.choose([make_line("k1"), make_line("k2")], old, old, verdicts, checked=old)
    assert choice.kept == {"k1": "post the thing or send the delete"}
    assert list(choice.rejected) == ["k2"]


def test_pending_all_lists_the_lines_that_have_a_text_too(tmp_path: Path):
    folder = make_map_folder(tmp_path)
    lines = line_texts_cmd.drawn_lines(make_graph())
    line_texts.save(folder, {ln.key: "post the thing or send the delete" for ln in lines})
    for flag, expected in (([], 0), (["--all"], len(lines))):
        out = tmp_path / "pending.json"
        assert line_texts_cmd.main(["pending", "--map", str(folder / "project-map.json"),
                                    "--out", str(out), *flag]) == 0
        assert len(json.loads(out.read_text())) == expected


def make_picture(src: str, dst: str, *sentences: str) -> dict[str, Any]:
    return {"lines": [{"src": src, "dst": dst, "sentences": [{"text": t} for t in sentences]}]}


def test_a_line_drawn_between_other_boxes_on_another_picture_says_so():
    """One picture draws the Client as itself; another folds it into its subsystem. The writer must
    see both pairs, or it names a box one picture does not draw."""
    said = ("post the thing", "send the delete")
    lines = line_texts_cmd.lines_of_pictures({
        "all|": make_picture("Screens", "Server", *said),
        "all|CAP1": make_picture("Client", "Server", *said),
        "happy|": make_picture("Screens", "Server", *said)})
    assert len(lines) == 1
    assert lines[0].drawn_as == (("Screens", "Server"), ("Client", "Server"))
    assert lines[0].to_json()["drawn_as"] == [["Screens", "Server"], ["Client", "Server"]]
    assert line_texts.line_from_json(lines[0].to_json()) == lines[0]
    one = line_texts_cmd.lines_of_pictures({"all|": make_picture("Screens", "Server", *said)})
    assert "drawn_as" not in one[0].to_json()


def test_a_texts_file_with_a_value_that_is_not_text_is_refused(tmp_path: Path):
    path = tmp_path / "written.json"
    path.write_text(json.dumps({"k1": None}))
    try:
        line_texts.read_texts(path)
    except ValueError as exc:
        assert "k1" in str(exc)
    else:
        raise AssertionError("a null must not become the words None")


def test_saving_leaves_one_whole_file_and_nothing_beside_it(tmp_path: Path):
    line_texts.save(tmp_path, {"k2": "b", "k1": "a"})
    assert [p.name for p in tmp_path.iterdir()] == [line_texts.FILE_NAME]
    assert list(line_texts.load(tmp_path)) == ["k1", "k2"]


def test_record_on_a_map_with_no_shared_line_writes_no_file(tmp_path: Path):
    folder = tmp_path / ".coyomap"
    folder.mkdir()
    (folder / "project-map.json").write_text(json.dumps(make_arch_map()), encoding="utf-8")
    (tmp_path / "written.json").write_text("{}")
    (tmp_path / "verdicts.json").write_text("{}")
    (tmp_path / "to-check.json").write_text("[]")
    assert line_texts_cmd.main(["record", "--map", str(folder / "project-map.json"),
                                "--texts", str(tmp_path / "written.json"),
                                "--checked", str(tmp_path / "to-check.json"),
                                "--verdicts", str(tmp_path / "verdicts.json")]) == 0
    assert not (folder / line_texts.FILE_NAME).exists()


def test_record_writes_the_kept_texts_beside_the_map(tmp_path: Path):
    folder = make_map_folder(tmp_path)
    lines = line_texts_cmd.drawn_lines(make_graph())
    written = {ln.key: "post the thing or send the delete" for ln in lines}
    (tmp_path / "written.json").write_text(json.dumps(written))
    (tmp_path / "verdicts.json").write_text(json.dumps({k: {"verdict": "ok"} for k in written}))
    (tmp_path / "to-check.json").write_text(json.dumps([{"key": k, "merged": t}
                                                        for k, t in written.items()]))
    code = line_texts_cmd.main(["record", "--map", str(folder / "project-map.json"),
                                "--texts", str(tmp_path / "written.json"),
                                "--checked", str(tmp_path / "to-check.json"),
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


# --- a text is kept only as the checker read it (retro 2026-09-30, finding 5) ---------------------
# The writer rewrote written.json after `check-input` had read it; `choose` kept the file's text
# whenever the key's verdict was ok, so a text no checker read could ship under a verdict given for
# its old wording. Only the lead's own file watch caught it.

def test_a_text_changed_after_the_check_is_not_kept_whatever_its_verdict():
    lines = [make_line("k1"), make_line("k2")]
    checked = {"k1": "post the thing or send the delete", "k2": "post or delete the thing"}
    texts = {"k1": "post the thing or send the delete", "k2": "a text no checker read"}
    verdicts: dict[str, dict[str, object]] = {"k1": {"verdict": "ok"}, "k2": {"verdict": "ok"}}
    choice = line_texts.choose(lines, {}, texts, verdicts, checked=checked)
    assert choice.kept == {"k1": "post the thing or send the delete"}
    assert choice.changed == ["k2"]


def test_a_text_the_check_input_never_held_is_not_kept():
    lines = [make_line("k1")]
    texts = {"k1": "post the thing or send the delete"}
    choice = line_texts.choose(lines, {}, texts, {"k1": {"verdict": "ok"}}, checked={})
    assert choice.kept == {} and choice.unchecked == ["k1"]


def test_record_names_a_text_changed_after_the_check():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        folder = make_map_folder(tmp)
        lines = line_texts_cmd.drawn_lines(make_graph())
        written = {ln.key: "post the thing or send the delete" for ln in lines}
        (tmp / "to-check.json").write_text(json.dumps([{"key": k, "merged": "post or delete it"}
                                                       for k in written]))
        (tmp / "written.json").write_text(json.dumps(written))
        (tmp / "verdicts.json").write_text(json.dumps({k: {"verdict": "ok"} for k in written}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = line_texts_cmd.main(["record", "--map", str(folder / "project-map.json"),
                                        "--texts", str(tmp / "written.json"),
                                        "--checked", str(tmp / "to-check.json"),
                                        "--verdicts", str(tmp / "verdicts.json")])
        assert code == 0
        assert "CHANGED after the check, so not kept" in out.getvalue()
        assert not line_texts.load(folder)


def test_the_saved_texts_get_the_ordinary_permissions():
    """`save` wrote through a temporary file left readable by its owner only (0600)."""
    old = os.umask(0o022)
    try:
        with tempfile.TemporaryDirectory() as td:
            path = line_texts.save(Path(td), {"k1": "a"})
            assert stat.S_IMODE(path.stat().st_mode) == 0o644
    finally:
        os.umask(old)
