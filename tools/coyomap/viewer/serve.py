#!/usr/bin/env python3
"""Local multi-project server for coyomap maps — the whole viewer's backend.

The interactive viewer is served, not baked into a file. For each project this server serves:

  * a generic shell (``viewer.html``) + shared frontend assets (``viewer.js`` / ``viewer.css`` from
    ``/static/``) — identical for every map;
  * the map's own data at ``/coyomap/<project>/api/view`` — the graph + every pre-rendered diagram, flow,
    and config flag (``gen_viewer.build_view_bundle``), which the frontend fetches and renders;
  * its own address, as a path: ``/coyomap/<project>/`` (``MAP_ROUTE``, the one definition), which the
    landing page's cards and ``coyomap url`` read from here rather than spell themselves;
  * the file browser + code viewer, both read from git AT THE MAP'S COMMIT (``/api/tree`` /
    ``/api/src``) by default, so what you see always matches the map. ONE scoped exception:
    ``/api/src?at=<sha>|WORKTREE`` serves a file at another commit or from the working tree — the
    impact explorer needs to show both ends of an arbitrary diff. Worktree reads are guarded
    (realpath containment, ``.git/`` excluded, tracked-or-untracked-not-ignored only).

The server does NOT scan the disk. You pick a project folder (one holding ``.coyomap/project-map.json``)
through the landing page's built-in folder browser; the choice is remembered in a small recents file
(``~/.coyomap/serve-recents.json``). On the next start the recents are shown, each openable or
removable, and one whose folder is gone from disk is dropped the moment the landing page loads.
While it runs, the server also records its port and process id beside that file
(``serve-running.json``, see ``running.py``), which is how ``coyomap url`` finds it. Files come from ``git ls-tree`` / ``git show <commit>:<path>``, so the view is a frozen
snapshot of the mapped commit and local edits never leak in.

Stdlib only (``http.server`` + ``subprocess``) — no third-party import, so this stays inside the
render dependency firewall (see internal/docs/design-notes.md). ``coyomap serve`` is the entry point.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import threading
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlparse

from coyomap.impact_git import WORKTREE as IMPACT_WORKTREE
from coyomap.impact_git import PREINDEX_JSON, compute_impact, load_map_extents
from coyomap.impact_git import resolve_ref as impact_resolve_ref
from coyomap.impact_ripple import RippleOptions, build_impact_result
from coyomap.model import old_map_folder_hint
from coyomap.viewer.compare import (
    LOG_FORMAT, MapVersion, compare_payload, history_payload, load_map_doc, parse_history,
    parse_ref, version_label,
)
from coyomap.model import ModelError, load_model
from coyomap.viewer.diffmap import DiffRow, parse_unified_diff
from coyomap.viewer.filetree import FileTreeNode, build_tree, node_path_index, resolved_path_index
from coyomap.viewer.gen_viewer import ViewBundle, build_view_bundle, repo_state
from coyomap.viewer.recents import RecentsStore
from coyomap.viewer.running import RUNNING_PATH, forget_running, note_running
from coyomap.views import model_to_graph

MAP_JSON = "project-map.json"
# `PREINDEX_JSON` is re-exported from impact_git — one home for the filename, since the extents
# reader there resolves the same file.
_DEFAULT_PORT = 8765
# The first segment of every map address: ``/coyomap/<slug>/…``. The tool's own name, so a link
# pasted anywhere says what produced it — the port cannot, since a real session rarely runs on the
# default one. THE ONE DEFINITION: the router, the landing page's cards and `coyomap url` all read
# it from here. The old ``/p/`` prefix answers 404 like any unknown path (a clean break, decided).
MAP_ROUTE = "coyomap"


def map_url(slug: str) -> str:
    """A project's map address, as a path: ``/coyomap/<slug>/``. No host or port — those belong to
    whichever server is running, and only it knows them."""
    return f"/{MAP_ROUTE}/{quote(slug, safe='')}/"


# The generic frontend assets (shell + viewer.js/css) live next to this module and are served as-is,
# shared by every project — the per-project data arrives separately via /coyomap/<slug>/api/view.
_FRONTEND_DIR = Path(__file__).resolve().parent
_STATIC_FILES = {  # exact-name whitelist (no path traversal possible) -> content type
    "viewer.js": "text/javascript; charset=utf-8",
    "viewer.css": "text/css; charset=utf-8",
    # The product's mark. Here rather than inline in each page for the reason viewer.html gives, and
    # in THIS table so the one entry feeds three readers at once: this server, the project index's
    # /static/ path, and `coyomap export`, which copies everything the table names.
    "favicon.png": "image/png",
}
_STATE_LOCK = threading.Lock()  # guards recents mutation + the derived projects map


@dataclass
class Project:
    """One served map: its slug (URL segment), repo root, the model file, and the map's commit.

    ``commit`` is the SHA every git read is pinned to — ``-dirty`` stripped, since a working-tree
    marker isn't a real ref. ``tree``/``view``/``symbols`` cache their built artifacts lazily, keyed
    to one map version: ``map_mtime`` records the model file's st_mtime_ns at load, and
    ``ensure_fresh`` drops the caches (and re-reads commit/title/goal) when the file changes — so an
    edited map (a Direct map change, an Accept, a re-balance) shows up on the next refresh without
    restarting the server."""

    slug: str
    repo_root: Path
    map_json: Path
    commit: str
    title: str = ""   # the map's human title (shown on the landing card) — folder name if the map has none
    goal: str = ""    # the map's one-paragraph goal (shown, clamped, under the title)
    map_mtime: int | None = None      # st_mtime_ns of map_json when loaded — the staleness key
    tree: FileTreeNode | None = None  # cached tree (built once per map version, on first /api/tree)
    view: ViewBundle | None = None    # cached view bundle (built once per map version, on first /api/view)
    symbols: list[dict[str, object]] | None = None  # cached code symbols (built once per map version)
    #: `api/compare` answers by commit ref, cached per map version: a commit's map never changes, and
    #: the served side is dropped with the other caches when the map file does.
    compare_cache: dict[str, dict[str, Any]] = field(default_factory=dict)


def _strip_dirty(commit: str) -> str:
    """Drop a ``-dirty`` suffix so the SHA is a real ref git can resolve (mirrors the viewer)."""
    return commit[:-6] if commit.endswith("-dirty") else commit


_SHA_RE = re.compile(r"[0-9a-fA-F]{7,64}")


def _valid_commit(commit: str) -> bool:
    """True only for a bare hex SHA. Guards the git calls: a commit read from the map JSON that is
    empty, malformed, or (crucially) starts with ``-`` must never reach git's argv, where a leading
    dash would be parsed as a flag rather than a revision (argument injection)."""
    return bool(_SHA_RE.fullmatch(commit))


def _has_coyomap(folder: Path) -> bool:
    """True if `folder` holds a `.coyomap/` directory — the marker of a coyomap project. The map inside
    may be missing or not yet valid; such a folder is still addable (its recents card then shows
    'No valid map yet' and stays disabled until the map is built)."""
    try:
        return (folder / ".coyomap").is_dir()
    except OSError:
        return False


def load_project(folder: str) -> Project | None:
    """Build a Project from a folder holding a valid map, or None if the map is missing/unloadable.
    A recents entry whose map broke is simply not served: it stays in the list, dimmed, so the user can
    rebuild or remove it. One whose FOLDER went away is pruned by the landing page (`prune_missing`)."""
    root = Path(folder)
    map_json = root / ".coyomap" / MAP_JSON
    if not map_json.is_file():
        return None
    try:
        graph = model_to_graph(load_model(map_json.read_text(encoding="utf-8")))
    except (ModelError, OSError, ValueError):
        return None
    commit = _strip_dirty(str(graph.get("commit") or "").strip())
    if commit and not _valid_commit(commit):
        return None
    try:
        mtime: int | None = map_json.stat().st_mtime_ns
    except OSError:
        mtime = None
    return Project(slug=root.name or "project", repo_root=root, map_json=map_json, commit=commit,
                   title=str(graph.get("title") or "").strip() or (root.name or "project"),
                   goal=str(graph.get("goal") or "").strip(), map_mtime=mtime)


# ── stale-process guard ──────────────────────────────────────────────────────────────────────────
# `viewer.js` / `viewer.css` are read from disk per request and sent `no-store`, so a frontend edit is
# already live on the next refresh. The BUNDLE is not: it is built by this process's Python, cached
# per map version, and no cache-drop can pick up an edit to code that is already imported. Nothing
# said so, which is the whole problem — a session spent three restarts discovering, each time, that
# the page was showing what the old code produced. Now the server says it, once per change.
_PY_SOURCES = Path(__file__).resolve().parent.parent   # tools/coyomap/
_STALE_CHECK_EVERY_NS = 2_000_000_000                  # at most one directory walk every 2s


def _sources_stamp() -> int:
    """Newest mtime across this tool's Python sources — 0 when the tree cannot be read."""
    newest = 0
    try:
        for f in _PY_SOURCES.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            try:
                newest = max(newest, f.stat().st_mtime_ns)
            except OSError:
                continue
    except OSError:
        return 0
    return newest


_STARTED_STAMP = _sources_stamp()
_LAST_STALE_CHECK = 0
_STALE_REPORTED = 0


def warn_if_code_changed() -> bool:
    """Say (once per change, on the console) that this process is serving OLD Python.

    Returns whether the sources have moved since startup. Deliberately a WARNING and not a reload:
    re-importing a live module graph mid-request is how a server starts answering from two versions
    of itself at once. The operator restarts; the point is that they know to."""
    global _LAST_STALE_CHECK, _STALE_REPORTED
    now = time.monotonic_ns()
    if now - _LAST_STALE_CHECK < _STALE_CHECK_EVERY_NS:
        return _STALE_REPORTED > _STARTED_STAMP
    _LAST_STALE_CHECK = now
    stamp = _sources_stamp()
    if stamp <= _STARTED_STAMP:
        return False
    if stamp > _STALE_REPORTED:
        _STALE_REPORTED = stamp
        print("coyomap serve: this process is running OLD code — a Python source under "
              f"{_PY_SOURCES.name}/ changed since startup. The frontend (viewer.js/css) reloads on "
              "refresh, but the view bundle is built in-process: RESTART to see server-side changes.",
              file=sys.stderr)
    return True


# ── live reload, DEV ONLY (--dev) ────────────────────────────────────────────────────────────────
# Off by default and never reachable without the flag: a user reading a map must not have their page
# reloaded under them, and must not carry a poll they did not ask for.
#
# With --dev the shell gets one small script that polls `api/dev-reload` for a STAMP — the newest
# mtime across the frontend assets AND this tool's Python — and reloads the page when it moves. The
# Python half is in the stamp on purpose: the view bundle is built in-process, so an edit there is
# only visible after a restart, and the reload is what puts the restarted server's answer on screen.
# A poll that fails is the server going down for that restart, so it retries rather than reloading
# into a dead port. The FIRST stamp is only recorded, never acted on, or every page load would
# reload itself once.
#
# The answer also says whether THIS process is STALE — its Python is older than the files on disk,
# so a restart is owed. A stale process must not be reloaded into: it is about to be killed, and a
# page that reloads from it loads its assets from a port that dies mid-request, which leaves a blank
# page that nothing will fix. The page therefore waits for a fresh process to answer before acting
# on the change. Measured, not reasoned about: an edit to a Python source did exactly that.
def dev_stamp() -> int:
    """Newest mtime across the served frontend files and this tool's Python — one number per edit."""
    newest = _sources_stamp()
    for name in ("viewer.html", *_STATIC_FILES):
        try:
            newest = max(newest, (_FRONTEND_DIR / name).stat().st_mtime_ns)
        except OSError:
            continue
    return newest


_DEV_RELOAD_SCRIPT = """<script>
(function () {
  var seen = null, EVERY = 1000;
  function again() { setTimeout(poll, EVERY); }
  function poll() {
    fetch('api/dev-reload', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.stamp) return again();
        if (seen === null) seen = d.stamp;          // first answer: remember, never act
        else if (d.stamp !== seen && !d.stale) return location.reload();
        again();                                     // stale: a restart is owed, wait for it
      })
      .catch(again);                                 // mid-restart: keep asking, do not reload
  }
  poll();
})();
</script>"""


def with_dev_reload(html: str) -> str:
    """Put the live-reload script into the shell, immediately before `</body>`. Appended when the
    shell has no `</body>`, so a hand-edited shell still reloads instead of silently not."""
    if "</body>" in html:
        return html.replace("</body>", _DEV_RELOAD_SCRIPT + "</body>", 1)
    return html + _DEV_RELOAD_SCRIPT


def ensure_fresh(proj: Project) -> None:
    """Drop a project's cached artifacts when its map file changed on disk (mtime_ns mismatch), and
    re-read the header fields (commit/title/goal — an Accept bumps the pin, and ``tree`` reads git AT
    that pin). Called on every /coyomap/<slug>/ request, so a map edited while the server runs is picked up
    on the next refresh. Failure modes stay serve-friendly: an unstat-able file keeps the cached copy;
    a map that no longer loads (e.g. caught mid-write) keeps the cached copy AND leaves ``map_mtime``
    stale, so the very next request retries the reload."""
    try:
        mtime = proj.map_json.stat().st_mtime_ns
    except OSError:
        return
    if mtime == proj.map_mtime:
        return
    fresh = load_project(str(proj.repo_root))
    if fresh is None:   # mid-write or newly-invalid map — serve the old bundle, retry next request
        return
    proj.commit, proj.title, proj.goal = fresh.commit, fresh.title, fresh.goal
    proj.map_mtime = fresh.map_mtime
    proj.tree = proj.view = proj.symbols = None
    proj.compare_cache.clear()


def build_projects(folders: list[str]) -> dict[str, Project]:
    """slug -> Project for every recents folder that still holds a loadable map. Slug is the folder
    name; a collision (same folder name from two paths) gets a numeric suffix so both stay reachable.
    Recents order (most-recent first) decides who wins the bare name."""
    out: dict[str, Project] = {}
    for folder in folders:
        proj = load_project(folder)
        if proj is None:
            continue
        base, slug, i = proj.slug, proj.slug, 2
        while slug in out:
            slug, i = f"{base}-{i}", i + 1
        proj.slug = slug
        out[slug] = proj
    return out


# --- git reads (pinned to the map's commit) -----------------------------------------------------

def _git(repo_root: Path, args: list[str]) -> tuple[int, bytes]:
    """Run a read-only git command in ``repo_root``; return (returncode, stdout-bytes). No shell —
    args are passed as a list, so a path from the query string can't inject a command."""
    try:
        p = subprocess.run(["git", "-C", str(repo_root), *args],
                           capture_output=True, timeout=15)
        return p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, b""


def git_ls_files(repo_root: Path, commit: str) -> list[str]:
    """Repo-relative posix paths tracked at ``commit`` (the map's frozen file set)."""
    if not _valid_commit(commit):  # empty or non-SHA -> no git call (see _valid_commit)
        return []
    code, out = _git(repo_root, ["ls-tree", "-r", "--name-only", commit])
    if code != 0:
        return []
    return [ln for ln in out.decode("utf-8", "replace").splitlines() if ln]


def git_blob_size(repo_root: Path, commit: str, path: str) -> int | None:
    """Byte size of the blob at ``commit:path`` — or None if it isn't a *file* there (missing, or a
    directory, which resolves to a git tree). One ``cat-file --batch-check`` gives object type + size,
    so the src route can reject an oversized blob BEFORE ``git_show`` buffers it into memory, and reject
    a directory path (whose ``git show`` would otherwise dump a bare filename listing)."""
    if not _valid_commit(commit) or not safe_rel(path):
        return None
    try:
        p = subprocess.run(["git", "-C", str(repo_root), "cat-file",
                            "--batch-check=%(objecttype) %(objectsize)"],
                           input=f"{commit}:{path}\n".encode(), capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    parts = p.stdout.decode("utf-8", "replace").split()
    if p.returncode != 0 or len(parts) != 2 or parts[0] != "blob":  # 'tree'/'missing'/malformed -> not a file
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def git_show(repo_root: Path, commit: str, path: str) -> bytes | None:
    """Contents of ``path`` at ``commit`` (``git show <commit>:<path>``); None if it doesn't exist."""
    if not _valid_commit(commit) or not safe_rel(path):
        return None
    code, out = _git(repo_root, ["show", f"{commit}:{path}"])
    return out if code == 0 else None


def safe_rel(path: str) -> bool:
    """A repo-relative path with no traversal / absolute escape — the only thing we'll read.

    Public because `export.py` guards the same thing on the WRITE side: a path that may not be read
    out of a commit may not be written into an export folder either, and one rule for both is the
    point."""
    if not path or path.startswith("/") or "\\" in path or "\x00" in path:
        return False
    return ".." not in Path(path).parts


# --- git ref resolution (shared by the impact endpoints) ----------------------------------------
# resolve_ref turns a user-supplied ref into a SHA the pinned-read helpers accept; the WORKTREE
# sentinel passes through (the dirty tree isn't a committed object).

_REF_RE = re.compile(r"[0-9A-Za-z_./~^@{}+-]{1,200}")


def _safe_ref(ref: str) -> bool:
    """A git revision safe to pass to git's argv: non-empty, no leading dash (which git would read as
    a flag — argument injection), and only revision-ish characters. Not a resolution — just the gate
    before `git rev-parse` peels it to a SHA."""
    return bool(ref) and not ref.startswith("-") and bool(_REF_RE.fullmatch(ref))


def resolve_ref(repo_root: Path, ref: str) -> str | None:
    """A user-supplied ref → the SHA it points at, or None if unsafe/unresolvable. The `WORKTREE`
    sentinel passes through verbatim (the dirty tree isn't a committed object). `--end-of-options`
    plus `_safe_ref` keep a hostile ref from becoming a git flag."""
    if ref == IMPACT_WORKTREE:
        return IMPACT_WORKTREE
    if not _safe_ref(ref):
        return None
    code, out = _git(repo_root, ["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"])
    if code != 0:
        return None
    sha = out.decode("utf-8", "replace").strip()
    return sha if _valid_commit(sha) else None


def worktree_read(root: Path, path: str) -> bytes | None:
    """A guarded read of a WORKING-TREE file for `api/src?at=WORKTREE`. `safe_rel` alone is not a
    disk-I/O guard, so: realpath containment inside the repo (a tracked symlink must not escape),
    `.git/` excluded, and only files git accounts for — tracked or untracked-not-ignored — are
    served (a gitignored `.env` never leaks through the viewer)."""
    if not safe_rel(path) or path.split("/", 1)[0] == ".git":
        return None
    try:
        real = (root / path).resolve(strict=True)
        real_root = root.resolve(strict=True)
    except OSError:
        return None
    if not real.is_relative_to(real_root) or ".git" in real.relative_to(real_root).parts:
        return None
    if not real.is_file():
        return None
    code, _out = _git(root, ["ls-files", "--error-unmatch", "--", path])
    if code != 0:  # not tracked — allow only untracked-not-ignored
        code2, out2 = _git(root, ["ls-files", "--others", "--exclude-standard", "--", path])
        if code2 != 0 or path not in out2.decode("utf-8", "replace").splitlines():
            return None
    try:
        return real.read_bytes()
    except OSError:
        return None


# --- compare with an old map (api/mapcommits + api/compare) --------------------------------------
# The served map is the NEW side. The OLD side is a version out of the map file's own git history,
# or a map file on disk named by a `path:` ref. The engine and the payload shape live in
# `mapdiff` / `viewer/compare`; only the git reads and the disk read are here.

_LEGACY_MAP_REL = ".coyodex/project-map.json"   # where the map lived before the 2026-09-13 rename


@dataclass(frozen=True)
class OldMap:
    """The old side of a comparison: the map document, and the labels the picker showed for it."""
    doc: dict[str, Any]
    side: dict[str, Any]


def _map_rel(proj: Project) -> str:
    try:
        return proj.map_json.resolve().relative_to(proj.repo_root.resolve()).as_posix()
    except ValueError:
        return f".coyomap/{MAP_JSON}"


def map_history(proj: Project, limit: int = 60) -> dict[str, Any]:
    """The commits that changed the map file, newest first, following the folder rename, and
    whether the file on disk has edits the last commit does not."""
    rel = _map_rel(proj)
    code, out = _git(proj.repo_root, ["log", f"-n{limit}", "--follow", f"--format={LOG_FORMAT}",
                                      "--name-only", "--", rel])
    versions = parse_history(out.decode("utf-8", "replace")) if code == 0 else []
    dirty_code, _ = _git(proj.repo_root, ["diff", "--quiet", "HEAD", "--", rel])
    return history_payload(versions, dirty=bool(versions) and dirty_code == 1)


def _old_map_at(proj: Project, sha: str) -> OldMap:
    """The map file at `sha`, at whichever path it had then, and the version's labels. A sha the
    history did not list still works when the file exists there under the current or the legacy
    path."""
    full = resolve_ref(proj.repo_root, sha)
    if full is None or full == IMPACT_WORKTREE:
        raise ValueError(f"{sha} is not a commit of this repo")
    versions = map_history(proj)["versions"]
    assert isinstance(versions, list)
    known = next((v for v in versions if isinstance(v, dict) and v.get("sha") == full), None)
    paths = ([str(known["path"])] if known else []) + [_map_rel(proj), _LEGACY_MAP_REL]
    blob = None
    for path in paths:
        blob = git_show(proj.repo_root, full, path)
        if blob is not None:
            break
    if blob is None:
        raise ValueError(f"no map file in commit {sha[:10]}")
    doc = load_map_doc(blob.decode("utf-8", "replace"), f"the map at {sha[:10]}")
    if known:
        label = version_label(MapVersion(str(known["sha"]), str(known["short"]), str(known["date"]),
                                         str(known["subject"]), str(known["path"])))
        old = {"label": label, "sha": known["sha"], "short": known["short"], "date": known["date"],
               "subject": known["subject"], "path": None}
    else:
        old = {"label": f"commit {full[:10]}", "sha": full, "short": full[:7], "date": "",
               "subject": "", "path": None}
    return OldMap(doc, old)


def _old_map_from_path(proj: Project, raw: str) -> OldMap:
    """A map file on disk: an absolute path, `~`, or a path under the repo root."""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = proj.repo_root / path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"cannot read {raw}: {e.strerror or e}") from None
    doc = load_map_doc(text, raw)
    return OldMap(doc, {"label": raw, "sha": None, "short": None, "date": "", "subject": "", "path": raw})


def compare_with(proj: Project, ref: str) -> dict[str, Any]:
    """`api/compare?ref=`: the change document between the old map `ref` names and the served map.
    Commit refs are cached per map version; a path ref is read every time, since the file may move."""
    parsed = parse_ref(ref)
    if parsed is None:
        raise ValueError("ref must be a commit sha or path:<file>")
    kind, value = parsed
    if kind == "commit" and ref in proj.compare_cache:
        return proj.compare_cache[ref]
    old = _old_map_at(proj, value) if kind == "commit" else _old_map_from_path(proj, value)
    new_doc = load_map_doc(proj.map_json.read_text(encoding="utf-8"), "the served map")
    new = {"label": "the current map", "sha": proj.commit or None,
           "short": (proj.commit or "")[:7] or None, "date": "", "subject": "", "path": None}
    payload = compare_payload(new_doc, old.doc, ref, old.side, new)
    if kind == "commit":
        proj.compare_cache[ref] = payload
    return payload


def impact_commits(proj: Project, limit: int = 25) -> dict[str, object]:
    """The impact picker's commit list: the pin's ancestors AND descendants (the map may be older
    than the code being compared), newest-first within each list."""
    pin_sha = resolve_ref(proj.repo_root, proj.commit) if proj.commit else None
    if pin_sha is None:
        return {"pin": None, "ancestors": [], "descendants": []}

    def _log(args: list[str]) -> list[dict[str, str]]:
        code, out = _git(proj.repo_root, ["log", f"-n{limit}", "--format=%h%x09%cs%x09%s", *args])
        rows: list[dict[str, str]] = []
        if code == 0:
            for line in out.decode("utf-8", "replace").splitlines():
                parts = line.split("\t", 2)
                if len(parts) == 3:
                    rows.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
        return rows

    return {"pin": pin_sha,
            "ancestors": _log([pin_sha]),
            "descendants": _log(["--all", "--ancestry-path", f"{pin_sha}.."])}


def impact_file_diff(proj: Project, path: str, base_ref: str, target_ref: str) -> dict[str, object]:
    """One file's inline diff across an ARBITRARY range (the impact explorer's code view) — same
    payload shape as `file_diff`, without the pin-at-one-end constraint. Raises ValueError → 400."""
    if not safe_rel(path):
        raise ValueError("bad path")
    base_sha = impact_resolve_ref(proj.repo_root, base_ref)
    if base_sha == IMPACT_WORKTREE:
        raise ValueError("base must be a commit")
    target_sha = impact_resolve_ref(proj.repo_root, target_ref)
    args = ["diff", "--no-color", f"-U{_DIFF_CONTEXT}", base_sha]
    if target_sha != IMPACT_WORKTREE:
        args.append(target_sha)
    args += ["--", path]
    code, out = _git(proj.repo_root, args)
    if code != 0:
        raise ValueError("git diff failed for that file")
    text = out.decode("utf-8", "replace")
    if "\nBinary files " in ("\n" + text) or text.startswith("Binary files "):
        return {"path": path, "base": base_sha, "target": target_sha, "binary": True, "rows": []}
    rows: list[DiffRow] = parse_unified_diff(text)
    if len(rows) > _DIFF_MAX_ROWS:
        return {"path": path, "base": base_sha, "target": target_sha, "tooLarge": True, "rows": []}
    return {
        "path": path, "base": base_sha, "target": target_sha,
        "rows": [{"op": r.op, "oldLn": r.old_ln, "newLn": r.new_ln, "text": r.text} for r in rows],
    }


def project_impact(proj: Project, query: dict[str, list[str]]) -> dict:
    """The impact-engine payload (design: internal/docs/impact-and-update-design.md): project an
    arbitrary B→T diff (any refs; target may be WORKTREE) onto the map's anchors and ripple once.
    Loads the model fresh (cheap; always current) and the preindex symbol extents when present —
    an extent-less pre-index just resolves every anchor at file rung, honestly."""
    def q(name: str, default: str | None = None) -> str | None:
        vals = query.get(name) or []
        return vals[0] if vals else default

    base = q("base") or proj.commit
    target = q("target") or IMPACT_WORKTREE
    file_scope = q("file")
    try:
        depth = max(1, min(4, int(q("depth") or "2")))
    except ValueError:
        depth = 2
    opts = RippleOptions(
        reads=q("reads") in ("1", "true"),
        entity_graph=q("entity_graph") in ("1", "true"),
        callgraph=q("callgraph") in ("1", "true"),
        callgraph_depth=depth,
    )
    model = load_model(proj.map_json.read_text(encoding="utf-8"))
    extents = load_map_extents(proj.map_json)
    core = compute_impact(proj.repo_root, model, extents, base, target)
    # The SAME table into both halves: the ripple's rule branch uses it exactly as the viewer does,
    # so a rule shown as enforcing a step also ripples to that step's use case.
    return build_impact_result(model, core, opts, file_scope, extents)


def project_tree(proj: Project) -> FileTreeNode:
    """The file-browser tree for a project — git file set at the commit, overlaid with map coverage.

    Reuses the render-path tree builder (build_tree + node_path_index) so the served tree and the
    once-embedded tree are the SAME shape; only the file source differs (git vs a disk walk). Cached
    on the Project after the first build."""
    if proj.tree is not None:
        return proj.tree
    graph = model_to_graph(load_model(proj.map_json.read_text(encoding="utf-8")))
    rels = sorted(git_ls_files(proj.repo_root, proj.commit))
    proj.tree = build_tree(rels, node_path_index(graph), resolved_path_index(graph),
                           root_name=proj.repo_root.name)
    return proj.tree


def project_view(proj: Project) -> ViewBundle:
    """The whole view bundle for a project — the graph plus every pre-rendered diagram, flow, colour,
    and config flag the generic frontend needs (see gen_viewer.build_view_bundle). Computed from the
    committed model, source-links anchored on the map's `.coyomap/` folder. Cached on the Project
    after the first request.
    The frontend fetches this at boot from /coyomap/<slug>/api/view and renders it."""
    if proj.view is not None:
        return proj.view
    # The pre-index symbol table, so a rule enforced inside the function a flow step names shows as
    # "same function as this step" rather than not at all. The markdown view has no such table and
    # degrades to exact-only — the viewer is where the finer answer is available, and using it here
    # keeps the graph a pure function of (model, extents).
    model = load_model(proj.map_json.read_text(encoding="utf-8"))
    extents = load_map_extents(proj.map_json)
    graph = model_to_graph(model, extents)
    # The feature derivation needs the MODEL, not the graph projected from it, and both are already
    # in hand here — passing them keeps `build_view_bundle` from reading and parsing the same map a
    # second time on every cold request.
    proj.view = build_view_bundle(graph, proj.map_json.parent, model=model, extents=extents)
    return proj.view


def project_symbols(proj: Project) -> list[dict[str, object]]:
    """The code symbols (class/function definitions) from the build-time pre-index next to the map, as a
    flat list of ``{name, file, line, kind}`` — one entry per definition site. The pre-index is generated
    at the map's commit, so its file:line anchors match what the code viewer serves from git. Missing or
    unreadable pre-index -> an empty list (the viewer then just has no code-symbol results). Cached on the
    Project after the first request; the frontend fetches it lazily from /coyomap/<slug>/api/symbols."""
    if proj.symbols is not None:
        return proj.symbols
    out: list[dict[str, object]] = []
    path = proj.map_json.parent / PREINDEX_JSON
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None  # no pre-index, or unreadable/invalid JSON -> degrade to no code symbols
    # isinstance guards at every level: a pre-index whose shape doesn't match (a list where a dict is
    # expected, a hand-edited/older/hostile file) must yield [] here, never an AttributeError that would
    # break the response. Only well-shaped {symbols:{by_name:{name:[{file,line,kind}]}}} contributes rows.
    symbols = doc.get("symbols") if isinstance(doc, dict) else None
    by_name = symbols.get("by_name") if isinstance(symbols, dict) else None
    if isinstance(by_name, dict):
        for name, locs in by_name.items():
            if not isinstance(locs, list):
                continue
            for loc in locs:
                if not isinstance(loc, dict) or not loc.get("file"):
                    continue
                out.append({"name": name, "file": loc.get("file"),
                            "line": loc.get("line"), "kind": loc.get("kind")})
    proj.symbols = out
    return out


# --- filesystem browser (for the "add a project" picker) ----------------------------------------

def list_dirs(path: Path) -> dict[str, object]:
    """The subdirectories of `path` (names only), each flagged whether it holds a mappable project,
    plus the parent (for up-navigation) and whether `path` itself is mappable. Used by the picker —
    it lists directories on the LOCAL machine for the LOCAL user, so there is no privilege boundary
    to cross here; a permission error on any entry is skipped."""
    entries: list[dict[str, object]] = []
    try:
        for child in sorted(path.iterdir(), key=lambda x: x.name.lower()):
            try:
                if child.is_dir() and not child.is_symlink():
                    entries.append({"name": child.name, "path": str(child), "hasMap": _has_coyomap(child)})
            except OSError:
                continue
    except (OSError, PermissionError):
        pass
    parent = str(path.parent) if path.parent != path else None
    return {"path": str(path), "parent": parent, "home": str(Path.home()),
            "hasMap": _has_coyomap(path), "entries": entries}


# --- HTTP -----------------------------------------------------------------------------------------

TEXT_MAX = 4_000_000  # refuse to stream an absurdly large blob into the browser code viewer
_DIFF_CONTEXT = 3      # lines of unchanged context around each hunk in the code-view diff
_DIFF_MAX_ROWS = 20_000  # cap the rows in one file's diff response (a pathological diff guard)
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _loopback_host(host: str) -> bool:
    """True if the request's Host names loopback (or is absent). Rejecting any other Host defeats a
    DNS-rebinding attack: a page on evil.com that re-points its name at 127.0.0.1 to read a victim's
    source code would still send ``Host: evil.com``, which is refused. An absent Host (HTTP/1.0, curl)
    is not a browser-driven rebinding vector, so it is allowed."""
    if not host:
        return True
    if host.startswith("["):                       # bracketed IPv6 literal: [::1] or [::1]:port
        host = host[1:host.index("]")] if "]" in host else host[1:]
    else:
        host = host.split(":", 1)[0]               # strip an optional :port
    return host in _LOOPBACK_HOSTS


def _recents_payload(store: RecentsStore, projects: dict[str, Project]) -> list[dict[str, object]]:
    """Every recents folder for the landing page — its served slug (None if the map is gone/broken) and
    commit — so the UI can offer Open / Remove for each. A valid map is directly openable: the viewer is
    served (built on demand), so there is no separate 'render the HTML first' step. `rendered` mirrors
    `ok` for the older landing-page script that still reads it."""
    by_path = {str(p.repo_root): slug for slug, p in projects.items()}
    items: list[dict[str, object]] = []
    for folder in store.list():
        slug = by_path.get(folder)
        proj = projects.get(slug) if slug else None
        items.append({
            "path": folder,
            "name": Path(folder).name,
            "title": proj.title if proj else Path(folder).name,
            "goal": proj.goal if proj else "",
            "slug": slug,
            # The map's own address, composed HERE so the landing page never spells the prefix itself.
            "url": map_url(slug) if slug else "",
            "ok": proj is not None,
            "commit": proj.commit if proj else "",
            "rendered": proj is not None,   # a valid map is openable; the viewer is served, not baked
            # Can this map's CODE be read? A `.coyomap/` copied outside its repo opens fine and then
            # 404s on every file — say so on the card instead of letting the reader find out by clicking.
            "code": repo_state(proj.map_json.parent, proj.commit) if proj else "no-repo",
        })
    return items


class Handler(BaseHTTPRequestHandler):
    store: RecentsStore = RecentsStore.__new__(RecentsStore)  # replaced in serve()
    projects: dict[str, Project] = {}
    dev: bool = False  # --dev only: inject live reload + answer api/dev-reload (see dev_stamp)
    server_version = "coyomap-serve"

    def log_message(self, format: str, *args: object) -> None:  # quieter than the default access log
        return

    # --- routing ---
    def do_GET(self) -> None:
        if not _loopback_host(self.headers.get("Host", "")):  # DNS-rebinding guard
            return self._send(403, "text/plain; charset=utf-8", b"host not allowed")
        parsed = urlparse(self.path)
        parts = [unquote(p) for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if not parts:
            return self._send(200, "text/html; charset=utf-8", INDEX_HTML.encode("utf-8"))
        if parts[0] == "api":            # landing-page API (recents + folder browser)
            return self._root_api(parts[1:], query)
        if parts[0] == "static" and len(parts) == 2:  # shared generic frontend (viewer.js/css)
            return self._static(parts[1])
        if parts[0] == MAP_ROUTE and len(parts) >= 2:  # /coyomap/<slug>/...  -> a project's map + its API
            proj = self.projects.get(parts[1])
            if proj is None:
                return self._send(404, "text/plain; charset=utf-8", b"unknown project")
            if len(parts) == 2 and not parsed.path.endswith("/"):
                # A map's address ENDS IN A SLASH, and the bare form is redirected to it rather than
                # answered. Everything the page then asks for is relative to its own directory — its
                # data (`./api/`), its script and its stylesheet — and without the slash the browser
                # treats the slug as a FILE name and drops it, so every one of those resolves a level
                # too high. The page used to render from the bare form and then fail to load a thing.
                return self._redirect(map_url(proj.slug) + (f"?{parsed.query}" if parsed.query else ""))
            ensure_fresh(proj)  # a map edited while the server runs is picked up on the next request
            warn_if_code_changed()  # …but an edit to THIS tool's Python needs a restart; say so
            return self._project(proj, parts[2:], query)
        return self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self) -> None:
        if not _loopback_host(self.headers.get("Host", "")):
            return self._send(403, "text/plain; charset=utf-8", b"host not allowed")
        # CSRF guard: a custom header a cross-origin page can't set without a (failing) CORS preflight.
        if self.headers.get("X-Coyomap") != "serve":
            return self._send(403, "text/plain; charset=utf-8", b"missing X-Coyomap header")
        parts = [unquote(p) for p in urlparse(self.path).path.split("/") if p]
        if parts[:1] == ["api"] and len(parts) == 2 and parts[1] in ("open", "forget", "reorder"):
            body = self._read_json()
            if parts[1] == "reorder":
                return self._reorder(body)
            path = str(body.get("path") or "") if isinstance(body, dict) else ""
            return self._open(path) if parts[1] == "open" else self._forget(path)
        return self._send(404, "text/plain; charset=utf-8", b"not found")

    # --- landing-page API ---
    def _root_api(self, rest: list[str], query: dict[str, list[str]]) -> None:
        if rest == ["recents"]:
            # Re-read the file (a build may have registered a project since startup) and rebuild the
            # served set, so a just-built project shows up as a card AND is openable, no restart needed.
            # The re-read is also when a remembered folder that no longer exists is dropped: the page
            # never shows a dead card, and the file does not keep growing with them.
            with _STATE_LOCK:
                gone = self.store.prune_missing()   # reloads first
                Handler.projects = build_projects(self.store.list())
            if gone:
                print(f"coyomap serve: forgot {len(gone)} remembered folder(s) that no longer exist",
                      file=sys.stderr)
            return self._json(_recents_payload(self.store, self.projects))
        if rest == ["browse"]:
            raw = (query.get("path") or [""])[0]
            if not raw:
                return self._json(list_dirs(Path.home()))  # no path -> land at Home
            try:
                base = Path(raw).expanduser().resolve()  # accept ~/… and absolute paths
            except OSError:
                base = None
            if base is None or not base.is_dir():
                return self._send(404, "text/plain; charset=utf-8", b"no such folder")  # let the UI flag a typo
            return self._json(list_dirs(base))
        return self._send(404, "text/plain; charset=utf-8", b"unknown api")

    def _open(self, path: str) -> None:
        p = Path(path).expanduser() if path else Path("")  # accept ~/… paths typed in the UI
        if not path or not p.is_absolute():
            return self._send(400, "text/plain; charset=utf-8", b"enter an absolute folder path")
        if not p.is_dir():
            return self._send(400, "text/plain; charset=utf-8", b"no such folder on this machine")
        if not _has_coyomap(p):  # a .coyomap/ dir is enough — the map inside may not be valid/built yet
            hint = old_map_folder_hint(p)
            return self._send(400, "text/plain; charset=utf-8",
                              (hint or "that folder has no .coyomap/ folder").encode("utf-8"))
        with _STATE_LOCK:
            self.store.add(str(p))
            Handler.projects = build_projects(self.store.list())
        return self._json({"ok": True})

    def _forget(self, path: str) -> None:
        if not path:
            return self._send(400, "text/plain; charset=utf-8", b"missing path")
        with _STATE_LOCK:
            self.store.remove(path)
            Handler.projects = build_projects(self.store.list())
        return self._json({"ok": True})

    def _reorder(self, body: object) -> None:
        folders = body.get("folders") if isinstance(body, dict) else None
        if not isinstance(folders, list):
            return self._send(400, "text/plain; charset=utf-8", b"missing folders")
        with _STATE_LOCK:
            self.store.set_order([f for f in folders if isinstance(f, str)])
            Handler.projects = build_projects(self.store.list())
        return self._json({"ok": True})

    # --- a project's map + file/code API ---
    def _project(self, proj: Project, rest: list[str], query: dict[str, list[str]]) -> None:
        if rest and rest[0] == "api":
            return self._project_api(proj, rest[1:], query)
        if len(rest) == 1 and rest[0] in _STATIC_FILES:
            # The shared frontend, under THIS map's path as well as /static/. The shell asks for
            # `viewer.js` / `viewer.css` RELATIVELY, so that one spelling works both here and in an
            # export, where there is no server root to hang a /static/ on.
            return self._static(rest[0])
        if not rest:
            # The generic shell — identical for every project; it fetches this map's data from
            # api/view at boot. Under --dev it carries the live-reload script as well.
            ctype = "text/html; charset=utf-8"
            if not self.dev:
                return self._send_file(_FRONTEND_DIR / "viewer.html", ctype)
            try:
                html = (_FRONTEND_DIR / "viewer.html").read_text(encoding="utf-8")
            except OSError:
                return self._send(404, "text/plain; charset=utf-8", b"file not found")
            return self._send(200, ctype, with_dev_reload(html).encode("utf-8"))
        return self._send(404, "text/plain; charset=utf-8", b"not found")

    def _project_api(self, proj: Project, rest: list[str], query: dict[str, list[str]]) -> None:
        if rest == ["dev-reload"]:
            # Without --dev this is not an endpoint at all — a 404, the same answer any other
            # unknown name gets, so a normal server offers no trace of the dev surface.
            if not self.dev:
                return self._send(404, "text/plain; charset=utf-8", b"unknown api")
            return self._json({"stamp": dev_stamp(), "stale": warn_if_code_changed()})
        if rest == ["health"]:
            return self._json({"ok": True, "project": proj.slug, "commit": proj.commit})
        if rest == ["view"]:
            # Widest of the API catches: build_view_bundle walks the whole model and
            # assembles every diagram, so an odd-but-loadable map can raise KeyError/IndexError/TypeError
            # too. A bad map must yield a clean 500, never kill the worker thread or leak a traceback.
            try:
                return self._json(project_view(proj))
            except (ModelError, OSError, ValueError, KeyError, IndexError, TypeError) as e:
                return self._send(500, "text/plain; charset=utf-8",
                                  f"could not build the view: {e}".encode("utf-8"))
        if rest == ["rawmap"]:
            # The map EXACTLY as `.coyomap/project-map.json` holds it, sent byte-for-byte. The map
            # inspector (viewer.js) reads THIS, never /api/view: the view bundle is a projection of
            # the model, so "what does the map actually say about this box" is a question it cannot
            # answer. Verbatim, not re-serialised, so the slot the inspector names (`use_cases[12]`)
            # is the slot a person opening the file by hand will find.
            try:
                return self._send(200, "application/json; charset=utf-8", proj.map_json.read_bytes())
            except OSError as e:
                return self._send(500, "text/plain; charset=utf-8",
                                  f"could not read the map: {e}".encode("utf-8"))
        if rest == ["tree"]:
            try:
                return self._json(project_tree(proj))
            except (ModelError, OSError, ValueError) as e:
                return self._send(500, "text/plain; charset=utf-8", str(e).encode("utf-8"))
        if rest == ["symbols"]:
            # Never fatal: a missing/broken pre-index yields an empty list, so the search just falls back
            # to map elements + files. No git or model work here, so nothing else to catch.
            return self._json({"symbols": project_symbols(proj), "commit": proj.commit})
        if rest and rest[0] == "src":
            # THE PATH RIDES IN THE URL'S OWN SEGMENTS (`api/src/<path>`), never a query string. A
            # static export answers this exact request with a file on disk, and a file host cannot
            # read a query — so the one spelling has to be the one a folder of files can satisfy.
            # Each segment arrives already percent-decoded (see do_GET); `safe_rel` on the rejoined
            # path is what stops `..`/absolute escapes, decoded ones included.
            path = "/".join(rest[1:])
            # The viewer appends `.txt` so a static host cannot serve a repo's own `.html` as a
            # live page (see `srcPathSegs` in viewer.js). Strip it here so both copies answer the
            # same address; a repo file genuinely called `x.txt` is asked for as `x.txt.txt`.
            if path.endswith(".txt"):
                path = path[:-4]
            if not safe_rel(path):
                return self._send(400, "text/plain; charset=utf-8", b"bad path")
            # `at=` (impact explorer): read the file at another commit, or from the working tree.
            # Default stays the map's pin — the frozen-snapshot behavior is unchanged without it.
            at = (query.get("at") or [proj.commit])[0]
            if at == IMPACT_WORKTREE:
                data = worktree_read(proj.repo_root, path)
                if data is None:
                    return self._send(404, "text/plain; charset=utf-8", b"file not in working tree")
                if len(data) > TEXT_MAX:
                    return self._send(413, "text/plain; charset=utf-8", b"file too large")
                return self._send(200, "text/plain; charset=utf-8", data)
            if not _valid_commit(at):
                return self._send(400, "text/plain; charset=utf-8", b"bad at= commit")
            size = git_blob_size(proj.repo_root, at, path)  # size + is-it-a-file check first
            if size is None:
                return self._send(404, "text/plain; charset=utf-8", b"file not in commit")
            if size > TEXT_MAX:  # reject BEFORE git_show buffers a huge blob into memory
                return self._send(413, "text/plain; charset=utf-8", b"file too large")
            blob = git_show(proj.repo_root, at, path)
            if blob is None:
                return self._send(404, "text/plain; charset=utf-8", b"file not in commit")
            # Served as plain text; the viewer highlights it client-side. charset best-effort utf-8.
            return self._send(200, "text/plain; charset=utf-8", blob)
        if rest == ["impact"]:
            # The impact engine (M2): ?base=&target=&file=&reads=&entity_graph=&callgraph=&depth=.
            # Any base/target pair (the pin need NOT be an endpoint); bad refs/specs are the user's
            # input → 400 (ImpactError is a ValueError); model/git faults → 500.
            try:
                return self._json(project_impact(proj, query))
            except ValueError as e:
                return self._send(400, "text/plain; charset=utf-8", str(e).encode("utf-8"))
            except (ModelError, OSError, KeyError, IndexError, TypeError) as e:
                return self._send(500, "text/plain; charset=utf-8",
                                  f"could not build the impact: {e}".encode("utf-8"))
        if rest == ["impactcommits"]:
            # The impact picker's list: the pin's ancestors AND descendants (M3).
            return self._json(impact_commits(proj))
        if rest == ["mapcommits"]:
            # The compare picker's list: every commit that changed the map file, newest first.
            return self._json(map_history(proj))
        if rest == ["compare"]:
            # The change document between an old map (?ref=<sha> or ?ref=path:<file>) and the served
            # map. A ref the reader typed wrong is their input → 400; a git or disk fault → 500.
            ref = (query.get("ref") or [""])[0]
            try:
                return self._json(compare_with(proj, ref))
            except ValueError as e:
                return self._send(400, "text/plain; charset=utf-8", str(e).encode("utf-8"))
            except (OSError, KeyError, IndexError, TypeError) as e:
                return self._send(500, "text/plain; charset=utf-8",
                                  f"could not compare the maps: {e}".encode("utf-8"))
        if rest == ["impactsrcdiff"]:
            # One file's inline diff across an ARBITRARY range, for the impact code view (M3).
            path = (query.get("path") or [""])[0]
            base = (query.get("base") or [proj.commit])[0]
            target = (query.get("target") or [IMPACT_WORKTREE])[0]
            try:
                return self._json(impact_file_diff(proj, path, base, target))
            except ValueError as e:
                return self._send(400, "text/plain; charset=utf-8", str(e).encode("utf-8"))
            except (OSError, KeyError, IndexError, TypeError) as e:
                return self._send(500, "text/plain; charset=utf-8",
                                  f"could not build the file diff: {e}".encode("utf-8"))
        return self._send(404, "text/plain; charset=utf-8", b"unknown api")

    # --- response helpers ---
    def _read_json(self) -> object:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if n <= 0 or n > 64_000:
            return None
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, OSError):
            return None

    def _json(self, obj: object) -> None:
        self._send(200, "application/json; charset=utf-8", json.dumps(obj).encode("utf-8"))

    def _static(self, name: str) -> None:
        """Serve one shared generic-frontend asset by exact name (whitelist -> no traversal)."""
        ctype = _STATIC_FILES.get(name)
        if ctype is None:
            return self._send(404, "text/plain; charset=utf-8", b"not found")
        return self._send_file(_FRONTEND_DIR / name, ctype)

    def _redirect(self, location: str) -> None:
        """A 301 to `location` — only ever a path this server composed, never user input echoed back."""
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send_file(self, path: Path, ctype: str) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            return self._send(404, "text/plain; charset=utf-8", b"file not found")
        self._send(200, ctype, data)

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)  # only reached from do_GET/do_POST (other verbs get the base 501)


def serve(add_folders: list[Path], port: int = _DEFAULT_PORT, open_browser: bool = False,
          store: RecentsStore | None = None, dev: bool = False,
          running_path: Path = RUNNING_PATH,
          on_start: Callable[[ThreadingHTTPServer], None] | None = None) -> int:
    """Serve the recents (plus any folders passed on the command line, added + validated) until
    interrupted. No disk scan — the served set is exactly the recents list.

    ``dev`` is for someone working ON the viewer: it adds live reload (see dev_stamp). It defaults
    off, so a person reading a map never gets a page that reloads under them.

    ``running_path`` is where this server's port and pid are recorded for the life of the process
    (``running.py``); ``on_start`` is handed the bound server once, before it starts answering —
    a test's way to stop a server it started, since nothing else here can reach it."""
    store = store or RecentsStore()
    for folder in add_folders:
        if _has_coyomap(folder):  # a .coyomap/ dir is enough; an unbuilt map just shows as "No valid map yet"
            store.add(str(folder))
        else:
            hint = old_map_folder_hint(folder)
            print(f"coyomap serve: skipping {folder} — no .coyomap/ folder" + (f" ({hint})" if hint else ""),
                  file=sys.stderr)
    Handler.store = store
    Handler.projects = build_projects(store.list())
    Handler.dev = dev
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    port = httpd.server_address[1]  # the BOUND port: `--port 0` asks the OS, and the record must say what it gave
    note_running(port, os.getpid(), running_path)
    url = f"http://127.0.0.1:{port}/"
    names = ", ".join(sorted(Handler.projects)) or "(none yet — add a folder from the landing page)"
    print(f"coyomap serve: {len(Handler.projects)} project(s): {names}")
    print(f"coyomap serve: listening on {url}  (Ctrl-C to stop)")
    if dev:
        print("coyomap serve: --dev — a map page reloads itself when the viewer's files change. "
              "An edit to this tool's PYTHON still needs the process restarted; the reload then "
              "puts the restarted server's answer on screen.")
    if open_browser:
        webbrowser.open(url)
    if on_start is not None:
        on_start(httpd)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\ncoyomap serve: stopped")
    finally:
        forget_running(os.getpid(), running_path)
        httpd.server_close()
    return 0


_USAGE = """usage: coyomap serve [FOLDER ...] [--port N] [--open] [--dev]

Serve coyomap maps over a local HTTP server so the viewer's file browser + code viewer light up
(files read from git at each map's commit). The server does NOT scan the disk: it serves the folders
you have opened before (remembered in ~/.coyomap/serve-recents.json). Open http://127.0.0.1:PORT/ to
add a project by browsing to its folder, or to open / remove a recent one. While it runs, its port is
recorded in ~/.coyomap/serve-running.json, which is how `coyomap url <ID>` finds it.

  FOLDER      a project folder (with .coyomap/project-map.json) to add + serve now (repeatable)
  --port N    port to listen on (default 8765)
  --open      open the landing page in a browser on start
  --dev       for working ON the viewer: a map page reloads itself when the viewer's files change
  -h/--help   show this help"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "-h" in args or "--help" in args:
        print(_USAGE)
        return 0
    port, open_browser, dev, folders = _DEFAULT_PORT, False, False, []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--port":
            i += 1
            if i >= len(args) or not args[i].isdigit():
                print("coyomap serve: --port needs a number", file=sys.stderr)
                return 2
            port = int(args[i])
        elif a == "--open":
            open_browser = True
        elif a == "--dev":
            dev = True
        elif a.startswith("-"):
            print(f"coyomap serve: unknown option '{a}'\n\n{_USAGE}", file=sys.stderr)
            return 2
        else:
            folders.append(Path(a))
        i += 1
    return serve(folders, port=port, open_browser=open_browser, dev=dev)


# --- landing page (recents cards + a folder browser to add a project) ---------------------------
# Self-contained (no external assets). Recents render as cards (map title + goal) from GET
# /api/recents; a project is added by pasting a path or browsing the filesystem via GET /api/browse
# (breadcrumbs, quick locations, filter, inline add). Add/Remove POST to /api/open|forget with the
# X-Coyomap CSRF header. Themed for light + dark via CSS variables + prefers-color-scheme.
INDEX_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>coyomap maps</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/png" href="/static/favicon.png">
<style>
:root{color-scheme:light dark;
  --bg:#fff;--fg:#111827;--muted:#6b7280;--faint:#9ca3af;--line:#e5e7eb;--line2:#f1f2f4;
  --card:#fff;--cardh:#f9fafb;--accent:#4f46e5;--accent2:#6366f1;--hover:#f5f6ff;
  --badge:#059669;--badgebg:#ecfdf5;--badgeln:#a7f3d0;--warn:#b45309;--danger:#dc2626;--ring:#c7d2fe}
@media (prefers-color-scheme:dark){:root{
  --bg:#0f1117;--fg:#e5e7eb;--muted:#9ca3af;--faint:#6b7280;--line:#242836;--line2:#1b1e28;
  --card:#161a23;--cardh:#1b2030;--accent:#a5b4fc;--accent2:#6366f1;--hover:#1a1f2e;
  --badge:#34d399;--badgebg:#0c2a20;--badgeln:#134e3a;--warn:#fbbf24;--danger:#f87171;--ring:#3730a3}}
*{box-sizing:border-box}
body{font:15px/1.55 -apple-system,system-ui,sans-serif;margin:0;background:var(--bg);color:var(--fg)}
.wrap{max-width:820px;margin:0 auto;padding:36px 20px 60px}
h1{font-size:22px;margin:0 0 2px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px;margin:0 0 20px}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);margin:26px 0 10px;font-weight:600}
button{font:inherit;font-size:13px;padding:7px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer}
button:hover{background:var(--hover)}button:disabled{opacity:.5;cursor:default}
button.primary{background:var(--accent2);border-color:var(--accent2);color:#fff}button.primary:hover{background:#818cf8}
input{font:inherit;font-size:14px;padding:8px 11px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);width:100%}
input:focus{outline:2px solid var(--accent2);outline-offset:-1px;border-color:transparent}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.addbar{display:flex;gap:8px;align-items:center}.addbar input{flex:1}
.err{color:var(--danger);font-size:13px;min-height:1.2em;margin:6px 2px 0}
.browser{border:1px solid var(--line);border-radius:12px;padding:12px;margin-top:6px;background:var(--card)}
.bhead{display:flex;gap:8px;align-items:center;margin-bottom:8px}
.crumbs{display:flex;flex-wrap:wrap;gap:1px;align-items:center;flex:1;min-width:0}
.crumb{padding:3px 7px;border:0;background:none;color:var(--accent);border-radius:6px;font-size:13px}
.crumb:hover{background:var(--hover);text-decoration:underline}.crsep{color:var(--faint);font-size:12px}
.quick{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.chip{font-size:12px;padding:3px 9px;border:1px solid var(--line);border-radius:999px;background:var(--bg);color:var(--muted)}
.chip:hover{background:var(--hover);color:var(--fg)}
.filter{margin-bottom:8px}
.dirs{max-height:300px;overflow:auto;border:1px solid var(--line2);border-radius:8px}
.dir{display:flex;align-items:center;gap:9px;padding:7px 11px;cursor:pointer;border-bottom:1px solid var(--line2)}
.dir:last-child{border-bottom:0}.dir:hover{background:var(--hover)}
.dir.hasmap{background:var(--cardh)}.dir.hasmap:hover{background:var(--hover)}
.dir.ksel{background:var(--hover);box-shadow:inset 2px 0 0 var(--accent2)}
.dir .ic{font-size:14px}.dir .dn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mapbadge{font-size:10px;color:var(--badge);background:var(--badgebg);border:1px solid var(--badgeln);border-radius:5px;padding:1px 6px;font-family:ui-monospace,monospace}
.mini{padding:3px 9px;font-size:12px}
.dir.empty{color:var(--faint);cursor:default}.dir.empty:hover{background:none}
.cards{display:flex;flex-direction:column;gap:10px}
.card{position:relative;border:1px solid var(--line);border-radius:12px;padding:14px 40px 14px 30px;background:var(--card);transition:border-color .12s,box-shadow .12s}
.card:hover{border-color:var(--ring);box-shadow:0 2px 12px rgba(80,70,229,.08)}
.card.clickable{cursor:pointer}
.card.disabled{opacity:.6}.card.disabled:hover{border-color:var(--line);box-shadow:none}.card.disabled .x{opacity:1}
.card.drag{opacity:.4}
.grip{position:absolute;left:8px;top:0;bottom:0;display:flex;align-items:center;color:var(--faint);opacity:0;cursor:grab;font-size:13px;user-select:none}
.card:hover .grip{opacity:.7}.grip:active{cursor:grabbing}
.card .title{font-size:15px;font-weight:650;color:var(--accent)}
.card.clickable:hover .title{text-decoration:underline}.card .title.dead{color:var(--fg)}
.iconbtn{border:0;background:none;color:var(--faint);font-size:14px;padding:2px 7px;line-height:1}.iconbtn:hover{color:var(--fg)}
.card .goal{color:var(--muted);font-size:13px;margin:3px 0 8px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card .cmeta{display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:12px}
.card .cpath{color:var(--faint);font-family:ui-monospace,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%}
.card .csha{color:var(--muted);font-family:ui-monospace,monospace}
.card .warn{color:var(--warn)}.card .copy{padding:2px 8px;font-size:11px}
.card .x{position:absolute;top:10px;right:8px;border:0;background:none;color:var(--faint);font-size:15px;padding:2px 6px;opacity:0;transition:opacity .1s}
.card:hover .x{opacity:1}.card .x:hover{color:var(--danger)}
.empty{color:var(--faint);font-size:14px;padding:6px 2px}
.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#111827;color:#fff;padding:8px 14px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none}
.toast.on{opacity:.95}
</style></head><body>
<div class="wrap">
<h1>coyomap maps</h1>
<p class="sub">Open a project's map, or add one — start typing a folder to browse, or paste a path and press ↵.</p>

<input id="pathbar" class="mono" placeholder="Type or paste a folder — ↵ opens it; type to browse &amp; filter" autocomplete="off" spellcheck="false">
<div id="adderr" class="err"></div>

<div id="browser" class="browser" hidden>
  <div class="bhead">
    <button id="up" title="Parent folder">↑</button>
    <div id="crumbs" class="crumbs"></div>
    <button id="closebrowser" class="iconbtn" title="Close browser">✕</button>
  </div>
  <div id="quick" class="quick"></div>
  <div id="dirs" class="dirs"></div>
</div>

<h2>Recent</h2>
<div id="recents" class="cards"><div class="empty">Loading…</div></div>
</div>
<div id="toast" class="toast"></div>

<script>
const H={'Content-Type':'application/json','X-Coyomap':'serve'};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const $=id=>document.getElementById(id);
async function jget(u){const r=await fetch(u,{cache:'no-store'});if(!r.ok)throw new Error(r.status);return r.json();}
async function jpost(u,body){return fetch(u,{method:'POST',headers:H,body:JSON.stringify(body)});}
// cur = the folder currently DISPLAYED (may be a live preview while typing); curBase = the COMMITTED
// current folder — changed only by an explicit click or Enter, never by typing. Relative paths resolve
// against curBase, and clearing the input snaps the view back to it.
let home=null,recents=[],cur=null,entries=[],curParent=null,typeSeq=0,curBase=null,dirRows=[],selIdx=-1,dragSrc=null,dragging=false;
const shorten=p=>home&&(p===home||p.startsWith(home+'/'))?'~'+p.slice(home.length):p;
function toast(m){const t=$('toast');t.textContent=m;t.classList.add('on');setTimeout(()=>t.classList.remove('on'),1400);}

async function loadRecents(){
  try{recents=await jget('/api/recents');}catch(_){$('recents').innerHTML='<div class="empty">Could not load recents.</div>';return;}
  const box=$('recents');
  if(!recents.length){box.innerHTML='<div class="empty">No projects yet — add one above.</div>';renderQuick();return;}
  box.innerHTML='';
  for(const it of recents){
    const c=document.createElement('div');c.className='card';c.draggable=true;c.dataset.path=it.path;
    const goal=it.goal?'<p class="goal">'+esc(it.goal)+'</p>':'';
    let meta='<span class="cpath" title="'+esc(it.path)+'">'+esc(shorten(it.path))+'</span>';
    if(it.commit)meta+='<span class="csha">'+esc(it.commit.slice(0,10))+'</span>';
    if(!it.ok)meta+='<span class="warn">No valid map yet</span>';
    else if(it.code==='no-repo')meta+='<span class="warn" title="This folder is not inside a git repository, so the viewer cannot read its files">no code beside this map</span>';
    else if(it.code==='no-commit')meta+='<span class="warn" title="The repo beside this map does not have the commit the map is pinned to">pinned commit missing</span>';
    else if(!it.rendered)meta+='<span class="warn">not rendered</span><button class="copy" data-path="'+esc(it.path)+'">Copy render cmd</button>';
    c.innerHTML='<span class="grip" title="Drag to reorder">⠿</span><span class="title'+(it.ok&&it.rendered?'':' dead')+'">'+esc(it.title)+'</span>'+goal
      +'<div class="cmeta">'+meta+'</div><button class="x" title="Remove from list">✕</button>';
    if(!it.ok)c.classList.add('disabled');                                                                 // .coyomap present but no valid map -> dimmed, not clickable
    if(it.ok&&it.rendered){c.classList.add('clickable');c.onclick=()=>{if(dragging){dragging=false;return;}location.href=it.url;};}  // whole card opens the map (unless we just dragged)
    // Drag to reorder. mousedown resets the flag so a plain click still opens; a drag sets it so the
    // click that may follow the drop is swallowed. Order is persisted on drop.
    c.addEventListener('mousedown',()=>{dragging=false;});
    c.addEventListener('dragstart',e=>{dragSrc=c;dragging=true;c.classList.add('drag');e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',it.path);});
    c.addEventListener('dragend',()=>{c.classList.remove('drag');dragSrc=null;persistOrder();});
    c.addEventListener('dragover',e=>{e.preventDefault();if(!dragSrc||dragSrc===c)return;const b=c.getBoundingClientRect();const before=(e.clientY-b.top)<b.height/2;c.parentNode.insertBefore(dragSrc,before?c:c.nextSibling);});
    c.querySelector('.x').onclick=async e=>{e.stopPropagation();await jpost('/api/forget',{path:it.path});loadRecents();};
    const cp=c.querySelector('.copy');
    if(cp)cp.onclick=e=>{e.stopPropagation();const cmd='cd "'+cp.dataset.path+'" && coyomap render .coyomap/project-map.json .coyomap/project-map.md';if(navigator.clipboard)navigator.clipboard.writeText(cmd);toast('Render command copied');};
    box.appendChild(c);
  }
  renderQuick();
}
// Persist the current card order (after a drag) to the server, and keep the local recents[] in sync.
async function persistOrder(){
  const order=[...$('recents').querySelectorAll('.card')].map(c=>c.dataset.path);
  jpost('/api/reorder',{folders:order});
  recents.sort((a,b)=>order.indexOf(a.path)-order.indexOf(b.path));
}

async function addPath(path){
  if(!path)return false;
  const r=await jpost('/api/open',{path});
  if(r.ok){$('adderr').textContent='';await loadRecents();if(!$('browser').hidden)renderList();toast('Added');return true;}
  $('adderr').textContent=await r.text();return false;
}

/* --- integrated path bar + folder browser (one control, not two) --- */
function openBrowser(){const b=$('browser');if(b.hidden){b.hidden=false;if(!cur)browse(home||'');}}
function closeBrowser(){$('browser').hidden=true;}
// A typed path: absolute (/…), home (~/…), or RELATIVE to the committed folder curBase (e.g.
// "mee6/repos" at Home). curBase never moves while typing, so relative resolution stays stable.
function resolvePath(v){if(v[0]==='/')return v;if(v[0]==='~')return (home||'')+v.slice(1);return (curBase||cur||home||'')+'/'+v;}
// The filter fragment = the text after the last "/" (or the whole value if none) — so a bare name
// filters the current folder, and while typing a path only the trailing segment filters.
function filterFrag(){const v=$('pathbar').value;const i=v.lastIndexOf('/');return (i===-1?v:v.slice(i+1)).trim().toLowerCase();}
// Enter COMMITS: resolve the typed path and either add it (a project folder) or move into it.
async function goPath(){
  const v=$('pathbar').value.trim();if(!v)return;
  let d;try{d=await fetchBrowse(resolvePath(v));}catch(_){$('adderr').textContent='No such folder.';return;}
  $('adderr').textContent='';
  if(d.hasMap){if(await addPath(d.path))browse(curBase);}  // a project folder -> add it, snap back to the committed folder
  else{$('pathbar').value='';applyBrowse(d);curBase=cur;}  // a parent folder -> move into it (commit)
}
// Typing only PREVIEWS — it never changes the committed folder (curBase). The text up to the last "/"
// is shown ("/" previews the root dir, "mee6/repos" at Home previews that folder), the part after it
// filters. A bare name (no "/") filters the committed folder. Clearing the input snaps back to curBase.
// Only a click (a folder row / breadcrumb / chip / Up) or Enter commits.
async function onType(){
  openBrowser();
  const v=$('pathbar').value;
  if(!v.includes('/')){                       // empty or a bare name -> show the committed folder, filtered
    if(cur!==curBase){const seq=++typeSeq;try{const d=await fetchBrowse(curBase);if(seq!==typeSeq)return;applyBrowse(d);}catch(_){}}
    renderList();return;
  }
  const target=resolvePath(v.slice(0,v.lastIndexOf('/')+1));   // preview the typed folder (no commit)
  const norm=target.replace(/\/+$/,'')||'/';
  if(norm!==cur){
    const seq=++typeSeq;
    try{const d=await fetchBrowse(target);if(seq!==typeSeq)return;applyBrowse(d);return;}catch(_){/* not a folder yet */}
  }
  renderList();
}
// Keyboard: ↑/↓ move a highlight through the folder list, Enter opens the highlighted folder (or, with
// nothing highlighted, commits the typed path via goPath).
function moveSel(d){
  if(!dirRows.length)return;
  selIdx = selIdx<0 ? (d>0?0:dirRows.length-1) : Math.max(0,Math.min(dirRows.length-1,selIdx+d));
  dirRows.forEach((r,i)=>r.classList.toggle('ksel',i===selIdx));
  dirRows[selIdx].scrollIntoView({block:'nearest'});
}
$('pathbar').addEventListener('focus',openBrowser);
$('pathbar').addEventListener('input',onType);
$('pathbar').addEventListener('keydown',e=>{
  if(e.key==='ArrowDown'){e.preventDefault();moveSel(1);}
  else if(e.key==='ArrowUp'){e.preventDefault();moveSel(-1);}
  else if(e.key==='Enter'){if(selIdx>=0&&dirRows[selIdx])dirRows[selIdx].click();else goPath();}
});
$('up').onclick=()=>{if(curParent)browse(curParent);};
$('closebrowser').onclick=closeBrowser;
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('browser').hidden)closeBrowser();});
// Click anywhere outside the browser (and not on the path bar that opens it) closes it — like Esc.
document.addEventListener('mousedown',e=>{const b=$('browser');if(b.hidden)return;if(!b.contains(e.target)&&e.target!==$('pathbar'))closeBrowser();});

async function fetchBrowse(path){return jget('/api/browse'+(path?'?path='+encodeURIComponent(path):''));}
function applyBrowse(d){
  home=d.home;cur=d.path;curParent=d.parent;entries=d.entries;
  $('up').disabled=!d.parent;
  renderCrumbs();renderList();
}
// A COMMITTED navigation (click / Up / crumb / chip): clear the typed text, show the folder, and make
// it the new committed base.
async function browse(path){$('pathbar').value='';let d;try{d=await fetchBrowse(path);}catch(_){return;}applyBrowse(d);curBase=cur;}
function renderCrumbs(){
  const box=$('crumbs');box.innerHTML='';
  const seg=(label,t)=>{const b=document.createElement('button');b.className='crumb';b.textContent=label;b.onclick=()=>browse(t);return b;};
  const sep=()=>{const s=document.createElement('span');s.className='crsep';s.textContent='/';return s;};
  let base,rest;
  if(home&&(cur===home||cur.startsWith(home+'/'))){base=home;rest=cur.slice(home.length);box.appendChild(seg('Home',home));}
  else{base='';rest=cur;box.appendChild(seg('/','/'));}
  let acc=base;
  // The root "/" crumb already shows the leading slash, so skip the separator before the first segment
  // under it (otherwise "/ / Users"). Under Home, every segment gets its separator.
  rest.split('/').filter(Boolean).forEach((p,i)=>{acc+='/'+p;if(!(base===''&&i===0))box.appendChild(sep());box.appendChild(seg(p,acc));});
}
function renderQuick(){
  const box=$('quick');box.innerHTML='';const seen=new Set();const chips=[];
  if(home){chips.push(['Home',home]);seen.add(home);}
  for(const it of recents){const par=it.path.slice(0,it.path.lastIndexOf('/'))||'/';if(!seen.has(par)){seen.add(par);chips.push([shorten(par),par]);}}
  if(chips.length<=1){box.style.display='none';return;}box.style.display='';
  for(const[label,path]of chips){const b=document.createElement('button');b.className='chip';b.textContent=label;b.title=path;b.onclick=()=>browse(path);box.appendChild(b);}
}
function renderList(){
  const q=filterFrag();const box=$('dirs');box.innerHTML='';selIdx=-1;dirRows=[];
  const added=new Set(recents.map(r=>r.path));  // map folders already in the recents list
  const ordered=[...entries.filter(e=>e.hasMap),...entries.filter(e=>!e.hasMap)].filter(e=>e.name.toLowerCase().includes(q));
  if(!ordered.length){box.innerHTML='<div class="dir empty">'+(entries.length?'No matching folders.':'(no subfolders)')+'</div>';return;}
  for(const e of ordered){
    const row=document.createElement('div');row.className='dir'+(e.hasMap?' hasmap':'');
    let tail='';
    if(e.hasMap)tail='<span class="mapbadge">map</span>'
      +(added.has(e.path)?'<button class="mini add" disabled>Added</button>':'<button class="mini primary add">+ Add</button>');
    row.innerHTML='<span class="ic">'+(e.hasMap?'🗺️':'📁')+'</span><span class="dn">'+esc(e.name)+'</span>'+tail;
    row.onclick=()=>browse(e.path);  // a click commits into the folder (browse clears the filter)
    const a=row.querySelector('.add');if(a&&!a.disabled)a.onclick=ev=>{ev.stopPropagation();addPath(e.path);};
    box.appendChild(row);
  }
  dirRows=[...box.querySelectorAll('.dir:not(.empty)')];  // for ↑/↓ keyboard selection
}
(async()=>{try{const d=await jget('/api/browse');home=d.home;}catch(_){}loadRecents();})();
</script>
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
