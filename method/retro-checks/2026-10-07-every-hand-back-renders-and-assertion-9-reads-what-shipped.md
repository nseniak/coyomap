# Every sub-agent report renders as the agent's, and assertion 9 reads what shipped

Change (2026-10-07, retro findings mcpolis-2026-10-07-9 and -10, carried rows 09-30b-10 and
08-29-23): `coyomap-eval transcript` reads a report a sub-agent hands back by its `origin` stamp,
whether it arrives as a user message or as a `queued_command` attachment, and renders it in `--full`
as `(hand-back from <agent id>)` at the turn it reached the lead; an attachment never becomes a turn.
`operator_text` removes whole `<system-reminder>` spans before its tests, so the operator's words in
the record's other block survive. Assertion 9 of `coyomap-eval process` scores the LAST
`Advisory disposition` line finalize printed (stdout or gate block) when the transcript holds one ·
eval/tools/coyomap_eval/transcript.py, eval/tools/coyomap_eval/process_scorecard.py. Tools only;
no method text and no map changed.

Escalation: none. If item 1 or 2 fails, every count of returns or operator turns a slice reader
takes from `--full` is low, so the retro says so before it relies on one.

## Checks

1. expect: `coyomap-eval transcript <build transcript> --full-output` prints one
   `(hand-back from` block per record stamped `origin.handback` (user messages plus `queued_command`
   attachments), and the transcript's turn count is the one the previous reader gave. On the
   2026-10-07 mcpolis build: 128 blocks for 128 stamped records (62 attachments, 66 messages),
   against 0 before, and 807 turns before and after.
   regression sign: fewer `(hand-back from` blocks than stamped records; an `(operator)` line that
   opens with "Another Claude session sent a message" or holds `[Subagent hand-back]`; or a turn
   count that moved for the same transcript, meaning a report became a turn and every cited turn
   number after it shifted.

2. expect: every user record stamped `origin.kind: human` that carries words renders as an
   `(operator)` line, including one whose first block is a `<system-reminder>`. On the 2026-10-07
   build: 6 operator lines, at turns 0, 767, 769, 773, 789 and 797; 767 and 789 were the 2 missing.
   regression sign: a human-stamped record with words and no `(operator)` line, or reminder text
   inside an `(operator)` block.

3. expect: on a build whose transcript holds a finalize disposition line (a `ship --note-file` run,
   a typed `finalize`, or a `cat` of `.coyomap/verify/gate-block.md`), assertion 9's note opens
   "from the last finalize disposition, turn N" and its counts are that line's `recorded` rows
   against `recorded` + UNANSWERED + UNRECORDED + UNSURE. On the 2026-10-07 build: 1 of 9, where the
   validate-only reading said 37 of 37.
   regression sign: a note reading "validate run(s) captured" on such a build, with no later
   finalize that raised 0 advisories; or a score of 1.00 while the last disposition line lists an
   UNANSWERED, UNRECORDED or UNSURE row.
