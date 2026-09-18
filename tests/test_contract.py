"""Tests for `coyomap contract <name>` — the verb that hands an agent its half of a contract.

The bug this verb exists to remove was silent: a build filled the skeptic template with one text
replacement and sent the whole file, so ten skeptics received the LEAD's instructions as their own
and four were told to read a claims file that does not exist. Nothing in the map or the gates could
see it. So the tests below pin the boundary itself, in both template shapes, and pin that no
lead-facing sentence survives into what an agent receives.
"""
from __future__ import annotations

import io
import contextlib
import json
import os
import re
from pathlib import Path

import pytest

from coyomap import contract

REPO_ROOT = Path(__file__).resolve().parent.parent

# Sentences that exist ONLY to instruct the lead. Any one of them in a rendered contract means the
# header crossed the boundary — the exact failure a real build paid for.
_LEAD_ONLY = ("Copy this file", "do not retype it from prose", "instructions to you, the",
              "Everything below the line is what the agent reads")


def make_quoted_template() -> str:
    return ("# Title\n\nLead instructions here.\n\n> You are an agent.\n>\n> Do the thing.\n")


def make_plain_template() -> str:
    return ("# Title\n\nLead instructions here.\n\n---\n\nYou are an agent.\n\nDo the thing.\n")


def render(name: str) -> str:
    return contract.render(name, REPO_ROOT)


# --- the boundary, both shapes -----------------------------------------------------------------

def test_a_quoted_template_yields_its_block_with_the_marker_stripped() -> None:
    assert contract.agent_half(make_quoted_template()) == "You are an agent.\n\nDo the thing."


def test_a_plain_template_yields_everything_after_its_divider() -> None:
    assert contract.agent_half(make_plain_template()) == "You are an agent.\n\nDo the thing."


def test_a_template_with_no_boundary_raises_rather_than_handing_over_the_header() -> None:
    """Silently returning the whole file is the failure this verb exists to remove, so the
    no-boundary case must be loud."""
    try:
        contract.agent_half("# Title\n\nLead instructions only.\n")
    except ValueError as exc:
        assert "no agent boundary" in str(exc)
        return
    raise AssertionError("a template with no boundary must raise")


def test_two_dividers_are_ambiguous_and_refused() -> None:
    try:
        contract.agent_half("# T\n\n---\n\nmiddle\n\n---\n\nagent\n")
    except ValueError as exc:
        assert "ambiguous" in str(exc)
        return
    raise AssertionError("two dividers must raise rather than guess which one is the boundary")


# --- the real templates ------------------------------------------------------------------------

def test_every_real_contract_renders_and_starts_with_the_agents_own_words() -> None:
    for name in contract.CONTRACTS:
        text = render(name)
        assert text.strip(), f"{name} rendered empty"
        assert text.lstrip().startswith("You are"), (
            f"{name} does not open by addressing the agent — the boundary is in the wrong place")


def test_no_lead_facing_sentence_survives_into_any_rendered_contract() -> None:
    for name in contract.CONTRACTS:
        text = render(name)
        leaked = [phrase for phrase in _LEAD_ONLY if phrase in text]
        assert not leaked, f"{name} leaks lead-only text {leaked} into the agent's prompt"


def test_no_quote_marker_survives_into_a_rendered_contract() -> None:
    """A `> ` left on every line is how an agent learns it was handed a document rather than a
    brief; it also breaks the fenced JSON examples the contracts carry."""
    for name in contract.CONTRACTS:
        stray = [line for line in render(name).splitlines() if line.startswith(">")]
        assert not stray, f"{name} still carries {len(stray)} quoted line(s)"


# --- the writing rules ride along, but only where they can be acted on --------------------------

def test_the_authoring_contracts_carry_the_writing_rules() -> None:
    for name in sorted(contract.AUTHORING):
        assert "One idea per sentence" in render(name), (
            f"{name} agents author reader-facing prose and received no writing rule")


def test_the_other_contracts_do_not_pay_for_rules_they_cannot_act_on() -> None:
    for name in set(contract.CONTRACTS) - contract.AUTHORING:
        assert "One idea per sentence" not in render(name), (
            f"{name} agents author no reader-facing prose; the rules are prompt weight there")


# --- the command line ----------------------------------------------------------------------------

def test_an_unknown_contract_name_is_refused_with_the_valid_set() -> None:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert contract.main(["nonsense"]) == 2
    assert "unknown contract" in err.getvalue()


def test_no_argument_prints_usage_and_fails_so_a_typo_is_never_silent() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert contract.main([]) == 2
    assert "usage: coyomap contract" in out.getvalue()


def test_the_verb_prints_the_contract_to_stdout() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert contract.main(["skeptic"]) == 0
    assert out.getvalue().lstrip().startswith("You are a fresh-context skeptic")


# --- `--slots` / `--fill` / `--brief`: the filled contract and the pointer that names it ---------
#
# A slot left unfilled reaches an agent as the literal `«REPO»`, and no gate sees it: the fragment
# that comes back is well-formed and simply about the wrong thing. A hand-composed brief grows —
# one build typed 159,993 bytes of brief across six fan-outs. Both jobs move into the verb here.

#: Slots whose CONTENT is checked, not only its presence — `_slot_content_faults`. A uniform
#: placeholder cannot satisfy those, so the builder gives each one a value of the right shape.
_CONTENTFUL_SLOTS = {"SERVES": "UC7 rename a page, R1 the owner"}


def make_slot_values(name: str, value: str = "filled") -> dict[str, str]:
    """Every slot of one contract, each filled with the same placeholder."""
    out = {k: value for k in contract.slots(name)}
    for key, real in _CONTENTFUL_SLOTS.items():
        if key in out:
            out[key] = real
    return out


def test_the_skeleton_lists_only_slots_the_agent_actually_receives() -> None:
    """The lead's half above the divider talks ABOUT «angle-bracket» slots. A skeleton listing
    those would ask the lead to fill words that reach nobody."""
    keys = contract.slots("rules")
    assert "angle-bracket" not in keys
    assert set(keys) == {"REPO", "PROJECT", "COYOMAP_HOME", "MAP", "BLOCK", "AGENT_ID"}


def test_the_skeleton_is_json_with_every_slot_empty() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert contract.main(["rules", "--slots"]) == 0
    printed = json.loads(out.getvalue())
    assert {k: v for k, v in printed.items() if not k.startswith("//")} == \
        {k: "" for k in contract.slots("rules")}


def test_a_clean_fill_leaves_no_slot_behind() -> None:
    text = contract.fill("rules", make_slot_values("rules"))
    assert "«" not in text and "»" not in text


def test_every_shipped_contract_can_be_filled_from_its_own_skeleton() -> None:
    """The skeleton and the filler must agree for all six, or a phase ships a verb that refuses
    the very keys it just printed."""
    for name in contract.CONTRACTS:
        assert "«" not in contract.fill(name, make_slot_values(name))


def test_a_missing_slot_is_refused_and_named() -> None:
    with pytest.raises(ValueError, match="no value given for"):
        contract.fill("rules", {"REPO": "/repo"})


def test_a_blank_value_is_refused_because_no_gate_can_see_one() -> None:
    values = make_slot_values("rules")
    values["REPO"] = "   "
    with pytest.raises(ValueError, match="blank"):
        contract.fill("rules", values)


def test_a_value_that_is_still_a_slot_name_is_refused() -> None:
    values = make_slot_values("rules")
    values["MAP"] = "«MAP»"
    with pytest.raises(ValueError, match="guillemets"):
        contract.fill("rules", values)


def test_a_key_that_is_no_slot_of_this_contract_is_refused_with_the_real_list() -> None:
    values = make_slot_values("rules")
    values["NOPE"] = "x"
    with pytest.raises(ValueError, match="no such slot"):
        contract.fill("rules", values)


def test_every_fault_is_reported_in_one_run() -> None:
    """Learning three missing slots must cost one run, not three — the brief→re-read loop this
    verb exists to end."""
    with pytest.raises(ValueError) as exc:
        contract.fill("rules", {"REPO": "  ", "NOPE": "x"})
    message = str(exc.value)
    assert "no such slot" in message and "no value given for" in message and "blank" in message


def test_the_brief_is_the_id_the_path_and_one_fixed_sentence() -> None:
    text = contract.brief("h1", Path("/abs/scratch/h1.md"))
    assert text.splitlines() == ["h1", "/abs/scratch/h1.md", contract.BRIEF_SENTENCE]
    assert len(text.encode("utf-8")) <= contract.BRIEF_MAX_BYTES


def test_a_relative_brief_path_is_refused_rather_than_resolved() -> None:
    """Resolving it would build a plausible absolute path out of the lead's cwd — the
    wrong-directory mistake, made silently, inside an agent's prompt."""
    with pytest.raises(ValueError, match="not absolute"):
        contract.brief("h1", Path("h1.md"))


def test_an_agent_id_with_a_space_is_refused() -> None:
    with pytest.raises(ValueError, match="one word"):
        contract.brief("h 1", Path("/abs/h1.md"))


def test_a_brief_over_the_pointer_cap_is_refused() -> None:
    with pytest.raises(ValueError, match="pointer cap"):
        contract.brief("h1", Path("/" + "d" * contract.BRIEF_MAX_BYTES + "/h1.md"))


def test_fill_writes_the_file_and_brief_prints_the_pointer(tmp_path: Path) -> None:
    slots = tmp_path / "slots.json"
    slots.write_text(json.dumps(make_slot_values("rules")), encoding="utf-8")
    out = tmp_path / "r3.md"
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
        assert contract.main(["rules", "--fill", str(slots), "--out", str(out),
                              "--brief", "r3"]) == 0
    assert "«" not in out.read_text(encoding="utf-8")
    assert stdout.getvalue().splitlines() == ["r3", str(out), contract.BRIEF_SENTENCE]


def test_a_refused_fill_writes_no_file(tmp_path: Path) -> None:
    slots = tmp_path / "slots.json"
    slots.write_text(json.dumps({"REPO": "/repo"}), encoding="utf-8")
    out = tmp_path / "r3.md"
    with contextlib.redirect_stderr(io.StringIO()):
        assert contract.main(["rules", "--fill", str(slots), "--out", str(out)]) == 2
    assert not out.exists()


def test_a_refused_brief_leaves_no_contract_nothing_points_at(tmp_path: Path) -> None:
    """The brief is composed before the write on purpose: a filled contract with no sendable
    pointer is a file the fan-out will never open."""
    slots = tmp_path / "slots.json"
    slots.write_text(json.dumps(make_slot_values("rules")), encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()):
        assert contract.main(["rules", "--fill", str(slots), "--out", "relative.md",
                              "--brief", "r3"]) == 2
    assert not Path("relative.md").exists()


def test_fill_refuses_to_print_the_contract_to_stdout(tmp_path: Path) -> None:
    """A filled contract on stdout is one pipe away from being pasted, which is the 13 KB brief
    the pointer exists to replace."""
    slots = tmp_path / "slots.json"
    slots.write_text(json.dumps(make_slot_values("rules")), encoding="utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert contract.main(["rules", "--fill", str(slots)]) == 2
    assert "needs --out" in err.getvalue()


def test_slots_does_not_combine_with_fill(tmp_path: Path) -> None:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert contract.main(["rules", "--slots", "--fill", "x.json", "--out", "y.md"]) == 2
    assert "does not combine" in err.getvalue()


def test_an_unreadable_slots_file_is_refused_by_name(tmp_path: Path) -> None:
    bad = tmp_path / "slots.json"
    bad.write_text("{not json", encoding="utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert contract.main(["rules", "--fill", str(bad), "--out", str(tmp_path / "o.md")]) == 2
    assert "not readable JSON" in err.getvalue()


# --- a filled contract is an agent's whole brief ----------------------------------------------
# Under pointer dispatch the agent reads its brief from the file whenever it gets round to it, so
# overwriting one rewrites the instructions of something that may still be running. On the
# 2026-08-29 mcpolis build turn 125 hand-wrote `briefs/t1.md` for an agent launched at turn 127, and
# turn 160's generator looped `--out …/briefs/{aid}.md` with `aid="t1"` and rewrote it mid-flight —
# exit 0, no warning. The lead saw only the downstream fragment-name collision, 19 turns later.

def _fill_to(tmp: Path, out: Path, extra: list[str] | None = None) -> tuple[int, str]:
    import contextlib, io, json as _json
    from coyomap.contract import main, slots
    values = {k: "x" for k in slots("skeptic")}
    src = tmp / "slots.json"
    src.write_text(_json.dumps(values), encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = main(["skeptic", "--fill", str(src), "--out", str(out), *(extra or [])])
    return rc, buf.getvalue()


def test_filling_over_an_existing_brief_is_refused():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        out = tmp / "brief.md"
        out.write_text("AN AGENT IS READING THIS", encoding="utf-8")
        rc, msg = _fill_to(tmp, out)
        body = out.read_text(encoding="utf-8")
    assert rc == 2, msg
    assert "already exists" in msg, msg
    assert body == "AN AGENT IS READING THIS", body


def test_force_overwrites_when_the_lead_knows_nothing_is_reading_it():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        out = tmp / "brief.md"
        out.write_text("stale", encoding="utf-8")
        rc, msg = _fill_to(tmp, out, ["--force"])
        body = out.read_text(encoding="utf-8")
    assert rc == 0, msg
    assert body != "stale", body


def test_a_fresh_path_still_writes():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        out = tmp / "nested" / "brief.md"
        rc, msg = _fill_to(tmp, out)
    assert rc == 0, msg


# --- a slot key must be typable (retro 2026-09-01, argus row 8) -----------------------------------
# `contract harvest --slots` returned keys like
# `«absolute paths this agent owns; list a directory first, then read each file»`. Nobody types
# that, so all four brief generators filled the skeleton BY POSITION — across 51 of 55 briefs — and
# a positional fill is silent when it is wrong. `trace` already used bare tokens.

def test_no_shipped_contract_has_a_prose_slot_key():
    from coyomap.contract import CONTRACTS, slots
    for name in CONTRACTS:
        slots(name)          # raises ValueError naming the offending keys


def test_a_prose_slot_key_is_refused_with_the_key_it_objects_to(tmp_path):
    import re
    from coyomap import contract
    home = tmp_path / "home"
    (home / "method" / "templates").mkdir(parents=True)
    (home / "method" / "templates" / "toy-contract.md").write_text(
        "lead half\n\n> agent half with «FINE» and «a whole sentence nobody types».\n",
        encoding="utf-8")
    contract.CONTRACTS["toy"] = "toy-contract.md"
    try:
        with pytest.raises(ValueError, match=re.escape("a whole sentence nobody types")):
            contract.slots("toy", root=home)
    finally:
        del contract.CONTRACTS["toy"]


def test_the_doors_contract_ships_and_names_its_own_slots():
    """The doors rule is ~9 KB of method.md and was hand-paraphrased into every brief; the argus
    build's was 9,031 bytes with no gate on the paraphrase."""
    from coyomap.contract import render, slots
    assert set(slots("doors")) == {"FLOWS", "MAP", "REPO", "SURFACES", "AGENT_ID", "COYOMAP_HOME"}
    text = render("doors")
    # The rule the hand-written brief dropped.
    assert "kind: service" in text and "audience: internal" in text
    # The two halves a paraphrase most often loses.
    assert "EVERY EXCHANGE IN BETWEEN" in text
    assert "add NO door" in text


# --- the cd rule must travel in the BRIEF (retro 2026-09-02, mcpolis N4) --------------------------
# The rule lived only in `method.md`, which no sub-agent reads. On the 2026-09-02 build 8 of 75
# agents stepped into the coyomap clone, 33 times, and one build before that the same slip edited
# the clone's committed map. A rule an agent never sees is not a rule.

def test_every_dispatched_contract_carries_the_cd_rule():
    from coyomap.contract import CONTRACTS, render
    # `harvest-t5` is an ADDENDUM appended to one harvest brief, which carries the rule itself.
    for name in CONTRACTS:
        if name == "harvest-t5":
            continue
        assert "NEVER `cd` into the coyomap clone" in render(name), name


def test_the_cd_rule_says_it_persists_BEYOND_this_command():
    """"across `;` and `&&`" was the whole sentence, and the expensive half is the rest of the
    session — a later command that mentions no clone at all still reads the wrong map."""
    from coyomap.contract import render
    text = render("trace")
    assert "rest of your session" in text, text[:400]


# --- what a slot is filled WITH (retro 2026-09-02, mcpolis findings 5 and 6) ----------------------
# A filled slot is a filled slot, so no other check could see either of these.

def _harvest_values(**over) -> dict[str, str]:
    from coyomap.contract import slots
    base = {k: "x" for k in slots("harvest")}
    base.update({"SERVES": "UC7 rename a page, R1 the owner", "SLICE_KIND": "structural",
                 "EXPECTED_COMPONENTS": "6"})
    base.update(over)
    return base


def test_a_SERVES_naming_no_behavioural_id_is_refused():
    """All 14 harvest briefs on one build filled it with a map-section name. Assertion 31 went
    1.00 -> 0.00 and the harvest returned components with no backbone edge at all."""
    from coyomap.contract import fill
    with pytest.raises(ValueError, match="names no behavioural id"):
        fill("harvest", _harvest_values(SERVES="T5 domain model"))


def test_a_SERVES_naming_any_behavioural_id_passes():
    from coyomap.contract import fill
    for value in ("UC7 rename a page", "R1 the owner", "CAP2 billing", "HP3 the third step"):
        fill("harvest", _harvest_values(SERVES=value))


def test_a_component_budget_is_NOT_judged_by_the_slice_kind_text():
    """This check was written and REVERTED. `«SLICE_KIND»` is free text — a real value is a
    sentence — so matching it against words like `config` or `entit` refused legitimate structural
    slices, and the remedy it demanded (write `0`) put "Expect roughly 0 components" in front of a
    slice that really had seven. Catching the real fault needs an enum of slice kinds, which the
    contract does not have."""
    from coyomap.contract import fill
    for kind in ("config loading and startup", "HTTP routing and config parsing",
                 "deployment scripts and the CI workflow", "the entity store adapters",
                 "T5 entities"):
        fill("harvest", _harvest_values(SLICE_KIND=kind, EXPECTED_COMPONENTS="7"))


def test_a_path_in_a_batch_id_slot_is_refused() -> None:
    """The contract composes `claims-«CLAIMS».json` and `verdicts-«BATCH».json` itself; a path in
    either slot names a file that exists nowhere, in every brief — 38 of 38 on one build."""
    values = make_slot_values("skeptic")
    values["CLAIMS"] = ".coyomap/verify/claims-backbone-1.json"
    with pytest.raises(ValueError, match="looks like a path"):
        contract.fill("skeptic", values)
    values["CLAIMS"], values["BATCH"] = "backbone-1", "backbone-1a"
    assert "«" not in contract.fill("skeptic", values)


def test_the_closer_contracts_claims_block_may_carry_paths() -> None:
    """The closer's «CLAIMS» is a pasted block of claims and `dump` output, `path:line` and all; the
    skeptic-only path check must not refuse it — its first version did, on the real build's slots."""
    values = make_slot_values("closer")
    values["CLAIMS"] = "- C1 reads E1 [backend/src/app.py:12]\n  dump: {\"where\": \"backend/src/app.py:12\"}"
    assert "«" not in contract.fill("closer", values)


# --- N skeptic briefs from an `audit --batches` directory (retro 2026-09-08, row 19) -------------

def _batches_dir(tmp: Path) -> Path:
    import json as _json
    d = tmp / "verify"
    d.mkdir()
    for bid, theme in (("security", "security"), ("backbone", "backbone"), ("small", "mixed")):
        (d / f"claims-{bid}.json").write_text(_json.dumps({"theme": theme, "claims": []}),
                                               encoding="utf-8")
    return d


def _skeptic_slots_file(tmp: Path, **over: str) -> Path:
    import json as _json
    from coyomap.contract import slots
    values = {k: "x" for k in slots("skeptic") if k not in ("BATCH", "CLAIMS")}
    values.update(over)
    src = tmp / "slots.json"
    src.write_text(_json.dumps(values), encoding="utf-8")
    return src


def _from_batches(tmp: Path, extra: list[str] | None = None) -> tuple[int, str]:
    import contextlib, io
    from coyomap.contract import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = main(["skeptic", "--from-batches", str(tmp / "verify"), "--fill",
                   str(tmp / "slots.json"), "--out-dir", str(tmp / "briefs"), *(extra or [])])
    return rc, buf.getvalue()


def test_from_batches_writes_one_brief_per_claims_file_and_votes_by_theme(tmp_path: Path) -> None:
    """Every build hand-wrote this loop, with `--force` on all 38 briefs. One brief per
    `claims-*.json`, BATCH and CLAIMS filled from the file name; `--votes security=3` writes
    three voters over the one security claims file."""
    _batches_dir(tmp_path)
    _skeptic_slots_file(tmp_path)
    rc, out = _from_batches(tmp_path, ["--votes", "security=3"])
    assert rc == 0, out
    names = sorted(p.name for p in (tmp_path / "briefs").glob("skeptic-*.md"))
    assert names == ["skeptic-backbone.md", "skeptic-security-a.md", "skeptic-security-b.md",
                     "skeptic-security-c.md", "skeptic-small.md"], names
    voter = (tmp_path / "briefs" / "skeptic-security-b.md").read_text(encoding="utf-8")
    assert "claims-security.json" in voter and "security-b" in voter and "«" not in voter
    assert "5 brief(s) written, 0 skipped" in out and out.count("Read it COMPLETELY") == 5, out


def test_from_batches_never_rewrites_an_existing_brief(tmp_path: Path) -> None:
    _batches_dir(tmp_path)
    _skeptic_slots_file(tmp_path)
    (tmp_path / "briefs").mkdir()
    (tmp_path / "briefs" / "skeptic-backbone.md").write_text("AN AGENT IS READING THIS",
                                                              encoding="utf-8")
    rc, out = _from_batches(tmp_path)
    assert rc == 0, out
    assert (tmp_path / "briefs" / "skeptic-backbone.md").read_text(encoding="utf-8") == \
        "AN AGENT IS READING THIS"
    assert "2 brief(s) written, 1 skipped" in out, out


def test_from_batches_refuses_a_slots_file_that_names_batch_or_claims(tmp_path: Path) -> None:
    _batches_dir(tmp_path)
    _skeptic_slots_file(tmp_path, BATCH="b1")
    rc, out = _from_batches(tmp_path)
    assert rc == 2 and "fills «BATCH» and «CLAIMS» itself" in out, out
    assert not (tmp_path / "briefs").exists() or not list((tmp_path / "briefs").glob("*"))


def test_a_harvest_fill_records_its_component_budget(tmp_path: Path) -> None:
    """`lint-fragment --expect` holds one slice to its budget; nothing summed them (60 budgeted,
    114 shipped). The fill records each brief's budget where `finalize` adds them up."""
    import contextlib, io, json as _json
    from coyomap.contract import main
    repo = tmp_path / "repo"
    repo.mkdir()
    values = _harvest_values(REPO_ABS=str(repo), **{"agent-id": "t1"}, EXPECTED_COMPONENTS="~6")
    src = tmp_path / "slots.json"
    src.write_text(_json.dumps(values), encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = main(["harvest", "--fill", str(src), "--out", str(tmp_path / "t1.md")])
    assert rc == 0, buf.getvalue()
    doc = _json.loads((repo / ".coyomap" / "verify" / "budgets.json").read_text(encoding="utf-8"))
    assert doc["harvest"] == {"t1": 6}, doc      # `session` is present only inside a build session


# --- review round 3: what a budget slot really says, and one build per budgets file --------------

def test_budget_of_reads_the_first_number_only() -> None:
    """Real briefs wrote `**4–6**`, `~10 (8–12)` and `five`; a digit-scrape made 46 and 10812 of
    the first two. The first number is the budget; a range records its low end; a word, None."""
    from coyomap.contract import budget_of
    assert [budget_of(v) for v in ("~8", "**4–6**", "~10 (8–12)", "5 to 7", "five", "")] == \
        [8, 4, 10, 5, None, None]


def test_a_budgets_file_belongs_to_one_build(tmp_path: Path) -> None:
    """A rebuild names its agents afresh; merging across builds would sum two harvests against
    one map. Another session's file is started over; a word-valued slot is kept as None."""
    import json as _json
    from coyomap.contract import record_budget
    record_budget(tmp_path, "h1", "6", session="s1")
    record_budget(tmp_path, "h2", "five", session="s1")
    doc = _json.loads((tmp_path / ".coyomap" / "verify" / "budgets.json").read_text(encoding="utf-8"))
    assert doc == {"harvest": {"h1": 6, "h2": None}, "session": "s1"}, doc
    record_budget(tmp_path, "h-entry", "4-6", session="s2")
    doc = _json.loads((tmp_path / ".coyomap" / "verify" / "budgets.json").read_text(encoding="utf-8"))
    assert doc == {"harvest": {"h-entry": 4}, "session": "s2"}, doc


def test_from_batches_refuses_a_missing_or_empty_batch_directory(tmp_path: Path) -> None:
    """Exit 0 with '0 brief(s) written' on a directory that does not exist is the accepting-and-
    misreading shape `--batches --cap` once had."""
    _skeptic_slots_file(tmp_path)
    rc, out = _from_batches(tmp_path)
    assert rc == 2 and "is not a directory" in out, out
    (tmp_path / "verify").mkdir()
    rc, out = _from_batches(tmp_path)
    assert rc == 2 and "no claims-*.json" in out, out


def test_from_batches_tolerates_the_empty_batch_and_claims_slots_the_skeleton_prints(tmp_path: Path) -> None:
    import json as _json
    _batches_dir(tmp_path)
    (tmp_path / "verify" / "claims-odd.json").write_text(_json.dumps([1, 2]), encoding="utf-8")
    _skeptic_slots_file(tmp_path, BATCH="", CLAIMS="  ")
    rc, out = _from_batches(tmp_path)
    assert rc == 0, out
    names = sorted(p.name for p in (tmp_path / "briefs").glob("skeptic-*.md"))
    assert names == ["skeptic-backbone.md", "skeptic-odd.md", "skeptic-security.md",
                     "skeptic-small.md"], names


# --- T11: `--slots` says what goes IN each slot (retro 2026-09-13, reminderrepo) -----------------
# `coyomap contract harvest` prints the agent half and strips the lead's, by design — so the only
# place saying that «SERVES» must name `Rn`/`UCn`/`CAPn`/`HPn` ids, and that «EXPECTED_COMPONENTS»
# is the slice's E from the pre-index, was a file the lead never opened. `--slots` printed bare
# empty strings. All 8 SERVES came back as map-section names and all 8 were refused at the barrier.

def test_every_shipped_contract_says_what_goes_in_every_one_of_its_slots() -> None:
    """The check with teeth. A slot with no one-line spec anywhere REFUSES, so a new slot cannot
    ship with an empty explanation beside its empty value."""
    for name in contract.CONTRACTS:
        specs = contract.slot_specs(name)
        assert set(specs) == set(contract.slots(name)), name
        for key, spec in specs.items():
            assert spec.strip(), f"{name}.{key} has an empty spec"


def test_the_skeleton_prints_each_spec_beside_its_own_empty_value() -> None:
    """The spec rides INSIDE the JSON, on a `//` line before the slot, because the lead redirects
    the skeleton to a file and fills it there."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert contract.main(["harvest", "--slots"]) == 0
    printed = json.loads(out.getvalue())
    keys = list(printed)
    for key in contract.slots("harvest"):
        assert keys.index(f"//{key}") == keys.index(key) - 1, f"{key}'s spec is not beside it"
    assert "granularity.per_dir" in printed["//EXPECTED_COMPONENTS"]
    assert "UC" in printed["//SERVES"] and "CAP" in printed["//SERVES"]


def test_the_lead_facing_spec_still_never_reaches_an_agent() -> None:
    """The separation is the reason this verb exists — a build once sent the lead's own half to ten
    skeptics. Saying more to the lead must not say more to the agent."""
    for name in contract.CONTRACTS:
        text = render(name)
        for spec in contract.slot_specs(name).values():
            assert spec[:60] not in text, f"{name}: a lead-facing spec crossed into the agent half"


def test_a_slot_with_no_spec_is_refused_and_named(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "method" / "templates").mkdir(parents=True)
    (home / "method" / "templates" / "toy-contract.md").write_text(
        "lead half\n\n- **«DESCRIBED»** — what this one holds.\n\n"
        "> agent half with «DESCRIBED» and «UNDESCRIBED».\n", encoding="utf-8")
    contract.CONTRACTS["toy"] = "toy-contract.md"
    try:
        with pytest.raises(ValueError, match="UNDESCRIBED"):
            contract.slot_specs("toy", root=home)
        assert contract.template_specs("toy", root=home) == {"DESCRIBED": "what this one holds."}
    finally:
        del contract.CONTRACTS["toy"]


def test_the_spec_check_has_no_exemption_and_the_one_false_slot_is_gone() -> None:
    """The check above covers every contract with nothing carved out. It found a FALSE slot doing
    it: `«key» parent_id` in the T5 addendum is the label a keyed relation draws on its arrow, not
    something a lead fills — and while it sat there in guillemets, appending that addendum to a
    harvest brief demanded a value for it and filling it would have destroyed the notation."""
    assert not hasattr(contract, "_SPECLESS"), "an exemption is a hole in the spec check"
    assert contract.slots("harvest-t5") == ["COYOMAP_HOME"]


def test_the_t5_addendum_rides_a_harvest_brief_on_the_same_slots_file() -> None:
    """The `>>` that produced a 1,217-byte brief holding only the addendum. The addendum's one slot
    is the harvest contract's own, so `--append` needs nothing extra from the lead."""
    values = make_slot_values("harvest")
    assert set(contract.union_slots(["harvest", "harvest-t5"])) == set(contract.slots("harvest"))
    text = contract.fill("harvest", values, append=["harvest-t5"])
    assert "«" not in text and "»" not in text
    assert "You are ALSO the T5 DOMAIN-MODEL owner" in text


def test_a_filled_slot_file_may_keep_the_comment_lines_the_skeleton_printed() -> None:
    """The lead edits the file `--slots` wrote, so the `//` lines come back in. `--fill` must read
    past them rather than call each one an unknown slot."""
    values = make_slot_values("rules")
    values["//REPO"] = "absolute path of the repo being mapped"
    assert "«" not in contract.fill("rules", values)


# --- T10: the doors half reaches the brief FILLED (retro 2026-09-13, reminderrepo) ---------------
# Turn 231 built each trace brief with `contract trace --fill`, then appended the doors half with a
# bare `>>`. `--fill` refuses a value still carrying guillemets; `>>` walked around the guard. Every
# brief but one shipped with nine literal slot names, and each of those 9 agents then ran one
# `lint-fragment --repo «REPO» …` that could not run.

def test_the_trace_and_doors_slot_sets_do_not_coincide() -> None:
    """The reason `--append` fills against the UNION and not against the first contract's slots.
    Assuming they coincided is what a `>>` silently assumes."""
    trace, doors = set(contract.slots("trace")), set(contract.slots("doors"))
    assert doors - trace == {"FLOWS", "MAP", "SURFACES"}
    assert trace - doors == {"USE_CASES", "SF_RANGE", "LEGEND", "WHERE_TO_LOOK", "your-fragment"}


def test_append_composes_both_halves_with_no_slot_left() -> None:
    values = make_slot_values("trace")
    values.update(make_slot_values("doors"))
    text = contract.fill("trace", values, append=["doors"])
    assert "«" not in text and "»" not in text
    assert "You are tracing use cases" in text and "doors\" retrofit" in text


def test_append_refuses_the_whole_brief_when_an_appended_slot_is_missing() -> None:
    """The point. A doors slot nobody filled must refuse the trace brief too, instead of shipping
    one brief that is half filled."""
    with pytest.raises(ValueError, match="no value given for.*FLOWS"):
        contract.fill("trace", make_slot_values("trace"), append=["doors"])


def test_the_skeleton_of_an_appended_pair_lists_both_contracts_slots() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert contract.main(["trace", "--slots", "--append", "doors"]) == 0
    printed = json.loads(out.getvalue())
    assert set(k for k in printed if not k.startswith("//")) == \
        set(contract.slots("trace")) | set(contract.slots("doors"))


def test_the_unfilled_form_says_out_loud_what_it_is() -> None:
    """`contract doors >> brief.md` is invisible to every check the tool makes, because the tool
    never sees the `>>`. So the one thing it can do is say what it just printed."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        assert contract.main(["doors"]) == 0
    assert "UNFILLED" in err.getvalue() and "FLOWS" in err.getvalue()
    assert "«FLOWS»" in out.getvalue()          # stdout is unchanged: it is still the raw contract


def test_an_unknown_append_name_is_refused() -> None:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert contract.main(["trace", "--append", "dorrs"]) == 2
    assert "no such contract" in err.getvalue()


# --- T12: many briefs in ONE run, refusing atomically (retro 2026-09-13, reminderrepo) -----------
# Turn 106 looped `contract harvest --fill` over 8 slices under `set -e`. All 8 exited 2 and wrote
# nothing; `set -e` does not abort a loop in this harness, so the trailing `&&` appended the T5
# addendum to a brief no fill had written. `record --lines-from` already solved this class: one
# process, one write, every line shape-checked before anything is written.

def _slots_dir(tmp: Path, name: str, agents: list[str], **over: str) -> Path:
    d = tmp / "slots"
    d.mkdir(parents=True, exist_ok=True)
    for agent in agents:
        values = make_slot_values(name)
        values.update(over)
        (d / f"{agent}.json").write_text(json.dumps(values), encoding="utf-8")
    return d


def _from_slots(tmp: Path, name: str, extra: list[str] | None = None) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = contract.main([name, "--from-slots", str(tmp / "slots"), "--out-dir",
                            str(tmp / "briefs"), *(extra or [])])
    return rc, buf.getvalue()


def test_one_run_writes_a_brief_per_slots_file_and_prints_its_pointer(tmp_path: Path) -> None:
    _slots_dir(tmp_path, "rules", ["r1", "r2", "r3"])
    rc, out = _from_slots(tmp_path, "rules")
    assert rc == 0, out
    assert sorted(p.name for p in (tmp_path / "briefs").glob("*.md")) == \
        ["r1.md", "r2.md", "r3.md"]
    assert "3 brief(s) written, 0 skipped" in out and out.count("Read it COMPLETELY") == 3


def test_one_bad_slots_file_writes_NOTHING_and_every_fault_is_named(tmp_path: Path) -> None:
    """The shape, not the cost: a loop that keeps going leaves part of a fan-out on disk and a lead
    that cannot tell which briefs are real."""
    d = _slots_dir(tmp_path, "rules", ["r1", "r2"])
    (d / "r3.json").write_text(json.dumps({"REPO": "  "}), encoding="utf-8")
    (d / "r4.json").write_text("{not json", encoding="utf-8")
    rc, out = _from_slots(tmp_path, "rules")
    assert rc == 2, out
    assert not (tmp_path / "briefs").exists(), "a refused batch left briefs behind"
    assert "2 of 4 slots file(s) are bad" in out
    assert "r3.json" in out and "r4.json" in out and "blank" in out


def test_a_batch_never_rewrites_a_brief_an_agent_may_be_reading(tmp_path: Path) -> None:
    _slots_dir(tmp_path, "rules", ["r1", "r2"])
    (tmp_path / "briefs").mkdir()
    (tmp_path / "briefs" / "r1.md").write_text("AN AGENT IS READING THIS", encoding="utf-8")
    rc, out = _from_slots(tmp_path, "rules")
    assert rc == 0, out
    assert (tmp_path / "briefs" / "r1.md").read_text(encoding="utf-8") == "AN AGENT IS READING THIS"
    assert "1 brief(s) written, 1 skipped" in out


def test_a_batch_of_trace_briefs_carries_the_doors_half_filled(tmp_path: Path) -> None:
    """T10 and T12 together — the run that replaces `--fill` in a loop plus `contract doors >>`."""
    values = make_slot_values("trace")
    values.update(make_slot_values("doors"))
    d = tmp_path / "slots"
    d.mkdir()
    for agent in ("t-ops", "t-browse"):
        (d / f"{agent}.json").write_text(json.dumps(values), encoding="utf-8")
    rc, out = _from_slots(tmp_path, "trace", ["--append", "doors"])
    assert rc == 0, out
    for agent in ("t-ops", "t-browse"):
        text = (tmp_path / "briefs" / f"{agent}.md").read_text(encoding="utf-8")
        assert "«" not in text and "»" not in text
        assert "doors\" retrofit" in text


def test_a_batch_of_harvest_briefs_records_every_budget(tmp_path: Path) -> None:
    """The single `--fill` records the budget `finalize` sums; the batch form must too, or a
    fan-out run this way ships a budgets file with a hole in it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    d = tmp_path / "slots"
    d.mkdir()
    for agent, budget in (("h1", "~6"), ("h2", "4-6")):
        values = _harvest_values(REPO_ABS=str(repo), EXPECTED_COMPONENTS=budget)
        values["agent-id"] = agent
        (d / f"{agent}.json").write_text(json.dumps(values), encoding="utf-8")
    rc, out = _from_slots(tmp_path, "harvest")
    assert rc == 0, out
    doc = json.loads((repo / ".coyomap" / "verify" / "budgets.json").read_text(encoding="utf-8"))
    assert doc["harvest"] == {"h1": 6, "h2": 4}, doc


# --- T7a: the closer's claims block is BUILT, not hand-typed (retro 2026-09-13) ------------------
# `contract closer` had only `--slots`/`--fill`, so the block was hand-built twice in one build, in
# two shapes. The second was a regex generator with no branch for a rule-site claim: 16 of 20
# refutations carried a map row and 4 carried none, and the closer answered `uphold` on all four
# rowless blocks and `unsure` on none. `dump` was typed once in 571 turns and `--edges` never.

def _tiny_map() -> str:
    return json.dumps({
        "format": "coyomap-map",
        "title": "Toy",
        "components": [
            {"id": "C1", "name": "Gate", "purpose": "Checks the caller may pass.",
             "source": "src/gate.py:10"},
            {"id": "C2", "name": "Store", "purpose": "Keeps the rows.", "source": "src/store.py:5"}],
        "edges": [{"src": "C1", "verb": "calls", "dst": "C2", "why": "asks for the row",
                   "where": "src/gate.py:22"}],
        "rules": [{"id": "BR1", "statement": "A caller with no token is refused.",
                   "sites": [{"where": "src/gate.py:31", "why": "Rejects the tokenless caller."}]}],
        "roles": [{"id": "R1", "name": "Caller", "kind": "human"}],
        "use_cases": [{"id": "UC1", "name": "Pass the gate", "actors": ["R1"],
                       "trigger": "A caller arrives", "outcome": "the row is returned"}],
        "flows": [{"uc": "UC1", "title": "Pass the gate", "steps": [
            {"n": 1, "src": "R1", "dst": "C1", "phrase": "present the token"},
            {"n": 2, "src": "C1", "dst": "C2", "phrase": "ask for the row",
             "where": "src/gate.py:22"}]}],
    })


def _refuted(claim: str, note: str = "the line does not do that") -> dict[str, object]:
    return {"claim": claim, "grounded": False, "evidence": "src/gate.py:31",
            "skeptic": "rule-1", "note": note}


def make_closer_inputs(tmp: Path, claims: list[str]) -> tuple[Path, Path, Path]:
    """The three paths `--from-verdicts` needs: the verdicts dir, the map, the slots file."""
    verify = tmp / "verify"
    verify.mkdir(parents=True, exist_ok=True)
    (verify / "verdicts-rule-1.json").write_text(
        json.dumps({"grounding": [{"claim": "C1 calls C2", "grounded": True,
                                   "evidence": "src/gate.py:22", "skeptic": "rule-1", "note": "ok"}]
                    + [_refuted(c) for c in claims]}), encoding="utf-8")
    map_path = tmp / "project-map.json"
    map_path.write_text(_tiny_map(), encoding="utf-8")
    slots_file = tmp / "closer-slots.json"
    slots_file.write_text(json.dumps({"REPO": str(tmp), "AGENT_ID": "closer1", "CLAIMS": ""}),
                          encoding="utf-8")
    return verify, map_path, slots_file


def _from_verdicts(tmp: Path, extra: list[str] | None = None) -> tuple[int, str, Path]:
    out = tmp / "closer.md"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = contract.main(["closer", "--from-verdicts", str(tmp / "verify"), "--map",
                            str(tmp / "project-map.json"), "--fill", str(tmp / "closer-slots.json"),
                            "--out", str(out), *(extra or [])])
    return rc, buf.getvalue(), out


#: One refutation of each kind the build produced. The rule site is the kind the hand-written
#: generator had no branch for, and it is the one that reached the closer with no map row.
_FOUR_KINDS = [
    "Component C1 (Gate) is described as: Checks the caller may pass.",
    "C1 calls C2",
    "UC1 step 2: C1 → C2 — ask for the row",
    "Rule 'A caller with no token is refused.' is enforced at src/gate.py:31 — Rejects the "
    "tokenless caller.",
]


def test_every_claim_kind_reaches_the_closer_with_its_map_row_and_its_edges(tmp_path: Path) -> None:
    """The finding, as a test: all four kinds, each carrying `dump --id` AND `dump --edges`, with no
    block reading NO MAP ROW FOUND."""
    make_closer_inputs(tmp_path, _FOUR_KINDS)
    rc, out, brief_path = _from_verdicts(tmp_path)
    assert rc == 0, out
    text = brief_path.read_text(encoding="utf-8")
    assert "NO MAP ROW FOUND" not in text
    for claim in _FOUR_KINDS:
        assert claim in text, claim
    assert "dump --id BR1" in text, "the rule-site claim reached the closer with no map row"
    assert "dump --edges C1" in text and "dump --record C1" in text
    assert "dump --id UC1" in text and '"phrase": "ask for the row"' in text
    assert "«" not in text


def test_a_claim_the_map_no_longer_makes_is_labelled_rather_than_dropped(tmp_path: Path) -> None:
    """The contract tells the closer to answer `unsure` when rows are missing. It can only do that
    if the brief SAYS they are missing."""
    make_closer_inputs(tmp_path, ["Auth surface 'nothing' is protected by: nobody"])
    rc, out, brief_path = _from_verdicts(tmp_path)
    assert rc == 0, out
    assert "NO MAP ROW FOUND" in brief_path.read_text(encoding="utf-8")


def test_an_exclusion_that_matches_nothing_is_an_ERROR(tmp_path: Path) -> None:
    """The measured bug: `done={"BR205","BR66","BR104"}` tested against claim TEXT, which carries
    the rule statement and never the id — 0 of 20 matched, silently, and four settled refutations
    were re-sent to the second closer."""
    make_closer_inputs(tmp_path, _FOUR_KINDS)
    rc, out, _ = _from_verdicts(tmp_path, ["--exclude", "BR999"])
    assert rc == 2, out
    assert "matched no refutation" in out


def test_an_exclusion_takes_a_rule_id_and_the_claim_text_never_carries_one(tmp_path: Path) -> None:
    make_closer_inputs(tmp_path, _FOUR_KINDS)
    rule_claim = _FOUR_KINDS[3]
    assert "BR1" not in rule_claim, "the claim text carries the statement, never the id"
    rc, out, brief_path = _from_verdicts(tmp_path, ["--exclude", "BR1"])
    assert rc == 0, out
    assert rule_claim not in brief_path.read_text(encoding="utf-8")


def test_a_second_wave_excludes_what_the_first_closer_settled(tmp_path: Path) -> None:
    """The durable answer (T7b) feeding the next wave (T7a): the closer's own verdicts file names
    what it judged, by id."""
    make_closer_inputs(tmp_path, _FOUR_KINDS)
    rc, out, first = _from_verdicts(tmp_path)
    assert rc == 0, out
    ids = re.findall(r"^### (\S+) —", first.read_text(encoding="utf-8"), re.M)
    assert len(ids) == 4, ids
    settled = tmp_path / "closer-closer1.json"
    settled.write_text(json.dumps({"grounding": [
        {"id": ids[0], "claim": _FOUR_KINDS[0], "verdict": "uphold", "grounded": False,
         "evidence": "src/gate.py:10", "skeptic": "closer1", "note": "read it"}]}),
        encoding="utf-8")
    buf = io.StringIO()
    second = tmp_path / "closer2.md"
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = contract.main(["closer", "--from-verdicts", str(tmp_path / "verify"), "--map",
                            str(tmp_path / "project-map.json"), "--fill",
                            str(tmp_path / "closer-slots.json"), "--out", str(second),
                            "--settled", str(settled)])
    assert rc == 0, buf.getvalue()
    text = second.read_text(encoding="utf-8")
    assert _FOUR_KINDS[0] not in text and _FOUR_KINDS[3] in text


def test_a_refutation_id_names_the_batch_and_the_row(tmp_path: Path) -> None:
    """Stable across waves, because the verdicts file is written once and never edited — the
    property a sequence number over a shrinking list does not have."""
    make_closer_inputs(tmp_path, _FOUR_KINDS)
    refs = contract.refutations(tmp_path / "verify")
    assert [r.id for r in refs] == ["rule-1#2", "rule-1#3", "rule-1#4", "rule-1#5"]
    assert refs[0].skeptic == "rule-1"


def test_a_slots_file_that_fills_CLAIMS_itself_is_refused(tmp_path: Path) -> None:
    """The same rule `--from-batches` has: a value this verb composes would be silently overwritten."""
    make_closer_inputs(tmp_path, _FOUR_KINDS)
    (tmp_path / "closer-slots.json").write_text(
        json.dumps({"REPO": str(tmp_path), "AGENT_ID": "c1", "CLAIMS": "typed by hand"}),
        encoding="utf-8")
    rc, out, _ = _from_verdicts(tmp_path)
    assert rc == 2 and "builds «CLAIMS» itself" in out, out


def test_an_empty_or_missing_verdicts_directory_is_refused(tmp_path: Path) -> None:
    make_closer_inputs(tmp_path, _FOUR_KINDS)
    for target in (tmp_path / "verify" / "verdicts-rule-1.json",):
        target.unlink()
    rc, out, _ = _from_verdicts(tmp_path)
    assert rc == 2 and "no verdicts-*.json" in out, out


# --- T7b: the closer's answer has a durable home ------------------------------------------------
# `.coyomap/verify/` held 0 closer artifacts, and 22 of 24 refutation judgements on one build were
# applied on the strength of a chat sentence, about "the re-read that decides what the map ends up
# saying".

def test_the_closer_is_told_to_write_its_verdicts_beside_the_skeptics() -> None:
    text = render("closer")
    assert ".coyomap/verify/closer-«AGENT_ID».json" in text
    assert '"grounding"' in text and '"skeptic": "«AGENT_ID»"' in text


def test_the_closer_file_is_a_verdicts_file_the_existing_reader_can_load() -> None:
    """It is written in the skeptics' own shape on purpose, so `grounding lint --verdicts` reads it
    with no change to that command: uphold → grounded false, reject → true, unsure →
    "unverifiable"."""
    text = render("closer")
    for word, value in (("uphold", "`false`"), ("reject", "`true`"), ("unsure", '`"unverifiable"`')):
        assert f"{word} → {value}" in text, word


def test_the_closer_carries_an_agent_id_so_two_waves_never_collide() -> None:
    assert set(contract.slots("closer")) == {"REPO", "CLAIMS", "AGENT_ID"}


# --- review round: the four findings the adversarial pass returned --------------------------------

def _map_with_moved_rule_site() -> str:
    """The map as it stands AFTER a rule refutation is applied: the statement is untouched, the
    refuted SITE has moved. `resolve_claim` matches statement AND anchor AND why, so the claim about
    the old site no longer resolves — and its text carries the statement, never the id."""
    doc = json.loads(_tiny_map())
    doc["rules"][0]["sites"] = [{"where": "src/gate.py:99", "why": "Rejects it earlier now."}]
    return json.dumps(doc)


_RULE_CLAIM = ("Rule 'A caller with no token is refused.' is enforced at src/gate.py:31 — "
               "Rejects the tokenless caller.")


def test_a_rule_claim_whose_site_moved_still_finds_its_rule(tmp_path: Path) -> None:
    """The finding: run on the build's own verdicts this gave 16 of 20 refutations a map row and 4
    none — every one a rule site whose refutation had already been applied. That is the identical
    split the hand-written generator produced, which is the whole reason this verb exists."""
    from coyomap.model import load_model
    live = load_model(_map_with_moved_rule_site())
    assert "BR1" not in _RULE_CLAIM, "a rule claim's text carries the statement, never the id"
    assert contract.dump_ids(live, _RULE_CLAIM) == ["BR1"]


def test_the_documented_exclude_example_works_on_a_moved_rule_site(tmp_path: Path) -> None:
    """Sharpest form of the same bug: `--exclude BR205` is the flag's own help-text example, and on
    the build's own verdicts it exited 2 with `matched no refutation: BR205` — while the error
    naming it as valid was printed by the same run."""
    make_closer_inputs(tmp_path, [_RULE_CLAIM])
    (tmp_path / "project-map.json").write_text(_map_with_moved_rule_site(), encoding="utf-8")
    rc, out, _ = _from_verdicts(tmp_path, ["--exclude", "BR1"])
    assert rc == 2 and "every one of the 1 refutation(s)" in out, out   # excluded, not unmatched
    assert "matched no refutation" not in out, out


def test_two_rules_stating_the_same_decision_are_both_named(tmp_path: Path) -> None:
    """Answering with one of them silently picks a side; the brief names both so the closer sees it."""
    from coyomap.model import load_model
    doc = json.loads(_map_with_moved_rule_site())
    twin = dict(doc["rules"][0], id="BR2")
    doc["rules"].append(twin)
    assert contract.dump_ids(load_model(json.dumps(doc)), _RULE_CLAIM) == ["BR1", "BR2"]


def make_description_refutation(eid: str) -> contract.Refutation:
    return contract.Refutation(id="description-1#6",
                               claim=f"Component {eid} (Gate) is described as: Checks the caller.",
                               evidence="src/gate.py:10", skeptic="description-1", note="no")


def test_an_id_the_map_no_longer_holds_still_tells_the_closer_to_answer_unsure(tmp_path: Path) -> None:
    """The second finding. The guidance was gated on "no id was FOUND", so a claim naming `C101`
    against a map without `C101` printed `NOT IN THE MAP` and no instruction at all — the exact
    shape that returned four `uphold`s and zero `unsure`."""
    from coyomap.model import load_model
    doc = json.loads(_tiny_map())
    doc["components"] = [c for c in doc["components"] if c["id"] != "C1"]
    doc["edges"], doc["flows"] = [], []
    gone = load_model(json.dumps(doc))
    block = contract.claims_block(gone, [make_description_refutation("C1")])
    assert "NOT IN THE MAP" in block
    assert "Return `unsure`" in block, "a rowless block reached the closer with no instruction"
    assert "The map holds no C1" in block
    assert block.splitlines()[0].endswith("NO MAP ROW FOUND")


def make_budgets_file(repo: Path, harvest: dict[str, int], session: str | None) -> Path:
    """A `budgets.json` as an earlier build left it. `session=None` writes a file with NO session
    key at all, which is what a build made before that field existed leaves behind."""
    (repo / ".coyomap" / "verify").mkdir(parents=True, exist_ok=True)
    doc: dict[str, object] = {"harvest": harvest}
    if session is not None:
        doc["session"] = session
    path = repo / ".coyomap" / "verify" / "budgets.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def make_harvest_slots(d: Path, agents: list[str], repo: Path, budget: str = "6") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for agent in agents:
        values = _harvest_values(REPO_ABS=str(repo), EXPECTED_COMPONENTS=budget)
        values["agent-id"] = agent
        (d / f"{agent}.json").write_text(json.dumps(values), encoding="utf-8")
    return d


def _fill_one(tmp: Path, agent: str, repo: Path, out: Path) -> tuple[int, str]:
    """ONE `contract harvest --fill` call — the shape the method dispatches harvest in, eight times
    per build, and the path the first version of this guard did not cover."""
    make_harvest_slots(tmp / "slots1", [agent], repo)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = contract.main(["harvest", "--fill", str(tmp / "slots1" / f"{agent}.json"),
                            "--out", str(out)])
    return rc, buf.getvalue()


def test_one_fill_call_will_not_discard_another_builds_budgets(tmp_path: Path) -> None:
    """THE PATH THAT MATTERS. `budgets.json` is written for `harvest` alone, and the method
    dispatches harvest one `--fill` per slice — so a guard that lived only in the batch verb was on
    a path harvest never takes. Three such calls under a fresh session turned `{h1..h8}` into
    `{h1,h2,h3}`, exit 0 and no warning on all three, after which `finalize` summed 23 budgeted
    against 126 shipped and raised a band failure about a harvest that never happened."""
    repo = tmp_path / "repo"
    repo.mkdir()
    held = {f"h{n}": 6 for n in range(1, 9)}
    path = make_budgets_file(repo, held, "the-earlier-build")
    rc, out = _fill_one(tmp_path, "h1", repo, tmp_path / "h1.md")
    assert rc == 2, out
    assert "already records `h1` under build the-earlier-build" in out
    assert "drop 7 sibling slice(s)" in out and "h2, h3, h4, h5, h6, h7, +1 more" in out
    assert json.loads(path.read_text(encoding="utf-8"))["harvest"] == held, "the file was rewritten"
    assert not (tmp_path / "h1.md").exists(), "a refused budget left a filled brief behind"


def test_a_rebuild_that_renames_its_agents_is_never_refused(tmp_path: Path) -> None:
    """`record_budget`'s own docstring says a rebuild does exactly this — `h1..h12` one build,
    `h-entry-gateway…` the next. The first version of this guard refused it, and the test that was
    supposed to cover the case reused `h1, h2` and so never exercised a rename at all."""
    repo = tmp_path / "repo"
    repo.mkdir()
    path = make_budgets_file(repo, {f"h{n}": 6 for n in range(1, 9)}, "the-earlier-build")
    rc, out = _fill_one(tmp_path, "h-entry-gateway", repo, tmp_path / "hx.md")
    assert rc == 0, out
    assert (tmp_path / "hx.md").exists()
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["harvest"] == {"h-entry-gateway": 6}, doc   # started over, which is right here


def test_a_budgets_file_with_no_session_key_is_not_silently_reset(tmp_path: Path) -> None:
    """`doc.get("session") in (None, session)` short-circuited the refusal, so a file written before
    that field existed was reset anyway: 8 slices to 3, exit 0, no warning."""
    repo = tmp_path / "repo"
    repo.mkdir()
    held = {f"h{n}": 6 for n in range(1, 9)}
    path = make_budgets_file(repo, held, None)
    rc, out = _fill_one(tmp_path, "h1", repo, tmp_path / "h1.md")
    assert rc == 2, out
    assert "(no session id)" in out, out
    assert json.loads(path.read_text(encoding="utf-8"))["harvest"] == held


def test_the_batch_path_refuses_on_the_very_same_condition(tmp_path: Path) -> None:
    """One condition, asked in two places. The batch asks it in its plan phase only so that a
    refusal writes no briefs at all — two copies of the reasoning is how the first guard ended up on
    a path harvest never takes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    held = {f"h{n}": 6 for n in range(1, 9)}
    path = make_budgets_file(repo, held, "the-earlier-build")
    make_harvest_slots(tmp_path / "slots", ["h1", "h2", "h3"], repo)
    rc, out = _from_slots(tmp_path, "harvest", [])
    assert rc == 2, out
    assert "3 of 3 slots file(s) are bad" in out and "already records `h1`" in out
    assert not (tmp_path / "briefs").exists(), "a refused batch left briefs behind"
    assert json.loads(path.read_text(encoding="utf-8"))["harvest"] == held


def test_the_same_build_filling_its_own_slices_again_is_never_refused(tmp_path: Path) -> None:
    """A repair or a second wave inside ONE build merges, and must keep doing so — the refusal is
    about another build's file, never about this one's."""
    repo = tmp_path / "repo"
    repo.mkdir()
    session = os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    doc = contract.budgets_doc(repo)
    assert contract.budget_conflict({"harvest": {"h1": 6}, "session": "s"}, "h1", "s") is None
    assert contract.budget_conflict({"harvest": {"h1": 6}, "session": "s"}, "h1", None) is None
    assert doc == {} and session is not None


def test_a_missing_appended_slot_names_the_contract_it_belongs_to() -> None:
    """`no value given for: FLOWS, MAP, SURFACES` sent a lead grepping trace-contract.md for three
    slots that all live in doors-contract.md."""
    with pytest.raises(ValueError) as exc:
        contract.fill("trace", make_slot_values("trace"), append=["doors"])
    message = str(exc.value)
    assert "FLOWS (doors)" in message and "SURFACES (doors)" in message, message
    assert "USE_CASES" not in message, "a trace slot that WAS given must not be listed"


def test_the_usage_no_longer_offers_the_form_it_now_warns_about() -> None:
    """`contract harvest > <scratch>/harvest-contract.md` was still in the help while the same run
    printed `WARNING: this is the UNFILLED … contract`, and method.md had stopped recommending it."""
    assert "> <scratch>/harvest-contract.md" not in contract._USAGE
    assert "budgets.json" in contract._USAGE, "the one write outside --out is undocumented"


def test_the_rowless_instruction_names_what_happens_without_it() -> None:
    """A closer SKIMS a brief. The instruction alone read as boilerplate; the consequence beside it
    is what makes the sentence land, and the consequence is measured — four blocks of exactly this
    shape came back `uphold`, with no `unsure` across two waves."""
    from coyomap.model import load_model
    doc = json.loads(_tiny_map())
    doc["components"], doc["edges"], doc["flows"] = [], [], []
    block = contract.claims_block(load_model(json.dumps(doc)), [make_description_refutation("C1")])
    assert "Do NOT settle it from the claim text and the skeptic's note alone" in block
    assert "four blocks arrived exactly like this one" in block and "`uphold`" in block
