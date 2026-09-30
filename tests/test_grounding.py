"""`coyomap grounding write` — the record `validate` blocks on, derived instead of hand-tallied."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from coyomap import grounding as G  # noqa: E402
from coyomap.audit_model import l2_worklist_model  # noqa: E402
from coyomap.grounding import build_record, main  # noqa: E402
from coyomap.model import load_model  # noqa: E402


def make_worklist(*claims: str) -> list[str]:
    return list(claims)


def make_votes(*rows: tuple[str, object]) -> list[dict]:
    return [{"claim": c, "grounded": g, "evidence": "a/b.py:1"} for c, g in rows]


def count(rec: dict[str, object], key: str) -> int:
    """One count out of the record, narrowed to `int`.

    The record is `dict[str, object]` because it carries the note and the digest as strings
    alongside the eight counts. Reading a count through here says which keys are numbers, and an
    entry that stops being one fails on the assert with its key named."""
    v = rec[key]
    assert isinstance(v, int), f"grounding record {key!r} is {v!r}, not a count"
    return v


def test_the_four_counts_add_up_to_challenged():
    """The arithmetic `validate` BLOCKS on. Derived, so it cannot drift from the verdicts."""
    rec, errs = build_record(make_worklist("A", "B", "C"),
                             make_votes(("A", True), ("B", False), ("C", "unverifiable")))
    assert not errs
    assert count(rec, "claims_confirmed") + count(rec, "claims_refuted") \
        + count(rec, "claims_unverifiable") == count(rec, "claims_challenged") == 3
    assert (rec["claims_confirmed"], rec["claims_refuted"], rec["claims_unverifiable"]) == (1, 1, 1)


def test_a_tie_is_unverifiable_not_a_silent_win():
    """1-1 is not settled by the code. Crediting either side is the failure the record exists to
    prevent, so an unsettled claim lands in the honest third bucket."""
    rec, errs = build_record(make_worklist("A"), make_votes(("A", True), ("A", False)))
    assert not errs
    assert rec["claims_unverifiable"] == 1 and rec["claims_confirmed"] == 0


def test_it_refuses_a_worklist_snapshot_the_verdicts_do_not_match():
    """The snapshot problem, reproduced from a live build: re-deriving the worklist AFTER the
    refutations are applied leaves verdicts referring to claims the map no longer holds, and the
    resulting record makes `claims_challenged` exceed `claims_total` — which `validate` blocks on."""
    _rec, errs = build_record(make_worklist("A"), make_votes(("A", True), ("GONE", False)))
    assert any("not in the pinned worklist" in e for e in errs)


def test_it_refuses_when_a_claim_has_no_verdict():
    """"The gate did not run" must never read as "the gate passed" — an unchallenged claim would
    otherwise be silently excluded and the pass would read as complete."""
    _rec, errs = build_record(make_worklist("A", "B"), make_votes(("A", True)))
    assert any("have NO verdict" in e for e in errs)


# --- a DELIBERATE partial pass (`--partial`) ---------------------------------------

def make_partial_pass(partial: bool, note: str = "top of the ranked worklist, 1 of 3"):
    """Three ranked claims, one challenged — the shape of every real budget-limited pass."""
    return build_record(make_worklist("A", "B", "C"), make_votes(("A", True)),
                        note=note, partial=partial)


def test_a_partial_pass_keeps_the_FULL_surface_in_claims_total():
    """The number that matters. The old workaround — shrink the pinned worklist to what you
    challenged — put `1` here, so a 319-of-1608 pass shipped looking like a complete pass over a
    small map and the real surface survived only in prose no gate can read."""
    rec, errs = make_partial_pass(True)
    assert not errs, errs
    assert rec["claims_total"] == 3
    assert rec["claims_challenged"] == 1


def test_a_partial_record_still_satisfies_the_arithmetic_validate_blocks_on():
    # confirmed + refuted + unverifiable == challenged, NOT == total. The counts were always right
    # for a partial pass; only the refusal stood in the way.
    rec, _ = make_partial_pass(True)
    split = sum(int(rec[k]) for k in  # type: ignore[call-overload]
                ("claims_confirmed", "claims_refuted", "claims_unverifiable"))
    assert split == rec["claims_challenged"]


def test_partial_needs_a_note_saying_what_was_prioritized():
    """Counts say how many were challenged, never why those ones. Without that, a deliberate pass
    and an abandoned one are the same record."""
    _rec, errs = make_partial_pass(True, note="   ")
    assert any("needs a `--note`" in e for e in errs)


def test_partial_on_a_COMPLETE_pass_is_refused():
    """A finished verification that calls itself partial understates itself, and the next reader
    cannot tell which it was."""
    _rec, errs = build_record(make_worklist("A"), make_votes(("A", True)),
                              note="all of it", partial=True)
    assert any("every worklist claim has a verdict" in e for e in errs)


def test_partial_does_NOT_lift_the_wrong_snapshot_refusal():
    """The flag says "I challenged a subset on purpose" — it says nothing about verdicts for claims
    that were never in the worklist, which is the snapshot bug and still fatal."""
    _rec, errs = build_record(make_worklist("A", "B"), make_votes(("A", True), ("GONE", False)),
                             note="top slice", partial=True)
    assert any("not in the pinned worklist" in e for e in errs)


def test_without_the_flag_the_refusal_names_the_way_forward():
    # A refusal an operator cannot act on is where the hand-written record comes back.
    _rec, errs = make_partial_pass(False)
    assert any("--partial" in e and "--note" in e for e in errs)


def test_cli_writes_a_fragment_that_is_a_grounding_block():
    with tempfile.TemporaryDirectory() as td:
        _cli_writes_a_fragment(Path(td))


def _cli_writes_a_fragment(tmp_path: Path) -> None:
    wl = tmp_path / "audit.json"
    wl.write_text(json.dumps({"worklist": [{"claim": "A"}, {"claim": "B"}]}), encoding="utf-8")
    vd = tmp_path / "v.json"
    vd.write_text(json.dumps({"grounding": [
        {"claim": "A", "grounded": True, "evidence": "a.py:1"},
        {"claim": "B", "grounded": False}]}), encoding="utf-8")
    out = tmp_path / "grounding.json"
    assert main(["write", "--worklist", str(wl), "--verdicts", str(vd), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert set(payload) == {"grounding"}
    assert payload["grounding"]["claims_total"] == 2
    assert payload["grounding"]["claims_refuted"] == 1


def test_cli_exits_nonzero_when_it_refuses():
    """A refusal that exits 0 is the "printed an error and claimed success" failure."""
    with tempfile.TemporaryDirectory() as td:
        _cli_exits_nonzero(Path(td))


def _cli_exits_nonzero(tmp_path: Path) -> None:
    wl = tmp_path / "audit.json"
    wl.write_text(json.dumps({"worklist": [{"claim": "A"}, {"claim": "B"}]}), encoding="utf-8")
    vd = tmp_path / "v.json"
    vd.write_text(json.dumps({"grounding": [{"claim": "A", "grounded": True}]}), encoding="utf-8")
    assert main(["write", "--worklist", str(wl), "--verdicts", str(vd)]) == 1


def test_cli_partial_flag_writes_the_record_the_bare_run_refuses():
    """The same inputs, through the real CLI: refused without the flag, written with it — and the
    written record keeps the full surface in `claims_total`."""
    with tempfile.TemporaryDirectory() as td:
        _cli_partial_flag(Path(td))


def _cli_partial_flag(tmp_path: Path) -> None:
    wl = tmp_path / "audit.json"
    wl.write_text(json.dumps({"worklist": [{"claim": "A"}, {"claim": "B"}, {"claim": "C"}]}),
                  encoding="utf-8")
    vd = tmp_path / "v.json"
    vd.write_text(json.dumps({"grounding": [{"claim": "A", "grounded": True}]}), encoding="utf-8")
    out = tmp_path / "grounding.json"
    base = ["write", "--worklist", str(wl), "--verdicts", str(vd), "--out", str(out)]
    assert main(base) == 1                       # no flag -> refused, as before
    assert not out.exists()                      # a refusal writes nothing
    assert main([*base, "--partial", "--note", "ranked top-down; 1 of 3 in budget"]) == 0
    rec = json.loads(out.read_text(encoding="utf-8"))["grounding"]
    assert (rec["claims_total"], rec["claims_challenged"]) == (3, 1)
    assert "1 of 3" in rec["note"]


# --- grounding report, skeptic ids, and the stale pin ------------------------------------------


def test_report_lists_which_claims_were_refuted_not_only_how_many():
    """`write` resolves every claim and emits four counts, so a build that must reconcile each
    refutation had nothing to read — one hand-wrote a 12-line vote aggregator one turn later."""
    claims = ["C1 calls C2", "C3 reads E1", "C4 persists E2"]
    rows = [{"claim": "C1 calls C2", "grounded": True, "evidence": "a.py:1"},
            {"claim": "C3 reads E1", "grounded": False, "evidence": "b.py:2",
             "note": "b.py:2 writes, it never reads"},
            {"claim": "C4 persists E2", "grounded": "unverifiable", "evidence": ""}]
    out = G.format_report(claims, rows)
    assert "REFUTED" in out and "C3 reads E1" in out
    assert "UNVERIFIABLE" in out and "C4 persists E2" in out
    assert "C1 calls C2" not in out.split("confirmed:")[0], "a confirmed claim is not a worklist item"
    assert "confirmed: 1 of 3" in out


def test_report_separates_a_tie_from_a_stated_unverifiable():
    """`_verdict_bucket` files both under `unverifiable` — right for the count, wrong for the
    reader. A live build's grounding note described four unverifiables as one kind when two were
    the other."""
    claims = ["C1 calls C2"]
    rows = [{"claim": "C1 calls C2", "grounded": True, "evidence": "a.py:1", "skeptic": "sec-a"},
            {"claim": "C1 calls C2", "grounded": False, "evidence": "a.py:9", "skeptic": "sec-b"}]
    out = G.format_report(claims, rows)
    assert "TIED" in out
    assert "1 for / 1 against" in out
    assert "sec-a" in out and "sec-b" in out


def test_report_names_the_claims_that_were_never_challenged():
    out = G.format_report(["C1 calls C2", "C3 reads E1"],
                          [{"claim": "C1 calls C2", "grounded": True, "evidence": "a.py:1"}])
    assert "NO VERDICT" in out and "C3 reads E1" in out


def test_two_skeptics_agreeing_are_not_reported_as_a_duplicate_row():
    """The method PRESCRIBES a double read of the security claims, and the note used to tell the
    build to "drop one" for doing exactly what it was asked to do."""
    from coyomap.anchor_drift import load_verdicts
    with tempfile.TemporaryDirectory() as tmp:
        rows = [{"claim": "C1 calls C2", "grounded": True, "evidence": "a.py:1"}]
        a, b = Path(tmp) / "v-a.json", Path(tmp) / "v-b.json"
        a.write_text(json.dumps({"grounding": [{**rows[0], "skeptic": "sec-a"}]}), encoding="utf-8")
        b.write_text(json.dumps({"grounding": [{**rows[0], "skeptic": "sec-b"}]}), encoding="utf-8")
        _loaded, notes = load_verdicts([str(a), str(b)])
        assert notes == [], notes


def test_the_same_skeptic_id_in_two_files_is_still_reported():
    from coyomap.anchor_drift import load_verdicts
    with tempfile.TemporaryDirectory() as tmp:
        row = {"claim": "C1 calls C2", "grounded": True, "evidence": "a.py:1", "skeptic": "sec-a"}
        a, b = Path(tmp) / "v-a.json", Path(tmp) / "agg.json"
        a.write_text(json.dumps({"grounding": [row]}), encoding="utf-8")
        b.write_text(json.dumps({"grounding": [row]}), encoding="utf-8")
        _loaded, notes = load_verdicts([str(a), str(b)])
        assert len(notes) == 1 and "SAME `skeptic` id" in notes[0]


def test_the_record_states_the_delta_when_given_the_live_map():
    """Without `--map` the record cannot say how the shipped map differs from the pinned worklist,
    and a build had no legal answer to the staleness advisory."""
    from coyomap.grounding import build_record, live_claims_digest
    pinned = ["a", "b", "c"]
    rows = [{"claim": c, "grounded": True, "evidence": "f.py:1"} for c in pinned]
    live = ["a", "b", "d"]                       # c was reconciled away; d was authored since
    rec, errors = build_record(pinned, rows, live_claims=live)
    assert not errors
    assert rec["claims_total"] == 3 and rec["claims_challenged"] == 3
    assert rec["claims_superseded"] == 1 and rec["claims_added_since"] == 1
    assert rec["live_claims_digest"] == live_claims_digest(live)


def test_without_the_live_map_the_record_is_exactly_as_before():
    """`--map` is optional: a build that never reconciles a count-changing refutation needs none of
    this, and its record must not grow fields it cannot fill honestly."""
    from coyomap.grounding import build_record
    pinned = ["a", "b"]
    rows = [{"claim": c, "grounded": True, "evidence": "f.py:1"} for c in pinned]
    rec, errors = build_record(pinned, rows)
    assert not errors
    for field in ("claims_superseded", "claims_added_since", "live_claims_digest",
                  "claims_live_challenged"):
        assert field not in rec, field


def make_reworded_pass() -> dict:
    """A COMPLETE pass whose map was then reworded — the shape that shipped 209 of 209 over 199.

    Three claims pinned and all three voted; the build then rewords `c` into `c-narrowed`, so the
    shipped map carries a claim no skeptic saw while every pinned count stays true."""
    from coyomap.grounding import build_record
    pinned = ["a", "b", "c"]
    rows = [{"claim": c, "grounded": True, "evidence": "f.py:1"} for c in pinned]
    rec, errors = build_record(pinned, rows, live_claims=["a", "b", "c-narrowed"])
    assert not errors
    return rec


def test_the_record_states_how_much_of_the_SHIPPED_map_was_challenged():
    """The pinned counts cannot say it, and a build read them as if they could.

    `claims_challenged == claims_total` here and is RIGHT: all three pinned claims were voted. The
    shipped map still carries one claim with no verdict, and nothing recorded that."""
    rec = make_reworded_pass()
    assert rec["claims_total"] == 3 and rec["claims_challenged"] == 3
    assert rec["claims_live_challenged"] == 2


def test_live_challenged_is_measured_not_derived_from_the_pinned_counts():
    """`claims_total - claims_superseded` is the tempting derivation, and it is wrong under
    `--partial`: there the unvoted and the superseded claims overlap by an amount no pinned count
    records. `c` is both superseded and unvoted; `b` is live and unvoted."""
    from coyomap.grounding import build_record
    pinned = ["a", "b", "c"]
    rows = [{"claim": "a", "grounded": True, "evidence": "f.py:1"}]
    rec, errors = build_record(pinned, rows, live_claims=["a", "b"], partial=True,
                               note="only the top of the ranked worklist")
    assert not errors
    assert rec["claims_live_challenged"] == 1                    # only `a` has a verdict
    # …while the tempting derivation says 2. `build_record` returns `dict[str, object]`, so the
    # subtraction is spelled through `int()` rather than on the raw values.
    assert int(str(rec["claims_total"])) - int(str(rec["claims_superseded"])) == 2


def test_a_complete_pass_over_an_unchanged_map_reports_full_live_coverage():
    """It must not cry wolf on the ordinary case, which is every build that rewords nothing."""
    from coyomap.grounding import build_record
    pinned = ["a", "b"]
    rows = [{"claim": c, "grounded": True, "evidence": "f.py:1"} for c in pinned]
    rec, errors = build_record(pinned, rows, live_claims=["a", "b"])
    assert not errors
    assert rec["claims_live_challenged"] == 2 == rec["claims_total"]


def test_the_digest_ignores_order_and_duplication():
    """Both sides are counted over the de-duplicated claim SET — two sides counted by different
    rules measure the rule instead of the map."""
    from coyomap.grounding import live_claims_digest
    assert live_claims_digest(["b", "a"]) == live_claims_digest(["a", "b"])
    assert live_claims_digest(["a", "a", "b"]) == live_claims_digest(["a", "b"])
    assert live_claims_digest(["a", "b"]) != live_claims_digest(["a", "c"])


def test_the_pinned_split_is_never_recomputed_against_the_live_map():
    """The `refuted 0` trap, pinned as a test. The claims a reconcile deletes are exactly the
    REFUTED ones, so a split measured against the live worklist reports that nothing was ever found
    wrong. The split must stay pinned no matter what `--map` says."""
    from coyomap.grounding import build_record
    pinned = ["kept", "refuted-and-rewritten"]
    rows = [{"claim": "kept", "grounded": True, "evidence": "f.py:1"},
            {"claim": "refuted-and-rewritten", "grounded": False, "note": "wrong"}]
    rec, _ = build_record(pinned, rows, live_claims=["kept", "the rewritten form"])
    assert rec["claims_refuted"] == 1, "the refutation must survive the live comparison"
    assert rec["claims_superseded"] == 1


def test_the_digest_is_not_ambiguous_about_where_a_claim_ends():
    """A separator that can appear inside a claim makes the digest ambiguous: newline-joined,
    `["a\\nb"]` hashed identically to `["a", "b"]`. No claim carries a newline today, which is why
    it was worth removing before one does."""
    from coyomap.grounding import live_claims_digest
    assert live_claims_digest(["a\nb"]) != live_claims_digest(["a", "b"])


def test_report_lists_which_claims_were_superseded():
    """The record says how MANY claims the reconcile removed; nothing could say WHICH, and the whole
    design rests on those being the refuted ones. `--map` used to be accepted and discarded here."""
    import contextlib
    import io
    import json as _json
    import tempfile
    from pathlib import Path
    from coyomap import grounding
    with tempfile.TemporaryDirectory() as tmp:
        wl = Path(tmp) / "wl.json"
        wl.write_text(_json.dumps({"worklist": [{"claim": c} for c in
                                                ("kept", "reconciled-away", "confirmed-then-cut")]}))
        v = Path(tmp) / "v.json"
        v.write_text(_json.dumps({"grounding": [
            {"claim": "kept", "grounded": True, "evidence": "f.py:1"},
            {"claim": "reconciled-away", "grounded": False, "note": "wrong"},
            {"claim": "confirmed-then-cut", "grounded": True, "evidence": "g.py:2"}]}))
        m = Path(tmp) / "m.json"
        m.write_text(_json.dumps({"format": "coyomap-map", "title": "T", "goal": "g",
                                  "components": [{"id": "C1", "name": "A", "source": "f.py:1"}]}))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = grounding.main(["report", "--worklist", str(wl), "--verdicts", str(v),
                                   "--map", str(m)])
        out = buf.getvalue()
    assert code == 0, out
    assert "SUPERSEDED (3)" in out, out
    # the one that was CONFIRMED and cut anyway is the interesting case, and is called out
    assert "confirmed-then-cut" in out and "was CONFIRMED" in out, out
    assert "CONFIRMED — the build rewrote a claim the skeptics had settled" in out, out


def make_report(pinned: list[str], rows: list[dict], live: list[str] | None) -> str:
    from coyomap.grounding import format_report
    return format_report(pinned, rows, live_claims=live)


def test_an_unvoted_claim_can_be_superseded_too():
    """The unvoted branch returned before the superseded check, so the report listed FEWER
    superseded claims than `write --map` counted — silently, in the tool the record points a reader
    at to see which."""
    pinned = ["kept", "never-challenged-and-cut"]
    rows = [{"claim": "kept", "grounded": True, "evidence": "f.py:1"}]
    text = make_report(pinned, rows, live=["kept"])
    assert "SUPERSEDED (1)" in text and "never-challenged-and-cut" in text


def test_only_a_confirmed_verdict_counts_as_settled():
    """A tie is by definition unsettled — the report's own next section says "the skeptics split;
    adjudicate against the code" — and an unverifiable verdict says the code could not answer.
    Calling all three "settled" over-claimed on two of them."""
    pinned = ["tied-and-cut", "unverifiable-and-cut", "confirmed-and-cut"]
    rows = [{"claim": "tied-and-cut", "grounded": True, "evidence": "a.py:1"},
            {"claim": "tied-and-cut", "grounded": False},
            {"claim": "unverifiable-and-cut", "grounded": "unverifiable"},
            {"claim": "confirmed-and-cut", "grounded": True, "evidence": "b.py:2"}]
    text = make_report(pinned, rows, live=[])
    assert "1 of these was CONFIRMED" in text, text
    assert "2 were never settled" in text, text


def test_the_superseded_list_shows_the_vote_split():
    """2-1 and 3-0 read identically without it — and a live report described a 2-1 override as
    "three skeptics agreed"."""
    pinned = ["c"]
    rows = [{"claim": "c", "grounded": True, "evidence": "a.py:1"},
            {"claim": "c", "grounded": True, "evidence": "a.py:1"},
            {"claim": "c", "grounded": False}]
    assert "[2 for / 1 against]" in make_report(pinned, rows, live=[])


def test_report_names_a_refutation_the_superseded_count_cannot_witness():
    """`claims_superseded` counts pinned claims the shipped map no longer carries, and the design
    reads that as "the refutations landed". A refutation can be reconciled WITHOUT changing the
    claim's rendered text: on a live build `E35 (UpstreamState) has states […] with 10
    transition(s)` was refuted, the wrong transition was corrected, and the claim string came out
    identical — 5 refutations, 4 superseded. The digest cannot witness that fifth fix at all, so a
    build that "corrected" it by doing nothing would produce the same digest."""
    claims = ["C1 calls C2", "E35 has states [a, b] with 10 transition(s)"]
    rows = [{"claim": "C1 calls C2", "grounded": False, "evidence": "a.py:1"},
            {"claim": "E35 has states [a, b] with 10 transition(s)", "grounded": False,
             "evidence": "s.py:41", "note": "the live -> deferred transition has no code path"}]
    # C1 calls C2 was DROPPED by the reconcile; the E35 claim still renders identically.
    live = ["E35 has states [a, b] with 10 transition(s)"]
    out = G.format_report(claims, rows, live_claims=live)
    assert "SUPERSEDED (1)" in out, out
    assert "REFUTED BUT NOT SUPERSEDED (1)" in out, out
    assert "E35 has states" in out.split("REFUTED BUT NOT SUPERSEDED")[1]


def test_report_says_nothing_extra_when_every_refutation_was_superseded():
    """The normal case must stay quiet, or the line becomes noise a build learns to skip."""
    claims = ["C1 calls C2"]
    rows = [{"claim": "C1 calls C2", "grounded": False, "evidence": "a.py:1"}]
    out = G.format_report(claims, rows, live_claims=[])
    assert "SUPERSEDED (1)" in out
    assert "NOT SUPERSEDED" not in out


# --- the note, without the shell -------------------------------------------------
# `--note` is required, so a re-run (the ordinary case: the record is re-measured after a late fix)
# had to re-supply the whole note. A live build did it through a nested `$(python -c …)` that
# pushed ~1900 characters back through the shell — it survived, but a note containing a quote or a
# backtick would not have.


def make_write_inputs(td: str) -> tuple[str, str]:
    wl = Path(td) / "worklist.json"
    wl.write_text(json.dumps({"worklist": [{"claim": "C1 calls C2"}]}), encoding="utf-8")
    vd = Path(td) / "verdicts.json"
    vd.write_text(json.dumps({"grounding": [
        {"claim": "C1 calls C2", "grounded": True, "evidence": "a.py:1"}]}), encoding="utf-8")
    return str(wl), str(vd)


def test_note_file_carries_a_note_the_shell_would_have_mangled():
    tricky = 'has a "quote", a `backtick` and a $(subshell)'
    with tempfile.TemporaryDirectory() as td:
        wl, vd = make_write_inputs(td)
        nf = Path(td) / "note.txt"
        nf.write_text(tricky, encoding="utf-8")
        out = Path(td) / "grounding.json"
        assert main(["write", "--worklist", wl, "--verdicts", vd, "--out", str(out),
                     "--note-file", str(nf)]) == 0
        assert json.loads(out.read_text())["grounding"]["note"] == tricky


def test_keep_note_reuses_the_note_already_written():
    with tempfile.TemporaryDirectory() as td:
        wl, vd = make_write_inputs(td)
        out = Path(td) / "grounding.json"
        assert main(["write", "--worklist", wl, "--verdicts", vd, "--out", str(out),
                     "--note", "the original reasoning"]) == 0
        # the re-run, with no note re-supplied
        assert main(["write", "--worklist", wl, "--verdicts", vd, "--out", str(out),
                     "--keep-note"]) == 0
        assert json.loads(out.read_text())["grounding"]["note"] == "the original reasoning"


def test_keep_note_refuses_when_there_is_no_prior_note(capsys):
    with tempfile.TemporaryDirectory() as td:
        wl, vd = make_write_inputs(td)
        out = Path(td) / "grounding.json"
        assert main(["write", "--worklist", wl, "--verdicts", vd, "--out", str(out),
                     "--keep-note"]) == 2
        assert "found no note" in capsys.readouterr().err


def test_keep_note_and_note_file_together_are_refused(capsys):
    with tempfile.TemporaryDirectory() as td:
        wl, vd = make_write_inputs(td)
        nf = Path(td) / "note.txt"
        nf.write_text("x", encoding="utf-8")
        assert main(["write", "--worklist", wl, "--verdicts", vd, "--out",
                     str(Path(td) / "g.json"), "--keep-note", "--note-file", str(nf)]) == 2
        assert "Pick one" in capsys.readouterr().err


def test_a_worklist_given_as_a_bare_list_is_read_not_crashed_on():
    """`coyomap audit --json | jq .worklist` yields a BARE LIST, which is the obvious way to hand
    this command its input — and it crashed with an AttributeError traceback.

    The list case was already intended: the `isinstance` test existed. It sat inside the default
    argument of `.get()`, so reaching it required the very attribute access that had already
    raised. A guard in an unreachable position is not a guard, and the one input shape it was
    written for was the one that failed."""
    import json, tempfile, os
    from coyomap.grounding import _worklist_claims
    from pathlib import Path
    rows = [{"claim": "C1 calls C2", "anchor": "a.py:1"}, {"claim": "C2 writes E1"}]
    with tempfile.TemporaryDirectory() as d:
        bare = Path(d) / "bare.json"
        bare.write_text(json.dumps(rows))
        wrapped = Path(d) / "wrapped.json"
        wrapped.write_text(json.dumps({"worklist": rows}))
        assert _worklist_claims(bare) == ["C1 calls C2", "C2 writes E1"]
        assert _worklist_claims(wrapped) == _worklist_claims(bare), \
            "both shapes must read identically — the wrapper is presentation, not meaning"


def _write(tmp, name, obj):
    import json
    from pathlib import Path
    p = Path(tmp) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))
    return str(p)


def test_lint_catches_the_quoted_boolean_at_the_skeptic_not_a_hundred_turns_later():
    """`grounding write` already refuses this — at the END of the build, where the skeptic that
    produced it finished long ago. One live build shipped 40 rows with `grounded` as the STRING
    "true" and paid four turns of hand-repair on the critical path. The skeptic's own self-check
    could not have caught it: printing str(value) renders 'true' for a string and a boolean alike."""
    import tempfile
    from coyomap.grounding import lint_verdicts
    with tempfile.TemporaryDirectory() as d:
        bad = _write(d, "v.json", {"grounding": [
            {"claim": "c", "grounded": "true", "evidence": "a.py:1", "skeptic": "s", "note": "n"}]})
        assert any("unrecognised" in p for p in lint_verdicts([bad]).problems)
        good = _write(d, "g.json", {"grounding": [
            {"claim": "c", "grounded": True, "evidence": "a.py:1", "skeptic": "s", "note": "n"},
            {"claim": "d", "grounded": "unverifiable", "evidence": "b.py:2", "skeptic": "s",
             "note": "n"}]})
        assert not lint_verdicts([good]).problems, "both legal shapes must pass"


def test_lint_catches_a_note_claiming_a_read_the_agent_never_made():
    """The worst thing a retrospective found: a skeptic settled 40 claims in 95 seconds from one
    directory-wide grep, generated every row from a script, and opened each note `Read <file>:` for
    files it never opened. Forty fabricated confirmations reached a shipped grounding record and
    nothing in the toolchain could see them. The agent's own transcript can."""
    import tempfile, json
    from pathlib import Path
    from coyomap.grounding import lint_verdicts
    with tempfile.TemporaryDirectory() as d:
        agents = Path(d) / "agents"
        agents.mkdir()
        (agents / "agent-a1.jsonl").write_text(json.dumps(
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash",
                 "input": {"command": "sed -n 1,60p db/schema/workspaces.ts"}}]}}) + "\n")
        v = _write(d, "v.json", {"grounding": [
            {"claim": "c1", "grounded": True, "evidence": "x:1", "skeptic": "a1",
             "note": "Read db/schema/workspaces.ts: it does"},
            {"claim": "c2", "grounded": True, "evidence": "y:1", "skeptic": "a1",
             "note": "Read db/schema/never_opened.ts: it does"}]})
        problems = lint_verdicts([v], agents).problems
        assert any("never_opened.ts" in p for p in problems), problems
        assert not any("workspaces.ts" in p for p in problems), \
            "the file it really did open must not be accused"


# --- `--verdicts` is variadic, as the usage line always said -----------------------
# Usage prints `--verdicts <raw.json>...`. It took exactly one value, so the documented spelling
# died on `unknown option(s): b.json` — while `write` and `report` are routinely handed thirty
# files. A retrospective following the printed usage got an error instead of a run.


def _verdict_file(tmp: Path, name: str, claim: str) -> Path:
    p = tmp / name
    p.write_text(json.dumps({"grounding": [
        {"claim": claim, "grounded": True, "evidence": "a.py:1", "skeptic": name}]}),
        encoding="utf-8")
    return p


def test_verdicts_accepts_several_paths_after_one_flag():
    from coyomap.grounding import main
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        a = _verdict_file(tmp, "a.json", "claim one")
        b = _verdict_file(tmp, "b.json", "claim two")
        # `env={}`: no session, so the lint reads no transcripts. Without it these two files' `a.py`
        # citation was checked against whatever sub-agents the RUNNING Claude Code session had spawned.
        assert main(["lint", "--verdicts", str(a), str(b)], env={}) == 0


def test_the_repeated_flag_form_still_works():
    from coyomap.grounding import main
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        a = _verdict_file(tmp, "a.json", "claim one")
        b = _verdict_file(tmp, "b.json", "claim two")
        assert main(["lint", "--verdicts", str(a), "--verdicts", str(b)], env={}) == 0


def test_a_flag_after_the_paths_is_still_a_flag():
    """The swallow stops at the next `-`, or `--verdicts a.json --json` would eat the `--json`."""
    from coyomap.grounding import main
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        a = _verdict_file(tmp, "a.json", "claim one")
        agents = tmp / "agents"
        agents.mkdir()
        (agents / "agent-1.jsonl").write_text(
            json.dumps({"message": {"content": [{"type": "tool_use", "name": "Read",
                                                       "input": {"file_path": "a.py"}}]}}) + "\n", encoding="utf-8")
        assert main(["lint", "--verdicts", str(a), "--agent-transcripts", str(agents)]) == 0


def test_the_evidence_check_tests_a_row_that_cites_its_anchor_only_in_evidence(capsys):
    """The widening, and it is most of this check. `note` prose of the shape `read <file>` covered
    20 of 1000 rows on a measured build, because most skeptics cite the anchor in `evidence` and
    describe the reading in words. `evidence` is a bare `path:line` on every row, and citing a file
    you never opened is exactly the shape this exists to catch — the fabricating pass put a
    real-looking anchor on all forty of its rows."""
    from coyomap.grounding import main
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        p = tmp / "v.json"
        p.write_text(json.dumps({"grounding": [
            {"claim": "c1", "grounded": True, "evidence": "a.py:1", "skeptic": "s",
             "note": "the anchor is the operative line"},
            {"claim": "c2", "grounded": True, "evidence": "ghost.py:2", "skeptic": "s",
             "note": "the anchor is the operative line"}]}), encoding="utf-8")
        agents = tmp / "agents"
        agents.mkdir()
        (agents / "agent-1.jsonl").write_text(json.dumps(
            {"message": {"content": [{"type": "tool_use", "name": "Read",
                                      "input": {"file_path": "/repo/a.py"}}]}}) + "\n",
            encoding="utf-8")
        assert main(["lint", "--verdicts", str(p),
                     "--agent-transcripts", str(agents)]) == 1
        out = capsys.readouterr()
        # the fabricated one is named; `a.py` was really opened, so it is not
        assert "ghost.py" in out.err and "a.py:" not in out.err


def test_a_SYMBOL_anchor_is_not_read_as_a_missing_file(capsys):
    """`evidence` also carries symbol references — `ServiceTokenService.mint` — which are
    `Word.word` and match any "token dot token" rule. Reading eleven of those as unopened files was
    the first thing the widening did on a real pass."""
    from coyomap.grounding import main
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        p = tmp / "v.json"
        p.write_text(json.dumps({"grounding": [
            {"claim": "c1", "grounded": True, "evidence": "ServiceTokenService.mint",
             "skeptic": "s", "note": "read MongoOAuthStateRepository.save"}]}), encoding="utf-8")
        agents = tmp / "agents"
        agents.mkdir()
        (agents / "agent-1.jsonl").write_text("{}\n", encoding="utf-8")
        assert main(["lint", "--verdicts", str(p), "--agent-transcripts", str(agents)]) == 0
        out = capsys.readouterr()
        assert "ServiceTokenService" not in out.out + out.err


def test_a_file_only_PRINTED_by_a_grep_is_a_note_and_does_not_fail_the_lint(capsys):
    """The `opened` set used to be every filename-shaped token anywhere in the transcript — 477
    names against 17 files actually opened, on one measured skeptic. A directory-wide grep prints
    hundreds of paths, and a grep is what the fabricating skeptic used. The two sets are kept apart:
    absent from both is a problem, present only as text is a NOTE, because a skeptic may read a
    range through a shell verb this cannot see and a signal that fails the lint teaches the next
    agent to route around it."""
    from coyomap.grounding import main
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        p = tmp / "v.json"
        p.write_text(json.dumps({"grounding": [
            {"claim": "c1", "grounded": True, "evidence": "printed.py:1", "skeptic": "s",
             "note": "the anchor is the operative line"}]}), encoding="utf-8")
        agents = tmp / "agents"
        agents.mkdir()
        (agents / "agent-1.jsonl").write_text(json.dumps(
            {"message": {"content": [{"type": "text",
                                      "text": "grep printed 'printed.py' among others"}]}}) + "\n",
            encoding="utf-8")
        assert main(["lint", "--verdicts", str(p), "--agent-transcripts", str(agents)]) == 0
        out = capsys.readouterr()
        assert "only as TEXT" in out.out + out.err


def test_lint_says_how_much_of_the_pass_the_evidence_check_could_test(capsys):
    """It printed the same line with and without `--agent-transcripts`, so a run that tested 16 of
    949 rows and a run that tested none were indistinguishable."""
    from coyomap.grounding import main
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        p = tmp / "v.json"
        p.write_text(json.dumps({"grounding": [
            {"claim": "c1", "grounded": True, "evidence": "a.py:1", "skeptic": "s",
             "note": "Read a.py and it holds"},
            {"claim": "c2", "grounded": True, "evidence": "b.py:2", "skeptic": "s",
             "note": "the anchor is the operative line"}]}), encoding="utf-8")
        (tmp / "agents").mkdir()
        (tmp / "agents" / "agent-1.jsonl").write_text("\n".join(
            json.dumps({"message": {"content": [{"type": "tool_use", "name": "Read",
                                                 "input": {"file_path": f"/repo/{f}"}}]}})
            for f in ("a.py", "b.py")) + "\n", encoding="utf-8")
        assert main(["lint", "--verdicts", str(p),
                     "--agent-transcripts", str(tmp / "agents")]) == 0
        out = capsys.readouterr().out
        assert "2 verdict row(s)" in out
        # BOTH rows are testable now: the second cites `b.py:2` in `evidence`, which the check
        # could not read while it only understood `read <file>` prose.
        assert "covered 2 of 2 row(s)" in out


# --- retro 2026-08-18, findings 0 and 21/A1 ------------------------------------------

def test_refuted_claims_still_in_the_map_are_named_at_BOTH_ends_of_the_report():
    """Two opposite narrowings hid two ends of one section on the same build.

    `grounding report | tail -40` started inside the refuted list, so the
    `REFUTED BUT NOT SUPERSEDED` header was cut off the top. `| head -30` ended after the third of
    that section's five bullets. The lead fixed the three it could see, wrote "Three refuted rules
    still carry their original wording", and two refuted claims shipped in the map. The report is
    hundreds of lines, so narrowing it is reasonable; the count must therefore survive either cut.
    """
    claims = ["C1 calls C2", "C3 reads E1"]
    rows = [{"claim": "C1 calls C2", "grounded": True, "evidence": "a.py:1"},
            {"claim": "C3 reads E1", "grounded": False, "evidence": "b.py:2"}]
    # `live_claims` still carries the refuted claim: the reconcile never removed it.
    out = G.format_report(claims, rows, live_claims=["C1 calls C2", "C3 reads E1"])
    lines = [ln for ln in out.splitlines() if ln.strip()]

    assert "REFUTED CLAIM(S) STILL IN THE MAP" in lines[0], (
        "a `| head -N` reader must see it on the first line:\n" + out)
    assert "STILL IN THE MAP" in lines[-1] and "C3 reads E1" in lines[-1], (
        "a `| tail -N` reader must see it on the last line:\n" + out)

    # A clean run must NOT end on a scary line it has no reason to print.
    clean = G.format_report(claims, [{"claim": c, "grounded": True, "evidence": "a.py:1"}
                                     for c in claims], live_claims=claims)
    assert "STILL IN THE MAP" not in clean, clean


def test_write_prints_the_numbers_a_note_will_cite(tmp_path: Path):
    """`--note` is free prose in a permanent record and nothing checks it.

    One shipped note said "Eighteen fresh-context skeptics" about a build that dispatched 17 and
    produced 20 verdict labels, because 18 was read off a `grounding lint` line printed while a
    verdict file was still being written. The same note said "Four superseded claims had been
    CONFIRMED" where the report counts 11, leaving seven overrides of settled verdicts
    undisclosed. Both numbers exist here, at the moment the note is written.
    """
    claims = ["C1 calls C2", "C3 reads E1"]
    rows = [{"claim": "C1 calls C2", "grounded": True, "evidence": "a.py:1", "skeptic": "sec-a"},
            {"claim": "C1 calls C2", "grounded": True, "evidence": "a.py:1", "skeptic": "sec-b"},
            {"claim": "C3 reads E1", "grounded": True, "evidence": "b.py:2", "skeptic": "own-1"}]
    wl = tmp_path / "wl.json"
    wl.write_text(json.dumps({"worklist": [{"claim": c} for c in claims]}), encoding="utf-8")
    vd = tmp_path / "v.json"
    vd.write_text(json.dumps({"grounding": rows}), encoding="utf-8")
    mp = tmp_path / "map.json"
    # The shipped map no longer carries "C1 calls C2" -> superseded, and it was CONFIRMED.
    mp.write_text(json.dumps({
        "format": "coyomap-map", "title": "T", "goal": "g", "commit": "abc1234",
        "components": [{"id": "C3", "name": "C3", "purpose": "p"}],
        "entities": [{"id": "E1", "name": "E1", "meaning": "m"}],
        "edges": [{"src": "C3", "verb": "reads", "dst": "E1", "why": "w", "where": "b.py:2"}],
    }), encoding="utf-8")

    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(["write", "--worklist", str(wl), "--verdicts", str(vd),
                     "--map", str(mp), "--out", str(tmp_path / "g.json"), "--note", "probe"])
    out = buf.getvalue()
    assert code == 0, out
    assert "NOTE FACTS" in out, out
    assert "distinct skeptic labels 3" in out, (
        "the label count is the number a note gets wrong; it must be stated:\n" + out)
    assert "of which 1 had been CONFIRMED" in out, (
        "a superseded claim that was CONFIRMED is a settled verdict the build overrode, and the "
        "note must be able to say how many:\n" + out)


def test_lint_expect_refuses_when_a_named_batch_has_no_verdicts_file(tmp_path, capsys):
    """A missing file is the one failure a reader cannot spot by eye, because nothing is there.

    `grounding lint` lints the files that happen to exist. One live run printed
    `VERDICTS OK — 18 file(s) well-formed` while a nineteenth was seconds from landing; four
    verdict-consuming commands then ran against the incomplete set and were redone.
    """
    v = tmp_path / "verdicts-security-1.json"
    v.write_text(json.dumps({"grounding": [
        {"claim": "C1 calls C2", "grounded": True, "evidence": "a.py:1", "skeptic": "security-1"}]}),
        encoding="utf-8")

    assert main(["lint", "--verdicts", str(v), "--expect", "security-1"], env={}) == 0   # env={}: no session's transcripts
    assert main(["lint", "--verdicts", str(v), "--expect", "security-1,cadence"], env={}) == 1
    err = capsys.readouterr().err
    assert "VERDICTS INCOMPLETE" in err and "cadence" in err, err
    assert "grounding write" in err, "it must name what not to run yet"


def test_report_lists_the_claims_added_since_the_pin(tmp_path):
    """`write` printed how MANY were added after the pin and nothing could say WHICH.

    A build hand-diffed `audit --json` against the worklist in python to find them, then
    hand-edited the pinned worklist file itself to extend it — against the rule that the pin is
    not re-derived. Listing them is the read half of that job, and the half that needed no script.
    """
    pinned = ["C1 calls C2"]
    rows = [{"claim": "C1 calls C2", "grounded": True, "evidence": "a.py:1"}]
    out = G.format_report(pinned, rows, live_claims=["C1 calls C2", "C3 reads E1"])
    assert "ADDED SINCE THE PIN (1)" in out, out
    assert "C3 reads E1" in out.split("ADDED SINCE THE PIN")[1], out
    # Nothing added -> no section, so a clean run does not grow a heading that says zero.
    assert "ADDED SINCE THE PIN" not in G.format_report(pinned, rows, live_claims=pinned)


# --- the directory the harness actually hands the lead ----------------------------
# `--agent-transcripts` was suggested by the tool twice on one build and used ZERO times. Every
# `Agent` dispatch result names `<session>/tasks/<id>.output` — the same JSONL under a different
# suffix — and pointing the flag there failed outright with "holds no .jsonl". The directory that
# works, `<session>/subagents/`, is named nowhere the lead could see.

def _agent_dir(tmp: Path, name: str, filename: str, body: str) -> Path:
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(body, encoding="utf-8")
    return d


def _lint_with(agent_dir: Path, tmp: Path) -> tuple[int, str]:
    from coyomap.grounding import main
    import io, contextlib
    p = tmp / "v.json"
    p.write_text(json.dumps({"grounding": [
        {"claim": "c1", "grounded": True, "evidence": "a.py:1", "skeptic": "s",
         "note": "Read a.py and it holds"}]}), encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = main(["lint", "--verdicts", str(p), "--agent-transcripts", str(agent_dir)])
    return rc, buf.getvalue()


def test_a_dot_output_transcript_is_read_like_a_dot_jsonl():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        d = _agent_dir(tmp, "session/tasks", "abc123.output",
                       json.dumps({"message": {"content": [{"type": "tool_use", "name": "Read",
                                                       "input": {"file_path": "a.py"}}]}}) + "\n")
        rc, out = _lint_with(d, tmp)
        assert rc == 0, out
        assert "covered 1 of 1 row(s)" in out, out


def test_an_empty_transcript_dir_names_the_one_that_works():
    """"holds no .jsonl" told the lead neither which suffix nor which directory."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "session" / "subagents").mkdir(parents=True)
        (tmp / "session" / "subagents" / "agent-1.jsonl").write_text("a.py\n", encoding="utf-8")
        empty = tmp / "session" / "tasks"
        empty.mkdir(parents=True)
        rc, out = _lint_with(empty, tmp)
        assert rc != 0, out
        assert "subagents" in out, out


def test_the_empty_dir_message_does_not_invent_a_sibling_that_is_not_there():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        empty = tmp / "nowhere" / "tasks"
        empty.mkdir(parents=True)
        rc, out = _lint_with(empty, tmp)
        assert rc != 0, out
        assert "Did you mean" not in out, out


# --- the tasks/ directory mixes agent transcripts with background-Bash stdout ---------------
# On the 2026-08-29 mcpolis build the lead pointed `--agent-transcripts` at `<session>/tasks/`,
# the one path a dispatch result names. That directory held 80 agent transcripts (`a*.output`)
# AND 18 background-Bash stdout captures under the same suffix. One captured line was a bare
# number, `json.loads` returned an `int`, and `_opened_files` called `.get` on it: the whole pass
# aborted with `AttributeError`. The lead read that as "the tool cannot run on this harness",
# dropped the flag, and the map shipped a `grounding.note` saying so. Run correctly the check
# covers 1,085 of 1,085 rows and flags 40.

def test_a_bare_scalar_line_in_the_transcript_dir_does_not_abort_the_pass():
    """The crash. A background-Bash capture whose stdout is a number sits beside the agents."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        d = _agent_dir(tmp, "session/tasks", "a1.output",
                       json.dumps({"message": {"content": [{"type": "tool_use", "name": "Read",
                                                            "input": {"file_path": "a.py"}}]}}) + "\n")
        (d / "b0df5wg4g.output").write_text("42\n[1, 2]\n\"a string\"\nnull\n", encoding="utf-8")
        rc, out = _lint_with(d, tmp)
        assert rc == 0, out
        assert "AttributeError" not in out, out
        assert "covered 1 of 1 row(s)" in out, out


def test_background_bash_stdout_does_not_vouch_for_a_file_no_agent_opened():
    """The quieter half. A batch file printed by a background command names hundreds of anchors;
    letting it into the LOOSE set makes a fabricated row look merely 'weak' instead of flagged."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # The agent opened NOTHING. Only the background capture names `a.py`.
        d = _agent_dir(tmp, "session/tasks", "a1.output",
                       json.dumps({"message": {"content": [{"type": "tool_use", "name": "Bash",
                                                            "input": {"command": "echo hi"}}]}}) + "\n")
        # A real background capture, and it must be one whose lines DO parse — otherwise
        # `_mentioned_files` ignored them already and the test proves nothing about the new
        # discriminator. One bare scalar among the objects is what a real capture holds and what
        # makes this file not an agent transcript.
        (d / "b1.output").write_text(
            json.dumps({"claims": [{"anchor": "a.py:1"}]}) + "\n42\n", encoding="utf-8")
        rc, out = _lint_with(d, tmp)
        assert rc != 0, out
        assert "a.py" in out, out


# --- a note whose own record contradicts it ---------------------------------------------------
# `--note` is free prose in a permanent record and in the commit message, and nothing checked it.
# The 2026-08-29 mcpolis map shipped both shapes: "483 verdict rows over 161 redundant rows" (161
# is the CLAIM count; 322 rows were redundant) and "16 of those 696 carry no verdict" where its own
# record said 22 of 702. The redundant-row error had been found by the PREVIOUS retro, marked fixed,
# and recurred — because the fix printed the number without refusing a note that disagrees.

def _write_with_note(note: str, rows: list[dict], claims: list[str],
                     live: list[str] | None = None):
    from coyomap.grounding import _note_contradictions, build_record
    record, _errors = build_record(claims, rows, note, live_claims=live)
    return _note_contradictions(note, rows, record, live)


def _triple(claim: str) -> list[dict]:
    return [{"claim": claim, "grounded": True, "evidence": "a.py:1", "skeptic": s}
            for s in ("a", "b", "c")]


def test_a_wrong_redundant_row_count_is_reported():
    rows = _triple("c1") + _triple("c2")            # 6 rows, 2 claims -> 4 redundant
    problems = _write_with_note("6 verdict rows over 2 redundant rows.", rows, ["c1", "c2"])
    assert problems and "4" in problems[0], problems


def test_the_right_redundant_row_count_passes():
    rows = _triple("c1") + _triple("c2")
    assert not _write_with_note("6 verdict rows, 4 redundant rows.", rows, ["c1", "c2"])


def test_another_builds_figure_beside_this_pass_is_fine():
    """A good note cites earlier builds for comparison; flagging those flags the honest notes."""
    rows = _triple("c1") + _triple("c2")
    note = "4 redundant rows this build, against 100 redundant rows on the one before."
    assert not _write_with_note(note, rows, ["c1", "c2"])


def _write_note_cli(note: str, extra: list[str] | None = None,
                    anchors: tuple[str, str, str] = ("a.py:1", "a.py:1", "a.py:1"),
                    ) -> tuple[int, str, bool]:
    """Run `grounding write` end to end over one triple-voted claim. Returns
    `(exit code, everything printed, whether the record was written)`.

    `anchors` is one `evidence` per voter, so a test can make the three readers agree or disagree."""
    import contextlib, io
    from coyomap.grounding import main
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        v = tmp / "v.json"
        v.write_text(json.dumps({"grounding": [
            {"claim": "c1", "grounded": True, "evidence": ev, "skeptic": s}
            for s, ev in zip(("a", "b", "c"), anchors)]}), encoding="utf-8")
        w = tmp / "w.json"
        w.write_text(json.dumps({"worklist": [{"claim": "c1"}]}), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["write", "--worklist", str(w), "--verdicts", str(v),
                       "--note", note, "--out", str(tmp / "g.json")] + (extra or []))
        return rc, buf.getvalue(), (tmp / "g.json").exists()


def test_a_contradicting_note_REFUSES_and_prints_the_right_numbers():
    """It warned, and warning did not work. The redundant-row error was found by one retrospective,
    marked fixed by printing the right number, and shipped again on the next map; the anchor
    unanimity claim then shipped on a third. The note is permanent and rides the commit message, so
    a wrong number here outlives every other artifact of the run."""
    rc, out, wrote = _write_note_cli("the build before produced 100 redundant rows")
    assert rc == 1, out
    assert not wrote, "a record whose note contradicts it must not be written"
    assert "redundant" in out, out
    # The numbers to fix it with must come WITH the refusal, or the next attempt is a guess.
    assert "NOTE FACTS" in out and "2 row(s) that added no new claim" in out, out
    assert "--note-cites-other-runs" in out, "the refusal must name its own escape"


def test_note_cites_other_runs_turns_the_refusal_back_into_a_warning():
    """Prose has more shapes than a regex: a note citing only earlier builds' figures, or a
    theme-scoped count, is honest and states a number this pass does not have. The tool cannot read
    which pass a sentence is about and the operator can, so the escape is an assertion of intent —
    the same shape as `--partial`."""
    rc, out, wrote = _write_note_cli("the build before produced 100 redundant rows",
                                     ["--note-cites-other-runs"])
    assert rc == 0, out
    assert wrote, "an asserted-honest note must still be written"
    assert "WARNING" in out and "redundant" in out, out


def test_a_stale_shipped_map_coverage_pair_is_reported():
    rows = [{"claim": "c1", "grounded": True, "evidence": "a.py:1", "skeptic": "a"}]
    problems = _write_with_note("2 of those 9 carry no verdict.", rows, ["c1"],
                                live=["c1", "c2", "c3"])
    assert problems, problems
    assert "2 of 3" in problems[-1], problems


def test_the_right_coverage_pair_passes():
    rows = [{"claim": "c1", "grounded": True, "evidence": "a.py:1", "skeptic": "a"}]
    assert not _write_with_note("2 of those 3 carry no verdict.", rows, ["c1"],
                                live=["c1", "c2", "c3"])


def _voted(claim: str, votes: list[tuple[object, str]]) -> list[dict]:
    """One claim, one row per voter: `(grounded, evidence anchor)`."""
    return [{"claim": claim, "grounded": g, "evidence": ev, "skeptic": f"s{i}"}
            for i, (g, ev) in enumerate(votes)]


def test_multi_vote_agreement_counts_verdict_and_anchor_disagreements_apart():
    from coyomap.grounding import multi_vote_agreement
    rows = (_voted("agree", [(True, "a.py:1"), (True, "a.py:1"), (True, "a.py:1")])
            + _voted("split-verdict", [(True, "b.py:2"), (False, "b.py:2")])
            + _voted("split-anchor", [(True, "c.py:3"), (True, "c.py:9")])
            + _voted("single", [(True, "d.py:4")]))
    assert multi_vote_agreement(rows) == (3, 1, 1)


def test_a_missing_anchor_is_not_counted_as_agreement():
    """An absent citation is not a matching one — counting it as agreement is how a pass with two
    silent voters reads as unanimous."""
    from coyomap.grounding import multi_vote_agreement
    rows = _voted("c1", [(True, "a.py:1"), (True, "")])
    assert multi_vote_agreement(rows) == (1, 0, 0)


def _agreement(note: str, rows: list[dict]):
    from coyomap.grounding import _agreement_contradictions
    return _agreement_contradictions(note, rows)


def test_a_wrong_anchor_unanimity_claim_is_reported():
    """The 2026-09-01 argus map shipped a note saying the three security voters agreed on every
    anchor. Two of its triple-voted claims disagree, and nothing computed the number."""
    rows = _voted("c1", [(True, "a.py:1"), (True, "a.py:9"), (True, "a.py:1")])
    out = _agreement("the voters agreed on every anchor: zero anchor disagreements.", rows)
    assert out, out
    assert "1 evidence-anchor disagreement(s)" in out[-1], out


def test_the_sentence_that_actually_SHIPPED_is_caught_with_no_number_in_it():
    """A count regex could not see it. The defect shipped in words: an assurance, not arithmetic."""
    rows = _voted("c1", [(True, "a.py:1"), (True, "a.py:9"), (True, "a.py:1")])
    assert _agreement("The three security voters agreed on every anchor.", rows)


def test_the_agreement_claim_WARNS_and_never_refuses():
    """Blocking on a language judgement would refuse honest notes — a worse failure than the one
    being caught, since `NOTE FACTS` already prints the true triple beside the author. The two
    ARITHMETIC shapes stay blocking; this one does not."""
    rc, out, wrote = _write_note_cli("The three voters agreed on every anchor.",
                                     anchors=("a.py:1", "a.py:9", "a.py:1"))
    assert rc == 0, out
    assert wrote, "an agreement claim must not stop the record being written"
    assert "WARNING" in out and "disagreement" in out, out


def test_a_single_skeptics_RE_VOTE_is_not_a_multi_voted_claim():
    """Voters are read off the rows, so `len(rows) < 2 and len(voters) < 2` reduced to "fewer than
    two rows" — counting one reader disagreeing with itself as a disagreement between readers."""
    from coyomap.grounding import multi_vote_agreement
    rows = [{"claim": "c1", "grounded": True, "evidence": "a.py:1", "skeptic": "s1"},
            {"claim": "c1", "grounded": True, "evidence": "a.py:9", "skeptic": "s1"}]
    assert multi_vote_agreement(rows) == (0, 0, 0)
    assert not _agreement("zero anchor disagreements", rows)


def test_rows_with_no_skeptic_field_are_not_multi_voted():
    from coyomap.grounding import multi_vote_agreement
    rows = [{"claim": "c1", "grounded": True, "evidence": "a.py:1"},
            {"claim": "c1", "grounded": True, "evidence": "a.py:9"}]
    assert multi_vote_agreement(rows) == (0, 0, 0)


def test_the_right_agreement_numbers_pass():
    rows = _voted("c1", [(True, "a.py:1"), (True, "a.py:9"), (True, "a.py:1")])
    assert not _agreement("1 evidence-anchor disagreements, 0 verdict disagreements.", rows)


def test_the_colon_form_of_a_disagreement_count_is_read():
    rows = _voted("c1", [(True, "a.py:1"), (True, "a.py:9"), (True, "a.py:1")])
    assert _agreement("anchor disagreements: 0", rows)
    assert not _agreement("anchor disagreements: 1", rows)


def test_a_note_that_states_neither_number_is_not_second_guessed():
    rows = _triple("c1")
    assert not _write_with_note("The pass was complete and the security theme was three-voted.",
                                rows, ["c1"])


def test_the_unvoted_reason_splits_pinned_from_minted():
    """One sentence for three places (the gate block, `write`'s NOTE, `ship`'s coverage line), so a
    partial pass cannot call its unchallenged pinned claims "minted after the pin" in any of them."""
    both = G.unvoted_reason(965, 16)
    assert "949 were pinned and never challenged" in both and "16 were minted or reworded" in both
    assert G.unvoted_reason(16, 16).startswith("They were minted or reworded")
    assert G.unvoted_reason(5, 0) == "They were pinned and never challenged."
    # a delta larger than the unvoted count is a malformed record, not a negative number
    assert G.unvoted_reason(5, 9).startswith("They were minted or reworded")


# --- the note gate fired on its own prescribed wording (retro 2026-09-13 reminderrepo, T2) -------
# `NOTE FACTS` tells the author to quote "N row(s) that added no new claim (usually a re-vote)", and
# the post-pin check read the `no` in that sentence as "0 claims added since the pin". `ship` died
# at step 6 of 13 against a record that said 14, and the run after it passed on a pure reword that
# changed no number.

def test_the_post_pin_check_does_not_fire_on_the_wording_NOTE_FACTS_prescribes():
    rows = _triple("c1") + _triple("c2")                 # 6 rows, 2 claims -> 4 redundant
    # The sentence SPELLED OUT, so this fails on the behaviour and not on a missing constant.
    note = "This pass produced 6 verdict rows, 4 row(s) that added no new claim (usually a re-vote)."
    assert not _write_with_note(note, rows, ["c1", "c2"], live=["c1", "c2", "c3"])
    assert G.REDUNDANT_PHRASE.format(n=4) in note, "the block must still prescribe that sentence"


def test_the_post_pin_count_it_exists_to_catch_is_still_caught():
    """The 2026-09-02 mcpolis note said "9 post-pin claims" where its own record said 13."""
    rows = _triple("c1") + _triple("c2")
    problems = _write_with_note("9 post-pin claims were never challenged.", rows, ["c1", "c2"],
                                live=["c1", "c2", "c3"])
    assert problems and "1 claim(s) added since the pin" in problems[0], problems


def test_a_MISQUOTED_note_facts_line_is_now_read_as_the_redundant_count():
    """Recognising the phrase is not the same as exempting it: a note that retypes it with the
    wrong number used to be read by nothing at all."""
    rows = _triple("c1") + _triple("c2")
    problems = _write_with_note("128 row(s) that added no new claim (usually a re-vote).",
                                rows, ["c1", "c2"])
    assert problems and "this pass has 4" in problems[0], problems


# --- the note gate never checked the skeptic count (retro 2026-09-13 reminderrepo, T14) ----------
# The shipped note opened "Twenty-one fresh-context skeptics challenged the pinned worklist" and
# said "Distinct skeptic labels 38" three sentences later. 38 is right three ways; 21 was the
# wave-one dispatch, re-pasted. `NOTE FACTS` printed the 38 and nothing read it back.

def test_a_wrong_skeptic_count_is_caught_beside_the_right_one():
    rows = _triple("c1")                                  # skeptics a, b, c -> 3 labels
    problems = _write_with_note(
        "Twenty-one fresh-context skeptics challenged the pinned worklist. "
        "Distinct skeptic labels 3.", rows, ["c1"])
    assert problems, "an any-occurrence-clears rule passes the note this check exists for"
    assert "Twenty-one fresh-context skeptics" in problems[0], problems
    assert "3 distinct skeptic label(s)" in problems[0], problems


def test_the_right_skeptic_count_passes_in_digits_and_in_words():
    rows = _triple("c1")
    assert not _write_with_note("Distinct skeptic labels 3.", rows, ["c1"])
    assert not _write_with_note("Three fresh-context skeptics challenged it.", rows, ["c1"])


def test_a_subset_written_as_n_of_the_m_reads_as_m():
    """The escape the refusal names, so an honest note about part of the wave is not refused."""
    rows = _triple("c1")
    assert not _write_with_note("2 of the 3 skeptics dissented.", rows, ["c1"])


def test_no_skeptic_saw_them_is_a_quantifier_not_a_count():
    """The real note says "so no skeptic saw them" about the post-pin claims. That is not a claim
    that the pass had zero skeptics."""
    rows = _triple("c1")
    assert not _write_with_note("They were minted after the pin, so no skeptic saw them.",
                                rows, ["c1"])


# --- an adverse note reached nothing (retro 2026-09-13 reminderrepo, T8) -------------------------
# Two channels carry what an agent tells the LEAD and no verdict carries. A `grounded: true` row's
# note reaches no section of the report, because confirmed reads as "nothing to do". And a harvest,
# trace, gap-fill or test agent writes no verdict file at all, so its ONLY channel is the closing
# message — where the 2026-09-13 build's unguarded-route finding sat, naming three anchors that
# appear zero times in the shipped map.

def make_agent_transcript(dir_path: Path, stem: str, task: str, final: str) -> Path:
    """One agent transcript in the shape the harness writes, plus the `.meta.json` beside it."""
    dir_path.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"message": {"role": "user", "content": [{"type": "text", "text": task}]}}),
             json.dumps({"message": {"role": "assistant",
                                     "content": [{"type": "text", "text": final}]}})]
    path = dir_path / f"{stem}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (dir_path / f"{stem}.meta.json").write_text(json.dumps({"description": task}), encoding="utf-8")
    return path


ROUTE_FINDING = """## [1] Outcome

Done. Fragment written.

## Findings the lead should know

- **Three paths are declared twice, with different guard sets.** `reminder-groups-list` and
  `reminder-page-invitations-list` appear as a tab child and as a top-level route.
- **One top-level route carries no guard at all.** `app-routing.module.ts:17`.
"""


def test_the_report_collects_the_closing_section_an_agent_wrote_to_the_lead(tmp_path):
    agents = tmp_path / "subagents"
    make_agent_transcript(agents, "agent-aaa", "Harvest Angular pages and routes", ROUTE_FINDING)
    make_agent_transcript(agents, "agent-bbb", "Harvest deps", "## [1] Outcome\n\nDone.\n")
    text = G.format_report(["c1"], [{"claim": "c1", "grounded": True, "evidence": "a.py:1"}],
                           agent_dir=agents)
    assert "FINDINGS THE AGENTS SENT UP" in text, text
    assert "Harvest Angular pages and routes" in text, text
    assert "app-routing.module.ts:17" in text, text
    assert "Harvest deps" not in text, "an agent with no such section must not be listed:\n" + text
    # Its own coverage, in `grounding lint`'s shape — this is a heading match over prose.
    assert "2 agent transcript(s)" in text, text


def test_a_missing_transcript_directory_reads_as_NOT_READ_and_never_as_zero(tmp_path):
    rows = [{"claim": "c1", "grounded": True, "evidence": "a.py:1"}]
    unread = G.format_report(["c1"], rows)
    assert "AGENT FINDINGS NOT READ" in unread.splitlines()[0], unread.splitlines()[0]
    assert "AGENT FINDINGS NOT READ" in unread.split("\n\n")[-1], unread
    agents = tmp_path / "subagents"
    make_agent_transcript(agents, "agent-aaa", "Harvest deps", "## [1] Outcome\n\nDone.\n")
    read = G.format_report(["c1"], rows, agent_dir=agents)
    assert "0 finding(s) sent up by agents" in read, read
    assert "NOT READ" not in read, read


def test_an_upheld_row_whose_note_speaks_to_the_lead_is_listed():
    """`security-1-c` CONFIRMED a business rule and added that another route reaches the same
    screen unguarded. The claim stands, so the row landed in no section of this report."""
    rows = [{"claim": "c1", "grounded": True, "evidence": "a.py:1", "skeptic": "security-1-c",
             "note": "The rule holds at line 90. Note for the lead: app-routing.module.ts:15 "
                     "registers a second, unguarded way in."},
            {"claim": "c2", "grounded": True, "evidence": "b.py:2", "skeptic": "security-1-c",
             "note": "The rule holds."}]
    text = G.format_report(["c1", "c2"], rows)
    assert "NOTES TO THE LEAD ON UPHELD CLAIMS (1)" in text, text
    assert "app-routing.module.ts:15" in text, text
    # from the SENTENCE the phrase sits in, so the finding is not cut off mid-clause
    assert "Note for the lead: app-routing.module.ts:15" in text, text
    assert "Phrase match over 2 of 2 upheld row(s)" in text, text


def test_both_lead_channels_survive_a_head_and_a_tail(tmp_path):
    """The report runs hundreds of lines and is read through a pipe; two opposite narrowings have
    already hidden two ends of one section on a real build."""
    agents = tmp_path / "subagents"
    make_agent_transcript(agents, "agent-aaa", "Trace groups", ROUTE_FINDING)
    rows = [{"claim": "c1", "grounded": True, "evidence": "a.py:1", "skeptic": "s",
             "note": "Holds. Worth flagging: the second route has no guard."}]
    text = G.format_report(["c1"], rows, agent_dir=agents)
    head, tail = text.splitlines()[0], text.splitlines()[-3:]
    assert "1 upheld with a note to the lead" in head and "1 finding(s) sent up" in head, head
    assert any("TO THE LEAD:" in ln for ln in tail), tail


def test_the_report_verb_prints_the_numbers_the_note_must_quote(tmp_path):
    """`note_facts_block` was printed only by `grounding write` — the run that REFUSES the note — so
    the first note of every build was written from hand-computed figures. `ship` PREPARE ends on
    this report; the numbers belong here."""
    import contextlib, io
    wl = tmp_path / "wl.json"
    wl.write_text(json.dumps({"worklist": [{"claim": "c1"}]}), encoding="utf-8")
    vd = tmp_path / "v.json"
    vd.write_text(json.dumps({"grounding": _triple("c1")}), encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["report", "--worklist", str(wl), "--verdicts", str(vd)], env={})
    out = buf.getvalue()
    assert rc == 0, out
    assert "NOTE FACTS" in out, out
    assert "distinct skeptic labels 3" in out, out
    assert "2 row(s) that added no new claim" in out, out


# --- the closer's verdicts reach the readers (retro 2026-09-13 reminderrepo, T7 second half) -----
# `contract closer` now makes the closer WRITE its verdicts to `verify/closer-<agent>.json`, in the
# skeptics' own shape with `uphold → grounded false`, `reject → true`, `unsure → "unverifiable"`.
# The map kept nothing of what the closer decided: on the reviewed build two REJECTED refutations
# still blocked the ship gate and cost five turns to talk past.

def make_closer_row(claim: str, verdict: str, note: str = "read the line in full") -> dict:
    grounded: object = {"uphold": False, "reject": True, "unsure": "unverifiable"}[verdict]
    return {"claim": claim, "verdict": verdict, "grounded": grounded, "id": "rule-1#12",
            "evidence": "a.py:90", "skeptic": "closer-agent-1", "note": note}


def make_refuted_map(claim_text: str):
    """A map whose ONE component description is the claim the skeptics refuted."""
    from coyomap.model import load_model
    return load_model(json.dumps({
        "format": "coyomap-map", "title": "T", "goal": "g", "commit": "abc1234",
        "components": [{"id": "C1", "name": "Front", "purpose": claim_text}],
    }))


def refuted_claim_of(m) -> str:
    from coyomap.audit_model import l2_worklist_model
    return next(w.claim for w in l2_worklist_model(m) if "C1" in w.claim)


def test_a_closer_row_is_never_counted_as_a_vote():
    """An `uphold` would double a refutation's weight and a `reject` would add a confirming vote."""
    skeptics = [{"claim": "c1", "grounded": False, "evidence": "a.py:1", "skeptic": "sec-a"}]
    rec_alone, _ = build_record(["c1"], skeptics)
    rec_with, _ = build_record(["c1"], skeptics + [make_closer_row("c1", "reject")])
    tally = ("claims_total", "claims_challenged", "claims_confirmed", "claims_refuted",
             "claims_unverifiable")
    assert [count(rec_alone, k) for k in tally] == [count(rec_with, k) for k in tally], (
        "the closer is an appeal, not a third skeptic — a `reject` folded into the tally turns a "
        f"1-0 refutation into a 1-1 tie:\n{rec_alone}\n{rec_with}")
    assert count(rec_with, "claims_refuted") == 1 and count(rec_with, "claims_confirmed") == 0
    # ...and the appeal is RECORDED, so a fresh clone can see the refutation was overturned
    assert count(rec_with, "closer_rejected") == 1, rec_with
    assert count(rec_with, "closer_upheld") == 0 and count(rec_with, "closer_unsure") == 0
    assert count(rec_alone, "closer_rejected") == 0, "no appeal heard reads as zero, not absent"


def test_a_closer_is_not_a_skeptic_label_and_not_a_second_voter():
    skeptics = _triple("c1")
    rows = skeptics + [make_closer_row("c1", "uphold")]
    assert G.skeptic_labels(rows) == ["a", "b", "c"], G.skeptic_labels(rows)
    assert G.multi_vote_agreement(rows) == G.multi_vote_agreement(skeptics)
    # ...so the note gate this batch added does not start refusing a truthful note
    assert not _write_with_note("Three fresh-context skeptics challenged it.", rows, ["c1"])


def test_a_refutation_the_closer_REJECTED_stops_blocking_the_gate():
    m = make_refuted_map("takes the ask and answers it")
    claim = refuted_claim_of(m)
    skeptics = [{"claim": claim, "grounded": False, "evidence": "a.py:1", "skeptic": "desc-1"}]
    assert G.surviving_refutations(m, skeptics), "without the appeal it must still block"
    cleared = G.surviving_refutations(m, skeptics + [make_closer_row(claim, "reject")])
    assert cleared == [], cleared
    # ...and it is NAMED, never silently absent
    text = G.format_refutations(cleared, [], m=m,
                                grounding_rows=skeptics + [make_closer_row(claim, "reject")])
    assert "CLOSER REJECTED" in text, text
    assert "read the line in full" in text, text


def test_uphold_and_unsure_keep_blocking():
    """`unsure` is "nobody settled it". Reading that as cleared is the one way this hides a
    survivor."""
    m = make_refuted_map("takes the ask and answers it")
    claim = refuted_claim_of(m)
    skeptics = [{"claim": claim, "grounded": False, "evidence": "a.py:1", "skeptic": "desc-1"}]
    for word in ("uphold", "unsure"):
        still = G.surviving_refutations(m, skeptics + [make_closer_row(claim, word)])
        assert len(still) == 1, (word, still)
        assert still[0].closed == word, still[0]


def test_the_report_shows_what_the_closer_decided():
    rows = [{"claim": "c1", "grounded": False, "evidence": "a.py:1", "skeptic": "sec-a"},
            make_closer_row("c1", "reject", "line 90 masks the address; the skeptic read line 80")]
    text = G.format_report(["c1"], rows)
    assert "CLOSED ON APPEAL (1 appeal row(s))" in text and "reject 1" in text, text
    assert "the skeptic read line 80" in text, text
    assert "1 closed on appeal" in text.splitlines()[0], text.splitlines()[0]
    # the buckets themselves must not have moved
    assert "REFUTED — reconcile each into the map (1)" in text, text


def test_lint_says_when_appeals_are_in_the_pile(tmp_path, capsys):
    v = tmp_path / "verdicts-rule-1.json"
    v.write_text(json.dumps({"grounding": [
        {"claim": "c1", "grounded": False, "evidence": "a.py:1", "skeptic": "sec-a"}]}))
    c = tmp_path / "closer-agent-1.json"
    c.write_text(json.dumps({"grounding": [make_closer_row("c1", "reject")]}))
    rc = main(["lint", "--verdicts", str(v), str(c)], env={})
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert rc == 0, out
    assert "1 are CLOSER appeals" in out, out


def test_the_agent_transcripts_are_the_MAPS_repos_not_the_working_directorys(tmp_path, monkeypatch):
    """Run from a coyomap clone against another repo's map, the cwd default read the CLONE's own
    session — 26 transcripts of coyomap's development — and printed their findings in a report
    about a different product."""
    home = tmp_path / "home"
    mapped = tmp_path / "mapped-repo"
    elsewhere = tmp_path / "the-clone"
    (mapped / ".coyomap").mkdir(parents=True)
    elsewhere.mkdir()
    sid = "sid-1"
    from coyomap.provenance import project_slug
    theirs = home / ".claude" / "projects" / project_slug(mapped) / sid / "subagents"
    make_agent_transcript(theirs, "agent-right", "Trace groups", ROUTE_FINDING)
    wrong = home / ".claude" / "projects" / project_slug(elsewhere) / sid / "subagents"
    make_agent_transcript(wrong, "agent-wrong", "Fix the linter", ROUTE_FINDING)
    monkeypatch.chdir(elsewhere)            # the clone the command is typed in
    env = {"CLAUDE_CODE_SESSION_ID": sid}
    the_map = mapped / ".coyomap" / "project-map.json"
    worklist = mapped / ".coyomap" / "verify" / "worklist.json"
    verdicts = mapped / ".coyomap" / "verify" / "verdicts-rule-1.json"
    # EVERY input these verbs take names the repo, so none of them has to guess from the cwd.
    for named in (the_map, worklist, verdicts):
        assert G._repo_of(str(named)) == mapped, named
        assert G._resolve_agent_dir(None, env, G._repo_of(str(named)), home=home) == str(theirs)
    # ...and the cwd answer, which is what it used to give, is the OTHER product's agents
    assert G._repo_of(None) is None
    assert G._resolve_agent_dir(None, env, None, home=home) == str(wrong)


def test_the_appeal_survives_into_the_shipped_map(tmp_path):
    """The record is a dict `grounding write` emits; whether it reaches a READER of the map is the
    model's question. Without the three fields the closer's answers stop at the fragment, and a
    fresh clone still cannot see that a refutation was overturned — the half that made this HIGH."""
    from coyomap.model import load_model, to_canonical_json
    skeptics = [{"claim": "c1", "grounded": False, "evidence": "a.py:1", "skeptic": "sec-a"}]
    record, _ = build_record(["c1"], skeptics + [make_closer_row("c1", "reject")])
    doc = {"format": "coyomap-map", "title": "T", "goal": "g",
           "components": [{"id": "C1", "name": "C1", "purpose": "p"}],
           "grounding": record}
    m = load_model(json.dumps(doc))
    assert m.grounding is not None
    assert m.grounding.closer_rejected == 1, m.grounding
    assert m.grounding.claims_refuted == 1, "the five counts must not have moved"
    # ...and it is written back out, so the committed map carries it
    assert '"closer_rejected": 1' in to_canonical_json(m)


def test_a_closer_file_whose_rows_carry_no_verdict_word_is_REFUSED(tmp_path, capsys):
    """`is_closer_row` decides from one optional string, and nothing checked it. A closer file
    saying `"verdict": "rejected"` — the natural typo — was read as two extra skeptic VOTES:
    `claims_refuted 19 → 17, claims_unverifiable 0 → 2, closer_rejected 0`."""
    v = tmp_path / "verdicts-rule-1.json"
    v.write_text(json.dumps({"grounding": [
        {"claim": "c1", "grounded": False, "evidence": "a.py:1", "skeptic": "sec-a"}]}))
    c = tmp_path / "closer-agent-1.json"
    c.write_text(json.dumps({"grounding": [
        {"claim": "c1", "verdict": "rejected", "grounded": True, "evidence": "a.py:9",
         "skeptic": "closer-1", "note": "n"}]}))
    rc = main(["lint", "--verdicts", str(v), str(c)], env={})
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert rc == 1, out
    assert "unreadable closer verdict word" in out, out
    assert "'rejected'" in out, out
    assert "KEEPS BLOCKING" in out, "an unreadable word must never become a vote:\n" + out


def test_an_appeal_word_inside_a_SKEPTICS_file_is_refused_too(tmp_path, capsys):
    """The same hole in the other direction: the row silently leaves the vote tally."""
    v = tmp_path / "verdicts-rule-1.json"
    v.write_text(json.dumps({"grounding": [
        {"claim": "c1", "grounded": False, "evidence": "a.py:1", "skeptic": "sec-a"},
        {"claim": "c2", "verdict": "reject", "grounded": True, "evidence": "a.py:2",
         "skeptic": "sec-a"}]}))
    rc = main(["lint", "--verdicts", str(v)], env={})
    captured = capsys.readouterr()
    assert rc == 1
    assert "1 of 2 row(s) carry a `verdict` field" in captured.out + captured.err


def test_the_gate_reads_the_closer_WORD_not_its_grounded_translation():
    """A row saying `{"verdict": "unsure", "grounded": true}` cleared the gate while the record
    counted an `unsure` and the report said "'uphold' and 'unsure' still need you"."""
    m = make_refuted_map("takes the ask and answers it")
    claim = refuted_claim_of(m)
    skeptics = [{"claim": claim, "grounded": False, "evidence": "a.py:1", "skeptic": "desc-1"}]
    lying = dict(make_closer_row(claim, "unsure"), grounded=True)
    still = G.surviving_refutations(m, skeptics + [lying])
    assert len(still) == 1 and still[0].closed == "unsure", still
    assert G.settled_on_appeal(m, skeptics + [lying]) == []


def test_two_appeals_that_disagree_settle_nothing():
    """The first version let the alphabetically-last FILE win and called it "the later wave"; closer
    files are named by random agent id, so which appeal survived was chance."""
    m = make_refuted_map("takes the ask and answers it")
    claim = refuted_claim_of(m)
    skeptics = [{"claim": claim, "grounded": False, "evidence": "a.py:1", "skeptic": "desc-1"}]
    both = [make_closer_row(claim, "reject"), make_closer_row(claim, "uphold")]
    assert G.closer_ruling(both) == {claim: G.DISPUTED}
    still = G.surviving_refutations(m, skeptics + both)
    assert len(still) == 1 and still[0].closed == G.DISPUTED, still
    # the marker must not read as a word anyone could write back into a file
    assert G.DISPUTED not in G._CLOSER_VERDICTS and G.DISPUTED.startswith("(")


def test_element_checks_never_counts_an_appeal_as_a_vote():
    """The ninth reader, reached with appeals in the pile through `ship`'s by-element step and
    through `grounding refutations`, whose output `finalize` consumes."""
    m = make_refuted_map("takes the ask and answers it")
    claim = refuted_claim_of(m)
    skeptics = [{"claim": claim, "grounded": False, "evidence": "a.py:1", "skeptic": "desc-1"}]
    alone, _ = G.element_checks(m, [claim], skeptics)
    with_appeals, _ = G.element_checks(m, [claim], skeptics + [make_closer_row(claim, "reject"),
                                                               make_closer_row(claim, "reject")])
    assert [(c.element_id, c.refuted, c.confirmed, c.unverifiable) for c in alone] \
        == [(c.element_id, c.refuted, c.confirmed, c.unverifiable) for c in with_appeals], \
        (alone, with_appeals)
    assert alone[0].refuted == 1, alone


def test_the_headline_skeptic_count_is_the_FIRST_one_and_no_word_dodges_it():
    """Three rules were tried on the four live notes. Every-must-agree caught reminderrepo and
    REFUSED argus. Some-must-agree passes reminderrepo, which states the right 38 after the wrong
    21. First-unscoped was defeated by one word: adding `each` to the false headline skipped it as
    scoped and fell through to the 38."""
    rows = _triple("c1")                                  # 3 labels
    # argus's shape: the correct total first, true per-batch sentences after
    argus_shaped = ("Three fresh-context skeptics challenged all 454 pinned claims. "
                    "Both batches got three independent skeptics, and the rule theme two.")
    assert not _write_with_note(argus_shaped, rows, ["c1"])
    # the defect, and every word that used to dodge it
    for dodge in ("Twenty-one fresh-context skeptics challenged it.",
                  "Twenty-one fresh-context skeptics each challenged it.",
                  "Twenty-one fresh-context skeptics per agent challenged it.",
                  "Twenty-one fresh-context skeptics in two waves challenged it.",
                  "Twenty-one fresh-context skeptics across both batches challenged it.",
                  "One team of twenty-one fresh-context skeptics challenged it."):
        note = dodge + " Distinct skeptic labels 3."
        problems = _write_with_note(note, rows, ["c1"])
        assert problems and "3 distinct skeptic label(s)" in problems[0], (dodge, problems)


def test_a_count_inside_a_QUOTATION_is_somebody_elses_words():
    rows = _triple("c1")
    assert not _write_with_note('The brief said "dispatch twelve skeptics". '
                                "Three fresh-context skeptics challenged it.", rows, ["c1"])
    assert not _write_with_note("The brief said `dispatch twelve skeptics`. "
                                "Three fresh-context skeptics challenged it.", rows, ["c1"])


def test_a_markdown_heading_IS_the_headline_and_is_read():
    """A heading is where a reader looks first, so a wrong number there is the defect this catches."""
    rows = _triple("c1")
    problems = _write_with_note("## 21 skeptics\n\nDistinct skeptic labels 3.", rows, ["c1"])
    assert problems and "21 skeptics" in problems[0], problems
    assert not _write_with_note("## 3 skeptics\n\nAll of them challenged it.", rows, ["c1"])


def test_a_number_this_reader_cannot_COMPOSE_is_not_read_at_all():
    """"One hundred and five fresh-context skeptics" matched `five` and read as 5 — a wrong read,
    which can refuse a truthful note as easily as pass a false one. A miss is the safe failure."""
    rows = _triple("c1")
    for unreadable in ("One hundred and five fresh-context skeptics challenged it.",
                       "A dozen skeptics challenged it.",
                       "38+ skeptics challenged it.",
                       "Skeptics: 38 of them."):
        assert G._headline_skeptic_count(unreadable) is None, unreadable
        assert not _write_with_note(unreadable, rows, ["c1"]), unreadable


def test_a_note_that_opens_on_ANOTHER_runs_figure_is_refused_and_told_how():
    """A DECISION, not an oversight: no rule over prose separates "the previous build used twelve
    skeptics" from the reminderrepo note, since both put a wrong number first and the right one
    later. The refusal is the half with a one-line remedy, and the message carries it."""
    rows = _triple("c1")
    problems = _write_with_note("The previous build used twelve skeptics. "
                                "Three fresh-context skeptics challenged this one.", rows, ["c1"])
    assert problems, "the first count is read, whoever it is about"
    assert "Only the FIRST count in the note is read" in problems[0], problems
    assert "--note-cites-other-runs" in problems[0] or "another run" in problems[0].lower(), problems


def test_the_prescribed_wording_is_read_in_words_and_with_verdict_rows():
    """The skip keys on this match, so a form it misses re-opens the bug — and this codebase's own
    notes spell small numbers out."""
    rows = _triple("c1") + _triple("c2")                  # 4 redundant
    for spelling in ("Four row(s) that added no new claim (usually a re-vote).",
                     "4 verdict rows that added no new claim, the re-votes.",
                     "4 row(s) that added no new claim."):
        assert not _write_with_note(spelling, rows, ["c1", "c2"], live=["c1", "c2", "c3"]), spelling


def test_the_headline_rule_against_all_four_live_notes():
    """The openings of the four shipped maps, verbatim from their `grounding.note`. Two earlier
    rules were tuned on two of them and were blind or off-target on the other two: mcpolis's only
    count sentence says "across 19 batches", and coyomap's true opening says "in two waves"."""
    live = [
        ("argus", 18, "Eighteen fresh-context skeptics challenged all 454 pinned claims, "
                      "returning 614 verdict rows across 18 files; the pass was complete."),
        ("mcpolis", 38, "A partial pass, worked top-down by danger. WHAT WAS CHALLENGED. 842 of "
                        "the pinned 1,791 claims went to 38 fresh-context skeptics across 19 "
                        "batches: every access-control claim, every business-rule site."),
        ("coyomap", 25, "Twenty-five fresh-context skeptics challenged every claim in the pinned "
                        "worklist, in two waves, with the behavioural theme turned on. This pass "
                        "has 790 verdict rows over 728 distinct claims, and 25 distinct skeptic "
                        "labels."),
        ("reminderrepo", 21, "Twenty-one fresh-context skeptics challenged the pinned worklist "
                             "top-down by danger. Distinct skeptic labels 38."),
    ]
    for name, expected, opening in live:
        got = G._headline_skeptic_count(opening)
        assert got is not None, f"{name}: the check must READ this note, not skip it"
        assert got[0] == expected, (name, got)
    # ...and only reminderrepo's headline disagrees with its own label count
    assert G._headline_skeptic_count(live[3][2])[0] != 38


# --- a second wave for the claims written after the pin (retro 2026-09-30, finding 4) -----------
# `write` refused every verdict on a claim outside the pin, and validate's claim-loss advisory
# prescribed a re-pin that `write` then refused too. On the 2026-09-30 mcpolis build 68 claims
# shipped with no verdict, 6 of them re-worded sites of access rules: a hand-merged worklist would
# have been accepted, and nothing described it.

_WAVE_MAP = {"format": "coyomap-map", "title": "T", "goal": "g", "commit": "abc1234",
             "components": [{"id": "C3", "name": "Reader", "purpose": "reads the record"}],
             "entities": [{"id": "E1", "name": "Record", "meaning": "a saved row"}],
             "edges": [{"src": "C3", "verb": "reads", "dst": "E1", "why": "w", "where": "b.py:2"}]}


def make_second_wave(td: Path, orphan: bool = False) -> tuple[Path, Path, Path, list[str]]:
    """A map, a pin missing its edge claim, and verdicts on the pin plus that claim — the second
    wave. `orphan` adds a verdict on a claim neither the pin nor the map holds. Returns (worklist,
    verdicts, map, live claims)."""
    mp = td / "map.json"
    mp.write_text(json.dumps(_WAVE_MAP), encoding="utf-8")
    live = [w.claim for w in l2_worklist_model(load_model(mp.read_text(encoding="utf-8")))]
    assert "C3 reads E1" in live, live
    wl = td / "worklist.json"
    wl.write_text(json.dumps({"worklist": [{"claim": c, "theme": "backbone"}
                                           for c in live if c != "C3 reads E1"]}), encoding="utf-8")
    rows = [{"claim": c, "grounded": True, "evidence": "b.py:2", "skeptic": "s1"} for c in live]
    if orphan:
        rows.append({"claim": "C9 calls C10", "grounded": True, "evidence": "b.py:2", "skeptic": "s1"})
    vd = td / "verdicts-added-backbone-1.json"
    vd.write_text(json.dumps({"grounding": rows}), encoding="utf-8")
    return wl, vd, mp, live


def test_write_folds_a_second_wave_into_the_pin_and_keeps_the_first_pin() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        wl, vd, mp, live = make_second_wave(tmp)
        first_pin = wl.read_text(encoding="utf-8")
        argv = ["write", "--worklist", str(wl), "--verdicts", str(vd), "--map", str(mp),
                "--out", str(tmp / "g.json"), "--note", "second wave on the claim added after the pin"]
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = main(argv)
        assert code == 0, err.getvalue()
        record = json.loads((tmp / "g.json").read_text(encoding="utf-8"))["grounding"]
        assert record["claims_total"] == len(live) and record["claims_added_since"] == 0, record
        assert record["claims_live_challenged"] == len(live), record
        assert "C3 reads E1" in G._worklist_claims(wl), "the second wave was not pinned"
        assert (tmp / "worklist-wave1.json").read_text(encoding="utf-8") == first_pin
        assert "second wave: 1 claim(s)" in err.getvalue(), err.getvalue()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert main(argv) == 0, "a re-run must find the wave already pinned"
        assert G._worklist_claims(wl).count("C3 reads E1") == 1


def test_a_verdict_on_a_claim_neither_the_pin_nor_the_map_holds_is_still_refused() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        wl, vd, mp, _live = make_second_wave(tmp, orphan=True)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = main(["write", "--worklist", str(wl), "--verdicts", str(vd), "--map", str(mp),
                         "--out", str(tmp / "g.json"), "--note", "n"])
        assert code == 1, err.getvalue()
        assert "1 verdict claim(s) are not in the pinned worklist" in err.getvalue()
        assert not (tmp / "worklist-wave1.json").exists(), "a refused write re-pinned the worklist"


def test_the_report_buckets_a_second_wave_and_marks_it() -> None:
    with tempfile.TemporaryDirectory() as td:
        wl, vd, _mp, live = make_second_wave(Path(td))
        rows = [{**r, "grounded": False, "note": "no such read"} if r["claim"] == "C3 reads E1"
                else r for r in json.loads(vd.read_text(encoding="utf-8"))["grounding"]]
        out = G.format_report(G._worklist_claims(wl), rows, live_claims=live)
        refuted = json.loads(G.format_report(G._worklist_claims(wl), rows, as_json=True,
                                             live_claims=live))["refuted"]
    assert "[second wave] C3 reads E1" in out, out
    assert [r["claim"] for r in refuted] == ["C3 reads E1"], "a second-wave refutation must be " \
                                                            "reconciled like the first wave's"


# --- a test cited by its name alone (retro 2026-09-30, finding 28) ---------------------------------
# The tests agent listed names with `grep -n 'def test_'` and wrote each `why` from the name: 83 of
# its 184 citations point at a test whose body no tool call printed.

_TEST_BODY = ("def test_a_member_is_refused():\n"
              "    response = client.post('/api/orgs/1/members', json={'role': 'owner'})\n"
              "    assert response.status_code == 403, response.json()\n"
              "    assert store.members_of_org(1) == [], 'the refused member was saved anyway'\n")


def make_tests_repo(td: Path, printed_body: bool) -> tuple[Path, Path]:
    """A repo whose tests fragment cites one test, and an agent transcript that printed either the
    test's body or only its name. Returns (fragment, transcripts dir)."""
    repo = td / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_members.py").write_text(_TEST_BODY, encoding="utf-8")
    frag = repo / ".coyomap" / "build-fragments" / "x-tests.json"
    frag.parent.mkdir(parents=True)
    frag.write_text(json.dumps({"tests_note": "read, not run", "tests": [
        {"targets": ["UC1"], "label": "refused member", "tested": "yes", "confidence": "inferred",
         "tests": [{"file": "tests/test_members.py:1", "why": "a member is refused"}]}]}),
        encoding="utf-8")
    shown = _TEST_BODY if printed_body else "tests/test_members.py:1:def test_a_member_is_refused():"
    agents = td / "agents"
    agents.mkdir()
    (agents / "agent-t1.jsonl").write_text(json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "content": shown}]}}) + "\n", encoding="utf-8")
    return frag, agents


def test_a_test_cited_by_its_name_alone_fails_the_lint():
    with tempfile.TemporaryDirectory() as td:
        frag, agents = make_tests_repo(Path(td), printed_body=False)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["lint", "--tests", str(frag), "--agent-transcripts", str(agents)], env={})
    assert code == 1, err.getvalue()
    assert "1 of 1 test citation(s) rest on the name alone" in err.getvalue()
    assert "tests/test_members.py:1" in err.getvalue()


def test_a_test_whose_body_was_printed_passes_the_lint():
    with tempfile.TemporaryDirectory() as td:
        frag, agents = make_tests_repo(Path(td), printed_body=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(["lint", "--tests", str(frag), "--agent-transcripts", str(agents)], env={})
    assert code == 0 and "TESTS OK — 1 of 1" in out.getvalue(), out.getvalue()
