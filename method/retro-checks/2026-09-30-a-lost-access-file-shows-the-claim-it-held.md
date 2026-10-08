# A lost access file is shown with the claim it held, and an excuse nobody read is counted

Change (2026-09-30, retro finding mcpolis-2026-09-30-2): `finalize`'s access-baseline leg lists
each file that lost its access claim WITH the claim it held in the previous map (the rule id, its
statement, and each site's line and why); `coyomap record` echoes that claim when a path is recorded
under "Access baseline exceptions"; and the leg adds an advisory counting the excused paths the
lead's own transcript never shows it opening (`--lead-transcript`, default this session's
`$CLAUDE_CODE_SESSION_ID` file) · tools/coyomap/finalize.py, access_surface.py, record.py,
records.py, provenance.py, grounding.py, eval/retro/method.md.
On the 2026-09-30 mcpolis build the leg named 17 paths with no claims; the lead recorded 11 reasons,
8 of them for files it never opened (re-counted after the review: an earlier count cut each command
at its first `>` and missed 2 reads), 5 of the 11 answered a different claim, and four old access
rules (team scoping of every stored record among them) left the map.

Amended 2026-10-08 (retro finding mcpolis-2026-10-08-#1): the old claim's TEXT is no longer
shown. It arrived after the last wave, and the 2026-10-08 build copied 3 old rules from it into
the map with no vote. Each path is now listed with its lines only; items 1, 2 and 4 are reworded
to match. See `2026-10-08-a-rule-written-after-the-last-wave-ships-only-with-a-vote.md`.

Escalation: if item 3 fails, run the eval before accepting the map.

## Checks

1. expect: when the build's `finalize-report.md` carries the access-baseline finding, every path
   it lists is followed by its lines, `(line N)` or `(lines N, M)`, and nothing else.
   regression sign: a listed path followed by `held BRn "<statement>"`, or the leg absent from a
   build whose repo has `.coyomap/dev-rebuilds/`.

2. expect: every `coyomap record --heading "Access baseline exceptions"` call in the lead
   transcript prints one `<path> (lines …) held access in NNNN/project-map.json` line per
   recorded path.
   regression sign: a record call with no such line, or "no archived map beside this one" on a
   repo that has an archive.

3. expect: the shipped report carries no `excused without being opened` advisory, and
   `finalize --no-write --lead-transcript <the build's session .jsonl>` run by the retro counts 0
   paths excused without being opened.
   regression sign: that advisory in the shipped report, or a count above 0 in the retro's re-run.

4. expect: read against the code at the listed lines, at most 1 of the lines recorded under
   "Access baseline exceptions" says something the code there does not do.
   regression sign: whys that describe the NEW map's rules instead of the code at those lines
   (the 2026-09-30 build: 5 of 11).
