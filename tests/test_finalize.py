#!/usr/bin/env python3
"""`coyomap finalize` — the pre-commit read.

The design point these pin: it is a CONVENIENCE WRAPPER, not an enforcement point. Nothing makes a
build run it, and `finalize | grep …` returns grep's status, so the value is (a) running `compare`
during the build at all — the check that caught a 103→19 security-table collapse every other gate
passed, and that nobody ran — and (b) writing a durable report a `> /dev/null` cannot erase.

Run either way: `python3 tests/test_finalize.py` or `pytest tests/test_finalize.py`.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from coyomap import buildstate, finalize, findings, grounding
from coyomap.audit_model import role_inclusion_claim, rule_site_claim
from coyomap.model import FORMAT

#: A genuinely minimal VALID map — no entities, because a domain card carries its own blocking
#: requirements (meaning, fields, a real named type in its source) that have nothing to do with what
#: these tests are about. Two components and one C→C edge is the smallest thing that validates.
MAP = {
    "format": FORMAT,   # the real constant, so the fixture cannot drift from the loader
    "title": "T", "goal": "G",
    "roles": [{"id": "R1", "name": "A", "kind": "human", "wants": "x", "drives": "UC1"}],
    "use_cases": [{"id": "UC1", "name": "Do it", "actors": ["R1"]}],
    "happy_path": [{"id": "HP1", "uc": "UC1"}],
    "components": [{"id": "C1", "name": "Front", "purpose": "takes the ask"},
                   {"id": "C2", "name": "Back", "purpose": "answers it"}],
    "edges": [{"src": "C1", "verb": "calls", "dst": "C2", "why": "to answer", "where": "src/a.py:2"}],
    "flows": [{"uc": "UC1", "title": "Do it",
               "steps": [{"n": 1, "src": "R1", "dst": "C1", "phrase": "asks"},
                         {"n": 2, "src": "C1", "dst": "C2", "phrase": "forwards", "where": "src/a.py:2"},
                         {"n": 3, "src": "C1", "dst": "R1", "phrase": "answers"}]}],
}


def make_git_repo() -> tuple[Path, Path]:
    """A repo with real git history. `finalize` reads no git state now (it compares nothing against a
    previous map — that is the developer-only retro's job), so this exists only to prove the command
    stays clean in a repo where a previous version of it used to materialise a baseline copy."""
    root, p = make_repo()
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True)
    subprocess.run(["git", "add", "-f", str(p.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "map"],
                   cwd=root, check=True)
    return root, p


def make_repo(broken: bool = False, components: int = 0) -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp())
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("def front():\n    return back()\n", encoding="utf-8")
    (root / "src" / "b.py").write_text("def back():\n    return 1\n", encoding="utf-8")
    (root / ".coyomap").mkdir()
    doc = json.loads(json.dumps(MAP))
    if components:
        # An edgeless map of N components: the isolated-component advisory lists every id, so a
        # truncation (or its absence) is observable.
        doc["components"] = [{"id": f"C{i}", "name": f"C{i}", "purpose": "p"} for i in range(1, components + 1)]
        doc["edges"] = []
        doc["flows"] = [{"uc": "UC1", "title": "Do it",
                         "steps": [{"n": 1, "src": "R1", "dst": "C1", "phrase": "asks"},
                                   {"n": 2, "src": "C1", "dst": "C2", "phrase": "f",
                                    "where": "src/a.py:2"},
                                   {"n": 3, "src": "C1", "dst": "R1", "phrase": "answers"}]}]
    if broken:
        doc["edges"][0]["dst"] = "C999"        # a dangling reference — a BLOCKING validate problem
    p = root / ".coyomap" / "project-map.json"
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return root, p


def test_a_clean_map_exits_zero_and_writes_both_reports():
    root, p = make_repo()
    code = finalize.main([str(p), "--repo", str(root)])
    assert code == 0
    assert (root / ".coyomap" / "finalize-report.json").is_file()
    assert (root / ".coyomap" / "finalize-report.md").is_file()


def test_a_blocking_problem_exits_one_and_is_recorded_as_blocking():
    """Exit 1 means exactly what validate/audit already block on — nothing more."""
    root, p = make_repo(broken=True)
    code = finalize.main([str(p), "--repo", str(root)])
    assert code == 1
    report = json.loads((root / ".coyomap" / "finalize-report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "BLOCKED"
    assert report["blocking_total"] >= 1
    assert any("C999" in b for leg in report["legs"] for b in leg["blocking"])


def test_a_leg_that_did_not_run_can_never_produce_a_verdict_of_clean():
    """The defect this command shipped in its first cut, and the whole reason `Leg.status` exists.

    A leg that did not run contributed 0 blocking and 0 advisory, so a broken map with a typo'd
    `--repo` reported **Verdict: CLEAN**, exit 0 — a report testifying that a gate passed when the gate
    never ran. Worse than no report at all."""
    root, p = make_repo(broken=True)                 # a dangling reference: validate exits 1 on this
    code = finalize.main([str(p), "--repo", "/nonexistent-dir-for-this-test"])
    r = json.loads((root / ".coyomap" / "finalize-report.json").read_text(encoding="utf-8"))
    assert r["verdict"] == "INCOMPLETE", r["verdict"]
    assert code != 0, "a run that does not know whether the map is clean must not exit 0"
    assert any(l["status"] == "failed" for l in r["legs"])
    md = (root / ".coyomap" / "finalize-report.md").read_text(encoding="utf-8")
    verdict_line = next(ln for ln in md.splitlines() if ln.startswith("**Verdict:"))
    assert "CLEAN" not in verdict_line, verdict_line
    assert "their silence is not a pass" in md


def test_the_report_is_byte_identical_across_identical_runs():
    """Non-determinism in a pre-commit report is a defect: a build cannot tell a real change from
    noise, and a diff of the committed report becomes unreadable."""
    root, p = make_repo()
    finalize.main([str(p), "--repo", str(root)])
    first = (root / ".coyomap" / "finalize-report.json").read_text(encoding="utf-8")
    finalize.main([str(p), "--repo", str(root)])
    assert (root / ".coyomap" / "finalize-report.json").read_text(encoding="utf-8") == first


def test_it_leaves_no_scratch_files_beside_the_map():
    """An earlier version materialised a ~800 KB copy of the previous map next to the real one and
    deleted it only on the success path. Nothing is materialised now; this holds that line."""
    root, p = make_git_repo()
    finalize.main([str(p), "--repo", str(root)])
    strays = [f.name for f in (root / ".coyomap").iterdir()
              if f.name.startswith(f".{finalize.REPORT_STEM}")]
    assert strays == [], strays


def test_a_crash_mid_run_leaves_no_scratch_behind():
    """A malformed `--verdicts` file reaches the drift leg and raises. Nothing temporary may survive."""
    root, p = make_git_repo()
    boom = root / ".coyomap" / "not-json.json"
    boom.write_text("{{{ not json", encoding="utf-8")
    try:
        finalize.main([str(p), "--repo", str(root), "--verdicts", str(boom)])
    except Exception:
        pass
    strays = [f.name for f in (root / ".coyomap").iterdir()
              if f.name.startswith(f".{finalize.REPORT_STEM}")]
    assert strays == [], strays


def test_a_missing_map_and_a_missing_verdicts_file_fail_before_any_leg_runs():
    root, p = make_repo()
    assert finalize.main([str(root / ".coyomap" / "nope.json")]) == 1
    assert finalize.main([str(p), "--repo", str(root), "--verdicts", str(root / "nope.json")]) == 1


def test_the_report_carries_whole_lists_on_a_map_big_enough_to_truncate():
    """The previous version asserted `"more" not in … or "+" not in …` on a 2-component map — both
    disjuncts trivially true, and it passed with whole-list mode removed. This builds a map with 30
    isolated components, well past the 8-id inline limit, and asserts the ids are all present."""
    root, p = make_repo(components=30)
    finalize.main([str(p), "--repo", str(root)])
    text = (root / ".coyomap" / "finalize-report.md").read_text(encoding="utf-8")
    isolated = [ln for ln in text.splitlines() if "carry no backbone edge" in ln]
    assert isolated, "expected the isolated-component advisory on a 30-component edgeless map"
    assert "more" not in isolated[0], isolated[0]
    assert "C30" in isolated[0], "the last id must be present, not elided"


def test_the_help_says_it_is_not_an_enforcement_point():
    """If the docs ever start promising enforcement, the promise is false — the exit status is lost to
    any pipeline. Pinned so the claim cannot drift back."""
    r = subprocess.run([sys.executable, "-m", "coyomap.cli", "finalize", "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "not an enforcement point" in r.stdout
    assert "never gating" in r.stdout


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all finalize tests passed")


def test_the_report_records_the_maps_hash_so_a_stale_one_is_detectable():
    """A crash writes no report, so the PREVIOUS run's file survives — and the method tells the build to
    read the file. The hash is how a reader tells this map's result from another's."""
    import hashlib
    root, p = make_repo()
    finalize.main([str(p), "--repo", str(root)])
    r = json.loads((root / ".coyomap" / "finalize-report.json").read_text(encoding="utf-8"))
    assert r["map_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert r["map_sha256"] in (root / ".coyomap" / "finalize-report.md").read_text(encoding="utf-8")


def test_a_grounding_record_pinned_to_a_stale_worklist_is_flagged():
    """A live build shipped `418 of 418 challenged` on a map whose worklist held 415 and quoted the
    418 in its commit as fact. `validate` cannot see it — it blocks only `challenged > total`, and a
    stale pin is self-consistent."""
    from coyomap.finalize import _stale_grounding_pin
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.json"
        p.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g",
                                 "grounding": {"claims_total": 418, "claims_challenged": 418}}),
                     encoding="utf-8")
        msg = _stale_grounding_pin(p, [f"claim {i}" for i in range(415)])
        assert msg and "418" in msg and "415" in msg
        # Agreeing counts are NOT a pass without a digest: a 1-for-1 rewrite leaves the count
        # untouched, so this branch says the record cannot be checked rather than that it is fine.
        msg2 = _stale_grounding_pin(p, [f"c{i}" for i in range(418)])
        assert msg2 and "no `live_claims_digest`" in msg2, msg2


def test_a_map_with_no_grounding_record_is_not_flagged():
    from coyomap.finalize import _stale_grounding_pin
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.json"
        p.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g"}), encoding="utf-8")
        assert _stale_grounding_pin(p, [f"c{i}" for i in range(415)]) is None


# ── the commit message's two other lies ──────────────────────────────────────────────────────────

def test_the_gate_block_states_the_shape_from_the_map_it_hashes():
    """A live commit claimed "416 backbone edges … 33 flows/sub-flows" for a map holding 365 and 36.
    Both numbers had been true earlier in the build; `fix dedup-edge` then dropped 49 duplicate
    occurrences. Hand-copied shape numbers describe whatever the author last looked at."""
    root, p = make_repo(components=4)
    report = finalize.build_report(p, root, [])
    block = finalize.gate_block(report, report.map_sha256)
    doc = json.loads(p.read_text())
    assert f"{len(doc['components'])} components" in block
    assert f"{len(doc['edges'])} edges" in block


def test_the_gate_block_states_grounding_from_the_map_not_from_memory():
    """A live commit said "all 446 L2 claims challenged" beside a gate block reading
    `challenged 440 of 444`. Both were minutes apart in one build; the durable one was the
    flattering one."""
    root, p = make_repo()
    doc = json.loads(p.read_text())
    doc["grounding"] = {"claims_total": 444, "claims_challenged": 440, "claims_confirmed": 430,
                        "claims_refuted": 5, "claims_unverifiable": 5}
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    report = finalize.build_report(p, root, [])
    block = finalize.gate_block(report, report.map_sha256)
    assert "440 of 444" in block, block


def test_the_gate_block_says_so_when_the_map_carries_no_grounding_record():
    """Silence would read as "not applicable" rather than "nobody challenged anything"."""
    root, p = make_repo()
    report = finalize.build_report(p, root, [])
    assert "NO RECORD" in finalize.gate_block(report, report.map_sha256)


def test_an_unreadable_map_says_so_instead_of_omitting_the_shape():
    """A gate block that silently drops the Shape and Grounding lines sends the author back to
    hand-writing the numbers, which is the defect those lines exist to remove."""
    root, p = make_repo()
    report = finalize.build_report(p, root, [])
    p.write_text("{truncated", encoding="utf-8")          # as a concurrent write would leave it
    block = finalize.gate_block(report, report.map_sha256)
    assert "Shape: UNAVAILABLE" in block and "Grounding: UNAVAILABLE" in block


def test_a_recorded_delta_makes_the_pin_advisory_go_quiet():
    """The escape that did not exist. All three documented ways out were closed: the pinned record
    raised this advisory, re-running against a fresh worklist was REFUSED, and explaining it in
    `note` changed nothing. `grounding write --map` records the delta and a digest of the live
    claim set, and that is what the gate now reads."""
    from coyomap.finalize import _stale_grounding_pin
    from coyomap.grounding import live_claims_digest
    live = [f"claim {i}" for i in range(444)]
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.json"
        p.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g", "grounding": {
            "claims_total": 446, "claims_challenged": 446, "claims_superseded": 6,
            "claims_added_since": 4, "live_claims_digest": live_claims_digest(live)}}),
            encoding="utf-8")
        assert _stale_grounding_pin(p, live) is None


def test_the_digest_catches_a_one_for_one_rewrite_that_the_counts_cannot():
    """The reason the gate is a digest and not arithmetic. Replace k claims with k others and every
    size-based check still closes — and a reconcile that rewrites a claim IS 1-for-1 by
    construction; 4 of 6 superseded claims on the build this came from were exactly that shape."""
    from coyomap.finalize import _stale_grounding_pin
    from coyomap.grounding import live_claims_digest
    # claims_total EQUALS the live count on purpose: with 446-vs-444 the count check would fire
    # too, and the test would not distinguish the branches. Here only the digest can catch it.
    live = [f"claim {i}" for i in range(444)]
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.json"
        p.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g", "grounding": {
            "claims_total": 444, "claims_challenged": 444, "claims_superseded": 6,
            "claims_added_since": 6, "live_claims_digest": live_claims_digest(live)}}),
            encoding="utf-8")
        swapped = live[:-1] + ["a claim authored after the record was written"]
        assert len(swapped) == len(live), "the count must be unchanged, or this proves nothing"
        msg = _stale_grounding_pin(p, swapped)
        assert msg and "live_claims_digest" in msg, msg


def make_verdicts_file(tmp: str, claims: list[str]) -> Path:
    """A verdicts file whose claims are the PINNED set — which is what `grounding write`'s two
    refusals guarantee, and what makes the delta counts recomputable."""
    p = Path(tmp) / "verdicts.json"
    p.write_text(json.dumps({"grounding": [
        {"claim": c, "grounded": True, "evidence": "f.py:1"} for c in claims]}), encoding="utf-8")
    return p


def make_grounding_map(tmp: str, live: list[str], **grounding: object) -> Path:
    from coyomap.grounding import live_claims_digest
    p = Path(tmp) / "m.json"
    rec = {"claims_total": len(live), "claims_challenged": len(live),
           "live_claims_digest": live_claims_digest(live)}
    rec.update(grounding)
    p.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g", "grounding": rec}),
                 encoding="utf-8")
    return p


def test_a_fabricated_delta_count_is_caught_when_the_verdicts_are_present():
    """The digest proves the record describes THIS map. It says nothing about whether the two delta
    counts are true — a valid digest and two invented numbers coexist happily, which is a poor
    property for the fields whose only job is honesty."""
    from coyomap.finalize import _stale_grounding_pin
    with tempfile.TemporaryDirectory() as tmp:
        live = ["kept", "added-since-the-pin"]
        pinned = ["kept", "reconciled-away"]
        p = make_grounding_map(tmp, live, claims_superseded=0, claims_added_since=0)
        v = make_verdicts_file(tmp, pinned)
        assert _stale_grounding_pin(p, live) is None, "without verdicts there is nothing to check"
        msg = _stale_grounding_pin(p, live, [v])
        # Only the LOWER bound on superseded fires here. `claims_added_since: 0` sits BELOW the
        # upper bound, which a partial verdict set legitimately permits — only a count ABOVE what
        # the verdicts leave room for is provably wrong.
        assert msg and "already name 1 pinned claim(s)" in msg, msg
        over = make_grounding_map(tmp, live, claims_superseded=1, claims_added_since=9)
        msg2 = _stale_grounding_pin(over, live, [v])
        assert msg2 and "at most 1 live claim(s) can be new" in msg2, msg2


def test_honest_delta_counts_pass_the_recomputation():
    from coyomap.finalize import _stale_grounding_pin
    with tempfile.TemporaryDirectory() as tmp:
        live = ["kept", "added-since-the-pin"]
        p = make_grounding_map(tmp, live, claims_superseded=1, claims_added_since=1)
        v = make_verdicts_file(tmp, ["kept", "reconciled-away"])
        assert _stale_grounding_pin(p, live, [v]) is None


def test_no_value_of_claims_total_can_buy_silence():
    """Three escapes, one root. The first guard demanded the verdict set equal `claims_total`, so
    LOWERING the total went quiet; patching that direction left RAISING it, and a digit STRING,
    equally quiet — a more wrong record stayed safer than a less wrong one.

    The bounds consult `claims_total` not at all. For any partial verdict set P of the true pinned
    set T: `|P \\ L| <= |T \\ L|` and `|L \\ P| >= |L \\ T|`, so a superseded count BELOW what the
    verdicts already name, or an added count ABOVE what they leave room for, is provably wrong
    whatever subset was handed in."""
    from coyomap.finalize import _stale_grounding_pin
    with tempfile.TemporaryDirectory() as tmp:
        live = ["kept", "added-since"]
        v = make_verdicts_file(tmp, ["kept", "reconciled-away"])
        honest = make_grounding_map(tmp, live, claims_total=2,
                                    claims_superseded=1, claims_added_since=1)
        assert _stale_grounding_pin(honest, live, [v]) is None
        for label, total in (("lowered", 1), ("raised", 17), ("digit string", "2"), ("zero", 0)):
            cheat = Path(tmp) / f"cheat-{label}.json"
            cheat.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g", "grounding": {
                "claims_total": total, "claims_challenged": 2, "claims_superseded": 0,
                "claims_added_since": 0,
                "live_claims_digest": __import__("coyomap.grounding", fromlist=["x"])
                .live_claims_digest(live)}}), encoding="utf-8")
            assert _stale_grounding_pin(cheat, live, [v]), f"{label} total bought silence"


def test_a_partial_verdict_set_still_stays_silent():
    """The honest case the guard exists for: `finalize` handed fewer files than the record was
    written against must not accuse it."""
    from coyomap.finalize import _stale_grounding_pin
    with tempfile.TemporaryDirectory() as tmp:
        live = ["kept", "added-since"]
        v = make_verdicts_file(tmp, ["kept"])          # 1 of the 2 pinned claims
        rec = make_grounding_map(tmp, live, claims_total=2,
                                 claims_superseded=1, claims_added_since=1)
        assert _stale_grounding_pin(rec, live, [v]) is None


def test_corrupting_claims_total_cannot_hide_a_wrong_digest():
    """The digest check used to sit BEHIND an early return for a missing or nonsensical
    `claims_total`, so a record bought silence by corrupting that field: 0, -5 and the string "446"
    all skipped the comparison even when the digest was provably another map's. Corrupting a field
    must never be safer than filling it in — the third appearance of that shape in this file."""
    from coyomap.finalize import _stale_grounding_pin
    from coyomap.grounding import live_claims_digest
    live = [f"claim {i}" for i in range(10)]
    other = [f"other {i}" for i in range(10)]          # same SIZE, different claims
    with tempfile.TemporaryDirectory() as tmp:
        for bad_total in (0, -5, "446", None):
            p = Path(tmp) / f"m{bad_total}.json"
            p.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g", "grounding": {
                "claims_total": bad_total, "claims_challenged": 10,
                "live_claims_digest": live_claims_digest(other)}}), encoding="utf-8")
            msg = _stale_grounding_pin(p, live)
            assert msg and "live_claims_digest" in msg, (bad_total, msg)


def test_a_record_with_no_numbers_at_all_is_not_called_stale():
    """`validate` owns the malformed-record complaint. This command reports staleness, and a record
    with nothing in it is unfinished, not stale."""
    from coyomap.finalize import _stale_grounding_pin
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.json"
        p.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g", "grounding": {}}),
                     encoding="utf-8")
        assert _stale_grounding_pin(p, ["a", "b"]) is None


def test_the_shape_line_names_the_access_surface():
    """The commit states the map's shape, and the access surface is part of it. Before the T7 fold
    the only mention of auth here was `len(m.security)`, gated on `if m.security:` — which the fold
    empties, so two real builds committed shapes that said nothing about 47 and 44 access rules."""
    root, p = make_repo()
    doc = json.loads(p.read_text())
    # a rule's components are DERIVED by resolving its sites through `files`, so validate blocks a
    # map that has rules and no component declaring any — give the first component the site's file
    doc["components"][0]["files"] = ["src/a.py"]
    doc["rules"] = [
        {"id": "BR1", "statement": "Only an owner may cancel.", "access": True,
         "risk": "anyone could cancel", "sites": [{"where": "a.py:1", "why": "rejects"}]},
        {"id": "BR2", "statement": "A refund is capped at the paid amount.",
         "sites": [{"where": "b.py:2", "why": "clamps"}]}]
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    report = finalize.build_report(p, root, [])
    block = finalize.gate_block(report, report.map_sha256)
    assert "2 business rules" in block, block
    assert "(1 access)" in block, block


def test_the_shape_line_says_nothing_about_access_when_there_is_none():
    """A map with no access rule must not gain an empty `(0 access)` clause."""
    root, p = make_repo()
    doc = json.loads(p.read_text())
    doc["rules"] = [{"id": "BR1", "statement": "A refund is capped.",
                     "sites": [{"where": "b.py:2", "why": "clamps"}]}]
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    report = finalize.build_report(p, root, [])
    assert "access)" not in finalize.gate_block(report, report.map_sha256)


def test_the_disposition_table_keys_an_audit_advisory_on_the_pair_not_the_family():
    """`finalize` says every advisory is "either fixed or recorded under the extras heading its
    message names", and used to check nothing — nine shipped on one map neither fixed nor recorded,
    invisible because every read of the list had been narrowed by a grep.

    The first draft of the table reproduced the bug it reports on: reading every id under 'Audit
    exceptions' marked a `flow-title UC25` advisory "recorded" on the strength of an unrelated
    `actor-attribution UC25` line. A record adjudicates one (check, id) pair, never a family."""
    from coyomap.finalize import advisory_disposition, FinalizeReport, Leg, RAN
    import json, tempfile, os
    # UC25 must be DEFINED: candidate ids are intersected with the map's real id universe, because
    # shape alone cannot tell subsystem `S3` from Amazon S3, and a false id can flip a genuine gap
    # to "recorded". A map that references an id it never declares is not a realistic input.
    m = {"format": "coyomap-map", "title": "t", "goal": "g",
         "roles": [{"id": "R2", "name": "Admin", "kind": "human"}],
         "use_cases": [{"id": "UC25", "name": "Rebuild the graph", "actors": ["R2"],
                        "trigger": "an admin asks", "outcome": "it rebuilds"}],
         "extras": [{"heading": "Audit exceptions",
                     "body": "actor-attribution UC25: the scheduler opens it, deliberate."}]}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "m.json")
        with open(p, "w") as fh:
            json.dump(m, fh)
        rep = FinalizeReport(
            map_path=p, map_sha256="x", verdict="ADVISORIES",
            legs=[Leg("audit", RAN, advisory=[
                "flow-title: UC25 — a renamed use case whose flow was never re-traced. "
                "Record 'flow-title <id>: <why>' under an 'Audit exceptions' extras heading.",
                "actor-attribution: UC25 — declared actors do not include the opener. "
                "Record 'actor-attribution <id>: <why>' under an 'Audit exceptions' extras heading."])],
            advisory_total=2, blocking_total=0)
        by_msg = {a.split(":", 1)[0]: d for d, _h, a in advisory_disposition(Path(p), rep)}
    assert by_msg["flow-title"] == "UNRECORDED", "an unrelated check's record must not count"
    assert by_msg["actor-attribution"] == "recorded"


def test_the_table_never_says_recorded_without_naming_the_key_that_records_it():
    """The first draft defaulted to `recorded` whenever a heading existed and the advisory carried
    no id — so it reported "recorded" for an advisory whose own text reads "and no granularity
    record". That is the exact failure the table exists to catch, committed by the table.

    And a DISCLOSURE — an advisory that reports what a record silenced — is not an advisory asking
    to be recorded. Marking those `recorded` filed the whole "a recorded gap is still a gap" family
    under "handled", cancelling the disclosure that had just been added to raise it."""
    from coyomap.finalize import advisory_disposition, FinalizeReport, Leg, RAN
    import json, tempfile, os
    m = {"format": "coyomap-map", "title": "t", "goal": "g",
         "extras": [{"heading": "Balance exceptions", "body": "granularity: deliberate.\nUC2: fine."}]}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "m.json")
        with open(p, "w") as fh:
            json.dump(m, fh)
        rep = FinalizeReport(
            map_path=p, map_sha256="x", verdict="ADVISORIES",
            legs=[Leg("validate", RAN, advisory=[
                "44 `access: true` rule(s) and no granularity record — record "
                "'security-granularity: <why>' under a 'Balance exceptions' extras heading",
                "66 component(s) with unclaimed surfaces are suppressed by a recorded "
                "'Unclaimed surfaces' line and counted as CLAIMED because of it: C1, C2"])],
            advisory_total=2, blocking_total=0)
        got = [d for d, _h, _a in advisory_disposition(Path(p), rep)]
    assert got[0] != "recorded", "an unrecorded advisory must never be filed as recorded"
    assert got[1] == "disclosure", "a disclosure of records is not itself a recordable advisory"


# --- a leg nobody asked for is not silence ----------------------------------------
# A build ran `finalize … --verdicts <30 files>`, then re-ran it with `--emit-gate-block` and NO
# `--verdicts` purely to emit the block. The second run overwrote the report, so what shipped — and
# what the commit message quoted — carried only the shape-only anchor-drift leg, losing the
# verdict-based leg and its `challenged N of M worklist claim(s)` coverage line. Nothing said so.


def _with_verdicts_beside_the_map(root: Path) -> Path:
    verify = root / ".coyomap" / "verify"
    verify.mkdir()
    for name in ("verdicts-a.json", "verdicts-b.json"):
        (verify / name).write_text(json.dumps({"grounding": []}), encoding="utf-8")
    return verify


def test_verdict_files_beside_the_map_are_named_when_the_run_was_given_none():
    root, p = make_repo()
    _with_verdicts_beside_the_map(root)
    assert finalize.main([str(p), "--repo", str(root)]) == 0        # still not a gate
    report = (root / ".coyomap" / "finalize-report.md").read_text(encoding="utf-8")
    assert "NOT RUN" in report
    assert "2 verdict file(s)" in report
    assert "--emit-gate-block` combine in ONE invocation" in report


def test_the_nag_is_gone_once_the_verdicts_are_passed():
    root, p = make_repo()
    verify = _with_verdicts_beside_the_map(root)
    args = [str(p), "--repo", str(root)]
    for f in sorted(verify.glob("verdicts-*.json")):
        args += ["--verdicts", str(f)]
    assert finalize.main(args) == 0
    report = (root / ".coyomap" / "finalize-report.md").read_text(encoding="utf-8")
    assert "NOT RUN" not in report


def test_a_map_with_no_verdicts_anywhere_says_nothing_about_them():
    root, p = make_repo()
    assert finalize.main([str(p), "--repo", str(root)]) == 0
    assert "NOT RUN" not in (root / ".coyomap" / "finalize-report.md").read_text(encoding="utf-8")


def test_finalize_records_whether_balance_ran_and_does_not_gate_on_it():
    """Phase 3.5 left a trace, or it did not happen.

    `method.md` puts a `coyomap balance` pass after the trace and says to reconcile each finding.
    Nothing observed it, so a skipped Phase 3.5 and a passed one read the same: one build ran
    `balance` three times and the next ran it ZERO times, and the only reason nobody noticed is
    that `validate` happened to emit no balance warning that run.

    The leg is INFORMATIONAL. `method.md` is explicit that "balance never gates and only ever
    re-groups", so its findings must not move this command's verdict.
    """
    from coyomap.finalize import build_report
    repo, map_path = make_repo()
    report = build_report(map_path, repo, [])
    balance_legs = [l for l in report.legs if l.name.startswith("balance")]
    assert len(balance_legs) == 1, [l.name for l in report.legs]
    leg = balance_legs[0]
    assert leg.ran, leg.note
    assert leg.note and "balance finding" in leg.note or "no balance findings" in (leg.note or "")
    assert leg.blocking == [] and leg.advisory == [], (
        "balance never gates — its findings must not become finalize advisories")
    assert report.advisory_total == sum(len(l.advisory) for l in report.legs if l is not leg)


# --- the grounding-refutations leg ----------------------------------------------

def make_verdicts(root: Path, name: str, rows: list[dict]) -> Path:
    """One skeptic's verdict file, where a build keeps them."""
    d = root / ".coyomap" / "verify"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps({"grounding": rows}), encoding="utf-8")
    return p


def test_a_refutation_the_map_still_carries_blocks_the_run():
    """No gate could see this before. `validate` reads shape, `audit` reads the map against itself,
    and the grounding record reduces the pass to four numbers in which a refutation that was
    reconciled and one that was ignored are the same integer. A live map shipped two refuted edges
    while this report said 0 blocking and never used the word "refuted"."""
    root, p = make_repo()
    v = make_verdicts(root, "verdicts-a.json",
                      [{"claim": "C1 calls C2", "grounded": False, "evidence": "src/a.py:2",
                        "note": "src/a.py never reaches back()"}])
    code = finalize.main([str(p), "--repo", str(root), "--verdicts", str(v)])
    assert code == 1
    doc = json.loads((root / ".coyomap" / "finalize-report.json").read_text())
    leg = next(l for l in doc["legs"] if l["name"] == "grounding refutations")
    assert len(leg["blocking"]) == 1 and "C1 calls C2" in leg["blocking"][0]
    assert doc["verdict"] == "BLOCKED"


def test_a_refutation_the_reconcile_applied_is_not_reported():
    """The whole discrimination. A refuted claim that was corrected or dropped no longer resolves
    against the live map, so it must leave no trace here — otherwise the gate fires forever on work
    that was done."""
    root, p = make_repo()
    v = make_verdicts(root, "verdicts-a.json",
                      [{"claim": "C1 persists C2", "grounded": False, "evidence": "src/a.py:2"}])
    assert finalize.main([str(p), "--repo", str(root), "--verdicts", str(v)]) == 0


def test_a_confirmed_claim_never_blocks():
    root, p = make_repo()
    v = make_verdicts(root, "verdicts-a.json",
                      [{"claim": "C1 calls C2", "grounded": True, "evidence": "src/a.py:2"}])
    assert finalize.main([str(p), "--repo", str(root), "--verdicts", str(v)]) == 0


def test_the_uncovered_element_finding_is_ONE_advisory_not_one_per_element():
    """An advisory here is contractually "fixed, or recorded under the heading its message names".
    A live map has 81 of these and no heading to record them under, so one row per element would
    push the ten real advisories off the top of the report."""
    root, p = make_repo(components=30)
    doc = json.loads(p.read_text())
    for c in doc["components"]:          # the authored label the votes are compared against
        c["confidence"] = "verified"
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    v = make_verdicts(root, "verdicts-a.json",
                      [{"claim": "C1 calls C2", "grounded": True, "evidence": "src/a.py:2"}])
    finalize.main([str(p), "--repo", str(root), "--verdicts", str(v)])
    doc = json.loads((root / ".coyomap" / "finalize-report.json").read_text())
    leg = next(l for l in doc["legs"] if l["name"] == "grounding refutations")
    assert len(leg["advisory"]) == 1
    assert "never looked at by a skeptic" in leg["advisory"][0]


def _map_with_rule(access: bool, confidence: str) -> tuple[Path, Path]:
    """A repo whose map carries one rule with a site, an authored `confidence`, and no verdict."""
    root, p = make_repo()
    doc = json.loads(p.read_text())
    # a rule's components are DERIVED by resolving its sites through `Component.files`, so validate
    # blocks a map that carries rules and no component declaring any
    doc["components"][0]["files"] = ["src/a.py"]
    doc["rules"] = [{"id": "BR1", "name": "Live updates never cross organizations",
                     "statement": "A listener reaches one organization only.",
                     "risk": "A wildcard listener is a tenant data leak.",
                     "access": access, "confidence": confidence,
                     "sites": [{"where": "src/a.py:2", "why": "the refusal"}]}]
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return root, p


def test_an_ACCESS_rule_no_skeptic_EVER_voted_on_is_CALLED_OUT_but_does_not_block():
    """Who-may-do-what is the one thing a reader trusts a map for, so an unchallenged access rule is
    named separately and first. It is ADVISORY, and that is a deliberate reversal.

    It shipped BLOCKING and keyed on nothing but coverage, which failed BOTH reference maps with no
    way out: every access rule on them says `inferred` (49 of 49 on one, 30 of 30 on the other)
    because the old contract mandated it, so the old `verified`-keyed gate had been dead by
    construction and making it live blocked everything at once. A blocking finding has no
    recorded-exception route at all, and the remedy the message names — send it to a skeptic — is
    unreachable after the verify phase closes. Promote it once one build ships with zero of these,
    and give it a recordable heading first."""
    root, p = _map_with_rule(access=True, confidence="verified")
    v = make_verdicts(root, "verdicts-a.json",
                      [{"claim": "C1 calls C2", "grounded": True, "evidence": "src/a.py:2"}])
    assert finalize.main([str(p), "--repo", str(root), "--verdicts", str(v)]) == 0
    doc = json.loads((root / ".coyomap" / "finalize-report.json").read_text())
    leg = next(l for l in doc["legs"] if l["name"] == "grounding refutations")
    assert not leg["blocking"], leg["blocking"]
    assert "ACCESS rule(s) were never challenged" in leg["advisory"][0], leg["advisory"]
    assert "BR1" in leg["advisory"][0]


def test_the_access_call_out_does_not_read_the_label():
    """It used to fire only on `confidence: verified`. `confidence` says what the AUTHOR knew, so an
    access rule the author genuinely read is honestly `verified` whether or not a skeptic saw it —
    and relabelling an unchallenged rule `inferred` used to silence the finding entirely, which was
    the remedy the old message itself recommended."""
    root, p = _map_with_rule(access=True, confidence="inferred")
    v = make_verdicts(root, "verdicts-a.json",
                      [{"claim": "C1 calls C2", "grounded": True, "evidence": "src/a.py:2"}])
    assert finalize.main([str(p), "--repo", str(root), "--verdicts", str(v)]) == 0
    doc = json.loads((root / ".coyomap" / "finalize-report.json").read_text())
    leg = next(l for l in doc["legs"] if l["name"] == "grounding refutations")
    assert "ACCESS rule(s) were never challenged" in leg["advisory"][0], leg["advisory"]


def test_a_NON_access_rule_nobody_voted_on_stays_advisory():
    """The narrowness is the point. A rule about how something WORKS that the pass did not reach is
    a coverage gap, and gating on every one of those would fail honest maps. Access is the
    exception because of what it claims, not because of how it is labelled."""
    root, p = _map_with_rule(access=False, confidence="verified")
    v = make_verdicts(root, "verdicts-a.json",
                      [{"claim": "C1 calls C2", "grounded": True, "evidence": "src/a.py:2"}])
    assert finalize.main([str(p), "--repo", str(root), "--verdicts", str(v)]) == 0
    doc = json.loads((root / ".coyomap" / "finalize-report.json").read_text())
    leg = next(l for l in doc["legs"] if l["name"] == "grounding refutations")
    assert not leg["blocking"]
    assert any("never looked at by a skeptic" in a for a in leg["advisory"])


def test_the_leg_is_absent_rather_than_silently_clean_when_no_verdicts_are_given():
    """A leg that cannot run must not report a pass. `finalize` already says which verdict files it
    was not given; inventing a clean grounding leg out of no verdicts is the failure this whole
    command exists to stop."""
    root, p = make_repo()
    finalize.main([str(p), "--repo", str(root)])
    doc = json.loads((root / ".coyomap" / "finalize-report.json").read_text())
    assert not [l for l in doc["legs"] if l["name"] == "grounding refutations"]


# --- the option parsing the leg exposed ------------------------------------------

def test_verdicts_swallows_every_file_a_shell_glob_expands_to():
    """`--verdicts verify/verdicts-*.json` is the natural spelling and the one the usage line
    implies. It took ONE path per flag, so the shell's other files fell through to the positional
    list and were dropped in silence — and the report then described a pass over one batch as the
    whole pass. Found by a run that reported 0 blocking on a map with two surviving refutations."""
    root, p = make_repo()
    a = make_verdicts(root, "verdicts-a.json",
                      [{"claim": "C1 calls C2", "grounded": True, "evidence": "src/a.py:2"}])
    b = make_verdicts(root, "verdicts-b.json",
                      [{"claim": "C1 calls C2", "grounded": False, "evidence": "src/a.py:2"},
                       {"claim": "C1 calls C2", "grounded": False, "evidence": "src/a.py:2"}])
    # Two files, one flag — the glob form. Both must be read, so the refutations win 2-1.
    code = finalize.main([str(p), "--repo", str(root), "--verdicts", str(a), str(b)])
    assert code == 1


def test_a_second_bare_path_is_refused_rather_than_ignored():
    """Swallowing it is how the glob above went unnoticed: the files landed in the positional list
    and nothing said a word."""
    root, p = make_repo()
    assert finalize.main([str(p), str(p), "--repo", str(root)]) == 2


# --- an escape that is not an extras heading --------------------------------------
# The disposition table resolved an escape by matching the advisory text against
# `records.KNOWN_HEADINGS` — a list of EXTRAS headings. An advisory offering a MAP FIELD as its
# remedy therefore fell through to "carried (no escape)" while the build had already taken it. On
# the 2026-08-20 argus map the post-pin-claims advisory says "or say in `grounding.note` which
# claims were minted after the pin", the shipped note says exactly that, and the report AND the
# commit message both called it unescapable.

_POSTPIN = ("Grounding covers the PINNED worklist, not the shipped map: 1 of the shipped map's "
            "376 claim(s) have NO verdict (375 do). Challenge them and re-run `coyomap grounding "
            "write`, or say in `grounding.note` which claims were minted after the pin and why "
            "they were not re-challenged.")


def _disposition_for(note: str | None, advisory: str) -> tuple[str, str]:
    from coyomap.finalize import advisory_disposition, FinalizeReport, Leg, RAN
    import json, tempfile, os
    m: dict[str, object] = {"format": "coyomap-map", "title": "t", "goal": "g"}
    if note is not None:
        m["grounding"] = {"claims_total": 3, "claims_challenged": 3, "claims_confirmed": 3,
                          "claims_refuted": 0, "claims_unverifiable": 0, "note": note}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "m.json")
        with open(p, "w") as fh:
            json.dump(m, fh)
        rep = FinalizeReport(map_path=p, map_sha256="x", verdict="ADVISORIES",
                             legs=[Leg("validate", RAN, advisory=[advisory])],
                             advisory_total=1, blocking_total=0)
        got = advisory_disposition(Path(p), rep)
    return got[0][0], got[0][1]


def test_an_advisory_escaped_through_a_map_field_is_not_carried_with_no_escape():
    disposition, where = _disposition_for("One claim was minted after the pin; here is why.",
                                          _POSTPIN)
    assert disposition == "recorded", disposition
    assert where == "grounding.note", where


def test_a_note_that_does_not_name_the_count_is_UNANSWERED_not_recorded():
    """This field was the one escape in the map with no KEY. Every other family keys a recorded line
    to the id it silences and refuses a line that keys to nothing; here any non-empty string filed
    the advisory as answered, so a note reading `no.` closed it. Naming the number the advisory is
    about is the smallest key prose can carry, and it cannot be met without reading the finding."""
    assert _disposition_for("no.", _POSTPIN)[0] == "UNANSWERED"
    assert _disposition_for("Every claim in this map was challenged.", _POSTPIN)[0] == "UNANSWERED"
    # a note about a DIFFERENT number is the realistic failure: it reads as an answer and is not one
    assert _disposition_for("Nine claims were minted after the pin.", _POSTPIN)[0] == "UNANSWERED"


def test_the_demanded_count_is_the_one_the_FINDING_is_about():
    """"The first number in the advisory" was wrong for half of them. The partial-grounding advisory
    OPENS with the count of claims that were confirmed — the good number. Demanding it accepted a
    note restating the headline and rejected the note that answers the finding."""
    partial = ("Grounding is partial: 100 of 500 claims confirmed (20%), 9 refuted. At that "
               "refutation rate the 400 remaining claims are good leads, not facts — say which "
               "claims were prioritized in `grounding.note`")
    assert _disposition_for("We prioritized the 400 remaining claims in the sign-in areas.",
                            partial)[0] == "recorded"
    assert _disposition_for("The 100 confirmed claims were the security theme.",
                            partial)[0] == "UNANSWERED"


def test_an_advisory_whose_wording_moves_out_from_under_its_pattern_fails_OPEN():
    """A gate that starts demanding an arbitrary number would reject honest notes with no way to
    tell why. No key means no demand — the behaviour before the key table existed."""
    unknown = "Something new about `grounding.note` with 7 and 9 in it."
    assert _disposition_for("any text at all", unknown)[0] == "recorded"


def test_a_number_inside_a_path_or_a_filename_does_not_count_as_naming_it():
    """`read verdicts-21.json` names a file. Accepting it let a note satisfy a demand for 21 by
    citing an artifact rather than by stating the count."""
    from coyomap.finalize import _note_names
    assert not _note_names("read verdicts-21.json", 21)
    assert not _note_names("src/a.py:21", 21)
    assert _note_names("The 21 post-pin claims were read line by line.", 21)


def test_the_spelled_form_needs_word_boundaries():
    """As a bare substring `ten` is inside "written", `one` inside "someone"/"none"/"money", `eight`
    inside "weighted". Against one real 3400-character note, 13 of 18 counts probed matched by
    accident, which made this check close to inert for anything under twenty."""
    from coyomap.finalize import _note_names
    assert not _note_names("nothing was written down", 10)
    assert not _note_names("someone looked at it", 1)
    assert not _note_names("none of them", 1)
    assert not _note_names("we weighted the evidence", 8)
    assert _note_names("ten claims", 10)
    assert _note_names("one claim", 1)


def test_the_count_may_be_spelled_out_because_a_note_is_prose():
    """The shipped mcpolis note says "Twenty-one claims in the shipped map were never in the pinned
    worklist". A digit-only check would have called that honest note unanswered."""
    adv = _POSTPIN.replace("1 of the shipped map's 376", "21 of the shipped map's 376")
    assert _disposition_for("Twenty-one claims were minted after the pin.", adv)[0] == "recorded"
    assert _disposition_for("The 21 post-pin claims were read line by line.", adv)[0] == "recorded"


def test_the_same_advisory_with_an_empty_note_is_unrecorded_not_unsure():
    """Both halves of the key are known — the field is named and it is empty — so absence is a fact."""
    assert _disposition_for("", _POSTPIN)[0] == "UNRECORDED"
    assert _disposition_for(None, _POSTPIN)[0] == "UNRECORDED"


def test_an_advisory_naming_no_escape_at_all_is_still_carried():
    """Widening the vocabulary must not turn every unescapable advisory into a recorded one."""
    minted = ("entry-point kind(s) minted (not a seed): 'browser-launch' — fine where the seeds "
              "name nothing close.")
    assert _disposition_for("a note about something else", minted)[0] == "carried (no escape)"


# --- the access baseline leg -------------------------------------------------------

def _finalize_with_baseline(tmp: Path, before: dict, after: dict):
    from coyomap.finalize import build_report
    base = tmp / "before.json"
    cur = tmp / "after.json"
    base.write_text(json.dumps(before), encoding="utf-8")
    cur.write_text(json.dumps(after), encoding="utf-8")
    return build_report(cur, tmp, [], base)


_AUTH = {"format": "coyomap-map", "title": "t", "goal": "g",
         "rules": [{"id": "BR21", "statement": "Only a proven upstream identity", "access": True,
                    "risk": "impersonation",
                    "sites": [{"where": "a/auth_google.py:67", "why": "verifies the signature"}]}]}
_NO_AUTH = {"format": "coyomap-map", "title": "t", "goal": "g",
            "rules": [{"id": "BR7", "statement": "Owner scoping", "access": True, "risk": "leak",
                       "sites": [{"where": "b/store.py:18", "why": "scopes by owner"}]}]}


def test_finalize_names_a_file_that_lost_its_access_claim():
    """The signal existed only in `coyomap-eval compare`'s notes — a developer-only command that runs
    at retro time. Here it runs after the map is written, so reading the baseline cannot contaminate
    the rebuild, and before the commit, which is the last moment anybody looks."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        report = _finalize_with_baseline(Path(td), _AUTH, _NO_AUTH)
    leg = next(l for l in report.legs if l.name == "access baseline")
    assert leg.advisory, leg
    assert "a/auth_google.py" in leg.advisory[0]
    assert not leg.blocking, "two LLM builds legitimately differ — this must never gate"


def test_finalize_says_so_when_the_whole_surface_survived():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        report = _finalize_with_baseline(Path(td), _AUTH, _AUTH)
    leg = next(l for l in report.legs if l.name == "access baseline")
    assert not leg.advisory, leg
    # `Leg.note` is optional by design — a leg that RAN with nothing to say carries None. Binding it
    # makes the failure name the missing note rather than an AttributeError two frames down.
    note = leg.note
    assert note is not None, leg
    assert "still named by an access rule" in note


def test_a_deliberate_drop_recorded_by_PATH_actually_silences_the_advisory():
    """The BEHAVIOURAL half, and the one that was missing. The advisory told the operator to record
    `access-baseline <path>: <why>` under 'Audit exceptions' — whose key vocabulary is `[A-Z]+\\d+`,
    so a path could never be a key there, and nothing read the heading for this purpose anyway. One
    live build wrote twenty such records and every one was inert: the same advisory came back
    unchanged on the next run.

    A static "the escape is wired" check cannot see that. This runs it: record the path, and the
    file must drop out of the FINDING.

    Out of the finding, and NOT out of the report — see
    `test_an_excused_file_is_disclosed_not_erased`. The record answers the question "is this
    deliberate?"; it does not make the file covered."""
    import tempfile
    from coyomap.finalize import ACCESS_BASELINE_EXCEPTIONS_HEADING
    after = {**_NO_AUTH, "extras": [{"heading": ACCESS_BASELINE_EXCEPTIONS_HEADING,
                                     "body": "a/auth_google.py: the check moved into the gateway "
                                             "and is claimed by BR7 there."}]}
    with tempfile.TemporaryDirectory() as td:
        report = _finalize_with_baseline(Path(td), _AUTH, after)
    leg = next(l for l in report.legs if l.name == "access baseline")
    assert len(leg.advisory) == 1, leg.advisory
    assert "check each one before shipping" not in leg.advisory[0], (
        "the FINDING must be gone — this is the disclosure, not the original advisory")


def test_an_excused_file_is_disclosed_not_erased():
    """The escape must not make the gate assert the opposite of what is true.

    Subtracting the excused paths and then, finding nothing left, printing "every one of the N
    file(s) ... is still named by an access rule" is what this leg used to do. On the 2026-08-29
    mcpolis build nine files were excused, that sentence was emitted, and it went into the commit
    message. Every sibling escape in this toolchain discloses in the same breath as it forgives:
    `Unclaimed surfaces` prints "counted as CLAIMED because of it"."""
    import tempfile
    from coyomap.finalize import ACCESS_BASELINE_EXCEPTIONS_HEADING
    after = {**_NO_AUTH, "extras": [{"heading": ACCESS_BASELINE_EXCEPTIONS_HEADING,
                                     "body": "a/auth_google.py: the check moved into the gateway "
                                             "and is claimed by BR7 there."}]}
    with tempfile.TemporaryDirectory() as td:
        report = _finalize_with_baseline(Path(td), _AUTH, after)
    leg = next(l for l in report.legs if l.name == "access baseline")
    text = " ".join(leg.advisory) + (leg.note or "")
    assert "every one of" not in text, f"the excused file is being erased, not disclosed: {text}"
    assert "a/auth_google.py" in text, text
    assert "recorded as deliberate" in text, text
    assert "A recorded gap is still a gap" in text, text
    assert not leg.blocking, "still advisory"


def test_the_advisory_names_the_heading_that_can_actually_carry_a_path():
    """The message is the operator's only instruction, so it must name a heading whose grammar
    accepts what it asks them to write. `Audit exceptions` cannot: its keys are ids."""
    import tempfile
    from coyomap.finalize import ACCESS_BASELINE_EXCEPTIONS_HEADING
    from coyomap import records
    with tempfile.TemporaryDirectory() as td:
        report = _finalize_with_baseline(Path(td), _AUTH, _NO_AUTH)
    msg = next(l for l in report.legs if l.name == "access baseline").advisory[0]
    assert ACCESS_BASELINE_EXCEPTIONS_HEADING in msg
    assert "Audit exceptions" not in msg
    # and the heading it names really parses a PATH as a key
    from coyomap.model import ExtraSection, ProjectModel
    m = ProjectModel(title="t", goal="g")
    m.extras = [ExtraSection(heading=ACCESS_BASELINE_EXCEPTIONS_HEADING,
                             body="a/auth_google.py: deliberate.")]
    assert records.recorded_keys(m, ACCESS_BASELINE_EXCEPTIONS_HEADING) == {"a/auth_google.py"}


def test_the_leg_is_absent_when_no_baseline_is_given():
    """A build with no predecessor must not grow a leg that silently reports nothing."""
    from coyomap.finalize import build_report
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        cur = Path(td) / "after.json"
        cur.write_text(json.dumps(_NO_AUTH), encoding="utf-8")
        report = build_report(cur, Path(td), [])
    assert not any(l.name == "access baseline" for l in report.legs)


def test_an_unreadable_baseline_is_INCOMPLETE_not_a_pass():
    """A leg that could not run must never read as silence — that is the whole INCOMPLETE rule."""
    from coyomap.finalize import build_report, FAILED
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cur = tmp / "after.json"
        cur.write_text(json.dumps(_NO_AUTH), encoding="utf-8")
        bad = tmp / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        report = build_report(cur, tmp, [], bad)
    leg = next(l for l in report.legs if l.name == "access baseline")
    assert leg.status == FAILED
    note = leg.note
    assert note is not None, leg
    assert "could not be read" in note
    # A FAILED leg forces INCOMPLETE unless something BLOCKS — the verdict order is blocking first,
    # then incomplete, because a blocking problem is known and an unrun leg is unknown.
    assert report.verdict in ("BLOCKED", "INCOMPLETE"), report.verdict
    assert leg not in [l for l in report.legs if l.status == "ran"]


# --- the warrant, and reading without writing (retro 2026-09-02, mcpolis N1 and 17) ---------------

def _repo_with_warrant(tmp: Path) -> Path:
    out = tmp / ".coyomap"
    (out / "verify").mkdir(parents=True)
    (out / "build-fragments").mkdir(parents=True)
    (out / "project-map.json").write_text("{}")
    (out / "project-map.md").write_text("#")
    (out / "preindex.json").write_text("{}")
    (out / "provenance.json").write_text("{}")
    (out / "verify" / "worklist.json").write_text("[]")
    (out / "verify" / "verdicts-a.json").write_text("{}")
    (out / "build-fragments" / "a.json").write_text("{}")
    return out / "project-map.json"


def test_the_commit_line_names_the_maps_warrant(tmp_path, capsys):
    """`grounding.note` cites the verdict rows as the reason to believe the map. Ship the counts
    without the rows and a fresh clone has the conclusion and can check no part of it."""
    from coyomap.finalize import _commit_hint
    _commit_hint(_repo_with_warrant(tmp_path))
    out = capsys.readouterr().out
    assert "verify" in out and "build-fragments" in out, out
    assert "WARRANT" in out, out


def test_the_commit_line_omits_a_warrant_that_is_not_there(tmp_path, capsys):
    from coyomap.finalize import _commit_hint
    out_dir = tmp_path / ".coyomap"
    out_dir.mkdir()
    (out_dir / "project-map.json").write_text("{}")
    _commit_hint(out_dir / "project-map.json")
    printed = capsys.readouterr().out
    assert "WARRANT" not in printed, printed


# --- the reconcile file was in nobody's commit line (retro 2026-09-13 reminderrepo, T1) ----------
# `method.md` calls `.coyomap/reconcile.json` the only mechanism that makes a reconcile decision
# survive a rebuild, and the printed `git add -f` line never named it. Re-assembling that build's
# COMMITTED fragments without it gives 248 edges against the committed map's 243: the two arrows
# the closer upheld as false come back, 8 code links revert, 119 directive rows are lost.

def test_the_commit_line_takes_the_reconcile_file(tmp_path, capsys):
    from coyomap.finalize import _commit_hint
    map_path = _repo_with_warrant(tmp_path)
    (map_path.parent / "reconcile.json").write_text('{"set": []}')
    _commit_hint(map_path)
    out = capsys.readouterr().out
    command = next(ln for ln in out.splitlines() if "git add -f" in ln)
    assert "reconcile.json" in command, command
    # With the INPUTS, ahead of the two warrant directories the sentence below calls "the last".
    assert command.index("reconcile.json") < command.index("verify"), command


def test_a_build_that_reconciled_nothing_is_asked_not_scolded(tmp_path, capsys):
    """Absence is legitimate — a build that reconciled nothing has no such file and needs none —
    so it must not join the `produce them and re-run finalize` arm."""
    from coyomap.finalize import _commit_hint
    _commit_hint(_repo_with_warrant(tmp_path))
    out = capsys.readouterr().out
    assert "reconcile.json" in out, out
    assert "no " in out and "reconciled nothing" in out, out
    assert "NOT in that command" not in out, out




# --- claim batches nobody answered are BLOCKING (2026-09-19) -------------------------------------
# The 2026-09-08 mcpolis build cut 24 behaviour batches holding 949 claims, dispatched none, and
# shipped ADVISORIES. One unchallenged step said an expired sign-in warns the team's ADMIN where the
# code warns the affected USER. `grounding write --partial` legitimately lifts the refusal over the
# same fact, so the fact needed a second gate that no flag lifts.
#
# The FIRST version of that gate paired file names and an adversarial review broke it both ways
# (F1/F2 below). It pairs claim text now; the two criticals are regression tests here.

def _verify(tmp_path):
    out = tmp_path / ".coyomap"
    (out / "verify").mkdir(parents=True)
    return out


def _batch(out, name, claims, theme=None):
    """A claims batch as `write_theme_batches` writes one."""
    import json
    payload = {"theme": theme or "backbone",
               "claims": [{"claim": c, "anchor": None} for c in claims]}
    (out / "verify" / f"claims-{name}.json").write_text(json.dumps(payload))


def _verdicts(out, name, claims):
    """A skeptic's answer. No `verdict` field, so these are VOTES, not closer appeals."""
    import json
    rows = [{"claim": c, "grounded": True, "evidence": "x.py:1", "skeptic": name} for c in claims]
    (out / "verify" / f"verdicts-{name}.json").write_text(json.dumps({"grounding": rows}))


def test_the_method_states_the_pairing_the_claims_leg_actually_does():
    """A substring check on a file name is what let the first version ship: the method said names
    were paired, the leg paired names, and both were wrong together."""
    from pathlib import Path
    method = (Path(__file__).resolve().parents[1] / "method.md").read_text(encoding="utf-8")
    assert "verdicts-«BATCH».json" in method
    assert "reads the CLAIMS, never the file names" in method, (
        "the method must say the gate pairs claims, or a lead reads a name mismatch as a failure "
        "and starts copying verdict files to satisfy it")


def test_a_batch_nobody_answered_blocks(tmp_path):
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    _batch(out, "behaviour-1", ["UC44 step 6 — warn the team admin"], theme="behaviour")
    leg = _undispatched_claims_leg(out / "project-map.json")
    assert leg is not None
    assert leg.blocking and not leg.advisory, "an unanswered batch must BLOCK, not advise"
    assert "behaviour" in leg.blocking[0]


def test_an_answered_batch_is_silent(tmp_path):
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    _batch(out, "behaviour-1", ["UC44 step 6 — warn the team admin"])
    _verdicts(out, "behaviour-1", ["UC44 step 6 — warn the team admin"])
    assert _undispatched_claims_leg(out / "project-map.json") is None


def test_one_verdict_file_may_answer_several_batches(tmp_path):
    """F1, CRITICAL. `skeptic-contract.md`: «BATCH» is the SKEPTIC's id, «CLAIMS» the file it reads,
    and they "are NOT the same thing". argus has one `verdicts-smallmix.json` answering 77 of 77
    claims across five batches; the name-pairing version called all five unread and offered to
    delete them."""
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    _batch(out, "cadence", ["EP13 fires hourly"], theme="cadence")
    _batch(out, "lifecycle", ["C23 is torn down on exit"], theme="lifecycle")
    _verdicts(out, "smallmix", ["EP13 fires hourly", "C23 is torn down on exit"])
    assert _undispatched_claims_leg(out / "project-map.json") is None


def test_batch_ten_does_not_absolve_batch_one(tmp_path):
    """F2, CRITICAL. `verdicts-behaviour-10.json` starts with `verdicts-behaviour-1`, so the glob
    `verdicts-behaviour-1*.json` matched it. Builds cut two-digit batch counts routinely (mcpolis
    24, reminderrepo 16), and the gate reported CLEAN over 39 unread claims."""
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    _batch(out, "behaviour-1", ["step one"], theme="behaviour")
    _batch(out, "behaviour-10", ["step ten"], theme="behaviour")
    _verdicts(out, "behaviour-10", ["step ten"])
    leg = _undispatched_claims_leg(out / "project-map.json")
    assert leg is not None, "batch 1 was answered by nobody"
    assert "1 of 2" in leg.blocking[0], leg.blocking[0]


def test_an_empty_verdict_file_is_not_an_answer(tmp_path):
    """F3. The name-pairing version could be satisfied by `touch`, with no record."""
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    _batch(out, "behaviour-1", ["step one"], theme="behaviour")
    (out / "verify" / "verdicts-behaviour-1.json").write_text("")
    assert _undispatched_claims_leg(out / "project-map.json") is not None
    (out / "verify" / "verdicts-behaviour-1.json").write_text("NOT JSON AT ALL")
    assert _undispatched_claims_leg(out / "project-map.json") is not None


def test_a_closer_appeal_is_not_a_vote(tmp_path):
    """`grounding.is_closer_row`: a row carrying a `verdict` field rules on an appeal, it does not
    vote. A batch answered only by the closer was still answered by no skeptic."""
    import json
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    _batch(out, "behaviour-1", ["step one"], theme="behaviour")
    (out / "verify" / "closer-1.json").write_text(json.dumps(
        {"grounding": [{"claim": "step one", "verdict": "uphold"}]}))
    assert _undispatched_claims_leg(out / "project-map.json") is not None


def test_the_theme_is_read_off_the_file_not_the_name(tmp_path):
    """F5. `claims-small.json` holds `theme: mixed` — the spelling `audit --json` uses. Parsing the
    name reported `small`, which appears in no theme count anywhere."""
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    _batch(out, "small", ["a stray claim"], theme="mixed")
    leg = _undispatched_claims_leg(out / "project-map.json")
    assert leg is not None
    assert "mixed" in leg.blocking[0] and "small" not in leg.blocking[0], leg.blocking[0]


def test_a_wave_batch_reports_its_theme_not_a_pair_of_shas(tmp_path):
    """F5. An update wave writes `claims-<from>-<to>-<theme>.json`; the name parse announced
    `a3f91c2-7b2e4d8-backbone` as the theme."""
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    _batch(out, "a3f91c2-7b2e4d8-backbone", ["C1 calls C2"], theme="backbone")
    leg = _undispatched_claims_leg(out / "project-map.json")
    assert leg is not None
    assert "a3f91c2" not in leg.blocking[0], leg.blocking[0]
    assert "backbone" in leg.blocking[0]


def test_the_message_names_themes_not_every_file(tmp_path):
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    for n in range(1, 25):
        _batch(out, f"behaviour-{n}", [f"step {n}"], theme="behaviour")
    leg = _undispatched_claims_leg(out / "project-map.json")
    assert leg is not None
    assert leg.blocking[0].count("behaviour") == 1, "24 files, one theme, said once"


def test_a_batch_with_no_readable_claims_is_skipped_not_accused(tmp_path):
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    (out / "verify" / "claims-broken.json").write_text("NOT JSON")
    assert _undispatched_claims_leg(out / "project-map.json") is None


def test_an_unbatched_build_pays_no_line(tmp_path):
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    assert _undispatched_claims_leg(out / "project-map.json") is None


def test_one_voted_claim_does_not_clear_a_whole_batch(tmp_path):
    """The gate's own exploit, found by review: `claims & answered` was non-empty intersection, so
    a hand-written verdict file of 24 rows — one claim lifted from each unread batch — moved
    mcpolis-rehearsal from BLOCKED to ADVISORIES with 925 of 949 claims still unread. Every claim
    must be voted."""
    from coyomap.finalize import _undispatched_claims_leg
    out = _verify(tmp_path)
    _batch(out, "behaviour-1", [f"step {n}" for n in range(40)], theme="behaviour")
    _verdicts(out, "behaviour-1", ["step 0"])
    assert _undispatched_claims_leg(out / "project-map.json") is not None
    _verdicts(out, "behaviour-1", [f"step {n}" for n in range(40)])
    assert _undispatched_claims_leg(out / "project-map.json") is None


def test_the_blocking_leg_reaches_the_verdict_and_the_exit_code():
    """The leg is only worth having if `build_report` turns it into BLOCKED and `main` exits 1.

    Every other test here calls the leg directly. Review deleted the single `build_report` line
    that registers it and all 115 of them still passed — the wiring was the untested part."""
    from coyomap import finalize
    root, map_path = make_repo()
    verify = root / ".coyomap" / "verify"
    verify.mkdir(parents=True, exist_ok=True)
    (verify / "claims-behaviour-1.json").write_text(json.dumps(
        {"theme": "behaviour", "claims": [{"claim": "UC44 warns the admin"}]}), encoding="utf-8")

    report = finalize.build_report(map_path, root, [])
    legs = [l for l in report.legs if l.name == "skeptic dispatch"]
    assert len(legs) == 1, [l.name for l in report.legs]
    assert report.verdict == "BLOCKED", report.verdict
    assert report.blocking_total >= 1
    assert finalize.main([str(map_path), "--repo", str(root)]) == 1

    (verify / "verdicts-behaviour-1.json").write_text(json.dumps(
        {"grounding": [{"claim": "UC44 warns the admin", "grounded": True, "skeptic": "b1"}]}),
        encoding="utf-8")
    again = finalize.build_report(map_path, root, [])
    assert [l for l in again.legs if l.name == "skeptic dispatch"] == []
    assert again.verdict != "BLOCKED", again.verdict


def test_prose_ten_does_not_absolve_prose_one(tmp_path):
    """F4. Rewiring the prose leg onto the shared helper carried the collision into it, and the
    coyomap map itself runs `prose-1` … `prose-10`."""
    from coyomap.finalize import _undispatched_prose_leg
    out = _verify(tmp_path)
    (out / "verify" / "prose-1.json").write_text("{}")
    (out / "verify" / "prose-10.json").write_text("{}")
    (out / "verify" / "verdicts-prose-10.json").write_text('{"x": 1}')
    leg = _undispatched_prose_leg(out / "project-map.json")
    assert leg is not None, "prose-1 was read by nobody"
    assert "1 of 2" in leg.advisory[0], leg.advisory[0]


def test_a_prose_voter_suffix_still_counts(tmp_path):
    from coyomap.finalize import _undispatched_prose_leg
    out = _verify(tmp_path)
    (out / "verify" / "prose-1.json").write_text("{}")
    (out / "verify" / "verdicts-prose-1-b.json").write_text('{"x": 1}')
    assert _undispatched_prose_leg(out / "project-map.json") is None


def test_an_empty_prose_verdict_is_not_a_review(tmp_path):
    from coyomap.finalize import _undispatched_prose_leg
    out = _verify(tmp_path)
    (out / "verify" / "prose-1.json").write_text("{}")
    (out / "verify" / "verdicts-prose-1.json").write_text("")
    assert _undispatched_prose_leg(out / "project-map.json") is not None


# --- the prose leg keys on a convention the method now states (adversarial review, 2026-09-02) ----
# It shipped keyed on `verdicts-prose-*.json` while nothing asked anyone to write that name, so it
# was an advisory no build could satisfy except by deleting its own batches.

def test_the_method_names_the_file_the_prose_leg_looks_for():
    from pathlib import Path
    method = (Path(__file__).resolve().parents[1] / "method.md").read_text(encoding="utf-8")
    assert "verdicts-prose-" in method, (
        "the prose leg reads a filename the method never asks anyone to write — an advisory whose "
        "only achievable remedy is 'delete the batches'")


def test_the_prose_leg_is_silent_when_the_verdicts_are_there(tmp_path):
    from coyomap.finalize import _undispatched_prose_leg
    out = tmp_path / ".coyomap"
    (out / "verify").mkdir(parents=True)
    (out / "verify" / "prose-1.json").write_text("{}")
    assert _undispatched_prose_leg(out / "project-map.json") is not None
    (out / "verify" / "verdicts-prose-1.json").write_text("{}")
    assert _undispatched_prose_leg(out / "project-map.json") is None


def test_no_write_does_not_point_at_the_file_it_left_alone(tmp_path, capsys):
    """It printed 'Full findings: finalize-report.md' — the stale one it deliberately did not
    overwrite — so a reader following the pointer read the previous build's disposition."""
    import io, contextlib
    from coyomap import finalize
    out = tmp_path / ".coyomap"
    (out / "build-fragments").mkdir(parents=True)
    (out / "project-map.json").write_text('{"format": "coyomap/1", "title": "t", "goal": "g"}')
    (out / "finalize-report.md").write_text("OLD REPORT")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        finalize.main([str(out / "project-map.json"), "--repo", str(tmp_path), "--no-write"])
    printed = buf.getvalue()
    assert (out / "finalize-report.md").read_text() == "OLD REPORT"
    assert "Full findings: " not in printed, printed[-400:]


# ── the tier the record was written at ──────────────────────────────────────────────────────────

def make_two_tier_map(tmp: str) -> Path:
    """A map whose behavioural claim surface is wider than its default one: two described
    components (the default tier) and one traced use case (three `behaviour` claims on top).
    The source files exist, so the validate leg has anchors to resolve."""
    root = Path(tmp)
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "g.py").write_text("def gate():\n    return 1\n", encoding="utf-8")
    (root / "src" / "s.py").write_text("def store():\n    return 2\n", encoding="utf-8")
    doc = {
        "format": FORMAT, "title": "T", "goal": "g",
        "roles": [{"id": "R1", "name": "Admin", "kind": "human"}],
        "components": [
            {"id": "C1", "name": "Gate", "purpose": "checks every call for a token",
             "files": ["src/g.py"], "source": "src/g.py:1"},
            {"id": "C2", "name": "Store", "purpose": "keeps the rows",
             "files": ["src/s.py"], "source": "src/s.py:1"}],
        "use_cases": [{"id": "UC1", "name": "Sign in", "actors": ["R1"],
                       "trigger": "the admin signs in", "outcome": "a session exists"}],
        "flows": [{"uc": "UC1", "title": "Sign in", "steps": [
            {"n": 1, "src": "R1", "dst": "C1", "phrase": "send the token", "where": "src/g.py:1"},
            {"n": 2, "src": "C1", "dst": "C2", "phrase": "store the session", "where": "src/s.py:1"}]}],
    }
    (root / ".coyomap").mkdir(exist_ok=True)
    p = root / ".coyomap" / "project-map.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def write_record(p: Path, live: set[str]) -> None:
    """The record `grounding write --map` leaves: pinned counts and the digest of the live surface
    it was computed at."""
    from coyomap.grounding import live_claims_digest
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["grounding"] = {"claims_total": len(live), "claims_challenged": len(live),
                        "claims_confirmed": len(live), "live_claims_digest": live_claims_digest(live)}
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_the_digest_is_checked_at_the_tier_the_record_was_written_at():
    """`grounding write --map` hashes the live surface at the pinned worklist's tier, and `finalize`
    re-hashed it at the default tier always. The first build that pinned a behavioural worklist got
    the mismatch advisory on a record that described its map exactly — 1782 claims hashed against
    833 compared — under a gate block counting the smaller surface. The tier is read off the digest
    itself, the audit leg runs at that tier, and a wrong-tier read says so instead of "moved"."""
    from coyomap.finalize import _audit_leg, _live_surfaces, _record_tier
    with tempfile.TemporaryDirectory() as tmp:
        p = make_two_tier_map(tmp)
        surfaces = _live_surfaces(p)
        assert surfaces is not None and surfaces[False] < surfaces[True], surfaces
        write_record(p, surfaces[True])
        assert _record_tier(p) is True
        leg = _audit_leg(p, None, behavioural=True)
        assert not [a for a in leg.advisory if "live_claims_digest" in a], leg.advisory
        assert f"{len(surfaces[True])} L2 claims" in (leg.note or ""), leg.note
        # read at the default tier, the same record is the false advisory the live build printed —
        # and the message now names the tier that does match
        wrong_tier = [a for a in _audit_leg(p, None).advisory if "live_claims_digest" in a]
        assert wrong_tier and "the tier compared at is not" in wrong_tier[0], wrong_tier
        # a record written at the default tier reads as such
        write_record(p, surfaces[False])
        assert _record_tier(p) is False
        assert not [a for a in _audit_leg(p, None).advisory if "live_claims_digest" in a]
        # a digest matching neither tier is a surface that MOVED, at either tier
        write_record(p, {"a claim this map never made"})
        assert _record_tier(p) is None
        moved = [a for a in _audit_leg(p, None).advisory if "live_claims_digest" in a]
        assert moved and "matches neither" in moved[0], moved


def test_build_report_counts_one_surface_the_one_the_record_hashed():
    """The gate block is what a commit message quotes: one surface, counted and hashed alike."""
    from coyomap.finalize import _live_surfaces
    with tempfile.TemporaryDirectory() as tmp:
        p = make_two_tier_map(tmp)
        surfaces = _live_surfaces(p)
        assert surfaces is not None
        write_record(p, surfaces[True])
        rep = finalize.build_report(p, Path(tmp), [])
        audit = next(leg for leg in rep.legs if leg.name == "audit")
        assert f"{len(surfaces[True])} L2 claims" in (audit.note or ""), audit.note
        assert not [a for a in audit.advisory if "live_claims_digest" in a], audit.advisory


def test_the_drift_leg_counts_coverage_at_the_records_tier():
    """`challenged 817 of 833` sat under an audit line counting 1782 on the first behavioural build:
    the drift leg's denominator was the default tier always. It follows the record's tier now."""
    from coyomap.finalize import _drift_leg, _live_surfaces
    with tempfile.TemporaryDirectory() as tmp:
        p = make_two_tier_map(tmp)
        surfaces = _live_surfaces(p)
        assert surfaces is not None
        vp = make_verdicts_file(tmp, sorted(surfaces[False]))
        narrow, wide = len(surfaces[False]), len(surfaces[True])
        assert f"of {narrow} worklist" in (_drift_leg(p, Path(tmp), [vp]).note or "")
        assert f"of {wide} worklist" in (_drift_leg(p, Path(tmp), [vp], behavioural=True).note or "")
        write_record(p, surfaces[True])
        rep = finalize.build_report(p, Path(tmp), [vp])
        drift = next(leg for leg in rep.legs if leg.name == "anchor-drift (verdict-based)")
        assert f"of {wide} worklist" in (drift.note or ""), drift.note


def test_the_gate_block_says_which_unvoted_claims_were_pinned_and_never_challenged():
    """Under a partial pass most of the shipped map's unvoted claims were PINNED and simply not
    challenged. The 2026-09-08 build's gate block called all 965 "minted after the worklist was
    pinned" when 949 had been on the worklist from the start."""
    from coyomap.finalize import _grounding_line
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.json"
        rec = {"claims_total": 1791, "claims_challenged": 842, "claims_confirmed": 823,
               "claims_refuted": 19, "claims_unverifiable": 0, "claims_superseded": 25,
               "claims_added_since": 16, "claims_live_challenged": 817, "live_claims_digest": "x"}
        p.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g", "grounding": rec}),
                     encoding="utf-8")
        line = _grounding_line(p)
        assert "817 of 1782" in line and "965 do not" in line, line
        assert "949 were pinned and never challenged" in line, line
        assert "16 were minted or reworded" in line, line
        # a complete pass keeps the one-part sentence
        rec.update({"claims_challenged": 1791, "claims_live_challenged": 1766})
        p.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g", "grounding": rec}),
                     encoding="utf-8")
        line = _grounding_line(p)
        assert "16 do not" in line and "never challenged" not in line, line


def test_the_gate_block_carries_the_advisory_disposition_counts():
    """The gate block is what a commit quotes, and its two-way wording ("recordable / no escape")
    is how one commit filed two UNANSWERED rows as carried. The report's own disposition rides
    along, and its counts cover every advisory."""
    import re as _re
    root, p = make_repo(components=3)
    report = finalize.build_report(p, root, [])
    block = finalize.gate_block(report, report.map_sha256)
    if not report.advisory_total:
        assert "Advisory disposition:" not in block
        return
    line = next((ln for ln in block.splitlines() if ln.startswith("Advisory disposition:")), "")
    assert line, block
    counted = sum(int(n) for n in _re.findall(r": (\d+)", line.split(". An UNANSWERED")[0]))
    assert counted == report.advisory_total, (line, report.advisory_total)


def test_the_disposition_reaches_STDOUT_beside_the_verdict_line(capsys):
    """It was written to the report file and to the gate block, and to nothing a build could see.

    At turn 560 of the 2026-09-13 reminderrepo build the lead grepped `ship`'s stdout for
    `finalize: ADVISORIES\\|Advisory disposition`; only the count line matched, the count was 14
    before and after, and the next turn concluded "both mine are answered" while the report beside
    it said `UNSURE: 1`. The counts move when an advisory is answered; the total does not."""
    root, p = make_repo(components=3)
    report = finalize.build_report(p, root, [])
    assert report.advisory_total, "this fixture must raise advisories or the test proves nothing"
    finalize.main([str(p), "--repo", str(root)])
    out = capsys.readouterr().out
    line = next((ln for ln in out.splitlines() if "Advisory disposition:" in ln), "")
    assert line, out
    assert line.startswith("finalize: "), ("it must sit with the other `finalize:` lines a build "
                                           "greps for:\n" + line)
    assert any(f"{k}:" in line for k in finalize._DISPOSITION_ORDER), line
    # The counts, NOT a replacement for the file the guidance sends readers to.
    assert "finalize-report.md" in line, line


# --- the component budgets summed against what shipped (retro 2026-09-08, row 28) ---------------

def _with_budgets(root: Path, budgets: dict[str, int]) -> None:
    verify = root / ".coyomap" / "verify"
    verify.mkdir(parents=True, exist_ok=True)
    (verify / "budgets.json").write_text(json.dumps({"harvest": budgets}), encoding="utf-8")


def _budget_leg_of(report) -> finalize.Leg | None:
    return next((leg for leg in report.legs if leg.name == "component budget"), None)


def test_the_budget_leg_sums_the_harvest_briefs_against_what_shipped():
    """60 budgeted, 114 shipped, every slice over, and the whole-map reading arrived ~450 turns
    later. The sum is held to the same ±40 % band each slice is held to."""
    root, p = make_repo(components=10)
    _with_budgets(root, {"t1": 3, "t2": 2})
    leg = _budget_leg_of(finalize.build_report(p, root, []))
    assert leg is not None and leg.ran
    assert leg.note and leg.note.startswith("10 shipped / 5 budgeted across 2 brief(s), band 3-7")
    assert leg.advisory and "10 component(s) shipped against 5 budgeted" in leg.advisory[0]
    assert not leg.blocking, "a budget is an aim; the leg advises, never blocks"


def test_a_map_inside_the_summed_band_gets_a_quiet_budget_leg():
    root, p = make_repo(components=10)
    _with_budgets(root, {"t1": 5, "t2": 5})
    leg = _budget_leg_of(finalize.build_report(p, root, []))
    assert leg is not None and leg.ran and not leg.advisory, leg


def test_no_recorded_budgets_means_no_budget_leg():
    """Absent rather than silently clean: a build that filled its briefs by hand recorded nothing."""
    root, p = make_repo(components=10)
    assert _budget_leg_of(finalize.build_report(p, root, [])) is None


def _budget_verdict(root: Path, p: Path, text: str) -> tuple[finalize.Leg | None, str]:
    verify = root / ".coyomap" / "verify"
    verify.mkdir(parents=True, exist_ok=True)
    (verify / "budgets.json").write_text(text, encoding="utf-8")
    report = finalize.build_report(p, root, [])
    return _budget_leg_of(report), report.verdict


def test_an_unreadable_budgets_file_advises_and_never_blocks():
    """A broken telemetry file must not turn a clean map into INCOMPLETE: the first version of
    this leg returned FAILED on bad JSON and crashed on a list where it expected a dict."""
    root, p = make_repo(components=10)
    for text in ("not json", '{"harvest": [1, 2]}', '{"harvest": {"t1": "six"}}'):
        leg, verdict = _budget_verdict(root, p, text)
        assert leg is not None and leg.ran and not leg.blocking, (text, leg)
        assert verdict not in ("INCOMPLETE", "BLOCKED"), (text, verdict)


def test_a_brief_with_no_numeric_budget_is_counted_not_dropped():
    root, p = make_repo(components=10)
    leg, _ = _budget_verdict(root, p, '{"harvest": {"t1": 5, "t2": 5, "t3": null}}')
    assert leg is not None and "1 brief(s) with no numeric budget (t3)" in (leg.note or ""), leg


# --- the refutation gate must SAY what it stopped firing on (adversarial review, 2026-09-14) -----
# A refutation the closer REJECTED leaves `surviving_refutations`, and the report left with it: the
# same map went `BLOCKED — 1 blocking` to `ADVISORIES — 0 blocking` with "refuted", "appeal" and
# "closer" appearing nowhere in the report, the gate block or the commit message.

def _map_with_a_refuted_claim(tmp: Path) -> tuple[Path, Path, Path]:
    """A repo whose one component description is refuted, plus a skeptics file for it."""
    root, p = make_repo()
    doc = json.loads(p.read_text(encoding="utf-8"))
    claim = (f"Component C1 ({doc['components'][0]['name']}) is described as: "
             f"{doc['components'][0]['purpose']}")
    verify = root / ".coyomap" / "verify"
    verify.mkdir(parents=True, exist_ok=True)
    v = verify / "verdicts-desc-1.json"
    v.write_text(json.dumps({"grounding": [
        {"claim": claim, "grounded": False, "evidence": "src/a.py:1", "skeptic": "desc-1",
         "note": "it does not take the ask"}]}), encoding="utf-8")
    c = verify / "closer-agent-1.json"
    c.write_text(json.dumps({"grounding": [
        {"claim": claim, "verdict": "reject", "grounded": True, "evidence": "src/a.py:2",
         "skeptic": "closer-1", "note": "line 2 does take the ask; the skeptic read line 1"}]}),
        encoding="utf-8")
    return root, p, verify


def test_a_refutation_settled_on_appeal_is_disclosed_not_erased(tmp_path):
    root, p, verify = _map_with_a_refuted_claim(tmp_path)
    v, c = verify / "verdicts-desc-1.json", verify / "closer-agent-1.json"
    blocked = finalize.build_report(p, root, [v])
    assert blocked.blocking_total == 1, "without the appeal the gate must block"
    passed = finalize.build_report(p, root, [v, c])
    assert passed.blocking_total == 0, "a closer rejection clears it"
    leg = next(l for l in passed.legs if l.name == "grounding refutations")
    assert leg.note is not None and "1 settled on appeal" in leg.note, leg.note
    text = finalize.format_report(passed) + finalize.gate_block(passed, passed.map_sha256)
    assert "CLOSER REJECTED" in text, text
    assert "the skeptic read line 1" in text, text
    # ...and it is filed as a disclosure, never as an escape nobody took
    where = {a: d for d, _h, a in finalize.advisory_disposition(p, passed)}
    appeal = next(a for a in where if "CLOSER REJECTED" in a)
    assert where[appeal] == "disclosure", where[appeal]


def test_the_commit_line_states_what_went_to_appeal(tmp_path):
    from coyomap.finalize import _grounding_line
    root, p, _verify = _map_with_a_refuted_claim(tmp_path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["grounding"] = {"claims_total": 1, "claims_challenged": 1, "claims_confirmed": 0,
                        "claims_refuted": 1, "claims_unverifiable": 0,
                        "closer_rejected": 1, "closer_upheld": 0, "closer_unsure": 0}
    p.write_text(json.dumps(doc), encoding="utf-8")
    line = _grounding_line(p)
    assert "1 appeal row(s)" in line and "1 reject" in line, line
    assert "an appeal is not a vote" in line.lower(), line
    assert "disagree" not in line, "no dispute here, so no dispute clause: " + line
    # A DISPUTED claim must never read as a settlement: one uphold and one reject on ONE refutation
    # used to print "2 refutation(s) went to appeal — 1 rejected, so the map keeps the claim".
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["grounding"].update({"closer_upheld": 1, "closer_disputed": 1})
    p.write_text(json.dumps(doc), encoding="utf-8")
    disputed = _grounding_line(p)
    assert "2 appeal row(s)" in disputed, disputed
    assert "refutation(s) went to appeal" not in disputed, disputed
    assert "1 claim(s) drew appeals that DISAGREE" in disputed, disputed
    assert "the refutation still stands" in disputed, disputed


# --- an access claim confirmed over a dissent goes to a closer (retro 2026-09-30, finding 3) ------
# BR23's sites were confirmed 2-1 on the 2026-09-30 mcpolis build; all three voters wrote the same
# counterexample and the code supported the dissent. The two dissent rows were dropped from the
# closer's brief by hand, and the rule shipped `verified`. Nothing counted a dissent the majority
# outvoted, so nothing could say it had not been heard.

def make_access_dissent_repo(closer_word: str | None,
                             access: bool = True) -> tuple[Path, Path, list[Path], str]:
    """A map whose rule BR1 is confirmed 2-1 by three skeptics, with the closer's ruling on the
    dissent when `closer_word` names one. Returns (root, map, verdict files, the claim)."""
    from coyomap.audit_model import rule_site_claim
    root, p = make_repo()
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["rules"] = [{"id": "BR1", "name": "No token, no entry",
                     "statement": "A caller with no token is refused.", "access": access,
                     "risk": "impersonation",
                     "sites": [{"where": "src/a.py:2", "why": "Rejects the tokenless caller."}]}]
    p.write_text(json.dumps(doc), encoding="utf-8")
    claim = rule_site_claim("A caller with no token is refused.", "src/a.py:2",
                            "Rejects the tokenless caller.")
    verify = root / ".coyomap" / "verify"
    verify.mkdir()
    votes = [{"claim": claim, "grounded": g, "evidence": "src/a.py:2", "skeptic": who,
              "note": "a caller removed another way keeps passing" if g is False else "it refuses"}
             for g, who in ((True, "security-1-a"), (True, "security-1-b"), (False, "security-1-c"))]
    files = [verify / "verdicts-security-1.json"]
    files[0].write_text(json.dumps({"grounding": votes}), encoding="utf-8")
    if closer_word:
        grounded = {"uphold": False, "reject": True, "unsure": "unverifiable"}[closer_word]
        files.append(verify / "closer-c1.json")
        files[1].write_text(json.dumps({"grounding": [
            {"id": "security-1#3", "claim": claim, "verdict": closer_word, "grounded": grounded,
             "evidence": "src/a.py:2", "skeptic": "c1", "note": "read the line"}]}),
            encoding="utf-8")
    return root, p, files, claim


def test_an_access_dissent_no_closer_heard_blocks() -> None:
    _root, p, files, claim = make_access_dissent_repo(None)
    leg = finalize._refutations_leg(p, files)
    assert any(b.startswith(claim) and "no closer has ruled on the dissent" in b
               for b in leg.blocking), leg.blocking


def test_a_closer_that_rejects_the_dissent_settles_it() -> None:
    _root, p, files, _claim = make_access_dissent_repo("reject")
    leg = finalize._refutations_leg(p, files)
    assert not leg.blocking, leg.blocking


def test_a_closer_that_upholds_the_dissent_makes_it_a_refutation_the_map_still_carries() -> None:
    _root, p, files, claim = make_access_dissent_repo("uphold")
    leg = finalize._refutations_leg(p, files)
    assert [b for b in leg.blocking if b.startswith(claim) and "UPHELD on appeal" in b], leg.blocking


def test_a_dissent_the_closer_could_not_settle_is_said_not_blocked() -> None:
    _root, p, files, _claim = make_access_dissent_repo("unsure")
    leg = finalize._refutations_leg(p, files)
    assert not leg.blocking, leg.blocking
    assert any("could not settle" in a for a in leg.advisory), leg.advisory


def test_a_dissent_on_a_claim_that_is_not_about_access_does_not_block() -> None:
    _root, p, files, _claim = make_access_dissent_repo(None, access=False)
    leg = finalize._refutations_leg(p, files)
    assert not leg.blocking, leg.blocking


# --- a credential in the files the commit line force-adds (retro 2026-09-30, finding 6) ---------

def test_a_key_shaped_value_in_a_fragment_blocks_and_withholds_the_commit_line() -> None:
    """The value is built from filler at run time (see tests/test_credentials.py): this file holds
    no credential-shaped value."""
    import contextlib
    import io
    root, p = make_repo()
    frags = root / ".coyomap" / "build-fragments"
    frags.mkdir()
    value = "AK" + "IA" + "Q" * 16
    (frags / "extras.json").write_text(json.dumps({"extras": [
        {"heading": "Notes", "body": f"The deploy config sets {value} for the bucket."}]}),
        encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = finalize.main([str(p), "--repo", str(root), "--no-write"])
    said = out.getvalue()
    assert code == 1, said
    assert "extras.json: line 1 (AWS access key id)" in said, said
    assert value not in said, "the scan printed the value it found"
    assert "NO commit line" in said and "git add -f" not in said, said


def test_a_key_in_a_file_no_commit_takes_is_an_advisory_and_the_commit_line_stands() -> None:
    """The findings, the build state and the findings report never reach a commit: the map folder's
    `.gitignore` keeps them out and the `git add -f` line names none of them. A key-shaped value
    there names its file and asks for the line to go; it does not withhold the commit line. The
    value is built from filler at run time."""
    root, p = make_repo()
    value = "gh" + "p_" + "z" * 40
    out_dir = root / ".coyomap"
    (out_dir / "findings").mkdir()
    local = [out_dir / "findings" / "harvest-1.jsonl", out_dir / buildstate.STATE_NAME,
             out_dir / buildstate.PREV_NAME, out_dir / "findings-report.md"]
    for f in local:
        f.write_text(f"a line holding {value}\n", encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = finalize.main([str(p), "--repo", str(root), "--no-write"])
    leg = next(l for l in finalize.build_report(p, root, []).legs if l.name == "credential scan")
    said = out.getvalue()
    assert code == 0, said
    assert leg.blocking == [], leg.blocking
    named = sorted(row.split(": line 1 (GitHub token) — ", 1)[0] for row in leg.advisory)
    assert named == sorted(str(f) for f in local), leg.advisory
    assert all("Remove that line from the file" in row for row in leg.advisory), leg.advisory
    assert "git add -f" in said and "NO commit line" not in said, said
    assert value not in said, "the scan printed the value it found"


def test_a_key_in_a_committed_file_beside_one_no_commit_takes_still_blocks() -> None:
    root, p = make_repo()
    value = "gh" + "p_" + "z" * 40
    verify = root / ".coyomap" / "verify"
    verify.mkdir()
    (verify / "verdicts-backbone-1.json").write_text(json.dumps({"grounding": [
        {"claim": "c", "grounded": True, "evidence": "src/a.py:1", "note": value}]}),
        encoding="utf-8")
    (root / ".coyomap" / "findings").mkdir()
    (root / ".coyomap" / "findings" / "harvest-1.jsonl").write_text(value, encoding="utf-8")
    leg = next(l for l in finalize.build_report(p, root, []).legs if l.name == "credential scan")
    assert [row.split(":", 1)[0] for row in leg.blocking] == [str(verify / "verdicts-backbone-1.json")]
    assert [row.split(":", 1)[0] for row in leg.advisory] == [
        str(root / ".coyomap" / "findings" / "harvest-1.jsonl")], leg.advisory


def test_a_clean_map_keeps_its_commit_line() -> None:
    import contextlib
    import io
    root, p = make_repo()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        finalize.main([str(p), "--repo", str(root), "--no-write"])
    assert "git add -f" in out.getvalue()


# --- a refuted walk step is reported, not blocked (retro 2026-09-30, finding 1) -----------------
# The gate could not place a flow-step claim at all, so it answered "0 refuted claim(s) still in the
# map" while `grounding report` listed 3. It sees them now, and REPORTS them without blocking:
# blocking waits for the closer's ruling on disputed appeals (finding 15), or it would have stopped
# that build on two steps whose appeals disagree.

def make_refuted_step_repo(closer_word: str | None) -> tuple[Path, Path, list[Path]]:
    """The finalize fixture map with its step 2 refuted by one skeptic, and the closer's word on it
    when `closer_word` names one."""
    root, p = make_repo()
    verify = root / ".coyomap" / "verify"
    verify.mkdir()
    claim = "UC1 step 2: C1 → C2 — forwards"
    files = [verify / "verdicts-behaviour-1.json"]
    files[0].write_text(json.dumps({"grounding": [
        {"claim": claim, "grounded": False, "evidence": "src/a.py:2", "skeptic": "behaviour-1",
         "note": "it answers, it forwards nothing"}]}), encoding="utf-8")
    if closer_word:
        files.append(verify / "closer-c1.json")
        files[1].write_text(json.dumps({"grounding": [
            {"id": "behaviour-1#1", "claim": claim, "verdict": closer_word,
             "grounded": {"uphold": False, "reject": True}[closer_word],
             "evidence": "src/a.py:2", "skeptic": "c1", "note": "read the line"}]}),
            encoding="utf-8")
    return root, p, files


def test_a_refuted_step_still_in_the_map_is_reported_and_does_not_block():
    _root, p, files = make_refuted_step_repo(None)
    leg = finalize._refutations_leg(p, files)
    assert not leg.blocking, leg.blocking
    assert any("UC1 step 2: C1 → C2 — forwards" in a and "reported, not blocking" in a
               for a in leg.advisory), leg.advisory


def test_a_step_the_closer_rejected_is_disclosed_as_settled_on_appeal():
    _root, p, files = make_refuted_step_repo("reject")
    leg = finalize._refutations_leg(p, files)
    assert not leg.blocking
    assert any("CLOSER REJECTED" in a and "UC1 step 2" in a for a in leg.advisory), leg.advisory


# --- finalize can settle every row it files UNSURE (retro 2026-09-30, finding 13) ------------------
# The budget leg read no record, two disclosures were missed by the disclosure pattern, an access
# path was never UNRECORDED, and anchor-drift's notes about the recorded lines were dropped: none of
# the 3 UNSURE rows on the 2026-09-30 mcpolis report could ever be settled.

def make_budget_repo(record: str | None) -> tuple[Path, Path]:
    """10 components against 5 budgeted, with `record` under 'Balance exceptions' when given."""
    root, p = make_repo(components=10)
    _with_budgets(root, {"t1": 3, "t2": 2})
    if record is not None:
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["extras"] = [{"heading": "Balance exceptions", "body": record}]
        p.write_text(json.dumps(doc), encoding="utf-8")
    return root, p


def test_a_budget_record_naming_both_counts_settles_the_budget_leg():
    root, p = make_budget_repo("component-budget: 10 shipped of 5 budgeted — the slices were "
                               "cut before the adapters were counted")
    report = finalize.build_report(p, root, [])
    leg = _budget_leg_of(report)
    assert leg is not None and leg.advisory and leg.advisory[0].startswith("DISCLOSURE"), leg
    rows = [d for d, _h, a in finalize.advisory_disposition(p, report) if "shipped against" in a]
    assert rows == ["disclosure"], rows


def test_a_bare_granularity_line_does_not_settle_the_budget_leg():
    root, p = make_budget_repo("granularity: the map is this size on purpose")
    report = finalize.build_report(p, root, [])
    rows = [d for d, _h, a in finalize.advisory_disposition(p, report) if "shipped against" in a]
    assert rows == ["UNRECORDED"], rows


def test_the_silenced_lines_disclosure_and_a_lost_access_file_are_filed_by_what_they_are():
    silenced = ("46 advisory line(s) are silenced by this map's recorded lines, which sit under: "
                "Access baseline exceptions, Balance exceptions.")
    lost = ("1 of 2 file(s) that held ACCESS enforcement in 0001/project-map.json are named by NO "
            "access rule in this map. Record '<path>: <why>' under an 'Access baseline exceptions' "
            "extras heading for each one that is deliberate.")
    disclosed = ("DISCLOSURE, not a request: 1 of 2 file(s) that held ACCESS enforcement are still "
                 "named, and the other 1 are recorded under 'Access baseline exceptions'.")
    assert _disposition_for(None, silenced)[0] == "disclosure"
    assert _disposition_for(None, lost)[0] == "UNRECORDED"
    assert _disposition_for(None, disclosed)[0] == "disclosure"


def test_the_drift_leg_carries_a_recorded_line_that_matched_no_finding():
    root, p = make_repo()
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["extras"] = [{"heading": "Drift exceptions",
                      "body": "anchor-drift `C9 calls C8`: the call moved into a helper on purpose"}]
    p.write_text(json.dumps(doc), encoding="utf-8")
    verify = root / ".coyomap" / "verify"
    verify.mkdir()
    v = verify / "verdicts-backbone-1.json"
    v.write_text(json.dumps({"grounding": [{"claim": "C1 calls C2", "grounded": True,
                                            "evidence": "src/a.py:2", "skeptic": "b1"}]}),
                 encoding="utf-8")
    leg = finalize._drift_leg(p, root, [v])
    assert any("recorded drift exception(s) matched no finding" in a for a in leg.advisory), leg


# --- a rule re-worded after the vote is not "never challenged" (retro 2026-09-30, finding 38) -----
# finalize told the commit that access rules BR1 and BR21 "were never challenged", while all 11 of
# their current sites carried 3 votes each under the wording before a reconcile corrected it.

def make_reworded_rule_repo(elements: list[str], anchor: str) -> tuple[Path, Path, Path]:
    """BR1 (access, one site at src/a.py:2), and a pinned worklist whose one claim, an OLDER wording
    of a rule, was voted on at `anchor` for `elements`."""
    root, p = _map_with_rule(access=True, confidence="inferred")
    older = rule_site_claim("A listener reaches its own organization.", anchor, "the refusal")
    verify = root / ".coyomap" / "verify"
    verify.mkdir(parents=True, exist_ok=True)
    (verify / "worklist.json").write_text(json.dumps({"worklist": [
        {"claim": older, "anchor": anchor, "elements": elements, "theme": "security"}]}),
        encoding="utf-8")
    v = make_verdicts(root, "verdicts-security-1-a.json",
                      [{"claim": older, "grounded": True, "evidence": "src/a.py:2"}])
    return root, p, v


def _access_advisory(root: Path, p: Path, v: Path) -> str:
    assert finalize.main([str(p), "--repo", str(root), "--verdicts", str(v)]) == 0
    doc = json.loads((root / ".coyomap" / "finalize-report.json").read_text())
    leg = next(l for l in doc["legs"] if l["name"] == "grounding refutations")
    return leg["advisory"][0]


def test_an_access_rule_voted_on_under_an_older_wording_is_said_to_be_reworded():
    root, p, v = make_reworded_rule_repo(["BR1"], "src/a.py:2")
    first = _access_advisory(root, p, v)
    assert "re-worded after the vote" in first and "BR1" in first, first
    assert "1 of 1 site(s) voted under the older wording" in first, first
    assert "never challenged" not in first, first


def test_an_older_vote_for_another_rule_or_another_line_still_reads_never_challenged():
    for elements, anchor in ((["BR9"], "src/a.py:2"), (["BR1"], "src/a.py:3")):
        root, p, v = make_reworded_rule_repo(elements, anchor)
        first = _access_advisory(root, p, v)
        assert "ACCESS rule(s) were never challenged" in first, (elements, anchor, first)


# --- after the review of findings 1 and 3: a dissent survives a moved line, a role's claim counts,
# and the refutations verb's exit code says what finalize blocks on ----------------------------------

def _refutations_exit(p: Path, files: list[Path]) -> int:
    argv = ["refutations", "--map", str(p), "--json"]
    for f in files:
        argv += ["--verdicts", str(f)]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return grounding.main(argv)


def test_an_access_dissent_keeps_blocking_after_its_line_moves() -> None:
    """`fix apply-drift` accepts a 2-1 majority's line inside `ship`: moved, the claim no longer
    matched its votes, and the dissent left the gate."""
    _root, p, files, claim = make_access_dissent_repo(None)
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["rules"][0]["sites"][0]["where"] = "src/a.py:3"
    p.write_text(json.dumps(doc), encoding="utf-8")
    leg = finalize._refutations_leg(p, files)
    assert any(b.startswith(claim) and "no closer has ruled on the dissent" in b
               for b in leg.blocking), leg.blocking


def test_an_access_dissent_keeps_blocking_after_its_statement_is_reworded() -> None:
    root, p, files, claim = make_access_dissent_repo(None)
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["rules"][0]["statement"] = "A caller without a token is refused."
    p.write_text(json.dumps(doc), encoding="utf-8")
    (root / ".coyomap" / "verify" / "worklist.json").write_text(json.dumps({"worklist": [
        {"claim": claim, "anchor": "src/a.py:2", "elements": ["BR1"], "theme": "security"}]}),
        encoding="utf-8")
    leg = finalize._refutations_leg(p, files)
    assert any(b.startswith(claim) for b in leg.blocking), leg.blocking


def test_a_split_vote_on_a_role_that_may_do_everything_another_may_do_blocks() -> None:
    root, p = make_repo()
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["roles"] = [{"id": "R1", "name": "Owner",
                     "relations": [{"kind": "includes", "role": "R2"}]},
                    {"id": "R2", "name": "Contact"}]
    p.write_text(json.dumps(doc), encoding="utf-8")
    claim = role_inclusion_claim("Owner", "Contact")
    verify = root / ".coyomap" / "verify"
    verify.mkdir(parents=True, exist_ok=True)
    v = verify / "verdicts-security-1.json"
    v.write_text(json.dumps({"grounding": [
        {"claim": claim, "grounded": g, "evidence": "src/a.py:2", "skeptic": who, "note": "n"}
        for g, who in ((True, "a"), (True, "b"), (False, "c"))]}), encoding="utf-8")
    leg = finalize._refutations_leg(p, [v])
    assert any(b.startswith(claim) for b in leg.blocking), leg.blocking
    assert _refutations_exit(p, [v]) == 1


def test_a_dissent_the_closer_rejected_is_neither_blocked_nor_advised() -> None:
    _root, p, files, _claim = make_access_dissent_repo("reject")
    leg = finalize._refutations_leg(p, files)
    assert not leg.blocking and not any("dissent" in a.lower() for a in leg.advisory), leg


def test_the_refutations_verb_exits_1_on_an_unheard_access_dissent() -> None:
    _root, p, files, _claim = make_access_dissent_repo(None)
    assert _refutations_exit(p, files) == 1


def test_the_refutations_verb_exits_0_when_only_a_reported_step_survives() -> None:
    _root, p, files = make_refuted_step_repo(None)
    assert _refutations_exit(p, files) == 0



def test_a_key_in_a_dissent_note_never_reaches_the_report() -> None:
    """Review of finding 6: the credential leg blocked on the verdict file, and the same report
    printed the dissent note, value and all. The value is built from filler at run time."""
    value = "AK" + "IA" + "Z" * 16
    root, p, files, _claim = make_access_dissent_repo(None)
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    for row in doc["grounding"]:
        if row["grounded"] is False:
            row["note"] = f"the config holds {value} for the caller"
    files[0].write_text(json.dumps(doc), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        finalize.main([str(p), "--repo", str(root), "--verdicts", *[str(f) for f in files]])
    written = "".join((root / ".coyomap" / f"finalize-report.{ext}").read_text(encoding="utf-8")
                      for ext in ("md", "json"))
    assert value not in out.getvalue() and value not in written
    assert "credential-shaped value" in written



# --- after the review of finding 13 ---------------------------------------------------------------

def test_a_budget_line_with_the_right_numbers_in_another_sentence_does_not_settle() -> None:
    for record in ("component-budget: 5 budgeted and 10 shipped, because the slices were cut early",
                   "component-budget: 11 shipped of 6 budgeted, because the slices were cut early"):
        root, p = make_budget_repo(record)
        report = finalize.build_report(p, root, [])
        rows = [d for d, _h, a in finalize.advisory_disposition(p, report)
                if "shipped against" in a]
        assert rows == ["UNRECORDED"], (record, rows)


def test_the_budget_template_followed_word_for_word_settles_the_leg_and_draws_no_advisory() -> None:
    root, p = make_budget_repo(None)
    report = finalize.build_report(p, root, [])
    leg = _budget_leg_of(report)
    assert leg is not None and leg.advisory and "\u2014" not in leg.advisory[0].split("record")[1]
    root, p = make_budget_repo("component-budget: 10 shipped of 5 budgeted, because the slices "
                               "were cut before the adapters were counted")
    report = finalize.build_report(p, root, [])
    assert [d for d, _h, a in finalize.advisory_disposition(p, report)
            if "shipped against" in a] == ["disclosure"]


def test_the_other_silenced_lines_wording_is_a_disclosure() -> None:
    changed = ("3 advisory line(s) read differently because of this map's recorded lines, which "
               "sit under: Sweep debt.")
    assert _disposition_for(None, changed)[0] == "disclosure"


def test_an_inert_drift_record_and_an_unread_excuse_are_carried() -> None:
    inert = ("1 recorded drift exception(s) matched no finding: `C9 calls C8` — the anchor was "
             "fixed or the claim changed.")
    unread = (f"2 of 3 access path(s) {finalize.UNREAD_EXCUSES}: the lead's transcript (lead.jsonl) "
              f"shows no tool call reading a.py; b.py.")
    assert _disposition_for(None, inert)[0] == "carried (no escape)"
    assert _disposition_for(None, unread)[0] == "carried (no escape)"


def test_a_note_on_the_recorded_lines_is_not_counted_as_a_drifted_anchor() -> None:
    root, p = make_repo()
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["extras"] = [{"heading": "Drift exceptions",
                      "body": "anchor-drift `C9 calls C8`: the call moved into a helper on purpose"}]
    p.write_text(json.dumps(doc), encoding="utf-8")
    verify = root / ".coyomap" / "verify"
    verify.mkdir()
    v = verify / "verdicts-backbone-1.json"
    v.write_text(json.dumps({"grounding": [{"claim": "C1 calls C2", "grounded": True,
                                            "evidence": "src/a.py:2", "skeptic": "b1"}]}),
                 encoding="utf-8")
    leg = finalize._drift_leg(p, root, [v])
    assert leg.note is not None and leg.note.startswith("no drifted anchors"), leg.note


# --- a list survives `head`, `tail` and `cut` (retro 2026-10-07, finding 1) ------------------------
# The access-baseline advisory was ONE line of 6,740 characters on the 2026-10-07 mcpolis build: a
# `cut -c1-500` left 1 of its 20 lost files legible, and 6 previous access rules shipped lost.

def make_lost_access_maps(lost: int) -> tuple[dict, dict]:
    """A previous map whose access rules hold a site in each of `lost` files, each claim as long as a
    real one, and a current map whose one access rule names none of those files."""
    before = {"format": "coyomap-map", "title": "t", "goal": "g", "rules": [
        {"id": f"BR{i}", "access": True, "risk": "a member of another team reads the record",
         "statement": f"Only a member of the owning team may read record kind {i}, whatever "
                      f"filter the caller passed",
         "sites": [{"where": f"src/auth/guard_{i}.py:{10 + i}",
                    "why": "refuses a caller outside the team before the read reaches the store"}]}
        for i in range(1, lost + 1)]}
    return before, _NO_AUTH


def make_lead_transcript(td: Path, opened: list[str]) -> Path:
    """A lead transcript whose only tool calls are `Read`s of `opened`."""
    f = td / "lead.jsonl"
    f.write_text("".join(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": str(td / p)}}]}}) + "\n"
        for p in opened), encoding="utf-8")
    return f


def lines_naming(text: str, path: str) -> list[str]:
    """The lines of `text` that hold `path`."""
    return [ln for ln in text.splitlines() if path in ln]


def test_the_access_list_puts_its_count_on_a_short_first_line_and_each_file_on_its_own():
    before, after = make_lost_access_maps(3)
    with tempfile.TemporaryDirectory() as td:
        report = _finalize_with_baseline(Path(td), before, after)
        rows = finalize.advisory_disposition(Path(td) / "after.json", report)
    text = next(l for l in report.legs if l.name == "access baseline").advisory[0]
    first = text.splitlines()[0]
    assert first.startswith("3 of 3 file(s) that held ACCESS enforcement in "), first
    assert len(first) < 200, f"{len(first)} characters: {first}"
    for i in (1, 2, 3):
        own = lines_naming(text, f"src/auth/guard_{i}.py")
        assert len(own) == 1 and own[0].startswith(f"  - src/auth/guard_{i}.py held BR{i} "), (
            i, text)
    # The disposition table finds the advisory and its heading by substring, in the whole text.
    assert [(d, h) for d, h, a in rows if a == text] == [
        ("UNRECORDED", finalize.ACCESS_BASELINE_EXCEPTIONS_HEADING)], rows


def test_the_excused_access_lists_put_each_file_on_its_own_line():
    """The disclosure of the recorded files and the count of those nobody opened carry the same
    list, so they take the same shape."""
    before, after = make_lost_access_maps(3)
    after = {**after, "extras": [{"heading": finalize.ACCESS_BASELINE_EXCEPTIONS_HEADING,
                                  "body": "\n".join(f"src/auth/guard_{i}.py: the team check moved "
                                                    f"into the query layer" for i in (1, 2, 3))}]}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "before.json").write_text(json.dumps(before), encoding="utf-8")
        (tmp / "after.json").write_text(json.dumps(after), encoding="utf-8")
        report = finalize.build_report(tmp / "after.json", tmp, [], tmp / "before.json",
                                       make_lead_transcript(tmp, ["src/auth/guard_2.py"]))
    leg = next(l for l in report.legs if l.name == "access baseline")
    disclosed = next(a for a in leg.advisory if a.startswith("DISCLOSURE"))
    unread = next(a for a in leg.advisory if finalize.UNREAD_EXCUSES in a)
    for text, count, paths in ((disclosed, "3 of 3", (1, 2, 3)), (unread, "2 of 3", (1, 3))):
        first = text.splitlines()[0]
        assert count in first and len(first) < 200, first
        for i in paths:
            own = lines_naming(text, f"src/auth/guard_{i}.py")
            assert len(own) == 1 and own[0].startswith(f"  - src/auth/guard_{i}.py"), (i, text)
    assert not lines_naming(unread, "src/auth/guard_2.py"), "the lead opened that one"


def test_every_list_in_the_refutation_leg_puts_its_count_first_and_each_item_on_its_own_line():
    """The same advisory shape five more times: a count, then the items run together on one line.
    The closer-rejected disclosure was 1,011 characters on the 2026-10-07 mcpolis report."""
    legs: list[finalize.Leg] = []
    _root, p, verify = _map_with_a_refuted_claim(Path(tempfile.mkdtemp()))
    legs.append(finalize._refutations_leg(p, [verify / "verdicts-desc-1.json",
                                               verify / "closer-agent-1.json"]))
    _root, p, files = make_refuted_step_repo(None)
    legs.append(finalize._refutations_leg(p, files))
    _root, p, files, _claim = make_access_dissent_repo("unsure")
    legs.append(finalize._refutations_leg(p, files))
    for elements in (["BR1"], ["BR9"]):
        _root, p, v = make_reworded_rule_repo(elements, "src/a.py:2")
        legs.append(finalize._refutations_leg(p, [v]))
    advisories = [a for leg in legs for a in leg.advisory]
    for head in ("refuted claim(s) are in this map because the CLOSER REJECTED",
                 "refuted walk-step or interface claim(s) are still in the map",
                 "the majority CONFIRMED over a dissent the closer could not settle",
                 "ACCESS rule(s) were re-worded after the vote",
                 "ACCESS rule(s) were never challenged"):
        lines = next((a for a in advisories if head in a), "").splitlines()
        assert lines and head in lines[0] and lines[0][:1].isdigit(), (head, lines)
        assert len(lines[0]) < 200, (head, lines[0])
        assert len(lines) >= 3 and lines[1].startswith("  - "), (head, lines)


# --- one line answers the map's size (retro 2026-10-07, finding 6) --------------------------------
# validate holds the component count to E and reads a `granularity:` line; the budget leg held the
# same count to the summed budgets and read only `component-budget:`, a key the method never names.
# The 2026-10-07 mcpolis build wrote the `granularity:` line, and the leg shipped UNRECORDED.

def test_a_granularity_line_naming_both_counts_answers_the_budget_leg_and_validate():
    root, p = make_budget_repo("granularity: 10 shipped of 5 budgeted, because the slices were "
                               "cut before the adapters were counted")
    report = finalize.build_report(p, root, [])
    assert [d for d, _h, a in finalize.advisory_disposition(p, report)
            if "shipped against" in a] == ["disclosure"]
    validate = next(l for l in report.legs if l.name == "validate")
    assert not [w for w in validate.advisory if w.startswith("Granularity:")], validate.advisory


def test_a_granularity_line_naming_the_shipped_count_and_E_does_not_answer_the_budget_leg():
    """The strictness stays: E is not the budget, and a line written against E says nothing about
    why the map outgrew what the briefs were handed."""
    root, p = make_budget_repo("granularity: 10 components against a code-derived 1, because the "
                               "slices split their folders by job")
    report = finalize.build_report(p, root, [])
    assert [d for d, _h, a in finalize.advisory_disposition(p, report)
            if "shipped against" in a] == ["UNRECORDED"]


def test_the_budget_advisory_offers_the_one_line_that_answers_both():
    root, p = make_budget_repo(None)
    leg = _budget_leg_of(finalize.build_report(p, root, []))
    assert leg is not None and leg.advisory, leg
    assert "'granularity: 10 shipped of 5 budgeted, because" in leg.advisory[0], leg.advisory[0]


# --- a disclosure says only what the tool knows (retro 2026-10-07, finding 23) --------------------
# finalize's report said each recorded audit exception "was judged acceptable by an operator"; the
# 2026-10-07 mcpolis lead wrote every one of them alone. The tool knows a line sits under the heading,
# not who weighed it.

def make_recorded_audit_repo(body: str) -> Path:
    """A map with one `read-never-created` advisory (HP1 reads E1, nothing writes it) and `body`
    under 'Audit exceptions'."""
    root = Path(tempfile.mkdtemp())
    (root / ".coyomap").mkdir()
    doc = {"format": FORMAT, "title": "T", "goal": "G",
           "roles": [{"id": "R1", "name": "A", "kind": "human", "wants": "x", "drives": "UC1"}],
           "use_cases": [{"id": "UC1", "name": "Read it", "actors": ["R1"]}],
           "happy_path": [{"id": "HP1", "uc": "UC1"}],
           "components": [{"id": "C1", "name": "A", "purpose": "p"}],
           "entities": [{"id": "E1", "name": "Thing", "source": "a.py:1"}],
           "edges": [{"src": "C1", "verb": "reads", "dst": "E1", "why": "w", "where": "a.py:2"}],
           "flows": [{"uc": "UC1", "title": "Read it", "steps": [
               {"n": 1, "src": "R1", "dst": "C1", "phrase": "asks"},
               {"n": 2, "src": "C1", "dst": "E1", "phrase": "reads the thing"}]}],
           "extras": [{"heading": "Audit exceptions", "body": body}]}
    p = root / ".coyomap" / "project-map.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_the_audit_disclosure_names_no_operator_it_cannot_know():
    p = make_recorded_audit_repo("read-never-created HP1: the settings come from the deployment\n"
                                 "read-never-created HP99: an id the map no longer has")
    leg = finalize._audit_leg(p)
    said = [a for a in leg.advisory if a.startswith("recorded-exceptions")]
    assert len(said) == 2, leg.advisory
    assert not [a for a in said if "operator" in a], said
    silenced = next(a for a in said if "suppressed by recorded exception" in a)
    assert "by whoever ran the build" in silenced, silenced
    assert finalize._DISCLOSURE.search(silenced), "it is still filed as a disclosure"


# --- a cut list says how many it left out (merge 5.4, 2026-10-07) ---------------------------------
# Three finalize messages cut a list and said nothing about what they cut: a bare `…`, or no tail
# at all. They now go through `reporting.shown`, whose tail counts what it left out.

def make_unnumbered_budgets(root: Path, unnumbered: int) -> None:
    """budgets.json holding two numeric harvest briefs and `unnumbered` briefs whose budget is a
    word rather than a number."""
    verify = root / ".coyomap" / "verify"
    verify.mkdir(parents=True, exist_ok=True)
    harvest: dict[str, int | str] = {"t1": 3, "t2": 2}
    harvest.update({f"u{i}": "about ten" for i in range(1, unnumbered + 1)})
    (verify / "budgets.json").write_text(json.dumps({"harvest": harvest}), encoding="utf-8")


def test_the_unasked_verdicts_leg_counts_the_verdict_files_it_does_not_name():
    leg = finalize._unasked_verdicts_leg([Path(f"verdicts-{i}.json") for i in range(1, 6)])
    said = leg.advisory[0]
    assert "(verdicts-1.json, verdicts-2.json, verdicts-3.json, +2 more)" in said, said


def test_the_budget_leg_counts_the_unnumbered_briefs_it_does_not_name():
    root, p = make_repo(components=10)
    make_unnumbered_budgets(root, 8)
    leg = _budget_leg_of(finalize.build_report(p, root, []))
    assert leg is not None and leg.note is not None, leg
    assert "8 brief(s) with no numeric budget (u1, u2, u3, u4, u5, u6, +2 more)" in leg.note, leg.note


def test_a_second_map_path_is_refused_with_every_extra_path_counted():
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = finalize.main([f"map-{i}.json" for i in range(1, 7)])
    assert code == 2
    assert "got 6 (map-1.json, map-2.json, map-3.json, map-4.json, +2 more)" in err.getvalue(), (
        err.getvalue())


# --- what the agents filed about the product, and the build state (round 1) -----------------------
# The agents file product findings with `coyomap findings add`; finalize counts them in a leg that
# never moves the verdict, and writes its own verdict line to an open build state.

def run_finalize(p: Path, root: Path, *extra: str) -> int:
    """`finalize` on one map, its printed output dropped: the report files are what is read."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return finalize.main([str(p), "--repo", str(root), *extra])


def make_finalized(filed: list[tuple[str, str]]) -> tuple[dict, str]:
    """A clean map finalized after its agents filed `(agent, kind)` findings: (report, its .md)."""
    root, p = make_repo()
    for agent, kind in filed:
        findings.add(root, agent, kind, ["src/a.py:1"], f"{kind} seen by {agent}")
    assert run_finalize(p, root) == 0
    report = json.loads((root / ".coyomap" / "finalize-report.json").read_text(encoding="utf-8"))
    return report, (root / ".coyomap" / "finalize-report.md").read_text(encoding="utf-8")


def test_finalize_names_the_filed_findings_in_an_informational_leg():
    report, md = make_finalized([("harvest-1", "risk"), ("trace-2", "gap")])
    quiet, _quiet_md = make_finalized([])
    leg = next(l for l in report["legs"] if l["name"] == "agent findings (informational)")
    assert leg["status"] == "ran" and leg["blocking"] == [] and leg["advisory"] == [], leg
    assert leg["note"].startswith("FINDINGS FILED BY AGENTS — 2 from 2 agent(s): risk 1 · bug 0 · "
                                  "gap 1 · contradiction 0 · 0 malformed"), leg["note"]
    assert "FINDINGS FILED BY AGENTS — 2 from 2 agent(s)" in md, md
    # a finding never moves the verdict: the same map with nothing filed reads the same
    assert ((report["verdict"], report["blocking_total"], report["advisory_total"])
            == (quiet["verdict"], quiet["blocking_total"], quiet["advisory_total"])), (report, quiet)
    none = next(l for l in quiet["legs"] if l["name"] == "agent findings (informational)")
    assert none["note"].startswith("FINDINGS FILED BY AGENTS — none filed"), none["note"]


def test_finalize_appends_its_verdict_to_an_open_state():
    root, p = make_repo()
    buildstate.start(root)
    assert run_finalize(p, root, "--no-write") == 0
    state = buildstate.read_state(root)
    assert state is not None and state.last("finalize") is None, "a --no-write read wrote a line"
    assert run_finalize(p, root) == 0
    report = json.loads((root / ".coyomap" / "finalize-report.json").read_text(encoding="utf-8"))
    state = buildstate.read_state(root)
    assert state is not None
    line = state.last("finalize")
    assert line is not None, state.events
    assert line.text.startswith(f"{report['verdict']} — {report['blocking_total']} blocking, "
                                f"{report['advisory_total']} advisory"), line.text
    assert line.text.endswith("finalize-report.md"), line.text


def test_an_archived_maps_findings_are_the_ones_its_report_counts():
    """An archive moves a build's `findings/` with its map; a retrospective reading that map must
    count those, not the findings of whatever build runs now."""
    root, live = make_repo()
    findings.add(root, "harvest-1", "risk", ["src/a.py:1"], "today's build saw this")
    findings.add(root, "harvest-2", "bug", ["src/a.py:1"], "and this")
    archive = root / ".coyomap" / "dev-rebuilds" / "0001"
    (archive / "findings").mkdir(parents=True)
    archived = archive / "project-map.json"
    archived.write_text(live.read_text(encoding="utf-8"), encoding="utf-8")
    (archive / "findings" / "trace-9.jsonl").write_text(json.dumps(
        {"agent": "trace-9", "kind": "gap", "where": ["src/a.py:1"], "text": "the old build saw this",
         "at": "2026-09-01 10:00"}) + "\n", encoding="utf-8")
    def note_of(p: Path) -> str:
        legs = finalize.build_report(p, root, []).legs
        return next(l.note or "" for l in legs if l.name == "agent findings (informational)")
    assert note_of(archived).startswith("FINDINGS FILED BY AGENTS — 1 from 1 agent(s): risk 0 · "
                                        "bug 0 · gap 1"), note_of(archived)
    assert note_of(live).startswith("FINDINGS FILED BY AGENTS — 2 from 2 agent(s): risk 1 · bug 1"), (
        note_of(live))
