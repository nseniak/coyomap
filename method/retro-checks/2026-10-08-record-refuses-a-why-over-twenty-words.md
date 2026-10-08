# record refuses a why with a sentence over 20 words

Change (2026-10-08, round 2, retro finding mcpolis-2026-10-08-#16): `coyomap record` refuses a line
whose why holds a sentence over 20 words, names each such sentence with its word count, and writes
none of the batch. It reads the why the way the readability check does (`records.why_of`, then
`prose.long_sentences`), so the key is never counted · tools/coyomap/record.py,
tests/test_record.py.

## Checks

1. expect: the next map's readability report counts 0 long sentences in recorded lines written by
   `record` (the 2026-10-08 mcpolis map: 20 of its 34 long sentences were recorded lines).
   regression sign: a recorded line on the shipped map with a why sentence over 20 words that the
   build transcript shows `record` writing.

2. expect: the build transcript shows `record` refusals with "over the 20-word limit" followed by
   a shorter rewrite, not by a hand edit of the extras fragment.
   regression sign: a refused line later found in the fragment with the same long sentence,
   written by any other means.
