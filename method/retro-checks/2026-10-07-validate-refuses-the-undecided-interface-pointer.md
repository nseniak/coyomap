# validate refuses a dep whose reason is still the harvest's "Not decided here" pointer

Change (2026-10-07, merge 5.5, after retro finding mcpolis-2026-10-07-8): the test for the harvest
pointer moved from `assemble` to `grammar.is_interface_pointer`, and the list of deps whose pointer
names no surface to `validate_model.undecided_interface_pointers`; `assemble` reads both from
there. Once a map records its interfaces, `validate` blocks each such dep with "<Dn> (<name>) still
gives the harvest pointer ('Not decided here …') as the reason it is no interface", and names the
two decisions, each the way a build makes it (`fix row --fragments`) and the way an update makes it
(a change-log edit of `not_an_interface`). `changes lint` opens a refusal the map already had with
"the map would not validate after apply, and did not before this log either", and
method/change-impact.md says how an update clears it (review of 2026-10-07, F1). The condition
advisory ("Steps where a business rule decides say no condition …") names the update's way too, a
change-log edit of `steps[n=…].note` ·
tools/coyomap/grammar.py, tools/coyomap/validate_model.py, tools/coyomap/assemble.py,
tools/coyomap/changelog.py, method/change-impact.md.
On the 2026-10-07 mcpolis map the check names exactly the 2 deps that shipped the pointer, D11
(nginx) and D13 (Caddy), and the plain `validate` of that map goes from exit 0 to exit 1. So does
the reminderrepo map, for D32 and D33: `changes lint` refuses any log for either map, an empty one
too, until its update decides those deps, and a log whose one entry edits the two fields lints clean.

Escalation: none on its own.

## Checks

1. expect: every dep that a post-synthesis assemble note lists as still carrying the pointer is
   named by the next `validate` with "still gives the harvest pointer", and the shipped map holds 0
   such deps (2 shipped on 2026-10-07: nginx and Caddy).
   regression sign: a shipped dep whose `not_an_interface` opens "Not decided here" while the
   build's last `validate` exits 0, or an assemble note naming a dep the `validate` after it does
   not name.
2. expect: each dep that problem names is decided in the turns after it, by a reconcile
   `interfaces` entry or a `fix row --set-not-an-interface` call whose reason does not open "Not
   decided here".
   regression sign: the pointer swapped for another placeholder ("Undecided", "TBD", "see
   synthesis"), or the same dep named by 3 or more `validate` runs in a row.
3. expect: 0 "still gives the harvest pointer" problems in `validate` runs on a map with no
   `interfaces` rows yet.
   regression sign: that problem on a map whose synthesis has not written a surface (the check
   fired before anyone could decide the dep).
4. expect: the first update of a map that shipped the pointer (mcpolis: D11 and D13; reminderrepo:
   D32 and D33) decides each such dep in its change log, by an entry that edits its
   `not_an_interface` or its `interfaces`, and the update's lint refuses no log for that dep after
   that entry exists.
   regression sign: a `fix row --fragments` or `fix step-notes --fragments` call made during an
   update, the map's `not_an_interface` edited by hand or by `python3`, or an update that stopped at
   lint on "did not before this log either" without writing the entry.
