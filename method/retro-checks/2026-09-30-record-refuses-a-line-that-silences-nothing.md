# record refuses a line that silences nothing, and removes all it is asked to

Change (2026-09-30, retro finding mcpolis-2026-09-30-17): under a heading keyed on free text that
only `validate` reads ('Sweep debt', 'Condition exceptions', 'Skipped screen exceptions',
'Accepted duplications'), `coyomap record` tries each new line on the assembled map beside the
fragment and refuses one that, on its own, changes nothing `validate` reports; every `--remove`
is honoured, all or nothing; a fragment with no `extras` key is refused instead of losing the line;
and "recorded under" is printed only once the write is certain · tools/coyomap/record.py, the
footers in tools/coyomap/finalize.py and tools/coyomap/validate_model.py.
On the 2026-09-30 mcpolis build `record` stored 6 comma-listed 'Sweep debt' lines with exit 0, and
the lead re-recorded them one per anchor two rounds later. On a copy of that map: two live anchors
as one comma-listed line, accepted before, refused after; one live anchor, accepted both times;
`--remove A --remove B` left 1 line before and 0 after.

Escalation: none on its own.

## Checks

1. expect: 0 lines under 'Sweep debt', 'Condition exceptions' or 'Skipped screen exceptions' whose
   key names more than one `path:line` anchor.
   regression sign: a comma-listed anchor line in the shipped map's extras.

2. expect: in the lead transcript, no `record` call under those headings exits 0 and is followed by
   the same anchors recorded again one per line.
   regression sign: the turn-575 pattern: a batch stored, then the same anchors re-recorded one per
   line once `validate` still showed them.

3. expect: 0 `python3` or heredoc edits of an extras fragment after a `record` refusal.
   regression sign: a refusal answered by writing the fragment by hand, which means the refusal had
   no reachable remedy (a stale assembled map is the likely cause: assemble, then record).
