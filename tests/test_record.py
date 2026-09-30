#!/usr/bin/env python3
"""Tests for `coyomap record` — the one writer for a recorded exception.

Every advisory family names an extras heading an operator may write a `<id>: <why>` line under, and
there was no command to write one. A live build hand-appended into one fragment's extras SIX times,
with no check that the heading was one a tool reads, no check on the line's shape, no dedup, and no
way to correct a record whose facts moved — it find-and-replaced its own paragraph two turns later
with a fragile `body.find(...)` + `assert`.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_record.py
    pytest tests/test_record.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from coyomap.model import ExtraSection, ProjectModel, to_canonical_json
from coyomap.record import KNOWN_HEADINGS, append_line, main
from test_business_rules import make_swept_model


def make_fragment(tmp: str, extras: list[dict] | None = None) -> Path:
    p = Path(tmp) / "behavioral.json"
    p.write_text(json.dumps({"title": "T", "goal": "g", "extras": extras or []}), encoding="utf-8")
    return p


def make_model(heading: str = "", body: str = "") -> ProjectModel:
    m = ProjectModel(title="T", goal="g")
    if heading:
        m.extras = [ExtraSection(heading=heading, body=body)]
    return m


def test_appending_creates_the_section_when_it_is_absent():
    m = make_model()
    changed, msg = append_line(m, "Balance exceptions", "UC5: two clauses, one goal — checkout.")
    assert changed and "recorded under" in msg
    assert m.extras[0].heading == "Balance exceptions"
    assert "UC5:" in m.extras[0].body


def test_appending_keeps_the_lines_already_there():
    m = make_model("Balance exceptions", "UC1: first — why.\n")
    append_line(m, "Balance exceptions", "UC2: second — why.")
    body = m.extras[0].body
    assert "UC1: first" in body and "UC2: second" in body


def test_recording_the_same_line_twice_is_a_no_op():
    m = make_model("Balance exceptions", "UC1: first — why.\n")
    changed, msg = append_line(m, "Balance exceptions", "UC1: first — why.")
    assert not changed and "already recorded" in msg
    assert m.extras[0].body.count("UC1:") == 1


def test_replace_rewrites_the_line_instead_of_appending_a_second_one():
    """The stale-paragraph problem: a live build wrote a fourteen-component list, then had to
    find-and-replace its own text with a hand-rolled body.find() + assert."""
    m = make_model("Balance exceptions", "isolated: 14 components — why.\n")
    changed, msg = append_line(m, "Balance exceptions", "isolated: 7 components — the corrected why.",
                               replace_prefix="isolated:")
    assert changed and "replaced under" in msg
    assert m.extras[0].body.count("isolated:") == 1
    assert "7 components" in m.extras[0].body


def test_replace_says_so_when_nothing_matched():
    m = make_model("Balance exceptions", "UC1: first — why.\n")
    changed, msg = append_line(m, "Balance exceptions", "isolated: 7 — why.",
                               replace_prefix="isolated:")
    assert not changed and "nothing replaced" in msg


def test_the_heading_must_be_one_a_check_actually_reads():
    """A line under an invented heading silences nothing, and the operator believes it was handled."""
    with tempfile.TemporaryDirectory() as tmp:
        frag = make_fragment(tmp)
        assert main(["--map", str(frag), "--heading", "My notes", "--line", "UC1: because"]) == 2


def test_every_known_heading_is_accepted():
    """One line per heading, in that family's OWN grammar.

    This used to send `UC1: a stated reason` to every heading. For 'Audit exceptions' that keys
    nothing — the family's shape is `<check-name> <id>, <id>: <why>` — and the command wrote it
    anyway, which is the defect `test_record_refuses_a_line_that_keys_to_nothing` now holds. A
    generic line here would have to be accepted by a command that must refuse it.
    """
    per_heading = {"Audit exceptions": "read-before-create HP1: a stated reason"}
    with tempfile.TemporaryDirectory() as tmp:
        for heading in KNOWN_HEADINGS:
            frag = make_fragment(tmp)
            line = per_heading.get(heading, "UC1: a stated reason")
            assert main(["--map", str(frag), "--heading", heading, "--line", line]) == 0, heading


def test_a_key_with_no_why_is_refused():
    """A key alone is a dismissal — the rule every escape family already states."""
    with tempfile.TemporaryDirectory() as tmp:
        frag = make_fragment(tmp)
        assert main(["--map", str(frag), "--heading", "Balance exceptions", "--line", "UC5:"]) == 2
        assert main(["--map", str(frag), "--heading", "Balance exceptions", "--line", "UC5"]) == 2


def test_the_heading_match_is_case_and_space_tolerant_like_the_readers():
    with tempfile.TemporaryDirectory() as tmp:
        frag = make_fragment(tmp, [{"heading": "Balance exceptions", "body": "UC1: a — why.\n"}])
        assert main(["--map", str(frag), "--heading", "  balance EXCEPTIONS ",
                     "--line", "UC2: b — why."]) == 0
        doc = json.loads(frag.read_text())
        sections = [x for x in doc["extras"] if x["heading"] == "Balance exceptions"]
        assert len(sections) == 1, "must not create a second section that differs only in case"
        assert "UC1:" in sections[0]["body"] and "UC2:" in sections[0]["body"]


def test_an_unreadable_map_is_refused_rather_than_created():
    with tempfile.TemporaryDirectory() as tmp:
        missing = str(Path(tmp) / "nope.json")
        assert main(["--map", missing, "--heading", "Balance exceptions", "--line", "UC1: w"]) == 2
        assert not Path(missing).exists()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok   {fn.__name__}")


# --- the extras fragment is seeded, not demanded (retro 2026-08-14) -------------------------------
# A build ran 21 well-formed `record` calls in one turn and every one failed with `cannot read …
# extras.json — no such file`: no fan-out agent owns creating that fragment. The workaround was
# `echo '{"extras": []}' >`, i.e. the hand-rolled write this command exists to replace.

def test_a_missing_extras_fragment_is_seeded_and_the_record_lands(capsys):
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "extras.json"
        assert main(["--map", str(target), "--heading", "Audit exceptions",
                     "--line", "read-never-created HP5: seeded out of band by the demo"]) == 0
        assert "seeded" in capsys.readouterr().out
        doc = json.loads(target.read_text())
        assert doc["extras"][0]["heading"] == "Audit exceptions"
        assert "HP5" in doc["extras"][0]["body"]


def test_seeding_is_limited_to_extras_json_so_a_typo_is_still_refused(capsys):
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "project-mapp.json"          # a plausible typo
        assert main(["--map", str(target), "--heading", "Audit exceptions", "--line", "HP5: why"]) == 2
        assert "no such file" in capsys.readouterr().err
        assert not target.exists(), "a typo'd path must never be created"


def test_seeding_does_not_invent_a_missing_parent_directory(capsys):
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "nope" / "extras.json"
        assert main(["--map", str(target), "--heading", "Audit exceptions", "--line", "HP5: why"]) == 2
        capsys.readouterr()
        assert not target.parent.exists()


def test_a_missing_target_is_reported_before_the_argument_shape(capsys):
    """Probing the failure with a malformed line reported the ARGUMENT complaint first and hid the
    real cause — the operator learned about their `--line` and not about the path that did not
    exist."""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "gone.json"
        assert main(["--map", str(target), "--heading", "Audit exceptions",
                     "--line", "no-why-here"]) == 2
        err = capsys.readouterr().err
        assert "no such file" in err, err
        assert "states no why" not in err, err


def test_a_failed_record_leaves_no_stray_seeded_fragment_behind():
    """Seeding ran before the argument check, so a call that exited 2 on a malformed --line still
    created `{"extras": []}` on disk."""
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "extras.json"
        assert main(["--map", str(target), "--heading", "Audit exceptions",
                     "--line", "no-why-here"]) == 2
        assert not target.exists(), "a refused call must not leave a fragment behind"


# --- removing a record that went stale --------------------------------------------
# A build recorded a sweep-debt line, then ten turns later wrote a business rule covering the same
# anchor — so the record now silenced a step the map claims. There was `--replace` and no way to
# remove, so the deletion went out as a `python3 - <<'PY'` splice of extras.json: the hand-rolled
# JSON write this command exists to end, in the other direction.


def test_remove_deletes_the_line_that_starts_with_the_prefix():
    from coyomap.record import remove_line
    m = ProjectModel(extras=[ExtraSection(heading="Sweep debt",
                                          body="a.py:1: one\nb.py:2: two\n")])
    changed, message = remove_line(m, "Sweep debt", "a.py:1")
    assert changed and "removed under 'Sweep debt'" in message
    assert m.extras[0].body.strip() == "b.py:2: two"


def test_removing_the_last_line_takes_the_heading_with_it():
    """An empty heading still reads as 'an exception was recorded here'."""
    from coyomap.record import remove_line
    m = ProjectModel(extras=[ExtraSection(heading="Sweep debt", body="a.py:1: one\n")])
    changed, message = remove_line(m, "Sweep debt", "a.py:1")
    assert changed and "the heading is gone too" in message
    assert m.extras == []


def test_removing_something_that_is_not_there_changes_nothing():
    from coyomap.record import remove_line
    m = ProjectModel(extras=[ExtraSection(heading="Sweep debt", body="a.py:1: one\n")])
    changed, message = remove_line(m, "Sweep debt", "zzz")
    assert not changed and "nothing removed" in message
    assert m.extras[0].body.strip() == "a.py:1: one"


def test_remove_refuses_to_combine_with_a_write():
    from coyomap.record import main
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "extras.json"
        p.write_text('{"extras": []}', encoding="utf-8")
        assert main(["--map", str(p), "--heading", "Sweep debt",
                     "--remove", "a.py:1", "--line", "b.py:2: two"]) == 2


def test_record_refuses_a_line_that_keys_to_nothing(tmp_path):
    """A line that adjudicates nothing silences nothing, silently.

    `record` checked the heading and that the line carried a `:` with a why, and stopped there. A
    live build wrote `read-before-create HP2, read-before-create HP3: …` — the check name repeated
    inside the comma list, where the family's grammar is the name ONCE then bare ids — and the
    line keyed zero ids. Unrecorded advisories went 1 to 9, and three extra `finalize` + `render`
    rounds were spent finding the shape by trial. `malformed_records` already knew the family's
    vocabulary; nothing asked it before writing.
    """
    frag = tmp_path / "extras.json"
    frag.write_text(json.dumps({"extras": []}), encoding="utf-8")
    before = frag.read_text(encoding="utf-8")

    code = main(["--map", str(frag), "--heading", "Audit exceptions",
                 "--line", "read-before-create HP2, read-before-create HP3: each reads its own"])
    assert code == 1, "a line that keys nothing must be refused"
    assert frag.read_text(encoding="utf-8") == before, "the refusal must write nothing"

    # The documented shape — the check name once, then bare ids — still works.
    assert main(["--map", str(frag), "--heading", "Audit exceptions",
                 "--line", "read-before-create HP2, HP3: each reads its own"]) == 0
    assert "HP3" in frag.read_text(encoding="utf-8")


# --- which headings can read a comma list -----------------------------------------
# `--help` says "one reason may answer SEVERAL elements — write them as one comma-separated list".
# That is right for the families with a key grammar and DESTROYS the record on the families without
# one, whose readers match the whole key. The distinction lived only in a module comment, so a build
# followed the advice under `Sweep debt`, silenced 0 of 5 anchors, and spent two rounds finding out.

def test_headings_listing_separates_list_families_from_free_text_ones(capsys):
    from coyomap.record import main
    from coyomap import records
    assert main(["--headings"]) == 0
    out = capsys.readouterr().out
    listed, free = out.split("FREE TEXT")
    for heading in records.KNOWN_HEADINGS:
        spec = records.spec_of(heading)
        assert spec is not None
        where = listed if spec.key else free
        assert heading in where, f"{heading} is on the wrong side of the split"


def test_sweep_debt_is_named_as_a_free_text_family(capsys):
    """The one a live build merged onto two lines, silencing 0 of the 5 anchors they named."""
    from coyomap.record import main
    assert main(["--headings"]) == 0
    out = capsys.readouterr().out
    assert "Sweep debt" in out.split("FREE TEXT")[1]


def test_the_help_no_longer_recommends_the_merged_form_unconditionally():
    from coyomap.record import USAGE
    assert "ONLY WHERE THE HEADING HAS A KEY GRAMMAR" in USAGE
    assert "coyomap record --headings" in USAGE


# --- record refuses what it cannot write, and removes all it is asked to (retro 2026-09-30, 17) -----
# The 2026-09-30 mcpolis build stored 6 comma-listed 'Sweep debt' lines with exit 0 that silenced
# nothing; `--remove A --remove B` removed A only; and a fragment with no `extras` key printed
# "recorded" and "wrote" while the line was dropped.

def make_sweep_repo(tmp: Path) -> Path:
    """An assembled map whose one sweep finding is the step at src/admin.py:4, and an empty extras
    fragment beside it, laid out the way a build lays them out."""
    out = tmp / ".coyomap"
    (out / "build-fragments").mkdir(parents=True)
    (out / "project-map.json").write_text(to_canonical_json(make_swept_model()), encoding="utf-8")
    frag = out / "build-fragments" / "extras.json"
    frag.write_text(json.dumps({"extras": []}), encoding="utf-8")
    return frag


def test_every_remove_is_honoured(tmp_path):
    frag = tmp_path / "extras.json"
    frag.write_text(json.dumps({"extras": [{"heading": "Sweep debt",
                                            "body": "a.py:1: one\nb.py:2: two\nc.py:3: three\n"}]}),
                    encoding="utf-8")
    assert main(["--map", str(frag), "--heading", "Sweep debt",
                 "--remove", "a.py:1", "--remove", "b.py:2"]) == 0
    assert json.loads(frag.read_text(encoding="utf-8"))["extras"][0]["body"].strip() == "c.py:3: three"


def test_a_remove_that_matches_nothing_removes_none_of_the_batch(tmp_path):
    frag = tmp_path / "extras.json"
    frag.write_text(json.dumps({"extras": [{"heading": "Sweep debt", "body": "a.py:1: one\n"}]}),
                    encoding="utf-8")
    before = frag.read_text(encoding="utf-8")
    assert main(["--map", str(frag), "--heading", "Sweep debt",
                 "--remove", "a.py:1", "--remove", "zzz"]) == 1
    assert frag.read_text(encoding="utf-8") == before


def test_a_fragment_with_no_extras_key_is_refused_rather_than_losing_the_line(tmp_path):
    frag = tmp_path / "behavioral.json"
    frag.write_text(json.dumps({"title": "T"}), encoding="utf-8")
    before = frag.read_text(encoding="utf-8")
    assert main(["--map", str(frag), "--heading", "Balance exceptions",
                 "--line", "UC1: a stated reason"]) == 2
    assert frag.read_text(encoding="utf-8") == before


def test_a_free_text_line_that_silences_nothing_is_refused(tmp_path, capsys):
    frag = make_sweep_repo(tmp_path)
    before = frag.read_text(encoding="utf-8")
    assert main(["--map", str(frag), "--heading", "Sweep debt", "--line",
                 "src/admin.py:4, src/guard.py:3: both are overrides, not rules"]) == 1
    assert frag.read_text(encoding="utf-8") == before
    out, err = capsys.readouterr()
    assert "names 2 anchors" in err and "recorded under" not in out, (out, err)
    # the same finding, keyed the way the reader matches it, is written
    assert main(["--map", str(frag), "--heading", "Sweep debt", "--line",
                 "src/admin.py:4: an admin override, not a business rule"]) == 0
    assert "src/admin.py:4: an admin override" in frag.read_text(encoding="utf-8")
