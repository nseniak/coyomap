#!/usr/bin/env python3
"""Tests for the wave plan — every voter of one fact-check wave, in one file three tools read.

`contract skeptic --from-batches` writes it, `grounding lint --plan` and `timings record --plan`
read it, and the wave runner sends each skeptic the pointer it holds. So a plan that does not read
back exactly, or a malformed one read as if it were whole, would send the wrong skeptics or lint
against the wrong files.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_waveplan.py
    pytest tests/test_waveplan.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from coyomap.waveplan import (PLAN_FILE, SCHEMA, PlanAgent, WavePlan, load_plan, to_json,
                              write_plan)


def make_agent(root: Path, voter: str, batch: str, theme: str) -> PlanAgent:
    verify = root / ".coyomap" / "verify"
    brief = root / "briefs" / f"skeptic-{voter}.md"
    return PlanAgent(id=voter, claims=verify / f"claims-{batch}.json", theme=theme, brief=brief,
                     verdicts=verify / f"verdicts-{voter}.json",
                     pointer=f"{voter}\n{brief}\nRead it COMPLETELY and follow it — it is your "
                             f"entire brief.\n")


def make_plan(td: str) -> WavePlan:
    """A first wave: one security batch with three voters, one backbone batch with one."""
    root = Path(td).resolve()
    agents = (*(make_agent(root, f"security-1-{v}", "security-1", "security") for v in "abc"),
              make_agent(root, "backbone-1", "backbone-1", "backbone"))
    return WavePlan(verify=root / ".coyomap" / "verify", prefix="", votes={"security": 3},
                    agents=agents)


def make_plan_doc(plan: WavePlan) -> dict[str, Any]:
    """The plan as the file holds it, as JSON data a test can break one field of."""
    doc = json.loads(to_json(plan))
    assert isinstance(doc, dict)
    return doc


def test_a_plan_round_trips() -> None:
    with tempfile.TemporaryDirectory() as td:
        plan = make_plan(td)
        path = Path(td) / "briefs" / PLAN_FILE
        write_plan(path, plan)
        again = load_plan(path)
        doc = json.loads(path.read_text(encoding="utf-8"))
    assert again == plan
    assert doc["schema"] == SCHEMA
    assert [a["id"] for a in doc["agents"]] == ["security-1-a", "security-1-b", "security-1-c",
                                                "backbone-1"], "the dispatch order is kept"


def test_a_malformed_plan_is_refused_by_name() -> None:
    """Every fault is named at once, with the file it is in, and nothing is guessed."""
    with tempfile.TemporaryDirectory() as td:
        plan = make_plan(td)
        doc = make_plan_doc(plan)
        agents = doc["agents"]
        agents[1]["brief"] = "briefs/skeptic-security-1-b.md"     # relative
        agents[2]["id"] = "security-1-a"                           # listed twice
        del agents[3]["pointer"]                                   # missing
        path = Path(td) / PLAN_FILE
        path.write_text(json.dumps(doc), encoding="utf-8")
        try:
            load_plan(path)
        except ValueError as exc:
            message = str(exc)
        else:
            raise AssertionError("a malformed plan was read as whole")
        not_json = Path(td) / "broken.json"
        not_json.write_text("{\"agents\": [", encoding="utf-8")
        try:
            load_plan(not_json)
        except ValueError as exc:
            broken = str(exc)
        else:
            raise AssertionError("a plan that is not JSON was read")
        bad = WavePlan(verify=Path("relative/verify"), prefix="", votes={}, agents=plan.agents)
        out = Path(td) / "never-written.json"
        try:
            write_plan(out, bad)
        except ValueError:
            written = out.exists()
        else:
            raise AssertionError("write_plan wrote a plan load_plan would refuse")
    assert str(path) in message and "3 fault(s)" in message, message
    assert "'briefs/skeptic-security-1-b.md' is not an absolute path" in message, message
    assert "'security-1-a' is listed twice" in message, message
    assert "pointer" in message, message
    assert str(not_json) in broken and "not JSON" in broken, broken
    assert not written, "a refused plan leaves no file behind"


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all wave-plan tests passed")
