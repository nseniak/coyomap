#!/usr/bin/env python3
"""`coyomap fix` — the mechanical reconcile edits the method's Phase-3/4 reconcile needs, applied to
the stored model IN PLACE so they are never hand-scripted (a hand script that matched edges by
endpoints-only once swapped a paired `persists`/`reads` edge — the class this command exists to kill).

Each verb loads `project-map.json`, mutates the dataclass tree, and writes it back through the one
canonical serializer (validity guaranteed by the serializer, never by hand):

  fix apply-drift   — write the grounding skeptics' corrected `where` line into each drifted edge
                      (consumes the same verdicts `coyomap anchor-drift` reads). Matches on the FULL
                      `(src, verb, dst)` triple, so paired edges sharing endpoints never swap.
  fix drop-edge     — remove a refuted backbone edge and surface (or heal) the flow steps that rode it.
  fix dedup-relation — resolve the blocking "relation declared on both cards" / "declared twice"
                       (--drop tok | --drop-file <path> | --drop-all for same-card only)
                      domain-card duplicates by dropping ONE human-chosen occurrence (never silent —
                      a wrong drop deletes a real domain fact).
  fix security-row  — rewrite a REFUTED security surface's text (and/or anchor), selected exactly.
                      0 or >1 matches is a refusal, not a "first match": the hand script this
                      replaces matched a substring, hit two rows, and clobbered a CONFIRMED claim.
  fix dedup-security — LEGACY maps only (an `access` business rule is the storage for an auth
                       surface now; `assemble` merges duplicate RULES by content). Drops security
                       rows authored twice under the same surface (two fragments
                      harvesting one auth check). Rows merely SHARING an anchor are reported, never
                      dropped — that is legal, and treating it as duplication is how the clobber
                      above got mistaken for a de-duplication.

After any fix, re-run the invariant: validate --check-sources → audit → render. Stdlib-only.
"""
from __future__ import annotations

import json
import re
import sys
import collections
import tempfile
from dataclasses import dataclass
from pathlib import Path

from coyomap.line_texts import FILE_NAME as LINE_TEXTS_JSON
from coyomap import subverb_help
from coyomap.subverb_help import usage_error
from coyomap.assemble import load_fragment_paths, merge_fragments
from coyomap.anchor_drift import (apply_drift_exceptions, drift_findings, drift_records,
                                  load_verdicts)
from coyomap.audit_model import (EDGE_CLAIM as _EDGE_CLAIM, _move_note, apply_anchor_corrections,
                                 cross_file_refusals,
                                 l2_worklist_model, security_claim as _security_claim)
from coyomap.impact_git import load_map_extents
from coyomap.model import ID_ARRAYS, ProjectModel, access_rules
from coyomap.reconcile import drop_riding, repoint_riding, riding_steps

#: The listing's display text for an edge carrying no anchor. Never a value to RECORD.
_NO_CALL_SITE = "(no call site)"

#: The claim themes `apply-drift` has a writer for: an edge's `where` and a security row's `source`.
#: `security` covers BOTH the auth-surface rows and the `enforces`/`encrypts` edges — `_EDGE_CLAIM`
#: sorts those two apart, so this set alone does not choose the writer.
#:
#: `lifecycle` used to reach the not-applicable branch: drift-ELIGIBLE (the skeptic is sent to the
#: declaring enum, the same kind of line the anchor holds) with no writer, so every confirmed
#: lifecycle drift was re-authored by hand. `cadence` was in that same bucket before it — a live
#: build had five cadence drifts refused and hand-typed them back through a bespoke script — and the
#: pattern repeating twice is why the partition test below now allows NO hand-written exception list.
#: `persistence` and `messaging` never arrive at all: `anchor_drift._confirmed_drifts` filters them
#: out upstream as report-only, because their skeptic is sent to a DIFFERENT KIND of line than the
#: anchor holds, so a difference there is not evidence of drift. That is a claim about the CLAIM, not
#: a missing feature, and completing the partition by writing anchors for them would be wrong.
#:
#: A theme added to `audit_model._THEMES` and not classified here silently becomes "not applicable",
#: which would stop `apply-drift` writing a kind it should write. `tests/test_fix.py` pins the
#: partition against `_THEMES` for exactly that.
_WRITABLE_THEMES = frozenset({"security", "dep-usage", "ownership", "backbone", "cadence",
                             "rule", "lifecycle"})


#: Optional fields a GATE explicitly tells a build to add, so `fix rows` may create them.
#:
#: The general refusal is right: a key that is not on a row is usually a typo or a schema change,
#: and silently minting it turns a correction into an invention. But `audit` and `validate` both
#: end findings with "state its prerequisite" / "give it a `why`" — asking for a field the row does
#: not have — and then the verb that exists to apply a finding refused it. On the 2026-08-29 mcpolis
#: build that sent eleven Happy-Path `why` lines through a `python3` heredoc, and forced a second
#: hand-script to attach `component` to an entry point `validate` said was owned by nobody.
#:
#: Narrow on purpose, twice over. Every member is a field some gate's own message asks for by name,
#: AND a field this verb can REACH: `component`, `cadence` and `cadence_source` live solely on
#: `EntryPoint`, whose ids are minted at assemble and exist in no fragment — `fix row --id EP12`
#: refuses by construction — so listing them promised a fix the verb cannot perform. The
#: entry-point half of the original complaint is still open and needs a different verb.
#: (`component` on an `EntryPoint` now has that different verb: `reconcile`'s `component` directive,
#: which runs after assemble where the `EPn` ids exist. It stays out of this set.)
#:
#: `owners` and `not_an_interface` meet both halves of the bar. `validate` asks for each by name —
#: an owner-with-no-evidence names the area and asks for `owners`; a dependency the map treats as
#: internal asks for `not_an_interface: <why>` — and both sit on elements `fix row` can reach:
#: `owners` on a `Group` (`SDn`) or an `Entity` (`En`), `not_an_interface` on a `Dep` (`Dn`), all
#: authored ids that exist in a fragment. Leaving them out sent the 2026-09-01 argus build to two
#: raw heredocs over the assembled map, which is the exact failure this set exists to prevent.
_GATE_REQUESTED_FIELDS: frozenset[str] = frozenset({
    "why", "risk", "purpose", "meaning", "owners", "not_an_interface",
})

#: Writable themes whose claim is NOT edge-shaped, so `apply_anchor_corrections` can place it by
#: recomputing the claim rather than by parsing `<Id> <verb> <Id>`. Everything writable and not in
#: here is an edge-themed claim `_EDGE_CLAIM` failed to parse — a real, differently-worded problem.
#: This list and `_WRITABLE_THEMES` must move together: `rule` was added to the second and not the
#: first, and every rule-site correction was then reported as an unparseable EDGE claim and dropped
#: — verbatim the `cadence` failure that set is documented as having fixed.
_CLAIM_SHAPED_THEMES = frozenset({"security", "cadence", "rule", "lifecycle"})


def _load(map_path: Path) -> tuple[ProjectModel, frozenset[str] | None]:
    """Load the target, which may be an assembled map OR a build fragment. Returns the fragment's own
    key set (None for a full map) so `_write` can keep a fragment a fragment."""
    from coyomap.assemble import load_map_or_fragment
    return load_map_or_fragment(map_path)


def _write(map_path: Path, m: ProjectModel, present: frozenset[str] | None = None) -> None:
    from coyomap.assemble import dump_preserving
    map_path.write_text(dump_preserving(m, present), encoding="utf-8")
    if present is not None:
        # Deliberately NOT "this edit is durable". An anchor rewrite is — it changes a `where` string
        # in this file, and the next assemble carries it through. A DROP is not, and `drop-edge` on a
        # fragment is refused for that reason (see `_refuse_fragment_drop`): the riding flow step may
        # live in a SIBLING fragment, where `riding_steps` cannot see it, so the tool reports a clean
        # drop and the next assemble re-derives the edge from the surviving step — silently, and with
        # a different verb. Verified: `C1 persists E1` dropped in one fragment came back as
        # `C1 writes E1`. The `--reconcile drop_edges` path sees the whole merged model and warns.
        print(f"note: edited the fragment {map_path.name} in place, preserving its "
              f"{len(present)} top-level section(s). Re-run `lint-fragment` on it, then re-assemble.",
              file=sys.stderr)
        return
    # `fix` edited the ASSEMBLED map. During a build the source of truth is the fragments, and a later
    # `assemble` regenerates the map from them — silently discarding this edit. Both fresh builds hit
    # exactly this (ran `fix drop-edge`, re-assembled, then hand-scripted the same drop into a
    # fragment). Say so: run `fix` only as the FINAL step, after the last assemble.
    print("note: this edited the assembled map in place — if you `assemble` again it is rebuilt from "
          "fragments and THIS edit is lost. Run `fix` as the final step (after the last assemble), or "
          "make structural changes in a fragment + re-assemble.", file=sys.stderr)


def _refuse_fragment_drop(present: frozenset[str] | None, map_path: Path) -> bool:
    """True (and explains) when a DROP was aimed at a fragment, which cannot be done safely here.

    Dropping a `C→E` edge has to heal the flow steps that rode it, or the next `assemble` re-derives
    the edge from the surviving step. `riding_steps` can only see the model it was handed, so in a
    fragment holding edges but not flows it finds nothing, reports a clean drop, and the drop silently
    does not stick. `--reconcile drop_edges` runs against the whole merged model and reports (or heals)
    the riding steps — which is what `method.md` already prescribes for a build-time drop."""
    if present is None:
        return False
    print(f"ERROR: refusing to drop an edge inside the fragment {map_path.name}. A dropped C→E edge "
          f"must heal the flow steps that rode it, and those steps may live in a SIBLING fragment "
          f"this file cannot see — the drop would look clean and then be undone by the next assemble, "
          f"with the edge re-derived under a different verb. Put the drop in the reconcile file, which "
          f"sees the whole merged model:\n"
          f'  {{"drop_edges": [{{"src": "<Cn>", "verb": "<verb>", "dst": "<En>", "drop_steps": true}}]}}\n'
          f"  coyomap assemble <fragments…> --out .coyomap --reconcile .coyomap/reconcile.json\n"
          f"(method.md, 'Where each reconcile lives'.) Anchor fixes — `apply-drift` — ARE safe on a "
          f"fragment and are not refused.", file=sys.stderr)
    return True


def _need(argv: list[str], i: int, flag: str) -> str:
    if i >= len(argv):
        print(f"ERROR: {flag} needs a value", file=sys.stderr)
        raise SystemExit(2)
    return argv[i]


# ── fix apply-drift ────────────────────────────────────────────────────────────────────────────────

def apply_drift(argv: list[str]) -> int:
    map_path = None
    verdicts_paths: list[str] = []
    to_reconcile: str | None = None
    tolerance = 2
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--map", "--verdicts", "--tolerance", "--repo", "--to-reconcile"):
            i += 1
            val = _need(argv, i, a)
            if a == "--repo":
                # ACCEPTED AND IGNORED. This verb reads the map and the verdicts and needs no repo,
                # but its sibling `anchor-drift` REQUIRES `--repo` and the two are invoked
                # back-to-back on the same inputs. Rejecting it cost a live build a turn on
                # `ERROR: unknown argument '--repo'`, with nothing saying the flag was merely
                # surplus rather than wrong.
                pass
            elif a == "--map":
                map_path = val
            elif a == "--to-reconcile":
                to_reconcile = val
            elif a == "--verdicts":
                # REPEATABLE, and it must stay in lockstep with `anchor-drift`. This used to bind a
                # scalar, so fixing only `anchor-drift`'s arity would have been worse than fixing
                # neither: drift would be reported over the union while the corrections were written
                # from one file, with nothing saying the two disagreed. It also silently lost the
                # NOT-APPLICABLE skip report — with >1 file this printed a bare "rewrote nothing".
                verdicts_paths.append(val)
            else:
                tolerance = int(val)
        else:
            return usage_error(_USAGE, "apply-drift", f"unknown argument '{a}'")
        i += 1
    if not map_path or not verdicts_paths:
        print("ERROR: --map and --verdicts are required", file=sys.stderr)
        return 2
    m, _present = _load(Path(map_path))
    grounding, notes = load_verdicts(verdicts_paths)
    for n in notes:
        print(n)
    worklist = l2_worklist_model(m)
    # The SAME symbol table `anchor-drift` reads, from the pre-index committed beside the map. The
    # two verbs run back-to-back on the same inputs in `ship`, so a correction this one writes must
    # be exactly the one the report a step earlier said would be written.
    extents = load_map_extents(Path(map_path))
    # Honour `Drift exceptions` HERE too. Reporting them in `anchor-drift` while the writer stayed
    # blind was worse than having no escape at all: the row vanished from the report and the anchor
    # got overwritten anyway, so the operator lost the warning he was about to be clobbered by.
    kept, exc_notes = apply_drift_exceptions(
        m, drift_findings(worklist, grounding, tolerance, extents))
    for n in exc_notes:
        print(n, file=sys.stderr)
    keep_claims = {w.claim for w, _d in kept}
    records = [r for r in drift_records(worklist, grounding, tolerance, extents)
               if r["claim"] in keep_claims]
    # REPORTED, NEVER WRITTEN. A drift whose corrected line left the definition the stored anchor
    # sits in is a re-anchor the operator has to make; applying it moved a live map's Docker-install
    # link 174 lines onto an unrelated build command. Partitioned before EITHER write path, so a
    # refused correction reaches neither the map nor the reconcile file's `set_anchors`.
    refused_moves = [r for r in records if r.get("refusal")]
    records = [r for r in records if not r.get("refusal")]
    _report_refused_moves(refused_moves)
    not_applicable: list[tuple[str, str]] = []
    unparseable: list[tuple[str, str]] = []
    corrections: list[tuple[str, str]] = []
    for rec in records:
        claim = rec["claim"]
        theme = rec.get("theme") or "unknown"
        # Partition BEFORE writing. `apply_anchor_corrections` dispatches on the claim's shape, so
        # everything it cannot place comes back as "matches nothing" — true, and useless to a reader
        # holding a cadence claim. The theme says which kind the claim IS, so an unwritable kind and
        # a malformed edge claim get their own accurate message here.
        if _EDGE_CLAIM.match(claim):
            corrections.append((claim, rec.get("corrected") or ""))
            continue
        if theme not in _WRITABLE_THEMES:
            not_applicable.append((theme, claim))
            continue
        if theme not in _CLAIM_SHAPED_THEMES:
            # An EDGE-themed claim that `_EDGE_CLAIM` could not parse. Letting it reach the security
            # writer reproduces the bug this dispatch exists to kill: `validate` accepts a multi-word
            # verb (`C1 writes to E1`), the regex's `(\S+)` cannot match it, and the operator was
            # told the claim "matches 0 security surfaces". It is not a security claim and there is
            # nothing to look for — say that instead.
            unparseable.append((theme, claim))
            continue
        corrections.append((claim, rec.get("corrected") or ""))
    _report_stuck(unparseable, not_applicable)
    # Before EITHER write path: a correction refused here reaches neither the map nor the
    # reconcile file's `set_anchors`, which `assemble` would otherwise replay on every rebuild.
    corrections, refused = cross_file_refusals(m, corrections)
    for n in refused:
        print(n, file=sys.stderr)
    if to_reconcile:
        # DURABLE. Writing anchors into the ASSEMBLED map is exactly what the note below warns
        # about, and a live build walked into it: 14 anchors corrected here, the map re-assembled to
        # pick up a fragment edit, and all 14 silently reverted — then re-typed by hand, from the
        # human-readable listing, into two bespoke python scripts. `set_anchors` is read by
        # `assemble --reconcile`, so the correction survives every rebuild.
        return _anchors_to_reconcile(Path(to_reconcile), corrections,
                                     {r["claim"]: r["stored"] for r in records},
                                     _unwritten_tail(not_applicable, unparseable, refused_moves,
                                                     refused))
    counts, notes = apply_anchor_corrections(m, corrections)
    for n in notes:
        # An applied rewrite is indented and is the RESULT (stdout); a skip is a warning (stderr).
        print(n, file=sys.stdout if n.startswith("  ") else sys.stderr)
    #: What each `apply_anchor_corrections` count is CALLED on the result line. Derived from the
    #: counts dict rather than hand-listed, for the same reason `sum(counts.values())` replaced a
    #: hand-listed disjunction below: the hand-listed version silently stopped covering a kind the
    #: moment a new writer existed, and the whole point of adding a writer is that its work shows up.
    kind_words = {"edge": "edge `where`", "security": "security anchor(s)",
                  "cadence": "cadence anchor(s)", "rule_site": "rule site(s)",
                  "lifecycle": "lifecycle anchor(s)"}
    applied = ", ".join(f"{counts[k]} {kind_words.get(k, k)}" for k in counts)
    tail = _unwritten_tail(not_applicable, unparseable, refused_moves, refused)
    # `sum(counts.values())`, not a hand-listed disjunction — `reconcile.py` already does it that
    # way, and the hand-listed one silently stopped writing the file the moment a fourth writer
    # existed: the correction applied in memory, printed, and was never persisted.
    if sum(counts.values()):
        _write(Path(map_path), m, _present)
        print(f"apply-drift: rewrote {applied}.{tail} "
              f"Re-run: validate --check-sources → audit → render.")
    else:
        print(f"apply-drift: rewrote nothing — no drifted "
              f"{', '.join(kind_words.get(k, k) for k in counts)} to fix.{tail}")
    return 0


def _unwritten_tail(not_applicable: list[tuple[str, str]], unparseable: list[tuple[str, str]],
                    refused_moves: list[dict], cross_file: list[str]) -> str:
    """The "and here is what did NOT get written" clause, for the LAST line of either write path.

    A live build read this command's output with `| tail -12`, so a count that is not on the final
    line is a count the reader never sees. ALL THREE refusal counts live here because there are two
    write paths and they keep drifting apart: the cross-file clause was appended by the in-place
    path alone, so `--to-reconcile` — the path `ship` step 3 actually runs — ended its last line
    without it. Fixing one clause and leaving the next one duplicated is how the first copy got
    made; every count this command refuses now has exactly one home."""
    stuck = len(not_applicable) + len(unparseable)
    tail = (f" {stuck} drift(s) NOT APPLICABLE to this command (named above) and still "
            f"unreconciled." if stuck else "")
    if refused_moves:
        tail += (f" {len(refused_moves)} correction(s) REFUSED as a re-anchor, not a nudge (named "
                 f"above): the corrected line leaves the definition the stored anchor sits in. The "
                 f"map still holds the OLD anchor — open both lines and decide by hand.")
    if cross_file:
        tail += (f" {len(cross_file)} cross-file correction(s) REFUSED (named above): the corrected "
                 f"file belongs to neither end of its edge.")
    return tail


def _report_refused_moves(refused_moves: list[dict]) -> None:
    """Name every correction refused as a relocation, with BOTH anchors and the reason.

    Loud on purpose. The 2026-09-13 reminderrepo build applied a 174-line move inside an unattended
    `ship`, and the only trace was one line of a drift listing that read exactly like the four small
    nudges beside it. A reader has to be able to see, from this output alone, that the tool declined
    to decide something — so the block names the claim, the stored anchor, the corrected anchor and
    why, and `_unwritten_tail` repeats the COUNT on the command's final line."""
    if not refused_moves:
        return
    print(f"WARNING: {len(refused_moves)} confirmed drift(s) were REFUSED, not written: the "
          f"skeptics' line is outside the definition the stored anchor sits in, which is a "
          f"re-anchor decision this command must not make for you. Read both lines, then fix the "
          f"anchor by hand — or record ``anchor-drift `<the claim, verbatim>`: <why>`` under a "
          f"'Drift exceptions' extras heading if the stored anchor is right:", file=sys.stderr)
    for r in refused_moves:
        print(f"    {r['claim']}\n"
              f"        stored    {r['stored']}\n"
              f"        corrected {r.get('corrected') or _NO_CALL_SITE}\n"
              f"        REFUSED:  {r['refusal']}", file=sys.stderr)


def _report_stuck(unparseable: list[tuple[str, str]],
                  not_applicable: list[tuple[str, str]]) -> None:
    """Name every drift this command cannot write, BEFORE either write path returns.

    It used to run only on the in-place path, so `--to-reconcile` ended with
    "N drift(s) NOT APPLICABLE to this command (see above)" and nothing above — the claims needing
    a hand re-anchor were counted and never named."""
    if unparseable:
        print(f"WARNING: {len(unparseable)} confirmed drift(s) are edge claims this command could "
              f"not parse back to an edge — an edge claim must read `<Id> <verb> <Id>`, and a "
              f"multi-word verb does not. Fix the edge's `where` by hand, or give the verb a single "
              f"word:", file=sys.stderr)
        for kind, claim in unparseable:
            print(f"    [{kind}] {claim}", file=sys.stderr)
    if not_applicable:
        by_kind: dict[str, int] = {}
        for kind, _claim in not_applicable:
            by_kind[kind] = by_kind.get(kind, 0) + 1
        print(f"note: {len(not_applicable)} confirmed drift(s) are of a kind this command cannot "
              f"rewrite ({', '.join(f'{k}: {n}' for k, n in sorted(by_kind.items()))}) — "
              f"`apply-drift` writes an edge `where`, a `security[].source` and an entry point's "
              f"`cadence_source`. Re-anchor each by hand, or record why it stands; they do NOT go "
              f"away by re-running this:", file=sys.stderr)
        for kind, claim in not_applicable:
            print(f"    [{kind}] {claim}", file=sys.stderr)


def _anchors_to_reconcile(rec_path: Path, corrections: list[tuple[str, str]],
                          stored_by_claim: dict[str, str], stuck_tail: str) -> int:
    """Record the corrected anchors as `set_anchors` in the reconcile file instead of editing the map.

    Keyed by CLAIM, which is what a verdict carries and what `apply_anchor_corrections` matches on,
    so the durable record and the in-place edit cannot drift apart. Re-recording the same claim with
    a different anchor UPDATES it and says so — silently discarding a changed mind is how a durable
    record ends up asserting what the artifact does not do.

    `stored_by_claim` feeds `_move_note`, which is why this path takes it at all. The far-move
    warning has existed since the 2026-09-02 mcpolis build and fires inside
    `apply_anchor_corrections` — the IN-PLACE writer. `ship` step 3 runs `--to-reconcile`, so on
    every real build the warning was dead code: the 2026-09-13 reminderrepo run recorded a 174-line
    move with no note of any kind. One warning, both write paths.

    `stuck_tail` is `_unwritten_tail`'s clause, built by the caller so BOTH write paths end on the
    same sentence — this one used to build its own copy, which is how the copies drift."""
    try:
        doc = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.exists() else {}
    except ValueError as e:
        print(f"ERROR: {rec_path} is not valid JSON ({e})", file=sys.stderr)
        return 2
    existing = doc.get("set_anchors") or []
    by_claim = {a.get("claim"): a for a in existing if isinstance(a, dict)}
    added = updated = 0
    for claim, corrected in corrections:
        if not corrected:
            print(f"  SKIPPED (no corrected line): {claim}", file=sys.stderr)
            continue
        note = _move_note(claim, stored_by_claim.get(claim), corrected)
        prior = by_claim.get(claim)
        if prior is None:
            new = {"claim": claim, "corrected": corrected}
            existing.append(new)
            by_claim[claim] = new
            added += 1
            print(f"  recorded {claim} → {corrected}")
        elif prior.get("corrected") != corrected:
            print(f"  UPDATED {claim}: {prior.get('corrected')} -> {corrected}")
            prior["corrected"] = corrected
            updated += 1
        else:
            continue                         # already recorded at this line: nothing new to say
        if note:
            print(note)
    if not added and not updated and "set_anchors" not in doc:
        # Nothing to record and no prior key: writing would re-serialise (and reformat) a committed
        # artifact to say nothing. The stuck count still rides the last line — it is the half of the
        # result that is not "nothing happened".
        print(f"apply-drift: no anchor correction to record — the reconcile file was not "
              f"touched.{stuck_tail}")
        return 0
    doc["set_anchors"] = existing
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    # indent=2 + ensure_ascii=False, matching `dedup-edge --to-reconcile`; two writers of one file
    # that disagree on formatting churn it on every alternating run (a claim holding an em dash
    # came out `\u2014`-escaped by one and literal by the other).
    rec_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"apply-drift: recorded {added} new and {updated} updated anchor correction(s) in "
          f"{rec_path} — the MAP was not edited. Re-run `assemble … --reconcile {rec_path}` to "
          f"apply them, then validate --check-sources → audit → render.{stuck_tail}")
    return 0


# ── fix drop-edge ────────────────────────────────────────────────────────────────────────────────
# The riding-step query + heal (repoint / drop) is shared with `assemble --reconcile drop_edges`
# (coyomap.reconcile) so the two drop paths reconcile flow steps identically.


def _drop_edge_to_reconcile(map_path: Path, rec_path: Path, src: str, verb: str, dst: str,
                            repoint: str | None, drop_steps: bool) -> int:
    """Record the drop as a `drop_edges` directive instead of editing the assembled map.

    The edge is verified against the map first — a directive naming an edge that is not there is the
    `reconcile --dry-run` failure one level down, and `drop_edges` only WARNS on a 0-match at
    assemble time so it would rot silently."""
    m, _present = _load(map_path)
    if not any(e.src == src and e.verb.strip().lower() == verb and e.dst == dst for e in m.edges):
        print(f"ERROR: no edge '{src} {verb} {dst}' found", file=sys.stderr)
        return 1
    doc: dict[str, object] = {}
    if rec_path.exists():
        try:
            loaded = json.loads(rec_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"ERROR: cannot read {rec_path}: {e}", file=sys.stderr)
            return 2
        if not isinstance(loaded, dict):
            print(f"ERROR: {rec_path} is not a reconcile object", file=sys.stderr)
            return 2
        doc = loaded
    raw = doc.get("drop_edges")
    drops: list[dict[str, object]] = list(raw) if isinstance(raw, list) else []
    entry: dict[str, object] = {"src": src, "verb": verb, "dst": dst}
    if repoint:
        entry["repoint"] = repoint
    if drop_steps:
        entry["drop_steps"] = True
    already = [d for d in drops if isinstance(d, dict)
               and (d.get("src"), str(d.get("verb", "")).lower(), d.get("dst")) == (src, verb, dst)]
    if already:
        for d in already:
            d.update(entry)
        verb_word = "updated"
    else:
        drops.append(entry)
        verb_word = "recorded"
    doc["drop_edges"] = drops
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    # indent=2 + ensure_ascii=False, matching the other two writers of this file.
    rec_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    riding = riding_steps(m, src, dst)
    print(f"drop-edge: {verb_word} the drop of '{src} {verb} {dst}' in {rec_path} — the MAP was not "
          f"edited. Re-run `assemble … --reconcile {rec_path}` to apply it.")
    if riding and not (repoint or drop_steps):
        print(f"  {len(riding)} flow step(s) ride this edge; assemble will report them. Add "
              f"--repoint <newDst> or --drop-steps to heal them in the same directive.")
    return 0


def drop_edge(argv: list[str]) -> int:
    map_path = new_dst = to_reconcile = None
    drop_steps = False
    positionals: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--map":
            i += 1
            map_path = _need(argv, i, a)
        elif a == "--repoint":
            i += 1
            new_dst = _need(argv, i, a)
        elif a == "--to-reconcile":
            i += 1
            to_reconcile = _need(argv, i, a)
        elif a == "--drop-steps":
            drop_steps = True
        elif a.startswith("-"):
            return usage_error(_USAGE, "drop-edge", f"unknown option '{a}'")
        else:
            positionals.append(a)
        i += 1
    if not map_path or len(positionals) != 3:
        print("ERROR: usage: fix drop-edge --map <map> <src> <verb> <dst> "
              "[--drop-steps | --repoint <newDst>] [--to-reconcile <file>]", file=sys.stderr)
        return 2
    if drop_steps and new_dst:
        print("ERROR: --drop-steps and --repoint are mutually exclusive", file=sys.stderr)
        return 2
    src, verb, dst = positionals[0], positionals[1].lower(), positionals[2]
    if to_reconcile:
        # DURABLE form. Without it a refuted edge had to be re-dropped by hand after every assemble
        # — the drop is re-derived from the fragments each time — and one real build hand-wrote the
        # same drop three times plus two hand-rolled riding-step scans. `drop_edges` is already a
        # first-class reconcile directive; this is the writer it never had.
        return _drop_edge_to_reconcile(Path(map_path), Path(to_reconcile),
                                       src, verb, dst, new_dst, drop_steps)
    m, _present = _load(Path(map_path))
    if _refuse_fragment_drop(_present, Path(map_path)):
        return 2
    kept = [e for e in m.edges if not (e.src == src and e.verb.strip().lower() == verb and e.dst == dst)]
    removed = len(m.edges) - len(kept)
    if removed == 0:
        print(f"ERROR: no edge '{src} {verb} {dst}' found", file=sys.stderr)
        return 1
    m.edges = kept
    riding = riding_steps(m, src, dst)
    if new_dst:
        repoint_riding(riding, dst, new_dst)
        print(f"drop-edge: removed {removed} edge(s); re-pointed {len(riding)} riding step(s) "
              f"{dst} → {new_dst}.")
    elif drop_steps:
        drop_riding(m, riding)
        print(f"drop-edge: removed {removed} edge(s) and {len(riding)} riding step(s).")
    else:
        print(f"drop-edge: removed {removed} edge(s).")
        if riding:
            print(f"  {len(riding)} flow step(s) rode this edge and now attribute {src}↔{dst} with no "
                  f"backing edge (validate warns on C↔E; C↔C is silent) — reconcile them:")
            for owner, st in riding:
                print(f"    {owner} step {st.n}: {st.src} → {st.dst}  ({st.phrase or '—'})")
            print("  Re-run with --repoint <newDst> or --drop-steps, or edit the steps by hand.")
    _write(Path(map_path), m, _present)
    print("Re-run: validate --check-sources → audit → render.")
    return 0


# ── fix dedup-relation ───────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DuplicateRelations:
    """The blocking domain-card duplicates, split by SHAPE, as drop-token lists.

    Named for the same reason as `assemble.FragmentLoad`, found by the same sweep: two same-typed
    lists returned positionally, both EMPTY on a healthy map — so a swap is invisible to every test
    that builds a clean fixture, and identical under a type checker. Verified rather than assumed:
    swapping this function's two returns passed all 1916 tests. The two shapes need different
    operator action (drop one of two on ONE card, versus keep one SIDE of a reciprocal pair), so a
    silent swap mislabels the listing the operator acts on."""

    #: `En:verb:Em` for a relation declared TWICE on one card — drop one occurrence.
    same_card: list[str]
    #: `En:verb:Em` for a pair authored from BOTH cards — keep one side, drop the other.
    reciprocal: list[str]


def _duplicate_relations(m: ProjectModel) -> DuplicateRelations:
    """The blocking domain-card duplicates the validator flags. A token is `En:verb:Em` — the
    relation to drop ONE occurrence of. Mirrors `validate_model._check_domain_cards` /
    `check_domain_relations`."""
    same_card: list[str] = []
    directed: dict[tuple[str, str], list[tuple[str, str]]] = {}   # (a,b) → [(verb, token)]
    for e in m.entities:
        seen: set[tuple[str, str]] = set()
        for r in e.relations:
            key = (r.verb, r.target)
            if key in seen:
                same_card.append(f"{e.id}:{r.verb}:{r.target}")
            seen.add(key)
            directed.setdefault((e.id, r.target), []).append((r.verb, f"{e.id}:{r.verb}:{r.target}"))
    reciprocal: list[str] = []
    for (a, b), items in directed.items():
        if a < b and (b, a) in directed:
            # both sides authored the pair — offer to drop EITHER side (list the a→b side's token(s))
            reciprocal.extend(tok for _verb, tok in items)
    return DuplicateRelations(same_card=same_card, reciprocal=reciprocal)


def dedup_relation(argv: list[str]) -> int:
    map_path = to_reconcile = None
    drops: list[str] = []
    drop_all = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--map":
            i += 1
            map_path = _need(argv, i, a)
        elif a == "--drop":
            i += 1
            drops.append(_need(argv, i, a))
        elif a == "--drop-file":
            # The listing's own tokens, one per line, straight back in. Passing 33 of them as
            # separate flags cost five turns of shell word-splitting on a live build — an unquoted
            # variable, then `xargs -a` (which macOS does not have), then a string-built argument
            # list — before a bash array worked. A tool that prints N tokens and demands N flags
            # back is asking the caller to solve a quoting problem to use it.
            i += 1
            fp = Path(_need(argv, i, a))
            if not fp.exists():
                print(f"ERROR: --drop-file {fp} not found", file=sys.stderr)
                return 2
            # The listing VERBATIM — headings, blank lines, trailer and all. The point of the
            # flag is that you save what the tool printed and hand it back; erroring on the
            # heading it printed one line earlier puts the caller straight back into grep/sed,
            # which is the shell fiddling this exists to remove. A token is `En:verb:Em`;
            # anything that is not one is not a token.
            for ln in fp.read_text(encoding="utf-8").splitlines():
                tok = ln.strip().removeprefix("--drop").strip().rstrip("\r")
                if re.fullmatch(r"E\d+:[^:\s]+:E\d+", tok):
                    drops.append(tok)
        elif a == "--drop-all":
            drop_all = True
        elif a == "--to-reconcile":
            i += 1
            to_reconcile = _need(argv, i, a)
        else:
            return usage_error(_USAGE, "dedup-relation", f"unknown argument '{a}'")
        i += 1
    if not map_path:
        print("ERROR: --map is required", file=sys.stderr)
        return 2
    if to_reconcile and not drops and not drop_all:
        # Above the listing branch, not below it: placed after, the listing returned 0 first and the
        # refusal never ran. `dedup-edge` shipped this exact ordering bug — the flag printed a full
        # listing, wrote nothing, and exited 0, which reads as success.
        #
        # `--drop-all` IS a decision, so it satisfies this guard. Without that clause the one
        # combination that makes a 33-token sweep survive the next assemble was impossible, while
        # the success message told the caller to use `--to-reconcile`.
        print("ERROR: --to-reconcile needs a decision — pass the --drop token(s) to record, or "
              "--drop-all for the mechanical same-card ones. On its own it would print the "
              "listing, write nothing, and exit 0, which reads as success.", file=sys.stderr)
        return 2
    m, _present = _load(Path(map_path))
    if drop_all:
        # RECIPROCAL only. A same-card duplicate is one card saying the same thing twice, so
        # dropping either occurrence is the same edit — mechanical. A reciprocal pair is TWO cards
        # each claiming the relation, and which side survives is a modelling judgement the tool's
        # own header calls out ("a wrong drop deletes a real domain fact"). Sweeping those would
        # make the judgement silently, which is worse than the quoting problem this flag solves.
        dupes = _duplicate_relations(m)
        # Only the reciprocals the caller has NOT already decided. The refusal used to fire on any
        # reciprocal at all — including when the explicit --drop tokens it asks for were sitting
        # right there in the same command line, which made its own instructions impossible to
        # follow. A pair is decided when either of its two directions is among the drops.
        def _pair(tok: str) -> frozenset[str]:
            parts = tok.split(":")
            return frozenset(parts[::2]) if len(parts) == 3 else frozenset({tok})
        decided = {_pair(t) for t in drops}
        undecided = [t for t in dupes.reciprocal if _pair(t) not in decided]
        if undecided:
            print(f"ERROR: --drop-all covers same-card duplicates only; "
                  f"{len(set(_pair(t) for t in undecided))} reciprocal pair(s) still need a "
                  f"per-pair decision about which side survives. Pass those as --drop tokens "
                  f"(or --drop-file) in this same command; --drop-all takes the rest.",
                  file=sys.stderr)
            return 2
        # UNION, never assignment: the refusal above tells the caller to resolve reciprocals with
        # explicit --drop tokens and then re-run with --drop-all, so overwriting silently threw
        # away the very tokens the message asked for — and exited 0 having ignored them.
        drops = sorted(set(drops) | set(dupes.same_card))
        if not drops:
            print("dedup-relation: no same-card duplicates to drop.")
            return 0
    if not drops:
        dupes = _duplicate_relations(m)
        same_card, reciprocal = dupes.same_card, dupes.reciprocal
        if not same_card and not reciprocal:
            print("dedup-relation: no blocking duplicate relations.")
            return 0
        if same_card:
            print("Same-card duplicates (relation declared twice on one card) — drop one occurrence:")
            for tok in same_card:
                print(f"  --drop {tok}")
        if reciprocal:
            print("Reciprocal (declared on BOTH cards) — keep one side, drop the other:")
            for tok in reciprocal:
                print(f"  --drop {tok}")
        print("\nRe-run with the chosen --drop token(s). Each drops ONE occurrence.")
        if same_card:
            print("  Same-card duplicates are mechanical: `--drop-all` takes them all in one go.")
        print("  Or save these lines to a file and pass `--drop-file <path>` — no shell quoting.")
        return 0
    dropped = 0
    resolved: list[tuple[str, str, str]] = []
    for tok in drops:
        parts = tok.split(":")
        if len(parts) != 3:
            print(f"ERROR: bad --drop token '{tok}' (want En:verb:Em)", file=sys.stderr)
            return 2
        eid, verb, target = parts
        ent = next((e for e in m.entities if e.id == eid), None)
        if ent is None:
            print(f"ERROR: no entity '{eid}'", file=sys.stderr)
            return 1
        idx = next((k for k, r in enumerate(ent.relations)
                    if r.verb.lower() == verb.lower() and r.target == target), None)
        if idx is None:
            print(f"ERROR: no relation '{verb} → {target}' on {eid}", file=sys.stderr)
            return 1
        resolved.append((eid, verb, target))
        if to_reconcile:
            continue
        del ent.relations[idx]                       # ONE occurrence
        dropped += 1
        print(f"  dropped {eid}: {verb} → {target}")
    if to_reconcile:
        return _relations_to_reconcile(Path(to_reconcile), resolved, m)
    _write(Path(map_path), m, _present)
    print(f"dedup-relation: dropped {dropped} relation(s). NOTE: this edited the assembled map in "
          f"place — the next `assemble` rebuilds it from fragments and restores the duplicate, which "
          f"BLOCKS. Use --to-reconcile to record the decision so it survives. "
          f"Re-run: validate --check-sources → audit → render.")
    return 0


def _relations_to_reconcile(rec_path: Path, resolved: list[tuple[str, str, str]],
                            m: ProjectModel) -> int:
    """Record the chosen drops as `drop_relations` instead of editing the assembled map.

    A duplicate relation is BLOCKING, and this verb was the only writer with no way to record its
    answer — so the resolution was discarded by the next assemble and the build re-blocked on the
    duplicate it had just resolved. Merges into an existing file, and updates rather than duplicating
    a directive already present for the same (entity, verb, target)."""
    doc: dict[str, object] = {}
    if rec_path.exists():
        try:
            loaded = json.loads(rec_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"ERROR: cannot read {rec_path}: {e}", file=sys.stderr)
            return 2
        if not isinstance(loaded, dict):
            print(f"ERROR: {rec_path} is not a reconcile object", file=sys.stderr)
            return 2
        doc = loaded
    existing = doc.get("drop_relations")
    rows: list[dict[str, str]] = list(existing) if isinstance(existing, list) else []
    # COUNTED, not set-membership. Presence-based dedup silently refused the SECOND drop a relation
    # legitimately needs — a token the listing prints three times — while still printing "recorded"
    # and exiting 0. The operator who follows the listing one token at a time then ships a map that
    # still blocks, with nothing saying so: the same "writes nothing, reads as success" shape the
    # `--to-reconcile needs a decision` refusal above exists to kill.
    recorded = collections.Counter((r.get("entity"), (r.get("verb") or "").lower(), r.get("target"))
                                   for r in rows if isinstance(r, dict))
    added, refused = 0, []
    for eid, verb, target in resolved:
        key = (eid, verb.lower(), target)
        ent = next((e for e in m.entities if e.id == eid), None)
        # The ceiling is how many occurrences the map actually declares — you cannot drop more than
        # exist, and beyond that a repeat is a mistake worth naming rather than a no-op.
        occurrences = sum(1 for r in (ent.relations if ent else [])
                          if r.verb.lower() == verb.lower() and r.target == target)
        if recorded[key] >= occurrences:
            refused.append((eid, verb, target, occurrences, recorded[key]))
            continue
        rows.append({"entity": eid, "verb": verb, "target": target})
        recorded[key] += 1
        added += 1
        print(f"  recorded {eid}: {verb} → {target}")
    for eid, verb, target, occurrences, already in refused:
        print(f"ERROR: {eid}: {verb} → {target} is declared {occurrences} time(s) and {rec_path.name} "
              f"already records {already} drop(s) — refusing to record another.", file=sys.stderr)
    if not added:
        print(f"dedup-relation: recorded NOTHING in {rec_path} — every drop asked for was already "
              f"recorded. The file is unchanged.", file=sys.stderr)
        return 2
    doc["drop_relations"] = rows
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    rec_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"dedup-relation: recorded {added} new drop_relations directive(s) in {rec_path} — the MAP "
          f"was not edited. `assemble --reconcile` re-applies them on every rebuild.")
    return 2 if refused else 0


# ── fix dedup-edge ──────────────────────────────────────────────────────────────────────────────

def _conflicting_edges(m: ProjectModel) -> dict[tuple[str, str, str], list[int]]:
    """(src, verb, dst) triples authored more than once, with the indexes of every occurrence.

    `assemble` already collapses duplicates that share a call site; what is left here declares the
    SAME relationship at DIFFERENT lines, which is a real conflict — one of the anchors is wrong,
    and a duplicate has masked a wrong anchor before."""
    triples: dict[tuple[str, str, str], list[int]] = {}
    for i, e in enumerate(m.edges):
        triples.setdefault((e.src, e.verb, e.dst), []).append(i)
    return {k: v for k, v in triples.items() if len(v) > 1}


def _own_code_rank(anchor: str, repo: Path | None) -> tuple[int, int, str]:
    """Sort key preferring the anchor most likely to be the true call site.

    The heuristic a live build hand-wrote as a 40-line script: prefer a path that exists in the
    repo, then one under a source root over a test or a script, then the shortest path. Reported,
    never applied silently — `--keep` is how a choice becomes an edit."""
    path = anchor.split(":")[0] if anchor else ""
    exists = 0 if (repo and path and (repo / path).exists()) else 1
    is_side = 1 if re.search(r"(^|/)(tests?|scripts?|docs?|examples?)/", path) else 0
    return (exists, is_side, str(len(path)).zfill(4) + path)


def dedup_edge(argv: list[str]) -> int:
    """List, or resolve, the duplicate (src, verb, dst) edges `validate` warns about.

    This existed only as a warning with no tool behind it: `coyomap fix` claims these mechanical
    reconcile edits are "never hand-scripted", but there was no verb for the commonest one. A live
    build hand-wrote a 40-line script to resolve 24 conflicting triples and dropped 29 rows."""
    map_path = None
    repo: Path | None = None
    keeps: list[str] = []
    to_reconcile: str | None = None
    as_json = False
    accept_suggested = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--json":
            as_json = True
        elif a == "--accept-suggested":
            accept_suggested = True
        elif a in ("--map", "--repo", "--keep", "--to-reconcile"):
            i += 1
            val = _need(argv, i, a)
            if a == "--map":
                map_path = val
            elif a == "--repo":
                repo = Path(val)
            elif a == "--to-reconcile":
                to_reconcile = val
            else:
                keeps.append(val)
        else:
            return usage_error(_USAGE, "dedup-edge", f"unknown argument '{a}'")
        i += 1
    if not map_path:
        print("ERROR: --map is required", file=sys.stderr)
        return 2
    # These three express DIFFERENT intents and silently overrode each other. `--json
    # --accept-suggested` printed the listing, wrote nothing and exited 0 — a script asking to apply
    # and report got a no-op that looked like success. `--keep X --accept-suggested` threw away the
    # operator's explicit choice in favour of the blanket one, which is the wrong direction for a
    # flag whose whole point is that a wrong drop is unrecoverable. Refuse instead of guessing.
    if accept_suggested and as_json:
        print("ERROR: --json lists without writing; --accept-suggested writes. Pick one: run "
              "--json to review, then --accept-suggested to apply.", file=sys.stderr)
        return 2
    if accept_suggested and keeps:
        print("ERROR: --accept-suggested takes the suggestion for EVERY conflict, which would "
              "override the --keep token(s) you named. Pass one or the other.", file=sys.stderr)
        return 2
    # `--to-reconcile` names an OUTPUT, so a run that reaches neither write path silently produced
    # nothing while exiting 0. Both no-write paths below return early — the listing (no `--keep`,
    # no `--accept-suggested`) at "pick the true site for each", and `--json` — and each ignored the
    # flag on the way out. A live build ran `dedup-edge --map … --repo … --to-reconcile <file>`,
    # got exit 0 and a full listing, and the file was untouched; it only noticed because it read the
    # file back afterwards. A build that trusted the exit code would ship a map whose fragments
    # re-assemble to a different edge count — the exact failure `--to-reconcile` exists to prevent.
    # Refuse rather than guess: implying `--accept-suggested` would apply a blanket choice nobody
    # asked for, and a wrong drop is unrecoverable.
    if to_reconcile and as_json:
        print("ERROR: --json lists without writing; --to-reconcile writes. Pick one: run --json to "
              "review, then re-run with --to-reconcile plus --keep or --accept-suggested.",
              file=sys.stderr)
        return 2
    m, present = _load(Path(map_path))
    conflicts = _conflicting_edges(m)
    if not conflicts:
        if as_json:
            print(json.dumps({"conflicts": []}, indent=1))
        else:
            print("dedup-edge: no (src, verb, dst) edge is declared more than once.")
        return 0
    # AFTER the no-conflicts return, deliberately. Placed above it, this refusal failed the healthy
    # end state: a map with nothing to de-duplicate exited 2, so a pipeline that runs the dedup step
    # unconditionally — which is what a durable-decision step should do — broke precisely when the
    # map was correct, and the message pushed the operator toward `--accept-suggested` on a map with
    # nothing to accept.
    if to_reconcile and not keeps and not accept_suggested:
        print(f"ERROR: --to-reconcile needs a decision to record, and none was given — nothing was "
              f"written, and {len(conflicts)} conflict(s) are still unresolved. Re-run with "
              f"--accept-suggested to take every suggestion, or with the --keep token(s) for the "
              f"conflicts you chose. Run without --to-reconcile to see the listing first.",
              file=sys.stderr)
        return 2
    # The suggestion ranking's first term is "exists under --repo"; with no --repo it is constant for
    # every candidate and the sort silently degrades to shortest-path. A live build passed --repo to
    # the listing it discarded and omitted it from the listing it applied, with nothing saying so.
    ranked = {(s, v, d): (
        [(m.edges[i].where or "(no call site)") for i in idxs],
        min([(m.edges[i].where or "(no call site)") for i in idxs],
            key=lambda a: _own_code_rank(a, repo)))
        for (s, v, d), idxs in sorted(conflicts.items())}
    if as_json:
        print(json.dumps({
            "repo_ranked": repo is not None,
            "conflicts": [{"src": s, "verb": v, "dst": d, "anchors": anchors,
                           "suggested": best, "keep_token": f"{s}:{v}:{d}:{best}"}
                          for (s, v, d), (anchors, best) in ranked.items()],
        }, indent=1))
        return 0
    if accept_suggested:
        keeps = [f"{s}:{v}:{d}:{best}" for (s, v, d), (_a, best) in ranked.items()]
        print(f"dedup-edge: accepting the suggested anchor for all {len(keeps)} conflict(s)"
              f"{'' if repo else ' — WITHOUT --repo, so suggestions are ranked by path length only'}.")
    if not keeps:
        print(f"{len(conflicts)} edge(s) declared more than once, at DIFFERING call sites. "
              f"Pick the true site for each, then re-run with the --keep token(s) — or "
              f"`--accept-suggested` to take every suggestion below:\n")
        for (s, v, d), (anchors, best) in ranked.items():
            print(f"  {s} {v} {d}")
            for anchor in anchors:
                mark = " <- suggested" if anchor == best else ""
                print(f"      {anchor}{mark}")
            print(f"      --keep {s}:{v}:{d}:{best}")
        print("\nEach --keep drops every OTHER occurrence of that triple. The suggestion prefers an "
              "anchor that exists in --repo, outside tests/scripts, with the shortest path — it is "
              "a hint, not a verdict.")
        if repo is None:
            print("NOTE: no --repo was given, so the 'exists in the repo' term is constant and the "
                  "suggestions are ranked by path length alone. Pass --repo for a real ranking.")
        print("Machine-readable: re-run with --json rather than parsing the lines above.")
        return 0
    drop_idx: set[int] = set()
    for tok in keeps:
        parts = tok.split(":")
        if len(parts) < 4:
            print(f"ERROR: bad --keep token '{tok}' (want src:verb:dst:path:line)", file=sys.stderr)
            return 2
        s, v, d, anchor = parts[0], parts[1], parts[2], ":".join(parts[3:])
        idxs = conflicts.get((s, v, d))
        if idxs is None:
            print(f"ERROR: '{s} {v} {d}' is not a duplicated edge in this map", file=sys.stderr)
            return 1
        keep = [i for i in idxs if (m.edges[i].where or "(no call site)") == anchor]
        if not keep:
            print(f"ERROR: none of {s} {v} {d}'s occurrences is anchored at '{anchor}'",
                  file=sys.stderr)
            return 1
        drop_idx |= {i for i in idxs if i != keep[0]}
        if not to_reconcile:
            # Only when this run actually edits the map. Printing it up here made `--to-reconcile`
            # announce `kept … at (no call site)` for a token it then silently skipped — the very
            # "assert what the artifact does not support" shape the skip was added to stop.
            print(f"  kept {s} {v} {d} at {anchor}")
    if to_reconcile:
        # DURABLE. Writing the decision into the assembled map is what made a shipped map
        # irreproducible from its own fragments: 365 edges committed, 416 on re-assemble, the
        # difference being 49 duplicates the next assemble silently restored. `keep_edges` is read
        # by `assemble --reconcile`, so the choice survives every rebuild.
        rec_path = Path(to_reconcile)
        try:
            doc = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.exists() else {}
        except ValueError as e:
            print(f"ERROR: {rec_path} is not valid JSON ({e})", file=sys.stderr)
            return 2
        existing = doc.get("keep_edges") or []
        by_triple = {(k.get("src"), k.get("verb"), k.get("dst")): k for k in existing
                     if isinstance(k, dict)}
        added = updated = skipped = 0
        for tok in keeps:
            parts = tok.split(":")
            s_, v_, d_, anchor = parts[0], parts[1], parts[2], ":".join(parts[3:])
            if anchor == _NO_CALL_SITE:
                # The listing's DISPLAY placeholder for an edge with no anchor. `apply_reconcile`
                # matches against the stored `where`, which is "" for such an edge, so recording the
                # placeholder produces a directive that can never match — a permanent no-op warning
                # "none of ... is anchored at '(no call site)'" on every assemble, phrased as drift
                # rather than as the tool bug it is. `--accept-suggested` walks into it whenever the
                # placeholder sorts first.
                print(f"  SKIPPED {s_} {v_} {d_}: its suggested winner has no call site, and a "
                      f"keep_edges directive matches on the anchor. Give it an anchor in the "
                      f"fragment, or pass an explicit --keep naming another occurrence.",
                      file=sys.stderr)
                skipped += 1
                continue
            print(f"  kept {s_} {v_} {d_} at {anchor}")
            prior = by_triple.get((s_, v_, d_))
            if prior is None:
                new = {"src": s_, "verb": v_, "dst": d_, "where": anchor}
                existing.append(new)
                by_triple[(s_, v_, d_)] = new
                added += 1
            elif prior.get("where") != anchor:
                # Changing your mind was silently discarded while the tool printed `kept ... at
                # <new anchor>` — a durable record asserting what the artifact does not support,
                # which is the pattern this whole series is about.
                print(f"  UPDATED {s_} {v_} {d_}: {prior.get('where')} -> {anchor}")
                prior["where"] = anchor
                updated += 1
        doc["keep_edges"] = existing
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        rec_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if skipped:
            print(f"  {skipped} conflict(s) were NOT recorded (see above) — they are still "
                  f"duplicated in the map.")
        print(f"dedup-edge: recorded {added} new and updated {updated} keep_edges directive(s) in "
              f"{rec_path} ({len(existing)} total). Re-run assemble WITH --reconcile {rec_path}; the map is "
              f"not edited here, so the decision survives every rebuild.")
        # Non-zero when a requested conflict went unrecorded: exit 0 with nothing written is the
        # shape a script reads as success.
        return 1 if skipped and not (added or updated) else 0
    m.edges = [e for i, e in enumerate(m.edges) if i not in drop_idx]
    _write(Path(map_path), m, present)
    print(f"dedup-edge: dropped {len(drop_idx)} duplicate occurrence(s) from the assembled map — "
          f"the next assemble REBUILDS from fragments and restores them. Use --to-reconcile "
          f"<file> to make this durable. Re-run: validate --check-sources → audit → render.")
    return 0


# ── fix security-row ─────────────────────────────────────────────────────────────────────────────
# The Phase-4 writer for a REFUTED security surface. `apply-drift` rewrites a security row's
# `source` when the skeptics agree the anchor moved; it has no answer to the other half of the
# refutation — "that anchor guards nothing, the real gate is elsewhere and your surface/risk text is
# wrong". A live build had to hand-roll that edit, selected the row with
# `'admin' in surface.lower() and source.startswith(…)`, matched TWO rows, and overwrote a CONFIRMED
# claim with the refuted one's replacement text. Nothing caught it but `grounding report`.
#
# So the selector here is EXACT and the multiplicity guard is a refusal, never a "first match":
# every one of `--claim` / `--surface` / `--at` must resolve to exactly one row or the command
# prints the candidates and writes nothing.


def _row_claims(m: ProjectModel) -> list[tuple[int, str]]:
    """Every security row as `(index, its L2 grounding claim)` — the same string
    `l2_worklist_model` pins and a skeptic verdict carries back."""
    return [(i, _security_claim(s.surface, s.source)) for i, s in enumerate(m.security)]


def _select_security_rows(m: ProjectModel, claim: str | None, surface: str | None,
                          at: str | None) -> list[int]:
    """Indexes of the rows matching the given selector(s). Every comparison is EXACT and every
    selector given must hold (they intersect), so `--surface X --at path:line` disambiguates two
    rows sharing a surface without anyone having to invent a regex."""
    idxs = list(range(len(m.security)))
    if claim is not None:
        by_claim = {i for i, c in _row_claims(m) if c == claim}
        idxs = [i for i in idxs if i in by_claim]
    if surface is not None:
        idxs = [i for i in idxs if m.security[i].surface == surface]
    if at is not None:
        idxs = [i for i in idxs if m.security[i].source == at]
    return idxs


def security_row(argv: list[str]) -> int:
    """Rewrite ONE security row's text, selected exactly, or list the rows when no selector is given."""
    map_path = None
    claim = surface = at = None
    sets: dict[str, str] = {}
    as_json = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--json":
            as_json = True
        elif a in ("--map", "--claim", "--surface", "--at",
                   "--set-surface", "--set-risk", "--set-source", "--set-who"):
            i += 1
            val = _need(argv, i, a)
            if a == "--map":
                map_path = val
            elif a == "--claim":
                claim = val
            elif a == "--surface":
                surface = val
            elif a == "--at":
                at = val
            else:
                sets[a[len("--set-"):]] = val
        else:
            return usage_error(_USAGE, "security-row", f"unknown argument '{a}'")
        i += 1
    if not map_path:
        print("ERROR: --map is required", file=sys.stderr)
        return 2
    m, present = _load(Path(map_path))
    if not m.security:
        # A post-T7 map has NO `security[]` by design — an auth surface is a business rule with
        # `access: true`. Saying only "no security rows" reads as "nothing to do" on a map whose
        # access surface is 47 rules, and method.md routed refuted access surfaces here for two
        # releases after the fold. Name the real destination instead of exiting quietly.
        print("security-row: this map holds no security rows.")
        if access_rules(m):
            print(f"  It carries {len(access_rules(m))} `access: true` business rule(s) instead — "
                  f"the T7 fold made an auth surface a RULE, and `security[]` is legacy storage.")
            print("  A rule's statement / why / risk / access is fixed in its OWNING T7 FRAGMENT, "
                  "then re-assembled; there is no `fix` verb for it.")
            print("  A rule SITE whose line moved is `coyomap fix apply-drift` — a site is a "
                  "claim-shaped, drift-eligible anchor like any other.")
        return 0
    selectors = {"--claim": claim, "--surface": surface, "--at": at}
    given = {k: v for k, v in selectors.items() if v is not None}
    if not given:
        if sets:
            print("ERROR: --set-* needs a row to write to. Pass --claim (exact L2 claim), "
                  "--surface (exact surface text) or --at <path:line>. Run without --set-* to "
                  "list the rows and their claims.", file=sys.stderr)
            return 2
        rows = [{"index": i, "surface": s.surface, "source": s.source, "who": s.who,
                 "risk": s.risk, "claim": c}
                for (i, c), s in zip(_row_claims(m), m.security)]
        if as_json:
            print(json.dumps({"security": rows}, indent=1))
        else:
            print(f"{len(rows)} security row(s). Select one with --claim / --surface / --at:")
            for r in rows:
                print(f"  [{r['index']}] {r['surface']}\n        at {r['source'] or _NO_CALL_SITE}")
        return 0
    idxs = _select_security_rows(m, claim, surface, at)
    if len(idxs) != 1:
        # The refusal IS the feature. A substring-matching hand script silently took both rows here.
        print(f"ERROR: that selector matches {len(idxs)} security row(s); exactly one is required, "
              f"and nothing was written.", file=sys.stderr)
        for i2 in idxs:
            s = m.security[i2]
            print(f"    [{i2}] surface={s.surface!r} at={s.source!r}", file=sys.stderr)
        if len(idxs) > 1:
            unused = [flag for flag, val in selectors.items() if val is None]
            print(f"Narrow it with {' or '.join(unused)}." if unused else
                  "Every selector is already given and they still match more than one row, so the "
                  "rows are indistinguishable by text.", file=sys.stderr)
            print("If the rows are true duplicates, resolve them with `coyomap fix dedup-security`.",
                  file=sys.stderr)
        return 2
    if not sets:
        s = m.security[idxs[0]]
        print(f"[{idxs[0]}] surface: {s.surface!r}\n     source: {s.source!r}\n"
              f"     who:     {s.who!r}\n     risk:    {s.risk!r}\n"
              f"     claim:   {_security_claim(s.surface, s.source)!r}")
        print("Pass --set-surface / --set-risk / --set-source / --set-who to rewrite it.")
        return 0
    s = m.security[idxs[0]]
    if "surface" in sets and not sets["surface"].strip():
        # The surface IS the row's identity: it keys `dedup-security`, the impact graph's
        # `security:<surface>` reference and the L2 grounding claim. An unset shell variable in
        # `--set-surface "$NEW"` would otherwise anonymise a security row, and no gate catches it.
        print("ERROR: --set-surface cannot be empty — the surface is the row's identity (it keys "
              "dedup-security, the impact reference and the L2 claim). Nothing written.",
              file=sys.stderr)
        return 2
    changed = 0
    for fieldname, val in sets.items():
        before = getattr(s, fieldname)
        if before == val:
            continue
        print(f"  [{idxs[0]}] {fieldname}: {before!r} → {val!r}")
        setattr(s, fieldname, val)
        changed += 1
    if not changed:
        print("security-row: every --set-* value already matched — nothing written.")
        return 0
    _write(Path(map_path), m, present)
    # A rewritten `surface` or `source` CHANGES the row's L2 claim, so the grounding record now
    # pins a claim string that no longer exists. Say it here: the build that hit this learned it
    # from `finalize`, several turns and one re-assemble later.
    if "surface" in sets or "source" in sets:
        print("note: this row's L2 claim changed, so the pinned grounding record no longer names "
              "it. Re-run `coyomap grounding write` (its --keep-note preserves the note) after the "
              "final assemble.")
    print(f"security-row: rewrote {changed} field(s) on 1 row. "
          f"Re-run: validate --check-sources → audit → render.")
    return 0


# ── fix dedup-security ───────────────────────────────────────────────────────────────────────────


def _duplicate_surfaces(m: ProjectModel) -> dict[str, list[int]]:
    """Security rows whose SURFACE text is identical, keyed by that surface.

    Two fragments harvesting the same auth check is the ordinary cause (one build had `fe-pages`
    and `fe-shared` both claiming the same sidebar gate). Identity is the surface, not the anchor:
    two different surfaces legitimately share one anchor, and treating that as a duplicate is what
    a hand script did just before it deleted a real claim."""
    by_surface: dict[str, list[int]] = {}
    for i, s in enumerate(m.security):
        by_surface.setdefault(s.surface, []).append(i)
    return {k: v for k, v in sorted(by_surface.items()) if len(v) > 1}


def _shared_anchors(m: ProjectModel) -> dict[str, list[int]]:
    """Rows sharing one `source` anchor under DIFFERENT surfaces — reported, never dropped."""
    by_anchor: dict[str, list[int]] = {}
    for i, s in enumerate(m.security):
        if s.source:
            by_anchor.setdefault(s.source, []).append(i)
    return {k: v for k, v in sorted(by_anchor.items())
            if len({m.security[i].surface for i in v}) > 1}


def _fullness(s) -> int:
    """How much a row actually says — the tiebreak when two duplicates differ only in detail."""
    return sum(1 for v in (s.who, s.risk, s.source) if v)


def dedup_security(argv: list[str]) -> int:
    """List, or resolve, security rows authored twice under the same surface."""
    map_path = None
    repo: Path | None = None
    keeps: list[str] = []
    as_json = False
    accept_suggested = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--json":
            as_json = True
        elif a == "--accept-suggested":
            accept_suggested = True
        elif a in ("--map", "--repo", "--keep"):
            i += 1
            val = _need(argv, i, a)
            if a == "--map":
                map_path = val
            elif a == "--repo":
                repo = Path(val)
            else:
                keeps.append(val)
        else:
            return usage_error(_USAGE, "dedup-security", f"unknown argument '{a}'")
        i += 1
    if not map_path:
        print("ERROR: --map is required", file=sys.stderr)
        return 2
    # Same exclusivity as `dedup-edge`, for the same reason: a run that both lists and writes
    # silently did neither.
    if as_json and (accept_suggested or keeps):
        print("ERROR: --json lists without writing; --accept-suggested and --keep write. Pick one: "
              "run --json to review, then re-run with the decision.", file=sys.stderr)
        return 2
    if accept_suggested and keeps:
        print("ERROR: --accept-suggested takes the suggestion for EVERY duplicate, which would "
              "override the --keep token(s) you named. Pass one or the other.", file=sys.stderr)
        return 2
    m, present = _load(Path(map_path))
    dups = _duplicate_surfaces(m)
    shared = _shared_anchors(m)
    ranked = {surface: min(idxs, key=lambda i2: (-_fullness(m.security[i2]),
                                                 _own_code_rank(m.security[i2].source, repo)))
              for surface, idxs in dups.items()}
    if as_json:
        print(json.dumps({
            "duplicate_surfaces": [
                {"surface": surface, "anchors": [m.security[i2].source for i2 in idxs],
                 "suggested": m.security[ranked[surface]].source,
                 "keep_token": f"{surface}::{m.security[ranked[surface]].source}"}
                for surface, idxs in dups.items()],
            "shared_anchors": [
                {"source": src, "surfaces": [m.security[i2].surface for i2 in idxs]}
                for src, idxs in shared.items()],
        }, indent=1))
        return 0
    if shared:
        # Not a defect and never dropped here — but it is the shape that hid a clobbered claim, so
        # it is printed every run, including the clean one.
        print(f"note: {len(shared)} anchor(s) carry MORE THAN ONE surface. That is legal (one line "
              f"can guard two things) and nothing below touches them; edit one with "
              f"`fix security-row --at <path:line> --surface <exact text>`:")
        for src, idxs in shared.items():
            print(f"    {src}")
            for i2 in idxs:
                print(f"      · {m.security[i2].surface}")
    if not dups:
        print("dedup-security: no security surface is authored more than once.")
        if not m.security and access_rules(m):
            print(f"  This map holds no `security[]` rows at all — its access surface is "
                  f"{len(access_rules(m))} `access: true` business rule(s) (T7).")
            print("  Two fragments that harvested one auth check are fused in the FRAGMENT: one "
                  "decision enforced in several places is ONE `access` rule with several sites.")
        return 0
    if not keeps and not accept_suggested:
        print(f"{len(dups)} security surface(s) authored more than once. Keep one anchor per "
              f"surface, then re-run with the token(s):")
        for surface, idxs in dups.items():
            print(f"  {surface}")
            for i2 in idxs:
                s = m.security[i2]
                mark = " (suggested)" if i2 == ranked[surface] else ""
                print(f"      · {s.source or _NO_CALL_SITE}{mark}  risk={s.risk or '—'!r}")
            print(f"      --keep '{surface}::{m.security[ranked[surface]].source}'")
        if not repo:
            print("Pass --repo <root> so the suggestion can prefer an anchor that exists in the "
                  "repo; without it, ranking falls back to path length.")
        return 0
    # DECISIONS are (surface, anchor) pairs. `--accept-suggested` builds them directly; a `--keep`
    # token is RESOLVED against the real candidates rather than split on "::". Splitting was a bug
    # of exactly the kind this command exists to prevent: with a surface named `A::B` present,
    # `partition("::")` read the token the tool itself had printed as surface `A`, and dropped a row
    # belonging to a different surface while reporting success.
    decisions: list[tuple[str, str]] = []
    if accept_suggested:
        decisions = [(surface, m.security[ranked[surface]].source) for surface in dups]
        print(f"dedup-security: accepting the suggested anchor for all {len(decisions)} duplicate(s)"
              f"{'' if repo else ' — WITHOUT --repo, so suggestions are ranked by path length only'}.")
    for token in keeps:
        candidates = [(surface, m.security[i2].source) for surface, idxs in dups.items()
                      for i2 in idxs if token == f"{surface}::{m.security[i2].source}"]
        uniq = sorted(set(candidates))
        if not uniq:
            print(f"ERROR: --keep token {token!r} names no duplicate row. Run without --keep to "
                  f"see the tokens — nothing written.", file=sys.stderr)
            return 2
        if len(uniq) > 1:
            print(f"ERROR: --keep token {token!r} is ambiguous — it reads as "
                  + " and as ".join(f"surface {s!r} at {a!r}" for s, a in uniq)
                  + ". A surface containing '::' cannot be named by a token; resolve these rows by "
                    "hand. Nothing written.", file=sys.stderr)
            return 2
        decisions.append(uniq[0])
    drop: set[int] = set()
    for surface, anchor in decisions:
        idxs = dups.get(surface)
        if not idxs:
            print(f"ERROR: {surface!r} is not authored more than once — nothing written.",
                  file=sys.stderr)
            return 2
        keep_idx = [i2 for i2 in idxs if m.security[i2].source == anchor]
        if not keep_idx:
            print(f"ERROR: {anchor!r} is not one of the anchors for {surface!r} — nothing written.",
                  file=sys.stderr)
            return 2
        if len(keep_idx) > 1:
            # The ORDINARY duplicate: two fragments harvested one auth check, so the rows share the
            # surface AND the anchor. Refusing here made the command unable to resolve the very case
            # it exists for, and the advisory that sends the operator here had no other answer than
            # the hand script this replaces. Rows that are byte-identical are not a choice; rows
            # that differ elsewhere still are.
            rows = [m.security[i2] for i2 in keep_idx]
            first = rows[0]
            identical = all((r.surface, r.source, r.who, r.risk)
                            == (first.surface, first.source, first.who, first.risk) for r in rows)
            if not identical:
                print(f"ERROR: {len(keep_idx)} rows for {surface!r} share the anchor {anchor!r} but "
                      f"differ in `who`/`risk`, so which one survives IS a decision — resolve them "
                      f"with `fix security-row`. Nothing written.", file=sys.stderr)
                for i2 in keep_idx:
                    s = m.security[i2]
                    print(f"    [{i2}] who={s.who!r} risk={s.risk!r}", file=sys.stderr)
                return 2
            print(f"  {len(keep_idx)} identical rows for {surface!r} at {anchor!r} — keeping one.")
        drop.update(i2 for i2 in idxs if i2 != keep_idx[0])
    for i2 in sorted(drop):
        s = m.security[i2]
        print(f"  dropping duplicate: {s.surface} at {s.source or _NO_CALL_SITE}")
    m.security = [s for i2, s in enumerate(m.security) if i2 not in drop]
    _write(Path(map_path), m, present)
    print(f"dedup-security: dropped {len(drop)} duplicate row(s), {len(m.security)} remain. "
          f"Re-run: validate --check-sources → audit → render.")
    return 0


# ── fix row ──────────────────────────────────────────────────────────────────────────────────────
# The writer for a row's OWN TEXT, in the fragment that authored it.
#
# Half the L2 worklist is business rules and access rules (192 of one map's 373 claims), and until
# now nothing could correct one. `fix security-row` was built for exactly this failure — a hand
# script matched `'admin' in surface.lower()`, hit two rows and overwrote a CONFIRMED claim with the
# refuted one's text — and then the T7 fold moved auth surfaces out of `security[]` into `rules`,
# where that verb does not reach. So the guard existed, the danger existed, and they no longer
# pointed at each other; a live build hand-edited two security-relevant rule statements with a python
# heredoc and nothing checked what it hit.
#
# WHY THE FRAGMENT AND NOT THE MAP. The assembled map is a build product: `fix` verbs that write it
# print "if you `assemble` again it is rebuilt from fragments and THIS edit is lost", and the whole
# `reconcile.json` directive mechanism exists to carry map edits across that rebuild. A correction
# written into the owning fragment needs none of that — it survives every re-assemble by
# construction, because it is in the source.
#
# WHY NO INDEX FILE. Eleven element families author their ids in the fragment (`model.ID_ARRAYS`),
# so the owner is found by scanning — 30-odd small files, no new artifact, and nothing that can go
# stale. An id-keyed sidecar was designed and dropped: entry-point ids are MINTED at assemble and
# re-sorted by content, so changing one anchor moved 22 of 104 EP ids on a real map. An index keyed
# on those would silently address the wrong row. `fix row` therefore reaches exactly the rows whose
# ids are authored, and says so when asked for one that is not.

#: Fields `fix row` will never write, and why. Anchors belong to `apply-drift` (it resolves them from
#: the skeptics' verdicts and refuses an ambiguous target); ids are identity; and the five
#: assignment fields are owned by `reconcile.json`, not by any fragment — on one real map ALL 66
#: rules take their `block` from the reconcile file and no fragment rule carries one, so writing it
#: here would be overwritten by the next assemble without a word.
_NEVER_WRITABLE: dict[str, str] = {
    "id": "an id is identity, not text — renaming a row is a fragment edit plus every reference",
    "source": "an anchor is `coyomap fix apply-drift`, which resolves it from the verdicts",
    "where": "an anchor is `coyomap fix apply-drift`, which resolves it from the verdicts",
    "cadence_source": "an anchor is `coyomap fix apply-drift`",
    "subsystem": "assignment lives in reconcile.json (`set`), not in the fragment",
    "subdomain": "assignment lives in reconcile.json (`set`), not in the fragment",
    "capability": "assignment lives in reconcile.json (`set`), not in the fragment",
    "runs_in": "assignment lives in reconcile.json (`set`), not in the fragment",
    "block": "assignment lives in reconcile.json (`set`), not in the fragment",
    "bucket": "assignment lives in reconcile.json (`set`), not in the fragment",
}


#: Files that live beside fragments and are NOT fragments. Pointing `--fragments` at `.coyomap/`
#: instead of `.coyomap/build-fragments/` is the obvious slip, and without this list the verb happily
#: edited `project-map.json` — the assembled build product, which the next `assemble` overwrites.
#: That silently violates the one thing this verb is for. Named, not guessed: a file the loader
#: cannot read is an ERROR the caller must see, so "it did not load" must never double as "skip it".
_NOT_A_FRAGMENT = frozenset({"project-map.json", "preindex.json", "provenance.json",
                             "reconcile.json", "rules.json", "finalize-report.json",
                             LINE_TEXTS_JSON})


def _fragment_paths(where: Path) -> tuple[list[Path], list[str]]:
    """The fragment files to search, and a note per neighbour deliberately skipped."""
    if not where.is_dir():
        return [where], []
    keep, skipped = [], []
    for p in sorted(where.glob("*.json")):
        if p.name in _NOT_A_FRAGMENT:
            skipped.append(p.name)
        else:
            keep.append(p)
    return keep, skipped


def _file_is_ascii(path: Path) -> bool:
    """Was this file written with every non-ASCII character escaped? Then keep it that way."""
    try:
        return path.read_bytes().isascii()
    except OSError:
        return True


def _rows_with_id(doc: object, wanted: str) -> list[tuple[str, int]]:
    """(array key, index) for every top-level row in one fragment document carrying `wanted`."""
    hits: list[tuple[str, int]] = []
    if not isinstance(doc, dict):
        return hits
    for key, value in doc.items():
        if not isinstance(value, list):
            continue
        for i, row in enumerate(value):
            if isinstance(row, dict) and row.get("id") == wanted:
                hits.append((key, i))
    return hits


def _edges_with_triple(doc: object, src: str, verb: str, dst: str) -> list[tuple[str, int]]:
    """(array key, index) for every fragment edge matching `(src, verb, dst)` exactly.

    Fragment edges carry NO `id` — an edge's identity is its triple — so `--id` cannot reach one and
    `_rows_with_id` returns nothing for them. That is why three heredocs on one build rewrote an
    edge's `why` by hand while `fix row` sat unused two turns away: the verb existed, the ADDRESS
    did not."""
    hits: list[tuple[str, int]] = []
    if not isinstance(doc, dict):
        return hits
    for key, value in doc.items():
        if not isinstance(value, list):
            continue
        for i, row in enumerate(value):
            if (isinstance(row, dict) and row.get("src") == src
                    and row.get("verb") == verb and row.get("dst") == dst):
                hits.append((key, i))
    return hits


def _surviving_ids(paths: list[Path]) -> tuple[frozenset[str], str]:
    """Every id the fragments assemble to, plus a complaint when they do not assemble at all.

    This is the guard that makes a text edit safe. `assemble` MERGES rows by content — a rule's
    identity is its normalised statement plus its site set, a component's is file+name, a dep's is
    kind+name — so editing the very text this command edits can split a merged row (minting an id
    that did not exist) or collapse two into one (retiring an id every other artifact still cites).
    Neither is reported by the digest today at the row level, and the audit worklist, the reconcile
    file and the grounding record are all keyed on ids that would have moved underneath them."""
    # Named fields, not positions. This read the results as a 3-tuple and got two same-typed lists
    # the wrong way round, which made the guard inert in the direction that loses data — see
    # `FragmentLoad`. `errors` is fatal here; `notes` (a `*.draft.json`, a verdicts file) is not,
    # and treating them as fatal refused every edit in a directory `assemble` itself accepts.
    loaded = load_fragment_paths(paths)
    if loaded.errors:
        return frozenset(), "; ".join(loaded.errors)
    merged, merge_problems = merge_fragments(loaded.parts)
    if merge_problems:
        return frozenset(), "; ".join(merge_problems)
    ids: set[str] = set()
    for attr in ID_ARRAYS:
        ids.update(el.id for el in getattr(merged, attr, []))
    return frozenset(ids), ""


@dataclass(frozen=True)
class _Edit:
    """One row rewrite, addressed either by id or by edge triple.

    `row` builds one of these and `rows` builds many; everything after the parse is shared, so a
    guard added for one is a guard for both. That mattered: `fix row` grew four guards over four
    builds, and a second hand-rolled batch path would have started again with none of them."""
    row_id: str | None
    edge: tuple[str, str, str] | None
    sets: dict[str, str]
    json_sets: dict[str, object]

    @property
    def label(self) -> str:
        return self.row_id or ":".join(self.edge or ())

    @property
    def edits(self) -> dict[str, object]:
        return {**self.sets, **self.json_sets}


def _edit_faults(edit: _Edit) -> list[str]:
    """Everything wrong with one edit that can be seen without opening a fragment."""
    faults: list[str] = []
    if bool(edit.row_id) == bool(edit.edge):
        faults.append(f"{edit.label or '(no address)'}: give exactly one of an id or an edge "
                      f"triple — they address different things")
    if not edit.edits:
        faults.append(f"{edit.label}: no field to write; give at least one set value")
    blank = sorted(f for f, v in edit.sets.items() if not v.strip())
    if blank:
        # Emptying a statement, a risk or a meaning is deletion wearing an edit's clothes, and every
        # other writer here refuses it (`security-row` refuses an empty surface for the same reason).
        faults.append(f"{edit.label}: refusing to blank {', '.join(blank)} — an empty value "
                      f"deletes the text rather than correcting it")
    for field_name in edit.edits:
        if field_name in _NEVER_WRITABLE:
            faults.append(f"{edit.label}: `{field_name}` is not writable here — "
                          f"{_NEVER_WRITABLE[field_name]}")
    return faults


def _resolve(edit: _Edit, docs: dict[Path, object]) -> tuple[list[tuple[Path, str, int]], list[str]]:
    """The single fragment row this edit addresses — or a refusal on 0 or >1, never a guess."""
    owners: list[tuple[Path, str, int]] = []
    for path, doc in docs.items():
        owners += [(path, key, idx) for key, idx in (
            _rows_with_id(doc, edit.row_id) if edit.row_id
            else _edges_with_triple(doc, *(edit.edge or ("", "", ""))))]
    if len(owners) == 1:
        return owners, []
    if not owners:
        if edit.edge:
            return [], [f"{edit.label}: no fragment declares this edge. The triple must match "
                        f"EXACTLY — `coyomap dump --edges` prints the spelling the fragments use, "
                        f"and an edge the map shows may have been merged from a triple spelled "
                        f"differently in its authoring fragment."]
        return [], [f"{edit.label}: no fragment declares a row with this id. Entry-point ids are "
                    f"MINTED at assemble and exist in no fragment, so they cannot be addressed "
                    f"here; correct the entry point by its trigger/source in the harvest fragment "
                    f"that declares it."]
    detail = ", ".join(f"{p.name}: {k}[{i}]" for p, k, i in owners)
    return [], [f"{edit.label}: declared by {len(owners)} fragment rows — refusing rather than "
                f"guessing which ({detail})"]


def _new_triple(edit: _Edit, target: dict) -> tuple[str, str, str] | None:
    """The triple this edit MOVES an edge to, or None when it is not an edge move.

    An edge's identity is its triple, so writing `verb` (or `src`/`dst`) re-addresses the row. The
    eight identical `emits` → `queues` edits one build made by hand are exactly this shape, which is
    why it is worth a guard rather than a note."""
    if edit.edge is None:
        return None
    moved = {f: edit.edits[f] for f in ("src", "verb", "dst") if f in edit.edits}
    if not moved:
        return None
    after = {**{f: target.get(f) for f in ("src", "verb", "dst")}, **moved}
    return (str(after["src"]), str(after["verb"]), str(after["dst"]))


def _apply_edits(where: Path, edits: list[_Edit]) -> int:
    """Resolve, check and write EVERY edit, or write none of them.

    All-or-nothing and one assembly check for the whole batch, not one per edit. Two reasons, and
    the second is correctness, not speed: a half-applied batch leaves fragments in a state nobody
    chose, and two edits can interact — one splitting a merged row the other collapses — so
    checking them one at a time can pass twice and still be wrong together."""
    if not where.exists():
        print(f"ERROR: {where} not found", file=sys.stderr)
        return 2
    paths, skipped = _fragment_paths(where)
    if skipped:
        print(f"note: not a build fragment, skipped: {', '.join(skipped)}")
    if not paths:
        print(f"ERROR: no build fragment .json under {where}"
              + (f" (skipped {', '.join(skipped)} — did you mean "
                 f"{where / 'build-fragments'}?)" if skipped else ""), file=sys.stderr)
        return 2

    docs: dict[Path, object] = {}
    for path in paths:
        try:
            docs[path] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"ERROR: cannot read {path}: {exc}", file=sys.stderr)
            return 2

    # EVERY fault first, then one refusal. A batch of twenty that reports its faults one run at a
    # time is the loop this verb exists to end.
    faults: list[str] = []
    resolved: list[tuple[_Edit, Path, str, int]] = []
    seen: dict[tuple[Path, str, int], str] = {}
    for edit in edits:
        faults += _edit_faults(edit)
        owners, trouble = _resolve(edit, docs)
        faults += trouble
        if not owners:
            continue
        path, array_key, index = owners[0]
        key = (path, array_key, index)
        if key in seen:
            faults.append(f"{edit.label}: addresses the same row as {seen[key]} — two edits to one "
                          f"row in one batch is an order that is not written down; combine them")
            continue
        seen[key] = edit.label
        target = docs[path][array_key][index]           # type: ignore[index]
        missing = sorted(f for f in edit.edits if f not in target)
        blocked = [f for f in missing if f not in _GATE_REQUESTED_FIELDS]
        if blocked:
            faults.append(f"{edit.label}: has no field(s) {', '.join(blocked)} — a new key here is "
                          f"a schema change, not a correction. Present fields: "
                          f"{', '.join(sorted(target))}"
                          + (f". ({', '.join(sorted(_GATE_REQUESTED_FIELDS))} may be ADDED, because "
                             f"a gate asks a build to add them.)" if _GATE_REQUESTED_FIELDS else ""))
            continue
        resolved.append((edit, path, array_key, index))

    # An edge move must not land on a triple that already exists: `assemble` would then hold the
    # same relation twice, which `validate` reports as a duplicate-edge conflict a build later.
    moves: dict[tuple[str, str, str], str] = {}
    for edit, path, array_key, index in resolved:
        target = docs[path][array_key][index]           # type: ignore[index]
        triple = _new_triple(edit, target)
        if triple is None:
            continue
        if any(_edges_with_triple(doc, *triple) for doc in docs.values()):
            faults.append(f"{edit.label}: moving it to {':'.join(triple)} collides with an edge "
                          f"that already exists — that is a merge, not a rewrite; drop one of them "
                          f"with `coyomap fix drop-edge` instead")
        elif triple in moves:
            faults.append(f"{edit.label}: moves to {':'.join(triple)}, where {moves[triple]} is "
                          f"also going — one batch cannot make two edges the same edge")
        else:
            moves[triple] = edit.label

    if faults:
        print(f"ERROR: {len(faults)} problem(s) — nothing was written:", file=sys.stderr)
        for fault in faults:
            print(f"       {fault}", file=sys.stderr)
        return 2

    before_ids, complaint = _surviving_ids(paths)
    if complaint:
        print(f"ERROR: the fragments do not assemble as they stand, so the effect of an edit cannot "
              f"be checked: {complaint}", file=sys.stderr)
        return 2

    changed: list[tuple[_Edit, Path, str, int, dict[str, object]]] = []
    for edit, path, array_key, index in resolved:
        target = docs[path][array_key][index]           # type: ignore[index]
        # `.get`, not `[…]`: a gate-requested field is ABSENT until this edit adds it, and the
        # before/after record has to be able to say so. Indexing raised `KeyError` on the first
        # field this verb was allowed to create.
        if all(target.get(f) == v for f, v in edit.edits.items()):
            print(f"row: {edit.label} already says that — nothing to write.")
            continue
        before = {f: target.get(f) for f in edit.edits}
        for field_name, value in edit.edits.items():
            target[field_name] = value
        changed.append((edit, path, array_key, index, before))
    if not changed:
        return 0

    # Match each file's OWN escaping. An agent-authored fragment is usually ASCII-escaped, and
    # dumping it with `ensure_ascii=False` rewrites every `\uXXXX` in the file — so a one-field edit
    # arrives as eight unrelated changed lines and buries the actual change in review.
    touched = {path for _, path, _, _, _ in changed}
    text_of = {path: json.dumps(docs[path], indent=2, ensure_ascii=_file_is_ascii(path)) + "\n"
               for path in touched}

    # Write to temp siblings, re-assemble from THAT set, and only keep them if no id moved. The
    # candidates go in a temp DIRECTORY, never beside the fragments: a leftover check file in
    # `build-fragments/` breaks every later assemble with a duplicate-id conflict, the
    # `.draft.json` skip does not cover that name, and two concurrent runs would race on one name.
    with tempfile.TemporaryDirectory() as td:
        swap: dict[Path, Path] = {}
        for path in touched:
            tmp = Path(td) / path.name
            tmp.write_text(text_of[path], encoding="utf-8")
            swap[path] = tmp
        after_ids, complaint = _surviving_ids([swap.get(p, p) for p in paths])
    if complaint:
        print(f"ERROR: that edit makes the fragments fail to assemble — nothing was written: "
              f"{complaint}", file=sys.stderr)
        return 2
    if after_ids != before_ids:
        appeared, vanished = sorted(after_ids - before_ids), sorted(before_ids - after_ids)
        print("ERROR: that edit changes which rows survive assembly — nothing was written.",
              file=sys.stderr)
        if vanished:
            print(f"       id(s) that would DISAPPEAR: {', '.join(vanished)} — the edited text now "
                  f"matches another row, so assemble would merge them and every reference to the "
                  f"retired id would be re-pointed.", file=sys.stderr)
        if appeared:
            print(f"       id(s) that would APPEAR: {', '.join(appeared)} — the edited text no "
                  f"longer matches the row it was merged with, so assemble would split them.",
                  file=sys.stderr)
        print("       Rewrite the text so the merge identity is unchanged, or make the split/merge "
              "deliberate by editing every fragment row involved.", file=sys.stderr)
        return 2

    for path in touched:
        path.write_text(text_of[path], encoding="utf-8")
    fields = 0
    for edit, path, array_key, index, before in changed:
        for field_name, value in edit.edits.items():
            print(f"  {edit.label}.{field_name}: {before[field_name]!r} → {value!r}")
            fields += 1
    print(f"row: rewrote {fields} field(s) across {len(changed)} row(s) in "
          f"{len(touched)} fragment(s): {', '.join(sorted(p.name for p in touched))}.")
    print(f"     Re-assemble to see it in the map. If a row carries L2 CLAIMS (a rule statement, a "
          f"site, an entity store, a cadence), its claim TEXT has changed, so the skeptics' "
          f"verdicts for it no longer match: re-run `coyomap grounding write` AFTER the final "
          f"assemble, or `finalize` will refuse on a stale `live_claims_digest`.")
    return 0


def _parse_triple(raw: str) -> tuple[str, str, str] | None:
    parts = raw.split(":")
    if len(parts) != 3 or not all(p.strip() for p in parts):
        return None
    return tuple(p.strip() for p in parts)     # type: ignore[return-value]


def row(argv: list[str]) -> int:
    """Rewrite one field of one row, in the fragment that authored it."""
    if subverb_help.wants_help(argv):
        return subverb_help.handle(_USAGE, "row", argv) or 0
    fragments = row_id = edge_triple = None
    sets: dict[str, str] = {}
    json_sets: dict[str, object] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--fragments", "--id", "--edge") or a.startswith(("--set-", "--set-json-")):
            if i + 1 >= len(argv):
                return usage_error(_USAGE, "row", f"{a} needs a value")
            val = argv[i + 1]
            if val.startswith("--"):
                # `--set-name --set-risk x` used to set `name` to the literal '--set-risk' and exit 0.
                return usage_error(_USAGE, "row", f"{a} was given '{val}', which is another flag — "
                                                  f"a missing value must not be swallowed silently")
            i += 2
            if a == "--fragments":
                fragments = val
            elif a == "--id":
                row_id = val
            elif a == "--edge":
                edge_triple = val
            elif a.startswith("--set-json-"):
                # STRUCTURED fields. `--set-<field> <text>` writes a string, which is right for a
                # statement, a meaning or a purpose and useless for the rest: an entity's `states`
                # block, a lifecycle `states.source`, a messaging row's `consumers` list, a rule's
                # `sites`. Those were the four edits builds hand-scripted into fragments with
                # `python3 - <<'PY'`, which is the failure `fix` exists to remove — and the reason
                # they hand-scripted them is that no flag could express a nested value.
                field = a[len("--set-json-"):].replace("-", "_")
                try:
                    json_sets[field] = json.loads(val)
                except json.JSONDecodeError as e:
                    return usage_error(_USAGE, "row", f"--set-json-{field} needs valid JSON: {e}")
            else:
                sets[a[len("--set-"):].replace("-", "_")] = val
            continue
        return usage_error(_USAGE, "row", f"unknown argument '{a}'")
    if not fragments or not (row_id or edge_triple):
        return usage_error(_USAGE, "row", "--fragments and one of --id / --edge are required")
    if row_id and edge_triple:
        return usage_error(_USAGE, "row", "--id and --edge address different things; give one")
    edge: tuple[str, str, str] | None = None
    if edge_triple:
        edge = _parse_triple(edge_triple)
        if edge is None:
            return usage_error(_USAGE, "row", f"--edge takes SRC:VERB:DST, got '{edge_triple}'")
    if not sets and not json_sets:
        return usage_error(_USAGE, "row",
                           "give at least one --set-<field> <text> or --set-json-<field> <json>")
    return _apply_edits(Path(fragments), [_Edit(row_id, edge, sets, json_sets)])


def rows(argv: list[str]) -> int:
    """Apply MANY row rewrites in one process, one write, all-or-nothing.

    One build made 37 single `fix row` calls and 8 identical hand edits beside them — twelve
    consecutive turns rewriting one file, eight of them the same one-word change to eight arrows
    pointing at the same box. Every one of those calls re-read every fragment and re-ran the
    assembly check, and each cost a turn."""
    if subverb_help.wants_help(argv):
        return subverb_help.handle(_USAGE, "rows", argv) or 0
    fragments = source = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--fragments", "--edits"):
            if i + 1 >= len(argv):
                return usage_error(_USAGE, "rows", f"{a} needs a value")
            val = argv[i + 1]
            if val.startswith("--"):
                return usage_error(_USAGE, "rows", f"{a} was given '{val}', which is another flag")
            if a == "--fragments":
                fragments = val
            else:
                source = val
            i += 2
            continue
        return usage_error(_USAGE, "rows", f"unknown argument '{a}'")
    if not fragments or not source:
        return usage_error(_USAGE, "rows", "--fragments and --edits are required")
    try:
        raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        return usage_error(_USAGE, "rows", f"--edits {source}: {exc}")
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        return usage_error(_USAGE, "rows", f"--edits {source} is not valid JSON: {exc}")
    if not isinstance(spec, list) or not spec:
        return usage_error(_USAGE, "rows", "--edits takes a non-empty JSON LIST of edits")

    edits: list[_Edit] = []
    for n, item in enumerate(spec):
        if not isinstance(item, dict):
            return usage_error(_USAGE, "rows", f"edit {n} is not an object")
        unknown = sorted(set(item) - {"id", "edge", "set", "set_json"})
        if unknown:
            return usage_error(_USAGE, "rows", f"edit {n} has unknown key(s) "
                                               f"{', '.join(unknown)}; use id / edge / set / "
                                               f"set_json")
        edge = None
        if "edge" in item:
            if not isinstance(item["edge"], str) or _parse_triple(item["edge"]) is None:
                return usage_error(_USAGE, "rows", f"edit {n}: 'edge' takes \"SRC:VERB:DST\", got "
                                                   f"{item['edge']!r}")
            edge = _parse_triple(item["edge"])
        row_id = item.get("id")
        if row_id is not None and not isinstance(row_id, str):
            return usage_error(_USAGE, "rows", f"edit {n}: 'id' must be a string")
        sets = item.get("set") or {}
        json_sets = item.get("set_json") or {}
        if not isinstance(sets, dict) or not isinstance(json_sets, dict):
            return usage_error(_USAGE, "rows", f"edit {n}: 'set' / 'set_json' must be objects")
        bad = sorted(f for f, v in sets.items() if not isinstance(v, str))
        if bad:
            return usage_error(_USAGE, "rows", f"edit {n}: 'set' values must be strings "
                                               f"({', '.join(bad)} is not) — a structured value "
                                               f"goes in 'set_json'")
        edits.append(_Edit(row_id, edge,
                           {f.replace("-", "_"): v for f, v in sets.items()},
                           {f.replace("-", "_"): v for f, v in json_sets.items()}))
    return _apply_edits(Path(fragments), edits)


# ── dispatch ─────────────────────────────────────────────────────────────────────────────────────

#: A walk step's address: a use case's walk (`UC5:3`) or a shared sub-flow's (`SF10:2`).
_STEP_ADDRESS = re.compile(r"^(UC\d+|SF\d+):(\d+)$")


def _steps_in(doc: object, container: str, n: int) -> list[dict]:
    """Every step `n` of the walk `container` in one fragment document."""
    if not isinstance(doc, dict):
        return []
    key, name = ("subflows", "id") if container.startswith("SF") else ("flows", "uc")
    return [st for walk in doc.get(key) or [] if isinstance(walk, dict) and walk.get(name) == container
            for st in walk.get("steps") or [] if isinstance(st, dict) and st.get("n") == n]


def step_notes(argv: list[str]) -> int:
    """Write the `note` on walk steps, in the fragment that authored the walk. All-or-nothing.

    A step where a rule decides says its condition in its note (method.md), and the rule is often
    placed on the step by the rules fan-out, after the tracers are gone. No verb could write a use
    case's step at all, and a sub-flow's only through a `--set-json-steps` of its whole step list:
    on the 2026-09-30 mcpolis build 166 deciding steps shipped with no condition."""
    fragments: str | None = None
    source: str | None = None
    step: str | None = None
    note: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--fragments", "--from", "--step", "--note"):
            if i + 1 >= len(argv):
                return usage_error(_USAGE, "step-notes", f"{a} needs a value")
            val = argv[i + 1]
            i += 2
            if a == "--fragments":
                fragments = val
            elif a == "--from":
                source = val
            elif a == "--step":
                step = val
            else:
                note = val
            continue
        return usage_error(_USAGE, "step-notes", f"unknown argument '{a}'")
    if not fragments or (source is None) == (step is None) or (step is None) != (note is None):
        return usage_error(_USAGE, "step-notes", "--fragments and one of --from <file|-> or "
                                                 "--step <UCn:k> --note <text> are required")
    wanted: dict[str, object]
    if source is not None:
        try:
            raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
            wanted = json.loads(raw)
        except (OSError, ValueError) as exc:
            print(f"ERROR: cannot read --from {source}: {exc}", file=sys.stderr)
            return 2
        if not isinstance(wanted, dict):
            print("ERROR: --from takes one JSON object of step to note: "
                  '{"UC5:3": "only when the plan allows it"}', file=sys.stderr)
            return 2
    else:
        wanted = {str(step): note}
    where = Path(fragments)
    paths, _skipped = _fragment_paths(where)
    docs: dict[Path, object] = {}
    for path in paths:
        try:
            docs[path] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"ERROR: cannot read {path}: {exc}", file=sys.stderr)
            return 2
    faults: list[str] = []
    targets: list[tuple[str, Path, dict, str]] = []
    for address, text in wanted.items():
        hit = _STEP_ADDRESS.match(str(address))
        if not hit:
            faults.append(f"{address}: not a step address — write UCn:k or SFn:k")
            continue
        if not isinstance(text, str) or not text.strip():
            faults.append(f"{address}: the note is empty — a condition is a sentence")
            continue
        container, n = hit.group(1), int(hit.group(2))
        owners = [(path, st) for path, doc in docs.items() for st in _steps_in(doc, container, n)]
        if len(owners) != 1:
            faults.append(f"{address}: {len(owners)} fragment step(s) match — "
                          + ("no fragment writes that walk step" if not owners else
                             "more than one fragment writes it; fix the fragments first"))
            continue
        targets.append((str(address), owners[0][0], owners[0][1], text.strip()))
    if faults:
        print(f"ERROR: {len(faults)} problem(s) — nothing was written:", file=sys.stderr)
        for fault in faults:
            print(f"       {fault}", file=sys.stderr)
        return 2
    touched: set[Path] = set()
    for address, path, st, text in targets:
        if st.get("note") == text:
            continue
        print(f"  {address}.note: {st.get('note', '')!r} → {text!r}")
        st["note"] = text
        touched.add(path)
    for path in touched:
        path.write_text(json.dumps(docs[path], indent=2, ensure_ascii=_file_is_ascii(path)) + "\n",
                        encoding="utf-8")
    print(f"step-notes: wrote {sum(1 for t in targets if t[1] in touched)} note(s) in "
          f"{len(touched)} fragment(s). Re-assemble to see them in the map.")
    return 0


_VERBS = {"apply-drift": apply_drift, "drop-edge": drop_edge, "dedup-relation": dedup_relation,
          "dedup-edge": dedup_edge, "security-row": security_row, "rows": rows,
          "dedup-security": dedup_security, "row": row, "step-notes": step_notes}

_USAGE = """usage: coyomap fix <verb> [args...]

Apply a mechanical reconcile edit to .coyomap/project-map.json IN PLACE. Verbs:

  row --fragments <dir|file> (--id <ID> | --edge <SRC:VERB:DST>)
      --set-<field> <text> [--set-<field> <text> ...]
      Rewrite one row's own TEXT in the FRAGMENT that authored it — a rule's statement or risk, an
      entity's meaning, a component's purpose. The one writer that is durable by construction: the
      fragment is the source, so the edit survives every re-assemble with no reconcile directive.
      Half a real map's L2 worklist is rules with no other repair path; `fix security-row` was built
      for this failure and the T7 fold moved auth surfaces out of `security[]`, where it reaches.
      Finds the owner by SCANNING the fragments for the id, and refuses on 0 or >1 rather than
      guessing. Entry-point ids are minted at assemble and exist in no fragment, so they cannot be
      addressed here — it says so instead of writing nothing.
      REFUSES an edit that would change which ids survive assembly: `assemble` merges rows by
      content (a rule's identity is its statement + sites), so rewording one can split a merged row
      or collapse two, moving ids the worklist, the reconcile file and the grounding record cite.
      Anchors (`source`/`where`) are `apply-drift`; assignment (`subsystem`/`block`/…) is
      reconcile's `set`. Both are refused by name.
      `--edge SRC:VERB:DST` addresses a fragment EDGE, which carries no id — an edge's identity is
      its triple, so `--id` could never reach one and three heredocs on one build rewrote an edge's
      `why` by hand two turns after using this verb correctly. Every guard above still applies.
      `--id` also reaches a happy-path STEP (`--id HP11 --set-why …`); it is not components and
      rules only.

  rows --fragments <dir|file> --edits <edits.json|->
      The SAME edit, many rows, one process, one write, all-or-nothing. `--edits` takes a JSON list:
        [ {"edge": "C12:emits:C30", "set": {"verb": "queues"}},
          {"id": "R7", "set": {"statement": "..."}},
          {"id": "E3", "set_json": {"states": {...}}} ]
      Every guard `row` applies, applied to each edit — and the faults are reported ALL AT ONCE, so
      a batch of twenty costs one run rather than twenty. One build spent twelve consecutive turns
      on 37 single `row` calls plus 8 identical hand edits, eight of them the same one-word verb
      change on eight arrows into one box.
      The assembly check runs ONCE over the whole edited set, which is not only cheaper: two edits
      can interact — one splitting a merged row the other collapses — so checking them one at a
      time can pass twice and still be wrong together.
      Writing `verb` (or `src`/`dst`) on an edge MOVES it, because an edge's identity is its triple.
      A move onto a triple that already exists is refused: that is a merge, not a rewrite, and
      `drop-edge` is the verb for it.

  step-notes --fragments <dir|file> (--from <notes.json|-> | --step <UCn:k> --note <text>)
      Write the NOTE on walk steps, in the fragment that authored each walk: `UC5:3` is step 3 of
      the use case's walk, `SF10:2` step 2 of a shared sub-flow. `--from` takes one JSON object,
      {"UC5:3": "only when the plan allows it", ...}; every address is checked before anything is
      written. The note of a step where a rule decides says its condition, and the rule often
      lands on the step after the tracers are gone: `validate` lists those steps.

  apply-drift --map <map> --verdicts <raw.json>... [--tolerance N] [--to-reconcile <file>]
      Write the grounding skeptics' corrected anchor into each drifted element: an edge `where`, a
      `security[].source`, or an entry point's `cadence_source`. Same verdicts `coyomap
      anchor-drift` reads. Matches the full (src, verb, dst) triple (or the row's exact L2 claim);
      an ambiguous multi-site target is skipped, not blind-rewritten.
      --to-reconcile records the corrections as `set_anchors` in the reconcile file INSTEAD of
      editing the map, so `assemble --reconcile` re-applies them on every rebuild. Without it the
      edit is lost at the next assemble — a live build corrected 14 anchors, re-assembled for one
      fragment edit, lost all 14, and re-typed them by hand.
      A correction whose line leaves the definition the stored anchor sits in is REFUSED, named
      with both anchors, and counted on the last line: moving an anchor onto another function is a
      re-anchor decision, not a mechanical nudge. Refused drift is reported, never gating.

  dedup-edge --map <map> [--repo <root>] [--json]
             (--accept-suggested | --keep <src:verb:dst:path:line> ...) [--to-reconcile <file>]
      With neither --keep nor --accept-suggested, LIST every (src, verb, dst) edge declared more
      than once at DIFFERING call sites — the conflict `validate` warns about — and suggest which
      anchor is the true one. With --keep, drop every other occurrence of that triple.
      --accept-suggested takes the suggestion for EVERY conflict, which is what harvesting the
      printed --keep lines through a shell was trying to do (and got wrong twice: zsh does not
      word-split an unquoted expansion, and the surrounding prose also contains "--keep ").
      --json emits the same listing as data; parse that, never the lines above.
      --to-reconcile writes the choices as `keep_edges` into the reconcile file INSTEAD of editing
      the map, so `assemble --reconcile` re-applies them on every rebuild. Without it the edit is
      lost at the next assemble — a shipped map carried 365 edges while its own fragments
      re-assembled to 416.
      THE THREE MODES ARE EXCLUSIVE, and mixing them is refused rather than guessed at:
        · --to-reconcile NEEDS a decision — pass --accept-suggested or --keep. On its own it used
          to print the listing, write nothing, and exit 0, which reads as success.
        · --json lists, --accept-suggested and --to-reconcile write. Never both.
        · --accept-suggested overrides every --keep you named. Pass one or the other.
      A map with no duplicate edges is not an error: it prints so and exits 0 whatever the flags.
      Pass --repo, or the "exists in the repo" rank term is constant and suggestions fall back to
      shortest-path.

  drop-edge --map <map> <src> <verb> <dst> [--drop-steps | --repoint <newDst>]
                [--to-reconcile <file>]
      Remove a refuted backbone edge. By default it REPORTS the flow steps that rode it (for a
      hand reconcile); --drop-steps removes them, --repoint <newDst> re-points them.
      --to-reconcile writes the drop as a `drop_edges` directive instead of editing the map, so a
      re-assemble re-applies it (the edge is re-derived from the fragments otherwise, and an
      in-place drop has to be redone after every assemble). The edge is verified against the map
      when the directive is written, because `drop_edges` only WARNS on a 0-match at assemble time.

  dedup-relation --map <map> [--drop <En:verb:Em> ...] [--to-reconcile <file>]
      With no --drop, LIST the blocking "declared on both cards" / "declared twice" domain-card
      duplicates and the token to resolve each. With --drop, remove ONE chosen occurrence.
      --to-reconcile records the choices as `drop_relations` INSTEAD of editing the map. Prefer it:
      a duplicate relation BLOCKS, and an in-place edit is discarded by the next assemble, which
      then re-blocks on the duplicate this command had just resolved. This was the only writing
      verb with no way to record its answer.

  security-row --map <map> [--claim <exact claim> | --surface <exact text> | --at <path:line>]
               [--set-surface T] [--set-risk T] [--set-source path:line] [--set-who T] [--json]
      The writer for a REFUTED security surface — when the skeptics say the anchor guards nothing
      and the surface/risk text is wrong. `apply-drift` only moves a row's `source`; this rewrites
      the text too. With no selector it LISTS every row with its exact L2 claim; with a selector
      and no --set-* it prints that one row.
      EVERY selector is an exact match and they intersect, and a selector resolving to 0 or >1 rows
      is REFUSED with the candidates printed — nothing is written. That refusal is the whole point:
      the hand script this replaces matched `'admin' in surface.lower()`, hit two rows, and
      overwrote a CONFIRMED claim with the refuted one's text. Two rows sharing an anchor is legal,
      so disambiguate with --at plus --surface, or use --claim (unique per row).

  dedup-security --map <map> [--repo <root>] [--json] [--accept-suggested | --keep <surface::anchor> ...]
      Resolve security rows authored more than once under the SAME surface (two fragments
      harvesting one auth check). Identity is the surface, never the anchor — two different
      surfaces sharing one anchor is legal and is reported, not dropped.
      With neither --keep nor --accept-suggested it LISTS the duplicates and suggests which anchor
      to keep (pass --repo, or the "exists in the repo" rank term is constant and the suggestion
      degrades to shortest-path). --json emits the same listing as data.
      Rows that are byte-identical are not a choice — one is kept. Rows sharing surface AND anchor
      but differing in `who`/`risk` ARE a choice, and are refused: use `security-row`.

NOTE — `security-row` and `dedup-security` edit the ASSEMBLED map and have no `--to-reconcile`
form, so their edit is DISCARDED by the next `assemble` (every write prints that warning). Run them
after the last assemble, or make the same change in the owning fragment. The verbs with a durable
form are `apply-drift`, `dedup-edge`, `drop-edge` and `dedup-relation`; `row` needs none, because it
edits the fragment itself.

After any fix, re-run the invariant: validate --check-sources → audit → render."""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    verb, rest = argv[0], argv[1:]
    fn = _VERBS.get(verb)
    if fn is None:
        print(f"coyomap fix: unknown verb '{verb}'\n", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2
    # Above the per-verb parsers on purpose: each one treats an unknown flag as a usage error, so
    # all four answered `ERROR: unknown argument '--help'`. See subverb_help.
    helped = subverb_help.handle(_USAGE, verb, rest)
    if helped is not None:
        return helped
    return fn(rest)


if __name__ == "__main__":
    raise SystemExit(main())
