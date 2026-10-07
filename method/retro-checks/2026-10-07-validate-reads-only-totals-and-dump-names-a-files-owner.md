# validate reads only totals and labels an untraced map; dump names a file's owner; two refusals name the way on

Change (2026-10-07, retro findings mcpolis-2026-10-07-21, -23 and -24, and F5 of the review that
followed): `validate`'s coverage-count check reads a record's total, the first number before the
kind's word or a noun like "routes", with at most two describing words between when that word is
the kind's name or its last word ("the two socket routes" for `websocket-route`, "the one
stop-signal handler", "19 addressable routes");
never a number that is one item of a list ("plus the two backend routes", "10 dashboard routes, 10
sign-in routes"), that the record says is left out, or that counts another noun ("the 3 route
files", "the one route table"). Over the 339 coverage lines of 33 real maps it takes 25 numbers and
objects 8 times, where finding 21's first fix took 15, objected 11 times and lost the three totals
above. Its Entry-point coverage line calls an untraced map's remainder "not yet traced" instead of "with no
owning component"; `timings record --phase tests` stores the `test-completeness` phase; `fix row`'s
refusal of an edge two fragments declare names `--fragments <one file>` for each copy, and of an id
declared twice says to remove or renumber one; `dump --owners <file>` names every component whose
`files` holds a file (never its `source`: the list `validate` reads), and the trace and gap-fill contracts point at it ·
tools/coyomap/validate_model.py, tools/coyomap/timings.py, tools/coyomap/fix.py,
tools/coyomap/dump.py, method.md, method/templates/trace-contract.md,
method/templates/gapfill-contract.md.

Escalation: none on its own.

## Checks

1. expect: every "Entry-point coverage: the '<kind>' record states" warning in the build quotes a
   total: the first number of its line before the kind's word, with at most two describing words
   between. 0 of them quote one item of a list or a count of files (the 2026-10-07 build printed 2,
   both quoting 'two backend routes' from "plus the two backend routes").
   regression sign: such a warning quoting a list item ("plus the …", "including the …", "N x, M
   y") or a file count, or a number deleted from an 'Entry-point coverage' line within a few turns
   after one (2026-10-07: turn 403 deleted a true "two"); or a shipped `complete` line whose total
   follows a describing word ("the one stop-signal handler") and disagrees with the map's rows of
   that kind while no warning names it.

2. expect: every `validate` run before the first flow exists prints its Entry-point coverage line
   ending in "N not yet traced", and "with no owning component" only for ways in that name no
   component.
   regression sign: "with no owning component" on a map whose ways in all carry a component
   (2026-10-07, turn 169: "201 with no owning component" with 0 of 215 ways in ownerless).

3. expect: every `timings record --phase tests` call in the lead transcript exits 0, and the rows it
   wrote sit in `.coyomap/fanout-timings.json` under `test-completeness`.
   regression sign: "unknown phase 'tests'", or a row stored under the phase `tests`.

4. expect: after a `fix row --edge` refusal reading "declared by 2 fragment rows", the edge's copies
   are corrected by one `fix row --fragments <one file>` call per copy.
   regression sign: a fragment edited by heredoc or `python3` within 3 turns after that refusal
   (2026-10-07: the turn-423 heredoc after the turn-421 refusal erased one agent's text).

5. expect: trace and gap-fill agents name a file's component with `dump --owners`, and 0 of their
   `python3` reads of `project-map.json` walk the components' `files` (2026-10-07: 16 of the
   tracers' 44 hand-written map lookups did).
   regression sign: such a hand walk in any trace or gap-fill agent, or `dump --owners` printing `[]`
   for a file a component's `files` lists.
