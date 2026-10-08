# findings withdraw takes a finding back and keeps the record

Change (2026-10-08, round 2, retro finding mcpolis-2026-10-08-#18): `coyomap findings withdraw
<agent>#<n> --why "<text>"` takes one finding back. It appends a line naming the finding and the
reason, and deletes nothing. `add` prints each finding's id; `collect` counts a withdrawn finding no
more, says "N withdrawn" in its line, and lists it under "## withdrawn" with the why. The agents'
findings rule tells them to use it · tools/coyomap/findings.py,
method/templates/findings-rule.md, tests/test_findings.py.

## Checks

1. expect: no finding in the next build's findings report is one its agent retracted in its own
   report or transcript text (the 2026-10-08 mcpolis build shipped 1).
   regression sign: an agent's hand-back or later text says a filed finding is wrong, and the
   report lists it outside "## withdrawn".

2. expect: every `withdraw` call in the build transcripts names an id `add` printed, and the
   findings report's "## withdrawn" section holds one entry per successful call.
   regression sign: a `withdraw` that exited 0 with no matching entry, or an agent that edited its
   `.coyomap/findings/<id>.jsonl` by hand to remove a finding.

## Review fix (2026-10-08)

Three fixes. "+N since the last collect" compares finding ids with the last report instead of
totals, so a finding filed after a withdrawal counts as new. A withdrawal of an exact repeat of a
finding already withdrawn is refused (exit 2, nothing written), instead of printing WITHDRAWN and
then reading as a malformed line. The eval's command index counts `findings withdraw` as its own
verb · tools/coyomap/findings.py, tests/test_findings.py, eval/tools/coyomap_eval/transcript.py,
eval/tests/test_transcript.py.

3. expect: on a build with a `withdraw`, the next collect's "+N" equals the findings filed since
   the collect before it.
   regression sign: "+0 since the last collect" on a collect whose report lists a finding id the
   previous report did not.
4. expect: the eval's command table shows `findings withdraw` rows apart from `findings add`.
   regression sign: a `findings withdraw` call in a transcript counted as a bare `findings`.
