#!/usr/bin/env python3
"""Tests for the local map server (coyomap.viewer.serve) — the file browser + code viewer backend.

Stdlib-only — no pytest required. Run either way (needs an editable install: `make deps`, and `git`
on PATH for the git-integration tests):
    python3 tests/test_serve.py
    pytest tests/test_serve.py

Covers the pure guards (path safety + the -dirty strip), the git reads against a REAL temp repo (no
patching — an actual `git init` + commit), project discovery over a temp directory tree using the
committed fixture map, and the git-backed file-browser tree.
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from coyomap.viewer.filetree import FileTreeNode
from coyomap.viewer.recents import RecentsStore, register_project
from coyomap.viewer.running import running_servers
from coyomap.viewer.serve import (
    Handler,
    Project,
    _FRONTEND_DIR,
    _has_coyomap,
    _loopback_host,
    safe_rel,
    _strip_dirty,
    _valid_commit,
    build_projects,
    dev_stamp,
    git_blob_size,
    git_ls_files,
    git_show,
    list_dirs,
    load_project,
    project_symbols,
    project_tree,
    project_view,
    with_dev_reload,
    serve,
)

_FIXTURE_MAP = Path(__file__).parent / "fixtures" / "mcpolis-project-map.json"


# --- builders (no fixtures; explicit make_* helpers) ----------------------------
def make_git_repo(root: Path, files: dict[str, str]) -> str:
    """Init a git repo at `root`, write + commit `files` (path -> text), return the commit SHA."""
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, env=env)
    run("init", "-q")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "init")
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, env=env)
    return out.stdout.decode().strip()


def make_project_dir(parent: Path, name: str) -> Path:
    """Create `parent/name` with a `.coyomap/project-map.json` (the committed fixture) inside."""
    d = parent / name
    (d / ".coyomap").mkdir(parents=True)
    shutil.copy(_FIXTURE_MAP, d / ".coyomap" / "project-map.json")
    return d


# --- pure guards ----------------------------------------------------------------
def test_strip_dirty() -> None:
    assert _strip_dirty("abc123-dirty") == "abc123"
    assert _strip_dirty("abc123") == "abc123"
    assert _strip_dirty("") == ""


def test_valid_commit() -> None:
    assert _valid_commit("e5cec8b")                       # short SHA
    assert _valid_commit("a" * 40)                        # full SHA
    assert not _valid_commit("")                          # empty
    assert not _valid_commit("-x")                        # leading dash -> would be a git flag
    assert not _valid_commit("--output=/tmp/x")           # flag smuggling attempt
    assert not _valid_commit("HEAD")                      # a ref name, not a bare SHA
    assert not _valid_commit("e5cec8b:../evil")           # not a bare SHA


def test_loopback_host() -> None:
    assert _loopback_host("")                             # absent Host (curl / HTTP1.0)
    assert _loopback_host("127.0.0.1:8765")
    assert _loopback_host("localhost:8765")
    assert _loopback_host("[::1]:8765")
    assert _loopback_host("localhost")
    assert not _loopback_host("evil.com")                 # DNS-rebinding target
    assert not _loopback_host("attacker.com:8765")
    assert not _loopback_host("192.168.1.10:8765")


def test_safe_rel_rejects_escapes() -> None:
    assert safe_rel("src/app.py")
    assert safe_rel("a/b/c.txt")
    assert not safe_rel("")                       # empty
    assert not safe_rel("/etc/passwd")            # absolute
    assert not safe_rel("../../etc/passwd")       # traversal
    assert not safe_rel("a/../../b")              # traversal mid-path
    assert not safe_rel("a\\b")                   # backslash
    assert not safe_rel("a\x00b")                 # null byte


# --- git reads (real temp repo, no patching) ------------------------------------
def test_git_ls_files_and_show() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sha = make_git_repo(root, {"src/app.py": "print('hi')\n", "README.md": "# hello\n"})
        assert sorted(git_ls_files(root, sha)) == ["README.md", "src/app.py"]
        assert git_show(root, sha, "src/app.py") == b"print('hi')\n"
        assert git_show(root, sha, "does/not/exist.py") is None   # missing -> None
        assert git_show(root, sha, "../escape.py") is None        # unsafe -> None (guard, no git call)


def test_git_blob_size_file_dir_and_missing() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sha = make_git_repo(root, {"src/app.py": "print('hi')\n", "README.md": "# hello\n"})
        assert git_blob_size(root, sha, "src/app.py") == len(b"print('hi')\n")  # blob -> byte size
        assert git_blob_size(root, sha, "src") is None            # a directory is a tree, not a file
        assert git_blob_size(root, sha, "nope.py") is None        # missing -> None
        assert git_blob_size(root, sha, "../escape.py") is None   # unsafe -> None (guard, no git call)


def test_git_reads_empty_commit_is_safe() -> None:
    with tempfile.TemporaryDirectory() as td:
        # No commit given -> both reads return the empty/None result rather than raising.
        assert git_ls_files(Path(td), "") == []
        assert git_show(Path(td), "", "x.py") is None


# --- discovery ------------------------------------------------------------------
# --- recents store --------------------------------------------------------------
def test_recents_store_add_remove_dedupe_persist() -> None:
    with tempfile.TemporaryDirectory() as td:
        store_path = Path(td) / "recents.json"
        s = RecentsStore(store_path)
        assert s.list() == []
        s.add(str(Path(td) / "a"))
        s.add(str(Path(td) / "b"))
        s.add(str(Path(td) / "a"))                 # re-add -> dedup + bump to front
        assert [Path(p).name for p in s.list()] == ["a", "b"]
        # Persisted + reloaded by a fresh store over the same file.
        assert [Path(p).name for p in RecentsStore(store_path).list()] == ["a", "b"]
        s.remove(str(Path(td) / "a"))
        assert [Path(p).name for p in s.list()] == ["b"]
        assert [Path(p).name for p in RecentsStore(store_path).list()] == ["b"]


def test_recents_store_missing_file_is_empty() -> None:
    with tempfile.TemporaryDirectory() as td:
        assert RecentsStore(Path(td) / "does-not-exist.json").list() == []


def test_recents_store_add_merges_external_change() -> None:
    # A mutation reloads first, so an external writer (a build registering a project while the server
    # runs) is merged, not clobbered.
    with tempfile.TemporaryDirectory() as td:
        store_path = Path(td) / "recents.json"
        s = RecentsStore(store_path)
        s.add(str(Path(td) / "a"))
        RecentsStore(store_path).add(str(Path(td) / "b"))  # a DIFFERENT store instance writes "b"
        s.add(str(Path(td) / "c"))                          # s hasn't seen "b" in memory...
        assert {Path(p).name for p in s.list()} == {"a", "b", "c"}  # ...but reload-before-add kept it


def test_register_project() -> None:
    """A finished build remembers its project — unless the opt-out switch is set. The whole test run
    sets that switch (the root conftest.py), so this test clears it for its own body; its stores are
    injected temp files, never the real list."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "myproj"
        (repo / ".coyomap").mkdir(parents=True)
        opt_out = os.environ.pop("COYOMAP_NO_SERVE_REGISTER", None)
        try:
            store = RecentsStore(Path(td) / "recents.json")
            register_project(repo / ".coyomap", store=store)
            assert [Path(p).name for p in store.list()] == ["myproj"]   # registered the project root
            register_project(repo, store=store)                          # not a .coyomap dir -> ignored
            assert len(store.list()) == 1
            os.environ["COYOMAP_NO_SERVE_REGISTER"] = "1"                 # opt-out (the eval, the tests)
            store2 = RecentsStore(Path(td) / "recents2.json")
            register_project(repo / ".coyomap", store=store2)
            assert store2.list() == []
        finally:
            if opt_out is None:
                os.environ.pop("COYOMAP_NO_SERVE_REGISTER", None)
            else:
                os.environ["COYOMAP_NO_SERVE_REGISTER"] = opt_out


def test_recents_store_prune_missing_drops_only_folders_that_are_gone() -> None:
    with tempfile.TemporaryDirectory() as td:
        store_path = Path(td) / "recents.json"
        s = RecentsStore(store_path)
        (Path(td) / "here").mkdir()
        s.add(str(Path(td) / "here"))
        s.add(str(Path(td) / "gone"))                      # remembered, then deleted (never made)
        assert [Path(p).name for p in s.prune_missing()] == ["gone"]
        assert [Path(p).name for p in s.list()] == ["here"]
        assert [Path(p).name for p in RecentsStore(store_path).list()] == ["here"]   # persisted
        assert s.prune_missing() == []                        # nothing gone: nothing dropped
        assert [Path(p).name for p in s.list()] == ["here"]


def test_recents_store_set_order() -> None:
    with tempfile.TemporaryDirectory() as td:
        store_path = Path(td) / "recents.json"
        s = RecentsStore(store_path)
        for n in ("a", "b", "c"):
            s.add(str(Path(td) / n))
        names = lambda st: [Path(p).name for p in st.list()]
        assert names(s) == ["c", "b", "a"]                       # most-recent first
        stored = {Path(p).name: p for p in s.list()}             # the actual resolved paths (what the client sends)
        s.set_order([stored["a"], stored["b"], stored["c"]])     # explicit reorder
        assert names(s) == ["a", "b", "c"]
        assert names(RecentsStore(store_path)) == ["a", "b", "c"]  # persisted
        # A partial order: an unknown path is ignored; entries missing from it are appended in place.
        s.set_order([stored["c"], "/nope/zzz"])
        assert names(s) == ["c", "a", "b"]


def test_recents_store_dedupes_same_dir_via_symlink() -> None:
    # The same directory reached two ways (here a symlink; on macOS/Windows also a case difference) must
    # collapse to ONE recents entry — samefile dedup, not string-equality.
    with tempfile.TemporaryDirectory() as td:
        real = Path(td) / "real"
        real.mkdir()
        link = Path(td) / "link"
        try:
            link.symlink_to(real)
        except OSError:
            return  # platform without symlink support -> skip
        s = RecentsStore(Path(td) / "recents.json")
        s.add(str(real))
        s.add(str(link))  # same dir via the symlink -> should replace, not duplicate
        assert len(s.list()) == 1


# --- load_project / build_projects ----------------------------------------------
def test_load_project_valid_and_invalid() -> None:
    with tempfile.TemporaryDirectory() as td:
        good = make_project_dir(Path(td), "alpha")
        proj = load_project(str(good))
        assert proj is not None
        assert proj.title == "MCP Hero (mcpolis)"  # from the fixture map, for the landing card
        assert proj.goal                            # a non-empty goal is carried too
        assert load_project(str(Path(td) / "nope")) is None          # no such folder
        (Path(td) / "bare").mkdir()
        assert load_project(str(Path(td) / "bare")) is None          # folder, but no .coyomap map
        broken = Path(td) / "broken"
        (broken / ".coyomap").mkdir(parents=True)
        (broken / ".coyomap" / "project-map.json").write_text("{ not json", encoding="utf-8")
        assert load_project(str(broken)) is None                     # map won't parse


def test_build_projects_slug_collision_and_skips_invalid() -> None:
    with tempfile.TemporaryDirectory() as td:
        one = make_project_dir(Path(td) / "one", "app")   # .../one/app
        two = make_project_dir(Path(td) / "two", "app")   # .../two/app  -> same folder name
        found = build_projects([str(one), str(two), str(Path(td) / "gone")])
        assert set(found) == {"app", "app-2"}             # collision disambiguated; missing one skipped
        assert found["app"].repo_root == one              # recents order decides who wins the bare name


# --- filesystem browser ---------------------------------------------------------
def test_list_dirs_flags_coyomap_and_parent() -> None:
    with tempfile.TemporaryDirectory() as td:
        parent = Path(td)
        make_project_dir(parent, "withmap")               # .coyomap/project-map.json (valid)
        (parent / "empty-coyomap" / ".coyomap").mkdir(parents=True)  # .coyomap dir, NO map file yet
        (parent / "plain").mkdir()                        # no .coyomap at all
        data = list_dirs(parent)
        assert data["path"] == str(parent)
        assert data["parent"] == str(parent.parent)
        by_name = {e["name"]: e for e in data["entries"]}  # type: ignore[union-attr]
        assert by_name["withmap"]["hasMap"] is True
        assert by_name["empty-coyomap"]["hasMap"] is True  # a bare .coyomap/ is addable (card: "No valid map yet")
        assert by_name["plain"]["hasMap"] is False
        assert _has_coyomap(parent / "empty-coyomap") and not _has_coyomap(parent / "plain")


# --- git-backed file-browser tree -----------------------------------------------
def test_project_tree_from_git() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sha = make_git_repo(root, {"src/app.py": "x = 1\n", "docs/readme.md": "hi\n"})
        (root / ".coyomap").mkdir()
        shutil.copy(_FIXTURE_MAP, root / ".coyomap" / "project-map.json")
        proj = Project(slug=root.name, repo_root=root,
                       map_json=root / ".coyomap" / "project-map.json", commit=sha)
        tree = project_tree(proj)
        assert tree["name"] == root.name and tree["dir"]
        paths = _all_paths(tree)
        assert "src/app.py" in paths and "docs/readme.md" in paths  # the committed git files
        assert proj.tree is not None  # cached on the Project after the first build


def _all_paths(node: FileTreeNode) -> set[str]:
    out = {node["path"]} if not node["dir"] else set()
    for c in node["children"]:
        out |= _all_paths(c)
    return out


def test_project_symbols_flattens_preindex() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".coyomap").mkdir()
        shutil.copy(_FIXTURE_MAP, root / ".coyomap" / "project-map.json")
        preindex = {"symbols": {"by_name": {
            "Widget": [{"file": "src/widget.py", "line": 3, "kind": "class"}],
            "run": [{"file": "src/a.py", "line": 5, "kind": "function"},
                    {"file": "src/b.py", "line": 9, "kind": "function"}],
            "bad": "not-a-list",                                  # skipped: malformed value
        }}}
        (root / ".coyomap" / "preindex.json").write_text(json.dumps(preindex), encoding="utf-8")
        proj = Project(slug=root.name, repo_root=root,
                       map_json=root / ".coyomap" / "project-map.json", commit="abc123")
        syms = project_symbols(proj)
        # one entry per definition SITE; ambiguous names keep every site
        assert {"name": "Widget", "file": "src/widget.py", "line": 3, "kind": "class"} in syms
        assert sum(1 for s in syms if s["name"] == "run") == 2
        assert all(s["name"] != "bad" for s in syms)
        assert proj.symbols is not None  # cached on the Project after the first build


def test_project_symbols_missing_preindex_is_empty() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".coyomap").mkdir()
        shutil.copy(_FIXTURE_MAP, root / ".coyomap" / "project-map.json")
        proj = Project(slug=root.name, repo_root=root,
                       map_json=root / ".coyomap" / "project-map.json", commit="abc123")
        assert project_symbols(proj) == []  # no pre-index -> degrade cleanly, never raise


def test_project_symbols_malformed_preindex_is_empty() -> None:
    # A pre-index whose SHAPE is wrong (not just a bad value inside by_name) must still yield [] and
    # never raise — the endpoint's "never fatal" contract. Covers the AttributeError shapes: a non-dict
    # `symbols`, a non-dict `by_name`, and a top-level non-dict document.
    bad_docs = [
        {"symbols": ["not", "a", "dict"]},   # symbols is a list
        {"symbols": "hello"},                # symbols is a string
        {"symbols": {"by_name": [1, 2, 3]}}, # by_name is a list
        {"symbols": {"by_name": "abc"}},     # by_name is a string
        ["top", "level", "list"],            # whole doc is a list
        "just a string",                     # whole doc is a string
    ]
    for i, doc in enumerate(bad_docs):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".coyomap").mkdir()
            shutil.copy(_FIXTURE_MAP, root / ".coyomap" / "project-map.json")
            (root / ".coyomap" / "preindex.json").write_text(json.dumps(doc), encoding="utf-8")
            proj = Project(slug=f"p{i}", repo_root=root,
                           map_json=root / ".coyomap" / "project-map.json", commit="abc123")
            assert project_symbols(proj) == []  # malformed shape -> empty, not a crash


# --- served view bundle (generic-frontend data) ---------------------------------
def test_project_view_bundle_and_cache() -> None:
    with tempfile.TemporaryDirectory() as td:
        folder = make_project_dir(Path(td), "alpha")
        proj = load_project(str(folder))
        assert proj is not None
        bundle = project_view(proj)
        assert bundle["graph"]["nodes"]                    # the merged graph is present
        assert isinstance(bundle["mermaidContext"], str) and bundle["mermaidContext"]
        assert proj.view is bundle                         # cached on the Project after the first build
        assert project_view(proj) is bundle                # a second call returns the same cached object


def _http_get(port: int, path: str) -> tuple[int, str, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", path)
        r = conn.getresponse()
        return r.status, r.getheader("Content-Type") or "", r.read()
    finally:
        conn.close()


def test_http_static_and_view_routes() -> None:
    # Exercises the real HTTP dispatch: shared static frontend + per-project view bundle.
    with tempfile.TemporaryDirectory() as td:
        folder = make_project_dir(Path(td), "alpha")
        projects = build_projects([str(folder)])
        slug = next(iter(projects))
        Handler.store = RecentsStore(Path(td) / "recents.json")
        Handler.projects = projects
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            port = httpd.server_address[1]
            code, ctype, body = _http_get(port, "/static/viewer.js")
            assert code == 200 and "javascript" in ctype and b"mermaid" in body
            code, ctype, _ = _http_get(port, "/static/viewer.css")
            assert code == 200 and "text/css" in ctype
            assert _http_get(port, "/static/nope.js")[0] == 404       # off-whitelist name rejected
            assert _http_get(port, "/static/../serve.py")[0] == 404   # not a 2-segment /static/<name>
            code, ctype, body = _http_get(port, f"/coyomap/{slug}/api/view")
            assert code == 200 and "application/json" in ctype
            data = json.loads(body)
            assert data["graph"]["nodes"] and data["mermaidContext"]
            assert _http_get(port, "/coyomap/ghost/api/view")[0] == 404     # unknown project
            # A CLEAN BREAK, decided: the old prefix is not redirected, it is an unknown path.
            assert _http_get(port, f"/p/{slug}/")[0] == 404
            assert _http_get(port, f"/p/{slug}/api/view")[0] == 404
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_the_landing_page_forgets_a_folder_that_is_gone() -> None:
    """A remembered folder that no longer exists is dropped from the list when the page loads, not
    shown as a dead card. One that exists with no valid map yet stays, dimmed, as before."""
    with tempfile.TemporaryDirectory() as td:
        live = make_project_dir(Path(td), "alpha")               # a valid map
        unbuilt = Path(td) / "beta"                               # exists, no map yet
        (unbuilt / ".coyomap").mkdir(parents=True)
        gone = Path(td) / "gamma"                                 # never created
        store_path = Path(td) / "recents.json"
        store = RecentsStore(store_path)
        for folder in (gone, unbuilt, live):                       # most recent first: alpha, beta, gamma
            store.add(str(folder))
        Handler.store = store
        Handler.projects = build_projects(store.list())
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            code, ctype, body = _http_get(httpd.server_address[1], "/api/recents")
            assert code == 200 and "application/json" in ctype
            cards = json.loads(body)
            assert [c["name"] for c in cards] == ["alpha", "beta"]
            assert [c["ok"] for c in cards] == [True, False]
            # Dropped from the FILE too, not only from this answer.
            assert [Path(p).name for p in RecentsStore(store_path).list()] == ["alpha", "beta"]
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_live_reload_is_off_unless_dev_is_asked_for() -> None:
    # A person reading a map must not get a page that reloads under them, nor a poll they did not
    # ask for: with no --dev the shell carries no script and the endpoint is not an endpoint.
    with tempfile.TemporaryDirectory() as td:
        folder = make_project_dir(Path(td), "alpha")
        projects = build_projects([str(folder)])
        slug = next(iter(projects))
        Handler.store = RecentsStore(Path(td) / "recents.json")
        Handler.projects = projects
        Handler.dev = False
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            port = httpd.server_address[1]
            code, ctype, body = _http_get(port, f"/coyomap/{slug}/")
            assert code == 200 and "text/html" in ctype
            assert b"api/dev-reload" not in body
            assert _http_get(port, f"/coyomap/{slug}/api/dev-reload")[0] == 404
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_dev_serves_the_shell_with_live_reload_and_a_stamp() -> None:
    # With --dev the shell carries the poll and the endpoint answers a stamp. The stamp is the
    # newest mtime across the frontend files AND the tool's Python, so an edit to either moves it
    # — the Python half is what makes a restart show up on screen.
    with tempfile.TemporaryDirectory() as td:
        folder = make_project_dir(Path(td), "alpha")
        projects = build_projects([str(folder)])
        slug = next(iter(projects))
        Handler.store = RecentsStore(Path(td) / "recents.json")
        Handler.projects = projects
        Handler.dev = True
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            port = httpd.server_address[1]
            code, ctype, body = _http_get(port, f"/coyomap/{slug}/")
            assert code == 200 and "text/html" in ctype
            assert b"api/dev-reload" in body and b"location.reload()" in body
            assert body.index(b"api/dev-reload") > body.index(b"<body")  # inside the document
            # A stale process is about to be killed; reloading from it loads assets from a port
            # that dies mid-request and leaves a blank page nothing will fix.
            assert b"!d.stale" in body, "the page never reloads from a process owed a restart"
            code, ctype, body = _http_get(port, f"/coyomap/{slug}/api/dev-reload")
            assert code == 200 and "application/json" in ctype
            answer = json.loads(body)
            stamp = answer["stamp"]
            assert isinstance(stamp, int) and stamp > 0
            assert isinstance(answer["stale"], bool), "the answer says whether a restart is owed"
            for name in ("viewer.js", "viewer.css", "viewer.html"):
                assert stamp >= (_FRONTEND_DIR / name).stat().st_mtime_ns, \
                    f"{name} is inside the stamp"
            assert stamp >= (_FRONTEND_DIR / "serve.py").stat().st_mtime_ns, \
                "the tool's Python is inside the stamp"
        finally:
            httpd.shutdown()
            httpd.server_close()
            Handler.dev = False


def test_the_live_reload_script_goes_inside_the_document() -> None:
    # Before </body>, so the page it watches has already parsed. A shell without </body> still gets
    # it appended: a hand-edited shell that silently stops reloading is the worse failure.
    assert with_dev_reload("<html><body>hi</body></html>").endswith("</body></html>")
    assert "location.reload()" in with_dev_reload("<html><body>hi</body></html>")
    assert with_dev_reload("<p>no body tag</p>").startswith("<p>no body tag</p>")
    assert "location.reload()" in with_dev_reload("<p>no body tag</p>")
    assert dev_stamp() > 0


# --- runner ---------------------------------------------------------------------
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")


def test_serve_records_its_bound_port_while_it_runs_and_forgets_it_after() -> None:
    """`coyomap url` finds a server through this record and nothing else, so the record must say
    the port the OS actually gave (port 0 asks for any) and must be gone once the server is."""
    with tempfile.TemporaryDirectory() as td:
        running = Path(td) / "running.json"
        got: list[ThreadingHTTPServer] = []
        ready = threading.Event()

        def on_start(h: ThreadingHTTPServer) -> None:
            got.append(h)
            ready.set()

        t = threading.Thread(target=serve, args=([],),
                             kwargs=dict(port=0, store=RecentsStore(Path(td) / "recents.json"),
                                         running_path=running, on_start=on_start), daemon=True)
        t.start()
        assert ready.wait(5), "the server never reported itself started"
        port = got[0].server_address[1]
        assert port != 0
        assert [(r.port, r.pid) for r in running_servers(running)] == [(port, os.getpid())]
        got[0].shutdown()
        t.join(5)
        assert not t.is_alive()
        assert running_servers(running) == []
