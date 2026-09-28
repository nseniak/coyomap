#!/usr/bin/env python3
"""`.coyomap/.ignore` — the analysis ignore file.

A repo may hold code that is deliberately NOT part of what the map describes: a fixture tree built
to trip the tooling's own advisories, a vendored copy git tracks under a name `DEFAULT_EXCLUDE_DIRS`
does not already cover (`vendor/`, `third_party/`, `dist/`, … never reach here), a scratch area. Left
in, it inflates the weight tree, skews the component expectation E, and shows up forever as an
unreferenced directory. `.gitignore` cannot express it (the files are meant to be committed), and a "Coverage
exceptions" extras heading is a different statement — that one says *mapped coarsely, stop warning*,
while this one says *not part of the analysed tree at all*.

So the repo declares it once, next to the map:

    # .coyomap/.ignore — gitignore-like patterns, one per line.
    # A comment goes on its OWN line: `pattern  # why` is one literal pattern (see below).
    # the trap fixture — deliberately broken code
    trapdoor/
    generated/**
    !generated/hand_written.py

Semantics (a deliberate SUBSET of gitignore, matched by `coyomap.pathmatch`):
  * blank lines and `#` comments are skipped — `#` opens a comment only at the START of a line,
    exactly as in gitignore, so `pattern  # why` is NOT a pattern plus a comment. That line is
    reported as bad rather than stored (see `parse_ignore`); write `\\#` for a literal `#`
  * a wildcard-free pattern matches that path AND everything beneath it (`trapdoor/` == `trapdoor`)
  * `*`/`?` match within one path segment; `**` spans segments
  * a leading `!` negates, and the LAST matching line wins — so a broad ignore can be narrowed
  * patterns are always repo-relative; a trailing `/` is accepted and ignored (only files are
    ever tested, so "the directory" and "everything under it" are the same statement here)

**It is never silent.** Every surface that walks the tree carries the narrowing out with it, per
pattern — because an ignore file is the one input that can hide a real gap from the coverage check
that exists to find gaps. Concretely:

  * `coyomap validate` ALWAYS warns (`validate_analysis.ignore_disclosure`) — not only under
    `--check-coverage`, since the cheap `--check-sources` pass is the one a lead runs most and a
    disclosure it skips is a disclosure that does not exist;
  * `coyomap preindex` records the counts in `preindex.json` and prints them on stderr;
    `preindex --report` prints the patterns;
  * the viewer's file-browser tree (`viewer.filetree.build_file_tree`) carries an `ignored` note on
    its root node, so a renderer can never present a narrowed tree as the whole repo;
  * `coyomap scope` prints the per-pattern block in the briefing a build shows BEFORE it starts,
    unusable lines included, in `validate`'s words (`bad_line_disclosure` below).

Each of those reports PER RULE (`ignore_report` below), so a pattern that decided nothing — a typo,
a tree that moved, a path a built-in exclusion already covers — is named instead of blending into a
reassuring total.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from coyomap.pathmatch import matches

# Where the file lives, relative to the repo root. Inside `.coyomap/` so it travels with the map and
# needs no entry in the repo root; `.coyomap` is already in `DEFAULT_EXCLUDE_DIRS`, so the ignore
# file can never be analysed as part of the tree it describes.
IGNORE_REL = Path(".coyomap") / ".ignore"


@dataclass(frozen=True)
class IgnoreSpec:
    """Parsed `.coyomap/.ignore`. `rules` is ordered; later rules override earlier ones."""

    rules: tuple[tuple[bool, str], ...] = ()      # (negated, pattern)
    path: Path | None = None                      # the file it came from, when one existed
    bad_lines: tuple[str, ...] = field(default=())  # lines that parsed to nothing, for reporting

    def __bool__(self) -> bool:
        return bool(self.rules)

    @property
    def patterns(self) -> list[str]:
        """The pattern lines as authored (with `!` restored), for the report."""
        return [("!" if neg else "") + pat for neg, pat in self.rules]

    def match_index(self, rel: str) -> int | None:
        """Index of the rule that DECIDES this repo-relative path — the LAST one that matches, since
        later rules override earlier ones. None when no rule matches (or the spec is empty).

        `match` is this plus the rule's polarity. The walk wants the index rather than the boolean so
        it can count hits PER RULE: a rule that decides nothing on a whole tree is the unused-pattern
        signal, and it is invisible in a yes/no answer."""
        hit: int | None = None
        for i, (_negated, pattern) in enumerate(self.rules):
            if matches(pattern, rel):
                hit = i
        return hit

    def match(self, rel: str) -> bool:
        """Is this repo-relative path ignored? LAST matching rule wins, so `!` can carve an
        exception out of a broad ignore. Returns False when the spec is empty."""
        i = self.match_index(rel)
        return i is not None and not self.rules[i][0]


@dataclass(frozen=True)
class IgnoreReport:
    """What an ignore file actually DID on ONE walk — per rule, so nothing hides in the total.

    Built by `ignore_report` from a spec plus the walk's per-rule hit counts. Every disclosing
    surface (validate's advisory, the pre-index artifact + its report, the viewer's file tree) reads
    this one object, so the three of them cannot drift into three different stories.
    """

    removed: int                    # files the walk dropped (sum over the non-negated rules)
    restored: int                   # files a `!` rule put BACK (sum over the negated rules)
    per_rule: tuple[str, ...]       # one authored pattern per rule, with what it decided
    unused: tuple[str, ...]         # patterns that decided nothing — the typo / moved-tree signal
    bad_lines: tuple[str, ...]      # lines that parsed to nothing at all (carried from the spec)


def ignore_report(spec: IgnoreSpec, hits: Sequence[int]) -> IgnoreReport:
    """Summarise one walk's use of `spec`. `hits[i]` is how many paths rule `i` DECIDED — pass
    `WalkResult.ignore_hits`, which the walk keeps aligned with `spec.rules` by construction (a
    short/long sequence is padded/truncated rather than raising inside a reporting path).

    A NEGATION rule's hit is not a removal: it means the rule RE-INCLUDED a file another rule had
    excluded. So it is counted, and worded, as a restore — `removed` covers only the positive rules,
    which is exactly `WalkResult.skipped_ignored`. `unused` spans both kinds: a `!` line that put
    nothing back is as misleading as a positive line that took nothing out, because in both cases the
    author believes the file is describing the tree and it is not.
    """
    n = len(spec.rules)
    counts = [hits[i] if i < len(hits) else 0 for i in range(n)]
    removed = sum(c for (neg, _pat), c in zip(spec.rules, counts) if not neg)
    restored = sum(c for (neg, _pat), c in zip(spec.rules, counts) if neg)
    per_rule = tuple(
        f"{'!' if neg else ''}{pat} ({'put back' if neg else 'removed'} {c} file(s))"
        for (neg, pat), c in zip(spec.rules, counts)
    )
    unused = tuple(("!" if neg else "") + pat
                   for (neg, pat), c in zip(spec.rules, counts) if c == 0)
    return IgnoreReport(removed=removed, restored=restored, per_rule=per_rule, unused=unused,
                        bad_lines=spec.bad_lines)


def bad_line_disclosure(bad_lines: Sequence[str]) -> list[str]:
    """The unusable-line report, worded ONCE for every surface that prints it (`validate`'s
    advisory, `coyomap scope`'s briefing), so the two commands cannot describe one file two ways.
    On its own, not inside `ignore_report`, so it can be emitted with or without a walk — a file
    whose every line is bad has no rules to walk with, and that is precisely the case worth
    reporting."""
    if not bad_lines:
        return []
    return [f"`.coyomap/.ignore` has {len(bad_lines)} unusable line(s), DROPPED — nothing they name "
            f"is excluded from the analysed tree: {', '.join(repr(b) for b in bad_lines)}. A pattern "
            f"that cannot fire reads as coverage the author never got. Two causes: the pattern strips "
            f"to nothing (e.g. `/`), or it carries a trailing `# comment`, which this file does not "
            f"support — `#` opens a comment only at the START of a line (gitignore's rule), so "
            f"`pattern  # why` is one literal pattern containing spaces. Put the comment on its own "
            f"line above the pattern, or write `\\#` for a literal `#`."]


_EMPTY = IgnoreSpec()
# Cache keyed by (path, mtime_ns, size): a build calls `iter_source_files` several times (the
# pre-index, then validate's independent re-walk), and re-parsing per call is pure waste. Keying on
# the stat means an edit during a session is still picked up.
_CACHE: dict[tuple[str, int, int], IgnoreSpec] = {}


#: Whitespace followed by an unescaped `#` — the trailing-comment mistake. `\#` does not match,
#: because the character after the whitespace is the backslash, so an escaped hash is left alone.
_TRAILING_COMMENT = re.compile(r"\s#")


def parse_ignore(text: str, path: Path | None = None) -> IgnoreSpec:
    """Parse ignore-file text. Pure, so the semantics are testable without a filesystem."""
    rules: list[tuple[bool, str]] = []
    bad: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pattern = line[1:].strip() if negated else line
        # A trailing `# comment` is the one syntax mistake worth its own detection. `#` opens a
        # comment only at the start of a line (gitignore's rule, which this file follows), so
        # `internal/    # private ops runbooks` is ONE literal pattern containing spaces, and it can
        # never match a real path. A live build wrote all three of its patterns that way — copied
        # from the method's own example, which showed them with trailing comments — and got only the
        # soft "decided nothing" advisory, so it deleted the file instead of fixing the syntax. That
        # silence cost a coverage decision, so report the line here. NOT stripped: stripping would
        # diverge from gitignore and make a real `a #b` path unmatchable. `\#` escapes a literal `#`.
        if _TRAILING_COMMENT.search(pattern):
            bad.append(raw)
            continue
        pattern = pattern.replace("\\#", "#")
        # `matches` treats an all-slash pattern as matching nothing; report it rather than storing a
        # rule that can never fire (a silently-dead pattern reads as coverage the author never got).
        if not pattern.strip("/"):
            bad.append(raw)
            continue
        rules.append((negated, pattern))
    return IgnoreSpec(rules=tuple(rules), path=path, bad_lines=tuple(bad))


def load_ignore(root: Path) -> IgnoreSpec:
    """Read `<root>/.coyomap/.ignore`. Absent or unreadable file → an empty spec that ignores
    nothing, so the walk behaves exactly as it did before the file existed."""
    p = (root / IGNORE_REL).resolve()
    try:
        st = p.stat()
    except OSError:
        return _EMPTY
    key = (str(p), st.st_mtime_ns, st.st_size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        spec = parse_ignore(p.read_text(encoding="utf-8"), path=p)
    except OSError:
        return _EMPTY
    _CACHE[key] = spec
    return spec
