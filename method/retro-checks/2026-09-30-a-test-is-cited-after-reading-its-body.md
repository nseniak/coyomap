# A test is cited after reading its body, and the lint checks it

Change (2026-09-30, retro finding mcpolis-2026-09-30-28): the tests contract says to read the body of
every test cited, never to cite from a name list; `coyomap grounding lint --tests <x-tests.json>`
fails every citation whose body (2 of the next 8 lines of at least 25 characters) no tool result in
the agents' transcripts printed; method.md runs it when the tests agent lands · tools/coyomap
/grounding.py, method/templates/tests-contract.md, method.md.
On the 2026-09-30 mcpolis build the tests agent built a name index with `grep -n 'def test_'`: the
new lint, run over that build's fragment and the agent's transcript, names 83 of 184 citations.

Escalation: none on its own.

## Checks

1. expect: the lead transcript runs `coyomap grounding lint --tests` after the tests agent lands,
   and its last run prints `TESTS OK`.
   regression sign: the lint never run, or `TESTS FAILED` with no re-ping.

2. expect: re-run by the retro over the build's `x-tests.json` and the tests agent's own
   transcript, the lint names fewer than 10 citations (the 2026-09-30 build: 83 of 184).
   regression sign: 40 or more, or a table smaller than 30 rows (the rule shrank the table instead
   of sending the agent to read).

3. expect: a sample of 10 `why`s matches what the cited test's body asserts.
   regression sign: a `why` that restates the test's name and misses what its body checks.
