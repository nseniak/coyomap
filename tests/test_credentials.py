"""The credential scan `finalize` runs over what its commit line force-adds (retro 2026-09-30,
finding 6).

On the 2026-09-30 mcpolis build a skeptic's recursive search printed the production API key into
its own transcript, and nothing scanned the agents' files the commit line takes. The scan looks for
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
