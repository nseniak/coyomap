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

import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from coyomap.model import ExtraSection, ProjectModel, to_canonical_json
from coyomap.record import KNOWN_HEADINGS, USAGE, append_line, main
from test_business_rules import make_swept_model

REPO = Path(__file__).resolve().parent.parent
RECORD = [sys.executable, "-m", "coyomap.record"]


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



def test_a_line_that_silences_nothing_is_refused_whatever_its_reason_says(tmp_path):
    """Review of finding 17: the readability check reads a recorded line's reason, so an em dash
    in the why changed validate's output and the line was kept though it silenced nothing."""
    frag = make_sweep_repo(tmp_path)
    before = frag.read_text(encoding="utf-8")
    assert main(["--map", str(frag), "--heading", "Sweep debt", "--line",
                 "src/nothing_here.py:1: made up \u2014 nothing reads this line"]) == 1
    assert frag.read_text(encoding="utf-8") == before


def test_replacing_a_live_line_under_sweep_debt_is_accepted(tmp_path):
    frag = make_sweep_repo(tmp_path)
    assert main(["--map", str(frag), "--heading", "Sweep debt", "--line",
                 "src/admin.py:4: an admin override, not a business rule"]) == 0
    # the assembled map carries the line too, as the next assemble would make it
    mp = tmp_path / ".coyomap" / "project-map.json"
    doc = json.loads(mp.read_text(encoding="utf-8"))
    doc.setdefault("extras", []).append({"heading": "Sweep debt",
                                         "body": "src/admin.py:4: an admin override, not a business rule\n"})
    mp.write_text(json.dumps(doc), encoding="utf-8")
    assert main(["--map", str(frag), "--heading", "Sweep debt", "--replace", "src/admin.py:4",
                 "--line", "src/admin.py:4: an override an admin makes, not a rule"]) == 0
    assert "an override an admin makes" in frag.read_text(encoding="utf-8")


# --- record writes only the file it is named, and never a map the next assemble rebuilds -----------
# (retro 2026-10-07, finding 5.) A build ran `record .coyomap/build-fragments/extras.json --heading
# "Drift exceptions" --line …`. `record` read its flags by name and dropped the positional, so `--map`
# fell back to the assembled map: the line was written there, the warning was the last line of the
# output, the exit was 0, and the next `assemble` discarded the record.

def run_record(argv: list[str]) -> tuple[int, str, str]:
    """`record` in-process: its exit code, its stdout and its stderr."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def make_extras_file(tmp: Path, body: str) -> Path:
    """An extras fragment holding one 'Balance exceptions' section whose body is `body`."""
    frag = tmp / "extras.json"
    frag.write_text(json.dumps({"extras": [{"heading": "Balance exceptions", "body": body}]}),
                    encoding="utf-8")
    return frag


def test_a_positional_argument_is_refused_and_the_refusal_names_map():
    """Run from the build's own folder in a child process, so the default `--map` is the scratch
    folder's assembled map, exactly as it was the build's."""
    with tempfile.TemporaryDirectory() as td:
        frag = make_sweep_repo(Path(td))
        assembled = frag.parent.parent / "project-map.json"
        before = (assembled.read_text(encoding="utf-8"), frag.read_text(encoding="utf-8"))
        proc = subprocess.run(RECORD + [".coyomap/build-fragments/extras.json",
                                        "--heading", "Balance exceptions",
                                        "--line", "UC1: the two clauses are one goal"],
                              cwd=td, capture_output=True, text=True)
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert "--map .coyomap/build-fragments/extras.json" in proc.stderr, proc.stderr
        after = (assembled.read_text(encoding="utf-8"), frag.read_text(encoding="utf-8"))
        assert after == before, "a refused call must write neither the map nor the fragment"


def test_the_assembled_map_is_refused_while_the_extras_fragment_sits_beside_it():
    with tempfile.TemporaryDirectory() as td:
        frag = make_sweep_repo(Path(td))
        assembled = frag.parent.parent / "project-map.json"
        before = assembled.read_text(encoding="utf-8")
        code, out, err = run_record(["--map", str(assembled), "--heading", "Balance exceptions",
                                     "--line", "UC1: the two clauses are one goal"])
        assert code == 2, out + err
        assert f"--map {frag}" in err, err
        assert assembled.read_text(encoding="utf-8") == before


def make_assembled_build(tmp: Path) -> Path:
    """An assembled map with one build fragment beside it and NO extras fragment: the state between
    the first `assemble` and the first `record`, since nothing else creates `extras.json`. Returns
    the assembled map."""
    out = tmp / ".coyomap"
    (out / "build-fragments").mkdir(parents=True)
    (out / "project-map.json").write_text(to_canonical_json(make_swept_model()), encoding="utf-8")
    (out / "build-fragments" / "header.json").write_text(json.dumps({"title": "Swept"}),
                                                         encoding="utf-8")
    return out / "project-map.json"


def test_the_assembled_map_is_refused_while_any_fragment_sits_beside_it():
    """(Review of finding 5.) The refusal fired only once `build-fragments/extras.json` existed, so
    between the first assemble and the first record `record` wrote the assembled map, exited 0, and
    the next `assemble` dropped the line. The route the refusal names is followed literally here."""
    with tempfile.TemporaryDirectory() as td:
        assembled = make_assembled_build(Path(td))
        extras = assembled.parent / "build-fragments" / "extras.json"
        before = assembled.read_text(encoding="utf-8")
        line = ["--heading", "Balance exceptions", "--line", "UC1: the two clauses are one goal"]
        code, out, err = run_record(["--map", str(assembled), *line])
        assert code == 2, out + err
        assert f"--map {extras}" in err and "seeds it" in err, err
        assert assembled.read_text(encoding="utf-8") == before
        assert not extras.exists(), "a refused call seeds nothing"
        code, out, err = run_record(["--map", str(extras), *line])
        assert code == 0, out + err
        assert "UC1: the two clauses are one goal" in extras.read_text(encoding="utf-8")
        assert assembled.read_text(encoding="utf-8") == before


def test_the_default_map_is_refused_before_the_first_record():
    """The turn-758 call without its positional: no `--map`, so the default, the assembled map, run
    from the build's own folder in a child process exactly as a build runs it."""
    with tempfile.TemporaryDirectory() as td:
        assembled = make_assembled_build(Path(td))
        before = assembled.read_text(encoding="utf-8")
        proc = subprocess.run(RECORD + ["--heading", "Walk jumps", "--line",
                                        "UC1: the operator searches the log store first"],
                              cwd=td, capture_output=True, text=True)
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert "--map .coyomap/build-fragments/extras.json" in proc.stderr, proc.stderr
        assert assembled.read_text(encoding="utf-8") == before


def test_an_empty_fragments_folder_is_nothing_to_assemble_from():
    """The refusal and the closing line ask one question, so a folder holding no fragment neither
    stops the write nor is said to discard it."""
    with tempfile.TemporaryDirectory() as td:
        assembled = make_assembled_build(Path(td))
        (assembled.parent / "build-fragments" / "header.json").unlink()
        code, out, err = run_record(["--map", str(assembled), "--heading", "Balance exceptions",
                                     "--line", "UC1: the two clauses are one goal"])
        assert code == 0, out + err
        assert "UC1: the two clauses are one goal" in assembled.read_text(encoding="utf-8")
        assert "discard" not in out + err, out + err


def test_a_map_with_no_fragments_beside_it_is_still_recorded_into():
    """A map edited directly, with no build fragments beside it, keeps working, and is not told an
    assemble will discard a line when there is nothing to assemble it from."""
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "project-map.json"
        mp.write_text(to_canonical_json(make_swept_model()), encoding="utf-8")
        code, out, err = run_record(["--map", str(mp), "--heading", "Balance exceptions",
                                     "--line", "UC1: the two clauses are one goal"])
        assert code == 0, out + err
        assert "UC1: the two clauses are one goal" in mp.read_text(encoding="utf-8")
        assert "discards" not in out, out


def test_no_reassemble_writes_the_assembled_map_once_the_build_is_over():
    """The fragments are committed with the map as its warrant, so they outlive the build. Once the
    map is changed directly, as an update changes it, nothing assembles it again."""
    with tempfile.TemporaryDirectory() as td:
        frag = make_sweep_repo(Path(td))
        assembled = frag.parent.parent / "project-map.json"
        before = frag.read_text(encoding="utf-8")
        code, out, err = run_record(["--map", str(assembled), "--no-reassemble",
                                     "--heading", "Balance exceptions",
                                     "--line", "UC1: the two clauses are one goal"])
        assert code == 0, out + err
        assert "UC1: the two clauses are one goal" in assembled.read_text(encoding="utf-8")
        assert frag.read_text(encoding="utf-8") == before


def test_an_unknown_option_is_refused_rather_than_ignored():
    """The same silent drop as the positional: `--replac` was ignored, and the corrected line was
    APPENDED beside the one it was meant to replace."""
    with tempfile.TemporaryDirectory() as td:
        frag = make_extras_file(Path(td), "UC1: the old why\n")
        code, _out, err = run_record(["--map", str(frag), "--heading", "Balance exceptions",
                                      "--replac", "UC1", "--line", "UC1: the new why"])
        assert code == 2 and "--replac" in err, err
        assert "the new why" not in frag.read_text(encoding="utf-8")


def test_a_one_value_flag_given_twice_is_refused():
    """`--map a --map b` wrote `a` and said nothing about `b`."""
    with tempfile.TemporaryDirectory() as td:
        a = make_extras_file(Path(td), "UC1: a why\n")
        b = Path(td) / "other.json"
        b.write_text(json.dumps({"extras": []}), encoding="utf-8")
        before = a.read_text(encoding="utf-8")
        code, _out, err = run_record(["--map", str(a), "--map", str(b), "--heading",
                                      "Balance exceptions", "--line", "UC2: a second why"])
        assert code == 2 and "--map" in err, err
        assert a.read_text(encoding="utf-8") == before


def test_every_record_example_names_the_file_it_writes():
    """The method's examples and `record --help` showed `record --heading … --line …` with no `--map`,
    so the default, the assembled map, is what a reader copied. 38 of that build's 39 `record` calls
    passed `--map`; the one that did not came right after the lead's context was summarised."""
    writes = re.compile(r"--(?:line|lines-from|remove|replace)\b")
    docs = [REPO / "method.md", *sorted((REPO / "method").glob("*.md")),
            *sorted((REPO / "method" / "templates").glob("*.md"))]
    missing: list[str] = []
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        # A call runs from `coyomap record` to the backtick or blank line that ends its code, or to
        # the next coyomap command. Not span by span: one ``double-backtick`` span shifts every
        # backtick pairing after it, and the calls after it then read as prose.
        for hit in re.finditer(r"coyomap record\b", text):
            call = " ".join(re.split(r"`|\n\s*\n", text[hit.start():], maxsplit=1)[0].split())
            following = re.search(r"coyomap \w", call[1:])
            call = call[:following.start() + 1] if following else call
            if writes.search(call) and "--map" not in call:
                line = text.count("\n", 0, hit.start()) + 1
                missing.append(f"{doc.relative_to(REPO)}:{line}: {call[:70]}")
    for line in re.sub(r"\\\n\s*", " ", USAGE).splitlines():
        call = line.strip()
        if call.startswith("coyomap record") and writes.search(call) and "--map" not in call:
            missing.append(f"record --help: {call[:70]}")
    assert not missing, "record examples that name no --map:\n" + "\n".join(missing)


# --- a refused `--replace` names the way out (retro 2026-10-07, finding 24) --------------------------
# Both refusals said that `--replace` corrects one record, and stopped there; the lead found the way
# to correct several (remove them, then write the batch) by trying.

def test_a_replace_given_a_batch_names_the_way_out_and_the_way_out_works():
    with tempfile.TemporaryDirectory() as td:
        frag = make_extras_file(Path(td), "UC1: the old why\nUC2: the old why\n")
        lines = Path(td) / "lines.txt"
        lines.write_text("UC1: the new why\nUC2: the new why\n", encoding="utf-8")
        for batch in (["--line", "UC1: the new why", "--line", "UC2: the new why"],
                      ["--lines-from", str(lines)]):
            code, _out, err = run_record(["--map", str(frag), "--heading", "Balance exceptions",
                                          "--replace", "UC1", *batch])
            assert code == 2, err
            assert "--remove" in err and "--lines-from" in err, err
        # the way out the refusal names, followed literally
        assert run_record(["--map", str(frag), "--heading", "Balance exceptions",
                           "--remove", "UC1", "--remove", "UC2"])[0] == 0
        assert run_record(["--map", str(frag), "--heading", "Balance exceptions",
                           "--lines-from", str(lines)])[0] == 0
        body = json.loads(frag.read_text(encoding="utf-8"))["extras"][0]["body"]
        assert "old why" not in body and body.count("the new why") == 2, body
