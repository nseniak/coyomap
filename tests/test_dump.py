#!/usr/bin/env python3
"""Tests for `coyomap dump` — the fixed-slice JSON reader over the model.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_dump.py
    pytest tests/test_dump.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from coyomap.dump import edges_of, main, members_of, record_of, resolve_id
from coyomap.model import (
    Component,
    Edge,
    Entity,
    EntryPoint,
    Group,
    ProjectModel,
    UseCase,
    to_canonical_json,
)

CLI = [sys.executable, "-m", "coyomap.cli", "dump"]


# --- builders -------------------------------------------------------------------

def make_model() -> ProjectModel:
    m = ProjectModel(title="Demo", goal="A demo.")
    m.use_cases = [UseCase(id="UC1", name="View", actors=[])]
    m.subsystems = [Group(id="S1", name="Core", source="[core](backend/core/)"),
                    Group(id="S2", name="Edge", parent="S1")]
    m.components = [
        Component(id="C1", name="Viewer", subsystem="S1", source="backend/viewer.py#L1"),
        Component(id="C2", name="Store", subsystem="S1"),
        Component(id="C3", name="Umbrella", subsystem="S2"),
    ]
    # Ids as an ASSEMBLED map carries them: entry-point ids are minted at assemble and exist in no
    # fragment, which is why `--legend` is the only mid-build place to read them.
    m.entry_points = [
        EntryPoint(id="EP1", kind="http", trigger="GET /orders", source="backend/api.py#L10",
                   component="C3"),
        EntryPoint(id="EP2", kind="queue", trigger="orders.created", source="backend/sub.py#L3",
                   component="C3"),
    ]
    m.subdomains = [Group(id="SD1", name="Orders")]
    m.entities = [Entity(id="E1", name="Order", subdomain="SD1", source="backend/order.py#L7")]
    m.edges = [Edge(src="C1", verb="uses", dst="C2", why="reads",
                    where="backend/viewer.py#L20"),
               Edge(src="C2", verb="persists", dst="E1")]
    return m


# --- --id: resolve --------------------------------------------------------------

def test_resolve_component_uses_its_canonical_anchor():
    r = resolve_id(make_model(), "C1")
    assert r == {"id": "C1", "kind": "component", "name": "Viewer",
                 "source": "backend/viewer.py#L1", "members": []}


def test_resolve_component_lists_its_member_entry_points():
    r = resolve_id(make_model(), "C3")
    assert r is not None
    assert r["members"] == [{"trigger": "GET /orders", "source": "backend/api.py#L10"},
                            {"trigger": "orders.created", "source": "backend/sub.py#L3"}]


def test_resolve_group_lists_member_ids_and_link_href():
    r = resolve_id(make_model(), "S1")
    assert r is not None
    assert r["source"] == "backend/core/"
    assert r["members"] == ["C1", "C2", "S2"]  # components first, then child subsystems


def test_resolve_entity_anchors_at_its_source():
    r = resolve_id(make_model(), "E1")
    assert r is not None and r["source"] == "backend/order.py#L7" and r["kind"] == "entity"


def test_resolve_unknown_id_is_none():
    assert resolve_id(make_model(), "C99") is None


# --- --record --------------------------------------------------------------------

def test_record_is_the_full_stored_element():
    r = record_of(make_model(), "C2")
    assert r is not None
    assert r["subsystem"] == "S1"


# --- --edges ---------------------------------------------------------------------

def test_edges_slice_splits_in_and_out():
    e = edges_of(make_model(), "C2")
    assert [x["src"] for x in e["in"]] == ["C1"]
    assert [x["dst"] for x in e["out"]] == ["E1"]
    assert e["in"][0]["where"] == "backend/viewer.py#L20"


def test_edges_slice_of_an_unwired_node_is_empty():
    e = edges_of(make_model(), "C3")
    assert e == {"in": [], "out": []}


# --- --members -------------------------------------------------------------------

def test_members_returns_full_records_of_the_groups_children():
    ms = members_of(make_model(), "S1")
    assert [r["id"] for r in ms] == ["C1", "C2", "S2"]
    assert ms[0]["name"] == "Viewer"


def test_subdomain_members_are_its_entities():
    ms = members_of(make_model(), "SD1")
    assert [r["id"] for r in ms] == ["E1"]


# --- CLI -------------------------------------------------------------------------

def run_dump(args: list[str], model: ProjectModel | None = None) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "project-map.json"
        path.write_text(to_canonical_json(model or make_model()), encoding="utf-8")
        proc = subprocess.run(CLI + [str(path)] + args, capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr


def test_cli_whole_dump_is_the_canonical_json():
    code, out, _ = run_dump([])
    assert code == 0 and out == to_canonical_json(make_model())


def test_cli_id_slice_emits_json():
    code, out, _ = run_dump(["--id", "S1"])
    assert code == 0
    assert json.loads(out)["members"] == ["C1", "C2", "S2"]


def test_cli_unknown_id_fails_loudly():
    code, _, err = run_dump(["--id", "C99"])
    assert code == 1 and "C99" in err


def test_cli_members_of_a_non_group_is_a_usage_error():
    code, _, err = run_dump(["--members", "C1"])
    assert code == 2 and "subsystem" in err


def test_cli_rejects_two_slice_flags():
    code, _, err = run_dump(["--id", "C1", "--edges", "C1"])
    assert code == 2 and "ONE slice" in err


def test_main_reports_a_missing_map():
    assert main(["/nonexistent/project-map.json"]) == 1


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if failures else 0)


# --- --legend / --counts ---------------------------------------------------------
# The two views every build hand-wrote a `python -c` walk for: the shared id universe a fan-out
# needs, and "how big is this map?". One build produced the legend with a 25-line script in the
# same turn as a contract telling its agents "use `coyomap dump`, don't hand-parse it".


def test_legend_covers_every_element_kind_with_its_parent_and_source():
    from coyomap.dump import legend_of
    rows = legend_of(make_model())
    by_id = {r["id"]: r for r in rows}
    assert by_id["C1"] == {"id": "C1", "name": "Viewer", "kind": "component", "parent": "S1",
                           "source": "backend/viewer.py#L1"}
    assert by_id["E1"]["kind"] == "entity" and by_id["E1"]["parent"] == "SD1"
    assert by_id["S2"]["kind"] == "subsystem" and by_id["S2"]["parent"] == "S1"
    assert by_id["UC1"]["kind"] == "use_case"
    # A markdown-link source is reduced to its href, like every other dump slice.
    assert by_id["S1"]["source"] == "backend/core/"
    # ENTRY POINTS. Their ids are minted at assemble and exist in no fragment, so the map is their
    # only source — and this legend emitted 0 of them. A build with 108 entry points and 34 reconcile
    # rules assigning `entry_points` hand-parsed `project-map.json` to get the ids.
    assert by_id["EP1"] == {"id": "EP1", "name": "GET /orders", "kind": "entry_point",
                            "parent": "C3", "source": "backend/api.py#L10"}


def test_legend_emits_every_id_the_map_defines() -> None:
    """The legend is the shared id universe a fan-out is handed. A kind missing from it is a kind
    every sub-agent is blind to, and there is no second place to look mid-build."""
    from coyomap.dump import legend_of
    m = make_model()
    rows = legend_of(m)
    ids = {r["id"] for r in rows}
    for group in (m.components, m.deps, m.entities, m.subsystems, m.subdomains, m.use_cases,
                  m.subflows, m.roles, m.capabilities, m.blocks, m.rules, m.entry_points):
        for element in group:
            assert element.id in ids, f"{element.id} is defined in the map and absent from --legend"


def test_counts_covers_every_array_not_just_assembles_three():
    from coyomap.dump import counts_of
    counts = counts_of(make_model())
    assert counts["components"] == 3 and counts["entities"] == 1 and counts["edges"] >= 1
    # The point of the slice: arrays `assemble`'s C/D/E summary never mentions.
    assert "entry_points" in counts and counts["entry_points"] == 2
    assert "use_cases" in counts and "subsystems" in counts


def test_a_whole_map_slice_takes_no_id(capsys):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "map.json"
        p.write_text(to_canonical_json(make_model()), encoding="utf-8")
        assert main([str(p), "--counts"]) == 0
        assert json.loads(capsys.readouterr().out)["components"] == 3


def test_two_slice_flags_are_still_refused(capsys):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "map.json"
        p.write_text(to_canonical_json(make_model()), encoding="utf-8")
        assert main([str(p), "--counts", "--legend"]) == 2
        assert "at most ONE slice flag" in capsys.readouterr().err


# --- the reads that did not exist -------------------------------------------------
# A rules contract handed to eleven agents advertised `dump --id UC31   # a use case, with its flow
# steps and their anchors`. It answered `"members": []`, there was NO dump path to a flow at all,
# `--id SF200` said `"kind": "unknown"` about a sub-flow the map defines, and 0 of 311 entry points
# were addressable. Agents fell back to hand-parsing project-map.json with `python3 -c` — the exact
# thing "never hand-parse the map" forbids, made unavoidable by the reader.


def _model_with_a_flow() -> ProjectModel:
    from coyomap.model import Flow, FlowStep, SubFlow
    return ProjectModel(
        use_cases=[UseCase(id="UC1", name="Sign in")],
        flows=[Flow(uc="UC1", title="Sign in", steps=[
            FlowStep(n=1, src="R1", dst="C1", phrase="opens the page",
                     where="frontend/App.tsx:10"),
            FlowStep(n=2, src="C1", dst="C2", phrase="verifies the token",
                     where="backend/auth.py:42")])],
        subflows=[SubFlow(id="SF1", name="Resolve the caller", steps=[
            FlowStep(n=1, src="C3", dst="C4", phrase="looks the org up",
                     where="backend/org.py:7")])],
        entry_points=[EntryPoint(id="EP1", kind="http-route", component="C1",
                                 trigger="POST /login", source="backend/routes.py:5")],
    )


def resolved_members(got: dict[str, object]) -> list[dict[str, object]]:
    """`resolve_id` answers `dict[str, object]` because its values are ids, names, kinds and lists.
    Every caller here asked for an element that HAS members, so narrowing once beats an unchecked
    index at each use."""
    ms = got["members"]
    assert isinstance(ms, list), f"members is {ms!r}, not a list"
    return ms


def test_id_on_a_use_case_returns_its_flow_steps_with_anchors():
    got = resolve_id(_model_with_a_flow(), "UC1")
    assert got is not None and got["kind"] == "use_case"
    assert [s["n"] for s in resolved_members(got)] == [1, 2]
    assert resolved_members(got)[1]["where"] == "backend/auth.py:42"


def test_id_on_a_sub_flow_knows_its_kind_and_returns_its_steps():
    got = resolve_id(_model_with_a_flow(), "SF1")
    assert got is not None
    assert got["kind"] == "sub_flow"          # was "unknown": SF was missing from the prefix table
    assert [s["where"] for s in resolved_members(got)] == ["backend/org.py:7"]


def test_id_on_an_entry_point_resolves():
    """Entry points are minted by `assemble` and live outside ID_ARRAYS, so every EP id answered
    `not defined in the map` — in the reader whose job is to stop agents parsing the JSON."""
    got = resolve_id(_model_with_a_flow(), "EP1")
    assert got is not None
    assert got["kind"] == "entry_point"
    assert got["source"] == "backend/routes.py:5"
    assert got["members"] == [{"component": "C1", "kind": "http-route"}]


def test_id_on_an_unknown_entry_point_is_still_none():
    assert resolve_id(_model_with_a_flow(), "EP99") is None


def test_id_resolves_the_change_log_s_own_addresses():
    """`flow:UC6`, `step:UC6:3`, `rule:BR168:0`, `glossary:<term>`: the ids a change log names a
    flow, a step, an enforcement site and a keyed row by. A rehearsal wrote them into a log and
    `dump --id` answered "not defined in the map" for every one."""
    from coyomap.model import BusinessRule, GlossaryRow, RuleSite, RunRow
    m = _model_with_a_flow()
    m.rules = [BusinessRule(id="BR1", statement="A guard holds.", name="A guard",
                            sites=[RuleSite(where="backend/auth.py:50", why="refuses a stranger")])]
    m.glossary = [GlossaryRow(term="guild", meaning="a team", source="backend/org.py:1")]
    m.run_commands = [RunRow(action="serve", command="make serve", source="Makefile:3")]
    flow = resolve_id(m, "flow:UC1")
    assert flow is not None and flow["kind"] == "flow" and flow["name"] == "Sign in"
    assert [s["n"] for s in resolved_members(flow)] == [1, 2]
    step = resolve_id(m, "step:UC1:2")
    assert step is not None and step["kind"] == "flow_step" and step["source"] == "backend/auth.py:42"
    assert resolved_members(step)[0]["phrase"] == "verifies the token"
    sub = resolve_id(m, "step:SF1:1")
    assert sub is not None and sub["name"] == "looks the org up"
    site = resolve_id(m, "rule:BR1:0")
    assert site is not None and site["kind"] == "rule_site" and site["source"] == "backend/auth.py:50"
    assert resolved_members(site) == [{"where": "backend/auth.py:50", "why": "refuses a stranger", "no_call_site": False}]
    term = resolve_id(m, "glossary:guild")
    assert term is not None and term["kind"] == "glossary_term" and term["source"] == "backend/org.py:1"
    assert resolved_members(term)[0]["meaning"] == "a team"
    run = resolve_id(m, "run:serve")
    assert run is not None and run["kind"] == "run_command" and resolved_members(run)[0]["command"] == "make serve"
    for missing in ("flow:UC9", "step:UC1:9", "step:SF9:1", "rule:BR1:1", "rule:BR9:0", "glossary:nope", "run:nope", "bogus:x"):
        assert resolve_id(m, missing) is None and record_of(m, missing) is None, missing
    ep = record_of(m, "EP1")
    assert ep is not None and ep["id"] == "EP1" and ep["source"] == "backend/routes.py:5", "a way in's record, the shape a new one is written in"
    rec = record_of(m, "flow:UC1")
    assert rec is not None and rec["uc"] == "UC1" and [s["n"] for s in rec["steps"]] == [1, 2], "the row, verbatim"
    assert record_of(m, "rule:BR1:0") == {"where": "backend/auth.py:50", "why": "refuses a stranger", "no_call_site": False}


def test_a_use_case_with_no_flow_yet_has_no_members():
    m = ProjectModel(use_cases=[UseCase(id="UC9", name="Not traced yet")])
    got = resolve_id(m, "UC9")
    assert got is not None and got["members"] == []
