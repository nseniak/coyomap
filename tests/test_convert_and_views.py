#!/usr/bin/env python3
"""Tests for the generated views — including the GOLDEN case: the committed real-world mcpolis
map (tests/fixtures/mcpolis-project-map.json, generated once from the retired md→model converter
at the Phase-2 boundary — see git history for the original markdown) must come through the model
pipeline losslessly:

  - model → canonical JSON → model is the identity;
  - model → graph carries every defined element (the HTML view is a pure function of that dict);
  - the model audit + L2 worklist behave deterministically on the real map.

(The md-vs-json PIPELINE PARITY tests, and the converter's own unit tests, retired with the v1
parser — the md→model converter is gone; only the JSON model pipeline exists now.)

Run either way (needs an editable install: `make deps`):
    python3 tests/test_convert_and_views.py
    pytest tests/test_convert_and_views.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

from coyomap import audit_model, grammar
from coyomap.model import (
    Component,
    Dep,
    Edge,
    Entity,
    EntityField,
    EntryPoint,
    Flow,
    FlowStep,
    GlossaryRow,
    Group,
    HappyStep,
    Interface,
    MessagingRow,
    ProjectModel,
    Role,
    RoleRelation,
    StateMachine,
    StateTransition,
    Store,
    SubFlow,
    UseCase,
    all_elements,
    load_model,
    to_canonical_json,
)
from coyomap.viewer.gen_viewer import (
    flow_actors,
    flow_maps,
    flow_narrative,
    flow_narratives,
    subflow_chips,
    gen_flow_map_mermaid,
    hp_actors,
)
from coyomap.views import _store_str, model_to_graph, model_to_markdown

FIXTURE = Path(__file__).parent / "fixtures" / "mcpolis-project-map.json"
RENDER = [sys.executable, "-m", "coyomap.viewer.render"]


def make_fixture_model() -> ProjectModel:
    return load_model(FIXTURE.read_text(encoding="utf-8"))


def make_small_model() -> ProjectModel:
    """A minimal model exercising one field of each kind, for the render-CLI smoke test."""
    m = ProjectModel(title="Tiny", goal="A tiny demo.")
    m.components = [Component(id="C1", name="Viewer", subsystem=None, purpose="shows orders",
                              depends_on="", source=None,
                              confidence="")]
    m.entities = [Entity(id="E1", name="Order", store=Store(notes="orders"), meaning="a customer order",
                         source="src/order.py:1",
                         fields=[EntityField(name="id", type="str", markers=["PK"])])]
    return m


# --- golden equivalence on the real mcpolis map ----------------------------------

def test_golden_json_round_trip_is_identity():
    m = make_fixture_model()
    j = to_canonical_json(m)
    assert to_canonical_json(load_model(j)) == j


def test_render_cli_json_to_md_and_html():
    m = make_small_model()
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "project-map.json"
        src.write_text(to_canonical_json(m), encoding="utf-8")
        assert subprocess.run(RENDER + [str(src), str(Path(td) / "out.md")],
                              capture_output=True).returncode == 0
        assert (Path(td) / "out.md").read_text(encoding="utf-8") == model_to_markdown(m)
        # The interactive viewer is served by `coyomap serve` now — the only rendered file is the .md
        # view. A non-.md target is a clean error (exit 2), not a silent no-op, and writes nothing.
        r = subprocess.run(RENDER + [str(src), str(Path(td) / "out.html")], capture_output=True, text=True)
        assert r.returncode == 2 and "coyomap serve" in r.stderr
        assert not (Path(td) / "out.html").exists()


def test_golden_graph_carries_every_defined_element():
    """model→graph must expose every defined element as a node (the HTML view is a pure function
    of this dict), with the map's header metadata intact."""
    m = make_fixture_model()
    g = model_to_graph(m)
    assert g["title"] and g["commit"] == m.commit and g["goal"]
    node_ids = set(g["nodes"])
    for eid in all_elements(m):
        # HP steps ride the `happy_path` list; roles ride the `roles` list (actors resolve to names,
        # they are not backbone nodes) — neither is a node in the graph dict.
        if not eid.startswith("HP") and not eid.startswith("R"):
            assert eid in node_ids, f"{eid} missing from the graph"
    assert len(g["happy_path"]) == len(m.happy_path)
    assert len(g["roles"]) == len(m.roles)
    assert len(g["glossary"]) == len(m.glossary)
    assert g["edges"], "the fixture's backbone must survive into the graph"


def test_golden_graph_carries_reference_collections_and_metadata():
    """The operational/reference collections the viewer's System & Tests tabs read (and the header
    metadata) must ride into the graph, one graph row per model row — nothing dropped at model→graph."""
    m = make_fixture_model()
    g = model_to_graph(m)
    assert g["built"] == m.built and g["format"] == m.format
    for key, coll in [("run_commands", m.run_commands), ("entry_points", m.entry_points),
                      ("non_entity_types", m.non_entity_types), ("deployment", m.deployment),
                      ("observability", m.observability), ("security", m.security),
                      ("config", m.config), ("tests", m.tests), ("extras", m.extras)]:
        assert len(g[key]) == len(coll), f"{key} lost rows at model→graph"
    assert g["tests_note"] == m.tests_note


def test_golden_graph_attaches_entry_points_and_resolves_test_targets():
    """Entry points that name a component surface on that component's node (the 'Triggered by' list),
    and each tests[] row resolves its target ids to `{id, name, node}` for the Tests tab."""
    m = make_fixture_model()
    g = model_to_graph(m)
    # every node carrying entry points is a component, and each entry point has the expected shape
    carriers = [nid for nid, n in g["nodes"].items() if n.get("entry_points")]
    assert carriers, "the fixture has entry points that name components"
    for nid in carriers:
        assert g["nodes"][nid]["kind"] == "component"
        eps = g["nodes"][nid]["entry_points"]
        assert isinstance(eps, list)
        for ep in eps:
            assert set(ep) == {"kind", "trigger", "source", "activation"}
            assert ep["activation"] in ("self", "external")
    # each flat entry point that names a component carries its 0-based position within that component's
    # list (the viewer uses it to select the exact entry point from a search hit / System link)
    counts: dict[str, int] = {}
    for e in g["entry_points"]:
        comp = str(e.get("component") or "")
        if comp:
            assert e["index"] == counts.get(comp, 0)
            counts[comp] = counts.get(comp, 0) + 1
    # each tests[] row carries its targets resolved to real nodes (or id-as-name when unresolved),
    # and cites suites as {file, why} bare anchors
    assert g["tests"], "the fixture has a test-completeness table"
    for row in g["tests"]:
        assert row["targets"], "a tests row names at least one target element"
        for tgt in row["targets"]:
            assert set(tgt) == {"id", "name", "node"}
            assert tgt["node"] is None or tgt["node"] in g["nodes"]
        for ev in row["tests"]:
            assert set(ev) == {"file", "why"}


def test_classify_activation_reads_kind_signatures():
    """Self-starting kinds (timer/loop/boot/signal/queue consumer) -> 'self'; caller-driven kinds
    (route/CLI/callback/webhook) -> 'external'; unknown -> 'external' (safe default)."""
    for kind in ("Background loop", "Cron job", "Boot task", "Signal", "Queue consumer",
                 "Startup hook", "Scheduled sweep", "SIGTERM handler"):
        assert grammar.classify_activation(kind) == "self", kind
    for kind in ("HTTP route", "CLI command", "OAuth callback", "Webhook", "Exported fn", ""):
        assert grammar.classify_activation(kind) == "external", kind


def test_entry_point_activation_authored_wins_else_derived():
    """The authored `activation` overrides the heuristic; a blank value falls back to classify_activation
    over `kind` — so old maps (no field) still classify without a rebuild."""
    m = ProjectModel(title="Acts", goal="demo")
    m.components = [Component(id="C1", name="Svc", subsystem=None, purpose="p",
                             depends_on="", source=None, confidence="")]
    m.entry_points = [
        EntryPoint(kind="Background loop", trigger="every 60s", source="src/s.py:1", component="C1"),
        EntryPoint(kind="HTTP route", trigger="GET /x", source="src/s.py:2", component="C1"),
        # authored value overrides what the kind text would imply (both directions):
        EntryPoint(kind="Reconcile pass", trigger="on boot", source="src/s.py:3", component="C1",
                   activation="self"),
        EntryPoint(kind="Background sync", trigger="manual", source="src/s.py:4", component="C1",
                   activation="external"),
    ]
    g = model_to_graph(m)
    acts = [e["activation"] for e in g["entry_points"]]
    assert acts == ["self", "external", "self", "external"]
    # the per-component "Triggered by" list carries the same resolved value
    comp_eps = g["nodes"]["C1"]["entry_points"]
    assert isinstance(comp_eps, list)
    assert [e["activation"] for e in comp_eps] == acts


def test_tests_rows_resolve_targets_to_names_and_nodes():
    """Each tests[] row carries its `targets` resolved SERVER-SIDE to `{id, name, node}`: a defined
    element gets its name + a node id (the Tests tab makes it clickable to locate); an undefined id
    keeps its id as the name and `node=None` — no client-side id parsing, no guessed link."""
    from coyomap.model import EvidenceItem, TestRow, UseCase
    m = ProjectModel(title="Tiny")
    m.use_cases = [UseCase(id="UC1", name="Login"), UseCase(id="UC2", name="Browse")]
    m.tests = [TestRow(targets=["UC1", "UC9"], label="auth", tested="no",
                       tests=[EvidenceItem(file="tests/unit/", why="login suite")]),
               TestRow(targets=["UC2"], tested="yes")]
    g = model_to_graph(m)
    r0 = g["tests"][0]
    assert r0["label"] == "auth" and r0["tested"] == "no"
    assert r0["targets"][0] == {"id": "UC1", "name": "Login", "node": "UC1"}
    assert r0["targets"][1] == {"id": "UC9", "name": "UC9", "node": None}  # undefined → id as name, no node
    assert r0["tests"] == [{"file": "tests/unit/", "why": "login suite"}]  # bare anchor → clickable code link
    assert g["tests"][1]["targets"][0] == {"id": "UC2", "name": "Browse", "node": "UC2"}


def test_glossary_where_renders_as_link_and_reaches_graph():
    """The bare `source` anchor becomes a clickable basename link in the md view, and the glossary
    (with `source` preserved, "" for a null home) rides into the graph the Glossary tab reads."""
    m = ProjectModel(title="Tiny", goal="A tiny demo.")
    m.glossary = [GlossaryRow(term="Order", meaning="a customer order", source="src/order.py:12"),
                  GlossaryRow(term="Brand", meaning="the product itself", source=None)]
    md = model_to_markdown(m)
    assert "| **Order** | a customer order | [order.py](src/order.py:12) |" in md
    assert "| **Brand** | the product itself |  |" in md  # null home -> empty cell, no broken link
    g = model_to_graph(m)
    assert g["glossary"] == [{"term": "Order", "meaning": "a customer order", "source": "src/order.py:12"},
                             {"term": "Brand", "meaning": "the product itself", "source": ""}]


def test_glossary_aliases_and_no_autolink_ride_into_the_graph_only_when_set():
    """The viewer's term-linking reads `aliases` / `no_autolink` off the graph rows; a row without
    them serializes exactly as before, so old bundles and the golden fixtures stay byte-stable."""
    m = ProjectModel(title="Tiny", goal="A tiny demo.")
    m.glossary = [GlossaryRow(term="Upstream MCP", meaning="a mounted server",
                              aliases=["upstream"]),
                  GlossaryRow(term="Tool", meaning="one callable action", no_autolink=True),
                  GlossaryRow(term="Sandbox", meaning="the isolated box")]
    g = model_to_graph(m)
    assert g["glossary"] == [
        {"term": "Upstream MCP", "meaning": "a mounted server", "source": "",
         "aliases": ["upstream"]},
        {"term": "Tool", "meaning": "one callable action", "source": "", "no_autolink": True},
        {"term": "Sandbox", "meaning": "the isolated box", "source": ""},
    ]


def test_messaging_section_is_conditional_and_reaches_graph():
    """WS-A5: the md 'Messaging' section appears only when the catalog has rows, and the rows ride
    into the graph for the System-tab table."""
    m = ProjectModel(title="Tiny", goal="A tiny demo.")
    m.components = [Component(id="C1", name="Worker", purpose="works")]
    assert "Messaging — channels" not in model_to_markdown(m)
    m.messaging = [MessagingRow(name="JOB_QUEUE", kind="job-queue", broker="D1",
                                publishers=["C1"], consumers=["C1"], payload="E1",
                                source="src/queues.py:3")]
    md = model_to_markdown(m)
    assert "Messaging — channels" in md and "**JOB_QUEUE**" in md
    assert "[queues.py](src/queues.py:3)" in md
    g = model_to_graph(m)
    rows = cast("list[dict[str, object]]", g["messaging"])
    assert rows[0]["name"] == "JOB_QUEUE" and rows[0]["publishers"] == ["C1"]


def test_states_render_on_card_and_panes():
    """WS-A3: STATES line on the domain card (with the declaring anchor), 'States' row on the
    entity and component panes — panel text only, one shared renderer."""
    m = ProjectModel(title="Tiny", goal="A tiny demo.")
    m.components = [Component(id="C1", name="Manager", purpose="manages",
                              states=StateMachine(states=["idle", "live"],
                                                  transitions=[StateTransition(src="idle", dst="live",
                                                                               on="connect ok")],
                                                  source="src/mgr.py:7"))]
    m.entities = [Entity(id="E1", name="Sub", meaning="a sub", source="src/s.py:1",
                         fields=[EntityField(name="id", type="str")],
                         states=StateMachine(states=["active", "cancelled"],
                                             transitions=[StateTransition(src="active",
                                                                          dst="cancelled")],
                                             source="src/s.py:9"))]
    md = model_to_markdown(m)
    assert "STATES: active → cancelled — [s.py](src/s.py:9)" in md
    g = model_to_graph(m)
    e1 = cast("dict[str, dict[str, str]]", g["nodes"]["E1"])
    c1 = cast("dict[str, dict[str, str]]", g["nodes"]["C1"])
    assert e1["fields"]["States"] == "active → cancelled"
    assert c1["fields"]["States"] == "idle → live (on connect ok)"


def test_structured_store_renders_one_shared_form():
    """WS-A1 + Data view: the markdown domain-card parenthetical always uses the ONE shared `_store_str`
    renderer (`D1.guilds — collection; 30-day TTL`). In the interactive pane, storage shows EXACTLY
    once: a PERSISTED entity (store.dep set) carries the structured store on its node (the richer
    'Persisted in' row) and drops the plain 'Stored' text; a NOT-persisted store keeps the shared
    'Stored' text row (no structured row), so the two never duplicate."""
    m = ProjectModel(title="Tiny", goal="A tiny demo.")
    m.deps = [Dep(id="D1", name="MongoDB", kind="datastore", type="document db")]
    m.entities = [Entity(id="E1", name="Guild", meaning="a server", source="src/g.py:1",
                         fields=[EntityField(name="id", type="str")],
                         store=Store(dep="D1", container="guilds", mode="collection",
                                     notes="30-day TTL"))]
    md = model_to_markdown(m)
    assert "**E1 — Guild** *(D1.guilds — collection; 30-day TTL)*" in md
    e1 = cast("dict[str, Any]", model_to_graph(m)["nodes"]["E1"])
    assert "Stored" not in e1["fields"]                       # persisted → no plain text row (structured instead)
    assert e1["store"] == {"dep": "D1", "container": "guilds", "mode": "collection",
                           "notes": "30-day TTL"}
    # a NOT-persisted store (no dep) keeps the shared "Stored" text row, no structured "Persisted in"
    transient = Store(mode="transient", notes="derived at request time")
    m.entities[0].store = transient
    e1b = cast("dict[str, dict[str, str]]", model_to_graph(m)["nodes"]["E1"])
    assert e1b["fields"]["Stored"] == _store_str(transient)
    # notes-only degrades to the bare notes (the migrated-legacy look)
    m.entities[0].store = Store(notes="mdb: guilds")
    assert "**E1 — Guild** *(mdb: guilds)*" in model_to_markdown(m)
    # no store → no parens at all
    m.entities[0].store = None
    assert "**E1 — Guild**\n" in model_to_markdown(m)


def test_subsystem_tech_column_is_conditional_and_reaches_graph():
    """WS-A7: the subsystems `Tech` column appears only when some subsystem states one, and the
    label lands on the subsystem node's info-pane fields (subdomains deliberately not mirrored)."""
    m = ProjectModel(title="Tiny", goal="A tiny demo.")
    m.subsystems = [Group(id="S1", name="Core", purpose="the core")]
    m.components = [Component(id="C1", name="Worker", purpose="works", subsystem="S1")]
    md = model_to_markdown(m)
    assert "| Tech |" not in md                                  # no tech anywhere → no column
    m.subsystems[0].tech = "Python/FastAPI"
    m.subsystems[0].tech_source = "pyproject.toml:1"
    md = model_to_markdown(m)
    assert "| Tech |" in md
    assert "Python/FastAPI ([pyproject.toml](pyproject.toml:1))" in md
    g = model_to_graph(m)
    s1 = cast("dict[str, dict[str, str]]", g["nodes"]["S1"])
    assert s1["fields"]["Tech"] == "Python/FastAPI"


def test_cadence_column_is_conditional_and_reaches_graph():
    """WS-A2: the T4 `Cadence` column appears ONLY when some row states one (committed md of maps
    without cadences stays byte-identical), and cadence + canonical kind ride into the graph's flat
    entry points for the System tab."""
    m = ProjectModel(title="Tiny", goal="A tiny demo.")
    m.components = [Component(id="C1", name="Worker", purpose="works")]
    m.entry_points = [EntryPoint(kind="poller", trigger="poll twitch", source="src/p.py:1",
                                 component="C1")]
    md = model_to_markdown(m)
    assert "Cadence" not in md                                   # no cadence anywhere → no column
    m.entry_points[0].cadence = "every 30s"
    m.entry_points[0].cadence_source = "src/beat.py:12"
    md = model_to_markdown(m)
    assert "| Cadence |" in md
    assert "every 30s ([beat.py](src/beat.py:12))" in md         # cadence + its declaring line
    g = model_to_graph(m)
    ep = cast("list[dict[str, object]]", g["entry_points"])[0]
    assert ep["cadence"] == "every 30s"
    assert ep["canonical_kind"] == "poller"


def test_step_where_renders_in_md_and_reaches_graph():
    """A flow step's own `where` (THE location) renders as an inline ` @ ` code link in the T6 md
    view — between the phrase and the note — and rides into the graph's flow steps for the viewer."""
    m = ProjectModel(title="Tiny", goal="A tiny demo.")
    m.use_cases = [UseCase(id="UC1", name="View")]
    m.components = [Component(id="C1", name="Viewer", purpose="shows")]
    m.entities = [Entity(id="E1", name="Order", source="src/e.py:1",
                         fields=[EntityField(name="id", type="str")])]
    m.flows = [Flow(uc="UC1", title="View",
                    steps=[FlowStep(n=1, src="C1", dst="E1", phrase="reads the order",
                                    where="src/v.py:5", note="cached")])]
    md = model_to_markdown(m)
    assert "1. C1 → E1 : reads the order @ [v.py](src/v.py:5) · cached" in md
    g = model_to_graph(m)
    steps = cast("list[dict[str, object]]", g["flows"][0]["steps"])
    assert steps[0]["where"] == "src/v.py:5"


def make_subflow_model() -> ProjectModel:
    """Two flows sharing one sub-flow: UC1 = actor step + reference; UC2 = reference only."""
    m = ProjectModel(title="Tiny", goal="A tiny demo.")
    m.use_cases = [UseCase(id="UC1", name="View"), UseCase(id="UC2", name="Audit")]
    m.components = [Component(id="C1", name="Viewer", purpose="shows"),
                    Component(id="C2", name="Store", purpose="keeps")]
    m.subflows = [SubFlow(id="SF1", name="Persist the thing",
                          steps=[FlowStep(n=1, src="C1", dst="C2", phrase="hands off",
                                          where="src/a.py:3"),
                                 FlowStep(n=2, src="C2", dst="C1", phrase="confirms",
                                          where="src/b.py:7")])]
    m.flows = [Flow(uc="UC1", title="View",
                    steps=[FlowStep(n=1, src="Andy", dst="C1", phrase="opens"),
                           FlowStep(n=2, src="C1", dst="C2", subflow="SF1"),
                           FlowStep(n=3, src="C1", dst="C2", phrase="renders the result",
                                    where="src/c.py:9")]),
               Flow(uc="UC2", title="Audit",
                    steps=[FlowStep(n=1, src="C1", dst="C2", subflow="SF1")])]
    return m


def test_subflow_renders_in_md_and_reaches_graph():
    m = make_subflow_model()
    md = model_to_markdown(m)
    assert "## T6b — Sub-flows" in md and "**SF1 — Persist the thing**" in md
    assert "2. C1 → C2 : ⟨runs SF1 — Persist the thing⟩" in md  # the reference step, named inline
    g = model_to_graph(m)
    sf = cast("list[dict[str, object]]", g["subflows"])[0]
    assert sf["id"] == "SF1"
    assert cast("list[dict[str, object]]", sf["steps"])[0]["where"] == "src/a.py:3"


def test_a_reference_step_keeps_its_own_slot_and_names_the_walk_it_runs():
    """The reference stays ONE narrative entry — never replaced by the walk's insides — so entry[i] is
    still message[i] and the step player's counter is the walk's own length. The entry names the walk it
    runs, which is what the panel, the map's box and the sequence column all read."""
    g = model_to_graph(make_subflow_model())
    narr = flow_narrative(g, cast("dict", g["flows"][0]))
    assert [(x["sf"], x["n"]) for x in narr] == [(None, 1), ("SF1", 2), (None, 3)]
    assert narr[1]["sfName"] == "Persist the thing" and narr[1]["sfSteps"] == 2
    # (The sequence rendering that stood beside the map is gone; the map is the one picture of a walk.)


def make_flow_map_model() -> ProjectModel:
    """One flow touching every box kind the map draws — an actor, two components grouped in a
    subsystem, an entity and an external dep — plus a pair used by two steps."""
    m = ProjectModel(title="Tiny", goal="A tiny demo.")
    m.use_cases = [UseCase(id="UC1", name="View")]
    m.subsystems = [Group(id="S1", name="Reading room", purpose="serves readers")]
    m.components = [Component(id="C1", name="Viewer", purpose="shows", subsystem="S1"),
                    Component(id="C2", name="Store", purpose="keeps", subsystem="S1")]
    m.deps = [Dep(id="D1", name="Postgres", kind="datastore", type="db", used_for="rows")]
    m.entities = [Entity(id="E1", name="Order", meaning="a customer order", source="src/o.py:1")]
    m.flows = [Flow(uc="UC1", title="View",
                    steps=[FlowStep(n=1, src="Andy", dst="C1", phrase="opens the page"),
                           FlowStep(n=2, src="C1", dst="C2", phrase="asks for the order",
                                    where="src/a.py:3"),
                           FlowStep(n=3, src="C2", dst="E1", phrase="reads the Order",
                                    where="src/b.py:5"),
                           FlowStep(n=4, src="C2", dst="D1", phrase="queries the table",
                                    where="src/b.py:9"),
                           FlowStep(n=5, src="C1", dst="C2", phrase="asks again",
                                    where="src/a.py:11")])]
    return m


def test_flow_map_draws_one_empty_slot_per_element():
    """The leaf-only map: a box per touched element and no subsystem FRAME (the containers are what it
    drops).

    EVERY BOX IS A SLOT. This generator writes the SHAPE of the drawing and nothing about what a box
    says; the viewer builds the box (`itemBoxHtml`), measures it, and swaps it in. A second copy of
    that builder here, in Python, is the drift the item box exists to end. So the label carries no
    name, no colour and no shape of its own — only which element, and which variant this picture
    wants."""
    g = model_to_graph(make_flow_map_model())
    mm = gen_flow_map_mermaid(g, cast("dict", g["flows"][0]))
    # NO NODE PADDING ON THIS MAP: every box carries its own, and the engine's default wrapped 30
    # units of nothing round each box's sides — which is where the arrows stopped, short of the box.
    assert mm.startswith("%%{init: {'flowchart': {'padding': 2}}}%%\nflowchart LR")
    assert "subgraph" not in mm                                   # leaf-only: no container frames
    assert '  C1["<span class=cyslot data-k=component data-v=tight data-id=C1></span>"]:::cy-C1' in mm
    assert "class C1 itembox" in mm
    assert "Reading room" not in mm                               # its group name stays off the box
    assert "Viewer" not in mm and "Order" not in mm               # NO name in the source at all
    assert "data-k=entity data-v=tight data-id=E1" in mm \
        and "data-k=dep data-v=tight data-id=D1" in mm
    # The PERSON keeps the stick figure it has always had here, so the actor is still the biggest mark
    # on the drawing — `figure` is the variant that draws it.
    assert 'FA0["<span class=cyslot data-k=role data-v=figure data-id=Andy></span>"]' in mm
    # ONE classDef, and it makes the node itself invisible: the box IS the label now.
    assert mm.count("classDef") == 1 and "classDef itembox fill:none,stroke:none;" in mm


def test_flow_map_arrows_come_from_the_steps_and_carry_their_numbers():
    """One arrow per ordered pair, labelled with the step positions riding it — the SAME 1-based
    numbers the sequence diagram puts on its messages, so a number carries between the renderings."""
    g = model_to_graph(make_flow_map_model())
    mm = gen_flow_map_mermaid(g, cast("dict", g["flows"][0]))
    arrows = [ln.strip() for ln in mm.splitlines() if "-->" in ln]
    assert arrows == ['FA0 -->|"1"| C1', 'C1 -->|"2, 5"| C2', 'C2 -->|"3"| E1', 'C2 -->|"4"| D1']
    # …and one arrow carries BOTH steps, because a pair used twice is one line with two numbers.


def test_flow_map_ignores_the_backbone_edge_list():
    """The map re-renders THIS FLOW'S steps, never the backbone edges — so a relationship the
    scenario does not exercise cannot appear on it."""
    m = make_flow_map_model()
    m.edges = [Edge(src="C1", verb="calls", dst="D1", why="unrelated to this flow",
                    where="src/a.py:99")]
    g = model_to_graph(m)
    mm = gen_flow_map_mermaid(g, cast("dict", g["flows"][0]))
    arrows = [ln.strip() for ln in mm.splitlines() if "-->" in ln]
    assert 'C1 -->|"2, 5"| C2' in arrows                            # the pair the steps do exercise
    assert not [a for a in arrows if a.startswith("C1 -->") and a.endswith("D1")]  # the edge is not drawn


def test_flow_map_draws_a_service_actor_as_a_service():
    """human vs service is the method's own distinction — an autonomous initiator must not be drawn as
    a person on one rendering and a service on the other. The map uses the same hexagon the Context
    view and the sequence lifelines use."""
    m = make_flow_map_model()
    m.roles = [Role(id="R1", name="Andy", kind="service", wants="to sync")]
    g = model_to_graph(m)
    mm = gen_flow_map_mermaid(g, cast("dict", g["flows"][0]))
    # THE DRAWING NO LONGER DECIDES THIS, and that is the point: the slot names the ROLE and the
    # viewer reads its kind off the map to pick the mark (`itemSpecRole` -> `itemGlyphSvg`), so one
    # answer serves the map, the Interfaces picture and every card. What must survive here is that
    # the actor still reaches the drawing as an actor, under its roster alias.
    assert 'FA0["<span class=cyslot data-k=role data-v=figure data-id=Andy></span>"]' in mm
    assert flow_actors(g, cast("dict", g["flows"][0]))[0]["kind"] == "service"


def test_flow_map_and_flow_actors_agree_on_every_alias():
    """The frontend crosses between an actor's `FAn` box and its roster entry, so a drawing that
    numbers its actors differently from `flow_actors` would resolve one participant as another. The
    hard case is a DANGLING element id (validate blocks it; serve still renders drafts): it must count
    as an element on BOTH sides, never consume an alias on one of them."""
    m = make_flow_map_model()
    m.flows[0].steps.insert(0, FlowStep(n=6, src="C99", dst="C1", phrase="a dangling id",
                                        where="src/x.py:1"))
    g = model_to_graph(m)
    mm = gen_flow_map_mermaid(g, cast("dict", g["flows"][0]))
    roster = flow_actors(g, cast("dict", g["flows"][0]))
    assert [a["name"] for a in roster] == ["Andy"] and roster[0]["aid"] == "FA0"
    assert "data-k=role data-v=figure data-id=Andy" in mm              # the roster's alias, on the map
    assert "data-k=component data-v=tight data-id=C99" in mm           # the dangling id stays an element
    assert "FA1" not in mm


def test_actor_facts_survive_a_name_the_sanitisers_rewrite():
    """A role name is AUTHORED text; the diagrams draw a sanitised form of it. Every lookup joining a
    drawn actor back to its Roles entry must resolve whichever form its caller holds — a flow step's
    endpoint is authored, a Happy Path actor arrives sanitised. Keying only one of the two lost the
    role's `kind`, and an empty kind draws a `service` actor as a PERSON: it broke the flow view when
    the index was display-keyed, and the Happy Path when it was authored-keyed. Both are asserted here
    so neither direction can regress alone."""
    m = make_flow_map_model()
    m.roles = [Role(id="R1", name="Ops#1 <sync>", kind="service", wants="to sync")]
    m.use_cases = [UseCase(id="UC1", name="View", actors=["Ops#1 <sync>"])]
    m.flows[0].steps[0] = FlowStep(n=1, src="Ops#1 <sync>", dst="C1", phrase="opens the page")
    m.happy_path = [HappyStep(id="HP1", uc="UC1")]
    g = model_to_graph(m)
    roster = flow_actors(g, cast("dict", g["flows"][0]))
    assert roster[0]["kind"] == "service" and roster[0]["wants"] == "to sync"   # authored token
    assert hp_actors(g)[0]["kind"] == "service"                                 # sanitised token
    mm = gen_flow_map_mermaid(g, cast("dict", g["flows"][0]))
    assert "data-k=role data-v=figure data-id=Ops%231%20%3Csync%3E" in mm   # URL-encoded: a name may
    #                                                        hold anything, and the slot is unquoted
    # The frontend joins a drawn box back to this roster BY ALIAS, so the alias must agree — the raw
    # name never has to survive the round trip through the sanitised label.
    assert roster[0]["aid"] == "FA0" and "FA1" not in mm
    assert roster[0]["name"] == "Ops#1 <sync>"        # the roster stays in the authored text space


def test_two_roles_that_differ_only_in_stripped_characters_stay_distinct():
    """Roles are looked up by name in two text spaces, so two names that COLLAPSE onto each other
    (`Night Shift` / `Night  Shift` — the sanitiser folds the double space) must not resolve to one
    another, and the answer must not depend on which was written first in the Roles table."""
    def facts(order: list[Role]) -> tuple[str, str]:
        m = make_flow_map_model()
        m.roles = order
        m.use_cases = [UseCase(id="UC1", name="View", actors=["Night Shift"])]
        m.flows[0].steps[0] = FlowStep(n=1, src="Night Shift", dst="C1", phrase="opens the page")
        g = model_to_graph(m)
        return (flow_actors(g, cast("dict", g["flows"][0]))[0]["kind"],
                flow_actors(g, cast("dict", g["flows"][0]))[0]["wants"])

    plain = Role(id="R1", name="Night Shift", kind="human", wants="to watch")
    doubled = Role(id="R2", name="Night  Shift", kind="service", wants="to poll")
    assert facts([plain, doubled]) == ("human", "to watch")   # the authored name wins…
    assert facts([doubled, plain]) == ("human", "to watch")   # …in either table order


def make_chipped_subflow_model() -> ProjectModel:
    """A shared sub-use case that touches a person, a door and a record — the three things a chip names — plus a
    component, which is deliberately NOT chipped."""
    m = make_subflow_model()
    m.roles = [Role(id="R1", name="Andy", kind="person", wants="to view")]
    m.interfaces = [Interface(id="I1", name="Public site", side="ours", facing="user",
                              kind="screen", source="src/web.py:1")]
    m.entities = [Entity(id="E1", name="Order", store=Store(notes="orders"), meaning="an order",
                         source="src/o.py:1", fields=[EntityField(name="id", type="str")])]
    m.subflows[0].steps += [FlowStep(n=3, src="C2", dst="E1", phrase="keeps it", where="src/a.py:9"),
                            FlowStep(n=4, src="C2", dst="I1", phrase="shows it", where="src/a.py:11"),
                            FlowStep(n=5, src="Andy", dst="C2", phrase="confirms", where="src/a.py:13")]
    return m


def test_a_use_case_walk_is_its_own_steps_not_the_shared_walks_it_runs():
    """A use case that runs a shared sub-use case appeared to DO that walk's work: its numbered steps included
    steps belonging to every other use case that runs the same walk. Measured on the live maps before
    this changed, a use case walk was 16 steps stored and 27 shown.

    The reference is one step now, in every rendering — so a walk's length is its own."""
    g = model_to_graph(make_subflow_model())
    narr = flow_narrative(g, cast("dict", g["flows"][0]))
    assert [n["verb"] for n in narr] == ["opens", "run", "renders the result"]
    assert narr[1]["sf"] == "SF1" and narr[1]["sfSteps"] == 2   # the walk it runs, and how big it is


def test_both_renderings_number_the_same_list():
    """The map and the Sequence view are two pictures of ONE walk, and the toggle between them keeps the
    reader's place. If one collapsed a shared sub-use case and the other did not, the same number would name two
    different moments and one picture would have steps the other does not."""
    g = model_to_graph(make_subflow_model())
    flow = cast("dict", g["flows"][0])
    mapped = [ln for ln in gen_flow_map_mermaid(g, flow).splitlines() if "-->" in ln]
    assert len(mapped) == len(flow_narrative(g, flow)) == 3
    assert mapped == ['  FA0 -->|"1"| C1', '  C1 -->|"2"| SF1', '  C1 -->|"3"| C2']


def test_a_shared_walk_is_one_dashed_box_with_nothing_drawn_out_of_it():
    """No step in the model hands control back from a shared sub-use case — the walk simply continues, and its
    next step draws itself. An arrow out of the box would have to be invented, and an invented arrow
    carries no step, no direction and no code link."""
    g = model_to_graph(make_subflow_model())
    mm = gen_flow_map_mermaid(g, cast("dict", g["flows"][0]))
    # A SHARED SUB-USE CASE IS A FULL BOX — the one box a reader cannot see inside, so it wears its people,
    # doors and records as chips or collapsing it buries the product's edge.
    assert 'SF1["<span class=cyslot data-k=subflow data-v=full data-id=SF1></span>"]' in mm
    assert "class SF1 itembox" in mm
    assert [ln for ln in mm.splitlines() if "-->" in ln and ln.strip().startswith("SF1 ")] == []


def test_the_box_says_how_big_the_walk_is_and_wears_its_people_doors_and_records():
    """Collapsing must not bury the product's edge or its saved data — the design philosophy's own rule.
    A COMPONENT is never a chip: a shared sub-use case is made of components, so every box would carry the same
    crowd and the two things worth seeing would be lost in it."""
    g = model_to_graph(make_chipped_subflow_model())
    chips = subflow_chips(g)["SF1"]
    assert [(c["kind"], c["name"]) for c in chips] == [
        ("actor", "Andy"), ("interface", "Public site"), ("entity", "Order")]  # people, doors, records
    # The chips reach the viewer through the BUNDLE, keyed by walk, not through the drawing's source:
    # the source carries a slot and nothing else. `subflow_chips` above is the one join, and the box
    # that wears them is `itemBoxHtml`.
    assert [c["name"] for c in chips] == ["Andy", "Public site", "Order"]
    assert "Store" not in [c["name"] for c in chips]          # C2 is a component, not a chip
    mm = gen_flow_map_mermaid(g, cast("dict", g["flows"][0]))
    assert "cychip" not in mm and "Public site" not in mm


def test_a_shared_walk_is_a_walk_in_its_own_right():
    """Clicking the box opens the walk itself, so it needs the same four things a use case walk has. It
    is stored in the same shape, so the same four generators produce them — which is what keeps the two
    kinds of screen from drifting apart."""
    g = model_to_graph(make_subflow_model())
    assert sorted(flow_maps(g)) == ["SF1", "UC1", "UC2"]
    assert sorted(flow_narratives(g)) == ["SF1", "UC1", "UC2"]
    own = flow_narratives(g)["SF1"]
    assert [n["verb"] for n in own] == ["hands off", "confirms"]   # numbered from 1, and its own
    assert all(n["sf"] is None for n in own)


def test_a_degraded_reference_stays_a_bare_step():
    """An unresolved reference or an empty shared sub-use case (validate blocks both, serve renders drafts) must
    not vanish. It stays one plain step naming what it tried to run."""
    m = make_subflow_model()
    m.flows[0].steps[1] = FlowStep(n=2, src="C1", dst="C2", subflow="SF404")
    g = model_to_graph(m)
    narr = flow_narrative(g, cast("dict", g["flows"][0]))
    assert len(narr) == 3 and narr[1]["verb"] == "run SF404" and narr[1]["sf"] is None


def test_flow_actors_index_the_walk_s_own_list():
    g = model_to_graph(make_subflow_model())
    actors = flow_actors(g, cast("dict", g["flows"][0]))
    assert len(actors) == 1 and actors[0]["name"] == "Andy"
    assert actors[0]["stepIdx"] == [0]                  # indexes the same 3-entry own-steps list


def test_graph_line_parses_colon_range_and_legacy_hash_anchors():
    """`model_to_graph`'s node.line (build_graph._line_of) must resolve the START line of every
    anchor form: canonical single-line, canonical range, and the retired `#Lnnn`/`#Lnnn-Lmmm`
    (an un-migrated map's anchors must still open on click, just not be re-emitted)."""
    m = ProjectModel(title="T", goal="G")
    m.entities = [
        Entity(id="E1", name="A", source="src/a.py:12",
              fields=[EntityField(name="id", type="str")]),
        Entity(id="E2", name="B", source="src/b.py:12-18",
              fields=[EntityField(name="id", type="str")]),
        Entity(id="E3", name="C", source="src/c.py#L12-L18",
              fields=[EntityField(name="id", type="str")]),
    ]
    g = model_to_graph(m)
    assert g["nodes"]["E1"]["line"] == 12 and g["nodes"]["E1"]["file"] == "src/a.py:12"
    assert g["nodes"]["E2"]["line"] == 12 and g["nodes"]["E2"]["file"] == "src/b.py:12-18"
    assert g["nodes"]["E3"]["line"] == 12 and g["nodes"]["E3"]["file"] == "src/c.py#L12-L18"


def test_golden_model_audit_is_deterministic_and_deduped():
    """The model audit on the real map: stable across runs, worklist deduped by claim, every edge
    claim self-describing enough to carry an anchor or a detail."""
    m = make_fixture_model()
    f1 = [(f.check, f.severity, f.location) for f in audit_model.audit_model(m)]
    f2 = [(f.check, f.severity, f.location) for f in audit_model.audit_model(m)]
    assert f1 == f2
    wl = audit_model.l2_worklist_model(m)
    claims = [w.claim for w in wl]
    assert wl and len(claims) == len(set(claims)), "worklist must be deduped by claim"


def test_golden_v2_detail_describes_components_by_entry_points():
    """The F2 fix: an edge claim's detail lists the FROM component's member entry points, and a dep
    endpoint reads as an external system, never a code file."""
    m = make_fixture_model()
    wl = audit_model.l2_worklist_model(m)
    assert any("entry points:" in (w.detail or "") for w in wl)
    dep_details = [w.detail for w in wl
                   if w.detail and "To: D" in w.detail]
    assert dep_details and all("external system" in d for d in dep_details if "To: D" in d)


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


# ── the grounding section, which shipped with no test at all ─────────────────────────────────────

def make_map_with_grounding(**g: object):
    from coyomap.model import Grounding, ProjectModel
    m = ProjectModel(title="T", goal="g")
    m.grounding = Grounding(**g)  # type: ignore[arg-type]
    return m


def test_the_grounding_record_is_rendered():
    """It travelled with the map as JSON and appeared in NO view, so the one number a reader needs
    in order to judge every other number was invisible in the markdown."""
    from coyomap.views import model_to_markdown
    md = model_to_markdown(make_map_with_grounding(
        claims_total=446, claims_challenged=446, claims_confirmed=428,
        claims_refuted=7, claims_unverifiable=11, live_claims_digest="abc"))
    assert "## Grounding" in md
    assert "446 of 446 claim(s) challenged" in md and "428 confirmed" in md


def test_a_map_without_grounding_renders_the_section_not_at_all():
    """Byte-identity for every map that has no record — the property other optional sections keep."""
    from coyomap.model import ProjectModel
    from coyomap.views import model_to_markdown
    assert "## Grounding" not in model_to_markdown(ProjectModel(title="T", goal="g"))


def test_partial_coverage_is_called_out_in_the_view():
    from coyomap.views import model_to_markdown
    md = model_to_markdown(make_map_with_grounding(
        claims_total=100, claims_challenged=40, claims_confirmed=40, live_claims_digest="abc"))
    assert "Coverage is PARTIAL" in md and "60 claim(s) were never challenged" in md


def test_a_record_with_no_digest_says_it_cannot_be_confirmed():
    """The record can be right and unverifiable at once; a reader must be able to tell."""
    from coyomap.views import model_to_markdown
    md = model_to_markdown(make_map_with_grounding(
        claims_total=10, claims_challenged=10, claims_confirmed=10))
    assert "No `live_claims_digest`" in md


def test_graph_roles_carry_relations_only_when_authored():
    """The actor page reads `relations` off the graph's roles; a map without them must serialize
    exactly as before (absence, not an empty list — the frontend treats absence as [])."""
    m = make_fixture_model()
    g = model_to_graph(m)
    assert all("relations" not in r for r in cast("list[dict[str, Any]]", g["roles"]))
    m.roles[0].relations = [RoleRelation(kind="becomes", role=m.roles[-1].id,
                                         at=m.use_cases[0].id),
                            RoleRelation(kind="includes", role=m.roles[-1].id)]
    g2 = model_to_graph(m)
    roles = cast("list[dict[str, Any]]", g2["roles"])
    assert roles[0]["relations"] == [
        {"kind": "becomes", "role": m.roles[-1].id, "at": m.use_cases[0].id},
        {"kind": "includes", "role": m.roles[-1].id},   # includes: no `at` key at all
    ]
    assert all("relations" not in r for r in roles[1:])


def test_the_grounding_ledger_is_rendered_one_row_per_wave():
    """After an update the counts describe the current pin; the ledger says how much a build's
    skeptics read and how much a later wave re-read, which is what a reader judges the counts by."""
    from coyomap.model import GroundingWave
    from coyomap.views import model_to_markdown
    md = model_to_markdown(make_map_with_grounding(
        claims_total=48, claims_challenged=48, claims_confirmed=47, claims_refuted=1,
        live_claims_digest="abc", history=[
            GroundingWave(kind="build", at="aaaaaaa", date="2026-09-01", challenged=40, confirmed=40, skeptics=6),
            GroundingWave(kind="update", at="aaaaaaa-bbbbbbb", date="2026-09-17", challenged=9, confirmed=8,
                          refuted=1, carried=31, retired=4, changed=3, touched=4, rippled=2, skeptics=2)]))
    assert "one row per wave of skeptics" in md
    assert "| build aaaaaaa | 2026-09-01 | 40 | 40 | 0 | 0 | 0 | 0 | the whole map | 6 |" in md, md
    assert "| update aaaaaaa-bbbbbbb | 2026-09-17 | 9 | 8 | 1 | 0 | 31 | 4 | 3 changed · 4 touched · 2 reached | 2 |" in md, md


def test_the_markdown_view_titles_the_description_and_puts_its_sections_two_levels_down() -> None:
    """The description's `##` sections sit under the document's own `## Product description`, so they
    are written as `####`; a legacy plain-paragraph text is copied as it is."""
    m = ProjectModel(title="Demo", goal="Opening.\n\n## Who uses it\n\nA shopper.\n\n### Staff\n\n- A clerk.\n\n##")
    md = model_to_markdown(m)
    assert ("## Product description\n\nOpening.\n\n#### Who uses it\n\nA shopper.\n\n##### Staff\n\n"
            "- A clerk.\n\n##\n") in md   # a bare `##` is not a heading, so it is not moved
    assert "T0" not in md
    legacy = model_to_markdown(ProjectModel(title="Demo", goal="One.\n\nTwo."))
    assert "## Product description\n\nOne.\n\nTwo.\n" in legacy
