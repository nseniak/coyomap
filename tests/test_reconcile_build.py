#!/usr/bin/env python3
"""Tests for `coyomap reconcile` — expanding path rules into an explicit reconcile.json.

The failure this command exists to prevent: a live 429-component build hand-wrote a generator
script that reported "components=0 assigned=429" — it emitted assignments for ids that were not in
the map, and nothing checked. Every test here is about that class: ids resolved against a real map,
and anything that matched nothing said out loud.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_reconcile_build.py
    pytest tests/test_reconcile_build.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from coyomap.model import (BusinessRule, Component, Dep, DeploymentRow, Entity, Group,
                           EntryPoint, Interface, ProjectModel, RuleSite, UseCase)
from coyomap.reconcile import SetDirective
from coyomap.reconcile_build import RuleError, coverage_report, expand, load_rules


def make_map() -> ProjectModel:
    m = ProjectModel(title="Demo", goal="g")
    m.subsystems = [Group(id="S1", name="Plugins"), Group(id="S2", name="Web")]
    m.subdomains = [Group(id="SD1", name="Billing")]
    m.components = [
        Component(id="C1", name="PluginA", source="app/plugins/a.py:1"),
        Component(id="C2", name="PluginB", source="app/plugins/b.py:1"),
        Component(id="C3", name="Deep", source="app/plugins/nested/deep.py:1"),
        Component(id="C4", name="Web", source="web/main.py:1"),
    ]
    m.entities = [Entity(id="E1", name="Invoice", meaning="m", source="app/plugins/models.py:3")]
    m.deps = [Dep(id="D1", name="Redis", type="broker")]
    m.deployment = [DeploymentRow(unit="api"), DeploymentRow(unit="worker")]
    return m


def write_rules(rules: list[dict], tmp: str) -> Path:
    p = Path(tmp) / "rules.json"
    p.write_text(json.dumps({"rules": rules}), encoding="utf-8")
    return p


# --------------------------------------------------------------------------------------
# rule shape
# --------------------------------------------------------------------------------------

def test_rules_must_select_and_assign_something():
    with tempfile.TemporaryDirectory() as tmp:
        for bad in ([{"subsystem": "S1"}],                 # selects nothing
                    [{"source_glob": "app/**"}]):          # assigns nothing
            try:
                load_rules(write_rules(bad, tmp))
                raise AssertionError(f"expected RuleError for {bad}")
            except RuleError:
                pass


# --------------------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------------------

def test_single_star_does_not_cross_a_directory_boundary():
    # `app/plugins/*` must NOT swallow `app/plugins/nested/deep.py` — fnmatch alone would, silently
    # over-assigning a whole subtree to one subsystem.
    doc, _ = expand(make_map(), [{"source_glob": "app/plugins/*", "subsystem": "S1"}])
    assert [s["ids"] for s in doc["set"]] == [["C1", "C2"]]


def test_double_star_is_the_recursive_form():
    doc, _ = expand(make_map(), [{"source_glob": "app/plugins/**", "subsystem": "S1"}])
    assert doc["set"][0]["ids"] == ["C1", "C2", "C3"]


def test_a_glob_silently_skips_elements_the_field_cannot_apply_to():
    # `app/plugins/**` also matches entity E1; `subsystem` is a component field, so E1 is skipped —
    # that is the rule working, not a problem worth a warning.
    doc, report = expand(make_map(), [{"source_glob": "app/plugins/**", "subsystem": "S1"}])
    assert "E1" not in doc["set"][0]["ids"]
    assert not [line for line in report if "E1" in line]


def test_naming_a_wrong_typed_id_explicitly_is_reported():
    _, report = expand(make_map(), [{"ids": ["E1"], "subsystem": "S1"}])
    assert any("E1" in line and "does not apply" in line for line in report)


# --------------------------------------------------------------------------------------
# the bug this command exists to prevent
# --------------------------------------------------------------------------------------

def test_ids_absent_from_the_map_are_reported_not_emitted():
    doc, report = expand(make_map(), [{"ids": ["C1", "C999"], "runs_in": ["api"]}])
    assert doc["set"][0]["ids"] == ["C1"]                       # C999 never reaches the file
    assert any("C999" in line for line in report)


def test_a_rule_that_matches_nothing_is_reported():
    doc, report = expand(make_map(), [{"source_glob": "nope/**", "subsystem": "S1"}])
    assert doc["set"] == []
    assert any("matched NOTHING" in line for line in report)


# --------------------------------------------------------------------------------------
# assignment semantics
# --------------------------------------------------------------------------------------

def test_later_rules_override_earlier_ones_per_field():
    doc, _ = expand(make_map(), [
        {"source_glob": "app/plugins/**", "subsystem": "S1"},
        {"ids": ["C2"], "subsystem": "S2"},                     # narrow override after a broad rule
    ])
    by_id = {eid: s["subsystem"] for s in doc["set"] for eid in s["ids"]}
    assert by_id == {"C1": "S1", "C2": "S2", "C3": "S1"}


def test_multiple_fields_on_one_rule_group_together():
    doc, _ = expand(make_map(), [{"source_glob": "app/plugins/*",
                                  "subsystem": "S1", "runs_in": ["api", "worker"]}])
    assert len(doc["set"]) == 1
    assert doc["set"][0]["subsystem"] == "S1"
    assert doc["set"][0]["runs_in"] == ["api", "worker"]


def test_output_feeds_assemble_reconcile_unchanged():
    # the emitted document must be exactly what `assemble --reconcile` already consumes.
    from coyomap.reconcile import load_reconcile
    with tempfile.TemporaryDirectory() as tmp:
        doc, _ = expand(make_map(), [{"source_glob": "app/plugins/*", "subsystem": "S1"}])
        p = Path(tmp) / "reconcile.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        load_reconcile(p.read_text(), "reconcile.json")          # raises if the shape is wrong


# --------------------------------------------------------------------------------------
# what the rules did NOT reach
# --------------------------------------------------------------------------------------

def test_coverage_report_names_the_elements_left_unassigned():
    m = make_map()
    doc, _ = expand(m, [{"source_glob": "app/plugins/*", "subsystem": "S1"}])
    lines = coverage_report(m, doc)
    assert any("C4" in line and "subsystem" in line for line in lines)   # web/ matched no rule
    assert any("E1" in line and "subdomain" in line for line in lines)
    assert any("runs_in" in line for line in lines)                      # deployment[] exists


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# --------------------------------------------------------------------------------------
# glob semantics — every case below was a REAL defect in the first hand-rolled matcher
# --------------------------------------------------------------------------------------

def test_star_outside_the_last_segment_matches():
    # was: any `*` before the final segment matched NOTHING, while blaming the user's path prefix.
    from coyomap.reconcile_build import _matches
    assert _matches("a/*/b", "a/x/b")
    assert not _matches("a/*/b", "a/b")
    assert not _matches("a/*/b", "a/x/y/b")


def test_double_star_does_not_discard_what_follows_it():
    # was: everything after `**` was dropped, so `a/**/nope` matched every path under `a/`.
    from coyomap.reconcile_build import _matches
    assert _matches("a/**/b", "a/x/y/b")
    assert _matches("a/**/b", "a/b")
    assert not _matches("a/**/nope", "a/x/y/b")


def test_leading_double_star_still_constrains_the_tail():
    # was: a leading `**` matched EVERY path, silently reassigning a whole map.
    from coyomap.reconcile_build import _matches
    assert _matches("**/*.md", "README.md")
    assert _matches("**/*.md", "a/b/c.md")
    assert not _matches("**/*.md", "a/b/c.py")


def test_a_trailing_slash_behaves_like_the_directory():
    # was: a trailing `/` matched nothing at all.
    from coyomap.reconcile_build import _matches
    assert _matches("app/plugins/", "app/plugins/a.py")
    assert _matches("app/plugins", "app/plugins/a.py")
    assert not _matches("app/plugins", "app/pluginsX/a.py")


def test_a_leading_double_star_rule_cannot_sweep_the_whole_map():
    # the end-to-end shape of the same bug: `**/*.md` must not reassign every component.
    doc, _ = expand(make_map(), [{"source_glob": "**/*.md", "subsystem": "S1"}])
    assert doc["set"] == []


# --------------------------------------------------------------------------------------
# Reading FRAGMENTS instead of a map.
#
# `--map` alone made this command unreachable at the one moment a build needs it: the reconcile
# file is an INPUT to `assemble`, and `assemble` is what writes the map, so requiring a map first
# is a circular dependency. Nine consecutive builds resolved it by hand-writing the file the
# command exists to generate. These tests pin the escape and the message that names it.
# --------------------------------------------------------------------------------------


def make_fragment_dir(tmp: str) -> Path:
    """Two harvest fragments, as an agent returns them: ids and sources, no assignments yet."""
    frag_dir = Path(tmp) / ".coyomap" / "build-fragments"
    frag_dir.mkdir(parents=True)
    (frag_dir / "h-plugins.json").write_text(json.dumps({
        "components": [
            {"id": "C1", "name": "PluginA", "source": "app/plugins/a.py:1"},
            {"id": "C2", "name": "PluginB", "source": "app/plugins/b.py:1"},
        ],
        "entities": [{"id": "E1", "name": "Invoice", "meaning": "m",
                      "source": "app/plugins/models.py:3"}],
    }), encoding="utf-8")
    (frag_dir / "h-web.json").write_text(json.dumps({
        "components": [{"id": "C4", "name": "Web", "source": "web/main.py:1"}],
    }), encoding="utf-8")
    return frag_dir


def test_fragments_resolve_the_same_ids_a_map_would():
    from coyomap.reconcile_build import load_elements
    with tempfile.TemporaryDirectory() as tmp:
        frag_dir = make_fragment_dir(tmp)
        m, _ = load_elements(None, [str(p) for p in sorted(frag_dir.glob("*.json"))])
        doc, report = expand(m, [{"source_glob": "app/plugins/**", "subsystem": "S1"}])
        assert doc["set"] == [{"ids": ["C1", "C2"], "subsystem": "S1"}]
        assert "2 element(s)" in report[0]


def test_fragments_and_map_are_interchangeable_inputs():
    # `assemble` mints no ids, so the (id, source) pairs the rules match are identical either way.
    from coyomap.reconcile_build import load_elements
    with tempfile.TemporaryDirectory() as tmp:
        frag_dir = make_fragment_dir(tmp)
        m, _ = load_elements(None, [str(p) for p in sorted(frag_dir.glob("*.json"))])
        rules = [{"source_glob": "app/plugins/**", "subsystem": "S1"},
                 {"source_glob": "web/**", "subsystem": "S2"}]
        from_frags, _ = expand(m, rules)
        from_map, _ = expand(make_map(), rules)
        # make_map() carries C3 too; compare only the elements both inputs hold.
        assert {s["subsystem"]: [i for i in s["ids"] if i != "C3"] for s in from_frags["set"]} == \
               {s["subsystem"]: [i for i in s["ids"] if i != "C3"] for s in from_map["set"]}


def test_a_missing_map_during_a_build_names_the_fragments_escape():
    # the whole point: the error must not read as "your build is broken".
    from coyomap.reconcile_build import load_elements
    with tempfile.TemporaryDirectory() as tmp:
        make_fragment_dir(tmp)
        missing = str(Path(tmp) / ".coyomap" / "project-map.json")
        try:
            load_elements(missing, [])
        except RuleError as exc:
            assert "--fragments" in str(exc)
            assert "does not exist yet" in str(exc)
        else:
            raise AssertionError("a missing map must raise")


def test_a_missing_map_with_no_fragment_dir_stays_a_plain_not_found():
    from coyomap.reconcile_build import load_elements
    with tempfile.TemporaryDirectory() as tmp:
        try:
            load_elements(str(Path(tmp) / "nope.json"), [])
        except RuleError as exc:
            assert "not found" in str(exc)
            assert "--fragments" not in str(exc)
        else:
            raise AssertionError("a missing map must raise")


def test_an_unreadable_fragment_fails_loudly_rather_than_resolving_nothing():
    # the original sin this command exists to prevent: emitting assignments nothing checked.
    from coyomap.reconcile_build import load_elements
    with tempfile.TemporaryDirectory() as tmp:
        frag_dir = make_fragment_dir(tmp)
        (frag_dir / "broken.json").write_text("{not json", encoding="utf-8")
        try:
            load_elements(None, [str(p) for p in sorted(frag_dir.glob("*.json"))])
        except RuleError as exc:
            assert "broken.json" in str(exc)
        else:
            raise AssertionError("a malformed fragment must raise")


def test_passing_both_sources_is_refused():
    from coyomap.reconcile_build import main
    with tempfile.TemporaryDirectory() as tmp:
        rules = write_rules([{"source_glob": "app/**", "subsystem": "S1"}], tmp)
        assert main(["--rules", str(rules), "--map", "m.json", "--fragments", "a.json"]) == 2


def test_main_writes_a_reconcile_file_from_fragments_alone():
    from coyomap.reconcile_build import main
    with tempfile.TemporaryDirectory() as tmp:
        frag_dir = make_fragment_dir(tmp)
        rules = write_rules([{"source_glob": "app/plugins/**", "subsystem": "S1"}], tmp)
        out = Path(tmp) / "reconcile.json"
        argv = ["--rules", str(rules), "--out", str(out), "--fragments"]
        argv += [str(p) for p in sorted(frag_dir.glob("*.json"))]
        assert main(argv) == 0
        assert json.loads(out.read_text())["set"] == [{"ids": ["C1", "C2"], "subsystem": "S1"}]


def make_round_trip_fragments(tmp: str) -> Path:
    """Fragments carrying all three assignable element kinds — components, entities AND deps — so
    the round-trip below can catch a fragment route that silently drops one."""
    frag_dir = Path(tmp) / "build-fragments"
    frag_dir.mkdir(parents=True)
    (frag_dir / "header.json").write_text(json.dumps({
        "title": "RT", "goal": "g",
        "subsystems": [{"id": "S1", "name": "Plugins"}],
        "subdomains": [{"id": "SD1", "name": "Billing"}],
    }), encoding="utf-8")
    (frag_dir / "h-plugins.json").write_text(json.dumps({
        "components": [{"id": "C1", "name": "PluginA", "source": "app/plugins/a.py:1"}],
        "entities": [{"id": "E1", "name": "Invoice", "meaning": "m",
                      "source": "app/plugins/models.py:3"}],
        "deps": [{"id": "D1", "name": "Redis", "type": "broker",
                  "where_configured": "app/plugins/redis.py:2"}],
    }), encoding="utf-8")
    return frag_dir


def test_the_same_rules_resolve_identically_from_fragments_and_from_their_own_assembled_map():
    """The load-bearing claim: `assemble` mints no ids, so both inputs are the same id space.

    This assembles the fragments and compares against the map they produce — the earlier test
    compared two hand-built inputs and stayed green when the fragment route was mutated to drop
    every entity and dep. Covers `subdomain` (entities) and `bucket` (deps), not just `subsystem`.
    """
    from coyomap.assemble import main as assemble_main
    from coyomap.reconcile_build import load_elements
    with tempfile.TemporaryDirectory() as tmp:
        frag_dir = make_round_trip_fragments(tmp)
        frags = [str(p) for p in sorted(frag_dir.glob("*.json"))]
        out = Path(tmp) / "out"
        assert assemble_main([*frags, "--out", str(out)]) == 0

        rules = [{"source_glob": "app/plugins/**", "subsystem": "S1"},
                 {"source_glob": "app/plugins/**", "subdomain": "SD1"},
                 {"source_glob": "app/plugins/**", "bucket": "Data & storage"}]
        from_frags, _ = expand(load_elements(None, frags)[0], rules)
        from_map, _ = expand(load_elements(str(out / "project-map.json"), [])[0], rules)
        assert from_frags == from_map
        # and all three element kinds actually resolved — a route that dropped entities or deps
        # would still satisfy the equality above if it dropped them on BOTH sides.
        assigned = {f: ids for s in from_frags["set"] for f, ids in
                    ((k, s["ids"]) for k in s if k != "ids")}
        assert assigned == {"subsystem": ["C1"], "subdomain": ["E1"], "bucket": ["D1"]}


def test_an_empty_fragments_glob_refuses_instead_of_reading_the_stale_map():
    """nullglob + a glob that matches nothing left the flag with zero paths, and the command read
    the previous build's map. Ids restart at C1 every build, so its C1 resolves and means something
    else: the assignments landed on the wrong components and every stage exited 0."""
    from coyomap.reconcile_build import load_elements, main
    with tempfile.TemporaryDirectory() as tmp:
        try:
            load_elements(None, [], want_fragments=True)
        except RuleError as exc:
            assert "expanded to no paths" in str(exc)
        else:
            raise AssertionError("an empty --fragments must raise, never fall back to the map")
        rules = write_rules([{"source_glob": "app/**", "subsystem": "S1"}], tmp)
        assert main(["--rules", str(rules), "--fragments"]) == 2
        assert main(["--rules", str(rules), "--fragments", "--out", str(Path(tmp) / "r.json")]) == 2


def test_keep_edges_resolves_a_duplicated_triple_on_every_assemble():
    """`fix dedup-edge` edited the assembled map, which the next assemble rebuilt from fragments —
    so a shipped map carried 365 edges while its own committed fragments produced 416."""
    from coyomap.model import Edge, ProjectModel
    from coyomap.reconcile import KeepEdgeDirective, Reconcile, apply_reconcile
    m = ProjectModel(title="T", goal="g")
    m.edges = [Edge(src="C1", verb="calls", dst="C2", where="src/a.py:10"),
               Edge(src="C1", verb="calls", dst="C2", where="src/b.py:20"),
               Edge(src="C3", verb="calls", dst="C4", where="src/c.py:1")]
    rec = Reconcile(keep_edges=[KeepEdgeDirective("C1", "calls", "C2", "src/a.py:10")])
    stats: dict[str, object] = {}
    apply_reconcile(m, rec, stats)
    assert len(m.edges) == 2
    assert [e.where for e in m.edges if e.src == "C1"] == ["src/a.py:10"]
    assert stats["duplicate_edges_resolved"] == 1


def test_a_keep_edges_anchor_that_no_longer_exists_warns_and_keeps_everything():
    """A reconcile file must not rot when a fragment's anchor is later corrected — the same
    0-match-warns rule `drop_edges` already follows."""
    from coyomap.model import Edge, ProjectModel
    from coyomap.reconcile import KeepEdgeDirective, Reconcile, apply_reconcile
    m = ProjectModel(title="T", goal="g")
    m.edges = [Edge(src="C1", verb="calls", dst="C2", where="src/a.py:10"),
               Edge(src="C1", verb="calls", dst="C2", where="src/b.py:20")]
    notes = apply_reconcile(m, Reconcile(
        keep_edges=[KeepEdgeDirective("C1", "calls", "C2", "src/gone.py:1")]), {})
    assert len(m.edges) == 2
    assert any("none of" in n and "kept them all" in n for n in notes)


def test_two_keep_edges_for_one_triple_are_a_contradiction_not_a_stale_directive():
    """At apply time this surfaced as "declared 1 time(s) — nothing to de-duplicate", because the
    first keep had already resolved the triple. That reads as drift, which is warned about and
    tolerated; it is actually the operator asking for two incompatible things."""
    from coyomap.model import Edge, ProjectModel
    from coyomap.reconcile import KeepEdgeDirective, Reconcile, validate_reconcile
    m = ProjectModel(title="T", goal="g")
    m.edges = [Edge(src="C1", verb="calls", dst="C2", where="a.py:1"),
               Edge(src="C1", verb="calls", dst="C2", where="b.py:2")]
    probs = validate_reconcile(m, Reconcile(keep_edges=[
        KeepEdgeDirective("C1", "calls", "C2", "a.py:1"),
        KeepEdgeDirective("C1", "calls", "C2", "b.py:2")]))
    assert probs and "one triple can only survive at one anchor" in probs[0]
    # the same anchor twice is harmless — a merge that recorded it twice, not a contradiction
    assert not validate_reconcile(m, Reconcile(keep_edges=[
        KeepEdgeDirective("C1", "calls", "C2", "a.py:1"),
        KeepEdgeDirective("C1", "calls", "C2", "a.py:1")]))


def test_keeping_and_dropping_the_same_triple_is_refused():
    """Both are honoured in order — the keep narrows to one row and the drop then removes it — so
    the edge vanishes and the keep directive reads as if it did nothing."""
    from coyomap.model import Edge, ProjectModel
    from coyomap.reconcile import (DropEdgeDirective, KeepEdgeDirective, Reconcile,
                                   validate_reconcile)
    m = ProjectModel(title="T", goal="g")
    m.edges = [Edge(src="C1", verb="calls", dst="C2", where="a.py:1")]
    probs = validate_reconcile(m, Reconcile(
        keep_edges=[KeepEdgeDirective("C1", "calls", "C2", "a.py:1")],
        drop_edges=[DropEdgeDirective(src="C1", verb="calls", dst="C2")]))
    assert probs and "the drop would win" in probs[0]


def test_a_bare_fragment_directory_is_expanded_instead_of_erroring():
    """A directory is what an operator types first, and it used to die on the fragment reader's raw
    `[Errno 21] Is a directory`. `--help` shows a glob but never says a bare directory is refused,
    so the failure reads as "this command is broken" — a live build lost a turn to it. Expansion is
    sorted, so the argument order stays the shell's glob order and a re-run assembles identically."""
    from coyomap.reconcile_build import load_elements
    with tempfile.TemporaryDirectory() as tmp:
        frag_dir = make_fragment_dir(tmp)
        from_dir, _ = load_elements(None, [str(frag_dir)], want_fragments=True)
        from_glob, _ = load_elements(None, [str(p) for p in sorted(frag_dir.glob("*.json"))],
                                     want_fragments=True)
        assert [c.id for c in from_dir.components] == [c.id for c in from_glob.components]
        assert [c.id for c in from_dir.components] == ["C1", "C2", "C4"]


def test_an_empty_fragment_directory_still_refuses():
    """Expanding must not turn "the harvest has not written anything yet" into a silent empty run —
    that is the case `want_fragments` exists to refuse, and it still has to be refused."""
    from coyomap.reconcile_build import RuleError, load_elements
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "build-fragments"
        empty.mkdir()
        try:
            load_elements(None, [str(empty)], want_fragments=True)
        except RuleError as e:
            assert "no readable fragment" in str(e), e
        else:
            raise AssertionError("an empty directory must refuse, not read the map")


def test_a_directory_named_something_json_still_raises():
    """`assemble` guards a directory swept up by the caller's own glob on purpose. Expanding every
    directory argument made that guard unreachable for `reconcile`: a nested `inner.json/` was
    silently dropped instead of erroring, so the glob form and the bare-directory form disagreed
    about the file set while both exited 0."""
    from coyomap.reconcile_build import RuleError, load_elements
    with tempfile.TemporaryDirectory() as tmp:
        frag_dir = make_fragment_dir(tmp)
        (frag_dir / "inner.json").mkdir()
        paths = [str(p) for p in sorted(frag_dir.glob("*.json"))]
        assert any(p.endswith("inner.json") for p in paths), paths
        try:
            load_elements(None, paths, want_fragments=True)
        except RuleError as e:
            assert "Is a directory" in str(e), e
        else:
            raise AssertionError("a directory named *.json must still raise, not vanish")


def test_reconcile_carries_forward_directives_it_does_not_author(tmp_path):
    """`coyomap reconcile` writes only `set`, and the write is whole-file — so a `set_anchors`
    block recorded by `fix apply-drift --to-reconcile` (into the SAME default file) was silently
    deleted by the next ordinary reconcile, and the map reverted to the drifted anchors with
    nothing said. That is the exact durability those flags exist to provide."""
    import json
    from coyomap import reconcile_build
    from coyomap.model import to_canonical_json
    map_path = tmp_path / "map.json"
    map_path.write_text(to_canonical_json(make_map()), encoding="utf-8")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"rules": [
        {"subsystem": "S1", "source_glob": "app/plugins/**"}]}), encoding="utf-8")
    out = tmp_path / "reconcile.json"
    out.write_text(json.dumps({
        "set_anchors": [{"claim": "C1 reads E1", "corrected": "a.py:9"}],
        "keep_edges": [{"src": "C1", "verb": "reads", "dst": "E1", "where": "a.py:9"}],
    }), encoding="utf-8")
    assert reconcile_build.main(["--rules", str(rules), "--map", str(map_path),
                                 "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["set_anchors"] == [{"claim": "C1 reads E1", "corrected": "a.py:9"}]
    assert len(doc["keep_edges"]) == 1
    assert doc["set"]                      # and the regenerated assignments are there too


# --------------------------------------------------------------------------------------
# generator ↔ consumer parity
# --------------------------------------------------------------------------------------

def test_the_generator_accepts_every_field_the_consumer_sets():
    """The test `_FIELD_OWNER`'s comment has claimed for two releases and never had.

    The generator listed 5 fields; the consumer `reconcile._SET_FIELD_OWNER` accepts 7. The two extra
    ones — `capability` and `entry_points` — are exactly what the method prescribes for a use case,
    so `coyomap reconcile --rules` could not express the assignment it exists to express. Two real
    builds hand-worked around it and both shipped `entry_points: []` on EVERY use case (43 of 43 on
    one, 40 of 40 on the other). A drift in either direction is a command that cannot say what the
    method asks for, or a file that assembles and silently drops a field."""
    from coyomap.reconcile import _SET_FIELD_OWNER
    from coyomap.reconcile_build import _FIELD_OWNER
    consumer = {field: owner for field, (owner, _label) in _SET_FIELD_OWNER.items()}
    missing = sorted(set(consumer) - set(_FIELD_OWNER))
    extra = sorted(set(_FIELD_OWNER) - set(consumer))
    assert not missing, f"field(s) the consumer sets that `reconcile --rules` cannot emit: {missing}"
    assert not extra, f"field(s) the generator emits that the consumer would reject: {extra}"
    mismatched = sorted(f for f in _FIELD_OWNER if _FIELD_OWNER[f] is not consumer[f])
    assert not mismatched, f"field(s) the two dicts disagree about the owner of: {mismatched}"


def test_every_owner_type_the_generator_knows_is_reachable_in_a_map():
    """`_FIELD_OWNER` naming a type that `_elements()` never yields is the same defect one level
    down: the field validates, matches nothing, and reports "matched NOTHING" forever. `m.use_cases`
    was missing while `capability`/`entry_points` were being added."""
    from coyomap.reconcile_build import _FIELD_OWNER, _elements
    m = make_map()
    m.use_cases = [UseCase(id="UC1", name="Do it")]
    m.rules = [BusinessRule(id="BR1", name="Owner-only cancellation", statement="Only an owner may cancel.",
                            sites=[RuleSite(where="app/plugins/a.py:9", why="rejects a non-owner")])]
    m.interfaces = [Interface(id="I1", name="Command line", side="ours")]
    m.entry_points = [EntryPoint(id="EP1", kind="cli", trigger="coyomap build",
                                 source="app/cli.py:12", component="C1")]
    reachable = {type(el) for el in _elements(m)}
    unreachable = sorted({t.__name__ for t in _FIELD_OWNER.values()} - {t.__name__ for t in reachable})
    assert not unreachable, (
        f"element type(s) a rule may target that `_elements()` never yields: {unreachable}")


def test_a_use_case_can_be_assigned_its_entry_points_by_id():
    """End to end: the assignment the method prescribes, through the real generator."""
    m = make_map()
    m.use_cases = [UseCase(id="UC1", name="Do it")]
    doc, report = expand(m, [{"ids": ["UC1"], "entry_points": ["EP1", "EP2"]}])
    assert doc["set"] == [{"ids": ["UC1"], "entry_points": ["EP1", "EP2"]}], doc
    assert any("1 element(s)" in line for line in report), report


# --- drop_relations: the blocking duplicate that could not be recorded (retro 2026-08-14) ---------
# `fix dedup-relation` was the only writing verb with no directive. A duplicate relation BLOCKS, so
# the in-place resolution was discarded by the next assemble and the build re-blocked on the very
# duplicate it had just resolved.

def make_relation_map(relations: list[dict]) -> dict:
    return {"format": "coyomap-map", "title": "t", "goal": "g",
            "use_cases": [{"id": "UC1", "name": "Do"}],
            "components": [{"id": "C1", "name": "A", "source": "a.py:1"}],
            "entities": [{"id": "E1", "name": "Thing", "relations": relations},
                         {"id": "E2", "name": "Other"}]}


def apply_directives(map_doc: dict, directives: dict) -> tuple:
    from coyomap.model import load_model
    from coyomap.reconcile import apply_reconcile, load_reconcile
    m = load_model(json.dumps(map_doc))
    rec = load_reconcile(json.dumps(directives), "test")
    stats: dict = {}
    notes = apply_reconcile(m, rec, stats)
    return m, stats, notes


def test_a_recorded_relation_drop_is_applied_on_re_assembly():
    doc = make_relation_map([{"verb": "has", "target": "E2"}, {"verb": "has", "target": "E2"}])
    m, stats, _notes = apply_directives(
        doc, {"drop_relations": [{"entity": "E1", "verb": "has", "target": "E2"}]})
    assert len(m.entities[0].relations) == 1, "exactly ONE occurrence is removed"
    assert stats["reconcile_relations_dropped"] == 1


def test_only_one_occurrence_goes_per_directive():
    doc = make_relation_map([{"verb": "has", "target": "E2"}] * 3)
    m, _stats, _notes = apply_directives(
        doc, {"drop_relations": [{"entity": "E1", "verb": "has", "target": "E2"}] * 2})
    assert len(m.entities[0].relations) == 1


def test_a_zero_match_warns_and_never_fails():
    """A reconcile file must not rot when the fragment that declared the duplicate is later fixed —
    the same rule `drop_edges` follows."""
    doc = make_relation_map([{"verb": "has", "target": "E2"}])
    m, stats, notes = apply_directives(
        doc, {"drop_relations": [{"entity": "E1", "verb": "owns", "target": "E2"}]})
    assert len(m.entities[0].relations) == 1
    assert stats["reconcile_relations_dropped"] == 0
    assert any("declares no" in n for n in notes), notes


def test_an_unknown_entity_warns_rather_than_failing():
    doc = make_relation_map([{"verb": "has", "target": "E2"}])
    _m, _stats, notes = apply_directives(
        doc, {"drop_relations": [{"entity": "E9", "verb": "has", "target": "E2"}]})
    assert any("no entity 'E9'" in n for n in notes), notes


def test_the_verb_match_is_case_insensitive_like_the_fix_verb():
    doc = make_relation_map([{"verb": "Has", "target": "E2"}, {"verb": "has", "target": "E2"}])
    m, _stats, _notes = apply_directives(
        doc, {"drop_relations": [{"entity": "E1", "verb": "has", "target": "E2"}]})
    assert len(m.entities[0].relations) == 1


def test_a_stale_directive_never_deletes_the_LAST_occurrence():
    """The directive means "drop one occurrence of a DUPLICATE". The normal repair order makes the
    dangerous case the default: record the directive, then fix the duplicate at source, and the next
    assemble silently removes the survivor — reported as a note and counted as a success."""
    doc = make_relation_map([{"verb": "has", "target": "E2"}])          # already repaired
    m, stats, notes = apply_directives(
        doc, {"drop_relations": [{"entity": "E1", "verb": "has", "target": "E2"}]})
    assert len(m.entities[0].relations) == 1, "a real domain fact must survive a stale directive"
    assert stats["reconcile_relations_dropped"] == 0
    assert any("no longer a duplicate" in n for n in notes), notes


def test_a_reciprocal_pair_is_still_droppable_with_one_occurrence_per_card():
    """`fix dedup-relation` lists two blocking shapes; the reciprocal one leaves ONE occurrence per
    card, so a single match is a legitimate drop there and must not read as stale."""
    doc = {"format": "coyomap-map", "title": "t", "goal": "g",
           "use_cases": [{"id": "UC1", "name": "Do"}],
           "components": [{"id": "C1", "name": "A", "source": "a.py:1"}],
           "entities": [{"id": "E1", "name": "Thing",
                         "relations": [{"verb": "has", "target": "E2"}]},
                        {"id": "E2", "name": "Other",
                         "relations": [{"verb": "belongs to", "target": "E1"}]}]}
    m, stats, _notes = apply_directives(
        doc, {"drop_relations": [{"entity": "E1", "verb": "has", "target": "E2"}]})
    assert m.entities[0].relations == []
    assert stats["reconcile_relations_dropped"] == 1


def test_a_malformed_drop_relations_directive_is_refused_at_load():
    from coyomap.reconcile import ReconcileError, load_reconcile
    for bad in ({"drop_relations": "nope"},
                {"drop_relations": [{"entity": "E1", "verb": "has"}]},
                {"drop_relations": [{"entity": "E1", "verb": "has", "target": "E2", "x": 1}]},
                {"drop_relations": [{"entity": "", "verb": "has", "target": "E2"}]}):
        try:
            load_reconcile(json.dumps(bad), "test")
        except ReconcileError:
            continue
        raise AssertionError(f"accepted a malformed directive: {bad}")


def test_a_rule_assigning_an_undeclared_group_is_reported_before_assemble_refuses_it():
    """Checking the SOURCE glob and not the DESTINATION is half a check. A rules file assigned
    `subdomain: SD9` while the map declared SD1..SD8; three `--dry-run` passes reported clean and
    `assemble` then died with "E62 parent SD9 is undefined … ASSEMBLY FAILED", four turns later."""
    m = make_map()
    m.entities.append(Entity(id="E1", name="Thing", source="app/plugins/x.py:1"))
    _doc, report = expand(m, [{"ids": ["E1"], "subdomain": "SD99"}])
    bad = [r for r in report if "SD99" in r and "nothing declares" in r]
    assert bad, f"an undeclared assignment target must be reported, got: {report}"


# --------------------------------------------------------------------------------------
# the entry-point witness — `EPn` renumbers, so an id that RESOLVES is not an id that still
# means the same surface
# --------------------------------------------------------------------------------------

def make_map_with_entry_points() -> ProjectModel:
    """A map whose EP ids are what a previous assemble minted. The two surfaces are deliberately the
    pair from the incident the tool records: an order route and an admin wipe, which traded ids when
    numbering followed argument order."""
    m = make_map()
    m.use_cases = [UseCase(id="UC1", name="Place an order", trigger="buyer submits", outcome="recorded")]
    m.entry_points = [
        EntryPoint(id="EP1", kind="http-route", trigger="POST /orders",
                   component="C4", source="web/orders.py:9"),
        EntryPoint(id="EP2", kind="http-route", trigger="DELETE /admin/wipe",
                   component="C4", source="web/admin.py:4"),
    ]
    return m


def make_witnessed_reconcile(ep_id: str, seen: str):
    """A reconcile file in the witnessed form the generator now emits."""
    from coyomap.reconcile import load_reconcile
    return load_reconcile(json.dumps({"set": [{"ids": ["UC1"],
                                               "entry_points": [{"id": ep_id, "source": seen}]}]}),
                          "reconcile.json")


def test_a_witness_that_still_matches_the_map_passes():
    from coyomap.reconcile import validate_reconcile
    m = make_map_with_entry_points()
    assert not validate_reconcile(m, make_witnessed_reconcile("EP1", "web/orders.py:9"))


def test_a_renumbered_entry_point_is_refused_and_names_both_anchors():
    """The failure this exists for. The id resolves, so every other check passes and the map ships
    claiming the wrong front door — one build had `POST /orders` and `DELETE /admin/wipe-database`
    trade ids, the use case claimed the wrong one, and the warning count did not move."""
    from coyomap.reconcile import validate_reconcile
    m = make_map_with_entry_points()
    probs = validate_reconcile(m, make_witnessed_reconcile("EP1", "web/admin.py:4"))
    assert len(probs) == 1
    assert "witnesses EP1 at 'web/admin.py:4'" in probs[0]
    assert "is now 'web/orders.py:9'" in probs[0]
    assert "different" in probs[0] and "front door" in probs[0]


def test_a_bare_id_still_works_and_witnesses_nothing():
    """The un-witnessed form stays legal — a small map is hand-authorable — but it buys no protection,
    which is why the generator emits the witnessed one."""
    from coyomap.reconcile import load_reconcile, validate_reconcile
    m = make_map_with_entry_points()
    rec = load_reconcile(json.dumps({"set": [{"ids": ["UC1"], "entry_points": ["EP1"]}]}), "r.json")
    assert rec.sets[0].entry_points == ["EP1"]
    assert rec.sets[0].entry_point_witness == {}
    assert not validate_reconcile(m, rec)


def test_a_corrected_line_in_the_same_file_is_not_a_renumbering():
    """Lenient on purpose. An anchor-drift fix between authoring and applying moves the LINE, not the
    surface — failing on that would fire the check on the one thing that is not the bug."""
    from coyomap.reconcile import validate_reconcile
    m = make_map_with_entry_points()
    assert not validate_reconcile(m, make_witnessed_reconcile("EP1", "web/orders.py:11"))


def test_a_witness_missing_its_source_is_a_parse_error_naming_the_id():
    from coyomap.reconcile import ReconcileError, load_reconcile
    payload = json.dumps({"set": [{"ids": ["UC1"], "entry_points": [{"id": "EP1"}]}]})
    try:
        load_reconcile(payload, "r.json")
    except ReconcileError as e:
        assert "'source' is required" in str(e) and "EP1" in str(e)
    else:
        raise AssertionError("a witness with no source must be refused")


def test_the_generator_witnesses_every_entry_point_it_emits():
    """A check nobody can satisfy is theatre. The normal path has to produce the witnessed form."""
    m = make_map_with_entry_points()
    with tempfile.TemporaryDirectory() as tmp:
        rules = write_rules([{"ids": ["UC1"], "entry_points": ["EP1"]}], tmp)
        doc, _report = expand(m, load_rules(rules))
    assert doc["set"][0]["entry_points"] == [{"id": "EP1", "source": "web/orders.py:9"}]


def test_a_temp_out_path_warns_that_the_live_directives_are_stranded(tmp_path, monkeypatch, capsys):
    """The carry-forward is keyed on `--out`, so a temp path silently loses it.

    A live build ran `--out /tmp/reconcile-new.json` while `.coyomap/reconcile.json` held
    keep_edges (5), drop_edges and set_anchors. The temp file did not exist, so nothing was
    carried, nothing was said, and the lead hand-merged the three keys back in python. The tool's
    own `Next:` hint then echoed the temp path into the suggested `assemble` line.
    """
    from coyomap import reconcile_build
    monkeypatch.chdir(tmp_path)
    live = tmp_path / ".coyomap" / "reconcile.json"
    live.parent.mkdir(parents=True)
    live.write_text(json.dumps({
        "set": [], "keep_edges": [{"src": "C1", "verb": "uses", "dst": "D1"}],
        "set_anchors": [{"claim": "C1 uses D1", "where": "a.py:2"}]}), encoding="utf-8")

    frag = tmp_path / "f.json"
    frag.write_text(json.dumps({"components": [{"id": "C1", "name": "A", "purpose": "p"}]}),
                    encoding="utf-8")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"rules": [{"ids": ["C1"], "subsystem": "S1"}]}), encoding="utf-8")

    reconcile_build.main(["--fragments", str(frag), "--rules", str(rules),
                          "--out", str(tmp_path / "temp-reconcile.json")])
    err = capsys.readouterr().err
    assert "WARNING" in err and "keep_edges" in err and "set_anchors" in err, err
    assert ".coyomap/reconcile.json" in err, err


# ── the two interface fields, end to end ─────────────────────────────────────────────────────────
# The generator, the loader, the validator and the applier are FOUR separate registries of field
# names, and only the first three were kept in step: `interface` was in the dict, the directive, the
# validator and the applier, and missing from the LOADER's scalar-parse loop. Every directive that
# assigned only `interface` then parsed to None, `assigned_fields()` returned [], and the whole file
# was rejected with "assigns no field" — while `coyomap reconcile` went on emitting exactly that
# shape. These two tests walk the whole path, which is the only shape of test that could have caught it.

def make_interface_map_doc() -> ProjectModel:
    m = make_map()
    m.interfaces = [Interface(id="I1", name="Command line", side="ours", facing="user",
                              source="app/plugins/a.py:1")]
    m.entry_points = [EntryPoint(id="EP1", kind="cli", trigger="run it", activation="external",
                                 source="app/plugins/a.py:3", component="C1")]
    return m


def test_a_dep_interfaces_assignment_survives_generate_load_validate_apply():
    from coyomap.reconcile import apply_reconcile, load_reconcile, validate_reconcile
    m = make_interface_map_doc()
    doc, _ = expand(m, [{"ids": ["D1"], "interfaces": ["I1"]}])
    rec = load_reconcile(json.dumps(doc), "reconcile.json")   # the step that used to raise
    assert not validate_reconcile(m, rec)
    stats: dict = {}
    apply_reconcile(m, rec, stats)
    assert m.deps[0].interfaces == ["I1"]
    assert stats["reconcile_set"]["interfaces"] == 1


def test_a_surface_ways_in_assignment_survives_generate_load_validate_apply():
    from coyomap.reconcile import apply_reconcile, load_reconcile, validate_reconcile
    m = make_interface_map_doc()
    doc, _ = expand(m, [{"ids": ["I1"], "ways_in": ["EP1"]}])
    rec = load_reconcile(json.dumps(doc), "reconcile.json")
    assert not validate_reconcile(m, rec)
    stats: dict = {}
    apply_reconcile(m, rec, stats)
    assert m.interfaces[0].ways_in == ["EP1"]
    assert stats["reconcile_set"]["ways_in"] == 1


def test_every_scalar_set_field_is_parsed_by_the_loader():
    """The registry guard for the bug above: any scalar `_SET_FIELD_OWNER` field the loader's parse
    loop does not read is unreachable, and the failure is a rejected FILE, not a rejected field."""
    from coyomap.reconcile import _SET_FIELD_OWNER, load_reconcile
    scalars = [f for f, (owner, _l) in _SET_FIELD_OWNER.items()
               if not isinstance(getattr(SetDirective(ids=["X"]), f, None), list)
               and f not in ("entry_points", "ways_in", "runs_in", "owners", "interfaces")]
    for fld in scalars:
        rec = load_reconcile(json.dumps({"set": [{"ids": ["X1"], fld: "Y1"}]}), "t")
        assert rec.sets[0].assigned_fields() == [fld], fld


# --- an entry point's owning component (retro 2026-09-01, argus row 7) ---------------------------
# `reconcile` had no way to say which component an entry point belongs to. `EPn` ids are minted by
# `assemble` from content, so no fragment can name one, and the only remaining route was a
# hand-written heredoc over the assembled map — 88 of them on one build, outside every check here.

def _map_with_entry_points() -> ProjectModel:
    m = make_map()
    m.entry_points = [
        EntryPoint(id="EP1", kind="cli", trigger="coyomap build", source="app/plugins/a.py:12"),
        EntryPoint(id="EP2", kind="http", trigger="POST /orders", source="web/main.py:31"),
    ]
    return m


def test_an_entry_point_can_be_assigned_its_owning_component():
    from coyomap.reconcile import Reconcile, SetDirective, apply_reconcile, validate_reconcile
    m = _map_with_entry_points()
    rec = Reconcile(sets=[SetDirective(ids=["EP1", "EP2"], component="C1")])
    assert not validate_reconcile(m, rec)
    apply_reconcile(m, rec, {})
    assert [ep.component for ep in m.entry_points] == ["C1", "C1"]


def test_an_entry_point_component_that_names_no_component_is_refused():
    """A wrong-but-DEFINED id is what nothing could catch on the heredoc route. An UNDEFINED one
    must not slip through either."""
    from coyomap.reconcile import Reconcile, SetDirective, validate_reconcile
    m = _map_with_entry_points()
    probs = validate_reconcile(m, Reconcile(sets=[SetDirective(ids=["EP1"], component="C99")]))
    assert probs and "not a defined component" in probs[0], probs


def test_an_empty_entry_point_component_is_refused():
    """An empty directive would blank a component the map already carries while reading as an
    assignment — the same trap `interface_kind` guards."""
    from coyomap.reconcile import Reconcile, SetDirective, validate_reconcile
    m = _map_with_entry_points()
    probs = validate_reconcile(m, Reconcile(sets=[SetDirective(ids=["EP1"], component="  ")]))
    assert probs and "is empty" in probs[0], probs


def test_component_can_only_be_set_on_an_entry_point():
    from coyomap.reconcile import Reconcile, SetDirective, validate_reconcile
    m = _map_with_entry_points()
    probs = validate_reconcile(m, Reconcile(sets=[SetDirective(ids=["C2"], component="C1")]))
    assert probs and "can only be set on a entry point" in probs[0], probs


def test_a_component_directive_round_trips_through_the_reconcile_file():
    """The three registries — `_SET_FIELD_OWNER`, `SetDirective` and the scalar-string parse loop —
    have to move together; a field missing from the third parses to None and the whole file is
    rejected as "assigns no field"."""
    from coyomap.reconcile import load_reconcile
    rec = load_reconcile(json.dumps({"set": [{"ids": ["EP1"], "component": "C1"}]}), "test")
    assert rec.sets[0].component == "C1"
    assert rec.sets[0].assigned_fields() == ["component"]
