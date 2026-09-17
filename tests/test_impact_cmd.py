#!/usr/bin/env python3
"""`coyomap impact` — the impact engine as a command: the boxes a code change touches, as text for
the agent and as JSON for `changes check --touched`. Real temp git repo, no fixtures/classes."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from coyomap import impact_cmd
from coyomap.model import to_canonical_json

from test_impact import GUILD_V1, commit, make_model


def make_changed_repo(td: str) -> tuple[Path, str, str]:
    """The impact fixture repo, then a commit that puts two lines above everything and rewrites the
    line the map's arrow is anchored on (svc/guild.py:8)."""
    root = Path(td)
    pin = commit(root, {"svc/guild.py": GUILD_V1, "README.md": "hi\n"}, msg="pin")
    (root / ".coyomap").mkdir()
    doc = json.loads(to_canonical_json(make_model(pin)))
    doc["entry_points"] = [{"id": "EP1", "kind": "cli", "trigger": "run it", "source": "svc/guild.py:12", "component": "C1"}]
    (root / ".coyomap" / "project-map.json").write_text(json.dumps(doc), encoding="utf-8")
    lines = GUILD_V1.splitlines()
    lines[7] = lines[7] + "  # changed"
    head = commit(root, {"svc/guild.py": "\n".join(["# one", "# two", *lines]) + "\n"}, msg="edit")
    return root, pin, head


def test_the_text_names_the_boxes_the_change_touched(capsys):
    with tempfile.TemporaryDirectory() as td:
        root, pin, head = make_changed_repo(td)
        assert impact_cmd.main(["--map", str(root / ".coyomap" / "project-map.json"), "--target", head]) == 0
        out = capsys.readouterr().out
        head_line = out.splitlines()[0]
        assert head_line.startswith(f"impact — {pin[:10]} → {head[:10]}: 1 file(s) changed, 5 box(es) hit, "
                                    "1 of them at the gate (*)"), head_line
        assert head_line.endswith("; 1 file(s) under .coyomap/ not counted"), "the map file itself is counted apart"
        assert "Arrows:" in out and "* edge:C1>uses>D1" in out and "Svc uses Store" in out, \
            "an arrow reads by its ends, and the one hit the gate counts is marked"
        assert "at line resolution" in out
        assert "  EP1 " in out and "run it" in out and "ep:svc/guild.py" not in out, \
            "a way in shows the id `dump --id` resolves, named by its trigger"
        assert "    E1 " in out and "* E1" not in out, "a file-resolution hit is listed for reading, unmarked"


def test_the_json_is_the_engine_s_result_and_names_the_range(capsys):
    with tempfile.TemporaryDirectory() as td:
        root, pin, head = make_changed_repo(td)
        assert impact_cmd.main(["--map", str(root / ".coyomap" / "project-map.json"), "--target", head, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["spec"]["base"] == pin and payload["spec"]["target"] == head
        hit = payload["impacts"]["edge:C1>uses>D1"]
        assert hit["cause"] == "direct" and hit["resolution"] == "line"


def test_the_command_refuses_a_bad_ref_a_bad_option_and_needs_a_map(capsys):
    with tempfile.TemporaryDirectory() as td:
        root, _pin, _head = make_changed_repo(td)
        m = str(root / ".coyomap" / "project-map.json")
        assert impact_cmd.main(["--map", m, "--target", "--upload-pack=x"]) == 2
        assert impact_cmd.main(["--map", m, "--target", "nope-not-a-ref"]) == 2 and "ERROR" in capsys.readouterr().err
        assert impact_cmd.main(["--map", m, "--bogus"]) == 2 and "unknown option" in capsys.readouterr().err
    assert impact_cmd.main(["--target", "HEAD"]) == 2 and "--map" in capsys.readouterr().err
    assert impact_cmd.main(["--help"]) == 0 and "usage: coyomap impact" in capsys.readouterr().out
    assert impact_cmd.main([]) == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
