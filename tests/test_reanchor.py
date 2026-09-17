#!/usr/bin/env python3
"""`coyomap reanchor` — code links follow git's line mapping; changed lines and gone files are the
agent's, and are listed. Real temp git repos, explicit make_* builders, no fixtures/classes."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from coyomap import reanchor as ra
from coyomap.impact_git import ImpactError
from coyomap.impact_lib import Hunk, anchor_index
from coyomap.model import load_model, to_canonical_json
from coyomap.reanchor import line_mapper, reanchor, set_anchor

from test_impact import commit, make_model

TEN = "\n".join(f"line {i}" for i in range(1, 11)) + "\n"


def make_map_doc(pin: str) -> dict[str, Any]:
    """A map whose links cover every kind of place a link can live, all into `svc/a.py` and the
    file that will be renamed and the one that will go."""
    doc = json.loads(to_canonical_json(make_model(pin)))
    doc["components"] = [{"id": "C1", "name": "Svc", "source": "svc/a.py:5", "files": ["svc/a.py:2-3"],
                          "evidence": [{"file": "svc/a.py:9", "why": "w"}]}]
    doc["entities"] = [{"id": "E1", "name": "Guild", "source": "svc/b.py:2"}]
    doc["non_entity_types"] = [{"name": "helper", "source": "svc/d.py:1"}]
    doc["edges"] = [{"src": "C1", "verb": "uses", "dst": "D1", "where": "svc/a.py:8"},
                    {"src": "C1", "verb": "uses", "dst": "D1", "where": "svc/a.py:4"}]
    doc["entry_points"] = [{"id": "EP1", "kind": "cli", "trigger": "run it", "source": "svc/a.py:3", "component": "C1"}]
    doc["rules"] = [{"id": "BR1", "name": "A guard", "statement": "A guard holds.",
                     "sites": [{"where": "svc/a.py:10", "why": "guards"}]}]
    doc["use_cases"] = [{"id": "UC1", "name": "Do it", "actors": ["R1"]}]
    doc["roles"] = [{"id": "R1", "name": "Reader"}]
    doc["flows"] = [{"uc": "UC1", "title": "Do it", "steps": [{"n": 1, "src": "R1", "dst": "C1", "phrase": "runs it", "where": "svc/a.py:6"}]}]
    doc["glossary"] = [{"term": "guild", "meaning": "a team", "source": "svc/d.py:1"}]
    return doc


def make_repo(td: str) -> tuple[Path, str, str]:
    """Commit 1: the anchored files. Commit 2: two lines inserted above everything in a.py, its line
    8 rewritten, b.py renamed to c.py, d.py deleted."""
    root = Path(td)
    pin = commit(root, {"svc/a.py": TEN, "svc/b.py": TEN, "svc/d.py": TEN}, msg="pin")
    lines = TEN.splitlines()
    lines[7] = "line 8 changed"
    after = "\n".join(["# one", "# two", *lines]) + "\n"
    (root / "svc/c.py").write_text(TEN, encoding="utf-8")
    head = commit(root, {"svc/a.py": after}, removed=["svc/b.py", "svc/d.py"], msg="edit")
    return root, pin, head


# --- the mapping ------------------------------------------------------------------------------

def test_a_line_below_an_insertion_moves_and_a_replaced_line_has_no_answer():
    to_t = line_mapper([Hunk(0, 0, ("a", "b"), ()),          # two lines inserted before line 1
                        Hunk(8, 1, ("changed",), ("old",))])  # line 8 rewritten
    assert [to_t(n) for n in (1, 7, 9)] == [3, 9, 11]
    assert to_t(8) is None


def test_a_deletion_pulls_the_lines_below_it_up():
    to_t = line_mapper([Hunk(2, 3, (), ("x", "y", "z"))])    # lines 2-4 deleted
    assert to_t(1) == 1 and to_t(5) == 2 and to_t(3) is None


# --- the run --------------------------------------------------------------------------------

def test_links_follow_shifts_and_renames_and_the_rest_is_listed():
    with tempfile.TemporaryDirectory() as td:
        root, pin, head = make_repo(td)
        m = load_model(json.dumps(make_map_doc(pin)))
        r = reanchor(m, root, head)
        moved = {(x.eid, x.field): (x.old, x.new) for x in r.moved}
        assert moved[("C1", "source")] == ("svc/a.py:5", "svc/a.py:7")
        assert moved[("C1", "files")] == ("svc/a.py:2-3", "svc/a.py:4-5")
        assert moved[("C1", "evidence")] == ("svc/a.py:9", "svc/a.py:11")
        assert moved[("ep:svc/a.py:3", "source")] == ("svc/a.py:3", "svc/a.py:5")
        assert moved[("rule:BR1:0", "where")] == ("svc/a.py:10", "svc/a.py:12")
        assert moved[("step:UC1:1", "where")] == ("svc/a.py:6", "svc/a.py:8")
        assert moved[("E1", "source")] == ("svc/b.py:2", "svc/c.py:2"), "a renamed file keeps its links"
        assert moved[("edge:C1>uses>D1", "where")] == ("svc/a.py:4", "svc/a.py:6"), "the sibling arrow at line 4 moved"
        unmapped = {(u.eid, u.anchor): u.why for u in r.unmapped}
        assert unmapped[("edge:C1>uses>D1", "svc/a.py:8")] == "line changed", "the arrow on the rewritten line is the agent's"
        assert unmapped[("glossary:guild", "svc/d.py:1")] == "file gone" and unmapped[("net:helper", "svc/d.py:1")] == "file gone"
        assert m.components[0].source == "svc/a.py:7" and m.entities[0].source == "svc/c.py:2"
        assert sorted(e.where or "" for e in m.edges) == ["svc/a.py:6", "svc/a.py:8"], "the unmapped arrow keeps its old link"
        assert r.files == 2


def test_nothing_moves_when_the_map_is_at_the_commit_asked_for():
    with tempfile.TemporaryDirectory() as td:
        root, pin, _head = make_repo(td)
        m = load_model(json.dumps(make_map_doc(pin)))
        r = reanchor(m, root, pin)
        assert r.moved == [] and r.unmapped == []


def make_every_kind_doc() -> dict[str, Any]:
    """A map carrying EVERY place `anchor_index` reads an anchor from, with a paired duplicate at one
    line wherever two rows can share a place (two arrows, two ways in, two sites, two security rows,
    two dependency evidence rows)."""
    return {
        "format": "coyomap-map", "title": "t", "goal": "g", "commit": "0000000",
        "roles": [{"id": "R1", "name": "Reader", "kind": "human"},
                  {"id": "R2", "name": "Admin", "kind": "human", "relations": [{"kind": "includes", "role": "R1", "source": "auth/grant.py:12"}]}],
        "glossary": [{"term": "guild", "meaning": "a team", "source": "svc/d.py:1"}],
        "capabilities": [{"id": "CAP1", "name": "Mapping", "source": "cap/x.py:3"}],
        "use_cases": [{"id": "UC1", "name": "Do it", "actors": ["R1"], "capability": "CAP1"}],
        "subsystems": [{"id": "S1", "name": "Core", "source": "core/y.py:4"}],
        "components": [{"id": "C1", "name": "Svc", "source": "svc/a.py:5", "files": ["svc/a.py:2-3", "svc/a.py"],
                        "evidence": [{"file": "svc/a.py:9", "why": "w"}]}],
        "deps": [{"id": "D1", "name": "Store", "where_configured": "cfg/dep.toml:7",
                  "evidence": [{"file": "svc/a.py:11", "why": "w"}, {"file": "svc/a.py:11", "why": "twice at one line"}]}],
        "interfaces": [{"id": "I1", "name": "CLI", "source": "cli/main.py:2", "evidence": [{"file": "cli/main.py:9", "why": "w"}]}],
        "run_commands": [{"action": "serve", "command": "make serve", "source": "Makefile:30"}],
        "entry_points": [{"id": "EP1", "kind": "cli", "trigger": "run it", "source": "svc/a.py:3", "component": "C1"},
                         {"id": "EP2", "kind": "cli", "trigger": "run it again", "source": "svc/a.py:3", "component": "C1"}],
        "subdomains": [{"id": "SD1", "name": "Teams", "source": "dom/z.py:6"}],
        "entities": [{"id": "E1", "name": "Guild", "source": "svc/b.py:2"}],
        "non_entity_types": [{"name": "helper", "source": "svc/d.py:1"}],
        "flows": [{"uc": "UC1", "title": "Do it", "steps": [
            {"n": 1, "src": "R1", "dst": "C1", "phrase": "runs it", "where": "svc/a.py:6"},
            {"n": 2, "src": "C1", "dst": "C1", "phrase": "does the shared bit", "subflow": "SF1"}]}],
        "subflows": [{"id": "SF1", "name": "Shared bit", "steps": [{"n": 1, "src": "C1", "dst": "D1", "phrase": "stores", "where": "svc/a.py:13"}]}],
        "edges": [{"src": "C1", "verb": "uses", "dst": "D1", "where": "svc/a.py:8"},
                  {"src": "C1", "verb": "uses", "dst": "D1", "where": "svc/a.py:8"}],
        "security": [{"surface": "dashboard", "who": "admins", "source": "auth/check.py:20"},
                     {"surface": "dashboard", "who": "same surface twice", "source": "auth/check.py:20"}],
        "blocks": [{"id": "BLK1", "name": "Access", "source": "rules/blk.py:1"}],
        "rules": [{"id": "BR1", "name": "A guard", "statement": "A guard holds.", "block": "BLK1",
                   "sites": [{"where": "svc/a.py:10", "why": "guards"}, {"where": "svc/a.py:10", "why": "guards twice"}]}],
    }


def test_the_setter_writes_where_the_walker_read_for_every_kind():
    """Every place `anchor_index` reads from, `set_anchor` can write to — the mirror is complete —
    and a pair of rows at one place is written once each, never one of them twice."""
    m = load_model(json.dumps(make_every_kind_doc()))
    refs = anchor_index(m)
    kinds = {r.kind for r in refs}
    assert kinds >= {"component", "dep", "interface", "entity", "non_entity_type", "glossary", "entry_point",
                     "edge", "flow_step", "security", "role", "rule_site", "run_command", "group"}
    for ref in refs:
        if ref.lo is None:
            continue
        assert set_anchor(m, ref, f"{ref.path}:{ref.lo + 100}"), (ref.eid, ref.field)
    moved = [r for r in anchor_index(m) if r.lo is not None]
    assert moved and all(r.lo is not None and r.lo > 100 for r in moved)
    assert len(moved) == len([r for r in refs if r.lo is not None]), "every anchored place still holds one anchor"


def test_reanchor_refuses_the_working_tree():
    """F8: the working tree has no line map; it used to answer 'file gone' for every link, exit 0."""
    with tempfile.TemporaryDirectory() as td:
        root, pin, _head = make_repo(td)
        m = load_model(json.dumps(make_map_doc(pin)))
        with pytest.raises(ImpactError, match="COMMIT"):
            reanchor(m, root, "WORKTREE")


# --- the command ------------------------------------------------------------------------------

def test_the_command_reports_without_writing_and_writes_on_request(capsys):
    with tempfile.TemporaryDirectory() as td:
        root, pin, head = make_repo(td)
        map_path = root / ".coyomap" / "project-map.json"
        map_path.parent.mkdir()
        map_path.write_text(json.dumps(make_map_doc(pin)), encoding="utf-8")
        before = map_path.read_text()
        assert ra.main(["--map", str(map_path), "--to", head]) == 0
        out = capsys.readouterr().out
        assert "8 link(s) moved, 3 left for the agent — not written" in out and "? edge:C1>uses>D1" in out
        assert map_path.read_text() == before
        assert ra.main(["--map", str(map_path), "--to", head, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["kind"] == "coyomap-reanchor" and payload["written"] is False and len(payload["moved"]) == 8
        assert ra.main(["--map", str(map_path), "--to", head, "--write"]) == 0
        assert "written" in capsys.readouterr().out.split("—")[-1]
        assert json.loads(map_path.read_text())["components"][0]["source"] == "svc/a.py:7"


def test_the_command_refuses_a_bad_option_and_needs_a_map(capsys):
    assert ra.main(["--map", "x.json", "--bogus"]) == 2 and "unknown option" in capsys.readouterr().err
    assert ra.main(["--to", "HEAD"]) == 2 and "--map" in capsys.readouterr().err
    assert ra.main(["--help"]) == 0 and "usage: coyomap reanchor" in capsys.readouterr().out
    assert ra.main([]) == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
