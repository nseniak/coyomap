#!/usr/bin/env python3
"""Tests for `coyomap assemble` — structured-row fragments → the canonical model.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_assemble.py
    pytest tests/test_assemble.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import get_args, get_type_hints

from coyomap import assemble, prose
from coyomap.assemble import (_infer_ce_verb, ensure_fragments_ignored, load_fragment,
                              load_fragment_paths, merge_fragments)
from coyomap.model import (ConfigRow, ExtraSection, ModelError, ObservabilityRow,
                           ProjectModel, load_model, to_canonical_json)

ASSEMBLE = [sys.executable, "-m", "coyomap.assemble"]


# --- C→E verb inference (regression after the verb families moved to grammar — DRY refactor) -------

def test_infer_ce_verb_unchanged_after_grammar_move():
    # The four families now live in grammar; _infer_ce_verb must classify EXACTLY as before.
    assert _infer_ce_verb("upserts the membership document") == "persists"
    assert _infer_ce_verb("updates the counter") == "writes"
    assert _infer_ce_verb("publishes the event") == "emits"
    assert _infer_ce_verb("encrypts the token") == "encrypts"
    assert _infer_ce_verb("reads the user record") == "reads"
    assert _infer_ce_verb("reads the asset metadata") == "reads"   # 'asset' contains 'set' — not a WRITE
    assert _infer_ce_verb("") == "reads"                            # ambiguous → never over-claims ownership


# --- builders -------------------------------------------------------------------

def make_header_fragment() -> str:
    return json.dumps({"title": "Demo", "goal": "A demo.", "commit": "abc1234"})


def make_harvest_fragment(cid: str = "C1") -> str:
    return json.dumps({
        "components": [{"id": cid, "name": f"Component {cid}", "purpose": "does things"}],
        "deps": [] if cid != "C1" else [{"id": "D1", "name": "Postgres", "kind": "datastore",
                                         "type": "SQL database"}],
    })


def make_trace_fragment() -> str:
    return json.dumps({
        "edges": [{"src": "C1", "verb": "uses", "dst": "D1", "why": "query",
                   "where": "src/a.py:3"}],
    })


# --- merge ----------------------------------------------------------------------

def test_merge_concatenates_arrays_and_takes_singletons():
    parts = [("header.json", load_fragment(make_header_fragment(), "header.json")),
             ("h1.json", load_fragment(make_harvest_fragment("C1"), "h1.json")),
             ("h2.json", load_fragment(make_harvest_fragment("C2"), "h2.json")),
             ("t1.json", load_fragment(make_trace_fragment(), "t1.json"))]
    model, problems = merge_fragments(parts)
    assert problems == []
    assert model.title == "Demo" and model.commit == "abc1234"
    assert [c.id for c in model.components] == ["C1", "C2"]
    assert len(model.edges) == 1 and model.edges[0].dst == "D1"


def test_strip_actor_edges_removes_role_endpoints_and_reports():
    # A trace agent wrongly emits an actor→component edge (R1 → C1). Edges connect
    # components/deps/entities ONLY — assemble strips it and reports the count.
    roles = json.dumps({"roles": [{"id": "R1", "name": "Admin", "kind": "human"}]})
    edges = json.dumps({"edges": [
        {"src": "R1", "verb": "uses", "dst": "C1", "why": "drives", "where": "src/a.py:1"},
        {"src": "C1", "verb": "uses", "dst": "D1", "why": "query", "where": "src/a.py:3"}]})
    parts = [("r.json", load_fragment(roles, "r.json")),
             ("e.json", load_fragment(edges, "e.json"))]
    stats: dict[str, int] = {}
    model, problems = merge_fragments(parts, stats)
    assert problems == []
    assert [(e.src, e.dst) for e in model.edges] == [("C1", "D1")]
    assert stats["actor_edges_stripped"] == 1


def make_component_fragment(cid: str, name: str, source: str, extra: dict | None = None) -> str:
    comp = {"id": cid, "name": name, "purpose": "does things", "source": source}
    return json.dumps({"components": [comp], **(extra or {})})


def test_component_dedup_merges_same_file_and_repoints_test_targets():
    # The same module harvested by two overlapping slices (same file + name). assemble collapses
    # them to one and RE-POINTS every reference — here a tests[].targets id (the review blocker-1
    # regression: a missed ref would become a dangling-reference validate failure).
    a = make_component_fragment("C1", "RolesManager", "mee6/roles_manager/__init__.py:1")
    b = json.dumps({
        "components": [{"id": "C2", "name": "RolesManager",
                        "purpose": "does things", "source": "mee6/roles_manager/__init__.py:1"}],
        "edges": [{"src": "C2", "verb": "uses", "dst": "D1", "why": "q", "where": "x.py:2"}],
        "tests": [{"targets": ["C2"], "tested": "no", "gap": "untested"}],
        "entry_points": [{"kind": "route", "trigger": "GET /x", "source": "x.py:1", "component": "C2"}],
    })
    parts = [("a.json", load_fragment(a, "a.json")), ("b.json", load_fragment(b, "b.json"))]
    stats: dict[str, int] = {}
    model, problems = merge_fragments(parts, stats)
    assert problems == []
    assert [c.id for c in model.components] == ["C1"]           # C2 merged away
    assert stats["components_merged"] == 1
    assert model.edges[0].src == "C1"                            # edge re-pointed
    assert model.tests[0].targets == ["C1"]                     # tests target re-pointed (blocker 1)
    assert model.entry_points[0].component == "C1"              # owner re-pointed
    # the round-trips through validate with no dangling reference
    assert load_model(to_canonical_json(model)) is not None


def test_component_dedup_skips_directory_anchor_and_empty_source():
    # A shared DIRECTORY anchor is NOT identity (two different components legitimately live under one
    # dir), and an empty source is not identity either (review blocker 2) — neither pair merges.
    dir_a = make_component_fragment("C1", "PluginA", "mee6/plugins/")
    dir_b = make_component_fragment("C2", "PluginB", "mee6/plugins/")
    none_a = json.dumps({"components": [{"id": "C3", "name": "X", "purpose": "p"}]})
    none_b = json.dumps({"components": [{"id": "C4", "name": "X", "purpose": "p"}]})
    parts = [(n, load_fragment(f, n)) for n, f in
             [("a", dir_a), ("b", dir_b), ("c", none_a), ("d", none_b)]]
    stats: dict[str, int] = {}
    model, _problems = merge_fragments(parts, stats)
    assert [c.id for c in model.components] == ["C1", "C2", "C3", "C4"]  # nothing merged
    assert stats["components_merged"] == 0


def test_duplicate_id_across_fragments_is_a_conflict():
    parts = [("a.json", load_fragment(make_harvest_fragment("C1"), "a.json")),
             ("b.json", load_fragment(make_harvest_fragment("C1"), "b.json"))]
    _model, problems = merge_fragments(parts)
    assert any("duplicate id C1" in p and "a.json" in p and "b.json" in p for p in problems)


def test_assemble_collapses_same_edge_same_call_site():
    # Two trace slices emit the SAME relationship at the SAME call site, differing only in the `why`
    # wording (the real duplication pattern) → one row kept (the first `why`).
    a = json.dumps({"edges": [{"src": "C1", "verb": "persists", "dst": "E1",
                               "why": "insert the row", "where": "src/a.py:3"}]})
    b = json.dumps({"edges": [{"src": "C1", "verb": "persists", "dst": "E1",
                               "why": "creates and stores the record", "where": "src/a.py:3"}]})
    parts = [("t1.json", load_fragment(a, "t1.json")), ("t2.json", load_fragment(b, "t2.json"))]
    model, problems = merge_fragments(parts)
    assert problems == []
    assert len(model.edges) == 1 and model.edges[0].why == "insert the row"


def test_assemble_keeps_edges_that_differ_in_anchor():
    # Same (src,verb,dst) but a DIFFERENT where is a real conflict — NOT silently merged; both kept
    # (validate then warns so a human picks the primary call site).
    a = json.dumps({"edges": [{"src": "C1", "verb": "uses", "dst": "D1", "why": "q", "where": "a.py:3"}]})
    b = json.dumps({"edges": [{"src": "C1", "verb": "uses", "dst": "D1", "why": "q", "where": "a.py:9"}]})
    parts = [("a.json", load_fragment(a, "a.json")), ("b.json", load_fragment(b, "b.json"))]
    model, _problems = merge_fragments(parts)
    assert len(model.edges) == 2


def test_assemble_never_merges_no_call_site_edges():
    # A no_call_site edge has no anchor to disambiguate, so a differing `why` may be two DISTINCT
    # couplings (two events on the same pair) — never silently merged; both kept for validate to warn.
    a = json.dumps({"edges": [{"src": "C1", "verb": "notifies", "dst": "C2",
                               "why": "publishes OrderCreated", "no_call_site": True}]})
    b = json.dumps({"edges": [{"src": "C1", "verb": "notifies", "dst": "C2",
                               "why": "publishes OrderCancelled", "no_call_site": True}]})
    parts = [("a.json", load_fragment(a, "a.json")), ("b.json", load_fragment(b, "b.json"))]
    model, _problems = merge_fragments(parts)
    assert len(model.edges) == 2


def test_dep_merge_then_edge_dedup_collapses_repointed_duplicates():
    # dep-merge re-points two edges (C1→D2, C1→D1) onto the SAME survivor dep at the SAME call site;
    # edge-dedup (which runs after) must then collapse the now-identical pair to one.
    d1 = json.dumps({"deps": [{"id": "D1", "name": "stripe", "kind": "saas", "type": "payments"}],
                     "edges": [{"src": "C1", "verb": "uses", "dst": "D1", "why": "charge",
                                "where": "pay.py:5"}]})
    d2 = json.dumps({"deps": [{"id": "D2", "name": "stripe", "kind": "saas", "type": "payments"}],
                     "edges": [{"src": "C1", "verb": "uses", "dst": "D2", "why": "charge",
                                "where": "pay.py:5"}]})
    parts = [("a.json", load_fragment(d1, "a.json")), ("b.json", load_fragment(d2, "b.json"))]
    model, _problems = merge_fragments(parts)
    assert len(model.deps) == 1                       # stripe merged to one dep
    assert len(model.edges) == 1 and model.edges[0].dst == "D1"   # re-pointed pair collapsed


def test_duplicate_deps_merge_by_identity_and_repoint_edges():
    # Two agents discover the SAME external dep (stripe) under different ids; one traces an edge to the
    # second id. Merge collapses them to one dep and re-points the edge to the survivor (C2). No error —
    # multi-slice discovery of the same dep is correct input, not a conflict.
    d1 = '{"deps":[{"id":"D1","name":"stripe"}]}'
    d2 = ('{"deps":[{"id":"D2","name":"Stripe"}],'
          '"edges":[{"src":"C1","verb":"uses","dst":"D2","where":"a.py:1"}]}')
    parts = [("a.json", load_fragment(d1, "a.json")), ("b.json", load_fragment(d2, "b.json"))]
    model, problems = merge_fragments(parts)
    assert problems == []
    assert [d.id for d in model.deps] == ["D1"]      # collapsed to one row
    assert model.edges[0].dst == "D1"                # edge re-pointed to the survivor


def test_distinct_deps_are_not_merged():
    d1 = '{"deps":[{"id":"D1","name":"stripe"}]}'
    d2 = '{"deps":[{"id":"D2","name":"redis"}]}'
    parts = [("a.json", load_fragment(d1, "a.json")), ("b.json", load_fragment(d2, "b.json"))]
    model, _ = merge_fragments(parts)
    assert {d.id for d in model.deps} == {"D1", "D2"}  # different deps stay separate


def test_conflicting_singletons_are_a_conflict():
    a = load_fragment(json.dumps({"title": "One"}), "a.json")
    b = load_fragment(json.dumps({"title": "Two"}), "b.json")
    _model, problems = merge_fragments([("a.json", a), ("b.json", b)])
    assert any("'title'" in p for p in problems)


def test_malformed_fragment_fails_alone_with_its_path():
    try:
        load_fragment(json.dumps({"components": [{"id": "C1"}]}), "h.json")  # name missing
        raise AssertionError("expected ModelError")
    except ModelError as e:
        assert "h.json" in str(e)


# --- extra accepts natural JSON values --------------------------------------------

def test_extra_accepts_natural_json_values():
    frag = json.dumps({"components": [{"id": "C1", "name": "X", "extra": {
        "Ports": [8080, 8443], "Replicas": 3, "HA": True, "Note": "plain text"}}]})
    m = load_fragment(frag, "h.json")
    assert m.components[0].extra["Ports"] == [8080, 8443]
    assert m.components[0].extra["Replicas"] == 3
    # the canonical serializer round-trips the values unchanged
    m2 = load_model(to_canonical_json(merge_fragments([("h.json", m)])[0]))
    assert m2.components[0].extra == m.components[0].extra


def test_extra_non_string_values_render_as_compact_json_in_the_md_view():
    from coyomap.views import model_to_markdown
    frag = json.dumps({"title": "T", "components": [
        {"id": "C1", "name": "X", "extra": {"Ports": [8080, 8443]}}]})
    model, problems = merge_fragments([("h.json", load_fragment(frag, "h.json"))])
    assert problems == []
    md = model_to_markdown(model)
    assert "[8080, 8443]" in md, md


# --- files / evidence / package / alternative: real fields, rendered as their own T1/T2 columns ---

def test_component_files_and_evidence_render_as_their_own_t1_columns():
    from coyomap.views import model_to_markdown
    frag = json.dumps({"title": "T", "components": [
        {"id": "C1", "name": "X", "files": ["src/v.py", "src/helpers.py"],
         "evidence": [{"file": "src/v.py:12", "why": "the entry point"}]}]})
    model, problems = merge_fragments([("h.json", load_fragment(frag, "h.json"))])
    assert problems == []
    md = model_to_markdown(model)
    assert "| Files |" in md and "Evidence |" in md, md
    assert "src/v.py · src/helpers.py" in md
    assert "[v.py](src/v.py:12) — the entry point" in md


def test_dep_package_and_alternative_render_as_their_own_t2_columns():
    from coyomap.views import model_to_markdown
    frag = json.dumps({"title": "T", "deps": [
        {"id": "D1", "name": "MongoDB", "package": "motor ^3.7.0 (pyproject.toml)",
         "alternative": "file-backed storage in standalone mode"}]})
    model, problems = merge_fragments([("h.json", load_fragment(frag, "h.json"))])
    assert problems == []
    md = model_to_markdown(model)
    assert "| Package |" in md and "Alternative |" in md, md
    assert "motor ^3.7.0 (pyproject.toml)" in md
    assert "file-backed storage in standalone mode" in md


def test_files_and_evidence_columns_absent_when_unused():
    from coyomap.views import model_to_markdown
    frag = json.dumps({"title": "T", "components": [{"id": "C1", "name": "X"}]})
    model, problems = merge_fragments([("h.json", load_fragment(frag, "h.json"))])
    assert problems == []
    md = model_to_markdown(model)
    assert "| Files |" not in md and "| Evidence |" not in md, md


# --- anchors are not fixed up ------------------------------------------------------
# `assemble` no longer normalizes anchor drift (a markdown-linked anchor, a missing directory
# slash, a retired `#Lnnn` suffix) — a fragment's fields pass through unchanged, and
# `coyomap validate`'s `_check_anchor_format` (tests/test_validate_model.py) is what rejects a
# wrong shape. These guard that no silent fix-up regrows here.

def test_component_anchor_passes_through_unchanged():
    frag = {"components": [{"id": "C1", "name": "X", "source": "[app.py](backend/app.py#L10)"}]}
    model, problems = merge_fragments([("f.json", load_fragment(json.dumps(frag), "f.json"))])
    assert problems == []
    assert model.components[0].source == "[app.py](backend/app.py#L10)"


def test_edge_where_passes_through_unchanged():
    frag = {"components": [{"id": "C1", "name": "X"}, {"id": "C2", "name": "Y"}],
            "edges": [{"src": "C1", "verb": "uses", "dst": "C2",
                      "where": "[app.py](backend/app.py#L20)"}]}
    model, problems = merge_fragments([("f.json", load_fragment(json.dumps(frag), "f.json"))])
    assert problems == []
    assert model.edges[0].where == "[app.py](backend/app.py#L20)"


# --- the build-fragments gitignore -------------------------------------------------

def test_ensure_fragments_ignored_creates_appends_and_is_idempotent():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        assert ensure_fragments_ignored(out) is True
        body = (out / ".gitignore").read_text(encoding="utf-8")
        assert body.splitlines() == list(assemble._GITIGNORE_KEEP)
        assert ensure_fragments_ignored(out) is False  # idempotent


def test_ensure_fragments_ignored_strips_stray_preindex_ignore():
    # preindex.json is a committed artifact — a stray ignore line (older build / hand edit) must be
    # stripped, build-fragments/ kept, and any unrelated lines left intact.
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / ".gitignore").write_text("preindex.json", encoding="utf-8")  # no trailing newline
        assert ensure_fragments_ignored(out) is True
        assert (out / ".gitignore").read_text(encoding="utf-8").splitlines() == \
            list(assemble._GITIGNORE_KEEP)
        # a fuller stray gitignore: preindex stripped, every per-run entry present, others preserved
        (out / ".gitignore").write_text("*.log\nbuild-fragments/\npreindex.json\n", encoding="utf-8")
        assert ensure_fragments_ignored(out) is True
        lines = (out / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert lines[0] == "*.log"                                   # unrelated line preserved
        assert set(assemble._GITIGNORE_KEEP) <= set(lines)           # every per-run artifact ignored
        assert "preindex.json" not in lines                          # the committed artifact is not
        assert ensure_fragments_ignored(out) is False  # now stable


def test_assemble_cli_writes_the_fragments_gitignore():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h.json"
        p.write_text(make_harvest_fragment("C1"), encoding="utf-8")
        out = Path(td) / "map"
        proc = subprocess.run(ASSEMBLE + [str(p), "--out", str(out)],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert "build-fragments/" in (out / ".gitignore").read_text(encoding="utf-8")


# --- CLI end-to-end ---------------------------------------------------------------

def test_assemble_cli_writes_canonical_map_and_views():
    with tempfile.TemporaryDirectory() as td:
        frags = []
        for name, content in (("header.json", make_header_fragment()),
                              ("h1.json", make_harvest_fragment("C1")),
                              ("t1.json", make_trace_fragment())):
            p = Path(td) / name
            p.write_text(content, encoding="utf-8")
            frags.append(str(p))
        out = Path(td) / "map"
        proc = subprocess.run(ASSEMBLE + frags + ["--out", str(out)],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        model = load_model((out / "project-map.json").read_text(encoding="utf-8"))
        assert model.title == "Demo" and [c.id for c in model.components] == ["C1"]
        # The interactive viewer is served by `coyomap serve`, not baked, so assembly writes json + md
        # (the committed views) and no HTML file.
        assert (out / "project-map.md").exists() and not (out / "project-map.html").exists()


def test_assemble_cli_fails_on_duplicate_ids_and_writes_nothing():
    with tempfile.TemporaryDirectory() as td:
        p1, p2 = Path(td) / "a.json", Path(td) / "b.json"
        p1.write_text(make_harvest_fragment("C1"), encoding="utf-8")
        p2.write_text(make_harvest_fragment("C1"), encoding="utf-8")
        out = Path(td) / "map"
        proc = subprocess.run(ASSEMBLE + [str(p1), str(p2), "--out", str(out)],
                              capture_output=True, text=True)
        assert proc.returncode == 1
        assert "duplicate id C1" in proc.stderr
        assert not out.exists()


# --- reconcile (--reconcile: set + drop_edges) ------------------------------------

def make_reconcile_fragment() -> str:
    """A fragment with everything the reconcile directives touch: two components, a subsystem, a dep, an
    entity + subdomain, a deployment unit, one C→D edge, and a C→E flow step with NO backing edge (so
    `_derive_entity_edges` derives one — the target of the drop_edges B1 test)."""
    return json.dumps({
        "title": "Demo", "goal": "g",
        "use_cases": [{"id": "UC1", "name": "Do"}],
        "subsystems": [{"id": "S1", "name": "Core"}],
        "subdomains": [{"id": "SD1", "name": "Sales"}],
        "components": [{"id": "C1", "name": "A", "purpose": "p", "source": "a.py:1"},
                       {"id": "C2", "name": "B", "purpose": "p", "source": "b.py:1"}],
        "deps": [{"id": "D1", "name": "Postgres", "kind": "datastore", "type": "SQL"}],
        "entities": [{"id": "E1", "name": "Order", "source": "order.py:1"}],
        "deployment": [{"unit": "worker"}],
        "edges": [{"src": "C1", "verb": "uses", "dst": "D1", "why": "q", "where": "a.py:2"}],
        "flows": [{"uc": "UC1", "title": "F", "steps": [
            {"n": 1, "src": "C1", "dst": "E1", "phrase": "reads the order", "where": "a.py:5"}]}],
    })


def _assemble_with_reconcile(td: str, reconcile_obj: dict | None
                             ) -> tuple[subprocess.CompletedProcess, Path]:
    frag = Path(td) / "frag.json"
    frag.write_text(make_reconcile_fragment(), encoding="utf-8")
    out = Path(td) / "map"
    args = ASSEMBLE + [str(frag), "--out", str(out)]
    if reconcile_obj is not None:
        rp = Path(td) / "reconcile.json"        # OUTSIDE build-fragments/ (S8) — passed via --reconcile
        rp.write_text(json.dumps(reconcile_obj), encoding="utf-8")
        args += ["--reconcile", str(rp)]
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc, out


def test_reconcile_set_assigns_and_survives_reassemble():
    # The fragment/model-mismatch regression: `set` assignments must re-apply on EVERY assemble (a
    # bespoke patch of the assembled map is discarded by the next assemble).
    rec = {"set": [{"ids": ["C1", "C2"], "subsystem": "S1"},
                   {"ids": ["C1"], "runs_in": ["worker"]},
                   {"ids": ["E1"], "subdomain": "SD1"},
                   {"ids": ["D1"], "bucket": "Data & storage"}]}
    with tempfile.TemporaryDirectory() as td:
        for _ in range(2):                      # assemble TWICE
            proc, out = _assemble_with_reconcile(td, rec)
            assert proc.returncode == 0, proc.stderr
            m = load_model((out / "project-map.json").read_text(encoding="utf-8"))
            assert {c.id: c.subsystem for c in m.components} == {"C1": "S1", "C2": "S1"}
            assert next(c for c in m.components if c.id == "C1").runs_in == ["worker"]
            assert next(e for e in m.entities if e.id == "E1").subdomain == "SD1"
            assert next(d for d in m.deps if d.id == "D1").bucket == "Data & storage"


def test_reconcile_drop_edges_removes_edge_and_heals_riding_step():
    # B1: the C→E edge `_derive_entity_edges` creates from the flow step must be dropped AFTER derivation
    # (not silently re-derived), and its riding step healed so a re-assemble stays stable.
    rec = {"drop_edges": [{"src": "C1", "verb": "reads", "dst": "E1", "drop_steps": True}]}
    with tempfile.TemporaryDirectory() as td:
        for _ in range(2):
            proc, out = _assemble_with_reconcile(td, rec)
            assert proc.returncode == 0, proc.stderr
            m = load_model((out / "project-map.json").read_text(encoding="utf-8"))
            assert not any(e.src == "C1" and e.dst == "E1" for e in m.edges)   # not re-derived
            steps = [s for f in m.flows for s in f.steps]
            assert not any(s.src == "C1" and s.dst == "E1" for s in steps)     # riding step healed


def test_reconcile_rejects_unknown_id_and_wrong_kind_and_bad_parent():
    with tempfile.TemporaryDirectory() as td:
        proc, out = _assemble_with_reconcile(td, {"set": [{"ids": ["C999"], "subsystem": "S1"}]})
        assert proc.returncode == 1 and "unknown id 'C999'" in proc.stderr
        assert not out.exists()                 # nothing written on a bad directive
        proc2, _ = _assemble_with_reconcile(td, {"set": [{"ids": ["E1"], "subsystem": "S1"}]})
        assert proc2.returncode == 1 and "can only be set on a component" in proc2.stderr
        proc3, _ = _assemble_with_reconcile(td, {"set": [{"ids": ["C1"], "subsystem": "SD1"}]})
        assert proc3.returncode == 1 and "is not a subsystem" in proc3.stderr
        proc4, _ = _assemble_with_reconcile(td, {"set": [{"ids": ["C1"], "runs_in": ["ghost"]}]})
        assert proc4.returncode == 1 and "unknown deployment unit" in proc4.stderr


def test_reconcile_zero_match_drop_edges_warns_but_does_not_fail():
    rec = {"drop_edges": [{"src": "C1", "verb": "calls", "dst": "C2"}]}   # no such edge
    with tempfile.TemporaryDirectory() as td:
        proc, out = _assemble_with_reconcile(td, rec)
        assert proc.returncode == 0, proc.stderr        # a stale directive warns, never fails
        assert "matched 0 edges" in proc.stderr
        assert (out / "project-map.json").exists()


def test_reconcile_reports_counts_in_the_summary():
    rec = {"set": [{"ids": ["C1", "C2"], "subsystem": "S1"}]}
    with tempfile.TemporaryDirectory() as td:
        proc, _ = _assemble_with_reconcile(td, rec)
        assert proc.returncode == 0, proc.stderr
        assert "reconcile applied" in proc.stdout and "subsystem: 2" in proc.stdout
        assert "reconcile set subsystem:2" in proc.stdout        # the self-describing digest (WS-T2)


def test_assemble_notes_present_but_unpassed_reconcile_file():
    # S8: a reconcile file present in the out dir but not passed silently reverts assignments — nudge.
    with tempfile.TemporaryDirectory() as td:
        frag = Path(td) / "frag.json"
        frag.write_text(make_reconcile_fragment(), encoding="utf-8")
        out = Path(td) / "map"
        out.mkdir()
        (out / "reconcile.json").write_text('{"set": []}', encoding="utf-8")
        proc = subprocess.run(ASSEMBLE + [str(frag), "--out", str(out)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert "exists but --reconcile was not passed" in proc.stderr


def test_load_reconcile_rejects_malformed_directives():
    from coyomap.reconcile import ReconcileError, load_reconcile
    for bad, needle in (('{"bogus": []}', "unknown top-level key"),
                        ('{"set": [{"subsystem": "S1"}]}', "missing 'ids'"),
                        ('{"set": [{"ids": ["C1"]}]}', "assigns no field"),
                        ('{"drop_edges": [{"src": "C1", "verb": "x", "dst": "C2", '
                         '"drop_steps": true, "repoint": "C3"}]}', "mutually exclusive")):
        try:
            load_reconcile(bad, "reconcile.json")
            raise AssertionError(f"expected ReconcileError for {bad}")
        except ReconcileError as e:
            assert needle in str(e), str(e)


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


def test_grounding_survives_assemble():
    """The Phase-4 coverage record must reach the committed model.

    `grounding` is written as its own fragment by the Phase-4 reconcile. Left out of the singleton
    merge it was silently DROPPED by the only code path that writes a map, so `validate` then
    reported a fully-grounded map as never challenged — and a re-assemble wiped any hand-edit."""
    from coyomap.model import Grounding, ProjectModel
    frag = ProjectModel(grounding=Grounding(claims_total=150, claims_challenged=40,
                                            claims_refuted=7, note="security first"))
    merged, problems = merge_fragments([("verify.json", frag)])
    assert problems == []
    assert merged.grounding is not None
    assert merged.grounding.claims_total == 150
    assert merged.grounding.claims_challenged == 40
    assert merged.grounding.note == "security first"


def test_conflicting_grounding_records_are_reported():
    from coyomap.model import Grounding, ProjectModel
    a = ProjectModel(grounding=Grounding(claims_total=10))
    b = ProjectModel(grounding=Grounding(claims_total=99))
    _, problems = merge_fragments([("a.json", a), ("b.json", b)])
    assert any("grounding" in p for p in problems)


def test_two_agents_writing_the_same_channel_merge_instead_of_failing_the_build():
    """The live failure: two trace prompts embedded the SAME literal example messaging row, both agents
    wrote it, and `assemble` failed the whole build on `Duplicate messaging channel name(s)`. The lead
    hand-scripted the merge and DROPPED three real publishers, because a hand merge picks a survivor
    where a union keeps what both agents actually found."""
    a = ('{"messaging":[{"name":"jobs","broker":"D1","publishers":["C6","C21"],'
         '"consumers":["C96"],"source":"q.py:1"}]}')
    b = '{"messaging":[{"name":"jobs","publishers":["C45"],"consumers":["C45"],"kind":"job-queue"}]}'
    stats: dict[str, int] = {}
    m, problems = merge_fragments([("a.json", load_fragment(a, "a.json")),
                                   ("b.json", load_fragment(b, "b.json"))], stats)
    assert problems == []                              # no CONFLICT: the second row states no broker
    assert len(m.messaging) == 1
    row = m.messaging[0]
    assert row.publishers == ["C6", "C21", "C45"]      # nothing dropped — the hand merge lost these
    assert row.consumers == ["C96", "C45"]
    assert row.broker == "D1" and row.kind == "job-queue"   # each empty field filled from the sibling
    assert stats["messaging_rows_collapsed"] == 1


def test_two_channels_that_merely_share_a_name_are_NOT_collapsed():
    """Identity is `(name, broker)`, not the name alone. Two rows named `jobs` on brokers `D1` and `D9`
    are two channels, and collapsing them would resolve a real conflict by fragment-filename order.
    They stay separate — and `validate` then blocks on the duplicate name, which is correct: the author
    has to rename one."""
    a = '{"messaging":[{"name":"jobs","broker":"D1","publishers":["C1"],"consumers":["C2"]}]}'
    b = '{"messaging":[{"name":"jobs","broker":"D9","publishers":["C3"],"consumers":["C4"]}]}'
    stats: dict[str, int] = {}
    m, _ = merge_fragments([("a.json", load_fragment(a, "a.json")),
                            ("b.json", load_fragment(b, "b.json"))], stats)
    assert len(m.messaging) == 2, [r.broker for r in m.messaging]
    assert stats.get("messaging_rows_collapsed", 0) == 0


def test_a_conflicting_scalar_is_reported_not_guessed():
    """Filling an EMPTY field from a sibling row is a merge; choosing between two different non-empty
    values is a guess decided by filename order. `merge_fragments` already blocks on a singleton stated
    twice with different values; this follows that precedent."""
    a = '{"messaging":[{"name":"jobs","publishers":["C1"],"consumers":["C2"],"payload":"E1"}]}'
    b = '{"messaging":[{"name":"jobs","publishers":["C3"],"consumers":["C4"],"payload":"E9"}]}'
    m, problems = merge_fragments([("a.json", load_fragment(a, "a.json")),
                                   ("b.json", load_fragment(b, "b.json"))], {})
    assert any("different `payload` values" in p for p in problems), problems
    assert m.messaging[0].publishers == ["C1", "C3"]      # participants still union


def test_merging_does_not_mutate_the_input_fragments():
    """`merge_fragments` extends the FRAGMENTS' own lists into the output, so writing through a
    survivor row would edit the caller's objects — and a second merge of the same parts would then
    produce a different map. `_derive_entity_edges` advertises idempotency as a property of this
    module; the merge must not break it."""
    a = '{"messaging":[{"name":"jobs","broker":"D1","publishers":["C1"],"consumers":["C2"]}]}'
    b = '{"messaging":[{"name":"jobs","publishers":["C3"],"consumers":["C4"]}]}'
    parts = [("a.json", load_fragment(a, "a.json")), ("b.json", load_fragment(b, "b.json"))]
    first, _ = merge_fragments(parts, {})
    pubs_first = list(first.messaging[0].publishers)
    assert parts[0][1].messaging[0].publishers == ["C1"], "the input fragment was mutated"
    second, _ = merge_fragments(parts, {})
    assert second.messaging[0].publishers == pubs_first


# --- the keyed sections: config + observability ---------------------------------------------------
#
# THE LIVE DEFECT. Three harvest slices each saw part of `DATABASE_URL` and each wrote a row for it,
# and nothing deduped `config`, so the reminderrepo map's Config screen answered one question three
# ways at once: 47 rows, 29 distinct keys, 16 keys duplicated — with three contradicting defaults on
# `DATABASE_URL` alone. `observability` carried the same defect smaller (12 rows, 11 signals).
# Neither section has an id to collide on or an anchor to pin, so no other check could see it.


def make_config_fragment(*rows: dict) -> str:
    return json.dumps({"config": list(rows)})


def make_observability_fragment(*rows: dict) -> str:
    return json.dumps({"observability": list(rows)})


def merge_two(a: str, b: str, c: str | None = None) -> tuple[ProjectModel, list[str], dict[str, int],
                                                             list[str]]:
    """Merge two or three fragment bodies, returning (model, problems, stats, notes)."""
    bodies = [x for x in (a, b, c) if x is not None]
    parts = [(f"f{n}.json", load_fragment(body, f"f{n}.json")) for n, body in enumerate(bodies)]
    stats: dict[str, int] = {}
    notes: list[str] = []
    model, problems = merge_fragments(parts, stats, notes)
    return model, problems, stats, notes


DATABASE_URL_SLICES = (
    {"key": "DATABASE_URL", "purpose": "Address of the database.",
     "default": "No default.", "per_env": ""},
    {"key": "DATABASE_URL", "purpose": "Full address of the database.",
     "default": "a local development database on port 5435",
     "per_env": "one address per environment"},
    {"key": "DATABASE_URL", "purpose": "Which database to open.",
     "default": "No default; the deploy builds it.", "per_env": "Yes, one per environment."},
)


def test_three_slices_describing_one_setting_become_one_config_row():
    """The reminderrepo `DATABASE_URL`, verbatim: three rows, three contradicting defaults, all
    three shipped. One key is one setting, so the map must show one row."""
    model, problems, stats, _notes = merge_two(*[make_config_fragment(r)
                                                 for r in DATABASE_URL_SLICES])
    assert problems == [], problems
    assert len(model.config) == 1, [r.default for r in model.config]
    assert stats["config_rows_merged"] == 2


def test_the_merged_cell_states_every_answer_rather_than_picking_one():
    """THE REVIEW FINDING. Keeping "the first row" made the survivor depend on
    `sorted(dir.glob("*.json"))` — codepoint order of fragment FILENAMES — and the map then asserted
    one answer, confidently, with the others gone. That is worse than the defect it replaced: before
    it, a reader saw three answers and could tell something was wrong.

    There is also no better answer to pick. Across the four live maps 191 fields disagree and a
    plurality rule finds a winner on 14, because agents paraphrase and the rest are 1-1-1 ties."""
    model, _problems, _stats, _notes = merge_two(*[make_config_fragment(r)
                                                   for r in DATABASE_URL_SLICES])
    default = model.config[0].default
    assert default.startswith("more than one answer was found: "), default
    for slice_row in DATABASE_URL_SLICES:               # nothing any slice found left the map
        assert slice_row["default"] in default, default


def test_a_field_only_one_slice_answered_is_stated_plainly():
    """Merging ADDS content, and this is the half a reader would otherwise never see: a field only
    one slice filled needs no marker, because nothing disagrees. 31 facts arrive this way across the
    live maps, 6 on reminderrepo and 25 on mcpolis — the live `GEO_APIFY_API_KEY` gains the
    `per_env` the other slice never wrote, while its two different defaults stay unsettled."""
    a = make_config_fragment({"key": "GEO_APIFY_API_KEY", "purpose": "Key for the lookup service.",
                              "default": "Empty. The service is still called, and refuses.",
                              "per_env": ""})
    b = make_config_fragment({"key": "GEO_APIFY_API_KEY", "purpose": "Holds the key.",
                              "default": "`none`",
                              "per_env": "No, both environments share one key."})
    model, _problems, _stats, _notes = merge_two(a, b)
    row = model.config[0]
    assert row.per_env == "No, both environments share one key."     # one answer, stated plainly
    assert "more than one answer" not in row.per_env
    assert "more than one answer" in row.default                     # two answers, marked


def test_the_merged_table_is_the_same_under_every_fragment_order():
    """THE REGRESSION GUARD for the review finding, and the exact attack it used: merge the same
    slices sorted, reversed and shuffled. The old merge produced a different table for 16 of
    reminderrepo's 29 keys, 59 of mcpolis's 98 and 4 of coyomap's 14, and six random shuffles gave
    six different tables. Every field is now computed from the whole group by content, so no
    permutation can move the output — verified on all four live maps at ten orders each.

    The last order leak was subtler than the first: two answers that differ only in SPACING fold to
    one, and keeping the first-seen spelling still let row order decide which spelling shipped. Two
    mcpolis keys moved on exactly that until `_distinct_answers` began keeping the smallest."""
    rows = [*DATABASE_URL_SLICES,
            {"key": "PORT", "purpose": "The  port.", "default": "3001", "per_env": ""},
            {"key": "PORT", "purpose": "The port.", "default": "3000 in production",
             "per_env": "Yes."},
            {"key": "LOG_LEVEL", "purpose": "How much is logged.", "default": "info"}]
    assert len(rows) == 6, "the permutations below index exactly these six rows"
    tables = set()
    for order in (rows, list(reversed(rows)), [rows[i] for i in (3, 0, 5, 2, 1, 4)],
                  [rows[i] for i in (5, 2, 4, 1, 3, 0)], [rows[i] for i in (1, 5, 0, 4, 2, 3)]):
        parts = [(f"f{n}.json", load_fragment(make_config_fragment(r), f"f{n}.json"))
                 for n, r in enumerate(order)]
        model, _ = merge_fragments(parts)
        # NOT sorted before comparing. An earlier version of this test sorted by key, which made it
        # blind to exactly half the bug: every row's CONTENT was settled while the rows themselves
        # still came out in fragment order, and a second reviewer got ten different tables from ten
        # orders on all four live maps. `views` and the viewer render this array in order, so the
        # position is part of the output.
        tables.add(json.dumps([[r.key, r.purpose, r.default, r.per_env] for r in model.config]))
    assert len(tables) == 1, f"{len(tables)} different config tables from 5 fragment orders"
    assert [r.key for r in model.config] == ["DATABASE_URL", "LOG_LEVEL", "PORT"]


def test_contradicting_config_rows_are_reported_but_never_block_the_build():
    """`_merge_duplicate_messaging` makes its contradiction a merge PROBLEM, which fails the
    assemble and writes nothing. The same rule here would have failed THREE of the four live builds
    (16 conflicting keys on reminderrepo, 59 on mcpolis, 4 on coyomap), so the finding rides the
    non-blocking channel instead: a warning naming the key and the fields."""
    a = make_config_fragment({"key": "PORT", "purpose": "The port.", "default": "3001"})
    b = make_config_fragment({"key": "PORT", "purpose": "The port.",
                              "default": "3000 in production and 3001 in staging"})
    model, problems, stats, notes = merge_two(a, b)
    assert problems == [], "a contradiction must not fail the assemble"
    assert len(model.config) == 1
    assert stats["keyed_row_contradictions"] == 1
    assert len(notes) == 1, notes
    assert notes[0].startswith("WARNING:")
    assert "PORT (default)" in notes[0], notes[0]
    assert "purpose" not in notes[0], "only the field that actually disagreed is named"


def test_identical_duplicate_config_rows_merge_with_no_contradiction_reported():
    """An exact duplicate is a tidy-up, not a disagreement — it must not spend a warning.

    Worth pinning even though no live map contains one: across all four, EVERY duplicated key
    disagrees on at least one field (16 · 0 · 59 · 4), so this path is the one the real builds never
    take and a change could break unnoticed."""
    row = {"key": "LOG_LEVEL", "purpose": "How much is logged.", "default": "info"}
    model, problems, stats, notes = merge_two(make_config_fragment(row),
                                              make_config_fragment(dict(row)))
    assert problems == [] and notes == []
    assert len(model.config) == 1
    assert stats["config_rows_merged"] == 1 and stats["keyed_row_contradictions"] == 0


def test_a_reworded_answer_is_not_a_contradiction():
    """Identity and answers both fold whitespace and case, so `Empty` and `empty` are one answer.
    A warning that fired on capitalisation would be the noise that gets the check switched off."""
    model, _problems, stats, notes = merge_two(
        make_config_fragment({"key": "SENTRY_DSN", "purpose": "Where crashes go.", "default": "empty"}),
        make_config_fragment({"key": "SENTRY_DSN", "purpose": "Where  crashes   go.",
                              "default": "Empty"}))
    assert len(model.config) == 1 and notes == []
    assert stats["keyed_row_contradictions"] == 0
    # And the spelling that ships is the smallest, not the first seen — the last place fragment
    # order could decide an answer, which two mcpolis keys were still losing to.
    assert model.config[0].default == "Empty"


def test_two_different_settings_are_never_merged():
    """The negative control: identity is the key, and two keys are two settings."""
    model, _problems, stats, _notes = merge_two(
        make_config_fragment({"key": "PORT", "default": "3001"}),
        make_config_fragment({"key": "HOST", "default": "0.0.0.0"}))
    assert len(model.config) == 2
    assert stats["config_rows_merged"] == 0


def test_two_settings_whose_keys_differ_only_in_case_stay_two_settings():
    """A config key is a case-sensitive IDENTIFIER — an environment variable, a YAML field — so
    `PORT` and `port` are two settings, not one spelled twice. Identity folded case for a while,
    justified as free because no live map holds such a pair (0 of 29 · 0 of 47 · 0 of 98 · 0 of 14).
    That is a measurement about maps that already exist, and what it permitted destroys data: the
    two rows below merged into ONE keyed `PORT` whose purpose, default and per_env all read
    `more than one answer was found: …`, with a warning telling the lead to leave one answer in the
    fragments. The map knew both settings cleanly and would have asserted confusion about one."""
    model, _problems, stats, notes = merge_two(
        make_config_fragment({"key": "PORT", "purpose": "The port the API server listens on.",
                              "default": "3000"}),
        make_config_fragment({"key": "port", "purpose": "The port field of the connection block.",
                              "default": "5432"}))
    assert [r.key for r in model.config] == ["PORT", "port"], [r.key for r in model.config]
    assert [r.default for r in model.config] == ["3000", "5432"]
    assert stats["config_rows_merged"] == 0 and notes == []
    # Whitespace still folds, because a run of spaces in an identifier is a typo, not a distinction.
    spaced, _p, spaced_stats, _n = merge_two(
        make_config_fragment({"key": "MY  KEY", "default": "a"}),
        make_config_fragment({"key": "MY KEY", "per_env": "b"}))
    assert len(spaced.config) == 1 and spaced_stats["config_rows_merged"] == 1
    assert spaced.config[0].default == "a" and spaced.config[0].per_env == "b"


def test_a_config_row_with_no_key_keeps_its_own_place():
    """`_dep_identity` / `_component_identity`'s rule: an unidentifiable row is never folded into a
    neighbour. Two keyless rows are two rows, not one."""
    model, _problems, _stats, _notes = merge_two(
        make_config_fragment({"key": "", "purpose": "Something unnamed."}),
        make_config_fragment({"key": "", "purpose": "Something else unnamed."}))
    assert len(model.config) == 2, [r.purpose for r in model.config]


def test_observability_rows_for_one_signal_merge_the_same_way():
    """The live reminderrepo row: `Container health check` twice, with different `where_emitted`,
    `where_viewed` and `alerts`."""
    a = make_observability_fragment({"signal": "Container health check",
                                     "where_emitted": "The compose healthcheck.",
                                     "where_viewed": "docker ps", "alerts": "None."})
    b = make_observability_fragment({"signal": "Container health check",
                                     "where_emitted": "The API's own /health route.",
                                     "where_viewed": "The deploy dashboard.",
                                     "alerts": "The deploy restarts the container."})
    model, problems, stats, notes = merge_two(a, b)
    assert problems == []
    assert len(model.observability) == 1
    viewed = model.observability[0].where_viewed
    assert "docker ps" in viewed and "The deploy dashboard." in viewed, viewed
    assert stats["observability_rows_merged"] == 1
    assert any("observability signal" in n and "Container health check" in n for n in notes), notes


def test_merging_keyed_rows_does_not_mutate_the_input_fragments():
    """The `_merge_duplicate_messaging` lesson: `merge_fragments` extends the FRAGMENTS' own lists
    into the output, so writing a merged value through one of them would edit the caller's objects
    and make a second merge of the same parts produce a different map."""
    a = make_config_fragment({"key": "DATABASE_URL", "purpose": "The database.", "per_env": ""})
    b = make_config_fragment({"key": "DATABASE_URL", "purpose": "The database.",
                              "per_env": "One per environment."})
    parts = [("a.json", load_fragment(a, "a.json")), ("b.json", load_fragment(b, "b.json"))]
    first, _ = merge_fragments(parts, {})
    assert first.config[0].per_env == "One per environment."
    assert parts[0][1].config[0].per_env == "", "the input fragment was mutated"
    second, _ = merge_fragments(parts, {})
    assert second.config[0].per_env == first.config[0].per_env


def test_every_keyed_section_names_a_real_array_and_a_real_key_field():
    """`_merge_keyed_rows` writes the merged list back with `setattr`, and `ProjectModel` is a plain
    dataclass — so a typo in the section table would create a NEW attribute, leave the real array
    untouched, and disable the merge in silence. The same typo in the key field would make every row
    unidentifiable and merge nothing, equally quietly."""
    hints = get_type_hints(ProjectModel)
    for section in assemble._KEYED_SECTIONS:
        assert section.attr in hints, f"{section.attr} is not a ProjectModel field"
        assert isinstance(getattr(ProjectModel(), section.attr), list), \
            f"{section.attr} is not an array"
        row_cls = get_args(hints[section.attr])[0]          # list[ConfigRow] -> ConfigRow
        names = {f.name for f in dataclass_fields(row_cls)}
        assert section.key_field in names, \
            f"{section.attr} rows have no '{section.key_field}' field — the merge would see no key"
        # `_distinct_answers` reads STRING answers and skips anything else, so a non-string field
        # added to one of these rows would merge to empty in silence. Two all-string row classes is
        # the assumption the merge rests on; say so here rather than discovering it in a map.
        for f in dataclass_fields(row_cls):
            assert get_type_hints(row_cls)[f.name] is str, (
                f"{row_cls.__name__}.{f.name} is not a str — `_distinct_answers` would drop it; "
                f"teach the merge how to combine that type before adding it")


def test_the_readability_walk_still_does_not_read_config_or_observability():
    """A TRIPWIRE on another module, deliberately. Stating every answer in a merged cell is only
    affordable because `prose.iter_prose_fields` does not walk these two sections — measured, the
    same answers under an unregistered extras heading take mcpolis from 39 readability findings to
    171. Nothing in `assemble` would notice if that walk were widened, so the cost of the merge
    would silently land on the advisory and on the audit's paid reading fan-out.

    If this fails, the widening may well be right — but re-cost the decision in `_UNSETTLED_LEAD`'s
    comment first, rather than deleting this test."""
    m = ProjectModel(
        config=[ConfigRow(key="DATABASE_URL", purpose="A sentence only this row holds.",
                                   default="Another sentence only this row holds.",
                                   per_env="A third sentence only this row holds.")],
        observability=[ObservabilityRow(signal="Container health check",
                                                 where_emitted="A fourth unique sentence.",
                                                 where_viewed="A fifth unique sentence.",
                                                 alerts="A sixth unique sentence.")])
    seen = [f"{where} :: {text}" for where, text in prose.iter_prose_fields(m)]
    for unique in ("A sentence only this row holds.", "Another sentence only this row holds.",
                   "A third sentence only this row holds.", "A fourth unique sentence.",
                   "A fifth unique sentence.", "A sixth unique sentence."):
        assert not any(unique in s for s in seen), (
            f"the readability walk now reads {unique!r} — config/observability prose has entered "
            f"`iter_prose_fields`, so a merged cell that states every answer is no longer free. "
            f"Re-cost the joining decision (see `_UNSETTLED_LEAD` in assemble.py) before changing "
            f"this test.")


def test_the_config_merge_and_its_contradictions_reach_the_operator():
    """End to end through the real CLI: the warning names the key on stderr and the digest carries
    the counts, so a build whose warning has scrolled away can still see what the merge chose."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "header.json").write_text(make_header_fragment())
        (d / "a.json").write_text(make_config_fragment(
            {"key": "DATABASE_URL", "purpose": "The database.", "default": "No default."}))
        (d / "b.json").write_text(make_config_fragment(
            {"key": "DATABASE_URL", "purpose": "The database.", "default": "Port 5435 locally."}))
        out = d / "out"
        proc = subprocess.run(ASSEMBLE + [str(d / "header.json"), str(d / "a.json"),
                                          str(d / "b.json"), "--out", str(out)],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr        # reports, never blocks
        assert "DATABASE_URL (default)" in proc.stderr, proc.stderr
        assert "config rows merged 1" in proc.stdout, proc.stdout
        assert "keys left unsettled (every answer kept) 1" in proc.stdout, proc.stdout
        written = json.loads((out / "project-map.json").read_text())
        assert len(written["config"]) == 1, written["config"]
        # The written MAP carries the finding too, which neither the warning nor the digest does:
        # both answers are in the cell a reader meets, so nothing downstream has to be told.
        assert "No default." in written["config"][0]["default"], written["config"][0]
        assert "Port 5435 locally." in written["config"][0]["default"], written["config"][0]


# --- the fragment-reading loop (`load_fragment_paths`) --------------------------------------------
#
# Extracted from `main()` so `reconcile` reads fragments through the same code. It had NO coverage:
# no test for a missing path, a malformed fragment, an unreadable path, or the verdicts skip — the
# whole error half of the tool's only write path. An independent review flagged that "945 passed"
# said nothing about the loop that moved.


def make_fragment_file(dir_path: Path, name: str, body: dict) -> Path:
    p = dir_path / name
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def test_every_path_is_attempted_so_one_bad_fragment_does_not_hide_the_next():
    from coyomap.assemble import load_fragment_paths
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        good = make_fragment_file(d, "good.json", {"components": [
            {"id": "C1", "name": "A", "source": "a.py:1"}]})
        broken = d / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        a_dir = d / "adir.json"
        a_dir.mkdir()
        missing = d / "missing.json"
        loaded = load_fragment_paths([broken, a_dir, missing, good])
        parts, errors = loaded.parts, loaded.errors
        # the good one still loaded, and all three failures are reported — not just the first
        assert [label for label, _ in parts] == ["good.json"]
        assert len(errors) == 3, errors
        assert any("broken.json" in e for e in errors)
        assert any("adir.json" in e and "cannot read" in e for e in errors)
        assert any("missing.json" in e and "not found" in e for e in errors)


def test_a_verdicts_file_swept_into_the_glob_is_skipped_with_a_note():
    # was: `_is_verdicts_file` keyed on "shares no ProjectModel field", but `grounding` IS one, so
    # it was unconditionally False — the skip never fired and the build died on a schema error.
    from coyomap.assemble import load_fragment_paths
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        good = make_fragment_file(d, "good.json", {"components": [
            {"id": "C1", "name": "A", "source": "a.py:1"}]})
        verdicts = make_fragment_file(d, "verdicts-security.json", {"grounding": [
            {"claim": "C1 calls C2", "grounded": False, "evidence": "a.py:1"}]})
        loaded = load_fragment_paths([verdicts, good])
        parts, notes, errors = loaded.parts, loaded.notes, loaded.errors
        assert errors == []
        assert [label for label, _ in parts] == ["good.json"]
        assert len(notes) == 1 and "verdicts-security.json" in notes[0]


def test_the_grounding_fragment_is_NOT_mistaken_for_a_verdicts_file():
    # `grounding write` emits {"grounding": {record}} into build-fragments/ — an object, not a list.
    # Skipping it would silently drop the map's grounding record.
    from coyomap.assemble import load_fragment_paths
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        frag = make_fragment_file(d, "grounding.json", {"grounding": {
            "claims_total": 10, "claims_challenged": 10, "claims_confirmed": 9,
            "claims_refuted": 1, "claims_unverifiable": 0}})
        loaded = load_fragment_paths([frag])
        parts, notes, errors = loaded.parts, loaded.notes, loaded.errors
        assert errors == [] and notes == []
        assert [label for label, _ in parts] == ["grounding.json"]
        record = parts[0][1].grounding
        assert record is not None and record.claims_total == 10


def test_assemble_fails_the_build_and_writes_nothing_when_a_fragment_is_bad():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        make_fragment_file(d, "good.json", {"components": [
            {"id": "C1", "name": "A", "source": "a.py:1"}]})
        (d / "broken.json").write_text("{not json", encoding="utf-8")
        out = d / "out"
        r = subprocess.run([*ASSEMBLE, str(d / "broken.json"), str(d / "good.json"),
                            "--out", str(out)], capture_output=True, text=True)
        assert r.returncode == 1
        assert "ASSEMBLY FAILED" in r.stderr
        assert not (out / "project-map.json").exists()


def test_a_draft_fragment_is_skipped_by_name():
    """The harvest contract promised the `.draft.json` suffix "keeps a half-written file out of the
    assemble glob". It did not: `*.draft.json` matches `*.json` and nothing looked at the name."""
    from coyomap.assemble import load_fragment_paths
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        good = make_fragment_file(d, "h-a.json", {"components": [
            {"id": "C1", "name": "A", "source": "a.py:1"}]})
        draft = d / "h-b.json.draft.json"
        draft.write_text('{"components": [{"id": "C2", "name":', encoding="utf-8")  # truncated
        loaded = load_fragment_paths([draft, good])
        parts, notes, errors = loaded.parts, loaded.notes, loaded.errors
        assert errors == []
        assert [label for label, _ in parts] == ["h-a.json"]
        assert len(notes) == 1 and "draft" in notes[0]


# ── one section per heading ──────────────────────────────────────────────────────────────────────

def make_extras_fragment(name: str, heading: str, body: str) -> tuple[str, ProjectModel]:
    m = ProjectModel(title="T", goal="g")
    m.extras.append(ExtraSection(heading=heading, body=body))
    return (name, m)


def test_same_named_extras_sections_are_merged_into_one():
    """A live map shipped five `Entry-point coverage` sections, three `Balance exceptions` and two
    `Coverage exceptions` — one per contributing fragment, simply concatenated."""
    from coyomap.assemble import merge_fragments
    out, problems = merge_fragments([
        make_extras_fragment("a.json", "Entry-point coverage", "- first"),
        make_extras_fragment("b.json", "Entry-point coverage", "- second"),
        make_extras_fragment("c.json", "Balance exceptions", "- other"),
    ])
    headings = [e.heading for e in out.extras]
    assert headings.count("Entry-point coverage") == 1, headings
    body = next(e.body for e in out.extras if e.heading == "Entry-point coverage")
    assert "- first" in body and "- second" in body, "no recorded line may be dropped"
    assert not problems


def test_merging_headings_makes_record_replace_reach_every_line():
    """The write path this actually fixes: `record.append_line` resolves a heading with the FIRST
    matching section, so with the sections split a `--replace` aimed at a line in a later one
    matched nothing and reported "nothing replaced"."""
    from coyomap.assemble import merge_fragments
    from coyomap.record import append_line
    out, _ = merge_fragments([
        make_extras_fragment("a.json", "Balance exceptions", "- alpha: original why"),
        make_extras_fragment("b.json", "Balance exceptions", "- beta: original why"),
    ])
    # the prefix is matched AFTER the bullet is stripped, so it carries no "- "
    changed, message = append_line(out, "Balance exceptions", "- beta: corrected why",
                                   replace_prefix="beta:")
    assert changed, message
    body = next(e.body for e in out.extras if e.heading == "Balance exceptions")
    assert "corrected why" in body and "beta: original why" not in body


def test_a_heading_written_in_another_case_is_the_same_section():
    """Matching reuses `record._resolve_heading` rather than a third implementation, so it is
    case- and outer-space-tolerant (it does NOT normalise interior spacing — that would silently
    accept a heading no check reads)."""
    from coyomap.assemble import merge_fragments
    out, _ = merge_fragments([
        make_extras_fragment("a.json", "Coverage exceptions", "- one"),
        make_extras_fragment("b.json", "  coverage exceptions  ", "- two"),
    ])
    covers = [e for e in out.extras if e.heading.strip().lower() == "coverage exceptions"]
    assert len(covers) == 1, [e.heading for e in out.extras]
    assert covers[0].heading == "Coverage exceptions", "the canonical spelling wins"
    assert "- one" in covers[0].body and "- two" in covers[0].body


def test_the_keep_edges_count_reaches_the_assemble_digest():
    """H1 shipped with no test: `keep_edges` removed 51 edges on a real map and the digest said
    nothing, reproducing the exact silence the directive was added to stop."""
    from coyomap.assemble import _assemble_digest
    from coyomap.model import ProjectModel
    line = _assemble_digest(ProjectModel(title="T", goal="g"), {},
                            {"duplicate_edges_resolved": 51})
    assert "keep_edges 51" in line, line
    # and zero-suppressed like every other op
    assert "keep_edges" not in _assemble_digest(ProjectModel(title="T", goal="g"), {}, {})


def test_assemble_accepts_a_bare_fragment_directory():
    """A directory is what an operator types first, and `assemble` — printed far more often in
    method.md than `reconcile` — died on the reader's raw `[Errno 21] Is a directory`. The expansion
    lives in the shared loader, so both commands agree on what an argument means."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "frags"
        d.mkdir()
        (d / "a.json").write_text(json.dumps({
            "components": [{"id": "C1", "name": "A", "purpose": "p", "source": "a.py:1"}]}),
            encoding="utf-8")
        (d / "b.json").write_text(json.dumps({
            "components": [{"id": "C2", "name": "B", "purpose": "p", "source": "b.py:1"}]}),
            encoding="utf-8")
        _by_dir_load = load_fragment_paths([d])
        by_dir, notes, errors = (_by_dir_load.parts, _by_dir_load.notes, _by_dir_load.errors)
        by_glob = load_fragment_paths(sorted(d.glob("*.json"))).parts
        assert not errors, errors
        assert [name for name, _ in by_dir] == [name for name, _ in by_glob] == ["a.json", "b.json"]
        assert any("expanded to 2 fragment(s)" in n for n in notes), notes


def test_a_directory_named_json_still_raises_from_assemble():
    """`inner.json/` swept up by the caller's own glob must keep erroring: silently dropping it
    would make the glob form and the bare-directory form disagree about the file set while both
    exit 0."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "frags"
        d.mkdir()
        (d / "a.json").write_text(json.dumps({"components": []}), encoding="utf-8")
        (d / "inner.json").mkdir()
        errors = load_fragment_paths(sorted(d.glob("*.json"))).errors
        assert any("Is a directory" in e for e in errors), errors


# ── entry-point ids: minted by assemble, never authored (Step 1 of plan/60-capabilities) ──────────

def make_entry_point_slice(cid: str, own_route: str) -> str:
    """One harvest slice. Every slice records the SHARED `/health` route it walked past — same file,
    same line, same owner, because it IS one surface — plus one route of its own. The
    duplicate-surface case nothing collapsed before, entry points being the one element family
    assemble simply concatenated."""
    return json.dumps({
        "components": [{"id": cid, "name": cid, "purpose": "p", "source": f"{cid}.py:1"}],
        "entry_points": [
            {"kind": "HTTP route", "trigger": "GET /health", "source": "app/health.py:10",
             "component": "C1", "activation": "external"},
            {"kind": "HTTP route", "trigger": f"GET {own_route}", "source": f"{cid}.py:5",
             "component": cid, "activation": "external"},
        ],
    })


def test_entry_point_ids_are_minted_and_duplicate_surfaces_collapse():
    """Ids are assigned by assemble from content, and the same surface harvested twice becomes ONE
    row — otherwise the completeness check would count a duplicated route as two unclaimed surfaces."""
    with tempfile.TemporaryDirectory() as td:
        a, b = Path(td) / "a.json", Path(td) / "b.json"
        a.write_text(make_entry_point_slice("C1", "/orders"), encoding="utf-8")
        b.write_text(make_entry_point_slice("C2", "/users"), encoding="utf-8")
        out = Path(td) / "map"
        proc = subprocess.run(ASSEMBLE + [str(a), str(b), "--out", str(out)],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        m = load_model((out / "project-map.json").read_text(encoding="utf-8"))
        triggers = [ep.trigger for ep in m.entry_points]
        assert triggers.count("GET /health") == 1, triggers      # collapsed, not concatenated
        assert [ep.id for ep in m.entry_points] == ["EP1", "EP2", "EP3"], triggers
        assert all(ep.id for ep in m.entry_points)


def test_entry_points_without_a_source_are_never_merged():
    """No anchor → not identifiable. Merging on trigger text alone would delete a real surface, so
    an unanchored row keeps its own id (the same rule `_dep_identity` uses for a nameless dep)."""
    with tempfile.TemporaryDirectory() as td:
        frag = Path(td) / "f.json"
        frag.write_text(json.dumps({
            "components": [{"id": "C1", "name": "A", "purpose": "p", "source": "a.py:1"}],
            "entry_points": [{"kind": "CLI", "trigger": "run", "component": "C1"},
                             {"kind": "CLI", "trigger": "run", "component": "C1"}],
        }), encoding="utf-8")
        out = Path(td) / "map"
        proc = subprocess.run(ASSEMBLE + [str(frag), "--out", str(out)],
                             capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        m = load_model((out / "project-map.json").read_text(encoding="utf-8"))
        assert [ep.id for ep in m.entry_points] == ["EP1", "EP2"]


def make_capability_fragment() -> str:
    """A behavioral fragment plus the T4 rows a synthesis-time reconcile will link it to."""
    return json.dumps({
        "title": "Demo", "goal": "g",
        "capabilities": [{"id": "CAP1", "name": "Ordering", "happy_path": "expected"},
                         {"id": "CAP2", "name": "Ops", "happy_path": "excluded"}],
        "use_cases": [{"id": "UC1", "name": "Place an order"},
                      {"id": "UC2", "name": "Rotate the keys"}],
        "components": [{"id": "C1", "name": "A", "purpose": "p", "source": "a.py:1"}],
        "entry_points": [{"kind": "HTTP route", "trigger": "POST /orders",
                          "source": "a.py:9", "component": "C1", "activation": "external"}],
    })


def test_reconcile_sets_capability_and_entry_points_and_survives_reassemble():
    """The authoring path for both new fields. Neither can be written in the behavioral fragment:
    `CAPn` is assigned at synthesis and `EPn` does not exist until assemble mints it, so reconcile
    is the only mechanism — and it must re-apply on every assemble, like the other set fields."""
    rec = {"set": [{"ids": ["UC1"], "capability": "CAP1", "entry_points": ["EP1"]},
                   {"ids": ["UC2"], "capability": "CAP2"}]}
    with tempfile.TemporaryDirectory() as td:
        frag = Path(td) / "frag.json"
        frag.write_text(make_capability_fragment(), encoding="utf-8")
        rp = Path(td) / "reconcile.json"
        rp.write_text(json.dumps(rec), encoding="utf-8")
        out = Path(td) / "map"
        for _ in range(2):                       # re-assemble: the assignment must not wash out
            proc = subprocess.run(ASSEMBLE + [str(frag), "--out", str(out), "--reconcile", str(rp)],
                                  capture_output=True, text=True)
            assert proc.returncode == 0, proc.stderr
            m = load_model((out / "project-map.json").read_text(encoding="utf-8"))
            by_id = {u.id: u for u in m.use_cases}
            assert by_id["UC1"].capability == "CAP1"
            assert by_id["UC1"].entry_points == ["EP1"]
            assert by_id["UC2"].capability == "CAP2"
            assert by_id["UC2"].entry_points == []


def test_reconcile_rejects_an_unknown_capability_or_entry_point():
    """A typo must fail loudly at apply time. The EP case is the one that bites: ids are minted
    from fragment order, so a stale reconcile file silently pointing at the wrong surface would
    otherwise mis-claim a front door."""
    with tempfile.TemporaryDirectory() as td:
        frag = Path(td) / "frag.json"
        frag.write_text(make_capability_fragment(), encoding="utf-8")
        out = Path(td) / "map"
        for bad, needle in (({"ids": ["UC1"], "capability": "CAP9"}, "not a defined capability"),
                            ({"ids": ["UC1"], "entry_points": ["EP7"]}, "unknown entry point")):
            rp = Path(td) / "reconcile.json"
            rp.write_text(json.dumps({"set": [bad]}), encoding="utf-8")
            proc = subprocess.run(ASSEMBLE + [str(frag), "--out", str(out), "--reconcile", str(rp)],
                                  capture_output=True, text=True)
            assert proc.returncode != 0, proc.stdout
            assert needle in (proc.stdout + proc.stderr), proc.stdout + proc.stderr


def test_reconcile_refuses_capability_on_a_non_use_case():
    """`capability` targets a use case, exactly as `subsystem` targets a component."""
    with tempfile.TemporaryDirectory() as td:
        frag = Path(td) / "frag.json"
        frag.write_text(make_capability_fragment(), encoding="utf-8")
        rp = Path(td) / "reconcile.json"
        rp.write_text(json.dumps({"set": [{"ids": ["C1"], "capability": "CAP1"}]}), encoding="utf-8")
        out = Path(td) / "map"
        proc = subprocess.run(ASSEMBLE + [str(frag), "--out", str(out), "--reconcile", str(rp)],
                              capture_output=True, text=True)
        assert proc.returncode != 0, proc.stdout
        assert "can only be set on a use case" in (proc.stdout + proc.stderr)


def test_two_surfaces_in_one_file_are_never_merged_away():
    """The dedup key must keep the LINE, and the owner and kind with it.

    The first revision keyed on `strip_anchor(source)`, which drops the line — so identity was
    really `(file, trigger)` and any two rows anywhere in one router file with the same trigger text
    collapsed, silently deleting a real surface along with its component, kind and activation. A
    deleted row can never be reported as unclaimed, never appears under "Triggered by", and never
    reaches `--emit-unclaimed`. Over-merging is the dangerous direction here, so the key is
    deliberately conservative."""
    with tempfile.TemporaryDirectory() as td:
        frag = Path(td) / "f.json"
        frag.write_text(json.dumps({
            "components": [{"id": "C1", "name": "A", "purpose": "p", "source": "a.py:1"},
                           {"id": "C2", "name": "B", "purpose": "p", "source": "b.py:1"}],
            "entry_points": [
                {"kind": "HTTP route", "trigger": "POST /jobs", "source": "routes.py:40",
                 "component": "C1", "activation": "external"},
                # same file, same trigger text — a DIFFERENT line, owner, kind and activation
                {"kind": "cron job", "trigger": "POST /jobs", "source": "routes.py:99",
                 "component": "C2", "activation": "self"},
            ],
        }), encoding="utf-8")
        out = Path(td) / "map"
        proc = subprocess.run(ASSEMBLE + [str(frag), "--out", str(out)],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        m = load_model((out / "project-map.json").read_text(encoding="utf-8"))
        assert len(m.entry_points) == 2, [(e.kind, e.source) for e in m.entry_points]
        assert {e.activation for e in m.entry_points} == {"external", "self"}


def test_entry_point_ids_do_not_depend_on_fragment_order():
    """Ids are numbered by CONTENT, so the same surfaces get the same ids however the fragments are
    passed in.

    Numbering in first-occurrence order made the ids depend on argument order — and because
    `use_case.entry_points` is authored separately (via reconcile, against a previous assemble's
    ids), swapping two fragments silently re-pointed a use case at a different front door. Measured
    before the fix: `POST /orders` and `DELETE /admin/wipe-database` traded ids, the use case
    claimed the wrong one, and validate resolved it happily."""
    a = json.dumps({"components": [{"id": "C1", "name": "A", "purpose": "p", "source": "a.py:1"}],
                    "entry_points": [{"kind": "HTTP route", "trigger": "POST /orders",
                                      "source": "orders.py:9", "component": "C1",
                                      "activation": "external"}]})
    b = json.dumps({"components": [{"id": "C2", "name": "B", "purpose": "p", "source": "b.py:1"}],
                    "entry_points": [{"kind": "HTTP route", "trigger": "DELETE /admin/wipe",
                                      "source": "admin.py:3", "component": "C2",
                                      "activation": "external"}]})
    def ids_for(order: list[str]) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.json").write_text(a, encoding="utf-8")
            (Path(td) / "b.json").write_text(b, encoding="utf-8")
            out = Path(td) / "map"
            proc = subprocess.run(
                ASSEMBLE + [str(Path(td) / f) for f in order] + ["--out", str(out)],
                capture_output=True, text=True)
            assert proc.returncode == 0, proc.stderr
            m = load_model((out / "project-map.json").read_text(encoding="utf-8"))
            return {ep.id: ep.trigger for ep in m.entry_points}
    assert ids_for(["a.json", "b.json"]) == ids_for(["b.json", "a.json"])


# --- the digest reports EVERY mutation counter (retro 2026-08-14) ---------------------------------
# Three of the eight counters were computed and printed nowhere, so a rule merge and an entry-point
# renumber — both of which move ids other artifacts already reference — showed `ops: none`. The digest
# is a table now; these tests pin the table against the code that writes the counters, statically, so
# a new counter cannot be added without a label.

def _stats_keys_written(module_name: str, dict_name: str) -> set[str]:
    """Every constant key assigned into `<dict_name>[...]` in a module's source, read with `ast`.

    Static, not runtime: a runtime check only sees the counters the fixture happens to trigger, which
    is exactly how three of them stayed invisible through 1440 passing tests."""
    import ast
    import importlib

    src = Path(importlib.import_module(module_name).__file__ or "").read_text(encoding="utf-8")
    found: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name) and target.value.id == dict_name
                    and isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str)):
                found.add(target.slice.value)
    return found


def test_every_assemble_stats_counter_has_a_digest_label():
    written = _stats_keys_written("coyomap.assemble", "stats")
    labelled = {k for k, _ in assemble._STATS_LABELS}
    assert written <= labelled, f"counter(s) computed but never printed: {sorted(written - labelled)}"
    assert labelled <= written, f"label(s) for a counter nothing writes: {sorted(labelled - written)}"


def test_every_reconcile_stats_counter_has_a_digest_label_or_a_custom_renderer():
    written = _stats_keys_written("coyomap.reconcile", "stats")
    accounted = {k for k, _ in assemble._REC_STATS_LABELS} | set(assemble._REC_STATS_CUSTOM)
    assert written <= accounted, f"reconcile counter(s) never printed: {sorted(written - accounted)}"
    assert accounted <= written, f"label(s) for a counter nothing writes: {sorted(accounted - written)}"


def test_digest_labels_are_unique_and_ordered_deterministically():
    keys = [k for k, _ in assemble._STATS_LABELS]
    labels = [lab for _, lab in assemble._STATS_LABELS]
    assert len(keys) == len(set(keys)), "duplicate stats key in the digest table"
    assert len(labels) == len(set(labels)), "two counters would print the same phrase"


def make_rule_fragment(frag_id: str, rid: str, statement: str, where: str) -> str:
    return json.dumps({"rules": [{"id": rid, "name": statement[:20], "statement": statement,
                                  "sites": [{"where": where}], "confidence": "verified"}]})


def test_a_rule_merge_is_named_in_the_digest():
    # Two fragments stating ONE rule at one site merge into one row. Before the table the count was
    # computed into `stats` and printed nowhere, so this collapse was invisible.
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "header.json").write_text(make_header_fragment())
        (d / "r1.json").write_text(make_rule_fragment("r1", "BR1", "A token is checked", "a.py:1"))
        (d / "r2.json").write_text(make_rule_fragment("r2", "BR9", "A token is checked", "a.py:1"))
        out = subprocess.run(ASSEMBLE + [str(d / "header.json"), str(d / "r1.json"),
                                         str(d / "r2.json"), "--out", str(d)],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert "dup-rules collapsed 1" in out.stdout, out.stdout


def test_a_dep_merge_is_named_in_the_digest():
    # `_merge_duplicate_deps` RE-POINTS every C→D edge onto the survivor, so a silent merge moves the
    # graph under a reader. It used to return None and reach no counter at all.
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "header.json").write_text(make_header_fragment())
        (d / "a.json").write_text(json.dumps({"deps": [{"id": "D1", "name": "redis", "kind": "library"}]}))
        (d / "b.json").write_text(json.dumps({"deps": [{"id": "D7", "name": "redis", "kind": "library"}]}))
        out = subprocess.run(ASSEMBLE + [str(d / "header.json"), str(d / "a.json"), str(d / "b.json"),
                                         "--out", str(d)], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert "deps merged 1" in out.stdout, out.stdout


def test_a_clean_assemble_still_says_ops_none():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "header.json").write_text(make_header_fragment())
        (d / "h.json").write_text(make_harvest_fragment())
        out = subprocess.run(ASSEMBLE + [str(d / "header.json"), str(d / "h.json"), "--out", str(d)],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert "ops: none" in out.stdout, out.stdout


# --- the loader's result is NAMED, not positional (retro 2026-08-14) ------------------------------
# `load_fragment_paths` returned `tuple[list[parts], list[str], list[str]]` and a caller unpacked the
# two same-typed lists the wrong way round: `notes` (files deliberately skipped) landed in the
# variable checked as fatal, and `errors` (files that failed to load) were assigned to `_` and
# dropped. Nothing could catch it — three positional lists type-check in any order, and the swap is
# invisible whenever both are empty, which is every test that builds well-formed fragments.
# Re-introducing the bug and running the whole suite: 1914 passed.

def test_the_loader_result_cannot_be_unpacked_positionally():
    """The fix is that the mistake is UNWRITABLE, not that it is tested for. A NamedTuple would have
    left it writable, so this pins that the result is a plain dataclass."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "h.json").write_text(make_header_fragment(), encoding="utf-8")
        loaded = load_fragment_paths([d / "h.json"])
        try:
            _a, _b, _c = loaded            # type: ignore[misc]
        except TypeError:
            pass
        else:
            raise AssertionError("the result is still unpackable — a swap stays writable")


def test_notes_and_errors_are_reachable_only_by_name_and_mean_different_things():
    """A NOTE is a file deliberately skipped and is advisory; an ERROR is a file that should have
    loaded and did not, and is fatal. A caller that confuses them either refuses work `assemble`
    accepts, or reasons about a fragment set that is missing pieces."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "h.json").write_text(make_header_fragment(), encoding="utf-8")
        (d / "half.draft.json").write_text('{"rules": []}', encoding="utf-8")
        loaded = load_fragment_paths(sorted(d.glob("*.json")))
        assert loaded.errors == [], loaded.errors
        assert any("draft" in n for n in loaded.notes), loaded.notes
        assert len(loaded.parts) == 1

        (d / "broken.json").write_text('{"extras": "not a list"}', encoding="utf-8")
        loaded = load_fragment_paths(sorted(d.glob("*.json")))
        assert loaded.errors and any("extras" in e for e in loaded.errors), loaded.errors
        assert any("draft" in n for n in loaded.notes), "a note must not be reclassified as an error"


# --- stream ordering under a pipe (retro 2026-08-18, finding 5) -------------------

def test_failure_survives_a_tail_because_stdout_is_line_buffered():
    """`assemble 2>&1 | tail -N` must keep the FAILURE, not the harmless notes.

    Piped stdout is block-buffered and flushes at exit; stderr is not. So a run that prints
    `note:` lines on stdout and `ERROR:` / `ASSEMBLY FAILED` on stderr comes out of the pipe with
    the failure at the HEAD and the notes at the TAIL. A live build read `2>&1 | tail -2` three
    times, saw two reassuring `note:` lines each time, and went on reading a stale map for 16
    turns — losing a whole round of prose fixes with it, which only surfaced when the next
    successful assemble dropped the long-sentence count 76 -> 53.

    The CLI entry sets `line_buffering=True` so both streams interleave in PROGRAM order. This
    test has to go through a real pipe: called in-process, the bug does not exist. The fixture
    must emit at least one stdout note before the failure, or there is nothing to be re-ordered
    ahead of and the test passes with the fix removed.
    """
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "h.json").write_text(make_header_fragment(), encoding="utf-8")
        (d / "a.json").write_text(make_harvest_fragment(), encoding="utf-8")
        # The SAME edge at the same call site twice -> a `note:` on stdout before the failure.
        (d / "t.json").write_text(json.dumps({"edges": [
            {"src": "C1", "verb": "uses", "dst": "D1", "why": "query", "where": "src/a.py:3"},
            {"src": "C1", "verb": "uses", "dst": "D1", "why": "query", "where": "src/a.py:3"},
        ]}), encoding="utf-8")
        # A well-formed directive naming an id no fragment defines — the shape that aborted a
        # live build, and the one a `set` typo produces.
        (d / "reconcile.json").write_text(
            json.dumps({"set": [{"ids": ["BR9999"], "block": "BLK1"}]}), encoding="utf-8")

        # `2>&1 | tail -2`, the exact shell the build used.
        merged = subprocess.run(
            f"{sys.executable} -m coyomap.cli assemble {d}/h.json {d}/a.json {d}/t.json "
            f"--out {d}/out --reconcile {d}/reconcile.json 2>&1 | tail -2",
            shell=True, capture_output=True, text=True).stdout
        lines = [ln for ln in merged.splitlines() if ln.strip()]

        # Program order is: note -> ERROR -> ASSEMBLY FAILED. So the last two lines ARE the two
        # stderr lines. Without line buffering they arrive first and the note is what survives.
        assert len(lines) == 2, merged
        assert "BR9999" in lines[0], (
            "the directive that failed fell out of `tail -2`; stdout is buffering behind "
            "stderr again:\n" + merged)
        assert "ASSEMBLY FAILED" in lines[1], merged
        assert not (d / "out" / "project-map.json").exists(), "a failed assemble wrote a map"


def test_a_duplicate_id_inside_one_fragment_is_a_merge_problem():
    """The help promises a refusal; two rows with one id in ONE file assembled to a map carrying
    both, exit 0, and only `validate` caught it downstream."""
    from coyomap.model import Component
    frag = ProjectModel()
    frag.components = [Component(id="C1", name="A", purpose="a"), Component(id="C1", name="B", purpose="b")]
    _model, problems = merge_fragments([("h-one.json", frag)])
    assert any("defined twice inside h-one.json" in p for p in problems), problems


def test_a_recorded_correction_into_a_stray_file_is_refused_on_replay_too():
    """The guard in `fix apply-drift` stops a new stray correction; a stray recorded BEFORE the
    guard existed sits in `reconcile.json` and would be re-applied on every assemble."""
    import subprocess, tempfile
    from coyomap.model import FORMAT
    frag = {"format": FORMAT, "title": "t", "goal": "g",
            "components": [{"id": "C1", "name": "A", "purpose": "a", "source": "a.py:1", "files": ["a.py"]},
                           {"id": "C2", "name": "B", "purpose": "b", "source": "b.py:1", "files": ["b.py"]}],
            "edges": [{"src": "C1", "verb": "reads", "dst": "C2", "where": "a.py:10"}]}
    with tempfile.TemporaryDirectory() as td:
        fp, rp, out = Path(td) / "frag.json", Path(td) / "reconcile.json", Path(td) / "map"
        fp.write_text(json.dumps(frag), encoding="utf-8")
        rp.write_text(json.dumps({"set_anchors": [{"claim": "C1 reads C2", "corrected": "z.py:3"}]}),
                      encoding="utf-8")
        proc = subprocess.run(ASSEMBLE + [str(fp), "--out", str(out), "--reconcile", str(rp)],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        m = json.loads((out / "project-map.json").read_text(encoding="utf-8"))
        assert m["edges"][0]["where"] == "a.py:10", m["edges"][0]
        assert "REFUSED" in proc.stdout + proc.stderr


# --- the map is written whole or not at all (retro 2026-09-30, finding 32) -------------------------
# `assemble` truncated and rewrote project-map.json in place, so an agent reading it mid-assemble
# could open half a file; the lead handed its rules and tests agents a copy instead, and the copy
# predated the gap-fill (121 of 143 gap-fill edges missing).

def test_a_reader_holding_the_old_map_keeps_reading_the_old_map_whole():
    """A rename leaves an open reader on the file it opened; an in-place rewrite truncates it under
    the reader. The open handle is the observable difference."""
    with tempfile.TemporaryDirectory() as td:
        proc, out = _assemble_with_reconcile(td, None)
        assert proc.returncode == 0, proc.stderr
        path = out / "project-map.json"
        before = path.read_text(encoding="utf-8")
        with path.open(encoding="utf-8") as held:
            proc, _ = _assemble_with_reconcile(td, {"set": [{"ids": ["C1"], "subsystem": "S1"}]})
            assert proc.returncode == 0, proc.stderr
            assert held.read() == before, "the reader's file changed under it"
        assert path.read_text(encoding="utf-8") != before
        assert not [p.name for p in out.iterdir() if p.name.endswith(".tmp")], "a temp file was left"
