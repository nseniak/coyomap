#!/usr/bin/env python3
"""`coyomap-eval score` — the deterministic quality PROFILE of a built map (the eval's reusable heart).

A map is LLM-authored, so two runs on the same repo differ in IDs, wording, and ordering — you cannot
regress a map by diffing its text. This module reduces a map to a `MapProfile`: a set of measurable
quality signals that ARE comparable run-to-run:

  well-formedness  — `validate` problems / warnings (via the shared `validate_model.validate_model`)
  self-consistency — `audit` findings, by severity, + the L2 grounding worklist size
  coverage         — compression / absent-module flags (needs the repo; else omitted)
  structure        — counts of use cases, subsystems, subdomains, components, deps, entities, edges,
                     Happy-Path steps, T6 flows, security surfaces
  concept sets     — auth-surface / use-case / entity NAMES, for the comparator's set diffs and the
                     "an auth surface must not silently disappear" gate

Everything here is DETERMINISTIC and stdlib-only. It reads the map through the model pipeline
(`load_model` + `validate_model` + `audit_model`) — never a second grammar. The comparator
(baseline vs candidate → verdict) and the LLM-judge layer build ON this profile; they are separate
modules.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from coyomap.impact_git import load_map_extents
from coyomap.impact_lib import enclosing_extent
from coyomap import audit_model, balance_lib, grammar, validate_model
from coyomap.model import FlowStep, ModelError, ProjectModel, load_model
from coyomap.packages import declared_packages, unnamed_packages

from coyomap_eval.legacy_map import load_model_tolerating_legacy
from coyomap.preindex_lib import expected_components  # the granularity expectation E, RE-COMPUTED
# from the repo tree at score time (shared code, never the pre-index's JSON — GR4)
from coyomap.validate_analysis import compression_coverage_from_refs  # repo-tree coverage (not a
# markdown parse — the same helper validate_model's --check-coverage runs)


@dataclass(frozen=True)
class MapProfile:
    """The deterministic quality signals of one built map. Serialized to `profile.json`; the comparator
    diffs two of these. Field order is the report order."""
    # ── structure (counts of the map's elements) ──
    use_cases: int
    subsystems: int
    subdomains: int
    components: int
    deps: int
    entities: int
    edges: int
    hp_steps: int
    flows: int
    security_surfaces: int
    # ── well-formedness (coyomap validate) ──
    validate_ok: bool
    validate_problems: int
    validate_warnings: int
    # ── self-consistency (coyomap audit) ──
    contradictions: int
    #: Audit findings of ADVISORY severity — audit ONLY, which is why the name says so. It was
    #: `advisories`, sitting next to `validate_warnings`, and on a map `finalize` called
    #: "ADVISORIES — 12 advisory" this field read 0. A retrospective quoted it as "the map has no
    #: advisories". Renamed with NO back-compat alias by operator decision: profiles written before
    #: this fail to load rather than silently reading 0, and the eval baselines are git-ignored
    #: artifacts that are cheap to re-bless.
    audit_advisories: int
    audit_warnings: int
    l2_claims: int
    # ── coverage (None when scored without the repo) ──
    coverage_flags: int | None
    # ── density (scale-invariant ratios — the drift signal that stays steady when a map merely gets
    #    finer or coarser uniformly; None when the denominator is 0 or the profile predates the field) ──
    edges_per_component: float | None = None
    # ── granularity (the code-derived component expectation E — the leaf anchor both maps are
    #    measured against; None when scored without the repo, or the profile predates the field) ──
    granularity_expected: int | None = None
    # ── diagram balance (fan-out of the rendered S-forest diagrams — report-only, no gate; None
    #    when the profile predates the fields. Gating is opt-in per project via thresholds bands.) ──
    root_fanout: int | None = None
    max_fanout: int | None = None
    fanout_in_band_pct: float | None = None    # share of diagrams inside [3,9], exemptions included
    nesting_depth: int | None = None
    # ── use-case granularity (the flow analog of the fan-out fields — report-only, same opt-in
    #    gating pattern; None when the profile predates the fields). Counts are AUTHORED steps: a
    #    sub-flow reference counts as 1, so extraction is rewarded, not punished. ──
    subflows: int | None = None
    max_flow_len: int | None = None
    flows_over_band_pct: float | None = None   # share of flows over FLOW_STEPS_HI (15)
    # ── use-case & Happy-Path completeness (report-only; band-able per project via a thresholds
    #    entry, like every numeric field — nothing compares them by default; None when the profile
    #    predates the fields or the signal is not computable). Counts are RAW (pre-escape): a
    #    recorded 'Unclaimed surfaces' / 'Happy Path coverage' adjudication silences the validate
    #    warning but not these — the same convention as flows_over_band_pct vs 'Balance exceptions',
    #    so the drift signal survives the adjudication. ──
    entry_points: int | None = None
    external_entry_points: int | None = None   # effective activation (authored-if-valid, else kind)
    unclaimed_entry_points: int | None = None  # external EPs whose component no flow reaches;
    #                                            None when the map has no entry points or no flows
    stepped_entry_points: int | None = None    # external EPs some flow step RUNS — a step anchored
    #                                            within 3 lines of the way in's own `source`, named
    #                                            or not. The way-in-grain evidence the component-
    #                                            grain unclaimed count cannot see (one flow through
    #                                            a component claims every way in it owns); same
    #                                            None rule as unclaimed_entry_points. Report-only.
    named_entry_points: int | None = None      # external EPs a use case NAMES (`entry_points`) —
    #                                            the authored arm; None when the map has no entry
    #                                            points or no use cases. Report-only.
    storyless_entry_points: int | None = None  # external EPs neither named nor run (middleware and
    #                                            recorded plumbing excluded) — the walk's debt, RAW
    #                                            (an 'Unclaimed surfaces' record silences the
    #                                            advisory, not this); same None rule as
    #                                            unclaimed_entry_points. Report-only.
    off_spine_ucs: int | None = None           # use cases with no HP position; None when HP empty
    unclaimed_self_entry_points: int | None = None  # SELF-activated EPs (crons, workers, consumers,
    #: The product's OUTSIDE EDGE (T2b). Optional so profiles written before it exists still load.
    #: The eval is the instrument every method change is validated with, and it could not see this
    #: section at all: a build that authored twelve surfaces and one that authored none scored
    #: identically. `interface_doors` is the retrofit half — surfaces authored and never put into a
    #: story is the failure mode that shipped, so the count that catches it is the one worth keeping.
    interfaces: int | None = None
    interface_doors: int | None = None        # flow steps whose endpoint is an `In`
    #: EVERY crossing between an actor and the product that does NOT go through a surface, and the
    #: reason it is a separate count: `interface_doors` rises the moment a build opens its stories, so
    #: a build that doors the openings and nothing else looks healthy in that one number. Counts
    #: STEPS, not flows, so a half-doored story is visible as a half-doored story. Measured the day
    #: the strict rule landed: mcpolis read 38 with `interface_doors` already at 129.
    crossings_without_a_door: int | None = None
    #: The same crossings MINUS the ones the map has already answered for — a `UCn/doors: <why>`
    #: (or sub-flow id) recorded under an 'Interface exceptions' heading, the record `validate`
    #: itself honours. So this is the count still OPEN, and the two instruments agree on one map.
    #: Without it the profile read 1 on a map `validate` had nothing left to say about, and
    #: `eval/retro/method.md` Step 1c, which treats "above 0" as a defect, had no adjudicated state
    #: to put that in.
    #: `None`, never 0, on a profile written before the field: 0 is the clean value here, and a
    #: comparison must be able to tell "not measured" from "measured, and nothing open".
    crossings_without_a_door_unadjudicated: int | None = None
    interfaces_undecided_deps: int | None = None   # external deps naming neither a surface nor a why
    #: The two counts that make an UNAUTHORED shape visible to the instrument. Without a rebuild to
    #: validate the method text on, these plus `eval/rubric.md` are the only things that will report
    #: on it — on somebody else's build, months from now.
    interfaces_without_kind: int | None = None
    #: Deps with no authored `bucket` (`validate_model.deps_without_bucket`). The viewer guesses a
    #: group for each, and on the 2026-10-08 mcpolis map all 19 shipped without one and 8 of the
    #: guesses were wrong. `None` on a profile written before the field.
    deps_without_bucket: int | None = None
    #: Top-level packages the repo's package files declare that no dep names
    #: (`packages.unnamed_packages`). Needs the repo, like `coverage_flags`: `None` without `--repo`.
    #: The 2026-10-08 mcpolis rebuild dropped from 29 deps to 19 and lost React Router, Tailwind and
    #: TanStack Query with no count moving but `deps` itself.
    packages_without_dep: int | None = None
    #: Counted over `theirs` surfaces ONLY, where nothing derives: an `ours` surface with ways in
    #: derives its actors from the walks, so counting it would report a full map as an empty one.
    #: A `theirs` surface with no actor is often CORRECT (a crash reporter has nobody on the far
    #: side) — this is a trend line across builds, never a defect count.
    interfaces_without_actors: int | None = None
    #                                            startup hooks) no use case reaches. These used to be
    #                                            exempt automatically, which could hide a whole
    #                                            background capability; they are now a decision, and
    #                                            this is the number that shows whether it was taken.
    capabilities: int | None = None            # size of the use-case grouping; None on a map that
    #                                            has not adopted it (the field is additive)
    capabilities_untraced: int | None = None   # capabilities NONE of whose use cases is traced — an
    #                                            empty box in the overlay, i.e. a real part of the
    #                                            product nobody traced. Invisible before this existed.
    use_cases_untraced: int | None = None      # trace debt. The target is 100 %; measured on a real
    #                                            build, closing a 15-of-25 gap costs ~12 % of build
    #                                            tokens, so the shortfall is reported, never redefined
    #                                            as correct.
    off_spine_in_expected_capabilities: int | None = None  # the deliberate give-up of the capability-level
    #                                            spine check, made countable: use cases off the walk
    #                                            inside a capability marked `happy_path: expected`,
    #                                            which no longer warn.
    entities_in_flows: int | None = None       # distinct entities appearing as a flow-step
    #                                            endpoint (sub-flows expanded) — the flow-derived
    #                                            'Used in UC' coverage of the domain model
    entities_in_flows_pct: float | None = None  # share of all entities; both fields None when the
    #                                            map has no entities or no flows (an untraced map
    #                                            is "not yet traced", not "traced and zero")
    # ── business logic (T7 — the decision layer) ────────────────────────────────────────────────
    # None on a map that has not adopted the layer, so an old profile stays loadable and an
    # un-adopted map is distinguishable from one whose sweep found nothing. REPORT-ONLY by default,
    # band-able per project via a thresholds entry — the same treatment `capabilities`, `subflows`
    # and the completeness fields get, and for the same reason: a DEFAULT band on an
    # adoption-dependent metric emits a "skipped, not numeric on both sides" note on every
    # comparison of every map that has not adopted it. `l2_claims` stays unbanded on purpose and
    # rule sites inflate it, so the collapse signal to band here is `rules` / `rule_sites`.
    rules: int | None = None                   # how many decisions the map states
    blocks: int | None = None                  # the decision grouping
    rule_sites: int | None = None              # ANCHORED enforcement sites across all rules — the
    #                                            number that says whether the rules are grounded or
    #                                            merely listed. A `no_call_site` entry is deliberately
    #                                            NOT counted: it is a declared absence, so counting
    #                                            it would inflate exactly the metric it is absent from.
    rules_swept: int | None = None             # rules whose components hold NO uncovered
    #                                            decision-sounding step. DERIVED (validate_model.
    #                                            rules_swept) — there is no authored flag, on
    #                                            purpose: "I searched the whole repo" is
    #                                            unfalsifiable, and a hand-set one would make this
    #                                            metric measure the author's confidence.
    rules_unverified: int | None = None        # rules with AT LEAST ONE anchored site in a file no
    #                                            component claims, so part of the rule renders bare.
    #                                            The debt number, and it matches what the T7 view
    #                                            stamps: counting only rules where EVERY site fails
    #                                            under-reports precisely the partly-grounded rule,
    #                                            which is the interesting one.
    # ── provenance of the TOOL, not the analysed repo ───────────────────────────────────────────
    #: Which coyomap build produced the map. Not a gate and not a quality signal — context, so a
    #: comparison across a tool change is READ as one. A comparison once reported REGRESSED for a
    #: map that was simply newer, across a documented breaking change with no migration, and
    #: nothing in either profile said the two maps came from different tools. `None` on any map
    #: built before the stamp existed, which reads as unknown, never as equal.
    tool_commit: str | None = None
    tool_committed: str | None = None

    # ── deployment linkage ──────────────────────────────────────────────────────────────────────
    # A Deployment view is only a view if components point at units. A live rebuild kept all eight
    # units, dropped the two components that owned the nginx and vector files, and filled `runs_in`
    # by contiguous component-id range — a formula that can only produce contiguous buckets, so six
    # of the eight boxes ended up empty. Nothing watched it: `runs_in` COVERAGE went 93/96 -> 66/66,
    # a perfect score produced by dumping everything into two units. Coverage is not linkage.
    deployment_units: int = 0
    deployment_units_linked: int = 0             # units named by at least one component's runs_in
    # Linkage counts UNITS, and a unit is cheap to add. A live map scored 3/10 linked where the
    # three linked units — `backend`, `standalone`, `e2e backend shard` — hosted the IDENTICAL 50
    # components: one placement decision, replicated across three deployment shapes of the same
    # process, while the other 30 components (the whole frontend) sat in no unit at all. The gate
    # passed on 2/8 -> 3/10 because a unit had been ADDED, not because code had been placed. This
    # counts DISTINCT non-empty component sets instead, so replicating a shape cannot move it.
    deployment_distinct_hosted_sets: int = 0
    #: Units carrying two or more `variants`. `method.md` models one process that runs in several
    #: environments as ONE unit with a variant per environment, and the alternative — a unit per
    #: environment — inflates `deployment_distinct_hosted_sets`. So a map that adopts the prescribed
    #: form scores lower on that gate than one that duplicates. This number is what tells the two
    #: apart; the gate stays as it is, because "another shape of the same process" must not buy
    #: linkage, and a NOTE explains the drop instead. None on a profile blessed before the field.
    deployment_units_multi_variant: int | None = None
    # The EMPTY boxes: units running no component and no entry point that are not system infra
    # either (`validate_model.orphan_deployment_units`, the same list `validate` advises on).
    #
    # Linkage as an absolute count punished a map for getting BETTER. One rebuild named 4 units, all
    # first-party runtimes, all linked; the next named 11 — the same 3 runtimes plus the proxy, two
    # datastores, the log forwarder, two test instances and two test doubles — and correctly folded
    # a unit that was really a mount inside the backend process into that process. Linked went
    # 4 -> 3, the gate FAILED, and the Deployment view it was judging had gained seven honest boxes
    # and lost nothing. Infra units are empty BY NATURE, so counting them as unfilled linkage
    # measures how COMPLETE the section is and reports completeness as a regression.
    #
    # `None`, not 0, when a profile predates the field: 0 is the STRICTEST value here, so a baseline
    # blessed before this existed made the gate fail a map against ITSELF. Both sibling deployment
    # gates handle the same hazard by skipping with a note, and this one has to be able to tell
    # "not scored" from "scored, and clean".
    deployment_orphan_units: int | None = None
    # Does ANY component or entry point set `runs_in`? Orphans are defined only on a map that
    # places something: a map placing nothing has not orphaned its units, it has not adopted the
    # field, which is a different finding. That definition left the WORST section un-gateable —
    # strip every `runs_in` and the orphan count is 0 by construction, so 16 empty boxes scored
    # `0 -> 0` and passed. `validate` fires an unlinked canary there; nothing here read it.
    deployment_runs_in_adopted: bool | None = None

    # ── concept sets (names, for the comparator's set diffs + the auth-surface gate) ──
    auth_surfaces: list[str] = field(default_factory=list)
    #: WHERE the auth surface is enforced — every anchored access site as a bare `path:line`, sorted.
    #: `auth_surfaces` holds the STATEMENTS, which are LLM prose: two builds of one commit describe
    #: the same decision in different words, so a name comparison reports almost everything as
    #: dropped and the operator is told to "verify rather than trust" with nothing to verify against.
    #: The anchors are wording-independent. Measured on two mcpolis builds of the SAME commit: the
    #: statement count moved 50 -> 44 while the anchor sets shared only 57 of 163, and 17 files
    #: holding access enforcement in one map were named by no access rule in the other. `None` on a
    #: profile written before this field existed — the comparison says so rather than reading 0 as
    #: agreement.
    auth_sites: list[str] | None = None
    use_case_names: list[str] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)

    # ── reproducibility: does a REBUILD of the same code produce the same map? ───────────────────
    #: The mapped repo's own commit. Not the tool's — `tool_commit` above is that. Without it a name
    #: comparison cannot tell the one case where it means something (two builds of ONE commit, where
    #: a changed name is instability) from the ordinary case (two commits, where a changed name is
    #: the code moving). `None` on a profile written before this field existed.
    commit: str | None = None
    #: The NAMES a build chose, per element kind. Counts already travel as `components`, `flows` and
    #: the rest; a count is the one thing that cannot see this failure. Two mcpolis builds of commit
    #: `5dccb1c`, 21 hours apart, both scored in band on every count that gates — and shared 9
    #: component names of 70 and 118, 13 use-case names of 47, and 0 test labels of 76, while
    #: agreeing on 55 of 70 component SOURCE anchors. The two maps point at the same code and call
    #: almost none of it by the same name. Nothing in the toolchain measured that until this field.
    #: `None`, never `[]`, on a profile that predates it — an empty list would read as "no overlap".
    component_names: list[str] | None = None
    #: How many component rows are IN EXCESS of the distinct names — 1 for a single colliding
    #: pair, not 2. (`components - len(set(names))`, so it is directly comparable to the two
    #: numbers beside it.) `component_names` is a SET, so a collision
    #: deduplicates itself away: the 2026-08-29 mcpolis map recorded `components: 107` beside 106
    #: names and nothing read the gap, while the retro metric built on that set ("component names
    #: surviving a rebuild") reported 8 % on a list that had quietly hidden the pair it should have
    #: surfaced. `validate` now advises on it; this is the number `compare` can watch.
    duplicate_component_names: int = 0
    #: Where each component points, as a bare path with the line dropped. Wording-independent, so it
    #: separates "the two builds cut the code differently" from "the two builds named it differently".
    component_sources: list[str] | None = None
    # `flow_titles` was here and was REMOVED before it shipped: a flow is titled after its use case,
    # so the set was byte-identical to `use_case_names` on four of five real maps and shared 51 of 54
    # on the fifth. Two rows printing one measurement makes the disagreement look twice as broad.
    #: The test FILES the map cites, as bare paths. Not the test-row LABELS: measured across 48
    #: same-commit build pairs the labels agree 0 % in 44 of them and 0 % under fuzzy matching too, so
    #: the row was a constant and could signal neither a regression nor a repair. The files a build
    #: chose to cite are wording-independent, which is the same reason `auth_sites` beat
    #: `auth_surfaces` and `component_sources` beats `component_names`.
    test_files: list[str] | None = None
    #: Each access-enforcement site as `path::function` (the innermost definition holding the
    #: line, from the pre-index beside the map), or `path:line` when no extent holds it. The
    #: line-level `auth_sites` agreement has read 22–28 % across seven rebuild pairs, and the
    #: 2026-08-29 investigation found the builds choose the same PLACES and different LINES in
    #: them; this is the number that separates that jitter from a function that lost its rule.
    auth_functions: list[str] | None = None
    #: How many interfaces of each canonical kind. A kind that goes to 0 between two builds is a
    #: surface lost or re-kinded — `handoff` went 1 -> 0 on a rebuild with its `mailto:` still in
    #: the code, and no count above moved.
    interface_kinds: dict[str, int] | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "MapProfile":
        # Filter to KNOWN fields so a baseline written by a newer profile version (e.g. once the judge
        # layer adds scores) still loads instead of raising on an unexpected keyword. A missing field
        # falls back to its dataclass default.
        raw = json.loads(s)
        known = {f.name for f in fields(cls)}
        # A profile written before `advisories` became `audit_advisories`. It is REFUSED, not
        # adapted: the rename exists because the old name read as "the whole map's advisories" when
        # it only ever counted audit's, and quietly accepting the old key would carry that
        # misreading into the comparison. Baselines are git-ignored artifacts — re-score and re-bless.
        if "advisories" in raw and "audit_advisories" not in raw:
            raise ValueError(
                "this profile predates the `advisories` -> `audit_advisories` rename. It counted "
                "AUDIT advisories only, and the old name was being read as the map's total. "
                "Re-score the map (`coyomap-eval score <map> --repo . --json`) and re-bless the "
                "baseline; there is deliberately no back-compat alias.")
        return cls(**{k: v for k, v in raw.items() if k in known})


# ── the profile ─────────────────────────────────────────────────────────────────────────────────────

def build_profile(map_text: str, repo_root: Path | None = None,
                  map_path: Path | None = None) -> MapProfile:
    """Reduce a project map to its deterministic `MapProfile`. `repo_root` (the mapped source) enables
    the coverage signal; without it `coverage_flags` is None. `map_path` (the map file, with
    `preindex.json` beside it) enables `auth_functions`; without it that field is None. It was an
    unused compatibility parameter until 2026-09-09."""
    return build_profile_from_model(load_model(map_text), repo_root=repo_root, map_path=map_path)


def _all_step_lists(m: ProjectModel) -> list[tuple[str, list[FlowStep]]]:
    """Flows AND sub-flows, each beside the id its adjudication is keyed on — a flow's USE CASE, a
    sub-flow's own id, exactly as `validate_model` keys them.

    Both counts below read this one list: `interface_doors` used to count flows only while
    `crossings_without_a_door` counted both, and `eval/retro/method.md` tells the reader to read the
    pair together. A map doored entirely inside shared machinery scored 0 and 0, which that page
    reads as "authored and never put into a story"."""
    return [(f.uc, f.steps) for f in m.flows] + [(sf.id, sf.steps) for sf in m.subflows]


def _door_steps(m: ProjectModel) -> int:
    """Steps with a DEFINED surface at either end. Reads the defined ids, not the id SHAPE: a step
    naming an undefined `I99` is a dangling reference the validator already blocks, and counting it
    as a door here would have the two instruments disagree about the same step."""
    ids = {i.id for i in m.interfaces}
    return sum(1 for _, steps in _all_step_lists(m) for st in steps
               if st.src in ids or st.dst in ids)


def _undoored_crossings(m: ProjectModel) -> tuple[int, int]:
    """`(every crossing with no surface between, how many of those nobody has answered for)`.

    Uses the validator's OWN definition of an actor, its OWN predicate and its OWN record reader, so
    the instrument and the check cannot drift: three copies of "who is an actor" existed once and two
    of them disagreed.

    TWO NUMBERS, because one could not tell an answered crossing from an unanswered one. The map
    adjudicates a story's crossings by recording `UCn/doors: <why>` (or the sub-flow's id) under an
    'Interface exceptions' extras heading, and `validate` honours that. The profile did not, so a map
    `validate` had nothing left to say about came back reading 1 — and `eval/retro/method.md` Step 1c
    reads "above 0" as a defect, with no adjudicated state to land in.

    The RAW count keeps the existing name and the existing meaning: it is the drift signal, and the
    fields around it hold the same line ("Counts are RAW (pre-escape)"), so an adjudication silences
    the warning and never the trend. The second number is the one still open."""
    roles = validate_model.outside_actor_ids(m)
    ids = {i.id for i in m.interfaces}
    excused = validate_model._recorded_ids(
        m, validate_model.INTERFACE_EXCEPTIONS_HEADING, ("UC", "SF"))
    raw = still_open = 0
    for key, steps in _all_step_lists(m):
        crossings = sum(1 for st in steps
                        if validate_model._is_undoored_crossing(st, roles, ids))
        raw += crossings
        # A bare `UCn` excuses the whole family, `UCn/doors` this gate alone — the two tokens
        # `validate`'s own `_excused` honours, read here rather than re-derived.
        if not {key, f"{key}/doors"} & excused:
            still_open += crossings
    return raw, still_open


def build_profile_from_model(m: ProjectModel, repo_root: Path | None = None,
                             map_path: Path | None = None) -> MapProfile:
    """The MapProfile computed from a model — every signal through the model-side checks
    (`validate_model`, `audit_model`). The Phase-2 golden-equivalence run proved these score a map
    exactly as the (now retired) markdown pipeline scored its v1 equivalent. `map_path` (the map
    file, with `preindex.json` beside it) enables `auth_functions`: without the pre-index's
    symbol table no line can be placed in its function, and the field is None."""
    iface_actors = validate_model.interface_actors(m)
    problems, warnings = validate_model.validate_model(m)  # no model_path: view-freshness is a
    # repo-hygiene signal, not map quality — it must not shift an eval profile
    findings = audit_model.audit_model(m)
    contradictions = sum(1 for f in findings if f.severity == audit_model.CONTRADICTION)
    audit_advisories = sum(1 for f in findings if f.severity == audit_model.ADVISORY)
    audit_warnings = sum(1 for f in findings if f.severity == audit_model.WARNING)
    l2_claims = len(audit_model.l2_worklist_model(m))

    coverage_flags: int | None = None
    granularity_expected: int | None = None
    packages_without_dep: int | None = None
    if repo_root is not None:
        root = Path(repo_root).resolve()
        packages_without_dep = len(unnamed_packages(m.deps, declared_packages(root)))
        coverage_flags = len(compression_coverage_from_refs(
            validate_model.referenced_paths(m, root), root))
        e = expected_components(root).expected
        granularity_expected = e if e > 0 else None  # a tree with no component-forming source anchors nothing

    # THE AUTH SURFACE, from both storages. `compare.auth_surfaces_must_not_drop` is a hard gate
    # with no tolerance, and phase 8 empties `security[]` into rules with `access: true` — so the
    # union is a no-op while both exist and a no-op again after the fold. Inverted HERE, one phase
    # before the fold, precisely so the gate never sees the transition.
    # De-duplicated as ONE set, not two passes: a list comprehension is evaluated against the
    # pre-`+=` list, so it would dedup rules against security rows and never against other rules —
    # and `security_surfaces = len(surfaces)` feeds `auth_surfaces_must_not_drop`, a hard gate with
    # no tolerance, where one duplicate masks one genuinely dropped surface.
    surfaces: list[str] = []
    for name in ([s.surface.strip() for s in m.security]
                 + [r.statement.strip() for r in m.rules if r.access]):
        if name and name not in surfaces:
            surfaces.append(name)
    # The same surface, addressed by LOCATION. Both storages again: a legacy `security[]` row carries
    # its own `source`, and an `access` rule carries one anchor per site. A site declared
    # `no_call_site` has no location to compare, so it is absent here and present in `auth_surfaces`.
    auth_sites = sorted({a.strip() for a in (
        [s.source for s in m.security]
        + [site.where for r in m.rules if r.access for site in r.sites])
        if a and ":" in a})
    owners = validate_model.component_file_owners(m)   # built once; the derivation's shared index
    auth_functions: list[str] | None = None
    if map_path is not None:
        extents = load_map_extents(map_path)
        if extents:
            placed: set[str] = set()
            for site in auth_sites:
                path, _, line = site.rpartition(":")
                ext = enclosing_extent(extents.get(path, []), int(line)) if line.isdigit() else None
                # A site outside every function (a module-level table, a constant) keys on the
                # FILE: 6 of mcpolis's 7 such sites were consecutive lines of one policy table, and a
                # `path:line` key would count a rebuild citing line 47 instead of 46 as a function
                # lost, the exact jitter this number exists to remove.
                placed.add(f"{path}::{ext[2]}" if ext else path)
            auth_functions = sorted(placed)
    kinds: dict[str, int] = {}
    for i in m.interfaces:
        k = grammar.canonical_interface_kind(i.kind) or "unknown"
        kinds[k] = kinds.get(k, 0) + 1
    undoored_raw, undoored_open = _undoored_crossings(m)
    n_components = len({c.id for c in m.components})
    n_edges = len(m.edges)
    root_fanout, max_fanout, in_band_pct, depth = balance_lib.fanout_summary(m)
    # DOORS DO NOT COUNT, exactly as `validate`'s own band does not count them. A sub-flow
    # reference still counts as 1 (the authored convention), but an INTERFACE step is a structural
    # exemption there: the band exists to catch a fused goal or wire-grain detail, and naming the
    # door a story comes in by is neither. The two measures disagreed the day doors were authored —
    # on argus this read 54.8% over band against `validate`'s 0%, so the eval reported a regression
    # in the very quality signal the gate said was clean. One rule, read from `validate_model`, so
    # the two cannot drift again.
    flow_lens = [validate_model.banded_step_count(f.steps) for f in m.flows]
    over_band = sum(1 for n in flow_lens if n > validate_model.FLOW_STEPS_HI)
    # Completeness — computed by the SAME helpers the validate advisory runs (never a second
    # implementation). Raw signal, pre-escape (see the field comments above).
    n_external = len(validate_model.external_entry_points(m))
    unclaimed = (len(validate_model.unclaimed_external_entry_points(m))
                 if m.entry_points and m.flows else None)
    off_spine = (sum(1 for u in m.use_cases if u.id not in {g.uc for g in m.happy_path})
                 if m.happy_path else None)
    e_in_flows = (len(validate_model.flow_touched_entities(m))
                  if m.entities and m.flows else None)
    unclaimed_self = (len(validate_model.unclaimed_self_entry_points(m))
                      if m.entry_points and m.flows else None)
    counts = validate_model.completeness_counts(m)
    stepped_eps = counts["entry_points_stepped"] if m.entry_points and m.flows else None
    storyless_eps = counts["entry_points_storyless"] if m.entry_points and m.flows else None
    named_eps = (counts["entry_points_named_by_use_case"]
                 if m.entry_points and m.use_cases else None)
    n_caps = len(m.capabilities) or None      # None on a map that has not adopted the grouping
    caps_untraced = counts["capabilities_untraced"] if m.capabilities else None
    ucs_untraced = counts["use_cases_untraced"] if m.use_cases else None
    off_spine_expected = counts["off_spine_in_expected_capabilities"] if m.capabilities and m.happy_path else None

    # Linkage, not coverage: how many declared units any component actually claims to run in.
    unit_names = [u.unit for u in m.deployment if u.unit]
    claimed = {name for c in m.components for name in (c.runs_in or [])}
    claimed |= {name for ep in m.entry_points for name in (ep.runs_in or [])}
    # What each unit hosts, as a set — two units hosting the same set are one placement decision
    # wearing two names, and only the distinct sets are evidence the view says anything.
    #
    # Components AND entry points, because `deployment_units_linked` above counts both and the two
    # numbers are read side by side. Counting only components made a map that places its frontend
    # via entry-point `runs_in` score `linked > 0` with `distinct_sets == 0` — which passed the gate
    # vacuously AND suppressed the note that explains the gap. Entry points are keyed by index;
    # they carry no id, and only set IDENTITY matters here.
    hosted: dict[str, frozenset[str]] = {}
    for u in unit_names:
        members = frozenset(
            [c.id for c in m.components if u in (c.runs_in or [])]
            + [f"ep:{i}" for i, ep in enumerate(m.entry_points) if u in (ep.runs_in or [])])
        if members:
            hosted[u] = members

    return MapProfile(
        tool_commit=m.tool_commit,
        tool_committed=m.tool_committed,
        deployment_units=len(unit_names),
        deployment_units_linked=sum(1 for u in unit_names if u in claimed),
        deployment_distinct_hosted_sets=len(set(hosted.values())),
        deployment_units_multi_variant=sum(1 for u in m.deployment if len(u.variants or []) > 1),
        deployment_orphan_units=len(validate_model.orphan_deployment_units(m)),
        deployment_runs_in_adopted=bool(
            any(c.runs_in for c in m.components) or any(ep.runs_in for ep in m.entry_points)),
        use_cases=len({u.id for u in m.use_cases}),
        subsystems=len({s.id for s in m.subsystems}),
        subdomains=len({s.id for s in m.subdomains}),
        components=n_components,
        deps=len({d.id for d in m.deps}),
        entities=len({e.id for e in m.entities}),
        edges=n_edges,
        hp_steps=len(m.happy_path),
        flows=len(m.flows),
        security_surfaces=len(surfaces),
        interfaces=len(m.interfaces),
        interface_doors=_door_steps(m),
        crossings_without_a_door=undoored_raw,
        crossings_without_a_door_unadjudicated=undoored_open,
        interfaces_undecided_deps=sum(
            1 for d in m.deps
            if grammar.classify_dep(d.kind or "", d.type or "") in grammar.DEP_KINDS_SYSTEM
            and not d.interfaces and not d.not_an_interface),
        deps_without_bucket=len(validate_model.deps_without_bucket(m)),
        packages_without_dep=packages_without_dep,
        interfaces_without_kind=sum(
            1 for i in m.interfaces if not grammar.canonical_interface_kind(i.kind)),
        interfaces_without_actors=sum(
            1 for i in m.interfaces
            if i.side == "theirs" and not iface_actors.get(i.id)),
        validate_ok=not problems,
        validate_problems=len(problems),
        validate_warnings=len(warnings),
        contradictions=contradictions,
        audit_advisories=audit_advisories,
        audit_warnings=audit_warnings,
        l2_claims=l2_claims,
        coverage_flags=coverage_flags,
        edges_per_component=round(n_edges / n_components, 3) if n_components else None,
        granularity_expected=granularity_expected,
        root_fanout=root_fanout,
        max_fanout=max_fanout,
        fanout_in_band_pct=in_band_pct,
        nesting_depth=depth,
        subflows=len({sf.id for sf in m.subflows}),
        max_flow_len=max(flow_lens) if flow_lens else None,
        flows_over_band_pct=round(100 * over_band / len(flow_lens), 1) if flow_lens else None,
        entry_points=len(m.entry_points),
        external_entry_points=n_external,
        unclaimed_entry_points=unclaimed,
        stepped_entry_points=stepped_eps,
        named_entry_points=named_eps,
        storyless_entry_points=storyless_eps,
        off_spine_ucs=off_spine,
        unclaimed_self_entry_points=unclaimed_self,
        capabilities=n_caps,
        capabilities_untraced=caps_untraced,
        use_cases_untraced=ucs_untraced,
        off_spine_in_expected_capabilities=off_spine_expected,
        entities_in_flows=e_in_flows,
        entities_in_flows_pct=(round(100 * e_in_flows / len(m.entities), 1)
                               if e_in_flows is not None else None),
        rules=len({r.id for r in m.rules}) or None,
        blocks=len({b.id for b in m.blocks}) or None,
        rule_sites=(sum(1 for r in m.rules for s in r.sites if (s.where or "").strip())
                    if m.rules else None),
        rules_swept=(sum(1 for v in validate_model.rules_swept(m).values() if v)
                     if m.rules else None),
        rules_unverified=(sum(1 for r in m.rules
                              if any((s.where or "").strip()
                                     and not validate_model.site_components(m, s, owners)
                                     for s in r.sites))
                          if m.rules else None),
        auth_surfaces=surfaces,
        auth_sites=auth_sites,
        auth_functions=auth_functions,
        interface_kinds=dict(sorted(kinds.items())),
        use_case_names=[u.name for u in m.use_cases if u.name.strip()],
        entity_names=[e.name for e in m.entities],
        commit=m.commit or None,
        component_names=sorted({c.name.strip() for c in m.components if c.name.strip()}),
        duplicate_component_names=(
            len([c for c in m.components if c.name and c.name.strip()])
            - len({c.name.strip().casefold() for c in m.components if c.name and c.name.strip()})),
        component_sources=sorted({(c.source or "").rsplit(":", 1)[0]
                                  for c in m.components if (c.source or "").strip()}),
        test_files=sorted({(inner.file or "").rsplit(":", 1)[0]
                           for t in m.tests for inner in (t.tests or [])
                           if (inner.file or "").strip()}),
    )


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────────

def _format(p: MapProfile) -> str:
    cov = "n/a (no --repo)" if p.coverage_flags is None else str(p.coverage_flags)
    gran = ("n/a (no --repo)" if p.granularity_expected is None
            else f"{p.components} components vs code-derived expectation ~{p.granularity_expected}")
    verdict = "OK" if p.validate_ok else f"FAILED ({p.validate_problems} problem(s))"
    return "\n".join([
        "Map profile — deterministic quality signals",
        "",
        f"  structure   : UC {p.use_cases} · S {p.subsystems} · SD {p.subdomains} · C {p.components} "
        f"· D {p.deps} · E {p.entities} · edges {p.edges} · HP {p.hp_steps} · flows {p.flows} "
        f"· auth-surfaces {p.security_surfaces}"
        + (f"\n  business    : BR {p.rules} in {p.blocks} block(s) · {p.rule_sites} site(s) · "
           f"{p.rules_swept} swept · {p.rules_unverified} unverified"
           if p.rules else ""),
        f"  validate    : {verdict}, {p.validate_warnings} warning(s)",
        f"  audit       : {p.contradictions} contradiction(s) · {p.audit_advisories} advisory · "
        f"{p.audit_warnings} warning(s) · {p.l2_claims} L2 claim(s)",
        f"  coverage    : {cov} compression/absent flag(s)",
        f"  deps        : {'n/a' if p.deps_without_bucket is None else p.deps_without_bucket} "
        f"with no bucket · "
        f"{'n/a (no --repo)' if p.packages_without_dep is None else p.packages_without_dep} "
        f"declared package(s) no dep names",
        f"  granularity : {gran}",
        ("  balance     : n/a (profile predates the balance fields)"
         if p.fanout_in_band_pct is None else
         f"  balance     : root fan-out {p.root_fanout} · max {p.max_fanout} · "
         f"{p.fanout_in_band_pct:.0%} of diagrams in the 3–9 band · depth {p.nesting_depth} "
         f"(report-only)"),
        ("  completeness: n/a (profile predates the completeness fields)"
         if p.entry_points is None else
         f"  completeness: entry points {p.entry_points} ({p.external_entry_points} external, "
         f"{'n/a' if p.unclaimed_entry_points is None else p.unclaimed_entry_points} unclaimed, "
         f"{'n/a' if p.named_entry_points is None else p.named_entry_points} named by a use case, "
         f"{'n/a' if p.stepped_entry_points is None else p.stepped_entry_points} run by a step, "
         f"{'n/a' if p.storyless_entry_points is None else p.storyless_entry_points} storyless) "
         f"· off-spine UCs {'n/a' if p.off_spine_ucs is None else p.off_spine_ucs} "
         f"· entities in flows "
         f"{'n/a' if p.entities_in_flows is None else f'{p.entities_in_flows} ({p.entities_in_flows_pct}%)'} "
         f"(report-only)"),
    ])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        print("usage: coyomap-eval score [.coyomap/project-map.json] [--repo <source-root>] [--json]\n\n"
              "Emit the deterministic quality profile of a built map (structure / validate / audit /\n"
              "coverage). `--repo` enables the coverage signal by re-measuring the source tree.\n"
              "`--json` prints the machine-readable MapProfile (for the eval baseline / comparator).")
        return 0
    repo_root: Path | None = None
    positional: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--repo":
            i += 1
            if i >= len(argv):
                print("ERROR: --repo needs a path", file=sys.stderr)
                return 2
            repo_root = Path(argv[i])
        elif a == "--json":
            pass
        elif a.startswith("-"):
            print(f"ERROR: unknown option '{a}'", file=sys.stderr)
            return 2
        else:
            positional.append(a)
        i += 1
    path = Path(positional[0] if positional else ".coyomap/project-map.json")
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        return 1
    if repo_root is not None and not repo_root.exists():
        print(f"ERROR: --repo {repo_root} not found", file=sys.stderr)
        return 1
    try:
        # READ-ONLY tolerance for a map an older coyomap wrote. `score` looking backwards at the map a
        # rebuild replaced is its whole job in a retrospective, and a schema rename used to make that
        # impossible: exit 1, no profile, and the reviewer hand-patching a copy to get a number.
        # Writing paths (assemble / validate / fix) keep the strict loader and the loud refusal.
        model, notes = load_model_tolerating_legacy(path.read_text(encoding="utf-8"))
        for note in notes:
            print(f"WARNING: {path}: {note}", file=sys.stderr)
        profile = build_profile_from_model(model, repo_root=repo_root, map_path=path)
    except ModelError as e:
        print(f"ERROR: {path}: {e}", file=sys.stderr)
        return 1
    print(profile.to_json() if "--json" in argv else _format(profile))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
