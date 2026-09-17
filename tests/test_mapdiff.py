#!/usr/bin/env python3
"""`coyomap diff` — what changed between two maps, as a reader would ask it.

The engine pairs rows (by id, then by name, then by code file), aligns a use case's steps like lines
of text, keys an arrow by its ends, classes every changed field (wording / structure / link), and
renders three ways: text for the agent, markdown for people, JSON for the viewer's change mode.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_mapdiff.py
    pytest tests/test_mapdiff.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from coyomap import mapdiff
from coyomap.mapdiff import (
    ElementDelta, KindCount, MapDelta, align_steps, diff_maps, field_deltas, to_json, to_markdown,
    to_text, word_spans,
)

FORMAT = "coyomap-map"


def make_map(**overrides) -> dict:
    doc = {
        "format": FORMAT, "title": "t", "goal": "g",
        "roles": [{"id": "R1", "name": "Reader", "wants": "a map", "kind": "human"}],
        "use_cases": [{"id": "UC1", "name": "Open the map", "actors": ["R1"],
                       "trigger_outcome": "The reader opens the map and sees the overview."}],
        "flows": [{"uc": "UC1", "title": "Open the map", "steps": make_steps(3)}],
        "components": [{"id": "C1", "name": "Server", "source": "srv.py:10", "purpose": "serves the map",
                        "files": ["srv.py"]}],
        "entities": [{"id": "E1", "name": "Thing", "meaning": "one thing", "source": "m.py:3",
                      "fields": [{"name": "id", "type": "str"}, {"name": "size", "type": "int"}]}],
        "edges": [],
        "rules": [],
        "entry_points": [],
    }
    doc.update(overrides)
    return doc


def make_steps(n: int, src: str = "R1", dst: str = "C1") -> list[dict]:
    return [{"n": i + 1, "src": src, "dst": dst, "phrase": f"does thing {i + 1}", "where": f"srv.py:{20 + i}"}
            for i in range(n)]


def make_rule(rid: str, statement: str, risk: str = "r", where: str = "a.py:1") -> dict:
    return {"id": rid, "name": statement, "statement": statement, "risk": risk,
            "sites": [{"where": where, "why": "guards"}]}


def make_edge(src: str, verb: str, dst: str, where: str, why: str = "w") -> dict:
    return {"src": src, "verb": verb, "dst": dst, "where": where, "why": why}


def make_ep(source: str, trigger: str, eid: str = "", cadence: str = "") -> dict:
    row = {"kind": "cli", "trigger": trigger, "source": source, "component": "C1"}
    if eid:
        row["id"] = eid
    if cadence:
        row["cadence"] = cadence
    return row


def copy(doc: Any) -> Any:
    return json.loads(json.dumps(doc))


def rows(delta: MapDelta, kind: str) -> list[ElementDelta]:
    return [e for e in delta.elements if e.kind == kind]


def count(delta: MapDelta, kind: str) -> KindCount | None:
    return next((c for c in delta.counts if c.kind == kind), None)


# --- pairing by id -----------------------------------------------------------------------

def test_an_unchanged_map_reports_nothing():
    m = make_map(rules=[make_rule("BR1", "A token is checked")])
    d = diff_maps(m, copy(m))
    assert d.elements == [] and d.arrows == [] and d.counts == [] and d.warnings == []


def test_a_changed_field_names_the_row_its_label_and_its_class():
    before = make_map(rules=[make_rule("BR1", "A token is checked", risk="old")])
    after = make_map(rules=[make_rule("BR1", "A token is checked", risk="new")])
    (e,) = rows(diff_maps(before, after), "rules")
    assert e.change == "modified" and e.id_new == "BR1"
    assert [(f.key, f.label, f.cls, f.old, f.new) for f in e.fields] == [("risk", "Risk", "structure", "old", "new")]
    assert e.summary == "risk changed"


def test_several_moved_fields_are_all_listed():
    before = make_map(rules=[make_rule("BR1", "A token is checked", risk="old")])
    after = make_map(rules=[make_rule("BR1", "A token is checked twice", risk="new")])
    (e,) = rows(diff_maps(before, after), "rules")
    assert sorted(f.key for f in e.fields) == ["name", "risk", "statement"]
    assert e.classes == ["wording", "structure"]


def test_an_added_and_a_removed_row_are_separated_and_counted():
    before = make_map(rules=[make_rule("BR1", "old rule")])
    after = make_map(rules=[make_rule("BR2", "new rule")])
    d = diff_maps(before, after)
    assert [(e.change, e.key) for e in rows(d, "rules")] == [("removed", "BR1"), ("added", "BR2")]
    c = count(d, "rules")
    assert c is not None and (c.added, c.removed, c.modified) == (1, 1, 0)


def test_a_removed_row_carries_every_old_field_and_its_old_steps_for_its_page():
    before = make_map()
    after = make_map(use_cases=[], flows=[])
    (e,) = rows(diff_maps(before, after), "use_cases")
    assert e.change == "removed" and e.name_old == "Open the map"
    assert {(f.key, f.new) for f in e.fields} >= {("name", None), ("trigger_outcome", None), ("actors", None)}
    assert [f.old for f in e.fields if f.key == "actors"] == ["Reader"], "a reader never meets an id"
    assert [s.state for s in e.steps] == ["removed"] * 3 and e.summary == "removed"


def test_a_reference_field_reads_by_name_on_both_sides():
    before = make_map(roles=[{"id": "R1", "name": "Reader"}, {"id": "R2", "name": "Admin"}])
    after = make_map(roles=[{"id": "R1", "name": "Reader"}, {"id": "R2", "name": "Admin"}],
                     use_cases=[{**make_map()["use_cases"][0], "actors": ["R2"]}])
    (e,) = rows(diff_maps(before, after), "use_cases")
    (f,) = [f for f in e.fields if f.key == "actors"]
    assert (f.old, f.new, f.added, f.removed) == ("Reader", "Admin", ["Admin"], ["Reader"])


def test_a_step_that_runs_a_shared_sub_flow_is_named_by_it():
    sf = {"id": "SF1", "name": "Sign in", "steps": make_steps(1)}
    steps = make_steps(3) + [{"n": 4, "src": "R1", "dst": "C1", "phrase": "", "subflow": "SF1"}]
    before = make_map(subflows=[sf])
    after = make_map(subflows=[sf], flows=[{"uc": "UC1", "title": "Open the map", "steps": steps}])
    (e,) = rows(diff_maps(before, after), "use_cases")
    (st,) = [s for s in e.steps if s.state == "added"]
    assert st.phrase_new is None and st.subflow == "Sign in"
    assert "+ step 4: runs Sign in" in to_markdown(diff_maps(before, after))


def test_an_added_row_s_summary_is_its_own_sentence():
    after = make_map(rules=[make_rule("BR1", "A token is checked")])
    (e,) = rows(diff_maps(make_map(), after), "rules")
    assert e.summary == "A token is checked"


def test_a_count_change_is_reported_even_with_no_row_detail():
    before = make_map(tests=[{"label": "a"}])
    after = make_map(tests=[{"label": "a"}, {"label": "b"}])
    d = diff_maps(before, after)
    c = count(d, "tests")
    assert c is not None and (c.before, c.after) == (1, 2) and rows(d, "tests") == []
    assert "counted only" in to_text(d)


def test_a_duplicate_id_in_an_id_keyed_array_is_reported_by_count_not_paired():
    before = make_map(rules=[make_rule("BR1", "one"), make_rule("BR1", "two")])
    after = make_map(rules=[make_rule("BR1", "three")])
    d = diff_maps(before, after)
    c = count(d, "rules")
    assert c is not None and c.collisions == ["BR1"] and c.removed == 1 and c.modified == 0
    assert "! BR1" in to_text(d)


def test_a_unique_key_is_still_compared_field_by_field_beside_a_collision():
    before = make_map(rules=[make_rule("BR1", "one"), make_rule("BR1", "two"), make_rule("BR2", "x", risk="a")])
    after = make_map(rules=[make_rule("BR1", "one"), make_rule("BR1", "two"), make_rule("BR2", "x", risk="b")])
    (e,) = rows(diff_maps(before, after), "rules")
    assert e.id_new == "BR2" and [f.key for f in e.fields] == ["risk"]


def test_an_unmodelled_field_is_still_compared():
    """A diff that only saw modelled fields would go quiet exactly on the extras a build writes."""
    before = make_map(components=[{"id": "C1", "name": "A", "source": "a.py:1", "made_up": 1}])
    after = make_map(components=[{"id": "C1", "name": "A", "source": "a.py:1", "made_up": 2}])
    (e,) = rows(diff_maps(before, after), "components")
    assert [(f.key, f.label, f.old, f.new) for f in e.fields] == [("made_up", "Made up", "1", "2")]


# --- code links are a class of their own ---------------------------------------------------

def test_a_moved_code_line_is_a_link_change_counted_apart():
    before = make_map(components=[{"id": "C1", "name": "A", "source": "a.py:1"}])
    after = make_map(components=[{"id": "C1", "name": "A", "source": "a.py:9"}])
    d = diff_maps(before, after)
    (e,) = rows(d, "components")
    assert e.classes == ["link"] and e.summary == "code link moved"
    c = count(d, "components")
    assert c is not None and (c.modified, c.link_only) == (0, 1)
    assert "≈ C1  [source]" in to_text(d)


def test_enforcement_sites_whose_lines_moved_are_a_link_change_with_no_items():
    before = make_map(rules=[make_rule("BR1", "x", where="a.py:1")])
    after = make_map(rules=[make_rule("BR1", "x", where="a.py:40")])
    (e,) = rows(diff_maps(before, after), "rules")
    (f,) = e.fields
    assert f.key == "sites" and f.cls == "link" and not f.added and not f.removed


def test_an_evidence_row_whose_line_moved_is_a_link_move_not_a_new_row():
    """A dependency's evidence is keyed by its file, never its line: on the real mcpolis update the
    re-anchor moved one evidence line and the gate read it as a row that came and went."""
    before = make_map(deps=[{"id": "D1", "name": "Store", "evidence": [{"file": "a.py:42", "why": "w"}, {"file": "b.py:9", "why": "w"}]}])
    after = make_map(deps=[{"id": "D1", "name": "Store", "evidence": [{"file": "a.py:45", "why": "w"}, {"file": "b.py:9", "why": "w"}]}])
    (e,) = rows(diff_maps(before, after), "deps")
    assert e.classes == ["link"] and e.fields[0].added == [] and e.fields[0].removed == []
    after["deps"][0]["evidence"].append({"file": "c.py:1", "why": "a third place"})
    (e,) = rows(diff_maps(before, after), "deps")
    assert e.classes == ["structure"] and e.fields[0].added == ["a third place (c.py)"]


def test_a_file_list_whose_lines_moved_is_a_link_move():
    before = make_map(components=[{"id": "C1", "name": "A", "files": ["a.py:10", "b.py"]}])
    after = make_map(components=[{"id": "C1", "name": "A", "files": ["a.py:14", "b.py"]}])
    (e,) = rows(diff_maps(before, after), "components")
    assert e.classes == ["link"]


def test_a_new_enforcement_site_is_a_structural_item():
    before = make_map(rules=[make_rule("BR1", "x")])
    after = make_map(rules=[{**make_rule("BR1", "x"), "sites": [{"where": "a.py:1", "why": "guards"},
                                                                {"where": "b.py:2", "why": "checks"}]}])
    (e,) = rows(diff_maps(before, after), "rules")
    (f,) = e.fields
    assert f.added == ["checks (b.py)"] and f.removed == []
    assert f.cls == "structure" and e.classes == ["structure"], "a new enforcement point is structure, not a moved link"


# --- words and lists ------------------------------------------------------------------------

def test_a_reworded_sentence_carries_word_spans_that_rejoin_to_both_texts():
    old, new = "The reader opens the map and sees the overview.", "The reader opens the map and lands on the overview."
    spans = word_spans(old, new)
    assert "".join(s.text for s in spans if s.op != "ins") == old
    assert "".join(s.text for s in spans if s.op != "del") == new
    assert [s.op for s in spans] == ["eq", "del", "ins", "eq"]
    assert [s.text for s in spans if s.op == "ins"] == ["lands on"]


def test_a_list_field_names_the_items_that_came_and_went():
    before = make_map()
    after = make_map(entities=[{**make_map()["entities"][0],
                                "fields": [{"name": "id", "type": "str"}, {"name": "owner", "type": "str"}]}])
    (e,) = rows(diff_maps(before, after), "entities")
    (f,) = e.fields
    assert (f.label, f.cls, f.added, f.removed) == ("Fields", "structure", ["owner (str)"], ["size (int)"])


def test_a_reordered_list_is_not_a_change():
    a = {"id": "C1", "name": "A", "files": ["x.py", "y.py"]}
    b = {"id": "C1", "name": "A", "files": ["y.py", "x.py"]}
    assert field_deltas(a, b, {}) == []


# --- steps: aligned like lines of text -----------------------------------------------------

def test_a_step_inserted_in_the_middle_is_one_addition_and_the_rest_renumbered():
    old = make_steps(3)
    new = [old[0], {"n": 2, "src": "R1", "dst": "C1", "phrase": "confirms the plan", "where": "srv.py:99"},
           {**old[1], "n": 3}, {**old[2], "n": 4}]
    steps = align_steps(old, new, {})
    assert [(s.state, s.n_old, s.n_new) for s in steps] == [("added", None, 2), ("renumbered", 2, 3), ("renumbered", 3, 4)]


def test_a_reworded_step_keeps_its_place_and_shows_the_changed_words():
    old = make_steps(2)
    new = copy(old)
    new[1]["phrase"] = "does the second thing"
    (s,) = align_steps(old, new, {})
    assert s.state == "modified" and s.n_new == 2 and s.phrase_old == "does thing 2"
    assert "".join(t.text for t in s.spans if t.op != "ins") == "does thing 2"
    assert "".join(t.text for t in s.spans if t.op != "del") == "does the second thing"
    assert {t.op for t in s.spans} == {"eq", "del", "ins"}


def test_a_step_whose_code_line_moved_is_a_link_change_not_a_rewording():
    old = make_steps(1)
    new = copy(old)
    new[0]["where"] = "srv.py:200"
    (s,) = align_steps(old, new, {})
    assert s.state == "modified" and s.spans == [] and [(f.key, f.cls) for f in s.fields] == [("where", "link")]
    assert s.classes == ["link"]


def test_a_use_case_whose_steps_only_moved_in_the_code_is_a_link_only_change():
    before = make_map()
    after = make_map(flows=[{"uc": "UC1", "title": "Open the map",
                             "steps": [{**st, "where": f"srv.py:{100 + i}"} for i, st in enumerate(make_steps(3))]}])
    d = diff_maps(before, after)
    (e,) = rows(d, "use_cases")
    assert e.classes == ["link"] and e.summary == "3 steps moved in the code"
    c = count(d, "use_cases")
    assert c is not None and (c.modified, c.link_only) == (0, 1)


def test_the_steps_phrase_tells_reworded_from_moved_in_the_code():
    old = make_steps(3)
    new = copy(old)
    new[0]["phrase"] = "does the first thing"
    new[1]["where"] = "srv.py:900"
    new.append({"n": 4, "src": "R1", "dst": "C1", "phrase": "does a fourth thing", "where": "srv.py:30"})
    (e,) = rows(diff_maps(make_map(), make_map(flows=[{"uc": "UC1", "title": "Open the map", "steps": new}])), "use_cases")
    assert e.summary == "steps: 1 added, 1 reworded, 1 moved in the code"


def test_step_changes_land_on_the_use_case_row_with_a_phrase():
    before = make_map()
    after = make_map(flows=[{"uc": "UC1", "title": "Open the map", "steps": make_steps(5)}])
    d = diff_maps(before, after)
    (e,) = rows(d, "use_cases")
    assert e.change == "modified" and e.summary == "2 steps added"
    assert [s.state for s in e.steps] == ["added", "added"] and e.fields == []
    assert "~ UC1  [steps +2]" in to_text(d)


def test_a_flow_s_own_title_lands_on_its_use_case():
    before = make_map()
    after = make_map(flows=[{"uc": "UC1", "title": "Open a map", "steps": make_steps(3)}])
    (e,) = rows(diff_maps(before, after), "use_cases")
    assert [f.key for f in e.fields] == ["title"] and e.summary == "title reworded"


def test_a_shared_sub_flow_s_steps_are_aligned_too():
    sf = {"id": "SF1", "name": "Sign in", "steps": make_steps(2)}
    before = make_map(subflows=[sf])
    after = make_map(subflows=[{**sf, "steps": make_steps(3)}])
    (e,) = rows(diff_maps(before, after), "subflows")
    assert [s.state for s in e.steps] == ["added"] and e.summary == "1 step added"


# --- arrows: keyed by their ends ------------------------------------------------------------

def test_arrows_match_on_their_ends_and_a_reason_change_is_wording():
    before = make_map(edges=[make_edge("C1", "reads", "E1", "a.py:1", why="old reason")])
    after = make_map(edges=[make_edge("C1", "reads", "E1", "a.py:1", why="new reason")])
    (a,) = diff_maps(before, after).arrows
    assert a.change == "modified" and a.classes == ["wording"] and [f.key for f in a.fields] == ["why"]


def test_a_moved_call_line_keeps_the_arrow_paired_as_a_link_change():
    """The old engine keyed an arrow by its line, so a line shift read as removed plus added —
    158 arrows on the live map carry a line, and every refactor lit them all."""
    before = make_map(edges=[make_edge("C1", "reads", "E1", "a.py:1")])
    after = make_map(edges=[make_edge("C1", "reads", "E1", "a.py:9")])
    d = diff_maps(before, after)
    (a,) = d.arrows
    assert a.change == "modified" and a.classes == ["link"] and (a.where_old, a.where_new) == ("a.py:1", "a.py:9")
    c = count(d, "edges")
    assert c is not None and (c.added, c.removed, c.link_only) == (0, 0, 1)


def test_two_arrows_with_the_same_ends_at_two_call_sites_stay_two_rows():
    """`assemble` deliberately keeps two no-call-site edges on one triple so a differing `why` can
    tell two couplings apart; deleting one must read as one removal, not as nothing."""
    both = [make_edge("C1", "uses", "E1", "", why="first coupling"),
            make_edge("C1", "uses", "E1", "", why="second coupling")]
    d = diff_maps(make_map(edges=both), make_map(edges=both[1:]))
    assert [(a.change, a.summary) for a in d.arrows] == [("removed", "Server uses Thing")]


def test_a_new_call_site_beside_an_old_one_is_an_addition():
    before = make_map(edges=[make_edge("C1", "reads", "E1", "a.py:1")])
    after = make_map(edges=[make_edge("C1", "reads", "E1", "a.py:1"), make_edge("C1", "reads", "E1", "b.py:7")])
    (a,) = diff_maps(before, after).arrows
    assert a.change == "added" and a.where_new == "b.py:7"


# --- ways in: matched on content ------------------------------------------------------------

def test_entry_points_match_on_content_so_a_renumber_alone_is_not_a_change():
    """EP ids are minted and re-sorted on every assemble: one anchor edit moved 22 of 104 on a real
    map. Matching by id would report a fifth of them as replaced when nothing about them changed."""
    before = make_map(entry_points=[make_ep("a.py:1", "run it", eid="EP1"), make_ep("b.py:2", "serve it", eid="EP2")])
    after = make_map(entry_points=[make_ep("a.py:1", "run it", eid="EP7"), make_ep("b.py:2", "serve it", eid="EP8")])
    d = diff_maps(before, after)
    assert rows(d, "entry_points") == [] and count(d, "entry_points") is None


def test_a_way_in_whose_line_moved_is_the_same_way_in_with_a_moved_code_link():
    before = make_map(entry_points=[make_ep("a.py:1", "run it", eid="EP1")])
    after = make_map(entry_points=[make_ep("a.py:30", "run it", eid="EP1")])
    d = diff_maps(before, after)
    (e,) = rows(d, "entry_points")
    assert e.change == "modified" and e.classes == ["link"] and e.summary == "code link moved"
    c = count(d, "entry_points")
    assert c is not None and (c.added, c.removed, c.link_only) == (0, 0, 1)


def test_a_way_in_whose_file_was_renamed_is_still_the_same_way_in():
    """A package rename moves every anchor at once; 97 of 97 ways in read as replaced on a live map."""
    before = make_map(entry_points=[make_ep("tools/old/a.py:1", "run it", eid="EP1")])
    after = make_map(entry_points=[make_ep("tools/new/a.py:1", "run it", eid="EP1")])
    (e,) = rows(diff_maps(before, after), "entry_points")
    assert e.change == "modified" and e.classes == ["link"]


def test_two_ways_in_with_one_trigger_pair_by_their_files():
    before = make_map(entry_points=[make_ep("a.py:1", "run it"), make_ep("b.py:1", "run it")])
    after = make_map(entry_points=[make_ep("b.py:9", "run it"), make_ep("a.py:1", "run it")])
    (e,) = rows(diff_maps(before, after), "entry_points")
    assert e.classes == ["link"] and e.fields[0].old == "b.py:1" and e.fields[0].new == "b.py:9"


def test_a_real_entry_point_change_is_still_caught_under_content_matching():
    before = make_map(entry_points=[make_ep("a.py:1", "run it", eid="EP1")])
    after = make_map(entry_points=[make_ep("a.py:1", "run it", eid="EP1", cadence="daily")])
    (e,) = rows(diff_maps(before, after), "entry_points")
    assert [f.key for f in e.fields] == ["cadence"] and e.name_new == "run it"


# --- the same box under a new id --------------------------------------------------------------

def test_a_box_that_kept_its_name_under_a_new_id_is_the_same_box():
    before = make_map(components=[{"id": "C1", "name": "Server", "source": "srv.py:10", "purpose": "serves"}],
                      edges=[make_edge("C1", "reads", "E1", "srv.py:12")])
    after = make_map(components=[{"id": "C9", "name": "Server", "source": "srv.py:10", "purpose": "serves and caches"}],
                     edges=[make_edge("C9", "reads", "E1", "srv.py:12")])
    d = diff_maps(before, after)
    (e,) = rows(d, "components")
    assert e.reidentified and (e.id_old, e.id_new) == ("C1", "C9") and e.change == "modified"
    assert [f.key for f in e.fields] == ["purpose"] and "same component under a new id" in e.summary
    assert d.arrows == [], "an arrow naming the re-identified box must not read as changed"
    assert d.idmap == {"C1": "C9"} and "⇒ C1 → C9" in to_text(d)


def test_a_box_that_kept_its_code_file_under_a_new_id_and_name_is_the_same_box():
    before = make_map(components=[{"id": "C1", "name": "Server", "source": "srv.py:10"}])
    after = make_map(components=[{"id": "C2", "name": "Map server", "source": "srv.py:10"}])
    (e,) = rows(diff_maps(before, after), "components")
    assert e.reidentified and e.summary == "renamed from Server · same component under a new id"


def test_a_guess_never_pairs_when_the_name_is_held_twice():
    before = make_map(components=[{"id": "C1", "name": "Worker", "source": "a.py:1"}])
    after = make_map(components=[{"id": "C5", "name": "Worker", "source": "b.py:1"},
                                 {"id": "C6", "name": "Worker", "source": "c.py:1"}])
    d = diff_maps(before, after)
    assert sorted(e.change for e in rows(d, "components")) == ["added", "added", "removed"]


# --- naming and warnings --------------------------------------------------------------------

def test_a_happy_path_step_is_named_by_its_use_case():
    before = make_map(happy_path=[{"id": "HP1", "uc": "UC1", "why": "first"}])
    after = make_map(happy_path=[{"id": "HP1", "uc": "UC1", "why": "first, and only"}])
    (e,) = rows(diff_maps(before, after), "happy_path")
    assert e.name_new == "Open the map"


def test_two_maps_that_look_like_separate_builds_are_flagged():
    ucs_old = [{"id": f"UC{i}", "name": f"Old goal {i}"} for i in range(1, 5)]
    ucs_new = [{"id": f"UC{i}", "name": f"New goal {i}"} for i in range(1, 5)]
    d = diff_maps(make_map(use_cases=ucs_old, flows=[]), make_map(use_cases=ucs_new, flows=[]))
    assert any("separate builds" in w and "0 of 4 use cases" in w for w in d.warnings)


def test_the_separate_builds_check_needs_three_shared_use_cases():
    d = diff_maps(make_map(use_cases=[{"id": "UC1", "name": "a"}], flows=[]),
                  make_map(use_cases=[{"id": "UC1", "name": "b"}], flows=[]))
    assert d.warnings == []


def test_an_older_format_is_compared_with_a_warning_not_refused():
    old = make_map(format="coyodex-map")
    d = diff_maps(old, make_map())
    assert any("older format" in w for w in d.warnings)


# --- the three renderings -------------------------------------------------------------------

def test_the_text_form_marks_removed_added_changed_and_link_only_distinctly():
    before = make_map(rules=[make_rule("BR1", "one"), make_rule("BR2", "two"), make_rule("BR3", "three", where="a.py:1")])
    after = make_map(rules=[make_rule("BR1", "one!"), make_rule("BR3", "three", where="a.py:2"), make_rule("BR4", "four")])
    txt = to_text(diff_maps(before, after))
    assert "    - BR2" in txt and "    + BR4" in txt
    assert "    ~ BR1  [name, statement]" in txt and "    ≈ BR3  [sites]" in txt


def test_no_change_says_so_rather_than_printing_an_empty_report():
    m = make_map()
    assert to_text(diff_maps(m, copy(m), "a", "b")) == "map diff — a → b\n  no row changed."


def test_the_markdown_form_names_boxes_and_shows_the_changed_words_under_their_group():
    before = make_map(rules=[make_rule("BR1", "A token is checked")])
    after = make_map(rules=[make_rule("BR1", "A token is checked twice")],
                     components=[{"id": "C1", "name": "Server", "source": "srv.py:10", "purpose": "serves the map fast"}])
    md = to_markdown(diff_maps(before, after, "old", "new"))
    assert md.startswith("# What changed: old → new")
    assert "0 boxes added · 0 removed · 2 modified · 0 moved in the code only" in md
    assert md.index("## Product") < md.index("### Rules") < md.index("## Under the hood") < md.index("### Components")
    assert "- **A token is checked twice** (modified): renamed from A token is checked · statement reworded" in md
    assert "  - Name: A token is checked **twice**" in md and "  - Statement: A token is checked **twice**" in md
    assert "Purpose: serves the map **fast**" in md


def test_the_json_form_is_the_whole_document():
    before = make_map(rules=[make_rule("BR1", "x", risk="r1")])
    after = make_map(rules=[make_rule("BR1", "x", risk="r2")])
    payload = to_json(diff_maps(before, after))
    assert payload["kind"] == "coyomap-map-diff" and payload["version"] == 2
    (e,) = payload["elements"]
    assert e["kind"] == "rules" and e["fields"][0]["label"] == "Risk" and payload["counts"][0]["modified"] == 1


# --- the CLI ----------------------------------------------------------------------------

def write_map(path: Path, doc: dict) -> str:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def test_cli_emits_parseable_json(capsys):
    with tempfile.TemporaryDirectory() as td:
        a = write_map(Path(td) / "a.json", make_map(rules=[make_rule("BR1", "x", risk="r1")]))
        b = write_map(Path(td) / "b.json", make_map(rules=[make_rule("BR1", "x", risk="r2")]))
        assert mapdiff.main([a, b, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "coyomap-map-diff"
    assert [f["key"] for f in payload["elements"][0]["fields"]] == ["risk"]


def test_cli_emits_markdown(capsys):
    with tempfile.TemporaryDirectory() as td:
        a = write_map(Path(td) / "a.json", make_map(rules=[make_rule("BR1", "x", risk="r1")]))
        b = write_map(Path(td) / "b.json", make_map(rules=[make_rule("BR1", "x", risk="r2")]))
        assert mapdiff.main([a, b, "--md"]) == 0
        assert "### Rules" in capsys.readouterr().out


def test_cli_refuses_a_document_that_is_not_a_map(capsys):
    with tempfile.TemporaryDirectory() as td:
        a = write_map(Path(td) / "a.json", make_map())
        bad = Path(td) / "b.json"
        bad.write_text('[1, 2, 3]', encoding="utf-8")
        assert mapdiff.main([a, str(bad)]) == 2
        assert "not a map" in capsys.readouterr().err


def test_cli_compares_an_older_format_and_says_so(capsys):
    with tempfile.TemporaryDirectory() as td:
        a = write_map(Path(td) / "a.json", make_map(format="coyodex-map"))
        b = write_map(Path(td) / "b.json", make_map())
        assert mapdiff.main([a, b]) == 0
        assert "older format" in capsys.readouterr().out


def test_cli_needs_exactly_two_maps(capsys):
    with tempfile.TemporaryDirectory() as td:
        a = write_map(Path(td) / "a.json", make_map())
        assert mapdiff.main([a]) == 2
        assert "exactly two map paths" in capsys.readouterr().err


def test_cli_refuses_an_unknown_option_with_the_usage(capsys):
    assert mapdiff.main(["--nope"]) == 2
    assert "usage: coyomap diff" in capsys.readouterr().err


def test_only_restricts_to_one_array():
    before = make_map(rules=[make_rule("BR1", "x", risk="a")], components=[{"id": "C1", "name": "A"}])
    after = make_map(rules=[make_rule("BR1", "x", risk="b")], components=[{"id": "C1", "name": "B"}])
    d = diff_maps(before, after, only="rules")
    assert [e.kind for e in d.elements] == ["rules"] and [c.kind for c in d.counts] == ["rules"]


def test_only_with_an_unknown_array_fails_loudly(capsys):
    with tempfile.TemporaryDirectory() as td:
        a = write_map(Path(td) / "a.json", make_map())
        b = write_map(Path(td) / "b.json", make_map())
        assert mapdiff.main([a, b, "--only", "edge"]) == 2
        assert "not an array in either map" in capsys.readouterr().err


def test_only_refuses_a_flag_as_its_value(capsys):
    assert mapdiff.main(["a", "b", "--only", "--json"]) == 2
    assert "another flag" in capsys.readouterr().err


def test_cli_writes_nothing():
    with tempfile.TemporaryDirectory() as td:
        a = write_map(Path(td) / "a.json", make_map(rules=[make_rule("BR1", "x")]))
        b = write_map(Path(td) / "b.json", make_map(rules=[make_rule("BR1", "y")]))
        before = {p.name: p.read_bytes() for p in Path(td).iterdir()}
        assert mapdiff.main([a, b]) == 0
        assert {p.name: p.read_bytes() for p in Path(td).iterdir()} == before


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
