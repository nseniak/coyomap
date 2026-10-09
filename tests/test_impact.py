"""Impact engine (M1) — pure-core units + golden git fixtures.

Golden fixtures use a REAL temp git repo (no patching), mirroring test_diff_serve.py: a pinned map
over a small Python file, then the named diffs from the design doc — body edit (symbol rung),
anchor-line edit (line rung), committed rename+edit, staged worktree rename, a cross-commit range
where the pin is NOT an endpoint (identical edits cancel; differing edits hit), moved-but-unchanged
(anchor drift, not a change), file deletion, and an untracked file claimed by territory.
Explicit make_* builders, no fixtures/classes. Design: internal/docs/impact-and-update-design.md.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from coyomap.impact_git import WORKTREE, compute_impact, diff_changes, rename_map, u0_diff
from coyomap.impact_lib import (
    AnchorRef,
    FileFrame,
    Hunk,
    ParsedDiff,
    anchor_index,
    dir_anchors_for,
    enclosing_extent,
    frame_from_two_diffs,
    parse_u0,
    resolve_hits,
)
from coyomap.model import (
    Component,
    EntryPoint,
    Dep,
    Edge,
    Entity,
    Flow,
    FlowStep,
    NonEntityType,
    ProjectModel,
    SubFlow,
    UseCase,
)

_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


# --- builders -------------------------------------------------------------------

def git_run(root: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, env=_ENV)


def git_sha(root: Path) -> str:
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                         capture_output=True, env=_ENV)
    return out.stdout.decode().strip()


def commit(root: Path, files: dict[str, str], removed: list[str] | None = None, msg: str = "c") -> str:
    if not (root / ".git").exists():
        git_run(root, "init", "-q")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    for rel in removed or []:
        (root / rel).unlink()
    git_run(root, "add", "-A")
    git_run(root, "commit", "-q", "-m", msg)
    return git_sha(root)


GUILD_V1 = '''"""Guild domain."""


class Guild:
    """A server."""

    def __init__(self):
        self.id = None
        self.name = None


def helper():
    return 1
'''
# line map: 4 = class Guild, 7 = __init__, 8 = self.id (the edge call site), 12 = def helper

EXTENTS = {"svc/guild.py": [(4, 9, "Guild", "class"), (7, 9, "__init__", "function"),
                            (12, 13, "helper", "function")]}


def make_model(pin: str) -> ProjectModel:
    return ProjectModel(
        title="t", commit=pin,
        components=[Component(id="C1", name="Svc", source="svc/", files=["svc/guild.py"])],
        deps=[Dep(id="D1", name="Store")],
        entities=[Entity(id="E1", name="Guild", source="svc/guild.py:4")],
        non_entity_types=[NonEntityType(name="helper", source="svc/guild.py:12")],
        edges=[Edge(src="C1", verb="uses", dst="D1", where="svc/guild.py:8")],
    )


def make_repo(td: str) -> tuple[Path, str, ProjectModel]:
    root = Path(td)
    pin = commit(root, {"svc/guild.py": GUILD_V1, "README.md": "hi\n"}, msg="pin")
    return root, pin, make_model(pin)


def hits_by_eid(core) -> dict[str, list]:
    out: dict[str, list] = {}
    for h in core.hits:
        out.setdefault(h.eid, []).append(h)
    return out


def one(core, eid: str):
    hs = hits_by_eid(core).get(eid)
    assert hs and len(hs) >= 1, f"no hit for {eid}: {core.hits}"
    return hs[0]


# --- pure core: parse_u0 ----------------------------------------------------------

def test_parse_u0_hunks_and_counts() -> None:
    d = parse_u0("--- a/x\n+++ b/x\n@@ -8 +8 @@\n-old\n+new\n@@ -12,2 +13,0 @@\n-a\n-b\n@@ -3,0 +4,2 @@\n+i1\n+i2\n")
    assert d.hunks[0] == Hunk(8, 1, ("new",), ("old",))
    assert d.hunks[1] == Hunk(12, 2, (), ("a", "b"))
    assert d.hunks[2] == Hunk(3, 0, ("i1", "i2"), ())  # pure insert AFTER P-line 3


def test_parse_u0_binary() -> None:
    assert parse_u0("Binary files a/x and b/x differ\n").binary is True


# --- pure core: the fate comparison ----------------------------------------------

def test_identical_edits_cancel_and_differing_edits_hit() -> None:
    b = ParsedDiff(hunks=[Hunk(8, 1, ("x",), ("o",))])
    t = ParsedDiff(hunks=[Hunk(8, 1, ("x",), ("o",)), Hunk(13, 1, ("y",), ("p",))])
    frame = frame_from_two_diffs(b, t)
    assert frame.affected == [(13, 13)]           # the identical line-8 edit cancelled


def test_same_range_different_replacement_is_affected() -> None:
    b = ParsedDiff(hunks=[Hunk(8, 1, ("x1",), ("o",))])
    t = ParsedDiff(hunks=[Hunk(8, 1, ("x2",), ("o",))])
    assert frame_from_two_diffs(b, t).affected == [(8, 8)]


def test_one_side_empty_degenerates() -> None:
    t = ParsedDiff(hunks=[Hunk(5, 2, ("n",), ("a", "b")), Hunk(9, 0, ("i",), ())])
    frame = frame_from_two_diffs(ParsedDiff(), t)
    assert frame.affected == [(5, 6)] and frame.insertions == [9]


def test_touches_semantics() -> None:
    f = FileFrame(affected=[(13, 13)], insertions=[4])
    assert not f.touches(12, 12)      # neighbouring edit does not hit line 12
    assert f.touches(12, 13)
    assert f.touches(4, 9)            # insertion after line 4 lands inside [4, 9]
    assert not f.touches(1, 3)


def test_fully_deleted_flag() -> None:
    t = ParsedDiff(hunks=[Hunk(1, 13, (), tuple("x" * 13))])
    assert frame_from_two_diffs(ParsedDiff(), t, p_line_count=13).fully_deleted is True


# --- pure core: anchors + ladder ---------------------------------------------------

def test_anchor_index_covers_seed_set() -> None:
    m = make_model("abc1234")
    kinds = {(a.eid, a.kind, a.field) for a in anchor_index(m)}
    assert ("C1", "component", "source") in kinds       # dir anchor
    assert ("C1", "component", "files") in kinds
    assert ("E1", "entity", "source") in kinds
    assert ("net:helper", "non_entity_type", "source") in kinds
    assert ("edge:C1>uses>D1", "edge", "where") in kinds


def test_step_anchor_seeds_and_call_site_window() -> None:
    # A flow step's `where` joins the direct-hit seed set as `step:<uc>:<n>` and resolves with the
    # same tight call-site window as an edge anchor (never the whole enclosing function's extent).
    m = make_model("abc1234")
    m.use_cases = [UseCase(id="UC1", name="Do")]
    m.flows = [Flow(uc="UC1", title="Do", steps=[
        FlowStep(n=2, src="C1", dst="D1", phrase="stores", where="svc/guild.py:8")])]
    refs = anchor_index(m)
    assert ("step:UC1:2", "flow_step", "where") in {(a.eid, a.kind, a.field) for a in refs}
    assert next(a for a in refs if a.eid == "step:UC1:2").owner == "UC1"
    file_refs = [a for a in refs if not a.is_dir]
    on_line = {h.eid: h for h in resolve_hits(
        file_refs, FileFrame(affected=[(8, 8)]), EXTENTS["svc/guild.py"], "M")}
    assert on_line["step:UC1:2"].resolution == "line"
    near_line = {h.eid: h for h in resolve_hits(
        file_refs, FileFrame(affected=[(9, 9)]), EXTENTS["svc/guild.py"], "M")}
    assert near_line["step:UC1:2"].resolution == "symbol"   # inside the ±3 window, not on the line


def test_subflow_step_anchor_seeds() -> None:
    # A sub-flow step's `where` joins the seed set as `step:SF<k>:<n>`, owner = the SF id.
    m = make_model("abc1234")
    m.subflows = [SubFlow(id="SF1", name="Persist", steps=[
        FlowStep(n=2, src="C1", dst="D1", phrase="stores", where="svc/guild.py:8")])]
    refs = anchor_index(m)
    assert ("step:SF1:2", "flow_step", "where") in {(a.eid, a.kind, a.field) for a in refs}
    assert next(a for a in refs if a.eid == "step:SF1:2").owner == "SF1"


def test_dir_anchor_longest_prefix() -> None:
    a_outer = AnchorRef("S1", "group", "svc", None, None, "source", is_dir=True)
    a_inner = AnchorRef("C9", "component", "svc/sub", None, None, "source", is_dir=True)
    got = dir_anchors_for([a_outer, a_inner], "svc/sub/x.py")
    assert [a.eid for a in got] == ["C9", "S1"]


def test_enclosing_extent_innermost_wins() -> None:
    ext = enclosing_extent(EXTENTS["svc/guild.py"], 8)
    assert ext is not None and ext[2] == "__init__"      # not the whole class


def test_resolve_hits_ladder_and_edge_window() -> None:
    refs = anchor_index(make_model("abc1234"))
    file_refs = [a for a in refs if not a.is_dir]
    frame = FileFrame(affected=[(8, 8)])                  # the call-site line changed
    hits = {h.eid: h for h in resolve_hits(file_refs, frame, EXTENTS["svc/guild.py"], "M")}
    assert hits["E1"].resolution == "symbol"              # class body edit → symbol rung
    assert hits["edge:C1>uses>D1"].resolution == "line"
    assert hits["net:helper"].resolution == "file"        # untouched def → file floor
    assert all(h.change == "modified" for h in hits.values())


# --- golden git fixtures ------------------------------------------------------------

def test_worktree_body_edit_hits_symbol_rung() -> None:
    with tempfile.TemporaryDirectory() as td:
        root, pin, model = make_repo(td)
        (root / "svc/guild.py").write_text(GUILD_V1.replace("self.name = None", "self.name = ''"),
                                           encoding="utf-8")
        core = compute_impact(root, model, EXTENTS, pin, WORKTREE)
        assert one(core, "E1").resolution == "symbol" and one(core, "E1").change == "modified"
        assert one(core, "edge:C1>uses>D1").resolution == "symbol"  # line 9 is inside the ±3 window


def test_a_changed_schedule_line_hits_its_way_in() -> None:
    """A way in's schedule is often declared far from its own source; a changed cron line is a
    change to that way in, under the way in's own id."""
    with tempfile.TemporaryDirectory() as td:
        root, pin, model = make_repo(td)
        model.entry_points = [EntryPoint(id="EP1", kind="job", trigger="sweep", source="README.md:1",
                                         component="C1", cadence="nightly", cadence_source="svc/guild.py:12")]
        (root / "svc/guild.py").write_text(GUILD_V1.replace("def helper", "def helper2"), encoding="utf-8")
        core = compute_impact(root, model, EXTENTS, pin, WORKTREE)
        hit = one(core, "ep:README.md:1")
        assert hit.field == "cadence_source" and hit.change == "modified"


def test_committed_rename_plus_edit_no_false_delete() -> None:
    with tempfile.TemporaryDirectory() as td:
        root, pin, model = make_repo(td)
        (root / "svc/guild_v2.py").write_text(GUILD_V1.replace("self.id = None", "self.id = 0"),
                                              encoding="utf-8")
        (root / "svc/guild.py").unlink()
        git_run(root, "add", "-A")
        git_run(root, "commit", "-q", "-m", "rename+edit")
        core = compute_impact(root, model, EXTENTS, pin, git_sha(root))
        h = one(core, "edge:C1>uses>D1")
        assert h.change == "modified" and h.resolution == "line"    # NOT a deleted candidate
        assert not [x for x in core.hits if x.change == "deleted"]


def test_staged_worktree_rename_diffs_blob_pair() -> None:
    with tempfile.TemporaryDirectory() as td:
        root, pin, model = make_repo(td)
        git_run(root, "mv", "svc/guild.py", "svc/guild_v2.py")
        (root / "svc/guild_v2.py").write_text(GUILD_V1.replace("self.id = None", "self.id = 0"),
                                              encoding="utf-8")
        core = compute_impact(root, model, EXTENTS, pin, WORKTREE)
        assert one(core, "edge:C1>uses>D1").change == "modified"
        assert not [x for x in core.hits if x.change == "deleted"]


def test_cross_commit_identical_edit_cancels() -> None:
    """P is NOT an endpoint: b1 and b2 share one edit (cancels) and differ on line 13."""
    with tempfile.TemporaryDirectory() as td:
        root, pin, model = make_repo(td)
        shared = GUILD_V1.replace("self.id = None", "self.id = 0")
        git_run(root, "checkout", "-q", "-b", "b1")
        b1 = commit(root, {"svc/guild.py": shared}, msg="b1")
        git_run(root, "checkout", "-q", "-b", "b2", pin)
        b2 = commit(root, {"svc/guild.py": shared.replace("return 1", "return 2")}, msg="b2")
        core = compute_impact(root, model, EXTENTS, b1, b2)
        hits = {h.eid: h for h in core.hits}
        assert hits["net:helper"].resolution in ("line", "symbol")  # the differing edit
        assert hits["E1"].resolution == "file"                      # line-8 edit cancelled
        assert hits["edge:C1>uses>D1"].resolution == "file"


def test_moved_unchanged_function_is_anchor_drift() -> None:
    with tempfile.TemporaryDirectory() as td:
        root, pin, model = make_repo(td)
        moved = 'def helper():\n    return 1\n\n\n' + GUILD_V1.replace(
            "\n\ndef helper():\n    return 1\n", "")
        (root / "svc/guild.py").write_text(moved, encoding="utf-8")
        core = compute_impact(root, model, EXTENTS, pin, WORKTREE)
        h = one(core, "net:helper")
        assert h.change == "drifted" and h.drift_to == 1
        assert one(core, "E1").change in ("modified", "drifted")    # class body may shift too


def test_deleted_file_marks_anchors_deleted() -> None:
    with tempfile.TemporaryDirectory() as td:
        root, pin, model = make_repo(td)
        commit(root, {}, removed=["svc/guild.py"], msg="rm")
        core = compute_impact(root, model, EXTENTS, pin, git_sha(root))
        assert {h.change for h in core.hits} == {"deleted"}
        assert {h.eid for h in core.hits} >= {"E1", "net:helper", "edge:C1>uses>D1", "C1"}


def test_untracked_file_claimed_by_territory() -> None:
    with tempfile.TemporaryDirectory() as td:
        root, pin, model = make_repo(td)
        (root / "svc/new.py").write_text("x = 1\n", encoding="utf-8")
        core = compute_impact(root, model, EXTENTS, pin, WORKTREE)
        h = one(core, "C1")
        assert h.change == "added" and h.resolution == "file" and h.kind == "component"


def test_unanchored_file_change_hits_nothing() -> None:
    with tempfile.TemporaryDirectory() as td:
        root, pin, model = make_repo(td)
        (root / "README.md").write_text("changed\n", encoding="utf-8")
        core = compute_impact(root, model, EXTENTS, pin, WORKTREE)
        assert core.hits == [] and [f.path for f in core.files] == ["README.md"]


# --- git plumbing helpers -----------------------------------------------------------

def test_diff_changes_worktree_includes_untracked() -> None:
    with tempfile.TemporaryDirectory() as td:
        root, pin, _ = make_repo(td)
        (root / "svc/new.py").write_text("x\n", encoding="utf-8")
        assert ("A", "svc/new.py") in [(c.status, c.path) for c in diff_changes(root, pin, WORKTREE)]


def test_rename_map_between_commits() -> None:
    with tempfile.TemporaryDirectory() as td:
        root, pin, _ = make_repo(td)
        (root / "svc/guild_v2.py").write_text(GUILD_V1, encoding="utf-8")
        (root / "svc/guild.py").unlink()
        git_run(root, "add", "-A")
        git_run(root, "commit", "-q", "-m", "mv")
        assert rename_map(root, pin, git_sha(root)) == {"svc/guild_v2.py": "svc/guild.py"}


def test_u0_diff_blob_pair_across_rename() -> None:
    with tempfile.TemporaryDirectory() as td:
        root, pin, _ = make_repo(td)
        edited = GUILD_V1.replace("return 1", "return 9")
        (root / "svc/other.py").write_text(edited, encoding="utf-8")
        (root / "svc/guild.py").unlink()
        git_run(root, "add", "-A")
        git_run(root, "commit", "-q", "-m", "mv+edit")
        d = u0_diff(root, pin, "svc/guild.py", git_sha(root), "svc/other.py")
        assert len(d.hunks) == 1 and d.hunks[0].p_lo == 13

def test_file_added_between_base_and_pin_resolves_added() -> None:
    """Regression (real-map smoke): base older than the pin, the anchored file not yet existing at
    base. The file HAS a P-frame — resolve at full precision, label 'added', never crash on the
    missing base blob and never classify drift."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        base = commit(root, {"README.md": "hi\n"}, msg="before")
        pin = commit(root, {"svc/guild.py": GUILD_V1}, msg="pin")
        core = compute_impact(root, make_model(pin), EXTENTS, base, pin)
        hits = {h.eid: h for h in core.hits}
        assert hits["E1"].change == "added" and hits["E1"].resolution == "line"
        assert not [h for h in core.hits if h.change == "drifted"]
