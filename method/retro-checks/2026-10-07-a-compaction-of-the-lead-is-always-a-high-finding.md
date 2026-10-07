# A compaction of the lead is always a HIGH finding, and the tools name it

Change (2026-10-07, retro finding mcpolis-2026-10-07-14, raised to HIGH by the operator):
`coyomap-eval cost` prints a CONTEXT block right after the BUILD header: the lead's tokens at its
first turn and at its peak, one `COMPACTED` line per compaction during the build (its turn, its
trigger, its before and after tokens), a near-limit line when the peak passes 900,000 tokens
without a compaction, and the sub-agents that compacted. `coyomap-eval process` gains assertion 41,
"the lead was not compacted during the build". `eval/retro/method.md` makes a compaction of the
lead a HIGH finding every time, names it in "What this covers", and puts it first in "Process
signals" · eval/tools/coyomap_eval/cost.py, eval/tools/coyomap_eval/process_scorecard.py,
eval/retro/method.md, eval/fixtures/trapdoor/L3-DESIGN.md. No build-side method text changed.

Escalation: none. A compaction is a finding about the build's size, not about the map's
correctness: the retro reads the summary and lists what the build lost, it never reruns the eval
for it.

## Checks

1. expect: `coyomap-eval cost <build transcript>` prints `CONTEXT (the lead's own window)` before
   `FAN-OUT`, with the first-turn and peak tokens. On a build that compacted, one `turn N (auto):
   A -> B tokens` line per compaction. On the 2026-10-07 mcpolis build: first turn 100,815, peak
   966,568 at turn 745, one compaction at turn 747 (967,939 -> 12,810). On the 2026-09-30 22:18
   build: peak 937,840 at turn 850 and the near-limit line, no compaction.
   regression sign: no CONTEXT block; a compaction count that differs from the number of
   `compact_boundary` records inside the build's turns; or a compaction placed after the build's
   last turn (the retro's own conversation is not the build's).

2. expect: on a build run as a helper, `cost --include-sidechains` reports the helper's own
   compactions in the same block. On the 2026-09-30 03:51 mcpolis build (the helper transcript
   `agent-adcf7512108b1bb4c.jsonl`): peak 966,062 at turn 434, one compaction at turn 436
   (968,360 -> 18,176).
   regression sign: a helper-run build whose transcript holds a `compact_boundary` record and whose
   CONTEXT block shows none.

3. expect: the retro report's "What this covers" names the lead's first and peak tokens and the
   compaction count, "0 compactions" when there were none. When the build compacted, the ledger
   holds a HIGH finding for it, "Process signals" opens with it, and the finding says what the
   summary dropped and which later actions that explains.
   regression sign: a compaction in the CONTEXT block and no HIGH row in `findings.json`; a
   compaction ranked MED or LOW; or a compaction finding that never read the summary.

4. expect: `coyomap-eval process <build transcript>` scores assertion 41 `0/1` with the turn of
   the first compaction when the build compacted, and `1/1` when it did not. On the 2026-10-07
   mcpolis build: `0/1`, "COMPACTED 1 time(s), first at turn 747".
   regression sign: `1/1` on a build whose CONTEXT block lists a compaction, or `0/1` on one whose
   CONTEXT block lists none, when both runs were given the same `--from-turn` / `--to-turn`.
