#!/usr/bin/env python3
"""`coyomap findings` — what the agents noticed about the PRODUCT, filed by each into its own file.

**Why this exists.** A build agent's job shows it things the job does not ask about: a route with no
guard, a check that is missing, two parts of the code that disagree. Until now the only channel for
those was the agent's closing report, and a report is lost on the way more often than it arrives.
`grounding report` read the agents' transcripts for such sections, and on the 2026-10-07 mcpolis
build it read 0 of 126 hand-backs: every agent handed back through a tool call, and the reader looked
only at assistant text. The lead hand-collected 57 findings from 27 agents instead, from its own
context, which is the context a long build cannot spare.

**What it does.** Three verbs and one folder:

    coyomap findings add --repo R --agent <id> --kind risk|bug|gap|contradiction \\
                         --where <path>[:<line>[-<line>]]... --text "<text>"
    coyomap findings withdraw [--repo R] <agent>#<n> --why "<text>"
    coyomap findings collect [--repo R] [--out .coyomap/findings-report.md]

`add` writes ONE JSON line into the agent's OWN file, `.coyomap/findings/<id>.jsonl`, so no two
agents ever share a writer, and a finding is on disk the moment it is seen. `collect` reads every
file and prints ONE line, and the whole list goes into a report file. The line is what reaches the
lead; the list is there when the line says it grew.

**What it refuses.** Everything at once, and nothing is written: an id that cannot name a file, an
unknown kind, no `--where`, a `--where` that is absolute, climbs out with `..`, or names no file
under the repo, an empty text or one over 600 characters, and a `--where` or a text holding a byte
that is not UTF-8. A finding is one sentence about the code at a place the agent opened; a
paragraph belongs in the code it is about.

**Withdrawing.** A finding's id is `<agent>#<n>`, `n` being its line in the agent's file; `add`
prints it. `withdraw` takes a finding back and keeps the record of it: it appends one line saying
which finding and why, and deletes nothing. `collect` then counts the finding no more and lists it
under its own heading, with the why. Before this verb an agent that saw it was wrong could only say
so in prose: on the 2026-10-08 mcpolis build a half-retracted finding shipped in the report.

The files are build telemetry, never map content: nothing in the map, its views or its gates reads
them, and `assemble` keeps them out of git.

Stdlib-only (the cli.py firewall). It imports buildstate, reporting, credentials, uncommitted and
the sub-verb helpers, none of which imports it back.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from coyomap import buildstate, subverb_help
from coyomap.credentials import redact
from coyomap.provenance import COYOMAP_SUBDIR, now_minute
from coyomap.reporting import clip, shown
from coyomap.subverb_args import ArgError, SubverbParser, subverb_parser, undecodable
from coyomap.uncommitted import FINDINGS_REPORT
from coyomap.whole_file import write_whole

#: The four kinds, in the order every count and every report lists them: the one the operator hears
#: about at once first.
KINDS: tuple[str, ...] = ("risk", "bug", "gap", "contradiction")

#: Where `collect` writes the whole list, relative to the repo.
REPORT = f"{COYOMAP_SUBDIR}/{FINDINGS_REPORT}"

#: The longest text `add` takes. A finding is one sentence about the code; the `--where` lines carry
#: the places.
TEXT_MAX = 600

#: The longest agent id: it names a file, and a file name has a limit of its own.
AGENT_MAX = 128

_AGENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
#: A finding's id: its agent, then its line in that agent's file.
_FINDING_ID = re.compile(r"(?P<agent>[A-Za-z0-9][A-Za-z0-9._-]*)#(?P<line>[1-9][0-9]*)")
_WHERE = re.compile(r"(?P<path>[^:]+)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?")

#: The report's first line, which carries the total the next `collect` counts the new from.
_REPORT_TITLE = "# Agent findings — "
_REPORT_TOTAL = re.compile(r"^# Agent findings — (?:(\d+) from |none filed)")


def findings_dir(repo: Path) -> Path:
    """`<repo>/.coyomap/findings/`, the folder every agent's file lives in."""
    return repo / buildstate.FINDINGS_DIR


def beside_map(map_path: Path) -> Path:
    """The findings folder of the build that made `map_path`: `<repo>/.coyomap/findings/` for the
    live map, and the one an archive moved with an archived map into `dev-rebuilds/NNNN/`. A reader
    of a map counts the findings beside it, the way finalize reads the `verify/` beside it."""
    return map_path.resolve().parent / Path(buildstate.FINDINGS_DIR).name


@dataclass(frozen=True)
class Finding:
    """One line of one agent's file."""

    agent: str
    kind: str
    where: tuple[str, ...]
    text: str
    at: str
    line: int = 0   # its line in the agent's file: the `n` of its id

    @property
    def id(self) -> str:
        """`<agent>#<n>`, what `withdraw` names it by."""
        return f"{self.agent}#{self.line}"

    @property
    def key(self) -> tuple[str, str, tuple[str, ...], str]:
        """What makes two lines the same finding: everything but the minute it was filed. A retried
        agent files its findings again, and the second copy is a repeat, not a second finding."""
        return (self.agent, self.kind, self.where, self.text)


@dataclass(frozen=True)
class Withdrawn:
    """A finding taken back, with the reason. The finding itself stays in its file."""

    finding: Finding
    why: str
    at: str


@dataclass(frozen=True)
class Filed:
    """Everything under one repo's findings folder."""

    findings: tuple[Finding, ...]   # in file order, files by name, exact repeats and withdrawn dropped
    malformed: tuple[str, ...]      # one per line that is not a finding: `<file>:<n>: <why>`
    repeats: int                    # exact repeats dropped
    files: int                      # agent files read
    withdrawn: tuple[Withdrawn, ...] = ()   # taken back by `withdraw`, in file order

    @property
    def agents(self) -> int:
        """How many agents filed at least one finding."""
        return len({f.agent for f in self.findings})

    def of_kind(self, kind: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.kind == kind)


class FindingRefused(ValueError):
    """`add` refused: every fault, so one retry can fix them all."""

    def __init__(self, faults: list[str]) -> None:
        super().__init__("; ".join(faults))
        self.faults = faults


# ── add ──────────────────────────────────────────────────────────────────────────────────────────

def _where_faults(repo: Path, where: str, repo_ok: bool) -> list[str]:
    m = _WHERE.fullmatch(where.strip())
    if not m:
        return [f"--where {where!r} is not <path>[:<line>[-<line>]]"]
    path = Path(m.group("path").strip())
    if path.is_absolute() or str(path).startswith("~"):
        return [f"--where {where!r} is absolute: give the path from the repo root"]
    if ".." in path.parts:
        return [f"--where {where!r} holds `..`: give the path from the repo root, inside it"]
    faults: list[str] = []
    start, end = m.group("start"), m.group("end")
    if start is not None and int(start) < 1:
        faults.append(f"--where {where!r}: lines are numbered from 1")
    if start is not None and end is not None and int(end) < int(start):
        faults.append(f"--where {where!r}: the range ends before it starts")
    if repo_ok:
        target = repo / path
        inside = target.resolve().is_relative_to(repo.resolve())
        if not inside or not target.is_file():
            faults.append(f"--where {where!r} names no file under {repo}: name a file you opened, "
                          f"by its path from the repo root")
    return faults


def _clean_where(where: str) -> str:
    """`./src/a.py:12` → `src/a.py:12`: one spelling per place, so a repeat is seen as one."""
    m = _WHERE.fullmatch(where.strip())
    if not m:
        return where.strip()
    tail = where.strip()[len(m.group("path")):]
    return Path(m.group("path").strip()).as_posix() + tail


def add_faults(repo: Path, agent: str | None, kind: str | None, where: Sequence[str],
               text: str | None) -> list[str]:
    """Every reason `add` would refuse this finding, in argument order. Empty means it is filed."""
    faults: list[str] = []
    repo_ok = repo.is_dir() and (repo / COYOMAP_SUBDIR).is_dir()
    if not repo.is_dir():
        faults.append(f"--repo {repo} is not a folder")
    elif not repo_ok:
        faults.append(f"--repo {repo} has no {COYOMAP_SUBDIR}/ folder: pass the repo "
                      f"you are mapping")
    if agent is None:
        faults.append("no --agent: give your agent id, which names your file")
    elif not _AGENT_ID.fullmatch(agent) or len(agent) > AGENT_MAX:
        faults.append(f"--agent {agent!r} is not an agent id: one word of letters, digits, `.`, "
                      f"`_` or `-`, starting with a letter or a digit, at most {AGENT_MAX} "
                      f"characters. It names your file, .coyomap/findings/<id>.jsonl")
    if kind is None:
        faults.append(f"no --kind: one of {' | '.join(KINDS)}")
    elif kind not in KINDS:
        faults.append(f"--kind {kind!r} is not one of {' | '.join(KINDS)}")
    if not where:
        faults.append("no --where: name the file the finding is about, as <path>:<line>")
    for w in where:
        if undecodable(w):
            faults.append(f"--where {w!r} holds a byte that is not UTF-8: give the path in UTF-8")
            continue
        faults += _where_faults(repo, w, repo_ok)
    said = " ".join((text or "").split())
    if text is None or not said:
        faults.append("no --text: say what the code does, and why it matters")
    elif undecodable(said):
        faults.append("--text holds a byte that is not UTF-8: write the text again in UTF-8")
    elif len(said) > TEXT_MAX:
        faults.append(f"--text is {len(said)} characters, over {TEXT_MAX}: say the finding in one "
                      f"sentence; the --where lines carry the places")
    return faults


def add(repo: Path, agent: str | None, kind: str | None, where: Sequence[str],
        text: str | None, at: str | None = None) -> Path:
    """File one finding into the agent's own file and return that file (see `file_finding`)."""
    return file_finding(repo, agent, kind, where, text, at)[0]


def file_finding(repo: Path, agent: str | None, kind: str | None, where: Sequence[str],
                 text: str | None, at: str | None = None) -> tuple[Path, str]:
    """File one finding into the agent's own file; return that file and the finding's id. Raises `FindingRefused`
    naming every fault, before anything is written, and `OSError` when the file cannot be written.

    ONE `os.write` to a file opened for appending, so an agent filing two findings at once loses
    neither; and one file per agent, so two agents never write the same file."""
    faults = add_faults(repo, agent, kind, where, text)
    if faults or agent is None or kind is None or text is None:
        raise FindingRefused(faults)
    row: dict[str, object] = {"agent": agent, "kind": kind,
                              "where": [_clean_where(w) for w in where],
                              "text": redact(" ".join(text.split())), "at": at or now_minute()}
    folder = findings_dir(repo)
    folder.mkdir(exist_ok=True)
    path = folder / f"{agent}.jsonl"
    return path, f"{agent}#{_append_row(path, row)}"


def _append_row(path: Path, row: dict[str, object]) -> int:
    """Append one JSON line to `path` with ONE `os.write`, and return its line number in the file:
    the last line holding exactly this text, so two agents appending at once each get their own."""
    text = json.dumps(row, ensure_ascii=False)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
    try:
        os.write(fd, (text + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    return max((n for n, ln in enumerate(lines, 1) if ln == text), default=0)


def withdraw_faults(repo: Path, finding_id: str | None, why: str | None) -> list[str]:
    """Every reason `withdraw` would refuse, in argument order. Empty means it is written."""
    faults: list[str] = []
    m = _FINDING_ID.fullmatch(finding_id or "")
    if finding_id is None:
        faults.append("no finding id: give `<agent>#<n>`, as `add` and the report print it")
    elif m is None:
        faults.append(f"{finding_id!r} is not a finding id: `<agent>#<n>`, as `add` and the "
                      f"report print it")
    else:
        filed = load_folder(findings_dir(repo))
        agent, line = m.group("agent"), int(m.group("line"))
        if any(w.finding.agent == agent and w.finding.line == line for w in filed.withdrawn):
            faults.append(f"{finding_id} is already withdrawn")
        elif not (findings_dir(repo) / f"{agent}.jsonl").is_file():
            faults.append(f"no findings file for agent {agent!r} under {buildstate.FINDINGS_DIR}")
        elif not _is_finding_line(findings_dir(repo) / f"{agent}.jsonl", agent, line):
            faults.append(f"line {line} of {agent}.jsonl is no finding: `collect` writes each "
                          f"finding's id into the report")
    said = " ".join((why or "").split())
    if not said:
        faults.append("no --why: say why the finding no longer holds")
    elif undecodable(said):
        faults.append("--why holds a byte that is not UTF-8: write it again in UTF-8")
    elif len(said) > TEXT_MAX:
        faults.append(f"--why is {len(said)} characters, over {TEXT_MAX}: say it in one sentence")
    return faults


def _is_finding_line(path: Path, agent: str, line: int) -> bool:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    if not 1 <= line <= len(lines):
        return False
    try:
        return isinstance(_parse(lines[line - 1], agent, line), Finding)
    except ValueError:
        return False


def withdraw(repo: Path, finding_id: str | None, why: str | None,
             at: str | None = None) -> Path:
    """Take one finding back: append a line to its agent's file naming it and the reason, and
    return that file. Nothing is deleted, so the finding and its withdrawal both stay on record.
    Raises `FindingRefused` naming every fault, before anything is written."""
    faults = withdraw_faults(repo, finding_id, why)
    m = _FINDING_ID.fullmatch(finding_id or "")
    if faults or m is None or why is None:
        raise FindingRefused(faults)
    agent = m.group("agent")
    path = findings_dir(repo) / f"{agent}.jsonl"
    _append_row(path, {"agent": agent, "withdraws": int(m.group("line")),
                       "why": redact(" ".join(why.split())), "at": at or now_minute()})
    return path


# ── reading ──────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Withdrawal:
    """One `withdraw` line: which line of the same file it takes back, and why."""

    line: int
    why: str
    at: str


def _parse(raw: str, stem: str, n: int = 0) -> Finding | _Withdrawal:
    """One line of `<stem>.jsonl` (its `n`-th) as a finding or a withdrawal. Raises `ValueError`
    saying why it is neither."""
    try:
        row: object = json.loads(raw)
    except ValueError:
        raise ValueError("not JSON") from None
    if not isinstance(row, dict):
        raise ValueError("not a JSON object")
    agent, kind, where = row.get("agent"), row.get("kind"), row.get("where")
    text, at = row.get("text"), row.get("at")
    if not isinstance(agent, str) or agent != stem:
        raise ValueError(f"its agent is {agent!r}, not {stem!r}: each agent files only into its "
                         f"own file")
    if "withdraws" in row:
        line, why = row.get("withdraws"), row.get("why")
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            raise ValueError("`withdraws` is not a line number")
        if not isinstance(why, str) or not why.strip():
            raise ValueError("a withdrawal with no `why`")
        return _Withdrawal(line=line, why=" ".join(why.split()),
                           at=at if isinstance(at, str) else "")
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} is not one of {' | '.join(KINDS)}")
    if (not isinstance(where, list) or not where
            or not all(isinstance(w, str) and w.strip() for w in where)):
        raise ValueError("`where` is not a list of places")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("`text` is empty")
    return Finding(agent=agent, kind=str(kind), where=tuple(str(w) for w in where),
                   text=" ".join(text.split()), at=at if isinstance(at, str) else "", line=n)


def load(repo: Path) -> Filed:
    """Every finding filed under `repo`, exact repeats dropped."""
    return load_folder(findings_dir(repo))


def load_folder(folder: Path) -> Filed:
    """Every finding in one findings folder, exact repeats dropped. A line that is not a finding is
    named in `malformed` and never stops the rest from being read."""
    if not folder.is_dir():
        return Filed(findings=(), malformed=(), repeats=0, files=0)
    out: list[Finding] = []
    malformed: list[str] = []
    withdrawn: list[Withdrawn] = []
    seen: set[tuple[str, str, tuple[str, ...], str]] = set()
    repeats = 0
    files = sorted(folder.glob("*.jsonl"))
    for f in files:
        try:
            body = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            malformed.append(f"{f.name}: cannot be read ({exc.strerror or exc})")
            continue
        own: dict[int, Finding] = {}
        takebacks: list[tuple[int, _Withdrawal]] = []
        for n, raw in enumerate(body.splitlines(), 1):
            if not raw.strip():
                continue
            try:
                parsed = _parse(raw, f.stem, n)
            except ValueError as exc:
                malformed.append(f"{f.name}:{n}: {exc} — {clip(redact(raw), 80)}")
                continue
            if isinstance(parsed, _Withdrawal):
                takebacks.append((n, parsed))
            else:
                own[n] = parsed
        # A WITHDRAWN FINDING is counted nowhere, and neither is a later exact repeat of it: a
        # retried agent filing it again does not bring it back.
        gone: set[tuple[str, str, tuple[str, ...], str]] = set()
        for n, w in takebacks:
            target = own.get(w.line)
            if target is None:
                malformed.append(f"{f.name}:{n}: withdraws line {w.line}, which is no finding")
            elif target.key in gone:
                malformed.append(f"{f.name}:{n}: withdraws {target.id} a second time")
            else:
                gone.add(target.key)
                withdrawn.append(Withdrawn(finding=target, why=w.why, at=w.at))
        for finding in own.values():
            if finding.key in gone:
                continue
            if finding.key in seen:
                repeats += 1
                continue
            seen.add(finding.key)
            out.append(finding)
    return Filed(findings=tuple(out), malformed=tuple(malformed), repeats=repeats, files=len(files),
                 withdrawn=tuple(withdrawn))


def counts(filed: Filed) -> str:
    """`23 from 11 agent(s): risk 9 · bug 4 · gap 7 · contradiction 3`."""
    return (f"{len(filed.findings)} from {filed.agents} agent(s): "
            + " · ".join(f"{k} {len(filed.of_kind(k))}" for k in KINDS))


def verdict_line(filed: Filed, since: int | None = None, report: str | None = None,
                 title: str = "FINDINGS") -> str:
    """The ONE line every reader of the findings prints. `collect` gives `since` and the report it
    wrote; a reader that writes nothing (`grounding report`, `finalize`) gives neither.

    `FINDINGS — 23 from 11 agent(s): risk 9 · bug 4 · gap 7 · contradiction 3 (+5 since the last
    collect) · 0 malformed → .coyomap/findings-report.md`, or `FINDINGS — none filed`."""
    if not filed.findings and not filed.malformed and not filed.withdrawn:
        return f"{title} — none filed"
    return (f"{title} — {counts(filed)}"
            + (f" (+{since} since the last collect)" if since is not None else "")
            + (f" · {len(filed.withdrawn)} withdrawn" if filed.withdrawn else "")
            + f" · {len(filed.malformed)} malformed"
            + (f" → {report}" if report else ""))


def reader_line(filed: Filed | None) -> str:
    """The line a report that READS the findings prints, `grounding report` and `finalize`: the
    collect line's counts under the one title both reports carry. No `since` and no report path,
    because neither writes the list, and a report file it named could be older than the folder.
    None is a report that could not tell whose findings to read, which must not read as "none"."""
    if filed is None:
        return ("FINDINGS FILED BY AGENTS — unknown: no input names a <repo>/.coyomap/ folder, so "
                "this cannot tell whose findings to read")
    return verdict_line(filed, title="FINDINGS FILED BY AGENTS")


#: What a reader says under its line when something was filed: where the list is, and who hears it.
READER_GUIDANCE = (f"Each agent filed these into its own file under {buildstate.FINDINGS_DIR} as it "
                   f"worked; no tool checked them against the code. `coyomap findings collect "
                   f"--repo <repo>` writes the whole list to {REPORT}. Tell the operator about each "
                   f"`risk`; the rest go in the closing report.")


# ── collect ──────────────────────────────────────────────────────────────────────────────────────

def previous_total(report: Path) -> int | None:
    """The total the last `collect` wrote into `report`, or None when there is no readable one."""
    try:
        first = report.read_text(encoding="utf-8").splitlines()[:1]
    except (OSError, UnicodeDecodeError):
        return None
    m = _REPORT_TOTAL.match(first[0]) if first else None
    if m is None:
        return None
    return int(m.group(1)) if m.group(1) else 0


def _place(path: Path, repo: Path) -> str:
    """`path` from the repo root when it is inside the repo, else as given."""
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return str(path)


def report_text(filed: Filed, since: int, at: str) -> str:
    """The whole list, grouped by kind: risk, bug, gap, contradiction, then the malformed lines."""
    title = "none filed" if not filed.findings and not filed.malformed and not filed.withdrawn else (
        f"{counts(filed)}" + (f" · {len(filed.withdrawn)} withdrawn" if filed.withdrawn else "")
        + f" · {len(filed.malformed)} malformed")
    out = [f"{_REPORT_TITLE}{title}", "",
           f"Collected {at} by `coyomap findings collect` from {filed.files} file(s) in "
           f"{buildstate.FINDINGS_DIR}: +{since} since the last collect"
           + (f", {filed.repeats} exact repeat(s) dropped" if filed.repeats else "") + ".",
           "",
           "Each line is one agent's own words, filed while it worked; no tool checked it against "
           "the code. Tell the operator about each `risk` now; the rest go in the closing report. "
           "The map changes only when a finding shows the map is wrong.", ""]
    for kind in KINDS:
        rows = filed.of_kind(kind)
        out += [f"## {kind} ({len(rows)})", ""]
        if not rows:
            out += ["None filed.", ""]
            continue
        for f in rows:
            places = " · ".join(f"`{w}`" for w in f.where)
            out.append(f"- [{f.id}] {places} — {redact(f.text)} ({f.agent}"
                       + (f", {f.at})" if f.at else ")"))
        out.append("")
    if filed.withdrawn:
        out += [f"## withdrawn ({len(filed.withdrawn)})", "",
                "Taken back by `coyomap findings withdraw`, and counted nowhere above. Each keeps "
                "the finding and the reason it was withdrawn.", ""]
        for w in filed.withdrawn:
            f = w.finding
            out.append(f"- [{f.id}] {f.kind} at " + " · ".join(f"`{p}`" for p in f.where)
                       + f" — {redact(f.text)} WITHDRAWN: {redact(w.why)}"
                       + (f" ({w.at})" if w.at else ""))
        out.append("")
    if filed.malformed:
        out += [f"## malformed lines ({len(filed.malformed)})", "",
                "A line `coyomap findings add` did not write. The findings beside it are counted "
                "above; fix or delete the line.", ""]
        out += [f"- {m}" for m in filed.malformed]
        out.append("")
    return "\n".join(out)


@dataclass(frozen=True)
class Collected:
    """What one `collect` read and wrote."""

    filed: Filed
    since: int
    report: Path
    line: str


def collect(repo: Path, out: Path | None = None, at: str | None = None) -> Collected:
    """Read every agent's file, write the whole list, and return the ONE line to print. Raises
    `OSError` when the report cannot be written.

    `since` counts against the total the previous report states, so it moves only at a `collect`:
    a reader that prints the line without writing the list leaves it where it was."""
    filed = load(repo)
    target = out if out is not None else repo / REPORT
    before = previous_total(target)
    since = max(0, len(filed.findings) - before) if before is not None else len(filed.findings)
    write_whole(target, report_text(filed, since, at or now_minute()))
    return Collected(filed=filed, since=since, report=target,
                     line=verdict_line(filed, since=since, report=_place(target, repo)))


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────

USAGE = f"""usage: coyomap findings <add | withdraw | collect> [args...]

Product findings the agents file as they work, and the lead collects. A finding is a bug, a risk
(to security, privacy, money or data), a gap (a check that is missing, a path nothing guards) or a
contradiction (two parts of the code, or the code and its own docs, that disagree).

  add --repo <repo> --agent <id> --kind <{'|'.join(KINDS)}>
      --where <path>[:<line>[-<line>]]... --text "<what the code does, and why it matters>"
      File ONE finding, the moment you see it, into your own file: .coyomap/findings/<id>.jsonl.
      `--where` repeats (or takes several places) when a finding spans files; each is a path from
      the repo root, to a file you opened. The text is at most {TEXT_MAX} characters, and a value
      shaped like a credential is replaced before it is written. Every fault is named at once and
      nothing is written (exit 2). Filing changes nothing in the code or the map.

  withdraw [--repo <repo>] <agent>#<n> --why "<why it no longer holds>"
      Take back ONE finding, by the id `add` printed (`<agent>#<n>`, n its line in the file). One
      line saying which finding and why is appended to that file; nothing is deleted. `collect`
      counts the finding no more and lists it under "withdrawn" with the why. Exit 2, and nothing
      written, on an id that names no finding, one already withdrawn, or no --why.

  collect [--repo <repo>] [--out <file>]
      Read every agent's file and print ONE line — the count by kind, how many are new since the
      last collect, the malformed lines, and the report it wrote (default {REPORT}),
      which holds the whole list grouped by kind. Run it when the agents are back, and open the
      report when its `risk` count grew.

  --repo <repo>   the repo you are mapping. `add` needs it; `withdraw` and `collect` default to
                  the current folder, refused inside the coyomap clone.

Build telemetry, never map content: nothing in the map, its views or its gates reads these files,
and none of them is committed."""

_VERBS = ("add", "withdraw", "collect")


def build_parser(verb: str) -> SubverbParser:
    p = subverb_parser(f"coyomap findings {verb}")
    p.add_argument("--repo", default=None)
    if verb == "add":
        p.add_argument("--agent", default=None)
        p.add_argument("--kind", default=None)
        p.add_argument("--where", action="extend", nargs="+", default=[])
        p.add_argument("--text", default=None)
    elif verb == "withdraw":
        p.add_argument("finding_id", nargs="?", default=None)
        p.add_argument("--why", default=None)
    else:
        p.add_argument("--out", default=None)
    return p


def _cmd_add(parsed: argparse.Namespace) -> int:
    if parsed.repo is None:
        return subverb_help.usage_error(USAGE, "add", "add needs --repo <the repo you are mapping>")
    repo = Path(parsed.repo).expanduser()
    try:
        path, ident = file_finding(repo, parsed.agent, parsed.kind, list(parsed.where),
                                   parsed.text)
    except FindingRefused as exc:
        print(f"REFUSED — {len(exc.faults)} fault(s), and nothing was filed:", file=sys.stderr)
        for fault in exc.faults:
            print(f"  - {fault}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: the finding was not filed ({exc.strerror or exc}: {exc.filename})",
              file=sys.stderr)
        return 1
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    held = sum(1 for ln in lines if ln.strip())
    where = list(parsed.where)
    print(f"FILED — {parsed.kind} at {shown([_clean_where(w) for w in where], 2)} as {ident} → "
          f"{_place(path, repo)}, which now holds {held} line(s). End your report with "
          f"`findings: <the number you filed>`. If it turns out wrong, take it back with "
          f"`coyomap findings withdraw <id> --why \"<why>\"`.")
    return 0


def _cmd_withdraw(parsed: argparse.Namespace) -> int:
    try:
        repo = buildstate.resolve_repo(parsed.repo)
    except ValueError as exc:
        return subverb_help.usage_error(USAGE, "withdraw", str(exc))
    try:
        path = withdraw(repo, parsed.finding_id, parsed.why)
    except FindingRefused as exc:
        print(f"REFUSED — {len(exc.faults)} fault(s), and nothing was written:", file=sys.stderr)
        for fault in exc.faults:
            print(f"  - {fault}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: the withdrawal was not written ({exc.strerror or exc}: {exc.filename})",
              file=sys.stderr)
        return 1
    print(f"WITHDRAWN — {parsed.finding_id}: the finding stays in {_place(path, repo)} with the "
          f"reason beside it, and `collect` counts it no more.")
    return 0


def _cmd_collect(parsed: argparse.Namespace) -> int:
    try:
        repo = buildstate.resolve_repo(parsed.repo)
    except ValueError as exc:
        return subverb_help.usage_error(USAGE, "collect", str(exc))
    if not (repo / COYOMAP_SUBDIR).is_dir():
        return subverb_help.usage_error(
            USAGE, "collect", f"{repo} has no {COYOMAP_SUBDIR}/ folder: pass --repo <the "
                              f"repo you are mapping>")
    try:
        got = collect(repo, Path(parsed.out) if parsed.out else None)
    except OSError as exc:
        print(f"ERROR: the findings report was not written ({exc.strerror or exc}: "
              f"{exc.filename})", file=sys.stderr)
        return 1
    print(got.line)
    buildstate.append(repo, "findings", got.line)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in subverb_help.HELP_FLAGS:
        print(USAGE)
        return 0 if args else 2
    verb, rest = args[0], args[1:]
    if verb not in _VERBS:
        print(f"coyomap findings: unknown verb '{verb}'\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        print(f"\nERROR: unknown verb '{verb}' (expected `add`, `withdraw` or `collect`)",
              file=sys.stderr)
        return 2
    helped = subverb_help.handle(USAGE, verb, rest)
    if helped is not None:
        return helped
    try:
        parsed = build_parser(verb).parse_args(rest)
    except ArgError as exc:
        return subverb_help.usage_error(USAGE, verb, str(exc))
    if verb == "add":
        return _cmd_add(parsed)
    return _cmd_withdraw(parsed) if verb == "withdraw" else _cmd_collect(parsed)


if __name__ == "__main__":
    raise SystemExit(main())
