#!/usr/bin/env python3
"""Tests for `coyomap eval compare` — the relative regression gates over two MapProfiles.

Stdlib-only — no pytest required. Run either way (needs an editable install: `make deps`):
    python3 tests/test_compare.py        # built-in runner (prints pass/fail)
    pytest tests/test_compare.py         # if pytest is installed
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from coyomap_eval.compare import (DEFAULT_BANDS, DRIFT, PASS, REGRESSED, Thresholds, compare,
                                  format_report, load_thresholds)
from coyomap_eval import compare as C
from coyomap_eval.judge import DimensionScore, JudgeReport
from coyomap_eval.profile import MapProfile

COMPARE = [sys.executable, "-m", "coyomap_eval.cli", "compare"]


# --- builders -------------------------------------------------------------------
def make_profile(**over: object) -> MapProfile:
    """A representative baseline profile; override any field to build a candidate that drifts."""
    base: dict[str, object] = dict(
        use_cases=10, subsystems=4, subdomains=3, components=20, deps=5, entities=15,
        edges=40, hp_steps=8, flows=10, security_surfaces=5,
        validate_ok=True, validate_problems=2, validate_warnings=1,
        contradictions=0, audit_advisories=1, audit_warnings=0, l2_claims=6,
        coverage_flags=0, edges_per_component=2.0,
        auth_surfaces=["a", "b", "c", "d", "e"], use_case_names=[], entity_names=[],
        auth_sites=["gate.py:1", "gate.py:2", "org.py:9"],
        commit="c0ffee", component_names=[], component_sources=[], test_files=[],
    )
    base.update(over)
    return MapProfile(**base)  # type: ignore[arg-type]


def make_judge(passrate: float = 1.0, overall: float = 3.0,
               dims: list[DimensionScore] | None = None, n_failures: int = 0) -> JudgeReport:
    """A representative JudgeReport; override pass-rate / overall / dimensions / failures to build a
    drifting one. The pass-rate is over the surviving denominator (n_claims - n_failures)."""
    if dims is None:
        dims = [DimensionScore("faithfulness", 3.0, 3), DimensionScore("completeness", 3.0, 3)]
    denom = 10 - n_failures
    return JudgeReport(n_claims=10, n_grounded=int(round(passrate * denom)),
                       grounding_passrate=passrate if denom else None,
                       dimensions=dims, overall=overall, n_worklist=10, n_failures=n_failures)


def _tight() -> Thresholds:
    """All hard gates on, no structural bands — so the tests isolate one axis at a time."""
    return Thresholds(bands={})


# --- identity -------------------------------------------------------------------
def test_identical_profiles_pass() -> None:
    p = make_profile()
    assert compare(p, p, _tight()).verdict == PASS


# --- hard gates (relative) ------------------------------------------------------
def test_new_validate_problem_regresses() -> None:
    r = compare(make_profile(validate_problems=2), make_profile(validate_problems=3), _tight())
    assert r.verdict == REGRESSED, r
    assert any(g.name == "validate-no-regress" and not g.passed for g in r.gates)


def test_fewer_validate_problems_is_fine() -> None:
    """A baseline that carried problems, improved — the RELATIVE gate must not punish getting better."""
    r = compare(make_profile(validate_problems=2), make_profile(validate_problems=0), _tight())
    assert r.verdict == PASS, r


def test_new_contradiction_regresses() -> None:
    r = compare(make_profile(contradictions=0), make_profile(contradictions=1), _tight())
    assert r.verdict == REGRESSED, r
    assert any(g.name == "no-new-contradictions" and not g.passed for g in r.gates)


def test_coverage_flag_increase_regresses() -> None:
    r = compare(make_profile(coverage_flags=0), make_profile(coverage_flags=1), _tight())
    assert r.verdict == REGRESSED, r


def test_coverage_gate_skipped_when_a_side_has_no_repo() -> None:
    r = compare(make_profile(coverage_flags=None), make_profile(coverage_flags=3), _tight())
    assert r.verdict == PASS, r
    assert any("coverage gate skipped" in n for n in r.notes), r.notes
    assert not any(g.name == "coverage-no-regress" for g in r.gates)


def test_auth_surface_count_drop_regresses() -> None:
    r = compare(make_profile(security_surfaces=5), make_profile(security_surfaces=4), _tight())
    assert r.verdict == REGRESSED, r
    assert any(g.name == "auth-surfaces-no-drop" and not g.passed for g in r.gates)


def test_auth_surface_name_drift_is_a_note_not_a_gate() -> None:
    """Same count, different names — the count gate passes; the renamed surface is only a note."""
    base = make_profile(security_surfaces=2, auth_surfaces=["/mcp gateway", "/admin"])
    cand = make_profile(security_surfaces=2, auth_surfaces=["MCP gateway endpoint", "/admin"])
    r = compare(base, cand, _tight())
    assert r.verdict == PASS, r
    assert any("names drift" in n for n in r.notes), r.notes


def test_disabling_a_gate_is_honored() -> None:
    r = compare(make_profile(contradictions=0), make_profile(contradictions=2),
                Thresholds(no_new_contradictions=False, bands={}))
    assert r.verdict == PASS, r


# --- bands (soft drift) ---------------------------------------------------------
def test_entities_within_band_pass() -> None:
    t = Thresholds(bands={"entities_pct": 0.20})
    r = compare(make_profile(entities=15), make_profile(entities=13), t)  # -13%, within 20%
    assert r.verdict == PASS, r


def test_entities_beyond_band_drift() -> None:
    t = Thresholds(bands={"entities_pct": 0.20})
    r = compare(make_profile(entities=15), make_profile(entities=9), t)   # -40%, beyond 20%
    assert r.verdict == DRIFT, r
    assert any(b.metric == "entities" and not b.within for b in r.bands)


def test_hard_fail_dominates_a_band_breach() -> None:
    """A hard gate trip outranks any band breach — verdict is REGRESSED, not DRIFT."""
    t = Thresholds(bands={"entities_pct": 0.20})
    r = compare(make_profile(entities=15, contradictions=0),
                make_profile(entities=9, contradictions=1), t)
    assert r.verdict == REGRESSED, r


def test_nonexistent_band_metric_is_noted_not_crashed() -> None:
    r = compare(make_profile(), make_profile(), Thresholds(bands={"nonsense_pct": 0.1}))
    assert r.verdict == PASS
    assert any("not a numeric profile metric" in n for n in r.notes), r.notes


# --- judge bands (drop-only, soft DRIFT) ----------------------------------------
def test_judge_passrate_drop_beyond_allowance_drifts() -> None:
    r = compare(make_profile(), make_profile(), None, make_judge(passrate=0.9), make_judge(passrate=0.7))
    assert r.verdict == DRIFT, r
    assert any(j.metric == "grounding_passrate" and not j.within for j in r.judge_bands)


def test_judge_passrate_small_drop_is_within() -> None:
    r = compare(make_profile(), make_profile(), None, make_judge(passrate=0.9), make_judge(passrate=0.85))
    assert r.verdict == PASS, r


def test_judge_score_rise_is_never_a_drift() -> None:
    """Judge bands are drop-only — a higher score is good, not drift."""
    r = compare(make_profile(), make_profile(), None, make_judge(overall=3.0), make_judge(overall=3.9))
    assert r.verdict == PASS, r


def test_dimension_score_drop_drifts() -> None:
    base = make_judge(dims=[DimensionScore("faithfulness", 4.0, 3)])
    cand = make_judge(dims=[DimensionScore("faithfulness", 3.0, 3)])
    r = compare(make_profile(), make_profile(), None, base, cand)
    assert r.verdict == DRIFT, r
    assert any(j.metric == "dim:faithfulness" and not j.within for j in r.judge_bands)


def test_missing_candidate_judge_is_a_drift_not_a_skip() -> None:
    """Review-2 Finding 3: a judged baseline vs an UNJUDGED candidate must not PASS — skipping the
    semantic gates is the escape hatch an unjudged (or judge-crashed) run would take."""
    r = compare(make_profile(), make_profile(), None, make_judge(), None)
    assert r.verdict == DRIFT, r
    assert any(j.metric == "judge_report_missing" and not j.within for j in r.judge_bands), r.judge_bands
    assert any("NO judge report" in n for n in r.notes), r.notes


def test_missing_baseline_judge_is_also_a_drift() -> None:
    """The reverse case is NOT harmless, though it was only a note until review-2 finding 3.

    That note encoded an assumption of the old design: the baseline was always the project's
    committed map with cached judge scores, and the candidate was the freshly built one, so
    "candidate unjudged" was the only half that could really happen. The eval now compares an
    ARCHIVED map against the current one, and Step 3 fills a cache dir profile-first, judge-second —
    so an interrupted judging leaves a profile-only BASELINE, and that half became reachable.

    Either way the effect is the same and it is not a skip: with one side unjudged, every semantic
    gate drops out, including `grounding_failure_rate_max`, whose entire job is "broken judging must
    not PASS". Measured on the real map: a candidate reporting 0/40 grounded with 40 judge FAILURES
    compared clean under the old note."""
    r = compare(make_profile(), make_profile(), None, None, make_judge())
    assert r.verdict == DRIFT, r
    assert any(j.metric == "judge_report_missing" and not j.within for j in r.judge_bands), r.judge_bands
    assert any("baseline has NO judge report" in n for n in r.notes), r.notes


def test_two_unjudged_sides_stay_a_clean_deterministic_comparison() -> None:
    """Neither side judged is a legitimate deterministic-only run, not a half-missing one — the
    breach above must not fire and turn every profile-only comparison into a DRIFT."""
    r = compare(make_profile(), make_profile(), None, None, None)
    assert r.verdict == PASS, r
    assert not any(j.metric == "judge_report_missing" for j in r.judge_bands), r.judge_bands


def test_grounding_failure_flood_is_a_drift() -> None:
    """Review-2 Finding 2: a candidate whose grounding mostly FAILED (no usable verdicts) must not
    PASS just because the pass-rate over the surviving denominator looks fine."""
    r = compare(make_profile(), make_profile(), None,
                make_judge(passrate=1.0), make_judge(passrate=1.0, n_failures=5))  # 50% failure rate
    assert r.verdict == DRIFT, r
    assert any(j.metric == "grounding_failure_rate" and not j.within for j in r.judge_bands), r.judge_bands


def test_small_grounding_failure_rate_is_within() -> None:
    r = compare(make_profile(), make_profile(), None,
                make_judge(passrate=1.0), make_judge(passrate=1.0, n_failures=2))  # 20% <= 25% cap
    assert r.verdict == PASS, r


def test_hard_fail_dominates_a_judge_drift() -> None:
    r = compare(make_profile(contradictions=0), make_profile(contradictions=1),
                None, make_judge(passrate=0.9), make_judge(passrate=0.4))
    assert r.verdict == REGRESSED, r


def test_report_leads_with_the_judge_deltas() -> None:
    """P1: the formatted report puts judge/quality deltas first; raw structural bands come last."""
    r = compare(make_profile(), make_profile(entities=9), None, make_judge(), make_judge())
    text = format_report(r)
    assert text.index("Judge bands") < text.index("Hard gates") < text.index("Bands"), text


# --- thresholds loading ---------------------------------------------------------
def test_per_project_overrides_global() -> None:
    cfg = {
        "global": {"hard_gates": {"no_new_contradictions": True}, "bands": {"entities_pct": 0.30}},
        "per_project": {"mcpolis": {"hard_gates": {"no_new_contradictions": False}}},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(json.dumps(cfg))
        path = Path(f.name)
    glob = load_thresholds(path)
    proj = load_thresholds(path, "mcpolis")
    assert glob.no_new_contradictions is True
    assert proj.no_new_contradictions is False
    assert proj.bands["entities_pct"] == 0.30       # global band value carried to the project
    assert "components_shrink_pct" in proj.bands    # a default band NOT dropped by the partial override


def test_partial_bands_override_keeps_defaults() -> None:
    """Review Finding 2: tightening ONE band must not disable the others (bands merge, not replace)."""
    t = Thresholds.from_config({"global": {"bands": {"components_pct": 0.05}}})
    assert t.bands["components_pct"] == 0.05
    assert t.bands["entities_shrink_pct"] == DEFAULT_BANDS["entities_shrink_pct"]  # still at its default
    assert set(t.bands) >= set(DEFAULT_BANDS)


def test_every_structural_count_has_a_band() -> None:
    """Review Finding 3: every count-like metric keeps a (shrink-only, collapse-detector) band, so a
    collapse can't pass silently. `l2_claims` is the deliberate exception (P1): the worklist derives
    from edges + auth rows, so banding it double-jeopardizes movement those signals already catch."""
    for metric in ("use_cases", "subsystems", "subdomains", "components", "deps", "entities",
                   "edges", "hp_steps", "flows"):
        assert f"{metric}_shrink_pct" in DEFAULT_BANDS, metric
    assert "l2_claims_pct" not in DEFAULT_BANDS and "l2_claims_shrink_pct" not in DEFAULT_BANDS
    assert "edges_per_component_pct" in DEFAULT_BANDS


def test_deps_collapse_drifts_under_default_thresholds() -> None:
    """A previously-ungated metric (deps) now drifts when it collapses (review Finding 3)."""
    r = compare(make_profile(deps=10), make_profile(deps=1))  # default Thresholds now band deps
    assert r.verdict == DRIFT, r
    assert any(b.metric == "deps" and not b.within for b in r.bands)


# --- density bands (P1): scale-invariant drift, counts as collapse detectors -----
def test_finer_but_better_map_with_steady_density_passes() -> None:
    """The motivating P1 case: a rebuild that maps FINER (more components, proportionally more edges)
    keeps edges-per-component steady and must NOT trip DRIFT under the default thresholds."""
    base = make_profile(components=20, edges=40, edges_per_component=2.0)
    cand = make_profile(components=28, edges=56, edges_per_component=2.0)
    r = compare(base, cand)
    assert r.verdict == PASS, r


def test_density_collapse_drifts_even_when_raw_counts_hold() -> None:
    """Same component count but a thinner backbone: the edge shrink (-27.5%) stays inside the 30%
    shrink band, and the tight density band is what catches it."""
    base = make_profile(components=20, edges=40, edges_per_component=2.0)
    cand = make_profile(components=20, edges=29, edges_per_component=1.45)  # -27.5% density
    r = compare(base, cand)
    assert r.verdict == DRIFT, r
    assert any(b.metric == "edges_per_component" and not b.within for b in r.bands)
    assert any(b.metric == "edges" and b.within for b in r.bands), r.bands


def test_exactly_halved_map_with_steady_density_drifts() -> None:
    """Review-2 Finding 1: a proportionally HALVED map keeps density steady — the shrink-only count
    bands are what refuse it (a symmetric ±50% band waved exactly this through)."""
    base = make_profile(components=20, edges=40, edges_per_component=2.0)
    cand = make_profile(components=10, edges=20, edges_per_component=2.0)
    r = compare(base, cand)
    assert r.verdict == DRIFT, r
    assert any(b.metric == "components" and not b.within for b in r.bands)


def test_count_growth_never_trips_a_shrink_band() -> None:
    """Counts are shrink-only: tripling the components with steady density is a (much) finer map, and
    whether that fineness is right is the altitude rubric's call — not a count band's."""
    base = make_profile(components=20, edges=40, edges_per_component=2.0)
    cand = make_profile(components=60, edges=120, edges_per_component=2.0)
    assert compare(base, cand).verdict == PASS


def test_baseline_without_the_density_field_is_skipped_not_crashed() -> None:
    """A baseline profile.json written before edges_per_component existed loads as None — the band is
    skipped with a note, never crashed on or treated as 0."""
    r = compare(make_profile(edges_per_component=None), make_profile())
    assert r.verdict == PASS, r
    assert any("edges_per_component" in n and "skipped" in n for n in r.notes), r.notes


# --- granularity (candidate vs the code-derived expectation E — the leaf anchor) --
def test_granularity_candidate_below_band_drifts() -> None:
    """The mcpolis failure mode: an honest rebuild lands far COARSER than the code-derived E."""
    base = make_profile(components=20, granularity_expected=20)
    cand = make_profile(components=10, granularity_expected=20)  # -50% vs E, band is ±40%
    r = compare(base, cand, _tight())
    assert r.verdict == DRIFT, r
    assert r.granularity is not None and not r.granularity.within, r.granularity


def test_granularity_candidate_above_band_drifts() -> None:
    base = make_profile(components=20, granularity_expected=20)
    cand = make_profile(components=30, granularity_expected=20)  # +50% vs E
    r = compare(base, cand, _tight())
    assert r.verdict == DRIFT, r


def test_granularity_within_band_passes() -> None:
    base = make_profile(components=20, granularity_expected=20)
    cand = make_profile(components=25, granularity_expected=20)  # +25%, inside ±40%
    r = compare(base, cand, _tight())
    assert r.verdict == PASS, r
    assert r.granularity is not None and r.granularity.within


def test_granularity_gates_the_candidate_never_the_baseline() -> None:
    """Both maps' distance to the same E is reported, but a baseline whose own zoom is off must not
    trip the verdict — E-relative is fairer than baseline-relative exactly because of this case.
    (Count bands are off here: the point is the E-band's own behavior.)"""
    base = make_profile(components=45, granularity_expected=20)   # baseline way off (+125%)
    cand = make_profile(components=22, granularity_expected=20)   # candidate in band
    r = compare(base, cand, _tight())
    assert r.verdict == PASS, r
    assert r.granularity is not None
    assert r.granularity.baseline_delta_pct > 1.0 and r.granularity.within, r.granularity


def test_granularity_skipped_with_a_note_when_no_profile_carries_e() -> None:
    r = compare(make_profile(), make_profile(), _tight())  # granularity_expected defaults to None
    assert r.verdict == PASS, r
    assert r.granularity is None
    assert any("granularity band skipped" in n for n in r.notes), r.notes


def test_granularity_prefers_the_candidate_e_and_notes_a_mismatch() -> None:
    """Both sides score the same pinned tree, so their E should agree; if they don't (the tree
    changed between scorings), the candidate's fresher E gates and the mismatch is surfaced."""
    base = make_profile(components=20, granularity_expected=15)
    cand = make_profile(components=20, granularity_expected=20)
    r = compare(base, cand, _tight())
    assert r.granularity is not None and r.granularity.expected == 20, r.granularity
    assert any("expectation differs" in n for n in r.notes), r.notes


def test_granularity_band_pct_merges_from_config() -> None:
    cfg = {
        "global": {"granularity_band_pct": 0.10},
        "per_project": {"mcpolis": {"granularity_band_pct": 0.60}},
    }
    glob = Thresholds.from_config(cfg)
    proj = Thresholds.from_config(cfg, "mcpolis")
    assert glob.granularity_band_pct == 0.10
    assert proj.granularity_band_pct == 0.60
    assert Thresholds.from_config({}).granularity_band_pct == 0.40  # the built-in default


def test_report_shows_both_maps_distance_to_e_and_leads_the_counts() -> None:
    """The formatted report carries a Granularity section with BOTH distances, placed before the
    baseline-relative count bands (the E-comparison leads for counts)."""
    base = make_profile(components=45, granularity_expected=20)
    cand = make_profile(components=10, granularity_expected=20)
    text = format_report(compare(base, cand, _tight()))
    assert "Granularity" in text and "candidate: 10 vs E 20" in text \
        and "baseline : 45 vs E 20" in text, text
    r = compare(base, cand)  # default bands on → a Bands section exists to order against
    text = format_report(r)
    assert text.index("Granularity") < text.index("Bands (drift vs baseline)"), text


# --- CLI ------------------------------------------------------------------------
def _write(p: MapProfile) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(p.to_json())
        return f.name


def test_cli_pass_exits_zero() -> None:
    r = subprocess.run([*COMPARE, _write(make_profile()), _write(make_profile())],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_cli_regressed_exits_one() -> None:
    r = subprocess.run([*COMPARE, _write(make_profile(contradictions=0)),
                        _write(make_profile(contradictions=1))], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REGRESSED" in r.stdout


def test_cli_drift_exits_two() -> None:
    # entities -67%: past even the wide collapse-detector band (±50%)
    r = subprocess.run([*COMPARE, _write(make_profile(entities=15)),
                        _write(make_profile(entities=5))], capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "DRIFT" in r.stdout


def _write_judge(j: JudgeReport) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(j.to_json())
        return f.name


def test_cli_applies_judge_reports() -> None:
    r = subprocess.run([*COMPARE, _write(make_profile()), _write(make_profile()),
                        "--baseline-judge", _write_judge(make_judge(passrate=0.9)),
                        "--candidate-judge", _write_judge(make_judge(passrate=0.5))],
                       capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Judge bands" in r.stdout and "DRIFT" in r.stdout


# --- built-in runner ------------------------------------------------------------
def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())


# ── deployment linkage: units nothing runs in ────────────────────────────────────────────────────

def test_a_deployment_unit_losing_its_last_component_is_a_hard_gate():
    """A live rebuild kept all eight units, dropped the two components that owned the nginx and
    vector files, and filled `runs_in` by contiguous component-id range — a formula that can only
    produce contiguous buckets, so six of eight boxes ended up empty. Nothing watched it.

    The two boxes that EMPTIED are the finding, and they held first-party code, so they are orphans
    (a unit matching an infra dep is expected to be empty and is not counted)."""
    base = make_profile(deployment_units=8, deployment_units_linked=4, deployment_orphan_units=0)
    cand = make_profile(deployment_units=8, deployment_units_linked=2, deployment_orphan_units=2)
    report = compare(base, cand, Thresholds())
    gate = next(g for g in report.gates if g.name == "deployment-linkage-no-drop")
    assert not gate.passed, gate.detail
    assert "0 -> 2" in gate.detail
    assert "4/8 -> 2/8" in gate.detail
    assert report.verdict == "REGRESSED"


def test_runs_in_coverage_rising_does_not_hide_lost_linkage():
    """The trap this gate exists for: the number that WAS being watched moved the right way. Across
    the same rebuild `runs_in` coverage went 93/96 to 66/66 — a perfect score, produced by dumping
    every component into two units."""
    base = make_profile(components=96, deployment_units=8, deployment_units_linked=4,
                        deployment_orphan_units=0)
    cand = make_profile(components=66, deployment_units=8, deployment_units_linked=2,
                        deployment_orphan_units=2)
    report = compare(base, cand, Thresholds())
    assert not next(g for g in report.gates if g.name == "deployment-linkage-no-drop").passed


def test_holding_deployment_linkage_passes_the_gate():
    base = make_profile(deployment_units=8, deployment_units_linked=4, deployment_orphan_units=1)
    cand = make_profile(deployment_units=8, deployment_units_linked=5, deployment_orphan_units=0)
    assert next(g for g in compare(base, cand, Thresholds()).gates
                if g.name == "deployment-linkage-no-drop").passed


def test_enriching_the_deployment_section_with_infra_is_not_a_linkage_drop():
    """The gate used to punish a map for getting BETTER.

    One rebuild named 4 units, all first-party runtimes, all linked. Its successor named 11 — the
    same 3 runtimes plus the proxy, two datastores, the log forwarder, two test instances and two
    test doubles — and correctly folded a unit that was really a mount inside the backend process
    into that process. Linked went 4/4 -> 3/11 and the gate FAILED, on a section that had gained
    seven honest boxes and lost nothing. An infra unit can never be "linked", so every one added
    drove the watched number down."""
    base = make_profile(deployment_units=4, deployment_units_linked=4, deployment_orphan_units=0)
    cand = make_profile(deployment_units=11, deployment_units_linked=3, deployment_orphan_units=0)
    gate = next(g for g in compare(base, cand, Thresholds()).gates
                if g.name == "deployment-linkage-no-drop")
    assert gate.passed, gate.detail


def test_a_recorded_exception_does_not_waive_the_gate():
    """The first cut honoured the map's recorded `runs-in/quality` literal, and an adversarial review
    demonstrated the hole end to end: the literal covers five unrelated sub-checks, `validate`
    actively suggests recording it for reasons that have nothing to do with placement, and nothing
    requires the justification to mention the orphaned units. One TRUE sentence about the infra units
    turned a REGRESSED verdict into a full green run on a map with two empty boxes.

    `compare` is the method developer's regression check between two builds and a build never runs
    it, so the "agree with validate" argument that motivated the waiver had no audience. An advisory
    may be waivable by its subject; a hard gate may not."""
    base = make_profile(deployment_units=4, deployment_units_linked=4, deployment_orphan_units=0)
    cand = make_profile(deployment_units=11, deployment_units_linked=3, deployment_orphan_units=3)
    report = compare(base, cand, Thresholds())
    gate = next(g for g in report.gates if g.name == "deployment-linkage-no-drop")
    assert not gate.passed, gate.detail
    assert "0 -> 3" in gate.detail


def test_a_pre_field_baseline_skips_the_gate_with_a_note():
    """0 is the STRICTEST value here, so defaulting a pre-field profile to it made the gate fail a
    map against ITSELF — the bug class the gate was rewritten to fix, reintroduced for every
    existing baseline. Both sibling deployment gates skip-with-a-note instead."""
    base = make_profile(deployment_units=8, deployment_units_linked=4)   # field absent -> None
    cand = make_profile(deployment_units=8, deployment_units_linked=4, deployment_orphan_units=2)
    report = compare(base, cand, Thresholds())
    assert not [g for g in report.gates if g.name == "deployment-linkage-no-drop"]
    assert any("predates the `deployment_orphan_units`" in n for n in report.notes), report.notes


def test_a_map_with_no_deployment_section_is_not_gated():
    """Most maps declare no units at all; the gate must not fire on an absent section."""
    base = make_profile(deployment_units=0, deployment_units_linked=0)
    cand = make_profile(deployment_units=0, deployment_units_linked=0)
    assert not [g for g in compare(base, cand, Thresholds()).gates
                if g.name == "deployment-linkage-no-drop"]


def test_adding_a_deployment_shape_of_the_same_process_does_not_buy_linkage():
    """Linkage counts UNITS, and a unit is cheap to add. A live rebuild scored 2/8 -> 3/10 and the
    gate passed — but the three linked units (`backend`, `standalone`, `e2e backend shard`) hosted
    the IDENTICAL 50 components, one placement decision replicated across three deployment shapes,
    while the other 30 (the whole frontend) sat in no unit at all. Counting DISTINCT hosted sets
    cannot be moved by naming another shape of the same process."""
    base = make_profile(deployment_units=8, deployment_units_linked=2, deployment_orphan_units=0,
                        deployment_distinct_hosted_sets=2)
    cand = make_profile(deployment_units=10, deployment_units_linked=3, deployment_orphan_units=0,
                        deployment_distinct_hosted_sets=1)
    report = compare(base, cand)
    assert next(g for g in report.gates if g.name == "deployment-linkage-no-drop").passed
    assert not next(g for g in report.gates
                    if g.name == "deployment-distinct-hosts-no-drop").passed
    assert any("deployment SHAPES of the same process" in n for n in report.notes), report.notes


def test_distinct_hosts_gate_is_vacuous_on_a_baseline_that_predates_the_field():
    """A profile blessed before the field carries 0, so the comparison is trivially satisfied rather
    than falsely failing — the direction the `deployment_units` skip already chose."""
    base = make_profile(deployment_units=8, deployment_units_linked=2)
    cand = make_profile(deployment_units=8, deployment_units_linked=2,
                        deployment_distinct_hosted_sets=1)
    assert next(g for g in compare(base, cand).gates
                if g.name == "deployment-distinct-hosts-no-drop").passed


def test_a_stale_baseline_says_the_distinct_hosts_gate_is_off():
    """A baseline blessed before the field carries 0, `cand >= 0` is always true, and a HARD gate is
    off with nothing saying so — the identical hazard the `deployment_units` skip prints a note for
    fifteen lines above."""
    base = make_profile(deployment_units=8, deployment_units_linked=2)
    cand = make_profile(deployment_units=8, deployment_units_linked=2,
                        deployment_distinct_hosted_sets=1)
    report = compare(base, cand)
    assert any("deployment-distinct-hosts gate is vacuous" in n for n in report.notes), report.notes


def test_a_candidate_that_places_nothing_cannot_pass_by_having_no_orphans():
    """Orphans are 0 by construction on a map that sets `runs_in` nowhere, so stripping every
    placement made the EMPTIEST possible Deployment view score better than a partly-filled one:
    16 declared units, none linked, `0 -> 0`, gate green. `validate` fires an unlinked canary there
    and nothing in the comparison read it."""
    base = make_profile(deployment_units=8, deployment_units_linked=4, deployment_orphan_units=0,
                        deployment_runs_in_adopted=True)
    cand = make_profile(deployment_units=16, deployment_units_linked=0, deployment_orphan_units=0,
                        deployment_runs_in_adopted=False)
    report = compare(base, cand, Thresholds())
    gate = next(g for g in report.gates if g.name == "deployment-linkage-no-drop")
    assert not gate.passed, gate.detail
    assert "NOWHERE" in gate.detail


def test_a_baseline_that_never_placed_anything_does_not_trip_the_new_check():
    """Only the LOSS of placement is the finding. A project that has not adopted `runs_in` on either
    side is measured by the orphan count as before."""
    base = make_profile(deployment_units=8, deployment_units_linked=0, deployment_orphan_units=0,
                        deployment_runs_in_adopted=False)
    cand = make_profile(deployment_units=8, deployment_units_linked=0, deployment_orphan_units=0,
                        deployment_runs_in_adopted=False)
    gate = next(g for g in compare(base, cand, Thresholds()).gates
                if g.name == "deployment-linkage-no-drop")
    assert gate.passed, gate.detail


def test_auth_site_churn_is_reported_when_the_statement_count_holds() -> None:
    """The gap this closes. The count gate sees nothing — five surfaces before, five after — while
    every enforcement line moved. Measured on two mcpolis builds of one commit: 50 -> 44 statements
    (caught) against 57 of 163 shared anchors (invisible)."""
    base = make_profile(auth_sites=["a.py:1", "a.py:2", "b.py:3"])
    cand = make_profile(auth_sites=["c.py:7", "c.py:8", "d.py:9"])
    rep = compare(base, cand)
    assert any("auth-surfaces-no-drop" in g.name and g.passed for g in rep.gates)
    assert any("ENFORCEMENT LINES: 3 -> 3, 0 in both" in n for n in rep.notes)


def test_a_file_that_lost_all_its_access_coverage_is_named() -> None:
    """The wording-independent half. Two builds may describe one decision differently, but a file
    that no access rule names any more is a fact about coverage, not about prose."""
    base = make_profile(auth_sites=["kept.py:1", "gone.py:4", "gone.py:9"])
    cand = make_profile(auth_sites=["kept.py:1"])
    notes = " ".join(compare(base, cand).notes)
    assert "1 file(s) held access enforcement in the baseline" in notes
    assert "gone.py" in notes and "kept.py" not in notes.split("read first:")[-1]


def test_a_file_only_the_candidate_covers_says_neither_map_is_complete() -> None:
    """Churn runs both ways, and that is the point: on the real pair each build found ~16 files of
    access enforcement the other missed, so the union is larger than either map claims."""
    base = make_profile(auth_sites=["kept.py:1"])
    cand = make_profile(auth_sites=["kept.py:1", "found.py:2"])
    notes = " ".join(compare(base, cand).notes)
    assert "1 file(s) carry access enforcement only in the candidate" in notes
    assert "neither map's surface is complete" in notes


def test_auth_site_churn_never_gates() -> None:
    """Two independent LLM builds legitimately differ, so gating on churn would fail every rebuild.
    A total change of anchors, with the statement count held, must still PASS."""
    base = make_profile(auth_sites=["a.py:1"])
    cand = make_profile(auth_sites=["z.py:99"])
    assert compare(base, cand).verdict == "PASS"


def test_a_baseline_predating_auth_sites_says_so_rather_than_going_quiet() -> None:
    """Silence is indistinguishable from agreement. The deployment-linkage gate learned this the
    same way: a baseline blessed before the field carried 0 and turned its gate off invisibly."""
    base = make_profile(auth_sites=None)
    cand = make_profile(auth_sites=["a.py:1"])
    assert any("auth-site comparison skipped" in n for n in compare(base, cand).notes)


def test_two_maps_with_no_access_surface_at_all_say_nothing() -> None:
    """A project with no auth surface should not produce a note about one."""
    rep = compare(make_profile(auth_sites=[], security_surfaces=0, auth_surfaces=[]),
                  make_profile(auth_sites=[], security_surfaces=0, auth_surfaces=[]))
    assert not any("ENFORCEMENT LINES" in n for n in rep.notes)


def test_the_dropped_by_name_note_is_truncated() -> None:
    """A rule statement is a paragraph, and a real pair produced FIFTY of them in one note —
    hundreds of words that pushed the readable notes off the screen. The count leads, three
    statements give a taste, and the rest stay in the JSON report."""
    base = make_profile(auth_surfaces=[f"statement number {i} " + "x" * 200 for i in range(50)],
                        security_surfaces=50)
    cand = make_profile(auth_surfaces=[], security_surfaces=50)
    note = next(n for n in compare(base, cand).notes if "not (by name) in candidate" in n)
    assert note.startswith("50 auth surface(s)")
    assert "+47 more" in note
    assert len(note) < 600


def test_a_short_dropped_list_is_not_truncated() -> None:
    """Three or fewer need no "+N more" — the note should read as the whole list."""
    base = make_profile(auth_surfaces=["a", "b", "c"], security_surfaces=3)
    cand = make_profile(auth_surfaces=["a"], security_surfaces=3)
    note = next(n for n in compare(base, cand).notes if "not (by name) in candidate" in n)
    assert "more" not in note and "b" in note and "c" in note


# --- the variants fold reads as a regression --------------------------------------
# `method.md` models one process across environments as ONE unit with a variant each. The
# alternative — a unit per environment — inflates `deployment_distinct_hosted_sets`, so a map that
# adopts the prescribed form FAILS `deployment-distinct-hosts-no-drop`. The gate must not move (a
# test below pins that another shape of the same process cannot buy linkage), so the drop is
# explained instead. On the pair this came from, units with 2+ variants went 1 of 6 to 2 of 5 while
# the gate failed 3 -> 2, and the whole comparison was stamped REGRESSED.

def test_a_distinct_hosts_drop_from_folding_units_into_variants_is_explained():
    from coyomap_eval.compare import compare as compare_profiles
    base = make_profile(deployment_units=6, deployment_units_linked=3,
                        deployment_distinct_hosted_sets=3, deployment_units_multi_variant=1)
    cand = make_profile(deployment_units=5, deployment_units_linked=2,
                        deployment_distinct_hosted_sets=2, deployment_units_multi_variant=2)
    report = compare_profiles(base, cand)
    gate = next(g for g in report.gates if g.name == "deployment-distinct-hosts-no-drop")
    assert not gate.passed, "the gate itself must still fail — a shape is not a placement"
    assert any("FOLDED units into variants" in n for n in report.notes), report.notes


def test_a_distinct_hosts_drop_with_no_variant_fold_gets_no_excuse():
    """The note must not fire on a genuine loss of modelling, which is what the gate is for."""
    from coyomap_eval.compare import compare as compare_profiles
    base = make_profile(deployment_units=6, deployment_units_linked=3,
                        deployment_distinct_hosted_sets=3, deployment_units_multi_variant=1)
    cand = make_profile(deployment_units=6, deployment_units_linked=2,
                        deployment_distinct_hosted_sets=2, deployment_units_multi_variant=1)
    report = compare_profiles(base, cand)
    assert not any("FOLDED units into variants" in n for n in report.notes), report.notes


def test_a_baseline_blessed_before_the_variant_field_gets_no_excuse_either():
    from coyomap_eval.compare import compare as compare_profiles
    base = make_profile(deployment_units=6, deployment_units_linked=3,
                        deployment_distinct_hosted_sets=3, deployment_units_multi_variant=None)
    cand = make_profile(deployment_units=5, deployment_units_linked=2,
                        deployment_distinct_hosted_sets=2, deployment_units_multi_variant=2)
    report = compare_profiles(base, cand)
    assert not any("FOLDED units into variants" in n for n in report.notes), report.notes


# --- rebuild agreement: how much of the baseline survives a rebuild ---------------
def test_rebuild_agreement_reports_how_much_of_the_baseline_survives() -> None:
    """The failure every COUNT gate walks through. Two mcpolis builds of commit `5dccb1c`, 21 hours
    apart with no product file changed, passed every count band that gates while 61 of the
    baseline's 70 component names did not appear in the rebuild at all."""
    base = make_profile(commit="5dccb1c", component_names=["Alpha", "Beta", "Gamma", "Delta"])
    cand = make_profile(commit="5dccb1c", component_names=["Alpha", "Epsilon"])
    rep = compare(base, cand)
    assert any("REBUILD AGREEMENT" in n and "5dccb1c" in n for n in rep.notes)
    assert any("component names: 4 -> 2, 1 of 4 survive (25 %)" in n for n in rep.notes)


def test_the_denominator_is_the_baseline_so_a_SPLIT_is_not_read_as_a_RENAME() -> None:
    """Union punishes a candidate for splitting. A rebuild that keeps every one of the baseline's
    names and adds more has renamed NOTHING, and scored 59 % of union on the real pair — which is
    why the survival figure leads and the union figure rides in parentheses."""
    base = make_profile(commit="x", component_names=["A", "B"])
    cand = make_profile(commit="x", component_names=["A", "B", "C", "D", "E", "F"])
    rep = compare(base, cand)
    assert any("2 of 2 survive (100 %)" in n for n in rep.notes)
    assert any("33 % of the union" in n for n in rep.notes)


def test_a_dirty_pin_still_counts_as_the_same_commit_and_says_so() -> None:
    """`5dccb1c` and `5dccb1c-dirty` are the same commit; comparing the raw strings went silent
    between two builds of one tree. `impact_git` already strips the suffix for this reason. The
    dirtiness is still WORTH SAYING — uncommitted code can differ between the two builds."""
    base = make_profile(commit="5dccb1c-dirty", component_names=["A"])
    cand = make_profile(commit="5dccb1c", component_names=["A"])
    rep = compare(base, cand)
    head = next(n for n in rep.notes if "REBUILD AGREEMENT" in n)
    assert "both maps pin commit" in head and "-dirty" in head


def test_two_pins_of_different_LENGTH_are_the_same_commit() -> None:
    """`git rev-parse --short` lengthens as a repo grows, and different repos stamp different widths
    — mcpolis stamps 7 characters, coworker stamps 9. Requiring equal length disabled the measure on
    a pair that shared a commit."""
    rep = compare(make_profile(commit="5dccb1c9a2", component_names=["A"]),
                  make_profile(commit="5dccb1c", component_names=["A"]))
    assert any("both maps pin commit" in n for n in rep.notes)


def test_two_commits_are_labelled_not_silenced() -> None:
    """An earlier draft suppressed the numbers across two commits, on a theory the data refutes:
    over 48 same-commit and 10 different-commit pairs the medians are indistinguishable (component
    names 2 % vs 1 %, sources 39 % vs 40 %). The commit is a LABEL on the reading, not a filter."""
    base = make_profile(commit="aaaaaaa", component_names=["Alpha"])
    cand = make_profile(commit="bbbbbbb", component_names=["Beta"])
    rep = compare(base, cand)
    assert any("different commits" in n and "the CODE moving" in n for n in rep.notes)
    assert any("component names: 1 -> 1, 0 of 1 survive" in n for n in rep.notes)


def test_an_empty_commit_string_is_not_read_as_a_matching_pin() -> None:
    """`""` on both sides is two maps with NO pin, not two maps of one commit. Reading it as a match
    printed `both maps pin commit ` and the whole table over two unrelated maps."""
    rep = compare(make_profile(commit="", component_names=["A"]),
                  make_profile(commit="", component_names=["B"]))
    assert any("carries no `commit` pin" in n for n in rep.notes)
    assert not any("both maps pin commit" in n for n in rep.notes)


def test_a_kind_missing_from_one_profile_is_named_not_read_as_zero_overlap() -> None:
    """`None` is "this profile never carried the field"; `[]` is "the map has none". Reading the
    first as the second reports 0 % agreement for a field nobody measured."""
    base = make_profile(commit="x", component_names=None, test_files=["t/a.py"])
    cand = make_profile(commit="x", component_names=["Alpha"], test_files=["t/a.py"])
    rep = compare(base, cand)
    assert not any("component names:" in n for n in rep.notes)
    assert any("kind(s) skipped" in n and "component names" in n for n in rep.notes)
    assert any("test FILES cited: 1 -> 1, 1 of 1 survive" in n for n in rep.notes)


def test_profiles_that_predate_EVERY_name_field_still_say_so() -> None:
    """An early return on an empty row list printed NOTHING for a pair of old profiles — silence,
    which every escape family in this file has had to stop doing in its own turn."""
    old = make_profile(commit="x", component_names=None, component_sources=None,
                       use_case_names=[], entity_names=[], test_files=None)
    rep = compare(old, old)
    assert any("nothing could be compared" in n for n in rep.notes)
    assert any("kind(s) skipped" in n for n in rep.notes)


def test_rebuild_agreement_never_gates() -> None:
    """Two independent LLM builds legitimately differ and no threshold has been defended across
    enough pairs. A total disagreement must leave the verdict alone."""
    base = make_profile(commit="x", component_names=["a", "b", "c"])
    cand = make_profile(commit="x", component_names=["d", "e", "f"])
    rep = compare(base, cand)
    assert any("0 of 3 survive" in n for n in rep.notes)
    assert rep.verdict == compare(make_profile(commit="x"), make_profile(commit="x")).verdict


def test_overlap_of_two_empty_sets_does_not_divide_by_zero() -> None:
    """The guard both callers of `_overlap` need, in one place instead of two."""
    assert C._overlap(set(), set()) == (0, 1)
    assert C._overlap({"a"}, {"a", "b"}) == (1, 2)


def test_a_source_root_the_candidate_cites_nowhere_is_noted() -> None:
    """`internal/` left one map whole, 27 mentions to 0, with every gate green: the walker calls it
    non-product, so no check was meant to look. Right or wrong, the move gets one line."""
    old = make_profile(component_sources=["internal/a.py", "backend/x.py"], auth_sites=["backend/y.py:3"])
    new = make_profile(component_sources=["backend/x.py"], auth_sites=["backend/y.py:3"])
    r = compare(old, new)
    assert any("1 source root(s)" in n and "internal/" in n for n in r.notes), r.notes
    assert not any("source root(s)" in n for n in compare(old, old).notes)
    older = make_profile(component_sources=["backend/x.py"], test_files=None, auth_sites=None)
    assert not any("source root(s)" in n for n in compare(old, older).notes), "a missing field is not a lost root"


def test_a_rules_shrink_beyond_the_band_is_drift() -> None:
    """Rules went 102 -> 79 -> 95 -> 88 across four mcpolis builds with no band on them, while
    every block came back on the contract's ceiling; the decisions and their enforcing sites are
    counts like the others, shrink-only."""
    import json as _json
    shipped = _json.loads((Path(__file__).resolve().parents[1] / "thresholds.json").read_text(encoding="utf-8"))
    bands = next(v["bands"] for v in shipped.values() if isinstance(v, dict) and "bands" in v)
    assert bands["rules_shrink_pct"] == 0.3 and bands["rule_sites_shrink_pct"] == 0.3
    assert "rules_shrink_pct" not in DEFAULT_BANDS, "the rules layer is optional: no default band"
    t = Thresholds(bands={"rules_shrink_pct": 0.3, "rule_sites_shrink_pct": 0.3})
    r = compare(make_profile(rules=100, rule_sites=250), make_profile(rules=60, rule_sites=250), t)
    assert r.verdict == DRIFT, r
    assert any(b.metric == "rules" and not b.within for b in r.bands)
    grown = compare(make_profile(rules=60), make_profile(rules=100), t)
    assert not any(b.metric == "rules" and not b.within for b in grown.bands), "growth never breaches"


def test_a_metric_no_band_in_force_watches_is_named_at_BOTH_ends_of_the_report() -> None:
    """`rules` and `rule_sites` are banded in `eval/thresholds.json` and deliberately not in the code
    defaults, and the skip was SILENT. `eval/retro/method.md` ran `compare` with no `--thresholds`,
    so no retrospective's band table could ever have carried either row — the whole point of banding
    them. The line prints at the top AND the bottom: a reader who `head`s the output and one who
    `tail`s it must each be told the table is short."""
    old, new = make_profile(rules=84, rule_sites=227), make_profile(rules=84, rule_sites=227)
    r = compare(old, new)
    assert r.unbanded == ["rules", "rule_sites"], r.unbanded
    assert not any(b.metric in ("rules", "rule_sites") for b in r.bands)
    lines = format_report(r).splitlines()
    assert any("NOT BANDED" in ln for ln in lines[:5]), "a reader who `head`s the report must see it"
    assert any("NOT BANDED" in ln for ln in lines[-3:]), "and so must one who `tail`s it"
    assert all("rules, rule_sites" in ln for ln in lines if "NOT BANDED" in ln), "one writer"


def test_a_map_with_no_rules_layer_is_told_nothing_about_rules() -> None:
    """The reason these were kept out of `DEFAULT_BANDS` in the first place: a map that never
    adopted the layer must not collect a line about it on every comparison."""
    r = compare(make_profile(), make_profile())
    assert r.unbanded == []
    assert "NOT BANDED" not in format_report(r)


def test_the_shipped_thresholds_replace_the_warning_with_the_rows() -> None:
    """The fix the line asks for has to actually work: with the shipped file the metrics are banded,
    so the warning goes and the two rows appear."""
    shipped = load_thresholds(Path(__file__).resolve().parents[1] / "thresholds.json")
    r = compare(make_profile(rules=84, rule_sites=227),
                make_profile(rules=84, rule_sites=227), shipped)
    assert r.unbanded == []
    assert {"rules", "rule_sites"} <= {b.metric for b in r.bands}
    assert "NOT BANDED" not in format_report(r)


def test_a_band_spelled_the_other_way_still_counts_as_watching_the_metric() -> None:
    """`rules_pct` and `rules_shrink_pct` resolve to the same profile field, so a thresholds file
    that bands either one IS watching `rules`. Testing the band KEY instead printed the row and the
    warning in the same report: `[ok] rules: 88 -> 88` above `no band in force watches it`."""
    t = Thresholds(bands={"rules_pct": 0.30, "rule_sites_shrink_pct": 0.30})
    r = compare(make_profile(rules=88, rule_sites=227), make_profile(rules=88, rule_sites=227), t)
    assert r.unbanded == [], r.unbanded
    assert {"rules", "rule_sites"} <= {b.metric for b in r.bands}
    assert "NOT BANDED" not in format_report(r)


def test_the_warning_is_silent_when_its_own_remedy_would_not_produce_the_row() -> None:
    """The line PRESCRIBES `--thresholds`. With a count on one side only, the band that flag turns
    on is demoted to a note ("not numeric on both sides"), so the advice cannot deliver the row it
    promises — and the line must not be given."""
    r = compare(make_profile(rules=None), make_profile(rules=88, rule_sites=227))
    assert "rules" not in r.unbanded, r.unbanded
    banded = compare(make_profile(rules=None), make_profile(rules=88),
                     Thresholds(bands={"rules_shrink_pct": 0.30}))
    assert not any(b.metric == "rules" for b in banded.bands), "the promised row does not appear"


def test_a_vanished_layer_is_named_as_one_rather_than_as_a_generic_skip() -> None:
    """`rules` is written `len(...) or None`, so a section that disappears reads None, the band is
    demoted to a note, and the verdict is PASS. A shrink band catches 88 -> 20 and cannot catch
    88 -> gone, which is the worse failure. The note at least says which way it went."""
    r = compare(make_profile(rules=88), make_profile(rules=None),
                Thresholds(bands={"rules_shrink_pct": 0.30}))
    assert r.verdict == PASS, "unchanged: naming it does not gate it"
    gone = [n for n in r.notes if "band 'rules_shrink_pct' skipped" in n]
    assert gone and "BASELINE carried 88 and the candidate carries nothing" in gone[0], r.notes
    other_way = compare(make_profile(rules=None), make_profile(rules=88),
                        Thresholds(bands={"rules_shrink_pct": 0.30}))
    assert not any("BASELINE carried" in n for n in other_way.notes), "a new layer is not a loss"


def test_every_band_only_the_shipped_file_carries_is_declared_optional() -> None:
    """The silence must not come back for the NEXT metric. A key added to `eval/thresholds.json` and
    not to `DEFAULT_BANDS` disappears from any run that passes no `--thresholds`, exactly as `rules`
    did; listing it in `OPTIONAL_BANDS` is what makes the skip say so.

    `per_project` counts too, and it is not a lesser case: `Thresholds.from_config` merges a project
    block over the global one, so a band that lives only under a project name is just as absent from
    a default run and just as silent about it."""
    shipped = json.loads(
        (Path(__file__).resolve().parents[1] / "thresholds.json").read_text(encoding="utf-8"))
    keys = set(shipped["global"]["bands"])
    for block in shipped.get("per_project", {}).values():
        keys |= set(block.get("bands", {}))
    assert keys - set(DEFAULT_BANDS) == set(C.OPTIONAL_BANDS), sorted(keys - set(DEFAULT_BANDS))


def test_the_retro_method_passes_the_thresholds_file_to_compare() -> None:
    """Half the fix is the command the retrospective runs. A `compare` line with no `--thresholds`
    silently falls back to the code defaults, and that is how the rows went missing."""
    text = (Path(__file__).resolve().parents[1] / "retro" / "method.md").read_text(encoding="utf-8")
    runs = [ln for ln in text.splitlines() if ln.strip().startswith("coyomap-eval compare")]
    assert runs, "the retro method must still run compare"
    assert all("--thresholds" in ln for ln in runs), runs


def test_enforcement_functions_are_compared_beside_the_lines() -> None:
    """Two builds pick the same functions and different lines in them; the line number mixes that
    jitter with real losses. The function number cannot."""
    old = make_profile(auth_sites=["a.py:10", "b.py:5"], auth_functions=["a.py::guard", "b.py::check"])
    new = make_profile(auth_sites=["a.py:14", "c.py:9"], auth_functions=["a.py::guard", "c.py::other"])
    r = compare(old, new)
    fn = [n for n in r.notes if "ENFORCEMENT FUNCTIONS" in n]
    assert fn and "2 -> 2, 1 in both (33 % of the union)" in fn[0], r.notes
    assert not any("ENFORCEMENT FUNCTIONS" in n
                   for n in compare(make_profile(auth_sites=["a.py:1"]), new).notes), "None on one side: silent"


def test_an_interface_kind_that_goes_to_zero_is_noted() -> None:
    """`handoff` went 1 -> 0 on a rebuild with its `mailto:` still in the code and no count moved."""
    old = make_profile(interface_kinds={"screen": 4, "handoff": 1})
    new = make_profile(interface_kinds={"screen": 5})
    r = compare(old, new)
    assert any("handoff (1 -> 0)" in n for n in r.notes), r.notes
    assert not any("interface kind(s)" in n for n in compare(old, old).notes)


# --- what the build cost, per row ------------------------------------------------------------------

def make_spend(cost: float | None = 0.10, seconds: float | None = 3.0, rows: int = 1000):
    from coyomap_eval.compare import Spend
    return Spend(rows, cost, seconds)


def test_a_build_that_costs_more_per_row_than_allowed_drifts():
    from coyomap_eval.compare import compare
    p = make_profile()
    report = compare(p, p, baseline_spend=make_spend(0.10), candidate_spend=make_spend(0.20))
    assert report.verdict == "DRIFT"
    breached = [s.metric for s in report.spend_bands if not s.within]
    assert breached == ["cost_per_row"]


def test_a_cheaper_build_is_never_a_drift():
    from coyomap_eval.compare import compare
    p = make_profile()
    report = compare(p, p, baseline_spend=make_spend(0.20, 6.0), candidate_spend=make_spend(0.05, 1.0))
    assert report.verdict == "PASS" and all(s.within for s in report.spend_bands)


def test_spend_measured_on_one_side_only_is_a_note_not_a_drift():
    from coyomap_eval.compare import compare
    p = make_profile()
    report = compare(p, p, candidate_spend=make_spend())
    assert report.verdict == "PASS" and not report.spend_bands
    assert any("one side only" in n for n in report.notes)


def test_a_missing_cost_leaves_only_the_time_band():
    from coyomap_eval.compare import compare
    p = make_profile()
    report = compare(p, p, baseline_spend=make_spend(None, 3.0), candidate_spend=make_spend(None, 3.3))
    assert [s.metric for s in report.spend_bands] == ["seconds_per_row"]
