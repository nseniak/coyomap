#!/usr/bin/env python3
"""End-to-end regression over a COMMITTED fragment corpus — `eval/fixtures/trapdoor/fragments/`.

Every other test in this suite hand-rolls its input: `test_assemble.py` alone builds fragments
inline in 31 temporary directories. That is right for unit tests — each one isolates a rule — and it
leaves a gap nothing covered: **no test ever assembled a realistic, many-fragment build the way a
real one arrives**, so the commands only ever saw inputs shaped by the test that was checking them.

The gap had a cost. A smoke test over one real project's saved fragments looked like it exercised
the pipeline and did not: it loaded 22 of 36 modules, and missed `lint_fragment`, `finalize`, `fix`,
`reconcile_build`, `scope`, `dump` and `preindex` entirely — which is where an adversarial review
had just found five real bugs. Passing a pre-built reconcile file also meant the half of `reconcile`
that BUILDS one never ran, so the coverage looked broader than it was.

The corpus is the trapdoor golden map split along the seams a real build cuts (header, behavioral,
structure, domain, deps/ops, edges, extras), anchored at the trapdoor synthetic repo so
`--check-sources` resolves. `rules.json` drives the reconcile builder.

Pinned against `expected/project-map.json`, not against `golden/project-map.json`: assembly
normalises entry-point order, so the golden file's authored order is not what a canonical assembly
produces. Pinning our own expected output keeps this test independent of the eval's baseline — and
`golden/` must stay whatever the eval says it is.

Regenerate after an INTENTIONAL output change:

    cd eval/fixtures/trapdoor
    coyomap reconcile --rules rules.json --fragments fragments --out reconcile.json
    coyomap assemble fragments/*.json --out /tmp/exp --reconcile reconcile.json
    python -c "import json,pathlib;m=json.load(open('/tmp/exp/project-map.json'));\
[m.pop(k,None) for k in ('tool_commit','tool_committed','built')];\
pathlib.Path('expected/project-map.json').write_text(json.dumps(m,indent=2,ensure_ascii=False)+'\\n')"
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "eval" / "fixtures" / "trapdoor"
FRAGMENTS = sorted((FIXTURE / "fragments").glob("*.json"))
#: Environment, not output — stripped before every comparison.
_ENV_KEYS = ("tool_commit", "tool_committed", "built")


def _cli(*args: str, cwd: Path = FIXTURE) -> subprocess.CompletedProcess:
    """Drive the real CLI in a subprocess. In-process calls would miss argument parsing, exit
    codes and stream handling — three of the bugs this file exists to guard were in exactly those."""
    return subprocess.run([sys.executable, "-c",
                           "import sys;from coyomap.cli import main;sys.exit(main(sys.argv[1:]))",
                           *args],
                          capture_output=True, text=True, cwd=cwd, stdin=subprocess.DEVNULL)


def _assemble(out: Path, reconcile: Path | None = None) -> dict:
    args = ["assemble", *[str(p) for p in FRAGMENTS], "--out", str(out)]
    if reconcile:
        args += ["--reconcile", str(reconcile)]
    r = _cli(*args)
    assert r.returncode == 0, f"assemble failed:\n{r.stdout}\n{r.stderr}"
    m = json.loads((out / "project-map.json").read_text())
    for k in _ENV_KEYS:
        m.pop(k, None)
    return m


def test_the_corpus_exists_and_covers_the_whole_model():
    """A fragment set that quietly loses an array would make every assertion below vacuous."""
    assert FRAGMENTS, "no committed fragments — the fixture is the point of this file"
    keys: set[str] = set()
    for p in FRAGMENTS:
        keys |= set(json.loads(p.read_text()))
    expected = json.loads((FIXTURE / "expected" / "project-map.json").read_text())
    missing = [k for k, v in expected.items()
               if isinstance(v, list) and v and k not in keys]
    assert not missing, f"expected output holds arrays no fragment authors: {missing}"


def test_assembly_is_byte_stable_against_the_pinned_output(tmp_path):
    """The regression itself: these fragments assemble to exactly this map."""
    got = _assemble(tmp_path / "out", FIXTURE / "reconcile.json")
    want = json.loads((FIXTURE / "expected" / "project-map.json").read_text())
    assert got == want, (
        "assembly output moved. If that was intentional, regenerate the pinned file — the "
        "regeneration command is in this module's docstring.")


def test_assembly_is_deterministic_across_processes(tmp_path):
    """Two runs, two processes, one answer. `balance` shipped a report that gave three different
    answers to five identical runs — equal-weight rows fell back to set iteration order, which
    Python randomises per process. Assembly walks far more collections than `balance` does."""
    import os
    outs = []
    for seed in ("0", "1"):
        d = tmp_path / f"run{seed}"
        r = subprocess.run([sys.executable, "-c",
                            "import sys;from coyomap.cli import main;sys.exit(main(sys.argv[1:]))",
                            "assemble", *[str(p) for p in FRAGMENTS], "--out", str(d),
                            "--reconcile", str(FIXTURE / "reconcile.json")],
                           capture_output=True, text=True, cwd=FIXTURE,
                           stdin=subprocess.DEVNULL,
                           env={**os.environ, "PYTHONHASHSEED": seed})
        assert r.returncode == 0, r.stderr
        m = json.loads((d / "project-map.json").read_text())
        for k in _ENV_KEYS:
            m.pop(k, None)
        outs.append(json.dumps(m, sort_keys=True))
    assert outs[0] == outs[1], "assembly is not reproducible across hash seeds"


def test_the_reconcile_builder_runs_and_its_output_is_applied(tmp_path):
    """The half of `reconcile` that BUILDS a file from rules. A smoke test that passes a pre-built
    reconcile file exercises only the half that applies one, and reports coverage it does not have."""
    rec = tmp_path / "rec.json"
    r = _cli("reconcile", "--rules", str(FIXTURE / "rules.json"),
             "--fragments", str(FIXTURE / "fragments"), "--out", str(rec))
    assert r.returncode == 0, r.stderr
    assert "SUMMARY:" in r.stderr, "the summary is what makes one run answer 'which rules matched'"
    assert "matched nothing" in r.stderr
    directives = json.loads(rec.read_text())
    assert directives["set"], "the rules assign nothing — the fixture stopped testing anything"
    placed = _assemble(tmp_path / "out", rec)
    assert [c for c in placed["components"] if c.get("subsystem") in ("S2", "S3")], \
        "reconcile directives did not reach the assembled map"


@pytest.mark.parametrize("gate", ["validate", "audit", "balance"])
def test_the_gates_read_the_assembled_map_without_crashing(tmp_path, gate):
    """Not a quality assertion — a crash guard. These run on every build, and a traceback here is
    the difference between an advisory and a lost build."""
    out = tmp_path / "out"
    _assemble(out, FIXTURE / "reconcile.json")
    r = _cli(gate, str(out / "project-map.json"), cwd=REPO)
    assert r.returncode in (0, 1), f"{gate} crashed (exit {r.returncode}):\n{r.stderr[-2000:]}"
    assert "Traceback" not in r.stderr, r.stderr[-2000:]


def test_every_committed_fragment_passes_its_own_self_check():
    """`lint-fragment` is what an agent runs before returning a fragment, and nothing in the suite
    ever ran it over a realistic one. It also guards the corpus: a fragment edited into an invalid
    shape would otherwise fail later, inside assembly, with a worse message."""
    for p in FRAGMENTS:
        r = _cli("lint-fragment", "--repo", str(FIXTURE), str(p))
        assert r.returncode == 0, f"{p.name} fails its own lint:\n{r.stdout}\n{r.stderr}"
        # The verdict leads STDERR, both ways. It used to go to stdout on a pass, which collided
        # with the per-fragment `name: OK` rows that live there — `| head -1 | grep OK` matched on
        # failure too. Stderr is the diagnostic stream; the OK rows stay on stdout for parsers.
        first = r.stderr.splitlines()[0] if r.stderr else ""
        assert first.startswith("LINT OK"), (
            f"{p.name}: the verdict must be the FIRST line of stderr — a truncating pipe hid a "
            f"pass twice on a live build, and the agent kept working on a finished fragment. "
            f"Got: {first!r}")
