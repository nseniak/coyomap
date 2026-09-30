# A rule re-worded after the vote is not called "never challenged"

Change (2026-09-30, retro finding mcpolis-2026-09-30-38): `grounding refutations` reads the pinned
worklist beside the map and pairs a vote cast on an OLDER wording of a rule to that rule when the
pin names the same element and the same line; `finalize` then says the access rule "was re-worded
after the vote", with how many of its sites the older votes cover, instead of "never challenged" ·
tools/coyomap/grounding.py, tools/coyomap/finalize.py, tools/coyomap/audit_model.py.
On the 2026-09-30 mcpolis map finalize told the commit that BR1 and BR21 "were never challenged",
while all 11 of their current sites carried 3 votes each under the wording before a reconcile
corrected it. Re-run on that map with the fix: 2 → 0 "never challenged" lines, and the two rules
read "5 of 5" and "6 of 6 site(s) voted under the older wording".

Escalation: none on its own.

## Checks

1. expect: every access rule the finalize report calls "never challenged" has no vote in the
   verdict files on any claim the pinned worklist names for that rule.
   regression sign: a rule called "never challenged" while the pin holds a voted claim for it at
   one of its current lines.

2. expect: every access rule the report calls "re-worded after the vote" has a voted claim in the
   pin for that rule at one of its current lines, and that claim differs from the rule's claim
   today.
   regression sign: a rule called re-worded whose only older vote the pin names for another rule
   or another line.

3. expect: with fix 4's second wave run, 0 access rules are called either.
   regression sign: a re-worded access rule in the report while `worklist-wave1.json` exists (the
   second wave ran and left it out).
