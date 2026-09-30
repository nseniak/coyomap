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
copy the secret into the report, the commit message and the transcript of whoever reads them. Nor is
it QUOTED: a report that repeats a skeptic's note runs it through `redact` first.

NOT A SHAPE, on measurement: an address carrying a password (`scheme://user:pass@host`). Across the
8 maps on this machine it matched once, a local development address a skeptic quoted from the code,
so as a blocking shape it would stop honest maps. Also out of reach: a value split across two lines,
and a file that is not UTF-8. The scan is a net over the files coyomap itself writes, not a proof.

Stdlib-only (the cli.py firewall).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

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


#: The folder under a map folder that holds archived maps: a map committed long ago, not this one.
ARCHIVE = "dev-rebuilds"


def map_folder_files(folder: Path) -> list[Path]:
    """Every file under a map folder, archived maps aside: what a build's commit line force-adds
    (the map, `verify/`, `build-fragments/`) and what an update commits with a plain `git add`
    (`changes/` too), plus `.ignore`, which the scan used to skip."""
    return sorted(f for f in folder.rglob("*")
                  if f.is_file() and ARCHIVE not in f.relative_to(folder).parts)


USAGE = """usage: coyomap credentials [<map folder>]

Scan every file under the map folder (default .coyomap), archived maps under dev-rebuilds/ aside,
for credential-shaped values: vendor key prefixes, key blocks, web tokens. Prints each hit's file,
line and shape, never the value, and exits 1 on any. `finalize` runs the same scan for a build; an
update's close runs this before its commit, since it runs no finalize."""


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
    for h in hits:
        print(f"{h.path}:{h.line}: {h.shape}")
    if hits:
        print(f"CREDENTIALS FOUND: {len(hits)} credential-shaped value(s) in "
              f"{len({h.path for h in hits})} file(s) under {folder}. Rewrite each line without the "
              f"value before you commit; if a value is real, tell the operator, who decides whether "
              f"to rotate it.", file=sys.stderr)
        return 1
    print(f"credentials: {len(files)} file(s) under {folder} scanned, 0 credential-shaped values")
    return 0
