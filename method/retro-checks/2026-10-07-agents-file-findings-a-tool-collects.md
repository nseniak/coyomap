# Agents file their product findings, and a tool collects them

Change (2026-10-07, round 1 of the context work): an agent that notices a bug, risk, gap or
contradiction in the product files it the moment it sees it, with `coyomap findings add`, into its
own file under `.coyomap/findings/`; every brief but the wave runner's carries that rule, once. The
lead runs `coyomap findings collect` at each barrier: one line on screen, the whole
list in `.coyomap/findings-report.md`. `grounding report` and `finalize` count what was filed under
"FINDINGS FILED BY AGENTS", the old reader of the agents' transcripts is deleted, and
`grounding report --agent-transcripts` is refused · tools/coyomap/findings.py,
method/templates/findings-rule.md, tools/coyomap/contract.py, tools/coyomap/grounding.py,
tools/coyomap/finalize.py, tools/coyomap/ship.py, tools/coyomap/cli.py, method.md,
method/dispatch.md.

Escalation: none.

## Checks

1. expect: each product finding the retro reads in a hand-back (bug, risk, gap, contradiction) has
   a filed finding by the same agent.
   regression sign: a hand-back carrying a finding that was not filed.
2. expect: the lead's operator report quotes `findings collect`'s line and names every `risk`.
   regression sign: a `risk` in `findings-report.md` that is missing from the operator report.
3. expect: the grounding report and the finalize report both show "FINDINGS FILED BY AGENTS"; no
   findings file is in the commit.
   regression sign: "AGENT FINDINGS NOT READ" anywhere, or `findings/` in the commit.
