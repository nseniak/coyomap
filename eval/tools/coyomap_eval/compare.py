#!/usr/bin/env python3
"""`coyomap-eval compare` — score one map PROFILE against a baseline and apply the regression gates.

A map is LLM-authored, so the comparison is RELATIVE to a blessed baseline, never absolute: a real
baseline map carries some validate problems, so the gate is "no NEW problems", not "must pass". Two
kinds of check:

  HARD GATES  → a trip means REGRESSED (block). All relative to baseline:
                validate problems must not increase · contradictions must not increase · coverage
                flags must not increase past an allowance · the number of auth surfaces must not drop.
  BANDS       → a metric that drifts past ±allowance vs baseline is a softer DRIFT (a human look, not
                a block) — counts legitimately wander run-to-run, so this only flags the big moves.

One check is NOT baseline-relative: the GRANULARITY band measures the candidate's component count
against the CODE-DERIVED expectation E (profile `granularity_expected`, re-computed from the tree at
score time — the leaf anchor in method.md). Fairer than baseline-relative for the component count —
the baseline's own zoom may be off; the report shows BOTH maps' distance to the same E, but only the
candidate gates (outside band(E) → DRIFT, named as granularity). The shrink-only count bands stay as
collapse detectors and the density ratio stays the secondary check.

Verdict precedence: REGRESSED (any hard gate) > DRIFT (any band breach) > PASS. Exit codes mirror it
(REGRESSED=1, DRIFT=2, PASS=0) so an unattended run can gate on it.

Deterministic and stdlib-only. Semantic checks (did an auth surface disappear even though the COUNT
held, are the claims still faithful) belong to the Phase-3 judge layer — auth-surface NAMES drift with
LLM wording, so name-level matching here is informational, never a gate.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from coyomap.reporting import shown
from coyomap_eval.judge import JudgeReport
from coyomap_eval.profile import MapProfile

PASS = "PASS"
DRIFT = "DRIFT"
REGRESSED = "REGRESSED"
_EXIT = {PASS: 0, REGRESSED: 1, DRIFT: 2}

# The structural bands applied by default when no thresholds file is given. Two key forms, both naming
# a numeric MapProfile field: `<metric>_pct` is a symmetric band (drift past ±allowance either way
# breaches); `<metric>_shrink_pct` is SHRINK-ONLY (only a fall past the allowance breaches).
#
# Two tiers by design: the DENSITY ratio (edges_per_component) is the tight symmetric drift signal —
# it is scale-invariant, so a map that legitimately got finer (more components AND proportionally more
# edges) stays steady and does not trip. The raw COUNTS are shrink-only: growth means a finer map
# (whether the fineness is RIGHT is the altitude/completeness rubric's job, not a count band's), while
# a shrink is lost information — including the proportional collapse that holds density steady, which
# a symmetric-but-wide count band would wave through (review-2 finding). No `l2_claims` band: the
# worklist is derived from edges + auth rows, so banding it double-jeopardizes the same movement the
# edges band (and the auth-surface hard gate) already catches.
DEFAULT_BANDS: dict[str, float] = {
    "use_cases_shrink_pct": 0.30,
    "subsystems_shrink_pct": 0.30,
    "subdomains_shrink_pct": 0.30,
    "components_shrink_pct": 0.30,
    "deps_shrink_pct": 0.30,
    "entities_shrink_pct": 0.30,
    "edges_shrink_pct": 0.30,
    "hp_steps_shrink_pct": 0.30,
    "flows_shrink_pct": 0.30,
    "edges_per_component_pct": 0.25,
    # NOT here: `rules` and `rule_sites`. The rules layer is optional, so a DEFAULT band would print a
    # "skipped, not numeric on both sides" note on every comparison of a map without it
    # (`test_the_rule_fields_are_report_only_by_default`). The shipped `eval/thresholds.json` bands
    # both at 0.30, shrink-only: rules went 102 -> 79 -> 95 -> 88 across four mcpolis builds with
    # nothing watching, and every block of the last one came back on the contract's ceiling.
    # They are listed in `OPTIONAL_BANDS` below, so leaving them out is SAID rather than silent.
}

#: Band keys the shipped `eval/thresholds.json` carries and `DEFAULT_BANDS` deliberately does not.
#: Keeping them out of the code defaults is right (see the note above), and it was also INVISIBLE: a
#: caller that passes no `--thresholds` falls back to `DEFAULT_BANDS`, both metrics vanish from the
#: band table, and nothing says a word. `eval/retro/method.md` ran exactly that command, so no
#: retrospective's band table could ever have carried `rules` or `rule_sites` — the one thing the
#: 2026-09-08 decision to band them was for. A metric named here is reported as UNBANDED whenever
#: the maps actually carry a count for it and no band is in force.
OPTIONAL_BANDS: tuple[str, ...] = ("rules_shrink_pct", "rule_sites_shrink_pct")

# Judge bands are DROP-only (asymmetric): a rise in faithfulness/coverage is good, only a fall is a
# concern. Values are allowed ABSOLUTE drops in the metric's own units (pass-rate 0..1, scores 0..4).
# `grounding_failure_rate_max` is the exception — an absolute CAP on the candidate's judge-failure
# rate (n_failures/n_claims): grounding whose orchestration mostly failed must not read as PASS.
#: WHAT A BUILD COST, per row of map it produced, may RISE by at most this much before the verdict
#: says DRIFT. Per row, because the map grows while the method changes under it: across four mcpolis
#: builds absolute cost moved $189-$207 while the map grew 1,195 -> 1,564 rows, so an absolute band
#: reads growth as a regression. A fall is always within: cheaper is never a drift. Not a hard gate,
#: because a build costs what it costs; the point is that a change which gains a little quality and
#: doubles the bill cannot read PASS.
DEFAULT_SPEND_BANDS: dict[str, float] = {"cost_per_row": 0.25, "seconds_per_row": 0.25}

DEFAULT_JUDGE_BANDS: dict[str, float] = {
    "l2_grounding_passrate_drop": 0.10,
    "judge_score_drop": 0.10,
    "grounding_failure_rate_max": 0.25,
    # Phase G: Layer-2 anchor-drift rate. v1 INFORMATIONAL ONLY — surfaced in the report, not gated,
    # until real drift distributions are seen. The named hook is here so it can be promoted to a
    # blocking DRIFT verdict later without a config migration.
    "anchor_drift_rate_max": 1.0,
}


# The generous band around the code-derived granularity expectation E (a fraction of E, both
# directions). Deliberately wider than the count bands: E anchors the ZOOM, it does not decree the
# exact component count. Mirrors preindex_lib.GRANULARITY_BAND_PCT (kept as eval config so a project
# can tune its gate without touching the builder-facing constant).
DEFAULT_GRANULARITY_BAND_PCT = 0.40


@dataclass(frozen=True)
class Thresholds:
    validate_must_not_regress: bool = True
    no_new_contradictions: bool = True
    coverage_flags_may_increase_by: int = 0
    auth_surfaces_must_not_drop: bool = True
    deployment_linkage_must_not_drop: bool = True
    bands: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_BANDS))
    judge_bands: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_JUDGE_BANDS))
    granularity_band_pct: float = DEFAULT_GRANULARITY_BAND_PCT
    spend_bands: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SPEND_BANDS))

    @classmethod
    def from_config(cls, cfg: dict, project: str | None = None) -> "Thresholds":
        """Build from a parsed thresholds.json: `global` merged with `per_project[project]` overrides."""
        g = cfg.get("global", cfg)
        hard = dict(g.get("hard_gates", {}))
        # Bands MERGE onto the defaults (like hard_gates merge key-by-key). A partial `bands` override
        # tightening one metric must NOT silently drop the others — that would turn off drift detection
        # on the rest and let a real regression PASS (review Finding 2). Same for judge_bands.
        bands = dict(DEFAULT_BANDS)
        bands.update(g.get("bands", {}))
        jbands = dict(DEFAULT_JUDGE_BANDS)
        jbands.update(g.get("judge_bands", {}))
        gran = g.get("granularity_band_pct", DEFAULT_GRANULARITY_BAND_PCT)
        sbands = dict(DEFAULT_SPEND_BANDS)
        sbands.update(g.get("spend_bands", {}))
        pp = cfg.get("per_project", {}).get(project, {}) if project else {}
        sbands.update(pp.get("spend_bands", {}))
        hard.update(pp.get("hard_gates", {}))
        bands.update(pp.get("bands", {}))
        jbands.update(pp.get("judge_bands", {}))
        gran = pp.get("granularity_band_pct", gran)
        return cls(
            validate_must_not_regress=hard.get("validate_must_not_regress", True),
            no_new_contradictions=hard.get("no_new_contradictions", True),
            coverage_flags_may_increase_by=hard.get("coverage_flags_may_increase_by", 0),
            auth_surfaces_must_not_drop=hard.get("auth_surfaces_must_not_drop", True),
            deployment_linkage_must_not_drop=hard.get(
                "deployment_linkage_must_not_drop", True),
            bands=bands,
            judge_bands=jbands,
            granularity_band_pct=float(gran),
            spend_bands=sbands,
        )


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class BandResult:
    metric: str
    baseline: float
    candidate: float
    delta_pct: float     # signed fractional change vs baseline
    allowed_pct: float
    within: bool
    shrink_only: bool = False  # True: only a fall past the allowance breaches (growth is always within)


@dataclass(frozen=True)
class JudgeBand:
    metric: str
    baseline: float
    candidate: float
    drop: float          # baseline - candidate (positive = a drop, the concern)
    allowed_drop: float
    within: bool


@dataclass(frozen=True)
class Spend:
    """What one build cost, per row of the map it produced (`coyomap_eval.cost`). Either number may be
    missing: a transcript whose model has no list price has no cost."""
    rows: int
    cost_per_row: float | None
    seconds_per_row: float | None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "Spend":
        d = json.loads(text)
        return cls(int(d["rows"]), d.get("cost_per_row"), d.get("seconds_per_row"))

    @classmethod
    def from_cost(cls, rows: int, per_row: dict[str, float], unpriced: list[str]) -> "Spend | None":
        """From a cost report's numbers (`coyomap_eval.cost`). None when the report was made without
        the map, so there is no row count to divide by. The cost is left out when a model in the
        transcript has no list price: a bill missing part of itself would read as cheaper."""
        if not rows or not per_row:
            return None
        return cls(rows, None if unpriced else per_row.get("cost"), per_row.get("seconds"))


@dataclass(frozen=True)
class SpendBand:
    metric: str
    baseline: float
    candidate: float
    rise_pct: float      # signed fractional change vs baseline (positive = dearer, the concern)
    allowed_pct: float
    within: bool


@dataclass(frozen=True)
class GranularityResult:
    """Both maps' distance to the same CODE-DERIVED component expectation E (the leaf anchor). Fairer
    than baseline-relative for the component count — the baseline's own zoom may be off — so this is
    what gates: the CANDIDATE outside band(E) → DRIFT, named as granularity. The baseline's distance
    is reported alongside, informational only."""
    expected: int                 # E, re-computed from the code tree at score time
    baseline_components: int
    candidate_components: int
    baseline_delta_pct: float     # signed fractional distance of the baseline count from E
    candidate_delta_pct: float    # … of the candidate count (the gated one)
    allowed_pct: float
    within: bool                  # candidate inside the band → ok


@dataclass(frozen=True)
class DeltaReport:
    verdict: str                  # PASS | DRIFT | REGRESSED
    gates: list[GateResult]
    bands: list[BandResult]
    notes: list[str]              # informational (skipped gates, drifted names) — never gating
    judge_bands: list[JudgeBand] = field(default_factory=list)  # empty unless judge reports were given
    granularity: GranularityResult | None = None  # None when no profile carries E (scored without --repo)
    tool_delta: str | None = None  # set when the two maps were built by different coyomap builds.
    # Its own field, not a note: notes print last, and this one changes how everything above it is
    # read — a delta that spans a tool change is not evidence about the method.
    #: Profile metrics both maps carry a count for that NO band in force watches (`OPTIONAL_BANDS`).
    #: Its own field for the same reason `tool_delta` has one, and printed at the TOP and the BOTTOM
    #: of the report: a reader who `head`s the output and a reader who `tail`s it must both see that
    #: the band table is short of these rows. A silent skip is what kept `rules` out of every
    #: retrospective's band table since the day it was banded.
    unbanded: list[str] = field(default_factory=list)
    spend_bands: list[SpendBand] = field(default_factory=list)  # empty unless both sides carry a Spend

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def _metric_of(key: str) -> tuple[str, bool]:
    """The profile field a band key names, and whether the band is shrink-only.

    One reader for the key grammar, because two callers need it: the band loop, which applies the
    band, and the unbanded check, which has to name the same metric a band WOULD have watched."""
    if key.endswith("_shrink_pct"):
        return key[: -len("_shrink_pct")], True
    if key.endswith("_pct"):
        return key[: -len("_pct")], False
    return key, False


def _numeric(value: object) -> float | None:
    """`value` as a number, or None when it is not a comparable metric.

    None covers a ratio with a 0 denominator, a field a profile predates, and a `bool` — which is an
    `int` in Python and must never be banded as one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _unbanded_metrics(baseline: MapProfile, candidate: MapProfile,
                      t: Thresholds) -> list[str]:
    """The `OPTIONAL_BANDS` metrics BOTH these maps carry a count for and no band in force watches.

    Matched on the METRIC, never on the band key. The band loop resolves `rules_shrink_pct` and
    `rules_pct` to the same field through `_metric_of`, so a thresholds file spelling the band the
    other way is still watching `rules` — and a key-level test printed `[ok] rules: 88 -> 88` and
    "no band in force watches it" in one report.

    BOTH sides must carry a number, and the reason is that the line PRESCRIBES a remedy. When one
    side is None the band it tells you to turn on is demoted to a note anyway ("not a numeric
    profile metric on both sides"), so the advice would not produce the row it promises. The
    non-zero test keeps the quiet that leaving these out of `DEFAULT_BANDS` bought: a map with no
    rules layer reads 0 or None on both sides and hears nothing about them."""
    watched = {_metric_of(k)[0] for k in t.bands}
    out: list[str] = []
    for key in OPTIONAL_BANDS:
        metric, _ = _metric_of(key)
        if metric in watched:
            continue
        b = _numeric(getattr(baseline, metric, None))
        c = _numeric(getattr(candidate, metric, None))
        if b is not None and c is not None and (b or c):
            out.append(metric)
    return out


def _unbanded_line(metrics: list[str]) -> str:
    """The one sentence that names the missing rows. ONE writer, printed twice — the top copy and
    the bottom copy must not drift into two different claims."""
    return (f"NOT BANDED — {', '.join(metrics)}: both maps carry a count and no band in force "
            f"watches it, so nothing in this report would catch a collapse. Re-run with "
            f"`--thresholds eval/thresholds.json`, which bands them shrink-only; the built-in "
            f"defaults leave them out because the layer they measure is optional.")


def _band(metric: str, b_val: float, c_val: float, allowed: float,
          shrink_only: bool = False) -> BandResult:
    denom = max(abs(b_val), 1.0)
    delta = (c_val - b_val) / denom
    within = delta >= -(allowed + 1e-9) if shrink_only else abs(delta) <= allowed + 1e-9
    return BandResult(metric, b_val, c_val, delta, allowed, within, shrink_only)


def _compare_judge(baseline: JudgeReport, candidate: JudgeReport, t: Thresholds) -> list[JudgeBand]:
    """Drop-only judge bands: grounding pass-rate, overall score, and each shared rubric dimension. A
    rise is always within; only a drop past the allowance breaches (→ DRIFT). Plus the failure-rate
    cap: a candidate whose grounding orchestration mostly FAILED (no usable verdicts) breaches even
    though its pass-rate over the surviving denominator looks fine — broken judging must not PASS."""
    out: list[JudgeBand] = []
    if candidate.n_claims:
        # `drop` here is the signed CHANGE in failure rate (a rise is the concern); `allowed_drop` is
        # the absolute cap on the candidate's rate — the only judge band judged against a cap, not a
        # baseline delta, because a failure flood is a broken run regardless of what the baseline did.
        fr_allowed = t.judge_bands.get("grounding_failure_rate_max", 0.25)
        b_rate = (baseline.n_failures / baseline.n_claims) if baseline.n_claims else 0.0
        c_rate = candidate.n_failures / candidate.n_claims
        out.append(JudgeBand("grounding_failure_rate", b_rate, c_rate, c_rate - b_rate, fr_allowed,
                             c_rate <= fr_allowed + 1e-9))
    pr_allowed = t.judge_bands.get("l2_grounding_passrate_drop", 0.10)
    if baseline.grounding_passrate is not None and candidate.grounding_passrate is not None:
        drop = baseline.grounding_passrate - candidate.grounding_passrate
        out.append(JudgeBand("grounding_passrate", baseline.grounding_passrate,
                             candidate.grounding_passrate, drop, pr_allowed, drop <= pr_allowed + 1e-9))
    s_allowed = t.judge_bands.get("judge_score_drop", 0.10)
    if baseline.overall is not None and candidate.overall is not None:
        drop = baseline.overall - candidate.overall
        out.append(JudgeBand("overall_score", baseline.overall, candidate.overall, drop, s_allowed,
                             drop <= s_allowed + 1e-9))
    base_dims = {d.dimension: d.score for d in baseline.dimensions}
    for d in candidate.dimensions:
        if d.dimension in base_dims:
            drop = base_dims[d.dimension] - d.score
            out.append(JudgeBand(f"dim:{d.dimension}", base_dims[d.dimension], d.score, drop, s_allowed,
                                 drop <= s_allowed + 1e-9))
    return out


def _load_profile(text: str) -> MapProfile:
    """Load a profile, turning a refusal into a clean CLI error instead of a traceback.

    `MapProfile.from_json` refuses a profile written before `advisories` became
    `audit_advisories` — deliberately, because silently reading 0 would relocate the misreading
    rather than fix it. But every other error path in this CLI prints `ERROR: …` and returns 2,
    and a stack trace on a stale baseline reads as a crash rather than as the instruction it is."""
    try:
        return MapProfile.from_json(text)
    except ValueError as e:
        raise SystemExit(f"ERROR: {e}")


def _compare_spend(baseline: Spend, candidate: Spend,
                   t: Thresholds) -> tuple[list[SpendBand], list[str]]:
    """Rise-only bands on what a build cost per row: a rise past the allowance breaches (→ DRIFT).

    Also the metrics it could NOT compare, because a side has no number for it: a build on a model
    with no list price has no cost. Returned so the report can say so, instead of reading PASS on a
    band that never ran."""
    out: list[SpendBand] = []
    skipped: list[str] = []
    for metric, allowed in sorted(t.spend_bands.items()):
        b, c = getattr(baseline, metric, None), getattr(candidate, metric, None)
        if not isinstance(b, (int, float)) or not isinstance(c, (int, float)) or b <= 0:
            skipped.append(metric)
            continue
        rise = (c - b) / b
        out.append(SpendBand(metric, float(b), float(c), rise, allowed, rise <= allowed))
    return out, skipped


def compare(baseline: MapProfile, candidate: MapProfile, thresholds: Thresholds | None = None,
            baseline_judge: JudgeReport | None = None,
            candidate_judge: JudgeReport | None = None,
            baseline_spend: Spend | None = None, candidate_spend: Spend | None = None) -> DeltaReport:
    """Apply the relative hard gates + bands, returning a ranked DeltaReport with a PASS/DRIFT/REGRESSED
    verdict. `thresholds` defaults to the built-in defaults (all hard gates on, DEFAULT_BANDS). When
    BOTH judge reports are given, drop-only judge bands are applied too (a breach → DRIFT)."""
    t = thresholds or Thresholds()
    gates: list[GateResult] = []
    notes: list[str] = []
    tool_delta: str | None = None
    if baseline.tool_commit is None and candidate.tool_commit is None:
        # UNKNOWN vs UNKNOWN is not equality. Two maps from two different installs both stamp
        # None, and `!=` alone read that as "same tool" — the one conclusion this field exists to
        # prevent. Every map built before the stamp existed is in this case.
        tool_delta = ("neither map records which coyomap built it — both predate the stamp, or "
                      "both were built by an install outside a clone. They may be from different "
                      "tools; nothing here can tell")
    elif baseline.tool_commit != candidate.tool_commit:
        # A tool change moves what a map can even CONTAIN — one moved auth surfaces between two
        # storages with no migration — so a delta across it is not a delta in map quality.
        # Informational, never gating: which side regressed is not knowable from here.
        def _tool(c: str | None, d: str | None) -> str:
            return f"{c} ({d})" if c and d else (c or "unknown, built before the stamp existed")
        tool_delta = (f"baseline {_tool(baseline.tool_commit, baseline.tool_committed)}, "
                      f"candidate {_tool(candidate.tool_commit, candidate.tool_committed)}")

    if t.validate_must_not_regress:
        ok = candidate.validate_problems <= baseline.validate_problems
        gates.append(GateResult("validate-no-regress", ok,
            f"validate problems {baseline.validate_problems} -> {candidate.validate_problems}"))
    if t.no_new_contradictions:
        ok = candidate.contradictions <= baseline.contradictions
        gates.append(GateResult("no-new-contradictions", ok,
            f"contradictions {baseline.contradictions} -> {candidate.contradictions}"))
    # Coverage — comparable only when BOTH sides were scored with --repo.
    if baseline.coverage_flags is None or candidate.coverage_flags is None:
        notes.append("coverage gate skipped — a profile was scored without --repo (coverage_flags is null)")
    else:
        delta = candidate.coverage_flags - baseline.coverage_flags
        ok = delta <= t.coverage_flags_may_increase_by
        gates.append(GateResult("coverage-no-regress", ok,
            f"coverage flags {baseline.coverage_flags} -> {candidate.coverage_flags} "
            f"(allowed +{t.coverage_flags_may_increase_by})"))
    if t.auth_surfaces_must_not_drop:
        ok = candidate.security_surfaces >= baseline.security_surfaces
        gates.append(GateResult("auth-surfaces-no-drop", ok,
            f"auth surfaces {baseline.security_surfaces} -> {candidate.security_surfaces}"))
        dropped = [s for s in baseline.auth_surfaces if s not in set(candidate.auth_surfaces)]
        if dropped:
            # TRUNCATED, and it was not: a real pair dumped 50 full rule statements here — hundreds
            # of words that pushed the two readable notes below it off the operator's screen. A
            # statement is a paragraph, so even one is long; the point of this note is the COUNT plus
            # a taste, and the site notes below carry the part worth acting on.
            head = "; ".join(s[:90] + ("…" if len(s) > 90 else "") for s in dropped[:3])
            more = f" (+{len(dropped) - 3} more, in the JSON report)" if len(dropped) > 3 else ""
            notes.append(f"{len(dropped)} auth surface(s) in baseline but not (by name) in candidate "
                         f"— names drift with LLM wording, so verify rather than trust: {head}{more}")
        notes.extend(_auth_site_notes(baseline, candidate))
    notes.extend(_reproducibility_notes(baseline, candidate))
    notes.extend(_source_root_notes(baseline, candidate))
    notes.extend(_interface_kind_notes(baseline, candidate))
    notes.extend(_dependency_notes(baseline, candidate))

    if t.deployment_linkage_must_not_drop and not baseline.deployment_units:
        # Silence here is indistinguishable from "the gate passed". A baseline blessed before this
        # field existed carries 0, which turns the gate off invisibly — the coverage gate already
        # prints a note for its own version of this and this one did not.
        notes.append("deployment-linkage gate skipped — the baseline profile predates the "
                     "deployment_units field (re-bless the baseline to enable it)")
    if t.deployment_linkage_must_not_drop and baseline.deployment_units:
        # LINKAGE, not coverage. A live rebuild kept all eight deployment units, dropped the two
        # components that owned the nginx and vector files, and filled `runs_in` by contiguous
        # component-id range — a formula that can only produce contiguous buckets, so six of the
        # eight boxes ended up with nothing running in them. The Deployment view still rendered.
        # `runs_in` coverage went 93/96 -> 66/66 across the same rebuild: a PERFECT score, produced
        # by dumping every component into two units. Coverage was the number being watched and it
        # moved the right way while the view got poorer, which is why this gate counts units that
        # some component actually claims instead.
        #
        # It counted LINKED UNITS to do that, and then punished a map for getting better. A later
        # rebuild named 4 units, all first-party runtimes, all linked; its successor named 11 — the
        # same 3 runtimes plus the proxy, two datastores, the log forwarder, two test instances and
        # two test doubles — and correctly folded a unit that was really a mount inside the backend
        # process into that process. Linked went 4/4 -> 3/11 and this gate FAILED, on a section that
        # had gained seven honest boxes and lost nothing. An infra unit hosts no first-party code BY
        # NATURE, so it can never be "linked", and every one added drove the number DOWN.
        #
        # ORPHANS are the number that means what the gate is for: units running nothing that are not
        # infra either — the genuinely empty boxes. It is also the list `validate` advises on, via
        # the shared `validate_model.orphan_deployment_units`, so tool and gate cannot drift apart.
        #
        # The gate does NOT honour the map's recorded `runs-in/quality` exception, and the first cut
        # of it did. That was wrong, and an adversarial review demonstrated it end to end: the
        # literal covers five different sub-checks (unit naming, variant tagging, formula-fill,
        # orphan units, entry hosts), `validate` actively suggests recording it for reasons that
        # have nothing to do with placement, and nothing requires the justification to mention the
        # orphaned units. So one TRUE sentence about the infra units — "the four infra units run no
        # first-party code by design" — turned a REGRESSED verdict into a full green run on a map
        # with two genuinely empty boxes. A hard gate whose input is authored by the thing being
        # gated is not a gate.
        #
        # The parity-with-`validate` argument that motivated the waiver does not survive contact
        # with who reads this: `compare` is the METHOD DEVELOPER's regression check between two
        # builds, and a build never runs it (assertion 29 exists to keep a build from reading the
        # previous map at all). Nobody is holding a green `validate` and a red gate about one map.
        # An advisory may be waivable by its subject; a regression gate may not.
        if baseline.deployment_orphan_units is None or candidate.deployment_orphan_units is None:
            # 0 is the STRICTEST value here, so defaulting a pre-field profile to it made the gate
            # fail a map against ITSELF — the exact bug class this whole gate was rewritten to fix,
            # reintroduced for every existing baseline. Skip with a note, which is what both sibling
            # deployment gates do and what this file's policy requires.
            notes.append("deployment-linkage gate skipped — a profile predates the "
                         "`deployment_orphan_units` field (re-score and re-bless to enable it)")
        elif baseline.deployment_runs_in_adopted and not candidate.deployment_runs_in_adopted:
            # Orphans are 0 by construction on a map that places nothing, so the emptiest possible
            # Deployment view scored better than a partly-filled one. This is the one shape where
            # the orphan count cannot speak, so the gate answers it directly rather than reporting
            # an improvement on a section that just went blank.
            gates.append(GateResult("deployment-linkage-no-drop", False,
                f"the candidate sets `runs_in` NOWHERE, so all "
                f"{candidate.deployment_units} declared unit(s) are empty boxes — the baseline "
                f"placed code in {baseline.deployment_units_linked}. Orphans read 0 here only "
                f"because nothing is placed at all"))
        else:
            ok = candidate.deployment_orphan_units <= baseline.deployment_orphan_units
            gates.append(GateResult("deployment-linkage-no-drop", ok,
                f"empty deployment units (running nothing, not infra) "
                f"{baseline.deployment_orphan_units} -> {candidate.deployment_orphan_units}"
                f" · units hosting a component "
                f"{baseline.deployment_units_linked}/{baseline.deployment_units} -> "
                f"{candidate.deployment_units_linked}/{candidate.deployment_units}"
                f" · distinct hosted component sets "
                f"{baseline.deployment_distinct_hosted_sets} -> "
                f"{candidate.deployment_distinct_hosted_sets}"))
        # Counting units let a hollow improvement pass: 2/8 -> 3/10 on a map whose three linked
        # units hosted the identical 50 components. Adding a deployment SHAPE of the same process
        # raises the unit count and cannot raise this one. Baselines written before the field carry
        # 0, which makes the comparison vacuously true rather than falsely failing — the same
        # direction the `deployment_units` skip above chose.
        if not baseline.deployment_distinct_hosted_sets:
            # Same hazard the `deployment_units` skip 15 lines above prints a note for: a baseline
            # blessed before the field carries 0, `cand >= 0` is always true, and a HARD gate is off
            # with nothing saying so. Silence here is indistinguishable from "the gate passed".
            notes.append("deployment-distinct-hosts gate is vacuous — the baseline profile carries "
                         "no `deployment_distinct_hosted_sets` (re-score and re-bless the baseline "
                         "to enable it)")
        sets_ok = (candidate.deployment_distinct_hosted_sets
                   >= baseline.deployment_distinct_hosted_sets)
        gates.append(GateResult("deployment-distinct-hosts-no-drop", sets_ok,
            f"distinct component sets hosted across the units "
            f"{baseline.deployment_distinct_hosted_sets} -> "
            f"{candidate.deployment_distinct_hosted_sets}"))
        # A DROP explained by the variants merge is not a loss of modelling. `method.md` models one
        # process across environments as ONE unit with a variant each; the alternative — a unit per
        # environment — inflates the distinct-set count, so adopting the prescribed form READS as a
        # regression. The gate itself must not move (a test pins that another shape of the same
        # process cannot buy linkage), so say what happened instead. On the pair this came from,
        # units carrying 2+ variants went 1 of 6 to 2 of 5 while the gate failed 3 -> 2.
        if (not sets_ok
                and baseline.deployment_units_multi_variant is not None
                and candidate.deployment_units_multi_variant is not None
                and candidate.deployment_units_multi_variant
                > baseline.deployment_units_multi_variant
                and candidate.deployment_units < baseline.deployment_units):
            notes.append(
                f"deployment-distinct-hosts dropped while the candidate FOLDED units into variants: "
                f"units carrying 2+ `variants` {baseline.deployment_units_multi_variant} -> "
                f"{candidate.deployment_units_multi_variant} across "
                f"{baseline.deployment_units} -> {candidate.deployment_units} unit(s). method.md "
                f"models one process in several environments as ONE unit with a variant each, so "
                f"this gate reads the prescribed form as a regression. Check the fold is real "
                f"before treating the FAIL as one")
        if (candidate.deployment_units_linked > candidate.deployment_distinct_hosted_sets
                and candidate.deployment_distinct_hosted_sets):
            notes.append(
                f"{candidate.deployment_units_linked} unit(s) host only "
                f"{candidate.deployment_distinct_hosted_sets} distinct component set(s) — some units "
                f"are deployment SHAPES of the same process, so linkage reads higher than the number "
                f"of real placement decisions. Check that the components in no unit at all are "
                f"deliberate")
        # Keyed on the ORPHAN count, not on a gate variable: the gate is skipped entirely when a
        # profile predates the field, and reading its `ok` there was both unbound and meaningless.
        if candidate.deployment_orphan_units:
            notes.append("a unit nothing runs in is an empty box in the Deployment view — check "
                         "whether the components that owned those files were dropped, and whether "
                         "`runs_in` was filled from the deploy manifests or from an id-range formula")

    # Granularity — both counts measured against the same code-derived E; only the CANDIDATE gates.
    # The gate uses the CANDIDATE profile's E only: that is the value re-computed from the tree at
    # check time (score --repo) — a candidate scored without the repo has no check-time E, so the
    # band degrades to a note rather than gating against a stale baseline value. Both sides score
    # the same pinned tree, so a baseline E that disagrees is surfaced as a note.
    granularity: GranularityResult | None = None
    e_b, e_c = baseline.granularity_expected, candidate.granularity_expected
    if e_c is None or e_c <= 0:
        notes.append("granularity band skipped — the candidate profile carries no code-derived "
                     "component expectation (score the fresh map with --repo)")
    else:
        if e_b is not None and e_b != e_c:
            notes.append(f"code-derived component expectation differs between the profiles "
                         f"(baseline {e_b} vs candidate {e_c}) — the tree changed between scorings; "
                         f"the candidate's E gates")
        c_delta = (candidate.components - e_c) / e_c
        b_delta = (baseline.components - e_c) / e_c
        granularity = GranularityResult(
            expected=e_c, baseline_components=baseline.components,
            candidate_components=candidate.components, baseline_delta_pct=b_delta,
            candidate_delta_pct=c_delta, allowed_pct=t.granularity_band_pct,
            within=abs(c_delta) <= t.granularity_band_pct + 1e-9)

    bands: list[BandResult] = []
    for key in sorted(t.bands):
        metric, shrink_only = _metric_of(key)
        b_val = _numeric(getattr(baseline, metric, None))
        c_val = _numeric(getattr(candidate, metric, None))
        if b_val is None or c_val is None:
            # Also hit by a None ratio (0-denominator, or a baseline profile written before the field
            # existed) — degrade to a note, never crash or fake a 0.
            note = f"band '{key}' skipped — '{metric}' is not a numeric profile metric on both sides"
            if b_val is not None and c_val is None:
                # THE DIRECTION MATTERS, and the generic wording hid it. An adoption-dependent count
                # is written `len(...) or None`, so a layer that VANISHES reads None rather than 0 —
                # the band is demoted to this note and the verdict stays PASS. A shrink band catches
                # `88 rules -> 20`; it cannot see `88 rules -> the section is gone`, which is the
                # worse of the two. Naming the direction is all this note can do: it does not gate.
                note += (f". The BASELINE carried {b_val:g} and the candidate carries nothing, so "
                         f"this may be the whole layer disappearing rather than a field the profile "
                         f"predates — no band can see that, and the verdict does not move on it")
            notes.append(note)
            continue
        bands.append(_band(metric, b_val, c_val, t.bands[key], shrink_only))
    # A band the thresholds in force do not carry at all was skipped in SILENCE, which is a
    # different failure from the note above: nothing named the metric, so nothing told a reader the
    # table was short a row. `unbanded` is printed at both ends of the report.
    unbanded = _unbanded_metrics(baseline, candidate, t)

    jbands = _compare_judge(baseline_judge, candidate_judge, t) \
        if baseline_judge is not None and candidate_judge is not None else []
    if (baseline_judge is not None and candidate_judge is not None
            and baseline_judge.protocol is not None and candidate_judge.protocol is not None
            and baseline_judge.protocol != candidate_judge.protocol):
        # Two sides judged under DIFFERENT protocols (model / n_skeptics / cap / rubric) are not
        # comparable — a stale-cache smell (`coyomap-eval protocol --against` is the upstream guard).
        # Surfaced as a breached band → DRIFT, mirroring the judge_report_missing sentinel.
        jbands.append(JudgeBand("judge_protocol_mismatch", 1.0, 0.0, 1.0, 0.0, False))
        notes.append("judge-protocol fingerprint differs between baseline and candidate "
                     f"(baseline {baseline_judge.protocol.__dict__} vs candidate "
                     f"{candidate_judge.protocol.__dict__}) — re-judge the baseline under the "
                     "current protocol (delete the baseline map's "
                     ".coyomap-eval/cache/<map sha12>/judge.json)")
    if (baseline_judge is None) != (candidate_judge is None):
        # EITHER side missing a judge report skips the semantic gates entirely, and a skipped gate
        # must never read as a passed one. This used to breach in one direction only — the old design
        # always had a judged baseline (the project's committed map, cached) and a freshly built
        # candidate, so "candidate unjudged" was the only reachable half. Now the baseline is an
        # ARCHIVED map whose cache dir is filled profile-first, judge-second, so an interrupted or
        # failed judging leaves a profile-only baseline; that half used to be a bare note. Measured:
        # a candidate judge reporting 0/40 grounded with 40 judge FAILURES compared clean, because
        # `grounding_failure_rate_max` — the cap whose whole job is "broken judging must not PASS" —
        # only runs when both sides have a report. Breach → DRIFT, in both directions.
        jbands.append(JudgeBand("judge_report_missing", 1.0, 0.0, 1.0, 0.0, False))
        if candidate_judge is None:
            notes.append("candidate has NO judge report while the baseline does — the semantic gates "
                         "were skipped; judge the candidate map (method.md Step 4) and re-run with "
                         "--judge")
        else:
            notes.append("baseline has NO judge report while the candidate does — the semantic gates "
                         "were skipped; judge the baseline map (method.md Step 4) into its "
                         ".coyomap-eval/cache/<map sha12>/judge.json and re-run")

    sbands: list[SpendBand] = []
    if baseline_spend is not None and candidate_spend is not None:
        sbands, unmeasured = _compare_spend(baseline_spend, candidate_spend, t)
        for metric in unmeasured:
            notes.append(f"{metric.replace('_', ' ')} was not compared: one side has no number for it "
                         f"(a build on a model with no list price has no cost), so the verdict says "
                         f"nothing about it")
    if (baseline_spend is None) != (candidate_spend is None):
        # A NOTE, not a breach: what a build cost is measured from its transcript, and a baseline
        # blessed before this band existed has none. It would DRIFT every run until re-blessed.
        notes.append("what the build cost was measured on one side only — give each map a spend.json "
                     "(`coyomap-eval cost <transcript> --map <map> --spend-out`) to compare cost and "
                     "time per row")

    if any(not g.passed for g in gates):
        verdict = REGRESSED
    elif (any(not b.within for b in bands) or any(not j.within for j in jbands)
          or any(not s.within for s in sbands)
          or (granularity is not None and not granularity.within)):
        verdict = DRIFT
    else:
        verdict = PASS
    return DeltaReport(verdict, gates, bands, notes, jbands, granularity, tool_delta, unbanded, sbands)


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────────


def _overlap(b: set[str], c: set[str]) -> tuple[int, int]:
    """`(in both, in either)` for two name sets — the two numbers every agreement line here needs.

    One function because two callers computed the same Jaccard by hand and could have drifted apart
    on the empty case: `max(len(union), 1)` is what keeps a percentage of nothing from dividing by
    zero, and it belongs in one place."""
    return len(b & c), max(len(b | c), 1)


#: The element kinds a rebuild is compared on. ACCESSORS, not attribute-name strings: a typo in a
#: string is invisible to pyright and reports the kind as "a profile predates the field", which is a
#: false explanation rather than an error. One was injected during review and the type checker
#: passed it.
_REBUILD_KINDS: tuple[tuple[str, Callable[[MapProfile], list[str] | None]], ...] = (
    ("component names", lambda p: p.component_names),
    ("component SOURCE files", lambda p: p.component_sources),
    ("use-case names", lambda p: p.use_case_names),
    ("entity names", lambda p: p.entity_names),
    ("test FILES cited", lambda p: p.test_files),
)


def _same_commit(baseline: MapProfile, candidate: MapProfile) -> tuple[bool, str]:
    """`(the two maps pin one commit, what to say about the pin)`.

    Two normalisations, both found by comparing real profiles rather than by reasoning:

    * `-dirty` is stripped before comparing, the way `impact_git` already strips it. Without that
      `5dccb1c` and `5dccb1c-dirty` read as different commits and the comparison went silent between
      two builds of the same code. A dirty pin is still WORTH SAYING, because uncommitted code can
      differ between the two builds and then a changed name may be the code after all.
    * The shorter pin is compared as a PREFIX of the longer. `git rev-parse --short` lengthens as a
      repo grows and different repos stamp different widths — mcpolis stamps 7 characters, coworker
      stamps 9 — so requiring equal length disabled the measure on a pair that shared a commit."""
    b = (baseline.commit or "").strip().removesuffix("-dirty")
    c = (candidate.commit or "").strip().removesuffix("-dirty")
    if not b or not c:
        return False, ""
    short, long = (b, c) if len(b) <= len(c) else (c, b)
    if not long.startswith(short):
        return False, ""
    dirty = [w for w, p in (("baseline", baseline), ("candidate", candidate))
             if (p.commit or "").strip().endswith("-dirty")]
    note = (f" (the {' and '.join(dirty)} pin says `-dirty`, so uncommitted code could differ "
            f"between the two builds)" if dirty else "")
    return True, note


def _source_root_notes(baseline: MapProfile, candidate: MapProfile) -> list[str]:
    """Top-level source roots the baseline's elements cite and the candidate's cite nowhere.

    `internal/` left the 2026-09-08 mcpolis map whole — 27 mentions to 0, its 17 code files
    unchanged in git — and every gate stayed green, because the walker lists `internal` as a
    non-product directory and no check was ever meant to look there. Right or wrong, a root the
    previous map described and this one describes nowhere is worth one line, so the move is
    recorded rather than silent. Reported, never gated: the convention may be the reason."""
    for p in (baseline, candidate):
        if p.component_sources is None or p.test_files is None or p.auth_sites is None:
            return []            # a profile predating one of the three fields: nothing to compare

    def roots(p: MapProfile) -> set[str]:
        cited = [*(p.component_sources or []), *(p.test_files or []), *(p.auth_sites or [])]
        return {c.split("/", 1)[0] for c in cited if "/" in c}

    lost = sorted(roots(baseline) - roots(candidate))
    if not lost:
        return []
    return [f"{len(lost)} source root(s) the baseline cites and the candidate cites nowhere in the "
            f"fields this note reads (component sources, test files, access sites): "
            f"{', '.join(r + '/' for r in lost)} — a scope decision, a loss, or a root the candidate "
            f"names only in `files` or ways in; read the map before deciding"]


def _interface_kind_notes(baseline: MapProfile, candidate: MapProfile) -> list[str]:
    """Interface kinds the baseline had and the candidate has none of.

    The only `handoff` surface of a map went 1 -> 0 on a rebuild while its `mailto:` sites stayed in
    the code, and the use case that crossed it went with it — so the advisory that guards a walk's
    reply could not fire, and no count moved. A kind at zero is a surface lost or re-kinded; the
    map says which."""
    if baseline.interface_kinds is None or candidate.interface_kinds is None:
        return []
    lost = [(k, n) for k, n in sorted(baseline.interface_kinds.items())
            if n and not candidate.interface_kinds.get(k)]
    if not lost:
        return []
    return [f"{len(lost)} interface kind(s) the baseline had and the candidate has none of: "
            + ", ".join(f"{k} ({n} -> 0)" for k, n in lost)
            + " — a surface lost or re-kinded; the code decides which"]


def _dependency_notes(baseline: MapProfile, candidate: MapProfile) -> list[str]:
    """Deps with no authored bucket, and declared packages no dep names, whenever the candidate has
    any. Reported, never gated, like the interface kinds above: the 2026-10-08 mcpolis rebuild went
    from 29 deps to 19, all 19 with no bucket, and the only row that moved was `deps` itself, still
    inside its band. A side scored before the field, or without `--repo`, reads n/a."""
    def n(v: int | None) -> str:
        return "n/a" if v is None else str(v)
    out: list[str] = []
    if candidate.deps_without_bucket:
        out.append(f"deps with no authored bucket {n(baseline.deps_without_bucket)} -> "
                   f"{candidate.deps_without_bucket} of {candidate.deps}: the viewer guesses their "
                   f"groups")
    if candidate.packages_without_dep:
        out.append(f"declared packages no dep names {n(baseline.packages_without_dep)} -> "
                   f"{candidate.packages_without_dep}: libraries the Dependencies view does not "
                   f"show (`validate --check-coverage` lists them)")
    return out


def _reproducibility_notes(baseline: MapProfile, candidate: MapProfile) -> list[str]:
    """How much of the baseline map SURVIVES a rebuild, name by name. Reported, never gated.

    Every gate in this file compares COUNTS, and a count is exactly the measurement this failure
    walks through. Two mcpolis builds of commit `5dccb1c`, 21 hours apart with no product file
    changed, sat in band on every count that gates — and 61 of the baseline's 70 component names do
    not appear in the rebuild at all. Nothing measured that until this ran; the only reason anyone
    knew was a hand count during a retrospective.

    THE DENOMINATOR IS THE BASELINE, not the union, and the difference is not cosmetic. Union
    punishes a candidate for SPLITTING: a rebuild that keeps every one of 70 baseline names and adds
    48 new ones scores 59 % of union while having renamed nothing. "How much of the baseline
    survived" is the question a reader actually has, and it separates renaming from splitting. The
    union figure rides along in parentheses because it is what a Jaccard-shaped reader expects.

    EXACT match, and it under-reports. Measured across 39 same-commit pairs, a fuzzy match (case,
    punctuation, light stemming, token overlap >= 0.6) roughly quadruples the component-name figure —
    on the pair above, 9 exact becomes 22 fuzzy, because `Log-forwarding pipeline` / `Log forwarding
    pipeline` and `Tool call router` / `Tool router` are the same box named twice. The exact figure
    is kept because it is reproducible and has no threshold to argue about, and the line says which
    it is so nobody quotes it as "87 % of the map was rebuilt differently".

    THE COMMIT GUARD IS A LABEL, NOT A FILTER. Measured over 48 same-commit and 10 consecutive
    different-commit pairs, the medians are indistinguishable (component names 2 % vs 1 %, sources
    39 % vs 40 %, entities 76 % vs 78 %). So the commit does not predict agreement, and an earlier
    draft of this function suppressed the numbers across two commits on a theory the data does not
    support. It now always reports, and says which case the reader is looking at.

    NOT gated, following `_auth_site_notes`: two independent LLM builds legitimately differ, no
    threshold has been defended across enough pairs, and a gate on an undefended threshold fails
    every rebuild. Sources are reported beside names on purpose — names low with sources high says
    the two builds CUT the code the same way and NAMED it differently, a different repair from
    cutting it differently."""
    same, dirty_note = _same_commit(baseline, candidate)
    if same:
        head = (f"REBUILD AGREEMENT — both maps pin commit {(candidate.commit or '').strip()}, so a "
                f"name only one of them carries is the map moving{dirty_note}:")
    elif (baseline.commit or "").strip() and (candidate.commit or "").strip():
        head = (f"REBUILD AGREEMENT — the maps pin different commits "
                f"({baseline.commit} -> {candidate.commit}), so some renaming is the CODE moving. "
                f"Measured across 58 pairs the commit barely predicts these numbers, so they are "
                f"still worth reading:")
    else:
        head = ("REBUILD AGREEMENT — at least one profile carries no `commit` pin, so whether the "
                "two maps describe the same code is unknown. Re-bless it to label these numbers:")
    rows: list[str] = []
    missing: list[str] = []
    for label, get in _REBUILD_KINDS:
        b, c = get(baseline), get(candidate)
        if b is None or c is None:
            missing.append(label)
            continue
        bs, cs = set(b), set(c)
        if not bs and not cs:
            continue
        shared, union = _overlap(bs, cs)
        kept = f"{shared} of {len(bs)} survive ({100 * shared // max(len(bs), 1)} %)"
        rows.append(f"    {label}: {len(bs)} -> {len(cs)}, {kept}"
                    f" · {100 * shared // union} % of the union · exact match, which under-reports")
    # The skipped list is emitted even when NO kind could be compared. An earlier draft returned
    # early on an empty `rows`, so a pair of profiles that both predate every field printed nothing
    # at all — silence, which is the one thing every escape family here has had to stop doing.
    notes = ([head] + rows) if rows else []
    if missing:
        notes = notes or ["REBUILD AGREEMENT — nothing could be compared:"]
        notes.append(f"    ({len(missing)} kind(s) skipped — a profile predates the field: "
                     f"{', '.join(missing)}; re-bless whichever profile is older)")
    return notes


def _auth_site_notes(baseline: MapProfile, candidate: MapProfile) -> list[str]:
    """How much of the auth surface's ENFORCEMENT LOCATIONS the two maps agree on.

    `auth-surfaces-no-drop` counts distinct STATEMENTS, which are LLM prose. That gate is necessary
    and it is not sufficient: on two mcpolis builds of the SAME commit the count moved 50 -> 44
    (caught) while the anchor sets shared only 57 of 163 and 17 files holding access enforcement in
    one map were claimed by no access rule in the other (invisible). A count can hold steady through
    a wholesale change of content, so the count alone cannot say whether a surface was re-worded,
    merged, lost, or newly found.

    Reported, never gated. Two independent LLM builds legitimately differ, so a hard gate here would
    fail every rebuild; what the operator needs is the churn in front of them, with the wording-free
    part — a file that lost its access coverage entirely — named. The dropped-by-name note above
    tells you to "verify rather than trust", and these are the numbers to verify against.
    """
    if baseline.auth_sites is None or candidate.auth_sites is None:
        # Silence would read as agreement. A profile blessed before `auth_sites` existed carries
        # None, exactly like the deployment-linkage gate's own version of this.
        return ["auth-site comparison skipped — a profile predates the `auth_sites` field "
                "(re-bless the baseline to enable it)"]
    b, c = set(baseline.auth_sites), set(candidate.auth_sites)
    if not b and not c:
        return []
    shared, union = _overlap(b, c)
    notes = [f"auth ENFORCEMENT LINES: {len(b)} -> {len(c)}, {shared} in both "
             f"({100 * shared // union} % of the union). A statement count can hold "
             f"steady while the lines it points at change wholesale, so read this beside the gate."]
    bf = {a.rsplit(":", 1)[0] for a in b}
    cf = {a.rsplit(":", 1)[0] for a in c}
    lost = sorted(bf - cf)
    if lost:
        notes.append(f"{len(lost)} file(s) held access enforcement in the baseline and are named by "
                     f"NO access rule in the candidate — wording-independent, so these are the ones "
                     f"to read first: {shown(lost, 8)}")
    gained = sorted(cf - bf)
    if gained:
        notes.append(f"{len(gained)} file(s) carry access enforcement only in the candidate — the "
                     f"baseline missed them, so neither map's surface is complete.")
    # BY FUNCTION: the same sites with the line dropped and the enclosing definition kept. Two
    # builds choose the same places and different lines in them (the 2026-08-29 finding), so
    # the line number above mixes real losses with jitter inside one function. This number
    # cannot: a function that lost its rule stays lost, a line that moved inside it agrees.
    if baseline.auth_functions is not None and candidate.auth_functions is not None:
        fb, fc = set(baseline.auth_functions), set(candidate.auth_functions)
        if fb or fc:
            fshared, funion = _overlap(fb, fc)
            notes.append(f"auth ENFORCEMENT FUNCTIONS: {len(fb)} -> {len(fc)}, {fshared} in both "
                         f"({100 * fshared // funion} % of the union) — the line agreement above "
                         f"minus the jitter inside one function; the gap between the two "
                         f"numbers is how much of the churn is placement.")
    return notes


def format_report(report: DeltaReport) -> str:
    # Judge/quality deltas lead; the raw structural counts come last — they are the noisiest signal.
    out = [f"Comparison verdict: {report.verdict}", ""]
    # TOP COPY. The bottom copy is the last line of the report, and both are wanted: a reader who
    # pipes this through `head` and a reader who pipes it through `tail` must each be told that the
    # band table below is missing rows. A skip that only whispers in the notes is what let `rules`
    # go unwatched through every retrospective since it was banded.
    if report.unbanded:
        out.append(_unbanded_line(report.unbanded))
        out.append("")
    if report.tool_delta:
        out.append(f"COYOMAP BUILD — {report.tool_delta}.")
        out.append("A delta below may belong to the tool rather than the method. Rule the tool out "
                   "before reading one as the method: a breaking change with no migration once made "
                   "this report say REGRESSED about a map that was simply newer.")
        out.append("")
    if report.judge_bands:
        out.append("Judge bands (drop vs baseline):")
        for j in report.judge_bands:
            tag = "ok" if j.within else "DRIFT"
            out.append(f"  [{tag}] {j.metric}: {j.baseline:g} -> {j.candidate:g} "
                       f"(change {j.drop:+g}, allowed {j.allowed_drop:g})")
        out.append("")
    if report.spend_bands:
        out.append("What the build cost, per row (a rise past the allowance is a DRIFT):")
        for s in report.spend_bands:
            tag = "ok" if s.within else "DRIFT"
            out.append(f"  [{tag}] {s.metric}: {s.baseline:.4g} -> {s.candidate:.4g} "
                       f"({s.rise_pct:+.0%}, allowed +{s.allowed_pct:.0%})")
        out.append("")
    out.append("Hard gates (relative to baseline):")
    for g in report.gates:
        out.append(f"  [{'PASS' if g.passed else 'FAIL'}] {g.name}: {g.detail}")
    # The E-comparison leads the count signals: both maps against the same code-derived anchor.
    if report.granularity is not None:
        gr = report.granularity
        tag = "ok" if gr.within else "DRIFT"
        out.append("\nGranularity (components vs the code-derived expectation E — the leaf anchor):")
        out.append(f"  [{tag}] candidate: {gr.candidate_components} vs E {gr.expected} "
                   f"({gr.candidate_delta_pct:+.0%}, allowed ±{gr.allowed_pct:.0%})")
        out.append(f"  [info] baseline : {gr.baseline_components} vs E {gr.expected} "
                   f"({gr.baseline_delta_pct:+.0%} — informational, only the candidate gates)")
    if report.bands:
        out.append("\nBands (drift vs baseline):")
        for b in report.bands:
            tag = "ok" if b.within else "DRIFT"
            allowed = f"-{b.allowed_pct:.0%} shrink" if b.shrink_only else f"±{b.allowed_pct:.0%}"
            out.append(f"  [{tag}] {b.metric}: {b.baseline:g} -> {b.candidate:g} "
                       f"({b.delta_pct:+.0%}, allowed {allowed})")
    if report.notes:
        out.append("\nNotes:")
        for n in report.notes:
            out.append(f"  - {n}")
    if report.unbanded:
        out.append("")
        out.append(_unbanded_line(report.unbanded))   # BOTTOM COPY — see the top one
    return "\n".join(out)


def load_thresholds(path: Path, project: str | None = None) -> Thresholds:
    return Thresholds.from_config(json.loads(path.read_text(encoding="utf-8")), project)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        print("usage: coyomap-eval compare <baseline.json> <candidate.json> "
              "[--thresholds <file>] [--project <name>]\n"
              "       [--baseline-judge <file>] [--candidate-judge <file>] [--json]\n\n"
              "Compare two MapProfile JSON files and apply the relative regression gates. Pass BOTH\n"
              "judge reports to also apply the drop-only judge bands.\n"
              "Exit: 0 PASS · 2 DRIFT (band breach) · 1 REGRESSED (hard gate).")
        return 0
    project: str | None = None
    thresholds_path: Path | None = None
    base_judge_path: Path | None = None
    cand_judge_path: Path | None = None
    positional: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--project":
            i += 1
            if i >= len(argv):
                print("ERROR: --project needs a name", file=sys.stderr)
                return 2
            project = argv[i]
        elif a == "--thresholds":
            i += 1
            if i >= len(argv):
                print("ERROR: --thresholds needs a path", file=sys.stderr)
                return 2
            thresholds_path = Path(argv[i])
        elif a in ("--baseline-judge", "--candidate-judge"):
            i += 1
            if i >= len(argv):
                print(f"ERROR: {a} needs a path", file=sys.stderr)
                return 2
            if a == "--baseline-judge":
                base_judge_path = Path(argv[i])
            else:
                cand_judge_path = Path(argv[i])
        elif a == "--json":
            pass
        elif a.startswith("-"):
            print(f"ERROR: unknown option '{a}'", file=sys.stderr)
            return 2
        else:
            positional.append(a)
        i += 1
    if len(positional) != 2:
        print("ERROR: need exactly <baseline.json> <candidate.json>", file=sys.stderr)
        return 2
    base_path, cand_path = Path(positional[0]), Path(positional[1])
    for p in (base_path, cand_path):
        if not p.exists():
            print(f"ERROR: {p} not found", file=sys.stderr)
            return 1
    for p in (thresholds_path, base_judge_path, cand_judge_path):
        if p is not None and not p.exists():
            print(f"ERROR: {p} not found", file=sys.stderr)
            return 1
    baseline = _load_profile(base_path.read_text(encoding="utf-8"))
    candidate = _load_profile(cand_path.read_text(encoding="utf-8"))
    thresholds = load_thresholds(thresholds_path, project) if thresholds_path else Thresholds()
    base_judge = JudgeReport.from_json(base_judge_path.read_text(encoding="utf-8")) if base_judge_path else None
    cand_judge = JudgeReport.from_json(cand_judge_path.read_text(encoding="utf-8")) if cand_judge_path else None
    report = compare(baseline, candidate, thresholds, base_judge, cand_judge)
    print(report.to_json() if "--json" in argv else format_report(report))
    return _EXIT[report.verdict]


if __name__ == "__main__":
    raise SystemExit(main())
