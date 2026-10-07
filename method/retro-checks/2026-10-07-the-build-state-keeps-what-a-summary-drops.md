# The build state keeps what a summary drops

Change (2026-10-07, round 1 of the context work): the coyomap tools write one line per event to
`<repo>/.coyomap/build-state.log` as they run, and `coyomap state show` prints a short view of it.
`state start` opens it once the mode is Build and any old map is archived, `state phase <name>`
marks each phase, and `state add decision|next` writes the lead's own lines. `record` writes each
write's command and the file it named, `assemble` its command with `--reconcile` and its digest,
`preindex` E and its band; the contract, grounding, timings, findings, finalize and ship tools write
theirs. A line that carries a command (`next`, `ship`, `assemble`, `record`) is kept whole, and the
re-run a stopped `ship` writes spells every path absolute. `state show` opens with one line per wave
runner, its verdict files counted from its plan, until the runner writes how its wave ended
(`state add wave`, just before its report): from then on the line says DONE, or INCOMPLETE with
the FAILED voters the lead re-sends. The map folder's `.gitignore` keeps the state and the findings
out of the commit, and a credential-shaped value in them is a warning naming the file, in
`finalize` and in `coyomap credentials` alike: both read one list of the files no commit takes.
`coyomap-eval archive` keeps an OPEN state in place and moves an ended one with its map ·
tools/coyomap/buildstate.py, tools/coyomap/home.py, tools/coyomap/cli.py, tools/coyomap/record.py,
tools/coyomap/assemble.py, tools/coyomap/preindex.py, tools/coyomap/ship.py,
tools/coyomap/uncommitted.py, tools/coyomap/credentials.py, tools/coyomap/finalize.py,
method/dispatch.md, method/templates/wave-contract.md, eval/tools/coyomap_eval/archive.py.

Escalation: none.

## Checks

1. expect: the log has 1 `start` line and a `phase` line for each phase reached, in method order.
   It has one `record` line for each `coyomap record` write in the transcript, and each names the
   `--map` its command named.
   regression sign: fewer record lines than writes, or a record line whose file differs from its
   `--map`.
2. expect: a `decision` line for each operator rule or answer in the transcript (the Step 0 pin at
   least), and one `end` line once ship completed.
   regression sign: an operator rule with no decision line, or ship complete with no `end`.
3. expect: the log is in the build's archive and not in its commit.
   regression sign: it was committed, or the archive lacks it.
4. expect: every `next`, `ship`, `assemble` and `record` line holds its whole command, none ending in
   `…`, and a `next` line written by a stopped `ship` carries every flag of the command it re-runs,
   each path absolute.
   regression sign: a command line of the log that ends in `…`, or a re-run that lacks a flag the
   stopped `ship` was given (`--partial`, the note path) or holds a relative path.
5. expect: while a wave runner is out, each `state show` and `state phase` the lead runs prints that
   runner's `wave <id>:` line right after the verdict line, and the lead starts none of that wave's
   voters itself.
   regression sign: a `state show` during a wave with no `wave` line, or a lead launch of a voter
   named in the plan of a runner that is out.
6. expect: just before its report, each wave runner writes one `wave` line saying how its wave
   ended, `<id> DONE` or `<id> INCOMPLETE <ids>` with the ids its report's `failed:` names, and each
   `state show` after it reads `wave <id>: handed back DONE`, or
   `wave <id>: handed back INCOMPLETE · re-send its FAILED voters yourself: <ids>`.
   regression sign: a runner report with no end line for its wave before it in the log, a
   `state show` after a hand-back that still says `a runner is out`, or FAILED ids in the log that
   differ from the report's.
7. expect: a credential-shaped value in a file no commit takes (the state, a findings file, the
   findings report) is a WARNING naming the file in `coyomap credentials` and an advisory in
   finalize's `credential scan` leg, and neither stops the commit. A value in a committed file
   still fails both.
   regression sign: finalize's commit line withheld, or `coyomap credentials` exiting 1, over a hit
   in a file no commit takes; or a hit in a committed file reported only as a warning.
8. expect: one state file covers the whole build: its `phase` lines begin with the first
   `state phase` the transcript runs, also when the lead ran `state start` before archiving the old
   map with `coyomap-eval archive`.
   regression sign: a build whose state file starts after its first phases, or none at all.
