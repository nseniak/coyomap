# record writes the fragment it is named, harvest rows arrive whole, and a cut lint list prints whole

Change (2026-10-07, retro findings mcpolis-2026-10-07-5, -8 and -24): `coyomap record` refuses a
positional argument, an unknown option and a one-value flag given twice (exit 2, the positional's
refusal naming `--map`), and refuses to write an assembled map while the `build-fragments/` folder
beside it holds any fragment, naming the `extras.json` there (which that call seeds when it is
missing); `--no-reassemble` writes the map once nothing will assemble it again. Both `--replace`
batch refusals name the way out (`--remove`, then `--lines-from`). Every `coyomap record` example
in method.md and in `record --help` passes `--map .coyomap/build-fragments/extras.json`.
`assemble` drops a dep's harvest `not_an_interface` pointer (it opens "Not decided here") once
synthesis links the dep to a surface, and after a `--reconcile` it names the deps whose pointer is
still undecided, with a `fix row --fragments` route naming the folder the fragments were read from,
never one built from `--out`; it names `coyomap ship` only for a map written to a `.coyomap`
folder, the only one `ship` closes. The harvest contract's
`entry_points` field row gains `component`, and `lint-fragment` warns on a way in that names no
owning component. `lint-fragment --all` prints every list whole, and a cut list says so
· tools/coyomap/record.py, tools/coyomap/assemble.py, tools/coyomap/lint_fragment.py,
method/templates/harvest-contract.md, method.md.
On the 2026-10-07 mcpolis build: 1 of 39 `record` calls wrote the assembled map (turn 758), and
`ship`'s assemble discarded its line; `validate` blocked 7 deps (D4-D9, D12) on the pointer, and the
lead deleted it by hand; 51 of 221 harvested ways in had no owning component, and the lead filled 45
by hand; the lint named 3 of 10 long sentences, with no way to list the other 7.

Escalation: none on its own.

## Checks

1. expect: 0 `record` calls in the lead transcript write `.coyomap/project-map.json` once
   `build-fragments/` holds any fragment, the first record included (before it, no `extras.json`
   exists yet), and every line the transcript records is in the shipped map's extras.
   regression sign: a `record` call that exits 0 with "wrote .coyomap/project-map.json" during the
   build, a `--no-reassemble` before the build's last assemble, or a finalize row "carried (no
   escape)" for a line the transcript shows being recorded.
2. expect: a `record` call refused for a positional or for the assembled map is followed by the
   same call with `--map <the fragment>`.
   regression sign: a python or heredoc edit of `extras.json` or `project-map.json` right after
   such a refusal.
3. expect: 0 "names an interface AND says why it is none" problems on a dep whose
   `not_an_interface` opens "Not decided here" in the build's `validate` runs, and 0 hand edits that
   delete such a pointer from a dep. The same problem on a dep that states a real reason is a
   contradiction `validate` is meant to block for the lead to settle, not a regression.
   regression sign: that problem on a dep whose `not_an_interface` opens "Not decided here", or a
   build whose deps agent wrote pointers and whose assemble digest never prints "harvest interface
   pointers cleared".
4. expect: 0 deps in the shipped map whose `not_an_interface` opens "Not decided here" (2 on the
   2026-10-07 map: nginx and Caddy), and the folder each undecided-pointer note names after
   `fix row --fragments` is the folder the build's fragments are in.
   regression sign: a shipped dep that keeps the pointer after an assemble note named it, or a
   `fix row` the note named that fails with "not found".
5. expect: at most 5 harvested ways in reach the first assemble with no owning component (51 of 221
   on the 2026-10-07 build), and the lead writes `component` onto no way in by hand.
   regression sign: harvest hand-backs that quote the "way(s) in name no owning `component`"
   advisory while the rows stay unowned, a lead heredoc writing `component` onto harvested ways in,
   or reconcile `component` directives for more than 5 of them.
6. expect: when a `lint-fragment` advisory ends in `+N more`, the agent's next lint call that needs
   the rest passes `--all`.
   regression sign: a hand-written sentence splitter or word counter run after a cut long-sentence
   line.
7. expect: a refused `record --replace` batch is followed by a `--remove` call and then a
   `--lines-from` (or several `--line`) call.
   regression sign: two or more `--replace` refusals in a row, or a heredoc edit of the extras
   fragment after one.
