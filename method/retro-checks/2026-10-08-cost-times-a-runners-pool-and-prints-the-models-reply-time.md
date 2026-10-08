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

Review fix (2026-10-08, independent review of round 2, findings 8 and 9): a runner's fan-out row
measures waste as its slowest agent minus the mean, each agent timed from its own launch, so its
launch stagger is no longer straggler waste; the lead's rows keep `wall - mean`. The footer sums
the dispatch stagger of the lead's rows only and says how many runner rows were timed from each
agent's launch. Only a parent of more than one agent is a runner: a worker that spawned one helper
keeps its row, and the helper gets none. A test now holds the "reply to a tool result only"
filter · eval/tools/coyomap_eval/cost.py, eval/tests/test_cost.py.
On the 2026-10-08 mcpolis build (`--to-turn 447`): straggler waste 75.2 → 64.5 minutes (41 % →
35 % of active time); the 29-agent wave-1 runner row (stagger 583.8 s) 13.3 → 7.1 minutes, the
15-agent one (213.9 s) 13.2 → 9.8, the 10-agent one (91.8 s) 2.2 → 1.1; the lead rows and the
runner count (2 runners, 81 agents) unchanged.

4. expect: no runner row's waste exceeds its slowest agent minus its mean.
   regression sign: a runner row whose waste grows with its stagger column.
