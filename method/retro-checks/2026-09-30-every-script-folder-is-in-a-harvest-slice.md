# Every folder a person runs a command from is in a harvest slice, tests included

Change (2026-09-30, retro finding mcpolis-2026-09-30-22): `coyomap contract harvest --from-slots`
names, on stderr, every in-scope script (a shell script, a file opening with `#!`, a Python file
with a `__main__` guard) that no slice's FILES covers; method.md says the slices cover every folder a
person runs a command from, tests included · tools/coyomap/contract.py, method.md.
On the 2026-09-30 mcpolis build no slice covered `backend/tests/integration/`: the orphan-sandbox
lister (a way in on the previous map) and 3 run scripts left the map while it recorded `cli:
complete`. Run over that build's 16 harvest slots, the check names 15 scripts, those four among them.

Escalation: if item 2 fails, re-run the partial run of the harvest step before accepting the map.

## Checks

1. expect: the lead runs `contract harvest --from-slots` (the batch form), and either its last run
   printed no "script(s) … are in no harvest slice" warning or the 'Entry-point coverage' line of
   each named script's kind says why that script is no way in.
   regression sign: the warning printed and nothing answered, harvest briefs filled one by one with
   `--fill` so the check never ran, or slots changed after the first run while the old briefs were
   dispatched (the batch form never rewrites a brief).

2. expect: the map has at least 1 row (a way in or a run command) whose source is the orphan-sandbox
   lister (`list_orphan_sandboxes.py` or its run script).
   regression sign: 0 such rows while the map records `cli: complete`.

3. expect: `Entry-point coverage` says `complete` for a kind only when no script of that kind sits
   outside every slice.
   regression sign: a `complete` line beside a script the warning named.
