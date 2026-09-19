#!/usr/bin/env python3
"""The challenge step of an update — what the wave re-argues, what is carried, and how the verdicts
fold back into the map's record.

A build ends with fresh-context skeptics reading every statement the map makes against the code
(method.md, Phase 4). An update used to end with none: the boxes it wrote had been argued with by
nobody, while the map's `grounding` record went on describing the build. Two verbs close that gap,
and cost in proportion to the diff rather than to the map:

  coyomap changes challenge <log> --map … --before … --touched …
      the statements to re-argue, cut into claims batches beside the build's (same folder, same
      names the skeptic contract composes, one wave's prefix on each), and the APPLIED COPY of the
      map — the log written into the map as it is — which is what the skeptics read, so that a
      refutation amends the log before anything on disk moves
  coyomap changes ground <log> --map … --before … --touched … --note-file …
      after the wave: the warrant re-pinned to the map as it now is, every earlier verdict carried,
      re-keyed or retired, the record re-measured over the whole live surface and written into the
      map, one row added to its wave ledger, and the log told what the wave decided

WHAT IS IN SCOPE (`scope_update`). Every statement the updated map makes falls in exactly one of:
  changed   its words are new or rewritten — no earlier verdict can be about them
  touched   its words stand, but the code touched one of its boxes (a gate hit, or a box an entry
            names or waives): the earlier verdict was cast on code that has since changed
  rippled   its words stand, but the change reached one of its boxes through the map (a caller, a
            walk step, a rule site): the neighbour the verdict rested on may have moved
  carried   nothing about it moved, and it has a verdict: the verdict stands and it is not re-voted
  unvoted   the build never voted it and nothing puts it in scope — or its whole THEME was never
            voted (a partial build that left, say, the behaviour theme unread): it stays unvoted,
            and the record goes on saying so. Parity with the build is the rule, in both
            directions: an update reads no theme the build did not, and skips none it did.
            Measured on the mcpolis dry run: without this, 451 of the 551 statements in scope
            were step phrases of a theme with zero verdicts behind it, eleven skeptics for a
            theme the build had decided not to buy.
and a pinned statement the updated map no longer makes is `superseded`: its verdicts are retired.

A PURE LINE SHIFT IS NOT A CHANGE. A rule-site statement embeds its `file:line`, so a line inserted
above it re-mints the statement word for word except the number. The re-anchor step already knows
which links only shifted; replaying it in memory on the map as it was gives the old text → shifted
text pairs (`shift_renames`), and a verdict cast on the old text is carried under the new one. On
the mcpolis dry run of 2026-09-15, 28 of the 206 statements anchored in the eight shifted files
would otherwise have been re-voted for nothing, 17 of them three-voted access statements.

OLD VOTES NEVER MIX WITH NEW ONES. A statement the wave re-votes has its earlier rows retired first:
a build's 1-0 confirmation plus an update's 1-0 refutation would otherwise tally as a tie, which
every gate reads as "unverifiable" and none as "refuted". Retired rows go to
`verify/retired-<from>-<to>.json`, whose payload deliberately is not the verdicts shape, so nothing
that scans the folder for votes ever counts them again.

Stdlib-only (the cli.py firewall).
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from coyomap.anchors import parse_anchor
from coyomap.audit_model import WorkItem, l2_worklist_model, worklist_payload, write_theme_batches
from coyomap.changelog import (ChangeLog, apply, commit_matches, dump_log, element_of, gated_box,
                               load_log, touched_ids)
from coyomap.grounding import (
    _note_contradictions,
    _verdict_bucket,
    _worklist_claims,
    build_record,
    closer_ruling,
    closer_word,
    is_closer_row,
    multi_vote_agreement,
    skeptic_labels,
    split_closer_rows,
    worklist_is_behavioural,
    DISPUTED,
    REDUNDANT_PHRASE,
)
from coyomap.impact_git import ImpactError, rename_map, resolve_ref, tree_paths, u0_diff
from coyomap.model import ModelError, load_model, resolve_map_path
from coyomap.reanchor import line_mapper, reanchor

USAGE = """usage: coyomap changes challenge <log> --map <map> --before <before.json> --touched <impact.json>
                                 [--repo <root>] [--cap N] [--floor N] [--json]
       coyomap changes ground <log> --map <map> --before <before.json> --touched <impact.json>
                              (--note-file <path> | --dry-run) [--repo <root>] [--json]

challenge  the statements an update must re-argue, before anything on disk moves. Writes the log
           applied to a copy of the map (`<log>.applied.json` — what the skeptics read), the claims
           batches into `.coyomap/verify/` as `claims-<from>-<to>-<theme>.json`, and
           `<log>.scope.json` saying which statement is in scope and why. Then dispatch:
             coyomap contract skeptic --from-batches .coyomap/verify --prefix <from>-<to>- …
ground     after the wave has landed (`grounding lint` clean, the closer heard, the log amended):
           re-pins `.coyomap/verify/worklist.json` to the map as it now is (the old pin is kept as
           `worklist-<from>.json`), carries every earlier verdict whose statement and code did not
           move (re-keyed across a pure line shift, its evidence line shifted with it), retires the
           rest to `retired-<from>-<to>.json`, re-measures the record over the whole live surface,
           writes it into the map with one more row in `grounding.history`, and writes what the
           wave decided into the log's `challenge` block. `--dry-run` prints the NOTE FACTS the
           note is written from and writes nothing.

--before is the copy step 0 kept (`<log>.before.json`: the map before re-anchor), --touched the
impact file step 1 wrote. `--map` is the re-anchored map for `challenge` and the APPLIED map for
`ground` — the same file, before and after `changes apply`.
"""

REASONS = ("changed", "touched", "rippled")
WORKLIST = "worklist.json"
RETIRED_FORMAT = "coyomap-retired-verdicts"
SCOPE_FORMAT = "coyomap-scope"
DEFAULT_CAP = 40
DEFAULT_FLOOR = 5


# ── the scope ─────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Scoped:
    """One statement the wave re-argues, and why."""
    item: WorkItem
    reason: str            # changed | touched | rippled
    via: str = ""          # the box that put it in scope, and how


@dataclass
class Scope:
    update: str                                  # `<from>-<to>`, the log's own name
    date: str                                    # the day the log was written
    behavioural: bool                            # the pinned worklist's tier, kept
    live: list[WorkItem]                         # every statement the updated map makes
    renames: dict[str, str]                      # old text → shifted text, pure line shifts only
    pinned: list[str]                            # the build's pinned statements, re-keyed
    in_scope: list[Scoped]
    carried: list[str]                           # live ∩ pinned, voted, nothing moved
    unvoted: list[str]                           # live ∩ pinned, never voted, nothing moved
    superseded: list[str]                        # pinned, and the updated map no longer says it
    touched: dict[str, str] = field(default_factory=dict)    # box → why it counts as touched
    rippled: dict[str, str] = field(default_factory=dict)    # box → what reached it
    notes: list[str] = field(default_factory=list)
    no_warrant: bool = False                     # no pinned worklist with verdicts beside the map

    @property
    def claims_in_scope(self) -> list[str]:
        return [s.item.claim for s in self.in_scope]

    def by_reason(self) -> dict[str, int]:
        return {r: sum(1 for s in self.in_scope if s.reason == r) for r in REASONS}

    def by_theme(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.in_scope:
            out[s.item.theme] = out.get(s.item.theme, 0) + 1
        return out


def shift_renames(before_text: str, repo: Path, to: str,
                  behavioural: bool) -> tuple[dict[str, str], list[str]]:
    """Old statement text → the same statement after the re-anchor step moved its line.

    The re-anchor run is REPLAYED in memory on the map as it was, never re-derived: the criterion
    for "only the line moved" is that step's own (git's line map, an unchanged line), so the two
    cannot disagree about which links shifted. The statement lists of the two copies then pair by
    position — the run changes anchor strings and never structure — and a pair that differs is a
    shift. The pairing is checked before it is trusted: if the two lists differ in theme or in
    the boxes they name, nothing is renamed and every shifted statement is simply re-voted, which
    costs skeptics and never a verdict."""
    old = load_model(before_text)
    shifted = load_model(before_text)
    reanchor(shifted, repo, to)
    a = l2_worklist_model(old, behavioural=behavioural)
    b = l2_worklist_model(shifted, behavioural=behavioural)
    if [(x.theme, x.elements) for x in a] != [(y.theme, y.elements) for y in b]:
        return {}, ["the re-anchored copy of the map as it was mints a different statement list "
                    "from the map as it was, so no verdict is carried across a line shift: every "
                    "statement whose line moved is re-voted"]
    renames = {x.claim: y.claim for x, y in zip(a, b) if x.claim != y.claim}
    return renames, ([f"{len(renames)} statement(s) re-minted by a line shift alone; their "
                      f"verdicts are carried under the new text"] if renames else [])


def _worklist_items(path: Path) -> list[dict[str, Any]]:
    """The pinned worklist's items, in either shape the file legitimately has."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = payload if isinstance(payload, list) else payload.get("worklist", [])
    return [i for i in items if isinstance(i, dict) and isinstance(i.get("claim"), str)]


def read_rows(path: Path) -> tuple[dict[str, Any] | list[Any], list[dict[str, Any]]]:
    """A verdict file's payload and its rows — the `{"grounding": [...]}` wrapper or a bare list,
    the two shapes `anchor_drift.load_verdicts` accepts. The payload comes back so a rewrite keeps
    whatever else the file carried."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("grounding") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"{path.name}: no verdict rows (expected a `grounding` list)")
    return payload, [r for r in rows if isinstance(r, dict)]


def batch_claims(path: Path) -> list[str]:
    """The statements one claims batch holds, as `write_theme_batches` wrote them."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    claims = payload.get("claims") if isinstance(payload, dict) else None
    return [str(c["claim"]) for c in (claims or []) if isinstance(c, dict) and c.get("claim")]


def batch_theme(path: Path) -> str:
    """The theme a claims batch is FOR, read off the file rather than parsed out of its name.

    `write_theme_batches` stamps `theme` into every batch it writes, so the file already knows. The
    first version of finalize's dispatch gate re-derived it from the file NAME, which is wrong twice
    over: an update wave is `claims-<from>-<to>-<theme>.json`, so the parse announced a pair of git
    shas as the theme, and `claims-small.json` reports `small` where the file itself says `mixed` —
    the spelling `audit --json`'s `theme_counts` uses. Falls back to the name only for a file with
    no `theme` at all."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    theme = payload.get("theme") if isinstance(payload, dict) else None
    if isinstance(theme, str) and theme.strip():
        return theme.strip()
    stem = path.stem[len("claims-"):] if path.stem.startswith("claims-") else path.stem
    head, _, tail = stem.rpartition("-")
    return head if (head and tail.isdigit()) else stem


def unanswered_batches(verify: Path, update: str) -> list[Path]:
    """This update's claims batches that no verdicts file answers, across all its waves.

    ANSWERED IS A CLAIM, NEVER A FILE NAME. The first version matched
    `name.startswith(f"verdicts-{batch}")`, which is wrong in both directions and was caught only
    when the same mistake was written a second time in `finalize`:

    * It absolves a batch nobody read. `verdicts-behaviour-10.json` starts with
      `verdicts-behaviour-1`, so batch 1 reads as answered whenever batch 10 was. Two-digit batch
      counts are ordinary — one build cut `behaviour-1` through `behaviour-24`.
    * It accuses a batch that was answered. `«BATCH»` is the SKEPTIC's id and `«CLAIMS»` the file it
      reads (`method/templates/skeptic-contract.md`); one skeptic may legitimately answer several
      small batches in one file. On the argus map, `verdicts-smallmix.json` answers 77 of 77 claims
      across five batches, every one of which the name match called unread.

    The claims themselves settle it, they are already on disk, and they cannot collide."""
    answered = voted_claims(wave_files(verify, update))
    out: list[Path] = []
    for claims_file in sorted(verify.glob(f"claims-{update}-*.json")):
        claims = batch_claims(claims_file)
        if claims and not (set(claims) & answered):
            out.append(claims_file)
    return out


def verdict_files(verify: Path) -> list[Path]:
    """Every file `grounding write` would be handed: the skeptics' votes and the closer's appeals."""
    return sorted(verify.glob("verdicts-*.json")) + sorted(verify.glob("closer-*.json"))


def wave_files(verify: Path, update: str) -> list[Path]:
    """The verdict files one update's waves wrote — named with the update's `<from>-<to>`."""
    return [f for f in verdict_files(verify) if update in f.name]


def voted_claims(files: list[Path]) -> set[str]:
    """Every statement a skeptic actually voted on across `files`.

    A file that cannot be read contributes NOTHING, which is the honest answer and also the useful
    one: an empty, truncated or non-JSON verdict file is not a review, and a gate that pairs on this
    set cannot be satisfied by `touch`ing a name into existence. Closer rows are excluded — the
    closer rules on appeals, it does not vote (`grounding.is_closer_row`)."""
    out: set[str] = set()
    for f in files:
        try:
            _payload, rows = read_rows(f)
        except (OSError, ValueError):
            continue
        out.update(str(r["claim"]) for r in rows if isinstance(r.get("claim"), str)
                   and not is_closer_row(r))
    return out


def wave_voted(verify: Path, update: str) -> set[str]:
    """The statements this update's earlier waves already voted on."""
    return voted_claims(wave_files(verify, update))


def next_prefix(verify: Path, update: str) -> str:
    """The file-name prefix for this run's batches. The first wave writes `claims-<update>-…`; a
    run after a wave has landed (a refutation amended the log, and the fix re-minted statements)
    writes `claims-<update>-w2-…`, and so on — never over a batch a skeptic has answered."""
    if not wave_files(verify, update):
        return f"{update}-"
    n = 2
    while any(verify.glob(f"claims-{update}-w{n}-*.json")):
        n += 1
    return f"{update}-w{n}-"


def pin_for(verify: Path, log: ChangeLog) -> Path:
    """The pinned worklist this update measures against: the one the map had BEFORE it.

    After `ground` has run, `worklist.json` is this update's own re-pin (`pinned_by` names it) and
    the list it replaced sits under the from-commit's name. Reading that one keeps a second
    `ground` — a retry after a crash, a re-run by mistake — computing the same scope as the first,
    instead of finding every statement already pinned and calling the wave's votes orphans."""
    current = verify / WORKLIST
    if grounded_already(verify, log):
        old = verify / f"worklist-{log.from_commit[:7]}.json"
        if old.is_file():
            return old
    return current


def grounded_already(verify: Path, log: ChangeLog) -> bool:
    """Has this update's `ground` already re-pinned the worklist?"""
    try:
        payload = json.loads((verify / WORKLIST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("pinned_by") == f"{log.from_commit}-{log.to_commit}"


def _ripple_via(imp: dict[str, Any]) -> str:
    via = imp.get("via") or []
    first = via[0] if via and isinstance(via[0], dict) else {}
    src, rel = str(first.get("from") or ""), str(first.get("relation") or "")
    return f"{src} ({rel})" if src and rel else src or rel or "the map"


def scope_update(log: ChangeLog, before_text: str, new_doc: dict[str, Any],
                 impact: dict[str, Any], verify: Path, repo: Path) -> Scope:
    """Which of the updated map's statements the wave must re-argue, and what is carried.

    `new_doc` is the map with the log written in — the applied copy at `challenge` time, the map on
    disk at `ground` time; both are the same document, which is what lets the two verbs agree on the
    scope without a file passing between them."""
    update = f"{log.from_commit}-{log.to_commit}"
    pin = pin_for(verify, log)
    behavioural = worklist_is_behavioural(pin) if pin.is_file() else False
    new = load_model(json.dumps(new_doc))
    live = l2_worklist_model(new, behavioural=behavioural)
    renames, notes = shift_renames(before_text, repo, log.to_commit, behavioural)
    pinned = [renames.get(c, c) for c in (_worklist_claims(pin) if pin.is_file() else [])]
    voted: set[str] = set()
    for f in verdict_files(verify):
        try:
            _payload, rows = read_rows(f)
        except (OSError, ValueError):
            continue
        for r in rows:
            if isinstance(r.get("claim"), str) and not is_closer_row(r):
                voted.add(renames.get(str(r["claim"]), str(r["claim"])))
    # THE THEMES THE BUILD BOUGHT. A theme with no verdict behind any of its pinned statements was
    # left unread on purpose (`grounding.note` says which), and the update keeps that decision.
    pinned_theme = {renames.get(i["claim"], i["claim"]): str(i.get("theme") or "")
                    for i in _worklist_items(pin)} if pin.is_file() else {}
    voted_themes = {pinned_theme[c] for c in voted if c in pinned_theme}
    # NO WARRANT AT ALL — no pinned worklist, or no verdict beside it. There is nothing to carry
    # and nothing to keep parity with, and a wave over the whole map would be a build's Phase-4
    # pass billed to an update. Everything stays unvoted, and the reason is printed.
    no_warrant = not pinned_theme or not voted_themes
    # TOUCHED: what the gate counts (a line or symbol hit, a link into a deleted file), and every
    # box the log itself names or waives — an entry says "this box changed meaning", a waiver says
    # "the code touched it and the meaning did not", and both are claims a stranger should read.
    impacts = impact.get("impacts") or {}
    touched: dict[str, str] = {box: "the code touched it" for box in touched_ids(impact)}
    # A WAY IN's own hit. `element_of` files an `ep:<file>:<line>` hit under no box, so the gate
    # never counts it — but a cadence statement is about exactly that way in. Resolve the hit to
    # the entry point's id through the map, the way `coyomap impact` prints it.
    ep_ids = {f"ep:{ep.source}": ep.id for ep in new.entry_points if ep.id and ep.source}
    for eid, imp in impacts.items():
        if (isinstance(imp, dict) and imp.get("cause") == "direct" and str(eid) in ep_ids
                and imp.get("change") != "drifted"
                and (imp.get("change") == "deleted" or imp.get("resolution") in ("line", "symbol"))):
            touched.setdefault(ep_ids[str(eid)], "the code touched it")
    for e in log.entries:
        for box in e.elements:
            touched.setdefault(box, f"entry {e.id} names it")
    for w in log.waived:
        touched.setdefault(w.id, "waived: the code touched it, the words did not change")
    # RIPPLED: what the change reached through the map's own relations, one hop — from a hit the
    # gate counts. A ripple out of a link that merely drifted (the text moved, nothing changed) or
    # out of a file-resolution hit is the map being walked, not a change arriving.
    rippled: dict[str, str] = {}
    for eid, imp in impacts.items():
        if not isinstance(imp, dict) or imp.get("cause") != "ripple":
            continue
        box = element_of(str(eid))
        if not box or box in touched:
            continue
        origins = [str(v.get("from") or "") for v in (imp.get("via") or []) if isinstance(v, dict)]
        if any(gated_box(o, impacts.get(o)) for o in origins):
            rippled.setdefault(box, _ripple_via(imp))
    pinned_set = set(pinned)
    in_scope: list[Scoped] = []
    carried: list[str] = []
    unvoted: list[str] = []
    skipped_themes: dict[str, int] = {}
    for it in live:
        if no_warrant:
            unvoted.append(it.claim)
            continue
        if it.theme not in voted_themes:
            skipped_themes[it.theme] = skipped_themes.get(it.theme, 0) + 1
            unvoted.append(it.claim)
            continue
        if it.claim not in pinned_set:
            in_scope.append(Scoped(it, "changed"))
            continue
        hit = next((b for b in it.elements if b in touched), None)
        if hit:
            in_scope.append(Scoped(it, "touched", f"{hit}: {touched[hit]}"))
            continue
        hit = next((b for b in it.elements if b in rippled), None)
        if hit:
            in_scope.append(Scoped(it, "rippled", f"{hit} ← {rippled[hit]}"))
            continue
        (carried if it.claim in voted else unvoted).append(it.claim)
    live_set = {it.claim for it in live}
    superseded = [c for c in pinned if c not in live_set]
    if no_warrant:
        notes.append("the map carries no warrant: no pinned worklist with verdicts beside it, so "
                     "there is nothing to carry and no tier to keep parity with. Nothing is "
                     "re-argued; a build's Phase-4 pass is what warrants a map")
    for theme, n in sorted(skipped_themes.items()):
        notes.append(f"{n} {theme} statement(s) stay unvoted: the build voted none of that theme, "
                     f"and an update reads no theme the build did not")
    return Scope(update, log.date, behavioural, live, renames, pinned, in_scope, carried, unvoted,
                 superseded, touched, rippled, notes, no_warrant)


def scope_payload(scope: Scope, batches: list[tuple[str, int]]) -> dict[str, Any]:
    return {
        "format": SCOPE_FORMAT, "update": scope.update, "behavioural": scope.behavioural,
        "counts": {"live": len(scope.live), "in_scope": len(scope.in_scope), **scope.by_reason(),
                   "carried": len(scope.carried), "unvoted": len(scope.unvoted),
                   "superseded": len(scope.superseded), "shifted": len(scope.renames)},
        "by_theme": scope.by_theme(),
        "batches": [{"file": name, "claims": n} for name, n in batches],
        "in_scope": [{"claim": s.item.claim, "theme": s.item.theme, "reason": s.reason,
                      "via": s.via, "elements": list(s.item.elements)} for s in scope.in_scope],
        "superseded": scope.superseded,
        "notes": scope.notes,
    }


def format_scope(scope: Scope, batches: list[tuple[str, int]]) -> str:
    r = scope.by_reason()
    lines = [f"challenge {scope.update} — {len(scope.in_scope)} of {len(scope.live)} statement(s) "
             f"to re-argue: {r['changed']} changed, {r['touched']} on a touched box, "
             f"{r['rippled']} on a box the change reached; {len(scope.carried)} carried with "
             f"their verdict, {len(scope.unvoted)} never voted (unchanged), "
             f"{len(scope.superseded)} superseded"]
    for n in scope.notes:
        lines.append(f"  note: {n}")
    for theme, n in scope.by_theme().items():
        lines.append(f"  {theme}: {n}")
    for name, n in batches:
        lines.append(f"  wrote {name}: {n} claim(s)")
    if not scope.in_scope:
        lines.append("  nothing to challenge: no statement changed, and none sits on a box the "
                     "code touched or the change reached. `changes ground` re-pins and carries.")
    return "\n".join(lines)


# ── carrying verdicts across the change ───────────────────────────────────────────────────────────

class LineMaps:
    """Old `path:line` → new, per file, from git's own line map between the two commits — the same
    mapping the re-anchor step applies to the map's links, applied here to the lines the skeptics
    CITED. Without it every carried verdict in a shifted file reads as drift on the next
    `anchor-drift`, and `fix apply-drift` would move the map's link back to the old line."""

    def __init__(self, repo: Path, pin: str, to: str) -> None:
        self.repo = repo
        self.pin = resolve_ref(repo, pin)
        self.to = resolve_ref(repo, to)
        self.renamed_to = {old: new for new, old in rename_map(repo, self.pin, self.to).items()}
        self.present = tree_paths(repo, self.to)
        self._maps: dict[str, Callable[[int], int | None]] = {}

    def map(self, path: str, line: int) -> tuple[str, int | None] | None:
        """`(new path, new line)`; the line is None when the diff replaced it; the whole answer is
        None when the file is gone."""
        new_path = self.renamed_to.get(path, path)
        if new_path not in self.present:
            return None
        if path not in self._maps:
            hunks = u0_diff(self.repo, self.pin, path, self.to, new_path).hunks
            self._maps[path] = line_mapper(hunks) if hunks else (lambda n: n)
        return new_path, self._maps[path](line)


def shift_evidence(rows: list[dict[str, Any]], maps: LineMaps, log: ChangeLog) -> tuple[int, int]:
    """Move each carried row's `evidence` line with the code. Returns `(moved, stale)`.

    IDEMPOTENT, and it has to be: `ground` is re-run after a crash, or by mistake, and a shift
    that reads a row's current line and pushes it through the diff again moves every carried
    citation twice (measured: 38 of 38 rows on the mcpolis rehearsal). `evidence_at` records the
    commit a row's citation is at; only a row still at this update's from-commit — or with no
    mark, the build's rows — is shifted, and every row is marked at the to-commit after.

    A line the diff replaced, or a file that is gone, cannot be followed. The citation is cut to
    the bare file (`evidence_was` keeps it, `evidence_stale` says which update cut it), because
    `anchor-drift` reads a confirmed row's cited LINE as where the map's link should be, and
    `fix apply-drift` writes it: a dead line left in place moved a correct link back to the line
    the diff had replaced. A bare path carries no line, so it moves nothing."""
    moved = stale = 0
    update = f"{log.from_commit}-{log.to_commit}"
    for row in rows:
        at = row.get("evidence_at")
        if isinstance(at, str) and at and not commit_matches(at, log.from_commit):
            continue                    # already at this update's to-commit
        row["evidence_at"] = log.to_commit
        ev = str(row.get("evidence") or "")
        loc = parse_anchor(ev) if ev else None
        if loc is None or loc.lo is None:
            continue
        hit = maps.map(loc.path, loc.lo)
        new_path, lo = hit if hit else (loc.path, None)
        hi: int | None = lo
        if hit and loc.hi is not None and loc.hi != loc.lo:
            hi_hit = maps.map(loc.path, loc.hi)
            hi = hi_hit[1] if hi_hit else None
        if lo is None or hi is None:
            row.setdefault("evidence_was", ev)
            row["evidence"] = new_path if hit else loc.path
            row["evidence_stale"] = update
            stale += 1
            continue
        new = f"{new_path}:{lo}" + (f"-{hi}" if hi != lo else "")
        if new != ev:
            row.setdefault("evidence_was", ev)
            row["evidence"] = new
            moved += 1
    return moved, stale


def rekey_rows(rows: list[dict[str, Any]], renames: dict[str, str], update: str) -> int:
    """Rename each row's claim across a pure line shift, keeping the text it was cast on."""
    n = 0
    for row in rows:
        claim = row.get("claim")
        if isinstance(claim, str) and claim in renames:
            row.setdefault("claim_was", claim)
            row["claim"] = renames[claim]
            row["rekeyed"] = update
            n += 1
    return n


@dataclass
class Fold:
    """What `changes ground` did, or would do."""
    scope: Scope
    wave: list[Path]
    prior: list[Path]
    wave_rows: list[dict[str, Any]]
    kept_rows: list[dict[str, Any]]
    retired_rows: list[dict[str, Any]]
    wave_gone: list[dict[str, Any]] = field(default_factory=list)   # wave rows on statements a fix removed
    #: Every row this update has retired, across runs: the retired file's rows merged with this
    #: run's. The ledger counts THIS, so a retry after a crash reports what the update retired
    #: and not what one run happened to find still in place.
    retired_all: list[dict[str, Any]] = field(default_factory=list)
    skipped: str = ""                                                 # why nothing was done, when so
    rekeyed: int = 0
    evidence_moved: int = 0
    evidence_stale: int = 0
    emptied: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    record: dict[str, object] = field(default_factory=dict)
    prior_files_rows: dict[Path, tuple[dict[str, Any] | list[Any], list[dict[str, Any]]]] = field(default_factory=dict)


def fold_update(scope: Scope, verify: Path, repo: Path, log: ChangeLog) -> Fold:
    """Sort every verdict row beside the map into the wave's, the kept and the retired, and shift
    what is kept. Pure with respect to the disk: nothing is written here."""
    wave = wave_files(verify, scope.update)
    prior = [f for f in verdict_files(verify) if f not in wave]
    wave_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for f in wave:
        try:
            _p, rows = read_rows(f)
        except (OSError, ValueError) as e:
            errors.append(f"{f.name}: {e}")
            continue
        wave_rows.extend(rows)
    fold = Fold(scope, wave, prior, wave_rows, [], [])
    # EVERY BATCH LANDED, and every in-scope statement has a vote. The barrier `grounding lint
    # --expect` enforces per batch; this is the same question asked of the claims files, because
    # an unattended update that lost a skeptic must refuse here rather than re-pin a hole.
    voted = {str(r.get("claim")) for r in wave_rows if not is_closer_row(r)}
    for claims_file in sorted(verify.glob(f"claims-{scope.update}-*.json")):
        batch = claims_file.stem[len("claims-"):]
        in_batch = batch_claims(claims_file)
        # CLAIMS, not names — `unanswered_batches` above says why, and this was the THIRD copy of
        # the same `startswith`: `verdicts-…-behaviour-10.json` cleared batch `…-behaviour-1`
        # because one name is a prefix of the other. The `missing` check below catches the in-scope
        # case, so only the message was ever wrong, but this is the pattern the module refuses.
        if set(in_batch) & voted:
            continue
        # A batch nobody answered whose statements were all re-issued and voted under a later
        # wave is settled, not missing; `challenge` replaces such a file, and a copy that slipped
        # through must not block `ground` for ever.
        live_claims = {it.claim for it in scope.live}
        if in_batch and all(c in voted or c not in live_claims for c in in_batch):
            continue
        errors.append(f"batch {batch} has no verdicts file beside it — the wave has not landed, "
                      f"or a skeptic returned without writing")
    missing = [c for c in scope.claims_in_scope if c not in voted]
    if missing:
        errors.append(f"{len(missing)} in-scope statement(s) have no verdict from this wave — "
                      f"first: {missing[0][:120]}")
    # A wave verdict on a statement the map no longer makes is the ordinary trace of a fix: the
    # skeptic refuted it, the log was amended, the statement is gone. Those rows retire with the
    # build's. One on a statement the map still makes but the scope does not hold is a skeptic
    # that reworded a claim, and that is refused.
    live_set = {it.claim for it in scope.live}
    orphans = sorted(c for c in voted - set(scope.claims_in_scope) if c in live_set)
    if orphans:
        errors.append(f"{len(orphans)} wave verdict(s) name a statement that is not in scope — a "
                      f"skeptic reworded a claim, or the log changed after `challenge` ran (re-run "
                      f"it). First: {orphans[0][:120]}")
    # SKEPTIC rows only. The closer's appeal on a refutation the fix then removed stays where the
    # closer wrote it: `validate` ties the record's appeal counts to the closer files beside the
    # map, and a record that said `uphold 0` over a file holding two upheld appeals was reported
    # stale on the first real run.
    gone_rows = [r for r in wave_rows if str(r.get("claim")) not in live_set
                 and isinstance(r.get("claim"), str) and not is_closer_row(r)]
    if gone_rows:
        for r in gone_rows:
            r["file"] = "this update's wave"
        fold.wave_gone = gone_rows
        fold.retired_rows.extend(gone_rows)
        fold.wave_rows = [r for r in wave_rows if r not in gone_rows]
    retire = set(scope.superseded) | set(scope.claims_in_scope)
    try:
        maps = LineMaps(repo, log.from_commit, log.to_commit)
    except ImpactError as e:
        errors.append(str(e))
        fold.errors = errors
        return fold
    for f in prior:
        try:
            payload, rows = read_rows(f)
        except (OSError, ValueError) as e:
            errors.append(f"{f.name}: {e}")
            continue
        fold.rekeyed += rekey_rows(rows, scope.renames, scope.update)
        kept = [r for r in rows if str(r.get("claim")) not in retire]
        gone = [r for r in rows if str(r.get("claim")) in retire]
        for r in gone:
            r["file"] = f.name
        moved, stale = shift_evidence(kept, maps, log)
        fold.evidence_moved += moved
        fold.evidence_stale += stale
        fold.kept_rows.extend(kept)
        fold.retired_rows.extend(gone)
        fold.prior_files_rows[f] = (payload, kept)
        if not kept:
            fold.emptied.append(f.name)
    fold.errors = errors
    return fold


def _wave_row(scope: Scope, fold: Fold, note: str) -> dict[str, Any]:
    """One row of `grounding.history` for this update."""
    # EVERYTHING THE WAVE VOTED, including a statement it refuted that the fix then removed from
    # the map: the ledger is the permanent record of what the wave caught, and a row that said
    # `refuted 0` about a wave whose refutation is the reason the map changed would understate it.
    split = split_closer_rows(fold.wave_rows + fold.wave_gone)
    votes: dict[str, list[dict[str, Any]]] = {}
    for r in split.skeptics:
        if isinstance(r.get("claim"), str):
            votes.setdefault(str(r["claim"]), []).append(r)
    buckets = {"confirmed": 0, "refuted": 0, "unverifiable": 0}
    for rows in votes.values():
        buckets[_verdict_bucket(rows)] += 1
    words = [closer_word(r) for r in split.closer]
    r = scope.by_reason()
    return {
        "kind": "update", "at": scope.update, "date": scope.date,
        "challenged": sum(buckets.values()),
        "confirmed": buckets["confirmed"], "refuted": buckets["refuted"],
        "unverifiable": buckets["unverifiable"],
        "carried": len(scope.carried),
        "retired": len({str(x.get("claim")) for x in fold.retired_all}),
        "changed": r["changed"], "touched": r["touched"], "rippled": r["rippled"],
        "closer_upheld": words.count("uphold"), "closer_rejected": words.count("reject"),
        "closer_unsure": words.count("unsure"),
        "skeptics": len(skeptic_labels(split.skeptics)),
        "note": note,
    }


def build_row(prior: dict[str, Any], before_doc: dict[str, Any],
              prior_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The build's own row of the ledger, seeded from the record as the build wrote it — once, the
    first time an update re-measures the map. The counts are the build's pinned counts, which
    after this write no longer appear anywhere else."""
    split = split_closer_rows(prior_rows)
    return {
        "kind": "build", "at": str(before_doc.get("commit") or "").removesuffix("-dirty"),
        "date": str(before_doc.get("built") or before_doc.get("committed") or ""),
        "challenged": int(prior.get("claims_challenged") or 0),
        "confirmed": int(prior.get("claims_confirmed") or 0),
        "refuted": int(prior.get("claims_refuted") or 0),
        "unverifiable": int(prior.get("claims_unverifiable") or 0),
        "carried": 0, "retired": 0, "changed": 0, "touched": 0, "rippled": 0,
        "closer_upheld": int(prior.get("closer_upheld") or 0),
        "closer_rejected": int(prior.get("closer_rejected") or 0),
        "closer_unsure": int(prior.get("closer_unsure") or 0),
        "skeptics": len(skeptic_labels(split.skeptics)),
        "note": str(prior.get("note") or ""),
    }


def challenge_block(scope: Scope, fold: Fold, batches: list[str]) -> dict[str, Any]:
    """What the log says the wave decided — the same facts as the ledger row, in the log's words."""
    row = _wave_row(scope, fold, "")
    row.pop("note", None)
    row.pop("kind", None)
    row.pop("at", None)
    row.pop("date", None)
    return {**row, "superseded": len(scope.superseded), "unvoted": len(scope.unvoted),
            "shifted": len(scope.renames), "batches": batches,
            "disputed": sum(1 for v in closer_ruling(split_closer_rows(fold.wave_rows).closer).values()
                            if v == DISPUTED)}


# ── the verbs ─────────────────────────────────────────────────────────────────────────────────────

def _read_json(path: Path, what: str) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{what} {path}: {e}") from e
    if not isinstance(doc, dict):
        raise ValueError(f"{what} {path}: not an object")
    return doc


def _opt(args: list[str], name: str) -> str | None:
    if name not in args:
        return None
    i = args.index(name)
    if i + 1 >= len(args):
        raise ValueError(f"{name} needs a value")
    value = args[i + 1]
    del args[i:i + 2]
    return value


def _flag(args: list[str], name: str) -> bool:
    if name in args:
        args.remove(name)
        return True
    return False


@dataclass
class Inputs:
    log_path: Path
    log: ChangeLog
    map_path: Path
    map_doc: dict[str, Any]
    before_text: str
    before_doc: dict[str, Any]
    impact: dict[str, Any]
    repo: Path
    verify: Path


def _inputs(rest: list[str]) -> Inputs:
    map_opt, before_opt, touched_opt, repo_opt = (_opt(rest, "--map"), _opt(rest, "--before"),
                                                  _opt(rest, "--touched"), _opt(rest, "--repo"))
    if not (map_opt and before_opt and touched_opt):
        raise ValueError("--map, --before and --touched are all required")
    positional = [a for a in rest if not a.startswith("-")]
    bad = [a for a in rest if a.startswith("-")]
    if bad:
        raise ValueError(f"unknown option '{bad[0]}'")
    if len(positional) != 1:
        raise ValueError("give exactly one log path")
    log_path = Path(positional[0])
    log = load_log(log_path.read_text(encoding="utf-8"))
    map_path = resolve_map_path(map_opt)
    map_doc = _read_json(map_path, "--map")
    before_path = Path(before_opt)
    before_text = before_path.read_text(encoding="utf-8")
    before_doc = _read_json(before_path, "--before")
    impact = _read_json(Path(touched_opt), "--touched")
    repo = Path(repo_opt) if repo_opt else map_path.parent.parent
    verify = map_path.parent / "verify"
    return Inputs(log_path, log, map_path, map_doc, before_text, before_doc, impact, repo, verify)


def run_challenge(inp: Inputs, cap: int, floor: int) -> tuple[Scope, list[tuple[str, int]], Path, str]:
    applied, _done = apply(inp.log, inp.map_doc)
    scope = scope_update(inp.log, inp.before_text, applied, inp.impact, inp.verify, inp.repo)
    applied_path = inp.log_path.with_name(inp.log_path.name[:-len(".json")] + ".applied.json")
    applied_path.write_text(json.dumps(applied, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    batches: list[tuple[str, int]] = []
    inp.verify.mkdir(parents=True, exist_ok=True)
    # A RE-RUN after a wave landed (a refutation amended the log) batches only what no wave of this
    # update has voted yet; an answered batch is never rewritten, an unanswered one is replaced.
    already = wave_voted(inp.verify, scope.update)
    # An unanswered batch from an earlier run is REPLACED: its statements go out again below, under
    # this run's prefix, if they are still in scope. Left in place it would block `ground` for
    # ever ("batch X has no verdicts file") while the very statements it held had come home.
    for stale in unanswered_batches(inp.verify, scope.update):
        stale.unlink()
    prefix = next_prefix(inp.verify, scope.update)
    todo = [s.item for s in scope.in_scope if s.item.claim not in already]
    if already:
        scope.notes.append(f"{len(scope.in_scope) - len(todo)} in-scope statement(s) already have "
                           f"a verdict from this update's earlier wave; {len(todo)} go out now")
    if todo:
        batches = write_theme_batches(todo, inp.verify, cap, floor=floor, prefix=prefix)
    scope_path = inp.log_path.with_name(inp.log_path.name[:-len(".json")] + ".scope.json")
    scope_path.write_text(json.dumps(scope_payload(scope, batches), indent=1, ensure_ascii=False)
                          + "\n", encoding="utf-8")
    return scope, batches, applied_path, prefix


def run_ground(inp: Inputs, note: str, dry_run: bool) -> Fold:
    scope = scope_update(inp.log, inp.before_text, inp.map_doc, inp.impact, inp.verify, inp.repo)
    fold = fold_update(scope, inp.verify, inp.repo, inp.log)
    retired_path = inp.verify / f"retired-{scope.update}.json"
    existing = _retired_rows(retired_path)
    seen = {_row_key(r) for r in existing}
    fold.retired_all = existing + [r for r in fold.retired_rows if _row_key(r) not in seen]
    g = inp.map_doc.get("grounding")
    prior: dict[str, Any] = g if isinstance(g, dict) else {}
    recorded = any(prior.get(k) for k in ("claims_total", "claims_challenged"))
    if scope.no_warrant:
        # The map says it was challenged and nothing beside it can show a vote: the warrant files
        # are missing, not absent — refuse rather than rewrite the record down to zero and call
        # that measured. A map with no record at all has nothing to ground, and says so.
        if recorded:
            fold.errors = [f"the map records {prior.get('claims_challenged')} challenged "
                           f"statement(s) but no pinned worklist with verdicts sits beside it under "
                           f"{inp.verify}: the warrant files are missing (they are committed with "
                           f"the map). Restore them, or run a build's Phase-4 pass; nothing was "
                           f"written"]
        else:
            fold.skipped = ("the map carries no warrant — no record, no pinned worklist, no "
                            "verdicts — so there is nothing to carry and nothing to measure. "
                            "Nothing was written; a build's Phase-4 pass is what warrants a map")
        return fold
    if fold.errors:
        return fold
    live = [it.claim for it in scope.live]
    all_rows = fold.kept_rows + fold.wave_rows
    # A dry run may have no note yet — it prints the facts the note is written from — and a
    # partial surface (a build that voted part of its worklist) refuses a record with no note.
    record, errors = build_record(live, all_rows, note or ("dry run" if dry_run else ""),
                                  live_claims=live, partial=bool(scope.unvoted))
    if note:
        # Against the WAVE's rows, and against a record without `claims_added_since`: after a
        # re-pin that count is zero by construction, and a note that says "24 new statements" is
        # telling the truth about the update, not contradicting the record.
        checked = {k: v for k, v in record.items() if k != "claims_added_since"}
        faults = _note_contradictions(note, fold.wave_rows + fold.wave_gone, checked, live)
        errors = list(errors) + [f"the `--note-file` contradicts this wave's own numbers. {f}"
                                 for f in faults]
    if errors:
        fold.errors = errors
        fold.record = record
        return fold
    history = [h for h in (prior.get("history") or []) if isinstance(h, dict)]
    if not history and recorded:
        # The build's rows are the ones this update carries plus the ones it retired — read from
        # what the fold holds, never from the files, which a retry finds already rewritten.
        history.append(build_row(prior, inp.before_doc, fold.kept_rows + fold.retired_all))
    # ONE ROW PER UPDATE. A re-run replaces its own row rather than appending a phantom wave.
    history = [h for h in history if not (h.get("kind") == "update" and h.get("at") == scope.update)]
    history.append(_wave_row(scope, fold, note))
    record["history"] = history
    fold.record = record
    if dry_run:
        return fold
    # WRITE, in the order that leaves the least behind if interrupted: the retired rows first (a
    # copy), then the prior files, the pin, the map, the log. Every step is safe to repeat: the
    # retired file is merged, the shift is marked per row, the pin is measured against the list
    # the update replaced, the ledger keeps one row per update.
    if fold.retired_all:
        retired_path.write_text(json.dumps({"format": RETIRED_FORMAT, "update": scope.update,
                                            "rows": fold.retired_all}, indent=1,
                                           ensure_ascii=False) + "\n", encoding="utf-8")
    for f, (payload, kept) in fold.prior_files_rows.items():
        if not kept:
            f.unlink()
            continue
        out: Any = {**payload, "grounding": kept} if isinstance(payload, dict) else kept
        f.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    pin = inp.verify / WORKLIST
    if pin.is_file() and not grounded_already(inp.verify, inp.log):
        old_pin = inp.verify / f"worklist-{inp.log.from_commit[:7]}.json"
        if not old_pin.exists():
            shutil.copy(pin, old_pin)
    payload = worklist_payload([], scope.live)
    payload["pinned_by"] = scope.update
    pin.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    inp.map_doc["grounding"] = record
    inp.map_path.write_text(json.dumps(inp.map_doc, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    batches = [f.stem[len("claims-"):] for f in sorted(inp.verify.glob(f"claims-{scope.update}-*.json"))]
    inp.log.challenge = challenge_block(scope, fold, batches)
    inp.log_path.write_text(dump_log(inp.log), encoding="utf-8")
    return fold


def _retired_rows(path: Path) -> list[dict[str, Any]]:
    """The rows an earlier run of this update already retired, or none."""
    if not path.is_file():
        return []
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in (old.get("rows") or []) if isinstance(r, dict)] if isinstance(old, dict) else []


def _row_key(r: dict[str, Any]) -> tuple[str, str, str, str]:
    """What makes two retired rows the same row: the same vote by the same skeptic from the same
    file. `grounded`/`verdict` spelled as text so a closer row and a skeptic row never collide."""
    return (str(r.get("claim")), str(r.get("skeptic")), str(r.get("file")),
            str(r.get("grounded", r.get("verdict"))))


def wave_facts(scope: Scope, fold: Fold, record: dict[str, object]) -> str:
    """THE NUMBERS THE UPDATE'S NOTE WILL CITE, computed over the WAVE and then the map. The
    build's `NOTE FACTS` block mixes the two when handed an update — its `superseded` is zero by
    construction after a re-pin, and its confirmed count is the map's beside the wave's rows —
    so an update gets its own block, with the map-wide line said as such."""
    rows = split_closer_rows(fold.wave_rows + fold.wave_gone)
    claimed = [r for r in rows.skeptics if r.get("claim")]
    voted = {str(r["claim"]) for r in claimed}
    redundant = max(0, len(claimed) - len(voted))
    labels = skeptic_labels(rows.skeptics)
    multi, verdict_dis, anchor_dis = multi_vote_agreement(rows.skeptics)
    by_claim: dict[str, list[dict[str, Any]]] = {}
    for r in claimed:
        by_claim.setdefault(str(r["claim"]), []).append(r)
    tied = sum(1 for rs in by_claim.values()
               if sum(1 for r in rs if r.get("grounded") is True)
               == sum(1 for r in rs if r.get("grounded") is False) > 0)
    w = _wave_row(scope, fold, "")
    sup = set(scope.superseded)
    sup_confirmed = len({str(r.get("claim")) for r in fold.retired_all
                         if str(r.get("claim")) in sup and r.get("grounded") is True})
    r_ = scope.by_reason()
    lines = ["  WAVE FACTS — quote these, do not retype them from an earlier run:",
             f"    verdict rows {len(rows.skeptics)} over {len(voted)} distinct statement(s) — "
             f"{REDUNDANT_PHRASE.format(n=redundant)}",
             f"    distinct skeptic labels {len(labels)} (a label is not an agent: one agent may "
             f"carry several batches)",
             f"    confirmed {w['confirmed']} · refuted {w['refuted']} · unverifiable "
             f"{w['unverifiable']} · tied {tied}",
             f"    multi-voted statements {multi} · verdict disagreements {verdict_dis} · "
             f"evidence-anchor disagreements {anchor_dis} (unanimity is only a fact about the "
             f"multi-voted ones)"]
    if rows.closer:
        words = [closer_word(r) for r in rows.closer]
        lines.append(f"    closer appeal rows {len(rows.closer)} — uphold {words.count('uphold')} · "
                     f"reject {words.count('reject')} · unsure {words.count('unsure')} (an appeal "
                     f"is not a vote: none of the counts above moved)")
    lines += [f"    in scope {len(scope.in_scope)} ({r_['changed']} changed · {r_['touched']} on a "
              f"touched box · {r_['rippled']} on a box the change reached) · carried "
              f"{len(scope.carried)} · never voted {len(scope.unvoted)} · re-keyed across a line "
              f"shift {len(scope.renames)}",
              f"    superseded {len(scope.superseded)}, of which {sup_confirmed} had been CONFIRMED "
              f"— each is a settled verdict this update overrode, and a note that does not say so "
              f"hides it; retired verdict rows {len(fold.retired_all)}",
              f"  MAP-WIDE, after this update: {record.get('claims_challenged')} of "
              f"{record.get('claims_total')} statement(s) carry a verdict — "
              f"{record.get('claims_confirmed')} confirmed, {record.get('claims_refuted')} refuted, "
              f"{record.get('claims_unverifiable')} unverifiable"]
    return "\n".join(lines)


def format_fold(fold: Fold, inp: Inputs, dry_run: bool) -> str:
    s = fold.scope
    rec = fold.record
    if fold.skipped:
        return f"ground {s.update} — {fold.skipped}"
    wave = _wave_row(s, fold, "")
    lines = [f"ground {s.update}{' (dry run — nothing written)' if dry_run else ''} — "
             f"{wave['challenged']} statement(s) re-argued: {wave['confirmed']} confirmed, "
             f"{wave['refuted']} refuted, {wave['unverifiable']} unverifiable; "
             f"{len(s.carried)} carried, {wave['retired']} retired, {len(s.unvoted)} never voted"]
    for n in s.notes:
        lines.append(f"  note: {n}")
    if fold.rekeyed or fold.evidence_moved or fold.evidence_stale:
        lines.append(f"  carried rows: {fold.rekeyed} re-keyed across a line shift, "
                     f"{fold.evidence_moved} evidence line(s) moved with the code, "
                     f"{fold.evidence_stale} evidence line(s) the diff replaced (cut to the file, "
                     f"marked stale)")
    for name in fold.emptied:
        lines.append(f"  {name}: every row retired, file removed (its rows are in "
                     f"retired-{s.update}.json)")
    if rec:
        hist = rec.get("history")
        lines.append(f"  record: {rec.get('claims_challenged')} of {rec.get('claims_total')} live "
                     f"statement(s) carry a verdict — {rec.get('claims_confirmed')} confirmed, "
                     f"{rec.get('claims_refuted')} refuted, {rec.get('claims_unverifiable')} "
                     f"unverifiable; {len(hist) if isinstance(hist, list) else 0} wave(s) in the "
                     f"ledger")
        lines.append(wave_facts(s, fold, rec))
    note = str(rec.get("note") or "") if rec else ""
    if note and note != "dry run":
        lines.append(f"  note: {len(note)} characters, checked against this wave's numbers — accepted")
    if not dry_run and not fold.errors:
        lines.append(f"  wrote {inp.map_path.name} (grounding), {inp.verify / WORKLIST} (re-pinned), "
                     f"{inp.log_path.name} (challenge block)")
        lines.append("  next: coyomap grounding refutations --map <map> --verdicts "
                     ".coyomap/verify/verdicts-*.json .coyomap/verify/closer-*.json")
    return "\n".join(lines)


def main(verb: str, rest: list[str]) -> int:
    rest = list(rest)
    if "-h" in rest or "--help" in rest:
        print(USAGE)
        return 0
    try:
        as_json = _flag(rest, "--json")
        dry_run = _flag(rest, "--dry-run")
        cap_opt, floor_opt, note_file = _opt(rest, "--cap"), _opt(rest, "--floor"), _opt(rest, "--note-file")
        inp = _inputs(rest)
    except (OSError, ValueError, ModelError) as e:
        print(f"ERROR: {e}\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    try:
        if verb == "challenge":
            cap = int(cap_opt) if cap_opt else DEFAULT_CAP
            floor = int(floor_opt) if floor_opt else DEFAULT_FLOOR
            scope, batches, applied_path, prefix = run_challenge(inp, cap, floor)
            if as_json:
                print(json.dumps({**scope_payload(scope, batches), "applied": str(applied_path),
                                  "prefix": prefix}, indent=1, ensure_ascii=False))
            else:
                print(format_scope(scope, batches))
                print(f"  applied copy: {applied_path} — the «MAP» every skeptic reads")
                if batches:
                    print(f"  next: coyomap contract skeptic --from-batches {inp.verify} "
                          f"--prefix {prefix} --fill <slots.json> --out-dir <scratch>/briefs "
                          f"--votes security=3  (this run's prefix; an earlier wave's batches are "
                          f"answered and stay)")
            return 0
        note = ""
        if note_file:
            note = Path(note_file).read_text(encoding="utf-8").strip()
            if not note:
                print(f"ERROR: --note-file {note_file} is empty", file=sys.stderr)
                return 2
        elif not dry_run:
            print("ERROR: ground needs --note-file <path> (the wave's note, written from the "
                  "NOTE FACTS a --dry-run prints) or --dry-run", file=sys.stderr)
            return 2
        fold = run_ground(inp, note, dry_run)
        if fold.errors:
            for e in fold.errors:
                print(f"ERROR: {e}", file=sys.stderr)
            if fold.record:
                print(wave_facts(fold.scope, fold, fold.record), file=sys.stderr)
            print("REFUSED: the record would misstate what was challenged; nothing was written.",
                  file=sys.stderr)
            return 1
        if as_json:
            print(json.dumps({"update": fold.scope.update, "dry_run": dry_run,
                              "wave": _wave_row(fold.scope, fold, note),
                              "record": fold.record}, indent=1, ensure_ascii=False))
        else:
            print(format_fold(fold, inp, dry_run))
        return 0
    except (OSError, ValueError, ModelError, ImpactError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
