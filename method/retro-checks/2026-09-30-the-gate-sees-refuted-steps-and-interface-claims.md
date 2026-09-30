# The refutation gate sees a refuted walk step or interface claim, and reports it

Change (2026-09-30, retro finding mcpolis-2026-09-30-1): `resolve_claim` places walk steps, shared
sub-flow steps, a use case's sentence, a `theirs` interface's claim and a derived far side,
recomputing each from the same builder the worklist uses; the refutation gate, `settled_on_appeal`
and `by-element` therefore see them. A refuted claim of these kinds still in the map is REPORTED,
not blocking (`grounding.REPORT_ONLY_KINDS`), until the closer's ruling on disputed appeals is fixed
(retro finding 15) · tools/coyomap/audit_model.py, grounding.py, finalize.py.
On the 2026-09-30 mcpolis map 0 of 1,343 behaviour and 0 of 34 interface claims resolved, so the
gate block said "0 refuted claim(s) still in the map" while `grounding report` listed 3; on the
same map the fixed gate lists the 2 disputed steps (UC43 step 7, UC44 step 4) as reported, and
UC10 step 7 as settled on appeal.

Escalation: none on its own.

## Checks

1. expect: the shipped `finalize-report.md`'s `grounding refutations` leg counts refuted walk-step
   or interface claims still in the map, and that count equals the refuted-and-not-superseded
   steps and interface claims `grounding report` lists (0 is the goal).
   regression sign: the report lists such a claim and the gate says 0, the blindness this fixed.

2. expect: every refuted step the gate reports is either corrected before the commit, or its
   closer file rejects it (then it shows under "CLOSER REJECTED").
   regression sign: a refuted step shipped with no closer row and no correction.

3. expect: 0 blocking lines about a walk step or interface claim in the refutation leg.
   regression sign: one of those blocking the map before retro finding 15 has landed.
