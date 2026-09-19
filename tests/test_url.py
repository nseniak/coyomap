#!/usr/bin/env python3
"""`coyomap url`: the address of one element, and the record of the running server it reads.

The grammar half is asserted here as TEXT (which words a fragment carries) and in
`tests/test_viewer_browser.py` as a SCREEN (which element ends up selected). Both, because the text
test is fast and names the exact word that moved, and the screen test is the only one that can see
the viewer disagree with it. Conventions: top-level functions, `make_*` helpers, no fixtures.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl

from coyomap import grammar
from coyomap.model import ProjectModel, load_model
from coyomap.viewer import url as url_cmd
from coyomap.viewer.recents import RecentsStore
from coyomap.viewer.running import forget_running, note_running, running_servers
from coyomap.viewer.serve import Handler, build_projects
from coyomap.viewer.url import HOME_VIEWS, link_for

REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_MAP = REPO_ROOT / "tests" / "fixtures" / "mcpolis-project-map.json"
VIEWER_JS = REPO_ROOT / "tools" / "coyomap" / "viewer" / "viewer.js"


def make_every_kind_map() -> dict:
    """The committed fixture, plus the kinds it lacks: an interface, a sub-flow, a decision area
    with a rule, and an entry point with an id."""
    m = json.loads(_FIXTURE_MAP.read_text(encoding="utf-8"))
    m["entry_points"][0]["id"] = "EP1"
    m["interfaces"] = [{"id": "I1", "name": "The dashboard", "what": "Screens a person signs in to.",
                        "side": "ours", "facing": "user", "kind": "screen", "ways_in": ["EP1"]}]
    m["subflows"] = [{"id": "SF1", "name": "Sign in with Google", "steps": [
        {"n": 1, "src": "C15", "dst": "C15", "phrase": "redirect the browser to Google", "note": "",
         "where": None, "no_call_site": False, "subflow": None}]}]
    m["blocks"] = [{"id": "BLK1", "name": "Who may call which tool",
                    "purpose": "How a team's permission sets decide whether one tool call goes out.",
                    "parent": None, "happy_path": "", "stakes": [], "story": None, "owners": None,
                    "source": None, "confidence": "verified", "tech": "", "tech_source": ""}]
    m["rules"] = [{"id": "BR1", "name": "No role, no access",
                   "statement": "A caller whose role cannot be found is refused every tool.",
                   "block": "BLK1", "access": True, "risk": "", "confidence": "verified",
                   "sites": []}]
    return m


def make_model() -> ProjectModel:
    return load_model(json.dumps(make_every_kind_map()))


def make_project(td: Path, name: str = "alpha") -> Path:
    """`td/name` holding the every-kind map, the way a mapped repo holds one."""
    folder = td / name
    (folder / ".coyomap").mkdir(parents=True)
    (folder / ".coyomap" / "project-map.json").write_text(json.dumps(make_every_kind_map()),
                                                          encoding="utf-8")
    return folder


def make_served(td: Path, folders: list[Path]) -> tuple[ThreadingHTTPServer, int]:
    """The real request handler on an ephemeral port, serving `folders` from a recents file of
    its own — never the user's."""
    store = RecentsStore(td / "recents.json")
    for f in folders:
        store.add(str(f))
    Handler.store = store
    Handler.projects = build_projects(store.list())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def run_url(argv: list[str], running_path: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = url_cmd.main(argv, running_path=running_path)
    return code, out.getvalue(), err.getvalue()


def make_dead_pid() -> int:
    """A process id nothing owns any more: a child that has already exited."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


# ── the grammar, as text ─────────────────────────────────────────────────────────────────────


def test_every_kind_has_its_own_page_and_the_words_are_the_viewers() -> None:
    """DRILL IN. One row per element kind the map holds; the words after `v=` are the viewer's own
    state kinds, not the element kinds (a use case's page is `usecase`, an actor's is by name)."""
    m = make_model()
    ep_kind = grammar.canonical_entry_kind(m.entry_points[0].kind)
    expect = {
        "CAP1": ("capability", "v=capability&cap=CAP1"),
        "UC1": ("use_case", "v=usecase&uc=UC1"),
        "R1": ("role", "v=actor&act=Org+creator"),
        "S1": ("subsystem", "v=subsystem&sid=S1"),
        "C1": ("component", "v=element&id=C1"),
        "D1": ("dep", "v=element&id=D1"),
        "SD1": ("subdomain", "v=domsub&sd=SD1"),
        "E1": ("entity", "v=element&id=E1"),
        "I1": ("interface", "v=interfaces&iface=I1"),
        "SF1": ("sub_flow", "v=subflow&sf=SF1"),
        "BLK1": ("block", "v=rules&blk=BLK1"),
        "BR1": ("business_rule", "v=rule&br=BR1"),
        "HP1": ("happy_path_step", "v=hp&sel=hpstep%3AHP1"),
        "EP1": ("entry_point", "v=sysSection&sys=sys-entry-points&epk="
                + ep_kind.replace(" ", "+") + "&sel=ep%3AEP1"),
    }
    for eid, (kind, fragment) in expect.items():
        link = link_for(m, eid)
        assert link is not None, eid
        assert (link.kind, link.fragment) == (kind, fragment), eid
        assert link.view == dict(parse_qsl(fragment))["v"]
    assert link_for(m, "UC999") is None
    assert link_for(m, "EP999") is None


def test_in_context_is_the_home_view_with_the_element_selected() -> None:
    """SHOW IN CONTEXT. A feature or an actor is a pinned card on Features, a surface a pinned box on
    Interfaces, a drawn box is `node:` inside the card that draws it — its parent's, or the overview
    when it has none — and a dependency goes where the Context diagram put it: on the diagram, or
    folded into Libraries. A kind whose context IS its page gets its page."""
    m = make_model()
    expect = {
        "CAP1": "v=features&sel=sfeat%3ACAP1",
        "R1": "v=features&sel=sactor%3AR1",
        "I1": "v=interfaces&sel=siface%3AI1",
        "C1": "v=subsystem&sid=S1&sel=node%3AC1",
        "S1": "v=container&sel=node%3AS1",
        "S13": "v=subsystem&sid=S5&sel=node%3AS13",
        "SD1": "v=domain&sel=node%3ASD1",
        "E1": "v=domsub&sd=SD1&sel=node%3AE1",
        "D1": "v=context&sel=node%3AD1",    # MongoDB: an external system, drawn on the Context diagram
        "D14": "v=libs&sel=node%3AD14",     # a library: folded into the Libraries box, drawn in its drill
        "UC1": "v=usecase&uc=UC1",
        "SF1": "v=subflow&sf=SF1",
        "BLK1": "v=rules&blk=BLK1",
        "BR1": "v=rule&br=BR1",
        "HP1": "v=hp&sel=hpstep%3AHP1",
    }
    for eid, fragment in expect.items():
        link = link_for(m, eid, context=True)
        assert link is not None and link.fragment == fragment, (eid, link)


def test_an_actor_with_no_cast_card_is_shown_on_its_own_page() -> None:
    """A map with no features draws no story diagram, so there is no card to pin: the actor's page is
    the one place that shows it, and context and drill meet there — as `selectTargetFor` says."""
    d = make_every_kind_map()
    d["capabilities"] = []
    for u in d["use_cases"]:
        u["capability"] = None
    m = load_model(json.dumps(d))
    link = link_for(m, "R1", context=True)
    assert link is not None and link.fragment == "v=actor&act=Org+creator"


def test_every_word_the_command_writes_is_one_the_viewer_reads() -> None:
    """The text-level tripwire between url.py and viewer.js: every state field is in STATE_FIELDS,
    every `sel` prefix is one the viewer pins, picks or selects, and every `v=` word is a state kind
    the viewer renders (or the one link word URL_WORD maps). The browser test is the real guard; this
    one is fast and names the exact word."""
    js = VIEWER_JS.read_text(encoding="utf-8")

    def words(after: str) -> set[str]:
        start = js.index(after)
        return set(re.findall(r"'([\w:]+)'", js[start: js.index("];", start)]))

    state_fields = words("const STATE_FIELDS = [")
    sel_prefixes = {w.rstrip(":") for w in words("const STORY_PIN_KEYS = [") | words("const PICK_KEYS = [")}
    sel_prefixes.add("node")  # a drawn box's selector key (`'node:' + id`, bindNodes)
    link_words = set(re.findall(r"'(\w+)'", js[js.index("const URL_WORD = {"): js.index("};", js.index("const URL_WORD = {"))]))
    m = make_model()
    ids = ["CAP1", "UC1", "R1", "S1", "S13", "C1", "D1", "D14", "SD1", "E1", "I1", "SF1", "BLK1",
           "BR1", "HP1", "EP1"]
    for eid in ids:
        for context in (False, True):
            link = link_for(m, eid, context)
            assert link is not None, eid
            for key, value in parse_qsl(link.fragment):
                if key == "v":
                    assert value in link_words or f"kind === '{value}'" in js \
                        or f"kind: '{value}'" in js, f"{eid}: v={value} is no screen the viewer draws"
                elif key == "sel":
                    assert value.split(":", 1)[0] in sel_prefixes, f"{eid}: sel={value}"
                else:
                    assert key in state_fields, f"{eid}: {key}= is not a state field"


# ── the running-server record ───────────────────────────────────────────────────────────────


def test_the_running_record_comes_and_goes_and_skips_the_dead() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "running.json"
        assert running_servers(p) == []                     # no file: no servers, no error
        note_running(8001, os.getpid(), p)
        note_running(8002, make_dead_pid(), p)              # recorded, but its process is gone
        assert [(r.port, r.pid) for r in running_servers(p)] == [(8001, os.getpid())]
        note_running(8003, os.getpid(), p)                  # the same process again: one row, the new port
        assert [r.port for r in running_servers(p)] == [8003]
        forget_running(os.getpid(), p)
        assert running_servers(p) == []
        assert json.loads(p.read_text())["servers"] == []   # the dead row went with it


# ── the command ─────────────────────────────────────────────────────────────────────────────


def test_with_a_running_server_the_address_is_whole_and_the_path_is_the_servers() -> None:
    """The port comes from the record, the path from the server's own recents payload (the one
    place the prefix is composed), the fragment from the grammar. One line on stdout, nothing on
    stderr but the map it read."""
    with tempfile.TemporaryDirectory() as td:
        folder = make_project(Path(td))
        httpd, port = make_served(Path(td), [folder])
        try:
            running = Path(td) / "running.json"
            note_running(port, os.getpid(), running)
            code, out, err = run_url(["UC1", "--repo", str(folder)], running)
            assert code == 0, err
            assert out.strip() == f"http://127.0.0.1:{port}/coyomap/alpha/#v=usecase&uc=UC1"
            assert "note:" not in err
            code, out, err = run_url(["CAP1", "--repo", str(folder), "--context", "--json"], running)
            assert code == 0, err
            got = json.loads(out)
            assert got == {"id": "CAP1", "kind": "capability", "name": "Organizations & teams",
                           "view": "features", "fragment": "v=features&sel=sfeat%3ACAP1",
                           "path": "/coyomap/alpha/",
                           "url": f"http://127.0.0.1:{port}/coyomap/alpha/#v=features&sel=sfeat%3ACAP1",
                           "server": {"port": port, "pid": os.getpid()},
                           "state": "served", "note": ""}
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_without_a_server_the_path_and_fragment_still_come_with_a_note() -> None:
    with tempfile.TemporaryDirectory() as td:
        folder = make_project(Path(td))
        running = Path(td) / "running.json"  # never written: no server ever ran
        code, out, err = run_url(["HP1", "--repo", str(folder)], running)
        assert code == 0
        assert out.strip() == "/coyomap/alpha/#v=hp&sel=hpstep%3AHP1"
        assert "no coyomap server is running" in err and "make start" in err
        code, out, _err = run_url(["HP1", "--repo", str(folder), "--json"], running)
        got = json.loads(out)
        assert got["url"] is None and got["server"] is None and got["path"] == "/coyomap/alpha/"


def test_a_server_that_does_not_list_the_project_is_named_in_the_note() -> None:
    """A recorded, answering server that serves OTHER folders is not silently taken for this one:
    the path falls back to the folder's name and the note says which port to add it on."""
    with tempfile.TemporaryDirectory() as td:
        mine = make_project(Path(td), "mine")
        other = make_project(Path(td), "other")
        httpd, port = make_served(Path(td), [other])
        try:
            running = Path(td) / "running.json"
            note_running(port, os.getpid(), running)
            code, out, err = run_url(["UC1", "--repo", str(mine)], running)
            assert code == 0
            assert out.strip() == "/coyomap/mine/#v=usecase&uc=UC1"
            assert f"port {port}" in err and str(mine) in err
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_a_dead_record_is_skipped_not_dialled() -> None:
    with tempfile.TemporaryDirectory() as td:
        folder = make_project(Path(td))
        running = Path(td) / "running.json"
        note_running(1, make_dead_pid(), running)          # port 1: nothing would answer anyway
        code, out, err = run_url(["UC1", "--repo", str(folder)], running)
        assert code == 0 and out.strip() == "/coyomap/alpha/#v=usecase&uc=UC1"
        assert "no coyomap server is running" in err


def test_bad_input_fails_loudly_and_never_with_exit_0() -> None:
    with tempfile.TemporaryDirectory() as td:
        folder = make_project(Path(td))
        running = Path(td) / "running.json"
        code, _out, err = run_url(["UC999", "--repo", str(folder)], running)
        assert code == 1 and "not defined in the map" in err
        code, _out, err = run_url(["hello", "--repo", str(folder)], running)
        assert code == 2 and "not an element id" in err
        code, _out, err = run_url(["UC1", "--repo", str(folder), "--nope"], running)
        assert code == 2 and "unknown option" in err
        code, _out, err = run_url(["UC1", "UC2", "--repo", str(folder)], running)
        assert code == 2 and "exactly ONE" in err
        code, _out, err = run_url(["UC1", "--repo", str(Path(td) / "nowhere")], running)
        assert code == 1 and "not found" in err
        code, out, _err = run_url(["--help"], running)
        assert code == 0 and "usage: coyomap url" in out


# ── --home: the map's own address ────────────────────────────────────────────────────────────


def test_home_is_the_map_address_with_no_element_and_no_fragment() -> None:
    """What a finished build hands the reader: the front door, on the server that is actually up —
    never a port spelled from memory."""
    with tempfile.TemporaryDirectory() as td:
        folder = make_project(Path(td))
        httpd, port = make_served(Path(td), [folder])
        try:
            running = Path(td) / "running.json"
            note_running(port, os.getpid(), running)
            code, out, err = run_url(["--home", "--repo", str(folder)], running)
            assert code == 0, err
            assert out.strip() == f"http://127.0.0.1:{port}/coyomap/alpha/"
            assert "#" not in out and "note:" not in err
            code, out, err = run_url(["--home", "--repo", str(folder), "--json"], running)
            assert code == 0, err
            got = json.loads(out)
            assert got == {"id": None, "kind": None, "name": None, "view": None, "fragment": None,
                           "path": "/coyomap/alpha/",
                           "url": f"http://127.0.0.1:{port}/coyomap/alpha/",
                           "server": {"port": port, "pid": os.getpid()},
                           "state": "served", "note": ""}
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_home_says_which_of_the_two_silences_it_met() -> None:
    """`state` is the word the closing message branches on, and the two answers are not the same
    remedy: with NO server you start one, with a server that does not list the map you add the
    folder to the one already up."""
    with tempfile.TemporaryDirectory() as td:
        mine = make_project(Path(td), "mine")
        other = make_project(Path(td), "other")
        running = Path(td) / "running.json"  # never written: no server ever ran
        code, out, err = run_url(["--home", "--repo", str(mine), "--json"], running)
        assert code == 0
        got = json.loads(out)
        assert got["state"] == "no-server" and got["url"] is None and got["server"] is None
        assert got["path"] == "/coyomap/mine/" and "no coyomap server is running" in got["note"]
        assert "no coyomap server is running" in err

        httpd, port = make_served(Path(td), [other])
        try:
            note_running(port, os.getpid(), running)
            code, out, err = run_url(["--home", "--repo", str(mine), "--json"], running)
            assert code == 0
            got = json.loads(out)
            assert got["state"] == "not-listed" and got["url"] is None
            assert f"port {port}" in got["note"] and str(mine) in got["note"]
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_home_answers_for_a_map_it_cannot_parse() -> None:
    """The address does not depend on the contents, and a build asking where its map is served must
    not be blocked by what the gates are there to judge."""
    with tempfile.TemporaryDirectory() as td:
        folder = make_project(Path(td))
        (folder / ".coyomap" / "project-map.json").write_text("{ not json", encoding="utf-8")
        running = Path(td) / "running.json"
        code, out, _err = run_url(["--home", "--repo", str(folder)], running)
        assert code == 0 and out.strip() == "/coyomap/alpha/"
        code, _out, err = run_url(["UC1", "--repo", str(folder)], running)  # the element half still reads it
        assert code == 1 and "ERROR" in err


def test_home_refuses_the_flags_that_only_make_sense_for_an_element() -> None:
    with tempfile.TemporaryDirectory() as td:
        folder = make_project(Path(td))
        running = Path(td) / "running.json"
        code, _out, err = run_url(["--home", "UC1", "--repo", str(folder)], running)
        assert code == 2 and "takes no element id" in err
        code, _out, err = run_url(["--home", "--context", "--repo", str(folder)], running)
        assert code == 2 and "cannot be combined with --home" in err
        code, _out, err = run_url(["--repo", str(folder)], running)
        assert code == 2 and "--home" in err  # the missing-id error teaches the flag
        code, _out, err = run_url(["--home", "--repo", str(Path(td) / "nowhere")], running)
        assert code == 1 and "not found" in err


def test_a_named_screen_is_the_whole_map_address_plus_that_screen() -> None:
    """What an update hands the reader: the Update log, no element selected. `--view` is the
    no-element mode by itself, so it needs no `--home` beside it."""
    with tempfile.TemporaryDirectory() as td:
        folder = make_project(Path(td))
        httpd, port = make_served(Path(td), [folder])
        try:
            running = Path(td) / "running.json"
            note_running(port, os.getpid(), running)
            code, out, err = run_url(["--view", "updates", "--repo", str(folder)], running)
            assert code == 0, err
            assert out.strip() == f"http://127.0.0.1:{port}/coyomap/alpha/#v=updates"
            code, out, err = run_url(["--view", "updates", "--repo", str(folder), "--json"], running)
            got = json.loads(out)
            assert got["view"] == "updates" and got["fragment"] == "v=updates"
            assert got["id"] is None and got["name"] is None and got["state"] == "served"
            assert got["url"] == f"http://127.0.0.1:{port}/coyomap/alpha/#v=updates"
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_every_home_view_is_a_screen_the_viewer_draws() -> None:
    """The tripwire for the closed list: a word here that the viewer does not render would send the
    reader to the default screen with nothing to tell them so."""
    js = VIEWER_JS.read_text(encoding="utf-8")
    for word in HOME_VIEWS:
        assert f"kind === '{word}'" in js or f"kind: '{word}'" in js, \
            f"--view {word} is no screen the viewer draws"
        assert f"const URL_WORD = {{ usecases: 'features' }}" in js  # the only kind→word rename
        assert f"'{word}':" not in js.split("const URL_WORD = {", 1)[1].split("}", 1)[0], \
            f"{word} is renamed on its way into the URL"


def test_a_screen_the_command_cannot_address_is_refused_by_name() -> None:
    with tempfile.TemporaryDirectory() as td:
        folder = make_project(Path(td))
        running = Path(td) / "running.json"
        code, _out, err = run_url(["--view", "nonsense", "--repo", str(folder)], running)
        assert code == 2 and "no screen this command can address" in err and "updates" in err
        code, _out, err = run_url(["--view", "updates", "UC1", "--repo", str(folder)], running)
        assert code == 2 and "takes no element id" in err
        code, _out, err = run_url(["--view", "--repo", str(folder)], running)
        assert code == 2 and "--view needs a screen" in err
