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
    assert line["store"] and line["number"] == 0


def test_every_story_reads_forward_and_answers_are_not_drawn():
    model = make_model()
    numbers = {(ln["src"], ln["dst"]): ln["number"] for ln in model["lines"] if not ln["store"]}
    assert [numbers[p] for p in model["stories"]["UC1"] if p in numbers] == [1, 2, 3, 4]
    assert [numbers[p] for p in model["stories"]["UC2"]] == [1, 2]
    # "return the saved thing" goes back to the box that called: an answer, left out
    assert ("S2", "S1") not in lines_of(model)


def test_a_story_ends_at_the_door_that_hands_its_result_back():
    assert make_model()["ends"] == {"UC1": "I1", "UC2": "I2"}


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
    assert ("S1", "S3") in ln and ("S3", "S2") in ln


def test_a_pipe_is_drawn_through():
    model = gv._arch_model(make_graph(make_kinded_map(C2="pipe")), "", "all")
    assert model is not None
    ln = lines_of(model)
    assert ("S1", "S2") in ln
    assert "S3" not in model["inside"] and not any("S3" in pair or "C2" in pair for pair in ln)
    assert ln[("S1", "S2")]["sentences"] == [("UC1", "send the thing")]
    # the line is both steps, into the pipe and out of it, and carries both numbers for the use case map
    assert ln[("S1", "S2")]["steps"] == {"UC1": [3, 4]}, ln[("S1", "S2")]["steps"]


def test_a_line_inside_a_shared_sub_use_case_carries_the_step_that_runs_it():
    """The layered picture writes a shared sub-use case's steps out; each of them belongs, on the use
    case map, to the step that runs it, so that is the number its line carries."""
    graph = make_graph(make_layered_map())
    texts = gv.gen_arch_views(graph)[1]
    inner = [e for e in texts["all|"]["lines"] if "UC1" in e["steps"]
             and any(x["text"] == "check the ask" for x in e["sentences"])]
    assert inner and all(5 in e["steps"]["UC1"] for e in inner), [e["steps"] for e in inner]


def make_map_with_a_deploy() -> dict[str, Any]:
    """The layered map plus an operator who deploys from the command line: the container stack, the
    product's wiring, seeds the thing's record when it is missing. The stack is the only code between
    the command line and the database."""
    doc = make_layered_map()
    doc["roles"].append({"id": "R3", "name": "Operator", "kind": "human", "audience": "internal",
                         "wants": "z", "drives": "UC3"})
    doc["use_cases"].append({"id": "UC3", "name": "Deploy", "actors": ["R3"], "capability": "CAP1",
                             "trigger": "A change is ready.", "outcome": "The change is live."})
    doc["interfaces"].append({"id": "I3", "name": "Command line", "what": "the command line", "side": "ours",
                              "facing": "operator", "kind": "cli"})
    doc["components"].append({"id": "C6", "name": "Container stack", "subsystem": "S3", "kind": "wiring",
                              "purpose": "starts the product", "files": ["deploy/compose.yml"]})
    doc["flows"].append({"uc": "UC3", "title": "Deploy", "steps": [
        {"n": 1, "src": "R3", "dst": "I3", "phrase": "run the deploy"},
        {"n": 2, "src": "I3", "dst": "C6", "phrase": "start the containers", "where": "deploy/compose.yml:1"},
        {"n": 3, "src": "C6", "dst": "E1", "phrase": "seed the thing when it is missing", "where": "deploy/compose.yml:9"},
        {"n": 4, "src": "C6", "dst": "I3", "phrase": "report the containers up", "where": "deploy/compose.yml:12"}]})
    return doc


def test_a_part_skipped_between_an_interface_and_a_database_is_drawn():
    """Nothing crosses from one edge of the product to another without code: the container stack is the
    only part between the command line and the database, so it is drawn, in the first layer, which then
    names it. A pipe between two parts is still skipped."""
    graph = make_graph(make_map_with_a_deploy())
    model = gv._arch_model(graph, "", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None
    ln = lines_of(model)
    stack, page, api = gv._arch_cell_id(0, "S3"), gv._arch_cell_id(0, "S1"), gv._arch_cell_id(1, "S2")
    assert ("I3", stack) in ln and (stack, "D1") in ln
    assert ("I3", "D1") not in ln
    # the pipe shares the stack's subsystem: its box holds the stack only, and the page calls the API
    assert model["cells"][stack]["parts"] == ["C6"], "the pipe between the page and the API is still skipped"
    assert (page, api) in ln and (page, stack) not in ln and (stack, api) not in ln
    drawing = gv.gen_arch_views(graph)[0]["all|"]
    # the layer holds a screen too, so its name says only that: the stack is a tag in its box
    assert frames_of(drawing, (stack, page)) == {stack: "UI", page: "UI"}


def test_the_first_layer_names_pipes_and_wiring_only_when_it_holds_nothing_else():
    """A pipe or the wiring drawn as a box sits in the first layer, but the layer is named for it only when
    it holds nothing else: beside a screen it is one tag in a subsystem box, and the layer read "UI,
    scripts, pipes and wiring", a list of whatever happened to be there. The deploy, a feature of its
    own here, reaches no screen: its first layer holds the container stack alone, and says so."""
    doc = make_map_with_a_deploy()
    doc["capabilities"].append({"id": "CAP9", "name": "Deploying", "purpose": "ship it", "happy_path": "expected"})
    next(u for u in doc["use_cases"] if u["id"] == "UC3")["capability"] = "CAP9"
    graph = make_graph(doc)
    drawing = gv.gen_arch_views(graph)[0]["all|CAP9"]
    stack = gv._arch_cell_id(0, "S3")
    assert frames_of(drawing, (stack,)) == {stack: "Wiring"}


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


def make_step(src: str, dst: str, key: str = "", phrase: str = "do it") -> gv._ArchStep:
    return gv._ArchStep(src=src, dst=dst, from_person=False, to_person=False, phrase=phrase, store="", ns=[])


def test_a_pipe_calling_two_servers_draws_each_call_from_the_caller():
    """The API's answer comes back into the pipe before the pipe calls the Biller. Taken for a new
    call, it drew API -> Biller with the answer's sentence, and lost the page's own call."""
    model = gv._arch_model(make_graph(make_two_server_pipe_map()), "", "all")
    assert model is not None
    ln = lines_of(model)
    assert ("S2", "S4") not in ln
    assert ln[("S1", "S4")]["sentences"] == [("UC1", "charge for the thing")]
    assert [s for _, s in next(v for k, v in ln.items() if k[0] == "S1" and k[1] != "S4")["sentences"]] \
        == ["send the thing"]


def test_a_store_stands_alone_inside_its_subsystem():
    """The Saver is a store: it is drawn as its own box, beside the Server's box, which still holds the
    API, the one other part of the Server the stories use. Even one part is drawn inside its subsystem."""
    model = gv._arch_model(make_graph(make_kinded_map(C5="store")), "", "all")
    assert model is not None
    assert model["inside"] == ["S1", "S3", "S2", "SF1", "C5"]
    ln = lines_of(model)
    assert ("S2", "SF1") in ln and ("C5", "D1") in ln and ("S2", "D1") not in ln
    assert ("SF1", "C5") in ln   # the save after the check, hidden inside S2 before


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
    # every layer keeps its fixed name: the Checker alone is in Logic; the last frame holds the
    # database alone, and says so. The detailed drawing keeps every layer, the people and doors too.
    page, api, checker, saver = (gv._arch_cell_id(f, s) for f, s in ((0, "S1"), (1, "S2"), (2, "S2"), (3, "S2")))
    drawing = drawings["all|CAP1"]
    for label in ("Actors", "Interfaces", "UI", "APIs", "Logic", "Storage", "Databases"):
        assert f'["{label}"]' in drawing, label
    assert frames_of(drawing, ("I1", page, api, checker, saver, "D1")) == {
        "I1": "Interfaces", page: "UI", api: "APIs", checker: "Logic", saver: "Storage", "D1": "Databases"}


def make_map_with_a_timer() -> dict[str, Any]:
    """The layered map plus the product's own nightly clock, which sweeps old things away."""
    doc = make_layered_map()
    doc["roles"].append({"id": "R3", "name": "Nightly clock", "kind": "service", "audience": "internal",
                         "wants": "old things gone", "drives": "UC3"})
    doc["use_cases"].append({"id": "UC3", "name": "Sweep old things", "actors": ["R3"], "capability": "CAP1",
                             "trigger": "Every night.", "outcome": "Old things are gone."})
    doc["flows"].append({"uc": "UC3", "title": "Sweep old things", "steps": [
        {"n": 1, "src": "R3", "dst": "C4", "phrase": "start the sweep"},
        {"n": 2, "src": "C4", "dst": "C5", "phrase": "delete the old things", "where": "src/check.py:20"}]})
    return doc


def test_the_products_own_timer_sits_in_the_work_layer_not_with_the_people():
    graph = make_graph(make_map_with_a_timer())
    model = gv._arch_model(graph, "", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None and model["timers"] == ["Nightly clock"]
    clock = gv._person_id("Nightly clock")
    drawings, _texts = gv.gen_arch_views(graph, crowded=0)
    assert frames_of(drawings["all|"], (clock, gv._person_id("Admin"))) == {
        clock: "Logic", gv._person_id("Admin"): "Actors"}
    # a person is still drawn with the people, on a picture with no people frame too
    assert gv._arch_layer(graph, model, "Admin") == -2
    assert gv._arch_layer(graph, model, "Nightly clock") == gv.ARCH_WORK_LAYER


def make_map_with_a_request_filter(kind: str) -> dict[str, Any]:
    """The layered map where the Checker is a part of `kind` that also runs on every request before
    the API answers it, as a request filter does."""
    doc = make_kinded_map(C1="screen", C2="pipe", C3="api", C4=kind, C5="store")
    doc["entry_points"] = [{"kind": "middleware", "trigger": "Every request arrives.", "component": "C4",
                            "source": "src/check.py:1"}]
    return doc


def test_a_part_that_runs_before_the_apis_is_drawn_with_them():
    """A part doing work whose way in filters requests sits with the APIs, not below them; the wiring
    keeps its place."""
    for kind in ("check", "logic"):
        drawings, texts = gv.gen_arch_views(make_graph(make_map_with_a_request_filter(kind)))
        drawing = drawings["all|"]
        # it joins the API of its own subsystem, in one group box in the APIs layer
        assert texts["all|"]["cells"] == {"CYG0S1": {"sub": "S1", "parts": ["C1"]},
                                          "CYG1S2": {"sub": "S2", "parts": ["C3", "C4"]},
                                          "CYG3S2": {"sub": "S2", "parts": ["C5"]}}, kind
        assert frames_of(drawing, ("CYG1S2",)) == {"CYG1S2": "APIs"}, kind
        # the work layer held the Checker alone: it is not drawn at all now
        assert '["Checks"]' not in drawing and '["Logic"]' not in drawing, kind
    graph = make_graph(make_map_with_a_request_filter("wiring"))
    assert gv._arch_frame(graph, "C4") != gv.ARCH_API_LAYER


def rows_of(drawing: str) -> dict[str, list[str]]:
    """Each frame of a drawing, by its title, with the boxes it writes, in the order it writes them."""
    rows: dict[str, list[str]] = {}
    current = ""
    for line in drawing.splitlines():
        head = line.strip()
        if head.startswith("subgraph "):
            current = head.split('["')[1].rstrip('"]')
            rows[current] = []
        elif head == "end":
            current = ""
        elif current and ":::cy-" in head:
            rows[current].append(head.split("[")[0])
    return rows


def test_the_stories_come_in_the_order_a_reader_knows_and_every_row_follows_them():
    """The happy path's stories first, then the others feature by feature in the Features page's order,
    whatever order the map file keeps them in. Each row is written in the order the stories reach its
    boxes, so it reads left to right."""
    doc = make_map_with_a_third_door()
    doc["capabilities"].insert(0, {"id": "CAP2", "name": "Counting", "purpose": "counts",
                                   "happy_path": "expected"})
    doc["use_cases"][-1]["capability"] = "CAP2"   # the operator's count, last in the file
    graph = make_graph(doc)
    assert gv._arch_walks(graph) == ["UC1", "UC3", "UC2"]
    rows = rows_of(gv.gen_arch_views(graph, crowded=0)[0]["all|"])
    assert rows["Actors"] == [gv._person_id(p) for p in ("Admin", "Operator", "Member")]
    assert rows["Interfaces"] == ["I1", "I3", "I2"]


def test_the_products_own_timer_takes_its_place_in_its_row_by_when_it_is_reached():
    """The nightly clock starts the last story, so it sits after the Checker, which the first story
    reaches."""
    rows = rows_of(gv.gen_arch_views(make_graph(make_map_with_a_timer()), crowded=0)[0]["all|"])
    assert rows["Logic"] == [gv._arch_cell_id(2, "S2"), gv._person_id("Nightly clock")]


def test_a_layer_keeps_its_name_whatever_kinds_it_holds():
    """The page is a screen and the client a script: the first frame holds both and is still "UI". It
    named the kinds it held for a while ("UI and scripts"), which showed mcpolis's 4 layers under 6
    names."""
    graph = make_graph(make_kinded_map(C1="screen", C2="script", C3="api", C4="check", C5="store"))
    drawing = gv.gen_arch_views(graph)[0]["all|"]
    assert '["UI"]' in drawing and '["UI and scripts"]' not in drawing
    page, client = gv._arch_cell_id(0, "S1"), gv._arch_cell_id(0, "S3")
    assert frames_of(drawing, (page, client)) == {page: "UI", client: "UI"}


def test_a_crowded_picture_draws_one_line_per_pair_of_layers():
    graph = make_graph(make_layered_map())
    drawings, texts = gv.gen_arch_views(graph, crowded=0)
    drawing, text = drawings["all|"], texts["all|"]
    who = gv._person_id("Admin")
    assert frames_of(drawing, (who, "I1")) == {who: "Actors", "I1": "Interfaces"}
    layer = {(x["src"], x["dst"]): x["lines"] for x in text["layerLines"]}
    assert layer[("Actors", "Interfaces")] == [[who, "I1"], [gv._person_id("Member"), "I2"]]
    assert layer[("APIs", "Logic")] == [[gv._arch_cell_id(1, "S2"), gv._arch_cell_id(2, "S2")]]
    # no box's own line is drawn: each frame is then laid out on its own, as one row of its boxes
    links = [ln.strip() for ln in drawing.splitlines() if "-->" in ln or "-.->" in ln]
    assert len(links) == len(text["layerLines"]) and links[0] == "CYFP --> CYFD"
    assert all(ln.startswith("CYF") for ln in links)
    # the frames are tied one below the other, and inside a frame each box to the next, in the order
    # the frame writes them: a row, left to right
    ties = [tuple(t.split()[::2]) for t in (ln.strip() for ln in drawing.splitlines() if "~~~" in ln)]
    frame_ties = [t for t in ties if t[0].startswith("CYF")]
    assert frame_ties[:2] == [("CYFP", "CYFD"), ("CYFD", "CYF0")]
    rows = rows_of(drawing)
    row_ties = [t for t in ties if not t[0].startswith("CYF")]
    assert row_ties == [pair for row in rows.values() for pair in zip(row, row[1:])]
    assert (who, gv._person_id("Member")) in row_ties
    assert "direction LR" in drawing and "direction TB" not in drawing
    # the text still tells every box line, for the view to draw on demand
    assert len(text["lines"]) == 8


def make_map_with_a_third_door() -> dict[str, Any]:
    """The layered map plus an operator who counts the things through a command line, straight into
    the API. Of the 3 doors, only the web page leads to a screen."""
    doc = make_layered_map()
    doc["roles"].append({"id": "R3", "name": "Operator", "kind": "human", "audience": "internal",
                         "wants": "z", "drives": "UC3"})
    doc["use_cases"].append({"id": "UC3", "name": "Count the things", "actors": ["R3"], "capability": "CAP1",
                             "trigger": "The operator asks for a count.", "outcome": "The operator has the count."})
    doc["interfaces"].append({"id": "I3", "name": "Command line", "what": "the command line", "side": "ours",
                              "facing": "operator", "kind": "cli"})
    doc["flows"].append({"uc": "UC3", "title": "Count the things", "steps": [
        {"n": 1, "src": "R3", "dst": "I3", "phrase": "run the count"},
        {"n": 2, "src": "I3", "dst": "C3", "phrase": "carry the count in", "where": "src/api.py:50"},
        {"n": 3, "src": "C3", "dst": "I3", "phrase": "print the count", "where": "src/api.py:52"},
        {"n": 4, "src": "I3", "dst": "R3", "phrase": "show the count"}]})
    return doc


def test_a_layer_line_few_boxes_of_its_layer_take_is_not_drawn():
    """A line between two layers is drawn only when more than a third of the boxes of the layer it
    leaves have a line to the other layer, and with no number. Under that, its lines are exceptions:
    the drawing leaves them out, and the text still tells them, for a click on a box to draw."""
    graph = make_graph(make_map_with_a_third_door())
    drawings, texts = gv.gen_arch_views(graph, crowded=0)
    drawing, text = drawings["all|"], texts["all|"]
    layer = {(x["src"], x["dst"]): x["lines"] for x in text["layerLines"]}
    # 2 of the 3 doors lead to the API: a rule of the picture
    api = gv._arch_cell_id(1, "S2")
    assert layer[("Interfaces", "APIs")] == [["I2", api], ["I3", api]]
    assert "  CYFD --> CYF1" in drawing
    # 1 of the 3 leads to a screen: an exception, not drawn, and still told in the text
    assert ("Interfaces", "UI") not in layer and "CYFD --> CYF0" not in drawing
    assert "exceptions" not in text
    assert any(e["srcBox"] == "I1" and e["dstBox"] == gv._arch_cell_id(0, "S1") for e in text["lines"])
    # every person comes in through a door: 3 of 3
    assert len(layer[("Actors", "Interfaces")]) == 3
    links = [ln for ln in drawing.splitlines() if "-->" in ln]
    assert len(links) == len(text["layerLines"])


def test_every_layered_picture_opens_on_its_layer_lines_whatever_its_size():
    """The look no longer depends on a size the reader cannot see. Every box's own line is still in the
    picture's text, for the view's "Lines: All" choice to draw on top of the same layout."""
    drawings, texts = gv.gen_arch_views(make_graph(make_layered_map()))
    assert texts and all("layerLines" in t and t["lines"] for t in texts.values())
    assert all("CYFP --> CYFD" in d for d in drawings.values())
    # a map without kinds has no layers to draw lines between
    assert not [t for t in gv.gen_arch_views(make_graph())[1].values() if "layerLines" in t]


def test_the_layered_picture_draws_parts_and_doors_goes_through_pipes_and_writes_out_sub_flows():
    graph = make_graph(make_layered_map())
    model = gv._arch_model(graph, "", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None
    ln = lines_of(model)
    page, api, checker, saver = (gv._arch_cell_id(f, s) for f, s in ((0, "S1"), (1, "S2"), (2, "S2"), (3, "S2")))
    # each part is drawn in its subsystem's box of its layer, and the pipe in none
    assert {c: x["parts"] for c, x in model["cells"].items()} == {
        page: ["C1"], api: ["C3"], checker: ["C4"], saver: ["C5"]}
    assert model["doors"] == ["I1", "I2"] and "SF1" not in model["inside"] and "C2" not in model["inside"]
    assert ("Admin", "I1") in ln and ("I1", page) in ln   # the person comes in through the door
    assert (page, api) in ln and (api, checker) in ln and (checker, saver) in ln
    assert ("Member", "I2") in ln and ("I2", api) in ln


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
    # an outside service and the database the records live in: the frame names both, and the
    # product's own database is never called an outside service
    drawing = gv.gen_arch_views(graph)[0]["all|"]
    assert '["Outside services"]' not in drawing
    outside = drawing.split('["Outside services and databases"]')[1].split("\n  end")[0]
    assert "  I3[" in outside and "  D1[" in outside


def make_grouped_map() -> dict[str, Any]:
    """The layered map with the API doing the work: the API and the Checker are then two parts of the
    Server in one layer, and the Saver the Server's only part in the storage layer."""
    return make_kinded_map(C1="screen", C2="pipe", C3="logic", C4="check", C5="store")


def test_the_parts_of_one_subsystem_in_one_layer_are_one_box():
    model = gv._arch_model(make_graph(make_grouped_map()), "", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None
    group = gv._arch_cell_id(2, "S2")
    page, saver = gv._arch_cell_id(0, "S1"), gv._arch_cell_id(3, "S2")
    assert model["cells"] == {page: {"sub": "S1", "frame": 0, "parts": ["C1"]},
                              group: {"sub": "S2", "frame": 2, "parts": ["C3", "C4"]},
                              saver: {"sub": "S2", "frame": 3, "parts": ["C5"]}}
    assert model["inside"] == [page, group, saver]
    ln = lines_of(model)
    # the check runs inside the group, so no line is drawn for it
    assert set(ln) == {("Admin", "I1"), ("I1", page), (page, group), (group, saver), (saver, "D1"),
                       ("Member", "I2"), ("I2", group)}


def test_a_group_lists_first_the_parts_most_stories_pass_through():
    """The Checker is met first, but two stories pass through the API and one through the Checker:
    the box names the API first, and past a few names it names only the busiest."""
    graph = make_graph(make_grouped_map())
    flow = gv._ArchFlow(walks=[("UC1", [("C4", "C5")]), ("UC2", [("C3", "C5")]), ("UC3", [("C3", "C5")])],
                        phrases={uc: ["x"] for uc in ("UC1", "UC2", "UC3")},
                        nums={uc: [1] for uc in ("UC1", "UC2", "UC3")},
                        people=[], doors=[], stores=[], ends={})
    lifted = gv._arch_lift(graph, flow, layered=True)
    assert lifted["cells"][gv._arch_cell_id(2, "S2")]["parts"] == ["C3", "C4"]


def test_a_line_names_the_use_cases_own_steps_it_draws():
    """Each line says, for each use case taking it, which of that use case's own steps it draws: the
    step that starts it, and for a line through boxes not drawn, the steps it passes. A use case map
    selects them."""
    graph = make_graph()
    model = gv._arch_model(graph, "", "all", budget=1)
    assert model is not None
    text = {(e["srcBox"], e["dstBox"]): e for e in gv._arch_text(graph, model)}
    flows = {f["uc"]: f for f in graph["flows"]}
    for (a, b), e in text.items():
        for uc, ns in e["steps"].items():
            own = {int(st["n"]) for st in flows[uc]["steps"]}
            assert ns and set(ns) <= own, (a, b, uc, ns)
    folded = text[("I1", "S2")]   # passes the Screens box, which has no room
    assert any(len(ns) > 1 for ns in folded["steps"].values()), folded["steps"]


def test_a_group_of_parts_is_drawn_as_its_subsystem_and_named_with_its_layer():
    graph = make_graph(make_grouped_map())
    drawings, texts = gv.gen_arch_views(graph)
    group = gv._arch_cell_id(2, "S2")
    drawing = drawings["all|"]
    assert (f'{group}["<span class=cyslot data-k=cell data-v=map data-id=S2 data-parts=C3%2CC4></span>"]'
            f":::cy-{group}") in drawing
    work = drawing.split('["Logic"]')[1].split("\n  end")[0]
    assert f"  {group}[" in work
    assert texts["all|"]["cells"] == {gv._arch_cell_id(0, "S1"): {"sub": "S1", "parts": ["C1"]},
                                      group: {"sub": "S2", "parts": ["C3", "C4"]},
                                      gv._arch_cell_id(3, "S2"): {"sub": "S2", "parts": ["C5"]}}
    line = next(e for e in texts["all|"]["lines"] if e["srcBox"] == gv._arch_cell_id(0, "S1"))
    assert line["dstBox"] == group and line["dst"] == "Server (Logic)"


def make_map_with_a_line_up() -> dict[str, Any]:
    """The layered map with the Checker kinded a store and the Saver a screen: the store then calls up
    into the top layer, and neither kind ever moves, so the line stays a line up the layers."""
    return make_kinded_map(C1="screen", C2="pipe", C3="api", C4="store", C5="screen")


def test_a_line_up_the_layers_is_drawn_from_the_upper_box_and_told_the_way_it_runs():
    graph = make_graph(make_map_with_a_line_up())
    model = gv._arch_model(graph, "", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None
    checker, saver = gv._arch_cell_id(3, "S2"), gv._arch_cell_id(0, "S2")
    assert [(ln["src"], ln["dst"]) for ln in model["lines"] if ln["up"]] == [(checker, saver)]
    _drawings, texts = gv.gen_arch_views(graph)
    drawing = gv._arch_mermaid(graph, model, layered=True)
    assert f'  {saver} <--> {checker}' in drawing and f"{checker} -->" not in drawing
    up = [(e["srcBox"], e["dstBox"]) for e in texts["all|"]["lines"] if e.get("up")]
    assert up == [(checker, saver)]




def test_the_picture_over_subsystems_draws_no_line_flipped():
    model = make_model()
    assert not any(ln["up"] for ln in model["lines"])


def test_the_picture_over_subsystems_has_no_groups_of_parts():
    _drawings, texts = gv.gen_arch_views(make_graph())
    assert texts["all|"]["cells"] == {}
    assert "data-k=cell" not in _drawings["all|"]


# --- the layers read top to bottom: what the call graph corrects --------------------------

def make_story(uc: str, name: str, steps: list[tuple[str, str, str]], feature: str = "CAP1") -> dict[str, Any]:
    """One more use case for the Admin, its walk given as (from, to, sentence), numbered in order."""
    return {"use_case": {"id": uc, "name": name, "actors": ["R1"], "capability": feature,
                         "trigger": "The admin asks.", "outcome": "It is done."},
            "flow": {"uc": uc, "title": name, "steps": [
                {"n": i, "src": s, "dst": d, "phrase": p, **({"where": "src/x.py:1"} if s.startswith("C") else {})}
                for i, (s, d, p) in enumerate(steps, 1)]}}


def add_story(doc: dict[str, Any], story: dict[str, Any]) -> dict[str, Any]:
    doc["use_cases"].append(story["use_case"])
    doc["flows"].append(story["flow"])
    return doc


def make_map_with_a_scoper() -> dict[str, Any]:
    """The layered map plus a Scoper, a check that only the Saver calls: it scopes and encrypts each
    row on its way to the database, as mcpolis's cloud-records part does."""
    doc = make_layered_map()
    doc["components"].append({"id": "C6", "name": "Scoper", "subsystem": "S2", "kind": "check",
                              "purpose": "scopes each row", "files": ["src/scope.py"]})
    return add_story(doc, make_story("UC3", "Clean things", [
        ("R1", "I1", "ask to clean"), ("I1", "C1", "carry the ask in"), ("C1", "C2", "send the ask"),
        ("C2", "C3", "post the ask"), ("C3", "C5", "save the cleaned thing"),
        ("C5", "C6", "scope and encrypt the row"), ("C6", "E1", "write the row")]))


def test_a_check_only_stores_call_is_drawn_in_storage_and_says_why():
    graph = make_graph(make_map_with_a_scoper())
    place = gv._arch_place(graph)
    assert (place["start"]["C6"], place["final"]["C6"]) == (gv.ARCH_WORK_LAYER, 3)
    text = gv.gen_arch_views(graph)[1]["all|"]
    assert text["cells"][gv._arch_cell_id(3, "S2")]["parts"] == ["C5", "C6"]
    assert text["moved"] == {"C6": "Scoper sits in Storage because Saver calls it."}
    assert not [e for e in text["lines"] if e.get("up")]


def make_map_with_a_pushed_event() -> dict[str, Any]:
    """The layered map plus a live list: the page listens through the client, a pipe, and the Saver later
    publishes a new thing through the same pipe, which hands it to the API that listens."""
    return add_story(make_layered_map(), make_story("UC3", "Watch new things", [
        ("R1", "I1", "open the live list"), ("I1", "C1", "carry the ask in"), ("C1", "C2", "listen for new things"),
        ("C2", "C3", "open the stream"), ("C5", "C2", "publish the new thing"),
        ("C2", "C3", "deliver the new thing to the listener")]))


def test_a_pushed_event_coming_back_up_a_pipe_is_not_drawn_as_a_call():
    """Joined to the publish, the delivery drew the Saver calling the API above it."""
    model = gv._arch_model(make_graph(make_map_with_a_pushed_event()), "", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None
    ln = lines_of(model)
    saver, api, page = gv._arch_cell_id(3, "S2"), gv._arch_cell_id(1, "S2"), gv._arch_cell_id(0, "S1")
    assert (saver, api) not in ln and (page, api) in ln
    assert not [pair for pair, line in ln.items() if line["up"]]


def make_map_run_in_two_places(client_runs_in: list[str]) -> dict[str, Any]:
    """The kinded map with the Client a piece of logic, run as `client_runs_in` says; the page runs in
    the browser, everything else on the server."""
    doc = make_kinded_map(C1="screen", C2="logic", C3="api", C4="check", C5="store")
    for c in doc["components"]:
        c["runs_in"] = client_runs_in if c["id"] == "C2" else ["web"] if c["id"] == "C1" else ["server"]
    return doc


def test_logic_that_runs_only_with_the_screens_sits_in_the_ui_layer():
    graph = make_graph(make_map_run_in_two_places(["web"]))
    assert gv._arch_frame(graph, "C2") == 0
    assert gv._arch_place(graph)["why"]["C2"] == "Client sits in UI because it runs with the screens, not with the APIs."
    # a place where both run decides nothing: the one-container setup most products also ship
    both = make_graph(make_map_run_in_two_places(["web", "server"]))
    assert gv._arch_frame(both, "C2") == gv.ARCH_WORK_LAYER


def make_map_with_an_outside_sign_in_page() -> dict[str, Any]:
    """The layered map plus a sign-in feature: the Checker sends the person to a provider's sign-in page,
    and the page sends them back to the API. No step draws the person at the page."""
    doc = make_layered_map()
    doc["interfaces"].append({"id": "I3", "name": "Sign-in page", "what": "the provider's sign-in page",
                              "side": "theirs", "facing": "user", "kind": "hosted-screen"})
    doc["capabilities"].append({"id": "CAP2", "name": "Signing in", "purpose": "signs in", "happy_path": "expected"})
    return add_story(doc, make_story("UC3", "Sign in", [
        ("R1", "I1", "ask to sign in"), ("I1", "C1", "carry the ask in"), ("C1", "C2", "send the ask"),
        ("C2", "C3", "start the sign-in"), ("C3", "C4", "check the ask"),
        ("C4", "I3", "send the person to the sign-in page"), ("I3", "C3", "send the person back with a code")],
        feature="CAP2"))


def test_an_outside_page_answering_the_story_that_called_it_is_an_answer():
    """The Checker's call to the sign-in page is drawn; the page sending the person back to the API is
    its answer, not a call up from the bottom frame through every layer."""
    graph = make_graph(make_map_with_an_outside_sign_in_page())
    checker, api = gv._arch_cell_id(2, "S2"), gv._arch_cell_id(1, "S2")
    model = gv._arch_model(graph, "CAP2", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None and "I3" in model["outside"]
    ln = lines_of(model)
    assert (checker, "I3") in ln and ("I3", api) not in ln
    assert not [pair for pair, line in ln.items() if line["up"]]


def make_map_with_an_unkinded_caller() -> dict[str, Any]:
    """The layered map with the page's kind unstated: a part with no kind starts below Storage."""
    doc = make_layered_map()
    del next(c for c in doc["components"] if c["id"] == "C1")["kind"]
    return doc


def test_a_part_the_call_graph_may_move_never_has_its_calls_up_a_pipe_dropped():
    """Judged by the layer it starts in, the page with no kind lost its call through the client to
    the API; the placement then moves it above the API."""
    graph = make_graph(make_map_with_an_unkinded_caller())
    model = gv._arch_model(graph, "", "all", gv.ARCH_LAYER_BUDGET, layered=True)
    assert model is not None
    assert any(src.endswith("S1") and dst == gv._arch_cell_id(1, "S2") for src, dst in lines_of(model))
    assert gv._arch_place(graph)["final"]["C1"] <= gv.ARCH_API_LAYER


def test_with_no_api_anywhere_no_part_counts_as_browser_code():
    graph = make_graph(make_map_run_in_two_places(["web"]))
    doc = make_map_run_in_two_places(["web"])
    for c in doc["components"]:
        c["runs_in"] = ["web"]
        if c.get("kind") == "api":
            c["kind"] = "logic"
    assert gv._arch_client_parts(make_graph(doc)) == set()
    assert gv._arch_client_parts(graph) == {"C1", "C2"}


def test_parts_that_call_each_other_share_one_layer():
    out = gv._arch_fewest_moves([("A", "B"), ("B", "A")], {"A": 1, "B": 2}, {}, {"A": 3, "B": 3})
    assert out["A"] == out["B"]


def test_a_line_no_placement_can_straighten_binds_nothing():
    """The store calling the screen stays a line up the layers; the check the store calls still moves down."""
    out = gv._arch_fewest_moves([("store", "screen"), ("store", "check")], {"check": 2},
                                {"store": 3, "screen": 0}, {"check": 3})
    assert out == {"check": 3}


def test_between_two_placements_that_cost_the_same_the_parts_stay_high():
    out = gv._arch_fewest_moves([("A", "B")], {"A": 2, "B": 1}, {}, {"A": 3, "B": 3})
    assert out == {"A": 1, "B": 1}


def test_the_layered_picture_keeps_the_story_numbers_and_the_text():
    graph = make_graph(make_layered_map())
    _drawings, texts = gv.gen_arch_views(graph)
    pairs = {(e["srcBox"], e["dstBox"]) for e in texts["all|"]["lines"]}
    assert {(gv._person_id("Admin"), "I1"), ("I1", gv._arch_cell_id(0, "S1"))} <= pairs
    assert not any("n" in e or "verb" in e for e in texts["all|"]["lines"]), "the view reads neither"
    assert "stories" not in texts["all|"], "no story is followed on the picture"


# --- the use case map marks the same things ---------------------------------------------

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
    """The key is drawn by the viewer, the marks by the generator: the two must stay the same. No rule
    mark: no picture ties a rule to a step (2026-10-01)."""
    js = _VIEWER_JS.read_text()
    assert "RULE_MARK" not in js and not hasattr(gv, "RULE_MARK")
    # Every box line is drawn the same, so the key names no line style of its own.
    assert "ARCH_STORE_LINE" not in js and not hasattr(gv, "ARCH_STORE_LINE")


def test_every_line_is_drawn_the_same_with_no_word_on_it():
    """No dashed line, no colour of its own, no label: the card tells a line."""
    drawing = gv.gen_arch_views(make_graph())[0]["all|"]
    assert "-.->" not in drawing and "|" not in "".join(ln for ln in drawing.splitlines() if "-->" in ln)
    assert "linkStyle" not in drawing


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)


def test_a_box_does_not_name_the_subsystem_it_sits_in() -> None:
    """A component's box carried its subsystem as a pill, a line of every box spent on what its card
    says one hover away. The only pill a picture adds to a box is a person's `via AI agent`."""
    graph = make_fixture_graph()
    comp = next(i for i, n in graph["nodes"].items()
                if n.get("kind") == "component" and gv._top_subsystem(graph, i) not in (None, i))
    lines: list[str] = []
    gv._arch_inside_box(graph, lines, comp, set(), {})
    assert f"data-id={comp}" in lines[0] and "data-pill" not in lines[0], lines
