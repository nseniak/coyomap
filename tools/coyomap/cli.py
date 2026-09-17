#!/usr/bin/env python3
"""The single `coyomap` command — dispatches to the pre-index, validator, and viewer.

DEPENDENCY FIREWALL: this module imports only stdlib at top level. Each subcommand
imports its implementation lazily, inside its own branch, so `coyomap validate` and
`coyomap render` never load the pre-index code path and stay free of any third-party
import (tree-sitter). See internal/docs/design-notes.md.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from coyomap import __version__
from coyomap.model import WrongMapError, old_map_folder_hint

USAGE = """usage: coyomap <command> [args...]

Commands:
  ship       The build's closing sequence (method.md's numbered list, steps 2-12) as one
             command. Without --note-file it PREPARES (anchor-drift → apply-drift →
             assemble → grounding report) and stops so the note is written from the
             report; with --note-file it FINISHES through finalize. A failed step stops
             the run and names every step that did not run.
  preindex   Build the structural pre-index (.coyomap/preindex.json). Needs the
             `preindex` extra (tree-sitter); install with: pip install -e '.[preindex]'
  validate   Validate a map (schema + semantic checks — is it WELL-FORMED?).
  audit      Adversarial pass over a built map (is it SELF-CONTRADICTORY?): L1
             deterministic contradiction checks + an L2 grounding worklist.
  contract   Print exactly the text one fan-out agent should receive (harvest, trace,
             rules, skeptic) — the contract's agent half, with the writing rules
             appended for the phases whose agents author map prose. The lead never
             handles the template, so its lead-facing header cannot reach an agent.
  render     Render a map's committed markdown view (model → project-map.md). The
             interactive diagram is served by `serve`, not written to a file.
  serve      Serve the interactive viewer + file browser + code viewer over a local
             HTTP server, building each map's diagram on demand from its model (files
             read from git at the map's commit). One server covers every project.
  export     Write a map as a STATIC SITE — a folder of plain files (the viewer, the map's
             data, and the code at its commit). Host it anywhere and share the link: a
             reader needs no repo and no coyomap. Everything works but the change-impact
             explorer, which needs git behind it.
  url        The address that opens the served map on ONE element, already selected:
             `coyomap url UC12` prints http://127.0.0.1:<port>/coyomap/<slug>/#v=usecase&uc=UC12
             with the running server's port, or the path alone when no server runs.
             `--context` gives the home view with the element lit instead of its page.
  assemble   Merge build agents' structured-row fragments into the canonical
             project-map.json (+ generated views).
  lint-fragment  Self-check ONE build fragment before returning it (schema + anchor
             format + extra-key conventions, and with --repo that anchors exist).
  anchor-drift  Deterministic Layer-2 check: for each grounding-confirmed claim, flag
             when the stored `where` line drifts from the line the skeptics found.
  grounding  Derive the map's `grounding` record from the skeptics' verdict files and the
             PINNED audit worklist (`grounding write`). The four counts are what `validate`
             blocks on, so they are never hand-tallied.
  fix        Apply a reconcile edit to the model in place (apply-drift / drop-edge /
             dedup-relation / dedup-edge / security-row / dedup-security) — the mechanical
             fixes the method's Phase-3/4
             reconcile needs, so they are never hand-scripted. Re-run validate → audit →
             render after.
  provenance Stamp WHICH session built this map and WHEN into .coyomap/provenance.json — the
             file `finalize` requires before the map is committed. It used to be produced only by
             a script in the coyomap clone that the shipped CLI does not install, so a build could
             be told to produce an artifact no command could make.
  context    One claims batch with its evidence beside it: per claim, the map record of
             every element it names and the code around its anchor. A skeptic spends its
             run fetching exactly this, and 52-62% of its bill is re-reading what it
             fetched.
  timings    What each fan-out slice ACTUALLY took (`record`), and that phase's slices
             longest-first for the next build's dispatch (`order`). Build telemetry beside
             the map, never inside it — the method's "dispatch the longest slice first" was
             folklore until something wrote the minutes down.
  record     Append (or --replace) one `<id>: <why>` line under a recorded-exception extras
             heading — the one writer for an advisory an operator judged acceptable, so a
             record is never a hand-rolled string append into the wrong heading.
  diff       What changed between two maps, ROW BY ROW — added / dropped / changed, with the
             fields that moved. Two assembles of the SAME work (old map vs new, before vs after a
             `fix`), never two independent builds: those agree on neither numbering nor wording.
  dump       Emit the parsed model as JSON — whole, or a fixed slice (--id /
             --record / --edges / --members). Read-only lookups over the model.
  reconcile  Expand path RULES into an explicit `reconcile.json` (the synthesis
             assignment pass), resolving ids against the build's own --fragments
             (or --map, once one exists) and reporting every rule that matched
             nothing. Feed the result to `assemble --reconcile`.
  finalize   The pre-commit read: validate + audit + the shape-only anchor-drift
             pass, and the verdict-based one too ONLY with --verdicts (without it
             that leg does not run). Written to .coyomap/finalize-report.{json,md}
             with whole lists. Adds no check of its own and compares nothing against
             a previous map. A convenience wrapper, not an enforcement point — exit 1
             for what validate/audit already block on, or when a check did not run.
  scope      The up-front briefing, before any work: which files will be analyzed
             (git decides — .gitignore is out), what `.coyomap/.ignore` removed, and
             which commit the map will be pinned to, warning when uncommitted code
             would put the map and its pin out of step.
  balance    Report per-diagram fan-out (target 5±2), the inter-subsystem edge
             matrix, and advisory split proposals for over-dense diagrams —
             apply accepted proposals via a Direct map change.

The method-quality regression eval is a separate command: `coyomap-eval` (see eval/).

Global:
  --version  Print the coyomap version and exit.
  -h/--help  Show this help and exit.

Run `coyomap <command> --help` for command-specific options."""


def _default_map(argv: list[str], cwd: "Path | None" = None) -> list[str]:
    """When no positional map is given, default to `.coyomap/project-map.json`. A folder that still
    holds the old `.coyodex/` map and no new one is told what changed and what to do."""
    flags_with_value = {"--repo"}
    expect_value = False
    for a in argv:
        if expect_value:
            expect_value = False
        elif a in flags_with_value:
            expect_value = True
        elif not a.startswith("-"):
            return argv  # an explicit map was given
    hint = old_map_folder_hint(cwd or Path.cwd())
    if hint:
        print(f"WARNING: {hint}", file=sys.stderr)
    return argv + [".coyomap/project-map.json"]


def main(argv: list[str] | None = None) -> int:
    # Line-buffer stdout so the two streams interleave in PROGRAM order under a pipe.
    #
    # Every command here prints notes on stdout and `ERROR:` / `WARNING:` / `… FAILED` on stderr.
    # Piped stdout is block-buffered and flushes at exit while stderr is unbuffered, so
    # `cmd 2>&1 | tail -N` re-orders the failure to the HEAD of the pipe and keeps the harmless
    # notes in the tail. A live build read that tail three times, saw a reassuring `note:` line
    # each time, and went on reading a map that `assemble` had refused to write — for 16 turns,
    # taking a whole round of prose fixes with it. One line here fixes it for every subcommand at
    # once; a per-site `flush()` would have to be right at ~200 stderr call sites and stay right.
    #
    # Guarded on the concrete type: an in-process caller (pytest's capture, a harness) may replace
    # stdout with a plain stream that has no `reconfigure`, and the bug does not exist there anyway.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    if args[0] in ("--version", "-V"):
        print(__version__)
        return 0

    cmd, rest = args[0], args[1:]
    try:
        return _dispatch(cmd, rest)
    except WrongMapError as exc:
        # ONE handler for every subcommand. `resolve_map_path` refuses a read of the clone's own
        # map, and that refusal reaches a dozen `main`s — `validate` grew its own handler and the
        # rest printed a ten-line traceback with the message buried at the bottom. A refusal whose
        # whole value is that a person reads it must not arrive as a stack trace, and adding the
        # same handler twelve times is how one of them gets forgotten.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _dispatch(cmd: str, rest: list[str]) -> int:
    if cmd == "preindex":
        from coyomap import preindex  # lazy: only this path may touch tree-sitter
        return preindex.main(rest)
    if cmd == "validate":
        from coyomap import validate_model  # stdlib-only
        return validate_model.main(_default_map(rest))
    if cmd == "audit":
        from coyomap import audit_model  # stdlib-only
        return audit_model.main(_default_map(rest))
    if cmd == "contract":
        from coyomap import contract  # stdlib-only; reads the model too, for `closer --from-verdicts`
        return contract.main(rest)
    if cmd == "render":
        from coyomap.viewer import render  # stdlib-only
        return render.main(rest)
    if cmd == "serve":
        from coyomap.viewer import serve  # stdlib-only (http.server + git subprocess)
        return serve.main(rest)
    if cmd == "export":
        from coyomap.viewer import export  # stdlib-only (git subprocess + json)
        return export.main(rest)
    if cmd == "url":
        from coyomap.viewer import url  # stdlib-only; asks the running server, writes nothing
        return url.main(rest)
    if cmd == "assemble":
        from coyomap import assemble  # stdlib-only
        return assemble.main(rest)
    if cmd == "diff":
        from coyomap import mapdiff  # stdlib-only; two maps of one lineage — it says when they are not
        return mapdiff.main(rest)
    if cmd == "dump":
        from coyomap import dump  # stdlib-only; defaults to .coyomap/project-map.json
        return dump.main(rest)
    if cmd == "scope":
        from coyomap import scope  # stdlib-only; the walk + git, no map needed
        return scope.main(rest)
    if cmd == "balance":
        from coyomap import balance  # stdlib-only; defaults its own map path
        return balance.main(rest)
    if cmd == "reconcile":
        from coyomap import reconcile_build  # stdlib-only
        return reconcile_build.main(rest)
    if cmd == "lint-fragment":
        from coyomap import lint_fragment  # stdlib-only
        return lint_fragment.main(rest)
    if cmd == "anchor-drift":
        from coyomap import anchor_drift  # stdlib-only
        return anchor_drift.main(rest)
    if cmd == "finalize":
        from coyomap import finalize  # stdlib-only; shells out to coyomap-eval for the compare leg
        return finalize.main(_default_map(rest))
    if cmd == "grounding":
        from coyomap import grounding  # stdlib-only; derives the record validate blocks on
        return grounding.main(rest)
    if cmd == "fix":
        from coyomap import fix  # stdlib-only; owns its own second-level (verb) dispatch
        return fix.main(rest)
    if cmd == "record":
        from coyomap import record  # stdlib-only; the one writer for a recorded exception
        return record.main(rest)
    if cmd == "timings":
        from coyomap import timings  # stdlib-only; build telemetry beside the map, never in it
        return timings.main(rest)
    if cmd == "context":
        from coyomap import context  # stdlib-only; reads the map and the tree, calls no model
        return context.main(rest)
    if cmd == "provenance":
        from coyomap import provenance  # stdlib-only; the file finalize requires before a commit
        return provenance.main(rest)
    if cmd == "ship":
        from coyomap import ship  # stdlib-only; orchestrates the other subcommands in-process
        return ship.main(rest)

    # THE ERROR IS PRINTED TWICE, HEAD AND TAIL. A usage block is 40-odd lines, and a build reads a
    # failed command through `2>&1 | tail -5` — which shows the LAST five lines of the usage text
    # and not one word of what went wrong. On the 2026-09-02 mcpolis build a real argument error
    # scrolled past exactly that way and the pipeline exited 0 (the pipe reports `tail`'s status),
    # so the run read as a success. The head line is for a reader who sees the whole thing; the tail
    # line is for the one who sees five lines of it.
    line = f"coyomap: unknown command '{cmd}'"
    print(f"{line}\n", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    print(f"\nERROR: {line}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
