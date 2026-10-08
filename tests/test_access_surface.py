#!/usr/bin/env python3
"""`coyomap access-surface` + `finalize --access-baseline` — a security claim that disappeared.

A from-scratch rebuild is deliberately blind to its predecessor, and that independence is the point.
The cost is that a claim can vanish between two maps of UNCHANGED code with nothing noticing. On the
2026-08-20 argus pair the access-rule statement count held at 21 -> 21, so `auth-surfaces-no-drop`
passed, while `adapters/auth_google.py` — which verifies the Google ID token's signature, issuer and
audience — lost its claim entirely: the previous map carried it as access rule BR21, and none of the
new map's 61 rules mentions a signature, an issuer or an audience.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from coyomap.access_surface import access_files, load_surface, lost_files, write_surface
from coyomap.grounding import unopened
from coyomap.provenance import session_transcript
from coyomap.assemble import load_map_or_fragment


def _map(rules: list[dict[str, object]]) -> dict[str, object]:
    return {"format": "coyomap-map", "title": "t", "goal": "g", "commit": "abc1234",
            "rules": rules}


def _rule(rid: str, statement: str, sites: list[str], access: bool = True) -> dict[str, object]:
    return {"id": rid, "statement": statement, "access": access, "risk": "impersonation",
            "sites": [{"where": w, "why": "enforces it"} for w in sites]}


def _model(doc: dict[str, object]):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "m.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        m, _present = load_map_or_fragment(p)
    return m


def test_the_surface_is_files_not_statements() -> None:
    """Statements are LLM prose and drift between builds with no change in meaning; a line moves when
    the code above it moves. A file that lost its coverage is the signal that survives both."""
    m = _model(_map([_rule("BR1", "Only a proven identity", ["a/auth.py:67", "a/auth.py:73"]),
                     _rule("BR2", "Owner scoping", ["b/store.py:18"])]))
    assert access_files(m) == {"a/auth.py": ["BR1"], "b/store.py": ["BR2"]}


def test_a_non_access_rule_is_not_part_of_the_auth_surface() -> None:
    m = _model(_map([_rule("BR1", "A plan cap", ["c/plan.py:9"], access=False)]))
    assert access_files(m) == {}


def test_a_file_that_lost_its_only_access_rule_is_named() -> None:
    before = _model(_map([_rule("BR21", "Only a proven upstream identity", ["a/auth_google.py:67"]),
                          _rule("BR2", "Owner scoping", ["b/store.py:18"])]))
    after = _model(_map([_rule("BR7", "Owner scoping, reworded", ["b/store.py:20"])]))
    assert lost_files(access_files(before), after) == ["a/auth_google.py"]


def test_a_rewording_or_a_moved_line_in_the_same_file_is_not_a_loss() -> None:
    """Two independent LLM builds legitimately reword and re-anchor. Only a whole file going
    unclaimed is reported, or the check would fire on every rebuild and be ignored."""
    before = _model(_map([_rule("BR1", "Only a proven identity", ["a/auth.py:67"])]))
    after = _model(_map([_rule("BR9", "An identity counts only once proven", ["a/auth.py:120"])]))
    assert lost_files(access_files(before), after) == []


def test_a_surface_file_and_a_whole_map_are_both_accepted_as_the_baseline() -> None:
    """Every archive already holds a map; requiring a pre-conversion is the friction that leaves a
    check unrun."""
    doc = _map([_rule("BR1", "Only a proven identity", ["a/auth.py:67"])])
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        map_path = tmp / "m.json"
        map_path.write_text(json.dumps(doc), encoding="utf-8")
        surface_path = tmp / "s.json"
        write_surface(_model(doc), surface_path)
        assert load_surface(map_path) == load_surface(surface_path) == {"a/auth.py": ["BR1"]}


# --- a lost file is shown with the claim it held (retro 2026-09-30 mcpolis, finding 2) ----------
# The access-baseline leg named 17 paths and nothing else. The lead opened none of them and wrote
# 11 reasons from the NEW map; 5 answered a different claim than the one lost, and four old access
# rules left the map outright. A path is not a question; the claim it held is.

_BEFORE = _map([_rule("BR61", "Every stored record carries its team", ["a/store.py:42"]),
                _rule("BR7", "Owner scoping", ["b/owner.py:18"])])
_AFTER = _map([_rule("BR9", "Owner scoping, reworded", ["b/owner.py:20"])])


def make_baseline_pair(td: Path, after: dict[str, object] | None = None) -> tuple[Path, Path]:
    """`(previous map, current map)` written under `td`, the current one as `.coyomap/project-map.json`
    with an archive beside it, the way `coyomap-eval archive` leaves a repo."""
    out = td / ".coyomap"
    (out / "dev-rebuilds" / "0001").mkdir(parents=True)
    before = out / "dev-rebuilds" / "0001" / "project-map.json"
    before.write_text(json.dumps(_BEFORE), encoding="utf-8")
    current = out / "project-map.json"
    current.write_text(json.dumps(after if after is not None else _AFTER), encoding="utf-8")
    return before, current


def make_lead_transcript(td: Path, read: list[str]) -> Path:
    """A lead transcript whose only tool calls are `Read`s of `read`."""
    f = td / "lead.jsonl"
    recs = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": str(td / p)}}]}} for p in read]
    f.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return f


def test_a_lost_file_is_listed_with_its_lines_and_nothing_the_old_map_said() -> None:
    """Retro 2026-10-08 #1: the advisory printed old rules in full after the last wave, and the
    lead wrote new rules from them that no skeptic read. The file and its lines only."""
    from coyomap.finalize import build_report
    with tempfile.TemporaryDirectory() as td:
        before, current = make_baseline_pair(Path(td))
        report = build_report(current, Path(td), [], before)
    leg = next(l for l in report.legs if l.name == "access baseline")
    text = leg.advisory[0]
    assert "  - a/store.py (line 42)\n" in text, text
    for old in ("Every stored record carries its team", "enforces it", "BR61"):
        assert old not in text, (old, text)
    assert "b/owner.py" not in text, "a file still named by an access rule is not lost"


def test_a_surface_file_keeps_the_claims_and_an_old_one_still_reads() -> None:
    from coyomap.access_surface import AccessClaim, load_claims
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        new = tmp / "new.json"
        write_surface(_model(_BEFORE), new)
        assert load_claims(new)["a/store.py"] == [AccessClaim(
            "BR61", "Every stored record carries its team", "a/store.py:42", "enforces it")]
        old = tmp / "old.json"
        old.write_text(json.dumps({"schema": "coyomap-access-surface/v1",
                                   "files": {"a/store.py": ["BR61"]}}), encoding="utf-8")
        assert load_claims(old) == {"a/store.py": [AccessClaim("BR61", "")]}


def test_record_echoes_the_lines_an_excused_path_held_and_not_the_claim() -> None:
    import contextlib
    import io
    from coyomap import record
    with tempfile.TemporaryDirectory() as td:
        _before, current = make_baseline_pair(Path(td))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = record.main(["--map", str(current), "--heading", "Access baseline exceptions",
                                "--line", "a/store.py: the team filter moved into the query layer",
                                "--line", "c/other.py: never held one"])
    assert code == 0
    said = out.getvalue()
    assert "a/store.py (line 42) held access in 0001/project-map.json" in said, said
    for old in ("Every stored record carries its team", "enforces it", "BR61"):
        assert old not in said, (old, said)
    assert "c/other.py held no access claim" in said, said


def test_an_excused_path_the_lead_never_opened_is_counted() -> None:
    from coyomap.finalize import UNREAD_EXCUSES, build_report
    after = {**_AFTER, "extras": [{"heading": "Access baseline exceptions",
                                   "body": "a/store.py: the team filter moved into the query layer"}]}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        before, current = make_baseline_pair(tmp, after)
        unread = build_report(current, tmp, [], before, make_lead_transcript(tmp, ["b/owner.py"]))
        read = build_report(current, tmp, [], before, make_lead_transcript(tmp, ["a/store.py"]))
        unknown = build_report(current, tmp, [], before, None)
    leg = next(l for l in unread.legs if l.name == "access baseline")
    flagged = [a for a in leg.advisory if UNREAD_EXCUSES in a]
    assert len(flagged) == 1 and flagged[0].startswith("1 of 1 access path(s)"), leg.advisory
    assert "a/store.py (line 42)" in flagged[0] and "BR61" not in flagged[0], flagged
    leg = next(l for l in read.legs if l.name == "access baseline")
    assert not [a for a in leg.advisory if UNREAD_EXCUSES in a], leg.advisory
    leg = next(l for l in unknown.legs if l.name == "access baseline")
    assert leg.note is not None and "not checked" in leg.note, leg


def test_the_session_transcript_is_the_file_beside_its_subagents_folder() -> None:
    from coyomap.provenance import project_slug, session_transcript
    with tempfile.TemporaryDirectory() as td:
        home, repo = Path(td) / "home", Path(td) / "repo"
        repo.mkdir()
        folder = home / ".claude" / "projects" / project_slug(repo)
        folder.mkdir(parents=True)
        assert session_transcript(repo, "abc", home) is None
        (folder / "abc.jsonl").write_text("{}\n", encoding="utf-8")
        assert session_transcript(repo, "abc", home) == folder / "abc.jsonl"



# --- after the review of finding 2: which tool calls open a file, and where the transcript is -----

def make_call_transcript(td: Path, calls: list[tuple[str, dict[str, str], bool]]) -> Path:
    """A transcript of `(tool name, input, failed)` calls, each with its result."""
    recs: list[dict[str, object]] = []
    for n, (name, inp, failed) in enumerate(calls):
        recs.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{n}", "name": name, "input": inp}]}})
        recs.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{n}", "is_error": failed,
             "content": "refused" if failed else "1 line"}]}})
    f = td / "lead.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return f


def _opens(call: tuple[str, dict[str, str], bool], path: str = "app/auth/guard.py") -> bool:
    with tempfile.TemporaryDirectory() as td:
        return unopened([path], [make_call_transcript(Path(td), [call])]) == []


def test_a_refused_read_opens_nothing() -> None:
    assert not _opens(("Read", {"file_path": "app/auth/guard.py"}, True))
    assert _opens(("Read", {"file_path": "app/auth/guard.py"}, False))


def test_counting_or_listing_a_file_is_not_opening_it() -> None:
    for command in ("wc -l app/auth/guard.py", "grep -l token app/auth/guard.py",
                    "grep -c token app/auth/guard.py"):
        assert not _opens(("Bash", {"command": command}, False)), command
    assert _opens(("Bash", {"command": "grep -n token app/auth/guard.py"}, False))


def test_a_quoted_path_and_a_git_show_are_opening_it() -> None:
    for command in ("sed -n '1,80p' \"app/auth/guard.py\"", "git show HEAD:app/auth/guard.py",
                    "cat app/auth/guard.py | head -40"):
        assert _opens(("Bash", {"command": command}, False)), command


def test_a_pattern_naming_a_path_is_still_not_opening_it() -> None:
    assert not _opens(("Bash", {"command": 'grep -rn "app/auth/guard.py" docs/'}, False))


def test_a_bare_name_read_elsewhere_does_not_open_a_longer_path() -> None:
    assert not _opens(("Bash", {"command": "cat guard.py"}, False))


def test_the_transcript_of_a_session_started_in_another_folder_is_found() -> None:
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        other = home / ".claude" / "projects" / "-Users-someone-elsewhere"
        other.mkdir(parents=True)
        (other / "abc-123.jsonl").write_text("{}\n", encoding="utf-8")
        found = session_transcript(home / "repo", "abc-123", home=home)
        assert found == other / "abc-123.jsonl", found
