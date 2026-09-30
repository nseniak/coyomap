#!/usr/bin/env python3
"""`coyomap grounding write` — derive the map's `grounding` record from the verdict files.

The four counts are the one thing `validate` BLOCKS on (`confirmed + refuted + unverifiable ==
challenged`), and until now nothing produced them: every build hand-wrote the block from a throwaway
tally. On a live build that record shipped asserting work that had not happened — "Roughly 20 further
anchors were confirmed-but-drifted **and corrected**", written 18 seconds before `anchor-drift
--verdicts` first ran (which found 23, not the guessed 20) and 29 before `fix apply-drift`, the tool
that actually does the correcting, ran at all — plus an
internal contradiction ("three skeptics split … two confirmed and two refuted" is four skeptics).
A hand-written honesty record is a contradiction in terms.

THE SNAPSHOT PROBLEM, which is why `--worklist` is required rather than re-derived. The normal build
order is: audit → skeptics → apply the refutations → the map shrinks. So by the time the record is
written, a fresh `audit` no longer matches the verdicts: on a live map the worklist had fallen to 404
while 408 claims had been challenged. Recomputing `claims_total` from the current map therefore emits
`claims_challenged (408) exceeds claims_total (404)` — a BLOCKING map, produced by the command meant
to stop the record lying. Counting only verdicts that still match the live worklist is worse: the
refuted claims are exactly the ones the fixes deleted, so it yields `confirmed 396 / refuted 0`, a
record asserting nothing was ever refuted. Both were reproduced. The worklist must be PINNED — the
`audit --json` captured before the fixes — and this command refuses anything else.

Stdlib-only (the cli.py firewall).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from coyomap import subverb_help
from coyomap.anchor_drift import load_verdicts
from coyomap.audit_model import (
    ClaimTarget,
    WorkItem,
    claim_digest,
    l2_worklist_model,
    pinned_claims,
    pinned_tier,
    resolve_claim,
    worklist_payload,
)
from coyomap.provenance import SESSION_ENV, session_agent_transcripts
from coyomap.model import ModelError, ProjectModel, load_model, resolve_map_path

USAGE = """usage: coyomap grounding lint   --verdicts <raw.json>... [--agent-transcripts <dir>] [--expect <batch,…>]
       coyomap grounding write  --worklist <audit.json> --verdicts <raw.json>... \\
                               [--out <fragment.json>] [--json] [--partial]
                               [--note <text> | --note-file <path> | --keep-note]
                               [--note-cites-other-runs] [--map <project-map.json>]
       coyomap grounding report --worklist <audit.json> --verdicts <raw.json>... [--map <map>]
                               [--agent-transcripts <dir>] [--json]
       coyomap grounding by-element --worklist <audit.json> --verdicts <raw.json>... \\
                               --map <project-map.json> [--kind <kind>] [--json]

`by-element` says what the pass did to each ELEMENT, beside the confidence its author typed.
Nothing in the tooling ever writes `confidence`, so an element challenged three times and confirmed
unanimously still reads exactly as the harvesting agent left it. This resolves every pinned claim
back onto the element that makes it and prints both, flagging each element whose stated label the
votes do not support. Derived on every run from the worklist and the verdicts; it stores nothing.
`--kind` narrows to one of rule_site / description / edge / cadence / lifecycle / security.

`refutations` is the GATE half, and needs no worklist: it walks the verdicts against the live map
and exits 1 when a claim the skeptics REFUTED is still in it, word for word. Every refutation is
supposed to be reconciled, and a reconciled claim no longer resolves, so a survivor is one nobody
acted on. It also lists the elements whose stated confidence the votes do not support (advisory).

`report` prints WHICH claims were refuted, tied, unverifiable or unvoted — the reconcile worklist
`write` computes and then reduces to four counts. A TIE is listed apart from a stated
`unverifiable`: the first needs a human decision, the second is a skeptic saying the code cannot
answer, and the counts cannot tell them apart.

It also collects the two channels in which an agent tells the LEAD something no verdict carries,
because a claim it upheld is still a claim it had a reservation about:
  NOTES TO THE LEAD ON UPHELD CLAIMS  a `grounded: true` row whose note speaks to you. Confirmed
                                      reads as "nothing to do", so the row reaches nothing else.
  FINDINGS THE AGENTS SENT UP         the closing section of each agent's final message
                                      (`--agent-transcripts`, or this session's own, as `lint`
                                      finds them). A harvest or trace agent files no verdict, so
                                      this is its only channel.
Both are PHRASE MATCHES over prose and both print their own coverage. Without
`--agent-transcripts` and outside a session, the second says NOT READ rather than zero.

`report` ends on the `NOTE FACTS` block, the numbers the closing note must quote — the same block
`write` prints. It used to be printed only by `write`, which is the run that REFUSES a wrong note,
so the first note of every build was written from figures computed by hand.

Derive the `grounding` block from the skeptics' verdict files and the PINNED audit worklist they
were drawn from (`coyomap audit <map> --json > audit.json`, captured BEFORE the refutations were
applied). Writes a `{"grounding": {...}}` build fragment, or prints it with --json.

It REFUSES rather than guess:
  - a verdict whose claim is not in the pinned worklist  -> the worklist is the wrong snapshot
  - a worklist claim with no verdict at all              -> the pass did not challenge everything
  - a --note whose numbers contradict this record        -> the note was written against another run
Both of the first two are the "gate did not run" failure wearing a different hat.

`--note-cites-other-runs` is the escape for the third: it says the figures in the note are about
OTHER runs, or are scoped to one theme rather than the whole pass. The refusal then becomes a
warning. Pass it to `coyomap ship` too, which forwards it — without that, the refusal stops the
prescribed closing sequence at step 6 of 12.

The note: `--note` takes it inline, `--note-file` reads it from a file, `--keep-note` reuses the
note already in `--out`. The last two exist because a re-run (the ordinary case — the record is
re-measured after a late fix) had to re-supply the whole note, and a live build did that through a
nested `$(python -c …)` re-extracting ~1900 characters back through the shell. It survived; a note
containing a quote or a backtick would not have.

--partial: record a DELIBERATE partial pass — the second refusal is lifted, `claims_total` keeps the
FULL pinned surface and `claims_challenged` says how far you got. Needs a --note naming what was
prioritized, and is refused when the pass turns out to be complete after all. Do NOT instead shrink
the --worklist file to what you challenged: that makes `claims_total` the reduced size, so the real
surface survives only in prose and a 319-of-1608 pass ships looking complete."""


#: The three words a CLOSER row may carry, from `method/templates/closer-contract.md`.
_CLOSER_VERDICTS = ("uphold", "reject", "unsure")

#: What two appeals that disagree amount to. PARENTHESISED so it cannot be read as a vocabulary
#: word and copied back into a file: the first version of this used the bare word `conflict`,
#: printed it to the operator as `closer said CONFLICT`, and an agent echoing it into a verdict
#: file would have had the row read as a skeptic VOTE — erasing the refutation it was about.
DISPUTED = "(appeals disagree)"


def is_closer_row(row: dict) -> bool:
    """Does this row carry a `verdict` field AT ALL?

    THE FIELD, NOT ITS VALUE, and this is a fail-closed decision. Keyed on the value, a row whose
    word is not one of the three fell through to the SKEPTIC side and its `grounded: true` became a
    vote: one such row turns a single-skeptic refutation into a tie, `grounding refutations` exits 0
    saying "No refuted claim survives", and `grounding write` records `claims_refuted 0`. Every gate
    green, a refutation erased, from one misspelt word — `rejected` for `reject`. Before the closer
    files were globbed into the closing sequence that was harmless; now every grounding step reads
    them, so a bad word went from inert to destructive.

    So the field decides WHICH SIDE the row is on and the word decides what it SAYS. A row with an
    unreadable word is an appeal that settles nothing — it never votes, the refutation it is about
    keeps standing, and `closer_faults` names it.

    THE CLOSER IS NOT A THIRD SKEPTIC. Counted as a vote, an `uphold` would double a refutation's
    weight and a `reject` would add a confirming vote to it. It is an appeal: it settles a
    refutation the skeptics already cast, and it changes no count of what the skeptics decided."""
    return bool(str(row.get("verdict", "")).strip())


def closer_word(row: dict) -> str:
    """The closer's verdict word if it is one of the three, else "" — never a guess."""
    word = str(row.get("verdict", "")).strip().lower()
    return word if word in _CLOSER_VERDICTS else ""


def closer_faults(rows: list[dict]) -> list[str]:
    """Appeal rows whose word nothing can read — the shape that used to become a vote.

    ON THE ROW, not on the file name. The first version of this check keyed on a file called
    `closer-*.json`, so `closer.json` or `appeals-a.json` was unchecked; and it lived in
    `grounding lint`, which `ship` never runs and which `method.md` schedules at COLLECTION, before
    the closer is dispatched — on the reviewed build it ran over 38 verdict files and 0 closer
    files. A guard nothing reaches is not a guard."""
    bad = sorted({str(r.get("verdict", "")).strip()
                  for r in rows if is_closer_row(r) and not closer_word(r)})
    if not bad:
        return []
    echoed = [w for w in bad if w.lower() in ("conflict", DISPUTED)]
    return [f"{len(bad)} unreadable closer verdict word(s): {', '.join(repr(w) for w in bad)}. "
            f"The vocabulary is {' / '.join(_CLOSER_VERDICTS)} — `uphold` the refutation stands, "
            f"`reject` the skeptic misread the code, `unsure` you could not settle it. A row with "
            f"any other word settles nothing, so the refutation it is about KEEPS BLOCKING; fix the "
            f"word or drop the row."
            + (" `conflict` is not an input word: it is what an older build PRINTED for a claim "
               "whose two appeals disagreed, and it was never something to write into a file."
               if echoed else "")]


@dataclass(frozen=True)
class VerdictRows:
    """One pile of verdict rows, told apart: the skeptics' votes and the closer's appeals.

    NAMED rather than a pair, because both halves are lists of the same thing and a swap would read
    perfectly at every call site while inverting the meaning of every count below it."""
    skeptics: list[dict]
    closer: list[dict]


def split_closer_rows(rows: list[dict]) -> VerdictRows:
    """The skeptics' votes and the closer's appeals, never mixed.

    Split HERE rather than at the command line, so every caller is right: `finalize` runs the
    refutation leg itself, `ship` hands the same file list to eight steps, and a split done once in
    `main` would leave each of those counting closer rows as votes."""
    closer = [r for r in rows if is_closer_row(r)]
    if not closer:
        return VerdictRows(skeptics=rows, closer=[])
    return VerdictRows(skeptics=[r for r in rows if not is_closer_row(r)], closer=closer)


def closer_ruling(rows: list[dict]) -> dict[str, str]:
    """claim -> the closer's own word for it: `uphold`, `reject`, `unsure` — or `DISPUTED`.

    THE WORD, NOT `grounded`. Reading the boolean instead let a row saying `{"verdict": "unsure",
    "grounded": true}` clear the refutation gate while the record beside it counted an `unsure` and
    the report printed "'uphold' and 'unsure' still need you". Two fields, one meaning, and the two
    readers disagreed with nothing noticing. `verdict` is the field the contract makes the closer
    write in its own vocabulary; `grounded` is its translation for the tally, and a translation is
    the half that can be wrong.

    A row whose word is unreadable rules on nothing — see `is_closer_row` for why that is the only
    safe answer. `DISPUTED` when two readable appeals on ONE claim disagree: the first version let
    the last row win and called it "the later wave", which is false — the winner is whichever file
    sorted last, and closer files are named by random agent id, so which appeal survived was
    chance. A dispute settles nothing, so the refutation keeps blocking and the lead is told."""
    out: dict[str, str] = {}
    for r in rows:
        claim, word = r.get("claim"), closer_word(r)
        if not isinstance(claim, str) or not claim or not word:
            continue
        out[claim] = word if out.get(claim, word) == word else DISPUTED
    return out


def _verdict_bucket(rows: list[dict]) -> str:
    """One claim's outcome from its votes: strict majority confirmed, else refuted, else unverifiable.

    `unverifiable` is the honest third outcome and it is NOT a rounding bucket: a claim reaches it
    only when a skeptic said so. Folding it into either of the others is what makes the record lie —
    and on a live build it read 0 of 408 because every batch prompt ended by telling the skeptics to
    "default to refuted on doubt", so the third verdict was never reachable in practice."""
    grounded = sum(1 for r in rows if r.get("grounded") is True)
    refuted = sum(1 for r in rows if r.get("grounded") is False)
    unver = sum(1 for r in rows if isinstance(r.get("grounded"), str)
                and str(r.get("grounded")).lower() == "unverifiable")
    if grounded * 2 > len(rows):
        return "confirmed"
    if refuted * 2 > len(rows):
        return "refuted"
    if unver:
        return "unverifiable"
    # A tie with no explicit `unverifiable` vote is not settled by the code either — say so rather
    # than silently crediting one side, which is the whole failure this record exists to prevent.
    #
    # It stays `unverifiable` rather than a bucket of its own, and a 2026-08-29 retro finding that
    # said otherwise was withdrawn after being checked: over the SAME 32 verdict files the record
    # and `grounding report` agree exactly (8 refuted, 0 tied, 0 unverifiable). The finding compared
    # a report over 38 files with a record built from 32. What is true is smaller and is the reason
    # this comment exists: `format_report` prints `tied` where the record says `unverifiable`, so
    # the two vocabularies differ for one claim shape. Splitting them would hide an unresolved tie
    # from every reader who checks `claims_unverifiable`, which is worse than the mismatch.
    return "unverifiable"


def multi_vote_agreement(rows: list[dict]) -> tuple[int, int, int]:
    """`(multi-voted claims, verdict disagreements, evidence-anchor disagreements)`.

    A claim voted by more than one skeptic is the only place unanimity is a MEANINGFUL word, and it
    is the word notes reach for: "the three security voters agreed on every anchor". Nothing
    computed it, so the sentence was written from impression. On the 2026-09-01 argus map the note
    said ZERO anchor disagreements and 2 of 80 triple-voted claims disagree.

    Two different disagreements, deliberately counted apart:

    * **verdict** — the voters did not return the same `grounded` value. The record's buckets fold
      these into a majority and the disagreement disappears.
    * **evidence anchor** — the voters agreed on the verdict but cited DIFFERENT `path:line`s.
      Harmless on its face and the reason to count it: it is the one signal that two readers who
      agree were not looking at the same thing.

    Rows carrying no `evidence` are skipped for the anchor test rather than counted as agreeing —
    an absent citation is not a matching one.

    SKEPTIC ROWS ONLY. A closer's appeal on a refuted claim is a different reader answering a
    different question, so counting it here would turn every closed refutation into a "multi-voted
    claim" whose voters disagree — and a note that truthfully says "0 verdict disagreements" would
    then be refused."""
    rows = split_closer_rows(rows).skeptics
    votes: dict[str, list[dict]] = {}
    for r in rows:
        claim = r.get("claim")
        if isinstance(claim, str):
            votes.setdefault(claim, []).append(r)
    multi = 0
    verdict_disagree = 0
    anchor_disagree = 0
    for claim_rows in votes.values():
        voters = {str(r.get("skeptic", "")) for r in claim_rows if r.get("skeptic")}
        # `or`, not `and`. Voters are read OFF the rows, so `len(rows) < 2` already implies
        # `len(voters) < 2` and the `and` form reduced to "fewer than two rows" — counting a
        # single skeptic's RE-VOTE of one claim, and a pair of rows carrying no `skeptic` field at
        # all, as multi-voted. Both then produced anchor "disagreements" between one reader and
        # itself. Unanimity is a fact about two or more READERS; two rows is not the same thing.
        if len(claim_rows) < 2 or len(voters) < 2:
            continue
        multi += 1
        grounded = {str(r.get("grounded")).lower() for r in claim_rows}
        if len(grounded) > 1:
            verdict_disagree += 1
        anchors = {str(r.get("evidence", "")).strip() for r in claim_rows
                   if str(r.get("evidence", "")).strip()}
        if len(anchors) > 1:
            anchor_disagree += 1
    return multi, verdict_disagree, anchor_disagree


def skeptic_labels(rows: list[dict]) -> list[str]:
    """The distinct `skeptic` values across the verdict rows, sorted.

    ONE derivation, because `NOTE FACTS` prints this number and the note gate now checks a note
    against it: two derivations of one count is how a gate ends up disagreeing with the line it
    tells the author to quote. A LABEL is not an agent — one agent may carry several batches — so
    every message about it says label.

    SKEPTIC ROWS ONLY: a closer signs its file with its own agent id, and counting that would make
    the wave look one reader larger than it was — in the note, and in the gate that now checks it."""
    rows = split_closer_rows(rows).skeptics
    return sorted({str(r.get("skeptic", "")) for r in rows if r.get("skeptic")})


def note_facts_block(worklist_claims: list[str], rows: list[dict], record: dict[str, object],
                     live_claims: "list[str] | None") -> str:
    """THE NUMBERS A NOTE WILL CITE, COMPUTED, so nobody retypes one from an earlier view.

    `--note` is free prose in a permanent record and in the commit message, and nothing checked it.
    One shipped note said "Eighteen fresh-context skeptics" about a build that dispatched 17 and
    produced 20 verdict labels: the 18 was read off a `grounding lint` line printed while one
    verdict file was still being written, then carried forward. The same note said "Four superseded
    claims had been CONFIRMED" where the report counts 11, leaving seven deliberate overrides of
    settled claims undisclosed. Every number was available at the moment the note was written.

    A FUNCTION rather than an inline print, because `_note_contradictions` now REFUSES rather than
    warns: the operator whose note is rejected needs these numbers in the same breath, and they
    used to be printed only on the success path, after the refusal had already returned."""
    buckets = json.loads(format_report(worklist_claims, rows, as_json=True, live_claims=live_claims))
    sup_confirmed = sum(1 for r in buckets["superseded"] if r.get("verdict") == "confirmed")
    # THE APPEALS ARE NOT VERDICT ROWS. Counted in, three closer rows turned "1202 verdict rows,
    # 256 redundant" into "1205, 259" — and the gate below then refused a note quoting the true
    # figures. They are stated on their own line instead, because a note that never mentions the
    # appeal hides the one reader who overturned a skeptic.
    appeals = split_closer_rows(rows).closer
    rows = split_closer_rows(rows).skeptics
    labels = skeptic_labels(rows)
    # REDUNDANT ROWS, spelled out, because the note has to state it and the arithmetic is the kind
    # nobody re-does. A three-voted theme produces three rows per claim; "136 redundant rows" was
    # published in a shipped map and in the operator report for a pass whose four security batches
    # held 136 CLAIMS and 408 rows — 272 redundant. The note's author had the row count here and the
    # claim count nowhere, so it quoted the number it could see.
    # Both sides count the SAME rows: a row with no claim is excluded from each, or it would inflate
    # `redundant` by one while belonging to neither side of the subtraction.
    claimed_rows = [r for r in rows if r.get("claim")]
    voted = len({str(r.get("claim")) for r in claimed_rows})
    redundant = max(0, len(claimed_rows) - voted)
    # The multi-vote agreement, for the same reason the redundant count is here: notes assert
    # unanimity ("the three security voters agreed on every anchor") and nothing computed it, so the
    # sentence came from impression and was wrong on a shipped map.
    multi, verdict_dis, anchor_dis = multi_vote_agreement(rows)
    return (f"  NOTE FACTS — quote these, do not retype them from an earlier run:\n"
            f"    verdict rows {len(rows)} over {voted} distinct claim(s) — "
            f"{REDUNDANT_PHRASE.format(n=redundant)}\n"
            f"    distinct skeptic labels {len(labels)} "
            f"(a label is not an agent: one agent may carry several batches)\n"
            f"    confirmed {record['claims_confirmed']} · refuted {record['claims_refuted']} · "
            f"unverifiable {record['claims_unverifiable']} · tied {len(buckets['tied'])}\n"
            f"    multi-voted claims {multi} · verdict disagreements {verdict_dis} · "
            f"evidence-anchor disagreements {anchor_dis} "
            f"(unanimity is only a fact about the multi-voted ones)"
            + (f"\n    closer appeal rows {len(appeals)} — "
               + " · ".join(f"{w} {sum(1 for r in appeals if closer_word(r) == w)}"
                            for w in _CLOSER_VERDICTS)
               + f" · {sum(1 for v in closer_ruling(appeals).values() if v == DISPUTED)} "
                 f"claim(s) disputed"
               + " (an appeal is not a vote: none of the counts above moved)" if appeals else "")
            + (f"\n    superseded {record['claims_superseded']}, of which {sup_confirmed} "
               f"had been CONFIRMED — each is a settled verdict the build overrode, and a note "
               f"that does not say so hides it" if live_claims is not None else ""))


#: THE WORDING THE NOTE FACTS BLOCK PRESCRIBES for the redundant-row count, in one place, so the
#: sentence a note is told to quote and the sentence the gate reads back cannot drift apart.
REDUNDANT_PHRASE = "{n} row(s) that added no new claim (usually a re-vote)"

#: The written-out numbers a note may use, to their value. Notes are prose and prose spells small
#: numbers; the shipped note that got the skeptic count wrong opened "Twenty-one", so the tens and
#: their hyphenated compounds are here too.
_WORD_UNITS = {"no": 0, "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
               "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
               "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
               "seventeen": 17, "eighteen": 18, "nineteen": 19}
_WORD_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
              "seventy": 70, "eighty": 80, "ninety": 90}

def _number_pattern(include_zero: bool = True) -> str:
    """ONE spelling of "a number a note states", shared by every check below, so a form one of them
    reads and another does not cannot become the difference between a caught error and a shipped
    one.

    Compounds FIRST, and the longer word before the shorter: `re` takes the first alternative that
    matches at a position, so a bare `twenty` ahead of `twenty-one` reads "Twenty-one skeptics" as
    twenty, and `nine` ahead of `nineteen` reads nineteen as nine.

    `include_zero=False` drops `no` and `zero`, for a noun a note QUANTIFIES rather than counts:
    "so no skeptic saw them" says none of them did, not that the pass had none."""
    units = [u for u in _WORD_UNITS if include_zero or _WORD_UNITS[u]]
    nonzero = "|".join(u for u in _WORD_UNITS if _WORD_UNITS[u])
    return "|".join([r"\d[\d,]*",
                     *(f"{t}[- ](?:{nonzero})" for t in _WORD_TENS),
                     *_WORD_TENS,
                     *sorted(units, key=len, reverse=True)])


_NUMBER = _number_pattern()
_NUMBER_COUNTED = _number_pattern(include_zero=False)


def _count_of(text: str) -> int | None:
    """The value of a number a note states — `14`, `fourteen`, `Twenty-one` — or None."""
    raw = text.strip().lower().replace(",", "")
    if raw[:1].isdigit():
        return int(raw)
    if raw in _WORD_UNITS:
        return _WORD_UNITS[raw]
    if raw in _WORD_TENS:
        return _WORD_TENS[raw]
    tens, _sep, unit = raw.replace(" ", "-").partition("-")
    if tens in _WORD_TENS and unit in _WORD_UNITS:
        return _WORD_TENS[tens] + _WORD_UNITS[unit]
    return None


#: A note stating the redundant-row count — in the words a build invents ("161 redundant rows"), or
#: in `REDUNDANT_PHRASE`'s own.
#:
#: READING THE PRESCRIBED WORDING IS THE POINT of the second alternative. `_ADDED_SINCE_IN_NOTE`
#: below saw `no new claim` inside it, read `no` as "0 claims added since the pin", and refused a
#: note whose record said 14 — so `ship` died at step 4 of 13 on the 2026-09-13 reminderrepo build
#: for quoting the line the tool had just told it to quote, and the run that followed passed on a
#: pure reword that changed no number. The phrase is not merely EXEMPTED here: recognising it as
#: the redundant count means a mis-quote of it ("128 row(s) that added no new claim" on a pass with
#: 256) is now caught, where before nothing read it at all.
_REDUNDANT_IN_NOTE = re.compile(
    rf"({_NUMBER})\s+(?:redundant\s+rows?"
    rf"|(?:verdict\s+)?rows?(?:\(s\))?\s+that\s+added\s+no\s+new\s+claims?)", re.I)

#: The note stating how many claims arrived AFTER the worklist was pinned. Third arithmetic shape,
#: same failure as the other two: the 2026-09-02 mcpolis note said "9 post-pin claims" where its own
#: record — and its own NEXT SENTENCE — said 13. Words and digits both, since notes write either.
_ADDED_SINCE_IN_NOTE = re.compile(
    rf"\b({_NUMBER})\s+(?:new\s+|post-pin\s+|added\s+)claims?\b", re.I)

#: The note stating how many SKEPTICS the pass had — the HEADLINE count, and only that.
#:
#: The defect: the 2026-09-13 reminderrepo note opened "Twenty-one fresh-context skeptics
#: challenged the pinned worklist" and said "Distinct skeptic labels 38" three sentences later. 38
#: is right three ways (38 dispatches, 38 verdict files, 38 distinct `skeptic` values in the rows);
#: 21 was the first wave's dispatch, re-pasted. The count was already PRINTED in `NOTE FACTS` and
#: nothing read it back.
#:
#: Tight on purpose. The number must sit against the word `skeptic`, with at most one hyphenated
#: adjective between them, and `skeptic` must not be the adjective of another noun — a looser gap
#: read "38 of the 1,202 rows came from skeptics" as a stated 1,202, and without the lookahead
#: "21 skeptic teams were dispatched" reads as 21 skeptics.
_SKEPTICS_IN_NOTE = re.compile(
    rf"\b(?:({_NUMBER_COUNTED})\s+"
    rf"(?:[a-z]+-[a-z]+\s+|distinct\s+|independent\s+|different\s+|separate\s+)?"
    rf"skeptics?\b(?!\s+(?:teams?|batch|batches|waves?|groups?|files?|briefs?|slots?))"
    rf"|(?:distinct\s+)?skeptic\s+labels?\s*[:=]?\s+({_NUMBER_COUNTED})\b)", re.I)

#: Text that is somebody else's words, not the note's own claim: a quotation. `The brief said
#: "dispatch twelve skeptics"` is a true sentence about an instruction, and reading the 12 in it as
#: this pass's headline refused an honest note. Double quotes and backticks only — an apostrophe
#: opens a span in "the lead's" that never closes.
_QUOTED = re.compile(r"\"[^\"\n]*\"|\u201c[^\u201d\n]*\u201d|`[^`\n]*`")

#: A magnitude this reader cannot compose. "One hundred and five fresh-context skeptics" matched
#: `five` and read as 5 — a WRONG read, which is worse than no read: it can refuse a truthful note
#: or pass a false one. A number reached through one of these words is not read at all.
_UNCOMPOSED = re.compile(r"\b(?:hundred|thousand|million)\b[\s\w]{0,12}$", re.I)


def _headline_skeptic_count(note: str) -> tuple[int, str] | None:
    """The FIRST count of skeptics the note states — the headline, and nothing else.

    ONE STATEMENT, and the first one, with no scope filtering of any kind. Three rules were tried on
    the four live notes:

    * **every stated count must agree** caught the reminderrepo defect and REFUSED argus, whose
      per-batch sentences ("both batches got three independent skeptics") are true beside a correct
      opening total.
    * **some stated count must agree** passes reminderrepo, whose note states the right 38 three
      sentences after the wrong 21. That is the defect, cleared by the defect's own note.
    * **the first unscoped count**, which this was, is defeated by one word: "Twenty-one
      fresh-context skeptics EACH challenged the pinned worklist" skips as scoped and falls through
      to the correct 38. `per agent`, `in two waves`, `across both batches` and `one team of` do the
      same. It was also blind on mcpolis, whose only count sentence says "across 19 batches", and
      off-target on coyomap, whose true opening says "in two waves".

    The first count, flat, is right on all four: argus 18 = 18, mcpolis 38 = 38, coyomap 25 = 25,
    reminderrepo 21 vs 38 REFUSED — and no word added to the headline sentence can dodge it,
    because there is nothing left to dodge.

    WHAT IT WILL REFUSE, and this is a decision rather than an oversight: a note that opens on
    ANOTHER run's figure ("the previous build used twelve skeptics") before stating its own. No
    rule over prose can tell that sentence from the reminderrepo one — both put a wrong number
    first and the right number later — so one of the two must be accepted, and the refusal is the
    one with a one-line remedy: state this pass's own count first. The message says so."""
    text = note or ""
    quoted = [m.span() for m in _QUOTED.finditer(text)]
    for m in _SKEPTICS_IN_NOTE.finditer(text):
        if any(a <= m.start() and m.end() <= b for a, b in quoted):
            continue
        if _UNCOMPOSED.search(text[max(0, m.start() - 30):m.start()]):
            continue
        value = _count_of(m.group(1) or m.group(2) or "")
        if value is not None:
            return value, m.group(0)
    return None


#: A note stating a disagreement COUNT: "0 verdict disagreements", "zero evidence-anchor
#: disagreements", "anchor disagreements: 2".
_AGREEMENT_IN_NOTE = re.compile(
    r"\b(?:(\d[\d,]*|no|zero)\s+(verdict|evidence[- ]anchor|anchor)\s+disagreements?"
    r"|(verdict|evidence[- ]anchor|anchor)\s+disagreements?\s*[:=]\s*(\d[\d,]*))", re.I)

#: A note ASSERTING unanimity in words rather than a number — which is how the defect actually
#: shipped: "the three security voters agreed on every anchor". A count regex could not see it, and
#: a build that phrases its assurance this way is making exactly the claim that was wrong.
#: Read as "0 disagreements of BOTH kinds", which is what the sentence means.
_UNANIMITY_IN_NOTE = re.compile(
    r"\b(?:agreed\s+on\s+every\s+anchor"
    r"|unanimous(?:ly)?(?:\s+\w+){0,3}\s+(?:anchor|evidence|verdict)"
    r"|(?:cited|read)\s+the\s+same\s+(?:anchor|evidence|line)"
    r"|(?:every|all)\s+(?:multi|triple|double)-voted\s+claims?\s+agreed)", re.I)
_COVERAGE_IN_NOTE = re.compile(r"(\d[\d,]*)\s+of\s+(?:those\s+|the\s+)?(\d[\d,]*)\s+"
                               r"(?:carry|have)\s+no\s+verdict", re.I)


def _note_contradictions(note: str, rows: list[dict], record: dict[str, object],
                         live_claims: "list[str] | None") -> list[str]:
    """Numbers the note states that its OWN record contradicts.

    `--note` is free prose in a permanent record and in the commit message, and nothing checked it.
    Two shapes recur and both shipped on the 2026-08-29 mcpolis map:

    * **the redundant-row count.** "483 verdict rows over 161 redundant rows" — 161 is the CLAIM
      count; 483 - 161 = 322 rows were redundant. The identical error ("136 redundant rows" for 272)
      was found by the previous retrospective, marked fixed, and recurred, because the fix printed
      the number in `NOTE FACTS` without refusing a note that disagrees with it.
    * **the shipped-map coverage pair.** The note said "16 of those 696 carry no verdict" while its
      own record said 22 of 702 — it had been written against an earlier pass and re-pasted.

    Only stated shapes, and only when the note states them: a general prose checker is not
    possible and a guessy one would refuse honest notes. Every fix is one word."""
    problems: list[str] = []
    # The closer's appeals are not verdict rows and never were: counting them makes this check
    # demand a redundant-row figure that `NOTE FACTS` does not print.
    rows = split_closer_rows(rows).skeptics
    claimed_rows = [r for r in rows if r.get("claim")]
    redundant = max(0, len(claimed_rows) - len({str(r.get("claim")) for r in claimed_rows}))
    # ANY occurrence may match, and one that does clears the note. A good note cites other builds'
    # figures for comparison — the real one said "over 160, 40 and 100 redundant rows" about three
    # earlier passes — and refusing those would refuse the most honest notes written.
    redundant_spans = [m.span() for m in _REDUNDANT_IN_NOTE.finditer(note or "")]
    # Digits OR words, and `10 verdict rows that added no new claim` as well as `10 row(s) …`:
    # the skip below keys on THIS match, so a form it misses re-opens the bug it was added for —
    # this codebase's own notes spell small numbers out.
    stated_redundant = [v for v in (_count_of(m.group(1))
                                    for m in _REDUNDANT_IN_NOTE.finditer(note or ""))
                        if v is not None]
    if stated_redundant and redundant not in stated_redundant:
        quoted = ", ".join(f"'{n} redundant rows'" for n in stated_redundant)
        problems.append(
            f"the note states {quoted} and this pass has {redundant} — none of them. A three-voted "
            f"theme produces one row per voter, so the redundant count is rows minus DISTINCT "
            f"claims ({len(claimed_rows)} - {len(claimed_rows) - redundant}). Quote the "
            f"`NOTE FACTS` line rather than the claim count; other builds' figures are fine "
            f"alongside this pass's.")
    live_done = record.get("claims_live_challenged")
    if live_claims is not None and isinstance(live_done, int):
        live_total = len(set(live_claims))
        pairs = [(int(m.group(1).replace(",", "")), int(m.group(2).replace(",", "")), m.group(0))
                 for m in _COVERAGE_IN_NOTE.finditer(note or "")]
        if pairs and (live_total - live_done, live_total) not in [(a, b) for a, b, _ in pairs]:
            quoted = ", ".join(f"'{t}'" for _a, _b, t in pairs)
            problems.append(
                f"the note states {quoted} and this record says {live_total - live_done} of "
                f"{live_total} — none of them. The note was written against an earlier pass; "
                f"requote it from this run.")
    # THE POST-PIN COUNT, the third arithmetic shape. `claims_added_since` is the claims the map
    # gained after the skeptics were given their worklist, so it is exactly the number a reader
    # needs to know how much of the shipped map went unchallenged — and a note that understates it
    # understates that. Blocking with the other two: it is a stated number about THIS pass, and the
    # record beside it holds the right one.
    added = record.get("claims_added_since")
    if isinstance(added, int):
        stated_added = [
            (_count_of(m.group(1)), m.group(0))
            for m in _ADDED_SINCE_IN_NOTE.finditer(note or "")
            # NOT inside the redundant-row sentence. `REDUNDANT_PHRASE` ends "…added no new
            # claim", and reading that `no` as "0 claims since the pin" refused a note whose
            # record said 14 — the tool rejecting its own prescribed wording. `_REDUNDANT_IN_NOTE`
            # reads that span as what it is, so it is spoken for and this check steps over it.
            if not any(s < m.end() and m.start() < e for s, e in redundant_spans)]
        values = [v for v, _t in stated_added if v is not None]
        if values and added not in values:
            quoted = ", ".join(f"'{t}'" for _v, t in stated_added)
            problems.append(
                f"the note states {quoted} and this record says {added} claim(s) added since the "
                f"pin. Those are the claims no skeptic saw, so understating them understates how "
                f"much of the shipped map went unchallenged; requote it from this run.")
    # THE SKEPTIC COUNT, the fourth arithmetic shape: the note's HEADLINE figure against the
    # labels. See `_headline_skeptic_count` for why one statement and not all of them.
    labels = skeptic_labels(rows)
    headline = _headline_skeptic_count(note)
    if headline is not None and headline[0] != len(labels):
        problems.append(
            f"the note opens on '{headline[1]}' and this pass has {len(labels)} distinct skeptic "
            f"label(s). A LABEL is not an agent — one agent may carry several batches — so the "
            f"number to quote is the `distinct skeptic labels` line of `NOTE FACTS`, not how many "
            f"agents were dispatched. Only the FIRST count in the note is read, so a per-batch or "
            f"per-theme sentence later on needs no change — and a figure about ANOTHER run belongs "
            f"after this pass's own, or behind `--note-cites-other-runs`.")
    return problems


def _agreement_contradictions(note: str, rows: list[dict]) -> list[str]:
    """The multi-vote agreement the note asserts, against what this pass actually did.

    ADVISORY, deliberately, where the two shapes above are blocking. The difference is what a regex
    can know. "483 verdict rows over 161 redundant rows" is arithmetic: the number is stated, it is
    about this pass, and it is wrong. An agreement claim is an ASSURANCE, and it shipped in words —
    "the three security voters agreed on every anchor" — on a map where 2 of 80 triple-voted claims
    disagree. Reading that reliably is a language problem, not a pattern problem: the count form
    misses every word form, the word form guesses at scope, and both fire on an honest sentence
    about an earlier run or one theme. Blocking on a guess would refuse correct notes, which is a
    worse failure than the one being caught — the `NOTE FACTS` line already prints the true triple
    right beside the author.

    So this WARNS, loudly, with the real numbers. What is blocking is the arithmetic."""
    multi, verdict_dis, anchor_dis = multi_vote_agreement(rows)
    text = note or ""
    stated: dict[str, list[tuple[int, str]]] = {"verdict": [], "anchor": []}
    for m in _AGREEMENT_IN_NOTE.finditer(text):
        raw = (m.group(1) or m.group(4) or "").lower()
        which_raw = (m.group(2) or m.group(3) or "").lower()
        value = 0 if raw in ("no", "zero") else int(raw.replace(",", ""))
        which = "verdict" if which_raw == "verdict" else "anchor"
        stated[which].append((value, m.group(0)))
    # A worded assurance means zero of BOTH kinds, which is what the sentence claims.
    for m in _UNANIMITY_IN_NOTE.finditer(text):
        stated["verdict"].append((0, m.group(0)))
        stated["anchor"].append((0, m.group(0)))
    out: list[str] = []
    for which, actual in (("verdict", verdict_dis), ("anchor", anchor_dis)):
        claimed = stated[which]
        # ANY occurrence clears it, exactly as the redundant-row check allows: a note that compares
        # this pass with an earlier one legitimately states both numbers.
        if claimed and actual not in [v for v, _t in claimed]:
            quoted = ", ".join(f"'{t}'" for _v, t in dict.fromkeys(claimed))
            label = "verdict" if which == "verdict" else "evidence-anchor"
            out.append(
                f"the note states {quoted} and this pass has {actual} {label} disagreement(s). "
                f"Over {multi} multi-voted claim(s): {verdict_dis} where the voters returned "
                f"different verdicts, {anchor_dis} where they agreed but cited different anchors. "
                f"If the note is about another run or one theme, it is fine as it stands; if it is "
                f"about THIS pass, quote the `NOTE FACTS` line.")
    return out


def unvoted_reason(unvoted: int, added_since: int) -> str:
    """WHY the shipped map's `unvoted` claims carry no verdict — the sentence after "N do NOT".

    A COMPLETE pass leaves only claims minted or reworded after the pin in that number, and three
    sentences in this codebase said exactly that, always. Under `--partial` the unvoted PINNED
    claims are the bulk of it: the first behavioural build shipped 965 claims with no verdict,
    949 of them pinned from the start and never challenged, and its gate block called all 965
    "minted after the worklist was pinned". `added_since` is clamped to `unvoted`: a record whose
    delta exceeds its unvoted count is malformed, and `validate` owns that complaint."""
    added = max(0, min(added_since, unvoted))
    never = unvoted - added
    if never == 0:
        return "They were minted or reworded after the worklist was pinned, so no skeptic saw them."
    if added == 0:
        return "They were pinned and never challenged."
    return (f"{never} were pinned and never challenged; {added} were minted or reworded after the "
            f"worklist was pinned, so no skeptic saw them.")


def live_claims_digest(claims: "Iterable[str]") -> str:
    """sha256 over the sorted, DE-DUPLICATED claim set — the shipped map's claim surface, as one
    value a later gate can recompute.

    This is the only part of the record that is proof rather than explanation. The count-based
    fields cannot catch a 1-for-1 rewrite (k claims replaced by k others leaves every size
    unchanged), and a reconcile that rewrites a claim IS 1-for-1 by construction — 4 of the 6
    superseded claims on the build this was written for were exactly that shape. De-duplicated
    because `build_record` de-duplicates the pinned side, and two sides counted by different rules
    is how a check ends up measuring the rule instead of the map.

    The hashing itself is `audit_model.claim_digest`, so `validate` and `changes check` recompute
    the very same value without importing this module."""
    return claim_digest(claims)


#: Where the first pin is kept once a second wave extends `worklist.json`, the way an update keeps
#: the list it replaced as `worklist-<from>.json`.
FIRST_PIN = "worklist-wave1.json"


def second_wave(pinned: list[str], grounding_rows: list[dict], live: list[str]) -> list[str]:
    """Live claims the pin never held that a skeptic voted on — a SECOND WAVE — in live order.

    `write` refused every verdict outside the pin as a sign of the wrong snapshot. That is right for
    a claim the map no longer makes, and wrong for one it makes and the pin never held: a text
    corrected after the vote, an edge written after it. On the 2026-09-30 mcpolis build 68 such
    claims shipped with no verdict, 6 of them re-worded sites of access rules, because the only
    route that worked (a hand-merged worklist) was described nowhere."""
    pin = set(pinned)
    voted = {r.get("claim") for r in split_closer_rows(grounding_rows).skeptics}
    return [c for c in dict.fromkeys(live) if c in voted and c not in pin]


def repin_second_wave(worklist_path: Path, wave: list[WorkItem]) -> Path:
    """Append a second wave's claims to the pinned worklist, keeping the first pin beside it as
    `worklist-wave1.json` — the re-pin an update's `changes ground` does, for a build's own second
    wave. Idempotent: on a re-run the wave is already pinned and `second_wave` finds nothing."""
    first = worklist_path.with_name(FIRST_PIN)
    if not first.exists():
        shutil.copy(worklist_path, first)
    payload: object = json.loads(worklist_path.read_text(encoding="utf-8"))
    added = worklist_payload([], wave)["worklist"]
    assert isinstance(added, list)
    out: object
    if isinstance(payload, list):
        out = [*payload, *added]
    elif isinstance(payload, dict):
        held = payload.get("worklist")
        items: list[object] = [*(held if isinstance(held, list) else []), *added]
        counts: dict[str, int] = {}
        for i in items:
            theme = i.get("theme") if isinstance(i, dict) else None
            if isinstance(theme, str):
                counts[theme] = counts.get(theme, 0) + 1
        before = payload.get("second_wave")
        out = {**payload, "worklist": items, "theme_counts": counts,
               "second_wave": (before if isinstance(before, int) else 0) + len(wave)}
    else:
        raise ValueError(f"{worklist_path} is not a pinned worklist")
    worklist_path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return first


def build_record(worklist_claims: list[str], grounding_rows: list[dict],
                 note: str = "", live_claims: "list[str] | None" = None,
                 partial: bool = False,
                 ) -> tuple[dict[str, object], list[str]]:
    """The `grounding` block, plus the refusals that must stop it being written.

    `live_claims` is the worklist of the ASSEMBLED map, when the caller passed `--map`. It is what
    lets the record state how the pinned surface and the shipped one differ, instead of leaving a
    build to argue with a staleness advisory that had no legal answer.

    `partial` is the operator asserting that challenging only part of the worklist was DELIBERATE.
    The counts never needed it — `claims_challenged` has always subtracted the unvoted — so what it
    buys is the distinction the tool cannot make on its own: a ranked worklist worked top-down until
    the budget ran out looks exactly like a batch of skeptics that died on the way home.

    THE CLOSER NEVER VOTES HERE. Its rows are dropped before the tally, so the five counts keep the
    meaning they have always had — what the SKEPTICS decided about the pinned worklist, the
    arithmetic `validate` blocks on. An appeal that moved `claims_refuted` would rewrite that
    meaning inside a permanent record, retroactively, for every reader of every past map."""
    _split = split_closer_rows(grounding_rows)
    grounding_rows, _closer_rows = _split.skeptics, _split.closer
    votes: dict[str, list[dict]] = {}
    for r in grounding_rows:
        claim = r.get("claim")
        if isinstance(claim, str):
            votes.setdefault(claim, []).append(r)
    # De-duplicate while preserving order: a claim repeated in the worklist must not be counted twice.
    seen_claims: set[str] = set()
    worklist_claims = [c for c in worklist_claims
                       if not (c in seen_claims or seen_claims.add(c))]
    pinned = set(worklist_claims)
    errors: list[str] = []
    bad = sorted({str(r.get("grounded")) for rows in votes.values() for r in rows
                  if not (r.get("grounded") is True or r.get("grounded") is False
                          or (isinstance(r.get("grounded"), str)
                              and str(r.get("grounded")).lower() == "unverifiable"))})
    if bad:
        errors.append(
            f"{len(bad)} unrecognised `grounded` value(s) in the verdict files: {', '.join(bad)} — "
            f"the vocabulary is true / false / \"unverifiable\". Bucketing an unknown value would fold "
            f"it into a verdict nobody gave, which is the failure this record exists to prevent.")
    orphans = sorted(c for c in votes if c not in pinned)
    if orphans:
        errors.append(
            f"{len(orphans)} verdict claim(s) are not in the pinned worklist — the --worklist file is "
            f"a DIFFERENT snapshot from the one the skeptics were given (it was probably re-derived "
            f"after the refutations were applied). Capture `audit --json` BEFORE the fixes. "
            + ("A verdict on a claim the shipped map makes and the pin never held is a second "
               "wave, and `write --map` folds it into the pin; these are in neither. "
               if live_claims is not None else
               "Pass `--map`: a verdict on a claim the shipped map makes and the pin never held is "
               "a second wave, which `write --map` folds into the pin. ")
            + f"First: {orphans[0][:100]}")
    # An unvoted claim has TWO causes that look identical from here: a pass that deliberately
    # challenged the top slice of a ranked worklist, and a pass whose skeptics silently died or that
    # was handed the wrong snapshot. The second is the failure this whole record exists to catch, so
    # the refusal stands by default and `partial` is the operator saying which one it is.
    #
    # It is NOT an accuracy problem: `claims_challenged` below already subtracts the unvoted, so the
    # counts were always right for a partial pass — the refusal guarded intent, not arithmetic. The
    # documented workaround (cut the pinned worklist down to what you challenged) is strictly worse:
    # it makes `claims_total` the reduced size, so the real surface survives only in free-text prose
    # where no gate can read it, and a 319-of-1608 pass ships looking like a complete pass over a
    # small map.
    unvoted = [c for c in worklist_claims if c not in votes]
    if unvoted and not partial:
        errors.append(
            f"{len(unvoted)} worklist claim(s) have NO verdict — this pass did not challenge the "
            f"whole surface. Ground them, or pass `--partial` to record a DELIBERATE partial pass "
            f"(`claims_total` then keeps the full surface and `claims_challenged` states how far you "
            f"got; a `--note` saying what was prioritized is required). First: {unvoted[0][:100]}")
    if partial and not unvoted:
        errors.append(
            "`--partial` was passed but every worklist claim has a verdict — this was a COMPLETE "
            "pass. Drop the flag: a record that calls itself partial when it is not understates a "
            "finished verification, and the next reader cannot tell which it was.")
    if partial and not note.strip():
        errors.append(
            "`--partial` needs a `--note` saying which claims were prioritized and out of what — "
            "the counts alone say how many were challenged, never why those ones, and an unexplained "
            "partial pass is indistinguishable from an abandoned one.")
    counts = {"confirmed": 0, "refuted": 0, "unverifiable": 0}
    for claim in worklist_claims:
        rows = votes.get(claim)
        if rows:
            counts[_verdict_bucket(rows)] += 1
    record: dict[str, object] = {
        "claims_total": len(worklist_claims),
        "claims_challenged": len(worklist_claims) - len(unvoted),
        "claims_confirmed": counts["confirmed"],
        "claims_refuted": counts["refuted"],
        "claims_unverifiable": counts["unverifiable"],
    }
    if live_claims is not None:
        live = set(live_claims)
        # SIZES, and explicitly not a proof: `total - superseded + added_since == live` closes for
        # every COMPLETE pass, because the orphan and unvoted refusals force `votes` == `pinned`
        # there. Under `--partial` the unvoted refusal is lifted, so the identity stops being a
        # tautology and starts measuring something. Either way it tells a reader WHAT moved; the
        # digest is what tells a gate whether anything moved.
        record["claims_superseded"] = len(pinned - live)
        record["claims_added_since"] = len(live - pinned)
        # COVERAGE OF THE SHIPPED MAP, which none of the counts above states. Every one of them is
        # pinned to the worklist the skeptics were given, so a build that rewords a claim after the
        # vote keeps `claims_challenged == claims_total` while the map it ships carries claims
        # nobody challenged. One did: 209 of 209 in the record, in the rendered view and in the
        # commit message, against 199 live claims with a verdict. Measured against `votes`, not
        # derived, because the derivation `total - superseded` only holds when every pinned claim
        # was voted — which `--partial` exists to allow it not to be.
        record["claims_live_challenged"] = sum(1 for c in live if c in votes)
        record["live_claims_digest"] = live_claims_digest(live)
    # THE APPEAL, RECORDED. Written unconditionally, zeros included, because "no appeal was heard"
    # is an answer a reader of the shipped map is entitled to and an absent key is not one. Beside
    # the five counts and never inside them: a closer rejection is why the map legitimately keeps a
    # claim its own skeptics refuted, and until this field existed that fact lived only in chat.
    # ROWS for the three — a claim re-heard in a second wave is two rows on purpose, and
    # `validate`'s tie to the closer's own files counts them the same way.
    words = [closer_word(r) for r in _closer_rows]
    record["closer_upheld"] = words.count("uphold")
    record["closer_rejected"] = words.count("reject")
    record["closer_unsure"] = words.count("unsure")
    # ...and CLAIMS for the fourth, because a disagreement is a fact about a claim and every row
    # count reads it as two settlements.
    record["closer_disputed"] = sum(1 for w in closer_ruling(_closer_rows).values() if w == DISPUTED)
    if note:
        record["note"] = note
    return record, errors


#: The phrases that mark a verdict note as addressed to the LEAD rather than to the vote. A
#: HEURISTIC, listed in the output beside its own numbers, because a regex over prose both
#: over-fires and under-fires and a reader must be able to see which words it looked for.
_LEAD_NOTE = re.compile(r"note for the lead|worth (?:flagging|noting)|caveat", re.I)

#: The same phrases in the words a reader recognises, for the coverage sentence.
_LEAD_NOTE_PHRASES = ('"note for the lead"', '"worth flagging"', '"worth noting"', '"caveat"')


@dataclass(frozen=True)
class LeadNote:
    """One UPHELD verdict row whose note says something to the lead.

    `said` is the note from the start of the SENTENCE the phrase sits in, to the end. These notes
    run to 1,200 characters and put the message last — "…the call happens but its result is
    discarded before the insert" — so truncating from the front shows the reasoning and throws away
    the finding. From the sentence rather than from the phrase, because a phrase can land mid-clause
    and cutting there printed the bare "separately at line 100"."""
    claim: str
    skeptic: str
    evidence: str
    note: str
    said: str


def lead_notes(rows: list[dict]) -> tuple[list[LeadNote], int, int]:
    """(the rows a skeptic upheld AND wrote to the lead about, upheld rows with a note, upheld rows).

    THE ONE VERDICT SHAPE THAT REACHED NOTHING. A refuted claim lands in the report's REFUTED list,
    a tie in TIED, an unverifiable one in UNVERIFIABLE — and a CONFIRMED claim lands nowhere,
    because confirmed reads as "nothing to do". On the 2026-09-13 reminderrepo build `security-1-c`
    CONFIRMED business rule BR5 and added that `app-routing.module.ts:15` registers a second,
    unguarded route to the same screen. That is true, no verb collected it, and the shipped map
    still says the screen opens only for a signed-in person, `access: true`, confidence `verified`,
    with that line named nowhere in it. 47 of that build's 1,182 upheld rows carry a note like it —
    measured over the phrase list below, which is the only number that means anything here: a looser
    list gave 49 and a tighter one 42 over the same files.

    The second and third numbers are the DENOMINATORS the caller must print: this is a phrase match
    over prose, so the only honest thing to say is how much of the pile it read.

    SKEPTIC ROWS ONLY. A closer's note is addressed to the lead by design and has a section of its
    own; listing it here too would say it twice and inflate the denominator with rows that are not
    votes."""
    rows = split_closer_rows(rows).skeptics
    upheld = [r for r in rows if r.get("grounded") is True]
    with_note = [r for r in upheld if str(r.get("note") or "").strip()]
    out: list[LeadNote] = []
    for r in with_note:
        note = str(r.get("note") or "").strip()
        m = _LEAD_NOTE.search(note)
        if not m:
            continue
        # Back up to the sentence the phrase sits in. A file name ends in `.ts:25`, never in `. `,
        # so the space is what keeps `app.controller.ts` from reading as a sentence end.
        cut = 0
        for sep in (". ", "; ", "\n", "! ", "? "):
            at = note.rfind(sep, 0, m.start())
            if at != -1:
                cut = max(cut, at + len(sep))
        out.append(LeadNote(claim=str(r.get("claim") or ""), skeptic=str(r.get("skeptic") or ""),
                            evidence=str(r.get("evidence") or ""), note=note,
                            said=note[cut:].strip()))
    return out, len(with_note), len(upheld)


#: A markdown heading in an agent's closing message: `## Findings the lead should know`, and the
#: numbered form this codebase's own house style produces, `## [4] Things the lead should know`.
_SECTION_HEADING = re.compile(
    r"^(?P<hashes>\#{1,6})[ \t]+(?:\[[\w.]+\][ \t]*)?(?P<title>[^\n]*?)[ \t]*$", re.M)

#: Which of those headings is ADDRESSED TO THE LEAD. Read off the real convention: across the 70
#: agents of the 2026-09-13 reminderrepo build the closing sections were spelled "Findings the lead
#: should know", "Findings worth the lead's attention", "Other findings worth passing on", "Notes
#: worth passing on", "Other findings worth keeping", "Things the lead should know", "Three caveats
#: the lead should weigh", "One caveat for you", "Two defects worth a second look" — nine wordings
#: for one thing. A HEURISTIC over prose, and the output says so beside its own numbers.
_LEAD_SECTION_TITLE = re.compile(
    r"\blead\b|\bcaveats?\b"
    r"|worth\s+(?:passing\s+on|keeping|reporting|noting|flagging|knowing|a\s+second\s+look"
    r"|your\s+\w+)", re.I)

_BULLET = re.compile(r"^[ \t]*(?:[-*•]|\d+[.)])[ \t]+(?P<text>.+?)[ \t]*$", re.M)


@dataclass(frozen=True)
class AgentFinding:
    """One section of one build agent's closing message, addressed to the lead."""
    agent: str          # the transcript's file stem, so the reader can open it
    task: str           # the agent's own job description, from its sibling `.meta.json`
    heading: str
    items: tuple[str, ...]


def _final_message(path: Path) -> str:
    """The text of the LAST assistant message in one agent transcript — what the agent handed up."""
    last = ""
    for rec in _records(path):
        msg = rec.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        blocks = msg.get("content")
        if not isinstance(blocks, list):
            continue
        text = "\n".join(str(b.get("text") or "") for b in blocks
                         if isinstance(b, dict) and b.get("type") == "text")
        if text.strip():
            last = text
    return last


def _agent_task(path: Path) -> str:
    """What this agent was sent to do, from the `<stem>.meta.json` the harness writes beside it.

    Without it every row reads `agent-a5626735a73ea9b47`, which tells a reader nothing about whose
    finding it is — "Harvest Angular pages and routes" does."""
    meta = path.with_suffix(".meta.json")
    try:
        doc = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(doc.get("description") or "") if isinstance(doc, dict) else ""


def _section_body(text: str, heading: "re.Match[str]") -> str:
    """The lines under one heading, down to the next heading at the same level or shallower."""
    depth = len(heading.group("hashes"))
    for nxt in _SECTION_HEADING.finditer(text, heading.end()):
        if len(nxt.group("hashes")) <= depth:
            return text[heading.end():nxt.start()]
    return text[heading.end():]


def agent_findings(agent_dir: Path) -> tuple[list[AgentFinding], int, int]:
    """(sections agents addressed to the lead, agents with a final message, transcripts read).

    THE CHANNEL NOTHING READS. A build agent hands up a fragment and, when it is a skeptic, a
    verdict file. Anything it noticed that fits in neither goes into the closing message it writes
    to the lead — and that message is read once, by a lead 400 turns from the end, and then never
    again. On the 2026-09-13 reminderrepo build 20 of 70 agents ended with such a section, 21
    sections in all (a hand sweep of the same files found 13, reading fewer of the nine wordings). The
    strongest of them came from a harvest agent, which has no verdict file at all: three Angular
    paths declared twice with different guard sets, and a top-level route carrying no guard. The
    three anchors it named appear ZERO times in the shipped map.

    Collecting from the verdict rows alone would have seen 3 of those 13 — the skeptics — which is
    why this reads the transcripts and `lead_notes` reads the rows. Two populations, both reported,
    neither a superset of the other.

    The second and third numbers are the DENOMINATORS the caller must print: this is a heading match
    over prose, so the only honest thing to say is how much of the pile it read."""
    files = _agent_transcript_files(agent_dir)
    out: list[AgentFinding] = []
    with_final = 0
    for f in files:
        final = _final_message(f)
        if not final.strip():
            continue
        with_final += 1
        task = _agent_task(f)
        for m in _SECTION_HEADING.finditer(final):
            title = m.group("title")
            if not title or not _LEAD_SECTION_TITLE.search(title):
                continue
            body = _section_body(final, m)
            items = tuple(b.group("text") for b in _BULLET.finditer(body))
            if not items:
                # A section written as a paragraph or a TABLE still counts — its lines ARE the
                # finding, and dropping it because nobody typed a dash would lose the whole section
                # silently. A table's `|---|---|` rule carries nothing and is dropped.
                items = tuple(ln.strip() for ln in body.splitlines()
                              if ln.strip() and set(ln.strip()) - set("|-: "))
            if items:
                out.append(AgentFinding(agent=f.stem, task=task, heading=title, items=items))
    return out, with_final, len(files)


def format_report(worklist_claims: list[str], grounding_rows: list[dict],
                  as_json: bool = False, live_claims: list[str] | None = None,
                  agent_dir: Path | None = None) -> str:
    """WHICH claims landed in each bucket — the half `write` computes and then throws away.

    `write` resolves every claim to confirmed / refuted / unverifiable and emits only the four
    counts, so a build that needs the actual worklist (every refutation has to be reconciled, and a
    tie has to be adjudicated) has nothing to read. A live build hand-wrote a 12-line vote
    aggregator one turn after `write` had parsed the same 14 files.

    A TIE is called out separately from a stated `unverifiable`. `_verdict_bucket` files both under
    `unverifiable`, which is right for the count but wrong for the reader: a tie is two skeptics
    disagreeing and needs a human decision, while an `unverifiable` verdict is a skeptic saying the
    code cannot answer. A live build's grounding note described its four unverifiables as one kind
    when two were the other."""
    # THE CLOSER IS NOT A VOTER — see `is_closer_row`. Its rows are pulled out before anything is
    # bucketed, and printed in a section of their own below.
    split = split_closer_rows(grounding_rows)
    grounding_rows, closer_rows = split.skeptics, split.closer
    votes: dict[str, list[dict]] = {}
    for r in grounding_rows:
        claim = r.get("claim")
        if isinstance(claim, str):
            votes.setdefault(claim, []).append(r)
    # De-duplicated exactly as `build_record` does (and for the same reason). Without it this
    # report listed a repeated claim twice and counted it twice, so it disagreed with the record it
    # exists to explain — first by listing FEWER than the record counted, then, once that was fixed,
    # by listing MORE.
    _seen: set[str] = set()
    pin_claims = [c for c in worklist_claims if not (c in _seen or _seen.add(c))]
    # A SECOND WAVE is bucketed with the pin, exactly as `write --map` will fold it: its refutations
    # have to be reconciled from this report like the first wave's.
    waved = second_wave(pin_claims, grounding_rows, live_claims) if live_claims is not None else []
    worklist_claims = pin_claims + waved
    buckets: dict[str, list[dict[str, object]]] = {
        "refuted": [], "unverifiable": [], "tied": [], "unvoted": [], "confirmed": [],
        "superseded": [], "refuted_not_superseded": []}
    # SUPERSEDED — pinned claims the reconcile rewrote or removed, so the shipped map no longer
    # carries them. The record states how MANY; until now nothing could say WHICH, and the whole
    # design rests on those being the refuted ones. A superseded claim that was CONFIRMED is the
    # interesting case: it means the build overrode a verdict three skeptics agreed on.
    live = set(live_claims) if live_claims is not None else None
    for claim in worklist_claims:
        rows = votes.get(claim)
        if not rows:
            buckets["unvoted"].append({"claim": claim})
            if live is not None and claim not in live:
                # BEFORE the continue: an unvoted claim can be superseded too, and skipping it made
                # the report list FEWER than `write --map` counted — silently, in the very tool the
                # record points a reader at to see WHICH.
                buckets["superseded"].append({"claim": claim, "verdict": "unvoted", "votes": 0,
                                              "for": 0, "against": 0, "notes": []})
            continue
        bucket = _verdict_bucket(rows)
        grounded = sum(1 for r in rows if r.get("grounded") is True)
        refuted = sum(1 for r in rows if r.get("grounded") is False)
        stated = any(isinstance(r.get("grounded"), str) for r in rows)
        if bucket == "unverifiable" and not stated:
            bucket = "tied"
        if live is not None and claim not in live:
            buckets["superseded"].append({
                "claim": claim, "verdict": bucket, "votes": len(rows),
                "for": grounded, "against": refuted,
                "notes": [str(r.get("note", "")) for r in rows if r.get("note")]})
        row = {
            "claim": claim, "votes": len(rows), "for": grounded, "against": refuted,
            "evidence": [str(r.get("evidence", "")) for r in rows if r.get("evidence")],
            "skeptics": sorted({str(r.get("skeptic", "")) for r in rows if r.get("skeptic")}),
            "notes": [str(r.get("note", "")) for r in rows if r.get("note")],
        }
        buckets[bucket].append(row)
        # A refutation whose claim TEXT did not change is invisible to `claims_superseded` and to
        # the digest. Bucketed here rather than derived in the text renderer, so `--json` — which
        # this codebase tells readers to prefer over parsing the lines — carries it too.
        if live is not None and bucket == "refuted" and claim in live:
            buckets["refuted_not_superseded"].append(row)
    # NOT keyed on the worklist: a note to the lead is a fact about a ROW, and the row may sit on a
    # claim that was reworded after the pin. Walking `grounding_rows` keeps it visible either way.
    # THE APPEALS, as their own bucket: `uphold`/`reject`/`unsure` on a refutation the skeptics
    # already cast. The map kept NOTHING of what the closer decided until this file existed.
    buckets["closer"] = [{"claim": str(r.get("claim") or ""),
                          "verdict": str(r.get("verdict") or ""),
                          "grounded": r.get("grounded"),
                          "closer": str(r.get("skeptic") or ""),
                          "evidence": str(r.get("evidence") or ""),
                          "note": str(r.get("note") or "")} for r in closer_rows]
    to_lead, lead_denominator, upheld_total = lead_notes(grounding_rows)
    buckets["lead_notes"] = [{"claim": n.claim, "skeptic": n.skeptic, "evidence": n.evidence,
                              "note": n.note, "said": n.said} for n in to_lead]
    # THE OTHER HALF OF THE SAME CHANNEL, and the bigger one: only a SKEPTIC writes a verdict row,
    # so the rows above cannot carry a word from a harvest, trace, gap-fill or test agent. Those
    # speak only in their closing message. Omitted, not emptied, when no transcript directory was
    # given: "nothing found" and "nobody looked" must not read alike.
    from_agents: list[AgentFinding] = []
    agents_read = agents_total = 0
    if agent_dir is not None:
        from_agents, agents_read, agents_total = agent_findings(agent_dir)
        buckets["agent_findings"] = [{"agent": f.agent, "task": f.task, "heading": f.heading,
                                      "items": list(f.items)} for f in from_agents]
    if as_json:
        return json.dumps(buckets, indent=2, ensure_ascii=False)
    out: list[str] = []
    # A SUMMARY LINE FIRST, AND THE CRITICAL COUNT AGAIN LAST. This report is read through a pipe,
    # and two opposite narrowings hid two ends of one section on the same build: `| tail -40`
    # started inside the refuted list and cut the `REFUTED BUT NOT SUPERSEDED` header off the top,
    # then `| head -30` ended after the third of its five bullets. The lead fixed the three it
    # could see, said so, and two refuted claims shipped in the map. Neither narrowing was wrong to
    # attempt: the report runs hundreds of lines. So the number a reader must not miss is stated at
    # BOTH ends, which is the same rule `lint-fragment` already follows for its verdict.
    still_live_n = len(buckets["refuted_not_superseded"])
    out.append(
        f"GROUNDING REPORT — {len(buckets['refuted'])} refuted, {len(buckets['tied'])} tied, "
        f"{len(buckets['unverifiable'])} unverifiable, {len(buckets['unvoted'])} unvoted"
        + (f", {len(buckets['superseded'])} superseded" if live is not None else "")
        # ALWAYS, including the zero: this count is the only evidence that the pass over the
        # upheld rows happened at all, and a silent zero reads the same as a check nobody ran.
        + (f", {len(closer_rows)} closed on appeal" if closer_rows else "")
        + f", {len(to_lead)} upheld with a note to the lead"
        + (f", {len(from_agents)} finding(s) sent up by agents" if agent_dir is not None
           # NOT a zero. Nobody looked, which is a different answer from "nobody found anything",
           # and this report is read through a `head`.
           else ", AGENT FINDINGS NOT READ (no --agent-transcripts)")
        + (f" · {still_live_n} REFUTED CLAIM(S) STILL IN THE MAP" if still_live_n else ""))
    if live is not None:
        sup = buckets["superseded"]
        out.append(f"\nSUPERSEDED ({len(sup)}) — pinned claims the shipped map no longer carries.")
        if not sup:
            out.append("  (none — the pinned worklist and the shipped map hold the same claims)")
        for row in sup:
            split = (f" [{row['for']} for / {row['against']} against]"
                     if row.get("votes") else "")
            mark = "" if row["verdict"] == "refuted" else f"   <- was {str(row['verdict']).upper()}"
            out.append(f"  * {row['claim']}{mark}{split}")
        # Only a CONFIRMED verdict was settled. A tie is by definition unsettled — this report's
        # own next section calls it "the skeptics split; adjudicate against the code" — and an
        # unverifiable verdict says the code could not answer. Calling all three "settled"
        # over-claimed on two of them.
        overridden = [r for r in sup if r["verdict"] == "confirmed"]
        unsettled = [r for r in sup if r["verdict"] in ("tied", "unverifiable", "unvoted")]
        if overridden:
            n = len(overridden)
            out.append(f"  {n} of these {'was' if n == 1 else 'were'} CONFIRMED — the build rewrote "
                       f"a claim the skeptics had settled. That is a decision, not a fix; say so in "
                       f"`grounding.note`.")
        if unsettled:
            n = len(unsettled)
            out.append(f"  {n} {'was' if n == 1 else 'were'} never settled (tied / unverifiable / "
                       f"unvoted) — removing the claim ended the question rather than answering it.")
        # The OTHER direction, and the one no number watches. `claims_superseded` counts pinned
        # claims the shipped map no longer carries, and the design reads that as "the refutations
        # landed". But a refutation can be reconciled WITHOUT changing the claim's rendered text: on
        # a live build, `E35 (UpstreamState) has states […] with 10 transition(s)` was refuted, the
        # wrong transition was corrected in the map, and the claim string — which names a COUNT, not
        # the transitions — came out identical. So 5 refutations produced 4 superseded, and the
        # digest cannot witness that fifth fix at all: a build that "corrected" it by doing nothing
        # would produce the same digest. Name them, so the reader checks the map instead of the count.
        still_live = buckets["refuted_not_superseded"]
        if still_live:
            # Its OWN section. Nested under `SUPERSEDED (N)` it made the heading's count disagree
            # with the bullets below it, and on a map where nothing was superseded it printed
            # "(none — the pinned worklist and the shipped map hold the same claims)" immediately
            # above a list of claims — two lines that contradict each other, told apart only by
            # indentation.
            n = len(still_live)
            out.append(f"\nREFUTED BUT NOT SUPERSEDED ({n}) — the map still carries "
                       f"{'this claim' if n == 1 else 'these claims'} verbatim, so neither "
                       f"`claims_superseded` nor the digest can witness the fix. Either the "
                       f"reconcile changed something the claim text does not name (check the map by "
                       f"hand), or it has not been applied:")
            for row in still_live:
                out.append(f"  * {row['claim']}")
    for name, label in (("refuted", "REFUTED — reconcile each into the map"),
                        ("tied", "TIED — the skeptics split; adjudicate against the code"),
                        ("unverifiable", "UNVERIFIABLE — a skeptic said the code cannot answer"),
                        ("unvoted", "NO VERDICT — not challenged")):
        if not buckets[name]:
            continue
        out.append(f"\n{label} ({len(buckets[name])}):")
        for row in buckets[name]:
            out.append(f"  * {row['claim']}")
            raw_skeptics = row.get("skeptics")
            skeptics = [str(s) for s in raw_skeptics] if isinstance(raw_skeptics, list) else []
            if row.get("votes"):
                out.append(f"      {row['for']} for / {row['against']} against"
                           + (f"  [{', '.join(skeptics)}]" if skeptics else ""))
            raw_notes = row.get("notes")
            for n in (raw_notes if isinstance(raw_notes, list) else [])[:2]:
                out.append(f"      {str(n)[:160]}")
    # ADDED SINCE THE PIN — the claims the SHIPPED map carries that the pinned worklist never
    # held. `write` prints how MANY ("37 added since the pin") and nothing could say WHICH, so a
    # build hand-diffed `audit --json` against the worklist in python, then hand-edited the pinned
    # file itself to extend it — against the rule that the pin is not re-derived. Listing them
    # here is the read half of that job, and it is the half that needed no hand script.
    if live is not None:
        pinned = set(pin_claims)
        added = [c for c in dict.fromkeys(live_claims or []) if c not in pinned]
        if added:
            out.append(f"\nADDED SINCE THE PIN ({len(added)}) — in the shipped map, never in the "
                       f"pinned worklist. {len(set(waved) & set(added))} have a verdict from a "
                       f"second wave, which "
                       f"`grounding write --map` folds into the pin. Challenge the rest the same "
                       f"way (`coyomap audit <map> --batches <verify dir> --since <pinned "
                       f"worklist>` cuts them), or say in the note why they were not challenged:")
            for c in added:
                out.append(f"  * {'[second wave] ' if c in waved else ''}{c}")
    # THE CLOSER'S ANSWERS. An appeal, never a vote: none of the buckets above moved because of
    # these rows. Listed because the map kept nothing of what the closer decided — on one build 22
    # of 24 refutation judgements were applied on the strength of a chat sentence no later reader
    # can open.
    if closer_rows:
        words = [closer_word(r) for r in closer_rows]
        disputed = sum(1 for w in closer_ruling(closer_rows).values() if w == DISPUTED)
        tally = " · ".join([f"{w} {words.count(w)}" for w in _CLOSER_VERDICTS if words.count(w)]
                           + ([f"{disputed} claim(s) DISPUTED"] if disputed else []))
        out.append(f"\nCLOSED ON APPEAL ({len(closer_rows)} appeal row(s)) — {tally}. A closer "
                   f"re-read each "
                   f"refutation in fresh context, denied the map. `reject` means the skeptic "
                   f"misread the code, so the map is right to keep the claim and the refutation "
                   f"gate lets it by; `uphold` and `unsure` still need you.")
        for r in closer_rows:
            word = (closer_word(r) or "UNREADABLE").upper()
            out.append(f"  * [{word}] {str(r.get('claim') or '')}"
                       f"   [{r.get('skeptic') or '-'}]  {r.get('evidence') or '-'}")
            note = str(r.get("note") or "")
            if note:
                out.append(f"      {note if len(note) <= 300 else note[:300] + ' …'}")
    # THE UPHELD ROWS THAT SAID SOMETHING ANYWAY. Every other section of this report is keyed on a
    # verdict that asks for work; a CONFIRMED row asks for none, so a skeptic who upholds a claim
    # and then tells the lead about a second, unguarded route to the same screen is writing into a
    # file nothing reads. Its own section, after the verdict buckets, because it is not a verdict.
    if to_lead:
        out.append(f"\nNOTES TO THE LEAD ON UPHELD CLAIMS ({len(to_lead)}) — the skeptic voted the "
                   f"claim GROUNDED and then wrote something for you. A confirmed row appears in no "
                   f"other section of this report, so this is the only place these are said. Read "
                   f"each against the map: the claim stands, the note may still change it.")
        # COVERAGE, in `grounding lint`'s shape ("evidence check covered N of M"), because this is a
        # phrase match over prose: it will miss a note that raises something in other words, and it
        # will catch a note that uses one of the words about nothing.
        out.append(f"  Phrase match over {lead_denominator} of {upheld_total} upheld row(s) — the "
                   f"ones carrying a note — looking for {', '.join(_LEAD_NOTE_PHRASES)}. A note "
                   f"that says it differently is NOT below.")
        for n in to_lead:
            out.append(f"  * {n.claim}"
                       + (f"   [{n.skeptic}]" if n.skeptic else "")
                       + (f"  {n.evidence}" if n.evidence else ""))
            said = n.said if len(n.said) <= 320 else n.said[:320] + " …"
            out.append(f"      {'' if n.said == n.note else '…'}{said}")
    # WHAT THE OTHER AGENTS SENT UP. A harvest, trace, gap-fill or test agent writes no verdict
    # file, so nothing above can carry a word of theirs; their closing message is the only channel
    # they have, and it is read once by a lead hundreds of turns from the end.
    if agent_dir is not None:
        senders = len({f.agent for f in from_agents})
        out.append(f"\nFINDINGS THE AGENTS SENT UP ({len(from_agents)} section(s) from {senders} "
                   f"agent(s)) — the closing message each build agent wrote to you. A harvest or "
                   f"trace agent files no verdict, so this is its ONLY channel; on the build this "
                   f"check was written for, the strongest finding in it was an unguarded route "
                   f"named nowhere in the shipped map.")
        out.append(f"  Heading match over {agents_read} of {agents_total} agent transcript(s) in "
                   f"{agent_dir} — the ones with a closing message — looking for a heading that "
                   f"names the lead, a caveat, or something worth passing on. An agent that says it "
                   f"under no heading is NOT below.")
        for f in from_agents:
            out.append(f"  * {f.task or f.agent}   [{f.agent}]  \"{f.heading}\"")
            for item in f.items:
                out.append(f"      - {item if len(item) <= 300 else item[:300] + ' …'}")
    out.append(f"\nconfirmed: {len(buckets['confirmed'])} of {len(worklist_claims)} claim(s)")
    # The trailer half of the both-ends rule above: a `| tail -N` reader gets this even when the
    # section itself scrolled off the top. Only printed when it is non-zero, so a clean run does
    # not end on a scary-looking line.
    # The trailer half of the both-ends rule, for the notes to the lead as well: a `| tail -N`
    # reader gets the count even when the section scrolled off the top.
    if to_lead or from_agents:
        out.append(
            "\nTO THE LEAD: "
            + " · ".join(
                ([f"{len(to_lead)} upheld claim(s) carry a note written for you (NOTES TO THE LEAD "
                  f"ON UPHELD CLAIMS above)"] if to_lead else [])
                + ([f"{len(from_agents)} closing section(s) from build agents (FINDINGS THE AGENTS "
                    f"SENT UP above)"] if from_agents else []))
            + ". Neither is a refutation and nothing blocks on them; nothing else collects them "
              "either.")
    if agent_dir is None:
        out.append("\nAGENT FINDINGS NOT READ — no --agent-transcripts directory, so the closing "
                   "message every build agent wrote to you was not opened. That is not a clean "
                   "result; it is an unread channel.")
    if still_live_n:
        out.append(f"\nSTILL IN THE MAP: {still_live_n} refuted claim(s) the map carries verbatim "
                   f"— see REFUTED BUT NOT SUPERSEDED above, and fix the map before shipping it: "
                   + ", ".join(str(r["claim"])[:60] for r in buckets["refuted_not_superseded"][:5])
                   + (" …" if still_live_n > 5 else ""))
    return "\n".join(out).lstrip("\n")


# ── per-element checks: what the grounding pass actually did to each element ──────────────────────


@dataclass(frozen=True)
class ElementCheck:
    """One element of the map, beside what the skeptics did to the claims it makes.

    Some kinds carry an AUTHORED `confidence` — `verified` or `inferred` — written once by the agent
    that harvested the element. NOTHING in the tooling ever writes that field. So a pass that
    challenged an element three times with three different lenses and confirmed it unanimously
    leaves the label exactly as the author typed it, and a reader cannot tell a claim three skeptics
    proved from one nobody looked at. On a live map every business rule read `inferred` after each
    of its sites had been confirmed; on another, every rule read `verified` because the author said
    so and no reader could see which of them a skeptic had actually opened.

    This row is the missing half: `stated` is what the author claimed, the four counts are what the
    pass did. DERIVED, never stored — recomputed from the pinned worklist and the committed verdict
    files whenever it is asked for, so it cannot drift from them and no agent can author it."""
    element_id: str
    kind: str
    label: str
    stated: str = ""
    confirmed: int = 0
    refuted: int = 0
    unverifiable: int = 0
    unvoted: int = 0

    @property
    def claims(self) -> int:
        return self.confirmed + self.refuted + self.unverifiable + self.unvoted

    @property
    def status(self) -> str:
        """One word for the whole element. A single refutation OUTRANKS any number of confirmations:
        the element makes several claims, one of them is wrong, and that is the fact a reader has to
        see first. `part-checked` is kept apart from `confirmed` for the same reason the record keeps
        a tie apart from an `unverifiable` — "some of it was checked" is not "it was checked"."""
        if self.refuted:
            return "refuted"
        if self.unverifiable:
            return "unverifiable"
        if not self.confirmed:
            return "unchecked"
        return "part-checked" if self.unvoted else "confirmed"

    @property
    def unseen(self) -> bool:
        """No skeptic looked at this element at all.

        This REPLACES a comparison of the authored `confidence` against the votes. That comparison
        was built on reading `verified` as "the skeptics confirmed it", and that is not what the
        field means: `confidence` records what the AUTHOR knew — read and traced, or taken from a
        name — so an element can honestly be `verified` and unvoted, or `inferred` and confirmed,
        with no defect in either. The old flag called both a disagreement and asked builds to
        relabel honest rows.

        What a reader of this report actually needs is coverage: which elements the pass never
        reached. That is a fact about the pass, it needs no second field to compare against, and it
        is the one thing the grounding record's totals cannot say per element."""
        return self.status == "unchecked"


def _stated_confidence(m: ProjectModel, t: ClaimTarget) -> str:
    """The element's AUTHORED confidence, or "" for a kind that carries none.

    An edge and a cadenced entry point have no `confidence` field at all, so "" here means "the map
    never asked the author", which is different from an author who left it blank — but the two are
    indistinguishable in the stored map, so the report says `-` for both rather than inventing a
    distinction the data does not hold."""
    seq: object
    if t.kind == "rule_site":
        seq = m.rules
    elif t.kind == "description":
        seq = m.components
    elif t.kind == "lifecycle":
        seq = m.entities if t.sub == 0 else m.components
    elif t.kind == "security":
        seq = m.security
    else:
        return ""
    el = seq[t.idx]  # type: ignore[index]
    return str(getattr(el, "confidence", "") or "")


def _checkable_elements(m: ProjectModel) -> "list[tuple[tuple[str, int, int], ClaimTarget]]":
    """Every element the L2 worklist COULD have made a claim about, whether or not it did.

    Seeded into the tally with zero votes so an element nobody challenged appears as `unchecked`
    instead of being absent. Absence is the false negative this whole report exists to remove: a
    rule missing from the table reads exactly like a rule that passed, and on a live map two rules
    the author had labelled `verified` carried no pinned claim at all — neither would have appeared.

    The kinds and their conditions mirror `l2_worklist_model` exactly; an element the worklist would
    skip (a rule with no anchored site, an entity with no store) is not listed as unchecked here,
    because nothing was ever going to check it and saying otherwise would invent a gap."""
    out: "list[tuple[tuple[str, int, int], ClaimTarget]]" = []
    for i, e in enumerate(m.edges):
        out.append((("edge", i, -1), ClaimTarget("edge", i, -1, "", f"{e.src} {e.verb} {e.dst}")))
    for i, sec in enumerate(m.security):
        out.append((("security", i, -1), ClaimTarget("security", i, -1, "", sec.surface)))
    for i, br in enumerate(m.rules):
        if any((st.where or "").strip() for st in br.sites):
            out.append((("rule_site", i, -1),
                        ClaimTarget("rule_site", i, 0, br.id, br.name or br.statement)))
    for i, ep in enumerate(m.entry_points):
        if (ep.cadence or "").strip():
            out.append((("cadence", i, -1),
                        ClaimTarget("cadence", i, -1, getattr(ep, "id", "") or "",
                                    f"[{ep.kind}] {ep.trigger}")))
    for which, seq in ((0, m.entities), (1, m.components)):
        for i, el in enumerate(seq):
            sm = getattr(el, "states", None)
            if sm is not None and sm.states and (sm.source or "").strip():
                out.append((("lifecycle", i, which),
                            ClaimTarget("lifecycle", i, which, el.id, el.name)))
    for i, en in enumerate(m.entities):
        st = en.store
        if st is not None and st.dep:
            out.append((("store", i, -1), ClaimTarget("store", i, -1, en.id, en.name)))
    for i, mr in enumerate(m.messaging):
        out.append((("messaging", i, -1), ClaimTarget("messaging", i, -1, "", mr.name)))
    for i, c in enumerate(m.components):
        if (c.purpose or "").strip():
            out.append((("description", i, -1), ClaimTarget("description", i, -1, c.id, c.name)))
    return out


def element_checks(m: ProjectModel, worklist_claims: list[str],
                   grounding_rows: list[dict]) -> tuple[list[ElementCheck], list[str]]:
    """Fold the pinned worklist and the skeptics' votes onto the elements they judged.

    Returns the rows plus the claims that named no single element — an unresolved claim is REPORTED,
    never dropped, because a growing unresolved list is how a reader learns the worklist and the map
    have drifted apart (the pinned worklist is a snapshot, and a claim rewritten since resolves to
    nothing).

    The worklist is de-duplicated exactly as `build_record` and `format_report` do, and for the same
    reason: a repeated claim counted twice would make this report disagree with the record it exists
    to explain.

    SKEPTIC ROWS ONLY, like every other tally. This one was missed and is reached with appeals in
    the pile two ways, both through `ship`: the `grounding by-element` step, and `grounding
    refutations`, whose output `finalize` consumes. Measured on one refuted claim: skeptic alone
    `refuted=1`; plus one closer `reject` `refuted=0, unverifiable=1`; plus two `confirmed=1`."""
    grounding_rows = split_closer_rows(grounding_rows).skeptics
    votes: dict[str, list[dict]] = {}
    for r in grounding_rows:
        claim = r.get("claim")
        if isinstance(claim, str):
            votes.setdefault(claim, []).append(r)
    seen_claims: set[str] = set()
    claims = [c for c in worklist_claims if not (c in seen_claims or seen_claims.add(c))]
    tally: dict[tuple[str, int, int], dict[str, int]] = {}
    naming: dict[tuple[str, int, int], ClaimTarget] = {}
    for key, target in _checkable_elements(m):
        naming[key] = target
        tally[key] = {"confirmed": 0, "refuted": 0, "unverifiable": 0, "unvoted": 0}
    unresolved: list[str] = []
    for claim in claims:
        target = resolve_claim(m, claim).target
        if target is None:
            unresolved.append(claim)
            continue
        # ONE ROW PER ELEMENT, not per claim site. A rule with three sites makes three claims and
        # is still one rule; keying on the site index printed the same rule three times and a reader
        # counting rows would have over-counted the map. `lifecycle` keeps its `sub` because there it
        # selects WHICH list the index is into (entities vs components), not a part of one element.
        key = (target.kind, target.idx, target.sub if target.kind == "lifecycle" else -1)
        naming.setdefault(key, target)
        counts = tally.setdefault(key, {"confirmed": 0, "refuted": 0,
                                        "unverifiable": 0, "unvoted": 0})
        rows = votes.get(claim)
        counts["unvoted" if not rows else _verdict_bucket(rows)] += 1
    out = [ElementCheck(element_id=naming[k].element_id, kind=naming[k].kind,
                        label=naming[k].label, stated=_stated_confidence(m, naming[k]),
                        confirmed=c["confirmed"], refuted=c["refuted"],
                        unverifiable=c["unverifiable"], unvoted=c["unvoted"])
           for k, c in tally.items()]
    # Worst first — a refuted element is the one a reader must act on. Then by kind and id, so a
    # re-run reads the same.
    order = {"refuted": 0, "unverifiable": 1, "unchecked": 2, "part-checked": 3, "confirmed": 4}
    out.sort(key=lambda r: (order[r.status], r.kind, r.element_id, r.label))
    return out, unresolved


def format_element_checks(rows: list[ElementCheck], unresolved: list[str],
                          as_json: bool = False, only_kind: str = "") -> str:
    """The report: every element the pass touched, its authored label, and what the votes said."""
    if only_kind:
        rows = [r for r in rows if r.kind == only_kind]
    if as_json:
        return json.dumps({
            "elements": [{"id": r.element_id, "kind": r.kind, "label": r.label,
                          "stated": r.stated, "status": r.status, "unseen": r.unseen,
                          "claims": r.claims, "confirmed": r.confirmed, "refuted": r.refuted,
                          "unverifiable": r.unverifiable, "unvoted": r.unvoted} for r in rows],
            "unresolved_claims": unresolved,
        }, indent=2, ensure_ascii=False)
    lines: list[str] = []
    unseen = [r for r in rows if r.unseen]
    # "checkable", not "carry a pinned claim": the table now seeds every element the worklist COULD
    # have claimed, so the count includes the ones it never did — which is the point.
    lines.append(f"{len(rows)} checkable element(s) · "
                 f"{sum(1 for r in rows if r.status == 'confirmed')} confirmed, "
                 f"{sum(1 for r in rows if r.status == 'part-checked')} part-checked, "
                 f"{sum(1 for r in rows if r.status == 'refuted')} refuted, "
                 f"{sum(1 for r in rows if r.status == 'unverifiable')} unverifiable, "
                 f"{sum(1 for r in rows if r.status == 'unchecked')} unchecked")
    if unseen:
        lines.append(f"{len(unseen)} element(s) no skeptic looked at — the pass never reached them, "
                     f"whatever their authored label says (`confidence` records what the AUTHOR "
                     f"knew, not what the votes found):")
    lines.append("")
    lines.append(f"{'id':<7} {'kind':<12} {'stated':<9} {'checked':<13} {'votes':<24} label")
    for r in rows:
        votes = (f"{r.confirmed}✓ {r.refuted}✗ {r.unverifiable}? {r.unvoted}– "
                 f"of {r.claims}")
        flag = "  <- nobody looked" if r.unseen else ""
        lines.append(f"{r.element_id or '-':<7} {r.kind:<12} {r.stated or '-':<9} "
                     f"{r.status:<13} {votes:<24} {r.label[:46]}{flag}")
    if unresolved:
        lines.append("")
        lines.append(f"{len(unresolved)} pinned claim(s) name no single element in this map — the "
                     f"claim was rewritten after the worklist was pinned, or two elements make it:")
        for c in unresolved[:20]:
            lines.append(f"  - {c[:110]}")
        if len(unresolved) > 20:
            lines.append(f"  ... and {len(unresolved) - 20} more")
    return "\n".join(lines)


@dataclass(frozen=True)
class SurvivingRefutation:
    """A claim the skeptics REFUTED that the shipped map still makes, word for word.

    The build contract is that every refutation is reconciled: the claim is corrected, or the row is
    dropped. Either way the wording changes, so the pinned claim no longer resolves against the live
    map — that is what `claims_superseded` counts. A refuted claim that still resolves to a live
    element is therefore one nobody acted on, and no gate could see it: `validate` checks shape,
    `audit` checks the map against itself, and the `grounding` record reduces the whole pass to four
    numbers in which a refutation and a reconciliation look identical. A live map shipped two of
    these while its finalize report said 0 blocking and never used the word "refuted".

    THERE IS DELIBERATELY NO RECORDED ESCAPE for this. Every escape in this tool was added after a
    real false alarm, and there is not one yet: a lead who reads a refutation and disagrees is
    expected to RE-AUTHOR the claim, which supersedes it and removes it from here by itself. Add the
    heading when a real map produces a survivor that should stay, not before.

    THE ONE THING THAT DOES CLEAR IT is the closer REJECTING the refutation in writing — a second
    fresh-context reader, denied the map, saying the skeptic misread the code. That is not an
    escape hatch; it is the appeal the method already runs, and until `verify/closer-*.json` existed
    its answer lived only in a chat sentence. On the 2026-09-13 reminderrepo build two rejected
    refutations blocked this gate and cost five turns to talk past."""
    claim: str
    element_id: str
    kind: str
    label: str
    refuted_by: int
    note: str = ""
    #: The closer's own word on this refutation, when it heard it: `uphold` (it stands), `unsure`
    #: (it could not settle it), `conflict` (two appeals disagreed) or "" (never closed). A `reject`
    #: is not here at all — it stops being a surviving refutation.
    closed: str = ""
    #: The majority CONFIRMED this claim and a skeptic refuted it: a dissent the tally files as
    #: confirmed. It is here only when a closer upheld the dissent, or (in `access_dissent`) when
    #: the claim is about who may do what.
    outvoted: bool = False


def surviving_refutations(m: ProjectModel,
                          grounding_rows: list[dict]) -> list[SurvivingRefutation]:
    """The refutations the shipped map still carries.

    Walks the VERDICTS, not the worklist: a refuted claim the reconcile dropped is absent from the
    live map and must not be looked for, while one the reconcile never touched is exactly what this
    finds. The pinned worklist is not needed and is not asked for, so this runs anywhere the map and
    the verdict files are — which is what lets `finalize` include it without a captured snapshot.

    A CLOSER REJECTION SETTLES ONE. The claim stays in the map on purpose, so it will keep resolving
    here forever; what changes is that a named reader wrote down why. Only `reject` clears it:
    `uphold` means the refutation stands, and `unsure` means nobody settled it — both still need the
    lead, and reading "not settled" as "cleared" is the one way this change could hide a real
    survivor."""
    split = split_closer_rows(grounding_rows)
    grounding_rows = split.skeptics
    closed = closer_ruling(split.closer)
    votes: dict[str, list[dict]] = {}
    for r in grounding_rows:
        claim = r.get("claim")
        if isinstance(claim, str):
            votes.setdefault(claim, []).append(r)
    out: list[SurvivingRefutation] = []
    for claim, rows in votes.items():
        # AN UPHELD DISSENT IS A REFUTATION. The majority confirmed the claim, one skeptic refuted
        # it, and a closer then read the code and sided with the one: the claim is false as the map
        # states it, whatever the tally says. Left out, the appeal the method runs for exactly this
        # case would have nowhere to land.
        outvoted = _outvoted(rows)
        if _verdict_bucket(rows) != "refuted" and not (outvoted and closed.get(claim) == "uphold"):
            continue
        target = resolve_claim(m, claim).target
        if target is None:
            continue          # reconciled: the live map no longer makes this claim
        if closed.get(claim) == "reject":
            continue          # the closer REJECTED the refutation: the map is right to keep it
        note = next((str(r.get("note") or "") for r in rows if r.get("grounded") is False), "")
        out.append(SurvivingRefutation(
            claim=claim, element_id=target.element_id, kind=target.kind, label=target.label,
            refuted_by=sum(1 for r in rows if r.get("grounded") is False), note=note,
            closed=closed.get(claim, ""), outvoted=outvoted))
    out.sort(key=lambda s: (s.kind, s.element_id, s.claim))
    return out


def _outvoted(rows: list[dict]) -> bool:
    """The majority confirmed the claim and at least one skeptic refuted it."""
    return _verdict_bucket(rows) == "confirmed" and any(r.get("grounded") is False for r in rows)


def access_dissent(m: ProjectModel, grounding_rows: list[dict]) -> list[SurvivingRefutation]:
    """ACCESS claims the majority confirmed over a refutation, that no closer has settled.

    A 2-1 vote files the claim as confirmed, and every count after that is silent about the one.
    On the 2026-09-30 mcpolis build two sites of an access rule were confirmed 2-1; all three voters
    wrote the same counterexample (a member removed one way keeps the row these lines trust), the
    code supported the dissent, and the brief's two dissent rows were dropped by hand as "duplicate
    votes or minority". The rule shipped `verified`.

    `closed` says where each one stands: "" nobody ruled (the gate BLOCKS: the remedy is one closer
    brief away), `unsure` or DISPUTED (heard and not settled; said, not blocked). A `reject` settles
    it — the majority read the code right — and an `uphold` makes it a surviving refutation, so
    neither is here."""
    split = split_closer_rows(grounding_rows)
    closed = closer_ruling(split.closer)
    access = _access_rule_ids(m)
    votes: dict[str, list[dict]] = {}
    for r in split.skeptics:
        claim = r.get("claim")
        if isinstance(claim, str):
            votes.setdefault(claim, []).append(r)
    out: list[SurvivingRefutation] = []
    for claim, rows in votes.items():
        if not _outvoted(rows) or closed.get(claim) in ("reject", "uphold"):
            continue
        target = resolve_claim(m, claim).target
        if target is None or target.element_id not in access:
            continue
        note = next((str(r.get("note") or "") for r in rows if r.get("grounded") is False), "")
        out.append(SurvivingRefutation(
            claim=claim, element_id=target.element_id, kind=target.kind, label=target.label,
            refuted_by=sum(1 for r in rows if r.get("grounded") is False), note=note,
            closed=closed.get(claim, ""), outvoted=True))
    out.sort(key=lambda s: (s.element_id, s.claim))
    return out


def _access_rule_ids(m: ProjectModel) -> set[str]:
    """Ids of the rules the map marks `access: true` — the ones whose CLAIM is about who may do
    what, not about how something works. Named apart because leaving one unchallenged matters more
    than leaving a description unchallenged, not because of anything its label says."""
    return {br.id for br in m.rules if getattr(br, "access", False) and br.id}


def _rules_voted_under_any_anchor(m: ProjectModel, grounding_rows: list[dict]) -> set[str]:
    """Rule ids a skeptic voted on, matched by STATEMENT rather than by the anchored claim string.

    `element_checks` pairs a vote to an element by exact claim text, and a rule-site claim embeds the
    `file:line` and the site's `why` (see `rule_site_claim`). So moving an anchor one line, or
    rewording a `why`, orphans every vote the rule ever had and the element reads `unchecked` — as if
    nobody had looked. That is fine for an advisory about wording. It is not fine for a gate: an
    adversarial review moved ONE anchor on a confirmed access rule of a real map and the rule went
    straight to BLOCKING under a message reading "NO skeptic ever voted on it", which was false. 50
    of that map's 56 access rules sit in the state where that could happen, and `fix apply-drift` —
    the method's own remedy for a drifted anchor — is documented as moving exactly these anchors.

    The statement is the part of the claim that does NOT move when an anchor is corrected, so it is
    what tells "nobody challenged this rule" from "the rule was challenged and then re-anchored"."""
    claims = " \u0000 ".join(str(r.get("claim") or "") for r in grounding_rows)
    return {br.id for br in m.rules
            if br.id and (br.statement or "").strip() and (br.statement or "").strip() in claims}


def settled_on_appeal(m: ProjectModel, grounding_rows: list[dict]) -> list[SurvivingRefutation]:
    """The refutations a closer REJECTED that the map still carries — the ones the gate now lets by.

    Named, always, and never merely absent. A gate that stops firing without saying what it stopped
    firing on is the shape every silent pass in this tool has taken; `surviving_refutations` drops
    these rows, so this is what puts them back on screen with the closer's own evidence line."""
    split = split_closer_rows(grounding_rows)
    closer_rows = split.closer
    closed = closer_ruling(closer_rows)
    rejected = {c for c, word in closed.items() if word == "reject"}
    if not rejected:
        return []
    votes: dict[str, list[dict]] = {}
    for r in split.skeptics:
        claim = r.get("claim")
        if isinstance(claim, str) and claim in rejected:
            votes.setdefault(claim, []).append(r)
    out: list[SurvivingRefutation] = []
    for claim, rows in votes.items():
        if _verdict_bucket(rows) != "refuted":
            continue
        target = resolve_claim(m, claim).target
        if target is None:
            continue
        note = next((str(r.get("note") or "") for r in closer_rows
                     if r.get("claim") == claim and r.get("note")), "")
        out.append(SurvivingRefutation(
            claim=claim, element_id=target.element_id, kind=target.kind, label=target.label,
            refuted_by=sum(1 for r in rows if r.get("grounded") is False), note=note,
            closed="reject"))
    out.sort(key=lambda s: (s.kind, s.element_id, s.claim))
    return out


def format_refutations(surviving: list[SurvivingRefutation],
                       unseen: list[ElementCheck], as_json: bool = False,
                       m: ProjectModel | None = None,
                       grounding_rows: list[dict] | None = None) -> str:
    """The gate's report: refuted claims still in the map, and the elements no skeptic looked at.

    `access` rides on each unseen element because the caller has to tell two cases apart that read
    identically here. A component description nobody challenged is a coverage gap. An ACCESS rule
    nobody challenged is the map making a claim about who may do what with nothing behind it — a
    shipped map carried three, all authored after the worklist was pinned, so no skeptic could have
    seen them.

    The second list is NOT keyed on the authored `confidence`. It once was, and the text branch of
    this function went on saying so after the JSON branch stopped: `format_refutations` has no test
    at all, so nothing caught the two halves disagreeing. On a real map 24 of its 33 rows were edges,
    which carry no `confidence` field, and printed as `says , pass says unchecked`."""
    access = _access_rule_ids(m) if m else set()
    voted = _rules_voted_under_any_anchor(m, grounding_rows or []) if m else set()
    appealed = settled_on_appeal(m, grounding_rows or []) if m else []
    dissent = access_dissent(m, grounding_rows or []) if m else []
    if as_json:
        return json.dumps({
            "surviving_refutations": [
                {"claim": s.claim, "id": s.element_id, "kind": s.kind, "label": s.label,
                 "refuted_by": s.refuted_by, "note": s.note, "closed": s.closed,
                 "outvoted": s.outvoted}
                for s in surviving],
            # Access claims the majority confirmed over a refutation no closer settled. `closed`
            # "" = nobody ruled (finalize blocks), else the closer's unsettled word.
            "access_dissent": [
                {"claim": s.claim, "id": s.element_id, "kind": s.kind, "label": s.label,
                 "refuted_by": s.refuted_by, "note": s.note, "closed": s.closed}
                for s in dissent],
            # The refutations this gate NO LONGER blocks on, and why. `finalize` reads the key
            # above; this one is beside it so a reader of either can see what left the list.
            "settled_on_appeal": [
                {"claim": s.claim, "id": s.element_id, "kind": s.kind, "label": s.label,
                 "refuted_by": s.refuted_by, "note": s.note} for s in appealed],
            # RENAMED from `stated_but_unchallenged`, which described a comparison that no longer
            # exists: these are the elements NO SKEPTIC LOOKED AT, whatever their authored
            # `confidence` says. The old key implied the label was part of the test.
            "unseen_by_any_skeptic": [
                {"id": e.element_id, "kind": e.kind, "label": e.label, "stated": e.stated,
                 "status": e.status, "access": e.element_id in access,
                 "voted_under_any_anchor": e.element_id in voted} for e in unseen],
        }, indent=2, ensure_ascii=False)
    lines: list[str] = []
    if surviving:
        lines.append(f"{len(surviving)} REFUTED claim(s) are still in this map, unchanged. The "
                     f"build contract is that every refutation is reconciled — corrected, or "
                     f"dropped — and a reconciled claim no longer resolves here at all:")
        for s in surviving:
            lines.append(f"  - {s.claim}   [{s.kind}{' ' + s.element_id if s.element_id else ''}, "
                         f"refuted by {s.refuted_by}"
                         + (", outvoted by the majority" if s.outvoted else "")
                         + (f", two appeals DISAGREE" if s.closed == DISPUTED
                            else f", closer said {s.closed.upper()}" if s.closed else "") + "]")
            if s.note:
                lines.append(f"      skeptic: {s.note[:200]}")
    else:
        lines.append("No refuted claim survives in this map.")
    if dissent:
        lines.append("")
        lines.append(f"{len(dissent)} ACCESS claim(s) the majority CONFIRMED over a skeptic who "
                     f"refuted them, with no closer ruling that settles it. A split vote on who may "
                     f"do what goes to a closer (`contract closer --from-verdicts` carries it under "
                     f"'Outvoted dissent'):")
        for s in dissent:
            lines.append(f"  - {s.claim}   [{s.element_id}, refuted by {s.refuted_by}, "
                         + ("NO closer ruling" if not s.closed
                            else "two appeals DISAGREE" if s.closed == DISPUTED
                            else f"closer said {s.closed.upper()}") + "]")
            if s.note:
                lines.append(f"      dissent: {s.note[:200]}")
    if appealed:
        lines.append("")
        lines.append(f"{len(appealed)} refutation(s) the CLOSER REJECTED — the map keeps these "
                     f"claims on purpose, so they are not counted above. A second fresh-context "
                     f"reader, denied the map, found the skeptic had misread the code:")
        for s in appealed:
            lines.append(f"  - {s.claim}   [{s.kind}"
                         f"{' ' + s.element_id if s.element_id else ''}, "
                         f"refuted by {s.refuted_by}, REJECTED on appeal]")
            if s.note:
                lines.append(f"      closer: {s.note[:200]}")
    if unseen:
        lines.append("")
        access_rows = [e for e in unseen if e.element_id in access]
        lines.append(f"{len(unseen)} element(s) no skeptic looked at — the pass never reached them "
                     f"(`coyomap grounding by-element` lists them in full):")
        for e in unseen[:15]:
            # The authored label is printed only when the element HAS one: an edge and a crossing
            # carry no `confidence` field, and `says , pass says unchecked` is what printing it
            # unconditionally produced.
            said = f", author said {e.stated}" if e.stated else ""
            lines.append(f"  - {e.element_id or '-':<7} {e.kind:<12} unchecked{said}"
                         f" — {e.label[:44]}")
        if len(unseen) > 15:
            lines.append(f"  ... and {len(unseen) - 15} more")
        if access_rows:
            lines.append(f"  {len(access_rows)} of those are ACCESS rules, which is what a reader "
                         f"trusts a map for: {', '.join(e.element_id for e in access_rows[:8])}")
    return "\n".join(lines)


def worklist_is_behavioural(path: Path) -> bool:
    """Was this pinned worklist captured with `audit --with-behavioural`?

    Read off the items' own `theme`, not a new file field: `audit --json` already writes the theme
    per item, and the behavioural tier is the only producer of `behaviour`. Deriving it means an
    existing worklist file answers the question with no migration.

    WHY IT HAS TO BE ASKED. The live claim surface below is recomputed from the assembled map, and
    it used to be recomputed at the DEFAULT tier always. So a build that pinned a behavioural
    worklist got every behaviour claim back as `superseded` — 489 of them on the map this was
    written from — and `live_claims_digest` described a different surface from the one that was
    pinned. That made the tier unusable in practice, which is why 1,049 rows of the 2026-09-02
    mcpolis map were outside the worklist "by construction". The two surfaces must be computed the
    same way or the record is about neither.

    The reading itself is `audit_model.pinned_tier`, shared with `validate` and `changes check`."""
    return pinned_tier(path)


def _worklist_claims(path: Path) -> list[str]:
    """Claims from a worklist file — `audit_model.pinned_claims`, the one reader, under the name
    this module's callers already use."""
    return pinned_claims(path)


@dataclass
class VerdictLint:
    """The lint's answer. A dataclass, not a `(list, list)` tuple — both are empty on the happy
    path, so a swapped pair reads as correct behaviour and no test can tell the difference. Same
    reason `assemble.FragmentLoad` exists."""
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _closer_file_faults(paths: list[str]) -> list[str]:
    """Is each file the KIND of file its name says it is?

    ONE DIRECTION ONLY, now that `closer_faults` reads the rows: an appeal word inside a
    `verdicts-*.json`. That row is not malformed — it is a well-formed appeal in the wrong file, so
    nothing about the row itself can object, and it silently leaves the vote tally. The other
    direction, a `closer-*.json` whose rows carry no readable word, is a row fault and is caught by
    `closer_faults` wherever the file is called `closer.json`, `appeals-a.json` or anything else."""
    faults: list[str] = []
    for path in paths:
        if not Path(path).name.startswith("verdicts-"):
            continue
        rows, _notes = load_verdicts([path])
        appeals = [r for r in rows if is_closer_row(r)]
        if appeals:
            faults.append(
                f"{Path(path).name}: {len(appeals)} of {len(rows)} row(s) carry a `verdict` field "
                f"inside a skeptics file, so they are read as APPEALS and drop out of the vote "
                f"tally. A closer writes its own `verify/closer-<agent>.json`; move them there, or "
                f"drop the field.")
    return faults


def lint_verdicts(paths: list[str], agent_dir: Path | None = None) -> VerdictLint:
    """Shape check over raw verdict files, WITHOUT needing a worklist or a map.

    `grounding write` already refuses a malformed record — but it runs at the very end of a build,
    and the skeptic that produced the bad file finished a hundred turns earlier. One live build
    shipped 40 rows whose `grounded` was the STRING `"true"`; the refusal came at the last step and
    cost four turns of hand-repair on the critical path. The same check, runnable the moment a
    skeptic returns, costs nothing and fails where the fix is cheap.

    With `--agent-transcripts <dir>` it also answers a question no shape check can: is the file a
    row cites one this agent ever touched. The incident behind it: one skeptic settled 40 claims in
    95 seconds from a single directory-wide grep and generated every row from a script, each `note`
    opening `Read <file>:` for files it never opened.

    WHAT IT CATCHES, stated narrowly on purpose. A citation of a file that appears NOWHERE in the
    transcript is a hard problem — that is a path the agent could not have learned. A citation of a
    file the transcript only ever PRINTED, in a grep result or a listing, is a note and not a
    failure: reading the matching lines out of a grep result is legitimate verification, so
    grep-only is a shape, not proof.

    WHAT IT DOES NOT CATCH, so nobody reads a clean run as more than it is: the incident above would
    pass this as a note. Its tell was 40 claims in 95 seconds off one grep — a RATE, not a missing
    path — and a rate is not something this command can see. Do not treat `VERDICTS OK` as evidence
    that a pass was honest.
    """
    out = VerdictLint()
    rows, load_notes = load_verdicts(paths)
    out.notes += load_notes
    if not rows:
        out.problems.append("no verdict rows found in " + ", ".join(paths))
        return out
    out.problems += closer_faults(rows) + _closer_file_faults(paths)

    bad = sorted({f"{r.get('grounded')!r}" for r in rows
                  if not (r.get("grounded") is True or r.get("grounded") is False
                          or (isinstance(r.get("grounded"), str)
                              and r.get("grounded", "").lower() == "unverifiable"))})
    if bad:
        out.problems.append(
            f"{len(bad)} unrecognised `grounded` value(s): {', '.join(bad)}. The vocabulary is the "
            f"JSON booleans true / false, or the string \"unverifiable\" — `\"true\"` quoted is the "
            f"one that has actually shipped, and a skeptic's own self-check cannot see it because "
            f"printing str(value) renders 'true' either way.")

    for field in ("claim", "evidence", "skeptic"):
        missing = sum(1 for r in rows if not str(r.get(field) or "").strip())
        if missing:
            out.problems.append(f"{missing} row(s) have no `{field}` — "
                            + {"claim": "the record pairs rows to claims by that exact string",
                               "evidence": "a verdict with no line is an opinion",
                               "skeptic": "it is what tells two independent votes from one file "
                                          "passed in twice"}[field])

    if agent_dir is not None:
        evidence = _fabricated_evidence(rows, agent_dir)
        # The weak half says of itself that it is not proof, so it rides as a NOTE. A signal that
        # fails the lint is a signal an agent must clear, and the only way to clear this one is to
        # re-read files it may have read already — which teaches the next agent to route its reading
        # around the check rather than to look again.
        out.problems += evidence.problems
        out.notes += evidence.notes
    return out


#: A note asserting the skeptic opened something — the claim this check tests against the record of
#: what it actually opened.
_CLAIMS_A_READ = re.compile(r"\bread\s+([\w./-]+\.[A-Za-z0-9]+)", re.I)


#: The file extensions a map anchors into. An explicit list, because `evidence` also carries
#: SYMBOL references — `ServiceTokenService.mint`, `MongoOAuthStateRepository.save` — which are
#: `Word.word` and match any "token dot token" rule. Reading eleven of those as unopened files was
#: the first thing this widening did.
_SOURCE_SUFFIXES = (
    "py", "pyi", "js", "jsx", "ts", "tsx", "mjs", "cjs", "go", "rs", "rb", "java", "kt", "kts",
    "swift", "c", "h", "cc", "cpp", "hpp", "cs", "php", "scala", "clj", "ex", "exs", "erl", "lua",
    "sh", "bash", "zsh", "sql", "html", "css", "scss", "vue", "svelte", "json", "yaml", "yml",
    "toml", "ini", "cfg", "conf", "env", "md", "txt", "proto", "graphql", "tf", "dockerfile")

#: Extensionless files a map really anchors into. Across three real maps these are 60 anchors the
#: suffix list alone could not reach — `Makefile` 43 times on one of them — and a build file is
#: where a fabricated claim is least likely to be noticed.
_EXTENSIONLESS = ("makefile", "dockerfile", "procfile", "rakefile", "gemfile", "justfile",
                  "commit-msg", "pre-commit", "pre-push", "codeowners")

#: A bare `path:line` — the shape every verdict row's `evidence` field carries.
_EVIDENCE_PATH = re.compile(
    r"((?:[\w./-]+\.(?:" + "|".join(_SOURCE_SUFFIXES) + r")"
    r"|(?:[\w./-]*/)?(?:" + "|".join(_EXTENSIONLESS) + r")))(?::\d+)?$", re.I)


def _claimed_files(row: dict) -> set[str]:
    """Every file this row asserts the skeptic looked at.

    Two sources, and the second is what took this check from 2 % of rows to nearly all of them. The
    NOTE half was here first and only matches prose of the shape `read <file>.<ext>`; on a measured
    build that was 20 of 1000 rows, because most notes cite their anchor in `evidence` instead and
    describe the reading in words. `evidence` is a bare `path:line` on every row, and citing a file
    you never opened is precisely the shape this check exists to catch — the skeptic that settled 40
    claims in 95 seconds from one directory-wide grep put a real-looking anchor on every one."""
    out = {_norm_path(m) for m in _CLAIMS_A_READ.findall(str(row.get("note") or ""))
           if m.rsplit(".", 1)[-1].lower() in _SOURCE_SUFFIXES
           or m.rsplit("/", 1)[-1].lower() in _EXTENSIONLESS}
    ev = _EVIDENCE_PATH.match(str(row.get("evidence") or "").strip())
    if ev:
        out.add(_norm_path(ev.group(1)))
    return {f for f in out if f}


def _read_claim_coverage(rows: list[dict]) -> tuple[int, int]:
    """`(rows, rows the evidence check can actually test)`."""
    return len(rows), sum(1 for r in rows if _claimed_files(r))


#: Suffixes a per-agent transcript is written under. `.jsonl` is the settled convention; `.output`
#: is what the harness names in the dispatch result it hands the LEAD — same JSONL, different
#: extension — and pointing this flag at that directory failed outright. The flag was suggested by
#: the tool twice on one build and used zero times, because the only path the lead had been given
#: was the one that does not work.
_AGENT_TRANSCRIPT_GLOBS = ("*.jsonl", "*.output")


def _records(path: Path) -> list[dict[str, object]]:
    """The agent-transcript RECORDS in one file — dicts only.

    A JSONL line is not guaranteed to decode to an object. `<session>/tasks/` mixes the per-agent
    transcripts with the stdout of every BACKGROUND BASH call the lead made, under the same
    `.output` suffix, and that stdout is whatever the command printed: a pretty-printed JSON file
    whose lines decode to `{`-fragments, or a bare number that decodes to an `int`. Callers used to
    go straight to `rec.get(...)`, so one such line aborted the whole pass with
    `AttributeError: 'int' object has no attribute 'get'` — measured on a real build, where it
    killed the fabricated-evidence check for all 1,085 verdict rows and the build shipped a
    `grounding.note` saying the check could not run at all.
    """
    out: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _is_agent_transcript(path: Path) -> bool:
    """Does this file look like ONE agent's turn log, rather than some command's stdout?

    Every line of an agent transcript is a JSON OBJECT. Background-Bash output under the same
    `.output` suffix is whatever the command printed, and on the measured build that included bare
    scalars — which is what crashed the pass — and pretty-printed JSON, whose lines mostly do not
    parse at all. So the test is: at least one object, and no line that parses to something else.

    An EMPTY-looking transcript still counts, because "this agent opened nothing" and "there are no
    agent transcripts here" are different answers and only the second should raise the
    wrong-directory error.

    Dropping the stdout captures matters beyond the crash: every path token they print would land in
    the LOOSE `_mentioned_files` set, which decides whether a cited file counts as "named
    somewhere". A claims batch printed by a background command would vouch for rows no agent read.
    """
    objects = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            objects += 1
        else:
            return False
    return objects > 0


def _agent_transcript_files(agent_dir: Path) -> list[Path]:
    """Every per-agent transcript under `agent_dir`, whichever suffix the harness used.

    Files that parse but are not agent transcripts are dropped — see `_is_agent_transcript`."""
    seen: dict[Path, None] = {}
    for pattern in _AGENT_TRANSCRIPT_GLOBS:
        for f in sorted(agent_dir.glob(pattern)):
            resolved = f.resolve()
            if resolved in seen:
                continue
            if _is_agent_transcript(resolved):
                seen.setdefault(resolved, None)
    return sorted(seen)


#: A tool call that really opens a file, and where the path sits in its input. `Read` is the direct
#: one; the shell verbs are how a skeptic reads a range without loading a whole file.
#: `Grep` and `Glob` open nothing themselves, but a skeptic that greps a file and reads the matching
#: lines out of the RESULT has verified the claim — and accusing it of fabrication is the expensive
#: mistake here. They count as opening their `path`, which is why the strong set is the one that
#: FAILS the lint and the loose set only notes.
_FILE_READING_TOOLS = ("Read", "NotebookRead", "Grep", "Glob")
_SHELL_READERS = re.compile(r"\b(?:cat|sed|head|tail|less|awk|grep|rg|nl|wc)\b")


def _shell_read_operands(command: str) -> set[str]:
    """Paths a shell command READS, as operands — never as a pattern or a redirect target.

    `grep -rn "src/auth_token.py" docs/` names a path inside its PATTERN and opens nothing. Taking
    every path-shaped token out of the command string turned that into a self-service whitelist: one
    grep laundered an arbitrary file list into "actually opened", and the row cleared without even a
    note. Quoted spans and everything after a redirect are dropped, and only the verbs that read a
    file are considered at all."""
    if not _SHELL_READERS.search(command):
        return set()
    body = re.sub(r"'[^']*'|\"[^\"]*\"", " ", command)      # a pattern is quoted; an operand rarely is
    body = re.split(r"[>]", body)[0]                        # a redirect target is written, not read
    out: set[str] = set()
    for tok in body.split():
        if tok.startswith("-"):
            continue
        if re.fullmatch(r"[\w./-]+\.[A-Za-z0-9]+", tok) or tok.rsplit("/", 1)[-1].lower() in _EXTENSIONLESS:
            out.add(_norm_path(tok))
    return out


def _opened_files(files: list[Path]) -> set[str]:
    """Paths the agent's transcript shows it ACTUALLY opening — file-reading tool calls only.

    The permissive set below (every filename-shaped token anywhere in the transcript) is what this
    check used to test against, and it is close to useless: measured on one skeptic transcript from
    a real build it held 477 names where the agent had opened 17 files. A directory-wide `grep`
    prints hundreds of paths into the transcript, and a grep is exactly what the fabricating skeptic
    this check was written for used. So the two sets are kept apart: a claim outside BOTH is a hard
    finding, and a claim inside the loose set but outside this one is the weaker signal, reported as
    such rather than silently folded into "no findings"."""
    out: set[str] = set()
    for f in files:
        for rec in _records(f):
            msg = rec.get("message")
            for c in ((msg if isinstance(msg, dict) else {}).get("content") or []):
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                inp = c.get("input") or {}
                if c.get("name") in _FILE_READING_TOOLS:
                    for key in ("file_path", "path", "notebook_path"):
                        if str(inp.get(key) or "").strip():
                            out.add(_norm_path(str(inp[key])))
                elif c.get("name") == "Bash":
                    out |= _shell_read_operands(str(inp.get("command") or ""))
    return {p for p in out if p}


def unopened(paths: list[str], transcripts: list[Path]) -> list[str]:
    """The `paths` no file-reading tool call in `transcripts` opened, in the order given.

    The same reading of "opened" the verdict lint uses (`_opened_files`, matched by `_resolves`),
    so a path counts as read here exactly when it would count as read there."""
    opened = _opened_files(transcripts)
    return [p for p in paths if not _resolves(p, opened)]


def _norm_path(p: str) -> str:
    """One normaliser, used on BOTH sides. `lstrip("./")` was the first version and it is a
    character-class strip, not a prefix strip: it turned `.github/dependabot.yml` into
    `github/dependabot.yml` while the transcript kept `/.github/`, so the two could never match. The
    single finding the widened check produced on a real 1000-row pass was that false accusation, and
    one of the three real maps carries 104 dot-directory anchors."""
    return p.strip().removeprefix("./").rstrip("/")


def _mentioned_files(files: list[Path]) -> set[str]:
    """Every path the transcript NAMES anywhere — including in a tool result a grep printed.

    Decoded from the JSON, not scanned off raw lines. A JSONL record holds `\n` as a two-character
    escape, so a line-wise regex reads `\nsrc/pkg/mod.py` as a token beginning `nsrc/`: measured on
    one real transcript, 10 of 477 tokens were real paths mangled that way. It decided outcomes — the
    same 40 fabricated rows exited 1 or 0 depending on whether the grep output happened to be
    indented."""
    out: set[str] = set()
    for f in files:
        for rec in _records(f):
            text = (json.dumps(rec, ensure_ascii=False)
                    .replace("\\n", "\n").replace("\\t", "\t"))
            for m in re.finditer(r"[\w./-]+\.[A-Za-z0-9]+", text):
                out.add(_norm_path(m.group(0)))
            for m in re.finditer(r"(?:[\w./-]*/)?(?:" + "|".join(_EXTENSIONLESS) + r")\b", text,
                                 re.I):
                out.add(_norm_path(m.group(0)))
    return {p for p in out if p}


def _resolves(claimed: str, pool: set[str]) -> bool:
    """Is `claimed` one of `pool`?

    SYMMETRIC, because the sides disagree about absoluteness in both directions: a transcript may
    hold `/repo/a/b.py` where a verdict cites `a/b.py`, and a verdict may cite an absolute path
    where the transcript holds the relative one.

    A bare BASENAME never matches on suffix alone. `config.py` would otherwise resolve against
    `vendor/thirdparty/junk/config.py` and clear a row that cited a file nobody opened — the check
    would report clean on exactly the shape it exists to catch. A one-segment claim must match
    whole."""
    c = _norm_path(claimed)
    if not c:
        return False
    normed = {_norm_path(p) for p in pool}
    if c in normed:
        return True
    if "/" in c:
        return any(p.endswith("/" + c) or c.endswith("/" + p) for p in normed)
    # A one-segment claim (`config.py`, `Makefile`) matches on basename ONLY when the pool holds
    # exactly one file with that name. Two candidates and the claim cannot say which was read; zero
    # is a genuine miss. Matching any suffix would clear a row that cited `config.py` against a
    # `vendor/thirdparty/junk/config.py` nobody opened — clean on the shape this exists to catch.
    same_name = {p for p in normed if p.rsplit("/", 1)[-1] == c}
    return len(same_name) == 1


def _fabricated_evidence(rows: list[dict], agent_dir: Path) -> VerdictLint:
    """What the transcript says about files a row CITES but the agent never opened.

    A `VerdictLint`, not a `(list, list)` pair, for the reason that class already exists: both slots
    are empty on the happy path, so a swapped return reads as correct behaviour and no test can tell
    the difference. `tests/test_cli_contract` refuses the positional shape by name."""
    files = _agent_transcript_files(agent_dir)
    opened = _opened_files(files)
    mentioned = _mentioned_files(files)
    if not files:
        # Name the directory that DOES work. The lead is handed
        # `<session>/tasks/<id>.output` at dispatch and has to guess that the readable copies live
        # in `<session>/subagents/`; "holds no .jsonl" told it neither.
        sibling = agent_dir.parent / "subagents"
        hint = (f" Did you mean {sibling}? That is where this harness keeps the readable per-agent "
                f"files; the `tasks/` directory a dispatch result names holds the same JSONL under "
                f"a different suffix." if sibling.is_dir() and sibling != agent_dir else "")
        return VerdictLint(problems=[
            f"--agent-transcripts {agent_dir} holds no per-agent transcript "
            f"({' or '.join(_AGENT_TRANSCRIPT_GLOBS)}) — nothing to check evidence against.{hint}"])
    claimed: dict[str, int] = {}
    for r in rows:
        for hit in _claimed_files(r):
            claimed[hit] = claimed.get(hit, 0) + 1
    # A file in EITHER set is not a ghost. Testing `mentioned` alone accused two real, opened files
    # on a live pass: `mentioned` is built from path-shaped tokens with a dot in them, so
    # `Makefile` — which the agent had genuinely opened with `Read` — never entered it.
    ghosts = sorted(f for f in claimed if not _resolves(f, mentioned | opened))
    unopened = sorted(f for f in claimed
                      if f not in ghosts and not _resolves(f, opened))
    found = VerdictLint()
    if ghosts:
        found.problems.append(
            f"{len(ghosts)} file(s) are cited as evidence but appear NOWHERE in the "
            f"{len(files)} transcript(s) given: {', '.join(ghosts[:8])}"
            f"{' …' if len(ghosts) > 8 else ''}. A cited anchor is a statement about your own work; "
            f"{sum(claimed[g] for g in ghosts)} row(s) rest on one. Pass the transcripts of EVERY "
            f"skeptic in the pass — rows are pooled across all of them, so a missing transcript "
            f"reads exactly like a fabricated citation.")
    if unopened:
        found.notes.append(
            f"{len(unopened)} file(s) are cited as evidence and appear in the transcript only as "
            f"TEXT — printed by a grep or a listing — never as a file this agent opened: "
            f"{', '.join(unopened[:8])}{' …' if len(unopened) > 8 else ''}. Weaker than the line "
            f"above and not proof of anything: a skeptic may read a range through a shell verb this "
            f"cannot see. It is the shape the fabricating pass had — 40 claims settled in 95 seconds "
            f"off one directory-wide grep — so {sum(claimed[u] for u in unopened)} row(s) are worth "
            f"a second look.")
    return found


def _repo_of(*paths: str | None) -> Path | None:
    """The repo a `<repo>/.coyomap/...` path belongs to — the first of `paths` that names one.

    Every input these verbs take lives under `.coyomap/`: the map, the pinned worklist, the verdict
    files. So the project is always knowable from an argument, and never has to be guessed from the
    working directory — which is a different project whenever a coyomap clone is driving the build.
    None when no argument names one, and then the caller falls back to cwd as before."""
    for path in paths:
        if not path:
            continue
        parts = Path(path).resolve().parts
        if ".coyomap" in parts:
            return Path(*parts[:parts.index(".coyomap")])
    return None


def _resolve_agent_dir(agent_dir: str | None, env: Mapping[str, str] | None,
                       repo: Path | None = None, home: Path | None = None) -> str | None:
    """`--agent-transcripts`, or this session's own sub-agent directory when it can be found.

    THE SESSION ID COMES FROM `env`, never straight from the process: three tests that lint
    throwaway files failed in any Claude Code session that had spawned a sub-agent, because the
    lint picked up THAT session's transcripts and rejected a citation they never held.

    `repo` is WHICH PROJECT'S transcripts, and it must be the repo the work is about rather than
    wherever the command was typed. Run from a coyomap clone against another repo's map, the cwd
    default read the CLONE's session — 26 transcripts of coyomap's own development. In `report`
    that printed coyomap's own components inside a report about a different product; in `lint` it
    exits 1 with `28 file(s) are cited as evidence but appear NOWHERE in the 59 transcript(s)
    given`, accusing 28 real files of fabricated citations. BOTH verbs pass it now, derived from
    the map, the worklist or the verdict files — every one of which lives under `<repo>/.coyomap/`."""
    if agent_dir is not None:
        return agent_dir
    sid = (os.environ if env is None else env).get(SESSION_ENV)
    found = (session_agent_transcripts(repo or Path.cwd(), session_id=sid, home=home)
             if sid else None)
    if found is None:
        return None
    print(f"agent transcripts: {found} (this session's, found without --agent-transcripts)",
          file=sys.stderr)
    return str(found)


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    """`env` is the process environment the verb reads its session id from (`lint` defaults
    `--agent-transcripts` to the running session's sub-agent transcripts). Injected, not read
    straight off the process, so a caller — a test linting two throwaway files inside a Claude Code
    session — can say "no session" with `env={}` instead of clearing a variable behind the verb's
    back. `None` reads the real environment, as the command line does."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    verb, rest = argv[0], argv[1:]
    if verb not in ("write", "report", "lint", "by-element", "refutations"):
        print(f"ERROR: unknown verb '{verb}' (expected `write`, `report`, `by-element`, "
              f"`refutations` or `lint`)\n\n{USAGE}",
              file=sys.stderr)
        return 2
    # Same hole `coyomap fix` had: the option loop below rejects `--help` as an unknown option.
    helped = subverb_help.handle(USAGE, verb, rest)
    if helped is not None:
        return helped
    worklist_path = out_path = map_path = agent_dir = None
    expect: list[str] = []
    verdicts: list[str] = []
    note = ""
    note_file: str | None = None
    keep_note = False
    as_json = False
    partial = False
    note_cites_other_runs = False
    only_kind = ""
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--agent-transcripts":
            i += 1
            if i >= len(rest):
                print("ERROR: --agent-transcripts needs a directory", file=sys.stderr)
                return 2
            agent_dir = rest[i]
        elif a == "--json":
            as_json = True
        elif a == "--partial":
            partial = True
        elif a == "--keep-note":
            keep_note = True
        elif a == "--note-cites-other-runs":
            note_cites_other_runs = True
        elif a in ("--worklist", "--verdicts", "--out", "--note", "--note-file", "--map",
                   "--kind"):
            i += 1
            if i >= len(rest):
                print(f"ERROR: {a} needs a value", file=sys.stderr)
                return 2
            if a == "--worklist":
                worklist_path = rest[i]
            elif a == "--map":
                map_path = rest[i]
            elif a == "--kind":
                only_kind = rest[i]
            elif a == "--verdicts":
                # VARIADIC, as the usage line has always said (`--verdicts <raw.json>...`): swallow
                # every following non-flag path, not just one. It took exactly one value, so the
                # documented spelling `--verdicts a.json b.json` died on
                # `unknown option(s): b.json` — while `write` and `report` are routinely handed
                # thirty files, and a build that trusted the usage line got an error instead of a
                # run. All three verbs share this loop, so all three were wrong together.
                verdicts.append(rest[i])
                while i + 1 < len(rest) and not rest[i + 1].startswith("-"):
                    i += 1
                    verdicts.append(rest[i])
            elif a == "--out":
                out_path = rest[i]
            elif a == "--note-file":
                note_file = rest[i]
            else:
                note = rest[i]
        elif a == "--expect":
            i += 1
            expect += [x for x in rest[i].split(",") if x.strip()] if i < len(rest) else []
        else:
            return subverb_help.usage_error(USAGE, verb, f"unknown option(s): {a}")
        i += 1
    if verb == "lint":
        # LINT NEEDS ONLY THE VERDICTS. Requiring a worklist and a map here would put it at the end
        # of the build again, which is the whole thing it exists to move earlier.
        if not verdicts:
            print("ERROR: grounding lint needs at least one --verdicts <file>", file=sys.stderr)
            return 2
        # `--expect` NAMES THE BATCHES THAT MUST HAVE LANDED. Without it this command lints the
        # files that happen to exist and cannot see a batch that produced none, so a fan-out whose
        # last skeptic was still writing linted clean: one live run printed
        # `VERDICTS OK — 18 file(s) well-formed` while a nineteenth was seconds from landing, and
        # five verdict-consuming commands then ran against the incomplete set and were redone.
        # A missing file is the one failure a reader cannot spot by eye, because nothing is there.
        if expect:
            # A CLOSER FILE IS NAMED BY ITS AGENT, NOT BY A BATCH. `--expect` names the skeptic
            # batches that must have landed, and `closer-<agent id>.json` matches none of them —
            # harmless, until someone writes `--expect closer` and reads the silence as a pass. Both
            # prefixes are stripped, so a closer file can be expected by the name it actually has.
            have = {Path(v).stem.replace("verdicts-", "", 1).replace("closer-", "", 1)
                    for v in verdicts}
            missing = [b for b in (x.strip() for x in expect) if b and b not in have]
            if missing:
                print(f"VERDICTS INCOMPLETE — {len(missing)} expected batch(es) have no verdicts "
                      f"file: {', '.join(missing)}", file=sys.stderr)
                print("The fan-out has not finished, or an agent returned without writing. Do NOT "
                      "run anchor-drift, apply-drift or grounding write yet: each consumes the "
                      "verdict set and would have to be redone.", file=sys.stderr)
                return 1
        agent_dir = _resolve_agent_dir(agent_dir, env,
                                       _repo_of(map_path, worklist_path, *verdicts))
        lint = lint_verdicts(verdicts, Path(agent_dir) if agent_dir else None)
        problems = lint.problems
        for n in lint.notes:
            print(n, file=sys.stderr)
        if problems:
            print(f"VERDICTS FAILED — {len(problems)} problem(s)", file=sys.stderr)
            for pr in problems:
                print(f"  - {pr}", file=sys.stderr)
            print("Fix these before `grounding write`; it refuses the same shapes at the END of "
                  "the build, where the skeptic that produced them is a hundred turns gone.",
                  file=sys.stderr)
            return 1
        # SAY WHAT WAS CHECKED, not just that nothing failed. With `--agent-transcripts` this
        # printed the same "well-formed" line as without it, so a run that tested 16 of 949 rows
        # and a run that tested none were indistinguishable — and the operator read the silence as
        # a clean bill of health on the whole pass. The evidence check can only speak about a note
        # that NAMES a file it read; that number belongs on screen beside the verdict.
        lint_rows, _ = load_verdicts(verdicts)
        rows_total, rows_testable = _read_claim_coverage(lint_rows)
        # SAY WHEN APPEALS ARE IN THE PILE. A closer row loads like any other and is counted by
        # nothing as a vote, so a run over 38 skeptic files and a run over 38 plus two closer files
        # printed the same line — and `--expect` cannot see the difference either.
        closer_rows = split_closer_rows(lint_rows).closer
        print(f"VERDICTS OK — {len(verdicts)} file(s) well-formed, {rows_total} verdict row(s)"
              + (f" of which {len(closer_rows)} are CLOSER appeals (uphold / reject / unsure), "
                 f"which vote on nothing and settle refutations the skeptics cast"
                 if closer_rows else "")
              + ("; pass --agent-transcripts <dir> to also check that every note claiming a read "
                 "is backed by the agent's transcript" if not agent_dir else
                 f"; evidence check covered {rows_testable} of {rows_total} row(s) — every row "
                 f"citing a file, in `evidence` or in a `read <file>` note. A row anchored on a "
                 f"SYMBOL, or on a filename this does not recognise, cannot be tested this way"))
        return 0

    if verb == "refutations":
        # NO --worklist. This walks the verdicts against the LIVE map, so it needs no pinned
        # snapshot — which is what lets `finalize` run it with the verdict files a build already
        # has, at the point where a captured worklist may be several reconciles out of date.
        if not map_path or not verdicts:
            print(f"ERROR: grounding refutations needs --map and at least one --verdicts",
                  file=sys.stderr)
            return 2
        try:
            live = load_model(resolve_map_path(map_path).read_text(encoding="utf-8"))
        except (OSError, ModelError) as e:
            print(f"ERROR: --map {map_path} could not be read as a map ({e})", file=sys.stderr)
            return 2
        rows, notes = load_verdicts(verdicts)
        for n in notes:
            print(n, file=sys.stderr)
        surviving = surviving_refutations(live, rows)
        # DEFAULT tier here, deliberately, unlike `write` above. This surface feeds the COVERAGE
        # list only — the refutation GATE beside it walks the verdicts directly and is unaffected.
        # Widening it to the behavioural tier would add every flow step and crossing to a list a
        # reader scans for gaps, which is a different report; `by-element --with-behavioural` is
        # where that question belongs.
        checks, _unresolved = element_checks(live, [w.claim for w in l2_worklist_model(live)], rows)
        print(format_refutations(surviving, [c for c in checks if c.unseen],
                                 as_json=as_json, m=live, grounding_rows=rows))
        # BLOCKING on a survivor, ADVISORY on a label the pass does not support. The second is a
        # judgement about wording; the first is the map asserting something its own skeptics
        # disproved, which is the one shape here that makes the map wrong rather than unclear.
        # An access dissent no closer ruled on blocks too: its remedy is one closer brief away.
        unheard = [d for d in access_dissent(live, rows) if not d.closed]
        return 1 if surviving or unheard else 0

    if verb == "by-element" and not worklist_path and verdicts:
        # `--worklist` OPTIONAL here, and only here. `finalize`'s advisory prints a count and then
        # names this command as where the list lives — but `finalize` reaches the count through
        # `grounding refutations`, which walks the LIVE map on purpose ("a captured worklist may be
        # several reconciles out of date"), while this verb required the PINNED file. On the
        # 2026-08-29 mcpolis map the two answered 1 and 7 about the same map, because six elements
        # had been reworded after the pin: measured against the pinned text their votes no longer
        # pair, measured against the live text they do. Neither number is wrong and the remedy could
        # not reproduce the finding it was offered for. With no `--worklist`, this now asks
        # `finalize`'s question; with one, it asks "what did the SKEPTICS see", which is the other
        # honest question and is why the flag stays.
        pass
    elif not worklist_path or not verdicts:
        print(f"ERROR: --worklist and at least one --verdicts are required\n\n{USAGE}",
              file=sys.stderr)
        return 2
    # `--note` is required for a real record, and a re-run therefore had to re-supply a note that
    # already existed. A live build did it through a nested `$(python -c …)` that re-extracted a
    # ~1900-character note out of the previous fragment and pushed it back through the shell — it
    # survived, but a note containing a quote or a backtick would not have. Two ways out that never
    # touch the shell: read it from a file, or keep the one already in `--out`.
    if keep_note and (note_file or note):
        other = "--note-file" if note_file else "--note"
        print(f"ERROR: --keep-note reuses the note already in --out; {other} supplies a new one. "
              f"Pick one — silently discarding the note you typed is worse than refusing.",
              file=sys.stderr)
        return 2
    if note_file:
        try:
            note = Path(note_file).read_text(encoding="utf-8").strip()
        except OSError as e:
            print(f"ERROR: --note-file {note_file} could not be read ({e})", file=sys.stderr)
            return 2
        if not note:
            print(f"ERROR: --note-file {note_file} is empty", file=sys.stderr)
            return 2
    if keep_note:
        if not out_path:
            print("ERROR: --keep-note reads the note from the existing --out fragment, so --out is "
                  "required.", file=sys.stderr)
            return 2
        prior = Path(out_path)
        existing = ""
        if prior.exists():
            try:
                doc = json.loads(prior.read_text(encoding="utf-8"))
                existing = str((doc.get("grounding") or {}).get("note") or "")
            except ValueError as e:
                print(f"ERROR: {out_path} is not valid JSON ({e})", file=sys.stderr)
                return 2
        if not existing:
            print(f"ERROR: --keep-note found no note in {out_path} — pass --note or --note-file "
                  f"for the first write.", file=sys.stderr)
            return 2
        note = existing
        print(f"note: reusing the {len(existing)}-character note already in {out_path}.",
              file=sys.stderr)
    claims = _worklist_claims(Path(worklist_path)) if worklist_path else []
    if not claims and worklist_path:
        print(f"ERROR: {worklist_path} holds no worklist claims — pass `coyomap audit <map> --json`",
              file=sys.stderr)
        return 2
    rows, notes = load_verdicts(verdicts)
    for n in notes:
        print(n, file=sys.stderr)
    live_claims = None
    live_model = None
    if verb == "by-element" and not map_path:
        # by-element resolves each claim back onto an ELEMENT, so it cannot run without the map the
        # claims are about. Refusing beats reporting an empty table that reads like "nothing was
        # checked" — the exact false-negative shape this command exists to expose.
        print("ERROR: grounding by-element needs --map <project-map.json> — it resolves each "
              "pinned claim back onto the element that makes it.", file=sys.stderr)
        return 2
    if map_path:
        # The LIVE claim surface, read from the assembled map this record describes. Not a second
        # captured file: a file goes stale between capture and write, and the whole defect here is a
        # record describing a surface that moved.
        try:
            live_model = load_model(resolve_map_path(map_path).read_text(encoding="utf-8"))
            # AT THE PINNED WORKLIST'S OWN TIER. Computing the live surface at the default tier
            # while the pin was behavioural reports every behaviour claim as superseded and makes
            # the digest describe a surface nobody pinned.
            behavioural = bool(worklist_path) and worklist_is_behavioural(Path(worklist_path))
            live_claims = [w.claim
                           for w in l2_worklist_model(live_model, behavioural=behavioural)]
        except Exception as e:
            print(f"ERROR: --map {map_path} could not be read as a map ({e})", file=sys.stderr)
            return 2
    # A SECOND WAVE, folded into the pin for the report and the record alike: verdicts on claims the
    # shipped map makes and the pin never held. `write` rewrites the pin file only once the record
    # is accepted, below.
    wave: list[str] = []
    if live_claims is not None and worklist_path and verb in ("report", "write"):
        wave = second_wave(claims, rows, live_claims)
    if verb == "by-element":
        assert live_model is not None   # guarded above: --map is required for this verb
        # With no `--worklist` the surface is the LIVE map's, which `--map` guarantees is populated.
        surface = claims if worklist_path else (live_claims or [])
        checks, unresolved = element_checks(live_model, surface, rows)
        print(format_element_checks(checks, unresolved, as_json=as_json,
                                    only_kind=only_kind))
        return 0
    if verb == "report":
        # THE AGENTS' OWN CLOSING MESSAGES, read with the same discovery `lint` uses — so the
        # channel is read by default on a build, and by name (`--agent-transcripts`) afterwards.
        # Keyed on the MAP'S OWN REPO, the way `finalize` derives it, and not on the directory the
        # command was typed in: those differ whenever a coyomap clone is driving another repo's
        # build, and the cwd answer is another product's agents.
        report_agent_dir = _resolve_agent_dir(
            agent_dir, env, _repo_of(map_path, worklist_path, *verdicts))
        for fault in closer_faults(rows):
            print(f"WARNING: {fault}", file=sys.stderr)
        print(format_report(claims, rows, as_json=as_json, live_claims=live_claims,
                            agent_dir=Path(report_agent_dir) if report_agent_dir else None))
        # NAME THE NEXT VERB, HERE. This report is what the closing note is written FROM, so a lead
        # reading it is standing exactly at the start of the close — and `ship` runs that whole
        # close in one command. It was reached for ZERO times on the 2026-09-02 build, which then
        # hand-typed the thirteen steps over 57 turns: the verb appears once in `method.md`, inside
        # a document read 540 turns earlier and never reopened, and sits on help line 62 under a
        # `head -60`. It was never unreachable for a bad reason; it was just never in front of
        # anyone at the moment it mattered. A build follows the `Next:` lines the tools print.
        if not as_json:
            # THE NUMBERS, HERE, WHERE THE NOTE IS WRITTEN. This block was printed only by
            # `grounding write` — that is, only by the run that REFUSES the note — so the first
            # note of every build was written from figures computed by hand. On the 2026-09-13
            # reminderrepo build the lead globbed one theme's verdict files and wrote "128
            # redundant rows" against the pass's real 256; `ship` died at step 6 and the second
            # attempt was the first time these numbers were on screen. `ship` PREPARE ends on this
            # report, so printing them here puts them in front of the author before the first try.
            # Errors are discarded on purpose: a report is a READ, and `write` is where a refusal
            # belongs.
            record, _errors = build_record(claims + wave, rows, live_claims=live_claims)
            print("\n" + note_facts_block(claims + wave, rows, record, live_claims))
            print("\nNext: coyomap ship <repo> --note-file <the note you write from this report> "
                  "— the whole closing sequence in one command, stopping at the first failing step "
                  "and naming every step that did not run.")
        return 0
    claims = claims + wave
    record, errors = build_record(claims, rows, note, live_claims=live_claims, partial=partial)
    # AN UNREADABLE APPEAL WORD, REFUSED HERE. `grounding lint` catches it too, and `ship` never
    # runs `grounding lint` — `method.md` schedules that at COLLECTION, before the closer is even
    # dispatched, so on the reviewed build it read 38 verdict files and 0 closer files. A guard
    # nothing reaches is not a guard, and this is the step every closing sequence does run.
    errors = list(errors) + closer_faults(rows)
    # REFUSE, having been a warning and having failed as one. This used to warn, on the argument
    # that prose has more shapes than a regex — a note citing only EARLIER builds' figures states a
    # number this pass does not have and is honest. That case is already covered by the "any
    # occurrence clears it" rule inside each check: a note that also quotes this pass passes. What
    # the warning did not cover is the case it was built for. The redundant-row error was found by
    # one retrospective, marked fixed by printing the right number, and shipped again on the next
    # map; the anchor-unanimity claim then shipped on a third. A warning on stderr, inside a build
    # that prints thousands of lines, is not seen.
    #
    # The note is a PERMANENT record and goes into the commit message, so a wrong number here
    # outlives every other artifact of the run, and the fix in each message is one word. That is the
    # bar for blocking: silent, durable, and cheap to correct.
    # The agreement claim warns and never refuses — see `_agreement_contradictions` for why a regex
    # may not block on an assurance. Printed first, so it is not buried under a refusal.
    for line in _agreement_contradictions(note, rows):
        print(f"WARNING: {line}", file=sys.stderr)
    note_faults = _note_contradictions(note, rows, record, live_claims)
    if note_faults and note_cites_other_runs:
        # The operator has ASSERTED that the numbers in the note are about other runs, or are
        # theme-scoped. Warn and continue — the same escape `--partial` is, for the same reason:
        # the tool cannot read which pass a sentence is about, and the operator can.
        for line in note_faults:
            print(f"WARNING: {line}", file=sys.stderr)
        print(note_facts_block(claims, rows, record, live_claims), file=sys.stderr)
    elif note_faults:
        errors = list(errors) + [
            f"the `--note` contradicts this pass's own numbers. {line}" for line in note_faults]
        errors.append(
            "If the numbers in the note are about OTHER runs, or are scoped to one theme rather "
            "than the whole pass, pass `--note-cites-other-runs` to say so and this becomes a "
            "warning.")
        # The numbers to fix it with, in the same breath as the refusal. Without this the operator
        # is told the note is wrong and not what right would be, and the next attempt is a guess.
        print(note_facts_block(claims, rows, record, live_claims), file=sys.stderr)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print("REFUSED: the record would misstate what was challenged; nothing was written.",
              file=sys.stderr)
        return 1
    payload = {"grounding": record}
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if wave and worklist_path and live_model is not None:
        by_claim = {w.claim: w for w in l2_worklist_model(
            live_model, behavioural=worklist_is_behavioural(Path(worklist_path)))}
        first = repin_second_wave(Path(worklist_path), [by_claim[c] for c in wave])
        print(f"second wave: {len(wave)} claim(s) the pin never held have verdicts; they are now "
              f"pinned in {worklist_path} (the first pin is kept as {first.name}).",
              file=sys.stderr)
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out_path}: {record['claims_challenged']} of {record['claims_total']} claim(s) "
              f"challenged — {record['claims_confirmed']} confirmed, {record['claims_refuted']} "
              f"refuted, {record['claims_unverifiable']} unverifiable"
              + (f" · vs the live map: {record['claims_superseded']} superseded, "
                 f"{record['claims_added_since']} added since the pin" if live_claims is not None
                 else " · no --map, so the record does not state how the live map differs"))
        # SAY IT AT THE MOMENT IT HAPPENS. The line above is the pinned pass and reads as complete
        # even when the shipped map is not; a build that saw only that line wrote "All 209 claims
        # were challenged" into a permanent note. `anchor-drift` had already said 199 of 209 ten
        # turns earlier, and nothing tied the two together.
        # THE NUMBERS A NOTE WILL CITE, COMPUTED, so nobody retypes one from an earlier view.
        #
        # `--note` is free prose in a permanent record and in the commit message, and nothing
        # checks it. One shipped note said "Eighteen fresh-context skeptics" about a build that
        # dispatched 17 and produced 20 verdict labels: the 18 was read off a `grounding lint`
        # line printed while one verdict file was still being written, then carried forward. The
        # same note said "Four superseded claims had been CONFIRMED" where this report counts 11,
        # leaving seven deliberate overrides of settled claims undisclosed. Both numbers were
        # available here, at the moment the note was written.
        print(note_facts_block(claims, rows, record, live_claims))
        live_done = record.get("claims_live_challenged")
        if live_claims is not None and isinstance(live_done, int):
            live_total = len(set(live_claims))
            if live_done < live_total:
                unvoted = live_total - live_done
                added = record.get("claims_added_since")
                print(f"  NOTE: the SHIPPED map carries {live_total} claim(s), of which "
                      f"{live_done} have a verdict — {unvoted} do NOT. "
                      + unvoted_reason(unvoted, added if isinstance(added, int) else 0)
                      + " Challenge them in a second wave (`coyomap audit <map> --batches "
                      "<verify dir> --since <pinned worklist>`, then re-run this), or say so in "
                      "`--note`: `claims_challenged` counts the pinned worklist and will keep "
                      "reading as full coverage.")
    elif as_json:
        print(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
