# The retro replays the build's own finalize arguments, and gives each reader its own folder

Change (2026-10-08, round 2, retro findings mcpolis-2026-10-08-#14 and #22): `eval/retro/method.md`
Step 1b tells the retro to copy the build's LAST finalize command (the line `ship` prints, indented
four spaces, or the command `--commands` lists for a hand run), drop `--emit-gate-block`, and add
`--no-write` and `--lead-transcript`; it says the build-state log tells when the last run was, not
its arguments. The slice-reader brief gives each reader, and each agent reader, refuter and report
reader, its own folder under `.coyomap-eval/retro/<ts>/work/<reader id>/` · eval/retro/method.md,
eval/tests/test_retro_method.py.
On the 2026-10-08 mcpolis retro a bare finalize printed 20 advisories against the build's 26, and
two slice readers overwrote each other's `slice.txt` in the shared scratchpad.

## Checks

1. expect: the retro's Step 1b finalize prints the same advisory count as the build's last
   finalize, and the report says which build run it matched.
   regression sign: a retro finalize whose advisory count differs from the build's own with no
   reason given, or a command line without `--verdicts` or `--access-baseline` on a build that
   passed them.

2. expect: the retro's `.coyomap/verify/gate-block.md` is unchanged by the retro (same modification
   time as at the build's commit).
   regression sign: a gate block rewritten during the retro, which means `--emit-gate-block` was
   copied along.

3. expect: every retro sub-agent's scratch files sit in its own folder under `work/`, and no reader
   reports another reader's file in its place.
   regression sign: a reader's note that a scratch file was overwritten, or two readers writing one
   file name outside their folders.

## Review fix (2026-10-08)

`ship` prints each step's command quoted for the shell (`shlex.join`), so a copied line with a
space in a path runs as printed · tools/coyomap/ship.py, tests/test_ship.py.

- expect: the retro's replayed finalize line runs without hand edits.
  regression sign: a retro that re-quotes a path from `ship`'s printed step line by hand.
