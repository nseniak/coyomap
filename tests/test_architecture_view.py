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


def test_a_story_of_thousands_of_steps_is_numbered_without_running_out_of_stack():
    chain = [(f"B{i}", f"B{i + 1}") for i in range(3000)]
    numbers = gv._story_order_numbers([chain])
    assert [numbers[a] for a in chain] == list(range(1, 3001))


def test_arrows_two_stories_take_in_opposite_orders_share_one_number():
    x, y, z = ("A", "B"), ("B", "C"), ("C", "D")
    numbers = gv._story_order_numbers([[x, y, z], [y, x]])
    assert numbers[x] == numbers[y] and numbers[z] == numbers[x] + 1


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


def make_two_server_pipe_map() -> dict[str, Any]:
    """The Client is a pipe that calls two servers in one story: the API saves the thing, and a
    Biller in a subsystem of its own charges for it. Each answer comes back through the pipe."""
    doc = make_kinded_map(C2="pipe")
    doc["subsystems"].append({"id": "S4", "name": "Billing things", "purpose": "bills"})
    doc["components"].append({"id": "C6", "name": "Biller", "subsystem": "S4", "purpose": "bills",
                              "files": ["src/bill.py"]})
    doc["flows"][0]["steps"] = [
        {"n": 1, "src": "R1", "dst": "I1", "phrase": "type the thing"},
        {"n": 2, "src": "I1", "dst": "C1", "phrase": "carry the thing in", "where": "src/page.ts:3"},
        {"n": 3, "src": "C1", "dst": "C2", "phrase": "send the thing", "where": "src/page.ts:9"},
        {"n": 4, "src": "C2", "dst": "C3", "phrase": "post the thing", "where": "src/client.ts:4"},
        {"n": 5, "src": "C3", "dst": "C2", "phrase": "return the saved thing", "where": "src/api.py:30"},
        {"n": 6, "src": "C2", "dst": "C6", "phrase": "charge for the thing", "where": "src/client.ts:8"},
        {"n": 7, "src": "C2", "dst": "C1", "phrase": "hand back the bill", "where": "src/client.ts:9"},
        {"n": 8, "src": "C1", "dst": "I1", "phrase": "show the saved thing", "where": "src/page.ts:12"},
        {"n": 9, "src": "I1", "dst": "R1", "phrase": "present the saved thing"}]
    return doc


def make_step(src: str, dst: str, key: str, phrase: str = "do it") -> gv._ArchStep:
    return gv._ArchStep(src=src, dst=dst, from_person=False, to_person=False, phrase=phrase,
                        keys=[key], store="")


def test_a_pipe_calling_two_servers_draws_each_call_from_the_caller():
    """The API's answer comes back into the pipe before the pipe calls the Biller. Taken for a new
    call, it drew API -> Biller with the answer's sentence, and lost the page's own call."""
    model = gv._arch_model(make_graph(make_two_server_pipe_map()), "", "all")
    assert model is not None
    ln = lines_of(model)
    assert ("C3", "C6") not in ln and ("S2", "C6") not in ln
    assert ln[("C1", "C6")]["sentences"] == [("UC1", "charge for the thing")]
    assert [s for _, s in next(v for k, v in ln.items() if k[0] == "C1" and k[1] != "C6")["sentences"]] \
        == ["send the thing"]


def test_a_step_a_pipe_drops_hands_its_map_steps_to_the_line_before_it():
    """An answer into a pipe, and a call into a pipe no step leaves, are not drawn. A rule decided on
    either one must still mark the line the story took to get there."""
    graph = make_graph(make_kinded_map(C2="pipe"))
    kept = gv._draw_through(graph, [make_step("I1", "C1", "k1"), make_step("C1", "C2", "k2")])
    assert [(s["src"], s["dst"]) for s in kept] == [("I1", "C1")]
    assert kept[0]["keys"] == ["k1", "k2"]
    kept = gv._draw_through(graph, [make_step("C1", "C2", "k1"), make_step("C2", "C3", "k2"),
                                    make_step("C3", "C2", "k3"), make_step("C2", "C1", "k4")])
    assert [(s["src"], s["dst"]) for s in kept] == [("C1", "C3")]
    assert kept[0]["keys"] == ["k1", "k2", "k3", "k4"]


def test_a_store_stands_alone_inside_its_subsystem():
    model = gv._arch_model(make_graph(make_kinded_map(C5="store")), "", "all")
    assert model is not None
    assert "C5" in model["inside"] and "S2" not in model["inside"]
    assert ("C5", "D1") in lines_of(model)
    assert ("SF1", "C5") in lines_of(model)   # the save after the check, hidden inside S2 before


# --- the layered picture: parts in frames by their kind ------------------------------------

def make_layered_map() -> dict[str, Any]:
    """The map with every component's kind stated: the page is a screen, the client a pipe, the API
    an api, the checker a check, the saver a store."""
    return make_kinded_map(C1="screen", C2="pipe", C3="api", C4="check", C5="store")


def test_a_map_without_kinds_keeps_the_picture_over_subsystems():
    assert not gv.arch_layered(make_graph())
    assert gv.arch_layered(make_graph(make_layered_map()))


def frames_of(drawing: str, ids: tuple[str, ...]) -> dict[str, str]:
    """Which frame each of `ids` is drawn in, read back from a drawing."""
    frame_of: dict[str, str] = {}
    current = ""
    for line in drawing.splitlines():
        head = line.strip()
        if head.startswith("subgraph "):
            current = head.split('["')[1].rstrip('"]')
        elif head == "end":
            current = ""
        elif current and head.split("[")[0] in ids:
            frame_of[head.split("[")[0]] = current
    return frame_of


def test_the_layered_picture_frames_each_part_by_its_kind():
    graph = make_graph(make_layered_map())
    drawings, _texts = gv.gen_arch_views(graph)
    drawing = drawings["all|CAP1"]
    for label in ("Screens and commands", "APIs", "Work", "Storage", "Outside services"):
        assert f'["{label}"]' in drawing, label
    # on a feature's picture the door is in no frame: it sits between the people and the first
    # frame, tied above it
    assert frames_of(drawing, ("I1", "C1", "C3", "C4", "C5", "D1")) == {
        "C1": "Screens and commands", "C3": "APIs", "C4": "Work", "C5": "Storage", "D1": "Outside services"}
    assert "  I1 ~~~ C1" in drawing and "  I2 ~~~ C1" in drawing


def test_a_crowded_picture_draws_one_line_per_pair_of_layers():
    graph = make_graph(make_layered_map())
    drawings, texts = gv.gen_arch_views(graph, crowded=0)
    drawing, text = drawings["all|"], texts["all|"]
    who = gv._person_id("Admin")
    assert frames_of(drawing, (who, "I1")) == {who: "People", "I1": "Interfaces"}
    layer = {(x["src"], x["dst"]): x["lines"] for x in text["layerLines"]}
    assert layer[("People", "Interfaces")] == [[who, "I1"], [gv._person_id("Member"), "I2"]]
    assert layer[("APIs", "Work")] == [["C3", "C4"]]
    # no box's own line is drawn, and nothing ties one box to another: each frame is then laid out on
    # its own, as one row of its boxes
    links = [ln.strip() for ln in drawing.splitlines() if "-->" in ln or "-.->" in ln]
    assert len(links) == len(text["layerLines"]) and links[0] == 'CYFP -->|"2"| CYFD'
    assert all(ln.startswith("CYF") for ln in links)
    ties = [ln.strip() for ln in drawing.splitlines() if "~~~" in ln]
    assert ties and all(a.startswith("CYF") and b.startswith("CYF") for a, _tie, b in (t.split() for t in ties))
    assert "direction TB" in drawing and "direction LR" not in drawing
    # the text still tells every box line, for the view to draw on demand
    assert len(text["lines"]) == 8


def test_a_picture_that_is_not_crowded_keeps_its_box_lines():
    drawings, texts = gv.gen_arch_views(make_graph(make_layered_map()))
    assert len(texts["all|"]["lines"]) <= gv.ARCH_CROWDED_LINES
    assert all("layerLines" not in t for t in texts.values())
    assert all("CYFP" not in d for d in drawings.values())


def test_the_layered_picture_draws_parts_and_doors_goes_through_pipes_and_writes_out_sub_flows():
    graph = make_graph(make_layered_map())
    model = gv._arch_model(graph, "", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None
    ln = lines_of(model)
    assert model["doors"] == ["I1", "I2"] and "SF1" not in model["inside"] and "C2" not in model["inside"]
    assert ("Admin", "I1") in ln and ("I1", "C1") in ln   # the person comes in through the door
    assert ("C1", "C3") in ln and ("C3", "C4") in ln and ("C4", "C5") in ln
    assert ("Member", "I2") in ln and ("I2", "C3") in ln


def test_the_layered_picture_keeps_the_outside_services_in_the_last_frame():
    doc = make_layered_map()
    doc["interfaces"].append({"id": "I3", "name": "Mailer", "what": "sends receipts", "side": "theirs",
                              "facing": "user", "kind": "api"})
    next(f for f in doc["flows"] if f["uc"] == "UC1")["steps"].append(
        {"n": 11, "src": "C5", "dst": "I3", "phrase": "send a receipt", "where": "src/save.py:9",
         "direction": "out"})
    graph = make_graph(doc)
    model = gv._arch_model(graph, "", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None and model["outside"] == ["I3"]
    outside = gv.gen_arch_views(graph)[0]["all|"].split('["Outside services"]')[1].split("\n  end")[0]
    assert "  I3[" in outside


def make_grouped_map() -> dict[str, Any]:
    """The layered map with the API doing the work: the API and the Checker are then two parts of the
    Server in one layer, and the Saver the Server's only part in the storage layer."""
    return make_kinded_map(C1="screen", C2="pipe", C3="logic", C4="check", C5="store")


def test_the_parts_of_one_subsystem_in_one_layer_are_one_box():
    model = gv._arch_model(make_graph(make_grouped_map()), "", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None
    group = gv._arch_cell_id(2, "S2")
    assert model["cells"] == {group: {"sub": "S2", "frame": 2, "parts": ["C3", "C4"]}}
    assert model["inside"] == ["C1", group, "C5"]
    ln = lines_of(model)
    # the check runs inside the group, so no line is drawn for it
    assert set(ln) == {("Admin", "I1"), ("I1", "C1"), ("C1", group), (group, "C5"), ("C5", "D1"),
                       ("Member", "I2"), ("I2", group)}


def test_a_group_lists_first_the_parts_most_stories_pass_through():
    """The Checker is met first, but two stories pass through the API and one through the Checker:
    the box names the API first, and past a few names it names only the busiest."""
    graph = make_graph(make_grouped_map())
    flow = gv._ArchFlow(walks=[("UC1", [("C4", "C5")]), ("UC2", [("C3", "C5")]), ("UC3", [("C3", "C5")])],
                        phrases={uc: ["x"] for uc in ("UC1", "UC2", "UC3")},
                        keys={uc: [[]] for uc in ("UC1", "UC2", "UC3")},
                        people=[], doors=[], stores=[], ends={})
    lifted = gv._arch_lift(graph, flow, layered=True)
    assert lifted["cells"][gv._arch_cell_id(2, "S2")]["parts"] == ["C3", "C4"]


def test_a_group_of_parts_is_drawn_as_its_subsystem_and_named_with_its_layer():
    graph = make_graph(make_grouped_map())
    drawings, texts = gv.gen_arch_views(graph)
    group = gv._arch_cell_id(2, "S2")
    drawing = drawings["all|"]
    assert (f'{group}["<span class=cyslot data-k=cell data-v=map data-id=S2 data-parts=C3%2CC4></span>"]'
            f":::cy-{group}") in drawing
    work = drawing.split('["Work"]')[1].split("\n  end")[0]
    assert f"  {group}[" in work
    assert texts["all|"]["cells"] == {group: {"sub": "S2", "parts": ["C3", "C4"]}}
    line = next(e for e in texts["all|"]["lines"] if e["srcBox"] == "C1")
    assert line["dstBox"] == group and line["dst"] == "Server (Work)"


def make_map_with_a_line_up() -> dict[str, Any]:
    """The layered map with the Saver kinded a screen: the Checker, in the work layer, then calls up
    into the top layer."""
    return make_kinded_map(C1="screen", C2="pipe", C3="api", C4="check", C5="screen")


def test_a_line_up_the_layers_is_drawn_from_the_upper_box_and_told_the_way_it_runs():
    graph = make_graph(make_map_with_a_line_up())
    model = gv._arch_model(graph, "", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None
    assert [(ln["src"], ln["dst"]) for ln in model["lines"] if ln["up"]] == [("C4", "C5")]
    drawings, texts = gv.gen_arch_views(graph)
    drawing = drawings["all|"]
    assert '  C5 <-->|"5"| C4' in drawing and "C4 -->" not in drawing
    up = [(e["srcBox"], e["dstBox"]) for e in texts["all|"]["lines"] if e.get("up")]
    assert up == [("C4", "C5")]


def test_the_picture_over_subsystems_draws_no_line_flipped():
    model = make_model()
    assert not any(ln["up"] for ln in model["lines"])


def test_the_picture_over_subsystems_has_no_groups_of_parts():
    _drawings, texts = gv.gen_arch_views(make_graph())
    assert texts["all|"]["cells"] == {}
    assert "data-k=cell" not in _drawings["all|"]


def test_the_layered_picture_keeps_the_story_numbers_and_the_text():
    graph = make_graph(make_layered_map())
    _drawings, texts = gv.gen_arch_views(graph)
    story = next(x for x in texts["all|"]["stories"] if x["uc"] == "UC1")
    assert story["lines"][:2] == [[gv._person_id("Admin"), "I1"], ["I1", "C1"]]
    assert all(e["n"] >= 1 for e in texts["all|"]["lines"] if not e["store"])


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
