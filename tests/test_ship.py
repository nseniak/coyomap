#!/usr/bin/env python3
"""Tests for `coyomap ship` — the closing sequence as one command.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_ship.py
    pytest tests/test_ship.py

The runner is INJECTED (a callable recording each step's argv), so these tests assert the plan and
the stop-on-failure contract without executing the underlying subcommands — those have their own
suites, and `tests/test_cli_sweep.py` drives `ship` end-to-end against the committed fixture.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import tempfile
from pathlib import Path

from coyomap import buildstate, ship


# --- builders -------------------------------------------------------------------

def make_repo(tmp: str, *, fragments: bool = True, worklist: bool = True,
              verdicts: bool = True, reconcile: bool = True) -> Path:
    """A repo skeleton holding exactly the closing sequence's inputs."""
    repo = Path(tmp) / "repo"
    out = repo / ".coyomap"
    (out / "build-fragments").mkdir(parents=True)
    (out / "verify").mkdir(parents=True)
    if fragments:
        (out / "build-fragments" / "b-slice.json").write_text("{}")
        (out / "build-fragments" / "a-slice.json").write_text("{}")
        (out / "build-fragments" / "half.draft.json").write_text("{}")  # must never assemble
    if worklist:
        (out / "verify" / "worklist.json").write_text("[]")
    if verdicts:
        (out / "verify" / "verdicts-security-1.json").write_text("{}")
        (out / "verify" / "verdicts-backbone-1.json").write_text("{}")
    if reconcile:
        (out / "reconcile.json").write_text("{}")
    return repo


def make_inputs(repo: Path, **kw) -> ship.ShipInputs:
    got = ship.derive_inputs(repo, **kw)
    assert not isinstance(got, str), got
    return got


def make_recording_runner(fail_on: str | None = None, code: int = 1):
    """A runner that records each step's argv and optionally fails the step whose argv[0]
    matches `fail_on` — dependency injection instead of patching the real subcommands."""
    calls: list[list[str]] = []

    def runner(argv: list[str]) -> int:
        calls.append(argv)
        return code if fail_on is not None and argv[0] == fail_on else 0

    return calls, runner


# --- deriving the inputs --------------------------------------------------------

def test_fragments_are_sorted_and_drafts_are_excluded():
    with tempfile.TemporaryDirectory() as td:
        s = make_inputs(make_repo(td))
        names = [p.name for p in s.fragments]
        assert names == ["a-slice.json", "b-slice.json"], (
            "fragment argument order decides dedup survivors, so it must be the shell's sorted "
            f"glob, drafts excluded — got {names}")


def test_derive_refuses_each_missing_input_by_name():
    with tempfile.TemporaryDirectory() as td:
        for kw, expect in ((dict(fragments=False), "no fragments"),
                           (dict(worklist=False), "worklist"),
                           (dict(verdicts=False), "verdicts")):
            repo = make_repo(tempfile.mkdtemp(dir=td), **kw)
            got = ship.derive_inputs(repo)
            assert isinstance(got, str) and expect in got, f"{kw}: {got}"


def test_a_missing_reconcile_file_is_none_not_an_error():
    with tempfile.TemporaryDirectory() as td:
        s = make_inputs(make_repo(td, reconcile=False))
        assert s.reconcile is None


# --- the plan -------------------------------------------------------------------

def test_prepare_plan_is_the_four_steps_ending_in_the_report():
    with tempfile.TemporaryDirectory() as td:
        steps = ship.build_plan(make_inputs(make_repo(td)))
        assert [st.argv[0] for st in steps] == ["anchor-drift", "fix", "assemble", "grounding"]
        assert steps[-1].argv[1] == "report", "the prepare phase must END on the report the note is written from"
        # every step that reads verdicts repeats the flag once per file
        assert steps[0].argv.count("--verdicts") == 2
        assert "--to-reconcile" in steps[1].argv
        assert "--reconcile" in steps[2].argv


def test_full_plan_runs_the_method_sequence_in_order():
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        note = repo / "note.txt"
        note.write_text("319 of 1608 challenged")
        steps = ship.build_plan(make_inputs(repo, note_file=note, partial=True))
        heads = [(st.argv[0], st.argv[1] if len(st.argv) > 1 else "") for st in steps]
        assert [h[0] for h in heads] == [
            "anchor-drift", "fix", "assemble",           # the idempotent prepare prefix
            "grounding", "assemble", "provenance",       # write → carry in → stamp
            "assemble", "lint-fragment",                 # header in → lint
            "grounding",                                 # by-element: the list behind the count
            "validate", "audit", "render", "finalize"], heads
        write = steps[3].argv
        assert write[1] == "write" and "--note-file" in write and "--partial" in write
        assert "--keep-note" not in write
        stamp = steps[5].argv
        assert "--update-header" in stamp and "--mode" in stamp
        fin = steps[-1].argv
        assert "--emit-gate-block" in fin and "--access-baseline" not in fin


def test_the_record_written_at_step_6_is_named_by_every_assemble_after_it_on_the_first_run():
    """`ship` globs the fragments once, before any step runs. On the run that writes the grounding
    record for the first time, `build-fragments/grounding.json` does not exist yet, so an assemble
    built from that glob carries every fragment but the one step 6 produced — and the map ships
    with no record until `ship` runs twice. A live build found its map without the record after a
    clean run. The assembles AFTER the write name the file; the one before it does not."""
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        note = repo / "note.txt"
        note.write_text("a note")
        steps = ship.build_plan(make_inputs(repo, note_file=note))
        record = str(repo / ".coyomap" / "build-fragments" / "grounding.json")
        assert not Path(record).exists(), "the case is a record that is NOT there when ship starts"
        assembles = [st for st in steps if st.argv[0] == "assemble"]
        assert len(assembles) == 3, [st.title for st in assembles]
        before_write, carry_in, header_in = assembles
        assert record not in before_write.argv, "step 4 runs before the record exists"
        assert record in carry_in.argv and record in header_in.argv
        # in sorted position, never appended: argument order decides dedup survivors
        frags = list(carry_in.argv[1:carry_in.argv.index("--out")])
        assert frags == sorted(frags) and "half.draft.json" not in " ".join(frags)


def test_access_baseline_reaches_finalize_and_only_finalize():
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        note = repo / "note.txt"
        note.write_text("n")
        base = repo / "old-map.json"
        base.write_text("{}")
        steps = ship.build_plan(make_inputs(repo, note_file=note, access_baseline=base))
        carriers = [st.argv[0] for st in steps if "--access-baseline" in st.argv]
        assert carriers == ["finalize"]


def test_without_a_reconcile_file_no_assemble_carries_the_flag():
    with tempfile.TemporaryDirectory() as td:
        steps = ship.build_plan(make_inputs(make_repo(td, reconcile=False)))
        for st in steps:
            if st.argv[0] == "assemble":
                assert "--reconcile" not in st.argv


# --- running --------------------------------------------------------------------

def test_run_stops_at_the_first_failing_step_and_names_the_rest():
    with tempfile.TemporaryDirectory() as td:
        steps = ship.build_plan(make_inputs(make_repo(td)))
        calls, runner = make_recording_runner(fail_on="fix", code=3)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            run = ship.run_plan(steps, runner)
        assert run.rc == 3, "the failing step's own exit code must propagate"
        assert run.stopped == 2 and run.title == steps[1].title, run
        assert [c[0] for c in calls] == ["anchor-drift", "fix"], (
            "a step after the failure ran — a skipped step must never happen silently, and a run "
            "one must never happen at all")
        said = err.getvalue()
        assert "SHIP STOPPED" in said and "NOT RUN" in said and "assemble" in said


def test_a_clean_run_calls_every_step_once():
    with tempfile.TemporaryDirectory() as td:
        steps = ship.build_plan(make_inputs(make_repo(td)))
        calls, runner = make_recording_runner()
        with contextlib.redirect_stdout(io.StringIO()):
            run = ship.run_plan(steps, runner)
        assert run.rc == 0 and run.stopped is None, run
        assert len(calls) == len(steps)


def test_each_step_prints_a_line_the_shell_can_run_again():
    """Review of round 2 (2026-10-08): the step line was the argv joined by spaces, so a path with a
    space split into two words when the retro copied the line, as its method tells it to."""
    steps = [ship.Step(title="validate", argv=("validate", "/a b/.coyomap/project-map.json", "--x"))]
    _calls, runner = make_recording_runner()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        ship.run_plan(steps, runner)
    line = next(ln.strip() for ln in out.getvalue().splitlines() if ln.startswith("    "))
    assert shlex.split(line) == list(steps[0].argv), line


# --- the command shell ----------------------------------------------------------

def test_main_refuses_an_unknown_option():
    assert ship.main(["--definitely-not-a-real-flag"]) == 2


def test_main_requires_a_repo():
    assert ship.main(["--partial"]) == 2


def test_main_refuses_a_note_file_that_does_not_exist():
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        assert ship.main([str(repo), "--note-file", str(repo / "missing-note.txt")]) == 2


def test_main_names_whats_missing_on_an_empty_repo(capsys):
    with tempfile.TemporaryDirectory() as td:
        assert ship.main([td]) == 2
        assert "fragments" in capsys.readouterr().err


if __name__ == "__main__":
    import inspect

    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            if "capsys" in inspect.signature(_fn).parameters:
                continue  # pytest-only: needs capture
            _fn()
            print(f"ok  {_name}")
    print("ship tests passed (capsys ones under pytest)")


# --- one verdict list, two commands with opposite contracts -----------------------------------
# `grounding write` refuses a verdict whose claim is not in the pinned worklist; `finalize` needs
# every verdict there is. `ship` spliced ONE `--verdicts` tuple into both. On the 2026-08-29
# mcpolis build it stopped at step 6 with "9 verdict claim(s) are not in the pinned worklist", the
# lead abandoned the verb and hand-ran steps 5-12, and the map still shipped finalize's "the
# record's delta counts contradict the verdict files" as a carried-no-escape advisory — because the
# two commands had been measured against different sets.

def _ship_dirs(tmp: Path, pinned_claims: list[str], files: dict[str, list[str]]) -> Path:
    import json as _json
    out = tmp / ".coyomap"
    (out / "verify").mkdir(parents=True)
    (out / "build-fragments").mkdir(parents=True)
    (out / "verify" / "worklist.json").write_text(
        _json.dumps({"worklist": [{"claim": c} for c in pinned_claims]}), encoding="utf-8")
    for name, claims in files.items():
        (out / "verify" / f"verdicts-{name}.json").write_text(
            _json.dumps({"grounding": [{"claim": c, "grounded": True} for c in claims]}),
            encoding="utf-8")
    return out


def _plan_argvs(out: Path, tmp: Path):
    from coyomap.ship import ShipInputs, build_plan
    s = ShipInputs(map_path=out / "project-map.json", repo=tmp, out=out,
                   header=out / "build-fragments" / "header.json",
                   md=out / "project-map.md", gate_block=out / "verify" / "gate-block.md",
                   reconcile=out / "reconcile.json", worklist=out / "verify" / "worklist.json",
                   verdicts=tuple(sorted((out / "verify").glob("verdicts-*.json"))),
                   note_file=tmp / "note.txt", fragments=(), partial=False, keep_note=False,
                   note_cites_other_runs=False, access_baseline=None)
    return {step.title: step.argv for step in build_plan(s)}


def test_grounding_write_gets_only_the_pinned_verdicts_and_finalize_gets_them_all():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "note.txt").write_text("a note", encoding="utf-8")
        out = _ship_dirs(tmp, ["c1", "c2"],
                         {"pinned": ["c1", "c2"], "recheck": ["c9-minted-after-the-pin"]})
        argvs = _plan_argvs(out, tmp)
    write = next(a for t, a in argvs.items() if t.startswith("grounding write"))
    final = next(a for t, a in argvs.items() if t.startswith("finalize"))
    assert "verdicts-recheck.json" not in " ".join(write), write
    assert "verdicts-pinned.json" in " ".join(write), write
    assert "verdicts-recheck.json" in " ".join(final), final
    assert "verdicts-pinned.json" in " ".join(final), final


def test_a_file_that_STRADDLES_the_pin_is_dropped_too():
    """The case the whole fix exists for, and the one a first version got wrong.

    On the real build the nine off-pin claims sat in three `verdicts-recheck*.json` files that each
    ALSO carried three pinned ones. Keeping straddlers left `grounding write` refusing the set with
    the identical "9 verdict claim(s) are not in the pinned worklist" — the failure the docstring
    quotes. The set the build needed by hand was the files with no post-pin claim at all."""
    import tempfile
    from coyomap.ship import ShipInputs, post_pin_verdicts
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "note.txt").write_text("a note", encoding="utf-8")
        out = _ship_dirs(tmp, ["c1"], {"pinned": ["c1"], "mixed": ["c1", "c-new"]})
        argvs = _plan_argvs(out, tmp)
        s = ShipInputs(map_path=out / "project-map.json", repo=tmp, out=out,
                       header=out / "build-fragments" / "header.json", md=out / "project-map.md",
                       gate_block=out / "verify" / "gate-block.md",
                       reconcile=out / "reconcile.json", worklist=out / "verify" / "worklist.json",
                       verdicts=tuple(sorted((out / "verify").glob("verdicts-*.json"))),
                       note_file=tmp / "note.txt", fragments=(), partial=False, keep_note=False,
                       note_cites_other_runs=False, access_baseline=None)
        dropped = [p.name for p in post_pin_verdicts(s)]
    write = " ".join(next(a for t, a in argvs.items() if t.startswith("grounding write")))
    final = " ".join(next(a for t, a in argvs.items() if t.startswith("finalize")))
    assert "verdicts-mixed.json" not in write, write
    assert "verdicts-pinned.json" in write, write
    assert "verdicts-mixed.json" in final, "finalize still needs every verdict"
    assert dropped == ["verdicts-mixed.json"], dropped


# --- the operator report's coverage line (retro 2026-09-01, argus row 2) -------------------------
# The build's closing message is written from `claims_total`, the size of the worklist the skeptics
# were given. That is not coverage of the SHIPPED map: a claim reworded after the vote stays in the
# map and loses its verdict. Two builds in a row headlined "all N claims challenged" over fewer.

def _grounding(repo: Path, **fields) -> None:
    import json
    record = {"claims_total": 454, "claims_live_challenged": 440,
              "claims_superseded": 0, "claims_added_since": 0}
    record.update(fields)
    # where `ship`'s own plan sends `grounding write --out`: beside the header fragment.
    (repo / ".coyomap" / "build-fragments" / "grounding.json").write_text(
        json.dumps({"grounding": record}), encoding="utf-8")


def test_the_coverage_line_states_the_shipped_map_not_the_pinned_worklist():
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp)
        _grounding(repo)
        line = ship._coverage_line(make_inputs(repo))
    assert "454 claims challenged" in line, line          # the sentence it refuses
    assert "454 claim(s), of which 440" in line, line
    assert "14 do NOT" in line, line


def test_the_live_total_is_computed_from_the_record_not_assumed_equal_to_the_pinned_one():
    """The whole defect is that the two differ. 454 pinned, 4 superseded, 10 added -> 460 live."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp)
        _grounding(repo, claims_superseded=4, claims_added_since=10, claims_live_challenged=440)
        line = ship._coverage_line(make_inputs(repo))
    assert "460 claim(s), of which 440" in line, line
    assert "20 do NOT" in line, line


def test_full_coverage_says_so_and_still_names_the_right_number():
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp)
        _grounding(repo, claims_live_challenged=454)
        line = ship._coverage_line(make_inputs(repo))
    assert "every one of the shipped map's 454 claim(s)" in line, line


def test_an_unreadable_grounding_record_makes_ship_silent_not_wrong():
    """finalize reports a broken record; a second voice guessing at it only adds noise."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = make_repo(tmp)
        assert ship._coverage_line(make_inputs(repo)) == ""
        (repo / ".coyomap" / "build-fragments" / "grounding.json").write_text(
            "{not json", encoding="utf-8")
        assert ship._coverage_line(make_inputs(repo)) == ""


def test_step_2_counts_drift_coverage_at_the_pinned_worklists_tier():
    """The gate block's `challenged N of M` comes from step 2; M followed the default tier always,
    so a behavioural pass read 833 under an audit line counting 1782. The flag follows the pinned
    worklist's own items."""
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        assert "--with-behavioural" not in ship.build_plan(make_inputs(repo))[0].argv
        (repo / ".coyomap" / "verify" / "worklist.json").write_text(
            '{"worklist": [{"claim": "UC1 step 1: R1 → C1 — send the token", "theme": "behaviour"}]}',
            encoding="utf-8")
        step2 = ship.build_plan(make_inputs(repo))[0]
        assert step2.argv[0] == "anchor-drift" and "--with-behavioural" in step2.argv, step2


def test_the_newest_archived_map_is_the_access_baseline_unless_one_is_given():
    """`finalize --access-baseline` exists for the map an archive filed, and the 2026-09-08 build
    never ran it because nothing in the closing sequence asked. The newest `dev-rebuilds/NNNN/` map
    is the default; an explicit flag still wins; a repo with no archive passes nothing."""
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        note = repo / "note.txt"
        note.write_text("n")
        for n in ("0002", "0010"):
            d = repo / ".coyomap" / "dev-rebuilds" / n
            d.mkdir(parents=True)
            (d / "project-map.json").write_text("{}")
        fin = ship.build_plan(make_inputs(repo, note_file=note))[-1].argv
        assert fin[0] == "finalize" and "--access-baseline" in fin
        assert fin[fin.index("--access-baseline") + 1].endswith("dev-rebuilds/0010/project-map.json")
        mine = repo / "old.json"
        mine.write_text("{}")
        fin = ship.build_plan(make_inputs(repo, note_file=note, access_baseline=mine))[-1].argv
        assert fin[fin.index("--access-baseline") + 1] == str(mine)

# --- the closer's appeals are an input too (retro 2026-09-13 reminderrepo, T7) ----------
# `contract closer` writes `verify/closer-<agent>.json` in the skeptics' own shape. The glob
# here saw `verdicts-*.json` only, so the file sat beside the map and no step of the closing
# sequence opened it — a refutation the closer had REJECTED still blocked the ship gate.

def test_ship_gives_every_step_the_closer_file_too(tmp_path):
    repo = tmp_path / "r"
    (repo / ".coyomap" / "build-fragments").mkdir(parents=True)
    (repo / ".coyomap" / "build-fragments" / "a.json").write_text("{}")
    verify = repo / ".coyomap" / "verify"
    verify.mkdir()
    (verify / "worklist.json").write_text(json.dumps({"worklist": [{"claim": "c1"}]}))
    (verify / "verdicts-rule-1.json").write_text(json.dumps({"grounding": []}))
    (verify / "closer-agent-1.json").write_text(json.dumps({"grounding": []}))
    inputs = ship.derive_inputs(repo)
    assert not isinstance(inputs, str), inputs
    assert [p.name for p in inputs.verdicts] == ["verdicts-rule-1.json", "closer-agent-1.json"]


def test_ship_refuses_a_closer_file_with_no_skeptics_beside_it(tmp_path):
    repo = tmp_path / "r"
    (repo / ".coyomap" / "build-fragments").mkdir(parents=True)
    (repo / ".coyomap" / "build-fragments" / "a.json").write_text("{}")
    verify = repo / ".coyomap" / "verify"
    verify.mkdir()
    (verify / "worklist.json").write_text(json.dumps({"worklist": [{"claim": "c1"}]}))
    (verify / "closer-agent-1.json").write_text(json.dumps({"grounding": []}))
    problem = ship.derive_inputs(repo)
    assert isinstance(problem, str) and "appeal against nothing" in problem, problem


def test_a_second_waves_verdict_file_reaches_grounding_write():
    """Retro 2026-09-30, finding 4: `grounding write --map` folds a verdict on a claim the map
    makes and the pin never held into the pin. Filtering on the pin alone handed the second wave's
    file to nobody, so the route the method names would have run and recorded nothing. A claim in
    neither the pin nor the map still holds its file back."""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "note.txt").write_text("a note", encoding="utf-8")
        out = _ship_dirs(tmp, ["c1"], {"pinned": ["c1"], "added-backbone-1": ["C3 reads E1"],
                                       "stale": ["C9 calls C10"]})
        (out / "project-map.json").write_text(json.dumps({
            "format": "coyomap-map", "title": "T", "goal": "g",
            "components": [{"id": "C3", "name": "Reader", "purpose": "reads the record"}],
            "entities": [{"id": "E1", "name": "Record", "meaning": "a saved row"}],
            "edges": [{"src": "C3", "verb": "reads", "dst": "E1", "why": "w", "where": "b.py:2"}]}),
            encoding="utf-8")
        argvs = _plan_argvs(out, tmp)
    write = " ".join(next(a for t, a in argvs.items() if t.startswith("grounding write")))
    assert "verdicts-added-backbone-1.json" in write, write
    assert "verdicts-stale.json" not in write, write


# --- ship writes its outcome to the build state (round 1) -----------------------------------------
# The closing sequence is where a long build is most likely to have been summarized, so the state
# says what ran, where it stopped, and the exact next command.

def run_ship(argv: list[str], runner: ship.Runner) -> int:
    """`ship` in-process with an injected step runner, its output dropped."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return ship.main(argv, runner=runner)


def make_state_events(repo: Path) -> list[tuple[str, str]]:
    """`(kind, text)` of every event in the repo's build state."""
    state = buildstate.read_state(repo)
    assert state is not None, "no build state"
    return [(e.kind, e.text) for e in state.events]


def make_long_dir(base: Path, length: int) -> Path:
    """A new folder under `base` whose path is `length` characters, as a worktree's or a session
    scratchpad's is."""
    folder = base / ("p" * (length - len(str(base)) - 1))
    folder.mkdir(parents=True)
    return folder


def run_ship_from(cwd: Path, argv: list[str], runner: ship.Runner) -> int:
    """`run_ship` from `cwd`, the paths as a lead types them there. The folder is always restored."""
    here = Path.cwd()
    try:
        os.chdir(cwd)
        return run_ship(argv, runner)
    finally:
        os.chdir(here)


def test_a_prepared_ship_writes_its_next_step():
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        buildstate.start(repo)
        _calls, runner = make_recording_runner()
        assert run_ship([str(repo)], runner) == 0
        events = make_state_events(repo)[1:]
    assert [k for k, _t in events] == ["ship", "next"], events
    assert events[0][1].startswith("prepared — 4 step(s) ran"), events
    assert (f"coyomap ship {repo.resolve()} --note-file <the note file>") in events[1][1], events


def test_a_stopped_ship_names_the_step_and_the_rerun():
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        buildstate.start(repo)
        _calls, runner = make_recording_runner(fail_on="fix", code=3)
        assert run_ship([str(repo), "--partial"], runner) == 3
        events = make_state_events(repo)[1:]
    assert [k for k, _t in events] == ["ship", "next"], events
    assert events[0][1].startswith("stopped at [2/4] fix apply-drift") and "(exit 3)" in events[0][1]
    assert events[1][1].endswith(f"then re-run: coyomap ship {repo.resolve()} --partial"), events


def test_a_stopped_ship_keeps_its_whole_rerun_at_a_real_builds_path_lengths():
    """The paths of the 2026-10-07 build: an 87-character worktree repo, a 177-character note file
    in the session's scratchpad. At the first line cap the re-run lost the end of the note path and
    its `--partial`."""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td).resolve()
        repo = make_repo(str(make_long_dir(base / "w", 87 - len("/repo"))))
        note = make_long_dir(base / "s", 177 - len("/grounding-note.md")) / "grounding-note.md"
        note.write_text("319 of 1608 challenged")
        buildstate.start(repo)
        _calls, runner = make_recording_runner(fail_on="grounding")
        assert run_ship([str(repo), "--note-file", str(note), "--partial"], runner) == 1
        log = buildstate.state_path(repo).read_text(encoding="utf-8")
        longest = max(len(line) for line in log.splitlines())
        events = make_state_events(repo)[1:]
    assert (len(str(repo)), len(str(note))) == (87, 177)
    assert [k for k, _t in events] == ["ship", "next"], events
    assert events[0][1].startswith("stopped at [4/13] grounding write"), events
    assert events[1][1].endswith(f"then re-run: coyomap ship {repo} --note-file {note} --partial"), (
        events)
    assert longest > 300, "the paths no longer reach past the first cap, so this tests nothing"


def test_the_rerun_spells_every_path_absolute():
    """The re-run is read after a summary, from whatever folder the shell has drifted to by then,
    so a path typed relative to the repo is written as the absolute path ship read."""
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td).resolve()
        (repo / "note.md").write_text("a note")
        buildstate.start(repo)
        _calls, runner = make_recording_runner(fail_on="grounding")
        code = run_ship_from(repo, [".", "--note-file", "note.md", "--worklist",
                                    ".coyomap/verify/worklist.json", "--keep-note"], runner)
        events = make_state_events(repo)[1:]
    assert code == 1
    assert events[1][1].endswith(
        f"then re-run: coyomap ship {repo} --note-file {repo / 'note.md'} --worklist "
        f"{repo / '.coyomap' / 'verify' / 'worklist.json'} --keep-note"), events


def test_a_prepared_ships_next_step_quotes_a_repo_path_with_a_space():
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(str(Path(td) / "my projects")).resolve()
        buildstate.start(repo)
        _calls, runner = make_recording_runner()
        assert run_ship([str(repo)], runner) == 0
        events = make_state_events(repo)[1:]
    assert f"then run: coyomap ship '{repo}' --note-file <the note file>" in events[1][1], events


def test_a_complete_ship_ends_the_state():
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        note = repo / "note.txt"
        note.write_text("a note")
        buildstate.start(repo)
        calls, runner = make_recording_runner()
        assert run_ship([str(repo), "--note-file", str(note)], runner) == 0
        state = buildstate.read_state(repo)
        events = make_state_events(repo)[1:]
    assert calls[-1][0] == "finalize", calls[-1]
    assert [k for k, _t in events] == ["ship", "end"], events
    assert events[0][1].startswith(f"complete — {len(calls)} step(s) ran through finalize"), events
    assert events[1][1] == "ship complete · the map is ready; the build does not commit it"
    assert state is not None and not state.is_open, "a completed ship leaves the state open"

