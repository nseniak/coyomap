#!/usr/bin/env python3
"""Compare the served map with an old one — `api/mapcommits` and `api/compare`.

The pure half (`viewer/compare.py`) is tested on strings; the routes run against a REAL temp git
repo whose map file was renamed between two commits and edited on disk after the last one, which is
the shape a reader meets: a history that crosses the `.coyodex/` → `.coyomap/` rename, and an
uncommitted accept. Explicit make_* builders, no fixtures/classes.
"""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from coyomap.model import to_canonical_json
from coyomap.viewer.compare import (
    LOG_FORMAT, MapVersion, compare_payload, history_payload, load_map_doc, parse_history, parse_ref,
)
from coyomap.viewer.recents import RecentsStore
from coyomap.viewer.serve import Handler, build_projects, compare_with, ensure_fresh, map_history

from test_impact import GUILD_V1, commit, make_model


# --- builders ------------------------------------------------------------------------

def make_map_text(pin: str, purpose: str = "serves guilds", extra_component: bool = False) -> str:
    doc = json.loads(to_canonical_json(make_model(pin)))
    doc["components"][0]["purpose"] = purpose
    if extra_component:
        doc["components"].append({"id": "C2", "name": "Worker", "source": "svc/worker.py:1",
                                  "purpose": "runs the queue"})
    return json.dumps(doc, indent=2)   # multi-line, as the real map is: git's rename detection is line-based


def make_history_repo(td: str) -> tuple[Path, str, str]:
    """Two commits of the map — first under the legacy folder, then renamed and edited — and an
    uncommitted edit on top. Returns (root, sha of the first map commit, sha of the second)."""
    root = Path(td)
    pin = commit(root, {"svc/guild.py": GUILD_V1}, msg="code")
    first = commit(root, {".coyodex/project-map.json": make_map_text(pin)}, msg="Map the codebase")
    second = commit(root, {".coyomap/project-map.json": make_map_text(pin, purpose="serves guilds fast")},
                    removed=[".coyodex/project-map.json"], msg="coyodex is now coyomap")
    (root / ".coyomap" / "project-map.json").write_text(
        make_map_text(pin, purpose="serves guilds fast", extra_component=True), encoding="utf-8")
    return root, first, second


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

def test_history_parsing_follows_the_file_across_its_rename():
    text = ("abc123abc123\x1fabc123a\x1f2026-09-13\x1fcoyodex is now coyomap\n\n"
            ".coyomap/project-map.json\n"
            "def456def456\x1fdef456d\x1f2026-09-09\x1fMap the codebase\n\n"
            ".coyodex/project-map.json\n")
    assert parse_history(text) == [
        MapVersion("abc123abc123", "abc123a", "2026-09-13", "coyodex is now coyomap", ".coyomap/project-map.json"),
        MapVersion("def456def456", "def456d", "2026-09-09", "Map the codebase", ".coyodex/project-map.json"),
    ]
    assert "%x1f" in LOG_FORMAT


def test_a_ref_is_a_commit_sha_or_a_path_and_nothing_else():
    assert parse_ref("abc1234") == ("commit", "abc1234")
    assert parse_ref("path:/tmp/old.json") == ("path", "/tmp/old.json")
    assert parse_ref("path: map-backups/x/project-map.json ") == ("path", "map-backups/x/project-map.json")
    assert parse_ref("--upload-pack=evil") is None
    assert parse_ref("HEAD~1") is None
    assert parse_ref("path:") is None
    assert parse_ref("") is None


def test_a_document_that_is_not_a_map_is_named_as_such():
    try:
        load_map_doc("[1, 2]", "the file")
    except ValueError as e:
        assert "not a coyomap map" in str(e)
    else:
        raise AssertionError("a list passed as a map")
    try:
        load_map_doc("{nope", "the file")
    except ValueError as e:
        assert "not JSON" in str(e)
    else:
        raise AssertionError("broken JSON passed as a map")


def test_the_payload_wraps_the_change_document_with_both_labels():
    old = {"format": "coyomap-map", "rules": [{"id": "BR1", "name": "old", "statement": "old"}]}
    new = {"format": "coyomap-map", "rules": [{"id": "BR1", "name": "new", "statement": "new"}]}
    p = compare_payload(new, old, "abc1234", {"label": "2026-09-09 · Map"}, {"label": "the current map"})
    assert p["ref"] == "abc1234" and p["old"]["label"] == "2026-09-09 · Map" and p["kind"] == "coyomap-map-diff"
    assert [e["change"] for e in p["elements"]] == ["modified"]


def test_the_history_payload_carries_a_label_per_version_and_the_dirty_flag():
    v = MapVersion("a" * 40, "aaaaaaa", "2026-09-09", "Map it", ".coyomap/project-map.json")
    h = history_payload([v], dirty=True)
    assert h["dirty"] is True and h["versions"][0]["label"] == "2026-09-09 · Map it"


# --- the routes, against a real repo ----------------------------------------------------

def test_the_map_s_history_lists_both_commits_newest_first_and_sees_the_edit_on_disk():
    with tempfile.TemporaryDirectory() as td:
        root, first, second = make_history_repo(td)
        proj = build_projects([str(root)])[root.name]
        h = map_history(proj)
        versions = h["versions"]
        assert [v["sha"] for v in versions] == [second, first]
        assert [v["path"] for v in versions] == [".coyomap/project-map.json", ".coyodex/project-map.json"]
        assert versions[1]["subject"] == "Map the codebase"
        assert h["dirty"] is True


def test_comparing_with_the_first_commit_reads_the_map_at_its_old_path():
    with tempfile.TemporaryDirectory() as td:
        root, first, _second = make_history_repo(td)
        proj = build_projects([str(root)])[root.name]
        p = compare_with(proj, first)
        assert p["old"]["label"].endswith("· Map the codebase") and p["old"]["sha"] == first
        assert p["new"]["label"] == "the current map"
        rows = {(e["kind"], e["change"], e["id_new"] or e["id_old"]) for e in p["elements"]}
        assert rows == {("components", "modified", "C1"), ("components", "added", "C2")}
        (c1,) = [e for e in p["elements"] if e["id_new"] == "C1"]
        assert [f["key"] for f in c1["fields"]] == ["purpose"] and c1["summary"] == "purpose reworded"


def test_comparing_with_the_last_commit_shows_only_the_uncommitted_edit():
    with tempfile.TemporaryDirectory() as td:
        root, _first, second = make_history_repo(td)
        proj = build_projects([str(root)])[root.name]
        p = compare_with(proj, second)
        assert [(e["change"], e["id_new"]) for e in p["elements"]] == [("added", "C2")]


def test_a_commit_ref_is_cached_until_the_map_changes_on_disk():
    with tempfile.TemporaryDirectory() as td:
        root, first, _second = make_history_repo(td)
        proj = build_projects([str(root)])[root.name]
        assert compare_with(proj, first) is compare_with(proj, first)
        f = root / ".coyomap" / "project-map.json"
        doc = json.loads(f.read_text())
        doc["components"][0]["purpose"] = "serves guilds slowly"
        f.write_text(json.dumps(doc), encoding="utf-8")
        import os
        os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 5_000_000))
        ensure_fresh(proj)
        (c1,) = [e for e in compare_with(proj, first)["elements"] if e["id_new"] == "C1"]
        assert c1["fields"][0]["new"] == "serves guilds slowly"


def test_a_map_file_on_disk_compares_too_and_a_bad_path_is_the_reader_s_fault():
    with tempfile.TemporaryDirectory() as td:
        root, _first, _second = make_history_repo(td)
        proj = build_projects([str(root)])[root.name]
        old = root / "backup.json"
        old.write_text(make_map_text(proj.commit, purpose="serves guilds"), encoding="utf-8")
        p = compare_with(proj, f"path:{old}")
        assert p["old"]["label"] == str(old) and p["old"]["path"] == str(old)
        assert {e["id_new"] or e["id_old"] for e in p["elements"]} == {"C1", "C2"}
        for bad, words in ((f"path:{root / 'missing.json'}", "cannot read"),
                           ("path:svc/guild.py", "not JSON"),
                           ("nonsense", "commit sha or path"),
                           ("0123456789abcdef0123456789abcdef01234567", "not a commit")):
            try:
                compare_with(proj, bad)
            except ValueError as e:
                assert words in str(e), (bad, str(e))
            else:
                raise AssertionError(f"{bad} was accepted")


def test_the_two_endpoints_answer_over_http_and_a_bad_ref_is_a_400():
    with tempfile.TemporaryDirectory() as td:
        root, first, _second = make_history_repo(td)
        httpd, slug, port = make_server(root)
        try:
            status, body = get(port, f"/coyomap/{slug}/api/mapcommits")
            assert status == 200 and len(json.loads(body)["versions"]) == 2
            status, body = get(port, f"/coyomap/{slug}/api/compare?ref={first}")
            assert status == 200 and json.loads(body)["ref"] == first
            status, body = get(port, f"/coyomap/{slug}/api/compare?ref=HEAD")
            assert status == 400 and b"commit sha or path" in body
        finally:
            httpd.shutdown()
            httpd.server_close()
