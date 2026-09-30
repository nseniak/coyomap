# One rule says where a door arrival is anchored, and every brief and check reads it

Change (2026-09-30, retro finding mcpolis-2026-09-30-25): `method/templates/door-anchor-rule.md`
states where a step arriving through a door (`In → Cn`) is anchored — the source line of the way in
it comes through, even a handler's definition — and `contract` appends it once to every doors,
trace and skeptic brief (shared rules are now composed once per brief, so a trace-plus-doors brief
also carries the repository-text rule once); the doors, trace and skeptic contracts point at it; the
operative-line check (`validate`, `lint-fragment`, `anchor-drift`) accepts an arrival on its way
in's own line, and a fragment check leaves an arrival through a door it cannot see to `validate` ·
method/templates/door-anchor-rule.md, doors-contract.md, trace-contract.md, skeptic-contract.md,
tools/coyomap/contract.py, validate_model.py, lint_fragment.py.
On the 2026-09-30 mcpolis build 8 arrival anchors were moved by hand at the barrier (ways in with
run evidence fell 8 → 5 of 32), and 51 confirmed door steps shipped at a line their skeptic had
replaced, 42 of them in another file.

Escalation: none on its own.

## Checks

1. expect: 0 operative-line warnings on a step arriving through a door whose anchor is its way
   in's own source (validate `--check-sources`, lint-fragment).
   regression sign: such a warning, or a lead hand-moving arrival anchors after one.

2. expect: the probe "confirmed step claims whose skeptic evidence drifts beyond tolerance" counts
   fewer than 20 door steps (the 2026-09-30 build: 51).
   regression sign: 40 or more, most of them arrivals whose evidence is the handler body line.

3. expect: the ways in with `run` evidence do not fall between the trace barrier and the ship.
   regression sign: a fall like 8 → 5 of 32, the trace of arrivals moved off their way-in lines.
