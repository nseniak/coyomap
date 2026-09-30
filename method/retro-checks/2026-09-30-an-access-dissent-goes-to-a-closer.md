# A claim reaches the closer once with every vote, and an access dissent always goes to a closer

Change (2026-09-30, retro finding mcpolis-2026-09-30-3): `contract closer --from-verdicts` carries
each refuted claim ONCE with every vote cast on it (the confirming votes on that claim included),
and puts the claims the majority confirmed over a refutation under their own **Outvoted dissent**
heading; the refutation gate counts an upheld dissent as a surviving refutation and BLOCKS on an
access claim confirmed over a dissent that no closer ruled on (`grounding refutations`,
`finalize`); method.md and the closer contract say a 2-1 split on an access claim always goes to a
closer · tools/coyomap/contract.py, grounding.py, finalize.py, method.md,
method/templates/closer-contract.md.
On the 2026-09-30 mcpolis build BR23's sites at `dashboard_auth.py:375` and `:383` were confirmed
2-1; the lead dropped both dissent rows from a 77-entry, 589 KB brief as "duplicate votes or
minority", and the rule shipped `verified` against a counterexample the code supports.

Escalation: if item 3 fails, run the eval before accepting the map.

## Checks

1. expect: the closer brief(s) in the build's scratchpad carry each refuted claim once (entries
   equal distinct refuted claims) and an `## Outvoted dissent` section whenever a claim was
   confirmed over a refutation.
   regression sign: one claim under two headings, or a split vote with no dissent section.

2. expect: every entry of the Outvoted dissent section reached a closer: each of those claims has a
   row in some `verify/closer-*.json`.
   regression sign: a dissent claim no closer file answers (the lead dropped it again).

3. expect: the shipped `finalize-report.md` has 0 blocking lines reading "no closer has ruled on
   the dissent", and the probe "security claims confirmed 2-1 whose dissent no closer file answers"
   counts 0.
   regression sign: the probe counts above 0 on a map that shipped (the gate was bypassed), or the
   gate blocked and the lead recorded a way round it instead of dispatching a closer.

4. expect: a dissent a closer UPHELD shows in the gate as a refutation, and the map corrects the
   claim or drops the site before it ships.
   regression sign: an upheld dissent on a claim the shipped map still makes word for word.

5. expect (after the review): a security claim confirmed 2-1 counts as a dissent even when its line
   moved or its sentence was reworded before FINISH, and when it is a role that may do everything
   another may do.
   regression sign: a 2-1 security vote whose claim the shipped map no longer makes word for word
   (apply-drift moved it) and no closer file answers, with finalize silent about it.
