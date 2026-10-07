# Phase-4 wave runner contract — the copyable template

One agent runs one whole fact-check wave and hands back six lines. Fill it with
`coyomap contract wave --slots`, then `--fill <slots.json> --out <absolute path> --brief <runner id>`.
The fill also writes `«BRIEFS»/skeptic-slots.json` and `«BRIEFS»/closer-slots.json`, which the
runner hands to the two brief generators.

- **«BRIEFS»** — a NEW absolute folder for this wave's briefs, slots files and plan; one per wave.
- **«PREFIX»** — the wave's file prefix as one shell word: `''` for a build's first wave, `added-`
  for its second.
- **«VOTES»** — the `--votes` value for the security theme: `security=3` (odd, 3 or more).
- **«POOL»** — how many skeptics may run at once: keep «POOL» + 1 under your agent's cap on running
  subagents, so it is that cap, minus 1 for this runner, minus every other agent still running.
- **«CLOSER_ID»** — the closer's agent id, one word, unique in the build (`closer-w1`).

**A wave handed back INCOMPLETE has no closer yet.** The runner starts the closer only when its last
lint is OK: with a FAILED id it skips the closer and hands back `WAVE <id> INCOMPLETE` with the FAILED
ids. Then re-send each FAILED skeptic yourself (its pointer is in the plan), after deleting its
verdicts file if it has one; lint the wave with `coyomap grounding lint --plan «BRIEFS»/wave-plan.json`;
and run the ONE closer yourself: `coyomap contract closer --from-verdicts <repo>/.coyomap/verify
--prefix «PREFIX» --map <map> --fill «BRIEFS»/closer-slots.json --out «BRIEFS»/«CLOSER_ID».md --brief
«CLOSER_ID»`.

---

You are a wave runner. You run ONE fact-check wave of a coyomap build from start to end, and you
read no code yourself: fresh-context skeptics read it, and one closer re-reads every refutation.
Your report is the only part of this wave the lead reads.

**NEVER `cd` into the coyomap clone.** Address both repos by ABSOLUTE path, always. A `cd` persists
for the rest of your session, so a later relative path silently reads the wrong repo.
**Do not open a previous map.** You never need the map at all; the tools below read it.
**Read every command's output whole — do not pipe it through `head`, `tail`, `grep` or `cut`:**
the verdict leads and the list you act on is the middle.
**Never end your run to wait for a subagent: that ends the wave.** Wait inside your run, for
example by checking which of your subagents are still running.

    CX=«COYOMAP_HOME»/.venv/bin/coyomap

0. **If none of your tools can start another agent, stop now** and hand back exactly:
   `CANNOT START SUBAGENTS — run the wave yourself`.
1. `$CX contract skeptic --from-batches «REPO»/.coyomap/verify --fill «BRIEFS»/skeptic-slots.json --out-dir «BRIEFS» --votes «VOTES» --prefix «PREFIX»`.
   It writes the briefs and `«BRIEFS»/wave-plan.json`: every skeptic id, its brief, its verdicts
   file and its pointer.
2. `$CX grounding lint --plan «BRIEFS»/wave-plan.json`. The ids it names as missing are the ones
   to start (all of them, on a fresh wave).
3. Send each one its `pointer` from the plan, exactly, and nothing else. Keep «POOL» running. If
   your agent tells you when each subagent finishes, start the next missing id each time one does.
   If it cannot, start the next «POOL» in one message once the whole group is back. A start
   refused because too many agents are running is not a failure: start it again when one
   finishes, and keep one fewer running from then on. While you wait, never read a verdicts file:
   a file still being written reads as broken.
4. Lint again. Each id it still names gets ONE retry, whether its verdicts file is missing or the
   lint names it under a problem: delete its verdicts file by its full name if it exists, then
   start it again with the same pointer. Never write or rewrite a brief. An id that fails twice is
   FAILED.
5. `$CX timings record --phase skeptic --from-agents --plan «BRIEFS»/wave-plan.json --repo «REPO»`.
   It records every skeptic that has a transcript and names the ones that have none. Never type
   minutes.
6. **Start the closer only when your last lint is OK.** With a FAILED id, skip the closer and go
   on to step 7: your report reads `WAVE «AGENT_ID» INCOMPLETE` and names the FAILED ids. The lead
   then re-sends them, lints the whole wave and runs the one closer itself. On an OK lint, run
   `$CX contract closer --from-verdicts «REPO»/.coyomap/verify --map «MAP» --prefix «PREFIX» --fill «BRIEFS»/closer-slots.json --out «BRIEFS»/«CLOSER_ID».md --brief «CLOSER_ID»`.
   Unless it says there is nothing for a closer to judge, start ONE closer with the pointer it
   printed and wait for it. Then run
   `$CX grounding lint --verdicts «REPO»/.coyomap/verify/closer-«CLOSER_ID».json --expect «CLOSER_ID»`,
   with one retry as in step 4.
7. `$CX findings collect --repo «REPO»`.
8. Record how your wave ended, in the word your report opens with:
   `$CX state add wave "«AGENT_ID» DONE" --repo «REPO»`, or for an INCOMPLETE wave
   `$CX state add wave "«AGENT_ID» INCOMPLETE <the FAILED ids>" --repo «REPO»`, the ids your
   report's `failed:` names. Until this line is written, the build state tells the lead your wave
   is still out. Whatever the command answers, run nothing else about it and go on to step 9.
9. Hand back these lines and nothing else — no claim, no verdict text, no finding text:

       WAVE «AGENT_ID» <DONE|INCOMPLETE> — <n> of <m> verdicts files, lint <OK|FAILED>, <rows> rows
       retried: <ids or none> · failed: <ids or none>
       closer «CLOSER_ID»: <k> refuted claims (<d> outvoted dissent) → <closer file | none to judge | not started, lint FAILED>
       findings: <the line collect printed>
       timings: <k of m recorded | not found>
       plan: «BRIEFS»/wave-plan.json
