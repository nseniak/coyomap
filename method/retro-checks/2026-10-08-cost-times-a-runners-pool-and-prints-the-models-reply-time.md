# `cost` times a runner's pool, not the runner, and prints the model's reply time beside seconds per row

Change (2026-10-08, round 2, retro findings mcpolis-2026-10-08-#5 and #23): `coyomap-eval cost`
reads `parentAgentId` from each sub-agent's `.meta.json`. An agent that dispatched agents of its own
is a runner: it gets no row in the fan-out table, and its children form fan-outs of their own, named
in a new `via` column (the lead, or the runner's description). The header line says how many runners
dispatched how many agents. The report also carries the median seconds from a tool result to the
next reply, per model: in `--json` as `reply_seconds`, in STRUCTURE, and beside `seconds per row`
· eval/tools/coyomap_eval/cost.py, eval/tests/test_cost.py.
Measured on the 2026-10-08 mcpolis build (`--to-turn 447`): straggler waste 118.0 → 75.2 minutes
(64 % → 41 % of active time); the 53.0-minute "straggler" row is gone; the wave-1 skeptics show as 6
fan-outs via "Fact-check wave 1 runner" and the wave-2 skeptics as 1 via "Fact-check wave 2
runner"; "124 sub-agent(s) (2 runner(s) dispatched 81 of them)"; model median reply 6.7 s
claude-opus-5-5, the number the retro had computed by hand.

## Checks

1. expect: on a build whose fact-check waves ran through runners, no fan-out row of `cost` has a
   runner as its slowest agent, and every skeptic the runner dispatched sits in a row whose `via` is
   that runner.
   regression sign: a fan-out row with `via` = lead whose slowest agent is a wave runner, or a
   skeptic counted in a lead row.

2. expect: the header's "N runner(s) dispatched M of them" equals the number of `.meta.json` files
   with a `parentAgentId` that names another agent of the build.
   regression sign: a count that differs, or no such phrase on a build whose `.meta.json` files carry
   `parentAgentId`.

3. expect: the retro report's cost line quotes the model median reply that `cost` printed, and the
   retro does not compute it by hand.
   regression sign: a retro that times replies with its own script, or reads a change in seconds per
   row as a method change without naming the reply time beside it.
