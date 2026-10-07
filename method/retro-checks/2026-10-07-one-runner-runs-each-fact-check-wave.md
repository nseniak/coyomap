# One runner runs each fact-check wave

Change (2026-10-07, round 1 of the context work): when the lead's agent can start subagents from a
subagent, the lead starts ONE wave runner per fact-check wave (`coyomap contract wave`). The runner
briefs the skeptics with `contract skeptic --from-batches`, which also writes the wave plan, keeps
its pool of skeptics running, waits inside its own run, lints the verdicts with
`grounding lint --plan` and retries each missing id once, records the timings with
`timings record --plan`, runs one closer only when its last lint is OK, collects the findings,
writes how the wave ended into the build state (`state add wave`) and hands back six fixed lines.
With a FAILED id it starts no closer and hands back `WAVE <id> INCOMPLETE`; the lead then re-sends
the FAILED skeptics, lints the wave and runs the ONE closer itself. Without nesting, or on
`CANNOT START SUBAGENTS`, the lead runs the wave as before. Process-scorecard assertion 5 credits
the skeptics a runner started, and assertion 3 leaves the runner's own launch out; only a launch
whose brief holds the wave contract's opening sentence counts as a runner, the brief being its
prompt or the file that prompt points to, as the runner's own read of it returned it ·
method/templates/wave-contract.md, tools/coyomap/contract.py,
tools/coyomap/waveplan.py, tools/coyomap/grounding.py, tools/coyomap/timings.py,
eval/tools/coyomap_eval/process_scorecard.py, method.md.

Escalation: if a wave shipped with a missing verdicts file, run the eval before accepting the map.

## Checks

1. expect: the lead starts 1 agent per wave, and the skeptics carry that agent as
   `parentAgentId`. The lead's tokens over wave 1 grow by less than 20,000 (172,726 on 2026-10-07).
   regression sign: the lead starts skeptics while a runner is out, or grows by more than 40,000.
2. expect: each runner report has the fixed shape, in at most 8 lines.
   regression sign: claim or finding text in a runner report.
3. expect: a runner starts its closer only when its last `grounding lint --plan` is OK. A runner
   left with a FAILED id starts no closer and hands back `WAVE <id> INCOMPLETE` with the FAILED
   ids. The lead then re-sends each FAILED skeptic itself (its pointer is in the plan), lints the
   wave with `grounding lint --plan <plan>`, and runs the ONE closer itself
   (`contract closer --from-verdicts --prefix <p>`).
   regression sign: a runner's closer started after a lint that was not OK, an INCOMPLETE wave with
   no closer from the lead, a wave with two closers, or a verdicts file missing at ship.
4. expect: on an agent that cannot nest, the runner hands back `CANNOT START SUBAGENTS` within its
   first turn, and the lead runs the wave the old way.
   regression sign: a runner that read code or judged claims itself.
5. expect: process-scorecard assertion 5 scores 1/1 on a build that used a runner. Only launches
   whose BRIEF holds "You are a wave runner." count as runners, in assertion 5 and in assertion 3.
   The scorecard reads the brief from the launch's own transcript: its prompt, or the file that
   prompt points to, as the runner's own read of that file returned it. A pointer prompt alone does
   not hold the sentence; the file it points to does.
   regression sign: 0/1 when a runner was present, or another agent that started agents of its own
   (a refuter, a report reader) read as a runner.
