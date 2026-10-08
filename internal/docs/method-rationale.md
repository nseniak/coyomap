# Method rationale — the incident record behind the rules

**This file is not part of the method.** It lives under `internal/`, which the method tells a
build agent to ignore, and nothing in `method.md` or `method/` points here. It is for the
coyomap author.

**Why it exists.** Almost every rule in the method was added after a real build got something
wrong, and for a long time the account of that build lived inside the rule, in the prompt every
build reads. Three registers were mixed in one file: the **contract** (what a map must contain),
the **procedure** (how to run a build), and the **incident record** (why a rule was added). The
third one is written for the author, not for the agent, and the agent paid attention cost for it
on every build. So the incident record moved here.

**What moved and what stayed.** The rule and its *mechanism* — the timeless causal statement of
what breaks if you ignore it — stayed in the method. What moved is the *evidence*: the named past
build, the measurement, the history of how the wording got escalated. Where a measured magnitude
was the whole deterrent (barrier polling, hand-written scripts) a short marker stayed behind.

**No rule was removed.** Every entry below records the rule it belongs to and an `Anchor` — a
verbatim phrase that must still appear in the named method doc. `tests/test_method_rationale.py`
checks every anchor, so a rule cannot be deleted or reworded out from under its evidence without
a test failing.

**Scope, stated honestly.** What moved is the evidence that was in the agent-facing method PROSE.
The same accounts still appear in places an agent does not read as instructions — CLI `--help` text
and code docstrings under `tools/coyomap/` — so this file is not the only copy in the repo.

**Format.** One entry per moved account, in the order the rules appear in the method.

### R01 — Why capabilities exist
- **Where**: `method.md`
- **Anchor**: `group into **capabilities** — the same shape, a third forest`
- **Evidence**: Measured on a 25-use-case map: with no capability grouping, no screen answered "what does this product do?" — the use-case list was the only content family with no structure at all.

### R02 — The walk expectation is authored, never derived from the walk
- **Where**: `method.md`
- **Anchor**: `**Deliberately not derived from the happy path.** A value that always agreed with`
- **Evidence**: Two derivations were tried and dropped. From FLOW REACH: on the reference map the maximum spread was 4 capabilities of 7, so no threshold separates machinery from product. From the WALK ITSELF: a value seeded from `happy_path[]` agrees with it by construction, so the forward check ("you wrote that the happy path must reach this, and it never does") can never fire. Seeding the three live maps from their own walks reproduced all 27 authored values, which is exactly why seeding alone proves nothing.

### R02b — One word carried two questions, and its middle value meant neither
- **Where**: `method.md`
- **Anchor**: `**It says NOTHING about who the capability is for.** That is a second, independent`
- **Evidence**: The predecessor field was a three-value `label` (core | supporting | platform). Two of its three values had no definition in any file, and every branch in the tooling tested only `== "core"`, so nothing ever distinguished them. The audience half was therefore unenforced and drifted: across rebuilds of the same repo one week apart the same feature was `platform`, then `supporting`; an audit feature was `supporting`, then `core`. Splitting the two questions also named the missing 2x2 cell — staff work the happy path shows on purpose — which is all that six per-step records on the three live maps existed to excuse; they were deleted in the same change.

### R02d — One audience is a signal, never a grouping rule
- **Where**: `method.md`
- **Anchor**: `**One audience is NOT a grouping rule.** Several actors in one capability is ordinary`
- **Evidence**: Requiring one audience per capability was proposed and dropped. Measured across the three reference maps: 10 of 27 capabilities have more than one human actor and every one of them is unanimous, so the rule would have changed nothing — several actors is ordinary, several GOALS is the defect. It would also force a wrong split on a shared surface (a support desk is one goal the customer and the company both act in), a shape none of the three maps happens to have. The mixed-audience warning stays as a signal with three causes the check cannot tell apart, and only the third (a genuinely shared surface) is recordable.

### R02c — Audience is authored on the role because the role is the stable element
- **Where**: `method.md`
- **Anchor**: `**Authored on the role because the role is the stable element.** Across 21 rebuilds`
- **Evidence**: Across 21 rebuilds of one repo over five weeks the capability set churned every build (9 → 8 → 9, names moving, labels flipping) while the same four roles appeared in nearly every build and never once changed side. Deriving upward from the roles reproduced all 27 hand assignments on the three live maps, leaving one `mixed` capability, which was a real defect. Letting MACHINE roles vote instead turns 3 of 27 `mixed`, two of them falsely — hence the human-only rule.

### R03 — What the capability-altitude coverage rule gives up
- **Where**: `method.md`
- **Anchor**: `**What this deliberately gives up**: an individual core use case falling off`
- **Evidence**: On the reference map the trade is six use cases — "Remove a team member" among them. The old per-use-case rule demanded eleven written records on that same map.

### R04 — Transitive entity tagging smears
- **Where**: `method.md`
- **Anchor**: `so transitive tags smear. Every step carries its **own** short action text describing`
- **Evidence**: Measured on a live map: transitive tagging would put a third of the reachable entities into more than half of all use cases.

### R05 — The dropped prose Journey table
- **Where**: `method.md`
- **Anchor**: `drawn as a flow map and read as a numbered narrative.`
- **Evidence**: A separate prose "Journey" table existed in earlier method versions. It duplicated the flows at prose level, the model had no field for it, and builders rightly skipped it — dropped.

### R06 — Flattening the environment axis loses information
- **Where**: `method.md`
- **Anchor**: `**Capture it, don't flatten it** — folding the variants away as "over-modeling"`
- **Evidence**: A build once dropped a project's dev/prod/standalone split as "over-modeling" and lost real information.

### R07 — Untagged variants produce false process arrows
- **Where**: `method.md`
- **Anchor**: `**The tags GATE the Deployment view's process→process arrows**, so leaving them`
- **Evidence**: A live map tagged `backend` (cloud + dev), `standalone` (standalone) and `e2e backend shard` (test) correctly, but every backend component listed all three in `runs_in` — so ONE Redis pub/sub channel produced SIX arrows between three deployment shapes of the same monolith. The tags were already there and already anchored; the view simply was not reading them.

### R08 — Where the two variant grounding rules came from
- **Where**: `method.md`
- **Anchor**: `Two grounding rules keep the tags honest`
- **Evidence**: Both rules come from a real mis-tag: a Vite dev server tagged into `standalone` + `cloud`, where it does not run.

### R09 — Why the security-to-rules fold says rebuild rather than assuming it
- **Where**: `method.md`
- **Anchor**: `but a map gains the decision layer only by being`
- **Evidence**: Two maps in the fleet already fail to load on an earlier rename, so "just rebuild" is said rather than assumed.

### R10 — No gate can see the security granularity choice
- **Where**: `method.md`
- **Anchor**: `Nothing else in the pipeline can see this`
- **Evidence**: Two maps of one repo, weeks apart, went from 103 security rows to 19 while `validate`, `audit` and `balance` were all clean.

### R11 — Why nothing about a rule may be authored
- **Where**: `method.md`
- **Anchor**: `there is no field for any of them, and none may be added.`
- **Evidence**: The first prototype of this layer rendered hand-assigned data as if it were derived, in six distinct ways, and every one of them looked correct on screen.

### R12 — Why the Level-2 tiers were renumbered
- **Where**: `method.md`
- **Anchor**: `T8 Component internals · T9 Config/env vars · T10 Data schema.`
- **Evidence**: T8/T9/T10 were renumbered from T7/T8/T9 when the business-logic section landed: T7 is a RENDERED map section (the map document runs T0 -> T6b -> T7), while these three are on-demand drill tiers nothing in the tooling produces. Two different things called T7 in one document is a confusion the reading agent pays for.

### R13 — The two guard bypasses
- **Where**: `method.md`
- **Anchor**: `**A blocked command is a STOP, not a puzzle.** When a shell or safety guard`
- **Evidence**: One build hit this twice in one run and evaded it both times, each with a comment naming the intent: a guard on dot-env files, whose own message said *ask the user before bypassing*, was defeated by assembling the filename from two string literals, and a guard on a prod-credential script was defeated by splitting that script's path across a `+`. Neither exposed anything and both blocks were arguably false positives. The rule itself was written through a file-writing tool, because composing it in a shell tripped the same guard three times.

### R14 — The two shell hazards, as measured
- **Where**: `method.md`
- **Anchor**: `**Two shell hazards this method's own commands keep hitting.** Both are invisible`
- **Evidence**: Both cost a live build real turns. One build `cd`-ed into the clone and reported "7 of 74 isolated entities" read off coyomap's own self-map. The zsh word-splitting trap was got wrong twice on `coyomap fix dedup-edge --keep` (which is why that `--help` documents it), then a third time on `--verdicts` — which is what moved the warning into the method, where it covers every flag.

### R15 — Hand-written scripts measured against the verb table
- **Where**: `method.md`
- **Anchor**: `**Reach for the verb before the heredoc.** Every row below replaces a `python3`
- **Evidence**: Twelve of one build's twenty-eight hand-written scripts mutated the map or a fragment where a command already existed, and the scorecard assertion that watches this fell from 1.00 to 0.57 in one build.

### R16 — Why preindex --report exists
- **Where**: `method.md`
- **Anchor**: `Use it instead of hand-parsing`
- **Evidence**: All four measured builds wrote a throwaway `python3 -c "json.load(open('.coyomap/preindex.json'))…"` to get exactly this, because the doc forbade hand-parsing without offering a read command. `preindex --help` used to run a full pre-index and overwrite the artifact.

### R17 — How far builds drift from E
- **Where**: `method.md`
- **Anchor**: `**Reconcile E with what it is BOUND BY.** The report says whether the file-count`
- **Evidence**: A live monorepo measured E≈994 against a built 429, with a 48-LOC median file. Three of four measured builds disagreed with E by 2–4× and had no way to see why.

### R18 — The serial build that skipped verification
- **Where**: `method.md`
- **Anchor**: `**Scope warning.** Phases 3.5 / test completeness / 4 are NOT part of this section,`
- **Evidence**: Phases 3.5 / test completeness / 4 used to sit as bullets *inside* the parallel-mode section, so a serial build read the whole block as inapplicable and skipped them. A live small-repo build did exactly that: it finished, then told the user "the method wants fresh-context skeptics to try to disprove the claims, **which I did not have**".

### R19 — Batching a fan-out does not buy speed
- **Where**: `method.md`
- **Anchor**: `**What it does NOT buy is speed.** Dispatch latency is the model EMITTING the`
- **Evidence**: The paragraph used to blame "~9–11 minutes of pure launch latency per build" on launching one agent per turn. A build that batched every fan-out into a single message paid 9.1 minutes anyway. The 13-agent skeptic fan-out was the FASTEST of the three at 14.9 KB, against the 12-agent harvest's 73.8 KB.

### R20 — The 23-minute harvest slice
- **Where**: `method.md`
- **Anchor**: `**Pre-size the slices from the pre-index so no slice becomes the critical path.** The whole phase ends when the SLOWEST agent does, so one oversized`
- **Evidence**: A live build's entrypoints+security slice ran 23 minutes while every sibling finished in 4–8, stalling the barrier by a quarter hour.

### R21 — Dead agents and the doubled draft suffix
- **Where**: `method.md`
- **Anchor**: `**Resilience: write a DRAFT fragment early, finalize at the end.** An agent`
- **Evidence**: Two live builds each lost ~13 minutes to an agent dying mid-run. The doubled suffix was what a live build produced. Before `assemble` matched on the name, it did not look at the name at all — so the suffix protected nothing and `*.json` matched the draft like any other fragment.

### R22 — Per-slice drift from E
- **Where**: `method.md`
- **Anchor**: `**Check each slice against ITS E, not only the sum.** The recorded-decision`
- **Evidence**: A live build drifted to 2× E on an overridden-but-unrecorded expectation, with the warning waved through at every validate. Another gave `domain/services` (E=4) about 12 components across two agents, `frontend/src/pages` (E=6) about 10, and `entrypoints` (E=8) thirteen — shipping 96 components against a code-derived expectation of 59 (+63 %), the largest single quality drift in that build.

### R23 — The glob that nearly destroyed three agents' drafts
- **Where**: `method.md`
- **Anchor**: `**Never delete draft fragments with a glob while any agent is still running.** `rm -f build-fragments/*.draft.json` mid-fan-out destroys the`
- **Evidence**: A live build ran exactly that three times, once with three agents still working (one for another seven minutes), and was saved only because those three had not yet written a draft.

### R24 — The measured cost of polling a barrier
- **Where**: `method.md`
- **Anchor**: `**Waiting for the batch (every fan-out phase):** after launching, **wait on`
- **Evidence**: The parenthetical that used to sanction "a `run_in_background` waiter" was the loophole: a build that had loaded `Monitor` in its second minute went on to launch 34 backgrounded polling waiters — 21 of them `until ls …`, the rest `until [ -f … ]`, thirteen alive at once — never calling `Monitor`. A later build polled `ListAgents` twice mid-barrier to count running skeptics.

### R25 — Keep-alive turns: 42 of 195 tool calls
- **Where**: `method.md`
- **Anchor**: `**The wait itself is a TEXT turn — emit no tool call at all.** A keep-alive`
- **Evidence**: A live build ran 39 keep-alive turns plus `sleep 1` / `sleep 120`, burning 42 of its 195 tool calls (22 %) doing nothing. It still scored a perfect 38/38 on the polling assertion, which until then only counted `ls` on the fragment dir — so the waste was invisible in the one number watching for it. One live build produced three interleaved event streams for a single wait.

### R26 — The T5 straggler dispatched twelfth of thirteen
- **Where**: `method.md`
- **Anchor**: `**Dispatch the known-longest slice FIRST, in every fan-out.** Launch order is`
- **Evidence**: In a live build the T5 domain-model slice ran 10.2 min against its siblings' 5.0–6.9 and was dispatched twelfth of thirteen, closing the barrier ~4 min later than it had to.

### R27 — Per-item cost spread inside one fan-out
- **Where**: `method.md`
- **Anchor**: `**Order by expected MINUTES, not by item count.** They are not the same number:`
- **Evidence**: In one Phase-4 fan-out the per-claim cost ran from 2.4s to 32.6s across batches, so the batch with the most claims was not the longest. Measured on a single build.

### R28 — The 23-agent fan-out against a 20-agent cap
- **Where**: `method.md`
- **Anchor**: `**And size the fan-out to the harness's concurrency cap** (~20 agents in one batch, measured). Agents over the cap are REJECTED`
- **Evidence**: A 23-agent fan-out met a 20-agent limit: three were rejected, re-sent 98-141s later over three extra turns, and one of the bumped batches then closed the barrier 4 minutes after its second-to-last sibling.

### R29 — dep: null on every entity
- **Where**: `method.md`
- **Anchor**: `has no D-id universe — it then ships `dep: null` on every entity, silently disabling`
- **Evidence**: Two of three live rebuilds shipped `dep: null` on EVERY entity.

### R30 — Invented state machines: 5 of ~11 refuted
- **Where**: `method.md`
- **Anchor**: `**But author it ONLY from a declared state list, and cite THAT line.** A `states`
- **Evidence**: The motivating live-rebuild case shipped its 5-phase machine as prose twice. On a fresh build the Phase-4 skeptics refuted 5 of ~11 state machines, all of the same two shapes.

### R31 — Isolated entities at 40 % on a 48-entity domain
- **Where**: `method.md`
- **Anchor**: `**Large domain models (many entities) — shard the RELATIONS pass, never skip it.** One agent can read ~40 entities and author a complete `E↔E`
- **Evidence**: A fresh large-monorepo build left about a quarter of its entities with no relation at all. A 48-entity build came back with 19 of them (40 %) holding no relation — the lead printed the isolated list at synthesis and moved on.

### R32 — Lead-only synthesis minutes with every agent idle
- **Where**: `method.md`
- **Anchor**: `**Treat this as a launch STEP, not advice** — it is step 1 of synthesis, before`
- **Evidence**: A live build spent 13 lead-only minutes here with every agent idle, then ran tests/backfill serially after the traces; a later one repeated it for ~6 minutes.

### R33 — The third build that paid the same nine minutes
- **Where**: `method.md`
- **Anchor**: `Dispatch those agents before you start authoring.`
- **Evidence**: A third build paid nine minutes with no agent running, while the lead fixed cards, authored `rules.json` and `structure.json`, and wrote the trace contract. Three builds, about 28 minutes between them, against one sentence buried mid-paragraph — which is why this is now a numbered step.

### R34 — 18 of 96 components edgeless after the trace
- **Where**: `method.md`
- **Anchor**: `**Put the gap-fill slice in the SAME batch as the Phase-3 trace fan-out.** Slicing`
- **Evidence**: A live build found 18 of 96 components (19 %) edgeless AFTER nine trace agents had finished, and paid for it with a serial dispatch plus two turns of rework on an extras paragraph it had written too early.

### R35 — The spot-script that nearly missed a component
- **Where**: `method.md`
- **Anchor**: `the mechanical harvest-completeness sweep`
- **Evidence**: An improvised spot-script covering one directory is how a live build nearly missed a component.

### R36 — 365 edges shipped against 416 re-assembled
- **Where**: `method.md`
- **Anchor**: `A map that cannot be rebuilt from its fragments has quietly stopped being generated.`
- **Evidence**: `--to-reconcile` with no decision used to print the listing, write nothing and exit 0; a build only noticed because it read the file back. A shipped map carried 365 edges while re-assembling its own committed fragments produced 416, because the next assemble restored 49 duplicates the fix had removed.

### R37 — The hand-authoring threshold ten builds used as permission
- **Where**: `method.md`
- **Anchor**: `Count IDS, not rules: a file of 25 rules can carry 187 hand-typed ids, and "25`
- **Evidence**: The threshold that used to be here ("fine below ~30 assignments") is the sentence ten consecutive builds used to justify writing the reconcile file by hand — including the one with 187 ids.

### R38 — The --map circle that made nine builds hand-write reconcile
- **Where**: `method.md`
- **Anchor**: `so demanding a map first is a circle with no way in`
- **Evidence**: Reaching for `--map` mid-build is the trap that made nine consecutive builds hand-write the reconcile file.

### R39 — 429 assignments resolving zero components
- **Where**: `method.md`
- **Anchor**: `It reports **every rule that matched nothing**`
- **Evidence**: A live 429-component build wrote a throwaway generator for this and the script reported 429 assignments while resolving ZERO components, because nothing checked the ids it emitted against the map.

### R40 — What closing a trace gap actually costs
- **Where**: `method.md`
- **Anchor**: `Do not reach for a coverage rule that redefines the`
- **Evidence**: Measured on a real 32-agent build: closing a 15-of-25 trace gap is ~12 % of total build tokens. Trace is 19.1 % of a 56 M-token build, at ~669 k tokens per use case.

### R41 — The 13-minute monetization trace
- **Where**: `method.md`
- **Anchor**: `**Size the trace fan-out so no agent becomes the straggler**: heaviness is predictable`
- **Evidence**: A live build's monetization trace ran 13½ minutes while the lead idled at the barrier, purely because one agent carried too many use cases.

### R42 — Trace-prompt discipline was all measured
- **Where**: `method.md`
- **Anchor**: `Trace-prompt discipline — the LEAD's half only. The agent's half (entity steps, the sub-flow`
- **Evidence**: Every item under this heading was proven on a live build.

### R43 — The build that shipped zero sub-flows
- **Where**: `method.md`
- **Anchor**: `**Do NOT blanket-ban sub-flows** ("no subflows" in every trace prompt) — that`
- **Evidence**: A live coarse-altitude build shipped zero sub-flows that way.

### R44 — Entity mentions channeled into the edges array
- **Where**: `method/templates/trace-contract.md`
- **Anchor**: ``En` is a valid step endpoint. A flow that narrates only components leaves the whole domain model`
- **Evidence**: A live rebuild whose prompts channeled ALL entity mentions into the edges array shipped a domain model with zero flow traceability, every gate green.

### R45 — Five agents wrote subflows[].title by analogy
- **Where**: `method/templates/trace-contract.md`
- **Anchor**: `A flow's display text is **`title`**; a sub-flow's is **`name`**. They are not the same key.`
- **Evidence**: Five trace agents in one live rebuild wrote `subflows[].title` by analogy and each burned a lint round.

### R46 — Rich broker edges with an empty catalog
- **Where**: `method/templates/trace-contract.md`
- **Anchor**: `alongside the `C→broker` edge: the channel name, the broker dep, its publishers and consumers`
- **Evidence**: Three live rebuilds shipped rich broker EDGES with an empty catalog.

### R47 — The legend that overflowed the shell arg limit
- **Where**: `method.md`
- **Anchor**: `**Fill «LEGEND» with a FILE PATH** (`--ids path/to/legend`), never inline contents — a`
- **Evidence**: A live build hit the shell argument limit this way on macOS.

### R48 — How often each overclaim shape was refuted
- **Where**: `method/templates/trace-contract.md`
- **Anchor**: `Between them these account for most refutations, so avoid them here rather than paying for them`
- **Evidence**: On one build, transitive attribution accounted for 5 of 40 dependency claims, and ownership overclaim for another 5 of 40.

### R49 — The messaging batch's 11 refutations
- **Where**: `method/templates/trace-contract.md`
- **Anchor**: `payload entity, and the `source` line that DECLARES the channel name — not a line that merely uses`
- **Evidence**: After earlier builds shipped rich broker edges with an EMPTY catalog, one build filled it and its messaging skeptic returned 11 refutations — the most of any batch.

### R50 — Four agents, four spellings of one channel row
- **Where**: `method.md`
- **Anchor**: `**NAME THE OWNER of every `messaging` catalog row in the slice briefs.** Several agents each`
- **Evidence**: Four trace agents were each told to record the same channel row and each complied: three spellings of `kind` (`pubsub`, `pub-sub`, and a free-text sentence) and two of `name`. `assemble` hard-failed twice ("nothing was written"), and it took two hand-normalisations and four assemble rounds to clear. Every one of those fragments linted CLEAN on its own.

### R51 — Rules used to be a sentence with no title
- **Where**: `method.md`
- **Anchor**: `is the rule's TITLE** — a few words ("Owner-only cancellation"), the way a use`
- **Evidence**: A rule used to be a full sentence and nothing else, so every list of rules was a wall of prose and every breadcrumb truncated one mid-word.

### R52 — risk as an advisory changed nothing
- **Where**: `method.md`
- **Anchor**: `Those seven keys are the WHOLE authored surface`
- **Evidence**: As an advisory the rule changed nothing across two real builds, which shipped 47 and 44 access rules without a single risk between them.

### R53 — The prototype's most frequent rule error
- **Where**: `method.md`
- **Anchor**: `**Nothing unsupported.** A rule must be reconstructible from the lines its sites`
- **Evidence**: This was the prototype's most frequent error.

### R54 — audit read no extras at all
- **Where**: `method.md`
- **Anchor**: `the Happy Path starts after sign-in`
- **Evidence**: Until this heading existed, `audit` read no extras at all: every one of its advisory families was permanently unanswerable, so a finding an operator had judged acceptable re-fired at every audit forever and got waved through.

### R55 — 360 of 408 claims dispatched without their anchor
- **Where**: `method.md`
- **Anchor**: `emits one claims file per theme, most-dangerous-first`
- **Evidence**: A hand-rolled batcher wrote only the claim string, so 360 of 408 dispatched claims reached the skeptics as a bare `C140 calls C78` while the prompt promised them a `path:line` in brackets.

### R56 — The build that batched by worklist order
- **Where**: `method.md`
- **Anchor**: `so the batches fall out of the data instead of being`
- **Evidence**: A live build read this payload, found no field to group by, and fell back to sequential chunks of 40 in worklist order.

### R57 — Three builds retyped the skeptic contract
- **Where**: `method.md`
- **Anchor**: `is one keystroke away from a rewrite, and a`
- **Evidence**: Three builds in a row composed the skeptic contract from prose while the template's own header told them not to.

### R58 — The two-skeptic split the lead broke by hand
- **Where**: `method.md`
- **Anchor**: `with N ODD, and N ≥ 3.** **Where the cut falls`
- **Evidence**: A live build ran exactly two skeptics on its security claims, they split, and the lead broke the tie by hand against the code.

### R58b — The vote's scope was written twice and differently
- **Where**: `method.md`
- **Anchor**: `**The WHOLE `security` theme — every batch of it — gets N skeptics + a majority`
- **Evidence**: "the riskiest claims (auth, scoping, encryption)" and "the `security` theme" both stood as the rule, so a build guessed: it triple-voted 80 of the security theme's 123 claims and single-voted 43, and 8 of its 10 applied refutations then came from single-vote batches. The same build's three-way batches disagreed on the verdict 0 times across 160 rows.

### R59 — Ties described as unverifiable
- **Where**: `method.md`
- **Anchor**: `to see ties listed apart from the claims a skeptic actually called`
- **Evidence**: A live build's own grounding note described four unverifiables as one kind when two were the other.

### R60 — Three false refutations in one batch
- **Where**: `method.md`
- **Anchor**: `**Re-verify every REFUTATION against the code before applying it.** A refutation`
- **Evidence**: Three skeptics split 2-1 on whether the rate limiter was installed, and the lead only got it right by grepping `app.py` itself. In the same batch two more refutations claimed a component was unused because neither source named it — while one of its own files was imported by both.

### R61 — The 144-claim skeptic
- **Where**: `method.md`
- **Anchor**: `**Cap each batch at ~40 claims** and split an oversized theme into two skeptics`
- **Evidence**: A live build gave one skeptic 144 claims (150 turns, 10 minutes, the phase's critical path) while its siblings finished in half the time.

### R62 — 319 of 1,608 claims, reported only in chat
- **Where**: `method.md`
- **Anchor**: `TRIAGE ON THE RECORD — never silently.**`
- **Evidence**: A live monorepo build grounded 319 of 1,608 claims (20 %) with an 11 % refutation rate among them — so the unchallenged remainder plausibly held ~140 more wrong claims — and reported that only in chat.

### R63 — total 399, grounded 399, refuted 3
- **Where**: `method.md`
- **Anchor**: `claims actually HELD UP — `total 399, grounded 399, refuted 3` reads as "399`
- **Evidence**: A live map wrote `total 399, grounded 399, refuted 3`.

### R64 — 0 unverifiable out of 408
- **Where**: `method.md`
- **Anchor**: `Do not tell a skeptic to "default to refuted on doubt"`
- **Evidence**: On a live build every one of 13 batch prompts ended with it: the result was 0 unverifiable out of 408 across 13 independent agents, 1.7 % refutation against the ~11 % these paragraphs were written from, and not one of 396 confirmed notes containing a word of hedging.

### R65 — Dropping --reconcile moved the claim count
- **Where**: `method.md`
- **Anchor**: `dropping that flag silently discards every subsystem`
- **Evidence**: Dropping `--reconcile` on the second assemble changed the claim count from 444 to 447 on a live map.

### R66 — assemble idempotence, as verified
- **Where**: `method.md`
- **Anchor**: `Step 3 is safe because `assemble` is idempotent on claims`
- **Evidence**: Verified over a real build's fragments: three runs, 444 claims every time.

### R67 — A refuted claim whose text did not change
- **Where**: `method.md`
- **Anchor**: `**a REFUTED claim that is NOT superseded** — the reconcile changed something`
- **Evidence**: On a live build `E35 (UpstreamState) has states […] with 10 transition(s)` was refuted, the wrong transition was corrected, and the claim string came out identical: 5 refutations, 4 superseded.

### R68 — 418 of 418 challenged, quoted as fact
- **Where**: `method.md`
- **Anchor**: `describes a worklist that no longer exists`
- **Evidence**: A live build wrote the record first, then reconciled nine refutations, and shipped `418 of 418 challenged` on a map whose worklist held 415 and of which only 403 could still be matched — then quoted the 418 in its commit message as fact. A hand-written record on another build asserted anchors had been "corrected" 29 seconds before the tool that corrects them first ran.

### R69 — The endpoints-only key that swapped a paired edge
- **Where**: `method.md`
- **Anchor**: `matching each on the full `(src, verb,`
- **Evidence**: A hand script that keyed on endpoints only once swapped a paired `persists`/`reads` edge.

### R70 — Three confirmed-but-wrong findings that vanished
- **Where**: `method.md`
- **Anchor**: `row is the one that disappears`
- **Evidence**: On a live build three of those — an incomplete messaging publisher list, a wrong state transition, a store note naming a field that is never stored — were read, agreed with, and then reached neither the map nor any record. All three claims stayed CONFIRMED and the record read 100 % clean.

### R71 — The security-row script that overwrote a confirmed claim
- **Where**: `method.md`
- **Anchor**: `**Never hand-script a security-row edit.** `fix security-row` selects EXACTLY`
- **Evidence**: The hand script this replaced selected with `'admin' in surface.lower()`, matched two rows, and overwrote a CONFIRMED claim with the refuted one's replacement text; the lead then read the two identical rows as a duplicate and deleted one. Only `grounding report` caught it, three assembles later.

### R72 — The minority refutation that was right
- **Where**: `method.md`
- **Anchor**: `**The vote is advisory; your re-read decides.** When N skeptics split and you`
- **Evidence**: A live build correctly applied a 1-of-3 minority refutation after verifying the dissenter was right about an inert constructor guard.

### R73 — The two orderings that could not both hold
- **Where**: `method.md`
- **Anchor**: `is second-to-last.** The sequence below is the single one; where an older note disagrees, this wins.`
- **Evidence**: This used to be stated in two places that could not both hold: "`grounding write` runs after the final reconcile edit, followed by ONE assemble", and "the anchor-drift reconcile is the TERMINAL write, no re-assemble". A live build followed the second, `finalize` then raised `live_claims_digest does not match this map`, and the whole tail — drift fixes, record, assemble — was redone by hand.

### R73b — Four steps the single sequence did not name
- **Where**: `method.md`
- **Anchor**: `**Steps 5, 8, 9 and 12 are here because the list without them cost real builds.** `grounding`
- **Evidence**: The block called itself the one sequence while omitting `grounding report`, `provenance stamp`, the header `built` backfill and the combined `finalize`. A build that followed it literally wrote the grounding record twice (once without a note, then again after reading `report`), and ran `finalize` twice — the second run, without `--verdicts`, overwrote the report and dropped its verdict-based anchor-drift leg and the "challenged N of M" coverage line from the committed record.

### R74 — Three builds lost their fix edits
- **Where**: `method.md`
- **Anchor**: `Steps 3 and 4 are the change. `fix` edits the ASSEMBLED map, and the source`
- **Evidence**: Three builds hit the discarded-`fix`-edit trap, one of them re-typing 14 anchors by hand.

### R75 — The undocumented reconcile directive names
- **Where**: `method.md`
- **Anchor**: `The directive shape (also in `assemble --help``
- **Evidence**: A live build had to read `reconcile.py`'s source to find these field names, because nothing wrote them down.

### R76 — The retyped harvest contract that dropped three rules
- **Where**: `method.md`
- **Anchor**: `Do not `Read` it and `Write` your own`
- **Evidence**: One build retyped 5.6 KB into a scratchpad and the copy drifted from the tool it described; the next produced 11 KB against a 5.6 KB body, silently dropping the template's anchor rules for `edges[].where`, `subsystems[].source` and `tests[].file` from the contract all twelve agents were handed.

### R77 — Two hours lost to a stray scratch comment
- **Where**: `method.md`
- **Anchor**: `do NOT block: proceed automatically as **B**`
- **Evidence**: A build once lost about 2 hours blocked on a single stray scratch comment.

### R78 — The map that shipped an hour-wrong build time
- **Where**: `method.md`
- **Anchor**: `is stamped LAST and copied BACKWARDS`
- **Evidence**: The rule used to say "capture the minute once and reuse that exact string in both the header cell and the stamp below", which is only safe when the two happen minutes apart. One build wrote `built: 2026-08-13 22:30` into its header near the start, passed that same string to `--built-at` at the end, and shipped a map whose own files were last written at 23:21.

### R79 — 63 per-plugin coverage records written by hand
- **Where**: `method.md`
- **Anchor**: `It is **boundary-scoped**: a real gap in an *unlisted* dir still warns, and`
- **Evidence**: One `plugins/` line replaces the 63 per-plugin records a live build hand-wrote.

### R80 — Every measured way a build narrowed its own gate read
- **Where**: `method.md`
- **Anchor**: `- **the report is a FILE.** A file survives `> /dev/null`, `| tail -12`, and`
- **Evidence**: A live build piped `validate` through `grep`, sent `audit` to `/dev/null`, and then told its operator "gates clean" with four warnings and two advisories open. A later build read every Phase-3 gate through `| tail -40` / `| head -14` and paid for it in four serial `validate` rounds, each surfacing a different untouched warning family; the same build re-checked with a grep whose pattern no longer matched the wording, and that finding shipped unrecorded and unfixed. A later build ended with `validate … | grep -ciE '^  - '` and the answer `11`; everything after — the audit, a 548-claim pin, an 18-skeptic fan-out, the commit — rested on a warning list nobody had looked at, three advisories went into Phase 4 neither fixed nor recorded, and the count was identical before and after the record it was meant to verify. The same build ran `audit --json`, printed `len(worklist)` and the theme table, and never read the `findings` key of the file it had just written — which carried a WARNING naming its own four freshly-written exception lines, three of them sharing one key. A later build piped `validate` through `grep -v 'declared .* times with differing'`, hiding 38 duplicate-edge warnings that stayed invisible across two assembles and an entire grounding pass — the same 38 `fix dedup-edge` listed when it was finally run 30 turns later.

### R81 — Three false clauses in a commit message
- **Where**: `method.md`
- **Anchor**: `closing report, not a summary from memory.** Its stdout can be piped away:`
- **Evidence**: (Since 2026-10-08 a build writes no commit message; the rule binds its closing report.) A live build quoted the verdict honestly in chat ("that is not a clean pass") and then wrote `validate … clean … anchor-drift clean … each reconciled or recorded` into its commit: three false clauses against its own report, with an anchor count copied from a validate run 32 minutes earlier.

### R82 — A map that cost hours and hundreds of dollars, left in one working tree
- **Where**: `method.md`
- **Anchor**: `never runs `git add` or `git commit` on it: whether and how the map is kept in git is the operator's choice`
- **Evidence**: RETIRED on 2026-10-08 by the operator, and REVERSED: "Then actually commit" was the rule this entry justified, and a build now commits nothing. The risk below is accepted on purpose, because keeping the map in git is the project owner's choice; two of the projects mapped then hid `.coyomap/` in their own `.gitignore`, and the build force-added it anyway. Do not re-add a commit step on this evidence. The original account: a live build ran the gates, wrote the report, and stopped — leaving `.coyomap/` untracked, so the map it had just spent 103 minutes and hundreds of dollars building existed only in one working tree. Two of the scorecard's assertions have never had an opportunity to score on that project, because both read the commit.

### R83 — Nine advisories neither fixed nor recorded
- **Where**: `method.md`
- **Anchor**: `also reads the advisory disposition`
- **Evidence**: `finalize` stated the rule ("either fixed or recorded") and used to check nothing; nine advisories shipped on one map neither fixed nor recorded, invisible because every read of the list had been narrowed by a grep.

### R84 — 29 duplicate-edge rows dropped unreviewed
- **Where**: `method.md`
- **Anchor**: `drops the rest. **Some advisories deliberately name no heading.** `tests/test_method_contract.py`'s`
- **Evidence**: A live build hand-wrote a 40-line script for 24 of these and dropped 29 rows unreviewed, against this method's own rule that these mechanical edits are never hand-scripted.

### R85 — Four advisories with no home and no right stock answer
- **Where**: `method.md`
- **Anchor**: `**Never call one "recorded"**: an advisory whose stock remedy would inject a misattribution`
- **Evidence**: On a live map two `C→broker` advisories named publishers whose own source holds zero references to the broker (it is reached through an event-stream adapter), so "author the edge" would have injected exactly the misattribution the grounding skeptics are told to refute; and two minted-bucket advisories asked for a rename "on rebuild", which is nothing to do now. Four advisories, no home, and both stock answers wrong.

### R86 — The drift-exception key regex that rejected quotes
- **Where**: `method.md`
- **Anchor**: `AND any line that opens with `anchor-drift` but does not parse — an unparsed`
- **Evidence**: The key regex used to reject every quote character, so a cadence claim — always phrased `runs on cadence '<x>'` — could never be recorded, and the failure was silent. A live build wrote two exceptions in the printed format, watched them do nothing, and had to read `anchor_drift.py` to find out why.

### R87 — The bucket a project was told to rename forever
- **Where**: `method.md`
- **Anchor**: `has its own escape: `Bucket vocabulary``
- **Evidence**: A real project hit this: an MCP gateway genuinely has an "MCP protocol" bucket, and the nudge asked it to rename on every rebuild.

### R88 — The prototype screens that were confidently wrong
- **Where**: `method.md`
- **Anchor**: `is unfalsifiable, and hand-assigned data rendered as derived`
- **Evidence**: This is what made the first prototype's screens confidently wrong.

### R89 — Two drift findings recorded without opening a file
- **Where**: `method.md`
- **Anchor**: `**OPEN THE FILE before recording one.** The escape is for "the skeptics read`
- **Evidence**: A live build recorded both of its drift findings as false alarms with no `Read` and no grep of either cited file, reasoning instead about what a cadence anchor "is defined to point at". The two SECURITY anchors in the same run were properly checked against source first, which is the standard.

### R90 — Two hours lost to the pin question asked late
- **Where**: `method/dispatch.md`
- **Anchor**: `moved from the END of the build to the front, where changing your mind is free`
- **Evidence**: A build once lost about 2 hours blocked on the pin question after the fact.

### R91 — The rebuild that reproduced the archived map
- **Where**: `method/dispatch.md`
- **Anchor**: `A build that reads the map it is replacing is no longer independent of it`
- **Evidence**: On a live rebuild the lead printed the archived map's title and goal, and the new goal then reproduced the old one near-verbatim for two sentences, while the dep buckets were inherited on purpose "for stability".

### R92 — Why the barrier rule was copied into dispatch
- **Where**: `method/dispatch.md`
- **Anchor**: `harvest, trace, and the Phase-4 skeptics. **The wait is a TEXT turn. Emit no`
- **Evidence**: The rule lived only in `method.md`, inside a block introduced by "Parallel mode covers HARVESTING ONLY … Verification is NOT part of it", and `dispatch.md` did not contain the words *poll*, *sleep*, *Monitor*, *notification*, *wait* or *barrier* anywhere.

### R93 — A verdicts file tallied 22 seconds early
- **Where**: `method/dispatch.md`
- **Anchor**: `**The agents' completion notifications ARE the barrier signal.** They arrive`
- **Evidence**: On a live build a verdicts file was tallied 22 seconds before the agent writing it finished, and only luck kept the read from being truncated JSON. Another live build had all fifteen completion notifications and counted files anyway.

### R94 — 88 of 278 tool calls spent polling
- **Where**: `method/dispatch.md`
- **Anchor**: `**L3 assertion 10 is the enforcement;`
- **Evidence**: One build spent 88 of its 278 tool calls (32 %) on `sleep 1; echo ok`, 77 of them inside a single 9-minute barrier — one poll every 7 seconds — and never called `Monitor` or `ToolSearch` once in 560 turns. The prose in `method.md` had already been escalated twice, citing an earlier build that wasted 22 %.

### R95 — The 2.1x spread across identical skeptic batches
- **Where**: `method/dispatch.md`
- **Anchor**: `**probe the straggler** with `SendMessage` after a couple of minutes of silence`
- **Evidence**: Identical 40-claim skeptic batches have run 4m54s to 10m31s, a 2.1x spread with nothing to sort on.

### R96 — 9.5 KB of replacement prose that dropped a clause
- **Where**: `method/templates/harvest-contract.md`
- **Anchor**: `**Copy this file; do not retype it from prose.** Taken literally that was impossible`
- **Evidence**: One live build produced 9.5 KB of replacement prose and dropped the AGENT_ID clause in the process, exactly the drift this file warns about.

### R97 — 14 of 14 briefs naming no use case
- **Where**: `method/templates/harvest-contract.md`
- **Anchor**: `**The slot that keeps being left empty is «SERVES».** Structural slices exist`
- **Evidence**: On two consecutive measured builds not one harvest brief — 14 of 14, then 13 of 13 — cited a single `UC`/`CAP`/`HP`/`R` id. Every slice boundary was a directory boundary, and the harvest came back with 260 of 260 components carrying no backbone edge. Assertion 31 has scored 0 both times.

### R98 — Why the harvest contract left method.md
- **Where**: `method/templates/harvest-contract.md`
- **Anchor**: `**The template starts at the quoted block below.** Everything above it is instructions`
- **Evidence**: This contract used to live inline in `method.md`, and every build hand-copied ~5.6 KB of it into a scratchpad. That retyping is where wording drifts: one live build's copy promised that a `.draft.json` suffix "keeps a half-written file out of the assemble glob", which was not true of the tool at the time and had to be fixed in both places.

### R99 — Six of fourteen agents wrote a generator script
- **Where**: `method/templates/harvest-contract.md`
- **Anchor**: `that GENERATES your fragment.**`
- **Evidence**: Six of fourteen agents on one build wrote a generator script instead. It predicted nothing about speed — the fastest agent of all used one — but the two slowest agents in that fan-out were both paying the patch-generate-copy-relint cost. On a live build a harvest agent that delegated returned prose instead of writing its fragment, and the whole slice had to be re-harvested. **Reworded 2026-09-02** from "writes your fragment" to "GENERATES your fragment", with the boundary spelled out: a 2026-09-02 retro found 9 of 30 harvest and trace agents using a program, and most were PATCHING a draft they had authored by hand — a two-anchor `.replace()`, not a generator. The old wording banned both and could not tell them apart, so the rule was read as broken rather than obeyed.

### R100 — confidence was listed as a stray key
- **Where**: `method/templates/harvest-contract.md`
- **Anchor**: `but `confidence` IS a real field`
- **Evidence**: `confidence` was listed in this template as a stray key while the same template demanded it.

### R101 — Budgets summing to 55 that delivered 86
- **Where**: `method/templates/harvest-contract.md`
- **Anchor**: `it puts the over/undershoot in front of the agent that can explain it`
- **Evidence**: On a live build nine slices dispatched with budgets summing to ~55 delivered 86 components, every slice over, and nobody noticed until the lead's granularity advisory fired after assembly.

### R102 — Every build composed the skeptic contract from prose
- **Where**: `method/templates/skeptic-contract.md`
- **Anchor**: `**Copy this file; do not compose it from prose.** Re-deriving it each time is`
- **Evidence**: A live build wrote a ~5 KB skeptic contract into a scratchpad from `method.md`'s Phase-4 section, and every build before it did the same. An earlier version of this template spelled the map and the repo two ways each: the fill needed four patterns for two values and shipped with four placeholders still in it.

### R103 — 40 quoted booleans refused at the end of a build
- **Where**: `method/templates/skeptic-contract.md`
- **Anchor**: `- `grounded` is a JSON **boolean**`
- **Evidence**: One skeptic built its rows as tuples starting `("true", …)` and shipped 40 quoted strings; `grounding write` refused the whole record ~100 turns later, at the end of the build.

### R104 — 40 fabricated confirmations from one grep
- **Where**: `method/templates/skeptic-contract.md`
- **Anchor**: `and write `evidence` and `note` by hand.**`
- **Evidence**: One skeptic settled 40 claims in 95 seconds from a single directory-wide `grep -n 'pgTable("'`, then emitted all 40 rows from a script — every `note` beginning `Read <file>:` for files it never opened. Those 40 fabricated confirmations are in a shipped grounding record.

### R105 — 0 unverifiable out of 408 (skeptic contract)
- **Where**: `method/templates/skeptic-contract.md`
- **Anchor**: `to "default to refuted on doubt".**`
- **Evidence**: A live build put that clause in every batch prompt and got 0 unverifiable claims out of 408. See also [[R64]] — the same incident, recorded against the method.md rule.

### R106 — The contract clause that caused its own rewriting
- **Where**: `method/templates/skeptic-contract.md`
- **Anchor**: `**WRITE the JSON to your output path, then say only that you wrote it.** Your`
- **Evidence**: An earlier version of this contract said "your final message IS the verdicts file", which is why every build up to that point rewrote the template instead of copying it.

### R107 — Self-activated entry points used to be exempt
- **Where**: `method.md`
- **Anchor**: `are NOT exempt.** A scheduled job is an actor with a goal by the Roles rule`
- **Evidence**: They used to be exempt, on the reasoning that nobody outside asks.

### R108 — A rebuild that shipped component-only flows
- **Where**: `method.md`
- **Anchor**: `leaves the whole domain model untraceable`
- **Evidence**: A live rebuild shipped a flow set that narrated only components, with all gates green.

### R109 — A bare runs-in record that hid six deployment units
- **Where**: `method.md`
- **Anchor**: `silences nothing and says so — a family-wide literal switches off five findings`
- **Evidence**: A bare `runs-in` used to switch off all five findings at once. On a live map a record about two test-profile containers thereby hid six deployment units that had stopped hosting any component.

### R110 — The runs_in family was the second family-wide escape
- **Where**: `method.md`
- **Anchor**: `is NOT a second one: its five scoped literals each silence exactly their own`
- **Evidence**: The `runs_in` family used to be the second family-wide escape; scoping its five literals was the fix. Same incident as R109.

### R111 — The custom-shard fleet that described an edge it never drew
- **Where**: `method.md`
- **Anchor**: `however well its `Purpose` describes`
- **Evidence**: A live map's custom-shard fleet said it "pushes their events to the same broker" and still drew no arrow to the bot it feeds, because neither an edge nor a channel row recorded it.

### R112 — The store-adapter hop a rebuild false-positived on
- **Where**: `method/model.md`
- **Anchor**: `the layered-architecture shape`
- **Evidence**: A live rebuild false-positived on this shape.

### R113 — Paraphrased container names
- **Where**: `method/model.md`
- **Anchor**: ``container` is the LITERAL compartment`
- **Evidence**: Two of three live rebuilds shipped `dep: null` on every store row (same incident as R29). A live map recorded `memberships subscriptions` where the code says `__collection__ = "memberships_subscriptions"`; 12 of its 37 rows were paraphrases.

### R114 — Rich broker edges, zero catalog rows
- **Where**: `method/model.md`
- **Anchor**: `with an EMPTY catalog draw one aggregated advisory`
- **Evidence**: Three live rebuilds shipped rich broker edges and zero catalog rows. Same class as R46.

### R115 — The re-read nobody ever did
- **Where**: `method.md`
- **Anchor**: `**`coyomap validate <map> --ignore-exceptions`** — not a hand-edited copy of`
- **Evidence**: The message used to ask for a re-read against a hand-edited copy of the map with the record removed. No build ever did it, which is why `--ignore-exceptions` exists.

### R116 — Two routes that traded ids
- **Where**: `method.md`
- **Anchor**: `family the tooling mints rather than an agent authoring it, and it is order-independent but NOT add-stable`
- **Evidence**: Entry-point ids were first numbered in fragment-argument order, so swapping two fragments re-pointed a use case at a different front door: measured, `POST /orders` and `DELETE /admin/wipe-database` traded ids, the use case claimed the wrong one, `validate` resolved it happily and the warning count did not move. Sorting by content key removed the order dependence; the ADD dependence is deliberately still there, which is what the rule in the method now warns about.

### R117 — The summary that kept the rules and dropped a flag
- **Where**: `method/dispatch.md`
- **Anchor**: `what replaces it is a summary that keeps the gist and drops the flags`
- **Evidence**: On one live build the lead's context reached 966,568 tokens at turn 745, before the closing sequence, and the harness replaced it with a summary at turn 747. It was a good summary of 1,407 words: it kept the security finding, the operator's rules and the pending steps. It dropped the `--map` of `record`, so the first record after it was lost, and the closing report then said that record existed. The lead re-read the method 0 times after the summary. It was the second compaction of a lead in three builds of the same project, so a summary is a normal event of a long build, not an accident; the build state keeps the flags outside the lead.

### R118 — The wave that filled the lead with receipts
- **Where**: `method.md`
- **Anchor**: `every report and launch receipt they send lands in the context of whoever started them`
- **Evidence**: On one live build the first fact-check wave added 172,726 tokens to the lead's context over its records 1,849 to 2,966. About 60 % came from the skeptics' reports and launch receipts, and 36 % from a queue file the lead kept by hand to run a rolling pool under the harness's 20-agent cap: 31 of its 33 shell calls in that stretch only kept the queue, the queue drifted, and the harness refused one launch. Across the whole build, helper reports, notifications and launch receipts were 41 % of the lead's growth, about 357,000 tokens, and the lead's context reached 966,568 tokens before the closing sequence. A runner holds a wave's receipts in its own context and hands the lead six lines.

### R119 — The findings reader that saw none of the hand-backs
- **Where**: `method/dispatch.md`
- **Anchor**: `open the report it names when its `risk` count grew, and tell the operator about each new `risk` then`
- **Evidence**: On one live build every hand-back, 126 of 126, came through a tool call, as did 119 of 119 on the build before, and the findings reader in `grounding report` read only an agent's text: it printed 0 findings while the lead hand-collected 57 findings from 27 agents into a file of its own. The build's most important product finding, an access escalation, went through that improvised file, and a second one never reached the operator. The reader was deleted rather than fixed: it read one harness's transcripts, it read text where the hand-backs arrive as a call, and kept, it would be a second channel beside the findings file. A finding filed the moment it is seen, into the agent's own file, does not depend on a hand-back arriving or being read.
