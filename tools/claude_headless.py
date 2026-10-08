#!/usr/bin/env python3
"""Run a coyomap build, and a retro of it, as a headless Claude Code session nobody watches.

`make claude-build REPO=<repo>` is for anyone using coyomap. `make claude-retro RUN=<run folder>`
and `make claude-build-retro REPO=<repo>` are for someone working on coyomap: the retro is the
developer skill `/coyomap-retro` (`make install-dev`).

Every run gets its own folder, `<project>/.coyomap/runs/claude-<date-time>/`, so nothing lands
outside the project. `runs/` hides itself from git with its own `.gitignore`, so it is never
committed, even before a build writes the map folder's `.gitignore`.

  run.json             the project folder, its branch and the commit the build started from
  status               one line per step: "build exit N", "retro exit N", "retro skipped: ..."
  empty-mcp.json       the MCP config the session starts with: none
  build.stream.jsonl   the session's own record of the build (stream-json), and build.stderr.log
  retro.stream.jsonl   the same for the retro, and retro.stderr.log

THE PROJECT FOLDER. The session works in the project folder itself, on whatever is checked out
there. A build does not commit (method.md); keeping the map in git is the operator's choice. This
script runs no push, and the session is refused any command starting `git push`. That rule matches
by prefix, so `git -C . push` would get through: the build has no step that pushes.

THE RETRO WAITS. It starts only when `coyomap-eval retro-precheck` says the build's folder has been
quiet for 180 s, asked every 30 s, for at most --wait minutes (30). A build that ran here has ended
before the retro starts, so a wait that runs out means something is still writing. The retro also
refuses a run whose map was not stamped by this run's build session: a build that died early leaves
the project's older map in place, and a retro of THAT map would report on the wrong build.

TWO PARTS. The steps any coding agent needs (run folder, the quiet wait, the status file) are kept apart from the Claude Code part (its flags, its environment, the nesting
check), so a version for another agent reuses the first part. The Claude Code part:

  * CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0. A headless session stops waiting for background
    subagents after 600 s by default and ends the run. On 2026-10-08 that ended an mcpolis build
    at its fact-check wave, after 52 minutes.
  * CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH below 2 is refused: the fact-check wave runner is a
    subagent that starts subagents. Unset, it is set to 3, Claude Code's own default, so a build
    does not depend on that default.
  * COYOMAP_CLAUDE names the claude program (default `claude`); the tests point it at a fake.

Usage:
  claude_headless.py build --repo <repo> [--model M] [--effort E] [--prompt P]
  claude_headless.py retro --run <run folder> [--model M] [--effort E] [--wait <minutes>]
  claude_headless.py build-retro --repo <repo> [the options of both]
Last night's values (2026-10-08): --model claude-opus-5-5 --effort medium. Without them, the
session uses Claude Code's own defaults: the session gets only the shell's basics (PASSED_ON), so
no setting of a chat it was started from reaches it.
Exit codes: the claude session's own; 1 refused before it started; 3 the retro's wait ran out.
build-retro exits with the build's code when the build failed, else with the retro's.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from coyomap.uncommitted import RUNS_FOLDER
from land import LandError, git_out, main_checkout

CLONE = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT = "/coyomap build a new map from scratch"
RETRO_PROMPT = "/coyomap-retro"
DEFAULT_WAIT_MINUTES = 30.0
DEFAULT_POLL_SECONDS = 30.0
STATUS = "status"
RUN_RECORD = "run.json"
EXIT_REFUSED = 1
EXIT_WAIT_RAN_OUT = 3


class RunError(Exception):
    """Why a run was refused before any agent session started."""


# ---------------------------------------------------------------------------------------------
# The part any coding agent needs.
# ---------------------------------------------------------------------------------------------

@dataclass
class Run:
    folder: Path
    repo: Path
    branch: str
    base_commit: str

    def save(self) -> None:
        record = {k: str(v) for k, v in asdict(self).items() if k != "folder"}
        (self.folder / RUN_RECORD).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")

    @staticmethod
    def load(folder: Path) -> Run:
        path = folder / RUN_RECORD
        if not path.is_file():
            raise RunError(f"{path} not found: {folder} is not a run folder made by a build")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            return Run(folder=folder, repo=Path(record["repo"]), branch=record["branch"],
                       base_commit=record["base_commit"])
        except (ValueError, KeyError, TypeError) as e:
            raise RunError(f"{path} does not hold a run's record ({e!r})") from None


def git_text(*args: str, cwd: Path) -> str:
    try:
        return git_out(*args, cwd=cwd)
    except LandError as e:
        raise RunError(str(e)) from e


def start_run(agent: str, repo: Path, now: datetime) -> Run:
    """The run folder, for a session that works in the project folder, as given, on its current
    branch. A folder inside a larger git repository stays that folder: the session maps what it was
    pointed at."""
    repo = repo.expanduser().resolve()
    if not repo.is_dir():
        raise RunError(f"{repo} is not a folder")
    base = git_text("rev-parse", "HEAD", cwd=repo)
    runs = repo / ".coyomap" / RUNS_FOLDER
    folder = runs / f"{agent}-{now.strftime('%Y-%m-%d_%H%M%S')}"
    if folder.exists():
        raise RunError(f"{folder} already exists")
    folder.mkdir(parents=True)
    if not (runs / ".gitignore").exists():
        (runs / ".gitignore").write_text("*\n", encoding="utf-8")
    branch = git_text("branch", "--show-current", cwd=repo) or "(no branch)"
    run = Run(folder=folder, repo=repo, branch=branch, base_commit=base)
    run.save()
    return run


def write_status(run: Run, line: str) -> None:
    with (run.folder / STATUS).open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def stamped_session(project: Path) -> str | None:
    """The session the map's provenance names as its newest build, or None."""
    try:
        sessions = json.loads((project / ".coyomap" / "provenance.json").read_text(encoding="utf-8"))["sessions"]
        return str(sessions[-1]["session_id"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def eval_program() -> str:
    """`coyomap-eval`: COYOMAP_EVAL, else this clone's venv, else the main checkout's (a worktree of
    coyomap has no venv of its own), else whatever the PATH finds."""
    named = os.environ.get("COYOMAP_EVAL")
    if named:
        return named
    candidates = [CLONE / ".venv" / "bin" / "coyomap-eval"]
    try:
        candidates.append(main_checkout(CLONE) / ".venv" / "bin" / "coyomap-eval")
    except (LandError, IndexError, OSError):
        pass
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("coyomap-eval") or "coyomap-eval"


def wait_until_quiet(project: Path, wait_seconds: float, poll_seconds: float,
                     sleep: Callable[[float], None] = time.sleep,
                     clock: Callable[[], float] = time.monotonic) -> tuple[str, str]:
    """Ask the retro check until it passes or the wait runs out: ("quiet" | "busy" | "error", the
    check's last message). "error" is a check that could not be run at all."""
    deadline = clock() + wait_seconds
    while True:
        try:
            done = subprocess.run([eval_program(), "retro-precheck", "--repo", str(project)],
                                  capture_output=True, text=True, env=clean_env(os.environ))
        except OSError as e:
            return "error", f"cannot run the retro check ({e})"
        message = (done.stdout + done.stderr).strip()
        if done.returncode == 0:
            return "quiet", message
        if clock() + poll_seconds > deadline:
            return "busy", message
        sleep(poll_seconds)


#: The variables a run passes on from the shell that started it. Nothing else: started from inside
#: an agent's own session (a chat in a desktop app), the environment carries that session's id,
#: its proxy address and its settings, and a session started with them is a child of that chat,
#: not a run of its own. API_KEY variables stay, because they are how some users sign in.
PASSED_ON = ("HOME", "PATH", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "LC_ALL", "TERM")


def clean_env(env: Mapping[str, str], keep: tuple[str, ...] = ()) -> dict[str, str]:
    return {k: v for k, v in env.items() if k in PASSED_ON or k in keep or k.endswith("_API_KEY")}


# ---------------------------------------------------------------------------------------------
# The Claude Code part.
# ---------------------------------------------------------------------------------------------

NESTING_VAR = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"
BG_WAIT_VAR = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"
#: Claude Code's own default, written out so a build does not depend on the default staying >= 2.
DEFAULT_NESTING = "3"
NO_PUSH = "Bash(git push:*)"


def check_nesting(env: Mapping[str, str]) -> None:
    value = env.get(NESTING_VAR)
    if value is None:
        return
    try:
        depth = int(value)
    except ValueError:
        raise RunError(f"{NESTING_VAR}={value!r} is not a number") from None
    if depth < 2:
        raise RunError(f"{NESTING_VAR}={depth}: a build needs at least 2 levels of subagents "
                       f"(the fact-check wave runner starts its own). Unset it or set it to 2 or more.")


def check_skill(env: Mapping[str, str], skill: str, install: str) -> None:
    home = Path(env.get("HOME", str(Path.home())))
    if not (home / ".claude" / "skills" / skill / "SKILL.md").is_file():
        raise RunError(f"the {skill} skill is not installed for Claude Code: run `{install}` in {CLONE}")


def claude_env(env: Mapping[str, str]) -> dict[str, str]:
    """The shell's basics, the nesting setting (the operator's, which was checked, else 3), and the
    wait limit turned off. Never the session, proxy or effort of an agent session this was started
    from."""
    return {NESTING_VAR: DEFAULT_NESTING, **clean_env(env, keep=(NESTING_VAR,)), BG_WAIT_VAR: "0"}


def claude_command(run: Run, prompt: str, model: str | None, effort: str | None,
                   extra_dirs: list[Path]) -> list[str]:
    mcp_config = run.folder / "empty-mcp.json"
    mcp_config.write_text('{"mcpServers":{}}\n', encoding="utf-8")
    command = [os.environ.get("COYOMAP_CLAUDE", "claude"), "-p", prompt,
               "--permission-mode", "auto", "--permission-prompts", "none",
               "--strict-mcp-config", "--mcp-config", str(mcp_config),
               "--disallowed-tools", NO_PUSH,
               "--output-format", "stream-json", "--verbose"]
    for folder in [CLONE, *extra_dirs]:
        command += ["--add-dir", str(folder)]
    if model:
        command += ["--model", model]
    if effort:
        command += ["--effort", effort]
    return command


def run_claude(run: Run, step: str, command: list[str]) -> int:
    print(f"{step}: started in {run.repo}; log {run.folder / (step + '.stream.jsonl')}", flush=True)
    with (run.folder / f"{step}.stream.jsonl").open("w", encoding="utf-8") as out, \
            (run.folder / f"{step}.stderr.log").open("w", encoding="utf-8") as err:
        code = subprocess.run(command, cwd=run.repo, env=claude_env(os.environ),
                              stdout=out, stderr=err).returncode
    write_status(run, f"{step} exit {code}")
    print(f"{step}: exit {code}", flush=True)
    return code


def session_of(stream: Path) -> str | None:
    """The session id a stream-json log carries on its first records."""
    if not stream.is_file():
        return None
    with stream.open(encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("session_id"):
                return str(record["session_id"])
    return None


def build(repo: Path, prompt: str, model: str | None, effort: str | None) -> tuple[Run, int]:
    check_nesting(os.environ)
    check_skill(os.environ, "coyomap", "make install")
    run = start_run("claude", repo, datetime.now())
    print(f"run folder: {run.folder}\nproject: {run.repo}, branch {run.branch} at {run.base_commit[:8]}", flush=True)
    return run, run_claude(run, "build", claude_command(run, prompt, model, effort, []))


def stamped_by_build(run: Run) -> bool:
    """Whether the map was stamped by this run's build session. When it was not, the status file and
    stderr say so."""
    built = session_of(run.folder / "build.stream.jsonl")
    stamped = stamped_session(run.repo)
    if built is not None and stamped == built:
        return True
    reason = (f"the map in {run.repo} was not stamped by this run's build "
              f"(build session {built}, map stamped by {stamped}), so there is no map of this build to retro")
    write_status(run, f"retro skipped: {reason}")
    print(f"retro: skipped, {reason}", file=sys.stderr)
    return False


def retro(run: Run, model: str | None, effort: str | None, wait_seconds: float, poll_seconds: float,
          build_ended: bool) -> int:
    """`build_ended`: the build ran in this process and has exited, so a map it did not stamp will
    never be stamped, and is refused before the wait. A retro started by hand may meet a build that
    is still running and has not stamped yet, so it waits first and checks the stamp after."""
    check_skill(os.environ, "coyomap-retro", "make install-dev")
    if build_ended and not stamped_by_build(run):
        return EXIT_REFUSED
    print("retro: waiting for the build's folder to be quiet", flush=True)
    state, message = wait_until_quiet(run.repo, wait_seconds, poll_seconds)
    if state == "error":
        write_status(run, f"retro skipped: {message}")
        print(f"retro: skipped, {message}. Run `make install-dev` in {CLONE}, or set COYOMAP_EVAL, "
              f"then: make claude-retro RUN={run.folder}", file=sys.stderr)
        return EXIT_REFUSED
    if state == "busy":
        minutes = f"{wait_seconds / 60:g}"
        write_status(run, f"retro skipped: build not quiet after {minutes} min")
        print(f"retro: skipped, the build's folder was not quiet after {minutes} min.\n"
              f"last check: {message}\n"
              f"run it later: make claude-retro RUN={run.folder}", file=sys.stderr)
        return EXIT_WAIT_RAN_OUT
    if not build_ended and not stamped_by_build(run):
        return EXIT_REFUSED
    projects = Path(os.environ.get("HOME", str(Path.home()))) / ".claude" / "projects"
    return run_claude(run, "retro", claude_command(run, RETRO_PROMPT, model, effort, [projects]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude_headless.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    steps = parser.add_subparsers(dest="step", required=True)
    for name in ("build", "retro", "build-retro"):
        sub = steps.add_parser(name)
        if name == "retro":
            sub.add_argument("--run", type=Path, required=True)
        else:
            sub.add_argument("--repo", type=Path, required=True)
            sub.add_argument("--prompt", default=DEFAULT_PROMPT)
        if name != "build":
            sub.add_argument("--wait", type=float, default=DEFAULT_WAIT_MINUTES, help="minutes")
            sub.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
        sub.add_argument("--model", help="last night's: claude-opus-5-5")
        sub.add_argument("--effort", help="last night's: medium")
    args = parser.parse_args(argv)
    try:
        if args.step == "retro":
            return retro(Run.load(args.run.expanduser().resolve()), args.model, args.effort,
                         args.wait * 60, args.poll_seconds, build_ended=False)
        run, code = build(args.repo, args.prompt, args.model, args.effort)
        if args.step == "build":
            return code
        retro_code = retro(run, args.model, args.effort, args.wait * 60, args.poll_seconds, build_ended=True)
        return code or retro_code
    except RunError as e:
        print(f"refused: {e}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
