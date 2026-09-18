"""`coyomap-eval field-score`: rows a partial run WROTE, against the writing rules."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from coyomap_eval import field_score


def make_row(rid: str = "UC1", **over: str) -> dict:
    """One clean row — both halves, one sentence each, well under the word cap."""
    row = {"id": rid, "name": "Open a map",
           "trigger": "A person opens a project's map.",
           "outcome": "The person sees what the product does."}
    row.update(over)
    return row


def make_run(rows: list[dict], tmp: Path) -> Path:
    f = tmp / "run.json"
    f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return f


def test_a_clean_run_passes_every_field() -> None:
    with tempfile.TemporaryDirectory() as td:
        checked, fails = field_score.score(make_run([make_row("UC1"), make_row("UC2")], Path(td)))
    assert checked == 4 and fails == [], fails


def test_the_four_field_rules_each_name_the_row_that_broke_them() -> None:
    """One failure line per rule broken, naming the row and the field, because a run is 12 fields and
    "something is wrong" sends the reader back through all of them."""
    long = " ".join(["word"] * 30) + "."
    rows = [make_row("UC1", outcome=""),                                   # blank
            make_row("UC2", trigger="A person asks -> the map opens."),    # the viewer's join
            make_row("UC3", outcome="It opens. Then it closes."),          # two sentences
            make_row("UC4", outcome=long)]                                 # over the cap
    with tempfile.TemporaryDirectory() as td:
        _, fails = field_score.score(make_run(rows, Path(td)))
    said = "\n".join(fails)
    assert "UC1.outcome: empty" in said, said
    assert "UC2.trigger" in said and "arrow" in said, said
    assert "UC3.outcome: 2 sentences" in said, said
    assert "UC4.outcome: 30 words" in said, said


def test_the_pair_is_read_as_one_box() -> None:
    """A BOX is the unit the readability rules read by, and the box a reader meets is the card, which
    shows the two halves together. Scored apart, an outcome opening "They" or "That account" is a
    bare pointer at nothing; scored as one box it points at the person the trigger just named. The
    live maps produced 29 of those, every one false, which is why this is pinned."""
    row = make_row("UC1", trigger="An administrator picks a different plan on one account's page.",
                   outcome="That account moves to the chosen plan.")
    with tempfile.TemporaryDirectory() as td:
        _, fails = field_score.score(make_run([row], Path(td)))
    assert fails == [], fails
    # …and a pointer with nothing behind it ANYWHERE in the pair is still caught.
    lost = make_row("UC2", trigger="It runs.", outcome="They are told.")
    with tempfile.TemporaryDirectory() as td:
        _, fails = field_score.score(make_run([lost], Path(td)))
    assert any("bare pointer" in f for f in fails), fails


def test_the_maps_own_advisory_runs_over_the_rows() -> None:
    """A run is held to the check a real build is held to, never to this file's copy of it: the
    half-written outside face is the validator's own warning, called here."""
    with tempfile.TemporaryDirectory() as td:
        _, fails = field_score.score(make_run([make_row("UC1", outcome="")], Path(td)))
    assert any(f.startswith("validator:") and "no outcome" in f for f in fails), fails


def test_the_command_exits_one_on_a_failure_and_zero_on_a_clean_run(capsys) -> None:
    with tempfile.TemporaryDirectory() as td:
        clean = make_run([make_row()], Path(td))
        assert field_score.main([str(clean)]) == 0
        assert "every field passed" in capsys.readouterr().out
        broken = make_run([make_row(outcome="")], Path(td))
        assert field_score.main([str(broken)]) == 1
    # The floor is never mistaken for the answer: the run's own guess section is named every time.
    assert "where I had to guess" in capsys.readouterr().out


def test_an_object_with_a_use_cases_list_is_read_too(capsys) -> None:
    """Two shapes reach this in practice: the bare list a brief asks for, and a whole fragment."""
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "run.json"
        f.write_text(json.dumps({"use_cases": [make_row()]}), encoding="utf-8")
        checked, fails = field_score.score(f)
    assert checked == 2 and fails == [], fails
