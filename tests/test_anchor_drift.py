"""Tests for `coyomap anchor-drift` (Phase G build command)."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path

from coyomap import anchor_drift as ad
from coyomap import audit_model
from coyomap.audit_model import WorkItem, l2_worklist_model
from coyomap.model import FORMAT, ProjectModel, load_model


def make_item(claim: str, anchor: str, drift_eligible: bool = True) -> WorkItem:
    return WorkItem(claim=claim, anchor=anchor, why_risky="risk", drift_eligible=drift_eligible)


def make_vote(claim: str, grounded: bool, evidence: str) -> dict:
    return {"claim": claim, "grounded": grounded, "evidence": evidence}


def test_drift_flags_confirmed_claim_with_drifted_anchor():
    wl = [make_item("C1 reads E1", "org_service.py:245")]
    grounding = [make_vote("C1 reads E1", True, "org_service.py:243"),
                 make_vote("C1 reads E1", True, "org_service.py:243")]
    found = ad.drift_findings(wl, grounding, tolerance=0)
    assert len(found) == 1 and found[0][1].drifted
    assert ad.drift_findings(wl, grounding, tolerance=2) == []  # within tolerance → no drift


def test_drift_skips_unconfirmed_claim():
    # only a tie (1 of 2 grounded) → not a strict majority → not evaluated for drift.
    wl = [make_item("C1 reads E1", "a.py:245")]
    grounding = [make_vote("C1 reads E1", False, "a.py:1"),
                 make_vote("C1 reads E1", True, "a.py:1")]
    assert ad.drift_findings(wl, grounding, tolerance=0) == []


def test_drift_records_carry_the_corrected_where():
    # drift_records (feeds --json and `fix apply-drift`) computes the corrected `path:line` — the
    # consensus (median) grounded evidence — so the two consumers can never disagree.
    wl = [make_item("C1 reads E1", "org_service.py:245")]
    grounding = [make_vote("C1 reads E1", True, "org_service.py:243"),
                 make_vote("C1 reads E1", True, "org_service.py:243")]
    recs = ad.drift_records(wl, grounding, tolerance=0)
    assert len(recs) == 1
    assert recs[0]["claim"] == "C1 reads E1"
    assert recs[0]["corrected"] == "org_service.py:243"
    assert recs[0]["same_file"] is True


def test_consensus_evidence_prefers_the_same_file_group():
    # a stray different-file vote must not pull the consensus off the stored file.
    got = ad.consensus_evidence("a.py:10", ["a.py:12", "a.py:12", "z.py:99"])
    assert got == "a.py:12"


def test_drift_cli_end_to_end():
    # A tiny map with one edge whose `where` is line 245; skeptics confirm the claim but report 243.
    edge_map = {
        "format": FORMAT, "title": "t", "goal": "g",
        "components": [{"id": "C1", "name": "A", "source": "a.py:1"},
                       {"id": "C2", "name": "B", "source": "b.py:1"}],
        "edges": [{"src": "C1", "verb": "reads", "dst": "C2", "where": "a.py:245"}],
    }
    claim = l2_worklist_model(load_model(json.dumps(edge_map)))[0].claim
    verdicts = {"grounding": [make_vote(claim, True, "a.py:243"),
                              make_vote(claim, True, "a.py:243")]}
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "map.json"
        vp = Path(td) / "verdicts.json"
        mp.write_text(json.dumps(edge_map), encoding="utf-8")
        vp.write_text(json.dumps(verdicts), encoding="utf-8")
        assert ad.main(["--map", str(mp), "--verdicts", str(vp), "--tolerance", "0"]) == 0
        assert ad.main(["--map", str(mp), "--verdicts", str(vp), "--tolerance", "2"]) == 0


# --- report-only claims are never anchor-nudged -------------------------------------------------
# A structured-store claim ("E1 (Guild) is stored in D1 container 'guilds'") is anchored at the
# entity's TYPE DEFINITION by the domain-card contract — deliberately NOT the line the write happens
# on. So when the Phase-4 skeptics confirm it and report the WRITE site, that gap is not drift: it is
# the contract working. A real build produced 13 drift findings of which NINE were this class, and
# the lead had to hand-filter them out before `fix apply-drift` — the hand-scripting method.md
# forbids. The suppression is a property of the claim (`drift_eligible`), never a text match.

def make_store_map() -> dict:
    """A map with BOTH an entity store claim (report-only, anchored at the type definition) and a
    plain backbone edge (drift-eligible, anchored at the call site). Both anchors are 40 lines away
    from where the skeptics will say the action happens."""
    return {
        "format": FORMAT, "title": "t", "goal": "g",
        "components": [{"id": "C1", "name": "Repo", "source": "repo.py:1"},
                       {"id": "C2", "name": "Api", "source": "api.py:1"}],
        "deps": [{"id": "D1", "name": "MongoDB", "kind": "datastore", "type": "document db"}],
        "entities": [{"id": "E1", "name": "Guild", "source": "domain/guild.py:9",
                      "store": {"dep": "D1", "container": "guilds", "mode": "collection"}}],
        "edges": [{"src": "C1", "verb": "reads", "dst": "C2", "where": "repo.py:245"}],
    }


def make_claims() -> tuple[list[WorkItem], str, str]:
    """(worklist, store-claim text, edge-claim text) built by the real worklist builder — so the
    test exercises the shipped `drift_eligible` wiring, not a hand-set flag."""
    wl = l2_worklist_model(load_model(json.dumps(make_store_map())))
    store = next(w.claim for w in wl if "is stored in" in w.claim)
    edge = next(w.claim for w in wl if w.claim.startswith("C1 "))
    return wl, store, edge


def test_store_claim_is_marked_report_only_in_the_worklist():
    wl, store, edge = make_claims()
    by_claim = {w.claim: w for w in wl}
    assert by_claim[store].drift_eligible is False
    assert by_claim[store].anchor == "domain/guild.py:9"   # the TYPE definition, by contract
    assert by_claim[edge].drift_eligible is True


def test_confirmed_store_claim_yields_no_drift_finding_and_no_apply_drift_record():
    wl, store, _edge = make_claims()
    # skeptics confirm the claim and report the WRITE site — 200 lines from the type definition.
    grounding = [make_vote(store, True, "repo/guild_repo.py:212"),
                 make_vote(store, True, "repo/guild_repo.py:212")]
    assert ad.drift_findings(wl, grounding, tolerance=0) == []
    assert ad.drift_records(wl, grounding, tolerance=0) == []


def test_confirmed_edge_claim_still_drifts_when_a_store_claim_is_present():
    # the suppression is per-claim, not a global off switch: the edge in the SAME worklist,
    # confirmed by the SAME verdicts file, must still be flagged and still reach `fix apply-drift`.
    wl, store, edge = make_claims()
    grounding = [make_vote(store, True, "repo/guild_repo.py:212"),
                 make_vote(store, True, "repo/guild_repo.py:212"),
                 make_vote(edge, True, "repo.py:243"),
                 make_vote(edge, True, "repo.py:243")]
    found = ad.drift_findings(wl, grounding, tolerance=0)
    assert [w.claim for w, _d in found] == [edge]
    recs = ad.drift_records(wl, grounding, tolerance=0)
    assert [r["claim"] for r in recs] == [edge]
    assert recs[0]["corrected"] == "repo.py:243"


def test_refuted_store_claim_still_surfaces_to_the_skeptics():
    # ONLY the anchor nudge is suppressed. The store claim is still in the worklist the skeptics are
    # farmed from, and still carried by `audit --json` — so a skeptic can still refute it and the
    # lead still re-authors the row. Marking it report-only must not hide the claim.
    wl, store, _edge = make_claims()
    assert store in [w.claim for w in wl]
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "map.json"
        mp.write_text(json.dumps(make_store_map()), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert audit_model.main([str(mp), "--json"]) == 0
        payload = json.loads(buf.getvalue())
    claims = [w["claim"] for w in payload["worklist"]]
    assert store in claims
    # `audit --json` keeps its published shape — the new flag is in-process only (anchor-drift
    # rebuilds the worklist from the map), so no Phase-4 consumer of this JSON has to change.
    assert all(set(w) == {"claim", "anchor", "detail", "why_risky", "theme", "drift_eligible"}
               for w in payload["worklist"])
    # the store claim is report-only by contract, and the payload now says so out loud
    assert all(w["theme"] == "persistence" and w["drift_eligible"] is False
               for w in payload["worklist"] if w["claim"] == store)


def test_refuted_report_only_claim_produces_no_drift_either():
    # a refuted claim was never drift-evaluated (no strict majority) — that stays true, and the
    # report-only skip must not turn a refutation into a silent confirmation.
    wl, store, _edge = make_claims()
    grounding = [make_vote(store, False, "domain/guild.py:9"),
                 make_vote(store, False, "domain/guild.py:9")]
    assert ad.drift_findings(wl, grounding, tolerance=0) == []
    assert ad.drift_records(wl, grounding, tolerance=0) == []


def make_declaration_anchored_doc() -> dict:
    """A map carrying one of each declaration-anchored claim kind, every one CITING its own
    declaring line (`messaging.source`, `states.source`, `cadence_source`)."""
    return {
        "format": FORMAT, "title": "t", "goal": "g",
        "components": [{"id": "C1", "name": "Worker", "source": "w.py:1"},
                       {"id": "C2", "name": "Consumer", "source": "c.py:1"}],
        "deps": [{"id": "D1", "name": "Redis", "kind": "messaging", "type": "queue broker"}],
        "messaging": [{"name": "JOB_QUEUE", "kind": "job-queue", "broker": "D1",
                       "publishers": ["C1"], "consumers": ["C2"], "source": "queues.py:3"}],
        "entities": [{"id": "E1", "name": "Job", "source": "job.py:2",
                      "store": {"dep": "D1", "container": "jobs", "mode": "collection"},
                      "states": {"states": ["NEW", "DONE"], "source": "job.py:20"}}],
        "entry_points": [{"kind": "cron", "trigger": "nightly", "component": "C1",
                          "cadence": "0 3 * * *", "cadence_source": "cron.py:7"}],
    }


def _row(wl: list, needle: str):
    return next(w for w in wl if needle in w.claim)


def test_a_claim_sent_to_a_different_kind_of_line_than_its_anchor_is_not_drift_evaluated():
    # Store and messaging anchors point at a DECLARATION while the skeptic is sent to a CALL SITE
    # (the write site, the enqueue/consume site). A difference between two different kinds of line
    # is not evidence of anything, so it must not be reported as drift.
    wl = l2_worklist_model(load_model(json.dumps(make_declaration_anchored_doc())))
    for needle in ("is stored in", "Channel '"):
        row = _row(wl, needle)
        assert row.drift_eligible is False, row.claim
        votes = [make_vote(row.claim, True, "elsewhere.py:900")] * 2
        assert ad.drift_findings(wl, votes, tolerance=0) == []


def test_a_claim_sent_to_the_SAME_line_its_anchor_cites_IS_drift_evaluated():
    # The opposite case, and the one an over-broad sweep silently broke. A state machine citing its
    # own `source` sends the skeptic to *the declaring enum* — the very line the anchor points at —
    # so a difference IS drift. Same for a cadence that cites `cadence_source`. This is the ONLY
    # line-level check these anchors have: `check_state_sources_model` reads the whole file text, so
    # a declaration that MOVES INSIDE its file is invisible to it.
    wl = l2_worklist_model(load_model(json.dumps(make_declaration_anchored_doc())))
    for needle in ("has states [", "runs on cadence"):
        row = _row(wl, needle)
        assert row.drift_eligible is True, row.claim
        votes = [make_vote(row.claim, True, "job.py:46")] * 2
        assert any(needle in w.claim for w, _d in ad.drift_findings(wl, votes, tolerance=0)), \
            f"a moved declaration must be reported for {needle!r}"
        assert any(needle in r["claim"] for r in ad.drift_records(wl, votes, tolerance=0)), \
            f"and must reach the apply-drift record for {needle!r}"


def test_an_UNCITED_declaration_anchor_falls_back_to_a_different_line_and_is_not_evaluated():
    # Without its own `source`, a state machine anchors the ENTITY's line and an inferred cadence
    # anchors the ENTRY POINT's line — neither ever declared the thing being claimed, so the
    # same different-kind-of-line reasoning applies and drift there is noise.
    doc = make_declaration_anchored_doc()
    doc["entities"][0]["states"].pop("source")
    doc["entry_points"][0].pop("cadence_source")
    wl = l2_worklist_model(load_model(json.dumps(doc)))
    for needle in ("has states [", "runs on cadence"):
        assert _row(wl, needle).drift_eligible is False, needle


def test_a_split_vote_is_a_tie_in_either_order_and_votes_are_never_deduped():
    """Two facts, one of which cost a reverted change.

    First: a review claimed a split vote was "decided by file-sort order". That is FALSE — the tally
    has always been a strict majority, so 1-grounded/1-refuted is a tie whichever order the rows
    arrive in.

    Second, and the reason there is NO dedupe here: collapsing identical `(claim, grounded, evidence)`
    triples looks like a fix for double-counted verdicts files and is worse in both directions.
    Refutations carry no evidence line by convention, so every refutation of a claim would collapse to
    ONE vote — turning a genuine 2-2 tie into 2-1 confirmed, exactly the failure it was meant to
    prevent. And two independent skeptics that agree on the same line are indistinguishable from one
    row seen twice: on this repo's own recorded build, two independent reads of the security batch
    agree exactly on 37 of 40 claims. A correct fix needs a per-vote identity the verdicts format does
    not carry."""
    from coyomap.anchor_drift import _confirmed_drifts
    from coyomap.audit_model import WorkItem
    w = WorkItem(claim="C1 reads E1", anchor="a.py:10", why_risky="x", theme="ownership")
    yes = {"claim": "C1 reads E1", "grounded": True, "evidence": "a.py:40"}
    no = {"claim": "C1 reads E1", "grounded": False, "evidence": ""}

    assert not _confirmed_drifts([w], [yes, no], 2)                 # a tie is not a majority
    assert not _confirmed_drifts([w], [no, yes], 2)                 # …in either order
    assert not _confirmed_drifts([w], [yes, no, dict(no)], 2)       # 1-2 against
    # Two independent agreeing skeptics outvote one dissenter — the case a dedupe would have broken.
    assert _confirmed_drifts([w], [yes, dict(yes), no], 2)
    # …and N refutations are N votes, not one: a real 2-2 tie stays a tie.
    assert not _confirmed_drifts([w], [yes, {**yes, "evidence": "a.py:41"}, no, dict(no)], 2)


# --- recording a drift exception --------------------------------------------------------------
#
# The escape existed but could not be used. The key regex was `[^`'"]+` — a class that cannot span
# a quote — while EVERY cadence claim is phrased `runs on cadence '<x>'`. So the whole cadence
# family was permanently un-recordable, and silently: a line that does not parse yields no key, the
# early return fires, and the "matched no finding" diagnostic never runs. A live build recorded two
# exceptions in the exact format the report prints, watched them do nothing, and had to read
# anchor_drift.py to find out why.


def make_map_with_drift_exceptions(body: str) -> ProjectModel:
    return load_model(json.dumps({
        "format": FORMAT, "title": "T", "goal": "g",
        "extras": [{"heading": ad.DRIFT_EXCEPTIONS_HEADING, "body": body}],
    }))


def test_the_shape_only_pass_says_a_recorded_drift_line_does_nothing_here():
    """A `Drift exceptions` line keys to a VERDICT-based finding, and `finalize` always runs the
    shape-only pass too. Nothing said so, so an operator who wrote one watched the finding survive
    with no way to tell a dead key from a live one that had not fired — the silently-inert record
    this heading was created to end, at the one address it still had. The findings on this pass have
    no recorded escape BY DESIGN (`KNOWN_NO_ESCAPE` carries that decision), so the answer is to name
    the pass, not to accept a second key vocabulary under one heading."""
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "m.json"
        mp.write_text(json.dumps(
            {"format": FORMAT, "title": "T", "goal": "g",
             "extras": [{"heading": ad.DRIFT_EXCEPTIONS_HEADING,
                         "body": "- anchor-drift `C1 calls C2`: read it, the anchor stands."}]}),
            encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert ad.main(["--map", str(mp)]) == 0
    out = buf.getvalue()
    assert "silence nothing HERE" in out
    assert "shape-only pass" in out and "--verdicts" in out


def test_the_shape_only_pass_stays_quiet_when_nothing_is_recorded():
    """The note appears only when a line exists to be wrong about. A note on every run is a note
    nobody reads."""
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "m.json"
        mp.write_text(json.dumps({"format": FORMAT, "title": "T", "goal": "g"}), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert ad.main(["--map", str(mp)]) == 0
    assert "silence nothing HERE" not in buf.getvalue()


def test_a_cadence_claim_with_quotes_can_be_recorded():
    claim = "Entry point [poller] hourly sweep runs on cadence 'every 1h'"
    m = make_map_with_drift_exceptions(
        f"- anchor-drift `{claim}`: the stored anchor is the declaration; skeptics read the caller.")
    findings = [(make_item(claim, "health.py:49"), ad.DriftResult(True, "health.py:49", 80, True, 31))]
    kept, notes = ad.apply_drift_exceptions(m, findings)
    assert kept == []
    assert any("suppressed by recorded exception" in n for n in notes)


def test_a_key_containing_the_delimiter_still_parses():
    claim = "C1 calls `weird` C2"
    m = make_map_with_drift_exceptions(f"- anchor-drift `{claim}`: verified, the stored line is right.")
    recorded, malformed = ad.drift_exceptions(m)
    assert recorded == {claim} and malformed == []


def test_a_line_that_does_not_parse_is_reported_not_silently_dropped():
    # the silent half of the bug: an unusable record must never look like no record at all.
    m = make_map_with_drift_exceptions("- anchor-drift C42 persists E6: no delimiters, so no key")
    recorded, malformed = ad.drift_exceptions(m)
    assert recorded == set() and len(malformed) == 1
    findings = [(make_item("C42 persists E6", "a.py:1"), ad.DriftResult(True, "a.py:1", 9, True, 8))]
    kept, notes = ad.apply_drift_exceptions(m, findings)
    assert len(kept) == 1                      # the finding still fires — nothing was silenced
    assert any("do not parse, so they silence NOTHING" in n for n in notes)


def test_a_key_alone_without_a_why_is_still_refused():
    # a dismissal is not a record; this rule must survive the regex widening.
    m = make_map_with_drift_exceptions("- anchor-drift `C42 persists E6`:")
    recorded, malformed = ad.drift_exceptions(m)
    assert recorded == set() and len(malformed) == 1


def test_a_why_containing_the_delimiter_does_not_swallow_the_key():
    """The 2026-08-01 clobber. The key was greedy, so it bound the closing backtick of a code quote
    inside the WHY (followed by an em dash, an accepted separator) instead of the key's own closing
    backtick. 90 characters of prose ended up in the key, it matched no finding, and `fix
    apply-drift` overwrote the security anchor the record existed to defend — while the line parsed
    cleanly, so the malformed-record diagnostic never fired and three turns went into finding out
    why. The sibling test above pins what greedy was chosen for: a delimiter INSIDE the key."""
    claim = ("Auth surface 'Public org info endpoint (/api/orgs/{slug}/public) — the documented "
             "anti-enumeration exception' is protected by: "
             "backend/src/mcpolis/entrypoints/routes/org_routes.py:271")
    why = ('the stored anchor is right. Line 271 is `return {"exists": True, "display_name": '
           'org.display_name}` — the statement that LIMITS what this deliberately unauthenticated '
           'endpoint discloses. The skeptics reported line 240, the route decorator.')
    m = make_map_with_drift_exceptions(f"- anchor-drift `{claim}`: {why}")
    recorded, malformed = ad.drift_exceptions(m)
    assert recorded == {claim}, f"the key must stop at its own delimiter, got {recorded}"
    assert malformed == []


# --- a nudge inside one definition, vs a re-anchor onto another ---------------------------------
#
# The 2026-09-13 reminderrepo build. `anchor-drift` reported "C146 calls D31: stored
# [deployment/scripts/auto-deploy.sh:87] — skeptics found line 261 (174 off)" and `fix apply-drift`
# wrote it, unattended, inside `ship`. Line 87 is `sh get-docker.sh`, the container-engine install
# the edge's own `why` describes; line 261 is a `docker build`. `drifted` is a LOWER bound only, so
# a 4-line nudge and that relocation were the same fact and the writer could not tell them apart.
#
# The cut is the ENCLOSING DEFINITION, not a line count, and the third test below is why: the
# commonest drift the adversarial pass finds is an anchor parked on a function header, and moving it
# onto the operative statement of a long function is a big move that is entirely right. An upper
# distance bound would refuse exactly the correction this command exists to make.


def make_extents(rows: dict[str, list[tuple[int, int, str, str]]]) -> dict:
    """The pre-index symbol table, in the shape `impact_git.load_map_extents` returns."""
    return {path: [(lo, hi, name, kind) for lo, hi, name, kind in v] for path, v in rows.items()}


def confirmed(anchor: str, evidence: str, extents: dict | None = None):
    """The single drift finding for one confirmed claim whose anchor is `anchor`."""
    wl = [make_item("C1 reads E1", anchor)]
    votes = [make_vote("C1 reads E1", True, evidence)] * 2
    found = ad.drift_findings(wl, votes, tolerance=2, extents=extents)
    assert len(found) == 1, f"{anchor} → {evidence} is not one finding: {found}"
    return found[0][1]


def test_a_correction_onto_another_definition_is_reported_and_refused():
    ext = make_extents({"a.py": [(5, 20, "save", "function"), (50, 70, "render", "function")]})
    d = confirmed("a.py:10", "a.py:60", ext)
    assert d.drifted is True, "it is still drift — the map's anchor is still wrong"
    assert d.refusal is not None
    assert "save" in d.refusal and "render" in d.refusal, d.refusal


def test_a_correction_inside_the_same_definition_is_applied():
    ext = make_extents({"a.py": [(5, 70, "save", "function")]})
    assert confirmed("a.py:10", "a.py:60", ext).refusal is None


def test_a_long_move_inside_ONE_definition_is_still_applied():
    """The case an upper distance bound would get wrong, and the reason there is not one. An anchor
    parked on the header of a 300-line function, corrected onto the operative statement 250 lines
    down, is the nudge `apply-drift` exists for — and 250 is bigger than the relocation this check
    was built to refuse."""
    ext = make_extents({"a.py": [(10, 320, "handle", "function")]})
    assert confirmed("a.py:10", "a.py:260", ext).refusal is None


def test_a_long_move_with_no_definition_on_either_side_is_refused():
    """The reminderrepo shape, exactly: a shell script the pre-index carries no symbols for, with
    both lines at the file's top level. There is no boundary to reason about, so the only signal
    left is distance — and 174 lines is not a nudge."""
    d = confirmed("deploy.sh:87", "deploy.sh:261", make_extents({"other.py": [(1, 9, "x", "f")]}))
    assert d.refusal is not None and "174 lines away" in d.refusal, d.refusal
    assert "neither line" in d.refusal, d.refusal


def test_a_short_move_with_no_definition_on_either_side_is_applied():
    """The other half of the same rule: with no symbol table, a small move is still a nudge. Left
    generous on purpose — refusing everything unplaced would turn `apply-drift` into a no-op on
    every map with no pre-index beside it."""
    assert confirmed("deploy.sh:87", "deploy.sh:100", make_extents({})).refusal is None


def test_a_decorator_moving_onto_the_line_it_decorates_is_applied():
    """Only a crossing the tool can SEE BOTH SIDES of is refused. Most extractors put a decorator
    outside the function it decorates, so `@app.post(...)` → the operative line inside the handler
    has no definition on the stored side — the ordinary nudge, and refusing it would kill a whole
    legitimate family."""
    ext = make_extents({"routes.py": [(41, 90, "create_user", "function")]})
    assert confirmed("routes.py:40", "routes.py:45", ext).refusal is None


def test_a_refused_finding_survives_both_head_and_tail_of_the_report():
    """The build that motivated this read `ship` output through both pipes and saw neither the
    174-line move nor any sign that something had been decided on its behalf. So a refusal leads
    the listing AND is counted on its last line."""
    ext = make_extents({"a.py": [(5, 20, "save", "function"), (50, 70, "render", "function")]})
    wl = [make_item("C1 reads E1", "a.py:10"), make_item("C2 reads E2", "a.py:12")]
    votes = [make_vote("C1 reads E1", True, "a.py:60")] * 2 + \
            [make_vote("C2 reads E2", True, "a.py:16")] * 2
    report = ad._format(ad.drift_findings(wl, votes, tolerance=2, extents=ext), 2)
    head, tail = report.splitlines()[:4], report.splitlines()[-1]
    assert any("NOT be written" in ln for ln in head), report
    assert "1 of 2 finding(s) are REFUSED" in tail, tail


def make_map_and_verdicts(td: str, stored: str, evidence: str,
                          extents: dict | None = None) -> tuple[Path, Path]:
    """A one-edge map, its verdicts, and — when `extents` is given — the `preindex.json` the real
    command reads from the map's own directory. Exercises the wiring, not just the predicate."""
    doc = {"format": FORMAT, "title": "t", "goal": "g",
           "components": [{"id": "C1", "name": "A", "source": "a.py:1"},
                          {"id": "C2", "name": "B", "source": "b.py:1"}],
           "edges": [{"src": "C1", "verb": "reads", "dst": "C2", "where": stored}]}
    mp, vp = Path(td) / "map.json", Path(td) / "verdicts.json"
    mp.write_text(json.dumps(doc), encoding="utf-8")
    claim = l2_worklist_model(load_model(json.dumps(doc)))[0].claim
    vp.write_text(json.dumps({"grounding": [make_vote(claim, True, evidence)] * 2}),
                  encoding="utf-8")
    if extents is not None:
        (Path(td) / "preindex.json").write_text(json.dumps({"symbols": {"extents": extents}}),
                                                encoding="utf-8")
    return mp, vp


def test_the_cli_report_marks_a_move_onto_another_definition_not_applied():
    """End to end, through the command the build actually runs: the pre-index is read from beside
    the map, the row is still REPORTED as drift, and it now says out loud that `fix apply-drift`
    will not write it. Before this, the row read exactly like the small nudges beside it."""
    with tempfile.TemporaryDirectory() as td:
        mp, vp = make_map_and_verdicts(
            td, "a.py:10", "a.py:60",
            {"a.py": [[5, 20, "save", "function"], [50, 70, "render", "function"]]})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert ad.main(["--map", str(mp), "--verdicts", str(vp), "--tolerance", "0"]) == 0
    out = buf.getvalue()
    assert "C1 reads C2" in out, "still reported as drift"
    assert "NOT APPLIED" in out and "save" in out and "render" in out, out
    assert "1 of 1 finding(s) are REFUSED" in out.splitlines()[-1], out.splitlines()[-1]


def test_the_cli_says_so_when_there_is_no_pre_index_to_judge_a_move_with():
    """Without the symbol table the check is WEAKER — a move onto another function in the same file
    is invisible to it. Silence there would read exactly like a full pass, which is the failure
    `finalize` exists to prevent."""
    doc = {"format": FORMAT, "title": "t", "goal": "g",
           "components": [{"id": "C1", "name": "A", "source": "a.py:1"},
                          {"id": "C2", "name": "B", "source": "b.py:1"}],
           "edges": [{"src": "C1", "verb": "reads", "dst": "C2", "where": "a.py:245"}]}
    claim = l2_worklist_model(load_model(json.dumps(doc)))[0].claim
    with tempfile.TemporaryDirectory() as td:
        mp, vp = Path(td) / "map.json", Path(td) / "verdicts.json"
        mp.write_text(json.dumps(doc), encoding="utf-8")
        vp.write_text(json.dumps({"grounding": [make_vote(claim, True, "a.py:243")] * 2}),
                      encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert ad.main(["--map", str(mp), "--verdicts", str(vp), "--tolerance", "0"]) == 0
    assert "no `preindex.json` beside" in err.getvalue(), err.getvalue()


def test_a_closer_appeal_is_never_counted_as_a_vote_in_the_drift_tally():
    """A closer re-reads ONE refutation and returns `uphold`/`reject`/`unsure`. It settles whether
    that refutation still blocks the gate; it votes on nothing. `ship` hands the closer files to
    step 2 AND step 3 through the same `--verdicts` list as the skeptics', so counted as a vote a
    single `reject` turns a 1-1 tie into a 2-1 majority and MINTS an anchor correction — which step
    3 (`fix apply-drift --to-reconcile`) writes into `reconcile.json`, where every rebuild replays
    it. A permanent map edit from a row that decides nothing. This tally was the ninth reader of the
    verdict pile and the one that was not split."""
    wl = [make_item("C1 reads E1", "a.py:10")]
    yes = make_vote("C1 reads E1", True, "a.py:60")
    no = make_vote("C1 reads E1", False, "")
    closer = {"claim": "C1 reads E1", "verdict": "reject", "grounded": True}
    assert ad.drift_findings(wl, [yes, no], tolerance=2) == [], "a 1-1 tie is not a majority"
    assert ad.drift_findings(wl, [yes, no, closer], tolerance=2) == [], \
        "and one closer appeal must not turn that tie into one"
    assert ad.drift_records(wl, [yes, no, closer], tolerance=2) == [], \
        "so nothing reaches `fix apply-drift` to be written into reconcile.json"
    # The suppression is of APPEALS, not of evidence: two real skeptics still confirm and still drift.
    assert [w.claim for w, _d in ad.drift_findings(wl, [yes, dict(yes)], tolerance=2)] == ["C1 reads E1"]


def test_a_closer_appeal_alone_does_not_count_as_a_claim_being_challenged():
    """`challenged N of M` means "what the SKEPTICS examined", and an appeal is not an examination.

    The invariant that would have saved the unsplit version — every closer row answers a claim some
    skeptic already voted on — is enforced nowhere. `grounding lint` refuses a `closer-*.json` whose
    rows carry no verdict word; it never checks the claim text against what the skeptics saw. A
    hand-written appeal, a paraphrased claim, or a claim reworded between the wave and the appeal
    each put an uncovered row in the pile, and the count then goes UP because an appeal was heard.
    `finalize` quotes this line into the committed gate block, so it is the one number where "the
    gate did not run" must never read as "the gate passed"."""
    wl = [make_item("C1 reads E1", "a.py:10")]
    closer_only = [{"claim": "C1 reads E1", "verdict": "uphold", "grounded": False}]
    assert "NO verdict" in ad.coverage_note(wl, closer_only), \
        "a claim only an appeal mentions was examined by nobody"
    assert ad.coverage_note(wl, closer_only) == ad.coverage_note(wl, [])
    # A real skeptic vote still counts, with the appeal sitting beside it.
    both = [make_vote("C1 reads E1", False, ""), *closer_only]
    assert "every claim has a verdict" in ad.coverage_note(wl, both)


def test_a_move_DEEPER_INTO_the_same_definition_is_applied():
    """`enclosing_extent` returns the INNERMOST definition, so a class header and a line inside one
    of that class's own methods come back as two different extents. Comparing them with `==` refused
    the header-to-operative-line nudge this command exists for — on reminderrepo's real pre-index,
    `FirebaseAuthService` (a class, 10-40) three lines down into its own `onModuleInit` (12-27). It
    never left the class; it went in. Containment, not equality."""
    ts = make_extents({"svc.ts": [(10, 40, "FirebaseAuthService", "class"),
                                  (12, 27, "onModuleInit", "method"),
                                  (29, 35, "verifyToken", "method")]})
    assert confirmed("svc.ts:10", "svc.ts:13", ts).refusal is None, "class header → inside its method"
    assert confirmed("svc.ts:13", "svc.ts:10", ts).refusal is None, "and the same move outward"
    # mcpolis' real shape, in another language: a closure nested in the function that builds it.
    py = make_extents({"factory.py": [(253, 343, "build_cloud_storage", "function"),
                                      (278, 279, "scoped", "function")]})
    assert confirmed("factory.py:273", "factory.py:279", py).refusal is None
    # Two SIBLING definitions still refuse — containment must not loosen the real cut.
    assert confirmed("svc.ts:13", "svc.ts:30", ts).refusal is not None


#: The six anchor corrections the 2026-09-13 reminderrepo build applied, with the real pre-index
#: extents for each line — the stored anchors recovered from that build's own fragments, the
#: corrected ones from its `reconcile.json`. Carried as DATA because the shipped map has already had
#: them applied: re-judging that map yields zero findings, so the survey behind "4 of 6" cannot be
#: reproduced from the artifact and was reported once as unverifiable.
_REMINDERREPO_2026_09_13: tuple[tuple[str, str, str, list[tuple[int, int, str, str]], bool], ...] = (
    ("C85 calls D27", "inv.page.ts:193", "inv.page.ts:200",
     [(174, 212, "openInvitation", "method")], False),
    ("C104 reads E5", "groups.service.ts:242", "groups.service.ts:237",
     [(230, 249, "getContactsByGroupId", "method")], False),
    ("C146 calls D31", "auto-deploy.sh:87", "auto-deploy.sh:261", [], True),
    ("C43 calls C45", "signup.component.ts:127", "signup.component.ts:172",
     [(87, 144, "signUpWithEmail", "method"), (170, 183, "showModernEmailSentAlert", "method")], True),
    ("C6 calls C1", "activity.model.ts:178", "activity.model.ts:141",
     [(173, 227, "createGenerator", "function"), (138, 163, "serializeActivity", "function")], True),
    ("C158 drives C71", "app.page.ts:23", "app.page.ts:27",
     [(22, 24, "openSideMenu", "method"), (26, 28, "navigateToHome", "method")], True),
)


def test_the_six_reminderrepo_corrections_split_four_refused_two_applied():
    """The claim this rule was justified with, pinned so it stops being unverifiable.

    Two of the six were later confirmed wrong by hand: `C146` moved the Docker-install link onto a
    `docker build` 174 lines away, and `C6` moved "picks and builds the schedule rule" off
    `createGenerator` onto `serializeActivity`. The two APPLIED rows are 7-line and 5-line nudges
    inside one method — the corrections the command exists to make."""
    refused = []
    for claim, stored, corrected, rows, want_refused in _REMINDERREPO_2026_09_13:
        path = stored.rsplit(":", 1)[0]
        d = confirmed(stored, corrected, make_extents({path: rows}))
        assert d.drifted is True, f"{claim} is drift either way"
        assert (d.refusal is not None) is want_refused, f"{claim}: refusal={d.refusal!r}"
        if d.refusal:
            refused.append(claim)
    assert len(refused) == 4 and len(_REMINDERREPO_2026_09_13) == 6, refused
    # C146 is caught by the DISTANCE backstop, not the definition rule: the pre-index carries no
    # extents for `.sh` at all, so an enclosing-definition test alone would have applied it.
    why = confirmed("auto-deploy.sh:87", "auto-deploy.sh:261", make_extents({})).refusal
    assert why is not None and "174 lines away" in why, why


# --- coverage at the pinned worklist's tier ------------------------------------------------------

def test_with_behavioural_counts_the_behavioural_surface_in_the_coverage_line():
    """The gate block quotes `challenged N of M`, and M was the default tier always: a behavioural
    pass read `817 of 833` beside an audit line counting 1782. Only the denominator moves — a
    behaviour claim is never anchor-nudged — so the findings are identical at either tier."""
    doc = {"format": FORMAT, "title": "t", "goal": "g",
           "roles": [{"id": "R1", "name": "Admin", "kind": "human"}],
           "components": [{"id": "C1", "name": "A", "purpose": "checks the token", "source": "a.py:1"},
                          {"id": "C2", "name": "B", "purpose": "keeps rows", "source": "b.py:1"}],
           "use_cases": [{"id": "UC1", "name": "Sign in", "actors": ["R1"],
                          "trigger": "signs in", "outcome": "a session exists"}],
           "flows": [{"uc": "UC1", "title": "Sign in", "steps": [
               {"n": 1, "src": "R1", "dst": "C1", "phrase": "send the token", "where": "a.py:1"}]}]}
    m = load_model(json.dumps(doc))
    narrow, wide = len(l2_worklist_model(m)), len(l2_worklist_model(m, behavioural=True))
    assert narrow < wide
    with tempfile.TemporaryDirectory() as td:
        mp, vp = Path(td) / "map.json", Path(td) / "verdicts.json"
        mp.write_text(json.dumps(doc), encoding="utf-8")
        vp.write_text(json.dumps({"grounding": [make_vote(l2_worklist_model(m)[0].claim, True, "a.py:1")]}),
                      encoding="utf-8")

        def run(*extra: str) -> str:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                assert ad.main(["--map", str(mp), "--verdicts", str(vp), *extra]) == 0
            return buf.getvalue()

        assert f"of {narrow} worklist claim(s)" in run()
        assert f"of {wide} worklist claim(s)" in run("--with-behavioural")
