# Retro backlog — what past retrospectives proposed, and where it stands

A retrospective's report lives in the reviewed project's `.coyomap-eval/`, which is scratch: it is
git-ignored, regenerated per run, and one `git clean` from gone. The proposals in it are the durable
part. They live here.

**Step 0 of `method.md` (this directory) tells a retro to read this file before it starts.** That is
the whole point: it stops the next run re-finding what is already fixed, and it stops a proposal
quietly dying because nobody wrote it down.

**Status is dated, never trusted.** Tools move — on one occasion within hours of the report that
prompted the change. Re-check every OPEN item against the tool as it stands before you act on it or
report it, and correct the line here when you do.

Each item carries the finding it came from and what it would have to read to be implemented.

---

## Landed

Verified against the working tree on **2026-08-16**. Pushed to `origin/main` on 2026-08-19.

| what | evidence |
|---|---|
| `audit` routes an `access: true` rule site to the `security` theme | `audit_model.py` — `theme="security" if br.access else "rule"`. This was the top-ranked finding of the 2026-08-13 coworker retro: the theme the audit orders first was permanently empty after auth surfaces moved into rules, so 200 access claims triaged as ordinary ones. |
| `process_scorecard` sees a subcommand called through a shell alias, and its quote scanner no longer eats invocations | `_COYOMAP_SUBCOMMANDS` now carries `grounding`/`finalize`/`record`; one quote scanner. Between them these two bugs mis-measured nine of the twenty-two scored lines on two consecutive builds. |
| `reconcile` can express the assignment the method prescribes | `reconcile_build.py` `_FIELD_OWNER` now carries `capability` and `entry_points`, matching the consumer it claims to mirror. |
| `cost --map` divides refutations by what was challenged, not by the worklist total | `cost.py` — falls back to `claims_total` only when `claims_challenged` is absent, and prints the partial denominator. The old form understated the rate by about half on both measured builds. |
| The retro method reads the per-agent transcripts, refutes its own findings, and checks the map | `method.md` in this directory (commit `6c2fb24`). |
| The map records WHICH coyomap built it; `compare` leads with the difference | `0a57a81`. Closes the cross-schema guard properly: it records the fact instead of inferring it, so it also catches tool changes that are not schema changes. |
| `balance` is reproducible | `0a57a81`. It was not: five identical runs printed three different seam lists, because equal-weight seams fell back to set iteration order. Found by a before/after harness on its first use. |
| `dump --map <path>` | `0a57a81`. |
| `lint-fragment` leads with its verdict, and runs the reciprocal domain-card check | `4d0ecd9`, `ac59f4f`. The verdict used to print last, so an agent's `head -40` hid a pass twice; the missing check let 33 blocking errors reach assembly. |
| `scope` warns when a previous map is being read as source | `4d0ecd9`. |
| `preindex --report --dirs a,b,c` | `4d0ecd9`. A ranking cannot answer "E for the slices I chose". |
| `reconcile` checks the assignment TARGET exists, and summarises | `f086f0b`. Plus `--only-unmatched`. |
| `scope` keys the stray-map warning on CONTENT, not a name prefix | `b21ef32`. It matched `.coyomap*` and so missed `map-backups/` — where this tool's own backup command writes. |
| `lint-fragment` survives a truncating pipe, and its verdict does not collide with the OK rows | `b21ef32`. |
| `preindex --dirs` normalises the path and distinguishes "exists but scores nothing" from "not a directory" | `b21ef32`. |
| The disposition table only accepts ids the MAP defines | `b21ef32`. It read `S3` out of "artifacts in S3" and `C4` out of "the C4 container view"; a false id can flip a real gap to "recorded". |
| `balance` renders the DOMAIN forest | `e75e89d`. `validate` advised on subdomain fan-out and ended "(`coyomap balance` proposes splits)" — a promise it could not keep. Surfaces four dense diagrams (13/23/22/27) on the coworker map. |
| `grounding lint` — malformed verdicts and fabricated evidence, at the skeptic | `988f51a`. `--agent-transcripts` flags a note claiming a read the agent's own transcript never made. |
| `fix row --set-json-<field>` | `8ad9758`. The four "missing verbs" were one gap: `fix row` could not carry a value that was not a string, which is why all four edits were hand-scripted. |
| Build method: SERVES slot in the harvest contract, fan-out ordering + concurrency cap, the commit step, the archive pointer, no fragment generators | `80e77e3`. |
| L3 assertions 36-39, and 26 widened to `reconcile`/`balance` | `e138a2a`. |
| A committed fragment corpus + assembly regression tests | `f9fbc05`. |
| CLI sweeps for both binaries, with completeness gates read from the dispatch | `760c80a`, `560a471`. Found a live crash in `grounding report` on its first run. |


### Landed 2026-08-17 — from the mcpolis build of that morning (session `0b3af67e`)

Pushed to `origin/main` on 2026-08-19. Gates at the time: `pytest tests eval/tests` **2,125 passed**;
`pyright tools/coyomap eval/tools` **0 errors**. Every one was verified against the real build's
artifacts, not only against a fixture.

**Measurement (`coyomap-eval`)**

| what | evidence |
|---|---|
| Assertion 31 follows a brief that lives in a file | The 15 harvest prompts were one-line pointers (`Read …/prompt-h-domain.md completely`), so the detector scored the pointer and reported 0.00 about a build whose 15 briefs ALL cite use cases. It reads 1.00 now, while the previous build — briefs inline, citing nothing — still reads 0.00. A pointer whose file is gone reads `n/a`, never 0. |
| `_COYOMAP_SUBVERBS` holds every dispatched verb, and `--commands` expands a shell function | `row`, `security-row`, `dedup-security`, `lint`, `stamp`, `show` were all missing, and the scan counted a function DEFINITION instead of its calls. On the build's own transcript the table goes `fix 1` → `fix row 6`, `provenance` → `provenance stamp`, `record 8` → `record 40`; 73 invocations → 111. `test_subverbs_cover_every_dispatched_verb` reads the three dispatch tables so the next verb cannot ship missing. |
| Assertion 38 resolves a shell variable in a redirect target | The worklist was written absolutely and read four times as `$CO/verify/worklist.json`. 0/1 → 1/1. |
| Assertion 3 stops counting a lone dispatch as a failed fan-out | `of` is now batched turns plus SERIALISED one-agent turns; an isolated single-agent job is neither. 5/6 → 5/5. The serialised shape the assertion exists for still scores 0. |
| `cost` excludes coordinator round-trip idle from an agent's duration | The two "slowest" agents held 4.7 and 6.9 minutes waiting for a follow-up; the rework after each took about a minute. Slowest in the trace batch 18.9m → 16.9m, in the rules batch 15.6m → 10.6m. `Actor.span` keeps the raw figure. |

**Tools (`coyomap`)**

| what | evidence |
|---|---|
| `grounding lint\|write\|report --verdicts` is variadic, as its usage line always said | `--verdicts a.json b.json` died on `unknown option(s)`. A bare glob works now; the repeated-flag form still does. |
| `grounding lint` says how much of the pass the evidence check could test | It printed the same line with and without `--agent-transcripts`. On the real build it now says `949 verdict row(s); evidence check covered 16 of 949` — the number this retro had to compute by hand. |
| `dump` reads a flow, a sub-flow and an entry point | `--id UC29` returned `members: []` while a contract handed to 11 agents advertised it as "a use case, with its flow steps and their anchors"; `--id SF200` said `kind: unknown`; 0 of 311 entry points were addressable. All three now resolve. |
| `finalize` names a verdict-based leg it was not asked to run | A second `finalize` (for `--emit-gate-block`, without `--verdicts`) overwrote the report and dropped the leg and its `challenged N of M` coverage line. It cannot be INCOMPLETE — that verdict is for a leg that FAILED — so it is a loud advisory naming the files it found beside the map. |
| `lint-fragment` warns on an authored `runs_in` | Two harvest slices guessed unit names; their own lint passed and the lead's `validate` raised 17 blocking lines. ADVISORY, not blocking: the committed corpus has a lead-authored fragment with 35 legitimate `runs_in` rows, and a single-fragment linter cannot tell the two apart. |
| `record --remove <prefix>` | A stale record was deleted with a `python3` splice of `extras.json`. Removing the last line takes the heading with it. |
| `provenance stamp --update-header <fragment>` | Closes the 2026-08-14 proposal 10: the build hand-edited `header.json` with a heredoc because the tool only printed the string. |
| `balance --map <path>` | Exit 2 before, while `record` / `anchor-drift` / every `fix` verb take `--map`. |

**Method and templates**

| what | evidence |
|---|---|
| The ordering block names all 13 steps | It omitted `grounding report`, `provenance stamp`, the header backfill and the combined `finalize`, while calling itself the one sequence — so a compliant build wrote the grounding record twice and ran `finalize` twice. |
| `grounding lint` is named at verdict collection, with its repeated-flag shape | It appeared 0 times in `method.md`, `method/` and the skill; the lead hand-rolled half of it twice. |
| The harvest template carries the `.draft.json` rule, the do-not-author list (`runs_in` first), per-agent scratch names and the zsh quoting rule | `draft.json` appeared 0 times in the template and 0 times in all 15 dispatched prompts, so the crash-resilience rule reached no agent. |
| A `rules-contract.md` template ships | There was none, so a lead composed one from prose and told all 11 rule agents to write a `block` field `lint-fragment` treats as blocking — the failure fired in 13 of 71 agent transcripts. |
| The skeptic contract has a `«CLAIMS»` slot, plus scratch-naming and quoting rules | An N-vote batch forced the generator to append an "## Override — read this, it corrects one path above" block contradicting the body, in 6 of 30 prompts. Ten skeptics wrote to the same `build_verdicts.py` and one process wrote another skeptic's verdicts file. |
| The anchor-drift pre-pass is a GATE before the skeptic dispatch | Stated as prose it was read as advice: one build ran it once, at the end, with `--verdicts`, and paid three skeptics to report drift by hand. |
| The N≥3 vote's scope is named (the whole `security` theme), with the counter-argument | Two different cuts were written; a build guessed and 8 of its 10 refutations came from single-vote batches. |
| Shared fan-out state must live in the contract, never a per-slice option | 12 of 14 slices got the shared-machinery block; of the two that did not, one was repaired and **the other shipped uncorrected**. |
| `record --line` repeats, `--lines-from` exists, `record` seeds the extras fragment | Every example showed one `--line`; the build spawned 40 processes for 40 lines and defended against a non-problem with a truncating `echo … >`. |
| `method/diagrams.md` is in dispatch's Build reading list; `method.md` says read it in windows | It was cited as authority and never opened; two whole-file reads overflowed the result cap into files nobody opened. |
| The barrier text turn should carry what happens next | The tool-less wait turn is MANDATED and is not the defect; the 18-turn gap between naming a refutation and opening the file is. |

**Not done, deliberately**

| what | why |
|---|---|
| Assertion 10 counting tool-less barrier turns as idle | Proposed before a refuter established that `method.md` REQUIRES a tool-less text turn at a barrier. Implementing it as written would penalise compliant behaviour — the exact bug class this batch fixes. What is worth measuring is the gap between naming a refutation and verifying it, which needs a different detector. |
| `audit --batches` balancing within a theme | Real (6 batches of ≤10 claims each cost a whole fresh-context agent), untouched — it changes how every future build is sliced and deserves its own measured change. |
| A recordable heading for the minted-entry-point-kind and single-reference-sub-flow advisories | Real (5 of 11 advisories are "carried (no escape)", so CLEAN is unreachable), but it is a change to the recorded-exception vocabulary, not a bug fix. |
| `reconcile` merge mode | Still open from 2026-08-14 (proposal 6). |
| Splitting `method.md` | The windowed-read note landed instead; the split is a large structural change. |

---

### Landed 2026-08-19 — from the mcpolis build of 2026-08-18 (session `c72a44ce`)

Pushed to `origin/main`, `b267f1e..3068508`. Gates at the last commit: `pytest tests eval/tests`
**2,244 passed**; `pyright tools/coyomap eval/tools` **0 errors**. Every fix has a test that was
checked to FAIL before the change and pass after — one first draft passed with its fix removed,
because its fixture produced nothing for the failure to be re-ordered ahead of, and a test that
passes before the fix holds nothing.

**Tools (`coyomap`)**

| what | evidence |
|---|---|
| Both CLI entry points line-buffer stdout, so `2>&1 \| tail -N` keeps the FAILURE | Piped stdout is block-buffered and stderr is not, so a failure is re-ordered to the HEAD of the pipe. Three consecutive assembles aborted on a `set` directive naming a deleted rule id, the lead read the tail each time, saw a reassuring `note:`, and went on reading a map the tool had refused to write — 16 turns, taking a round of prose rewrites with it, visible only when the next good assemble dropped the long-sentence count 76 → 53. One line fixes every subcommand; `fix.py` alone has 72 stderr call sites. `bd10157` |
| `grounding report` states the still-live refuted count on its FIRST line and its LAST | `\| tail -40` started inside the refuted list and cut the section header off the top; `\| head -30` ended after the third of five bullets. The lead fixed the three it could see and **two refuted claims shipped in the map**. `bd10157` |
| `grounding write` prints a `NOTE FACTS` block | A note said "Eighteen fresh-context skeptics" of a build that dispatched 17 and produced 20 labels, and "Four superseded claims had been CONFIRMED" where the true count was 11 — seven overrides of settled verdicts undisclosed. Both numbers were computable at the moment the note was written. `bd10157` |
| `audit --json` emits `where` beside `location` | The text report prints `where:`; a script read `f.get("where")`, matched nothing, printed nothing, and the next turn redid it by grepping the text. Both keys ship; a rename would break existing readers. `66d2b39` |
| `reconcile` warns when `--out` strands the live directives | The carry-forward is keyed on `--out`, so `--out /tmp/…` silently lost keep_edges (5), drop_edges and set_anchors, and the lead hand-merged them. The tool's `Next:` hint then echoed the temp path into the suggested `assemble`. `66d2b39` |
| The flow-duplication advisory moved to `validate` only | Its escape is an extras heading read from the model being checked — one fragment under `lint-fragment`, while the heading lives in `extras.json`. A build recorded exactly the line it was asked for and got the identical warning back. `--ids` harvests id tokens, never extras. `66d2b39` |
| `finalize` runs `balance` as an INFORMATIONAL leg | A skipped Phase 3.5 and a passed one read the same. One build ran `balance` three times, the next ZERO, and nothing noticed. Never gates: method.md says balance "never gates and only ever re-groups". `66d2b39` |
| `record` refuses a line that keys to nothing | It checked the heading and the presence of a why, then wrote whatever it was given. `read-before-create HP2, read-before-create HP3: …` — the check name repeated inside a comma list — keyed zero ids; unrecorded advisories went 1 → 9 and three extra finalize+render rounds were spent finding the shape by trial. Only the lines THIS call adds are checked. `68f4b06` |
| `grounding lint --expect <batch-ids>` | A missing verdicts file is the one failure nobody spots by eye. One run printed `VERDICTS OK — 18 file(s) well-formed` while a nineteenth was landing, then ran four verdict-consuming commands against the incomplete set. `68f4b06` |
| `grounding report` lists `ADDED SINCE THE PIN` | `write` printed how many and nothing said which, so a build hand-diffed `audit --json` against the worklist in python and then hand-edited the pinned file. `68f4b06` |
| `validate` and `finalize` name `coyomap record` in a footer | Sixty advisory strings end by naming an extras heading and none said what writes one. `record` is named six times in `method.md` and the build used it ZERO times, against forty on the build before. A footer, not sixty rewritten strings, and quiet when every escape is already recorded. `8a36641` |
| `lint-fragment` runs the operative-line check, ADVISORY, with the count in the verdict | The self-check every contract names was blind to the largest defect class it produces: six hand-authored fragments printed `LINT OK — 0 problems` and the next `validate` raised 86 drifted anchors over 366 call-site anchors. Advisory for at least one build — blocking would have failed six fragments on a build that shipped clean. The count rides in the verdict because the agents read this through `head -60`, `head -20`, `head -5` and `tail -20`. `2d325cb` |
| A component's own `purpose` is an L2 claim, themed `description` | Nothing read the map's prose against the code. A map shipped `C36` saying a sign-in guard "refuses to be built at all…" beside its own `BR21` saying that guard "cannot fire" — the true reading. The rule had been challenged and corrected; the sentence next to it was in no worklist. 80 claims on that map, 500 → 580, ~$8 a build. Sorts ABOVE `backbone`: a backbone edge is at least anchor-checked, a description is read by nothing. `3068508` |

**Measurement (`coyomap-eval`)**

| what | evidence |
|---|---|
| `_python_write` sees a path bound to a variable and written through `open(var,'w')` | The dominant hand-edit shape in two measured builds, and neither the literal-path patterns nor `_VAR_BOUND_WRITE` (which covers `Path(…)` + `.write_text()`) matched it. Assertion 27 goes 36/42 → **29/63** and assertion 28's denominator 2 → **11**: the scorecard was reporting about half the hand-scripted edits, in its own favour. `68f4b06` |
| Assertion 21 says when the digest was FILTERED away rather than absent | It printed `n/a — not captured` about an assemble piped through `grep -E "ERROR\|FAILED\|Assembled"`. The digest existed and the build discarded it, which is the class assertion 37 exists to catch, reported as a clean absence. `68f4b06` |
| **Assertion 40** — no sub-agent narrowed its own `lint-fragment` output | The first assertion that reads the per-agent transcripts, because this is invisible anywhere else. 8 of 22 invocations were piped on the measured build. A `grep` FOR the string is not an invocation and is excluded — counting one inflated both halves. `68f4b06` |

**Method and templates**

| what | evidence |
|---|---|
| The retro carries FINDINGS forward and re-verifies them (Step 0b, `findings.json`) | The backlog carries proposals; nothing carried findings, and neither could say whether a landed fix changed anything. `record --line` landed and usage went 40 → 0; the rules contract landed and worker behaviour changed while the churn it targeted did not. `b267f1e` |
| Every finding carries `severity`, `fix_class` and `risk`, and **LOW risk is earned by a test** | Three different questions, collapsed into one impression by a ranked list of prose. The LOW gate moved five rows on a finished report. HIGH severity at LOW risk is the quadrant that sets the order. `e693e46` |
| Step 5b — one reader at the FINISHED report | Step 5 refutes claims mid-draft and overturned six. A separate reader on the finished report then found the most consequential defect of the whole retro (two refuted claims in the shipped map), refuted three of the report's own numbers, and killed its top-ranked proposal by quoting the method line that decided the opposite. `b44d47e` |
| The operator's `decision` is written into the ledger; the per-agent read states its coverage; a hand-rolled number is a draft until a second signal agrees | Three of one report's own figures were wrong: a path set-difference said three files were "never opened" when all had been read, a pipe count said 4 of 23 because a display truncated at 150 characters, and a per-agent read count did not reproduce. `b44d47e` |
| `method.md` names `--expect`, `ADDED SINCE THE PIN`, `REFUTED BUT NOT SUPERSEDED`, `NOTE FACTS` and `--note-file`; all three agent contracts say the lint verdict carries a drift count | Five capabilities existed that no build could reach. This is the `reconcile` class — shipped, tested, and run ZERO times across four builds. A test now checks that direction, which nothing did. `5f5e072` |
| `method.md` says what T7 block bundling costs; `dispatch.md` says the briefing comes before the first tool call | A build gave four of five rule agents two or three blocks each and spent the fresh-context-per-block property without deciding to. Another ran `scope` at turn 6 and emitted two user-facing messages in seventy turns, neither the briefing. `8a36641` |

### Landed 2026-08-20 — from the argus build of that morning (session `446bbaeb`)

Gates at the last change: `pytest tests eval/tests` **2,340 passed** (2,283 before, so 57 new
tests); `pyright tools/coyomap eval/tools` **0 errors**. Every fix was checked to FAIL before the
change. The operator chose "everything ranked HIGH or MEDIUM"; the LOW rows below are deferred, not
rejected.

**This is also the first argus retro to appear here at all** — see `Sources`. The 2026-08-14 one
never got an entry, and two of its proposals are recorded above under someone else's numbering.

**Tools (`coyomap`)**

| what | evidence |
|---|---|
| `lint-fragment --repo` FAILS a header whose `commit` lacks `-dirty` on a dirty tree, and `provenance stamp --update-header` writes the pin itself | The operator was OFFERED and ACCEPTED a `-dirty` pin; the header was hand-written as the bare sha, this lint returned `0 problems` on it, and the final report told the operator the suffix HAD been recorded. Another session then edited a file mid-build and **9 of the map's 10 anchors into it resolve against the wrong lines at the recorded commit**. `scope`, `stamp` and `lint-fragment` now share ONE definition of dirty — which also stops `.coyomap-eval/`, this toolchain's own scratch, reading as the user's uncommitted code (it was the sole reason that build asked the pin question at all). |
| `why-less-step` is ADVISORY, and its message names the line that records it | It was the one substantive check emitted at WARNING, and `_apply_audit_exceptions` suppresses ADVISORY only — so no recorded exception could ever silence it. A build recorded its reading three times, watched the finding survive, then cleared the gate by CHANGING THE MAP: it deleted a happy-path step and wrote two preconditions, one of which is false against the code. |
| `validate` re-reads a `Happy Path coverage` rationale against the walk it describes | Every other check asks whether a gap is RECORDED; nothing asked whether the record is still TRUE. The shipped map says `CAP8: … only the version switch sits on the walk` while **0 of CAP8's 2 use cases** are on it — the step was deleted three turns after the line was written. Catches the dangling-`HPn` shape deterministically too. |
| `finalize --access-baseline <map>` names files that lost their ACCESS claim | The access-rule COUNT held at 21 → 21, so `auth-surfaces-no-drop` passed, while `adapters/auth_google.py` lost its claim outright — the file that verifies the Google ID token's signature, issuer and audience, carried as BR21 by the previous map and by **0 of the new map's 61 rules**. The signal existed only in `coyomap-eval compare`'s notes: a developer-only command, run at retro time, whose output was parked as "a reading job" for three retrospectives. The leg runs after the map is written (so it cannot contaminate the rebuild) and before the commit. New module `access_surface.py`. |
| `finalize` resolves an escape named as a MAP FIELD, not only an extras heading | The disposition table matched `records.KNOWN_HEADINGS` only, so the post-pin advisory — whose own text offers "or say in `grounding.note` …", and whose escape the build had already taken — was filed `carried (no escape)`, and the commit message repeated it. |
| `record --headings`, and `--help` stops recommending the merged form unconditionally | "Write them as one comma-separated list" is right for the 6 headings with a key grammar and destroys the record on the 5 keyed on free text. A build followed it under `Sweep debt`, silenced **0 of 5** anchors, and spent two rounds finding out. |
| `dump --legend` emits `entry_point` rows | **0 of 277** on a map with 108 entry points — the one id kind minted at assemble, so the map is its only mid-build source, while 34 of that build's 65 reconcile `set` entries assign `entry_points`. The lead hand-parsed the map for the ids and then hand-wrote the whole fan-out legend. |
| `validate`'s coverage-line parser strips leading markup | A backtick around the identifier discarded three correct statements in silence; the warning said only "no completeness statement", and the barrier repaired it by RE-RECORDING a second differently worded line. The map ships two ui-route statements, one unreadable. |
| `grounding lint --agent-transcripts` reads `*.output`, and its error names the directory that works | The flag was suggested by the tool twice on one build and used **0 times**: every dispatch result names `<session>/tasks/<id>.output`, and pointing it there failed with "holds no .jsonl". |
| `fix row --edge SRC:VERB:DST` | A fragment edge carries no `id`, so `--id` could never reach one — which is why three heredocs rewrote an edge's `why` by hand two turns after using this verb correctly on a component. Shares every existing guard. |
| `audit --batches` splits a theme evenly | `--cap 40` cut a 42-claim theme into 40 + 2, twice, so **2 of 19 skeptics covered 4 of 388 claims** while a sibling carried 40 and was the slowest agent in its barrier. 21 + 21 costs the same two agents. |
| `preindex`'s granularity NOTE covers both directions | Its escape was written for "if you build under the band". A build landed **27% ABOVE E**, against the note's own stated expectation, inside the ±40% band — so nothing fired and no record was asked for. |

**Measurement (`coyomap-eval`)**

| what | evidence |
|---|---|
| **Assertion 16 ranks by real per-agent duration, joined on the dispatching call's id** | It measured nothing for two builds, and it took THREE bugs: it read duration as launch-turn → `tool_result`, which under async dispatch is the launch ACKNOWLEDGEMENT (4–26 seconds against real runtimes of 1.6–6.7 minutes); it timed from `turn.timestamp`, which every call in one message shares, so the latencies rose with position and the "slowest" was always the last dispatched; and it ranked with `order.index()` over LAUNCH TURN INDICES, which are identical across a one-message fan-out, so `rank` was always 0 and failure was impossible for 4 of 5 fan-outs. It scored **5/5 and 4/4** and a retrospective published "the dispatch-longest-first rule is working" on it. Now **2 of 5** and **1 of 4**, naming the real stragglers. |
| Assertion 8 is scoped to the L2 worklist | The banner it enforces sits under the L2 heading. It counted every audit invocation, so paging the L1 findings block — the human-facing half, which a build must page to reconcile advisories one at a time — scored against a rule about the worklist. It tests for a printed CLAIM ROW now: **0 of 4** this build, **1 of 4** the previous one, against a headline `3 of 12` that was measuring paging habit. Two cheaper tests were tried and are wrong, both recorded in the docstring. |
| `process --diff` flags a score whose DENOMINATOR collapsed | Assertion 35 went `39 of 41` → `1 of 1` and a retrospective read it, in a carried-forward table, as "fixed and proven". 19 of that build's 37 assertions carried one observation or none. |
| `transcript --full` prints a truncation marker for a COMMAND, and `--full-output` lifts that cap too | A bare `[:40]` with no notice and no flag, while the RESULT path two lines below printed a marker and honoured `--full-output`. `--full`'s own help says "include the whole command". 9 of one build's 197 tool-call bodies exceeded it; the worst lost **333 of its 373 lines**, silently, from the retrospective whose whole job is reading what a build hand-wrote. |
| `compare` explains a distinct-hosts drop caused by folding units into variants | `method.md` models one process across environments as ONE unit with a variant each, so adopting the prescribed form READS as a regression and stamped a whole comparison REGRESSED. The GATE is unchanged — `test_compare.py:556` pins that another shape of the same process cannot buy linkage — and a NOTE says what happened. |

**Method and templates**

| what | evidence |
|---|---|
| The trace contract states that a flow OPENS with the actor its use case declares, and `«USE_CASES»` must carry the actors | Nothing said it, the legend prints roles and use cases as two unlinked lists, and `lint-fragment`'s flat id set structurally cannot check it. Eight agents each wrote the caller the code showed them and the lead repointed **34 of 38** role endpoints in one script at the barrier. |
| A `gapfill-contract.md` template ships, and `coyomap contract gapfill` serves it | `method/templates/` had four contracts and no fifth, so the gap-fill slice was hand-composed every build. Its brief was the ONE trace-phase contract of eleven missing "do NOT spawn sub-agents", and lost four more shared blocks with it; the same build hand-wrote its test-completeness brief and lost the no-delegation block and `--expect` too. |
| The "reach for the verb" table names `record --remove/--replace/--lines-from` and `fix row --set-why` | All four shipped, tested, in the tool commit that build pinned, and ran **zero times between them** while six of its heredocs did exactly those jobs — one splicing `extras.json` by string match twelve turns after using `fix row` correctly on the same component. |
| The N-vote rule asks for the disagreement count in `grounding.note` | Three builds have now three-voted an access theme: 160 redundant rows / 0 verdict disagreements / 1 anchor disagreement, then 40 / 0 / 0, then 100 / 0 / 0 — and on the last, all 150 rows returned an `evidence` string identical to the claim's own anchor. Independently written (0 of 50 triples had two identical notes), so it is replication, not copying — but the next decision about the rule should rest on the number, not on one build. |
| `dispatch.md`'s Build step reads the backlog's `owner: the next build` rows, and names `finalize --access-baseline` at archive time | Question 3 was raised 2026-08-19 with its whole experiment written out and costed at ONE agent. The next build ran nine rule agents, none of them that one, and a retrospective then parked the same question a third time. Nothing put the table in front of a build. |

**Deferred, not rejected** (the operator took HIGH + MEDIUM): `coyomap contract prose`; `scope`
excluding `.coyomap-eval` as its own line (it landed inside the pin fix); `finalize` printing the
sub-agent count; `cost` pricing haiku; the trace contract's "do not pipe the lint output" line; the
skeptic contract returning a false-row count; the retro ledger carrying proposals (already open as
item 16 above).


---

### Landed 2026-09-08 — from the mcpolis build of that evening (session `1fe076d7`, retro `2026-09-08_2144`)

Fixed the same night on branch `claude/rebuild-maps-sequence-24c3bf`, each with a retro-check file under
`method/retro-checks/2026-09-08-*.md` and a test; replayed on a copy of the build's map where the closing path was touched.

| what | evidence |
|---|---|
| `record` accepts the 'Walk jumps' heading `validate` names, and `walk_jumps` reads it; a test reads every escape heading off the source | `f5f5cf2`, `00d27bb` (finding 14) |
| `ship` carries `grounding.json` into the map on its first run | `a4ed3c4` (finding 13) |
| `finalize` checks `live_claims_digest` at the record's own tier; the gate block counts one surface and splits the unvoted claims | `a9d8fb4`, `e25d0df` (findings 5, 6) |
| Assertions 12, 14 and 40 read a `ship` build honestly; `ledger` refuses a bare list; `archive` keeps `fanout-timings.json` | `5b21c22` (findings 9, 10, 12, 22, 31) |
| The gate block carries the three-way advisory disposition; `assemble` refuses a duplicate id inside one fragment; `grounding lint --help` names `--expect`; `ship` and `reconcile` say where their lists are | `aab1206` (findings 17, 33, 34) |
| `fix apply-drift` refuses a correction into a file neither end of the edge lists; `contract --fill` refuses a path in a batch-id slot; `ship` passes the newest archived map as `--access-baseline`, and the leg names every file; `provenance stamp` records `tool_commit` | `ff4f816` (findings 2, 3, 18, 32) |
| Six live-map sentences moved to the past; `compare` notes a source root the candidate cites nowhere | `a6e5e7f` (findings 1, 27) |
| The skeptic contract's worked example is no longer mcpolis's own code; assertion 27 follows a fragment directory bound to a variable | `76ca734` (findings 4, 11) |
| `grounding lint` finds this session's agent transcripts by itself; `compare` reports enforcement-FUNCTION agreement and the interface kinds a candidate lost; `validate --json` carries the sweep worklist; `fanout-timings.json` stays out of git | `15ffdbb` (findings 8, 16, 24, 25, 22) |
| Themes under 5 claims share one skeptic batch, security never; prose batches only on `--with-prose`; method.md says what the budget buys every build | `a080fc3` (findings 7, 20) |
| `contract skeptic --from-batches` writes every brief from the batch directory and never rewrites one; `finalize` sums the harvest budgets against what shipped | `53314a6` (findings 19, 28) |
| `validate` discloses every 'Interface exceptions' silence by family; `timings record --from-agents`; `contract tests`; method.md: lint after EVERY wave | `3aaabb8` (findings 15, 23, 21, 16) |
| Review round 3 (8 MED, 6 LOW, all reconciled): the budget leg never blocks and reads the first number of a range, one budgets file per build; the shared small batch is cut at the cap; every scoped `UCn/<gate>` record and stray key is disclosed; `--from-batches` refuses an empty directory; the method prescribes `--fill` for harvest and the tests agent runs after the traced map is assembled | `99c93b8` |

**Decided 2026-09-09 by the operator ("go for all"):** 7 (the verification budget: the behaviour theme
every build, the prose surface on request — landed `a080fc3`) and 8 (the access churn is measured by
function now, and the 19 lost files are answered under question 7 below). **Still open, as
recorded:** 26, 29 and 30, the method-wording rows.

### Landed 2026-10-07 — from the mcpolis build of 2026-10-07 01:11 (session `d55942be`, retro `2026-10-07_0903`)

**Decided 2026-10-07 by the operator:** the 11 low-risk tool fixes (findings 1, 4-10, 21, 23, 24),
finding 14 raised to HIGH with a compaction of the lead made a HIGH finding in every retro, and the
5 shared-code merges the fixes turned up. Fixed on branch `claude/retro-fixes-2026-10-07`, each with
a test and a check file under `method/retro-checks/2026-10-07-*.md`, then reviewed by an
independent sub-agent before landing.

| what | evidence |
|---|---|
| Gate lines survive a cut: the access-baseline advisory counts first and names one lost file per line; finalize's budget leg accepts the granularity line method.md names; five self-contradicting messages corrected | findings 1, 6, 23 · `2026-10-07-a-gate-list-survives-a-cut.md` |
| The closer's brief splits into numbered parts above 40,000 characters; the slot check names every source file in no component slice, not only scripts | findings 4, 7 · `2026-10-07-the-closer-brief-fits-one-read-and-every-source-file-is-in-a-component-slice.md` |
| `record` refuses a positional, an unknown option and a repeated one-value flag, and refuses to write the assembled map while the build's fragments sit beside it, naming the extras fragment to write instead (`--no-reassemble` to override); `assemble` clears the harvest pointer once a dep is linked to a surface; the harvest contract asks each way in for its component and `lint-fragment` warns when one has none | findings 5, 8, 24 · `2026-10-07-record-writes-the-named-fragment-and-harvest-rows-arrive-whole.md` |
| `validate` reads a count only when it counts the kind; `fix` refusals name the fragment files; `timings record --phase tests`; `coyomap dump --owners <file>` | findings 21, 23, 24 · `2026-10-07-validate-reads-only-totals-and-dump-names-a-files-owner.md` |
| `coyomap-eval transcript` renders every hand-back, as a message or a queued attachment, without shifting a turn number; assertion 9 reads the last finalize disposition | findings 9, 10 · `2026-10-07-every-hand-back-renders-and-assertion-9-reads-what-shipped.md` |
| A compaction of the lead is always a HIGH finding: `cost` prints a CONTEXT block, assertion 41 scores it, `eval/retro/method.md` ranks it | finding 14, the flag only: shrinking what fills the lead's context stays open · `2026-10-07-a-compaction-of-the-lead-is-always-a-high-finding.md` |
| Shared code: one list of a component's files (`dump --owners` now answers as `validate` does), one check for a way in's live owner, one rule for the files E counts, one printer for a cut list (22 lists now end on `+N more`), and `validate` blocks a dep still giving the harvest pointer as its reason | `2026-10-07-dump-owners-and-validate-read-one-list-of-a-components-files.md`, `2026-10-07-a-cut-list-says-how-many-it-left-out.md`, `2026-10-07-validate-refuses-the-undecided-interface-pointer.md` |

## Open — tools

What is still open. Landed items move to the table above, with the commit. `scope` here means
what the change would have to read.

| # | change | why | scope |
|---|---|---|---|
| 41 | ~~**A derived fact reaches no skeptic**~~ **LANDED 2026-09-03** | `audit` now raises one claim per derived far side, anchored at the evidence that produced it — the way in that role's own use case drives, else the walk step naming both, else the dependency standing on the surface. 23 of the 24 across the two live maps land on a real line; the one that cannot (a `theirs` surface with no ways in and no dep) is reported UNANCHORED rather than dropped. The trap that had kept it open — a derived claim comes from a JOIN and has no line of its own — is answered by anchoring at the arm of the join, not at the fact. Three tests pin it, including that the anchor is the way in THAT ROLE drives: taking the surface's first put a dev-stub sign-in line under "who is on the far side of the Dashboard". Still open for the OTHER derived facts a reader sees (the features through an interface, the Interfaces picture's order) — the far side was the measured one. |
| 42 | **argus's waitlist entry point says a VISITOR does it, and the code says a signed-in person does** | Found by a partial run tracing UC25 on 2026-09-05, not by any gate. `EP30`'s trigger reads "A visitor leaves an email address to be told when a paid plan opens". The ROUTE is public (`/api/waitlist` is one of two entries in `_PUBLIC_API_PATHS`, `auth_routes.py:514`), but the SCREEN is signed-in only: the button draws only when the loaded plan is free (`PricingPage.tsx:126`) and the modal refuses without a session email (`UpgradeModal.tsx:36`). The use case's own actor is right; the way in's trigger text is not. Scope: one `trigger` string in argus's map, and worth a look at whether other triggers describe the route's reach rather than the screen's — a public route behind a signed-in screen is a shape that will recur. |
| 7 | ~~`record`: repeatable `--line` / `--lines-from`, and seed the extras fragment~~ **LANDED** | The seeding half was yours; `--line` now repeats and `--lines-from <file|->` reads a batch, one process and one write. Every line is shape-checked before anything is written, so a bad one in a batch of twenty leaves the fragment untouched. |
| 43 | **The build profile counts an ADJUDICATED crossing as an open one** — **OPEN** | From the 2026-09-13 reminderrepo retro, finding R3. The profile's `crossings_without_a_door` reads 1 on that map while `validate` reads 0: the single crossing (publishing the phone app to the app stores) is recorded under two extras headings, and the profile counts raw openings only. A retro following Step 1c therefore reports a defect that nobody has. | the profile's crossing count, to report the RAW and the UNADJUDICATED number side by side. `eval/retro/method.md` Step 1c is already reworded against that shape and reads the unadjudicated half as the finding. |
| 44 | **`compare` gates a metric that stops being measurable** — **OPEN** | A metric numeric in the BASELINE and `None` in the CANDIDATE is REGRESSED. Why a gate and not a band: `rules` is written `len(...) or None`, so a section that DISAPPEARS reads `None`, the band demotes to a buried note and the verdict stays PASS. A shrink band catches 88 rules → 20; nothing catches 88 rules → the section is gone, and that is the worse failure. Scope: the 38 `int \| None` / `float \| None` fields of `MapProfile`, the same numeric population the band loop already walks; not opt-in, and it needs no band configured — the point is that no band can see this. Skip: candidate key ABSENT (rather than present and null) means the candidate predates the field. **Blast radius, measured 2026-09-14: 0 trips across 17 real baseline→candidate pairs, and 0 of 38 fields `None` on the four live maps. All 21 explicit nulls in 44 archived profiles are BASELINE-side — the layer being ADOPTED, which this gate ignores by construction — so the skip is a footnote, not the design.** Risk to name in review: `unclaimed_entry_points`, `entities_in_flows` and `edges_per_component` are `None` for a legitimate "not computable" reason, so a candidate that traced nothing trips the gate. That IS a regression, but it would be reported as "the entities-in-flows layer disappeared" when the cause is "this build traced nothing" — a clearer message for that shape, not an exemption. |
| 45 | **The L3 corpus cannot be re-pinned to the data it was built on** — **OPEN** | All nine `test_process_corpus.py` tests assert a `base`-vs-`post` adoption comparison across 2026-07-29 builds, and those nine transcripts have evaporated from `~/.claude/projects/`. Re-pinning is not editing paths, it is rewriting nine assertions around different questions. **Recommendation from the batch that found it: commit two or three hand-trimmed transcripts as fixtures beside `eval/fixtures/transcript/build.jsonl` and pin them the way `FIXTURE_SCORES` is pinned, rather than re-pointing `CORPUS` at more files under `~/.claude/projects/`** — that directory is exactly what lost the first nine. A design call about the instrument, not a bug fix. The gate itself is now loud (asked-for-and-absent fails, un-asked skips visibly). |
| 46 | **Two weak siblings of the assertion-12 `elif` class** — **OPEN** | `process_scorecard.py:721` — assertion 4 labels a call that runs both `finalize` and `anchor-drift` as `finalize` only. `process_scorecard.py:826` — assertion 7 credits a call that runs `coyomap reconcile` AND separately hand-writes a `reconcile.json`. Both lose a fact rather than a measurement and both err toward UNDER-reporting, which the module's own rule permits — recorded so they are not re-found. The rest of the class was swept clean: no other `max(…, default=…)` invents an owner, every other splitter splits on all operators, and the two remaining `[^)]*` patterns start immediately inside `open(`. |
| 47 | ~~**The agent-findings collector cannot read this harness's hand-backs**~~ **SUPERSEDED 2026-10-07** | From the 2026-10-07 mcpolis retro, finding 12. The collector was deleted rather than fixed. An agent now files each product finding the moment it sees it, with `coyomap findings add`, into its own file under `.coyomap/findings/`; `coyomap findings collect` reads every file, and `grounding report` and `finalize` count what was filed. Three reasons: the reader read text while every hand-back arrives as a tool call (it saw 0 of 126), it read one harness's transcripts, and kept, it would have been a second channel beside the file. What the file misses in the hand-backs is row 48. | `tools/coyomap/findings.py`, `method/templates/findings-rule.md` · `method/retro-checks/2026-10-07-agents-file-findings-a-tool-collects.md` |
| 48 | **Nothing counts the findings a hand-back carries that its agent never filed** — **OPEN** | From round 1 of the context work, 2026-10-07. The findings file replaced the reader of the hand-backs (row 47), and an agent may still put a finding in its hand-back instead of filing it. `coyomap-eval transcript` reads every hand-back (`Turn.handbacks`), so the leak is measurable, and nothing measures it: check 1 of `method/retro-checks/2026-10-07-agents-file-findings-a-tool-collects.md` is settled by reading. | `eval/tools/coyomap_eval/transcript.py` (`Turn.handbacks`), beside the build's `.coyomap/findings/<agent>.jsonl` files |
| 49 | **Dependencies can be dropped or left uncategorised in silence** — **OPEN, round 2 (operator OK 2026-10-08)** | Found 2026-10-08 explaining the mcpolis rebuild's deps DRIFT (29 -> 19). Two optional steps, both skipped, neither caught. (1) The lead cut no dependency slice: it wrote a fixed legend of 9 outside services up front (turn 282: "deps authored only by h-ops with fixed legend D1-D9"), so all 14 harvest agents could start at once, and gave dependencies to the operations slice among 4 other jobs. That agent listed services, merged frameworks ("React and Vite") and skipped 12 libraries the previous build's `h-deps` slice had listed (16 of its 29 deps were libraries or frameworks). method.md:2217 assumes a T2 deps slice but nothing requires one. (2) The reconcile pass set 7 fields and no `bucket` (previous build: 17 assignments), so all 19 deps ship with an empty bucket; the viewer then guesses one from `type` + `used_for`, and 8 of the 19 guesses are wrong (Local JSON file storage under Identity & access, Sentry under Integrations, frameworks in external groups). `validate` reported 0 problems. | method: a dedicated dependency slice is required (its legend injected into T5, as method.md:2214-2219 already allows); `validate`: warn on a top-level package in the package files (package.json, pyproject.toml, go.mod ...) that no dep names, and on a dep with no authored bucket; the profile counts both so `compare` can gate them. |

---

### Instrumentation lesson from that investigation (2026-08-17)

Three of four hand-rolled measures over the worker logs were WRONG, and each wrong one pointed at a
different conclusion:

| the measure | what it did | how it was caught |
|---|---|---|
| classify rule workers from their prose | found 9 and 8 workers, then 2 and 0 on a second attempt | the two attempts disagreed |
| identify them by the fragment they wrote | matched `r01-…` in one build, silently ZERO in the other | the two builds name fragments differently |
| count `Read`/`Grep`/`Glob` calls | reported **1** read for a worker that read 30 files | these workers read code through `sed -n`/`grep` in Bash |
| count distinct source files named in a log | said the newer workers read MORE (38 vs 36) — the opposite of the truth | a file NAMED in the brief a worker was handed is not a file it read |

Every map-based finding held; every shaky number came from hand-parsing transcripts while
`coyomap-eval transcript` was available and unused — the method's own "reach for the verb before the
heredoc" rule, broken by the retro tooling's own author. A retro reading worker logs should use the
command, and should cross-check any per-worker number against a second signal before reporting it.

## Open — build method and templates

These are `method.md` at the repo root and `method/templates/`, not the retro method.

| # | change | why |
|---|---|---|
| 1 | ~~`skeptic-contract.md` needs an explicit falsification mandate~~ **WITHDRAWN — measured, 2026-08-16** | The experiment it was gated on ran: 10 planted falsehoods, four shapes, both contracts, two skeptics each. **10/10 detection either way, zero false positives, identical verdict splits** — the wording made no measurable difference, and the hardest shape (a two-clause rule with only the second clause reversed) was caught every time. The low refutation rate is much better explained by the map being right. Write-up and answer key in `eval/experiments/`. |
| 2 | ~~The skeptic contract must require the claim's own anchor line to be opened per row, and forbid machine-generated `evidence`/`note`~~ **LANDED** `898233a` |
| 3 | ~~Make the harvest contract fillable — complete it with the row shapes, or generate it~~ **LANDED** `80e77e3` (SERVES slot; the contract is still hand-filled) |
| 4 | ~~Harvest and trace briefs must cite the UC/CAP/HP ids their slice serves~~ **LANDED** `80e77e3` |
| 5 | ~~Order a fan-out by expected minutes, not item count; size it to the harness's 20-agent cap~~ **LANDED** `80e77e3` |
| 6 | ~~State the gate-reading rule for `balance` and `audit` explicitly~~ **ANSWERED THE OTHER WAY, 2026-08-19** | Its own note asked whether the tools should resist narrowing instead. The 2026-08-18 build answered yes: restating did not work (`balance` ran ZERO times against three on the run before), so the tools changed instead — `grounding report` states its critical count at BOTH ends, `lint-fragment` puts the drift count in the verdict, `finalize` runs `balance` itself and records it, and assertion 21 no longer reports a filtered view as `n/a`. What is still open is narrower and belongs to whoever writes a gate next: **a gate's headline number must survive both a `head` and a `tail`.** |
| 7 | Resolve the grounding-write ordering tension (**the `--note-file` half LANDED `5f5e072`**) | Recording an advisory is a fragment change, but advisories only surface at the gate step after `grounding write` — so the prescribed order forces a redo loop. The 2026-08-18 build reproduced it exactly: assertion 13 scored 0/1 with four map/fragment writes after `grounding write`, and the note was retyped inline three times (~1,900 characters). `--note-file` is now in the worked example, which fixes the retyping and not the ordering. The ordering half needs a decision: move a validate+audit read BEFORE `grounding write`, or state the loop-back explicitly. |
| 8 | ~~Say where the 3-vote majority goes — the access batches~~ **LANDED** `method.md:1478` | Verified on the 2026-08-18 build: the 40 highest-risk access claims were three-voted and the three skeptics agreed on all 40 rows, including the single refutation. |
| 9 | ~~Name `coyomap-eval archive` at the front door of the skill, not parenthetically~~ **LANDED** `80e77e3` |
| 10 | ~~Distinguish *launching* the pre-index from *reading* it~~ **LANDED** `898233a` |
| 11 | ~~Say plainly whether a harvest agent may author a fragment-generating program~~ **LANDED** `80e77e3` |
| 12 | ~~Name `ListAgents` in the anti-polling rule, or bless it as a cheap one-shot~~ **LANDED** `898233a` |
| 13 | When a build request includes a retro, say up front that the retro needs a fresh chat | One build reached turn 537 before finding out. Untouched as of 2026-08-19. |
| 14 | ~~The build must commit~~ **LANDED** `80e77e3` |
| 15 | ~~The rules contract must say that a file handed to a worker is a file to OPEN~~ **LANDED, AND IT WORKS — but the churn it targeted did not move** | `method/templates/rules-contract.md` (2026-08-17) got its first fair test on the 2026-08-18 build: **every one of the 63 files named in a rule worker's brief was opened**, against a previous build whose secrets worker opened none of its handed file. The enforcement-line churn did not follow: 116 → 115 lines with **50 in both**, 50 of a 181-line union (28%), against 57 of 222 (26%) for the pair before. So the diagnosis was incomplete, and the obvious replacement does not survive either — of the 17 files that lost coverage, 14 were in NO rule worker's brief, but access SITES did not fall (123 → 124 across 44 → 47 rules), every one of the 14 is in the map as a component `files` entry, and 8 of the 14 were mentioned inside a worker's transcript anyway. **Now question 3 below, with the experiment that would settle it.** |
| 19 | **The T5 addendum never says what to CALL an entity** — **OPEN** | From the 2026-09-13 reminderrepo retro, finding M1. `t5-addendum.md` and `method.md`'s T5 bullet both said what to MODEL (a real named type whose `source` anchors its definition) and were silent on the name, so the domain agent used the class name: **52 of 59 entity names were raw class names, against 0 of 126 component names**, with a good plain-language `meaning` beside every one. Both files now say the name is the reader's word and the class name lives in `source`. Armed as `method/retro-checks/2026-09-13-an-entity-name-is-the-readers-word.md`. |
| 20 | **Nothing says a lead may build the closer's claims block as refutations ARRIVE** — **OPEN** | From the 2026-09-13 reminderrepo retro, finding M2. The barrier rule already says a refutation is verified when it arrives, and that build obeyed it; what it did in one turn after the barrier was compose all 20 of the closer's claim blocks. That block is the one piece of work an arriving refutation enables. The closer paragraph now says to accumulate it per refutation and dispatch once. |
| 21 | **A destination-table row contradicted `fix row --help`** — **OPEN** | From the 2026-09-13 reminderrepo retro, finding M3. The refuted-access-rule row said "there is no `fix` verb for a rule's text", while `fix row --help` and `method.md`'s own tool table both say the opposite. The build ignored the stale row and used the verb correctly; a lead that followed the table would have hand-edited a fragment, which the method forbids elsewhere. The row now names `fix row --set-statement`. |
| 22 | **`timings record` was taught only in its hand-typed form** — **OPEN** | From the 2026-09-13 reminderrepo retro, finding M4. `--from-agents` reads each slice's minutes off its own agent transcript; `method.md` prescribed `--slice … --minutes <m>` and never mentioned it. Result: `coyomap timings` was typed **0 times** across that build's 6 fan-outs and the repo has no `fanout-timings.json`, so its next build still orders slices by guess. A hand replay against the 70 agent transcripts matched 6 of 6 sampled slices to 0.1 minute, so the leg works; nothing sent a build to it. |
| 23 | **Available verbs and flags named nowhere a build meets them** — **OPEN** | From the 2026-09-13 reminderrepo retro, finding M5. Each existed and was typed 0 times in that build's 117 `coyomap` invocations: `validate --json` (8 of 9 validate runs were read through `cut -c1-150/190/230/250/300`), `preindex --report --dirs a,b,c` (6 turns hand-built per-directory counts with `git ls-files | awk | uniq -c`; `--dirs` appeared nowhere in `method.md` or `method/`), `contract gapfill` (the gap-fill slice ran off a mutated trace slot file), `dump --record` (rules and blocks re-serialized by hand for the closer and the rule briefs). Each is now named in the sentence describing the work, not in a list of flags. **Two the finding named are NOT changed, and the finding was wrong about both.** `validate --emit-unclaimed` IS named at the step — twice in `method.md`, with its reason ("so you adjudicate them in one pass instead of hand-typing the list") — so the build had the instruction and skipped it. That is a different problem from a flag nobody can reach, and a third mention does not fix it; **whatever fixes a skipped instruction is still open, and is not this row**. `dump --legend` is not a deviation either: the trace contract names the assembled map as a legitimate legend, and across all 10 trace agents there are **0 `Read` calls on `legend.json`** — every use is a tool argument, so its 341 KB never entered a context window. Withdrawn. |
| 24 | **`dispatch.md`'s own size numbers for `method.md` rot** — **OPEN** | From the 2026-09-13 reminderrepo retro, finding M6. It called the file "~2,500 lines" when it had reached 3,290, and priced a full read at "four" windows when the lead needed five. The window size itself still holds (the densest 650-line window is ~20,800 tokens against a 25,000 cap). Resolved by REMOVING the rotting numbers rather than re-measuring them, and saying so: the reader divides `wc -l` by 650. This is the same class as the open 2026-09-07 item on present-tense number-claims. |
| 25 | **The shell is not bash, and no coyomap doc said so** — **OPEN** | From the 2026-09-13 reminderrepo retro, finding M7, widened to the whole shell-is-not-bash class. Verified: `bash -c 'set -e; for a in 1 2 3; do false; done'` exits 1 and prints nothing, while the same script through the harness's Bash tool runs every iteration and exits 0. `set -e` appeared 0 times in `method.md` and `method/`, so the lead invented the guard and the guard did not exist: 8 failing `contract harvest --fill` calls went through to a `&&` chain that appended the T5 addendum to a brief no fill had written. **Widened, because it has a sibling with the same signature**: an unquoted `$VAR` holding a list does not word-split in zsh, so `for f in $LIST` runs ONCE on the whole string — three builds wrote 35 `timings record` calls with empty arguments that way, and it happened again to the agent writing this row, caught only because the loop printed one line per item. Both fail silently at exit 0. One rule now in `dispatch.md`, with both instances and the detection habit (print one line per item). |
| 26 | **The retro method told itself to write to `backlog.md` and also forbade it** — **OPEN** | From the 2026-09-13 reminderrepo retro, finding R1. Step 2 said "Append this build's line to the Cost log in `backlog.md`"; the opening says "Change nothing on disk" and Step 6 says "Proposing that edit is the deliverable; making it is not". Resolved in favour of report-only: Step 2 now PROPOSES the row, written out ready to paste, and the 2026-08-27 durability decision is restated so the reason the row exists is not lost. |

---

### Open — from the mcpolis retro of 2026-08-18 (decided by the operator 2026-08-19)

Nineteen of that retro's twenty-four findings landed; these are what did not.

| # | item | decision | why it is still here |
|---|---|---|---|
| 16 | A degraded mode for a fan-out that cannot run | **undecided** | An API outage killed 19 of 61 sub-agents (four records each, zero tool calls, all launched 16:39–17:18). The lead improvised: it hand-harvested 4 of 10 harvest slices and hand-traced 6 of 8 trace slices, and lost the contract's self-check discipline with it — which is where that build's 86 drifted anchors came from. The method describes no degraded mode, so the fallback was invented under pressure. It is an ORPHAN: decisions were recorded on findings and this existed only as a proposal, so nothing ever asked about it. **The ledger should carry proposals too, not only findings.** |
| 17 | The wider prose surface | **deferred** | Component `purpose` landed as the `description` theme (80 claims). Uncut: component `evidence[].why` (371) — which carries a SECOND copy of the false sentence that motivated the whole tier — plus rule-site `why` (187), edge `why` (276) and flow step phrases (372). All of it would be 1,286 claims and roughly double a build. **Widen once the refutation rate on real descriptions is known; the next build gives that number for free.** |
| 18 | Assertion 21's sibling: an advisory whose escape is unreachable from the tool that prints it | **open** | The flow-duplication case is fixed by moving the check to `validate`. `test_method_contract` check (c) asserts an escape is read by the check that prints it and did NOT catch this one, so the check has a reach problem of its own. |

**Rejected, 2026-08-19** — recorded so they are not re-proposed: a placeholder-`purpose` warning in
`lint-fragment` (a threshold, and the harm on the measured build was zero); a rule about the grep
that dropped an `assemble` WARNING (the dangerous half is fixed by line-buffering, and what remains
is a filter habit no test can hold); and a method sentence about the post-hoc `granularity` record
(hygiene, and no test reaches a timing habit).

### Answered 2026-08-27 — the whole 2026-08-26_2158 ledger, 40 rows of 77

Scope: every row open two or more retrospectives, plus every new HIGH row. Verified against the code
and the real maps, not against the rows' own prose. Two adversarial refuters overturned two of the
kills below before they were written. The ledger itself is git-ignored, which is why the answers are
repeated here.

**Rejected — do not re-propose. Each was checked; the evidence is on the row.**

| # | item | why it is dead |
|---|---|---|
| 19 | The readable map file is read by nobody | False. `validate_model.py` re-renders the model and flags a stale or hand-edited `project-map.md`, and `eval/rubric.md` hands it to the judge. |
| 20 | No use case names any entry point | False against the map it was written about: 30 of 30 use cases name entry points, 52 distinct ids. `_trigger_arm_warnings` returns `[]`, which is the check that would fire. |
| 21 | `--agent-transcripts` never passed (open 4 retros) | **Measured by the retro since 2026-09-08**, on both builds of each pair: 56 of 1,180 verdict rows (4.7 %) rested on grep-only evidence against 29 of 850 (3.4 %) the build before. The row is measured, not unproven. Superseded. I ran the check it would have run: `evidence check covered 20 of 1000 row(s)`. The defect is the check, not the missing flag — see the KEEP row for it. |
| 22 | A recorded exception silences one advisory but not its sibling | Wrong reading. The sub-flow refcount advisory is deliberately unescapable and is registered in `KNOWN_NO_ESCAPE` (`tests/test_method_contract.py`), with the reason in `method.md`. The real residual moved to the inert-record row. |
| 23 | The prose counter reads 400 of ~1,437 fields | Duplicate of the prose-coverage row, and its totals do not reproduce (true unwalked: 1,534 and 2,208). |
| 24 | 389 prose fields batched and dispatched on none | Duplicate of the better-evidenced dispatch row. Killing it also removes two probes that both give the wrong answer: `grep -ri 'prose batch'` returns 0 while the instruction exists in `method.md`, and `verdicts-prose-*.json` is a filename the method never asks anyone to write. |
| 25 | The scorecard cannot see `open(var,'w')` | Landed. The class stays open under the `bash -c` and script-by-path rows; decide it there. |
| 26 | Post-pin claims have no lister | Landed. `grounding report` prints `ADDED SINCE THE PIN (n)`. What remains is that `grounding write` REFUSES those verdicts, which is its own KEEP row. |

**Confirmed fixed, verified rather than trusted** — refuted claims no longer ship; `lint-fragment`
runs the operative-line check; both CLI entry points are line-buffered; NOTE FACTS carries
superseded-that-were-CONFIRMED; the description theme is live and caught 5 false descriptions;
`record` ran 15 times; the access-baseline escape works (moving the 20 recorded paths to the new
heading takes the leg from 1 advisory to 0).

**Reopened** — the Step-0 briefing. It IS shown verbatim, but after 10 tool calls, and
`method/dispatch.md` says "before the first tool call". Do not close it against its own probe.

**Seven of these landed the same day, in commits `019f1b6` and `5569348`** — marked LANDED below.
The ledger rows carry the commit. Fifteen keeps are genuinely still open.

**The keeps, ranked.** Full evidence on each ledger row.

| rank | item | size |
|---|---|---|
| 1 | The process scorecard cannot parse `bash -c`, so it is blind to 94 % of the commands it scores | small |  **[LANDED 2026-08-27]**
| 2 | The behavioural half of the map ships with no grounding claim at all — 235 elements, 461 step phrases | large |
| 3 | Two builds of one commit produce different maps; the box count is the loudest symptom | see below |
| 4 | Two access rules carry `confidence: verified` with zero votes | small |  **[LANDED 2026-08-27]**
| 5 | `R1 includes R2` is not enforced by the code, and a role relation cannot carry an anchor | medium |  **[LANDED 2026-08-27]**
| 6 | The fabricated-evidence check covers 2 % of verdict rows and treats any filename token as "opened" | medium |  **[LANDED 2026-08-27]**
| 7 | 136 of 188 customer-facing surfaces carry none of the method's three dispositions | medium |
| 8 | `Drift exceptions` records are inert on the shape-only pass, which finalize always runs — NEW | small |  **[LANDED 2026-08-27]**
| 9 | `grounding report` says "challenge these 21"; `grounding write` then refuses them with a false diagnosis | small |
| 10 | Access enforcement lines agree 55 % at file level between two builds of one commit | restate + one agent |
| 11 | Four fifths of the map's reader-facing prose is never checked | small |
| 12 | The prose batches are minted every build and dispatched on none, three builds running | small |
| 13 | Fan-out scheduling wastes a third of active build time | method prose |
| 14 | `grounding.note` publishes "136 redundant rows" where the true count is 272 | tiny |  **[LANDED 2026-08-27]**
| 15 | `read-never-created HP3-files` parses to `HP3`, so one key silences two findings | small |
| 16 | `coyomap record` accepts a key no reader of that heading honours | small |
| 17 | `lint-fragment` runs no prose check, so 16 long sentences shipped | tiny |
| 18 | `fix row --set-<field>` refuses to create a field the row omits | small |
| 19 | The build hand-scripted 3 mutations a fix verb owns; the detector flagged only the one that never ran | method prose |
| 20 | `finalize` accepts any non-empty `grounding.note` as the answer — a note reading "no." passes — NEW | small |  **[LANDED 2026-08-27]**
| 21 | Nothing notices a sub-agent dispatched and returned empty | small |
| 22 | The retro method gives slice readers no filename rule | one line |

**Why the map doubled, 70 boxes to 118 on the same commit.** Not a method change: the slice-sizing
paragraph is byte-identical between the two tool commits, and `EXPECTED COMPONENTS (E):` was never
in the method at either — the earlier lead invented that field. Not a missing pre-index read: both
builds ran `preindex --report` and saw the full per-directory E table (the scorecard says otherwise,
and the scorecard is wrong — see rank 1). Not bad budgets: the numbers handed out match the table.
What differs is only obedience — the earlier build ran 1.29× over budget with 2 of 7 slices exactly
on target, this one 2.17× with 10 of 10 over. The one visible difference is the FORM of the line, a
labelled field against a `~6 components` aside, and that is a hypothesis across two builds, not a
proven cause. **What is certain: nothing anywhere compares a returned fragment's component count
against the budget its own brief stated.** Build that check and the cause stops mattering.

**The deeper number, which nothing in the toolchain measures.** Two builds of one commit share 55 of
70 component SOURCE anchors but only **9 component NAMES of 70 and 118**; 13 of 47 use-case names;
13 of 47 flow titles; **0 of 76 test-area labels**. `compare` measures name overlap for access
enforcement lines only, and `profile` already collects `entity_names` that nothing reads.

### Investigated 2026-08-27 — why two builds of one commit produce different maps

The question: 70 components then 118, on commit `5dccb1c`, 21 hours apart, no product file
changed. Answered from the 22 archived rebuilds under `.coyomap/dev-rebuilds/`; no build was run.

**What is established.**

1. **The instability is real and it is concentrated in INVENTED names.** Median survival of a
   baseline name across 10 same-commit rebuild pairs: entities 96 %, glossary 70 %, deps 67 % —
   all names COPIED from the code; components 4 %, box groups 5 %, data areas 14 % — all names the
   model composes. 55 files carry a box in both builds and only 6 kept their name. The map points at
   the same code and offers a different vocabulary each time.
2. **The 70 -> 118 growth was every slice running about twice its own budget.** Ten harvest slices,
   ten overshoots: 6->13, 6->10, 2->6, 6->22, 4->8, 5->9, 6->9, 11->20, 4->12, 4->8. Told 54, made
   117, 2.17x — which IS the 2.11 C/E ratio. Not a lost signal: `lint-fragment --expect` fired on
   five slices, all five agents quoted the warning verbatim to the lead, and the lead recorded a
   deliberate `granularity` exception. It was a judgement, taken with the numbers in front of
   everyone.
3. **The operator judges build 23's names consistently better than build 22's.** Four explanations
   were offered for that. THREE WERE WRONG, and each was wrong the same way — a line drawn through
   two points before anyone looked at the distribution that was already on disk:
   - *"Finer boxes name better."* Mostly wrong. Across 446 boxes on three maps the share of
     list-shaped names runs 1 % (one file), 20 % (2-3), 25 % (4-6), 30 % (7-10), 28 % (11+). The only
     sharp break is at ONE file; above that it is flat. On the 49 renames the operator judged
     better, list-shaped names fell only 40 % -> 34 %.
   - *"The granularity band is too coarse."* Not supported. Boxes at the band's ceiling are named
     about as well as boxes of three files.
   - *"List-shaped names are rising, 4 % -> 27 %."* Wrong as first measured: builds 0003, 0014, 0015
     and 0018 name boxes with CODE IDENTIFIERS (`AsgiAppFactory`, `DrainCoordinator`), and an
     identifier cannot contain "and", so their 0 % was arithmetic. Restricted to the 19
     plain-English builds the rise SURVIVES (first half median 4 %, second half 21 %, last four
     builds 29/28/33/27 %) — real, and with no cause found. Do not treat it as explained.
   - *"Build 23 is better."* True but backwards: **build 22 is the outlier.** Its share of vague
     words (plumbing / chrome / machinery / helpers / shell / bundle / glue) is 15 %, the WORST of
     all 22 earlier builds, against a median of 6 %. Build 23's 3 % ranks 4th best of 23. The gap
     the operator saw is one bad build, not a better method.

**The one actionable thing this found.** `method.md`'s leaf rule says a component is "a directory of
<= ~10 source files / <= ~3 kLOC **with one purpose**". The file-count half is computed, banded and
nudged. **The one-purpose half is checked nowhere, and nothing in the toolchain reads a component's
NAME at all** (grep `c.name` in `validate_model.py`: no hits outside id/source/files handling; no
naming rule in `method.md` or `method/templates/`). Yet the name already states the violation: a name
joining two things with "and" or a comma is the build saying in writing that the box holds two
purposes. 32 of the current map's 118 boxes say it. PROPOSED: an ADVISORY on a list-shaped component
name — split the box, or rename it to the one purpose it has. Advisory, not a gate: some joined names
are legitimately one thing.

**Still open, and unaffected by any of the above.** The cut is not reproducible. Nothing makes the
next build land on build 23's granularity rather than build 22's; the better map was luck. And eight
test suites entered build 23 as components while `method.md:988` computes E with test trees excluded,
so that part of the growth is not a better reading of the code.

**Ruled out by the operator, 2026-08-27:** carrying names forward from the previous map. A full
rebuild must not peek at the map it replaces (scorecard assertion 29, and the reason is recorded
there: a build that reads its predecessor is not independent of it, and an eval then reads copying as
convergence). If name stability is ever wanted, the only sanctioned position is AFTER the map is
written and before the commit — where `finalize --access-baseline` already sits, for the same reason.

## Open — questions a retro could not answer

A retro's `Not assessed` block names the tool that owns each question it parked. That naming used to
be the end of it, and the report it lives in is git-ignored scratch — so the question died with the
folder. These are the parked ones, with who can answer them.

| # | question | owner | raised |
|---|---|---|---|
| 1 | Do the 44 access rules of the 2026-08-17 mcpolis map SAY what the previous map's 50 said? The deterministic half is answered — the two maps share 25 % of their enforcement lines, 17 files lost their coverage and 16 gained it, so it is neither a clean merge nor a clean loss. What no deterministic check can settle is whether the surviving statements cover the same decisions. **Narrowed 2026-10-07 — see below.** | `/coyomap-eval` (judges) | 2026-08-17 |
| 2 | Which of the 17 files that lost access coverage hold enforcement the map should still be claiming? Two were verified by hand as real — a sign-in signature check and a credential encryption call — and one old anchor was a config constant rather than enforcement. The remaining fourteen are unread. | a human, or a targeted skeptic pass | 2026-08-17 |
| 3 | ~~What actually causes the access enforcement-line churn?~~ **ANSWERED 2026-08-29 — see below** | the next build | 2026-08-19 |
| 4 | Do the 47 access rules of the 2026-08-18 map say what the previous map's 44 said? Same shape as question 1, for the newer pair: 50 shared enforcement lines of a 181-line union, 17 files lost, 11 gained. **Narrowed 2026-10-07 — see below.** | `/coyomap-eval` (judges) | 2026-08-19 |
| 6 | ~~Is the four-build "0 verdict disagreements" record evidence, or an artefact of a contract that named one repo's answer to every skeptic of that repo?~~ **ANSWERED 2026-09-09 — see below** | one skeptic wave | 2026-09-08 |
| 7 | ~~Which of the 19 files that lost access coverage on the 2026-09-08 mcpolis map hold enforcement the map should still be claiming?~~ **ANSWERED 2026-09-09 — see below.** Nine are OAuth or token handling (`pending_auth.py`, `oauth_refresh.py`, `tool_router.py`, `upstream_oauth_callback.py` among them); the list is in that retro's run directory. Fourth build parked on this shape; `ship` now runs the leg that names them before the commit. **2026-10-07:** BR204, the P1 decision that answer says the map owes, lost every cited file again (see the narrowing below, and question 14). | a targeted skeptic pass, or a human | 2026-09-08 |
| 5 | Is one refuted-claim-in-the-map a pattern? `grounding report`'s `REFUTED BUT NOT SUPERSEDED` section found two on the 2026-08-18 map, both from a reconcile that corrected one copy of a row and left another. Nobody has looked at an older map with the same command. **Re-opened 2026-10-07, not answered:** on the 2026-10-07 mcpolis map 3 refuted claims were kept on appeal, and 1 of them (C142) contradicts the code. | anyone, one command per archived map | 2026-08-19 |
| 8 | Of the **25 saved records no flow reaches** on the reminderrepo map, how many are genuinely unreachable (a record the product keeps for something no use case covers) and how many are a MISSING WALK STEP (the flow does touch them and nobody wrote the step)? The two have opposite fixes: the first is a recorded line, the second is a re-trace. One recorded line under the unstoried heading answers all 25 at once, which is exactly why nobody has separated them. | a targeted skeptic pass, or a human | 2026-09-13 |
| 9 | Is a map's Data section **readable to a non-coder** when 52 of 59 record names are class names (`WeeklyMultipleRequestTypeWithIntervalEndWithOccurence`, `NotificationSecurityData`)? This is NOT the accuracy question — every one of those rows is correct and carries a good plain-language `meaning` beside it. It asks whether a reader who does not read code can use the section at all. The naming rule landed in the T5 addendum on 2026-09-13; `method/retro-checks/2026-09-13-an-entity-name-is-the-readers-word.md` counts the names, and this question is the half a count cannot answer. | `/coyomap-eval` (judges), or a human at the viewer | 2026-09-13 |
| 10 | ~~Has the **`unverifiable` verdict ever been used on a REAL repository**?~~ **ANSWERED 2026-10-07 — see below.** 0 of 2,970 challenged claims across four real project maps (reminderrepo 0 of 946, coyomap's own 0 of 728, mcpolis 0 of 842, argus 0 of 454); 3 of 153 on the Trapdoor planted-defect corpus (`/Users/nitsanseniak/Projects/coyodex-test-project/.coyomap/`), each with a substantive note saying what the skeptic read and why it could not settle the claim. **The verdict is reachable and the contract does make it usable** — `method/templates/skeptic-contract.md:115-121` carries the WARNING against defaulting to refuted, and Trapdoor shows it works. So the question is whether a real repo genuinely settles every claim, or whether a skeptic facing real code reaches for confirmed/refuted rather than admit it cannot tell. Trapdoor is the instrument that could separate them, because it is the one place the verdict has fired. | one skeptic wave designed to produce one on a real repo | 2026-09-13 |
| 11 | Do other shipped claims **contradict evidence the lead held**? Two did on the 2026-10-07 mcpolis map: UC40's outcome, and C142 kept on appeal (finding 3 of that retro). | a human, reading the build's findings file against the map line by line | 2026-10-07 |
| 12 | Did any of the **13 appeals judged without their map rows** go wrong? The 2026-10-07 closer read about a third of its 62,130-token brief and judged 13 of 28 appeals with no map rows shown (finding 4; the brief now splits into parts). | one closer re-run with a paged brief | 2026-10-07 |
| 13 | Do the **18 caveat notes whose claims shipped unchanged**, and the concern notes, hide more defects like BR25? BR25 was confirmed by all 3 security voters, each noting that the check is skipped when the team's runtime is not cached (finding 2). | a targeted pass over those notes | 2026-10-07 |
| 14 | Which of the **20 files that lost access coverage** on the 2026-10-07 mcpolis map hold decisions the map should still claim? 6 previous access rules lost every cited file (BR201, 202, 204, 205, 206, 208); the lead opened 0 of the 20 files. | a targeted skeptic pass, as for question 7 | 2026-10-07 |
| 15 | Does a helper agent limited by `tools:` really **start with a smaller context**? The README's "Long builds in Claude Code" note expects it and says it has not been shown. | one build whose helpers run as a `coyomap-helper` agent: compare the fixed base per agent turn that `coyomap-eval cost` prints | 2026-10-07 |
| 16 | ~~Can a subagent wait on BACKGROUND children, so one agent can run a whole fact-check wave?~~ **ANSWERED 2026-10-07 — see below** | a nesting test | 2026-10-07 |


### Answered 2026-08-29 — question 3, the enforcement-line churn

The mcpolis build of 2026-08-29 ran the experiment as specified: one block's rule worker re-run with
a `coyomap dump --members`-derived candidate list beside the hand-curated control.

| arm | rules | sites | files earning sites |
|---|---|---|---|
| `r1` hand-curated | 8 | 22 | 4 |
| `r1x` map-derived | 8 | 19 | 4 |

**14 shared exact `file:line` anchors**; three of the four files identical (only `service_token_verifier.py`
in the hand arm, only `tool_router.py` in the map arm).

**The candidate list is NOT the cause.** Given the same block and the same code the two arms
converged, which also means the hand-curation step is not buying much — a `dump --members`-derived
list is a viable replacement for it.

**The cause is anchor PLACEMENT.** The map handed `r1x` 143 candidate anchors across 35 files, and
it reported that they "pointed at the right functions, but most of them sat on the call site or the
return, not the enforcing line" — it moved 14 of its 18 anchors onto the actual `if`. Verified
concretely: the map stores `policy_engine.py:317`, which is `if constraint.mode == "forbid":`, while
the only `re.IGNORECASE` is at `:318`. So every build's rule worker re-derives the operative line by
reading the file rather than by trusting the stored anchor, and two builds reading one function land
a line or two apart and are both defensible.

**Corroboration, with the caveat that killed half of it.** On the same pair `compare` gives 37 of a
60-file union shared (62 %) against 54 of a 244-line union (22 %) — file-stable, line-unstable. But
only **12 of 68** baseline-only anchors on shared files have a candidate within ±1 line, and 35 of
190 non-shared anchors sit on files the other map never names, so the churn is mostly NOT the
one-line wobble. **The r1/r1x arms are the evidence; the compare figures add less than they look
like they do.**

**What follows, for the coyomap developer to decide.** Store the enforcing line rather than the call
site when a flow step's `where` is the caller's line, or compare two maps' access rules by FILE plus
enclosing function rather than by exact line. One block on one repo: a data point, not a settled
result.

The write-up came out of a build scratchpad that would have been swept. `method.md`'s closing list
now carries step 12b — write an experiment's answer somewhere durable before the commit.

### Answered 2026-09-09 — question 6, whether the voters ever disagree

The coyomap self-map build of 2026-09-09 ran the wave the question asked for: the whole `security`
theme, three independent skeptics, on the revised contract (the one whose example stopped naming a
repo's own answer, commit `76ca734`).

| | rows |
|---|---|
| multi-voted claims | 27 |
| verdict disagreements | **2** |
| evidence-anchor disagreements | **4** |

**The record is broken, and the dissenter was right.** Two voters confirmed that a rule refusing an
odd version name is enforced at two lines of the map server. The third followed every call site of
that function and ran it: the only production caller passes a value already forced to a bare commit
id, and the refs that really arrive in a web address are guarded somewhere else entirely. An
independent closer, denied the map, upheld both refutations. The map's two citations were dropped
and the line the closer named was added.

**What this says about the four earlier builds.** 160 redundant rows / 0 / 1, then 40 / 0 / 0, then
100 / 0 / 0 — and now 54 / 2 / 4. One run is not a cause, and this build differs from those in two
ways at once (a different repo AND the revised contract), so it does not isolate the contract. What
it does settle is the weaker claim the question was really about: unanimity was not a law of the
method, and the vote can still find something a single voter would have shipped. The next decision
about the three-vote rule should rest on whether that keeps happening, not on the old run of zeros.

**Method note the same wave produced.** Both confirming voters read the anchored line and stopped;
the dissenter read the callers. The difference was not care but reach, which is an argument for the
contract telling a skeptic to follow a guard to its call sites — cheap to state, and untested.

### Answered 2026-09-09 — question 7, the 19 files that lost access coverage

One skeptic read every old enforcement line in the 19 files against the current map's 68 access
rules and the code (report in the fix session's scratchpad, `wave/report.md`; the two inputs are
the previous map's rules for those files and the current access rules).

| verdict | files |
|---|---|
| covered elsewhere — the current map claims the same decision at a different line, usually the shared guard rather than the call site | 11 |
| should be claimed — a real decision no current rule states | 4 |
| not an access decision — the old rule was about shape, cleanup or validity, not a caller | 3 |
| enforced nowhere — the file switches a protection OFF and checks nothing | 1 |

The 4 files carry **3 missing rules**, each a candidate for the next mcpolis build (not added by
hand; a rule is authored in a T7 fragment):

- **P1 — the returning sign-in must prove who began it.** The signed link a member follows back from
  an outside server binds team, server, person and original state, lives ten minutes, and a bad or
  expired signature or a server outside the team is refused (`pending_auth.py:86`,
  `upstream_oauth_callback.py:110`/`:154`). Block: BLK2, beside BR22, which anchors the expiry half
  of the same helper.
- **P2 — the startup sandbox sweep also crosses every team.** The restart sweep reads every team's
  rented machines with no operator behind it (`mongo_sandbox_persistence_repository.py:107`), a
  second crossing BR63 does not mention. Block: BLK4.
- **P3 — whose account an outbound call runs on.** A call to an outside server goes out on the
  caller's own connection, or on the admin-fixed one when the server is configured that way
  (`tool_router.py:922`, `:887`, `:920`). Block: BLK1 or BLK10; the skeptic was not sure.

Two corrections to the retro's own list: `reconciler.py` was never lost from the map, only from the
access rules, and correctly (it is non-access BR146); the two SSRF call sites are covered by BR141
at the transport. So of the "19 lost files" the map owes 4, and the other 15 are the churn the
by-function reading below already predicted.

### Measured 2026-09-09 — questions 1 and 4, read by function rather than by line

`compare` now reports enforcement-line agreement AND enforcement-function agreement (the function
each auth site sits in, from the pre-index beside the map). On the 2026-09-08 mcpolis pair:

| | previous | current | shared | agreement |
|---|---|---|---|---|
| enforcement lines | 194 | 153 | 76 | 28 % |
| enforcement functions | 128 | 108 | 65 | 38 % |

Ten points of the line churn is placement inside one function; the rest is real: two builds pick
different guards for the same decision, and the wave above shows most of those picks are covered
elsewhere rather than lost. The 2026-08-29 answer to question 3 ("mostly placement jitter") does
not hold on this pair. Questions 1 and 4 stay open on their own terms (whether the surviving
statements cover the same decisions), but the number to judge them by is now the function one.

### Narrowed 2026-10-07 — questions 1, 4 and 7

On the previous → 2026-10-07 mcpolis pair, `compare` reads enforcement-function agreement at 90 of
162 (55 %) and line agreement at 105 of 299 (35 %), up from 38 % and 28 % on the 2026-09-08 pair.
The loss did not shrink: 6 previous access rules lost every cited file (BR201, 202, 204, 205, 206,
208), and BR204 is the P1 decision the answer to question 7 says the map owes. The likeliest
mechanism is finding 11 of that retro: files the lead's seed lists left out lost their rules 16 of
25 times, seeded files 4 of 34. Questions 1 and 4 stay open on their own terms; question 14 asks
which of the 20 lost files still hold decisions.

### Answered 2026-10-07 — question 10, `unverifiable` on a real repository

Yes. 19 of 2,086 challenged claims got `unverifiable` on the previous mcpolis build, and 2 of 2,095
on the 2026-10-07 build, all of them steps outside the repository. What stays open is consistency:
the same step shape got `unverifiable` from 2 skeptics and `true` from 13 (ledger row 09-30b-13,
carried).

### Answered 2026-10-07 — question 16, a subagent waiting on background children

Yes, while it stays in its run. On 2026-10-07 a subagent started 2 subagents in the background,
then a third, and received each result while it stayed in its run: each result arrived attached
to its next tool call, for example a call listing which agents were still running. When it ended
its turn to wait, its run ended. So the wave contract tells the runner never to end its run to
wait for a subagent, and to wait inside it by checking which of its subagents are still running.
The group-wise fallback stays for an agent that cannot start subagents in the background.

### Open 2026-09-07 — the 45 number-claims in the tools that can go stale

**The class.** Six defects fixed on 2026-09-07 were all one shape: a sentence that stopped matching
what it described, while the code stayed right. A gate cannot see one, because every instance IS the
code doing exactly what the code says. Four of the six were a NUMBER in a comment or docstring that
no longer held.

**Measured the same day, over `tools/coyomap/` and `eval/tools/coyomap_eval/`:**

| | claims |
|---|---|
| number-claims in comments and docstrings | 958 |
| date fragments, an artefact of the counting regex | 88 |
| **records a PAST build** — cannot rot, it says what happened then | **665** |
| illustrative or neither | 160 |
| **describes a LIVE map NOW** — the class that rots | **45** |

That split is the finding. "Numbers in comments" is not the problem: two thirds are historical
evidence that stays true forever. What rots is a claim phrased about a live map today — "coyomap 2
of 40", "fires three times on the same map" — and those are exactly the four that were wrong.

**The list of 45** was written to `scratchpad/rotting-claims.txt` in the session that measured it,
which is git-ignored and gone. Regenerate it: prose blocks in those two trees carrying `\d+\s+\w+`,
naming argus / mcpolis / coyomap's own map / "live maps", with no past-tense framing (`was`, `were`,
`ran`, `on the 20xx-`, `one build`).

**Why no check was written.** Each of the 45 needs its own probe — re-measure THIS function against
THAT map — so it is 45 small measurements, not one rule. And the three advisories written that same
day each missed the defect they were written for, so a fourth designed at the same speed was the
wrong move. `owner: a session with a fresh head`.

**What would settle it.** Re-measure the 45 and count how many are wrong today. Four of four known
wrong is not a rate. If the real rate is low, this needs no check and the answer is to stop writing
present-tense numbers about live maps in code comments — put them in a retro-check file, where
something already comes back to measure them.

## Candidate L3 assertions

**Five landed as 36-39 plus a widening of 26 (`e138a2a`)**: the piped exit code, the growing gate
filter, the unread `--json`, the empty security theme, and `reconcile`/`balance` joining the gates
that may not be read as a count.

The four below are the ones the scorecard cannot yet reach: it reads the LEAD's transcript, and
these need the per-agent files or a second map. That is a change to what it consumes, not another
detector. **Tagged by what the detector must read**, because the scorecard is a lead-transcript instrument and most of
these are not — an assertion nobody can implement is a proposal that quietly dies.

| assertion | reads |
|---|---|
| Every recorded exception's `(check, id)` pair appears in the gate's live output — the inverse of 24, which catches records that silence nothing | map + gate output |
| A budget deviation that leaves the granularity band carries a `granularity` balance exception at the time | map + fan-out prompts + pre-index |
| ~~No sub-agent narrowed its own `lint-fragment` output~~ **LANDED as assertion 40** `68f4b06` — 8 of 22 invocations were piped on the 2026-08-18 build. It is the first assertion that reads the per-agent files, so the "change to what it consumes" is now made and the remaining two below are cheaper than they were | per-agent transcripts |
| A verdict's `evidence`/`note` does not assert a read the agent's transcript contradicts | per-agent transcripts + verdict files |

The last one is partly built already: `coyomap grounding lint --agent-transcripts <dir>` performs
exactly that check (`988f51a`). What is missing is the scorecard reading it as a NUMBER, which needs
the same per-agent input as the one above it — so both arrive together or not at all.

---

## Cost log

What each build SPENT, one row per build, appended by the retro's "What it cost" step (decision of
2026-08-27). `coyomap-eval cost <transcript> --map <map>` prints every number. Compare per row,
never per build — absolute dollars track how big the map got.

| date | project | rows | active min | $ total | $ / 100 rows | per-role split ($ lead / harvest / trace / verify / other) |
|---|---|---|---|---|---|---|
| — | (four mcpolis builds pre-log measured $189–$207, 61–71 min active, 1,195→1,564 rows; per-role split not recorded) | | | | | |
| 2026-08-26 | mcpolis | 1,288 | 88.9 | 382.42 | 29.69 | 74.26 / 21.50 / 6.06 / 71.98 / 208.61 |
| 2026-08-29 | mcpolis | 1,292 | 156.9 | 493.45 | 38.19 | 82.88 / 83.63 / 87.84 / 162.67 / 76.42 |
| 2026-09-08 | mcpolis | 1,614 | 102.9 | 398.77 | 24.71 | 66.72 / 58.54 / 70.62 / 131.72 / 71.18 |
| 2026-09-13 | reminderrepo | 1,016 | 42.0 | 348.62 | 34.31 | 69.28 / 43.08 / 52.38 / 132.73 / 34.17 |
| 2026-09-30 | mcpolis | 1,486 | 92.5 | n/a — no list price for claude-opus-5-5 | n/a | n/a — cache read 583M (0.39M/row, 1.22× the 2026-09-08 row); output under-recorded |
| 2026-10-07 | mcpolis | 1,559 | 77.1 | n/a — no list price for claude-opus-5-5 | n/a | n/a — cache read 679M (0.436M/row, 1.12× the 2026-09-30 row); fixed base per agent turn 85.9K (was 46.2K) |

**The rows from 2026-09-30 on carry no dollars**, because `cost` has no list price for
`claude-opus-5-5`. Compare them with each other by cache-read tokens per row. The 2026-10-07 lead
was compacted at turn 747; `cost` now prints that in its CONTEXT block.

**Two things about the reminderrepo row.** (1) Its `active min` is the LEAD's own turn span, not
`coyomap-eval cost`'s figure: on this build `cost` over-reports active time by **12.8 minutes**,
because a sub-agent's background command outlived the commit and the window is measured to the last
record. Where the two disagree, the lead's span is the comparable number. (2) **reminderrepo is a
DIFFERENT PROJECT from the three mcpolis rows above it**, with different code, a different size and
a different shape. Its `$ / 100 rows` of 34.31 against mcpolis's 24.71 is not a regression and not a
trend point; only rows of the same project compare.

**The role buckets are not comparable across those two rows** and the totals are. Harvest ran 4
agents then 12, trace 1 then 13, "other" 48 then 14 — the same work moved between buckets as the
fan-out was cut differently. Only `$ total`, `$ / 100 rows` and `active min` compare. Cost per row
rose 29 % and seconds per row 76 %, on a build that ran a whole second phase (the interfaces
section) the first did not.

**~~One open question this log raises~~ ANSWERED 2026-09-13.** The question was: the verify role
went $0.0635 to $0.1499 per verdict row on FEWER rows (1,134 → 1,085), with three candidates and
nothing separating them — `dump` round-trips replacing one map read with many, the skeptic count
doubling (19 → 38), and fixed base context per agent turn rising 52,195 → 64,503 (+23.6 %). It
asked for a build that holds the skeptic count fixed. **The reminderrepo build held it: 38 verify
agents, the same 38 as the 2026-09-08 mcpolis build.** With the count fixed, the rise does not
reproduce — it reverses. Verify tokens per challenged claim fell **205,464 → 175,642 (−14.5 %)**
and dollars per challenged claim **$0.1564 → $0.1403 (−10.3 %)**. That points at the skeptic COUNT
as the driver and away from the other two candidates. **It is one cross-repo pair, not a trend**:
reminderrepo and mcpolis are different projects, so this retires the question as asked rather than
proving the mechanism. A same-project pair would still be worth having.

## Sources

- 2026-08-20, argus (`446bbaeb`) — 25 findings, 22 landed. Report and a `findings.json` ledger were
  at `.coyomap-eval/retro/2026-08-20_1130/` in that project; git-ignored, so this file is the
  surviving record. **The 2026-08-14 argus retro has no entry of its own** — 20 findings, 23
  proposals, of which two are recorded above as "the 2026-08-14 proposal N" under numbering that
  does not match that report. That is the gap open item 16 names.

- 2026-08-18, mcpolis (`c72a44ce`) — 24 findings, 19 landed across `b267f1e..3068508`. Report was
  at `.coyomap-eval/retro/2026-08-18_2257/` in that project, with a `findings.json` ledger beside
  it; both are git-ignored, so this file is the surviving record.

- 2026-08-13, coworker (`3ee6dd61`) — the retro these came from. Report was at
  `.coyomap-eval/retro/2026-08-13_0754/` in that project; git-ignored, so treat this file as the
  surviving record.
