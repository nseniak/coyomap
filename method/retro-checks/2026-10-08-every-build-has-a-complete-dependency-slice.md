# Every build harvests the dependencies as their own slice, and every dependency gets a bucket

Change (2026-10-08, round 2, backlog row 49, method half): method.md's T2 section requires a
dedicated dependency job every build (one slice in a fan-out, a step of its own in a serial build).
It lists every outside system AND every top-level library or framework the package files declare,
one row per package. Its D-ids are the legend the T5 owner gets, by injection or by a reconcile
backfill, and a legend the lead writes by hand is not allowed. The harvest contract tells the
dependency slice the same. The synthesis reconcile step says every dep gets a `bucket`, not only
the ones to fix · method.md, method/templates/harvest-contract.md.

Escalation: if check 1 or 3 fails, run the eval: the Dependencies view loses rows or groups with
no gate seeing it.

## Checks

1. expect: the harvest fan-out has one agent whose only job is dependencies, and the shipped map
   holds a dep row for each top-level library or framework in the package files (2026-10-08: no
   such slice, 19 deps where the previous build had 29).
   regression sign: dependencies given to a slice with other jobs, or a dep row naming two
   packages ("React and Vite").
2. expect: the T5 brief's D-id legend matches the dependency slice's fragment, or `store.dep` is
   backfilled by a reconcile set.
   regression sign: a D-id legend in the lead's turns written before any harvest fragment exists
   (2026-10-08: "fixed legend D1-D9" at turn 282).
3. expect: the reconcile file sets a `bucket` on every dep, and the shipped map has 0 deps with an
   empty bucket (2026-10-08: 19 of 19 empty, 8 of the viewer's guesses wrong).
   regression sign: any dep with an empty `bucket` in the shipped map.
