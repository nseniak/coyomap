# coyomap-retro — a retrospective on one finished build

A build just ran. Two artifacts survive it: the **map** it produced and the **transcript** that
produced it. This method reads both and reports what the run says about the tools and the method.

**Report only.** Change nothing **on disk** — no map edit, no tool fix, no method edit. Every finding
is a proposal the user decides on. Saying "I would change X" is the deliverable; changing X is not.
In-memory experiments against the tools are the exception and are encouraged: Step 2 prescribes one.

**Why it is not `/coyomap-eval`.** That one REBUILDS the map blind and judges it against a
baseline: *did quality regress?* This one never builds anything. It asks a different question —
*what did this run reveal?* — and its answer is a list of bugs, friction and gaps. The two are
complementary; neither replaces the other.

## Paths — keep them straight

- **`COYOMAP_HOME`** — the coyomap clone (the skill substitutes the real path). The CLI is
  `COYOMAP_HOME/.venv/bin/coyomap` and `COYOMAP_HOME/.venv/bin/coyomap-eval`; the method under
  audit is `COYOMAP_HOME/method.md` + `COYOMAP_HOME/method/`.
- **The reviewed project** — your cwd. Map in `.coyomap/`, previous maps in
  `.coyomap/dev-rebuilds/NNNN/`, output in `.coyomap-eval/retro/<timestamp>/`.

**`dev-rebuilds/` is a coyomap-DEVELOPER convention and nothing a user of coyomap should have.** A
user's map evolves incrementally with their code, so a from-scratch rebuild is a first-run event and
they never accumulate previous maps. Rebuilding repeatedly is what someone changing coyomap does, and
`coyomap-eval archive` is what files each snapshot. No production code path reads the
directory — a *build* compares against nothing, deliberately. So expect it in the coyomap author's own
repos and expect it to be ABSENT everywhere else; when it is missing, say Step 1's comparison was
skipped rather than treating it as a defect.

---

## Step 0a — Run this in a NEW chat, not the build's own

**If this retro is running in the same session that built the map, STOP and say so.** Check
`$CLAUDE_CODE_SESSION_ID` against the `session_id` in `.coyomap/provenance.json`; if they match, the
retro is invalid and must not proceed.

Three reasons, and the first is mechanical:

1. **It would read the file it is writing.** A transcript is named after its session, and the
   session is the chat. Running here appends the retro's own turns to the `.jsonl` under analysis,
   so the process scorecard counts the retro's commands as part of the build.
2. **Fresh context is the point** — the same reason Phase 4 uses fresh-context skeptics. An agent
   that built the map inherits its own blind spots: it knows why it wrote that workaround, so it
   reads as the obvious thing to do rather than as friction.
3. **Context budget.** A build is 300–500 turns. Reading it in slices AND fanning out sub-agents
   needs headroom a spent context does not have.

Tell the user to open a new chat in the same project and run `/coyomap-retro` there.

## Step 0 — Locate the run, and refuse clearly if you cannot

```
.coyomap/project-map.json        the map to review
.coyomap/provenance.json         names the session that built it
```

**First, refuse if the build has not finished:**

```
COYOMAP_HOME/.venv/bin/coyomap-eval retro-precheck        # exit 1 = do not proceed
```

**Run it bare — never pipe it.** `cmd | tail -3; echo $?` reports `tail`'s status, so a REFUSED
precheck reads as exit 0. A live run printed `PRECHECK_EXIT=0` over the words "REFUSED — provenance
names THIS session". Capture to a file if you want the message and the code.

Step 0a's same-session guard does NOT cover this, and the gap is silent. Provenance is stamped near
the END of a build, so while one is running it still names the PREVIOUS build — a different session
id from yours, so the guard passes, the retro proceeds, and every finding is about the wrong run
with nothing saying so. `retro-precheck` refuses a half-written map, refuses while another
session's transcript is still being written, and — the case the transcript scan cannot see — refuses
while anything under `.coyomap/` is still being written.

**That last check is the one that matters most, because provenance being fresh does not mean the
build is over.** A build stamps provenance and then keeps going: recording advisories, `finalize`,
`render`, the commit. On the 2026-08-01 mcpolis build, provenance said 14:57 and the map was still
being rewritten at 15:43. The transcript scan is blind to it by construction — it must skip the
session provenance names, or the retro would refuse forever after every build — so for 46 minutes
the only answer available was "safe to proceed". Watching the build's own output closes it, and
survives the operator carrying on chatting in the build window after the commit.

Do not hand-roll this wait. The one live attempt used `find -newermt '-120 seconds'`, which this
platform's `find` rejects outright — so the idle test silently read as "always idle" — and it waited
on a `dev-rebuilds/NNNN/` directory that **a build never creates** (archiving is
`coyomap-eval archive`, a developer convention; see the note above). Both conditions were
unsatisfiable, and the finished build went unnoticed for ~90 minutes. Poll the command instead, from
a background waiter, and read its exit code.

Read `provenance.json`. Its last `sessions[]` entry carries the `session_id` and `built_at` of the
build. The transcript is:

```
~/.claude/projects/<slug>/<session_id>.jsonl
```

where `<slug>` is the project's absolute path with every `/` replaced by `-`. **Derive it; do not
guess and do not pick "the newest file"** — several sessions can share a directory, and the newest
one is often the retro itself.

**Locate the per-agent transcripts too — that is where most of the evidence is:**

```
~/.claude/projects/<slug>/<session_id>/subagents/agent-<id>.jsonl      one per sub-agent, full internal turns
~/.claude/projects/<slug>/<session_id>/subagents/agent-<id>.meta.json  which agent that id was
```

Every sub-agent a build fans out keeps a full transcript here — the tools it called, the files it
opened, what it wrote. `coyomap-eval cost` has read them all along and says why in its own `--help`:
they are "~80% of the spend — a reader that opens only the session file measures the lead and misses
the build." That holds for a reader looking for friction too.

Everything a slice reader says about what an agent *did* is otherwise an inference from the text that
agent chose to return, and those inferences go wrong. Step 3 says which of these files to open.

**If the directory is absent, say so and carry on** — a different harness, or a build with no
fan-out, leaves nothing here. Then every agent-level finding is an inference, and the report must say
so rather than imply the agents were checked.

Also locate, for comparison (all optional — say so when absent):

- **the previous map** — the highest-numbered `.coyomap/dev-rebuilds/NNNN/project-map.json`. That is
  where `coyomap-eval archive` puts the map a from-scratch rebuild replaced. Names are zero-padded, so a
  plain sort is a numeric sort; take the last one.
- **the previous transcript** — the `session_id` in that archive's own `provenance.json`.

Stop and say what is missing if the map or the provenance is absent. A retro with no transcript can
still do Steps 1 and 6, and must say that Steps 2–5 were skipped — including the
`Verification status` block, which has nothing to report.

**Then read the backlog and the previous retro, before you create your own directory.**

`COYOMAP_HOME/eval/retro/backlog.md` is the durable record of what past retros proposed and where
each item stands. Read it first — it is tracked, whereas a report is not: `.coyomap-eval/` is
git-ignored scratch, one `git clean` from gone, which is exactly why the backlog exists.

It carries two kinds of item and both bear on this run. The proposals stop you re-finding what is
already fixed. **"Open — questions a retro could not answer" stops you re-parking a question that is
already parked** — if one of them is about the build you are reading, say whether this run answers it,
narrows it, or leaves it alone, and only add a new question when none of them covers it.

Then, if the reviewed project still has one, take the highest-numbered directory under
`.coyomap-eval/retro/` — noting that once you create yours, the newest one is yours, the same trap
this step already warns about for transcripts — and read its `Proposals` for anything the backlog
has not absorbed.

Do this FIRST, not at the end. It changes what the rest of the retro looks for, and skipping it
wastes a fan-out re-finding what is already fixed. Two failure modes it catches, both seen:

- **A fix landed and the docs went on describing the gap.** `L3-DESIGN.md` recorded an assertion as
  not yet reached while it had in fact passed on the last two builds. Nothing re-reads a retro's own
  past claims, so the sentence outlived its truth by several runs before anyone re-scored it.
- **A fix landed between the last retro and this one.** Tools move, sometimes within hours of the
  report that prompted them: the two scorecard bugs above were repaired the same evening the retro
  that found them was written. Re-check every proposal against the tool as it stands right now, and
  carry the answer into Step 6's proposals section. Publishing a fixed bug as live burns the
  reader's trust in the rest.

### Step 0b — Carry the previous FINDINGS forward, and re-verify each one

The backlog above carries past PROPOSALS. It does not carry past FINDINGS, and neither can say
whether a landed fix changed anything. Load the newest
`.coyomap-eval/retro/<ts>/findings.json` and settle every row **before any other analysis starts**.
A recurrence changes what the rest of the retro should look for, and a fix that landed and did
nothing is the most expensive result a method change can produce.

Both halves have been observed live on one build: `record --line` landed as a tool while the build
used `record` **0 times against 40 on the previous build**, and the rules contract landed and did
change worker behaviour while the churn it targeted did not move.

For each row, run both probes.

- **`product_probe`** answers *did the fix land in `COYOMAP_HOME`*. A grep, a `--help` check, or one
  command against a copy. `null` means the finding is not a product change.
- **`behaviour_probe`** answers *does the behaviour still occur in THIS build*, and it must return a
  NUMBER, not a yes. Store it in `observed` and move the old value to `prior`. "Reproduced or
  worsened" is a comparison, and a boolean cannot express one.

Three rules, each of which a real run has already broken:

1. **A probe that cannot run is `broken`, never `fixed` and never `reproduced`.** A renamed command
   turns a silent probe into a false verdict, and a false verdict looks exactly like data.
2. **Zero occurrences with no opportunity is `unproven`, not `fixed`.** Set `opportunity: false` and
   say so. One live case: scorecard assertion 21 printed `n/a`, which reads as "no opportunity",
   while the truth was that the build had filtered the line away with a grep.
   **"No opportunity" means the check CANNOT be run, not that the build did not run it. If YOU can
   run it, run it.** A retro filed `grounding lint --agent-transcripts` as unproven because the
   BUILD never passed the flag — and the check is read-only, takes one command, and the transcripts
   were on disk. Running it turned an open question into data in a single turn: 0 fabricated
   citations, 29 of 1,048 rows resting on evidence the agent may only have seen in a grep. Before
   writing `opportunity: false`, ask whether the retro itself is the missing opportunity.
3. **Do not answer this by re-reading the previous `report.md` prose.** It runs 300 to 900 lines per
   retro, it is git-ignored, and a grep over it is unreliable: one alternation typed with a single
   wrong character reported 0 of 12 reports for a phrase that appears in 10 of them. The ledger
   exists so this step is one file read and N commands.

Then combine `decision`, `landed` and `observed vs prior` into one verdict per row:

| decision | landed | count vs prior | verdict |
|---|---|---|---|
| accepted | yes | 0, with opportunity | **fixed and proven** |
| accepted | yes | lower, not 0 | **landed, improved, not gone** |
| accepted | yes | same | **landed but ineffective** |
| accepted | yes | higher | **landed and worse** |
| accepted | yes | no opportunity | **unproven this build** |
| accepted | no | any | **accepted, not done yet** |
| proposed / deferred | no | higher | **open and worsening** |
| proposed / deferred | no | same | **open, reproduced** |
| proposed / deferred | no | lower | **open, improving** |
| rejected | any | any | listed once, then quiet |

`decision` is the OPERATOR's answer, not the retro's, and nothing else in this method records it.
An item the operator rejected and an item nobody got to must not read the same.

Increment `retros_open` on every row that is not `fixed and proven` or `rejected`. **An item open
for four retros is a different problem from a new one**, and the count is what makes a small
recurring item visible. Carry every row forward whatever its severity: a LOW-severity item that has
survived five retros outranks a new MED one, and only the count can say so.

**Before writing it, run `coyomap-eval ledger <the previous findings.json> --repo <the coyomap
clone>`.** The `landed` flag is hand-set and it is the one input this carry-forward depends on;
nothing checked it until that command existed. On the session that wrote it, an operator answered 40
rows and fixed seven of them in the same session, leaving all seven reading `landed: false` — seven
rows the next retro would have re-proposed with their `retros_open` going up, which is the shape
that ledger already had 24 instances of. Exit 1 names each row whose `landed_in` commit is merged
while the row still calls itself open. It says nothing about a row that names no commit, and prints
how many of those there are: a clean result there is not a clean ledger.

Write the updated ledger to YOUR run directory as `findings.json`, with this run's new findings
appended. The shape:

```json
{
  "schema": "coyomap-retro-ledger/v1",
  "project": "<repo>", "retro": "<ts>", "build_session": "…", "built_at": "…",
  "code_commit": "…", "tool_commit": "…",
  "findings": [
    {
      "id": "<project>-<date>-<n>", "title": "one line",
      "severity": "HIGH | MED | LOW", "fix_class": "HARD | SOFT | HARD / SOFT",
      "risk": "LOW | MEDIUM | HIGH",
      "decision": "proposed | accepted | rejected | deferred",
      "landed": true,
      "product_probe": "…or null", "behaviour_probe": "…returns a number",
      "observed": 0, "unit": "what the number counts, with its noun",
      "prior": 0, "opportunity": true, "retros_open": 1
    }
  ]
}
```

`severity`, `fix_class` and `risk` are defined once, under **What a finding must carry** in
Step 3. They are three different questions and collapsing them into one impression is what a
ranked list of prose does instead.

The ledger is git-ignored like everything else under `.coyomap-eval/`. Anything that must outlive a
`git clean` is promoted into the tracked `backlog.md`, exactly as a proposal is today.

Create the output directory `.coyomap-eval/retro/<YYYY-MM-DD_HHMM>/` and write everything there.

### Step 0c — Run the retro-checks committed since the previous build

Step 0b looks BACKWARD: it re-verifies what past retros found. This step looks FORWARD: it runs
the checks that method and tool changes declared about themselves when they were committed. The
convention lives in `COYOMAP_HOME/method/retro-checks/README.md` — every commit that changes the
method or the tools in a way that should change build behaviour also adds one check file there,
stating the observable outcome the change promises. This step is what makes those promises come
due. Without it, a method change is verified only if someone remembers it existed.

Compute the commit range from data both ends already record:

- **`old`** — the `tool_commit` of the PREVIOUS build: read it from the previous ledger
  (`findings.json`, Step 0b) or, failing that, from the previous archived map's `provenance.json`
  (`sessions[-1].tool_commit`, stamped at build time — the map header's own `tool_commit` is
  re-stamped by any later repair, which once cost a retro 5 of its 13 pending checks). If neither exists,
  there is no range: run every check file still active (not yet in `verified/`) and say so.
- **`new`** — the `tool_commit` of the map being retro'd.

```
git -C COYOMAP_HOME diff --diff-filter=AM --name-only <old>..<new> -- method/retro-checks/
```

Added files are the pending checks. A MODIFIED check file counts as re-armed: someone sharpened
its expectations, so it runs again even if a past retro confirmed the old wording. Ignore paths
under `method/retro-checks/verified/`.

Run every pending check against THIS build. A check file is a prose checklist of observables;
each item gets one of three verdicts, with the same discipline as Step 0b:

- **confirmed** — the observable occurred, with the number and its noun.
- **failed** — the observable did not occur, or its regression sign occurred. A failed check is a
  FINDING: it enters the ledger with a `behaviour_probe`, and ranks with the rest.
- **no opportunity** — the build never exercised the changed path. Mirror Step 0b rule 2: that is
  `unproven`, never `confirmed`. Say what a build WOULD have to contain to arm the check.

A check that names the eval as its escalation ("if X fails, run the eval") is not yours to run —
report the trigger as fired and hand the line to the operator.

The retro changes nothing, so retirement is a PROPOSAL, not an action: for every check where all
items are confirmed, propose the commit that moves the file into `method/retro-checks/verified/`
with a `verified in <project> build of <built_at>` line appended. The operator commits it, or
declines and the check stays armed.

---

## Step 1 — Product signals (deterministic, free, no model)

What the map itself says. Capture each command's output to the run directory.

```
coyomap validate .coyomap/project-map.json --check-sources --check-coverage
coyomap audit .coyomap/project-map.json
coyomap balance .coyomap/project-map.json
coyomap-eval score .coyomap/project-map.json --repo . --json
```

If a previous map exists, score it too and compare:

```
coyomap-eval score <archive>/project-map.json --repo . --json > prev-profile.json
coyomap-eval compare prev-profile.json profile.json --thresholds eval/thresholds.json
```

Record: blocking problems (should be zero), the advisory count and which advisories survived, the
component count against the code-derived expectation E, the map's own `grounding` record
(`claims_challenged / claims_total` plus the confirmed/refuted/unverifiable split), and
every count that moved against the previous
map.

**And read `compare`'s NOTES, not only its gates and bands.** One of them is not a count and cannot
be: the share of the auth surface's ENFORCEMENT LINES the two maps agree on, plus the files that hold
access enforcement in one map and are named by no access rule in the other. Two rebuilds of ONE
commit have come in at 25 % agreement — 163 lines against 116, 57 shared, 17 files covered by only
the older map and 16 by only the newer — while the statement count moved just 50 → 44 and every other
signal read clean. A count can hold steady through a wholesale change of content, so this is the only
place that churn is visible. Report the number and name the lost files; they are the reading list.

**Read `compare`'s verdict as information, not judgement.** A DRIFT on a rebuild is expected — two
LLM builds of one repo never match.

### Step 1c — Did a whole SECTION go unwritten, and did anything say so?

Three of `score`'s counts answer a question the others cannot: not "is this section good" but "did
anyone write it at all". A section with no step sending anyone to author it comes back EMPTY, and an
empty section is the one state most checks are silent about, because they need a row to check.

```
interfaces · interface_doors · crossings_without_a_door
crossings_without_a_door_unadjudicated · interfaces_undecided_deps · interfaces_without_kind
```

Read them together:

- **`interfaces` 0 on a repo with external systems** — nobody was sent. This has happened: a build
  produced 13 external dependencies, 249 ways in and zero interfaces, and `validate` said nothing.
  The dependency worker refused correctly (it sees one slice and cannot group a surface), left a note
  that the field was the lead's, and no step in the build order ever sent the lead back.
- **`interfaces` high and `interface_doors` 0** — the rows were authored and never put into a story.
  The map can SAY what its outside edge is while no walk goes through a door. This reads as success
  in every other count, which is what makes it worth its own line here.
- **`crossings_without_a_door` above 0** — somewhere a person touches the code with no surface
  between them. This is what `interface_doors` cannot see: that count rises on the openings alone, so
  a build that did part of the rule scores as a build that did all of it. It counts STEPS, not flows,
  because a flow counter scores a half-doored story as done. Measured the day the strict rule landed:
  mcpolis read 38 with `interface_doors` already at 129.
  **Read the UNADJUDICATED count, not the raw one**: a crossing recorded under an extras heading is
  a decision somebody made, and `validate` is already silent about it, so the raw number can stand
  above 0 with nothing open. The profile prints both. On the reminderrepo map that was 1 raw and 0
  unadjudicated — the one crossing (publishing the phone app to the stores) is recorded under two
  headings. It is a finding only when the unadjudicated half is above 0.
- **`interfaces_undecided_deps` above 0** — an external dependency naming neither a surface nor a
  reason. That is a decision nobody made, not a decision to exclude.
- **`interfaces_without_kind` equal to `interfaces`** — the rows were written and their SHAPE was
  not, so no step sent anyone to the field even though the row it sits on was authored. This one is
  worth reading closely: the field shipped WITHOUT a rebuild to prove the method text on, so the
  first build to author a kind is the first evidence that the instruction reads correctly. A count
  BETWEEN 0 and the total is the more interesting reading — some rows got one and some did not,
  which is a lead who stopped rather than a lead nobody sent.

**Then generalise the question**, because interfaces is only the instance that was caught: for each
section the method documents, did this build write it? A section documented but never SEQUENCED is a
section no build writes, and the failure is silent by construction. `method.md`'s build order is the
list to read it against.

### Step 1b — The map's own contradictions

Step 1 runs the gates. It does not read the MAP, and the gates cannot see a map that is internally
consistent by their rules and wrong on its face. This is not a minor lane: on the 2026-08-13 coworker
retro the finding ranked most consequential of all came from reading the audit's worklist builder
against the map, and three more came from reading the shipped map directly. Every one of them passed
`validate` and `audit` cleanly.

Four checks, all cheap, all deterministic, each one productive on that run:

1. **Re-derive every number the `grounding.note` states.** It is free prose in a permanent record and
   nothing checks it. One shipped note gave two of its eight per-theme counts wrong and stated a
   superseded total its own fields contradicted, because the prose was written against an earlier
   pass and re-pasted.
2. **Match each `finalize` advisory to a record in the map's extras. Run it with `--no-write`.**
   `finalize` OVERWRITES `.coyomap/finalize-report.{json,md}` on every run, so a report-only reader
   that runs it plainly destroys the record of the build it came to read — the retro replaces the
   build's own disposition with its own. `--no-write` prints the same report and leaves the files
   alone. `finalize` says in its own
   output that each advisory is either fixed or recorded; it does not check it. Nine had been waved
   through, and the transcript could not show it because every read of the list had been filtered.
   Pass `--lead-transcript <the build's session .jsonl>` too: without it the access-baseline leg
   looks for the RETRO's own session and cannot say which excused paths the lead never opened.
3. **Check each use case's declared `actors` against the actor of its own flow's first step**, and
   its name against its flow's title. A late rewrite left two use cases declaring one actor while
   their flows started with another, and one carrying its pre-rename flow title.
4. **Count the vocabulary the map minted against the seeds it was offered** — entry-point kinds,
   bucket names. One concept shipped under two kinds, 139 rows against 15, because one brief spelled
   out the seeded name and the others did not.

More generally: where a tool writes a number into the map and a *human sentence* beside it, check the
sentence against the number. That pairing is where this class lives.

---

## Step 2 — Process signals (deterministic, free, no model)

What the RUN did, as opposed to what it produced.

```
coyomap-eval process <transcript> --map .coyomap/project-map.json \
    --out .coyomap-eval/retro/<ts>/process.json
coyomap-eval transcript <transcript> --stats
```

**`--map` is not optional here.** Without it, assertion 6 falls back to transcript inference and
assertions 23 and 24 report `n/a` — three of the scorecard's lines quietly stop measuring, and `n/a`
reads as "no opportunity" rather than "you did not pass the map". This command line omitted it, and
the retro that found the omission had to re-run the whole scorecard.

If the previous transcript exists:

```
coyomap-eval process <prev-transcript> --map <archive>/project-map.json \
    --out .../prev-process.json
coyomap-eval process --diff .../prev-process.json .../process.json
```

Pass each transcript the map IT produced — the archived one for the previous run — or the diff
compares a scorecard that could read the map against one that could not, and three assertions move
for that reason alone.

### What it cost

```
coyomap-eval cost <transcript> --map .coyomap/project-map.json
coyomap-eval cost <prev-transcript> --map <archive>/project-map.json
```

Wall time, tokens, and both PER ROW of map produced, plus the straggler waste in each fan-out.

**PROPOSE this build's line for the Cost log in `backlog.md`, written out ready to paste** —
the report-only rule covers the backlog, and this step used to say "append", which contradicted it
twice over (the opening rule and Step 6's). The durability decision of 2026-08-27 stands: the
backlog is the home for spend, because reports are git-ignored and evaporate — so put the row in
the report as a finished line and ask for it in Step 6 with the other proposals. One row: date,
project, rows, active minutes, $ total, $ per 100 rows, and the per-role split. The log is what makes any
future "did this method change pay?" answerable without re-running `cost` on an old transcript.

**Compare per row, never per build.** Absolute minutes and dollars track how big the map got: over
four consecutive mcpolis builds the map grew 1,195 → 1,564 rows while the method changed under it,
so the build that was *cheapest per unit of work* read as the slowest and most expensive one. Cost
per row and seconds per row are the comparable numbers; a rise in either is the signal.

`--map` also prints the grounding counts beside the spend, and they are read together — a change
that halves the bill and doubles the refutation rate is not an improvement. If the session did
anything before or after the build (an archive step, questions once the map landed), bound it with
`--from-turn` / `--to-turn`, or time and tokens describe different stretches.

**Bound it even when the session looks finished, because the retro takes an hour and the build
window is still open.** `retro-precheck` clears you when the build session has been idle for 180
seconds; it cannot promise the operator will not come back to that window while you read. On the
2026-08-14 mcpolis retro they did: the transcript went 449 turns / 3.0 MB at the start to 491 turns
/ 3.4 MB by the time the findings were written, and an unbounded `cost` re-run then covered 42 turns
of unrelated scratch work. Turn INDICES are stable — records only ever append — so findings keep
their turn numbers and nothing has to be redone. Note the last build turn once (the `finalize` or
commit turn), pass `--to-turn` on every `cost` and `process` run, and say in the report which
snapshot the numbers describe.

**Note the transcript's turn count now** (`coyomap-eval transcript <t> --stats`) so Step 6 can tell
whether it grew while you read.

The assertions and what each audits are in
`COYOMAP_HOME/eval/fixtures/trapdoor/L3-DESIGN.md` — **all of them, so check the doc against
`coyomap-eval process` output rather than against any count written here.** This file said "the ten
assertions" while the scorecard ran fifteen, and the six the doc did not cover were three of the
four a live build scored zero on; the retro had to read the source to learn what they meant. Then it
happened AGAIN, in the same file, two paragraphs later — the report template below still said "the
ten L3 assertions" while twenty-two ran. Never write the count here; say "every assertion the
scorecard prints". (`eval/tests/test_process_scorecard.py` now fails when L3-DESIGN.md is missing
one, which is the half of this that a doc sentence cannot enforce.)

**Read the scores with their notes** — several carry a caveat that changes their meaning
(assertion 9 says so when the final validate view was narrowed by a grep), and `n/a` means the run
held no opportunity of that kind, which is not the same as a miss.

### Then audit the scorecard itself

**Every `n/a` and every zero is a hypothesis until you have settled which of three things it is.**
Work the triage in order; it is cheap and it is where the biggest findings of the last two retros
came from.

1. **Was `--map` passed?** Assertions 6, 23 and 24 go `n/a` without it. That is your own omission,
   not the build's.
2. **Does the assertion measure a COMMAND?** Then cross-check `coyomap-eval transcript --commands`.
   An assertion whose note says a command "never ran" against an index listing four runs of it is a
   detector bug.
3. **Otherwise, read the assertion's source in `process_scorecard.py`.** Several score turn
   structure, Agent-prompt text or the map — 3, 10, 16, 22 and 31 among them, and the map-only ones
   take no turns at all. No command index can settle those, and they are not rare — 3 and 31 were
   both among the headline lines of the last coworker retro.

The scorecard reads shell text with regexes over the lead's transcript. It is the most fragile thing
you will quote and the most trusted, because it prints numbers.

**When a detector looks wrong, patch it in memory and re-score — do not argue from a code read.**
That turns "this regex looks wrong" into an exact list of which lines move, on real data, changing
nothing on disk:

```python
import sys; sys.path.insert(0, "COYOMAP_HOME/eval/tools")
from coyomap_eval import process_scorecard as P
P._COYOMAP_SUBCOMMANDS = P._COYOMAP_SUBCOMMANDS | {"grounding"}     # the suspect override
for t, m in ((cur_transcript, cur_map), (prev_transcript, prev_map)):
    print(P.score_transcript(t, map_path=m, to_turn=LAST_BUILD_TURN))
```

**Pass `map_path` and `to_turn` on both sides**, for the same reasons the CLI runs did — a bare
`score_transcript(t)` re-scores without the map (three lines silently stop measuring) and over the
post-build turns you were told to exclude.

This is worth doing because it has paid twice. On the 2026-08-13 coworker retro it found two detector
bugs — an alias-blind subcommand list and a quoted-string scanner that ate whole invocations —
between them mis-measuring nine of the twenty-two SCORED lines on BOTH the build and its baseline
(eleven of the twenty-eight printed, counting two that printed `n/a`), changing three of the diff's
directions and inverting one outright. **Both are fixed** (`_COYOMAP_SUBCOMMANDS`, `_MULTILINE_QUOTE`);
they are cited here as the shape to look for, not as live bugs.


---

## Step 3 — The friction read (this is the part no tool does)

Steps 1 and 2 count the failures somebody already named. This step looks for the ones nobody has,
and it is the reason this skill exists.

**Slice first, then delegate.** The transcript is 300–500 turns and cannot be read whole. Get the
index and the fan-out map:

```
coyomap-eval transcript <transcript> --stats
coyomap-eval transcript <transcript> --commands         # every coyomap subcommand, with turn numbers
coyomap-eval transcript <transcript>                    # one line per tool call, with turn numbers
```

**Use `--commands` before concluding a command "never ran".** The one-line index truncates at 100
characters, so a subcommand chained behind `;` or `&&` is invisible in it. A retrospective read the
index, concluded `grounding write` never ran, and published that about a build which ran it at turn
489 behind an `assemble`; the finding had to be withdrawn. `--commands` reads the full command text.

Cut it into phases at the fan-out boundaries the stats print — typically: **setup + behavioral
draft**, **pre-index + harvest**, **synthesis**, **trace**, **gates (validate/audit/balance)**,
**Phase-4 grounding**, **finalize + commit**. Give each phase to one fresh-context sub-agent with
its exact turn range:

```
coyomap-eval transcript <transcript> --from <lo> --to <hi> --full
```

Hand every sub-agent the same brief: **the evidence classes below**, the requirement that each
finding carry a **turn number**, and the instruction to return findings only — no fixes, no prose
essay. Tell each one it is reading a slice, so "I did not see X" means "not in my range", never
"the build skipped X".

**Tell them not to time a fan-out off the raw JSONL.** A sub-agent that goes looking at the file
directly will find one assistant record per `tool_use` block, each stamped with the time that block
*executed* — so a single message that launched fourteen agents looks like fourteen separate turns
two minutes apart. Three sub-agents on one run independently reported "the fan-out was emitted as N
separate turns, violating the one-message rule", and all three were wrong: the fourteen records
shared one `message.id`. The transcript reader groups by that id on purpose (`transcript.py`, "A
JSONL record is NOT a turn"), and assertion 3 already measures this correctly. Put it in the brief:
**turn boundaries and turn counts come only from `coyomap-eval transcript`; agent wall times come
only from the per-agent files, which slice readers do not have; never mix the two.** A timestamp
spread inside one printed turn is streaming, not round trips.

### The evidence classes to hunt

Each one has been observed in a real build. Name them in the prompt: a vague "find problems"
returns vague findings.

1. **Hand-written what a tool produces.** A `python3 - <<'PY'` block doing something a `coyomap`
   subcommand already does. The headline case: `coyomap reconcile` ran zero times across eight
   builds while every build hand-wrote the file it generates.
2. **A tool that failed, and a workaround instead of a fix.** A command that errored and was never
   retried, or was replaced by a manual approach. Look for the SECOND attempt: what changed
   between the failing call and the working one usually names the bug.
3. **A flag accepted and ignored.** The output does not match what the flags asked for.
4. **Repeated lint / validate rounds on the same thing.** A fragment bouncing three times means a
   rule was not stated clearly enough in the prompt that produced it.
5. **A prescribed step skipped.** The method says do X; the transcript never does X. Check against
   `COYOMAP_HOME/method.md`, not memory.
6. **A doc that misled.** The agent read a doc and then did the wrong thing, or had to ask a
   question the doc should have answered.
7. **An advisory neither fixed nor recorded.** The "waved through" failure the method names.
8. **Wasted turns.** Polling a directory, re-deriving something already computed, re-reading a file
   it had already read.
9. **A straggler in a fan-out.** One agent taking far longer than its siblings stalls the whole
   barrier. **Name which agent; do not time it** — you are reading the lead's transcript, where
   asynchronous dispatch makes every agent look like it returned in about two seconds. Timing is the
   lead's job, after the slices.
10. **Anything surprising.** The classes above are what was found LAST time. The valuable finding
    is the one not on this list — say so explicitly when you see it.

### After the slices: read the agents themselves

The slice readers cover the lead's turns and cannot see inside a sub-agent. Send a second, small wave
at the per-agent files from Step 0. You do not need them all.

**Start from the fan-out table `coyomap-eval cost` already printed** in Step 2 — it has slowest,
median and straggler waste per batch. What it does not give you is *which* agent was slowest, because
the batch rows carry no names. That is the only reason to compute a duration by hand: open
`<session>/subagents/` and take first-to-last record of each `agent-*.jsonl` to put a name to the
outlier.

Two things that span does NOT tell you. A dispatch the harness rejected has **no file at all** — one
build sent 68 and 65 ran — so a re-sent agent's lateness is invisible here and must come from the
lead's turn numbers. And a file span measures the agent's WORK, not its contribution to the barrier:
the batch that held one fan-out open for four minutes had only 2.3 of them in its own file, the rest
being the delay before it was re-sent. Use the span to name the agent; use the lead's transcript to
explain the barrier.

Read, at minimum:

- **the slowest one or two agents in each fan-out**, identified as above;
- **every agent the lead's transcript shows being corrected** — a fragment that bounced through
  repeated lint rounds, a malformed output file, a brief a later turn had to rewrite. The slice
  readers hand you this list; do not wait for the analysis to name it;
- **any agent that finished far faster than its share of the work would allow.** One settled 40
  claims in 95 seconds; that was not diligence.

What to look for there that the lead's transcript cannot show: whether the agent opened the files its
output claims it read; whether it wrote a *program* to produce its answer instead of producing the
answer; whether it narrowed its own self-check (class 4 — one agent's `head -40` cut the verdict line
off a `lint-fragment` run that had already passed, so it iterated twice more); and what it did with
the minutes it spent.

### What a finding must carry

- **turn number(s)** — so the user can go and look;
- **what happened**, in one or two sentences;
- **the class** (one of the above, or "new");
- **`severity`** — `HIGH | MED | LOW`. **What the defect costs the MAP if nobody fixes it.** This is
  the only one of the three tags that describes the BUG rather than the fix. HIGH: the map ships
  something false or unverified, or a defect of that kind can reach a shipped map unnoticed. MED:
  the map is not wrong, but a signal was lost, work was redone, or a measurement that future
  decisions rest on is wrong. LOW: friction, cost or hygiene, and the map is unaffected either way;
- **`fix_class`** — `HARD | SOFT | HARD / SOFT`. **Whether there is one right answer.** HARD: the
  defect is deterministic and the fix is exact, a machine can tell whether it landed, and a
  regression test can hold it. SOFT: the fix is a judgement — a threshold, a wording, a prompt, a
  policy — that two competent people would implement differently and that can over- or under-fire.
  Split rows are common and honest: HARD to detect, SOFT to prevent;
- **`risk`** — `LOW | MEDIUM | HIGH`. **What applying the fix could break**, never what leaving the
  bug in place costs. **The gate for LOW is testability: a fix is LOW only when a test in the
  coyomap suite can hold it** — the test fails before the change, passes after, fails again on a
  revert, and what it asserts is the WHOLE of the fix. **Name that test file on every LOW row**, or
  the claim is unfalsifiable. MEDIUM: no test can hold the whole fix, OR the change alters what
  passes and fails, OR something downstream may already read the old shape — a method sentence
  stating a POLICY the agent must then apply by judgement lands here, because a test can assert the
  sentence exists but the sentence is not the fix. HIGH: it can stop a build, or it materially
  changes cost or an output format others parse;
- **where the fix belongs**: `tool` / `method` / `both` / `neither — agent judgement`;
- **confidence**: certain (the transcript shows it plainly) vs likely (inferred);
- **verification**: `re-ran it myself` or `slice reader's word`. One word, on every finding, written
  when the finding is recorded — not reconstructed later from memory across a 40-turn
  reconciliation. This field IS the list Step 5 splits on;
- **a probe** — one runnable check whose output says whether the behaviour still occurs, returning
  a NUMBER wherever a number is possible. This is what makes the next retro's Step 0b affordable: it
  turns "is this still true?" into one command instead of a re-read of every past report. A finding
  whose behaviour no command can observe carries `behaviour_probe: null` and is reported as
  `unverifiable`, never quietly dropped. About one finding in five is of that kind — a briefing not
  shown, a timing habit — and saying so is the honest result;
- **both halves of every ratio, and where each came from.** "Roughly ten of 67" was exactly ten of
  63 — the 67 mixed two different record types under one heading. One run reported the same
  refutation rate as 0.81% and 0.73% in different places because one used challenged claims as the
  denominator and the other used verdict rows, which differ when a batch is voted on more than once.
  Write `6 of 743 challenged claims` or `6 of 823 verdict rows`, never `0.8%`.

A finding without a turn number is not a finding. Drop it.

**A number from your own throwaway script is a draft until a second signal agrees with it.** This
is not a general caution, it is the most common way a retro publishes something false: three of one
report's own figures were wrong, and each looked exactly as solid as the figures that held. A
set difference over paths said three files were "never opened" when every one had been read,
because the brief named `backend/src/…/settings.py` and the command ran `cat -n …/settings.py` —
**normalise before differencing, and never read an empty intersection as absence.** A pipe count
said 4 of 23 because the display truncated at 150 characters and hid four more. A per-agent
read count did not reproduce at all. Cross-check any hand-rolled per-agent number against a second
signal, and prefer `coyomap-eval transcript` to a heredoc wherever it can answer — the tool exists
and every wrong number above came from not using it.

**A trend claim needs the whole ordered list, not its two ends.** This is the most common way a wrong
finding gets published, because a clean correlation across two extremes feels exactly like the
"anything surprising" class 10 asks for. Every refuted finding on the 2026-08-13 coworker retro had
the shape *the two X are the two Y*, and each collapsed once the middle rows existed: six of fourteen
agents wrote generator scripts, including the fastest; the "anti-correlation" between dispatch order
and duration was a rank correlation of +0.16. Before writing one: print all N rows — for per-agent
numbers, first-to-last record of each `agent-*.jsonl` — look at the middle, and check the obvious
confound, which for per-unit costs is fixed startup overhead on small units.

---

## Step 4 — Reconcile the findings (lead, not delegated)

The sub-agents return overlapping and sometimes contradictory lists. This step is yours.

- **Dedupe** — the same defect seen from two phases is one finding.
- **Verify the cheap ones against the code.** A claimed tool bug can usually be confirmed in one
  command: run it. A confirmed bug outranks ten plausible ones.
- **Separate a tool bug from a method gap from an agent judgement call.** Only the first two are
  actionable here; the third is worth recording but is not a defect.
- **Drop what a sub-agent could not have known.** "It did not run X" from an agent holding turns
  40–90 is not evidence about the whole build. Check the full index before accepting it.
- **Rank by what it costs.** A defect that silently produces a wrong map outranks one that wastes
  turns.

Keep, as you go, a list of **which findings you personally re-ran** and which you are taking on a
slice reader's word. Step 5 needs it and the report publishes it.

---

## Step 5 — Send skeptics at your own findings

**Do to this report what the method tells a build to do to its map.** Phase 4 of `method.md` exists
because an author cannot audit their own claims; the lead who just accepted a list of findings is the
worst possible reviewer of it. Step 4 above is dedupe plus spot-check by that same lead. It is not
enough, and the evidence is direct: on the 2026-08-13 coworker retro an adversarial pass moved
**eight** claims in a finished report — five refuted outright, one withdrawn, one causal conclusion
demoted to a hypothesis, one arithmetic error. Every one would have shipped.

Take the list Step 4 told you to keep. **Everything you did not re-run yourself goes to a refuter.**

**How to run it:**

- **Two refuters, split by the Step 3 phase list** — one takes the earlier phases, one the later.
  More than two and they start duplicating each other's recomputation.
- **While they run**, write the Step 6 sections that do not depend on findings: `What this covers`,
  `Product signals`, `Process signals`, `Not assessed`.
- **One round only.** A refuter's corrections are yours to reconcile, not to send out again — that
  recursion has no natural floor. If a verdict is still unsettled after your own check, it is
  published as unverifiable, not sent to a third agent.
- **When two refuters disagree**, recompute from disk yourself. If that does not settle it, publish
  it as unverifiable and say what would.
- **Point them at what the second wave already read.** Step 3's per-agent pass covered the stragglers
  and the fast finishers; name those agents so the refuters spend their reads elsewhere.

The brief that works:

- **"Your job is to REFUTE these claims, not confirm them. Assume each is wrong until the evidence
  forces you to accept it. A refuted claim is a more valuable result than a confirmed one."** Say it
  first and say it plainly — a reviewer asked to "check" a list confirms it.
- Give each claim **as stated**, with its turn numbers and where the underlying artifact lives.
- Point at the files, hard: the map, `.coyomap/verify/`, the build scratchpad, and the per-agent
  transcripts. **"Prefer computing from files on disk over trusting the claim."** The refuter that
  recomputed per-batch counts from the claims files confirmed the headline finding to the digit; the
  one that read the agent transcripts broke three.
- Demand a four-way verdict, not a yes/no: **refuted** (wrong — give the correct value) ·
  **overstated** (directionally right, magnitude or wording wrong) · **unverifiable** (the artifacts
  cannot settle it) · **confirmed**. Most real outcomes are the middle two, and a yes/no forces them
  into the wrong bucket.
- For any claim that is *causal* rather than arithmetic, say so and **tell the refuter to attack the
  inference, not the numbers**, and to name what evidence would settle it. That is what turned "the
  low refutation rate means weaker skeptics" into a hypothesis with two cheap experiments attached,
  which is what it always was.
- Tell them to change nothing.

Then reconcile every verdict — fix or reject, each with a reason. **A refuter is not automatically
right.** One reported the previous map absent and a baseline unverifiable; it had searched the
coyomap clone instead of the archive under the project, and the finding stood. Check before you
retract.

Expect this to change the report substantially. If nothing comes back overturned, suspect the brief
asked for confirmation.

---

## Step 5b — Send one reader at the FINISHED report

Step 5 refutes individual CLAIMS while the report is still being drafted. This is a different job
and it comes after the report is written: **one fresh-context agent, briefed to refute the REPORT
as an artifact.** Skipping it because Step 5 already ran is the mistake — on the run this step
comes from, Step 5 overturned six claims and Step 5b then found the single most consequential
defect of the whole retro, which no claim-level refuter could have seen because nobody had claimed
it.

Brief it to attack six things, in this order:

1. **A finding that is factually wrong.** Hand it the numbers that carry the most weight and tell
   it to recompute each from disk.
2. **A finding whose numbers are right and whose CAUSE is wrong.** Correlation read as mechanism.
3. **A proposal that does not follow from its finding**, or that would break something else.
4. **A claim presented as verified that was not.** Give it the `Verification status` split and tell
   it to audit that split specifically — anything asserted with more confidence than the split
   supports, and anything the split calls "re-ran it myself" that does not reproduce.
5. **A ranking that is wrong.** Argue for a different order if the evidence supports one.
6. **What the retro MISSED.** The highest-value thing it can return, and the reason this step
   exists. Name a defect class nobody looked for, a file nobody opened, a question nobody asked.

Expect it to hurt. On its first run it refuted three of the report's own numbers — two were wrong
counts from the lead's own scripts and one did not reproduce at all — killed the report's
top-ranked proposal by quoting the method line that already decided the opposite, and found two
refuted claims sitting in the shipped map that the gate had printed and a pipe had discarded.

Reconcile every verdict yourself, and **re-verify the consequential ones against the files before
accepting them** — a report-level reader is not automatically right either. Then say in
`Verification status` what it overturned, including anything of your own it corrected.

## Step 6 — Report

Write `.coyomap-eval/retro/<ts>/report.md` and summarise it in chat. Structure:

```
# Retrospective — <project> build of <built_at> (session <id>)

## What this covers
the map, the transcript, and what could NOT be assessed

## Carried forward
landed and worse FIRST · landed but ineffective · open and worsening · open, reproduced
(each with its `retros_open` count) · fixed and proven · accepted, not done yet ·
unproven this build · probe broken · rejected (once, then quiet)

## Retro-checks
the commit range checked (`old..new` tool commits) · each pending check file with its per-item
verdicts (confirmed with numbers / failed -> finding # / no opportunity) · retirement commits
proposed · "no check files pending" stated explicitly when the range adds none

## Product signals
blocking problems · advisories surviving · components vs E · grounding coverage
· deltas vs the previous map

## Process signals
every L3 assertion the scorecard printed, with the diff against the previous build

## Findings
FIRST a `Findings at a glance` table — one row per finding, columns
`# | finding | severity | fix class | risk | the fix in one line` — then the findings themselves,
ranked, each with turn number, class, where the fix belongs, confidence, verification and probe

## Proposals
tool changes · method changes · new L3 assertions worth adding
· whether the LAST retro's proposals landed
· each tagged with the severity of what it fixes, its own fix class and its own risk

## Verification status
what you re-ran yourself · what a refuter confirmed · what it overturned
· what came back unverifiable, and what would settle it
· where a refuter was wrong · what nobody checked

## Not assessed
say it plainly — and **state the per-agent read COVERAGE as a fraction**: "read 11 of 61 agent
transcripts — the 5 rule workers and 6 skeptics; no harvest agent and neither surviving trace
agent". Step 3 says you do not need them all, which is true and is exactly why the number must be
printed: a report that names the agents it opened and not the ones it skipped reads as a complete
per-agent pass. On the run this rule comes from, the two trace agents nobody opened held half the
narrowed self-checks the report went on to under-count
```

**Rules for the report.**

- **Numbers with evidence, never verdicts.** No PASS/FAIL. `observed / of` and turn numbers.
- **Say what you could not assess.** A retro that only lists what it found reads as complete when
  it is not. Semantic map quality is NOT assessed here — that is `/coyomap-eval`. Say so.
  **And propose a backlog line for every item in `Not assessed` that is a QUESTION about this build,
  not a permanent limit.** Naming the owning tool is not the same as handing the question over: this
  report lives in `.coyomap-eval/`, which is git-ignored scratch, so a deferral that stops here dies
  with it. One retro correctly parked "same code, 50 access rules became 44 — merged or lost?" as the
  quality eval's job; it survived only because somebody read the report before the folder was
  cleaned, and the answer turned out to be neither (the two maps shared 25 % of their enforcement
  lines). Distinguish the two kinds and only propose the first: a QUESTION has an answer somebody
  could go and get ("does X still hold on this map?"), while a permanent limit is just this
  instrument's shape ("a single build proves nothing about a trend") and belongs in the report alone.
- **`Carried forward` leads the report, and `landed and worse` leads that section.** A fix that
  shipped and made things worse is the most expensive outcome a method change can have, and it is
  invisible to every other instrument here. A new finding can wait one section.
- **A carried row prints both halves of its comparison and their units.** Write
  `record invocations 40 -> 0`, never "record usage regressed". The ratio rule below applies to
  every carried number too.
- **Tag every finding and every proposal with all three, and read them as a PAIR.** Severity and
  risk do not correlate, and that is what makes the table decide anything. **The quadrant that sets
  the order is HIGH severity at LOW risk**: it lets a wrong map ship, and a named test can hold the
  fix. On the run this rule came from, the two biggest map-quality defects were also two of the
  cheapest, safest fixes, and a ranked list of prose had buried both. Say the counts out loud —
  "of the 24 rows, 12 HARD, 9 SOFT, 3 split; by risk 10 LOW, 11 MED, 3 HIGH" — because a reader who
  cannot see the shape of the list will read it top to bottom and stop early.
- **A PROPOSAL IS NEVER A MAP REPAIR.** The taxonomy above is tools, method, assertions, and the
  previous proposals' status. Nothing else. A defect found in the map is EVIDENCE about the method
  that produced it; repairing it belongs to a build or a direct map change, and a retro that
  proposes the edit has quietly changed job. The pull towards writing one is strongest exactly when
  the defect is small and concrete — one retro drafted two such rows, for two refuted claims and
  two stale numbers, precisely because each was a two-line fix. Report the defect, name the tool or
  method change that would have caught it, and stop there.
- **A single build proves nothing about a trend.** Where a number moved against the previous build,
  say it moved; do not say the method improved. Two data points are two data points.
- **A proposal lands as a TOOL CHANGE first, prose last.** For each proposal, answer in this order:
  can a tool refuse the behaviour, do the step itself, or lint it? Else, can a check count it? Only
  when neither is possible does the fix become a method sentence — and a prose-only proposal SAYS
  SO ("no tool can carry this, because ...") and names the retro that should re-read it. WHY the
  order is fixed: `method.md` records at least four times that a rule "stated as prose was read as
  advice and skipped", while every rule that moved into a tool stopped recurring; each prose fix
  also grows the file every build re-reads. A proposal written as prose when a verb could carry it
  is the expensive kind of cheap.
- **Propose, do not apply.** End by asking which proposals the user wants implemented — and then
  **write the answer into `findings.json` as each row's `decision`.** That is the one input the
  carry-forward needs and the one the retro cannot compute: without it every row stays `proposed`,
  Step 0b can never print `landed but ineffective`, and the next retro re-proposes everything the
  operator already refused. Record a rejection's REASON on the row too, so it is answered once and
  goes quiet rather than being re-argued each run. An operator who does not answer leaves the rows
  `proposed`, which is honest and is not the same as a `no`.
- **Re-check the turn count before you write.** Compare `coyomap-eval transcript <t> --stats` against
  the count you noted in Step 2. If it grew, the operator came back to the build window while you
  read, and every UNBOUNDED number you quoted has drifted — one run went 250.5m to 799.7m wall for
  the same build. `retro-precheck` will not warn you; it passes correctly, because those writes are
  the operator's and not another session mid-build. Requote from the `--to-turn` bounded runs and
  say which snapshot the numbers describe.
- **Publish how each finding was checked, not just what it says.** That is the `Verification status`
  block, and it is not optional: a report whose re-run findings and whose taken-on-trust findings are
  formatted identically reads as uniformly solid, and its weakest claim gets quoted as confidently as
  its strongest. Name what a refuter overturned — a table of `claim as drafted` → `outcome` is
  enough — and name where a refuter was itself wrong. Say plainly what nobody verified. On the run
  this section was written from, eight claims moved and one was withdrawn; a reader of the first
  draft had no way to tell those eight from the rest.

### Feed it back

Any finding that is a REPEATABLE process defect is a candidate NEW L3 assertion — the
scorecard exists to turn a one-off discovery into a number that gets watched. Name those
explicitly in the proposals section; that loop is how the retro stops being a one-off read.

**Say what each proposed assertion would have to read.** The scorecard is a lead-transcript
instrument, and much of what a retro finds does not live there — an assertion that needs the map or
a per-agent transcript is a different piece of work from one that greps the lead's commands, and one
nobody can implement is a proposal that quietly dies. Tag each with its source.

**Report what the previous proposals did, and update the backlog.** You read
`COYOMAP_HOME/eval/retro/backlog.md` in Step 0; say in `Proposals` which items landed, which did not,
and which were overtaken by a fix that arrived in between. Then say what the backlog should become —
new items to add, items to move to Landed, status lines that are now wrong. **Proposing that edit is
the deliverable; making it is not** — the report-only rule covers the backlog too.
