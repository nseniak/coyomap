#!/usr/bin/env python3
"""`coyomap scope` — the up-front briefing: WHICH files will be analyzed, and WHAT the map is pinned to.

Two facts decide whether a map can be trusted, and both were previously discoverable only by reading
the method or the code:

  * **What is in scope.** The file set comes from git, so a `.gitignore`d tree is simply absent from
    the map — and absent without a word, which reads exactly like "coyomap looked and found nothing
    there". `.coyomap/.ignore` narrows it further. The user has to be told, once, before the build.
  * **What the pin means.** The map records the commit it describes. When the working tree is dirty
    the map describes code that commit does not contain, so the pin is a promise the repo cannot
    keep — `method.md` already blocks on this, but only at the END, after the whole build (one run
    lost ~2 hours to it). Saying it FIRST turns a late block into an early choice.

Text out, no exit-code signalling: this is a briefing a human reads, and the caller (dispatch) acts
on what it says. Stdlib-only (the `cli.py` dependency firewall); the counts come from the same walk
the pre-index and the validator use, so the briefing can never describe a different tree than the
one that gets mapped.
"""
from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

from coyomap import provenance
from coyomap.ignorefile import IGNORE_REL, bad_line_disclosure, ignore_report
from coyomap.preindex_lib import iter_source_files
from coyomap.reporting import shown

# How many dirty paths to name before the `+N more` tail. Enough to recognize the change, short
# enough that the pin paragraph stays readable when someone runs coyomap mid-refactor.
DIRTY_SHOWN = 8


@dataclass
class Pin:
    """What the map would be pinned to right now."""
    sha: str | None            # short sha of HEAD, None when there is no commit (or no git)
    date: str | None           # HEAD's commit date, YYYY-MM-DD
    dirty: tuple[str, ...]     # repo-relative paths changed but not committed (excluding .coyomap/)


def _git(root: Path, *args: str) -> str | None:
    """git stdout, or None when git is unavailable / the command failed (not a repo, no commit yet)."""
    try:
        out = subprocess.run(["git", "-C", str(root), *args],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def read_pin(root: Path) -> Pin:
    """HEAD + the uncommitted CODE paths.

    coyomap's own `.coyomap/` files are excluded exactly as `method.md`'s pin gate excludes them:
    the map, its view and its reports are always in flux and the workflow commits them itself, so
    counting them would make every run look dirty and train the user to wave the warning through.
    """
    sha = _git(root, "rev-parse", "--short", "HEAD")
    date = _git(root, "show", "-s", "--format=%cs", "HEAD")
    # ONE definition of "dirty", shared with `provenance.stamp` (which records the operator's answer)
    # and `lint-fragment` (which checks it). It used to live here alone and exclude `.coyomap` only,
    # so `.coyomap-eval/` — this toolchain's own git-ignored scratch — read as the user's uncommitted
    # code and was the sole reason one build asked the operator to pin dirty at all.
    dirty = provenance.dirty_paths(root)
    return Pin(sha=(sha or "").strip() or None, date=(date or "").strip() or None, dirty=dirty)


def scope_report(root: Path) -> list[str]:
    """The briefing, as lines. Two sections — what gets read, and what the map will claim."""
    walk = iter_source_files(root)
    out: list[str] = ["What coyomap will analyze", ""]
    if walk.used_git:
        out += [
            "  Files come from git: everything git tracks, plus files you created but have not",
            "  added yet. Anything in .gitignore is left out — git decides that, so a .gitignore",
            "  inside a subfolder counts too.",
        ]
    else:
        out += [
            "  This folder is not a git repository, so coyomap reads the files on disk and",
            "  .gitignore is NOT applied — only coyomap's built-in exclusions narrow the tree.",
        ]
    out += [
        "",
        f"  {len(walk.files)} file(s) will be analyzed.",
        f"  {walk.skipped_excluded} file(s) left out by coyomap's built-in list"
        " (node_modules/, dist/, build output, lock files and friends).",
    ]

    # A PREVIOUS MAP sitting in the tree is source as far as the walk is concerned. `.coyomap/` is
    # excluded by name; a hand-made copy beside it is not, and a build that archived its old map by
    # hand — `mv .coyomap .coyomap-archive-<date>` — silently pulled ~59 files of it into the harvest
    # scope (2731 analysed against 2672 after the archive was filed properly). That is the one
    # artifact the method forbids a rebuild from reading, so it cannot be left to the reader to spot
    # in a file count. `coyomap-eval archive` is the supported way to file one.
    # KEYED ON CONTENT, not on a name. Matching `.coyomap*` caught the hand-made archive that
    # prompted this and missed every other shape a copied map takes — `map-backups/`, which is where
    # this tool's OWN backup command writes, and any `coyomap-old/`. The thing that makes a
    # directory a stray is that it holds a map, so that is what to look for. Only inside the files
    # the walk is actually going to analyse: a map under an ignored path is already excluded, and
    # warning about it would be noise.
    homes: set[str] = set()
    for f in walk.files:
        if f.name not in ("project-map.json", "project-map.md"):
            continue
        try:
            rel = f.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        homes.add(rel.parent.as_posix() or ".")
    strays = sorted(h for h in homes if h != ".coyomap" and not h.startswith(".coyomap/"))
    if strays:
        out += [
            "",
            f"  WARNING: {len(strays)} folder(s) inside the analysis set contain a project map and "
            f"will be read as SOURCE: {', '.join(strays)}.",
            "  A previous map is not source — mapping your own map inflates every count and feeds "
            "the rebuild the one artifact the method forbids it to read.",
            "  If it is an archive, file it with `coyomap-eval archive` (it lands under "
            ".coyomap/dev-rebuilds/, which is excluded); otherwise add it to .coyomap/.ignore.",
        ]

    # The ignore file gets its own per-pattern block, never a bare total: it is the one input that
    # can hide a real gap from the checks whose job is finding gaps, so a pattern that removed
    # nothing must be visible as such (same rule, and the same wording, as `validate`'s disclosure).
    # A line that parsed to nothing misleads the same way, since its author believes it excludes
    # something, so it is named too, in validate's own sentence. Gating on the rules alone made the
    # worst case silent: a file whose EVERY line is unusable has no rules, so the briefing said
    # nothing at all.
    if walk.ignore.rules or walk.ignore.bad_lines:
        rep = ignore_report(walk.ignore, walk.ignore_hits)
        out.append(f"  {rep.removed} file(s) removed by {IGNORE_REL.as_posix()}:")
        out += [f"    {line}" for line in rep.per_rule]
        if rep.unused:
            out.append(f"    warning: {len(rep.unused)} pattern(s) removed nothing: "
                       f"{shown(list(rep.unused), 5, unit='pattern(s)')}")
        out += [f"    warning: {line}" for line in bad_line_disclosure(rep.bad_lines)]

    pin = read_pin(root)
    out += ["", "What the map will be pinned to", ""]
    if pin.sha is None:
        out += [
            "  There is no commit here, so the map cannot be pinned to one. Commit your code first",
            "  if you want the map to say which version of the code it describes.",
        ]
        return out

    out.append(f"  The map records the commit it describes: {pin.sha}"
               f"{f' ({pin.date})' if pin.date else ''}.")
    if not pin.dirty:
        out.append("  Your code is committed, so the map and that commit will match.")
        return out
    out += [
        "",
        f"  {len(pin.dirty)} file(s) in your code are changed but not committed:",
        f"    {shown(list(pin.dirty), DIRTY_SHOWN, sep=chr(10) + '    ', unit='file(s)')}",
        "",
        "  coyomap maps what is on disk, so the map WILL describe those changes — but the commit",
        "  it points at does not contain them. The map and its pin would be out of step, and a",
        "  later change analysis, which compares your code against the pin, would report the same",
        "  changes again. Committing first avoids that; continuing is fine too, and the pin is",
        f"  then recorded as {pin.sha}-dirty to say so.",
    ]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="coyomap scope",
        description="Say which files coyomap will analyze and what the map will be pinned to.")
    ap.add_argument("--repo", default=".", help="repo root to describe (default: cwd)")
    args = ap.parse_args(argv)
    print("\n".join(scope_report(Path(args.repo).resolve())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
