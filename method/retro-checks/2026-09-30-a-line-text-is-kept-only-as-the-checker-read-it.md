# A merged line text is kept only as the checker read it

Change (2026-09-30, retro finding mcpolis-2026-09-30-5): `coyomap line-texts record` takes the
check input (`--checked <the file check-input wrote>`, required) and keeps no text that differs
from the one the checker was handed, naming each as "CHANGED after the check"; method.md step 5b
and change-impact.md step 7 run `check-input` only after the writer has handed back · tools/coyomap
/line_texts.py, line_texts_cmd.py, method.md, method/change-impact.md.
On the 2026-09-30 mcpolis build the writer rewrote 5 texts after `check-input` had read its file;
3 could have shipped under verdicts given for their old wording, and only the lead's own file watch
caught it.

Escalation: none on its own.

## Checks

1. expect: in the lead transcript, `line-texts check-input` runs after the writer agent's
   hand-back, and `line-texts record` is called with `--checked`.
   regression sign: check-input before the hand-back, or a record call refused for a missing
   `--checked` and then worked around.

2. expect: `record`'s output names 0 texts "CHANGED after the check".
   regression sign: 1 or more, which means check-input read a file the writer was still writing.

3. expect: every text in the shipped `line-texts.json` equals its `merged` text in the build's
   `to-check.json`.
   regression sign: a kept text that differs from the one the checker read.
