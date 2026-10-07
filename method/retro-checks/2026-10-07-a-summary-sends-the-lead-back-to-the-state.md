# A summary sends the lead back to the build state

Change (2026-10-07, round 1 of the context work): the coyomap skill opens with a "Continuing from a
summary?" paragraph: run `coyomap state show`, re-read the method section it names, and read the
`--help` of the next coyomap command before running it. `method.md` marks the start of each of the
12 phases `coyomap state phase <name>` knows, and `method/dispatch.md` says to open the state, to
start every phase with `state phase` and to write each operator decision with `state add` ·
skill/coyomap/SKILL.md, method.md, method/dispatch.md, tools/coyomap/buildstate.py.

Escalation: none.

## Checks

1. expect: on a build that compacted, the first coyomap command after the summary is
   `state show`. A read of the method lines it named follows within 5 turns. Each coyomap command
   not run since the summary comes after its `--help`.
   regression sign: a coyomap command before `state show`, or a record or assemble after the
   summary whose flags differ from the state's last one.
2. expect: each `coyomap state phase` call comes before that phase's first step.
   regression sign: more than 2 phases reached with no `phase` line.
3. expect: the installed `~/.claude/skills/coyomap/SKILL.md` opens with the "Continuing from a
   summary?" paragraph.
   regression sign: the installed copy lacks it (`make install` was not re-run).
