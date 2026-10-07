# Gap-fill contract — the eleventh trace slice

**Lead half.** Fill every `«SLOT»` before dispatch. The slots are
`«COYOMAP_HOME»`, `«REPO»`, `«AGENT_ID»`, `«LEGEND»`, `«GAPS»` — each spelled the same way everywhere.

WHY THIS TEMPLATE EXISTS. `method/templates/` shipped four contracts and no fifth, so the gap-fill
slice was hand-composed from prose on every build — and a hand-composed brief loses the shared
machinery. On the 2026-08-20 argus build `contract-t11-gapfill.md` was the ONE trace-phase brief of
eleven missing "do NOT spawn sub-agents", and it also lost the `SHARED CONTEXT` block, "never inline
the fragment in your reply", the scratch-file naming rule and the do-not-author list. The same build
hand-wrote its test-completeness brief and lost the no-delegation block and `--expect` from that one
too. Two hand-written briefs, two sets of missing blocks, and the blocks exist because each one has
already cost a re-run.

- **«GAPS»** — the specific holes this agent closes, as a numbered list, each with what "done" looks
  like. Derive them from the lead's own `validate` output, never from a guess: *"Job 1: every
  external dependency needs at least one incoming component edge — `validate` names D7, D19, D31.
  Job 2: entities with no owning component — E24, E50."* An agent handed "fill the gaps" fills the
  ones it happens to notice.
- **«LEGEND»** — the PATH to the id legend file, exactly as the trace contract uses it. Never inline.
- **«AGENT_ID»** — this agent's id, and it must be unique across the WHOLE build, not just this
  fan-out. Scratch-file safety rests on that uniqueness.

---

> You are closing named gaps in a coyomap codebase map — the rows the sliced fan-outs could not own,
> because each one sits between two slices.
>
> **NEVER `cd` into the coyomap clone.** Address both repos by ABSOLUTE path, always. A `cd`
> persists for the rest of your session, so a later relative `.coyomap/...` path silently reads
> the TOOL's own map instead of this project's — a wrong answer that looks like a right one. On the
> 2026-09-02 build 8 of 75 agents did this 33 times, because the rule lived only in the lead's guide
> and no agent had read it.
>
> **Your jobs:** «GAPS».
>
> **The id legend is at «LEGEND».** Read it before you write a single id. Every id you use must
> already exist there; an id you invent dies at the lead's `assemble`, after you are gone.
> `«COYOMAP_HOME»/.venv/bin/coyomap dump «REPO»/.coyomap/project-map.json --owners <file>` names
> every component that owns a file; never search the map with a script of your own.
>
> Read the code these gaps run through, then produce ONLY the rows your jobs name. The one file you
> may write yourself is your own fragment; the findings command below writes your findings file for
> you. **Do this work yourself — do NOT spawn sub-agents, and do NOT write
> a program that writes your fragment.** A sub-agent's output is silently dropped, and an agent that
> delegates returns prose instead of a fragment, which means the whole slice is re-run.
>
> ## What you return
>
> **ONE JSON fragment** at `«REPO»/.coyomap/build-fragments/«AGENT_ID».json`, holding only the arrays
> your jobs name. **Never inline the fragment in your reply** — reply with the path and a one-line
> summary per job, including any job you could NOT close and why. A gap you leave open and NAME is a
> result; a gap you leave open silently is a defect the lead finds at the gate.
>
> **Write it as `«AGENT_ID».draft.json` first, then rename to `«AGENT_ID».json` when the lint passes.**
> A half-written fragment in the assemble glob fails the whole build; a `.draft.json` is ignored.
>
> ## Fields you must NOT author
>
> `runs_in`, `subsystem`, `subdomain`, `capability`, `block`, `entry_points` — every one of these is
> ASSIGNED by the lead through `coyomap reconcile` after this fan-out. A value you write here is
> overwritten at best and contradicts the assignment at worst.
>
> ## Name every scratch file after your agent id
>
> Every agent in this fan-out shares one scratchpad directory. Any script or note you write goes in
> `«AGENT_ID»-<what>.py`, with absolute paths. Ten agents once wrote to one `build_verdicts.py` and
> one of them ran a script that was not its own.
>
> **Quote your shell separators.** The Bash tool runs zsh, where a bare `=word` is EQUALS expansion:
> `echo ====` aborts the command line THERE, so everything after it silently does not run and you get
> a partial read you believe is complete. Write `echo "===="`. Measured on one build: 61 truncated
> command lines across 18 of 71 agents.
>
> ## Before you return
>
> ```
> «COYOMAP_HOME»/.venv/bin/coyomap lint-fragment --repo «REPO» --ids «LEGEND» \
>     «REPO»/.coyomap/build-fragments/«AGENT_ID».json
> ```
>
> Fix every row it reports until it exits clean. **Read the output whole — do not pipe it through
> `head` or `tail`.** The verdict leads the output and the PROBLEM LIST is the middle; a narrow
> window shows you `LINT FAILED — 6 problem(s)` and two of the six, and you fix two. On one build 22
> of 58 sub-agent invocations were narrowed this way.
>
> **With `--repo`, the verdict line ends with an anchor drift count when any of your `where`s point
> at a line that cannot be acting** — an import, a comment, a `def`, a blank line. Those rows are
> advisory and never fail the lint, and they are the defect this self-check was blind to until now:
> six fragments once passed clean and produced 86 drifted anchors at the lead's `validate`, costing
> fifty turns of repair after their authors were gone. Anchor the operative statement — the call, the
> write, the enforce line itself — or set `no_call_site`.
>
> If the lint prints `warning:` lines, either FIX them or **repeat them verbatim in your reply with
> one line of justification each**; never shrug an advisory off silently.

> **Do not open a previous map.** Not one under `.coyomap/dev-rebuilds/`, not a
> `map-backups/` copy, not one `git show` can produce. This build is deliberately independent of
> its predecessor: a map that reads the one it replaces may still be right, but nobody can tell any
> more, and an eval comparing two maps of one repo reads the agreement as convergence when it is
> copying. If you need an element's record, it is in THIS map — `coyomap dump` reads it.
