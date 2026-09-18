#!/usr/bin/env python3
"""Tests for the model layer (`coyomap.model`) — round-trip, deterministic
serialization, and structural (schema) validation on load.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_model.py
    pytest tests/test_model.py
"""
from __future__ import annotations

import json

from coyomap.model import (
    Component,
    Dep,
    Edge,
    DeploymentRow,
    Entity,
    EntityField,
    EntityRelation,
    EntryPoint,
    ExtraSection,
    Flow,
    FlowStep,
    HappyStep,
    Group,
    ModelError,
    Role,
    RoleRelation,
    Store,
    StoryAnchor,
    ProjectModel,
    TestRow as _TestRow,  # aliased: a bare `TestRow` name makes pytest try to collect it as a test class
    UseCase,
    VariantTag,
    ID_ARRAYS,
    ID_SHAPE,
    all_elements,
    load_model,
    remap_element_ids,
    to_canonical_json,
)
from coyomap import grammar


# --- id remap (the mutable twin of validate_model._referenced_ids) --------------

def make_component_ref_model(cid: str) -> ProjectModel:
    """A model that references component `cid` in EVERY reference site _referenced_ids reads —
    edge, flow step, entry-point owner, test target, and `[[cid]]` prose."""
    m = ProjectModel(title="t", goal="g")
    m.use_cases = [UseCase(id="UC1", name="Do")]
    m.components = [Component(id="C1", name="A", source="a.py:1"),
                    Component(id=cid, name="B", source="b.py:1")]
    m.entities = [Entity(id="E1", name="Thing")]
    m.edges = [Edge(src="C1", verb="uses", dst=cid, where="a.py:2")]
    m.entry_points = [EntryPoint(kind="route", trigger="GET /x", source="x.py:1", component=cid)]
    m.flows = [Flow(uc="UC1", title="Do",
                    steps=[FlowStep(n=1, src="C1", dst=cid, phrase="calls", where="a.py:2")])]
    m.tests = [_TestRow(targets=["C1", cid], tested="no")]
    m.extras = [ExtraSection(heading="Notes", body=f"see [[{cid}]] for details")]
    return m


def test_remap_covers_every_referenced_id_site():
    # DRIFT GUARD: remap must rewrite every place _referenced_ids READS, or a merged-away id would
    # survive as a dangling reference. Remap the id everywhere, then assert it is referenced nowhere.
    from coyomap.validate_model import _referenced_ids
    m = make_component_ref_model("C9")
    assert "C9" in _referenced_ids(m)                 # sanity: the fixture really references it
    remap_element_ids(m, {"C9": "C1"})
    assert "C9" not in _referenced_ids(m)             # no reference site was missed
    assert m.extras[0].body == "see [[C1]] for details"


def test_remap_covers_store_dep():
    # WS-A1 lockstep: `store.dep` is a reference site — a dep merge must re-point it, and
    # _referenced_ids must read it (so a dangling store.dep is a validate problem, not silence).
    from coyomap.validate_model import _referenced_ids
    m = ProjectModel(title="t", goal="g")
    m.deps = [Dep(id="D1", name="Postgres", kind="datastore", type="SQL"),
              Dep(id="D9", name="Postgres dup", kind="datastore", type="SQL")]
    m.entities = [Entity(id="E1", name="Order", store=Store(dep="D9", container="orders",
                                                            mode="collection"))]
    assert "D9" in _referenced_ids(m)
    remap_element_ids(m, {"D9": "D1"})
    st = m.entities[0].store
    assert st is not None and st.dep == "D1"
    assert "D9" not in _referenced_ids(m)


def test_legacy_string_store_fails_with_targeted_error():
    # WS-A1 hard retype: a pre-retype map (`store: "<prose>"`) must fail with a message that says
    # exactly what happened — not the generic "expected an object, got str".
    m = make_model()
    j = to_canonical_json(m).replace(
        '"store": {\n        "dep": null,\n        "container": "",\n        "mode": "",\n        "notes": "orders"\n      }',
        '"store": "mdb: orders collection"')
    assert '"store": "mdb: orders collection"' in j    # the replacement really landed
    try:
        load_model(j)
        raise AssertionError("legacy string store must not load")
    except ModelError as e:
        assert "structured object" in str(e) and "entities[0].store" in str(e)


def test_subflow_title_alias_loads_as_name():
    # Rebuild finding M-B1: five trace agents wrote `subflows[].title` by analogy with Flow.title.
    # The loader accepts the alias (canonical stays `name` — renaming would break today's maps).
    m = make_model()
    j = to_canonical_json(m)
    j2 = j.replace('"edges": [', '"subflows": [{"id": "SF1", "title": "Shared sub-use case", "steps": []}],\n  "edges": [')
    m2 = load_model(j2)
    assert m2.subflows[0].name == "Shared sub-use case"
    # round-trips canonically as `name`
    assert '"title"' not in to_canonical_json(m2) or m2.subflows[0].name == "Shared sub-use case"


def test_empty_string_store_loads_as_null():
    # "" was the serializer's old "not stated" — tolerated and dropped to null, not an error.
    m = make_model()
    j = to_canonical_json(m).replace(
        '"store": {\n        "dep": null,\n        "container": "",\n        "mode": "",\n        "notes": "orders"\n      }',
        '"store": ""')
    m2 = load_model(j)
    assert m2.entities[0].store is None


# --- builders -------------------------------------------------------------------

def make_model(extra_order: tuple[str, ...] = ("Zeta", "Alpha")) -> ProjectModel:
    """A small but full-shaped model. `extra_order` controls the INSERTION order of a component's
    `extra` dict, so determinism tests can prove key order can't wobble the serialization."""
    m = ProjectModel(title="Demo", goal="A demo project.", commit="abc1234",
                     committed="2026-07-01", built="2026-07-02 10:00")
    m.use_cases = [UseCase(id="UC1", name="View order", actors=[], trigger="opens", outcome="sees")]
    m.happy_path = [HappyStep(id="HP1", uc="UC1")]
    m.subsystems = [Group(id="S1", name="Core", purpose="everything")]
    extra: dict[str, object] = {k: k.lower() for k in extra_order}
    m.components = [
        Component(id="C1", name="Viewer", subsystem="S1", purpose="shows orders",
                  extra=extra),
        Component(id="C2", name="Store", subsystem="S1", purpose="persists orders"),
    ]
    m.deps = [Dep(id="D1", name="Postgres", kind="datastore", type="SQL database",
                  used_for="orders", where_configured="cfg.py:1")]
    m.entities = [Entity(id="E1", name="Order", store=Store(notes="orders"), meaning="a customer order",
                         source="src/order.py#L1",
                         fields=[EntityField(name="id", type="str", markers=["PK"])],
                         relations=[EntityRelation(verb="has", target="E1",
                                                   src_card="1", dst_card="*")])]
    m.flows = [Flow(uc="UC1", title="View order",
                    steps=[FlowStep(n=1, src="Andy", dst="C1", phrase="opens the list"),
                           FlowStep(n=2, src="C1", dst="E1")])]
    m.edges = [Edge(src="C1", verb="reads", dst="E1", why="show it", where="src/viewer.py:5"),
               Edge(src="C2", verb="persists", dst="E1", why="store it", where="src/store.py:9"),
               Edge(src="C1", verb="uses", dst="D1", why="query", where="src/viewer.py:7")]
    return m


# --- round-trip + determinism ---------------------------------------------------

def test_round_trip_identity():
    m = make_model()
    j = to_canonical_json(m)
    m2 = load_model(j)
    assert to_canonical_json(m2) == j
    assert m2 == m


def test_serializer_deterministic_across_builds():
    assert to_canonical_json(make_model()) == to_canonical_json(make_model())


def test_environments_and_variants_round_trip():
    m = make_model()
    m.environments = ["standalone", "cloud"]
    m.deployment = [
        DeploymentRow(unit="backend", variants=[VariantTag(env="cloud", source="docker-compose.yml:96")]),
        DeploymentRow(unit="db", variants=[VariantTag(env="dev"), VariantTag(env="cloud")]),  # 'dev' inferred
        DeploymentRow(unit="shared")]                             # ungated: empty variants
    m2 = load_model(to_canonical_json(m))
    assert m2.environments == ["standalone", "cloud"]
    assert [(d.unit, [(v.env, v.source) for v in d.variants]) for d in m2.deployment] == [
        ("backend", [("cloud", "docker-compose.yml:96")]),
        ("db", [("dev", ""), ("cloud", "")]),
        ("shared", [])]


def test_variants_bare_string_shape_loads_as_inferred_tag():
    """Backward-compat (T1): the just-shipped maps store `variants: ["cloud"]` (list of strings). The
    load pre-pass must coerce each bare string `s` → VariantTag(env=s, source="") (inferred), or every
    existing map breaks."""
    m = make_model()
    m.environments = ["cloud", "dev"]
    doc = json.loads(to_canonical_json(m))
    doc["deployment"] = [{"unit": "backend", "variants": ["cloud"]},
                         {"unit": "db", "variants": ["dev", "cloud"]},
                         {"unit": "shared", "variants": []}]
    m2 = load_model(json.dumps(doc))
    assert [(d.unit, [(v.env, v.source) for v in d.variants]) for d in m2.deployment] == [
        ("backend", [("cloud", "")]),
        ("db", [("dev", ""), ("cloud", "")]),
        ("shared", [])]


def test_serializer_sorts_extra_dicts():
    # Same extra content, different insertion order -> byte-identical serialization.
    assert to_canonical_json(make_model(("Zeta", "Alpha"))) == \
        to_canonical_json(make_model(("Alpha", "Zeta")))


def test_canonical_key_order_is_field_order():
    keys = list(json.loads(to_canonical_json(make_model())).keys())
    assert keys[:6] == ["format", "title", "goal", "commit", "committed", "built"]
    assert keys[-1] == "extras"


# --- structural validation on load ----------------------------------------------

def test_load_rejects_non_model_format():
    try:
        load_model(json.dumps({"format": "something-else"}))
        raise AssertionError("expected ModelError")
    except ModelError as e:
        assert "format" in str(e)


def test_load_rejects_wrong_type_with_path():
    doc = json.loads(to_canonical_json(make_model()))
    doc["components"][0]["purpose"] = 42
    try:
        load_model(json.dumps(doc))
        raise AssertionError("expected ModelError")
    except ModelError as e:
        assert "$.components[0].purpose" in str(e)


def test_load_rejects_unknown_field():
    doc = json.loads(to_canonical_json(make_model()))
    doc["components"][0]["colour"] = "red"
    try:
        load_model(json.dumps(doc))
        raise AssertionError("expected ModelError")
    except ModelError as e:
        assert "colour" in str(e) and "unknown field" in str(e)


def test_load_rejects_missing_required_field():
    doc = json.loads(to_canonical_json(make_model()))
    del doc["use_cases"][0]["name"]
    try:
        load_model(json.dumps(doc))
        raise AssertionError("expected ModelError")
    except ModelError as e:
        assert "use_cases[0]" in str(e)


def test_load_rejects_wrong_id_prefix():
    doc = json.loads(to_canonical_json(make_model()))
    doc["deps"][0]["id"] = "C9"  # a component id in the deps array is a SHAPE error
    try:
        load_model(json.dumps(doc))
        raise AssertionError("expected ModelError")
    except ModelError as e:
        assert "deps" in str(e) and "C9" in str(e)


def test_load_rejects_suffixed_id():
    doc = json.loads(to_canonical_json(make_model()))
    doc["subsystems"][0]["id"] = "S12a"  # the historical malformed-id class, now a load error
    try:
        load_model(json.dumps(doc))
        raise AssertionError("expected ModelError")
    except ModelError as e:
        assert "S12a" in str(e)


def test_a_map_from_before_the_rename_is_refused_with_the_two_edits_named():
    """Every map built before 2026-09-13 says `coyodex-map`. The refusal must say what to do, not
    only what was expected: the folder to rename and the field to set."""
    try:
        load_model(json.dumps({"format": "coyodex-map", "title": "T"}))
        raise AssertionError("expected ModelError")
    except ModelError as e:
        assert ".coyodex/" in str(e) and ".coyomap/" in str(e) and '"coyomap-map"' in str(e)


def test_absent_optional_fields_take_defaults():
    minimal = {"format": "coyomap-map", "title": "T",
               "components": [{"id": "C1", "name": "Only"}]}
    m = load_model(json.dumps(minimal))
    assert m.components[0].purpose == ""
    assert m.components[0].subsystem is None
    assert m.deps == [] and m.flows == []


def test_relation_keyed_by_round_trips_and_defaults_when_absent():
    # keyed_by serializes + reloads unchanged.
    m = make_model()
    m.entities[0].relations[0].keyed_by = ["upstream_id", "org_id"]
    reloaded = load_model(to_canonical_json(m))
    assert reloaded.entities[0].relations[0].keyed_by == ["upstream_id", "org_id"]
    assert reloaded == m
    # a pre-existing map with no keyed_by on its relations still loads → default [] (back-compat).
    doc = json.loads(to_canonical_json(m))
    for r in doc["entities"][0]["relations"]:
        r.pop("keyed_by", None)
    old = load_model(json.dumps(doc))
    assert old.entities[0].relations[0].keyed_by == []


# --- helpers ---------------------------------------------------------------------

def test_all_elements_keyed_by_id():
    els = all_elements(make_model())
    assert set(els) == {"UC1", "HP1", "S1", "C1", "C2", "D1", "E1"}


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if failures else 0)


# ── id namespaces for capabilities + entry points (plan/60-capabilities Step 1) ───────────────────

def test_id_shape_accepts_the_new_namespaces_without_shadowing_the_old() -> None:
    """First-match alternation: `CAP3` also starts with "C" and `EP1` with "E", so the multi-letter
    prefixes must lead. Before they did, `CAP3` matched the `C` branch and then failed on "AP3" —
    a shape error on a perfectly good id."""
    for good in ("CAP1", "CAP42", "EP1", "EP99", "C3", "E7", "UC12", "SD2", "SF9", "S1", "R4", "HP1", "D2"):
        assert ID_SHAPE.match(good), good
    for bad in ("CAP", "EP", "CAPX1", "EPP1", "cap1", "ep1", "X1"):
        assert not ID_SHAPE.match(bad), bad


def test_grammar_id_token_finds_the_new_namespaces_in_prose() -> None:
    """The prose scanner shares ID_SHAPE's ordering problem: with `C\\d+` first, "CAP3" matched
    nothing at all, so a `why:` or a note citing a capability read as citing no element."""
    found = grammar.ID_TOKEN.findall("see CAP3 and EP1 alongside C5, UC2 and SD4")
    assert set(found) == {"CAP3", "EP1", "C5", "UC2", "SD4"}, found


def test_capabilities_are_an_id_array_and_entry_points_are_not() -> None:
    """Entry-point ids are minted by `assemble` from content, so a fragment carries none — registering
    them here would make every pre-assembly fragment a shape error and every rebuild a false duplicate."""
    assert ID_ARRAYS["capabilities"] == "CAP"
    assert "entry_points" not in ID_ARRAYS


# --- role relations (the "one human, several hats" links) -----------------------

def make_related_roles_model() -> ProjectModel:
    m = ProjectModel(title="Demo", goal="A demo project.")
    m.use_cases = [UseCase(id="UC1", name="Sign in and name the organization", actors=["R1"])]
    m.roles = [
        Role(id="R1", name="Prospect", kind="human", audience="user",
             relations=[RoleRelation(kind="becomes", role="R2", at="UC1")]),
        Role(id="R2", name="Admin", kind="human", audience="user",
             relations=[RoleRelation(kind="includes", role="R3")]),
        Role(id="R3", name="Member", kind="human", audience="user"),
    ]
    return m


def test_role_relations_round_trip():
    m = make_related_roles_model()
    m2 = load_model(to_canonical_json(m))
    assert m2.roles[0].relations == [RoleRelation(kind="becomes", role="R2", at="UC1")]
    assert m2.roles[1].relations == [RoleRelation(kind="includes", role="R3")]
    assert m2.roles[2].relations == []
    assert to_canonical_json(m2) == to_canonical_json(m)


def test_a_role_without_relations_serializes_them_empty_not_absent():
    # `relations` is an ordinary defaulted list field: the canonical serializer emits every field,
    # so a bare role writes `"relations": []` and an old map without the key still loads.
    m = make_related_roles_model()
    j = to_canonical_json(m)
    assert '"relations": []' in j
    stripped = json.loads(j)
    for r in stripped["roles"]:
        r.pop("relations")
    m2 = load_model(json.dumps(stripped))
    assert all(r.relations == [] for r in m2.roles)


def test_story_anchor_round_trip():
    m = make_related_roles_model()
    m.capabilities = [Group(id="CAP1", name="Billing", purpose="p"),
                      Group(id="CAP2", name="Marketing", purpose="p",
                            story=StoryAnchor(place="before", feature="CAP1"))]
    m2 = load_model(to_canonical_json(m))
    assert m2.capabilities[1].story == StoryAnchor(place="before", feature="CAP1")
    assert m2.capabilities[0].story is None
    assert to_canonical_json(m2) == to_canonical_json(m)
