# Claims a build removed on purpose are not counted as gone

Change (2026-10-08, round 2, retro finding mcpolis-2026-10-08-#3): the `validate` advisory "N
claim(s) the skeptics were given are GONE from the shipped map", which `finalize` carries as a
no-escape row, no longer counts two kinds of removal. A pinned claim a LATER wave re-stated (a pin
row after it, in the rows `audit --since` appended, on the same theme and boxes, still in the map),
and a pinned claim whose refutation the closer upheld (read from the closer's own files beside the
map). The line says how many of each it left out. Also checked: `finalize`'s gate block already
carries the findings count (#24), read from the agents' files when it runs, so that finding needed
no tool change; a test now pins it · tools/coyomap/validate_model.py, tests/test_validate_model.py,
tests/test_finalize.py.
On the 2026-10-08 mcpolis map the advisory said 21; it now says nothing, because all 25 claims gone
by text are explained (20 re-stated in wave 2, 5 refuted with the closer upholding).

Escalation: none. An advisory's count; no gate reads it.

## Checks

1. expect: on a build that ran a second wave, the `finalize-report.md` claims-GONE row is absent,
   or its count is at most the number of pinned claims missing from the map minus the second
   wave's re-stated claims and the closer's upheld refutations (count both from `verify/`).
   regression sign: a GONE count equal to the pinned theme counts minus the live ones while the
   closer file holds an `uphold` row on a claim the map no longer makes.

2. expect: when the GONE line fires on a build with a closer file or a second wave, it ends its
   theme list with "Not counted: N claim(s) a later wave re-stated and M the closer upheld a
   refutation of".
   regression sign: the line fires with neither number while `verify/worklist.json` carries a
   `second_wave` count above 0.

3. expect: the commit message's findings count equals the `agent findings (informational)` line
   of `verify/gate-block.md`.
   regression sign: a commit amended only to change a findings count.
