#!/usr/bin/env python3
"""Tests for `coyomap.validate_model` — the semantic checks over a model, including the
v2-only behaviors: the deployment_linked orphan-dep exemption, the non_entity_types under-harvest
marker, and the generated-view freshness check.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_validate_model.py
    pytest tests/test_validate_model.py
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import re
import tempfile
from pathlib import Path

from coyomap import grammar, lint_fragment, reporting
from coyomap import balance_lib as balance_lib_mod
from coyomap import validate_model as validate_model_mod
from coyomap.model import (
    Interface,
    ModelError,
    load_model,
    FORMAT,
    Grounding,
    Component,
    DeploymentRow,
    Dep,
    Edge,
    Entity,
    EntityField,
    EntityRelation,
    EntryPoint,
    EvidenceItem,
    Flow,
    FlowStep,
    GlossaryRow,
    HappyStep,
    Group,
    BusinessRule,
    ExtraSection,
    MessagingRow,
    NonEntityType,
    ProjectModel,
    Role,
    RoleRelation,
    RuleSite,
    SecurityRow,
    Stake,
    StoryAnchor,
    StateMachine,
    StateTransition,
    Store,
    SubFlow,
    UseCase,
    VariantTag,
    to_canonical_json,
)
from coyomap.validate_model import (
    INTERFACE_EXCEPTIONS_HEADING,
    NAMING_EXCEPTIONS_HEADING,
    _anchor_pairs,
    _inventory,
    _inheritance_runs_in_warnings,
    check_anchor_existence_model,
    check_domain_coverage_model,
    check_domain_relations,
    interface_actors,
    interface_steps_by_use_case,
    interface_directions,
    interface_walk_steps,
    validate_model,
    walk_jumps,
)
from coyomap.views import model_to_markdown


# --- builders -------------------------------------------------------------------

def make_entity(eid: str = "E1", name: str = "Order", source: str | None = "src/order.py:1",
                relations: list[EntityRelation] | None = None) -> Entity:
    return Entity(id=eid, name=name, store=Store(notes="orders"), meaning="a thing", source=source,
                  fields=[EntityField(name="id", type="str", markers=["PK"])],
                  relations=relations or [])


def make_valid_model() -> ProjectModel:
    m = ProjectModel(title="Demo", goal="A demo.")
    m.roles = [Role(id="R1", name="Andy", kind="human", wants="orders", drives="UC1")]
    m.use_cases = [UseCase(id="UC1", name="View order", actors=["R1"])]
    m.happy_path = [HappyStep(id="HP1", uc="UC1")]
    m.components = [Component(id="C1", name="Viewer", purpose="shows")]
    m.deps = [Dep(id="D1", name="Postgres", kind="datastore", type="SQL database")]
    m.entities = [make_entity()]
    m.flows = [Flow(uc="UC1", title="View order",
                    steps=[FlowStep(n=1, src="R1", dst="C1", phrase="opens")])]
    m.edges = [Edge(src="C1", verb="reads", dst="E1", why="show", where="src/v.py:5"),
               Edge(src="C1", verb="uses", dst="D1", why="query", where="src/v.py:7")]
    return m


def problems_of(m: ProjectModel) -> list[str]:
    problems, _ = validate_model(m)
    return problems


def warnings_of(m: ProjectModel) -> list[str]:
    _, warnings = validate_model(m)
    return warnings


# --- dependency purpose buckets ---------------------------------------------------

def test_bucket_cap_exceeded_is_advisory_not_gating() -> None:
    # More than the soft cap of distinct buckets among external systems -> an advisory warning, NOT a
    # gate (an integration-heavy product legitimately spans many purposes — e.g. mee6 needs 9).
    m = make_valid_model()
    m.deps = [Dep(id=f"D{i}", name=f"S{i}", kind="service", type="api", bucket=f"Bucket {i}")
              for i in range(grammar.DEP_BUCKET_CAP + 2)]
    assert any("Many purpose buckets among external systems" in w for w in warnings_of(m))
    assert not any("purpose buckets" in p for p in problems_of(m))



def test_entry_point_coverage_splits_the_two_arms_of_claiming():
    """"Reached by a use case" hides two different facts, and the loose one was invisible. A way in
    a use case NAMES is claimed on purpose; one reached only because a walk touches its owning
    component is claimed by a rule that cannot tell a real door from a sibling row in the same file.
    On a live map the loose half was the LARGE half. This is a number, never an advisory: the
    unclaimed check's signal is already thin, and the fix for coarseness is not more warnings."""
    from coyomap.model import Component, EntryPoint, Flow, FlowStep, ProjectModel, UseCase
    m = ProjectModel(title="T", goal="G")
    m.components = [Component(id="C1", name="Doors", purpose="p", source="a.py:1")]
    m.entry_points = [
        EntryPoint(id="EP1", kind="http-route", activation="external", component="C1",
                   trigger="named by the use case", source="a.py:1"),
        EntryPoint(id="EP2", kind="http-route", activation="external", component="C1",
                   trigger="covered only because C1 is touched", source="a.py:2"),
    ]
    m.use_cases = [UseCase(id="UC1", name="Do it", entry_points=["EP1"])]
    m.flows = [Flow(uc="UC1", title="Do it",
                    steps=[FlowStep(n=1, src="C1", dst="C1", phrase="does it")])]
    counts = validate_model_mod.completeness_counts(m)
    assert counts["entry_points_named_by_use_case"] == 1
    assert counts["entry_points_covered_by_component_only"] == 1
    assert counts["entry_points_unclaimed_external"] == 0
    line = validate_model_mod._entry_point_coverage_line(m)
    assert "2 external way(s) in" in line and "1 named by a use case" in line
    assert "1 reached only through the component a walk touches" in line
    # A row with no owning component belongs to neither arm — it has its own check — so it is
    # named as the remainder rather than swelling either half and breaking the arithmetic.
    m.entry_points.append(EntryPoint(id="EP3", kind="http-route", activation="external",
                                     component="", trigger="ownerless", source="a.py:3"))
    assert "1 with no owning component" in validate_model_mod._entry_point_coverage_line(m)
    # No externally activated way in: nothing to split, so the line stays off.
    assert validate_model_mod._entry_point_coverage_line(ProjectModel(title="T", goal="G")) == ""


def test_entry_point_coverage_counts_a_flow_step_at_the_way_ins_own_line():
    """The third bucket. The traversal arm is component-grain, so one flow through a component
    marks every way in it owns as covered — 87 of coyomap's own 97 the day this landed. A surface
    step carries the way in's own `source` line (method.md), so a step anchored within 3 lines of a
    way in is evidence a flow RUNS it: derived, at way-in grain, no new authored field. A number,
    not an advisory — it is the ruler any rule about drawing steps at ways in is judged with."""
    m = ProjectModel(title="T", goal="G")
    m.components = [Component(id="C1", name="Doors", purpose="p", source="a.py:1")]
    ep = lambda i, why, src: EntryPoint(id=f"EP{i}", kind="http-route", activation="external",
                                        component="C1", trigger=why, source=src)
    m.entry_points = [
        ep(1, "named, and a step sits on its line", "a.py:10"),
        ep(2, "run: a step 3 lines under its line", "a.py:20"),
        ep(3, "loose: the nearest step is 4 lines away", "a.py:30"),
        ep(4, "loose: same line number, other file", "b.py:40"),
        ep(5, "run: the step sits inside a sub-flow", "a.py:50"),
        ep(6, "named, no step anywhere near", "a.py:60"),
    ]
    m.use_cases = [UseCase(id="UC1", name="Do it", entry_points=["EP1", "EP6"])]
    m.subflows = [SubFlow(id="SF1", name="Shared", steps=[
        FlowStep(n=1, src="C1", dst="C1", phrase="shared", where="a.py:50")])]
    m.flows = [Flow(uc="UC1", title="Do it", steps=[
        FlowStep(n=1, src="C1", dst="C1", phrase="opens", where="a.py:10"),
        FlowStep(n=2, src="C1", dst="C1", phrase="handles", where="a.py:23"),
        FlowStep(n=3, src="C1", dst="C1", phrase="misses", where="a.py:34"),
        FlowStep(n=4, src="C1", dst="C1", phrase="elsewhere", where="a.py:40"),
        FlowStep(n=5, src="C1", dst="C1", subflow="SF1"),
    ])]
    assert validate_model_mod.step_anchored_entry_point_ids(m) == {"EP1", "EP2", "EP5"}
    counts = validate_model_mod.completeness_counts(m)
    assert counts["entry_points_named_by_use_case"] == 2
    assert counts["entry_points_named_without_step"] == 1          # EP6
    assert counts["entry_points_run_by_a_step"] == 2               # EP2, EP5
    assert counts["entry_points_stepped"] == 3                     # + EP1, named AND stepped
    assert counts["entry_points_covered_by_component_only"] == 2   # EP3, EP4
    assert counts["entry_points_unclaimed_external"] == 0
    line = validate_model_mod._entry_point_coverage_line(m)
    assert "6 external way(s) in" in line and "2 named by a use case" in line
    assert "2 run by a flow step at their own line" in line
    assert "2 reached only through the component a walk touches" in line and "0 unclaimed" in line
    # The tolerance is a parameter: at 0 only the exact-line step counts.
    assert validate_model_mod.step_anchored_entry_point_ids(m, tolerance=0) == {"EP1", "EP5"}


def make_storyless_model() -> ProjectModel:
    """Two interfaces, seven ways in: EP1 named by UC1, EP2 run by a step, EP3 and EP4 storyless on
    I1, EP5 storyless on I2, EP6 storyless in no interface, EP7 a middleware (a pipe, never
    listed). One component, touched by the flow, so the per-component arm sees nothing."""
    m = ProjectModel(title="T", goal="G")
    m.components = [Component(id="C1", name="Doors", purpose="p", source="a.py:1")]

    def ep(i: int, kind: str, why: str, src: str) -> EntryPoint:
        return EntryPoint(id=f"EP{i}", kind=kind, activation="external", component="C1",
                          trigger=why, source=src)
    m.entry_points = [
        ep(1, "http-route", "named by UC1", "a.py:10"),
        ep(2, "http-route", "run by a step", "a.py:20"),
        ep(3, "http-route", "storyless on I1", "a.py:30"),
        ep(4, "http-route", "storyless on I1 too", "a.py:40"),
        ep(5, "mcp-tool", "storyless on I2", "a.py:50"),
        ep(6, "http-route", "storyless, in no interface", "a.py:60"),
        ep(7, "middleware", "a pipe", "a.py:70"),
    ]
    m.interfaces = [
        Interface(id="I1", name="Dashboard", what="w", side="ours", facing="user",
                  ways_in=["EP1", "EP2", "EP3", "EP4"]),
        Interface(id="I2", name="Admin MCP", what="w", side="ours", facing="user", ways_in=["EP5"]),
    ]
    m.use_cases = [UseCase(id="UC1", name="Do it", entry_points=["EP1"])]
    m.flows = [Flow(uc="UC1", title="Do it", steps=[
        FlowStep(n=1, src="C1", dst="C1", phrase="handles", where="a.py:21")])]
    return m


def storyless_warnings(m: ProjectModel) -> list[str]:
    return [w for w in warnings_of(m) if "way(s) in have no story" in w]


def test_storyless_ways_in_warn_once_per_interface_and_honour_the_records():
    """The walk, checked. The component arm cannot see a skipped walk: one flow through a component
    marks every way in it owns as covered (87 of coyomap's own 97). So every way in NO use case
    names and NO flow step runs is listed, once per interface, and each is adjudicated by a use
    case or by a record — per way in (`EPn`), per surface (`In`), or per component (`Cn`, the
    line that already exists). A pipe (`middleware`) is never a door, and a way in the map already
    calls plumbing ('Interface exceptions') owes no story either."""
    m = make_storyless_model()
    assert {e.id for e in validate_model_mod.storyless_ways_in(m)} == {"EP3", "EP4", "EP5", "EP6"}
    assert validate_model_mod.completeness_counts(m)["entry_points_storyless"] == 4
    ws = storyless_warnings(m)
    assert len(ws) == 3, ws
    assert any(w.startswith("I1 (Dashboard): 2 of its 4 way(s) in have no story")
               and "EP3" in w and "EP4" in w for w in ws)
    assert any(w.startswith("I2 (Admin MCP): 1 of its 1 way(s) in have no story") for w in ws)
    assert any(w.startswith("In no interface: 1 way(s) in have no story") and "EP6" in w for w in ws)
    assert not any("EP7" in w or "EP1 " in w or "EP2 " in w for w in ws)
    # Records: one way in, one whole surface, and the plumbing heading.
    m.extras = [ExtraSection(heading="Unclaimed surfaces",
                             body="EP3: a dev-only page.\nI2: an ops surface, deliberate."),
                ExtraSection(heading="Interface exceptions", body="EP6: the health probe, plumbing.")]
    ws = storyless_warnings(m)
    assert len(ws) == 1 and ws[0].startswith("I1 (Dashboard): 1 of its 4") and "EP4" in ws[0], ws
    assert "EP3" not in ws[0]
    assert any("2 way(s) in with no story are suppressed" in w and "EP3" in w and "EP5" in w
               for w in warnings_of(m))
    # The per-component line that already exists still covers the ways in it owns.
    m.extras[0].body += "\nC1: the whole area is dev tooling."
    assert not storyless_warnings(m)
    # Additivity: an untraced map whose use cases name nothing has not walked yet — silence...
    m = make_storyless_model()
    m.flows = []
    m.use_cases[0].entry_points = []
    assert not storyless_warnings(m)
    # ...but the trigger arm ALONE lists the rest: the walk happens at synthesis, before any trace.
    m.use_cases[0].entry_points = ["EP1"]
    ws = storyless_warnings(m)
    assert any(w.startswith("I1 (Dashboard): 3 of its 4") and "EP2" in w for w in ws)
    # Needs interfaces: without them there is no "per surface" to list by.
    m = make_storyless_model()
    m.interfaces = []
    assert not storyless_warnings(m)


def test_validate_json_carries_the_coverage_counts_as_numbers():
    m = make_storyless_model()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "project-map.json"
        p.write_text(to_canonical_json(m), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            validate_model_mod.main(["--json", str(p)])
    d = json.loads(buf.getvalue())
    c = d["completeness"]
    assert c["entry_points_external"] == 7 and c["entry_points_named_by_use_case"] == 1
    assert c["entry_points_run_by_a_step"] == 1 and c["entry_points_storyless"] == 4
    assert "1 named by a use case" in d["entry_point_coverage"]


def test_emit_unclaimed_prints_the_storyless_ways_in_per_interface():
    m = make_storyless_model()
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "project-map.json"
        p.write_text(to_canonical_json(m), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = validate_model_mod.main(["--emit-unclaimed", str(p)])
    out = buf.getvalue()
    assert rc == 0, out
    assert "# I1 (Dashboard)" in out and "- EP3: <why>" in out and "- EP4: <why>" in out
    assert "# I2 (Admin MCP)" in out and "- EP5: <why>" in out
    assert "# in no interface" in out and "- EP6: <why>" in out
    assert "EP7" not in out and "EP1:" not in out and "EP2:" not in out


def test_bucket_non_seed_is_an_advisory_nudge_not_a_gate() -> None:
    m = make_valid_model()
    m.deps = [Dep(id="D1", name="Postgres", kind="datastore", type="SQL", bucket="Datastores")]
    assert not any("Datastores" in p for p in problems_of(m))                      # not gating
    assert any("Datastores" in w and "not a seed" in w for w in warnings_of(m))    # one nudge, aggregated


def test_bucket_seed_spelling_passes_clean() -> None:
    m = make_valid_model()
    m.deps = [Dep(id="D1", name="Postgres", kind="datastore", type="SQL", bucket="Data & storage")]
    assert not any("bucket" in w.lower() for w in warnings_of(m))


# --- entry-point kind vocabulary + per-kind coverage contract (WS-A8) -------------

def make_ep(kind: str = "http-route", trigger: str = "GET /x", activation: str = "",
            component: str = "C1") -> EntryPoint:
    return EntryPoint(kind=kind, trigger=trigger, source="src/v.py:1", component=component,
                      activation=activation)


def test_alias_kind_spelling_is_an_advisory_not_a_gate() -> None:
    # the observed real-map drift: `http` and `http-route` rows for the same thing.
    m = make_valid_model()
    m.entry_points = [make_ep(kind="http"), make_ep(kind="http", trigger="GET /y")]
    ws = warnings_of(m)
    assert any("'http'" in w and "http-route" in w and "2 row(s)" in w for w in ws)
    assert not any("drift spelling" in p for p in problems_of(m))    # seeded-open: never blocking


def test_seed_kind_is_silent_and_minted_kinds_nudge_one_aggregated_line() -> None:
    m = make_valid_model()
    m.entry_points = [make_ep(kind="webhook"),
                      make_ep(kind="gateway-loop", trigger="loop a"),
                      make_ep(kind="gateway-loop", trigger="loop b"),
                      make_ep(kind="generator-loop", trigger="gen")]
    minted = [w for w in warnings_of(m) if "minted" in w and "entry-point kind" in w]
    assert len(minted) == 1                                          # ONE line, not one per kind/row
    assert "'gateway-loop'" in minted[0] and "'generator-loop'" in minted[0]
    assert "'webhook'" not in minted[0]                              # seed spelling stays silent


def test_kind_coverage_contract_nudges_and_heading_silences() -> None:
    m = make_valid_model()
    m.entry_points = [make_ep(kind="http-route"), make_ep(kind="cli", trigger="cx")]
    assert any("Entry-point coverage" in w and "'cli'" in w and "'http-route'" in w
               for w in warnings_of(m))                              # one AGGREGATED line
    m.extras = [ExtraSection(
        heading="Entry-point coverage",
        body="http-route: complete — walked app.routes\ncli: sampled — main scripts only")]
    assert not any("Entry-point coverage: no completeness" in w for w in warnings_of(m))


def test_kind_coverage_line_folds_alias_spellings() -> None:
    # a contract written as `http` covers the `http-route` rows — both fold through canonical kind.
    m = make_valid_model()
    m.entry_points = [make_ep(kind="http-route")]
    m.extras = [ExtraSection(heading="Entry-point coverage", body="http: complete — walked routes")]
    assert not any("Entry-point coverage: no completeness" in w for w in warnings_of(m))


def test_kind_coverage_records_spaced_and_case_drifted_minted_kinds() -> None:
    # review #1/#4: a minted kind may contain spaces ("Mounted ASGI") and has no canonical case —
    # the contract line the advisory itself prescribes MUST be able to silence it.
    m = make_valid_model()
    m.entry_points = [make_ep(kind="Mounted ASGI"), make_ep(kind="gateway-loop", trigger="loop")]
    assert any("Entry-point coverage" in w for w in warnings_of(m))   # nudges before recording
    m.extras = [ExtraSection(
        heading="Entry-point coverage",
        body="Mounted ASGI: complete — enumerated the mounts\nGateway-loop: sampled — main loop only")]
    assert not any("Entry-point coverage: no completeness" in w for w in warnings_of(m))


def test_kind_coverage_reads_a_line_wrapped_in_markdown_markup() -> None:
    """A backtick around the identifier is as natural as bold, and it used to discard the record in
    silence: h7's three statements — ``- `ui-route: complete` — read every <Route> element`` and two
    siblings — parsed 0 of 3, the warning said only "no completeness statement", and the barrier
    answered by RE-RECORDING a second differently worded line. The shipped map carries two ui-route
    statements and no tool can read one of them."""
    m = make_valid_model()
    m.entry_points = [make_ep(kind="ui-route"), make_ep(kind="middleware", trigger="mw"),
                      make_ep(kind="startup-hook", trigger="boot")]
    assert any("Entry-point coverage" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Entry-point coverage", body=(
        "- `ui-route: complete` — read every <Route> element in the router\n"
        "- **middleware: complete** — one route-level gate\n"
        "- _startup-hook_: complete — second pass over main.tsx"))]
    assert not any("Entry-point coverage: no completeness" in w for w in warnings_of(m))


def test_kind_coverage_still_ignores_prose_that_merely_mentions_a_kind() -> None:
    """Widening the markup must not widen what counts as a RECORD. A sentence is not a contract."""
    m = make_valid_model()
    m.entry_points = [make_ep(kind="ui-route")]
    m.extras = [ExtraSection(heading="Entry-point coverage", body=(
        "Not counted as separate addresses: the two wrapper routes that only mount a frame.\n"
        "The `ui-route` rows were the complete set at the time of writing."))]
    assert any("Entry-point coverage: no completeness" in w for w in warnings_of(m))


# --- a recorded rationale the walk outgrew -----------------------------------------
# Every other check here asks whether a gap is RECORDED. Nothing asked whether the record is still
# TRUE. The 2026-08-20 argus map shipped `CAP8: … so only the version switch sits on the walk` while
# 0 of CAP8's 2 use cases appear in the walk — the version-switch step had been deleted three turns
# after the line was written, to clear an unrelated warning, and nothing re-read the sentence.

def _walk_model(record: str, keep_step: bool = True):
    m = make_valid_model()
    m.capabilities = [Group(id="CAP8", name="Demo target site", happy_path="excluded")]
    # UC1 comes from the base model and belongs to no CAP8 — it is what the walk falls back to when
    # the demo step is deleted, which is the shape the real map ended up in.
    m.use_cases = list(m.use_cases) + [
        UseCase(id="UC33", name="Visit the demo site", actors=["R1"],
                trigger="a visitor opens it", outcome="it renders", capability="CAP8"),
        UseCase(id="UC34", name="Switch the demo version", actors=["R1"],
                trigger="an admin picks one", outcome="it serves that one", capability="CAP8")]
    m.happy_path = ([HappyStep(id="HP1", uc="UC34")] if keep_step
                    else [HappyStep(id="HP1", uc="UC1")])
    m.extras = [ExtraSection(heading="Happy Path coverage", body=record)]
    return m


def test_a_capability_record_claiming_the_walk_is_checked_against_the_walk() -> None:
    m = _walk_model("CAP8: the demo exists so a demo has a page that changes, so only the version "
                    "switch sits on the walk", keep_step=False)
    assert any("sits on the walk, and 0 of its 2 use case(s) do" in w for w in warnings_of(m)), \
        warnings_of(m)


def test_the_same_record_is_silent_while_the_claim_is_still_true() -> None:
    m = _walk_model("CAP8: the demo exists so a demo has a page that changes, so only the version "
                    "switch sits on the walk", keep_step=True)
    assert not any("sits on the walk, and 0 of" in w for w in warnings_of(m)), warnings_of(m)


def test_an_ordinary_off_the_spine_rationale_is_not_flagged() -> None:
    """The heading's ordinary content is the OPPOSITE claim — "these are off the spine, and why" —
    and a check that fired on those would fire on every map and be ignored."""
    m = _walk_model("CAP8: the demo site is scaffolding for a demo, not product functionality",
                    keep_step=False)
    assert not any("sits on the walk" in w for w in warnings_of(m)), warnings_of(m)


def test_a_record_naming_a_walk_step_that_no_longer_exists_is_flagged() -> None:
    """Fully deterministic half: the walk lost HP18 and the line explaining HP18 stayed behind."""
    m = _walk_model("HP18: the version switch is what makes the demo worth showing", keep_step=True)
    assert any("records HP18, and the walk has no such step" in w for w in warnings_of(m)), \
        warnings_of(m)


# --- structured store + persistence coverage (WS-A1) ------------------------------

def test_store_dep_shape_and_mode_are_blocking() -> None:
    m = make_valid_model()
    m.entities = [Entity(id="E1", name="Order", meaning="a thing", source="src/order.py:1",
                         fields=[EntityField(name="id", type="str")],
                         store=Store(dep="Postgres", mode="Collection"))]
    ps = problems_of(m)
    assert any("store.dep 'Postgres' is not a D-id" in p for p in ps)
    assert any("store.mode 'Collection' is invalid" in p for p in ps)   # closed vocab, EXACT match


def test_store_dep_must_resolve_and_not_be_folded() -> None:
    m = make_valid_model()
    m.entities[0].store = Store(dep="D7", container="orders", mode="collection")
    assert any("D7" in p for p in problems_of(m))                       # dangling → _check_references
    m.entities[0].store = Store(dep="D1", container="orders", mode="collection")
    assert not any("store" in p.lower() for p in problems_of(m))        # resolves to a datastore dep
    m.deps = [Dep(id="D1", name="SQLAlchemy", kind="library", type="ORM library")]
    m.edges = [e for e in m.edges if e.dst != "D1"]  # drop the C→D edge; the folded dep is the point
    assert any("folded" in p and "E1" in p for p in problems_of(m))


def test_persistence_coverage_is_adoption_gated_fires_and_escapes() -> None:
    m = make_valid_model()
    # a write-family C→D edge into the datastore dep, with NO structured store anywhere → silent
    m.edges.append(Edge(src="C1", verb="persists", dst="D1", why="rows", where="src/v.py:9"))
    assert not any("no entity both records" in w for w in warnings_of(m))
    # adoption: E1 structures its store on D1, but C1's persists edge writes no entity → advisory
    m.entities[0].store = Store(dep="D1", container="orders", mode="collection")
    assert any("C1 persists into D1" in w and "Persistence exceptions" in w for w in warnings_of(m))
    # explaining pair: C1 also persists E1 (whose store is D1) → quiet
    m.edges.append(Edge(src="C1", verb="persists", dst="E1", why="rows", where="src/v.py:10"))
    assert not any("no entity both records" in w for w in warnings_of(m))
    # escape channel: the C id recorded under 'Persistence exceptions' silences it
    m.edges.pop()
    m.extras = [ExtraSection(heading="Persistence exceptions",
                             body="C1: lock rows only — infra, not domain")]
    assert not any("no entity both records" in w for w in warnings_of(m))


def test_container_without_dep_is_nudged_and_exempt_modes_stay_quiet() -> None:
    # Rebuild finding M-B5: two of three live rebuilds shipped `dep: null` on EVERY entity (the T5
    # agent had no deps legend), silently disabling the coverage rule. A named container in a
    # dep-linkable mode (collection/cache) with no dep now draws ONE aggregated nudge.
    m = make_valid_model()
    m.entities = [Entity(id="E1", name="A", meaning="x", source="src/a.py:1",
                         fields=[EntityField(name="id", type="str")],
                         store=Store(container="guilds", mode="collection")),
                  Entity(id="E2", name="B", meaning="x", source="src/b.py:1",
                         fields=[EntityField(name="id", type="str")],
                         store=Store(container="users", mode="embedded"))]   # embedded: exempt
    m.edges = [e for e in m.edges if not e.dst.startswith("E")]
    ws = [w for w in warnings_of(m) if "link no `dep`" in w]
    assert len(ws) == 1 and "1 entity store(s)" in ws[0] and "E1" in ws[0]
    m.extras = [ExtraSection(heading="Balance exceptions", body="store: dual-mode, dep ambiguous")]
    assert not any("link no `dep`" in w for w in warnings_of(m))


def test_persistence_coverage_adapter_hop_explains_layered_writes() -> None:
    # Rebuild finding: argus false positive — services own the entities, the ADAPTER carries the
    # physical writes edge. One write-family hop through the adapter now explains the pair.
    m = make_valid_model()
    m.components.append(Component(id="C30", name="Store adapter", purpose="mongo adapter"))
    m.entities[0].store = Store(dep="D1", container="orders", mode="collection")
    m.edges = [Edge(src="C1", verb="persists", dst="E1", why="owns", where="src/v.py:5"),
               Edge(src="C1", verb="persists", dst="C30", why="through adapter", where="src/v.py:6"),
               Edge(src="C30", verb="writes", dst="D1", why="documents", where="src/a.py:9")]
    assert not any("no entity both records" in w for w in warnings_of(m))
    # remove the service→adapter edge: the hop breaks and the pair is unexplained again
    m.edges = [e for e in m.edges if e.dst != "C30"]
    assert any("C30 writes into D1" in w for w in warnings_of(m))


def test_messaging_gap_canary_fires_and_escapes() -> None:
    # Rebuild finding: three builds shipped `messaging: []` while their edges showed a bus in use.
    m = make_valid_model()
    m.deps.append(Dep(id="D2", name="Redis broker", kind="messaging", type="queue broker"))
    m.edges.append(Edge(src="C1", verb="enqueues", dst="D2", why="jobs", where="src/v.py:8"))
    m.edges.append(Edge(src="C1", verb="listens-to", dst="D2", why="jobs", where="src/v.py:9"))
    ws = [w for w in warnings_of(m) if "`messaging` catalog is empty" in w]
    assert len(ws) == 1 and "2 emit/listen edge(s)" in ws[0]
    m.messaging = [MessagingRow(name="JOBS", kind="job-queue", broker="D2", publishers=["C1"],
                                consumers=["C1"], source="src/q.py:1")]
    assert not any("catalog is empty" in w for w in warnings_of(m))   # rows exist → quiet
    m.messaging = []
    m.extras = [ExtraSection(heading="Balance exceptions", body="messaging: no nameable channels")]
    assert not any("catalog is empty" in w for w in warnings_of(m))   # adjudicated → quiet


def test_isolated_component_canary_fires_and_escapes() -> None:
    # Live finding: a custom-shard fleet whose Purpose said it "pushes their events to the same
    # broker" carried no edge and no messaging role, so no view could draw the link it describes.
    m = make_valid_model()
    m.components.append(Component(id="C2", name="Custom shard fleet", purpose="pushes events to the "
                                  "same broker"))
    ws = [w for w in warnings_of(m) if "carry no backbone edge and no" in w]
    assert len(ws) == 1                                    # ONE aggregated line, not one per component
    assert "1 of 2 component(s)" in ws[0] and "C2 (Custom shard fleet)" in ws[0]
    # wiring it via a backbone edge quiets it...
    m.edges.append(Edge(src="C2", verb="emits", dst="D1", why="events", where="src/shard.go:9"))
    assert not any("carry no backbone edge and no" in w for w in warnings_of(m))
    # ...and so does recording it as a channel publisher (the other way a view can see it)
    m.edges = [e for e in m.edges if e.src != "C2"]
    m.messaging = [MessagingRow(name="shard.events", kind="queue", broker="D1", publishers=["C2"],
                                consumers=["C1"], source="src/shard.go:34")]
    assert not any("carry no backbone edge and no" in w for w in warnings_of(m))
    # ...and an adjudicated map stays quiet even while genuinely isolated
    m.messaging = []
    m.extras = [ExtraSection(heading="Balance exceptions", body="isolated: leaf plugins stand alone")]
    assert not any("carry no backbone edge and no" in w for w in warnings_of(m))


def test_isolated_component_canary_caps_the_inline_list() -> None:
    m = make_valid_model()
    for i in range(2, 14):
        m.components.append(Component(id=f"C{i}", name=f"Leaf {i}", purpose="p"))
    ws = [w for w in warnings_of(m) if "carry no backbone edge and no" in w]
    assert len(ws) == 1 and "12 of 13 component(s)" in ws[0]
    assert "+4 more" in ws[0]                              # 12 isolated, 8 shown inline
    assert "C13 (Leaf 13)" not in ws[0]


def test_roleless_nudge_exempts_folded_deps_and_knows_listen_verbs() -> None:
    m = make_valid_model()
    m.deps = [Dep(id="D1", name="FastAPI", kind="framework", type="web framework"),
              Dep(id="D2", name="Redis broker", kind="messaging", type="queue broker")]
    m.edges = [Edge(src="C1", verb="uses", dst="D1", why="serves", where="src/v.py:7"),      # folded
               Edge(src="C1", verb="listens-to", dst="D2", why="jobs", where="src/v.py:8")]  # role verb
    assert not any("name no role" in w for w in warnings_of(m))
    m.edges.append(Edge(src="C1", verb="uses", dst="D2", why="jobs", where="src/v.py:9"))    # roleless
    assert any("name no role" in w and "C1 uses D2" in w for w in warnings_of(m))


def test_unstructured_stores_draw_one_aggregated_nudge_with_store_literal_escape() -> None:
    m = make_valid_model()
    m.entities = [Entity(id="E1", name="A", meaning="x", source="src/a.py:1",
                         fields=[EntityField(name="id", type="str")],
                         store=Store(notes="mdb: a")),
                  Entity(id="E2", name="B", meaning="x", source="src/b.py:1",
                         fields=[EntityField(name="id", type="str")],
                         store=Store(notes="mdb: b"))]
    m.edges = [e for e in m.edges if not e.dst.startswith("E")]
    ws = [w for w in warnings_of(m) if "unstructured" in w]
    assert len(ws) == 1 and "2 entity store(s)" in ws[0]
    m.extras = [ExtraSection(heading="Balance exceptions", body="store: notes-only by choice")]
    after = warnings_of(m)
    # The DETAIL goes; the COUNT stays and names the group, because that one literal silences the
    # whole store family and a suppression nobody can see reads as "no findings".
    assert not any("2 entity store(s) are unstructured" in w for w in after)
    counts = [w for w in after if "store-hygiene advisory" in w]
    assert len(counts) == 1 and "unstructured (notes-only) stores" in counts[0]


def test_prose_container_is_nudged_and_descriptive_modes_stay_quiet() -> None:
    # A live map recorded `memberships subscriptions` where the code says
    # `__collection__ = "memberships_subscriptions"` — the agent DESCRIBED the compartment instead of
    # naming it, so the container can't lead a reader to the real collection. A space is the tell.
    m = make_valid_model()
    m.deps = [Dep(id="D1", name="Mongo", kind="datastore", type="document db")]
    m.entities = [
        Entity(id="E1", name="A", meaning="x", source="src/a.py:1",
               store=Store(dep="D1", container="memberships subscriptions", mode="collection")),
        Entity(id="E2", name="B", meaning="x", source="src/b.py:1",
               store=Store(dep="D1", container="memberships_plans", mode="collection")),   # a real name
        # `transient` legitimately DESCRIBES where a value comes from — never a container name.
        Entity(id="E3", name="C", meaning="x", source="src/c.py:1",
               store=Store(container="Chargebee API", mode="transient")),
    ]
    m.edges = [e for e in m.edges if not e.dst.startswith("E")]
    ws = [w for w in warnings_of(m) if "reads as prose" in w]
    assert len(ws) == 1 and "1 entity store(s)" in ws[0] and "E1" in ws[0]
    assert "E2" not in ws[0] and "E3" not in ws[0]
    m.extras = [ExtraSection(heading="Balance exceptions", body="store: names verified against code")]
    after = warnings_of(m)
    assert not any("1 entity store(s) name a container that reads as prose" in w for w in after)
    counts = [w for w in after if "store-hygiene advisory" in w]
    assert len(counts) == 1 and "reads as prose, not a name" in counts[0]


def test_the_store_literal_count_names_every_group_it_swallowed() -> None:
    # The reason this count exists: one record, written about one of the three store-hygiene
    # findings, silences all three. `runs-in` had the identical bug and the same remedy.
    m = make_valid_model()
    m.entities = [Entity(id="E1", name="A", meaning="x", source="src/a.py:1",
                         fields=[EntityField(name="id", type="str")],
                         store=Store(notes="mdb: a")),                       # unstructured
                  Entity(id="E2", name="B", meaning="x", source="src/b.py:1",
                         fields=[EntityField(name="id", type="str")],
                         # dep linked, so ONLY the prose-container group fires for this one
                         store=Store(dep="D1", container="rank card configs", mode="collection"))]
    m.edges = [e for e in m.edges if not e.dst.startswith("E")]
    assert len([w for w in warnings_of(m) if "store-hygiene advisory" in w]) == 0
    m.extras = [ExtraSection(heading="Balance exceptions", body="store: notes-only is deliberate")]
    counts = [w for w in warnings_of(m) if "store-hygiene advisory" in w]
    assert len(counts) == 1
    assert counts[0].startswith("2 store-hygiene advisory")
    assert "unstructured (notes-only) stores" in counts[0] and "reads as prose" in counts[0]


def test_the_store_literal_count_stays_quiet_when_it_silenced_nothing() -> None:
    # A record on a clean map must not manufacture a line — the count reports suppression, not the
    # existence of the record.
    m = make_valid_model()
    m.entities = [Entity(id="E1", name="A", meaning="x", source="src/a.py:1",
                         fields=[EntityField(name="id", type="str")],
                         store=Store(dep="D1", container="widgets", mode="collection"))]
    m.edges = [e for e in m.edges if not e.dst.startswith("E")]
    assert not any("store-hygiene advisory" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Balance exceptions", body="store: nothing to hide")]
    assert not any("store-hygiene advisory" in w for w in warnings_of(m))


# --- messaging catalog (WS-A5) -----------------------------------------------------

def make_msg(name: str = "JOB_QUEUE", broker: str = "D1", publishers: list[str] | None = None,
             consumers: list[str] | None = None) -> MessagingRow:
    return MessagingRow(name=name, kind="job-queue", broker=broker,
                        publishers=publishers if publishers is not None else ["C1"],
                        consumers=consumers if consumers is not None else ["C1"],
                        source="src/queues.py:3")


def test_messaging_shape_rules_block() -> None:
    m = make_valid_model()
    m.messaging = [make_msg(), make_msg(),                       # duplicate name
                   MessagingRow(name="X", broker="Redis", publishers=["worker"],
                                consumers=["C1"], payload="Order", source="see code")]
    ps = problems_of(m)
    assert any("Duplicate messaging channel name(s): JOB_QUEUE" in p for p in ps)
    assert any("broker 'Redis' is not a D-id" in p for p in ps)
    assert any("publisher 'worker' is not a C-id" in p for p in ps)
    assert any("payload 'Order' is not an E-id" in p for p in ps)
    assert any("messaging[2] ('X') source" in p and "not a valid" in p for p in ps)


def test_messaging_broker_resolution_and_backing_edge_advisories() -> None:
    m = make_valid_model()
    m.deps = [Dep(id="D1", name="Redis", kind="messaging", type="queue broker")]
    m.edges = [Edge(src="C1", verb="reads", dst="E1", why="show", where="src/v.py:5")]
    m.messaging = [make_msg()]                                   # C1 has no C→D1 edge
    ws = warnings_of(m)
    assert any("carry no backbone edge to D1" in w for w in ws)  # invisible to ripple/diagrams
    m.edges.append(Edge(src="C1", verb="enqueues", dst="D1", why="jobs", where="src/v.py:8"))
    assert not any("carry no backbone edge" in w for w in warnings_of(m))
    m.messaging[0].consumers = []
    assert any("no consumers recorded" in w for w in warnings_of(m))
    # a dangling broker id is blocking via _check_references
    m.messaging[0].broker = "D9"
    assert any("D9" in p for p in problems_of(m))


def test_messaging_folded_broker_blocks_and_service_broker_nudges() -> None:
    m = make_valid_model()
    m.deps = [Dep(id="D1", name="requests", kind="library", type="HTTP client library")]
    m.messaging = [make_msg()]
    assert any("folded" in p and "JOB_QUEUE" in p for p in problems_of(m))
    m.deps = [Dep(id="D1", name="Webhook svc", kind="service", type="external API")]
    m.edges.append(Edge(src="C1", verb="enqueues", dst="D1", why="jobs", where="src/v.py:8"))
    assert any("not messaging/datastore" in w for w in warnings_of(m))


# --- state machines (WS-A3) --------------------------------------------------------

def test_state_machine_endpoint_and_dup_rules_block() -> None:
    m = make_valid_model()
    m.entities[0].states = StateMachine(
        states=["draft", "draft", "sent"],
        transitions=[StateTransition(src="draft", dst="shipped", on="ship")],
        source="src/order.py:20")
    ps = problems_of(m)
    assert any("duplicate state name(s): draft" in p for p in ps)
    assert any("'shipped' is not a declared state" in p for p in ps)
    m.components[0].states = StateMachine(states=[], source="src/v.py:3")
    assert any("C1 states: empty state list" in p for p in problems_of(m))


def test_state_machine_inferred_source_and_isolated_state_are_advisory() -> None:
    m = make_valid_model()
    m.entities[0].states = StateMachine(
        states=["a", "b", "c"], transitions=[StateTransition(src="a", dst="b")])
    ws = warnings_of(m)
    assert any("cite no `source`" in w and "E1" in w for w in ws)
    assert any("no transition in or out: c" in w for w in ws)
    assert not any("states" in p for p in problems_of(m))            # both are advisory
    sm = m.entities[0].states
    assert sm is not None
    sm.source = "src/order.py:20"
    assert not any("cite no `source`" in w for w in warnings_of(m))
    assert any(label == "E1 states" and href == "src/order.py:20"
               for label, href in _anchor_pairs(m))                  # cited → --check-sources


# --- tech on subsystems (WS-A7) ---------------------------------------------------

def test_tech_on_subdomain_blocks_and_on_subsystem_is_clean() -> None:
    m = make_valid_model()
    m.subsystems = [Group(id="S1", name="Core", purpose="core", tech="Python/FastAPI",
                          tech_source="pyproject.toml:1")]
    m.components[0].subsystem = "S1"
    assert not any("tech" in p.lower() for p in problems_of(m))
    m.subdomains = [Group(id="SD1", name="Orders", purpose="orders", tech="Python")]
    m.entities[0].subdomain = "SD1"
    assert any("SD1" in p and "subsystem field" in p for p in problems_of(m))


# --- label on capabilities (plan/60-capabilities Step 1) --------------------------------

def test_happy_path_on_a_capability_is_clean_and_on_a_subsystem_blocks() -> None:
    """The mirror of the `tech` rule: one Group dataclass, four forests. `happy_path` asks whether
    the WALK must reach this, and only a capability is on the walk at all — a subsystem groups
    components, which the walk never visits."""
    m = make_valid_model()
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="orders", happy_path="expected")]
    m.use_cases[0].capability = "CAP1"
    assert not any("happy_path" in p.lower() for p in problems_of(m))
    m.subsystems = [Group(id="S1", name="Core", purpose="core", happy_path="excluded")]
    m.components[0].subsystem = "S1"
    assert any("S1" in p and "capability field" in p for p in problems_of(m))


def test_happy_path_outside_the_closed_vocabulary_blocks() -> None:
    m = make_valid_model()
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="orders", happy_path="core")]
    m.use_cases[0].capability = "CAP1"
    assert any("CAP1" in p and "unknown `happy_path`" in p for p in problems_of(m))


def test_a_stake_for_a_driving_actor_is_clean_and_on_a_subsystem_blocks() -> None:
    """`stakes` is the third capability-only field, policed like `happy_path` and `tech`: one Group
    dataclass, four forests."""
    m = make_valid_model()
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="orders", happy_path="expected",
                            stakes=[Stake(actor="R1", stake="orders and pays")])]
    m.use_cases[0].capability = "CAP1"
    assert not any("stake" in p.lower() for p in problems_of(m))
    assert not any("stake" in w.lower() for w in warnings_of(m))
    m.subsystems = [Group(id="S1", name="Core", purpose="core",
                          stakes=[Stake(actor="R1", stake="orders")])]
    m.components[0].subsystem = "S1"
    assert any("S1" in p and "capability field" in p for p in problems_of(m))


def test_a_stake_naming_an_undefined_role_blocks() -> None:
    m = make_valid_model()
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="orders", happy_path="expected",
                            stakes=[Stake(actor="R9", stake="orders")])]
    m.use_cases[0].capability = "CAP1"
    assert any("CAP1" in p and "R9" in p and "not a defined Role id" in p for p in problems_of(m))


def test_two_stakes_for_one_actor_block() -> None:
    """The arrow a stake labels can only carry one."""
    m = make_valid_model()
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="orders", happy_path="expected",
                            stakes=[Stake(actor="R1", stake="orders"),
                                    Stake(actor="R1", stake="pays")])]
    m.use_cases[0].capability = "CAP1"
    assert any("CAP1" in p and "two stakes" in p for p in problems_of(m))


def test_an_empty_stake_blocks_instead_of_counting_as_covered() -> None:
    """An entry with an actor and no text would satisfy the coverage advisory while the arrow still
    falls back to a use-case name — silencing a check while authoring nothing."""
    m = make_valid_model()
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="orders", happy_path="expected",
                            stakes=[Stake(actor="R1")])]
    m.use_cases[0].capability = "CAP1"
    assert any("CAP1" in p and "no text" in p for p in problems_of(m))


def test_a_stake_for_a_non_driving_actor_advises_as_dead_data() -> None:
    """A stake for a defined role that drives none of the capability's use cases labels an arrow
    the derivation never draws — it validates, renders nowhere, and reads as coverage."""
    m = make_valid_model()
    m.roles.append(Role(id="R2", name="Ghost", kind="human", audience="user", wants="w", drives=""))
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="orders", happy_path="expected",
                            stakes=[Stake(actor="R1", stake="orders and pays"),
                                    Stake(actor="R2", stake="haunts the page")])]
    m.use_cases[0].capability = "CAP1"
    assert any("CAP1" in w and "drive none" in w and "R2" in w for w in warnings_of(m))
    assert not any("stake" in p.lower() for p in problems_of(m))


def test_a_recorded_stake_exception_silences_only_that_capability() -> None:
    m = make_valid_model()
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="orders", happy_path="expected"),
                      Group(id="CAP2", name="Refunds", purpose="undoes", happy_path="excluded")]
    m.use_cases[0].capability = "CAP1"
    m.use_cases.append(UseCase(id="UC2", name="Refund", actors=["R1"], capability="CAP2"))
    assert any("CAP1" in w and "no stake entry" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Stake exceptions",
                             body="CAP1: the one use-case name is the honest label here")]
    assert not any("CAP1" in w and "no stake entry" in w for w in warnings_of(m))
    assert any("CAP2" in w and "no stake entry" in w for w in warnings_of(m))


def test_a_driving_actor_with_no_stake_advises_and_never_blocks() -> None:
    """The Features diagram labels each actor→feature arrow with the actor's stake; a missing one
    only degrades the label to a use-case name, so the check nudges rather than gates."""
    m = make_valid_model()
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="orders", happy_path="expected")]
    m.use_cases[0].capability = "CAP1"
    assert any("CAP1" in w and "no stake entry" in w and "R1" in w for w in warnings_of(m))
    assert not any("stake" in p.lower() for p in problems_of(m))


def test_tech_on_a_capability_blocks() -> None:
    """A capability groups use cases, so it has no stack — same argument as the subdomain."""
    m = make_valid_model()
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="orders", tech="Python")]
    m.use_cases[0].capability = "CAP1"
    assert any("CAP1" in p and "subsystem field" in p for p in problems_of(m))


def test_bad_tech_source_anchor_blocks_and_cited_joins_check_sources() -> None:
    m = make_valid_model()
    m.subsystems = [Group(id="S1", name="Core", purpose="core", tech="Go",
                          tech_source="see go.mod")]
    m.components[0].subsystem = "S1"
    assert any("S1 tech_source" in p and "not a valid" in p for p in problems_of(m))
    m.subsystems[0].tech_source = "go.mod:1"
    assert not any("S1 tech_source" in p for p in problems_of(m))
    assert any(label == "S1 tech" and href == "go.mod:1" for label, href in _anchor_pairs(m))


# --- entry-point cadence (WS-A2) --------------------------------------------------

def test_missing_cadence_on_self_ep_is_aggregated_and_literal_silences() -> None:
    m = make_valid_model()
    m.entry_points = [make_ep(kind="poller", trigger="poll twitch"),
                      make_ep(kind="job", trigger="prune data")]
    ws = [w for w in warnings_of(m) if "record no cadence" in w]
    assert len(ws) == 1 and "2 self-activated" in ws[0]              # one aggregated line
    m.extras = [ExtraSection(heading="Balance exceptions", body="cadence: all loops continuous")]
    assert not any("record no cadence" in w for w in warnings_of(m))


def test_cadence_literal_in_prose_does_not_silence() -> None:
    # review #2: `cadence` is an ordinary English word — a justification sentence merely USING it
    # ("its cadence lives in ops config") must not disable the family; only a line-leading record.
    m = make_valid_model()
    m.entry_points = [make_ep(kind="poller", trigger="poll twitch")]
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="C7: one worker on purpose — its cadence lives in ops config.")]
    assert any("record no cadence" in w for w in warnings_of(m))


def test_dangling_cadence_source_without_value_is_nudged() -> None:
    # review #7: an anchor that labels nothing.
    m = make_valid_model()
    ep = make_ep(kind="poller")
    ep.cadence_source = "src/beat.py:12"
    m.entry_points = [ep]
    assert any("records no `cadence`" in w for w in warnings_of(m))


def test_cadence_on_external_ep_is_a_contradiction_nudge() -> None:
    m = make_valid_model()
    ep = make_ep(kind="http-route")
    ep.cadence = "every 30s"
    m.entry_points = [ep]
    assert any("externally activated" in w and "cadence" in w for w in warnings_of(m))


def test_cadence_without_source_is_inferred_advisory_and_cited_is_clean() -> None:
    m = make_valid_model()
    ep = make_ep(kind="poller", trigger="poll twitch")
    ep.cadence = "every 30s"
    m.entry_points = [ep]
    assert any("cite no `cadence_source`" in w for w in warnings_of(m))
    ep.cadence_source = "src/poller.py:12"
    assert not any("cite no `cadence_source`" in w for w in warnings_of(m))
    assert not any("record no cadence" in w for w in warnings_of(m))  # cadence present → no missing nudge


def test_bad_cadence_source_anchor_blocks() -> None:
    m = make_valid_model()
    ep = make_ep(kind="poller")
    ep.cadence = "every 30s"
    ep.cadence_source = "see the config"                             # prose, not a bare anchor
    m.entry_points = [ep]
    assert any("cadence_source" in p and "not a valid" in p for p in problems_of(m))


def test_cited_cadence_source_joins_check_sources_pairs() -> None:
    m = make_valid_model()
    ep = make_ep(kind="poller")
    ep.cadence = "every 30s"
    ep.cadence_source = "src/poller.py:12"
    m.entry_points = [ep]
    assert any("cadence" in label and href == "src/poller.py:12"
               for label, href in _anchor_pairs(m))


# --- clean baseline ---------------------------------------------------------------

def test_valid_model_has_no_problems():
    assert problems_of(make_valid_model()) == []


# --- referential + shape -----------------------------------------------------------

def test_undefined_reference_is_flagged():
    m = make_valid_model()
    m.edges.append(Edge(src="C1", verb="uses", dst="C9"))
    assert any("undefined IDs" in p and "C9" in p for p in problems_of(m))


def test_stray_s_token_suppressed_without_grouping():
    m = make_valid_model()
    m.goal = "Files are stored in AWS S3 buckets."  # no subsystems defined → S3 must not flag
    assert problems_of(m) == []


def test_prose_id_token_is_not_a_reference():
    # An id-shaped token in PROSE (the PKCE value "S256", "AWS S3", a "D3" library) is a domain string,
    # not a cross-reference — even when grouping exists. The old whole-document scan false-positived here
    # (and a build once "fixed" it by corrupting "S256" to "S-256"); references now come only from typed
    # id fields + `[[ID]]` markers.
    m = make_valid_model()
    m.subsystems = [Group(id="S1", name="Core", purpose="all")]
    m.components[0].subsystem = "S1"
    m.goal = "Auth uses S256 (PKCE); files sit in AWS S3; charts use the D3 lib."
    assert not any("S256" in p or "S3" in p or "D3" in p for p in problems_of(m))


def test_bracket_marker_reference_is_resolved():
    # A deliberate in-prose cross-reference uses the `[[ID]]` marker, which IS resolved.
    m = make_valid_model()
    m.components[0].purpose = "Delegates to [[C9]] for the heavy lifting."
    assert any("undefined IDs" in p and "C9" in p for p in problems_of(m))


def test_empty_actors_blocks_when_roles_defined():
    # Loud guard (the anti-silent-no-op): with roles defined, a use case that names NO actor FAILS
    # validate — so the actor-attribution audit can never silently have nothing to compare.
    m = make_valid_model()
    m.use_cases[0].actors = []
    assert any("no actor" in p and "UC1" in p for p in problems_of(m))


def make_two_door_model() -> ProjectModel:
    """One use case, two actors, and a flow each of them OPENS — the shape the door check blocks."""
    m = make_valid_model()
    m.roles.append(Role(id="R2", name="Assistant", kind="service", wants="the same list",
                        drives="UC1"))
    m.use_cases[0].actors = ["R1", "R2"]
    m.flows[0].steps = [
        FlowStep(n=1, src="R1", dst="C1", phrase="opens the screen"),
        FlowStep(n=2, src="C1", dst="E1", phrase="reads the order", where="src/v.py:5"),
        FlowStep(n=3, src="R2", dst="C1", phrase="calls the tool"),
    ]
    return m


def test_two_actors_opening_one_flow_block():
    # Two front doors on one number line: step 3 does not follow step 2, it starts a second run.
    # The message must name BOTH openings, so the split is actionable without reading the flow.
    problems = problems_of(make_two_door_model())
    hit = [p for p in problems if "openings" in p and "UC1" in p]
    assert hit, problems
    assert "R1 (Andy) at step 1" in hit[0] and "R2 (Assistant) at step 3" in hit[0]


def test_interchangeable_actors_sharing_one_opening_are_clean():
    # The legitimate multi-actor case: either role may run it, and the flow has ONE opening — only
    # one of them ever appears as a step src. Nothing to split, so the check stays silent.
    m = make_two_door_model()
    m.flows[0].steps = m.flows[0].steps[:2]
    assert not any("openings" in p for p in problems_of(m))


def test_a_second_actor_that_only_RECEIVES_is_not_a_second_door():
    # Receiving the outcome is how a flow CLOSES, not how it opens. A door is a step the actor
    # drives, so an actor appearing only as a `dst` must never be read as a second opening.
    m = make_two_door_model()
    m.flows[0].steps[2] = FlowStep(n=3, src="C1", dst="R2", phrase="hands the list back")
    assert not any("openings" in p for p in problems_of(m))


def test_empty_actors_allowed_when_no_roles():
    # A roles-less map legitimately has no actors and no role-id references — the guard does not fire.
    m = make_valid_model()
    m.roles = []
    m.use_cases[0].actors = []
    m.flows[0].steps = [FlowStep(n=1, src="C1", dst="E1", phrase="reads",
                                 where="src/v.py:5")]  # no actor step / role ref
    assert not any("no actor" in p for p in problems_of(m))


def test_duplicate_ids_flagged():
    m = make_valid_model()
    m.components.append(Component(id="C1", name="Again"))
    assert any("Duplicate element definitions" in p and "C1" in p for p in problems_of(m))


def test_suffixed_pointer_is_flagged():
    m = make_valid_model()
    m.subsystems = [Group(id="S1", name="Core", purpose="all")]
    m.components[0].subsystem = "S12a"
    assert any("S12a" in p and "not a valid schema ID" in p for p in problems_of(m))


def test_hierarchy_cycle_and_wrong_kind_parent():
    m = make_valid_model()
    m.subsystems = [Group(id="S1", name="A", parent="S2"), Group(id="S2", name="B", parent="S1")]
    m.components[0].subsystem = "S1"
    probs = problems_of(m)
    assert any("cycle" in p.lower() for p in probs)
    m2 = make_valid_model()
    m2.subsystems = [Group(id="S1", name="A")]
    m2.subdomains = [Group(id="SD1", name="Dom")]
    m2.entities[0].subdomain = "SD1"
    m2.components[0].subsystem = "SD1"  # a component under a SUBDOMAIN is the wrong kind
    assert any("not a subsystem" in p for p in problems_of(m2))


# --- element checks ------------------------------------------------------------------

def test_gp_step_without_uc_is_flagged():
    m = make_valid_model()
    m.happy_path[0].uc = None
    assert any("Happy Path steps missing" in p for p in problems_of(m))


def test_unknown_flow_actor_is_flagged():
    m = make_valid_model()
    m.flows[0].steps[0].src = "Zoe"
    assert any("actor 'Zoe' is not a defined Role" in p for p in problems_of(m))


def test_duplicate_flow_per_use_case_is_flagged():
    m = make_valid_model()
    m.flows.append(Flow(uc="UC1", title="Again", steps=[]))
    assert any("more than one T6 flow" in p for p in problems_of(m))


def test_flow_step_without_action_text_is_flagged():
    # Every step must carry its own action text; it is no longer derived from the backbone edge.
    m = make_valid_model()
    m.flows[0].steps[0].phrase = ""
    assert any("has no action text" in p for p in problems_of(m))


def test_invalid_dep_kind_is_flagged():
    m = make_valid_model()
    m.deps[0].kind = "databaze"
    assert any("invalid dependency Kind" in p for p in problems_of(m))


def test_empty_edge_verb_is_flagged():
    m = make_valid_model()
    m.edges[0].verb = "  "
    assert any("empty Verb" in p for p in problems_of(m))


def test_edge_where_prose_is_a_blocking_problem():
    # A present-but-malformed `where` (prose, not a `path:line`) is blocked by the anchor-format gate.
    m = make_valid_model()
    m.edges[0].where = "somewhere in the code"
    assert any("where" in p and "not a valid" in p for p in problems_of(m))


def test_extensionless_file_anchor_is_valid():
    # An extensionless ops file carrying a line (`Dockerfile:1`, `Makefile:6-9`) is a valid file anchor —
    # file-ness is not decided by "has a dot". Format must not reject these real run/build anchors.
    for anchor in ("Dockerfile:1", "Makefile:6-9"):
        m = make_valid_model()
        m.edges[0].where = anchor
        assert not any("not a valid" in p and "where" in p.lower() for p in problems_of(m)), anchor


def test_edge_missing_where_is_a_blocking_problem():
    # An edge's `where` is its witness (an EXAMPLE call site grounding the claim) — still required.
    m = make_valid_model()
    m.edges[0].where = None
    assert any("no `Where` anchor" in p and "EXAMPLE call site" in p for p in problems_of(m))


def test_edge_no_call_site_opt_out_allows_missing_where():
    # The explicit opt-out for a genuinely decoupled edge clears the missing-`where` block.
    m = make_valid_model()
    m.edges[0].where = None
    m.edges[0].no_call_site = True
    assert not any("no `Where` anchor" in p for p in problems_of(m))


# --- containers are not edge endpoints --------------------------------------------

def make_promoted_model(endpoint: str, side: str = "dst") -> ProjectModel:
    """A map mid-PROMOTION: a component became a subsystem and one edge still points at the
    container. This is the exact state `method/change-impact.md`'s promotion recipe produces when a
    re-point is missed, and the recipe promises validation catches it."""
    m = make_valid_model()
    m.subsystems = [Group(id="S1", name="Billing", purpose="charges")]
    m.subdomains = [Group(id="SD1", name="Orders", purpose="ordering")]
    m.components[0].subsystem = "S1"
    setattr(m.edges[1], side, endpoint)
    return m


def test_an_edge_pointing_at_a_subsystem_is_a_blocking_problem():
    m = make_promoted_model("S1")
    assert any("cannot be an edge endpoint" in p and "S1" in p for p in problems_of(m))


def test_an_edge_pointing_at_a_subdomain_is_a_blocking_problem():
    m = make_promoted_model("SD1")
    assert any("cannot be an edge endpoint" in p and "SD1" in p for p in problems_of(m))


def test_a_container_as_the_SOURCE_of_an_edge_is_caught_too():
    # Both ends, not just the one the promotion recipe happens to describe.
    m = make_promoted_model("S1", side="src")
    assert any("cannot be an edge endpoint" in p for p in problems_of(m))


def test_ordinary_endpoints_are_not_mistaken_for_containers():
    # The guard is the ID SHAPE, so nothing that merely starts with an S-ish letter is swept in — and
    # C/D/E endpoints, which is every real edge, stay silent.
    m = make_valid_model()
    assert not any("cannot be an edge endpoint" in p for p in problems_of(m))


# --- flow-step anchors (`where` is THE location — one step, one call site) ---------


def make_element_step_flow() -> Flow:
    # An element↔element step with its own precise call site — the shape the anchor rules target.
    return Flow(uc="UC1", title="View order",
                steps=[FlowStep(n=1, src="C1", dst="E1", phrase="reads", where="src/v.py:5")])


def test_element_step_missing_where_is_a_blocking_problem():
    m = make_valid_model()
    m.flows = [make_element_step_flow()]
    m.flows[0].steps[0].where = None
    assert any("UC1 flow step 1" in p and "no `where` call-site anchor" in p for p in problems_of(m))


def test_element_step_no_call_site_opt_out_allows_missing_where():
    m = make_valid_model()
    m.flows = [make_element_step_flow()]
    m.flows[0].steps[0].where = None
    m.flows[0].steps[0].no_call_site = True
    assert not any("no `where` call-site anchor" in p for p in problems_of(m))


def test_actor_step_needs_no_where():
    # An actor step (a Role endpoint) is a human action — no call site is demanded.
    m = make_valid_model()  # its only step is R1 → C1 with no `where`
    assert not any("no `where` call-site anchor" in p for p in problems_of(m))


def test_step_where_prose_is_a_blocking_problem():
    # A present-but-malformed step `where` is blocked by the anchor-format gate, like every anchor.
    m = make_valid_model()
    m.flows = [make_element_step_flow()]
    m.flows[0].steps[0].where = "somewhere in the code"
    assert any("flow step 1 where" in p and "not a valid" in p for p in problems_of(m))


def test_step_where_with_no_call_site_is_a_warning():
    # Contradictory intent (`where` + `no_call_site`) is advisory, mirroring the edge rule.
    m = make_valid_model()
    m.flows = [make_element_step_flow()]
    m.flows[0].steps[0].no_call_site = True
    assert any("`no_call_site` is set but a `where` is present" in w for w in warnings_of(m))


def test_duplicate_step_n_is_a_blocking_problem():
    # `step:<uc>:<n>` is the impact engine's synthetic id — `n` must be unique within a flow.
    m = make_valid_model()
    m.flows = [Flow(uc="UC1", title="View order",
                    steps=[FlowStep(n=1, src="C1", dst="E1", phrase="reads", where="src/v.py:5"),
                           FlowStep(n=1, src="C1", dst="D1", phrase="queries", where="src/v.py:7")])]
    assert any("duplicate step number 1" in p for p in problems_of(m))


# --- sub-flows (named shared step sequences) ----------------------------------------


def make_subflow(sid: str = "SF1") -> SubFlow:
    return SubFlow(id=sid, name="Persist the order",
                   steps=[FlowStep(n=1, src="C1", dst="E1", phrase="writes", where="src/v.py:5"),
                          FlowStep(n=2, src="C1", dst="D1", phrase="notifies", where="src/v.py:7")])


def make_ref_step(n: int = 2) -> FlowStep:
    return FlowStep(n=n, src="C1", dst="D1", subflow="SF1")


def make_model_with_subflow() -> ProjectModel:
    # two flows referencing SF1, so the <2-references advisory stays quiet
    m = make_valid_model()
    m.use_cases.append(UseCase(id="UC2", name="Audit order", actors=["R1"]))
    m.subflows = [make_subflow()]
    m.flows = [Flow(uc="UC1", title="View order",
                    steps=[FlowStep(n=1, src="R1", dst="C1", phrase="opens"), make_ref_step()]),
               Flow(uc="UC2", title="Audit order",
                    steps=[FlowStep(n=1, src="R1", dst="C1", phrase="asks"), make_ref_step()])]
    return m


def test_subflow_model_is_clean():
    assert problems_of(make_model_with_subflow()) == []


def test_unresolved_subflow_reference_is_flagged():
    m = make_model_with_subflow()
    m.flows[0].steps[1].subflow = "SF9"
    assert any("undefined sub-flow 'SF9'" in p for p in problems_of(m))


def test_nested_subflow_reference_is_flagged():
    m = make_model_with_subflow()
    m.subflows[0].steps[0].subflow = "SF1"
    assert any("may not reference a sub-flow" in p for p in problems_of(m))


def test_reference_step_with_own_where_is_flagged():
    m = make_model_with_subflow()
    m.flows[0].steps[1].where = "src/v.py:9"
    assert any("carries no location of its own" in p for p in problems_of(m))


def test_reference_step_phrase_is_optional():
    # already empty in make_ref_step — the phrase-required rule must not fire on a reference
    assert not any("no action text" in p for p in problems_of(make_model_with_subflow()))


def test_subflow_steps_obey_step_rules():
    # a sub-flow's element↔element step without `where` blocks, exactly like a flow's step
    m = make_model_with_subflow()
    m.subflows[0].steps[0].where = None
    assert any("SF1 step 1" in p and "no `where` call-site anchor" in p for p in problems_of(m))
    m2 = make_model_with_subflow()
    m2.subflows[0].steps[0].where = "prose, not an anchor"
    assert any("SF1 step 1 where" in p and "not a valid" in p for p in problems_of(m2))


def test_subflow_step_dangling_endpoint_is_flagged():
    # sub-flow steps are ordinary steps — a dangling element endpoint must resolve like a flow's
    m = make_model_with_subflow()
    m.subflows[0].steps[0].dst = "C99"
    assert any("undefined IDs" in p and "C99" in p for p in problems_of(m))


def test_dangling_subflow_prose_ref_is_never_suppressed():
    # `[[SF9]]` in prose dangles even when the map has no grouping (the S-family additivity
    # suppression must not swallow SF refs)
    m = make_valid_model()
    m.components[0].purpose = "Runs the shared sequence [[SF9]] on every write."
    assert any("undefined IDs" in p and "SF9" in p for p in problems_of(m))


def test_empty_flow_warns_under_band():
    m = make_valid_model()
    m.flows[0].steps = []
    assert any("only 0 step(s)" in w for w in warnings_of(m))


def test_subflow_referenced_once_is_an_advisory():
    m = make_model_with_subflow()
    m.flows[1].steps = [FlowStep(n=1, src="R1", dst="C1", phrase="asks")]  # drop UC2's reference
    assert any("referenced 1 time(s)" in w for w in warnings_of(m))
    assert not any("referenced 1 time" in w for w in warnings_of(make_model_with_subflow()))


def test_subflow_refcount_stays_off_the_blocking_fragment_channel():
    # Rebuild finding M-B2: the refcount nudge is judgment-shaped AND per-fragment blind (the other
    # reference may live in a sibling fragment) — it must ride lint's ADVISORY channel, never fail
    # a fragment. Also: two references inside ONE flow count as reuse (steps, not distinct flows).
    m = make_model_with_subflow()
    m.flows[1].steps = [FlowStep(n=1, src="R1", dst="C1", phrase="asks")]  # SF1 now referenced once
    assert not any("referenced" in p for p in lint_fragment.lint_fragment_problems(m, None))
    assert any("referenced 1 time(s)" in w for w in lint_fragment.lint_fragment_warnings(m))
    # two step-references in one flow = reuse → quiet (the old wording counted steps but said flows)
    m2 = make_model_with_subflow()
    m2.flows[1].steps = [FlowStep(n=1, src="C1", dst="C1", subflow="SF1"),
                         FlowStep(n=2, src="C1", dst="C1", subflow="SF1")]
    assert not any("referenced" in w for w in warnings_of(m2))


def test_cross_fragment_subflow_ref_passes_lint_with_known_ids():
    # Rebuild finding M-B3: a step may legitimately reference a SIBLING fragment's sub-flow; with
    # an --ids universe that knows the SF id, the undefined-sub-flow problem must not fire (without
    # one, an invented SF still dies in the authoring agent's turn).
    m = make_valid_model()
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="C1", subflow="SF10"))
    assert any("undefined sub-flow 'SF10'" in p
               for p in lint_fragment.lint_fragment_problems(m, None))
    assert not any("undefined sub-flow" in p
                   for p in lint_fragment.lint_fragment_problems(m, None, {"SF10"}))
    assert any("undefined sub-flow 'SF10'" in p
               for p in lint_fragment.lint_fragment_problems(m, None, {"SF99"}))


# --- granularity advisories (band, fused names, literal duplication) ----------------


def make_long_flow(n_steps: int, uc: str = "UC1") -> Flow:
    return Flow(uc=uc, title="View order",
                steps=[FlowStep(n=i, src="C1", dst="E1", phrase=f"does thing {i}",
                                where=f"src/v.py:{i}") for i in range(1, n_steps + 1)])


def test_flow_over_band_warns_and_exception_silences():
    m = make_valid_model()
    m.flows = [make_long_flow(16)]
    assert any("16 steps" in w and "band" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="UC1: OAuth is protocol-imposed; one goal, wire grain kept.")]
    assert not any("16 steps" in w for w in warnings_of(m))


def test_under_band_flow_warns():
    m = make_valid_model()  # its only flow has 1 step
    assert any("only 1 step(s)" in w for w in warnings_of(m))


def test_under_band_flow_names_its_escape_and_the_record_silences_it():
    # The OVER-band half always named the escape; the under-band half asked a question ("is the
    # flow traced to its outcome?") an operator could answer only by ignoring the line forever.
    m = make_valid_model()
    assert any("only 1 step(s)" in w and "Balance exceptions" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="UC1: a one-hop read; the outcome IS the read.")]
    assert not any("only 1 step(s)" in w for w in warnings_of(m))
    # an unrelated id under the same heading leaves it firing
    m.extras = [ExtraSection(heading="Balance exceptions", body="UC9: some other flow.")]
    assert any("only 1 step(s)" in w for w in warnings_of(m))


def test_fused_use_case_name_warns():
    m = make_valid_model()
    m.use_cases[0].name = "Sign in and create an organization"
    assert any("joins two clauses with 'and'" in w for w in warnings_of(m))


def test_fused_name_is_silenced_by_the_elements_own_recorded_exception():
    # "Split it, rename it, or ignore knowingly" offered no record, and rewording prose to dodge a
    # heuristic is exactly what the exceptions mechanism exists to prevent.
    m = make_valid_model()
    m.use_cases[0].name = "Sign in and create an organization"
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="UC1: the signup flow really is one goal for this product.")]
    assert not any("joins two clauses with 'and'" in w for w in warnings_of(m))
    # a DIFFERENT element's record does not cross-silence this one
    m.subflows = [SubFlow(id="SF1", name="Fetch and cache the profile",
                          steps=[FlowStep(n=1, src="C1", dst="E1", phrase="reads",
                                          where="src/v.py:2")])]
    ws = warnings_of(m)
    assert any("SF1 name" in w and "joins two clauses" in w for w in ws)
    assert not any("UC1 name" in w for w in ws)


def test_a_recorded_id_reports_which_granularity_signals_it_swallowed():
    """Adversarial finding F7. `SF20: three steps is the whole session handshake` is a BAND why,
    and on a live map it also removed an unrelated fused-goal NAME warning with nothing on screen
    to say so. One id still exempts the whole family (both signals read one question about one
    element) — but the suppression is now visible and names the signal, so an operator can tell
    what the record actually bought."""
    m = make_valid_model()
    m.subflows = [SubFlow(id="SF20", name="Open the session and discover the catalog",
                          steps=[FlowStep(n=i, src="C1", dst="E1", phrase=f"s{i}",
                                          where=f"src/v.py:{i}") for i in range(1, 4)])]
    assert any("SF20 name" in w and "joins two clauses" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="SF20: three steps is the whole session handshake.")]
    ws = warnings_of(m)
    assert not any("SF20 name" in w and "joins two clauses" in w for w in ws)   # still exempt
    hits = [w for w in ws if "granularity advisory/advisories suppressed" in w]
    assert len(hits) == 1, ws
    assert "SF20 (the fused-goal name smell)" in hits[0]
    assert "extras heading" in hits[0]         # the line says how to re-read what it hid


def test_the_granularity_messages_say_the_record_covers_the_whole_family():
    """The escape's SCOPE has to be on screen where the decision is made, not only in method.md."""
    m = make_valid_model()                      # UC1's only flow has 1 step → under-band
    m.use_cases[0].name = "Sign in and create an organization"
    band = [w for w in warnings_of(m) if "only 1 step(s)" in w]
    name = [w for w in warnings_of(m) if "joins two clauses" in w]
    assert len(band) == 1 and len(name) == 1
    for w in band + name:
        assert "WHOLE granularity family" in w, w


def test_the_granularity_count_stays_quiet_when_the_record_silenced_nothing():
    """A recorded id whose element trips no granularity signal must not print a suppression line —
    the record self-clears once the flow is fixed."""
    m = make_valid_model()
    m.flows = [make_long_flow(6)]               # inside the band, name has no ' and '
    m.extras = [ExtraSection(heading="Balance exceptions", body="UC1: adjudicated long ago.")]
    assert not any("granularity advisory/advisories suppressed" in w for w in warnings_of(m))


def test_shared_run_detector_finds_literal_duplication():
    m = make_valid_model()
    m.use_cases.append(UseCase(id="UC2", name="Audit order", actors=["R1"]))
    shared = [FlowStep(n=i, src="C1", dst=("E1" if i % 2 else "D1"), phrase=f"s{i}",
                       where=f"src/v.py:{i}") for i in range(1, 5)]  # 4 identical hops
    m.flows = [Flow(uc="UC1", title="a", steps=shared),
               Flow(uc="UC2", title="b",
                    steps=[FlowStep(n=0, src="R1", dst="C1", phrase="opens"), *shared])]
    assert any("share a run of 4 identical steps" in w for w in warnings_of(m))


def test_shared_run_with_different_wheres_is_quiet():
    # endpoint-only matching called "stores X" and "loads Y" duplicates (seen on a live map) —
    # steps are identical only when src, dst AND grounding match
    m = make_valid_model()
    m.use_cases.append(UseCase(id="UC2", name="Audit order", actors=["R1"]))
    mk = lambda base: [FlowStep(n=i, src="C1", dst=("E1" if i % 2 else "D1"), phrase=f"s{i}",
                                where=f"src/{base}.py:{i}") for i in range(1, 5)]
    m.flows = [Flow(uc="UC1", title="a", steps=mk("a")),
               Flow(uc="UC2", title="b", steps=mk("b"))]  # same endpoints, different call sites
    assert not any("identical steps" in w for w in warnings_of(m))


def test_shared_run_through_actor_step_is_quiet():
    # a run containing an actor step is unextractable by rule (sub-flows can't hold actor
    # endpoints) — "extract a sub-flow" would be impossible advice, so the run must not report
    m = make_valid_model()
    m.use_cases.append(UseCase(id="UC2", name="Audit order", actors=["R1"]))
    shared = [FlowStep(n=1, src="R1", dst="C1", phrase="asks"),
              FlowStep(n=2, src="C1", dst="E1", phrase="reads", where="src/v.py:2"),
              FlowStep(n=3, src="R1", dst="C1", phrase="asks again"),
              FlowStep(n=4, src="C1", dst="D1", phrase="queries", where="src/v.py:4")]
    m.flows = [Flow(uc="UC1", title="a", steps=list(shared)),
               Flow(uc="UC2", title="b", steps=list(shared))]  # identical, but actor-interleaved
    assert not any("identical steps" in w for w in warnings_of(m))


def test_accepted_duplication_heading_silences_the_pair():
    m = make_valid_model()
    m.use_cases.append(UseCase(id="UC2", name="Audit order", actors=["R1"]))
    shared = [FlowStep(n=i, src="C1", dst=("E1" if i % 2 else "D1"), phrase=f"s{i}",
                       where=f"src/v.py:{i}") for i in range(1, 5)]
    m.flows = [Flow(uc="UC1", title="a", steps=shared),
               Flow(uc="UC2", title="b", steps=list(shared))]
    assert any("identical steps" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Accepted duplications",
                             body="UC1 & UC2: the UI-kickoff prefix is deliberate, not machinery.")]
    assert not any("identical steps" in w for w in warnings_of(m))


def test_altitude_nudge_silenced_by_component_exception():
    m = make_valid_model()
    m.components[0].purpose = "ports, adapters, stores, loaders, mappers, codecs"  # 6 bare sub-units
    assert any("consider promoting C1" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="C1: a legitimate family roster, not hidden subsystems.")]
    assert not any("consider promoting C1" in w for w in warnings_of(m))


def test_short_shared_run_is_quiet():
    m = make_valid_model()
    m.use_cases.append(UseCase(id="UC2", name="Audit order", actors=["R1"]))
    shared = [FlowStep(n=i, src="C1", dst=("E1" if i % 2 else "D1"), phrase=f"s{i}",
                       where=f"src/v.py:{i}") for i in range(1, 4)]  # only 3 hops
    m.flows = [Flow(uc="UC1", title="a", steps=shared),
               Flow(uc="UC2", title="b", steps=list(shared))]
    assert not any("identical steps" in w for w in warnings_of(m))


# --- use-case & Happy-Path completeness (front-door verification's teeth) -----------


def make_entry_point(component: str = "C1", activation: str = "external",
                     kind: str = "http", trigger: str = "GET /orders") -> EntryPoint:
    return EntryPoint(kind=kind, trigger=trigger, source="src/v.py:1",
                      component=component, activation=activation)


def test_claimed_external_entry_point_is_quiet():
    m = make_valid_model()  # its flow's step R1 → C1 claims C1
    m.entry_points = [make_entry_point("C1")]
    assert not any("unclaimed" in w for w in warnings_of(m))


def test_unclaimed_external_entry_point_warns_grouped_per_component():
    m = make_valid_model()
    m.components.append(Component(id="C2", name="Debug routes", purpose="ops"))
    m.entry_points = [make_entry_point("C2", trigger="GET /debug/a"),
                      make_entry_point("C2", trigger="GET /debug/b")]
    hits = [w for w in warnings_of(m) if "unclaimed by any use case" in w]
    assert len(hits) == 1  # grouped per component, not per entry point
    assert "C2" in hits[0] and "2 externally-activated" in hits[0]
    assert "/debug/a" in hits[0] and "/debug/b" in hits[0]


def test_self_activated_entry_point_is_exempt():
    m = make_valid_model()
    m.components.append(Component(id="C2", name="Worker", purpose="background"))
    m.entry_points = [make_entry_point("C2", activation="self", kind="background loop",
                                       trigger="interval tick")]
    assert not any("unclaimed" in w for w in warnings_of(m))


def test_invalid_activation_falls_back_to_kind_inference():
    # A truthy near-miss ('mounted' on an http-ish kind) must not silently exempt the row — the
    # effective activation comes from the kind heuristic, so the coverage check still sees it.
    m = make_valid_model()
    m.components.append(Component(id="C2", name="Demo mount", purpose="demo"))
    m.entry_points = [make_entry_point("C2", activation="mounted", kind="http")]
    assert any("unclaimed" in w and "C2" in w for w in warnings_of(m))
    assert any("invalid activation 'mounted'" in p for p in problems_of(m))  # and it BLOCKS


def test_component_claimed_only_via_subflow_is_quiet():
    m = make_valid_model()
    m.components.append(Component(id="C2", name="OAuth dance", purpose="auth"))
    m.subflows = [SubFlow(id="SF1", name="OAuth dance",
                          steps=[FlowStep(n=1, src="C1", dst="C2", phrase="redirects",
                                          where="src/v.py:9")])]
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="C1", subflow="SF1"))
    m.entry_points = [make_entry_point("C2", trigger="GET /oauth/callback")]
    assert not any("unclaimed" in w for w in warnings_of(m))


def test_unclaimed_surfaces_heading_silences_the_component_but_the_debt_keeps_counting():
    """The record retires the PER-COMPONENT advisory and leaves a disclosure naming what it
    silenced. Full silence was the old behaviour and it hid real debt: one build recorded, in its
    own words, "C455: a REAL GAP" and "C192: a genuine customer capability with fourteen live
    surfaces and no use case behind it", after which `validate` reported `unclaimed: 0`. The
    honesty was real; the mechanism could not tell justified non-coverage from acknowledged debt.
    'Sweep debt' already discloses its suppressions this way."""
    m = make_valid_model()
    m.components.append(Component(id="C2", name="Debug routes", purpose="ops"))
    m.entry_points = [make_entry_point("C2", trigger="GET /debug")]
    assert any("unclaimed by any use case" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Unclaimed surfaces",
                             body="C2: superadmin debug surface — deliberate, no use case.")]
    after = warnings_of(m)
    assert not any("unclaimed by any use case" in w for w in after), (
        "the per-component advisory must be retired by the record")
    debt = [w for w in after if "counted as CLAIMED" in w]
    assert debt and "C2" in debt[0], f"the silenced component must stay visible as debt: {after}"


def test_unclaimed_surfaces_record_is_read_from_line_starts_only():
    # Prose that merely MENTIONS a component id mid-sentence, or a sentence that STARTS with the
    # id but runs on with no separator, must not silence it — only a line-leading `Cn: <why>`
    # record counts (live 'Happy Path coverage' bodies carry such prose).
    m = make_valid_model()
    m.components.append(Component(id="C2", name="Debug routes", purpose="ops"))
    m.entry_points = [make_entry_point("C2", trigger="GET /debug")]
    for prose in ("The debug router (see C2) is under review.",
                  "C2 is under review.",           # line-leading but separator-less prose
                  "* C2 mentioned in passing"):
        m.extras = [ExtraSection(heading="Unclaimed surfaces", body=prose)]
        assert any("unclaimed" in w and "C2" in w for w in warnings_of(m)), prose


def test_hp_coverage_record_paren_form_is_read():
    # The tolerated record shape a live map already uses: "UCn (its name) — why", no colon.
    m = make_valid_model()
    m.use_cases.append(UseCase(id="UC2", name="Side flow", actors=["R1"]))
    m.flows.append(Flow(uc="UC2", title="Side",
                        steps=[FlowStep(n=1, src="R1", dst="C1", phrase="opens")]))
    m.extras = [ExtraSection(heading="Happy Path coverage",
                             body="UC2 (Side flow) is intentionally off the spine — demo ops.")]
    assert not any("off the Happy-Path spine" in w for w in warnings_of(m))


def test_external_entry_point_with_no_component_warns():
    m = make_valid_model()
    m.entry_points = [make_entry_point(component="  ", trigger="GET /orphan")]
    assert any("owned by no component" in w for w in warnings_of(m))


def test_entry_surface_check_is_silent_without_flows():
    # Additivity: an untraced map is "not yet traced", not "all unclaimed".
    m = make_valid_model()
    m.flows = []
    m.components.append(Component(id="C2", name="Debug routes", purpose="ops"))
    m.entry_points = [make_entry_point("C2", trigger="GET /debug")]
    assert not any("unclaimed" in w for w in warnings_of(m))


def test_use_case_without_flow_warns_once_tracing_began():
    m = make_valid_model()
    m.use_cases.append(UseCase(id="UC2", name="Ghost feature", actors=["R1"]))
    m.happy_path.append(HappyStep(id="HP2", uc="UC2"))  # on-spine, still untraced
    assert any("UC2" in w and "has no T6 flow" in w for w in warnings_of(m))
    m.flows = []  # no tracing yet → the phantom signal stays quiet for every use case
    assert not any("has no T6 flow" in w for w in warnings_of(m))


def test_role_driving_nothing_warns_unless_it_lives_in_a_flow():
    m = make_valid_model()
    m.roles.append(Role(id="R2", name="Approver", kind="human", wants="", drives=""))
    assert any("R2" in w and "drives no use case and appears in no flow" in w
               for w in warnings_of(m))
    # a role can legitimately live mid-flow only (an approver) without driving any use case
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="R2", phrase="notifies"))
    assert not any("drives no use case and appears in no flow" in w for w in warnings_of(m))


def test_role_with_no_on_spine_use_case_warns_and_record_silences():
    m = make_valid_model()
    m.roles.append(Role(id="R2", name="Operator", kind="human", wants="", drives="UC2"))
    m.use_cases.append(UseCase(id="UC2", name="Step into an org", actors=["R2"]))
    m.flows.append(Flow(uc="UC2", title="Step in",
                        steps=[FlowStep(n=1, src="R2", dst="C1", phrase="enters")]))
    warns = warnings_of(m)
    assert any("R2" in w and "drives no on-spine use case" in w for w in warns)
    assert any("UC2" in w and "off the Happy-Path spine and unrecorded" in w for w in warns)
    m.extras = [ExtraSection(heading="Happy Path coverage",
                             body="R2: ops-only role, off the walk by design.\n"
                                  "UC2: demo-operations side flow, not the product walk.")]
    warns = warnings_of(m)
    assert not any("drives no on-spine use case" in w for w in warns)
    assert not any("off the Happy-Path spine" in w for w in warns)


def test_hp_coverage_checks_are_silent_without_a_happy_path():
    m = make_valid_model()
    m.happy_path = []
    m.use_cases.append(UseCase(id="UC2", name="Side flow", actors=["R1"]))
    m.flows.append(Flow(uc="UC2", title="Side",
                        steps=[FlowStep(n=1, src="R1", dst="C1", phrase="opens")]))
    warns = warnings_of(m)
    assert not any("off the Happy-Path spine" in w for w in warns)
    assert not any("on-spine use case" in w for w in warns)


# --- entity-in-flows completeness (the canary + the unbacked-entity-step advisory) ---


def test_entity_flow_canary_fires_and_escape_silences():
    m = make_valid_model()  # has entities + a flow, but no entity step
    assert any("No flow step touches any entity" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="entity-flows: pure orchestration layer, no domain reads/writes.")]
    assert not any("No flow step touches any entity" in w for w in warnings_of(m))


def test_entity_step_silences_the_canary():
    m = make_valid_model()
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="E1", phrase="reads the order",
                                     where="src/v.py:5"))  # rides the C1 reads E1 edge
    warns = warnings_of(m)
    assert not any("No flow step touches any entity" in w for w in warns)
    assert not any("claims entity use" in w for w in warns)  # edge-backed → quiet


def test_entity_step_only_in_subflow_silences_the_canary():
    m = make_valid_model()
    m.subflows = [SubFlow(id="SF1", name="Persist pipeline",
                          steps=[FlowStep(n=1, src="C1", dst="E1", phrase="writes",
                                          where="src/v.py:5")])]
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="C1", subflow="SF1"))
    assert not any("No flow step touches any entity" in w for w in warnings_of(m))


def test_canary_is_silent_without_entities_or_without_flows():
    m = make_valid_model()
    m.entities = []
    m.edges = [e for e in m.edges if not e.dst.startswith("E")]
    assert not any("No flow step touches any entity" in w for w in warnings_of(m))
    m = make_valid_model()
    m.flows = []
    assert not any("No flow step touches any entity" in w for w in warnings_of(m))


def test_unbacked_entity_step_warns():
    m = make_valid_model()
    m.edges = [Edge(src="C1", verb="uses", dst="D1", why="query", where="src/v.py:7")]
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="E1", phrase="reads the order",
                                     where="src/v.py:5"))  # no C1↔E1 edge backs it now
    assert any("UC1 flow step 2" in w and "claims entity use the backbone doesn't" in w
               for w in warnings_of(m))


def test_return_direction_entity_step_matches_the_edge_undirected():
    m = make_valid_model()  # C1 reads E1 edge present
    m.flows[0].steps.append(FlowStep(n=2, src="E1", dst="C1", phrase="returns the loaded order",
                                     no_call_site=True))
    assert not any("claims entity use" in w for w in warnings_of(m))


def test_display_name_actor_step_is_not_flagged_as_unbacked():
    # A roles-less map may use Role DISPLAY NAMES as actor endpoints ("End user → C1") — an actor
    # name starting with E (End user, Engineer) must not read as an entity endpoint.
    m = make_valid_model()
    m.roles = []
    m.use_cases[0].actors = []
    m.flows[0].steps = [FlowStep(n=1, src="End user", dst="C1", phrase="opens the order")]
    assert not any("claims entity use" in w for w in warnings_of(m))


def test_cc_step_without_edge_is_not_flagged_as_unbacked():
    # C↔C return-direction steps legitimately match no backbone edge — only C+E pairs are checked.
    m = make_valid_model()
    m.components.append(Component(id="C2", name="Helper", purpose="helps"))
    m.flows[0].steps.append(FlowStep(n=2, src="C2", dst="C1", phrase="returns the result",
                                     no_call_site=True))
    assert not any("claims entity use" in w for w in warnings_of(m))


def test_entity_step_still_demands_a_where():
    # guard: the element↔element `where` rule applies to C→E steps unchanged
    m = make_valid_model()
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="E1", phrase="reads the order"))
    assert any("UC1 flow step 2" in p and "no `where` call-site anchor" in p
               for p in problems_of(m))


# --- entry-point row validity (activation vocabulary + owning-component reference) ---


def test_valid_and_empty_activations_are_clean():
    m = make_valid_model()
    m.entry_points = [make_entry_point("C1", activation="external"),
                      make_entry_point("C1", activation="self", kind="cron"),
                      make_entry_point("C1", activation="")]
    assert not any("activation" in p for p in problems_of(m))


def test_near_miss_activation_is_a_blocking_problem():
    # 'External' would silently reroute through the kind heuristic in every consumer — blocked,
    # EXACT match (unlike the case-folded dep-Kind check).
    m = make_valid_model()
    m.entry_points = [make_entry_point("C1", activation="External")]
    assert any("invalid activation 'External'" in p for p in problems_of(m))


def test_dangling_entry_point_component_is_flagged():
    m = make_valid_model()
    m.entry_points = [make_entry_point("C9")]
    assert any("undefined IDs" in p and "C9" in p for p in problems_of(m))


def test_entry_point_component_must_be_a_c_id():
    m = make_valid_model()
    m.subsystems = [Group(id="S1", name="Core", purpose="all")]
    m.components[0].subsystem = "S1"
    m.entry_points = [make_entry_point("S1")]
    assert any("component 'S1' is not a C id" in p for p in problems_of(m))


def test_empty_entry_point_component_is_not_a_shape_problem():
    m = make_valid_model()
    m.entry_points = [make_entry_point(component="")]
    assert not any("is not a C id" in p or "undefined IDs" in p for p in problems_of(m))


def test_padded_entry_point_component_is_a_shape_problem():
    # ' C1' resolves under the strip-tolerant semantic checks but detaches in the viewer (exact
    # string keying) and violates the published `^C\d+$` schema — the padding itself is the error.
    m = make_valid_model()
    m.entry_points = [make_entry_point(component="C1 ")]
    assert any("component 'C1 ' is not a C id" in p for p in problems_of(m))


def test_edge_no_call_site_with_where_warns():
    # Claiming no call site while also giving one is contradictory — advisory.
    m = make_valid_model()
    m.edges[0].no_call_site = True  # edges[0].where is a valid anchor from make_valid_model
    assert any("no_call_site` is set but a `Where` is present" in w for w in warnings_of(m))


def test_domain_card_completeness_and_relations():
    m = make_valid_model()
    m.entities = [Entity(id="E1", name="Order",
                         relations=[EntityRelation(verb="owns", target="E1"),
                                    EntityRelation(verb="has", target="E1",
                                                   src_card="1", dst_card=None)])]
    probs = problems_of(m)
    assert any("missing a MEANING" in p for p in probs)
    assert any("missing a SOURCE" in p for p in probs)
    assert any("has no FIELDS" in p for p in probs)
    assert any("non-canonical alias" in p for p in probs)          # owns → contains
    assert any("half-stated cardinality" in p for p in probs)


# --- the cardinality vocabulary is closed ------------------------------------------

def make_carded_model(src_card: str, dst_card: str = "1") -> ProjectModel:
    m = make_valid_model()
    m.entities = [make_entity(relations=[EntityRelation(verb="refersTo", target="E1",
                                                        src_card=src_card, dst_card=dst_card)])]
    return m


def test_every_published_cardinality_token_is_accepted():
    # The four `method/domain-cards.md` publishes. If enforcement and documentation ever disagree,
    # this is the side that must not move silently.
    for token in ("1", "*", "0..1", "1..*"):
        assert not any("unknown" in p and "cardinality" in p
                       for p in problems_of(make_carded_model(token))), token


def test_an_invented_cardinality_token_is_a_blocking_problem():
    # `many→ONE` parsed, validated clean and reached the class diagram, where a reader cannot tell an
    # author's private notation from the map's.
    probs = problems_of(make_carded_model("many", "ONE"))
    assert any("unknown src cardinality 'many'" in p for p in probs)
    assert any("unknown dst cardinality 'ONE'" in p for p in probs)


def test_a_near_miss_cardinality_is_still_rejected():
    # `0..n` and `0..*` look like the vocabulary and are not in it — the case a substring test misses.
    for token in ("0..n", "0..*", "n"):
        assert any("unknown src cardinality" in p for p in problems_of(make_carded_model(token))), token


def test_stating_neither_side_stays_clean():
    # The vocabulary applies to a STATED cardinality; omitting the pair entirely is legal.
    m = make_valid_model()
    m.entities = [make_entity(relations=[EntityRelation(verb="refersTo", target="E1")])]
    assert not any("cardinality" in p for p in problems_of(m))


def make_keyed_relation(keyed_by: list[str], verb: str = "attachedTo") -> EntityRelation:
    return EntityRelation(verb=verb, target="E2", src_card="*", dst_card="1", keyed_by=keyed_by)


def test_keyed_by_alone_is_clean_and_quiets_fieldless_nudge():
    # a field-less association whose key lives in `keyed_by` (not a `{how}` note) must NOT trip the
    # "not backed by a field and has no note" warning, and must raise no problems.
    m = make_valid_model()
    m.entities = [make_entity("E1", "Order", relations=[make_keyed_relation(["parent_id"])]),
                  make_entity("E2", "Parent")]
    assert not any("keyed_by" in p for p in problems_of(m))
    assert not any("not backed by a field" in w for w in warnings_of(m))


def test_keyed_by_naming_a_declared_source_field_is_rejected():
    # the key IS a plain (unmarked) field on the source row → it's a foreign key, not a storage key.
    # This is the `Membership.role` misuse class the FK-marker XOR rule alone would miss.
    e1 = Entity(id="E1", name="Membership", store=Store(notes="x"), meaning="a thing", source="src/o.py:1",
                fields=[EntityField(name="id", type="str", markers=["PK"]),
                        EntityField(name="role", type="string", markers=[])],
                relations=[EntityRelation(verb="assignedRole", target="E2", src_card="*",
                                          dst_card="1", keyed_by=["role"])])
    m = make_valid_model()
    m.entities = [e1, make_entity("E2", "RoleDefinition")]
    assert any("which is a declared field" in p and "role" in p for p in problems_of(m))


def test_keyed_by_naming_a_declared_target_field_is_rejected():
    # the key matches a field on the TARGET row → a reverse FK; still not a storage key.
    e2 = Entity(id="E2", name="Child", store=Store(notes="x"), meaning="a thing", source="src/c.py:1",
                fields=[EntityField(name="id", type="str", markers=["PK"]),
                        EntityField(name="parent_id", type="str", markers=[])])
    m = make_valid_model()
    m.entities = [make_entity("E1", "Parent", relations=[make_keyed_relation(["parent_id"], "has")]),
                  e2]
    assert any("which is a declared field" in p for p in problems_of(m))


def test_keyed_by_with_differently_named_backing_fk_is_rejected():
    # a real FK field (a DIFFERENT name than the key) backs the relation → the XOR rule catches it.
    e1 = Entity(id="E1", name="Order", store=Store(notes="orders"), meaning="a thing", source="src/o.py:1",
                fields=[EntityField(name="id", type="str", markers=["PK"]),
                        EntityField(name="parent", type="E2", markers=[])],   # typed by the target
                relations=[make_keyed_relation(["some_store_key"])])
    m = make_valid_model()
    m.entities = [e1, make_entity("E2", "Parent")]
    assert any("already backs it" in p and "keyed_by" in p for p in problems_of(m))


def test_keyed_by_empty_entry_is_rejected():
    m = make_valid_model()
    m.entities = [make_entity("E1", "Order", relations=[make_keyed_relation([" "])]),
                  make_entity("E2", "Parent")]
    assert any("empty `keyed_by` entry" in p for p in problems_of(m))


def test_validate_warns_on_duplicate_edges_with_differing_anchors():
    # After assemble's exact-dedup, a remaining (src,verb,dst) duplicate differs in where/why — a real
    # conflict the lead must reconcile; validate names it (non-blocking warning).
    m = make_valid_model()
    m.edges = [Edge(src="C1", verb="uses", dst="D1", why="q", where="a.py:3"),
               Edge(src="C1", verb="uses", dst="D1", why="q", where="a.py:9")]
    assert any("declared 2 times" in w for w in warnings_of(m))


def make_fk_heuristic_entities() -> list[Entity]:
    # a field-less association whose {how} note names a plain source field (the role→RoleDefinition
    # class): no FK marker, no keyed_by — a by-name FK hidden behind prose.
    e1 = make_entity("E1", "Membership")
    e1.fields.append(EntityField(name="role", type="string", markers=[]))
    e1.relations.append(EntityRelation(verb="grantsRole", target="E2", src_card="*", dst_card="1",
                                        how="role string names a RoleDefinition key"))
    return [e1, make_entity("E2", "RoleDefinition")]


def test_fk_heuristic_warns_when_note_names_a_source_field():
    m = make_valid_model()
    m.entities = make_fk_heuristic_entities()
    assert any("FK→E2" in w and "role" in w for w in warnings_of(m))
    assert not any("FK→E2" in p for p in problems_of(m))    # a warning, never a blocking problem


def test_fk_heuristic_guard_skips_when_target_absent():
    # at lint a fragment may hold the source but not the FK target — the r.target-in-backing guard
    # must keep the heuristic from false-firing on an entity-typed relation resolved cross-fragment.
    src_only = [make_fk_heuristic_entities()[0]]        # E1 only, no E2
    _problems, warnings = check_domain_relations(src_only)
    assert not any("FK→" in w for w in warnings)


def test_deployment_linked_dep_that_is_a_call_target_warns():
    m = make_valid_model()
    m.deps[0].deployment_linked = True                  # D1 marked deploy-only …
    m.edges = [Edge(src="C1", verb="uses", dst="D1", why="q", where="a.py:3")]  # … but is a call target
    assert any("deployment_linked" in w and "call target" in w for w in warnings_of(m))


def test_security_anchor_is_collected_for_existence_check():
    m = make_valid_model()
    m.security = [SecurityRow(surface="/admin", who="admin",
                              source="[require_admin](backend/auth.py#L70)")]
    pairs = _anchor_pairs(m)
    assert any(lbl.startswith("security") and href == "backend/auth.py#L70" for lbl, href in pairs)


# --- v2-only behaviors ----------------------------------------------------------------

def test_orphan_dep_warns_unless_deployment_linked():
    m = make_valid_model()
    m.deps.append(Dep(id="D2", name="nginx", kind="platform", type="reverse proxy"))
    assert any("D2" in w and "no incoming edge" in w for w in warnings_of(m))
    m.deps[1].deployment_linked = True
    assert not any("D2" in w and "no incoming edge" in w for w in warnings_of(m))


def test_non_entity_marker_quiets_under_harvest():
    with tempfile.TemporaryDirectory() as td:
        domain = Path(td) / "domain"
        domain.mkdir()
        classes = "\n\n".join(f"class Thing{i}:\n    pass" for i in range(12))
        (domain / "things.py").write_text(classes, encoding="utf-8")
        (domain / "order.py").write_text("class Order:\n    pass\n", encoding="utf-8")
        m = make_valid_model()
        m.entities = [make_entity(source="domain/order.py:1")]
        roots = [Path(td)]
        warnings = check_domain_coverage_model(m, roots)
        assert any("Under-harvested" in w for w in warnings)
        m.non_entity_types = [NonEntityType(name=f"Thing{i}", why="generated plumbing")
                              for i in range(12)]
        assert not any("Under-harvested" in w for w in check_domain_coverage_model(m, roots))


def make_flat_domain_model() -> ProjectModel:
    """Six entity cards, none of which relates to another — the isolated-entities shape."""
    m = make_valid_model()
    m.entities = [make_entity(eid=f"E{i}", name=f"Thing{i}", source=None) for i in range(1, 7)]
    m.edges = [e for e in m.edges if not e.dst.startswith("E")]
    m.flows = []
    return m


def test_isolated_entities_advisory_is_recordable_with_the_entity_relations_literal():
    # "Did one T5 harvest agent author per-entity RELATIONS?" is a question, and a map whose domain
    # really is flat (an event log, a settings bag) had no way to answer it.
    m = make_flat_domain_model()
    ws = check_domain_coverage_model(m, [])
    assert any("Isolated entities" in w and "entity-relations" in w for w in ws)
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="entity-relations: an event log; the cards are genuinely flat.")]
    assert not any("Isolated entities" in w for w in check_domain_coverage_model(m, []))
    # a neighbouring literal about COMPONENTS standing alone must not silence the ENTITY side
    m.extras = [ExtraSection(heading="Balance exceptions", body="isolated: leaf plugins.")]
    assert any("Isolated entities" in w for w in check_domain_coverage_model(m, []))


def make_unowned_entity_model() -> ProjectModel:
    """One entity a component writes and one nothing writes — the trap-P1 shape."""
    m = make_valid_model()
    m.entities = [make_entity(eid="E1", name="Order"), make_entity(eid="E2", name="Snapshot")]
    m.edges = [Edge(src="C1", verb="persists", dst="E1", why="owns", where="src/v.py:5")]
    m.flows = []
    return m


def test_an_unowned_entity_is_adjudicated_by_an_E_line_under_persistence_exceptions():
    """Trap P1: three separate live leads independently invented a 'Persistence exceptions'
    heading for this advisory. The heading existed and read `Cn` lines for the coverage rule from
    the other side of the same question; it now reads `En` lines for this one."""
    m = make_unowned_entity_model()
    assert any("no owning component" in w and "E2" in w and "Persistence exceptions" in w
               for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Persistence exceptions",
                             body="E2: a read-only projection built at query time.")]
    assert not any("no owning component" in w for w in warnings_of(m))
    # an unrelated id under the same heading leaves it firing
    m.extras = [ExtraSection(heading="Persistence exceptions", body="E9: some other card.")]
    assert any("no owning component" in w and "E2" in w for w in warnings_of(m))


def test_the_two_sides_of_persistence_exceptions_do_not_cross_silence():
    # C lines and E lines share the heading; each reader filters by its own prefix, so a writer
    # adjudication can never quiet an ownership gap (or the reverse).
    m = make_unowned_entity_model()
    m.entities[0].store = Store(dep="D1", container="orders", mode="collection")
    m.edges.append(Edge(src="C1", verb="writes", dst="D1", why="rows", where="src/v.py:9"))
    m.components.append(Component(id="C2", name="Locks", purpose="infra"))
    m.edges.append(Edge(src="C2", verb="writes", dst="D1", why="locks", where="src/l.py:4"))
    m.extras = [ExtraSection(heading="Persistence exceptions",
                             body="C2: lock rows only — infra, not domain.")]
    ws = warnings_of(m)
    assert not any("C2 writes into D1" in w for w in ws)       # the C line did its own job…
    assert any("no owning component" in w and "E2" in w for w in ws)   # …and only its own job
    m.extras = [ExtraSection(heading="Persistence exceptions",
                             body="E2: a read-only projection built at query time.")]
    ws = warnings_of(m)
    assert not any("no owning component" in w for w in ws)     # the E line did its own job…
    assert any("C2 writes into D1" in w for w in ws)           # …and only its own job


def test_a_no_writer_store_mode_answers_the_unowned_entity_advisory():
    """The MODE is the answer where the model can hold it: an entity that lives in a parent's row,
    in the source, or only for the length of a call has no writer by definition. Live maps wrote
    that as prose 67 times on one map, in 11 spellings of the same five sentences — each of them a
    mode restated in a footnote on a tab nobody reads."""
    for mode in ("embedded", "in-code", "enum", "transient", "projection"):
        m = make_unowned_entity_model()
        m.entities[1].store = Store(mode=mode)
        assert not any("no owning component" in w for w in warnings_of(m)), mode


def test_a_mode_that_implies_a_writer_leaves_the_unowned_advisory_firing():
    """`collection` and `cache` are NOT an answer — something writes a collection, and something
    writes a cache. Silencing on those would turn the check off for the population it is for."""
    for mode in ("collection", "cache", ""):
        m = make_unowned_entity_model()
        m.entities[1].store = Store(dep="D1", container="snapshots", mode=mode)
        assert any("no owning component" in w and "E2" in w for w in warnings_of(m)), mode or "unset"


def test_one_recorded_line_may_adjudicate_several_entities():
    m = make_unowned_entity_model()
    m.entities.append(make_entity(eid="E3", name="Draft"))
    assert any("no owning component" in w and "E2" in w and "E3" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Persistence exceptions",
                             body="E2, E3: read-only projections built at query time.")]
    assert not any("no owning component" in w for w in warnings_of(m))


SILENCED_LINE = "silenced by this map's recorded lines"


def test_what_the_records_silenced_is_disclosed_even_where_the_family_says_nothing():
    """Five families disclose their suppressions by hand and a dozen do not: the saved-record rule
    silenced 25 of reminderrepo's 26 records behind ONE recorded line and the report said nothing,
    so the gap was invisible without `--ignore-exceptions`.

    Answered by running the checks again WITHOUT the records and counting the advisories that
    vanish — which covers every family at once, including the ones nobody has written yet, and
    cannot over-report the way a hand-rolled count can."""
    m = make_unowned_entity_model()
    m.entities.append(make_entity(eid="E3", name="Draft"))
    live_without_record = warnings_of(m)
    assert any("no owning component" in w for w in live_without_record)
    assert not any(SILENCED_LINE in w for w in live_without_record), "nothing recorded, nothing hidden"

    m.extras = [ExtraSection(heading="Persistence exceptions",
                             body="E2, E3: read-only projections built at query time.")]
    silenced: list[str] = []
    _, warnings = validate_model(m, silenced_out=silenced)
    assert not any("no owning component" in w for w in warnings), "the record still silences it"
    hit = [w for w in warnings if SILENCED_LINE in w]
    assert len(hit) == 1, warnings
    assert hit[0].startswith("1 advisory line(s)"), hit[0]
    assert "Persistence exceptions" in hit[0], "it names where the records sit"
    assert "--ignore-exceptions" in hit[0], "and how to read the silenced lines"
    assert [w for w in silenced if "no owning component" in w], silenced


def test_the_disclosure_counts_the_silenced_lines_and_never_repeats_their_words():
    """A disclosure that quotes a silenced finding puts that finding's own words back into the
    report. 55 of this repo's tests ask "is this gone?" by looking for those words, and so does
    every script and counter that reads the report the same way — they would have read a silenced
    finding as a live one. The words go to the out-param; the line carries the count."""
    m = make_unowned_entity_model()
    m.extras = [ExtraSection(heading="Persistence exceptions",
                             body="E2: a read-only projection built at query time.")]
    silenced: list[str] = []
    _, warnings = validate_model(m, silenced_out=silenced)
    hit = [w for w in warnings if SILENCED_LINE in w]
    assert hit and silenced, (warnings, silenced)
    for line in silenced:
        assert line not in " ".join(hit), "the report must not restate a silenced finding"
        assert line[:40] not in " ".join(hit), line[:40]


def test_a_finding_whose_COUNT_moves_is_not_called_silenced():
    """A check still reporting, with a smaller number, is visible — calling it silenced would
    overstate. The prose counter is the same case from the other side: dropping the recorded lines
    drops the SENTENCES on them, so it reports fewer findings without the records, not more."""
    m = make_valid_model()
    m.extras = [ExtraSection(
        heading="Unclaimed surfaces",
        body="C1: a development-only surface that nobody outside this team will ever reach at all")]
    silenced: list[str] = []
    _, warnings = validate_model(m, silenced_out=silenced)
    assert not [w for w in silenced if w.startswith("1 prose field")], silenced


def test_the_re_read_flag_and_the_disclosure_drop_the_SAME_sections():
    """One answer to "which section is a record". `--ignore-exceptions` carried its own list — every
    heading ending in "exceptions" plus four named ones — and it had fallen four behind the
    registry: 'Missing surfaces', 'Walk jumps', 'Sweep debt' and 'Bucket vocabulary' all silence a
    finding and all survived the flag whose whole job is to drop them."""
    from coyomap import records as records_mod
    from coyomap.model import ExtraSection as Section
    for spec in records_mod.HEADINGS:
        assert validate_model_mod._is_recorded_section(Section(heading=spec.heading, body="x")), \
            spec.heading
    assert not validate_model_mod._is_recorded_section(Section(heading="Design notes", body="x"))


def test_a_repeated_reason_across_records_is_reported():
    """The shape that grew the walls: one sentence written out once per element."""
    m = make_valid_model()
    m.extras = [ExtraSection(heading="Unclaimed surfaces",
                             body="C1: a dev-only surface\nC2: a dev-only surface\n"
                                  "C3: a dev-only surface")]
    assert any("repeats one reason" in w and "Unclaimed surfaces" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Unclaimed surfaces",
                             body="C1, C2, C3: a dev-only surface")]
    assert not any("repeats one reason" in w for w in warnings_of(m))


def test_a_record_that_tries_to_be_one_and_reads_as_nothing_is_reported():
    """Three silent shapes, all reported now: a list holding a non-key, a key with no why, and (in
    the audit family) a list that lost the check name that scopes it."""
    for heading, body in (("Unclaimed surfaces", "C1, the poller: a dev-only surface"),
                          ("Unclaimed surfaces", "C1:"),
                          ("Coverage exceptions", "vendor/, the whole tree: vendored"),
                          ("Audit exceptions", "HP1, HP2: verified by hand")):
        m = make_valid_model()
        m.extras = [ExtraSection(heading=heading, body=body)]
        assert any("adjudicates NOTHING" in w for w in warnings_of(m)), (heading, body)


def test_a_family_with_no_comma_list_is_never_told_to_merge_its_records():
    """The advice that destroyed records: seven of the eleven families cannot read a bare list, and
    following the merge instruction wiped their adjudication with nothing said."""
    for heading, body in (
            ("Entry-point coverage", "http-route: complete — all of them\ncli: complete — all of them\n"
                                     "job: complete — all of them"),
            ("Sweep debt", "a.py:1: mechanics\nb.py:2: mechanics\nc.py:3: mechanics"),
            ("Bucket vocabulary", "AI: core machinery\nAuth: core machinery\nDocs: core machinery")):
        m = make_valid_model()
        m.extras = [ExtraSection(heading=heading, body=body)]
        assert not any("repeats one reason" in w for w in warnings_of(m)), heading


def test_the_merge_advice_names_the_real_keys_of_the_repeated_records():
    m = make_valid_model()
    m.extras = [ExtraSection(heading="Unclaimed surfaces",
                             body="C1: a dev-only surface\nC2: a dev-only surface\nC3: a dev-only surface")]
    hit = [w for w in warnings_of(m) if "repeats one reason" in w]
    assert hit and "C1, C2, C3: <why>" in hit[0]


def test_one_sentence_stretched_over_too_many_findings_is_reported():
    """The fix for the fix. Merging kills the wall, and reminderrepo then carried ONE line with 25
    `En` keys and one sentence — every saved record the map keeps, adjudicated in a single judgement
    nobody re-read against any of them.

    MEASURED across the four live maps of 2026-09-13: of 106 recorded lines that parse a key list,
    83 carry one key and 101 carry six or fewer, then the tail jumps to 8, 10, 10, 25 and 25."""
    cap = validate_model_mod._KEYS_PER_RECORD_CAP
    m = make_valid_model()
    keys = ", ".join(f"C{n}" for n in range(1, cap + 1))
    m.extras = [ExtraSection(heading="Unclaimed surfaces", body=f"{keys}: a dev-only surface")]
    assert not any("with one sentence" in w for w in warnings_of(m)), "the cap itself is legal"

    keys = ", ".join(f"C{n}" for n in range(1, cap + 2))
    m.extras = [ExtraSection(heading="Unclaimed surfaces", body=f"{keys}: a dev-only surface")]
    hit = [w for w in warnings_of(m) if "with one sentence" in w]
    assert hit, warnings_of(m)
    assert f"answering {cap + 1} findings" in hit[0] and "Unclaimed surfaces" in hit[0], hit[0]
    assert "C1" in hit[0], "it must name the keys it is about"

    # It must never ask for the wall back — the two advisories pull opposite ways on purpose.
    assert "repeated-reason" in hit[0], hit[0]
    assert not any("repeats one reason" in w for w in warnings_of(m))

    # Splitting into the groups it is really about is the answer, and it goes quiet.
    half = cap // 2
    m.extras = [ExtraSection(
        heading="Unclaimed surfaces",
        body=", ".join(f"C{n}" for n in range(1, half + 1)) + ": a dev-only surface\n"
             + ", ".join(f"C{n}" for n in range(half + 1, cap + 2)) + ": a build machine runs it")]
    assert not any("with one sentence" in w for w in warnings_of(m)), warnings_of(m)


def test_stale_view_warns_and_fresh_view_does_not():
    m = make_valid_model()
    with tempfile.TemporaryDirectory() as td:
        model_path = Path(td) / "project-map.json"
        model_path.write_text(to_canonical_json(m), encoding="utf-8")
        _, warnings = validate_model(m, model_path)
        assert any("view missing" in w for w in warnings)
        (Path(td) / "project-map.md").write_text(model_to_markdown(m), encoding="utf-8")
        _, warnings = validate_model(m, model_path)
        # specifically the STALENESS warnings — other advisories may mention "View order" (a title)
        assert not any("view missing" in w or "GENERATED file" in w for w in warnings)
        (Path(td) / "project-map.md").write_text("# hand-edited\n", encoding="utf-8")
        _, warnings = validate_model(m, model_path)
        assert any("GENERATED file" in w for w in warnings)


def test_check_sources_flags_synthesized_entity():
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "src"
        src.mkdir()
        (src / "order.py").write_text("class Order:\n    pass\n", encoding="utf-8")
        m = make_valid_model()
        m.entities = [make_entity(name="PhantomConcept", source="src/order.py:1")]
        problems, _ = validate_model(m, repo_root=Path(td), check_sources=True)
        assert any("PhantomConcept" in p and "not defined in its SOURCE" in p for p in problems)
        m.entities = [make_entity(name="Order", source="src/order.py:1")]
        problems, _ = validate_model(m, repo_root=Path(td), check_sources=True)
        assert not any("not defined in its SOURCE" in p for p in problems)


def test_check_sources_blocks_on_dead_anchor():
    # B3: a nonexistent-file anchor (wrong repo-root prefix / stale path) is a BLOCKING problem now,
    # not a warning — so a bad prefix can never reach the committed map with `validate` all-green.
    with tempfile.TemporaryDirectory() as td:
        m = make_valid_model()
        m.entities[0].source = "src/nowhere.py:1"
        problems, _ = validate_model(m, repo_root=Path(td), check_sources=True)
        assert any("does not resolve" in p for p in problems)


# --- anchor syntax gate: `path#Lnnn` is retired, `path:line`/`path:line-line` is mandatory ---

def test_legacy_hash_anchor_is_a_blocking_problem():
    m = make_valid_model()
    m.entities[0].source = "src/order.py#L1"
    assert any("source" in p and "not a valid" in p for p in problems_of(m))


# --- glossary `where`: a nullable file-OR-directory source anchor, like entities[].source ---

def test_glossary_where_accepts_bare_file_dir_and_null():
    m = make_valid_model()
    m.glossary = [GlossaryRow(term="Order", meaning="a thing", source="src/order.py:12"),
                  GlossaryRow(term="Domain", meaning="the dir", source="src/domain/"),
                  GlossaryRow(term="Product", meaning="no code home", source=None)]
    assert problems_of(m) == []


def test_glossary_where_rejects_markdown_link():
    m = make_valid_model()
    m.glossary = [GlossaryRow(term="Order", meaning="a thing",
                              source="[order.py](src/order.py:12)")]
    assert any("glossary 'Order' source" in p and "not a valid" in p for p in problems_of(m))


def test_glossary_where_dead_anchor_blocks_with_check_sources():
    with tempfile.TemporaryDirectory() as td:
        m = make_valid_model()
        m.glossary = [GlossaryRow(term="Ghost", meaning="gone", source="src/nowhere.py:1")]
        problems, _ = validate_model(m, repo_root=Path(td), check_sources=True)
        assert any("glossary 'Ghost'" in p and "does not resolve" in p for p in problems)


def test_extensionless_edge_where_existence_is_verified():
    # A2 + B3: an extensionless edge anchor (`Dockerfile:1`) is format-valid AND its existence is
    # actually checked (the `_where_href`/`_BARE_PATH` path used to skip extensionless files silently).
    from coyomap.model import Edge, ProjectModel
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        ok = ProjectModel(edges=[Edge(src="C1", verb="uses", dst="C2", where="Dockerfile:1")])
        assert check_anchor_existence_model(ok, [root]) == []                 # exists → clean
        bad = ProjectModel(edges=[Edge(src="C1", verb="uses", dst="C2", where="Nope.file:1")])
        assert any("does not resolve" in p for p in check_anchor_existence_model(bad, [root]))


# --- a cited LINE must exist, not just the file ------------------------------------

def make_anchored_model(anchor: str) -> ProjectModel:
    return ProjectModel(edges=[Edge(src="C1", verb="uses", dst="C2", where=anchor)])


def make_three_line_repo(td: str) -> Path:
    root = Path(td)
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    return root


def test_a_line_past_the_end_of_the_file_is_a_blocking_problem():
    # `method.md` promised "`--check-sources` verifies that line exists, so a fabricated anchor is a
    # hard block" while only the FILE was tested — so an agent that could not find the true line was
    # told a gate would catch a guess. `src/a.py:999999` passed all-green.
    with tempfile.TemporaryDirectory() as td:
        root = make_three_line_repo(td)
        out = check_anchor_existence_model(make_anchored_model("src/a.py:999999"), [root])
        assert any("cites a line the file does not have" in p and "3 line(s)" in p for p in out), out


def test_a_line_inside_the_file_stays_clean():
    with tempfile.TemporaryDirectory() as td:
        root = make_three_line_repo(td)
        for anchor in ("src/a.py:1", "src/a.py:3", "src/a.py:2-3"):
            assert check_anchor_existence_model(make_anchored_model(anchor), [root]) == [], anchor


def test_a_range_whose_END_overflows_is_caught():
    # The start being real is not enough — `2-99` claims 99 lines of witness that do not exist.
    with tempfile.TemporaryDirectory() as td:
        root = make_three_line_repo(td)
        out = check_anchor_existence_model(make_anchored_model("src/a.py:2-99"), [root])
        assert any("cites a line the file does not have" in p for p in out), out


def test_a_whole_file_anchor_cites_no_line_and_stays_clean():
    with tempfile.TemporaryDirectory() as td:
        root = make_three_line_repo(td)
        m = ProjectModel(components=[Component(id="C1", name="A", purpose="p", source="src/")])
        assert check_anchor_existence_model(m, [root]) == []


def test_a_missing_file_reports_only_the_file_not_the_line():
    # One finding per anchor: a nonexistent file must not ALSO produce a line complaint about a file
    # nobody could read.
    with tempfile.TemporaryDirectory() as td:
        root = make_three_line_repo(td)
        out = check_anchor_existence_model(make_anchored_model("src/gone.py:99"), [root])
        assert len(out) == 1 and "does not resolve" in out[0], out


def test_colon_range_anchor_is_not_flagged():
    m = make_valid_model()
    m.entities[0].source = "src/order.py:1-9"
    assert problems_of(m) == []


# --- anchor format gate: where_configured / edges.where / entry_points.source ---
# must be bare `path:line`, never a markdown link (the label was always just the file's basename).
# A component's own `entry_point` was checked here too; the field is gone (see `_component_headers`).

def test_dep_where_configured_md_link_is_a_blocking_problem():
    m = make_valid_model()
    m.deps[0].where_configured = "[cfg.py](cfg.py:1)"
    assert any("where_configured" in p and "not a valid" in p for p in problems_of(m))


def test_edge_where_md_link_is_a_blocking_problem():
    m = make_valid_model()
    m.edges[0].where = "[v.py](src/v.py:5)"
    assert any("where" in p and "not a valid" in p for p in problems_of(m))


def test_entry_point_entity_md_link_is_a_blocking_problem():
    m = make_valid_model()
    m.entry_points = [EntryPoint(kind="http", trigger="GET /x", source="[api.py](src/api.py:1)",
                                 component="C1")]
    assert any("source" in p and "not a valid" in p for p in problems_of(m))


# --- group source: a bare file-OR-directory anchor, like components[].source (no markdown link) ---

def test_group_source_accepts_bare_dir_and_file():
    m = make_valid_model()
    m.subsystems = [Group(id="S1", name="Core", purpose="all", source="src/core/")]
    m.components[0].subsystem = "S1"
    m.subdomains = [Group(id="SD1", name="Dom", purpose="d", source="src/order.py:1")]
    m.entities[0].subdomain = "SD1"
    assert not any("source" in p and "not a valid" in p for p in problems_of(m))


def test_group_source_rejects_markdown_link():
    m = make_valid_model()
    m.subsystems = [Group(id="S1", name="Core", purpose="all", source="[core](src/core/)")]
    m.components[0].subsystem = "S1"
    assert any("S1 source" in p and "not a valid" in p for p in problems_of(m))


# --- files / evidence / package / alternative: real fields, not `extra` columns ---

def test_component_files_and_evidence_round_trip_clean():
    m = make_valid_model()
    m.components[0].files = ["src/v.py", "src/helpers.py"]
    m.components[0].evidence = [EvidenceItem(file="src/v.py:12", why="the entry point")]
    assert problems_of(m) == []


def test_evidence_file_must_be_a_bare_path_line_anchor():
    m = make_valid_model()
    m.components[0].evidence = [EvidenceItem(file="[v.py](src/v.py:12)", why="a link, not bare")]
    assert any("evidence[0].file" in p and "not a valid" in p for p in problems_of(m))
    m.components[0].evidence = [EvidenceItem(file="src/v.py#L12", why="the retired form")]
    assert any("evidence[0].file" in p and "not a valid" in p for p in problems_of(m))


def test_evidence_why_must_be_non_empty():
    m = make_valid_model()
    m.components[0].evidence = [EvidenceItem(file="src/v.py:12", why="  ")]
    assert any("evidence[0].why" in p and "non-empty" in p for p in problems_of(m))


def test_dep_package_and_alternative_round_trip_clean():
    m = make_valid_model()
    m.deps[0].package = "motor ^3.7.0 (pyproject.toml)"
    m.deps[0].alternative = "file-backed storage in standalone mode"
    assert problems_of(m) == []


# --- `extra`: a promoted name (files/evidence/package/alternative, or an old spelling) is retired ---

def test_extra_files_count_and_members_are_retired_in_favor_of_the_files_field():
    m = make_valid_model()
    m.components[0].extra = {"files_count": 3}
    assert any("extra.files_count" in p and "top-level `files`" in p for p in problems_of(m))
    m.components[0].extra = {"members": ["a.py"]}
    assert any("extra.members" in p and "top-level `files`" in p for p in problems_of(m))
    m.components[0].extra = {"files": ["a.py"]}
    assert any("extra.files" in p and "top-level `files`" in p for p in problems_of(m))


def test_extra_evidence_is_retired_in_favor_of_the_evidence_field():
    m = make_valid_model()
    m.components[0].extra = {"evidence": [{"file": "policy.py:1", "why": "the reason"}]}
    assert any("extra.evidence" in p and "top-level `evidence`" in p for p in problems_of(m))


def test_extra_sdk_and_client_library_are_retired_in_favor_of_the_package_field():
    m = make_valid_model()
    m.deps[0].extra = {"sdk": "e2b ^2.20.0"}
    assert any("extra.sdk" in p and "top-level `package`" in p for p in problems_of(m))
    m.deps[0].extra = {"client_library": "motor ^3.7.0"}
    assert any("extra.client_library" in p and "top-level `package`" in p for p in problems_of(m))


def test_extra_standalone_alternative_is_retired_in_favor_of_the_alternative_field():
    m = make_valid_model()
    m.deps[0].extra = {"standalone_alternative": "dev_stub"}
    assert any("extra.standalone_alternative" in p and "top-level `alternative`" in p
              for p in problems_of(m))


def test_extra_loc_is_forbidden():
    m = make_valid_model()
    m.components[0].extra = {"loc": 1692}
    assert any("extra.loc" in p and "compute it" in p for p in problems_of(m))


def test_extra_deployment_flavored_key_is_advisory_only():
    m = make_valid_model()
    m.components[0].extra = {"sticky_sessions": "hash $http_mcp_session_id"}
    assert problems_of(m) == []
    assert any("extra.sticky_sessions" in w and "Deployment or Config" in w
              for w in warnings_of(m))


# --- granularity advisory (opt-in via check_coverage; re-computed from the tree — GR4) ---

def make_subsystem_shaped_repo(td: str, n_units: int = 9) -> Path:
    """A tree whose code-derived expectation E is n_units + 1 (n small unit dirs + a core dir)."""
    root = Path(td)
    for i in range(n_units):
        sub = root / "plugins" / f"p{i}"
        sub.mkdir(parents=True)
        for j in range(3):
            (sub / f"f{j}.py").write_text("x\n" * 100, encoding="utf-8")
    core = root / "core"
    core.mkdir()
    (core / "a.py").write_text("x\n" * 60, encoding="utf-8")
    return root


def test_granularity_advisory_fires_through_check_coverage():
    """A 1-component map over a tree expecting ~10 leaves draws the granularity nudge."""
    m = make_valid_model()  # 1 component
    with tempfile.TemporaryDirectory() as td:
        root = make_subsystem_shaped_repo(td)
        _, warnings = validate_model(m, repo_root=root, check_coverage=True)
    assert any(w.startswith("Granularity:") for w in warnings), warnings


def test_granularity_advisory_silent_within_band():
    """A component count inside E's ±40% band stays silent — the anchor nudges, it never nags."""
    m = make_valid_model()
    m.components = [Component(id=f"C{i}", name=f"Unit {i}", purpose="one unit") for i in range(1, 11)]  # 10 ≈ E
    m.edges = []  # the demo edges/flows reference C1 only — drop them so the model stays valid
    m.flows = []
    with tempfile.TemporaryDirectory() as td:
        root = make_subsystem_shaped_repo(td)
        _, warnings = validate_model(m, repo_root=root, check_coverage=True)
    assert not any(w.startswith("Granularity:") for w in warnings), warnings


# --- Coverage exceptions (per-directory suppression of the --check-coverage wall) ---

def test_recorded_coverage_dirs_reads_line_leading_dirs():
    from coyomap.validate_model import _recorded_coverage_dirs
    m = make_valid_model()
    m.extras = [ExtraSection(heading="Coverage exceptions",
                             body="plugins/: coarse altitude\n  foo/bar/: generated\nprose plugins/x mid-line")]
    assert _recorded_coverage_dirs(m) == {"plugins", "foo/bar"}   # trailing slash normalized; prose ignored


def test_compression_coverage_exception_is_boundary_aware():
    from coyomap.validate_analysis import compression_coverage_from_refs
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for base in ("plugins", "plugins_legacy"):   # a NAME-PREFIX sibling, not a path child
            for i in range(10):                       # ≥ _COMPRESSION_MIN (8) sibling subdirs
                sub = root / base / f"p{i}"
                sub.mkdir(parents=True)
                (sub / "a.py").write_text("x\n", encoding="utf-8")
        refs = {"plugins/p0", "plugins_legacy/p0"}    # the map references one subdir under each
        base = compression_coverage_from_refs(refs, root)
        assert any(w.startswith("Compression: plugins/") for w in base)
        assert any(w.startswith("Compression: plugins_legacy/") for w in base)
        skipped = compression_coverage_from_refs(refs, root, frozenset({"plugins"}))
        assert not any(w.startswith("Compression: plugins/") for w in skipped)     # recorded → silent
        assert any(w.startswith("Compression: plugins_legacy/") for w in skipped)  # sibling still warns


def test_coverage_exception_drops_recorded_domain_dir_from_denominator():
    with tempfile.TemporaryDirectory() as td:
        for d, cover, extra in (("folded", "Order", "T"), ("kept", "Member", "K")):
            p = Path(td) / d
            p.mkdir()
            (p / f"{cover.lower()}.py").write_text(f"class {cover}:\n    pass\n", encoding="utf-8")
            (p / "more.py").write_text("\n\n".join(f"class {extra}{i}:\n    pass" for i in range(12)),
                                       encoding="utf-8")
        m = make_valid_model()
        m.entities = [make_entity(eid="E1", name="Order", source="folded/order.py:1"),
                      make_entity(eid="E2", name="Member", source="kept/member.py:1")]
        roots = [Path(td)]
        assert any("Under-harvested" in w for w in check_domain_coverage_model(m, roots))
        skipped = check_domain_coverage_model(m, roots, frozenset({"folded"}))
        msg = [w for w in skipped if "Under-harvested" in w]
        assert msg                                      # 'kept' still warns
        assert not any("T0" in w for w in msg)          # folded types dropped from denominator + list


def test_a_use_case_that_states_half_its_outside_face_is_named() -> None:
    """`trigger` and `outcome` are two fields and one statement, and NOTHING else catches a missing
    half. The loader takes either alone, and the card drops the empty side rather than print a
    one-sided arrow — so the gap is invisible exactly where a reader meets it.

    Measured before this check existed: a map whose 25 outcomes were all blank loaded clean and
    validated silent. One line per SHAPE, because the remedy is the same sentence per row and a line
    each is the wall this file pays for elsewhere."""
    from coyomap.validate_model import _outside_face_warnings
    m = make_valid_model()
    m.use_cases = [UseCase(id="UC1", name="Open it", trigger="A person opens it.", outcome="It opens."),
                   UseCase(id="UC2", name="Half a", trigger="A person asks.", outcome=""),
                   UseCase(id="UC3", name="Half b", trigger="", outcome="The row is returned."),
                   UseCase(id="UC4", name="Nothing", trigger="", outcome="")]
    said = _outside_face_warnings(m)
    assert len(said) == 3, said                      # one line per shape, never one per use case
    assert any("UC2" in w and "no outcome" in w for w in said), said
    assert any("UC3" in w and "no trigger" in w for w in said), said
    assert any("UC4" in w and "neither" in w for w in said), said
    assert not any("UC1" in w for w in said), "the whole one is not named"
    # …and a map whose use cases all state both halves says nothing at all.
    m.use_cases = [m.use_cases[0]]
    assert _outside_face_warnings(m) == []


def test_coverage_exception_silences_unclaimed_surface_by_dir():
    from coyomap.validate_model import _completeness_warnings
    m = make_valid_model()
    m.components.append(Component(id="C2", name="Plugin", purpose="a plugin",
                                  source="plugins/achievements/plugin.py:1"))
    m.entry_points = [EntryPoint(kind="command", trigger="!achieve", source="plugins/achievements/plugin.py:5",
                                 component="C2", activation="external")]  # C2 is in no flow → unclaimed
    assert any(w.startswith("C2 ") and "unclaimed" in w for w in _completeness_warnings(m))
    m.extras = [ExtraSection(heading="Coverage exceptions", body="plugins/: representative at coarse altitude")]
    assert not any(w.startswith("C2 ") for w in _completeness_warnings(m))


# --- Deployment / runs_in ------------------------------------------------------

def test_runs_in_must_resolve_to_a_deployment_unit():
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="bot"), DeploymentRow(unit="worker")]
    m.components[0].runs_in = ["worker"]
    assert problems_of(m) == []                                   # a real unit → clean
    m.components[0].runs_in = ["ghost"]
    assert any("C1 runs_in names unknown deployment unit" in p and "ghost" in p for p in problems_of(m))


def test_entry_point_runs_in_also_checked():
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="worker")]
    m.entry_points = [EntryPoint(kind="worker", trigger="loop", source="w.py:1", component="C1",
                                 activation="self", runs_in=["nope"])]
    assert any("entry_points[0] runs_in names unknown deployment unit" in p for p in problems_of(m))


def test_duplicate_deployment_unit_blocks():
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="bot"), DeploymentRow(unit="bot")]
    assert any("Duplicate deployment unit name" in p and "bot" in p for p in problems_of(m))


def test_unplaced_self_thread_is_advised_only_once_runs_in_is_used():
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="worker")]
    m.entry_points = [EntryPoint(kind="cron", trigger="orphan loop", source="o.py:1", component="C1",
                                 activation="self")]  # C1 has no runs_in → this thread is unplaced
    # runs_in nowhere used yet → silent (un-adopted, not a gap)
    assert not any("Unplaced" in w for w in warnings_of(m))
    # once ANY runs_in is set, the un-hosted self thread is surfaced
    m.deployment.append(DeploymentRow(unit="bot"))
    m.components[0].runs_in = ["bot"]  # C1 now runs in bot → the C1-owned loop is placed, so add a second unplaced one
    m.entry_points.append(EntryPoint(kind="cron", trigger="really orphan", source="o2.py:1",
                                     component="C99", activation="self"))  # C99 undefined-owner → no host
    assert any("Unplaced" in w and "self-started" in w for w in warnings_of(m))


def test_the_unplaced_self_thread_answers_to_the_runs_in_literal():
    # It is a `runs_in` advisory that happens to live outside `_deployment_quality_warnings`'
    # family, so it took the same literal rather than a token of its own. An operator who has
    # decided the background threads are not worth placing decides it once.
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="worker"), DeploymentRow(unit="bot")]
    m.components[0].runs_in = ["bot"]
    m.entry_points = [EntryPoint(kind="cron", trigger="orphan loop", source="o.py:1",
                                 component="C99", activation="self")]
    assert any("Unplaced" in w and "runs-in" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="runs-in/entry-hosts: the maintenance threads float by design.")]
    assert not any("Unplaced" in w for w in warnings_of(m))
    # an unrelated literal under the same heading leaves it firing
    m.extras = [ExtraSection(heading="Balance exceptions", body="isolated: leaf plugins.")]
    assert any("Unplaced" in w for w in warnings_of(m))


# --- Deployment quality warnings (WS2) -----------------------------------------

def test_formula_filled_runs_in_is_flagged_but_a_true_monolith_is_not():
    m = make_valid_model()
    # one unit blankets EVERY component while another unit hosts nothing + no entry point placed
    m.deployment = [DeploymentRow(unit="standalone"), DeploymentRow(unit="worker")]
    m.components[0].runs_in = ["standalone"]
    assert any("formula-filled" in w for w in warnings_of(m))
    # a legit all-in-one app (single unit hosting everything, no empty peer) must NOT nag
    m.deployment = [DeploymentRow(unit="standalone")]
    assert not any("formula-filled" in w for w in warnings_of(m))
    # The SCOPED exception silences this group's detail even with the empty peer back — and the
    # suppression itself stays visible, because a silence you cannot see reads exactly like having
    # no findings. A BARE `runs-in` would silence nothing at all (see the bare-record test).
    m.deployment = [DeploymentRow(unit="standalone"), DeploymentRow(unit="worker")]
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="runs-in/quality: it truly is one process.")]
    ws = warnings_of(m)
    assert not any("one unit blankets" in w or "per-id-range" in w for w in ws)   # detail gone
    assert any("suppressed by recorded scoped exception(s)" in w for w in ws)   # count kept


def test_formula_fill_silent_on_grounded_dual_deployment():
    # F1 regression: a legitimately grounded map where every component runs in an all-in-one unit PLUS
    # a real split unit (standalone + backend/frontend), and the only EMPTY units are infra, must NOT
    # be called formula-filled — the spread across real units and the infra-only emptiness are grounding.
    m = make_valid_model()
    m.components = [Component(id="C1", name="A", purpose="p"),
                   Component(id="C2", name="B", purpose="p")]
    m.edges = []
    m.flows = []
    m.deps = [Dep(id="D1", name="MongoDB", kind="datastore", type="db")]
    m.deployment = [DeploymentRow(unit="standalone"), DeploymentRow(unit="backend"),
                    DeploymentRow(unit="frontend"), DeploymentRow(unit="mongo")]  # mongo = empty INFRA
    m.components[0].runs_in = ["standalone", "backend"]
    m.components[1].runs_in = ["standalone", "frontend"]
    assert not any("formula-filled" in w for w in warnings_of(m))   # spread → grounded, stays quiet


def test_unlinked_deployment_unit_is_flagged_unless_it_matches_a_dep():
    m = make_valid_model()                                    # dep D1 = "Postgres" (datastore)
    m.deployment = [DeploymentRow(unit="worker"), DeploymentRow(unit="ghosttown")]
    m.components[0].runs_in = ["worker"]                      # adoption present; ghosttown hosts nothing
    assert any("ghosttown" in w and "run no traced component" in w for w in warnings_of(m))
    # a no-host unit whose NAME matches a system dep is that dep's box, not a gap → not flagged
    m.deployment = [DeploymentRow(unit="worker"), DeploymentRow(unit="postgres")]
    assert not any("postgres" in w and "run no traced component" in w for w in warnings_of(m))


def test_ambiguous_thread_host_is_flagged():
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="bot"), DeploymentRow(unit="worker")]
    m.components[0].runs_in = ["bot", "worker"]               # C1 runs in TWO units
    m.entry_points = [EntryPoint(kind="cron", trigger="loop", source="o.py:1", component="C1",
                                 activation="self")]          # no own runs_in → host is ambiguous
    assert any("ambiguous" in w for w in warnings_of(m))
    m.entry_points[0].runs_in = ["bot"]                       # pinning its own host resolves it
    assert not any("ambiguous" in w for w in warnings_of(m))


def test_non_atomic_unit_name_is_flagged_but_a_spaced_name_is_not():
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="mongo-test / redis-test")]  # a separator → two units in one row
    assert any("non-atomic" in w for w in warnings_of(m))
    m.deployment = [DeploymentRow(unit="api worker")]              # spaces, no separator → legit
    assert not any("non-atomic" in w for w in warnings_of(m))


# --- deployment environments (C1) ----------------------------------------------

def test_deployment_variant_must_name_a_declared_environment():
    m = make_valid_model()
    m.environments = ["standalone", "cloud"]
    m.deployment = [DeploymentRow(unit="backend", variants=[VariantTag(env="cloud")])]
    assert problems_of(m) == []                                   # a declared env → clean
    m.deployment = [DeploymentRow(unit="backend", variants=[VariantTag(env="ghost")])]
    assert any("undeclared environment" in p and "ghost" in p for p in problems_of(m))
    # a variant with NO environments declared at all is also flagged (can't gate to an unnamed env)
    m.environments = []
    assert any("no `environments` are declared" in p for p in problems_of(m))


def test_variant_source_dead_anchor_blocks_with_check_sources():
    # WS1/T6: a CITED variant anchor that doesn't resolve on disk is a hard block under --check-sources
    # (same existence path as security[].source); an empty source (inferred) is NOT checked here.
    with tempfile.TemporaryDirectory() as td:
        Path(td, "docker-compose.yml").write_text("services:\n  api:\n", encoding="utf-8")
        m = make_valid_model()
        m.environments = ["cloud"]
        m.deployment = [DeploymentRow(unit="api",
                                      variants=[VariantTag(env="cloud", source="docker-compose.yml:2")])]
        problems, _ = validate_model(m, repo_root=Path(td), check_sources=True)
        assert not any("variant" in p and "does not resolve" in p for p in problems)  # resolves → clean
        m.deployment[0].variants = [VariantTag(env="cloud", source="nope.yml:9")]  # cited but missing
        problems, _ = validate_model(m, repo_root=Path(td), check_sources=True)
        assert any("variant 'cloud'" in p and "does not resolve" in p for p in problems)


def test_variant_source_malformed_is_a_format_error():
    m = make_valid_model()
    m.environments = ["cloud"]
    m.deployment = [DeploymentRow(unit="api",
                                  variants=[VariantTag(env="cloud", source="docker-compose.yml#L9")])]
    assert any("variant 'cloud'" in p and "not a valid" in p for p in problems_of(m))


def test_inferred_variant_tag_warns_and_is_silenced_by_runs_in_exception():
    # WS1/T8: an unanchored (source="") variant tag surfaces as an advisory (aggregated, non-blocking),
    # in the deployment family — silenced by the `runs-in` Balance-exceptions literal.
    m = make_valid_model()
    m.environments = ["cloud"]
    m.deployment = [DeploymentRow(unit="api", variants=[VariantTag(env="cloud")])]  # no source → inferred
    assert not any("inferred" in p for p in problems_of(m))       # advisory, never a problem
    assert any("inferred (no manifest anchor)" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Balance exceptions", body="runs-in/quality: single unit")]
    ws = warnings_of(m)
    assert not any("inferred (no manifest anchor)" in w for w in ws)               # detail silenced
    assert any("suppressed by recorded scoped exception(s)" in w for w in ws)   # count kept


# --- the ONE counted exit for the whole `runs-in` family (adversarial finding F1) ----------
# The literal used to be honoured at four separate sites and COUNTED at one. On two committed maps
# a `runs-in` record written about something else swallowed unrelated placement findings while the
# count named a smaller number — and when the counted group was empty, nothing appeared at all.

def make_multi_family_runs_in_model() -> ProjectModel:
    """A map that trips THREE different `runs_in` advisory groups at once: deployment quality
    (a non-atomic unit name + a unit hosting nothing), a self-started entry point with no host,
    and a channel whose consumer sets no `runs_in`."""
    return ProjectModel(
        components=[Component(id="C1", name="C1", purpose="p", source="a.py:1", runs_in=["api"]),
                    Component(id="C2", name="C2", purpose="p", source="b.py:1")],
        deps=[Dep(id="D1", name="Redis", kind="messaging", type="broker")],
        deployment=[DeploymentRow(unit="api"), DeploymentRow(unit="worker / bot")],
        messaging=[MessagingRow(name="JOB_QUEUE", broker="D1", publishers=["C1"], consumers=["C2"])],
        entry_points=[EntryPoint(kind="cron", trigger="orphan loop", source="o.py:1",
                                 component="C99", activation="self")],
    )


def test_every_runs_in_group_is_reported_before_the_exception_is_recorded():
    ws = warnings_of(make_multi_family_runs_in_model())
    assert any("non-atomic" in w for w in ws)                      # quality
    assert any("run no traced component" in w for w in ws)         # quality
    assert any("Unplaced" in w and "self-started" in w for w in ws)  # entry-point placement
    assert any("cannot place this channel" in w for w in ws)       # messaging placement


def test_a_bare_runs_in_record_now_silences_nothing_and_says_why():
    """It used to switch off all five groups at once while its justification was about one. On a
    live map a record about two test-profile containers thereby hid a real regression: six of eight
    deployment units had stopped hosting any component."""
    m = make_multi_family_runs_in_model()
    detail = [w for w in warnings_of(m) if "runs-in" in w]
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="runs-in: the Mongo units run no first-party code by design.")]
    ws = warnings_of(m)
    hits = [w for w in ws if "silences NOTHING" in w]
    assert len(hits) == 1, ws
    for scope in balance_lib_mod.RUNS_IN_SCOPES:
        assert scope in hits[0], (scope, hits[0])
    # and every finding it used to swallow is still on screen
    assert len([w for w in ws if "runs-in" in w]) >= len(detail)
    # every detail line really is gone
    assert any("non-atomic" in w or "Unplaced" in w or "cannot place this channel" in w
               for w in ws), "a bare record must swallow nothing"


def test_the_count_is_visible_when_the_deployment_quality_group_is_empty():
    """The invisible case: the group that used to own the count line produces nothing, so before
    the fix the `runs-in` record silenced a real finding with no trace on screen at all."""
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="bot")]
    m.components[0].runs_in = ["bot"]
    m.entry_points = [EntryPoint(kind="cron", trigger="orphan loop", source="o.py:1",
                                 component="C99", activation="self")]
    before = warnings_of(m)
    assert not any("non-atomic" in w or "run no traced component" in w or "formula-filled" in w
                   for w in before), "the quality group must be EMPTY for this test to mean anything"
    assert any("Unplaced" in w for w in before)
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="runs-in/entry-hosts: threads float by design.")]
    ws = warnings_of(m)
    hits = [w for w in ws if "suppressed by recorded scoped exception(s)" in w]
    assert len(hits) == 1, ws
    assert hits[0].startswith("1 deployment advisory/advisories")
    assert "runs-in/entry-hosts" in hits[0]
    assert "self-started entry points with no host unit" in hits[0]


def test_the_unlinked_units_group_is_counted_too():
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="api")]          # units exist, nothing sets runs_in
    assert any("no component or entry point sets" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="runs-in/unlinked: it truly runs as one unit.")]
    ws = warnings_of(m)
    hits = [w for w in ws if "suppressed by recorded scoped exception(s)" in w]
    assert len(hits) == 1, ws
    assert "deployment units enumerated but nothing links code to them" in hits[0]
    assert not any("no component or entry point sets" in w for w in ws)


def make_token_tagged_deployment_model(placed: int = 1, total: int = 12) -> ProjectModel:
    """A map with `total` components of which only `placed` carry `runs_in` — the shape that defeats
    the all-or-nothing canary. `total` is above `_RUNS_IN_UNPLACED_MIN` on purpose: the share alone is
    meaningless on a tiny map (1-of-2 is 50% and reads as a finding over a single component), so the
    check needs a real number of unplaced components before it means anything."""
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="api")]
    m.components = [Component(id=f"C{i}", name=f"Comp{i}", purpose="does") for i in range(1, total + 1)]
    for i, c in enumerate(m.components):
        c.runs_in = ["api"] if i < placed else []
    return m


def test_one_tagged_component_does_not_buy_silence_for_the_rest():
    """The graded hole the all-or-nothing canary leaves.

    `_deployment_unlinked_warning` early-returns on `any(c.runs_in ...)`, so ONE tagged component out
    of many satisfies it and the other N-1 go unreported — the Deployment view is then almost empty
    with no signal, which is the same failure that check was written for, one component short of
    triggering it. Measured on two real maps (100% and 97% placed), the new canary is silent."""
    m = make_token_tagged_deployment_model(placed=1, total=12)
    ws = warnings_of(m)
    assert not any("no component or entry point sets" in w for w in ws)   # the old one is blind here
    assert any("component(s) set `runs_in`" in w and "the other 11" in w for w in ws)


def test_a_fully_placed_map_says_nothing_about_placement_share():
    """The other half: a real map must not be nagged. Silence is the correct output at 100%."""
    m = make_token_tagged_deployment_model(placed=12, total=12)
    assert not any("component(s) set `runs_in`" in w for w in warnings_of(m))


def test_a_small_map_is_not_nagged_about_a_single_unplaced_component():
    """A share needs an absolute floor. 1-of-2 placed is 50% but the gap is one component, and an
    existing 2-component fixture caught the share-only version of this check nagging."""
    m = make_token_tagged_deployment_model(placed=1, total=2)
    assert not any("component(s) set `runs_in`" in w for w in warnings_of(m))


def test_the_placement_share_group_is_silenced_and_counted_with_its_family():
    """It is a `runs_in` advisory, so the one recorded literal must swallow it — and SAY it did."""
    m = make_token_tagged_deployment_model(placed=1, total=12)
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="runs-in/unplaced: deliberately unplaced.")]
    ws = warnings_of(m)
    assert not any("component(s) set `runs_in`" in w for w in ws)
    hits = [w for w in ws if "suppressed by recorded scoped exception(s)" in w]
    assert len(hits) == 1 and "most components unplaced" in hits[0], ws


def test_no_runs_in_record_means_no_count_line_at_all():
    """The count reports a suppression; with nothing suppressed it must not appear."""
    m = make_multi_family_runs_in_model()
    assert not any("suppressed by recorded scoped exception(s)" in w for w in warnings_of(m))


def test_only_one_function_may_read_the_runs_in_vocabulary():
    """The structural guard that stops a FIFTH group repeating F1.

    Every producer is RAW; the literal is applied — and counted — at exactly one exit. A new group
    added with its own private `if "runs-in" in ...: return []` would silence findings the count
    line never sees, which is precisely the bug this test exists to prevent. Adding a group means
    appending one row to `_RUNS_IN_FAMILY`; there is no other wiring."""
    # The whole VOCABULARY, not just the bare literal. Scoping the escape made `"runs-in"` inert —
    # it is now only what the "silences nothing" complaint keys off — so a sixth group added with a
    # private `if "runs-in/unplaced" in _exceptions(m): return []` would have tripped nothing.
    watched = ("runs-in", *balance_lib_mod.RUNS_IN_SCOPES)
    src = Path(str(validate_model_mod.__file__)).read_text(encoding="utf-8")
    readers = sorted({fn.name for fn in ast.walk(ast.parse(src))
                      if isinstance(fn, ast.FunctionDef)
                      and any(isinstance(n, ast.Constant) and n.value in watched
                              for n in ast.walk(fn))})
    assert readers == ["_runs_in_family_warnings"], (
        "a `runs_in` escape literal is read outside its one counted exit: " + ", ".join(readers))


def test_every_runs_in_group_is_registered_in_the_family_table():
    """The table IS the wiring, so it must not go stale: each entry produces a list of strings and
    carries a label the count line can print."""
    m = make_multi_family_runs_in_model()
    scopes = [scope for scope, _l, _p in validate_model_mod._RUNS_IN_FAMILY]
    labels = [label for _s, label, _p in validate_model_mod._RUNS_IN_FAMILY]
    assert len(labels) == len(set(labels)) >= 4
    assert len(scopes) == len(set(scopes)), "each group needs its OWN scoped escape"
    assert set(scopes) == set(balance_lib_mod.RUNS_IN_SCOPES), (
        "the scope table and the recognised literals must not drift apart")
    produced = [produce(m) for _s, _l, produce in validate_model_mod._RUNS_IN_FAMILY]
    assert all(isinstance(ws, list) and all(isinstance(w, str) for w in ws) for ws in produced)
    # the raw producers no longer read the literal themselves: recording it changes nothing here
    m.extras = [ExtraSection(heading="Balance exceptions", body="runs-in: recorded.")]
    assert [produce(m) for _s, _l, produce in validate_model_mod._RUNS_IN_FAMILY] == produced


def test_environments_absent_is_silent_but_declared_untagged_advises():
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="app")]                    # no environments, no variants
    assert not any("environment" in w.lower() for w in warnings_of(m))   # un-adopted → silent
    m.environments = ["dev", "prod"]                             # declared but nothing tagged
    assert any("environment(s) declared but no deployment unit is tagged" in w for w in warnings_of(m))


# --- Orphan-dep nudge scoped to system deps (WS6) ------------------------------

def test_orphan_dep_nudge_skips_folded_library_kinds():
    m = make_valid_model()
    # a library dep with no incoming edge folds into Libraries → must NOT nudge for a missing call site
    m.deps.append(Dep(id="D2", name="pydantic", kind="library", type="validation"))
    assert not any("no incoming edge" in w and "D2" in w for w in warnings_of(m))
    # a SYSTEM dep (datastore) with no incoming edge still nudges — it needs a real call site
    m.deps.append(Dep(id="D3", name="Redis", kind="datastore", type="cache"))
    assert any("no incoming edge" in w and "D3" in w for w in warnings_of(m))


# --- Roleless C→D verb nudge (WS2) — advisory, non-blocking, C→D only ----------

def test_roleless_cd_verb_warns_but_never_blocks():
    m = make_valid_model()                                        # already has `C1 uses D1` (roleless C→D)
    assert any("name no role" in w and "C1 uses D1" in w for w in warnings_of(m))
    assert not any("name no role" in p for p in problems_of(m))   # advisory, never a blocking problem


def test_role_revealing_cd_verb_is_not_flagged():
    m = make_valid_model()
    m.edges = [Edge(src="C1", verb="reads", dst="E1", why="show", where="src/v.py:5"),
               Edge(src="C1", verb="queries", dst="D1", why="query", where="src/v.py:7")]  # queries → datastore
    assert not any("name no role" in w for w in warnings_of(m))


def test_roleless_verb_off_the_dep_boundary_is_not_flagged():
    # C→C and C→E generic `uses` are legitimate — the nudge is C→D ONLY (T4), else it floods.
    m = make_valid_model()
    m.components.append(Component(id="C2", name="Other", purpose="p"))
    m.edges = [Edge(src="C1", verb="uses", dst="C2", why="x", where="src/v.py:3"),   # C→C uses
               Edge(src="C1", verb="uses", dst="E1", why="y", where="src/v.py:5")]   # C→E uses
    assert not any("name no role" in w for w in warnings_of(m))


# --- File-level harvest coverage (WS4) -----------------------------------------

def test_file_level_coverage_flags_loose_py_with_the_exclusions():
    from coyomap.validate_analysis import file_level_coverage
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "adapters").mkdir()
        (root / "adapters" / "a.py").write_text("x\n", encoding="utf-8")        # referenced
        (root / "adapters" / "loose.py").write_text("x\n", encoding="utf-8")    # the loose gap
        (root / "adapters" / "README.md").write_text("d\n", encoding="utf-8")   # not code → excluded (2)
        (root / "adapters" / "__init__.py").write_text("\n", encoding="utf-8")  # package marker → excluded (4)
        (root / "tests").mkdir()
        (root / "tests" / "t.py").write_text("x\n", encoding="utf-8")           # non-product → excluded (3)
        (root / ".coyomap-eval").mkdir()
        (root / ".coyomap-eval" / "e.py").write_text("x\n", encoding="utf-8")   # coyomap artifact → excluded (3)
        refs = {"adapters/a.py"}
        out = file_level_coverage(refs, root)
        assert any("loose.py" in w for w in out)
        assert not any("README" in w for w in out)
        assert not any("__init__.py" in w for w in out)        # package marker not flagged
        assert not any("tests/t.py" in w for w in out)
        assert not any(".coyomap-eval" in w for w in out)      # coyomap's own output not flagged
        assert any("adapters/ (1)" in w for w in out)          # GROUPED by directory with a count
        # exclusion 1: a referenced DIRECTORY covers its whole subtree
        assert not file_level_coverage({"adapters"}, root)
        # a 'Coverage exceptions' recorded dir suppresses it too
        assert not file_level_coverage(refs, root, frozenset({"adapters"}))


def test_file_level_coverage_groups_root_files_under_root_label():
    from coyomap.validate_analysis import file_level_coverage
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "loose1.py").write_text("x\n", encoding="utf-8")
        (root / "loose2.py").write_text("x\n", encoding="utf-8")
        out = file_level_coverage(set(), root)
        assert any("(root)/ (2): loose1.py, loose2.py" in w for w in out)   # both root files on one line


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


def test_referenced_paths_matches_root_files_but_not_root_directories():
    """B1 + its adversarial correction.

    A bare root FILE anchor (`Makefile:6`) must count as a reference — `_REF_INLINE` needs a `/`,
    so root files used to be invisible. But root DIRECTORIES must NOT be matched by name: a dir
    shares its name with words that appear in ordinary map prose, and accepting them let a `Why`
    sentence mark a whole tree as referenced (on a live map that silenced a true "i18n/ has no path
    referenced — likely an unmapped module" finding)."""
    from coyomap.validate_model import referenced_paths
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "Makefile").write_text("all:\n")
        (root / "i18n").mkdir()
        (root / "i18n" / "en.ts").write_text("export const x = 1\n")
        m = ProjectModel(
            components=[Component(id="C1", name="Build", purpose="runs the build",
                                  source="Makefile:1")],
            edges=[Edge(src="C1", verb="reads", dst="C2", where="Makefile:1",
                        why="resolves a key across the bundle's i18n files")],
        )
        refs = referenced_paths(m, root)
        assert "Makefile" in refs          # the root FILE anchor is seen
        assert "i18n" not in refs          # the prose mention of a root DIR is not


def make_channel_map(publishers: list[str], consumers: list[str],
                     runs_in: list[str] | None = None) -> ProjectModel:
    """A one-channel map whose participants optionally carry a deployment placement."""
    hosts = runs_in if runs_in is not None else ["api"]
    return ProjectModel(
        components=[Component(id=c, name=c, purpose="p", source="a.py:1", runs_in=list(hosts))
                    for c in sorted(set(publishers) | set(consumers))],
        deps=[Dep(id="D1", name="Redis", kind="messaging", type="broker")],
        deployment=[DeploymentRow(unit="api"), DeploymentRow(unit="worker")],
        messaging=[MessagingRow(name="JOB_QUEUE", broker="D1",
                                publishers=list(publishers), consumers=list(consumers))],
    )


def test_channel_missing_a_side_warns_with_the_topology_consequence():
    """A one-sided catalog row draws NO process arrow, and the hole is invisible in every view.

    On a live map 5 of 25 channels were one-sided; their traffic then appeared only as a link to
    the broker box, which says "this process uses Redis" but never who it talks to."""
    for pubs, cons, word in (([], ["C2"], "publisher"), (["C1"], [], "consumer")):
        _, warnings = validate_model(make_channel_map(pubs, cons))[:2]
        hits = [w for w in warnings if "JOB_QUEUE" in w and f"no {word}s recorded" in w]
        assert len(hits) == 1, (pubs, cons, warnings)
        assert "Deployment view" in hits[0]


def test_channel_missing_both_sides_reports_them_together():
    _, warnings = validate_model(make_channel_map([], []))[:2]
    hits = [w for w in warnings if "no publishers and no consumers recorded" in w]
    assert len(hits) == 1


def test_a_two_sided_channel_does_not_warn():
    _, warnings = validate_model(make_channel_map(["C1"], ["C2"]))[:2]
    assert not [w for w in warnings if "recorded —" in w and "JOB_QUEUE" in w]


def test_untagged_participants_warn_separately():
    # Both sides named, but nothing says which process runs them — same invisible outcome as a
    # missing side, different fix (tag runs_in, not "record the other end").
    _, warnings = validate_model(make_channel_map(["C1"], ["C2"], runs_in=[]))[:2]
    hits = [w for w in warnings if "cannot place this channel" in w]
    assert len(hits) == 1 and "runs_in" in hits[0]


def test_the_unplaced_channel_answers_to_the_runs_in_literal():
    # It is a `runs_in` gap wearing a messaging hat, so it takes the SAME literal the rest of the
    # deployment family takes — one decision about this map's tagging, recorded once.
    m = make_channel_map(["C1"], ["C2"], runs_in=[])
    assert any("cannot place this channel" in w and "runs-in" in w for w in validate_model(m)[1])
    m.extras = [ExtraSection(heading="Balance exceptions", body="runs-in/messaging: one process, no split.")]
    assert not any("cannot place this channel" in w for w in validate_model(m)[1])
    # an unrelated literal leaves it firing
    m.extras = [ExtraSection(heading="Balance exceptions", body="channel-ends: far ends external.")]
    assert any("cannot place this channel" in w for w in validate_model(m)[1])


def test_placement_warning_is_silent_without_deployment_units():
    # No deployment[] means no process boxes at all, so there is no topology to be missing.
    m = make_channel_map(["C1"], ["C2"], runs_in=[])
    m.deployment = []
    _, warnings = validate_model(m)[:2]
    assert not [w for w in warnings if "cannot place this channel" in w]


def test_the_one_sided_warning_is_advisory_not_blocking():
    # A channel whose other end lives outside the mapped repo is legitimately one-sided.
    problems, _ = validate_model(make_channel_map(["C1"], []))[:2]
    assert not [p for p in problems if "JOB_QUEUE" in p]


def test_the_one_sided_decision_is_recordable_with_the_channel_ends_literal():
    # "Legitimately one-sided" was the code's OWN justification for keeping this advisory, and
    # there was nowhere to write that judgement down — so it re-fired at every validate.
    m = make_channel_map(["C1"], [])
    assert any("no consumers recorded" in w and "channel-ends" in w for w in validate_model(m)[1])
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="channel-ends: every consumer is a third-party service.")]
    assert not any("no consumers recorded" in w for w in validate_model(m)[1])
    # a neighbouring literal under the same heading must not stand in for it
    m.extras = [ExtraSection(heading="Balance exceptions", body="messaging: nothing nameable.")]
    assert any("no consumers recorded" in w for w in validate_model(m)[1])


def test_base_class_must_run_where_its_subclass_runs():
    """A subclass cannot exist in a process that does not load its base class.

    That makes `src_units ⊆ dst_units` a hard invariant for inheritance, checkable with no code
    reading — and a gap is not cosmetic: the Deployment view composes process topology from `runs_in`
    differences, so one missing tag on a shared connector framework drew eight false process arrows
    from the plugin that extends it to all its siblings."""
    m = ProjectModel(
        components=[Component(id="C1", name="Plugin", purpose="p", source="a.py:1",
                              runs_in=["bluesky"]),
                    Component(id="C2", name="Framework", purpose="p", source="b.py:1",
                              runs_in=["rss"])],
        deployment=[DeploymentRow(unit="bluesky"), DeploymentRow(unit="rss")],
        edges=[Edge(src="C1", verb="extends", dst="C2", why="w", where="a.py:1")])
    out = _inheritance_runs_in_warnings(m)
    assert len(out) == 1 and "bluesky" in out[0] and "C2" in out[0]

    m.components[1].runs_in = ["rss", "bluesky"]           # base now loaded where the subclass runs
    assert _inheritance_runs_in_warnings(m) == []

    m.edges = [Edge(src="C1", verb="calls", dst="C2", why="w", where="a.py:1")]
    m.components[1].runs_in = ["rss"]
    assert _inheritance_runs_in_warnings(m) == []           # a plain call may legitimately cross


def make_inheritance_model(base_runs_in: list[str], sub_runs_in: list[str],
                           units: list[str] | None = None) -> ProjectModel:
    """`C1` (subclass) extends `C2` (base), each placed by `runs_in` over `units`.

    `units=[]` builds a map with NO `deployment[]` rows — the state where nothing can be placed
    at all, as distinct from a map whose units exist but which tags no component into them."""
    return ProjectModel(
        components=[Component(id="C1", name="Report worker", purpose="p", source="sub.py:1",
                              runs_in=list(sub_runs_in)),
                    Component(id="C2", name="Worker template", purpose="p", source="base.py:1",
                              runs_in=list(base_runs_in))],
        deployment=[DeploymentRow(unit=u) for u in (["worker", "api"] if units is None else units)],
        edges=[Edge(src="C1", verb="extends", dst="C2", why="w", where="sub.py:1")])


def test_a_base_tagged_nowhere_at_all_warns_where_its_subclass_runs():
    """The state a real build produces: the subclass owns a directory and gets tagged, the
    abstract base sits in a shared module and is forgotten.

    The check used to require the base to be tagged SOMEWHERE before comparing, which inverted
    the rule — it reported the half-done job and stayed silent on the un-started one."""
    out = _inheritance_runs_in_warnings(make_inheritance_model(base_runs_in=[],
                                                               sub_runs_in=["worker"]))
    assert len(out) == 1, out
    assert "C2" in out[0] and "worker" in out[0] and "sets no `runs_in` at all" in out[0], out[0]


def test_a_partially_tagged_base_keeps_the_add_the_unit_remedy():
    """A base tagged somewhere-but-not-there needs a unit ADDED, so it keeps the older text —
    a different remedy from the untagged base, which needs tagging at all."""
    out = _inheritance_runs_in_warnings(make_inheritance_model(base_runs_in=["api"],
                                                               sub_runs_in=["worker"]))
    assert len(out) == 1, out
    assert "not tagged to run there" in out[0] and "sets no `runs_in` at all" not in out[0], out[0]


def test_a_base_tagged_everywhere_its_subclass_runs_is_silent():
    assert _inheritance_runs_in_warnings(
        make_inheritance_model(base_runs_in=["worker", "api"], sub_runs_in=["worker"])) == []


def test_a_map_that_uses_runs_in_nowhere_is_silent():
    """Units exist, but no component is tagged into any of them: the map does not place code, so
    there is no placement to be missing. The subclass's own placement is the only guard, and it
    is what keeps this state quiet without a special case."""
    assert _inheritance_runs_in_warnings(
        make_inheritance_model(base_runs_in=[], sub_runs_in=[])) == []


def test_a_map_with_no_deployment_units_is_silent():
    """No `deployment[]` rows means no process boxes at all — a `runs_in` value would resolve
    against nothing, so an untagged base claims nothing."""
    assert _inheritance_runs_in_warnings(
        make_inheritance_model(base_runs_in=[], sub_runs_in=["worker"], units=[])) == []


def test_mixed_variant_tagging_is_flagged():
    """An untagged unit reads as 'runs in EVERY environment', so on a partly-tagged map a FORGOTTEN
    unit does not go missing — it silently claims to run everywhere.

    Same shape as the `runs_in` gap that drew eight false process arrows on a live map: an absence
    read as a positive claim. The pre-existing check only fired when NO unit was tagged, which is
    the one state where nothing is hidden."""
    m = make_valid_model()
    m.environments = ["dev", "prod"]
    m.deployment = [DeploymentRow(unit="api", variants=[VariantTag(env="prod", source="c.yml:1")]),
                    DeploymentRow(unit="spa")]                       # forgotten
    ws = warnings_of(m)
    assert any("carry no `variants` while others do" in w and "spa" in w for w in ws)
    # fully tagged -> silent
    m.deployment[1].variants = [VariantTag(env="dev", source="c.yml:9")]
    assert not any("carry no `variants` while others do" in w for w in warnings_of(m))
    # nothing tagged at all -> the pre-existing all-or-nothing advisory owns it, not this one
    for d in m.deployment:
        d.variants = []
    ws = warnings_of(m)
    assert not any("carry no `variants` while others do" in w for w in ws)
    assert any("no deployment unit is tagged" in w for w in ws)


def make_channel_catalog(payloads: list[str]) -> ProjectModel:
    """A catalog of len(payloads) channels; '' entries claim the channel carries no domain type."""
    m = make_valid_model()
    m.entities = [Entity(id="E1", name="Job", meaning="m", source="a.py:1")]
    m.deps = [Dep(id="D1", name="Redis", kind="messaging", type="broker")]
    m.components = [Component(id="C1", name="Prod", purpose="p", source="a.py:1")]
    m.messaging = [MessagingRow(name=f"chan{i}", broker="D1", publishers=["C1"], consumers=["C1"],
                                payload=pl) for i, pl in enumerate(payloads)]
    return m


def test_an_entirely_unfilled_payload_column_is_flagged():
    """`payload: ''` CLAIMS the channel carries no domain type, so an unfilled column reads as N
    untyped channels. A live map made that claim on 25 of 25 channels — including `shard.events`
    and `job_queue` — with 134 entities available to reference."""
    ws = warnings_of(make_channel_catalog(["", "", ""]))
    assert any("names a `payload`" in w for w in ws)


def test_the_untyped_confirmation_is_recordable_with_the_channel_payload_literal():
    # The message asked the operator to "confirm they really are untyped" and gave them nowhere to
    # put the confirmation — the shape that trains people to skim past validate output.
    m = make_channel_catalog(["", "", ""])
    assert any("names a `payload`" in w and "channel-payload" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="channel-payload: all three carry raw strings, no domain type.")]
    assert not any("names a `payload`" in w for w in warnings_of(m))
    # the catalog-level literal says something else and must not silence this one
    m.extras = [ExtraSection(heading="Balance exceptions", body="messaging: no nameable channels.")]
    assert any("names a `payload`" in w for w in warnings_of(m))


def test_a_partly_typed_catalog_stays_quiet():
    # one genuinely untyped channel among typed ones is unremarkable — only ALL-empty is the signal.
    assert not any("names a `payload`" in w for w in warnings_of(make_channel_catalog(["E1", "", ""])))


def test_the_payload_canary_needs_entities_and_enough_channels():
    assert not any("names a `payload`" in w for w in warnings_of(make_channel_catalog(["", ""])))
    m = make_channel_catalog(["", "", ""])
    m.entities = []          # nothing to reference -> nothing to claim
    assert not any("names a `payload`" in w for w in warnings_of(m))


def test_json_mode_emits_whole_lists_where_the_human_view_truncates():
    """`--json`'s consumer is a program, so `+N more` is a defect there.

    The truncation was silently forcing hand-written python: a live build hit `16 of 86 component(s)
    carry no backbone edge: C1, C12, … +8 more`, needed the hidden eight to write its exceptions
    block, and re-derived the whole list in a throwaway script. Every such list goes through one
    helper so `--json` cannot cover nine sites and miss the tenth."""
    m = make_valid_model()
    m.components = [Component(id=f"C{i}", name=f"Comp{i}", purpose="does") for i in range(1, 21)]
    m.edges = []
    m.flows = []
    try:
        reporting.reset_full_lists()
        human = [w for w in warnings_of(m) if "carry no backbone edge" in w][0]
        reporting.set_full_lists(True)
        full = [w for w in warnings_of(m) if "carry no backbone edge" in w][0]
    finally:
        reporting.reset_full_lists()
    assert "+12 more" in human and human.count("Comp") == 8
    assert "more" not in full and full.count("Comp") == 20


def test_json_mode_does_not_clip_trigger_prose_either():
    """A clipped trigger cannot be matched back to the entry point it names, so `--json` keeps it."""
    long_trigger = "GET /a/very/long/route/that/keeps/going/and/going/past/sixty/characters/easily"
    try:
        reporting.reset_full_lists()
        assert reporting.clip(long_trigger).endswith("…")
        reporting.set_full_lists(True)
        assert reporting.clip(long_trigger) == long_trigger
    finally:
        reporting.reset_full_lists()


def test_no_hand_written_truncation_bypasses_the_helper():
    """The structural guard: no finding-list truncation outside `coyomap.reporting`.

    A hand-written tail is invisible to `--json`, which then reports a completeness it does not have.
    The first version of this test sliced ONE file after `def _shown(` and grepped for one exact
    literal; a review defeated it four ways and found a real bypass it had missed — `validate_analysis`
    emitted `+N more dir(s)` inside the JSON payload.

    SCOPE, stated rather than overclaimed: the modules whose findings reach a `--json` payload. The
    viewer is deliberately out — a diagram label has a hard pixel budget and clips regardless of any
    report mode, which is a different medium, not a findings list. The SHAPE is the `+<remainder> more`
    tail computed from a length; a prose ellipsis is not truncation and is not flagged."""
    pkg = Path(str(reporting.__file__)).parent
    reporters = ("validate_model.py", "validate_analysis.py", "audit_model.py", "lint_fragment.py",
                 "balance_lib.py", "balance.py", "anchor_drift.py", "assemble.py", "dump.py", "fix.py")
    tail = re.compile(r"\+\s*\{[^}]*\}\s*more")      # f-string: `+{len(x) - N} more`
    offenders: list[str] = []
    for name in reporters:
        mod = pkg / name
        if not mod.is_file():
            continue
        for n, line in enumerate(mod.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#") or '"""' in line:
                continue
            code = line.split("  # ", 1)[0]
            if tail.search(code) and not any(h in code for h in ("shown(", "capped(", "clip(")):
                offenders.append(f"{name}:{n}: {code.strip()[:90]}")
    assert not offenders, (
        "hand-written truncation bypasses coyomap.reporting, so `--json` silently under-reports:\n"
        + "\n".join(offenders))


def test_the_guard_above_would_catch_a_reintroduced_truncation():
    """The guard's own test — a guard nobody has seen fail is a guard nobody knows works.

    The previous version passed all four re-introductions a review threw at it, so this asserts the
    detector fires on the shape it exists to find."""
    tail = re.compile(r"\+\s*\{[^}]*\}\s*more")
    for bad in ('shown = ", ".join(x[:8]) + f", +{len(x) - 8} more"',
                "msg = f'…, +{n} more'",
                'lines.append(f"+{len(dirs) - CAP} more dir(s)")',
                'out += f", +{extra} more"'):
        assert tail.search(bad), bad
    for ok in ('shown = _shown(items, 8)',
               'kept, dropped = capped(rows, 8)',
               'desc = clip(text)',
               '# a comment mentioning +N more is prose'):
        assert not (tail.search(ok) and not any(h in ok for h in ("shown(", "capped(", "clip("))), ok


def make_grounded_model(digest: str = "", *,
                        claims_total: int = 0, claims_challenged: int = 0,
                        claims_confirmed: int = 0, claims_refuted: int = 0,
                        claims_unverifiable: int = 0, claims_superseded: int = 0,
                        claims_added_since: int = 0,
                        claims_live_challenged: int = 0) -> ProjectModel:
    """The eight COUNT fields, named. They were once `**counts: int`, which read as tidy and typed
    nothing: `Grounding` carries `note` and `live_claims_digest` as strings, so the spread was
    unassignable, and a mis-typed count name went straight through to a runtime `TypeError` from a
    helper whose whole job is to build a valid one."""
    m = make_valid_model()
    m.grounding = Grounding(
        claims_total=claims_total, claims_challenged=claims_challenged,
        claims_confirmed=claims_confirmed, claims_refuted=claims_refuted,
        claims_unverifiable=claims_unverifiable, claims_superseded=claims_superseded,
        claims_added_since=claims_added_since,
        claims_live_challenged=claims_live_challenged, live_claims_digest=digest)
    return m


def grounding_of(m: ProjectModel) -> Grounding:
    """`ProjectModel.grounding` is optional; every model `make_grounded_model` returns has one."""
    assert m.grounding is not None, "make_grounded_model always sets a grounding record"
    return m.grounding


def test_grounding_counts_that_do_not_add_up_are_blocking():
    """The lie the old field allowed, now caught.

    A live map recorded `total 399, grounded 399, refuted 3` — read as "399 held up AND 3 were
    refuted out of 399". The check that replaced it in an earlier draft asserted
    `refuted <= challenged <= total`, which PASSES on that exact map (3 <= 399 <= 399) and therefore
    checked nothing. Arithmetic on the map's own numbers is blocking: there is no judgement to defer
    to and no repo to re-read."""
    m = make_grounded_model(claims_total=399, claims_challenged=399, claims_confirmed=399,
                            claims_refuted=3)
    probs = problems_of(m)
    assert any("do not add up" in p and "402" in p for p in probs), probs


def test_the_honest_version_of_the_same_counts_passes_and_reports_the_right_coverage():
    """Asserting only "no finding" made this pass with the whole check deleted. So it also pins the
    number the advisory would have used: coverage is measured on CONFIRMED claims, and 396/399 is
    above the thin threshold, so the map is quiet for a reason rather than by accident."""
    m = make_grounded_model(claims_total=399, claims_challenged=399, claims_confirmed=396,
                            claims_refuted=3)
    assert not any("grounding" in p for p in problems_of(m))
    assert not any("Grounding is partial" in w for w in warnings_of(m))
    assert validate_model_mod._grounding_split_recorded(grounding_of(m)) is True
    # …and one confirmed claim fewer would NOT balance, which is what makes the silence meaningful
    grounding_of(m).claims_confirmed = 395
    assert any("do not add up" in p for p in problems_of(m))


def test_a_map_carrying_claims_nobody_challenged_says_so():
    """The pinned counts read as full coverage and the shipped map is not fully covered.

    A finished map recorded `claims_total 209, claims_challenged 209` under a note opening "All 209
    claims were challenged", while ten of its own live claims had no verdict: the build reworded
    three rule statements after the vote, retiring ten pinned claims and minting ten fresh ones.
    Every pinned number stayed true. `anchor-drift` printed "challenged 199 of 209" in the same
    build and nothing tied the two together."""
    m = make_grounded_model(claims_total=209, claims_challenged=209, claims_confirmed=209,
                            claims_superseded=10, claims_added_since=10,
                            claims_live_challenged=199)
    warns = warnings_of(m)
    hit = [w for w in warns if "PINNED worklist, not the shipped map" in w]
    assert len(hit) == 1, warns
    assert "10 of the shipped map's 209 claim(s) have NO verdict" in hit[0]
    assert "199 do" in hit[0]
    # …and it is ADVISORY, never blocking: the record is arithmetically sound, and which claims to
    # re-challenge is a judgement.
    assert not any("shipped map" in p for p in problems_of(m))


CLOSER_LINE = "appeal counts disagree with the closer's files"


def make_verify_dir(root: Path, m: ProjectModel, *, skeptics: int = 1,
                    closer: tuple[str, ...] = ()) -> Path:
    """The map on disk with a `verify/` directory beside it: `skeptics` ordinary verdict rows, and
    one closer row per word in `closer` (`uphold` / `reject` / `unsure`)."""
    model_path = root / "project-map.json"
    model_path.write_text(to_canonical_json(m), encoding="utf-8")
    (root / "project-map.md").write_text(model_to_markdown(m), encoding="utf-8")
    verify = root / "verify"
    verify.mkdir(exist_ok=True)
    rows = [{"claim": f"a claim ({n})", "grounded": True, "evidence": "a.py:1"}
            for n in range(skeptics)]
    (verify / "verdicts-1.json").write_text(json.dumps({"grounding": rows}), encoding="utf-8")
    if closer:
        appeals = [{"claim": f"a claim ({n})", "verdict": word, "grounded": True}
                   for n, word in enumerate(closer)]
        (verify / "closer-a.json").write_text(json.dumps({"grounding": appeals}), encoding="utf-8")
    return model_path


def test_a_recorded_appeal_must_agree_with_the_closers_own_files():
    """`validate` blocks when confirmed + refuted + unverifiable != challenged, and the three closer
    counts had no such tie to anything — an ASSERTION rather than evidence. A `closer_rejected` is
    why a map legitimately keeps a claim its own skeptics refuted, so an overstated one turns an
    unfixed defect into a settled question."""
    m = make_grounded_model(claims_total=3, claims_challenged=3, claims_confirmed=2,
                            claims_refuted=1)
    grounding_of(m).closer_rejected = 1
    with tempfile.TemporaryDirectory() as td:
        model_path = make_verify_dir(Path(td), m, closer=("reject",))
        _, warnings = validate_model(m, model_path)
        assert not [w for w in warnings if CLOSER_LINE in w], warnings

        # The record claims an appeal the files do not show.
        grounding_of(m).closer_rejected = 2
        _, warnings = validate_model(m, model_path)
        hit = [w for w in warnings if CLOSER_LINE in w]
        assert len(hit) == 1, warnings
        assert "the record says 2, the files show 1" in hit[0], hit[0]
        assert "grounding write" in hit[0], "it must name the recompute"

        # …and the other direction: the closer ruled and the record never caught up.
        grounding_of(m).closer_rejected = 0
        model_path = make_verify_dir(Path(td), m, closer=("reject", "uphold"))
        hit = [w for w in validate_model(m, model_path)[1] if CLOSER_LINE in w]
        assert hit and "the record says 0, the files show 1" in hit[0], hit


def test_the_closer_check_is_ADVISORY_while_a_negative_appeal_count_BLOCKS():
    """The split is deliberate. The negative half is arithmetic on the MAP ALONE, so it blocks with
    its siblings. The comparison half reads files OUTSIDE the map, whose completeness nothing
    guarantees — a closer wave run after `grounding write`, a half-copied `verify/` — and blocking
    on that would fail a map that is right."""
    m = make_grounded_model(claims_total=3, claims_challenged=3, claims_confirmed=2,
                            claims_refuted=1)
    grounding_of(m).closer_rejected = 2
    with tempfile.TemporaryDirectory() as td:
        model_path = make_verify_dir(Path(td), m, closer=("reject",))
        problems, warnings = validate_model(m, model_path)
        assert [w for w in warnings if CLOSER_LINE in w]
        assert not [p for p in problems if CLOSER_LINE in p], "advisory, never a gate"

    grounding_of(m).closer_rejected = -1
    assert [p for p in problems_of(m) if "negative count(s)" in p and "closer_rejected" in p], \
        "a negative tally is arithmetic on the map alone and blocks"


def test_no_closer_evidence_means_the_check_SAYS_NOTHING_and_never_that_it_passed():
    """Every map built before the field existed has no closer file, and a clone may carry the map
    with no `verify/` at all. The guard is narrower than "the directory exists": the check runs only
    when the verify evidence is THERE, so a pruned `verify/` reads as "cannot check" rather than
    "checked and passed"."""
    m = make_grounded_model(claims_total=3, claims_challenged=3, claims_confirmed=2,
                            claims_refuted=1)
    grounding_of(m).closer_rejected = 2
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        model_path = make_verify_dir(root, m, closer=("reject",))
        # No `verify/` at all — the fresh-clone shape.
        for f in sorted((root / "verify").glob("*")):
            f.unlink()
        (root / "verify").rmdir()
        assert not [w for w in validate_model(m, model_path)[1] if CLOSER_LINE in w]

        # A `verify/` holding no verdict row is the same state wearing a directory.
        (root / "verify").mkdir()
        (root / "verify" / "budgets.json").write_text('{"budget": 4}', encoding="utf-8")
        assert not [w for w in validate_model(m, model_path)[1] if CLOSER_LINE in w]

        # …but the skeptics' rows being there and the closer's not IS checkable, and fires.
        model_path = make_verify_dir(root, m, skeptics=2)
        hit = [w for w in validate_model(m, model_path)[1] if CLOSER_LINE in w]
        assert hit and "no closer row at all" in hit[0], hit
    # And a call with no path at all must not go looking for files.
    assert not [w for w in warnings_of(m) if CLOSER_LINE in w]


def test_an_appeal_re_heard_in_a_SECOND_wave_is_two_rows_not_one_claim():
    """`grounding write` counts the closer's verdict WORDS, and the closer contract's own design is
    that a re-hearing is a second row. Counted here the same way, or the two drift."""
    m = make_grounded_model(claims_total=3, claims_challenged=3, claims_confirmed=2,
                            claims_refuted=1)
    grounding_of(m).closer_rejected = 2
    with tempfile.TemporaryDirectory() as td:
        model_path = make_verify_dir(Path(td), m, closer=("reject", "reject"))
        assert not [w for w in validate_model(m, model_path)[1] if CLOSER_LINE in w]


CLAIM_LOSS_LINE = "are GONE from the shipped map"


def make_pinned_worklist(root: Path, m: ProjectModel, *, drop: int = 0) -> Path:
    """The map on disk, with the claim surface it had BEFORE a correction pinned beside it.

    `drop` removes that many claims from the pin's live equivalent by pinning the map's own current
    worklist plus `drop` extra rows — the shape a `fix rows` leaves behind, where the pin holds
    claims the shipped map no longer makes."""
    from coyomap.audit_model import l2_worklist_model
    model_path = root / "project-map.json"
    model_path.write_text(to_canonical_json(m), encoding="utf-8")
    (root / "project-map.md").write_text(model_to_markdown(m), encoding="utf-8")
    rows = [{"claim": i.claim, "anchor": i.anchor, "theme": i.theme} for i in l2_worklist_model(m)]
    rows += [{"claim": f"a claim a correction removed ({n})", "anchor": "a.py:1", "theme": "rule"}
             for n in range(drop)]
    verify = root / "verify"
    verify.mkdir(exist_ok=True)
    (verify / "worklist.json").write_text(json.dumps({"worklist": rows}), encoding="utf-8")
    return model_path


def test_a_correction_that_removed_claims_nobody_re_stated_is_reported():
    """At turn 478 of one build a `fix rows` rewrote rule BR205's sites down to one entry, dropping
    two deploy anchors. Two of the three claims that rule generated went with them — the audit's
    `rule` theme fell from 103 on the pinned worklist to 100 on the shipped map — and the rule's own
    `risk` still asserts a fact about "two of the three deploy commands" that its single surviving
    anchor cannot support. `validate`, `audit` and `finalize` all saw nothing."""
    m = make_valid_model()
    with tempfile.TemporaryDirectory() as td:
        model_path = make_pinned_worklist(Path(td), m, drop=2)
        _, warnings = validate_model(m, model_path)
        hit = [w for w in warnings if CLAIM_LOSS_LINE in w]
        assert len(hit) == 1, warnings
        assert hit[0].startswith("2 claim(s)") and "rule" in hit[0], hit[0]
        assert "audit" in hit[0], "it must name the re-pin, which is the record"
        problems, _ = validate_model(m, model_path)
        assert not [p for p in problems if CLAIM_LOSS_LINE in p], "advisory, never a gate"


def test_a_map_whose_claims_all_survive_hears_nothing_and_so_does_one_with_no_pin():
    """Two silences that matter: the ordinary build removes no claim, and most maps have never run
    a verify pass at all, so there is no pin to compare against."""
    m = make_valid_model()
    with tempfile.TemporaryDirectory() as td:
        model_path = make_pinned_worklist(Path(td), m)
        _, warnings = validate_model(m, model_path)
        assert not [w for w in warnings if CLAIM_LOSS_LINE in w], warnings
        (Path(td) / "verify" / "worklist.json").unlink()
        _, warnings = validate_model(m, model_path)
        assert not [w for w in warnings if CLAIM_LOSS_LINE in w], warnings
    # No path at all — the profiler's shape — must not go looking for a file.
    assert not [w for w in warnings_of(m) if CLAIM_LOSS_LINE in w]


def test_a_claim_ADDED_since_the_pin_is_not_a_loss():
    """Growth is the healthy direction and has its own advisory (the shipped map carrying claims
    nobody challenged). Only a theme that SHRANK is a claim nobody re-stated."""
    m = make_valid_model()
    with tempfile.TemporaryDirectory() as td:
        model_path = make_pinned_worklist(Path(td), m)
        m.rules = [*m.rules, BusinessRule(id="BR99", name="A new rule",
                                          statement="Only an owner may act.",
                                          sites=[RuleSite(where="src/v.py:1")])]
        _, warnings = validate_model(m, model_path)
        assert not [w for w in warnings if CLAIM_LOSS_LINE in w], warnings


def test_full_live_coverage_is_silent():
    """The ordinary build rewords nothing after the vote, and must hear nothing about it."""
    m = make_grounded_model(claims_total=209, claims_challenged=209, claims_confirmed=209,
                            claims_live_challenged=209)
    assert not any("PINNED worklist, not the shipped map" in w for w in warnings_of(m))


def test_a_record_predating_the_live_count_falls_back_to_a_LOWER_bound():
    """Every map built before `claims_live_challenged` existed still carries `claims_added_since`,
    and a claim minted after the pin cannot have a verdict. That makes it a lower bound rather than
    the exact figure — a `--partial` pass can also leave a PINNED claim unvoted, which this cannot
    see. The message must say which of the two it is reading, because "at least 10" and "exactly 10"
    invite different next steps."""
    m = make_grounded_model(claims_total=209, claims_challenged=209, claims_confirmed=209,
                            claims_superseded=10, claims_added_since=10)
    hit = [w for w in warnings_of(m) if "PINNED worklist, not the shipped map" in w]
    assert len(hit) == 1
    assert "at least 10" in hit[0] and "lower bound" in hit[0]


def test_the_live_coverage_advisory_does_not_reuse_the_thin_coverage_threshold():
    """One unchallenged live claim in a large map is still a claim the record says was challenged,
    and an already-partial map is where a reader most needs to know which surface the number covers.
    This map is thin AND reworded; both advisories must fire, not one masking the other."""
    m = make_grounded_model(claims_total=1000, claims_challenged=100, claims_confirmed=100,
                            claims_superseded=0, claims_added_since=1,
                            claims_live_challenged=1000)
    warns = warnings_of(m)
    assert any("Grounding is partial" in w for w in warns), warns
    m2 = make_grounded_model(claims_total=1000, claims_challenged=1000, claims_confirmed=1000,
                             claims_superseded=0, claims_added_since=1,
                             claims_live_challenged=1000)
    assert any("PINNED worklist, not the shipped map" in w for w in warnings_of(m2))


def test_an_unverifiable_verdict_is_a_first_class_outcome():
    """`method.md` allows three verdicts (`true|false|"unverifiable"`). A two-term check would force a
    build to fold the third into one of the others, which is what makes a grounding record lie.

    Also pins that unverifiable does NOT count as coverage: an all-unverifiable map summed correctly,
    read as 100% challenged, and produced no finding at all — a map where nothing was verified passing
    in silence."""
    m = make_grounded_model(claims_total=399, claims_challenged=399, claims_confirmed=390,
                            claims_refuted=3, claims_unverifiable=6)
    assert not any("grounding" in p for p in problems_of(m))
    # drop the unverifiable count and the sum breaks — so the third term is load-bearing here
    grounding_of(m).claims_unverifiable = 0
    assert any("do not add up" in p for p in problems_of(m))
    # and a map where NOTHING held up is reported, however tidy its arithmetic
    none_held = make_grounded_model(claims_total=42, claims_challenged=42, claims_confirmed=0,
                                    claims_unverifiable=42)
    assert not any("grounding" in p for p in problems_of(none_held))
    assert any("0 of 42 claims confirmed" in w and "42 unverifiable" in w
               for w in warnings_of(none_held)), warnings_of(none_held)


def test_challenging_more_claims_than_the_worklist_held_is_blocking():
    m = make_grounded_model(claims_total=100, claims_challenged=120, claims_confirmed=120)
    assert any("exceeds claims_total" in p for p in problems_of(m))


def test_a_record_with_no_verdict_split_is_advisory_not_blocking():
    """The graceful half: a map that records only "N challenged" cannot be checked, so it is told to
    record the split — not failed. Blocking it would fail every map written before the split existed,
    for a shape that is incomplete rather than wrong."""
    m = make_grounded_model(claims_total=399, claims_challenged=399, claims_refuted=3)
    assert not any("grounding" in p for p in problems_of(m))
    assert any("no verdict SPLIT" in w for w in warnings_of(m))


def test_the_renamed_grounding_field_tells_the_reader_what_to_do():
    """An alpha format may break, but the break must be legible: a map written before the rename gets
    the new name and the reason, not a bare "unknown field"."""
    doc = json.dumps({"format": FORMAT, "title": "t", "goal": "g",
                      "grounding": {"claims_total": 9, "claims_grounded": 9}})
    try:
        load_model(doc)
        raise AssertionError("expected ModelError")
    except ModelError as e:
        assert "claims_challenged" in str(e) and "claims_confirmed" in str(e), str(e)


def test_ignore_exceptions_re_reads_the_map_with_every_recorded_line_dropped():
    """Several suppression messages end with "re-read the rest by validating a copy with the
    exception removed" — an instruction asking the operator to hand-edit a copy, which no build ever
    did. This flag IS that copy, made by the tool."""
    import subprocess
    import sys
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.json"
        p.write_text(json.dumps({
            "format": FORMAT, "title": "T", "goal": "g",
            "extras": [{"heading": "Balance exceptions", "body": "UC1: granularity — a why.\n"}],
        }), encoding="utf-8")
        plain = subprocess.run([sys.executable, "-m", "coyomap.validate_model", str(p)],
                               capture_output=True, text=True)
        rescan = subprocess.run([sys.executable, "-m", "coyomap.validate_model", str(p),
                                 "--ignore-exceptions"], capture_output=True, text=True)
        assert "--ignore-exceptions" in rescan.stdout
        assert "1 recorded line(s) were dropped" in rescan.stdout
        # and it is a READ: the file on disk is untouched
        assert "Balance exceptions" in p.read_text()
        assert "recorded line(s) were dropped" not in plain.stdout


def test_ignore_exceptions_does_not_report_a_stale_view_on_a_current_one():
    """The flag strips the recorded lines from the IN-MEMORY model, and the view-freshness check
    re-renders that model and compares it to `project-map.md` on disk. So the one command
    `method.md` prescribes for re-reading exceptions told the operator their view was stale — on
    every map carrying any recorded exception, and on a view byte-identical to a fresh `render`.

    The A/B is the whole test: the same map, the same `.md`, with and without the flag."""
    import subprocess
    import sys
    from coyomap.views import model_to_markdown
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "project-map.json"
        doc = {"format": FORMAT, "title": "T", "goal": "g",
               "extras": [{"heading": "Balance exceptions", "body": "UC1: granularity — a why.\n"}]}
        p.write_text(json.dumps(doc), encoding="utf-8")
        # A view that IS current, written the way `coyomap render` writes it.
        (Path(tmp) / "project-map.md").write_text(
            model_to_markdown(load_model(p.read_text(encoding="utf-8"))), encoding="utf-8")
        plain = subprocess.run([sys.executable, "-m", "coyomap.validate_model", str(p)],
                               capture_output=True, text=True)
        rescan = subprocess.run([sys.executable, "-m", "coyomap.validate_model", str(p),
                                 "--ignore-exceptions"], capture_output=True, text=True)
        assert "differs from the view generated" not in plain.stdout, plain.stdout
        assert "differs from the view generated" not in rescan.stdout, rescan.stdout
        # …and the flag still did its job, so the silence is not the flag having become a no-op.
        assert "1 recorded line(s) were dropped" in rescan.stdout


def test_a_genuinely_stale_view_is_still_caught_without_the_flag():
    """The suppression above is scoped to the edited-model run. A plain `validate` must still say
    so, or the fix would have traded a false report for a missed one."""
    import subprocess
    import sys
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "project-map.json"
        p.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g"}), encoding="utf-8")
        (Path(tmp) / "project-map.md").write_text("hand-edited\n", encoding="utf-8")
        plain = subprocess.run([sys.executable, "-m", "coyomap.validate_model", str(p)],
                               capture_output=True, text=True)
        assert "differs from the view generated" in plain.stdout, plain.stdout


def test_one_scoped_runs_in_record_does_not_silence_a_sibling_group():
    """The whole point of scoping: a justification about one finding must not switch off another.
    A live map recorded `runs-in` for two test-profile containers and thereby hid a real
    regression — six of eight deployment units had stopped hosting any component."""
    m = make_multi_family_runs_in_model()
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="runs-in/messaging: the bus lives outside this repo.")]
    ws = warnings_of(m)
    assert not any("cannot place this channel" in w for w in ws), "its OWN group is silenced"
    assert any("Unplaced" in w for w in ws), "a sibling group must survive untouched"
    hits = [w for w in ws if "suppressed by recorded scoped exception(s)" in w]
    assert len(hits) == 1 and "runs-in/messaging" in hits[0]
    assert "self-started entry points" not in hits[0], "only the silenced group is named"


# ── the pin-delta fields, whose three guards shipped uncovered ───────────────────────────────────

def test_superseded_above_the_pinned_total_is_blocking():
    """A superseded claim is one that WAS pinned, so it cannot exceed `claims_total`. Bounded by
    total and NOT by `challenged`: those are equal only because `grounding write` refuses an unvoted
    pinned claim, and its own error offers "challenge a smaller worklist deliberately" as the way
    out — so `total 100 / challenged 50 / superseded 60` is legitimate and must not be blocked."""
    m = make_grounded_model(claims_total=10, claims_challenged=10, claims_confirmed=10,
                            claims_superseded=11)
    assert any("cannot exceed `claims_total`" in p for p in problems_of(m))
    ok = make_grounded_model(claims_total=100, claims_challenged=50, claims_confirmed=50,
                             claims_superseded=60)
    assert not any("cannot exceed `claims_total`" in p for p in problems_of(ok))


def test_a_negative_pin_delta_is_blocking():
    """A negative count can BALANCE an equality — the reason the negatives check exists at all —
    and `total - superseded` is exactly such a sum."""
    m = make_grounded_model(claims_total=10, claims_challenged=10, claims_confirmed=10,
                            claims_added_since=-3)
    assert any("negative count" in p and "claims_added_since" in p for p in problems_of(m))


def test_a_record_carrying_only_a_pin_delta_still_reaches_the_checks():
    """`_any_grounding_count` gates every grounding check. A record with only `claims_added_since`
    would otherwise skip all of them — the same hole that function was written to close."""
    m = make_grounded_model(claims_added_since=4)
    # A GROUNDING finding specifically — the model has unrelated warnings, so "any warning at all"
    # passes even with the gate reverted, which is how this test first shipped proving nothing.
    assert any("`grounding`" in w for w in warnings_of(m)), (
        "a record carrying only a pin-delta must still reach the grounding checks")


def test_a_recorded_runs_in_key_that_silences_nothing_is_named():
    """A correctly spelled key whose advisory is NOT firing suppresses nothing and, until now, said
    nothing — so an inert record and a typo'd one were indistinguishable. A live map recorded three
    scoped keys; the count line named two groups, and removing the third changed no output at all.
    The build read that line three times and never noticed.

    `assemble` already reports a `keep_edges` directive that matches nothing, and `reconcile` every
    rule that matched nothing; this was the one escape family with no such signal."""
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="standalone"), DeploymentRow(unit="worker")]
    m.components[0].runs_in = ["standalone"]
    # `runs-in/quality` is doing real work here; `runs-in/messaging` names a group with no findings.
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="runs-in/quality: it truly is one process.\n"
                                  "runs-in/messaging: the far ends are all third-party.")]
    ws = warnings_of(m)
    inert = [w for w in ws if "currently suppressing nothing" in w]
    assert len(inert) == 1, ws
    assert "runs-in/messaging" in inert[0], inert
    assert "runs-in/quality" not in inert[0], "the key that IS suppressing must not be named"


def test_no_inert_line_when_every_recorded_key_suppresses_something():
    """The line must stay quiet on an honest record, or it becomes noise every build learns to skip."""
    m = make_valid_model()
    m.deployment = [DeploymentRow(unit="standalone"), DeploymentRow(unit="worker")]
    m.components[0].runs_in = ["standalone"]
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="runs-in/quality: it truly is one process.")]
    assert not any("currently suppressing nothing" in w for w in warnings_of(m))


def test_the_inert_record_phrase_has_exactly_one_producer():
    """L3 assertion 24 recognises this finding by the literal phrase, so a second advisory using the
    same words would make it report a silent false 0. Pinning the phrase here means the assertion
    and its producer cannot drift apart unnoticed."""
    src = (Path(__file__).resolve().parent.parent
           / "tools" / "coyomap" / "validate_model.py").read_text(encoding="utf-8")
    assert src.count("currently suppressing nothing") == 1, (
        "assertion 24 keys on this phrase; a second producer makes its 0 ambiguous")


# --- capability-level spine membership + two-arm entry-point claiming (plan/60 Step 3) ----------

def make_capability_model() -> ProjectModel:
    """Two capabilities, one `expected` and one `excluded`, each with an on-spine and an off-spine
    member."""
    m = make_valid_model()
    m.capabilities = [Group(id="CAP1", name="Ordering", happy_path="expected"),
                      Group(id="CAP2", name="Reporting", happy_path="excluded")]
    m.use_cases = [UseCase(id="UC1", name="Place order", actors=["R1"], capability="CAP1"),
                   UseCase(id="UC2", name="Amend order", actors=["R1"], capability="CAP1"),
                   UseCase(id="UC3", name="Read report", actors=["R1"], capability="CAP2")]
    m.happy_path = [HappyStep(id="HP1", uc="UC1")]
    m.flows = [Flow(uc=u.id, title=u.name, steps=[FlowStep(n=1, src="R1", dst="C1", phrase="does")])
               for u in m.use_cases]
    return m


def test_an_expected_capability_off_the_spine_warns_once_not_per_use_case() -> None:
    m = make_capability_model()
    m.happy_path = [HappyStep(id="HP1", uc="UC3")]   # only the excluded one walks
    ws = warnings_of(m)
    assert any("CAP1" in w and "no Happy-Path step reaches it" in w for w in ws)
    # the two CAP1 members are NOT each nagged about — that is the whole point of moving altitude
    assert not any("off the Happy-Path spine and unrecorded" in w for w in ws)


def test_off_spine_members_of_an_expected_capability_are_silent_when_the_capability_walks() -> None:
    """UC2 is off the walk and produces no warning — accepted, and counted instead."""
    m = make_capability_model()
    ws = warnings_of(m)
    assert not any("UC2" in w and "spine" in w for w in ws)
    assert validate_model_mod.completeness_counts(m)["off_spine_in_expected_capabilities"] == 1


# --- audience: authored once on the ROLE, derived up to the capability ---------------------------
# The predecessor was a three-value `label` on the CAPABILITY carrying this question AND the walk
# question in one word. Two of its three values had no definition in any file and no branch ever
# distinguished them, so the audience half was unenforced and drifted between rebuilds of the same
# repo. Authored on the role, derived up, nothing on the capability can contradict its own actors.

def make_audience_model() -> ProjectModel:
    """A customer feature and a staff feature, plus one machine actor that serves BOTH sides."""
    m = make_capability_model()
    m.roles = [Role(id="R1", name="Customer", kind="human", audience="user"),
               Role(id="R2", name="Operator", kind="human", audience="internal"),
               Role(id="R3", name="Scheduler", kind="service", audience="internal")]
    m.use_cases[2].actors = ["R2"]                        # UC3 (CAP2) is the staff one
    return m


def test_a_capabilitys_audience_is_derived_from_the_roles_driving_its_use_cases() -> None:
    m = make_audience_model()
    assert validate_model_mod.capability_audience(m) == {"CAP1": ["user"], "CAP2": ["internal"]}
    assert not any("audiences" in w for w in warnings_of(m))


def test_only_human_roles_vote_and_machines_are_the_fallback() -> None:
    """A machine actor is the product doing work on someone's behalf, and one scheduler routinely
    fires a customer's work AND the company's own upkeep. Letting machines vote turned 3 of 27
    capabilities `mixed` on the live maps, two of them falsely."""
    m = make_audience_model()
    m.use_cases[0].actors = ["R1", "R3"]                  # staff-tagged machine inside a user feature
    assert validate_model_mod.capability_audience(m)["CAP1"] == ["user"]
    m.use_cases[0].actors = ["R3"]                        # no human left: the machine answers
    m.use_cases[1].actors = ["R3"]
    assert validate_model_mod.capability_audience(m)["CAP1"] == ["internal"]


def test_a_capability_driven_by_both_sides_warns_and_can_be_recorded() -> None:
    """The one cross-check the tag buys. On the three live maps it fires exactly once, on a demo
    site an outside visitor browses and the company's own administrator operates."""
    m = make_audience_model()
    m.use_cases[1].actors = ["R2"]                        # CAP1 now holds a user AND a staff use case
    # BOTH words, never a "mixed" sentinel: the views show two pills, and a surface that really does
    # serve both sides keeps an honest answer after the operator records it.
    assert validate_model_mod.capability_audience(m)["CAP1"] == ["user", "internal"]
    assert any("CAP1" in w and "both `user` and `internal`" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Audience exceptions",
                             body="CAP1: the status page is the one surface both sides read")]
    assert not any("CAP1" in w and "both `user` and `internal`" in w for w in warnings_of(m))


def test_an_audience_outside_the_closed_vocabulary_blocks() -> None:
    m = make_audience_model()
    m.roles[0].audience = "customer"
    assert any("R1" in p and "unknown `audience`" in p for p in problems_of(m))


def test_an_untagged_role_warns_only_once_the_axis_is_adopted() -> None:
    """Graceful degradation, the same shape a project with no environments gets: silent while NO
    role carries an audience, a real hole the moment one does."""
    m = make_audience_model()
    assert not any("no `audience`" in w for w in warnings_of(m))
    m.roles[1].audience = ""
    assert any("R2" in w and "no `audience`" in w for w in warnings_of(m))
    for r in m.roles:
        r.audience = ""
    assert not any("no `audience`" in w for w in warnings_of(m))


def test_a_spine_step_in_an_excluded_capability_warns_and_can_be_recorded() -> None:
    """The converse direction — the one a single-direction check cannot produce."""
    m = make_capability_model()
    m.happy_path.append(HappyStep(id="HP2", uc="UC3"))
    assert any("HP2" in w and "happy_path: excluded" in w for w in warnings_of(m))
    m.extras = [ExtraSection(heading="Happy Path coverage",
                             body="HP2: the operator reads the report as part of the main walk")]
    assert not any("HP2" in w and "happy_path: excluded" in w for w in warnings_of(m))


def test_a_capability_with_no_happy_path_value_warns_once_the_axis_is_adopted() -> None:
    """"Nobody decided" is its own state and must never read as `excluded` — the hole the old
    three-value `label` had, where an empty value silently meant "deliberately off the walk". It is
    also why the field is a word pair and not a boolean: `false` cannot carry "undecided".

    Silent while NO capability carries one, so a map that has not adopted the axis degrades the way
    a project with no environments does."""
    m = make_capability_model()
    m.capabilities[1].happy_path = ""
    assert any("CAP2" in w and "no `happy_path` expectation" in w for w in warnings_of(m))
    m.capabilities[0].happy_path = ""                    # nobody has one now: un-adopted, not a gap
    assert not any("no `happy_path` expectation" in w for w in warnings_of(m))


def test_a_staff_capability_on_the_walk_costs_no_record() -> None:
    """The 2x2 cell the old three-value label had no word for. `platform` and `supporting` were both
    read as "not core", so a spine step in staff work demanded a written excuse — six of them across
    the three live maps. Audience is not read by the Coverage rule at all now."""
    m = make_capability_model()
    m.roles = [Role(id="R1", name="Operator", kind="human", audience="internal")]
    m.capabilities[1].happy_path = "expected"
    m.happy_path.append(HappyStep(id="HP2", uc="UC3"))
    ws = warnings_of(m)
    assert not any("HP2" in w for w in ws)
    assert validate_model_mod.capability_audience(m)["CAP2"] == ["internal"]


def test_an_excluded_capability_holding_off_spine_use_cases_needs_one_record() -> None:
    m = make_capability_model()
    ws = warnings_of(m)
    assert any("CAP2" in w and "off-spine use case" in w for w in ws)
    m.extras = [ExtraSection(heading="Happy Path coverage",
                             body="CAP2: reporting is side work, deliberately off the walk")]
    assert not any("CAP2" in w and "off-spine use case" in w for w in warnings_of(m))


def test_without_capabilities_the_per_use_case_off_spine_check_still_runs() -> None:
    """Additivity: a map that has not adopted the grouping keeps exactly the old behaviour."""
    m = make_capability_model()
    m.capabilities = []
    for u in m.use_cases:
        u.capability = None
    ws = warnings_of(m)
    assert sum("off the Happy-Path spine and unrecorded" in w for w in ws) == 2   # UC2, UC3


def make_entry_point_model() -> ProjectModel:
    """C2 owns an external surface and NO flow reaches it — the unclaimed case."""
    m = make_valid_model()
    m.components.append(Component(id="C2", name="Admin", purpose="admin", source="src/adm.py:1"))
    m.entry_points = [EntryPoint(id="EP1", kind="HTTP route", trigger="GET /admin",
                                 source="src/adm.py:9", component="C2", activation="external")]
    return m


def test_the_trigger_arm_claims_a_surface_no_flow_reaches() -> None:
    """Two arms: the flow's component reach is primary, and a use case naming the entry point
    claims it too — which is what lets the cross-check run before any tracing exists."""
    m = make_entry_point_model()
    assert any("C2" in w and "unclaimed by any use case" in w for w in warnings_of(m))
    m.use_cases[0].entry_points = ["EP1"]
    assert not any("C2" in w and "unclaimed by any use case" in w for w in warnings_of(m))


def test_self_activated_surfaces_are_no_longer_exempt() -> None:
    """A cron used to be silently exempt, which hid whole background capabilities. Now it is a
    decision — and the warning says plainly that a record is often the honest answer."""
    m = make_entry_point_model()
    m.entry_points = [EntryPoint(id="EP1", kind="cron job", trigger="nightly rollup",
                                 source="src/adm.py:9", component="C2", activation="self")]
    def unclaimed(ws: list[str]) -> list[str]:   # not the cadence advisory, which also says "self-activated"
        return [w for w in ws if "no use case reaches" in w]
    ws = warnings_of(m)
    assert any("C2" in w and "self-activated" in w for w in unclaimed(ws))
    assert any("often has no actor to claim it" in w for w in ws)
    m.extras = [ExtraSection(heading="Unclaimed surfaces", body="C2: nightly rollup, no actor")]
    assert not unclaimed(warnings_of(m))


def test_a_use_case_in_no_capability_is_reported() -> None:
    """The silent-loss regression. Once capabilities exist EVERY coverage check keys off membership,
    so a use case with an empty or typo'd `capability` fell through all of them AND out of the
    counts — reported by nothing at all. That is not the documented trade (an off-spine member of a
    CORE capability is counted instead of warned); it is a hole. The other two forests have had the
    symmetric advisory all along ("Entities with no SUBDOMAIN")."""
    m = make_capability_model()
    m.use_cases[1].capability = None
    assert any("no capability" in w and "UC2" in w for w in warnings_of(m))


def test_a_dangling_capability_or_entry_point_reference_blocks() -> None:
    """All three new pointers were wired into the readers and into none of the validators, so a typo
    silently turned the coverage check off for that use case instead of failing loudly."""
    m = make_capability_model()
    m.use_cases[0].capability = "CAP99"
    assert any("CAP99" in p for p in problems_of(m))
    m = make_capability_model()
    m.capabilities.append(Group(id="CAP3", name="Orphan", parent="CAP404", happy_path="expected"))
    assert any("CAP404" in p for p in problems_of(m))
    m = make_capability_model()
    m.use_cases[0].entry_points = ["EP7"]
    assert any("EP7" in p for p in problems_of(m))


def test_a_cycle_in_the_capability_forest_blocks() -> None:
    """`capability_members` guards against hanging, but a cycle is a MAP defect and validate owns
    it — as it already does for the subsystem and subdomain forests."""
    m = make_capability_model()
    m.capabilities[0].parent = "CAP2"
    m.capabilities[1].parent = "CAP1"
    assert any("cycle" in p.lower() for p in problems_of(m))


def test_a_stale_record_cannot_silence_the_other_capability_check() -> None:
    """One record silences exactly one (check, id) pair. Sharing the `recorded` test across both
    branches meant a line written about an EXCLUDED capability's off-spine members kept hiding a
    real coverage gap after the capability was flipped to `expected`."""
    m = make_capability_model()
    m.extras = [ExtraSection(heading="Happy Path coverage",
                             body="CAP2: reporting is side work, deliberately off the walk")]
    assert not any("CAP2" in w and "off-spine use case" in w for w in warnings_of(m))
    m.capabilities[1].happy_path = "expected"   # flipped; the old record must not cover this
    m.happy_path = [HappyStep(id="HP1", uc="UC1")]
    assert any("CAP2" in w and "no Happy-Path step reaches" in w for w in warnings_of(m))


def test_an_unreached_expected_subtree_reports_once_at_its_highest_ancestor() -> None:
    """A three-node `expected` tree with nothing on the walk is ONE absence, not three warnings — and a
    record on the root retires the whole subtree, which is what "one line covers it" has to mean."""
    m = make_capability_model()
    m.capabilities = [Group(id="CAP1", name="Commerce", happy_path="expected"),
                      Group(id="CAP2", name="Ordering", parent="CAP1", happy_path="expected"),
                      Group(id="CAP3", name="Fulfilment", parent="CAP1", happy_path="expected")]
    m.use_cases = [UseCase(id="UC1", name="Order", actors=["R1"], capability="CAP2"),
                   UseCase(id="UC2", name="Ship", actors=["R1"], capability="CAP3")]
    m.flows = [Flow(uc=u.id, title=u.name,
                    steps=[FlowStep(n=1, src="R1", dst="C1", phrase="does")]) for u in m.use_cases]
    # a walk exists (an empty one would trip the additivity guard and skip the family) but it
    # reaches nothing in the core subtree
    m.use_cases.append(UseCase(id="UC9", name="Elsewhere", actors=["R1"], capability="CAP1x"))
    m.capabilities.append(Group(id="CAP1x", name="Other", happy_path="excluded"))
    m.flows.append(Flow(uc="UC9", title="Elsewhere",
                        steps=[FlowStep(n=1, src="R1", dst="C1", phrase="does")]))
    m.happy_path = [HappyStep(id="HP1", uc="UC9")]
    hits = [w for w in warnings_of(m) if "no Happy-Path step reaches" in w]
    assert len(hits) == 1 and "CAP1" in hits[0], hits
    m.extras = [ExtraSection(heading="Happy Path coverage",
                             body="CAP1/spine: pre-launch, the walk does not cover commerce yet")]
    assert not [w for w in warnings_of(m) if "no Happy-Path step reaches" in w]


# --- project-extensible bucket vocabulary ----------------------------------------
# A project whose real vocabulary needs a bucket the library seeds never named was told to rename it
# on EVERY rebuild, forever — and the advice contradicted itself, because reusing the previous map's
# spelling for stability is exactly what earned the warning.


def make_bucket_model(bucket: str, extras: list[dict] | None = None) -> dict:
    return {
        "format": FORMAT, "title": "t", "goal": "g",
        "use_cases": [{"id": "UC1", "name": "Do"}],
        "components": [{"id": "C1", "name": "A", "source": "a.py:1"}],
        "deps": [{"id": "D1", "name": "somelib", "kind": "library", "bucket": bucket,
                  "used_for": "things"}],
        "extras": extras or [],
    }


def test_a_minted_library_bucket_still_nudges_by_default():
    m = load_model(json.dumps(make_bucket_model("MCP protocol")))
    _problems, warnings = validate_model_mod._check_dep_buckets(m)
    assert any("'MCP protocol' is minted" in w for w in warnings)
    assert any("Bucket vocabulary" in w for w in warnings)


def test_a_declared_bucket_stops_nudging_and_says_it_was_silenced():
    m = load_model(json.dumps(make_bucket_model("MCP protocol", extras=[
        {"heading": "Bucket vocabulary",
         "body": "MCP protocol: this product IS an MCP gateway; the seeds name nothing close"}])))
    _problems, warnings = validate_model_mod._check_dep_buckets(m)
    assert not any("'MCP protocol' is minted" in w for w in warnings)
    # A silence you cannot see reads exactly like having no findings.
    assert any("NOT re-nudged" in w and "MCP protocol" in w for w in warnings)


def test_declaring_one_bucket_does_not_silence_another():
    m = load_model(json.dumps(make_bucket_model("MCP protocol", extras=[
        {"heading": "Bucket vocabulary", "body": "Build & tooling: the repo's own toolchain"}])))
    _problems, warnings = validate_model_mod._check_dep_buckets(m)
    assert any("'MCP protocol' is minted" in w for w in warnings)


def make_security_dup_model(rows: list[dict], extras: list[dict] | None = None) -> dict:
    return {
        "format": FORMAT, "title": "t", "goal": "g",
        "use_cases": [{"id": "UC1", "name": "Do"}],
        "components": [{"id": "C1", "name": "A", "source": "a.py:1"}],
        "security": rows, "extras": extras or [],
    }


def test_an_accepted_duplication_silences_only_its_own_surface():
    """A substring test let ONE adjudication silence a DIFFERENT duplicate: recording the long
    URL-shaped surface also suppressed an un-adjudicated duplicate of the short one, because the
    short name is a substring of the long line."""
    long_surface = "Admin pages (/orgs/:slug/admin/**)"
    m = load_model(json.dumps(make_security_dup_model(
        [{"surface": long_surface, "source": "a.tsx:1"},
         {"surface": long_surface, "source": "b.tsx:2"},
         {"surface": "Admin pages", "source": "c.tsx:3"},
         {"surface": "Admin pages", "source": "d.tsx:4"}],
        extras=[{"heading": "Accepted duplications",
                 "body": f"{long_surface}: two fragments, both anchors real"}])))
    warnings = validate_model_mod.duplicate_security_warnings(m)
    # The recorded one is silenced (and the silence is reported) …
    assert any("suppressed by a recorded" in w and long_surface in w for w in warnings)
    # … and the OTHER duplicate still fires. A surface that contains a colon must still key.
    assert any(w.startswith("security surface 'Admin pages' is authored 2 times") for w in warnings)


def test_a_duplicate_security_surface_warns_and_names_the_verb():
    m = load_model(json.dumps(make_security_dup_model(
        [{"surface": "Login", "source": "a.py:1"}, {"surface": "Login", "source": "b.py:2"}])))
    warnings = validate_model_mod.duplicate_security_warnings(m)
    assert any("fix dedup-security" in w for w in warnings)


def test_two_surfaces_sharing_one_anchor_are_not_a_duplicate():
    """One line can legitimately guard two things; calling that duplication is the mistake that
    let a hand script delete a real claim."""
    m = load_model(json.dumps(make_security_dup_model(
        [{"surface": "Admin pages", "source": "ui/Sidebar.tsx:97"},
         {"surface": "Role-gated navigation", "source": "ui/Sidebar.tsx:97"}])))
    assert validate_model_mod.duplicate_security_warnings(m) == []


# --- the access surface: read from rules[access], not the emptied security[] ------------

def make_model_with_access_rules(n: int = 2) -> ProjectModel:
    """A valid map carrying `n` access rules and no `security[]` — the shape EVERY map built since
    the T7 fold has, and the shape both real 2026-08-12 builds shipped."""
    m = make_valid_model()
    m.rules = [BusinessRule(id=f"BR{i + 1}", name="Test rule", statement=f"Only an owner may act ({i + 1}).",
                            access=True, risk="privilege escalation",
                            sites=[RuleSite(where=f"src/a.py:{10 + i}", why="rejects a non-owner")])
               for i in range(n)]
    return m


def test_the_inventory_reports_the_access_surface_from_the_rules():
    """The inventory's access line was gated on `if m.security:`, which the T7 fold empties — so on a
    post-fold map it printed nothing at all. Two real builds carrying 47 and 44 access rules showed
    no access count and no granularity state."""
    line = _inventory(make_model_with_access_rules(3))
    assert "access:3" in line, line
    assert "granularity NOT recorded" in line, line


def test_the_inventory_says_nothing_about_access_when_the_map_has_none():
    assert "access:" not in _inventory(make_valid_model())


def test_access_rules_with_no_recorded_granularity_are_advised():
    """method.md requires the granularity choice be recorded, because one row per surface FAMILY and
    one per endpoint-and-condition differ ~5x on the same code. The safeguard that echoed it was dead
    code post-fold, and neither real build recorded anything."""
    hits = [w for w in warnings_of(make_model_with_access_rules())
            if "no granularity record" in w]
    assert len(hits) == 1, hits
    assert "security-granularity" in hits[0] and "Balance exceptions" in hits[0]


def test_a_recorded_granularity_silences_the_advisory():
    """The escape the message names must actually work, or the advisory re-fires forever and gets
    waved through — the failure the method names in its own words."""
    m = make_model_with_access_rules()
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="security-granularity: family — one row per surface family.")]
    assert not [w for w in warnings_of(m) if "no granularity record" in w]


def test_a_map_with_no_access_rules_is_not_asked_for_a_granularity():
    """A map with no access surface has no choice to declare, so the advisory must stay quiet."""
    assert not [w for w in warnings_of(make_valid_model()) if "no granularity record" in w]


# --- a map with only its generated views is NAMED (retro 2026-08-14) ------------------------------
# One repo sits in this state: `project-map.md` and `project-map.html` present, the model gone. The
# views still look authoritative to a reader, and `ERROR: … not found` reads as "no coyomap here"
# when in fact a build ran and its source was lost. The recovery differs from an empty directory's.

def test_views_without_a_model_are_reported_as_such(capsys):
    import tempfile

    from coyomap import validate_model as vm

    with tempfile.TemporaryDirectory() as td:
        coy = Path(td) / ".coyomap"
        coy.mkdir()
        (coy / "project-map.md").write_text("# a rendered map\n", encoding="utf-8")
        (coy / "project-map.html").write_text("<html></html>", encoding="utf-8")
        assert vm.main([str(coy / "project-map.json")]) == 1
        err = capsys.readouterr().err
        assert "project-map.md" in err and "project-map.html" in err, err
        assert "GENERATED views" in err, err
        assert "build-fragments" in err, err


def test_an_empty_map_directory_keeps_the_plain_not_found(capsys):
    import tempfile

    from coyomap import validate_model as vm

    with tempfile.TemporaryDirectory() as td:
        coy = Path(td) / ".coyomap"
        coy.mkdir()
        assert vm.main([str(coy / "project-map.json")]) == 1
        err = capsys.readouterr().err
        assert "not found" in err
        assert "GENERATED views" not in err, err


def test_only_the_markdown_view_surviving_is_still_reported(capsys):
    import tempfile

    from coyomap import validate_model as vm

    with tempfile.TemporaryDirectory() as td:
        coy = Path(td) / ".coyomap"
        coy.mkdir()
        (coy / "project-map.md").write_text("# a rendered map\n", encoding="utf-8")
        assert vm.main([str(coy / "project-map.json")]) == 1
        err = capsys.readouterr().err
        assert "project-map.md" in err and "project-map.html" not in err, err


def test_the_duplication_advisory_still_fires_at_validate():
    """The other half of `test_the_duplication_advisory_does_not_fire_at_fragment_lint`.

    Moving it out of the fragment lint must not lose it: at `validate` the model carries the whole
    map, so the 'Accepted duplications' escape the message names is actually readable, and the
    advisory is answerable.
    """
    from coyomap.validate_model import _duplication_warnings
    from coyomap.model import load_model
    steps = [{"n": i, "src": "C70", "dst": "C1", "phrase": f"does thing {i}",
              "where": f"a.py:{i}"} for i in range(1, 5)]
    base = {
        "format": "coyomap-map", "title": "T", "goal": "g", "commit": "abc1234",
        "components": [{"id": "C70", "name": "G", "purpose": "p"},
                       {"id": "C1", "name": "P", "purpose": "p"}],
        "use_cases": [{"id": "UC13", "name": "A", "actors": ["Dev"], "trigger": "t", "outcome": ""},
                      {"id": "UC15", "name": "B", "actors": ["Dev"], "trigger": "t", "outcome": ""}],
        "flows": [{"uc": "UC13", "title": "A", "steps": steps},
                  {"uc": "UC15", "title": "B", "steps": steps}],
    }
    fired = _duplication_warnings(load_model(json.dumps(base)))
    assert [w for w in fired if "UC13 and UC15 share a run of" in w], fired

    # And the escape works where it is readable.
    base["extras"] = [{"heading": "Accepted duplications", "body": "UC13 & UC15: one path, two doors"}]
    assert not _duplication_warnings(load_model(json.dumps(base))), "the recorded escape must silence it"


def test_validate_names_the_writer_command_when_an_advisory_asks_for_a_record(capsys, tmp_path):
    """Sixty advisory strings end by naming an extras heading, and none named what writes one.

    `coyomap record` is named six times in `method.md` and a measured build used it ZERO times —
    against forty on the build before — hand-appending every record with a `python3` heredoc,
    which is the anti-pattern `record --help` opens by quoting. One of those hand-written lines
    keyed no ids and cost three extra finalize rounds. A footer, not sixty rewritten strings: the
    sentence lands once and stays right.
    """
    from coyomap import validate_model
    steps = [{"n": i, "src": "C70", "dst": "C1", "phrase": f"does thing {i}",
              "where": f"a.py:{i}"} for i in range(1, 5)]
    doc = {
        "format": "coyomap-map", "title": "T", "goal": "g", "commit": "abc1234",
        "components": [{"id": "C70", "name": "G", "purpose": "p"},
                       {"id": "C1", "name": "P", "purpose": "p"}],
        "use_cases": [{"id": "UC13", "name": "A", "actors": ["Dev"], "trigger": "t", "outcome": ""},
                      {"id": "UC15", "name": "B", "actors": ["Dev"], "trigger": "t", "outcome": ""}],
        "flows": [{"uc": "UC13", "title": "A", "steps": steps},
                  {"uc": "UC15", "title": "B", "steps": steps}],
    }
    p = tmp_path / "map.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    validate_model.main([str(p)])
    out = capsys.readouterr().out
    assert "share a run of" in out, "the fixture must raise an advisory that names a heading"
    assert "coyomap record --map" in out, out
    assert "shape-checks" in out, "it must say why the command beats a heredoc"

    # A map raising no advisory that names a heading gets no footer: the line appears where there
    # is something to record, not on every run. (Verified on a real map too — the 2026-08-18
    # mcpolis map has every escape recorded and prints no footer.)
    quiet = {"format": "coyomap-map", "title": "T", "goal": "g", "commit": "abc1234",
             "components": [{"id": "C70", "name": "G", "purpose": "p"}]}
    q = tmp_path / "quiet.json"
    q.write_text(json.dumps(quiet), encoding="utf-8")
    validate_model.main([str(q)])
    quiet_out = capsys.readouterr().out
    if "extras heading" not in quiet_out:
        assert "coyomap record --map" not in quiet_out, quiet_out


# --- role relations: referential integrity plus the closed kind pair, nothing more ---------------

def make_related_roles_model() -> ProjectModel:
    m = make_valid_model()
    m.roles = [Role(id="R1", name="Prospect", kind="human", audience="user", wants="to start",
                    relations=[RoleRelation(kind="becomes", role="R2", at="UC1")]),
               Role(id="R2", name="Admin", kind="human", audience="user", wants="to run it",
                    relations=[RoleRelation(kind="includes", role="R1")])]
    m.use_cases[0].actors = ["R1"]
    m.flows[0].steps[0].src = "R1"
    return m


def test_role_relations_that_resolve_pass_clean() -> None:
    assert not any("relations" in p or "undefined IDs" in p
                   for p in problems_of(make_related_roles_model()))


def test_a_relation_naming_an_undefined_role_or_use_case_is_a_dangling_reference() -> None:
    m = make_related_roles_model()
    m.roles[0].relations = [RoleRelation(kind="becomes", role="R9", at="UC7")]
    joined = " ".join(problems_of(m))
    assert "References to undefined IDs" in joined
    assert "R9" in joined and "UC7" in joined


def test_an_unknown_relation_kind_is_blocking() -> None:
    m = make_related_roles_model()
    m.roles[0].relations = [RoleRelation(kind="supersedes", role="R2")]
    assert any("unknown `kind` 'supersedes'" in p for p in problems_of(m))


def test_a_becomes_without_its_transition_use_case_is_blocking() -> None:
    m = make_related_roles_model()
    m.roles[0].relations = [RoleRelation(kind="becomes", role="R2")]
    assert any("R1.relations[0]" in p and "`at`" in p for p in problems_of(m))


def test_relation_semantics_are_not_over_constrained() -> None:
    """A `becomes` whose `at` use case does not list both roles, a self-reference and a symmetric
    include pair are all the retro's business (or the author's), never validate's."""
    m = make_related_roles_model()
    m.roles[1].relations = [RoleRelation(kind="includes", role="R2"),   # self-reference
                            RoleRelation(kind="includes", role="R1")]   # symmetric with R1? fine
    m.roles[0].relations.append(RoleRelation(kind="includes", role="R2"))
    assert not any("relations" in p for p in problems_of(m))


# --- story anchors: a capability field, shape + referential integrity and nothing more -----------

def make_story_anchored_model() -> ProjectModel:
    m = make_valid_model()
    m.capabilities = [Group(id="CAP1", name="Billing", purpose="p", happy_path="expected"),
                      Group(id="CAP2", name="Marketing", purpose="p", happy_path="excluded",
                            story=StoryAnchor(place="before", feature="CAP1"))]
    m.use_cases[0].capability = "CAP1"
    return m


def test_a_resolving_story_anchor_passes_clean() -> None:
    assert not any("story" in p or "undefined IDs" in p for p in problems_of(make_story_anchored_model()))


def test_a_story_anchor_is_blocked_off_the_capability_forest() -> None:
    m = make_story_anchored_model()
    m.subsystems = [Group(id="S1", name="Core", purpose="p",
                          story=StoryAnchor(place="after", feature="CAP1"))]
    m.components[0].subsystem = "S1"
    assert any("S1 carries `story`" in p and "subsystem" in p for p in problems_of(m))


def test_an_unknown_place_and_a_self_anchor_are_blocking() -> None:
    m = make_story_anchored_model()
    m.capabilities[1].story = StoryAnchor(place="Before", feature="CAP2")
    joined = " ".join(problems_of(m))
    assert "unknown `place` 'Before'" in joined
    assert "CAP2.story anchors the feature to itself" in joined


def test_an_anchor_to_anything_but_a_defined_capability_is_blocking() -> None:
    """One check owns the target: an undefined id AND a defined-but-wrong-kind id (`UC1` exists,
    but the derivation would silently drop the anchor) both block, each reported once."""
    m = make_story_anchored_model()
    for bad in ("CAP9", "UC1"):
        m.capabilities[1].story = StoryAnchor(place="after", feature=bad)
        hits = [p for p in problems_of(m) if bad in p]
        assert len(hits) == 1 and "not a defined capability" in hits[0], (bad, hits)


# --- the trigger arm is never skipped wholesale --------------------------------------------------

def make_all_empty_trigger_model() -> ProjectModel:
    m = make_valid_model()
    m.entry_points = [make_ep(kind="http-route", trigger="GET /a"),
                      make_ep(kind="http-route", trigger="GET /b")]
    for u in m.use_cases:
        u.entry_points = []
    return m


def test_an_all_empty_trigger_arm_warns_once() -> None:
    hits = [w for w in warnings_of(make_all_empty_trigger_model())
            if "No use case names any entry point" in w]
    assert len(hits) == 1
    assert "2 surfaces harvested" in hits[0]
    assert "Entry-point coverage" in hits[0], "the warning names its recordable escape"


def test_one_trigger_link_anywhere_silences_the_degenerate_warning() -> None:
    m = make_all_empty_trigger_model()
    m.entry_points[0].id = "EP1"
    m.use_cases[0].entry_points = ["EP1"]
    assert not any("No use case names any entry point" in w for w in warnings_of(m))


def test_a_recorded_trigger_arm_line_silences_it_durably() -> None:
    m = make_all_empty_trigger_model()
    m.extras = [ExtraSection(heading="Entry-point coverage",
                             body="http-route: complete — swept\n"
                                  "trigger-arm: the harvest recorded route groups; links add nothing")]
    assert not any("No use case names any entry point" in w for w in warnings_of(m))


def test_a_map_with_no_harvest_or_no_use_cases_stays_silent() -> None:
    m = make_all_empty_trigger_model()
    m.entry_points = []
    assert not any("No use case names any entry point" in w for w in warnings_of(m))
    m = make_all_empty_trigger_model()
    m.use_cases = []
    m.happy_path = []
    m.flows = []
    assert not any("No use case names any entry point" in w for w in warnings_of(m))


# ── interfaces (T2b) — the product's outside edge ────────────────────────────────────────────────

def make_interface_model() -> ProjectModel:
    """A map that records its outside edge: one `ours` surface made of one way in, one crossing that
    names a record, and the one dependency decided as not-an-interface."""
    m = make_valid_model()
    m.entry_points = [
        EntryPoint(id="EP1", kind="cli", trigger="run it", activation="external",
                   source="src/v.py:1", component="C1"),
        EntryPoint(id="EP2", kind="poller", trigger="every minute", activation="self",
                   source="src/v.py:20", component="C1"),
        EntryPoint(id="EP3", kind="middleware", trigger="every request", activation="external",
                   source="src/v.py:30", component="C1"),
    ]
    m.deps[0].not_an_interface = "the product writes these rows and reads them back itself"
    m.interfaces = [Interface(
        id="I1", name="Command line", what="How a person runs the product.", side="ours",
        facing="user", kind="command-line", source="src/v.py:1", ways_in=["EP1"])]
    return m


def test_a_recorded_outside_edge_is_clean():
    m = make_interface_model()
    assert not [p for p in problems_of(m) if "I1" in p or "D1" in p]
    assert not [w for w in warnings_of(m) if "belong to no interface" in w]


def test_an_interface_with_no_side_blocks():
    # `side` is the one fact nothing else in the map carries: whose DESIGN the surface is.
    m = make_interface_model()
    m.interfaces[0].side = ""
    assert any("side=" in p and "I1" in p for p in problems_of(m))


def test_a_self_activated_way_in_cannot_belong_to_an_interface():
    # A timer is work the product does to itself. 133 of the 1050 entry points across the four live
    # maps are this, and they are the reason `entry_points` reads as two lists wearing one name.
    m = make_interface_model()
    m.interfaces[0].ways_in = ["EP2"]
    assert any("self-activated" in p for p in problems_of(m))


def test_one_way_in_cannot_belong_to_two_interfaces():
    m = make_interface_model()
    m.interfaces.append(Interface(id="I2", name="Other", side="ours", facing="user",
                                  source="src/v.py:9", ways_in=["EP1"]))
    assert any("claimed by 2 interfaces" in p for p in problems_of(m))


def test_the_walk_steps_at_a_surface_ARE_what_crosses_it():
    """`interfaces[].carries[]` is gone and these replaced it. The removal only became honest once
    the step itself carried a `direction`; an earlier attempt without one was reverted."""
    m = make_interface_model()
    assert interface_walk_steps(m)["I1"] == [], "no step yet, and that is a real answer"
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", direction="in",
                                 phrase="types the command"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="hands it to the runner",
                                 where="src/v.py:3")]
    assert [st.phrase for st in interface_walk_steps(m)["I1"]] == [
        "types the command", "hands it to the runner"]
    assert not hasattr(m.interfaces[0], "carries"), "the authored rows are gone for good"


def test_NO_step_at_a_surface_is_dropped():
    """An "outer step wins" filter was tried — keep only the steps whose far end is outside the
    product — and it silently deleted the sign-in back-channel where a member's verified email
    actually crosses (150 of 317 steps on mcpolis). A reader asking what happens here is owed all
    of it."""
    m = make_interface_model()
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="I1", phrase="trades it for the token",
                                 where="src/v.py:4")]
    assert [st.phrase for st in interface_walk_steps(m)["I1"]] == [
        "opens it", "asks", "trades it for the token"]


def test_the_direction_is_CARRIED_from_the_step_never_re_derived_from_its_polarity():
    """A PULL points outward while its data comes back, and the map draws that as ONE step. Reading
    polarity as direction flipped argus's "Tracked web pages" from `in` to `out` on a page the
    product FETCHES, which is why the answer is authored on the step and only relayed here."""
    m = make_interface_model()
    m.flows[0].steps = [FlowStep(n=1, src="C1", dst="I1", direction="in",
                                 phrase="fetches the page", where="src/v.py:4")]
    st = interface_walk_steps(m)["I1"][0]
    assert st.direction == "in", "the arrow points OUT and the data comes IN — the step is right"
    assert interface_directions(m)["I1"] == ["in"]


def test_a_both_step_votes_for_each_direction():
    """One exchange really does run each way — a code traded for a verified email."""
    m = make_interface_model()
    m.flows[0].steps = [FlowStep(n=1, src="C1", dst="I1", direction="both",
                                 phrase="trades the code for the verified email",
                                 where="src/v.py:4")]
    assert interface_directions(m)["I1"] == ["in", "out"]


def test_a_surface_no_step_reaches_states_no_direction():
    """Not "neither" — NOT STATED. The removed field could claim a direction with no story behind
    it; this one cannot, which is the whole gain."""
    m = make_interface_model()
    assert interface_directions(m)["I1"] == []


def test_a_step_with_no_phrase_says_nothing_and_a_repeat_is_kept_once():
    m = make_interface_model()
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="   ", where="src/v.py:3"),
                        FlowStep(n=3, src="R1", dst="I1", phrase="opens it")]
    assert [st.phrase for st in interface_walk_steps(m)["I1"]] == ["opens it"]


def test_a_step_names_the_walk_and_the_container_that_identifies_it():
    """`(container, n)` is the only unique step identity once a sub-flow is spliced in, so a link
    built from `(uc, n)` alone lands the reader on a different step."""
    m = make_interface_model()
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it")]
    st = interface_walk_steps(m)["I1"][0]
    assert (st.uc, st.container, st.n, st.role) == (m.flows[0].uc, m.flows[0].uc, 1, "R1")


def test_the_steps_are_grouped_by_story_in_happy_path_order():
    """A step means little without the story it sits in: mcpolis's dashboard draws 89 of them from
    20 walks, and read as one list they are noise."""
    m = make_interface_model()
    m.use_cases.append(UseCase(id="UC2", name="Second", trigger="asks", outcome="gets",
                               capability=m.use_cases[0].capability))
    m.happy_path.append(HappyStep(id="HP2", uc="UC2"))
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="a")]
    m.flows.append(Flow(uc="UC2", title="Second",
                        steps=[FlowStep(n=1, src="R1", dst="I1", phrase="b")]))
    got = [(uc, [st.phrase for st in group])
           for uc, group in interface_steps_by_use_case(m)["I1"]]
    assert got == [(m.flows[0].uc, ["a"]), ("UC2", ["b"])], got


def test_an_interface_grounded_by_nothing_blocks_but_a_source_alone_is_enough():
    # The rows with no T4 row and no dep — the files a product writes, the settings an operator sets
    # — are grounded by their own declaring line, and that has to be sufficient.
    m = make_interface_model()
    m.interfaces[0].ways_in = []
    assert not [p for p in problems_of(m) if "grounded by nothing" in p]
    m.interfaces[0].source = ""
    assert any("grounded by nothing" in p for p in problems_of(m))


def test_an_external_system_dep_must_be_decided_one_way_or_the_other():
    # Without a written reason there is no way to tell "deliberately not one" from "nobody looked" —
    # the trap a search service sets: over the product's own records it is not an interface, over
    # the open web it is, and the call site looks identical.
    m = make_interface_model()
    m.deps[0].not_an_interface = ""
    assert any("neither names an interface nor says why" in p for p in problems_of(m))


def test_a_dep_cannot_both_name_an_interface_and_say_it_is_none():
    m = make_interface_model()
    m.deps[0].interfaces = ["I1"]
    assert any("AND says why it is none" in p for p in problems_of(m))


def test_a_dep_naming_an_undefined_interface_blocks():
    m = make_interface_model()
    m.deps[0].not_an_interface = ""
    m.deps[0].interfaces = ["I9"]
    assert any("'I9', which is not a defined interface" in p for p in problems_of(m))


def test_one_dep_may_sit_on_SEVERAL_surfaces():
    # The case that forced the list: one outside system hosts our skill AND writes the transcript we
    # read back. Both surfaces must be able to show the code behind them.
    m = make_interface_model()
    m.interfaces.append(Interface(id="I2", name="Its transcript", side="theirs", facing="operator",
                                  source="",
                                  evidence=[EvidenceItem(file="src/v.py:2", why="reads them")]))
    m.deps[0].not_an_interface = ""
    m.deps[0].interfaces = ["I1", "I2"]
    assert not [p for p in problems_of(m) if "D1" in p]
    m.deps[0].interfaces = ["I1", "I1"]
    assert any("same interface twice" in p for p in problems_of(m))


def test_a_library_dep_never_has_to_be_decided():
    # Libraries and frameworks BECOME the product; 27 of Meerbot's 40 deps are exempt this way.
    m = make_interface_model()
    m.deps[0].not_an_interface = ""
    m.deps[0].kind = "library"
    assert not [p for p in problems_of(m) if "neither names an interface" in p]


def test_the_dep_decision_stays_silent_on_a_map_that_records_no_interfaces():
    # Every existing map is that map. The rule bites only once a map starts recording its edge.
    m = make_interface_model()
    m.interfaces = []
    m.deps[0].not_an_interface = ""
    assert not [p for p in problems_of(m) if "neither names an interface" in p]


def test_unassigned_ways_in_are_ONE_aggregated_line_and_exclude_plumbing():
    # One line per row would print 88/94/249/486 lines against ~20 existing advisories. And the
    # plumbing kinds can never belong to a surface, so counting them makes zero unreachable.
    m = make_interface_model()
    m.entry_points.append(EntryPoint(id="EP4", kind="http-route", trigger="GET /x",
                                     activation="external", source="src/v.py:40", component="C1"))
    hits = [w for w in warnings_of(m) if "belong to no interface" in w]
    assert len(hits) == 1, hits
    assert "1 way(s) in" in hits[0] and "http-route" in hits[0]   # EP3 (middleware) is not counted


def test_a_theirs_surface_with_no_evidence_warns():
    m = make_interface_model()
    m.interfaces[0].side = "theirs"
    m.interfaces[0].source = ""
    assert any("no evidence" in w for w in warnings_of(m))


# ── `kind` — what SHAPE a surface is. Seeded-open, so NOTHING here blocks. ──────────────────────

def test_a_surface_with_no_kind_warns_and_never_blocks():
    m = make_interface_model()
    m.interfaces[0].kind = ""
    assert any("has no `kind`" in w and "I1" in w for w in warnings_of(m))
    assert not [p for p in problems_of(m) if "kind" in p]


def test_the_no_kind_advisory_can_be_recorded_away():
    m = make_interface_model()
    m.interfaces[0].kind = ""
    m.extras = [ExtraSection(heading=INTERFACE_EXCEPTIONS_HEADING,
                             body="I1: the shape of this one is genuinely undecided")]
    assert not [w for w in warnings_of(m) if "has no `kind`" in w]


def test_a_purpose_shaped_kind_is_nudged_toward_the_dependency_bucket():
    """The one rule this field can break: `kind` is SHAPE, `Dep.bucket` is PURPOSE. A payment
    processor and a crash reporter are both `api`."""
    m = make_interface_model()
    m.interfaces[0].kind = "observability"
    hits = [w for w in warnings_of(m) if "I1" in w and "`bucket`" in w]
    assert hits, warnings_of(m)
    assert "FOR, not" in hits[0], hits[0]


def test_a_minted_kind_draws_ONE_aggregated_line_naming_every_kind():
    """Never one line per row: minting is legal, and the only useful thing to say is the list."""
    m = make_interface_model()
    m.interfaces[0].kind = "browser-extension"
    m.interfaces.append(Interface(id="I2", name="CI", what="Our pipeline.", side="ours",
                                  facing="operator", kind="browser-extension",
                                  source="src/v.py:1"))
    m.interfaces.append(Interface(id="I3", name="Phone line", what="A call.", side="ours",
                                  facing="user", kind="telephony", source="src/v.py:1"))
    hits = [w for w in warnings_of(m) if "are not seeds" in w]
    assert len(hits) == 1, hits
    assert "browser-extension" in hits[0] and "telephony" in hits[0], hits[0]
    assert "I1" in hits[0] and "I2" in hits[0] and "I3" in hits[0], hits[0]
    assert "2 interface kind(s)" in hits[0], hits[0]        # two KINDS over three surfaces


def test_a_drifted_spelling_of_a_seed_is_nudged_to_the_canonical_one():
    m = make_interface_model()
    m.interfaces[0].kind = "cli"
    hits = [w for w in warnings_of(m) if "canonical spelling" in w]
    assert hits, warnings_of(m)
    assert "'command-line'" in hits[0], hits[0]
    assert not [w for w in warnings_of(m) if "are not seeds" in w]


def test_every_kind_advisory_is_actually_silenced_by_the_recorded_line():
    """The message TEXT naming an escape is one test; the escape WORKING is this one. Three of these
    messages shipped naming a heading the branch never read."""
    rec = [ExtraSection(heading=INTERFACE_EXCEPTIONS_HEADING, body="I1: deliberate")]
    for value, needle in (("", "has no `kind`"), ("observability", "`bucket`"),
                          ("browser-extension", "are not seeds"), ("cli", "canonical spelling")):
        m = make_interface_model()
        m.interfaces[0].kind = value
        assert [w for w in warnings_of(m) if needle in w], (value, needle)
        m.extras = rec
        assert not [w for w in warnings_of(m) if needle in w], (value, needle)


def test_the_authored_kind_and_the_derived_actor_both_reach_the_rendered_T2b_table():
    """A SECTION reaching the rendered file is already guarded; a COLUMN is not. `kind` and `actors`
    are the only two facts on this row that no other section of the committed map carries, so a
    column that silently never renders takes both of them with it."""
    m = make_interface_model()
    m.use_cases[0].entry_points = ["EP1"]
    # The actor derives from the DOOR the flow draws at the surface, never from the way in alone.
    m.flows = [Flow(uc="UC1", title="View order", steps=[
        FlowStep(n=1, src="R1", dst="I1", phrase="runs the command", where="src/v.py:1")])]
    md = model_to_markdown(m)
    table = md[md.index("## T2b — Interfaces"):]
    table = table[:table.index("\n## ")]
    header = table.splitlines()[2]
    assert "| Kind |" in header and "| Actors |" in header, header
    row = next(l for l in table.splitlines() if "**I1**" in l)
    assert "command-line" in row, row          # the authored SHAPE
    assert "R1" in row, row                    # the DERIVED actor


def test_a_seed_kind_says_nothing_at_all():
    m = make_interface_model()
    m.interfaces[0].kind = "screen"
    assert not [w for w in warnings_of(m) if "kind" in w and "I1" in w]


# ── `actors` — DERIVED, never authored ─────────────────────────────────────────────────────────

def test_an_ours_surface_derives_its_actors_from_the_doors_its_flows_draw_at_it():
    """WHO stands at an `ours` surface is what the flows DOOR there — `R1 → I1` — and nothing else.
    The use cases behind its ways in used to vote too, through the use case's authored
    `entry_points`; that was the one join in the product that did not read the flow, and it is what
    put the Dashboard at happy-path step 1 on mcpolis. A program whose flow merely writes a report to
    the command line (`C1 → I1`, no door) is not the person at the prompt, and the broad join would
    have put them there."""
    m = make_interface_model()
    m.use_cases[0].entry_points = ["EP1"]
    m.roles.append(Role(id="R2", name="Upkeep job", kind="software", wants="tidy", drives="UC2"))
    m.use_cases.append(UseCase(id="UC2", name="Tidy up", actors=["R2"]))
    m.flows = [
        Flow(uc="UC1", title="View order", steps=[
            FlowStep(n=1, src="R1", dst="I1", phrase="runs the command", where="src/v.py:1")]),
        Flow(uc="UC2", title="Tidy up", steps=[
            FlowStep(n=1, src="C1", dst="I1", phrase="writes the report", where="src/v.py:9")])]
    assert interface_actors(m)["I1"] == ["R1"]
    # …and a way in named with NO door at it derives nobody: the map owes the door, and the gate says so.
    m.flows = [m.flows[1]]
    assert interface_actors(m)["I1"] == []


def test_a_theirs_surface_the_product_merely_calls_derives_NO_actor():
    """"Whose story reaches it" is not "who goes there". A member's story reaches an upstream
    server, but the PRODUCT calls it — so an `api` surface draws nobody, and none is correct."""
    m = make_interface_model()
    m.interfaces[0].side = "theirs"
    m.interfaces[0].kind = "api"
    m.interfaces[0].ways_in = []
    m.interfaces[0].source = ""
    m.flows = [Flow(uc="UC1", title="View order", steps=[
        FlowStep(n=1, src="R1", dst="C1", phrase="asks", where="src/v.py:1"),
        FlowStep(n=2, src="C1", dst="I1", phrase="calls out", where="src/v.py:2")])]
    assert interface_actors(m)["I1"] == []


def test_a_handoff_surface_derives_the_roles_whose_stories_reach_it():
    """The two kinds that MEAN a person goes there are the gate — and they are exactly the case an
    authored field existed for: coyomap's GitHub and code editor name no actor and have no ways in."""
    m = make_interface_model()
    m.interfaces[0].side = "theirs"
    m.interfaces[0].kind = "handoff"
    m.interfaces[0].ways_in = []
    m.interfaces[0].source = ""
    m.flows = [Flow(uc="UC1", title="View order", steps=[
        FlowStep(n=1, src="R1", dst="C1", phrase="asks", where="src/v.py:1"),
        FlowStep(n=2, src="C1", dst="I1", phrase="hands over the link", where="src/v.py:2")])]
    assert interface_actors(m)["I1"] == ["R1"]


def test_a_person_goes_there_surface_that_no_walk_reaches_is_a_finding_about_the_walks():
    m = make_interface_model()
    m.interfaces[0].side = "theirs"
    m.interfaces[0].kind = "hosted-screen"
    m.interfaces[0].ways_in = []
    m.interfaces[0].source = ""
    hits = [w for w in warnings_of(m) if "no walk in this map shows anyone going" in w]
    assert hits, warnings_of(m)
    assert "I1" in hits[0], hits[0]


def test_that_finding_is_silent_once_a_walk_opens_the_door():
    m = make_interface_model()
    m.interfaces[0].side = "theirs"
    m.interfaces[0].kind = "hosted-screen"
    m.interfaces[0].ways_in = []
    m.interfaces[0].source = ""
    m.flows = [Flow(uc="UC1", title="View order", steps=[
        FlowStep(n=1, src="R1", dst="I1", phrase="signs in there", where="src/v.py:1"),
        FlowStep(n=2, src="I1", dst="C1", phrase="comes back", where="src/v.py:2")])]
    assert not [w for w in warnings_of(m) if "no walk in this map shows anyone going" in w]


def test_a_door_is_a_legal_step_endpoint_and_does_not_count_toward_the_band():
    """`R1 → I3 → C12` reads "a person, through the dashboard, into the code". The band exists to
    catch a fused goal or wire-grain detail; naming the door is neither, and counting door steps
    would have put 33 of the 150 flows across the four live maps over the band the day doors were
    authored — 33 findings that are not defects."""
    m = make_interface_model()
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="types the command"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="runs it", where="src/v.py:3")]
    assert not problems_of(m), "a door is a legal endpoint on both arms of the step"
    # …and the code-facing arm is held to the same call-site rule as any other element-to-element
    # step: a door does not buy a step out of being anchored.
    m.flows[0].steps[1].where = ""
    assert any("call-site anchor" in p and "step 2" in p for p in problems_of(m))
    # 16 authored steps, one of them a door → 15 counted, which is inside the band.
    m.flows[0].steps = ([FlowStep(n=1, src="R1", dst="I1", phrase="in", no_call_site=True)]
                        + [FlowStep(n=i, src="C1", dst="C1", phrase="works") for i in range(2, 17)])
    assert not [w for w in warnings_of(m) if "band" in w and "UC1" in w]
    # …and 16 counted steps, with no door, is over it.
    m.flows[0].steps = [FlowStep(n=i, src="C1", dst="C1", phrase="works") for i in range(1, 17)]
    assert any("over the \u226415 band" in w and "16 steps" in w for w in warnings_of(m))


def test_a_map_that_authors_surfaces_and_never_retrofits_its_flows_says_so():
    """T2b is authored AFTER the trace, so every flow was written before any surface existed and the
    doors have to be added back. A build that authors the surfaces and stops leaves a map that can
    SAY what its outside edge is while no story goes through a door — measured on the first real
    build to author the section: 12 surfaces, 517 steps, ZERO doors, 5 migrations owed."""
    m = make_interface_model()
    m.use_cases[0].entry_points = ["EP1"]                    # …and EP1 belongs to I1
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="C1", phrase="asks")]   # straight in, no door
    assert any("never goes through its door" in w or "no step of theirs touches" in w
               for w in warnings_of(m))
    # …and opening at the door clears it.
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3")]
    assert not [w for w in warnings_of(m) if "touches that surface" in w]


def test_a_step_still_pointing_at_a_dependency_that_stands_on_a_surface_is_flagged():
    """The other half of the retrofit. A step at the dep names the PIPE; the surface is the far side."""
    m = make_interface_model()
    m.deps[0].not_an_interface = ""
    m.deps[0].interfaces = ["I1"]
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="C1", dst="D1", phrase="calls out", where="src/v.py:4")]
    assert any("stands on a surface" in w for w in warnings_of(m))


def test_a_flow_that_hands_its_result_to_an_actor_without_a_door_is_flagged():
    """The OUT half. The arrival was already gated; the hand-off was not, so a map could open every
    story at a door and still show 57 stories walking out past it (coyomap 30, mcpolis 27, measured
    the day this shipped)."""
    m = make_interface_model()
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="R1", phrase="shows the order")]
    assert any("cross between an actor and the product without going through a door" in w
               for w in warnings_of(m))


def test_the_out_door_is_drawn_even_when_it_is_the_surface_the_story_arrived_by():
    """"Skip it when it is the same surface" was the first draft and was rejected: the use-case
    picture would show data flowing only IN while that same surface's `carries` rows record both
    directions, so one screen would contradict itself. Closing at I1 after arriving at I1 is CLEAN."""
    m = make_interface_model()
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="I1", phrase="answers", where="src/v.py:4"),
                        FlowStep(n=4, src="I1", dst="R1", phrase="shows the order")]
    assert not [w for w in warnings_of(m) if "without going through a door" in w]
    # The positive half, and the one that pins the rejected draft: the flow still ARRIVES at I1, and
    # dropping only its out-door must fire. A "skip the out-door when it is the same surface" rule
    # would make this map clean, and nothing else in the suite would notice.
    m.flows[0].steps = m.flows[0].steps[:2] + [
        FlowStep(n=3, src="C1", dst="R1", phrase="shows the order")]
    assert any("without going through a door" in w for w in warnings_of(m))


def test_a_MID_STORY_crossing_needs_its_door_like_any_other():
    """EVERY crossing, not only the two ends. An "endpoints only" rule shipped first and was withdrawn
    once it could be measured on a map that HAD doors: it drew one person on both sides of one wall,
    routing the same actor through the same surface at the ends and past it in the middle. On mcpolis
    the strict rule costs 36 steps (~6%), adds NO new box, and draws FEWER arrows (525 → 522)."""
    m = make_interface_model()
    doored = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
              FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
              FlowStep(n=3, src="C1", dst="I1", phrase="previews it", where="src/v.py:5"),
              FlowStep(n=4, src="I1", dst="R1", phrase="shows the preview"),
              FlowStep(n=5, src="R1", dst="I1", phrase="confirms"),
              FlowStep(n=6, src="I1", dst="C1", phrase="passes the confirmation", where="src/v.py:6"),
              FlowStep(n=7, src="C1", dst="I1", phrase="answers", where="src/v.py:4"),
              FlowStep(n=8, src="I1", dst="R1", phrase="shows the order")]
    m.flows[0].steps = doored
    assert not [w for w in warnings_of(m) if "without going through a door" in w]
    # Both ends doored and the MIDDLE left direct: this is the shape the withdrawn rule allowed, and
    # it must now fire. One person, one component, two contradictory routes on one picture.
    m.flows[0].steps = [doored[0], doored[1],
                        FlowStep(n=3, src="C1", dst="R1", phrase="previews it"),
                        FlowStep(n=4, src="R1", dst="C1", phrase="confirms"),
                        doored[6], FlowStep(n=5, src="I1", dst="R1", phrase="shows the order")]
    fired = [w for w in warnings_of(m) if "without going through a door" in w]
    assert fired, warnings_of(m)
    assert "step 3" in fired[0] and "step 4" in fired[0], fired[0]
    assert "EVERY crossing takes a door, not only the story's two ends" in fired[0], fired[0]


def test_the_closing_gate_is_advisory_and_is_honoured_by_a_recorded_use_case():
    """Both halves. An advisory must not merely NAME its escape, it must HONOUR it: `recorded` reads
    `I`/`EP` tokens, so the three retrofit gates all named a use-case id their branch then dropped.
    With every use case recorded under the heading the message names, all three still fired."""
    m = make_interface_model()
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="R1", phrase="shows the order")]
    assert not [p for p in problems_of(m) if "door" in p], "advisory, never blocking"
    fired = [w for w in warnings_of(m) if "without going through a door" in w]
    assert INTERFACE_EXCEPTIONS_HEADING in fired[0], fired[0]
    m.extras.append(ExtraSection(heading=INTERFACE_EXCEPTIONS_HEADING,
                                 body="UC1: the command prints and exits, nobody is handed anything"))
    assert not [w for w in warnings_of(m) if "without going through a door" in w]


def test_the_two_older_retrofit_gates_honour_a_recorded_use_case_too():
    """The sibling half of the bug above, found by the same sweep and fixed in the same change."""
    m = make_interface_model()
    m.use_cases[0].entry_points = ["EP1"]
    m.deps[0].not_an_interface = ""
    m.deps[0].interfaces = ["I1"]
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="C1", phrase="asks"),
                        FlowStep(n=2, src="C1", dst="D1", phrase="calls out", where="src/v.py:4")]
    assert any("touches that surface" in w for w in warnings_of(m))
    assert any("stands on a surface" in w for w in warnings_of(m))
    m.extras.append(ExtraSection(heading=INTERFACE_EXCEPTIONS_HEADING, body="UC1: deliberate"))
    assert not [w for w in warnings_of(m) if "touches that surface" in w]
    assert not [w for w in warnings_of(m) if "stands on a surface" in w]


def test_our_surface_that_sends_and_derives_nobody_says_the_far_side_is_unnamed():
    """Check (a). An `ours` surface that sends is the product handing something over, so somebody
    receives it. Deriving nobody means neither a closing door nor a driven way in was ever written.
    Fires on 2 of the 23 surfaces across the two live maps: both products' `I6`."""
    m = make_interface_model()
    m.interfaces[0].ways_in = []
    # The surface SENDS because a step drawn at it says `out`. That used to be a `carries[]` row.
    m.flows[0].steps = [FlowStep(n=1, src="C1", dst="I1", direction="out",
                                 phrase="writes the map files", where="src/v.py:4")]
    fired = [w for w in warnings_of(m) if "derives nobody on the far side" in w]
    assert fired, warnings_of(m)
    assert "I1" in fired[0] and INTERFACE_EXCEPTIONS_HEADING in fired[0], fired[0]
    assert not [p for p in problems_of(m) if "far side" in p], "advisory, never blocking"


def test_check_a_is_silent_once_a_flow_closes_at_that_door():
    """The fix the message asks for is a STORY, not a field — so writing the story must clear it."""
    m = make_interface_model()
    m.interfaces[0].ways_in = []
    m.flows[0].steps = [FlowStep(n=1, src="C1", dst="I1", direction="out", phrase="writes them",
                                 where="src/v.py:4"),
                        FlowStep(n=2, src="I1", dst="R1", direction="out",
                                 phrase="hands the reader the files")]
    assert not [w for w in warnings_of(m) if "derives nobody on the far side" in w]


def test_check_a_is_honoured_by_a_recorded_interface_id():
    m = make_interface_model()
    m.interfaces[0].ways_in = []
    m.flows[0].steps = [FlowStep(n=1, src="C1", dst="I1", direction="out",
                                 phrase="writes the map files", where="src/v.py:4")]
    assert any("derives nobody on the far side" in w for w in warnings_of(m))
    m.extras.append(ExtraSection(heading=INTERFACE_EXCEPTIONS_HEADING,
                                 body="I1: the far side is a disk, not anybody this map names"))
    assert not [w for w in warnings_of(m) if "derives nobody on the far side" in w]


def test_a_written_door_puts_its_role_at_the_surface_with_NO_kind_gate():
    """The DOOR arm of `interface_actors`, and the reason it is ungated. The `theirs` arm is gated on
    `kind` to stop a bad INFERENCE — an ungated "whose story reaches it" join once put three human
    roles on the far side of an upstream MCP server. A written step is not an inference: `R1 → I2` is
    the map's own statement, and gating it would discard what the map says for what the code guesses.
    `api` is deliberately NOT one of the kinds a person goes to, and the role still derives."""
    m = make_interface_model()
    m.interfaces.append(Interface(
        id="I2", name="Their console", what="Someone else's screen.", side="theirs",
        facing="user", kind="api", source="src/v.py:9",
        evidence=[EvidenceItem(file="src/v.py:9", why="the call site")]))
    assert not interface_actors(m).get("I2"), "no door yet, and none is the right answer"
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="I2", phrase="pushes", where="src/v.py:9"),
                        FlowStep(n=4, src="I2", dst="R1", phrase="the person reads it there")]
    assert interface_actors(m)["I2"] == ["R1"], interface_actors(m)


def test_the_door_arm_reads_a_role_on_EITHER_side_of_the_step():
    m = make_interface_model()
    m.roles.append(Role(id="R2", name="Bo", kind="human", wants="the file", drives="UC1"))
    m.flows[0].steps = [FlowStep(n=1, src="R2", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="I1", phrase="answers", where="src/v.py:4"),
                        FlowStep(n=4, src="I1", dst="R1", phrase="shows it")]
    assert interface_actors(m)["I1"] == ["R1", "R2"], interface_actors(m)


def test_handing_back_to_the_products_OWN_timer_needs_no_door():
    """An actor for the doors rule is one OUTSIDE the product. A `service` + `internal` role is the
    product's own scheduled work, so a story that starts or ends at one crosses nothing. Read the two
    FIELDS, never the name: the first real trial stalled on a role called "Upkeep job", which the
    method text names in one breath as an actor and in the next as a timer."""
    m = make_interface_model()
    m.roles.append(Role(id="R9", name="Upkeep job", kind="service", audience="internal",
                        wants="the sweep to run", drives="UC1"))
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="R9", phrase="tells the sweep it is done")]
    assert not [w for w in warnings_of(m) if "without going through a door" in w]
    # …and a service role the CUSTOMER runs is outside the product, so it still owes its door.
    m.roles.append(Role(id="R8", name="Their bot", kind="service", audience="user",
                        wants="the answer", drives="UC1"))
    m.flows[0].steps[-1] = FlowStep(n=3, src="C1", dst="R8", phrase="answers the bot")
    assert any("without going through a door" in w for w in warnings_of(m))


def test_a_SUB_FLOW_step_pointing_at_a_pipe_is_flagged_under_its_own_id():
    """Shared machinery is where a pipe hides best: a sub-flow is written once and ridden by several
    stories, so ONE unmigrated step there draws the dep in every flow that runs it. This loop read
    `m.flows` only, and a worker doing the retrofit by hand found what no check could see — mcpolis's
    "open a session to a mounted server" carries 3 such steps while `validate` reported zero owed."""
    m = make_interface_model()
    m.deps[0].not_an_interface = ""
    m.deps[0].interfaces = ["I1"]
    m.subflows = [SubFlow(id="SF1", name="Open a session", steps=[
        FlowStep(n=1, src="C1", dst="D1", phrase="calls out", where="src/v.py:4"),
        FlowStep(n=2, src="C1", dst="E1", phrase="stores it", where="src/v.py:5")])]
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3")]
    fired = [w for w in warnings_of(m) if "stands on a surface" in w]
    assert fired, warnings_of(m)
    assert "SF1 step 1" in fired[0], fired[0]
    # …and the escape honours the SUB-FLOW's own id, which is where the edit goes.
    m.extras.append(ExtraSection(heading=INTERFACE_EXCEPTIONS_HEADING,
                                 body="SF1: the step really means the dependency itself"))
    assert not [w for w in warnings_of(m) if "stands on a surface" in w]


def test_a_SUB_FLOW_crossing_is_reported_under_its_OWN_step_number():
    """A sub-flow's step numbers belong to the SUB-FLOW. Reading the crossing sweep off
    `expanded_flow_steps` reported one against a step number the named flow does not have, and once
    per flow that rides the sub-flow. Same rule `_check_actor_doors` states, same reason."""
    m = make_interface_model()
    m.subflows = [SubFlow(id="SF1", name="Ask the person", steps=[
        FlowStep(n=1, src="C1", dst="R1", phrase="asks them"),
        FlowStep(n=2, src="C1", dst="E1", phrase="stores it", where="src/v.py:5")])]
    # TWO flows RIDE the sub-flow. Without riders both assertions below pass for the wrong reason —
    # nothing to double-count and nothing to misattribute — which is how an adversarial review landed
    # a mutation reading `expanded_flow_steps` straight through this test.
    m.use_cases.append(UseCase(id="UC2", name="Ask again", actors=["R1"]))
    m.happy_path.append(HappyStep(id="HP2", uc="UC2"))
    riders = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
              FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
              FlowStep(n=3, src="C1", dst="C1", phrase="runs the shared ask", subflow="SF1"),
              FlowStep(n=4, src="C1", dst="I1", phrase="answers", where="src/v.py:4"),
              FlowStep(n=5, src="I1", dst="R1", phrase="shows it")]
    m.flows[0].steps = list(riders)
    m.flows.append(Flow(uc="UC2", title="Ask again", steps=list(riders)))
    assert sum(1 for f in m.flows for st in f.steps if st.subflow == "SF1") == 2, "two real riders"
    fired = [w for w in warnings_of(m) if "without going through a door" in w]
    assert fired, warnings_of(m)
    assert "SF1 step 1" in fired[0], fired[0]
    assert "UC1 step 1" not in fired[0], "reported against a step number UC1 does not have"
    assert "UC2 step 1" not in fired[0], "reported against a step number UC2 does not have"
    assert fired[0].startswith("1 step(s)"), fired[0]   # ONCE, not once per riding flow
    # …and the reference step itself is not a crossing: its `src`/`dst` are the run's entry and exit
    # endpoints, so the door can live inside the sub-flow while the reference reads `Cn → Cn`.
    assert "step 3" not in fired[0], fired[0]
    m.extras.append(ExtraSection(heading=INTERFACE_EXCEPTIONS_HEADING, body="SF1: deliberate"))
    assert not [w for w in warnings_of(m) if "without going through a door" in w]


def test_a_person_at_a_machine_shaped_surface_is_nudged():
    """The one question the door checks CANNOT ask. They verify a door EXISTS and can never tell a
    RIGHT door from a WRONG one — measured by repointing every door on a 42-story map onto the crash
    reporter, a nonsense map, which raised 2 advisories and ZERO blocking problems. `api` and
    `content` are one program calling another, so a walk that puts a person at one is worth a look."""
    m = make_interface_model()
    m.interfaces.append(Interface(
        id="I2", name="Their log store", what="Where our log lines go.", side="theirs",
        facing="operator", kind="api", source="src/v.py:9",
        evidence=[EvidenceItem(file="src/v.py:9", why="the call site")]))
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="I2", phrase="ships a line", where="src/v.py:9"),
                        FlowStep(n=4, src="I2", dst="R1", phrase="the person reads it there")]
    fired = [w for w in warnings_of(m) if "nobody stands there" in w]
    assert fired, warnings_of(m)
    assert "I2" in fired[0] and "'api'" in fired[0], fired[0]
    # It must name BOTH causes: either the door is wrong, or the shape is.
    assert "WRONG DOOR" in fired[0] and "SHAPE is" in fired[0], fired[0]
    assert not [p for p in problems_of(m) if "nobody stands there" in p], "a nudge, never a gate"
    # EVERY machine-shaped kind, named LITERALLY. A first attempt looped over the grammar constant
    # itself, so shrinking that constant shrank the test with it and the mutation stayed green — the
    # same vacuous shape this suite has now been bitten by twice.
    assert set(grammar.INTERFACE_KINDS_NOBODY_STANDS_AT) == {"api", "content"}, \
        "both shapes mean one program calling another; changing this set needs a case below"
    for kind in ("api", "content"):
        m.interfaces[1].kind = kind
        hit = [w for w in warnings_of(m) if "nobody stands there" in w]
        assert hit and f"'{kind}'" in hit[0], (kind, warnings_of(m))


def test_the_nudge_is_silent_when_the_shape_says_a_person_belongs_there():
    """`hosted-screen` and `handoff` MEAN a person goes there, and `agent-tools` can hold a headless
    agent, which is a role in its own right. None of those may fire."""
    m = make_interface_model()
    for kind in ("hosted-screen", "handoff", "agent-tools", "screen", "command-line"):
        m.interfaces[0].kind = kind
        m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                            FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                            FlowStep(n=3, src="C1", dst="I1", phrase="answers", where="src/v.py:4"),
                            FlowStep(n=4, src="I1", dst="R1", phrase="shows it")]
        assert not [w for w in warnings_of(m) if "nobody stands there" in w], kind


def test_the_nudge_says_nothing_about_a_MINTED_kind():
    """Seeded-open: an unknown word cannot say whether anybody stands there, so guessing would put a
    false finding on every legitimate mint. The minted-kind advisory already covers the mint itself."""
    m = make_interface_model()
    m.interfaces[0].kind = "kiosk"
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="I1", phrase="answers", where="src/v.py:4"),
                        FlowStep(n=4, src="I1", dst="R1", phrase="shows it")]
    assert not [w for w in warnings_of(m) if "nobody stands there" in w], warnings_of(m)


def test_the_nudge_is_honoured_by_a_recorded_interface_id():
    m = make_interface_model()
    m.interfaces[0].kind = "api"
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="I1", phrase="answers", where="src/v.py:4"),
                        FlowStep(n=4, src="I1", dst="R1", phrase="shows it")]
    assert any("nobody stands there" in w for w in warnings_of(m))
    m.extras.append(ExtraSection(heading=INTERFACE_EXCEPTIONS_HEADING,
                                 body="I1: the mail really does land in a person's inbox"))
    assert not [w for w in warnings_of(m) if "nobody stands there" in w]


def test_ONE_definition_of_an_actor_is_shared_by_the_derivation_and_the_checks():
    """The blocking finding of an adversarial review. Two copies of "who is an actor" existed and
    DISAGREED: the door checks exempted the product's own timer, `interface_actors` did not. So a
    door closing onto that timer registered as a far side and SILENCED the advisory that exists to
    say a surface hands something over to nobody. Every gate stayed green."""
    m = make_interface_model()
    m.interfaces[0].ways_in = []
    m.flows[0].steps = [FlowStep(n=1, src="C1", dst="I1", direction="out",
                                 phrase="writes the files", where="src/v.py:4")]
    fires = lambda: [w for w in warnings_of(m) if "derives nobody on the far side" in w]
    assert fires(), "with no door at all it must fire"
    m.roles.append(Role(id="R9", name="Upkeep job", kind="service", audience="internal",
                        wants="the sweep to run", drives="UC1"))
    m.flows[0].steps = [FlowStep(n=1, src="C1", dst="I1", direction="out", phrase="writes",
                                 where="src/v.py:4"),
                        FlowStep(n=2, src="I1", dst="R9", direction="out",
                                 phrase="hands it to its own timer")]
    assert not interface_actors(m)["I1"], "the product's own timer is not a far side"
    assert fires(), "and the advisory must STILL fire — a timer is not somebody"


def test_an_INTERNAL_HUMAN_role_still_owes_its_doors():
    """The mutation that survived the whole suite: dropping the `service` half of the exemption. An
    internal HUMAN role is an operator or a staff admin, who very much comes in through a door.
    Measured on this repo's own map when the review landed it: 46 of 140 findings vanished."""
    m = make_interface_model()
    m.roles.append(Role(id="R7", name="Service operator", kind="human", audience="internal",
                        wants="to run it", drives="UC1"))
    m.flows[0].steps = [FlowStep(n=1, src="R7", dst="C1", phrase="opens the console")]
    fired = [w for w in warnings_of(m) if "without going through a door" in w]
    assert fired, "an internal HUMAN still crosses"
    assert "R7" in fired[0], fired[0]
    # …while the product's own timer, on the same shape, does not.
    m.roles[-1].kind = "service"
    assert not [w for w in warnings_of(m) if "without going through a door" in w]


def test_the_nudge_says_nothing_about_a_SERVICE_role_at_a_machine_shaped_surface():
    """The second blocking finding. The message says "a PERSON", the condition read ANY role, so a
    partner's bot calling our `api` — the single most normal thing an `api` is for — raised a false
    defect. Its only escape is the shared `recorded` set, which silences six other checks on that row."""
    m = make_interface_model()
    m.interfaces[0].kind = "api"
    m.roles.append(Role(id="R8", name="Partner bot", kind="service", audience="user",
                        wants="the answer", drives="UC1"))
    m.flows[0].steps = [FlowStep(n=1, src="R8", dst="I1", phrase="calls in"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="I1", phrase="answers", where="src/v.py:4"),
                        FlowStep(n=4, src="I1", dst="R8", phrase="answers the bot")]
    assert interface_actors(m)["I1"] == ["R8"], "the bot IS on the far side"
    assert not [w for w in warnings_of(m) if "nobody stands there" in w], warnings_of(m)
    # …and a HUMAN in the same position is exactly what the nudge is for.
    m.roles[-1].kind = "human"
    assert any("nobody stands there" in w for w in warnings_of(m))


def test_a_SCOPED_record_excuses_ONE_retrofit_gate_and_a_bare_one_excuses_all_three():
    """`_recorded_ids` returns the bare and the scoped form so each caller asks for the token IT
    honours. All three gates asked only for the bare one, so the precise record was INERT and the
    blunt one was the only thing that worked — the exact shape that docstring says a record must
    never have."""
    def probe(record):
        m = make_interface_model()
        m.use_cases[0].entry_points = ["EP1"]
        m.deps[0].not_an_interface = ""
        m.deps[0].interfaces = ["I1"]
        m.flows[0].steps = [FlowStep(n=1, src="R1", dst="C1", phrase="asks"),
                            FlowStep(n=2, src="C1", dst="D1", phrase="calls", where="src/v.py:4")]
        if record:
            m.extras.append(ExtraSection(heading=INTERFACE_EXCEPTIONS_HEADING, body=record))
        w = warnings_of(m)
        return (any("touches that surface" in x for x in w),
                any("without going through a door" in x for x in w),
                any("stands on a surface" in x for x in w))
    assert probe(None) == (True, True, True)
    assert probe("UC1/opening: why") == (False, True, True)
    assert probe("UC1/doors: why") == (True, False, True)
    assert probe("UC1/migration: why") == (True, True, False)
    assert probe("UC1: why") == (False, False, False), "a bare token excuses the whole family"


def test_the_no_interfaces_advisory_can_actually_be_recorded_away():
    """Its escape named the bare word `interfaces`, which has no id prefix, so the line reader
    dropped it and the escape was UNREACHABLE. The author wrote the record, was told nothing, and the
    advisory fired forever. Found by an adversarial review, in the same function as the bug this
    change had already celebrated fixing."""
    m = make_valid_model()
    m.deps = [Dep(id="D1", name="Their service", kind="service", type="api")]
    fires = lambda: [w for w in warnings_of(m) if "outside edge (T2b) was" in w]
    assert fires(), "a map with an external system and no surfaces must say so"
    m.extras.append(ExtraSection(heading=INTERFACE_EXCEPTIONS_HEADING,
                                 body="interfaces: this product genuinely has none"))
    assert not fires(), "…and following the instruction must silence it"


def test_a_SUB_FLOW_REFERENCE_step_is_never_itself_a_crossing():
    """A reference step's `src`/`dst` are the RUN'S ENTRY AND EXIT endpoints, so a shared sign-in
    sub-flow that opens `R1 → I1` is referenced by a step authored `R1 → C1`. The door exists one
    level down. Reporting it demanded an edit the author cannot make: those endpoints are
    load-bearing for every unexpanded consumer, so the only way out was a record that also silenced
    two older gates. Found by an adversarial review; not live on either map."""
    m = make_interface_model()
    m.subflows = [SubFlow(id="SF1", name="Sign in", steps=[
        FlowStep(n=1, src="R1", dst="I1", phrase="opens the sign-in"),
        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:7")])]
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="C1", phrase="signs in", subflow="SF1"),
                        FlowStep(n=2, src="C1", dst="I1", phrase="answers", where="src/v.py:4"),
                        FlowStep(n=3, src="I1", dst="R1", phrase="shows it")]
    fired = [w for w in warnings_of(m) if "without going through a door" in w]
    assert not fired, fired          # the reference step spans a role and is NOT a crossing
    # …and an ordinary step of that same shape, with no `subflow`, still is.
    m.flows[0].steps[0] = FlowStep(n=1, src="R1", dst="C1", phrase="signs in")
    assert any("without going through a door" in w for w in warnings_of(m))


def test_a_door_anchored_where_its_surface_has_no_way_in_is_flagged():
    """The rule "use the way in's own `source`" is CHECKABLE only because it names a field. Its
    predecessor, "use the route line", was unenforceable — nothing in the model says what a route is.
    Restating a rule in terms of something the model already records is what turns prose into a check.
    Measured when this landed: 15 flagged on the one doored map, and they were exactly the 15 found
    by hand, with no false positive."""
    m = make_interface_model()
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/button.py:9")]
    fired = [w for w in warnings_of(m) if "has no way in" in w]
    assert fired, warnings_of(m)
    assert "UC1 step 2" in fired[0] and "src/button.py:9" in fired[0], fired[0]
    # It must name BOTH causes: the clicked widget, or a way in the surface is missing.
    assert "WIDGET" in fired[0] and "MISSING a way in" in fired[0], fired[0]
    assert not [p for p in problems_of(m) if "has no way in" in p], "advisory, never a gate"
    # …and the way in's own file clears it. FILE level, not line: a way in points at the declaration
    # and a step may legitimately sit a line or two inside the handler.
    m.flows[0].steps[1] = FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:40")
    assert not [w for w in warnings_of(m) if "has no way in" in w]


def test_the_anchor_check_says_nothing_about_a_surface_with_no_ways_in():
    """A `theirs` surface has none by definition, so there is no line to compare against and a
    finding would be pure noise on every map that records one."""
    m = make_interface_model()
    m.interfaces.append(Interface(
        id="I2", name="Their console", what="Someone else's screen.", side="theirs",
        facing="user", kind="hosted-screen", source="src/v.py:9",
        evidence=[EvidenceItem(file="src/v.py:9", why="the call site")]))
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/v.py:3"),
                        FlowStep(n=3, src="C1", dst="I2", phrase="pushes", where="src/v.py:9"),
                        FlowStep(n=4, src="I2", dst="C1", phrase="comes back", where="src/zz.py:1")]
    assert not [w for w in warnings_of(m) if "has no way in" in w], warnings_of(m)


def test_the_anchor_check_is_honoured_by_a_scoped_record():
    m = make_interface_model()
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I1", phrase="opens it"),
                        FlowStep(n=2, src="I1", dst="C1", phrase="asks", where="src/button.py:9")]
    assert any("has no way in" in w for w in warnings_of(m))
    m.extras.append(ExtraSection(heading=INTERFACE_EXCEPTIONS_HEADING,
                                 body="UC1/doors: the Makefile target really is where this starts"))
    assert not [w for w in warnings_of(m) if "has no way in" in w]


def test_a_name_starting_with_the_is_nudged():
    """A name is a LABEL, read on a card and in a breadcrumb, never in a sentence. Measured when this
    landed: across the two live maps, components 0 of 138, entities 0 of 171, deps 0 of 49, use cases
    0 of 80 and roles 0 of 9 began with "The", while INTERFACES were 7 of 12 on one map and 3 of 11 on
    the other. One element type had drifted off a convention 360-odd names already kept."""
    m = make_interface_model()
    m.interfaces[0].name = "The command line"
    fired = [w for w in warnings_of(m) if "start with 'The'" in w]
    assert fired, warnings_of(m)
    assert "I1" in fired[0] and "The command line" in fired[0], fired[0]
    assert not [p for p in problems_of(m) if "start with 'The'" in p], "advisory, never a gate"
    m.interfaces[0].name = "Command line"
    assert not [w for w in warnings_of(m) if "start with 'The'" in w]


def test_the_naming_nudge_reads_EVERY_element_type_not_only_surfaces():
    """Surfaces are where it was found, but the convention belongs to every name. coyomap's own map
    had 5 components and 3 subsystems doing the same thing."""
    for setter in (lambda m: setattr(m.components[0], "name", "The viewer"),
                   lambda m: setattr(m.deps[0], "name", "The database"),
                   lambda m: setattr(m.roles[0], "name", "The reader"),
                   lambda m: setattr(m.use_cases[0], "name", "The order view"),
                   lambda m: setattr(m.entities[0], "name", "The order")):
        m = make_interface_model()
        setter(m)
        assert [w for w in warnings_of(m) if "start with 'The'" in w], m


def test_the_naming_nudge_is_ONE_line_and_is_honoured_by_a_record():
    """A product really can be called "The Gateway", so the escape must work — and a map with many
    names must produce one line, not one per name."""
    m = make_interface_model()
    m.interfaces[0].name = "The command line"
    m.components[0].name = "The viewer"
    fired = [w for w in warnings_of(m) if "start with 'The'" in w]
    assert len(fired) == 1 and fired[0].startswith("2 element name(s)"), fired
    assert NAMING_EXCEPTIONS_HEADING in fired[0], fired[0]
    m.extras.append(ExtraSection(heading=NAMING_EXCEPTIONS_HEADING,
                                 body="I1: the product is really called The Command Line\n"
                                      "C1: and so is this one"))
    assert not [w for w in warnings_of(m) if "start with 'The'" in w]


CODE_NAME_LINE = "spelled like code"


def test_a_name_spelled_like_the_class_is_nudged():
    """The asymmetry is the evidence: on the 2026-09-13 live maps 52 of 59, 50 of 53 and 96 of 100
    RECORD names were the class's own spelling while 0 of 126, 0 of 43 and 0 of 114 COMPONENT names
    were. The sentence beside each record was good plain language, so the writer knew what the thing
    was and named it after the class anyway — and nothing in the method or the tools said not to."""
    m = make_interface_model()
    m.entities[0].name = "NotificationSecurityData"
    fired = [w for w in warnings_of(m) if CODE_NAME_LINE in w]
    assert fired, warnings_of(m)
    assert "NotificationSecurityData" in fired[0] and m.entities[0].id in fired[0], fired[0]
    assert not [p for p in problems_of(m) if CODE_NAME_LINE in p], "advisory, never a gate"
    m.entities[0].name = "Who may see a reminder"
    assert not [w for w in warnings_of(m) if CODE_NAME_LINE in w]


def test_the_code_name_nudge_reads_every_reader_facing_element_and_exempts_dependencies():
    """A dependency's name is the vendor's own spelling and SHOULD be — the rule would fire 14 times
    on one live map's 35 dependencies, every one of them correct. An advisory wrong 14 times in one
    section is one a build learns to route around."""
    for setter in (lambda m: setattr(m.components[0], "name", "OrderRepository"),
                   lambda m: setattr(m.use_cases[0], "name", "PlaceOrder"),
                   lambda m: setattr(m.roles[0], "name", "AdminUser"),
                   lambda m: setattr(m.interfaces[0], "name", "AdminConsole")):
        m = make_interface_model()
        setter(m)
        assert [w for w in warnings_of(m) if CODE_NAME_LINE in w], m
    m = make_interface_model()
    m.deps[0].name = "BeautifulSoup"
    assert not [w for w in warnings_of(m) if CODE_NAME_LINE in w], "a vendor spells its own name"


def test_a_vendor_word_the_map_already_lists_clears_the_name_that_uses_it():
    """"MongoDB stores" is a component naming a product, and the map's own dependency list is what
    knows which words those are."""
    m = make_interface_model()
    m.deps[0].name = "MongoDB"
    m.components[0].name = "MongoDB stores"
    assert not [w for w in warnings_of(m) if CODE_NAME_LINE in w], warnings_of(m)
    m.components[0].name = "MongoClient wrapper"
    assert [w for w in warnings_of(m) if CODE_NAME_LINE in w]


def test_the_code_name_nudge_is_ONE_line_and_its_escape_is_reachable_and_scoped():
    """One line for a map with many such names, and a SCOPED key: this heading already adjudicates
    the leading article on the same ids, and one record must never answer two checks it was not
    written for."""
    m = make_interface_model()
    m.entities[0].name = "GroupContact"
    m.components[0].name = "OrderRepository"
    fired = [w for w in warnings_of(m) if CODE_NAME_LINE in w]
    assert len(fired) == 1 and fired[0].startswith("2 element name(s)"), fired
    assert NAMING_EXCEPTIONS_HEADING in fired[0], fired[0]

    eid, cid = m.entities[0].id, m.components[0].id
    m.extras.append(ExtraSection(
        heading=NAMING_EXCEPTIONS_HEADING,
        body=f"{eid}/code-name, {cid}/code-name: the business really calls them this"))
    assert not [w for w in warnings_of(m) if CODE_NAME_LINE in w], warnings_of(m)
    assert not validate_model_mod.recorded_line_warnings(m), "the scoped key must PARSE here"

    # …and the leading-article question on the same element is NOT answered by that record.
    m.entities[0].name = "The GroupContact"
    assert [w for w in warnings_of(m) if "start with 'The'" in w]


def test_a_BARE_naming_record_answers_the_article_question_and_only_that_one():
    """One record silences exactly one (check, id) pair, never a family — the method says it in those
    words, and the doors family already had this same bug fixed out of it once
    (`method/retro-checks/2026-08-30-doors-both-ways.md`).

    The bare `In` has ONE documented meaning under this heading — the article is part of a real
    proper name — and every recorded line on every live map was written to mean that. So it keeps
    that meaning and answers nothing else; the code-shape question has its own scoped key."""
    m = make_interface_model()
    m.entities[0].name = "The GroupContact"
    eid = m.entities[0].id
    m.extras.append(ExtraSection(heading=NAMING_EXCEPTIONS_HEADING,
                                 body=f"{eid}: the business really is called The GroupContact"))
    warnings = warnings_of(m)
    assert not [w for w in warnings if "start with 'The'" in w], "the bare id answers the article"
    hit = [w for w in warnings if CODE_NAME_LINE in w]
    assert hit, "…and must NOT answer the code-shape question as well"
    assert eid in hit[0], hit[0]


def test_a_scope_no_check_reads_parses_looks_answered_and_is_reported_by_name():
    """`C1/article` is the word an operator reaches for when answering the article question the
    scoped way. It parses into a valid key, silences nothing, and `malformed_records` cannot see it
    — that check only catches an UNREADABLE key. So the heading declares which scopes work and this
    names the ones that do not."""
    m = make_interface_model()
    m.entities[0].name = "The GroupContact"
    eid = m.entities[0].id
    m.extras.append(ExtraSection(heading=NAMING_EXCEPTIONS_HEADING,
                                 body=f"{eid}/article: it really is called that"))
    warnings = warnings_of(m)
    hit = [w for w in warnings if "name a scope no check reads" in w]
    assert len(hit) == 1, warnings
    assert f"{eid}/article" in hit[0] and "`/code-name`" in hit[0], hit[0]
    # It really does silence nothing — both naming questions still fire.
    assert [w for w in warnings if "start with 'The'" in w]
    assert [w for w in warnings if CODE_NAME_LINE in w]
    # …and the scope that IS read is never reported as inert.
    m.extras[-1].body = f"{eid}/code-name: the business really spells it this way"
    assert not [w for w in warnings_of(m) if "name a scope no check reads" in w]


def test_a_heading_that_declares_no_scopes_is_left_alone_and_a_PATH_key_is_never_a_scope():
    """Empty means unchecked, which is the safe default twice over: a family whose scopes nobody has
    enumerated keeps working, and the two PATH-keyed headings must never be read this way — a
    `src/app/` key is a directory, and reading its slash as a scope would report every coverage
    record on every live map as dead."""
    from coyomap import records as records_mod
    m = make_valid_model()
    m.extras = [ExtraSection(heading="Coverage exceptions", body="src/app/: vendored and coarse"),
                ExtraSection(heading="Interface exceptions", body="UC1/doors: the anchor is right")]
    assert not records_mod.inert_scoped_keys(m, "Coverage exceptions")
    assert not records_mod.inert_scoped_keys(m, "Interface exceptions")
    assert not [w for w in warnings_of(m) if "name a scope no check reads" in w], warnings_of(m)


# ── a user-facing surface no use case reaches ──────────────────────────────────────────────────

def make_unreached_surface_model() -> ProjectModel:
    """A `theirs` surface the product calls, that no story goes near. argus's paid page-reading
    service in miniature: the map carries the surface AND the dep standing on it, and the one flow
    step that leaves the product is drawn at a different, cheaper far side."""
    m = make_interface_model()
    m.deps.append(Dep(id="D2", name="Paid reader", kind="service", type="api",
                      interfaces=["I2"]))
    m.interfaces.append(Interface(
        id="I2", name="Paid reading service", what="Fetches a page we cannot get past, for a fee.",
        side="theirs", facing="user", kind="api", source="src/v.py:60",
        evidence=[EvidenceItem(file="src/v.py:60",
                               why="hands one address to the paid service")]))
    return m


def test_a_surface_no_use_case_reaches_warns():
    m = make_unreached_surface_model()
    hits = [w for w in warnings_of(m) if "I2" in w and "reached by NO use case" in w]
    assert len(hits) == 1, hits


def test_an_OPERATOR_surface_owes_a_use_case_TOO():
    """The `facing: operator` exemption this check shipped with is GONE, and it must stay gone. It
    was drawn from 5 unstoried surfaces, 4 of them operator-facing, read as "operator surfaces do
    not get stories". The fuller count says the opposite: 7 of the 11 operator-facing surfaces
    across the two live maps ALREADY have use cases, and each of the 4 without names a person in
    its own description ("the log records an operator searches and charts")."""
    m = make_unreached_surface_model()
    m.interfaces[1].facing = "operator"
    hits = [w for w in warnings_of(m) if "I2" in w and "reached by NO use case" in w]
    assert len(hits) == 1, hits
    assert "OPERATOR surface owes one" in hits[0], hits[0]


#: EVERY "…clears it" TEST BELOW ASSERTS THE ADVISORY FIRED FIRST. A filter on a string the
#: validator does not emit is VACUOUSLY TRUE, and five of these shipped that way for one commit
#: after the message was reworded — silently un-testing the recorded escape and the never-blocks
#: guarantee at the very commit that made every interface owe a use case. Asserting the fire before
#: the fix is what makes the silence mean something.
def _unreached_hits(m) -> list[str]:
    return [w for w in warnings_of(m) if "I2" in w and "reached by NO use case" in w]


def test_a_walk_step_drawn_at_the_surface_clears_it():
    m = make_unreached_surface_model()
    assert _unreached_hits(m), "the advisory must fire before the fix, or the silence proves nothing"
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="I2", phrase="asks the paid service",
                                     where="src/v.py:60"))
    assert not _unreached_hits(m)


def test_a_step_drawn_at_the_dep_standing_on_it_clears_it():
    # The third arm: a story that names the outside SYSTEM, not the surface it is met at, still
    # reaches that surface. Scores zero on both live maps, and must stay for the day one does.
    m = make_unreached_surface_model()
    assert _unreached_hits(m), "must fire before the fix"
    m.edges.append(Edge(src="C1", verb="calls", dst="D2", why="fetch", where="src/v.py:60"))
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="D2", phrase="asks the paid service",
                                     where="src/v.py:60"))
    assert not _unreached_hits(m)


def test_a_use_case_naming_one_of_its_ways_in_does_NOT_clear_it_only_a_step_does():
    """"Reached" means a step of a flow drawn at the surface (`use_case_interfaces`), the same rule
    the use case cards, the picture's order and the far side read. Naming one of the surface's ways
    in on a use case is an authored claim, and the flow owes the step that backs it — so on its own
    it clears nothing, and the advisory keeps asking for the story."""
    m = make_unreached_surface_model()
    assert _unreached_hits(m), "must fire before the fix"
    m.entry_points.append(EntryPoint(id="EP9", kind="http-route", trigger="GET /paid",
                                     activation="external", source="src/v.py:60", component="C1"))
    m.interfaces[1].ways_in = ["EP9"]
    m.use_cases[0].entry_points = ["EP9"]
    assert _unreached_hits(m), "a named way in is a claim, not a story"


def test_a_recorded_line_silences_it():
    m = make_unreached_surface_model()
    assert _unreached_hits(m), "must fire before the fix"
    m.extras = [ExtraSection(
        heading="Interface exceptions",
        body="I2: the paid reader is a fallback the stories deliberately do not branch on")]
    assert not _unreached_hits(m)


def test_an_unstoried_interface_never_blocks():
    m = make_unreached_surface_model()
    assert _unreached_hits(m), "it must fire at all, or 'never blocks' is vacuous"
    assert not [p for p in problems_of(m) if "reached by NO use case" in p]


def test_one_gap_owes_one_line_not_two():
    """The two advisories can no longer double-bill, BY CONSTRUCTION rather than by a guard. "Hands
    something over to nobody" now reads the directions its own STEPS carry, so a surface no story
    reaches carries none, and only the missing-story line fires."""
    m = make_unreached_surface_model()
    m.interfaces[1].side = "ours"
    m.interfaces[1].evidence = []
    hits = [w for w in warnings_of(m) if "I2" in w]
    assert any("reached by NO use case" in w for w in hits), hits
    assert not any("never says to whom" in w for w in hits), hits


# ── `direction` — the map's ONE statement of which way data moved ───────────────────────────────
#
# All three paths below were UNTESTED when the field shipped, and the field is the whole reason
# `interfaces[].carries[]` could be removed. An adversarial review found the gap.

def make_direction_model() -> ProjectModel:
    """One flow with a door, the surface step behind it, a record step and a plain component step —
    the four shapes the rule has to tell apart."""
    m = make_interface_model()
    m.flows[0].steps = [
        FlowStep(n=1, src="R1", dst="I1", phrase="types the command"),
        FlowStep(n=2, src="I1", dst="C1", phrase="hands it to the runner", where="src/v.py:3",
                 direction="in"),
        FlowStep(n=3, src="C1", dst="E1", phrase="writes the order", where="src/v.py:4",
                 direction="out"),
        FlowStep(n=4, src="C1", dst="C1", phrase="checks the flag", where="src/v.py:5"),
    ]
    return m


def test_a_valid_direction_model_is_clean():
    m = make_direction_model()
    assert not [p for p in problems_of(m) if "direction" in p], problems_of(m)
    assert not [w for w in warnings_of(m) if "no `direction`" in w], warnings_of(m)


def test_a_direction_outside_the_vocabulary_BLOCKS():
    m = make_direction_model()
    m.flows[0].steps[1].direction = "inbound"
    hits = [p for p in problems_of(m) if "direction='inbound'" in p]
    assert len(hits) == 1, problems_of(m)
    assert "in/out/both" in hits[0], hits[0]


def test_EVERY_word_in_the_vocabulary_is_accepted():
    # Looping the grammar constant would shrink with it; naming the three literally is what keeps a
    # silently-dropped word visible — the vacuous-test shape this suite has been bitten by before.
    assert set(grammar.STEP_DIRECTIONS) == {"in", "out", "both"}
    for word in ("in", "out", "both"):
        m = make_direction_model()
        m.flows[0].steps[1].direction = word
        assert not [p for p in problems_of(m) if "direction" in p], (word, problems_of(m))


def test_a_DOOR_carrying_a_direction_BLOCKS():
    """The exemption, in the direction that matters. A role standing at a surface is a human action
    with no product end — argus's operator opens the log store's own console and nothing of ours
    moves. Forcing an answer there produced labels contradicting their own step's phrase."""
    m = make_direction_model()
    m.flows[0].steps[0].direction = "in"
    hits = [p for p in problems_of(m) if "step 1" in p and "not at either end" in p]
    assert len(hits) == 1, problems_of(m)
    assert "DOOR" in hits[0], hits[0]


def test_a_COMPONENT_TO_COMPONENT_step_carrying_a_direction_BLOCKS():
    m = make_direction_model()
    m.flows[0].steps[3].direction = "out"
    assert [p for p in problems_of(m) if "step 4" in p and "not at either end" in p], problems_of(m)


def test_a_step_at_a_DEP_carries_no_direction():
    """A dep is the PIPE, not the surface. `Cn → Dn` crosses nothing the map can answer for, and a
    fixture that put a direction there passed for a while because `build_index` never validates."""
    m = make_direction_model()
    m.flows[0].steps.append(FlowStep(n=5, src="C1", dst="D1", phrase="calls it",
                                     where="src/v.py:6", direction="out"))
    assert [p for p in problems_of(m) if "step 5" in p and "not at either end" in p], problems_of(m)


def test_a_MISSING_direction_is_advisory_and_names_the_steps():
    """Advisory, not blocking, and deliberately so: a gate on a brand-new required field walls off
    every rebuild before one build has shown an agent filling it. The retro-check carries the
    promotion."""
    m = make_direction_model()
    m.flows[0].steps[1].direction = ""
    m.flows[0].steps[2].direction = ""
    hits = [w for w in warnings_of(m) if "no `direction`" in w]
    assert len(hits) == 1, warnings_of(m)
    assert "2 step(s)" in hits[0] and "step 2" in hits[0] and "step 3" in hits[0], hits[0]
    assert not [p for p in problems_of(m) if "no `direction`" in p], "advisory, never blocking"


def test_the_RECORD_arm_is_covered_too():
    """83 of the 170 record steps across the live maps sit on a component/record pair whose arrows
    say BOTH read and write — the stated reason this field answers at a record and not only at a
    surface."""
    m = make_direction_model()
    m.flows[0].steps[2].direction = ""
    hits = [w for w in warnings_of(m) if "no `direction`" in w]
    assert hits and "step 3" in hits[0], warnings_of(m)


def test_a_SUB_FLOW_step_owes_one_too():
    """A sub-flow's steps are ordinary steps under one rulebook, and a surface reached only from
    inside an `SFn` is invisible without this."""
    m = make_direction_model()
    m.subflows.append(SubFlow(id="SF1", name="Read it", steps=[
        FlowStep(n=1, src="C1", dst="I1", phrase="answers through the surface", where="src/v.py:7")]))
    m.flows[0].steps.append(FlowStep(n=5, src="C1", dst="C1", phrase="runs it", subflow="SF1"))
    hits = [w for w in warnings_of(m) if "no `direction`" in w]
    assert hits and "SF1 step 1" in hits[0], warnings_of(m)


def test_a_REFERENCE_step_owes_none():
    """It carries no location of its own either; its endpoints are the run's entry and exit."""
    m = make_direction_model()
    m.subflows.append(SubFlow(id="SF1", name="Read it", steps=[
        FlowStep(n=1, src="C1", dst="I1", phrase="answers", where="src/v.py:7", direction="out")]))
    m.flows[0].steps.append(FlowStep(n=5, src="C1", dst="I1", phrase="", subflow="SF1"))
    assert not [w for w in warnings_of(m) if "no `direction`" in w and "flow step 5" in w], \
        warnings_of(m)


def test_a_ROLE_reading_a_RECORD_owes_no_direction():
    """"The map's own code" is a component or a subsystem, never a dep and never a role. A person
    does not read a row out of our store — some code does it for them — so `Rn → En` is a human
    action like any other door. The migration script and the validator disagreed here for a while;
    no live map has the shape, which is exactly how a disagreement survives."""
    m = make_direction_model()
    m.flows[0].steps.append(FlowStep(n=5, src="R1", dst="E1", phrase="looks at their order"))
    assert not [w for w in warnings_of(m) if "no `direction`" in w], warnings_of(m)
    m.flows[0].steps[-1].direction = "in"
    assert [p for p in problems_of(m) if "step 5" in p and "not at either end" in p], problems_of(m)


# ── every SAVED record owes a use case ─────────────────────────────────────────────────────────
#
# The twin of "every interface owes a use case", asking the same question about the other half of
# the map's outside: an interface is where the product meets the world, a saved record is what it
# keeps, and neither means anything until a story says what it is FOR.

def make_saved_record_model() -> ProjectModel:
    """One saved record no story reaches, one inside it, and one shape that is not saved at all."""
    m = make_valid_model()
    m.entities = [
        make_entity("E1", "Order", source="src/order.py:1"),
        make_entity("E2", "OrderLine", source="src/order.py:20"),
        make_entity("E3", "OrderResponse", source="src/api.py:9"),
    ]
    m.entities[0].store = Store(dep="D1", container="orders", mode="collection")
    m.entities[1].store = Store(dep="D1", container="orders", mode="embedded")
    m.entities[2].store = Store(container="built per request", mode="transient")
    m.entities[0].relations = [EntityRelation(verb="contains", target="E2",
                                              src_card="1", dst_card="*", display="OrderLine")]
    m.flows = [Flow(uc="UC1", title="View order",
                    steps=[FlowStep(n=1, src="R1", dst="C1", phrase="opens it")])]
    m.edges = [Edge(src="C1", verb="reads", dst="E1", why="show", where="src/v.py:5"),
               Edge(src="C1", verb="uses", dst="D1", why="query", where="src/v.py:7")]
    return m


def _unstoried_records(m) -> list[str]:
    return [w for w in warnings_of(m) if "SAVED record(s) are reached by NO use case" in w]


def test_a_saved_record_no_use_case_reaches_warns():
    m = make_saved_record_model()
    hits = _unstoried_records(m)
    assert len(hits) == 1, warnings_of(m)
    assert "E1 (Order)" in hits[0] and "E2 (OrderLine)" in hits[0], hits[0]


def test_a_shape_the_codebase_does_not_SAVE_owes_nothing():
    """A transient is built for one call, a projection is a read shape over rows something else
    owns, an enum is a set of constants. Demanding a story for one would bury the real gaps: 142
    entities across the two live maps, 46 of them saved."""
    m = make_saved_record_model()
    assert "E3" not in _unstoried_records(m)[0], _unstoried_records(m)


def test_a_step_at_the_record_clears_it():
    m = make_saved_record_model()
    assert _unstoried_records(m), "must fire before the fix, or the silence proves nothing"
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="E1", phrase="reads the order",
                                     where="src/v.py:5", direction="in"))
    assert not [w for w in _unstoried_records(m) if "E1 (Order)" in w], warnings_of(m)


def test_a_record_INSIDE_a_reached_one_counts_as_reached():
    """The container arm, and the reason the rule is affordable. An embedded record lives in its
    parent's row, so a story that writes the parent writes the piece; requiring its own step would
    put 16 of them into mcpolis's walks to say what one step already says."""
    m = make_saved_record_model()
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="E1", phrase="reads the order",
                                     where="src/v.py:5", direction="in"))
    assert not _unstoried_records(m), warnings_of(m)


def test_the_container_walk_survives_a_cycle():
    """`contains` is authored and nothing stops two records naming each other."""
    m = make_saved_record_model()
    m.entities[1].relations = [EntityRelation(verb="contains", target="E1",
                                              src_card="1", dst_card="1", display="Order")]
    assert _unstoried_records(m), "a cycle must not hide the gap, and must not hang"


def test_a_recorded_line_silences_one_record():
    m = make_saved_record_model()
    m.extras.append(ExtraSection(heading="Balance exceptions",
                                 body="E1: only the nightly migration writes this"))
    hits = _unstoried_records(m)
    assert hits and "E1 (Order)" not in hits[0], hits
    assert "E2 (OrderLine)" in hits[0], "and it silences only the record it names"


def test_an_unstoried_record_never_blocks():
    m = make_saved_record_model()
    assert _unstoried_records(m), "it must fire at all, or 'never blocks' is vacuous"
    assert not [p for p in problems_of(m) if "SAVED record" in p], problems_of(m)


def test_no_two_tests_in_this_file_share_a_name():
    """A duplicate `def test_x` silently REPLACES the first: the earlier one stops running, and
    nothing goes red. It happened here — `test_it_never_blocks` was written twice, once for the
    unstoried-interface advisory and once for the unstoried-record one, and the interface guarantee
    quietly stopped being checked. Same failure class as an assertion filtering on a string nothing
    emits: a test that is not run and a test that cannot fail look identical from the outside."""
    import ast
    src = Path(__file__).read_text(encoding="utf-8")
    names = [n.name for n in ast.parse(src).body
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"shadowed test(s): {dupes}"


# ── the stories must not contradict the arrows about which way data moved ───────────────────────

def make_direction_gap_model() -> ProjectModel:
    """A saved record with a `writes` arrow and only a READ in the story — the map disagreeing with
    itself about one record, which is the whole point: the arrow IS the evidence."""
    m = make_saved_record_model()
    m.edges.append(Edge(src="C1", verb="writes", dst="E1", why="save", where="src/v.py:9"))
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="E1", phrase="reads the order",
                                     where="src/v.py:5", direction="in"))
    return m


def _gap_hits(m) -> list[str]:
    return [w for w in warnings_of(m) if "ARROWS claim a direction NO walk step shows" in w]


def test_an_arrow_claiming_a_write_no_story_makes_warns():
    m = make_direction_gap_model()
    hits = _gap_hits(m)
    assert len(hits) == 1, warnings_of(m)
    assert "E1 (Order)" in hits[0] and "writes it, no story does" in hits[0], hits[0]


def test_the_story_writing_it_clears_the_contradiction():
    m = make_direction_gap_model()
    assert _gap_hits(m), "must fire before the fix, or the silence proves nothing"
    m.flows[0].steps.append(FlowStep(n=3, src="C1", dst="E1", phrase="writes the order",
                                     where="src/v.py:9", direction="out"))
    assert not _gap_hits(m), warnings_of(m)


def test_a_BOTH_step_answers_each_direction_at_once():
    m = make_direction_gap_model()
    m.flows[0].steps[-1].direction = "both"
    assert not _gap_hits(m), warnings_of(m)


def test_a_record_with_only_a_READS_arrow_is_correctly_SILENT():
    """mcpolis's pre-registered credentials are the live case: an admin puts that file there by
    hand, so read-and-never-written is the truth, not a gap. The arrows say so."""
    m = make_direction_gap_model()
    m.edges = [e for e in m.edges if not (e.dst == "E1" and e.verb == "writes")]
    assert not _gap_hits(m), warnings_of(m)


def test_a_GENERIC_verb_claims_no_direction():
    """`uses` and `accesses` reveal no role. Guessing a direction from one is how a roleless arrow
    would start making claims it cannot back."""
    m = make_direction_gap_model()
    for e in m.edges:
        if e.dst == "E1" and e.verb == "writes":
            e.verb = "uses"
    assert not _gap_hits(m), warnings_of(m)


def test_the_comparison_runs_ONE_WAY_the_arrows_are_the_oracle():
    """A step direction with no matching arrow is a DIFFERENT finding, already reported by the
    unbacked-entity-step check — and `assemble` derives the missing arrow from the step anyway."""
    m = make_saved_record_model()
    m.edges = [e for e in m.edges if e.dst != "E1"]
    m.flows[0].steps.append(FlowStep(n=2, src="C1", dst="E1", phrase="writes the order",
                                     where="src/v.py:9", direction="out"))
    assert not _gap_hits(m), "a step the arrows do not back is the other check's finding"


def test_a_record_inherits_its_HOLDERS_directions():
    m = make_direction_gap_model()
    m.edges.append(Edge(src="C1", verb="writes", dst="E2", why="save", where="src/v.py:9"))
    assert any("E2" in h for h in _gap_hits(m)), _gap_hits(m)
    m.flows[0].steps.append(FlowStep(n=3, src="C1", dst="E1", phrase="writes the order",
                                     where="src/v.py:9", direction="out"))
    assert not _gap_hits(m), "writing the holder writes the piece inside it"


def test_a_recorded_line_silences_the_contradiction():
    m = make_direction_gap_model()
    m.extras.append(ExtraSection(heading="Balance exceptions",
                                 body="E1: only the nightly migration writes this"))
    assert not _gap_hits(m), warnings_of(m)


def test_the_contradiction_never_blocks():
    m = make_direction_gap_model()
    assert _gap_hits(m), "it must fire at all, or 'never blocks' is vacuous"
    assert not [p for p in problems_of(m) if "ARROWS claim" in p], problems_of(m)


def test_a_TRACE_FRAGMENT_may_carry_a_direction_at_a_surface():
    """A fragment holds flows, sub-flows and edges and NO `interfaces` list, by its own contract.

    The surface arm asked `in iface_ids` while the record arm read the id SHAPE, in one expression.
    On a fragment that set is empty, so every `Cn → In` step looked like a DOOR and its direction
    was BLOCKED. A real partial run hit it: three correct directions were refused and stripped out
    so the agent could return a clean fragment, and the lint said nothing about why. `validate` on
    the assembled map would then report the very steps that had been silenced.

    An `In` that resolves to nothing is a different defect, and the id-resolution check reports it."""
    m = ProjectModel(title="frag", goal="g")
    m.flows = [Flow(uc="UC1", title="Sign in", steps=[
        FlowStep(n=1, src="C63", dst="I6", phrase="sends the person to the sign-in screen",
                 where="src/a.py:1", direction="out"),
        FlowStep(n=2, src="C1", dst="E1", phrase="writes the record",
                 where="src/a.py:2", direction="out")])]
    assert not m.interfaces and not m.entities, "the shape a trace fragment really has"
    problems, _ = validate_model_mod._check_flows(m)
    assert not [p for p in problems if "not at either end" in p], problems


def test_a_DOOR_in_a_fragment_is_still_blocked():
    """The fix reads the id shape; it must not become 'anything goes when the list is empty'. A role
    at a surface is a human action wherever it is authored."""
    m = ProjectModel(title="frag", goal="g")
    m.flows = [Flow(uc="UC1", title="Sign in", steps=[
        FlowStep(n=1, src="R1", dst="I6", phrase="clicks sign in", direction="in")])]
    problems, _ = validate_model_mod._check_flows(m)
    assert [p for p in problems if "not at either end" in p], problems


def test_a_walk_that_jumps_to_a_box_it_never_reached_is_flagged():
    """A walk is a chain: each step acts from somewhere the walk has already been. A step whose `src`
    appears for the first time as a SOURCE has no way in — the map cannot say how the story got there,
    and the picture draws that box hanging with no incoming arrow.

    Reported on mcpolis UC12: the walk runs a shared sub-use case that ends at one component, then step 22
    starts at "Tool catalog" with nothing joining them. The missing step was real and traceable in the
    code (`upstream_connection_service.py:1640` calls the tool registry's refresh).

    Advisory, never blocking: a walk may legitimately begin a second thread. 58 across the two live
    maps, and the ones read by hand were omissions."""
    m = ProjectModel(title="T", goal="G")
    m.use_cases = [UseCase(id="UC1", name="View")]
    m.components = [Component(id="C1", name="A", purpose="a"), Component(id="C2", name="B", purpose="b"),
                    Component(id="C3", name="C", purpose="c")]
    m.flows = [Flow(uc="UC1", title="View", steps=[
        FlowStep(n=1, src="C1", dst="C2", phrase="hand it on", where="src/a.py:1"),
        FlowStep(n=2, src="C3", dst="C1", phrase="hand it back", where="src/c.py:1"),
    ])]
    out = walk_jumps(m)
    assert len(out) == 1 and "UC1 step 2 starts at C3" in out[0]
    # …and a chain with no jump says nothing.
    m.flows[0].steps[1].src = "C2"
    assert walk_jumps(m) == []


def test_a_walk_jump_sees_through_a_shared_walk():
    """Running a shared sub-use case really does reach what is inside it, so the check expands. The commonest
    shape is a step right after a reference: the shared sub-use case ends somewhere inside itself and the next
    step starts somewhere new."""
    m = ProjectModel(title="T", goal="G")
    m.use_cases = [UseCase(id="UC1", name="View")]
    m.components = [Component(id="C1", name="A", purpose="a"), Component(id="C2", name="B", purpose="b"),
                    Component(id="C3", name="C", purpose="c")]
    m.subflows = [SubFlow(id="SF1", name="Shared", steps=[
        FlowStep(n=1, src="C1", dst="C3", phrase="reach C", where="src/a.py:1")])]
    m.flows = [Flow(uc="UC1", title="View", steps=[
        FlowStep(n=1, src="C1", dst="C2", phrase="hand it on", where="src/a.py:1"),
        FlowStep(n=2, src="C1", dst="C3", subflow="SF1"),
        FlowStep(n=3, src="C3", dst="C2", phrase="carry on", where="src/c.py:2"),
    ])]
    assert walk_jumps(m) == []          # the shared sub-use case reached C3, so step 3 has its way in
    m.subflows[0].steps[0].dst = "C2"   # …and now it does not
    assert len(walk_jumps(m)) == 1 and "step 3 starts at C3" in walk_jumps(m)[0]


def test_a_recorded_walk_jump_is_a_second_thread_not_a_gap():
    """The advisory has always ended "or record 'UCn: <why this begins a new thread>' under a
    'Walk jumps' extras heading", and nothing read that heading: `record` refused the line, and a
    live build carried the advisory with no escape. The heading is registered now and the check
    reads it — a recorded use case is a story that opens a second thread on purpose. One use case
    per line; a key with no why is a dismissal, as in every family."""
    m = ProjectModel(title="T", goal="G")
    m.use_cases = [UseCase(id="UC1", name="View"), UseCase(id="UC2", name="Sweep")]
    m.components = [Component(id="C1", name="A", purpose="a"), Component(id="C2", name="B", purpose="b"),
                    Component(id="C3", name="C", purpose="c")]
    def jumping(uc: str, title: str) -> Flow:
        return Flow(uc=uc, title=title, steps=[
            FlowStep(n=1, src="C1", dst="C2", phrase="hand it on", where="src/a.py:1"),
            FlowStep(n=2, src="C3", dst="C1", phrase="wake up later", where="src/c.py:1")])
    m.flows = [jumping("UC1", "View"), jumping("UC2", "Sweep")]
    assert len(walk_jumps(m)) == 2
    m.extras = [ExtraSection(heading="Walk jumps",
                             body="UC1: the sweep is a background job the first half set going")]
    out = walk_jumps(m)
    assert len(out) == 1 and out[0].startswith("UC2 step 2 starts at C3"), out
    m.extras = [ExtraSection(heading="Walk jumps", body="UC2:")]
    assert len(walk_jumps(m)) == 2, "a key alone is a dismissal, not a record"


def test_a_walk_that_leaves_its_person_with_no_reply_is_reported():
    """The method says a door works both ways: a walk arrives through one and hands its result back
    through one. Nothing checked the second half.

    THIS IS THE ARM THE INTERFACE SWEEP COULD NOT REACH. "Every interface owes a use case" reads
    DOWN the interface table, so it only ever finds a surface no story crosses; a story that needed
    a surface NOBODY WROTE is invisible to it, because that row is not in the table to be read. On
    the 2026-09-06 mcpolis build a tracing agent reported exactly that — "no authored surface fits,
    so I added no door and the story stops at the click" — the lead read it as a wording correction,
    and the map lost its only `handoff` surface while the use case's own outcome still reads "their
    own mail program opens". Measured across the two maps: 0 person-facing walks fire on the
    previous one and 5 of 43 on that build, including the story in question."""
    from coyomap.model import (Component, ExtraSection, Flow, FlowStep, Interface, ProjectModel,
                               Role, UseCase)
    m = ProjectModel(title="T", goal="G")
    m.roles = [Role(id="R1", name="Visitor", kind="human", audience="user")]
    m.components = [Component(id="C1", name="Page", purpose="shows the address", source="a.py:1")]
    m.interfaces = [Interface(id="I1", name="Website", side="ours", kind="screen", facing="user")]
    m.use_cases = [UseCase(id="UC1", name="Ask the team a question")]
    m.flows = [Flow(uc="UC1", title="Ask the team a question", steps=[
        FlowStep(n=1, src="R1", dst="I1", phrase="open the contact page"),
        FlowStep(n=2, src="I1", dst="C1", phrase="render the address"),
        FlowStep(n=3, src="R1", dst="C1", phrase="click the address that fits the question"),
    ])]
    fired = [w for w in validate_model_mod._walk_no_reply_warnings(m) if "UC1" in w]
    assert fired, "a walk ending on the person acting draws nothing"
    assert "step 3" in fired[0] and "click the address" in fired[0], (
        "the warning must name WHICH step left the person waiting")

    # A reply closes it: the last actor contact now runs product -> person.
    m.flows[0].steps.append(FlowStep(n=4, src="I1", dst="R1", phrase="hand the visitor to their "
                                                                    "own mail program"))
    assert not validate_model_mod._walk_no_reply_warnings(m)

    # A SERVICE role opening its own scheduled work is owed no reply, and firing on those buried
    # the five that mattered under three timer walks on the same map.
    m.flows[0].steps.pop()
    m.roles[0].kind = "software"
    assert not validate_model_mod._walk_no_reply_warnings(m)

    # …and the recorded escape silences it durably, keyed on the use case.
    m.roles[0].kind = "human"
    m.extras = [ExtraSection(heading="Missing surfaces",
                             body="UC1: the visitor leaves for a program we never see")]
    assert not validate_model_mod._walk_no_reply_warnings(m)


def test_a_whole_kind_of_front_door_that_nobody_names_is_reported():
    """A total hides this: a map can hold its overall naming up on screens while every address
    behind them goes unnamed, and what is lost is the map's answer to "which address does this
    action fire?".

    THE COLLAPSE THIS WAS WRITTEN FOR. Between two mcpolis builds the method's front-door sentence
    widened from "two parties" to "one party arriving two ways". The next build read an admin's
    screen plus the address behind it as one party arriving twice, kept the screen and dropped the
    address. Per kind: `http-route` named went 38 of 114 to 2 of 118 and `mcp-tool` 6 of 43 to 1 of
    43, while `ui-route` held at 20 of 39 and 21 of 36. Only the action-level kinds moved."""
    from coyomap.model import Component, EntryPoint, ExtraSection, ProjectModel, UseCase
    m = ProjectModel(title="T", goal="G")
    m.components = [Component(id="C1", name="Routes", purpose="serves", source="a.py:1")]
    m.entry_points = [EntryPoint(id=f"EP{i}", kind="http-route", activation="external",
                                 component="C1", trigger=f"address {i}", source=f"a.py:{i}")
                      for i in range(1, 21)]
    m.use_cases = [UseCase(id="UC1", name="Do it", entry_points=["EP1"])]
    fired = validate_model_mod._kind_naming_warnings(m)
    assert fired and "1 of 20 `http-route`" in fired[0]

    # Above the floor it goes quiet: naming three of twenty is 15%.
    m.use_cases[0].entry_points = ["EP1", "EP2", "EP3"]
    assert not validate_model_mod._kind_naming_warnings(m)

    # A kind too small for a rate to mean anything never fires: one row would swing any threshold.
    m.use_cases[0].entry_points = ["EP1"]
    m.entry_points = m.entry_points[:9]
    assert not validate_model_mod._kind_naming_warnings(m)

    # Plumbing is not a front door. Middleware scores 0 of 15 on every map ever measured, and
    # reporting it is how a reader learns to skip the whole advisory.
    m.entry_points = [EntryPoint(id=f"EP{i}", kind="middleware", activation="external",
                                 component="C1", trigger=f"filter {i}", source=f"a.py:{i}")
                      for i in range(1, 21)]
    assert not validate_model_mod._kind_naming_warnings(m)

    # A map where NO use case names anything is the degenerate case another check owns; reporting it
    # once per kind would say the same fact several times.
    m.entry_points = [EntryPoint(id=f"EP{i}", kind="http-route", activation="external",
                                 component="C1", trigger=f"address {i}", source=f"a.py:{i}")
                      for i in range(1, 21)]
    m.use_cases[0].entry_points = []
    assert not validate_model_mod._kind_naming_warnings(m)

    # …and the recorded line silences one kind durably.
    m.use_cases[0].entry_points = ["EP1"]
    m.extras = [ExtraSection(heading="Entry-point coverage",
                             body="http-route naming: every address is reached from one shell")]
    assert not validate_model_mod._kind_naming_warnings(m)


def test_a_record_kept_inside_nothing_that_is_kept_is_reported():
    """`embedded` means persisted inside another record's row, so it needs a holder and that holder
    must itself be saved. The word is defined in full in one source file no map-building agent
    opens; what an agent reads said "inside a parent's row", with PERSISTED missing. So a build read
    it as "nested": on the 2026-09-07 mcpolis map every row it labelled `embedded` from one
    response-models file was nested inside another row and none was inside anything saved.

    The escape is a SCOPED token. The bare id under this heading already answers the saved-record
    rule, and on that map one line — "E54, E68, E75, E78: three of these live inside a record a
    story already reaches" — pre-silenced all four before this check existed, with a reason the
    map's own data contradicts."""
    from coyomap.model import Entity, EntityField, EntityRelation, ExtraSection, ProjectModel, Store
    m = ProjectModel(title="T", goal="G")
    holder = Entity(id="E1", name="Page answer", meaning="what one screen returns",
                    source="a.py:1", store=Store(mode="projection", container="the detail page"))
    holder.fields = [EntityField(name="rows", type="list[E2]")]
    inner = Entity(id="E2", name="Row", meaning="one line of it", source="a.py:9",
                   store=Store(mode="embedded", container="the detail page"))
    m.entities = [holder, inner]
    fired = validate_model_mod._orphan_embedded_warnings(m)
    assert fired and "E2" in fired[0] and "E1 (projection)" in fired[0], fired

    # A saved holder is the whole point: the same shape inside a real compartment is fine.
    holder.store = Store(mode="collection", container="answers")
    assert not validate_model_mod._orphan_embedded_warnings(m)

    # No holder at all is the other half — either the mode is wrong or the `contains` is missing.
    holder.store = Store(mode="collection", container="answers")
    holder.fields = []
    fired = validate_model_mod._orphan_embedded_warnings(m)
    assert fired and "no record holds it at all" in fired[0]

    # A containment RELATION is the second arm of the same question.
    holder.relations = [EntityRelation(verb="contains", target="E2")]
    assert not validate_model_mod._orphan_embedded_warnings(m)

    # The bare id must NOT silence it — that token already answers a different check.
    holder.relations = []
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="E2: it lives inside a record a story already reaches")]
    assert validate_model_mod._orphan_embedded_warnings(m), (
        "a blanket waiver written for another check answered this one before it was asked")

    # …and the scoped token does silence it.
    m.extras = [ExtraSection(heading="Balance exceptions",
                             body="E2/embedded: the holder is authored in a slice we do not map")]
    assert not validate_model_mod._orphan_embedded_warnings(m)


def test_the_embedded_holder_chain_must_end_somewhere_real():
    """One level is not enough, and the containment helper's own docstring says so: it is "not
    transitive: callers walk it themselves, and must carry a `seen` set".

    The first version asked only whether an immediate holder `is_saved`, and `embedded` counts as
    saved. So a record embedded inside an embedded inside a read shape passed, and a record naming
    ITSELF as its holder passed on its own say-so. An adversarial reader found the second on
    coyomap's own map: E38 `DirExpectation`, whose only holder is E38. A cycle of two never
    converges at all, which is why `seen` is not optional."""
    from coyomap.model import Entity, EntityField, ProjectModel, Store

    def rec(i, mode, holds=None):
        e = Entity(id=i, name=i, meaning="m", source=f"a.py:{i[1:]}",
                   store=Store(mode=mode, container="c"))
        if holds:
            e.fields = [EntityField(name="inner", type=f"list[{holds}]")]
        return e

    # A chain that never lands: E3 embedded in E2 embedded in E1, and E1 is a read shape.
    m = ProjectModel(title="T", goal="G")
    m.entities = [rec("E1", "projection", "E2"), rec("E2", "embedded", "E3"), rec("E3", "embedded")]
    fired = {w.split()[0] for w in validate_model_mod._orphan_embedded_warnings(m)}
    assert fired == {"E2", "E3"}, fired

    # The same chain landing on a real compartment is fine.
    m.entities[0].store = Store(mode="collection", container="rows")
    assert not validate_model_mod._orphan_embedded_warnings(m)

    # A record naming ITSELF as its holder is held by nothing.
    m.entities = [rec("E9", "embedded", "E9")]
    fired = validate_model_mod._orphan_embedded_warnings(m)
    assert fired and "E9" in fired[0]

    # A cycle terminates instead of hanging, and both rows are reported.
    m.entities = [rec("E1", "embedded", "E2"), rec("E2", "embedded", "E1")]
    assert {w.split()[0] for w in validate_model_mod._orphan_embedded_warnings(m)} == {"E1", "E2"}


def make_variant_map():
    """A saved row holding one record, and two variants of that record authored as `isA`.

    The reminderrepo shape: 27 of its 29 `embedded` rows name a real table as their container, and
    the 25 the check reported reach that table through a subtype relation, never a `contains` — the
    map holds no `contains` pointing at them at all."""
    from coyomap.model import Entity, EntityRelation, ProjectModel, Store
    m = ProjectModel(title="T", goal="G")
    table = Entity(id="E1", name="Activity", meaning="one scheduled thing", source="a.py:1",
                   store=Store(mode="collection", container="activities"))
    table.relations = [EntityRelation(verb="contains", target="E2")]
    base = Entity(id="E2", name="Notification security", meaning="who may see the reminder",
                  source="a.py:9", store=Store(mode="embedded", container="activities"))
    kinds = [Entity(id=i, name=n, meaning="one way to do it", source=f"a.py:{i[1:]}",
                    store=Store(mode="embedded", container="activities"))
             for i, n in (("E3", "Public"), ("E4", "By code"))]
    for k in kinds:
        k.relations = [EntityRelation(verb="isA", target="E2")]
    m.entities = [table, base, *kinds]
    return m


def test_a_variant_lands_where_the_record_it_is_a_kind_of_lands():
    """The holder walk followed containment alone, so a VARIANT of a saved record read as kept
    inside nothing — 25 of reminderrepo's 29 `embedded` rows, every one of them naming the real
    table it sits in. The map states that family as `isA` and authors no `contains` for it, so the
    check was asking for a relation the map does not use for this.

    A supertype is not a holder, which is why this is its own walk: it says WHERE the row lands, not
    what is inside what."""
    m = make_variant_map()
    assert not validate_model_mod._orphan_embedded_warnings(m)

    # It is the LANDING that clears it, never the relation on its own: a variant of a read shape is
    # still kept nowhere.
    m.entities[1].store.mode = "projection"
    fired = {w.split()[0] for w in validate_model_mod._orphan_embedded_warnings(m)}
    assert fired == {"E3", "E4"}, fired

    # A relation that is not inheritance says nothing about where the row lands.
    m.entities[1].store.mode = "embedded"
    for k in m.entities[2:]:
        k.relations[0].verb = "refersTo"
    assert {w.split()[0] for w in validate_model_mod._orphan_embedded_warnings(m)} == {"E3", "E4"}

    # `extends` is the vocabulary's other inheritance verb and reads the same way.
    for k in m.entities[2:]:
        k.relations[0].verb = "extends"
    assert not validate_model_mod._orphan_embedded_warnings(m)


def test_the_supertype_walk_is_read_from_the_relation_vocabulary():
    """Which verbs count is `grammar.REL_KIND`'s answer, not a second list here — the relation
    checks, the class diagram and this walk must call the same verbs inheritance."""
    from coyomap import grammar
    m = make_variant_map()
    inheritance = {v for v, kind in grammar.REL_KIND.items() if kind == "inheritance"}
    assert inheritance, "the vocabulary must still name an inheritance kind"
    for verb in inheritance:
        for k in m.entities[2:]:
            k.relations[0].verb = verb
        assert not validate_model_mod._orphan_embedded_warnings(m), verb
    assert set(validate_model_mod.record_supertypes(m)) == {"E3", "E4"}


def test_a_machine_step_after_a_person_no_longer_hides_the_dead_end():
    """The first version took the last step touching ANY actor and then asked whether that one was
    a person. So a single machine step after a person's dead end hid it, and an adversarial reader
    found the shipped check silent on argus UC3 and on coyomap's own UC38 — the exact defect it
    exists for. It also read a walk's OWN steps, so a reply handed back inside a shared sub-use case
    read as no reply, and a dead end inside one was invisible."""
    from coyomap.model import (Component, Flow, FlowStep, Interface, ProjectModel, Role, SubFlow,
                               UseCase)
    m = ProjectModel(title="T", goal="G")
    m.roles = [Role(id="R1", name="Visitor", kind="human", audience="user"),
               Role(id="R3", name="Assistant", kind="ai-agent", audience="user")]
    m.components = [Component(id="C1", name="App", purpose="p", source="a.py:1")]
    m.interfaces = [Interface(id="I1", name="Site", side="ours", kind="screen", facing="user"),
                    Interface(id="I2", name="Sign-in", side="theirs", kind="hosted-screen",
                              facing="user")]
    m.use_cases = [UseCase(id="UC1", name="Approve")]
    m.flows = [Flow(uc="UC1", title="Approve", steps=[
        FlowStep(n=1, src="R1", dst="I1", phrase="approve it"),
        FlowStep(n=2, src="I1", dst="R3", phrase="hand the assistant its pass"),
    ])]
    fired = validate_model_mod._walk_no_reply_warnings(m)
    assert fired and "R1" in fired[0], "a machine step after the person still hides the dead end"

    # A person answered inside a SHARED sub-use case is answered. The walk's own steps do not say so.
    m.subflows = [SubFlow(id="SF1", name="Say thanks", steps=[
        FlowStep(n=1, src="I1", dst="R1", phrase="show the confirmation")])]
    m.flows[0].steps.append(FlowStep(n=3, src="I1", dst="I1", phrase="run the thanks", subflow="SF1"))
    assert not validate_model_mod._walk_no_reply_warnings(m)

    # Somebody else's console, as the walk's LAST act, is a door we cannot answer.
    m.subflows = []
    m.flows[0].steps = [FlowStep(n=1, src="R1", dst="I2", phrase="search their log store")]
    assert not validate_model_mod._walk_no_reply_warnings(m)

    # …but stepping out to a third party while the walk CARRIES ON without the person is the
    # opposite case, and exempting it hid argus UC3.
    m.flows[0].steps.append(FlowStep(n=2, src="I1", dst="R3", phrase="answer the assistant instead"))
    fired = validate_model_mod._walk_no_reply_warnings(m)
    assert fired and "R1" in fired[0]


def test_validate_json_carries_the_sweep_worklist_as_rows():
    """`audit --json` has a structured `worklist`; `validate --json` hid its sweep worklist inside one
    clipped prose advisory. A build hand-parsed the text and then searched the JSON for a key that
    did not exist. The rows are here now."""
    from coyomap.validate_model import sweep_worklist
    m = ProjectModel(title="T", goal="G")
    m.use_cases = [UseCase(id="UC1", name="Delete")]
    m.components = [Component(id="C1", name="A", purpose="a", source="src/a.py:1"),
                    Component(id="C2", name="B", purpose="b", source="src/b.py:1")]
    m.flows = [Flow(uc="UC1", title="Delete", steps=[
        FlowStep(n=1, src="C1", dst="C2", phrase="refuse the delete unless the caller is an admin",
                 where="src/a.py:4")])]
    rows = sweep_worklist(m, None)
    assert isinstance(rows, list)
    for row in rows:
        assert set(row) == {"container", "step", "where", "phrase"}, row


# --- what a recorded 'Interface exceptions' id silenced, by family (retro 2026-09-08, row 15) ----

def test_a_recorded_interface_id_is_disclosed_by_the_family_it_silenced():
    """One heading forgave 35 keys across five check families on a live build and `validate`
    disclosed 8 (the excused ways in). Every silence is now on screen, one line by family, and a
    recorded id that silences nothing is named as stale."""
    m = make_unreached_surface_model()
    m.interfaces[1].facing = ""
    m.extras = [ExtraSection(heading="Interface exceptions",
                             body="I2: the paid reader is a deliberate fallback\nI9: gone")]
    ws = warnings_of(m)
    assert not _unreached_hits(m) and not [w for w in ws if w.startswith("I2 (") and "facing" in w]
    line = next(w for w in ws if "interface advisory/advisories suppressed" in w)
    assert "no `facing`: I2" in line and "reached by no use case: I2" in line, line
    assert line.startswith("2 interface")
    stale = next(w for w in ws if "silence nothing" in w)
    assert "I9" in stale and "I2" not in stale, stale


def test_an_unrecorded_map_prints_no_disclosure_line():
    ws = warnings_of(make_unreached_surface_model())
    assert not [w for w in ws if "suppressed by recorded 'Interface exceptions'" in w
                or "silence nothing" in w]


def test_a_scoped_use_case_record_is_disclosed_under_its_gate_and_a_stray_key_as_idle():
    """The retrofit gates honour `UCn/<scope>` tokens under the same heading, and a `Cn` line there
    is honoured by nothing; the first disclosure read only the I/EP ids and saw neither."""
    m = make_unreached_surface_model()
    m.extras = [ExtraSection(heading="Interface exceptions",
                             body="UC1/doors: deliberate\nC9: nothing here\nI2: fallback")]
    ws = warnings_of(m)
    line = next(w for w in ws if "interface advisory/advisories suppressed" in w)
    assert "the doors gate: UC1" in line and "reached by no use case: I2" in line, line
    stale = next(w for w in ws if "silence nothing" in w)
    assert "C9" in stale and "UC1" not in stale and "I2" not in stale, stale
