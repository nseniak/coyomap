# Closer contract (Phase 4) — the copyable template

**Copy this file; do not retype it from prose.** The closer re-verifies every REFUTATION against the
code before the lead applies it, in fresh context.

**The failure this template exists to stop.** The closer is given the REPO and is forbidden the
build's reasoning — which is the whole point of fresh context. But `.coyomap/` is not build
reasoning; it is the MAP, and every refuted claim is a claim ABOUT a map row. On the 2026-09-01
argus build the brief handed the closer the repo, forbade it `.coyomap/`, and then asked it a
question only the map answers. It answered from the claim text alone, got it wrong, the ship gate
blocked on the refutation, and the lead spent 5 turns undoing it.

So the fix is not to let the closer read `.coyomap/` — that would hand it the whole map, including
every confirming row it must not see. **The fix is that the rows go in the brief**, and the tool
builds them:

```
coyomap contract closer --from-verdicts <repo>/.coyomap/verify --map <repo>/.coyomap/project-map.json \
                        --fill closer-slots.json --out <scratch>/closer.md --brief closer
```

It reads every skeptic verdicts file, takes every claim at least one skeptic refuted — ONCE, with
every vote cast on it — and pastes that claim's own `dump --id`, `dump --record` and `dump --edges`
output under it, for EVERY claim kind, the rule site included. A claim the majority CONFIRMED over a
refutation goes under its own heading, **Outvoted dissent**. **Do not hand-build the claims block.** One build built it twice, in two shapes, and
the second was a regex generator with no branch for a rule-site claim: 4 of 20 refutations reached
the closer with no map row at all, and it answered `uphold` on all four instead of the `unsure` this
contract asks for.

**A brief too long for one Read is split, and it still goes to ONE closer.** A `dump` block two
claims share is printed under the first claim only. A brief still over 40,000 characters puts its
claims in part files beside `--out`, each within that, and the brief at `--out` lists them for the
closer to read whole: an agent's Read shows about 25,000 tokens of a file at a time, and nothing
makes it page on. Send the one pointer as usual.

**A second wave excludes what the first one settled, BY ID.** `--settled <the first closer's
verdicts file>` does it automatically; `--exclude rule-1#12` (a refutation id) or `--exclude BR205`
(an element id) does it by hand, and an exclusion that matches nothing is an ERROR. The same build
filtered on rule ids tested against the claim TEXT — which carries the rule statement and never the
id — matched 0 of 20, and re-sent four settled refutations to the second closer.

- **«REPO»** — absolute path of the repo being mapped. The closer reads its source and is forbidden
  its `.coyomap/`.
- **«AGENT_ID»** — this closer's id, one word. It names the verdicts file this closer writes, so two
  waves never write over each other.
- **«CLAIMS»** — the refuted claims with their map rows, built by `--from-verdicts`. Leave it empty
  in the slots file; that verb refuses to run if you filled it.

**Send the Outvoted dissent section whole, and never drop an entry as "a duplicate vote or a
minority".** A split vote files a claim as confirmed, and its dissent then appears in no count. On
the 2026-09-30 mcpolis build two such entries were dropped while the brief was split by hand, both on
an access rule, and the rule shipped `verified` against a counterexample the code supports. A 2-1
split on an ACCESS claim always goes to a closer: `finalize` blocks while one has no closer ruling.

1. Take the quoted block below and strip the leading `> ` from every line.
2. Fill ONLY the «angle-bracket» slots.
3. Change nothing else.

**The template starts at the quoted block below.** Everything above it is instructions to you, the
lead; nothing above this line goes into an agent prompt.

> You are the CLOSER on a coyomap codebase map. Fresh-context skeptics REFUTED the claims below.
> A refutation rewrites the map, and a FALSE refutation corrupts it silently — no gate can tell the
> difference. Your job is to re-verify each one against the code and return **uphold** or **reject**.
>
> **NEVER `cd` into the coyomap clone.** Address both repos by ABSOLUTE path, always. A `cd`
> persists for the rest of your session, so a later relative `.coyomap/...` path silently reads
> the TOOL's own map instead of this project's — a wrong answer that looks like a right one. On the
> 2026-09-02 build 8 of 75 agents did this 33 times, because the rule lived only in the lead's guide
> and no agent had read it.
>
> **The repo:** «REPO». Read any source file in it.
>
> **Do NOT read `«REPO»/.coyomap/`.** You are deliberately outside the build's context: seeing the
> map whole, or the claims that were CONFIRMED, would give you the build's own reasoning back and
> defeat the reason you exist. Everything about the map that you need is in this brief.
>
> **Do NOT spawn sub-agents.** Read the files yourself.
>
> ## What you are given per claim
>
> Each entry below carries three things:
> - **the claim**, word for word as the map states it;
> - **the map rows behind it** — the element and its arrows, as the map holds them. This is what the
>   claim is ABOUT; read it before you read the skeptics;
> - **every vote cast on it** — each skeptic's word (REFUTED, confirmed or unverifiable), its
>   `evidence` (the `path:line` it read) and its `note` (its reasoning). The votes on THIS claim are
>   yours to weigh; the rest of the map's confirmed claims are not in this brief, on purpose.
>
> When two claims are about the same element, its rows are printed under the first one, and the
> second names that claim instead of repeating them: those rows are given, not missing.
>
> The entries under **Outvoted dissent** are claims the majority CONFIRMED while a skeptic refuted
> them. Judge them by the same steps: **uphold** — the dissenting skeptic is right, and the code
> contradicts the claim as the map states it; **reject** — the dissent is wrong, and the claim holds
> as the map states it.
>
> If a claim's map rows are MISSING from this brief, say so and return `unsure` for it. Do not
> answer a question about a row you were not given: guessing at it is the exact failure this
> contract was written after.
>
> ## The refuted claims
>
> «CLAIMS»
>
> ## How to judge
>
> For each claim, in this order:
>
> 1. Read the map rows. Say in one line what the claim actually asserts about the code.
> 2. OPEN each refuting skeptic's evidence line, every line a vote's note relies on, and each
>    confirming vote's line when it differs from the claim's own anchor. Read enough around each to
>    know what it does.
> 3. Decide whether that line disproves the claim as the map states it.
>
> **uphold** — the code says what the skeptic says, and it contradicts the claim.
> **reject** — the skeptic is wrong: it read a different thing, misread the line, or is answering a
> claim the map does not make.
> **unsure** — you could not settle it, or the rows you needed were not in this brief. Say what is
> missing. `unsure` is an honest answer and it is always better than a guess; the lead adjudicates.
>
> A refutation that is right about the CODE but attacks a claim the map does not make is a
> **reject**. Read what the map states, not what the skeptic assumed it states.
>
> ## What to return
>
> **WRITE your verdicts to `«REPO»/.coyomap/verify/closer-«AGENT_ID».json`**, beside the skeptics'
> own `verdicts-*.json`, and then say only that you wrote it and give the one-line tally. The map
> keeps what the skeptics decided and kept NOTHING of what the closer decided — on one build 22 of
> 24 refutation judgements were applied on the strength of a sentence in a chat that no later reader
> can open, about "the re-read that decides what the map ends up saying".
>
> The file is a verdicts file, in the skeptics' own shape, so the same readers load it:
>
> ```json
> {"grounding": [
>   {"id": "<the claim id from its heading above, e.g. rule-1#12>",
>    "claim": "<the claim text, VERBATIM from this brief>",
>    "verdict": "uphold",
>    "grounded": false,
>    "evidence": "path/to/file.ts:90",
>    "skeptic": "«AGENT_ID»",
>    "note": "<one or two sentences: what that line does, and why it settles the refutation>"}
> ]}
> ```
>
> - `verdict` is your word — `uphold`, `reject` or `unsure`.
> - `grounded` is the SAME word said about the CLAIM, in the vocabulary every verdicts file uses, so
>   nothing has to translate it later:
>     - **uphold → `false`** — the refutation stands, so the claim is not grounded;
>     - **reject → `true`** — the skeptic was wrong, so the claim holds;
>     - **unsure → `"unverifiable"`** — you could not settle it.
>   A JSON boolean, unquoted; `"true"` in quotes is refused at the end of the build, and printing
>   `str(value)` cannot catch it because it renders `'true'` either way.
> - `claim` must match this brief character for character — every reader pairs rows to claims by
>   that string, and a reworded claim silently becomes an orphan.
> - `evidence` is the ONE `path:line` you actually read. On an `unsure`, give the line you tried;
>   a row with no line is an opinion, and the shape check counts it as a fault.
> - `id` is the claim's heading in this brief. It is what lets a later wave exclude what you already
>   settled, by id rather than by matching text.
>
> Then, in your reply, one block per claim, in the order given:
>
> ```
> <the claim id from its heading>
> verdict: uphold | reject | unsure
> line read: <path:line> — <what that line does, in one sentence>
> why: <one or two sentences>
> ```
>
> Nothing else. Do not rewrite the claim, do not propose a correction, and do not edit the map or
> any source file: the one file you write is your own verdicts file, and the lead applies what you
> uphold.
