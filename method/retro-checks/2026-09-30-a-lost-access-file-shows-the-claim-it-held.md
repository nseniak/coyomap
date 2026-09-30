# A lost access file is shown with the claim it held, and an excuse nobody read is counted

Change (2026-09-30, retro finding mcpolis-2026-09-30-2): `finalize`'s access-baseline leg lists
each file that lost its access claim WITH the claim it held in the previous map (the rule id, its
statement, and each site's line and why); `coyomap record` echoes that claim when a path is recorded
under "Access baseline exceptions"; and the leg adds an advisory counting the excused paths the
lead's own transcript never shows it opening (`--lead-transcript`, default this session's
`$CLAUDE_CODE_SESSION_ID` file) · tools/coyomap/finalize.py, access_surface.py, record.py,
records.py, provenance.py, grounding.py, eval/retro/method.md.
On the 2026-09-30 mcpolis build the leg named 17 paths with no claims; the lead opened none of them
and recorded 11 reasons, 5 of which answered a different claim, and four old access rules (team
scoping of every stored record among them) left the map.

Escalation: if item 3 fails, run the eval before accepting the map.

## Checks

1. expect: when the build's `finalize-report.md` carries the access-baseline finding, every path
   it lists is followed by `held BRn "<statement>"`.
   regression sign: a listed path with no `held` clause, or the leg absent from a build whose repo
   has `.coyomap/dev-rebuilds/`.

2. expect: every `coyomap record --heading "Access baseline exceptions"` call in the lead
   transcript prints one `<path> held, in NNNN/project-map.json: …` line per recorded path.
   regression sign: a record call with no `held` line, or "no archived map beside this one" on a
   repo that has an archive.

3. expect: the shipped report carries no `excused without being opened` advisory, and
   `finalize --no-write --lead-transcript <the build's session .jsonl>` run by the retro counts 0
   paths excused without being opened.
   regression sign: that advisory in the shipped report, or a count above 0 in the retro's re-run.

4. expect: read against the `held` text, at most 1 of the lines recorded under "Access baseline
   exceptions" answers a different claim than the one its path held.
   regression sign: whys that describe the NEW map's rules instead of the lost claim (the
   2026-09-30 build: 5 of 11).
