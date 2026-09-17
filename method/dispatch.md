# Dispatch — what to do when coyomap is invoked

The user invoked coyomap on a repo. Decide the mode, then read the listed doc(s) **fully** and
follow them — don't restate them or work from memory. The tooling is the `coyomap` CLI, installed
into this clone's venv (`.venv/bin/coyomap`; source under `tools/coyomap/`).
The clone's `internal/` folder is design rationale, not the method — ignore it.

**Path reminder:** every `method.md` / `method/...` / template / `.venv/bin/coyomap` path below is
under the coyomap clone (`COYOMAP_HOME` from the skill), **not** the repo you are mapping (your cwd).
Read/run them with that absolute prefix. Only `.coyomap/...` paths are in the analyzed repo.

**The shell here is not bash, and every difference is silent, at exit 0.** `set -e` does nothing —
a loop of failing commands runs every iteration and the turn still succeeds — and an unquoted
`$VAR` holding a list does not word-split, so `for f in $LIST` runs ONCE on the whole string. Read
each command's own exit code, never let a `&&` chain stand in for a guard, and print one line per
item in a loop. One build appended a T5 addendum to a brief that 8 failed fill calls never wrote;
three wrote 35 `timings record` calls with empty arguments and no timings file was ever written.

## Step 0 — brief the user BEFORE doing anything else

The first thing the user sees must be what coyomap is about to read, and what the map will claim
about the code. Run this immediately — before choosing a mode, before reading the repo (an ABSOLUTE
path: your cwd is the analyzed repo, which has no `.venv/`):

```
<COYOMAP_HOME>/.venv/bin/coyomap scope --repo <repo>
```

**Show its output verbatim, as your first message.** Do not summarise, re-word or "the highlights
are" it. **First message means FIRST: before the first tool call, not after the setup turns.** One
build ran `scope` at turn 6 and emitted exactly two user-facing messages in its first seventy
turns, neither of them the briefing and neither naming the mode; the operator learned what the map
had covered only when the map was finished. The briefing is cheap to print and impossible to
reconstruct later, because by then the reader has the map and no reason to doubt its scope. It states the rule that decides the file set (git, minus `.gitignore`, minus coyomap's
built-in exclusions — `node_modules/`, `dist/`, build output, lock files — minus
`.coyomap/.ignore`), how many files that came to, what each ignore pattern removed — naming any
pattern that removed nothing — and what the commit pin will mean. Paraphrase it and the narrowing
turns into silence, after which the map reads complete because the evidence of what it skipped never
reached the person reading it. The only paths it lists are the uncommitted ones; the in-scope and
excluded sets are reported as COUNTS and PATTERNS, so if the user asks which files, answer then,
from the repo.

**Order.** Run the briefing now, then go on to Steps 1–2 and decide the mode. The pin branch below
depends on the mode, so come back to it once you know — it is written here because it belongs to
the briefing, not because it happens before the mode is known.

Then, with the mode decided, act on what the briefing said about the pin:

- **Uncommitted code, and the mode is Build (or a rebuild)** → ask before starting the work, and say
  which mode you are in so the question has a reason. This is the same A/B choice `method.md`'s pin
  gate asks, moved from the END of the build to the front, where changing your mind is free:
  - **A (recommended)** — **the user** commits or stashes the code, then you re-run `coyomap scope`
    (show it again — it is the same briefing about a now-different tree) and continue. Never commit
    or stash the user's code yourself: it is their working tree and their commit message, and this
    step is a question, not a mandate.
  - **B** — continue as is. The pin is recorded `<sha>-dirty`, meaning "this map describes code that
    is not in any commit".

  Carry the answer forward: the pin gate in `method.md` **must not ask again**.
- **Uncommitted code, and the mode is Analyze** → say so and continue, do NOT ask. Analysis is
  designed to run on a dirty tree; that is the normal case, not a problem.
- **No uncommitted code** → nothing to ask.
- **No git repo at all** → nothing to ask, and nothing to add: the briefing already says that
  `.gitignore` cannot apply and that there is no commit to pin the map to.

**Announce the mode** you land on in Steps 1–2, whichever it is — a build that starts with no word
about what it decided is the thing Step 0 exists to prevent.

## Step 1 — did the user name a mode?

If the invocation explicitly names a mode — **`build`**, **`update`**, **`analyze`**, or
**`accept`** (the verbs the README teaches, e.g. `/coyomap update`) — do that mode directly: Build →
`method.md`; Update / Analyze / Accept → `method/change-impact.md` (update is the whole sequence,
analyze its first half — the log written, the map untouched — and accept its second half on a log
that exists). (Bare `/coyomap` names nothing, so fall through to Step 2.)

A **request to see one thing in the map** ("show me the use case about rate limiting in the map",
"link to the component that sends invoices", "open the map on this rule") is a **Link**: no build,
no analysis, nothing written. Find the element in `.coyomap/project-map.json` (grep for the words the
user used; `coyomap dump --id <ID>` says what an id is), then run
`<COYOMAP_HOME>/.venv/bin/coyomap url <ID> --repo <repo>` and end the answer with the address it
prints — clickable, opening the running map on that element. `--context` gives the element's home
view with it lit instead of its own page. Never compose the address by hand: the part after `#` is
the viewer's own grammar, and the port belongs to whichever server is running.

A **plain-language request to change the map itself** ("move component X into subsystem Y", "rename
this subsystem", "split this component", "add a use case for…") is also a recognized input, even
without a verb — it is a **Direct map change** (Step 2, "Baseline exists", item 3), not Analyze. Do
not treat such a request as "nothing to analyze / baseline up to date".

## Step 2 — is there already a baseline?

Look **only at the working tree** of the analyzed repo for `.coyomap/project-map.json`. If the file
is not on disk, **there is no baseline — even if git history still has a committed copy.** A deleted
working-tree file is a deliberate signal to start from scratch. **Never restore, `git checkout`,
`git show`, or otherwise recover a deleted `.coyomap/` file from git; never treat a git-committed
copy as the baseline when the working-tree file is gone.** Fall through to Build below.

### No baseline → Build

Create it. Read `method.md` (+ `method/model.md`, `method/domain-cards.md`, and
`method/diagrams.md` — `method.md` cites it as the authority on Happy-Path rendering and the
leaf-only map, and it was missing from this list, so a whole build never opened it): agents return
structured rows and `coyomap assemble` writes the model + views.

**`method.md` is thousands of lines and cannot be read in one tool call.** A `cat` and a `sed -n
'1,400p'` both overflow the tool-result cap and spill into a persisted-output file that nobody then
opens; one build burned a turn finding that out. Read it in windows — `Read` with `offset`/`limit`,
**650 lines at a time**, no gaps — and do that FIRST rather than after two failed attempts.

**650, and why that number and not 300.** The cap is 25,000 tokens per tool result, and this file
runs about 2.88 bytes to the token, so the window that matters is BYTES, not lines. Measured on its
densest 900-line stretch: 27,738 tokens — over. Its densest 650-line stretch was 20,583 tokens, a
21% margin that survives the file growing. 300 lines costs more than twice the reads, and the extra
turns buy nothing: the earlier number was set after a 400-line `sed` failed, and 400 was never the
ceiling — it was just the first thing tried. **No line count for `method.md` is written here, on
purpose**: the one that used to be here said "~2,500" while the file had reached 3,290, and the
read count beside it was stale the same way. `wc -l` divided by 650 is how many windows it is. Do not raise
650 on a guess: the failure mode is a silent spill to a file nobody opens.

**When you archive, remember the archived map at the GATE.** `coyomap finalize --access-baseline
<archived-map.json>` adds one advisory leg: files that held ACCESS enforcement in that map and are
named by no access rule in the new one. It runs after the map is written, so it cannot contaminate
the rebuild, and before the commit, which is the last moment anybody looks. It is not a
contradiction of the rule below: the build is finished by then, and a claim that vanished between
two maps of unchanged code is invisible to every other gate — one pair held its access-rule COUNT at
21 → 21 while the file verifying an identity token's signature lost its claim outright.

A file that deliberately no longer holds an access rule is recordable as `<path>: <why>` under an
**"Access baseline exceptions"** extras heading, and `finalize` READS it — the path drops out of the
advisory on the next run. Record only a deliberate drop, after reading the file: this is the one
gate that sees an auth claim disappear between two maps of unchanged code. (The advisory used to
name `'access-baseline <path>: <why>'` under "Audit exceptions", whose keys are ids, not paths — so
one live build wrote twenty records that nothing could read and nothing ever read.)

**Archiving an existing map is `coyomap-eval archive <repo>`.** Say so before the rest of this
paragraph, because the rest is a prohibition and the command is the permitted action: a build asked
to archive first did it by hand — `mv .coyomap .coyomap-archive-<date>` — before the skill was even
loaded, which left ~59 files of the old map inside the harvest scope (2731 analysed against 2672
once it was filed properly), and then spent four turns discovering the command in `--help`. It files
the map under `.coyomap/dev-rebuilds/NNNN/`, which is excluded from the walk.

**Read the retro backlog's open experiments — this is the only place they reach a build.**
`COYOMAP_HOME/eval/retro/backlog.md` ends with "Open — questions a retro could not answer", and some
of those rows carry `owner: the next build`. Nothing put them in front of one. Question 3 was raised
on 2026-08-19 with its whole experiment written out — *"re-run ONE block's rule worker with a
`coyomap dump --members`-derived candidate list instead of the hand-curated one, and compare which
files earn sites. One extra agent on the next build"* — and the next build ran nine rule agents,
none of them that one, then a retrospective parked the same question a third time. Read the table,
run any row owned by the build (they are costed in agents, and so far always ONE), and say in the
final report what it returned. A question nobody can be assigned is a question nobody answers.
(This is a COYOMAP-DEVELOPER step: a user of coyomap has no backlog. Skip it when the file is absent.)

**Do not open a previous map while building.** Not the one git still has, and not one filed under
`.coyomap/dev-rebuilds/` (the coyomap author's own archive; a user of coyomap never has that
directory). A build that reads the map it is replacing is no longer independent of it: the new text
may even be right, but nobody can tell any more, and an eval comparing two maps of one repo reads
the agreement as convergence when it is copying. Archiving the old map (`coyomap-eval archive`) is
filing it, not consulting it, and stays fine. If a project genuinely needs a vocabulary to stay
stable across rebuilds, record it in the map (`Bucket vocabulary`) so the next build inherits it
from a DECLARATION rather than by reading the artifact. (L3 assertion 29 watches this.)

### Baseline exists → default to Analyze (never silently rebuild)

A rebuild regenerates the map from scratch and **overwrites the curated, reviewed baseline** — it
loses manual fixes and the pin history. So it is **never** the default. Read the baseline pin from
the model's `commit` / `committed` fields, then:

1. **Is there anything to analyze?** Compare the pin to the **current working tree** (so a later
   commit *and* uncommitted edits both count), ignoring coyomap's own files. The tree matches the pin
   only when there is no diff **and** no untracked file:

   ```
   git -C <repo> diff --quiet <pin> -- . ':(exclude).coyomap' \
     && [ -z "$(git -C <repo> ls-files --others --exclude-standard -- . ':(exclude).coyomap')" ]
   ```

   (Use the pin's bare sha; if the pin ends in `-dirty` it never matched a clean commit, so skip
   straight to Analyze.)

   - **Both true — current source == the pin** → the baseline is current. Tell the user
     `baseline is up to date @ commit <id> from <date>` and stop; do **not** produce an empty diff.
     (If only the committed `.coyomap/project-map.md` view is stale, just re-render it with
     `coyomap render … project-map.md` — that is a render, not a rebuild.)
   - **Otherwise — the source differs** (a later commit, uncommitted edits, or new files) →
     **Update**: read `method/change-impact.md` and follow it. Its step 0 refuses a dirty tree — an
     update names two commits — so uncommitted edits mean: tell the user, and stop until they
     commit or stash. A user who wants to read the log before it lands asks for **Analyze**, the
     first half of the same sequence.

2. **Accept** — when a log already exists (an earlier Analyze), read `method/change-impact.md`
   (steps 5–7).

3. **Direct map change** — the user asks, in plain language, to change the *map itself* (not driven
   by a code diff): "move component X into subsystem Y", "rename the API subsystem", "split this
   component in two", "create a subsystem for the reporting components", "add a use case for an admin
   resetting a password". This is **not** Analyze (there may be no code change to diff) — do it
   directly:
   - **Make the edit surgically to the model** (`.coyomap/project-map.json`) — the same field/array
     edits Accept applies (`method/change-impact.md`), never a rebuild.
   - **Stay grounded in the code** (the same rule as Build): a map describes what the code does, so
     reorganize / rename / re-drill what exists, but do not invent elements the code doesn't back — an
     "add a use case" only stands if there is real code and a traced flow behind it; otherwise say so
     and don't add it.
   - **Run the gates and commit**: the invariant below — **validate --check-sources → audit → render** — then commit
     the model + regenerated markdown view (a direct map change is a write like any other; the gates
     are not optional).

4. **Rebuild** — only when the user *explicitly* asks to regenerate from scratch. Warn that it
   **overwrites the existing baseline and discards its curation and pin history**, get confirmation,
   then Build as above.

## Invariant (every mode)

The map is the single source at the analyzed repo's `.coyomap/project-map.json`; the committed
`.coyomap/project-map.md` is a generated view of it (never hand-edited), and the interactive C4
diagram is served live by `coyomap serve` (not a committed file). After every write — **including a
Direct map change made at the user's request**, not only Build / Accept — the invariant is
**validate → audit → render**. Validate (`coyomap validate --check-sources`) checks schema +
semantics (and that the committed markdown view is fresh); audit (`coyomap audit`) is the adversarial
pass — it makes the narrative Happy Path and
the mechanism flows/edges refute each other. It blocks only on a hard contradiction (a forward/dangling
`why:` reference); read-before-create and actor-attribution are ADVISORY (lossy attribution — reconcile,
don't treat as fact), and it prints an L2 grounding worklist to disprove against the code with
fresh-context skeptics (see `method.md`); render (`coyomap render … project-map.md`) — the markdown
view is a rendering, never a second source, and the diagram is served on demand from the model.

**Going deeper stays in the one map.** When a part of the system needs finer detail than its current
altitude, refine it IN PLACE — nest subsystems/subdomains, or promote a leaf component into a subsystem
(see `method.md` "Drilling deeper"). The viewer drills these nested levels recursively. **Never write a
second map file** (a per-area `.coyomap/<area>/project-map.md` "child map"): a separate file is a
separate ID space, so cross-references can't resolve, bidirectional links and shared elements break, the
viewer can't drill across it, and Analyze/Accept/change-impact only ever track this one baseline. Child
maps are **not supported**.

## Waiting at a barrier (every fan-out, every phase)

This is here, in the file the skill points at, because the rules it governs otherwise live inside a
parallel-mode block that a serial build can read as inapplicable — and this file, every build reads.
It applies to **every** fan-out: harvest, trace, and the Phase-4 skeptics.

**The wait is a TEXT turn. Emit no tool call at all.**

- **Never** `sleep`, `until … sleep …`, or a keep-alive like `echo ok` — foreground or backgrounded.
  A no-op turn costs a full model round trip and yields the turn no better than ending on text.
- **Never** `ls` the fragment or verdicts directory. A not-ready file reads as an error and burns
  the turn. It is also unsafe: a half-written verdicts file tallies wrong, or parses as truncated
  JSON.
- **The agents' completion notifications ARE the barrier signal.** They arrive named and carrying
  the agent's result.
- If you genuinely must block on a condition, use the **`Monitor` tool with an until-condition** —
  and `Monitor`'s command must not itself be an `ls`/`sleep` poll. (`Monitor` is deferred: run
  `ToolSearch select:Monitor` once before the first call.) **One barrier means ONE `Monitor`.**

The measured cost of ignoring this has run to **32 % of a build's tool calls** — one poll every 7
seconds through a 9-minute barrier, with `Monitor` never called. **L3 assertion 10 is the
enforcement; this paragraph is the courtesy.**

**Dispatch the known-longest slice FIRST** — launch order is the only lever on when a barrier
closes. Where the slices are deliberately uniform (the Phase-4 skeptic batches are capped at the
same claim count) that lever does not exist — identical batches vary more than 2× with nothing to
sort on. There, **probe the straggler** with `SendMessage` after a couple of minutes of silence —
not with a late `ls` sweep, and not by waiting out the tail.
