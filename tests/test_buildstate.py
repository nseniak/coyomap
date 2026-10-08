#!/usr/bin/env python3
"""Tests for `coyomap state` — the build's short memory, written by the tools as they run.

A long build's lead had its context replaced by a summary that kept the operator's rules and the
pending steps and dropped the `--map` of `record`, so the first record after it went to the wrong
file. These tests hold the file that keeps those flags: one line per event, written whole by every
tool at once, never failing its tool, and a view short enough to read after a summary.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_buildstate.py
    pytest tests/test_buildstate.py
"""
from __future__ import annotations

import contextlib
import io
import multiprocessing
import re
import stat
import tempfile
from multiprocessing.synchronize import Barrier
from pathlib import Path

from coyomap import buildstate
from coyomap.buildstate import (CLOSING_LINE, LINE_CAP, PHASES, PREV_NAME, RUNNER_OUT, STATE_NAME,
                                WHOLE_KINDS, append, main, read_state, sections, show_lines,
                                state_path)
from coyomap.credentials import REDACTED
from coyomap.waveplan import PLAN_FILE, PlanAgent, WavePlan, write_plan

REPO_ROOT = Path(__file__).resolve().parent.parent
EVENT = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} \S+ ")


def make_repo(td: str, name: str = "repo") -> Path:
    """An empty folder standing for the repo a build maps."""
    repo = Path(td) / name
    repo.mkdir(parents=True, exist_ok=True)
    return repo


def run_state(argv: list[str]) -> tuple[int, str, str]:
    """`coyomap state …` in-process: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def make_state(td: str) -> Path:
    """A repo with an open build state, opened through the command a lead runs."""
    repo = make_repo(td)
    code, _out, err = run_state(["start", "--repo", str(repo)])
    assert code == 0, err
    return repo


def make_clone(td: str) -> Path:
    """A coyomap clone whose method.md holds the harvest section on lines 3-4 and the synthesis
    phase's start, but not its end, so synthesis has no section."""
    clone = Path(td) / "clone"
    clone.mkdir(parents=True, exist_ok=True)
    (clone / "method.md").write_text(
        "# A method\n"
        "intro\n"
        "- Phase 1 Harvest (fan out, one agent each): the harvest rules\n"
        "more harvest rules\n"
        "- Phase 2 Synthesize (barrier, one agent): the synthesis rules\n",
        encoding="utf-8")
    return clone


def make_view(repo: Path, clone: Path | None = None) -> list[str]:
    """What `state show` prints for `repo`, one entry per printed line."""
    state = read_state(repo)
    assert state is not None
    text = "\n".join(line for line in show_lines(state, repo, clone or REPO_ROOT) if line)
    return text.splitlines()


def make_log_lines(repo: Path) -> list[str]:
    return state_path(repo).read_text(encoding="utf-8").splitlines()


def make_wave_plan(briefs: Path, verify: Path, voters: list[str]) -> Path:
    """A wave plan in `briefs` naming one voter per id, each with its verdicts file in `verify`,
    written by the writer `contract skeptic --from-batches` uses."""
    agents = tuple(PlanAgent(id=v, claims=verify / f"claims-{v}.json", theme="backbone",
                             brief=briefs / f"skeptic-{v}.md", verdicts=verify / f"verdicts-{v}.json",
                             pointer=f"{v}\n{briefs / f'skeptic-{v}.md'}\n") for v in voters)
    plan = briefs / PLAN_FILE
    write_plan(plan, WavePlan(verify=verify, prefix="", votes={}, agents=agents))
    return plan


def make_wave_event(runner: str, plan: Path) -> str:
    """The `wave` event `contract wave --fill` writes for one runner."""
    return f"{runner} · pool 8 · prefix '' · plan {plan}"


# ── start ────────────────────────────────────────────────────────────────────────────────────────

def test_start_writes_the_header_and_one_start_line() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        lines = make_log_lines(repo)
    assert len(lines) == 3, lines
    assert lines[0].startswith("# ") and lines[1].startswith("# "), lines
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} start    build · pin .+ · coyomap .+ · "
                    r"findings \.coyomap/findings/$", lines[2]), lines[2]


def test_start_refuses_an_open_state_and_names_new() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        assert append(repo, "decision", "pin B: build on the dirty tree")
        before = state_path(repo).read_bytes()
        code, _out, err = run_state(["start", "--repo", str(repo)])
        after = state_path(repo).read_bytes()
        started = make_log_lines(repo)[2][:16]
    assert code == 2
    assert "--new" in err and "already open" in err, err
    assert f"started {started}" in err, err
    assert "pin B: build on the dirty tree" in err, "the refusal names the last event"
    assert after == before, "a refused start changes nothing"


def test_start_new_keeps_the_previous_state_as_prev() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        assert append(repo, "decision", "the first build's rule")
        code, out, err = run_state(["start", "--new", "--repo", str(repo)])
        prev = (repo / ".coyomap" / PREV_NAME).read_text(encoding="utf-8")
        now = state_path(repo).read_text(encoding="utf-8")
    assert code == 0, err
    assert "the first build's rule" in prev
    assert "the first build's rule" not in now
    assert sum(1 for line in now.splitlines() if " start " in line) == 1
    assert PREV_NAME in out and "open" in out, out


def test_an_ended_state_is_moved_aside_without_a_flag() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        assert append(repo, "end", "ship complete")
        code, _out, err = run_state(["start", "--repo", str(repo)])
        prev = (repo / ".coyomap" / PREV_NAME).read_text(encoding="utf-8")
        state = read_state(repo)
    assert code == 0, err
    assert "ship complete" in prev
    assert state is not None and state.is_open and len(state.events) == 1


# ── append ───────────────────────────────────────────────────────────────────────────────────────

def test_append_writes_nothing_when_no_state_exists() -> None:
    with tempfile.TemporaryDirectory() as td:
        bare = make_repo(td, "bare")
        with_folder = make_repo(td, "with-folder")
        (with_folder / ".coyomap").mkdir()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            results = [append(bare, "record", "x"), append(with_folder, "record", "x"),
                       append(None, "record", "x")]
        created = [p for p in (state_path(bare), state_path(with_folder)) if p.exists()]
    assert results == [False, False, False]
    assert not created, "only `state start` creates the file"
    assert err.getvalue() == "", "with no state there is nothing to say"


def test_append_never_fails_its_tool() -> None:
    """A state that cannot be written costs the tool one stderr line, never its run."""
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        path = state_path(repo)
        path.chmod(stat.S_IRUSR)
        path.parent.chmod(stat.S_IRUSR | stat.S_IXUSR)
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                written = append(repo, "record", "+1 under \"Sweep debt\"")
        finally:
            path.parent.chmod(stat.S_IRWXU)
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        lines = make_log_lines(repo)
    assert written is False
    notes = err.getvalue().splitlines()
    assert len(notes) == 1 and notes[0].startswith("note: build state not written ("), notes
    assert len(lines) == 3, "nothing was appended"


def test_a_long_event_is_clipped_to_the_line_cap() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        assert append(repo, "decision", "first line\nsecond line " + "x" * 2000)
        last = make_log_lines(repo)[-1]
    assert len(last) <= LINE_CAP and last.endswith("…"), (len(last), last[-20:])
    assert "first line second line x" in last, "an event is one line"


def test_a_line_that_carries_a_command_is_never_clipped() -> None:
    """A clipped command cannot be run: at the first cap, a stopped ship's re-run lost its
    `--partial`. Each command kind keeps its whole text, however long; the rest stay clipped."""
    command = "coyomap ship /a/repo " + " ".join(f"--verdicts /a/repo/.coyomap/verify/v-{k:02d}.json"
                                                 for k in range(40)) + " --partial"
    assert len(command) > LINE_CAP
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        for kind in WHOLE_KINDS:
            assert append(repo, kind, f"{kind}: {command}")
        lines = make_log_lines(repo)[3:]
    assert [line.split()[2] for line in lines] == list(WHOLE_KINDS), lines
    for kind, line in zip(WHOLE_KINDS, lines):
        assert line.endswith(f"{kind}: {command}"), (kind, line[-80:])


def test_an_append_never_raises() -> None:
    """The tool's work is done when it appends: a character UTF-8 cannot hold (an argument the
    shell could not decode) is written as its escape, and a path no file can have costs one note."""
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            written = append(repo, "record", "+1 under \"Sweep debt\" · src/caf\udce9.py")
            nul = append(repo / "a\0b", "record", "+1 under \"Sweep debt\"")
        lines = make_log_lines(repo)
    assert written is True, err.getvalue()
    assert lines[-1].endswith("src/caf\\udce9.py"), lines[-1]
    assert nul is False
    notes = err.getvalue().splitlines()
    assert len(notes) == 1 and notes[0].startswith("note: build state not written ("), notes


def test_a_credential_shaped_value_never_reaches_the_file() -> None:
    value = "gh" + "p_" + "a" * 36            # the shape, built at run time, never a real key
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        assert append(repo, "record", f"+1 under \"Sweep debt\" · coyomap record --line 'k={value}'")
        assert run_state(["add", "decision", f"use the token {value}", "--repo", str(repo)])[0] == 0
        text = state_path(repo).read_text(encoding="utf-8")
    assert value not in text
    assert text.count(REDACTED) == 2, text


def _append_many(repo: str, tag: str, n: int, barrier: Barrier) -> None:
    """One writer of the two-process test: wait for the other, then append `n` lines."""
    barrier.wait()
    for k in range(n):
        if not append(Path(repo), "record", f"{tag} {k:03d}"):
            raise SystemExit(1)


def test_two_processes_appending_lose_no_line() -> None:
    ctx = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        barrier = ctx.Barrier(2)
        procs = [ctx.Process(target=_append_many, args=(str(repo), tag, 200, barrier))
                 for tag in ("left", "right")]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
        codes = [p.exitcode for p in procs]
        events = [line for line in make_log_lines(repo) if EVENT.match(line)][1:]
    assert codes == [0, 0], codes
    assert len(events) == 400, len(events)
    for tag in ("left", "right"):
        mine = [e.split(" record   ", 1)[1] for e in events if f" {tag} " in f" {e} "]
        assert mine == [f"{tag} {k:03d}" for k in range(200)], f"{tag}: a line was lost or torn"


# ── show ─────────────────────────────────────────────────────────────────────────────────────────

def test_show_leads_with_one_verdict_line() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        assert run_state(["phase", "harvest", "--repo", str(repo)])[0] == 0
        assert append(repo, "decision", "pin A: the operator committed first")
        assert append(repo, "record", "+1 under \"Sweep debt\" → .coyomap/build-fragments/x.json")
        view = make_view(repo)
    assert re.match(r"^BUILD STATE — open since \d{4}-\d{2}-\d{2} \d{2}:\d{2} · phase harvest "
                    r"\(\d{4}-\d{2}-\d{2} \d{2}:\d{2}\) · 4 events: 1 decisions, 1 records$",
                    view[0]), view[0]
    assert not [line for line in view[1:] if line.startswith("BUILD STATE")], view
    assert view[-1] == CLOSING_LINE


def test_show_keeps_every_decision_and_only_the_last_assemble() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        for k in range(12):
            assert append(repo, "decision", f"rule number {k:02d}")
        assert append(repo, "assemble", "61 fragments, the FIRST assemble")
        for k in range(10):
            assert append(repo, "record", f"+1 under \"Sweep debt\" record {k:02d}")
        assert append(repo, "assemble", "62 fragments, the SECOND assemble")
        view = make_view(repo)
    text = "\n".join(view)
    assert all(f"rule number {k:02d}" in text for k in range(12)), "every decision is shown"
    assert "SECOND assemble" in text and "FIRST assemble" not in text
    shown_records = [k for k in range(10) if f"record {k:02d}" in text]
    assert shown_records == list(range(2, 10)), "the last 8 records"
    assert f"+2 more in .coyomap/{STATE_NAME}" in text
    assert len(view) <= 40 + 2, f"{len(view)} lines: at most 40, plus one per decision past 10"


def test_show_names_the_method_lines_of_the_current_phase() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        clone = make_clone(td)
        assert append(repo, "phase", "harvest")
        harvest = make_view(repo, clone)
        assert append(repo, "phase", "synthesis")
        synthesis = make_view(repo, clone)
        code, out, _err = run_state(["phase", "trace", "--repo", str(repo)])
    assert f"method: re-read {clone / 'method.md'} lines 3-4 (harvest)" in harvest, harvest
    assert any(line.startswith("method: ") and "synthesis" in line and "not found" in line
               for line in synthesis), synthesis
    assert code == 0
    assert re.search(r"^method: re-read \S+/method\.md lines \d+-\d+ \(trace\)$", out, re.M), out


def test_show_says_each_wave_runner_out_and_counts_its_verdict_files_now() -> None:
    """After a summary the lead must know a runner is out, or it starts the wave's voters itself
    and each runs twice. The count is read from the plan's voters at each `show`, never stored."""
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        verify = repo / ".coyomap" / "verify"
        verify.mkdir()
        briefs = Path(td).resolve() / "briefs-w1"
        plan = briefs / PLAN_FILE
        assert append(repo, "decision", "pin A: the operator committed first")
        # filled twice under one id (a `--force` re-fill): ONE runner, read from its last fill
        assert append(repo, "wave", make_wave_event("wave-1", Path(td) / "old" / PLAN_FILE))
        assert append(repo, "wave", make_wave_event("wave-1", plan))
        starting = make_view(repo)
        make_wave_plan(briefs, verify, ["backbone-1", "backbone-2", "security-1-a"])
        (verify / "verdicts-backbone-2.json").write_text("{}", encoding="utf-8")
        partway = make_view(repo)
        for voter in ("backbone-1", "security-1-a"):
            (verify / f"verdicts-{voter}.json").write_text("{}", encoding="utf-8")
        assert append(repo, "wave", make_wave_event("added-1", briefs / "none-yet" / PLAN_FILE))
        landed = make_view(repo)
    assert starting[1] == "wave wave-1: runner starting, no plan yet", starting
    assert not starting[2].startswith("wave "), "one line per runner id"
    assert partway[1] == (f"wave wave-1: 1 of 3 verdict files so far · plan {plan} · "
                          f"{RUNNER_OUT}"), partway
    assert landed[1:3] == ["wave wave-1: all 3 verdict files in",
                           "wave added-1: runner starting, no plan yet"], landed
    assert landed[0].startswith("BUILD STATE — ") and landed[3].startswith("method: "), landed


def test_a_wave_plan_that_cannot_be_read_still_says_the_runner_is_out() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        plan = Path(td).resolve() / "briefs" / PLAN_FILE
        plan.parent.mkdir()
        plan.write_text("{not json", encoding="utf-8")
        assert append(repo, "wave", make_wave_event("wave-1", plan))
        view = make_view(repo)
    assert view[1].startswith(f"wave wave-1: wave plan {plan} is not JSON"), view[1]
    assert view[1].endswith(f" · {RUNNER_OUT}"), view[1]


def make_wave_out(td: str, voters: list[str], landed: list[str]) -> tuple[Path, Path]:
    """A repo whose state has one runner, `wave-1`, filled with a plan of `voters`, and a verdicts
    file for each of `landed`: (the repo, the plan)."""
    repo = make_state(td)
    verify = repo / ".coyomap" / "verify"
    verify.mkdir()
    plan = make_wave_plan(Path(td).resolve() / "briefs-w1", verify, voters)
    for voter in landed:
        (verify / f"verdicts-{voter}.json").write_text("{}", encoding="utf-8")
    assert append(repo, "wave", make_wave_event("wave-1", plan))
    return repo, plan


def test_a_wave_handed_back_done_says_so() -> None:
    """The runner writes how its wave ended just before its report, and from then on its line
    says that rather than counting files."""
    with tempfile.TemporaryDirectory() as td:
        repo, _plan = make_wave_out(td, ["backbone-1", "security-1-a"],
                                    ["backbone-1", "security-1-a"])
        code, out, err = run_state(["add", "wave", "wave-1", "done", "--repo", str(repo)])
        view = make_view(repo)
        state = read_state(repo)
    assert code == 0 and out.startswith("BUILD STATE — wave written to "), (out, err)
    assert view[1] == "wave wave-1: handed back DONE", view
    assert state is not None and state.of("wave")[-1].text == "wave-1 DONE"


def test_a_wave_handed_back_incomplete_names_the_voters_the_lead_resends() -> None:
    """A runner left with a FAILED id hands its wave back INCOMPLETE, and the lead re-sends those
    voters itself. The line kept saying "do not start its voters yourself" until every verdict file
    was in, which a FAILED voter's never is. Another runner keeps its own line, and a runner filled
    again after its end is out again: the LAST wave event of each id decides."""
    with tempfile.TemporaryDirectory() as td:
        repo, plan = make_wave_out(td, ["backbone-1", "backbone-2", "security-1-a"],
                                   ["backbone-1"])
        assert append(repo, "wave", make_wave_event("added-1", plan.parent / "none" / PLAN_FILE))
        out = make_view(repo)
        code, _out, err = run_state(["add", "wave", "wave-1 INCOMPLETE backbone-2, security-1-a",
                                     "--repo", str(repo)])
        handed = make_view(repo)
        written = make_log_lines(repo)[-1]
        assert append(repo, "wave", make_wave_event("wave-1", plan))
        refilled = make_view(repo)
    out_line = f"wave wave-1: 1 of 3 verdict files so far · plan {plan} · {RUNNER_OUT}"
    assert out[1] == out_line, out
    assert code == 0, err
    assert handed[1:3] == ["wave wave-1: handed back INCOMPLETE · re-send its FAILED voters "
                           "yourself: backbone-2, security-1-a",
                           "wave added-1: runner starting, no plan yet"], handed
    assert written.endswith(" wave     wave-1 INCOMPLETE backbone-2 security-1-a"), written
    assert refilled[1] == out_line, refilled


def test_add_refuses_a_wave_line_that_says_no_end() -> None:
    """A wave line is written for `show` to read back, so `state add` takes only the two ends a
    runner hands back, and an INCOMPLETE one only with the ids the lead is to re-send."""
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        before = state_path(repo).read_bytes()
        said = [run_state(["add", "wave", text, "--repo", str(repo)])
                for text in ("wave-1 finished", "wave-1 INCOMPLETE", "wave-1 DONE backbone-2",
                             "wave-1 · pool 8 · prefix '' · plan /abs/briefs/wave-plan.json",
                             "   ")]
        after = state_path(repo).read_bytes()
    assert [code for code, _out, _err in said] == [2] * 5, said
    assert all("ERROR: " in err and "  add decision|next|wave" in err for _c, _o, err in said), said
    assert "names its FAILED ids" in said[1][2], said[1][2]
    assert '"wave-1 INCOMPLETE backbone-2" if those ids FAILED' in said[2][2], said[2][2]
    assert after == before, "a refused add writes nothing"


def test_every_phase_anchor_is_found_once_in_method_md() -> None:
    text = (REPO_ROOT / "method.md").read_text(encoding="utf-8")
    bad = [f"{p.name}: {anchor!r} found {text.count(anchor)} time(s)"
           for p in PHASES for anchor in (p.start, p.end) if text.count(anchor) != 1]
    assert not bad, "a phase anchor must name one place in method.md:\n  " + "\n  ".join(bad)
    found = sections(text)
    assert list(found) == [p.name for p in PHASES], sorted(set(p.name for p in PHASES) - set(found))
    spans = [(found[p.name].first, found[p.name].last) for p in PHASES]
    assert all(first <= last for first, last in spans), spans
    assert all(a[1] < b[0] for a, b in zip(spans, spans[1:])), "the sections run in method order"


def test_add_refuses_an_unknown_kind_and_an_empty_text() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        before = state_path(repo).read_bytes()
        unknown = run_state(["add", "rule", "a rule", "--repo", str(repo)])
        tool_kind = run_state(["add", "start", "a second start", "--repo", str(repo)])
        empty = run_state(["add", "decision", "   ", "--repo", str(repo)])
        after = state_path(repo).read_bytes()
    assert unknown[0] == 2 and "'rule'" in unknown[2], unknown
    assert tool_kind[0] == 2, tool_kind
    assert empty[0] == 2 and "empty" in empty[2], empty
    assert after == before, "a refused add writes nothing"


def test_show_without_a_state_says_so() -> None:
    """The folder may be the wrong one, since `--repo` defaults to the current folder: every
    message asks that first, and only then says to start a state there."""
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td).resolve()
        shown = run_state(["show", "--repo", str(repo)])
        phase = run_state(["phase", "harvest", "--repo", str(repo)])
        added = run_state(["add", "decision", "a rule", "--repo", str(repo)])
        created = (repo / ".coyomap").exists()
    asks = (f"NO BUILD STATE in {repo}: if this is not the repo you are mapping, pass --repo <that "
            f"repo>; if it is, ")
    assert shown[0] == 0 and shown[1].startswith(asks), shown
    assert "method/dispatch.md" in shown[1], shown[1]
    assert shown[1].rstrip().endswith(f"run coyomap state start --repo {repo}"), shown[1]
    for code, _out, err in (phase, added):
        assert code == 1 and err == f"{asks}run coyomap state start --repo {repo}\n", err
    assert not created, "nothing is written without a state"


# ── the CLI around it ────────────────────────────────────────────────────────────────────────────

def test_the_phases_flag_lists_every_phase_with_its_lines() -> None:
    code, out, _err = run_state(["--phases"])
    assert code == 0
    for p in PHASES:
        assert re.search(rf"^  {p.name} +lines \d+-\d+$", out, re.M), (p.name, out)


def test_an_omitted_repo_is_refused_inside_the_coyomap_clone() -> None:
    """A lead's shell drifts into the clone; a state opened there would sit beside no map."""
    try:
        buildstate.resolve_repo(None, cwd=REPO_ROOT / "tools", clone=REPO_ROOT)
    except ValueError as exc:
        assert "--repo" in str(exc)
    else:
        raise AssertionError("an omitted --repo inside the clone was accepted")
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        assert buildstate.resolve_repo(None, cwd=repo, clone=REPO_ROOT) == repo.resolve()
        assert buildstate.resolve_repo(str(repo), cwd=REPO_ROOT, clone=REPO_ROOT) == repo.resolve()


def test_repo_of_names_the_repo_of_a_coyomap_path() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td).resolve()
        frag = repo / ".coyomap" / "build-fragments" / "x.json"
        assert buildstate.repo_of(None, str(frag)) == repo
        assert buildstate.repo_of(frag) == repo
        assert buildstate.repo_of(repo / "src" / "a.py") is None
        assert buildstate.repo_of() is None


def test_a_bad_argument_is_answered_with_the_verbs_own_usage() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        code, out, err = run_state(["start", "--repo", str(repo), "--bogus"])
        missing = run_state(["phase", "--repo", str(repo)])
    assert code == 2 and not out, (out, err)
    assert err.startswith("ERROR: unrecognized arguments: --bogus\n"), err
    assert "  start   Open the state" in err and "  show    Print" not in err, err
    assert missing[0] == 2 and "required: name" in missing[2] and "  phase <name>" in missing[2]
    assert not (repo / ".coyomap").exists(), "a refused start wrote something"


def test_an_unknown_kind_from_a_tool_is_a_note_not_a_line() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            written = append(repo, "recrod", "a typo in a tool")
        lines = make_log_lines(repo)
    assert written is False and "unknown kind 'recrod'" in err.getvalue()
    assert len(lines) == 3



def test_a_read_after_the_build_closed_writes_no_line() -> None:
    """Retro 2026-10-08 #8: after `ship` wrote `end`, a `findings collect` and the retrospective's
    `grounding lint` runs added 8 lines to the log the build had already committed. A read changes
    no map, so once the build has closed it leaves the log alone; a fix after the end opens it
    again and is logged as before."""
    with tempfile.TemporaryDirectory() as td:
        repo = make_state(td)
        assert append(repo, "barrier", "VERDICTS OK — 3 file(s)"), "an open build logs its reads"
        assert append(repo, "end", "ship complete")
        before = make_log_lines(repo)
        assert append(repo, "barrier", "VERDICTS OK — 3 file(s)") is False
        assert append(repo, "findings", "FINDINGS — 2 from 2 agent(s)") is False
        assert append(repo, "next", "commit"), "the lead's own notes still go in"
        assert make_log_lines(repo)[:-1] == before
        # A record after the end opens the build again, and its reads are logged.
        assert append(repo, "record", "+1 under \"Walk jumps\"")
        assert append(repo, "barrier", "VERDICTS OK — 3 file(s)")
        # `phase commit` closes it as `end` does.
        assert append(repo, "phase", "commit")
        assert append(repo, "findings", "FINDINGS — 2 from 2 agent(s)") is False
        assert append(repo, "phase", "verify")
        assert append(repo, "barrier", "VERDICTS OK — 3 file(s)")


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all build-state tests passed")
