#!/usr/bin/env python3
"""Tests for `coyomap-eval archive` — moving a map aside for a from-scratch rebuild.

This command moves a repo's only copy of its map, so the tests are about not losing it: the archive
never nests inside itself, `.gitignore` stays where the next assemble expects it, an interrupted run
puts everything back, and nothing is ever deleted.

Run either way (needs an editable install: `make deps`):
    python3 eval/tests/test_archive.py
    pytest eval/tests/test_archive.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "eval" / "tools"))

# A plain import now. This used to be an `importlib.util.spec_from_file_location` dance against an
# absolute path, because the module was a loose script under `eval/scripts/` rather than part of a
# package — the same pathness that made every caller spell the path out by hand.
from coyomap import buildstate  # noqa: E402
from coyomap_eval import archive as archive_map  # noqa: E402


def make_repo(tmp: str, *, archives: tuple[str, ...] = ()) -> Path:
    """A repo whose `.coyomap/` holds a full map plus any pre-existing archives."""
    root = Path(tmp)
    cy = root / ".coyomap"
    (cy / "build-fragments").mkdir(parents=True)
    (cy / "build-fragments" / "header.json").write_text("{}")
    for name in ("project-map.json", "project-map.md", "preindex.json", "provenance.json"):
        (cy / name).write_text("x")
    (cy / ".gitignore").write_text("build-fragments/\n")
    (cy / ".ignore").write_text("eval/fixtures/trapdoor/\n")
    for a in archives:
        (cy / archive_map.ARCHIVE_DIR / a).mkdir(parents=True)
    return root


def test_archives_are_numbered_from_one_inside_the_container():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        dest, _ = archive_map.archive(root)
        assert dest is not None and dest.name == "0001"
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, archives=("0001", "0002"))
        dest, _ = archive_map.archive(root)
        assert dest is not None and dest.name == "0003"


def test_numbering_is_numeric_and_zero_padding_makes_text_order_match():
    """The trap the unpadded convention carried: `-9` sorted after `-10` as text, and a consumer got it
    wrong for real (a baseline picker sorted on name length and chose the wrong archive in 28 of 40
    trials). Padding removes it — so assert BOTH that the next number is right and that a plain
    lexical sort of the names now agrees with a numeric one."""
    with tempfile.TemporaryDirectory() as tmp:
        names = tuple(f"{n:04d}" for n in range(1, 11))
        root = make_repo(tmp, archives=names)
        dest, _ = archive_map.archive(root)
        assert dest is not None and dest.name == "0011"
        on_disk = [d.name for d in (root / ".coyomap" / archive_map.ARCHIVE_DIR).iterdir()
                   if d.is_dir()]
        assert sorted(on_disk) == sorted(on_disk, key=int)


def test_a_gap_is_left_alone_so_the_number_still_means_recency():
    """Always highest + 1 — filling a gap would make the number lie about age.

    With `0001` and `0003` present, reusing `0002` would file the NEWEST map between two older
    ones. The common cleanup is worse: prune the oldest archives and the next map lands in
    `0001`, the name that reads as "the first one", so the sequence reads backwards."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, archives=("0001", "0003"))
        dest, _ = archive_map.archive(root)
        assert dest is not None and dest.name == "0004"


def test_pruning_the_oldest_archives_never_recycles_their_names():
    # deleting the two oldest must not hand their names to the newest map
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, archives=("0003", "0004"))
        dest, _ = archive_map.archive(root)
        assert dest is not None and dest.name == "0005"


def test_a_hand_named_sibling_does_not_break_the_numbering():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, archives=("0001", "broken"))
        dest, _ = archive_map.archive(root)
        assert dest is not None and dest.name == "0002"


def test_the_whole_map_moves_and_nothing_is_deleted():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        dest, entries = archive_map.archive(root)
        assert dest is not None
        assert {p.name for p in entries} == {
            "build-fragments", "project-map.json", "project-map.md", "preindex.json",
            "provenance.json"}
        for name in ("project-map.json", "provenance.json"):
            assert (dest / name).is_file()
        assert (dest / "build-fragments" / "header.json").is_file()   # directories move whole
        # …and the working tree now reads as "no baseline", which is what makes the next run BUILD
        assert not (root / ".coyomap" / "project-map.json").exists()


def test_the_gitignore_stays_put():
    # coyomap writes `.coyomap/.gitignore` and the next assemble expects it; archiving it would
    # un-ignore build-fragments/ for the following build.
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        archive_map.archive(root)
        assert (root / ".coyomap" / ".gitignore").read_text() == "build-fragments/\n"


def test_the_scope_declaration_stays_put():
    """`.ignore` is scope, not output — archiving it silently rescopes the analysed tree.

    It decides which files `iter_source_files` walks, so it sets the coverage denominator AND the
    code-derived component expectation E. On the coyomap repo, moving it aside took E from 14 to 37
    (+164%) and flipped the current map's granularity band from DRIFT to PASS — same map, same code.
    Since `archive` is the first command of the eval loop (archive -> rebuild -> compare), a rescope
    there lands squarely between the two maps the eval compares, and the same-code guard cannot see
    it: the guard excludes `.coyomap/` wholesale."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        dest, entries = archive_map.archive(root)
        assert (root / ".coyomap" / ".ignore").read_text() == "eval/fixtures/trapdoor/\n"
        assert not any(p.name == ".ignore" for p in entries)
        assert dest is not None and not (dest / ".ignore").exists()


def test_archives_are_never_nested_inside_each_other():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp, archives=("0001",))
        (root / ".coyomap" / archive_map.ARCHIVE_DIR / "0001" / "project-map.json").write_text("old")
        dest, entries = archive_map.archive(root)
        assert dest is not None
        assert not any(p.name == archive_map.ARCHIVE_DIR for p in entries)
        assert (root / ".coyomap" / archive_map.ARCHIVE_DIR / "0001" / "project-map.json").read_text() == "old"


def test_an_already_clear_map_is_not_an_error():
    # the state a from-scratch build wants — running twice must be harmless, not a failure
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        archive_map.archive(root)
        dest, entries = archive_map.archive(root)
        assert dest is None and entries == []
        assert archive_map.main([str(root)]) == 0


def test_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        dest, entries = archive_map.archive(root, dry_run=True)
        assert dest is not None and entries
        assert not dest.exists()
        assert (root / ".coyomap" / "project-map.json").is_file()


def test_a_failed_move_puts_everything_back():
    """A half-finished archive is worse than none: the map would be split across two directories."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        real_move = archive_map.shutil.move
        calls = {"n": 0}

        def flaky(src: str, dst: str) -> object:
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("disk full")
            return real_move(src, dst)

        archive_map.shutil.move = flaky
        try:
            with pytest.raises(OSError):
                archive_map.archive(root)
        finally:
            archive_map.shutil.move = real_move
        cy = root / ".coyomap"
        assert (cy / "project-map.json").is_file() and (cy / "build-fragments").is_dir()
        assert not (cy / archive_map.ARCHIVE_DIR).exists()          # the empty archive is cleaned up too


def test_a_missing_coyomap_dir_reports_instead_of_crashing():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(FileNotFoundError):
            archive_map.archive(Path(tmp))
        assert archive_map.main([tmp]) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- `--list` answers "what was the previous map" (retro 2026-08-14) ------------------------------
# `archive` filed maps and then could never say where any of them were. A retrospective located its
# baseline by hand — and found it under a hand-rolled `.old-ignore-N/` convention this command did
# not create, which is exactly the convention a reader cannot guess.

def make_archived_map(d: Path, built_at: str, session: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "project-map.json").write_text('{"format": "coyomap-map"}', encoding="utf-8")
    (d / "provenance.json").write_text(json.dumps({
        "schema": "coyomap-provenance/v1",
        "sessions": [{"session_id": session, "built_at": built_at, "mode": "build"}]}),
        encoding="utf-8")


def test_list_reports_maps_archived_by_this_command_newest_first(capsys):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make_archived_map(root / ".coyomap" / "dev-rebuilds" / "0001", "2026-07-13 23:37", "aaa11111")
        make_archived_map(root / ".coyomap" / "dev-rebuilds" / "0002", "2026-08-02 17:46", "bbb22222")
        assert archive_map.main([str(root), "--list"]) == 0
        out = capsys.readouterr().out
        assert out.index("0002") < out.index("0001"), out
        assert "bbb22222" in out and "aaa11111" in out


def test_list_also_reports_a_hand_rolled_archive_convention(capsys):
    """The one a reader cannot guess. Hiding it does not make it go away."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make_archived_map(root / ".coyomap" / ".old-ignore-6", "2026-07-29 11:27", "07a8f4e9")
        assert archive_map.main([str(root), "--list"]) == 0
        out = capsys.readouterr().out
        assert ".old-ignore-6" in out, out
        assert "2026-07-29 11:27" in out


def test_list_says_plainly_when_there_is_nothing_to_compare_against(capsys):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".coyomap").mkdir()
        assert archive_map.main([str(root), "--list"]) == 0
        assert "no archived map" in capsys.readouterr().out


def test_list_survives_an_archive_too_old_to_carry_provenance(capsys):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / ".coyomap" / "dev-rebuilds" / "0001"
        d.mkdir(parents=True)
        (d / "project-map.json").write_text('{"format": "coyomap-map"}', encoding="utf-8")
        assert archive_map.main([str(root), "--list"]) == 0
        assert "(no provenance)" in capsys.readouterr().out


def test_list_never_writes_anything():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        make_archived_map(root / ".coyomap" / "dev-rebuilds" / "0001", "2026-07-13 23:37", "aaa11111")
        (root / ".coyomap" / "project-map.json").write_text('{"format": "coyomap-map"}',
                                                            encoding="utf-8")
        before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        assert archive_map.main([str(root), "--list"]) == 0
        assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before


def test_the_fan_out_timings_stay_put():
    """`fanout-timings.json` is cross-build INPUT: `timings order` reads the last recording per slice
    to order the next build's dispatch. Archived with the map, that verb started cold on a repo with
    26 rebuilds behind it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        (root / ".coyomap" / "fanout-timings.json").write_text('{"harvest": []}', encoding="utf-8")
        dest, entries = archive_map.archive(root)
        assert (root / ".coyomap" / "fanout-timings.json").read_text() == '{"harvest": []}'
        assert not any(p.name == "fanout-timings.json" for p in entries)
        assert dest is not None and not (dest / "fanout-timings.json").exists()


def test_an_open_build_state_stays_when_the_map_is_archived():
    """A lead that opens the state before archiving must not lose it: only `state start` creates
    the file, so a moved state drops every later event of the build in silence."""
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        buildstate.start(root)
        dest, entries = archive_map.archive(root)
        assert dest is not None
        assert buildstate.STATE_NAME not in {p.name for p in entries}
        assert (root / ".coyomap" / buildstate.STATE_NAME).is_file()
        assert buildstate.append(root, "decision", "pin A") is True


def test_an_ended_build_state_moves_with_its_map():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_repo(tmp)
        buildstate.start(root)
        buildstate.append(root, "end", "ship complete")
        dest, entries = archive_map.archive(root)
        assert dest is not None
        assert buildstate.STATE_NAME in {p.name for p in entries}
        assert (dest / buildstate.STATE_NAME).is_file()
