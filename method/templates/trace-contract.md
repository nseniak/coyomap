# Trace contract (Phase 3) — the copyable template

**Copy this file; do not compose it from prose.** This template exists because the trace fan-out was
the largest one in a build with no contract of its own — fourteen agents on one build, each prompt
hand-composed from nine separate rules in `method.md`. The rules fan-out was in exactly that state
until it cost eleven repaired fragments and a blocking lint failure in 13 of 71 agent transcripts,
from one wrong sentence the lead wrote from memory. `method.md` states the general form of this
mistake in its own words: shared state belongs in the contract every agent reads, never in a
per-slice option, because a per-slice option gets omitted from one slice — and it records a build
that passed a shared block to 12 of 14 slices, missed two, and shipped one of the omissions.

Fill the «angle-bracket» slots. There are exactly EIGHT — «COYOMAP_HOME», «REPO», «AGENT_ID»,
«USE_CASES», «SF_RANGE», «LEGEND», «WHERE_TO_LOOK», «your-fragment» — each spelled the same way
everywhere. `coyomap contract trace --slots` prints them with a line each on what goes in them, so
this list is a cross-check and never the thing you type from.

**The doors half rides ON this brief, and it must be FILLED.** Appending `contract doors` with `>>`
walks around every check `--fill` makes — 9 of 10 trace briefs on one build reached their agent
still carrying nine literal slot names, and each of those agents then ran one `lint-fragment --repo
«REPO» …` that could not run. The two contracts do NOT share a slot set, so the composed brief needs
doors' «FLOWS», «MAP» and «SURFACES» as well:

```
coyomap contract trace --from-slots <slots-dir> --out-dir <briefs-dir> --append doors
```

That is also the batch form: one slots file per agent, one process, every file checked before any
brief is written.

- **«USE_CASES»** — the `UCn` ids this agent owns, with each one's name, `trigger`, `outcome` **and
  its declared `actors`**, copied from the map. Always whole use cases: **never split one use case's
  flow across two agents**, because a flow traced by two contexts loses its coherence.
  **The actors are not optional.** The legend prints roles and use cases as two unlinked lists, so
  an agent handed the ids alone cannot tell which role its flow should open with — and eight agents
  on one build each opened with the caller the code showed them, costing 34 endpoint repointings at
  the barrier. Fill it as `UC12 Rename a tracked page (actors: R1) — <trigger> → <outcome>`.
- **«SF_RANGE»** — this agent's sub-flow id range (`SF1–9`, `SF10–19`, …), exactly like the harvest
  id ranges. Two agents minting `SF7` is a hard `assemble` failure.
- **«LEGEND»** — the PATH to the id legend file (the assembled map, or a legend the lead wrote).
  Never the legend's contents inline: a whole-map legend overflows the shell argument limit.
- **«WHERE_TO_LOOK»** — the entry points, components and files this agent's use cases run through,
  and any sub-flow the lead wants extracted (see the sub-flow note below).

**Run every sub-flow name you PRESCRIBE past the naming heuristic first.** A brief that hands agents
`SF20 — Validate and store the token` freezes a fused-goal name into a shared id contract: the agents
hit the lint warning, correctly refuse to rename because renaming breaks the contract, and the same
warnings resurface at your own `validate` to be written up as exceptions. Name a sub-flow the way you
would name a use case — one goal, no "and".

**The template starts at the quoted block below.** Everything above it is instructions to you, the
lead; nothing above this line goes into an agent prompt.

> You are tracing use cases for a coyomap codebase map — the ordered interactions inside each one.
>
> **NEVER `cd` into the coyomap clone.** Address both repos by ABSOLUTE path, always. A `cd`
> persists for the rest of your session, so a later relative `.coyomap/...` path silently reads
> the TOOL's own map instead of this project's — a wrong answer that looks like a right one. On the
> 2026-09-02 build 8 of 75 agents did this 33 times, because the rule lived only in the lead's guide
> and no agent had read it.
>
> **Your use cases:** «USE_CASES».
> **Where to look:** «WHERE_TO_LOOK».
> **Your sub-flow id range:** «SF_RANGE». Never mint an `SFn` outside it.
>
> Read the code these use cases run through, then produce ONLY the rows below. The one file you may
> write is your own fragment. **Do this work yourself — do NOT spawn sub-agents, and do NOT write a
> program that GENERATES your fragment.** A sub-agent's output is silently dropped, and an agent
> that delegates returns prose instead of a fragment, which means the whole slice is re-run.
> **What the ban is and is not.** Banned: a script that PRODUCES rows — reading the code, deciding
> what a step is, emitting the JSON. Allowed: a small edit to a fragment you already authored by
> hand — a `sed`, a two-anchor `.replace()`. The line is whether the PROGRAM made the judgement or
> you did. The wording said "writes your fragment", which reads as banning both: 9 of 30 agents on
> one build used a program, and most were patching an authored draft rather than generating one.
>
> ## What you return
>
> **ONE JSON fragment** at `«REPO»/.coyomap/build-fragments/«AGENT_ID».json`, holding only:
>
> ```json
> { "flows":    [ {"uc": "UC7", "title": "<the use case's name>",
>                  "steps": [ {"n": 1, "src": "R1", "dst": "C5",
>                              "phrase": "POST the new upstream",
>                              "where": "frontend/src/pages/Upstreams.tsx:212"} ]} ],
>   "subflows": [ {"id": "SF12", "name": "<one goal, no \"and\">", "steps": [ … ]} ],
>   "edges":    [ {"src": "C5", "verb": "persists", "dst": "E2",
>                  "why": "writes the membership document",
>                  "where": "backend/repo.py:155"} ] }
> ```
>
> Return that PATH plus a one-line inventory (flows, sub-flows, steps, edges). **Never inline the
> fragment in your reply** — a large one is silently truncated by the result cap, and a truncated
> fragment fails `assemble`.
>
> A flow's display text is **`title`**; a sub-flow's is **`name`**. They are not the same key.
>
> ## Steps
>
> - **Every step carries a `phrase`** — what happens at that point, as an ACTION, in the IMPERATIVE
>   ("return the verified email"), never the third person ("returns the verified email"). The viewer
>   shows the phrase ON ITS OWN as the step's title, with no subject in front of it, so a third-person
>   verb there reads as a sentence missing its start. It is also the form a use case's name and a
>   shared sub-flow's name already take, which is what lets one line title either kind of step.
>   A condition or qualifier belongs in `note`, never in `phrase`.
> - **Every element↔element step carries its own `where`** — the `path:line` in the `src` side's code
>   where THIS step's action fires. Not the callee's definition. A step with genuinely no single site
>   sets `"no_call_site": true` instead; silence is not an option.
> - **Anchor the operative statement** — the call / write / enforce line itself, never the enclosing
>   `def` or class header. That header is the most common drift the adversarial pass finds.
> - **`n` is unique within a flow.** It identifies the step for navigation and for diff impact.
> - **Actor steps** use the role id as `src` (`R1 → C5`). An actor step needs no `where`, though one
>   is welcome when the handler line is clear.
> - **Every step where YOUR CODE touches a SURFACE (`In`) or a RECORD (`En`) carries a `direction`**
>   — `"in"`, `"out"` or `"both"`. Read it from the PRODUCT'S OWN CODE, never from the arrow:
>     - at a RECORD, `in` is a read and `out` is a write;
>     - at a SURFACE, `in` is what the product receives and `out` is what it sends;
>     - `both` is one exchange running each way (a code traded for a verified email, an upsert that
>       returns the stored row). Keep it rare: it is for a real exchange, not for indecision.
>   **A PULL is `in` even though the arrow points outward** — `C32 → I8 : fetches the markup of the
>   watched page` is `in`, because the data comes back. Reading the arrow instead is the one mistake
>   this field exists around.
>   **EMPTY on every other step, INCLUDING A DOOR.** A role standing at a surface (`R1 → I3`,
>   `I3 → R1`) is a human action with no product end, the same reason it owes no `where`. `validate`
>   BLOCKS a door that carries a direction, and warns on a crossing that carries none.
>   This is the map's ONLY statement of direction. Nothing else holds it: the `C→E` arrows say both
>   read and write on half the record steps, and no arrow reaches a surface at all.
> - **EVERY SAVED RECORD IN YOUR SLICE OWES A STEP** — one this codebase KEEPS (a row of its own,
>   or one carried inside a parent's row). A saved record no flow reaches cannot say what it is for.
>   A record INSIDE another one counts when its container is reached, so an embedded piece needs no
>   step of its own. A read shape, a request object or an enum is not a saved record and owes
>   nothing.
> - **YOUR STEPS MUST NOT CONTRADICT THE ARROWS.** If a `C→E` arrow in your slice says the code
>   WRITES a record, some flow step must write it (`direction: "out"`), and the same for a `reads`.
>   The arrow is the map's own statement that the code does this, so a story that never does it is
>   the map disagreeing with itself about one record.
> - **A flow OPENS with an actor its own use case declares.** Your slice's use cases are listed
>   above with their `actors`; step 1's `src` must be one of them. This is not the same question as
>   "who calls this code first" — the caller at the entry point is often a client application while
>   the GOAL is the person's, and the use case names whoever owns the goal. If the code convinces you
>   the declared actor is wrong, **say so in your reply** and keep the declared one; do not silently
>   substitute. `lint-fragment` cannot check this — its `--ids` input is a flat id set, so it can
>   only see that `R4` is *a* role, not that this use case declares `R1`. On one build eight agents
>   each wrote the caller they saw in the code and the lead repointed **34 of 38** role endpoints at
>   the barrier, one turn, one script, after the agents were gone.
> - **Steps may go BACKWARD.** Record the return-direction interactions that carry meaning: the
>   response the actor sees (the use case's outcome), an error or fallback path, a callback the callee
>   fires back. Write them like any step — `C5 → C2 : returns the member list`. Do not echo every
>   call with a return; only the ones that say something.
> - **3–15 steps per flow.** Over 15 usually means a fused goal, protocol round-trips narrated at
>   wire grain, or shared machinery that should be a sub-flow. Under 3: check the flow reaches its
>   outcome.
>
> ## Entity steps — 1 to 2 per flow, required
>
> The entities whose read or write IS this scenario's outcome or decision appear as their own steps:
>
> ```
> {"n": 6, "src": "C5", "dst": "E2", "phrase": "upsert the Membership document",
>  "where": "backend/repo.py:155"}
> ```
>
> `En` is a valid step endpoint. A flow that narrates only components leaves the whole domain model
> untraceable — the "used in which use case" view and line-level diff impact both derive from STEPS,
> not from edges — and every gate still passes, so nothing will tell you. *Central* means the join
> flow's membership upsert or the tool-call flow's settings decision, NOT every config read along the
> way. Each entity step also needs its `C→E` edge in `edges`, with the real verb (`reads` /
> `writes` / `persists`).
>
> ## Sub-flows
>
> When the same step sequence rides two or more of your flows, extract it once into `subflows` and
> reference it from each flow with a step whose `subflow` names it:
>
> ```
> {"n": 4, "src": "C1", "dst": "C2", "subflow": "SF12"}
> ```
>
> A reference step carries NO `where` of its own and counts as ONE step against the band. One level
> only — a sub-flow's step may not reference another sub-flow. **A step may reference a SIBLING
> agent's sub-flow**: pass `--ids «REPO»/.coyomap/build-fragments/` to your self-check (a directory
> scans every fragment) so the reference resolves at lint time instead of forcing you to duplicate
> the shared trace inline. The refcount nudge ("referenced once — consider inlining") is advisory on
> the fragment channel, because the other reference may live in a sibling's fragment.
>
> ## Edges
>
> - **`C→D` edges name the ROLE with a role-revealing verb**, never a bare `uses`: `publishes` /
>   `emits` for a bus, `reads` / `writes` / `persists` / `queries` for a store, `calls` for a service.
> - **`why` is a short phrase: what `src` does to `dst`** — an action, and a summary of the WHOLE
>   relationship, never one call's story. "writes org, membership and settings documents", not "the
>   page needs the client to POST".
> - **`where` is one representative call site in `src`'s code.** Do not emit the same
>   `(src, verb, dst)` twice with different anchors.
> - **A `reads` edge — or an entity step — requires the entity TYPE at the site.** A function
>   operating on a string or a field extracted from an entity is NOT reading that entity. This is the
>   false-read the grounding pass keeps refuting.
> - **Never author an edge whose endpoint is an actor** (`Rn`). A person or service driving the system
>   is a flow STEP, not an edge.
>
> ## The three overclaim shapes the skeptics keep refuting
>
> Between them these account for most refutations, so avoid them here rather than paying for them
> later. In all three the rule is the same: **attribute the edge to the component whose own code
> contains the operative line**, and if the line you found is a call into another component, the edge
> belongs to that one.
>
> 1. **Transitive attribution** — a component that calls a first-party wrapper credited with the
>    external call the *wrapper's owner* makes.
> 2. **Ownership overclaim** — a controller that calls `.save()` credited as the system of record when
>    the real upsert lives in the repository.
> 3. **Constructs ≠ persists** — a client factory recorded as writing to the stores it only builds
>    clients for.
>
> ## A named channel is a catalog row
>
> When a step or edge passes through a named queue, topic or channel, record the `messaging` row
> alongside the `C→broker` edge: the channel name, the broker dep, its publishers and consumers, the
> payload entity, and the `source` line that DECLARES the channel name — not a line that merely uses
> it. **Only record a channel row if this brief says you own it.** Several agents each recording the
> same channel is how one build produced three spellings of one field and two of another, and
> `assemble` hard-failed twice: every one of those fragments linted clean on its own, because a
> cross-fragment conflict is invisible per fragment by construction.
>
> ## Before you return
>
> ```
> «COYOMAP_HOME»/.venv/bin/coyomap lint-fragment --repo «REPO» --ids «LEGEND» «your-fragment».json
> ```
>
>
> **With `--repo`, the verdict line ends with an anchor-drift count when any of your `where`s point
> at a line that cannot be acting** — an import, a comment, a `def`, a blank line. Read the FIRST
> line: `LINT OK — 0 problems, 3 advisory warning(s) (3 anchor drift)`. The drift rows are advisory
> and never fail the lint, and they are the defect this self-check was blind to until now: six
> fragments once passed clean and produced 86 drifted anchors at the lead's `validate`, costing
> fifty turns of repair after their authors were gone. Anchor the operative statement — the call,
> the write, the enforce line itself — or set `no_call_site`.
> Fix every row it reports until it exits clean — this catches schema, anchor-format, extra-key and
> invented-id errors in YOUR context, in parallel, so nothing bounces back from the lead. `--ids`
> makes a plausible-but-invented element id die in your own turn. If the lint prints `warning:` lines,
> either FIX them or **repeat them verbatim in your reply with one line of justification each**; never
> shrug an advisory off silently.
>
> **Fields you must NOT author** — the lead assigns these after the fan-out, and a fragment carrying
> one is either rejected or silently wrong: `capability`, `entry_points` on a use case, `subsystem`,
> `subdomain`, `bucket`, `block`, and an `id` on an entry point.
>
> **Write a draft as you go.** Write incremental progress to `«AGENT_ID».draft.json` and RENAME it to
> `«AGENT_ID».json` only when complete — an agent that dies mid-run otherwise loses all its reading.
> `assemble` skips any path ending `.draft.json`, so a fragment left with that name never assembles at
> all: the RENAME is what makes your work land.
>
> **Name every scratch file after your agent id.** Every agent in this fan-out shares one scratchpad
> directory and nothing namespaces it. On one build ten agents wrote to the same script name and one
> of them ran a script that was not its own, writing another agent's output file.
>
> **Quote your shell separators.** The Bash tool runs zsh, where a bare `=word` is EQUALS expansion:
> `echo ====` aborts the command line THERE, so every read after it on that line silently does not
> happen and you are left believing you made it. Write `echo "===="`. Measured on one build: 61
> truncated command lines across 18 of 71 agents.

> **Read the output whole — do not pipe it through `head` or `tail`.** The verdict leads
> the output and the PROBLEM LIST is the middle; a narrow window shows you `LINT FAILED — 6
> problem(s)` and two of the six, and you fix two. Measured across two builds: 0 of 101 sub-agent
> invocations were narrowed on one, 71 of 101 on the next.
>
> **Do not open a previous map.** Not one under `.coyomap/dev-rebuilds/`, not a
> `map-backups/` copy, not one `git show` can produce. This build is deliberately independent of
> its predecessor: a map that reads the one it replaces may still be right, but nobody can tell any
> more, and an eval comparing two maps of one repo reads the agreement as convergence when it is
> copying. If you need an element's record, it is in THIS map — `coyomap dump` reads it.
