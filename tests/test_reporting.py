#!/usr/bin/env python3
"""Tests for `coyomap.reporting` — the one place a long list is cut and the cut is counted.

On 2026-10-07 `finalize` and `grounding` each grew a private copy of the same two lines: a list put
one item per line under its count line, cut at N, ending on a `+N more` line. Both now call
`reporting.item_lines`; the pins below hold its output to theirs, byte for byte. The structural
tests keep a copy from coming back, and keep a list from being cut by hand again in the modules
whose cuts were moved onto the helper the same day.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_reporting.py
    pytest tests/test_reporting.py
"""
from __future__ import annotations

import ast
from pathlib import Path

from coyomap import reporting

PACKAGE = Path(str(reporting.__file__)).parent


def make_items(n: int) -> list[str]:
    return [f"src/file_{i}.py" for i in range(1, n + 1)]


# --- item_lines: the output both copies printed ---------------------------------------------------

def test_no_items_print_nothing():
    """Empty, so a caller can concatenate it after its count line unconditionally."""
    assert reporting.item_lines([], 3) == ""
    assert reporting.item_lines([], None) == ""


def test_items_that_fit_print_one_per_line_with_no_tail():
    assert reporting.item_lines(make_items(2), 3) == "  - src/file_1.py\n  - src/file_2.py"
    assert reporting.item_lines(make_items(3), 3, unit="file(s)") == (
        "  - src/file_1.py\n  - src/file_2.py\n  - src/file_3.py")


def test_items_past_the_limit_are_counted_on_a_line_of_their_own():
    assert reporting.item_lines(make_items(5), 2, unit="file(s)") == (
        "  - src/file_1.py\n  - src/file_2.py\n  - +3 more file(s)")
    assert reporting.item_lines(make_items(5), 2) == (
        "  - src/file_1.py\n  - src/file_2.py\n  - +3 more")


def test_no_limit_prints_every_item():
    """`None` is the reading list that must arrive whole (`finalize`'s lost access files)."""
    assert reporting.item_lines(make_items(40), None).splitlines() == [
        f"  - src/file_{i}.py" for i in range(1, 41)]


def test_whole_list_mode_prints_every_item_whatever_the_limit():
    try:
        reporting.set_full_lists(True)
        text = reporting.item_lines(make_items(5), 2, unit="file(s)")
    finally:
        reporting.reset_full_lists()
    assert text.splitlines() == [f"  - src/file_{i}.py" for i in range(1, 6)]


# --- the structural guards ------------------------------------------------------------------------

#: The modules whose hand-cut lists moved onto `shown` / `item_lines` on 2026-10-07, and must stay
#: there. A module joins this list when its last hand cut goes. Named, not the whole package: the
#: same slice also builds a path's parent folders (`"/".join(parts[:i])` in `validate_analysis`),
#: which is no list, and a few cuts are a ranking or a label on purpose (`balance`, `mapdiff`).
HELPER_ONLY = ("finalize.py", "grounding.py", "audit_model.py", "reconcile.py",
               "reconcile_build.py", "viewer/export.py", "validate_model.py", "contract.py")


def _is_cut(node: ast.expr) -> bool:
    """`x[:n]`: a slice with no start or step whose end is a COUNT, a number (`[:6]`) or a name
    (`[:limit]`). An end worked out from the text is a position, not a count: `lines[:quoted[0]]`
    is the part of a document above a marker (`contract`), `parts[:i + 1]` a path's parent folders,
    and `xs[:-1]` the head of an "a, b and c" join. None of those is a cut at N."""
    if not (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice)):
        return False
    upper = node.slice.upper
    return (node.slice.lower is None and node.slice.step is None
            and (isinstance(upper, ast.Name)
                 or (isinstance(upper, ast.Constant) and isinstance(upper.value, int))))


def hand_cut_lists(source: str) -> list[int]:
    """The lines where a list is cut by a slice and then printed: the slice is what a `.join()`
    reads, or what a comprehension inside one, or a `for` loop, walks. A slice of a string is never
    walked, so a clipped claim or note (`s[:90]`) is not counted."""
    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "join" and node.args):
            arg = node.args[0]
            if _is_cut(arg) or (isinstance(arg, (ast.GeneratorExp, ast.ListComp))
                                and any(_is_cut(g.iter) for g in arg.generators)):
                found.append(node.lineno)
        elif isinstance(node, ast.For) and _is_cut(node.iter):
            found.append(node.lineno)
    return sorted(found)


def test_no_module_keeps_a_private_copy_of_item_lines():
    """`finalize._items` and `grounding._item_lines` were the same two lines, written the same day.
    The separator that makes the one-per-line shape is the copy's fingerprint."""
    offenders = [f"{mod.relative_to(PACKAGE)}:{n}"
                 for mod in sorted(PACKAGE.rglob("*.py")) if mod.name != "reporting.py"
                 for n, line in enumerate(mod.read_text(encoding="utf-8").splitlines(), 1)
                 if 'sep="\\n  - "' in line or "sep='\\n  - '" in line]
    assert not offenders, f"a private copy of reporting.item_lines: {offenders}"


def test_the_converted_modules_cut_no_list_by_hand():
    """A hand cut prints `…` or nothing where `shown` counts what it left out, and it ignores
    `--json`, which promises whole lists."""
    offenders = [f"{name}:{n}" for name in HELPER_ONLY
                 for n in hand_cut_lists((PACKAGE / name).read_text(encoding="utf-8"))]
    assert not offenders, f"a list cut by hand, not through coyomap.reporting: {offenders}"


def test_the_guard_above_sees_every_hand_cut_shape_and_no_clipped_string():
    """A guard nobody has seen fail is a guard nobody knows works."""
    cut = ('a = ", ".join(xs[:6]) + (" …" if len(xs) > 6 else "")\n'
           'b = "; ".join(f"{x}" for x in xs[:4])\n'
           'for x in xs[:15]:\n    print(x)\n'
           'e = ", ".join(xs[:limit])\n')
    assert hand_cut_lists(cut) == [1, 2, 3, 5]
    clipped = ('a = "; ".join(s[:90] for s in shown_ones)\n'
               'b = shown(xs, 6)\n'
               'c = note[:300] + " …"\n'
               'd = ", ".join(xs[:-1]) + " and " + xs[-1]\n'
               'e = "\\n".join(lines[: quoted[0]])\n'
               'f = "/".join(parts[:i + 1])\n')
    assert hand_cut_lists(clipped) == []
