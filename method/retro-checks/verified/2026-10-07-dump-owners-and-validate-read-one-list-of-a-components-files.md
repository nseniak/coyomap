# dump --owners, validate and the viewer read one list of the files a component holds

Change (2026-10-07, merge 5.1): `validate_model.component_files` is the one answer to "which files
does a component hold": its `files` only, a folder entry dropped, a `:line` suffix stripped. The
rule layer (`component_file_owners`), `coyomap dump --owners` and the viewer's file switcher read
it. `dump --owners` no longer counts a component's `source`, which is where a component lives, and
prints each file as that list spells it (`./x` stays `./x`); the switcher still opens `source`
first, as display order · tools/coyomap/validate_model.py, tools/coyomap/dump.py,
tools/coyomap/views.py.
On the 2026-10-07 mcpolis map one answer changed: `dump --owners` for
`backend/src/mcpolis/entrypoints/app.py`, or any tail of it, named C23 and C24 and now names C23
alone. C24 "MCP door guards" lives at `app.py:354` and lists only its middleware files, and its 6
steps anchored in `app.py` (UC21:5, UC25:4, UC58:4 at line 356; UC44:3, UC45:3, UC45:10 at line
690) are the only 6 of 806 anchored component steps whose `where` is outside their own component's
`files`.

Escalation: none on its own.

## Checks

1. expect: every flow step a trace or gap-fill agent writes from a component sits in a file that
   component lists in `files` (6 of 806 anchored component steps did not on 2026-10-07, all C24
   at `app.py`).
   regression sign: a step whose `src` component does not list its `where` file, written by an
   agent whose transcript shows a `dump --owners` call on that file.
2. expect: for any file a retro asks `dump --owners` about, the components it names are the ones
   `validate` gives a rule site in that file (the viewer's rule page shows the same ones).
   regression sign: `dump --owners` naming a component whose `files` does not list the file, or a
   component in the viewer's rule site list that `dump --owners` leaves out for that file.

verified in mcpolis build of 2026-10-08 05:44 (map c0be7daa, tool 5103046)
