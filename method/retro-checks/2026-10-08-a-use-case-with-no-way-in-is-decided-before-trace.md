# The lead decides each use case with no way in before the trace

Change (2026-10-08, round 2, retro finding mcpolis-2026-10-08-#15): at the front-door verification
moment of synthesis, method.md now tells the lead to list the use cases that still name no way in
once the reconcile file is written, and to keep each one only with a checkable reason or drop it
before the trace. When a trace drops a use case anyway, every recorded line about its pieces says
it was dropped. Prose only: the method still allows a use case with no way in · method.md.

## Checks

1. expect: the trace briefs carry 0 use cases with `entry_points: none` unless the build state or
   the lead's turns give a reason for each (2 went to trace that way on 2026-10-08, UC22 and UC53,
   and both were dropped after it).
   regression sign: a tracer reporting "no code for this use case" on a use case that had no way
   in at synthesis.
2. expect: every recorded line naming a sub-flow or step of a dropped use case gives the drop as
   its reason.
   regression sign: a recorded reason that contradicts a trace hand-back, as SF51's "cut to keep
   that flow inside the step band" did on 2026-10-08 when its second user had been dropped.
