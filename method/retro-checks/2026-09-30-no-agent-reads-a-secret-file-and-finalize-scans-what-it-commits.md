# No agent reads a secret file, and finalize scans what its commit line force-adds

Change (2026-09-30, retro finding mcpolis-2026-09-30-6): the rule every brief carries
(`method/templates/repo-text-rule.md`) names the secret files no agent opens, prints, greps or
globs, and says to search named folders, never the repository root or a pattern that can reach a
secret file; `finalize` adds a BLOCKING `credential scan` leg over every file its `git add -f` line
would force-add (the map, its inputs, `verify/`, `build-fragments/`), matching vendor key shapes
only, naming the file, line and shape and never the value, and withholding the commit line on a
hit · tools/coyomap/credentials.py, finalize.py, contract.py, method/templates/repo-text-rule.md.
On the 2026-09-30 mcpolis build a skeptic's recursive search over the deployment config printed the
production API key into its transcript; the harness guard stopped 9 helpers' explicit reads of that
file and let the pattern through.

Escalation: if item 1 or item 3 fails, stop and tell the operator before anything is committed or
shared; do not run the eval.

## Checks

1. expect: 0 helper transcripts show a tool call whose command or path reaches a secret file
   (count only, never print a line: e.g. `grep -l 'prevent secret exposure'` over the helpers
   counts the ones the guard had to stop, which should also be 0).
   regression sign: any helper that the guard stopped, or any tool call with a recursive search
   rooted at the repository or a pattern ending in the secret-file prefix.

2. expect: the shipped `finalize-report.md` has a `credential scan` leg reading
   "scanned for credential shapes: 0 hit(s)" over the same number of files the commit line names.
   regression sign: the leg absent, or DID NOT RUN.

3. expect: 0 credential-shaped values in the committed `.coyomap/` (re-run the scan over the
   commit's tree).
   regression sign: a hit in a committed file, which means the leg was bypassed.

4. expect: every brief in the build's scratchpad carries "Some files are never read, and never
   searched."
   regression sign: a brief composed by hand without it.
