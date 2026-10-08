"""The retro method's instructions that a later retro depends on, held against the tools they name.

Run either way:
    python3 -m pytest eval/tests/test_retro_method.py
"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path

from coyomap.ship import Step, run_plan

METHOD = Path(__file__).resolve().parents[1] / "retro" / "method.md"


def make_method_text() -> str:
    return METHOD.read_text(encoding="utf-8")


def make_step_1b(text: str) -> str:
    start = text.index("### Step 1b")
    return text[start:text.index("## Step 2", start)]


def test_step_1b_replays_the_builds_last_finalize_arguments():
    """A bare `finalize <map>` skipped two legs: the 2026-10-08 mcpolis retro read 20 advisories
    against the build's 26 (retro finding mcpolis-2026-10-08-#14)."""
    step = make_step_1b(make_method_text())
    assert "LAST finalize arguments" in step
    for flag in ("--verdicts", "--access-baseline", "--emit-gate-block", "--no-write",
                 "--lead-transcript", "--commands", "build-state.log"):
        assert flag in step, flag
    assert "`    finalize `" in step, "the method names the line ship prints"


def test_ship_prints_each_steps_command_indented_four_spaces():
    """The method sends the reader to grep `^    finalize ` in ship's output: hold ship to it."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        run_plan([Step("finalize (step 12)", ("finalize", "m.json", "--access-baseline", "a.json"))],
                 lambda argv: 0)
    assert "\n    finalize m.json --access-baseline a.json\n" in out.getvalue(), out.getvalue()


def test_every_retro_reader_gets_its_own_scratch_folder():
    """Two slice readers saved the same `slice.txt` in the shared scratchpad and one overwrote the
    other (retro finding mcpolis-2026-10-08-#22)."""
    text = make_method_text()
    assert "Give each reader its own folder" in text
    assert ".coyomap-eval/retro/<ts>/work/<reader id>/" in text
