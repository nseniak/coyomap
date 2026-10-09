# Updating the map after the code changed

After the code changed, coyomap **updates the map** and writes the **change log**: what the product
now does differently, in entries that name the boxes they are about, with the map edits each entry
makes. The log is the product of the update; the updated map is what it leaves behind. The same skill
as building the baseline — read code → meaning — scoped to the diff, and bounded by tools that know
what the map already says.

## Lifecycle — one verb, nine steps, two documents

| Step | Action | Tool | Writes |
|---|---|---|---|
| **0 Gate** | the worktree must be clean; the log's folder must be committable; copy the map aside | `git status --porcelain -- . ':(exclude).coyomap'` must print nothing — an untracked product file refuses the update too: commit it or ignore it first. `git check-ignore -q .coyomap/changes/<from>-<to>.json` and `git check-ignore -q .coyomap/verify/claims-<from>-<to>-x.json` must both FAIL (see the tracked-folder rule). Then `mkdir -p .coyomap/changes && cp .coyomap/project-map.json .coyomap/changes/<from>-<to>.before.json` — the copy is what `challenge` and `ground` read as `--before`, so a typo in its name surfaces only after the wave was paid for | `.coyomap/changes/<from>-<to>.before.json`, a copy of the map as it is now (`check` reads it as `--old` at step 6). This copy and step 1's impact file both stay until step 7 is clean; neither is ever committed |
| **1 Touched** | which boxes the code change reaches | `coyomap impact --map .coyomap/project-map.json --json > .coyomap/changes/<from>-<to>.impact.json`, and read the text form too: a hit marked `*` is one the gate counts. Run it BEFORE step 2: it reads the links where the pin left them | the impact file, beside the log (deleted at step 7, never committed) |
| **2 Re-anchor** | move the code links whose lines only shifted | `coyomap reanchor --map .coyomap/project-map.json --write` | the map: the links, and the canonical rewrite may spell out a default field the map had left implicit. The links it lists as left behind are yours: each is re-pointed by an edit of that link (`where`, `source`, `cadence_source`…) in the entry that read that code (step 3) |
| **3 Read and write** | read the diff and the touched boxes; write the log. When an actor, a feature or a happy path step is added, removed or renamed, re-run the description review (Principles below) | you | `.coyomap/changes/<from>-<to>.json` |
| **4 Lint** | the log fits the map | `coyomap changes lint <log> --map .coyomap/project-map.json` | nothing |
| **5 Gate** | the log explains every change it makes, before anything is written | `coyomap changes check <log> --map .coyomap/project-map.json --touched .coyomap/changes/<from>-<to>.impact.json` — the log applied to a copy of the map in memory | nothing. A gap sends you back to step 3, with the map untouched |
| **5b Challenge** | the statements the update wrote, and the ones its change reached, re-argued by fresh-context skeptics — before anything is written | `coyomap changes challenge <log> --map .coyomap/project-map.json --before .coyomap/changes/<from>-<to>.before.json --touched .coyomap/changes/<from>-<to>.impact.json`, then ONE wave runner runs the whole wave: `coyomap contract wave --fill <slots.json> --out <brief> --brief <from>-<to>-wave` and one agent on the pointer it prints (Step 5b below says how to fill it). An upheld refutation amends the log and sends you back to step 4 | `.coyomap/changes/<from>-<to>.applied.json` (the copy the skeptics read) and `<from>-<to>.scope.json` (scratch, deleted at step 7); the wave's `claims-<from>-<to>-*.json` and `verdicts-<from>-<to>-*.json` under `.coyomap/verify/`, which stay: they are the map's warrant |
| **6 Apply** | the entries land in the map, the pin moves; the record is re-measured over the map as it now is; then the same gate, on what was written | `coyomap changes apply <log> --map .coyomap/project-map.json --date <to-date>`, where the to-date is what `git log -1 --format=%cs <to>` prints; then `coyomap changes ground <log> --map .coyomap/project-map.json --before … --touched … --note-file <note>` (its `--dry-run` first, for the facts the note quotes); then `coyomap changes check <log> --old .coyomap/changes/<from>-<to>.before.json --new .coyomap/project-map.json --touched .coyomap/changes/<from>-<to>.impact.json`, which now also refuses a map whose record does not describe it | the map (`commit` = the log's `to_commit`, `committed` = that commit's date, `grounding` re-pinned with one more row in its `history`); `.coyomap/verify/worklist.json` re-pinned, the old pin kept as `worklist-<from>.json`, the build's verdict rows carried or moved to `retired-<from>-<to>.json`; the log's `challenge` block |
| **7 Close** | the invariant, the rendering, the record, the commit | the refutation gate first: `coyomap grounding refutations --map .coyomap/project-map.json --verdicts .coyomap/verify/verdicts-*.json .coyomap/verify/closer-*.json` must exit 0; then render → validate → audit: `coyomap render … project-map.md`, then `coyomap validate --check-sources`, then `coyomap audit`; `coyomap changes render <log> --map … --out .coyomap/changes/<from>-<to>.md`; `coyomap preindex` when the map has one; `coyomap provenance stamp <repo> --mode accept`, which records this session and the new pin; `coyomap credentials .coyomap`, which must exit 0, since this commit carries `verify/` and `changes/` and no finalize scans them; delete the `.before.json`, `.impact.json`, `.applied.json` and `.scope.json` scratch files LAST, once validate is clean | the markdown view, the rendered log, the pre-index, `provenance.json`; **one commit** of map + log + views + pre-index + provenance + the `verify/` files the wave wrote or rewrote, with a plain `git add` — never `git add -f` |
| **8 Hand over** | the reader is told where to see what changed | `coyomap url --view updates --repo <repo> --json`, and `coyomap serve` when nothing is running (Step 8 below) | nothing |

- **`update`** is the whole sequence. **`analyze`** is steps 0–5b: the log written, linted, gated
  and argued with, the map's meaning untouched — its code links have moved (step 2), which is a
  change of no meaning — for a reader who wants the log before it lands. **`accept`** is steps 6–8
  on a log that already exists; it finds the `.before.json` copy, the `.impact.json` file and the
  wave's verdicts that steps 0, 1 and 5b left beside the log.
- **From and to are commits.** `from` is the map's pin, `to` is `HEAD`. A dirty tree cannot be
  named, so step 0 refuses it: commit first, or stash. An untracked product file is refused the same
  way, because a file git does not know is a file no commit describes: commit it, or add it to
  `.gitignore`. (The old rule analyzed the working tree so an edit could be read before its commit;
  that preview is `git stash` away, and a log that names a commit is worth more than one that names
  a moment.)
- **`.coyomap/changes/` and `.coyomap/verify/` must be tracked.** The test, at step 0: `git
  check-ignore -q .coyomap/changes/<from>-<to>.json` must fail (exit 1: the path is not ignored),
  and so must `git check-ignore -q .coyomap/verify/claims-<from>-<to>-x.json` — the wave writes
  new files under `verify/` (its batches, its verdicts, the retired rows, the old pin), and they
  are the map's warrant. If either passes, those files would be left out of the commit without a
  word — a map whose files are tracked can still sit under an ignore rule for the whole folder,
  and the tracked files hide it. Fix the rule with the user before going on: git cannot re-include
  a path under an ignored folder, so a rule `.coyomap/` becomes `.coyomap/*` plus
  `!.coyomap/changes/` and `!.coyomap/verify/`. Never `git add -f` around it: a forced add works
  once and leaves the next log ignored again.
- **The commit IS the acceptance.** Nothing else marks it; the map's pin and the log's `to_commit`
  agree, and the next update starts from there.

## Step 5b — the wave: an update is argued with, like a build

A build ends with fresh-context skeptics reading every statement the map makes against the code
(`method.md`, Phase 4). An update writes statements too — a rewritten sentence, a new rule site, a
waiver saying "the code moved and the meaning did not" — and until this step existed nobody read
them against the code, while the map's `grounding` record went on describing the build. The wave
closes that, and costs in proportion to the diff: only what the change touched is re-argued.

**What is in scope — the tool decides, never you.** `changes challenge` sorts every statement the
updated map makes into one bucket, and prints the count per bucket and per theme:

- **changed** — its words are new or rewritten. No earlier verdict can be about them.
- **touched** — its words stand, but the code touched one of its boxes: a hit the gate counts, or
  a box an entry names or a waiver covers. The earlier verdict was cast on code that has changed.
- **rippled** — its words stand, but the change reached one of its boxes through the map, one hop
  from a counted hit: a caller, a walk step, a rule site. The neighbour the verdict rested on moved.
- **carried** — nothing about it moved. Its verdict stands and it is NOT re-voted. A statement
  whose only change is a line number the re-anchor step moved is carried under its new text; the
  tool replays that step in memory on the map as it was, so the two never disagree about which
  links merely shifted. Measured on the dry run of 2026-09-15: 28 of the 206 statements in the
  eight shifted files would otherwise have been re-voted for nothing, 17 of them access statements
  that take three voters each.

Do not hand-pick a subset, and do not add "just this one" from the carried set: the scope is a
rule, and a rule is what makes the next reader able to trust it. If nothing is in scope the tool
says so, and `changes ground` re-pins and carries without a wave.

**The wave itself is Phase 4, scoped, and every rule of Phase 4 holds:** one fresh-context skeptic
per batch, the security theme three-voted with an odd count, the batches at ~40, the barrier
linted, the closer on every refutation, the note written from the printed facts.

**One wave runner runs it, never the lead.** `coyomap contract wave --slots`, filled with «MAP» the
applied copy, «PREFIX» the prefix `challenge` printed (`<from>-<to>-`, then `<from>-<to>-w2-`),
«VOTES» `security=3`, «AGENT_ID» that prefix plus `wave`, «CLOSER_ID» that prefix plus `closer`
(so the closer's file carries the update's name and counts with its wave), a new absolute «BRIEFS»
folder outside the repo, and «POOL» under your cap on running subagents. Then `--fill <slots>
--out <brief> --brief <AGENT_ID>`, and start ONE agent with the pointer it prints; it hands back
six lines. The runner runs items 2 and 3 below; you run them yourself only for a wave it hands back
INCOMPLETE, as the wave contract says. Measured: the mcpolis update of 2026-10-09 started 62
skeptics and a closer by hand, about 60 extra lead turns against the cap. The differences from a
build's wave:

1. **The map the skeptics read is the applied copy**, `.coyomap/changes/<from>-<to>.applied.json`:
   the log written into the map as it is, before anything on disk moves. Fill «MAP» with that
   path. A refutation then amends the LOG, and the map on disk is untouched.
2. **The batches sit beside the build's, under the wave's name:** `claims-<from>-<to>-<theme>.json`
   in `.coyomap/verify/`. The briefs come from `coyomap contract skeptic --from-batches
   .coyomap/verify --prefix <the prefix the challenge printed> --fill <slots.json> --out-dir
   <scratch>/briefs --votes security=3` — `<from>-<to>-` for the first wave, `<from>-<to>-w2-` for
   the next; without `--prefix` the generator writes a brief per BUILD batch too, and sends
   skeptics at claims settled months ago. The skeptic ids are the batch ids, so the verdict files
   land as `verdicts-<from>-<to>-<theme>.json`, beside the build's, and the barrier is `coyomap
   grounding lint --verdicts <each wave file> --expect <every SKEPTIC id the brief generator
   printed>` — the skeptic ids, not the batch ids: a three-voted batch `…-security` answers as
   `…-security-a`, `-b` and `-c`, and the batch id fails the barrier (measured: one failed run).
   Pass `--votes security=3` on EVERY `challenge` run, the second wave's included. A batch nobody
   answered is REPLACED by the next `challenge` run (its statements go out again under the new
   prefix); an answered batch is never rewritten.
3. **The closer reads this wave only:** `coyomap contract closer --from-verdicts .coyomap/verify
   --prefix <from>-<to>- --map <the applied copy> --fill <slots.json> --out <brief>`, its agent id
   `<from>-<to>-closer`, so its file is `closer-<from>-<to>-closer.json` and counts with the wave.
4. **An upheld refutation is a change to the log, not to the map.** Write the entry (or the edit,
   or drop the waiver) and go back to step 4: lint, gate, `changes challenge` again. The tool
   re-scopes; the statements the fix re-minted are the only new ones, and ONE more skeptic reads
   them — a second wave over the re-minted statements alone. There is no third: a fix that needs a
   third reading is a fix you have not understood, and the log's `notes` say so.
5. **Nothing is dropped and nothing is skipped.** `changes ground` refuses a batch with no verdicts
   file and an in-scope statement with no vote, in words, and writes nothing. There is no
   `--partial` here: an update that could not finish its wave has not finished, and an unattended
   run must fail loudly rather than re-pin a hole. A statement the BUILD never voted stays unvoted
   and is said to be: the update reads no THEME the build did not (mcpolis pinned 949 step phrases
   and voted none; they stay unvoted), and skips none it did. A map whose record says it was
   challenged but whose `verify/` holds no verdicts is refused too — the warrant files are missing,
   not absent — and a map with no record at all is left alone. `ground` may be run again, after a
   crash or by mistake: it measures against the list the update replaced, moves no citation twice,
   and keeps one ledger row per update.
6. **The note is the wave's, and the facts are printed for it.** `changes ground --dry-run` prints
   the `WAVE FACTS` of this wave — rows, distinct skeptic labels, the split, the multi-vote
   agreement, what was superseded and how many of those had been confirmed — and one `MAP-WIDE`
   line. Write the note from them, put it in a file, and pass `--note-file` (with `--dry-run` first,
   to have the draft checked). A note whose numbers contradict the wave is refused, exactly as a
   build's is; a note that cites the build's figures cites them as the build's.

**What `changes ground` leaves behind, and why each part is there.** The record's counts now
describe the map at its NEW pin: `claims_total` is every statement the map makes, `claims_challenged`
the ones with a verdict — carried or cast — and the digest is taken over the live surface, so
`validate` and the second `check` can see a map whose record does not describe it. One row is added
to `grounding.history`: what this wave re-argued, confirmed and refuted, what it carried and retired,
and why each statement was in scope. The first update seeds the ledger with the build's own row, so
the build's note and counts are never lost. `worklist.json` is re-pinned and the old pin kept under
the from-commit's name. The build's verdict rows are rewritten in place: a carried row keeps its
verdict, its claim re-keyed across a line shift (the text it was cast on stays in `claim_was`), its
cited line moved with the code (`evidence_was`); a row on a statement the wave re-voted or the map
no longer makes goes to `retired-<from>-<to>.json`, because an old confirmation and a new refutation
of one statement would otherwise tally as a tie and read as "unverifiable". The log gets a
`challenge` block with the same facts, which is what the Update log draws on each row.

**Analyze includes the wave.** A log handed to a reader before it lands is a log whose statements
have been argued with; `accept` then runs `ground` and the gates on verdicts that already exist.

## Step 8 — hand the reader the Update log

An update that ends at the commit ends with nothing to look at. The work of steps 3–6 is a story
about what changed, and the screen that tells it — the **Update log** — is one the reader has to go
and find. So close the way a build closes, on the same three answers, and **ask where the map is
served rather than spelling an address** (`method.md`'s closing section is the long form of why):

```
.venv/bin/coyomap url --view updates --repo <repo> --json
```

`updates` is the Update log itself, every update newest first — **never one update's own page**. A
reader who wants this update opens it from the list, and the list is also what says the update
landed at all.

- **`served`** — close with its `url`, verbatim:

  > **The map of `<project>` is up to date.**
  >
  > A viewer is already running. See what changed at `<url>`

- **`no-server`** — offer, and start it yourself on a yes (`<path>` is what the command printed,
  and 8765 is safe to name because no coyomap server holds a port):

  > **The map of `<project>` is up to date.**
  >
  > No viewer is running. Shall I start one? It stays up until you stop it, and serves every map you
  > have opened.
  >
  > Then what changed is at `http://127.0.0.1:8765<path>#v=updates`

  On a yes, start it detached, and never behind a `cd`:

  ```
  nohup .venv/bin/coyomap serve > /tmp/coyomap-serve.log 2>&1 &
  ```

  Then re-run the `url` command and give the reader the `url` it now prints, not the one you
  predicted.

- **`not-listed`** — a viewer is up but does not serve this folder. **Do not start a second one.**
  Print the command's own `note`: it names the port and what to add to it.

**Analyze stops before this.** It writes a log and lands nothing, so there is no update to look at;
its closing line is the log's own path, as before.

## Where the map lags, and how far

The map always describes one past commit, its **pin**. Between updates it lags the code on purpose,
and that lag is exactly what the next log describes. Cadence is yours: one update per commit gives
small logs; one per week gives one log with more entries. Either way every entry names the commits.

## Principles

- **Driven by BOTH.** The **diff drives** (bottom-up — what changed, what it reaches; this catches
  ADDED code that maps to no existing box). The **baseline guides** (anti-drift, consistent names;
  catches MODIFIED and REMOVED). Walking only the baseline would miss purely-additive changes, so
  the diff must be a driver, not just the guide.
- **Bounded, not blind.** `coyomap impact` is the list of boxes whose code links fall in the changed
  files, with the resolution each was found at. Only some of them count at the gate: a hit at LINE
  or SYMBOL resolution, and every link into a deleted file; the text marks those `*`. A hit at FILE
  resolution only says the file changed somewhere, so it is listed for reading and needs no waiver.
  Read the marked hits first, then the changed files they are not in. A marked box that no entry
  names or waives is a warning at steps 5 and 6; a box `impact` does not name that an entry claims
  is your own finding, and says so in the entry's evidence.
- **Line moves are not changes.** `coyomap reanchor` moves every link whose line only shifted, and
  lists the links into lines the code changed or files that are gone. Those are yours to read, and
  the reading lands in the log: a link `reanchor` left behind is re-pointed by an edit of that link
  (on `flow:UC6`, key `steps[n=3].where`; on `BR168`, key `sites[0].where`; on
  `edge:C15>calls>C13`, key `where`; on `EP22`, key `cadence_source`) in the entry that read that
  code, so the move and its reason travel together. The log never carries a move `reanchor` made,
  and `check` ignores link-only changes. **A left-behind link is never waived.** A waiver says the
  box's meaning did not change; it says nothing about the link, which still points at a line the
  code rewrote. No gate catches that until `validate` at step 7 — and only when the stale line
  happens to be a comment or a header: the first real update shipped two such links behind
  waivers. Re-point every link `reanchor` listed, or say in the entry why the old line still acts.
- **Waive the BOX, not the row `impact` marks.** `impact`'s text marks rows such as `step:UC6:4`
  or `edge:C15>calls>C13` with `*`; the gate counts them under the box that owns them (the use
  case, the arrow's source component, the rule). A waiver on a step or site row id is refused by
  `lint` ("not in the map"); name the owning box. An arrow is the exception: it is a row of the
  log (see "Addressing an edit"), so an entry or a waiver may name the arrow itself, and that
  covers the arrow's own hit without speaking for the rest of its source box. `impact --json`
  lists more rows at line or symbol resolution than the text marks, because a way in
  (`ep:<file>:<line>`) belongs to no box.
- **Per change.** Classify a box as modified / added / removed; **ripple** by following its
  relations (arrows, flows, Happy Path steps). Verify by reading the changed code; a pure refactor
  or move with no behaviour change is a **waiver**, not an entry (keep noise down).
- **Resolution honesty.** Place a change at least at **component** level (which file → which
  component — always available). Sharpen to a record, a rule or a step where reading allows, and
  say the resolution reached, per change, in the log's `notes`; never fake step precision. An
  entry's `confidence` says something else — how sure the reading is — and is one of three words:
  `verified`, `likely`, `inferred`. For a widely-used helper the honest entry is "load-bearing,
  reaches these use cases", which is useful.
- **The product description follows the product.** When an entry adds, removes or renames an
  actor, a feature or a happy path step, run the description review (method.md, under **Product
  description**) on the map as the log leaves it. Where an answer turns to no, the same entry, or
  one of its own, edits `map` with the key `goal`: the description is a box like any other.
- **Seam caveat.** Tracing callers statically breaks at interface / dependency-injection
  boundaries (callers hit a port, not the impl). Resolve the binding by reading the wiring, and put
  where reachability is incomplete in the log's `notes` rather than claim a clean closure.

## The log

One JSON file per update, `.coyomap/changes/<from>-<to>.json` (`from` and `to` are the two commits'
short shas), written by you at step 3 and read by four tools. Its shape:

```json
{
  "format": "coyomap-changes", "version": 1,
  "from_commit": "3a9e901", "to_commit": "1b77f52", "date": "2026-09-15",
  "entries": [
    {
      "id": "e1",
      "headline": "Removing or demoting the last admin is refused",
      "sentence": "A team can no longer be left with nobody who can manage it. The refusal happens in the store, inside the write lock, so two parallel calls cannot each see a surviving admin.",
      "elements": ["BR209", "BR168", "C19", "UC6", "UC7"],
      "edits": [{"id": "BR168", "key": "risk", "was": "…the old sentence…", "now": "…the new one…"}],
      "added": [{"kind": "rules", "row": {"id": "BR209", "name": "The last admin cannot be removed", "…": "…"}}],
      "removed": [],
      "evidence": ["backend/src/mcpolis/adapters/repositories/file_config_store.py"],
      "confidence": "verified"
    }
  ],
  "waived": [{"id": "C66", "why": "the screens gained a failure message; the map does not describe per-screen error display"}],
  "notes": "Resolution reached per change, gaps, seams — the honesty footer."
}
```

**The two-way rule.** Every entry names at least one box in `elements`, and every box an entry
edits, adds or removes is among its `elements`. Every box the map's own diff says changed (wording
or structure) is named by an entry or covered by a waiver. `lint` enforces the first half against
the map the log is written for — and runs the whole apply on a copy through the loader and the
validator's blocking checks, so a row of an older shape is refused before any write; `check`
enforces the second half twice: at step 5 on that same copy, before anything is written, and at
step 6 on the map before and after `apply`. A gap at step 5 sends you back to step 3 — write the
entry, or waive with a `why` — and costs nothing else: the map on disk has not moved, so lint and
the gate simply run again. Step 6's check should find nothing step 5 did not; if it does, the map on
disk is not the one the log was gated on.

**A problem the map had before the log.** `lint` validates the map the log leaves behind, so it
also refuses a problem the map already had: an update must leave a map that validates, whoever
broke it. Lint says so at the front of the line: `the map would not validate after apply, and did
not before this log either: …`. Nothing in your entries caused it. Clear it in the log like any
other change, with an entry that names the box and edits the field. Two shipped maps meet one at
their next update: a dependency whose reason is still the harvest's pointer, `D11 (nginx) still
gives the harvest pointer ('Not decided here …')` (mcpolis: D11 and D13; reminderrepo: D32 and
D33). Decide it: if it is no surface, an entry naming `D11` makes the edit

```json
{"id": "D11", "key": "not_an_interface", "was": "Not decided here. nginx fronts every web surface, …", "now": "A proxy in front of the product's own surfaces, with none of its own."}
```

where `was` is the field exactly as `coyomap dump --record D11` prints it. If it belongs to a
surface, the entry sets `interfaces` (`"was": [], "now": ["I1"]`) and removes the pointer
(`"key": "not_an_interface"`, `"now": null`). The problem also names `coyomap fix row --fragments
…`: that is the way during a build, and it edits fragments an update never reads.

**What counts as a box for the rule.** Every row with an id; a keyed row under a synthetic id
(`glossary:<term>`, `run:<action>`, `config:<key>`, `deployment:<unit>`, `observability:<signal>`,
`net:<name>`); the map's own header under `map` (its `title`, `goal` and the other header fields —
an edit on `map` takes one such field as its key); an arrow under `edge:<src>><verb>><dst>`,
credited to the box it starts from, so an entry or a waiver naming either the arrow or that box
explains it.
Outside the rule, because they carry no identity: `tests` and `extras` rows (added as whole rows,
never edited), and the code-link moves.

**What an entry says.** The `headline` is one line of at most 14 words, in product words: the words
a card wears on the Update log (`lint` counts them). The `sentence` says what a user can now do or
no longer do — or, for a box under the hood, what the machine now does differently. Both face the
map's readability check (under 20 words a sentence, no code words). `elements` are ids; the viewer
draws them by name, as the pills of the entry's card on the update's page, under each feature the
boxes belong to, so nothing else is authored for the screen.

**The map is a snapshot; its history is the log.** The words an entry writes INTO the map — an
edit's `now`, an added row — describe the product as it is, as if it had always been so. "Now",
"no longer", "since the last-admin rule", "before", "previously", "any more" belong to the entry's
`sentence`, never to the map: a reader of the map a year on must not meet the story of one change
in a box's own words. Write the box as a stranger to the change would read it: *Only the screens
hold this back, so a direct call still gets through; the store refuses the call that would leave
the team without an admin.* `lint` warns on those words in the new text.

**Addressing an edit.** `id` names the box; `key` is a path inside its row: `risk`,
`sites[0].where`, `fields[name=size].type`, `steps[n=4].phrase`. A use case's flow is the row
`flow:<UC id>` (an edit on it is an edit on the use case, which the entry names); a shared sub-flow's
steps are on its own row. `coyomap dump --id <UC id>` shows a flow's steps and their numbers, and
the log's own addresses resolve the same way: `dump --id flow:UC6`, `dump --id step:UC6:3`,
`dump --id rule:BR168:0` (that rule's first site), `dump --id glossary:<term>`, `dump --id
edge:C15>calls>C13` (one arrow). An arrow's address is its source, verb and target, so an edit may
re-point its `where` or reword its `why`, and an arrow that became false goes in `removed` by that
id; its `src`, `verb` and `dst` ARE the address, and an edit of one is refused: remove the arrow
and add the new one, whole, in `added` (kind `edges`). Two arrows that share all three (`validate`
warns on the pair) go by number, `edge:C15>calls>C13#1` and `#2`, in map order; the bare id then
names neither and `lint` says which numbers do. `was` must equal
what the map holds — `lint` refuses a stale `was`, since applying it would overwrite a change
someone else made; one field is edited by one entry, and the log's `from_commit` must be the map's
pin. `now: null` removes the field or the list item. Every address is read in the frame of the
map as it was, whatever order the entries come in: removing `sites[0]` in one entry never shifts
what `sites[1].why` names in another. Two edits whose targets nest — a whole list and one of its
items, a dict and a field in it, one item under two spellings, an item and the removal that takes
it out — are refused at `lint`, since one would land and vanish or land on the wrong words. To
add a list item, address the position one past the end with `was: null` and the whole item as
`now`: `sites[2]` on a rule with two sites appends a third, `sites[3]` after it a fourth, and
`sites[5]` on it is refused. A row
this log adds is written whole — never added and then edited; a row an entry removes is edited by
no other. The new words face the map's readability check at `lint` (under 20 words a sentence, no
em dash, no code word), as advice — every sentence an added row carries too, through the same
field walk `validate` reads at step 7. Never a JSON pointer with an array index into the whole map:
those break the moment a row above moves.

**A new box** goes in `added` as its whole row, id included, in the array it belongs to, in the
shape the map holds today (`coyomap dump --record <a sibling>` shows it). Its id is the next number
after the highest of its kind in the map — `BR209` when the last rule is `BR208`, `EP210` after
`EP209`; `coyomap dump --legend` lists every id. A new use case brings its flow as a second added
row (`kind: flows`, keyed by `uc`); a keyed row brings its key. A box that is gone goes in
`removed` by id. **A box the code touched without changing its meaning** goes in `waived` with its
`why`; the code-link moves `reanchor` made need no mention at all. Two dates: the log's `date` is
the day it was written; `committed` in the map is the to-commit's date, which `apply --date` sets.

## Deliberately out of scope (for now)

- **Cross-map linking.** Each repo keeps its own baseline; a repo of repos is a later step.
- **Automatic updates.** The update is asked for, never run by a hook: a log is a reading, and a
  reading has a reader.
- **Re-running tests.** An update reads code; it does not run it. A green run is a claim the log can
  quote from the repo's own record, never one it makes.
- **A full re-vote.** The wave re-argues what the change reached, one hop through the map, and
  carries the rest. A carried verdict is one cast on code that has not changed since; how much of
  the map rests on carried verdicts is a number the record now shows (`grounding.history`), and a
  rule that re-votes the whole map when that share thins is a later decision, made on that number.
