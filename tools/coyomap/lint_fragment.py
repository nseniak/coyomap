"""`coyomap lint-fragment` — the per-fragment self-check a harvest/trace sub-agent runs BEFORE it
returns its fragment.

Today nothing checks a fragment until the LEAD assembles all of them and patches the errors by
guessing, serially. This moves the fix into the agent's own context (where it has the knowledge) and
in parallel: schema, anchor format, `extra`-key conventions, and — with `--repo` — that every anchor's
file actually exists (so a wrong repo-root prefix or a stale line is caught at the source, not by the
lead's `validate`). Reports every finding it can in one pass. Stdlib-only (the cli.py firewall).

**`--finalize` fuses the write to the check.** The method has agents write `<id>.draft.json` and
RENAME to `<id>.json` only when complete, because `assemble` skips a `.draft.json` and a half-written
fragment must never assemble. But the rename was a separate step done by hand, so the loop was
write → lint → fix → lint → rename, and the rename could happen after a lint that had failed —
nothing connected the two. With `--finalize` the rename IS the lint's exit: a draft becomes a
fragment only by passing, and it is all-or-nothing across the batch, because a half-landed fan-out
is a map missing one slice with every gate green.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from coyomap import grammar, prose, provenance
from coyomap.anchors import parse_anchor
from coyomap.reporting import clip, reset_full_lists, set_full_lists, shown
from coyomap.assemble import fragment_schema_errors, load_fragment
from coyomap.model import ID_SHAPE, ModelError, ProjectModel, access_rules, all_elements
from coyomap.validate_model import (
    _cadence_row_warnings,
    _check_activations,
    _check_anchor_format,
    _check_edges,
    _check_entry_kinds,
    _check_extra_conventions,
    _check_flows,
    _check_messaging,
    _check_states,
    _check_stores,
    _granularity_warnings,
    confidence_warnings,
    _referenced_ids,
    check_anchor_existence_model,
    check_operative_lines_model,
    check_domain_relations,
    door_arrival_sources,
    check_entity_sources_model,
    rule_row_problems,
    domain_card_shape_problems,
    reciprocal_relation_problems,
    duplicate_security_warnings,
    nobody_at_door_warnings,
    roleless_cd_verb_warnings,
    subflow_refcount_warnings,
    walk_jumps,
)

def arrivals_from(sources: list[Path]) -> dict[str, set[tuple[str, int | None]]]:
    """`{interface id: its ways in's source lines}` from the JSON files `--ids` names — the
    sibling fragments or the assembled map. A doors fragment carries no ways in, and without them
    every arrival anchored on its way in's own line reads as drift (`door_arrival_sources`)."""
    sources_of: dict[str, str] = {}
    ways: dict[str, list[str]] = {}
    for src in sources:
        if src.suffix != ".json":
            continue
        try:
            doc = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        for ep in _rows(doc, "entry_points"):
            if isinstance(ep, dict) and ep.get("id") and ep.get("source"):
                sources_of[str(ep["id"])] = str(ep["source"])
        for iface in _rows(doc, "interfaces"):
            if isinstance(iface, dict) and iface.get("id"):
                ways.setdefault(str(iface["id"]), []).extend(
                    str(w) for w in iface.get("ways_in") or [])
    out: dict[str, set[tuple[str, int | None]]] = {}
    for iid, ws in ways.items():
        locs = [parse_anchor(sources_of.get(w, "")) for w in ws]
        out[iid] = {(loc.path, loc.lo) for loc in locs if loc is not None}
    return out


def _rows(doc: dict[str, object], key: str) -> list[object]:
    """`doc[key]` when it is a list, else nothing: a file `--ids` names is any JSON at all, and a
    non-list where rows belong is not the map's shape, so it holds no rows."""
    rows = doc.get(key)
    return rows if isinstance(rows, list) else []


def our_doors_from(sources: list[Path]) -> set[str]:
    """The ids of OUR surfaces in the JSON files `--ids` names. A trace fragment holds no interfaces,
    so without them the check for a door nobody stands at cannot tell our door from someone else's
    sign-in page, and stays silent; it stays silent too on a markdown legend, which states no side."""
    out: set[str] = set()
    for src in sources:
        if src.suffix != ".json":
            continue
        try:
            doc = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        out.update(str(i["id"]) for i in _rows(doc, "interfaces")
                   if isinstance(i, dict) and i.get("id") and i.get("side") == "ours")
    return out


# id-SHAPED but unknown-prefix tokens ('SEC1') can never resolve — catchable per-fragment, unlike a
# full undefined-reference check (which needs the whole map, or the --ids universe below).
_ID_LIKE = re.compile(r"^[A-Z]+\d+$")


def _check_reference_shapes(m: ProjectModel) -> list[str]:
    """Reference tokens that LOOK like ids but use a prefix outside the id vocabulary — the
    'tests target SEC1' class: fragment lint used to pass them, and they died only at the lead's
    final validate. A prefix that isn't in the vocabulary can never resolve, so it's a fragment bug."""
    problems: list[str] = []
    for i, tr in enumerate(m.tests):
        for t in tr.targets:
            if _ID_LIKE.match(t) and not ID_SHAPE.match(t):
                problems.append(f"tests[{i}] target '{t}': unknown id prefix — a target must be a "
                                "defined element id (UC/HP/CAP/S/SD/SF/C/D/E/I/R/EP/BLK/BR + digits)")
    return problems


def _id_prefix(tok: str) -> str:
    """The id's leading letters (its namespace): `UC19`→`UC`, `SD2`→`SD`, `C5`→`C`."""
    mo = re.match(r"[A-Z]+", tok)
    return mo.group(0) if mo else ""


def lint_unknown_references(m: ProjectModel, known_ids: set[str]) -> list[str]:
    """With `--ids` (the lead's legend or the assembled map), every cross-reference in the fragment
    must resolve to the fragment's own definitions or the known universe — so an INVENTED id (the
    'tests target C112' class: plausible-looking, defined nowhere) dies in the authoring agent's
    turn instead of at the lead's final validate."""
    defined = set(all_elements(m)) | {g.id for g in m.happy_path} | known_ids
    out: list[str] = []
    # Gate the flag by NAMESPACE presence in the known universe (mirrors the actor/roles gate below):
    # a trace fragment's flow `uc` (`UC13`) is a real reference to a use case defined in the BEHAVIORAL
    # fragment, but a reduced trace legend lists only element ids (`C/E/D/R/S`), so without this gate
    # every trace fragment false-positives on its own `uc` values (the mcpolis build hand-worked around
    # this on ~7 agents). A namespace the universe doesn't cover at all can't be adjudicated — invented
    # vs. legit-but-omitted is indistinguishable. Element namespaces are always present, so
    # `tests target C112` still fails; a full-map legend contains `UC` ids, so an invented `UC99` inside
    # a behavioral fragment that defines `UC1..20` is still caught.
    known_prefixes = {_id_prefix(k) for k in defined}
    unresolved = sorted(r for r in _referenced_ids(m) - defined if _id_prefix(r) in known_prefixes)
    if unresolved:
        out.append(f"references ids defined neither in this fragment nor in --ids: "
                   f"{', '.join(unresolved)}")
    # A flow/sub-flow actor endpoint that is neither a backbone element id nor a KNOWN Role id is a
    # display name used where an Rn id belongs ("Team member" instead of R1). validate's actor check
    # self-disables in a roles-less trace fragment (roles live in the behavioral fragment), so without
    # the --ids universe this class survives to the lead's full validate — a whole reconcile phase
    # later, which both fresh builds hit and hand-patched. Gate on the universe actually HAVING roles:
    # a genuinely roles-less project may use display-name actors (a documented tolerance), and with no
    # role ids in --ids we can't tell "should be Rn" from "legit display name" — so only fire when the
    # legend proves roles exist, where a display-name endpoint is then unambiguously a mistake.
    if any(grammar.is_role_id(k) for k in known_ids):
        bad_actors: list[str] = []
        for label, steps in ([(f.uc, f.steps) for f in m.flows]
                             + [(sf.id, sf.steps) for sf in m.subflows]):
            for st in steps:
                if st.subflow:
                    continue  # a reference step's endpoints are the bridged backbone ids
                for end in (st.src, st.dst):
                    if end and not grammar.is_step_id(end) and not grammar.is_role_id(end) \
                            and end not in defined:
                        bad_actors.append(f"{label} step {st.n}: '{end}'")
        if bad_actors:
            out.append("actor endpoint(s) not a known Role id — reference the role by its Rn id from "
                       f"the legend, not a display name: {', '.join(bad_actors)}")
    return out


def lint_fragment_problems(m: ProjectModel, repo_root: Path | None,
                           known_ids: set[str] | None = None) -> list[str]:
    """Every non-schema problem in one (partial) fragment: anchor format + `extra`-key conventions +
    the domain-relation rules (`keyed_by` misuse, verb alias, cardinality, dup) + the per-edge rules
    (missing/contradictory `where`, empty verb, intra-fragment dup), plus — when a repo root is given
    — that each anchor / entity source actually exists. This is the shift-left: an authoring agent
    catches its own `keyed_by`/edge mistakes in-context instead of the lead reconciling them a phase
    later at `validate`. Edge-level *warnings* (e.g. `no_call_site` + `where` together) are surfaced as
    lint problems here — at authoring time they are worth fixing before returning the fragment."""
    problems: list[str] = list(_check_anchor_format(m))
    problems += _check_activations(m)  # row-local vocabulary check — an invalid `activation` is a
    # fragment bug (a truthy near-miss would silently reroute the row through the kind heuristic)
    extra_problems, _extra_warnings = _check_extra_conventions(m)
    problems += extra_problems
    rel_problems, _rel_warnings = check_domain_relations(m.entities)
    problems += rel_problems
    # The per-card SHAPE rules (meaning / source / fields / field types), shared verbatim with
    # `validate`. Every one is row-local, so a fragment CAN answer them — they simply ran only on
    # the assembled map, which is how a T5 fragment linted clean and then failed the lead's
    # `validate` a phase later, eight cards at a time.
    problems += domain_card_shape_problems(m.entities)
    # The same reciprocal check `validate` runs. Omitting it let a T5 fragment self-check OK
    # and fail the assembled map on 33 of these, all of them inside that one fragment.
    problems += reciprocal_relation_problems(m.entities)
    problems += _check_stores(m)  # row-local store-shape rules (dep id shape, closed mode); the
    # folded-dep check self-disables when the fragment doesn't define the dep (it can't resolve it)
    state_problems, _state_warnings = _check_states(m)  # row-local machine rules (empty list, dup
    problems += state_problems                          # names, undeclared transition endpoint)
    msg_problems, _msg_warnings = _check_messaging(m)   # row-local channel rules (id shapes,
    problems += msg_problems                            # dup names); the backing-edge advisory
    # stays out — the edges usually live in another fragment
    edge_problems, edge_warnings = _check_edges(m)
    problems += edge_problems + edge_warnings
    # Flow rules (missing step `where`, duplicate step n, missing phrase/endpoint) fail in the trace
    # agent's own turn, not a phase later at the lead's `validate`. Safe on a partial fragment: the
    # actor-id check self-disables when the fragment defines no roles. Warnings promoted, like edges'.
    flow_problems, flow_warnings = _check_flows(m)
    # A step referencing a sub-flow DEFINED IN A SIBLING FRAGMENT is legal (per-agent SF id ranges
    # make collisions impossible; the map assembles whole) — but this fragment can't see it, so the
    # undefined-sub-flow problem false-fires. With an `--ids` universe that KNOWS the SF id, drop
    # that problem; without one, it stands (an invented SF must still die here). A live rebuild
    # duplicated a shared trace inline because this filter didn't exist.
    if known_ids:
        flow_problems = [p for p in flow_problems
                         if not (( mo := re.search(r"references undefined sub-flow '(SF\d+)'", p))
                                 and mo.group(1) in known_ids)]
    problems += flow_problems + flow_warnings
    problems += _check_reference_shapes(m)
    # The T7 rule rules (a statement, at least one site, an anchored OPERATIVE line per site) — all
    # row-local, so a per-block fragment CAN answer them. Here rather than only at the lead's
    # `validate` for the same reason the flow rules are: a block agent writing eight rules should
    # fail on its own bad anchor in its own turn, not eight rules later in someone else's report.
    # The WHOLE-MAP rules stay out — the sweep canary (a fragment holds one block's rules, so every
    # other block's decisions would read as debt) and the `Component.files` gate (they live in a
    # different fragment, so a block agent would fail its lint on a defect it cannot fix).
    problems += rule_row_problems(m)
    # …plus the one row-local rule `validate` does NOT share: an access rule with no `risk`. See
    # `_access_rule_risk_problems` — the gate is on the fragment being written, not on a built map.
    problems += _access_rule_risk_problems(m)
    # `block` is a SYNTHESIS assignment, exactly like `capability`: a `BLK` id is minted before the
    # rules exist, and a re-synthesis that renumbers blocks must not silently re-point every rule.
    # The method says "never in the fragment"; without this the rule is prose, and a fragment
    # carrying `block` lints clean and assembles with the value intact.
    problems += _interface_shape_problems(m)
    in_fragment = [r.id for r in m.rules if r.block]
    if in_fragment:
        problems.append(
            f"business rule(s) carry `block` in a fragment: {', '.join(in_fragment)} — block "
            "assignment goes through the synthesis `reconcile` (`coyomap reconcile`), never a "
            "fragment: BLK ids are minted before the rules exist, and a re-synthesis that "
            "renumbers them would leave these pointing at the wrong areas")
    if repo_root is not None:
        roots = [repo_root.resolve()]
        problems += check_anchor_existence_model(m, roots)
        problems += check_entity_sources_model(m, roots)
        problems += _check_pin_matches_the_tree(m, repo_root)
    return problems


def _interface_shape_problems(m: ProjectModel) -> list[str]:
    """Row-local shape rules for the `interfaces` array.

    This file held ZERO references to "interface" until now, so the section the method makes the
    LEAD hand-author was the one section its own self-check could not see. On the 2026-08-29 mcpolis
    build `lint-fragment` printed `LINT OK — 0 problems` on the interfaces fragment and `validate`
    raised seven interface findings on the same content four turns later — and it printed the same
    `LINT OK` again after the evidence was added, so the verdict was identical with and without the
    field `validate` blocks on.

    Only the row-local half lives here, the same division every other array follows: a bad `side`,
    a bad `facing`, a `theirs` surface with no evidence, a `ways_in` that is not an id-shaped token,
    and a `kind` that is neither a seed nor a deliberate mint. Cross-array resolution (does `EP99`
    exist, is it externally activated, does every way in belong to exactly one surface) needs the
    assembled map and stays in `validate`."""
    problems: list[str] = []
    minted: list[str] = []
    for iface in m.interfaces:
        if iface.side and iface.side not in grammar.INTERFACE_SIDES:
            problems.append(
                f"{iface.id}: `side` is '{iface.side}' — it must be one of "
                f"{', '.join(grammar.INTERFACE_SIDES)} (ours = a surface the product offers, "
                f"theirs = one it reaches out to)")
        if iface.facing and iface.facing not in grammar.INTERFACE_FACINGS:
            problems.append(
                f"{iface.id}: `facing` is '{iface.facing}' — it must be one of "
                f"{', '.join(grammar.INTERFACE_FACINGS)}")
        for ep in iface.ways_in:
            if not _ID_LIKE.match(str(ep)):
                problems.append(
                    f"{iface.id}: `ways_in` holds '{ep}', which is not an id — a way in is an entry "
                    f"point id (`EP12`), never a path or a name")
        if iface.side == "theirs" and not (
                [e for e in iface.evidence if getattr(e, "file", "")] or iface.source):
            problems.append(
                f"{iface.id}: a `theirs` surface carries no evidence and no `source` — whose data "
                f"crosses cannot be read off a call site, so the one line you read is the whole "
                f"claim. `validate` blocks on this; answering it here costs one turn instead of a "
                f"phase")
        canon = grammar.canonical_interface_kind(iface.kind)
        if canon and canon.lower() in grammar.INTERFACE_KIND_PURPOSE_WORDS:
            problems.append(
                f"{iface.id}: `kind` is '{iface.kind}', which says what the surface is FOR, not "
                f"what SHAPE it is — that axis is the dependency's `bucket`. A payment processor "
                f"and a crash reporter are both `api`")
        elif canon and canon not in grammar.INTERFACE_KIND_SEEDS:
            minted.append(f"{iface.id}: '{canon}'")
        elif canon and canon != (iface.kind or "").strip():
            problems.append(
                f"{iface.id}: `kind` is '{iface.kind}' — the canonical spelling is '{canon}'. One "
                f"spelling per shape, or two builds of one repo split the same surface")
    if minted:
        # ONE aggregated line, never one per row: a minted kind is LEGAL (the vocabulary is
        # seeded-open) and the author is the one who adjudicates whether it is a synonym.
        problems.append(
            f"{len(minted)} interface kind(s) are not seeds: {'; '.join(minted)}. Minting is "
            f"allowed — check first that none is a spelling of a seed "
            f"({', '.join(grammar.INTERFACE_KIND_SEEDS)}), and reuse the exact spelling on rebuild")
    return problems


def _check_pin_matches_the_tree(m: ProjectModel, repo_root: Path) -> list[str]:
    """A header fragment claiming a bare sha while the working tree carries uncommitted code.

    `method.md` requires `<short-sha>-dirty` when the operator proceeds on a dirty tree, and
    `dispatch.md` reads the suffix back. Nothing wrote it and nothing checked it, so a build that had
    been offered — and had accepted — a `-dirty` pin hand-wrote the bare sha, passed this very lint
    clean, and shipped a map whose anchors do not resolve at the commit it names. Nine of its ten
    anchors into one file another session edited mid-build point at the wrong lines today.

    Needs `--repo`, because the tree is the evidence. Silent where git cannot answer, where the
    fragment carries no pin, and where the pin is already suffixed — the failure mode of a check that
    guesses about a repo it cannot read is worse than the gap it closes."""
    pin = (m.commit or "").strip()
    if not pin or pin.endswith("-dirty"):
        return []
    dirty = provenance.dirty_paths(repo_root)
    if not dirty:
        return []
    listed = shown(list(dirty), 5, unit="path(s)")
    return [f"header pin `{pin}` says the map describes commit {pin}, but {len(dirty)} path(s) are "
            f"changed and not committed: {listed}. Either commit them and re-stamp, or record the pin "
            f"as `{pin}-dirty` (method.md) — `coyomap provenance stamp --update-header <header>` "
            f"writes the suffix for you. coyomap's own .coyomap/ and .coyomap-eval/ do not count."]


def _legacy_security_warnings(m: ProjectModel) -> list[str]:
    """Advisory: a fragment authoring `security[]`. An auth surface is an `access` business rule
    now — the Security & auth table is a derived view of those. Nothing REJECTS a security row (a
    map built before the fold still loads and still renders its rows), so this is where a NEW build
    finds out, in the authoring agent's own turn rather than never."""
    if not m.security:
        return []
    return [f"{len(m.security)} `security[]` row(s) authored — an auth surface is a business rule "
            "with `access: true` now (T7), and the Security & auth table is a derived view of "
            "those. Write the decision, its enforcement site(s) and its `risk`; a security row is "
            "the legacy storage, kept only so a map built before the fold still renders."]


def _access_rule_risk_problems(m: ProjectModel) -> list[str]:
    """BLOCKING: an `access: true` rule with no `risk`.

    method.md requires an auth surface to state "what is at stake as its `risk`", and before the fold
    every security row carried one. After it, two consecutive real builds shipped maps where NOT ONE
    rule of 69 and 96 had a risk — the rendered Security & auth table's Risk column was blank on
    every row — and nothing anywhere said so.

    It was an advisory first, on the reasoning that an author may be mid-draft. Two builds later the
    advisory had changed nothing: a nudge that fires on every rule of a fragment reads as background
    noise, and `risk` is precisely the field a statement, a site and a `why` between them CANNOT
    replace — not what the line does, but what its limit costs.

    Blocking HERE and not in `rule_row_problems`, which `validate` shares: a fragment is being
    written now, by the agent that knows the answer, so it can fix it in its own turn — while an
    already-built map must keep validating, rendering and rebuilding. The gate is on new work."""
    naked = [r.id for r in access_rules(m) if not (r.risk or "").strip()]
    if not naked:
        return []
    # Through `shown`, never a hand-cut `[:12]`: `--all` prints every list whole, and a list cut here
    # by hand was the one it could not reach.
    return [f"{len(naked)} `access: true` rule(s) with an empty `risk`: "
            f"{shown(naked, 12, unit='rule(s)')} — an auth surface must say what is at stake if it "
            f"fails. The Security & auth table renders `risk` as its own column, so an empty one "
            f"ships as a blank cell."]


def _authored_runs_in_warnings(m: ProjectModel) -> list[str]:
    """Advisory: this fragment authors `runs_in`, which is the lead's to assign.

    The deployment-unit NAMES are authored by a different slice running in parallel, so a harvest
    agent cannot know them and writes something plausible — `["backend"]`,
    `["backend","standalone"]`. Its own lint passed clean and the lead's `validate` then raised 17
    BLOCKING `runs_in names unknown deployment unit(s)` lines, hand-patched with a heredoc.

    ADVISORY, not blocking, and the distinction is load-bearing: a LEAD-authored synthesis fragment
    legitimately carries `runs_in` (the committed corpus has one with 35 such rows), and this linter
    cannot tell a synthesis fragment from a harvest slice. It also cannot check the NAME — the
    vocabulary lives in a sibling fragment. What it can do is put the field in front of the agent
    that can explain it, at the moment it is cheap, which is the whole point of the self-check."""
    rows = [c.id for c in m.components if c.runs_in]
    rows += [ep.id or ep.source for ep in m.entry_points if ep.runs_in]
    if not rows:
        return []
    listed = shown([str(x) for x in rows], 6, unit="row(s)")   # `shown`, so `--all` reaches it
    return [f"{len(rows)} row(s) carry `runs_in`: {listed} — if you are a HARVEST slice, drop it: "
            f"`runs_in` is assigned by the lead through `coyomap reconcile` after the fan-out, and "
            f"the deployment-unit names come from a different slice running beside you, so a guess "
            f"passes this lint and hard-fails the lead's `validate`. If you are the lead's own "
            f"synthesis fragment, this is yours to keep."]


def _unowned_entry_point_warnings(m: ProjectModel) -> list[str]:
    """Advisory: a way in that names no owning `component`.

    The owner is what relates a way in to a use case, a coverage count and a deployment unit, and
    `validate` warns on every externally activated way in that has none. The harvest contract's
    field table did not list the field, so on the 2026-10-07 mcpolis build 51 of 221 ways in came
    back unowned and the lead filled 45 of them by hand. The slice that harvested a way in usually
    holds the component that owns it, so the agent that wrote the row is the one who can answer.

    Every way in, not only the externally activated ones `validate` names: a job's owner places it
    in its deployment unit, and the one self-started way in of those 51 had none either. ADVISORY,
    as `validate`'s own line is, and because an owner can sit in another slice, whose ids this agent
    cannot know: that one is assigned at synthesis, by the reconcile file's `component` directive."""
    unowned = [f"[{ep.kind}] {clip(ep.trigger)}" for ep in m.entry_points
               if not ep.component.strip()]
    if not unowned:
        return []
    return [f"{len(unowned)} way(s) in name no owning `component`: "
            f"{shown(unowned, 5, sep='; ', unit='way(s) in')} — set each one's `component` to the "
            f"`Cn` in this fragment whose code holds it, or say in your reply which ones another "
            f"slice owns. `validate` warns on every externally activated way in with no owner, and "
            f"the lead otherwise fills them in by hand."]


#: Below this a fragment is too small for "nearly every row says the same thing" to mean anything —
#: three components read from the same file honestly are all `verified`. Counts only rows that CARRY
#: the field, not every row.
_CONFIDENCE_CONSTANT_MIN = 8

#: How much of one value makes the labelling uninformative. Not 1.0: a single dissenting token is
#: what "use both values" produces from an agent that did not really distinguish, and equality on
#: the value SET let that through — a 301-row fragment with one `inferred` passed.
_CONFIDENCE_CONSTANT_SHARE = 0.95


def _authored_confidence_warnings(m: ProjectModel) -> list[str]:
    """Advisory: a fragment whose `confidence` is a CONSTANT.

    `confidence` says what its author KNEW: `verified` = I read the code and traced it,
    `inferred` = I took it from a name or a convention. That is a fact only the author has, and
    nothing else in the map records it — which is why the field exists and why nothing writes it.

    (It does NOT mean "the skeptics confirmed it". That reading was tried and dropped: no process
    can produce it, so `verified` would be a word nothing could ever legitimately write, and the
    vote status is already DERIVED per element by `coyomap grounding by-element`, where it cannot go
    stale. Two facts, two homes.)

    So the defect is not which value a row carries — it is a fragment that carries only ONE. On the
    2026-08-29 mcpolis map all 301 element-level values said `verified` while `inferred` appeared 64
    times and never once outside the `tests` array. A constant carries no information: it tells a
    reader nothing about which rows were read and which were guessed, while reading as though every
    row was read.

    ADVISORY: a small, carefully-read slice really can be all `verified`, and a single-fragment
    linter cannot tell that from a slice that never distinguished."""
    kinds = (("component", m.components), ("rule", m.rules), ("dep", m.deps),
             ("subsystem", m.subsystems), ("subdomain", m.subdomains),
             ("interface", m.interfaces))
    values = [str(getattr(el, "confidence", "") or "").strip()
              for _kind, group in kinds for el in group
              if str(getattr(el, "confidence", "") or "").strip()]
    # A SHARE, not equality on the value set — see `_CONFIDENCE_CONSTANT_SHARE`.
    from collections import Counter
    if len(values) < _CONFIDENCE_CONSTANT_MIN:
        return []
    only, n = Counter(values).most_common(1)[0]
    if n < len(values) * _CONFIDENCE_CONSTANT_SHARE:
        return []
    return [f"{n} of {len(values)} labelled row(s) in this fragment carry `confidence: {only}` "
            f"— the field says what YOU knew (`verified` = read and traced, `inferred` = taken "
            f"from a name or a convention), so one value across every row tells a reader nothing "
            f"about which rows you read. Measured on one shipped map: 301 of 301 element-level "
            f"values said `verified`. If the slice really was uniform, say so in your reply."]


def lint_fragment_warnings(m: ProjectModel) -> list[str]:
    """Advisory (non-blocking) findings for one fragment — the domain-relation *warnings* (the
    field-less-association nudge, the by-name-FK hint) and the use-case *granularity* signals
    (flow-length band, fused-goal name smell, shared-run duplication). These are HEURISTIC /
    judgment-shaped, so unlike `lint_fragment_problems` they must NOT fail the lint — the authoring
    agent sees them and decides (a long flow may be the lead's call, not the fragment's bug). Kept
    separate from the blocking problems so the fatal/advisory split is explicit.
    The use-case/Happy-Path COMPLETENESS family (`_completeness_warnings`) is deliberately NOT
    here: it relates T4 ↔ flows ↔ HP across the whole map, and a fragment holds only one slice
    (a T4 harvest fragment has no flows; a trace fragment has no entry points) — per-fragment the
    signal is vacuous or a guaranteed false positive, so it runs in `validate` only."""
    _problems, warnings = check_domain_relations(m.entities)
    warnings += _legacy_security_warnings(m)
    warnings += _authored_runs_in_warnings(m)
    warnings += _unowned_entry_point_warnings(m)
    warnings += _authored_confidence_warnings(m)
    # The roleless-C→D-verb nudge rides THIS non-blocking channel (never `lint_fragment_problems`,
    # which would promote it to a blocking problem — trap T7), so an authoring agent SEES it and
    # decides, without a legitimately-generic `uses` failing the lint. The entry-point-kind nudges
    # and the ROW-LOCAL cadence nudges (contradiction / inferred / dangling anchor) ride here too
    # (seeded-OPEN vocabulary and judgment-shaped signals — never fail a fragment); the per-kind
    # COVERAGE contract and the missing-cadence family do not (each relates the whole T4 inventory
    # to an extras heading another fragment may carry — vacuous per-fragment, like
    # `_completeness_warnings`).
    # The sub-flow refcount nudge rides here too — it is judgment-shaped AND per-fragment blind
    # (the other reference may live in a sibling fragment); promoting it to blocking made a live
    # rebuild inline three legitimate sub-flows and ship a fragment its author believed had passed.
    # `duplicate_security_warnings` rides here too: WITHIN one fragment a repeated surface is
    # answerable now, and the cross-fragment case (the common one) still surfaces at validate.
    # PROSE rides here too. `validate` has run the same countable readability check since it
    # existed, but only over the ASSEMBLED map — so a long sentence, an em dash or a raw code name
    # written by a fan-out agent could not be seen until every fragment was merged, at which point
    # the agent that wrote it is gone and the lead is the one editing prose it did not author. The
    # 2026-09-01 argus build surfaced 21 long sentences that way. The check is row-local by
    # construction (one field, one sentence, no cross-fragment reference), so a fragment can answer
    # it alone, which is the test for belonging in a lint. Advisory here for the same reason it is
    # advisory in `validate`: a long sentence is not a wrong map. The glossary comes from the
    # fragment when it has one, which is the same allowance `prose.scan` makes at validate time.
    prose_lines = prose.advisory_lines(m)
    return (warnings + _granularity_warnings(m) + roleless_cd_verb_warnings(m)
            + _check_entry_kinds(m) + _cadence_row_warnings(m) + subflow_refcount_warnings(m)
            + walk_jumps(m)
            + duplicate_security_warnings(m) + confidence_warnings(m) + prose_lines)


# DELIBERATELY ABSENT: a per-fragment nudge about the entry-point per-kind COMPLETENESS statement.
# The information loss it would chase is real — on a live build all twelve harvest agents stated their
# per-kind completeness in their RETURN MESSAGE, no prompt asked for it in a fragment, and the lead's
# validate then flagged 13 kinds with no statement. It still does not belong here. A canonical-kind T4
# harvest fragment is CORRECT, `lint_fragment_warnings` is asserted EMPTY for one on purpose, and an
# advisory that fires on every such fragment is a nag on correct work. The fragment also cannot know
# whether the statement exists: the 'Entry-point coverage' heading is authored by the LEAD, in a
# different fragment. The fix is in the harvest PROMPT — the fragment template must ask for the
# statement — which is a method change, not a lint check. (Tried as a warning; reverted.)


#: How far a slice may miss its dispatched component budget before `--expect` says so. Wide on
#: purpose: the budget is a pre-read estimate, and a slice that finds 7 where 5 were guessed is
#: normal. What it catches is the systematic overshoot — on a live build the nine code slices were
#: dispatched with budgets summing to ~55 and delivered 86, every slice over, and nothing noticed
#: until the lead's granularity advisory said "86 vs a code-derived ~59" after assembly.
_BUDGET_LO, _BUDGET_HI = 0.5, 1.5


def _budget_warnings(m: ProjectModel, expect: int | None) -> list[str]:
    """Advisory: this fragment's component count against the budget its slice was dispatched with.

    Never blocking. The budget is the lead's estimate, and the authoring agent is the one holding the
    code — if it found more real components than the estimate, the estimate was wrong. The point is
    that the delta becomes visible to the agent that can explain it, in its own turn, instead of
    surfacing as an unattributable total after every fragment has been merged."""
    if expect is None or expect <= 0:
        return []
    n = len(m.components)
    if not n or _BUDGET_LO * expect <= n <= _BUDGET_HI * expect:
        return []
    direction = "over" if n > expect else "under"
    return [f"{n} component(s) against a dispatched budget of ~{expect} ({n / expect:.1f}x, {direction} "
            f"the {_BUDGET_LO:g}x-{_BUDGET_HI:g}x band) — if the slice really holds this many, say so "
            f"in your reply so the lead can record the altitude decision under a 'Balance exceptions' "
            f"extras heading; if it is drift, fold the near-duplicates into one component."]


#: The tail `reporting.shown` puts on a list it cut to its first items (`+7 more field(s)`).
_CUT_LIST_TAIL = re.compile(r"\+\d+ more\b")


def main(argv: list[str] | None = None) -> int:
    """Thin wrapper: whole-list mode (`--all`) is process-wide, so it is reset on EVERY exit path,
    the way `validate` and `audit` reset it after their `--json`. Without the reset, one `--all` run
    in-process would widen every later list in that process."""
    try:
        return _run(argv)
    finally:
        reset_full_lists()


def _run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv or not argv:
        print("usage: coyomap lint-fragment [--repo <root>] [--ids <legend-or-map>] [--expect N]\n"
              "                             [--all] <fragment.json>...\n\n"
              "Self-check a build fragment BEFORE returning it: schema, anchor format, `extra`-key\n"
              "conventions, (with --repo) that every anchor's file exists, and (with --ids) that every\n"
              "cross-referenced id is defined in the fragment or the given id universe — pass the\n"
              "lead's legend (_legend.md) or the assembled project-map.json, so an INVENTED id dies\n"
              "here instead of at the lead's final validate. Reports all findings and exits non-zero\n"
              "on any, so an agent fixes its own rows in context instead of the lead hand-patching\n"
              "them after assembly.\n"
              "--expect N: the component budget this slice was dispatched with. Advisory: warns when\n"
              "  the fragment lands outside 0.5x-1.5x N, so the overshoot is visible to the agent that\n"
              "  caused it rather than only in the lead's granularity advisory after assembly.\n"
              "--finalize: on a CLEAN lint, rename each <id>.draft.json to <id>.json — the rename\n"
              "  the method asks for, done by the check instead of by hand, so a draft can only\n"
              "  become a fragment by passing. All fragments must be drafts, no target may already\n"
              "  exist, and a failing lint renames nothing.\n"
              "--all: print every list whole. A list cut to its first items ends `+N more`; this\n"
              "  prints the rest, so you never rebuild a list the lint already found.")
        return 0 if ("-h" in argv or "--help" in argv) else 2
    repo_root: Path | None = None
    known_ids: set[str] | None = None
    sibling_arrivals: dict[str, set[tuple[str, int | None]]] = {}
    sibling_doors: set[str] = set()
    expect: int | None = None
    finalize = False
    show_all = False
    frags: list[Path] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--finalize":
            finalize = True
        elif a == "--all":
            # Set before any check runs: `shown` reads it while each message is built.
            show_all = True
            set_full_lists(True)
        elif a == "--repo":
            i += 1
            if i >= len(argv):
                print("ERROR: --repo needs a directory", file=sys.stderr)
                return 2
            repo_root = Path(argv[i])
        elif a == "--ids":
            i += 1
            if i >= len(argv) or not Path(argv[i]).exists():
                print("ERROR: --ids needs an existing legend/map file (or a directory of fragments)",
                      file=sys.stderr)
                return 2
            # any format works: the universe is every id-shaped token in the file (a markdown legend,
            # the assembled map, or a plain id list all read the same way). A DIRECTORY scans its
            # *.json/*.md files — pass `build-fragments/` so ids DEFINED by sibling fragments (a
            # trace agent's SF the legend predates) resolve instead of forcing inline duplication.
            ids_path = Path(argv[i])
            sources = (sorted([*ids_path.glob("*.json"), *ids_path.glob("*.md")])
                       if ids_path.is_dir() else [ids_path])
            known_ids = {t for src in sources
                         for t in re.findall(r"\b[A-Z]+\d+\b", src.read_text(encoding="utf-8"))
                         if ID_SHAPE.match(t)}
            sibling_arrivals = arrivals_from(sources)
            sibling_doors = our_doors_from(sources)
        elif a == "--expect":
            i += 1
            if i >= len(argv) or not argv[i].lstrip("+").isdigit():
                print("ERROR: --expect needs a component count (an integer)", file=sys.stderr)
                return 2
            expect = int(argv[i])
        elif a.startswith("-"):
            print(f"ERROR: unknown option '{a}'", file=sys.stderr)
            return 2
        else:
            frags.append(Path(a))
        i += 1
    if not frags:
        print("ERROR: no fragment given", file=sys.stderr)
        return 2
    clean = True
    worst_budget = 0.0
    n_drift = 0
    unreadable = False
    # Buffered, so the VERDICT can be printed before the detail. It used to print last, after every
    # advisory row — and a harvest agent's own `head -40` cut it off twice: rounds that had already
    # returned 0 problems looked identical to failing ones, so the agent kept iterating on a
    # fragment that was finished. A verdict a pipe can remove is a verdict that does not exist.
    detail: list[tuple[str, bool]] = []   # (line, to_stderr)
    # COUNTED AS EMITTED, never re-derived from the text. Classifying the buffered lines by string
    # match (`": warning: " in line`) miscounts whenever a fragment's own free text contains the
    # marker — a messaging row named `jobs: warning: retries` produced "0 problem(s), 1 advisory
    # warning(s)" directly above "LINT FAILED: fix the rows above", telling the agent there was
    # nothing to fix. Any problem message quoting a name, statement or path is in that class.
    tally = {"problem": 0, "warning": 0}
    def say(line: str, err: bool = True, kind: str | None = None) -> None:
        detail.append((line, err))
        if kind:
            tally[kind] += 1
    for p in frags:
        # "cannot read it" and "it breaks a rule" are different answers, and they used to print the
        # same verdict: a wrong path produced `ERROR: … not found` followed by "LINT FAILED: fix the
        # rows above", sending the agent hunting for a rule violation in a file nobody opened. A
        # live build lost two turns to it, both times from running the command in another directory.
        if not p.exists():
            say(f"ERROR: cannot read {p} — no such file. (The fragment path and --repo are both "
                f"resolved from the CURRENT directory.)")
            unreadable = True
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            say(f"ERROR: cannot read {p}: {e}")
            unreadable = True
            continue
        try:
            m = load_fragment(text, p.name)
        except ModelError as e:
            # EVERY schema fault, not only the first: one line each, so the agent fixes them all in
            # one round. The first fault alone used to cost a lint round per fault.
            for fault in fragment_schema_errors(text, p.name) or [str(e)]:
                say(f"{p.name}: SCHEMA — {fault}", kind="problem")
            clean = False
            continue
        problems = lint_fragment_problems(m, repo_root, known_ids)
        if known_ids is not None:
            problems += lint_unknown_references(m, known_ids)
        if problems:
            clean = False
            for pr in problems:
                say(f"{p.name}: {pr}", kind="problem")
        else:
            say(f"{p.name}: OK", False)
        # advisory warnings never fail the lint — heuristic nudges the agent can act on or ignore
        drift: list[str] = []
        budget = _budget_warnings(m, expect)
        if budget and expect:
            worst_budget = max(worst_budget, len(m.components) / expect)
        if repo_root is not None:
            # THE OPERATIVE-LINE CHECK, which this command could not see until now.
            #
            # Every contract tells an agent to self-check with `lint-fragment` until clean, and
            # this was the one defect class it was structurally blind to: it imports
            # `check_anchor_existence_model` (does the FILE exist) and never
            # `check_operative_lines_model` (does the LINE act). Six hand-authored trace fragments
            # each printed `LINT OK — 0 problems`, and the next `validate --check-sources` raised
            # 86 anchor-drift warnings over 366 call-site anchors — 44 python function headers, 17
            # imports, 9 comments, one blank line. Repairing them took fifty turns at the lead.
            #
            # ADVISORY, deliberately, and for one build before anyone argues about blocking:
            # `validate_model` documents the check as "non-blocking on purpose" because a drifted
            # anchor does not refute the relationship, only its `where`. Promoting it here would
            # have failed six fragments on a build that shipped a clean map.
            # A STEP ARRIVING THROUGH A DOOR sits on its way in's own line, often a handler's
            # `def` (door-anchor-rule.md). The fragment rarely carries the ways in, so the doors
            # the sibling fragments or the map name are read from `--ids`, and an arrival through
            # a door nothing here names is left to `validate`.
            arrivals = {**sibling_arrivals, **door_arrival_sources(m)}
            drift = check_operative_lines_model(m, [repo_root.resolve()], arrivals,
                                                unknown_doors_pass=True)
        # A DOOR NOBODY STANDS AT is seen here, by the agent that drew it, and not only at the lead's
        # `validate`: the lead is who silenced the smoke test's doors on the build that found them.
        # Our surfaces come from the fragment or from `--ids`, the map a trace brief names.
        doors = nobody_at_door_warnings(
            m, {i.id for i in m.interfaces if i.side == "ours"} | sibling_doors)
        for w in lint_fragment_warnings(m) + doors + budget + drift:
            say(f"{p.name}: warning: {w}", kind="warning")
        n_drift += len(drift)
    n_prob, n_warn = tally["problem"], tally["warning"]
    # The drift count rides in the VERDICT, not only in the rows. The rows are the middle of the
    # output and a `head -5` cuts them; the verdict is the line every reader keeps.
    drift_note = f" ({n_drift} anchor drift)" if n_drift else ""
    # The BUDGET overshoot rides in the verdict too, for the reason the drift count already does:
    # rows get cut by a `head`, the verdict is the line every reader keeps.
    #
    # REDUNDANCY, NOT A RESCUE — and the distinction matters, because the first draft of this comment
    # claimed the opposite and the transcripts refute it. On the measured build the warning fired for
    # FIVE slices (1.8x, 2.0x, 2.0x, 3.0x, 3.7x) and all five agents quoted it verbatim in their
    # report to the lead, one of them as "Balance exception to record: 22 components against a budget
    # of 6, deliberate". The lead then recorded a `granularity` line under `Balance exceptions`, which
    # is the documented escape for `validate`'s own component-count advisory. The map shipped at 118
    # components against a code-derived 56 as a DECISION, not through a signal anyone lost.
    #
    # So this line buys one thing only: a reader who takes the verdict and nothing else sees the
    # ratio. What it does NOT fix is the surface where that decision was actually made — the lead
    # writing one line of prose about its own work, with no second reader and no requirement to name
    # the per-slice overshoots it covers.
    budget_note = f" ({worst_budget:.1f}x the slice budget)" if worst_budget >= _BUDGET_HI else ""
    if unreadable:
        verdict, code = "LINT DID NOT RUN", 2
    elif not clean:
        verdict, code = (f"LINT FAILED — {n_prob} problem(s), "
                         f"{n_warn} advisory warning(s){drift_note}{budget_note}"), 1
    else:
        verdict, code = (f"LINT OK — 0 problems, "
                         f"{n_warn} advisory warning(s){drift_note}{budget_note}"), 0
    # FIRST line, always, and on STDERR whichever way the lint went. Two reasons, both learned:
    #
    #  * a truncating pipe must keep the verdict, so it leads and both streams are flushed before
    #    any detail — stderr is unbuffered and stdout is block-buffered when piped, so without the
    #    flush it loses the race to its own rows under `2>&1 | head`, which is how it is read;
    #  * putting it on stdout for a PASS created a collision: on failure stdout's first line is
    #    some other fragment's `name: OK` row, so `| head -1 | grep OK` matched either way. The
    #    verdict is a diagnostic; the per-fragment `OK` rows stay on stdout, unchanged.
    print(verdict, file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        for line, err in detail:
            print(line, file=sys.stderr if err else sys.stdout)
        sys.stdout.flush()
    except BrokenPipeError:
        # `| head -1` closes the pipe mid-write. The verdict — the only line that reader asked for —
        # is already out. A traceback here would turn the endorsed usage into a crash.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
    # A CUT LIST SAYS HOW TO SEE THE REST. The long-sentence advisory named 3 of 10 fields and `+7
    # more`, and nothing said how to print the other seven. Read off the printed rows: a fragment
    # whose own text holds `+3 more` can add this one note, and never changes a count.
    if not show_all and any(_CUT_LIST_TAIL.search(line) for line, _err in detail):
        print("note: a list above ends in `+N more`, cut to its first items. Re-run with --all to "
              "print every item.", file=sys.stderr)
    if unreadable:
        print("LINT DID NOT RUN on the file(s) above — they could not be read, so nothing was "
              "checked. This is not a rule violation; fix the path and re-run.", file=sys.stderr)
    elif not clean:
        print("LINT FAILED: fix the rows above before returning this fragment. "
              "(`warning:` lines are advisory heuristics — they do not fail the lint.)", file=sys.stderr)
    if finalize:
        code = _finalize(frags, code)
    return code


DRAFT_SUFFIX = ".draft.json"


def _finalize(frags: list[Path], code: int) -> int:
    """Rename each `<id>.draft.json` to `<id>.json`, but only on a clean lint and only all at once.

    All-or-nothing on purpose. A partial rename lands some of a fan-out's slices and leaves the rest
    as drafts `assemble` skips, which is a map missing a slice with every gate still green — the
    quietest failure this whole file exists to prevent."""
    not_drafts = [p for p in frags if not p.name.endswith(DRAFT_SUFFIX)]
    if not_drafts:
        print(f"FINALIZE REFUSED: not a draft: {', '.join(p.name for p in not_drafts)}. "
              f"--finalize renames <id>{DRAFT_SUFFIX} to <id>.json; a fragment already named "
              f".json has nothing to rename.", file=sys.stderr)
        return max(code, 2)
    if code != 0:
        print("FINALIZE SKIPPED: the lint did not pass, so nothing was renamed. Fix the rows "
              "above and re-run — the draft is still on disk.", file=sys.stderr)
        return code
    targets = [(p, p.with_name(p.name[: -len(DRAFT_SUFFIX)] + ".json")) for p in frags]
    clash = [t for _, t in targets if t.exists()]
    if clash:
        print(f"FINALIZE REFUSED: already exists: {', '.join(t.name for t in clash)}. "
              f"Renaming over it would drop another agent's fragment; nothing was renamed.",
              file=sys.stderr)
        return 2
    for src, dst in targets:
        try:
            src.rename(dst)
        except OSError as e:
            # A rename that fails mid-batch leaves the earlier ones landed. Say exactly which,
            # rather than reporting a clean number that is not true of the disk.
            print(f"FINALIZE FAILED on {src.name}: {e}. Renamed already: "
                  f"{', '.join(d.name for s, d in targets if d.exists() and s != src)}",
                  file=sys.stderr)
            return 2
    print(f"FINALIZED {len(targets)} fragment(s): "
          f"{', '.join(d.name for _, d in targets)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
