#!/usr/bin/env python3
"""`coyomap.features` — the feature-led derivation: what belongs to each feature, from the stored map.

The pin that matters most is the RULE JOIN. The obvious join (through the component holding the
site) reaches 92-98% of rules on live maps and names a single feature for 10-28% of them, because a
component is shared. The join here goes through the enclosing FUNCTION: half the rules, but a single
clean answer four times out of five. These tests hold that choice in place, and hold the honesty
flags that say what did NOT join.

Run either way: `python3 tests/test_features.py` or `pytest tests/test_features.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

from typing import cast

from coyomap.features import as_bundle, build_index
from coyomap.model import FORMAT, load_model


# --- builders -------------------------------------------------------------------

def make_map(*, capability_on_uc: str | None = "CAP1", rules: list[dict] | None = None,
             files_c1: list[str] | None = None, files_c2: list[str] | None = None,
             steps: list[dict] | None = None, subflows: list[dict] | None = None,
             entry_points: list[str] | None = None) -> dict:
    """One feature, one use case, two components, one entity — the smallest map that can join."""
    return {
        "format": FORMAT, "title": "T", "goal": "G",
        "roles": [{"id": "R1", "name": "User", "kind": "human", "audience": "user",
                   "wants": "x", "drives": "UC1"},
                  {"id": "R2", "name": "Admin", "kind": "human", "audience": "user",
                   "wants": "y", "drives": "UC1"}],
        "capabilities": [{"id": "CAP1", "name": "Billing", "purpose": "takes the money",
                          "happy_path": "expected"}],
        "use_cases": [{"id": "UC1", "name": "Pay", "actors": ["R1", "R2"],
                       "capability": capability_on_uc,
                       "entry_points": entry_points if entry_points is not None else ["EP1"]}],
        "happy_path": [{"id": "HP1", "uc": "UC1"}],
        "entry_points": [{"id": "EP1", "kind": "http-route", "trigger": "POST /pay",
                          "source": "src/a.py:1", "component": "C1"},
                         {"id": "EP2", "kind": "cli", "trigger": "pay",
                          "source": "src/b.py:1", "component": "C2"}],
        "components": [
            {"id": "C1", "name": "Front", "purpose": "takes the ask", "files": files_c1 if files_c1 is not None else ["src/a.py"]},
            {"id": "C2", "name": "Back", "purpose": "answers it", "files": files_c2 if files_c2 is not None else ["src/b.py"]},
            {"id": "C3", "name": "Lonely", "purpose": "nothing reaches it",
             "files": ["src/c.py"]}],
        "entities": [{"id": "E1", "name": "Payment", "meaning": "money moved",
                      "source": "src/a.py:1"}],
        "edges": [{"src": "C1", "verb": "calls", "dst": "C2", "why": "to answer",
                   "where": "src/a.py:12"}],
        "flows": [{"uc": "UC1", "title": "Pay", "steps": steps if steps is not None else [
            {"n": 1, "src": "R1", "dst": "C1", "phrase": "asks"},
            {"n": 2, "src": "C1", "dst": "C2", "phrase": "forwards", "where": "src/a.py:12"},
            {"n": 3, "src": "C2", "dst": "E1", "phrase": "records", "where": "src/b.py:22"},
            {"n": 4, "src": "C1", "dst": "R1", "phrase": "answers"}]}],
        "subflows": subflows or [],
        "blocks": [{"id": "BLK1", "name": "Money"}],
        "rules": rules if rules is not None else [
            {"id": "BR1", "name": "Card required", "statement": "A payment needs a card.",
             "block": "BLK1", "confidence": "verified",
             "sites": [{"where": "src/a.py:14", "why": "refuses without one"}]}],
    }


#: The pre-index symbol table, as `impact_git.load_map_extents` returns it. One function spans lines
#: 10-20 of a.py, another 30-40. Step 2 (a.py:12) and rule BR1 (a.py:14) both land in the first, so
#: they join by SYMBOL; anything outside it does not.
EXTENTS = {
    "src/a.py": [(10, 20, "pay", "function"), (30, 40, "refund", "function")],
    "src/b.py": [(20, 30, "record", "function")]}


def feature(ix, fid: str = "CAP1"):
    hits = [f for f in ix.features if f.id == fid]
    assert len(hits) == 1, f"expected one feature {fid}"
    return hits[0]


def index_of(doc: dict, extents: dict | None = EXTENTS):
    return build_index(load_model(json.dumps(doc)), extents)


# --- what a feature gathers ------------------------------------------------------

def test_a_feature_gathers_the_roles_use_cases_and_ways_in_of_its_use_cases():
    f = feature(index_of(make_map()))
    assert (f.roles, f.use_cases, f.entry_points) == (["R1", "R2"], ["UC1"], ["EP1"])
    assert (f.name, f.purpose) == ("Billing", "takes the money")


def test_a_feature_carries_its_derived_audience_and_not_its_walk_expectation():
    """`audience` is derived and drawn; `happy_path` is authored and NOT drawn — it is an authoring
    decision the Coverage rule reads, and a reader of the map has no use for it, so no view carries
    it and the bundle does not ship it."""
    ix = index_of(make_map())
    assert feature(ix).audience == ["user"]
    features = as_bundle(ix)["features"]
    assert isinstance(features, list)
    bundled = features[0]
    assert bundled["audience"] == ["user"]
    assert "happyPath" not in bundled and not hasattr(feature(ix), "happy_path")


def test_a_feature_gathers_the_components_and_entities_its_flow_touches():
    f = feature(index_of(make_map()))
    assert f.components == ["C1", "C2"]      # C3 is on no flow
    assert f.entities == ["E1"]


def test_content_inside_a_sub_flow_belongs_to_the_feature_that_calls_it():
    """Sub-flows are shared machinery referenced by a step. Without expanding them a feature's real
    work is invisible exactly where several features share it."""
    doc = make_map(
        steps=[{"n": 1, "src": "R1", "dst": "C1", "phrase": "asks"},
               {"n": 2, "src": "C1", "dst": "C2", "phrase": "", "subflow": "SF1"}],
        subflows=[{"id": "SF1", "title": "store it",
                   "steps": [{"n": 1, "src": "C2", "dst": "E1", "phrase": "records",
                              "where": "src/b.py:22"}]}])
    assert feature(index_of(doc)).entities == ["E1"]


def test_a_use_case_with_no_feature_is_reported_rather_than_dropped():
    ix = index_of(make_map(capability_on_uc=None))
    assert ix.unassigned_use_cases == ["UC1"]
    assert ix.coverage.use_cases_without_feature == 1
    assert feature(ix).use_cases == []


# --- the rule join ---------------------------------------------------------------

def test_a_rule_enforced_in_the_same_function_as_a_step_joins_to_that_feature():
    ix = index_of(make_map())
    # THE JOIN, not the feature's own list. `FeatureFacts.rules` answers a different question now — the
    # rules in the decision areas SPECIFIED UNDER the feature, which is authored — and this join is what
    # still feeds the coverage line and `rule_features`.
    assert ix.rule_features == {"BR1": ["CAP1"]}
    assert ix.coverage.rules_joined == 1 and ix.coverage.rules_unjoined == 0


def test_a_rule_in_another_function_of_the_same_file_does_not_join():
    """THE choice this module exists for. `src/a.py:34` is in `refund`, and no step of this feature
    goes there. Joining it anyway is the component-level join, which on live maps reached 92-98% of
    rules and named a single feature for 10-28% of them."""
    doc = make_map(rules=[{"id": "BR1", "name": "Card required",
                           "statement": "A payment needs a card.", "block": "BLK1",
                           "sites": [{"where": "src/a.py:34", "why": "in the refund path"}]}])
    ix = index_of(doc)
    assert feature(ix).rules == []
    assert (ix.coverage.rules_joined, ix.coverage.rules_unjoined) == (0, 1)


def test_an_unjoined_rule_is_counted_so_a_feature_page_cannot_imply_it_has_them_all():
    """A page showing only the joined rules would say a feature decides two things when it decides
    three. The count is what lets it say so."""
    doc = make_map(rules=[
        {"id": "BR1", "name": "In", "statement": "A payment needs a card.", "block": "BLK1",
         "sites": [{"where": "src/a.py:14", "why": "here"}]},
        {"id": "BR2", "name": "Out", "statement": "A refund needs a reason.", "block": "BLK1",
         "sites": [{"where": "src/a.py:34", "why": "elsewhere"}]}])
    ix = index_of(doc)
    assert ix.rule_features == {"BR1": ["CAP1"]}
    assert (ix.coverage.rules_joined, ix.coverage.rules_unjoined) == (1, 1)


def test_without_the_preindex_only_an_exact_line_match_links_a_rule():
    """The degradation is `rule_steps`' own, not a second silence: with no symbol table a site links
    to a step only when they name the SAME line. On the three live maps that is the difference
    between 43 rules joined and 13, so a page that does not say which it is reports a floor as an
    answer."""
    ix = index_of(make_map(), extents=None)       # site a.py:14, step a.py:12 — same function only
    assert ix.rule_join_uses_extents is False
    assert feature(ix).rules == []
    assert ix.coverage.rules_unjoined == 1


def test_an_exact_line_match_still_links_without_the_preindex():
    doc = make_map(rules=[{"id": "BR1", "name": "Card required",
                           "statement": "A payment needs a card.", "block": "BLK1",
                           "sites": [{"where": "src/a.py:12", "why": "on the step's own line"}]}])
    ix = index_of(doc, extents=None)
    assert ix.rule_features == {"BR1": ["CAP1"]} and ix.rule_join_uses_extents is False


def test_a_map_with_no_features_cannot_join_and_reports_no_gap():
    """coyomap's own map records no capabilities. Reporting its 14 rules as unjoined would read as a
    defect rather than as the pre-feature shape the map has."""
    doc = make_map()
    doc["capabilities"] = []
    doc["use_cases"][0]["capability"] = None
    ix = index_of(doc)
    assert ix.features == []
    assert (ix.coverage.rules_joined, ix.coverage.rules_unjoined) == (0, 0)


# --- coverage --------------------------------------------------------------------

def test_coverage_names_the_components_no_feature_and_no_rule_reaches():
    c = index_of(make_map()).coverage
    assert c.components_total == 3
    assert c.components_in_a_flow == 2 and c.components_in_a_rule == 1
    assert c.components_unreached == ["C3"]


def test_every_owner_of_a_shared_file_counts_as_enforcing_the_rule():
    """`components[].files` is not disjoint: on coyomap's own map 5 files are claimed by 2-5
    components each. Crediting the first owner silently would under-count where a decision lives."""
    c = index_of(make_map(files_c1=["src/a.py"], files_c2=["src/a.py", "src/b.py"])).coverage
    assert c.components_in_a_rule == 2      # BR1's site is in a.py, which C1 and C2 both claim


def test_coverage_counts_the_ways_in_that_no_use_case_names():
    c = index_of(make_map()).coverage
    assert c.entry_points_total == 2 and c.entry_points_named == 1     # EP2 is named by nobody


# --- the inverse views -----------------------------------------------------------

def test_a_component_knows_which_features_it_serves():
    ix = index_of(make_map())
    assert ix.component_features == {"C1": ["CAP1"], "C2": ["CAP1"]}
    assert "C3" not in ix.component_features


def test_the_role_grid_counts_use_cases_per_role_per_feature():
    ix = index_of(make_map())
    assert ix.role_features == {"R1": {"CAP1": 1}, "R2": {"CAP1": 1}}


def test_ids_come_back_in_id_order_not_string_order():
    """`C9` before `C10`. A rendered list sorted as strings reads as shuffled."""
    doc = make_map()
    doc["components"] += [{"id": f"C{i}", "name": f"N{i}", "purpose": "p",
                           "files": []} for i in (9, 10)]
    doc["flows"][0]["steps"] += [
        {"n": 5, "src": "C1", "dst": "C10", "phrase": "then", "where": "src/a.py:15"},
        {"n": 6, "src": "C1", "dst": "C9", "phrase": "then", "where": "src/a.py:16"}]
    assert feature(index_of(doc)).components == ["C1", "C2", "C9", "C10"]


# --- the story (the tripartite Features diagram's data) ----------------------------

def make_story_map() -> dict:
    """Two on-path features touched out of authoring order, one excluded, one authored but never
    walked; three roles, the third driving nothing on the walk. The smallest map where every
    derived order can come out wrong."""
    doc = make_map()
    doc["roles"] += [{"id": "R3", "name": "Auditor", "kind": "human", "audience": "internal",
                      "wants": "z", "drives": "UC4"}]
    doc["capabilities"] = [
        {"id": "CAP1", "name": "Billing", "purpose": "takes the money", "happy_path": "expected"},
        {"id": "CAP2", "name": "Signup", "purpose": "opens the account", "happy_path": "expected"},
        {"id": "CAP3", "name": "Marketing", "purpose": "draws people in", "happy_path": "excluded"},
        {"id": "CAP4", "name": "Cleanup", "purpose": "sweeps up", "happy_path": "expected"}]
    doc["use_cases"] = [
        {"id": "UC1", "name": "Pay", "actors": ["R1", "R2"], "capability": "CAP1",
         "entry_points": []},
        {"id": "UC2", "name": "Sign up", "actors": ["R1"], "capability": "CAP2",
         "entry_points": []},
        {"id": "UC3", "name": "Read the ADS page", "actors": ["R1"], "capability": "CAP3",
         "entry_points": []},
        {"id": "UC4", "name": "Audit the books", "actors": ["R3"], "capability": "CAP1",
         "entry_points": []},
        {"id": "UC5", "name": "Refund", "actors": ["R2"], "capability": "CAP1",
         "entry_points": []}]
    # The walk touches Signup FIRST, then Billing twice — Billing must appear once, at its first.
    doc["happy_path"] = [{"id": "HP1", "uc": "UC2"},
                         {"id": "HP2", "uc": "UC1"},
                         {"id": "HP3", "uc": "UC5"}]
    doc["flows"] = []
    doc["rules"] = []
    return doc


def story_of(doc: dict):
    return index_of(doc).story


def test_the_spine_orders_on_path_features_by_first_touch_once_each():
    st = story_of(make_story_map())
    assert st.spine == ["CAP2", "CAP1"]        # Signup first (HP1); Billing once, at HP2 not HP3


def test_features_the_walk_never_touches_go_off_the_story():
    """`excluded` features and an `expected` one no step reaches both sit off the walk — the
    diagram draws what the walk DOES, and the unreached-but-expected gap is validate's finding."""
    assert story_of(make_story_map()).off == ["CAP3", "CAP4"]


def test_the_cast_orders_actors_by_first_driven_step_then_map_order():
    st = story_of(make_story_map())
    assert st.cast == ["R1", "R2", "R3"]       # R1 drives HP1, R2 HP2; R3 drives no step -> last


def test_edges_are_distinct_actor_feature_pairs_with_the_pairs_first_step():
    st = story_of(make_story_map())
    by = {(e.actor, e.feature): e for e in st.edges}
    assert set(by) == {("R1", "CAP1"), ("R1", "CAP2"), ("R1", "CAP3"),
                       ("R2", "CAP1"), ("R3", "CAP1")}
    assert by[("R2", "CAP1")].step == "HP2"    # UC1 at HP2, not UC5 at HP3
    assert by[("R1", "CAP3")].step is None     # the walk never exercises the pair
    assert by[("R3", "CAP1")].step is None     # UC4 is on no step


def test_a_fallback_label_is_the_pairs_first_use_case_as_a_verb_phrase():
    st = story_of(make_story_map())
    by = {(e.actor, e.feature): e for e in st.edges}
    assert by[("R1", "CAP1")].label == "pay" and by[("R1", "CAP1")].authored is False
    assert by[("R1", "CAP2")].label == "sign up"
    assert by[("R2", "CAP1")].label == "pay"   # first use case of the PAIR, in map order


def test_a_fallback_label_keeps_a_leading_acronym():
    doc = make_story_map()
    doc["use_cases"][2]["name"] = "ADS reading"
    st = story_of(doc)
    by = {(e.actor, e.feature): e for e in st.edges}
    assert by[("R1", "CAP3")].label == "ADS reading"


def test_an_authored_stake_wins_over_the_fallback():
    doc = make_story_map()
    doc["capabilities"][0]["stakes"] = [{"actor": "R2", "stake": "settles and refunds"}]
    st = story_of(doc)
    by = {(e.actor, e.feature): e for e in st.edges}
    assert by[("R2", "CAP1")].label == "settles and refunds"
    assert by[("R2", "CAP1")].authored is True
    assert by[("R1", "CAP1")].label == "pay"   # the OTHER actor still falls back


def test_a_map_with_no_walk_has_no_spine_and_everything_off():
    """The viewer draws no diagram then (its guard reads the empty spine); the classification must
    still be coherent rather than crash."""
    doc = make_story_map()
    doc["happy_path"] = []
    st = story_of(doc)
    assert st.spine == [] and st.off == ["CAP1", "CAP2", "CAP3", "CAP4"]
    assert st.cast == ["R1", "R2", "R3"]                    # map order, nobody appears first


def test_a_walk_step_naming_a_missing_use_case_is_skipped_not_fatal():
    """A dangling `uc` is validate's finding; the derivation must not crash on it or let it shift
    the orders."""
    doc = make_story_map()
    doc["happy_path"].insert(0, {"id": "HP9", "uc": "UC99"})
    st = story_of(doc)
    assert st.spine == ["CAP2", "CAP1"] and st.cast == ["R1", "R2", "R3"]


def test_the_story_ships_in_the_bundle():
    b = as_bundle(index_of(make_story_map()))
    st = b["story"]
    assert isinstance(st, dict)
    assert sorted(st) == ["cast", "column", "edges", "off", "spine"]
    assert st["spine"] == ["CAP2", "CAP1"]
    assert st["column"] == ["CAP2", "CAP1", "CAP3", "CAP4"]
    e = next(x for x in st["edges"] if (x["actor"], x["feature"]) == ("R2", "CAP1"))
    assert (e["label"], e["authored"], e["step"]) == ("pay", False, "HP2")


# --- the one story column: the walk unbroken, then the off-walk features in a trailing block ------

def test_the_column_is_the_spine_with_off_features_at_the_derived_fallback():
    """No anchors authored: Marketing's only actor (R1) last drives HP2, whose feature is Billing,
    so Marketing reads after Billing; Cleanup has no use cases, so no actors, so it falls to the
    end. The spine's own order never moves."""
    st = story_of(make_story_map())
    assert st.column == ["CAP2", "CAP1", "CAP3", "CAP4"]


def test_an_authored_before_anchor_beats_the_fallback():
    """The lead-in case the anchor exists for: a marketing feature belongs BEFORE the first step,
    and the fallback (the actor's last step) puts it after."""
    doc = make_story_map()
    doc["capabilities"][2]["story"] = {"place": "before", "feature": "CAP2"}
    assert story_of(doc).column == ["CAP3", "CAP2", "CAP1", "CAP4"]


def test_an_after_anchor_on_a_walk_feature_orders_the_trailing_block_and_never_breaks_the_walk():
    """`after CAP2` is honoured by the trailing block itself: everything there is after CAP2. So
    Cleanup does NOT interrupt the walk to sit beside it; it only sorts ahead of Marketing, whose
    fallback (after Billing) puts it later."""
    doc = make_story_map()
    doc["capabilities"][3]["story"] = {"place": "after", "feature": "CAP2"}
    assert story_of(doc).column == ["CAP2", "CAP1", "CAP4", "CAP3"]


def test_every_off_feature_trails_the_whole_walk_even_when_anchored_mid_walk():
    """The rule that changed: two off features anchored after two DIFFERENT walk features used to
    interleave at each anchor. Both now sit after the last walk feature, and the anchors survive as
    the order INSIDE that block — Cleanup (after Signup) ahead of Marketing (after Billing)."""
    doc = make_story_map()
    doc["capabilities"][2]["story"] = {"place": "after", "feature": "CAP1"}
    doc["capabilities"][3]["story"] = {"place": "after", "feature": "CAP2"}
    assert story_of(doc).column == ["CAP2", "CAP1", "CAP4", "CAP3"]


def test_before_a_mid_walk_feature_splits_the_walk_and_lands_exactly_above_it():
    """The reason `pinned()` exists, and the case the trailing block cannot serve: `before Billing`
    can only be honoured by sitting between Signup and Billing. Asserting the WHOLE column, not
    just "somewhere earlier": a rule that pinned only against the walk's FIRST feature would put
    Marketing after Billing and silently break the anchor."""
    doc = make_story_map()
    doc["capabilities"][2]["story"] = {"place": "before", "feature": "CAP1"}
    assert story_of(doc).column == ["CAP2", "CAP3", "CAP1", "CAP4"]


def test_before_an_unpinned_off_feature_does_not_drag_it_into_the_walk():
    """`before` pins only when the chain REACHES the walk. Anchored before an off feature that is
    itself trailing, this feature is honoured inside the trailing block and must not climb into the
    walk with it. Needs a third walk feature, so that the target's own fallback lands mid-walk and
    a wrong rule would be visible."""
    doc = make_story_map()
    doc["capabilities"].append({"id": "CAP5", "name": "Support", "purpose": "helps out",
                                "happy_path": "expected"})
    doc["use_cases"].append({"id": "UC6", "name": "Ask for help", "actors": ["R2"],
                             "capability": "CAP5", "entry_points": []})
    doc["happy_path"].append({"id": "HP4", "uc": "UC6"})
    doc["capabilities"][3]["story"] = {"place": "before", "feature": "CAP3"}
    col = story_of(doc).column
    assert col == ["CAP2", "CAP1", "CAP5", "CAP4", "CAP3"]
    assert col.index("CAP5") < col.index("CAP4"), "the walk stays unbroken"


def test_an_anchor_may_name_another_off_feature_and_a_cycle_falls_back():
    doc = make_story_map()
    # CAP4 hangs off CAP3, which hangs off the spine: both resolve, in chain order.
    doc["capabilities"][2]["story"] = {"place": "before", "feature": "CAP2"}
    doc["capabilities"][3]["story"] = {"place": "after", "feature": "CAP3"}
    assert story_of(doc).column == ["CAP3", "CAP4", "CAP2", "CAP1"]
    # A cycle cannot fully resolve, and it never recurses: the member reached first with the cycle
    # closed behind it (Cleanup, whose anchor IS the cycle) takes its non-anchor placement (the
    # end), and the other's anchor then holds against that — "Marketing after Cleanup" survives.
    doc["capabilities"][2]["story"] = {"place": "after", "feature": "CAP4"}
    assert story_of(doc).column == ["CAP2", "CAP1", "CAP4", "CAP3"]


def test_a_dangling_or_self_anchor_is_ignored_by_the_derivation():
    """Resolution must not crash on what validate flags; the feature simply keeps its fallback."""
    doc = make_story_map()
    doc["capabilities"][2]["story"] = {"place": "after", "feature": "CAP99"}
    doc["capabilities"][3]["story"] = {"place": "before", "feature": "CAP4"}
    assert story_of(doc).column == ["CAP2", "CAP1", "CAP3", "CAP4"]


def test_two_features_anchored_to_the_same_spot_keep_map_order():
    doc = make_story_map()
    doc["capabilities"][2]["story"] = {"place": "after", "feature": "CAP1"}
    doc["capabilities"][3]["story"] = {"place": "after", "feature": "CAP1"}
    assert story_of(doc).column == ["CAP2", "CAP1", "CAP3", "CAP4"]


def test_a_map_with_no_walk_columns_in_map_order():
    doc = make_story_map()
    doc["happy_path"] = []
    assert story_of(doc).column == ["CAP1", "CAP2", "CAP3", "CAP4"]


# --- the view bundle ---------------------------------------------------------------

def test_the_view_bundle_carries_the_feature_block_in_the_viewers_vocabulary():
    """The frontend reads `applyBundle` keys, so a rename here is a silent blank screen there. This
    pins the shape, and that the whole bundle still serialises.

    EXACT EQUALITY, so a key cannot be renamed or dropped unnoticed; growing the list is the
    deliberate act of adding one. `ownerRecords` is such an addition — the Features page needs the
    author's recorded reason for an ownership claim no step reaches, and it is parsed server-side
    through `records` (the one reader of the `<key>: <why>` line shape) rather than a second time in
    the browser. It rides ALONGSIDE `as_bundle`'s output rather than inside it: that function is the
    feature-led derivation of the map, and a recorded exception is the author's note about the map's
    own build record. `{}` on a map that records nothing, which is most maps."""
    from coyomap.viewer.gen_viewer import build_view_bundle
    from coyomap.views import model_to_graph
    m = load_model(json.dumps(make_map()))
    b = build_view_bundle(model_to_graph(m, EXTENTS), Path("."), model=m, extents=EXTENTS)
    f = b["features"]
    assert sorted(f) == ["areas", "areasAreRecords", "componentFeatures", "coverage",
                         "entityOwners", "features", "interfaces", "ownerRecords", "roleFeatures",
                         "ruleFeatures", "ruleJoinUsesExtents", "story", "unassignedUseCases",
                         "useCaseInterfaces"]
    assert f["ownerRecords"] == {}, "a map recording nothing ships an empty answer, never no key"
    assert f["features"][0]["useCases"] == ["UC1"]        # camelCase, not use_cases
    assert f["coverage"]["componentsUnreached"] == ["C3"]
    json.dumps(b)                                          # the bundle is served as JSON


def test_a_map_with_no_subdomain_draws_its_saved_records_as_the_data_column():
    """The data column keyed every box on a sub-domain, so a map that cut none drew nothing at all —
    while the same bundle listed, one click away, the records each feature reaches. Sub-domains are
    optional below roughly fifteen records, so the method's own advice produced the empty column.

    The fallback is one box per SAVED record, counted by the same walk over the same steps. `owners`
    stays empty because ownership is authored on a sub-domain and there is none, so every arrow is a
    touch and none is an owner. `validate` reads `build_areas` and never this, so its
    cross-examination of authored ownership is untouched."""
    doc = make_map()
    doc["subdomains"] = []
    for e in doc["entities"]:
        e["subdomain"] = None
        e["store"] = {"dep": None, "container": "orders", "mode": "collection", "notes": ""}
    b = as_bundle(build_index(load_model(json.dumps(doc))))
    assert b["areasAreRecords"] is True
    assert [a["id"] for a in b["areas"]] == [e["id"] for e in doc["entities"]
                                             if (e.get("store") or {}).get("mode")
                                             in ("collection", "embedded")]
    assert all(a["owners"] == [] for a in b["areas"]), "no sub-domain means no authored owner"


def test_a_map_with_a_subdomain_is_untouched_by_the_record_fallback():
    """The fallback fires ONLY where there is no group to draw. A map that cut sub-domains keeps
    exactly the areas it had, so the three live maps this shipped against do not move."""
    doc = make_map()
    doc["subdomains"] = [{"id": "SD1", "name": "Orders", "purpose": "what the shop keeps"}]
    doc["entities"][0]["subdomain"] = "SD1"
    doc["entities"][0]["store"] = {"dep": None, "container": "orders", "mode": "collection",
                                   "notes": ""}
    b = as_bundle(build_index(load_model(json.dumps(doc))))
    assert b["areasAreRecords"] is False
    assert [a["id"] for a in b["areas"]] == ["SD1"]


def test_a_map_with_neither_a_subdomain_nor_a_saved_record_claims_no_mode():
    """Nothing to draw either way. The flag must not claim records mode over an empty column, or the
    viewer is told a box is a record on a column that holds none."""
    doc = make_map()
    doc["subdomains"] = []
    for e in doc["entities"]:
        e["subdomain"] = None
        e["store"] = None
    b = as_bundle(build_index(load_model(json.dumps(doc))))
    assert b["areas"] == []
    assert b["areasAreRecords"] is False


def make_owner_record_map(body: str) -> dict:
    """The small map, plus one `Data owner exceptions` section holding `body`."""
    doc = make_map()
    doc["extras"] = [{"heading": "Data owner exceptions", "body": body}]
    return doc


def test_the_bundle_carries_the_recorded_owner_reason_for_every_key_on_the_line():
    """A MULTI-KEY line is the form the live maps actually use: all 12 recorded reasons that reach a
    box on the three maps that record anything ride one, because the record format exists so an
    author writes a shared reason ONCE instead of seventeen times. A reader that took only the first
    key would blank the reason on 9 of those 12 boxes.

    This is also the test that can fail on an always-empty answer: asserting `{}` on a map that
    records nothing cannot, and that was the whole of the coverage."""
    from coyomap.viewer.gen_viewer import owner_records
    m = load_model(json.dumps(make_owner_record_map(
        "SD1, SD2, SD3: the rows are written by a loop no use case narrates")))
    got = owner_records(m)
    assert got == {"SD1": "the rows are written by a loop no use case narrates",
                   "SD2": "the rows are written by a loop no use case narrates",
                   "SD3": "the rows are written by a loop no use case narrates"}, got


def test_the_recorded_reason_is_read_whole_and_a_malformed_line_records_nothing():
    """The why is the WHOLE sentence after the keys, colons and all — a cut reason is the one thing
    the page cannot recover, because it holds the only complete copy in the product. And a line whose
    key list does not parse records NOTHING rather than the part it could read: a partly-read record
    is the dangerous direction, since the author believes the gap is answered."""
    from coyomap.viewer.gen_viewer import owner_records
    whole = "written deep inside the start path: the walk narrates the start, not the write"
    m = load_model(json.dumps(make_owner_record_map(f"SD4: {whole}")))
    assert owner_records(m) == {"SD4": whole}
    # A key the family does not own, and a bare sentence, both record nothing.
    for body in ("CAP1: this heading has no say over a feature", "no key at all here"):
        assert owner_records(load_model(json.dumps(make_owner_record_map(body)))) == {}, body


def test_a_map_recording_nothing_ships_an_empty_answer_not_a_missing_key():
    """The page reads `FEATURES.ownerRecords` and must never have to tell "no record" apart from
    "this bundle is too old to carry the field"."""
    from coyomap.viewer.gen_viewer import owner_records
    assert owner_records(load_model(json.dumps(make_map()))) == {}


def test_a_bundle_built_without_a_readable_map_still_renders_the_rest():
    """`build_view_bundle` runs per request. A map folder it cannot read must cost the feature block,
    never the whole view."""
    from coyomap.viewer.gen_viewer import build_view_bundle
    from coyomap.views import model_to_graph
    m = load_model(json.dumps(make_map()))
    b = build_view_bundle(model_to_graph(m, EXTENTS), Path("/nonexistent-map-dir"))
    assert b["features"] == {} and b["graph"]


def test_a_feature_says_which_way_its_data_moves():
    """The feature page words its data sentence from this: `in` its steps read a record, `out` they
    store into one. A FIXED "stores and reads" was measured wrong on 1 of the two live maps' 13
    features — mcpolis's Audit trail only ever reads — so the direction the map already carries on
    the step is summed here and the page reads the answer rather than the steps."""
    m = load_model(json.dumps(make_map(steps=[
        {"n": 1, "src": "C1", "dst": "E1", "phrase": "store it", "where": "a.py:1",
         "direction": "out"},
    ])))
    b = as_bundle(build_index(m, EXTENTS))
    assert b["features"][0]["dataDirections"] == ["out"]


def test_a_feature_whose_steps_touch_no_record_claims_no_direction():
    """An empty list, not a guess. The page falls back to stating what the list holds when it has
    no direction to report, which is the honest answer for a map that records none."""
    m = load_model(json.dumps(make_map(steps=[
        {"n": 1, "src": "C1", "dst": "C2", "phrase": "call it", "where": "a.py:1"},
    ])))
    b = as_bundle(build_index(m, EXTENTS))
    assert b["features"][0]["dataDirections"] == []


if __name__ == "__main__":     # pragma: no cover
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))


# ── the interface join ───────────────────────────────────────────────────────────────────────────

def make_interface_map() -> dict:
    """The join's two independent paths in one map: a surface reached through a way in a use case
    names, and a surface reached OUT to by a walk step drawn at the dependency."""
    doc = make_map()
    doc["deps"] = [{"id": "D1", "name": "Stripe", "kind": "service", "type": "payments",
                    "interfaces": ["I2"]},
                   {"id": "D2", "name": "Postgres", "kind": "datastore", "type": "SQL",
                    "not_an_interface": "the product writes these rows and reads them back"}]
    doc["edges"].append({"src": "C2", "verb": "calls", "dst": "D1", "why": "charges",
                         "where": "src/b.py:30"})
    doc["flows"][0]["steps"].append({"n": 5, "src": "C2", "dst": "D1", "phrase": "charges the card",
                                     "where": "src/b.py:30"})
    # WHAT CROSSES IS THE STEPS. `carries[]` was removed, so a surface's directions come from the
    # steps drawn at it — `I1` receives what a person types and sends the receipt back, and the
    # charge at `D1` reaches `I2` through the dep standing on it.
    # A DOOR carries no direction (a role at a surface is a human action with no product end), and
    # neither does a step at a DEP — `C2 → D1` is neither a surface nor a record. An earlier version
    # of this fixture put a direction on both, which `validate` BLOCKS, and three assertions rested
    # on that illegal shape: `build_index` never validates, so nothing here caught it. The test
    # above now runs `validate` over this very fixture so it cannot happen again.
    doc["flows"][0]["steps"] += [
        {"n": 6, "src": "R1", "dst": "I1", "phrase": "types the card details"},
        {"n": 7, "src": "I1", "dst": "C1", "phrase": "carries the details inward",
         "where": "src/a.py:1", "direction": "in"}]
    doc["interfaces"] = [
        {"id": "I1", "name": "Web app", "what": "Where a person pays.", "side": "ours",
         "facing": "user", "source": "src/a.py:1", "ways_in": ["EP1"]},
        {"id": "I2", "name": "Payments", "what": "Where the money moves.", "side": "theirs",
         "facing": "user"},
        {"id": "I3", "name": "Log store", "what": "Where the logs go.", "side": "theirs",
         "facing": "operator", "source": ""}]
    return doc


def test_a_surface_carries_the_walks_and_features_that_come_through_it():
    ix = build_index(load_model(json.dumps(make_interface_map())))
    by_id = {i.id: i for i in ix.interfaces}
    assert by_id["I1"].use_cases == ["UC1"] and by_id["I1"].features == ["CAP1"]
    assert by_id["I1"].components == ["C1"]        # the way in's owning component
    assert by_id["I2"].components == ["C2"]        # the component that calls the dependency
    assert by_id["I2"].deps == ["D1"]


def test_the_interface_fixture_is_a_map_VALIDATE_ACCEPTS():
    """`build_index` never validates, so a fixture can encode a shape the product rejects and every
    assertion resting on it passes. One did: doors carrying a direction, which `validate` blocks."""
    from coyomap.validate_model import validate_model
    problems, _ = validate_model(load_model(json.dumps(make_interface_map())))
    assert not [p for p in problems if "direction" in p], problems


def test_a_surface_s_directions_are_derived_from_the_STEPS_THAT_CARRY_THEM():
    """Never authored. `interfaces[].carries[]` said it by hand beside the walks, and a surface
    could claim to send while no story sent anything through it."""
    ix = build_index(load_model(json.dumps(make_interface_map())))
    by_id = {i.id: i for i in ix.interfaces}
    assert by_id["I1"].directions == ["in"], "one step drawn at it, and it says the product received"
    # …and a surface reached only THROUGH A DEP states no direction. That is the honest answer, not
    # a gap to paper over: the step is drawn at the dependency, which is the PIPE, so nothing says
    # which way data crossed the SURFACE. The fix is to draw the step at the surface, which is
    # exactly what the method now tells an author to do.
    assert by_id["I2"].directions == []


def test_the_flow_steps_ARE_what_crosses_and_each_carries_its_own_direction():
    """`interfaces[].carries[]` is removed and these replaced it. An earlier removal WITHOUT the
    step direction was reverted, because a step could not say which way data went."""
    doc = make_interface_map()
    doc["flows"][0]["steps"] = [
        {"n": 1, "src": "R1", "dst": "I1", "phrase": "hands over the card", "direction": "in"},
        {"n": 2, "src": "I1", "dst": "C1", "phrase": "carries it inward", "direction": "in"},
        {"n": 3, "src": "C2", "dst": "I3", "phrase": "ships a log line", "direction": "out"}]
    by_id = {i.id: i for i in build_index(load_model(json.dumps(doc))).interfaces}
    assert not hasattr(by_id["I1"], "crossings"), "the authored rows are gone for good"
    assert by_id["I1"].directions == ["in"], "…and `directions` now comes from the steps themselves"
    # grouped by story, in walk order, none dropped, each with its direction
    assert by_id["I1"].steps == [("UC1", [("hands over the card", "UC1", 1, "R1", "in"),
                                          ("carries it inward", "UC1", 2, "", "in")])], \
        by_id["I1"].steps
    assert by_id["I3"].steps == [("UC1", [("ships a log line", "UC1", 3, "", "out")])]
    assert by_id["I2"].steps == [] and by_id["I2"].directions == []


def test_the_bundle_ships_the_steps_with_their_direction():
    doc = make_interface_map()
    doc["flows"][0]["steps"] = [{"n": 1, "src": "R1", "dst": "I1",
                                 "phrase": "hands over the card", "direction": "in"}]
    b = as_bundle(build_index(load_model(json.dumps(doc))))
    i1 = next(i for i in cast(list[dict[str, object]], b["interfaces"]) if i["id"] == "I1")
    assert "crossings" not in i1, "the authored rows no longer ship"
    assert i1["steps"] == [{"uc": "UC1", "steps": [
        {"phrase": "hands over the card", "container": "UC1", "n": 1, "role": "R1",
         "direction": "in"}]}]


def test_a_surface_nothing_reaches_says_UNKNOWN_not_none():
    # Measured on Meerbot: 8 of 344 walk steps touch an outside service at all, so most `theirs`
    # surfaces are legitimately unknowable. "none" would read as a defect that is not there.
    ix = build_index(load_model(json.dumps(make_interface_map())))
    by_id = {i.id: i for i in ix.interfaces}
    assert by_id["I3"].features_unknown is True and by_id["I3"].features == []
    assert by_id["I1"].features_unknown is False


def test_a_feature_names_the_surfaces_it_enters_by_and_the_ones_it_calls_out_to():
    ix = build_index(load_model(json.dumps(make_interface_map())))
    f = ix.features[0]
    assert f.reached_through == ["I1"]
    assert f.reaches_out == ["I2"]


def test_a_feature_is_NOT_wired_to_a_service_through_a_shared_component():
    # The banned inference. C2 calls Stripe (there is a C->D edge), but this feature's walk no
    # longer steps at the dependency — so the map cannot say this feature charges a card, and must
    # not pretend it can. Otherwise one shared helper wires nearly every feature to every service:
    # there are 24/41/32/102 such edges on the four live maps.
    doc = make_interface_map()
    # Drop the DEP step by its number, not by position: the fixture now ends with a door pair, and
    # slicing the tail silently dropped one of those instead of the step under test.
    doc["flows"][0]["steps"] = [st for st in doc["flows"][0]["steps"] if st["n"] != 5]
    ix = build_index(load_model(json.dumps(doc)))
    assert ix.features[0].reaches_out == []
    assert {i.id: i.features for i in ix.interfaces}["I2"] == []


def test_the_bundle_ships_the_surfaces_and_the_feature_links():
    b = as_bundle(build_index(load_model(json.dumps(make_interface_map()))))
    ifaces = cast(list[dict[str, object]], b["interfaces"])
    feats = cast(list[dict[str, object]], b["features"])
    assert [i["id"] for i in ifaces] == ["I1", "I2", "I3"]
    assert feats[0]["reachedThrough"] == ["I1"]
    assert feats[0]["reachesOut"] == ["I2"]


def test_a_door_step_says_which_features_come_through_a_surface():
    """The strongest statement the map can make, and the only one that works on the way IN. Which
    direction it means comes from the STEP — see the sibling test for the two cases that prove
    `side` cannot decide it."""
    doc = make_interface_map()
    doc["flows"][0]["steps"] = ([{"n": 1, "src": "R1", "dst": "I1", "phrase": "opens it",
                                 "no_call_site": True},
                                {"n": 2, "src": "I1", "dst": "C1", "phrase": "asks"},
                                {"n": 3, "src": "C2", "dst": "I3", "phrase": "ships a log line"}])
    ix = build_index(load_model(json.dumps(doc)))
    by_id = {i.id: i for i in ix.interfaces}
    assert by_id["I1"].use_cases == ["UC1"] and by_id["I1"].features == ["CAP1"]
    assert by_id["I3"].use_cases == ["UC1"], "a step at a `theirs` surface reaches it too"
    assert ix.features[0].reached_through == ["I1"]      # a role and a code step INTO it
    assert ix.features[0].reaches_out == ["I3"]          # a code step OUT to it


def test_the_direction_comes_from_the_STEP_not_from_whose_surface_it_is():
    """The two cases that killed the `side`-based rule. coyomap's map files are OUR surface and the
    story goes OUT through them; Slack is SOMEONE ELSE'S and the story comes IN through it."""
    doc = make_interface_map()
    doc["interfaces"][0]["name"] = "Files we write"          # I1, ours — but written OUT to
    doc["interfaces"][1]["name"] = "Slack"                   # I2, theirs — but stories arrive FROM it
    doc["use_cases"][0]["entry_points"] = []      # only the STEPS may decide, here
    doc["flows"][0]["steps"] = [{"n": 1, "src": "I2", "dst": "C1", "phrase": "a message arrives"},
                                {"n": 2, "src": "C1", "dst": "I1", "phrase": "writes the file"}]
    ix = build_index(load_model(json.dumps(doc)))
    assert ix.features[0].reached_through == ["I2"], "their surface, entered through"
    assert ix.features[0].reaches_out == ["I1"], "our surface, written out through"
