"""Credential-shaped values in the files a build commits — found by SHAPE, reported by PLACE.

`finalize` prints a `git add -f` line that force-adds the map and the agents' own files (`verify/`,
`build-fragments/`), because the repo's own `.gitignore` usually ignores `.coyomap/`. Nothing looked
at what that line would commit. On the 2026-09-30 mcpolis build a skeptic's `grep … $R/.env*`
printed the production deployment config, API key included, into its own transcript; the harness
hook stopped nine explicit reads of that file and let the glob through. The key reached no committed
file that time, and nothing would have said so if it had.

SPECIFIC SHAPES ONLY. A naive rule ("any 32+ character token") hits 247 strings in 7 of that map's
295 committed files — digests, ids, paths — and a check that always fires is a check nobody reads.
Each shape here is a vendor prefix or a key block, so a hit is worth stopping for.

THE VALUE IS NEVER PRINTED. A hit names the file, the line and the shape; printing the value would
copy the secret into the report, the commit message and the transcript of whoever reads them.

Stdlib-only (the cli.py firewall).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: `(what it is, its shape)`. Vendor prefixes and key blocks: each is specific enough that a match
#: in a map's own files is a leak, not a coincidence.
SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}")),
    ("Stripe live key", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{20,}")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("E2B API key", re.compile(r"\be2b_[0-9A-Za-z]{32,}")),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)


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
        for shape, pattern in SHAPES:
            if pattern.search(line):
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
