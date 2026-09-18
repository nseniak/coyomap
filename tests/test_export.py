#!/usr/bin/env python3
"""The static export: does a folder of files really behave like the served map?

Two halves, and the second is the one that matters.

The first half checks the FILES: every address the page asks for is written, the code comes back at
the path the viewer spells, and no repo path can put a file outside the export folder.

The second half opens a REAL BROWSER on an exported folder served by a plain file server — no
coyomap server anywhere — and drives it. That is the only check that can see the export drift away
from the viewer: a new question `viewer.js` learns to ask the server is a question the export does
not write down, and every file-level assertion here would stay green while a hosted map broke.
`plain_file_server` deliberately uses the stdlib's own static handler, because a static host is
exactly what it is standing in for.

Conventions: top-level test functions, no classes/fixtures (helpers are `make_*` / `_*`).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from browser_harness import new_page
from coyomap.viewer.export import ExportError, _safe_target, export_project, main
from coyomap.viewer.serve import load_project

_FIXTURE_MAP = Path(__file__).resolve().parent / "fixtures" / "mcpolis-project-map.json"

# Every address the page asks a server for, that an export must answer with a file. The code files
# live under api/src/ and are checked separately.
_ADDRESSES = ["api/view", "api/health", "api/tree", "api/symbols", "api/rawmap"]


# --- builders -------------------------------------------------------------------------------------
def make_git_repo(root: Path, files: dict[str, str]) -> str:
    """Init a git repo at `root`, write + commit `files` (path -> text), return the commit SHA."""
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_SYSTEM": "/dev/null"}
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True,  # noqa: E731
                                    capture_output=True, env=env)
    root.mkdir(parents=True, exist_ok=True)
    run("init", "-q")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "init")
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                         capture_output=True, env=env)
    return out.stdout.decode().strip()


def make_git_repo_commit(root: Path, message: str) -> str:
    """Commit whatever is in `root` now, and return the new SHA — for tests that change a repo
    after its first commit."""
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_SYSTEM": "/dev/null"}
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], check=True,
                   capture_output=True, env=env)
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                         capture_output=True, env=env)
    return out.stdout.decode().strip()


def make_mapped_repo(parent: Path, name: str, extra: dict[str, str] | None = None) -> Path:
    """A real git repo holding the fixture map, re-pinned to its own commit — so the export has
    actual code to read, the way a mapped project does."""
    root = parent / name
    files = {"README.md": "# a project\n", "src/app.py": "def run():\n    return 1\n"}
    files.update(extra or {})
    root.mkdir(parents=True, exist_ok=True)
    (root / ".coyomap").mkdir(parents=True, exist_ok=True)
    shutil.copy(_FIXTURE_MAP, root / ".coyomap" / "project-map.json")
    sha = make_git_repo(root, files)
    m = json.loads((root / ".coyomap" / "project-map.json").read_text())
    m["commit"] = sha
    (root / ".coyomap" / "project-map.json").write_text(json.dumps(m))
    return root


@contextmanager
def make_export(extra: dict[str, str] | None = None) -> Iterator[Path]:
    """A mapped repo, exported. Yields the export folder."""
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha", extra)
        proj = load_project(str(root))
        assert proj is not None
        out = Path(td) / "site"
        export_project(proj, out)
        yield out


@contextmanager
def plain_file_server(folder: Path) -> Iterator[str]:
    """The stdlib's own static file handler over `folder` — a stand-in for any web host. It runs no
    coyomap code at all, which is the point: whatever the page manages here, it manages on GitHub
    Pages."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(folder))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    finally:
        httpd.shutdown()
        httpd.server_close()


@contextmanager
def _page(url: str) -> Iterator[Any]:
    """A Chromium page on `url`, with JS errors collected on `js_errors`."""
    # ONE browser per process, a fresh PAGE per test (see tests/browser_harness.py).
    page = new_page()
    page.goto(url)
    if url.startswith("file:"):
        # The viewer never boots here — that IS the case under test. Wait for the shell's own
        # guard instead of a screen the page cannot reach.
        page.wait_for_timeout(1200)
    else:
        page.wait_for_selector("#crumb h1", state="attached")
    try:
        yield page
    finally:
        page.close()


# --- the files ------------------------------------------------------------------------------------
def test_the_export_answers_every_address_the_page_asks_for() -> None:
    """A missing one is a screen that breaks only once the map is hosted."""
    with make_export() as out:
        assert (out / "index.html").is_file()
        assert (out / "viewer.js").is_file() and (out / "viewer.css").is_file()
        for addr in _ADDRESSES:
            assert (out / addr).is_file(), f"{addr} not written"


def test_a_shared_copy_has_no_update_log_tab_and_a_direct_link_says_why() -> None:
    """A static copy has no server to read the update logs from, so the Update log group is not
    drawn, and a link pasted from the live map (`#v=updates`) says the copy carries no log rather
    than "No update yet" with instructions to run one."""
    with make_export() as out, plain_file_server(out) as url, _page(url + "#v=updates") as page:
        page.wait_for_timeout(900)
        groups = page.evaluate("() => [...document.querySelectorAll('#groupsw button')].map((b) => b.textContent)")
        assert "Update log" not in groups, groups
        text = str(page.evaluate("() => document.getElementById('diagram').textContent"))
        assert "shared copy carries no update log" in text and "No update yet" not in text
        assert not page.js_errors, page.js_errors


def test_the_shell_asks_for_its_script_and_style_relatively() -> None:
    """An absolute /static/ path works on a server rooted at / and nowhere else — a map published
    under https://host/repo/map/ would load no script and no stylesheet at all."""
    with make_export() as out:
        html = (out / "index.html").read_text()
        assert '"viewer.css"' in html and '"viewer.js"' in html
        assert "/static/" not in html


def test_the_exported_bundle_says_it_is_exported() -> None:
    """The one flag the page reads to know there is no server behind it."""
    with make_export() as out:
        assert json.loads((out / "api/view").read_text())["exported"] is True


def test_the_code_is_written_where_the_viewer_asks_for_it() -> None:
    """The `.txt` is the safety suffix, not a typo: a host must never serve a repo's own file as a
    live page (see the .html test below). Both halves have to agree or the code viewer 404s."""
    with make_export() as out:
        assert (out / "api/src/src/app.py.txt").read_text() == "def run():\n    return 1\n"
        assert (out / "api/src/README.md.txt").read_text() == "# a project\n"
        assert not (out / "api/src/src/app.py").exists(), "an unsuffixed copy defeats the point"


def test_the_map_itself_ships_byte_for_byte() -> None:
    """The map inspector reads the STORED map, so a re-serialised copy would name different slots."""
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha")
        proj = load_project(str(root))
        assert proj is not None
        out = Path(td) / "site"
        export_project(proj, out)
        assert (out / "api/rawmap").read_bytes() == (root / ".coyomap/project-map.json").read_bytes()


def test_a_repo_path_can_never_write_outside_the_export() -> None:
    """The write-side guard. Reading a traversal path is refused by the server; writing one would
    scatter a repo's files across the publisher's disk, which is worse and permanent."""
    with tempfile.TemporaryDirectory() as td:
        dest = (Path(td) / "site" / "api" / "src")
        dest.mkdir(parents=True)
        dest = dest.resolve()
        for bad in ["../escape.txt", "../../escape.txt", "/etc/passwd", "a/../../b", ""]:
            assert _safe_target(dest, bad) is None, f"{bad!r} was allowed out"
        ok = _safe_target(dest, "deep/nested/file.py")
        assert ok is not None and dest in ok.parents


def test_the_export_reports_a_map_with_no_symbols() -> None:
    """Search still works without a pre-index; it just finds no classes or functions. The command
    says so rather than leaving the publisher to discover it on the hosted page."""
    with make_export() as out:
        assert json.loads((out / "api/symbols").read_text())["symbols"] == []


def test_export_refuses_a_folder_that_already_holds_something() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha")
        out = Path(td) / "site"
        out.mkdir()
        (out / "someone-elses-work.txt").write_text("do not scatter files over me")
        assert main([str(root), "--out", str(out)]) == 1
        assert not (out / "index.html").exists()
        assert main([str(root), "--out", str(out), "--force"]) == 0
        assert (out / "index.html").is_file()
        assert (out / "someone-elses-work.txt").is_file()  # --force adds, it does not wipe


def test_export_names_the_project_after_its_folder_not_the_cwd() -> None:
    """`coyomap export .` must not produce a site that calls the project "project"."""
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha")
        out = Path(td) / "site"
        assert main([str(root) + "/.", "--out", str(out)]) == 0   # a path git would call "."
        assert json.loads((out / "api/health").read_text())["project"] == "alpha"


def test_export_refuses_a_map_with_no_commit() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha")
        f = root / ".coyomap" / "project-map.json"
        m = json.loads(f.read_text())
        m["commit"] = ""
        f.write_text(json.dumps(m))
        assert main([str(root), "--out", str(Path(td) / "site")]) == 1


def test_a_framing_mistake_stops_the_export_instead_of_writing_wrong_files() -> None:
    """The guard on `git cat-file --batch`: a size or id that does not match what `ls-tree` said
    would put one file's bytes under another file's name, and the folder would look complete."""
    from coyomap.viewer import export as export_mod
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha")
        rows = export_mod._ls_tree(root, load_project(str(root)).commit)  # type: ignore[union-attr]
        assert rows, "the fixture repo should have files"
        lied = [(p, "0" * 40, s) for p, _oid, s in rows]  # ids git will not return
        dest = Path(td) / "dest"
        dest.mkdir()
        with pytest.raises(ExportError):
            export_mod._write_blobs(root, lied, dest.resolve(),
                                    export_mod.ExportReport(out=dest, slug="a", commit="b"))


# --- what the adversarial review found (2026-09-13) ----------------------------------------------
def test_a_name_that_is_not_plain_ascii_survives_the_export() -> None:
    """`git ls-tree` C-QUOTES any path that is not printable ASCII unless it is asked for `-z`, so
    `café.txt` arrived as the literal `"caf\\303\\251.txt"`, failed the write guard, and was left out
    — silently, while the served map had the file. Served-versus-exported drift, which is the one
    thing this module exists not to do. It also moved with the publisher's own `core.quotePath`."""
    names = {"café.txt": "accented\n", "sub/שלום.txt": "hebrew\n", "sp ace.py": "spaced\n"}
    with make_export(extra=names) as out:
        for name, body in names.items():
            assert (out / "api/src" / (name + ".txt")).read_text() == body, f"{name} was dropped"


def test_the_export_carries_ONLY_what_is_committed_at_the_maps_commit() -> None:
    """THE SAFETY PROPERTY THAT MAKES PUBLISHING AN EXPORT SANE. Everything in the folder comes out
    of `git ls-tree` at the map's pin, so a gitignored `.env`, an untracked scratch file and an
    uncommitted working-tree edit are all absent by construction rather than by a filter someone has
    to maintain. Worth a test of its own: the day this reads the working tree instead, a publisher's
    secrets go onto a web host and nothing else would notice."""
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha", extra={"committed.txt": "tracked\n"})
        # every one of these lands AFTER the commit the map is pinned to
        (root / ".gitignore").write_text("ignored.txt\n")
        (root / "ignored.txt").write_text("ZZMARKER-gitignored")
        (root / "untracked.txt").write_text("ZZMARKER-untracked")
        (root / "committed.txt").write_text("ZZMARKER-worktree-edit")
        out = Path(td) / "site"
        assert main([str(root), "--out", str(out)]) == 0
        src = out / "api/src"
        for absent in ("ignored.txt.txt", "untracked.txt.txt", ".gitignore.txt"):
            assert not (src / absent).exists(), f"{absent} reached the export"
        assert (src / "committed.txt.txt").read_text() == "tracked\n", \
            "the working-tree edit was published instead of the committed content"
        # Belt and braces: no planted marker reached ANY exported file, under any name.
        body = "\n".join(f.read_text(errors="replace") for f in src.rglob("*") if f.is_file())
        assert "ZZMARKER" not in body, "an uncommitted marker reached the export"


def test_a_symlink_in_the_output_cannot_redirect_a_write_outside_it() -> None:
    """`--force` writes into a folder somebody else filled. A symlink sitting at a file's own name
    was followed straight out and OVERWROTE what it pointed at — the parent chain was checked, the
    file itself never was."""
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha")
        victim = Path(td) / "victim.txt"
        victim.write_text("ORIGINAL VICTIM CONTENT")
        out = Path(td) / "site"
        (out / "api" / "src").mkdir(parents=True)
        (out / "api" / "src" / "README.md.txt").symlink_to(victim)
        assert main([str(root), "--out", str(out), "--force"]) == 0
        assert victim.read_text() == "ORIGINAL VICTIM CONTENT", "the export wrote through a symlink"
        assert (out / "api/src/README.md.txt").read_text() == "# a project\n"


def test_a_symlinked_folder_in_the_output_makes_no_directories_outside_it() -> None:
    """The same mistake one level up: `mkdir(parents=True)` followed a symlinked directory and
    created folders outside the export before anything checked."""
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha")
        outside = Path(td) / "outside"
        outside.mkdir()
        out = Path(td) / "site"
        (out / "api" / "src").mkdir(parents=True)
        (out / "api" / "src" / "sub").symlink_to(outside)
        main([str(root), "--out", str(out), "--force"])
        assert list(outside.iterdir()) == [], f"wrote outside the export: {list(outside.iterdir())}"


def test_a_committed_html_file_is_never_served_as_a_live_page() -> None:
    """A served map hands every source file back as text/plain, so nothing in it can run. An export
    hands the host raw bytes and the host guesses from the file ending — so a repo with an `.html`
    in it published that file as LIVE SCRIPT on the map's own address, and on GitHub Pages one
    person's sites all share a single origin."""
    page_html = "<script>window.PWNED = 1</script>"
    with make_export(extra={"page.html": page_html, "doc.svg": "<svg onload='window.PWNED=1'/>"}) as out:
        assert not (out / "api/src/page.html").exists(), "an .html a host would run"
        assert (out / "api/src/page.html.txt").read_text() == page_html
        with plain_file_server(out) as url:
            for name in ("page.html.txt", "doc.svg.txt"):
                with urlopen(url + "api/src/" + name) as r:
                    ctype = r.headers.get("Content-Type", "")
                assert "html" not in ctype and "svg" not in ctype, f"{name} came back as {ctype}"


def test_a_re_export_does_not_keep_a_file_the_project_no_longer_has() -> None:
    """An export ADDS and REPLACES. It used to keep every file a previous run wrote, so a secret
    deleted from the project stayed in the published folder — still served, and no longer listed in
    the file browser, so nobody could see it from inside the map."""
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha", extra={"secrets.txt": "API_KEY=hunter2\n"})
        out = Path(td) / "site"
        assert main([str(root), "--out", str(out)]) == 0
        assert (out / "api/src/secrets.txt.txt").is_file()
        # the project drops the file and is re-pinned, the way a real removal lands
        (root / "secrets.txt").unlink()
        sha = make_git_repo_commit(root, "drop the secret")
        f = root / ".coyomap" / "project-map.json"
        m = json.loads(f.read_text())
        m["commit"] = sha
        f.write_text(json.dumps(m))
        assert main([str(root), "--out", str(out), "--force"]) == 0
        assert not (out / "api/src/secrets.txt.txt").exists(), "the deleted secret is still published"


def test_a_map_pinned_to_a_commit_this_clone_lacks_refuses_instead_of_exporting_nothing() -> None:
    """Zero files is never a real map. It used to write a whole site with an empty code viewer and
    exit 0, so an automated publish reported success and the reader found every file missing."""
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha")
        f = root / ".coyomap" / "project-map.json"
        m = json.loads(f.read_text())
        m["commit"] = "0" * 40          # a well-formed SHA this repo does not have
        f.write_text(json.dumps(m))
        assert main([str(root), "--out", str(td + "/site")]) == 1


def test_files_left_out_make_the_command_exit_non_zero() -> None:
    """Exit 0 told a scheduled publish everything was written while the file browser had holes."""
    from coyomap.viewer import export as export_mod
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha", extra={"big.bin": "x" * 4096})
        out = Path(td) / "site"
        original = export_mod.TEXT_MAX
        export_mod.TEXT_MAX = 100       # everything but the tiniest file is now "too large"
        try:
            assert main([str(root), "--out", str(out)]) == 1
        finally:
            export_mod.TEXT_MAX = original


def test_the_published_page_does_not_carry_the_publishers_own_folder_path() -> None:
    """`repoRoot` is where the project sits on the machine that built the map. Served locally that
    is the reader's own path; published it tells everyone the person's home directory, in plain
    text in `api/view` and pre-filled in the viewer's settings box."""
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha")
        out = Path(td) / "site"
        assert main([str(root), "--out", str(out)]) == 0
        bundle = json.loads((out / "api/view").read_text())
        assert bundle["repoRoot"] == ""
        assert str(root) not in (out / "api/view").read_text()


def test_a_zero_byte_file_and_one_with_no_final_newline_both_survive() -> None:
    """Both walk the `git cat-file --batch` framing reader past its edges: an empty payload, and a
    payload whose last byte is not the LF the protocol adds."""
    with make_export(extra={"empty.txt": "", "noeol.txt": "no newline at the end"}) as out:
        assert (out / "api/src/empty.txt.txt").read_bytes() == b""
        assert (out / "api/src/noeol.txt.txt").read_text() == "no newline at the end"


def test_the_served_map_refuses_encoded_traversal_too() -> None:
    """The plain form was tested; the percent-encoded one is the form that actually gets tried,
    because segments are decoded BEFORE they are rejoined and guarded."""
    from coyomap.viewer.recents import RecentsStore
    from coyomap.viewer.serve import Handler, build_projects
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha")
        projects = build_projects([str(root)])
        slug = next(iter(projects))
        Handler.store = RecentsStore()
        Handler.projects = projects
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}/coyomap/{slug}/api/src/"
        try:
            for bad in ("..%2f..%2fetc%2fpasswd", "%2e%2e/%2e%2e/etc/passwd",
                        "%252e%252e/etc/passwd", "..%00/etc/passwd", "/etc/passwd"):
                try:
                    with urlopen(base + bad) as r:
                        body = r.read()
                    raise AssertionError(f"{bad} was served: {body[:60]!r}")
                except HTTPError as e:
                    assert e.code in (400, 404), f"{bad} answered {e.code}"
        finally:
            httpd.shutdown()
            httpd.server_close()


# --- the browser, over a plain file server ----------------------------------------------------------
def test_a_hosted_map_renders_and_navigates() -> None:
    with make_export() as out, plain_file_server(out) as url, _page(url) as page:
        page.evaluate("() => document.querySelector('[data-view=\"glossary\"]').click()")
        page.wait_for_timeout(700)
        assert page.evaluate("() => location.hash") == "#v=glossary"
        assert "Glossary" in str(page.evaluate(
            "() => (document.getElementById('crumb').textContent || '').trim()"))
        assert not page.js_errors, page.js_errors


def test_a_hosted_map_keeps_your_place_on_reload() -> None:
    """A shareable link is the whole reason the export exists."""
    with make_export() as out, plain_file_server(out) as url, _page(url) as page:
        page.evaluate("() => document.querySelector('[data-view=\"glossary\"]').click()")
        page.wait_for_timeout(700)
        page.reload()
        page.wait_for_selector("#crumb h1", state="attached")
        page.wait_for_timeout(700)
        assert page.evaluate("() => location.hash") == "#v=glossary"
        assert not page.js_errors, page.js_errors


def open_a_file_in_the_code_viewer(page: Any, name: str) -> str:
    """Drive the REAL file browser: open the source column, switch to Files, click `name`, and
    return what the code viewer shows.

    Deliberately not a hand-written `fetch('api/src/…')`. Spelling the address in the test is what
    let the address builder go unexercised: its encoding could be deleted whole and every test still
    passed, because no test ever went through it."""
    page.evaluate("() => { const r = document.getElementById('srcrail'); if (r) r.click(); }")
    page.wait_for_timeout(400)
    page.evaluate("() => { const f = document.getElementById('srcsw-files'); if (f) f.click(); }")
    page.wait_for_timeout(600)
    clicked = page.evaluate(
        "(n) => { const row = [...document.querySelectorAll('#srcpanes .trow')]"
        ".find(e => (e.querySelector('.tname') || {}).textContent === n);"
        " if (!row) return false; row.click(); return true; }", name)
    assert clicked, f"{name} was not in the file browser"
    page.wait_for_timeout(1200)
    return str(page.evaluate("() => document.getElementById('codeview').textContent || ''"))


def test_a_hosted_map_shows_the_source_column_and_loads_a_file() -> None:
    """The code viewer is the half of the export that needed a new address, so it is the half most
    likely to break. Driven through the UI, so the address builder is on the hook."""
    with make_export() as out, plain_file_server(out) as url, _page(url) as page:
        assert page.evaluate("() => document.body.classList.contains('served')"), \
            "the source column never revealed itself — api/health was not reachable"
        shown = open_a_file_in_the_code_viewer(page, "README.md")
        assert "a project" in shown, shown[:300]
        assert not page.js_errors, page.js_errors


def test_a_hosted_map_offers_no_impact_explorer_and_no_way_back_to_a_server() -> None:
    """Both need a coyomap server. Offering either on a hosted page is a dead control."""
    with make_export() as out, plain_file_server(out) as url, _page(url) as page:
        assert page.evaluate("() => document.getElementById('impactctl').hidden") is True
        assert page.evaluate("() => !!document.querySelector('header .brand.home-link')") is False
        assert not page.js_errors, page.js_errors


def test_a_hosted_map_works_in_a_SUBFOLDER_of_the_site() -> None:
    """The GitHub Pages shape: https://user.github.io/<repo>/<folder>/, not the site root. Every
    address the page asks for is relative to its own directory, and this is the test that says so —
    an absolute one would 404 here while passing every root-served check above."""
    with make_export() as out:
        site = out.parent / "pages"
        (site / "myrepo").mkdir(parents=True)
        shutil.copytree(out, site / "myrepo" / "map")
        with plain_file_server(site) as base, _page(base + "myrepo/map/") as page:
            assert page.evaluate("() => document.body.classList.contains('served')"), \
                "the page could not reach its own api/ from a subfolder"
            assert page.evaluate(
                "() => getComputedStyle(document.querySelector('header')).display") != "block", \
                "the stylesheet did not load from a subfolder"
            shown = open_a_file_in_the_code_viewer(page, "README.md")
            assert "a project" in shown, shown[:300]
            assert not page.js_errors, page.js_errors


def test_a_hosted_map_never_asks_for_an_address_the_export_did_not_write() -> None:
    """THE DRIFT GATE. Every request the page makes to its own origin is recorded; any that 404s is
    a question `viewer.js` learned to ask and the export does not answer. Without this, the export
    rots silently as the viewer grows, and only a person opening a hosted map would find out."""
    with make_export() as out, plain_file_server(out) as url, _page(url) as page:
        misses: list[str] = []
        page.on("response", lambda r: misses.append(f"{r.status} {r.url}") if r.status >= 400 else None)
        # Walk every view the map offers, which is where the page asks for what it needs.
        views = page.evaluate(
            "() => [...document.querySelectorAll('[data-view]')].map(b => b.dataset.view)")
        for v in views:
            page.evaluate(f"() => {{ const b = document.querySelector('[data-view=\"{v}\"]');"
                          f" if (b) b.click(); }}")
            page.wait_for_timeout(350)
        page.evaluate("() => { const s = document.getElementById('srcrail'); if (s) s.click(); }")
        page.wait_for_timeout(600)
        assert not misses, f"the hosted map asked for something the export did not write: {misses}"
        assert not page.js_errors, page.js_errors


def test_opening_the_export_as_a_local_file_says_what_to_do() -> None:
    """THE FIRST THING ANYONE DOES with a folder of files is double-click index.html, and a browser
    refuses to run a module script off the disk — so `viewer.js` never executes and cannot report
    anything. Without the shell's own inline guard the reader gets the bare shell, tabs and all, and
    no explanation. That is exactly what happened the first time someone opened one."""
    with make_export() as out:
        with _page((out / "index.html").as_uri()) as page:
            text = str(page.evaluate("() => document.body.innerText"))
            assert "has to be served" in text, text[:500]
            # all three servers, each its own block with its own Copy — you run ONE of them
            cmds = page.evaluate("() => [...document.querySelectorAll('.cycmd pre')].map(e => e.textContent)")
            assert sum("http.server" in c for c in cmds) == 1, cmds
            assert sum(c.startswith("ruby ") for c in cmds) == 1, cmds
            assert sum(c.startswith("npx ") for c in cmds) == 1, cmds
            assert page.evaluate("() => document.querySelectorAll('.cycmd .cycopy').length") == len(cmds)
            assert page.evaluate("() => document.querySelectorAll('.cyor').length") == 2
            # the address is a LINK, not text to retype
            assert page.evaluate(
                "() => !!document.querySelector('.cylink a[href=\"http://localhost:8000/\"]')")


def test_the_local_file_page_names_the_folder_it_is_actually_in() -> None:
    """The page works its own folder out from its own address, so a folder the reader MOVED or
    renamed still prints the right `cd`. A space in the name is the case that breaks naive quoting,
    and \"my maps\" is not an exotic thing to call a folder."""
    with make_export() as out:
        moved = out.parent / "my maps" / "coyomap map"
        moved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(out, moved)
        with _page((moved / "index.html").as_uri()) as page:
            cmds = page.evaluate("() => [...document.querySelectorAll('.cycmd pre')].map(e => e.textContent)")
            cd = [c for c in cmds if c.startswith("cd ")]
            assert len(cd) == 1, cmds
            # shell-quoted, so the path survives its spaces when pasted
            assert cd[0] == f"cd '{moved}'", cd[0]


def test_the_local_file_page_copies_a_command_to_the_clipboard() -> None:
    """The Copy button is the point of splitting the blocks — a long path is what nobody wants to
    retype. Clicked here for real, then read back out of the clipboard."""
    with make_export() as out:
        with _page((out / "index.html").as_uri()) as page:
            page.context.grant_permissions(["clipboard-read", "clipboard-write"])
            page.evaluate("() => document.querySelectorAll('.cycmd .cycopy')[0].click()")
            page.wait_for_timeout(300)
            assert page.evaluate("() => document.querySelectorAll('.cycmd .cycopy')[0].textContent") \
                == "Copied"
            got = page.evaluate("async () => await navigator.clipboard.readText()")
            assert str(got) == f"cd '{out}'", got


def test_the_local_file_page_shows_nothing_of_the_dead_shell() -> None:
    """Not one control in the shell works without the script, so a tab bar you can click that
    answers nothing is worse than no tab bar. Covering it was tried and leaked: the source rail is
    `position:fixed` under a static parent, so it escapes to the viewport and competes with the
    overlay whatever z-index the overlay carries."""
    with make_export() as out:
        with _page((out / "index.html").as_uri()) as page:
            leaked = page.evaluate("""() => [...document.querySelectorAll('header, #srcrail, """
                                   """[data-view], [data-group]')]
                .filter(e => e.getClientRects().length > 0).map(e => e.id || e.tagName)""")
            assert leaked == [], f"the dead shell is still on screen: {leaked}"


def test_the_export_ships_no_script_of_its_own() -> None:
    """The launcher was tried and removed: an export is files a web host serves, and a shell script
    in it is a thing to explain, to trust, and to keep working on three platforms."""
    with make_export() as out:
        assert not list(out.glob("*.command")), "an export must not ship an executable"
        assert not list(out.glob("*.sh"))


def test_a_served_export_never_shows_the_boot_guard() -> None:
    """The guard must not fire on a working page: the module sets the flag it watches for."""
    with make_export() as out, plain_file_server(out) as url, _page(url) as page:
        assert page.evaluate("() => window.__coyomapBooted") is True
        assert "has to be served" not in str(page.evaluate("() => document.body.innerText"))
        assert "could not start" not in str(page.evaluate("() => document.body.innerText"))


# --- the served viewer still works ------------------------------------------------------------------
def test_the_served_map_redirects_its_bare_address_to_the_slash_form() -> None:
    """Everything the page asks for is relative to its own directory now, so the slash is load-
    bearing: without it the browser drops the slug and every request resolves one level too high."""
    from coyomap.viewer.recents import RecentsStore
    from coyomap.viewer.serve import Handler, build_projects
    with tempfile.TemporaryDirectory() as td:
        root = make_mapped_repo(Path(td), "alpha")
        projects = build_projects([str(root)])
        slug = next(iter(projects))
        Handler.store = RecentsStore()
        Handler.projects = projects
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            with urlopen(f"{base}/coyomap/{slug}") as r:   # urllib follows the 301
                assert r.url.endswith(f"/coyomap/{slug}/")
            for name in ("viewer.js", "viewer.css"):       # the relative assets, under the map path
                with urlopen(f"{base}/coyomap/{slug}/{name}") as r:
                    assert r.status == 200 and r.length
            with urlopen(f"{base}/coyomap/{slug}/api/src/src/app.py") as r:
                assert r.read().decode() == "def run():\n    return 1\n"
            for bad in ("api/src/../../../etc/passwd", "api/src/"):
                try:
                    urlopen(f"{base}/coyomap/{slug}/{bad}")
                    raise AssertionError(f"{bad} was served")
                except HTTPError as e:
                    assert e.code == 400
        finally:
            httpd.shutdown()
            httpd.server_close()
