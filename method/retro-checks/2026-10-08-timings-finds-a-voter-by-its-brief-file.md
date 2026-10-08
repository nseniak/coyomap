# `timings record --plan` finds a voter by its brief file when its prompt lost the id line

Change (2026-10-08, round 2, retro finding mcpolis-2026-10-08-#17): a sub-agent's span now keeps the
text of the prompt that dispatched it, and `timings record --from-agents --plan` matches a plan
voter that no transcript names by the voter's own brief file, named in its prompt. The latest
matching transcript wins, as for a name. The claims file is not used: the voters of a theme with
several votes share one, and no pointer names it · tools/coyomap/provenance.py,
tools/coyomap/timings.py, tests/test_timings.py.
Replayed on the 2026-10-08 mcpolis wave-2 plan and session: 0 → 5 of 5 voters recorded
(added-behaviour 7.8 min, added-description 4.7, added-security-a/b/c 1.5, 1.2, 1.1).

## Checks

1. expect: the runner's `timings record --plan` report says it recorded every voter its plan names,
   or names each one it could not find with a reason.
   regression sign: "k of m recorded" with k < m while the missing voters' transcripts exist under
   the session's `subagents/` folder.

2. expect: `.coyomap/fanout-timings.json` holds one `skeptic` row per voter of every wave plan the
   build ran.
   regression sign: a wave with no rows, which is what the 2026-10-08 wave 2 left.
