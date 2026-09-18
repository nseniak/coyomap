"""`coyomap-eval live-numbers` — do the tools' present-tense sentences about a LIVE map still hold?

THE CLASS THIS EXISTS FOR. A number written into a comment or a docstring — "142 entities, 46 of
them saved", "4 of the 7 features have two or more drivers" — is a measurement of a map that keeps
being rebuilt. The code stays right and the sentence stops being true, so no gate can see it: every
instance IS the code doing exactly what the code says. Measured on 2026-09-07 over `tools/coyomap/`
and `eval/tools/coyomap_eval/`: of 739 number-claims in prose, 665 record a PAST build and cannot
rot; 35 describe a live map today, and **23 of the 27 that could be decided were wrong**.

WHY THE OBVIOUS CHECK IS NOT WHAT THIS IS. A checker that reads prose and works out which
computation produced the number has to GUESS, and three advisories written that way on 2026-09-06/07
each missed the exact defect they were written for. This reads no prose. A person writes the
sentence twice — once in the code, once here as `quote` — and a `measure` regenerates it from the
map. There is nothing to infer, so there is nothing to infer wrongly.

ONE RULE FOR WHAT MAY BE A ROW, and it is the whole reason this file is short. **A measure calls
the product's own function — the one the sentence sits on, or the one that produced its number.** It
never reimplements what the sentence seems to count. An adversarial review of the first cut found
19 of 30 rows defective, and every one of them was a hand-written recount that had drifted a step
away from the thing described: markers looked up by the wrong spelling, an advisory's aggregate line
counted as instances, a sub-flow matched by substring onto a different sub-flow. The two rows that
survived that review were the two that called the real function. A sentence with no function to call
is recorded in `NOT_MECHANISED` instead, with the reason — a smaller ledger that can be trusted
beats a longer one that cannot.

THE THREE WAYS A ROW CAN GO WRONG, and all three are caught:

    the map moved      -> `measure` no longer returns `quote`                  STALE
    the comment moved  -> `quote` no longer appears at `site`                  DRIFTED
    only this file was edited -> the quote here stops matching the file        DRIFTED

That last one is the failure this whole class came from: three of the six defects of 2026-09-07
were a number corrected in a markdown file and left wrong in the code beside it. A ledger that
stored the number ALONE would repeat it. Storing the SENTENCE, and demanding the file still
contains it, does not.

NOT A GATE, and deliberately not in `make gates`. Two of the maps live outside this repo, so most
rows cannot run in CI at all — and a rebuild of any map legitimately moves these numbers. Run it
after a build, or when a retro comes round. Exit 1 on any stale row so a deliberate run can be
piped; a run with maps missing still exits 0 for the rows it skipped."""
from __future__ import annotations

import collections
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

USAGE = """usage: coyomap-eval live-numbers [--map NAME=PATH ...] [--repo DIR] [--json] [--list]

Re-measure every present-tense sentence the tools write about a LIVE map.

  --map NAME=PATH   supply one map. NAME is `coyomap`, `argus` or `mcpolis`. Repeatable.
                    `coyomap` defaults to the repo's own .coyomap/project-map.json.
  --repo DIR        the coyomap checkout whose prose is being checked (default: cwd).
  --list            print the ledger without measuring anything.
  --json            machine-readable rows.

Rows whose map was not supplied are SKIPPED, never failed. Exit 1 if any row is stale or drifted."""

# The logical map names a row may ask for. A row names the map its sentence names — never "some
# live map", because a sentence that does not say which map it counted cannot be re-measured.
MAP_NAMES = ("coyomap", "argus", "mcpolis")


@dataclass(frozen=True)
class Claim:
    """One present-tense sentence in the tools, and the way to regenerate it from the map.

    `quote` is the sentence AS IT APPEARS in the code, its number included, with comment markers
    stripped and whitespace collapsed. `measure` must return a string of exactly that shape. The
    row holds the number once; the file holds it once; nothing else does."""
    site: str                                   # "tools/coyomap/model.py:832"
    maps: tuple[str, ...]                       # the maps `measure` needs, all of them required
    quote: str                                  # verbatim in the file at `site`, markers stripped
    measure: Callable[[dict], str]              # {name: ProjectModel} -> the same sentence
    note: str = ""                              # why the sentence is there, for the report
    #: Why this row's measure may change WORDS and not only figures. Empty for almost every row,
    #: and that emptiness is enforced: a measure that quietly rewords its sentence can never match
    #: it, so the row reports STALE forever for a reason that is not staleness — one row was found
    #: doing exactly that. Setting this says the rewording is READ OFF THE MAP, so a reader seeing
    #: the two versions side by side is being told the sentence needs rewriting, not renumbering.
    data_words: str = ""


@dataclass
class Row:
    claim: Claim
    verdict: str                                # holds | STALE | DRIFTED | skipped | ERROR
    measured: str = ""
    detail: str = ""


# --- normalising prose so a quote can be matched against a file -------------------------------
_MARKER = re.compile(r"^\s*(#:|#|//|\*)\s?")


def normalise(text: str) -> str:
    """Comment markers off, whitespace collapsed — the form a `quote` is written in and the form a
    file is searched in. Both sides go through THIS function, so a rewrapped comment still matches
    and only a changed WORD counts as a change."""
    lines = [_MARKER.sub("", ln) for ln in text.split("\n")]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def quote_is_present(repo: Path, claim: Claim) -> tuple[bool, str]:
    """Does `claim.quote` still appear in the file `claim.site` names?

    The whole file is searched, not the recorded line: a comment survives the code around it
    moving, and a row whose only fault is a shifted line number is not a finding. The line IS
    reported back when it has moved, so the ledger can be re-pinned."""
    path_part, _, line_part = claim.site.rpartition(":")
    if not path_part or not line_part.isdigit():
        return False, f"site '{claim.site}' is not `path:line`"
    path = repo / path_part
    if not path.is_file():
        return False, f"{path_part} does not exist"
    text = path.read_text(encoding="utf-8", errors="replace")
    if normalise(claim.quote) not in normalise(text):
        return False, f"the sentence is no longer in {path_part}"
    # Where is it now? Find the first line whose forward window contains the quote.
    lines = text.split("\n")
    want = normalise(claim.quote)
    # The window has to be wider than the quote or a long quote never fits inside one and the
    # search silently finds nothing to re-pin. Its own line count plus slack for re-wrapping.
    width = claim.quote.count("\n") + 12
    # The LAST window that still contains it — a fixed-width forward window starting anywhere in
    # the lines before the quote also contains it, and the first such start is not where the
    # sentence is. Taking the last one lands on the line the sentence actually begins.
    found = 0
    hits = 0
    for i in range(len(lines)):
        if want in normalise("\n".join(lines[i:i + width])):
            found = i + 1
            hits += 1
    if hits > width:
        # The same sentence written twice in one file: a re-pin would pick one of them silently,
        # and an edit to the other would go unreported.
        return True, f"appears more than once in {path_part} — the line pin is ambiguous"
    recorded = int(line_part)
    # EXACTLY, with no slack. A three-line tolerance let 12 of 30 rows sit on a line their sentence
    # is not on while the runner reported nothing moved, which makes the ledger a place a reader
    # cannot look things up.
    if found and found != recorded:
        return True, f"moved to {path_part}:{found} (ledger says {recorded})"
    return True, ""


# --- the measures -----------------------------------------------------------------------------
# EVERY ONE CALLS THE PRODUCT'S OWN FUNCTION. A measure that recounts by hand is a second copy of a
# rule, and a second copy drifts — that is what took out 19 of the first cut's 30 rows. Where the
# sentence describes something the product exposes no function for, there is no measure here and
# the sentence is listed in `NOT_MECHANISED` instead.

def _anchored_expanded_steps(maps: dict) -> str:
    from coyomap import model as M
    m = maps["coyomap"]
    anchored = 0
    keyed: set = set()
    flat: set = set()
    for f in m.flows:
        for container, st in M.expanded_steps_with_container(m, f):
            if (st.where or "").strip():
                anchored += 1
                keyed.add((f.uc, container, st.n))
                flat.add((f.uc, st.n))
    return (f"this repo's own map has {anchored} anchored expanded steps, {len(keyed)} distinct "
            f"`(uc, container, n)` keys — and only {len(flat)} distinct `(uc, n)` keys.")


def _saved_records_two_maps(maps: dict) -> str:
    from coyomap import model as M
    pair = ("argus", "mcpolis")
    entities = sum(len(maps[n].entities) for n in pair)
    saved = sum(len([e for e in maps[n].entities if M.is_saved(e)]) for n in pair)
    return f"Measured across the two live maps: {entities} entities, {saved} of them saved."


def _record_direction_gaps(maps: dict) -> str:
    """THE WHOLE SENTENCE, its trailing clause included. "both on argus" says which maps the gaps
    land on, and that is read off the map exactly as the counts are — so it is regenerated too,
    even though doing it changes WORDS. Clipping it instead was the tempting fix and the wrong one:
    the clause is false today, and a clipped clause is an unwatched clause. When the words differ,
    the report is telling a reader the sentence needs REWRITING, not renumbering, which is a truer
    thing to be told than a number that no longer has a sentence around it."""
    from coyomap import model as M
    from coyomap import validate_model as V
    pair = ("argus", "mcpolis")
    saved = sum(len([e for e in maps[n].entities if M.is_saved(e)]) for n in pair)
    hits = {n: V.record_direction_gaps(maps[n]) for n in pair}
    total = sum(len(v) for v in hits.values())
    on = [n for n in pair if hits[n]]
    if not on:
        where = "on neither map"
    elif len(on) == 1:
        where = f"{'both ' if total > 1 else ''}on {on[0]}"
    else:
        where = "on " + " and ".join(on)
    return f"Measured across the two live maps: {total} of {saved} saved records, {where}"


def _dashboard_steps(maps: dict) -> str:
    from coyomap import validate_model as V
    steps, walks = _dashboard(maps["mcpolis"], V)
    return (f"mcpolis's dashboard draws {steps} steps from {walks} different walks, and read as one "
            f"list they are noise.")


def _dashboard(m, V) -> tuple[int, int]:
    """The Dashboard interface's steps, grouped the way `interface_steps_by_use_case` groups them —
    the function both sentences describe. Raises if the interface is gone, so the row ERRORs rather
    than reporting a confident zero."""
    dash = next((i for i in m.interfaces if i.name == "Dashboard"), None)
    if dash is None:
        raise LookupError("mcpolis has no interface named 'Dashboard'")
    grouped = V.interface_steps_by_use_case(m).get(dash.id, [])
    return sum(len(s) for _, s in grouped), len(grouped)


def _shared_files(m, V) -> tuple[dict[str, list[str]], int, int]:
    """`component_file_owners` — the product's own answer to "which components claim this file"."""
    owners = V.component_file_owners(m)
    multi = {f: o for f, o in owners.items() if len(o) > 1}
    sizes = sorted(len(o) for o in multi.values())
    return multi, (min(sizes) if sizes else 0), (max(sizes) if sizes else 0)


def _shared_file_anchors(m, V) -> tuple[int, int]:
    """Through `site_components`, the call this sentence sits directly above in `views.py`.
    Splitting the anchor by hand instead was a third copy of `strip_anchor` — a copy that happened
    to agree on today's map and had no reason to keep agreeing."""
    owners = V.component_file_owners(m)
    total = 0
    shared = 0
    for rule in m.rules:
        for site in (rule.sites or []):
            total += 1
            if len(V.site_components(m, site, owners)) > 1:
                shared += 1
    return shared, total


def _rule_sites_in_shared_files(maps: dict) -> str:
    from coyomap import validate_model as V
    m = maps["coyomap"]
    multi, lo, hi = _shared_files(m, V)
    shared, total = _shared_file_anchors(m, V)
    return (f"On this repo's own map, {len(multi)} files are claimed by {lo}-{hi} components each "
            f"and hold {shared} of its {total} call-site anchors "
            f"({round(100.0 * shared / max(1, total))}%)")


def _rule_sites_short(maps: dict) -> str:
    from coyomap import validate_model as V
    m = maps["coyomap"]
    _, lo, hi = _shared_files(m, V)
    shared, total = _shared_file_anchors(m, V)
    return (f"on this repo's own map {round(100.0 * shared / max(1, total))}% of call-site anchors "
            f"sit in a file {lo}-{hi} components claim.")


def _role_use_cases_at_dashboard(maps: dict) -> str:
    """`interface_actor_use_cases` — the table `audit_model` itself builds the detail line from. The
    first cut re-derived the far side from steps and actors and answered 24 where the tool says 25,
    so a reader repairing the comment would have written a number the tool never produces."""
    from coyomap import validate_model as V
    m = maps["mcpolis"]
    dash = next((i for i in m.interfaces if i.name == "Dashboard"), None)
    if dash is None:
        raise LookupError("mcpolis has no interface named 'Dashboard'")
    per_role = V.interface_actor_use_cases(m).get(dash.id, {})
    top = max((len(v) for v in per_role.values()), default=0)
    return f"One role drove {top} use cases at mcpolis's dashboard"


def _entities_with_a_lifecycle(maps: dict) -> str:
    from coyomap.viewer import gen_viewer as GV
    n = 0
    for name in MAP_NAMES:
        for e in maps[name].entities:
            # `states_count` is the key the box builder reads — `Entity.states` is a StateMachine,
            # not a list, and its `states` is the list the count comes from.
            count = len(e.states.states) if (e.states and e.states.states) else 0
            if GV._lifecycle_line({"states_count": count}):
                n += 1
    return f"Rare by nature ({n} entities across three live maps)"


# --- the ledger -------------------------------------------------------------------------------
# ONE ROW PER SENTENCE, and a row exists only when a measure can call the product's own function
# for it. `quote` is copied from the file and must carry the WHOLE claim — its dating clause
# included. A quote clipped to the numbers is how a dated RECORD ended up watched as if it were a
# live claim, and the report then told a reader to "repair" a sentence that was true.

LEDGER: tuple[Claim, ...] = (
    Claim(site="tools/coyomap/model.py:932", maps=("coyomap",),
          quote="this repo's own map has 462 anchored expanded steps, 462 distinct "
                "`(uc, container, n)` keys — and only 337 distinct `(uc, n)` keys.",
          measure=_anchored_expanded_steps,
          note="the argument that `(uc, n)` alone silently merges two rows"),
    Claim(site="tools/coyomap/validate_model.py:1033", maps=("argus", "mcpolis"),
          quote="Measured across the two live maps: 135 entities, 45 of them saved.",
          measure=_saved_records_two_maps,
          note="why the check reads SAVED records and not every entity"),
    Claim(site="tools/coyomap/validate_model.py:974", maps=("argus", "mcpolis"),
          quote="Measured across the two live maps: 0 of 45 saved records, on neither map",
          measure=_record_direction_gaps,
          note="the map contradicting itself about a record's direction",
          data_words="'on neither map' names WHICH maps the gaps land on, read off the map the "
                     "same way the counts are. When a gap comes back the words change with it, and "
                     "that is the row saying the sentence needs rewriting, not renumbering"),
    Claim(site="tools/coyomap/validate_model.py:1178", maps=("mcpolis",),
          quote="mcpolis's dashboard draws 141 steps from 31 different walks, and read as one list "
                "they are noise.",
          measure=_dashboard_steps,
          note="why interface steps are grouped by story"),
    Claim(site="tools/coyomap/validate_model.py:1305", maps=("coyomap",),
          quote="On this repo's own map, 3 files are claimed by 3-4 components each and hold 5 "
                "of its 245 call-site anchors (2%)",
          measure=_rule_sites_in_shared_files,
          note="one of two 'measured facts that must not be designed away'"),
    Claim(site="tools/coyomap/views.py:584", maps=("coyomap",),
          quote="on this repo's own map 2% of call-site anchors sit in a file 3-4 components "
                "claim.",
          measure=_rule_sites_short,
          note="the same fact, second site"),
    Claim(site="tools/coyomap/audit_model.py:1322", maps=("mcpolis",),
          quote="One role drove 25 use cases at mcpolis's dashboard",
          measure=_role_use_cases_at_dashboard,
          note="why a detail line is capped through `shown` and never by hand"),
    Claim(site="tools/coyomap/viewer/gen_viewer.py:406", maps=MAP_NAMES,
          quote="Rare by nature (5 entities across three live maps)",
          measure=_entities_with_a_lifecycle,
          note="why a lifecycle marker costs the diagram nothing when absent"),
)

# Sentences of the same class with NO row, and the reason each has none. They are listed so a reader
# can see the gap rather than assume the ledger is complete — an unlisted omission is how a check
# comes to be trusted for more than it does.
#
# TWO ADVERSARIAL REVIEWS SHAPED THIS LIST. The first cut mechanised 30 of these sentences by
# hand-recounting what each seemed to say; 19 broke. The rebuild mechanised 14 by the calls-the-real-
# function rule; 4 more broke, every one of them a `max()` or a substring picking which map or which
# object the sentence "meant". Where a sentence names no map, or names a computation nothing
# implements, there is no rule that picks for it — so it is recorded here instead of guessed at.
NOT_MECHANISED: tuple[tuple[str, str], ...] = (
    # -- the sentence names no particular map, so any selection rule is a guess -------------------
    ("tools/coyomap/grammar.py:463",
     "'13 buckets on one live map' — the three live maps read 7, 13 and 17. max() reports STALE "
     "while argus satisfies the sentence exactly."),
    ("tools/coyomap/viewer/gen_viewer.py:390",
     "'one map: 47 PK, 52 FK, 50 optional' — per map: 27/26/69, 15/20/48, 7/19/103. Choosing by "
     "the largest total reports the map with the FEWEST primary keys under a sentence reading "
     "'every live map is full of these'."),
    ("tools/coyomap/viewer/viewer.js:8118",
     "'8 of 344 steps do' is a SMALL-fraction claim, and the map with the most such steps is the "
     "one where the block is fullest (mcpolis, 298 of 1084). Choosing by max() would paste a "
     "number into the comment that contradicts the sentence around it."),
    ("tools/coyomap/viewer/gen_viewer.py:2852",
     "'a use case walk is 16 steps stored and 27 shown' — an average over one map chosen by the "
     "widest gap, and argus's raw 27.406 is three expanded steps from rounding to 28."),
    # -- the sentence describes a computation nothing implements ----------------------------------
    ("tools/coyomap/features.py:72",
     "'24/41/32/102 such edges on the four live maps' — the component-shared inference is described "
     "as the thing NOT done, so there is no function to call."),
    ("tools/coyomap/model.py:222",
     "'one clean answer on 4 of coyomap's 11 surfaces and 1 of mcpolis's 12' — 'a clean answer' is "
     "the derivation the field exists BECAUSE the product does not do."),
    ("tools/coyomap/features.py:213",
     "'3 of coyomap's 11 read `out`' — the numerator means 'carry an `in` and nothing else', which "
     "no function answers. Measured by hand 2026-09-07 it is 0: no coyomap interface has any "
     "derived direction at all. The sentence is wrong today and cannot be watched mechanically."),
    ("tools/coyomap/features.py:467",
     "'coyomap's own is only 72.7% unique, with 5 files claimed by 2-5 components each' — this "
     "comment sits on an INLINE dict built from `c.files` raw, not on `component_file_owners`, "
     "which drops directory entries. The two agree on today's map and are not the same rule, so "
     "watching it through the function would be watching a different thing. The same fact IS "
     "watched at its other two sites, where the code does call the function."),
    ("tools/coyomap/grammar.py:818",
     "'33 of the 150 flows across the four live maps over the band' — needs the step-count band's "
     "own thresholds applied the way the harvest applies them; a copy here is a second copy of the "
     "rule."),
    ("tools/coyomap/viewer/viewer.js:8656",
     "'4 of the 15 actor pages that have steps at all' — the numerator is the viewer's own zoning "
     "of a happy path, computed in JS at render time."),
    ("tools/coyomap/viewer/viewer.js:9304",
     "'4 of the 7 features have two or more drivers' — drivers come from the viewer's `actorGroups`, "
     "whose two tie-break rules live only in JS."),
    ("tools/coyomap/validate_model.py:1929",
     "'~16 of 61 entry points are not triggers of anything a person does' — the comment sits on "
     "`unclaimed_external_entry_points`, which returns 0 today because the DERIVED arm claims them "
     "all. The sentence counts a different population (external minus triggered = 24 of 88), and "
     "the two denominators it could mean, 61 and 88, are both wrong. It needs rewording before it "
     "can be watched."),
    # -- the advisory does not report per instance ------------------------------------------------
    ("tools/coyomap/validate_model.py:2685",
     "'on the only live instance today it is the SECOND' — the advisory emits ONE aggregated line "
     "per map, so any count of its output counts maps, never instances. Its load-bearing half "
     "('the SECOND' of two named causes) is not in the output at all."),
    ("tools/coyomap/validate_model.py:4761",
     "'measured on the three live maps it fires exactly once' — `_check_capability_audience` emits "
     "two unrelated advisories and `len()` cannot separate them. `capability_audience` IS public, "
     "but it answers which AUDIENCES a capability has, not whether the advisory fired: measured "
     "2026-09-07 the advisory fires 0 times across the three maps (argus CAP8 is recorded as an "
     "exception) while `capability_audience` reports 1 mixed capability. The sentence is false "
     "today, and no single function answers the question it asks."),
    ("tools/coyomap/validate_model.py:4769",
     "'10 capabilities of 27 that already have several actors' — `capability_members` is public "
     "but returns use cases, not actors; nothing groups a capability's ACTORS. Measured by hand "
     "2026-09-07: 7 of 26."),
    # -- the sentence names a map that can no longer be opened -------------------------------------
    ("tools/coyomap/validate_model.py:3784",
     "'25 of 25 channels claimed no payload, with 134 entities available' — no map that loads on "
     "today's schema has a single messaging row, or 134 entities."),
    ("tools/coyomap/viewer/viewer.js:7957",
     "'one live map names 0 of 664' — the largest ways-in count on a loadable map is 207."),
    ("tools/coyomap/viewer/viewer.js:8308",
     "'381 elements across four live maps claim `verified`' — two of those four are in "
     "UNLOADABLE_MAPS, so the population cannot be assembled."),
    # -- the number is not a measurement ------------------------------------------------------------
    ("tools/coyomap/validate_model.py:6653",
     "'a live map answered 66 of these and wrote 15 distinct reasons' — 'distinct reasons' has no "
     "definition a tool can apply: the record's own emitted form puts the element id inside the "
     "reason, so any split makes reasons equal lines."),
    ("tools/coyomap/validate_model.py:5205",
     "'a live map carried 66 lines holding 15 distinct reasons' — the same sentence, same reason."),
    ("tools/coyomap/validate_model.py:6401",
     "'One live map wrote that footnote 67 times' — the footnote is prose inside a recorded "
     "section, not a countable row."),
    ("eval/tools/coyomap_eval/compare.py:550",
     "'mcpolis stamps 7 characters, coworker stamps 9' — the coworker map is not among the three, "
     "and `_same_commit` inlines the `-dirty` strip rather than exposing it."),
    # -- a DATED RECORD. Records do not rot, and watching one is worse than not watching it: the
    # -- report tells a reader to "repair" a sentence that is true about the build it names.
    ("eval/tools/coyomap_eval/profile.py:111",
     "'Measured the day the strict rule landed: mcpolis read 38 with interface_doors already at "
     "129' — its own words date it. Today the map reads 0 and 291, and both sentences are true."),
    ("eval/tools/coyomap_eval/profile.py:190",
     "'A live map scored 3/10 linked' — a named past incident, three units hosting an identical 50 "
     "components. No live map has ten deployment units."),
    ("tools/coyomap/validate_model.py:2853",
     "'open a session to a mounted server carries 3 such steps across 2 deps' — no sub-flow of that "
     "name exists; the sentence records what a worker found by hand during the migration."),
    ("tools/coyomap/validate_model.py:3145",
     "'Measured on the two mcpolis maps of 2026-09-02 and 2026-09-07: 0 person-facing walks fire "
     "on the first and 4 of 43 on the second' — dated to two named builds. This WAS a row until a "
     "review caught that its quote had been clipped past the dating clause, which is exactly how a "
     "record comes to be watched as a live claim."),
    # -- found by the second review, in neither list until now. All present-tense, all stale, all
    # -- reachable through public functions: they are rows waiting to be written, not exclusions.
    ("tools/coyomap/views.py:590",
     "NOT YET WATCHED. '47 of this repo's 114 anchored steps come from a sub-flow, and 26 (uc, n) "
     "pairs name more than one distinct step' — measured 165 of 462 and 99 pairs. It carries the "
     "SAME 114 as the watched row at model.py:837, 250 lines away."),
    ("tools/coyomap/validate_model.py:799",
     "NOT YET WATCHED. '12 of 74 entities, 9 of 18 deps are flow endpoints' — measured 28 of 59 "
     "and 13 of 16."),
    ("tools/coyomap/model.py:476",
     "NOT YET WATCHED. '1071 of the 1762 steps across the live maps' — measured 1480 of 2456."),
    ("tools/coyomap/validate_model.py:1044",
     "NOT YET WATCHED. 'argus 9→11 of 11, mcpolis 17→28 of 35' — measured argus 11 of 11, mcpolis "
     "33 of 34."),
    ("tools/coyomap/validate_model.py:854",
     "NOT YET WATCHED. '3 of 27 mixed; 26 of 27 unanimous' — measured 1 of 26 mixed."),
)

# Maps the sentences count that can no longer be OPENED by the tool that counts them. Any sentence
# saying 'the four live maps' or 'five maps' is partly unverifiable for this reason, not because it
# drifted.
UNLOADABLE_MAPS: tuple[tuple[str, str], ...] = (
    ("MEE6", "`grounding.claims_grounded` was renamed to `claims_challenged`"),
    ("distown", "`capabilities[].label` was split into `happy_path` and `audience`"),
)


# --- running ----------------------------------------------------------------------------------
def load_maps(paths: dict[str, Path]) -> dict:
    """Load each supplied map. `COYOMAP_SELF_MAP` is set for the duration, because coyomap's own
    map is one of the three and reading a clone's own `.coyomap/` is refused without it."""
    from coyomap import model as M
    before = os.environ.get("COYOMAP_SELF_MAP")
    os.environ["COYOMAP_SELF_MAP"] = "1"
    try:
        return {name: M.load_model_path(p) for name, p in paths.items()}
    finally:
        if before is None:
            os.environ.pop("COYOMAP_SELF_MAP", None)
        else:
            os.environ["COYOMAP_SELF_MAP"] = before


def run(repo: Path, maps: dict, ledger: tuple[Claim, ...] = LEDGER) -> list[Row]:
    """Every row: is the sentence still in the file, and does the map still produce it?

    A missing map SKIPS its rows. It never fails them — the two maps outside this repo are not
    always to hand, and a check that fails when it cannot look is a check people learn to ignore."""
    rows: list[Row] = []
    for claim in ledger:
        # THE PRESENCE CHECK RUNS FIRST, BEFORE ANY SKIP. Whether the sentence is still in the file
        # has nothing to do with whether its map is to hand, and putting the skip first meant the
        # CLI could not see a single DRIFTED row in the one configuration it actually runs in — the
        # sweep supplies no external map, so nine of the rows skipped before they were looked at.
        # A run against a tree with none of the files reported "all skipped" and exited 0.
        try:
            present, where = quote_is_present(repo, claim)
        except Exception as exc:                                  # noqa: BLE001 — report, never crash
            rows.append(Row(claim, "ERROR", detail=f"{type(exc).__name__}: {exc}"))
            continue
        if not present:
            rows.append(Row(claim, "DRIFTED", detail=where))
            continue
        missing = [n for n in claim.maps if n not in maps]
        if missing:
            rows.append(Row(claim, "skipped", detail=f"no map supplied for {', '.join(missing)}"))
            continue
        # BOTH halves inside the guard. `quote_is_present` sat outside it, so a malformed `site`
        # killed the whole run instead of reporting one row; so did a measure returning anything but
        # a string, because the comparison itself is what raised.
        try:
            got = claim.measure(maps)
            if not isinstance(got, str):
                raise TypeError(f"measure returned {type(got).__name__}, not a sentence")
        except Exception as exc:                                  # noqa: BLE001 — report, never crash
            rows.append(Row(claim, "ERROR", detail=f"{type(exc).__name__}: {exc}"))
            continue
        if normalise(got) == normalise(claim.quote):
            rows.append(Row(claim, "holds", measured=got, detail=where))
        else:
            rows.append(Row(claim, "STALE", measured=got, detail=where))
    return rows


def _format(rows: list[Row]) -> str:
    counts = collections.Counter(r.verdict for r in rows)
    out: list[str] = []
    order = ("STALE", "DRIFTED", "ERROR", "skipped", "holds")
    for verdict in order:
        chosen = [r for r in rows if r.verdict == verdict]
        if not chosen:
            continue
        out.append(f"\n{verdict.upper()} — {len(chosen)}")
        for r in chosen:
            out.append(f"  {r.claim.site}")
            out.append(f"    says     : {r.claim.quote}")
            if r.measured:
                out.append(f"    measures : {r.measured}")
            if r.detail:
                out.append(f"    note     : {r.detail}")
    decided = counts["STALE"] + counts["holds"]
    out.append("")
    out.append(f"{counts['STALE']} stale · {counts['holds']} hold · {counts['DRIFTED']} drifted · "
               f"{counts['ERROR']} errored · {counts['skipped']} skipped"
               + (f"  ({counts['STALE']}/{decided} of the decidable rows are stale)" if decided else ""))
    if counts["skipped"]:
        out.append("Supply the missing maps with --map NAME=PATH to decide the skipped rows.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import json
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        print(USAGE)
        return 0
    repo = Path.cwd()
    as_json = False
    listing = False
    paths: dict[str, Path] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--json":
            as_json = True
        elif a == "--list":
            listing = True
        elif a in ("--map", "--repo"):
            i += 1
            if i >= len(argv):
                print(f"ERROR: {a} needs a value", file=sys.stderr)
                return 2
            if a == "--repo":
                repo = Path(argv[i])
            else:
                name, sep, path = argv[i].partition("=")
                if not sep:
                    print(f"ERROR: --map wants NAME=PATH, got '{argv[i]}'", file=sys.stderr)
                    return 2
                if name not in MAP_NAMES:
                    print(f"ERROR: unknown map '{name}' — one of {', '.join(MAP_NAMES)}",
                          file=sys.stderr)
                    return 2
                paths[name] = Path(path)
        else:
            print(f"ERROR: unknown option: {a}", file=sys.stderr)
            return 2
        i += 1
    if listing:
        for c in LEDGER:
            print(f"{c.site}\n  maps  : {', '.join(c.maps)}\n  says  : {c.quote}\n"
                  f"  why   : {c.note}")
        print(f"\n{len(LEDGER)} rows. Not mechanised: {len(NOT_MECHANISED)} "
              f"(see NOT_MECHANISED in this module).")
        return 0
    own = repo / ".coyomap" / "project-map.json"
    if "coyomap" not in paths and own.exists():
        paths["coyomap"] = own
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        print(f"ERROR: no such map: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        loaded = load_maps(paths)
    except Exception as exc:                                      # noqa: BLE001 — a broken run, not a stale one
        print(f"live-numbers: could not open a map — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    rows = run(repo, loaded)
    if as_json:
        print(json.dumps([{"site": r.claim.site, "verdict": r.verdict, "says": r.claim.quote,
                           "measures": r.measured, "note": r.detail} for r in rows], indent=1))
    else:
        print(_format(rows))
    # 1 = a sentence disagrees with its map, which is the normal finding. 2 = the ledger itself is
    # broken (a row crashed, or its sentence is gone), which is not the same news and must not be
    # swallowed by a caller that tolerates exit 1.
    if any(r.verdict in ("ERROR", "DRIFTED") for r in rows):
        return 2
    return 1 if any(r.verdict == "STALE" for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
