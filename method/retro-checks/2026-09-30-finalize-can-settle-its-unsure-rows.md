# finalize can settle every row it would file UNSURE

Change (2026-09-30, retro finding mcpolis-2026-09-30-13): `finalize`'s budget leg reads a record, a
'Balance exceptions' line opening `component-budget:` that names both the shipped and the budgeted
count (a bare `granularity:` sentence settles nothing); the disposition matches the silenced-lines
and `DISCLOSURE` wordings, files an access path no rule names UNRECORDED, and carries a line whose
text is not in the map; the drift leg keeps anchor-drift's notes about recorded lines that matched
no finding · tools/coyomap/finalize.py.
On the 2026-09-30 mcpolis map the report filed 3 rows UNSURE, and no record could settle any of
them. Re-run on that map with the fix: UNSURE 3 → 0 (UNRECORDED 3, carried 48, disclosure 12,
recorded 1).

Escalation: none on its own.

## Checks

1. expect: the shipped map's `finalize-report.md` has 0 `**UNSURE**` rows.
   regression sign: 1 or more UNSURE rows.

2. expect: when the map ships more components than the harvest briefs budgeted, either the budget
   leg reads "DISCLOSURE, not a request" over a `component-budget:` line naming both counts, or the
   row is UNRECORDED and the lead answered it.
   regression sign: a `granularity:` or other key-less line that settled the budget row.

3. expect: every recorded 'Drift exceptions' line that matched no finding appears in the drift leg's
   advisories.
   regression sign: anchor-drift printed "matched no finding" in the build and the finalize report
   is silent about it.
