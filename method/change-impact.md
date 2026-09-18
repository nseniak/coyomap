# Updating the map after the code changed

After the code changed, coyomap **updates the map** and writes the **change log**: what the product
now does differently, in entries that name the boxes they are about, with the map edits each entry
makes. The log is the product of the update; the updated map is what it leaves behind. The same skill
as building the baseline — read code → meaning — scoped to the diff, and bounded by tools that know
what the map already says.

## Lifecycle — one verb, seven steps, two documents

| Step | Action | Tool | Writes |
|---|---|---|---|
| **0 Gate** | the worktree must be clean; the log's folder must be committable; copy the map aside | `git status --porcelain -- . ':(exclude).coyomap'` must print nothing — an untracked product file refuses the update too: commit it or ignore it first. `git check-ignore -q .coyomap/changes/<from>-<to>.json` must FAIL (see the tracked-folder rule). Then `mkdir -p .coyomap/changes` | `.coyomap/changes/<from>-<to>.before.json`, a copy of the map as it is now (`check` reads it as `--old` at step 6). This copy and step 1's impact file both stay until step 7 is clean; neither is ever committed |
| **1 Touched** | which boxes the code change reaches | `coyomap impact --map .coyomap/project-map.json --json > .coyomap/changes/<from>-<to>.impact.json`, and read the text form too: a hit marked `*` is one the gate counts. Run it BEFORE step 2: it reads the links where the pin left them | the impact file, beside the log (deleted at step 7, never committed) |
| **2 Re-anchor** | move the code links whose lines only shifted | `coyomap reanchor --map .coyomap/project-map.json --write` | the map: the links, and the canonical rewrite may spell out a default field the map had left implicit. The links it lists as left behind are yours: each is re-pointed by a `where` edit in the entry that read that code (step 3) |
| **3 Read and write** | read the diff and the touched boxes; write the log | you | `.coyomap/changes/<from>-<to>.json` |
| **4 Lint** | the log fits the map | `coyomap changes lint <log> --map .coyomap/project-map.json` | nothing |
| **5 Gate** | the log explains every change it makes, before anything is written | `coyomap changes check <log> --map .coyomap/project-map.json --touched .coyomap/changes/<from>-<to>.impact.json` — the log applied to a copy of the map in memory | nothing. A gap sends you back to step 3, with the map untouched |
| **6 Apply** | the entries land in the map, the pin moves; then the same gate, on what was written | `coyomap changes apply <log> --map .coyomap/project-map.json --date <to-date>`, where the to-date is what `git log -1 --format=%cs <to>` prints; then `coyomap changes check <log> --old .coyomap/changes/<from>-<to>.before.json --new .coyomap/project-map.json --touched .coyomap/changes/<from>-<to>.impact.json` | the map (`commit` = the log's `to_commit`, `committed` = that commit's date) |
| **7 Close** | the invariant, the rendering, the record, the commit | render → validate → audit: `coyomap render … project-map.md`, then `coyomap validate --check-sources`, then `coyomap audit`; `coyomap changes render <log> --map … --out .coyomap/changes/<from>-<to>.md`; `coyomap preindex` when the map has one; `coyomap provenance stamp <repo> --mode accept`, which records this session and the new pin; delete the `.before.json` and `.impact.json` scratch files LAST, once validate is clean | the markdown view, the rendered log, the pre-index, `provenance.json`; **one commit** of map + log + views + pre-index + provenance, with a plain `git add` — never `git add -f` |

- **`update`** is the whole sequence. **`analyze`** is steps 0–5: the log written, linted and gated,
  the map's meaning untouched — its code links have moved (step 2), which is a change of no meaning
  — for a reader who wants the log before it lands. **`accept`** is steps 6–7 on a log that already
  exists; it finds the `.before.json` copy and the `.impact.json` file that steps 0 and 1 left
  beside the log.
- **From and to are commits.** `from` is the map's pin, `to` is `HEAD`. A dirty tree cannot be
  named, so step 0 refuses it: commit first, or stash. An untracked product file is refused the same
  way, because a file git does not know is a file no commit describes: commit it, or add it to
  `.gitignore`. (The old rule analyzed the working tree so an edit could be read before its commit;
  that preview is `git stash` away, and a log that names a commit is worth more than one that names
  a moment.)
- **`.coyomap/changes/` must be tracked.** The test, at step 0: `git check-ignore -q
  .coyomap/changes/<from>-<to>.json` must fail (exit 1: the path is not ignored). If it passes, the
  log would be left out of the commit without a word — a map whose files are tracked can still sit
  under an ignore rule for the whole folder, and the tracked files hide it. Fix the rule with the
  user before going on: git cannot re-include a path under an ignored folder, so a rule `.coyomap/`
  becomes `.coyomap/*` plus `!.coyomap/changes/`. Never `git add -f` around it: a forced add works
  once and leaves the next log ignored again.
- **The commit IS the acceptance.** Nothing else marks it; the map's pin and the log's `to_commit`
  agree, and the next update starts from there.

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
  the reading lands in the log: a link `reanchor` left behind is re-pointed by a `where` edit (on
  `flow:UC6`, key `steps[n=3].where`; on `BR168`, key `sites[0].where`) in the entry that read that
  code, so the move and its reason travel together. The log never carries a move `reanchor` made,
  and `check` ignores link-only changes.
- **Per change.** Classify a box as modified / added / removed; **ripple** by following its
  relations (arrows, flows, Happy Path steps). Verify by reading the changed code; a pure refactor
  or move with no behaviour change is a **waiver**, not an entry (keep noise down).
- **Resolution honesty.** Place a change at least at **component** level (which file → which
  component — always available). Sharpen to a record, a rule or a step where reading allows, and
  say the resolution reached, per change, in the log's `notes`; never fake step precision. An
  entry's `confidence` says something else — how sure the reading is — and is one of three words:
  `verified`, `likely`, `inferred`. For a widely-used helper the honest entry is "load-bearing,
  reaches these use cases", which is useful.
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

**What counts as a box for the rule.** Every row with an id; a keyed row under a synthetic id
(`glossary:<term>`, `run:<action>`, `config:<key>`, `deployment:<unit>`, `observability:<signal>`,
`net:<name>`); the map's own header under `map` (its `title`, `goal` and the other header fields —
an edit on `map` takes one such field as its key); an arrow, credited to the box it starts from.
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
`dump --id rule:BR168:0` (that rule's first site), `dump --id glossary:<term>`. `was` must equal
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
