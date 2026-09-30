# A deciding step is one a rule site sits on, and its condition is written after the rules fan-out

Change (2026-09-30, retro finding mcpolis-2026-09-30-14): `validate`'s "Steps where a business rule
decides say no condition" advisory and the pictures' rule mark count EXACT links only (a rule site on
the step's own line), not links through the enclosing function; `coyomap fix step-notes` writes a
walk step's note (`UC5:3`, `SF10:2`) in the fragment that wrote the walk; method.md sequences the
conditions after the rules fan-out · tools/coyomap/validate_model.py, views.py, fix.py, method.md.
On the 2026-09-30 mcpolis map the advisory listed 166 steps, 147 of them function links (19 exact),
and the mark sat on 486 steps (127 marks on the Architecture pictures); with exact links it is 95
steps and 37 marks.

Escalation: none on its own.

## Checks

1. expect: the shipped map's condition advisory lists 0 steps, or only steps recorded under
   "Condition exceptions" (it lists 19 on the 2026-09-30 map with this rule).
   regression sign: 10 or more deciding steps with an empty note shipped.

2. expect: the lead transcript runs `coyomap fix step-notes` (or the tracers wrote every condition)
   after the rules fan-out is assembled, and 0 hand scripts edit a step's `note`.
   regression sign: a `python3 - <<` edit of `flows[].steps[].note`, or a `--set-json-steps` of a
   whole sub-flow to change one note.

3. expect: every step carrying the rule mark in the viewer has a rule site on its own line.
   regression sign: a mark on a step whose line holds no rule site (the enclosing-function link).
