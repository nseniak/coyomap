# The claims added after the pin get a second wave, and grounding write folds it into the pin

Change (2026-09-30, retro finding mcpolis-2026-09-30-4): `coyomap audit <map> --batches <verify>
--since <pinned worklist>` cuts only the claims the map carries that the pin never held, as
`claims-added-*.json`; `grounding write --map` folds verdicts on those claims into the pin (keeping
the first pin as `verify/worklist-wave1.json`) instead of refusing them; `grounding report` buckets
and marks them; `ship` passes their verdict files to `grounding write`; validate's live-coverage
and claim-loss advisories name this route and no longer prescribe a fresh `audit --json` re-pin;
method.md describes it · tools/coyomap/audit_model.py, grounding.py, ship.py, validate_model.py,
method.md.
On the 2026-09-30 mcpolis build 68 claims shipped with no verdict (14 of them re-worded confirmed
claims, 6 of those sites of access rules BR1 and BR21); the re-pin the advisory prescribed was
refused on 67 claims. A replay of the new route on that map took live claims with a verdict from
2,254 to 2,322 of 2,322.

Escalation: none on its own.

## Checks

1. expect: the shipped map's `grounding.claims_added_since` is 0, or the grounding note names the
   claims added since the pin and says why they were not challenged.
   regression sign: a count above 0 with a note that does not mention it.

2. expect: when claims were added after the pin, `verify/` holds `claims-added-*.json` batches, a
   `verdicts-added-*.json` file answering each, and `worklist-wave1.json` beside the re-pinned
   `worklist.json`.
   regression sign: added claims with no second-wave batch, a batch with no verdicts file, or a
   hand-edited `worklist.json` with no `worklist-wave1.json` beside it.

3. expect: 0 `grounding write` refusals reading "are not in the pinned worklist" in the lead
   transcript after the second wave landed.
   regression sign: that refusal, followed by a hand-merged worklist or a note-only escape.

4. expect: every refutation cast in the second wave is reconciled (corrected, dropped, or rejected
   by a closer) before the commit, exactly as a first-wave one.
   regression sign: a second-wave refuted claim the shipped map still makes word for word.
