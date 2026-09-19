#!/usr/bin/env python3
"""`coyomap changes challenge` / `changes ground` — the update's own skeptic wave: which statements
it re-argues, which verdicts it carries across the change, and what the map's record says after.
Real temp git repos, explicit make_* builders, no fixtures/classes."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from coyomap import challenge as ch
from coyomap.audit_model import l2_worklist_model, worklist_payload
from coyomap.changelog import apply, load_log
from coyomap.grounding import build_record, main as grounding_main
from coyomap.impact_git import compute_impact, load_map_extents
from coyomap.impact_ripple import RippleOptions, build_impact_result
from coyomap.model import load_model, to_canonical_json
from coyomap.reanchor import reanchor

from test_impact import commit, make_model

TEN = "\n".join(f"line {i}" for i in range(1, 11)) + "\n"
TWENTY = "\n".join(f"line {i}" for i in range(1, 21)) + "\n"


# --- builders ---------------------------------------------------------------------------------

def make_repo(td: str) -> tuple[Path, str, str]:
    """Commit 1: two anchored files. Commit 2: two lines inserted above everything in a.py and its
    line 8 rewritten; b.py untouched."""
    root = Path(td)
    pin = commit(root, {"svc/a.py": TWENTY, "svc/b.py": TEN}, msg="pin")
    lines = TWENTY.splitlines()
    lines[7] = "line 8 changed"
    head = commit(root, {"svc/a.py": "\n".join(["# one", "# two", *lines]) + "\n"}, msg="edit")
    return root, pin, head


def make_map_doc(pin: str) -> dict[str, Any]:
    """Three components, three arrows, one rule: enough for every reason a statement lands in
    scope. C1's arrow sits on the line the diff rewrites; the rule's site, twelve lines below
    it and outside the gate's window around a call-site link, only shifts."""
    doc = json.loads(to_canonical_json(make_model(pin)))
    doc["components"] = [
        {"id": "C1", "name": "Alpha", "source": "svc/a.py:5", "files": ["svc/a.py"],
         "purpose": "Reads the alpha file."},
        {"id": "C2", "name": "Beta", "source": "svc/b.py:2", "files": ["svc/b.py"],
         "purpose": "Keeps the beta list."},
        {"id": "C3", "name": "Gamma", "source": "svc/b.py:5", "files": ["svc/b.py"],
         "purpose": "Sends gamma mail."}]
    doc["deps"] = [{"id": "D1", "name": "Mailer", "kind": "service", "type": "SMTP"}]
    doc["entities"] = []
    doc["non_entity_types"] = []
    doc["edges"] = [{"src": "C1", "verb": "calls", "dst": "C2", "where": "svc/a.py:8"},
                    {"src": "C2", "verb": "calls", "dst": "C3", "where": "svc/b.py:3"},
                    {"src": "C3", "verb": "uses", "dst": "D1", "where": "svc/b.py:6"}]
    doc["blocks"] = [{"id": "BLK1", "name": "Limits", "purpose": "what is bounded"}]
    doc["rules"] = [{"id": "BR1", "name": "A guard", "statement": "A guard holds.", "block": "BLK1",
                     "sites": [{"where": "svc/a.py:20", "why": "guards"}]},
                    # Its site only shifts too; its BUILD verdict cites the line the diff rewrites.
                    {"id": "BR3", "name": "A second guard", "statement": "A second guard holds.",
                     "block": "BLK1", "sites": [{"where": "svc/a.py:19", "why": "guards twice"}]}]
    # A way in whose declaring line the diff rewrites: a hit the gate files under no box.
    doc["entry_points"] = [{"id": "EP1", "kind": "job", "trigger": "nightly sweep", "component": "C1",
                            "source": "svc/a.py:8", "cadence": "every night",
                            "cadence_source": "svc/a.py:8"}]
    return doc


def make_verdict(claim: str, evidence: str, grounded: object = True,
                 skeptic: str = "build") -> dict[str, Any]:
    return {"claim": claim, "grounded": grounded, "evidence": evidence, "skeptic": skeptic,
            "note": f"read {evidence}"}


def make_build(root: Path, doc: dict[str, Any]) -> tuple[Path, list[str]]:
    """The map as a build left it: the pinned worklist and one verdicts file beside it, and the
    record the build wrote into the map. Returns the map path and the pinned claims."""
    m = load_model(json.dumps(doc))
    items = l2_worklist_model(m)
    verify = root / ".coyomap" / "verify"
    verify.mkdir(parents=True)
    (verify / "worklist.json").write_text(json.dumps(worklist_payload([], items), indent=1),
                                          encoding="utf-8")
    rows = [make_verdict(it.claim, "svc/a.py:8" if it.claim == rule_claim("svc/a.py:19", "A second guard holds.", "guards twice")
                         else it.anchor or "svc/b.py:1") for it in items]
    (verify / "verdicts-build.json").write_text(json.dumps({"grounding": rows}, indent=1),
                                                encoding="utf-8")
    claims = [it.claim for it in items]
    record, errs = build_record(claims, rows, "nine claims, one skeptic", live_claims=claims)
    assert not errs, errs
    doc["grounding"] = record
    map_path = root / ".coyomap" / "project-map.json"
    map_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return map_path, claims


def make_log(pin: str, head: str) -> dict[str, Any]:
    """One reworded description, one new rule, one waiver on the box the code touched."""
    return {"format": "coyomap-changes", "version": 1, "from_commit": pin, "to_commit": head,
            "date": "2026-09-19",
            "entries": [
                {"id": "e1", "headline": "Gamma mail goes out twice", "elements": ["C3"],
                 "sentence": "Every gamma mail is sent twice.",
                 "edits": [{"id": "C3", "key": "purpose", "was": "Sends gamma mail.",
                            "now": "Sends gamma mail, twice."}],
                 "evidence": ["svc/b.py"], "confidence": "verified"},
                {"id": "e2", "headline": "The beta list is bounded", "elements": ["BR2"],
                 "sentence": "The beta list refuses an eleventh item.",
                 "added": [{"kind": "rules", "row": {
                     "id": "BR2", "name": "Beta bound", "block": "BLK1",
                     "statement": "The beta list holds at most ten items.",
                     "sites": [{"where": "svc/b.py:4", "why": "refuses the eleventh"}]}}],
                 "evidence": ["svc/b.py"], "confidence": "verified"}],
            "waived": [{"id": "C1", "why": "the alpha line was reworded, same meaning"}],
            "notes": "component level throughout"}


def make_update(td: str) -> tuple[ch.Inputs, Path, str, str]:
    """Steps 0–2 of an update, as the method runs them: the before copy, the impact file read off
    the map at its pin, the links re-anchored on disk. Returns the inputs `challenge` takes."""
    root, pin, head = make_repo(td)
    doc = make_map_doc(pin)
    map_path, _claims = make_build(root, doc)
    changes = root / ".coyomap" / "changes"
    changes.mkdir()
    update = f"{pin}-{head}"
    before = changes / f"{update}.before.json"
    before.write_text(map_path.read_text(encoding="utf-8"), encoding="utf-8")
    model = load_model(map_path.read_text(encoding="utf-8"))
    core = compute_impact(root, model, load_map_extents(map_path), "", head)
    impact = build_impact_result(model, core, RippleOptions(), None, load_map_extents(map_path))
    touched = changes / f"{update}.impact.json"
    touched.write_text(json.dumps(impact), encoding="utf-8")
    m = load_model(map_path.read_text(encoding="utf-8"))
    reanchor(m, root, head)
    current = json.loads(to_canonical_json(m))
    current["grounding"] = doc["grounding"]           # the canonical dump drops nothing the map holds
    map_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    log_path = changes / f"{update}.json"
    log_path.write_text(json.dumps(make_log(pin, head), indent=2), encoding="utf-8")
    inputs = ch.Inputs(log_path, load_log(log_path.read_text(encoding="utf-8")), map_path, current,
                       before.read_text(encoding="utf-8"), json.loads(before.read_text(encoding="utf-8")),
                       impact, root, root / ".coyomap" / "verify")
    return inputs, root, pin, head


def make_wave(inputs: ch.Inputs, refute: str | None = None, skip_batch: str | None = None) -> None:
    """The skeptics' answer: one verdicts file per batch `challenge` wrote and nobody has answered
    yet, confirming everything but `refute`; `skip_batch` is a batch nobody answers."""
    for claims_file in sorted(inputs.verify.glob(f"claims-{inputs.log.from_commit}-*.json")):
        batch = claims_file.stem[len("claims-"):]
        if skip_batch and batch.endswith(skip_batch):
            continue
        if (inputs.verify / f"verdicts-{batch}.json").exists():
            continue                    # an earlier wave answered it; its votes stand
        payload = json.loads(claims_file.read_text(encoding="utf-8"))
        rows = [make_verdict(c["claim"], c.get("anchor") or "svc/b.py:1",
                             grounded=(c["claim"] != refute), skeptic=batch)
                for c in payload["claims"]]
        (inputs.verify / f"verdicts-{batch}.json").write_text(
            json.dumps({"grounding": rows}, indent=1), encoding="utf-8")


def claims_by_reason(scope: ch.Scope) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {r: set() for r in ch.REASONS}
    for s in scope.in_scope:
        out[s.reason].add(s.item.claim)
    return out


def rule_claim(where: str, statement: str = "A guard holds.", why: str = "guards") -> str:
    return f"Rule '{statement}' is enforced at {where} — {why}"


# --- the scope ----------------------------------------------------------------------------------

def test_every_statement_lands_in_exactly_one_bucket_for_the_right_reason():
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        applied, _ = apply(inputs.log, inputs.map_doc)
        scope = ch.scope_update(inputs.log, inputs.before_text, applied, inputs.impact,
                                inputs.verify, inputs.repo)
        by = claims_by_reason(scope)
        # New or rewritten words: the reworded description and the new rule's site.
        assert by["changed"] == {
            "Component C3 (Gamma) is described as: Sends gamma mail, twice.",
            rule_claim("svc/b.py:4", "The beta list holds at most ten items.", "refuses the eleventh")}
        # Same words, changed code: C1's arrow sits on the rewritten line (a gate hit), and C3 is
        # the box an entry names — every statement with C3 at either end goes too.
        touched = by["touched"]
        cadence = next(c for c in touched if "nightly sweep" in c)
        assert touched - {cadence} == {"Component C1 (Alpha) is described as: Reads the alpha file.",
                                       "C1 calls C2", "C3 uses D1", "C2 calls C3"}
        # The way in's own line was rewritten: its schedule statement is touched, through EP1.
        assert scope.touched["EP1"] == "the code touched it"
        # Same words, a neighbour changed: C2 is where C1's rewritten arrow lands.
        assert by["rippled"] == {"Component C2 (Beta) is described as: Keeps the beta list."}
        # The two rule sites only shifted two lines: re-keyed and carried, never re-voted.
        assert scope.renames == {rule_claim("svc/a.py:20"): rule_claim("svc/a.py:22"),
                                 rule_claim("svc/a.py:19", "A second guard holds.", "guards twice"):
                                 rule_claim("svc/a.py:21", "A second guard holds.", "guards twice")}
        assert set(scope.carried) == set(scope.renames.values())
        assert scope.unvoted == []
        assert scope.superseded == ["Component C3 (Gamma) is described as: Sends gamma mail."]
        assert len(scope.live) == 10 == len(scope.in_scope) + len(scope.carried)
        assert scope.touched["C1"] == "the code touched it"
        assert scope.touched["C3"] == "entry e1 names it"
        assert scope.rippled["C2"].startswith("edge:C1>calls>C2")


def test_challenge_writes_the_applied_copy_the_batches_and_the_scope_file():
    with tempfile.TemporaryDirectory() as td:
        inputs, root, pin, head = make_update(td)
        scope, batches, applied_path, prefix = ch.run_challenge(inputs, cap=40, floor=0)
        assert prefix == f"{pin}-{head}-"
        assert applied_path.name == f"{pin}-{head}.applied.json"
        applied = json.loads(applied_path.read_text(encoding="utf-8"))
        assert applied["commit"] == head and any(r["id"] == "BR2" for r in applied["rules"])
        names = {name for name, _n in batches}
        assert names == {f"claims-{pin}-{head}-{t}.json"
                         for t in ("rule", "dep-usage", "cadence", "description", "backbone")}
        assert sum(n for _name, n in batches) == 8
        # The build's own batch files and verdicts are untouched: they are the map's warrant.
        assert (inputs.verify / "verdicts-build.json").is_file()
        scope_doc = json.loads((root / ".coyomap" / "changes" / f"{pin}-{head}.scope.json").read_text())
        assert scope_doc["counts"] == {"live": 10, "in_scope": 8, "changed": 2, "touched": 5,
                                       "rippled": 1, "carried": 2, "unvoted": 0, "superseded": 1,
                                       "shifted": 2}
        # The map on disk has not moved: the skeptics read the copy, and a refutation amends the log.
        on_disk = json.loads(inputs.map_path.read_text(encoding="utf-8"))
        assert on_disk["commit"] == pin and not any(r["id"] == "BR2" for r in on_disk["rules"])
        assert scope.update == f"{pin}-{head}"


# --- the fold -----------------------------------------------------------------------------------

def make_grounded(td: str, note: str = "one wave, five skeptics") -> tuple[ch.Inputs, ch.Fold, str, str]:
    """Challenge, the wave, apply, ground — the whole step, everything confirmed."""
    inputs, _root, pin, head = make_update(td)
    ch.run_challenge(inputs, cap=40, floor=0)
    make_wave(inputs)
    applied, _ = apply(inputs.log, inputs.map_doc, "2026-09-19")
    inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
    inputs.map_doc = applied
    fold = ch.run_ground(inputs, note, dry_run=False)
    assert not fold.errors, fold.errors
    return inputs, fold, pin, head


def test_ground_carries_rekeys_and_retires_and_the_record_describes_the_new_pin():
    with tempfile.TemporaryDirectory() as td:
        inputs, fold, pin, head = make_grounded(td)
        verify = inputs.verify
        # The old pin is kept under the from-commit's name; the new pin is the live surface.
        old = json.loads((verify / f"worklist-{pin[:7]}.json").read_text(encoding="utf-8"))
        assert len(old["worklist"]) == 9 and "pinned_by" not in old
        new = json.loads((verify / "worklist.json").read_text(encoding="utf-8"))
        assert new["pinned_by"] == f"{pin}-{head}" and len(new["worklist"]) == 10
        assert {i["claim"] for i in new["worklist"]} == {it.claim for it in fold.scope.live}
        # The build's file keeps only the carried rows, re-keyed across the shift. One citation
        # moved with the code; the other cited the line the diff rewrote, so it is cut to the file.
        kept = json.loads((verify / "verdicts-build.json").read_text(encoding="utf-8"))["grounding"]
        by_claim = {r["claim"]: r for r in kept}
        assert set(by_claim) == set(fold.scope.renames.values())
        one = by_claim[rule_claim("svc/a.py:22")]
        assert one["claim_was"] == rule_claim("svc/a.py:20") and one["rekeyed"] == f"{pin}-{head}"
        assert one["evidence"] == "svc/a.py:22" and one["evidence_was"] == "svc/a.py:20"
        assert one["evidence_at"] == head
        two = by_claim[rule_claim("svc/a.py:21", "A second guard holds.", "guards twice")]
        assert two["evidence"] == "svc/a.py" and two["evidence_was"] == "svc/a.py:8"
        assert two["evidence_stale"] == f"{pin}-{head}"
        assert (fold.rekeyed, fold.evidence_moved, fold.evidence_stale) == (2, 1, 1)
        # Every other build row is retired, with the file it came from, in a payload no verdict
        # reader recognises as votes.
        retired = json.loads((verify / f"retired-{pin}-{head}.json").read_text(encoding="utf-8"))
        assert retired["format"] == ch.RETIRED_FORMAT and len(retired["rows"]) == 7
        assert {r["file"] for r in retired["rows"]} == {"verdicts-build.json"}
        assert "grounding" not in retired
        # The record is about the map as it now is: every live statement has a verdict, none is
        # superseded or added, and the ledger tells how it got there.
        g = json.loads(inputs.map_path.read_text(encoding="utf-8"))["grounding"]
        assert (g["claims_total"], g["claims_challenged"], g["claims_confirmed"], g["claims_refuted"]) == (10, 10, 10, 0)
        assert (g["claims_superseded"], g["claims_added_since"], g["claims_live_challenged"]) == (0, 0, 10)
        assert g["note"] == "one wave, five skeptics"
        build_row, wave_row = g["history"]
        assert build_row["kind"] == "build" and build_row["at"] == pin and build_row["challenged"] == 9
        assert build_row["note"] == "nine claims, one skeptic" and build_row["skeptics"] == 1
        assert wave_row["kind"] == "update" and wave_row["at"] == f"{pin}-{head}"
        assert wave_row["date"] == "2026-09-19"
        assert (wave_row["challenged"], wave_row["confirmed"], wave_row["refuted"]) == (8, 8, 0)
        assert (wave_row["carried"], wave_row["retired"]) == (2, 7)
        assert (wave_row["changed"], wave_row["touched"], wave_row["rippled"]) == (2, 5, 1)
        assert wave_row["skeptics"] == 5
        # The log says the same, in its own block.
        log = load_log(inputs.log_path.read_text(encoding="utf-8"))
        assert log.challenge is not None
        assert log.challenge["challenged"] == 8 and log.challenge["carried"] == 2
        assert log.challenge["superseded"] == 1 and log.challenge["shifted"] == 2
        assert len(log.challenge["batches"]) == 5
        # The map loads with the ledger in it, and the refutation gate is clean over the folder.
        load_model(inputs.map_path.read_text(encoding="utf-8"))
        files = [str(p) for p in ch.verdict_files(verify)]
        assert grounding_main(["refutations", "--map", str(inputs.map_path), "--verdicts", *files]) == 0


def test_a_refutation_the_wave_cast_survives_the_gate_until_the_map_is_fixed():
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        ch.run_challenge(inputs, cap=40, floor=0)
        make_wave(inputs, refute="C2 calls C3")
        applied, _ = apply(inputs.log, inputs.map_doc, "2026-09-19")
        inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
        inputs.map_doc = applied
        fold = ch.run_ground(inputs, "one refuted, six confirmed", dry_run=False)
        assert not fold.errors, fold.errors
        g = json.loads(inputs.map_path.read_text(encoding="utf-8"))["grounding"]
        assert g["claims_refuted"] == 1 and g["history"][-1]["refuted"] == 1
        files = [str(p) for p in ch.verdict_files(inputs.verify)]
        assert grounding_main(["refutations", "--map", str(inputs.map_path), "--verdicts", *files]) == 1


def test_ground_refuses_when_a_batch_has_no_verdicts_and_writes_nothing():
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, pin, head = make_update(td)
        ch.run_challenge(inputs, cap=40, floor=0)
        make_wave(inputs, skip_batch="backbone")
        applied, _ = apply(inputs.log, inputs.map_doc, "2026-09-19")
        inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
        inputs.map_doc = applied
        before = {p.name: p.read_text(encoding="utf-8") for p in inputs.verify.iterdir()}
        fold = ch.run_ground(inputs, "a note", dry_run=False)
        assert any("has no verdicts file" in e for e in fold.errors), fold.errors
        assert any("have no verdict from this wave" in e for e in fold.errors), fold.errors
        after = {p.name: p.read_text(encoding="utf-8") for p in inputs.verify.iterdir()}
        assert after == before, "a refusal leaves the warrant exactly as it was"
        assert "history" not in json.loads(inputs.map_path.read_text(encoding="utf-8"))["grounding"]
        assert load_log(inputs.log_path.read_text(encoding="utf-8")).challenge is None


def test_a_dry_run_reports_the_wave_and_writes_nothing():
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        ch.run_challenge(inputs, cap=40, floor=0)
        make_wave(inputs)
        applied, _ = apply(inputs.log, inputs.map_doc, "2026-09-19")
        inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
        inputs.map_doc = applied
        before = {p.name: p.read_text(encoding="utf-8") for p in inputs.verify.iterdir()}
        fold = ch.run_ground(inputs, "", dry_run=True)
        assert not fold.errors, fold.errors
        assert fold.record["claims_challenged"] == 10 and len(fold.record["history"]) == 2
        assert {p.name: p.read_text(encoding="utf-8") for p in inputs.verify.iterdir()} == before
        assert "history" not in json.loads(inputs.map_path.read_text(encoding="utf-8"))["grounding"]


def test_a_note_that_contradicts_the_wave_is_refused():
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        ch.run_challenge(inputs, cap=40, floor=0)
        make_wave(inputs)
        applied, _ = apply(inputs.log, inputs.map_doc, "2026-09-19")
        inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
        inputs.map_doc = applied
        fold = ch.run_ground(inputs, "Nine skeptics re-read the change.", dry_run=False)
        assert any("contradicts this wave" in e and "5 distinct skeptic" in e for e in fold.errors), fold.errors
        # A dry run given a note checks it too, so a draft is refused where it is cheap.
        fold = ch.run_ground(inputs, "Nine skeptics re-read the change.", dry_run=True)
        assert any("contradicts this wave" in e for e in fold.errors), fold.errors


# --- the command line -----------------------------------------------------------------------------

def test_the_verbs_run_from_the_command_line(capsys):
    with tempfile.TemporaryDirectory() as td:
        inputs, root, pin, head = make_update(td)
        args = [str(inputs.log_path), "--map", str(inputs.map_path),
                "--before", str(root / ".coyomap" / "changes" / f"{pin}-{head}.before.json"),
                "--touched", str(root / ".coyomap" / "changes" / f"{pin}-{head}.impact.json"),
                "--repo", str(root)]
        assert ch.main("challenge", [*args, "--floor", "0"]) == 0
        out = capsys.readouterr().out
        assert out.startswith(f"challenge {pin}-{head} — 8 of 10 statement(s) to re-argue: 2 changed, "
                              "5 on a touched box, 1 on a box the change reached; 2 carried"), out
        assert f"--prefix {pin}-{head}- " in out
        make_wave(inputs)
        applied, _ = apply(inputs.log, inputs.map_doc, "2026-09-19")
        inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
        assert ch.main("ground", [*args, "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "dry run — nothing written" in out and "WAVE FACTS" in out
        note = root / "note.txt"
        note.write_text("Five fresh-context skeptics re-read the eight statements the change reached, "
                        "and the map gained 2 new statements.\n")
        assert ch.main("ground", [*args, "--note-file", str(note)]) == 0
        out = capsys.readouterr().out
        assert "8 statement(s) re-argued: 8 confirmed" in out and "next: coyomap grounding refutations" in out
        assert "WAVE FACTS" in out and "superseded 1, of which 1 had been CONFIRMED" in out, out
        assert "MAP-WIDE, after this update: 10 of 10" in out, out
        assert ch.main("ground", [*args]) == 2, "a real write needs the note"


# --- the two gates that see an update which skipped its wave ------------------------------------

def test_the_written_map_is_refused_by_check_until_the_record_describes_it():
    """`changes check --old --new` runs on what `apply` wrote. A record still pinned to the build
    describes statements the update rewrote, so the gate refuses until `ground` re-measures it;
    `validate` says the same as advice, for a map edited after the fact."""
    from coyomap.changelog import check
    from coyomap.validate_model import validate_model
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        ch.run_challenge(inputs, cap=40, floor=0)
        make_wave(inputs)
        applied, _ = apply(inputs.log, inputs.map_doc, "2026-09-19")
        inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
        inputs.map_doc = applied
        stale = check(inputs.log, inputs.before_doc, applied, inputs.impact, new_path=inputs.map_path)
        assert any("does not describe this map" in e for e in stale.errors), stale.errors
        _problems, warnings = validate_model(load_model(json.dumps(applied)), inputs.map_path,
                                             disclose_records=False)
        assert any("does not describe this map" in w for w in warnings), warnings
        fold = ch.run_ground(inputs, "one wave, five skeptics", dry_run=False)
        assert not fold.errors, fold.errors
        grounded = json.loads(inputs.map_path.read_text(encoding="utf-8"))
        fresh = check(inputs.log, inputs.before_doc, grounded, inputs.impact, new_path=inputs.map_path)
        assert not [e for e in fresh.errors if "describe" in e], fresh.errors
        _problems, warnings = validate_model(load_model(json.dumps(grounded)), inputs.map_path,
                                             disclose_records=False)
        assert not [w for w in warnings if "does not describe this map" in w], warnings


def test_a_theme_the_build_never_voted_stays_unvoted_in_the_update():
    """Parity with the build, in both directions: the mcpolis build pinned 949 step phrases and
    voted none of them. An update that re-argued every phrase on a touched box would buy a theme
    the build had decided not to — measured, 451 of 551 statements and eleven skeptics."""
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        # The build's file loses every backbone vote: that theme was never read.
        vf = inputs.verify / "verdicts-build.json"
        rows = json.loads(vf.read_text(encoding="utf-8"))["grounding"]
        kept = [r for r in rows if " calls " not in r["claim"]]
        vf.write_text(json.dumps({"grounding": kept}, indent=1), encoding="utf-8")
        applied, _ = apply(inputs.log, inputs.map_doc)
        scope = ch.scope_update(inputs.log, inputs.before_text, applied, inputs.impact,
                                inputs.verify, inputs.repo)
        by = claims_by_reason(scope)
        assert "C1 calls C2" not in by["touched"] and "C2 calls C3" not in by["touched"]
        assert {"C1 calls C2", "C2 calls C3"} <= set(scope.unvoted)
        assert any("2 backbone statement(s) stay unvoted" in n for n in scope.notes), scope.notes
        # Every other theme keeps its verdicts, so the rest of the scope is unchanged.
        assert by["changed"] == {
            "Component C3 (Gamma) is described as: Sends gamma mail, twice.",
            rule_claim("svc/b.py:4", "The beta list holds at most ten items.", "refuses the eleventh")}
        assert "C3 uses D1" in by["touched"]


def test_a_map_with_no_warrant_gets_no_wave_and_is_told_why():
    """No pinned worklist with verdicts beside it: nothing to carry, no tier to keep parity with.
    A wave over the whole map would be a build's Phase-4 pass billed to an update."""
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        for p in inputs.verify.iterdir():
            p.unlink()
        applied, _ = apply(inputs.log, inputs.map_doc)
        scope = ch.scope_update(inputs.log, inputs.before_text, applied, inputs.impact,
                                inputs.verify, inputs.repo)
        assert scope.in_scope == [] and len(scope.unvoted) == 10 and scope.carried == []
        assert any("carries no warrant" in n for n in scope.notes), scope.notes
        _scope, batches, _applied, _prefix = ch.run_challenge(inputs, cap=40, floor=0)
        assert batches == [] and not list(inputs.verify.glob("claims-*.json"))


def test_a_fix_after_a_refutation_gets_one_more_wave_over_the_re_minted_statements_only():
    """The loop the method describes: a skeptic refutes, the log is amended, `challenge` runs
    again and batches only what no wave of this update has voted; `ground` then folds both waves,
    retiring the refuted row with the statement the fix removed."""
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, pin, head = make_update(td)
        ch.run_challenge(inputs, cap=40, floor=0)
        refuted = "Component C2 (Beta) is described as: Keeps the beta list."
        make_wave(inputs, refute=refuted)
        # The fix: one more entry rewording C2, which retires the refuted statement.
        log_doc = json.loads(inputs.log_path.read_text(encoding="utf-8"))
        log_doc["entries"].append(
            {"id": "e3", "headline": "Beta keeps a bounded list", "elements": ["C2"],
             "sentence": "The beta list is bounded, and the description now says so.",
             "edits": [{"id": "C2", "key": "purpose", "was": "Keeps the beta list.",
                        "now": "Keeps the bounded beta list."}],
             "evidence": ["svc/b.py"], "confidence": "verified"})
        inputs.log_path.write_text(json.dumps(log_doc, indent=2), encoding="utf-8")
        inputs.log = load_log(inputs.log_path.read_text(encoding="utf-8"))
        scope, batches, _applied, prefix = ch.run_challenge(inputs, cap=40, floor=0)
        assert prefix == f"{pin}-{head}-w2-"
        assert [name for name, _n in batches] == [f"claims-{pin}-{head}-w2-description.json"]
        assert batches[0][1] == 1, "only the statement the fix re-minted goes out"
        assert any("already have a verdict from this update's earlier wave" in n for n in scope.notes)
        # The first wave's answered batches are untouched.
        assert (inputs.verify / f"verdicts-{pin}-{head}-backbone.json").is_file()
        make_wave(inputs)          # answers the w2 batch (the others already have their files)
        applied, _ = apply(inputs.log, inputs.map_doc, "2026-09-19")
        inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
        inputs.map_doc = applied
        fold = ch.run_ground(inputs, "two waves, six skeptics", dry_run=False)
        assert not fold.errors, fold.errors
        g = json.loads(inputs.map_path.read_text(encoding="utf-8"))["grounding"]
        assert g["claims_refuted"] == 0 and g["claims_challenged"] == g["claims_total"] == 10
        # The ledger row counts what the wave caught, including the statement the fix then removed.
        wave = g["history"][-1]
        assert wave["challenged"] == 9 and wave["refuted"] == 1 and wave["skeptics"] == 6
        assert wave["retired"] == 7
        retired = json.loads((inputs.verify / f"retired-{pin}-{head}.json").read_text(encoding="utf-8"))
        assert any(r["claim"] == refuted and r["file"] == "this update's wave" for r in retired["rows"])
        files = [str(p) for p in ch.verdict_files(inputs.verify)]
        assert grounding_main(["refutations", "--map", str(inputs.map_path), "--verdicts", *files]) == 0


# --- the reviewer's findings, each pinned ---------------------------------------------------------

def _verify_snapshot(verify: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(verify.iterdir())}


def test_ground_run_twice_changes_nothing_the_second_time():
    """A re-run by mistake: the same scope against the list the update replaced, no citation moved
    twice, one ledger row — the second run is a no-op on every file."""
    with tempfile.TemporaryDirectory() as td:
        inputs, fold, _pin, _head = make_grounded(td)
        before = _verify_snapshot(inputs.verify)
        map_before = inputs.map_path.read_text(encoding="utf-8")
        log_before = inputs.log_path.read_text(encoding="utf-8")
        inputs.map_doc = json.loads(map_before)
        again = ch.run_ground(inputs, "one wave, five skeptics", dry_run=False)
        assert not again.errors, again.errors
        assert _verify_snapshot(inputs.verify) == before
        assert inputs.map_path.read_text(encoding="utf-8") == map_before
        assert inputs.log_path.read_text(encoding="utf-8") == log_before
        assert len(json.loads(map_before)["grounding"]["history"]) == 2


def test_a_retry_after_a_crash_finishes_the_fold_without_moving_a_citation_twice():
    """The crash state the reviewer forced: the retired file written and the prior files rewritten,
    the pin, the map and the log not yet. The retry must complete and leave the same result."""
    with tempfile.TemporaryDirectory() as td:
        inputs, fold, pin, _head = make_grounded(td)
        done = _verify_snapshot(inputs.verify)
        map_done = inputs.map_path.read_text(encoding="utf-8")
        # Back to the crash state: the old pin back in place, the map and the log as before ground.
        shutil.copy(inputs.verify / f"worklist-{pin[:7]}.json", inputs.verify / "worklist.json")
        doc = json.loads(map_done)
        doc["grounding"] = inputs.before_doc["grounding"]
        inputs.map_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        inputs.map_doc = doc
        log_doc = json.loads(inputs.log_path.read_text(encoding="utf-8"))
        log_doc.pop("challenge")
        inputs.log_path.write_text(json.dumps(log_doc, indent=2), encoding="utf-8")
        inputs.log = load_log(inputs.log_path.read_text(encoding="utf-8"))
        retry = ch.run_ground(inputs, "one wave, five skeptics", dry_run=False)
        assert not retry.errors, retry.errors
        assert (retry.rekeyed, retry.evidence_moved, retry.evidence_stale) == (0, 0, 0), \
            "the prior files were already carried: nothing to re-key or move"
        assert _verify_snapshot(inputs.verify) == done
        assert json.loads(inputs.map_path.read_text(encoding="utf-8")) == json.loads(map_done)


def test_a_dead_citation_is_not_read_as_drift_by_the_anchor_check():
    """The reviewer's end-to-end case: a carried confirmed row cited the line the diff rewrote;
    left as a line, `anchor-drift` reported the map's correct link as drifted and `fix
    apply-drift` moved it back. Cut to the file, the row carries no line to read."""
    from coyomap.anchor_drift import drift_findings
    with tempfile.TemporaryDirectory() as td:
        inputs, _fold, _pin, _head = make_grounded(td)
        rows: list[dict] = []
        for f in ch.verdict_files(inputs.verify):
            rows.extend(ch.read_rows(f)[1])
        m = load_model(inputs.map_path.read_text(encoding="utf-8"))
        found = drift_findings(l2_worklist_model(m), rows, tolerance=2)
        assert not [w.claim for w, _d in found if "second guard" in w.claim], found
        site = next(r for r in m.rules if r.id == "BR3").sites[0].where
        assert site == "svc/a.py:21", "the map's own link stays where the re-anchor step put it"


def test_an_unanswered_batch_is_replaced_by_the_next_challenge_run_and_never_blocks_ground():
    """Wave 1 lost a skeptic; a refutation elsewhere amended the log; `challenge` re-runs. The lost
    batch's statements go out again under the new prefix, and `ground` sees every statement voted."""
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, pin, head = make_update(td)
        ch.run_challenge(inputs, cap=40, floor=0)
        make_wave(inputs, refute="Component C2 (Beta) is described as: Keeps the beta list.",
                  skip_batch="backbone")
        log_doc = json.loads(inputs.log_path.read_text(encoding="utf-8"))
        log_doc["entries"].append(
            {"id": "e3", "headline": "Beta keeps a bounded list", "elements": ["C2"],
             "sentence": "The beta list is bounded, and the description now says so.",
             "edits": [{"id": "C2", "key": "purpose", "was": "Keeps the beta list.",
                        "now": "Keeps the bounded beta list."}],
             "evidence": ["svc/b.py"], "confidence": "verified"})
        inputs.log_path.write_text(json.dumps(log_doc, indent=2), encoding="utf-8")
        inputs.log = load_log(inputs.log_path.read_text(encoding="utf-8"))
        _scope, batches, _applied, prefix = ch.run_challenge(inputs, cap=40, floor=0)
        assert not (inputs.verify / f"claims-{pin}-{head}-backbone.json").exists(), "replaced"
        assert {name for name, _n in batches} == {f"claims-{prefix}backbone.json",
                                                  f"claims-{prefix}description.json"}
        make_wave(inputs)
        applied, _ = apply(inputs.log, inputs.map_doc, "2026-09-19")
        inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
        inputs.map_doc = applied
        fold = ch.run_ground(inputs, "two waves, six skeptics", dry_run=False)
        assert not fold.errors, fold.errors


def test_missing_warrant_files_are_refused_and_a_map_with_no_record_is_left_alone():
    with tempfile.TemporaryDirectory() as td:
        inputs, _root, _pin, _head = make_update(td)
        for p in inputs.verify.iterdir():
            p.unlink()
        applied, _ = apply(inputs.log, inputs.map_doc, "2026-09-19")
        inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
        inputs.map_doc = applied
        # The record says 9 challenged and nothing beside the map can show a vote: refuse.
        fold = ch.run_ground(inputs, "a note", dry_run=False)
        assert any("warrant files are missing" in e for e in fold.errors), fold.errors
        assert not list(inputs.verify.iterdir()) and "history" not in \
            json.loads(inputs.map_path.read_text(encoding="utf-8"))["grounding"]
        # No record at all: nothing to ground, nothing written, no error.
        applied.pop("grounding")
        inputs.map_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
        inputs.map_doc = applied
        fold = ch.run_ground(inputs, "a note", dry_run=False)
        assert not fold.errors and "carries no warrant" in fold.skipped
        assert not list(inputs.verify.iterdir())
        assert "grounding" not in json.loads(inputs.map_path.read_text(encoding="utf-8"))
        assert load_log(inputs.log_path.read_text(encoding="utf-8")).challenge is None
