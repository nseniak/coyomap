# Test-completeness contract — the copyable template

**Lead half.** Fill every `«SLOT»` before dispatch: `«COYOMAP_HOME»`, `«REPO»`, `«MAP»`,
`«PROJECT»`, `«TESTS_ARE»`, `«AGENT_ID»`. Get it with the verb — `coyomap contract tests --slots`
prints the skeleton, `coyomap contract tests --fill <slots.json> --out <file> --brief <id>` writes
the brief and prints the pointer to send — never by copying this file.

WHY THIS TEMPLATE EXISTS. The test-completeness slice is the one every build has and no template
covered, so its brief was hand-written on every build: on 2026-08-20 the hand-written brief lost
the no-delegation block and `--expect`; on 2026-09-08 it was written last, dispatched last, and was
the batch's straggler (13.6 minutes against a 6.1-minute median). A hand-composed brief loses the
shared machinery every time, and `method.md` says this agent launches the moment the traced map is
assembled — before the T7 rules and the Phase 4 skeptics — so the brief has to be ready then.

- **«TESTS_ARE»** — where the suites live and what each costs to run, in two or three sentences:
  the unit tree, the integration tree and whether it hits a paid service, the browser suite, and
  the map components that already carry them (`dump --members <the tests subsystem>`). Say what is
  deliberately OUTSIDE the analysed tree (a front end's own unit tests, for example), so the agent
  does not go looking for it.
- **«PROJECT»** — the product's name as the map's title spells it.
- **«AGENT_ID»** — unique across the WHOLE build; scratch-file safety rests on it.

---

You are measuring TEST COMPLETENESS for a coyomap codebase map of «PROJECT».

**NEVER `cd` into the coyomap clone.** Address both repos by ABSOLUTE path, always. A `cd` persists
for the rest of your session, so a later relative `.coyomap/...` path silently reads the TOOL's own
map instead of this project's — a wrong answer that looks like a right one.

- The repo you are measuring: `«REPO»`
- The finished map: `«MAP»`
- The coyomap clone (tools only): `«COYOMAP_HOME»`

**Do this work yourself — do NOT spawn sub-agents, and do NOT write a program that GENERATES your
fragment.** Author the rows. A small edit to a draft you already wrote by hand is fine.

## The job

Coverage percentages say which LINES ran. They do not say which BEHAVIOURS are tested. So measure
against the MAP's own inventory, not against the code:

1. Read the map with `coyomap dump` rather than hand-parsing the JSON:
   `«COYOMAP_HOME»/.venv/bin/coyomap dump --legend «MAP»` gives the inventory with its counts, and
   `--id <ID>` / `--record <ID>` / `--members <ID>` one element. `dump --help` is real.
2. Walk the inventory and ask of each target: **is there a test that exercises it?**
   - the use cases (`UCn`)
   - the ways in (`entry_points`), especially the customer-facing kinds
   - the records (`entities`), especially the ones the product keeps
   - the failure paths the flows narrate (a refusal, a fallback, an expiry)
   - the critical-path branches: anything touching access control, credentials, team isolation,
     money-shaped caps, or an irreversible delete
3. The DELIVERABLE IS THE GAPS, risk-ranked. Lead with untested critical paths.

## Where the tests are

«TESTS_ARE»

## READ-ONLY BY DEFAULT — and say so

**Do NOT run the suites.** A browser suite starts its own stacks and an integration suite may cost
real money. So build this table by READING the tests, mark **every** row `inferred`, and set
`tests_note` to state plainly that the suites were not run and that the rows are therefore a
reading, not a measurement. Never present a read-only table as if it were measured. Running the
suite with coverage, which upgrades rows to `verified`, is an opt-in the lead grants in this brief;
it was not granted here.

**Read the body of every test you cite.** A test's name says what its author meant; its body says
what it checks. Open each test you cite at its line and read it through (`sed -n '<line>,+30p'
<file>`) before you write its `why`. A list of names from `grep -n 'def test_'` tells you where to
look, never what to cite. The lead runs `coyomap grounding lint --tests` over your fragment, and a
citation whose body no tool call of yours printed fails it: on one build 83 of 184 citations rested
on the name alone.

## The fragment

Write ONE JSON fragment to `«REPO»/.coyomap/build-fragments/x-tests.json` and return only that
path plus a one-line inventory. Never inline the fragment in your reply.

```json
{ "tests_note": "<the honesty line: were the suites run?>",
  "tests": [
    { "targets": ["UC28", "C19"],
      "label": "<the behaviour being asked about, in a few words>",
      "tested": "yes | partial | no",
      "tests": [ { "file": "backend/tests/unit/test_policy_engine.py:40",
                   "why": "<what this suite actually asserts about the target>" } ],
      "gap": "<what is NOT covered, and what it would cost if it broke>",
      "confidence": "inferred" } ] }
```

- `targets` are explicit map IDs, never prose.
- `tests[].file` is a bare `path:line` or a `path/` directory — never a markdown link.
- A row with `tested: "no"` carries an empty `tests` array and a real `gap`.
- **The table must never ship empty**, and it must not be only the good news: a table with no
  `no`/`partial` rows means the sweep did not look hard enough.
- Aim for roughly 30–50 rows. Group by behaviour, not one row per test file.

Every `label`, `gap` and `why` is read ONE BOX AT A TIME by somebody who does not read code; the
writing rules at the end of this brief govern all three.

## Self-check before returning (required)

```
«COYOMAP_HOME»/.venv/bin/coyomap lint-fragment --repo «REPO» --ids «MAP» \
  «REPO»/.coyomap/build-fragments/x-tests.json
```

Read the output WHOLE — do not pipe it through `head` or `tail`. Fix every problem until it exits
clean. If advisory `warning:` lines remain, either fix them or repeat them verbatim in your reply
with one line of justification each.

**With `--repo`, the verdict line ends with an anchor drift count when a `tests[].file` points at
a line that cannot be a test** — an import, a comment, a blank line. Read the FIRST line:
`LINT OK — 0 problems, 3 advisory warning(s) (3 anchor drift)`. Those rows are advisory and never
fail the lint; point each `file` at the test function itself, or at the suite's directory.

Write progress to `x-tests.draft.json` as you go and RENAME to `x-tests.json` when complete — the
rename is what makes your work land. Quote your shell separators (`echo "===="`), because a bare
`=word` aborts the command line in this shell. Name any other scratch file `«AGENT_ID»-<what>`.

**Do not open a previous map** — not one under `.coyomap/dev-rebuilds/`, not one `git show` can
produce. This build is deliberately independent of its predecessor.

In your reply, state: the row count, the split of `yes` / `partial` / `no`, and the three gaps you
would fix first, with why each one matters.
