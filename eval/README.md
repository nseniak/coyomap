# coyomap-eval — method-quality regression harness

**For the coyomap DEVELOPER, not for users of coyomap.** It exists to answer "did my change to the method or the tooling make the maps worse?", which is a question only someone changing coyomap asks. A user's map evolves incrementally alongside their code; a from-scratch rebuild is a first-run event for them, so the repeated rebuilding this command depends on is a developer habit.

This package answers one question: **did a change to the coyomap method or tooling make the maps it
produces better or worse?** It compares **two maps of the same code**: the project's current
`.coyomap/project-map.json` against an archived predecessor in `.coyomap/dev-rebuilds/NNNN/`. If
quality dropped, it tells you.

**It builds nothing.** `/coyomap` is the builder — and the thing being measured, so a second build
path here would be a copy that drifts from it. The loop is:

```sh
coyomap-eval archive .    # move the current map to .coyomap/dev-rebuilds/NNNN/
/coyomap                  # rebuild from scratch with the current method
/coyomap-eval             # compare the new map against that archive
```

Maps are LLM-written, so two builds of the same repo never match byte-for-byte (IDs, wording, ordering
drift). So the harness never diffs map *text* — it compares measurable **quality signals**.

## The two ways in

- **`/coyomap-eval` (the skill)** — the normal way. Run it inside a project and it drives the whole
  thing: pick the two maps → guard (same code both sides) → freeze their hashes → score + judge each,
  cached by map hash → compare → store the run. It's the agent-driven orchestration (it spawns the
  judge sub-agents, which the tool itself can't do). Install it with `make install-eval`; the recipe
  it follows is `eval/method.md`.
- **The `coyomap-eval` CLI commands below** — the deterministic building blocks the skill calls. You can
  also run them by hand.

`eval/blind-build.md` is the separate recipe for producing a map whose builder **provably** never saw
the previous one (an isolated worktree at the pin). The everyday loop above is blind in practice —
`archive` moves the map out of the working tree; nothing reads `dev-rebuilds/` — but a phase-boundary
validation wants blindness by construction. Its output is handed to the eval as an explicit map path.

## The signals it compares

- **structure** — counts of use cases, subsystems, components, entities, edges, Happy-Path steps…
- **well-formedness** — `coyomap validate` problems / warnings
- **self-consistency** — `coyomap audit` contradictions / advisories
- **coverage** — how much of the source the map actually maps
- **faithfulness (semantic)** — the LLM judge: L2 grounding pass-rate + a 5-dimension rubric (0–4)

The first four are **deterministic** (free, instant, no LLM). The judge needs a real model, so it runs
in the orchestration layer (sub-agents) and is handed in as a `judge.json` (see "The judge" below).

## Two homes — keep them straight

- **The `eval/` bundle** (this self-contained folder in the coyomap repo): the skill (`SKILL.md`), the
  method doc (`method.md`), the config (`thresholds.json`, `rubric.md`), and the code — a standalone
  `coyomap_eval` package under `tools/coyomap_eval/` exposing the `coyomap-eval` command. It depends on
  coyomap's core (schema/validate/audit) but the core has no reference back to it.
- **Data** (`.coyomap-eval/` inside each evaluated project, **git-ignored**): run archives, and a
  scoring cache keyed by map hash. The maps themselves are the project's own — the current
  `.coyomap/project-map.json` and its archives under `.coyomap/dev-rebuilds/`.

```
eval/                         # the bundle (in the coyomap repo)
  README.md  SKILL.md  method.md  blind-build.md  thresholds.json  rubric.md
  tools/coyomap_eval/         profile.py · compare.py · judge.py · run.py · cli.py
  tests/                      test_profile.py · test_compare.py · test_judge.py · test_run.py
```

```
<project>/
  .coyomap/project-map.json           # the candidate — the current map
  .coyomap/dev-rebuilds/NNNN/         # the baselines — previous maps, moved here by `archive`
  .coyomap-eval/                      # git-ignored, regenerable
    cache/<map sha12>/  map-hash · profile.json · judge.json · judge-verdicts.json
    runs/<timestamp>/   project-map.json · project-map.md · map-hash · project-map.view.json
                        profile.json · judge.json · judge-verdicts.json · delta.md
```

The cache is keyed by the map's own hash, so both sides of a comparison use one mechanism — and the
map scored as the candidate today is already scored when it becomes tomorrow's baseline.

## The same-code guard (why the eval is trustworthy)

The comparison only means "the *method* changed" if the *code* is held fixed. Both maps are scored
against the **working tree** — `validate --check-sources` resolves anchors there, coverage reads it,
and the grounding skeptics read it. So `/coyomap-eval` **refuses** unless every clause holds: neither
map carries a `-dirty` pin, there is zero code delta between the two maps' pins (a delta test, not an
equality test — committing a map moves HEAD past the commit it describes, so consecutive maps
normally carry different pins over identical code), the tree is clean, there is zero code delta
between the candidate's pin and HEAD, and `.coyomap/.ignore` — the analysis-scope declaration — is
unchanged against both pins in the working tree.

You can override it ("run it anyway") except for a `-dirty` pin, which is never overridable. An
overridden run is stamped **INFORMATIONAL**, names both commits, writes **nothing to the score
cache**, and is never reported as a clean PASS or REGRESSED. `eval/method.md` Step 1 is the exact
contract.

## The commands

Run them with the CLI from the repo venv (`.venv/bin/coyomap-eval …`, or `python -m coyomap_eval.cli …`).

| command | what it does |
|---|---|
| `coyomap-eval score <map.json> [--repo <src>] [--json]` | print a map's deterministic profile (structure / validate / audit / coverage). `--repo` adds coverage. |
| `coyomap-eval run --project <name> --map <map.json> [--repo <src>] [--expect-map-hash <sha256>] [--judge <judge.json>] [--spend <spend.json>] [--baseline-dir <dir>] [--thresholds <file>] [--out <run-dir>]` | profile a map, compare it to the baseline, archive the run (map + md view + view-bundle snapshot + profile + delta). With `--spend` and a `spend.json` in the baseline dir, what each build cost per row is compared too: a rise past 25% (`spend_bands`) reads DRIFT. `--expect-map-hash` is the freeze guard: it refuses a map edited after freeze. A `--baseline-dir` that is missing or empty is REFUSED, so a mistyped path can never become a silent non-comparison. |
| `coyomap-eval hash <file>` | print a map artifact's sha256 freeze hash — written to `runs/<ts>/map-hash` when the eval picks the map, enforced by `run --expect-map-hash`. |
| `coyomap-eval claims <map.json> [--top <K>] [--json]` | print the audit's risk-ranked L2 worklist — the claims the judge grounds. `--top K` keeps the grounding sample; `--json` is the judge orchestration's input. |
| `coyomap-eval judge --map <map.json> --verdicts <raw.json> --out <judge.json> [--repo <src>] [--rubric <file>]` | aggregate raw judge verdicts (from the sub-agents) into a `judge.json`, via the tested math. |
| `coyomap-eval bless <run-dir> <baseline-dir>` | copy a run's artifacts into a baseline dir (used to seed a cache entry by hand; the normal baseline is an archive under `.coyomap/dev-rebuilds/`). |
| `coyomap-eval archive <repo-root> [--dry-run]` | move the current map to `.coyomap/dev-rebuilds/NNNN/` so the next `/coyomap` builds from scratch — and so the eval has a baseline to compare against. Moves, never deletes. |
| `coyomap-eval compare <baseline.json> <candidate.json> [--thresholds] [--baseline-judge] [--candidate-judge]` | low-level: compare two profiles directly. `eval run` uses this under the hood. |

**Verdict / exit code** (from `coyomap-eval run` / `coyomap-eval compare`): `0` = **PASS** (or **BASELINE**, first run,
nothing to compare) · `2` = **DRIFT** (a soft band exceeded — worth a look) · `1` = **REGRESSED** (a
hard gate tripped). Gates are **relative** to the baseline ("no *new* validate problems", not "must be
perfect"); tune them in `eval/thresholds.json`.

## Running it (normal path)

```sh
cd <project>
.venv/bin/coyomap-eval archive .   # the current map -> .coyomap/dev-rebuilds/NNNN/
/coyomap                           # rebuild from scratch with the current method
/coyomap-eval                      # compare, writes .coyomap-eval/runs/<ts>/
```

It prints the verdict and points you at the run's `delta.md` and `project-map.view.json`. **PASS** →
nothing got worse. **DRIFT** → a count/score moved a lot, look at it. **REGRESSED** → a real
regression. There is nothing to accept: the map it judged is already the project's current map. If the
new map is worse, the previous one is intact in `.coyomap/dev-rebuilds/NNNN/`.

## The judge (the semantic signal)

The tool never calls an LLM (that keeps it dependency-free and testable). So the real judge runs in the
**orchestration layer** — sub-agents on a pinned model (`thresholds.json` → `judge.grounding_model`)
that (1) try to **disprove** the top-K risk-ranked L2 claims against the code, 3 skeptics per claim
with a majority vote → a grounding pass-rate (a skeptic that returns no usable verdict is a *failure*,
excluded from the denominator, never counted as refuted), and (2) **score** the 5 rubric dimensions
(`eval/rubric.md`) 0–4, N judges per dimension. They write a raw verdicts JSON; `coyomap-eval judge`
turns it into `judge.json` via the tested `PrecomputedJudge` path — so the numbers are trustworthy even
though the verdicts came from live models. `/coyomap-eval` does all of this for you (step 4 of
`eval/method.md`).

## The code, briefly

- `profile.py` — `MapProfile` + `build_profile` (the deterministic signals) → `coyomap-eval score`.
- `compare.py` — `Thresholds` + `compare` → the gates/bands and the PASS/DRIFT/REGRESSED verdict.
- `judge.py` — the `Judge` seam, the aggregation, and `PrecomputedJudge` (replays orchestrated verdicts).
- `run.py` — `run_eval` + archive + `bless` + `claims` → `coyomap-eval run` / `claims` / `judge` / `bless`.
- `cli.py` — the `coyomap-eval <subcommand>` dispatcher.

Everything here is stdlib-only and reuses the validator's / audit's exact parse — one grammar, no drift.
Tests: `eval/tests/test_profile.py`, `test_compare.py`, `test_judge.py`, `test_run.py`.
