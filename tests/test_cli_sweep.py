#!/usr/bin/env python3
"""Every subcommand and every `fix` verb, driven through the real CLI against the committed
fragment corpus — and a completeness gate so a new command cannot ship without joining the sweep.

Why this is separate from `test_cli_contract.py`: that file probes commands for *contract*
properties (an unknown option is refused, machine-readable output is only JSON, an error is never
followed by a success claim) using minimal or empty inputs. It answers "does the command behave".
This one answers a different question — **"does the command survive a realistic map"** — and the
two failed apart in practice: an adversarial pass found five real bugs in `fix`, `finalize`,
`reconcile` and `lint-fragment` while every contract test passed, because none of those bugs
reproduced on a toy input.

The completeness gate is the point of the file. `RECIPES` must name every command
`test_cli_contract.COMMAND_MODULE` advertises, and `FIX_RECIPES` every verb in `fix._VERBS` — both
of which are themselves kept honest against the CLI's own dispatch. Adding a command without a
recipe fails the suite, which is the only way "comprehensive" survives contact with a growing tool.

What a recipe asserts, deliberately weakly: the command RUNS on a real map — no traceback, and an
exit code in its documented set. Semantics belong in the per-command unit tests; duplicating them
here would create two places to update and one of them would rot. What only this file can catch is
the crash, the hang, and the wrong-shaped output that a toy fixture never provokes.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_cli_contract import COMMAND_MODULE, UNPROBEABLE

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "eval" / "fixtures" / "trapdoor"
FRAGMENTS = sorted((FIXTURE / "fragments").glob("*.json"))
MAP = FIXTURE / "expected" / "project-map.json"

#: Exit codes that are a RESULT, not a failure. Gates return 1 for "findings", 2 for "bad usage" —
#: and 2 from a sweep recipe means the recipe is wrong, so it is never in a default allow-set.
OK = (0, 1)


def cli(*args: str, cwd: Path = FIXTURE, timeout: int = 120) -> subprocess.CompletedProcess:
    """The real binary in a real subprocess. In-process `main()` calls skip argument parsing, exit
    codes and stream buffering — where three of today's bugs actually lived."""
    return subprocess.run(
        [sys.executable, "-c",
         "import sys;from coyomap.cli import main;sys.exit(main(sys.argv[1:]))", *args],
        capture_output=True, text=True, cwd=cwd, stdin=subprocess.DEVNULL, timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def _assembled(tmp: Path) -> Path:
    r = cli("assemble", *[str(p) for p in FRAGMENTS], "--out", str(tmp),
            "--reconcile", str(FIXTURE / "reconcile.json"))
    assert r.returncode == 0, r.stderr
    return tmp / "project-map.json"


def _worklist(tmp: Path, map_path: Path) -> Path:
    """An audit worklist, which the grounding verbs need as input."""
    r = cli("audit", str(map_path), "--json")
    assert r.returncode in OK, r.stderr
    wl = tmp / "worklist.json"
    wl.write_text(json.dumps(json.loads(r.stdout).get("worklist", [])))
    return wl


def _verdicts(tmp: Path, map_path: Path) -> Path:
    """A verdict file shaped exactly as a skeptic returns one — confirming the first few claims.

    Built from the worklist rather than hand-written, so it cannot drift from the shape the tool
    actually pairs on: `claim` must match character for character, and `grounded` is a JSON boolean
    (a skeptic once shipped 40 quoted `"true"` strings and the record refused, 100 turns later)."""
    wl = json.loads(_worklist(tmp, map_path).read_text())
    rows = [{"claim": w["claim"], "grounded": True, "evidence": w.get("anchor") or "src/x.py:1",
             "skeptic": "sweep", "note": "fixture verdict"} for w in wl[:5]]
    out = tmp / "verdicts-sweep.json"
    out.write_text(json.dumps({"grounding": rows}))
    return out


def _extras_copy(tmp: Path) -> Path:
    """`record` WRITES. Pointed at the committed fragment it rewrote it — reformatted and reordered
    — and the damage reached a commit before the untouched-check caught it, because that check
    snapshots the fixture inside its own test and cannot see what a sibling test already did."""
    import shutil
    dst = tmp / "extras.json"
    shutil.copy(FIXTURE / "fragments" / "extras.json", dst)
    return dst


def _with_coyomap_dir(tmp: Path) -> Path:
    """`provenance stamp` writes into an existing `.coyomap/`; it refuses to invent one."""
    (tmp / "prov" / ".coyomap").mkdir(parents=True, exist_ok=True)
    return tmp / "prov"


def _changes_log(tmp: Path, map_path: Path) -> Path:
    """A one-entry change log naming the map's first use case — the smallest log `changes lint`
    can read against this map."""
    doc = json.loads(map_path.read_text(encoding="utf-8"))
    uc = doc["use_cases"][0]["id"]
    log = {"format": "coyomap-changes", "version": 1, "from_commit": "a" * 7, "to_commit": "b" * 7,
           "date": "2026-09-17", "entries": [{"id": "e1", "headline": "The sweep names one use case",
           "sentence": "A use case is named so the lint has a box to check.", "elements": [uc]}]}
    path = tmp / "changes.json"
    path.write_text(json.dumps(log), encoding="utf-8")
    return path


def _git_map(tmp: Path, map_path: Path) -> Path:
    """The assembled map inside a real git repo, pinned to that repo's one commit — what `impact`
    and `reanchor` need to resolve a range. Nothing registers this repo anywhere."""
    repo = tmp / "gitrepo"
    (repo / ".coyomap").mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, env=env)
    (repo / "README.md").write_text("sweep\n", encoding="utf-8")
    run("init", "-q")
    run("add", "-A")
    run("commit", "-q", "-m", "pin")
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True,
                         text=True, env=env).stdout.strip()
    doc = json.loads(map_path.read_text(encoding="utf-8"))
    doc["commit"] = sha
    out = repo / ".coyomap" / "project-map.json"
    out.write_text(json.dumps(doc), encoding="utf-8")
    return out


#: command -> (argv builder, allowed exit codes). The builder gets (tmp_dir, assembled_map_path).
#: What a recipe IS: given a scratch directory and a map path, the argv to hand `cli`. Typed,
#: because `dict[str, object]` made every `RECIPES[verb](...)` an uncallable `object`.
Recipe = Callable[[Path, Path], list[str]]

def _staged_project_export(tmp: Path, map_path: Path) -> list[str]:
    """Put the assembled map in a project folder of its own, and export THAT."""
    proj = tmp / "proj"
    (proj / ".coyomap").mkdir(parents=True, exist_ok=True)
    shutil.copy(map_path, proj / ".coyomap" / "project-map.json")
    return ["export", str(proj), "--out", str(tmp / "site")]


RECIPES: dict[str, tuple] = {
    "validate":      (lambda t, m: ["validate", str(m), "--check-sources", "--check-coverage"], OK),
    "audit":         (lambda t, m: ["audit", str(m), "--json"], OK),
    # Takes a contract NAME, never a map: it prints the text one fan-out agent receives.
    "contract":      (lambda t, m: ["contract", "harvest"], OK),
    "balance":       (lambda t, m: ["balance", str(m)], OK),
    "render":        (lambda t, m: ["render", str(m), str(t / "out.md")], OK),
    "assemble":      (lambda t, m: ["assemble", *[str(p) for p in FRAGMENTS],
                                    "--out", str(t / "asm")], OK),
    "diff":          (lambda t, m: ["diff", str(MAP), str(m)], OK),
    "changes":       (lambda t, m: ["changes", "lint", str(_changes_log(t, m)), "--map", str(m)], OK),
    # Both need a git range to resolve, so the map is staged in a scratch repo pinned to its one commit.
    "impact":        (lambda t, m: ["impact", "--map", str(_git_map(t, m)), "--target", "HEAD"], OK),
    "reanchor":      (lambda t, m: ["reanchor", "--map", str(_git_map(t, m))], OK),
    "dump":          (lambda t, m: ["dump", str(m), "--counts"], OK),
    # Read-only: the address of one element. With no server running it prints the path alone and
    # says so on stderr, still exit 0 — the link is what it could give.
    "url":           (lambda t, m: ["url", "UC1", "--map", str(m)], OK),
    # `export` takes a PROJECT FOLDER, not a map path, so the recipe stages one: the assembled map
    # in a `.coyomap/` of its own. The code read out of git comes back empty (the map's pin is not a
    # commit of this staged folder) and the command still has to produce a whole site — which is the
    # shape a publisher hits with a map pinned to a commit they have not fetched.
    "export":        (_staged_project_export, OK),
    "scope":         (lambda t, m: ["scope"], OK),
    "reconcile":     (lambda t, m: ["reconcile", "--rules", str(FIXTURE / "rules.json"),
                                    "--fragments", str(FIXTURE / "fragments"),
                                    "--out", str(t / "rec.json")], OK),
    "lint-fragment": (lambda t, m: ["lint-fragment", "--repo", str(FIXTURE),
                                    *[str(p) for p in FRAGMENTS]], OK),
    "anchor-drift":  (lambda t, m: ["anchor-drift", "--map", str(m), "--repo", str(FIXTURE)], OK),
    "finalize":      (lambda t, m: ["finalize", str(m), "--repo", str(FIXTURE)], OK),
    "grounding":     (lambda t, m: ["grounding", "report", "--map", str(m),
                                    "--worklist", str(_worklist(t, m)),
                                    "--verdicts", str(_verdicts(t, m))], OK),
    "record":        (lambda t, m: ["record", "--map", str(_extras_copy(t)),
                                    "--heading", "Balance exceptions",
                                    "--line", "S1: deliberate, the fixture says so"], OK),
    "provenance":    (lambda t, m: ["provenance", "stamp", str(_with_coyomap_dir(t))], OK),
    "preindex":      (lambda t, m: ["preindex", "--root", str(FIXTURE),
                                    "--out", str(t / "pre.json")], OK),
    "fix":           (lambda t, m: ["fix", "dedup-relation", "--map", str(m)], OK),
    # ship's PREPARE phase (no --note-file): anchor-drift → apply-drift → assemble → report.
    # The finish phase stamps provenance and reads the session env, so prepare is the honest sweep.
    "ship":          (lambda t, m: ["ship", str(_ship_repo(t, m))], OK),
    # Takes no map: build telemetry beside the map. `order` on a repo with no record is the
    # shape a FIRST build sees, and it must exit 0 — a first build cannot be blocked waiting
    # for a measurement that does not exist yet.
    "timings":       (lambda t, m: ["timings", "order", "--repo", str(t), "--phase", "harvest"], OK),
    # Reads a claims batch, the map and the tree; writes only the bundle. The fixture's own
    # worklist is the honest input, since that is the shape a skeptic is actually handed.
    "context":       (lambda t, m: ["context", "--map", str(m), "--repo", str(FIXTURE),
                                    "--claims", str(_claims(t, m)), "--out", str(t / "b.md")], OK),
}


def _claims(tmp: Path, map_path: Path) -> Path:
    """A one-claim batch shaped like `coyomap audit --batches` writes them."""
    p = tmp / "claims.json"
    p.write_text(json.dumps({"schema": "coyomap-claims/v1", "theme": "backbone",
                             "claims": [{"claim": "C1 calls C2", "anchor": "src/a.py:10"}]}),
                 encoding="utf-8")
    return p


def _ship_repo(tmp: Path, map_path: Path) -> Path:
    """A repo shaped like a build at its closing sequence: fragments, a map, the pinned worklist,
    verdicts, and the fixture's reconcile file (so ship's assembles match `_assembled`'s)."""
    import shutil
    repo = tmp / "shiprepo"
    out = repo / ".coyomap"
    (out / "build-fragments").mkdir(parents=True, exist_ok=True)
    (out / "verify").mkdir(parents=True, exist_ok=True)
    for p in FRAGMENTS:
        shutil.copy(p, out / "build-fragments" / p.name)
    shutil.copy(map_path, out / "project-map.json")
    shutil.copy(FIXTURE / "reconcile.json", out / "reconcile.json")
    shutil.copy(_worklist(tmp, map_path), out / "verify" / "worklist.json")
    shutil.copy(_verdicts(tmp, map_path), out / "verify" / "verdicts-sweep.json")
    return repo

#: `fix` verb -> argv builder. Each is invoked in its LISTING form where it has one (no mutation),
#: because a sweep that edited the map would make every later case depend on the earlier ones.
FIX_RECIPES: dict[str, Recipe] = {
    "dedup-relation": lambda t, m: ["fix", "dedup-relation", "--map", str(m)],
    "dedup-edge":     lambda t, m: ["fix", "dedup-edge", "--map", str(m)],
    "dedup-security": lambda t, m: ["fix", "dedup-security", "--map", str(m)],
    "apply-drift":    lambda t, m: ["fix", "apply-drift", "--map", str(m),
                                    "--to-reconcile", str(t / "d.json")],
    "drop-edge":      lambda t, m: ["fix", "drop-edge", "--map", str(m),
                                    "C1", "calls", "C2", "--to-reconcile", str(t / "e.json")],
    "security-row":   lambda t, m: ["fix", "security-row", "--map", str(m)],
    "row":            lambda t, m: ["fix", "row", "--map", str(m)],
    # `rows` takes its batch from --edits, never from --map. An empty list is the honest sweep: it
    # exercises the parse and the refusal without needing a fragment set shaped for an edit.
    "rows":           lambda t, m: ["fix", "rows", "--map", str(m)],
}


#: `grounding` verb -> argv builder. Its own set for the same reason `fix` has one: a command with
#: a second-level dispatch is not covered by exercising one of its verbs.
GROUNDING_RECIPES: dict[str, Recipe] = {
    "report": lambda t, m: ["grounding", "report", "--map", str(m),
                            "--worklist", str(_worklist(t, m)),
                            "--verdicts", str(_verdicts(t, m))],
    "lint":   lambda t, m: ["grounding", "lint", "--verdicts", str(_verdicts(t, m))],
    "by-element": lambda t, m: ["grounding", "by-element", "--map", str(m),
                                "--worklist", str(_worklist(t, m)),
                                "--verdicts", str(_verdicts(t, m))],
    # No --worklist: the gate walks the verdicts against the live map, and the recipe has to
    # exercise the spelling a build actually uses.
    "refutations": lambda t, m: ["grounding", "refutations", "--map", str(m),
                                 "--verdicts", str(_verdicts(t, m))],
    "write":  lambda t, m: ["grounding", "write", "--map", str(m),
                            "--worklist", str(_worklist(t, m)),
                            "--verdicts", str(_verdicts(t, m)),
                            "--partial", "--note", "sweep",
                            "--out", str(t / "grounding.json")],
}


def test_every_grounding_verb_has_a_sweep_recipe():
    """Read from the dispatch, like the others — a hand-kept list stops being complete quietly."""
    import re
    src = (REPO / "tools" / "coyomap" / "grounding.py").read_text(encoding="utf-8")
    m = re.search(r'verb not in \(([^)]*)\)', src)
    assert m, "could not read the grounding verb tuple — the gate would pass vacuously"
    verbs = set(re.findall(r'"([a-z-]+)"', m.group(1)))
    assert verbs, "no verbs parsed"
    missing = sorted(verbs - set(GROUNDING_RECIPES))
    stale = sorted(set(GROUNDING_RECIPES) - verbs)
    assert not missing, f"{missing} are `grounding` verbs with no sweep recipe"
    assert not stale, f"{stale} in GROUNDING_RECIPES but no longer a verb"


@pytest.mark.parametrize("verb", sorted(GROUNDING_RECIPES))
def test_the_grounding_verb_survives_a_realistic_map(verb, tmp_path):
    m = _assembled(tmp_path / "m")
    r = cli(*GROUNDING_RECIPES[verb](tmp_path, m))
    assert "Traceback" not in r.stderr, f"grounding {verb} crashed:\n{r.stderr[-3000:]}"
    assert r.returncode in (0, 1), f"grounding {verb} exited {r.returncode}\n{r.stderr[-1500:]}"


def test_the_sweep_never_registers_its_scratch_repos_with_serve() -> None:
    """The `ship` recipe assembles into a throwaway `<tmp>/shiprepo/.coyomap`, and a finished assemble
    registers its folder in ~/.coyomap/serve-recents.json — the landing page's cards. Every run left
    one more dead card there (577 by 2026-09-12). The root conftest.py sets the product's own opt-out
    for the whole run, and `cli()` hands children `os.environ`, so they inherit it. This is the guard
    that the switch stays set."""
    assert os.environ.get("COYOMAP_NO_SERVE_REGISTER"), "conftest.py no longer sets the opt-out"


def test_every_advertised_command_has_a_sweep_recipe():
    """THE COMPLETENESS GATE. Without it "comprehensive" decays the moment a command is added:
    the sweep keeps passing while covering less of the tool every release."""
    advertised = set(COMMAND_MODULE) - set(UNPROBEABLE)
    missing = sorted(advertised - set(RECIPES))
    stale = sorted(set(RECIPES) - advertised)
    assert not missing, (
        f"{missing} advertised by the CLI with no sweep recipe — add one to RECIPES so the command "
        f"is exercised against a real map, or justify it in UNPROBEABLE")
    assert not stale, f"{stale} in RECIPES but no longer advertised — delete the recipe"


def test_every_fix_verb_has_a_sweep_recipe():
    from coyomap.fix import _VERBS
    missing = sorted(set(_VERBS) - set(FIX_RECIPES))
    stale = sorted(set(FIX_RECIPES) - set(_VERBS))
    assert not missing, f"{missing} are `fix` verbs with no sweep recipe"
    assert not stale, f"{stale} in FIX_RECIPES but no longer a `fix` verb"


@pytest.mark.parametrize("command", sorted(RECIPES))
def test_the_command_survives_a_realistic_map(command, tmp_path):
    build, allowed = RECIPES[command]
    m = _assembled(tmp_path / "m")
    r = cli(*build(tmp_path, m))
    assert "Traceback" not in r.stderr, f"{command} crashed:\n{r.stderr[-3000:]}"
    assert r.returncode in allowed, (
        f"{command} exited {r.returncode}, expected one of {allowed}\n"
        f"stdout:{r.stdout[-1500:]}\nstderr:{r.stderr[-1500:]}")


@pytest.mark.parametrize("verb", sorted(FIX_RECIPES))
def test_the_fix_verb_survives_a_realistic_map(verb, tmp_path):
    m = _assembled(tmp_path / "m")
    r = cli(*FIX_RECIPES[verb](tmp_path, m))
    assert "Traceback" not in r.stderr, f"fix {verb} crashed:\n{r.stderr[-3000:]}"
    assert r.returncode in (0, 1, 2), f"fix {verb} exited {r.returncode}\n{r.stderr[-1500:]}"


#: Taken ONCE, at import, before any recipe has run.
_FIXTURE_AT_START = {p: p.read_bytes() for p in sorted(FIXTURE.rglob("*.json"))}


def test_the_sweep_left_the_committed_fixture_untouched():
    """SESSION-WIDE, not per test — and that distinction is the whole finding.

    The first version snapshotted inside each parametrized case. By the time it ran, `record` had
    already rewritten the committed `extras.json` in an earlier case, so the damage WAS the
    baseline and every case passed while the fixture sat modified in the working tree. It reached a
    commit. A guard that measures from after the harm cannot see it.

    Ordering makes this fragile in the other direction too (pytest may run this before the recipes),
    so the snapshot is taken at import and the comparison is against that, never against a state
    any test produced."""
    changed = [str(p.relative_to(FIXTURE)) for p, b in _FIXTURE_AT_START.items()
               if not p.exists() or p.read_bytes() != b]
    assert not changed, (
        f"the sweep modified committed fixture files: {changed}. A recipe that writes must be "
        f"pointed at a copy — see `_extras_copy`.")


def test_no_command_hangs_without_a_terminal():
    """Every recipe runs with stdin closed and no TTY, which is how CI and an agent invoke them.
    A command that waits for input there is a build that never finishes — and `assemble` shipped a
    subprocess call with no timeout that would do exactly that behind a credential prompt."""
    for command, (build, _allowed) in sorted(RECIPES.items()):
        pass  # the timeout in `cli()` enforces this for every parametrized case above
