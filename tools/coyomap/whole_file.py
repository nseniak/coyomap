"""Write a file whole or not at all: a temporary file beside it, then one rename.

`assemble` writes the map while agents read it, and a map rewritten in place can be read
half-written. The copies this replaced left their file readable by its owner only, because
`tempfile.mkstemp` creates its file 0600 and the rename carries that over. The map had been 0644
until the first of them.

Stdlib-only (the cli.py firewall).
"""
from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path


def write_whole(path: Path, text: str) -> None:
    """Write `text` to `path` whole or not at all, and keep the permissions the file had.

    A new file gets what any ordinary write gives it: the temporary file is created with 0o666 and
    the process umask applies, exactly as for `Path.write_text`. An existing file's permissions are
    copied onto the temporary file before the rename, so a map someone made private stays private."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            shutil.copymode(path, tmp)
        except FileNotFoundError:
            pass                                  # a new file: keep what the umask gave it
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
