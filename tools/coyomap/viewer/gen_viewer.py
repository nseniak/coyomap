#!/usr/bin/env python3
"""Build the view bundle a coyomap map's frontend renders — the graph plus every pre-rendered diagram.

Reads a graph.json (from build_graph.py) and produces a
`ViewBundle` (via `build_view_bundle`): the graph, every altitude's Mermaid source, the use-case
flows, colours, and source-link config. `coyomap serve` calls this per request and serves the bundle
as JSON at /coyomap/<slug>/api/view; the generic frontend (viewer.html + viewer.js/css, served from the
same folder) fetches it and renders. Mermaid + svg-pan-zoom load from a pinned CDN with SRI.
The viewer offers these altitudes — Context (C4; external SYSTEMS drawn by name, while in-process
framework/library deps fold into one ⌘-clickable "Libraries" box that drills to the full list) →
Subsystems (click a box to select it + its linked
subsystems, or ⌘-click to drill in; click an arrow to select it — the side panel lists every
component edge it bundles — or ⌘-click to drill into the pair's edge card; while ⌘ is held, drillable
boxes/arrows show a drill-in cursor) → a subsystem's components → code links — navigated as a
back/forward history within one frame, wraps Mermaid's SVG with pan/zoom and a click->side-panel
bridge, and a baseline<->diff toggle (on the Subsystems views) that badges added/modified/deleted/
rippled elements. A map with no subsystem of its own gets one synthetic default subsystem (build_graph),
so the component-level view is always reached by drilling a subsystem. The flat whole-repo component
map (gen_mermaid / MERMAID_BASE / MERMAID_DIFF and the viewer's `component` state) is no longer wired
to a tab — it is kept dormant and restorable.

Node labels are the element name only (no ID prefix) to keep them uncluttered;
the ID still appears in the panel header and drives the bridge via the cy-<ID>
class.

Normally called in-process by `coyomap serve`. For two-stage debugging (dumps the bundle JSON):
    python -m coyomap.viewer.gen_viewer [graph.json] [view-bundle.json]
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from html import escape as html_escape
from pathlib import Path
from typing import Any, TypedDict, cast
from urllib.parse import quote

from coyomap.viewer.build_graph import GraphDict
from coyomap.features import as_bundle, build_index
from coyomap.model import ModelError, ProjectModel, load_model
from coyomap import records
from coyomap.validate_model import DATA_OWNER_EXCEPTIONS_HEADING
from coyomap.impact_git import Extents, load_map_extents
from coyomap import grammar
from coyomap.grammar import (  # external-dep Kind fold rule + the purpose-bucket grouping axis
    DEP_BUCKET_FOLD_AT, DEP_KINDS_FOLDED, DEP_KINDS_SYSTEM, canonical_bucket, order_buckets,
    resolve_bucket, unit_name_matches_dep,
)

# Synthetic node id for the collapsed "Libraries" box in the Context view (folds framework + library
# deps out of the C4 Context altitude). Not a real element id (no prefix+digits), so it never
# collides; the viewer resolves it via its `cy-LIBS` class and the synthetic node added to the panel
# graph. The viewer.js side uses the same literal — keep them in step.
LIBS_ID = "LIBS"


def _git(args: list[str], cwd: Path) -> str | None:
    """Run a read-only git command in `cwd`; return stripped stdout, or None on any failure
    (not a repo, git missing, no remote). Build-time only — never blocks rendering."""
    try:
        out = subprocess.run(["git", "-C", str(cwd), *args],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def repo_state(anchor: Path, commit: str | None) -> str:
    """Can the viewer actually read this map's CODE? — `ok` / `no-repo` / `no-commit`.

    Every source read (the file browser, the code viewer) goes through git at the map's pinned
    commit, so two setups show a map whose every file click fails:

    * **`no-repo`** — the map's folder is not inside a git work tree at all. A `.coyomap/` copied
      somewhere for inspection is the common case: the map opens, every diagram works, and every file
      404s. The old per-file message ("Not tracked in this commit") blamed the commit for what is
      really a missing repo, and it only appeared after a click.
    * **`no-commit`** — a git repo is there, but it does not have the pinned commit (a different
      clone, a shallow one, a branch fetched without it).

    Cheap: two `git` calls, and callers cache it with the rest of the map's derived data. Both probes
    PRINT on success (`rev-parse` echoes the path / the sha) — `_git` reports empty output as failure,
    so a silent-on-success probe like `cat-file -e` would read as "missing" every time."""
    top = _git(["rev-parse", "--show-toplevel"], anchor)
    if not top:
        return "no-repo"
    sha = (commit or "").removesuffix("-dirty").strip()
    if sha and sha.lower() != "unknown" and not _git(["rev-parse", "--verify", f"{sha}^{{commit}}"], anchor):
        return "no-commit"
    return "ok"


def commit_stamp(anchor: Path, commit: str | None, committed: str | None) -> str:
    """The pinned commit's date AND time, for the header — `2026-07-29 14:32`.

    The model stores only the commit DATE (`committed`, `%cs`), which cannot tell two commits of the
    same day apart; the time is read from git here, where the repo is at hand. A `-dirty` pin names a
    real commit plus uncommitted code, so the suffix is stripped before asking git and the map still
    reports the commit it was pinned to. Falls back to the stored date whenever git cannot answer
    (no repo, unknown sha, git missing), so a map read outside its repo still shows what it knows."""
    sha = (commit or "").removesuffix("-dirty").strip()
    if sha and sha.lower() != "unknown":
        stamp = _git(["show", "-s", "--format=%cd", "--date=format:%Y-%m-%d %H:%M", sha], anchor)
        if stamp:
            return stamp
    return committed or ""


def repo_root_default(anchor: Path) -> str:
    """Absolute path of the mapped repo, seeded into the viewer as the default source root for
    'open in editor' links. The viewer overrides this with a per-machine value in localStorage, so a
    wrong path on a teammate's checkout is fixable in Settings without a rebuild. Falls back to the
    output file's directory when `anchor` is not inside a git work tree."""
    top = _git(["rev-parse", "--show-toplevel"], anchor)
    return top or str(anchor.resolve())


def gh_repo_url(anchor: Path) -> str | None:
    """GitHub repository URL ('https://github.com/<owner>/<repo>') from the `origin` remote, for the
    'open on GitHub' target. None when there is no `origin` remote or it is not github.com. The viewer
    combines this with the map's commit into blob links and lets the user override the URL in Settings."""
    url = _git(["remote", "get-url", "origin"], anchor)
    if not url:
        return None
    m = re.search(r"github\.com[:/]+([^/]+)/(.+?)(?:\.git)?/?$", url)
    return f"https://github.com/{m.group(1)}/{m.group(2)}" if m else None

SHAPE = {"component": ('["', '"]'), "dep": ('[("', '")]')}
DIAGRAM_KINDS = ("component", "dep")

# Domain (T5) relationship kind -> Mermaid classDiagram arrow. The diamond/triangle sits at the
# `src` (left) end, matching how the relation is authored on the source entity's card.
CLASS_ARROW = {"inheritance": "--|>", "composition": "*--", "aggregation": "o--", "association": "-->"}


def _safe_label(name: str) -> str:
    """Sanitize a node name for a Mermaid label — the ONE place every diagram's label text is made
    Mermaid-safe, so no call site has to re-escape by hand. Neutralised: `"`/backtick (markdown-string
    mode), `[`/`]` (node-shape syntax), `{`/`}` (flowchart rhombus + classDiagram member block), `|`
    (edge-label delimiter), `<`/`>` (open an HTML tag under securityLevel:'loose' htmlLabels). An
    intentional `<br/>` is added by callers OUTSIDE this function, so it is never stripped here."""
    return (
        name.replace('"', "'")
        .replace("`", "")
        .replace("[", "(")
        .replace("]", ")")
        .replace("{", "(")
        .replace("}", ")")
        .replace("|", "/")
        .replace("<", "‹")
        .replace(">", "›")
    )


def _count_label(n: int) -> str:
    """The pipe label for an AGGREGATED flowchart arrow — or nothing at all when it stands for one link.

    A count of 1 says nothing a click would not: the arrow already is that one link, and clicking it names
    it. Measured over three maps: of 8012 labelled arrows, 1801 carry a count and 1118 of those counts are
    "1". Dropping them takes 14% of every label off the diagrams and costs the reader nothing.

    2 and up stay. "33" is the difference between a glance and a sit-down, and it is the only place the
    diagram says how much is folded into a line. The biggest on the reference maps is 33.

    Written "×33", never a bare "33": a bare number on an arrow already means something else in the
    product — a step position on a use-case flow map — and a reader carries that habit between views.
    "×" is the one marker that says "this many folded in" without a legend."""
    return f"|×{n}|" if n >= 2 else ""


def _count_suffix(n: int) -> str:
    """The same rule (and the same × marker) for a classDiagram relation, whose label is a ` : n`
    suffix rather than a pipe."""
    return f" : ×{n}" if n >= 2 else ""


def _edge_label(text: str) -> str:
    """Sanitize authored text for a Mermaid PIPE edge label (`-->|…|`) — and return it WITH its quotes,
    so a call site can never forget them.

    A pipe label is far stricter than a node label: unquoted, `(`, `)`, `[`, `]`, `{`, `}` and `@` are
    hard PARSE errors, and one bad character fails the WHOLE diagram (the frontend then shows "this view
    could not be rendered"), not just that label. Quoting admits all of them, so authored text survives
    intact — a channel named `gateway.rpc.{guild_id}` or a verb reading `emits (fan-out)` renders as
    itself instead of being mangled by `_safe_label`'s node-shape substitutions.

    Only what quoting cannot cover is neutralised: `"`/backtick, which would close the string early,
    and `<`/`>`, which open an HTML tag under securityLevel:'loose' htmlLabels."""
    inner = text.replace('"', "'").replace("`", "").replace("<", "‹").replace(">", "›")
    return f'"{inner}"'


def _draw_nodes(graph: GraphDict) -> list[tuple[str, str, str]]:
    """(id, label, kind) for every node drawn at component level."""
    return [(nid, str(node["name"]), str(node["kind"])) for nid, node in graph["nodes"].items()
            if str(node["kind"]) in DIAGRAM_KINDS]


def _diagram_edges(graph: GraphDict, ids: set[str]) -> list[tuple[str, str, str]]:
    edges: list[tuple[str, str, str]] = [
        (str(e["src"]), str(e["verb"]), str(e["dst"])) for e in graph["edges"]
    ]
    return [(s, v, d) for (s, v, d) in edges if s in ids and d in ids]


def gen_mermaid(graph: GraphDict, only: set[str] | None = None) -> str:
    """Nodes keep their baseline kind styling; change status is shown by JS badges, not fill.
    `only` (a set of ids) restricts the drawing to those components + the deps they touch — used
    for the per-subsystem drill-down view."""
    draw = _draw_nodes(graph)
    if only is not None:
        keep = set(only)
        for e in graph["edges"]:
            s, d = str(e["src"]), str(e["dst"])
            if s in keep and str(graph["nodes"].get(d, {}).get("kind")) == "dep":
                keep.add(d)
            if d in keep and str(graph["nodes"].get(s, {}).get("kind")) == "dep":
                keep.add(s)
        draw = [(nid, name, kind) for (nid, name, kind) in draw if nid in keep]
    ids = {nid for nid, _, _ in draw}
    lines = ["flowchart TB"]
    for nid, name, kind in draw:
        open_b, close_b = SHAPE[kind]
        label = _safe_label(name)  # name only — no ID prefix
        lines.append(f"  {nid}{open_b}{label}{close_b}:::cy-{nid}")
        lines.append(f"  class {nid} {kind}")
    for src, verb, dst in _diagram_edges(graph, ids):
        lines.append(f"  {src} -->|{_edge_label(verb)}| {dst}")
    lines.append(f"  classDef component {COMPONENT_STYLE};")
    lines.append(f"  classDef dep {DEP_STYLE};")
    return "\n".join(lines)


def _parent_of(graph: GraphDict, nid: str) -> str | None:
    n = graph["nodes"].get(nid)
    return cast("str | None", n.get("parent")) if n else None


def _top_group(graph: GraphDict, nid: str) -> str | None:
    """Walk parent pointers up to the top-level GROUP above `nid` (or None). Generic over the grouping
    kind — a component resolves to its top subsystem (`S`), an entity to its top subdomain (`SD`) —
    because the two forests share the one `parent` pointer over disjoint id spaces. Callers that mean a
    specific altitude must use _top_subsystem / _top_subdomain, NOT this directly, so the two altitudes
    never bleed (an entity endpoint must not read as an inter-subsystem crossing, and vice versa)."""
    cur = _parent_of(graph, nid)
    if cur is None:
        return None
    seen: set[str] = set()
    while True:
        p = _parent_of(graph, cur)
        if p is None or p in seen:
            return cur
        seen.add(cur)
        cur = p


def _top_subsystem(graph: GraphDict, nid: str) -> str | None:
    """`nid`'s top group, but ONLY when it is a subsystem (`S`) — else None. The component/subsystem
    altitude uses this so an entity endpoint (top group = a SUBDOMAIN) never reads as an inter-subsystem
    crossing. Before subdomains existed an entity had no parent, so C→E / E→E edges were silently
    excluded from the Subsystems overview; now they must be excluded explicitly by kind."""
    g = _top_group(graph, nid)
    return g if g is not None and str(graph["nodes"].get(g, {}).get("kind")) == "subsystem" else None


def _top_subdomain(graph: GraphDict, nid: str) -> str | None:
    """`nid`'s top group, but ONLY when it is a subdomain (`SD`) — else None. The domain-altitude mirror
    of _top_subsystem, so a component/dep endpoint never reads as an inter-subdomain crossing."""
    g = _top_group(graph, nid)
    return g if g is not None and str(graph["nodes"].get(g, {}).get("kind")) == "subdomain" else None


def _child_under(graph: GraphDict, nid: str, ancestor: str | None) -> str | None:
    """The immediate child of `ancestor` on the path down to `nid` — the LEVEL-RELATIVE bucket that
    replaces flatten-to-top. Returns `nid` itself when its direct parent is `ancestor`; the
    intermediate child-group when `nid` is deeper; None when `nid` is not in `ancestor`'s subtree.
    With `ancestor=None` it is `nid`'s top-level ancestor (i.e. `_top_group`), so the root overview
    is just the card of the virtual root. This is what lets a subsystem card show its IMMEDIATE
    children (and bucket a deep endpoint into the child box that contains it) instead of flattening."""
    cur, seen = nid, set()
    while True:
        p = _parent_of(graph, cur)
        if p == ancestor:
            return cur
        if p is None or p in seen:
            return None
        seen.add(cur)
        cur = p


def _sibling_level_box(graph: GraphDict, nid: str, sid: str) -> str | None:
    """The subsystem box to draw `nid` as in `sid`'s card when `nid` is OUTSIDE sid's subtree: the
    ancestor of `nid` that is a sibling of `sid` (shares sid's parent), so neighbours read at sid's
    own altitude. Falls back to nid's top-level subsystem when nid is not under sid's parent (a
    distant link still shows, collapsed). None when no subsystem box applies (e.g. an ungrouped
    component) — matching the old `_top_subsystem` skip. For a top-level `sid` (parent None) this is
    exactly `_top_subsystem(nid)`, so flat maps are unchanged."""
    b = _child_under(graph, nid, _parent_of(graph, sid))
    if b is not None and str(graph["nodes"].get(b, {}).get("kind")) == "subsystem":
        return b
    return _top_subsystem(graph, nid)


def has_grouping(graph: GraphDict) -> bool:
    return any(str(n.get("kind")) == "subsystem" for n in graph["nodes"].values())


def has_domain(graph: GraphDict) -> bool:
    return any(str(n.get("kind")) == "entity" for n in graph["nodes"].values())


def has_subdomains(graph: GraphDict) -> bool:
    """True when the domain model is grouped into subdomains (a `SD` node exists) — gates the Domain
    view's Subdomains overview, exactly as has_grouping gates the Subsystems view."""
    return any(str(n.get("kind")) == "subdomain" for n in graph["nodes"].values())


def _safe_member(s: str) -> str:
    """Sanitize an attribute type/name for a classDiagram member line: `<>{}|"` and backticks break
    member parsing (generics use `~`, not `<>`)."""
    return re.sub(r'[<>{}|`"]', "", s).strip()


def _relation_label(edge: dict[str, Any]) -> str:
    """Arrow label — REAL field name(s) only (an invented relationship verb isn't grounded in code).
    The backing field(s) are resolved once in build_graph (`fk_fields` / `fk_side`); here we only
    format them: forward (fields on the source / arrow-tail) -> the field name (`subscription`,
    `org_id`), or a comma-joined list for a composite key (`user_id, page_id`); reverse (FK on the
    target / arrow-head) -> `↩ field`. When no field backs the relation, a storage key (`keyed_by`)
    draws as `«key» name(s)` — a lookup/partition key the store imposes, marked distinct from a real
    row FK; blank when there is neither (the `{how}` note then explains it in the click-panel)."""
    fields = edge.get("fk_fields") or []
    if not fields:
        keyed = edge.get("keyed_by") or []
        if keyed:  # a storage/lookup key (not a row FK) — marked distinct with «key»
            return "«key» " + _safe_label(", ".join(str(k) for k in keyed))
        return ""
    label = _safe_label(", ".join(str(f) for f in fields))
    return label if edge.get("fk_side") == "src" else "↩ " + label


def _store_line(node: dict[str, Any], dep_names: dict[str, str]) -> str | None:
    """WHERE an entity is persisted — `🛢 guilds(MongoDB)` — rendered in the class box's SECOND
    compartment, the one below the divider that classDiagram reserves for methods and that these
    boxes otherwise leave empty. Two deliberate placement choices:

    * NOT a `<<…>>` stereotype — that draws ABOVE the class name, costing the diagram its "every box
      leads with the entity name" uniformity;
    * NOT a plain member line — that shares the compartment with the real fields, where a store reads
      as one more property.

    Landing in that second compartment REQUIRES the `name(args)` method shape, so the store name
    renders parenthesised (a verified constraint: classDiagram strips any space before the paren).
    Parens inside the names would nest and break parsing — a live map ships a dep literally named
    `Redis (cache / main)` — so both parts drop them. Shown ONLY for an entity with a physical store
    (`store.dep` + a container), matching the ghost fill; a not-persisted entity carries no line."""
    st = cast("dict[str, str] | None", node.get("store"))
    if not st or not st.get("dep") or not st.get("container"):
        return None
    depobj = dep_names.get(str(st["dep"]), str(st["dep"]))
    where = _safe_member(depobj).replace("(", "").replace(")", "").strip()
    container = _safe_member(str(st["container"])).replace("(", "").replace(")", "").strip()
    return f"🛢 {container}({where})" if container else None


# The DETAIL separator: everything after it on a member line is the field's key markers. Chosen because
# no type/name carries it, so the marker run stays unambiguously separable from the field itself.
DETAIL_SEP = " · "
# Key/relation markers, in fixed render order (determinism) — the map's own vocabulary, shortened.
# `[]` is deliberately absent: it is part of the type's SHAPE and already rides on the type itself.
# The authored `?` renders as `opt`: a bare `?` is a symbol the reader has to guess, while PK/FK/uniq
# are words they already know — every marker should read, not need decoding.
_MARKER_LABEL: tuple[tuple[str, str], ...] = (("PK", "PK"), ("FK", "FK"), ("unique", "uniq"), ("?", "opt"))
_TTL_AMOUNT = re.compile(r"(?:TTL\s*(?:of\s*)?(\d+\s*[-\w]+)|(\d+[-\s]?\w+)\s*TTL)", re.I)


def _field_markers(markers: str) -> str:
    """The toggleable key markers for one field — `PK`, `FK`, `uniq`, `opt` — as a ` · `-prefixed
    suffix (`string id · PK`). Every live map is full of these (one map: 47 PK, 52 FK, 50 optional)
    and the box drew NONE of them; they answer "which field is the key / points elsewhere / is
    optional" without opening the panel. An `FK→E7` marker renders as bare `FK`: which entity it
    points at is already drawn as the relation arrow between the two boxes."""
    have = {m.split("→")[0].strip() for m in markers.split()}
    out = [label for key, label in _MARKER_LABEL if key in have]
    return DETAIL_SEP + " ".join(out) if out else ""


def _retention_line(node: dict[str, Any]) -> str | None:
    """`⏱ retention(30 days)` — the TTL an entity's store notes record, promoted out of prose onto the
    box (live maps bury "TTL 30 days" mid-sentence in the notes). Rendered in the same second
    compartment as the store line, and only when the notes actually mention a TTL."""
    st = cast("dict[str, str] | None", node.get("store"))
    notes = str(st.get("notes", "")) if st else ""
    if not notes or "ttl" not in notes.lower():
        return None
    hit = _TTL_AMOUNT.search(notes)
    amount = (hit.group(1) or hit.group(2)).strip() if hit else "TTL"
    return f"⏱ retention({_safe_member(amount).replace('(', '').replace(')', '')})"


def _lifecycle_line(node: dict[str, Any]) -> str | None:
    """`⟳ lifecycle(3 states)` — a marker that this entity's code declares a state machine, which the
    diagram otherwise never showed (the states themselves stay in the panel, where they fit). Rare by
    nature (5 entities across three live maps), so it costs the diagram nothing when absent."""
    n = int(node.get("states_count") or 0)
    return f"⟳ lifecycle({n} states)" if n else None


def _extra_rows(node: dict[str, Any], dep_names: dict[str, str]) -> list[str]:
    """The lines an entity box draws in its SECOND compartment — where it lives, how long it is kept,
    its lifecycle — in drawn order, absent ones dropped. Its own function because the store line is
    also a LINK (entity_store_links needs the line's index in this compartment), and the drawn order
    must be decided exactly once."""
    return [x for x in (_store_line(node, dep_names), _retention_line(node), _lifecycle_line(node)) if x]


def _member_rows(node: dict[str, Any], ent_names: dict[str, str]) -> list[tuple[str, str, str]]:
    """One `(member line, type text, target entity id)` per attribute line an entity box draws, in
    drawn order. The ONE place that decides both what a member line says and which entity (if any)
    its type names — the viewer turns these same rows into per-field links, so a link can never point
    somewhere other than the type the reader is looking at. `target` is '' for a plain type
    (`string`, or a type that isn't an entity in this map)."""
    rows: list[tuple[str, str, str]] = []
    for a in cast("list[dict[str, str]]", node.get("attrs") or []):
        # an embedded-entity-id type (`mode:E10`) renders with the entity's NAME, not its id
        raw = str(a.get("type", ""))
        atype = _safe_member(ent_names.get(raw, raw))
        # `[]` is part of the type's SHAPE (it makes the field multi-valued), so it rides on the type
        # — unlike PK/FK/opt/unique, which render as a toggleable ` · ` suffix (see _field_markers).
        markers = str(a.get("markers", ""))
        if "[]" in markers.split():
            atype += "[]"
        member = f'{atype} {_safe_member(str(a.get("name", "")))}'.strip()
        if member:
            rows.append((f"{member}{_field_markers(markers)}", atype, raw if raw in ent_names else ""))
    return rows


def _class_box_lines(nid: str, node: dict[str, Any], ent_names: dict[str, str],
                     with_members: bool, dep_names: dict[str, str] | None = None) -> list[str]:
    """The `classDiagram` lines for one entity box. `with_members=True` renders its attributes
    (`type name`, each with its toggleable key markers) plus, in the box's own second compartment,
    where it is persisted (`🛢 guilds(MongoDB)`), its retention and its lifecycle; `with_members=False`
    renders a bare box — used for a cross-subdomain NEIGHBOUR entity in a per-subdomain card, so it
    reads as collapsed (its detail lives in its own subdomain's view). Shared by the flat Domain view
    and the per-subdomain card so a class renders identically in both.

    The detail extras are ALWAYS emitted — the generator is the one place that decides what a box says.
    (A viewer-side "Details" toggle used to hide them in the rendered SVG; it was removed as a control
    nobody needed, and one that could silently leave a reader with a poorer diagram.)"""
    label = _safe_label(str(node["name"]))
    if not with_members:
        return [f'  class {nid}["{label}"]']
    out = [f'  class {nid}["{label}"] {{']
    for line, _atype, _target in _member_rows(node, ent_names):
        out.append(f"    {line}")
    # Second compartment (below the divider): where it lives, how long it is kept, its lifecycle.
    for extra in _extra_rows(node, dep_names or {}):
        out.append(f"    {extra}")
    out.append("  }")
    return out


def entity_field_links(graph: GraphDict) -> dict[str, list[dict[str, Any]]]:
    """Per entity, every attribute line whose TYPE is another entity of this map — `{i, type, target}`,
    where `i` is that line's index among the members its box draws and `type` is the exact type text
    drawn there. The viewer turns each one into a click target on the type word, so a field like
    `Role[] roles` selects the Role entity. Computed HERE, off the same rows the box is built from,
    because what a member line says is a generator decision (entity-name lookup, the `[]` shape,
    sanitising) the frontend must never re-derive — re-deriving it is how a link starts pointing at
    something other than the word under the cursor."""
    ent_names = {nid: str(n["name"]) for nid, n in graph["nodes"].items() if str(n["kind"]) == "entity"}
    out: dict[str, list[dict[str, Any]]] = {}
    for nid, n in graph["nodes"].items():
        if str(n["kind"]) != "entity":
            continue
        rows = _member_rows(cast("dict[str, Any]", n), ent_names)
        links = [{"i": i, "type": atype, "target": target}
                 for i, (_line, atype, target) in enumerate(rows) if target]
        if links:
            out[nid] = links
    return out


def entity_store_links(graph: GraphDict) -> dict[str, dict[str, Any]]:
    """Per entity that draws a store line (`🛢 guilds(MongoDB)`), what that line should link to —
    `{i, text, dep}`, where `i` is the line's index in the box's SECOND compartment and `dep` is the
    dependency the store lives in. The viewer turns the line into a link into the Data tab, focused on
    that store's pane and this entity's row — the same jump the info pane's "See in Data view" makes.
    Emitted here for the same reason the field links are (see entity_field_links): the drawn text is a
    generator decision, and the frontend must not re-derive it."""
    dep_names = _dep_name_map(graph)
    out: dict[str, dict[str, Any]] = {}
    for nid, n in graph["nodes"].items():
        if str(n["kind"]) != "entity":
            continue
        node = cast("dict[str, Any]", n)
        line = _store_line(node, dep_names)
        dep = str((node.get("store") or {}).get("dep") or "")
        if not line or not dep:
            continue
        out[nid] = {"i": _extra_rows(node, dep_names).index(line), "text": line, "dep": dep}
    return out


def _class_relation_line(e: dict[str, Any]) -> str:
    """The `classDiagram` arrow line for one domain relation (kind + cardinality + backing-field
    label). Shared by the flat Domain view and the per-subdomain card so an edge renders identically."""
    s, d, kind = str(e["src"]), str(e["dst"]), str(e.get("kind"))
    arrow = CLASS_ARROW.get(kind, "-->")
    label = _relation_label(e)
    suffix = f" : {label}" if label else ""
    if kind == "inheritance":
        # The inheritance triangle is a VERB-DERIVED fact: it trusts the authored `isA`/`extends`
        # verb, which no gate verifies against the code (method.md: verbs may prioritize, never
        # gate). Never field-backed, so no cardinality label to clash with the verb.
        return f"  {s} {arrow} {d} : {_safe_label(str(e.get('verb') or 'isA'))}"
    left = f'"{e["src_card"]}" ' if e.get("src_card") else ""
    right = f' "{e["dst_card"]}"' if e.get("dst_card") else ""
    return f"  {s} {left}{arrow}{right} {d}{suffix}"


def _domain_relation_edges(graph: GraphDict) -> list[dict[str, Any]]:
    """The E→E domain-relation edges — a relation `kind` is set AND both endpoints are entity nodes.
    Distinct from component edges (no kind) and the C→E bridge edges (no kind, dst is an entity); the
    source for the Domain view's derived SD→SD arrows and the per-subdomain card's drawn relations."""
    nodes = graph["nodes"]
    return [cast("dict[str, Any]", e) for e in graph["edges"]
            if e.get("kind") and str(nodes.get(str(e["src"]), {}).get("kind")) == "entity"
            and str(nodes.get(str(e["dst"]), {}).get("kind")) == "entity"]


def _entities_of(graph: GraphDict, sdid: str) -> list[tuple[str, str]]:
    """(id, name) of the DIRECT child entities of `sdid` (parent is exactly `sdid`), the domain mirror
    of _components_of. Entities nested in child subdomains are drawn one level down, on those
    subdomains' own cards. Leaf subdomain: direct == all, so flat maps are unchanged."""
    return [(eid, str(n["name"])) for eid, n in graph["nodes"].items()
            if str(n["kind"]) == "entity" and _parent_of(graph, eid) == sdid]


def _child_subdomains(graph: GraphDict, sdid: str) -> list[tuple[str, str]]:
    """(id, name) of the DIRECT child subdomains of `sdid` — drawn inside its card as collapsed,
    drillable boxes (the domain mirror of _child_subsystems). Empty for a leaf subdomain."""
    return [(c, str(n["name"])) for c, n in graph["nodes"].items()
            if str(n["kind"]) == "subdomain" and _parent_of(graph, c) == sdid]


def _descendant_entity_count(graph: GraphDict, sdid: str) -> int:
    """Number of entities anywhere under `sdid` (any depth) — the '(N)' shown on a collapsed neighbour
    box or the Subdomains-overview box, so the label reflects the whole subtree, not just direct kids.
    Flat: equals the direct count."""
    return sum(1 for eid, n in graph["nodes"].items()
               if str(n["kind"]) == "entity" and _child_under(graph, eid, sdid) is not None)


def _sibling_subdomain_box(graph: GraphDict, nid: str, sdid: str) -> str | None:
    """The subdomain box to draw `nid` as in `sdid`'s card when `nid` is OUTSIDE sdid's subtree — the
    domain mirror of _sibling_level_box: the ancestor of `nid` sharing sdid's parent, else nid's
    top-level subdomain. For a top-level `sdid` this is exactly `_top_subdomain(nid)`, so flat maps are
    unchanged."""
    b = _child_under(graph, nid, _parent_of(graph, sdid))
    if b is not None and str(graph["nodes"].get(b, {}).get("kind")) == "subdomain":
        return b
    return _top_subdomain(graph, nid)


def _dep_name_map(graph: GraphDict) -> dict[str, str]:
    """`D-id → display name` for every dependency node — what an entity box's store line names as the
    place it lives (`🛢 guilds(MongoDB)`). Read off the graph rather than stored on each entity node,
    so the name can't drift from the dep it points at."""
    return {nid: str(n["name"]) for nid, n in graph["nodes"].items() if str(n["kind"]) == "dep"}


def gen_domain_mermaid(graph: GraphDict) -> str:
    """C4 Code altitude: the T5 domain model as a Mermaid `classDiagram` — each entity a class box
    (id = its `E` id, label = its name) holding its attributes (`type name`), with typed, cardinal
    relations between entities. Markers (PK/FK/…) live in the click->panel, since classDiagram boxes
    carry no native key notation. Class id = the `E` id so the viewer's id bridge resolves a click.
    This is the FLAT whole-model view; on a subdomain-grouped map the viewer leads with the Subdomains
    overview (gen_domain_container_mermaid) and drills into one subdomain's card."""
    ents = [(nid, n) for nid, n in graph["nodes"].items() if str(n["kind"]) == "entity"]
    ent_ids = {nid for nid, _ in ents}
    ent_names = {nid: str(n["name"]) for nid, n in ents}
    dep_names = _dep_name_map(graph)
    lines = ["classDiagram"]
    for nid, n in ents:
        lines += _class_box_lines(nid, cast("dict[str, Any]", n), ent_names, True, dep_names)
    for nid, _ in ents:  # tint each entity (light fuchsia member) — the flat view has no namespace to inherit from
        lines.append(f"  style {nid} {ENTITY_STYLE}")
    for e in graph["edges"]:
        if e.get("kind") and str(e["src"]) in ent_ids and str(e["dst"]) in ent_ids:
            lines.append(_class_relation_line(cast("dict[str, Any]", e)))
    return "\n".join(lines)


# Element palettes — TINT PER FAMILY: one hue per family, the container box a DEEPER shade of the
# member's hue, so a member visibly belongs to its container while the two families stay distinct.
#   Structural family = INDIGO: component (member, indigo-50) inside subsystem (container, indigo-200).
#   Domain family     = FUCHSIA: entity (member, fuchsia-50) inside subdomain (container, fuchsia-200).
# Within a family the container + member share the stroke and differ only by fill depth; the families
# differ by hue (indigo vs fuchsia), so subsystem≠subdomain AND component≠entity (the old clash, where
# the entity used Mermaid's default lavender ≈ the component's indigo, is gone). Defined once, reused as
# flowchart `classDef`s and as classDiagram per-id `style`s (classDiagram has no classDef-by-name).
# A container's border is also drawn thicker AND dashed (`stroke-width` + `stroke-dasharray`) — a
# SECOND, colour-blind-safe signal (on top of the JS-injected corner icon) that a box is a container,
# not a leaf, since fill depth alone is easy to miss. Only subsystem/subdomain carry it.
_CONTAINER_BORDER = "stroke-width:2.5px,stroke-dasharray:6 3"
COMPONENT_STYLE = "fill:#eef2ff,stroke:#3730a3,color:#1e1b4b"  # indigo-50   — component (C), light member
SUBSYSTEM_STYLE = f"fill:#c7d2fe,stroke:#3730a3,color:#1e1b4b,{_CONTAINER_BORDER}"  # indigo-200  — subsystem (S), deep container
ENTITY_STYLE    = "fill:#fdf4ff,stroke:#86198f,color:#581c87"  # fuchsia-50  — entity (E), light member
SUBDOMAIN_STYLE = f"fill:#f5d0fe,stroke:#86198f,color:#581c87,{_CONTAINER_BORDER}"  # fuchsia-200 — subdomain (SD), deep container
DEP_STYLE       = "fill:#ecfdf5,stroke:#065f46,color:#064e3b"  # emerald     — external dependency (D)
INTERFACE_STYLE = "fill:#fffbeb,stroke:#b45309,color:#78350f"  # amber-50    — interface (I), the door a
                                                               # story crosses the product's edge at
# An actor box, wherever one is drawn as a flowchart node (the Context view's stick figures and
# hexagons, a use-case map's driving actor) — one constant per kind so the views can never drift apart.
# The human/service distinction is the METHOD's, not decoration: a `service` actor is an autonomous
# initiator, and drawing one as a person reads as "somebody did this" when nobody did.
ACTOR_HUMAN_STYLE = "fill:#fff7ed,stroke:#c2410c,color:#7c2d12"  # orange-50   — human actor (R)
ACTOR_SVC_STYLE   = "fill:#eef2ff,stroke:#4338ca,color:#312e81"  # indigo-50   — service actor (R)
# A dependency/library GROUP container (the Libraries bundle box + folded bucket count boxes): the SAME
# emerald as the deps/libraries it holds, distinguished as a drillable group only by the shared dashed
# container border (the convention subsystems/subdomains already use), never by a foreign hue.
CONTAINER_STYLE = f"fill:#ecfdf5,stroke:#065f46,color:#064e3b,{_CONTAINER_BORDER}"
PROCESS_STYLE   = f"fill:#fef3c7,stroke:#b45309,color:#78350f,{_CONTAINER_BORDER}"  # amber-100 — a deployable process/thread (Deployment view), a runtime container
INFRA_STYLE     = "fill:#f1f5f9,stroke:#475569,color:#1e293b"  # slate       — infrastructure node (broker/store) in the Deployment view
# Deployment infra BANDING by derived role (WS2 grammar.dep_roles): a broker/store/service dep's colour
# in the Deployment view's Infrastructure lane echoes its role band. Roleless infra falls back to slate.
INFRA_BUS_STYLE   = "fill:#ede9fe,stroke:#6d28d9,color:#4c1d95"  # violet — message bus (messaging)
INFRA_STORE_STYLE = "fill:#e0f2fe,stroke:#0369a1,color:#0c4a6e"  # sky    — data store (datastore)
INFRA_SVC_STYLE   = "fill:#ccfbf1,stroke:#0f766e,color:#134e4a"  # teal   — service (service)
INFRA_SEC_STYLE   = "fill:#ffe4e6,stroke:#be123c,color:#881337"  # rose   — security (encrypt)
# (band_role, subgraph id, lane title, mermaid classDef name) — fixed display order; a dual-role dep
# lands in the FIRST band it qualifies for (messaging beats datastore, per the redesign).
#
# The titles say "Used as …" because that is what the band actually measures: `_infra_band_of`
# reads the dep's VERB-DERIVED role first and only falls back to its declared `kind`. So two deps
# of the same kind can land in different bands — on a live map Mixpanel (`kind: service`, reached
# by `emits`) sat under the bus band while Sentry (`kind: service`, reached by `calls`) sat under
# the service band, and a reader scanning for queues found an analytics SaaS. That grouping is
# deliberate and useful — "how does the code talk to this?" is a question no other view answers —
# but a bare "Message bus" states it as an identity claim the map never made. The label now says
# which question it is answering, so the same picture reads correctly.
_INFRA_BANDS: tuple[tuple[str, str, str, str], ...] = (
    ("messaging", "L_infra_bus", "Used as a message bus", "infraBus"),
    ("datastore", "L_infra_store", "Used as a data store", "infraStore"),
    ("service", "L_infra_svc", "Used as a service", "infraSvc"),
    ("security", "L_infra_sec", "Used for security", "infraSec"),
    # The roleless fallback — no verb-derived role AND no infra `kind` to fall back to, so there is
    # no usage to state. It stays a plain "Other" rather than claiming one.
    ("other", "L_infra_other", "Other", "infra"),
)
DOMAIN_SUBDOMAIN_CLASSDEF = f"  classDef subdomain {SUBDOMAIN_STYLE};"


def _fill_stroke(style: str) -> dict[str, str]:
    """`{'fill':…, 'stroke':…, 'strokeWidth':…, 'strokeDasharray':…}` parsed from a
    `fill:…,stroke:…,color:…[,stroke-width:…,stroke-dasharray:…]` style string — the stroke-width/dasharray
    keys only present for a container style, so the viewer can tell a drilled subsystem/subdomain CLUSTER
    frame (which `style`/classDef can't reach) apart from a member's."""
    d: dict[str, str] = {}
    for part in style.split(","):
        k, _, v = part.partition(":")
        d[k.strip()] = v.strip()
    out = {"fill": d["fill"], "stroke": d["stroke"]}
    if "stroke-width" in d:
        out["strokeWidth"] = d["stroke-width"]
    if "stroke-dasharray" in d:
        out["strokeDasharray"] = d["stroke-dasharray"]
    return out


# Per-kind fill/stroke, injected into the viewer so it can recolour elements Mermaid renders with a
# default (kind-agnostic) palette: an EXPANDED group's CLUSTER frame (a drilled subsystem subgraph /
# subdomain namespace — defaults to pale yellow, and `style` can't reach a classDiagram namespace) and a
# FLOW sequence diagram's participant boxes (every `participant` is the same default box, so an entity
# would read like a component). Derived from the box styles above — one source for every view.
ELEMENT_TINT = {
    "component": _fill_stroke(COMPONENT_STYLE),
    "interface": _fill_stroke(INTERFACE_STYLE),
    "dep": _fill_stroke(DEP_STYLE),
    "entity": _fill_stroke(ENTITY_STYLE),
    "subsystem": _fill_stroke(SUBSYSTEM_STYLE),
    "subdomain": _fill_stroke(SUBDOMAIN_STYLE),
    "process": _fill_stroke(PROCESS_STYLE),
    "infra": _fill_stroke(INFRA_STYLE),
    # The Context/Libraries PURPOSE-bucket group frames (`CYBK<i>` clusters) and the folded count boxes:
    # the SAME emerald as the deps/libraries they hold + the dashed container border, so a group reads as
    # "a drillable box of these" rather than a foreign-coloured panel. Matches CONTAINER_STYLE.
    "bucket": {"fill": "#ecfdf5", "stroke": "#065f46", "strokeWidth": "2.5px", "strokeDasharray": "6 3"},
    "bucketfold": {"fill": "#ecfdf5", "stroke": "#065f46", "strokeWidth": "2.5px", "strokeDasharray": "6 3"},
    # The remaining drawn vocabularies, so the viewer's LEGEND can build its swatches from the very
    # styles the diagrams paint with (one source of truth — a legend that can drift is worse than none).
    # `color` too: the System is the one box dark enough that its LABEL has to be repainted with it —
    # the Happy Path's System lifeline is a default Mermaid participant, and a dark fill under the
    # default near-black label is unreadable. (The flowchart views get the colour from their classDef.)
    "system": {"fill": "#1e1b4b", "stroke": "#312e81", "color": "#fff"},
    "human": {"fill": "#fff7ed", "stroke": "#c2410c"},
    "svc": {"fill": "#eef2ff", "stroke": "#4338ca"},
    "infraBus": _fill_stroke(INFRA_BUS_STYLE),
    "infraStore": _fill_stroke(INFRA_STORE_STYLE),
    "infraSvc": _fill_stroke(INFRA_SVC_STYLE),
    "infraSec": _fill_stroke(INFRA_SEC_STYLE),
    # ── the kinds the ITEM BOX draws that no diagram had a colour for ────────────────────────────
    # An AI agent wears the program colour and the person's stance; the viewer draws the bot figure.
    "agent": {"fill": "#eef2ff", "stroke": "#4338ca"},
    # A SHARED SUB-USE CASE is not an element of the product, it is a piece of another use case's story, so
    # it wears no element colour. Slate, and the dashed border every "there is more inside" box has.
    "subflow": {"fill": "#f8fafc", "stroke": "#475569", "strokeWidth": "2.5px",
                "strokeDasharray": "6 3"},
    # A FEATURE and a USE CASE are the light-member / deep-container pair a component and a subsystem
    # already make in indigo, here in sky. SKY, and not the person's warm orange the feature glyph
    # used to borrow, because on the Features picture a feature's box sits between the person's and
    # the data area's and has to differ from both: 36 from the person, 40 from the data area, where
    # the warm alternative (rose #ffe4e6) managed only 20 from the person.
    #
    # It is close to the component's indigo (14 and 7), and that costs nothing only because neither
    # a feature nor a use case ever shares a picture with a component. THE RULE THAT FALLS OUT, and
    # it has to be checked whenever a new picture is drawn: a kind's colour must be far from the
    # kinds it SHARES A PICTURE WITH, not from every kind in the map.
    "feature": {"fill": "#e0f2fe", "stroke": "#0369a1"},
    "usecase": {"fill": "#f0f9ff", "stroke": "#0284c7"},
    # A BUSINESS RULE and its DECISION AREA share ONE stroke, the container's fill deeper — the
    # component/subsystem shape. Rose, and the rule above is what picks it: a rule is drawn on no
    # diagram at all, so the only place it sits beside another kind is a card list and the search
    # results, and rose is far from every hue those already hold. `infraSec` is the same family, and
    # that costs nothing: it is a box on the Dependencies and Deployment pictures, which no rule card
    # is ever drawn on.
    #
    # No dashed border on the area, unlike the other two containers. The dash says "there is more
    # inside this FRAME", and a decision area is never drawn as a frame — it is a card you open.
    #
    # The two MARKS are a scale and a scroll (see itemMarkD), which unlike every other container pair
    # is not "the member drawn twice". The colour is what carries the family resemblance instead, so
    # it does more work here than it does for the pairs whose shapes already match.
    "rule": {"fill": "#fff1f2", "stroke": "#be123c"},
    "block": {"fill": "#fecdd3", "stroke": "#be123c"},
}

def gen_domain_container_mermaid(graph: GraphDict) -> str:
    """Domain Container altitude: each top-level subdomain (`SD`) an ITEM BOX — a slot the viewer fills
    with the same box every other picture draws (see gen_flow_map_mermaid), its record count in the
    box's band — with inter-subdomain arrows DERIVED from the E→E relation list (a `SDa → SDb` arrow
    exists iff a domain relation crosses, labelled by count). The exact mirror of
    gen_container_mermaid for components — the scalable entry point into a large domain model."""
    lines = [SLOT_MAP_INIT, "flowchart TB"]  # no node padding: the boxes carry their own, arrows stop on them
    for nid, node in graph["nodes"].items():
        if str(node["kind"]) == "subdomain" and _parent_of(graph, nid) is None:
            lines.append(f'  {nid}["{_slot("subdomain", "compact", nid)}"]:::cy-{nid}')
            lines.append(f"  class {nid} itembox")
    counts: dict[tuple[str, str], int] = {}
    for e in _domain_relation_edges(graph):
        ca, cb = _top_subdomain(graph, str(e["src"])), _top_subdomain(graph, str(e["dst"]))
        if ca and cb and ca != cb:
            counts[(ca, cb)] = counts.get((ca, cb), 0) + 1
    for (ca, cb), c in sorted(counts.items()):
        lines.append(f"  {ca} -->{_count_label(c)} {cb}")
    lines.append(ITEM_SLOT_CLASSDEF)
    return "\n".join(lines)


def _subdomain_ancestors(graph: GraphDict, nid: str) -> list[str]:
    """The subdomain ids on `nid`'s parent chain (nearest first) — the domain mirror of
    _subsystem_ancestors, enumerating the boxes `nid` collapses into at successive drill levels."""
    out: list[str] = []
    cur, seen = _parent_of(graph, nid), set()
    while cur and cur not in seen:
        seen.add(cur)
        if str(graph["nodes"].get(cur, {}).get("kind")) == "subdomain":
            out.append(cur)
        cur = _parent_of(graph, cur)
    return out


def _domain_edge_card_pairs(graph: GraphDict) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Every disjoint ordered subdomain pair (a, b) an entity relation crosses between, with the
    crossing relations — the domain mirror of _edge_card_pairs (subdomain ancestors of each endpoint,
    disjoint only), covering the pair at every drill level. The single source for the domain edge-card
    diagrams and the per-arrow crossing lists."""
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in _domain_relation_edges(graph):
        s, d = str(e["src"]), str(e["dst"])
        for a in _subdomain_ancestors(graph, s):
            for b in _subdomain_ancestors(graph, d):
                if _disjoint(graph, a, b):
                    out.setdefault((a, b), []).append(e)
    return out


def gen_domain_container_edges(graph: GraphDict) -> dict[str, list[dict[str, str]]]:
    """For each inter-subdomain arrow 'A>B' the viewer can draw — at the Domain overview AND inside any
    (possibly nested) subdomain card — the underlying entity→entity relations crossing from A's subtree
    to B's (endpoints, names, verb, kind), listed in the arrow's hover tooltip / select panel. Derived
    from the one _domain_edge_card_pairs source, keyed 'A>B' to match the relation bridge."""
    out: dict[str, list[dict[str, str]]] = {}
    for (a, b), edges in _domain_edge_card_pairs(graph).items():
        out[f"{a}>{b}"] = [{
            "src": str(e["src"]),
            "dst": str(e["dst"]),
            "srcName": str(graph["nodes"][str(e["src"])]["name"]) if str(e["src"]) in graph["nodes"] else str(e["src"]),
            "dstName": str(graph["nodes"][str(e["dst"])]["name"]) if str(e["dst"]) in graph["nodes"] else str(e["dst"]),
            "verb": str(e["verb"]),
            "kind": str(e.get("kind") or ""),
            "where": str(e["where"]) if e.get("where") else "",  # call-site path:line -> per-row source link
        } for e in edges]
    return out


def _subdomain_namespace(graph: GraphDict, sdid: str,
                         members: list[tuple[str, str]],
                         keep: set[str] | None = None) -> list[str]:
    """`classDiagram` lines framing a subdomain's entities as `namespace <sdid>["Name"] { … }` —
    each member entity drawn full (attributes). The classDiagram analog of `_component_subgraph`:
    a subdomain always reads as a labelled frame (Mermaid 11 namespaces render as a titled cluster,
    DOM-id `cluster-<sdid>`, with the inner class group ids unchanged so the id bridge still resolves).
    The title is the bare name — NO member count: when zoomed into the frame the entities are drawn
    inside, so the count is redundant (it stays on the COLLAPSED subdomain boxes, where it can't be
    seen). This matches the subsystem frame (`_component_subgraph`), which never carried one.
    Shared by the subdomain card and the domain edge card. `members` is already whatever the caller
    chose to draw; `keep` filters the CHILD-SUBDOMAIN boxes this builds itself, which the edge card
    narrows the same way it narrows the entities (see gen_domain_edge_card)."""
    nodes = graph["nodes"]
    ent_names = {nid: str(n["name"]) for nid, n in nodes.items() if str(n["kind"]) == "entity"}
    nm = _safe_label(str(nodes[sdid]["name"])) if sdid in nodes else sdid
    out = [f'namespace {sdid}["{nm}"] {{']
    for eid, _ in members:
        out += _class_box_lines(eid, cast("dict[str, Any]", nodes[eid]), ent_names, True,
                                _dep_name_map(graph))
    for cid, _ in _child_subdomains(graph, sdid):  # nested child subdomains: collapsed item boxes, drillable
        if keep is not None and cid not in keep:
            continue
        out.append(f'  class {cid}["{_slot("subdomain", "compact", cid)}"]')
    out.append("}")
    for eid, _ in members:  # tint each focal entity (light fuchsia member); `style` lives OUTSIDE the namespace
        out.append(f"  style {eid} {ENTITY_STYLE}")
    return out


# The reverse structure↔domain bridge — a collapsed box per subsystem whose components touch an entity —
# used to be drawn onto the subdomain card and the entity-pair page. Both are ENTITY diagrams, and a
# subsystem box on one of them made an arrow ambiguous: "relates to" and "writes" looked alike. The
# builder went with its two callers. The same bridge is still drawn from the structural side, on the
# subsystem card, and the subsystem × subdomain page is about nothing else.
def gen_domain_subdomain_card(graph: GraphDict, sdid: str) -> str:
    """A per-subdomain `classDiagram` neighbourhood: `sdid` framed as a `namespace` holding its own
    entities (full attributes), every OTHER subdomain its entities relate to drawn as a collapsed
    member-less box (one per neighbour subdomain, labelled `Name (N)`), the focal subdomain's internal
    relations drawn in full, and one arrow (labelled by its count of crossing relations) per (focal
    entity, neighbour subdomain) pair. NO subsystem boxes (see the note in the body): the structure↔domain
    bridge is drawn from the subsystem card's side only. The entity analog of gen_subsystem_card_mermaid
    — each screen stays small no matter the total model size, neighbours stay collapsed, and the viewer
    turns a click on a neighbour subdomain box into that subdomain's card, and a click on a cross arrow
    into the two-subdomain edge card. Node ids +
    relation shapes match the flat Domain view, so the class/relation bridge resolves a click to the
    entity panel or the relation detail."""
    members = _entities_of(graph, sdid)          # direct child entities (drawn full)
    member_ids = {eid for eid, _ in members}
    child_sd_ids = {c for c, _ in _child_subdomains(graph, sdid)}  # nested child subdomains (collapsed, drillable)
    nodes = graph["nodes"]
    if not members and not child_sd_ids:
        # A defined-but-empty subdomain would leave a body-less classDiagram, which Mermaid rejects
        # (the drill would throw). Emit a placeholder class so the card stays a VALID, self-explaining
        # diagram; its id carries no prefix+digits, so the viewer's id bridge skips it. (Returning here
        # also skips the relation/bridge loops below, which would all be empty with no member entities.)
        name = _safe_label(str(nodes[sdid]["name"])) if sdid in nodes else sdid
        return f'classDiagram\n  class EmptySubdomain["{name} — no entities"]'
    internal: list[dict[str, Any]] = []   # both endpoints DIRECT entities of this subdomain — drawn full
    cross: dict[tuple[str, str], int] = {}   # (focal box, neighbour-subdomain box) -> crossing count
    childcross: dict[tuple[str, str], int] = {}  # (box, nested child-subdomain box) -> aggregated count
    nb_sds: set[str] = set()
    # Bucket each relation endpoint at THIS card's level via `_child_under` (the domain mirror of the
    # subsystem card): a direct entity buckets to itself, a deeper one to the child-subdomain box that
    # holds it, an out-of-subtree one to None. Leaf subdomain -> each is the entity itself or None,
    # identical to the old `in member_ids` / `_top_subdomain` flat behaviour.
    for e in _domain_relation_edges(graph):
        s, d = str(e["src"]), str(e["dst"])
        bs, bd = _child_under(graph, s, sdid), _child_under(graph, d, sdid)
        if bs is not None and bd is not None:          # both inside sdid's subtree
            if bs == s and bd == d:
                internal.append(e)                     # two direct entities -> full relation
            elif bs != bd:
                childcross[(bs, bd)] = childcross.get((bs, bd), 0) + 1  # child-subdomain box -> aggregated
        elif bs is not None:                           # outbound crossing to outside sdid
            nb = _sibling_subdomain_box(graph, d, sdid)
            if nb and nb != sdid:
                cross[(bs, nb)] = cross.get((bs, nb), 0) + 1
                nb_sds.add(nb)
        elif bd is not None:                           # inbound crossing from outside sdid
            nb = _sibling_subdomain_box(graph, s, sdid)
            if nb and nb != sdid:
                cross[(nb, bd)] = cross.get((nb, bd), 0) + 1
                nb_sds.add(nb)
    lines = ["classDiagram", *_subdomain_namespace(graph, sdid, members)]
    # A COLLAPSED SUBDOMAIN IS AN ITEM BOX, here as on the Domain overview: the class draws no shape of
    # its own (ITEM_SLOT_STYLE) and the viewer swaps the box into its label, count in the band.
    for cid in sorted(child_sd_ids):  # the nested child-subdomain boxes (declared inside the namespace)
        lines.append(f"  style {cid} {ITEM_SLOT_STYLE}")
    for nb in sorted(nb_sds):  # collapsed neighbour-subdomain boxes
        lines.append(f'  class {nb}["{_slot("subdomain", "compact", nb)}"]')
        lines.append(f"  style {nb} {ITEM_SLOT_STYLE}")
    # NO SUBSYSTEM BOXES. An entity diagram draws entities and the subdomains that hold them, and nothing
    # else. It used to add a collapsed box for every subsystem whose components touch one of these
    # entities, which put two different kinds of thing on one canvas: a reader could not tell whether an
    # arrow meant "this entity relates to that one" or "this code writes that entity".
    # The fact is not lost. The subsystem card draws the same bridge from the other side, and the
    # subsystem × subdomain page exists for nothing else.
    for e in internal:  # the focal subdomain's own relations, full
        lines.append(_class_relation_line(e))
    for (src, dst), c in sorted(cross.items()):  # crossing arrows to/from collapsed neighbour boxes (click → edge card)
        lines.append(f"  {src} --> {dst}{_count_suffix(c)}")
    for (src, dst), c in sorted(childcross.items()):  # nested child-subdomain arrows (aggregated; box drills in)
        lines.append(f"  {src} --> {dst}{_count_suffix(c)}")
    return "\n".join(lines)


def domain_subdomain_mermaids(graph: GraphDict) -> dict[str, str]:
    """One per-subdomain card per subdomain at EVERY level (see gen_domain_subdomain_card), so a nested
    child subdomain has its own card to drill into — the domain mirror of subsystem_component_mermaids."""
    return {nid: gen_domain_subdomain_card(graph, nid)
            for nid, node in graph["nodes"].items()
            if str(node["kind"]) == "subdomain"}


def gen_domain_edge_card(graph: GraphDict, a: str, b: str) -> str:
    """Domain edge card: disjoint subdomains `a` and `b` framed as `namespace` blocks holding their
    IMMEDIATE entities (full) + child-subdomain boxes, drawn with the a→b crossings PLUS each frame's own
    internal relations. A crossing between two DIRECT entities keeps its full relation (so the bridge
    resolves it); a crossing into a child subdomain is an aggregated box arrow. It also draws the reverse
    structure↔domain bridge (collapsed subsystem boxes that own/read either frame's direct entities). The
    entity analog of gen_edge_card_mermaid (only the a→b direction; the b→a arrow has its own card)."""
    ents_a = _entities_of(graph, a)            # direct child entities of each frame
    ents_b = _entities_of(graph, b)
    # ONLY THE ENTITIES A CROSSING RELATION TOUCHES — the same rule the subsystem edge card follows, and
    # for the same reason: the card answers "what does this arrow stand for", and an entity at neither end
    # of any crossing is not part of that answer. Measured over two maps: 28 of these cards drew 656 entity
    # boxes, and 394 of those 656 (60%) touched no crossing relation.
    cross: list[dict[str, Any]] = []
    agg: dict[tuple[str, str], int] = {}
    for e in _domain_relation_edges(graph):
        s, d = str(e["src"]), str(e["dst"])
        if not (_in_subtree(graph, s, a) and _in_subtree(graph, d, b)):
            continue
        ba, bb = str(_child_under(graph, s, a)), str(_child_under(graph, d, b))
        if ba == s and bb == d:                                          # both direct entities -> full relation
            cross.append(cast("dict[str, Any]", e))
        else:                                                            # reaches into a child subdomain -> aggregated box arrow
            agg[(ba, bb)] = agg.get((ba, bb), 0) + 1
    drawn = ({str(e["src"]) for e in cross} | {str(e["dst"]) for e in cross}
             | {box for pair in agg for box in pair})
    ids_a = {eid for eid, _ in ents_a} & drawn
    ids_b = {eid for eid, _ in ents_b} & drawn
    lines = ["classDiagram",
             *_subdomain_namespace(graph, a, [x for x in ents_a if x[0] in drawn], keep=drawn),
             *_subdomain_namespace(graph, b, [x for x in ents_b if x[0] in drawn], keep=drawn)]
    for cid, _ in _child_subdomains(graph, a) + _child_subdomains(graph, b):  # style the child boxes drawn in the frames
        if cid in drawn:
            lines.append(f"  style {cid} {ITEM_SLOT_STYLE}")  # an item box, as on the subdomain card
    # No subsystem boxes here either — see gen_domain_subdomain_card. Entities and subdomains only.
    for e in _domain_relation_edges(graph):  # a frame's inner wiring, between two entities both drawn
        s, d = str(e["src"]), str(e["dst"])
        if (s in ids_a and d in ids_a) or (s in ids_b and d in ids_b):
            lines.append(_class_relation_line(cast("dict[str, Any]", e)))
    for e in cross:
        lines.append(_class_relation_line(e))
    for (src, dst), c in sorted(agg.items()):
        lines.append(f"  {src} --> {dst}{_count_suffix(c)}")
    return "\n".join(lines)


def domain_edge_card_mermaids(graph: GraphDict) -> dict[str, str]:
    """One edge-card per disjoint subdomain pair with a crossing relation — at every drill level, not
    only top-level — keyed 'A>B' to match the rendered arrow's endpoints. The entity analog of
    edge_card_mermaids, built from the one _domain_edge_card_pairs source."""
    return {f"{a}>{b}": gen_domain_edge_card(graph, a, b) for (a, b) in sorted(_domain_edge_card_pairs(graph))}


def gen_bridge_card_mermaid(graph: GraphDict, sid: str, sdid: str) -> str:
    """Bridge card: subsystem `sid` and subdomain `sdid` framed side by side — the structure↔domain
    relationship — with the component→entity edges between them: a direct link drawn unlabelled (one
    concrete edge, resolves to it on click), a crossing into a child group aggregated into a
    count-labelled box arrow. The analog of
    the edge cards across the two groupings (S×S pairs two subsystems, SD×SD two subdomains; this pairs a
    subsystem with a subdomain). Rendered as a classDiagram so the subsystem's components (member-less,
    simple boxes) and the subdomain's entities (full boxes) share one canvas; node ids + the C→E edges
    match the component view, so the viewer resolves an in-card arrow to its real edge."""
    nodes = graph["nodes"]
    # C→E edges crossing sid's subtree -> sdid's subtree, bucketed to each frame's immediate children:
    # a direct member->direct entity link is ONE concrete edge (resolves to it on click, not drillable),
    # drawn UNLABELLED; a crossing into a child group aggregates several edges -> count-labelled box arrow.
    # Worked out FIRST, because it also decides which boxes the card draws (see below).
    direct: set[tuple[str, str]] = set()
    agg: dict[tuple[str, str], int] = {}
    for e in graph["edges"]:
        s, d = str(e["src"]), str(e["dst"])
        if str(nodes.get(s, {}).get("kind")) != "component" or str(nodes.get(d, {}).get("kind")) != "entity":
            continue
        if not (_in_subtree(graph, s, sid) and _in_subtree(graph, d, sdid)):
            continue
        bs, bd = str(_child_under(graph, s, sid)), str(_child_under(graph, d, sdid))
        if bs == s and bd == d:            # both direct -> one concrete link, unlabelled
            direct.add((bs, bd))
        else:                              # reaches into a child group -> aggregated, count-labelled
            agg[(bs, bd)] = agg.get((bs, bd), 0) + 1
    # ONLY THE BOXES A CROSSING TOUCHES — the third arrow card following the one rule (see
    # gen_edge_card_mermaid). Measured over three maps: 82 bridge cards drew 1416 boxes between them, and
    # 1042 of those 1416 (74%) touched no crossing arrow.
    drawn = {box for pair in (direct | set(agg)) for box in pair}
    comps = [x for x in _components_of(graph, sid) if x[0] in drawn]      # direct component members
    ents = [x for x in _entities_of(graph, sdid) if x[0] in drawn]        # direct entity members
    child_subs = [x for x in _child_subsystems(graph, sid) if x[0] in drawn]
    child_sds = [x for x in _child_subdomains(graph, sdid) if x[0] in drawn]
    lines = ["classDiagram", f'namespace {sid}["{_safe_label(str(nodes[sid]["name"]))}"] {{']
    for cid, name in comps:  # direct components as member-less (simple) boxes
        lines.append(f'  class {cid}["{_safe_label(name)}"]')
    for ssid, sname in child_subs:  # child subsystems as collapsed (drillable) boxes
        lines.append(f'  class {ssid}["{_safe_label(sname)}"]')
    lines.append("}")
    lines += _subdomain_namespace(graph, sdid, ents, keep=drawn)  # its immediate entities (+ child SD boxes)
    for cid, _ in comps:  # indigo — read as components, not entities
        lines.append(f"  style {cid} {COMPONENT_STYLE}")
    for ssid, _ in child_subs:
        lines.append(f"  style {ssid} {SUBSYSTEM_STYLE}")
    for cid, _ in child_sds:
        lines.append(f"  style {cid} {SUBDOMAIN_STYLE}")
    for bs, bd in sorted(direct):
        lines.append(f"  {bs} --> {bd}")
    for (bs, bd), c in sorted(agg.items()):
        lines.append(f"  {bs} --> {bd}{_count_suffix(c)}")
    return "\n".join(lines)


def bridge_card_mermaids(graph: GraphDict) -> dict[str, str]:
    """One bridge card per (subsystem-ancestor, subdomain-ancestor) pair joined by a C→E edge
    — at EVERY drill level, so a NESTED subsystem card's bridge arrow (key `nestedS>SD`) and a nested
    subdomain card's reverse bridge (key `S>nestedSD`) both resolve. Keyed 'S>SD'; the cross-grouping
    analog of edge_card_mermaids (no disjoint check — the two forests never overlap)."""
    nodes = graph["nodes"]
    pairs: set[tuple[str, str]] = set()
    for e in graph["edges"]:
        s, d = str(e["src"]), str(e["dst"])
        if str(nodes.get(s, {}).get("kind")) == "component" and str(nodes.get(d, {}).get("kind")) == "entity":
            for a in _subsystem_ancestors(graph, s):
                for b in _subdomain_ancestors(graph, d):
                    pairs.add((a, b))
    return {f"{sub}>{sd}": gen_bridge_card_mermaid(graph, sub, sd) for sub, sd in sorted(pairs)}


def gen_container_mermaid(graph: GraphDict) -> str:
    """C4 Container: each top-level subsystem an ITEM BOX — a slot the viewer fills with the same box
    every other picture draws (see gen_flow_map_mermaid), its component count in the box's band — with
    inter-subsystem edges DERIVED from the component edge list (an S->S arrow exists iff a component
    edge crosses), labeled by count. The exact mirror of gen_domain_container_mermaid for entities."""
    lines = [SLOT_MAP_INIT, "flowchart TB"]  # no node padding: the boxes carry their own, arrows stop on them
    for nid, node in graph["nodes"].items():
        if str(node["kind"]) == "subsystem" and _parent_of(graph, nid) is None:
            lines.append(f'  {nid}["{_slot("subsystem", "compact", nid)}"]:::cy-{nid}')
            lines.append(f"  class {nid} itembox")
    counts: dict[tuple[str, str], int] = {}
    for e in graph["edges"]:
        sa, sb = _top_subsystem(graph, str(e["src"])), _top_subsystem(graph, str(e["dst"]))
        if sa and sb and sa != sb:
            counts[(sa, sb)] = counts.get((sa, sb), 0) + 1
    for (sa, sb), c in sorted(counts.items()):
        lines.append(f"  {sa} -->{_count_label(c)} {sb}")
    lines.append(ITEM_SLOT_CLASSDEF)
    return "\n".join(lines)


def _subsystem_ancestors(graph: GraphDict, nid: str) -> list[str]:
    """The subsystem ids on `nid`'s parent chain (nearest first) — the boxes `nid` collapses into at
    successive drill levels. Used to enumerate the disjoint pairs a component edge crosses between."""
    out: list[str] = []
    cur, seen = _parent_of(graph, nid), set()
    while cur and cur not in seen:
        seen.add(cur)
        if str(graph["nodes"].get(cur, {}).get("kind")) == "subsystem":
            out.append(cur)
        cur = _parent_of(graph, cur)
    return out


def _in_subtree(graph: GraphDict, nid: str, anc: str) -> bool:
    """True when `nid` is strictly inside `anc`'s subtree (its level-relative bucket exists)."""
    return _child_under(graph, nid, anc) is not None


def _disjoint(graph: GraphDict, a: str, b: str) -> bool:
    """True when subsystems `a` and `b` are neither equal nor nested — so they can frame a two-box edge
    card without overlapping. Overlapping (ancestor/descendant) pairs are navigated, never carded."""
    return a != b and not _in_subtree(graph, a, b) and not _in_subtree(graph, b, a)


def _edge_card_pairs(graph: GraphDict) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Every disjoint ordered subsystem pair (a, b) a component edge crosses between, with the crossing
    edges. `a`/`b` range over the subsystem ancestors of the edge's endpoints, so this covers the pair
    at EVERY drill level (the top-level overview arrow AND a nested card's cross arrow) — a superset of
    what any single card draws, keyed to match the viewer's edge bridge. The single source for both the
    edge-card diagrams and the per-arrow crossing lists."""
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in graph["edges"]:
        s, d = str(e["src"]), str(e["dst"])
        if str(graph["nodes"].get(s, {}).get("kind")) != "component" \
                or str(graph["nodes"].get(d, {}).get("kind")) != "component":
            continue
        for a in _subsystem_ancestors(graph, s):
            for b in _subsystem_ancestors(graph, d):
                if _disjoint(graph, a, b):
                    out.setdefault((a, b), []).append(e)
    return out


def gen_container_edges(graph: GraphDict) -> dict[str, list[dict[str, str]]]:
    """For each inter-subsystem arrow 'A>B' the viewer can draw — at the Subsystems overview AND inside
    any (possibly nested) subsystem card — the underlying component->component edges crossing from A's
    subtree to B's (endpoints, names, verb, why), listed in the arrow's hover tooltip / select panel.
    Derived from the one _edge_card_pairs source, keyed 'A>B' to match the edge bridge."""
    out: dict[str, list[dict[str, str]]] = {}
    for (a, b), edges in _edge_card_pairs(graph).items():
        out[f"{a}>{b}"] = [{
            "src": str(e["src"]),
            "dst": str(e["dst"]),
            "srcName": str(graph["nodes"][str(e["src"])]["name"]) if str(e["src"]) in graph["nodes"] else str(e["src"]),
            "dstName": str(graph["nodes"][str(e["dst"])]["name"]) if str(e["dst"]) in graph["nodes"] else str(e["dst"]),
            "verb": str(e["verb"]),
            "why": str(e["why"]) if e["why"] else "",
            "where": str(e["where"]) if e.get("where") else "",  # call-site path:line -> per-row source link
        } for e in edges]
    return out


def gen_bridge_edges(graph: GraphDict) -> list[dict[str, str]]:
    """Every component->entity edge — the structure<->domain bridge ATOM — with resolved endpoint names
    and call site. A bridge arrow (component->subdomain box in a subsystem card, subsystem box->entity in
    a subdomain/domain view, or a child-box arrow inside a bridge card) bundles a subset of these; the
    viewer filters this ONE flat list by the clicked arrow's drawn endpoints — a leaf end by id, a group
    (subsystem/subdomain) end by subtree membership — to list exactly the C->E links that arrow stands
    for at any level. The bridge analog of gen_container_edges (flat, not pre-keyed, because the same
    edge is reachable from differently-keyed arrow shapes; subtree tests live in the viewer, which
    already walks the parent chain, so no per-level ancestor is baked here)."""
    nodes = graph["nodes"]
    out: list[dict[str, str]] = []
    for e in graph["edges"]:
        s, d = str(e["src"]), str(e["dst"])
        if str(nodes.get(s, {}).get("kind")) != "component" or str(nodes.get(d, {}).get("kind")) != "entity":
            continue
        out.append({
            "src": s,
            "dst": d,
            "srcName": str(nodes[s]["name"]) if s in nodes else s,
            "dstName": str(nodes[d]["name"]) if d in nodes else d,
            "verb": str(e["verb"]),
            "why": str(e["why"]) if e["why"] else "",
            "where": str(e["where"]) if e.get("where") else "",
        })
    return out


def _components_of(graph: GraphDict, sid: str) -> list[tuple[str, str]]:
    """(id, name) of the DIRECT child components of `sid` (its immediate component members — those
    whose `parent` is exactly `sid`, NOT all descendants). Nested components live in `sid`'s child
    subsystems and are drawn one level down, on those subsystems' own cards. For a leaf subsystem
    (no child subsystems) direct == all, so flat maps are unchanged."""
    return [(cid, str(n["name"])) for cid, n in graph["nodes"].items()
            if str(n["kind"]) == "component" and _parent_of(graph, cid) == sid]


def _child_subsystems(graph: GraphDict, sid: str) -> list[tuple[str, str]]:
    """(id, name) of the DIRECT child subsystems of `sid` — drawn inside its card as collapsed,
    drillable boxes (⌘-click opens the child's own card). Empty for a leaf subsystem."""
    return [(s, str(n["name"])) for s, n in graph["nodes"].items()
            if str(n["kind"]) == "subsystem" and _parent_of(graph, s) == sid]


def _component_subgraph(graph: GraphDict, sid: str, indent: str = "  ",
                        keep: set[str] | None = None) -> list[str]:
    """Mermaid lines framing a subsystem's components as `subgraph <sid>["name"] … end`. Shared by
    the subsystem card and the edge card so a subsystem always reads as a labelled frame (matching
    the base-map subsystem boxes).

    `keep` draws only the members in that set — the EDGE card passes the boxes its crossing arrows
    actually touch, since a box at neither end of that arrow is not part of what the arrow stands for.
    `None` (the subsystem card) draws every member: there the frame IS the subject, so a member with no
    wiring is still one of the parts it is made of."""
    shown = (lambda cid: keep is None or cid in keep)
    out = [f'{indent}subgraph {sid}["{_safe_label(str(graph["nodes"][sid]["name"]))}"]']
    # EVERY BOX IS AN ITEM BOX, as on a use case map: a component tight (a glyph, its name, its kind said
    # by the colour), a nested child subsystem compact (dashed, its component count in the band). The
    # slot node draws no shape of its own; the viewer swaps the box in (see gen_flow_map_mermaid).
    for cid, _ in _components_of(graph, sid):
        if not shown(cid):
            continue
        out.append(f'{indent}  {cid}["{_slot("component", "tight", cid)}"]:::cy-{cid}')
        out.append(f"{indent}  class {cid} itembox")
    for ssid, _ in _child_subsystems(graph, sid):  # nested child subsystems: collapsed item boxes, drillable
        if not shown(ssid):
            continue
        out.append(f'{indent}  {ssid}["{_slot("subsystem", "compact", ssid)}"]:::cy-{ssid}')
        out.append(f"{indent}  class {ssid} itembox")
    out.append(f"{indent}end")
    return out


def gen_subsystem_card_mermaid(graph: GraphDict, sid: str) -> str:
    """Subsystem card: `sid` drawn as a frame around its components (with their internal wiring),
    the deps those components touch drawn outside the frame, AND the subsystem's neighbourhood —
    every other subsystem its components link to/from is drawn as a collapsed box, with one
    arrow per (component, neighbour) pair labelled by the count of underlying edges. A component
    inside the frame points to the neighbour box (outbound) or is pointed at by it (inbound). The
    viewer turns a click on such an arrow into the matching edge card, and a click on a neighbour
    box into that subsystem's own card. When the subsystem's components touch the domain model
    (`C→E` edges), the subdomains they touch are also drawn as collapsed boxes — the bridge between
    the structural and domain groupings, labelled by the count of underlying C→E edges."""
    members = {cid for cid, _ in _components_of(graph, sid)}   # direct component members (drawn nodes)
    deps: set[str] = set()
    neighbours: set[str] = set()
    cross: dict[tuple[str, str], int] = {}       # (drawn-box, neighbour-subsystem box) -> crossing count
    childcross: dict[tuple[str, str], int] = {}  # (box, nested child-subsystem box) -> aggregated count
    bridges: dict[tuple[str, str], int] = {}     # (drawn box, subdomain box) -> underlying C→E edge count
    # Every endpoint is bucketed at THIS card's level: `_child_under` gives the immediate child of `sid`
    # that contains it — the component itself when a direct member, the child-subsystem box when deeper,
    # None when outside sid's subtree. A leaf subsystem has no child boxes, so each bs/bd is the endpoint
    # itself or None — identical to the old `in members` / `_top_subsystem` flat behaviour.
    for e in graph["edges"]:
        s, d = str(e["src"]), str(e["dst"])
        ks, kd = str(graph["nodes"].get(s, {}).get("kind")), str(graph["nodes"].get(d, {}).get("kind"))
        bs, bd = _child_under(graph, s, sid), _child_under(graph, d, sid)
        if kd == "dep":                                  # a DIRECT member's dep (a child's deps live on its own card)
            if bs == s:
                deps.add(d)
            continue
        if ks == "dep":
            if bd == d:
                deps.add(s)
            continue
        if kd == "entity":                               # bridge: a DIRECT member touches a domain entity
            if bs == s:
                sd = _top_subdomain(graph, d)
                if sd:
                    bridges[(s, sd)] = bridges.get((s, sd), 0) + 1
            continue
        if ks == "entity":
            continue
        if bs is not None and bd is not None:            # both inside sid's subtree
            if not (bs == s and bd == d) and bs != bd:   # a child-subsystem box is involved -> aggregated
                childcross[(bs, bd)] = childcross.get((bs, bd), 0) + 1
            continue                                     # two direct members -> labelled (via keep) below
        if bs is not None:                               # outbound crossing to outside sid
            nb = _sibling_level_box(graph, d, sid)
            if nb and nb != sid:
                neighbours.add(nb)
                cross[(bs, nb)] = cross.get((bs, nb), 0) + 1
            continue
        if bd is not None:                               # inbound crossing from outside sid
            nb = _sibling_level_box(graph, s, sid)
            if nb and nb != sid:
                neighbours.add(nb)
                cross[(nb, bd)] = cross.get((nb, bd), 0) + 1
    keep = members | deps  # the set whose internal (labelled) edges are drawn
    # Item-box slots throughout, as on the Data pictures: the slot init drops the engine's node padding
    # so an arrow tip reaches the box it points at (see SLOT_MAP_INIT).
    lines = [SLOT_MAP_INIT, "flowchart TB", *_component_subgraph(graph, sid)]
    for nb in sorted(neighbours):  # collapsed neighbour-subsystem boxes (compact: count in the band)
        lines.append(f'  {nb}["{_slot("subsystem", "compact", nb)}"]:::cy-{nb}')
        lines.append(f"  class {nb} itembox")
    for did in sorted(deps):  # deps belong to no subsystem — draw them outside the frame
        lines.append(f'  {did}["{_slot("dep", "tight", did)}"]:::cy-{did}')
        lines.append(f"  class {did} itembox")
    bridge_sd = {sd for (_, sd) in bridges}
    for sd in sorted(bridge_sd):  # collapsed subdomain boxes the subsystem's data bridges to
        lines.append(f'  {sd}["{_slot("subdomain", "compact", sd)}"]:::cy-{sd}')
        lines.append(f"  class {sd} itembox")
    for src, verb, dst in _diagram_edges(graph, keep):  # internal + dep edges (labelled)
        lines.append(f"  {src} -->|{_edge_label(verb)}| {dst}")
    for (src, dst), c in sorted(cross.items()):  # neighbourhood arrows (click -> edge card)
        lines.append(f"  {src} -->{_count_label(c)} {dst}")
    for (src, dst), c in sorted(childcross.items()):  # nested child-subsystem arrows (aggregated; box drills in)
        lines.append(f"  {src} -->{_count_label(c)} {dst}")
    for (src, sd), c in sorted(bridges.items()):  # bridge arrows: member -> subdomain (underlying edge count)
        lines.append(f"  {src} -->{_count_label(c)} {sd}")
    lines.append(ITEM_SLOT_CLASSDEF)
    return "\n".join(lines)


def subsystem_component_mermaids(graph: GraphDict) -> dict[str, str]:
    """One subsystem-card diagram per subsystem at EVERY level (see gen_subsystem_card_mermaid), so a
    nested child subsystem has its own card to drill into. The viewer keys these by id, so a ⌘-click on
    any subsystem box — top-level box in the overview or a child box inside a card — finds its card."""
    return {nid: gen_subsystem_card_mermaid(graph, nid)
            for nid, node in graph["nodes"].items()
            if str(node["kind"]) == "subsystem"}


def gen_edge_card_mermaid(graph: GraphDict, a: str, b: str) -> str:
    """Edge card: disjoint subsystems `a` and `b` as two frames holding their IMMEDIATE children
    (components + child-subsystem boxes), drawn with the a->b crossings between them PLUS each frame's
    own internal component wiring. A crossing between two DIRECT members keeps its `src -->|verb| dst`
    so the viewer's edge bridge resolves it to the real component edge; a crossing reaching into a child
    subsystem is an aggregated box arrow. Deps and other-subsystem edges are omitted, and only the a->b
    direction is drawn (the b->a arrow has its own card)."""
    direct: list[tuple[str, str, str]] = []
    agg: dict[tuple[str, str], int] = {}
    for e in graph["edges"]:  # the a->b crossings, bucketed to each frame's immediate children
        s, d = str(e["src"]), str(e["dst"])
        if not (_in_subtree(graph, s, a) and _in_subtree(graph, d, b)):
            continue
        ba, bb = str(_child_under(graph, s, a)), str(_child_under(graph, d, b))
        if ba == s and bb == d:                      # both direct members -> labelled (resolves to the edge)
            direct.append((s, str(e["verb"]), d))
        else:                                        # reaches into a child subsystem -> aggregated box arrow
            agg[(ba, bb)] = agg.get((ba, bb), 0) + 1
    # ONLY THE BOXES A CROSSING ARROW TOUCHES. The card's whole question is "what does this arrow stand
    # for", and a box at neither end of any crossing is not part of the answer — it stood there saying
    # nothing, and the page had to be read around it. Measured over three maps: 493 of these cards drew
    # 6713 boxes between them, and 5007 of those 6713 (75%) touched no crossing arrow at all; every one of
    # the 493 cards had at least one.
    #
    # Each frame always keeps at least one box, since every crossing has one end in each frame and a card
    # exists only where there is a crossing. Inner wiring survives when BOTH its ends do: it is real
    # information about boxes that are on the page, and dropping it would hide how a crossing carries on.
    drawn = ({s for s, _, _ in direct} | {d for _, _, d in direct}
             | {box for pair in agg for box in pair})
    members_a = {cid for cid, _ in _components_of(graph, a)} & drawn
    members_b = {cid for cid, _ in _components_of(graph, b)} & drawn
    lines = [SLOT_MAP_INIT, "flowchart LR",  # item-box slots: no node padding, arrows stop on the boxes
             *_component_subgraph(graph, a, keep=drawn),
             *_component_subgraph(graph, b, keep=drawn)]
    for src, verb, dst in _diagram_edges(graph, members_a):  # a's inner links, between drawn boxes
        lines.append(f"  {src} -->|{_edge_label(verb)}| {dst}")
    for src, verb, dst in _diagram_edges(graph, members_b):  # b's inner links, between drawn boxes
        lines.append(f"  {src} -->|{_edge_label(verb)}| {dst}")
    for s, verb, d in direct:
        lines.append(f"  {s} -->|{_edge_label(verb)}| {d}")
    for (src, dst), c in sorted(agg.items()):
        lines.append(f"  {src} -->{_count_label(c)} {dst}")
    lines.append(ITEM_SLOT_CLASSDEF)
    return "\n".join(lines)


def edge_card_mermaids(graph: GraphDict) -> dict[str, str]:
    """One edge-card diagram per disjoint subsystem pair with a crossing component edge — at every drill
    level, not only top-level — keyed 'A>B' to match the rendered arrow's endpoints (overview or nested
    card). Built from the one _edge_card_pairs source."""
    return {f"{a}>{b}": gen_edge_card_mermaid(graph, a, b) for (a, b) in sorted(_edge_card_pairs(graph))}


def _field_ci(node: dict[str, Any], key: str) -> str:
    """A node field looked up case-insensitively (table headers vary in case)."""
    for k, v in cast("dict[str, object]", node.get("fields") or {}).items():
        if k.strip().lower() == key:
            return str(v)
    return ""


def _dep_kind(node: dict[str, Any]) -> str:
    """A dep node's Context Kind, defaulting to 'library' (folds) when unset."""
    return str(node.get("dep_kind") or "library")


def _dep_bucket(node: dict[str, Any]) -> str:
    """A dep node's purpose bucket via the shared resolver: the authored `Bucket` field or the
    heuristic fallback. `is_library` follows the dep's Kind so the fallback draws from the right seed
    family and a folded dep never lands in an external bucket (or vice-versa)."""
    is_lib = _dep_kind(node) in DEP_KINDS_FOLDED
    return resolve_bucket(is_lib, _field_ci(node, "bucket"),
                          _field_ci(node, "type"), _field_ci(node, "used for"))


def folded_libs(graph: GraphDict) -> list[dict[str, str]]:
    """(id, name, type, used_for, bucket) for the deps folded into the Context 'Libraries' box — those
    whose Kind is an in-process one (framework / library). The C4 Context view shows external SYSTEMS
    by name and collapses these, since libraries are an implementation concern, not a system the
    project talks to; `bucket` groups them once the box is drilled."""
    out: list[dict[str, str]] = []
    for nid, node in graph["nodes"].items():
        if str(node["kind"]) == "dep" and _dep_kind(node) in DEP_KINDS_FOLDED:
            out.append({"id": nid, "name": str(node["name"]), "type": _field_ci(node, "type"),
                        "used_for": _field_ci(node, "used for"), "bucket": _dep_bucket(node)})
    return out


def _dep_caption(used_for: str) -> str:
    """A short caption drawn under a dep box's name — the LEAD of its 'Used for', link-stripped, cut at
    the first clause and capped, so a box reads 'Scrapfly / scraping' instead of a full sentence. Empty
    'Used for' → no caption (the name stands alone)."""
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", used_for or "")     # md link -> its text
    s = re.split(r"[.;(]| — |, ", s.strip())[0]                     # first clause only
    s = s.replace('"', "'").replace("`", "").replace("[", "(").replace("]", ")")
    s = s.replace("<", "(").replace(">", ")")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= 32:
        return s
    cut = s[:32].rsplit(" ", 1)[0].strip(" -/·")   # trim back to a word boundary
    return (cut or s[:32]) + "…"


def _dep_view(nid: str, node: dict[str, Any]) -> dict[str, str]:
    """The fields the grouped Context/Libraries diagrams need per dep: id, name, its short caption
    source, and its (resolved) purpose bucket."""
    return {"id": nid, "name": str(node["name"]),
            "used_for": _field_ci(node, "used for"), "bucket": _dep_bucket(node)}


def _context_dep_groups(deps: list[dict[str, str]], is_library: bool) -> list[str]:
    """Mermaid lines drawing `deps` grouped into one labelled subgraph per PURPOSE bucket (in seed
    order), each dep a cylinder captioned by the lead of its 'Used for', plus an UNLABELLED `SYS -->
    dep` arrow (the direction already says 'uses'; the repeated word was pure noise). Shared by the
    Context view (external systems) and the Libraries drill (folded in-process code) — the ONE grouping
    implementation, so both diagrams read identically. Cluster ids are `CYBK<i>` (presentational
    frames, not graph nodes) — the viewer tints them via that prefix."""
    open_b, close_b = SHAPE["dep"]
    by_bucket: dict[str, list[dict[str, str]]] = {}
    for d in deps:
        by_bucket.setdefault(canonical_bucket(d["bucket"]), []).append(d)
    lines: list[str] = []
    for i, bucket in enumerate(order_buckets(by_bucket.keys(), is_library)):
        lines.append(f'  subgraph CYBK{i}["{_safe_label(bucket)}"]')
        for d in by_bucket[bucket]:
            cap = _dep_caption(d["used_for"])
            label = _safe_label(d["name"]) + (f"<br/>{cap}" if cap else "")
            lines.append(f'    {d["id"]}{open_b}{label}{close_b}:::cy-{d["id"]}')
            lines.append(f'    class {d["id"]} dep')
        lines.append("  end")
    for d in deps:
        lines.append(f'  SYS --> {d["id"]}')
    return lines


def _context_head(graph: GraphDict) -> list[str]:
    """The System node + actor lifelines — the part of the Context view shared with its drill-downs."""
    title = _safe_label(graph["title"] or "System")
    # LR (not TB): with every dep hanging off SYS at the same rank, TB spreads them across ONE very wide
    # row (unreadable at ~45 deps); LR stacks them into a narrow, tall column of bucket clusters instead.
    lines = ["flowchart LR", f'  SYS["{title}"]:::cy-SYS', "  class SYS system"]
    for i, r in enumerate(graph["roles"]):
        rid = _actor_id(i)
        label = _safe_label(str(r["name"]))
        # AN AI AGENT TAKES THE PERSON'S SHAPE, not the hexagon, and the viewer re-paths it into a bot
        # figure (`botFigureNode`) the same way it re-paths a person into a stick figure. It needs the
        # same blank first label line, for the same reason: that blank line IS the room the figure is
        # drawn in, and without it the figure lands on top of the name.
        if str(r["kind"]).strip().lower() == "ai-agent":
            lines.append(f'  {rid}([" <br/>{label}"]):::cy-{rid}')
            lines.append(f"  class {rid} agent")
        elif grammar.is_machine_role(str(r["kind"])):   # every other program
            lines.append(f'  {rid}{{{{"{label}"}}}}:::cy-{rid}')   # hexagon = a program
            lines.append(f"  class {rid} svc")
        else:
            # Stick figure = human actor, the same figure the sequence views draw — but a flowchart has
            # no such shape, so the viewer redraws this node's outline as one (`stickFigureNode`). The
            # BLANK FIRST LINE is what makes room for it: the name then sits on the second line, and
            # dagre allocates the taller box, so the figure can never be clipped at the diagram's edge
            # or overlap the actor above. `<br/>` is deliberately outside `_safe_label` (which
            # neutralises markup) — the same exception other callers use for an intentional break.
            lines.append(f'  {rid}([" <br/>{label}"]):::cy-{rid}')
            lines.append(f"  class {rid} human")
        lines.append(f"  {rid} --> SYS")                            # direction says 'uses'; no label noise
    return lines


CONTEXT_CLASSDEFS = [
    "  classDef system fill:#1e1b4b,stroke:#312e81,color:#fff;",
    f"  classDef human {ACTOR_HUMAN_STYLE};",
    f"  classDef svc {ACTOR_SVC_STYLE};",
    # An AI agent wears the PROGRAM colour and its own shape: colour says what it is, shape says which.
    f"  classDef agent {ACTOR_SVC_STYLE};",
    f"  classDef dep {DEP_STYLE};",
    # Group CONTAINERS (the Libraries bundle box + folded bucket count boxes) share one look: the same
    # emerald hue as the individual deps/libraries they hold, but a paler fill and a DASHED border — the
    # convention that says "this is a drillable group", not a leaf.
    f"  classDef libs {CONTAINER_STYLE};",
    f"  classDef bucketfold {CONTAINER_STYLE};",
]


def _actor_id(i: int) -> str:
    r"""The VIEW-only id of the Context diagram's actor node for `roles[i]`.

    `ACT<n>`: index-based, and in a PREFIX the model's id grammar does not use, because the plain
    `R<i>` form it replaced COLLIDED with the model's own role ids. Both were `R\d+`, and the two
    numberings disagree by one (`R0` is the model's `R1`), so anything that looked a model role id up
    in the viewer's node map got the NEXT role: a recorded line about the site visitor `R3` rendered
    as the name of the MCP client application. A view-only node must never be able to answer to a
    model element's id.

    NO UNDERSCORE, deliberately, unlike the deployment units' `U_<n>`. Mermaid names a link
    `L_<src>_<dst>_<n>`, so an underscored endpoint is ambiguous to split, and `eachEdge` pays for
    `U_<n>` by enumerating it in its pattern as "the only ids carrying an underscore". `R_0` was the
    first spelling tried here and it silently unbound the actor→system arrows: `L_R_0_SYS_0` matched
    nothing, so the Context view's actor edge cards stopped opening. An underscore-free id needs no
    pattern to know about it."""
    return f"ACT{i}"


def _external_buckets(graph: GraphDict) -> dict[str, list[dict[str, str]]]:
    """Shown external deps (kinds NOT folded into Libraries) grouped by canonical purpose bucket."""
    by: dict[str, list[dict[str, str]]] = {}
    for nid, node in graph["nodes"].items():
        if str(node["kind"]) == "dep" and _dep_kind(node) not in DEP_KINDS_FOLDED:
            d = _dep_view(nid, node)
            by.setdefault(canonical_bucket(d["bucket"]), []).append(d)
    return by


def _library_buckets(graph: GraphDict) -> dict[str, list[dict[str, str]]]:
    """Folded in-process deps (the Libraries drill's contents) grouped by canonical purpose bucket."""
    by: dict[str, list[dict[str, str]]] = {}
    for d in folded_libs(graph):
        by.setdefault(canonical_bucket(d["bucket"]), []).append(d)
    return by


def _folds(by: dict[str, list[dict[str, str]]], is_library: bool, prefix: str,
           all_or_nothing: bool) -> list[dict[str, Any]]:
    """The buckets that collapse into a drillable count box, in diagram order (seed-first). A bucket
    reaching DEP_BUCKET_FOLD_AT members is 'big'. `all_or_nothing` (the Context view): if ANY bucket is
    big, EVERY bucket folds so the top altitude reads uniformly — no mix of inline clusters and count
    boxes. Not all-or-nothing (the Libraries drill): fold ONLY the big buckets and leave small ones
    inline, so a one-library bucket never becomes a pointless count box. Each fold is
    {id: '<prefix><i>', name, members, is_library} — the ONE source every consumer (count box, drill
    diagram, synthetic node, context edge, roster) derives from, so the ids stay consistent."""
    ordered = order_buckets(by.keys(), is_library)
    if not any(len(by[b]) >= DEP_BUCKET_FOLD_AT for b in ordered):
        return []
    chosen = ordered if all_or_nothing else [b for b in ordered if len(by[b]) >= DEP_BUCKET_FOLD_AT]
    return [{"id": f"{prefix}{i}", "name": b, "members": by[b], "is_library": is_library}
            for i, b in enumerate(chosen)]


def folded_context_buckets(graph: GraphDict) -> list[dict[str, Any]]:
    """The external-system buckets folded into count boxes in the Context view (`BKF<i>`), or []. The
    top altitude folds ALL-OR-NOTHING for a uniform look."""
    return _folds(_external_buckets(graph), is_library=False, prefix="BKF", all_or_nothing=True)


def folded_library_buckets(graph: GraphDict) -> list[dict[str, Any]]:
    """The in-process buckets folded into count boxes in the Libraries drill (`LBKF<i>`), or []. The
    drill folds PARTIALLY — only big buckets fold; small ones stay inline (libraries are excluded from
    the Context view's all-or-nothing consistency rule)."""
    return _folds(_library_buckets(graph), is_library=True, prefix="LBKF", all_or_nothing=False)


def all_folded_buckets(graph: GraphDict) -> list[dict[str, Any]]:
    """Every folded bucket across both diagrams (external Context buckets + library-drill buckets) — the
    synthetic nodes / drill diagrams / context edges / roster all range over this."""
    return folded_context_buckets(graph) + folded_library_buckets(graph)


def _fold_box_lines(fb: dict[str, Any]) -> list[str]:
    """The count box for a folded bucket: `<id>["<name> (N)"]` classed as a container, arrowed from SYS.
    No icon — the dashed container border already signals a drillable group."""
    return [f'  {fb["id"]}["{_safe_label(fb["name"])} ({len(fb["members"])})"]:::cy-{fb["id"]}',
            f'  class {fb["id"]} bucketfold',
            f'  SYS --> {fb["id"]}']


def gen_context_mermaid(graph: GraphDict) -> str:
    """C4 Context: the system as one node, actors (Roles) using it, and the EXTERNAL SYSTEMS it relies
    on — GROUPED by purpose bucket. On a small map every bucket is an inline labelled cluster; once ANY
    bucket is big enough to fold (>= DEP_BUCKET_FOLD_AT), ALL of them collapse into uniform drillable
    count boxes so an integration-heavy map stays legible. In-process deps (framework / library) still
    fold into one `Libraries (N)` box."""
    lines = _context_head(graph)
    by = _external_buckets(graph)
    folded = folded_context_buckets(graph)
    if folded:
        for fb in folded:
            lines += _fold_box_lines(fb)
    else:
        lines += _context_dep_groups([d for b in order_buckets(by.keys(), is_library=False) for d in by[b]],
                                     is_library=False)
    n_folded = len(folded_libs(graph))
    if n_folded:
        lines.append(f'  {LIBS_ID}["Libraries ({n_folded})"]:::cy-{LIBS_ID}')
        lines.append(f"  class {LIBS_ID} libs")
        lines.append(f"  SYS -->|bundles| {LIBS_ID}")
    lines += CONTEXT_CLASSDEFS
    return "\n".join(lines)


def mermaid_by_bucketfold(graph: GraphDict) -> dict[str, str]:
    """The drill diagram for each folded bucket — external (`BKF<i>`) AND library (`LBKF<i>`): the System
    + that ONE bucket's members drawn by name, same shape as its parent view. Reached by drilling the
    count box."""
    out: dict[str, str] = {}
    for fb in all_folded_buckets(graph):
        lines = _context_head(graph)
        lines += _context_dep_groups(fb["members"], is_library=fb["is_library"])
        lines += CONTEXT_CLASSDEFS
        out[fb["id"]] = "\n".join(lines)
    return out


def folded_buckets_roster(graph: GraphDict) -> list[dict[str, Any]]:
    """The folded-bucket roster the viewer carries (count-box preview panel + member routing + which
    parent view a bucket drills out of): [{id, name, count, parent, members: [{id, name}]}]. `parent` is
    'libs' for a library bucket (it drills out of the Libraries view), else 'context'."""
    return [{"id": fb["id"], "name": fb["name"], "count": len(fb["members"]),
             "parent": "libs" if fb["is_library"] else "context",
             "members": [{"id": m["id"], "name": m["name"]} for m in fb["members"]]}
            for fb in all_folded_buckets(graph)]


def gen_libs_mermaid(graph: GraphDict) -> str:
    """The Libraries drill-down (reached by drilling the Context 'Libraries' box): the System + every
    folded in-process dep, GROUPED by purpose bucket. Like the Context view: small → inline clusters;
    once any library bucket is big enough, ALL fold into drillable count boxes (each drills to its
    members). Empty string when nothing is folded into Libraries (the box — hence this view — never
    appears)."""
    libs = folded_libs(graph)
    if not libs:
        return ""
    lines = _context_head(graph)
    by = _library_buckets(graph)
    folded = folded_library_buckets(graph)
    folded_names = {fb["name"] for fb in folded}                        # big buckets → count boxes; the rest stay inline
    inline = [d for b in order_buckets(by.keys(), is_library=True) if b not in folded_names for d in by[b]]
    lines += _context_dep_groups(inline, is_library=True)
    for fb in folded:
        lines += _fold_box_lines(fb)
    lines += CONTEXT_CLASSDEFS
    return "\n".join(lines)


def add_context_nodes(g: dict[str, Any], graph: GraphDict) -> None:
    """Synthetic System + actor nodes in the panel graph so the click bridge resolves them."""
    g["nodes"]["SYS"] = {"id": "SYS", "kind": "system", "name": graph["title"] or "System",
                         "file": None, "line": None,
                         "fields": {"Overview": graph["goal"]} if graph.get("goal") else {}}
    for i, r in enumerate(graph["roles"]):
        rid = _actor_id(i)
        # `audience` rides on the NODE, not only on graph.roles: an actor card is drawn from the node
        # alone, and joining role-by-name in the browser would be the second implementation of a join
        # this project keeps paying for. Derived once, here.
        g["nodes"][rid] = {"id": rid, "kind": r["kind"], "name": r["name"], "file": None, "line": None,
                           "audience": r.get("audience") or "",
                           "fields": ({"Wants": r["wants"]} if r["wants"] else {})}
    # The collapsed Libraries box is a synthetic node so bindNodes binds it (it skips ids absent from
    # the graph) and the click bridge resolves it; its panel/tooltip are driven by FOLDED_LIBS, not fields.
    if folded_libs(graph):
        g["nodes"][LIBS_ID] = {"id": LIBS_ID, "kind": "libs", "name": "Libraries",
                               "file": None, "line": None, "fields": {}}
    # Each folded bucket (external AND library) is a synthetic node too (same reason as LIBS): so
    # bindNodes binds its count box and the click bridge resolves it; panel/tooltip come from the roster.
    for fb in all_folded_buckets(graph):
        g["nodes"][fb["id"]] = {"id": fb["id"], "kind": "bucketfold", "name": fb["name"],
                                "file": None, "line": None, "fields": {}}


# ── Deployment view (processes/threads ↔ subsystems) ──────────────────────────────────────────────
# A process is NOT a model element (it stays a `deployment[]` table row); it is a VIEW-only graph node,
# injected like SYS/roles so the viewer's binders (which skip ids absent from GRAPH.nodes) resolve it.
# Ids are INDEX-based `U_<n>` — never a name slug, which could collide for two units differing only in
# punctuation (mermaid silently merges same-id nodes). The `runs` edges are DERIVED (process → the
# subsystem of each component whose `runs_in` names the unit), never authored in `edges[]`.
_INFRA_DEP_KINDS = ("messaging", "datastore", "service")


def _deployment_unit_ids(graph: GraphDict) -> list[tuple[str, str]]:
    """`[(U_<n>, unit_name)]` for each deployment unit — one shared index→id mapping used by BOTH the
    node injection and the generators, so their ids always agree."""
    return [(f"U_{i}", str(r.get("unit", ""))) for i, r in enumerate(graph["deployment"])]


def has_deployment(graph: GraphDict) -> bool:
    return bool(graph["deployment"])


def _node_runs_in(node: object) -> list[str]:
    """A graph node's `runs_in` as a `list[str]` (components only carry it; missing → [])."""
    v = node.get("runs_in") if isinstance(node, dict) else None
    return [str(x) for x in v] if isinstance(v, list) else []


def _entry_point_runs_in(ep: object) -> list[str]:
    """An entry point's `runs_in` — the precise host unit(s) of a self-started thread (its component may
    run in several). Carried in the graph's flat `entry_points` list (from EntryPoint.runs_in)."""
    v = ep.get("runs_in") if isinstance(ep, dict) else None
    return [str(x) for x in v] if isinstance(v, list) else []


def _process_unit_names(graph: GraphDict) -> set[str]:
    """The deployment units that are real PROCESSES: a unit hosting ≥1 component OR ≥1 entry point via
    `runs_in` (B2 — a worker whose component runs in several units is tagged only at the entry-point
    level; counting components alone would drop that real process). A unit hosting neither is
    infrastructure the app talks to (mongo/redis/nginx), not a code-running process."""
    hosts: set[str] = set()
    for node in graph["nodes"].values():
        if isinstance(node, dict) and str(node.get("kind")) == "component":
            hosts.update(_node_runs_in(node))
    for ep in graph.get("entry_points", []):
        hosts.update(_entry_point_runs_in(ep))
    return {u for u in hosts if u}


def _system_dep_names(graph: GraphDict) -> list[str]:
    """The names of every EXTERNAL (system) dependency box — datastore/messaging/service/platform. A
    no-host deployment unit whose name matches one of these IS that dep's box, not a real process."""
    return [str(node.get("name", "")) for node in graph["nodes"].values()
            if isinstance(node, dict) and str(node.get("kind")) == "dep"
            and node.get("dep_kind") in DEP_KINDS_SYSTEM]


def _unit_matches_system_dep(unit: str, dep_names: list[str]) -> bool:
    """The no-host unit `unit` name-matches a drawn system-dep box (so it needs no process/untraced box)."""
    return any(unit_name_matches_dep(unit, dn) for dn in dep_names)


def _unit_fields(r: dict[str, object]) -> dict[str, str]:
    """A deployment row's operational facts as pane fields — the columns the System tab used to table."""
    return {k: str(v) for k, v in (("Runs on", r.get("runs_on")),
                                   ("Exposed as", r.get("exposed_as")),
                                   ("Config source", r.get("config_source"))) if v}


def add_deployment_nodes(g: dict[str, Any], graph: GraphDict) -> None:
    """Inject one view-only `process` node per deployment unit the view DRAWS a box for, so each binds +
    drills + shows a panel carrying that unit's operational facts (its `runs_on` / `exposed_as` /
    `config_source` / `variants` — the pane is their only home now that the System tab no longer tables
    them). Two kinds of unit get a node: one that HOSTS code (`_process_unit_names`), and one that hosts
    nothing yet matches no system dep — the "Untraced units" lane draws that box too, and a drawn box
    that cannot be selected breaks the every-box-binds rule.

    Infrastructure units (mongo/redis/nginx — no `runs_in` points at them, and their name matches a
    system dep) still get NO process node: they are already the dep box the running components point at,
    so a process box would be a dead, arrow-less duplicate. `annotate_unit_dep_facts` puts their facts on
    that dep box instead, so nothing is lost. `_deployment_unit_ids` stays complete (the shared index→id
    map); the skip is HERE, at the usage site (S1). `unit` carries the raw name for the reverse lookup."""
    process_units = _process_unit_names(graph)
    dep_names = _system_dep_names(graph)
    for uid, unit in _deployment_unit_ids(graph):
        if unit not in process_units and _unit_matches_system_dep(unit, dep_names):
            continue
        r = graph["deployment"][int(uid[2:])]
        g["nodes"][uid] = {"id": uid, "kind": "process", "name": unit or uid,
                           "file": None, "line": None, "fields": _unit_fields(r), "unit": unit,
                           "variants": r.get("variants") or []}


def annotate_unit_dep_facts(g: dict[str, Any], graph: GraphDict) -> None:
    """Copy an INFRASTRUCTURE unit's operational facts onto the dependency box that represents it.

    A unit like `mongo` hosts no code, so it gets no process box — it IS the Mongo dep box the running
    components point at. Its `runs_on` / `exposed_as` / `config_source` / `variants` would otherwise have
    no home at all once the System tab stops tabling `deployment[]`. Authored dep fields win on a key
    clash: the dep's own text is about the dependency, the unit's is about how it is deployed here."""
    dep_names = _system_dep_names(graph)
    process_units = _process_unit_names(graph)
    by_name = {str(n.get("name", "")): nid for nid, n in graph["nodes"].items()
               if str(n.get("kind")) == "dep" and n.get("dep_kind") in DEP_KINDS_SYSTEM}
    for uid, unit in _deployment_unit_ids(graph):
        if unit in process_units or not _unit_matches_system_dep(unit, dep_names):
            continue
        did = next((nid for name, nid in by_name.items() if unit_name_matches_dep(unit, name)), None)
        node = g["nodes"].get(did) if did else None
        if not isinstance(node, dict):
            continue
        r = graph["deployment"][int(uid[2:])]
        fields = node.setdefault("fields", {})
        for k, v in _unit_fields(r).items():
            fields.setdefault(k, v)
        if r.get("variants") and not node.get("variants"):
            node["variants"] = r.get("variants")
        # The unit NAME on the dep node, so search can still find `mongo` when the dep is `MongoDB`.
        # `kind` stays `dep`, so nothing that keys off `process` picks this up.
        node["unit"] = unit


def annotate_run_by(g: dict[str, Any], graph: GraphDict) -> None:
    """Annotate every box that the Deployment view's `runs` edges point at — a top subsystem, or an
    ungrouped component — plus each component itself, with the PROCESS UNITS that run it (`node.run_by`).

    This is where "where does this code actually run" gets answered for a SUBSYSTEM. The overview draws
    one aggregate `runs` arrow (the per-process fan would be ~22 arrows on a map MEE6's size), so the
    placement lives in the info pane instead of on the canvas: select a subsystem, read the processes,
    click one to open its card. Derived from the one `_deployment_edges` source, so the pane and the
    diagram can never disagree. Units are filtered to real PROCESS units (B2): a name that hosts no code
    has no card to open, exactly as the diagram draws no box for it."""
    units = _deployment_unit_ids(graph)
    uid_of = {unit: uid for uid, unit in units}
    name_of = dict(units)
    # `_process_unit_names` is every name some `runs_in` mentions — which may include a unit with NO
    # `deployment[]` row. Such a name has no process box and no card, so intersect with the declared
    # units: the pane must not offer a link that opens nothing.
    hosted = {u for u in _process_unit_names(graph) if u in uid_of}
    runs, _infra, _boxes = _deployment_edges(graph, uid_of)
    by_box: dict[str, set[str]] = {}
    for uid, box in runs:
        unit = name_of.get(uid, "")
        if unit in hosted:
            by_box.setdefault(box, set()).add(unit)
    # A component states its OWN hosts, so a leaf answers the question without climbing to its subsystem.
    for nid, node in graph["nodes"].items():
        if str(node.get("kind")) == "component":
            own = {u for u in _node_runs_in(node) if u in hosted}
            if own:
                by_box.setdefault(nid, set()).update(own)
    for box, hosts in by_box.items():
        node = g["nodes"].get(box)
        if not isinstance(node, dict):
            continue
        node["run_by"] = sorted(hosts)
        # A component already carries an authored "Runs in" TEXT field saying the same thing. Keeping
        # both would print the unit twice under two different labels; the annotated row supersedes it
        # because it links to each process's card. Dropped only when we actually replace it — a
        # `runs_in` naming no real unit yields no `run_by`, and there the authored text is all there is.
        fields = node.get("fields")
        if isinstance(fields, dict):
            fields.pop("Runs in", None)


def _subsystem_box_of(graph: GraphDict, cid: str) -> str:
    """The box a component `runs` edge points at: its top subsystem, or the component itself when it is
    ungrouped (still a real node, so it binds)."""
    return _top_subsystem(graph, cid) or cid


def _infra_band_of(graph: GraphDict, did: str) -> str:
    """The Infrastructure role-band an infra dep box belongs to (one of `_INFRA_BANDS`' roles). Prefer
    the dep's DERIVED role set (WS2 `grammar.dep_roles` on the node, from its incoming C→D verbs), in
    the fixed priority messaging > datastore > service > security so a dual-role dep (Redis = bus +
    store) lands in one band deterministically. Fall back to the structural `dep_kind` when the dep has
    no verb-derived role (a roleless C→D edge, or infra wired at deployment level only), then to
    'other' (slate) so a box is never bandless."""
    node = graph["nodes"].get(did, {})
    roles = node.get("roles") if isinstance(node, dict) else None
    role_set = {str(r) for r in roles} if isinstance(roles, list) else set()
    for role, _bid, _title, _cls in _INFRA_BANDS:
        if role != "other" and role in role_set:
            return role
    dep_kind = str(node.get("dep_kind") or "") if isinstance(node, dict) else ""
    if dep_kind in ("messaging", "datastore", "service"):
        return dep_kind
    return "other"


def _declare_box(graph: GraphDict, nid: str, default_kind: str) -> list[str]:
    """The two mermaid lines declaring a node box (`id["label"]:::cy-id` + `class id kind`), so an
    endpoint that would otherwise render as a bare inert node binds with the right colour."""
    node = graph["nodes"].get(nid, {})
    name = str(node.get("name", nid))
    kind = str(node.get("kind") or default_kind)
    shape = SHAPE.get(kind, ('["', '"]'))
    cls = kind if kind in ("subsystem", "component", "infra", "dep", "process") else "subsystem"
    return [f'  {nid}{shape[0]}{_safe_label(name)}{shape[1]}:::cy-{nid}', f"  class {nid} {cls}"]


def _infra_call_sites(graph: GraphDict, uid_of: dict[str, str]
                      ) -> dict[tuple[str, str], list[dict[str, str]]]:
    """`{(process_uid, infra_dep_id): [the component→dep calls behind that arrow]}` — the ONE derivation
    of process→infra, so the arrows drawn and the calls listed when one is selected can never disagree
    (`_deployment_edges` takes its `infra` set straight from these keys).

    A process reaches a broker/store/service through the components it runs, so each arrow stands for
    one or more real call sites. Rows carry the endpoint NAMES, the verb, the why and the bare
    `path:line` anchor — the same shape `gen_container_edges` uses, so the viewer renders both with the
    same panel idiom."""
    out: dict[tuple[str, str], list[dict[str, str]]] = {}
    for e in graph["edges"]:
        did, cid = str(e["dst"]), str(e["src"])
        dn, cn = graph["nodes"].get(did), graph["nodes"].get(cid)
        if not dn or str(dn.get("kind")) != "dep" or dn.get("dep_kind") not in _INFRA_DEP_KINDS:
            continue
        if not cn or str(cn.get("kind")) != "component":
            continue
        # Same rule as the process→process derivation: `extends`/`implements` describe the shape of
        # the code, not runtime traffic, so they cannot evidence a process reaching infrastructure.
        # Latent today (the only structural C→D edges on live maps point at deps classified
        # `library`, which never enter this lane) — but the filter belongs with the claim, not with
        # the accident that no map has tripped it yet.
        if str(e.get("verb") or "") in ("extends", "implements"):
            continue
        row = {"src": cid, "dst": did,
               "srcName": str(cn.get("name") or cid), "dstName": str(dn.get("name") or did),
               "verb": str(e.get("verb") or ""), "why": str(e.get("why") or ""),
               "where": str(e.get("where") or "")}
        for unit in _node_runs_in(cn):
            uid = uid_of.get(str(unit))
            if uid:
                out.setdefault((uid, did), []).append(row)
    return out


def _deployment_edges(graph: GraphDict, uid_of: dict[str, str]
                      ) -> tuple[set[tuple[str, str]], set[tuple[str, str]], dict[str, set[str]]]:
    """Derive the Deployment view's edges: `runs` (process → the subsystem/ungrouped-component of each
    component it runs) and `infra` (process → a broker/store dep a running component touches, straight
    from `_infra_call_sites`). Also returns `boxes_by_uid` (the subsystem boxes each process runs)."""
    runs: set[tuple[str, str]] = set()
    infra: set[tuple[str, str]] = set(_infra_call_sites(graph, uid_of))
    boxes_by_uid: dict[str, set[str]] = {}
    for nid, node in graph["nodes"].items():
        if str(node.get("kind")) != "component":
            continue
        for unit in _node_runs_in(node):
            uid = uid_of.get(str(unit))
            if not uid:
                continue
            box = _subsystem_box_of(graph, nid)
            runs.add((uid, box))
            boxes_by_uid.setdefault(uid, set()).add(box)
    return runs, infra, boxes_by_uid


def _unit_environments(graph: GraphDict) -> dict[str, frozenset[str]]:
    """`{unit: the environment(s) it belongs to}`, from each deployment row's `variants`.

    An EMPTY set means UNGATED — the row's own documented meaning: the unit appears in every
    environment (shared infra, or a map with no variant axis at all)."""
    out: dict[str, frozenset[str]] = {}
    for row in graph["deployment"]:
        unit = str(row.get("unit", ""))
        variants = row.get("variants")
        out[unit] = frozenset(
            str(v.get("env", "")) for v in (variants if isinstance(variants, list) else [])
            if isinstance(v, dict) and v.get("env"))
    return out


def _can_coexist(envs: dict[str, frozenset[str]], a: str, b: str) -> bool:
    """Whether two units can be RUNNING AT THE SAME TIME — i.e. share at least one environment.

    Two units that never coexist cannot talk to each other, so an arrow between them is false
    however the derivation reached it. On a live map `backend` (cloud, dev), `standalone`
    (standalone) and `e2e backend shard` (test) are three deployment SHAPES of one monolith: you run
    one or the other. Every backend component listed all three in `runs_in`, so ONE Redis pub/sub
    channel produced SIX process→process arrows between processes that are never up together.

    The data was already in the map and grounded in real manifest lines (`docker-compose.yml:117`,
    `:96`, the e2e orchestrator) — the views simply were not reading it. An untagged unit is
    ungated and pairs with everything, so a map with no variant axis behaves exactly as before."""
    ea, eb = envs.get(a, frozenset()), envs.get(b, frozenset())
    return not ea or not eb or bool(ea & eb)


def _channel_units(graph: GraphDict, ch: dict[str, object], key: str, hosted: set[str]) -> set[str]:
    """The PROCESS units at one end of an async channel: each component id under `key`
    (`publishers`/`consumers`) resolved through its `runs_in`, keeping only units that actually host
    code (a unit with no host is not drawn as a process box, so an arrow to it would dangle — B1)."""
    ids = ch.get(key)
    return {u for cid in (ids if isinstance(ids, list) else [])
            for u in _node_runs_in(graph["nodes"].get(str(cid))) if u in hosted}


def _channel_process_links(graph: GraphDict, uid_of: dict[str, str], hosted: set[str]
                           ) -> dict[tuple[str, str], list[dict[str, str]]]:
    """`{(publisher_uid, consumer_uid): [channel row…]}` — the process→process topology DERIVED from
    the async catalog, the one thing the Deployment view can say that no other diagram does.

    A channel already names its publishing and consuming COMPONENTS; each component already names the
    unit(s) it `runs_in`. Composing the two turns 'this queue exists' into 'this process feeds that
    process', with the channel as the arrow's evidence. Nothing new is authored.

    Every publisher-unit × consumer-unit pair crosses (a component running in two units really does
    publish from both). A same-unit pair is DROPPED: a process queueing work for itself is a self-loop,
    not topology — its channel is still listed on the unit's own Data-tab broker section.

    DELIBERATELY ASYMMETRIC with `_call_process_links`, which drops a pair whose endpoints share a
    host. That subtraction is right for a SYNCHRONOUS call — co-resident code calls itself in-process
    — but wrong for a channel: a broker decouples publisher from consumer, so a message published in
    `api` is delivered to every consumer of that channel wherever it runs, including a different unit
    that happens to also host the publishing component. The overlap carries no implication of
    in-process delivery, so there is nothing to subtract."""
    out: dict[tuple[str, str], list[dict[str, str]]] = {}
    # A `runs_in` may name a unit that has no `deployment[]` row at all (an unvalidated or mid-edit map
    # — `serve` renders without validating). Such a unit has no id and no box, so drop it HERE rather
    # than letting the id lookup below fail: one bad name must not 500 the whole map.
    known = {u for u in hosted if u in uid_of}
    envs = _unit_environments(graph)
    for ch in graph["messaging"]:
        pubs, cons = _channel_units(graph, ch, "publishers", known), _channel_units(graph, ch, "consumers", known)
        if not pubs or not cons:
            continue
        bid = str(ch.get("broker") or "")
        row = {"name": str(ch.get("name") or ""), "kind": str(ch.get("kind") or ""),
               "broker": bid, "brokerName": str((graph["nodes"].get(bid) or {}).get("name") or bid),
               "source": str(ch.get("source") or "")}
        for p in sorted(pubs):
            for c in sorted(cons):
                # `p != c` drops the self-loop; `_can_coexist` drops the pair that is two shapes of
                # the same process. A broker really does decouple publisher from consumer — which is
                # why this half deliberately does NOT subtract shared hosts the way the call half
                # does — but decoupling only reaches processes that are up at the same time.
                if p != c and _can_coexist(envs, p, c):
                    out.setdefault((uid_of[p], uid_of[c]), []).append(row)
    return out


def _call_process_links(graph: GraphDict, uid_of: dict[str, str], hosted: set[str]
                        ) -> dict[tuple[str, str], list[dict[str, str]]]:
    """`{(caller_uid, callee_uid): [the component→component calls crossing that process boundary]}` —
    the SYNCHRONOUS half of the process topology, composed exactly like the async half: a backbone
    component→component edge whose two ends `runs_in` DIFFERENT units is, by definition, one process
    calling another (a browser bundle calling an HTTP API, a worker calling an id service).

    Without this the view is blank for any ordinary client/server app: its processes talk over HTTP, not
    over a queue, so the async catalog has nothing to say about them. Same-unit pairs are dropped — an
    in-process call is not topology — and units that host no code are skipped (they have no box).

    A CROSSING IS FORCED ONLY FROM A UNIT THAT HOSTS THE CALLER BUT NOT THE CALLEE. A component may
    run in several units (a monolith loads the same module into its api, bot and worker processes).
    Pairing every host of one end with every host of the other then invents arrows — in BOTH
    directions — between processes that never talk: inside the api process the call is api→api, and
    inside the bot process it is bot→bot, yet the cartesian product draws api→bot AND bot→api.
    Measured on a 429-component monolith, 589 of 648 such edges (91%) had a host in common, and the
    heaviest arrows on the overview (`api↔bot` at 511 calls, `api/bot → worker` at 397) were built
    almost entirely from them — one launcher calling the bot runtime at `manage.py:75`, both ends
    running in {api, bot, worker}, produced SIX false network arrows from ONE in-process call.

    So the source side is `src_units - dst_units`: units where the caller runs and the callee does
    NOT, which is exactly where the call has to leave the process. Note this is deliberately not the
    blunter "drop the edge whenever the host sets overlap" — that also erases REAL traffic: a
    frontend tagged {backend, vite-dev-server} calling a backend tagged {backend} still genuinely
    crosses the wire from the dev server, and subtracting keeps that arrow while dropping the
    self-pair."""
    out: dict[tuple[str, str], list[dict[str, str]]] = {}
    known = {u for u in hosted if u in uid_of}
    envs = _unit_environments(graph)
    for e in graph["edges"]:
        sid, did = str(e["src"]), str(e["dst"])
        sn, dn = graph["nodes"].get(sid), graph["nodes"].get(did)
        if not sn or not dn or str(sn.get("kind")) != "component" or str(dn.get("kind")) != "component":
            continue
        # STRUCTURAL verbs are not runtime traffic. `extends`/`implements` describe the shape of the
        # CODE — a subclass does not "call" the process its base class also happens to run in — so
        # they can never evidence a process→process hop. Leaving them in produced exactly that
        # nonsense on a live map: a Bluesky plugin drew calls to eight sibling scrapers purely
        # because it extends a framework class those processes also load.
        if str(e.get("verb") or "") in ("extends", "implements"):
            continue
        src_units = {u for u in _node_runs_in(sn) if u in known}
        dst_units = {u for u in _node_runs_in(dn) if u in known}
        crossing_from = src_units - dst_units       # co-resident hosts force nothing
        if not crossing_from or not dst_units:
            continue
        row = {"src": sid, "dst": did,
               "srcName": str(sn.get("name") or sid), "dstName": str(dn.get("name") or did),
               "verb": str(e.get("verb") or ""), "why": str(e.get("why") or ""),
               "where": str(e.get("where") or "")}
        for a in sorted(crossing_from):
            for b in sorted(dst_units):
                # Same guard as the async half: a call cannot cross into a process that is never up
                # at the same time. Subtracting co-resident hosts is not enough on its own, because
                # two deployment SHAPES of one monolith are not co-resident — they are alternatives.
                if a != b and _can_coexist(envs, a, b):
                    out.setdefault((uid_of[a], uid_of[b]), []).append(row)
    return out


# A deployment overview stays flat until it stops being readable. Below this many process boxes the
# flat list IS the clearest drawing, and a grouping level would add a drill that buys nothing (9, 5
# and 2-process maps all lose by it). Set at the fan-out rule's advisory cap, so grouping switches on
# exactly when `validate` would start complaining about the screen.
DEPLOYMENT_GROUP_MIN = 13
# Coupling points shown on the overview. The "2+ processes" rule bounds the fan on a small map, but on
# a 51-process monolith almost every dep clears it — 68 boxes and 243 arrows, where MongoDB alone drew
# 17. The full inventory is the Dependencies view's job (and the Data view's, for stores); what only
# THIS view answers is which infrastructure couples the MOST processes, so the lane keeps the heaviest
# and says how many it dropped.
INFRA_LANE_MAX = 8
# A container is only worth drawing if it can be NAMED. Processes running one product area ("the 14
# social connectors") make a box a reader understands at a glance; a process running seven is a
# monolith whose identity IS the process, and folding two of them together produced a real box
# labelled "AI & media services + Core platform + Discord bot experience + Discord connectivity +
# Monetization + Social content connectors + Web platform API (2)" — while hiding `api` and `bot`,
# the two processes the reader most wants to see. Above this many product areas the members stay
# individual boxes.
DEPLOYMENT_GROUP_MAX_CAPS = 2


def _unit_product_areas(graph: GraphDict) -> dict[str, frozenset[str]]:
    """`unit name → the top-level subsystems whose components run in that process`.

    The grouping key for the overview. It is SEMANTIC (what the process runs) rather than structural
    (what it connects to), and both halves are already in the model — `runs_in` on the component, the
    component's `subsystem`, and the subsystem parent chain — so no new authoring is needed.

    Grouping by connection signature was the obvious alternative and it measures badly: on a
    51-process monolith, exact same-neighbours grouping yields 46 groups (only 9 units merge at all),
    and the merges it does find are semantically arbitrary — a memberships worker paired with a
    sponsorships worker because they touch the same stores. Relaxing the match to 50% overlap reaches
    30 groups but the groups stop being nameable, a group arrow becomes false for some members, and
    the whole grouping reshuffles whenever one edge is added (which makes every diagram diff
    unreadable). Capability signature gives 12 NAMED groups over the same 51 processes, changes only
    when a component is re-assigned, and matches the method's own product-area-first grouping rule."""
    caps: dict[str, set[str]] = {}
    for nid, node in graph["nodes"].items():
        if str(node.get("kind")) != "component":
            continue
        top = _top_subsystem(graph, str(nid))
        if not top:
            continue
        for unit in _node_runs_in(node):
            caps.setdefault(str(unit), set()).add(top)
    return {u: frozenset(s) for u, s in caps.items()}


def deployment_groups(graph: GraphDict, process_units: set[str]
                      ) -> tuple[dict[str, list[str]], dict[str, str]]:
    """`({group_id: [unit names]}, {unit name: group_id})` — product-area containers for the overview.

    A signature with only ONE process is not a container: it is drawn as the process itself, which is
    why a monolith's `api`/`bot`/`worker` (each running five product areas) stay their own boxes. Empty
    on a map below `DEPLOYMENT_GROUP_MIN`, so small maps render exactly as before."""
    if len(process_units) < DEPLOYMENT_GROUP_MIN:
        return {}, {}
    caps = _unit_product_areas(graph)
    by_sig: dict[frozenset[str], list[str]] = {}
    for unit in sorted(process_units):
        sig = caps.get(unit)
        if sig:
            by_sig.setdefault(sig, []).append(unit)
    groups: dict[str, list[str]] = {}
    group_of: dict[str, str] = {}
    # Deterministic ids: biggest group first, then alphabetically by member list — so a re-render at
    # the same commit produces the same ids and the diagram diffs cleanly.
    ordered = sorted(by_sig.items(), key=lambda kv: (-len(kv[1]), kv[1]))
    for i, (_sig, members) in enumerate(
            (s, m) for s, m in ordered if len(m) >= 2 and len(s) <= DEPLOYMENT_GROUP_MAX_CAPS):
        gid = f"PG_{i}"
        groups[gid] = members
        for u in members:
            group_of[u] = gid
    return groups, group_of


def deployment_group_label(graph: GraphDict, members: list[str]) -> str:
    """A container's display text: the product-area names its processes run, plus the member count."""
    caps = _unit_product_areas(graph)
    sig = caps.get(members[0], frozenset())
    # Names only — an id that leaked into a box label would be meaningless on screen (the same rule
    # the info pane and every other view follow: ids are navigation, never display).
    names = sorted(n for n in (str(graph["nodes"].get(s, {}).get("name") or "") for s in sig) if n)
    return f"{' + '.join(names) or 'Grouped processes'} ({len(members)})"


def _call_edge_label(rows: list[dict[str, str]]) -> str:
    """A synchronous process→process arrow's label: the verb when the pair is one call (`requests` says
    more than `1 call`), else the count."""
    if len(rows) != 1:
        return f"{len(rows)} calls"
    return rows[0]["verb"] or "calls"


def _process_edge_label(chans: list[dict[str, str]], calls: list[dict[str, str]]) -> str:
    """The label for the ONE arrow drawn per ordered process pair. A pair usually talks one way or the
    other; when it does both, the label counts each mechanism rather than picking a winner."""
    if chans and calls:
        n = lambda k, word: f"{k} {word}" + ("" if k == 1 else "s")  # noqa: E731 - local formatting only
        return f"{n(len(chans), 'channel')}, {n(len(calls), 'call')}"
    return _channel_edge_label(chans) if chans else _call_edge_label(calls)


def _channel_edge_label(rows: list[dict[str, str]]) -> str:
    """A process→process arrow's label: the channel's own name when it carries ONE (the useful fact —
    `shard.events` says more than `1 channel`), else the count. Long/templated names are elided to keep
    the arrow from stretching its rank; the full name is always on the arrow's select panel."""
    if len(rows) != 1:
        return f"{len(rows)} channels"
    name = rows[0]["name"]
    return name if len(name) <= 30 else name[:29] + "…"


def _components_run_by_uid(graph: GraphDict, uid_of: dict[str, str]) -> dict[str, set[str]]:
    """`uid → {component ids that run in that process}`. The packaging fingerprint of each process, used
    to spot an all-in-one unit (a superset of every other process's set)."""
    out: dict[str, set[str]] = {}
    for nid, node in graph["nodes"].items():
        if str(node.get("kind")) != "component":
            continue
        for unit in _node_runs_in(node):
            uid = uid_of.get(str(unit))
            if uid:
                out.setdefault(uid, set()).add(nid)
    return out


def _allinone_uids(process_uids: list[str], comps_by_uid: dict[str, set[str]]) -> set[str]:
    """The process units that are ALL-IN-ONE packagings, not peers: a unit whose component set contains
    the union of every OTHER process unit's components (e.g. a `standalone` that runs everything
    `backend` and `frontend` run between them). Such a unit re-runs the whole mesh, so fanning its arrows
    just re-draws every other arrow — the overview folds it to a label instead.
    Guard: never fold so many that no fanned process remains (the all-equal degenerate case, where every
    unit runs the same set — fold nothing so the overview still shows the processes)."""
    if len(process_uids) < 2:
        return set()
    fold: set[str] = set()
    for u in process_uids:
        mine = comps_by_uid.get(u, set())
        if not mine:
            continue
        others: set[str] = set().union(*(comps_by_uid.get(o, set()) for o in process_uids if o != u))
        if others and others <= mine:
            fold.add(u)
    if len(fold) >= len(process_uids):   # would fold every process → keep them all fanned instead
        return set()
    return fold


def _unit_variants(graph: GraphDict) -> dict[str, set[str]]:
    """`{unit_name: {environment…}}` from the deployment rows — a unit's declared variant ENVs. An empty
    set means UNGATED (the unit appears in every environment). Each variant is a `{env, source}` object
    (source = the manifest anchor grounding it, or "" when inferred); only the `env` axis filters the
    view."""
    out: dict[str, set[str]] = {}
    for r in graph["deployment"]:
        raw = r.get("variants")
        variants = raw if isinstance(raw, list) else []
        out[str(r.get("unit", ""))] = {str(v["env"]) for v in variants
                                       if isinstance(v, dict) and v.get("env")}
    return out


def deployment_environments(graph: GraphDict) -> list[str]:
    """The declared deployment-variant names, in order — or [] when the project has no environment axis."""
    return [str(e) for e in graph.get("environments", [])]


def gen_deployment_mermaid(graph: GraphDict) -> str:
    """The Deployment overview: each deployable unit a `process` box and derived `runs` edges to the
    subsystems it executes. Everything drawn is a real (or injected) graph node, so every box binds
    (the B1 rule).

    ONE diagram, whatever environment is selected. Every unit is drawn; the viewer DIMS the boxes and
    arrows the chosen environment excludes (`applyEnvDim`, driven by each node's `variants`) instead of
    dropping them. Filtering here made units silently disappear — the reader could not tell "not
    deployed there" from "not in the map", and every switch relaid the whole diagram out from scratch.

    Four DERIVED readability rules keep the overview from hairballing (kind + `runs_in` + edge verbs +
    the async catalog, no authored input):
      * PROCESS TOPOLOGY — a process→process arrow per async channel one unit publishes and another
        consumes (`_channel_process_links`), labelled with the channel (or a count when several cross
        the same pair). This is the view's own content: which process feeds which, evidenced by a
        catalogued channel. Every other lane restates a diagram the reader already has.
      * RUNTIME ONLY, NO SUBSYSTEMS LANE — the overview draws processes and infrastructure: the things
        that exist at run time. Subsystems are CODE STRUCTURE, and the Subsystems view already draws all
        of them with their real relationships; a lane here showed a subset (only those whose components
        happen to carry `runs_in`) joined by one aggregate `runs` arrow that said no more than "the
        processes run the code". Placement is a property of the code, so it is answered where you ask
        about that code — `annotate_run_by` puts a linked "Runs in" row in the info pane of every
        subsystem and component — and per-process on each unit's drill card, which still draws what it
        runs. A per-process fan here would be ~22 arrows on a map MEE6's size.
      * COUPLING POINTS, NOT A CATALOG — the Infrastructure lane holds only the brokers/stores/services
        used by 2+ processes, each with REAL process→infra arrows. Listing everything the app talks to
        duplicated the Dependencies view (and the Data view, which covers stores far more deeply) while
        silently under-reporting it, since the list is derived from `runs_in` coverage. "Which
        infrastructure couples processes together" is the deployment-specific question, and the 2+ rule
        bounds the fan by construction. Single-process infra stays on that process's card. Boxes stay
        banded by each dep's DERIVED role (`grammar.dep_roles` via `node.roles`): Message bus / Data
        store / Service / Security / Other. A dual-role dep (Redis = bus + store) lands in one band.
      * ALL-IN-ONE annotation — a superset packaging (a `standalone` that runs everything) keeps a
        "… — all-in-one: runs every subsystem" label suffix, so it still reads as "runs the lot" without
        needing a fold or a core/satellite split.

    LAYERED layout: nodes band into subgraph lanes — Processes, then the (nested) Infrastructure role
    bands, then any Untraced units — so dagre stacks them into readable rows."""
    units = _deployment_unit_ids(graph)
    uid_of = {unit: uid for uid, unit in units}
    runs, infra, _boxes_by_uid = _deployment_edges(graph, uid_of)
    # Only units that HOST code are process boxes (B2). A no-host unit is either an infra dep already
    # drawn in the Infrastructure lane (name-match → drawn NOWHERE) or a genuinely-unlinked unit (a real
    # gap → the small "Untraced units" lane, so it is never dropped silently — S2).
    process_units = _process_unit_names(graph)
    dep_names = _system_dep_names(graph)
    process_uids = [uid for uid, name in units if name in process_units]
    untraced = [uid for uid, name in units
                if name not in process_units and not _unit_matches_system_dep(name, dep_names)]
    # ALL-IN-ONE annotation: a superset packaging (a `standalone` that runs everything) keeps a
    # label suffix so it still reads as "runs the lot" — but with the single aggregate arrow there is no
    # fan for it to distort, so the old core/satellite split is gone (all processes share one lane).
    comps_by_uid = _components_run_by_uid(graph, uid_of)
    fold = _allinone_uids(process_uids, comps_by_uid)
    proc_set = set(process_uids)
    # COUPLING POINTS: the infrastructure used by 2+ processes, with REAL arrows. A catalog of every
    # broker/store/service the app touches is what the Dependencies view already is (and the Data view
    # covers the stores in far more depth) — repeating it here added nothing and, being derived from
    # `runs_in`, silently under-reported it. What only THIS view can say is placement: which
    # infrastructure couples processes together. Infra touched by a single process is not a coupling
    # point; it stays on that process's card, where it already is.
    infra_procs: dict[str, set[str]] = {}
    for u, b in infra:
        if u in proc_set:
            infra_procs.setdefault(b, set()).add(u)
    shared_infra = {b: us for b, us in infra_procs.items() if len(us) >= 2}
    # …and, on a big map, only the heaviest couplers. NEVER a silent cap: the count that did not fit
    # is drawn as a note box pointing at the view that does hold the full inventory.
    infra_dropped = 0
    if len(shared_infra) > INFRA_LANE_MAX:
        keep = sorted(shared_infra, key=lambda b: (-len(shared_infra[b]), b))[:INFRA_LANE_MAX]
        infra_dropped = len(shared_infra) - len(keep)
        shared_infra = {b: shared_infra[b] for b in keep}
    infra_boxes = sorted(shared_infra)

    # PRODUCT-AREA CONTAINERS: above the readable cap, processes running the same product areas collapse
    # into one drillable box (see `deployment_groups`). Members keep their own card; the container
    # carries the synthesized arrows.
    groups, group_of = deployment_groups(graph, process_units)
    uid_group = {uid_of[u]: gid for u, gid in group_of.items() if u in uid_of}
    box_of = {uid: uid_group.get(uid, uid) for uid in process_uids}      # process uid → what draws it
    grouped_uids = [uid for uid in process_uids if uid not in uid_group]  # ungrouped stay themselves
    group_label = {gid: deployment_group_label(graph, members) for gid, members in groups.items()}
    top_boxes = grouped_uids + sorted(groups)

    lines = ["flowchart TB"]
    class_lines: list[str] = []
    label_of = {uid: unit for uid, unit in units}  # process ids aren't in the clean graph — label from units
    label_of.update(group_label)                   # …and a container is labelled by its product areas
    allinone_label = {uid: f"{label_of.get(uid, uid)} — all-in-one: runs every subsystem" for uid in fold}

    def _decl(nid: str, default_kind: str, cls_override: str | None = None) -> tuple[str, str]:
        node = graph["nodes"].get(nid, {})
        name = allinone_label.get(nid) or label_of.get(nid) or str(node.get("name", nid))
        kind = str(node.get("kind") or default_kind)
        shape = SHAPE.get(kind, ('["', '"]'))
        cls = cls_override or (kind if kind in ("subsystem", "component", "infra", "dep", "process")
                               else "subsystem")
        return f'{nid}{shape[0]}{_safe_label(name)}{shape[1]}:::cy-{nid}', f"  class {nid} {cls}"

    def lane(lid: str, title: str, ids: list[str], default_kind: str) -> None:
        if not ids:
            return
        lines.append(f'  subgraph {lid}["{title}"]')
        for nid in ids:
            decl, cls = _decl(nid, default_kind)
            lines.append(f"    {decl}")
            class_lines.append(cls)
        lines.append("  end")

    # REDESIGN: one "Processes" lane, one "Subsystems" lane, joined by a SINGLE aggregate `runs` arrow
    # between the two lane boxes (the per-process→subsystem fan moves to each process's drill card).
    lane("L_proc", "Processes", top_boxes, "process")
    # Infrastructure lane, BANDED by derived role: nested role sub-bands (Message bus / Data store /
    # Service / Security / Other), each infra box coloured by its band. A dual-role dep (Redis =
    # bus + store) lands in the first band it qualifies for; a roleless infra falls to "Other" (slate).
    if infra_boxes:
        bands: dict[str, list[str]] = {}
        for did in infra_boxes:
            bands.setdefault(_infra_band_of(graph, did), []).append(did)
        lines.append('  subgraph L_infra["Shared infrastructure"]')
        for role, bid, title, cls in _INFRA_BANDS:
            ids = bands.get(role)
            if not ids:
                continue
            lines.append(f'    subgraph {bid}["{title}"]')
            for did in ids:
                decl, clsline = _decl(did, "infra", cls)
                lines.append(f"      {decl}")
                class_lines.append(clsline)
            lines.append("    end")
        if infra_dropped:
            # Say what was left out, and where it lives. A capped lane that reads as complete is the
            # "silent truncation" failure — the reader cannot tell 8-of-8 from 8-of-68.
            lines.append(f'    L_infra_more["+{infra_dropped} more shared '
                         f'{"dependency" if infra_dropped == 1 else "dependencies"} — '
                         f'see the Dependencies view"]')
            class_lines.append("  class L_infra_more infra")
        lines.append("  end")
    # A unit hosting no code and matching no infra dep is a real gap — surface it in its own lane rather
    # than dropping it silently (S2). It has no injected graph node (so it stays inert), and the viewer
    # keeps it searchable via a non-process fallback row.
    lane("L_untraced", "Untraced units", untraced, "process")

    lines += class_lines
    # PROCESS TOPOLOGY: the one thing only this view can say. A process→process arrow per ordered pair
    # that talks — asynchronously over a catalogued channel (`_channel_process_links`) OR synchronously
    # over a cross-process call (`_call_process_links`). BOTH mechanisms matter: a message-driven system
    # is all channels, an ordinary client/server app is all calls, and drawing only one leaves the other
    # kind of project with an empty diagram. ONE arrow per pair whichever way they talk, so an id can
    # never bind to the wrong bundle. Drawn only between boxes present in THIS env.
    chan_links = _channel_process_links(graph, uid_of, process_units)
    call_links = _call_process_links(graph, uid_of, process_units)
    # When containers are on, every endpoint is routed to the box that DRAWS it and the per-pair
    # bundles merge, so one container arrow stands for every member pair beneath it. A pair whose two
    # ends land in the SAME container is internal to it and belongs on its drill card, not here.
    merged_chan: dict[tuple[str, str], list[dict[str, str]]] = {}
    merged_call: dict[tuple[str, str], list[dict[str, str]]] = {}
    for src, dst in ((chan_links, merged_chan), (call_links, merged_call)):
        for (a, b), rows in src.items():
            if a not in proc_set or b not in proc_set:
                continue
            ga, gb = box_of.get(a, a), box_of.get(b, b)
            if ga != gb:
                dst.setdefault((ga, gb), []).extend(rows)
    for pair in sorted(set(merged_chan) | set(merged_call)):
        label = _process_edge_label(merged_chan.get(pair, []), merged_call.get(pair, []))
        lines.append(f"  {pair[0]} -->|{_edge_label(label)}| {pair[1]}")
    # …and a real arrow per process using a COUPLING POINT, so the sharing is visible rather than
    # implied by adjacency (which no reader can actually read). Bounded by construction: only infra
    # with 2+ users is drawn, so this cannot fan out into the hairball that removed these arrows before.
    for did in infra_boxes:
        for box in sorted({box_of.get(uid, uid) for uid in shared_infra[did]}):
            lines.append(f"  {box} --> {did}")
    lines.append(f"  classDef process {PROCESS_STYLE};")
    lines.append(f"  classDef subsystem {SUBSYSTEM_STYLE};")
    lines.append(f"  classDef component {COMPONENT_STYLE};")
    lines.append(f"  classDef infra {INFRA_STYLE};")
    lines.append(f"  classDef infraBus {INFRA_BUS_STYLE};")
    lines.append(f"  classDef infraStore {INFRA_STORE_STYLE};")
    lines.append(f"  classDef infraSvc {INFRA_SVC_STYLE};")
    lines.append(f"  classDef infraSec {INFRA_SEC_STYLE};")
    return "\n".join(lines)


def gen_deployment_group_card_mermaid(graph: GraphDict, gid: str) -> str:
    """A product-area container's card: its member processes, with the REAL arrows between them.

    The container hides nothing — it defers. The overview shows one synthesized arrow per container
    pair; opening the container shows which members actually carry it, and each member still drills to
    its own process card. Arrows that leave the container are drawn to the peer BOX (a sibling
    container or an ungrouped process), so the card reads as a zoom rather than a different diagram."""
    process_units = _process_unit_names(graph)
    groups, group_of = deployment_groups(graph, process_units)
    lines = ["flowchart TB"]
    members = groups.get(gid)
    if not members:
        return "\n".join(lines + [f'  MISSING["{_safe_label(gid)} — not a process group"]'])
    units = _deployment_unit_ids(graph)
    uid_of = {name: u for u, name in units}
    member_uids = {uid_of[u] for u in members if u in uid_of}
    uid_group = {uid_of[u]: g for u, g in group_of.items() if u in uid_of}
    label_of = {uid: name for uid, name in units}
    label_of.update({g: deployment_group_label(graph, ms) for g, ms in groups.items()})

    lines.append(f'  subgraph {gid}_box["{_safe_label(deployment_group_label(graph, members))}"]')
    for uid in sorted(member_uids):
        lines.append(f'    {uid}["{_safe_label(label_of.get(uid, uid))}"]:::cy-{uid}')
    lines.append("  end")
    cls = [f"  class {uid} process" for uid in sorted(member_uids)]

    chan = _channel_process_links(graph, uid_of, process_units)
    call = _call_process_links(graph, uid_of, process_units)
    inside: dict[tuple[str, str], tuple[list, list]] = {}
    outside: dict[tuple[str, str], tuple[list, list]] = {}
    for src, idx in ((chan, 0), (call, 1)):
        for (a, b), rows in src.items():
            if a not in member_uids and b not in member_uids:
                continue
            if a in member_uids and b in member_uids:
                pair, bucket = (a, b), inside
            else:
                # one end is outside: draw it to the peer's BOX (its container, or itself)
                pair = (uid_group.get(a, a), uid_group.get(b, b))
                if pair[0] == pair[1]:
                    continue
                bucket = outside
            slot = bucket.setdefault(pair, ([], []))
            slot[idx].extend(rows)
    for pair in sorted(outside):
        for nid in pair:
            if nid not in member_uids and nid != gid:
                lines.append(f'  {nid}["{_safe_label(label_of.get(nid, nid))}"]:::cy-{nid}')
                cls.append(f"  class {nid} process")
    for bucket in (inside, outside):
        for pair in sorted(bucket):
            chans, calls = bucket[pair]
            src, dst = pair
            src = gid + "_box" if src == gid else src
            dst = gid + "_box" if dst == gid else dst
            lines.append(f"  {src} -->|{_edge_label(_process_edge_label(chans, calls))}| {dst}")
    lines += sorted(set(cls))
    lines.append(f"  classDef process {PROCESS_STYLE};")
    return "\n".join(lines)


def deployment_group_cards(graph: GraphDict) -> dict[str, str]:
    """`{group_id: card mermaid}` for every product-area container on the overview."""
    groups, _ = deployment_groups(graph, _process_unit_names(graph))
    return {gid: gen_deployment_group_card_mermaid(graph, gid) for gid in groups}


def deployment_group_members(graph: GraphDict) -> dict[str, list[str]]:
    """`{group_id: [unit names]}` — the frontend's list for a container's info pane."""
    return deployment_groups(graph, _process_unit_names(graph))[0]


def gen_deployment_unit_card_mermaid(graph: GraphDict, unit: str) -> str:
    """One process's card: the unit box + the subsystems/components it runs AND the brokers/stores it
    uses. The infra arrows are dropped from the OVERVIEW (ambient band there) and shown HERE instead, so
    a process's actual dependencies are still one click away. Its threads are a panel list on the
    frontend, not diagram nodes. Reuses `_deployment_edges` so the card's runs/infra match the overview's
    exactly (one derivation).

    KNOWN LIMIT — a card is ENVIRONMENT-INDEPENDENT (see `deployment_cards`): it lists everything the
    unit runs, uses and exchanges channels with, whatever environment the picker has selected. For the
    subsystems and infra that is right (they do not change per environment). For a PEER PROCESS it is a
    compromise: with `prod` selected, a card can still name a dev-only peer the overview has hidden, and
    that peer box still drills. Closing it means generating cards per environment (the shape
    the viewer's environment dimming already uses) — deliberately not done here."""
    units = _deployment_unit_ids(graph)
    uid_of = {name: u for u, name in units}
    uid = uid_of.get(unit)
    lines = ["flowchart TB"]
    if uid is None:
        return "\n".join(lines + [f'  MISSING["{_safe_label(unit)} — not a deployment unit"]'])
    runs, infra, _boxes = _deployment_edges(graph, uid_of)
    lines.append(f'  {uid}["{_safe_label(unit)}"]:::cy-{uid}')
    lines.append(f"  class {uid} process")
    for nid in sorted({b for u, b in runs if u == uid}):        # subsystems/components it runs
        lines += _declare_box(graph, nid, "subsystem")
        lines.append(f"  {uid} --> {nid}")
    for did in sorted({d for u, d in infra if u == uid}):       # brokers/stores it uses (dropped from overview)
        lines += _declare_box(graph, did, "infra")
        lines.append(f"  {uid} --> {did}")
    # The peer processes it exchanges channels with, in both directions — the same derivation the
    # overview draws, narrowed to this unit, so a card answers "who feeds me / who do I feed".
    name_of = dict(units)
    hosted = _process_unit_names(graph)
    chan_links = _channel_process_links(graph, uid_of, hosted)
    call_links = _call_process_links(graph, uid_of, hosted)
    mine = sorted({p for p in set(chan_links) | set(call_links) if uid in p and p[0] != p[1]})
    for peer in sorted({b if a == uid else a for a, b in mine}):
        lines.append(f'  {peer}["{_safe_label(name_of.get(peer, peer))}"]:::cy-{peer}')
        lines.append(f"  class {peer} process")
    for pair in mine:
        label = _process_edge_label(chan_links.get(pair, []), call_links.get(pair, []))
        lines.append(f"  {pair[0]} -->|{_edge_label(label)}| {pair[1]}")
    lines.append(f"  classDef process {PROCESS_STYLE};")
    lines.append(f"  classDef subsystem {SUBSYSTEM_STYLE};")
    lines.append(f"  classDef component {COMPONENT_STYLE};")
    lines.append(f"  classDef infra {INFRA_STYLE};")
    return "\n".join(lines)


def deployment_cards(graph: GraphDict) -> dict[str, str]:
    """`{unit_name: card_mermaid}` — the per-process drill cards, keyed by unit NAME (the frontend
    drills a process to `{kind:'deploymentUnit', unit:<node.unit>}`). Cards are env-independent (a
    unit's card lists everything it runs); the environment picker only filters the OVERVIEW."""
    return {unit: gen_deployment_unit_card_mermaid(graph, unit)
            for _uid, unit in _deployment_unit_ids(graph) if unit}


def _with_group_pairs(graph: GraphDict, links: dict[tuple[str, str], list[dict[str, str]]]
                      ) -> dict[str, list[dict[str, str]]]:
    """`{'<src>><dst>': rows}` for every process pair, PLUS the container pairs the overview draws.

    A container arrow stands for its members' arrows, so selecting it must list exactly those. Without
    the container keys the synthesized arrows rendered but bound to nothing — visible, unselectable,
    and silently different from every other arrow in the viewer."""
    process_units = _process_unit_names(graph)
    uid_of = {unit: uid for uid, unit in _deployment_unit_ids(graph)}
    _groups, group_of = deployment_groups(graph, process_units)
    box = {uid_of[u]: g for u, g in group_of.items() if u in uid_of}
    out: dict[str, list[dict[str, str]]] = {f"{a}>{b}": rows for (a, b), rows in links.items()}
    merged: dict[tuple[str, str], list[dict[str, str]]] = {}
    for (a, b), rows in links.items():
        ga, gb = box.get(a, a), box.get(b, b)
        if ga != gb and (ga != a or gb != b):        # at least one end is inside a container
            merged.setdefault((ga, gb), []).extend(rows)
    for (a, b), rows in merged.items():
        out[f"{a}>{b}"] = rows
    return out


def gen_deployment_edges(graph: GraphDict) -> dict[str, list[dict[str, str]]]:
    """For each process→process arrow the Deployment view can draw — on the overview AND on either
    end's card — the async channels it carries, keyed `'<src_uid>><dst_uid>'` to match the edge bridge
    (the deployment analog of `gen_container_edges`). Selecting the arrow lists these, each with its
    kind, its broker and the source line that declares it."""
    uid_of = {unit: uid for uid, unit in _deployment_unit_ids(graph)}
    return _with_group_pairs(
        graph, _channel_process_links(graph, uid_of, _process_unit_names(graph)))


def gen_deployment_call_edges(graph: GraphDict) -> dict[str, list[dict[str, str]]]:
    """For each process→process arrow, the SYNCHRONOUS component→component calls behind it — keyed
    `'<src_uid>><dst_uid>'`, the sibling of `gen_deployment_edges` (which carries the async channels).
    A pair may appear in both when two processes talk each way; the viewer draws one arrow and lists
    each mechanism under its own heading."""
    uid_of = {unit: uid for uid, unit in _deployment_unit_ids(graph)}
    return _with_group_pairs(
        graph, _call_process_links(graph, uid_of, _process_unit_names(graph)))


def gen_deployment_infra_edges(graph: GraphDict) -> dict[str, list[dict[str, str]]]:
    """For each process→infrastructure arrow, the component→dep CALLS behind it — keyed
    `'<process_uid>><dep_id>'` to match the edge bridge, like `gen_deployment_edges` does for channels.
    Selecting a coupling-point arrow then answers "why does this process need this store" with the
    components, verbs, reasons and call sites, instead of leaving the arrow mute."""
    uid_of = {unit: uid for uid, unit in _deployment_unit_ids(graph)}
    sites = _infra_call_sites(graph, uid_of)
    _groups, group_of = deployment_groups(graph, _process_unit_names(graph))
    box = {uid_of[u]: g for u, g in group_of.items() if u in uid_of}
    out: dict[str, list[dict[str, str]]] = {f"{uid}>{did}": rows for (uid, did), rows in sites.items()}
    # …and the same rows under the CONTAINER that draws the arrow on the overview, so a coupling-point
    # arrow leaving a container answers "which of these processes reach this store, and where".
    merged: dict[tuple[str, str], list[dict[str, str]]] = {}
    for (uid, did), rows in sites.items():
        if uid in box:
            merged.setdefault((box[uid], did), []).extend(rows)
    for (gid, did), rows in merged.items():
        out[f"{gid}>{did}"] = rows
    return out


def gen_context_edges(graph: GraphDict) -> dict[str, dict[str, Any]]:
    """Explanations for the Context view's synthetic edges, derived from already-parsed map data:
    actor→system = the role's 'wants'; system→dep = the dep's 'Used for' + the component edges
    (with their Why) that realize it; system→Libraries = the collapsed fold (panel reuses the roster).
    Keyed by '<src>><dst>' to match the rendered edge path ids. Registering the Libraries arrow here is
    what lets the viewer's focus/dim pass treat it like any other edge (keep it lit when the System is
    focused; dim it when a dependency is selected) — without an entry the arrow stays un-bound."""
    title = graph["title"] or "System"
    ce: dict[str, dict[str, Any]] = {}
    for i, r in enumerate(graph["roles"]):
        rid = _actor_id(i)
        ce[rid + ">SYS"] = {"src": rid, "dst": "SYS", "type": "actor",
                            "from": r["name"], "to": title, "wants": r["wants"]}
    # component edges grouped by their target — the "realized by" detail for system→dep
    by_dst: dict[str, list[dict[str, str]]] = {}
    for e in graph["edges"]:
        src, dst = str(e["src"]), str(e["dst"])
        node = graph["nodes"].get(src)
        why = e["why"]
        by_dst.setdefault(dst, []).append({
            "src": src,
            "srcName": str(node["name"]) if node else src,
            "verb": str(e["verb"]),
            "why": str(why) if why else "",
        })
    for nid, node in graph["nodes"].items():
        if str(node["kind"]) != "dep":
            continue
        fields = cast("dict[str, object]", node["fields"])
        ce["SYS>" + nid] = {"src": "SYS", "dst": nid, "type": "dep",
                            "from": title, "to": str(node["name"]),
                            "usedFor": str(fields.get("Used for") or ""),
                            "realizedBy": by_dst.get(nid, [])}
    # The collapsed Libraries fold draws a `SYS -->|bundles| LIBS` arrow (gen_context_mermaid). Register
    # it so the viewer binds it as a real edge; its panel/tooltip reuse the box's roster, not a 'why'.
    if folded_libs(graph):
        ce["SYS>" + LIBS_ID] = {"src": "SYS", "dst": LIBS_ID, "type": "libs",
                                "from": title, "to": "Libraries"}
    # Same for each folded bucket's `SYS --> <id>` arrow (external Context buckets + library-drill
    # buckets) — so the viewer binds it and clicking the arrow opens the bucket's roster (its `type`
    # routes to showBucketFold, not a 'why').
    for fb in all_folded_buckets(graph):
        ce["SYS>" + fb["id"]] = {"src": "SYS", "dst": fb["id"], "type": "bucketfold",
                                 "from": title, "to": fb["name"]}
    return ce


def has_hp(graph: GraphDict) -> bool:
    return bool(graph["happy_path"])


def _safe_msg(s: str) -> str:
    """Sanitize text for a Mermaid sequenceDiagram message / participant label: strip markdown links
    and emphasis, drop the chars that break sequence parsing (`;#<>` + newlines), collapse runs of
    whitespace. Colons are kept (only the FIRST colon delimits a message)."""
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)   # md link -> its text
    s = re.sub(r"[`*]", "", s)
    s = s.replace("\n", " ").replace(";", ",").replace("#", "").replace("<", "(").replace(">", ")")
    return re.sub(r"\s+", " ", s).strip()


def _hp_actors(graph: GraphDict, step: dict[str, Any]) -> list[str]:
    """The actor NAMES that can drive a GP step = the actors of the use case it realizes (a step IS
    exactly one use case, so no separate actor signal is needed), falling back to a generic 'Actor'.

    Usually one name. A use case may list several INTERCHANGEABLE initiators — either party can start
    the same action — and those are the reason this returns a list: reading the human `Actor` field
    instead gave one joined string ("Team member, Organization admin"), which the diagram then drew as
    a third lifeline for a person who does not exist. The `actors` list is the same fact, unjoined.
    The field is still the fallback for a graph built before it existed."""
    uc = step.get("uc")
    node = graph["nodes"].get(uc) if isinstance(uc, str) else None
    if node:
        names = [_safe_msg(str(a)) for a in cast("list[str]", node.get("actors") or []) if str(a).strip()]
        if names:
            return names
        for k, v in cast("dict[str, str]", node.get("fields") or {}).items():
            if k.strip().lower() == "actor" and str(v).strip():
                return [_safe_msg(str(v))]
    return ["Actor"]


def _hp_actor_order(graph: GraphDict) -> dict[str, str]:
    """{actor name: participant id} in the order the lifelines are declared — EVERY actor of every
    step, primary first, in first-appearance order. The co-actors of a shared use case are declared
    here too (not only the one an arrow starts from), which is what gives them a lifeline to be marked
    on. Read by hp_actors, which is what tells the viewer who drives each step."""
    order: dict[str, str] = {}
    for st in cast("list[dict[str, Any]]", graph["happy_path"]):
        for name in _hp_actors(graph, st):
            order.setdefault(name, "HPA" + str(len(order)))
    return order


def hp_actors(graph: GraphDict) -> list[dict[str, Any]]:
    """Per-actor data for the Happy Path lifelines, in the SAME participant order/ids as
    _hp_actor_order gives (`HPAn`). Each actor links back to its
    Roles-table entry by name to surface what it wants + its kind, plus the GP steps it drives —
    `stepIdx` are the message positions the viewer highlights when the actor is selected.

    An actor drives a step when it is ONE OF that step's interchangeable actors, not only when the
    arrow happens to start from it: the alternative initiator genuinely drives that step too, so
    selecting it lights the step and its card lists it."""
    steps = cast("list[dict[str, Any]]", graph["happy_path"])
    roles_by_name = _roles_by_name(graph)
    order = _hp_actor_order(graph)  # actor name -> participant id, in first-appearance order
    out: list[dict[str, Any]] = []
    for name, aid in order.items():
        idxs = [i for i, st in enumerate(steps) if name in _hp_actors(graph, st)]
        role = roles_by_name.get(name.strip().lower())
        out.append({
            "aid": aid,
            "name": name,
            "kind": str(role["kind"]) if role else "",
            "wants": str(role["wants"]) if role else "",
            "steps": [{"id": str(steps[i]["id"])} for i in idxs],
            "stepIdx": idxs,
        })
    return out


# ── T6 use-case flows: the shared sequence renderer ───────────────────────────────────────────────
# One renderer drives BOTH the use-case view and the Happy-Path step drill-down (an HP step IS a use
# case, so it opens that use case's flow). A flow renders two derived views from ONE source — a Mermaid
# sequenceDiagram (the visual) and a numbered narrative (the readable text) — so the "why" of each step
# is never authored twice. Each step carries its OWN action text; the arrow and the panel render from
# that text alone, so a step describes what happens at that point — not a shared pair-level edge label.

def _edge_index(graph: GraphDict) -> dict[tuple[str, str], tuple[str, str]]:
    """{(src_id, dst_id): (verb, why)} from the backbone edges — the single source for an element↔
    element flow step's label/why. First edge for a pair wins (a pair almost always has one)."""
    idx: dict[tuple[str, str], tuple[str, str]] = {}
    for e in cast("list[dict[str, Any]]", graph["edges"]):
        key = (str(e.get("src")), str(e.get("dst")))
        if key not in idx:
            idx[key] = (str(e.get("verb") or ""), str(e.get("why") or ""))
    return idx


def _roles_by_name(graph: GraphDict) -> dict[str, dict[str, Any]]:
    """Roles indexed for name lookup — under BOTH the AUTHORED name and its DISPLAY form
    (`_safe_msg`), because callers legitimately hold either: a flow step's endpoint is the authored
    token, while a Happy Path actor has already been through `_safe_msg` by the time it gets here.

    Indexing one space and looking up in the other is a silent miss, and a missed role returns no
    `kind` — which draws a `service` actor as a PERSON in whichever view got it wrong. That has now
    happened in both directions (display-keyed lost the flow view; authored-keyed lost the Happy
    Path), so neither space is 'the' right one and the index carries both. The authored spelling wins
    a collision: it is what the map actually says.

    Keys are stripped + lowercased, as every caller's token is.

    Written as TWO PASSES, not one loop writing both keys per role: the authored spelling must beat a
    DIFFERENT role's display form, and a single loop only makes it beat the same role's — leaving the
    winner to list order. Two roles named `Night Shift` and `Night  Shift` (a doubled space, which
    `_safe_msg` collapses — a typo, not an exotic name) then resolved to whichever was written last,
    so one of them silently wore the other's kind and `wants`."""
    roles = cast("list[dict[str, Any]]", graph["roles"])
    out: dict[str, dict[str, Any]] = {}
    for r in roles:                                # pass 1: display forms
        out[_safe_msg(str(r["name"])).strip().lower()] = r
    for r in roles:                                # pass 2: authored names, which win outright
        out[str(r["name"]).strip().lower()] = r
    return out


def is_role_endpoint(is_id: bool) -> bool:
    """Is this flow-step endpoint a PERSON (a Role) rather than an element? The one rule, shared by
    every consumer — the sequence diagram, the flow map and `flow_actors` — because they must agree on
    which endpoints get an `FAn` alias or the alias numbering drifts between them.

    The rule is the authored shape: a token authored as an ID is an element, full stop. A dangling id
    (one no element defines — `coyomap validate` blocks it, but `serve` still renders drafts) stays an
    element, drawn as a box labelled with the raw id: a visible gap. It must NOT fall through to the
    role branch, where a missing element would mis-read as a person AND would consume an `FAn` alias
    that the other renderings hand to a real actor — which is how one drawing's `FA0` came to mean a
    different participant than another's."""
    return not is_id


def _flow_step_label(idx: dict[tuple[str, str], tuple[str, str]], st: dict[str, Any]) -> str:
    """A flow step's arrow label: the step's OWN authored text (`phrase`) describing the action at this
    point in the scenario. Every step carries one (`coyomap validate` requires it), so this is the normal
    path. The backbone-edge lookup is only a safety net for a legacy step that predates that rule and left
    its text empty — a pair used by several steps can't be described correctly by one shared edge label,
    which is exactly why the step describes itself. The net prefers the edge's descriptive `Why` over its
    terse verb, then falls back to a neutral 'uses'."""
    phrase = str(st.get("phrase") or "").strip()
    if phrase:
        return phrase
    if st.get("subflow"):  # a DEGRADED reference step (unresolved/empty sub-flow — validate blocks
        return f"run {st['subflow']}"  # it, but serve renders drafts): name the run, never 'uses'
    if st.get("src_is_id") and st.get("dst_is_id"):
        verb, why = idx.get((str(st["src"]), str(st["dst"])), ("", ""))
        if why:
            return why
        if verb:
            return verb
    return "uses"


def subflow_chips(graph: GraphDict) -> dict[str, list[dict[str, str]]]:
    """Per shared sub-use case, the people, doors and records inside it.

    A use-case map draws a shared sub-use case as one collapsed box, and these ride ON that box — so a reader
    still sees where the product meets the outside world and what it keeps, without opening the walk.
    That is the design philosophy's own rule: the critical pieces are surfaced, not buried.

    Components are deliberately NOT chips. A shared sub-use case is MADE of components, so every box would carry
    the same crowd and the two things worth seeing would be lost in it.

    Order is people, doors, records — stable, so a walk gaining one does not reshuffle the row."""
    out: dict[str, list[dict[str, str]]] = {}
    for sf in cast("list[dict[str, Any]]", graph.get("subflows") or []):
        people: list[dict[str, str]] = []
        doors: list[dict[str, str]] = []
        recs: list[dict[str, str]] = []
        for st in cast("list[dict[str, Any]]", sf.get("steps") or []):
            if not st.get("ok"):
                continue
            for tok, is_id in ((st["src"], st.get("src_is_id")), (st["dst"], st.get("dst_is_id"))):
                token = str(tok)
                if is_role_endpoint(bool(is_id)):
                    if not any(c["name"] == token for c in people):
                        people.append({"kind": "actor", "id": "", "name": token})
                    continue
                node = cast("dict[str, Any] | None", graph["nodes"].get(token))
                kind = str((node or {}).get("kind") or "")
                bucket = doors if kind == "interface" else recs if kind == "entity" else None
                if bucket is None or any(c["id"] == token for c in bucket):
                    continue
                bucket.append({"kind": kind, "id": token,
                               "name": str((node or {}).get("name") or token)})
        out[str(sf["id"])] = people + doors + recs
    return out


def own_steps(graph: GraphDict, flow: dict[str, Any],
              chips: dict[str, list[dict[str, str]]] | None = None) -> list[dict[str, Any]]:
    """The walk's OWN ok-filtered steps — a shared-walk reference stays ONE step.

    This is what a READER walks. The four per-walk views (sequence, map, narrative, actors) all consume
    it, so `message[i]` <-> `FLOWS_NARR[uc][i]` <-> `actor stepIdx` is still one index space, and a step
    number still means the same moment in both renderings of the same walk.

    THE INSIDE OF A SHARED SUB-USE CASE IS NOT THIS WALK'S BUSINESS. Expanded, a use case appeared to do work it
    only borrows: measured on the live maps, a use case walk is 16 steps stored and 27 shown, and 12 of
    the 21 steps of one mcpolis use case belonged to two other walks. The shared sub-use case gets a screen of
    its own instead, where its steps are numbered from 1 and belong to it.

    What ASKS "does this use case reach that record, that door?" must keep expanding — running a shared
    walk does reach what is inside it. `model.expanded_flow_steps` is that one, and every check already
    uses it; nothing here changes them.

    A reference step gains `sf` (the walk's id), `sfName`, `sfSteps` (how many it holds) and `sfChips`
    (see `subflow_chips`). Its own `src` is the box that runs it; the DRAWN destination is `sf`, never
    the authored `dst`, which names some component inside the walk. No reference step in either live map
    carries text of its own (0 of 84), so `run` is the verb unless one is authored — imperative,
    like every other phrase and like the walk's own name it arrives at.

    An unresolved reference or an empty shared sub-use case (validate blocks both, serve renders drafts) stays a
    bare step, so nothing disappears silently."""
    ch = subflow_chips(graph) if chips is None else chips
    sfs = {str(sf.get("id")): sf for sf in cast("list[dict[str, Any]]", graph.get("subflows") or [])}
    out: list[dict[str, Any]] = []
    for st in cast("list[dict[str, Any]]", flow.get("steps") or []):
        if not st.get("ok"):
            continue
        sf = sfs.get(str(st.get("subflow") or ""))
        inner = [x for x in cast("list[dict[str, Any]]", (sf or {}).get("steps") or []) if x.get("ok")]
        if sf is None or not inner:
            out.append(st)
            continue
        e = dict(st)
        e["sf"] = str(sf["id"])
        e["sfName"] = str(sf.get("name") or sf["id"])
        e["sfSteps"] = len(inner)
        e["sfChips"] = ch.get(str(sf["id"]), [])
        # `run`, not `runs`: a phrase is imperative, like the walk's own name it arrives at.
        e["phrase"] = str(st.get("phrase") or "").strip() or "run"
        out.append(e)
    return out


def all_walks(graph: GraphDict) -> list[dict[str, Any]]:
    """Every walk the viewer can draw: the use case walks, plus each SHARED walk as a walk in its own
    right.

    A shared sub-use case is stored in the same shape a use case walk is — a title and an ordered list of steps
    — so the four per-walk generators take it unchanged. That is what gives a shared sub-use case its own
    screen without a second set of generators to keep in step with the first."""
    out: list[dict[str, Any]] = list(graph["flows"])
    for sf in cast("list[dict[str, Any]]", graph.get("subflows") or []):
        out.append({"uc": str(sf["id"]), "title": str(sf.get("name") or sf["id"]),
                    "steps": sf.get("steps") or []})
    return out


#: WHAT A PERSON CAME THROUGH, said in WORDS on their own label rather than drawn beside them.
#: A glyph was built first — a small bot head on a short line off the person's head — and it was
#: rejected on sight: at the size these render, a figure with an object beside it reads as a SECOND
#: CHARACTER, and an attended AI agent is a pipe, not a party. Words carry the same fact, cannot be
#: misread as a participant, and work identically on every picture including the ones nothing has
#: post-processed.
#: ON ITS OWN LINE, and the phrase never splits. Run on after the name it wrapped wherever the label
#: was narrow — "Team member · via AI" / "agent" — breaking the one phrase a reader needs whole. The
#: `<br/>` is added OUTSIDE the label sanitisers on purpose: `_safe_msg` turns `<` into `(`, and
#: `_safe_label` says in its own docstring that an intentional break is the caller's to add.
#: The non-breaking space is the belt: even a renderer that ignores the break keeps "AI agent" whole.
#: Parentheses because this is an aside about the name, not part of it.
#: ONE SPELLING NOW. There were two, because the two pictures sized a label differently and each broke
#: the other way. The MAP's is gone with the label it rode on: a person's box there is an item box, and
#: "via AI agent" is a PILL on it, laid out by the box rather than by a hand-placed line break.
#: The non-breaking space keeps "AI agent" whole.
CLIENT_LABEL_TEXT = " (via AI\u00a0agent)"          # one line — the lifeline picture, and matching


def flow_client_roles(graph: GraphDict, steps: list[dict[str, Any]]) -> set[str]:
    """The role names in these steps that a person reached an agent-facing surface through.

    ONE ANSWER, read by the sequence picture's label, the map picture's label and `flow_actors`.
    Three copies of this join would be three chances for one screen to say a person came through an
    agent while another says they did not — the failure this file has already been broken by once,
    over two copies of "who is an actor".

    NEVER FOR A MACHINE ACTOR: an unattended agent reaches an MCP address alone, and saying it came
    through an agent would be an agent behind an agent."""
    ifkind: dict[str, str] = {}
    for nid, n in graph["nodes"].items():
        if str(n["kind"]) != "interface":
            continue
        fields = cast("dict[str, Any]", n.get("fields") or {})
        ifkind[nid] = str(fields.get("Kind") or "")
    roles_by_name = _roles_by_name(graph)
    out: set[str] = set()
    for st in steps:
        for near, far in ((str(st["src"]), str(st["dst"])), (str(st["dst"]), str(st["src"]))):
            if ifkind.get(far, "") not in grammar.INTERFACE_KINDS_REACHED_THROUGH_A_CLIENT:
                continue
            role = roles_by_name.get(near.strip().lower())
            if role is not None and not grammar.is_machine_role(str(role["kind"])):
                out.add(near)
    return out


# ── the walk MAP — the ONE picture of a use case ───────────────────────────────────────────────────
# It answers both questions a reader has: what does this use case touch, and in what order. The order is
# on the arrows, as the step numbers the side panel and the step player count in.
#
# A SEQUENCE DIAGRAM stood beside it and was removed. Two renderings of one walk meant every rule had to
# be written twice and kept in step — and the map answers strictly more: it draws the element kinds in
# the structural views' own colours and shapes, which lifelines cannot.
#: HOW A BOX GETS ONTO THIS MAP. The generator writes the SHAPE of the drawing — which boxes, which
#: arrows, which step numbers — and nothing about what a box SAYS. What a box says is `itemBoxHtml` in
#: the viewer, and it is the one box every picture in this product draws; a second copy of it here, in
#: Python, is exactly the drift the item box was built to end. Measured before it existed: eleven
#: builders in five designs, the name set in three sizes, one stick figure drawn twice.
#:
#: So each node's label is one EMPTY SLOT and the node itself is invisible — the box IS the label. The
#: viewer builds the box, measures it, gives the drawing engine that exact size, and swaps the real box
#: in once the drawing is on the page (see `expandItemSlots` / `fillItemSlots`).
#:
#: The label therefore holds no markup the engine's own label syntax could choke on: one span, three
#: unquoted attributes, no angle brackets and no quotes of ours. `data-id` is URL-encoded because an
#: actor's is a NAME, and a name may hold anything.
# A SLOT NODE DRAWS NO SHAPE OF ITS OWN: the item box the viewer swaps in is the box. `ITEM_SLOT_CLASSDEF`
# is the flowchart form (a class every slot node is tagged with), `ITEM_SLOT_STYLE` the classDiagram form
# (one `style` line per class), because the two diagram types take their styling differently.
ITEM_SLOT_CLASSDEF = "  classDef itembox fill:none,stroke:none;"
ITEM_SLOT_STYLE = "fill:none,stroke:none"
# 2, not 0: an arrowhead lands ON the border at 0 and its point sits inside the box's own rule. Every
# flowchart drawn from item-box slots leads with this (the use case map, the Data overview); a
# classDiagram cannot, and the viewer closes that one's gap itself (see fillItemSlots).
SLOT_MAP_INIT = "%%{init: {'flowchart': {'padding': 2}}}%%"


def _slot(kind: str, variant: str, ident: str, pill: str = "") -> str:
    """One item-box slot, as a mermaid node label body."""
    extra = f" data-pill={quote(pill, safe='')}" if pill else ""
    return (f"<span class=cyslot data-k={kind} data-v={variant} "
            f"data-id={quote(ident, safe='')}{extra}></span>")


def _flow_map_arrow_label(ns: list[int]) -> str:
    """The step numbers riding one pair — the same 1-based positions the sequence diagram numbers its
    messages with, so a reader can carry a number from one rendering to the other.

    EVERY number is listed, never a truncated head: the whole promise of the label is that the two
    renderings can be read against each other, and `1, 2, 3, 4 +3` breaks it for steps 5-7 — they would
    appear nowhere on the map. The flow step band (3-15) bounds the worst case at a short list — doors are exempt from that
    band, so a door-heavy flow can run a little longer than 15."""
    return ", ".join(str(n) for n in ns)


def gen_flow_map_mermaid(graph: GraphDict, flow: dict[str, Any]) -> str:
    """One walk as a LEAF-ONLY map: a box per touched element (component / dependency / record / the
    driving actor) and one arrow per ordered pair, labelled with the step numbers that ride it.

    EVERY BOX IS AN ITEM BOX, in the variant this picture asked for:

    * the PERSON keeps the stick figure it has always had here, so the actor is still the biggest mark
      on the drawing (`figure`);
    * a SHARED SUB-USE CASE is a full box (`full`) — it is the one box a reader cannot see inside, so it has to
      wear its people, doors and records as chips or collapsing it buries the product's edge;
    * everything else is `tight`: a glyph, a name, and the kind said by the box's own colour. What a
      tight box leaves out is one click away in the floating card, which is the same box in full.

    Measured on MCP Hero's 11-step walk: this drawing is 1678x459 against 1224x383 for the old one, so
    41% wider and 20% taller. Every richer arrangement tried cost more: a full box everywhere at a fixed
    300px width came to 3170px wide on the 27-step walk, and fitting each box to its own text is what
    took that back.

    Three choices that predate the item box and still hold:

    * **No subsystem / subdomain frames.** Scoped to one use case, a container frames one or two
      members and reads as noise. The group lives in the element's own panel, a click away.
    * **Arrows come from THIS WALK'S STEPS, never the backbone edge list.** A step is what the
      scenario does; a backbone edge is the aggregate of every scenario. Drawing edges here would
      show relationships this use case never exercises.
    * **Nothing is drawn OUT of a shared sub-use case's box.** No step in the model hands control back; the
      walk simply continues, and its next step draws itself. Measured before this was built: an arrow
      out of the box would have to be invented for 64 of 83 runs.

    A box's mermaid id IS its element id (an actor gets the `FAn` alias, a shared sub-use case its `SFn`), so
    the viewer's generic node binding resolves a click with no special casing."""
    steps = own_steps(graph, flow)
    clients = flow_client_roles(graph, steps)
    pid: dict[str, str] = {}
    decls: list[str] = []
    n_actor = 0

    def ensure(token: str, is_id: bool) -> None:
        nonlocal n_actor
        if is_role_endpoint(is_id):                    # a Role name (actor step) — no node behind it
            if token in pid:
                return
            aid = "FA" + str(n_actor)
            n_actor += 1
            pid[token] = aid
            # VIA AN AI AGENT is a fact about THIS WALK, not about the actor, so the generator is the
            # only thing that can know it and it rides on the slot as an extra pill.
            via = "via AI agent" if token in clients else ""
            decls.append(f'  {aid}["{_slot("role", "figure", token, via)}"]:::cy-{aid}')
            decls.append(f"  class {aid} itembox")
            return
        if token in pid:
            return
        node = cast("dict[str, Any] | None", graph["nodes"].get(token))
        # An unknown id (validate blocks the build on one, serve still renders drafts) still draws a
        # box, labelled with the raw id — visible as a gap, never silently dropped.
        kind = str((node or {}).get("kind") or "component")
        pid[token] = token
        decls.append(f'  {token}["{_slot(kind, "tight", token)}"]:::cy-{token}')
        decls.append(f"  class {token} itembox")

    def ensure_sf(st: dict[str, Any]) -> None:
        sid = str(st["sf"])
        if sid in pid:
            return
        pid[sid] = sid
        decls.append(f'  {sid}["{_slot("subflow", "full", sid)}"]:::cy-{sid}')
        decls.append(f"  class {sid} itembox")

    def box_of(st: dict[str, Any]) -> str:
        return str(st["sf"]) if st.get("sf") else pid[str(st["dst"])]

    for st in steps:
        ensure(str(st["src"]), bool(st.get("src_is_id")))
        if st.get("sf"):
            ensure_sf(st)
        else:
            ensure(str(st["dst"]), bool(st.get("dst_is_id")))
    # One arrow per ORDERED pair, in first-appearance order; a return-direction step is its own arrow,
    # so a call and its response stay two arrows rather than collapsing into one ambiguous line.
    pairs: dict[tuple[str, str], list[int]] = {}
    for i, st in enumerate(steps):
        pairs.setdefault((pid[str(st["src"])], box_of(st)), []).append(i + 1)
    # NO NODE PADDING ON THIS MAP. Every box here is an ITEM BOX carrying its own padding, and the
    # engine's default wraps another 30 units of nothing round its sides and 15 above and below —
    # measured: a 208x40 box inside a 268x70 invisible rectangle. Arrows stop on THAT rectangle, so
    # every arrowhead ended 30 units short of the box it points at, and the drawing paid the width for
    # the gap. Set for this diagram alone, in its own source: on every other map a label is plain text
    # and needs the padding to stand off its border.
    lines = [SLOT_MAP_INIT, "flowchart LR", *decls]
    for (a, b), ns in pairs.items():
        lines.append(f"  {a} -->|{_edge_label(_flow_map_arrow_label(ns))}| {b}")
    lines.append(ITEM_SLOT_CLASSDEF)
    return "\n".join(lines)


def flow_narrative(graph: GraphDict, flow: dict[str, Any]) -> list[dict[str, Any]]:
    """The readable numbered steps for the side panel — the SAME source the map draws from. Each step
    carries its from/to display names + (clickable) node ids, its own action text, and any note. The panel
    describes the step from the step alone — it does NOT pull the shared backbone-edge description, since
    a pair used by several steps has one edge label that can't be right for all of them. `why` stays empty
    for a normal step; the edge lookup is only a safety net for a legacy step with no authored text."""
    idx = _edge_index(graph)
    out: list[dict[str, Any]] = []
    for st in own_steps(graph, flow):
        src, dst = str(st["src"]), str(st["dst"])
        src_id = src if (st.get("src_is_id") and src in graph["nodes"]) else None
        dst_id = dst if (st.get("dst_is_id") and dst in graph["nodes"]) else None
        phrase = str(st.get("phrase") or "").strip()
        verb, why = phrase, ""
        if not phrase:                             # safety net: a legacy step that left its text empty
            if st.get("subflow"):                  # a degraded reference — name the walk it runs
                verb = f"run {st['subflow']}"
            elif st.get("src_is_id") and st.get("dst_is_id"):
                v, w = idx.get((src, dst), ("", ""))
                verb, why = (v or "uses"), w
            else:
                verb = "uses"
        out.append({
            "n": st.get("n"),
            "srcId": src_id, "src": str(graph["nodes"][src]["name"]) if src_id else src,
            "dstId": dst_id, "dst": str(graph["nodes"][dst]["name"]) if dst_id else dst,
            "verb": verb, "why": why, "note": str(st.get("note") or "").strip(),
            "where": str(st.get("where") or "") or None,  # the step's own call site (THE location)
            # A step that RUNS A SHARED SUB-USE CASE (None on every other step). `sf` is the walk this step
            # goes into, and it is also the box the map draws the arrow to — so the panel, the map and
            # the sequence column all name the same thing from this one field.
            "sf": st.get("sf"), "sfName": st.get("sfName"),
            "sfSteps": st.get("sfSteps"), "sfChips": st.get("sfChips") or [],
        })
    return out


def flow_maps(graph: GraphDict) -> dict[str, str]:
    """{uc_id: flowchart} for every T6 flow — the map rendering the use-case view toggles to."""
    return {str(f["uc"]): gen_flow_map_mermaid(graph, f) for f in all_walks(graph)}


def flow_narratives(graph: GraphDict) -> dict[str, list[dict[str, Any]]]:
    """{uc_id: [narrative step, …]} for every walk — the readable companion to flow_maps."""
    return {str(f["uc"]): flow_narrative(graph, f) for f in all_walks(graph)}


def flow_actors(graph: GraphDict, flow: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-actor (Role) participants in one use-case flow, in the SAME `FAn` alias order the map
    assigns them, so the viewer's actor lifeline lines up with its rendered `data-id`. Mirrors hp_actors
    for the Happy Path, scoped to this one flow: each actor links back to its Roles-table entry (kind +
    wants) and lists which of THIS flow's own steps it drives — `stepIdx` indexes the SAME filtered,
    ordered step list flow_narrative returns (== the viewer's FLOWS_NARR[uc]), so the two stay in
    lockstep. A role can drive more than one step (e.g. it also receives the final reply).
    Role-ness comes from the SHARED `is_role_endpoint` rule, so the aliases handed out here are exactly
    the ones the two diagram generators draw. (This used to be a local predicate that also treated a
    DANGLING id as a role; the diagrams never did, so on a draft map carrying one, every alias after it
    named a different participant here than on the diagram — see is_role_endpoint.)"""
    steps = own_steps(graph, flow)  # the SAME index space as flow_narrative and the map

    roles_by_name = _roles_by_name(graph)
    order: dict[str, str] = {}  # role display name -> alias (FAn), first-appearance order
    for st in steps:
        for tok, is_id in ((str(st["src"]), bool(st.get("src_is_id"))), (str(st["dst"]), bool(st.get("dst_is_id")))):
            if is_role_endpoint(is_id):
                order.setdefault(tok, "FA" + str(len(order)))
    #: The people this flow took to an agent-facing surface — the SAME answer both pictures label
    #: with, from the one function, so a lifeline and a node cannot disagree.
    clients = flow_client_roles(graph, steps)
    out: list[dict[str, Any]] = []
    for name, aid in order.items():
        idxs = [i for i, st in enumerate(steps)
                if (is_role_endpoint(bool(st.get("src_is_id"))) and str(st["src"]) == name)
                or (is_role_endpoint(bool(st.get("dst_is_id"))) and str(st["dst"]) == name)]
        role = roles_by_name.get(name.strip().lower())
        out.append({
            "aid": aid,
            "name": name,
            #: What the picture actually prints for this actor — the name, plus what they came
            #: through when that is worth saying. The viewer matches its bottom-of-diagram figure on
            #: rendered TEXT, so it needs the label and not only the name.
            "label": name + (CLIENT_LABEL_TEXT if name in clients else ""),
            "kind": str(role["kind"]) if role else "",
            "wants": str(role["wants"]) if role else "",
            "stepIdx": idxs,
        })
    return out


def flow_actors_map(graph: GraphDict) -> dict[str, list[dict[str, Any]]]:
    """{uc_id: [actor, …]} for every T6 flow — the flow-level companion to hp_actors, one list per flow."""
    return {str(f["uc"]): flow_actors(graph, f) for f in all_walks(graph)}


def merged_graph(graph: GraphDict) -> dict[str, Any]:
    """A copy of the graph the panel's extra nodes (context, deployment) are added to."""
    return cast("dict[str, Any]", copy.deepcopy(graph))


def gen_channel_mermaids(graph: GraphDict) -> dict[str, str]:
    """Per-broker async flowchart (LR): publisher components → channel → consumer components, with the
    channel's kind + payload entity noted on the channel node. ONE diagram per broker carrying ≥2
    channels (a single-channel broker is fully described by its card — no diagram earns its keep).
    Keyed by broker dep id. Component nodes keep their C-id so the viewer binds a click→navigate;
    channel nodes are synthetic (`CH_<i>`) labels. Deterministic: brokers + channels in data_view
    order, component nodes emitted in sorted id order."""
    dv = cast("dict[str, Any]", graph.get("data_view") or {})
    out: dict[str, str] = {}
    for store in dv.get("stores", []):
        channels = store.get("channels", [])
        if len(channels) < 2:
            continue
        lines = ["flowchart LR"]
        comp_names: dict[str, str] = {}
        for i, ch in enumerate(channels):
            cid = f"CH_{i}"
            sub = str(ch.get("kind") or "channel")
            payload = ch.get("payload_name") or ""
            if payload:
                sub += f" · {payload}"
            lines.append(f'  {cid}["{_safe_label(str(ch["name"]))}<br/>{_safe_label(sub)}"]:::chan')
            for p in ch.get("publishers", []):
                comp_names[p["id"]] = p["name"]
                lines.append(f'  {p["id"]} --> {cid}')
            for c in ch.get("consumers", []):
                comp_names[c["id"]] = c["name"]
                lines.append(f'  {cid} --> {c["id"]}')
        for c in sorted(comp_names):
            lines.append(f'  {c}["{_safe_label(comp_names[c])}"]:::comp')
        lines.append(f"  classDef chan {INFRA_BUS_STYLE};")
        lines.append(f"  classDef comp {COMPONENT_STYLE};")
        out[str(store["dep"])] = "\n".join(lines)
    return out


class ViewBundle(TypedDict):
    """All the per-project view data the frontend needs — the graph plus every pre-rendered diagram
    source, edge-crossing list, flow, colour table, and config flag. Built from the model by
    `build_view_bundle` and served as JSON by `coyomap serve` at /coyomap/<slug>/api/view; the frontend
    fetches it and renders.

    Keys are the viewer's own vocabulary (camelCase); the frontend maps them onto its runtime state
    (see viewer.js `applyBundle` — keep the two in step).
    """
    repoRoot: str
    repoState: str                 # 'ok' | 'no-repo' | 'no-commit' — can the viewer read this map's code?
    #: True only in a STATIC EXPORT (`coyomap export`) — a folder of files on a web host with no
    #: coyomap server behind it. The builder always writes False; the export flips it. It is what
    #: tells the page not to offer the things only a live server with git can answer.
    exported: bool
    ghRepo: str | None
    ghCommit: str | None
    graph: dict[str, Any]          # the MERGED graph (base+diff, with Context nodes added)
    mermaidBase: str
    mermaidContext: str
    mermaidContainer: str
    mermaidBySub: dict[str, str]
    mermaidEdgeCard: dict[str, str]
    containerEdges: dict[str, list[dict[str, str]]]
    mermaidDomain: str
    mermaidDomainContainer: str
    mermaidDomainSub: dict[str, str]
    mermaidDomainEdgeCard: dict[str, str]
    entityFieldLinks: dict[str, list[dict[str, Any]]]  # entity id -> its entity-typed field
                                   # links ({i, type, target}); drives the clickable type
                                   # word on a class box (see entity_field_links)
    entityStoreLinks: dict[str, dict[str, Any]]      # entity id -> its store line's link into the
                                   # Data tab ({i, text, dep}); see entity_store_links
    mermaidBridgeCard: dict[str, str]
    bridgeEdges: list[dict[str, str]]
    domainContainerEdges: dict[str, list[dict[str, str]]]
    mermaidDeployment: str
    deploymentCards: dict[str, str]
    deploymentGroupCards: dict[str, str]      # product-area container id -> its members' diagram
    deploymentGroupMembers: dict[str, list[str]]  # container id -> the unit names inside it
    deploymentEdges: dict[str, list[dict[str, str]]]  # process→process arrow 'U_a>U_b' -> the async
                                     # channels it carries (the arrow's select panel)
    deploymentInfraEdges: dict[str, list[dict[str, str]]]  # process→infra arrow 'U_a>D_n' -> the
                                     # component→dep calls behind it (same panel idiom)
    deploymentCallEdges: dict[str, list[dict[str, str]]]  # process→process arrow 'U_a>U_b' -> the
                                     # synchronous cross-process calls behind it
    deploymentEnvironments: list[str]
    hasDeployment: bool
    hasBusinessRules: bool         # the map states at least one business rule (T7) — gates the tab
    hasInterfaces: bool            # the map records at least one interface (T2b) — gates the tab
    flowsMap: dict[str, str]      # uc-id (and SFn) -> its walk map — the ONE picture of a walk
    flowsNarr: dict[str, list[dict[str, Any]]]
    hpActors: list[dict[str, Any]]
    flowActors: dict[str, list[dict[str, Any]]]
    elementTint: dict[str, dict[str, str]]
    #: {SFn: [chip, …]} — the people, doors and records inside each shared sub-use case, so the
    #: viewer can wear them on that walk's collapsed box without re-deriving the join.
    subflowChips: dict[str, list[dict[str, str]]]
    mermaidLibs: str
    foldedLibs: list[dict[str, str]]
    mermaidByBucketFold: dict[str, str]
    foldedBuckets: list[dict[str, Any]]
    contextEdges: dict[str, dict[str, Any]]
    hasGrouping: bool
    hasDomain: bool
    hasSubdomains: bool
    hasHp: bool
    mermaidChannels: dict[str, str]  # per-broker async flowchart (dep id → source), for brokers with
                                     # ≥2 channels; rendered inside the Data tab's broker pane
    meta: str                      # the header meta line (HTML)
    features: dict[str, Any]       # the feature-led derivation (coyomap.features.as_bundle): what
                                   # each feature owns, the inverse lookups and the coverage
                                   # line. `{}` when no model could be read beside the graph.


def owner_records(m: ProjectModel) -> dict[str, str]:
    """Per data area, the reason its author RECORDED for an ownership claim no step reaches.

    THE VIEWER'S READER IS NOT THE VALIDATOR'S. A recorded line silences `validate`, whose audience
    is the build lead; the person reading the Features page never sees that record and is still shown
    a claim with nothing behind it. A recorded gap is still a gap — so the page marks it anyway, and
    this is what lets it also say WHY, in the author's own words, instead of leaving the reader to
    guess whether anybody has looked.

    Parsed HERE rather than in the browser, through `records` — the module that exists to be the one
    reader of the `<key>: <why>` line shape, after four separate parsers each silently over-suppressed
    in their own way. A fifth in JavaScript would be the fifth scar. Same heading and same key
    vocabulary as `validate`'s own skip, so the two can never disagree about which areas are answered.

    `{}` when the map records nothing, which is most maps."""
    spec = records.spec_of(DATA_OWNER_EXCEPTIONS_HEADING)
    if spec is None or spec.key is None:
        return {}
    out: dict[str, str] = {}
    for line in records.lines(m, DATA_OWNER_EXCEPTIONS_HEADING):
        why = records.why_of(DATA_OWNER_EXCEPTIONS_HEADING, line)
        if not why:
            continue
        for key in records.keys_on_line(line, spec.key, spec.seps, spec.lead, spec.strict_multi):
            out[key] = why
    return out


def build_view_bundle(graph: GraphDict, anchor: Path,
                      model: ProjectModel | None = None,
                      extents: Extents | None = None) -> ViewBundle:
    """Compute every derived view artifact for one map — the pure-data core that `coyomap serve`
    exposes at /coyomap/<slug>/api/view for the frontend to fetch and render.

    `model` and `extents` feed the feature-led derivation, which needs the model itself rather
    than the graph projected from it. A caller holding both passes them (the server does);
    otherwise they are read from `anchor`, and a map that cannot be read there ships an EMPTY
    `features` block rather than failing the whole bundle — the viewer must still open a map
    whose folder the server cannot fully read, which is the case this whole function is called
    per request to survive.

    `anchor` is the directory that source links resolve against (the map's `.coyomap/` folder): the
    repo root + GitHub URL are derived from the git work tree around it, overridable in the viewer's
    Settings. Nothing here touches the output file or the frontend assets, so it is safe to call per
    request.
    """
    if model is None:
        map_json = anchor / 'project-map.json'
        try:
            model = load_model(map_json.read_text(encoding='utf-8'))
            if extents is None:
                extents = load_map_extents(map_json)
        except (OSError, ModelError):
            model = None
    feature_block: dict[str, Any] = as_bundle(build_index(model, extents)) if model else {}
    # The recorded answers ride ALONGSIDE the derivation rather than inside it: `as_bundle` is the
    # feature-led derivation of the MAP, and a recorded exception is the author's note about the
    # map's own build record. The Features page joins the two by area id.
    if model and feature_block:
        feature_block["ownerRecords"] = owner_records(model)
    base_mm = gen_mermaid(graph)
    context_mm = gen_context_mermaid(graph)
    context_edges = gen_context_edges(graph)
    # Source-link config, derived from the mapped repo (the anchor dir sits inside its work tree).
    # Seeded into the viewer; the user can override the root / GitHub URL in Settings (localStorage).
    repo_root = repo_root_default(anchor)
    gh_repo = gh_repo_url(anchor)
    gh_commit = graph["commit"]
    # Repo root name in the header — so the map plainly states which repo its file links resolve into.
    repo_name = Path(repo_root).name or repo_root
    repo_tag = f'<strong class="repo" title="{html_escape(repo_root, quote=True)}">{html_escape(repo_name)}</strong> · '
    commit = graph['commit'] or 'unknown'
    # The pin reads `commit <sha> <date> <time>` — no "from", which read as if the SHA came from
    # the date. The time is resolved from git (commit_stamp); the stored date is the fallback.
    stamp = commit_stamp(anchor, graph.get('commit'), graph.get('committed'))
    meta = f"baseline @ commit <code>{commit}</code>" + (f" {html_escape(stamp)}" if stamp else "")
    built = graph.get('built')
    if built:
        meta += f" · built {html_escape(built)}"
    # The map's `format` ("coyomap-map") is deliberately NOT shown: it is the same literal on every
    # map ever written, so it told a reader nothing about the map in front of them. It stays in the
    # model, where the loader checks it.
    meta = repo_tag + meta
    grouping = has_grouping(graph)
    domain = has_domain(graph)
    subdomains = has_subdomains(graph)
    hp = has_hp(graph)
    deployment = has_deployment(graph)
    mg = merged_graph(graph)
    add_context_nodes(mg, graph)
    if deployment:
        add_deployment_nodes(mg, graph)
        annotate_unit_dep_facts(mg, graph)
        annotate_run_by(mg, graph)
    return ViewBundle(
        repoRoot=repo_root, repoState=repo_state(anchor, graph.get('commit')), exported=False,
        ghRepo=gh_repo, ghCommit=gh_commit,
        graph=mg,
        mermaidBase=base_mm, mermaidContext=context_mm,
        mermaidContainer=gen_container_mermaid(graph) if grouping else "",
        mermaidBySub=subsystem_component_mermaids(graph) if grouping else {},
        mermaidEdgeCard=edge_card_mermaids(graph) if grouping else {},
        containerEdges=gen_container_edges(graph) if grouping else {},
        mermaidDomain=gen_domain_mermaid(graph) if domain else "",
        mermaidDomainContainer=gen_domain_container_mermaid(graph) if subdomains else "",
        mermaidDomainSub=domain_subdomain_mermaids(graph) if subdomains else {},
        mermaidDomainEdgeCard=domain_edge_card_mermaids(graph) if subdomains else {},
        entityFieldLinks=entity_field_links(graph) if domain else {},
        entityStoreLinks=entity_store_links(graph) if domain else {},
        mermaidBridgeCard=bridge_card_mermaids(graph) if (grouping and subdomains) else {},
        bridgeEdges=gen_bridge_edges(graph) if (grouping and subdomains) else [],
        domainContainerEdges=gen_domain_container_edges(graph) if subdomains else {},
        mermaidDeployment=gen_deployment_mermaid(graph) if deployment else "",
        deploymentCards=deployment_cards(graph) if deployment else {},
        deploymentGroupCards=deployment_group_cards(graph) if deployment else {},
        deploymentGroupMembers=deployment_group_members(graph) if deployment else {},
        deploymentEdges=gen_deployment_edges(graph) if deployment else {},
        deploymentInfraEdges=gen_deployment_infra_edges(graph) if deployment else {},
        deploymentCallEdges=gen_deployment_call_edges(graph) if deployment else {},
        deploymentEnvironments=deployment_environments(graph) if deployment else [],
        hasDeployment=deployment,
        hasBusinessRules=bool((graph.get("rules_view") or {}).get("rules")),
        hasInterfaces=bool(model is not None and model.interfaces),
        # Flows are independent of the Happy Path — the use-case view needs them even with no HP — so
        # they come from graph["flows"] directly (empty when the map has no T6 section).
        flowsMap=flow_maps(graph),
        flowsNarr=flow_narratives(graph),
        hpActors=hp_actors(graph) if hp else [],
        flowActors=flow_actors_map(graph),
        elementTint=ELEMENT_TINT,
        subflowChips=subflow_chips(graph),
        mermaidLibs=gen_libs_mermaid(graph),
        foldedLibs=folded_libs(graph),
        mermaidByBucketFold=mermaid_by_bucketfold(graph),
        foldedBuckets=folded_buckets_roster(graph),
        contextEdges=context_edges,
        hasGrouping=grouping, hasDomain=domain, hasSubdomains=subdomains, hasHp=hp,
        mermaidChannels=gen_channel_mermaids(graph),
        meta=meta, features=feature_block,
    )


def main(argv: list[str] | None = None) -> int:
    """Two-stage debug entry: dump the view bundle (the JSON the frontend fetches) for a graph.json.

        python -m coyomap.viewer.gen_viewer [graph.json] [view-bundle.json]
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    src = Path(argv[0] if len(argv) > 0 else "build/graph.json")
    out = Path(argv[1] if len(argv) > 1 else "build/view-bundle.json")
    if not src.exists():
        print(f"ERROR: {src} not found (build the graph first)", file=sys.stderr)
        return 1
    graph = cast(GraphDict, json.loads(src.read_text(encoding="utf-8")))
    bundle = build_view_bundle(graph, out.resolve().parent)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(f"Wrote view bundle -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
