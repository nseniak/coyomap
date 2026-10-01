#!/usr/bin/env python3
"""`Component.kind`: what kind of thing a component is, in one word: a known word, or a word the
map mints and declares once, with the known word it acts as.

The kind is optional, so a map built before it loads and draws as it always did. A word that is
neither known nor declared blocks, because the Architecture picture places and draws a part by the
known word; a missing kind is advised only on a map that states kinds for other components. Run
either way: `python3 tests/test_component_kind.py` or pytest.
"""
from __future__ import annotations

import json
from typing import Any

from coyomap import grammar
from coyomap.assemble import merge_fragments
from coyomap.mapdiff import diff_maps
from coyomap.model import FORMAT, ComponentKind, ProjectModel, load_model
from coyomap.validate_model import validate_model
from coyomap.viewer import gen_viewer as gv
from coyomap.views import model_to_graph, model_to_markdown


def make_map(**kinds: str) -> dict[str, Any]:
    """Two components, one use case: the smallest map a kind can sit on."""
    comps = [{"id": "C1", "name": "Team page", "purpose": "shows the team", "files": ["src/page.ts"]},
             {"id": "C2", "name": "Team store", "purpose": "keeps the team", "files": ["src/store.py"]}]
    for c in comps:
        if c["id"] in kinds:
            c["kind"] = kinds[c["id"]]
    return {
        "format": FORMAT, "title": "T", "goal": "G",
        "roles": [{"id": "R1", "name": "Admin", "kind": "human", "audience": "user", "wants": "x",
                   "drives": "UC1"}],
        "use_cases": [{"id": "UC1", "name": "See the team", "actors": ["R1"]}],
        "components": comps,
        "edges": [{"src": "C1", "verb": "calls", "dst": "C2", "why": "reads it", "where": "src/page.ts:3"}],
        "flows": [{"uc": "UC1", "title": "See the team", "steps": [
            {"n": 1, "src": "R1", "dst": "C1", "phrase": "open the team page"},
            {"n": 2, "src": "C1", "dst": "C2", "phrase": "read the team", "where": "src/page.ts:3"}]}],
    }


def make_minted_map(word: str = "skill", acts_as: str = "instructions", **kinds: str) -> dict[str, Any]:
    """The same map with one minted word declared."""
    doc = make_map(**kinds)
    doc["component_kinds"] = [{"word": word, "meaning": "instructions an agent loads by name",
                               "acts_as": acts_as}]
    return doc


def findings(doc: dict[str, Any]) -> tuple[list[str], list[str]]:
    return validate_model(load_model(json.dumps(doc)), disclose_records=False)


def test_a_map_with_no_kinds_loads_and_is_not_advised():
    problems, warnings = findings(make_map())
    assert not any("kind" in p for p in problems)
    assert not any(w.startswith("Components with no kind") for w in warnings)


def test_a_word_neither_known_nor_declared_blocks():
    problems, _ = findings(make_map(C1="page"))
    assert any(p.startswith("C1 (Team page) kind='page'") and "declare it" in p for p in problems)


def test_every_known_word_is_accepted_the_three_new_ones_too():
    for word in grammar.COMPONENT_KINDS:
        problems, _ = findings(make_map(C1=word, C2="store"))
        assert not any("kind=" in p for p in problems), (word, problems)
    assert {"command", "script", "instructions"} <= set(grammar.COMPONENT_KINDS)


def test_how_a_part_starts_is_not_a_kind():
    """A timer or the product's start is what a part's ways in record: `job` is no known word, and a
    word minted to say it is refused, whatever it acts as."""
    assert "job" not in grammar.COMPONENT_KINDS
    problems, _ = findings(make_map(C1="screen", C2="job"))
    assert any(p.startswith("C2 (Team store) kind='job'") for p in problems), problems
    for word in ("job", "cron"):
        problems, _ = findings(make_minted_map(word=word, acts_as="logic", C1="screen", C2=word))
        assert any(f"'{word}' names how a part starts" in p for p in problems), (word, problems)


def test_only_a_part_with_a_timed_way_in_says_it_runs_on_a_schedule():
    doc = make_map(C1="screen", C2="logic")
    doc["components"].append({"id": "C3", "name": "Boot", "purpose": "starts the app", "files": ["src/boot.py"],
                              "kind": "logic"})
    doc["entry_points"] = [{"kind": "job", "trigger": "every hour", "component": "C2", "source": "src/store.py:9"},
                           {"kind": "ui-route", "trigger": "open /team", "component": "C1", "source": "src/page.ts:1"},
                           {"kind": "startup-hook", "trigger": "at start", "component": "C3", "source": "src/boot.py:3"}]
    nodes = model_to_graph(load_model(json.dumps(doc)))["nodes"]
    assert nodes["C2"]["fields"].get("Starts") == "on a schedule"
    assert "Starts" not in nodes["C1"]["fields"]
    assert "Starts" not in nodes["C3"]["fields"], "a startup hook is not a schedule"


def test_a_part_whose_way_in_filters_requests_says_it_runs_before_the_apis():
    doc = make_map(C1="screen", C2="check")
    doc["entry_points"] = [{"kind": "middleware", "trigger": "every request", "component": "C2", "source": "src/store.py:3"},
                           {"kind": "ui-route", "trigger": "open /team", "component": "C1", "source": "src/page.ts:1"}]
    nodes = model_to_graph(load_model(json.dumps(doc)))["nodes"]
    assert nodes["C2"]["fields"].get("Runs") == "before the APIs"
    assert nodes["C2"]["fields"].get("Kind") == "check"   # what it does is still its kind
    assert "Runs" not in nodes["C1"]["fields"]


def test_a_declared_word_is_accepted_and_acts_as_its_known_word():
    problems, _ = findings(make_minted_map(C1="skill", C2="store"))
    assert not any("kind" in p for p in problems), problems
    graph = model_to_graph(load_model(json.dumps(make_minted_map(C1="skill", C2="store"))))
    assert graph["nodes"]["C1"]["component_kind"] == "instructions"   # the picture acts on this
    assert graph["nodes"]["C1"]["fields"]["Kind"] == "skill"            # the pill says the word


def test_a_declaration_that_cannot_say_how_to_draw_its_word_blocks():
    cases = {"known": (make_minted_map(word="logic", C1="logic"), "is a known word"),
             "acts": (make_minted_map(acts_as="widget", C1="skill"), "must be one known word"),
             "several": (make_minted_map(acts_as="more than one answer was found: logic; pipe",
                                         C1="skill"), "must be one known word")}
    for name, (doc, expected) in cases.items():
        problems, _ = findings(doc)
        assert any(expected in p for p in problems), (name, problems)
    doc = make_minted_map(C1="skill")
    doc["component_kinds"][0]["meaning"] = ""
    assert any("has no meaning" in p for p in findings(doc)[0])
    doc = make_minted_map(C1="skill")
    doc["component_kinds"] *= 2
    assert any("declared twice" in p for p in findings(doc)[0])


def test_a_minted_word_one_component_uses_is_advised_and_can_be_recorded():
    """One part with its own word is usually a known word in other clothes."""
    _, warnings = findings(make_minted_map(C1="skill", C2="store"))
    assert any(w.startswith("Minted component kinds that only one component uses: C1 'skill'")
               for w in warnings), warnings
    doc = make_minted_map(C1="skill", C2="store")
    doc["extras"] = [{"heading": "Kind exceptions", "body": "C1: the product's one real skill"}]
    assert not any(w.startswith("Minted component kinds that only one") for w in findings(doc)[1])
    _, warnings = findings(make_minted_map(C1="skill", C2="skill"))
    assert not any(w.startswith("Minted component kinds that only one") for w in warnings)


def test_a_declared_word_no_component_uses_is_advised():
    _, warnings = findings(make_minted_map(C1="logic", C2="store"))
    assert any(w.startswith("Minted component kinds that no component uses: 'skill'") for w in warnings)


def test_a_minted_word_acting_as_a_pipe_is_drawn_through():
    """The picture acts on the known word, so a minted "relay" that acts as a pipe vanishes the
    way a pipe does."""
    doc = make_minted_map(word="relay", acts_as="pipe", C1="screen", C2="relay")
    doc["components"].append({"id": "C3", "name": "Team logic", "purpose": "runs the team",
                              "kind": "logic", "files": ["src/logic.py"]})
    doc["flows"][0]["steps"].append({"n": 3, "src": "C2", "dst": "C3", "phrase": "pass it on",
                                     "where": "src/store.py:9"})
    graph = model_to_graph(load_model(json.dumps(doc)))
    kept = gv._draw_through(graph, gv._arch_steps(graph, graph["flows"][0]))
    assert ("C1", "C3") in [(st["src"], st["dst"]) for st in kept]


def test_two_slices_minting_one_word_merge_into_one_declaration():
    one = ProjectModel(component_kinds=[ComponentKind("skill", "instructions an agent loads", "instructions")])
    two = ProjectModel(component_kinds=[ComponentKind("skill", "instructions an agent loads", "instructions")])
    merged = merge_fragments([("a.json", one), ("b.json", two)])[0]
    assert [(k.word, k.acts_as) for k in merged.component_kinds] == [("skill", "instructions")]
    three = ProjectModel(component_kinds=[ComponentKind("skill", "instructions an agent loads", "logic")])
    merged = merge_fragments([("a.json", one), ("c.json", three)])[0]
    assert len(merged.component_kinds) == 1
    assert merged.component_kinds[0].acts_as not in grammar.COMPONENT_KINDS   # both answers kept


def test_a_changed_declaration_is_a_change_of_its_word():
    before = make_minted_map(C1="skill", C2="skill")
    after = json.loads(json.dumps(before))
    after["component_kinds"][0]["meaning"] = "a named set of instructions an agent loads"
    delta = diff_maps(before, after)
    rows = [e for e in delta.elements if e.kind == "component_kinds"]
    assert [(e.change, e.name_new) for e in rows] == [("modified", "skill")]


def test_a_missing_kind_is_advised_once_other_components_state_one():
    _, warnings = findings(make_map(C1="screen"))
    assert any(w.startswith("Components with no kind, on a map where 1 others have one: C2") for w in warnings)


def test_the_kind_rides_on_the_graph_and_on_the_card_word():
    graph = model_to_graph(load_model(json.dumps(make_map(C1="api", C2="store"))))
    assert graph["nodes"]["C1"]["component_kind"] == "api"
    assert graph["nodes"]["C1"]["fields"]["Kind"] == grammar.COMPONENT_KIND_WORDS["api"] == "API"
    assert graph["nodes"]["C2"]["fields"]["Kind"] == "store"


def test_the_markdown_view_gains_a_kind_column_only_when_a_kind_is_stated():
    assert "| ID | Component | Subsystem |" in model_to_markdown(load_model(json.dumps(make_map())))
    md = model_to_markdown(load_model(json.dumps(make_map(C1="screen"))))
    assert "| ID | Component | Kind | Subsystem |" in md and "| Team page | screen |" in md


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
