#!/usr/bin/env python3
"""Tests for `coyomap findings` — what the agents noticed about the product, filed by each one.

The channel this replaces was the agents' closing reports, read back out of their transcripts: on
the 2026-10-07 mcpolis build that reader saw 0 of 126 hand-backs, and the lead collected 57 findings
by hand. These tests hold the three properties that make a file better than a report: a finding is
on disk the moment it is filed, no two agents share a writer, and the lead reads ONE line.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_findings.py
    pytest tests/test_findings.py
"""
from __future__ import annotations

import contextlib
import io
import json
import multiprocessing
import tempfile
from multiprocessing.synchronize import Barrier
from pathlib import Path

from coyomap import buildstate, findings
from coyomap.credentials import REDACTED

#: A credential shape `credentials.redact` replaces, assembled so this file holds no literal one.
FAKE_KEY = "gh" + "p_" + "A1b2C3d4" * 5


def make_repo(td: str, name: str = "repo") -> Path:
    """A repo being mapped: two source files an agent can point at, and its `.coyomap/` folder."""
    repo = Path(td) / name
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "auth.py").write_text("def check(user):\n    return True\n", encoding="utf-8")
    (repo / "src" / "routes.py").write_text("ROUTES = ['/admin']\n", encoding="utf-8")
    (repo / ".coyomap").mkdir()
    return repo


def make_add_argv(repo: Path, agent: str = "harvest-3", kind: str = "risk",
                  where: tuple[str, ...] = ("src/auth.py:2",),
                  text: str = "check() lets every user through, so the admin route has no guard.",
                  ) -> list[str]:
    argv = ["add", "--repo", str(repo), "--agent", agent, "--kind", kind, "--text", text]
    for w in where:
        argv += ["--where", w]
    return argv


def run_findings(argv: list[str]) -> tuple[int, str, str]:
    """`coyomap findings …` in-process: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = findings.main(argv)
    return code, out.getvalue(), err.getvalue()


def make_filed(repo: Path, rows: list[tuple[str, str, str]]) -> None:
    """File `(agent, kind, text)` findings at `src/auth.py:1`, through the real command."""
    for agent, kind, text in rows:
        code, _out, err = run_findings(make_add_argv(repo, agent=agent, kind=kind,
                                                     where=("src/auth.py:1",), text=text))
        assert code == 0, err


def lines_of(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# --- add ------------------------------------------------------------------------------------------

def test_add_writes_one_line_to_the_agents_own_file() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        code, out, err = run_findings(make_add_argv(repo, where=("./src/auth.py:2",
                                                                 "src/routes.py:1-1")))
        assert code == 0, err
        own = repo / ".coyomap" / "findings" / "harvest-3.jsonl"
        rows = [json.loads(ln) for ln in lines_of(own)]
        assert [sorted(r) for r in rows] == [["agent", "at", "kind", "text", "where"]], rows
        assert rows[0]["agent"] == "harvest-3" and rows[0]["kind"] == "risk", rows
        assert rows[0]["where"] == ["src/auth.py:2", "src/routes.py:1-1"], rows
        # its own file and no other: a second agent never writes into it
        assert [p.name for p in own.parent.iterdir()] == ["harvest-3.jsonl"]
        assert "FILED" in out and "which now holds 1 line(s)" in out, out
        # a second finding by the same agent is a second line of the same file
        assert run_findings(make_add_argv(repo, kind="gap"))[0] == 0
        assert len(lines_of(own)) == 2


def test_add_reports_every_fault_at_once_and_writes_nothing() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        code, _out, err = run_findings(["add", "--repo", str(repo), "--agent", "bad/id",
                                        "--kind", "worry", "--text", "x" * 601])
        assert code == 2, err
        assert "REFUSED — 4 fault(s)" in err, err
        for said in ("--agent 'bad/id' is not an agent id", "--kind 'worry' is not one of",
                     "no --where", "over 600"):
            assert said in err, (said, err)
        assert not (repo / ".coyomap" / "findings").exists(), "a refused finding wrote something"
        # an empty text is a fault of its own
        code, _out, err = run_findings(make_add_argv(repo, text="   "))
        assert code == 2 and "no --text" in err, err


def test_add_refuses_a_where_outside_the_repo_or_naming_no_file() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        (Path(td) / "outside.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "src" / "escape.py").symlink_to(Path(td) / "outside.py")
        for where, said in ((str(repo / "src" / "auth.py") + ":1", "is absolute"),
                            ("../outside.py:1", "holds `..`"),
                            ("src/missing.py:3", "names no file"),
                            ("src", "names no file"),
                            ("src/escape.py:1", "names no file"),
                            ("src/auth.py:abc", "is not <path>[:<line>[-<line>]]"),
                            ("src/auth.py:5-2", "ends before it starts")):
            code, _out, err = run_findings(make_add_argv(repo, where=(where,)))
            assert code == 2 and said in err, (where, err)
        assert not (repo / ".coyomap" / "findings").exists()
        # a repo that is not being mapped is refused too, before any --where is believed
        bare = Path(td) / "bare"
        bare.mkdir()
        code, _out, err = run_findings(make_add_argv(bare))
        assert code == 2 and "has no .coyomap/ folder" in err, err


def test_add_refuses_a_byte_that_is_not_utf8_instead_of_failing() -> None:
    """A byte the shell could not decode reaches Python as a lone surrogate, which no UTF-8 file
    can hold: `add` names it as a fault, and writes nothing, rather than ending in a traceback."""
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        code, out, err = run_findings(make_add_argv(repo, text="check() in caf\udce9.py lets anyone in"))
        where = run_findings(make_add_argv(repo, where=("src/caf\udce9.py:1",)))
        written = (repo / ".coyomap" / "findings").exists()
    assert code == 2 and not out, (out, err)
    assert "REFUSED — 1 fault(s)" in err and "--text holds a byte that is not UTF-8" in err, err
    assert where[0] == 2 and "--where 'src/caf\\udce9.py:1' holds a byte that is not UTF-8" in where[2]
    assert not written, "a refused finding wrote something"


def test_add_replaces_a_credential_shaped_value() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        code, _out, err = run_findings(make_add_argv(
            repo, text=f"the deploy script prints {FAKE_KEY} into its log"))
        assert code == 0, err
        raw = (repo / ".coyomap" / "findings" / "harvest-3.jsonl").read_text(encoding="utf-8")
        assert FAKE_KEY not in raw, raw
        assert REDACTED in json.loads(raw)["text"], raw


def _file_many(repo: str, agent: str, tag: str, n: int, barrier: Barrier) -> None:
    """One agent of the concurrency test: wait for the others, then file `n` findings."""
    barrier.wait()
    for k in range(n):
        findings.add(Path(repo), agent, "gap", ["src/auth.py:1"], f"{tag} finding {k:03d}")


def test_agents_filing_at_once_lose_nothing() -> None:
    """Three agents at once, and two processes on ONE agent's file: no line lost or torn."""
    ctx = multiprocessing.get_context("spawn")
    writers = (("harvest-1", "a"), ("harvest-2", "b"), ("skeptic-1", "c"), ("skeptic-1", "d"))
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        barrier = ctx.Barrier(len(writers))
        procs = [ctx.Process(target=_file_many, args=(str(repo), agent, tag, 50, barrier))
                 for agent, tag in writers]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
        codes = [p.exitcode for p in procs]
        filed = findings.load(repo)
    assert codes == [0] * len(writers), codes
    assert not filed.malformed, filed.malformed
    assert len(filed.findings) == 200, len(filed.findings)
    for agent, tag in writers:
        mine = [f.text for f in filed.findings if f.agent == agent and f.text.startswith(tag)]
        assert mine == [f"{tag} finding {k:03d}" for k in range(50)], f"{agent}/{tag} lost a line"


# --- collect --------------------------------------------------------------------------------------

def test_collect_leads_with_one_line_and_counts_by_kind() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        make_filed(repo, [("harvest-1", "risk", "one"), ("harvest-1", "bug", "two"),
                          ("trace-2", "risk", "three"), ("trace-2", "contradiction", "four")])
        code, out, err = run_findings(["collect", "--repo", str(repo)])
    assert code == 0, err
    assert out.splitlines() == [
        "FINDINGS — 4 from 2 agent(s): risk 2 · bug 1 · gap 0 · contradiction 1 "
        "(+4 since the last collect) · 0 malformed → .coyomap/findings-report.md"], out


def test_collect_writes_the_whole_list_and_counts_the_new() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        make_filed(repo, [("harvest-1", "risk", "the admin route has no guard"),
                          ("harvest-1", "gap", "no test covers the refund path")])
        assert run_findings(["collect", "--repo", str(repo)])[0] == 0
        make_filed(repo, [("trace-2", "bug", "the retry sends the email twice"),
                          # a retried agent files the same finding again: a repeat, not a new one
                          ("harvest-1", "risk", "the admin route has no guard")])
        code, out, _err = run_findings(["collect", "--repo", str(repo)])
        report = (repo / ".coyomap" / "findings-report.md").read_text(encoding="utf-8")
    assert code == 0 and "3 from 2 agent(s)" in out and "(+1 since the last collect)" in out, out
    assert report.startswith("# Agent findings — 3 from 2 agent(s)"), report[:200]
    sections = [ln for ln in report.splitlines() if ln.startswith("## ")]
    assert sections == ["## risk (1)", "## bug (1)", "## gap (1)", "## contradiction (0)"], sections
    for said in ("the admin route has no guard", "the retry sends the email twice",
                 "no test covers the refund path", "`src/auth.py:1`", "(trace-2, ",
                 "+1 since the last collect, 1 exact repeat(s) dropped"):
        assert said in report, (said, report)
    assert report.index("the admin route") < report.index("the retry sends")


def test_collect_keeps_the_good_lines_beside_a_malformed_one() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        make_filed(repo, [("harvest-1", "risk", "the admin route has no guard")])
        own = repo / ".coyomap" / "findings" / "harvest-1.jsonl"
        with own.open("a", encoding="utf-8") as fh:
            fh.write("{not json\n")
            fh.write(json.dumps({"agent": "someone-else", "kind": "bug", "where": ["src/a.py"],
                                 "text": "t", "at": ""}) + "\n")
        make_filed(repo, [("harvest-1", "bug", "the retry sends the email twice")])
        code, out, _err = run_findings(["collect", "--repo", str(repo)])
        report = (repo / ".coyomap" / "findings-report.md").read_text(encoding="utf-8")
    assert code == 0, out
    assert "2 from 1 agent(s): risk 1 · bug 1" in out and "· 2 malformed →" in out, out
    assert "## malformed lines (2)" in report, report
    assert "harvest-1.jsonl:2: not JSON" in report, report
    assert "harvest-1.jsonl:3: its agent is 'someone-else'" in report, report
    assert "the retry sends the email twice" in report, "a line after a bad one was dropped"


def test_collect_with_nothing_filed_says_none() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        code, out, err = run_findings(["collect", "--repo", str(repo)])
        assert code == 0, err
        assert out.splitlines() == ["FINDINGS — none filed"], out
        # a folder that is not a mapped repo is not "none filed": it is the wrong folder
        bare = Path(td) / "bare"
        bare.mkdir()
        code, out, err = run_findings(["collect", "--repo", str(bare)])
        assert code == 2 and "has no .coyomap/ folder" in err and not out, (out, err)


def test_collect_appends_its_line_to_an_open_state() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        make_filed(repo, [("harvest-1", "risk", "the admin route has no guard")])
        # no state open: the collect still answers, and writes no state of its own
        assert run_findings(["collect", "--repo", str(repo)])[0] == 0
        assert buildstate.read_state(repo) is None
        buildstate.start(repo)
        code, out, _err = run_findings(["collect", "--repo", str(repo)])
        state = buildstate.read_state(repo)
    assert code == 0 and state is not None
    line = state.last("findings")
    assert line is not None and line.text == out.strip(), (line, out)
    assert "(+0 since the last collect)" in line.text, line


def test_a_bad_argument_is_answered_with_the_verbs_own_usage() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        code, out, err = run_findings(["collect", "--repo", str(repo), "--bogus"])
        report = (repo / ".coyomap" / "findings-report.md").exists()
    assert code == 2 and not out, (out, err)
    assert err.startswith("ERROR: unrecognized arguments: --bogus\n"), err
    assert "  collect [--repo <repo>]" in err and "  add --repo" not in err, err
    assert not report, "a refused collect wrote its report"


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("findings tests passed")


# --- withdraw (retro mcpolis-2026-10-08-#18) -----------------------------------------------------
# An agent saw one of its findings was wrong and could only say so in prose; the finding shipped in
# the report, half retracted. `withdraw` takes it back and keeps the record of both.

def test_add_prints_the_id_withdraw_takes() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        make_filed(repo, [("harvest-1", "risk", "first")])
        code, out, err = run_findings(make_add_argv(repo, agent="harvest-1", text="second"))
    assert code == 0, err
    assert " as harvest-1#2 → " in out, out


def test_withdraw_keeps_the_finding_and_its_reason_and_collect_counts_it_no_more() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        make_filed(repo, [("harvest-1", "risk", "the admin route has no guard"),
                          ("harvest-1", "bug", "the retry sends the email twice")])
        own = repo / ".coyomap" / "findings" / "harvest-1.jsonl"
        before = lines_of(own)
        code, out, err = run_findings(["withdraw", "--repo", str(repo), "harvest-1#1",
                                       "--why", "the guard sits in the middleware, line 40"])
        assert code == 0, err
        assert "WITHDRAWN — harvest-1#1" in out, out
        after = lines_of(own)
        assert after[:2] == before, "a withdrawal deletes nothing"
        assert json.loads(after[2])["withdraws"] == 1, after
        # a retried agent filing the same finding again does not bring it back
        make_filed(repo, [("harvest-1", "risk", "the admin route has no guard")])
        code, out, _err = run_findings(["collect", "--repo", str(repo)])
        report = (repo / ".coyomap" / "findings-report.md").read_text(encoding="utf-8")
    assert code == 0, out
    assert "1 from 1 agent(s): risk 0 · bug 1" in out and "· 1 withdrawn ·" in out, out
    assert "## withdrawn (1)" in report, report
    gone = report[report.index("## withdrawn"):]
    assert "[harvest-1#1]" in gone and "the admin route has no guard" in gone, gone
    assert "WITHDRAWN: the guard sits in the middleware, line 40" in gone, gone
    assert "[harvest-1#2]" in report[:report.index("## withdrawn")], report


def test_withdraw_refuses_every_fault_at_once_and_writes_nothing() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(td)
        make_filed(repo, [("harvest-1", "risk", "the admin route has no guard")])
        own = repo / ".coyomap" / "findings" / "harvest-1.jsonl"
        before = own.read_text(encoding="utf-8")
        code, _out, err = run_findings(["withdraw", "--repo", str(repo), "harvest-1#7"])
        assert code == 2, err
        assert "REFUSED — 2 fault(s)" in err and "line 7 of harvest-1.jsonl is no finding" in err
        assert "no --why" in err, err
        for bad in ("harvest-1", "nobody#1"):
            code, _out, err = run_findings(["withdraw", "--repo", str(repo), bad, "--why", "x"])
            assert code == 2, (bad, err)
        assert own.read_text(encoding="utf-8") == before, "a refused withdrawal wrote something"
        # once withdrawn, a second withdrawal is refused
        assert run_findings(["withdraw", "--repo", str(repo), "harvest-1#1", "--why", "x"])[0] == 0
        code, _out, err = run_findings(["withdraw", "--repo", str(repo), "harvest-1#1",
                                        "--why", "y"])
        assert code == 2 and "already withdrawn" in err, err
