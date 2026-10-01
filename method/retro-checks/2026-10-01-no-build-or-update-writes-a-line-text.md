# No build and no update writes, checks or commits an Architecture line text

Change (2026-10-01): the Architecture view lists the use cases that take a line instead of one merged
sentence, so the merged sentences ("line texts") and everything that made them go: the `line-texts`
command, the `line-texts` and `line-texts-check` contracts, method.md's closing step 5b, the
update's Step 7 line-text commands and scratch files, and the `line-texts.json` entry of the
tracked-folder rule · method.md, method/change-impact.md, method/templates/,
tools/coyomap/{cli,contract,finalize,fix,ship,whole_file}.py, tools/coyomap/viewer/{gen_viewer,serve}.py.
It was checked by a test run and by one fresh agent reading the edited passages, not by a build or an
update, so this file is what makes the first real one count.

Escalation: if check 1 or 3 fails, read the method passages it names before accepting the map.

## Checks

1. expect: the transcript has 0 calls of `coyomap line-texts` and 0 `contract line-texts` or
   `contract line-texts-check` fills, and launches 0 agents to write or check a merged sentence.
   regression sign: any such call; or a "no such command" / file-not-found error naming
   `line-texts`, which means a passage still sends the agent there.

2. expect: the shipped commit adds or changes no `.coyomap/line-texts.json` (mcpolis's was deleted
   with this change, so on mcpolis the file does not exist at all).
   regression sign: the file exists after the run, or appears in the commit's file list.

3. expect (an update only): Step 7 runs refutations, render, validate, audit, `changes render`,
   preindex, provenance stamp and credentials in that order, then deletes the `.before.json`,
   `.impact.json`, `.applied.json` and `.scope.json` scratch files, and commits map, log, views,
   pre-index, provenance and the `verify/` files in one commit.
   regression sign: the agent pauses between preindex and provenance looking for a step, mentions
   line texts, or creates or deletes a `.lines.json`, `.texts.json`, `.to-check.json` or
   `.text-verdicts.json` file.

4. expect (a build only): closing step 13 commits the map, the .md, the pre-index and provenance,
   and the lead never names a step 5b.
   regression sign: the lead says "5b", or looks for a line-text contract before step 12.

5. expect: the Architecture view's text lists, under each line, the use cases that take it (grouped
   under features with a count past 3 use cases from more than one feature), and no line shows a
   "The N sentences it merges" fold.
   regression sign: a merged-sentence fold appears, or a line shows no use cases.
