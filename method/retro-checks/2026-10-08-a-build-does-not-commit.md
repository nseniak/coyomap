# A build ends with the map ready in `.coyomap/` and commits nothing

Change (2026-10-08, operator's decision): a build no longer runs `git add` or `git commit`. Keeping
the map in git is the operator's choice. Step 13 of the closing sequence is "stop: the map is
ready"; `finalize`'s closing line names the map's parts instead of printing a `git add -f` line;
`ship` ends with "the map is ready; the build does not commit it". `.coyomap/.gitignore` hides only
what is not part of the map: `build-fragments/` and `finalize-report.{json,md}` are no longer
ignored, and `assemble` strips those lines from an older file · method.md, method/dispatch.md,
skill/coyomap/SKILL.md, tools/coyomap/{assemble,finalize,ship,credentials,uncommitted}.py and their
tests. Updates (`/coyomap update`) still commit.

## Checks

1. expect: the build transcript has no `git add` and no `git commit` command run in the mapped repo,
   from the first turn to the last.
   regression sign: a `git add -f .coyomap/...` or `git commit` in the commit phase, which is what
   every build before this change ran (the 2026-10-08 mcpolis build force-added 75 findings files).

2. expect: `git status --porcelain .coyomap` in the mapped repo, after the build, lists the map,
   its `.md`, `preindex.json`, `provenance.json`, `verify/` and `build-fragments/` as changed or
   untracked, and lists no file under `findings/` and no `build-state.log`.
   regression sign: `build-fragments/` or `finalize-report.md` missing from that list while the
   files exist on disk (the map's `.gitignore` still hides them), or `findings/` listed (the
   `.gitignore` lost its scratch lines).

3. expect: `finalize`'s last run prints "the map is ready in <folder>" naming those parts, and the
   lead's closing report says the map is ready and was not committed.
   regression sign: the lead reports "committed" or asks the operator for permission to commit as
   if committing were the build's job.

4. expect: the L3 assertions that read the build's commit (12, and 18 to 22) read `n/a`, because
   there is no commit. That is expected, not a lost check: the same numbers are in
   `.coyomap/finalize-report.md` and `verify/gate-block.md`.
   regression sign: any of them scores a commit the build made.
