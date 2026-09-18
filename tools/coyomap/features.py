#!/usr/bin/env python3
"""Derived: everything the map already knows about each FEATURE, gathered from where it is stored.

A feature (a capability) is a LABEL today. Its use cases carry it, and nothing else does — so
"what does Billing & credits do, decide, know and run on?" is answered by reading four other views
and joining them by hand. This module does that join once, from the stored map, and stores nothing.

DERIVED, NEVER AUTHORED, for the same reason a rule's components and sweep state are derived: an
authored "this feature touches these entities" is unfalsifiable, and a hand-assigned list rendered
as derived was the rules prototype's most damaging failure — it looked correct on every screen.

ONE EXCEPTION, and it is named where it is built: `FeatureFacts.rules`. A feature's rules are the ones
in the decision areas SPECIFIED UNDER it, which is authored. The derived answer to a NEARBY question —
which rules the feature's own flows run into — is still computed below and still feeds the coverage
line; it simply is not what the feature page calls "What it decides". Two true numbers under one word
is what this change ends: on mcpolis one feature's join said 12 and its areas hold 16.

THE RULE JOIN IS REUSED, NOT REINVENTED. `validate_model.rule_steps` already answers "which
use-case steps does this rule\'s sites reach", with the exact-line and same-function strengths the
Rules view renders. This module walks from those steps to the use case to its feature. A second
implementation would drift from the Rules view, and the two screens would then disagree about what
one rule governs.

The obvious join — through the COMPONENT holding the site — was measured and rejected. On two live
maps (Meerbot 61 rules, mcpolis 66) it reached 92-98% of rules and named a single feature for only
10-28% of them, because a component is shared and a rule smears across most of the product. The
step join reaches about half the rules and names one feature four times out of five.

WHAT DOES NOT JOIN IS A FINDING, not a hole to paper over. The unjoined rules on both maps are the
DEEPEST logic in each product (`policy_engine.py`, `settings_resolver.py`, `reader_runner.py`): a
flow step anchors at the call BETWEEN two components, a rule anchors INSIDE the decision function one
level down, so the two are recorded at different depths and never meet. `Coverage.rules_unjoined`
carries that count so a reader is told, rather than shown a feature's rules as if they were all of
them.

Stdlib-only (the cli.py firewall). Everything it needs already exists: `expanded_flow_steps` (so
content inside a sub-flow is never invisible), `rule_steps` + `anchored_flow_steps` for the join,
`impact_git.load_map_extents` for the pre-index table, and `parse_anchor` for a site's file.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from coyomap import grammar
from coyomap.anchors import parse_anchor
from coyomap.impact_git import Extents
from coyomap.areas import DataArea, build_areas, build_record_areas, sorted_ids
from coyomap.model import (ProjectModel, UseCaseReach, entity_owners, expanded_flow_steps,
                           use_case_interfaces)
from coyomap.validate_model import (
    anchored_flow_steps,
    capability_audience,
    interface_actor_use_cases,
    interface_directions,
    interface_steps_by_use_case,
    interface_use_cases,
    interface_walk_order,
    rule_steps,
)


@dataclass(frozen=True)
class FeatureFacts:
    """One feature, with every part of the map that belongs to it.

    Ids, not objects: the caller already holds the model and renders names from it, and a list of
    ids serialises into the viewer bundle unchanged."""
    id: str
    name: str
    purpose: str = ""
    # `happy_path` is deliberately NOT carried: it is an authoring decision the Coverage rule reads,
    # and no view draws it, so shipping it would be a field nothing consumes.
    audience: list[str] = field(default_factory=list)        # user and/or internal — DERIVED from the
                                                             # roles driving its use cases, never
                                                             # authored, so the two cannot disagree.
                                                             # A SET: a surface both sides act in
                                                             # honestly carries both words
    roles: list[str] = field(default_factory=list)           # who drives its use cases
    use_cases: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)    # how you reach it
    #: WHICH WAY THE DATA MOVES on this feature's steps that touch a record: `in` it reads, `out` it
    #: stores, both when it does each somewhere. Read off `FlowStep.direction`, which the map already
    #: carries; derived here rather than in the browser so the page states it without a second
    #: reader. The feature page's data sentence is worded from it — a fixed "stores and reads"
    #: overstated 1 of the two live maps' 13 features (mcpolis's Audit trail only ever reads).
    data_directions: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)           # what it decides (specified_under)
    entities: list[str] = field(default_factory=list)        # what it knows about
    components: list[str] = field(default_factory=list)      # what implements it
    areas: list[str] = field(default_factory=list)           # the data areas its walks reach — a
                                                             # projection of `FeatureIndex.areas`,
                                                             # not a second derivation
    reached_through: list[str] = field(default_factory=list)  # In — the surfaces this feature is
                                                             # entered by, via its use cases' ways in
    reaches_out: list[str] = field(default_factory=list)      # In — the surfaces it calls OUT to.
                                                             # ONLY from a walk step drawn AT the
                                                             # dep: the component-shared inference
                                                             # ("this feature uses code that
                                                             # somewhere calls the payment
                                                             # processor") would wire nearly every
                                                             # feature to nearly every service —
                                                             # there are 24/41/32/102 such edges on
                                                             # the four live maps


@dataclass(frozen=True)
class Coverage:
    """How much of the map the feature layer accounts for. Every number is a count of named things,
    so a reader can always ask which ones."""
    components_total: int = 0
    components_in_a_flow: int = 0          # a use-case walk passes through it
    components_in_a_rule: int = 0          # a decision is enforced in it
    components_unreached: list[str] = field(default_factory=list)   # neither — named, not counted
    rules_total: int = 0
    rules_joined: int = 0
    rules_unjoined: int = 0                # enforced where no use-case walk passes
    entry_points_total: int = 0
    entry_points_named: int = 0            # named by some use case
    use_cases_total: int = 0
    use_cases_without_feature: int = 0


@dataclass(frozen=True)
class StoryEdge:
    """One actor→feature arrow of the Features diagram: a distinct (actor, capability) pair across
    the use cases, labelled with the actor's STAKE in that feature."""
    actor: str            # Rn
    feature: str          # CAPn
    label: str            # the authored stake, or the fallback derived from the pair's use cases
    authored: bool        # True when `label` is an authored `stakes[]` entry
    step: str | None      # HPn — the first happy-path step exercising this pair; None when the
                          # walk never does (the label then explains instead of navigating)


@dataclass(frozen=True)
class Story:
    """The story diagram's data: ONE column holding every feature, the cast, and the edges.

    ALL ORDERS ARE DERIVED HERE, deterministically, never layout-computed in the browser:
    `spine` is the on-path features by their FIRST happy-path touch (a feature touched at several
    moments appears once, at its first); `off` is every feature the walk never touches, in map
    order — the classification, never a column of its own. No screen draws it today: the trailing
    block in `column` is where an off feature reads, and `off` survives for callers that need the
    SET rather than the order;
    `column` is the one merged order every screen draws: the spine unbroken, then the off features
    in a block after it, each at its authored story anchor, or at the derived fallback (its actors'
    last walk step), or at the end — an off feature stays among the walk only when a `before` anchor
    leaves it no choice (see _story_column); `cast` is every role by the first step it drives, roles
    driving none last, in map order."""
    spine: list[str] = field(default_factory=list)      # CAPn, first-touch order
    off: list[str] = field(default_factory=list)        # CAPn, map order — the off-the-walk SET
    column: list[str] = field(default_factory=list)     # CAPn, the one merged story order
    cast: list[str] = field(default_factory=list)       # Rn, order of first appearance
    edges: list[StoryEdge] = field(default_factory=list)


@dataclass(frozen=True)
class InterfaceFacts:
    """One interface, joined to everything the map already knows reaches it.

    Everything here is DERIVED. The map authors the surface, its side, who it faces and what
    crosses; who USES it falls out of the ways in, the deps and the walks — the same rule the rest
    of this module follows, and the reason a hand-assigned "these features use this surface" is not
    a field.

    `directions` is derived rather than authored for the same reason: it is exactly the set of
    directions this surface's own flow steps carry, so a surface cannot claim to send while no story
    sends anything through it.

    IT WAS CALLED `flow`, and that was one word for two ideas: everywhere else in this product a
    flow is a use case's numbered steps (`flows` in the map, `flowsNarr` in the bundle). The field
    never existed in an authored map at all — it is computed here — so a reader who met it in the
    served bundle had every reason to think a surface stores one."""
    id: str
    name: str
    what: str = ""
    side: str = ""
    facing: str = ""
    kind: str = ""                                           # SHAPE — the canonical spelling, so the
                                                             # viewer's icon lookup and the eval read
                                                             # one surface as one
    #: WHO is on the far side. DERIVED, never authored — an authored value beside a derived one is
    #: the failure mode this shape was built to remove. Empty is a REAL ANSWER, not a gap: a crash
    #: reporter has nobody on the far side, and only the two kinds that mean a person goes there
    #: derive anyone on a `theirs` surface.
    actors: list[str] = field(default_factory=list)          # Rn
    #: …and which walks bring each of them here. Same derivation, one grain finer: the Interfaces
    #: page orders the people by where the happy path first reaches them, and lists what each is
    #: here for. Keyed by role id, values are use-case ids.
    actor_use_cases: dict[str, list[str]] = field(default_factory=dict)
    directions: list[str] = field(default_factory=list)      # in and/or out — DERIVED from the steps
    ways_in: list[str] = field(default_factory=list)         # EPn
    deps: list[str] = field(default_factory=list)            # Dn naming this surface
    components: list[str] = field(default_factory=list)      # the code behind it: each way in's
                                                             # owning component, plus the components
                                                             # that call each of its deps
    use_cases: list[str] = field(default_factory=list)       # the walks that come through it
    features: list[str] = field(default_factory=list)        # CAPn, through those use cases
    #: True when NOTHING in the map can say which features use this surface — no way in of its own is
    #: named by a use case, and no walk step touches its deps. The page must then read "not stated"
    #: rather than "none": measured on Meerbot, only 8 of 344 walk steps touch an outside service at
    #: all, so most `theirs` surfaces are legitimately unknowable until the walks say more.
    features_unknown: bool = False
    #: WHAT CROSSES THIS SURFACE: the walk steps drawn at it, each with its own direction. This is
    #: the whole answer now — `interfaces[].carries[]` was removed, and the one fact it held that a
    #: step could not say (which way data goes) is authored on the step itself.
    #:
    #: The walk steps drawn at this surface,
    #: grouped by the story they belong to, in happy-path order. Each entry is
    #: (use case, [(phrase, container, step number, far-side role or "", direction)]).
    #: Every step is GROUNDED — a line in the code a skeptic has already been sent at — which is
    #: what the removed authored rows were not: one of them claimed a credential is "shown exactly
    #: once" and nothing in the map backed it.
    steps: list[tuple[str, list[tuple[str, str, int, str, str]]]] = field(default_factory=list)
    #: WHERE THE WALK FIRST REACHES IT, as a happy-path position, or None for a surface no step of
    #: the walk touches. The picture reads down in this order, which is the same rule `build_story`
    #: gives the features column: first touch, unbroken, then the untouched in a block after it. On
    #: MCP Hero that reads as the product's own story — a prospect reads the public website, signs up
    #: on the dashboard, a member uses the gateway, an operator the console — and it puts the one
    #: staff surface last with no staff rule, because the operator's steps ARE the end of the walk.
    walk_pos: int | None = None
    #: WHO SPEAKS FIRST, so the two directions can be drawn in the order they happen.
    #: A WAY IN is an address or a command that something outside invokes, so a surface holding one
    #: is opened from outside and its `in` is the first move; a surface holding none is one the
    #: product reaches for, so its `out` opens.
    #: Measured against the walk on both live maps: the walk names an initiator for only 5 of the 7
    #: MCP Hero surfaces where the order matters, this rule answers all 11 across the two maps, and
    #: where both speak they AGREE — including the case that is not obvious, where the walk's
    #: `C52 -> I8` says the product sends a person to Google sign-in and the ways-in rule says the
    #: same because Google sign-in holds no way in.
    #: MEANINGLESS ON A ONE-DIRECTION SURFACE, and deliberately not special-cased: with one crossing
    #: there is nothing to order. 3 of coyomap's 11 read `out` while carrying only an `in`, and it
    #: costs nothing because no consumer asks.
    opens: str = "in"


@dataclass(frozen=True)
class FeatureIndex:
    """The whole derivation. `rule_join_uses_extents` is the honesty flag the pages depend on.

    Without the pre-index table the join still runs, but only an EXACT line match links a rule to a
    step, so a feature's rule list is a floor rather than an answer. A page that does not say so
    reports a partial list as the whole one. This mirrors `rule_steps`' own degradation rather than
    inventing a second silence."""
    features: list[FeatureFacts] = field(default_factory=list)
    component_features: dict[str, list[str]] = field(default_factory=dict)
    rule_features: dict[str, list[str]] = field(default_factory=dict)
    role_features: dict[str, dict[str, int]] = field(default_factory=dict)  # role -> feat -> UCs
    unassigned_use_cases: list[str] = field(default_factory=list)
    coverage: Coverage = field(default_factory=Coverage)
    story: Story = field(default_factory=Story)
    areas: list[DataArea] = field(default_factory=list)   # in the order the right column draws them
    areas_are_records: bool = False       # TRUE when the map cut no sub-domain, so each box above is
                                          # one SAVED RECORD rather than a group of them. The column
                                          # then draws touches and never an owner, because ownership
                                          # is authored on a sub-domain and there is none.
    entity_owners: dict[str, list[str]] = field(default_factory=dict)
                                        # record -> its EFFECTIVE owning feature(s): its own
                                        # authored `owners`, else its area's. The entity page's
                                        # "Owned by" line is the field's day-one consumer, so an
                                        # authored owner cannot sit in the map unread.
    interfaces: list[InterfaceFacts] = field(default_factory=list)
    #: Per use case, the interfaces its flow reaches — THE rule (`use_case_interfaces`), shipped so
    #: the viewer's use case cards and boards read it rather than re-deriving it from the steps.
    use_case_interfaces: dict[str, UseCaseReach] = field(default_factory=dict)
    rule_join_uses_extents: bool = False


def _fallback_label(name: str) -> str:
    """A use-case name as an arrow label: the first letter lowered so it reads as a verb phrase
    after the actor's name — unless the first word is ALL CAPS, so an acronym survives (the same
    rule the viewer's `wantsSentence` applies to a role's wants)."""
    s = name.strip()
    if not s:
        return ""
    first = s.split()[0]
    if first == first.upper() and any(c.isalpha() for c in first):
        return s
    return s[0].lower() + s[1:]


def _story_column(m: ProjectModel, spine: list[str], first_cap: dict[str, int],
                  last_actor: dict[str, int]) -> list[str]:
    """The ONE story order: the spine, then the off-walk features, in a block after it.

    The walk reads unbroken. An off feature interrupted it for no gain: walk membership is not
    importance, so the reader paid a break in the story order to learn nothing.

    An off feature's position INSIDE that trailing block, in priority order: its AUTHORED anchor
    (before/after another feature, resolved recursively with a cycle guard — an anchor may name
    another off feature); the DERIVED fallback (after the feature holding its actors' last walk
    step — right for trailing features like ops or a chat variant of walked work, wrong for
    lead-in ones, which is why the anchor exists); else the END, in map order.

    The ONE thing that keeps an off feature among the walk is a `before` anchor it could not
    otherwise honour: a marketing page authored BEFORE the first step has to sit before it, and
    the end of the column is not before anything. Such a feature is PINNED, and so is anything
    authored `after` a pinned one, which keeps an authored lead-in chain together. An `after`
    anchor naming a WALK feature never pins: the end of the column is already after it, so the
    anchor still holds there, and honouring it in place is what used to break the walk.

    Ties (two features anchored to the same spot, or a chain landing on a spine position) break
    walk-features-first, then map order — deterministic, so the same map always draws the same
    column."""
    caps = {c.id: c for c in m.capabilities}
    role_ids = {r.id for r in m.roles}
    map_pos = {c.id: i for i, c in enumerate(m.capabilities)}
    key: dict[str, float] = {c: float(i) for i, c in enumerate(spine)}
    # Each feature's "granularity": how far its OWN dependents sit from it. Halving per link keeps
    # a realistic chain (B after A, A before CAP2) inside the gap its head claimed, whatever order
    # the memoized resolution visits them in. A pathological chain of ~50+ links saturates the
    # floats: past that depth the steps round to zero, the tail ties on one key, and the members
    # fall back to map order — so the chain's own links stop being honoured. Deterministic, and no
    # authored map comes near 50 anchors deep.
    gran: dict[str, float] = {c: 0.5 for c in key}
    cap_roles: dict[str, set[str]] = {c: set() for c in caps}
    for u in m.use_cases:
        if u.capability in caps:
            cap_roles[u.capability].update(a for a in u.actors if a in role_ids)
    uc_by_id = {u.id: u for u in m.use_cases}
    step_cap: list[str | None] = []          # walk position -> the feature its use case belongs to
    for hp in m.happy_path:
        u = uc_by_id.get(hp.uc or "")
        step_cap.append(u.capability if u is not None and u.capability in caps else None)

    def resolve(fid: str, seen: frozenset[str]) -> float | None:
        if fid in key:
            return key[fid]
        if fid in seen:
            return None                       # an anchor cycle: the caller falls back instead
        a = caps[fid].story
        if (a is not None and a.place in ("before", "after")
                and a.feature in caps and a.feature != fid):
            t = resolve(a.feature, seen | {fid})
            if t is not None:
                step = gran.get(a.feature, 0.5)
                key[fid] = t + (step if a.place == "after" else -step)
                gran[fid] = step / 2
                return key[fid]
        steps = [last_actor[r] for r in cap_roles.get(fid, ()) if r in last_actor]
        anchors = [step_cap[i] for i in steps if step_cap[i] is not None]
        if steps and anchors:
            fc = step_cap[max(i for i in steps if step_cap[i] is not None)]
            key[fid] = key[fc] + 0.5 if fc in key else float(len(spine))
        else:
            key[fid] = float(len(spine))     # nothing to hang on: the end, in map order
        gran[fid] = 0.25                     # something anchored to THIS feature sits half as far
        return key[fid]

    for cid in caps:
        resolve(cid, frozenset())

    def pinned(fid: str, seen: frozenset[str]) -> bool:
        """Must this off feature stay among the walk? Only an unhonourable `before` says so."""
        if fid in first_cap or fid in seen:
            return False                      # on the walk (not an off feature), or an anchor cycle
        a = caps[fid].story
        if a is None or a.feature not in caps or a.feature == fid:
            return False
        if a.place == "before":
            return a.feature in first_cap or pinned(a.feature, seen | {fid})
        # `after` a PINNED off feature keeps an authored chain together; `after` a walk feature
        # does not pin, since the trailing block is already after it.
        return a.place == "after" and a.feature not in first_cap and pinned(a.feature, seen | {fid})

    late = {cid: cid not in first_cap and not pinned(cid, frozenset()) for cid in caps}
    return sorted(caps, key=lambda cid: (late[cid], key[cid], cid not in first_cap, map_pos[cid]))


def build_story(m: ProjectModel) -> Story:
    """The story diagram's data, derived from the walk, the use cases and the roles.

    The label of an edge is the actor's authored STAKE when the capability carries one for that
    actor, else the FALLBACK: the pair's first use case's name as a verb phrase. Every existing map
    has no stakes, so the fallback is what most arrows show until the next build authors them."""
    caps = {c.id: c for c in m.capabilities}
    uc_by_id = {u.id: u for u in m.use_cases}
    role_ids = {r.id for r in m.roles}

    first_cap: dict[str, int] = {}          # capability -> its first happy-path touch (position)
    first_actor: dict[str, int] = {}        # role -> the first step it drives
    last_actor: dict[str, int] = {}         # role -> the last step it drives (the fallback anchor)
    pair_step: dict[tuple[str, str], str] = {}   # (actor, capability) -> first HPn exercising it
    for i, hp in enumerate(m.happy_path):
        u = uc_by_id.get(hp.uc or "")
        if u is None:
            continue
        cap = u.capability if u.capability in caps else None
        if cap is not None:
            first_cap.setdefault(cap, i)
        for a in u.actors:
            if a in role_ids:
                first_actor.setdefault(a, i)
                last_actor[a] = i
                if cap is not None:
                    pair_step.setdefault((a, cap), hp.id)

    spine = sorted(first_cap, key=lambda c: first_cap[c])
    off = [c.id for c in m.capabilities if c.id not in first_cap]
    column = _story_column(m, spine, first_cap, last_actor)
    cap_pos = {c: i for i, c in enumerate(column)}

    # Roles in order of appearance; a role driving no step keeps its map position, after the cast.
    role_pos = {r.id: i for i, r in enumerate(m.roles)}
    cast = sorted(role_ids, key=lambda r: (first_actor.get(r, len(m.happy_path) + role_pos[r]),
                                           role_pos[r]))

    stakes = {(c.id, s.actor): s.stake.strip()
              for c in m.capabilities for s in c.stakes if s.stake.strip()}
    pair_first_uc: dict[tuple[str, str], str] = {}   # (actor, capability) -> first UC name, map order
    for u in m.use_cases:
        if u.capability not in caps:
            continue
        for a in u.actors:
            if a in role_ids:
                pair_first_uc.setdefault((a, u.capability), u.name)

    edges = [StoryEdge(actor=a, feature=c,
                       label=stakes.get((c, a)) or _fallback_label(pair_first_uc[(a, c)]),
                       authored=(c, a) in stakes,
                       step=pair_step.get((a, c)))
             for a, c in sorted(pair_first_uc, key=lambda p: (cast.index(p[0]), cap_pos[p[1]]))]
    return Story(spine=spine, off=off, column=column, cast=cast, edges=edges)


def build_index(m: ProjectModel, extents: Extents | None = None) -> FeatureIndex:
    """Join every part of the map onto the feature it belongs to.

    `extents` is the pre-index symbol table, from `impact_git.load_map_extents(<map path>)`. Without
    it the rule join finds exact-line links only, and `rule_join_uses_extents` says so."""
    caps = {c.id: c for c in m.capabilities}
    uc_by_id = {u.id: u for u in m.use_cases}
    # use case -> feature, and the ones that belong to none. A map with no capabilities at all is
    # not a defect here: it is the pre-feature shape, and every field below simply comes back empty.
    uc_cap = {u.id: u.capability for u in m.use_cases if u.capability in caps}
    unassigned = [u.id for u in m.use_cases if u.id not in uc_cap]

    roles = {r.id for r in m.roles}
    comp_ids = {c.id for c in m.components}
    ent_ids = {e.id for e in m.entities}

    feat_roles: dict[str, set[str]] = {c: set() for c in caps}
    feat_ucs: dict[str, set[str]] = {c: set() for c in caps}
    feat_eps: dict[str, set[str]] = {c: set() for c in caps}
    feat_ents: dict[str, set[str]] = {c: set() for c in caps}
    feat_comps: dict[str, set[str]] = {c: set() for c in caps}
    feat_dirs: dict[str, set[str]] = {c: set() for c in caps}
    role_feat: dict[str, dict[str, int]] = {}

    for u in m.use_cases:
        cap = uc_cap.get(u.id)
        if cap is None:
            continue
        feat_ucs[cap].add(u.id)
        feat_eps[cap].update(u.entry_points or ())
        for a in u.actors or ():
            if a in roles:
                feat_roles[cap].add(a)
                role_feat.setdefault(a, {})
                role_feat[a][cap] = role_feat[a].get(cap, 0) + 1

    # What a feature touches, from the steps of its use cases' flows. Sub-flows are EXPANDED, so a
    # feature whose work happens inside a shared sequence still owns what that sequence touches.
    comp_in_flow: set[str] = set()
    for f in m.flows:
        cap = uc_cap.get(f.uc)
        for st in expanded_flow_steps(m, f):
            for side in (st.src, st.dst):
                if side in comp_ids:
                    comp_in_flow.add(side)
                    if cap:
                        feat_comps[cap].add(side)
                elif side in ent_ids and cap:
                    feat_ents[cap].add(side)
                    if st.direction:
                        feat_dirs[cap].add(st.direction)

    # The rule join, through `rule_steps` — the SAME reader the Rules view uses, so the two screens
    # cannot disagree about what one rule governs. A rule reaches a feature when one of its sites
    # reaches a step of one of that feature's use cases.
    rule_feats: dict[str, set[str]] = {}
    # A map with no capabilities cannot join a rule to one. Reporting every rule as "unjoined" there
    # would read as a gap rather than as the pre-feature shape the map actually has.
    can_join = bool(caps)
    if can_join:
        steps = anchored_flow_steps(m)
        for r in m.rules:
            hit = {uc_cap[link.uc] for link in rule_steps(m, r, extents, steps)
                   if link.uc in uc_cap}
            if hit:
                rule_feats[r.id] = hit

    # A rule's own component reach is NOT a feature join (it smears) — but it IS how a component
    # earns "a decision is enforced here", which the coverage line counts.
    # EVERY owner of a file, never the first. `components[].files` is not required to be disjoint
    # and carries no line ranges: measured across five maps, coyomap's own is only 72.7% unique, with
    # 5 files claimed by 2-5 components each. Picking one silently is the failure the rules design
    # exists to prevent, and here it would UNDER-count the components a decision is enforced in.
    file_owners: dict[str, list[str]] = {}
    for c in m.components:
        for fp in c.files or ():
            file_owners.setdefault(fp, []).append(c.id)
    comp_in_rule: set[str] = set()
    for r in m.rules:
        for site in r.sites:
            loc = parse_anchor((site.where or "").strip())
            if loc is not None:
                comp_in_rule.update(file_owners.get(loc.path) or ())

    # ── the interface join ───────────────────────────────────────────────────────────────────────
    # Two independent paths in, and NEITHER is the component-shared inference: a feature that merely
    # uses code which somewhere calls a service has not been shown to call it.
    #   (1) a use case names a way in, and that way in belongs to a surface  -> reached_through
    #   (2) a walk step is drawn AT a dep, and that dep names a surface      -> reaches_out
    iface_deps: dict[str, list[str]] = {}
    dep_iface: dict[str, list[str]] = {}
    for d in m.deps:
        for iid in d.interfaces:
            iface_deps.setdefault(iid, []).append(d.id)
        if d.interfaces:
            # One dep can sit on several surfaces, but a walk STEP drawn at that dep says only "this
            # feature reaches this outside system" — it cannot say which of its surfaces. Attribute
            # the step to every surface the dep sits on rather than guessing one.
            dep_iface[d.id] = list(d.interfaces)
    ep_comp = {ep.id: ep.component for ep in m.entry_points if ep.id and ep.component}
    dep_callers: dict[str, set[str]] = {}
    for ed in m.edges:
        if ed.dst in dep_iface and ed.src in comp_ids:
            dep_callers.setdefault(ed.dst, set()).add(ed.src)

    # WHICH USE CASES REACH A SURFACE is the one rule in `use_case_interfaces` (model.py), read here
    # through its inverse. A use case's authored `entry_points` used to be a second route into this
    # table (the use case names one of the surface's ways in); it went with the rule, so a surface's
    # use cases, its features and the walk order all read the same answer the use case cards read.
    # The loop below still walks the steps, but only to tell the DIRECTION of each reach — in through
    # the surface, or out to it — which is a feature's `reached_through` / `reaches_out` and nothing
    # the rule answers.
    reach_ucs = interface_use_cases(m)
    feat_in: dict[str, set[str]] = {c: set() for c in caps}
    feat_out: dict[str, set[str]] = {c: set() for c in caps}
    iface_ids = {i.id for i in m.interfaces}
    for f in m.flows:
        cap = uc_cap.get(f.uc)
        for st in expanded_flow_steps(m, f):
            for side in (st.src, st.dst):
                # A step drawn AT the surface itself is the strongest statement the map can make, and
                # the only one that works on the way IN as well as the way out.
                #
                # WHICH of the two comes from the STEP, never from the surface's `side`. Deriving it
                # from `side` was tried and is wrong on two real cases: coyomap's map files are OUR
                # surface and the story goes OUT through them, and Slack is SOMEONE ELSE'S surface
                # and Meerbot's stories come IN through it. A surface is commonly both.
                #   a step INTO a surface, from anything inside the product -> reaching OUT
                #   anything else touching a surface                        -> coming IN through it
                # "Inside the product" is any element id, not just a component: a record written out
                # (`En → In`), a subsystem-grain step, and a relay from one surface to another are all
                # the product pushing outward. A step whose source is a ROLE NAME is a person or an
                # outside system arriving, which is the other direction.
                if side in iface_ids:
                    reaching_out = (st.dst == side and grammar.is_step_id(st.src))
                    if cap:
                        (feat_out if reaching_out else feat_in)[cap].add(side)
                    continue
                # …and the older, weaker statement: a step drawn at a DEP the surface stands on.
                for iid in dep_iface.get(side, ()):
                    if cap:
                        feat_out[cap].add(iid)

    iface_actor_ucs = interface_actor_use_cases(m)
    iface_walk = interface_walk_order(m)
    iface_steps = interface_steps_by_use_case(m)
    #: WHICH WAY DATA GOES, derived from the steps. Replaced `carries[]`, which said it by hand.
    iface_dirs = interface_directions(m)
    interfaces = [
        InterfaceFacts(
            id=i.id, name=i.name, what=i.what, side=i.side, facing=i.facing,
            kind=grammar.canonical_interface_kind(i.kind),
            actors=list(iface_actor_ucs.get(i.id, {})),
            actor_use_cases=iface_actor_ucs.get(i.id, {}),
            directions=iface_dirs.get(i.id, []),
            ways_in=sorted_ids(set(i.ways_in)),
            deps=sorted_ids(set(iface_deps.get(i.id, ()))),
            components=sorted_ids(
                {ep_comp[ep] for ep in i.ways_in if ep in ep_comp}
                | {c for d in iface_deps.get(i.id, ()) for c in dep_callers.get(d, ())}),
            use_cases=sorted_ids(reach_ucs[i.id]),
            features=sorted_ids({uc_cap[u] for u in reach_ucs[i.id] if u in uc_cap}),
            features_unknown=not reach_ucs[i.id],
            steps=[(uc, [(st.phrase, st.container, st.n, st.role, st.direction) for st in group])
                   for uc, group in iface_steps.get(i.id, ())],
            walk_pos=iface_walk.get(i.id),
            opens="in" if i.ways_in else "out",
        )
        for i in m.interfaces
    ]

    # WHICH RULES A FEATURE DECIDES: the ones in the decision areas SPECIFIED UNDER it. Authored, and
    # deliberately so — see the note at the top of this module for what is derived here and why this one
    # is the exception.
    #
    # It was the STEP JOIN: the rules whose call sites land in the same function as a step of one of this
    # feature's flows. That is a true fact, but it is a different fact, and the two screens then printed
    # two numbers under one word. Measured on mcpolis for `Organizations and teammates`: the join said 12
    # rules, its two areas hold 16, and only 9 are in both — 3 reached only through its flows, 7 sitting
    # in its areas with no flow of its own reaching them.
    #
    # THE AUTHORED ONE IS WHAT THE HEADING PROMISES. The section is called "What it decides", which is a
    # question about the product's spec, not about which lines its code happens to run past.
    rules_by_block: dict[str, list[str]] = {}
    for r in m.rules:
        # A rule whose `block` the map never set belongs to no area, so it reaches no feature this way.
        if r.block:
            rules_by_block.setdefault(r.block, []).append(r.id)
    feat_rules: dict[str, set[str]] = {c.id: set() for c in m.capabilities}
    for b in m.blocks:
        for cap in (b.specified_under or []):
            if cap in feat_rules:
                feat_rules[cap].update(rules_by_block.get(b.id, ()))

    audience = capability_audience(m)
    story = build_story(m)
    areas = build_areas(m, story.column)
    # A map under the sub-domain threshold has no group to draw, and drawing nothing said its
    # features touch no data — while the same bundle lists what each one reaches. Same walk, same
    # steps; one box is one record instead of a group of them.
    # The flag says what the boxes ARE, so it is set from what the fallback actually produced. A map
    # with no sub-domain AND no saved record has nothing to draw either way, and claiming records
    # mode there would tell the viewer a box is a record on a column that holds none.
    areas_are_records = False
    if not areas:
        areas = build_record_areas(m, story.column)
        areas_are_records = bool(areas)
    feat_areas: dict[str, list[str]] = {}
    for a in areas:
        for t in a.touched_by:
            feat_areas.setdefault(t.feature, []).append(a.id)
    features = [
        FeatureFacts(
            id=c.id, name=c.name, purpose=c.purpose,
            audience=audience.get(c.id) or [],
            roles=sorted_ids(feat_roles[c.id]),
            use_cases=sorted_ids(feat_ucs[c.id]),
            entry_points=sorted_ids(feat_eps[c.id]),
            rules=sorted_ids(feat_rules[c.id]),
            entities=sorted_ids(feat_ents[c.id]),
            data_directions=sorted(feat_dirs[c.id]),
            components=sorted_ids(feat_comps[c.id]),
            areas=feat_areas.get(c.id, []),
            reached_through=sorted_ids(feat_in[c.id]),
            reaches_out=sorted_ids(feat_out[c.id]),
        )
        for c in m.capabilities
    ]

    comp_feats: dict[str, list[str]] = {}
    for f in features:
        for cid in f.components:
            comp_feats.setdefault(cid, []).append(f.id)

    named_eps = {e for u in m.use_cases for e in (u.entry_points or ())}
    unreached = sorted_ids({c.id for c in m.components} - comp_in_flow - comp_in_rule)
    coverage = Coverage(
        components_total=len(m.components),
        components_in_a_flow=len(comp_in_flow),
        components_in_a_rule=len(comp_in_rule),
        components_unreached=unreached,
        rules_total=len(m.rules),
        rules_joined=len(rule_feats),
        rules_unjoined=(len(m.rules) - len(rule_feats)) if can_join else 0,
        entry_points_total=len(m.entry_points),
        entry_points_named=len({e.id for e in m.entry_points if e.id and e.id in named_eps}),
        use_cases_total=len(m.use_cases),
        use_cases_without_feature=len(unassigned),
    )
    return FeatureIndex(
        features=features,
        use_case_interfaces=use_case_interfaces(m),
        component_features={k: sorted_ids(set(v)) for k, v in comp_feats.items()},
        rule_features={k: sorted_ids(v) for k, v in rule_feats.items()},
        role_features=role_feat,
        unassigned_use_cases=sorted_ids(set(unassigned)),
        coverage=coverage,
        story=story,
        areas=areas,
        areas_are_records=areas_are_records,
        entity_owners=entity_owners(m),
        interfaces=interfaces,
        rule_join_uses_extents=bool(extents),
    )


def as_bundle(ix: FeatureIndex) -> dict[str, object]:
    """The index in the viewer's own vocabulary (camelCase), ready to ship in the view bundle.

    A flat, id-keyed shape on purpose: the frontend already holds the model's names and renders them
    itself, so shipping objects here would put a second copy of every name in the payload and let
    the two drift."""
    return {
        "features": [
            {"id": f.id, "name": f.name, "purpose": f.purpose,
             "audience": f.audience,
             "roles": f.roles, "useCases": f.use_cases, "entryPoints": f.entry_points,
             "rules": f.rules, "entities": f.entities, "components": f.components,
             "dataDirections": f.data_directions,
             "areas": f.areas,
             "reachedThrough": f.reached_through, "reachesOut": f.reaches_out}
            for f in ix.features],
        "interfaces": [
            {"id": i.id, "name": i.name, "what": i.what, "side": i.side, "facing": i.facing,
             "kind": i.kind, "actors": i.actors, "actorUseCases": i.actor_use_cases,
             "directions": i.directions, "waysIn": i.ways_in, "deps": i.deps,
             "components": i.components, "useCases": i.use_cases, "features": i.features,
             "featuresUnknown": i.features_unknown,
             "hpStepPos": i.walk_pos, "opens": i.opens,
             "steps": [{"uc": uc, "steps": [{"phrase": ph, "container": ct, "n": n, "role": r,
                                             "direction": dr}
                                            for ph, ct, n, r, dr in group]}
                       for uc, group in i.steps]}
            for i in ix.interfaces],
        "useCaseInterfaces": {
            uc: {"list": sorted_ids(set(r.interfaces)), "sub": sorted_ids(set(r.via_subflow_only))}
            for uc, r in ix.use_case_interfaces.items()},
        "areas": [
            {"id": a.id, "name": a.name, "purpose": a.purpose, "entities": a.entities,
             "owners": a.owners,
             "touchedBy": [{"feature": t.feature, "touches": t.touches, "entities": t.entities}
                           for t in a.touched_by]}
            for a in ix.areas],
        "areasAreRecords": ix.areas_are_records,
        "entityOwners": ix.entity_owners,
        "componentFeatures": ix.component_features,
        "ruleFeatures": ix.rule_features,
        "roleFeatures": ix.role_features,
        "unassignedUseCases": ix.unassigned_use_cases,
        "story": {
            "spine": ix.story.spine,
            "off": ix.story.off,
            "column": ix.story.column,
            "cast": ix.story.cast,
            "edges": [{"actor": e.actor, "feature": e.feature, "label": e.label,
                       "authored": e.authored, "step": e.step}
                      for e in ix.story.edges],
        },
        "ruleJoinUsesExtents": ix.rule_join_uses_extents,
        "coverage": {
            "componentsTotal": ix.coverage.components_total,
            "componentsInAFlow": ix.coverage.components_in_a_flow,
            "componentsInARule": ix.coverage.components_in_a_rule,
            "componentsUnreached": ix.coverage.components_unreached,
            "rulesTotal": ix.coverage.rules_total,
            "rulesJoined": ix.coverage.rules_joined,
            "rulesUnjoined": ix.coverage.rules_unjoined,
            "entryPointsTotal": ix.coverage.entry_points_total,
            "entryPointsNamed": ix.coverage.entry_points_named,
            "useCasesTotal": ix.coverage.use_cases_total,
            "useCasesWithoutFeature": ix.coverage.use_cases_without_feature,
        },
    }
