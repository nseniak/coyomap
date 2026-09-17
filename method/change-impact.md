# Updating the map after the code changed

After the code changed, coyomap **updates the map** and writes the **change log**: what the product
now does differently, in entries that name the boxes they are about, with the map edits each entry
makes. The log is the product of the update; the updated map is what it leaves behind. The same skill
as building the baseline — read code → meaning — scoped to the diff, and bounded by tools that know
what the map already says.

## Lifecycle — one verb, seven steps, two documents

| Step | Action | Tool | Writes |
|---|---|---|---|
| **0 Gate** | the worktree must be clean; copy the map aside | `git status --porcelain -- . ':(exclude).coyomap'` must print nothing | `.coyomap/changes/<from>-<to>.before.json`, a copy of the map as it is now (`check` reads it as `--old`; deleted at step 7, never committed) |
| **1 Touched** | which boxes the code change reaches | `coyomap impact --map .coyomap/project-map.json --json > .coyomap/changes/<from>-<to>.impact.json` | the impact file, beside the log (deleted at step 7, never committed) |
| **2 Re-anchor** | move the code links whose lines only shifted | `coyomap reanchor --map .coyomap/project-map.json --write` | the map: the links, and the canonical rewrite may spell out a default field the map had left implicit |
| **3 Read and write** | read the diff and the touched boxes; write the log | you | `.coyomap/changes/<from>-<to>.json` |
| **4 Lint** | the log fits the map | `coyomap changes lint <log> --map .coyomap/project-map.json` | nothing |
| **5 Apply** | the entries land in the map, the pin moves | `coyomap changes apply <log> --map .coyomap/project-map.json --date <to-date>`, where the to-date is what `git log -1 --format=%cs <to>` prints | the map (`commit` = the log's `to_commit`, `committed` = that commit's date) |
| **6 Check** | the gate: the log explains every change the map's own diff shows | `coyomap changes check <log> --old .coyomap/changes/<from>-<to>.before.json --new .coyomap/project-map.json --touched .coyomap/changes/<from>-<to>.impact.json` | nothing |
| **7 Close** | the invariant, the rendering, the commit | validate → audit → render; `coyomap changes render <log> --map … --out .coyomap/changes/<from>-<to>.md`; `coyomap preindex` when the map has one; delete the `.before.json` and `.impact.json` scratch files | the markdown view, the rendered log, the pre-index; **one commit** of map + log + views |

- **`update`** is the whole sequence. **`analyze`** is steps 0–4: the log written and linted, the
  map's meaning untouched — its code links have moved (step 2), which is a change of no meaning —
  for a reader who wants the log before it lands. **`accept`** is steps 5–7 on a log that already
  exists; it finds the `.before.json` copy step 0 left beside the log.
- **From and to are commits.** `from` is the map's pin, `to` is `HEAD`. A dirty tree cannot be
  named, so step 0 refuses it: commit first, or stash. (The old rule analyzed the working tree so an
  edit could be read before its commit; that preview is `git stash` away, and a log that names a
  commit is worth more than one that names a moment.)
- **`.coyomap/changes/` must be tracked.** A repo whose `.gitignore` covers the whole `.coyomap/`
  folder cannot commit the log; say so at step 0 and fix the ignore rule with the user before going on.
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
  files, with the resolution each was found at. Read those first, and the changed files they are
  not in. A box it names that no entry names or waives is a warning at step 6; a box it does not
  name that an entry claims is your own finding, and says so in the entry's evidence.
- **Line moves are not changes.** `coyomap reanchor` moves every link whose line only shifted, and
  lists the links into lines the code changed or files that are gone — those are yours to read. The
  log never carries a line move, and `check` ignores link-only changes.
- **Per change.** Classify a box as modified / added / removed; **ripple** by following its
  relations (arrows, flows, Happy Path steps). Verify by reading the changed code; a pure refactor
  or move with no behaviour change is a **waiver**, not an entry (keep noise down).
- **Resolution honesty.** Place a change at least at **component** level (which file → which
  component — always available). Sharpen to a record, a rule or a step where reading allows, and
  say the resolution reached in the entry's `confidence`; never fake step precision. For a
  widely-used helper the honest entry is "load-bearing, reaches these use cases", which is useful.
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
enforces the second half against the map before and after `apply`. A gap at `check` sends you back
to step 3: write the entry, or waive with a `why`.

**What counts as a box for the rule.** Every row with an id; a keyed row under a synthetic id
(`glossary:<term>`, `run:<action>`, `config:<key>`, `deployment:<unit>`, `observability:<signal>`,
`net:<name>`); the map's own header under `map` (its `title`, `goal` and the other header fields —
an edit on `map` takes one such field as its key); an arrow, credited to the box it starts from.
Outside the rule, because they carry no identity: `tests` and `extras` rows (added as whole rows,
never edited), and the code-link moves.

**What an entry says.** The `headline` is one line in product words, the words a card wears on the
Changes tab. The `sentence` says what a user can now do or no longer do — or, for a box under the
hood, what the machine now does differently. Both face the map's readability check (under 20 words
a sentence, no code words). `elements` are ids; the viewer draws them by name, under Product or
Under the hood by their kind, so the two views are derived from this list and nothing else is
authored for them.

**Addressing an edit.** `id` names the box; `key` is a path inside its row: `risk`, `sites[0].where`,
`fields[name=size].type`, `steps[n=4].phrase`. A use case's flow is the row `flow:<UC id>` (an edit
on it is an edit on the use case, which the entry names); a shared sub-flow's steps are on its own
row. `was` must equal what the map holds — `lint` refuses a stale `was`, since applying it would
overwrite a change someone else made; one field is edited by one entry, and the log's
`from_commit` must be the map's pin. `now: null` removes the field or the list item; an entry's
removals land after its other edits, from the highest index down, so removing `sites[0]` never
shifts what `sites[1].why` names. A row this log adds is written whole — never added and then
edited; a row an entry removes is edited by no other. The new words face the map's readability
check at `lint` (under 20 words a sentence, no em dash, no code word), as advice. Never a JSON
pointer with an array index into the whole map: those break the moment a row above moves.

**A new box** goes in `added` as its whole row, id included, in the array it belongs to, in the
shape the map holds today (`coyomap dump --id <a sibling>` shows it); a new use case brings its
flow as a second added row (`kind: flows`, keyed by `uc`); a keyed row brings its key. A box that
is gone goes in `removed` by id. **A box the code touched without changing its meaning** goes in
`waived` with its `why`; the code-link moves `reanchor` made need no mention at all. Two dates:
the log's `date` is the day it was written; `committed` in the map is the to-commit's date, which
`apply --date` sets.

## Deliberately out of scope (for now)

- **Cross-map linking.** Each repo keeps its own baseline; a repo of repos is a later step.
- **Automatic updates.** The update is asked for, never run by a hook: a log is a reading, and a
  reading has a reader.
- **Re-running tests.** An update reads code; it does not run it. A green run is a claim the log can
  quote from the repo's own record, never one it makes.
