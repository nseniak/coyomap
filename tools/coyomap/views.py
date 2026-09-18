#!/usr/bin/env python3
"""Generated views of the model: model → markdown, and model → graph (the viewer's input).

The markdown view is the READABLE, COMMITTED rendering of `project-map.json` (canonical section
order, template-shaped tables, deterministic output) — never hand-edited; `coyomap validate` warns
when the committed copy is stale. The graph view feeds the viewer bundle builder
(`gen_viewer.build_view_bundle`, served by `coyomap serve`) its `GraphDict` input, built straight
from the model.

Stdlib-only. Both functions are pure (same model → same bytes).
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict

from coyomap import grammar, records
from coyomap.model import (
    record_parents,
    BusinessRule,
    Component,
    Dep,
    Entity,
    EvidenceItem,
    FlowStep,
    Group,
    ProjectModel,
    RuleSite,
    StateMachine,
    Store,
    TestRow,
    all_elements,
)
from coyomap.validate_analysis import strip_anchor
from coyomap.impact_git import Extents
from coyomap.validate_model import (
    STEP_LINK_EXACT,
    anchored_flow_steps,
    capability_elements,
    completeness_counts,
    component_file_owners,
    capability_audience,
    element_capabilities,
    interface_actors,
    interface_directions,
    rule_components,
    rule_entities,
    rule_steps,
    rules_swept,
    site_components,
    unexplained_persistence_pairs,
)
from coyomap.viewer.build_graph import (
    ExtraSectionView,
    LINK,
    Edge as GraphEdge,
    HappyStep as GraphHappyStep,
    GraphDict,
    Node,
    TestTarget,
    _ensure_default_subsystem,
    _line_of,
    _role_kind,
)

# ── markdown view ────────────────────────────────────────────────────────────────────────────────

_GENERATED_NOTICE = (
    "<!-- GENERATED VIEW — do not edit. The source of truth is project-map.json; regenerate this\n"
    "     file with `coyomap render project-map.json project-map.md`. -->")


def and_list(items: list[str]) -> str:
    """`X` · `X and Y` · `X, Y, and Z` — a name list a reader parses as PLURAL. A bare comma join reads
    as one long name: a use case with two interchangeable initiators rendered as "Team member,
    Organization admin", which every view then treated as a single unknown actor. The conjunction is
    what makes the plurality visible, so it is used everywhere an actor list is displayed (the markdown
    Use cases table and the viewer's `Actor` field alike) — one spelling, no drift between views."""
    xs = [i for i in items if i]
    if len(xs) < 2:
        return xs[0] if xs else ""
    if len(xs) == 2:
        return f"{xs[0]} and {xs[1]}"
    return ", ".join(xs[:-1]) + ", and " + xs[-1]


def _esc(cell: str) -> str:
    """A model text value as a table cell: literal pipes re-escaped (the schema rule), newlines
    flattened so one row stays one line."""
    return cell.replace("|", r"\|").replace("\n", " ").strip()


def _extra_str(v: object) -> str:
    """An `extra` value as display text: a string passes through; any other JSON value (the model
    accepts them in `extra`) renders as compact JSON."""
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(_esc(c) for c in cells) + " |"


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    sep = "|" + "|".join("---" for _ in headers) + "|"
    return [_row(headers), sep] + [_row(r) for r in rows]


def _source_line(source: str) -> str:
    """A card SOURCE line from the stored href: labelled with the file's basename (its line anchor
    stripped — leaving it in would mislabel `path:line` as `basename:line` instead of `basename`)."""
    label = strip_anchor(source).rsplit("/", 1)[-1] or source
    return f"SOURCE: [{label}]({source})"


def _anchor_link(href: str | None) -> str:
    """A bare `path:line` anchor (deps[].where_configured, edges[].where,
    entry_points[].source) as a markdown-link table cell, labelled with its basename — so the
    generated view stays clickable even though the model itself stores these bare, like
    `Entity.source`."""
    if not href:
        return ""
    label = strip_anchor(href).rsplit("/", 1)[-1] or href
    return f"[{label}]({href})"


def _files_str(paths: list[str]) -> str:
    return " · ".join(paths)


_URL_REF = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)


def _bare_local_file(href: str | None) -> str | None:
    """A bare repo-relative FILE path from a source/anchor href, or None for empty / off-repo /
    directory refs (a directory or URL is not a single openable file). Line anchors are stripped, so
    the result matches the file-browser tree keys."""
    if not href or _URL_REF.match(href):
        return None
    p = strip_anchor(href).strip().strip("/")
    return p if p and not href.rstrip().endswith("/") else None


def _component_files(c: Component) -> list[str]:
    """A component's owned files as bare repo-relative paths — the canonical `source` file first,
    then the rest of `files`, deduped. This is the list the code-viewer switcher pages through."""
    out: list[str] = []
    for f in ([_bare_local_file(c.source)] + [_bare_local_file(f) for f in c.files]):
        if f and f not in out:
            out.append(f)
    return out


def _evidence_str(items: list[EvidenceItem]) -> str:
    """`evidence` as a table cell: one clickable anchor + its why per citation, `·`-separated.
    A blank `why` (allowed for a test suite whose dir name speaks for itself) drops the ` — `."""
    return " · ".join(f"{_anchor_link(ev.file)} — {ev.why}" if ev.why.strip() else _anchor_link(ev.file)
                      for ev in items)


def _resolve_targets(row: TestRow, elems: Mapping[str, object], nodes: Mapping[str, object]) -> list[TestTarget]:
    """A test row's `targets` ids → `{id, name, node}`, resolved server-side (no prose parsing). `name`
    is the defined element's name (falls back to the id when unresolved); `node` is the id when it is a
    drawn diagram node — the viewer makes that clickable to locate the element — else None."""
    out: list[TestTarget] = []
    for tid in row.targets:
        out.append({"id": tid, "name": _element_label(elems.get(tid), tid), "node": tid if tid in nodes else None})
    return out


#: An element id inside authored prose. `grammar.ID_TOKEN` plus `Rn`: a role is a defined element the
#: records key on ("Rn: a role deliberately without a spine position") even though it is not a drawn
#: diagram node, and the whole point of resolving here is that the reader sees its NAME.
_PROSE_ID = re.compile(r"\b(?:CAP\d+|EP\d+|UC\d+|HP\d+|SD\d+|SF\d+|BLK\d+|BR\d+|R\d+|C\d+|D\d+|E\d+|I\d+|S\d+)\b")


def _extra_refs(body: str, elems: Mapping[str, object],
                nodes: Mapping[str, object]) -> dict[str, TestTarget]:
    """Every element id this authored body names → `{id, name, node}`, resolved SERVER-SIDE.

    Recorded lines are keyed by id, and on the live maps 60-78% of them opened with one — so this is
    the one place the viewer would otherwise print raw ids, against its own rule that ids stay
    internal and names go on screen. Resolution happens here, against the real element table, for a
    reason the first attempt found the hard way: resolving in the browser against the DIAGRAM's node
    map read `R3` as the fourth role, because the Context diagram used to mint its own zero-based
    `R0, R1, …` actor nodes, whose id space collided with the model's roles (they are `ACT<n>` now). `name` comes from the model;
    `node` is the id only when it is a drawn node, so a role renders as a name and a component as a
    link."""
    out: dict[str, TestTarget] = {}
    for eid in _PROSE_ID.findall(body or ""):
        if eid in out:
            continue
        el = elems.get(eid)
        if el is not None:   # an id the map does not define is left exactly as written
            out[eid] = {"id": eid, "name": _element_label(el, eid),
                        "node": eid if eid in nodes else None}
    return out


def _element_label(el: object, fallback: str) -> str:
    """A defined element's human name for display — `name` (most elements), `term` (glossary),
    or `title` (a happy-path step) — falling back to the id when the element is unknown."""
    return str(getattr(el, "name", None) or getattr(el, "term", None)
               or getattr(el, "title", None) or fallback)


def _targets_label(row: TestRow, elems: dict[str, object]) -> str:
    """A test row's targets as a Markdown-view cell: the resolved element names, prefixed by the
    row's optional grouping `label`."""
    joined = ", ".join(_element_label(elems.get(t), t) for t in row.targets)
    if row.label and joined:
        return f"{row.label} ({joined})"
    return row.label or joined


def _relation_item(r) -> str:
    parts = [r.verb]
    if r.src_card and r.dst_card:
        parts.append(f"{r.src_card}→{r.dst_card}")
    parts.append(r.target)
    if r.display:
        parts.append(r.display)
    if r.keyed_by:
        # a storage key, shown with the «key» marker (comma-joined — never `·`, the relation
        # separator); mirrors the canvas arrow label so the text view reads the same.
        parts.append("«key» " + ", ".join(r.keyed_by))
    if r.how:
        parts.append("{" + r.how + "}")
    return " ".join(parts)


def _states_parts(sm: StateMachine | None) -> list[str]:
    """A state machine as its INDIVIDUAL parts — one `a → b (on x)` per transition, or the plain
    state names when it declares none. The single source both renderings share: `_states_str` joins
    them for the one-line markdown card, while the info pane lists them one per line (a real machine
    runs to several transitions, each carrying its own trigger prose — joined up they read as an
    unparseable paragraph)."""
    if sm is None:
        return []
    if not sm.transitions:
        return list(sm.states)
    return [f"{t.src} → {t.dst}" + (f" (on {t.on})" if t.on else "") for t in sm.transitions]


def _states_str(sm: StateMachine | None) -> str:
    """The one-LINE text rendering of a state machine — the markdown domain card's STATES line, and
    the info pane's fallback when the node carries no structured parts. `_states_parts` joined by
    ` · `; a transition-less machine lists the state names."""
    return " · ".join(_states_parts(sm))


def _store_str(st: Store | None) -> str:
    """The ONE human rendering of a structured store — shared by the domain-card parenthetical and
    the entity pane's "Stored" row, so the two can never phrase the same store differently.
    `D1.guilds — collection; 30-day TTL` (dep.container — mode; notes), degrading gracefully when
    parts are unstated (a notes-only store renders just its notes)."""
    if st is None:
        return ""
    place = f"{st.dep}.{st.container}" if st.dep and st.container else (st.dep or st.container)
    head = f"{place} — {st.mode}" if place and st.mode else (place or st.mode)
    if head and st.notes:
        return f"{head}; {st.notes}"
    return head or st.notes


def _component_headers(m: ProjectModel) -> tuple[list[str], bool, list[str]]:
    """T1's column set: the canonical five, plus Conf./Files/Evidence when any component states one,
    plus the union of authored extra columns (sorted — deterministic).

    NO "ENTRY POINT" COLUMN. It held a `path:line` — where a component's code STARTS — and `source`
    replaced it: every reader of it was a fallback behind `source`, and on all five live maps every
    component carrying it carried a `source` too, so the fallback never once fired. It also collided
    head-on with the T4 rows this map calls entry points, which are ways in and not code lines at
    all: a component's page printed "Entry point: cli.py:139" a few lines above "Triggered by · 10
    ways in", one word meaning two things on one screen."""
    with_conf = any(c.confidence for c in m.components)
    extra = sorted({k for c in m.components for k in c.extra})
    headers = ["ID", "Component", "Subsystem", "Purpose", "Depends on"]
    if with_conf:
        headers.append("Conf.")
    if any(c.files for c in m.components):
        headers.append("Files")
    if any(c.evidence for c in m.components):
        headers.append("Evidence")
    if any(c.runs_in for c in m.components):
        headers.append("Runs in")
    return headers + extra, with_conf, extra


def _dep_headers(m: ProjectModel) -> tuple[list[str], bool, list[str]]:
    linked = any(d.deployment_linked for d in m.deps)
    extra = sorted({k for d in m.deps for k in d.extra})
    headers = ["ID", "Name", "Kind", "Bucket", "Type", "Used for", "Where configured", "Conf."]
    if linked:
        headers.append("Deployment-linked")
    if any(d.package for d in m.deps):
        headers.append("Package")
    if any(d.alternative for d in m.deps):
        headers.append("Alternative")
    if any(d.evidence for d in m.deps):
        headers.append("Evidence")
    return headers + extra, linked, extra


def model_to_markdown(m: ProjectModel) -> str:
    """The canonical markdown view. Sections render in the template's order; an empty section is
    omitted (a small map without subsystems reads exactly like any other small map)."""
    out: list[str] = [f"# {m.title} — Codebase Analysis" if m.title else "# Codebase Analysis", ""]
    out += [_GENERATED_NOTICE, ""]
    out += ["> Built with the **coyomap** method. Behavioral layer first (Goal → Glossary → Roles →",
            "> Use cases → Happy Path), then the structural machine (Components → Entry points /",
            "> Model / Deps → Flows + Edges), joined at **use case ↔ flow**.",
            "> The committed source of truth is `project-map.json` (JSON); this file is a generated",
            "> view. IDs, cross-references, and confidence tags are validated by",
            "> `coyomap validate project-map.json`."]
    pin = []
    if m.commit:
        pin.append(f"**Commit:** `{m.commit}`")
    if m.committed:
        pin.append(f"**Committed:** `{m.committed}`")
    if m.built:
        pin.append(f"**Built:** `{m.built}`")
    if pin:
        out.append("> " + " · ".join(pin))
    out.append("")

    def section(title: str, body: list[str]) -> None:
        out.extend(["---", "", f"## {title}", ""] + body + [""])

    if m.goal:
        section("T0 — Goal (the anchor)", [m.goal])
    if m.glossary:
        section("Glossary — the ubiquitous language",
                _table(["Term", "Meaning", "Defined / used in"],
                       [[f"**{g.term}**", g.meaning, _anchor_link(g.source)] for g in m.glossary]))
    if m.roles:
        section("Roles (actors)",
                ["`Audience` says WHICH SIDE this actor is on: `internal` = the side of the company "
                 "that ships the product,", "`user` = everyone else. On a program it is whose "
                 "machine it is, so a bought service is `internal`.",
                 "Every capability's audience is derived from it.", ""]
                + _table(["Role", "Kind", "Audience", "What they want", "Use cases they drive"],
                         [[f"**{r.name}**", r.kind, r.audience, r.wants, r.drives]
                          for r in m.roles]))
    if m.capabilities:
        cap_parent = {c.id: c.name for c in m.capabilities}
        cap_audience = capability_audience(m)
        section("Capabilities — what this product does",
                ["The use-case grouping. `Audience` is DERIVED from the roles driving its use "
                 "cases, so nothing on a capability can contradict its own actors.", ""]
                # `happy_path` is deliberately absent: it is an authoring decision the Coverage rule
                # reads, and a reader of the map has no use for it. It stays in the model.
                + _table(["ID", "Capability", "Audience", "Purpose", "Parent"],
                         [[f"**{c.id}**", c.name,
                           ", ".join(cap_audience.get(c.id) or ()),
                           c.purpose, cap_parent.get(c.parent or "", "")]
                          for c in m.capabilities]))
    if m.use_cases:
        rn = {r.id: r.name for r in m.roles}  # render actors as role NAMES, resolved from their ids
        if m.capabilities:
            # Grouped by capability — the reader's first question is "what does this product do?",
            # and a flat 25-row table never answered it. One sub-table per capability, in
            # capabilities[] order, with any unassigned use cases last so they are visible rather
            # than silently dropped.
            cap_names = {c.id: c.name for c in m.capabilities}
            uc_body: list[str] = []
            groups = [(c.id, c.name, [u for u in m.use_cases if (u.capability or "") == c.id])
                      for c in m.capabilities]
            loose = [u for u in m.use_cases if (u.capability or "") not in cap_names]
            if loose:
                groups.append(("", "Not assigned to a capability", loose))
            for cid, cname, members in groups:
                if not members:
                    continue
                uc_body += [f"### {cname}" + (f" *({cid})*" if cid else ""), ""]
                uc_body += _table(["ID", "Use case", "Actor", "Trigger", "Outcome"],
                                  [[f"**{u.id}**", u.name,
                                    and_list([rn.get(a, a) for a in u.actors]),
                                    u.trigger, u.outcome] for u in members]) + [""]
            section("Use cases", uc_body)
        else:
            section("Use cases",
                    _table(["ID", "Use case", "Actor", "Trigger", "Outcome"],
                           [[f"**{u.id}**", u.name, and_list([rn.get(a, a) for a in u.actors]),
                             u.trigger, u.outcome] for u in m.use_cases]))
    if m.happy_path:
        body = ["The happy-path ordering of use cases. Each step IS a use case (its `*(UCn)*` tag",
                "names it); the step's detail lives in that use case's T6 flow. An optional `why:`",
                "line records the prerequisite that fixes the step's position.", ""]
        uc_name = {u.id: u.name for u in m.use_cases}
        for hp in m.happy_path:
            # A step has no text of its own: the heading is its use case's name, so the spine
            # reads in the same words as the use-case table above it.
            tag = f" *({hp.uc})*" if hp.uc else ""
            body.append(f"**{hp.id} — {uc_name.get(hp.uc or '', hp.uc or '')}**{tag}")
            if hp.why:
                body.append(f"why: {hp.why}")
        section("Happy Path — the spine (an ordered walk through the use cases)", body)
    if m.subsystems:
        # Tech column only when some subsystem states one (conditional-column rule — existing maps'
        # committed md stays byte-identical). A cited tech shows its manifest anchor inline.
        with_tech = any(s.tech for s in m.subsystems)
        s_headers = ["ID", "Subsystem", "Purpose", "Parent"] + (["Tech"] if with_tech else []) + [
            "Source", "Conf."]
        s_rows = [[f"**{s.id}**", s.name, s.purpose, s.parent or ""]
                  + ([f"{s.tech} ({_anchor_link(s.tech_source)})" if s.tech_source else s.tech]
                     if with_tech else [])
                  + [s.source or "", s.confidence] for s in m.subsystems]
        section("Subsystems (S) — the container altitude", _table(s_headers, s_rows))
    if m.components:
        headers, with_conf, extra = _component_headers(m)
        rows = []
        for c in m.components:
            row = [f"**{c.id}**", c.name, c.subsystem or "", c.purpose,
                   c.depends_on]
            if with_conf:
                row.append(c.confidence)
            if "Files" in headers:
                row.append(_files_str(c.files))
            if "Evidence" in headers:
                row.append(_evidence_str(c.evidence))
            if "Runs in" in headers:
                row.append(", ".join(c.runs_in))
            row += [_extra_str(c.extra.get(k, "")) for k in extra]
            rows.append(row)
        section("T1 — Components", _table(headers, rows))
    if m.deps:
        headers, linked, extra = _dep_headers(m)
        rows = []
        for d in m.deps:
            row = [f"**{d.id}**", d.name, d.kind or "", d.bucket, d.type, d.used_for,
                   _anchor_link(d.where_configured), d.confidence]
            if linked:
                row.append("yes" if d.deployment_linked else "")
            if "Package" in headers:
                row.append(d.package)
            if "Alternative" in headers:
                row.append(d.alternative)
            if "Evidence" in headers:
                row.append(_evidence_str(d.evidence))
            row += [_extra_str(d.extra.get(k, "")) for k in extra]
            rows.append(row)
        section("T2 — External dependencies", _table(headers, rows))
    # T2b — the product's OUTSIDE EDGE. The committed markdown is the half of the map a person reads
    # in the repo, and it carried 23 sections and no interfaces at all: the section existed in the
    # model, was checked by `validate`, drew its own tab in the viewer, and was invisible in the file
    # the map is actually committed as.
    if m.interfaces:
        ways_by_iface = {i.id: len(i.ways_in) for i in m.interfaces}
        deps_by_iface: dict[str, list[str]] = {}
        for d in m.deps:
            for iid in d.interfaces:
                deps_by_iface.setdefault(iid, []).append(d.id)
        # `Kind` is the SHAPE the map authored; `Actors` is DERIVED and appears nowhere else in the
        # committed file. Both are columns rather than a second section: the row is the surface, and
        # a reader answering "which of my products has a mobile app?" reads down one column.
        actors_by_iface = interface_actors(m)
        # "Crosses" is DERIVED from the directions this surface's walk steps carry — the successor
        # to the removed `carries[]` rows, and now the map's only answer.
        dirs_by_iface = interface_directions(m)
        rows = []
        for i in m.interfaces:
            flow = ", ".join(dirs_by_iface.get(i.id, ()))
            rows.append([f"**{i.id}**", i.name, i.side, grammar.canonical_interface_kind(i.kind),
                         i.facing, flow, i.what,
                         ", ".join(actors_by_iface.get(i.id, [])),
                         str(ways_by_iface.get(i.id) or ""),
                         ", ".join(deps_by_iface.get(i.id, [])),
                         _anchor_link(i.source), i.confidence])
        section("T2b — Interfaces (the product's outside edge)",
                _table(["ID", "Name", "Side", "Kind", "Facing", "Crosses", "What it is",
                        "Actors", "Ways in", "Deps", "Source", "Conf."], rows))
        # The "What crosses each interface" table went with `carries[]`. What a surface carries is
        # now its walk steps, which the viewer draws grouped by the story they belong to; a flat
        # table here would repeat T6 in a worse order.
    if m.run_commands:
        section("T3 — How to run / build / test",
                _table(["Action", "Command", "Source"],
                       [[r.action, r.command, r.source] for r in m.run_commands]))
    if m.entry_points:
        # Cadence column only when any row states one (the `_component_headers` conditional-column
        # rule) — maps without cadences keep their committed T4 byte-identical.
        with_cadence = any(e.cadence for e in m.entry_points)
        headers = ["Kind", "Trigger", "Code entity", "Component"] + (
            ["Cadence"] if with_cadence else [])
        rows = [[e.kind, e.trigger, _anchor_link(e.source), e.component]
                + ([f"{e.cadence} ({_anchor_link(e.cadence_source)})" if e.cadence_source
                    else e.cadence] if with_cadence else [])
                for e in m.entry_points]
        section("T4 — Entry points", _table(headers, rows))
    if m.subdomains:
        section("Subdomains (SD) — bounded contexts of the domain model",
                _table(["ID", "Subdomain", "Purpose", "Parent", "Source", "Conf."],
                       [[f"**{s.id}**", s.name, s.purpose, s.parent or "", s.source or "",
                         s.confidence] for s in m.subdomains]))
    if m.entities:
        body: list[str] = []
        for e in m.entities:
            store = f" *({_store_str(e.store)})*" if e.store else ""
            body.append(f"**{e.id} — {e.name}**{store}")
            if e.subdomain:
                body.append(f"SUBDOMAIN: {e.subdomain}")
            if e.meaning:
                body.append(f"MEANING: {e.meaning}")
            if e.fields:
                body.append("FIELDS: " + " · ".join(
                    " ".join([f"{f.name}:{f.type}"] + f.markers).rstrip() for f in e.fields))
            if e.relations:
                body.append("RELATIONS: " + " · ".join(_relation_item(r) for r in e.relations))
            if e.states:
                sm_src = f" — {_anchor_link(e.states.source)}" if e.states.source else ""
                body.append(f"STATES: {_states_str(e.states)}{sm_src}")
            if e.source:
                body.append(_source_line(e.source))
            body.append("")
        section("T5 — Domain model (domain cards)", body[:-1] if body else body)
    if m.non_entity_types:
        section("Non-entity types (plumbing, deliberately unmodelled)",
                _table(["Type", "Source", "Why"],
                       [[t.name, t.source or "", t.why] for t in m.non_entity_types]))
    if m.flows or m.subflows:
        rn = {r.id: r.name for r in m.roles}  # an actor step carries a role id → show the role NAME
        sfn = {sf.id: sf.name for sf in m.subflows}

        def _ep(x: str) -> str:
            return rn.get(x, x) if grammar.is_role_id(x) else x

        def _step_line(st: FlowStep) -> str:  # ONE step-line writer, shared by flows and sub-flows
            line = f"{st.n}. {_ep(st.src)} → {_ep(st.dst)}"
            if st.phrase:
                line += f" : {st.phrase}"
            if st.subflow:  # a reference step: the included run, named inline
                line += f" {'⟨' if st.phrase else ': ⟨'}runs {st.subflow} — {sfn.get(st.subflow, st.subflow)}⟩"
            if st.where:  # the step's own call site (THE location) — rendered as a code link
                line += f" @ {_anchor_link(st.where)}"
            if st.note:
                line += f" · {st.note}"
            return line

        body = []
        for f in m.flows:
            body.append(f"**{f.uc} — {f.title}**")
            body.extend(_step_line(st) for st in f.steps)
            body.append("")
        if m.flows:
            section("T6 — Use-case flows", body[:-1] if body else body)
        if m.subflows:
            body = []
            for sf in m.subflows:
                body.append(f"**{sf.id} — {sf.name}**")
                body.extend(_step_line(st) for st in sf.steps)
                body.append("")
            section("T6b — Sub-flows (shared step sequences, referenced by the flows above)",
                    body[:-1] if body else body)
    if m.rules or m.blocks:
        # T7 — the decision layer. Grouped by block exactly as the use cases are grouped by
        # capability above, trailing "not assigned" group included, so a rule `reconcile` has not
        # placed yet is visible rather than silently dropped.
        #
        # NOTHING HERE IS AUTHORED except the statement, the sites and the block. The components on
        # each site line and the use-case steps under it are DERIVED by
        # `validate_model.site_components` / `rule_steps` — the one implementation, shared with the
        # checks, the viewer transport and the eval. A second copy here is precisely the drift the
        # layer exists to prevent.
        #
        # EXACT step links only. `rule_steps` gains its second strength ("inside the same function
        # as this step") from the pre-index symbol table, and the markdown view is a pure function
        # of the JSON — mixing an optional side file in would make `_check_view_fresh` depend on a
        # file the map does not contain. The viewer, which has the table, shows both.
        owners = component_file_owners(m)
        comp_names = {c.id: c.name for c in m.components}
        anchored = anchored_flow_steps(m)
        uc_names = {u.id: u.name for u in m.use_cases}

        def _site_line(site: RuleSite) -> str:
            why = f" · {site.why}" if site.why else ""
            where = (site.where or "").strip()
            if site.no_call_site and not where:
                return f"- *no call site* — enforced by construction{why}"
            if not where:
                return f"- *no anchor* — this site claims nothing{why}"
            comps = site_components(m, site, owners)
            # EVERY owner, never one: `Component.files` is not disjoint, and on this repo's own map
            # 2% of call-site anchors sit in a file 3-4 components claim.
            who = (", ".join(f"{comp_names.get(c, c)} ({c})" for c in comps)
                   or "*unverified — no component claims this file*")
            # Labelled with the LINE, not the basename `_anchor_link` uses elsewhere: a rule is
            # routinely enforced at several lines of one file, and a list of identical `guard.py`
            # labels hides exactly the thing the site list exists to show.
            line = f"- [{where}]({where}) — {who}{why}"
            # `validate` blocks a site that declares an absence AND cites a line, but `render` runs
            # on unvalidated models — showing one half and dropping the other would turn a
            # contradiction into a clean claim, which is the failure this layer exists to prevent.
            return line + ("  *(also declares `no_call_site` — contradictory)*"
                           if site.no_call_site else "")

        def _step_ref(l) -> str:
            """A step's FULL address. `n` is unique per authoring container, never per use case —
            47 of this repo's 114 anchored steps come from a sub-flow, and 26 `(uc, n)` pairs name
            more than one distinct step. Printing `(UC9) step 3` would point at the wrong row in
            T6b, and two different steps would render as a byte-identical duplicate.

            THE AUTHORED `n` IS RIGHT HERE, and wrong in the viewer. This view does not expand a
            sub-flow: T6 renders the reference step inline and T6b lists the sub-flow under its own
            numbering, so `UC9 → SF50 step 4` is a lookup a reader can follow. The VIEWER splices a
            sub-flow's steps into each referencing flow and numbers the result by POSITION, so a
            chip there must show the position instead (viewer.js `flowStepIndex`). Two views, two
            numbering schemes, each matching what its own reader sees."""
            uc = f"{uc_names.get(l.uc, l.uc)} ({l.uc})"
            return f"{uc} step {l.n}" if l.container == l.uc else f"{uc} → {l.container} step {l.n}"

        body: list[str] = [
            "One decision per rule, with every place it is enforced. The component on each site "
            "line and the",
            "use-case steps under it are DERIVED from the site anchors — no field carries them.", ""]
        def _rule_lines(r: BusinessRule) -> list[str]:
            tags = "".join(f"  *({t})*" for t in (["access"] if r.access else [])
                           + ([r.confidence] if r.confidence else []))
            # Title, then the decision, on ONE line. A second line would be a lazy continuation of
            # this paragraph anyway (markdown joins them), and a blank line between them would put
            # air between a rule and its own sentence. A map written before `name` existed renders
            # exactly as it did — the statement alone, as the heading — so its committed `.md` does
            # not churn on a field the map does not have.
            head = f"{r.name.strip()}** — {r.statement}" if r.name.strip() else f"{r.statement}**"
            lines = [f"**{r.id} — {head}{tags}"]
            lines += [_site_line(site) for site in r.sites]
            # Exact links only, and the filter says so INDEPENDENTLY of `rule_steps` happening to
            # produce none without a symbol table: the view must stay a pure function of the JSON
            # even if a caller later hands this one.
            steps = [l for l in rule_steps(m, r, None, anchored) if l.strength == STEP_LINK_EXACT]
            if steps:
                lines.append("- enforced at: " + " · ".join(_step_ref(l) for l in steps))
            return lines + [""]

        if m.blocks:
            groups = [(b.id, b.name, b.purpose, [r for r in m.rules if (r.block or "") == b.id])
                      for b in m.blocks]
            placed = {b.id for b in m.blocks}
            loose = [r for r in m.rules if (r.block or "") not in placed]
            if loose:
                groups.append(("", "Not assigned to a block", "", loose))
            for bid, bname, purpose, members in groups:
                body += [f"### {bname}" + (f" *({bid})*" if bid else ""), ""]
                if purpose:
                    body += [purpose, ""]
                if not members:
                    # Blocks are minted at synthesis, BEFORE the rules are authored, so an empty one
                    # is a real state — and an invisible one reads as a block nobody minted.
                    body += ["*No rules assigned to this block yet.*", ""]
                for r in members:
                    body += _rule_lines(r)
        else:
            for r in m.rules:
                body += _rule_lines(r)
        section("T7 — Business logic (the decisions this product makes)",
                body[:-1] if body else body)
    access_rules = [r for r in m.rules if r.access]
    if m.deployment or m.observability or m.security or m.config or access_rules:
        body = []
        if m.deployment:
            body += ["### Deployment & topology", ""] + _table(
                ["Unit", "Runs on", "Exposed as", "Config source"],
                [[r.unit, r.runs_on, r.exposed_as, r.config_source] for r in m.deployment]) + [""]
        if m.observability:
            body += ["### Observability", ""] + _table(
                ["Signal", "Where emitted", "Where viewed", "Alerts"],
                [[r.signal, r.where_emitted, r.where_viewed, r.alerts] for r in m.observability]) + [""]
        if m.security or access_rules:
            # DERIVED from T7 where the map has rules: an `access` rule IS a security surface now,
            # and re-typing it into a second table is the two-storages problem this fold ends. A
            # legacy `security[]` row still renders beside them — an un-rebuilt map must not lose
            # its table — with its own kind stated, so a reader can tell which storage each came
            # from and there is no doubt about which one is authoritative.
            rows = [[(f"**{r['id']}** — {r['surface']}" if r["kind"] == "rule"
                      else f"*(legacy row)* {r['surface']}"
                           + (f" — {r['who']}" if r["who"].strip() else "")),
                      " · ".join(f"[{w}]({w})" for w in r["source"].split(" · ") if w)
                      or "*enforced by construction*",
                      r["risk"]] for r in auth_surface_rows(m)]
            lead = ("Derived from the business rules marked `access` (T7) — the decision IS the "
                    "surface." if access_rules else
                    "Legacy `security[]` rows: this map predates the fold and has not been rebuilt.")
            body += ["### Security & auth", "", lead, ""] + _table(
                ["Decision", "Enforced at", "Risk note"], rows) + [""]
        if m.config:
            body += ["### Config & environments", ""] + _table(
                ["Key", "Purpose", "Default", "Per-env / secret?"],
                [[r.key, r.purpose, r.default, r.per_env] for r in m.config]) + [""]
        section("Operational dimensions — the standard core four", body[:-1])
    if m.edges:
        section("Relationships — backbone edge list",
                _table(["From", "Verb", "To", "Why", "Where (example)"],
                       [[e.src, e.verb, e.dst, e.why or "", _anchor_link(e.where)] for e in m.edges]))
    if m.messaging:  # only-when-present: maps without an async catalog keep their md byte-identical
        section("Messaging — channels & queues (the async catalog; participation is claimed by edges)",
                _table(["Name", "Kind", "Broker", "Publishers", "Consumers", "Payload", "Source"],
                       [[f"**{r.name}**", r.kind, r.broker, ", ".join(r.publishers),
                         ", ".join(r.consumers), r.payload, _anchor_link(r.source)]
                        for r in m.messaging]))
    if m.tests or m.tests_note:
        body = []
        if m.tests_note:
            body += [f"> **Tests run for this table?** {m.tests_note}", ""]
        if m.tests:
            elems = all_elements(m)
            body += _table(["Target", "Tested?", "Test(s)", "Gap / risk", "Confidence"],
                           [[_targets_label(t, elems), t.tested, _evidence_str(t.tests), t.gap, t.confidence]
                            for t in m.tests])
        section("Test completeness — gaps against the map", body)
    if m.grounding is not None:
        # The record travelled with the map as JSON and appeared in NO view — so the one number a
        # reader most needs in order to judge every other number was invisible to anyone reading
        # the markdown. It is the map's statement about its own confidence; it belongs on the page.
        g = m.grounding
        body = [f"**{g.claims_challenged} of {g.claims_total} claim(s) challenged** by "
                f"fresh-context skeptics — {g.claims_confirmed} confirmed, {g.claims_refuted} "
                f"refuted, {g.claims_unverifiable} unverifiable. That is the PINNED worklist: the "
                f"claim surface the skeptics were handed.", ""]
        if g.claims_total and g.claims_challenged < g.claims_total:
            body += [f"> Coverage is PARTIAL: {g.claims_total - g.claims_challenged} claim(s) were "
                     f"never challenged. Those are good leads, not facts.", ""]
        # THE SHIPPED MAP'S OWN COVERAGE, which the headline above does not state. A reader who
        # stopped at the first line read "209 of 209" on a map carrying ten claims no skeptic saw.
        _live_total = g.claims_total - g.claims_superseded + g.claims_added_since
        if g.claims_live_challenged and g.claims_live_challenged < _live_total:
            body += [f"> Of the claims THIS map carries, **{g.claims_live_challenged} of "
                     f"{_live_total} have a verdict**. The other "
                     f"{_live_total - g.claims_live_challenged} were minted after the worklist was "
                     f"pinned, so no skeptic saw them.", ""]
        if g.claims_superseded or g.claims_added_since:
            body += [f"Against the shipped map: **{g.claims_superseded} superseded** (pinned claims "
                     f"the reconcile rewrote or removed) and **{g.claims_added_since} added** since "
                     f"the worklist was pinned. `coyomap grounding report --map` lists which.", ""]
        if not g.live_claims_digest:
            body += ["> No `live_claims_digest`: nothing can confirm this record describes the map "
                     "as it now stands.", ""]
        if g.note:
            body += [f"{g.note}", ""]
        section("Grounding — how much of this map was challenged", body[:-1] if body else body)
    # Notes about the CODE first; the map's own build record last, under one parent heading. Both
    # are kept verbatim — the records are machine-read and auditable — but a reader scrolling this
    # file should reach the facts about their system before the adjudication log about the map.
    for ex in m.extras:
        if not records.is_maintenance(ex.heading):
            section(ex.heading, [ex.body] if ex.body else [])
    build_record = [ex for ex in m.extras if records.is_maintenance(ex.heading)]
    if build_record:
        section("Map maintenance records — the build's own adjudication log",
                ["These sections answer this tool's own checks: each line records an element and why "
                 "a finding about it was judged correct as it stands. They say nothing about the "
                 "system being mapped.", ""]
                + [ln for ex in build_record
                   for ln in [f"### {ex.heading}", ""] + ([ex.body, ""] if ex.body else [])])
    out += ["---", "",
            "*Generated with coyomap from `project-map.json` — the committed source of truth. "
            "Do not edit this file; regenerate it with `coyomap render`.*", ""]
    return "\n".join(out)


# ── graph view (the HTML viewer's input) ─────────────────────────────────────────────────────────

def _first_href(*cells: str | None) -> str | None:
    for c in cells:
        if c:
            hit = LINK.search(c)
            if hit:
                return hit.group(1)
    return None


def _node(el, kind: str, name: str, file: str | None, fields: dict[str, str],
          parent: str | None) -> Node:
    clean = {k: v for k, v in fields.items() if v}
    return Node(id=el.id, kind=kind, name=name or el.id, file=file, line=_line_of(file),
                fields=clean, parent=parent)


# The Data view's non-collection rail groups, in fixed display order (determinism). Each entity here
# has no store of its OWN, but that covers four genuinely different situations, and calling them all
# "not persisted" was wrong for the biggest of them: an `embedded` entity IS persisted — it just lives
# inside a parent's document — and `in-code`/`enum` are persisted in the SOURCE. Only `transient` is
# actually not stored anywhere. So the groups carry a SECTION that states which is which.
#   elsewhere = the data is durable, just not in a collection of its own
#   outside   = it is not in a datastore at all
_NP_SECTIONS: list[tuple[str, str]] = [("elsewhere", "Stored elsewhere"), ("outside", "Not in a datastore")]
# (mode key, section, label). `enum` folds into `in-code`: both mean "the values live in the code".
_NP_MODE_LABELS: list[tuple[str, str, str]] = [
    ("embedded", "elsewhere", "Inside another entity"),
    # A projection is durable data — the rows exist, another entity owns them — so it belongs beside
    # `embedded` under "Stored elsewhere", not under "not in a datastore" with the transient shapes.
    ("projection", "elsewhere", "Read view of another entity's rows"),
    ("in-code", "outside", "Lives in code"),
    ("transient", "outside", "Derived at runtime"),
    ("cache", "outside", "Cache, no store linked"),
    ("", "outside", "Storage not stated"),
]
_NP_MODE_ALIAS = {"enum": "in-code"}   # an enum is a code-level registry by another name


def _embedded_homes(m: ProjectModel) -> dict[str, dict[str, object]]:
    """For every entity stored INSIDE another one, the parent(s) it lives in and the physical store it
    therefore ends up in — the fact the old "not persisted" label hid. A parent is an entity that
    either types a field with this entity's id, or declares a containment relation onto it; the
    physical home is found by walking those parents up until one has a real store (embedding nests —
    a config inside a role inside a document), so even a deeply nested value reports where it lands.
    Resolvable for every embedded entity across the live maps."""
    ents = {e.id: e for e in m.entities}
    parents = record_parents(m)      # ONE containment answer, shared with the saved-record rule

    def home(eid: str, seen: set[str], depth: int = 0) -> str | None:
        """The id of the nearest ancestor holding a real store — None when the chain never reaches one."""
        if depth > 4:
            return None
        for pid in parents.get(eid, []):
            if pid in seen:
                continue
            seen.add(pid)
            p = ents.get(pid)
            if p and p.store and p.store.dep:
                return pid
            deeper = home(pid, seen, depth + 1)
            if deeper:
                return deeper
        return None

    out: dict[str, dict[str, object]] = {}
    for e in m.entities:
        if not (e.store and e.store.mode == "embedded"):
            continue
        hid = home(e.id, {e.id})
        holder = ents.get(hid) if hid else None
        out[e.id] = {
            "parents": [{"id": p, "name": ents[p].name} for p in parents.get(e.id, []) if p in ents],
            "home": ({"id": holder.id, "name": holder.name,
                      "container": holder.store.container} if holder and holder.store else None),
        }
    return out


def _ce_access(m: ProjectModel, name_of: "dict[str, str]") -> dict[str, dict[str, list[dict[str, object]]]]:
    """Per-entity writer/reader/other components from the backbone C→E edges, classified by the SAME
    verb families the persistence rule uses: PERSIST/WRITE → a writer chip (owner=True for the
    system-of-record persist family), READ → a reader chip, anything else → an `other` chip carrying
    its raw verb (so a real link is never silently dropped — the multi-word / non-family-verb case).
    Deduped per (component, role), ordered by component id."""
    acc: dict[str, dict[str, list[dict[str, object]]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for e in sorted(m.edges, key=lambda x: x.src):
        if not (e.src.startswith("C") and e.dst.startswith("E")):
            continue
        verb = e.verb.strip().lower()
        if verb in grammar.PERSIST_VERBS:
            role, owner = "writers", True
        elif verb in grammar.WRITE_VERBS:
            role, owner = "writers", False
        elif verb in grammar.READ_VERBS:
            role, owner = "readers", False
        else:
            role, owner = "other", False
        if (e.src, e.dst, role) in seen:
            continue
        seen.add((e.src, e.dst, role))
        chip: dict[str, object] = {"id": e.src, "name": name_of.get(e.src, e.src), "verb": verb}
        if owner:
            chip["owner"] = True
        acc.setdefault(e.dst, {"writers": [], "readers": [], "other": []})[role].append(chip)
    return acc


def _build_data_view(m: ProjectModel, nodes: dict[str, Node]) -> dict[str, object]:
    """The store-centric Data view payload (rides in the GraphDict like `messaging`). Every list is
    built in model order or sorted, so the output is deterministic. Physical stores = deps classified
    datastore/messaging UNION deps named by any entity's `store.dep` UNION any messaging channel's
    `broker` — so a channel on a service-classed or unmodelled broker still gets a pane. Per store:
    the entities whose structured store names it (container/mode/notes + who writes/reads each, from
    C→E edges) and the channels it carries. Entities with a store but no dep fall into the
    "Not persisted" rail groups; the coverage strip reuses `unexplained_persistence_pairs`."""
    name_of = {nid: n.name for nid, n in nodes.items()}
    access = _ce_access(m, name_of)
    deps_by_id = {d.id: d for d in m.deps}

    # ── the store set (ordered by m.deps) ──
    store_ids: list[str] = []
    referenced = {e.store.dep for e in m.entities if e.store and e.store.dep}
    referenced |= {ch.broker for ch in m.messaging if ch.broker}
    for d in m.deps:
        if grammar.classify_dep(d.kind or "", d.type) in ("datastore", "messaging") or d.id in referenced:
            store_ids.append(d.id)

    rows_by_dep: dict[str, list[dict[str, object]]] = {sid: [] for sid in store_ids}
    for e in m.entities:
        if e.store and e.store.dep in rows_by_dep:
            rows_by_dep[e.store.dep].append({
                "entity": e.id, "name": e.name, "source": e.source or "",
                "meaning": e.meaning, "container": e.store.container, "mode": e.store.mode,
                "notes": e.store.notes,
            })
    channels_by_dep: dict[str, list[dict[str, object]]] = {}
    unassigned: list[dict[str, object]] = []
    for ch in m.messaging:
        row = {"name": ch.name, "kind": ch.kind, "broker": ch.broker,
               "publishers": [{"id": c, "name": name_of.get(c, c)} for c in ch.publishers],
               "consumers": [{"id": c, "name": name_of.get(c, c)} for c in ch.consumers],
               "payload": ch.payload, "payload_name": name_of.get(ch.payload, ch.payload),
               "source": ch.source}
        # A channel attaches to its broker's store pane when that broker is a real store dep; an empty
        # broker OR a broker id that resolves to no store (never happens on a validated map) falls to
        # "unassigned" so a catalogued channel is never silently dropped.
        if ch.broker in rows_by_dep:
            channels_by_dep.setdefault(ch.broker, []).append(row)
        else:
            unassigned.append(row)

    stores: list[dict[str, object]] = []
    for sid in store_ids:
        d = deps_by_id[sid]
        stores.append({
            "dep": sid, "name": d.name,
            "kind": grammar.classify_dep(d.kind or "", d.type),
            "roles": nodes[sid].roles if sid in nodes else [],
            "where": d.where_configured or "",
            "rows": rows_by_dep[sid],
            "channels": channels_by_dep.get(sid, []),
        })

    # ── the groups for entities with no store of their own (see _NP_SECTIONS on why they split) ──
    homes = _embedded_homes(m)
    np_buckets: dict[str, list[dict[str, object]]] = {mode: [] for mode, _, _ in _NP_MODE_LABELS}
    unlinked: list[dict[str, object]] = []
    for e in m.entities:
        if e.store and e.store.dep:
            continue
        ent: dict[str, object] = {"id": e.id, "name": e.name,
               "container": e.store.container if e.store else "",
               "mode": e.store.mode if e.store else "", "source": e.source or ""}
        if e.store and not e.store.dep and e.store.container and e.store.mode in ("collection", "cache"):
            unlinked.append(ent)
            continue
        mode = e.store.mode if e.store else ""
        mode = _NP_MODE_ALIAS.get(mode, mode)
        if mode == "embedded":                       # WHERE it actually lands, the label used to hide
            ent.update(homes.get(e.id, {"parents": [], "home": None}))
        np_buckets.setdefault(mode if mode in np_buckets else "", []).append(ent)
    not_persisted: list[dict[str, object]] = []
    if unlinked:  # persisted for real — the map just failed to name the store (validator nudges it too)
        not_persisted.append({"section": "elsewhere", "mode": "unlinked",
                              "label": "Persisted, but no store linked", "warn": True,
                              "entities": unlinked})
    for mode, section, label in _NP_MODE_LABELS:
        if np_buckets[mode]:
            not_persisted.append({"section": section, "mode": mode, "label": label, "warn": False,
                                  "entities": np_buckets[mode]})
    sections = [{"key": k, "label": lbl} for k, lbl in _NP_SECTIONS
                if any(g["section"] == k for g in not_persisted)]

    # ── coverage gaps (the shared persistence rule), grouped by dep ──
    gaps_by_dep: dict[str, list[dict[str, object]]] = {}
    for cid, verb, d in unexplained_persistence_pairs(m):
        gaps_by_dep.setdefault(d.id, []).append(
            {"component": cid, "name": name_of.get(cid, cid), "verb": verb})
    gaps = [{"dep": did, "name": deps_by_id[did].name, "pairs": pairs}
            for did, pairs in gaps_by_dep.items()]

    # `access` (entity id → {writers, readers, other}) covers EVERY entity with a C→E edge — including
    # non-persisted ones — so the entity info pane can render "Written by" / "Read by" for any entity,
    # while the store rows stay lean (the table looks the writer/reader chips up by entity id).
    return {"stores": stores, "not_persisted": not_persisted, "np_sections": sections, "gaps": gaps,
            "unassigned_channels": unassigned, "access": access}


def auth_surface_rows(m: ProjectModel) -> list[dict[str, str]]:
    """The security surface as display rows — `access` rules FIRST, then any legacy `security[]`.

    ONE derivation, read by the markdown table and by the viewer transport. The fold made rules the
    storage, and a view that reads only `security[]` shows an empty Security section on a folded map
    while the markdown shows fourteen rows — which is the two-answers problem the fold exists to end,
    running the other way. `kind` says which storage a row came from so a reader is never left
    guessing which one is authoritative."""
    # The rule's TITLE where it has one — the same words the Business logic tab names it by, so the
    # two views of one decision are recognisably the same decision. A map with no `name` keeps the
    # statement, which is what this column always was.
    rows = [{"kind": "rule", "id": r.id, "surface": r.name or r.statement, "who": "",
             "source": " · ".join((s.where or "").strip() for s in r.sites
                                  if (s.where or "").strip()),
             "risk": r.risk}
            for r in m.rules if r.access]
    rows += [{"kind": "legacy", "id": "", "surface": r.surface, "who": r.who,
              "source": r.source, "risk": r.risk} for r in m.security]
    return rows


def _build_rules_view(m: ProjectModel, extents: Extents | None) -> dict[str, object]:
    """The T7 transport — every rule with its DERIVED components, steps, entities and sweep state.

    Computed HERE because the typed model is in hand and `validate_model` owns the one
    implementation: the frontend cannot call Python, and a second derivation in JS is exactly the
    drift this repo keeps paying for. `tests/test_business_rules.py` asserts this payload equals the
    Python helper, the way `capability_touch` is pinned.

    `byComponent` and `byStep` are INVERSIONS of the same data, not second derivations — the
    component pane and the flow-step pane look up by key instead of scanning every rule."""
    owners = component_file_owners(m)
    comp_names = {c.id: c.name for c in m.components}
    ent_names = {e.id: e.name for e in m.entities}
    uc_names = {u.id: u.name for u in m.use_cases}
    # `containerName` rides along because the UI shows NAMES, never ids — and a step's authoring
    # container is an `SFn` whenever it was written in a sub-flow.
    sf_names = {sf.id: sf.name for sf in m.subflows}
    anchored = anchored_flow_steps(m)
    by_component: dict[str, list[str]] = {}
    by_step: dict[str, list[str]] = {}
    swept = rules_swept(m, extents)
    out_rules: list[dict[str, object]] = []
    for r in m.rules:
        sites: list[dict[str, object]] = []
        for site in r.sites:
            where = (site.where or "").strip()
            comps = site_components(m, site, owners) if where else []
            sites.append({
                "where": where,
                "why": site.why,
                "declared": bool(site.no_call_site),
                # EVERY owner: `Component.files` is not disjoint, and picking one is the failure
                # this layer exists to prevent. The UI renders them all.
                "components": [{"id": c, "name": comp_names.get(c, c)} for c in comps],
            })
        steps = [{"uc": l.uc, "ucName": uc_names.get(l.uc, l.uc), "container": l.container,
                  "containerName": sf_names.get(l.container, ""),
                  "n": l.n, "strength": l.strength, "phrase": l.phrase}
                 for l in rule_steps(m, r, extents, anchored)]
        for c in rule_components(m, r, owners):
            by_component.setdefault(c, []).append(r.id)
        for l in steps:
            by_step.setdefault(f"{l['uc']}:{l['container']}:{l['n']}", []).append(r.id)
        out_rules.append({
            "id": r.id, "name": r.name, "statement": r.statement, "block": r.block or "",
            "access": r.access, "risk": r.risk, "confidence": r.confidence,
            "sites": sites, "steps": steps,
            "entities": [{"id": e, "name": ent_names.get(e, e)}
                         for e in rule_entities(m, r, extents, anchored)],
            "swept": bool(swept.get(r.id)),
            # A rule with an anchored site nobody owns renders bare — a real state, stamped, never
            # blank. `no_call_site` sites are a DECLARED absence and never count as unverified.
            "unverified": any(not s["declared"] and not s["components"] for s in sites),
        })
    return {
        # `specified_under` rides along so the Rules page can GROUP by it. Ids, not names: the viewer shows
        # names everywhere and looks them up itself, and a name shipped here would be a second copy
        # to keep in step with the feature's own.
        "blocks": [{"id": b.id, "name": b.name, "purpose": b.purpose, "parent": b.parent or "",
                    "specified_under": list(b.specified_under or [])}
                   for b in m.blocks],
        "rules": out_rules,
        "byComponent": by_component,
        "byStep": by_step,
    }


def model_to_graph(m: ProjectModel, extents: Extents | None = None) -> GraphDict:
    """The model as the viewer's GraphDict, the shape `gen_viewer.build_view_bundle` consumes. A
    component's drill file prefers its canonical `source` and falls back to its `entry_point`,
    then a link found in its free-text fields."""
    nodes: dict[str, Node] = {}
    subsystem_names = {s.id: s.name for s in m.subsystems}
    subdomain_names = {sd.id: sd.name for sd in m.subdomains}
    capability_names = {c.id: c.name for c in m.capabilities}
    role_names = {r.id: r.name for r in m.roles}  # role ids → display names (the frontend sees names)
    for u in m.use_cases:
        # BOTH forms: the readable one for display, and the LIST for every view that needs to know who
        # the actors actually are. The display string used to be the only form, so a two-actor use case
        # reached the frontend as one unsplittable name — it matched no role, and the Happy Path drew a
        # lifeline for a person who does not exist while the Use-cases catalog filed it under "Other".
        actor_names = [role_names.get(a, a) for a in u.actors]
        # `parent` = the use case's capability, exactly as a component's parent is its subsystem.
        # Reusing the existing membership channel is what lets the frontend group by capability
        # without a second lookup table travelling beside the nodes.
        # TWO ROWS, because the map holds two fields. One row called `Trigger → Outcome` carried
        # both halves in one cell and left the reader to find the seam. The viewer's CARD is what
        # joins them again with an arrow, because a card has one sentence's worth of room; a detail
        # page has room to label each half.
        node = _node(u, "usecase", u.name, _first_href(u.trigger) or _first_href(u.outcome),
                     {"Use case": u.name, "Actor": and_list(actor_names),
                      "Trigger": u.trigger, "Outcome": u.outcome,
                      **({"Capability": capability_names.get(u.capability or "", u.capability or "")}
                         if u.capability else {})},
                     u.capability)
        node.actors = actor_names
        nodes[u.id] = node
    for s in m.subsystems:
        parent_name = subsystem_names.get(s.parent, s.parent) if s.parent else ""
        nodes[s.id] = _node(s, "subsystem", s.name, s.source,
                            {"Subsystem": s.name, "Purpose": s.purpose, "Parent": parent_name,
                             # tech is subsystem-only (validate blocks it on subdomains), so the
                             # subdomain population below deliberately does NOT mirror this row.
                             **({"Tech": s.tech} if s.tech else {})},
                            s.parent)
    # Capabilities: the use-case forest. A capability is never DRAWN as a box — it groups behavior,
    # not code — but it must reach the browser as a node all the same: the Use Cases tab groups by it,
    # the overlay selects by it, and both show its NAME, never its id. Two words ride along: the
    # AUTHORED `Happy Path` expectation the membership rule reads, and the DERIVED `Audience`, which
    # is computed here because the typed model is in hand and the frontend cannot call Python.
    cap_audience_nodes = capability_audience(m)
    for cap in m.capabilities:
        parent_name = capability_names.get(cap.parent, cap.parent) if cap.parent else ""
        nodes[cap.id] = _node(cap, "capability", cap.name, None,
                              {"Capability": cap.name, "Purpose": cap.purpose,
                               "Parent": parent_name,
                               # Joined, because a node field is a display string. The card splits
                               # it back into one pill per audience.
                               **({"Audience": ", ".join(aud)}
                                  if (aud := cap_audience_nodes.get(cap.id)) else {})},
                              cap.parent)
    # Blocks and rules are never DRAWN as boxes — they group decisions, not code — but they must
    # reach the browser as nodes all the same: `test_convert_and_views` requires every defined
    # element to be one, and the Business logic tab shows NAMES, never ids.
    block_names = {b.id: b.name for b in m.blocks}
    for blk in m.blocks:
        # `None` for the drill file, exactly like a capability. A node carrying a `file` joins
        # `filetree.node_path_index`, where a non-group kind sorts FIRST and becomes that path's
        # primary — so a block with a `source` took over the file browser's selection for that file
        # and landed the reader on the Dependencies tab instead of the component that owns it.
        nodes[blk.id] = _node(blk, "block", blk.name, None,
                              {"Block": blk.name, "Purpose": blk.purpose,
                               "Parent": block_names.get(blk.parent or "", blk.parent or "")},
                              blk.parent)
    for br in m.rules:
        nodes[br.id] = _node(br, "rule", br.name or br.statement, None,
                             {"Rule": br.name or br.statement, "Decision": br.statement,
                              "Block": block_names.get(br.block or "", br.block or "")},
                             br.block)
    # T4 entry points grouped by the component they name — surfaced as each component's "Triggered by"
    # list in the info pane (the standalone table also lives on the System tab). Each flat entry point
    # also carries `index` = its position within its component's list, so the viewer's search hits and
    # System-tab component links can select the exact entry point in that component's pane.
    eps_by_comp: dict[str, list[dict[str, str]]] = {}
    flat_entry_points: list[dict[str, object]] = []
    for ep in m.entry_points:
        # Activation ("self" = runs with no caller, "external" = something asks): the authored value
        # wins; when absent, derive it from the free-text `kind` — mirrors classify_dep, so old maps
        # (and any untagged entry) still classify without a rebuild.
        activation = grammar.effective_activation(ep.activation, ep.kind)
        # The canonical kind (seed spelling / alias fold) rides ALONGSIDE the authored `kind` — the
        # System tab groups by it so `http` and `http-route` rows land in one group, while the row
        # still shows the authored spelling. Same one-resolver rule as `effective_activation`.
        canonical_kind = grammar.canonical_entry_kind(ep.kind)
        ep_dict: dict[str, object] = asdict(ep)
        ep_dict["activation"] = activation
        ep_dict["canonical_kind"] = canonical_kind
        if ep.component:
            ep_dict["index"] = len(eps_by_comp.setdefault(ep.component, []))
            eps_by_comp[ep.component].append(
                {"kind": ep.kind, "trigger": ep.trigger, "source": ep.source,
                 "activation": activation})
        flat_entry_points.append(ep_dict)
    for c in m.components:
        subsystem_name = subsystem_names.get(c.subsystem, c.subsystem) if c.subsystem else ""
        fields = {"Component": c.name, "Subsystem": subsystem_name, "Purpose": c.purpose,
                  **({"Runs in": ", ".join(c.runs_in)} if c.runs_in else {}),
                  **({"States": _states_str(c.states)} if c.states else {}),
                  **{k: _extra_str(v) for k, v in c.extra.items()}}
        # `source` is the v2 canonical home; `entry_point` (also bare) is the next best single
        # location; only then fall back to hunting a markdown link in the free-text cells.
        href = c.source or _first_href(c.purpose, c.depends_on)
        node = _node(c, "component", c.name, href, fields, c.subsystem)
        node.files = _component_files(c)
        node.entry_points = eps_by_comp.get(c.id, [])
        node.runs_in = list(c.runs_in)
        node.states_lines = _states_parts(c.states)   # a component lifecycle lists per line too
        nodes[c.id] = node
    # A dep's ROLE set is derived from the verbs of its incoming C→D edges (grammar.dep_roles), so a
    # dual-role dep (Redis as bus + store) reads from its two real verbs, never a stored field.
    dep_verbs: dict[str, list[str]] = {}
    for e in m.edges:
        if e.dst.startswith("D"):
            dep_verbs.setdefault(e.dst, []).append(e.verb)
    for d in m.deps:
        dep_kind = grammar.classify_dep(d.kind or "", d.type)
        bucket = grammar.resolve_bucket(dep_kind in grammar.DEP_KINDS_FOLDED, d.bucket, d.type, d.used_for)
        fields = {"Name": d.name, "Kind": d.kind or "", "Bucket": bucket, "Type": d.type,
                  "Used for": d.used_for, "Package": d.package,
                  **{k: _extra_str(v) for k, v in d.extra.items()}}
        node = _node(d, "dep", d.name, d.where_configured or _first_href(d.used_for), fields, None)
        node.dep_kind = dep_kind
        node.roles = sorted(grammar.dep_roles(dep_verbs.get(d.id, [])))
        nodes[d.id] = node
    # INTERFACES reach the browser as nodes because a flow STEP may end at one: `R1 → I3 → C12` reads
    # "a person, through the dashboard, into the code". Without a node the step would draw a bare id.
    iface_dirs = interface_directions(m)
    for iface in m.interfaces:
        flow = iface_dirs.get(iface.id, [])
        kind = grammar.canonical_interface_kind(iface.kind)
        fields = {"Name": iface.name, "What it is": iface.what,
                  "Side": iface.side,
                  **({"Kind": kind} if kind else {}),
                  "Facing": iface.facing,
                  "What crosses": ", ".join(flow) or ""}
        nodes[iface.id] = _node(iface, "interface", iface.name, iface.source, fields, None)
    for sd in m.subdomains:
        parent_name = subdomain_names.get(sd.parent, sd.parent) if sd.parent else ""
        nodes[sd.id] = _node(sd, "subdomain", sd.name, sd.source,
                             {"Subdomain": sd.name, "Purpose": sd.purpose,
                              "Parent": parent_name}, sd.parent)
    for e in m.entities:
        meta: dict[str, str] = {}
        if e.meaning:
            meta["Meaning"] = e.meaning
        # A persisted entity (store.dep set) gets the richer structured "Persisted in" row in the info
        # pane (clickable dep + Data-view link, see viewer.js persistedInHtml), so the plain "Stored"
        # text line would just duplicate it. Keep "Stored" ONLY for a not-persisted store (no dep),
        # where the structured row does not render — so every entity shows its storage exactly once.
        if e.store and not e.store.dep:
            meta["Stored"] = _store_str(e.store)
        if e.states:
            meta["States"] = _states_str(e.states)
        node = Node(id=e.id, kind="entity", name=e.name, file=e.source, line=_line_of(e.source),
                    fields=meta, parent=e.subdomain,
                    attrs=[{"name": f.name, "type": f.type, "markers": " ".join(f.markers)}
                           for f in e.fields])
        if e.store:
            node.store = {"dep": e.store.dep or "", "container": e.store.container,
                          "mode": e.store.mode, "notes": e.store.notes}
        if e.states:
            node.states_count = len(e.states.states)
            node.states_lines = _states_parts(e.states)
        ent_file = _bare_local_file(e.source)
        node.files = [ent_file] if ent_file else []
        nodes[e.id] = node

    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for e in m.edges:
        key = (e.src, e.verb, e.dst)
        if key in seen:
            continue
        seen.add(key)
        edges.append(GraphEdge(e.src, e.verb, e.dst, e.why or None, e.where or None))
    for ent in m.entities:
        for r in ent.relations:
            edges.append(GraphEdge(ent.id, r.verb, r.target, None, None,
                                   kind=grammar.REL_KIND.get(r.verb.lower(), "association"),
                                   src_card=r.src_card, dst_card=r.dst_card, how=r.how,
                                   keyed_by=r.keyed_by))
    # Resolve which real field backs each domain relation (drives the arrow label + panel line) —
    # the same second pass the v1 parser ran once all entity nodes existed.
    backing = {e.id: [(f.name, f.type, grammar.fk_targets(f.markers)) for f in e.fields]
               for e in m.entities}
    for ge in edges:
        if ge.kind and ge.kind != "inheritance" and ge.src in backing and ge.dst in backing:
            ge.fk_fields, ge.fk_side = grammar.resolve_backing(
                ge.src, ge.dst, backing[ge.src], backing[ge.dst])

    def _endpoint(x: str) -> str:  # an actor step carries a role id → show the role NAME
        return role_names.get(x, x) if grammar.is_role_id(x) else x

    def _graph_steps(steps: list[FlowStep]) -> list[grammar.FlowStep]:  # shared: flows + sub-flows
        return [grammar.FlowStep(n=st.n, src=_endpoint(st.src), dst=_endpoint(st.dst),
                                 src_is_id=grammar.is_step_id(st.src),
                                 dst_is_id=grammar.is_step_id(st.dst),
                                 phrase=st.phrase, note=st.note, where=st.where,
                                 subflow=st.subflow, ok=True)
                for st in steps]
    flows = [grammar.Flow(uc=f.uc, title=f.title, line_no=0, steps=_graph_steps(f.steps))
             for f in m.flows]
    subflows = [{"id": sf.id, "name": sf.name, "steps": [asdict(s) for s in _graph_steps(sf.steps)]}
                for sf in m.subflows]

    _ensure_default_subsystem(nodes, m.title or None)

    # A group's files = the union of its members' files (subsystems roll up their components, subdomains
    # their entities), recursively through nested groups — so drilling a subsystem's code viewer or
    # highlighting its footprint spans everything it contains. Run after the default-subsystem inject so
    # a synthesized group also rolls up its (now reparented) members. Membership is single-source on the
    # child.
    children_by_parent: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        if n.parent:
            children_by_parent.setdefault(n.parent, []).append(nid)

    def _group_files(gid: str, seen: set[str]) -> list[str]:
        out: list[str] = []
        for cid in children_by_parent.get(gid, []):
            if cid in seen:
                continue
            seen.add(cid)
            child = nodes[cid]
            contrib = _group_files(cid, seen) if child.kind in ("subsystem", "subdomain") else child.files
            for f in contrib:
                if f not in out:
                    out.append(f)
        return out

    for nid, n in nodes.items():
        if n.kind in ("subsystem", "subdomain"):
            n.files = _group_files(nid, set())
    return {
        "commit": m.commit,
        "committed": m.committed,
        "built": m.built,
        "format": m.format or None,
        "title": m.title or None,
        "goal": m.goal or None,
        "nodes": {nid: asdict(n) for nid, n in nodes.items()},
        "edges": [asdict(e) for e in edges],
        "happy_path": [asdict(GraphHappyStep(id=g.id, uc=g.uc, why=g.why or ""))
               for g in m.happy_path],
        "flows": [asdict(f) for f in flows],
        "subflows": subflows,
        # WHICH RECORD HOLDS WHICH, so the browser can answer "in use cases" for a record that is
        # only ever reached through its container. Without it the panel said "No traced use case
        # reaches it" on a record `validate` counts as storied — the screen and the check
        # disagreeing about one record, which is the shape this whole change exists to end.
        "record_parents": record_parents(m),
        # `id` rides along with the name because the DERIVED feature layer (coyomap.features)
        # keys a role by its id — `role_features` and `FeatureFacts.roles` are id lists — while
        # every other consumer here reads the name. Without it the frontend holds no way to turn
        # `R3` into "Workspace admin", and the who-can-do-what grid would print raw ids.
        # `relations` rides along only when authored, so a map without them serializes exactly as
        # before (the frontend treats absence as []). The actor page reads it for its hero meta
        # ("was <role> until <use case>", the includes chip) and its greyed before-segment.
        "roles": [{"id": r.id, "name": r.name, "wants": r.wants, "kind": _role_kind(r.name, r.kind),
                   "audience": r.audience,
                   **({"relations": [{"kind": rel.kind, "role": rel.role,
                                      **({"at": rel.at} if rel.at else {})}
                                     for rel in r.relations]} if r.relations else {})}
                  for r in m.roles],
        # `aliases` / `no_autolink` ride along only when set, so a map without them serializes
        # exactly as before (and the frontend treats absence as [] / false).
        "glossary": [{"term": g.term, "meaning": g.meaning, "source": g.source or "",
                      **({"aliases": g.aliases} if g.aliases else {}),
                      **({"no_autolink": True} if g.no_autolink else {})}
                     for g in m.glossary],
        # ── the capability overlay's data (plan/60-capabilities Step 6) ──
        # Computed HERE because the typed model is in hand and `validate_model` owns the one
        # implementation of the touch primitive — the frontend cannot call Python, and a second
        # implementation in JS is exactly the drift this repo keeps paying for elsewhere.
        "capability_touch": {eid: sorted(caps)
                             for eid, caps in element_capabilities(m).items()},
        # ── the T7 decision layer (see `_build_rules_view`) ──
        "rules_view": _build_rules_view(m, extents),
        "completeness": completeness_counts(m),
        # ── reference collections (System / Tests tabs) — carried straight from the model ──
        "run_commands": [asdict(r) for r in m.run_commands],
        "entry_points": flat_entry_points,
        "non_entity_types": [asdict(t) for t in m.non_entity_types],
        "deployment": [asdict(r) for r in m.deployment],
        "environments": list(m.environments),
        "messaging": [asdict(r) for r in m.messaging],

        "observability": [asdict(r) for r in m.observability],
        # DERIVED from both storages (see `auth_surface_rows`): a folded map keeps its Security
        # section, and a legacy map keeps its rows, without the frontend knowing which is which.
        "security": auth_surface_rows(m),
        "config": [asdict(r) for r in m.config],
        # Store-centric Data view (rail of physical stores → collections + writers/readers + async
        # channels + coverage gaps). Derived here where the typed model is in hand; rides in the graph
        # like the other reference collections.
        "data_view": _build_data_view(m, nodes),
        "tests_note": m.tests_note,
        # Rows carry SERVER-RESOLVED targets ({id, name, node}) so the Tests tab renders element
        # names + locate-links with no client-side id parsing; `tests` cites suites as {file, why}.
        "tests": [{
            "targets": _resolve_targets(r, all_elements(m), nodes),
            "label": r.label,
            "tested": r.tested,
            "tests": [asdict(ev) for ev in r.tests],
            "gap": r.gap,
            "confidence": r.confidence,
        } for r in m.tests],
        # `maintenance` marks the map's own build record (see `records.HEADINGS`), so the System tab
        # can lead with notes about the code and fold the adjudication log away at the bottom.
        "extras": [ExtraSectionView(heading=x.heading, body=x.body,
                                    maintenance=records.is_maintenance(x.heading),
                                    refs=_extra_refs(x.body, all_elements(m), nodes))
                   for x in m.extras],
    }
