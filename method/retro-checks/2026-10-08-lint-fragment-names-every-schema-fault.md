# lint-fragment names every schema fault of a fragment in one run

Change (2026-10-08, round 2, retro finding mcpolis-2026-10-08-#7): `coyomap lint-fragment` prints
one `SCHEMA —` line for every schema fault of a fragment (unknown field, wrong type, missing
required field, bad id shape), not only the first, and its verdict counts them all. Every other
reader still stops at the first fault · tools/coyomap/model.py (`_build` and `_check` take an
optional list that collects), tools/coyomap/assemble.py (`fragment_schema_errors`),
tools/coyomap/lint_fragment.py, tests/test_lint_fragment.py.

## Checks

1. expect: on the next build, no harvest or trace agent runs `lint-fragment` on a fragment twice in
   a row where the second run's first `SCHEMA —` line names a fault that was already in the file
   at the first run. On the 2026-10-08 mcpolis build 14 of 48 harvest lint runs failed on schema,
   one fault per round.
   regression sign: a fragment whose lint output shows one `SCHEMA —` line while the same file
   held two or more faults (read the next lint of the same file: a new fault in a row the agent
   did not edit).

2. expect: the failed-lint share of harvest lint runs falls below 14 of 48 (29%).
   regression sign: the share stays at or above 29% with schema faults as the cause.
