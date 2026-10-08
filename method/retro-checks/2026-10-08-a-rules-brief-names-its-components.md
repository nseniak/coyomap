# A rules brief names the components its block starts from

Change (2026-10-08, round 2, retro finding mcpolis-2026-10-08-#12): the rules contract has a
seventh slot, «COMPONENTS»: the `Cn` / `Sn` ids whose code makes the block's decisions. The brief
puts them beside the `dump --members` / `--record` / `--edges` commands it tells the agent to start
from, and `contract rules --fill` refuses a value with no `Cn` or `Sn` id in it. method.md's T7
step lists the ids among what each rules agent gets ·
method/templates/rules-contract.md, tools/coyomap/contract.py, method.md, tests/test_contract.py.

## Checks

1. expect: every rules brief of the build carries a «COMPONENTS» value naming at least one `Cn` or
   `Sn` id.
   regression sign: a rules slots file filled with a block name or a sentence, refused, and then
   filled with every component id of the map to get past the refusal.
2. expect: most rules agents run `dump --members`, `--record` or `--edges` on ids from their
   brief's list (0 of 11 ran `--members` or `--edges` on 2026-10-08).
   regression sign: still 0 agents running them, or agents reading the map file whole.

## Review fix (2026-10-08)

The «COMPONENTS» check took `S3` in "AWS S3" or `C2` in "Phase C2" as an id. An id right after a
capitalised word that is no id itself is now part of a name, so such a slot is refused ·
tools/coyomap/contract.py, tests/test_contract.py.

3. expect: no rules brief's «COMPONENTS» line holds only a service or product name.
   regression sign: a rules brief whose «COMPONENTS» line is a name like "AWS S3" and no id.
