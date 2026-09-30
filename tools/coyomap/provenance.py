#!/usr/bin/env python3
"""`coyomap provenance` — record WHICH session built the map, and WHEN.

`finalize` refuses to bless a commit whose `.coyomap/provenance.json` is missing, and the file was
produced only by `tools/map_backup.py` — a script in the coyomap clone that the SHIPPED CLI does
not install. So a build that had done everything right hit a gate demanding an artifact no
`coyomap` command could make: one live build ran `finalize`, was told to produce provenance,
re-ran `finalize` without it, got the identical complaint, and only then went looking for the
script. That is the whole reason this module exists as a command.

The model lives here and `map_backup.py` imports it, so the stamp the CLI writes and the stamp the
backup tool reads can never drift into two shapes of the same file. Stdlib-only.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from coyomap import subverb_help

COYOMAP_SUBDIR = ".coyomap"
PROVENANCE_NAME = "provenance.json"
PROVENANCE_SCHEMA = "coyomap-provenance/v1"
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"


@dataclasses.dataclass
class SessionEntry:
    session_id: str
    built_at: str                     # local wall-clock, minute precision: "YYYY-MM-DD HH:MM"
    mode: str                         # build | accept | rebuild
    code_commit: str | None = None    # short sha of the analyzed repo at build time
    code_committed: str | None = None  # that commit's date, YYYY-MM-DD
    #: The coyomap clone that built it, as `assemble` stamps the map header — but a later repair
    #: re-assembles and re-stamps the header, so the header names the repair's tool, not the
    #: build's. The retro's check range needs the build's, and this is where it survives.
    tool_commit: str | None = None

    @staticmethod
    def from_dict(d: dict[str, object]) -> "SessionEntry":
        def s(key: str) -> str:
            v = d.get(key)
            return v if isinstance(v, str) else ""

        def opt(key: str) -> str | None:
            v = d.get(key)
            return v if isinstance(v, str) else None

        return SessionEntry(
            session_id=s("session_id"),
            built_at=s("built_at"),
            mode=s("mode") or "build",
            code_commit=opt("code_commit"),
            code_committed=opt("code_committed"),
            tool_commit=opt("tool_commit"),
        )


@dataclasses.dataclass
class Provenance:
    project: str
    repo_path: str
    sessions: list[SessionEntry] = dataclasses.field(default_factory=list)
    schema: str = PROVENANCE_SCHEMA

    def latest(self) -> SessionEntry | None:
        return self.sessions[-1] if self.sessions else None

    def upsert(self, entry: SessionEntry) -> None:
        """Add the entry, or update the existing entry for the same session id."""
        for i, existing in enumerate(self.sessions):
            if existing.session_id == entry.session_id:
                self.sessions[i] = entry
                return
        self.sessions.append(entry)

    def to_json(self) -> str:
        payload: dict[str, object] = {
            "schema": self.schema,
            "project": self.project,
            "repo_path": self.repo_path,
            "sessions": [dataclasses.asdict(s) for s in self.sessions],
        }
        return json.dumps(payload, indent=2) + "\n"

    @staticmethod
    def load(path: Path) -> "Provenance | None":
        """Parse provenance.json. Raises ValueError on a corrupt/non-object file."""
        if not path.is_file():
            return None
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"{path} is not readable JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"{path} does not contain a JSON object")
        sessions_raw = raw.get("sessions")
        sessions: list[SessionEntry] = []
        if isinstance(sessions_raw, list):
            for item in sessions_raw:
                if isinstance(item, dict):
                    sessions.append(SessionEntry.from_dict(item))
        project = raw.get("project")
        repo_path = raw.get("repo_path")
        schema = raw.get("schema")
        return Provenance(
            project=project if isinstance(project, str) else "",
            repo_path=repo_path if isinstance(repo_path, str) else "",
            sessions=sessions,
            schema=schema if isinstance(schema, str) else PROVENANCE_SCHEMA,
        )


def git_value(repo: Path, *args: str) -> str | None:
    try:
        # TIMEOUT, and a wide except: this runs inside `assemble`, immediately before the map is
        # written. A `git` that blocks — a credential prompt, a stalled filesystem, a hook — used
        # to lose the whole assembly rather than the one optional value it was fetching. No git
        # answer is ever worth more than the work already done.
        out = subprocess.run(["git", "-C", str(repo), *args],
                             capture_output=True, text=True, check=True, timeout=5,
                             stdin=subprocess.DEVNULL,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout.strip() or None


#: Directories whose churn is coyomap's OWN and must never make the user's tree read as dirty.
#: `.coyomap/` is the map and its reports; `.coyomap-eval/` is the eval and retro scratch, which is
#: git-ignored scratch by design. Leaving the second one out is not cosmetic: on a live build it was
#: the ONLY path `scope` reported, so the operator was asked to choose a dirty pin because of a
#: directory this toolchain had just written itself.
_OURS = (".coyomap", ".coyomap-eval")


def _git_raw(repo: Path, *args: str) -> str | None:
    """`git_value` without the `.strip()`. Porcelain status is COLUMN-ORIENTED — `XY path`, where a
    clean index leaves column 1 blank — so stripping the output eats the first line's leading space
    and takes a character off the first path with it. Caught by a test, one commit after the strip
    turned `tests/test_audit.py` into `ests/test_audit.py`."""
    try:
        out = subprocess.run(["git", "-C", str(repo), *args],
                             capture_output=True, text=True, check=True, timeout=5,
                             stdin=subprocess.DEVNULL,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout


def dirty_paths(repo: Path) -> tuple[str, ...]:
    """Repo-relative paths changed but not committed, excluding coyomap's own output.

    One definition, read by `scope` (which asks the operator), by `stamp` (which records the answer)
    and by `lint-fragment` (which checks the record). They disagreed once and the map shipped a pin
    that said `clean` about a tree that was not."""
    excludes = [f":(exclude){d}" for d in _OURS]
    status = _git_raw(repo, "status", "--porcelain", "--", ".", *excludes)
    return tuple(line[3:].strip() for line in (status or "").splitlines() if line.strip())


def project_slug(repo: Path) -> str:
    """`~/.claude/projects/<slug>`: the absolute path with every `/` and `.` replaced by `-`
    (a worktree under `.claude/worktrees/` lands at `…-coyomap--claude-worktrees-…`)."""
    return re.sub(r"[/.]", "-", str(repo.resolve()))


def session_agent_transcripts(repo: Path, session_id: str | None = None,
                              home: Path | None = None) -> Path | None:
    """Where this harness keeps the running build's per-agent transcripts, or None.

    `~/.claude/projects/<slug of repo>/<$CLAUDE_CODE_SESSION_ID>/subagents/`. Read only when the
    session id is in the environment (or given) and the directory exists, so a run outside a build
    behaves as before. `grounding lint` defaults `--agent-transcripts` to this: the flag was
    advertised by the tool's own output and passed 0 times across four builds, which left the one
    check that can see a fabricated citation unrun while the transcripts sat on disk."""
    sid = session_id or os.environ.get(SESSION_ENV)
    if not sid:
        return None
    d = (home or Path.home()) / ".claude" / "projects" / project_slug(repo) / sid / "subagents"
    return d if d.is_dir() else None


def session_transcript(repo: Path, session_id: str | None = None,
                       home: Path | None = None) -> Path | None:
    """The running build's OWN transcript — the lead's turns — or None.

    `~/.claude/projects/<slug of repo>/<$CLAUDE_CODE_SESSION_ID>.jsonl`, the file beside the
    `subagents/` folder `session_agent_transcripts` finds. `finalize` reads it for one question
    only: did the lead open a file before recording why its access claim may go."""
    sid = session_id or os.environ.get(SESSION_ENV)
    if not sid:
        return None
    root = (home or Path.home()) / ".claude" / "projects"
    f = root / project_slug(repo) / f"{sid}.jsonl"
    if f.is_file():
        return f
    # A session started in another folder keeps its transcript under THAT folder's slug: the
    # 2026-09-30 mcpolis build ran from the coyomap clone, the mcpolis slug held nothing, and the
    # check never ran. A session id names one session, so one match anywhere is the file.
    found = sorted(root.glob(f"*/{sid}.jsonl"))
    return found[0] if len(found) == 1 else None


def tool_commit_here() -> str | None:
    """The coyomap clone this command runs from, spelled as `assemble` spells the map header's
    `tool_commit` (`git describe --always --dirty`), or None under an ordinary install."""
    home = Path(__file__).resolve().parents[2]
    if not (home / ".git").exists():
        return None
    return git_value(home, "describe", "--always", "--dirty", "--abbrev=7")


def pin_sha(repo: Path) -> str | None:
    """HEAD's short sha, with the `-dirty` suffix when the working tree carries uncommitted code.

    `method.md` requires `<short-sha>-dirty` whenever the operator proceeds on a dirty tree, and
    `dispatch.md` reads the suffix back ("if the pin ends in `-dirty` it never matched a clean
    commit"). Nothing wrote it. On the 2026-08-20 argus build the operator was offered, and chose,
    an option whose own text promised `611c93c-dirty`; the header was then hand-written as plain
    `611c93c`, the final report told the operator the suffix HAD been recorded, and nine of the ten
    map anchors into a file another session edited mid-build now resolve against the wrong lines.
    The suffix is not a label — it is the difference between "read this at that commit" and "this
    commit does not contain what I read"."""
    sha = git_value(repo, "rev-parse", "--short", "HEAD")
    if not sha:
        return None
    return f"{sha}-dirty" if dirty_paths(repo) else sha


def now_minute() -> str:
    """Local wall-clock, minute precision. Build time per the user's choice."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def stamp(repo: Path, mode: str = "build", session_id: str | None = None,
          built_at: str | None = None) -> tuple[Path, SessionEntry, list[str]]:
    """Write (or refresh) this session's entry in `<repo>/.coyomap/provenance.json`.

    Returns the path, the entry written, and any warnings. A CORRUPT file is rewritten from
    scratch with a warning rather than refused: the stamp is the repair."""
    warnings: list[str] = []
    coyomap_dir = repo / COYOMAP_SUBDIR
    if not coyomap_dir.is_dir():
        raise FileNotFoundError(f"no {COYOMAP_SUBDIR}/ directory under {repo}")
    sid = session_id or os.environ.get(SESSION_ENV)
    if not sid:
        raise ValueError(f"no session id: set ${SESSION_ENV} (present inside a Claude Code "
                         f"session) or pass --session-id")
    entry = SessionEntry(
        session_id=sid,
        built_at=built_at or now_minute(),
        mode=mode,
        code_commit=pin_sha(repo),
        code_committed=git_value(repo, "show", "-s", "--format=%cs", "HEAD"),
        tool_commit=tool_commit_here(),
    )
    path = coyomap_dir / PROVENANCE_NAME
    try:
        prov = Provenance.load(path)
    except ValueError as exc:
        warnings.append(f"warning: {exc}; rewriting from scratch")
        prov = None
    if prov is None:
        prov = Provenance(project=repo.name, repo_path=str(repo))
    prov.project = prov.project or repo.name
    prov.repo_path = str(repo)          # keep fresh in case the repo moved
    prov.upsert(entry)
    path.write_text(prov.to_json(), encoding="utf-8")
    return path, entry, warnings


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────

_MODES = ("build", "accept", "rebuild")

USAGE = """usage: coyomap provenance stamp [<repo>] [--mode build|accept|rebuild]
                                [--session-id <id>] [--built-at 'YYYY-MM-DD HH:MM']
                                [--update-header <header-fragment.json>]
       coyomap provenance show [<repo>]

stamp   Record this session's id + minute-precise build time in <repo>/.coyomap/provenance.json —
        the file `finalize` requires before a map is committed. <repo> defaults to the current
        directory. The session id comes from $CLAUDE_CODE_SESSION_ID unless --session-id overrides
        it.

        --update-header <header-fragment.json>
                WRITE the stamped minute straight into that fragment's `built`, AND the stamped pin
                into its `commit`, so the header and provenance cannot disagree. The pin carries the
                `-dirty` suffix `method.md` requires whenever the working tree holds uncommitted code
                (coyomap's own `.coyomap/` and `.coyomap-eval/` never count as dirt). USE THIS. Without it the only way to close the loop is
                to read `built_at=...` off stdout and hand-write it back, and hand-writing it is a
                map write in the middle of the one closing sequence: builds did it with a
                `python3 - <<'PY'` heredoc that json-loads the fragment, sets one string and dumps
                it back. This flag exists because of that, and a build still hand-rolled it the day
                after it shipped: this help told the reader to carry the minute across by hand and
                named no alternative, so the alternative went unfound.

        Prints `built_at=YYYY-MM-DD HH:MM` on stdout either way, so a caller that needs the value
        for something else still has it.
        Re-stamping the SAME session updates its entry rather than appending a second one.

show    Print the recorded sessions, newest last."""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if argv else 2
    verb, rest = argv[0], argv[1:]
    if verb not in ("stamp", "show"):
        print(f"coyomap provenance: unknown verb '{verb}'\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    helped = subverb_help.handle(USAGE, verb, rest)
    if helped is not None:
        return helped
    repo_arg = None
    mode = "build"
    session_id = built_at = header_path = None
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("--mode", "--session-id", "--built-at", "--update-header"):
            i += 1
            if i >= len(rest):
                print(f"ERROR: {a} needs a value", file=sys.stderr)
                return 2
            if a == "--mode":
                mode = rest[i]
            elif a == "--session-id":
                session_id = rest[i]
            elif a == "--update-header":
                header_path = rest[i]
            else:
                built_at = rest[i]
        elif a.startswith("-"):
            print(f"ERROR: unknown option '{a}'\n{USAGE}", file=sys.stderr)
            return 2
        else:
            repo_arg = a
        i += 1
    repo = Path(repo_arg or ".").resolve()
    if verb == "show":
        path = repo / COYOMAP_SUBDIR / PROVENANCE_NAME
        try:
            prov = Provenance.load(path)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        if prov is None:
            print(f"{path} does not exist — this map is un-stamped. Run `coyomap provenance stamp`.")
            return 1
        print(f"{prov.project} ({prov.repo_path}) — {len(prov.sessions)} session(s)")
        for s in prov.sessions:
            print(f"  {s.built_at}  {s.mode:<8} {s.session_id}"
                  f"{f'  code {s.code_commit}' if s.code_commit else ''}")
        return 0
    if mode not in _MODES:
        print(f"ERROR: --mode must be one of {', '.join(_MODES)}", file=sys.stderr)
        return 2
    try:
        path, entry, warnings = stamp(repo, mode=mode, session_id=session_id, built_at=built_at)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for w in warnings:
        print(f"coyomap provenance: {w}", file=sys.stderr)
    if header_path is not None:
        rc = _write_header_built(Path(header_path), entry.built_at, entry.code_commit)
        if rc:
            return rc
    # stdout carries the one value the build must copy verbatim; the human line goes to stderr, so
    # `built_at=$(coyomap provenance stamp)` is a usable idiom.
    print(f"built_at={entry.built_at}")
    print(f"stamped {path} (session {entry.session_id}, mode {entry.mode})", file=sys.stderr)
    return 0


def _write_header_built(header: Path, built_at: str, commit: str | None = None) -> int:
    """Put `built_at` in the header fragment's `built`, and the stamped pin in its `commit`.

    Returns a non-zero exit on failure.

    The `commit` half exists because the pin was the one field a build hand-wrote and nothing
    checked. `stamp` computes it from git — including the `-dirty` suffix `method.md` requires —
    so writing it here is the only way the header and the provenance file cannot disagree.

    The alternative, and what builds actually did, is a `python3 - <<'PY'` heredoc that json-loads
    the fragment, sets one string and dumps it back — a hand-written map write in the middle of the
    one sequence, for a value the tool had just printed. It is a two-line edit, which is exactly why
    it should not be hand-rolled: the failure mode is a header and a provenance file that disagree,
    and nothing downstream compares them."""
    try:
        data = json.loads(header.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"ERROR: --update-header {header}: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"ERROR: --update-header {header} is not JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print(f"ERROR: --update-header {header} is not a fragment object", file=sys.stderr)
        return 2
    was = data.get("built")
    data["built"] = built_at
    changed = [f"built {was!r} -> {built_at!r}"]
    if commit is not None:
        was_commit = data.get("commit")
        if was_commit != commit:
            data["commit"] = commit
            changed.append(f"commit {was_commit!r} -> {commit!r}")
    header.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"header {header.name}: " + "; ".join(changed), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


#: The build's own name for a sub-agent, from the pointer prompt that dispatched it. The verb's
#: brief is `<agent id>\n<path>\n<sentence>`; a build that composes its own writes "You are agent
#: <id>." instead, and both shapes are read.
_YOU_ARE_AGENT = re.compile(r"You are agent (\S+?)[.,]?(?:\s|$)")


@dataclasses.dataclass(frozen=True)
class AgentSpan:
    """One sub-agent's transcript, reduced to what a fan-out timing needs."""

    agent_id: str            # the harness's id, from the file name
    name: str | None         # the build's own name for it, from the pointer prompt
    description: str | None  # the harness's one-line description, from the meta file
    minutes: float           # first record to last record, wall clock
    records: int
    started: str = ""        # the first record's timestamp, ISO 8601, for ordering re-dispatches


def agent_spans(subagents_dir: Path) -> list[AgentSpan]:
    """Every `agent-*.jsonl` under the session's transcripts, with its wall span.

    `timings record --from-agents` reads minutes off these instead of off the lead's memory of the
    barrier: 11 of 12 recorded fan-out timings on the 2026-09-08 mcpolis build were exact and the
    twelfth understated the batch straggler by 14 minutes, which is the one number `timings order`
    exists to carry to the next build."""
    out: list[AgentSpan] = []
    for f in sorted(subagents_dir.glob("agent-*.jsonl")):
        stamps: list[datetime] = []
        name: str | None = None
        records = 0
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            records += 1
            ts = row.get("timestamp")
            if isinstance(ts, str):
                try:
                    stamps.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
                except ValueError:
                    pass
            if name is None and row.get("type") == "user":
                name = _agent_name(row.get("message"))
        if not stamps:
            continue
        meta = f.with_name(f.stem + ".meta.json")
        description: str | None = None
        if meta.is_file():
            try:
                doc = json.loads(meta.read_text(encoding="utf-8"))
                if isinstance(doc, dict) and isinstance(doc.get("description"), str):
                    description = doc["description"]
            except ValueError:
                pass
        minutes = (max(stamps) - min(stamps)).total_seconds() / 60
        out.append(AgentSpan(agent_id=f.stem[len("agent-"):], name=name, description=description,
                             minutes=round(minutes, 1), records=records,
                             started=min(stamps).isoformat()))
    return out


def _agent_name(message: object) -> str | None:
    """The agent's name in a user record's text, under either pointer-prompt shape."""
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, list):
        text = " ".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
    elif isinstance(content, str):
        text = content
    else:
        return None
    hit = _YOU_ARE_AGENT.search(text)
    if hit:
        return hit.group(1)
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) >= 3 and lines[0].split() == [lines[0]] and lines[2].startswith("Read it COMPLETELY"):
        return lines[0]
    return None
