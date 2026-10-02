# A call between two parts of the product takes no door

Change (2026-10-02): `method.md` (Doors) and `method/templates/doors-contract.md` gain the clause
"a call between two parts of the product is NOT a crossing, even when it reaches one of our own
addresses", with its test: who stands at the surface in this story. `trace-contract.md` narrows "A
door counts" to "A step FROM a door counts". `validate` and `lint-fragment` (given the map with
`--ids`) gain the advisory "Doors nobody stands at", with no recorded-line escape.

Escalation: if check 2 fails, the clause is stripping right doors; revert the clause before the
next build and keep the advisory, which never fires on those stories.

## What this change is answering

The 2026-09-30 mcpolis build drew its live smoke test (UC53), a script an operator runs, reaching
the dashboard's backend addresses through the Dashboard door 5 times and the gateway through the
Gateway door once. Nobody stands at either surface in that story. The 5 dashboard doors drew 2
lines on the Architecture picture that no code takes, and the lead silenced the 5 skipped-screen
warnings they raised with "the smoke test calls the backend directly, with no page".

Partial runs on 2026-10-02 showed the old wording does not force the doors: 1 fresh agent with the
old brief drew UC53 straight too. So the clause removes an ambiguity, and the advisory is what
stops a repeat.

## Checks

1. expect: mcpolis UC53 has no step from the smoke test into the Dashboard or the Gateway, and
   `validate` prints no "Doors nobody stands at" line naming UC53.
   regression sign: that line names UC53, or the map carries a recorded line quoting it.
2. expect: mcpolis UC29 and UC37 keep the sign-in exchange with the person's AI client: at least
   one step from the organization check into the Gateway (UC29) or the Admin MCP (UC37) while the
   person stands there. 5 of 6 partial-run agents drew it in UC29: 2 of 3 with the first new
   wording, 3 of 3 with the old.
   regression sign: both stories lose every step from a part of ours into their surface except the
   final answer.
3. expect: reminderrepo's deploy, monitor and setup stories (UC27, UC30, UC31) reach the service
   health check part directly.
   regression sign: `validate` names UC27 step 10, UC30 step 4 or UC31 step 13.
4. expect: files written to a map folder keep their doors (coyomap UC8, UC2, UC3 write to their
   file surface with nobody drawn reading).
   regression sign: those stories lose their steps into the file surface.
