"""Impact engine — the git-facing half (produces `impact_lib`'s inputs, assembles the result).

Design: internal/docs/impact-and-update-design.md (Part I). Read-only git via subprocess (the same
envelope as the serve backend; no shell, timeouts, ref/path safety) with ONE scoped exception:
diffing a RENAMED file against the working tree writes a temp blob (`git hash-object -w`) so both
sides of the fate comparison come from the same diff engine — a loose object, never a ref, GC'd by
git's normal housekeeping.

Frames and paths: the map's anchors live at the pin P (`model.commit`). A change is B→T where each
end is a commit or the working tree. Every changed file is re-expressed in P's frame:
  path@P  ──(rename map P→B)──  path@B  ──(the B→T name-status)──  path@T
Rename maps come from full-tree `--name-status -M` passes (NEVER a single-path pathspec — pathspec
filters before rename detection, which fabricates full-file deletes for renamed files).
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

from coyomap.impact_lib import (
    AnchorRef,
    DirectHit,
    FileFrame,
    Hunk,
    ParsedDiff,
    anchor_index,
    anchors_by_file,
    dir_anchors_for,
    frame_from_two_diffs,
    parse_u0,
    resolve_hits,
)
from coyomap.model import ProjectModel

WORKTREE = "WORKTREE"  # target sentinel: the working tree (tracked edits + untracked files)

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@^~+-]*$")


class ImpactError(ValueError):
    pass


def _git(repo: Path, *args: str, ok_codes: tuple[int, ...] = (0,)) -> bytes:
    """Run git in `repo`; raise ImpactError on unexpected exit. `git diff` exits 1 on differences,
    so diff callers pass ok_codes=(0, 1)."""
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=60)
    if proc.returncode not in ok_codes:
        raise ImpactError(f"git {' '.join(args[:3])}… failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def resolve_ref(repo: Path, ref: str) -> str:
    """A commit sha for `ref` (WORKTREE passes through). Refuses ref-shaped injection."""
    if ref == WORKTREE:
        return WORKTREE
    if not _REF_RE.match(ref):
        raise ImpactError(f"unsafe ref: {ref!r}")
    out = _git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    return out.decode().strip()


# ── the change set ────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Change:
    status: str               # A|M|D|R|C|T (first letter of the name-status code)
    path: str                 # path at the RIGHT side (T); for D, the (left) deleted path
    old_path: str | None = None  # for R/C: the LEFT-side path


def _parse_name_status(out: str) -> list[Change]:
    changes: list[Change] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0]
        if code.startswith(("R", "C")) and len(parts) >= 3:
            changes.append(Change(code[0], parts[2], parts[1]))
        elif len(parts) >= 2:
            changes.append(Change(code[0], parts[1]))
    return changes


def diff_changes(repo: Path, base_sha: str, target: str) -> list[Change]:
    """B→T name-status with rename detection; target may be WORKTREE (adds untracked as A)."""
    args = ["diff", "--name-status", "-M", "--no-color", base_sha]
    if target != WORKTREE:
        args.append(target)
    changes = _parse_name_status(_git(repo, *args, ok_codes=(0, 1)).decode(errors="replace"))
    if target == WORKTREE:
        untracked = _git(repo, "ls-files", "--others", "--exclude-standard").decode(errors="replace")
        seen = {c.path for c in changes}
        changes += [Change("A", p) for p in untracked.splitlines() if p and p not in seen]
    return changes


def rename_map(repo: Path, from_sha: str, to: str) -> dict[str, str]:
    """`{path@to: path@from}` for files RENAMED between the two points (identity pairs omitted)."""
    out: dict[str, str] = {}
    for c in diff_changes(repo, from_sha, to):
        if c.status == "R" and c.old_path:
            out[c.path] = c.old_path
    return out


# ── blob access ───────────────────────────────────────────────────────────────────────────────────

def blob_exists(repo: Path, sha: str, path: str) -> bool:
    try:
        _git(repo, "cat-file", "-e", f"{sha}:{path}")
        return True
    except ImpactError:
        return False


def tree_paths(repo: Path, sha: str) -> set[str]:
    """Every file path in the tree at `sha` — one listing, for a caller that would otherwise ask
    `blob_exists` once per file (17 s on a 300-file map, 8 of them in the calls)."""
    out = _git(repo, "ls-tree", "-r", "--name-only", "-z", sha).decode(errors="replace")
    return {p for p in out.split("\0") if p}


def show_lines(repo: Path, sha: str, path: str) -> list[str]:
    return _git(repo, "show", f"{sha}:{path}").decode(errors="replace").splitlines()


def read_side_lines(repo: Path, sha_or_worktree: str, path: str) -> list[str] | None:
    """The file's lines at a commit or on disk (None when absent/unreadable)."""
    if sha_or_worktree == WORKTREE:
        try:
            return (repo / path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
    try:
        return show_lines(repo, sha_or_worktree, path)
    except ImpactError:
        return None


def _worktree_blob(repo: Path, path: str) -> str:
    """Hash the on-disk file into a loose blob so a renamed worktree file can be diffed blob-to-blob
    (same diff engine on both sides of the fate comparison). A loose object only — no ref."""
    out = _git(repo, "hash-object", "-w", "--", path)
    return out.decode().strip()


def _side_diff(repo: Path, pin: str, p_path: str, side: str, side_path: str,
               p_lines: list[str]) -> ParsedDiff:
    """`diff(P, side)` for one file — the empty diff when the side IS the pin, and the synthetic
    all-deleted diff when the side lacks the file entirely (added/removed relative to that side)."""
    if side == pin:
        return ParsedDiff()
    absent = not (repo / side_path).exists() if side == WORKTREE \
        else not blob_exists(repo, side, side_path)
    if absent:
        return ParsedDiff(hunks=[Hunk(1, len(p_lines), (), tuple(p_lines))])
    return u0_diff(repo, pin, p_path, side, side_path)


def u0_diff(repo: Path, pin: str, p_path: str, side: str, side_path: str) -> ParsedDiff:
    """`git diff -U0` of `pin:p_path` against the file at `side` (a commit sha or WORKTREE),
    always as a blob pair / pinned-tree diff — never a rename-blind single-path pathspec."""
    if side == WORKTREE:
        if side_path == p_path:
            out = _git(repo, "diff", "-U0", "--no-color", pin, "--", p_path, ok_codes=(0, 1))
        else:  # renamed on disk: temp blob so both sides use git's diff
            blob = _worktree_blob(repo, side_path)
            out = _git(repo, "diff", "-U0", "--no-color", f"{pin}:{p_path}", blob, ok_codes=(0, 1))
    else:
        out = _git(repo, "diff", "-U0", "--no-color",
                   f"{pin}:{p_path}", f"{side}:{side_path}", ok_codes=(0, 1))
    return parse_u0(out.decode(errors="replace"))


# ── the orchestrator ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ImpactFile:
    path: str                  # path at T (the right side)
    p_path: str | None         # the same file in P's frame (None = no P-frame)
    status: str
    frame: FileFrame | None = None
    hits: list[DirectHit] = field(default_factory=list)


@dataclass
class ImpactCore:
    pin: str
    base: str
    target: str
    files: list[ImpactFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def hits(self) -> list[DirectHit]:
        return [h for f in self.files for h in f.hits]


#: The build-time structural pre-index (symbols/imports), committed alongside the map.
PREINDEX_JSON = "preindex.json"

Extents = dict[str, list[tuple[int, int, str, str]]]


def load_extents(preindex: dict) -> Extents:
    """The per-file symbol-extent table from a preindex.json document (empty when absent — older
    pre-indexes; every anchor then resolves at file rung, honestly)."""
    raw = (preindex.get("symbols") or {}).get("extents") or {}
    return {f: [(int(r[0]), int(r[1]), str(r[2]), str(r[3])) for r in rows]
            for f, rows in raw.items()}


def load_map_extents(map_json: Path) -> Extents:
    """The symbol-extent table of the pre-index COMMITTED BESIDE a map (`preindex.json`, same
    directory), or `{}` when there is none / it cannot be read.

    One reader, because there are now several consumers — change impact, and the business-rule
    step join, which uses the same table to tell "this exact step" from "inside the same function
    as this step". A missing table degrades every consumer the same way rather than each inventing
    its own silence."""
    path = map_json.parent / PREINDEX_JSON
    if not path.is_file():
        return {}
    try:
        return load_extents(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def compute_impact(repo: Path, model: ProjectModel, extents: Extents,
                   base: str, target: str) -> ImpactCore:
    """Project the B→T change set onto the map's anchors: per changed file, translate the change
    into P's line frame (two `-U0` diffs against the pin) and resolve every hosted anchor through
    the ladder. Ripple/aggregation is the next layer (M2) — this returns files + direct hits."""
    pin = (model.commit or "").removesuffix("-dirty")
    if not pin:
        raise ImpactError("the map carries no commit pin")
    pin = resolve_ref(repo, pin)
    base_sha = resolve_ref(repo, base or pin)
    target_r = target if target == WORKTREE else resolve_ref(repo, target)
    if base_sha == WORKTREE:
        raise ImpactError("base must be a commit (WORKTREE is only a target)")

    anchors = anchor_index(model)
    by_file = anchors_by_file(anchors)
    # P-frame path translation: identity when an endpoint IS the pin; otherwise via rename maps.
    rmap_b = {} if base_sha == pin else rename_map(repo, pin, base_sha)
    rmap_t = ({} if target_r == pin else rename_map(repo, pin, target_r)) if target_r != WORKTREE \
        else rename_map(repo, pin, WORKTREE)

    core = ImpactCore(pin=pin, base=base_sha, target=target_r)
    changes = diff_changes(repo, base_sha, target_r)
    added_names = {Path(c.path).name for c in changes if c.status == "A"}
    for ch in changes:
        left_path = ch.old_path if ch.old_path else ch.path
        # preimages in P's frame from each side; disagreement = outside the pinned frame
        p_from_b = rmap_b.get(left_path, left_path)
        p_from_t = rmap_t.get(ch.path, ch.path) if ch.status != "D" else p_from_b
        p_path: str | None = p_from_b if base_sha != pin else left_path
        if ch.status != "D" and target_r != WORKTREE and target_r == pin:
            p_path = ch.path
        if p_from_b != p_from_t and base_sha != pin and ch.status != "D":
            p_path = None
        if p_path is not None and not blob_exists(repo, pin, p_path):
            p_path = None

        rec = ImpactFile(path=ch.path, p_path=p_path, status=ch.status)
        refs: list[AnchorRef] = by_file.get(p_path, []) if p_path else []
        if p_path is None:
            rec.frame = FileFrame(p_absent=True)
            # no P-frame → no anchors to hit; territory (dir) anchors may still claim it
            refs = []
        core.files.append(rec)

        if p_path is not None:
            if ch.status == "D":
                rec.frame = FileFrame(fully_deleted=True)
            elif refs:  # translate only files that host an anchor (the laziness rule)
                p_lines = show_lines(repo, pin, p_path)
                side_b = _side_diff(repo, pin, p_path, base_sha, left_path, p_lines)
                side_t = _side_diff(repo, pin, p_path, target_r, ch.path, p_lines)
                rec.frame = frame_from_two_diffs(side_b, side_t, p_line_count=len(p_lines))
                # A file with status "A" that exists at the pin was ADDED between base and pin:
                # relative to this diff all its code is new — resolve at full precision, label
                # "added", and skip drift classification (nothing 'moved').
                t_lines = None if ch.status == "A" else read_side_lines(repo, target_r, ch.path)
                rec.hits = resolve_hits(refs, rec.frame, extents.get(p_path, []),
                                        ch.status, p_lines, t_lines)
                if ch.status == "A":
                    rec.hits = [replace(h, change="added") for h in rec.hits]
            else:
                rec.frame = FileFrame()  # changed, hosts no file anchor — file-level info only
            if ch.status == "D" and refs:
                rec.hits = resolve_hits(refs, rec.frame, [], "D")
                if Path(p_path).name in added_names:
                    core.warnings.append(
                        f"{p_path}: deleted candidate (rename suspected — an added file shares its "
                        f"basename; git -M did not pair them)")

        # territory: dir anchors claim the file ONLY when no finer (file) anchor matched
        if not rec.hits:
            terr = dir_anchors_for(anchors, p_path or ch.path)
            if terr:
                deepest = [a for a in terr if len(a.path) == len(terr[0].path)]
                change = {"A": "added", "D": "deleted"}.get(ch.status, "modified")
                rec.hits = [DirectHit(a.eid, a.kind, a.path, change, "file", a.field, a.owner,
                                      territory=True)
                            for a in deepest]
    return core
