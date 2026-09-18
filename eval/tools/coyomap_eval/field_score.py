#!/usr/bin/env python3
"""`coyomap-eval field-score` — score a partial run that WRITES map fields against the writing rules.

A tier-2b run of an authoring step hands a fresh agent the changed method text and a real project,
and gets back rows it wrote from scratch. Scoring them is the same question every time: does each
field obey the rules a reader's sentence obeys, and does the validator stay quiet about the result.
The trigger/outcome split was scored by a throwaway script in a scratchpad, the T0 Goal runs before
it by another, and a scorer nobody commits is a scorer that drifts from the checks it is meant to
share. This reads the SAME helpers the product does — `coyomap.prose` for the sentence rules and the
validator's own advisories for the row rules — so a run can never be graded against a second, softer
copy of the method.

WHAT IT DOES NOT DO. It says nothing about whether the rows are TRUE of the project, or whether the
six a run chose are the six worth having. Those are a reading job, and the guess section the run
returns is where that value has always been: across four past runs the score barely moved while the
guess sections produced thirty-odd defects in the wording. Use this to clear the mechanical floor in
one command, then read the prose.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from coyomap.model import ProjectModel, UseCase
from coyomap.prose import SENTENCE_WORD_LIMIT, field_findings, sentences, word_count
from coyomap.validate_model import _outside_face_warnings

USAGE = f"""usage: coyomap-eval field-score <run.json> [<run.json> ...] [--json]

Each <run.json> is what a partial run wrote: a list of rows, or an object with a `use_cases` list.
A row carries an `id` and the fields the run was asked to author. Recognised today:

  trigger, outcome   a use case's outside face — the pair a card joins with an arrow

Every named field is checked for: present and not blank; exactly one sentence; at most
{SENTENCE_WORD_LIMIT} words; no arrow inside it (the viewer adds that, an author never does); and no
readability finding (`coyomap.prose.field_findings` — an em dash, a code name, a bare opening, an
unresolved reference). The PAIR is then read as one box, which is what a reader meets on a card, and
the map's own advisory for a half-written outside face is run over the rows.

Exit 1 on any failure, so a partial run can be gated on it.

  --json   machine-readable
"""

# The viewer joins the pair; an author never types the join. Any of the three spellings is the same
# mistake — the two halves written into one field, or one half carrying both.
_ARROW = re.compile(r"→|->|=>")
# Read as ONE BOX, never per half: the card shows the two together, so a reference in the outcome may
# point at what the trigger named. Splitting the box produced 29 findings across six live maps, every
# one of them false (see `prose.iter_prose_fields`).
_PAIR = ("trigger", "outcome")


def field_failures(row_id: str, label: str, text: str) -> list[str]:
    """Every rule one authored field breaks, in the reader's words."""
    body = (text or "").strip()
    if not body:
        return [f"{row_id}.{label}: empty"]
    out: list[str] = []
    if _ARROW.search(body):
        out.append(f"{row_id}.{label}: holds an arrow — the viewer adds that, an author never does")
    n = len(sentences(body))
    if n != 1:
        out.append(f"{row_id}.{label}: {n} sentences, the rule is one")
    words = word_count(body)
    if words > SENTENCE_WORD_LIMIT:
        out.append(f"{row_id}.{label}: {words} words, the cap is {SENTENCE_WORD_LIMIT}")
    return out


def row_failures(row: dict) -> list[str]:
    """One row: every field's own rules, then the rules the PAIR carries together."""
    rid = str(row.get("id") or "?")
    out: list[str] = []
    for label in _PAIR:
        if label in row:
            out.extend(field_failures(rid, label, row.get(label) or ""))
    trigger, outcome = (row.get("trigger") or "").strip(), (row.get("outcome") or "").strip()
    if trigger and outcome:
        # THE BOX, and the readability rules that read a whole one. Joined with a space and not the
        # card's arrow: the sentence split reads a full stop, so an arrow in the middle would fuse
        # the two into one sentence and every pair would trip the word cap.
        for f in field_findings(f"{rid} trigger and outcome", f"{trigger} {outcome}"):
            out.append(f"{rid}: {f.kind} — {f.detail}")
        if set(trigger.lower().split()) == set(outcome.lower().split()):
            out.append(f"{rid}: the two halves hold the same words")
    return out


def rows_of(path: Path) -> list[dict]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    rows = loaded.get("use_cases", []) if isinstance(loaded, dict) else loaded
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a list of rows, or an object with a `use_cases` list")
    return [r for r in rows if isinstance(r, dict)]


def score(path: Path) -> tuple[int, list[str]]:
    """(fields checked, failures) for one run's file."""
    rows = rows_of(path)
    fails = [f for r in rows for f in row_failures(r)]
    # …and the MAP's own advisory, over the same rows, so a run is held to the check a real build is
    # held to rather than to this file's opinion of it.
    model = ProjectModel()
    model.use_cases = [UseCase(id=str(r.get("id") or f"UC{i}"), name=str(r.get("name") or ""),
                               trigger=(r.get("trigger") or ""), outcome=(r.get("outcome") or ""))
                       for i, r in enumerate(rows, 1)]
    fails.extend(f"validator: {w}" for w in _outside_face_warnings(model))
    checked = sum(1 for r in rows for label in _PAIR if label in r)
    return checked, fails


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    as_json = "--json" in argv
    if not args or "--help" in argv or "-h" in argv:
        print(USAGE)
        return 0 if "--help" in argv or "-h" in argv else 2
    report, bad = [], 0
    for name in args:
        path = Path(name)
        if not path.is_file():
            print(f"no such run file: {path}", file=sys.stderr)
            return 2
        checked, fails = score(path)
        bad += len(fails)
        report.append({"run": str(path), "rows": len(rows_of(path)), "fields": checked,
                       "failures": fails})
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for r in report:
            head = f"{r['run']}: {r['rows']} row(s), {r['fields']} field(s)"
            print(f"{head} — {len(r['failures'])} failure(s)" if r["failures"]
                  else f"{head} — every field passed")
            for f in r["failures"]:
                print(f"    {f}")
        # The floor, and the sentence that stops it being mistaken for the answer.
        print("\nThe score is the mechanical floor only. Read the run's own \"where I had to guess\" "
              "section next: that is where every wording defect has come from.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
