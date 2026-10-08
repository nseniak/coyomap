# A rule written after the last wave ships only with a vote, and the gate never shows the old map's words

Change (2026-10-08, round 2, retro finding mcpolis-2026-10-08-#1, backlog row 50): `finalize`'s
access-baseline leg names each lost file with its lines only, never the old map's rule id,
statement or site why, in every place its text lands (stdout, `finalize-report.md` and `.json`,
the gate block) and in `coyomap record`'s echo under "Access baseline exceptions"; a new BLOCKING
`late claims` leg refuses a claim no wave was given and no skeptic voted on, unless a line under
the "Late claims without a vote" extras heading names its anchor (then it is disclosed; a
`grounding.note` sentence clears nothing); `coyomap audit --since … --prefix late-` cuts the late
wave beside the second, and refuses to re-cut a prefix whose verdicts exist; method.md describes
the late wave (write the rule from the code, 3 votes per claim); L3 assertion 42 counts the rule
claims made after the first pin that carry no vote, with each one's closest archived rule ·
tools/coyomap/finalize.py, access_surface.py, record.py, challenge.py, audit_model.py, records.py,
validate_model.py, method.md, method/dispatch.md, eval/tools/coyomap_eval/process_scorecard.py.
On the 2026-10-08 mcpolis build the advisory printed BR49, BR104 and BR105 in full after wave 2;
the lead wrote 6 rules at the gate, 3 of them copied (assertion 42 on that map: ratios 0.86, 0.88,
0.97), and their 13 site claims shipped with no vote. Read afterwards by 3 skeptics, 2 of the 6
were overstated. The new leg, run on a copy of that map, prints BLOCKED with those 13 anchors.

Escalation: if item 1 or item 2 fails, run the eval before accepting the map.

## Checks

1. expect: the shipped map's `grounding.claims_added_since` is 0, or every claim it counts has
   its anchor under "Late claims without a vote" and the finalize report discloses it.
   regression sign: a count above 0 with finalize CLEAN or ADVISORIES and no `late claims`
   disclosure, or a `late claims` blocking line in the lead transcript followed by a commit.

2. expect: L3 assertion 42 scores 1.00 or n/a, and no evidence row reads `ratio` 0.8 or more.
   regression sign: a score below 1.00, or a rule written at the gate whose closest archived
   rule is 0.8 or more similar (copied, not written from the code).

3. expect: every access-baseline output in the lead transcript lists `<path> (line N, …)` rows
   and no `held BRn "<statement>"` text; assertion 42's gate evidence reads
   `old map's text shown: False` on every turn.
   regression sign: an old statement, site why or old rule id in any finalize output or `record`
   echo after the last wave.

4. expect: when rules were written at the gate, `verify/` holds `claims-late-*.json` and
   `verdicts-late-*.json` files, with 3 voters for each claim, and `worklist.json` holds those
   claims.
   regression sign: late claims recorded under the heading instead of voted while the build had
   the time for a wave, or a `--prefix added-` re-cut refused and then worked around by hand.

5. expect: the late wave costs at most 5 minutes of wall time for 15 or fewer claims.
   regression sign: a late wave longer than the second wave, or more than 3 voters per claim.
