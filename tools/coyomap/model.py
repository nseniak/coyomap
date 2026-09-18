#!/usr/bin/env python3
"""The canonical map model (JSON source). See method/model.md.

`.coyomap/project-map.json` is the committed source of truth; the markdown map and the HTML
diagram are generated views. This module is the model's single definition: the typed dataclasses,
the DETERMINISTIC serializer (same model → byte-identical JSON, so the committed file diffs
cleanly), and the structural loader (`load_model`), which validates shape/types field-by-field and
reports the exact path of a violation — the "schema validation" half of `coyomap validate`.

Stdlib-only, like every core tool. Semantic checks (IDs resolve, hierarchy sound, code anchors
exist) are NOT here — they are `validate_model.py`'s job; this module only guarantees that a loaded
object IS a well-typed model.
"""
from __future__ import annotations

import json
import os
import re
import sys
import types
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Union, get_args, get_origin, get_type_hints

from coyomap import grammar

FORMAT = "coyomap-map"
#: What every map built before 2026-09-13 says, when the tool was called coyodex. Refused, with the
#: two edits named: the map folder and this field are the only things the rename changed for a user.
OLD_FORMAT = "coyodex-map"
OLD_MAP_FOLDER = ".coyodex"
RENAME_HINT = ("coyodex is now coyomap (renamed 2026-09-13): rename the map folder .coyodex/ to "
               ".coyomap/ and set \"format\": \"coyomap-map\" in project-map.json")


def old_map_folder_hint(folder: "Path | str") -> str | None:
    """The rename hint when `folder` still holds the old `.coyodex/` map and no `.coyomap/` one, else
    None. One text for the CLI's default-map lookup and the viewer's project intake."""
    root = Path(folder)
    if (root / OLD_MAP_FOLDER).is_dir() and not (root / ".coyomap" / "project-map.json").exists():
        return f"found {OLD_MAP_FOLDER}/ but no .coyomap/project-map.json: {RENAME_HINT}"
    return None

# Each element array's required id prefix — structural (a `Cn` in `deps` is a shape error, caught at
# load), while uniqueness/resolution stay semantic (validate_model).
# ORDER MATTERS: the alternation is first-match, so a multi-letter prefix must precede any prefix it
# starts with — `CAP` before `C`, `EP` before `E` — else `CAP3` matches `C` and then fails on `AP3`.
ID_SHAPE = re.compile(r"^(UC|HP|SD|SF|CAP|EP|BLK|BR|C|D|E|I|S|R)\d+$")


class ModelError(ValueError):
    """A structural violation in a model document, carrying the JSON path of the offending value."""


# ── the model ────────────────────────────────────────────────────────────────────────────────────

@dataclass
class RoleRelation:
    """One authored link between two roles — the map's answer to 'is this the same person wearing
    another hat'. Roles are permission hats the code recognizes; without a relation the viewer
    draws one person as several strangers (the prospect who signs in IS the future admin).

    `kind` is a closed pair: `becomes` (this role turns into `role` at the use case `at` — the
    transition must be a real, mapped action) and `includes` (this role may do everything `role`
    may do). Validation stops at referential integrity: `role` and `at` must resolve to defined
    ids, and nothing more is checked — whether `at`'s use case lists both roles is the map
    author's judgement, not a rule."""
    kind: str                 # becomes | includes
    role: str                 # Rn — the other role
    at: str | None = None     # UCn — becomes only: the use case where the hat changes
    #: `includes` only: the `path:line` that grants the inclusion. An `includes` is an ACCESS claim —
    #: the viewer draws it as "may also do everything a Team member may do" — and it was the one
    #: element class in the map that asserted who may do what while being structurally incapable of
    #: carrying evidence: `at` is pinned to a use-case id, and there was no other field. A fabricated
    #: `R3 includes R1` (a headless agent may do everything an admin may do) passed `validate` with
    #: exit 0 and left `audit`'s theme counts byte-identical. On the map that found this, `R1
    #: includes R2` was not true of the code at all: the admin flag gates the dashboard routes, and
    #: the three functions deciding what a caller actually reaches never consult it.
    source: str | None = None


@dataclass
class Role:
    id: str                   # Rn — a role is a first-class element, referenced by id (not by name)
    name: str
    #: human | service | ai-agent (grammar.ROLE_KINDS; free text preserved, the viewer normalizes).
    #: `ai-agent` is a program driven by a language model, acting for somebody. It is always
    #: OUTSIDE the product, which is why it is not spelled `service`: only `service` + an `internal`
    #: audience means the product's own scheduled work. Every "is this a program" question reads
    #: `grammar.is_machine_role`, which is `!= human`, so a new kind is a machine by default.
    kind: str = ""
    audience: str = ""        # user | internal (grammar.ROLE_AUDIENCE) — WHICH SIDE of the product
                              # this actor sits on. A PERSON: does the person work for the company
                              # that ships it? A PROGRAM: whose machine is it — the customer set it
                              # up (user), or the company runs it or pays a vendor to run it
                              # (internal)? The map's one authored answer to "who is this for": a
                              # capability's audience is DERIVED from the roles driving its use
                              # cases (`capability_audience`), so the two can never contradict each
                              # other. Orthogonal to `kind`: a customer's own bot is service+user,
                              # an upkeep job is service+internal.
    wants: str = ""
    drives: str = ""          # the "Use cases they drive" cell (UC ids inside)
    relations: list[RoleRelation] = field(default_factory=list)  # optional; [] = no relation stated


@dataclass
class GlossaryRow:
    term: str
    meaning: str = ""
    source: str | None = None  # the term's canonical code home: a bare `path:line` or `path/`
                               # anchor (like Component.source / Entity.source), or None when the
                               # concept has no single code home (a pure product-level term)
    aliases: list[str] = field(default_factory=list)  # extra surface forms the viewer also turns
                               # into in-place definitions. Real alternative NAMES only — the viewer
                               # folds plural/possessive/case/hyphen variants on its own, so those
                               # never belong here (see the Glossary deliverable in method.md).
    no_autolink: bool = False  # True = the term's own name is excluded from automatic linking (it
                               # links only via its aliases, or not at all). Escape hatch for a term
                               # whose name is an ordinary English word ("Tool") that would link
                               # every unrelated use of the word.


@dataclass
class UseCase:
    id: str
    name: str
    actors: list[str] = field(default_factory=list)  # the role ids that drive this use case (was a
                                                     # single free-text `actor` name in the pre-role-id format)
    trigger: str = ""             # what starts this use case, in one sentence
    outcome: str = ""             # what the actor comes away with, in one sentence. The pair is
                                   # the use case's OUTSIDE face; the flow is its inside one.
    capability: str | None = None    # CAPn — the capability this use case belongs to. Symmetric with
                                     # Component.subsystem / Entity.subdomain: authored once, and every
                                     # capability-derived view (the overlay, the Use-cases grouping, the
                                     # Happy-Path membership rule) reads it rather than re-deciding.
    entry_points: list[str] = field(default_factory=list)  # EPn — the TRIGGER arm of entry-point
                                     # claiming: the front door(s) an actor hits to START this use case.
                                     # 0, 1, or a few; EMPTY IS LEGITIMATE (the front door may sit inside
                                     # a coarse T4 row a sibling already names, or the row may not be
                                     # recorded at that granularity). The other arm — surfaces the
                                     # scenario merely PASSES THROUGH — stays derived from the flow's
                                     # component reach, which remains the primary claim (see
                                     # validate_model's front-door family).


@dataclass
class HappyStep:
    id: str                   # HPn — the position in the walk
    uc: str | None = None     # the use case this step realizes (required by validate). The step
                              # has no text of its own: every screen labels it with that use
                              # case's name, so one goal is worded once.
    why: str | None = None    # the prerequisite that fixes this step's position


@dataclass
class Stake:
    """CAPABILITY-ONLY: what ONE driving actor comes to this capability to do. A short verb phrase
    with the actor as the implied subject ("mounts, configures and runs the servers"), written to
    read correctly after the actor's name. The Features diagram labels each actor→feature arrow
    with it; a capability's own purpose is written from one chair and hides the other roles."""
    actor: str                # Rn — the driving role this stake belongs to
    stake: str = ""           # the verb phrase (writing rules apply: one idea, plain words, no code)


@dataclass
class StoryAnchor:
    """CAPABILITY-ONLY: where a feature the walk never reaches SITS in the one product story.

    The viewer draws ONE story column — the walk unbroken, then the off-walk features in a block
    after it — and a feature with no walk step has no derived position in it. The anchor is the
    authored answer: this feature reads `before` or `after` that one. `after` a walk feature only
    ORDERS the trailing block, since the block already sits after every walk feature; `before` a
    walk feature is the one anchor that keeps a feature among the walk, because the end of the
    column is not before anything. Without an anchor the viewer falls back to a guess (the
    feature's actors' last walk step), which never rescues a lead-in like a marketing page. Validation
    stops at shape + referential integrity: `place` is the exact pair, `feature` must resolve and
    not be the capability itself; whether the placement reads well is the author's judgement."""
    place: str                # before | after
    feature: str              # CAPn — the feature this one reads beside


@dataclass
class Group:
    """A subsystem (S), a subdomain (SD), or a capability (CAP) — same shape, three forests."""
    id: str
    name: str
    purpose: str = ""
    parent: str | None = None
    happy_path: str = ""       # CAPABILITY-ONLY: expected | excluded (grammar.CAP_HAPPY_PATH). Does the
                               # Happy-Path walk have to reach this capability? It is what makes
                               # membership a rule instead of a written record per off-spine use case.
                               # Deliberately NOT derived from `ProjectModel.happy_path`: a field that
                               # always agreed with the walk could never disagree with it, and the
                               # disagreement IS the check. `validate` blocks it on a subsystem or a
                               # subdomain, which have no walk to be on. Says NOTHING about audience —
                               # that is `Role.audience`, derived up by `capability_audience`.
    stakes: list[Stake] = field(default_factory=list)
                               # CAPABILITY-ONLY: one entry per driving actor, saying what THAT actor
                               # comes to this capability to do (see Stake). `validate` blocks it on
                               # the other forests, and advises when a derived driving actor has none.
    story: StoryAnchor | None = None
                               # CAPABILITY-ONLY: where a feature the walk never reaches sits in the
                               # one story column (see StoryAnchor). None = derive (actors' last walk
                               # step) — orders the trailing block for trailing features, and cannot
                               # pull a lead-in one back among the walk; only `before` does that.
    owners: list[str] | None = None
                               # SUBDOMAIN-ONLY: which feature(s) this data area exists FOR — the one
                               # that creates its records and runs their lifecycle. AUTHORED, never
                               # derived: every derivation was measured on three live maps and each
                               # one guessed from what the code TOUCHES, which is not what the data
                               # is FOR (snapshots are first written by Page tracking but exist so
                               # Change detection can compare them). One id = that feature owns it;
                               # several = deliberately shared among exactly those; None = not
                               # decided (advisory nudges a decision, old maps still load). `[]` is
                               # a shape error, not "none": say who, or leave the field out.
                               # `validate` blocks it on the other forests, and cross-examines the
                               # list against the derived touches (grounding / split / dominance).
    specified_under: list[str] | None = None
                               # BLOCK-ONLY: the feature(s) this decision area would be SPECIFIED
                               # UNDER — where a person writing the product's spec would put these
                               # rules. AUTHORED, and the reason is `owners` one field
                               # up, one forest over: every derivation was measured on three live
                               # maps and every one failed. The feature a rule's steps land on is a
                               # plurality, not a home (52% and 61% at the median; 8 of 32 areas win
                               # on under half their links, one on 23% against a runner-up at 20%);
                               # entities reach only 10% of walked steps; actors collapse to two
                               # groups of nine and two; components fan out to 100+ per map; and the
                               # happy path ties four areas at one station.
                               #
                               # TWO STANDPOINTS, AND THIS FIELD IS THE FIRST ONE:
                               #   SPEC        under which feature would these rules be WRITTEN
                               #   ENFORCEMENT in which feature's code are they APPLIED
                               # They differ on most areas. mcpolis's "Who may call which tool" is
                               # specified under Access control, whose whole job is deciding who may
                               # reach which tools, and enforced inside the gateway. Its "Plan caps"
                               # is applied in six features — teammates, servers, roles, machine
                               # sizes, argument checks, history — and specified under a plans
                               # feature that product has not shipped, so the field is absent there.
                               #
                               # THE ENFORCEMENT ANSWER IS ALREADY DERIVABLE, which is what settles
                               # it: a rule carries its own call sites, sites resolve to components,
                               # and steps join to use cases and so to features. Spending the one
                               # authored field on that would buy a worse copy of what the map has.
                               # Nothing in the code says where a rule would be WRITTEN IN A SPEC;
                               # that judgement is the thing only a person can make.
                               #
                               # NOT `owners`, which is deliberately about DATA: an owner is the
                               # feature that creates a record and runs its lifecycle, and a decision
                               # area keeps nothing. Same authoring discipline, different question,
                               # so a different word — and `validate` blocks each on the other's
                               # forest rather than letting one field mean two things.
                               #
                               # NO RECONCILE DIRECTIVE, for the reason `subdomains[].owners` needs
                               # none: a decision area is authored AT SYNTHESIS, in the same pass
                               # that mints the features, so the answer is written straight onto the
                               # area and never has to travel through a reconcile file the way a
                               # rule's `block` does.
                               #
                               # WHAT IT BUYS: the Rules page groups by it, and because features are
                               # already ordered by the story column, the groups arrive in the
                               # product's own order without a second field. One id = this area
                               # governs that feature; several = it genuinely spans them; None = not
                               # decided (advisory asks). `[]` is a shape error, not "none".
    source: str | None = None  # bare path anchor to the group's home: a file `path:line`, or a
                               # directory ref ending in `/` (like Component.source / Entity.source)
    confidence: str = ""
    tech: str = ""             # SUBSYSTEM-ONLY: one honest stack label ("Python/FastAPI", "Go",
                               # "Elixir") read off the manifests — live maps left container tech
                               # buried in deployment prose. `validate` blocks it on a subdomain
                               # (a bounded context has no stack).
    tech_source: str = ""      # optional bare `path:line` anchor to the manifest line proving the
                               # label (go.mod, package.json, pyproject.toml)


@dataclass
class EvidenceItem:
    """One citation grounding a claim the map makes about the element carrying it — a
    fresh-context skeptic re-reads `file` and checks whether `why` still holds."""
    file: str                        # bare path:line anchor
    why: str


@dataclass
class Interface:                     # T2b — the product's outside edge
    """One surface through which the product exchanges data or events with something outside itself.

    Two orthogonal facts, deliberately not squeezed into one word (the words "inbound"/"outbound"
    were tried and abandoned — they meant three different things at once: who starts the contact,
    which way data flows, and whose surface it is):
    `side` is whose DESIGN it is; the overall flow is DERIVED from the `direction` its walk steps
    carry. Who STARTS the contact is already recorded on every way in (`EntryPoint.activation`) and
    gets no field here. THE SURFACE ITSELF AUTHORS NO DIRECTION — that was `carries[]`, and its one
    underivable fact now lives on the step that does the crossing."""
    id: str                          # I<n>
    name: str                        # the surface in PRODUCT words ("Customer dashboard"), never a
                                     # code word ("http-route")
    what: str = ""                   # one sentence: what this surface is for
    side: str = ""                   # ours | theirs (grammar.INTERFACE_SIDES)
    facing: str = ""                 # user | operator (grammar.INTERFACE_FACINGS) — AUTHORED
    #: What SHAPE this surface is — `grammar.INTERFACE_KIND_SEEDS`, seeded-open. SHAPE, NEVER
    #: PURPOSE: a payment processor and a crash reporter are both `api`, and which is which is
    #: already authored on the dependency's `bucket`. A kind that answers "what is it FOR" means this
    #: field has been mis-modelled. It exists so the viewer can DRAW the surface, which is why the
    #: vocabulary is the size of an icon set. NOT derivable from the ways in: measured, one clean
    #: answer on 4 of coyomap's 11 surfaces and 1 of mcpolis's 12, and nothing at all on a `theirs`
    #: surface, which has no ways in by definition.
    kind: str = ""
    #: The ways in this interface is made of. Points DOWN, like `UseCase.entry_points`, and for the
    #: same reason: `EPn` ids are minted by `assemble` from content, so a fragment cannot know them
    #: and `reconcile` is the only path. NAMED `ways_in`, NOT `entry_points`: `_SET_FIELD_OWNER` is
    #: keyed by FIELD NAME, so reusing the name REPLACES the use-case entry and breaks every
    #: existing map (this repo's own reconcile.json carries 34 use-case directives over 65 EP ids).
    #: Empty is legitimate: a `theirs` interface has none, and neither do the rows with no T4 row at
    #: all (the files a product writes, the settings an operator sets).
    ways_in: list[str] = field(default_factory=list)
    #: The one line that declares the SURFACE — the router, the command table, the file writer.
    #: Advisory, never required: `ConfigRow` carries no anchor and a Settings surface is declared in
    #: no single place (coyomap's 11 keys live in ~9, one of them in no file at all).
    source: str = ""
    confidence: str = ""             # verified | inferred | "" (grammar.CONFIDENCE_VALUES)
    evidence: list[EvidenceItem] = field(default_factory=list)


@dataclass
class Component:
    id: str
    name: str
    subsystem: str | None = None
    purpose: str = ""
    depends_on: str = ""             # the coarse derived summary text (edge list is the source)
    source: str | None = None        # v2: the canonical source anchor — where the component LIVES
    confidence: str = ""
    files: list[str] = field(default_factory=list)       # repo-relative paths this component owns
    runs_in: list[str] = field(default_factory=list)     # deployment unit name(s) whose PROCESS runs this
                                     # component's code — a runtime placement (the C4 instance link),
                                     # powering the Deployment view. Verified for a satellite (own dir/
                                     # image), inferred for the shared monolith; empty = untraced. Each
                                     # value must resolve to a `deployment[].unit` (validate).
    evidence: list[EvidenceItem] = field(default_factory=list)
    states: "StateMachine | None" = None  # the component's runtime lifecycle, when the code
                                     # implements one (a connection manager's connecting/live/failed)
    extra: dict[str, object] = field(default_factory=dict)  # non-standard authored columns, by
    # header; values are any JSON value (agents return lists/numbers/bools naturally — the views
    # render non-string values as compact JSON). A key `coyomap validate` gives a fixed shape to
    # (or the method otherwise defines) does not belong here — it graduates to a real field instead.


@dataclass
class Dep:
    id: str
    name: str
    kind: str | None = None          # closed Context vocabulary; None → inferred from `type`
    type: str = ""
    used_for: str = ""
    bucket: str = ""                 # PURPOSE bucket (seeded-open) — groups the dep within its diagram
                                     # (Context externals / Libraries drill); "" → inferred from type+used_for
    where_configured: str = ""
    confidence: str = ""
    deployment_linked: bool = False  # v2: wired at deployment level only — no code call site
    package: str = ""                # "<name> <version> (<where declared>)"
    alternative: str = ""            # the fallback used instead, and when
    evidence: list[EvidenceItem] = field(default_factory=list)
    #: The `I<n>`s this dep belongs to, on EITHER side of each. A dep can BE the interface (Sentry)
    #: or sit on the FAR SIDE of one of ours (the coding agents that call coyomap's skill), so `side`
    #: is authored on the interface and never inferred from whether deps point at it.
    #: A LIST, because one outside system really does sit on several surfaces: coyomap's own map has
    #: Claude Code hosting the agent skill AND writing the build transcript coyomap reads back. A
    #: single slot forced one of those two surfaces to show no code behind it.
    interfaces: list[str] = field(default_factory=list)
    #: Why this dep is no interface at all. REQUIRED when the dep is in `DEP_KINDS_SYSTEM` and
    #: `interfaces` is empty — without it there is no way to tell "deliberately not one" from "the
    #: agent never looked", which is exactly the trap a search service sets (a search over the
    #: product's own records is not an interface; a search over the open web is, and the call site
    #: looks identical). Frameworks and libraries are exempt: they become the product.
    not_an_interface: str = ""
    extra: dict[str, object] = field(default_factory=dict)  # any JSON values, like Component.extra


@dataclass
class RunRow:                        # T3
    action: str
    command: str = ""
    source: str = ""                 # bare `path:line` anchor: where the command is defined (script /
                                     # Makefile target / config line) — not a markdown link, not prose


@dataclass
class EntryPoint:                    # T4
    id: str = ""                     # EPn — MINTED BY `assemble`, never authored in a fragment. Entry
                                     # points are identified by CONTENT (their `source` anchor), not by
                                     # a per-agent id range: change-impact already keys them that way
                                     # (`ep:{source}`, stable across rebuilds), harvest agents already
                                     # juggle C/D/E/SF ranges, and a 4th range would make an overlap a
                                     # hard build failure for ids nobody needs before synthesis. So
                                     # fragments leave this empty, assemble dedups by source and mints
                                     # ids in argument order, and `use_case.entry_points` — authored at
                                     # synthesis via `reconcile`, once T4 exists — is what references them.
    kind: str = ""
    trigger: str = ""
    source: str = ""                 # md link to the code entity — where the entry point LIVES
    component: str = ""              # the owning C id
    activation: str = ""             # "self" | "external" (grammar.ACTIVATIONS); "" → inferred from kind
    runs_in: list[str] = field(default_factory=list)  # the PRECISE host unit(s) of a self-started thread
                                     # (a loop's exact process, since its component may run in several);
                                     # empty → falls back to the owning component's runs_in in the
                                     # Deployment view. Each value must resolve to a `deployment[].unit`.
    cadence: str = ""                # WHEN a self-activated entry point runs: a cron expression
                                     # ("0 3 * * *"), an interval ("every 30s"), "on-boot", or
                                     # "continuous". Meaningful only when the effective activation is
                                     # "self" (validate nudges a cadence on an external EP).
    cadence_source: str = ""         # bare `path:line` anchor to the line DECLARING the schedule (a
                                     # beat/cron config, a compose schedule, the loop's sleep) — often
                                     # a different line than `source`; "" on a set cadence = INFERRED
                                     # (advisory, the deployment-variant rule).


@dataclass
class EntityField:
    name: str
    type: str = ""
    markers: list[str] = field(default_factory=list)  # PK / FK→En / unique / ? / []


@dataclass
class EntityRelation:
    verb: str                        # contains / has / isA / free association verb
    target: str                      # En
    src_card: str | None = None      # cardinality pair — both or neither
    dst_card: str | None = None
    display: str = ""                # optional display text after the target id
    how: str | None = None           # plain-text note: how a field-less relation is implemented
    keyed_by: list[str] = field(default_factory=list)  # storage KEY name(s) the store uses to relate
                                     # the two — a lookup/partition key it imposes, NOT a field on
                                     # EITHER entity's row (e.g. a per-parent store keyed by
                                     # `parent_id`). Distinct from a real FK field (`fk_fields`): if a
                                     # field carries the id, that is a (reverse) FK, not a key. Drawn
                                     # on the arrow with the «key» marker, never in the field box.


@dataclass
class MessagingRow:
    """One channel/queue/topic — the async sibling of a backbone edge, NAME-keyed like a
    deployment unit (nothing points AT a channel, so no id prefix; the row itself is the join).
    The rows CATALOG; the backbone edges CLAIM — each publisher/consumer is expected to also carry
    a real `C→broker` edge (advisory), which is how messaging participation reaches the diagrams
    and the change-impact ripple without a second edge system."""
    name: str                        # unique channel/queue/topic name ("JOB_QUEUE")
    kind: str = ""                   # seeded-open: queue | topic | stream | pubsub | job-queue | …
    broker: str = ""                 # Dn — the messaging/datastore dep carrying it; "" = in-process
    publishers: list[str] = field(default_factory=list)   # C ids that put messages on it
    consumers: list[str] = field(default_factory=list)    # C ids that take messages off it
    payload: str = ""                # En — the entity a message carries; "" = untyped/none
    source: str = ""                 # bare `path:line` anchor to where the channel NAME is declared


@dataclass
class StateTransition:
    src: str                         # a state name declared in the owning StateMachine.states
    dst: str
    on: str = ""                     # the trigger label ("connect ok", "refresh failed")


@dataclass
class StateMachine:
    """A lifecycle the code actually implements — states + transitions + the line DECLARING them
    (an enum / status constants / a dispatch table). Live maps kept these in prose ("disabled/
    deferred/connecting/live/failed" buried in a component purpose): unqueryable, and the first
    thing to rot when the code moves. Optional on entities AND components (a subscription's states
    are entity lifecycle; a connection manager's are component lifecycle)."""
    states: list[str]                # required, non-empty, unique names
    transitions: list[StateTransition] = field(default_factory=list)
    source: str = ""                 # bare `path:line` anchor to the DECLARATION; "" = inferred
                                     # (advisory — cite the enum/constants line)


@dataclass
class Store:
    """WHERE an entity physically lives — structured so "what is persisted in <datastore>?" is a
    query, not a prose hunt (live maps wrote `"mdb: guilds (+ redis cache)"` free text: unqueryable,
    typo-prone, and real collections with no domain type escaped the entity net entirely)."""
    dep: str | None = None           # Dn — the physical datastore/messaging dep holding it; None
                                     # for a store with no dep (in-memory, in-code registry)
    container: str = ""              # the compartment inside the dep: collection / table / key
                                     # prefix / bucket / file name
    mode: str = ""                   # grammar.STORE_MODES (collection/embedded/projection/transient/
                                     # cache/in-code/enum) — closed, exact-match; "" = unstated.
                                     # The five that mean "nothing writes this" (STORE_MODES_UNOWNED)
                                     # answer the unowned-entity advisory on their own.
    notes: str = ""                  # what the shape can't say: TTL, cache tiers, compression


@dataclass
class Entity:                        # a T5 domain card
    id: str
    name: str
    store: Store | None = None       # None = not persisted / not stated. HARD retype (no legacy
                                     # string form): a map authored with `store: "<prose>"` fails
                                     # to load with a targeted error — rebuild or migrate.
    meaning: str = ""
    subdomain: str | None = None
    source: str | None = None        # path:line anchoring the real named type
    fields: list[EntityField] = field(default_factory=list)
    relations: list[EntityRelation] = field(default_factory=list)
    states: StateMachine | None = None  # the entity's lifecycle, when the code implements one
    owners: list[str] | None = None     # OVERRIDE of the sub-domain's `owners`, for the one record
                                        # whose owning feature differs from its area's (an audit
                                        # entry sits in the Audit trail area but is written by the
                                        # gateway). Author it ONLY where it differs from what would
                                        # be inherited — `validate` reports an override equal to the
                                        # inherited answer as redundant. None = inherit, walking up
                                        # `subdomain` then `parent`.


@dataclass
class NonEntityType:
    """v2: an explicit plumbing marker — a named type in the domain dirs that is deliberately NOT an
    entity, so the under-harvest coverage check must not count it as unmodelled."""
    name: str
    source: str | None = None        # bare `path:line` anchor (or a `path/` dir) to where the type is
                                     # defined — same shape as entity.source, not a markdown link
    why: str = ""


@dataclass
class FlowStep:
    n: int
    src: str                         # an element ID or a Role display name (actor step)
    dst: str
    phrase: str = ""                 # authored inline action text (required on every step — `validate`;
                                     # EXEMPT on a sub-flow reference step, where it defaults to the
                                     # sub-flow's name)
    note: str = ""                   # flow-specific note
    where: str | None = None         # THE location: bare `path:line` of this step's own call site —
                                     # unlike an edge's `where` (an example among possibly many), a step
                                     # is exactly one interaction, so its anchor is precise. Required on
                                     # element↔element steps (`validate` blocks) unless `no_call_site`;
                                     # optional on actor steps (a human action has no call site).
    no_call_site: bool = False       # opt-out, mirroring Edge.no_call_site: this step has no single
                                     # call site (event-driven / config-wired) — `where` may be null.
    #: WHICH WAY THE DATA MOVES, read from the product's own code: `in` it arrives, `out` it leaves,
    #: `both` one exchange runs both ways (`grammar.STEP_DIRECTIONS`). REQUIRED on a step where the
    #: map's OWN CODE touches a surface or a record; EMPTY everywhere else.
    #:
    #: TWO KINDS OF STEP OWE NOTHING. A step between two components moves nothing across anything
    #: (1071 of the 1762 steps across the live maps). And a DOOR — a role standing at a surface —
    #: is a human action with no product end at all: argus's operator opens the log store's own
    #: console and nothing of ours moves. Forcing an answer on a door produced labels that
    #: contradicted their own step's phrase, and it is the same exemption an actor step already has
    #: from `where`.
    #:
    #: This is the map's ONLY statement of direction, and it is why `interfaces[].carries[]` could be
    #: removed. Measured before that removal: direction was the one thing on a crossing row that no
    #: step could say, its record list held 2 real independent records out of 68 references, and its
    #: sentence repeated what the steps already said (66% of its words, at the busiest surfaces).
    #:
    #: It answers at a RECORD too, not only at a surface, and that is not a bonus: 83 of the 170
    #: record steps across the two live maps sit on a component/record pair whose arrows say BOTH
    #: read and write, so the step alone could not say which it was.
    direction: str = ""
    subflow: str | None = None       # a REFERENCE step: "runs SFn here". src/dst stay authored (the
                                     # run's entry/exit endpoints — every unexpanded consumer keeps
                                     # working); the step carries NO where/no_call_site of its own
                                     # (its location IS the sub-flow's steps' anchors — `validate`
                                     # blocks a contradiction). One level only: a sub-flow's step may
                                     # not itself reference a sub-flow.


@dataclass
class Flow:                          # T6 — the inside view of one use case
    uc: str
    title: str
    steps: list[FlowStep] = field(default_factory=list)


@dataclass
class SubFlow:
    """A named, reusable step sequence (an "include" fragment): machinery shared by ≥2 use-case
    flows — an OAuth dance, an event fan-out — defined ONCE and referenced by a FlowStep whose
    `subflow` names it. Steps are ordinary FlowSteps under all the ordinary rules (phrase, anchors,
    unique `n`); nesting is forbidden (one level). Extracting a shared run keeps every flow that
    rides it at the same depth — the alternative is each flow retelling it at whatever grain its
    author happened to pick."""
    id: str                          # SFn
    name: str
    steps: list[FlowStep] = field(default_factory=list)


@dataclass
class Edge:                          # one backbone edge (C↔C, C↔D, C→E)
    src: str
    verb: str
    dst: str
    why: str | None = None
    where: str | None = None         # the call site: bare `path:line` in src's code where it invokes dst
    no_call_site: bool = False       # opt-out: this relationship has no single call site (event-driven /
                                     # shared-state / config-wired coupling) — `where` may be null. Without
                                     # it, a missing `where` is a blocking `validate` error, not a warning.


@dataclass
class VariantTag:
    """One environment placement of a deployment unit, WITH its grounding. `env` names a
    `ProjectModel.environments` entry; `source` is a bare `path:line` anchor to the manifest line that
    places the unit in that environment (the compose `profiles:` line, the overlay/values file, the
    stage declaration). `source == ""` = INFERRED: no manifest witness, so `validate` surfaces it as an
    advisory (escapable via the `runs-in/quality` Balance-exceptions literal), never blocks — an unanchored tag
    is a soft claim, not a proven fact. A CITED `source` that does not resolve on disk IS a hard block
    under `--check-sources` (same treatment as `security[].source`)."""
    env: str                         # must name a `ProjectModel.environments` entry
    source: str = ""                 # bare `path:line` anchor to the manifest line; "" = INFERRED


@dataclass
class DeploymentRow:
    unit: str
    runs_on: str = ""
    exposed_as: str = ""
    config_source: str = ""
    variants: list[VariantTag] = field(default_factory=list)  # the environment(s) this unit belongs to
                                     # — each `VariantTag.env` must name a `ProjectModel.environments`
                                     # entry, and SHOULD cite the manifest line that grounds it (else it
                                     # is inferred). Empty = UNGATED: the unit appears in every
                                     # environment (shared infra / no variant axis). Harvested from the
                                     # deploy manifests (compose `profiles:`, k8s overlays, Helm values,
                                     # env-file suffixes, Terraform envs).


@dataclass
class ObservabilityRow:
    signal: str
    where_emitted: str = ""
    where_viewed: str = ""
    alerts: str = ""


@dataclass
class SecurityRow:
    surface: str
    who: str = ""
    source: str = ""                 # bare `path:line` anchor to the auth check in code — an L2
                                     # grounding claim (was a markdown link; now a bare anchor)
    risk: str = ""


@dataclass
class ConfigRow:
    key: str
    purpose: str = ""
    default: str = ""
    per_env: str = ""


@dataclass
class TestRow:
    """One row of the test-completeness gap table. `targets` names the element ids this row assesses
    (explicit, not parsed out of prose), `tests` cites the exercising suites/files as `{file, why}`
    evidence (bare anchors, so the viewer renders them as clickable code links)."""
    targets: list[str]                                        # element ids assessed, e.g. ["C48", "C49"]
    tested: str = ""                                          # yes / partial / no
    label: str = ""                                           # optional display text (grouping / journey name)
    tests: list[EvidenceItem] = field(default_factory=list)   # exercising suites: {file: bare anchor, why: what it covers}
    gap: str = ""
    confidence: str = ""


@dataclass
class RuleSite:
    """One place a business rule is actually ENFORCED — the line that acts, not the line that
    declares. Deliberately NOT an `EvidenceItem`: evidence CITES a claim ("re-read this and the
    purpose still holds"), a site ASSERTS that this line does the deciding, which is what the
    operative-line check (`call_site_anchors`) gates on. Folding `no_call_site` into `EvidenceItem`
    would leak a call-site concept onto components, deps and test rows, which cite rather than act."""
    where: str | None = None     # bare `path:line` — the OPERATIVE line (a definition header, an
                                 # import or a comment is a shape error, not a site). Typed
                                 # `str | None` exactly like Edge.where / FlowStep.where, so the
                                 # DECLARED-ABSENCE form is expressible: a required `str` whose
                                 # published pattern rejects `""` makes `no_call_site` unwritable.
    why: str = ""                # what this line does FOR the rule ("rejects a non-owner caller")
    no_call_site: bool = False   # declared absence, mirroring Edge/FlowStep.no_call_site: this rule
                                 # is enforced by construction (a type, a schema constraint, a
                                 # config-wired guard) and has no single line — `where` may be empty.


@dataclass
class BusinessRule:
    """ONE product decision the code makes, plus every place it is enforced — the map's decision
    layer (T7). Entities say what the product stores, flows say what it does in what order,
    lifecycles say what states it moves through; nothing said what it DECIDES, which is exactly the
    part a reader calls "product-specific".

    EVERYTHING ELSE IS DERIVED. The components a rule lives in, the use-case steps that enforce it,
    the entities it touches and whether it has been swept are all computed from `sites` against the
    rest of the map (`validate_model.rule_components` / `rule_steps`). There is deliberately no
    `components`, no `steps` and no `swept` field: an authored boolean asserting "I searched the
    whole repo" is unfalsifiable, and hand-assigned data rendered as derived was the prototype's
    most damaging failure — it looked correct on every screen."""
    id: str                      # BRn
    statement: str               # ONE decision, in product language, naming no component
    name: str = ""               # the SHORT title — a few words, the way a use case has a `name`
                                 # beside its trigger→outcome sentence. REQUIRED of authored
                                 # content: the schema lists it (see json_schema._ALSO_REQUIRED),
                                 # `rule_row_problems` blocks without it, so both `lint-fragment`
                                 # and `validate` fail on a rule that has none. A rule used to be a
                                 # full sentence and nothing else, so every list of rules was a wall
                                 # of prose with nothing to skim and every breadcrumb truncated one
                                 # mid-word; every other element in the map has a `name`, this was
                                 # the one that did not.
                                 #
                                 # The DEFAULT is what makes the requirement a gate rather than a
                                 # wall: with no default the dataclass cannot be constructed at all,
                                 # so a map written before the field existed would fail to LOAD —
                                 # `coyomap serve` could not open it to show the reader what is
                                 # wrong, and `validate` could not report it either. It loads, it
                                 # renders (the views fall back to the statement), and every gate
                                 # says so until the map is rebuilt.
    block: str | None = None     # BLKn — the decision area this rule belongs to. Assigned at
                                 # synthesis via `reconcile` (symmetric with UseCase.capability):
                                 # `BLK` ids are minted at synthesis while rules are authored after
                                 # the trace, so a fragment cannot know them, and a re-synthesis that
                                 # renumbers blocks must not silently re-point every rule.
    sites: list[RuleSite] = field(default_factory=list)
    access: bool = False         # this rule governs WHO MAY DO WHAT — the security marker. The
                                 # security surface table and the eval's `auth_surfaces` read it.
    risk: str = ""               # what is AT STAKE if this decision is wrong or absent. Authored,
                                 # like `confidence` — it is a judgement, not a derivation, and it
                                 # is the one thing a `security[]` row carried that a statement, a
                                 # site and a `why` between them cannot say: "Tenant-only. No scope
                                 # is required to read" is not what the line does, it is what the
                                 # line's LIMIT costs. Meaningful mainly on an `access` rule, which
                                 # is where the security surface table renders it.
    confidence: str = ""


@dataclass
class ExtraSection:
    """An unrecognized authored section, preserved verbatim so a converted map loses no content."""
    heading: str
    body: str = ""


@dataclass
class Grounding:
    """How much of the map's L2 claim surface the Phase-4 skeptics actually challenged.

    Every other quality signal in a map is per-row; this one is about the map's OWN confidence, and
    without it a reader cannot tell a fully-challenged map from an unchallenged one — both render
    identically and both pass every gate. It matters most exactly where it is hardest: on a large
    monorepo build, 319 of 1,608 claims (20%) were grounded and 11% of those were REFUTED, so the
    unchallenged remainder plausibly held ~140 more wrong claims. The lead reported that honestly in
    chat, where it is lost; recorded here it travels with the map.

    THE COUNTS, and why there are four of them. `claims_total` is the size of the audit's L2 worklist
    at grounding time. `claims_challenged` is how many got a verdict at all. The verdict then splits
    three ways, because `method.md` allows three (`"grounded": true|false|"unverifiable"`):
    `claims_confirmed` held up, `claims_refuted` came back refuted (and were fixed),
    `claims_unverifiable` could not be settled from the code either way.

    The field used to be called `claims_grounded`, and a live map recorded
    `total 399, grounded 399, refuted 3` — which reads as "399 grounded AND 3 refuted out of 399".
    The number was defensible under the old docstring ("how many got a verdict") and the NAME was a
    lie, so a reader could not tell 396-held-up from 399-held-up. Renaming it is half the fix; the
    other half is recording the split, because only then does the arithmetic
    `confirmed + refuted + unverifiable == challenged` exist to be checked. `validate` checks it.

    An unverifiable verdict is not a failure to report. It is the honest outcome when the code cannot
    settle a claim, and folding it into either other bucket is what makes a grounding record lie.

    Leave the whole object absent when no grounding pass ran — `validate` says so rather than
    assuming."""
    claims_total: int = 0
    claims_challenged: int = 0
    claims_confirmed: int = 0
    claims_refuted: int = 0
    claims_unverifiable: int = 0

    #: THE PIN vs THE LIVE MAP. The five counts above are pinned to the worklist the skeptics were
    #: GIVEN, and that pin is load-bearing: recomputing them against the finished map yields
    #: `refuted 0`, because the claims a reconcile deletes are exactly the refuted ones. (Reproduced;
    #: see `grounding.py`.) But reconciling a refutation rewrites its claim, so the pinned surface and
    #: the shipped one legitimately differ — and a build had no way to say so. Every documented escape
    #: was closed: the pinned record raised a staleness advisory, re-running against a fresh worklist
    #: was REFUSED, and explaining the snapshot in `note` changed nothing. These three fields are how
    #: a build states the delta instead of arguing with the gate.
    #:
    #: `claims_superseded` — pinned claims the reconcile rewrote or removed, so their verdict names
    #: nothing in the shipped map. `claims_added_since` — claims the shipped map has that did not
    #: exist when the worklist was pinned. Both are EXPLANATIONS, deliberately not proof: they are
    #: sizes, and `total - superseded + added_since == live` is a TAUTOLOGY — plain set arithmetic,
    #: `|P| - |P-L| + |L-P| = |P∩L| + |L-P| = |L|`, true for ANY two sets. It is not a consequence
    #: of the writer's refusals: brute-forced over 20,000 configurations with the refusals
    #: deliberately violated, zero failures. So it can never fail and must never be read as proof.
    #:
    #: `live_claims_digest` is the proof. sha256 over the sorted, de-duplicated live claim strings at
    #: the moment the record was written. It is the one field a build cannot plausibly fabricate, and
    #: the only one that catches a 1-for-1 rewrite — where k claims are replaced by k others, the
    #: count stays put and every size-based check closes while the surface has changed underneath.
    claims_superseded: int = 0
    claims_added_since: int = 0
    live_claims_digest: str = ""

    #: `claims_live_challenged` — how many of the SHIPPED map's claims carry a verdict. The five
    #: pinned counts above describe the worklist the skeptics were GIVEN, which is right, and is
    #: also how a finished map came to record `claims_total 209, claims_challenged 209` while ten of
    #: its own live claims had never been challenged: the build reworded three rule statements and
    #: one site note AFTER the vote, retiring ten pinned claims and minting ten fresh ones. Every
    #: pinned number stayed true, `claims_added_since` said 10, and the headline still read as full
    #: coverage — in the map, in the rendered view, and in the commit message.
    #:
    #: It is NOT derivable from the pinned counts in general. On a COMPLETE pass it equals
    #: `claims_total - claims_superseded`, because every pinned claim was voted; under `--partial`
    #: the unvoted and the superseded claims overlap by an unknown amount and that identity stops
    #: holding. So it is measured against the live set and recorded, never inferred.
    #:
    #: Zero on a record written before this field existed, and on one written without `--map` (there
    #: is no live set to measure). Both cases fall back to `claims_added_since`, which is a LOWER
    #: bound on the live claims with no verdict rather than the exact figure.
    claims_live_challenged: int = 0

    #: WHAT THE CLOSER DECIDED, which until now the map kept nothing of. A closer is a second
    #: fresh-context reader, denied the map, that re-reads every refutation the skeptics cast and
    #: returns `uphold` (the refutation stands), `reject` (the skeptic misread the code) or `unsure`.
    #: Its answers decide what the map ends up saying — on one build 22 of 24 refutation judgements
    #: were applied on the strength of a sentence in a chat no later reader can open, and on the
    #: 2026-09-13 reminderrepo build two REJECTED refutations are why the map still carries two
    #: claims its own skeptics disproved. A reader of the shipped map could see the refutations and
    #: not the appeal, which reads as two unfixed defects rather than two settled questions.
    #:
    #: THEY ARE NOT VOTES, and this is the reason they are three fields of their own rather than a
    #: shift in the five counts above. Folded into the tally, one `reject` turns a 1-0 refutation
    #: into a 1-1 tie — measured: `claims_refuted 1 → 0, claims_unverifiable 0 → 1` — and every gate
    #: that reads a tie as "not refuted" then reports the claim as cleared. The five counts keep
    #: saying what the SKEPTICS decided about the pinned worklist, which is the arithmetic
    #: `validate` blocks on; these three say what the appeal did to it.
    #:
    #: All three zero means no appeal was heard. `closer_rejected` is the only one that changes what
    #: the refutation gate blocks on (see `grounding.surviving_refutations`): an `uphold` leaves the
    #: refutation standing and an `unsure` leaves it unsettled, and both still need the lead.
    #: The three are ROW counts — a claim re-heard in a second wave is two rows on purpose, and
    #: `validate`'s advisory tie to the closer's own files counts them the same way so the two
    #: cannot drift.
    closer_upheld: int = 0
    closer_rejected: int = 0
    closer_unsure: int = 0

    #: CLAIMS whose appeals DISAGREE — one `uphold` and one `reject` on the same refutation. No row
    #: count can say this: read as rows it is "2 refutations went to appeal, 1 rejected, so the map
    #: keeps the claim", which asserts a settlement at the same moment the gate is refusing one.
    #: A dispute settles nothing, so the refutation still stands and the lead still has to act.
    closer_disputed: int = 0

    note: str = ""                   # how claims were triaged when coverage is partial


@dataclass
class ProjectModel:
    """The whole map. Field order IS the canonical JSON key order (the serializer relies on it)."""
    format: str = FORMAT
    title: str = ""
    goal: str = ""
    commit: str | None = None
    committed: str | None = None
    built: str | None = None
    #: The coyomap build that produced this map — NOT the analysed repo's commit above. Two maps of
    #: one repo are only comparable when read against the tool that made each: a breaking schema
    #: change once made `compare` report REGRESSED for a map that was simply newer.
    tool_commit: str | None = None
    tool_committed: str | None = None
    roles: list[Role] = field(default_factory=list)
    glossary: list[GlossaryRow] = field(default_factory=list)
    capabilities: list[Group] = field(default_factory=list)  # the use-case forest — the container
                                     # precedes its members here exactly as `subsystems` precedes
                                     # `components` and `subdomains` precedes `entities`.
    use_cases: list[UseCase] = field(default_factory=list)
    happy_path: list[HappyStep] = field(default_factory=list)
    subsystems: list[Group] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    deps: list[Dep] = field(default_factory=list)
    interfaces: list[Interface] = field(default_factory=list)   # T2b — the outside edge
    run_commands: list[RunRow] = field(default_factory=list)
    entry_points: list[EntryPoint] = field(default_factory=list)
    subdomains: list[Group] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    non_entity_types: list[NonEntityType] = field(default_factory=list)
    flows: list[Flow] = field(default_factory=list)
    subflows: list[SubFlow] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    messaging: list[MessagingRow] = field(default_factory=list)  # channels/queues/topics — the
                                     # async catalog (name-keyed; see MessagingRow). Sits right
                                     # after `edges`: it reads as the edge list's async sibling.
    deployment: list[DeploymentRow] = field(default_factory=list)
    environments: list[str] = field(default_factory=list)  # the declared deployment-variant names
                                     # (compose profiles / k8s overlays / stages …), in display order —
                                     # an OPEN, project-specific vocabulary. Each `deployment[].variants`
                                     # value must name one of these. Empty = the project has no
                                     # environment axis (single-deploy); the Deployment view then behaves
                                     # exactly as if the field were absent (graceful degradation).
    observability: list[ObservabilityRow] = field(default_factory=list)
    security: list[SecurityRow] = field(default_factory=list)
    config: list[ConfigRow] = field(default_factory=list)
    tests_note: str = ""
    tests: list[TestRow] = field(default_factory=list)
    grounding: Grounding | None = None   # Phase-4 coverage over the L2 claim surface (see Grounding)
    blocks: list[Group] = field(default_factory=list)   # T7 — the DECISION forest, a 4th `Group`
                                     # forest beside capabilities/subsystems/subdomains. A block
                                     # groups rules the way a capability groups use cases; its
                                     # `purpose` carries the "what this area decides" line. Group's
                                     # `happy_path` and `tech` stay capability-/subsystem-only
                                     # (validate).
    rules: list[BusinessRule] = field(default_factory=list)  # the decisions themselves
    extras: list[ExtraSection] = field(default_factory=list)


# The element arrays that DEFINE ids, with each one's required prefix. `S` must not match `SD` (both
# start with "S"), so validation matches the WHOLE id against ID_SHAPE and then the exact prefix.
# `entry_points` is deliberately ABSENT: its ids are minted by `assemble` from content (see
# EntryPoint.id), so a fragment carries none and there is nothing for the load-time shape check —
# or the merge-time duplicate-id check — to read. Registering it would turn every pre-assembly
# fragment into a shape error and every post-assembly rebuild into a false duplicate.
ID_ARRAYS: dict[str, str] = {
    "use_cases": "UC", "happy_path": "HP", "capabilities": "CAP", "subsystems": "S",
    "components": "C", "deps": "D", "subdomains": "SD", "entities": "E", "roles": "R",
    "subflows": "SF", "blocks": "BLK", "rules": "BR", "interfaces": "I",
}


def expanded_steps_with_container(m: ProjectModel, f: Flow) -> list[tuple[str, FlowStep]]:
    """Each expanded step paired with the id of the container that AUTHORED it — the flow's own
    `uc`, or the `SFn` a reference step expanded to.

    `(container, n)` is the ONLY unique step identity. `validate` enforces a unique `n` per flow
    and per sub-flow SEPARATELY, so after expansion two different steps legitimately share an `n`
    under one use case: this repo's own map has 462 anchored expanded steps, 462 distinct
    `(uc, container, n)` keys — and only 337 distinct `(uc, n)` keys. The impact engine already
    keys steps this way (`step:<uc|sf>:<n>`, impact_lib); anything that identifies an expanded step
    by `(uc, n)` alone silently merges two rows into one, keeping one row's phrase and the OTHER
    row's endpoints."""
    sfs = {sf.id: sf for sf in m.subflows}
    out: list[tuple[str, FlowStep]] = []
    for st in f.steps:
        sf = sfs.get(st.subflow or "")
        if sf is None or not sf.steps:
            out.append((f.uc, st))
        else:
            out.extend((sf.id, s) for s in sf.steps)
    return out


def expanded_flow_steps(m: ProjectModel, f: Flow) -> list[FlowStep]:
    """The flow's steps with each sub-flow REFERENCE step replaced inline by the referenced
    sub-flow's steps — the model-level analog of the viewer's graph-level expansion
    (gen_viewer.expanded_steps). Consumers that reason about "what this flow touches" (impact
    ripple, the model audit) walk THIS, so content inside a sub-flow is never invisible.
    An unresolved or empty reference degrades to the bare reference step."""
    return [st for _container, st in expanded_steps_with_container(m, f)]


@dataclass(frozen=True)
class UseCaseReach:
    """The interfaces ONE use case's flow reaches, and which of them only from inside a sub-flow."""
    interfaces: frozenset[str]
    via_subflow_only: frozenset[str]


def use_case_interfaces(m: ProjectModel) -> dict[str, UseCaseReach]:
    """THE ONE RULE for "this use case reaches this interface": a step of its flow is drawn AT the
    surface, or at a DEP the surface stands on. Sub-flows are EXPANDED, and the rule remembers which
    surfaces came only from inside one, so a board can chip them as the sub-flow's.

    Nothing else decides it. A use case's authored `entry_points` used to be a third arm — "the use
    case names one of the surface's ways in" — in three derivations, while the viewer's use case
    cards read the flow alone. Measured on the 2026-09-07 mcpolis map, that arm added 5 links no
    flow drew: the
    prospect's first use case put the Dashboard at happy-path step 1, because two backend routes
    filed under the Dashboard were listed on it. Every derivation that answers "which use cases
    reach an interface", "where does the walk first reach it", "who stands at it" or "which
    features come through it" reads THIS, and so does the viewer (the bundle ships it), so none of
    them can drift from the others or from the cards. The authored list keeps its other job: the
    gates compare it with the flows (an opening the flow owes, an interface no use case names)."""
    iface_ids = {i.id for i in m.interfaces}
    dep_iface: dict[str, list[str]] = {d.id: list(d.interfaces) for d in m.deps if d.interfaces}
    direct: dict[str, set[str]] = {}
    inside: dict[str, set[str]] = {}
    for fl in m.flows:
        for container, st in expanded_steps_with_container(m, fl):
            hit: set[str] = set()
            for end in (st.src, st.dst):
                if end in iface_ids:
                    hit.add(end)
                hit.update(i for i in dep_iface.get(end, ()) if i in iface_ids)
            (direct if container == fl.uc else inside).setdefault(fl.uc, set()).update(hit)
    out: dict[str, UseCaseReach] = {}
    for uc in set(direct) | set(inside):
        d, s = direct.get(uc, set()), inside.get(uc, set())
        if d or s:
            out[uc] = UseCaseReach(interfaces=frozenset(d | s), via_subflow_only=frozenset(s - d))
    return out


def is_saved(e: Entity) -> bool:
    """Does this codebase SAVE a record of the entity — a row of its own, or one inside a parent's?

    The eligibility filter for everything ownership: a data AREA is an area of saved records, so
    plumbing and value shapes (a request object, an enum, a read projection) never become a box on
    the Features page and never pull an ownership question that has no answer. `store.mode` is the
    one derived ownership signal that measured reliable; see `grammar.STORE_MODES_SAVED`."""
    return e.store is not None and (e.store.mode or "").strip() in grammar.STORE_MODES_SAVED


#: An entity id INSIDE a field's type — matched whole, so `E1` never matches inside `E10`.
_ENTITY_REF_IN_TYPE = re.compile(r"\bE\d+\b")
#: The relation verbs that mean "this record HOLDS that one". Three spellings of one idea, and they
#: are all in the live maps.
_CONTAINMENT_VERBS = ("contains", "embeds", "has")


def record_parents(m: ProjectModel) -> dict[str, list[str]]:
    """Per entity, the entities that HOLD it — the one answer to "which record is this one inside".

    TWO ARMS, because a map states containment two ways and both are load-bearing:
    a relation whose verb is one of `contains`/`embeds`/`has`, and a FIELD whose type names the
    entity's id. `views._embedded_homes` walked exactly this to find where a nested value physically
    lands; the saved-record rule needs the same walk to ask which stories reach it. They were written
    twice with different definitions — one verb versus three, no field arm versus one — which is two
    answers to one question, so this is now the only one.

    Not transitive: callers walk it themselves, and must carry a `seen` set. Containment is authored,
    and nothing stops two records naming each other."""
    ents = {e.id for e in m.entities}
    parents: dict[str, list[str]] = {}
    for owner in m.entities:
        for f in owner.fields:
            for ref in _ENTITY_REF_IN_TYPE.findall(f.type or ""):
                if ref in ents and owner.id not in parents.setdefault(ref, []):
                    parents[ref].append(owner.id)
        for r in owner.relations:
            if r.target in ents and (r.verb or "").strip().lower() in _CONTAINMENT_VERBS:
                if owner.id not in parents.setdefault(r.target, []):
                    parents[r.target].append(owner.id)
    return parents


def subdomain_owners(m: ProjectModel) -> dict[str, list[str]]:
    """The EFFECTIVE owning feature(s) of every sub-domain: its own authored `owners`, else the
    nearest authored answer walking up `parent`. A sub-domain absent from the result is one nobody
    decided anywhere up its chain.

    Ids that name no defined capability are dropped here rather than passed on — `validate` reports
    the dangling entry as a shape error, and no screen should draw an owner box that has no feature.
    A `parent` cycle (a shape error of its own) stops the walk instead of hanging."""
    subs = {g.id: g for g in m.subdomains}
    cap_ids = {c.id for c in m.capabilities}
    out: dict[str, list[str]] = {}
    for sid in subs:
        chain: list[str] = []
        answer: list[str] = []
        cur: str | None = sid
        seen: set[str] = set()
        while cur and cur in subs and cur not in seen:
            if cur in out:
                answer = out[cur]
                break
            seen.add(cur)
            chain.append(cur)
            g = subs[cur]
            if g.owners:
                answer = [o for o in g.owners if o in cap_ids]
                break
            cur = g.parent
        for c in chain:
            out[c] = answer
    return {k: v for k, v in out.items() if v}


def entity_owners(m: ProjectModel) -> dict[str, list[str]]:
    """The EFFECTIVE owning feature(s) of every entity: its own authored `owners` when it has them,
    else its sub-domain's (`subdomain_owners`, which already walked up `parent`). An entity absent
    from the result is one nobody decided for.

    ONE implementation, because three consumers ask it — `validate`'s cross-examination, the feature
    derivation the Features page draws, and the entity page's "Owned by" line. Two of them computing
    the inheritance separately is how the same map answers the same question two ways."""
    cap_ids = {c.id for c in m.capabilities}
    areas = subdomain_owners(m)
    out: dict[str, list[str]] = {}
    for e in m.entities:
        own = ([o for o in e.owners if o in cap_ids] if e.owners
               else areas.get(e.subdomain or "", []))
        if own:
            out[e.id] = own
    return out


def group_forests(m: ProjectModel) -> list[Group]:
    """Every `Group` in the model, across ALL FOUR forests (subsystems, subdomains, capabilities,
    blocks), in canonical order.

    One dataclass backs four id spaces, and every consumer that walks "the groups" was hand-writing
    `(*m.subsystems, *m.subdomains)` — which is how capability `source` anchors went unchecked by
    `validate` for a whole release, and how a per-kind field guard silently legalises the field in
    whatever forest the tuple forgot. Adding a forest must be one edit here, not eight in five
    files."""
    return [*m.subsystems, *m.subdomains, *m.capabilities, *m.blocks]


def all_elements(m: ProjectModel) -> dict[str, object]:
    """Every DEFINED element keyed by id, in document order (later duplicates keep the first —
    duplicate ids are a validate_model problem, not a load problem)."""
    out: dict[str, object] = {}
    for attr in ID_ARRAYS:
        for el in getattr(m, attr):
            out.setdefault(el.id, el)
    return out


# ── element-id remap (the mutable twin of validate_model._referenced_ids) ─────────────────────────

_BRACKET_REF = re.compile(r"\[\[([^\]]+)\]\]")


def _map_strings(value: object, fn) -> None:
    """Apply `fn` to every `str` in a dataclass / list / dict tree, in place."""
    if hasattr(value, "__dataclass_fields__"):
        for f in fields(value):  # type: ignore[arg-type]
            v = getattr(value, f.name)
            if isinstance(v, str):
                setattr(value, f.name, fn(v))
            else:
                _map_strings(v, fn)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            if isinstance(v, str):
                value[i] = fn(v)
            else:
                _map_strings(v, fn)
    elif isinstance(value, dict):
        for k in list(value.keys()):
            v = value[k]
            if isinstance(v, str):
                value[k] = fn(v)
            else:
                _map_strings(v, fn)


def _remap_str_ids(text: str, remap: dict[str, str]) -> str:
    """Rewrite whole id TOKENS in a dedicated id-bearing string field (an FK marker `FK→E7`, an
    entity-typed field `auth:E7`, a role's `drives` cell) — never arbitrary prose."""
    if not text:
        return text
    return grammar.ID_TOKEN.sub(lambda mo: remap.get(mo.group(0), mo.group(0)), text)


def remap_element_ids(m: ProjectModel, remap: dict[str, str]) -> None:
    """Rewrite every REFERENCE to a remapped element id, in place — the mutable twin of
    `validate_model._referenced_ids`. When a merge collapses one element id into another (assemble's
    cross-slice component dedup, or a `fix` verb), the merged-away id must not survive anywhere it was
    referenced, or `validate` blocks on a dangling reference. This rewrites references ONLY; it never
    touches an element's own defining `id` (the caller drops the merged-away definition). Kept
    field-for-field in step with `_referenced_ids` so the read and the write can't drift — a regression
    test (`test_remap_covers_referenced_ids`) fails if a new reference site is added to one and not the
    other."""
    if not remap:
        return

    def r(x: str) -> str:
        return remap.get(x, x)

    for g in m.happy_path:
        if g.uc:
            g.uc = r(g.uc)
    for steps in [f.steps for f in m.flows] + [sf.steps for sf in m.subflows]:
        for st in steps:
            st.src = r(st.src)
            st.dst = r(st.dst)
            if st.subflow:
                st.subflow = r(st.subflow)
    for e in m.edges:
        e.src = r(e.src)
        e.dst = r(e.dst)
    for ep in m.entry_points:
        comp = ep.component.strip()
        if comp in remap:
            ep.component = remap[comp]
    for mr in m.messaging:
        if mr.broker:
            mr.broker = r(mr.broker)
        mr.publishers = [r(c) for c in mr.publishers]
        mr.consumers = [r(c) for c in mr.consumers]
        if mr.payload:
            mr.payload = r(mr.payload)
    # An interface REFERENCES two id families, and both can be merged away: entry points as its ways
    # in, entities in a crossing. (`party_ref` held a third and was removed: its dependency half was
    # already stated from the dep's own `interfaces` list, and its actor half is now DERIVED.)
    # `_merge_duplicate_deps` long carried the comment "edges are the only refs into a dep id", which
    # stopped being true the moment a dep could name a surface and a surface could name a dep.
    for iface in m.interfaces:
        iface.ways_in = [r(ep) for ep in iface.ways_in]
    for d in m.deps:
        d.interfaces = [r(i) for i in d.interfaces]
    for en in m.entities:
        if en.subdomain:
            en.subdomain = r(en.subdomain)
        if en.store and en.store.dep:
            en.store.dep = r(en.store.dep)
        for rel in en.relations:
            if rel.target:
                rel.target = r(rel.target)
        for fld in en.fields:
            fld.type = _remap_str_ids(fld.type, remap)
            fld.markers = [_remap_str_ids(mk, remap) for mk in fld.markers]
    for role in m.roles:
        role.drives = _remap_str_ids(role.drives, remap)
    for tr in m.tests:
        tr.targets = [r(t) for t in tr.targets]
    for blk in m.blocks:
        if blk.parent:
            blk.parent = r(blk.parent)
    for br in m.rules:
        if br.block:
            br.block = r(br.block)

    def _brackets(s: str) -> str:
        return _BRACKET_REF.sub(
            lambda mo: f"[[{remap[mo.group(1).strip()]}]]" if mo.group(1).strip() in remap else mo.group(0),
            s,
        )

    _map_strings(m, _brackets)


# ── deterministic serializer ─────────────────────────────────────────────────────────────────────

def _plain(value: object) -> object:
    """A dataclass tree as plain JSON values, keys in dataclass field order (deterministic).
    `extra` dicts are emitted with sorted keys so authored-column order can never wobble a diff."""
    if hasattr(value, "__dataclass_fields__"):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}  # type: ignore[arg-type]
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(value[k]) for k in sorted(value)}
    return value


def to_canonical_json(m: ProjectModel) -> str:
    """The one serialization: fixed key order, indent=2, no ASCII-escaping, trailing newline.
    Same model → byte-identical output, so the committed source diffs cleanly."""
    return json.dumps(_plain(m), indent=2, ensure_ascii=False) + "\n"


# ── structural loader (the schema-validation half of `coyomap validate`) ─────────────────────────

def _check(value: object, hint: object, path: str) -> object:
    """Validate `value` against a type hint, returning the built (dataclass-ified) value.
    Handles exactly the shapes the model uses: str, int, bool, X|None, list[T], dict[str,str],
    and nested dataclasses. Raises ModelError with the JSON path of the first violation."""
    origin = get_origin(hint)
    if origin is Union or origin is types.UnionType:  # only `X | None` appears in the model
        args = [a for a in get_args(hint) if a is not type(None)]
        if value is None:
            return None
        return _check(value, args[0], path)
    if hint is str:
        if not isinstance(value, str):
            raise ModelError(f"{path}: expected a string, got {type(value).__name__}")
        return value
    if hint is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ModelError(f"{path}: expected an integer, got {type(value).__name__}")
        return value
    if hint is bool:
        if not isinstance(value, bool):
            raise ModelError(f"{path}: expected a boolean, got {type(value).__name__}")
        return value
    if origin is list:
        if not isinstance(value, list):
            raise ModelError(f"{path}: expected an array, got {type(value).__name__}")
        (item_hint,) = get_args(hint)
        return [_check(v, item_hint, f"{path}[{i}]") for i, v in enumerate(value)]
    if origin is dict:
        if not isinstance(value, dict):
            raise ModelError(f"{path}: expected an object, got {type(value).__name__}")
        _key_hint, val_hint = get_args(hint)
        if val_hint is object:  # `extra`: any JSON value is welcome (str/number/bool/null/list/dict)
            return {str(k): _check_json_value(v, f"{path}.{k}") for k, v in value.items()}
        return {str(k): _check(v, val_hint, f"{path}.{k}") for k, v in value.items()}
    if hasattr(hint, "__dataclass_fields__"):
        return _build(value, hint, path)  # type: ignore[arg-type]
    raise ModelError(f"{path}: unsupported schema type {hint!r}")  # unreachable on the fixed model


def _check_json_value(value: object, path: str) -> object:
    """Any JSON value, validated recursively (dict keys coerced to str). Defensive: everything the
    loader sees came out of json.loads, but fragments built in-process must obey the same shape."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_check_json_value(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, dict):
        return {str(k): _check_json_value(v, f"{path}.{k}") for k, v in value.items()}
    raise ModelError(f"{path}: not a JSON value ({type(value).__name__})")


#: Fields this schema has RENAMED, so the error can say what to do instead of only what is wrong.
#: NOT a compatibility shim — the old key is still rejected, the map still has to be edited (this is
#: an alpha format, and CONTRIBUTING says treat generated maps as disposable). What this buys is that
#: an operator holding a map written last week reads one line and knows the fix, instead of grepping
#: the schema for a field that no longer exists.
_RENAMED_FIELDS: dict[str, str] = {"claims_grounded": "claims_challenged",
                                   "label": "happy_path"}
#: Fields that were REMOVED outright, with the reason and what to do instead. Separate from
#: `_RENAMED_FIELDS` because there is no new name to point at, and a bare "unknown field" on a map
#: authored last week is a worse answer than a sentence saying why the field went.
_REMOVED_FIELDS: dict[str, str] = {
    "party_ref": ("It held either an `Rn` or a `Dn` in one slot, and BOTH of its jobs are covered "
                  "elsewhere. The dependency half was already stated twice — the dep points UP at "
                  "the surface through its own `interfaces` list, which is the direction every "
                  "other membership in this model runs — so an interface's dependencies are now "
                  "DERIVED. The actor half is now DERIVED too, from the walks, gated on the "
                  "surface's `kind`. Delete the field; the far side is now the roles the walks put at "
                  "the surface, plus the dependencies standing on it."),
    "party": ("Free text for the far side, and after the doors rule landed not one value earned "
              "its place. Measured over the 15 values on the two live maps: 14 repeat a neighbour "
              "— a dependency standing on the surface, or a role the walks now put at it — and the "
              "fifteenth restates its own row's `what`. Delete the field. Anything it said that no "
              "neighbour says belongs in `what`, which is the row's own sentence."),
    "carries": ("One sentence per direction saying what crossed a surface, authored beside the walk "
                "steps and checked against nothing. WHAT CROSSES IS THE WALK STEPS NOW, and each of "
                "them carries its own `direction`. Measured on the two live maps before removal: "
                "the sentence repeated the steps (66% of its words at the surfaces with the richest "
                "walks, and 4 rows were word-for-word copies of one step); its record list held 68 "
                "references of which 2 were a real independent stored record, the rest wire shapes, "
                "embedded parts and computed views; and one of its genuinely-new facts was a claim "
                "nothing in the map backed, which is what an unanchored sentence attracts. Delete "
                "the field and put `direction` on the steps drawn at the surface. An earlier "
                "removal WITHOUT the step direction was reverted, and that is the difference."),
}
_RENAME_NOTES: dict[str, str] = {
    "label": ("It was a THREE-value word (core | supporting | platform) carrying two questions at "
              "once, and two of its values had no definition anywhere. Split them: `happy_path` "
              "(expected | excluded) on the CAPABILITY says whether the walk must reach it, and "
              "`audience` (user | internal) on the ROLE says which side it is on — a capability's audience is "
              "derived from its actors. Old value → new: core → happy_path 'expected'; supporting / "
              "platform → 'excluded' UNLESS a walk step already reaches it, in which case "
              "'expected'. There is no mechanical rule for the audience half; read the roles."),
    "claims_grounded": ("It counted claims that got a VERDICT, which read as 'held up' and let a map "
                        "record total 399 / grounded 399 / refuted 3. Rename it, and add the verdict "
                        "split `claims_confirmed` / `claims_unverifiable` — validate blocks unless "
                        "confirmed + refuted + unverifiable == challenged."),
}


def _build(data: object, cls: type, path: str):
    if not isinstance(data, dict):
        raise ModelError(f"{path}: expected an object, got {type(data).__name__}")
    hints = get_type_hints(cls)
    kwargs: dict[str, object] = {}
    known = {f.name for f in fields(cls)}
    for key in data:
        if key not in known:
            hint = _RENAMED_FIELDS.get(key)
            gone = _REMOVED_FIELDS.get(key)
            raise ModelError(f"{path}.{key}: unknown field"
                             + (f" — renamed to `{hint}`. {_RENAME_NOTES[key]}" if hint else "")
                             + (f" — REMOVED. {gone}" if gone else ""))
    for f in fields(cls):
        if f.name in data:
            kwargs[f.name] = _check(data[f.name], hints[f.name], f"{path}.{f.name}")
        # an absent field takes its dataclass default; a missing REQUIRED field (no default)
        # surfaces as the TypeError below, reported with this path
    try:
        return cls(**kwargs)  # missing REQUIRED fields (no default) raise TypeError
    except TypeError as e:
        raise ModelError(f"{path}: {e}") from e


def _normalize_variants(data: object) -> None:
    """Backward-compat pre-pass: the just-shipped maps store `deployment[].variants` as a list of bare
    environment STRINGS (`["cloud"]`); the current model types it `list[VariantTag]`. Rewrite each bare
    string element `s` → `{"env": s}` in place BEFORE `_build`, so an old map loads as
    `VariantTag(env=s, source="")` (inferred). A localized coercion, not a `_build` union hook: a
    `list[VariantTag | str]` type does NOT work — `_check`'s Union branch only handles `X | None`, so a
    bare string element is rejected. Any element that is neither a str nor a dict is left untouched for
    `_build` to report with its exact JSON path."""
    if not isinstance(data, dict):
        return
    deployment = data.get("deployment")
    if not isinstance(deployment, list):
        return
    for row in deployment:
        if not isinstance(row, dict):
            continue
        variants = row.get("variants")
        if not isinstance(variants, list):
            continue
        row["variants"] = [{"env": v} if isinstance(v, str) else v for v in variants]


def _normalize_subflow_title(data: object) -> None:
    """Alias pre-pass: `Flow` names its display text `title`, `SubFlow` names it `name` — and five
    trace agents in one live rebuild wrote `subflows[].title` by analogy with the flow shape they'd
    just authored, each failing a lint round on `unknown field`. Accept `title` as an alias
    (rewritten to `name` before `_build`; `name` stays canonical — renaming the field would break
    the three maps rebuilt with it today). Applied by BOTH `load_model` and fragment loading."""
    if not isinstance(data, dict):
        return
    subflows = data.get("subflows")
    if not isinstance(subflows, list):
        return
    for row in subflows:
        if isinstance(row, dict) and "title" in row and "name" not in row:
            row["name"] = row.pop("title")


def _reject_legacy_store(data: object) -> None:
    """The `entities[].store` retype (free string → Store object) is a HARD break, no coercion —
    but the generic `_build` error ("expected an object, got str") would leave the reader guessing.
    Raise a targeted message instead, so a pre-retype map says exactly what happened and what to do.
    (Empty string is tolerated as "not stated" → dropped to null, since serializers never emitted a
    meaningful `""`.)"""
    if not isinstance(data, dict):
        return
    entities = data.get("entities")
    if not isinstance(entities, list):
        return
    for i, row in enumerate(entities):
        if not isinstance(row, dict):
            continue
        store = row.get("store")
        if store == "":
            row["store"] = None
        elif isinstance(store, str):
            raise ModelError(
                f"$.entities[{i}].store: '{store}' — `store` is now a structured object "
                '({"dep": "Dn", "container": "...", "mode": "...", "notes": "..."}), not free '
                "text. Rebuild the map with the current method, or migrate the row.")


def access_rules(m: ProjectModel) -> list[BusinessRule]:
    """The map's ACCESS SURFACES — the rules the T7 fold made the single home for auth.

    One reader, because "what is this map's access surface" is now asked in five places (the audit's
    theme routing, validate's inventory, its granularity advisory, finalize's shape line and the
    rendered Security & auth table) and it was being re-derived at each of them. `security[]` is
    legacy storage and is NOT counted here: a map built before the fold still renders its rows, but
    the surface a new map states is its access rules."""
    return [r for r in m.rules if r.access]


def load_model(text: str) -> ProjectModel:
    """Parse + structurally validate a project-map.json document. Raises ModelError on any shape
    violation (bad JSON, wrong type, unknown field, missing required field, wrong id prefix)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ModelError(f"not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ModelError("top level: expected an object")
    fmt = data.get("format")
    if fmt != FORMAT:
        hint = f": {RENAME_HINT}" if fmt == OLD_FORMAT else ""
        raise ModelError(f"format: expected '{FORMAT}', got {fmt!r}{hint}")
    _normalize_variants(data)
    _normalize_subflow_title(data)
    _reject_legacy_store(data)
    m = _build(data, ProjectModel, "$")
    for attr, prefix in ID_ARRAYS.items():
        for i, el in enumerate(getattr(m, attr)):
            eid = el.id
            good = bool(ID_SHAPE.match(eid)) and re.match(r"[A-Z]+", eid).group(0) == prefix  # type: ignore[union-attr]
            if not good:
                raise ModelError(f"$.{attr}[{i}].id: '{eid}' is not a valid {prefix}-id "
                                 f"(a schema id is the prefix + digits only, e.g. {prefix}3)")
    return m


#: The coyomap clone this code is running from — `<COYOMAP_HOME>/tools/coyomap/model.py`.
COYOMAP_HOME = Path(__file__).resolve().parents[2]


class WrongMapError(ValueError):
    """A verb was about to read the coyomap clone's OWN map by accident.

    Its own class so `cli.py` can catch exactly this and print it as one line. A bare `ValueError`
    could not be caught there without swallowing every other one, and `ModelError` subclasses
    `ValueError` too — so a dozen `main`s each grew (or, mostly, did not grow) their own handler and
    the refusal arrived as a ten-line traceback with the message at the bottom. A refusal whose
    entire value is that a person reads it must not look like a crash."""


def guard_wrong_map(path) -> Path:
    """The refusal alone, with no `reading` line — for a WRITE.

    `assemble` is the only verb that writes a map, and overwriting the clone's own is the
    destructive half of the accident `resolve_map_path` guards the reads against. Same rule, same
    escape; it just is not a read, so it must not say it is reading."""
    resolved = Path(path).resolve()
    if os.environ.get("COYOMAP_SELF_MAP", "") in ("1", "true", "yes"):
        return resolved
    try:
        resolved.relative_to(COYOMAP_HOME / ".coyomap")
    except ValueError:
        return resolved
    raise WrongMapError(
        f"refusing to WRITE {resolved} — that is the coyomap clone's OWN map, and this shell is "
        f"standing in {Path.cwd()}. A build that reached it by accident after a `cd` overwrote the "
        f"clone's committed map. If you really are mapping coyomap itself, set COYOMAP_SELF_MAP=1.")


def resolve_map_path(path) -> Path:
    """The absolute path a verb is about to read, refusing the one slip nothing downstream can see.

    THE SLIP. A build runs the coyomap CLI by absolute path while its shell folder drifts into the
    clone. A RELATIVE `.coyomap/project-map.json` then resolves against the clone, and the verb
    reads COYOMAP'S OWN self-map: it succeeds, it prints a healthy result, and the result is about
    the wrong product. It has now happened on two consecutive builds. The 2026-09-01 argus build
    ran `validate` that way and got "7 of 74 isolated entities" in coyomap's vocabulary; the
    2026-09-02 mcpolis build went further and EDITED the clone's committed map. `git status` in the
    analyzed repo shows nothing either time, because nothing happened there.

    THE RULE: reading the clone's own `.coyomap/` is refused unless `COYOMAP_SELF_MAP=1` is set.
    Coyomap DOES map itself, and that run is deliberate — setting one environment variable is the
    whole cost of saying so, once per session. An accident cannot set it, which is the point: the
    thing that moved was the shell folder, not anyone's intent.

    An absolute path is NOT treated as proof of intent. It was the first rule tried and it is
    wrong: the mcpolis build reached the clone's map through absolute paths too, having composed
    them from a `cd`-ed shell.

    It also PRINTS what it resolved, on stderr so a `--json` consumer is untouched. A verb that
    names the file it read makes the next slip visible in the transcript instead of invisible."""
    resolved = Path(path).resolve()
    if os.environ.get("COYOMAP_SELF_MAP", "") not in ("1", "true", "yes"):
        try:
            resolved.relative_to(COYOMAP_HOME / ".coyomap")
        except ValueError:
            pass
        else:
            raise WrongMapError(
                f"refusing to read {resolved} — that is the COYOMAP CLONE'S OWN map, and this "
                f"shell is standing in {Path.cwd()}. Two builds in a row reached it by accident "
                f"after a `cd` into the clone, read a healthy-looking result about the wrong "
                f"product, and one of them edited it. If you really are mapping coyomap itself, "
                f"set COYOMAP_SELF_MAP=1.")
    print(f"reading {resolved}", file=sys.stderr)
    return resolved


def load_model_path(path) -> ProjectModel:
    """`load_model` from a file path (the common CLI entry)."""
    return load_model(resolve_map_path(path).read_text(encoding="utf-8"))
