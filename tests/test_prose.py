"""Tests for the countable readability checks on the map's reader-facing prose (`coyomap.prose`).

The module's whole claim is that it COUNTS rather than judges, so these tests pin the boundaries: a
20-word sentence is fine and a 21-word one is not, a backticked literal is a quotation rather than a
code name, and a summary line names a few fields and counts the rest through the shared truncation
helper instead of printing two hundred.
"""
from __future__ import annotations

from pathlib import Path

from coyomap import prose
from coyomap.model import (
    BusinessRule, Component, Dep, Entity, ExtraSection, GlossaryRow, Group, HappyStep, ProjectModel,
    Role, Stake, Store, UseCase,
)
from coyomap.model import TestRow as GapRow  # aliased: a bare `TestRow` trips pytest class collection


def make_sentence(words: int) -> str:
    return " ".join(["word"] * words) + "."


def make_findings(kind: str, count: int) -> list[prose.Finding]:
    return [prose.Finding(kind, f"C{n} purpose", "detail") for n in range(1, count + 1)]


def make_model() -> ProjectModel:
    """A map whose every reader-facing prose field is short, plain and self-contained."""
    m = ProjectModel(title="Demo", goal="A demo.")
    m.roles = [Role(id="R1", name="Andy", kind="human", wants="to place an order")]
    m.use_cases = [UseCase(id="UC1", name="Place order",
                           trigger="A shopper submits a basket and gets an order.", outcome="")]
    m.happy_path = [HappyStep(id="HP1", uc="UC1", why="nothing precedes it")]
    m.components = [Component(id="C1", name="Checkout", purpose="Takes a basket and books an order.")]
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="Everything a shopper buys with.",
                            stakes=[Stake(actor="R1", stake="picks a basket and pays for it")])]
    # `alternative` and `not_an_interface` are NOT walked: the viewer's dependency card draws
    # neither (see test_the_two_dependency_fields_the_viewer_never_draws_are_not_walked).
    m.deps = [Dep(id="D1", name="Postgres", kind="datastore", used_for="Stores every order.",
                  alternative="A file on disk, when Postgres is down.",
                  not_an_interface="Only the product reads what it writes here.")]
    m.entities = [Entity(id="E1", name="Order", meaning="What a shopper has paid for.",
                         store=Store(dep="D1", container="orders", notes="Kept for seven years."))]
    m.tests_note = "Every row comes from reading the suites, not from running them."
    m.tests = [GapRow(targets=["C1"], tested="partial", gap="Nothing checks a refused card.")]
    m.extras = [ExtraSection(heading="Unclaimed surfaces",
                             body="- C1: The health probe is a tool for the operator.")]
    m.rules = [BusinessRule(id="BR1", name="Owner-only cancellation",
                            statement="Only the owner of an order may cancel it.",
                            risk="A stranger could cancel another shopper's order.")]
    m.glossary = [GlossaryRow(term="basket", meaning="What a shopper has chosen but not yet paid for.")]
    return m


# --- sentence length -------------------------------------------------------------------------

def test_a_twenty_word_sentence_is_not_long_and_a_twenty_one_word_one_is() -> None:
    assert prose.long_sentences(make_sentence(20)) == []
    assert len(prose.long_sentences(make_sentence(21))) == 1


def test_each_long_sentence_in_one_field_is_reported_separately() -> None:
    text = f"{make_sentence(25)} {make_sentence(3)} {make_sentence(30)}"
    assert len(prose.long_sentences(text)) == 2


def test_the_limit_is_a_parameter_so_map_text_can_differ_from_chat() -> None:
    assert prose.long_sentences(make_sentence(12), limit=10) != []
    assert prose.long_sentences(make_sentence(12), limit=15) == []


# --- em dash ---------------------------------------------------------------------------------

def test_em_dashes_are_counted_and_a_quoted_one_is_not() -> None:
    assert prose.em_dash_count("Orders are booked — and then paid.") == 1
    assert prose.em_dash_count("It prints `a — b` verbatim.") == 0


# --- code names ------------------------------------------------------------------------------

def test_code_shapes_are_found_in_plain_text() -> None:
    assert prose.code_tokens("Reads src/order.py and books it.") == ["src/order.py"]
    # one word, one finding: the call form wins over the snake_case form inside it
    assert prose.code_tokens("Calls cancel_order() on the way out.") == ["cancel_order()"]
    assert prose.code_tokens("Pass --dry-run to preview.") == ["--dry-run"]
    assert prose.code_tokens("The order_total is recomputed.") == ["order_total"]


def test_ordinary_product_prose_names_no_code() -> None:
    assert prose.code_tokens("Only the owner of an order may cancel it.") == []
    assert prose.code_tokens("Stores every order and every payment.") == []


def test_a_backticked_literal_is_a_quotation_not_a_code_name() -> None:
    assert prose.code_tokens("The state is `in_progress` until paid.") == []


# --- code-shaped NAMES -------------------------------------------------------------------------

def test_a_humped_name_is_code_and_a_sentence_is_never_scanned_for_one() -> None:
    """The class's own spelling is how a map picks up a code name, and it is a NAME rule only:
    prose legitimately writes PostgreSQL and NestJS."""
    assert prose.name_tokens("NotificationSecurityData") == ["NotificationSecurityData"]
    assert prose.name_tokens("DateGeneratorDaily") == ["DateGeneratorDaily"]
    assert prose.name_tokens("createUserSchema") == ["createUserSchema"]
    # the sentence walk must not learn this shape
    assert prose.code_tokens("Holds the notification security data for one activity.") == []
    assert prose.code_tokens("Runs on PostgreSQL and NestJS.") == []


def test_a_plain_label_and_an_all_caps_product_are_not_code_shaped() -> None:
    assert prose.name_tokens("Reminder batch") == []
    assert prose.name_tokens("Who may see a reminder") == []
    # An acronym run never gets a lower-case tail, which is what keeps the vendors out.
    for vendor in ("PostgreSQL", "NestJS", "RxJS", "MongoDB", "FastAPI", "LocationIQ", "PyJWT"):
        assert prose.name_tokens(vendor) == [], vendor


def test_a_product_name_the_map_already_knows_is_cleared() -> None:
    """A component called "MongoDB stores" names a vendor's product, and the map's own dependency
    list is what knows which words those are. The clearing is exact, never a prefix."""
    assert prose.name_tokens("MongoDB stores", {"MongoDB"}) == []
    assert prose.name_tokens("PyMongo", {"PyMongo"}) == []
    assert prose.name_tokens("MongoClient", {"MongoDB"}) == ["MongoClient"]


def test_the_name_table_still_carries_every_sentence_shape() -> None:
    """One detector, two vocabularies: a name spelled `deploy-production.sh` or `user_prefs` is as
    much code as a humped one, and those shapes are defined once."""
    assert prose.name_tokens("deploy-production.sh") == ["deploy-production.sh"]
    assert prose.name_tokens("user_prefs") == ["user_prefs"]


# --- bare pointers ---------------------------------------------------------------------------

def test_a_field_opening_with_a_pointer_word_is_flagged() -> None:
    assert prose.opens_with_bare_pointer("It books the order.") == "It"
    assert prose.opens_with_bare_pointer("This is the checkout.") == "This"


def test_a_pointer_word_inside_the_sentence_is_fine() -> None:
    assert prose.opens_with_bare_pointer("The checkout books it.") == ""
    assert prose.opens_with_bare_pointer("Items are priced when the shopper adds them.") == ""


# --- unresolved references (rule 4 beyond the opening pointer) -------------------------------

def test_a_split_the_box_never_names_is_flagged() -> None:
    # the sentence that motivated the rule: which two kinds? The box never says.
    assert prose.unresolved_references(
        "Mounting the MCP servers a team shares, in either kind, and keeping each one configured "
        "and running.") == ["either kind"]


def test_every_reference_shape_is_recognized() -> None:
    assert prose.unresolved_references("Configuration flows through both modes.") == ["both modes"]
    assert prose.unresolved_references("Accepts such kinds without a check.") == ["such kinds"]
    assert prose.unresolved_references("Falls back to the other way.") == ["the other way"]
    assert prose.unresolved_references("The gateway prefers the latter.") == ["the latter"]
    assert prose.unresolved_references("The former is cached.") == ["The former"]


def test_a_reference_without_a_category_noun_is_not_flagged() -> None:
    # "both servers" names WHAT the two are; only a category word ("kind", "mode") hides the split
    assert prose.unresolved_references("Restarts both servers on deploy.") == []
    assert prose.unresolved_references("The kind of MCP decides the mount.") == []


def test_alternatives_named_in_an_earlier_sentence_resolve_the_reference() -> None:
    assert prose.unresolved_references(
        "The policy check and the argument check run first. Both checks must pass.") == []


def test_the_same_sentences_own_and_is_not_an_enumeration() -> None:
    # "Opens and holds" is the sentence's clause structure, not the two transports being named
    assert prose.unresolved_references(
        "Opens and holds the live connection to each upstream, in either transport, and keeps "
        "its stored credentials valid.") == ["either transport"]


def test_two_glossary_terms_before_the_reference_resolve_it() -> None:
    text = "Serves Remote HTTP MCPs and Hosted stdio MCPs; either kind mounts the same way."
    assert prose.unresolved_references(text, ["Remote HTTP MCP", "Hosted stdio MCP"]) == []
    assert prose.unresolved_references(text, ["Remote HTTP MCP"]) == ["either kind"]


def test_a_trailing_or_enumeration_in_the_same_sentence_resolves_it() -> None:
    assert prose.unresolved_references("Runs in either mode: standalone or cloud.") == []


def test_unresolved_reference_rides_field_findings_and_the_summary() -> None:
    found = prose.field_findings("CAP2 purpose", "Mounting the shared servers, in either kind.")
    assert [f.kind for f in found] == ["unresolved reference"]
    line = prose.summarize(found)[0]
    assert line.startswith("1 prose field with an unresolved reference")
    assert "name the alternatives" in line


# --- per-field findings ----------------------------------------------------------------------

def test_a_clean_field_produces_nothing_and_an_empty_field_is_skipped() -> None:
    assert prose.field_findings("C1 purpose", "Takes a basket and books an order.") == []
    assert prose.field_findings("C1 purpose", "") == []
    assert prose.field_findings("C1 purpose", "   ") == []


def test_one_field_can_carry_several_kinds_at_once() -> None:
    text = ("It " + " ".join(["word"] * 25) + " — see src/order.py.")
    kinds = {f.kind for f in prose.field_findings("C1 purpose", text)}
    assert kinds == {"long sentence", "em dash", "code name", "bare pointer"}


def test_the_finding_names_the_field_in_readers_words_not_a_code_location() -> None:
    found = prose.field_findings("BR1 statement", "It decides.")
    assert found[0].where == "BR1 statement"


# --- summarizing -----------------------------------------------------------------------------

def test_a_summary_line_leads_with_the_count_and_carries_the_remedy() -> None:
    line = prose.summarize(make_findings("long sentence", 1))[0]
    assert line.startswith("1 prose field with a long sentence")
    assert "one idea per sentence" in line


def test_many_findings_of_one_kind_collapse_to_one_counted_line() -> None:
    lines = prose.summarize(make_findings("long sentence", 200))
    assert len(lines) == 1
    assert lines[0].startswith("200 prose fields")
    assert "+197 more" in lines[0]     # truncation goes through the shared reporting helper


def test_each_kind_gets_its_own_line_and_an_absent_kind_gets_none() -> None:
    lines = prose.summarize([*make_findings("em dash", 2), *make_findings("code name", 1)])
    assert len(lines) == 2
    assert not any("bare pointer" in line for line in lines)


# --- walking a map ---------------------------------------------------------------------------

def test_every_reader_facing_field_is_walked() -> None:
    labels = {where for where, _text in prose.iter_prose_fields(make_model())}
    assert labels == {"goal", "C1 purpose", "CAP1 purpose", "CAP1 stake for R1",
                      # ONE ENTRY for the pair, although the map holds them apart: the BOX these
                      # checks read by is the card, and the card shows the two together.
                      "UC1 trigger and outcome",
                      "BR1 statement", "BR1 risk", "D1 used for", "R1 wants", "HP1 why",
                      "glossary 'basket'", "E1 meaning", "E1 store notes", "tests note",
                      "tests row C1 gap", "record 'Unclaimed surfaces' line 1"}


def test_a_stake_and_the_tests_note_ride_the_narrow_surface_and_the_rest_do_not() -> None:
    """The narrow surface is what the reading fan-out is billed for. A stake is the label on a
    Features-page arrow and there are at most fifteen per live map; the tests note is one field.
    Neither moved a live map's batch count. A test gap, a store note and a recorded line are
    drill-down text, up to 54, 53 and 57 of them per map: wide only."""
    narrow = {where for where, _text in prose.iter_prose_fields(make_model(), wide=False)}
    assert {"CAP1 stake for R1", "tests note"} <= narrow
    assert not narrow & {"tests row C1 gap", "E1 store notes", "E1 meaning",
                         "record 'Unclaimed surfaces' line 1"}


def test_the_goal_is_walked_first_and_on_the_narrow_surface_too() -> None:
    """The one reader-facing field the walk skipped until 2026-09-11: on the three live maps 7 of its
    22 sentences were over the limit and nothing had said so."""
    m = make_model()
    m.goal = make_sentence(30)
    assert next(prose.iter_prose_fields(m, wide=False)) == ("goal", m.goal)
    assert [f.where for f in prose.scan(prose.iter_prose_fields(m))] == ["goal"]


def test_a_plainly_written_map_produces_no_findings() -> None:
    assert prose.scan(prose.iter_prose_fields(make_model())) == []


def test_a_long_purpose_on_a_real_map_is_found_through_the_walk() -> None:
    m = make_model()
    m.components[0].purpose = make_sentence(30)
    found = prose.scan(prose.iter_prose_fields(m))
    assert [f.kind for f in found] == ["long sentence"]
    assert found[0].where == "C1 purpose"


# --- batching for the read fan-out ------------------------------------------------------------

def test_empty_fields_never_reach_a_batch() -> None:
    """A batch padded with blanks spends a fan-out's attention on nothing, and the count printed to
    the lead would stop being the work done."""
    batches = prose.batch_fields([("C1 purpose", "Books an order."), ("C2 purpose", "  "),
                                  ("C3 purpose", "")], cap=10)
    assert batches == [[("C1 purpose", "Books an order.")]]


def test_batches_respect_the_cap_and_keep_map_order() -> None:
    fields = [(f"C{n} purpose", f"Does thing {n}.") for n in range(1, 8)]
    batches = prose.batch_fields(fields, cap=3)
    assert [len(b) for b in batches] == [3, 3, 1]
    assert [where for b in batches for where, _t in b] == [w for w, _t in fields]


def test_a_cap_below_one_is_refused_rather_than_looping_forever() -> None:
    try:
        prose.batch_fields([("C1 purpose", "x")], cap=0)
    except ValueError:
        return
    raise AssertionError("cap=0 must raise, not produce an endless slice")


def test_the_read_prompt_asks_for_the_two_rules_a_counter_cannot_judge() -> None:
    text = prose.build_read_prompt()
    assert "UNKNOWN WORD" in text and "LOST PRECISION" in text


def test_the_read_prompt_forbids_repeating_what_is_already_counted() -> None:
    """Without this the fan-out re-reports 486 long sentences and buries its own two findings under
    a number the lead already had."""
    text = prose.build_read_prompt()
    assert "Do NOT report sentence length" in text
    for counted in ("em dash", "code name", "opening"):
        assert counted in text


# --- the six arrays this walk was blind to ----------------------------------------------------
# Both consumers read `iter_prose_fields` — the reading fan-out and the deterministic long-sentence
# gate — so a field it does not yield is a field NOTHING checks. On the 2026-08-29 mcpolis map it
# yielded 477 non-empty fields and skipped 1,171: every flow step phrase and note, every entry
# point trigger, every entity meaning, every flow title, and the whole interfaces section. Widening
# it took that map's long-sentence count from 1 to 25.

def _walked(m) -> dict[str, str]:
    from coyomap.prose import iter_prose_fields
    return {where: text for where, text in iter_prose_fields(m)}


def test_a_flow_step_phrase_and_note_are_reader_facing():
    from coyomap.model import Flow, FlowStep, ProjectModel
    m = ProjectModel(title="D", goal="g")
    m.flows = [Flow(uc="UC1", title="Sign in", steps=[
        FlowStep(n=1, src="R1", dst="C1", phrase="opens the sign-in page", note="a note")])]
    walked = _walked(m)
    assert "opens the sign-in page" in walked.values(), walked
    assert "a note" in walked.values(), walked
    assert "Sign in" in walked.values(), walked


def test_an_entry_point_trigger_and_an_entity_meaning_are_reader_facing():
    from coyomap.model import Entity, EntryPoint, ProjectModel
    m = ProjectModel(title="D", goal="g")
    m.entry_points = [EntryPoint(id="EP1", kind="http-route", trigger="a person opens the page")]
    m.entities = [Entity(id="E1", name="Token", meaning="what a headless agent signs in with")]
    vals = list(_walked(m).values())
    assert "a person opens the page" in vals, vals
    assert "what a headless agent signs in with" in vals, vals


def test_an_interfaces_what_is_reader_facing():
    """Its crossing sentences went with `interfaces[].carries[]`. What crosses is a walk step now,
    and step phrases already walk through this checker one block above."""
    from coyomap.model import Interface, ProjectModel
    m = ProjectModel(title="D", goal="g")
    m.interfaces = [Interface(id="I1", name="The gateway", what="The one address clients use.",
                              side="ours", facing="user")]
    vals = list(_walked(m).values())
    assert "The one address clients use." in vals, vals


def test_the_long_sentence_gate_now_sees_a_step_phrase():
    """The gate reads the same walk, so widening the walk widens the gate. That is the point."""
    from coyomap.model import Flow, FlowStep, ProjectModel
    from coyomap.validate_model import validate_model
    long_phrase = ("writes the answer back to the caller " + "and then " * 8 + "stops")
    m = ProjectModel(title="D", goal="g")
    m.flows = [Flow(uc="UC1", title="Sign in", steps=[
        FlowStep(n=1, src="R1", dst="C1", phrase=long_phrase)])]
    warnings = validate_model(m)[1]
    assert any("long sentence" in w for w in warnings), warnings


# --- the five fields the 2026-09-11 schema sweep found ----------------------------------------
# A sweep of the schema against the walk turned up seven string fields it never yielded. Five are
# drawn by the viewer as text a reader meets and are walked now; two are not drawn and are not. On
# the three live maps the seven held 355 non-empty fields with 65 long sentences, 8 em dashes and
# 5 code names, and the walk had never seen one of them.

def test_a_stake_is_reader_facing():
    """The Features page labels each actor→feature arrow with it."""
    m = ProjectModel(title="D", goal="g")
    m.capabilities = [Group(id="CAP1", name="Ordering", purpose="p",
                            stakes=[Stake(actor="R1", stake="picks a basket and pays for it")])]
    assert _walked(m)["CAP1 stake for R1"] == "picks a basket and pays for it"


def test_the_tests_note_and_a_test_rows_gap_are_reader_facing():
    """The note leads the Tests tab; the gap is its 'Gap / risk' column. A row is named by its
    targets through the shared truncation helper, so a wide row cannot flood the report."""
    m = ProjectModel(title="D", goal="g")
    m.tests_note = "The suites were read, not run."
    m.tests = [GapRow(targets=["C1", "C2"], gap="Nothing checks a refused card."),
               GapRow(targets=["C3", "C4", "C5", "C6"], gap="Nothing checks a lost parcel."),
               # two rows on one component, told apart by their labels (four such on a live map)
               GapRow(targets=["C7"], label="Browse", gap="Nothing opens an empty folder."),
               GapRow(targets=["C7"], label="Serve", gap="Nothing serves a missing map."),
               GapRow(targets=[], gap="A row with no target.")]
    walked = _walked(m)
    assert walked["tests note"] == "The suites were read, not run."
    assert walked["tests row C1, C2 gap"] == "Nothing checks a refused card."
    wide_row = [w for w in walked if w.startswith("tests row C3")]
    assert wide_row == ["tests row C3, C4, C5, +1 more gap"], wide_row
    assert walked["tests row C7 'Browse' gap"] == "Nothing opens an empty folder."
    assert walked["tests row C7 'Serve' gap"] == "Nothing serves a missing map."
    assert walked["tests row no target gap"] == "A row with no target."


def test_an_entity_store_note_is_reader_facing_and_an_unstored_entity_has_none():
    """The note is the sentence beside a record's storage, on the Storage tab and in its info pane."""
    m = ProjectModel(title="D", goal="g")
    m.entities = [Entity(id="E1", name="Session", meaning="m",
                         store=Store(dep="D1", container="sessions", notes="Expires after a day.")),
                  Entity(id="E2", name="Quote", meaning="m")]
    walked = _walked(m)
    assert walked["E1 store notes"] == "Expires after a day."
    assert "E2 store notes" not in walked


def test_a_recorded_section_is_walked_one_line_at_a_time_and_only_its_why():
    """A recorded line is `<key>: <why>`, and the key is grammar: a Sweep-debt key is a file path by
    design, and the `complete —` of an Entry-point coverage line is the template's own separator.
    Scanning whole bodies flagged both on every live map."""
    m = ProjectModel(title="D", goal="g")
    m.extras = [
        ExtraSection(heading="Sweep debt",
                     body="- tools/x.py:12: Hands the answer back. Plumbing, not a decision.\n"
                          "- tools/y.py:40: Loads a screen."),
        ExtraSection(heading="Entry-point coverage",
                     body="cli: complete — walked every command.\n"
                          "http-route: partial - the eight routes that decide."),
    ]
    walked = _walked(m)
    assert walked["record 'Sweep debt' line 1"] == "Hands the answer back. Plumbing, not a decision."
    assert walked["record 'Sweep debt' line 2"] == "Loads a screen."
    assert walked["note 'Entry-point coverage' line 1"] == "walked every command."
    assert walked["note 'Entry-point coverage' line 2"] == "the eight routes that decide."
    assert prose.scan(prose.iter_prose_fields(m)) == []   # no file path and no em dash was written


def test_a_freeform_note_under_an_unknown_heading_is_walked_one_block_at_a_time():
    """A heading the registry does not know is a note somebody wrote by hand. A paragraph wrapped
    over three lines is ONE field, read as sentences: line by line, the second line would open with
    a bare "It". A list is one field per item: as one field, ten items with no full stops read as a
    single 150-word sentence, the artifact the review found this path would bring back."""
    m = ProjectModel(title="D", goal="g")
    wrapped = "The job starts at three.\nIt reads every order\nand writes one file."
    items = "\n".join(f"- item {n} " + " ".join(["word"] * 14) for n in range(1, 11))
    m.extras = [ExtraSection(heading="How the nightly job runs", body=f"{wrapped}\n\n{items}")]
    walked = _walked(m)
    assert walked["note 'How the nightly job runs' block 1"] == wrapped
    assert walked["note 'How the nightly job runs' block 11"].startswith("item 10 word")
    assert len([w for w in walked if w.startswith("note '")]) == 11
    assert prose.scan(prose.iter_prose_fields(m)) == []
    assert prose._note_blocks("1. first\n   still first\n2) second\n\nthird") == [
        "first\nstill first", "second", "third"]


def test_the_two_dependency_fields_the_viewer_never_draws_are_not_walked():
    """`alternative` and `not_an_interface` are strings a person could read, and the sweep asked. The
    viewer's dependency card draws neither: `alternative` reaches only the committed markdown's
    dependency table, and `not_an_interface` is read by `validate` alone. Reader-facing means drawn,
    so they stay out — and this test is where that decision is written down."""
    m = ProjectModel(title="D", goal="g")
    m.deps = [Dep(id="D1", name="Postgres", kind="datastore", used_for="Stores every order.",
                  alternative="A file on disk, when Postgres is down.",
                  not_an_interface="Only the product reads what it writes here.")]
    assert [where for where in _walked(m) if where.startswith("D1")] == ["D1 used for"]


def test_the_long_sentence_gate_now_sees_a_recorded_line_and_not_its_key():
    """The gate reads the same walk. A long why under 'Sweep debt' is a finding; its path key is not
    a code name, and a coverage line's template dash is not an em dash."""
    from coyomap.validate_model import validate_model
    m = ProjectModel(title="D", goal="g")
    long_why = "hands the answer back to the caller " + "and then " * 8 + "stops"
    m.extras = [ExtraSection(heading="Sweep debt", body=f"- tools/x.py:12: {long_why}"),
                ExtraSection(heading="Entry-point coverage", body="cli: complete — walked every command.")]
    warnings = validate_model(m)[1]
    assert any("long sentence" in w and "record 'Sweep debt' line 1" in w for w in warnings), warnings
    assert not any("code name" in w or "em dash" in w for w in warnings), warnings


# --- the goal's shape ---------------------------------------------------------------------------

def make_paragraph(sentences: int, words: int = 8) -> str:
    return " ".join(make_sentence(words) for _ in range(sentences))


def make_goal(paragraphs: int, sentences: int = 2, words: int = 8) -> str:
    return "\n\n".join(make_paragraph(sentences, words) for _ in range(paragraphs))


def test_a_goal_inside_the_rule_has_no_shape_finding() -> None:
    for n in range(prose.GOAL_PARAGRAPHS[0], prose.GOAL_PARAGRAPHS[1] + 1):
        assert prose.goal_shape_findings(make_goal(n, sentences=prose.GOAL_PARAGRAPH_SENTENCES)) == []


def test_a_single_paragraph_is_one_finding_that_counts_its_sentences() -> None:
    found = prose.goal_shape_findings(make_paragraph(8))
    assert [f.kind for f in found] == ["goal shape"]
    assert found[0].where == "goal"
    assert found[0].detail == "one paragraph of 8 sentences; the rule is 2 to 4 paragraphs"


def test_too_many_paragraphs_and_a_long_paragraph_are_each_named_with_their_number() -> None:
    goal = make_goal(5) + "\n\n" + make_paragraph(4)
    details = [f.detail for f in prose.goal_shape_findings(goal)]
    assert details == ["6 paragraphs; the rule is 2 to 4", "paragraph 6 has 4 sentences; the rule is 1 to 3"]


def test_the_word_total_counts_every_paragraph_and_under_means_under() -> None:
    at_limit = make_goal(3, sentences=3, words=20)                  # 180 words in all
    assert [f.detail for f in prose.goal_shape_findings(at_limit)] == ["180 words in all; the rule is under 180"]
    under = at_limit.replace("word word.", "word.", 1)              # 179
    assert prose.goal_shape_findings(under) == []


def test_a_single_newline_is_a_wrap_not_a_paragraph_and_blank_lines_may_carry_spaces() -> None:
    assert prose.paragraphs("one line.\nstill the same paragraph.") == ["one line.\nstill the same paragraph."]
    assert prose.paragraphs("first.\n  \nsecond.") == ["first.", "second."]


def test_a_windows_line_ending_still_makes_a_paragraph() -> None:
    """A goal saved with CRLF used to count as one block: a false shape warning, and one run on screen."""
    assert prose.paragraphs("a.\r\n\r\nb.") == ["a.", "b."]
    assert prose.paragraphs("a.\n\r\nb.") == ["a.", "b."]


def test_a_single_paragraph_over_the_word_cap_gets_both_findings() -> None:
    """The early return after the one-block finding used to skip the word cap, so a 201-word block
    was reported as a block only and its length surfaced one run later."""
    details = [f.detail for f in prose.goal_shape_findings(make_paragraph(10, words=20))]
    assert details == ["one paragraph of 10 sentences; the rule is 2 to 4 paragraphs",
                       "200 words in all; the rule is under 180"]


def test_an_empty_goal_has_no_shape_the_completeness_checks_own_that() -> None:
    assert prose.goal_shape_findings("") == []


def test_the_advisory_lines_carry_the_shape_and_the_sentence_findings_together() -> None:
    m = make_model()
    m.goal = make_sentence(30)   # one paragraph, one long sentence
    lines = prose.advisory_lines(m)
    assert any(line.startswith("1 prose field with a long sentence") for line in lines)
    shape = [line for line in lines if "goal shape" in line]
    assert len(shape) == 1 and shape[0].startswith("1 prose field with a goal shape")
    assert "two to four short paragraphs" in shape[0]


def test_the_method_states_the_shape_the_tool_counts() -> None:
    """The rule lives in prose and the count lives in code; this is the line that keeps them equal."""
    text = (Path(__file__).resolve().parent.parent / "method.md").read_text(encoding="utf-8")
    at = text.index("**T0 Goal**")
    rule = " ".join(text[at:at + 900].split())   # one line, so a re-wrap of the rule is not a failure
    assert "two to four short paragraphs" in rule and prose.GOAL_PARAGRAPHS == (2, 4)
    assert "one to three sentences each" in rule and prose.GOAL_PARAGRAPH_SENTENCES == 3
    assert f"under {prose.GOAL_WORD_LIMIT} words in all" in rule


# --- the map is a snapshot: the words an update writes into it tell no history -------------------

def test_a_sentence_written_into_the_map_that_narrates_its_change_is_one_finding_naming_the_words() -> None:
    text = ("Only the screens hold this back, so a direct call still gets through. Since the last-admin "
            "rule, such a call can no longer leave the team without an admin.")
    found = prose.history_findings("entry e1 BR168 risk", text)
    assert [(f.kind, f.where) for f in found] == [("history word", "entry e1 BR168 risk")]
    assert found[0].detail.startswith("says Since the, no longer: ")
    assert prose.history_words("Before, a refused click looked as if it had worked. Now it shows the reason.") == ["Before,", "Now"]
    assert "history word" in prose._REMEDY and "snapshot" in prose._REMEDY["history word"]


def test_the_product_s_own_present_is_not_history() -> None:
    for text in ("An admin asks which MCP servers are connected right now.",
                 "The `now` flag is a quoted literal.",
                 "Nowhere in the settings; the page knows nothing of it.",
                 "An admin removes a member from the team."):
        assert prose.history_words(text) == [], text


# --- the goal describes, it does not sell -----------------------------------------------------

def test_a_marketing_word_in_the_goal_is_one_finding_naming_the_words() -> None:
    goal = "Alpha simply works.\n\nA seamless, powerful map. Its `simply` flag is a quoted literal."
    found = prose.goal_pitch_findings(goal)
    assert [(f.kind, f.where) for f in found] == [("pitch word", "goal")]
    assert found[0].detail == "says simply, seamless, powerful"


def test_a_plain_description_and_the_need_behind_it_are_not_a_pitch() -> None:
    goal = ("A coding agent can write more code than anyone follows. The code runs fine until the day "
            "somebody needs to understand it.\n\ncoyomap reads the project and writes a map.")
    assert prose.goal_pitch_findings(goal) == []
    assert prose.pitch_words("simplicity and uniqueness are not the words") == []   # whole words only


def test_the_pitch_finding_rides_the_advisory_lines_with_its_remedy() -> None:
    m = make_model()
    m.goal = "A robust demo.\n\nIt works."
    lines = [line for line in prose.advisory_lines(m) if "pitch word" in line]
    assert len(lines) == 1 and "describes, it does not sell" in lines[0]


def test_a_pitch_word_is_reported_as_written() -> None:
    assert prose.goal_pitch_findings("Seamless setup.\n\nIt works.")[0].detail == "says Seamless"


def test_words_with_a_plain_literal_use_are_not_pitch_words() -> None:
    plain = ("The leading zero is dropped. Each person gets a unique link. A trusted device unlocks the "
             "door. A blazing fire spreads.")
    assert prose.pitch_words(plain) == []


# --- the goal speaks in the third person ------------------------------------------------------

def test_a_second_person_goal_is_one_finding_naming_the_words() -> None:
    found = prose.goal_person_findings("You open the map.\n\nYour agent builds it, and we check it.")
    assert [(f.kind, f.where, f.detail) for f in found] == [("second person", "goal", "says You, Your, we")]


def test_a_third_person_goal_has_no_person_finding_and_us_is_left_alone() -> None:
    assert prose.goal_person_findings("A developer opens the map.\n\nThe US market is not named.") == []
    assert prose.goal_person_findings("") == []


def test_the_person_finding_rides_the_advisory_lines_with_its_remedy() -> None:
    m = make_model()
    m.goal = "You get a demo.\n\nIt works."
    lines = [line for line in prose.advisory_lines(m) if "second person" in line]
    assert len(lines) == 1 and "naming the people by role" in lines[0]
