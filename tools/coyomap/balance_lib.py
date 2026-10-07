#!/usr/bin/env python3
"""Diagram balance — the fan-out advisories and the regroup-proposal engine.

Every rendered diagram shows a node's IMMEDIATE children (the viewer draws exactly
`_components_of` + `_child_subsystems`), so each screen should carry a readable number of
boxes: target 5±2. This module computes, from the model alone (stdlib-only, zero I/O):

  * `balance_warnings` — the always-on advisory warnings `coyomap validate` appends
    (never problems: balance NEVER gates; it only ever re-groups, and re-grouping is a
    view-only edit — membership on the child, member lists derived).
  * the C→C graph machinery (`cc_pairs`, `quotient_pairs`, `modularity`,
    `inter_group_matrix`) and the deterministic greedy split proposer (`propose_split`)
    that `coyomap balance` renders as Direct-map-change suggestions.

Scoping rules (from the adversarial review of the design):
  * Modularity (Q) is a SPLIT-context number, never a top-cut score — a tech-tier root
    cut scores near-perfect Q while being the least informative top screen.
  * Sparse (<3) warns at the ROOT only; mid-tree 2-child subsystems are normal.
  * Homogeneous screens (a family of same-kind siblings — 11 repositories) are exempt
    up to `FANOUT_HOMOG_HI` and never receive a modularity proposal ("list-shaped").
  * A justified exception recorded in the model's `extras` under the heading
    "Balance exceptions" silences the named diagrams durably.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from coyomap import records
from coyomap.model import ProjectModel, group_forests

# ── the bands (named constants so calibration is one edit) ───────────────────────────────────────

FANOUT_LO = 3            # below → sparse (root only)
FANOUT_TARGET = 5        # the 5±2 target the method text states
FANOUT_SOFT_HI = 9       # above → soft tier (reported by `coyomap balance` only)
FANOUT_HARD_HI = 12      # above → validate warning
FANOUT_HOMOG_HI = 15     # homogeneous families are exempt up to here
SUBSYSTEMS_RECOMMENDED_ABOVE = 15  # mirrors method.md "recommended above ~15 components"

_EXCEPTIONS_HEADING = "balance exceptions"
_ROOT = "<root>"

# The LITERAL escapes recordable under 'Balance exceptions' — the whole non-id vocabulary. Every
# one of them is an ordinary English word (or a hyphenated word pair) that a justification sentence
# naturally uses in passing — "the runs-in tagging was audited separately", "we reviewed
# granularity and entity-flows during the walkthrough" — so an anywhere-in-body scan lets unrelated
# prose silently switch off a whole advisory family. `cadence`/`store`/`messaging`/`isolated` were
# put on the line-leading discipline by adversarial-review finding #2; `runs-in`, `granularity` and
# `entity-flows` were left behind on the old scan and joined them for the same reason (finding #3),
# `runs-in` most urgently of all — it now silences the entire deployment family, so one stray prose
# mention would blank a dozen checks at once. ALL of them are now read LINE-LEADING, the same
# `_RECORD_LINE` discipline `validate_model` uses for its recorded-id headings.
#: The five SCOPED `runs_in` escapes, one per finding group in `validate_model._RUNS_IN_FAMILY`.
#: A bare `runs-in` used to silence all five at once, which is the one thing the method says a
#: record must never do ("silences exactly one (check, id) pair — never a family"). On a live map a
#: record written about two test-profile containers thereby hid a real regression: six of eight
#: deployment units had stopped hosting any component, and the advisory that says so was already
#: switched off. Scoping is what makes the justification and the silence describe the same thing.
RUNS_IN_SCOPES: tuple[str, ...] = (
    "runs-in/quality", "runs-in/unlinked", "runs-in/unplaced",
    "runs-in/entry-hosts", "runs-in/messaging",
)

_LITERAL_ESCAPES: tuple[str, ...] = (
    "cadence", "channel-ends", "channel-payload", "entity-flows", "entity-relations",
    "granularity", "isolated", "messaging", "runs-in", "store", *RUNS_IN_SCOPES,
)

# Line-leading literal + terminator. Longest-first alternation so a shorter bare alternative can
# never swallow the prefix of a longer one (a bare `messaging` would otherwise record the
# `messaging`-prefixed shape of a future token and silence the empty-catalog canary as a side
# effect). The terminator is `:`, `(`, an em/en dash, a SPACED ascii hyphen, or the end of the line
# (a line that is nothing but the literal is a record — prose sentences are never one word long).
# A BARE hyphen is deliberately NOT a separator: it is word-internal in half the vocabulary above,
# so the old `[:(—–-]` class read `store-front redesign: see ticket 44` as a `store` record,
# `isolated-network deploys: nothing to do` as an `isolated` one, and `channel-payload-review-2026:`
# as a `channel-payload` one (adversarial-review finding #8). Requiring the space around the hyphen
# keeps the legible `cadence - <why>` dash form working while closing the compound-word hole.
# Public because `finalize`'s budget leg reads its `granularity:` line with it, so a line that leg
# takes is a line validate takes.
LITERAL_LINE = re.compile(
    r"^\s*(?:[-*]\s+)?\**\s*("
    + "|".join(re.escape(lit) for lit in sorted(_LITERAL_ESCAPES, key=len, reverse=True))
    + r")\**(?:\s*[:(—–]|\s+-\s|\s*$)")

# Diagram / element ids ('root', 'S7', 'UC5', 'C18', …) stay an anywhere-in-body scan. They are not
# words, so prose cannot mint one by accident, and live maps rely on it: a real map records five
# sub-flows as one comma-separated line (`SF40, SF41, SF52, SF70, SF71: each is referenced once`),
# of which only the first is line-leading.
_EXCEPTION_IDS = re.compile(r"\b(?:root|SD\d+|SF\d+|UC\d+|C\d+|S\d+)\b")

_STOPWORDS = frozenset(
    "the a an and or of for to in on with via per by from into over its their our this that "
    "component components service services module modules code file files".split())


# ── immediate-children maps (the diagrams) ───────────────────────────────────────────────────────

def subsystem_children(m: ProjectModel) -> dict[str | None, list[str]]:
    """Diagram id -> immediate children (None = the root diagram). Children of the root are the
    top-level subsystems plus any ungrouped components; children of an S are its child subsystems
    plus its direct member components — exactly what the viewer draws."""
    out: dict[str | None, list[str]] = {None: []}
    for s in m.subsystems:
        out.setdefault(s.id, [])
        out.setdefault(s.parent, []).append(s.id) if s.parent else out[None].append(s.id)
    for c in m.components:
        if c.subsystem:
            out.setdefault(c.subsystem, []).append(c.id)
        else:
            out[None].append(c.id)
    return out


def subdomain_children(m: ProjectModel) -> dict[str | None, list[str]]:
    """The SD-forest mirror of `subsystem_children` (entities as leaves)."""
    out: dict[str | None, list[str]] = {None: []}
    for sd in m.subdomains:
        out.setdefault(sd.id, [])
        out.setdefault(sd.parent, []).append(sd.id) if sd.parent else out[None].append(sd.id)
    for e in m.entities:
        if e.subdomain:
            out.setdefault(e.subdomain, []).append(e.id)
        else:
            out[None].append(e.id)
    return out


def nesting_depth(m: ProjectModel) -> int:
    """Grouping levels in the S forest (flat subsystems = 1, one nested tier = 2, …; none = 0)."""
    parent = {s.id: s.parent for s in m.subsystems}
    best = 0
    for sid in parent:
        depth, cur = 1, parent.get(sid)
        seen = {sid}
        while cur and cur not in seen:   # cycle-safe (cycles are a validate problem, not ours)
            seen.add(cur)
            depth += 1
            cur = parent.get(cur)
        best = max(best, depth)
    return best


# ── homogeneity (deterministic, model-only) ──────────────────────────────────────────────────────

def _container_dir(m: ProjectModel, elem_id: str) -> str | None:
    """The element's container directory: a file anchor's dir; a `path/` anchor's own path."""
    src: str | None = None
    files: list[str] = []
    for c in m.components:
        if c.id == elem_id:
            src, files = c.source, c.files
            break
    else:
        for grp in group_forests(m):
            if grp.id == elem_id:
                src = grp.source
                break
        else:
            for e in m.entities:
                if e.id == elem_id:
                    src = e.source
                    break
    if not src and files:
        src = files[0]
    if not src:
        return None
    if src.endswith("/"):
        return src.rstrip("/")
    path = src.rsplit(":", 1)[0] if re.search(r":\d", src) else src
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _name_token(m: ProjectModel, elem_id: str) -> str | None:
    """The element's final name token, lowercased ('Audit log repository' -> 'repository')."""
    for el in [*m.components, *group_forests(m), *m.entities]:
        if el.id == elem_id:
            tokens = re.findall(r"[A-Za-z0-9]+", el.name)
            return tokens[-1].lower() if tokens else None
    return None


def _kind(elem_id: str) -> str:
    return "SD" if elem_id.startswith("SD") else elem_id[0]


def is_homogeneous(m: ProjectModel, children: list[str]) -> bool:
    """All children the same kind AND ≥2/3 share a container directory or a final name token —
    a list-shaped family (11 repositories) that reads fine dense."""
    if len(children) < 2 or len({_kind(c) for c in children}) != 1:
        return False
    threshold = math.ceil(len(children) * 2 / 3)
    dirs = Counter(d for c in children if (d := _container_dir(m, c)) is not None)
    if dirs and dirs.most_common(1)[0][1] >= threshold:
        return True
    tokens = Counter(t for c in children if (t := _name_token(m, c)) is not None)
    return bool(tokens) and tokens.most_common(1)[0][1] >= threshold


# ── the always-on advisory (validate hook) ───────────────────────────────────────────────────────

#: The one heading matcher every escape family shares, so matching can never drift between them.
#: Re-exported from `records` (which owns the whole recorded-line contract) rather than
#: re-implemented — every caller that already imports it through here keeps working.
extras_bodies = records.extras_bodies


def _exceptions(m: ProjectModel) -> set[str]:
    """Ids the operator has durably justified ('root', 'S7', 'UC5', 'C18', 'granularity', …) in an
    extras block headed 'Balance exceptions'. Diagram ids silence fan-out warnings here; UC/SF ids
    silence the flow-length band; C ids silence the promote-to-subsystem altitude nudge; the
    literal `granularity` silences the component-count-vs-E advisory; the literal `entity-flows`
    silences the no-entity-in-any-flow canary (a map whose flows legitimately touch no entity —
    a pure proxy with no domain layer traced); the FIVE SCOPED
    `runs-in/…` literals each silence exactly one deployment finding group (`RUNS_IN_SCOPES`); a
    bare `runs-in` silences nothing and is reported as a mistake, because it used to switch off all
    five at once while the justification behind it was about one; the literal `cadence`
    silences the self-activated-entry-points-record-no-cadence advisory (loops that are all
    genuinely continuous / caller-shaped); the literal `store` silences the unstructured-entity-
    stores advisory (a map deliberately keeping notes-only stores); the literal `messaging`
    silences the bus-edges-but-empty-catalog canary (a bus used only through an abstraction with
    no nameable channels); the literal `isolated` silences the components-wired-to-nothing canary
    (code that genuinely stands alone); the literal `channel-ends` silences the one-sided-channel
    advisory (a channel whose other end lives outside the mapped repo); the literal
    `channel-payload` silences the no-channel-names-a-payload canary (channels that really are
    untyped); the literal `entity-relations` silences the isolated-entities advisory (a domain
    whose cards legitimately carry no E↔E relation). The two placement advisories that live
    outside the deployment-quality family — an unplaced self-started entry point, and a messaging
    channel no participant's `runs_in` can place — have their own scopes (`runs-in/entry-hosts`,
    `runs-in/messaging`) rather than riding a shared literal. EVERY literal is
    read LINE-LEADING (`LITERAL_LINE`: `granularity: <why>`), because every one of them is an
    ordinary prose word — a sentence merely using the word never silences anything. Ids keep the
    anywhere-in-body scan (`_EXCEPTION_IDS`), which prose cannot trip. All consumed only as
    skip-sets, so the families can't cross-silence anything. Without a machine-readable escape a
    justified advisory re-fires forever — and worse, invites rewording prose to dodge a heuristic."""
    out: set[str] = set()
    for body in extras_bodies(m, _EXCEPTIONS_HEADING):
        out.update(_EXCEPTION_IDS.findall(body))
        for line in body.splitlines():
            hit = LITERAL_LINE.match(line)
            if hit:
                out.add(hit.group(1))
    return out


#: A line that LOOKS like a scoped `runs_in` escape. Deliberately looser than `LITERAL_LINE`,
#: which only ever matches keys that are already recognised — so a typo'd key does not appear in
#: `_exceptions` at all, silences nothing, and says nothing. The operator then believes the finding
#: is adjudicated while `validate` goes on reporting it. Scoping replaced one short word with five
#: slash-and-hyphen keys typed free-hand into `record --line`, which multiplies that surface.
_RUNS_IN_NEAR_MISS = re.compile(
    r"^\s*(?:[-*]\s+)?\**\s*(runs[-_]in[-/][a-z-]+)\**\s*(?:[:(—–]|\s+-\s|\s*$)", re.IGNORECASE)


def near_miss_runs_in_keys(m: ProjectModel) -> list[str]:
    """Recorded lines that meant to be a scoped `runs_in` escape and are not one."""
    out: set[str] = set()
    for body in extras_bodies(m, _EXCEPTIONS_HEADING):
        for line in body.splitlines():
            hit = _RUNS_IN_NEAR_MISS.match(line)
            if hit and hit.group(1) not in RUNS_IN_SCOPES:
                out.add(hit.group(1))
    return sorted(out)


def _name_of(m: ProjectModel, gid: str) -> str:
    for grp in group_forests(m):
        if grp.id == gid:
            return grp.name
    return gid


def _forest_warnings(m: ProjectModel, children: dict[str | None, list[str]],
                     groups_exist: bool, n_leaves: int, leaf_word: str, leaf_singular: str,
                     group_word: str, skip: set[str]) -> list[str]:
    out: list[str] = []
    root_kids = children.get(None, [])
    if not groups_exist:
        if n_leaves > SUBSYSTEMS_RECOMMENDED_ABOVE and "root" not in skip:
            out.append(f"Balance: {n_leaves} {leaf_word} with no {group_word} — the root diagram "
                       f"shows all of them ungrouped; {group_word} are recommended above "
                       f"~{SUBSYSTEMS_RECOMMENDED_ABOVE} (cluster by product area, target 5±2 "
                       f"boxes per diagram)")
        return out

    # Root: the one diagram where SPARSE is an anti-pattern (the first screen must inform).
    n_root = len(root_kids)
    if "root" not in skip:
        if n_root < FANOUT_LO and n_leaves >= SUBSYSTEMS_RECOMMENDED_ABOVE:
            out.append(f"Balance: the root diagram shows only {n_root} top-level boxes for "
                       f"{n_leaves} {leaf_word} — a sparse (often tech-tier) root wastes the first "
                       f"screen; lead with product-area groups (target 5±2)")
        elif n_root > FANOUT_HARD_HI and not (
                is_homogeneous(m, root_kids) and n_root <= FANOUT_HOMOG_HI):
            out.append(f"Balance: the root diagram shows {n_root} top-level boxes (target 5±2) — "
                       f"group them into fewer product-area {group_word}")

    for gid, kids in children.items():
        if gid is None or gid in skip or not kids:
            continue  # root handled above; empty boxes have their own warning
        n = len(kids)
        if n == 1 and not kids[0].startswith(("S", "SD")):
            out.append(f"Balance: {gid} ({_name_of(m, gid)}) wraps a single {leaf_singular} "
                       f"({kids[0]}) — a one-child level isn't pulling its weight; inline it or "
                       f"grow the group")
        elif n > FANOUT_HARD_HI:
            if is_homogeneous(m, kids):
                if n > FANOUT_HOMOG_HI:
                    out.append(f"Balance: {gid} ({_name_of(m, gid)}) shows {n} children — dense "
                               f"even for a homogeneous family; split it by name/directory family")
            else:
                out.append(f"Balance: {gid} ({_name_of(m, gid)}) shows {n} children (target 5±2) "
                           f"— group them into child {group_word} (`coyomap balance` proposes "
                           f"splits)")
    return sorted(out)


def balance_warnings(m: ProjectModel) -> list[str]:
    """The advisory fan-out warnings for both forests. Warnings only — balance never blocks."""
    skip = _exceptions(m)
    out = _forest_warnings(m, subsystem_children(m), bool(m.subsystems), len(m.components),
                           "components", "component", "subsystems", skip)
    out += _forest_warnings(m, subdomain_children(m), bool(m.subdomains), len(m.entities),
                            "entities", "entity", "subdomains", skip)
    return out


# ── the C→C graph (split proposals; `coyomap balance` only) ──────────────────────────────────────

def cc_pairs(m: ProjectModel) -> set[frozenset[str]]:
    """Deduped undirected component↔component pairs (C→D / C→E excluded, self-loops dropped)."""
    return {frozenset((e.src, e.dst)) for e in m.edges
            if e.src.startswith("C") and e.dst.startswith("C") and e.src != e.dst}


def _subtree_leaves(m: ProjectModel, sid: str) -> set[str]:
    """Every component under `sid` at any depth."""
    kids: dict[str, list[str]] = {}
    for s in m.subsystems:
        if s.parent:
            kids.setdefault(s.parent, []).append(s.id)
    comps: dict[str, list[str]] = {}
    for c in m.components:
        if c.subsystem:
            comps.setdefault(c.subsystem, []).append(c.id)
    out: set[str] = set()
    stack = [sid]
    while stack:
        cur = stack.pop()
        out.update(comps.get(cur, []))
        stack.extend(kids.get(cur, []))
    return out


def partition_at(m: ProjectModel, level: str = "leaf") -> dict[str, str]:
    """Component id -> group key: its immediate subsystem ('leaf') or its top-level ancestor
    ('top'); ungrouped components map to the synthetic root group."""
    parent = {s.id: s.parent for s in m.subsystems}
    out: dict[str, str] = {}
    for c in m.components:
        g = c.subsystem or _ROOT
        if level == "top" and g != _ROOT:
            seen = {g}
            while (p := parent.get(g)) and p not in seen:
                seen.add(p)
                g = p
        out[c.id] = g
    return out


def modularity(pairs: set[frozenset[str]] | dict[frozenset[str], int],
               partition: dict[str, str]) -> tuple[float, float]:
    """(coverage, Newman Q) of a partition over an undirected (optionally weighted) pair graph.
    Coverage = intra-group weight share (the explainable number); Q additionally discounts what
    a random cut would score. Pairs with an endpoint outside the partition are ignored."""
    weights = pairs if isinstance(pairs, dict) else {p: 1 for p in pairs}
    m_total = 0
    intra: Counter[str] = Counter()
    degree: Counter[str] = Counter()
    for pair, w in weights.items():
        a, b = sorted(pair)
        if a not in partition or b not in partition:
            continue
        m_total += w
        degree[partition[a]] += w
        degree[partition[b]] += w
        if partition[a] == partition[b]:
            intra[partition[a]] += w
    if m_total == 0:
        return 0.0, 0.0
    coverage = sum(intra.values()) / m_total
    q = sum(intra[g] / m_total - (degree[g] / (2 * m_total)) ** 2 for g in degree)
    return coverage, q


def inter_group_matrix(pairs: set[frozenset[str]] | dict[frozenset[str], int],
                       partition: dict[str, str]) -> dict[tuple[str, str], int]:
    """(group, group) -> pair weight, groups sorted within the key; (g, g) rows are intra."""
    weights = pairs if isinstance(pairs, dict) else {p: 1 for p in pairs}
    out: Counter[tuple[str, str]] = Counter()
    for pair, w in weights.items():
        a, b = sorted(pair)
        if a in partition and b in partition:
            ga, gb = sorted((partition[a], partition[b]))
            out[(ga, gb)] += w
    return dict(out)


def _diagram_graph(m: ProjectModel, sid: str | None) -> tuple[list[str], dict[frozenset[str], int]]:
    """The graph a diagram's split proposal runs on: nodes = the diagram's immediate children;
    pairs = C→C pairs projected onto them. A child SUBSYSTEM absorbs its whole subtree's
    components (the quotient graph), so S-children diagrams get proposals too."""
    children = subsystem_children(m).get(sid, [])
    rep: dict[str, str] = {}
    for ch in children:
        if ch.startswith("S"):
            for leaf in _subtree_leaves(m, ch):
                rep[leaf] = ch
        else:
            rep[ch] = ch
    weights: Counter[frozenset[str]] = Counter()
    for pair in cc_pairs(m):
        a, b = sorted(pair)
        if a in rep and b in rep and rep[a] != rep[b]:
            weights[frozenset((rep[a], rep[b]))] += 1
    return children, dict(weights)


def subgraph_signal(m: ProjectModel, sid: str | None) -> str:
    """Whether a diagram's internal graph carries enough signal for a modularity split:
    'homogeneous' | 'sparse' (pair weight < n/2) | 'star' (one hub carries >½ the weight) | 'ok'."""
    children, weights = _diagram_graph(m, sid)
    if is_homogeneous(m, children):
        return "homogeneous"
    total = sum(weights.values())
    if total < len(children) / 2:
        return "sparse"
    incident: Counter[str] = Counter()
    for pair, w in weights.items():
        for node in pair:
            incident[node] += w
    if incident and incident.most_common(1)[0][1] > total / 2:
        return "star"
    return "ok"


# ── the greedy split (deterministic CNM) ─────────────────────────────────────────────────────────

@dataclass
class Proposal:
    """One suggested child group for an over-dense diagram."""
    name: str
    name_basis: str                       # "dir" | "purpose" | "unnamed"
    members: list[tuple[str, str]] = field(default_factory=list)   # (id, display name)


def _segmentwise_lcp(paths: list[str]) -> list[str]:
    """Longest common directory prefix, SEGMENT-wise (never string-wise)."""
    if not paths:
        return []
    split = [p.split("/") for p in paths]
    out: list[str] = []
    for segs in zip(*split):
        if len(set(segs)) == 1:
            out.append(segs[0])
        else:
            break
    return out


def _display_name(m: ProjectModel, elem_id: str) -> str:
    for el in [*m.components, *group_forests(m), *m.entities]:
        if el.id == elem_id:
            return el.name
    return elem_id


def name_seed(m: ProjectModel, member_ids: list[str],
              parent_lcp: list[str] | None = None) -> tuple[str, str]:
    """(seed name, basis). Dir first (last segment of the members' segment-wise LCP), the most
    frequent non-stopword purpose token second, '(name me)' last. A dir seed must extend BEYOND
    `parent_lcp` (the diagram's own common prefix) — the shared package dir discriminates
    nothing, so it falls through to the purpose words."""
    dirs = [d for c in member_ids if (d := _container_dir(m, c))]
    lcp = _segmentwise_lcp(dirs) if len(dirs) == len(member_ids) and dirs else []
    if lcp and lcp[-1] and len(lcp) > len(parent_lcp or []):
        return lcp[-1].replace("_", " ").replace("-", " ").title(), "dir"
    purposes: list[str] = []
    for el in (*m.components, *m.subsystems):   # quotient members are subsystems
        if el.id in member_ids and el.purpose:
            purposes.append(el.purpose)
    tokens = Counter(t for p in purposes for t in re.findall(r"[a-z0-9]+", p.lower())
                     if t not in _STOPWORDS and len(t) > 2)
    if tokens:
        return tokens.most_common(1)[0][0].title(), "purpose"
    return "(name me)", "unnamed"


def _dedup_names(m: ProjectModel, proposals: list[Proposal]) -> None:
    """Sibling proposals with colliding seeds get a discriminating member-token suffix."""
    by_name: dict[str, list[Proposal]] = {}
    for p in proposals:
        by_name.setdefault(p.name, []).append(p)
    for clashing in (v for v in by_name.values() if len(v) > 1):
        for p in clashing:
            tokens = Counter(t for _, disp in p.members
                             for t in re.findall(r"[a-z0-9]+", disp.lower())
                             if t not in _STOPWORDS and len(t) > 2)
            others = {t for q in clashing if q is not p for _, disp in q.members
                      for t in re.findall(r"[a-z0-9]+", disp.lower())}
            distinct = [t for t, _ in tokens.most_common() if t not in others]
            p.name = f"{p.name} — {distinct[0].title()}" if distinct else f"{p.name} (name me)"


def propose_split(m: ProjectModel, sid: str | None) -> list[Proposal]:
    """Deterministic greedy-modularity (CNM) split of an over-dense diagram's children.
    Returns [] when the subgraph carries no signal (`subgraph_signal` != 'ok') or the merge
    collapses to a single group — the caller prints the 'list-shaped' message instead.
    Never returns a group of size 1 (a singleton wrap would itself warn)."""
    if subgraph_signal(m, sid) != "ok":
        return []
    children, weights = _diagram_graph(m, sid)
    groups: dict[str, list[str]] = {ch: [ch] for ch in children}
    member_of: dict[str, str] = {ch: ch for ch in children}

    def q_of() -> float:
        return modularity(weights, member_of)[1]

    current_q = q_of()
    while len(groups) > 1:
        best: tuple[float, str, str] | None = None
        for pair in weights:
            a, b = sorted(pair)
            ga, gb = member_of[a], member_of[b]
            if ga == gb or len(groups[ga]) + len(groups[gb]) > FANOUT_SOFT_HI:
                continue
            ga, gb = sorted((ga, gb))
            trial = dict(member_of)
            for node in groups[gb]:
                trial[node] = ga
            delta = modularity(weights, trial)[1] - current_q
            cand = (delta, ga, gb)
            if best is None or cand[0] > best[0] or (cand[0] == best[0] and cand[1:] < best[1:]):
                best = cand
        if best is None or best[0] <= 0:
            break
        _, ga, gb = best
        for node in groups.pop(gb):
            member_of[node] = ga
            groups[ga].append(node)
        current_q = q_of()

    # Attach edge-less / singleton leftovers by dir-prefix affinity (never propose a 1-box group).
    multi = {g: sorted(mem) for g, mem in groups.items() if len(mem) > 1}
    if not multi or len(multi) == 1 and len(next(iter(multi.values()))) == len(children):
        return []
    singles = sorted(ch for g, mem in groups.items() if len(mem) == 1 for ch in mem)
    for ch in singles:
        ch_dir = _container_dir(m, ch) or ""
        def affinity(gmem: list[str]) -> int:
            return max((len(_segmentwise_lcp([ch_dir, _container_dir(m, o) or ""]))
                        for o in gmem), default=0)
        target = max(sorted(multi), key=lambda g: (affinity(multi[g]), -len(multi[g])))
        multi[target].append(ch)
    parent_lcp = _segmentwise_lcp([d for c in children if (d := _container_dir(m, c))])
    proposals = [Proposal(*name_seed(m, mem, parent_lcp),
                          members=[(c, _display_name(m, c)) for c in mem])
                 for _, mem in sorted(multi.items())]
    _dedup_names(m, proposals)
    return proposals


def fanout_band(m: ProjectModel) -> tuple[int, int]:
    """(in_band, total) over the S-forest diagrams — the ONE definition of "reads at target density".

    This was written twice: once for the `coyomap balance` headline and once for the eval profile's
    `fanout_in_band_pct`. Both documented the same rule in prose ("diagrams in the 3–9 band,
    exemptions included") over two different computations, and the two had already drifted in TWO
    ways — which is why the whole measurement lives here and not just a membership predicate:

      * the EXEMPT test — the report keyed off its own display flag, which is never `exempt` below
        `FANOUT_SOFT_HI`, while the profile counted any homogeneous family at `≤ FANOUT_HOMOG_HI`.
        A 2-child homogeneous subsystem was therefore in-band for one and out for the other.
      * the DENOMINATOR — the report counts one row per subsystem INCLUDING childless ones; the
        profile skipped them. On any map with an empty subsystem the two fractions differ for no
        reason a reader could see.

    A shared boolean would have fixed the first and left the second, so the fraction could still
    disagree. Returning both halves is what makes them one number.

    This is a MEASUREMENT, not a policy. What is worth flagging to a human is a separate decision
    (`balance`'s findings list), and deliberately narrower: SPARSE is an anti-pattern at the root
    only, so a thin non-root diagram is counted out-of-band here and still raises no finding. The
    report must say which of the two it is printing; a live report put "14/15" directly above
    "No balance findings — every diagram reads at target density."
    """
    per = fanout_band_by_diagram(m)
    return sum(1 for ok in per.values() if ok), len(per)


def fanout_band_by_diagram(m: ProjectModel) -> dict[str | None, bool]:
    """`{diagram id (None = root): is it in band}` — the per-diagram half of `fanout_band`.

    Exposed because the report needs to NAME the out-of-band diagrams, and the first attempt at that
    hand-rolled a second predicate (`n < FANOUT_LO`). It disagreed with this one on a 2-child
    homogeneous subsystem, so the report printed "4/4 diagrams in band" directly above "1 below the
    band" — reintroducing, two lines apart, the contradiction the shared measurement removed. One
    definition means one definition, including for the callers that only want a subset of it."""
    if not m.components and not m.subsystems:
        return {}
    children = subsystem_children(m)
    return {sid: (FANOUT_LO <= len(children.get(sid, [])) <= FANOUT_SOFT_HI
                  or (len(children.get(sid, [])) <= FANOUT_HOMOG_HI
                      and is_homogeneous(m, children.get(sid, []))))
            for sid in (None, *(s.id for s in m.subsystems))}


def fanout_summary(m: ProjectModel) -> tuple[int | None, int | None, float | None, int]:
    """(root_fanout, max_fanout, in_band_pct, nesting_depth) over the S-forest diagrams — the
    eval profile's report-only balance fields. In-band is `fanout_band`, shared with the report."""
    if not m.components and not m.subsystems:
        return None, None, None, 0
    children = subsystem_children(m)
    in_band, total = fanout_band(m)
    fans = [len(children.get(sid, [])) for sid in (None, *(s.id for s in m.subsystems))]
    return (len(children.get(None, [])),
            max(fans),
            round(in_band / total, 3) if total else None,
            nesting_depth(m))


def next_free_group_id(m: ProjectModel, prefix: str = "S") -> str:
    """The next unused numeric id for the given group prefix ('S', 'SD', 'CAP' or 'BLK').

    An unknown prefix would search the WRONG array and mint a colliding id in silence, so the
    mapping is exhaustive over the forests rather than a `.get(prefix, m.subsystems)` fallback."""
    arrays = {"S": m.subsystems, "SD": m.subdomains, "CAP": m.capabilities, "BLK": m.blocks}
    if prefix not in arrays:
        raise ValueError(f"next_free_group_id: unknown group prefix '{prefix}' — "
                         f"one of {', '.join(arrays)}")
    arr = arrays[prefix]
    pat = re.compile(rf"^{prefix}(\d+)$")
    used = [int(match.group(1)) for g in arr if (match := pat.match(g.id))]
    return f"{prefix}{max(used, default=0) + 1}"
