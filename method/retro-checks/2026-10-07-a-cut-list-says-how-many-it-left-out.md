# A list cut at N says how many items it left out, in one shape everywhere

Change (2026-10-07, merge 5.4 of the shared-code merges): `reporting.item_lines` replaces the two
private copies `finalize._items` and `grounding._item_lines`, with the same output byte for byte.
Twenty-two lists that were cut by hand now go through `reporting.shown` or `item_lines`, so each
cut ends on a count (`+N more`) where it ended on a bare `…`, on an `... and N more` line of its own,
or on nothing at all: `validate` (the three retrofit gates past 6 stories or steps, the holders of an
`embedded` record past 4, the keys of the merge advice past 3; every one whole under `--json`),
`finalize` (the verdict files nobody passed, the briefs with no numeric budget, the extra map
paths), `grounding report` (a claim's notes past the second, the STILL IN THE MAP claims),
`grounding by-element` (the unresolved claims past 20), `grounding refutations` (the unseen
elements past 15, the access rules and the re-worded ones past 8), `audit` (a description claim's
files past 6, and every file under `--json`; the removed prose batches past 5), `assemble` (the
keep_edges directives past 5), `reconcile` (the ids not in the map past 8, the elements no rule
placed past 10), and `export` (the files left out past 3) · tools/coyomap/reporting.py,
validate_model.py, finalize.py, grounding.py, audit_model.py, reconcile.py, reconcile_build.py,
viewer/export.py; contract.py and eval/tools/coyomap_eval/compare.py (moved onto `shown`, output
unchanged).
On the 2026-10-07 mcpolis map, 14 description claims hid 56 file names behind a bare `…`, 4 claims
in `grounding report` dropped their third skeptic's note with nothing said, and `by-element` ended
its 36 unresolved claims on `... and 16 more`. None of the five `validate` lists fires on that map,
so its `validate --check-sources --check-coverage` output, text and `--json`, is unchanged.

Escalation: none. A list's tail is wording; no gate reads it.

## Checks

1. expect: every claim in the build's `grounding report` whose vote line shows 3 votes with 3 notes
   prints 2 notes and then a `+1 more note(s)` line.
   regression sign: a claim with 3 skeptics named on its vote line that prints 2 notes and no
   `more` line under them.

2. expect: in the build's `claims-description-*.json` batches, every description claim whose
   component holds more than 6 files ends its `detail` on `, +N more`, and N plus 6 is the number of
   files the component holds in the map.
   regression sign: a `detail` ending on a bare `…`, or an N that does not add up to the
   component's file count.

3. expect: in the pinned `verify/worklist.json` (written by `audit --json`), every description
   claim's `detail` names all of its component's files.
   regression sign: a pinned description `detail` ending on `+N more` or `…`.

4. expect: 0 tool results in the build transcript where `validate`, `finalize`, `grounding`,
   `audit`, `assemble`, `reconcile` or `export` ends a list on a bare ` …` or on an `... and N more`
   line.
   regression sign: any such line, which means a list is cut by hand again.

5. expect: when a retrofit gate fires (a story that skips its door, a crossing with no door, a step
   at a dependency standing on a surface) over more than 6 items, its `validate` advisory ends the
   list on `+N more`, and the `validate --json` payload names every item.
   regression sign: a retrofit advisory ending its list on a bare `…`, or a `--json` advisory that
   names 6 items when its count says more.
