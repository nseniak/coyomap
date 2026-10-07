"""The wave plan: every voter of ONE fact-check wave, written once, read by the tools that check it.

`contract skeptic --from-batches` writes `<out-dir>/wave-plan.json`, naming every voter it filled a
brief for (written or skipped): its claims file, its theme, its brief, the verdicts file it must
write, and the pointer to send it. `grounding lint --plan` reads the plan to know which verdicts
files must exist, and `timings record --plan` reads it to know which slices to time. So the wave
runner never types an id list, and never composes a pointer: it sends what the plan holds.

Data only. It imports nothing from coyomap but the whole-file writer, so `contract`, `grounding` and
`timings` can all import it without an import cycle.

Every path in a plan is ABSOLUTE, and `write_plan` refuses a plan that `load_plan` would refuse. The
plan is read by agents that do not share the writer's working directory, so a relative path would
resolve somewhere else, or nowhere.

Stdlib-only (the cli.py firewall).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from coyomap.whole_file import write_whole

#: The plan's file name, in the folder its briefs are written to.
PLAN_FILE = "wave-plan.json"
SCHEMA = "coyomap-wave-plan/v1"

#: The fields of one agent, in the order a plan writes them.
_AGENT_FIELDS = ("id", "claims", "theme", "brief", "verdicts", "pointer")
_PATH_FIELDS = ("claims", "brief", "verdicts")


@dataclass(frozen=True)
class PlanAgent:
    """One voter of the wave: one skeptic over one claims file."""

    id: str           # the voter id, one word: the batch id, or `<batch>-a` when its theme has votes
    claims: Path      # the claims file it checks
    theme: str        # the claims file's theme (`security`, `backbone`, ...)
    brief: Path       # its filled brief
    verdicts: Path    # the verdicts file it must write
    pointer: str      # the exact text to send it, from `contract.brief()`


@dataclass(frozen=True)
class WavePlan:
    """One wave: where its files live, which of them it covers, and every voter."""

    verify: Path                   # the folder holding the claims and verdicts files
    prefix: str                    # the wave's file prefix: '' for a first wave, `added-` for a second
    votes: dict[str, int]          # voters per theme (`{"security": 3}`); an unnamed theme has 1
    agents: tuple[PlanAgent, ...]  # every voter, in dispatch order


def to_json(plan: WavePlan) -> str:
    """The plan as the file holds it."""
    doc: dict[str, object] = {
        "schema": SCHEMA,
        "verify": str(plan.verify),
        "prefix": plan.prefix,
        "votes": dict(plan.votes),
        "agents": [{"id": a.id, "claims": str(a.claims), "theme": a.theme, "brief": str(a.brief),
                    "verdicts": str(a.verdicts), "pointer": a.pointer} for a in plan.agents],
    }
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def write_plan(path: Path, plan: WavePlan) -> None:
    """Write the plan whole or not at all. Raises `ValueError` on a plan `load_plan` would refuse,
    before anything is written."""
    text = to_json(plan)
    from_json(text, str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    write_whole(path, text)


def load_plan(path: Path) -> WavePlan:
    """Read a plan. Raises `ValueError` naming the file and every fault in it."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"wave plan {path}: cannot read it ({exc.strerror or exc})") from exc
    return from_json(text, str(path))


def from_json(text: str, where: str) -> WavePlan:
    """Parse a plan's text. `where` names it in a refusal."""
    try:
        raw: object = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"wave plan {where} is not JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"wave plan {where} is not a JSON object")
    faults: list[str] = []
    if raw.get("schema") != SCHEMA:
        faults.append(f'"schema" is {raw.get("schema")!r}, not {SCHEMA!r}')
    verify = _path(raw.get("verify"), '"verify"', faults)
    prefix = raw.get("prefix")
    if not isinstance(prefix, str):
        faults.append('"prefix" is not a string')
        prefix = ""
    votes = _votes(raw.get("votes"), faults)
    agents = _agents(raw.get("agents"), faults)
    if faults:
        raise ValueError(f"wave plan {where} is malformed — {len(faults)} fault(s):\n"
                         + "\n".join(f"  - {f}" for f in faults))
    return WavePlan(verify=verify, prefix=prefix, votes=votes, agents=agents)


def _path(value: object, label: str, faults: list[str]) -> Path:
    if not isinstance(value, str) or not value.strip():
        faults.append(f"{label} is not a path")
        return Path()
    if not Path(value).is_absolute():
        faults.append(f"{label} {value!r} is not an absolute path")
    return Path(value)


def _votes(value: object, faults: list[str]) -> dict[str, int]:
    if not isinstance(value, dict):
        faults.append('"votes" is not an object of theme → count')
        return {}
    out: dict[str, int] = {}
    for theme, n in value.items():
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            faults.append(f'"votes" gives theme {theme!r} {n!r}, not a count of 1 or more')
            continue
        out[str(theme)] = n
    return out


def _agents(value: object, faults: list[str]) -> tuple[PlanAgent, ...]:
    if not isinstance(value, list) or not value:
        faults.append('"agents" lists no agent')
        return ()
    out: list[PlanAgent] = []
    seen: set[str] = set()
    for k, row in enumerate(value):
        label = f"agent {k + 1}"
        if not isinstance(row, dict):
            faults.append(f"{label} is not an object")
            continue
        missing = [f for f in _AGENT_FIELDS if not isinstance(row.get(f), str)]
        if missing:
            faults.append(f"{label} has no {', '.join(missing)} string")
            continue
        aid = str(row["id"])
        label = f"agent {aid!r}"
        if not aid or aid.split() != [aid]:
            faults.append(f"{label}: the id is not one word")
        elif aid in seen:
            faults.append(f"{label} is listed twice")
        seen.add(aid)
        if not str(row["pointer"]).strip():
            faults.append(f"{label} has an empty pointer")
        paths = {f: _path(row[f], f'{label} "{f}"', faults) for f in _PATH_FIELDS}
        out.append(PlanAgent(id=aid, claims=paths["claims"], theme=str(row["theme"]),
                             brief=paths["brief"], verdicts=paths["verdicts"],
                             pointer=str(row["pointer"])))
    return tuple(out)
