#!/usr/bin/env python3
"""`coyomap finalize` — the pre-commit read: one command, one verdict, one durable record.

It runs `validate` (`--check-sources --check-coverage`), `audit`, both `anchor-drift` passes and —
when it is given verdicts — `grounding refutations`, and writes `.coyomap/finalize-report.{json,md}`.
It adds no check of its own; every finding here is one those commands already produce.

**It compares nothing against a previous map, deliberately.** An earlier version of this command did,
and that was wrong for the build: in real use a map EVOLVES INCREMENTALLY alongside the code, so a
from-scratch rebuild is a first-run event and there is usually no meaningful predecessor to diff
against. Rebuilding often is a coyomap-DEVELOPER habit, with its own `.coyomap/dev-rebuilds/NNNN/`
convention that users should not adopt — so baseline comparison belongs to the developer's
`/coyomap-retro`, which already does it (`eval/retro/method.md`), and not to anybody's build.

**It is a convenience wrapper, not an enforcement point.** Nothing makes a build run it, and in a
shell pipeline the exit status is the LAST command's — so `coyomap finalize | grep …` returns grep's
0. A live build wrote exactly that shape at the step this command occupies (`validate … | grep -E …;
audit … > /dev/null 2>&1`). A tool cannot fix that by exiting non-zero harder.

What it is actually for, then, is two properties the separate commands do not have:

1. **A record the build cannot erase.** The build above sent `audit` to `/dev/null`, then reported
   "gates clean" to the operator with four warnings and two advisories open. Findings are written to
   a FILE, with whole lists, so `> /dev/null`, `| tail -12` and a summary-from-memory all fail to
   hide them.
2. **An explicit answer to "did every check actually run".** Run the three commands by hand and a
   skipped one looks identical to a clean one. Here a leg that should have run and did not makes the
   verdict INCOMPLETE, which is not a pass and exits non-zero — because "the gate did not run" must
   never read as "the gate passed".

**Exit code.** 0 when nothing blocking was found and every leg ran; 1 for a blocking finding
(exactly what `validate` and `audit` already block on — a schema/reference problem, an L1
contradiction) or for INCOMPLETE. Unapplied anchor drift is reported, never gating: on the map this
came from, all 17 confirmed rows were entry-point cadence claims and `fix apply-drift` cannot apply
one of them, so gating on it would be a false failure with no remedy.

Stdlib-only (the cli.py dependency firewall).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field

from coyomap.challenge import (
    batch_claims,
    batch_theme,
    unvoted_after_the_last_wave,
    verdict_files,
    voted_claims,
)
from pathlib import Path
from typing import TYPE_CHECKING

from coyomap import balance_lib, buildstate, findings, records
from coyomap.reporting import item_lines, shown

if TYPE_CHECKING:
    from coyomap.model import ProjectModel

from coyomap.access_surface import AccessClaim, load_claims, lost_files, where_lines
from coyomap.audit_model import WorkItem, l2_worklist_model
from coyomap.credentials import (UNCOMMITTED_REMEDY, map_folder_files, places, redact,
                                 scan as scan_credentials)
from coyomap.grounding import live_claims_digest, unopened, unvoted_reason
from coyomap.contract import BUDGETS_FILE
from coyomap.model import ModelError, access_rules, load_model, load_model_path, resolve_map_path
from coyomap.preindex_lib import expected_components, granularity_band
from coyomap.provenance import session_transcript
from coyomap.uncommitted import never_committed

#: The extras heading the access-baseline advisory offers as its escape, and READS. Named the way
#: `AUDIT_EXCEPTIONS_HEADING` and `DRIFT_EXCEPTIONS_HEADING` are, so the method contract's scan for
#: "which headings do the tools actually read" finds it without a literal at the call site.
ACCESS_BASELINE_EXCEPTIONS_HEADING = "Access baseline exceptions"

#: The extras heading the late-claims leg READS: a claim written after the last fact-check wave
#: that ships without a vote, keyed by its `path:line` anchor (or by the whole claim when it has
#: none), with the reason no late wave voted on it.
LATE_CLAIMS_HEADING = "Late claims without a vote"

#: The file prefix the method gives a late wave's claims and verdicts (`claims-late-*.json`):
#: one more small wave, cut after the second (`added-`), over the claims written after it.
LATE_WAVE_PREFIX = "late-"

#: Where the durable record goes, next to the map it describes.
REPORT_STEM = "finalize-report"


#: A leg's outcome. The split exists because the first version had none of it and got the most
#: important case wrong: a leg that DID NOT RUN contributed 0 blocking and 0 advisory, so a run whose
#: validate leg errored out (a typo'd `--repo` is enough) reported **CLEAN**, exit 0, on a map with a
#: dangling reference. A report that testifies a gate passed when the gate never ran is worse than no
#: report — it is the exact failure this whole command was written to stop.
RAN = "ran"        # the check executed and its findings are below
FAILED = "failed"  # the check should have run and did not — never reported as a pass


@dataclass
class Leg:
    """One check's outcome. `blocking` decides the exit code; `status` decides whether a verdict of
    CLEAN is even permitted."""

    name: str
    status: str
    blocking: list[str] = field(default_factory=list)
    advisory: list[str] = field(default_factory=list)
    note: str | None = None      # why it did not run, or a one-line summary of what it did

    @property
    def ran(self) -> bool:
        return self.status == RAN


@dataclass
class FinalizeReport:
    map_path: str
    map_sha256: str              # so a STALE report cannot be read as this map's result
    legs: list[Leg]
    verdict: str                 # BLOCKED | INCOMPLETE | ADVISORIES | CLEAN
    advisory_total: int
    blocking_total: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


def _run_leg(name: str, argv: list[str]) -> tuple[int, str, str]:
    """Run one core subcommand IN THIS PROCESS, capturing its streams."""
    import io
    import contextlib
    out, err = io.StringIO(), io.StringIO()
    code = 2
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            if name == "validate":
                from coyomap import validate_model
                code = validate_model.main(argv)
            elif name == "audit":
                from coyomap import audit_model
                code = audit_model.main(argv)
            elif name == "anchor-drift":
                from coyomap import anchor_drift
                code = anchor_drift.main(argv)
            elif name == "balance":
                from coyomap import balance
                code = balance.main(argv)
            elif name == "grounding":
                from coyomap import grounding
                code = grounding.main(argv)
        except SystemExit as e:                       # a subcommand that argues with its own args
            # `sys.exit("msg")` carries a STRING, so int() would raise inside the handler.
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 2)
    return code, out.getvalue(), err.getvalue()


def _validate_leg(map_path: Path, repo: Path | None) -> Leg:
    argv = [str(map_path), "--check-sources", "--check-coverage", "--json"]
    if repo is not None:
        argv += ["--repo", str(repo)]
    code, out, err = _run_leg("validate", argv)
    try:
        payload = json.loads(out)
    except ValueError:
        return Leg("validate", FAILED, note=f"validate did not return JSON (exit {code}): "
                                               f"{(err or out).strip()[:200]}")
    return Leg("validate", RAN, blocking=list(payload.get("problems") or []),
               advisory=list(payload.get("warnings") or []),
               note=payload.get("checked") or None)


def _live_surfaces(map_path: Path) -> dict[bool, set[str]] | None:
    """The map's claim surface at each tier `audit` can compute — `{False: default, True:
    behavioural}` — or None when the file does not load as a map."""
    try:
        m = load_model(resolve_map_path(map_path).read_text(encoding="utf-8"))
        return {tier: {w.claim for w in l2_worklist_model(m, behavioural=tier)}
                for tier in (False, True)}
    except Exception:
        return None


def _record_tier(map_path: Path) -> bool | None:
    """Which claim tier the map's grounding record describes, read off its own digest.

    `grounding write --map` hashes the live surface at the PINNED WORKLIST'S tier
    (`grounding.worklist_is_behavioural`), and this file re-hashed it at the default tier always.
    On the first build that pinned a behavioural worklist the two could not agree — 1782 claims
    hashed, 833 compared — so the one proof field in the record raised a mismatch on a record
    that described the map exactly, and the audit leg's headline counted the smaller surface.
    The record carries no tier field and needs none: at most one surface matches its digest.

    True: behavioural. False: default. None: no digest to read, or neither surface matches —
    the audit then runs at the default tier and `_stale_grounding_pin` says so."""
    try:
        doc = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    g = doc.get("grounding") if isinstance(doc, dict) else None
    digest = g.get("live_claims_digest") if isinstance(g, dict) else None
    if not isinstance(digest, str) or not digest:
        return None
    surfaces = _live_surfaces(map_path)
    if surfaces is None:
        return None
    for tier in (False, True):
        if live_claims_digest(surfaces[tier]) == digest:
            return tier
    return None


def _audit_leg(map_path: Path, verdicts: list[Path] | None = None,
               behavioural: bool = False) -> Leg:
    """`behavioural` runs the audit at the record's own tier (`_record_tier`), so the worklist
    this leg counts and the surface the digest is checked against are the one the record was
    written from."""
    argv = [str(map_path), "--json"] + (["--with-behavioural"] if behavioural else [])
    code, out, err = _run_leg("audit", argv)
    try:
        payload = json.loads(out)
    except ValueError:
        return Leg("audit", FAILED, note=f"audit did not return JSON (exit {code}): "
                                            f"{(err or out).strip()[:200]}")
    findings = payload.get("findings") or []
    blocking = [f"{f.get('check')}: {f.get('location')} — {f.get('message')}"
                for f in findings if f.get("severity") == "CONTRADICTION"]
    advisory = [f"{f.get('check')}: {f.get('location')} — {f.get('message')}"
                for f in findings if f.get("severity") != "CONTRADICTION"]
    counts = payload.get("theme_counts") or {}
    live_claims = [str(w.get("claim", "")) for w in (payload.get("worklist") or [])
                   if isinstance(w, dict)]
    live_worklist = len(live_claims)
    note = (f"{live_worklist} L2 claims on the grounding worklist"
            + (f" ({', '.join(f'{k}:{v}' for k, v in counts.items())})" if counts else ""))
    stale = _stale_grounding_pin(map_path, live_claims, verdicts or [])
    if stale:
        advisory.append(stale)
    return Leg("audit", RAN, blocking=blocking, advisory=advisory, note=note)


def _recomputed_delta(g: dict, live: set[str], verdicts: list[Path]) -> str | None:
    """Check the record's two delta counts against the verdicts, when they are available.

    The digest proves the record describes THIS map's claim surface. It says nothing about whether
    `claims_superseded` and `claims_added_since` are true — a record can carry a valid digest beside
    two invented numbers, and every other check still passes. That is a poor property for the two
    fields whose only job is honesty.

    ONE-SIDED BOUNDS, not equality, and that distinction is the whole correctness argument. The
    first version demanded that the verdict set exactly match `claims_total`, on the reasoning that
    a partial set would accuse an honest record. True of an equality; false of a bound. For any
    partial set `P` of the true pinned set `T`, and live set `L`:

        P ⊆ T  ⇒  |P \\ L| ≤ |T \\ L|      so `claims_superseded` BELOW |P \\ L| is provably wrong
        P ⊆ T  ⇒  |L \\ P| ≥ |L \\ T|      so `claims_added_since` ABOVE |L \\ P| is provably wrong

    (Brute-forced over 200 000 random configurations: zero counterexamples.) Both hold whatever
    subset of the verdict files `finalize` was handed, so no honest record can be accused — and
    neither bound consults `claims_total`, which is what closes the three escapes the equality
    version left: raising the total by one, setting it to a digit STRING, and the lower-total
    bypass that an earlier commit patched one direction of.
    """
    if not verdicts:
        return None
    try:
        from coyomap.anchor_drift import load_verdicts
        rows, _notes = load_verdicts([str(v) for v in verdicts])
    except BaseException:
        # BaseException on purpose: `load_verdicts` raises SystemExit on a malformed file, which an
        # `except Exception` lets straight through a guard whose entire job is to stand down.
        return None
    pinned = {str(r.get("claim")) for r in rows if isinstance(r, dict) and r.get("claim")}
    if not pinned:
        return None
    at_least_superseded = len(pinned - live)
    at_most_added = len(live - pinned)
    got_superseded = g.get("claims_superseded", 0)
    got_added = g.get("claims_added_since", 0)
    wrong = []
    if isinstance(got_superseded, int) and got_superseded < at_least_superseded:
        wrong.append(f"`claims_superseded` says {got_superseded}, but the verdict files already "
                     f"name {at_least_superseded} pinned claim(s) this map no longer carries")
    if isinstance(got_added, int) and got_added > at_most_added:
        wrong.append(f"`claims_added_since` says {got_added}, but at most {at_most_added} live "
                     f"claim(s) can be new — the rest have verdicts")
    if not wrong:
        return None
    return ("grounding: the record's delta counts contradict the verdict files — "
            + "; ".join(wrong) + ". These are the numbers a reader uses to judge whether the "
            "superseded claims were the refuted ones, so a wrong count is worse than none. Re-run "
            "`coyomap grounding write --worklist <pinned.json> --map <this map> --verdicts <…>`.")


def _stale_grounding_pin(map_path: Path, live_claims: list[str],
                         verdicts: list[Path] | None = None) -> str | None:
    """The map's `grounding` record no longer describes the map's claim surface.

    `grounding write` PINS `claims_total` to the worklist the skeptics were given, and that pin is
    load-bearing: recomputing the split against the finished map yields `refuted 0`, because the
    claims a reconcile deletes are exactly the refuted ones. But reconciling a refutation rewrites
    its claim, so the pinned surface and the shipped one legitimately differ, and for a long time a
    build had no way to say so — the pinned record raised this advisory, re-running against a fresh
    worklist was REFUSED, and explaining it in `note` changed nothing. Three documented escapes, all
    closed. `grounding write --map` is the escape: it records the delta and a DIGEST of the live
    claim set.

    So the check is the digest, not the counts. `claims_total - claims_superseded +
    claims_added_since == live` is a tautology given the writer's own refusals (they force the vote
    set to equal the pinned set), so it closes for every input and proves nothing; and every
    size-based test is blind to a 1-for-1 rewrite, which is the shape a reconcile actually produces.
    A live build shipped `418 of 418 challenged` on a map whose worklist held 415, and quoted the
    418 in its commit message as fact — the digest is what makes that impossible to do silently.

    Falls back to the old count comparison when no digest is stored, so a record written without
    `--map`, or by an older build, behaves exactly as before."""
    try:
        doc = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    g = doc.get("grounding") if isinstance(doc, dict) else None
    if not isinstance(g, dict):
        return None
    # Both sides over the DE-DUPLICATED claim set: `build_record` de-duplicates the pinned side, and
    # two sides counted by different rules measure the rule rather than the map.
    live_set = set(live_claims)
    stored_digest = g.get("live_claims_digest")
    pinned_raw = g.get("claims_total")
    pinned = pinned_raw if isinstance(pinned_raw, int) and pinned_raw > 0 else 0

    # THE DIGEST IS CHECKED FIRST, and never gated on `claims_total`. It used to sit behind an early
    # return for a missing or nonsensical total, so a record could buy silence by CORRUPTING that
    # field: `claims_total` of 0, of -5, or of the string "446" all skipped the digest comparison
    # entirely, even when the digest was provably a different map's. Corrupting a field must never be
    # safer than filling it in — that is the same shape as the bypass fixed one commit earlier, and
    # this is the third time it has appeared in this file's history.
    if isinstance(stored_digest, str) and stored_digest:
        if live_claims_digest(live_set) == stored_digest:
            # The surface matches. The COUNTS beside it are still unverified — check them when the
            # verdicts are at hand, because a valid digest and two invented numbers coexist happily.
            return _recomputed_delta(g, live_set, verdicts or [])
        superseded = g.get("claims_superseded", 0)
        added = g.get("claims_added_since", 0)
        # Name the tier, or a reader cannot tell a moved surface from a record written at the
        # other tier — which is what this advisory reported on one live build.
        surfaces = _live_surfaces(map_path)
        tier_note = ""
        if surfaces is not None and live_set in (surfaces[False], surfaces[True]):
            mine_default = live_set == surfaces[False]
            other = surfaces[True] if mine_default else surfaces[False]
            here = "at the default tier" if mine_default else "with `--with-behavioural`"
            there = "with `--with-behavioural`" if mine_default else "at the default tier"
            if live_claims_digest(other) == stored_digest:
                tier_note = (f" {here}; the record matches the {len(other)} {there} — the surface "
                             f"is fine and the tier compared at is not")
            else:
                tier_note = f" {here} and {len(other)} {there}, and the record matches neither"
        return (f"grounding: the record's `live_claims_digest` does not match this map's claim "
                f"surface. It was written against a map with {pinned} pinned claim(s), "
                f"{superseded} superseded and {added} added since the pin; this map's audit "
                f"worklist holds {len(live_set)}{tier_note}. Something changed the claims AFTER "
                f"`grounding write` ran — re-run it as the last step before the final assemble:\n"
                f"  coyomap grounding write --worklist <pinned.json> --map {map_path} "
                f"--verdicts <…> --out .coyomap/build-fragments/grounding.json")
    if not pinned:
        # No digest AND no usable `claims_total`: there is nothing here to compare. `validate` owns
        # the malformed-record complaint (negative counts, a split that does not add up); this
        # command reports staleness, and a record with no total is not stale, it is unfinished.
        return None
    if pinned == len(live_set):
        # Counts agree — which proves nothing. A 1-for-1 rewrite (the shape a reconcile actually
        # produces) leaves the count untouched, so this branch is silent EXACTLY where the digest
        # was needed. Say the record cannot be checked, rather than implying it passed.
        return (f"grounding: the record carries no `live_claims_digest`, so nothing here can confirm "
                f"it describes THIS map. The counts agree ({pinned}), but a reconcile that rewrites "
                f"a claim leaves the count unchanged, so agreement is not evidence. Re-run "
                f"`coyomap grounding write --worklist <pinned.json> --map <this map> --verdicts <…>` "
                f"as the last step before the final assemble.")
    return (f"grounding: the record is pinned to a worklist of {pinned} claim(s), but this map's "
            f"audit worklist holds {len(live_set)} — and the record does not say why. Reconciling a "
            f"refutation rewrites its claim, so the two legitimately differ; record the delta with "
            f"`coyomap grounding write --worklist <pinned.json> --map <this map> --verdicts <…>`, "
            f"which stores how many claims were superseded and added and a digest of the live "
            f"surface. Do NOT re-pin against a fresh worklist: the claims a reconcile deletes are "
            f"the refuted ones, so that records `refuted 0`.")


#: anchor-drift's notes about the 'Drift exceptions' lines themselves.
_DRIFT_RECORD_NOTE = re.compile(r"recorded drift exception\(s\) matched no finding|"
                                r"drift finding\(s\) suppressed by recorded exception|"
                                r"'Drift exceptions' heading open with `anchor-drift`")
#: Of those, the two that say a recorded line does nothing.
_INERT_DRIFT_RECORD = re.compile(r"recorded drift exception\(s\) matched no finding|"
                                 r"'Drift exceptions' heading open with `anchor-drift`")


def _drift_leg(map_path: Path, repo: Path, verdicts: list[Path],
               behavioural: bool = False) -> Leg:
    """`behavioural` (verdict-based pass only) counts coverage at the record's tier, so the
    gate block's `challenged N of M` and its audit line count one surface."""
    argv = ["--map", str(map_path), "--repo", str(repo)]
    for v in verdicts:
        argv += ["--verdicts", str(v)]
    if behavioural and verdicts:
        argv.append("--with-behavioural")
    code, out, err = _run_leg("anchor-drift", argv)
    text = (out or "") + (err or "")
    drifts = [ln.strip()[2:] for ln in text.splitlines() if ln.startswith("  - ")]
    # WHAT anchor-drift SAID ABOUT THE RECORDED LINES, carried beside its findings: a line that
    # does not parse, a line that matched no finding, and what the lines suppressed. Only the
    # verdict-based pass: the recorded lines answer verdict findings, so the shape-only pass would
    # call every one of them idle. They used to be dropped with every line not shaped `  - `.
    # COUNTED APART from the drifts: counted with them, the real map's gate block said "1 drifted
    # anchor(s)" over a pass that found none and one suppression note.
    notes = ([ln.strip() for ln in text.splitlines() if _DRIFT_RECORD_NOTE.search(ln)]
             if verdicts else [])
    rows = drifts + notes
    kind = "verdict-based" if verdicts else "shape-only"
    # Carry the COVERAGE line into the report and the gate block. Without it the leg printed
    # "no drifted anchors" off a pass that had seen 31 of 404 claims — the same "the gate did not
    # run reads as the gate passed" sentence this whole command exists to make impossible, in the
    # one artifact meant to be quotable.
    coverage = next((ln.strip().split(" — ")[0] for ln in text.splitlines()
                     if ln.startswith("challenged ")), "")
    # ADVISORY on purpose: `fix apply-drift` handles edge and security anchors only, so on the map
    # this command was written for all 17 confirmed rows were entry-point cadence claims it cannot
    # apply. A gate on a finding with no remedy is a false failure.
    return Leg(f"anchor-drift ({kind})", RAN if code in (0, 1) else FAILED, advisory=rows,
               note=((f"{len(drifts)} drifted anchor(s) — reconcile each (fix the `where`, or "
                      f"record why it stands); `fix apply-drift` covers edge + security anchors only"
                      if drifts else "no drifted anchors")
                     + (f" · {len(notes)} note(s) on the recorded lines" if notes else "")
                     + (f" · {coverage}" if coverage else "")))


def _refutations_leg(map_path: Path, verdicts: list[Path]) -> Leg:
    """`grounding refutations` — does the shipped map still assert what its own skeptics disproved?

    BLOCKING, unlike anchor drift, and the difference is whether a remedy exists. A drifted anchor
    can be one `fix apply-drift` cannot apply, so gating on it is a false failure with no way out.
    A surviving refutation always has one: correct the claim or drop the row, which is what the
    build contract already requires of every refutation. Until this leg existed nothing looked: a
    live map shipped two refuted edges while this very report said 0 blocking and never used the
    word "refuted", because `validate` reads shape, `audit` reads the map against itself, and the
    `grounding` record reduces the pass to four numbers in which a refutation that was reconciled
    and one that was ignored are the same integer."""
    argv = ["refutations", "--map", str(map_path), "--json"]
    for v in verdicts:
        argv += ["--verdicts", str(v)]
    code, out, err = _run_leg("grounding", argv)
    try:
        payload = json.loads(out)
    except ValueError:
        return Leg("grounding refutations", FAILED,
                   note=f"it did not return JSON (exit {code}): {(err or out).strip()[:200]}")
    surviving = list(payload.get("surviving_refutations") or [])
    # WHAT THIS GATE STOPPED FIRING ON. A refutation a closer REJECTED leaves `surviving_refutations`
    # and, until this line, left the report with it: the same map went `BLOCKED — 1 blocking` to
    # `ADVISORIES — 0 blocking` with the words "refuted", "appeal" and "closer" appearing nowhere in
    # the report, the gate block or the commit message. A gate that stops firing without saying what
    # it stopped firing on is the shape every silent pass in this tool has taken.
    appealed = list(payload.get("settled_on_appeal") or [])
    stated = list(payload.get("unseen_by_any_skeptic") or [])
    dissent = list(payload.get("access_dissent") or [])
    # A WALK STEP OR AN INTERFACE CLAIM IS REPORTED, NOT BLOCKED (`grounding.REPORT_ONLY_KINDS`):
    # the gate could not place those claims at all until 2026-09-30, and gating on them before the
    # closer's ruling on disputed appeals is fixed would have stopped that very build.
    report_only = [s for s in surviving if s.get("blocks") is False]
    surviving = [s for s in surviving if s.get("blocks") is not False]
    blocking = [f"{s['claim']} — REFUTED by {s['refuted_by']} skeptic(s)"
                + (" and outvoted, then UPHELD on appeal," if s.get("outvoted") else "")
                + f" and still in the map, unchanged. Correct the claim or drop the row; a "
                f"reconciled refutation no longer resolves here."
                + (f" Skeptic: {s['note'][:300]}" if s.get("note") else "")
                for s in surviving]
    # AN ACCESS CLAIM CONFIRMED OVER A DISSENT NO CLOSER HEARD. The tally files a 2-1 claim as
    # confirmed, so no count shows the one; on the 2026-09-30 mcpolis build two such dissents were
    # dropped from the closer's brief by hand and an access rule shipped `verified` against a
    # counterexample the code supports. Blocking, because the remedy costs one closer: the brief
    # `contract closer --from-verdicts` builds carries every one under "Outvoted dissent".
    blocking += [f"{d['claim']} — an ACCESS claim ({d['id']}) the majority CONFIRMED while "
                 f"{d['refuted_by']} skeptic(s) REFUTED it, and no closer has ruled on the dissent. "
                 f"A split vote on who may do what goes to a closer: `coyomap contract closer "
                 f"--from-verdicts <verify dir> --map <map>` carries it under 'Outvoted dissent'; "
                 f"send that section whole." + (f" Dissent: {d['note'][:300]}" if d.get("note")
                                               else "")
                 for d in dissent if not d.get("closed")]
    # ONE advisory line, not one per element. A live map produced 81 of these, and an advisory in
    # this report is contractually "fixed or recorded under the heading its message names" — 81 rows
    # with no heading to record them under is not a finding, it is noise that pushes the ten real
    # advisories off the top. The count is the finding; `by-element` is where the list lives.
    # ONE SHAPE IS PROMOTED OUT OF THE COUNT LINE, and only one: an ACCESS rule that states
    # `verified` with NO vote at all. The rest of this list is a wording judgement — a component
    # described as `verified` when the pass part-checked it overstates how it was read. An access
    # rule is different in kind: `verified` on it tells a reader that someone checked who may do
    # what, and nobody did. The shipped mcpolis map carried two, `A sign-in return must carry an
    # unforged ticket` and `Live updates never cross organizations`, both authored AFTER the
    # worklist was pinned — so no skeptic could have seen them — and both labelled by the hand that
    # wrote them. The map's own note admits it: "neither went to a skeptic, so they carry less
    # assurance than the 728 that did". It shipped as an advisory nobody acted on.
    #
    # `part-checked` stays advisory. Some skeptic did read the rule, so the label is an
    # overstatement rather than an invention, and a gate that cannot tell those apart would fail
    # honest maps. `unchecked` is the case with nothing behind it at all.
    # `voted_under_any_anchor` is what keeps this from firing on a rule that WAS challenged and then
    # re-anchored. Votes pair to an element by exact claim text, and a rule-site claim carries the
    # `file:line` in it, so one `fix apply-drift` orphans every vote the rule had and the element
    # reads `unchecked`. Blocking on `unchecked` alone turned 50 confirmed access rules of a real
    # map into build failures under a message asserting nobody had voted.
    # NO LONGER KEYED ON THE LABEL, and ADVISORY rather than blocking. Two separate decisions.
    #
    # The label went because it was never the right test: `confidence` records what the AUTHOR knew,
    # so an access rule the author genuinely read is honestly `verified` whether or not a skeptic
    # saw it. Keyed on `verified` the check was also DEAD BY CONSTRUCTION — the old contract told
    # every agent to write `inferred`, and 49 of 49 access rules on one live map and 30 of 30 on
    # another say exactly that. It had never fired.
    #
    # It is advisory because making it live and blocking in one step FAILED BOTH REFERENCE MAPS,
    # with no way out: a blocking finding has no recorded-exception route at all, and the only
    # remedy the message can offer ("send it to a skeptic") is unreachable once the verify phase has
    # closed. That is the same trap the crossing-anchor and messaging-participant checks were kept
    # advisory to avoid, on the same evidence, earlier the same day — and this one was shipped
    # blocking anyway. A gate that fails every existing map teaches a lead to ignore the gate.
    #
    # PROMOTE IT once one build has shipped with zero of these, and give it a recordable heading
    # first: an access rule minted after the worklist was pinned genuinely could not be challenged,
    # and that is a build-ordering fact the operator has to be able to state.
    unvetted_access = [e for e in stated
                       if e.get("access") and e.get("kind") == "rule_site"
                       and e.get("status") == "unchecked"
                       and not e.get("voted_under_any_anchor")]
    # RE-WORDED AFTER THE VOTE is not "never challenged". A rule whose statement a reconcile
    # corrected keeps no vote under its new text, and the line below called BR1 and BR21 of the
    # 2026-09-30 mcpolis map "never challenged" while all 11 of their sites carried 3 votes each
    # under the older wording. The pinned worklist names the element and the line of every claim,
    # so `grounding` pairs the older vote to this rule exactly; the rule is still unread in its
    # current words, and the advisory says that instead.
    reworded = [e for e in unvetted_access if e.get("reworded_after_vote")]
    unvetted_access = [e for e in unvetted_access if not e.get("reworded_after_vote")]
    # Every row in `unseen_by_any_skeptic` is `unchecked` by construction (`grounding.py` filters
    # on `ElementCheck.unseen`, which IS `status == "unchecked"`), so this is the whole list. Named
    # rather than re-filtered: a filter that never removes anything reads as a narrowing.
    unchecked = stated
    kinds: dict[str, int] = {}
    for e in unchecked:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    # WHAT THE PASS DID NOT REACH — not "elements whose label the pass does not support". The old
    # line compared the author's `confidence` against the votes, which are two different facts about
    # two different things; the number it produced meant nothing and asked for `inferred` on rows
    # that were honestly read. What a reader needs from this leg is coverage: which elements no
    # skeptic looked at.
    advisory = ([f"{len(unchecked)} element(s) were never looked at by a skeptic "
                 f"({', '.join(f'{n} {k}' for k, n in sorted(kinds.items()))}). Run `coyomap "
                 f"grounding by-element --map <this map> --verdicts <…>` for the list — no "
                 f"`--worklist`, so it reads the LIVE map. It reports the same {len(unchecked)}; "
                 f"adding the pinned worklist answers a different question (what the skeptics saw) "
                 f"and gives a different number."]
                if unchecked else [])
    # THE ACCESS ROWS, SAID SEPARATELY AND FIRST. They are a subset of the count of unseen elements,
    # so this is not a second finding — it is the part of it that is worth acting on, named.
    # Who-may-do-what is the one thing a reader trusts a map for. Every list below takes
    # `item_lines`' shape: the count on a short first line, then one item per line. Readers that
    # match an advisory by substring (`advisory_disposition`) read the whole string, so the lines
    # change nothing there.
    if reworded:
        advisory.insert(0, (
            f"{len(reworded)} ACCESS rule(s) were re-worded after the vote: the skeptics voted on an "
            f"older wording at the same line, and no skeptic has read the current one:\n"
            + item_lines([f"{e['id']} ({e['label']}, {e['reworded_after_vote']['sites_voted']} of "
                          f"{e['reworded_after_vote']['sites']} site(s) voted under the older "
                          f"wording)" for e in reworded], 6, unit="rule(s)")
            + f"\nThese are among the {len(unchecked)} element(s) no skeptic looked at. Send the "
              f"current wording to a skeptic in a second wave (method.md; `coyomap audit <map> "
              f"--batches .coyomap/verify --since .coyomap/verify/worklist.json` cuts it), or say in "
              f"the grounding note why it needs none."))
    if unvetted_access:
        advisory.insert(0, (
            f"{len(unvetted_access)} ACCESS rule(s) were never challenged — no skeptic voted on "
            f"them under this anchor or any other:\n"
            + item_lines([f"{e['id']} ({e['label']})" for e in unvetted_access], 6,
                         unit="rule(s)")
            + f"\nThese are among the {len(unchecked)} element(s) no skeptic looked at, and are "
              f"called out because of what they claim. Send them to a skeptic, or say in the "
              f"grounding note why they could not be (a rule minted after the worklist was pinned "
              f"is the common honest reason)."))
    # DISCLOSURE, not a finding: the map is right to keep these claims, and the reader is entitled
    # to know a named second reader is why. It rides as an advisory so it reaches the report, the
    # gate block and the disposition table, where `_DISCLOSURE` files it as what it is.
    if appealed:
        advisory.insert(0, (
            f"{len(appealed)} refuted claim(s) are in this map because the CLOSER REJECTED the "
            f"refutation, not because nobody acted:\n"
            + item_lines([f"{a['claim'][:90]}"
                          + (f" — closer: {a['note'][:160]}" if a.get("note") else "")
                          for a in appealed], 4, unit="claim(s)")
            + "\nThis is a disclosure of what the refutation gate did NOT block on; the appeals are "
              "recorded in the map's `grounding.closer_rejected`."))
    # HEARD AND NOT SETTLED: a closer said `unsure`, or two appeals disagree. The claim stands on
    # the majority, which is not the same as settled, so it is said rather than blocked.
    unsettled = [d for d in dissent if d.get("closed")]
    if unsettled:
        advisory.insert(0, (
            f"{len(unsettled)} ACCESS claim(s) the majority CONFIRMED over a dissent the closer "
            f"could not settle:\n"
            + item_lines([f"{d['id']}: {d['claim'][:90]} (closer said {d['closed']})"
                          for d in unsettled], 4, unit="claim(s)")
            + "\nEach stands on the majority vote alone. Send it to a second closer, or correct "
              "the claim if the dissent is right."))
    if report_only:
        advisory.insert(0, (
            f"{len(report_only)} refuted walk-step or interface claim(s) are still in the map, "
            f"unchanged — reported, not blocking yet:\n"
            + item_lines([f"{s['claim'][:110]} (refuted by {s['refuted_by']}"
                          + (f", closer said {s['closed']}" if s.get("closed") else "") + ")"
                          for s in report_only], 6, unit="claim(s)")
            + "\nCorrect each step or drop it, as for any refutation; a claim a closer rejected "
              "is not here."))
    unheard = len(dissent) - len(unsettled)
    return Leg("grounding refutations", RAN if code in (0, 1) else FAILED,
               blocking=blocking, advisory=advisory,
               note=(f"{len(surviving)} refuted claim(s) still in the map"
                     + (f" and {len(report_only)} reported, not blocking" if report_only else "")
                     + ", "
                     + (f"{len(appealed)} settled on appeal, " if appealed else "")
                     + (f"{unheard} access dissent(s) no closer heard, " if unheard else "")
                     + f"{len(unchecked)} element(s) no skeptic looked at"))


#: Where a build keeps the skeptics' verdicts. `finalize` looks here when it was given none, so it
#: can say that a leg it CAN run was not asked for.
_VERDICTS_GLOB = "verify/verdicts-*.json"


def _unasked_verdicts(map_path: Path, verdicts: list[Path]) -> list[Path]:
    """Verdict files sitting beside the map that this run was not given.

    A build ran `finalize … --verdicts <30 files>`, then re-ran it with `--emit-gate-block` and NO
    `--verdicts` purely to emit the block. The second run overwrote the report, so what shipped and
    what the commit message quoted had only the shape-only anchor-drift leg — losing the
    verdict-based leg and, with it, the `challenged N of M worklist claim(s)` coverage line whose
    whole job is to stop "the gate did not run" reading as "the gate passed".

    This cannot be an INCOMPLETE: that verdict is for a leg that FAILED, and a leg nobody asked for
    did not fail. So it is reported as a leg in its own right — visible in the report, in the gate
    block and on stdout — which is the thing the silent version did not do."""
    if verdicts:
        return []
    return sorted(map_path.parent.glob(_VERDICTS_GLOB))


def _unasked_verdicts_leg(found: list[Path]) -> Leg:
    return Leg(name="anchor-drift (verdict-based)", status=RAN, blocking=[], advisory=[
        f"NOT RUN — {len(found)} verdict file(s) sit beside this map "
        f"({shown([p.name for p in found], 3)}) and this run was given none, so the verdict-based "
        f"anchor-drift leg and its coverage attestation are missing from this report. Re-run with "
        f"`--verdicts <file>` per file; `--verdicts` and `--emit-gate-block` combine in ONE "
        f"invocation."],
               note="the leg was skipped because no --verdicts was passed")


@dataclass
class BatchPairing:
    """What one look at a `verify/` directory found: every batch cut, and the ones nobody answered.

    A dataclass, not a tuple: both slots are `list[Path]`, so a positional return lets a caller
    unpack them the wrong way round and report "0 of 24 answered" as "24 of 0" with nothing able to
    tell. `assemble.FragmentLoad` carries the same scar, and `test_cli_contract` refuses new ones."""

    cut: list[Path]
    unanswered: list[Path]


def _unanswered_claim_batches(verify: Path) -> BatchPairing:
    """Claim batches under `verify` that no skeptic answered. ANSWERED IS A CLAIM, NOT A FILE NAME.

    The first version of this paired file names — `claims-«BATCH».json` against
    `verdicts-«BATCH»*.json` — and an adversarial review broke it in both directions on real maps:

    * **It absolved a batch nobody read.** The trailing `*` that absorbs a voter suffix absorbs
      digits too, so `verdicts-behaviour-10.json` answered `claims-behaviour-1.json`. Builds
      routinely cut two-digit batch counts (mcpolis 24, reminderrepo 16), and on a reminderrepo-
      shaped layout with only batch 1 undispatched the gate reported CLEAN over 39 unread claims —
      the exact failure it exists to catch.
    * **It accused a batch that WAS read.** `method/templates/skeptic-contract.md` is explicit that
      «BATCH» is the skeptic's own id and «CLAIMS» the file it reads, and that the two "are NOT the
      same thing": one skeptic may answer several small batches in one file. On the argus map
      `verdicts-smallmix.json` and `verdicts-description.json` answer 77 of 77 claims across seven
      batches, all seven of which the name match called unread — and the remedy the message offered
      ("delete them") would have destroyed seven warrant files whose verdicts were sitting beside
      them.

    Pairing on the claim strings fixes both, needs no new data, and cannot collide. It also closes
    the `touch` hole: an empty, truncated or non-JSON verdict file contributes no claims, where a
    name match counted it as a review.

    EVERY claim must be voted, not one of them, and the verdict must be NEWER than the batch. Both
    halves were found by review, both were exploitable, and they compound:

    * **Any-one.** `claims & answered` let a single voted claim clear a 40-claim batch. Demonstrated
      end to end: one hand-written verdict file of 24 rows, one claim lifted from each of
      mcpolis-rehearsal's unread batches, moved the whole map from BLOCKED to ADVISORIES with 925
      of 949 claims still unread. The docstring said no flag lifts this gate; a 24-line file did.
    * **Staleness.** `write_theme_batches` unlinks its own `claims-*` before each cut, and NOTHING
      anywhere unlinks `verdicts-*`. The directory is committed and long-lived, so a fresh build's
      batches were being answered by the PREVIOUS build's verdicts. Demonstrated on two real
      consecutive mcpolis builds: 43 old verdict files cleared 2 of 52 fresh batches with no skeptic
      dispatched at all — and that pair was a near-total rewrite where only 5 claim strings of 1791
      survived. A rebuild after a SMALL edit re-mints nearly identical claims, where the same hole
      opens all the way.

    Requiring every claim is safe here, and that is measured rather than hoped: two independent
    reviews found 0 non-verbatim echoes across 3,302 skeptic votes on five maps, every batch matching
    at either 100% or 0%. The pipeline enforces it — `skeptic-contract.md` says "character for
    character" and `challenge.py` already REFUSES a reworded claim — so this gate reuses the key the
    rest of the pipeline already runs on rather than inventing a looser one.

    KNOWN LIMIT, deliberate: the answered set is every verdict in the directory, with no way to tell
    which build wrote it. `verdicts-*` is never swept, so a rebuild's batches can be cleared by an
    earlier build's votes. Two non-fixes were tried and rejected. File mtime looks exact — the cut
    rewrites every `claims-*` file, so a real answer is newer — but mtime records checkout, not
    authorship: on the argus and mcpolis trees every claims file carries one `git` timestamp and
    18 of 18 and 38 of 38 verdict files read as older, so the rule mass-blocks maps whose every
    claim was answered. A run token in the payload would be exact and is a format change across the
    contract, the templates and every skeptic.

    What is left after requiring EVERY claim is small, and is provenance rather than substance. On
    the two real consecutive mcpolis builds, 5 claim strings of 1791 survived, and under any-one
    those 5 cleared 2 whole batches; under all-claims they clear nothing, because a batch needs all
    of its claims voted. The case that still passes is a batch every claim of which is character-
    identical to one a skeptic already voted on — the same sentence about the same code, read by
    somebody. Which BUILD read it is `grounding write`'s question: it pins a worklist per build and
    records the counts. This leg's question is whether anyone did.

    A batch whose own file cannot be read, or that holds no claims, is SKIPPED rather than accused.
    Nothing about it says a skeptic was or was not called. Note that no other gate covers it either:
    `validate` never reads `verify/claims-*.json`, so emptying a batch's `claims` array silences
    this leg with nothing else objecting. Deleting the batch is the sanctioned remedy and costs
    nothing, so there is little to gain by corrupting one instead."""
    if not verify.is_dir():
        return BatchPairing(cut=[], unanswered=[])
    batches = sorted(verify.glob("claims-*.json"))
    answered = voted_claims(verdict_files(verify))
    unanswered = [b for b in batches
                  if (claims := set(batch_claims(b))) and (claims - answered)]
    return BatchPairing(cut=batches, unanswered=unanswered)


def _unanswered_prose_batches(verify: Path) -> BatchPairing:
    """Prose batches with no verdict file beside them.

    Prose batches carry reader-facing FIELDS, not claims, so there is no claim text to pair on and
    this one stays a file pair. What it does not keep is the collision: the candidates are the exact
    name and a `-`-separated suffix, never `verdicts-<stem>*`, so `verdicts-prose-10.json` no longer
    answers `prose-1.json`. The coyomap map itself runs `prose-1` … `prose-10`, so that was live
    surface. A zero-byte file does not count, which is the cheap half of the `touch` hole."""
    if not verify.is_dir():
        return BatchPairing(cut=[], unanswered=[])
    batches = sorted(verify.glob("prose-*.json"))
    unanswered: list[Path] = []
    for b in batches:
        found = [verify / f"verdicts-{b.stem}.json", *verify.glob(f"verdicts-{b.stem}-*.json")]
        if not any(f.is_file() and f.stat().st_size > 0 for f in found):
            unanswered.append(b)
    return BatchPairing(cut=batches, unanswered=unanswered)


def _undispatched_prose_leg(map_path: Path) -> Leg | None:
    """Prose batches written and sent to nobody.

    `audit --prose-batches` writes a numbered batch per chunk of reader-facing prose, for a fan-out
    of prose reviewers. Writing them is one command; DISPATCHING them is the lead's next act, and
    nothing observed whether it happened. Four builds in a row wrote batches and dispatched none:
    the 2026-09-02 mcpolis build produced 459 prose fields across 12 batches that no agent ever
    read, and the map shipped with the prose gate's own count as its only evidence.

    A file pair, so it is cheap and it cannot be wrong: batches on disk, no `verdicts-prose-*`
    beside them. Returns None when there is nothing to say, so a build that does not use the tier
    pays no line.

    THE FILENAME IS A CONVENTION, AND IT HAD TO BE LANDED FIRST. This check shipped keyed on
    `verdicts-prose-*.json` while nothing in the method asked anyone to write that name — so it was
    an advisory no build could ever satisfy except by deleting its own batches, and this repo's own
    backlog had already recorded exactly that objection. `method.md` now names the file where it
    tells the lead to dispatch the read fan-out. Without that sentence, delete this leg rather than
    keeping an unsatisfiable one."""
    verify = map_path.parent / "verify"
    found = _unanswered_prose_batches(verify)
    batches, unpaired = found.cut, found.unanswered
    if not batches or not unpaired:
        return None
    return Leg(name="prose review", status=RAN, blocking=[], advisory=[
        f"{len(unpaired)} of {len(batches)} prose batch(es) sit in {verify} with NO "
        f"`verdicts-<batch>.json` beside them — they were written and dispatched to nobody. This is "
        f"the fourth build running: one produced 459 reader-facing fields across 12 batches that no "
        f"agent read. Dispatch them, or delete the batches so the next reader is not told a review "
        f"happened."],
        note=f"{len(batches)} batch(es) written, {len(batches) - len(unpaired)} dispatched")


def _undispatched_claims_leg(map_path: Path) -> Leg | None:
    """Claim batches written and sent to nobody. BLOCKING.

    `audit --batches` cuts one claims file per theme for the Phase-4 skeptics. Cutting them is one
    command; DISPATCHING them is the lead's next act, and until this leg nothing refused a map whose
    skeptics were never called. The 2026-09-08 mcpolis build cut 24 behaviour batches holding 949
    claims — every flow title and every step phrase, the half of the map a reader actually reads —
    and dispatched none of them. The map shipped ADVISORIES, and one of those unchallenged steps
    said an expired sign-in warns the team's ADMIN when the code warns the affected USER: a
    two-armed `if` recorded as one arm, on the line the step itself anchors.

    BLOCKING, where the prose leg beside it is advisory, and the difference is whether a remedy
    exists that costs nothing. It does, and it is in the message: dispatch the batches, or DELETE
    them. A build that deletes them loses no work and states the truth, because a batch file sitting
    beside a map says a review happened. That is why this one has no recorded-exception route and
    does not need one — every other blocking finding in this command is a contradiction the lead
    must reason about, and this is a file that should not be there.

    The no-escape argument only holds while the accusation is TRUE, and the first version's was not:
    pairing file names, it blocked argus over seven batches whose 77 claims were all answered, and
    "delete them" there would have deleted warrant files. `finalize.py`'s access-baseline leg is
    advisory for exactly that reason — see "FAILED BOTH REFERENCE MAPS" — and this leg would have
    earned the same downgrade. Pairing on claim text instead, the six local maps split 3 clean
    (coyomap, fresque, argus) and 3 blocked (mcpolis, its rehearsal copy, reminderrepo), and all
    three blocks are real: 949 and 304 claims respectively appear in no verdict file at all.

    It is deliberately a SECOND gate over the same fact. `grounding write` already refuses a
    worklist claim with no verdict, and `--partial` lifts that refusal by design, for a pass that
    was knowingly cut short. The mcpolis build took that route and shipped. A partial pass is a
    legitimate thing to record; a batch nobody answered is not, and no flag here lifts it."""
    verify = map_path.parent / "verify"
    found = _unanswered_claim_batches(verify)
    batches, unpaired = found.cut, found.unanswered
    if not batches or not unpaired:
        return None
    themes = sorted({batch_theme(b) for b in unpaired})
    voted = voted_claims(verdict_files(verify))
    unread = sum(len(set(batch_claims(b)) - voted) for b in unpaired)
    return Leg(name="skeptic dispatch", status=RAN, advisory=[], blocking=[
        f"{len(unpaired)} of {len(batches)} claim batch(es) in {verify} hold {unread} claim(s) "
        f"that no verdict file in that directory votes on: {', '.join(themes)}. Every one of those "
        f"is in the map unchecked. Dispatch those batches to skeptics, or delete them — a batch "
        f"file beside a map says a review happened. WHICH file answers a batch does not matter "
        f"(one skeptic may answer several); answering ALL of its claims does, so a verdict file "
        f"covering one claim in forty clears nothing, and nor does `grounding write --partial`."],
        note=f"{len(batches)} batch(es) cut, {len(batches) - len(unpaired)} answered")


def _balance_leg(map_path: Path) -> Leg:
    """Phase 3.5 left a trace, or it did not happen.

    `method.md` puts a `coyomap balance` pass after the trace and says to reconcile each finding.
    Nothing observed it, so a skipped Phase 3.5 and a passed one read the same: one build ran
    `balance` three times, the next ran it ZERO times, and the only reason nobody noticed is that
    `validate` happened to emit no balance warning. Running it here means the report always says
    what the grouping looks like against the real graph.

    INFORMATIONAL, never advisory and never blocking. `method.md` is explicit that "balance never
    gates and only ever re-groups" — grouping is a free, view-only choice — so a balance finding
    must not move this command's verdict. The leg exists to record the fact, not to add a gate.
    """
    code, out, err = _run_leg("balance", [str(map_path)])
    text = (out or "") + (err or "")
    findings = [ln.strip()[2:] for ln in text.splitlines() if ln.startswith("  - ")]
    if code not in (0, 1):
        return Leg("balance (informational)", FAILED,
                   note="balance could not run, so Phase 3.5 has no trace in this report")
    return Leg("balance (informational)", RAN,
               note=(f"{len(findings)} balance finding(s) — apply a Drilling-deeper operation, or "
                     f"record a why under 'Balance exceptions'; this never gates"
                     if findings else "no balance findings — every diagram reads at target density")
                    + " (informational: grouping is a view-only choice, method.md)")


def _findings_leg(map_path: Path) -> Leg:
    """What the agents filed about the PRODUCT, counted, so the record of the run says it.

    INFORMATIONAL, never advisory and never blocking, like the balance leg. A finding is an agent's
    own words about the code, which no tool checked; it is the operator's to hear, and a map whose
    agents noticed a risk in the product is not a wrong map. The leg exists so the finalize report
    and the commit's gate block carry the count, read from the map's own folder: the findings
    files themselves never ship.

    Read, never collected: `coyomap findings collect` is the one writer of the list, and a run that
    wrote it here would move the "since the last collect" count the lead reads at its barriers.
    Read BESIDE THE MAP, as the budget leg reads its `verify/`: an archived map's findings moved
    with it, and a retrospective's `--no-write` read of that map counts those, not today's."""
    filed = findings.load_folder(findings.beside_map(map_path))
    return Leg("agent findings (informational)", RAN,
               note=findings.reader_line(filed)
                    + (" (informational: a finding never blocks the map; tell the operator about "
                       "each `risk`, and `coyomap findings collect` lists them all)"
                       if filed.findings else " (informational: a finding never blocks the map)"))


def _access_baseline_leg(map_path: Path, baseline: Path,
                         lead_transcript: Path | None = None) -> Leg:
    """Files that held ACCESS enforcement in a previous map and are named by no access rule now.

    A from-scratch rebuild is deliberately blind to its predecessor, and that independence is the
    point. The cost is that a security claim can vanish between two maps of unchanged code with
    nothing in the build noticing: on the 2026-08-20 argus pair the access-rule STATEMENT count held
    at 21 -> 21 — so `compare`'s hard gate passed — while `adapters/auth_google.py` lost its claim
    entirely. That file verifies the Google ID token's signature, issuer and audience; the previous
    map said so as access rule BR21, and none of the new map's 61 rules mentions a signature, an
    issuer or an audience.

    `coyomap-eval compare` prints this, and printing it there is too late twice over: it is a
    developer-only command, and it runs at retro time. Here it runs AFTER the map is written — so
    reading the baseline cannot contaminate the rebuild — and BEFORE the commit, which is the last
    moment anybody looks.

    ADVISORY, never blocking, and FILES rather than statements or lines. Two independent LLM builds
    legitimately reword and re-anchor; a file that lost its coverage altogether is the one signal
    that survives both.

    EACH FILE WITH ITS LINES, AND NOTHING THE OLD MAP SAID. On the 2026-09-30 mcpolis build a
    bare list of 17 paths was answered without one file being opened, so the leg began printing the
    old claim each file held. On the 2026-10-08 build that text arrived after the last fact-check
    wave: the lead wrote three new rules from three printed old ones (text similarity 0.80 to 0.87),
    and their site claims shipped with no vote. The line numbers are the question now; the code at
    them is the answer; a rule written from it ships only after a late wave votes on its sites,
    which `_late_claims_leg` holds. And because the record is the escape, the lead's own transcript
    is read, when there is one, for the excused paths nobody opened."""
    from coyomap.assemble import load_map_or_fragment
    try:
        base = load_claims(baseline)
        m, _present = load_map_or_fragment(map_path)
    except Exception as exc:                       # noqa: BLE001 — any unreadable baseline is one case
        return Leg("access baseline", FAILED,
                   note=f"--access-baseline {baseline} could not be read ({exc}), so nothing says "
                        f"whether an auth claim was dropped")
    all_lost = lost_files(base, m)
    # The ESCAPE, actually wired: a path recorded as deliberate drops out of the FINDING. Without
    # this read the advisory asked for a record, the operator wrote one, and the next run said
    # exactly the same thing — the shape this project calls a promise the tool cannot keep.
    #
    # An excused file drops out of the finding and NOT out of the count. A recorded gap is still a
    # gap, and every sibling escape in this toolchain says so in the same breath as it forgives —
    # `Unclaimed surfaces` prints "counted as CLAIMED because of it". This leg used to subtract the
    # excused paths and then, finding nothing left, assert "every one of the N file(s) … is still
    # named by an access rule". On the 2026-08-29 mcpolis build nine files were excused, that
    # sentence was emitted, and it went into the commit message: the escape did not disclose the
    # gap, it erased it.
    excused = records.recorded_keys(m, ACCESS_BASELINE_EXCEPTIONS_HEADING)
    lost = [f for f in all_lost if f not in excused]
    excused_here = [f for f in all_lost if f in excused]
    advisory: list[str] = []
    note: str | None = None
    if excused_here:
        advisory += _unread_excuses(excused_here, base, lead_transcript)
        if lead_transcript is None:
            note = (f"{len(excused_here)} excused path(s); no lead transcript was found, so "
                    f"whether the lead opened them is not checked (pass --lead-transcript)")
    excused_note = (
        f"; {len(excused_here)} of {len(base)} more are named by no access rule and are recorded as "
        f"deliberate under '{ACCESS_BASELINE_EXCEPTIONS_HEADING}'" if excused_here else "")
    if not lost:
        covered = len(base) - len(excused_here)
        if not excused_here:
            return Leg("access baseline", RAN,
                       note=f"every one of {len(base)} file(s) that held access enforcement in "
                            f"{baseline.name} is still named by an access rule")
        return Leg("access baseline", RAN, note=note, advisory=[
            f"DISCLOSURE, not a request: {len(excused_here)} of {len(base)} file(s) that held "
            f"ACCESS enforcement in {baseline.name} are excused under "
            f"'{ACCESS_BASELINE_EXCEPTIONS_HEADING}':\n"
            + item_lines(excused_here, 8, unit="file(s)")
            + f"\nNo access rule in this map names them; they are recorded as deliberate, and the "
              f"other {covered} are still named by an access rule. There is nothing to record here "
              f"and recording more would raise this number; this disclosure stays so a reader can "
              f"see what the escape forgave. It clears when the rules cover those files again, or "
              f"when the records are deleted. A recorded gap is still a gap — re-read one by "
              f"validating a copy with its line removed.", *advisory])
    # Every file, never a `+N more`: this list IS the reading list, and a build that ran the leg
    # would have seen 8 of its 19 names. Each with its lines, on a line of its own (`item_lines`),
    # and NOTHING the old map said there (`where_lines`).
    return Leg("access baseline", RAN, note=note, advisory=[
        f"{len(lost)} of {len(base)} file(s) that held ACCESS enforcement in "
        f"{baseline.parent.name}/{baseline.name} are named by NO access rule in this map:\n"
        + item_lines([where_lines(f, base[f]) for f in lost], None)
        + f"\nEach file is listed with the lines that held access there, and never with what the "
          f"old map said about them: this runs after the last fact-check wave, so copied text would "
          f"ship unchecked. The code of these {len(lost)} file(s) may be unchanged — check each one "
          f"before shipping: open the file at those lines, then write a rule from the code you "
          f"read, which ships only after a late wave votes on its sites (method.md, the late wave), "
          f"or record why no rule belongs there. A statement count can hold steady while a claim "
          f"disappears, so this is not visible in `auth-surfaces-no-drop`. Record '<path>: <why>' "
          f"under an '{ACCESS_BASELINE_EXCEPTIONS_HEADING}' extras heading for each one that is "
          f"deliberate — the why says what the code at those lines does now{excused_note}.",
        *advisory])


def late_claim_key(anchor: str | None, claim: str) -> str:
    """The key a late claim is recorded under: its `path:line` anchor, or the whole claim when
    the map gives it no anchor."""
    return (anchor or "").strip() or claim.strip()


def _late_claims_leg(map_path: Path) -> Leg | None:
    """Claims the map makes that no fact-check wave was given and no skeptic voted on. BLOCKING.

    A wave's cut pins what its skeptics are given, and `audit --since` cuts a second wave over the
    claims written after the first. Nothing stopped a claim written after the LAST wave. On the
    2026-10-08 mcpolis build the access-baseline advisory, which runs at the gate, printed three of
    the old map's rules in full; the lead wrote six rules after the second wave, three of them
    near word for word, and their 13 site claims shipped with only a sentence in the grounding
    note. Three skeptics read them afterwards in about 1.5 minutes each: 2 of the 6 rules were
    overstated, against about 99 % holding for the voted rest of that map.

    BLOCKING, with an escape that names each claim. The remedy costs one small wave (method.md,
    the late wave). A claim that cannot get one is recorded `<path:line>: <why>` under
    `LATE_CLAIMS_HEADING`, one line per anchor, and the leg then DISCLOSES it rather than forgets
    it. `grounding.note` is not an escape here: it is free prose, and it is what the 2026-10-08
    build used. None when the map has no pinned worklist beside it, so there was no wave."""
    from coyomap.assemble import load_map_or_fragment
    try:
        m, _present = load_map_or_fragment(map_path)
    except Exception:                              # noqa: BLE001 — the validate leg reports it
        return None
    late = unvoted_after_the_last_wave(m, map_path.parent / "verify")
    if late is None:
        return None
    if not late:
        return Leg("late claims", RAN,
                   note="every claim the map makes was given to a fact-check wave or voted on")
    recorded = records.lines(m, LATE_CLAIMS_HEADING)
    excused = [w for w in late if records.records_key(recorded, late_claim_key(w.anchor, w.claim))]
    unexcused = [w for w in late if w not in excused]

    def row(w: WorkItem) -> str:
        ids = ", ".join(w.elements)
        return (f"{late_claim_key(w.anchor, w.claim)} ({w.theme}"
                + (f", {ids}" if ids else "") + ")")

    disclosure = ([f"DISCLOSURE, not a request: {len(excused)} claim(s) written after the last "
                   f"fact-check wave ship with no vote, recorded under '{LATE_CLAIMS_HEADING}':\n"
                   + item_lines([row(w) for w in excused], None)
                   + "\nA recorded claim is still unchecked. This clears when a late wave votes "
                     "on it, or when its line is removed and it is voted."] if excused else [])
    if not unexcused:
        return Leg("late claims", RAN, advisory=disclosure,
                   note=f"{len(late)} claim(s) with no vote, each recorded")
    return Leg("late claims", RAN, advisory=disclosure, blocking=[
        f"{len(unexcused)} claim(s) the map makes were written after the last fact-check wave and "
        f"have no vote:\n"
        + item_lines([row(w) for w in unexcused], None)
        + f"\nA claim no skeptic read ships unchecked: on one build, 2 of 6 rules restored this "
          f"way were overstated. Cut one more small wave over them (method.md, the late wave): "
          f"`coyomap audit <map> --batches .coyomap/verify --since .coyomap/verify/worklist.json "
          f"--prefix {LATE_WAVE_PREFIX}`, then `coyomap contract skeptic --from-batches "
          f".coyomap/verify --prefix {LATE_WAVE_PREFIX} --votes <theme>=3` for each theme it cut, "
          f"dispatch, `coyomap grounding lint --plan <briefs>/wave-plan.json`, a closer for its "
          f"refutations, then `ship` again. Or, for a claim that cannot get a vote, record "
          f"'<path:line>: <why>' under a '{LATE_CLAIMS_HEADING}' extras heading, keyed by the "
          f"anchor listed above. `grounding.note` does not clear this."],
        note=f"{len(late)} claim(s) with no vote, {len(excused)} of them recorded")


#: The start of the advisory that counts excused access paths the lead never opened. Named so the
#: disposition table can file it: no record answers it, only opening the file does.
UNREAD_EXCUSES = "excused without being opened"


def _unread_excuses(excused: list[str], base: dict[str, list[AccessClaim]],
                    lead_transcript: Path | None) -> list[str]:
    """One advisory naming the excused paths the lead's transcript never shows it opening, or [].

    `dispatch.md` says to record a drop "after reading the file". On the 2026-09-30 mcpolis build
    the lead recorded 11 and opened none, and 5 of the 11 reasons answered a different claim. The
    record IS the escape here, so a record cannot answer this; only opening the file does."""
    if lead_transcript is None:
        return []
    try:
        never = unopened(excused, [lead_transcript])
    except OSError as exc:
        return [f"the lead's transcript ({lead_transcript.name}) could not be read ({exc}), so "
                f"whether the {len(excused)} excused access path(s) were opened is not known. "
                f"Pass --lead-transcript with a readable copy."]
    if not never:
        return []
    # The transcript's name goes after the list, so the count line stays short whatever the session
    # id is called.
    return [f"{len(never)} of {len(excused)} access path(s) {UNREAD_EXCUSES}: no tool call in the "
            f"lead's transcript reads them:\n"
            + item_lines([where_lines(f, base[f]) for f in never], None)
            + f"\nThe transcript read is {lead_transcript.name}. A drop is recorded after reading "
              f"the file (dispatch.md). Open each one, then keep its line, correct its why, or "
              f"remove it and restore the rule."]


#: The 'Balance exceptions' keys the component-budget leg reads: this one, and the `granularity`
#: literal exactly as validate reads it (`balance_lib.LITERAL_LINE`). Validate holds the component
#: count to E and this leg holds it to the summed budgets: one fact, the map's size, banded two
#: ways, so ONE `granularity:` line naming both counts answers both checks. Either key, the line
#: must NAME the shipped and the budgeted count, so a record written against another size stops
#: answering once the map moves, and a line naming E or the band answers validate and never this.
BUDGET_KEY = "component-budget"


def budget_record(m: "ProjectModel", shipped: int, budgeted: int) -> str:
    """The 'Balance exceptions' line that answers the budget leg for THESE counts, or ""."""
    # THE COUNTS AS THE ADVISORY WRITES THEM, never two numbers anywhere: a line holding the band's
    # bounds, E or a date answered it too, whatever it said about the size.
    said = re.compile(rf"(?<![\w.]){shipped} shipped of {budgeted} budgeted(?![\w.])")
    for line in records.lines(m, "Balance exceptions"):
        # `granularity` read by validate's own reader, so a line this leg takes is one validate
        # takes too. Reading only its own key, the leg shipped UNRECORDED on the 2026-10-07 mcpolis
        # build beside the `granularity:` line that answered validate.
        literal = balance_lib.LITERAL_LINE.match(line)
        keyed = (line.lower().startswith(BUDGET_KEY)
                 or (literal is not None and literal.group(1) == "granularity"))
        if keyed and said.search(line):
            return line
    return ""


def _budget_leg(map_path: Path, repo: Path) -> Leg | None:
    """The sum of the component budgets the harvest briefs were handed, against what shipped and
    against the code-derived expectation E. None when no budgets were recorded (a build that did
    not fill its briefs with the tool), so the leg is absent rather than silently clean.

    `lint-fragment --expect` holds one slice to its own budget; nothing summed them. 60 budgeted,
    114 shipped, every slice over and 7 of 10 past their own band, and the whole-map reading
    arrived ~450 turns later in a `Balance exceptions` record. Advisory: a budget is an aim, and a
    map that shipped twice its aim may be right — but somebody should have said so at assemble.
    """
    budgets_path = resolve_map_path(map_path).parent / "verify" / BUDGETS_FILE
    if not budgets_path.is_file():
        return None
    # ADVISORY on every path, including a file this leg cannot read: a budget is an aim, and a
    # broken telemetry file must never turn a clean map into INCOMPLETE (the review's first version
    # of this leg did exactly that, and crashed on a list where it expected a dict).
    try:
        doc = json.loads(budgets_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return Leg("component budget", RAN, note=f"{budgets_path} could not be read ({e})",
                   advisory=[f"{budgets_path} is not readable JSON; the harvest budgets cannot be "
                             f"summed. Fix or delete it — it is build telemetry, not map content"])
    harvest = doc.get("harvest") if isinstance(doc, dict) else None
    if not isinstance(harvest, dict) or not harvest:
        return Leg("component budget", RAN, note=f"{budgets_path} records no harvest budgets",
                   advisory=[] if isinstance(harvest, dict) else [
                       f"{budgets_path} has no `harvest` object; the budgets cannot be summed"])
    budgets: dict[str, int] = {}
    unnumbered: list[str] = []
    for agent_id, value in harvest.items():
        if isinstance(value, int) and not isinstance(value, bool):
            budgets[str(agent_id)] = value
        else:
            unnumbered.append(str(agent_id))
    try:
        m = load_model(resolve_map_path(map_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, ModelError) as e:
        return Leg("component budget", RAN, note=f"could not re-read {map_path}: {e}",
                   advisory=[f"the map could not be re-read to count its components: {e}"])
    shipped = len(m.components)
    total = sum(budgets.values())
    uncounted = (f", {len(unnumbered)} brief(s) with no numeric budget ({shown(unnumbered, 6)})"
                 if unnumbered else "")
    e_note = ""
    try:
        e = expected_components(repo).expected
        if e:
            e_note = f", code-derived expectation E {e}"
    except (OSError, ValueError):
        pass
    low, high = granularity_band(total)      # the same ±40 % band each slice is held to
    advisory: list[str] = []
    if total and not low <= shipped <= high:
        recorded = budget_record(m, shipped, total)
        if recorded:
            advisory.append(f"DISCLOSURE, not a request: {shipped} component(s) shipped against "
                            f"{total} budgeted (band {low}-{high}{e_note}), recorded as deliberate "
                            f"under 'Balance exceptions': {recorded}")
        else:
            advisory.append(f"{shipped} component(s) shipped against {total} budgeted across "
                            f"{len(budgets)} harvest brief(s) (band {low}-{high}{e_note}{uncounted}). "
                            f"Every slice can be inside its own band while the sum is not; record "
                            f"'granularity: {shipped} shipped of {total} budgeted, because <why the "
                            f"map is this size>' under 'Balance exceptions', in place of any other "
                            f"`granularity:` line there, since that one line also answers "
                            f"validate's component-count advisory; or re-cut the slices.")
    return Leg("component budget", RAN, advisory=advisory,
               note=f"{shipped} shipped / {total} budgeted across {len(budgets)} brief(s), "
                    f"band {low}-{high}{e_note}{uncounted}")


def build_report(map_path: Path, repo: Path, verdicts: list[Path],
                 access_baseline: Path | None = None,
                 lead_transcript: Path | None = None) -> FinalizeReport:
    unasked = _unasked_verdicts(map_path, verdicts)
    # The audit runs at the tier the grounding record was written at, so the gate block counts
    # ONE surface and the digest is compared with the surface it hashed.
    behavioural = _record_tier(map_path) is True
    legs = [
        _validate_leg(map_path, repo),
        _audit_leg(map_path, verdicts, behavioural=behavioural),
        _drift_leg(map_path, repo, []),
        *([_drift_leg(map_path, repo, verdicts, behavioural=behavioural)] if verdicts else []),
        *([_refutations_leg(map_path, verdicts)] if verdicts else []),
        *([_unasked_verdicts_leg(unasked)] if unasked else []),
        *([_access_baseline_leg(map_path, access_baseline, lead_transcript)]
          if access_baseline else []),
        *([leg for leg in (_budget_leg(map_path, repo),) if leg is not None]),
        *([leg for leg in (_undispatched_prose_leg(map_path),) if leg is not None]),
        *([leg for leg in (_undispatched_claims_leg(map_path),) if leg is not None]),
        *([leg for leg in (_late_claims_leg(map_path),) if leg is not None]),
        _credential_leg(map_path),
        _balance_leg(map_path),
        _findings_leg(map_path),
    ]
    blocking = sum(len(l.blocking) for l in legs)
    advisory = sum(len(l.advisory) for l in legs)
    failed = [l for l in legs if l.status == FAILED]
    # ORDER MATTERS, and CLEAN is the narrowest case on purpose: a leg that FAILED means this run does
    # not know whether the map is clean, so it must never say that it is.
    if blocking:
        verdict = "BLOCKED"
    elif failed:
        verdict = "INCOMPLETE"
    elif advisory:
        verdict = "ADVISORIES"
    else:
        verdict = "CLEAN"
    # NO VALUE LEAVES THROUGH THE REPORT. A leg quotes skeptics' and closers' notes, and a note can
    # hold a key: the review put one in a dissent note, and the report printed it while the
    # credential leg blocked on the very same file. Every string every writer reads is here.
    for leg in legs:
        leg.blocking = [redact(b) for b in leg.blocking]
        leg.advisory = [redact(a) for a in leg.advisory]
        leg.note = redact(leg.note) if leg.note else leg.note
    return FinalizeReport(map_path=str(map_path),
                          map_sha256=hashlib.sha256(map_path.read_bytes()).hexdigest(),
                          legs=legs, verdict=verdict,
                          advisory_total=advisory, blocking_total=blocking)


def format_report(r: FinalizeReport) -> str:
    out: list[str] = [f"# coyomap finalize — {r.map_path}", ""]
    out.append(f"**Verdict: {r.verdict}** — {r.blocking_total} blocking, "
               f"{r.advisory_total} advisory.")
    out.append("")
    out.append(f"Map sha256 `{r.map_sha256}` — if this does not match the map you are looking at, this "
               f"report is STALE and describes a different file.")
    unran = [l for l in r.legs if l.status != RAN]
    if unran:
        out.append("")
        out.append("**Checks that did not run** — their silence is not a pass:")
        for l in unran:
            out.append(f"- {l.name} ({l.status}): {l.note}")
    out.append("")
    out.append("An ADVISORY is not a pass. Each one is either fixed or recorded under the extras "
               "heading its message names; \"gates clean\" may only be claimed when this file says "
               "CLEAN.")
    out.append("")
    disp = advisory_disposition(Path(r.map_path), r)
    if disp:
        counts: dict[str, int] = {}
        for d, _h, _a in disp:
            counts[d] = counts.get(d, 0) + 1
        out.append("## Advisory disposition")
        out.append("Each advisory, against what the map actually records. "
                   + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
        out.append("")
        for d, h, a in disp:
            tag = f"**{d}**" if d in ("UNRECORDED", "UNSURE", "UNANSWERED") else d
            out.append(f"- {tag}{f' [{h}]' if h else ''} — {a}")
        out.append("")
        # The UNRECORDED rows are the ones asking to be written, so name the writer beside them.
        # See the same footer in `validate`: sixty advisory strings name a heading and none names
        # the command, and a measured build hand-appended every record instead.
        # `coyomap record` appends under an EXTRAS HEADING; it cannot write a map field. Naming it
        # beside an UNANSWERED row would point the author at a command that cannot fix it — the same
        # unreachable-remedy shape this footer exists to prevent, committed by the footer.
        if any(d == "UNANSWERED" for d, _, _ in disp):
            out.append("An **UNANSWERED** row is a map FIELD, not a recorded line: edit the field the "
                       "row names (`grounding.note`) so it states the count the advisory is about. "
                       "`coyomap record` cannot write it — that command appends under an extras "
                       "heading.")
            out.append("")
        if any(d in ("UNRECORDED", "UNSURE") for d, _, _ in disp):
            out.append("Write the missing records with `coyomap record --map <the FRAGMENT that "
                       "owns extras> --heading \"<heading>\" --line \"<key>: <why>\"` — it "
                       "shape-checks each line and tries a free-text key against what `validate` "
                       "reports, so a line its heading cannot read, or that changes nothing, is "
                       "refused rather than stored. Re-run `finalize` after, never before: records written "
                       "against an earlier run's findings go stale the moment anything is fixed.")
            out.append("")
    for leg in r.legs:
        out.append(f"## {leg.name}")
        if not leg.ran:
            out.append(f"DID NOT RUN ({leg.status}) — {leg.note}")
            out.append("")
            continue
        if leg.note:
            out.append(f"_{leg.note}_")
        for b in leg.blocking:
            out.append(f"- BLOCKING: {b}")
        for a in leg.advisory:
            out.append(f"- advisory: {a}")
        if not leg.blocking and not leg.advisory:
            out.append("- nothing found")
        out.append("")
    return "\n".join(out)


def _shape_line(map_path: Path) -> str:
    """The map's own counts, for the commit message, read from the map the gate block hashes.

    A live commit claimed "416 backbone edges … 33 flows/sub-flows" for a map holding 365 and 36.
    Neither number was invented: both were true earlier in the build, and `fix dedup-edge` dropped
    49 duplicate occurrences after they were written down. Hand-copied shape numbers describe
    whatever state the author last looked at, and the commit message is the artifact a future
    reader trusts most, so these are generated from the same file the sha is taken over."""
    try:
        from coyomap.model import load_model
        m = load_model(resolve_map_path(map_path).read_text(encoding="utf-8"))
    except Exception as e:
        # NOT a silent None. A gate block that quietly omits the shape sends the author straight
        # back to hand-writing the numbers, which is the defect this line exists to remove.
        return f"Shape: UNAVAILABLE — could not re-read {map_path}: {e}"
    flows = len(m.flows) + len(m.subflows)
    return (f"Shape: {len(m.components)} components in {len(m.subsystems)} subsystems, "
            f"{len(m.entities)} entities in {len(m.subdomains)} subdomains, {len(m.deps)} deps, "
            f"{len(m.use_cases)} use cases, {len(m.edges)} edges, {flows} flows/sub-flows, "
            f"{len(m.entry_points)} entry points, {len(m.rules)} business rules in "
            f"{len(m.blocks)} blocks"
            # The access surface is part of the shape a commit states. It was invisible here for the
            # same reason it was invisible in validate's inventory: the only mention of auth was
            # gated on `security[]`, which the fold empties.
            + (f" ({len(access_rules(m))} access)" if access_rules(m) else "")
            + (f", {len(m.security)} LEGACY security rows" if m.security else "") + ".")


def _grounding_line(map_path: Path) -> str:
    """The map's grounding counts, so the commit cannot quote a friendlier number than the gate.

    A live commit said "all 446 L2 claims challenged" while the gate block it was pasted beside
    said `challenged 440 of 444`. Both came out of the same build minutes apart; the one a reader
    sees forever was the flattering one. Emitting it here removes the choice.

    NAMING THE SURFACE is the second half of that, and it was missing. This line used to say "from
    the map" and quote the PINNED counts, so one commit carries "209 of 209 claim(s) challenged"
    four lines below this same report's "challenged 199 of 209 worklist claim(s)". Both were true —
    209 counts the worklist the skeptics were given, 199 counts the claims the shipped map actually
    carries — and nothing said they measure different sets. The pinned figure stays first, because
    it is what the skeptics did; the live figure follows whenever it disagrees."""
    try:
        from coyomap.model import load_model
        g = load_model(resolve_map_path(map_path).read_text(encoding="utf-8")).grounding
    except Exception as e:
        return f"Grounding: UNAVAILABLE — could not re-read {map_path}: {e}"
    if g is None:
        return "Grounding: NO RECORD — nothing in this map says what was challenged."
    line = (f"Grounding (pinned worklist): {g.claims_challenged} of {g.claims_total} claim(s) "
            f"challenged — {g.claims_confirmed} confirmed, {g.claims_refuted} refuted, "
            f"{g.claims_unverifiable} unverifiable.")
    # THE APPEAL, in the sentence the commit quotes. These counts are why a map legitimately keeps a
    # claim its own skeptics refuted, and a commit that states the five counts and not these three
    # reads as a map with unfixed refutations.
    heard = g.closer_upheld + g.closer_rejected + g.closer_unsure
    if heard:
        # APPEAL ROWS, said as rows. Called refutations, one `uphold` and one `reject` on ONE claim
        # read as "2 refutations went to appeal, 1 rejected, so the map keeps the claim" — a
        # settlement asserted at the moment the gate is refusing it, and a number `settled_on_appeal`
        # correctly lists as 0.
        line += (f"\nGrounding (closer): {heard} appeal row(s) — {g.closer_rejected} reject, "
                 f"{g.closer_upheld} uphold, {g.closer_unsure} unsure. A rejection is why a map may "
                 f"legitimately keep a claim its own skeptics refuted; an appeal is not a vote and "
                 f"moves none of the counts above."
                 + (f" {g.closer_disputed} claim(s) drew appeals that DISAGREE — those settle "
                    f"nothing, and the refutation still stands." if g.closer_disputed else ""))
    live_total = g.claims_total - g.claims_superseded + g.claims_added_since
    if g.claims_live_challenged and g.claims_live_challenged < live_total:
        unvoted = live_total - g.claims_live_challenged
        line += (f"\nGrounding (shipped map): {g.claims_live_challenged} of {live_total} claim(s) "
                 f"have a verdict — {unvoted} do not. "
                 + unvoted_reason(unvoted, g.claims_added_since))
    elif not g.claims_live_challenged and g.claims_added_since:
        line += (f"\nGrounding (shipped map): at least {g.claims_added_since} claim(s) have NO "
                 f"verdict — minted after the worklist was pinned. This record predates "
                 f"`claims_live_challenged`, so that is a lower bound.")
    return line


#: Ids an advisory names, for matching against what the map recorded.
#:
#: A CANDIDATE id — the shape only. Shape alone cannot settle it: `S3` in "stores artifacts in S3",
#: `C4` in "the C4 container view" (this tool's own vocabulary) and `D3` in "the D3 chart library"
#: are all well-formed ids and none of them is one. So candidates are intersected with the ids the
#: map actually DEFINES, below, which is decisive and free — the model is already loaded.
#:
#: A false id is not cosmetic: it can collide with something the map really did record and flip a
#: genuine unrecorded gap to `recorded`, the one direction this table must never fail in.
#: `EP` is included because entry-point ids are in the records vocabulary and were missing, so an
#: advisory naming only those fell through to the id-less branch.
_ADVISORY_IDS = re.compile(
    r"(?<![A-Za-z0-9])((?:UC|CAP|BLK|SD|SF|EP|HP|BR|C|D|E|I|R|S)\d+)(?![A-Za-z0-9])")


#: An advisory that REPORTS suppression rather than asking for it. These name a heading and quote
#: the very keys recorded under it, so any "is this recorded?" test answers yes — and the answer is
#: meaningless: they exist BECAUSE something was recorded. Marking them `recorded` filed the whole
#: "a recorded gap is still a gap" family under "handled", which cancelled the disclosure outright.
_DISCLOSURE = re.compile(
    r"suppressed by (?:a )?recorded|counted as (?:CLAIMED|SWEPT)|and NOT re-nudged|"
    r"is NOT re-reported above|advisory line\(s\) are silenced by this map's recorded lines|"
    r"advisory line\(s\) read differently because of this map's recorded lines|"
    r"^DISCLOSURE, not a request|"
    # The refutation gate saying what it did NOT block on. Asking whether that is "recorded under a
    # heading" is a category error: it reports a thing the map is right to carry.
    r"disclosure of what the refutation gate did NOT block on", re.I)


def advisory_disposition(map_path: Path, report: FinalizeReport) -> list[tuple[str, str, str]]:
    """(disposition, heading-or-'', advisory) for every advisory the gates raised.

    `finalize` already SAYS "each one is either fixed or recorded under the extras heading its
    message names", and then checked nothing — so nine advisories shipped on one map neither fixed
    nor recorded, and no transcript could show it because every read of the list had been narrowed
    by a grep. Both halves are here already: the advisory list, and the map.

    Four dispositions, and the design rule is that **the table never says `recorded` unless it can
    name the key that records it**. The first draft did the opposite — it defaulted to `recorded`
    whenever a heading existed and the advisory carried no id — and so reported "recorded" for an
    advisory whose own text reads "and no granularity record". That is the exact failure this
    function exists to catch, committed by the function itself.

    - `recorded` — the key this advisory is about is present under the heading it names.
    - `UNRECORDED` — the key is absent, and both halves of the key are known, so absence is a fact.
    - `UNSURE` — the heading keys on free text (a path, a bucket name) and this advisory carries no
      id, so the pairing cannot be decided here. Say so; do not guess either way.
    - `disclosure` — the advisory reports what a record silenced. Asking whether it is recorded is
      a category error.
    - `UNANSWERED` — a map-field escape (`grounding.note`) holds text, but the text does not state
      the count the advisory is about. Every other family keys a record to the id it silences and
      refuses a line that keys to nothing; this field had no key at all, so a note reading `no.`
      filed as `recorded`. Naming the number is the smallest key a prose field can carry, and it
      cannot be satisfied without having read the finding.
    - `carried (no escape)` — names no heading AND no map-field escape; can only be fixed.

    An advisory may offer a MAP FIELD instead of an extras heading — `grounding.note` is one — and
    this table read only `records.KNOWN_HEADINGS`, so it filed a taken escape as an absent one and
    the commit message repeated it."""
    from coyomap import records
    from coyomap.assemble import load_map_or_fragment
    try:
        m, _present = load_map_or_fragment(map_path)
    except Exception:
        return []
    # The id universe: nothing outside it is an id, whatever it looks like.
    from coyomap.model import all_elements
    defined = set(all_elements(m)) | {g.id for g in m.happy_path} | {
        ep.id for ep in m.entry_points if ep.id}
    out: list[tuple[str, str, str]] = []
    for leg in report.legs:
        for a in leg.advisory:
            low = a.lower()
            heading = next((h for h in records.KNOWN_HEADINGS if h.lower() in low), "")
            if _DISCLOSURE.search(a):
                out.append(("disclosure", heading, a))
                continue
            # Three advisories whose key is known although it is no id. A lost access FILE is
            # listed only while no line records it, so each one is unrecorded by construction; the
            # budget advisory is printed only when no `granularity:` or `component-budget:` line
            # names both counts (`budget_record`); and an excuse nobody read, or a recorded line
            # that silences nothing, is answered by reading or deleting, never by recording more.
            if "named by NO access rule in this map" in a or "budgeted across" in a:
                out.append(("UNRECORDED", heading, a))
                continue
            if UNREAD_EXCUSES in a or _INERT_DRIFT_RECORD.search(a):
                out.append(("carried (no escape)", "", a))
                continue
            if not heading:
                field = _map_field_escape(m, a)
                if field is not None:
                    out.append(field)
                    continue
                out.append(("carried (no escape)", "", a))
                continue
            ids = set(_ADVISORY_IDS.findall(a)) & defined
            if heading.lower() == "audit exceptions":
                # PAIRS, not ids. Reading every id under this heading marked a `flow-title UC25`
                # advisory "recorded" on the strength of an unrelated `actor-attribution UC25`
                # line — the family-vs-pair error the heading exists to prevent.
                from coyomap.audit_model import audit_exceptions
                check = a.split(":", 1)[0].strip().lower()
                if ids and check.replace("-", "").isalpha():
                    recorded = {eid for c, eid in audit_exceptions(m) if c.lower() == check}
                    out.append(("recorded" if ids & recorded else "UNRECORDED", heading, a))
                else:
                    out.append(("UNSURE", heading, a))
                continue
            recorded = records.recorded_keys(m, heading)
            if not ids:
                # Free-text key, or an advisory that names none. UNDECIDABLE here — and it must not
                # fall through to `recorded`, which is how "no granularity record" got filed as
                # recorded beside a heading holding unrelated lines.
                out.append(("UNSURE", heading, a))
            elif ids & recorded:
                out.append(("recorded", heading, a))
            else:
                out.append(("UNRECORDED", heading, a))
    return out


#: Worst first. An UNANSWERED or UNRECORDED row is an escape nobody took; `recorded` is the only
#: one that is finished.
_DISPOSITION_ORDER = ("UNANSWERED", "UNRECORDED", "UNSURE", "carried (no escape)", "disclosure",
                      "recorded")


def disposition_line(map_path: Path, report: FinalizeReport) -> str:
    """`Advisory disposition: UNSURE: 1 · disclosure: 9 · …`, or "" when there is nothing to say.

    ONE renderer, because this line has to appear in three places and drifting wordings are the
    defect it exists to prevent: the commit's gate block, the report file, and — since the
    2026-09-13 reminderrepo build — `finalize`'s own stdout. That build grepped `ship`'s stdout for
    `finalize: ADVISORIES\\|Advisory disposition`, matched only the count line (14 advisories before
    and after the fixes), and concluded "both mine are answered" while the report beside it said
    `UNSURE: 1`. The counts are one line; the verdict line was already on stdout."""
    return disposition_sentence(advisory_disposition(map_path, report))


def disposition_counts(disp: list[tuple[str, str, str]]) -> str:
    """`UNSURE: 1 · disclosure: 9`, worst first: the counts alone, for a line that has no room for
    the sentence around them (the build state's `finalize` line)."""
    counts = {k: sum(1 for d, _, _ in disp if d == k) for k in _DISPOSITION_ORDER}
    return " · ".join(f"{k}: {n}" for k, n in counts.items() if n)


def disposition_sentence(disp: list[tuple[str, str, str]]) -> str:
    """`disposition_line`'s sentence from rows already worked out, or "" when there are none."""
    if not disp:
        return ""
    return ("Advisory disposition: " + disposition_counts(disp)
            + ". An UNANSWERED or UNRECORDED row is an escape nobody took, not a carried one.")


#: Escapes an advisory can name that are NOT extras headings. `records.KNOWN_HEADINGS` is the only
#: vocabulary the disposition table knew, so an advisory offering a MAP FIELD as its second remedy
#: fell straight through to `carried (no escape)` — while the build had already taken that remedy.
#: The post-pin-claims advisory says, in its own text, "or say in `grounding.note` which claims were
#: minted after the pin and why they were not re-challenged"; the 2026-08-20 argus map carries
#: exactly that sentence, and both the report and the commit message called it unescapable.
_MAP_FIELD_ESCAPES = ("grounding.note",)


#: Written-out forms of the small numbers, because a note is prose and prose spells them. The
#: shipped mcpolis note says "Twenty-one claims in the shipped map were never in the pinned
#: worklist" — a digit check alone would have called that note unanswered.
_SPELLED: tuple[str, ...] = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty")


#: Each advisory that offers `grounding.note` as its remedy, and the pattern that pulls out THE
#: number it is about. Explicit per advisory, because "the first number in the text" is wrong for
#: half of them: the partial-grounding advisory opens with the count of claims that WERE confirmed,
#: so demanding it accepted a note restating the headline ("The 100 confirmed claims were the
#: security theme") and rejected the note that answers the finding ("we prioritized the 400
#: remaining claims"). A parser guessing at prose is what this table replaces.
_NOTE_KEYS: tuple[tuple[str, str], ...] = (
    # "…: 21 of the shipped map's 736 claim(s) have NO verdict" -> the 21 with no verdict
    ("covers the pinned worklist", r"(?:^|:\s*)(?:at least\s+)?(\d[\d,]*) of the shipped map"),
    # "…the 400 remaining claims are good leads" -> the REMAINING, never the confirmed
    ("grounding is partial", r"the (\d[\d,]*) remaining claims"),
)

#: A digit inside a path, a filename or a version is not the note NAMING a count — `read
#: verdicts-21.json` and `src/a.py:21` both used to satisfy a demand for 21.
_PATHY = re.compile(r"\S*[/\\.:-]\d[\d,]*\S*")


def _advisory_counts(advisory: str) -> list[int]:
    """The count(s) an advisory demands an answer about, or `[]` when this text names none.

    `[]` means "no key", and the caller then accepts any non-empty note — the behaviour before this
    table existed. An advisory whose wording moves out from under its pattern must fail OPEN: a gate
    that starts demanding an arbitrary number would reject honest notes with no way to tell why."""
    low = advisory.lower()
    for marker, pattern in _NOTE_KEYS:
        if marker in low:
            m = re.search(pattern, advisory, re.I)
            return [int(m.group(1).replace(",", ""))] if m else []
    return []


def _note_names(note: str, n: int) -> bool:
    """Does the note state `n`, as a digit or spelled out (`21` or `twenty-one`)?

    Two things this had to learn from a review. Path-shaped tokens are stripped first, because a
    note saying `read verdicts-21.json` names a filename, not a count. And the spelled form needs
    WORD BOUNDARIES: as a bare substring, `ten` is inside "written", `one` is inside "someone",
    "none" and "money", and `eight` is inside "weighted" — 13 of 18 counts probed against one real
    3400-character note matched by accident, which made the check close to inert for anything under
    twenty."""
    low = _PATHY.sub(" ", note.lower())
    if re.search(rf"(?<![\d,]){n}(?![\d,])", low.replace(",", "")):
        return True
    for word in _spelled_forms(n):
        if re.search(rf"\b{re.escape(word)}\b", low):
            return True
    return False


def _spelled_forms(n: int) -> list[str]:
    """How prose writes `n`. Only up to 99: past that a note spells it out too rarely to be worth
    the table, and the digit form still matches."""
    if 0 <= n <= 20:
        return [_SPELLED[n]]
    if 21 <= n <= 99:
        tens, ones = divmod(n, 10)
        word = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
                "ninety"][tens]
        return [word] if ones == 0 else [f"{word}-{_SPELLED[ones]}", f"{word} {_SPELLED[ones]}"]
    return []


def _map_field_escape(m: "ProjectModel", advisory: str) -> tuple[str, str, str] | None:
    """`(disposition, field, advisory)` when the advisory names a map-field escape, else None.

    Only the fields listed above, and only when the advisory NAMES one — a classifier that guesses
    at prose is how "no granularity record" got filed as recorded."""
    low = advisory.lower()
    for field in _MAP_FIELD_ESCAPES:
        if field not in low:
            continue
        if field == "grounding.note":
            note = (m.grounding.note if m.grounding else "") or ""
            if not note.strip():
                return ("UNRECORDED", field, advisory)
            # A NON-EMPTY note used to be the whole test, which made this the one escape in the map
            # with no key: every other family keys a recorded line to the id it silences and refuses
            # a line that keys to nothing. Here a note reading `no.` filed the advisory as answered.
            # The advisory states its own numbers ("21 of the shipped map's 736 claim(s) have NO
            # verdict"), so the note has to name the count it is excusing — the smallest thing that
            # cannot be satisfied without having read the finding.
            missing = _advisory_counts(advisory)
            unnamed = [n for n in missing if not _note_names(note, n)]
            if unnamed:
                return ("UNANSWERED", field, advisory)
            return ("recorded", field, advisory)
    return None


def gate_block(report: FinalizeReport, map_sha: str, disposition: str | None = None) -> str:
    """A copy-pasteable gate summary for the COMMIT MESSAGE, generated from the report.

    A live build read its own report, quoted the verdict honestly in chat ("that is not a clean
    pass"), and then wrote `validate … clean (1166 anchors resolved), audit reports no
    self-contradiction, anchor-drift clean` into the commit — three false clauses, with an anchor
    count copied from a validate run 32 minutes earlier. Chat is ephemeral; the commit is
    the only record a future reader sees. So the durable half must be generated, not remembered.

    That covers the VERDICT. The two other things a commit reliably gets wrong are the map's shape
    and its grounding coverage, for the same reason and with the same fix — see `_shape_line` and
    `_grounding_line`.

    `disposition` is `disposition_line`'s answer, when the caller already has it. Working it out
    re-loads the map, and `main` needs the same sentence for stdout — computing it twice printed
    `reading <map>` twice in the middle of a `ship` run for no gain."""
    lines = [f"Gates: finalize {report.verdict} — {report.blocking_total} blocking, "
             f"{report.advisory_total} advisory (map sha256 {map_sha[:12]}…)."]
    for leg in report.legs:
        if not leg.ran:
            lines.append(f"  {leg.name}: DID NOT RUN ({leg.status})")
            continue
        counts = f"{len(leg.blocking)} blocking, {len(leg.advisory)} advisory"
        lines.append(f"  {leg.name}: {counts}" + (f" — {leg.note}" if leg.note else ""))
    if report.advisory_total:
        lines.append("Advisories are NOT a pass. Some name an extras heading and can be recorded; "
                     "the rest name none (tests/test_method_contract.py KNOWN_NO_ESCAPE) and can only "
                     "be fixed or carried. State which of the two you did — neither is 'clean'.")
        # The report's own disposition, in the block the commit quotes: a two-way vocabulary here
        # ("recordable / no escape") is how one commit filed two UNANSWERED rows as carried.
        disp = (disposition_line(Path(report.map_path), report) if disposition is None
                else disposition)
        if disp:
            lines.append(disp)
    for extra in (_shape_line(Path(report.map_path)), _grounding_line(Path(report.map_path))):
        if extra:
            lines.append(extra)
    return "\n".join(lines)


@dataclass(frozen=True)
class ForceAdded:
    """What the `git add -f` line names: the files, in the order it names them, and the warrant
    DIRECTORIES after them. ONE list, read by the commit line and by the credential scan, so the scan
    covers exactly what the line would commit."""
    present: list[Path]
    missing: list[Path]
    warrant: list[Path]
    reconcile: Path


def force_added(map_path: Path) -> ForceAdded:
    """The paths `finalize`'s commit line force-adds, and the required ones not there yet."""
    # The four artifacts the method says ship with the map, and whether git will actually take them.
    # A live build ran `git check-ignore`, GOT the answer (`.gitignore:85:.coyomap/`), and then issued
    # an un-forced `git add` two turns later that failed — shipping a map whose viewer symbol-search
    # input (`preindex.json`) and provenance were left untracked. Naming the command removes the step
    # where the operator has to remember the `-f`.
    required = [map_path, map_path.with_suffix(".md"),
                map_path.parent / "preindex.json", map_path.parent / "provenance.json"]
    present = [p for p in required if p.exists()]
    missing = [p for p in required if not p.exists()]
    # THE RECONCILE FILE IS AN ASSEMBLE INPUT, and the only mechanism that carries a reconcile
    # decision across a rebuild (method.md). It was missing from this line entirely — not ignored by
    # `.coyomap/.gitignore`, just never named — so a commit that followed the printed command
    # shipped the map WITHOUT the decisions that produced it. Re-assembling the 2026-09-13
    # reminderrepo build's committed fragments without it gives 248 edges against the committed
    # map's 243: the two arrows the closer upheld as false come back, 8 code links revert, and 119
    # directive rows naming 340 element ids are lost.
    #
    # With the INPUTS rather than with the WARRANT: `verify/` and `build-fragments/` are the reason
    # to BELIEVE the map, while this file is one of the things `assemble` READS to produce it —
    # the same role `preindex.json` plays for the viewer. It is listed last of the inputs, in the
    # order `assemble` names it.
    reconcile = map_path.parent / "reconcile.json"
    if reconcile.exists():
        present.append(reconcile)
    # THE WARRANT SHIPS WITH THE MAP. The four paths above are the map and its inputs; they are not
    # the reason to BELIEVE it. That lives in `verify/` — the pinned worklist, the claims batches
    # and every skeptic's verdict file — and in the fragments each agent authored. `grounding.note`
    # cites "1,048 verdict rows … 33 skeptic labels" as the map's warrant, and on the 2026-09-02
    # mcpolis build 71 verify files and 47 fragments were git-ignored and force-added by nothing.
    # A fresh clone got the conclusion and could check no part of it.
    #
    # Named as DIRECTORIES, not expanded: `git add -f <dir>` takes the whole tree, the count is
    # what an operator needs to see, and a 118-path command line is not copyable.
    warrant = [d for d in (map_path.parent / "verify", map_path.parent / "build-fragments")
               if d.is_dir() and any(d.iterdir())]
    return ForceAdded(present=present, missing=missing, warrant=warrant, reconcile=reconcile)


def _credential_leg(map_path: Path) -> Leg:
    """Credential-shaped values in the files of the map folder. BLOCKING in a file the commit takes.

    The commit line takes the agents' own files — every verdict, every fragment — and nothing read
    them. On the 2026-09-30 mcpolis build a skeptic's glob printed the production API key into its
    transcript; it reached no committed file, and nothing would have said so if it had. No recorded
    escape, and none is needed: the remedy is to rewrite one sentence without the value, which costs
    nothing and is always possible. The value itself is never printed (`credentials`).

    A value in a file NO commit takes (`never_committed`: the findings, the build state) is an
    ADVISORY that names the file and says to remove the line. Blocking there withheld the commit
    line over a value the commit would never have carried. `coyomap credentials` reads the same
    answer, so an update's close and a build's finalize never disagree about a file."""
    # THE WHOLE MAP FOLDER, archived maps aside: everything the commit line force-adds, and
    # `.ignore` and `changes/`, which it takes too and the first version of this leg never read.
    # Not this command's own report, which this run rewrites from masked strings: counting it made
    # two identical runs report different numbers.
    own = {f"{REPORT_STEM}.json", f"{REPORT_STEM}.md"}
    folder = map_path.parent
    files = [f for f in map_folder_files(folder) if f.name not in own]
    hits = scan_credentials(files)
    by_file = places(hits)
    kept = {path for path in by_file if never_committed(folder, path)}
    blocking = [f"{path}: {', '.join(where)} — a credential-shaped value in a file of the map "
                f"folder, which the commit takes. Rewrite that text without the value (name the "
                f"setting, never its value) and re-run finalize; the commit line is withheld until "
                f"then. If the value is real it is also in the transcript of the agent that wrote "
                f"it: tell the operator, who decides whether to rotate it."
                for path, where in by_file.items() if path not in kept]
    advisory = [f"{path}: {', '.join(where)} — a credential-shaped value in a file no commit "
                f"takes, so the commit line stands. {UNCOMMITTED_REMEDY}"
                for path, where in by_file.items() if path in kept]
    return Leg("credential scan", RAN, blocking=blocking, advisory=advisory,
               note=f"{len(files)} file(s) of the map folder scanned for credential shapes: "
                    f"{len(hits)} hit(s)"
                    + (f", {sum(len(by_file[p]) for p in kept)} of them in {len(kept)} file(s) no "
                       f"commit takes" if kept else ""))


def _commit_hint(map_path: Path, withheld: bool = False) -> None:
    """What to commit, and the `git add -f` line that will actually take it — unless the credential
    scan found a value in those files, when the line is withheld rather than printed."""
    fa = force_added(map_path)
    present, missing, warrant, reconcile = fa.present, fa.missing, fa.warrant, fa.reconcile
    if withheld:
        print("finalize: NO commit line — the credential scan found a credential-shaped value in the "
              "files it would force-add. Rewrite those lines and re-run finalize.")
        return
    if present:
        counts = ", ".join(f"{d.name}/ ({sum(1 for _ in d.rglob('*') if _.is_file())} files)"
                           for d in warrant)
        print("finalize: commit these with the map — "
              f"git add -f {' '.join(str(p) for p in present + warrant)}\n"
              "  (`-f` because a repo whose root .gitignore ignores `.coyomap/` refuses a plain "
              "`git add`, and method.md requires the pre-index and provenance to ship with the map.)"
              + (f"\n  The last of those are the map's WARRANT — {counts}. The note cites the "
                 f"verdict rows as the reason to believe the map; without them a fresh clone has "
                 f"the conclusion and can check no part of it." if warrant else "")
              + (f"\n  {reconcile.name} rides with them: it is what makes a reconcile decision "
                 f"survive a rebuild, and an assemble without it silently reverts every one."
                 if reconcile.exists() else ""))
    if not reconcile.exists():
        # NOT in `missing`: that arm says "produce them and re-run", which is the wrong sentence
        # here. A build that reconciled nothing has no reconcile file and needs none, so absence is
        # reported as a question rather than as a defect.
        print(f"finalize: no {reconcile} — right if this build reconciled nothing. If it recorded "
              f"decisions somewhere else, commit that file too: it is the ONLY thing that carries "
              f"a reconcile decision into the next rebuild.")
    if missing:
        # NAME what is absent instead of quietly dropping it from the command. The filter above is
        # right — `git add` on a non-existent path fails — but printing the survivors alone turns a
        # missing artifact into a shorter, still-copyable line. A live build ran finalize before
        # stamping provenance, and the hint it printed would have committed the map WITHOUT it: the
        # exact omission the hint exists to prevent. The operator caught it by hand.
        # NAME THE COMMAND for each, too. Telling a build to "produce them" without saying how
        # cost a live run two extra finalize rounds: it re-ran finalize unchanged, got the identical
        # complaint, and only then went hunting — provenance was, at the time, produced by a script
        # in the coyomap clone that the shipped CLI does not install. It is `coyomap provenance
        # stamp` now, and the hint says so.
        how = {"provenance.json": "coyomap provenance stamp .",
               "preindex.json": "coyomap preindex . --report"}
        print(f"finalize: NOT in that command, because {'it does' if len(missing) == 1 else 'they do'}"
              f" not exist yet — {', '.join(str(p) for p in missing)}. method.md requires the "
              f"pre-index and provenance to ship WITH the map; produce them and re-run finalize "
              f"rather than committing the shorter line above.")
        for p_missing in missing:
            cmd = how.get(p_missing.name)
            if cmd:
                print(f"  {p_missing.name}: {cmd}")

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        print("usage: coyomap finalize [--repo <root>] [--verdicts <file>]... "
              "[--emit-gate-block <file>] [--access-baseline <map-or-surface.json>] "
              "[--lead-transcript <session.jsonl>] [--no-write] "
              "[.coyomap/project-map.json]\n\n"
              "The pre-commit read: validate (--check-sources --check-coverage) + audit +\n"
              "anchor-drift (shape-only, and verdict-based when --verdicts is given). Writes\n"
              ".coyomap/finalize-report.{json,md} and prints one verdict line. It adds no check of\n"
              "\n--no-write PRINTS the report instead of writing it, leaving the build's own\n"
              "finalize-report.{json,md} untouched. For a report-only reader — a retrospective\n"
              "running finalize to see a finished build's disposition would otherwise overwrite\n"
              "the record it came to read. (--emit-gate-block still writes the file it names.)\n"
              "its own, and it compares nothing against a previous map — a map evolves with the\n"
              "code, so a build has no predecessor to diff against.\n\n"
              "A CONVENIENCE WRAPPER, not an enforcement point: exit 1 for what validate and audit\n"
              "already block on (schema/reference problems, L1 contradictions), or when a leg that\n"
              "should have run did not (INCOMPLETE — never reported as a pass). Unapplied anchor\n"
              "drift is reported, never gating: apply-drift cannot fix an entry-point cadence\n"
              "anchor, so gating on it would fail a build that has no remedy.\n\n"
              "--access-baseline names a PREVIOUS map (or a `coyomap access-surface` file) and adds\n"
              "one advisory leg: files that held ACCESS enforcement there and are named by no access\n"
              "rule here. A rebuild is blind to its predecessor by design, so a security claim can\n"
              "disappear between two maps of unchanged code with nothing noticing — one pair held its\n"
              "access-rule COUNT at 21 -> 21 while the file verifying an identity token's signature\n"
              "lost its claim entirely. Reading it HERE cannot contaminate the rebuild: the map is\n"
              "already written, and the commit has not happened yet. Each lost file is listed with\n"
              "its lines there and never with the old map's text, and the excused files the lead's\n"
              "own transcript never shows it opening are counted: --lead-transcript names that\n"
              "transcript (default: this session's, from $CLAUDE_CODE_SESSION_ID).\n\n"
              "Read the REPORT FILE, not this stdout: a file survives `> /dev/null` and `| tail`,\n"
              "and it carries whole lists with no `+N more`.")
        return 0
    repo: Path | None = None
    verdicts: list[Path] = []
    gate_block_path: Path | None = None
    access_baseline: Path | None = None
    #: The lead's own transcript, read for the excused access paths it never opened. Defaults to
    #: this session's, which is right inside a build and wrong for a retrospective — so a reader
    #: re-running finalize on a finished build names the build's file here.
    lead_transcript: Path | None = None
    #: Report-only. `finalize` OVERWRITES `.coyomap/finalize-report.{json,md}` on every run, and
    #: the retro method sends a read-only reader at it — so reading a finished build's disposition
    #: destroyed the record of the disposition being read. A reader can now see it without
    #: replacing what the build left behind.
    no_write = False
    positional: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--no-write":
            no_write = True
        elif a == "--emit-gate-block":
            i += 1
            if i >= len(argv):
                print("ERROR: --emit-gate-block needs a value", file=sys.stderr)
                return 2
            gate_block_path = Path(argv[i])
        elif a in ("--repo", "--verdicts", "--access-baseline", "--lead-transcript"):
            i += 1
            if i >= len(argv):
                print(f"ERROR: {a} needs a path", file=sys.stderr)
                return 2
            if a == "--repo":
                repo = Path(argv[i])
            elif a == "--access-baseline":
                access_baseline = Path(argv[i])
            elif a == "--lead-transcript":
                lead_transcript = Path(argv[i])
            else:
                # VARIADIC, exactly as `grounding` had to become: swallow every following non-flag
                # path. It took one value per flag, so the natural `--verdicts verify/verdicts-*.json`
                # handed it ONE file and let the shell's other nineteen fall through to `positional`,
                # where they were silently ignored — the report then described a pass over one batch
                # as the whole pass. `grounding` failed loudly on the same spelling (`unknown
                # option(s)`); here it failed silently, which is the worse half of the same bug and
                # the one this command exists to make impossible.
                verdicts.append(Path(argv[i]))
                while i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                    i += 1
                    verdicts.append(Path(argv[i]))
        elif a.startswith("-"):
            print(f"ERROR: unknown option '{a}'", file=sys.stderr)
            return 2
        else:
            positional.append(a)
        i += 1
    if len(positional) > 1:
        # One map per run. An extra bare path is a mis-typed option, and swallowing it is how the
        # `--verdicts` glob above went unnoticed for so long: the files landed here and nothing said
        # a word about them.
        print(f"ERROR: finalize takes ONE map path; got {len(positional)} "
              f"({shown(positional, 4)}). Pass verdict files after --verdicts.", file=sys.stderr)
        return 2
    map_path = Path(positional[0] if positional else ".coyomap/project-map.json")
    if not map_path.exists():
        print(f"ERROR: {map_path} not found", file=sys.stderr)
        return 1
    for v in verdicts:
        if not v.exists():
            print(f"ERROR: --verdicts {v} not found", file=sys.stderr)
            return 1
    if repo is None:
        repo = map_path.resolve().parent.parent
    try:
        load_model_path(map_path)          # fail fast and legibly, before any leg runs
    except ModelError as e:
        print(f"ERROR: {map_path} is not a loadable map: {e}", file=sys.stderr)
        return 1
    # No `set_full_lists` here: every leg that renders a list goes through a `--json` subcommand, and
    # each of those sets and RESETS the mode itself — so a flag set here was cleared by the first leg
    # and did nothing. Whole lists come from the legs' own JSON, which is the honest mechanism.
    if access_baseline is not None and not access_baseline.exists():
        print(f"ERROR: --access-baseline {access_baseline} not found", file=sys.stderr)
        return 1
    if lead_transcript is not None and not lead_transcript.is_file():
        print(f"ERROR: --lead-transcript {lead_transcript} not found", file=sys.stderr)
        return 1
    if lead_transcript is None:
        lead_transcript = session_transcript(repo)
    report = build_report(map_path, repo, verdicts, access_baseline, lead_transcript)
    # ONCE. The gate block, the stdout line and the build state below all say it, and working it out
    # re-loads the map.
    disposition_rows = advisory_disposition(map_path, report)
    disposition = disposition_sentence(disposition_rows)
    json_path = map_path.parent / f"{REPORT_STEM}.json"
    md_path = map_path.parent / f"{REPORT_STEM}.md"
    if no_write:
        # Print what would have been written, so `--no-write` is a READ and not a silence.
        print(format_report(report))
        print(f"finalize: --no-write, so {md_path} and {json_path} are unchanged", file=sys.stderr)
    else:
        json_path.write_text(report.to_json(), encoding="utf-8")
        md_path.write_text(format_report(report), encoding="utf-8")
        # THE RUN THAT WROTE THE RECORD, never a `--no-write` read: a retrospective reading a
        # finished build's disposition must not add a line to that build's state.
        unran_legs = [f"{l.name} ({l.status})" for l in report.legs if not l.ran]
        counts = disposition_counts(disposition_rows)
        buildstate.append(buildstate.repo_of(map_path), "finalize",
                          f"{report.verdict} — {report.blocking_total} blocking, "
                          f"{report.advisory_total} advisory"
                          + (f" · disposition {counts}" if counts else "")
                          + (f" · DID NOT RUN: {', '.join(unran_legs)}" if unran_legs else "")
                          + f" → {md_path}")
    if gate_block_path is not None:
        import hashlib
        sha = hashlib.sha256(map_path.read_bytes()).hexdigest()
        gate_block_path.parent.mkdir(parents=True, exist_ok=True)
        gate_block_path.write_text(gate_block(report, sha, disposition) + "\n",
                                   encoding="utf-8")
        print(f"finalize: wrote the commit-message gate block to {gate_block_path}")
    _commit_hint(map_path, withheld=any(l.name == "credential scan" and l.blocking
                                        for l in report.legs))
    unran = [f"{l.name} ({l.status})" for l in report.legs if not l.ran]
    print(f"finalize: {report.verdict} — {report.blocking_total} blocking, "
          f"{report.advisory_total} advisory"
          + (f"; DID NOT RUN: {', '.join(unran)}" if unran else "")
          + (". Full findings above — `--no-write` printed the report instead of writing it, so "
             f"{md_path.name} still holds the build's own." if no_write
             else f". Full findings: {md_path}"))
    # BESIDE THE VERDICT LINE, on stdout. The count alone does not move when an advisory is
    # answered — 14 before and 14 after, on the run that read it — so a build grepping this output
    # for its disposition found the count and read it as an answer. The counts do move. The ROWS
    # still live in the report file, which this line says rather than replaces.
    if disposition:
        print(f"finalize: {disposition} Which advisory is which — its text, and the heading it "
              f"names — is in the `Advisory disposition` table of {md_path.name}"
              + ("; this run printed that table above instead of writing it." if no_write
                 else "; this line carries the counts only."))
    if report.verdict == "INCOMPLETE":
        print("finalize: INCOMPLETE — a check that should have run did not, so this run does NOT know "
              "whether the map is clean. Fix the cause above and re-run; do not read the absence of "
              "findings as their absence.", file=sys.stderr)
    if report.verdict == "ADVISORIES":
        print("finalize: advisories are not a pass — fix each one or record it under the extras "
              "heading its message names. Quote THIS verdict line when reporting the gates; a build "
              "that says \"gates clean\" with advisories open is the failure this command exists for.",
              file=sys.stderr)
    # INCOMPLETE exits non-zero too: "the gate did not run" must not read as "the gate passed".
    return 1 if (report.blocking_total or report.verdict == "INCOMPLETE") else 0


if __name__ == "__main__":
    raise SystemExit(main())
