# The map is written whole, and the rules and tests agents read it after the gap-fill lands

Change (2026-09-30, retro finding mcpolis-2026-09-30-32): `assemble` writes `project-map.json` and
`project-map.md` through a temporary file and one rename; method.md says the rules and tests agents
read the map assembled with the gap-fill's fragment, not a copy · tools/coyomap/assemble.py,
method.md.
On the 2026-09-30 mcpolis build the lead handed its rules and tests agents a copy of the map, taken
before the gap-fill landed: both worked from a map missing 121 of 143 gap-fill edges.

Escalation: none on its own.

## Checks

1. expect: the rules and tests briefs' «MAP» is `<repo>/.coyomap/project-map.json`, and the lead
   transcript assembles with the gap-fill fragment before dispatching them.
   regression sign: a «MAP» pointing at a copy in the scratchpad, or the dispatch before the
   gap-fill's fragment exists.

2. expect: 0 of the gap-fill's edges are missing from the map the rules and tests agents read (the
   edges named in the gap-fill fragment appear in the map at their dispatch).
   regression sign: gap-fill edges absent from what they read (the 2026-09-30 build: 121 of 143).

3. expect: 0 `.project-map.json.*.tmp` files left in `.coyomap/` after the build.
   regression sign: a leftover temporary file, which means an assemble died mid-write.

4. expect: `project-map.json` and `project-map.md` carry the permissions an ordinary write gives
   (`-rw-r--r--` under the usual umask), or the ones they had before the build.
   regression sign: `-rw-------` on a file that was not made private by hand (the first whole-file
   writer left them readable by their owner only).
