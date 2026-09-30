"""`whole_file.write_whole`: a file is written whole or not at all, and keeps its permissions."""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from coyomap.whole_file import write_whole


def make_file(folder: Path, text: str, mode: int) -> Path:
    path = folder / "map.json"
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def test_a_new_file_gets_what_the_umask_gives_any_write():
    old = os.umask(0o022)
    try:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "map.json"
            write_whole(path, "{}")
            assert stat.S_IMODE(path.stat().st_mode) == 0o644
    finally:
        os.umask(old)


def test_an_existing_file_keeps_its_permissions():
    with tempfile.TemporaryDirectory() as td:
        path = make_file(Path(td), "old", 0o640)
        write_whole(path, "new")
        assert path.read_text(encoding="utf-8") == "new"
        assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_a_failed_write_leaves_the_old_file_and_no_temporary_file():
    with tempfile.TemporaryDirectory() as td:
        path = make_file(Path(td), "old", 0o644)
        try:
            write_whole(path, "\udcff")              # a lone surrogate cannot be written as UTF-8
        except UnicodeEncodeError:
            pass
        else:
            raise AssertionError("the write should have failed")
        assert path.read_text(encoding="utf-8") == "old"
        assert [p.name for p in Path(td).iterdir()] == ["map.json"]
