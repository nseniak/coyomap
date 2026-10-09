"""Impact engine core — project an arbitrary git diff onto the map's anchors (PURE half).

Design: internal/docs/impact-and-update-design.md (Part I). This module is stdlib-only and does
NO git/IO — `impact_git.py` produces its inputs (parsed `-U0` hunks, file texts) and consumes its
outputs. Deliberately independent of the existing diff feature (`viewer/diffmap.py`): fresh names,
no shared state; the small name-status parsing overlap is accepted for now (candidate for later
consolidation).

The line-frame problem, solved with two diffs against the pin P (the map's commit): for a changed
file, take `diff -U0 (P,B)` and `diff -U0 (P,T)`; compare fates at HUNK granularity — a P-region is
unaffected iff BOTH sides carry an identical (minus-range, plus-block) hunk or none. Proven sound
(no false negatives — identical hunk sets applied to P yield byte-identical B and T); direction of
error is false positives only (git's alignment is not canonical). When B or T equals P one side's
hunk list is empty and this degenerates to the trivial exact case.

Resolution ladder (each hit records the rung it reached — the UI never fakes precision):
line (affected P-lines overlap the anchor's line/range) > symbol (overlap the anchor's enclosing
definition extent; edges use a tight ±window instead of the whole enclosing function) > file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from coyomap.anchors import parse_anchor
from coyomap.model import ProjectModel, group_forests

# ── `-U0` unified-diff hunks ──────────────────────────────────────────────────────────────────────

# `@@ -a[,b] +c[,d] @@ ...` — omitted counts mean 1. With -U0, b==0 marks a pure insertion AFTER
# P-line a (a may be 0 = at top); d==0 a pure deletion of P-lines a..a+b-1.
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Hunk:
    """One `-U0` hunk in P's coordinate frame (P is always the LEFT side of both diffs)."""
    p_lo: int                 # first P-line of the minus range; for pure inserts, the line the
                              # insertion follows (0 = before line 1)
    p_len: int                # P-lines replaced/deleted (0 = pure insertion)
    plus: tuple[str, ...]     # replacement/inserted lines (content, no '+' prefix)
    minus: tuple[str, ...]    # removed P-lines (content, no '-' prefix)

    def key(self) -> tuple[int, int, tuple[str, ...]]:
        """Hunk identity for the fate comparison. The minus side is determined by (p_lo, p_len) —
        both diffs share P — so identity is the P-range plus the replacement block."""
        return (self.p_lo, self.p_len, self.plus)


@dataclass
class ParsedDiff:
    hunks: list[Hunk] = field(default_factory=list)
    binary: bool = False


def parse_u0(text: str) -> ParsedDiff:
    """Parse `git diff -U0` output for ONE file pair into hunks (P-frame on the left)."""
    out = ParsedDiff()
    minus: list[str] = []
    plus: list[str] = []
    cur: tuple[int, int] | None = None

    def flush() -> None:
        nonlocal minus, plus, cur
        if cur is not None:
            out.hunks.append(Hunk(cur[0], cur[1], tuple(plus), tuple(minus)))
        minus, plus, cur = [], [], None

    for line in text.splitlines():
        if line.startswith("Binary files ") and line.endswith(" differ"):
            out.binary = True
            continue
        m = _HUNK_RE.match(line)
        if m:
            flush()
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) is not None else 1
            cur = (a, b)
            continue
        if cur is None:
            continue  # headers (---, +++, index, diff --git)
        if line.startswith("-"):
            minus.append(line[1:])
        elif line.startswith("+"):
            plus.append(line[1:])
        # `\ No newline at end of file` and stray context are ignored
    flush()
    return out


# ── the fate comparison (two diffs against the pin) ───────────────────────────────────────────────

@dataclass
class FileFrame:
    """The P-frame effect of B→T on one file: which P-lines the change affects."""
    affected: list[tuple[int, int]] = field(default_factory=list)  # inclusive P-line ranges
    insertions: list[int] = field(default_factory=list)  # P-lines AFTER which content is inserted
    p_absent: bool = False        # file has no P-frame (added after the pin) → symbol/file rungs only
    binary: bool = False
    whitespace_only: bool = False  # every differing hunk is a pure whitespace rewrite
    fully_deleted: bool = False    # the changed side deletes every P-line (deleted-file candidate)

    def touches(self, lo: int, hi: int) -> bool:
        """Does the frame affect the inclusive P-range [lo, hi]? An insertion point k counts when
        content is added after a line of the range (k in [lo, hi]) — inserting right below the
        range's last line is counted on purpose: conservative, false-positives-only doctrine."""
        for a, b in self.affected:
            if a <= hi and lo <= b:
                return True
        return any(lo <= k <= hi for k in self.insertions)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _ws_equal(h: Hunk) -> bool:
    return "".join(h.minus).split() == "".join(h.plus).split()


def frame_from_two_diffs(side_b: ParsedDiff, side_t: ParsedDiff,
                         p_line_count: int | None = None) -> FileFrame:
    """Fold `diff(P,B)` and `diff(P,T)` into the P-lines affected by B→T.

    Identical hunks (same P-range, same replacement block) cancel — that region is a change already
    present at BOTH ends, so B→T is a no-op there. Every unmatched hunk from either side marks its
    P-range affected (or an insertion point when p_len == 0).
    """
    frame = FileFrame(binary=side_b.binary or side_t.binary)
    if frame.binary:
        return frame

    from collections import Counter
    b_keys = Counter(h.key() for h in side_b.hunks)
    t_keys = Counter(h.key() for h in side_t.hunks)
    unmatched_b = [h for h in side_b.hunks
                   if t_keys.get(h.key(), 0) < 1 or b_keys[h.key()] > t_keys[h.key()]]
    unmatched_t = [h for h in side_t.hunks
                   if b_keys.get(h.key(), 0) < 1 or t_keys[h.key()] > b_keys[h.key()]]
    unmatched = unmatched_b + unmatched_t

    ranges: list[tuple[int, int]] = []
    ws_flags: list[bool] = []
    for h in unmatched:
        if h.p_len == 0:
            frame.insertions.append(h.p_lo)
        else:
            ranges.append((h.p_lo, h.p_lo + h.p_len - 1))
        ws_flags.append(_ws_equal(h))
    frame.affected = _merge_ranges(ranges)
    frame.insertions = sorted(set(frame.insertions))
    frame.whitespace_only = bool(ws_flags) and all(ws_flags)
    if p_line_count and frame.affected == [(1, p_line_count)] and not frame.insertions:
        # Deletion candidate ONLY when the TARGET side removes every P-line — a file absent at
        # BASE (all-deleted on the B side) is being ADDED by B→T, never deleted.
        deleted = sum(h.p_len for h in unmatched_t if not h.plus)
        frame.fully_deleted = deleted >= p_line_count
    return frame


# ── anchors: the direct-hit seed set from the model ───────────────────────────────────────────────

@dataclass(frozen=True)
class AnchorRef:
    """One code anchor carried by a map element (the direct-hit seed set)."""
    eid: str                  # element id, or a synthetic id for id-less rows (edge:…, ep:…, step:…)
    kind: str                 # component|entity|dep|edge|flow_step|entry_point|glossary|security|
                              # run_command|non_entity_type|group
    path: str                 # repo-relative (dir anchors keep NO trailing slash; see is_dir)
    lo: int | None
    hi: int | None
    field: str                # which model field carried the anchor
    is_dir: bool = False
    owner: str | None = None  # e.g. an entry point's component — ripple seed for M2


def _ref(eid: str, kind: str, raw: str | None, fld: str, owner: str | None = None) -> AnchorRef | None:
    if not raw:
        return None
    raw = raw.strip()
    if raw.endswith("/"):
        return AnchorRef(eid, kind, raw.rstrip("/"), None, None, fld, is_dir=True, owner=owner)
    loc = parse_anchor(raw)
    if loc is None:
        return None  # prose (contains whitespace) — not an anchor
    # A single bare word with no path/line/extension signal ("Makefile", "cron") parses as a path
    # but is indistinguishable from prose — reject it, like anchors.is_file_anchor does.
    if "/" not in raw and ":" not in raw and "." not in raw:
        return None
    return AnchorRef(eid, kind, loc.path, loc.lo, loc.hi, fld, owner=owner)


def anchor_index(model: ProjectModel) -> list[AnchorRef]:
    """Every code anchor in the map, by element — components (source/files/evidence/entry_point),
    entities, deps (where_configured + evidence), backbone edges (`where`), flow steps (`where` —
    a step's own precise call site, so a changed line hits the step directly and ripples to its use
    case), entry points, glossary, security rows, run_commands, non_entity_types, and groups
    (EVERY forest — subsystems/subdomains/capabilities/blocks — the territory seeds), and a
    role INCLUSION's grant line. HP and use cases carry no anchors (ripple-only, by design — they
    inherit precision from their steps)."""
    out: list[AnchorRef] = []

    def add(r: AnchorRef | None) -> None:
        if r is not None:
            out.append(r)

    for c in model.components:
        add(_ref(c.id, "component", c.source, "source"))
        for f in c.files:
            add(_ref(c.id, "component", f, "files"))
        for ev in c.evidence:
            add(_ref(c.id, "component", ev.file, "evidence"))
    for d in model.deps:
        add(_ref(d.id, "dep", d.where_configured, "where_configured"))
        for ev in d.evidence:
            add(_ref(d.id, "dep", ev.file, "evidence"))
    for iface in model.interfaces:
        add(_ref(iface.id, "interface", iface.source, "source"))
        for ev in iface.evidence:
            add(_ref(iface.id, "interface", ev.file, "evidence"))
    for e in model.entities:
        add(_ref(e.id, "entity", e.source, "source"))
    for n in model.non_entity_types:
        add(_ref(f"net:{n.name}", "non_entity_type", n.source, "source"))
    for g in model.glossary:
        add(_ref(f"glossary:{g.term}", "glossary", g.source, "source"))
    for ep in model.entry_points:
        add(_ref(f"ep:{ep.source}", "entry_point", ep.source, "source", owner=ep.component))
        # The line DECLARING a self-started way in's schedule is often far from its own source: a
        # changed cron line is a change to that way in, under the way in's own id, which belongs to
        # no box, so the gate counts nothing new and `challenge` re-argues the schedule statement.
        add(_ref(f"ep:{ep.source}", "entry_point", ep.cadence_source, "cadence_source", owner=ep.component))
    for ed in model.edges:
        if ed.where:
            add(_ref(f"edge:{ed.src}>{ed.verb}>{ed.dst}", "edge", ed.where, "where"))
    for fl in model.flows:
        for st in fl.steps:
            if st.where:  # `validate` guarantees `n` is unique within a flow, so the id is stable
                add(_ref(f"step:{fl.uc}:{st.n}", "flow_step", st.where, "where", owner=fl.uc))
    for sf in model.subflows:
        for st in sf.steps:
            if st.where:  # a sub-flow step's hit ripples to EVERY referencing use case (impact_ripple)
                add(_ref(f"step:{sf.id}:{st.n}", "flow_step", st.where, "where", owner=sf.id))
    for s in model.security:
        add(_ref(f"security:{s.surface}", "security", s.source, "source"))
    # A role INCLUSION's grant line. Roles were listed above as carrying no anchors, and that was
    # true until `includes` gained a `source`: an inclusion is an access claim ("may do everything
    # the other may do"), so its anchor has to face `--check-sources` like every other one. Without
    # this an entirely invented grant line passed the existence gate, and change impact never
    # rippled an edit of that line to the role.
    for r in model.roles:
        for rel in (r.relations or []):
            add(_ref(r.id, "role", rel.source, "relations[].source"))
    for br in model.rules:
        # `owner=` carries the rule id, following the `ep:` pattern, so a changed site ripples to the
        # rule AND onward to what the rule reaches (impact_ripple).
        for i, site in enumerate(br.sites):
            add(_ref(f"rule:{br.id}:{i}", "rule_site", site.where, "where", owner=br.id))
    for r in model.run_commands:
        add(_ref(f"run:{r.action}", "run_command", r.source, "source"))
    for grp in group_forests(model):
        add(_ref(grp.id, "group", grp.source, "source"))
    return out


def link_index(model: ProjectModel) -> list[AnchorRef]:
    """Every code LINK the map carries: `anchor_index`, plus the links that seed no impact hit —
    a lifecycle's `states.source`, a channel's `source`, a
    group's `tech_source`, a deployment variant's `source`, and a test row's cited files: the
    file fields `validate` checks as anchors. (A deployment unit's `config_source` is free prose,
    which `validate` reads as text; "frontend/vite.config.ts." would parse as a link to nothing.) `reanchor` moves all of them: a link it does not walk keeps its old
    line, and the 2026-10-09 mcpolis update re-pointed 20 cadence links by hand after their
    files shifted. The impact report keeps its own list; widening what it counts as a hit is a
    change to the gate, decided on its own."""
    out = anchor_index(model)

    def add(r: AnchorRef | None) -> None:
        if r is not None:
            out.append(r)

    for kind, rows in (("entity", model.entities), ("component", model.components)):
        for el in rows:
            if el.states is not None:
                add(_ref(el.id, kind, el.states.source, "states.source"))
    for mr in model.messaging:
        add(_ref(f"messaging:{mr.name}", "messaging", mr.source, "source"))
    for grp in group_forests(model):
        add(_ref(grp.id, "group", grp.tech_source, "tech_source"))
    for d in model.deployment:
        for v in d.variants:
            add(_ref(f"deployment:{d.unit}", "deployment", v.source, f"variants[env={v.env}].source"))
    for i, tr in enumerate(model.tests):
        for j, ev in enumerate(tr.tests):
            add(_ref(f"tests[{i}]", "tests", ev.file, f"tests[{j}].file"))
    return out


def anchors_by_file(anchors: list[AnchorRef]) -> dict[str, list[AnchorRef]]:
    """File anchors grouped by exact path (dir anchors are matched separately by prefix)."""
    out: dict[str, list[AnchorRef]] = {}
    for a in anchors:
        if not a.is_dir:
            out.setdefault(a.path, []).append(a)
    return out


def dir_anchors_for(anchors: list[AnchorRef], path: str) -> list[AnchorRef]:
    """Dir anchors whose territory contains `path`, LONGEST prefix first — among ALL dir anchors
    (component territories nest inside each other and inside groups; the deepest wins)."""
    hits = [a for a in anchors if a.is_dir and (path.startswith(a.path + "/") or path == a.path)]
    return sorted(hits, key=lambda a: -len(a.path))


# ── hit resolution (the ladder) ───────────────────────────────────────────────────────────────────

# An edge's (or flow step's) `where` is one call-site line; its enclosing function may be long, so
# the symbol rung for call-site anchors is a tight window around the anchor, never the whole
# enclosing extent.
EDGE_SYMBOL_WINDOW = 3

#: Anchor kinds whose claim is "THIS LINE ACTS" — an example call site, a step's own call site, an
#: auth check, a rule's enforcement site. They take the tight window above rather than the enclosing
#: definition's span. `security` was outside it while claiming to be an enforcement point, and a
#: rule SITE is the same shape; both are fixed here together.
_CALL_SITE_KINDS = ("edge", "flow_step", "security", "rule_site")

Extent = tuple[int, int, str, str]  # (start, end, name, kind) — preindex `symbols.extents` rows


@dataclass(frozen=True)
class DirectHit:
    eid: str
    kind: str
    path: str                 # the P-frame path the anchor names
    change: str               # modified|added|deleted|drifted
    resolution: str           # line|symbol|file
    field: str
    owner: str | None = None
    drift_to: int | None = None  # for change=="drifted": the anchor's new start line at T
    territory: bool = False   # a dir-anchor claim (no finer anchor matched) — ranked below ripples


def enclosing_extent(extents: list[Extent], line: int) -> Extent | None:
    """The INNERMOST definition interval containing `line` (extents may nest: method in class)."""
    best: Extent | None = None
    for lo, hi, name, kind in extents:
        if lo <= line <= hi and (best is None or hi - lo < best[1] - best[0]):
            best = (lo, hi, name, kind)
    return best


def _find_block(block: list[str], text: list[str]) -> int | None:
    """1-based start line of `block` as a contiguous run inside `text`, or None. Blank-heavy or
    tiny blocks are not evidence of a move — require some substance."""
    body = [ln for ln in block if ln.strip()]
    if len(body) < 2:
        return None
    n = len(block)
    for i in range(len(text) - n + 1):
        if text[i:i + n] == block:
            return i + 1
    return None


def resolve_hits(refs: list[AnchorRef], frame: FileFrame, extents: list[Extent],
                 status: str, p_text: list[str] | None = None,
                 t_text: list[str] | None = None) -> list[DirectHit]:
    """Resolve one changed file's anchors against its P-frame. `status` is the B→T name-status
    letter (A/M/D/R…). Every anchor in a changed file is at least a file-rung hit; the ladder
    upgrades to symbol/line where the frame reaches the anchor; a fully-covered anchor whose
    extent text survives verbatim at T is ANCHOR DRIFT, not a change."""
    hits: list[DirectHit] = []
    if status == "D" or frame.fully_deleted:
        return [DirectHit(a.eid, a.kind, a.path, "deleted", "file", a.field, a.owner) for a in refs]
    if frame.p_absent:
        # The file has no P-frame. A map anchor pointing at it can only exist if the map already
        # (wrongly or presciently) names it — surface at file rung. (A file with status "A" that
        # DOES exist at the pin — added between base and pin — keeps its P-frame and resolves
        # normally; the caller labels those hits "added".)
        return [DirectHit(a.eid, a.kind, a.path, "added", "file", a.field, a.owner) for a in refs]

    for a in refs:
        change, resolution, drift_to = "modified", "file", None
        if a.lo is not None:
            lo, hi = a.lo, a.hi if a.hi is not None else a.lo
            ext = None if frame.binary else enclosing_extent(extents, lo)
            # A call-site-shaped anchor names ONE acting line inside a definition, not the
            # definition, so the enclosing span is the wrong neighbourhood: a change anywhere in a
            # 200-line function would read as a symbol-rung hit on a line it never touched.
            if a.kind in _CALL_SITE_KINDS:
                w_lo, w_hi = max(1, lo - EDGE_SYMBOL_WINDOW), hi + EDGE_SYMBOL_WINDOW
                sym_span: tuple[int, int] | None = (w_lo, w_hi)
            else:
                sym_span = (ext[0], ext[1]) if ext else None
            if frame.touches(lo, hi):
                resolution = "line"
            elif sym_span and frame.touches(sym_span[0], sym_span[1]):
                resolution = "symbol"
            # moved-but-unchanged (anchor drift): the definition's P-lines are all replaced/deleted,
            # nothing was inserted INTO it, and its exact text survives verbatim at T. Surrounding
            # blank-line noise lumped into the same hunk does not defeat the classification.
            if resolution != "file" and ext and p_text and t_text:
                intact = _fully_covered(frame.affected, ext) and not any(
                    ext[0] <= k < ext[1] for k in frame.insertions)
                if intact:
                    at = _find_block(p_text[ext[0] - 1:ext[1]], t_text)
                    if at is not None:
                        change, drift_to = "drifted", at
        hits.append(DirectHit(a.eid, a.kind, a.path, change, resolution, a.field, a.owner, drift_to))
    return hits


def _fully_covered(ranges: list[tuple[int, int]], ext: Extent) -> bool:
    """Every line of the extent falls in some affected range (the whole definition was disturbed)."""
    line = ext[0]
    for a, b in sorted(ranges):
        if a > line:
            return False
        if b >= line:
            line = b + 1
        if line > ext[1]:
            return True
    return line > ext[1]
