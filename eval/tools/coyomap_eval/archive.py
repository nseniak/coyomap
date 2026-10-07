#!/usr/bin/env python3
"""Archive a repo's coyomap map into `.coyomap/dev-rebuilds/NNNN/`, clearing the way for a rebuild.

**A COYOMAP-DEVELOPER convention, not something a user should adopt** — hence the `dev-` prefix, on
disk where it cannot be missed. A user's map EVOLVES INCREMENTALLY alongside their code: a from-scratch
rebuild is a first-run event for them, so they never accumulate previous maps. Rebuilding over and over
is what someone changing coyomap itself does, and these snapshots are the baselines `/coyomap-retro`
and `/coyomap-eval` (both developer commands) compare a fresh map against. No production code path
reads this directory.

WHY THIS EXISTS. `method/dispatch.md` decides Build vs Analyze by looking for
`.coyomap/project-map.json` **in the working tree** — "a deleted working-tree file is a deliberate
signal to start from scratch", and it forbids recovering the old map from git. So a from-scratch
rebuild means getting the current map out of the way first, and the only safe way to do that is to
MOVE it, never delete it: the old map is the baseline you diff the new one against, and it holds
curation (recorded exceptions, adjudications, Phase-4 corrections) that a rebuild must re-derive.

Doing it by hand is how the archives already in the wild got their shape — one live repo has ten of
them — and hand-moving is exactly where a stray `rm` or a clobbered directory costs a whole build.

WHAT MOVES. Everything in `.coyomap/` except `dev-rebuilds/` itself and the two files that are
DECLARATIONS ABOUT THE REPO rather than build output — `.gitignore` (coyomap writes it, and the next
assemble expects it) and `.ignore` (which code the map is not meant to describe). That is
deliberately a denylist, not a list of known filenames: a future artifact should be archived by
default rather than silently left behind to confuse the next build.

WHY `.ignore` STAYS. It is scope, not output. `iter_source_files` honours it, so it decides which
files feed the coverage check AND the code-derived component expectation E. Archiving it away
silently rescopes the tree for the next build and for every later scoring of ANY map: measured on
this repo, moving `.ignore` aside took E from 14 to 37 (+164%), which flipped the current map's
granularity band from DRIFT (36 vs 14) to PASS (36 vs 37) with no change to the map or the code.
The eval compares an archived map against a current one, so a rescope between the two is exactly
the confound its same-code guard exists to prevent — and the guard cannot see it, because it
excludes `.coyomap/` wholesale. Keeping the file in place removes the trap instead of documenting it.

    coyomap-eval archive <repo-root> [--dry-run]

WHY IT IS A `coyomap-eval` SUBCOMMAND. It was a loose script under `eval/scripts/`, invoked by an
absolute path that every caller had to spell out — the shape that makes a tool easy to hand-roll
around instead. `coyomap-eval` is the developer-only CLI (`eval/` is the developer-only tree, and
the `/coyomap-eval` and `/coyomap-retro` skills say so), so this belongs beside `retro-precheck`
and `process`: discoverable from `coyomap-eval --help`, and reachable without knowing a path.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from coyomap.buildstate import STATE_NAME, read_state

#: The container for every archived map. NESTED, so `.coyomap/` holds one entry instead of the dozen
#: sibling dot-directories the flat `.old-ignore*` convention accumulated.
ARCHIVE_DIR = "dev-rebuilds"
#: Zero-padded, so a lexical sort IS a numeric sort. The flat convention was unpadded, which made
#: `-9` sort after `-10` as text; the docstring below warned about it and a consumer still got it
#: wrong (a baseline picker sorted on name length and chose the wrong archive in 28 of 40 trials).
#: Padding removes the trap instead of documenting it.
ARCHIVE_WIDTH = 4
# Kept in place: `.gitignore` is coyomap's own (it ignores build-fragments/ and the archives),
# `.ignore` is the repo's analysis-scope declaration and moving it rescopes E and coverage for every
# later build and score (see WHY `.ignore` STAYS above), and archiving the archive container would
# nest it one inside the next on every run.
# `fanout-timings.json` is cross-build input, not build output: `timings order` reads the most
# recent recording per slice to order the NEXT build's dispatch, and archiving it made that verb
# start cold on a repo with 26 rebuilds behind it.
KEEP = {".gitignore", ".ignore", "fanout-timings.json", ARCHIVE_DIR}


def next_archive_dir(coyomap: Path) -> Path:
    """The next archive: `dev-rebuilds/0001`, `0002`, … — zero-padded so any sort is right.

    ALWAYS highest + 1, never the smallest free number. Filling a gap left by a manual delete keeps
    the names dense but destroys what the number is for: with `0001`, `0002`, `0003` on disk, deleting
    `0002` and archiving again would put the NEWEST map in `0002`, between two older ones. The common
    cleanup — pruning the OLDEST archives — is worse still: the next map would land in `0001`, the name
    that reads as "the first one", so the sequence reads exactly backwards. Monotonic numbering means
    the number always encodes recency and cannot lie. The cost is a cosmetic gap after a delete, which
    is a far better failure than a wrong order."""
    container = coyomap / ARCHIVE_DIR
    highest = 0
    if container.is_dir():
        for p in container.iterdir():
            if p.is_dir() and p.name.isdigit():   # ignore any hand-named sibling ("broken", "keep")
                highest = max(highest, int(p.name))
    return container / f"{highest + 1:0{ARCHIVE_WIDTH}d}"


def movable_entries(coyomap: Path) -> list[Path]:
    """Everything that should be archived, sorted for a stable report.

    An OPEN build state stays too: it belongs to the build that is starting, not to the map being
    moved aside. The method opens the state once the old map is archived, but a lead that opens it
    first would otherwise lose it here, and every later event of that build would be dropped in
    silence, because only `state start` creates the file. An ENDED state moves with its map."""
    state = read_state(coyomap.parent)
    keep = KEEP | ({STATE_NAME} if state is not None and state.is_open else set())
    return sorted((p for p in coyomap.iterdir() if p.name not in keep), key=lambda p: p.name)


def archive(root: Path, dry_run: bool = False) -> tuple[Path | None, list[Path]]:
    """Move the map aside. Returns `(archive dir, entries moved)`; `(None, [])` when there is
    nothing to archive, which is not an error — it is the state a fresh build wants."""
    coyomap = root / ".coyomap"
    if not coyomap.is_dir():
        raise FileNotFoundError(f"no .coyomap/ directory under {root}")
    entries = movable_entries(coyomap)
    if not entries:
        return None, []
    dest = next_archive_dir(coyomap)
    if dry_run:
        return dest, entries
    dest.mkdir(parents=True)   # `dev-rebuilds/` may not exist yet
    moved: list[Path] = []
    try:
        for p in entries:
            shutil.move(str(p), str(dest / p.name))
            moved.append(p)
    except OSError:
        # Put back what already moved, so a failure half-way leaves the map usable rather than
        # split across two directories with no record of which half is which.
        for p in moved:
            shutil.move(str(dest / p.name), str(p))
        dest.rmdir()
        if not any((dest.parent).iterdir()):      # we created the container on this run — undo that too
            dest.parent.rmdir()
        raise
    return dest, entries



def previous_maps(root: Path) -> list[tuple[Path, str, str]]:
    """Every archived map under `.coyomap/`, newest id first: (map path, built_at, session id).

    `archive` could file a map and then never say where any of them were. A retrospective had to
    locate the baseline by hand — and located it in `.coyomap/.old-ignore-6/`, because the repo used
    a hand-rolled archive convention that predates this command. Any directory holding a
    `project-map.json` is reported, not just `dev-rebuilds/NNNN/`: a convention this command did not
    create is exactly the one a reader cannot guess, and hiding it does not make it go away.

    Provenance is read best-effort — an archive too old to carry one is still listed, with blanks.
    """
    coyomap = root / ".coyomap"
    if not coyomap.is_dir():
        return []
    found: list[tuple[Path, str, str]] = []
    for d in sorted(coyomap.iterdir()) + sorted((coyomap / ARCHIVE_DIR).glob("*")
                                                if (coyomap / ARCHIVE_DIR).is_dir() else []):
        if not d.is_dir() or d.name == ARCHIVE_DIR:
            continue
        m = d / "project-map.json"
        if not m.is_file():
            continue
        built_at = session = ""
        try:
            prov = json.loads((d / "provenance.json").read_text(encoding="utf-8"))
            sessions = prov.get("sessions") or []
            if sessions:
                built_at = str(sessions[-1].get("built_at", ""))
                session = str(sessions[-1].get("session_id", ""))
        except (OSError, ValueError, AttributeError, IndexError, TypeError):
            pass
        found.append((m, built_at, session))
    found.sort(key=lambda t: (t[1], t[0].as_posix()), reverse=True)
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="coyomap-eval archive",
        description="Move a repo's coyomap map into .coyomap/dev-rebuilds/NNNN/ so the next run "
                    "builds from scratch (dispatch.md reads the WORKING TREE to choose the mode).")
    ap.add_argument("root", type=Path, help="the mapped repo's root directory")
    ap.add_argument("--dry-run", action="store_true", help="show what would move, write nothing")
    ap.add_argument("--list", action="store_true", dest="list_only",
                    help="list the archived maps already under .coyomap/ and exit — the baseline a "
                         "retrospective or a comparison needs, which nothing else could answer")
    args = ap.parse_args(argv)

    root: Path = args.root.expanduser().resolve()
    if args.list_only:
        rows = previous_maps(root)
        if not rows:
            print(f"archive: no archived map under {root / '.coyomap'} — nothing to compare against. "
                  f"A from-scratch rebuild files one here; a user's map evolves in place and never "
                  f"accumulates any.")
            return 0
        print(f"archived map(s) under {root / '.coyomap'}, newest first:")
        for m, built_at, session in rows:
            stamp = built_at or "(no provenance)"
            sid = f"  session {session[:8]}…" if session else ""
            print(f"  {stamp:<20} {m.relative_to(root)}{sid}")
        return 0
    try:
        dest, entries = archive(root, dry_run=args.dry_run)
    except (FileNotFoundError, OSError) as exc:
        print(f"archive: {exc}", file=sys.stderr)
        return 1

    if dest is None:
        print(f"archive: nothing to archive in {root / '.coyomap'} "
              "(already clear — a build here starts from scratch)")
        return 0
    verb = "would move" if args.dry_run else "moved"
    rel = dest.relative_to(root)
    print(f"archive: {verb} {len(entries)} entry/entries -> {rel}/")
    for p in entries:
        # After a real move the source path is gone, so ask the side that now holds it.
        landed = p if args.dry_run else dest / p.name
        print(f"  {p.name}{'/' if landed.is_dir() else ''}")
    if not args.dry_run:
        print("\nThe working tree now has no project-map.json, so `/coyomap` will BUILD.\n"
              f"The previous map is intact in {rel}/ — keep it: it is the baseline the new map is "
              "compared against, and it holds curation a rebuild has to re-derive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
