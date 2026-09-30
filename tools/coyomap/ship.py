#!/usr/bin/env python3
"""`coyomap ship` — the build's closing sequence as ONE command.

`method.md` closes a build with a numbered sequence (anchor-drift → apply-drift → assemble →
grounding report → grounding write → assemble → provenance stamp → assemble → lint the header →
validate → audit → render → finalize). Every step is deterministic given its inputs, and the two
judgement points are OUTSIDE the steps: reconciling the refutations (before), and writing the
grounding note (between report and write). Run by hand, the sequence has been re-done on real
builds — `finalize` run twice with the second run overwriting the report, the grounding record
written twice, a hand-scripted header edit landing as the build's last write.

So this command runs the mechanical tail and stops where judgement is needed:

  without --note-file   PREPARE: anchor-drift → apply-drift --to-reconcile → assemble →
                        grounding report. Then STOP: read the report, write the note.
  with --note-file      FINISH: the same three (idempotent), then grounding write → assemble →
                        provenance stamp --update-header → assemble → lint-fragment header →
                        validate --check-sources → audit → render → finalize --emit-gate-block.

A failed step STOPS the run and names itself — a skipped step must never read as a clean one.
Every step is the ordinary subcommand with its documented flags, invoked in-process; `ship` adds
no check and writes nothing of its own.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from coyomap.access_surface import newest_archived_map

USAGE = """usage: coyomap ship <repo> [--note-file <path>] [--partial] [--keep-note]
                    [--note-cites-other-runs]
                    [--access-baseline <map-or-surface.json>]
                    [--worklist <audit.json>] [--reconcile <file>]
                    [--verdicts <raw.json>]... [--fragments <dir>]
                    [--agent-transcripts <dir>]

The closing sequence of a build (method.md's numbered list) as one command.
Defaults, all under <repo>/.coyomap/: the map at project-map.json, fragments at
build-fragments/*.json, the reconcile file at reconcile.json, the pinned worklist at
verify/worklist.json, verdicts at verify/verdicts-*.json AND the closer's appeals at
verify/closer-*.json, the gate block written to verify/gate-block.md.

A closer file is a verdicts file in shape and an APPEAL in meaning: it never votes, and a
refutation it REJECTS stops blocking the refutation gate. See `grounding.is_closer_row`.

--agent-transcripts forwards to `grounding report`, which reads the closing message every build
agent wrote to the lead. Inside the build's own session it is found without the flag; a
RETROSPECTIVE is a different session, so without it that whole channel reads NOT READ — and the
retrospective is the reader who most needs it.

Two phases, split where the ONE judgement input sits:
  no --note-file : anchor-drift, apply-drift --to-reconcile, assemble, grounding report —
                   then stop, so the note is written FROM the report.
  --note-file    : the full tail through finalize. --partial / --keep-note /
                   --note-cites-other-runs forward to `grounding write`;
                   --access-baseline forwards to `finalize`; without it, the newest archived map under
                   .coyomap/dev-rebuilds/ is used when one exists.

--note-cites-other-runs says the figures in the note are about OTHER runs, or are scoped
to one theme. `grounding write` REFUSES a note whose numbers contradict its own record;
without this flag that refusal stops ship at step 6 of 12 with no way past it.
"""

#: The subcommand names a Step may use — the same names `coyomap <cmd>` dispatches on.
Runner = Callable[[list[str]], int]


@dataclass(frozen=True)
class Step:
    title: str
    argv: tuple[str, ...]  # argv[0] is the subcommand name


@dataclass(frozen=True)
class ShipInputs:
    repo: Path
    out: Path                 # <repo>/.coyomap
    map_path: Path
    fragments: tuple[Path, ...]
    reconcile: Path | None    # None = no reconcile.json on disk (assemble runs without it)
    worklist: Path
    verdicts: tuple[Path, ...]
    header: Path
    md: Path
    gate_block: Path
    note_file: Path | None
    partial: bool
    keep_note: bool
    #: Forwarded to `grounding write`. Without it a note whose numbers are about ANOTHER run kills
    #: `ship` at step 6 of 12, and the operator's only route is to abandon the prescribed path and
    #: hand-run the remaining seven steps — the failure `run_plan`'s "NOT RUN:" line exists to stop.
    note_cites_other_runs: bool
    access_baseline: Path | None
    #: Forwarded to `grounding report`, whose findings-from-the-agents section needs it whenever
    #: the run is not the build's own session — which is every retrospective.
    agent_transcripts: Path | None = None
    #: The pinned worklist's tier, read off its items. Step 2's `anchor-drift` counts coverage at
    #: that tier, so the gate block's `challenged N of M` and its audit line count ONE surface.
    behavioural: bool = False


def derive_inputs(repo: Path,
                  note_file: Path | None = None,
                  partial: bool = False,
                  keep_note: bool = False,
                  note_cites_other_runs: bool = False,
                  access_baseline: Path | None = None,
                  worklist: Path | None = None,
                  reconcile: Path | None = None,
                  verdicts: tuple[Path, ...] | None = None,
                  fragments_dir: Path | None = None,
                  agent_transcripts: Path | None = None) -> ShipInputs | str:
    """Resolve every path the sequence needs, or return an error string saying what is missing.

    Globs are sorted, matching the shell's lexicographic `*.json` — fragment ARGUMENT ORDER decides
    dedup survivors, so it must be stable across the repeated assembles.
    """
    out = repo / ".coyomap"
    frag_dir = fragments_dir if fragments_dir is not None else out / "build-fragments"
    if not frag_dir.is_dir():
        return f"no fragments directory at {frag_dir} — nothing to assemble; ship is the BUILD closer"
    frags = tuple(sorted(p for p in frag_dir.glob("*.json") if not p.name.endswith(".draft.json")))
    if not frags:
        return f"no fragments in {frag_dir} — nothing to assemble"
    wl = worklist if worklist is not None else out / "verify" / "worklist.json"
    if not wl.is_file():
        return (f"no pinned worklist at {wl} — capture it BEFORE reconciling refutations "
                "(coyomap audit <map> --json > .coyomap/verify/worklist.json), or pass --worklist")
    # TWO GLOBS, SEPARATELY, because they are two populations and the second was invisible.
    # `verdicts-*.json` is the skeptics' votes; `closer-*.json` is the closer's appeals, written in
    # the same shape beside them (`method/templates/closer-contract.md`). One glob for both would
    # read, but naming the second is what says the gate can see it — until now the closer's file sat
    # in `verify/` and no step of the closing sequence opened it, so a refutation the closer had
    # REJECTED still blocked the ship gate. The readers tell the two apart by the row's own
    # `verdict` field, never by the file name (`grounding.is_closer_row`).
    skeptic_files = tuple(sorted((out / "verify").glob("verdicts-*.json")))
    closer_files = tuple(sorted((out / "verify").glob("closer-*.json")))
    vd = verdicts if verdicts else skeptic_files + closer_files
    if not vd:
        return (f"no verdicts files under {out / 'verify'} — the Phase-4 skeptics' output is a "
                "required input; pass --verdicts, or run the sequence by hand for a map with no "
                "claim surface")
    if not verdicts and not skeptic_files:
        return (f"only closer file(s) under {out / 'verify'} and no verdicts-*.json — a closer "
                "settles refutations the skeptics cast, so on its own it is an appeal against "
                "nothing; pass --verdicts if the skeptics' files live elsewhere")
    rec = reconcile if reconcile is not None else out / "reconcile.json"
    rec_final: Path | None = rec if rec.is_file() else None
    from coyomap.grounding import worklist_is_behavioural   # lazy, like `_dispatch`
    behavioural = worklist_is_behavioural(wl)
    if access_baseline is None:
        access_baseline = newest_archived_map(out)
    return ShipInputs(
        repo=repo, out=out, map_path=out / "project-map.json", fragments=frags,
        reconcile=rec_final, worklist=wl, verdicts=vd,
        header=frag_dir / "header.json", md=out / "project-map.md",
        gate_block=out / "verify" / "gate-block.md",
        note_file=note_file, partial=partial, keep_note=keep_note,
        note_cites_other_runs=note_cites_other_runs,
        access_baseline=access_baseline, agent_transcripts=agent_transcripts,
        behavioural=behavioural)


def _assemble_step(s: ShipInputs, title: str, carry_record: bool = False) -> Step:
    """One assemble over the fragments `ship` found when it started — and, with `carry_record`,
    the record fragment `grounding write` creates at `build-fragments/grounding.json`.

    The fragment list is ONE glob, taken before any step runs. On the run that writes the record
    for the first time the file is not there to be globbed, so every assemble after the write
    carried every fragment but the one the write had just produced, and the map shipped with no
    grounding record until `ship` was run a second time — a live build found its map without the
    record after a clean run and re-ran the whole sequence. The steps after the write name the
    file explicitly, in sorted position, so argument order (which decides dedup survivors) is what
    a re-run's glob would give."""
    frags = s.fragments
    if carry_record:
        frags = tuple(sorted(set(s.fragments) | {s.header.parent / "grounding.json"}))
    argv: list[str] = ["assemble", *map(str, frags), "--out", str(s.out)]
    if s.reconcile is not None:
        argv += ["--reconcile", str(s.reconcile)]
    return Step(title, tuple(argv))


def _verdict_flags(s: ShipInputs) -> list[str]:
    flags: list[str] = []
    for v in s.verdicts:
        flags += ["--verdicts", str(v)]
    return flags


def _pinned_verdict_flags(s: ShipInputs) -> list[str]:
    """The verdicts `grounding write` will accept: the ones cast on the PINNED worklist.

    `grounding write` refuses a verdict whose claim is not in the pinned worklist, on purpose — a
    record built from votes on claims the skeptics were never given would misstate what was
    challenged. `finalize` needs the opposite: every verdict there is, including the post-pin
    re-challenges, or its refutation leg cannot see them.

    Feeding ONE list to both is what broke on the 2026-08-29 mcpolis build. `ship` stopped at step 6
    with `9 verdict claim(s) are not in the pinned worklist`, the lead abandoned the verb and
    hand-ran steps 5-12 with a shell loop that filtered the post-pin files out for `grounding write`
    and back in for `finalize` — and the map still shipped `finalize`'s "the record's delta counts
    contradict the verdict files" as a `carried (no escape)` advisory, because the two commands had
    been measured against different sets.

    The rule is EVERY claim pinned, not ANY. A first version kept a file that straddles — some rows
    pinned, some not — reasoning that dropping it would hide votes the record is entitled to. That
    version does not fix the case its own paragraph above describes: on the real build the nine
    off-pin claims lived in the three `verdicts-recheck*.json` files, each carrying 3 pinned claims
    and 9 post-pin ones. Straddlers, kept, and `grounding write` refused the set with the identical
    "9 verdict claim(s) are not in the pinned worklist". The set the build needed by hand was the 32
    files with no post-pin claim at all.

    What a dropped straddler costs is a RE-VOTE, in the normal case: a post-pin batch re-challenges
    claims the pinned pass already voted on, so those verdicts exist elsewhere. Where it would cost
    a claim's only vote, the record simply reports that claim as unchallenged — which is true, and
    is what `claims_live_challenged` is for. The alternative is not a better record; it is
    `grounding write` refusing and no record at all.

    Dropped files are NAMED by the caller, because a lost sole vote must be visible."""
    pinned = set(_worklist_claims(s.worklist))
    if not pinned:
        return _verdict_flags(s)
    flags: list[str] = []
    for v in s.verdicts:
        claims = _verdict_claims(v)
        if claims and not (claims <= pinned):
            continue                # holds a post-pin claim: `grounding write` would refuse the set
        flags += ["--verdicts", str(v)]
    return flags


def post_pin_verdicts(s: ShipInputs) -> list[Path]:
    """The verdict files `grounding write` cannot be given — named so a lost vote is visible."""
    pinned = set(_worklist_claims(s.worklist))
    if not pinned:
        return []
    return [v for v in s.verdicts
            if (claims := _verdict_claims(v)) and not (claims <= pinned)]


def _worklist_claims(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    rows = payload.get("worklist") if isinstance(payload, dict) else payload
    return {str(r.get("claim")) for r in (rows or []) if isinstance(r, dict) and r.get("claim")}


def _verdict_claims(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    rows = payload.get("grounding") if isinstance(payload, dict) else payload
    return {str(r.get("claim")) for r in (rows or []) if isinstance(r, dict) and r.get("claim")}


def build_plan(s: ShipInputs) -> list[Step]:
    """The method's closing list, steps 2-12, cut at the note. Step numbers cite method.md."""
    prepare = [
        Step("anchor-drift (step 2 — what drifted)",
             ("anchor-drift", "--map", str(s.map_path), *_verdict_flags(s),
              *(("--with-behavioural",) if s.behavioural else ()))),
        Step("fix apply-drift --to-reconcile (step 3 — record the corrections)",
             ("fix", "apply-drift", "--map", str(s.map_path), *_verdict_flags(s),
              "--to-reconcile", str(s.reconcile if s.reconcile is not None
                                    else s.out / "reconcile.json"))),
        _assemble_step(s, "assemble (step 4 — last structural assemble)"),
        Step("grounding report (step 5 — what the note is written from)",
             ("grounding", "report", "--worklist", str(s.worklist), *_verdict_flags(s),
              *(("--agent-transcripts", str(s.agent_transcripts))
                if s.agent_transcripts is not None else ()),
              "--map", str(s.map_path))),
    ]
    if s.note_file is None:
        return prepare
    write_argv: list[str] = ["grounding", "write", "--worklist", str(s.worklist),
                             *_pinned_verdict_flags(s), "--map", str(s.map_path),
                             "--note-file", str(s.note_file),
                             "--out", str(s.header.parent / "grounding.json")]
    if s.partial:
        write_argv.append("--partial")
    if s.keep_note:
        write_argv.append("--keep-note")
    if s.note_cites_other_runs:
        write_argv.append("--note-cites-other-runs")
    finalize_argv: list[str] = ["finalize", str(s.map_path), "--repo", str(s.repo),
                                *_verdict_flags(s), "--emit-gate-block", str(s.gate_block)]
    if s.access_baseline is not None:
        finalize_argv += ["--access-baseline", str(s.access_baseline)]
    # prepare[:-1]: the report leg is for writing the note; with the note in hand it is finalize's
    # and grounding write's own reads that matter, and `report` would only repeat what was read.
    return prepare[:3] + [
        Step("grounding write (step 6 — the record, measured against the map)", tuple(write_argv)),
        _assemble_step(s, "assemble (step 7 — carries the record in)", carry_record=True),
        Step("provenance stamp (step 8 — stamps and fills `built`)",
             ("provenance", "stamp", str(s.repo), "--mode", "build",
              "--update-header", str(s.header))),
        _assemble_step(s, "assemble (step 9 — the filled header reaches the map)", carry_record=True),
        Step("lint-fragment header (step 10 — the one hand-authored fragment)",
             ("lint-fragment", str(s.header))),
        # `by-element` between the map being final and the gates reading it. `finalize`'s grounding
        # leg has told three builds in a row to run this command for the list behind its count, and
        # it was run ZERO times on all three — the advisory names the command, the operator is 400
        # lines downstream, and the count ships unexamined (112 elements on argus). Running it here
        # costs one read of files already in memory and puts the list where the count is. No
        # `--worklist` ON PURPOSE: that reads the LIVE map and reproduces finalize's number, while
        # adding the pinned worklist answers a different question and gives a different one.
        Step("grounding by-element (the list behind finalize's confidence count)",
             ("grounding", "by-element", *_verdict_flags(s), "--map", str(s.map_path))),
        Step("validate --check-sources (step 11a)",
             ("validate", str(s.map_path), "--check-sources", "--repo", str(s.repo))),
        Step("audit (step 11b)", ("audit", str(s.map_path))),
        Step("render (step 11c)", ("render", str(s.map_path), str(s.md))),
        Step("finalize (step 12 — one run, both flags)", tuple(finalize_argv)),
    ]


def default_runner(argv: list[str]) -> int:
    """Dispatch one step to its subcommand main(), lazily — the same firewall as cli.py."""
    cmd, rest = argv[0], argv[1:]
    if cmd == "anchor-drift":
        from coyomap import anchor_drift
        return anchor_drift.main(rest)
    if cmd == "fix":
        from coyomap import fix
        return fix.main(rest)
    if cmd == "assemble":
        from coyomap import assemble
        return assemble.main(rest)
    if cmd == "grounding":
        from coyomap import grounding
        return grounding.main(rest)
    if cmd == "provenance":
        from coyomap import provenance
        return provenance.main(rest)
    if cmd == "lint-fragment":
        from coyomap import lint_fragment
        return lint_fragment.main(rest)
    if cmd == "validate":
        from coyomap import validate_model
        return validate_model.main(rest)
    if cmd == "audit":
        from coyomap import audit_model
        return audit_model.main(rest)
    if cmd == "render":
        from coyomap.viewer import render
        return render.main(rest)
    if cmd == "finalize":
        from coyomap import finalize
        return finalize.main(rest)
    print(f"ship: unknown step subcommand '{cmd}'", file=sys.stderr)
    return 2


def run_plan(steps: list[Step], runner: Runner) -> int:
    """Run the steps in order; STOP at the first non-zero exit, naming the step.

    A skipped step must never read as a clean one, so the failure line says which steps did NOT
    run — the exact information three hand-run sequences lost on real builds.
    """
    for i, step in enumerate(steps):
        print(f"\n=== ship [{i + 1}/{len(steps)}] {step.title}")
        print("    " + " ".join(step.argv))
        rc = runner(list(step.argv))
        if rc != 0:
            remaining = [s.title for s in steps[i + 1:]]
            print(f"\nSHIP STOPPED at [{i + 1}/{len(steps)}] {step.title} (exit {rc}).",
                  file=sys.stderr)
            if remaining:
                print("NOT RUN: " + " · ".join(remaining), file=sys.stderr)
            print("Fix the step's own report, then re-run ship — every step is safe to repeat.",
                  file=sys.stderr)
            return rc
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    repo: Path | None = None
    note_file: Path | None = None
    partial = keep_note = note_cites_other_runs = False
    access_baseline: Path | None = None
    worklist: Path | None = None
    reconcile: Path | None = None
    fragments_dir: Path | None = None
    agent_transcripts: Path | None = None
    verdicts: list[Path] = []
    it = iter(args)
    for a in it:
        if a == "--note-file":
            note_file = Path(next(it, ""))
        elif a == "--partial":
            partial = True
        elif a == "--keep-note":
            keep_note = True
        elif a == "--note-cites-other-runs":
            note_cites_other_runs = True
        elif a == "--access-baseline":
            access_baseline = Path(next(it, ""))
        elif a == "--worklist":
            worklist = Path(next(it, ""))
        elif a == "--reconcile":
            reconcile = Path(next(it, ""))
        elif a == "--fragments":
            fragments_dir = Path(next(it, ""))
        elif a == "--agent-transcripts":
            agent_transcripts = Path(next(it, ""))
        elif a == "--verdicts":
            verdicts.append(Path(next(it, "")))
        elif a.startswith("-"):
            print(f"ship: unknown option '{a}'\n{USAGE}", file=sys.stderr)
            return 2
        elif repo is None:
            repo = Path(a)
        else:
            print(f"ship: unexpected argument '{a}'\n{USAGE}", file=sys.stderr)
            return 2
    if repo is None:
        print(f"ship: <repo> is required\n{USAGE}", file=sys.stderr)
        return 2
    if note_file is not None and not note_file.is_file():
        print(f"ship: --note-file {note_file} does not exist — write the note first "
              "(the grounding report from the prepare phase is what it is written from)",
              file=sys.stderr)
        return 2
    inputs = derive_inputs(repo, note_file=note_file, partial=partial, keep_note=keep_note,
                           note_cites_other_runs=note_cites_other_runs,
                           access_baseline=access_baseline, worklist=worklist,
                           reconcile=reconcile,
                           verdicts=tuple(verdicts) if verdicts else None,
                           fragments_dir=fragments_dir,
                           agent_transcripts=agent_transcripts)
    if isinstance(inputs, str):
        print(f"ship: {inputs}", file=sys.stderr)
        return 2
    if inputs.reconcile is None:
        print("ship: note — no reconcile.json found; assemble runs WITHOUT --reconcile. If the "
              "build authored one elsewhere, stop and pass --reconcile: an assemble without it "
              "silently reverts every assignment.")
    # NAME the verdict files `grounding write` will not be given. Dropping them is what lets the
    # step run at all (see `_pinned_verdict_flags`), and in the normal case it costs only re-votes
    # — but where a dropped file holds a claim's ONLY vote, the record will report that claim as
    # unchallenged. A silent drop would make that indistinguishable from nobody having voted.
    dropped = post_pin_verdicts(inputs)
    if dropped:
        print(f"ship: note — {len(dropped)} verdict file(s) hold claims outside the pinned "
              f"worklist, so `grounding write` is given the other "
              f"{len(inputs.verdicts) - len(dropped)}: "
              f"{', '.join(p.name for p in dropped)}. `finalize` still reads all "
              f"{len(inputs.verdicts)}. Those votes count toward the LIVE map, never toward "
              f"`claims_challenged`, which is pinned to the worklist the skeptics were given.")
    # AN UNREADABLE APPEAL WORD STOPS THE RUN, before any step consumes the files. `ship` globs
    # `closer-*.json` into every grounding step, so a misspelt `verdict` is no longer inert: the row
    # falls to the SKEPTIC side, its `grounded: true` turns a refutation into a tie, and the
    # refutation gate exits 0 saying nothing survives. `ship` runs no `grounding lint`, so the check
    # that catches it has to be here as well.
    from coyomap.anchor_drift import load_verdicts        # lazy, like `_dispatch`
    from coyomap.grounding import closer_faults
    all_rows, _notes = load_verdicts([str(v) for v in inputs.verdicts])
    faults = closer_faults(all_rows)
    if faults:
        for fault in faults:
            print(f"ship: {fault}", file=sys.stderr)
        print("ship: STOPPED before step 1 — an appeal nobody can read must not reach a step that "
              "counts it.", file=sys.stderr)
        return 2
    rc = run_plan(build_plan(inputs), default_runner)
    if rc != 0:
        return rc
    if inputs.note_file is None:
        print("\nSHIP PREPARED — the grounding report above is the reconcile worklist. Read it "
              "whole, then write the grounding note to a file.\n"
              "  While you write it: the Architecture line texts (method.md, closing step 5b), "
              f"starting with `coyomap line-texts pending --map {inputs.repo}/.coyomap/project-map.json "
              "--out <file>`.\n"
              f"  Next: coyomap ship {inputs.repo} --note-file <path> [--partial]")
    else:
        print("\nSHIP COMPLETE — quote finalize's verdict line in the commit message "
              f"(gate block at {inputs.gate_block}), then commit the map, the .md, the pre-index, "
              "provenance and the line texts. finalize printed the exact `git add -f` line ABOVE, in this output — "
              "the report file does not carry it."
              + _coverage_line(inputs))
    return 0


def _coverage_line(s: ShipInputs) -> str:
    """The one number the OPERATOR REPORT keeps getting wrong, printed where the operator writes it.

    The build's closing message to its user is written from what the lead remembers, and what the
    lead remembers is `claims_total` — the size of the worklist the skeptics were given. That is not
    coverage of the SHIPPED map: a claim reworded after the vote stays in the map and loses its
    verdict. Two builds in a row headlined "all N claims challenged" while the record beside them
    said otherwise — argus 2026-09-01 shipped "454 claims, all challenged" over 440 with a verdict.

    The number already existed, in `grounding.json` as `claims_live_challenged`, and it is printed
    by `grounding write`, in `gate-block.md`, and twice in the finalize report. It was missing from
    the ONE place the sentence gets written, hundreds of lines after those. So it is repeated here,
    last, where the operator report is composed.

    Silent when the record cannot be read: an unreadable grounding file is `finalize`'s problem to
    report, and a second voice guessing at it would only add noise to a run that already failed."""
    try:
        record = json.loads((s.header.parent / "grounding.json").read_text(encoding="utf-8"))
        g = record["grounding"]
        pinned = int(g["claims_total"])
        live_done = int(g["claims_live_challenged"])
        # The LIVE size is not stored directly, and must not be approximated by the pinned one —
        # the whole defect is that the two differ. `build_record` writes both differences, so the
        # live total is exact: pinned, minus the claims that left the map, plus the ones that
        # arrived after the pin.
        live_total = pinned - int(g["claims_superseded"]) + int(g["claims_added_since"])
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    if live_done >= live_total:
        return (f"\n\nCOVERAGE — every one of the shipped map's {live_total} claim(s) carries a "
                f"verdict. Quote {live_total}, not the pinned worklist's {pinned}: the two are the "
                f"same number only when nothing was reworded after the vote.")
    from coyomap.grounding import unvoted_reason   # lazy, like `_dispatch`
    unvoted = live_total - live_done
    return (f"\n\nCOVERAGE — say this, and NOT \"all {pinned} claims challenged\": the shipped map "
            f"carries {live_total} claim(s), of which {live_done} have a verdict and "
            f"{unvoted} do NOT. " + unvoted_reason(unvoted, int(g.get("claims_added_since", 0)))
            + " `claims_total` counts the PINNED worklist and will keep reading as full coverage.")


if __name__ == "__main__":
    raise SystemExit(main())
