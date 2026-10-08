# A closed build's log takes no line from a read

Change (2026-10-08, round 2, retro finding mcpolis-2026-10-08-#8): once the build state has closed
(its last event that is not a note or a read is `end`, or the lead's `phase commit`), a `barrier`
line from `grounding lint` and a `findings` line from `findings collect` are no longer written. The
commands still run and print as before. A `record`, an `assemble`, another `phase` or a new `start`
opens the build again, and its reads are logged · tools/coyomap/buildstate.py,
tests/test_buildstate.py.
On the 2026-10-08 mcpolis build 8 lines landed after the map commit: 2 from the build (`findings`,
then `phase commit`) and 6 from the retrospective's lint and collect runs.

Escalation: none.

## Checks

1. expect: 0 `barrier` or `findings` lines in `build-state.log` after the last `end` or
   `phase commit` line, unless a `record`, `assemble`, `phase` or `start` line comes between them.
   regression sign: a `barrier` line dated after the map commit, or after the retro started.

2. expect: `git diff .coyomap/build-state.log` after a retrospective of the build shows no added
   line (when the log is committed at all).
   regression sign: any added `barrier` or `findings` line in that diff.

3. expect: a fix after `end` (a `record` then a re-run of `ship`) is still logged in full: its
   record, assemble, grounding, finalize, ship and end lines all appear.
   regression sign: a `ship complete` in the transcript after the first `end` with no matching
   `ship` line in the log.

## Review fix (2026-10-08)

`phase commit` alone no longer closes the log: the method starts that phase BEFORE `finalize`, so
the pre-commit read's barrier and findings lines were dropped. The build closes at `end`, or at a
`finalize` or `ship` line written in the commit phase · tools/coyomap/buildstate.py,
tests/test_buildstate.py.

4. expect: a build's log shows the barrier and findings lines of the reads run between
   `phase commit` and the first `finalize` line.
   regression sign: a `phase commit` line followed directly by `finalize` while the transcript shows
   a `grounding lint` or `findings collect` run between them.
