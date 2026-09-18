#!/usr/bin/env python3
"""The single `coyomap-eval` command — the method-quality regression harness dispatcher.

Each subcommand imports its implementation lazily. Stdlib-only; depends on the `coyomap` core package
(schema / validate / audit) for the shared parse, and nothing else.
"""
from __future__ import annotations

import io
import sys

USAGE = """usage: coyomap-eval <command> [args...]

Commands:
  score    Emit a map's deterministic quality PROFILE (structure / validate / audit / coverage).
  run      Profile a built map, compare vs its baseline, and archive the run.
  hash     Print a map artifact's sha256 freeze hash (write it at build time; `run` enforces it).
  claims   Print the audit's L2 worklist (the judge's input) — `--json`, `--top K` for the sample.
  judge    Aggregate orchestrated judge verdicts (grounding + rubric) into judge.json.
  protocol Print the current judge-protocol fingerprint; --against guards the baseline cache.
  bless    Promote a run to the baseline (map + rendered view + profile + judge).
  arrows   Which relations a rebuild LOST, and whether the code still makes each one. Matches
           by SOURCE FILE (ids and wording never agree across two builds) and re-reads each lost
           arrow's recorded call site. The check that catches a map dropping true relations while
           validate, audit and the shrink bands all stay green. Exit 1 on any lost truth.
  compare  Compare a candidate MapProfile against a baseline; apply the relative regression gates.
  process  L3 PROCESS scorecard over a build TRANSCRIPT (did the agent behave as the method says?)
           — `--diff a.json b.json` compares two scorecards. A scorecard, never a gate.
  transcript  READ a build transcript in slices — an index by default, `--full` for one range.
           The retrospective's eye on what the agent actually did.
  cost     What a build SPENT — wall time, tokens, and both PER ROW of map produced (`--map`).
           Reads the sub-agent transcripts too, which are most of the spend. Never a gate.
  mutate   Plant known-false claims in a batch (`plant`) and score a skeptic's verdicts against
           the answer key (`score`). Measures RECALL: comparing two prompts' refutation RATES
           cannot say whether the skeptics are weak or the map is good, because neither run has a
           ground truth to be wrong about. Planted falsehoods do.
  archive  Move a repo's coyomap map into .coyomap/dev-rebuilds/NNNN/ so the next run BUILDS
           from scratch (dispatch reads the WORKING TREE to choose the mode). Moves, never
           deletes — the old map is the baseline the new one is compared against.
  ledger   Cross-examine a retro ledger against the git history it cites. A row's `landed`
           flag is set by hand and nothing checked it: one session answered 40 rows, fixed
           seven of them, and left all seven reading `landed: false` — the next retro would
           re-propose work already done. Exit 1 on any such row.
  live-numbers  Re-measure every present-tense sentence the tools write about a LIVE map.
           A number in a comment ("142 entities, 46 of them saved") measures a map that keeps
           being rebuilt, so the code stays right while the sentence stops being true and no
           gate can see it. Reads no prose: a person writes the sentence here too, and a
           measure regenerates it from the map. Exit 1 on any stale row.
  walk-score  Score a PARTIAL RUN of the front-door walk: two maps (before, after) against a
           gold table written BEFORE the agent ran — which way in became a use case, was named
           on one, was recorded, or was left untouched. Exit 1 on any way in outside its gold.
  field-score  Score a partial run that WROTE map fields, against the writing rules and the map's
           own advisories — one sentence each, the word cap, no arrow an author never types, and the
           pair read as one box. Two runs before this were scored by throwaway scratchpad scripts. It
           clears the mechanical floor only; the run's "where I had to guess" section is where every
           wording defect has actually come from. Exit 1 on any failure.
  retro-precheck  Refuse to retrospect a build that has not finished. Exit 1 when another
           session is still writing a transcript — provenance is stamped near the END of a
           build, so mid-run it still names the PREVIOUS one and a retro reads the wrong run.

Run `coyomap-eval <command> --help` for command-specific options."""


def main(argv: list[str] | None = None) -> int:
    # Line-buffer stdout so the two streams interleave in PROGRAM order under a pipe. Same reason
    # as `coyomap.cli.main`: piped stdout is block-buffered, stderr is not, so `2>&1 | tail -N`
    # re-orders a failure to the head of the pipe and leaves harmless notes in the tail.
    # Guarded on the concrete type: an in-process caller (pytest's capture, a harness) may
    # replace stdout with a plain stream that has no `reconfigure`, and the buffering bug
    # does not exist there anyway.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    cmd, rest = args[0], args[1:]
    if cmd == "score":
        from coyomap_eval import profile
        return profile.main(rest)
    if cmd == "run":
        from coyomap_eval import run
        return run.run_cli(rest)
    if cmd == "hash":
        from coyomap_eval import run
        return run.hash_cli(rest)
    if cmd == "claims":
        from coyomap_eval import run
        return run.claims_cli(rest)
    if cmd == "judge":
        from coyomap_eval import run
        return run.judge_cli(rest)
    if cmd == "protocol":
        from coyomap_eval import run
        return run.protocol_cli(rest)
    if cmd == "bless":
        from coyomap_eval import run
        return run.bless_cli(rest)
    if cmd == "arrows":
        from coyomap_eval import arrows  # stdlib-only; reads two maps and the tree, no model
        return arrows.main(rest)
    if cmd == "compare":
        from coyomap_eval import compare
        return compare.main(rest)
    if cmd == "process":
        from coyomap_eval import process_scorecard
        return process_scorecard.main(rest)
    if cmd == "archive":
        from coyomap_eval import archive
        return archive.main(rest)
    if cmd == "ledger":
        from coyomap_eval import ledger
        return ledger.main(rest)
    if cmd == "live-numbers":
        from coyomap_eval import live_numbers
        return live_numbers.main(rest)
    if cmd == "walk-score":
        from coyomap_eval import walk_score
        return walk_score.main(rest)
    if cmd == "field-score":
        from coyomap_eval import field_score
        return field_score.main(rest)
    if cmd == "retro-precheck":
        from coyomap_eval import retro_precheck
        return retro_precheck.main(rest)
    if cmd == "transcript":
        from coyomap_eval import transcript
        return transcript.main(rest)
    if cmd == "cost":
        from coyomap_eval import cost
        return cost.main(rest)
    if cmd == "mutate":
        from coyomap_eval import mutate
        return mutate.main(rest)
    print(f"coyomap-eval: unknown command '{cmd}'\n", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
