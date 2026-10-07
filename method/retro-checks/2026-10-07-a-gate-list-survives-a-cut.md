# A gate's list survives a cut, one line answers the map's size, and grounding says only what it knows

Change (2026-10-07, retro findings mcpolis-2026-10-07-1, -6 and -23): every list-bearing advisory of
`finalize` (the access-baseline finding, its disclosure, its excuses nobody opened, and five lists of
the refutation leg) and of `grounding lint` (the second-look note, the files cited and named nowhere,
the test citations read by name only) prints its count on a short first line and each item on a
line of its own; the budget leg reads a `granularity:` line that names both counts, and its advisory
offers that line; `grounding report` lists the claims kept on appeal apart from those still to fix;
the audit disclosure no longer says an operator judged each record; an evidence-anchor disagreement
counts only claims whose voters agreed on the verdict; a note writing "N rows added no new claim" is
read as the redundant-row count · tools/coyomap/finalize.py, grounding.py, audit_model.py, method.md.
On the 2026-10-07 mcpolis build the access-baseline advisory was one line of 6,740 characters, a
`cut -c1-500` left 1 of its 20 lost files legible, and 6 previous access rules shipped lost; the
budget leg shipped UNRECORDED beside a `granularity:` line; `grounding report` asked to fix the 3
claims its own CLOSED ON APPEAL section kept; and `ship` refused a note that dropped the word "that".

Escalation: if item 1 fails, run the eval before accepting the map.

## Checks

1. expect: every line of the build's `finalize-report.md` that names a lost access file names that
   one file only, and the access-baseline finding's first line carries "N of M file(s)" and is
   under 200 characters.
   regression sign: a line of one of the three access lists this change split that names 2 or more
   files: the finding ("… are named by NO access rule in this map"), its disclosure ("… are excused
   under 'Access baseline exceptions'") or the excuses nobody opened ("… excused without being
   opened"); or a lost file the lead never opened while the report listed it. Other report lines
   are not this check's: validate's advisories keep their list on one line (the 2026-10-07 report's
   "45 door step(s) are anchored on a file …" is 4,207 characters with 45 paths), because the
   scorecard's assertion 9 reads each validate advisory as one `- ` line.

2. expect: every `grounding lint --agent-transcripts` run that prints "worth a second look" prints it
   on the first line of its note, opening on the row count, under 200 characters.
   regression sign: a lint line over 300 characters holding file paths, or the lead reading the lint
   through a pipe that left the row count out.

3. expect: when the map ships outside the summed budget band, the budget leg reads "DISCLOSURE, not
   a request" over ONE `granularity:` line naming "N shipped of M budgeted", and the same report
   carries no validate advisory opening "Granularity:"; or the row is UNRECORDED and the lead
   answered it.
   regression sign: 2 or more lines under 'Balance exceptions' about the map's size, or a line naming
   only E or the band that settled the budget row.

4. expect: when a closer rejected a refutation, the STILL IN THE MAP count of `grounding report`
   leaves that claim out, and the claim is listed under KEPT ON APPEAL.
   regression sign: a STILL IN THE MAP count that includes a claim the CLOSED ON APPEAL section marks
   [REJECT].

5. expect: 0 finalize reports and 0 `audit` outputs of the build say a recorded line was "judged
   acceptable by an operator"; the audit disclosure says the lines were written by whoever ran the
   build.
   regression sign: any tool output naming an operator as the judge of a recorded line.

6. expect: in NOTE FACTS, the evidence-anchor disagreements are at most the multi-voted claims minus
   the verdict disagreements, and a `grounding.note` that quotes that line draws no disagreement
   WARNING from `grounding write`.
   regression sign: an anchor count above that bound, or a WARNING on a note that quotes NOTE FACTS.

7. expect: 0 `ship` refusals at the `grounding write` step quoting "no new claim" as the note's count
   of claims added since the pin.
   regression sign: a refusal reading "the note states 'no new claim'" on a note that wrote "N rows
   added no new claim".
