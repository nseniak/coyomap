#!/usr/bin/env python3
"""`coyomap url <ID>` — the address that opens the served map on ONE element, already selected.

WHY A COMMAND. A chat working in a mapped project can find an element by grepping the map, but the
address of a screen is written by the viewer alone (`urlFromState` / `stateFromUrl` in viewer.js):
the word after `v=` is not always the element's kind (a use case's page is `v=usecase`, the Features
tab is `v=features`), and a pinned card, a picked step and a drawn box each ride the `sel` field
under a prefix of their own. And the running server's port is recorded nowhere a reader would look.
This command answers all three: which screen, which selection, which server.

TWO GESTURES, the viewer's own. DRILL IN opens the element's own page (`drillInto` in viewer.js);
SHOW IN CONTEXT opens its home view with it selected (`selectTargetFor`). The default is the page;
`--context` is the other. `_page_state` and `_context_state` below mirror those two functions kind
by kind. THE GUARD AGAINST DRIFT is tests/test_viewer_browser.py: it opens every row of both tables
in a real browser and checks the element named is the one on screen. A change to either side is made
in both, and that test is what says so.

The path half (`/coyomap/<slug>/`) is never composed here: a running server is asked for it through
its own recents payload, and without one `serve.map_url` — the same one definition — spells it.
Read-only: the command registers nothing and writes nothing.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from coyomap import grammar
from coyomap.dump import resolve_id
from coyomap.model import (
    COYOMAP_HOME, ID_SHAPE, BusinessRule, Component, Dep, Entity, EntryPoint, Group, HappyStep,
    Interface, ModelError, ProjectModel, Role, SubFlow, UseCase, all_elements, load_model_path,
    resolve_map_path,
)
from coyomap.viewer.running import RUNNING_PATH, RunningServer, running_servers
from coyomap.viewer.serve import map_url

#: Every record the map defines an id for — what `link_for` is handed, one of these per kind.
Element = (Group | UseCase | Role | Component | Dep | Entity | Interface | SubFlow | BusinessRule
           | HappyStep | EntryPoint)

#: The System tab's section that holds the entry-point table (viewer.js `systemSections` derives it
#: from the section's title, 'Entry points').
SYS_ENTRY_POINTS = "sys-entry-points"

#: The screens `--home --view <word>` may name: a whole-map address with no element selected. CLOSED
#: on purpose — a word the viewer does not render costs nothing to type and lands the reader on the
#: default screen with no sign anything went wrong, which is worse than an error. Add a word when a
#: caller needs it; `test_every_home_view_is_a_screen_the_viewer_draws` is what keeps the list honest.
HOME_VIEWS = ("updates",)


@dataclass(frozen=True)
class MapLink:
    id: str
    kind: str        # the word `coyomap dump --id` uses: use_case, capability, role, entry_point…
    name: str
    view: str        # the word after `v=`
    fragment: str    # everything after `#`, e.g. `v=usecase&uc=UC12`


def _page_state(m: ProjectModel, el: Element, kind: str) -> list[tuple[str, str]]:
    """DRILL IN — the element's own page. Mirrors `drillInto` (and, for the kinds that page draws no
    box for, the state their card's click reaches)."""
    eid = str(el.id)
    if kind == "capability":
        return [("v", "capability"), ("cap", eid)]
    if kind == "use_case":
        return [("v", "usecase"), ("uc", eid)]
    if kind == "role" and isinstance(el, Role):  # an actor's page is addressed by NAME, not id
        return [("v", "actor"), ("act", el.name)]
    if kind == "subsystem":
        return [("v", "subsystem"), ("sid", eid)]
    if kind == "subdomain":
        return [("v", "domsub"), ("sd", eid)]
    if kind == "interface":
        return [("v", "interfaces"), ("iface", eid)]
    if kind == "sub_flow":
        return [("v", "subflow"), ("sf", eid)]
    if kind == "block":
        return [("v", "rules"), ("blk", eid)]
    if kind == "business_rule":
        return [("v", "rule"), ("br", eid)]
    if kind == "happy_path_step":  # the walk has no page per step: the step is PICKED on the board
        return [("v", "hp"), ("sel", "hpstep:" + eid)]
    if kind == "entry_point" and isinstance(el, EntryPoint):  # …a picked ROW in its kind's table
        return [("v", "sysSection"), ("sys", SYS_ENTRY_POINTS),
                ("epk", grammar.canonical_entry_kind(el.kind)), ("sel", "ep:" + eid)]
    return [("v", "element"), ("id", eid)]  # component, entity, dependency: the details page


def _context_state(m: ProjectModel, el: Element, kind: str) -> list[tuple[str, str]]:
    """SHOW IN CONTEXT — the element's home view, focused on it. Mirrors `selectTargetFor`. A kind
    whose context IS its page (a use case, a rule, a step) falls through to `_page_state`."""
    eid = str(el.id)
    node = ("sel", "node:" + eid)
    if kind == "capability":
        return [("v", "features"), ("sel", "sfeat:" + eid)]
    if kind == "role":
        # A cast card to pin exists only when the map records features (the story diagram draws
        # then); otherwise the actor's own page is the one place that shows it.
        if m.capabilities:
            return [("v", "features"), ("sel", "sactor:" + eid)]
        return _page_state(m, el, kind)
    if kind == "interface":
        return [("v", "interfaces"), ("sel", "siface:" + eid)]
    if kind == "component" and isinstance(el, Component):
        if el.subsystem and any(s.id == el.subsystem for s in m.subsystems):
            return [("v", "subsystem"), ("sid", el.subsystem), node]
        return _page_state(m, el, kind)  # ungrouped: the viewer injects a default card this cannot name
    if kind == "subsystem" and isinstance(el, Group):
        return [("v", "subsystem"), ("sid", el.parent), node] if el.parent else [("v", "container"), node]
    if kind == "subdomain" and isinstance(el, Group):
        return [("v", "domsub"), ("sd", el.parent), node] if el.parent else [("v", "domain"), node]
    if kind == "entity" and isinstance(el, Entity):
        return [("v", "domsub"), ("sd", el.subdomain), node] if el.subdomain else [("v", "domain"), node]
    if kind == "dep":
        # A dependency's box is on the Context diagram, or folded: into the Libraries box, or into a
        # bucket. The folds are the viewer's own derivation, so they are asked, not re-derived here.
        from coyomap.viewer.gen_viewer import folded_buckets_roster, folded_libs  # heavy; only this kind
        from coyomap.views import model_to_graph
        graph = model_to_graph(m)
        for fb in folded_buckets_roster(graph):
            if any(mem["id"] == eid for mem in fb["members"]):
                return [("v", "bucketfold"), ("bkid", str(fb["id"])), node]
        if any(d["id"] == eid for d in folded_libs(graph)):
            return [("v", "libs"), node]
        return [("v", "context"), node]
    return _page_state(m, el, kind)


def _element(m: ProjectModel, eid: str) -> Element | None:
    if eid.startswith("EP"):  # minted by assemble, so not in ID_ARRAYS and not in all_elements
        return next((ep for ep in m.entry_points if ep.id == eid), None)
    el = all_elements(m).get(eid)
    return el if isinstance(el, (Group, UseCase, Role, Component, Dep, Entity, Interface, SubFlow,
                                 BusinessRule, HappyStep)) else None


def link_for(m: ProjectModel, eid: str, context: bool = False) -> MapLink | None:
    """The link for one element, or None when the map does not define it."""
    el = _element(m, eid)
    info = resolve_id(m, eid)
    if el is None or info is None:
        return None
    kind = str(info["kind"])
    pairs = _context_state(m, el, kind) if context else _page_state(m, el, kind)
    return MapLink(id=eid, kind=kind, name=str(info.get("name") or ""), view=pairs[0][1],
                   fragment=urlencode(pairs))


# ── the running server ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Located:
    """Where the map is served, if anywhere: the server that lists it and the path it gives."""
    server: RunningServer | None
    path: str                 # `/coyomap/<slug>/` — the server's own spelling when it has one
    note: str                 # what to tell a reader when the address is incomplete ('' when whole)
    state: str                # served | no-server | not-listed — the note's reason, as one word

    #: The three answers, so a caller branches on a word instead of grepping the note. `served` is
    #: the only one with a whole address; the other two are told apart because the remedies differ —
    #: with NO server you start one, and with one that does not list the map you add the folder to
    #: the server that is already up rather than starting a second.
    SERVED = "served"
    NO_SERVER = "no-server"
    NOT_LISTED = "not-listed"


def _recents_of(server: RunningServer) -> list[dict[str, Any]] | None:
    """The server's recents payload, or None when it does not answer."""
    # A generous timeout: a dead port refuses at once, so only a live server that is slow to answer
    # costs the wait — and /api/recents rebuilds the served set from every remembered folder, which
    # on a long recents list takes a few seconds.
    try:
        with urlopen(f"{server.base}/api/recents", timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (URLError, OSError, ValueError):
        return None
    return [it for it in data if isinstance(it, dict)] if isinstance(data, list) else None


def _same_folder(a: str, b: Path) -> bool:
    try:
        return Path(a).resolve() == b.resolve()
    except OSError:
        return False


def locate(folder: Path, running_path: Path = RUNNING_PATH) -> Located:
    """Find a live server that lists `folder`, asking each recorded one for its recents. The path
    comes from the server (its `url` field) so this never spells the prefix; without a server the
    fallback is the same definition the server uses, with the folder's name as the slug."""
    answered: list[RunningServer] = []
    for server in running_servers(running_path):
        items = _recents_of(server)
        if items is None:
            continue  # recorded but silent: a pid reused, or a server still starting
        answered.append(server)
        for it in items:
            if it.get("ok") and it.get("url") and _same_folder(str(it.get("path") or ""), folder):
                return Located(server=server, path=str(it["url"]), note="", state=Located.SERVED)
    fallback = map_url(folder.name)
    if answered:
        ports = ", ".join(str(s.port) for s in answered)
        return Located(server=None, path=fallback, state=Located.NOT_LISTED, note=(
            f"note: the coyomap server on port {ports} does not list {folder}. Open its landing page "
            f"and add the folder, or rebuild the map (rendering registers it); then run this again."))
    return Located(server=None, path=fallback, state=Located.NO_SERVER, note=(
        "note: no coyomap server is running, so this is the path only. Start one from the coyomap "
        f"clone ({COYOMAP_HOME}): `make start`, or `.venv/bin/coyomap serve`; then run this again "
        "for the full address."))


# ── the command ────────────────────────────────────────────────────────────────────────────────

_USAGE = """usage: coyomap url <ID> [--repo <dir> | --map <file>] [--context] [--json]
       coyomap url --home [--view <screen>] [--repo <dir> | --map <file>] [--json]

Print the address that opens the served map on ONE element, already selected — the last line of a
"show me X in the map" answer. Read-only: it registers nothing and writes nothing.

  <ID>         an element id from .coyomap/project-map.json: UC12, CAP3, C7, S2, SD1, E4, D9, I5,
               R1, SF30, BLK2, BR12, HP6, EP40 (grep the map for the name; `coyomap dump --id`
               says what an id is)
  --home       the map's own address instead of an element's — the front door a finished build
               hands the reader. No id, no fragment, and the map is not parsed.
  --view WORD  a whole-map SCREEN instead of the front door (implies --home): `updates` is the
               Update log, what an update hands the reader. No element is selected.
  --repo DIR   the mapped repo; its .coyomap/project-map.json is read (default: the current folder)
  --map FILE   the map file itself, when it is not at <repo>/.coyomap/project-map.json
  --context    "show in context": the element's home view with it selected (a feature pinned on
               Features, a component lit inside its subsystem) instead of its own page
  --json       {id, kind, name, view, fragment, path, url, server, state, note} — the first five
               are null under --home. `url` and `server` are null when no running server lists the
               map, and `state` says why: served | no-server | not-listed.

The host and port come from the running server (~/.coyomap/serve-running.json, written by
`coyomap serve`). With none running, the path and fragment are printed alone and a note says so."""


def main(argv: list[str] | None = None, *, running_path: Path = RUNNING_PATH) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        print(_USAGE)
        return 0
    ids: list[str] = []
    repo: str | None = None
    map_arg: str | None = None
    context = as_json = home = False
    view: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--home":
            home = True
        elif a == "--view":
            # A following flag is a MISSING screen, not a screen called "--repo": swallowing it
            # would report the next option as an unknown screen and leave the real slip unsaid.
            i += 1
            if i >= len(argv) or argv[i].startswith("-"):
                print(f"ERROR: --view needs a screen ({', '.join(HOME_VIEWS)})", file=sys.stderr)
                return 2
            view, home = argv[i], True  # naming a screen IS the no-element mode
        elif a in ("--repo", "--map"):
            i += 1
            if i >= len(argv):
                print(f"ERROR: {a} needs a path", file=sys.stderr)
                return 2
            if a == "--repo":
                repo = argv[i]
            else:
                map_arg = argv[i]
        elif a == "--context":
            context = True
        elif a == "--json":
            as_json = True
        elif a.startswith("-"):
            print(f"ERROR: unknown option '{a}'\n{_USAGE}", file=sys.stderr)
            return 2
        else:
            ids.append(a)
        i += 1
    if view is not None and view not in HOME_VIEWS:
        print(f"ERROR: '{view}' is no screen this command can address. One of: "
              f"{', '.join(HOME_VIEWS)}", file=sys.stderr)
        return 2
    if home and ids:
        print(f"ERROR: --home is the map's own address, so it takes no element id (got "
              f"{' '.join(ids)})\n{_USAGE}", file=sys.stderr)
        return 2
    if home and context:
        print("ERROR: --context selects an element, so it cannot be combined with --home",
              file=sys.stderr)
        return 2
    if not home and len(ids) != 1:
        print(f"ERROR: give exactly ONE element id, got {len(ids)} (or --home for the map's own "
              f"address)\n{_USAGE}", file=sys.stderr)
        return 2
    eid = "" if home else ids[0]
    if eid and not ID_SHAPE.match(eid):
        print(f"ERROR: '{eid}' is not an element id (an id is a prefix and digits: UC12, CAP3, C7, "
              "EP40 …)", file=sys.stderr)
        return 2
    if repo and map_arg:
        print("ERROR: give --repo or --map, not both", file=sys.stderr)
        return 2
    map_path = Path(map_arg) if map_arg else Path(repo or ".") / ".coyomap" / "project-map.json"
    if not map_path.is_file():
        print(f"ERROR: {map_path} not found — is this a mapped repo? (see --repo / --map)", file=sys.stderr)
        return 1
    # --home asks WHERE the map is served, never WHAT it says, so it does not parse the map: a build
    # that has just written one should still be able to hand over its address, and the gates are what
    # judge the contents. It still goes through `resolve_map_path`, because the slip that guard
    # exists for (a shell that drifted into the clone) hands back a plausible address for the wrong
    # product exactly as it hands back a plausible result — and a closing message is where nobody
    # would look twice.
    link: MapLink | None = None
    if home:
        resolve_map_path(map_path)
    else:
        try:
            m = load_model_path(map_path)
        except ModelError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        link = link_for(m, eid, context)
        if link is None:
            print(f"ERROR: {eid} is not defined in the map", file=sys.stderr)
            return 1
    folder = map_path.resolve().parent.parent  # <repo>/.coyomap/project-map.json -> <repo>
    where = locate(folder, running_path)
    fragment = link.fragment if link else (f"v={view}" if view else "")
    tail = f"#{fragment}" if fragment else ""
    url = f"{where.server.base}{where.path}{tail}" if where.server else None
    if as_json:
        empty = {"id": None, "kind": None, "name": None, "view": view, "fragment": fragment or None}
        print(json.dumps({**(asdict(link) if link else empty), "path": where.path, "url": url,
                          "server": {"port": where.server.port, "pid": where.server.pid}
                          if where.server else None,
                          "state": where.state, "note": where.note}, indent=2, ensure_ascii=False))
    else:
        print(url or f"{where.path}{tail}")
    if where.note:
        print(where.note, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
