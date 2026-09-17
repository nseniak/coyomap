#!/usr/bin/env python3
"""`coyomap timings` — what each fan-out slice ACTUALLY took, so the next build orders from it.

**Why this exists.** The method tells the lead to dispatch the known-longest slice first, because
launch order is the only lever it has over when a barrier closes. Then it hands the lead folklore to
decide "longest" with: *T5 and the entry-points slice are the reliably heaviest*. That was true of
the builds somebody watched. Nothing wrote down the rest, so every build after them guessed again
from the same sentence.

A measured build got the order wrong three times in six fan-outs, and the straggler it dispatched
last held its barrier for its whole runtime — up to 7.7 minutes of pure delay, not work.

**What it does.** Two verbs and one file. At each barrier the lead records what the batch took;
at the next build's dispatch it asks for the order. That is the whole loop:

    coyomap timings record --phase harvest --slice "T5 model"     --minutes 12.4 \\
                           --slice "entry points" --minutes 9.1 \\
                           --slice "deps"         --minutes 3.2
    coyomap timings order  --phase harvest

`--slice` and `--minutes` REPEAT and pair by position — one process, one write, the same shape
`coyomap record --line` already has. A count mismatch is refused rather than paired off silently.

**It is a SECOND-build lever and says so.** On a project with no record, `order` prints one line
saying it has none and exits 0. A first build must not stall waiting for a measurement that cannot
exist yet, and an empty file must never read as "these slices take no time".

**What it deliberately does not do.** It does not time anything itself — the lead reads the elapsed
minutes off the barrier it just waited at, and no coyomap process is running while the helpers are.
It does not average across builds: the most RECENT recording for a slice wins, because slices are
re-cut between builds and an old shape is not evidence about a new one. And it never reorders a
dispatch on its own; it prints, the lead dispatches.

The file is `<repo>/.coyomap/fanout-timings.json`. It is build telemetry, not map content, so it
lives beside the map and never inside it — nothing in the map's schema, its views or its gates reads
it, and a wrong number here can make a build slower but can never make a map wrong.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from coyomap import subverb_help
from coyomap.provenance import agent_spans, session_agent_transcripts

#: The fan-out phases a build actually has. A typo'd phase would record fine and then be found by
#: nothing at `order` time, so an unknown one is refused with the list — the same choice
#: `coyomap record` makes for extras headings.
PHASES: tuple[str, ...] = (
    "harvest",
    "trace",
    "rules",
    "t7",
    "test-completeness",
    "skeptic",
    # The interfaces/doors fan-out. Missing until 2026-09-01, when the argus build ran four door
    # agents, tried to record them, and had all four slices refused by `_check_phase` — so the one
    # wave the build was told to measure is the one wave with no measurement.
    "doors",
    "gapfill",
)

#: Plural (and other obvious) spellings a build reaches for, mapped to the real phase name. A typo'd
#: phase is refused on purpose, but refusing `--phase skeptics` teaches nothing: on the 2026-09-01
#: argus build 19 `skeptics` records and 5 `doors` records were rejected outright. The alias is
#: accepted silently — the canonical name is what gets stored, so `order` and `show` stay keyed on
#: one spelling.
PHASE_ALIASES: dict[str, str] = {
    "skeptics": "skeptic",
    "door": "doors",
    "harvests": "harvest",
    "traces": "trace",
    "rule": "rules",
    "gap-fill": "gapfill",
    "test_completeness": "test-completeness",
}

#: How long the longest slice must hold the barrier ALONE before splitting it is worth saying.
#: Below this the advice costs more attention than the minutes it could recover.
_SPLIT_MIN_MINUTES = 2.0

#: Where the record lives, relative to the analyzed repo's root.
RECORD_PATH = ".coyomap/fanout-timings.json"

#: Bumped only if the on-disk shape changes. A file from a newer version is refused, not guessed at.
VERSION = 1


@dataclass(frozen=True)
class Run:
    """One slice of one fan-out, and the wall minutes it held the barrier for."""
    phase: str
    slice: str
    minutes: float
    items: int | None
    commit: str | None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"phase": self.phase, "slice": self.slice, "minutes": self.minutes}
        if self.items is not None:
            out["items"] = self.items
        if self.commit is not None:
            out["commit"] = self.commit
        return out


def record_path(repo: str) -> Path:
    return Path(repo) / RECORD_PATH


def load_runs(path: Path) -> list[Run]:
    """Read the record. A missing file is an empty record, not an error — the first build has none.

    A malformed or future-version file is an ERROR: silently starting over would throw away the
    measurements the next dispatch was going to be ordered by, and nothing would say so."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} is not readable JSON ({exc}). Fix or delete it; "
                         f"it will not be silently replaced.") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object, found {type(raw).__name__}.")
    version = raw.get("version")
    if version != VERSION:
        raise ValueError(f"{path}: version {version!r}, this coyomap writes version {VERSION}.")
    rows = raw.get("runs")
    if not isinstance(rows, list):
        raise ValueError(f"{path}: 'runs' must be a list.")
    runs: list[Run] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: runs[{i}] is not an object.")
        try:
            phase, name, minutes = row["phase"], row["slice"], row["minutes"]
        except KeyError as exc:
            raise ValueError(f"{path}: runs[{i}] is missing {exc}.") from exc
        if not isinstance(phase, str) or not isinstance(name, str):
            raise ValueError(f"{path}: runs[{i}] has a non-string 'phase' or 'slice'.")
        if not isinstance(minutes, (int, float)) or isinstance(minutes, bool):
            raise ValueError(f"{path}: runs[{i}]['minutes'] is not a number.")
        items = row.get("items")
        if items is not None and (not isinstance(items, int) or isinstance(items, bool)):
            raise ValueError(f"{path}: runs[{i}]['items'] is not an integer.")
        commit = row.get("commit")
        if commit is not None and not isinstance(commit, str):
            raise ValueError(f"{path}: runs[{i}]['commit'] is not a string.")
        runs.append(Run(phase, name, float(minutes), items, commit))
    return runs


def write_runs(path: Path, runs: list[Run]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"version": VERSION, "runs": [r.as_json() for r in runs]}
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def latest_by_slice(runs: list[Run], phase: str) -> list[Run]:
    """The most recent recording per slice name, longest-first.

    Most recent, not averaged: slices are re-cut between builds, so an old shape's minutes are not
    evidence about a new shape's. Ties keep the order they were recorded in, so the print is stable
    across two runs of the same command."""
    latest: dict[str, Run] = {}
    for run in runs:
        if run.phase == phase:
            latest[run.slice] = run
    return sorted(latest.values(), key=lambda r: -r.minutes)


def _pair_slices(slices: list[str], minutes: list[str]) -> list[tuple[str, float]]:
    """Pair the repeated `--slice`/`--minutes` by position, refusing anything ambiguous."""
    if len(slices) != len(minutes):
        raise ValueError(f"--slice was given {len(slices)} time(s) and --minutes {len(minutes)}; "
                         f"they pair by position, so the counts must match.")
    pairs: list[tuple[str, float]] = []
    seen: set[str] = set()
    for name, raw in zip(slices, minutes):
        name = name.strip()
        if not name:
            raise ValueError("a --slice name is empty.")
        if name in seen:
            raise ValueError(f"--slice {name!r} was given twice in one call; "
                             "record each slice once.")
        seen.add(name)
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"--minutes {raw!r} for slice {name!r} is not a number.") from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"--minutes {raw!r} for slice {name!r} must be a positive number "
                             "of wall minutes.")
        pairs.append((name, value))
    return pairs


#: The coyomap clone this tool is running from — `<COYOMAP_HOME>/tools/coyomap/timings.py`.
COYOMAP_HOME = Path(__file__).resolve().parents[2]


def _repo_of(args: argparse.Namespace) -> str:
    """The analyzed repo for this call, refusing the one mistake that cannot be seen afterwards.

    `timings` writes to `<repo>/.coyomap/fanout-timings.json` and the default repo is the current
    folder. A build runs the coyomap CLI by absolute path and its shell folder drifts, so an
    omitted `--repo` silently files the measurement in the CLONE instead of the mapped project —
    on the 2026-09-01 argus build, 9 harvest slices landed in the clone and were counted by nobody.
    Nothing downstream can detect it: both files are well-formed, and the loss looks exactly like a
    phase that was never measured.

    So: an OMITTED `--repo` while standing in the clone is refused. An EXPLICIT one is always
    honoured, which is what keeps coyomap mappable by itself (`--repo .` from the clone is a
    deliberate statement, `.` by default is not)."""
    if args.repo is not None:
        return str(args.repo)
    # ANYWHERE INSIDE the clone, not just its root. From `<clone>/tools` an omitted `--repo` filed
    # the measurement at `<clone>/tools/.coyomap/…`, which is the same loss one folder deeper.
    cwd = Path.cwd().resolve()
    if cwd == COYOMAP_HOME or COYOMAP_HOME in cwd.parents:
        raise ValueError(
            f"--repo is required here. The current folder is the coyomap clone "
            f"({COYOMAP_HOME}), and the default would file this measurement in the clone's own "
            f"{RECORD_PATH} instead of the mapped project's. Pass `--repo <the mapped repo>` — or "
            f"`--repo .` if you really are measuring a build OF coyomap.")
    return "."


def _check_phase(phase: str) -> str:
    canonical = PHASE_ALIASES.get(phase, phase)
    if canonical not in PHASES:
        raise ValueError(f"unknown phase {phase!r}. The fan-out phases are: "
                         + ", ".join(PHASES) + ".")
    return canonical


@dataclass(frozen=True)
class ParsedLines:
    """`--lines-from` parsed. NAMED rather than a 3-tuple: two of the three slots are `list[str]`
    and both are empty on an empty file, so a swapped return would look exactly like correct
    behaviour and no test could tell (`tests/test_cli_contract.py` refuses the positional shape)."""

    slices: list[str]
    minutes: list[str]
    items: list[int | None]


def _pairs_from_lines(text: str) -> ParsedLines:
    """`<slice name>  <minutes>  [items]` per line, blanks and `#` comments skipped.

    Why this exists: the flags already repeat and pair by position, and three real builds still
    wrote a shell loop instead — `for s in "h11 t5-domain 15.6" ...; do set -- $s; timings record
    --slice "$2" --minutes "$3"; done`. The Bash tool runs zsh, where an unquoted `$s` does NOT
    word-split, so every call in every loop received empty arguments and exited 2. With
    `>/dev/null 2>&1` on the call and an unconditional success line after the loop, all 35 attempts
    across three fan-outs failed silently and `.coyomap/fanout-timings.json` was never created —
    so the next build's `timings order` had nothing to read, which is the whole point of the file.

    A file (or `-`) is the shape that has no loop in it."""
    slices: list[str] = []
    minutes: list[str] = []
    items: list[int | None] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit(None, 2) if len(line.split()) > 2 else line.rsplit(None, 1)
        if len(parts) < 2:
            raise ValueError(f"line {n} is not `<slice> <minutes> [items]`: {raw!r}")
        if len(parts) == 3:
            name, mins, count = parts
            try:
                items.append(int(count))
            except ValueError:
                # Two fields after all — the name simply had no spaces and the third token is not a
                # count. Re-read the line as `<slice> <minutes>`.
                name, mins = line.rsplit(None, 1)
                items.append(None)
        else:
            name, mins = parts
            items.append(None)
        slices.append(name.strip())
        minutes.append(mins.strip())
    return ParsedLines(slices=slices, minutes=minutes, items=items)


def cmd_record(args: argparse.Namespace) -> int:
    phase = _check_phase(args.phase)
    slice_args = list(args.slice or [])
    minute_args = list(args.minutes or [])
    item_args: list[int | None] = list(args.items or [])
    if getattr(args, "lines_from", None):
        src = (sys.stdin.read() if args.lines_from == "-"
               else Path(args.lines_from).read_text(encoding="utf-8"))
        parsed = _pairs_from_lines(src)
        slice_args += parsed.slices
        minute_args += parsed.minutes
        # ALL or NONE. Filling the gaps with 0 wrote a fabricated item count into durable telemetry
        # the next build's `timings order` reads, and the `recorded N slice(s)` confirmation does
        # not show items, so nothing said it had happened. `--items` already pairs by position and
        # refuses a count mismatch; this is the same rule one file up.
        have = [v for v in parsed.items if v is not None]
        if have and len(have) != len(parsed.items):
            raise ValueError(
                f"{len(have)} of {len(parsed.items)} line(s) carry an item count — give one on "
                f"every line or on none. Filling the rest with 0 would write a number nobody typed "
                f"into telemetry the next build orders by.")
        item_args += have
    if getattr(args, "from_agents", None) is not None:
        minute_args = _minutes_from_agents(args, slice_args, minute_args)
    pairs = _pair_slices(slice_args, minute_args)
    if not pairs:
        raise ValueError("nothing to record: pass at least one --slice with its --minutes.")
    args = argparse.Namespace(**{**vars(args), "items": item_args or None})
    items = args.items or []
    if items and len(items) != len(pairs):
        raise ValueError(f"--items was given {len(items)} time(s) for {len(pairs)} slice(s); "
                         "give one per slice or none at all.")
    path = record_path(_repo_of(args))
    runs = load_runs(path)
    for i, (name, value) in enumerate(pairs):
        runs.append(Run(phase, name, value, items[i] if items else None, args.commit))
    write_runs(path, runs)
    print(f"recorded {len(pairs)} slice(s) for phase '{phase}' -> {path}")
    for name, value in sorted(pairs, key=lambda p: -p[1]):
        print(f"  {value:6.1f} min  {name}")
    return 0


def _minutes_from_agents(args: argparse.Namespace, slices: list[str],
                         minutes: list[str]) -> list[str]:
    """The named slices' minutes, read off their agents' transcripts.

    Each `--slice` names an agent the way its brief was sent (the pointer prompt's first word), or
    by the harness's description of it. `--from-agents` with no value is this session's own
    transcripts directory. Nothing here is estimated: the span is the transcript's first record to
    its last, which is what the barrier actually waited for."""
    if minutes:
        raise ValueError("--from-agents reads each slice's minutes off its transcript; do not also "
                         "pass --minutes.")
    if not slices:
        raise ValueError("--from-agents needs the --slice names of the agents to record — the id "
                         "each brief was sent as.")
    repo = Path(_repo_of(args))
    where = Path(args.from_agents) if args.from_agents else session_agent_transcripts(repo)
    if where is None or not where.is_dir():
        raise ValueError("no agent transcripts found. Pass `--from-agents <the session's "
                         "subagents/ dir>`, or run inside the build session so the default "
                         "(this session's directory) exists.")
    by_name: dict[str, float] = {}
    seen: dict[str, list[str]] = {}
    # The LATEST transcript wins when one name was dispatched twice (a re-run after a failure),
    # and the choice is printed: the earlier span is a different attempt, not this slice's time.
    for span in sorted(agent_spans(where), key=lambda s: s.started):
        for key in (span.name, span.description):
            if key:
                by_name[key] = span.minutes
                seen.setdefault(key, []).append(f"{span.agent_id} ({span.minutes:.1f} min)")
    missing = [name for name in slices if name.strip() not in by_name]
    if missing:
        raise ValueError(f"no transcript named {', '.join(repr(m) for m in missing)} under {where}. "
                         f"Names found: {', '.join(sorted(by_name)) or 'none'}.")
    for name in slices:
        if len(seen.get(name.strip(), [])) > 1:
            print(f"note: {name.strip()!r} has {len(seen[name.strip()])} transcripts "
                  f"({', '.join(seen[name.strip()])}); the latest was recorded", file=sys.stderr)
    return [f"{by_name[name.strip()]:.1f}" for name in slices]


def cmd_order(args: argparse.Namespace) -> int:
    phase = _check_phase(args.phase)
    ranked = latest_by_slice(load_runs(record_path(_repo_of(args))), phase)
    asked = [s.strip() for s in (args.slice or []) if s.strip()]
    known = {r.slice for r in ranked}
    unrecorded = [s for s in asked if s not in known]
    if args.json:
        print(json.dumps({"phase": phase,
                          "order": [r.as_json() for r in ranked
                                    if not asked or r.slice in asked],
                          "unrecorded": unrecorded}, indent=2))
        return 0
    shown = [r for r in ranked if not asked or r.slice in asked]
    if not shown:
        print(f"no timings recorded for phase '{phase}' yet — order by the pre-index this build, "
              f"and record what the barrier takes so the next one does not have to guess.")
    else:
        print(f"phase '{phase}' — longest first, from the last build that recorded each slice:")
        for r in shown:
            extra = f"  ({r.items} items)" if r.items is not None else ""
            print(f"  {r.minutes:6.1f} min  {r.slice}{extra}")
    # NAME THE SLICE TO SPLIT. Ordering is worth seconds — the whole dispatch stagger is 12.6 s for
    # 9 agents — while straggler waste on the 2026-09-02 mcpolis build was 42% of active time. The
    # lever is SIZING, and this record is the only place that knows which slice is oversized. A list
    # sorted longest-first invites the reader to reorder; saying which one to CUT is the actionable
    # half, and it costs one line.
    if len(shown) >= 3:
        longest, runner_up = shown[0], shown[1]
        # AGAINST THE SECOND-LONGEST, not the median. A barrier closes when the LAST agent finishes,
        # so the time the longest slice holds it alone is the gap to its nearest sibling. Measured
        # against a median, slices of 10/9/1/1 min reported 9 minutes of waste where the real figure
        # is 1 — the 9-minute sibling is running the whole time.
        alone = longest.minutes - runner_up.minutes
        # AND AN ABSOLUTE FLOOR. Without one this fired on 0.4 against 0.2 min and advised splitting
        # a slice to recover twelve seconds, in a message whose own last sentence says launch order
        # is worth seconds and therefore not worth thinking about.
        if alone >= _SPLIT_MIN_MINUTES and longest.minutes >= 2 * runner_up.minutes:
            print(f"\nSPLIT '{longest.slice}': {longest.minutes:.1f} min against "
                  f"{runner_up.minutes:.1f} min for the next longest — it holds the barrier ALONE "
                  f"for {alone:.1f} min after every sibling is done. Reordering cannot recover any "
                  f"of that; only cutting the slice smaller can. Launch order is worth the dispatch "
                  f"stagger, which is SECONDS.")
    if unrecorded:
        print("\nno record for these — place them by the pre-index, not by this list:")
        for name in unrecorded:
            print(f"          ?  {name}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    repo = _repo_of(args)
    runs = load_runs(record_path(repo))
    if args.json:
        print(json.dumps({"version": VERSION, "runs": [r.as_json() for r in runs]}, indent=2))
        return 0
    if not runs:
        print(f"no fan-out timings recorded in {record_path(repo)}.")
        return 0
    for phase in PHASES:
        ranked = latest_by_slice(runs, phase)
        if not ranked:
            continue
        print(f"{phase}:")
        for r in ranked:
            extra = f"  ({r.items} items)" if r.items is not None else ""
            print(f"  {r.minutes:6.1f} min  {r.slice}{extra}")
    return 0


USAGE = """\
usage: coyomap timings <record | order | show> [args...]

What each fan-out slice ACTUALLY took, so the next build's dispatch is ordered by measurement
rather than by the method's folklore about which slice is heaviest.

  record --phase <phase> --slice "<name>" --minutes <m> [--items <n>] ...
  record --phase <phase> --lines-from <file|->
  record --phase <phase> --from-agents [<subagents dir>] --slice "<name>" ...
      Append what one fan-out's slices took. `--slice` and `--minutes` REPEAT and pair by
      position — one process, one write. A count mismatch is refused, not paired off.
      `--lines-from` reads `<slice> <minutes> [items]` per line instead, which is the shape
      with no shell loop in it: three real builds wrote `for s in ...; do set -- $s; ...; done`,
      and zsh does not word-split an unquoted `$s`, so all 35 calls got empty arguments, exited
      2 into `/dev/null`, and no timings file was ever written.
      Read the minutes off the barrier you just waited at; nothing here times anything —
      except `--from-agents`, which reads each named slice's minutes off its agent's transcript
      (first record to last), so the straggler is recorded at what it took: one of 12 hand-read
      timings on one build understated its batch's straggler by 14 minutes. Name each slice as
      its brief was sent (the pointer prompt's first word). With no value, the directory is this
      session's own transcripts.

  order --phase <phase> [--slice "<name>" ...] [--json]
      Print that phase's slices longest-first, from the last build that recorded each. With
      --slice names given, the ones with no record are listed separately rather than assumed
      short. A project with no record prints one line saying so and exits 0.

  show [--json]
      Every phase that has a record.

  --phases    the phase names this accepts
  --repo <root>   the analyzed repo (default: .); the file is <root>/.coyomap/fanout-timings.json

This is build telemetry, never map content: nothing in the map, its views or its gates reads it.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coyomap timings", add_help=False)
    sub = parser.add_subparsers(dest="verb")

    def common(p: argparse.ArgumentParser) -> None:
        # `None`, not ".", so `_repo_of` can tell an OMITTED --repo from an explicit one. The
        # default is still the current folder; what the distinction buys is the refusal below.
        p.add_argument("--repo", default=None)

    rec = sub.add_parser("record", add_help=False)
    common(rec)
    rec.add_argument("--phase", required=True)
    rec.add_argument("--slice", action="append")
    rec.add_argument("--minutes", action="append")
    rec.add_argument("--items", action="append", type=int)
    rec.add_argument("--lines-from")
    rec.add_argument("--from-agents", nargs="?", const="", default=None)
    rec.add_argument("--commit")
    rec.set_defaults(func=cmd_record)

    order = sub.add_parser("order", add_help=False)
    common(order)
    order.add_argument("--phase", required=True)
    order.add_argument("--slice", action="append")
    order.add_argument("--json", action="store_true")
    order.set_defaults(func=cmd_order)

    show = sub.add_parser("show", add_help=False)
    common(show)
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_show)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    if args[0] == "--phases":
        for phase in PHASES:
            print(phase)
        return 0
    if args[0] not in ("record", "order", "show"):
        print(f"coyomap timings: unknown verb '{args[0]}'\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    # `timings show -h` was an argparse error (`add_help=False`, so `-h` read as an unknown
    # argument): the same hole `fix`, `grounding` and `changes` had, closed the same way.
    helped = subverb_help.handle(USAGE, args[0], args[1:])
    if helped is not None:
        return helped
    parsed = build_parser().parse_args(args)
    try:
        return int(parsed.func(parsed))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
