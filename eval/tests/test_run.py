#!/usr/bin/env python3
"""Tests for the run orchestrator (deterministic half) — run_eval + archive + bless.

No live LLM: the judge is the injected `ScriptedJudge` from test_judge. Stdlib-only.
    python3 tests/test_run.py        # built-in runner
    pytest tests/test_run.py         # if pytest is installed
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from coyomap_eval.judge import JudgeReport
from coyomap_eval.profile import MapProfile, build_profile
from coyomap_eval.run import BASELINE, bless, delta_md, load_baseline, map_sha256, run_eval, write_run
from test_judge import ScriptedJudge

RUN = [sys.executable, "-m", "coyomap_eval.cli", "run"]
BLESS = [sys.executable, "-m", "coyomap_eval.cli", "bless"]
HASH = [sys.executable, "-m", "coyomap_eval.cli", "hash"]
CLAIMS = [sys.executable, "-m", "coyomap_eval.cli", "claims"]
JUDGE = [sys.executable, "-m", "coyomap_eval.cli", "judge"]


def make_map() -> str:
    """A small well-formed-enough map (a JSON model document) with the two L2 sources
    (a Security & auth row + an `enforces` edge), so profile + judge both have content."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "Admin action",
      "actors": [],
      "trigger": "a", "outcome": "b"
    }
  ],
  "happy_path": [],
  "subsystems": [],
  "components": [
    {
      "id": "C1",
      "name": "Gate",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "C2",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "Policy",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "",
      "source": null,
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [],
  "non_entity_types": [],
  "flows": [],
  "edges": [
    {
      "src": "C1",
      "verb": "enforces",
      "dst": "C2",
      "why": "policy",
      "where": "gate.py#L5"
    }
  ],
  "deployment": [],
  "observability": [],
  "security": [
    {
      "surface": "/admin",
      "who": "admins",
      "source": "[require_admin](auth.py#L10)",
      "risk": "escalation"
    }
  ],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


# --- run_eval -------------------------------------------------------------------
def test_first_run_has_no_baseline_verdict() -> None:
    r = run_eval("p", make_map(), None)
    assert r.verdict == BASELINE and r.delta is None, r


def test_run_against_equal_baseline_passes() -> None:
    base = build_profile(make_map())
    r = run_eval("p", make_map(), None, baseline_profile=base)
    assert r.verdict == "PASS", r


def test_run_builds_judge_report_from_injected_judge() -> None:
    r = run_eval("p", make_map(), Path("."), judge=ScriptedJudge(), rubric="R", n_judges=1)
    assert r.judge is not None and r.judge.n_claims >= 1, r


def test_delta_md_leads_with_the_judge_section() -> None:
    """P1: the run report leads with the judge (semantic quality); raw structural counts follow."""
    r = run_eval("p", make_map(), Path("."), judge=ScriptedJudge(), rubric="R", n_judges=1)
    md = delta_md(r)
    assert md.index("## Judge") < md.index("## Profile"), md
    assert "risk-ranked" in md and "judge failure(s) excluded" in md, md


def test_run_flags_a_judge_drop_as_drift() -> None:
    base_profile = build_profile(make_map())
    base_judge = run_eval("p", make_map(), Path("."), judge=ScriptedJudge(), rubric="R", n_judges=1).judge
    # candidate grounds fewer claims (refute the enforces edge) -> pass-rate drops
    r = run_eval("p", make_map(), Path("."), baseline_profile=base_profile, baseline_judge=base_judge,
                 judge=ScriptedJudge(refute_marker="enforces"), rubric="R", n_judges=1)
    assert r.verdict == "DRIFT", r


# --- persistence + bless --------------------------------------------------------
def test_write_run_then_load_and_bless_round_trip() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        run_dir, baseline_dir = root / "runs" / "p" / "ts", root / "baseline" / "p"
        r = run_eval("p", make_map(), Path("."), judge=ScriptedJudge(), rubric="R", n_judges=1)
        write_run(run_dir, r, make_map())
        assert (run_dir / "project-map.md").exists()
        assert (run_dir / "project-map.view.json").exists()   # the viewer's data snapshot is archived
        assert (run_dir / "profile.json").exists()
        assert (run_dir / "judge.json").exists()
        assert (run_dir / "delta.md").exists()
        bless(run_dir, baseline_dir)
        assert (baseline_dir / "project-map.view.json").exists()  # bless copies the snapshot too
        bp, bj = load_baseline(baseline_dir)
        assert isinstance(bp, MapProfile) and isinstance(bj, JudgeReport)
        # the blessed baseline is what a next run compares against -> equal map -> PASS
        r2 = run_eval("p", make_map(), None, baseline_profile=bp)
        assert r2.verdict == "PASS", r2


def test_load_baseline_missing_is_none() -> None:
    with tempfile.TemporaryDirectory() as d:
        bp, bj = load_baseline(Path(d))
        assert bp is None and bj is None


# --- CLI ------------------------------------------------------------------------
def test_cli_run_first_then_bless_then_run_again() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        mp = root / "map.json"
        mp.write_text(make_map(), encoding="utf-8")
        run_dir, baseline_dir = root / "run1", root / "baseline"
        # first run: no baseline -> BASELINE, exit 0
        r1 = subprocess.run([*RUN, "--project", "p", "--map", str(mp), "--out", str(run_dir)],
                           capture_output=True, text=True)
        assert r1.returncode == 0 and "BASELINE" in r1.stdout, r1.stdout + r1.stderr
        assert (run_dir / "project-map.view.json").exists(), "run should archive the viewer's data snapshot"
        # bless it
        rb = subprocess.run([*BLESS, str(run_dir), str(baseline_dir)], capture_output=True, text=True)
        assert rb.returncode == 0, rb.stdout + rb.stderr
        # second run vs the baseline (same map) -> PASS, exit 0
        r2 = subprocess.run([*RUN, "--project", "p", "--map", str(mp), "--baseline-dir", str(baseline_dir)],
                           capture_output=True, text=True)
        assert r2.returncode == 0 and "PASS" in r2.stdout, r2.stdout + r2.stderr


def test_cli_run_requires_project_and_map() -> None:
    r = subprocess.run([*RUN, "--project", "p"], capture_output=True, text=True)
    assert r.returncode == 2 and "required" in (r.stdout + r.stderr)


def test_cli_judge_refuses_a_rubric_that_is_not_there() -> None:
    """Same bug class as the --baseline-dir one: a flag given, its target missing, the guard skipped.

    The rubric's sha is part of the judge-protocol fingerprint. Falling back to "" stamped the report
    `rubric_sha: ""` — a fingerprint claiming the scores came from a rubric that was never read.
    `coyomap-eval protocol` refuses the same missing path, so the two disagreed and an expensive
    skeptic fan-out got silently discarded as a protocol mismatch."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        mp, vp = root / "map.json", root / "raw.json"
        mp.write_text(make_map(), encoding="utf-8")
        vp.write_text('{"grounding": [], "judges": []}', encoding="utf-8")
        r = subprocess.run([*JUDGE, "--map", str(mp), "--verdicts", str(vp),
                            "--rubric", str(root / "nosuch.md"), "--out", str(root / "j.json")],
                           capture_output=True, text=True)
        assert r.returncode == 1, r.stdout + r.stderr
        assert not (root / "j.json").exists()


def test_cli_run_refuses_a_baseline_dir_that_is_not_there() -> None:
    """A mistyped --baseline-dir must not silently become "no comparison at all".

    It used to: a missing dir was skipped, the verdict fell back to BASELINE, and the exit code was
    0 — indistinguishable from "nothing got worse". The eval names its cache dirs by a 12-character
    map hash, so the mistype is one transposed character away, and the caller asked for a comparison
    in the very same command. Fail closed instead."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        mp = root / "map.json"
        mp.write_text(make_map(), encoding="utf-8")
        r = subprocess.run([*RUN, "--project", "p", "--map", str(mp),
                            "--baseline-dir", str(root / "nosuch")], capture_output=True, text=True)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "BASELINE" not in r.stdout


def test_cli_run_refuses_a_baseline_dir_with_no_profile() -> None:
    """Same failure by another route: the directory exists but holds nothing to compare against."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        mp = root / "map.json"
        mp.write_text(make_map(), encoding="utf-8")
        (empty := root / "empty").mkdir()
        r = subprocess.run([*RUN, "--project", "p", "--map", str(mp),
                            "--baseline-dir", str(empty)], capture_output=True, text=True)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "BASELINE" not in r.stdout


# --- freeze / hash (I2) ---------------------------------------------------------
def test_cli_hash_prints_the_sha256_of_the_file() -> None:
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "map.json"
        mp.write_text(make_map(), encoding="utf-8")
        r = subprocess.run([*HASH, str(mp)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.strip() == map_sha256(mp), r.stdout


def test_cli_run_matching_map_hash_proceeds() -> None:
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "map.json"
        mp.write_text(make_map(), encoding="utf-8")
        r = subprocess.run([*RUN, "--project", "p", "--map", str(mp),
                            "--expect-map-hash", map_sha256(mp)], capture_output=True, text=True)
        assert r.returncode == 0 and "BASELINE" in r.stdout, r.stdout + r.stderr


def test_cli_run_refuses_a_map_edited_after_freeze() -> None:
    """The freeze guard: any post-build edit to the map invalidates the run — hard non-zero refusal,
    no profile, no comparison."""
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "map.json"
        mp.write_text(make_map(), encoding="utf-8")
        frozen = map_sha256(mp)
        mp.write_text(make_map() + "\n<!-- silently fixed after freeze -->\n", encoding="utf-8")
        out_dir = Path(d) / "run"
        r = subprocess.run([*RUN, "--project", "p", "--map", str(mp),
                            "--expect-map-hash", frozen, "--out", str(out_dir)],
                           capture_output=True, text=True)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "hash mismatch" in r.stderr, r.stderr
        assert not out_dir.exists(), "a refused run must not archive anything"


def test_cli_run_expect_map_hash_without_a_value_is_a_usage_error() -> None:
    """Review-2 Finding 5: a --expect-map-hash whose value got lost (bad quoting, empty map-hash file)
    must fail CLOSED, never silently skip the freeze guard."""
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "map.json"
        mp.write_text(make_map(), encoding="utf-8")
        r = subprocess.run([*RUN, "--project", "p", "--map", str(mp), "--expect-map-hash"],
                           capture_output=True, text=True)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "needs a value" in r.stderr, r.stderr


def test_cli_claims_top_caps_the_sample() -> None:
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "map.json"
        mp.write_text(make_map(), encoding="utf-8")
        r = subprocess.run([*CLAIMS, str(mp), "--top", "1", "--json"], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        claims = json.loads(r.stdout)
        assert len(claims) == 1, claims
        assert "Auth surface" in claims[0]["claim"], claims  # the top of the risk ranking


def test_cli_claims_map_path_may_equal_the_top_value() -> None:
    """Review-2 Finding 6: a map file literally named `1` must not be swallowed as --top's value —
    the flag's value is consumed by index, not by string equality."""
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "1"
        mp.write_text(make_map(), encoding="utf-8")
        r = subprocess.run([*CLAIMS, "1", "--top", "1", "--json"], capture_output=True, text=True,
                           cwd=d)
        assert r.returncode == 0, r.stdout + r.stderr
        assert len(json.loads(r.stdout)) == 1, r.stdout


def test_cli_claims_rejects_a_negative_top() -> None:
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "map.json"
        mp.write_text(make_map(), encoding="utf-8")
        r = subprocess.run([*CLAIMS, str(mp), "--top", "-5"], capture_output=True, text=True)
        assert r.returncode == 2, r.stdout + r.stderr
        assert "non-negative" in r.stderr, r.stderr


def test_cli_claims_lists_the_l2_worklist_as_json() -> None:
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "map.json"
        mp.write_text(make_map(), encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "coyomap_eval.cli", "claims", str(mp), "--json"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        claims = json.loads(r.stdout)
        assert len(claims) >= 2 and all("claim" in c and "anchor" in c for c in claims), claims


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
