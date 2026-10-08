# A walk-jump names the sub-flow's step, and assemble names two rows at one anchor

Change (2026-10-08, round 2, retro findings mcpolis-2026-10-08-#10 and #19):
`validate`'s walk-jump advisory names a step written inside a sub-flow as
`SFn step k (via UCm step j)`, where it printed the sub-flow's step number under the use case id.
The record key stays the use case (`UCm: <why>` under 'Walk jumps'). `assemble` prints a WARNING
when two parts sit at one `file:line` under different names, and when two ways in of one kind sit
at one `file:line` with different owning parts. Ways in that differ only in their trigger (one call
registering several routes) and anchors with no line stay silent · tools/coyomap/model.py
(`expanded_steps_with_parent`, which `expanded_steps_with_container` now reads),
tools/coyomap/validate_model.py, tools/coyomap/assemble.py, tests/test_validate_model.py,
tests/test_assemble.py.
On the 2026-10-08 mcpolis map 21 of 25 walk-jump warnings pointed at a step number the use case
does not have, and two near-duplicate pairs (C310/C330, EP20/EP21 and 5 more at `app.py`) were
found only by dumping all 256 ways in.

Escalation: none.

## Checks

1. expect: every walk-jump line whose step sits inside a sub-flow starts with `SFn step k (via`,
   and the named sub-flow's step k starts at the box the line names.
   regression sign: a line `UCm step k starts at X` where UCm's own step k does not start at X.

2. expect: when two harvest slices write one part or one way in twice, the first `assemble` output
   carries a "code line(s) anchor more than one part" or "hold ways in of one kind owned by
   different parts" WARNING naming both ids.
   regression sign: a shipped map with two parts at one `file:line`, or two ways in of one kind at
   one `file:line` with different owners, and no such WARNING in any assemble output of the build.

3. expect: the warning names no pair of ways in that share one owner (an SDK call that mounts
   several routes on one line).
   regression sign: a WARNING row listing ways in that all end `on` the same part.
