#!/usr/bin/env python3
"""`coyomap finalize` — the pre-commit read.

The design point these pin: it is a CONVENIENCE WRAPPER, not an enforcement point. Nothing makes a
build run it, and `finalize | grep …` returns grep's status, so the value is (a) running `compare`
during the build at all — the check that caught a 103→19 security-table collapse every other gate
passed, and that nobody ran — and (b) writing a durable report a `> /dev/null` cannot erase.

Run either way: `python3 tests/test_finalize.py` or `pytest tests/test_finalize.py`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from coyomap import finalize
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
