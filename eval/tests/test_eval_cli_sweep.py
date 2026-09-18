#!/usr/bin/env python3
"""Every `coyomap-eval` subcommand, through the real CLI, against committed fixtures — with a
completeness gate so a new command cannot ship without joining the sweep.

The sibling of `tests/test_cli_sweep.py`, for the eval half of the toolchain, and it exists for the
same reason: the per-command tests here build their own minimal inputs, so nothing ever ran these
commands over a realistic map and a realistic transcript. The first sweep on the `coyomap` side
found a live crash on its first run — `grounding report` on the bare-list worklist that
`audit --json | jq .worklist` produces — which every unit test had missed because none of them fed
it that shape.

Two committed fixtures make it possible, and both were missing:

* `eval/fixtures/trapdoor/` — the map corpus (added with the assembly sweep).
* `eval/fixtures/transcript/build.jsonl` — a small transcript shaped like a real build: a fan-out
  emitted as ONE message (the rule the scorecard measures), a command chained behind `&&` (invisible
  to the one-line index, visible to `--commands`), tool results, and token usage so `cost` has
  something to divide. Every transcript test until now wrote its own into a temp directory.

Assertions are deliberately weak — runs, no traceback, documented exit code, fixtures unmodified.
Semantics live in the per-command tests; duplicating them here would give one rule two homes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
FIXTURE = REPO / "eval" / "fixtures" / "trapdoor"
MAP = FIXTURE / "expected" / "project-map.json"
TRANSCRIPT = REPO / "eval" / "fixtures" / "transcript" / "build.jsonl"
OK = (0, 1)

#: Taken at import, before any recipe runs — a per-test snapshot cannot see damage an earlier test
#: already did, which is exactly how a recipe on the other sweep rewrote committed data unnoticed.
_FIXTURE_DIRS = (FIXTURE, TRANSCRIPT.parent)


def _fixture_state() -> dict[Path, bytes]:
    """Contents AND membership. The first version listed a fixed set of files, so it could see a
    file change but not a file APPEAR — and `process` writes `<transcript>.l3-scorecard.json`
    beside its input by default. That artifact reached a commit before this caught it."""
    return {p: p.read_bytes()
            for d in _FIXTURE_DIRS for p in sorted(d.rglob("*")) if p.is_file()}


_FIXTURES_AT_START = _fixture_state()


def cli(*args: str, cwd: Path = REPO, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c",
         "import sys;from coyomap_eval.cli import main;sys.exit(main(sys.argv[1:]))", *args],
        capture_output=True, text=True, cwd=cwd, stdin=subprocess.DEVNULL, timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def _advertised() -> set[str]:
    """The dispatch table, read from the source — never a second hand-kept list.

    A hand-maintained copy is how a completeness gate quietly stops being complete: it passes while
    the tool grows past it."""
    src = (REPO / "eval" / "tools" / "coyomap_eval" / "cli.py").read_text(encoding="utf-8")
    import re
    return set(re.findall(r'cmd == "([a-z-]+)"', src))


def _profile(tmp: Path, name: str, map_path: Path) -> Path:
    r = cli("score", str(map_path), "--repo", str(FIXTURE), "--json")
    assert r.returncode in OK, r.stderr
    p = tmp / f"{name}.json"
    p.write_text(r.stdout)
    return p


def _verdicts(tmp: Path) -> Path:
    """A verdict file in the shape a skeptic returns — `grounded` a JSON boolean, never `"true"`."""
    r = cli("claims", str(MAP), "--json")
    claims = json.loads(r.stdout) if r.returncode in OK and r.stdout.strip() else []
    if isinstance(claims, dict):
        claims = claims.get("claims") or claims.get("worklist") or []
    rows = [{"claim": (c.get("claim") if isinstance(c, dict) else str(c)), "grounded": True,
             "evidence": "src/x.py:1", "skeptic": "sweep", "note": "fixture"} for c in claims[:5]]
    p = tmp / "verdicts.json"
    p.write_text(json.dumps({"grounding": rows}))
    return p


def _ledger_file(t) -> "Path":
    """A minimal retro ledger. One row, no `landed_in`, so the sweep exercises the command without
    depending on any sha existing in this clone."""
    p = t / "findings.json"
    p.write_text(json.dumps({"schema": "coyomap-retro-ledger/v1",
                             "findings": [{"id": "x-1", "title": "t", "landed": False}]}),
                 encoding="utf-8")
    return p


def _gold_file(tmp: Path) -> Path:
    """An empty gold: nothing to compare, so a map against itself exits 0."""
    p = tmp / "gold.json"
    p.write_text("{}", encoding="utf-8")
    return p


def _run_dir(tmp: Path, name: str) -> Path:
    """`bless` promotes a run directory to a baseline; both must exist and hold a profile."""
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    r = cli("score", str(MAP), "--repo", str(FIXTURE), "--json")
    (d / "profile.json").write_text(r.stdout)
    return d


RECIPES: dict[str, tuple] = {
    "score":          (lambda t: ["score", str(MAP), "--repo", str(FIXTURE), "--json"], OK),
    "claims":         (lambda t: ["claims", str(MAP), "--json"], OK),
    "hash":           (lambda t: ["hash", str(MAP)], OK),
    "transcript":     (lambda t: ["transcript", str(TRANSCRIPT), "--stats"], OK),
    "cost":           (lambda t: ["cost", str(TRANSCRIPT), "--map", str(MAP)], OK),
    "process":        (lambda t: ["process", str(TRANSCRIPT), "--map", str(MAP),
                                  "--out", str(t / "scorecard.json")], OK),
    "compare":        (lambda t: ["compare", str(_profile(t, "base", MAP)),
                                  str(_profile(t, "cand", MAP))], OK),
    "judge":          (lambda t: ["judge", "--map", str(MAP), "--verdicts", str(_verdicts(t)),
                                  "--out", str(t / "judge.json")], OK),
    "protocol":       (lambda t: ["protocol", "--thresholds", str(REPO / "eval" / "thresholds.json"),
                                  "--rubric", str(REPO / "eval" / "rubric.md")], OK),
    "bless":          (lambda t: ["bless", str(_run_dir(t, "run")), str(_run_dir(t, "baseline"))], OK),
    "archive":        (lambda t: ["archive", str(t / "empty"), "--list"], (0, 1, 2)),
    "retro-precheck": (lambda t: ["retro-precheck", "--repo", str(t / "empty"), "--json"], (0, 1)),
    # a ledger of one row that names no commit: nothing to check, so nothing to be wrong about
    "ledger":         (lambda t: ["ledger", str(_ledger_file(t)), "--repo", str(REPO), "--json"], OK),
    "mutate":         (lambda t: ["mutate", "plant", str(FIXTURE / "claims-sample.json"),
                                  "--n", "2", "--repo", str(FIXTURE),
                                  "--out", str(t / "m.json"), "--key", str(t / "k.json")], OK),
    "run":            (lambda t: ["run", "--project", "trapdoor", "--map", str(MAP),
                                  "--repo", str(FIXTURE)], OK),
    # A map against ITSELF: nothing can be lost, so the sweep exercises the whole path (load,
    # source check, match, report) on a pair that is guaranteed to exit 0.
    "arrows":         (lambda t: ["arrows", str(MAP), str(MAP), "--repo", str(FIXTURE)], OK),
    # THIS repo, so the ledger's own sentences are found and the coyomap map is the one in-tree.
    # argus and mcpolis live outside the checkout, so their rows skip. Exit 1 whenever a row is
    # stale — the normal state between a rebuild and the rewrite that follows it. NOT 2, which is
    # the ledger itself being broken; accepting that here would let a run where every row crashed
    # pass this sweep.
    "live-numbers":   (lambda t: ["live-numbers", "--repo", str(REPO)], (0, 1)),
    # A map against ITSELF with an empty gold: every path runs, nothing can be wrong.
    "walk-score":     (lambda t: ["walk-score", str(MAP), str(MAP), "--gold", str(_gold_file(t))], OK),
    # THE FIXTURE MAP'S OWN use cases, fed back as a run: every one states both halves, so the whole
    # path runs (load, per-field rules, the pair as one box, the validator's advisory) and exits 0.
    "field-score":    (lambda t: ["field-score", str(_rows_file(t))], OK),
}


def _rows_file(t: Path) -> Path:
    """The fixture map's use cases, in the shape a partial run returns them."""
    rows = json.loads(MAP.read_text(encoding="utf-8"))["use_cases"]
    f = t / "rows.json"
    f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return f


def test_every_advertised_eval_command_has_a_sweep_recipe():
    """THE COMPLETENESS GATE, read from the dispatch itself. Without it the sweep keeps passing
    while covering a smaller share of the tool every release."""
    advertised = _advertised()
    assert advertised, "could not read the dispatch table — the gate would pass vacuously"
    missing = sorted(advertised - set(RECIPES))
    stale = sorted(set(RECIPES) - advertised)
    assert not missing, f"{missing} advertised by coyomap-eval with no sweep recipe"
    assert not stale, f"{stale} in RECIPES but no longer advertised — delete the recipe"


@pytest.mark.parametrize("command", sorted(RECIPES))
def test_the_eval_command_survives_real_fixtures(command, tmp_path):
    (tmp_path / "empty").mkdir(exist_ok=True)
    build, allowed = RECIPES[command]
    r = cli(*build(tmp_path))
    assert "Traceback" not in r.stderr, f"{command} crashed:\n{r.stderr[-3000:]}"
    assert r.returncode in allowed, (
        f"{command} exited {r.returncode}, expected one of {allowed}\n"
        f"stdout:{r.stdout[-1200:]}\nstderr:{r.stderr[-1200:]}")


def test_the_sweep_left_the_committed_fixtures_untouched():
    now = _fixture_state()
    changed = sorted(str(p) for p in set(now) | set(_FIXTURES_AT_START)
                     if now.get(p) != _FIXTURES_AT_START.get(p))
    assert not changed, (
        f"the sweep changed the fixture tree: {changed}. A recipe that writes must be given an "
        f"--out under tmp_path — several commands default to writing beside their input.")


def test_the_transcript_fixture_still_exercises_what_it_was_built_for():
    """The fixture is only worth committing while it still provokes the shapes it was made for. If
    an edit flattens the fan-out into three turns, or unchains the `&&`, the scorecard and the
    command index silently stop being tested on their hardest inputs."""
    r = cli("transcript", str(TRANSCRIPT), "--stats")
    # The AGENT COUNT, not the turn count. Asserting "1 turn(s) launching agents" was vacuous:
    # it stays true when the fan-out is flattened to a single agent, which is precisely the shape
    # the fixture exists to rule out. Verified by flattening it — the first version stayed green.
    import re
    sizes = [int(n) for n in re.findall(r"turn\s+\d+:\s+(\d+) agent\(s\)", r.stdout)]
    assert sizes and max(sizes) >= 2, (
        f"the fixture must keep a MULTI-agent fan-out in one message — that is the rule the "
        f"scorecard measures, and it cannot be tested by a single-agent turn. Got {sizes}")
    r = cli("transcript", str(TRANSCRIPT), "--commands")
    for sub in ("assemble", "validate", "audit", "preindex"):
        assert sub in r.stdout, f"`{sub}` vanished from the fixture's command index"
    assert "validate" in r.stdout, (
        "the chained `&& coyomap validate` must stay visible to --commands — a retrospective once "
        "published that a command 'never ran' from the one-line index, which truncates at 100 chars")
