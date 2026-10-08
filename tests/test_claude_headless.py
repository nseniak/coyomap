"""Tests for `tools/claude_headless.py`, the headless build and retro. They spend no tokens.

COYOMAP_CLAUDE points at a fake claude that records its argv, its folder, its environment and the
branch it found, and plays a build: it prints the session id the way stream-json does and, when
asked, stamps the map's provenance with it. COYOMAP_EVAL points at a fake retro check that refuses
a set number of times. HOME is a throwaway folder holding the two skills and `fake.json`, which
tells the fakes what to do: the script passes on only a few variables, so the fakes cannot be
told through the environment.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "claude_headless.py"
NO_PUSH = "Bash(git push:*)"

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
fake = json.loads((Path(os.environ["HOME"]) / "fake.json").read_text())
cwd = Path.cwd()
log = Path(fake["FAKE_PRECHECK_LOG"])
record = {
    "argv": sys.argv[1:], "cwd": str(cwd),
    "bg_wait": os.environ.get("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"),
    "nesting": os.environ.get("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"),
    "env": sorted(os.environ),
    "branch": subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True).stdout.strip(),
    "prechecks": log.read_text().splitlines() if log.exists() else [],
}
with open(fake["FAKE_CLAUDE_LOG"], "a") as f:
    f.write(json.dumps(record) + "\n")
session = fake.get("FAKE_SESSION", "s-build")
print(json.dumps({"type": "system", "subtype": "init", "session_id": session}))
if sys.argv[2] != "/coyomap-retro" and fake.get("FAKE_STAMP") == "1":
    (cwd / ".coyomap").mkdir(exist_ok=True)
    (cwd / ".coyomap" / "project-map.json").write_text("{}")
    (cwd / ".coyomap" / "provenance.json").write_text(json.dumps({"sessions": [{"session_id": session}]}))
retro_run = sys.argv[2] == "/coyomap-retro"
sys.exit(int(fake.get("FAKE_RETRO_EXIT" if retro_run and "FAKE_RETRO_EXIT" in fake else "FAKE_EXIT", "0")))
'''

FAKE_PRECHECK = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
fake = json.loads((Path(os.environ["HOME"]) / "fake.json").read_text())
log = Path(fake["FAKE_PRECHECK_LOG"])
calls = len(log.read_text().splitlines()) if log.exists() else 0
refusals = int(fake.get("FAKE_REFUSALS", "0"))
with open(fake["FAKE_PRECHECK_ENV"], "w") as f:
    f.write(json.dumps(sorted(os.environ)))
ok = refusals >= 0 and calls >= refusals
with log.open("a") as f:
    f.write(("OK " if ok else "REFUSED ") + " ".join(sys.argv[1:]) + "\n")
print("retro-precheck: " + ("OK" if ok else "REFUSED - .coyomap/x written 5s ago"))
sys.exit(0 if ok else 1)
'''


def make_root() -> Path:
    """A throwaway folder, resolved: macOS hands out /var/..., which git and the script see as /private/var/..."""
    return Path(tempfile.mkdtemp(prefix="headless-")).resolve()


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


def make_program(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def make_repo(root: Path) -> Path:
    """A repo with one commit, whose committed map was stamped by an older session, and a bare
    remote as its origin."""
    repo = root / "project"
    repo.mkdir()
    run(["git", "init", "-q", "-b", "main"], repo)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        run(["git", "config", key, value], repo)
    (repo / ".coyomap").mkdir()
    (repo / ".coyomap" / "provenance.json").write_text(json.dumps({"sessions": [{"session_id": "s-old"}]}))
    (repo / "a.txt").write_text("one\n")
    run(["git", "add", "."], repo)
    run(["git", "commit", "-qm", "one"], repo)
    remote = root / "remote.git"
    run(["git", "init", "-q", "--bare", str(remote)], root)
    run(["git", "remote", "add", "origin", str(remote)], repo)
    return repo


def make_home(root: Path, skills: tuple[str, ...] = ("coyomap", "coyomap-retro")) -> Path:
    home = root / "home"
    home.mkdir()
    for skill in skills:
        (home / ".claude" / "skills" / skill).mkdir(parents=True)
        (home / ".claude" / "skills" / skill / "SKILL.md").write_text("skill\n")
    return home


def make_env(root: Path, **fake: str) -> dict[str, str]:
    """The environment the script starts with, and in HOME the fakes' instructions: each keyword
    whose name starts with FAKE_ goes to `fake.json`, any other to the environment."""
    programs = root / "programs"
    programs.mkdir(exist_ok=True)
    home = make_home(root) if not (root / "home").exists() else root / "home"
    settings = {"FAKE_CLAUDE_LOG": str(root / "claude.log"), "FAKE_PRECHECK_LOG": str(root / "precheck.log"),
                "FAKE_PRECHECK_ENV": str(root / "precheck.env"), "FAKE_STAMP": "1"}
    settings.update({k: v for k, v in fake.items() if k.startswith("FAKE_")})
    (home / "fake.json").write_text(json.dumps(settings))
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_")}
    env.update({"HOME": str(home),
                "COYOMAP_CLAUDE": str(make_program(programs, "claude", FAKE_CLAUDE)),
                "COYOMAP_EVAL": str(make_program(programs, "coyomap-eval", FAKE_PRECHECK))})
    env.update({k: v for k, v in fake.items() if not k.startswith("FAKE_")})
    return env


def headless(root: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=root, env=env,
                          capture_output=True, text=True, timeout=60)


def claude_calls(root: Path) -> list[dict[str, object]]:
    log = root / "claude.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def run_folders(root: Path) -> list[Path]:
    runs = root / "project" / ".coyomap" / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []


def status_lines(folder: Path) -> list[str]:
    return (folder / "status").read_text().splitlines()


def build_retro(root: Path, env: dict[str, str], wait_minutes: str = "1") -> subprocess.CompletedProcess[str]:
    return headless(root, env, "build-retro", "--repo", str(root / "project"),
                    "--wait", wait_minutes, "--poll-seconds", "0.05")


def test_build_runs_claude_in_the_project_folder_on_its_branch_with_the_headless_flags() -> None:
    root = make_root()
    repo = make_repo(root)
    run(["git", "checkout", "-q", "-b", "work"], repo)
    done = headless(root, make_env(root), "build", "--repo", str(repo),
                    "--model", "claude-opus-5-5", "--effort", "medium")
    assert done.returncode == 0, done.stderr
    [folder] = run_folders(root)
    assert folder.name.startswith("claude-20")
    [call] = claude_calls(root)
    argv = call["argv"]
    assert isinstance(argv, list)
    assert argv[:2] == ["-p", "/coyomap build a new map from scratch"]
    for flag in (["--permission-mode", "auto"], ["--permission-prompts", "none"],
                 ["--mcp-config", str(folder / "empty-mcp.json")], ["--disallowed-tools", NO_PUSH],
                 ["--output-format", "stream-json"], ["--model", "claude-opus-5-5"], ["--effort", "medium"],
                 ["--add-dir", str(SCRIPT.parent.parent)]):
        i = argv.index(flag[0])
        assert argv[i:i + 2] == flag
    assert "--strict-mcp-config" in argv and "--verbose" in argv
    assert json.loads((folder / "empty-mcp.json").read_text()) == {"mcpServers": {}}
    assert call["bg_wait"] == "0"
    # Claude ran in the project folder itself, on the branch checked out there, and no branch was added.
    assert call["cwd"] == str(repo) and call["branch"] == "work"
    record = json.loads((folder / "run.json").read_text())
    assert record["repo"] == str(repo) and record["branch"] == "work"
    assert run(["git", "branch", "--format=%(refname:short)"], repo).stdout.split() == ["main", "work"]
    assert not (folder / "repo").exists()
    assert record["base_commit"] == run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    assert status_lines(folder) == ["build exit 0"]
    assert '"session_id": "s-build"' in (folder / "build.stream.jsonl").read_text()


def test_build_passes_no_model_or_effort_unless_given() -> None:
    root = make_root()
    headless(root, make_env(root), "build", "--repo", str(make_repo(root)))
    [call] = claude_calls(root)
    argv = call["argv"]
    assert isinstance(argv, list)
    assert "--model" not in argv and "--effort" not in argv


def test_build_writes_the_claude_exit_code_into_the_status_file() -> None:
    root = make_root()
    done = headless(root, make_env(root, FAKE_EXIT="7"), "build", "--repo", str(make_repo(root)))
    assert done.returncode == 7
    [folder] = run_folders(root)
    assert status_lines(folder) == ["build exit 7"]


def test_build_refuses_nesting_below_two_levels() -> None:
    for value in ("0", "1", "x"):
        root = make_root()
        done = headless(root, make_env(root, CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=value), "build",
                        "--repo", str(make_repo(root)))
        assert done.returncode == 1
        assert "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH" in done.stderr
        assert claude_calls(root) == [] and run_folders(root) == []


def test_build_accepts_nesting_of_two_levels() -> None:
    root = make_root()
    done = headless(root, make_env(root, CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH="2"), "build",
                    "--repo", str(make_repo(root)))
    assert done.returncode == 0, done.stderr


def test_build_refuses_without_the_coyomap_skill() -> None:
    root = make_root()
    make_home(root, skills=())
    done = headless(root, make_env(root), "build", "--repo", str(make_repo(root)))
    assert done.returncode == 1 and "make install" in done.stderr
    assert claude_calls(root) == []


def test_nothing_is_pushed() -> None:
    root = make_root()
    make_repo(root)
    build_retro(root, make_env(root))
    assert run(["git", "ls-remote", "--heads", str(root / "remote.git")], root).stdout == ""
    for call in claude_calls(root):
        argv = call["argv"]
        assert isinstance(argv, list)
        assert argv[argv.index("--disallowed-tools") + 1] == NO_PUSH


def test_build_retro_waits_for_the_check_before_the_retro() -> None:
    root = make_root()
    repo = make_repo(root)
    done = build_retro(root, make_env(root, FAKE_REFUSALS="2"))
    assert done.returncode == 0, done.stderr
    [folder] = run_folders(root)
    build_call, retro_call = claude_calls(root)
    argv = retro_call["argv"]
    assert isinstance(argv, list)
    assert argv[:2] == ["-p", "/coyomap-retro"]
    assert str(root / "home" / ".claude" / "projects") in argv
    assert retro_call["cwd"] == str(repo)
    # The check had passed when the retro's claude started.
    prechecks = retro_call["prechecks"]
    assert isinstance(prechecks, list) and len(prechecks) == 3
    assert prechecks[-1] == f"OK retro-precheck --repo {repo}"
    assert build_call["prechecks"] == []
    assert status_lines(folder) == ["build exit 0", "retro exit 0"]


def test_retro_still_runs_after_a_failed_build_that_stamped_its_map() -> None:
    root = make_root()
    make_repo(root)
    done = build_retro(root, make_env(root, FAKE_EXIT="1"))
    [folder] = run_folders(root)
    assert len(claude_calls(root)) == 2
    assert status_lines(folder) == ["build exit 1", "retro exit 1"]
    assert done.returncode == 1


def test_retro_gives_up_when_the_build_never_goes_quiet() -> None:
    root = make_root()
    make_repo(root)
    done = build_retro(root, make_env(root, FAKE_REFUSALS="-1"), wait_minutes="0.005")
    assert done.returncode == 3
    [folder] = run_folders(root)
    assert len(claude_calls(root)) == 1
    assert status_lines(folder) == ["build exit 0", "retro skipped: build not quiet after 0.005 min"]
    assert "written 5s ago" in done.stderr and f"make claude-retro RUN={folder}" in done.stderr
    assert len((root / "precheck.log").read_text().splitlines()) >= 2


def test_retro_refuses_a_map_this_build_did_not_stamp() -> None:
    root = make_root()
    make_repo(root)
    done = build_retro(root, make_env(root, FAKE_STAMP="0", FAKE_EXIT="1"))
    assert done.returncode == 1
    [folder] = run_folders(root)
    assert len(claude_calls(root)) == 1
    assert not (root / "precheck.log").exists()
    [_, skipped] = status_lines(folder)
    assert skipped.startswith("retro skipped:") and "s-old" in skipped


def test_retro_by_hand_waits_first_then_checks_the_stamp() -> None:
    root = make_root()
    repo = make_repo(root)
    env = make_env(root)
    headless(root, env, "build", "--repo", str(repo))
    [folder] = run_folders(root)
    env = make_env(root, FAKE_REFUSALS="1")
    done = headless(root, env, "retro", "--run", str(folder), "--poll-seconds", "0.05")
    assert done.returncode == 0, done.stderr
    assert len((root / "precheck.log").read_text().splitlines()) == 2
    assert status_lines(folder) == ["build exit 0", "retro exit 0"]


def test_retro_refuses_a_folder_that_is_not_a_run() -> None:
    root = make_root()
    done = headless(root, make_env(root), "retro", "--run", str(root))
    assert done.returncode == 1 and "run.json" in done.stderr
    assert claude_calls(root) == []


def test_the_session_gets_none_of_the_chat_it_was_started_from() -> None:
    """Started from a chat in a desktop app, the environment carries that chat's session id, proxy
    address and effort. The review of 2026-10-08 saw all three reach the session; a session started
    with them is a child of the chat, and its map is stamped with the chat's id."""
    root = make_root()
    parent = {"CLAUDE_CODE_SESSION_ID": "s-parent-chat", "CLAUDECODE": "1", "CLAUDE_EFFORT": "max",
              "ANTHROPIC_BASE_URL": "http://127.0.0.1:1/proxy", "CLAUDE_CODE_SESSION_ATTENDED": "1",
              "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "3", "ANTHROPIC_API_KEY": "key-for-a-test"}
    make_repo(root)
    done = build_retro(root, make_env(root, **parent))
    assert done.returncode == 0, done.stderr
    for call in claude_calls(root):
        env = call["env"]
        assert isinstance(env, list)
        for name in ("CLAUDE_CODE_SESSION_ID", "CLAUDECODE", "CLAUDE_EFFORT", "ANTHROPIC_BASE_URL",
                     "CLAUDE_CODE_SESSION_ATTENDED", "COYOMAP_CLAUDE", "COYOMAP_EVAL"):
            assert name not in env, f"{name} reached the session"
        for name in ("HOME", "PATH", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", "ANTHROPIC_API_KEY",
                     "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"):
            assert name in env, f"{name} did not reach the session"
    precheck_env = json.loads((root / "precheck.env").read_text())
    assert "CLAUDE_CODE_SESSION_ID" not in precheck_env


def test_a_build_that_failed_fails_the_build_retro_command() -> None:
    """A build that exited 1 but stamped its map, then a retro that exits 0: the command must not
    exit 0, or a night's failure shows only in the status file."""
    root = make_root()
    make_repo(root)
    done = build_retro(root, make_env(root, FAKE_EXIT="5", FAKE_RETRO_EXIT="0"))
    [folder] = run_folders(root)
    assert status_lines(folder) == ["build exit 5", "retro exit 0"]
    assert done.returncode == 5


def test_retro_refuses_a_build_log_with_no_session() -> None:
    root = make_root()
    make_repo(root)
    env = make_env(root)
    headless(root, env, "build", "--repo", str(root / "project"))
    [folder] = run_folders(root)
    (folder / "build.stream.jsonl").write_text("")
    (root / "project" / ".coyomap" / "provenance.json").unlink()
    done = headless(root, env, "retro", "--run", str(folder), "--poll-seconds", "0.05")
    assert done.returncode == 1
    assert status_lines(folder)[-1].startswith("retro skipped: the map")
    assert len(claude_calls(root)) == 1


def test_retro_says_so_when_the_retro_check_cannot_run() -> None:
    root = make_root()
    make_repo(root)
    done = build_retro(root, make_env(root, COYOMAP_EVAL=str(root / "no-such-program")))
    assert done.returncode == 1
    assert "Traceback" not in done.stderr and "make install-dev" in done.stderr, done.stderr
    [folder] = run_folders(root)
    assert status_lines(folder)[-1].startswith("retro skipped: cannot run the retro check")


def test_retro_refuses_a_broken_run_record() -> None:
    root = make_root()
    (root / "run.json").write_text('{"repo": "/x"}')
    done = headless(root, make_env(root), "retro", "--run", str(root))
    assert done.returncode == 1 and "Traceback" not in done.stderr, done.stderr
    assert "does not hold a run's record" in done.stderr


def test_build_runs_in_the_folder_given_inside_a_larger_repo() -> None:
    root = make_root()
    repo = make_repo(root)
    (repo / "pkg").mkdir()
    done = headless(root, make_env(root), "build", "--repo", str(repo / "pkg"))
    assert done.returncode == 0, done.stderr
    assert (repo / "pkg" / ".coyomap" / "runs").is_dir()
    [call] = claude_calls(root)
    assert call["cwd"] == str(repo / "pkg")


def test_nesting_is_set_to_three_when_the_operator_left_it_unset() -> None:
    root = make_root()
    make_repo(root)
    headless(root, make_env(root), "build", "--repo", str(root / "project"))
    [call] = claude_calls(root)
    assert call["nesting"] == "3"
    root = make_root()
    make_repo(root)
    headless(root, make_env(root, CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH="5"), "build",
             "--repo", str(root / "project"))
    [call] = claude_calls(root)
    assert call["nesting"] == "5"


def test_run_folders_go_in_the_projects_map_folder_and_git_ignores_them() -> None:
    root = make_root()
    repo = make_repo(root)
    done = headless(root, make_env(root), "build", "--repo", str(repo))
    assert done.returncode == 0, done.stderr
    [folder] = sorted(p for p in (repo / ".coyomap" / "runs").iterdir() if p.is_dir())
    assert folder.name.startswith("claude-20")
    assert (folder / "status").read_text() == "build exit 0\n"
    untracked = run(["git", "status", "--porcelain", "--untracked-files=all"], repo).stdout
    assert "runs/" not in untracked, untracked
    assert not (root / "home" / "coyomap-runs").exists()
