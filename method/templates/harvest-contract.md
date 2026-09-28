# Harvest contract (Phase 1) — the copyable template

**Copy this file; do not retype it from prose.** Taken literally that was impossible — the body
below is a `>`-quoted skeleton full of «angle-bracket» slots, so it cannot be handed to an agent
as-is, and every build "copied" it by rewriting it. So the instruction is mechanical:

1. Take the quoted block below and strip the leading `> ` from every line.
2. Fill ONLY the «angle-bracket» slots — per agent, that is the file list, the background blurb,
   the **use cases the slice serves**, the component budget and the agent id; per build, the repo
   path and `COYOMAP_HOME`.
3. Change nothing else. If a rule reads wrong for this repo, fix it HERE, once, so the next build
   inherits the fix instead of re-deriving it.

**Every slot needs a word about what goes IN it**, since the agent half no longer explains itself.
`coyomap contract harvest --slots` prints these lines beside the empty values, so this list is what
a lead actually reads — it is not documentation of the template, it IS the skeleton's help text.

- **«SERVES»** — the UC / CAP / HP / R ids whose behavior runs through these files, one line each
  on what they need from this slice.
- **«EXPECTED_COMPONENTS»** — the slice's E from the pre-index `granularity.per_dir`.
- **«SLICE_KIND»** — what this slice IS, as a short phrase in the agent's first sentence ("HTTP
  routing and config parsing"). Free text, and a real value is a phrase, not a category word.
- **«FILES»** — the absolute paths this agent owns, as a list it can pass to `ls` and then read
  one by one. Directories are allowed; the agent is told to list one before reading it.
- **«BACKGROUND»** — what the lead already learned about this slice, handed down so the agent does
  not re-derive it: the product in a sentence, the frameworks, the one or two facts that shape it.

**The slot that keeps being left empty is «SERVES».** Structural slices exist to serve the
behavioral layer. The behavioral draft exists before this fan-out precisely so the slices can be cut
to it; a brief that names no use case is a brief cut from the file tree, and the harvest then comes
back with components carrying no backbone edge at all. Assertion 31 counts this.

Give every harvest agent the same skeleton — only the file list and the background blurb change per
agent. Reusing one contract is what makes each agent return the same row shapes with the same
verified/inferred discipline, which keeps the barrier synthesis clean.

**The template starts at the quoted block below.** Everything above it is instructions to you, the
lead; nothing above this line goes into an agent prompt.

> You are harvesting «SLICE_KIND» facts for a coyomap codebase map.
>
> **NEVER `cd` into the coyomap clone.** Address both repos by ABSOLUTE path, always. A `cd`
> persists for the rest of your session, so a later relative `.coyomap/...` path silently reads
> the TOOL's own map instead of this project's — a wrong answer that looks like a right one. On the
> 2026-09-02 build 8 of 75 agents did this 33 times, because the rule lived only in the lead's guide
> and no agent had read it.
>
> **This slice serves: «SERVES».** They are why the slice is cut this way. Where a
> file matters to one of them, that is the fact worth returning; where it matters to none, say so
> rather than padding the slice.
> Read these files completely, then produce ONLY the rows below — the only file you may write is
> your own fragment file (see the output rule below).
> **Do this work yourself — do NOT spawn your own sub-agents / delegate, and do NOT write a program
> that GENERATES your fragment.** Author the rows. Speed is not the argument — the fastest agent on
> a measured build used one. The cost is every lint round: patch-generator, regenerate, copy,
> re-lint instead of one edit. A sub-agent's output is silently dropped: an agent that delegates
> returns prose instead of a fragment, and the whole slice has to be re-harvested.
> **What the ban is and is not.** Banned: a script that PRODUCES rows — reading the code, deciding
> what a component is, emitting the JSON. Allowed: a small edit to a fragment you already authored
> by hand — a `sed`, a two-anchor `.replace()`, a `json.dump` that reformats. The line is whether
> the PROGRAM made the judgement or you did. The wording said "writes your fragment", which reads
> as banning both: 9 of 30 agents on one build used a program, and most were patching an authored
> draft rather than generating one. That is not the defect this rule names.
> You read the files and write the one fragment; no delegation.
>
> **Files:** «FILES». **List a directory first, then read each file** — a slice read from the
> file names alone returns components nobody opened.
> **Background:** «BACKGROUND» — what the main agent already learned about this slice, handed
> down so you don't re-derive it.
>
> **Expect roughly «EXPECTED_COMPONENTS» components for your
> slice** (one component ≈ one module-/folder-sized unit, ≤ ~10 source files / ~3 kLOC). If you come
> out far under, you are folding subsystem-shaped dirs into single components — make those
> subsystems and recurse into their units; far over, you are splitting module-sized units.
> **Give every component a `kind`**, one word for what kind of thing it is. Use a known word when
> one fits: `screen` (a page a person uses), `command` (the product's own command line, the commands
> a person or an agent types), `script` (a script a person runs by hand to operate the product),
> `api` (an entry the product's own screens or clients call), `logic` (does the work), `check`
> (decides whether something is allowed), `job` (runs without being asked: on a timer, or once each
> time the product starts), `instructions` (text an agent follows: a skill, a prompt, a method
> document), `store` (keeps records), `pipe` (passes calls on and DECIDES nothing: an API client, a
> request helper; adding a cookie, a header or a retry on the way is still a pipe), `wiring`
> (assembles and starts the product). **When none fits, mint a word and declare it** in your
> fragment's `component_kinds`, once: `{"word": "<the word>", "meaning": "<one sentence: what a
> component of this kind is>", "acts_as": "<the known word it is drawn as>"}`. Never mint a word for
> a thing a known word already names ("service" is `logic`). Another slice may mint the same word:
> the merge keeps one declaration, so say what the word MEANS, not what your component does.
> The name stays free: the kind is said here, once, and a reader sees it beside the name.
> **Name a subsystem for its JOB**, the way its `purpose` opens ("Managing teams and members",
> "Serving tools"), never a bare topic noun ("Teams and members"): a reader takes a topic for a
> store of data. **Test code is not a component**: test cases, fixtures and test helpers are left to
> the test-completeness agent. A script in a test folder that a person runs to operate the product
> is a component like any other, because what decides is what the code does, not where it sits.
> **WHEN THE BUDGET AND THE SIZE CEILING DISAGREE, THE CEILING WINS.** The budget is the lead's
> pre-read ESTIMATE, made without opening your files; the ceiling is a property of the code in front
> of you. A slice of 46 files and 11 kLOC cannot be 5 components without two of them breaking the
> ~3 kLOC limit on their own, so it is 8, and the estimate was wrong. Return the number the code
> has, and **say in your reply why it differs** — the lint warns outside 0.5x–1.5x of the budget, and
> that warning is answered by your sentence, not by bending the count to it. Both agents this rule
> was written for hit the conflict and neither could tell which side was meant to give.
> For every row give `file:line` evidence and a confidence tag. **`verified`** = you read the code
> and traced it; **`inferred`** = you took it from a name, a path or a convention. Nothing writes
> this field, so it is the one fact only you have — it is NOT a statement about the grounding
> skeptics, whose verdicts are worked out separately and never stored here. **Use both values**: one
> shipped map carried `verified` on all 301 element rows, which tells a reader nothing about which
> rows were read, and `lint-fragment` warns when a fragment's labels are all one value. Use only the schema IDs and edge verbs; reference nodes, never
> invent them.
>
> **THE ARRAYS THIS SLICE OWNS — the full list, not an example.** Author every one of these, and
> nothing else:
>
> | array | yours when |
> |---|---|
> | `components` | always |
> | `entry_points` | a file here is a trigger surface (a route, a job, a command that acts on the running product) |
> | `deps` | a third-party system is reached from a file here |
> | `observability` | a logging / crash / analytics adapter lives here |
> | `config` | a settings key is read literally in a file here |
> | `deployment`, `run_commands` | a manifest, compose file or command declaration lives here |
>
>
> **A command is a way in ONLY when it acts on the DEPLOYED product.** What it acts on decides, and
> nothing else: not its name, not what it is for. **Being a test exempts nothing** — a release smoke
> test that signs into the live site IS a way in, and a suite that starts its own stack is not.
>
> | it acts on | which is | verdict |
> |---|---|---|
> | the deployed product, the one other people use | the live site; a live account at a provider the product runs on; the stored data; an instance somebody else depends on | a way in |
> | a copy this command owns | a stack it starts and stops itself; a test database; a build output; the source; a fake server a test launches | not a way in |
>
> **Reading counts.** An operator who prints production data crossed the same door as one who
> changes it.
>
> **When both rows fire, ask what was there BEFORE the command ran.** A thing the command creates
> and can destroy is a copy it owns, however publicly that copy can be reached. A thing that was
> already there and is still there afterwards is the deployed product. A dev launcher whose stack a
> matching stop script kills owns it, even behind a public tunnel; a deploy that builds an image AND
> replaces the live site is a way in, because the site outlived it at both ends.
>
> Three cuts, each one a row a reader got wrong:
>
> - **A command that CALLS one of the product's own addresses is not a NEW way in.** The address is,
>   and the slice holding it records it. A script that posts to the live admin API adds nothing here.
> - **A wrapper and the command it wraps are ONE way in**, recorded once, at the command that acts.
>   A `make` target calling `scripts/clear_db.py` is one row, not two.
> - **What a container declares for ITSELF is not a command anybody types**: its own argv, a
>   healthcheck, a sidecar. Those are the deployment's business, so they get no `entry_points` row
>   and no `run_commands` row either. **A command a PERSON runs is a command wherever it is written
>   down**, a comment inside the compose file included: one live map's only deploy command lives
>   there, and a reader who took this cut broadly would have dropped it.
>
> **Moving it is a WRITE, not a decision.** Deciding a command is not a way in is half the work;
> the other half is its `run_commands` row, in the same edit. **Then count them: your reply says how
> many commands you moved out of `entry_points`, and names them.** Measured on the first build under
> this rule: 11 of the 36 command files the previous map carried as ways in ended up in NEITHER
> array — the backend lint command among them, which the map now records nowhere at all. Every one
> of those was a decision made and a write forgotten, and nothing in the build could see it, because
> a row that was never written leaves no trace. The count is what makes the second half visible.
>
> **`entities` is NOT yours** unless your brief carries the T5 addendum. Neither is any array not
> listed above.
>
> **AUTHORING A `deps` ROW: one rule lives in `model.md` and blocks you if you do not know it.**
> Every dep in the EXTERNAL group (`datastore` / `messaging` / `service` / `platform`) must either
> name the surface(s) it belongs to in `interfaces`, or carry `not_an_interface: <why it is none>`.
> Surface ids (`In`) are minted at synthesis by a slice you do not own, so you cannot fill
> `interfaces` from here even when you can see the answer. **Three cases, and the third is the one
> that keeps being got wrong:**
>
> - it is genuinely NOT a surface (a library the product embeds, a store it writes only to read
>   back) → `not_an_interface: <why>`.
> - it IS a surface and you can see which one → say so in `not_an_interface` as a POINTER, in
>   words: `"Not decided here — this is a surface; the id is minted at synthesis."` The lead reads
>   it as a candidate, not as an exclusion.
> - **you do not know** → the same pointer, saying that. Do not guess either way.
>
> **Never write a reason you do not believe.** An earlier draft of this paragraph said the answer is
> "almost always `not_an_interface`", and an agent looking at a crash-reporting service — reports
> leave the product and nothing inside reads them back, so it plainly IS a surface — was being asked
> to state a false reason. It refused and wrote the pointer instead, which was right. A wrong
> exclusion is worse than a missing one: the next reader cannot tell it was wrong.
> Frameworks and libraries are exempt from the whole rule: they become the product.
>
> **If an array is empty, return it as an empty array AND say why in your reply** — never silently
> omit one. The lead cannot tell "nothing here" from "the agent forgot" otherwise. (This paragraph
> used to read "return exactly this fixed set of sections — one per prescribed slice", which an
> agent owning one slice could not parse at all: it reads as "return one section".)
>
> Your output is **ONE JSON fragment** — a partial map model per
> [model.md](«COYOMAP_HOME»/method/model.md), each entry using that array's exact field names.
>
> **THE FIELD NAMES, so you do not have to go and find them.** Required fields are in bold; omit an
> optional one you have no value for (but see the "nothing is configured" rule below).
>
> | array | fields |
> |---|---|
> | `components` | **id**, **name**, **purpose**, **source**, kind, confidence, subsystem, entry_point, files, depends_on |
> | `entry_points` | **kind**, **trigger**, **source**, activation, runs_in, cadence, cadence_source — NO `id`, `assemble` mints it |
> | `deps` | **id**, **name**, **kind**, type, used_for, where_configured, confidence, package, evidence, interfaces, not_an_interface |
> | `observability` | **signal**, where_emitted, where_viewed, alerts |
> | `config` | **key**, **purpose**, default, per_env |
> | `deployment` | **unit**, runs_on, exposed_as, config_source, variants |
> | `run_commands` | action, command, source |
>
> `deps[].kind` is a CLOSED vocabulary: `datastore`, `messaging`, `service`, `platform`,
> `framework`, `library`. The first four are the EXTERNAL group the interface rule below governs;
> the last two are folded — they become the product.
>
> This table exists because the brief used to give field names for `components` only and say "see
> the schema" without saying where it is. Two agents out of two went and opened `model.md`, and one
> opened `grammar.py` as well, to author rows the brief had told them to author. **WRITE the fragment to
> `«repo»/.coyomap/build-fragments/«agent-id».json` yourself and return only that path plus a
> one-line inventory (row count per array)** — never inline the fragment in your reply: a large
> fragment (a T5 return routinely exceeds 50 KB) is silently truncated by sub-agent result caps,
> and a truncated fragment fails `assemble`. An empty slice is an empty array plus a one-line note.
> **Anchor formats** (`assemble` does not fix these up — write them right, or `coyomap validate`
> rejects them): `components[].source`, `entities[].source`, `components[].entry_point`,
> `deps[].where_configured`, `edges[].where`, `entry_points[].source`, `evidence[].file`,
> `run_commands[].source`, `non_entity_types[].source`,
> **`rules[].sites[].where`** (the OPERATIVE line — its `:line` is REQUIRED, never a bare file),
> **and the group `source`
> fields** (`subsystems[].source` / `subdomains[].source` / `capabilities[].source` /
> `blocks[].source`) are all **bare** repo-root-relative refs
> (`path/to/file.py:120`; a directory anchor keeps its trailing slash, `path/dir/`; an extensionless
> ops file carrying a line is fine — `Dockerfile:1`, `Makefile:6-9`) — a bare file or directory ref,
> never a markdown link and never two refs joined by a separator (put a run command's doc pointer in
> its `command`/prose, not its `source`). `tests[].tests[].file` is also a bare anchor (a `path:line`
> or a `path/` test dir), turned into a code link. The operational free-prose fields
> (`deployment[].config_source`, `observability[].where_emitted`/`where_viewed`) are
> the deliberate exception — they stay prose, not anchors.
> **Field discipline** (what `assemble` / `validate` reject — get it right at the source): (a) every
> **required** field is present and non-null; for an **optional** field with no value **omit the key**
> entirely — do NOT emit `null` (rejected on defaulted-string fields) and do NOT emit a placeholder like
> `(none)` (fails the anchor gate). **"Nothing is configured" is a VALUE, not a missing field.** If
> the true answer is that this thing has no alerts, no schedule, no retention — say so in the field,
> in words. Omitting the key means "I did not find out"; the two are different facts and the reader
> cannot tell them apart afterwards. Omit only when you really did not find out. (b) Use **only** each array's exact field names — no stray keys
> (`notes`, `slice`, `loc`, …) — but `confidence` IS a real field, required above and enumerated in the schema (`verified` / `inferred`). (c) Every anchor is **repo-root-relative**, and that means
> it does NOT carry the repo root. The root is «REPO_ABS»; write the part AFTER it, with no leading
> slash — `backend/auth/gate.py:10`, never `«REPO_ABS»/backend/auth/gate.py:10`. (This used to read
> "the repo root is «REPO_ABS» — prefix every path with it", which says the opposite of the rule in
> the same breath: prefixing makes an anchor absolute. Two agents spotted the contradiction and did
> the right thing anyway; a third would not have.) Minimal valid fragment:
> `{"components":[{"id":"C1","name":"AuthGate","purpose":"verifies tokens","source":"backend/auth/gate.py:10"}]}`.
> **WRITE A DRAFT AS YOU GO (required).** Do not hold the fragment in your head until the end: an
> agent that dies mid-run (API outage, machine sleep) loses ALL its reading. Write incremental
> progress to `«repo»/.coyomap/build-fragments/«agent-id».draft.json` and RENAME it to
> `«agent-id».json` only when complete. Spell it `«agent-id».draft.json`, never
> `«agent-id».json.draft` and never a doubled suffix: `assemble` SKIPS any path ending
> `.draft.json`, which is what keeps a half-written fragment out of the glob — and what makes a
> fragment left with that name never assemble at all. The RENAME is what makes your work land.
> **Fields you must NOT author** (the lead assigns them after the fan-out, through `coyomap
> reconcile`; a fragment carrying one is either rejected or silently wrong): `runs_in` — the
> deployment-unit names are minted by a DIFFERENT slice running beside you, so a plausible guess
> like `["backend"]` passes your own lint and hard-fails the lead's `validate`; `subsystem`;
> `subdomain`; `bucket`; `block`; an `id` key on `entry_points` (`assemble` mints `EP` ids from
> content); and a `security` array, ever — an auth surface is a BUSINESS RULE (`access: true`),
> written after the trace by the rules fan-out, and the Security & auth table is derived from those
> rules. `security[]` is legacy storage on old maps; `lint-fragment` warns on any fragment that
> authors it. Note the auth-relevant facts you see (the guard, its file:line) in your REPLY so the
> lead can seed the rules fan-out; do not author rows for them.
> **Scratch files: put your AGENT_ID in the name.** Every agent in this fan-out shares one
> scratchpad directory. A helper script called `build.py` or `notes.py` WILL be overwritten by a
> sibling mid-run — it has happened, and one agent's script then wrote another agent's output file.
> Name it `«agent-id»-<what>.py` and use absolute paths.
> **Quote your shell separators.** The Bash tool runs zsh, where a bare `=word` is EQUALS expansion:
> `echo ====` aborts the command line THERE, so everything after it on that line silently does not
> run and you get a partial read you believe is complete. Write `echo "===="`. Measured on one
> build: 61 truncated command lines across 18 of 71 agents.
> **SELF-CHECK BEFORE RETURNING (required):** run
> `«COYOMAP_HOME»/.venv/bin/coyomap lint-fragment --repo «repo» --expect «N» «your-fragment».json` and
> fix every row it reports until it exits clean — this catches schema / anchor-format / extra-key /
> missing-file errors in YOUR context (in parallel), so nothing bounces back from the lead's
> `assemble`. Pass `--expect «N»` with the component budget this slice was dispatched with: it is
> advisory, and it puts the over/undershoot in front of the agent that can explain it — otherwise
> nobody sees it until the lead's granularity advisory fires after assembly.
> **The verdict line carries the two counts worth acting on, so a reader who takes only the first
> line still sees them.** With `--repo` it ends with an anchor-drift count when any of your anchors
> point at a line that cannot be acting — an import, a comment, a `def`, a blank line. With
> `--expect` it also carries how far past its budget the slice landed. Read the FIRST line:
> `LINT OK — 0 problems, 4 advisory warning(s) (3 anchor drift) (3.7x the slice budget)`. Those rows are advisory and
> never fail the lint, and they are the defect this self-check was blind to until now: six
> fragments once passed clean and produced 86 drifted anchors at the lead's `validate`, costing
> fifty turns of repair after their authors were gone. Anchor the operative statement — the call,
> the write, the enforce line itself — or set `no_call_site`.
> If the lint prints `warning:` lines (advisory), either FIX them or **repeat them verbatim in your
> reply with one line of justification each** — never silently shrug an advisory off; the lead must
> not rediscover a warning your own lint already showed you.
> **Anchor the operative statement** — the call / write / enforce line itself — **never the enclosing
> `def`/class header** (the most common anchor-drift the adversarial pass finds).
> Your AGENT_ID is your fragment's **filename stem only** — never a field inside the JSON.
> **Entities are the T5 owner's alone.** Exactly one agent in this fan-out owns T5; its brief says
> so and continues in an appended addendum. If yours does not, return your components /
> entry-points only and leave `entities` (and every `E↔E` relation) to the owner — do not author
> them, however clearly the domain layer shows in your files.
> (Edges — including `C→E` — are traced in Phase 3, NOT harvested here; this phase returns nodes.)

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
