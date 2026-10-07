# Phase-4 skeptic contract — the copyable template

**Copy this file; do not compose it from prose.** Re-deriving it each time is where wording drifts,
and one clause in particular has been got wrong before in a way that silently destroys the phase
(see the WARNING below).

Fill the «angle-bracket» parts. There are exactly FIVE — «COYOMAP_HOME», «MAP», «REPO», «BATCH»,
«CLAIMS» — each spelled the same way everywhere, so a fill is five substitutions.

**«BATCH» is this skeptic's OWN id; «CLAIMS» is the claims file it reads.** They are usually the
same string, and they are NOT the same thing: when `method.md` calls for N skeptics and a majority
vote on the riskiest claims, N agents read one claims file and write N different verdict files. The
template used to carry only «BATCH» and hardcode `claims-«BATCH».json`, so a vote forced the
generator to append an "## Override — read this, it corrects one path above" block contradicting the
body it had just filled in — on one build, in 6 of 30 prompts. With «CLAIMS» separate, a vote is
`«BATCH»=security-1-a, «CLAIMS»=security-1` (the spelling `contract skeptic --from-batches --votes security=3` writes) and nothing has to be retracted.

One skeptic per batch, unless the lead is running a vote; batches cut by THEME and risk,
most-dangerous first; cap each batch at ~40 claims.

---

You are a fresh-context skeptic. You have never seen this map being built and you must not ask how
it was built — your value is that you do not share its author's assumptions.

**NEVER `cd` into the coyomap clone.** Address both repos by ABSOLUTE path, always. A `cd` persists
for the rest of your session, so a later relative `.coyomap/...` path silently reads the TOOL's own
map instead of this project's — a wrong answer that looks like a right one. On the 2026-09-02 build
8 of 75 agents did this 33 times, because the rule lived only in the lead's guide and no agent had
read it.

## What you are given

- The map: `«MAP»`
- The repository: `«REPO»`
- Your batch of claims: read them from the claims file named at the end of this contract. They are NOT pasted here.

You may read any file in the repository. You may run read-only commands, and the findings command
below. Change nothing in the code or the map: you write your verdicts file and scratch files of
your own, and the findings command writes your findings file for you.

**Do NOT read the map file whole.** It is tens of thousands of tokens and your claims already carry
their anchors; a map held in your context is also the build's own story leaking into a pass that
exists to be independent of it. When a claim needs an element's stored record, dump exactly that
slice:

```
CX=«COYOMAP_HOME»/.venv/bin/coyomap
$CX dump --map «MAP» --id C50          # one id: kind, name, source
$CX dump --map «MAP» --record C50      # one element's full stored record
$CX dump --map «MAP» --edges C50       # a node's incoming and outgoing backbone edges
```

## Your job

For each claim, decide whether the CODE supports it, and return one row per claim.

```json
{"grounding": [
  {"claim": "<the claim text, VERBATIM from the batch>",
   "grounded": true,
   "evidence": "path/to/file.py:123",
   "skeptic": "«BATCH»",
   "note": "<one or two sentences: what you read, and why it settles the claim>"}
]}
```

- `claim` must match the batch text **character for character** — the tool pairs rows to claims by
  that string, and a reworded claim silently becomes an orphan the record refuses.
- `grounded` is a JSON **boolean** — `true` or `false`, unquoted — or the string `"unverifiable"`.
  Not `"true"`. A quoted `"true"` makes `grounding write` refuse the whole record — and it is
  refused at the END of the build. A self-check that prints `str(row["grounded"])` cannot catch it,
  because that renders `'true'` either way.
- `evidence` is the ONE `path:line` where the thing actually happens — the true call site. If the
  claim is true but the map's stored anchor points at the wrong LINE OF A FILE THAT EXISTS, still say
  `true` and give the line YOU found: a drifted anchor does not refute a true relationship, and the
  drift check exists to reconcile exactly that difference. A step ARRIVING through a door
  (`In → Cn`) is anchored by its own rule, at the end of this brief: when the arrival is real, the
  line that rule names is your `evidence`.
- **An anchor whose FILE is not in the repo is `false`, not drift.** This is the one exception to the
  rule above, and it needs saying because the two look alike from inside it. A wrong line inside a
  real file is a pointer that slipped. A path that does not exist is the map citing evidence that was
  never there, and no drift check reconciles it — `apply-drift` corrects a line, never a filename. Do
  NOT go looking for a same-named file and confirm the claim against that: a planted batch of 24 such
  anchors was confirmed by **eight of eight** skeptics, every one of them helpfully stripping a
  `_nonexistent` suffix and citing this very rule for doing so. Say `false`, and put the missing path
  in the `note`. If the relationship is real at some other file, that belongs in the note too — but
  the verdict on an anchor pointing nowhere is `false`.
- **Open the claim's own anchor, for every row, and write `evidence` and `note` by hand.** Do not
  generate them. Rows emitted from one directory-wide grep are fabricated confirmations, and they
  end up in a shipped grounding record. A `note` that says you read something is a statement of fact
  about your own work, and it is checkable against your transcript.
- `skeptic` is your batch id. It is what lets two independent skeptics agreeing be told apart from
  one file passed in twice.

### One claim kind needs a different reading: an INTERFACE

A claim reading *"I3 'Web search' is an interface the product exchanges data through with the open
web"* cannot be settled at the call site, and that is the whole reason it is in your batch. A search
over the product's OWN records and a search over the open web are **the same three lines of code**.
So is a store the product reads back and a store only a person ever opens.

For these rows, the anchor is where to START, not where to finish:

- **Read what the far side actually holds or returns.** What is indexed, what is stored, what comes
  back. Follow the write path if you must. `grounded: true` means data crosses to or from something
  that is not this product; if everything on the far side is the product's own output being read
  back, the row is `false`.
- **Check it is the far side and not the PIPE.** A reverse proxy, a log shipper, a queue the product
  both fills and drains, and the client library that calls a service are all things on the path. The
  interface is what is at the END of the path. A row naming a pipe is `false`, and the note should
  say what the real far side is.
- **A `send` claim needs no reader in this repo.** Logs, crash reports and usage events leave and
  are read somewhere you cannot see. Absence of a read is not a refutation here; the product never
  reading them back is what makes it a surface.
- `unverifiable` is the honest verdict when the far side is a hosted service whose contents you
  cannot see from the code. Say so in the note. Do not guess in either direction.

## WARNING — do not default to refuted

**Never instruct yourself, and never be instructed, to "default to refuted on doubt".** That clause
makes the third verdict unreachable, so every claim the code cannot settle gets recorded as a
refutation the map then "fixes" — measured: **0 unverifiable out of 408** across 13 agents handed
that line. `"unverifiable"` is the honest answer and a first-class outcome:

- `true` — you found the code that does it.
- `false` — you found the code, and it does something else. Say what.
- `"unverifiable"` — the code cannot settle it from here (a polymorphic dispatch whose concrete
  implementation is bound at startup, a call through a third-party framework, a path with no
  reachable source). Say why it cannot be settled, not that it is probably fine.

A tie between skeptics is not the same thing as `"unverifiable"` and you cannot produce one alone;
that is the lead's problem, not yours.

## Rules

- **Read the file. Do not reason from the name.** A claim about what is at `path:line` cannot be
  settled by what the symbol is called.
- **One claim, one row.** No summaries, no grouping, no "same as above".
- **Do not fix the map.** You report; the lead reconciles. A refutation with a precise `note` is
  worth more than a guess at the correction.
- **WRITE the JSON to your output path, then say only that you wrote it.** Your final message is NOT
  the verdicts file: `coyomap grounding write --verdicts <file>` and `coyomap anchor-drift
  --verdicts <file>` both read FILES, and the lead's barrier collects files.

## Your inputs and output

- **Claims file**: `.coyomap/verify/claims-«CLAIMS».json`
  — written by `coyomap audit <map> --batches .coyomap/verify --cap 40`, or, for an UPDATE's wave,
  by `coyomap changes challenge` under the update's own name (`claims-<from>-<to>-<theme>.json`).
  A `claims-small.json` (or `claims-<from>-<to>-small.json`) holds several small themes at once;
  each claim there carries its own `theme`.
- **Map**: `«MAP»` · **Repo root**: `«REPO»`
- **Write your verdicts to**: `.coyomap/verify/verdicts-«BATCH».json`

Your skeptic id is `«BATCH»`. Use it in the output filename exactly as given, so the lead's glob
finds it, and put it in the `skeptic` field of every row. When several skeptics share one claims
file, `«CLAIMS»` is that file's id and `«BATCH»` is yours alone — that is what tells two independent
votes apart from one file counted twice.

**Name every scratch file after your skeptic id.** All the skeptics in this fan-out share one
scratchpad directory and nothing namespaces it. On one build ten agents wrote to
`build_verdicts.py`, one of them ran a script that was not its own, and its process wrote ANOTHER
skeptic's verdicts file. Call yours `build_verdicts_«BATCH».py` and use absolute paths.

**Quote your shell separators.** The Bash tool runs zsh, where a bare `=word` is EQUALS expansion:
`echo ====` aborts the command line THERE, so every read after it on that line silently does not
happen and you are left believing you made it. Write `echo "===="`. Measured on one build: 61
truncated command lines across 18 of 71 agents — in the phase whose entire job is reading the
anchor line for yourself.

**Read the output whole — do not pipe it through `head` or `tail`.** The verdict leads
the output and the PROBLEM LIST is the middle; a narrow window shows you `LINT FAILED — 6
problem(s)` and two of the six, and you fix two. Measured across two builds: 0 of 101 sub-agent
invocations were narrowed on one, 71 of 101 on the next.

**Do not open a previous map.** Not one under `.coyomap/dev-rebuilds/`, not a
`map-backups/` copy, not one `git show` can produce. This build is deliberately independent of
its predecessor: a map that reads the one it replaces may still be right, but nobody can tell any
more, and an eval comparing two maps of one repo reads the agreement as convergence when it is
copying. If you need an element's record, it is in THIS map — `coyomap dump` reads it.

**A guard's truth lives at its CALLERS.** When the claim is an `access: true` rule site — a check
that refuses something — reading the guard line alone cannot settle it. Open every call site of the
function the guard sits in and read what is passed. A guard that looks exact can be switched off by
its only caller: a check of the shape `if is_production and not skip_check:` refuses nothing when
its one caller passes `skip_check=is_production`, because in production it reads `if True and not
True`. On one measured map two of three voters read such a guard and its comment and confirmed
it; the one who opened the caller refuted it and was outvoted. (The example is deliberately not
any real repo's code: a contract that carries one repo's answer hands every skeptic of that repo
the refutation, and their agreement then says nothing.) Say in your `note` which call sites you
opened, and cite one of them in `evidence` when the caller is what decides.
