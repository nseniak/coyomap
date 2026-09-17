#!/usr/bin/env python3
"""The viewer's graph data model + the change-impact report parser.

The graph (`GraphDict`) is what `gen_viewer.build_view_bundle` turns into the viewer's data; it is
produced by `coyomap.views.model_to_graph`, straight from the model.
the change-impact REPORT, a markdown artifact distinct from the map itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

# Shared schema grammar lives in tools/coyomap/grammar.py (one grammar; the table helpers serve
# the change-impact report parser below).
from coyomap import grammar
from coyomap.grammar import ID_TOKEN, is_separator_row, iter_pipe_runs, split_cells

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")  # markdown link -> href

# Synthetic id for the default subsystem injected when a map has components but no subsystem of its
# own (see _ensure_default_subsystem). "S0" is a valid subsystem id (prefix "S") and can't collide,
# since the case only fires when no subsystem node exists.
DEFAULT_SUBSYSTEM_ID = "S0"


@dataclass
class Node:
    id: str
    kind: str
    name: str
    file: str | None
    line: int | None
    fields: dict[str, str]
    parent: str | None = None  # the one parent S-id (grouping); None = top-level / ungrouped
    attrs: list[dict[str, str]] = field(default_factory=list)  # entity attributes (T5 cards only)
    dep_kind: str | None = None  # T2 deps only: the Context Kind (datastore/messaging/service/…); see classify_dep
    files: list[str] = field(default_factory=list)  # every repo-relative file this element covers,
                                  # bare (no line anchor), the canonical `source` file first. A
                                  # component's owned files; a group's = union of its members' files;
                                  # an entity's single source file. Drives the code-viewer file
                                  # switcher + the tree footprint highlight.
    entry_points: list[dict[str, str]] = field(default_factory=list)  # components only: the T4 entry
                                  # points that name this component ({kind, trigger, source}) — the
                                  # "Triggered by" list in the info pane
    runs_in: list[str] = field(default_factory=list)  # components only: the deployment unit name(s)
                                  # whose process runs this component — the Deployment view's `runs`
                                  # edges (process → this component's subsystem) derive from it
    actors: list[str] = field(default_factory=list)  # use cases only: the driving role NAMES, primary
                                  # first — the structured half of the human `Actor` field. A use case
                                  # may list several INTERCHANGEABLE initiators (either can start it),
                                  # and only this list lets a view tell "two actors" from one actor
                                  # whose name happens to contain a comma.
    roles: list[str] = field(default_factory=list)  # deps only: the role SET derived from the dep's
                                  # incoming C→D edge verbs (grammar.dep_roles) — 'datastore' /
                                  # 'messaging' / 'service' / 'security'. A dual-role dep (Redis as bus +
                                  # store) → ['datastore', 'messaging']; no C→D edge → [] (no role tag).
                                  # Purely derived (no stored model field), so it can't drift from edges.
    store: dict[str, str] | None = None  # entities only: the structured store {dep, container, mode,
                                  # notes} (Entity.store), exposed so the info pane can render a
                                  # "Persisted in" row (dep chip + container) without re-parsing the
                                  # human "Stored" field string. None = not persisted / not stated.
    states_count: int = 0         # entities/components only: how many states its lifecycle declares
                                  # (0 = none). The `States` field holds the human TEXT; only the count
                                  # is countable, and the Domain diagram's lifecycle marker needs it.
    states_lines: list[str] = field(default_factory=list)  # the lifecycle's transitions, ONE per entry
                                  # (`a → b (on x)`) — the info pane lists them line by line, since a
                                  # real machine's transitions joined into one string read as a wall.


@dataclass
class Edge:
    src: str
    verb: str
    dst: str
    why: str | None
    where: str | None
    kind: str | None = None       # domain-relation kind (association/composition/…); None = plain edge
    src_card: str | None = None   # cardinality at the source end (domain relations only)
    dst_card: str | None = None   # cardinality at the destination end
    how: str | None = None        # plain-text note: how a field-less domain relation is implemented
    fk_fields: list[str] = field(default_factory=list)  # REAL field(s) backing the relation (drive the
                                  # arrow label) — more than one is a composite key, e.g. (user_id, page_id)
    fk_side: str | None = None    # 'src' = field on the tail (forward), 'dst' = FK on the head (reverse)
    keyed_by: list[str] = field(default_factory=list)  # storage KEY name(s) identifying the target
                                  # (a lookup/partition key the store imposes, not a row field) — drawn
                                  # on the arrow with the «key» marker when no fk_fields back the link


@dataclass
class HappyStep:
    """A Happy Path step = a use-case occurrence: a position (`id`) in the ordered walk that realizes
    a use case (`uc`). It carries no STORY/Touches — those live in the use case's T6 flow; drilling the
    step opens that flow. `why` is the optional prerequisite that fixes this step's position."""
    id: str
    uc: str | None = None  # the use case this step realizes; the viewer labels the step with its name
    why: str = ""          # optional `why:` line — the prerequisite that places this step in the walk


class TestTarget(TypedDict):
    id: str
    name: str
    node: str | None       # the id when it is a drawn diagram node (clickable to locate), else None


class TestRowView(TypedDict):
    targets: list[TestTarget]
    label: str
    tested: str
    tests: list[dict[str, str]]   # exercising suites: {file (bare anchor), why}
    gap: str
    confidence: str


class GraphDict(TypedDict):
    commit: str | None
    committed: str | None  # commit date of the pin (None for older maps without the field)
    built: str | None      # build timestamp (YYYY-MM-DD HH:MM); shown in the header meta line
    format: str | None     # schema/format tag (e.g. "coyomap-map"); shown in the header meta line
    title: str | None
    goal: str | None
    nodes: dict[str, dict[str, object]]
    edges: list[dict[str, object]]
    happy_path: list[dict[str, object]]
    flows: list[dict[str, object]]  # T6 use-case flows (one per use case): the ordered inside view
    subflows: list[dict[str, object]]  # T6b named sub-flows: {id, name, steps} — shared step
                                       # sequences a flow step references via its `subflow` field
    #: Which record HOLDS which (`model.record_parents`): child id -> the ids that contain it. The
    #: browser walks it so a record only ever reached THROUGH its holder still answers "in use
    #: cases" — the panel said "No traced use case reaches it" on records `validate` counts as
    #: storied, which is the screen and the check disagreeing about one record.
    record_parents: dict[str, list[str]]
    roles: list[dict[str, object]]  # id/name/wants/kind/audience strings, plus `relations`
                                    # (list of {kind, role, at?}) only when the map authors them
    glossary: list[dict[str, object]]  # ubiquitous-language terms: {term, meaning, source, aliases?,
                                    # no_autolink?} (source = bare `path:line`/`path/` anchor, or ""
                                    # when the term has no code home; aliases/no_autolink only when set)
    # ── reference collections shown on the System / Tests tabs (rows the diagram doesn't hold) ──
    run_commands: list[dict[str, str]]      # T3: {action, command, source}
    entry_points: list[dict[str, object]]   # T4: {kind, trigger, source, component, index} (component = owning
                                            # C id; index = position within that component's list, for pane select)
    # ── capability overlay (plan/60-capabilities) ──
    capability_touch: dict[str, list[str]]      # element id -> the capability ids whose flows reach
                                                # it. Absent = no capability reaches it (untraced, or
                                                # touched by no flow) — the overlay dims those.
    completeness: dict[str, int]                # the four-state counts (traced / untraced / claimed /
                                                # off-spine-in-core) shown on the System tab
    # ── T7, the decision layer (views._build_rules_view) ──
    # {blocks:[{id,name,purpose,parent}], rules:[{id,statement,block,access,confidence,
    #  sites:[{where,why,declared,components:[{id,name}]}], steps:[{uc,ucName,container,n,strength,
    #  phrase}], entities:[{id,name}], swept, unverified}], byComponent:{C-id:[BR…]},
    #  byStep:{"uc:container:n":[BR…]}}. EVERY field under a rule except statement/block/access/
    #  confidence/sites is DERIVED server-side by the one Python implementation — the frontend must
    #  never re-derive an owner or a step link from `sites`.
    rules_view: dict[str, object]
    non_entity_types: list[dict[str, str]]  # deliberately-unmodelled types: {name, source, why}
    deployment: list[dict[str, object]]     # {unit, runs_on, exposed_as, config_source, variants: [{env, source}…]}
    environments: list[str]                 # declared deployment-variant names (compose profiles / stages); [] = none
    messaging: list[dict[str, object]]      # async catalog: {name, kind, broker, publishers, consumers,
                                            # payload, source} — rendered as a System-tab table
    observability: list[dict[str, str]]     # {signal, where_emitted, where_viewed, alerts}
    security: list[dict[str, str]]          # {surface, who, source, risk}
    config: list[dict[str, str]]            # {key, purpose, default, per_env}
    # Store-centric Data view (viewer.js renderData): {stores:[{dep,name,kind,roles,where,rows:[{entity,
    # name,source,meaning,container,mode,notes}], channels:[…]}], access:{E-id:{writers,readers,other}},
    # not_persisted:[{section,mode,label,warn,entities}] + np_sections:[{key,label}] (entities with no
    # collection of their own, SPLIT by whether they are still durable — an embedded row also carries
    # its `parents` and the `home` collection it lands in), gaps:[{dep,name,pairs}],
    # unassigned_channels:[…]. All derived (writers/readers from C→E edges, gaps from the shared
    # persistence rule, homes by walking containment); not part of project-map.json.
    data_view: dict[str, object]
    tests_note: str                         # the "Tests run for this table?" honesty line
    # targets resolved server-side (name + node-locatability) so the Tests tab needs no id parsing.
    tests: list[TestRowView]
    # Authored sections: {heading, body, maintenance}. `maintenance` marks the map's own build
    # record — the lines that answer this tool's checks — so the System tab can lead with notes
    # about the code and fold the adjudication log away at the bottom (`records.HEADINGS`).
    extras: list[ExtraSectionView]


class ExtraSectionView(TypedDict):
    """One authored extras section as the viewer receives it."""
    heading: str
    body: str
    maintenance: bool
    refs: dict[str, TestTarget]   # element ids named in `body` → {id, name, node}, resolved server-side


_LINE_OF = re.compile(r"(?:#L|:)(\d+)(?:-L?\d+)?$")  # a trailing anchor's START line, either form


def _line_of(href: str | None) -> int | None:
    if not href:
        return None
    m = _LINE_OF.search(href)
    return int(m.group(1)) if m else None


SERVICE_HINTS = re.compile(
    r"\b(agent|service|svc|server|system|external|idp|bot|daemon|cron|scheduler|worker|webhook|job)\b", re.I
)


def _role_kind(name: str, explicit: str) -> str:
    """An explicit kind wins; with none, infer `service` from name hints.

    A KNOWN KIND PASSES THROUGH VERBATIM. This used to collapse every explicit value into two —
    `startswith("s")` meant service, everything else meant human — and `ai-agent` starts with an
    `a`, so the day that kind arrived every AI actor reached the browser labelled `human`: a stick
    figure, the wrong pill, and the wrong colour on every diagram, with the map itself saying
    otherwise. It is the most dangerous shape of bug in this file, because nothing downstream can
    tell a coerced value from an authored one.

    The two-value fallback stays for a spelling this build does not know (`svc`, `bot`), so an old
    or hand-typed map still draws something sensible."""
    if explicit:
        k = explicit.strip().lower()
        return k if k in grammar.ROLE_KINDS else ("service" if k.startswith("s") else "human")
    return "service" if SERVICE_HINTS.search(name) else "human"


def _ensure_default_subsystem(nodes: dict[str, Node], title: str | None) -> None:
    """If the map has components but defines NO subsystem, inject one default subsystem (`S0`, named
    after the project) and reparent every component under it. This keeps the viewer uniform: there is
    always a subsystem altitude that holds the component-level view, so the flat per-component map is
    never the only place components live. A map that already groups its components is left untouched;
    a pure domain map (no components) gets nothing."""
    has_subsystem = any(n.kind == "subsystem" for n in nodes.values())
    comp_ids = [nid for nid, n in nodes.items() if n.kind == "component"]
    if has_subsystem or not comp_ids:
        return
    nodes[DEFAULT_SUBSYSTEM_ID] = Node(
        id=DEFAULT_SUBSYSTEM_ID, kind="subsystem", name=title or "Application",
        file=None, line=None,
        fields={"Purpose": "All components — this map defines no subsystem grouping."},
        parent=None,
    )
    for nid in comp_ids:
        nodes[nid].parent = DEFAULT_SUBSYSTEM_ID




