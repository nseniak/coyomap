#!/usr/bin/env python3
"""The update logs on screen — `api/changes`, `api/changes/<from>-<to>`, and the pin on every row of
`api/mapcommits`.

The pure half (`viewer/changes.py`: file names, order, the pin out of a map's text) is tested on
strings. The routes run against a REAL temp git repo: the map committed once, then the code moved on,
the map updated on disk and the log written beside it — which is what a reader meets after `coyomap
update` and before its commit. Explicit make_* builders, no fixtures/classes.
"""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from coyomap.viewer.changes import LogHead, log_name, order_logs, parse_log_ref, pin_of
from coyomap.viewer.recents import RecentsStore
from coyomap.viewer.serve import (
    Handler, build_projects, change_log_view, list_changes, map_history, version_for_pin,
)

from test_impact import GUILD_V1, commit
from test_map_compare import make_map_text

RULE = {"id": "BR1", "name": "A guild keeps its founder", "statement": "A guild keeps its founder.",
        "risk": "a guild is left with nobody who can run it", "sites": [{"where": "svc/guild.py:4", "why": "guards"}]}


# --- builders ------------------------------------------------------------------------

def make_log_text(from_commit: str, to_commit: str, entries: list[dict[str, Any]] | None = None,
                  date: str = "2026-09-17") -> str:
    entry = {"id": "e1", "headline": "A guild keeps its founder", "sentence": "A guild can no longer lose the person who founded it.",
             "elements": ["C1", "BR1"],
             "edits": [{"id": "C1", "key": "purpose", "was": "serves guilds", "now": "serves guilds fast"}],
             "added": [{"kind": "rules", "row": RULE}], "removed": [], "evidence": ["svc/guild.py"],
             "confidence": "verified"}
    return json.dumps({"format": "coyomap-changes", "version": 1, "from_commit": from_commit, "to_commit": to_commit,
                       "date": date, "entries": entries if entries is not None else [entry], "waived": [], "notes": ""})


def make_update_repo(td: str) -> tuple[Path, str, str, str]:
    """The map committed at the first code commit, then the code moved on and the map was updated on
    disk — reworded purpose, a rule added, the Worker component gone — with the log beside it.
    Returns (root, sha of the map commit, the old pin, the new pin)."""
    root = Path(td)
    pin1 = commit(root, {"svc/guild.py": GUILD_V1}, msg="code")
    first = commit(root, {".coyomap/project-map.json": make_map_text(pin1, extra_component=True)}, msg="Map the codebase")
    pin2 = commit(root, {"svc/guild.py": GUILD_V1 + "\n\ndef founder():\n    return 2\n"}, msg="a guild keeps its founder")
    doc = json.loads(make_map_text(pin2, purpose="serves guilds fast"))
    doc["rules"] = [RULE]
    (root / ".coyomap" / "project-map.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    changes = root / ".coyomap" / "changes"
    changes.mkdir()
    entry = json.loads(make_log_text(pin1[:7], pin2[:7]))["entries"][0]
    entry["elements"].append("C2")
    entry["removed"] = ["C2"]
    (changes / f"{pin1[:7]}-{pin2[:7]}.json").write_text(make_log_text(pin1[:7], pin2[:7], [entry]), encoding="utf-8")
    return root, first, pin1, pin2


def make_server(root: Path) -> tuple[ThreadingHTTPServer, str, int]:
    projects = build_projects([str(root)])
    slug = next(iter(projects))
    Handler.store = RecentsStore()
    Handler.projects = projects
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, slug, httpd.server_address[1]


def get(port: int, url: str) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", url)
    resp = conn.getresponse()
    return resp.status, resp.read()


# --- the pure half ---------------------------------------------------------------------

def test_only_a_log_is_a_log_never_the_scratch_files_or_an_editor_s_swap():
    assert log_name(Path("3a9e901-1b77f52.json")) == "3a9e901-1b77f52"
    for other in ("3a9e901-1b77f52.before.json", "3a9e901-1b77f52.impact.json", "3a9e901-1b77f52.md",
                  ".3a9e901-1b77f52.md.swp", "notes.json", "HEAD-1b77f52.json"):
        assert log_name(Path(other)) is None, other


def test_a_log_ref_names_a_log_and_nothing_else_does():
    assert parse_log_ref("log:3a9e901-1b77f52") == "3a9e901-1b77f52"
    assert parse_log_ref("3a9e901-1b77f52") is None
    assert parse_log_ref("log:../x") is None
    assert parse_log_ref("log:") is None


def test_the_pin_is_read_off_the_header_or_the_whole_file():
    canonical = '{\n  "format": "coyomap-map",\n  "title": "t",\n  "commit": "1b77f52-dirty",\n  "rules": []\n}\n'
    assert pin_of(canonical) == "1b77f52"
    assert pin_of('{"format": "coyomap-map", "commit": "3a9e901"}') == "3a9e901"
    assert pin_of('{"format": "coyomap-map"}') is None
    assert pin_of("{nope") is None


def test_logs_are_ordered_by_the_chain_from_the_pin_then_by_date():
    a = LogHead("aaaaaaa-bbbbbbb", "aaaaaaa", "bbbbbbb", "2026-09-01", 1)
    b = LogHead("bbbbbbb-ccccccc", "bbbbbbb", "ccccccc", "2026-09-02", 2)
    stray = LogHead("1111111-2222222", "1111111", "2222222", "2026-09-03", 1)
    older_stray = LogHead("3333333-4444444", "3333333", "4444444", "2026-08-01", 1)
    assert [h.name for h in order_logs([older_stray, a, stray, b], "ccccccc")] == [b.name, a.name, stray.name, older_stray.name]
    assert [h.name for h in order_logs([a, b], None)] == [b.name, a.name], "no pin: by date"


def test_two_logs_ending_at_the_pin_the_newest_by_date_is_the_latest():
    older = LogHead("bbbbbbb-ccccccc", "bbbbbbb", "ccccccc", "2026-09-02", 1)
    newer = LogHead("ddddddd-ccccccc", "ddddddd", "ccccccc", "2026-09-05", 1)
    assert [h.name for h in order_logs([older, newer], "ccccccc")] == [newer.name, older.name]
    assert [h.name for h in order_logs([older, newer], "ccccccc-dirty")][0] == newer.name


def test_the_pin_is_found_past_a_long_header():
    goal = "x" * 5000
    text = json.dumps({"format": "coyomap-map", "title": "t", "goal": goal, "commit": "1b77f52", "rules": []}, indent=2)
    assert '"commit"' not in text[:4096] and pin_of(text) == "1b77f52"


def test_a_folder_with_no_git_still_serves_the_log_with_no_evidence():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".coyomap" / "changes").mkdir(parents=True)
        doc = json.loads(make_map_text("bbbbbbb", purpose="serves guilds fast"))
        doc["rules"] = [RULE]
        (root / ".coyomap" / "project-map.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        entry = json.loads(make_log_text("aaaaaaa", "bbbbbbb"))["entries"][0]
        entry["elements"].append("C2")
        entry["removed"] = ["C2"]
        (root / ".coyomap" / "changes" / "aaaaaaa-bbbbbbb.json").write_text(make_log_text("aaaaaaa", "bbbbbbb", [entry]), encoding="utf-8")
        proj = build_projects([str(root)])[root.name]
        assert [l["latest"] for l in list_changes(proj)["logs"]] == [True]
        got = change_log_view(proj, "aaaaaaa-bbbbbbb")
        assert got["from_version"] is None
        boxes = got["entries"][0]["boxes"]
        assert (boxes[0]["name"], boxes[2]["name"], boxes[2]["kind"], boxes[2]["word"]) == ("Svc", None, "components", "component")


# --- the routes, against a real repo ----------------------------------------------------

def test_the_map_versions_carry_their_own_pin_and_a_log_s_from_commit_finds_its_version():
    with tempfile.TemporaryDirectory() as td:
        root, first, pin1, pin2 = make_update_repo(td)
        proj = build_projects([str(root)])[root.name]
        rows = map_history(proj, pins=True)["versions"]
        assert [(r["sha"], r["pin"]) for r in rows] == [(first, pin1)]
        assert "pin" not in map_history(proj)["versions"][0], "the pin is read only when asked for"
        found = version_for_pin(proj, pin1[:7])
        assert found is not None and found["sha"] == first and found["pin"] == pin1
        assert version_for_pin(proj, pin2) is None, "the updated map is on disk, not committed yet"
        assert proj.pin_cache == {first: pin1}


def test_the_oldest_version_with_a_pin_is_the_commit_that_moved_it_there():
    """Three map commits carry one pin (an update, then two rename-only commits). The newest is the
    map a later log starts from; the oldest is the commit that landed the update — the new side of
    its own step."""
    with tempfile.TemporaryDirectory() as td:
        root, first, pin1, pin2 = make_update_repo(td)
        second = commit(root, {".coyomap/project-map.json": make_map_text(pin1, purpose="serves guilds (renamed)")},
                        msg="a rename-only commit")
        third = commit(root, {".coyomap/project-map.json": make_map_text(pin1, purpose="serves guilds (renamed twice)")},
                       msg="another")
        proj = build_projects([str(root)])[root.name]
        assert version_for_pin(proj, pin1)["sha"] == third
        assert version_for_pin(proj, pin1, oldest=True)["sha"] == first
        # `landed` is the commit that ADDED the log file — here the rename commit swept it in — never a
        # guess from the pins, which a rebuild or a later commit sharing the pin would get wrong.
        (row,) = list_changes(proj)["logs"]
        assert row["landed"]["sha"] == second and row["landed"]["subject"] == "a rename-only commit"
        view = change_log_view(proj, f"{pin1[:7]}-{pin2[:7]}")
        assert view["to_version"]["sha"] == second, "the step's new side is the map at the update's own commit"
        assert view["from_version"]["sha"] == first, "the old side is the map's version in force just before that commit"
        assert view["from_version"]["subject"] == "Map the codebase"
        assert version_for_pin(proj, "0000000", oldest=True) is None
        assert second != first


def test_the_logs_are_listed_with_the_latest_marked_and_a_broken_one_reported():
    with tempfile.TemporaryDirectory() as td:
        root, _first, pin1, pin2 = make_update_repo(td)
        changes = root / ".coyomap" / "changes"
        (changes / "0000000-1111111.json").write_text("{broken", encoding="utf-8")
        (changes / f"{pin1[:7]}-{pin2[:7]}.before.json").write_text("{}", encoding="utf-8")
        proj = build_projects([str(root)])[root.name]
        got = list_changes(proj)
        assert [(l["name"], l["from"], l["to"], l["entries"], l["latest"]) for l in got["logs"]] == \
            [(f"{pin1[:7]}-{pin2[:7]}", pin1[:7], pin2[:7], 1, True)]
        assert got["logs"][0]["headlines"] == ["A guild keeps its founder"]
        assert got["logs"][0]["landed"] is None, "the update sits on disk, uncommitted"
        assert got["pin"] == pin2
        assert got["problems"] and got["problems"][0].startswith("0000000-1111111.json:")


def test_a_map_without_logs_lists_none():
    with tempfile.TemporaryDirectory() as td:
        root, _first, _pin1, _pin2 = make_update_repo(td)
        for p in (root / ".coyomap" / "changes").iterdir():
            p.unlink()
        proj = build_projects([str(root)])[root.name]
        assert list_changes(proj) == {"logs": [], "pin": proj.commit, "problems": []}


def test_one_log_comes_with_its_boxes_by_name_and_the_map_it_was_written_against():
    with tempfile.TemporaryDirectory() as td:
        root, first, pin1, pin2 = make_update_repo(td)
        proj = build_projects([str(root)])[root.name]
        got = change_log_view(proj, f"{pin1[:7]}-{pin2[:7]}")
        assert got["latest"] is True and got["from_version"]["sha"] == first and got["from_version"]["pin"] == pin1
        assert got["to_version"] is None, "the update sits on disk, uncommitted: the served map is the step's new side"
        assert [k["array"] for k in got["kinds"]][:2] == ["capabilities", "use_cases"]
        (e,) = got["entries"]
        assert e["headline"] == "A guild keeps its founder"
        assert [(b["name"], b["kind"], b["group"], b["state"]) for b in e["boxes"]] == [
            ("Svc", "components", "hood", "modified"),
            ("A guild keeps its founder", "rules", "product", "added"),
            ("Worker", "components", "hood", "removed"),   # named from the map as it was
        ]
        (ed,) = e["edits"]
        assert ed["box"] == "C1" and ed["name"] == "Svc" and ed["label"] == "Purpose"
        assert (ed["old"], ed["new"]) == ("serves guilds", "serves guilds fast")
        assert [sp["op"] for sp in ed["spans"]] == ["eq", "ins"]


def test_a_later_commit_sharing_the_pin_does_not_claim_the_update():
    """After the update's commit, two more map commits keep the same pin. The update still lands at
    its own commit, and its step runs from the map before it to the map it made."""
    with tempfile.TemporaryDirectory() as td:
        root, first, pin1, pin2 = make_update_repo(td)
        own = commit(root, {".coyomap/changes/keep.txt": "x"}, msg="Map update: a guild keeps its founder")
        commit(root, {".coyomap/project-map.json": make_map_text(pin2, purpose="serves guilds fast (tidied)")}, msg="a repair")
        commit(root, {".coyomap/project-map.json": make_map_text(pin2, purpose="serves guilds fast (tidied twice)")}, msg="another repair")
        proj = build_projects([str(root)])[root.name]
        (row,) = list_changes(proj)["logs"]
        assert row["landed"]["sha"] == own and row["landed"]["subject"].startswith("Map update")
        view = change_log_view(proj, f"{pin1[:7]}-{pin2[:7]}")
        assert view["to_version"]["sha"] == own and view["from_version"]["sha"] == first
        assert view["from_version"]["subject"] == "Map the codebase", "the parent is a known version, so it keeps its own label"



    with tempfile.TemporaryDirectory() as td:
        root, _first, pin1, pin2 = make_update_repo(td)
        proj = build_projects([str(root)])[root.name]
        for bad, exc, words in (("HEAD", ValueError, "not the name"), ("../etc", ValueError, "not the name"),
                                ("1234567-abcdef0", LookupError, "no update log")):
            try:
                change_log_view(proj, bad)
            except exc as e:
                assert words in str(e), (bad, str(e))
            else:
                raise AssertionError(f"{bad} was accepted")
        (root / ".coyomap" / "changes" / f"{pin1[:7]}-{pin2[:7]}.json").write_text("{broken", encoding="utf-8")
        try:
            change_log_view(proj, f"{pin1[:7]}-{pin2[:7]}")
        except RuntimeError as e:
            assert "could not be read" in str(e)
        else:
            raise AssertionError("a broken log was served")


def test_the_routes_answer_over_http():
    with tempfile.TemporaryDirectory() as td:
        root, first, pin1, pin2 = make_update_repo(td)
        httpd, slug, port = make_server(root)
        try:
            status, body = get(port, f"/coyomap/{slug}/api/changes")
            assert status == 200 and [l["name"] for l in json.loads(body)["logs"]] == [f"{pin1[:7]}-{pin2[:7]}"]
            status, body = get(port, f"/coyomap/{slug}/api/changes/{pin1[:7]}-{pin2[:7]}")
            assert status == 200 and json.loads(body)["entries"][0]["boxes"][0]["name"] == "Svc"
            status, body = get(port, f"/coyomap/{slug}/api/changes/nope")
            assert status == 400 and b"not the name" in body
            status, body = get(port, f"/coyomap/{slug}/api/changes/1234567-abcdef0")
            assert status == 404
            status, body = get(port, f"/coyomap/{slug}/api/changes/a/b/c")
            assert status == 404, "three segments is no route"
            status, body = get(port, f"/coyomap/{slug}/api/mapcommits")
            assert status == 200 and json.loads(body)["versions"][0]["pin"] == pin1
        finally:
            httpd.shutdown()
            httpd.server_close()
