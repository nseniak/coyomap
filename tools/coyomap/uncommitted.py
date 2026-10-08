"""The files of a map folder that no commit takes — one answer for every tool that asks.

A build keeps its own working memory in the map folder: the build state (`coyomap state`) and the
one before it, the findings each agent files (`coyomap findings add`) and the report they are
collected into. The folder's `.gitignore` keeps them out (`assemble` writes it from the names below),
`finalize`'s closing line never names them as part of the map, and a plain `git add` follows that
`.gitignore`. So a credential-shaped value in one of them is a line to remove, never a commit to
stop.

`finalize` and `coyomap credentials` both scan the whole map folder. `finalize` learned to report a
value in these files as an advisory while `coyomap credentials` still failed on it, because each
kept its own idea of which files those are. This is the one both read.

Stdlib-only (the cli.py firewall). It imports nothing from coyomap, so `credentials`, which the
build state imports, can import it too.
"""
from __future__ import annotations

from pathlib import Path

#: The build state, and the ended or set-aside one before it (`coyomap state start`).
STATE_NAME = "build-state.log"
PREV_NAME = "build-state.prev.log"
#: The folder each agent's findings file lives in (`coyomap findings add`), and the report
#: `coyomap findings collect` writes beside it.
FINDINGS_FOLDER = "findings"
FINDINGS_REPORT = "findings-report.md"
#: The folder a headless build keeps its run records in (`tools/claude_headless.py`): one folder
#: per run, holding the session's whole log. Not part of the map, and far too large to scan.
RUNS_FOLDER = "runs"

#: The files at the top of a map folder that no commit takes, and the folders whose whole tree none
#: takes.
FILES: tuple[str, ...] = (STATE_NAME, PREV_NAME, FINDINGS_REPORT)
FOLDERS: tuple[str, ...] = (FINDINGS_FOLDER, RUNS_FOLDER)
#: The same files and folders as `.gitignore` lines.
IGNORE_LINES: tuple[str, ...] = (*FILES, *(f"{name}/" for name in FOLDERS))


def never_committed(folder: Path, path: Path) -> bool:
    """Whether `path`, a file under the map folder `folder`, is one no commit takes."""
    top, *below = path.relative_to(folder).parts or ("",)
    return top in (FOLDERS if below else FILES)
