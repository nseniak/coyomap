# An excuse the messaging check reads is not called idle

Change (2026-09-30, retro finding mcpolis-2026-09-30-12): `validate`'s "recorded 'Interface
exceptions' id(s) silence nothing" advisory counts the keys the messaging check honours (a
publisher or consumer with no backbone edge to its broker), read through one shared function; the
process scorecard's assertion 24 matches every wording `validate` gives an idle record ·
tools/coyomap/validate_model.py, eval/tools/coyomap_eval/process_scorecard.py.
On the 2026-09-30 mcpolis map validate called 8 broker ids idle while the same run counted their 2
silences; the lead deleted the record and spent 9 rounds getting it back. With the fix the line is
gone from that map's output (1 → 0).

Escalation: none on its own.

## Checks

1. expect: the shipped map's validate output has no "silence nothing" line naming a key that
   excuses a messaging participant (a `Cn` publisher or consumer).
   regression sign: such a line, or a lead deleting an 'Interface exceptions' line and then
   re-adding it.

2. expect: assertion 24 of the build's scorecard reads 1/1, or names an idle line that is really
   idle when checked by removing it on a copy.
   regression sign: 1/1 while the map carries a "silence nothing" line (the old blindness).
