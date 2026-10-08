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
