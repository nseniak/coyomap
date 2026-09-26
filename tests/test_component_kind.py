#!/usr/bin/env python3
"""`Component.kind`: what kind of thing a component is, in one word of a closed list.

The kind is optional, so a map built before it loads and draws as it always did. A word outside the
list blocks, because the Architecture picture acts on the kind; a missing kind is advised only on a
map that states kinds for other components. Run either way: `python3 tests/test_component_kind.py`
or pytest.
"""
from __future__ import annotations

import json
from typing import Any

from coyomap import grammar
from coyomap.model import FORMAT, load_model
from coyomap.validate_model import validate_model
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


def findings(doc: dict[str, Any]) -> tuple[list[str], list[str]]:
    return validate_model(load_model(json.dumps(doc)), disclose_records=False)


def test_a_map_with_no_kinds_loads_and_is_not_advised():
    problems, warnings = findings(make_map())
    assert not any("kind" in p for p in problems)
    assert not any(w.startswith("Components with no kind") for w in warnings)


def test_a_word_outside_the_list_blocks():
    problems, _ = findings(make_map(C1="page"))
    assert any(p.startswith("C1 (Team page) kind='page'") for p in problems)


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
