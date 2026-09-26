#!/usr/bin/env python3
"""The Architecture view: every story merged into one flow, drawn over the product's boxes.

These tests hold the rules the picture is drawn by, on the smallest map that has every part: two
people, two doors, two subsystems, one shared sub-use case, one record kept in a database, one
business rule. The viewer's own behaviour (following one story, one box's steps) is held in
`test_viewer_browser.py`, because only a browser can see it.

Run either way: `python3 tests/test_architecture_view.py` or `pytest tests/test_architecture_view.py`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from coyomap.model import FORMAT, load_model
from coyomap.viewer import gen_viewer as gv
from coyomap.viewer.build_graph import GraphDict
from coyomap.views import model_to_graph

_FIXTURE_MAP = Path(__file__).resolve().parent / "fixtures" / "mcpolis-project-map.json"
_VIEWER_JS = Path(__file__).resolve().parents[1] / "tools" / "coyomap" / "viewer" / "viewer.js"


# --- builders -------------------------------------------------------------------

def make_arch_map() -> dict[str, Any]:
    """Save a thing (the admin, through a web page) and ask the agent (a member, through an MCP
    address). Saving runs a shared sub-use case that checks the ask, where a business rule decides,
    then keeps the thing in a record that lives in a database."""
    return {
        "format": FORMAT, "title": "T", "goal": "G",
        "roles": [{"id": "R1", "name": "Admin", "kind": "human", "audience": "user", "wants": "x",
                   "drives": "UC1"},
                  {"id": "R2", "name": "Member", "kind": "human", "audience": "user", "wants": "y",
                   "drives": "UC2"}],
        "capabilities": [{"id": "CAP1", "name": "Doing things", "purpose": "does things",
                          "happy_path": "expected"}],
        "use_cases": [{"id": "UC1", "name": "Save a thing", "actors": ["R1"], "capability": "CAP1",
                       "trigger": "The admin types a thing.", "outcome": "The thing is saved."},
                      {"id": "UC2", "name": "Ask the agent", "actors": ["R2"], "capability": "CAP1",
                       "trigger": "The member asks.", "outcome": "The member has an answer."}],
        "happy_path": [{"id": "HP1", "uc": "UC1"}],
        "interfaces": [{"id": "I1", "name": "Web page", "what": "the page", "side": "ours",
                        "facing": "user", "kind": "website"},
                       {"id": "I2", "name": "Tools address", "what": "the MCP address", "side": "ours",
                        "facing": "user", "kind": "mcp"}],
        "subsystems": [{"id": "S1", "name": "Screens", "purpose": "what people see"},
                       {"id": "S2", "name": "Server", "purpose": "what answers"}],
        "components": [
            {"id": "C1", "name": "Page", "subsystem": "S1", "purpose": "shows the thing", "files": ["src/page.ts"]},
            {"id": "C2", "name": "Client", "subsystem": "S1", "purpose": "sends asks", "files": ["src/client.ts"]},
            {"id": "C3", "name": "API", "subsystem": "S2", "purpose": "takes asks", "files": ["src/api.py"]},
            {"id": "C4", "name": "Checker", "subsystem": "S2", "purpose": "checks asks", "files": ["src/check.py"]},
            {"id": "C5", "name": "Saver", "subsystem": "S2", "purpose": "saves things", "files": ["src/save.py"]}],
        "deps": [{"id": "D1", "name": "Database", "type": "mongodb", "used_for": "keeps things"}],
        "entities": [{"id": "E1", "name": "Thing", "meaning": "a thing", "source": "src/save.py:1",
                      "store": {"dep": "D1", "container": "things", "mode": "collection"}}],
        "edges": [{"src": "C2", "verb": "calls", "dst": "C3", "why": "to post", "where": "src/client.ts:4"},
                  {"src": "C5", "verb": "persists", "dst": "E1", "why": "keeps it", "where": "src/save.py:4"}],
        "flows": [
            {"uc": "UC1", "title": "Save a thing", "steps": [
                {"n": 1, "src": "R1", "dst": "I1", "phrase": "type the thing"},
                {"n": 2, "src": "I1", "dst": "C1", "phrase": "carry the thing in", "where": "src/page.ts:3"},
                {"n": 3, "src": "C1", "dst": "C2", "phrase": "send the thing", "where": "src/page.ts:9"},
                {"n": 4, "src": "C2", "dst": "C3", "phrase": "post the thing", "where": "src/client.ts:4"},
                {"n": 5, "src": "C3", "dst": "C4", "phrase": "", "subflow": "SF1"},
                {"n": 6, "src": "C4", "dst": "C5", "phrase": "save the thing", "where": "src/check.py:9"},
                {"n": 7, "src": "C5", "dst": "E1", "phrase": "write the row", "where": "src/save.py:4"},
                {"n": 8, "src": "C3", "dst": "C2", "phrase": "return the saved thing", "where": "src/api.py:30"},
                {"n": 9, "src": "C1", "dst": "I1", "phrase": "show the saved thing", "where": "src/page.ts:12"},
                {"n": 10, "src": "I1", "dst": "R1", "phrase": "present the saved thing"}]},
            {"uc": "UC2", "title": "Ask the agent", "steps": [
                {"n": 1, "src": "R2", "dst": "I2", "phrase": "ask a question"},
                {"n": 2, "src": "I2", "dst": "C3", "phrase": "carry the question in", "where": "src/api.py:40"},
                {"n": 3, "src": "C3", "dst": "I2", "phrase": "answer", "where": "src/api.py:44"},
                {"n": 4, "src": "I2", "dst": "R2", "phrase": "show the answer"}]}],
        "subflows": [{"id": "SF1", "name": "check the ask", "steps": [
            {"n": 1, "src": "C3", "dst": "C4", "phrase": "check the ask", "where": "src/api.py:20"},
            {"n": 2, "src": "C4", "dst": "C3", "phrase": "return the verdict", "where": "src/check.py:5"}]}],
        "blocks": [{"id": "BLK1", "name": "Checks"}],
        "rules": [{"id": "BR1", "name": "Asks are checked", "statement": "Every ask is checked.",
                   "block": "BLK1", "confidence": "verified",
                   "sites": [{"where": "src/api.py:20", "why": "checks it"}]}],
    }


def make_graph(doc: dict[str, Any] | None = None) -> GraphDict:
    return model_to_graph(load_model(json.dumps(doc if doc is not None else make_arch_map())))


def make_model(budget: int = gv.ARCH_BOX_BUDGET) -> gv._ArchModel:
    model = gv._arch_model(make_graph(), "", "all", budget)
    assert model is not None
    return model


def lines_of(model: gv._ArchModel) -> dict[tuple[str, str], gv._ArchLine]:
    return {(ln["src"], ln["dst"]): ln for ln in model["lines"]}


def make_fixture_graph() -> GraphDict:
    return model_to_graph(load_model(_FIXTURE_MAP.read_text()))


# --- what the picture draws --------------------------------------------------------

def test_the_picture_draws_people_doors_subsystems_the_sub_use_case_and_the_database():
    model = make_model()
    assert model["people"] == ["Admin", "Member"]
    assert model["doors"] == ["I1", "I2"]
    assert model["inside"] == ["S1", "S2", "SF1"]
    assert model["stores"] == ["D1"]
    assert set(lines_of(model)) == {("Admin", "I1"), ("I1", "S1"), ("S1", "S2"), ("S2", "SF1"),
                                    ("S2", "D1"), ("Member", "I2"), ("I2", "S2")}


def test_a_shared_sub_use_case_is_one_box_and_its_inside_is_not_drawn():
    """The check runs from the API to the Checker and back inside the shared sub-use case: the
    picture draws one line into the box and nothing between the two components."""
    ln = lines_of(make_model())
    assert ("S2", "SF1") in ln
    assert not any("C4" in pair for pair in ln)
    assert ln[("S2", "SF1")]["sentences"] == [("UC1", "check the ask")]


def test_a_record_is_drawn_as_its_database_with_no_step_number():
    line = lines_of(make_model())[("S2", "D1")]
    assert line["store"] and line["number"] == 0 and not line["always"]
    assert line["verb"] == "persists"   # the code's link to the record counts for its database


def test_every_story_reads_forward_and_answers_are_not_drawn():
    model = make_model()
    numbers = {(ln["src"], ln["dst"]): ln["number"] for ln in model["lines"] if not ln["store"]}
    assert [numbers[p] for p in model["stories"]["UC1"] if p in numbers] == [1, 2, 3, 4]
    assert [numbers[p] for p in model["stories"]["UC2"]] == [1, 2]
    # "return the saved thing" goes back to the box that called: an answer, left out
    assert ("S2", "S1") not in lines_of(model)


def test_a_story_ends_at_the_door_that_hands_its_result_back():
    assert make_model()["ends"] == {"UC1": "I1", "UC2": "I2"}


def test_a_line_where_a_business_rule_decides_carries_the_mark_and_names_the_rule():
    graph = make_graph()
    model = gv._arch_model(graph, "", "all")
    assert model is not None
    drawing = gv._arch_mermaid(graph, model)
    assert re.search(rf"S2 --> *\|\"[^|]*{gv.RULE_MARK}\"\| *SF1", drawing)
    entry = next(e for e in gv._arch_text(graph, model) if e["dstBox"] == "SF1")
    assert entry["rules"] == [{"id": "BR1", "name": "Asks are checked"}]
    assert entry["rulesByStory"] == {"UC1": [{"id": "BR1", "name": "Asks are checked"}]}


def test_a_grey_line_names_the_boxes_it_passes_through():
    """With room for one box, the Screens box is folded into the line from the web page."""
    graph = make_graph()
    model = gv._arch_model(graph, "", "all", budget=1)
    assert model is not None
    line = lines_of(model)[("I1", "S2")]
    assert (line["hidden"], line["via"]) == (1, ["S1"])
    entry = next(e for e in gv._arch_text(graph, model) if (e["srcBox"], e["dstBox"]) == ("I1", "S2"))
    assert entry["via"] == ["Screens"]


def test_via_ai_agent_is_said_only_of_a_person_who_comes_in_only_through_an_agent():
    graph = make_graph()
    model = gv._arch_model(graph, "", "all")
    assert model is not None
    drawing = gv._arch_mermaid(graph, model)
    member = next(ln for ln in drawing.splitlines() if ln.strip().startswith(gv._person_id("Member") + "["))
    admin = next(ln for ln in drawing.splitlines() if ln.strip().startswith(gv._person_id("Admin") + "["))
    assert "data-pill=via" in member and "data-pill" not in admin


def test_each_story_carries_its_trigger_outcome_and_its_own_lines():
    graph = make_graph()
    model = gv._arch_model(graph, "", "all")
    assert model is not None
    first = gv._arch_stories(graph, model)[0]
    assert (first["uc"], first["trigger"], first["outcome"]) == (
        "UC1", "The admin types a thing.", "The thing is saved.")
    assert first["lines"][0] == [gv._person_id("Admin"), "I1"]
    assert (first["start"], first["end"]) == (gv._person_id("Admin"), "I1")


# --- what a component's kind changes ------------------------------------------------------

def make_kinded_map(**kinds: str) -> dict[str, Any]:
    """The same map with the Client in a subsystem of its own, and a kind on the named components."""
    doc = make_arch_map()
    doc["subsystems"].append({"id": "S3", "name": "Passing calls on", "purpose": "passes calls on"})
    for c in doc["components"]:
        if c["id"] == "C2":
            c["subsystem"] = "S3"
        if c["id"] in kinds:
            c["kind"] = kinds[c["id"]]
    return doc


def test_without_a_kind_the_client_between_page_and_server_is_drawn():
    ln = lines_of(gv._arch_model(make_graph(make_kinded_map()), "", "all") or make_model())
    assert ("C1", "C2") in ln and ("C2", "S2") in ln


def test_a_pipe_is_drawn_through():
    model = gv._arch_model(make_graph(make_kinded_map(C2="pipe")), "", "all")
    assert model is not None
    ln = lines_of(model)
    assert ("C1", "S2") in ln
    assert not any("C2" in pair for pair in ln)
    assert ln[("C1", "S2")]["sentences"] == [("UC1", "send the thing")]


def test_a_store_stands_alone_inside_its_subsystem():
    model = gv._arch_model(make_graph(make_kinded_map(C5="store")), "", "all")
    assert model is not None
    assert "C5" in model["inside"] and "S2" not in model["inside"]
    assert ("C5", "D1") in lines_of(model)
    assert ("SF1", "C5") in lines_of(model)   # the save after the check, hidden inside S2 before


# --- the use case map marks the same things ---------------------------------------------

def test_a_use_case_map_marks_the_arrow_that_runs_a_deciding_sub_use_case():
    graph = make_graph()
    flow = next(f for f in graph["flows"] if f["uc"] == "UC1")
    drawing = gv.gen_flow_map_mermaid(graph, flow)
    assert re.search(rf"C3 --> *\|\"5 {gv.RULE_MARK}\"\| *SF1", drawing)
    assert gv.flow_map_ends(graph, flow) == {"start": "FA0", "end": "FA0"}


# --- the live map: rules that hold on every picture --------------------------------------

def test_on_every_picture_of_the_live_map_no_story_reads_backwards_and_every_box_has_a_way_in():
    graph = make_fixture_graph()
    features = ["", *(f["id"] for f in gv.arch_features(graph))]
    for scope in gv.ARCH_SCOPES:
        for feature in features:
            model = gv._arch_model(graph, feature, scope)
            if model is None:
                continue
            numbers = {(ln["src"], ln["dst"]): ln["number"] for ln in model["lines"] if not ln["store"]}
            for uc, seq in model["stories"].items():
                ns = [numbers[p] for p in seq if p in numbers]
                assert ns == sorted(ns), (scope, feature, uc, ns)
            drawn = set(model["doors"]) | set(model["inside"]) | set(model["outside"]) | set(model["stores"])
            reached = {ln["dst"] for ln in model["lines"]}
            assert drawn <= reached, (scope, feature, drawn - reached)


def test_the_viewer_key_shows_the_marks_the_generator_draws():
    """The key is drawn by the viewer, the marks by the generator: the two must stay the same."""
    js = _VIEWER_JS.read_text()
    assert f"const RULE_MARK = '{gv.RULE_MARK}';" in js
    assert f"const ARCH_STORE_LINE = '{gv.ARCH_STORE_LINE}';" in js


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
