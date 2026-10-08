"""`coyomap state` — the build's short memory, in one file the tools write as they run.

**Why this exists.** A long build can outgrow the lead's context, and what replaces the context is a
summary that keeps the gist and drops the flags. On one live build the lead's context reached
966,568 tokens before the closing sequence and was replaced by a summary. The summary was a good
one: it kept the operator's rules and the pending steps. It dropped the `--map` of `record`, so the
first record after it went into the wrong file, and the closing report then said it existed.

So the build's memory lives outside the lead. Each tool appends one line per event to
`<repo>/.coyomap/build-state.log`: each record with its command, each brief and budget, each
barrier, assemble and finalize result, the phase, the next step, the operator's decisions, and how
each wave runner's wave ended. `coyomap state show` prints a short view of it, and that view is what
a lead reads after a summary.

**What a write promises.**
  * ONE `os.write` per event, to a file opened `O_WRONLY|O_APPEND` and never `O_CREAT`. Tools that
    run at once lose no line, and with no state nothing is written: only `state start` creates it.
  * A write never fails its tool: `append` never raises, because the tool's work is already done.
    A write that fails prints one stderr line, and the tool goes on. A character that is not UTF-8
    (an argument the shell could not decode) is written as its backslash escape.
  * Every line goes through `credentials.redact`. A line is clipped to `LINE_CAP` characters, but a
    line that carries a command (`WHOLE_KINDS`) is kept whole: a clipped command cannot be run.
  * The file is never rewritten. It has no size bound; the view `show` prints has one.
  * Once the build has closed (`end`, or `finalize` in the commit phase), a read writes no line
    (`QUIET_AFTER_END`): a check run after the commit, or by a retrospective, leaves the committed
    log as it was.

Stdlib-only (the cli.py firewall). It imports provenance, reporting, credentials, home, waveplan,
subverb_help, subverb_args and uncommitted (which names its two files), none of which imports it
back, so every tool that writes an event can import it.
"""
from __future__ import annotations

import contextlib
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from coyomap import subverb_help
from coyomap.credentials import redact
from coyomap.home import home
from coyomap.provenance import COYOMAP_SUBDIR, now_minute, pin_sha, tool_commit_here
from coyomap.reporting import item_lines, shown
from coyomap.subverb_args import ArgError, SubverbParser, subverb_parser
from coyomap.uncommitted import FINDINGS_FOLDER, PREV_NAME, STATE_NAME
from coyomap.waveplan import load_plan

#: Where `coyomap findings add` files each agent's findings, named in the `start` line.
FINDINGS_DIR = f"{COYOMAP_SUBDIR}/{FINDINGS_FOLDER}/"

#: The longest line the file holds, but for the `WHOLE_KINDS` lines. A full build writes about 150
#: lines.
LINE_CAP = 1000
#: The kinds whose line carries a command the lead runs again, kept WHOLE past `LINE_CAP`. A clipped
#: command cannot be run: at the first cap, 300 characters, a stopped `ship`'s re-run line at the
#: paths of a real build (an 87-character worktree repo, a 177-character note file) lost the end of
#: its note path and its `--partial`. A `record` line stays short on its own: it keeps the first 40
#: characters of each line it recorded, because the fragment holds the text.
WHOLE_KINDS: tuple[str, ...] = ("next", "ship", "assemble", "record")
KIND_WIDTH = 8

#: Every kind of event, and so every word `append` accepts. A kind outside this list is a typo in a
#: tool, which `show` would never find; it is refused with a note rather than written.
KINDS: tuple[str, ...] = (
    "start", "phase", "decision", "next", "budget", "record", "assemble", "brief", "wave",
    "barrier", "grounding", "timings", "findings", "finalize", "ship", "end",
)
#: The kinds `state add` writes: the lead's own two, and how a wave runner's wave ended, which the
#: runner writes just before its report. The tools write the rest.
ADD_KINDS: tuple[str, ...] = ("decision", "next", "wave")

#: The kinds a READ writes: a check of files already there (`grounding lint`) and a count of the
#: agents' findings (`findings collect`). Neither changes the map, so neither belongs in the log of a
#: build that has closed. On the 2026-10-08 mcpolis build they added 8 lines after the build's own
#: commit: 2 from the build itself and 6 from the retrospective that read it.
QUIET_AFTER_END: tuple[str, ...] = ("barrier", "findings")
#: The kinds that neither close a build nor open it again: the lead's own notes, and the reads above.
_NEITHER: tuple[str, ...] = ("decision", "next", "timings", *QUIET_AFTER_END)

HEADER = ("# coyomap build state: one line per event, oldest first, written by the coyomap tools.\n"
          "# Never edit it by hand. Read it with `coyomap state show --repo <repo>`.\n")


@dataclass(frozen=True)
class Phase:
    """One phase of a build, and where its section of method.md runs."""

    name: str
    start: str   # the words its section opens with: found exactly once in method.md
    end: str     # the words the section stops before: the next anchor in method order


#: The 12 phases of a build, in method order. `state show` names the method.md lines of the current
#: one; `tests/test_buildstate.py` checks that every anchor is found once in method.md.
PHASES: tuple[Phase, ...] = (
    Phase("behavioral", "## Behavioral layer — lead with this", "## Structural layer"),
    Phase("preindex", "**Pre-index (structural input).**", "**Parallel mode covers HARVESTING ONLY"),
    Phase("harvest", "- Phase 1 Harvest (fan out", "- Phase 2 Synthesize (barrier"),
    Phase("synthesis", "- Phase 2 Synthesize (barrier", "- Phase 3 Trace (fan out"),
    Phase("trace", "- Phase 3 Trace (fan out", "### After the trace — EVERY build"),
    Phase("rebalance", "- Phase 3.5 Re-balance reconcile", "- **Description review** (lead"),
    Phase("description", "- **Description review** (lead", "- **T7 Business logic (fan out"),
    Phase("rules", "- **T7 Business logic (fan out", "- Test completeness (one agent"),
    Phase("tests", "- Test completeness (one agent", "- Phase 4 Adversarial verify"),
    Phase("verify", "- Phase 4 Adversarial verify", "- **Ordering — ONE sequence"),
    Phase("closing", "- **Ordering — ONE sequence", "- **Where each reconcile lives"),
    Phase("commit", "**Run `coyomap finalize` as the pre-commit read.**", "**Maintaining the map.**"),
)
PHASE_NAMES: tuple[str, ...] = tuple(p.name for p in PHASES)

#: How many records `show` lists, newest first.
SHOWN_RECORDS = 8
#: The "last …" lines of `show`, in the order it prints them.
LAST_KINDS: tuple[str, ...] = ("assemble", "finalize", "barrier", "grounding", "ship")
CLOSING_LINE = "Before you run a coyomap command again, read its --help."

_EVENT = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) (\S+)(?: +(.*))?$")
_BUDGET = re.compile(r"\bbudget (\d+)\b")


# ── writing ──────────────────────────────────────────────────────────────────────────────────────

def state_path(repo: Path) -> Path:
    return repo / COYOMAP_SUBDIR / STATE_NAME


def repo_of(*paths: str | Path | None) -> Path | None:
    """The repo a `<repo>/.coyomap/...` path belongs to — the first of `paths` that names one.

    Every input the build's tools take lives under `.coyomap/`: the map, the fragments, the pinned
    worklist, the verdict files. So the project is knowable from an argument, and never has to be
    guessed from the working directory, which is a different project whenever a coyomap clone is
    driving the build. None when no argument names one; the caller then falls back as it chooses."""
    for path in paths:
        if not path:
            continue
        parts = Path(path).resolve().parts
        if COYOMAP_SUBDIR in parts:
            return Path(*parts[:parts.index(COYOMAP_SUBDIR)])
    return None


def event_line(kind: str, text: str, at: str | None = None) -> str:
    """One event as the file holds it: `YYYY-MM-DD HH:MM <kind> <text>`, on ONE line, redacted,
    and clipped to `LINE_CAP` characters with `…` unless its kind is one of `WHOLE_KINDS`."""
    line = f"{at or now_minute()} {kind:<{KIND_WIDTH}} {redact(' '.join(text.split()))}".rstrip()
    if len(line) > LINE_CAP and kind not in WHOLE_KINDS:
        line = line[:LINE_CAP - 1].rstrip() + "…"
    return line + "\n"


def _encode(text: str) -> bytes:
    """`text` as the file's bytes. A character UTF-8 cannot hold (a lone surrogate, from an argument
    the shell could not decode: `caf\\udce9.py`) is written as its backslash escape, so the line is
    still written and still one line."""
    return text.encode("utf-8", errors="backslashreplace")


def _note(why: object) -> None:
    print(f"note: build state not written ({why})", file=sys.stderr)


def _why(exc: Exception) -> str:
    if isinstance(exc, OSError) and exc.strerror and exc.filename:
        return f"{exc.strerror}: {exc.filename}"
    return str(exc)


def append(repo: Path | None, kind: str, text: str) -> bool:
    """Write one event to the open build state of `repo`. True when the line was written.

    Nothing is written, and nothing is said, when there is no state: no `state start` ran, or the
    tool runs outside a build. Any other failure prints ONE stderr line and returns False. It never
    raises: the tool that calls it has done its work, and a line it could not log must not fail it.
    An `OSError` is a file that cannot be opened or written, and a `ValueError` a path holding a NUL
    character."""
    if repo is None:
        return False
    if kind not in KINDS:
        _note(f"unknown kind {kind!r}")
        return False
    if kind in QUIET_AFTER_END and _closed(repo):
        return False
    data = _encode(event_line(kind, text))
    try:
        fd = os.open(state_path(repo), os.O_WRONLY | os.O_APPEND)
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as exc:
        _note(_why(exc))
        return False
    try:
        written = os.write(fd, data)
    except (OSError, ValueError) as exc:
        _note(_why(exc))
        return False
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
    if written != len(data):
        _note(f"only {written} of {len(data)} bytes written")
        return False
    return True


def _closed(repo: Path) -> bool:
    """Has the build closed: is its last event that is not a note or a read the `end` that `ship`
    writes, or a `finalize` or `ship` line written in the commit phase? A `phase commit` line alone
    does not close it: the method starts that phase BEFORE `finalize`, and the pre-commit read's
    barrier and findings lines belong in the log. A `record`, an `assemble`, another phase, or a
    fresh `start` opens it again, so a fix after the end is logged as before. A state that cannot be
    read counts as open: a lost line is worse than a stray one."""
    try:
        state = read_state(repo)
    except OSError:
        return False
    last = next((e for e in reversed(state.events) if e.kind not in _NEITHER), None) if state else None
    if last is None:
        return False
    return last.kind == "end" or (last.kind in ("finalize", "ship") and last.phase == "commit")


# ── reading ──────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Event:
    """One line of the file."""

    at: str      # "YYYY-MM-DD HH:MM"
    kind: str
    text: str
    phase: str   # the build phase that was current when it was written; "" before the first


@dataclass(frozen=True)
class State:
    """The events of a state file from its last `start` on."""

    path: Path
    events: tuple[Event, ...]
    unreadable: int   # lines that are neither a header nor an event

    def of(self, kind: str) -> list[Event]:
        return [e for e in self.events if e.kind == kind]

    def last(self, kind: str) -> Event | None:
        found = self.of(kind)
        return found[-1] if found else None

    @property
    def started(self) -> Event | None:
        return self.events[0] if self.events and self.events[0].kind == "start" else None

    @property
    def ended(self) -> Event | None:
        return self.last("end")

    @property
    def is_open(self) -> bool:
        """A start with no later end."""
        return self.started is not None and self.ended is None

    @property
    def phase(self) -> Event | None:
        return self.last("phase")


def parse_state(path: Path, text: str) -> State:
    """The events of `text` from its last `start` on, each with the phase it was written in."""
    rows: list[tuple[str, str, str]] = []
    unreadable = 0
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        m = _EVENT.match(line)
        if not m:
            unreadable += 1
            continue
        rows.append((m.group(1), m.group(2), m.group(3) or ""))
    starts = [i for i, (_at, kind, _text) in enumerate(rows) if kind == "start"]
    rows = rows[starts[-1]:] if starts else []
    events: list[Event] = []
    phase = ""
    for at, kind, body in rows:
        if kind == "phase":
            phase = body.split()[0] if body.split() else ""
        events.append(Event(at=at, kind=kind, text=body, phase=phase))
    return State(path=path, events=tuple(events), unreadable=unreadable)


def read_state(repo: Path) -> State | None:
    """The state of `repo`, or None when it has none. Raises `OSError` when the file is there and
    cannot be read."""
    path = state_path(repo)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    return parse_state(path, text)


# ── the method sections ──────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Section:
    """The method.md lines of one phase, first to last, 1-based."""

    first: int
    last: int


def sections(method_text: str) -> dict[str, Section]:
    """The lines of every phase whose start and end anchors are each found once, in that order."""
    out: dict[str, Section] = {}
    for p in PHASES:
        if method_text.count(p.start) != 1 or method_text.count(p.end) != 1:
            continue
        a, b = method_text.index(p.start), method_text.index(p.end)
        if b <= a:
            continue
        out[p.name] = Section(first=method_text.count("\n", 0, a) + 1,
                              last=method_text.count("\n", 0, b))
    return out


def _method_text(method_md: Path) -> str:
    try:
        return method_md.read_text(encoding="utf-8")
    except OSError:
        return ""


# ── the view ─────────────────────────────────────────────────────────────────────────────────────

def no_state_message(repo: Path, clone: Path | None = None) -> str:
    """What `phase` and `add` print when `repo` has no build state, and, given the clone, what
    `show` prints. It asks first whether `repo` is the repo being mapped: `--repo` defaults to the
    current folder, a lead's shell drifts, and a state started in the wrong folder would get no line
    from any tool, since each writes into the repo its own paths name. `show` is what a lead runs
    after a summary, so it also names the dispatch file to re-read."""
    then = (f"re-read {clone / 'method' / 'dispatch.md'}: once the mode is Build and any old map "
            f"is archived, run coyomap state start --repo {repo}" if clone is not None
            else f"run coyomap state start --repo {repo}")
    return (f"NO BUILD STATE in {repo}: if this is not the repo you are mapping, pass --repo <that "
            f"repo>; if it is, {then}")


def _item(e: Event) -> str:
    return f"{e.at} {e.text}"


def _phase_word(e: Event) -> str:
    return e.phase or "before any phase"


#: What a wave line tells the lead while that wave's runner works. The runner starts every voter in
#: its plan, so a voter the lead starts too runs twice, and the later verdicts file replaces the
#: first.
RUNNER_OUT = "a runner is out: do not start its voters yourself"

#: How a wave ends, in the word its runner's report opens with (`WAVE <id> DONE|INCOMPLETE`).
WAVE_DONE = "DONE"
WAVE_INCOMPLETE = "INCOMPLETE"
#: The line the runner writes just before that report, with `state add wave`.
WAVE_END_FORMS = f'"<runner id> {WAVE_DONE}", or "<runner id> {WAVE_INCOMPLETE} <its FAILED ids>"'


@dataclass(frozen=True)
class WaveEnd:
    """How a wave runner's wave ended, as the runner wrote it."""

    runner: str
    outcome: str               # WAVE_DONE or WAVE_INCOMPLETE
    failed: tuple[str, ...]    # the FAILED ids an INCOMPLETE wave names; none for a DONE one

    @property
    def text(self) -> str:
        """The event text: `<runner id> DONE`, or `<runner id> INCOMPLETE <id> <id> …`."""
        return " ".join([self.runner, self.outcome, *self.failed])


def _wave_words(text: str) -> list[str]:
    return text.replace(",", " ").split()


def wave_end_fault(text: str) -> str | None:
    """Why `text` says no way a wave ended, or None when it says one: `<runner id> DONE`, or
    `<runner id> INCOMPLETE <its FAILED ids>`. The ids may be split by spaces or commas, and the word
    may be written in any case. A fill's text (`<runner id> · pool …`) says none."""
    words = _wave_words(text)
    if len(words) < 2 or words[1].upper() not in (WAVE_DONE, WAVE_INCOMPLETE):
        return f"a wave line says how a runner's wave ended: {WAVE_END_FORMS}, not {text!r}"
    runner, outcome, failed = words[0], words[1].upper(), words[2:]
    if outcome == WAVE_DONE and failed:
        return (f"a {WAVE_DONE} wave has no FAILED id: write \"{runner} {WAVE_DONE}\", or "
                f"\"{runner} {WAVE_INCOMPLETE} {' '.join(failed)}\" if those ids FAILED")
    if outcome == WAVE_INCOMPLETE and not failed:
        return (f"an {WAVE_INCOMPLETE} wave names its FAILED ids, the ones the lead re-sends: "
                f"\"{runner} {WAVE_INCOMPLETE} <its FAILED ids>\"")
    return None


def parse_wave_end(text: str) -> WaveEnd | None:
    """How a wave ended, from a `wave` event's text; None for a fill's text, or one that says no end
    (`wave_end_fault`)."""
    if wave_end_fault(text) is not None:
        return None
    words = _wave_words(text)
    return WaveEnd(runner=words[0], outcome=words[1].upper(), failed=tuple(words[2:]))


@dataclass(frozen=True)
class WaveRun:
    """A wave runner, as its LAST `wave` event names it."""

    id: str
    plan: Path | None       # the plan its last fill names; None when it names none
    end: WaveEnd | None     # how its wave ended, when its last event says so


def wave_runs(state: State, repo: Path) -> list[WaveRun]:
    """Each runner from the last `wave` event under its id, in the order the runners were first
    filled: a runner filled again (`--force`) is one runner. A fill reads
    `<runner id> · pool <N> · prefix <p> · plan <path>` (`contract wave --fill`); the line the
    runner writes just before its report reads `<runner id> DONE`, or `<runner id> INCOMPLETE
    <its FAILED ids>` (`state add wave`)."""
    runs: dict[str, WaveRun] = {}
    for e in state.of("wave"):
        end = parse_wave_end(e.text)
        if end is not None:
            known = runs.get(end.runner)
            runs[end.runner] = WaveRun(id=end.runner, plan=known.plan if known else None, end=end)
            continue
        parts = e.text.split(" · ")
        runner = parts[0].strip()
        if not runner:
            continue
        named = next((p[len("plan "):].strip() for p in reversed(parts) if p.startswith("plan ")),
                     "")
        plan = (Path(named) if Path(named).is_absolute() else repo / named) if named else None
        runs[runner] = WaveRun(id=runner, plan=plan, end=None)
    return list(runs.values())


def wave_line(run: WaveRun) -> str:
    """One runner's line in `show`, counted NOW from the voters its plan names. The view is what a
    lead reads after a summary, and a summary drops which waves are still out: a lead that then
    starts a wave's voters itself runs each of them twice.

    Once the runner has written how its wave ended, the line says that instead. A runner that hands
    back INCOMPLETE leaves its FAILED voters to the lead, and a line still saying "a runner is out"
    told a lead back from a summary not to start the very voters it had to re-send."""
    if run.end is not None:
        if run.end.outcome == WAVE_DONE:
            return f"wave {run.id}: handed back {WAVE_DONE}"
        return (f"wave {run.id}: handed back {WAVE_INCOMPLETE} · re-send its FAILED voters "
                f"yourself: {', '.join(run.end.failed)}")
    if run.plan is None or not run.plan.is_file():
        return f"wave {run.id}: runner starting, no plan yet"
    try:
        plan = load_plan(run.plan)
    except ValueError as exc:
        why = (str(exc).splitlines() or [f"its plan {run.plan} cannot be read"])[0].rstrip(":")
        return f"wave {run.id}: {why} · {RUNNER_OUT}"
    voters = len(plan.agents)
    landed = sum(1 for a in plan.agents if a.verdicts.is_file())
    if landed == voters:
        return f"wave {run.id}: all {voters} verdict files in"
    return (f"wave {run.id}: {landed} of {voters} verdict files so far · plan {run.plan} · "
            f"{RUNNER_OUT}")


def show_lines(state: State, repo: Path, clone: Path) -> list[str]:
    """The view a lead reads after a summary: at most 40 lines, a build's two waves included, plus
    one per decision past 10. `clone` is the coyomap clone whose method.md the method lines point
    into."""
    method_md = clone / "method.md"
    started = state.started
    phase = state.phase
    decisions = state.of("decision")
    records = state.of("record")
    if state.ended is not None:
        since = f"ended {state.ended.at} (opened {started.at if started else 'never'})"
    else:
        since = f"open since {started.at if started else 'never'}"
    where = f"phase {phase.text} ({phase.at})" if phase else "no phase started yet"
    lines = [f"BUILD STATE — {since} · {where} · {len(state.events)} events: "
             f"{len(decisions)} decisions, {len(records)} records"]
    # RIGHT AFTER THE VERDICT LINE: a wave out is the one thing the lead must not act on itself.
    lines += [wave_line(run) for run in wave_runs(state, repo)]

    if phase is None:
        lines.append(f"method: re-read {clone / 'method' / 'dispatch.md'}, then start "
                     f"the first phase with coyomap state phase <name> --repo {repo} "
                     f"(coyomap state --phases lists them)")
    else:
        section = sections(_method_text(method_md)).get(phase.text)
        if section is None:
            lines.append(f"method: re-read {method_md} for phase {phase.text}: its section was "
                         f"not found (coyomap state --phases)")
        else:
            lines.append(f"method: re-read {method_md} lines {section.first}-{section.last} "
                         f"({phase.text})")
    nxt = state.last("next")
    lines.append(f"next: {nxt.text} (written {nxt.at}, in phase {nxt.phase or 'none'})" if nxt
                 else "next: none written")

    for kind in LAST_KINDS:
        e = state.last(kind)
        if e is not None:
            lines.append(f"last {kind}: {_item(e)}")

    if decisions:
        lines.append(f"decisions ({len(decisions)}), oldest first:")
        lines.append(item_lines([_item(e) for e in decisions], None))
    else:
        lines.append(f'decisions: none written. Write each operator decision or rule the moment it '
                     f'is given: coyomap state add decision "<…>" --repo {repo}')
    if records:
        lines.append(f"records ({len(records)}), newest first:")
        lines.append(item_lines([_item(e) for e in reversed(records)], SHOWN_RECORDS,
                                unit=f"in {COYOMAP_SUBDIR}/{STATE_NAME}"))
    else:
        lines.append("records: none yet")

    briefs = state.of("brief")
    if briefs:
        per_phase: dict[str, int] = {}
        for e in briefs:
            per_phase[_phase_word(e)] = per_phase.get(_phase_word(e), 0) + 1
        lines.append("briefs, by the phase they were filled in: "
                     + shown([f"{p} {n}" for p, n in per_phase.items()], len(PHASES), sep=" · "))
    sums = [int(m.group(1)) for e in briefs for m in _BUDGET.finditer(e.text)]
    budget = state.last("budget")
    if sums or budget:
        parts = [f"harvest briefs {sum(sums)}" if sums else "no harvest brief budget yet",
                 f"preindex {budget.text}" if budget else "no preindex E yet"]
        lines.append("budget: " + " · ".join(parts))
    findings = state.last("findings")
    if findings is not None:
        lines.append(f"findings: {_item(findings)}")
    timed = sorted({_phase_word(e) for e in state.of("timings")},
                   key=lambda p: PHASE_NAMES.index(p) if p in PHASE_NAMES else len(PHASES))
    if timed:
        lines.append("timings: recorded in " + shown(timed, len(PHASES)))
    if state.unreadable:
        lines.append(f"note: {state.unreadable} line(s) of {state.path} are not events; only the "
                     f"tools write this file")
    lines.append(CLOSING_LINE)
    return lines


# ── start ────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Started:
    path: Path
    line: str
    moved: Path | None      # where the state before it went, when there was one
    moved_open: bool        # that state was still open (`--new`)


def start_text(repo: Path) -> str:
    return (f"build · pin {pin_sha(repo) or 'none (no git)'} · coyomap "
            f"{tool_commit_here() or 'unknown'} · findings {FINDINGS_DIR}")


def open_refusal(state: State, repo: Path) -> str:
    started = state.started
    last = state.events[-1] if state.events else None
    return (f"a build state is already open in {state.path}: started "
            f"{started.at if started else '?'}, last event "
            f"{f'{last.at} {last.kind} {last.text}' if last else 'none'}. Continue it: coyomap state "
            f"show --repo {repo}. Or set it aside and open a new one: coyomap state start --new "
            f"--repo {repo} (the open state moves to {COYOMAP_SUBDIR}/{PREV_NAME}).")


def start(repo: Path, new: bool = False, at: str | None = None) -> Started:
    """Open a build state. An ENDED state moves to `build-state.prev.log`; an OPEN one is refused
    with `ValueError`, unless `new`, which moves it aside too. Raises `OSError` when the folder or
    the file cannot be written."""
    folder = repo / COYOMAP_SUBDIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / STATE_NAME
    moved: Path | None = None
    moved_open = False
    old = read_state(repo)
    if old is not None:
        if old.is_open and not new:
            raise ValueError(open_refusal(old, repo))
        moved, moved_open = folder / PREV_NAME, old.is_open
        os.replace(path, moved)
    line = event_line("start", start_text(repo), at)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    except FileExistsError as exc:
        raise ValueError(f"another `coyomap state start` opened {path} at the same moment; "
                         f"read it with coyomap state show --repo {repo}") from exc
    try:
        os.write(fd, _encode(HEADER + line))
    finally:
        os.close(fd)
    return Started(path=path, line=line.rstrip("\n"), moved=moved, moved_open=moved_open)


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────

USAGE = f"""usage: coyomap state start [--repo <repo>] [--new]
       coyomap state phase <name> [--repo <repo>]
       coyomap state add decision|next|wave "<text>" [--repo <repo>]
       coyomap state show [--repo <repo>]
       coyomap state --phases

The build's short memory: <repo>/.coyomap/{STATE_NAME}, one line per event, written by the coyomap
tools as they run: each record with its command, each brief and budget, each barrier, assemble and
finalize result, the phase, the next step, the operator's decisions, how each wave ended. A summary
of your context keeps the gist and drops the flags; this file keeps both. Never edit it by hand.

  start   Open the state, once the mode is Build and any old map is archived. An ENDED state (one
          `ship` completed) moves to .coyomap/{PREV_NAME}. An OPEN one is refused, naming
          its start and its last event; --new moves it aside too and opens a new one.
  phase <name>
          Write that a phase starts, then print the state. Run it before the phase's first step.
  add decision|next|wave "<text>"
          Write one line. A decision is an operator decision or rule, in the operator's words, the
          moment it is given. A next is the step you will take when a long wait ends. A wave is how
          a wave runner's wave ended, written by the runner just before its report:
          {WAVE_END_FORMS}.
  show    Print the state, in at most 40 lines (one more for each decision past 10): each wave
          runner that is out and how many of its verdict files are in, or how its wave ended once
          it says so, the method lines to re-read, the next step, the last assemble, finalize,
          barrier, grounding and ship lines, every decision, the last {SHOWN_RECORDS} records, the
          briefs, budget, findings and timings. After a summary, run it before anything else.
  --phases
          The {len(PHASES)} phase names and their method.md lines.

  --repo <repo>   the repo you are mapping (default: the current folder, refused inside the
                  coyomap clone, where the state would be filed in the wrong repo).

Without a state, `phase` and `add` exit 1 and `show` exits 0, each saying so."""

_VERBS = ("start", "phase", "add", "show")


def build_parser(verb: str) -> SubverbParser:
    p = subverb_parser(f"coyomap state {verb}")
    p.add_argument("--repo", default=None)
    if verb == "start":
        p.add_argument("--new", action="store_true")
    elif verb == "phase":
        p.add_argument("name")
    elif verb == "add":
        p.add_argument("kind")
        p.add_argument("text", nargs="+")
    return p


def resolve_repo(arg: str | None, cwd: Path | None = None, clone: Path | None = None) -> Path:
    """The repo the call is about. An explicit `--repo` always wins, when it is a folder. An omitted
    one is the current folder, refused inside the coyomap clone: a lead's shell drifts there, and a
    state started there would be filed in the clone while every tool writes into the mapped repo."""
    if arg is not None:
        path = Path(arg).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"--repo {arg} is not a folder")
        return path
    here = (cwd or Path.cwd()).resolve()
    clone = (clone or home()).resolve()
    if here == clone or clone in here.parents:
        raise ValueError(f"--repo is required here: the current folder is inside the coyomap clone "
                         f"({clone}). Pass --repo <the repo you are mapping> (--repo . maps the "
                         f"clone itself).")
    return here


def phases_lines(clone: Path) -> list[str]:
    method_md = clone / "method.md"
    found = sections(_method_text(method_md))
    width = max(len(n) for n in PHASE_NAMES)
    lines = [f"{len(PHASES)} build phases, in method order, with their lines in {method_md}. "
             f"Start each with coyomap state phase <name> --repo <repo>:"]
    for p in PHASES:
        s = found.get(p.name)
        lines.append(f"  {p.name:<{width}}  " + (f"lines {s.first}-{s.last}" if s
                                                 else "its section was not found"))
    return lines


def _print(lines: Sequence[str]) -> None:
    print("\n".join(line for line in lines if line))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in subverb_help.HELP_FLAGS:
        print(USAGE)
        return 0 if args else 2
    clone = home()
    if args[0] == "--phases":
        if len(args) > 1:
            return subverb_help.usage_error(USAGE, "--phases",
                                            f"--phases takes no argument (given: {' '.join(args[1:])})")
        _print(phases_lines(clone))
        return 0
    verb, rest = args[0], args[1:]
    if verb not in _VERBS:
        print(f"coyomap state: unknown verb '{verb}'\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        print(f"\nERROR: unknown verb '{verb}'", file=sys.stderr)
        return 2
    helped = subverb_help.handle(USAGE, verb, rest)
    if helped is not None:
        return helped
    try:
        parsed = build_parser(verb).parse_args(rest)
        repo = resolve_repo(parsed.repo, clone=clone)
    except (ArgError, ValueError) as exc:
        return subverb_help.usage_error(USAGE, verb, str(exc))
    if verb == "start":
        return _cmd_start(repo, bool(parsed.new))
    if verb == "add":
        kind, text = str(parsed.kind), " ".join(parsed.text).strip()
        if kind not in ADD_KINDS:
            return subverb_help.usage_error(USAGE, verb, f"state add writes a decision, a next or a "
                                                         f"wave, not {kind!r}")
        if kind == "wave":
            # Written as the view reads it back: one id, the word, the FAILED ids, all by spaces.
            end = parse_wave_end(text)
            if end is None:
                return subverb_help.usage_error(USAGE, verb, str(wave_end_fault(text)))
            text = end.text
        elif not text:
            return subverb_help.usage_error(USAGE, verb, f"the {kind} is empty: write it in the "
                                                         f"operator's words")
        return _cmd_add(repo, kind, text)
    if verb == "phase":
        name = str(parsed.name)
        if name not in PHASE_NAMES:
            return subverb_help.usage_error(USAGE, verb, f"unknown phase {name!r}; the phases are "
                                                         f"{', '.join(PHASE_NAMES)}")
        return _cmd_phase(repo, name, clone)
    return _cmd_show(repo, clone)


def _cmd_start(repo: Path, new: bool) -> int:
    try:
        started = start(repo, new=new)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: the build state was not started ({_why(exc)})", file=sys.stderr)
        return 1
    _print([f"BUILD STATE — started → {started.path}",
            f"  {started.line}",
            (f"  the {'open' if started.moved_open else 'ended'} state before it → {started.moved}"
             if started.moved else ""),
            f"Start each phase with coyomap state phase <name> --repo {repo} "
            f"(coyomap state --phases lists them)."])
    return 0


def _read(repo: Path) -> State | None:
    """The state, or None after saying why there is none to read."""
    try:
        return read_state(repo)
    except OSError as exc:
        print(f"ERROR: cannot read the build state ({_why(exc)})", file=sys.stderr)
        return None


def _cmd_add(repo: Path, kind: str, text: str) -> int:
    if not state_path(repo).is_file():
        print(no_state_message(repo), file=sys.stderr)
        return 1
    if not append(repo, kind, text):
        return 1
    print(f"BUILD STATE — {kind} written to {state_path(repo)}")
    return 0


def _cmd_phase(repo: Path, name: str, clone: Path) -> int:
    if not state_path(repo).is_file():
        print(no_state_message(repo), file=sys.stderr)
        return 1
    if not append(repo, "phase", name):
        return 1
    state = _read(repo)
    if state is None:
        return 1
    _print(show_lines(state, repo, clone))
    return 0


def _cmd_show(repo: Path, clone: Path) -> int:
    if not state_path(repo).exists():
        print(no_state_message(repo, clone))
        return 0
    state = _read(repo)
    if state is None:
        return 1
    _print(show_lines(state, repo, clone))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
