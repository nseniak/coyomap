"""Credential-shaped values in the files of a map — found by SHAPE, reported by PLACE.

A map folder holds the agents' own files (`verify/`, `build-fragments/`), and a plain `git add` of
the folder takes them with the map. Nothing looked at what that would commit. On the 2026-09-30 mcpolis build a skeptic's `grep … $R/.env*`
printed the production deployment config, API key included, into its own transcript; the harness
hook stopped nine explicit reads of that file and let the glob through. The key reached no committed
file that time, and nothing would have said so if it had.

SPECIFIC SHAPES ONLY. A naive rule ("any 32+ character token") hits 247 strings in 7 of that map's
295 committed files — digests, ids, paths — and a check that always fires is a check nobody reads.
Each shape here is a vendor prefix or a key block, so a hit is worth stopping for.

THE VALUE IS NEVER PRINTED. A hit names the file, the line and the shape; printing the value would
copy the secret into the report, the commit message and the transcript of whoever reads them. Nor is
it QUOTED: a report that repeats a skeptic's note runs it through `redact` first.

NOT A SHAPE, on measurement: an address carrying a password (`scheme://user:pass@host`). Across the
8 maps on this machine it matched once, a local development address a skeptic quoted from the code,
so as a blocking shape it would stop honest maps. Also out of reach: a value split across two lines,
and a file that is not UTF-8. The scan is a net over the files coyomap itself writes, not a proof.

A FILE NO COMMIT TAKES only warns. The build state, the findings and their report stay on this
machine (`uncommitted.never_committed`), so a value there names its file and asks for the line to
go, and stops nothing. `finalize` reads the same answer, so the two never disagree about a file.

Stdlib-only (the cli.py firewall). It imports only `uncommitted`, which imports nothing from coyomap.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from coyomap.uncommitted import RUNS_FOLDER, never_committed

#: What may stand before a shape: nothing that could be part of a token. `\b` missed a value right
#: after an `_`, and after a JSON `\n` or `\t` escape, whose letter is a word character; the files
#: this scans are mostly JSON.
_BEFORE = r"(?<![A-Za-z0-9])"

#: `(what it is, its shape)`. Vendor prefixes and key blocks: each is specific enough that a match
#: in a map's own files is a leak, not a coincidence.
SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key id", re.compile(_BEFORE + r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])")),
    ("GitHub token", re.compile(_BEFORE + r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("GitHub fine-grained token", re.compile(_BEFORE + r"github_pat_[A-Za-z0-9_]{40,}")),
    ("GitLab token", re.compile(_BEFORE + r"glpat-[A-Za-z0-9_-]{20,}")),
    ("Slack token", re.compile(_BEFORE + r"xox[abprs]-[0-9A-Za-z-]{10,}")),
    ("Slack webhook", re.compile(r"hooks\.slack\.com/services/T[A-Za-z0-9]+/B[A-Za-z0-9]+/"
                                 r"[A-Za-z0-9]{16,}")),
    ("Stripe live key", re.compile(_BEFORE + r"[rs]k_live_[0-9A-Za-z]{20,}")),
    ("Anthropic API key", re.compile(_BEFORE + r"sk-ant-[A-Za-z0-9_-]{20,}")),
    # The older keys are letters and digits after `sk-`; project, service-account and admin keys
    # carry `_` and `-` after their own word.
    ("OpenAI API key", re.compile(_BEFORE + r"sk-(?:(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}"
                                  r"|[A-Za-z0-9]{32,})")),
    ("Google API key", re.compile(_BEFORE + r"AIza[0-9A-Za-z_-]{35}")),
    ("Google OAuth client secret", re.compile(_BEFORE + r"GOCSPX-[A-Za-z0-9_-]{20,}")),
    ("Hugging Face token", re.compile(_BEFORE + r"hf_[A-Za-z0-9]{30,}")),
    ("E2B API key", re.compile(_BEFORE + r"e2b_[0-9A-Za-z]{32,}")),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("JSON web token", re.compile(_BEFORE + r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\."
                                  r"[A-Za-z0-9_-]{10,}")),
)

#: A JSON escape or a URL-encoded byte. Blanked, length kept, before matching, so a value right
#: after one has a boundary in front of it and a span found still points into the original text.
_ESCAPE = re.compile(r"\\[nrtbf]|%[0-9A-Fa-f]{2}")

#: What `redact` puts where a value was.
REDACTED = "[a credential-shaped value, not shown]"


def _visible(text: str) -> str:
    return _ESCAPE.sub(lambda m: " " * len(m.group(0)), text)


def _spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, shape) of every credential-shaped value in `text`."""
    seen = _visible(text)
    return sorted((m.start(), m.end(), shape) for shape, p in SHAPES for m in p.finditer(seen))


def redact(text: str) -> str:
    """`text` with each credential-shaped value replaced by `REDACTED`, so a report can quote a
    skeptic's note without copying a key out of it. The review put a key-shaped value in a dissent
    note: the credential leg blocked, and the same report printed the note, value and all."""
    spans = _spans(text)
    if not spans:
        return text
    out: list[str] = []
    last = 0
    for start, end, _shape in spans:
        if end <= last:
            continue
        out.append(text[last:max(start, last)])
        out.append(REDACTED)
        last = end
    out.append(text[last:])
    return "".join(out)


@dataclass(frozen=True)
class Hit:
    """One credential-shaped value: where it is and what shape it has — never the value."""
    path: Path
    line: int
    shape: str


def scan_file(path: Path) -> list[Hit]:
    """Every credential-shaped value in one file, one hit per shape per line."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[Hit] = []
    for n, line in enumerate(text.splitlines(), start=1):
        seen = _visible(line)
        for shape, pattern in SHAPES:
            if pattern.search(seen):
                hits.append(Hit(path, n, shape))
    return hits


def scan(paths: list[Path]) -> list[Hit]:
    """Every hit across `paths`, where a directory stands for every file under it."""
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*") if f.is_file()))
        elif p.is_file():
            files.append(p)
    return [h for f in files for h in scan_file(f)]


def places(hits: list[Hit]) -> dict[Path, list[str]]:
    """Each file's hits as `line <n> (<shape>)`, files and lines in the order found."""
    by_file: dict[Path, list[str]] = {}
    for h in hits:
        by_file.setdefault(h.path, []).append(f"line {h.line} ({h.shape})")
    return by_file


#: What to do about a value in a file no commit takes (`never_committed`). `finalize` and this verb
#: both say it after naming the file.
UNCOMMITTED_REMEDY = ("Remove that line from the file: it is the build's own record, kept on this "
                      "machine. If the value is real it is also in the transcript of the agent that "
                      "wrote it: tell the operator, who decides whether to rotate it.")


#: The folder under a map folder that holds archived maps: a map committed long ago, not this one.
ARCHIVE = "dev-rebuilds"
#: Folders no scan reads: the archive, and the run records of headless builds (`uncommitted`),
#: which hold whole session logs and are never part of the map.
NOT_SCANNED = (ARCHIVE, RUNS_FOLDER)


def map_folder_files(folder: Path) -> list[Path]:
    """Every file under a map folder, archived maps and run records aside: every part of a map
    (the map, `verify/`, `build-fragments/`) and what an update commits with a plain `git add`
    (`changes/` too), plus `.ignore`, which the scan used to skip, and the files no commit takes
    (`never_committed`), where a hit only warns."""
    return sorted(f for f in folder.rglob("*")
                  if f.is_file() and not set(NOT_SCANNED) & set(f.relative_to(folder).parts))


USAGE = """usage: coyomap credentials [<map folder>]

Scan every file under the map folder (default .coyomap), archived maps under dev-rebuilds/ aside,
for credential-shaped values: vendor key prefixes, key blocks, web tokens. Prints each hit's file,
line and shape, never the value, and exits 1 on any in a file a commit takes. A hit in a file no
commit takes (the build state, the findings folder, the findings report) is a WARNING naming the
file: remove the line; it does not fail. `finalize` runs the same scan for a build; an update's
close runs this before its commit, since it runs no finalize."""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "-h" in args or "--help" in args:
        print(USAGE)
        return 0
    folder = Path(args[0]) if args else Path(".coyomap")
    if not folder.is_dir():
        print(f"ERROR: {folder} is not a folder.\n\n{USAGE}", file=sys.stderr)
        return 2
    files = map_folder_files(folder)
    hits = scan(files)
    local = [h for h in hits if never_committed(folder, h.path)]
    taken = [h for h in hits if not never_committed(folder, h.path)]
    for h in taken:
        print(f"{h.path}:{h.line}: {h.shape}")
    kept = places(local)
    for path, where in kept.items():
        print(f"WARNING: {path}: {', '.join(where)} — a credential-shaped value in a file no "
              f"commit takes, so it stops no commit. {UNCOMMITTED_REMEDY}", file=sys.stderr)
    if taken:
        print(f"CREDENTIALS FOUND: {len(taken)} credential-shaped value(s) in "
              f"{len({h.path for h in taken})} file(s) under {folder} that a commit takes. Rewrite "
              f"each line without the value before you commit; if a value is real, tell the "
              f"operator, who decides whether to rotate it.", file=sys.stderr)
        return 1
    print(f"credentials: {len(files)} file(s) under {folder} scanned, 0 credential-shaped values"
          + (f" in the files a commit takes; {len(local)} in {len(kept)} file(s) no commit takes, "
             f"each named in a WARNING line" if local else ""))
    return 0
