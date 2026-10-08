# Contributing to coyomap

Thanks for taking a look. coyomap is **alpha** — experimental, early, and moving
fast. That means feedback is worth a lot right now, and the bar to contribute is
low: a clear bug report or a sharp idea is a real contribution. The version
number lives in one place, the [`VERSION`](VERSION) file at the repo root;
`pyproject.toml` reads it from there, and the docs deliberately do not repeat it.

By participating you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to help

- **Report a bug.** Something the skill, the method, or the viewer got wrong.
  Open a [bug report](../../issues/new?template=bug_report.yml).
- **Share an idea or feedback.** Missing capability, confusing output, an awkward
  step in the build → analyze → accept loop. Open an
  [idea / feedback issue](../../issues/new?template=idea.yml).
- **Comment on map quality.** Because map quality depends on the coding agent and
  model, concrete before/after examples ("the map said X, the code does Y") are
  especially useful.
- **Send a pull request.** For docs, the method, or the Python tooling. For
  anything non-trivial, please open an issue first so we can agree on the shape
  before you spend time on it.

## How the repo is laid out

- **`method.md`** — the single source of truth for the method. The skill follows
  it; it is not a mirror of the code. Changes to behavior usually start here.
- **`method/`** — the supporting method docs (`model.md`, `domain-cards.md`,
  `change-impact.md`, `diagrams.md`) and templates.
- **`skill/coyomap/`** — the agent skill (`SKILL.md`) that drives the method; works on
  Claude Code, Codex, and Cursor.
- **`tools/coyomap/`** — the Python package behind the `coyomap` CLI: the pre-index, schema
  validation, the analysis validator, and the **`viewer/`** (builds the map's view data and
  serves the interactive viewer via `coyomap serve`). `cli.py` is the subcommand dispatcher.
- **`tests/`** — the tool tests, plus the two contract layers: `test_method_contract.py`
  (does the method name tools that exist?) and `test_trapdoor_tools.py` (do the tools say the
  right thing about a real tree?). Stdlib runners; also run under `pytest`.
- **`eval/`** — the two evals and their tests: map quality (`eval/README.md`) and the build-process
  scorecard. `eval/fixtures/trapdoor/` is a synthetic codebase that deliberately plants every
  defect class real builds produced; `traps.yaml` there is the source of truth for what is planted.
- **`README.md`** — user-facing overview and the install / usage steps.

> `internal/` (design notes, working drafts) is **not** part of the method and is
> git-ignored — with ONE tracked exception, `internal/docs/method-rationale.md`, described
> below. Don't treat any of it as instructions or as input to a map.

## Writing method prose — keep the three registers apart

`method.md`, the `method/` docs and the templates in `method/templates/` are not
documentation. They are the **prompt** an agent reads on every build, and the templates are
copied verbatim into 12-20 sub-agent prompts per run. Every sentence you add there is paid
for on every build, by every agent.

Three registers get written into a rule, and only two of them belong in the prompt:

| register | example | where it goes |
|---|---|---|
| **Contract** — what a map must contain | "every edge carries a `Where`" | the method |
| **Procedure** — what to do, and the mechanism that makes it matter | "never `ls` the fragment dir: a not-ready file reads as an error and burns the turn" | the method |
| **Incident record** — the build that went wrong, and how the wording got here | "a live build spent 88 of its 278 tool calls polling; the prose had already been escalated twice" | `internal/docs/method-rationale.md` |

**Write the rule and its mechanism. Put the incident in the record.** The mechanism is
timeless and lets an agent reason about a case nobody anticipated; the story is evidence for
*you*, when you later ask whether the rule still earns its place. The corpus grew to ~48k
words largely by accretion of the third kind.

**One exception, used sparingly:** where a measured magnitude is itself the deterrent — the
rules agents are tempted to skip, like polling a barrier or hand-writing a script a command
already does — keep a short marker (`32 % of a build's tool calls`) and put the full account
in the record.

**Every record entry carries an `Anchor`** — a phrase quoting the rule it explains, which
must still appear in the named doc. `tests/test_method_rationale.py` checks all of them, so a
rule cannot be reworded or deleted away from its evidence: change the rule and the suite tells
you which entry to reconcile. Anchors must quote the rule's own words, not just the bold
heading above it — a heading survives its paragraph being gutted, so it certifies nothing.

**Never link from the method to the record.** The method tells agents to ignore `internal/`;
a method doc pointing there would contradict that in the same breath. The link runs one way
only, and the anchors are what keep it honest.

**The record is PUBLISHED, so describe the build and never identify it.** It is the one tracked file
under `internal/`, and it grows every time a rule earns evidence. What makes an account useful is the
mechanism and the magnitude — "32 % of a build's tool calls", "103 minutes", "5 of ~11 state machines
refuted" — never which project, which session, or what it cost in money. Those identify a private
codebase and add nothing a reader can act on. `tests/test_method_rationale.py` refuses absolute home
paths, session ids, currency amounts, hostnames and email addresses outright; for project NAMES, which
no pattern can catch, it reads an optional git-ignored `internal/docs/.private-names` — one name per
line, so the check enforces on the machine where those projects exist without the names ever entering
the repo.

## Numbers about a live map

A number measured off a real map — "142 entities, 46 of them saved", "4 of the 7 features have two
or more drivers" — is a measurement of something that keeps being rebuilt. The code stays right and
the sentence stops being true, and no gate can see it: every instance IS the code doing exactly what
the code says. Measured on 2026-09-07, 23 of the 27 decidable sentences of this shape were wrong.

So, when you write one:

- **Past tense, naming the build** — "the 2026-09-07 mcpolis map read 4 of 43" — is a record, and
  records do not rot. Two thirds of the number-claims in `tools/` already do this. Prefer it.
- **Present tense about a live map** needs a row in `eval/tools/coyomap_eval/live_numbers.py`: the
  sentence, the maps it needs, and a `measure` that regenerates it. `coyomap-eval live-numbers`
  then re-measures it whenever someone asks, and `coyomap-eval live-numbers --list` shows what is
  already tracked.

Nothing reads your prose to work this out — you write the sentence in both places on purpose, and
the ledger reports when the two stop agreeing in either direction.

## Local setup

The skill itself needs no build — install it once from the repo root (macOS/Linux).
`make install` copies `SKILL.md` (with the repo path baked in) into each agent's
skills home — `~/.claude/skills` (Claude Code) and `~/.agents/skills` (the cross-agent
standard read by Codex and Cursor):

```
make install       # the USER skill: skill/coyomap -> ~/.claude/skills + ~/.agents/skills
make install-dev   # both DEVELOPER skills: coyomap-eval + coyomap-retro
make uninstall     # removes the user skill from both homes
make uninstall-dev # removes both developer skills
```

`install-dev` is the one a contributor wants: `coyomap-eval` answers "did my change make the maps
worse?" and `coyomap-retro` answers "what did that run reveal?" — two halves of one feedback loop.
They are deliberately NOT part of `make install`, so installing the developer surface is never a
side effect of setting the tool up. (`make install-eval` / `make install-retro` still install one
at a time.)

**Re-run the relevant target after editing any `SKILL.md`, or after moving the clone.** The install
renders a COPY into the skills homes with the repo path baked in, and nothing re-runs it for you —
which is how the main skill spent weeks telling agents to read a method doc that had been renamed.
`tests/test_skill_pointers.py` keeps the copies thin enough that drift is nearly harmless, but it
cannot see the installed files.

**A build and its retro, overnight.** `make claude-build` (see the README, "Using headless
Claude Code") has two developer siblings, which need `make install-dev`:

```
make claude-build-retro REPO=~/my-project   # the build, then /coyomap-retro of it, in the same folder
make claude-retro RUN=~/my-project/.coyomap/runs/claude-2026-10-08_230000   # the retro of a run alone
```

The retro asks `coyomap-eval retro-precheck` every 30 s and starts once the project folder has been
quiet for 180 s; after `WAIT=` minutes (30) it gives up and writes "retro skipped" in the run's
`status` file. Another Claude session open on that project also counts as not quiet. It also
refuses a map this run's build did not stamp, because a build that died early leaves the older
map in place. `MODEL=` and
`EFFORT=` work as for the build. Every target that runs Claude is named `claude-*`, so a version for
another agent can sit beside it; `tools/claude_headless.py` keeps the agent-neutral steps apart.

The `coyomap` package is tested with `pytest` and type-checked with `pyright` (see
`pyrightconfig.json`). `make dev` builds the repo-local venv and installs both into it
(alongside the editable package), so the gates run against the installed CLI:

```
make dev                # venv + editable install + pytest/pyright
.venv/bin/pytest        # run the whole suite — see the warning below
.venv/bin/pyright tools # type-check (please keep it clean)
```

> **Run `pytest` with no path.** The suite lives in two places (`tests/` and `eval/tests/`)
> and `pyproject.toml` lists both under `testpaths`. Naming a path on the command line
> **overrides** that setting, so `pytest tests` silently skips every test under `eval/tests`
> and still reports green. Plain `.venv/bin/pytest` runs all of them.

Working on the **viewer** (the browser page a map is read in), use `make dev-start` instead of
`make start`. It serves this repo's own map with live reload, so an edit to `viewer.js` / `.css` /
`.html` — or to the server's Python, which restarts it — reaches the page with nothing pressed. Off
in `make start` on purpose: a person reading a map must not get a page that reloads under them. See
`tools/coyomap/viewer/README.md` → **Working on the viewer** for how the two halves fit together.

## How to test a change

There is no single command that covers everything, because the layers answer different
questions. What you changed decides how far up you need to go.

| tier | command | answers |
|---|---|---|
| **1. The gates** | `.venv/bin/pytest` · `.venv/bin/pyright tools` | Is anything broken? Do the tools do the right thing, and does the method still name commands and flags that exist? |
| **2. Process corpus** | `COYOMAP_L3_CORPUS=1 .venv/bin/pytest eval/tests/test_process_corpus.py -q -s` | Do the transcript detectors still read saved builds the same way? |
| **3. A real build** | `claude -p "/coyomap from scratch"` in a repo, then `coyomap-eval process <transcript>` | Did the agent actually *do* the thing? |
| **4. Map quality** | `/coyomap-eval` in a project with a committed map | Is the map any good — grounding, rubric, coverage? |

### Working on the viewer

Serve one or more maps and look at them:

```
PYTHONPATH=tools .venv/bin/python -m coyomap.cli serve . ~/somewhere/else --port 8871 --dev
```

Two things that will otherwise cost you an hour:

- **The page caches its own JavaScript. Hard-reload after every edit**, or you will debug a
  version of the file you have already changed. A viewer edit that "did nothing", or a page
  that renders blank while its content is plainly in the DOM, is this until proven otherwise.
- **Test against two maps with different shapes, not one.** This repo's own map is a command
  line and files; a web product's map is screens and APIs. A screen that only looks right on
  the richer of the two is not finished, and the sparse one is where the empty states show.

**Hold Ctrl+Shift** to ask what the map SAYS about anything on screen: every element the map
stores lights up under the cursor, and Ctrl+Shift+click opens its stored record — the slot in
`.coyomap/project-map.json` it came from, and the record itself. An id inside the record opens that
record. A click on something the map does not store says so, and prints the DOM handles it looked
at, which is what extending the resolver needs. While both keys are down the page itself is
deaf — no pan, no wheel-zoom, no hover, no drill, and no browser context menu — and nothing at
all is armed until they are.

The viewer's own tests need a real browser and are slower than the rest: `tests/test_viewer_browser.py`.
`node --check tools/coyomap/viewer/viewer.js` catches a syntax error in a second, so run it first.

**Tier 1 is required for every PR.** It is fast (~20s) and deterministic. It covers three
layers:

- the tool tests — what the code does when it is called;
- **`tests/test_method_contract.py`** — the prose↔tool contract, checked statically: every
  command and flag `method.md` names really exists, and every advisory the validator prints
  can be answered. This layer exists because `coyomap reconcile` once shipped fully working
  and fully tested while appearing nowhere in the method, so no build could reach it;
- **`tests/test_trapdoor_tools.py`** — the tools run against `eval/fixtures/trapdoor/`, a
  synthetic codebase that deliberately plants every defect class real builds produced. Its
  `traps.yaml` is the single source of truth for what is planted and which layer asserts it.

**Tier 2 is opt-in** because it reads build transcripts from `~/.claude/projects/`, which
live outside the repo and will not exist on another machine. Without the flag the tests skip
cleanly. Run it when you touch the process checker itself.

**Tier 3 is the only thing that can test a change to `method.md`.** The method is a prompt.
Tiers 1 and 2 read text and old recordings; neither can tell you whether an agent reading
your new wording behaves differently. That gap is not theoretical — a rule was once rewritten
and the behaviour did not move at all, and nobody could tell. So: make a real build, score its
transcript, and diff it against a build from before your change.

```
.venv/bin/coyomap-eval process <transcript.jsonl>        # writes a scorecard next to it
.venv/bin/coyomap-eval process --diff before.json after.json
```

The scorecard is **never a gate**. It reports `observed / of` with turn numbers attached, not
pass/fail: a single run proves nothing, and these are LLM builds that vary. A number that
moves is something to look at. The design and the ten assertions are in
[`eval/fixtures/trapdoor/L3-DESIGN.md`](eval/fixtures/trapdoor/L3-DESIGN.md).

**Tier 4** costs real model time and money — see [`eval/README.md`](eval/README.md). Reach for
it when your change should alter what a map *contains*, not which commands get run.

### Short version

| you changed | run |
|---|---|
| `tools/coyomap/` | tier 1, plus tier 2 if you touched the transcript detectors |
| `method.md` or `method/` | tier 1, then **tier 3** — nothing else can tell you it landed |
| `eval/` | tier 1 + tier 2 |
| something you expect to improve map quality | tier 1 + tier 4 |

## Pull request guidelines

- **Keep the diff scoped** to one change. The project itself is built around
  small, reviewable diffs — please mirror that.
- **Match the surrounding style.** Plain prose in the docs; typed Python in the
  tools (type annotations, no unnecessary `Any`).
- **Update the method and the docs together with the code.** If behavior changes,
  `method.md` / `method/` should change in the same PR, since the method is the
  source of truth.
- **Run the gates** (`.venv/bin/pytest` with no path, `.venv/bin/pyright tools`) before pushing,
  and say in the PR what you ran. If you changed `method.md` or `method/`, say whether you ran a
  real build (tier 3 above) — a method change the gates pass can still fail to reach the agent.
- **Fill in the PR template** so a reviewer can see what changed, why, and how you
  checked it.

## A note on stability

The on-disk map format and the method are still moving — there are **no
backward-compatibility guarantees yet**. Treat generated maps as disposable, and
don't be surprised if a change touches the format. If a change *does* break the
format, please call that out explicitly in the PR.

**Latest format break — the business-logic layer (T7).** A map now states what the product
DECIDES: `blocks[]` (a decision grouping) and `rules[]` (one decision plus every place it is
enforced). **An auth surface is a business rule with `access: true`** — the Security & auth table
is a derived view of those rules, and `security[]` is legacy. **There is no migration tool.** An
existing map keeps loading and keeps rendering its `security[]` rows beside any rules, so nothing
disappears; it gains the decision layer only by being **rebuilt** with the current method. Two maps
in the fleet already fail to load on an earlier rename, so "just rebuild" is stated here rather
than assumed.

## Licensing of contributions

coyomap is licensed under the [Apache License 2.0](LICENSE). By contributing, you
agree that your contributions are licensed under the same terms, including the
patent grant in section 3 of that license.
