"""The credential scan `finalize` runs over the files of the map (retro 2026-09-30, finding 6).

On the 2026-09-30 mcpolis build a skeptic's recursive search printed the production API key into
its own transcript, and nothing scanned the agents' files a commit of the map takes. The scan looks for
SPECIFIC shapes: a naive "32 or more characters" rule hit 247 strings in 7 of that map's committed
files.

THIS FILE HOLDS NO CREDENTIAL-SHAPED VALUE. Every value below is assembled at run time from a
vendor prefix and repeated filler, so the source never carries the shape it tests.
"""
from __future__ import annotations

import contextlib
import io
import tempfile
from pathlib import Path

from coyomap import finalize
from coyomap.credentials import REDACTED, SHAPES, main, map_folder_files, redact, scan


def make_shaped_values() -> dict[str, str]:
    """One value per shape in `SHAPES`, built from filler — the shape, never a real key."""
    return {
        "AWS access key id": "AK" + "IA" + "Q" * 16,
        "GitHub token": "gh" + "p_" + "a" * 36,
        "GitHub fine-grained token": "github" + "_pat_" + "b" * 60,
        "Slack token": "xo" + "xb-" + "1" * 12 + "-" + "c" * 12,
        "Stripe live key": "sk" + "_live_" + "d" * 24,
        "Anthropic API key": "sk" + "-ant-" + "e" * 40,
        "OpenAI API key": "sk" + "-" + "f" * 40,
        "Google API key": "AI" + "za" + "g" * 35,
        "E2B API key": "e2" + "b_" + "0" * 40,
        "GitLab token": "gl" + "pat-" + "k" * 20,
        "Slack webhook": ("https://hooks." + "slack.com/services/T" + "0" * 8 + "/B" + "1" * 8
                          + "/" + "p" * 24),
        "Google OAuth client secret": "GOC" + "SPX-" + "n" * 28,
        "Hugging Face token": "h" + "f_" + "m" * 34,
        "private key block": "-----BEGIN " + "RSA PRIV" + "ATE KEY-----",
        "JSON web token": "ey" + "J" + "h" * 12 + ".ey" + "J" + "i" * 12 + "." + "j" * 12,
    }


def make_file(td: Path, name: str, text: str) -> Path:
    p = td / name
    p.write_text(text, encoding="utf-8")
    return p


def test_every_shape_is_found_by_its_own_pattern() -> None:
    values = make_shaped_values()
    assert set(values) == {name for name, _ in SHAPES}, "a shape has no test value"
    with tempfile.TemporaryDirectory() as td:
        for name, value in values.items():
            f = make_file(Path(td), "f.json", f'{{"note": "the setting holds {value} today"}}\n')
            assert name in {h.shape for h in scan([f])}, name


def test_a_hit_names_the_place_and_the_shape_never_the_value() -> None:
    value = make_shaped_values()["E2B API key"]
    with tempfile.TemporaryDirectory() as td:
        f = make_file(Path(td), "v.json", "first line\n" + f"the key is {value}\n")
        hits = scan([Path(td)])
    assert [(h.path.name, h.line, h.shape) for h in hits] == [("v.json", 2, "E2B API key")]
    assert value not in repr(hits[0])


def test_ids_digests_and_long_words_a_map_is_full_of_are_not_credentials() -> None:
    """The false alarms a naive length rule raised: digests, commit shas, uuids, long paths."""
    ordinary = "\n".join([
        "sha256 " + "0123456789abcdef" * 4,
        "commit " + "a1b2c3d4e5" * 4,
        "id 123e4567-e89b-12d3-a456-426614174000",
        "backend/src/mcpolis/adapters/repositories/mongo_upstream_config_repository.py:133",
        "tokenExpiryInSecondsForTheDashboardSessionCookie",
        "sk-lines are a prefix a sentence can start with",
    ])
    with tempfile.TemporaryDirectory() as td:
        assert scan([make_file(Path(td), "m.json", ordinary)]) == []


# --- after the review of finding 6 ---------------------------------------------------------------

def test_a_value_right_after_a_json_escape_an_underscore_or_an_encoded_byte_is_found() -> None:
    """`\\b` missed all four shapes the review tried right after a JSON `\\n`: the escape's letter is
    a word character, and the files the scan reads are mostly JSON."""
    values = make_shaped_values()
    with tempfile.TemporaryDirectory() as td:
        for name in ("AWS access key id", "Anthropic API key", "JSON web token", "GitHub token"):
            v = values[name]
            for text in ('{"note": "first\\n' + v + '"}', "KEY_" + v, "key%3D" + v):
                f = make_file(Path(td), "f.json", text + "\n")
                assert name in {h.shape for h in scan([f])}, (name, text[:12])


def test_new_style_keys_and_pgp_blocks_are_found() -> None:
    new = {"OpenAI API key": ["sk" + "-proj-" + "ab_c-" * 8, "sk" + "-svcacct-" + "d_e" * 9,
                              "sk" + "-admin-" + "f-g" * 9],
           "private key block": ["-----BEGIN " + "PGP PRIV" + "ATE KEY BLOCK-----"]}
    with tempfile.TemporaryDirectory() as td:
        for name, vs in new.items():
            for v in vs:
                f = make_file(Path(td), "f.json", f"the value {v} here\n")
                assert name in {h.shape for h in scan([f])}, (name, v[:10])


def test_redact_masks_every_value_and_keeps_the_rest() -> None:
    values = make_shaped_values()
    text = "before " + values["E2B API key"] + " middle " + values["AWS access key id"] + " after"
    out = redact(text)
    assert out == f"before {REDACTED} middle {REDACTED} after", out
    assert redact("nothing here") == "nothing here"


def test_the_map_folder_scan_leaves_archived_maps_aside() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        make_file(d, "a.json", "{}")
        (d / "dev-rebuilds" / "0001").mkdir(parents=True)
        make_file(d / "dev-rebuilds" / "0001", "b.json", "{}")
        (d / "changes").mkdir()
        make_file(d / "changes", "c.json", "{}")
        assert [f.relative_to(d).as_posix() for f in map_folder_files(d)] == ["a.json",
                                                                              "changes/c.json"]


def test_the_credentials_verb_exits_1_and_never_prints_the_value() -> None:
    value = make_shaped_values()["E2B API key"]
    with tempfile.TemporaryDirectory() as td:
        make_file(Path(td), "v.json", f"the key is {value}\n")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([td])
    assert code == 1
    said = out.getvalue() + err.getvalue()
    assert "v.json:1: E2B API key" in said and value not in said, said


# --- a file no commit takes (round 1, 2026-10-07) ------------------------------------------------
# The build state, the findings and their report stay on this machine. `finalize` reported a value
# there as an advisory, and this verb, which an update's close runs and needs at exit 0, failed on it.

#: Files of a map folder that no commit takes, as the tools write them.
LOCAL_FILES = ["findings/harvest-1.jsonl", "build-state.log", "build-state.prev.log",
               "findings-report.md"]


def make_map_folder(td: str, files: list[str]) -> tuple[Path, str]:
    """A map folder with a key-shaped value in each of `files`: (the folder, the value)."""
    folder = Path(td) / ".coyomap"
    value = make_shaped_values()["GitHub token"]
    for rel in files:
        f = folder / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"a line holding {value}\n", encoding="utf-8")
    return folder, value


def run_credentials(folder: Path) -> tuple[int, str, str]:
    """`coyomap credentials <folder>` in process: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(folder)])
    return code, out.getvalue(), err.getvalue()


def make_warned(err: str) -> list[str]:
    """The files the WARNING lines of `err` name."""
    return [line[len("WARNING: "):].split(": line ", 1)[0] for line in err.splitlines()
            if line.startswith("WARNING: ")]


def test_a_key_in_a_file_no_commit_takes_warns_and_does_not_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        folder, value = make_map_folder(td, LOCAL_FILES)
        code, out, err = run_credentials(folder)
    assert code == 0, (out, err)
    assert sorted(make_warned(err)) == sorted(str(folder / rel) for rel in LOCAL_FILES), err
    assert all("so it stops no commit. Remove that line from the file" in line
               for line in err.splitlines()), err
    assert "CREDENTIALS FOUND" not in err
    assert out.rstrip().endswith("4 in 4 file(s) no commit takes, each named in a WARNING line"), out
    assert value not in out + err, "the scan printed the value it found"


def test_a_key_in_a_committed_file_still_fails_beside_a_warning() -> None:
    with tempfile.TemporaryDirectory() as td:
        folder, value = make_map_folder(td, ["verify/verdicts-backbone-1.json",
                                             "findings/harvest-1.jsonl"])
        code, out, err = run_credentials(folder)
    assert code == 1, (out, err)
    assert out.splitlines() == [f"{folder / 'verify' / 'verdicts-backbone-1.json'}:1: GitHub token"]
    assert make_warned(err) == [str(folder / "findings" / "harvest-1.jsonl")], err
    assert "CREDENTIALS FOUND: 1 credential-shaped value(s) in 1 file(s)" in err, err
    assert value not in out + err


def test_finalize_and_the_credentials_verb_agree_on_every_file() -> None:
    """ONE answer to which files no commit takes: a file finalize blocks on is a file this verb
    fails on, and a file finalize only advises about is one this verb only warns about. A name of a
    file no commit takes, deeper in the folder or as a file where a folder is meant, is a committed
    file all the same."""
    committed = ["project-map.json", ".ignore", "verify/verdicts-backbone-1.json",
                 "build-fragments/harvest-1.json", "changes/a1-b2.json", "verify/build-state.log",
                 "findings"]
    with tempfile.TemporaryDirectory() as td:
        folder, _value = make_map_folder(td, [*committed, *LOCAL_FILES[1:],
                                              "findings-old/harvest-1.jsonl"])
        leg = finalize._credential_leg(folder / "project-map.json")
        _code, out, err = run_credentials(folder)
    failed = sorted(line.split(":", 1)[0] for line in out.splitlines() if ": GitHub token" in line)
    blocked = sorted(row.split(": line ", 1)[0] for row in leg.blocking)
    advised = sorted(row.split(": line ", 1)[0] for row in leg.advisory)
    assert failed == blocked == sorted(str(folder / rel) for rel in
                                       [*committed, "findings-old/harvest-1.jsonl"]), (failed, blocked)
    assert sorted(make_warned(err)) == advised == sorted(str(folder / rel)
                                                         for rel in LOCAL_FILES[1:]), (err, advised)
