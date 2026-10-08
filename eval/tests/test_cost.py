#!/usr/bin/env python3
"""Tests for `coyomap-eval cost` — what a build spent.

Run either way (needs an editable install: `make install-eval`):
    python3 eval/tests/test_cost.py
    pytest eval/tests/test_cost.py
"""
from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from pathlib import Path

from coyomap_eval import cost
from coyomap_eval.transcript import Usage, read_turns

# The whole report rests on two readings that are easy to get wrong, and both were wrong once:
#   * usage repeats on every record of one message — summing records inflates output ~8x
#   * a tool call executes at its OWN record's time, not its Turn's — timing from the Turn
#     reported tool execution at 34% of agent time when the true figure is 4%
# Those two are pinned first.


def write_jsonl(path: Path, records: list[dict[str, object]]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def make_assistant_records(message_id: str, calls: list[tuple[str, str, str]],
                           usage: Mapping[str, object], stamp_of: dict[str, str],
                           model: str = "claude-opus-5") -> list[dict[str, object]]:
    """One API response written the way the harness writes it: one record per content block, each
    stamped when THAT block ran, every record repeating the same usage."""
    out: list[dict[str, object]] = []
    for call_id, name, command in calls:
        out.append({
            "type": "assistant",
            "timestamp": stamp_of[call_id],
            "message": {"id": message_id, "model": model, "usage": usage,
                        "content": [{"type": "tool_use", "id": call_id, "name": name,
                                     "input": {"command": command}}]},
        })
    return out


def make_result_record(call_id: str, stamp: str) -> dict[str, object]:
    return {"type": "user", "timestamp": stamp,
            "message": {"content": [{"type": "tool_result", "tool_use_id": call_id,
                                     "content": "ok"}]}}


def make_session(tmp: Path) -> Path:
    """A lead that made one two-call response, each call taking 10s, 60s apart."""
    usage = {"input_tokens": 3, "output_tokens": 1000,
             "cache_read_input_tokens": 100_000, "cache_creation_input_tokens": 2_000}
    records = make_assistant_records(
        "m1", [("c1", "Bash", "rg foo"), ("c2", "Bash", "rg bar")], usage,
        {"c1": "2026-08-02T10:00:00.000Z", "c2": "2026-08-02T10:01:00.000Z"})
    records.insert(1, make_result_record("c1", "2026-08-02T10:00:10.000Z"))
    records.append(make_result_record("c2", "2026-08-02T10:01:10.000Z"))
    return write_jsonl(tmp / "session.jsonl", records)


def make_agent(dir_path: Path, name: str, description: str, minutes: float,
               output_tokens: int = 500) -> None:
    """A sub-agent transcript with two responses `minutes` apart."""
    dir_path.mkdir(parents=True, exist_ok=True)
    usage = {"input_tokens": 1, "output_tokens": output_tokens,
             "cache_read_input_tokens": 44_000, "cache_creation_input_tokens": 500}
    end = 60 * minutes
    records = [
        {"type": "user", "isSidechain": True, "timestamp": "2026-08-02T10:05:00.000Z",
         "message": {"content": "go"}},
        {"type": "assistant", "isSidechain": True, "timestamp": "2026-08-02T10:05:00.000Z",
         "message": {"id": f"{name}-1", "model": "claude-opus-5", "usage": usage,
                     "content": [{"type": "tool_use", "id": f"{name}-t1", "name": "Bash",
                                  "input": {"command": "rg x"}}]}},
        {"type": "assistant", "isSidechain": True,
         "timestamp": f"2026-08-02T10:{5 + int(end // 60):02d}:{int(end % 60):02d}.000Z",
         "message": {"id": f"{name}-2", "model": "claude-opus-5", "usage": usage,
                     "content": [{"type": "text", "text": "done"}]}},
    ]
    write_jsonl(dir_path / f"agent-{name}.jsonl", records)
    (dir_path / f"agent-{name}.meta.json").write_text(
        json.dumps({"description": description}), encoding="utf-8")


# --- usage is per message, never per record ------------------------------------------


def test_usage_is_counted_once_per_message_not_once_per_record():
    with tempfile.TemporaryDirectory() as td:
        session = make_session(Path(td))
        turns = read_turns(session)
        assistant = [t for t in turns if t.usage]
        assert len(assistant) == 1, "two tool_use records are ONE API response"
        assert assistant[0].usage.output_tokens == 1000, "summing the records would give 2000"
        assert assistant[0].model == "claude-opus-5"


def test_context_is_everything_the_request_read():
    u = Usage(input_tokens=3, output_tokens=9, cache_read_input_tokens=100,
              cache_creation_input_tokens=7)
    assert u.context == 110


# --- a tool call is timed from its own record ----------------------------------------


def test_tool_time_uses_the_call_timestamp_not_the_turn():
    with tempfile.TemporaryDirectory() as td:
        session = make_session(Path(td))
        lead, _agents = cost.read_run(session)
        seconds = cost._tool_seconds([lead])
        # Two 10s calls. Timing from the Turn (which carries c1's stamp) would charge the 60s of
        # generation between them and report ~80s.
        assert 15 <= seconds <= 25, seconds


# --- idle is a silence with NOTHING running -------------------------------------------


def test_a_long_silence_with_no_agent_running_is_idle():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        records = [
            {"type": "assistant", "timestamp": "2026-08-02T10:00:00.000Z",
             "message": {"id": "a", "model": "claude-opus-5", "usage": {"output_tokens": 1},
                         "content": [{"type": "text", "text": "?"}]}},
            {"type": "assistant", "timestamp": "2026-08-02T11:00:00.000Z",
             "message": {"id": "b", "model": "claude-opus-5", "usage": {"output_tokens": 1},
                         "content": [{"type": "text", "text": "!"}]}},
        ]
        session = write_jsonl(tmp / "s.jsonl", records)
        report = cost.build_report(session)
        assert round(report.idle_seconds) == 3600
        assert round(report.wall_seconds - report.idle_seconds) == 0


def test_a_long_silence_while_an_agent_runs_is_build_time():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        records = [
            {"type": "assistant", "timestamp": "2026-08-02T10:05:00.000Z",
             "message": {"id": "a", "model": "claude-opus-5", "usage": {"output_tokens": 1},
                         "content": [{"type": "text", "text": "spawning"}]}},
            {"type": "assistant", "timestamp": "2026-08-02T10:25:00.000Z",
             "message": {"id": "b", "model": "claude-opus-5", "usage": {"output_tokens": 1},
                         "content": [{"type": "text", "text": "collected"}]}},
        ]
        session = write_jsonl(tmp / "s.jsonl", records)
        make_agent(tmp / "s" / "subagents", "one", "Harvest the adapters", minutes=20.0)
        report = cost.build_report(session)
        assert report.idle_seconds == 0.0, "the lead was waiting on its own fan-out"


# --- sub-agents are most of the spend -------------------------------------------------


def test_subagent_transcripts_are_read_and_bucketed_by_role():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_session(tmp)
        agents = tmp / "session" / "subagents"
        make_agent(agents, "h1", "Harvest the repositories", minutes=4.0)
        make_agent(agents, "t1", "Trace the sign-in flow", minutes=9.0)
        make_agent(agents, "s1", "Skeptic security-1a", minutes=3.0)
        make_agent(agents, "g1", "Measure test completeness", minutes=2.0)
        report = cost.build_report(session)
        assert report.agents == 4
        assert set(report.by_role) == {"lead", "harvest", "trace", "verify", "test/gap"}
        assert report.by_role["trace"]["requests"] == 2


def test_an_undescribed_agent_is_other_never_forced_into_a_bucket():
    assert cost.classify("") == "other"
    assert cost.classify("Trace the harvest gaps") == "trace", "trace wins over harvest"
    assert cost.classify("Skeptic backbone-2") == "verify"


# --- the straggler tax ----------------------------------------------------------------


def test_waste_is_not_charged_with_a_stragglers_idle_wait_on_an_UNBOUNDED_run():
    """`waste = wall - mean`, and the two were measured on different bases: `mean` subtracts the
    stretches an agent sat blocked on its coordinator, `wall` read the raw span. So the DEFAULT
    invocation — no flags — printed 14.86 phantom minutes in one fan-out of a real build and 22.35
    minutes of straggler waste for a true 7.49. `--to-turn` hid it there only because that build's
    block happened to fall outside the window: correctness must not depend on a flag."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_bounded_session(tmp)
        make_spanning_agent(cost.subagent_dir(session), "s1", "Trace the slow one",
                            start="2026-08-02T10:01:00.000Z", end="2026-08-02T10:04:00.000Z",
                            woken="2026-08-02T10:29:00.000Z")
        loose = cost.build_report(session)          # NO bounds at all
        assert len(loose.batches) == 1
        assert round(loose.batches[0]["waste"]) == 0, loose.batches[0]["waste"]
        assert round(loose.batches[0]["wall"] / 60) == 3, "the barrier held for the work, not the nap"
        assert round(loose.agent_busy_seconds / 60) == 3, loose.agent_busy_seconds


def test_waste_is_the_batch_wall_minus_its_mean_agent():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_session(tmp)
        agents = tmp / "session" / "subagents"
        make_agent(agents, "a", "Harvest one", minutes=2.0)
        make_agent(agents, "b", "Harvest two", minutes=2.0)
        make_agent(agents, "c", "Harvest three", minutes=14.0)
        report = cost.build_report(session)
        assert len(report.batches) == 1
        batch = report.batches[0]
        assert round(batch["wall"] / 60) == 14
        assert round(batch["mean"] / 60) == 6
        assert round(batch["waste"] / 60) == 8, "the two fast agents idled 8 minutes"


# --- pricing --------------------------------------------------------------------------


def test_cache_reads_and_writes_are_priced_at_their_multipliers():
    usage = Usage(input_tokens=0, output_tokens=0,
                  cache_read_input_tokens=1_000_000, cache_creation_input_tokens=0)
    assert cost.cost_of(usage, "claude-opus-5", "5m") == 0.5  # 0.1x of $5
    write = Usage(cache_creation_input_tokens=1_000_000)
    assert cost.cost_of(write, "claude-opus-5", "5m") == 6.25
    assert cost.cost_of(write, "claude-opus-5", "1h") == 10.0


def test_an_unpriced_model_is_named_not_silently_priced_as_something_else():
    usage = Usage(output_tokens=1_000_000)
    assert cost.cost_of(usage, "some-future-model", "5m") is None
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        records = [{"type": "assistant", "timestamp": "2026-08-02T10:00:00.000Z",
                    "message": {"id": "a", "model": "some-future-model",
                                "usage": {"output_tokens": 1_000_000},
                                "content": [{"type": "text", "text": "hi"}]}}]
        session = write_jsonl(tmp / "s.jsonl", records)
        report = cost.build_report(session)
        assert report.cost == 0.0
        assert report.unpriced_models == ["some-future-model"]
        assert "no list price" in cost.format_report(report)


def test_a_mixed_model_run_prices_each_turn_by_its_own_model():
    """The whole point of the report: swapping the verify agents to a cheaper model has to show
    up as a cheaper run, not as the same run priced at the lead's rate."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        records = [
            {"type": "assistant", "timestamp": "2026-08-02T10:00:00.000Z",
             "message": {"id": "a", "model": "claude-opus-5",
                         "usage": {"output_tokens": 1_000_000},
                         "content": [{"type": "text", "text": "x"}]}},
            {"type": "assistant", "timestamp": "2026-08-02T10:00:30.000Z",
             "message": {"id": "b", "model": "claude-haiku-4-5",
                         "usage": {"output_tokens": 1_000_000},
                         "content": [{"type": "text", "text": "y"}]}},
        ]
        session = write_jsonl(tmp / "s.jsonl", records)
        report = cost.build_report(session)
        assert report.cost == 30.0, "$25 of Opus plus $5 of Haiku, not 2x either rate"


# --- the per-unit divisor -------------------------------------------------------------


def make_map(path: Path, rows: int) -> Path:
    path.write_text(json.dumps({
        "components": [{"id": f"C{i}"} for i in range(rows)],
        "grounding": {"claims_total": 100, "claims_refuted": 2, "claims_unverifiable": 1},
        "goal": "not a list, not counted",
    }), encoding="utf-8")
    return path


def test_per_row_divides_by_what_the_build_produced():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_session(tmp)
        report = cost.build_report(session, map_path=make_map(tmp / "map.json", 100))
        assert report.map["rows"] == 100
        assert report.map["claims_refuted"] == 2
        assert report.per_row["cost"] == report.cost / 100
        rendered = cost.format_report(report)
        assert "cost per row" in rendered and "refuted" in rendered


def test_a_map_that_fails_to_parse_does_not_lose_the_spend_numbers():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_session(tmp)
        broken = tmp / "broken.json"
        broken.write_text("{ not json", encoding="utf-8")
        report = cost.build_report(session, map_path=broken)
        assert report.map == {} and report.cost > 0


# --- bounding a build inside a longer session -----------------------------------------


def test_only_a_partly_covered_silence_counts_the_uncovered_part():
    """A 40-minute silence with a 2-minute agent in it is 38 idle minutes, not zero and not 40."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        records = [
            {"type": "assistant", "timestamp": "2026-08-02T10:00:00.000Z",
             "message": {"id": "a", "model": "claude-opus-5", "usage": {"output_tokens": 1},
                         "content": [{"type": "text", "text": "x"}]}},
            {"type": "assistant", "timestamp": "2026-08-02T10:40:00.000Z",
             "message": {"id": "b", "model": "claude-opus-5", "usage": {"output_tokens": 1},
                         "content": [{"type": "text", "text": "y"}]}},
        ]
        session = write_jsonl(tmp / "s.jsonl", records)
        make_agent(tmp / "s" / "subagents", "one", "Harvest one", minutes=2.0)
        report = cost.build_report(session)
        assert round(report.idle_seconds / 60) == 38


def test_turn_bounds_cut_the_session_down_to_the_build():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        records = []
        for i in range(4):
            records.append({
                "type": "assistant", "timestamp": f"2026-08-02T10:0{i}:00.000Z",
                "message": {"id": f"m{i}", "model": "claude-opus-5",
                            "usage": {"output_tokens": 100},
                            "content": [{"type": "text", "text": str(i)}]}})
        session = write_jsonl(tmp / "s.jsonl", records)
        assert cost.build_report(session).requests == 4
        assert cost.build_report(session, from_turn=2).requests == 2
        assert cost.build_report(session, from_turn=1, to_turn=2).requests == 2


def make_spanning_agent(dir_path: Path, name: str, description: str, *, start: str, end: str,
                        woken: str | None = None, woke_until: str | None = None) -> None:
    """A sub-agent running `start` to `end`, optionally WOKEN once more at `woken` and working on
    until `woke_until` (default: answering immediately, at `woken`).

    The wake is what a completed background command looks like in a real transcript: a user record
    carrying NO tool result, long after the agent answered. Stamps are explicit so a test can place
    the agent either side of a turn bound."""
    dir_path.mkdir(parents=True, exist_ok=True)
    usage = {"input_tokens": 1, "output_tokens": 500,
             "cache_read_input_tokens": 44_000, "cache_creation_input_tokens": 500}

    def response(n: int, stamp: str, block: dict[str, object]) -> dict[str, object]:
        return {"type": "assistant", "isSidechain": True, "timestamp": stamp,
                "message": {"id": f"{name}-{n}", "model": "claude-opus-5", "usage": usage,
                            "content": [block]}}

    records: list[dict[str, object]] = [
        {"type": "user", "isSidechain": True, "timestamp": start, "message": {"content": "go"}},
        response(1, start, {"type": "tool_use", "id": f"{name}-t1", "name": "Bash",
                            "input": {"command": "rg x &"}}),
        response(2, end, {"type": "text", "text": "nothing changes any verdict"}),
    ]
    if woken is not None:
        records.append({"type": "user", "isSidechain": True, "timestamp": woken,
                        "message": {"content": "the background command completed"}})
        records.append(response(3, woke_until or woken,
                                {"type": "text", "text": "a duplicate lookup"}))
    write_jsonl(dir_path / f"agent-{name}.jsonl", records)
    (dir_path / f"agent-{name}.meta.json").write_text(
        json.dumps({"description": description}), encoding="utf-8")


def make_bounded_session(tmp: Path) -> Path:
    """A lead whose build is turns 0-1 (10:00 to 10:10) and which keeps chatting at 10:30 — the
    normal case, an operator who goes on asking questions once the map has landed."""
    records = [
        {"type": "assistant", "timestamp": f"2026-08-02T{stamp}.000Z",
         "message": {"id": f"m{i}", "model": "claude-opus-5", "usage": {"output_tokens": 100},
                     "content": [{"type": "text", "text": str(i)}]}}
        for i, stamp in enumerate(("10:00:00", "10:10:00", "10:30:00"))
    ]
    return write_jsonl(tmp / "s.jsonl", records)


def test_a_turn_bound_stops_a_subagents_clock_where_it_stops_the_leads():
    """`--to-turn` numbers the LEAD's messages and a sub-agent has none, so its span used to run on
    to its last record whatever the bound said. One measured build: an agent woken by a background
    command 12.9 minutes after the commit stretched a 42.0-minute build to 54.8 and made the
    straggler waste read 22.3m (41% of active) for a true 7.5m (18%)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_bounded_session(tmp)
        make_spanning_agent(cost.subagent_dir(session), "w1", "Close the wave-two refutations",
                            start="2026-08-02T10:05:00.000Z", end="2026-08-02T10:08:00.000Z",
                            woken="2026-08-02T10:38:00.000Z")
        loose = cost.build_report(session)
        assert round(loose.wall_seconds / 60) == 38, "unbounded, the wake is still the build's"
        bound = cost.build_report(session, to_turn=1)
        assert round(bound.wall_seconds / 60) == 10, bound.wall_seconds
        assert round(bound.agent_busy_seconds / 60) == 3, bound.agent_busy_seconds
        assert bound.batches[0]["waste"] == 0.0, "the 30-minute wake is not straggler waste"
        assert round(bound.batches[0]["wall"] / 60) == 3


def test_the_bound_cuts_the_clock_and_never_the_bill():
    """The build spawned that agent and paid for every call it made, whenever it landed. Dropping
    the late turns from the token sums would quietly change what the run COST, which is a different
    claim from what it took."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_bounded_session(tmp)
        make_spanning_agent(cost.subagent_dir(session), "w1", "Close the wave-two refutations",
                            start="2026-08-02T10:05:00.000Z", end="2026-08-02T10:08:00.000Z",
                            woken="2026-08-02T10:38:00.000Z")
        bound = cost.build_report(session, to_turn=1)
        assert bound.agents == 1
        assert bound.by_role["other"]["requests"] == 3, "all three agent calls are still billed"
        assert bound.usage["output_tokens"] == 3 * 500 + 2 * 100


def test_an_agent_that_began_just_before_the_bound_still_did_its_work_inside_it():
    """The start edge, which "started inside the window" got wrong. On a real transcript moving
    `--from-turn` by ONE lead turn — 1.49 seconds of clock — deleted a whole trace agent: 41 API
    calls and $4.49, whose 4.56-minute span was work from end to end and almost all of it inside
    the window.
    `lead alone` then rose 6.2m -> 7.4m over an unchanged 28.3m wall, so the report claimed the lead
    was alone for time it was plainly waiting on that agent."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_bounded_session(tmp)
        # begins one second BEFORE the lead's first in-bound turn, works until 10:08
        make_spanning_agent(cost.subagent_dir(session), "early", "Trace the sign-in flow",
                            start="2026-08-02T09:59:59.000Z", end="2026-08-02T10:08:00.000Z")
        bound = cost.build_report(session, from_turn=0, to_turn=1)
        assert bound.agents == 1, "one second of head start does not make it another build's agent"
        assert bound.by_role["trace"]["requests"] == 2, "and it keeps its whole bill"
        # 10:00 (the window opening, it was already running) to 10:08 (its last record) — NOT the
        # single instant 10:08, which is all that survives if the clock starts at the first
        # in-window RECORD instead of the bound.
        assert round(bound.agent_busy_seconds / 60) == 8, bound.agent_busy_seconds
        assert round(bound.lead_only_seconds / 60) == 2, "the lead was waiting for the other 8"


def test_a_block_straddling_the_bound_is_not_billed_as_work():
    """The window used to filter the TURN LIST the blocked-stretch scan ran over, so a stretch with
    one end outside lost its pair and the whole gap read as work. Measured on a real build at
    `--from-turn 525 --to-turn 570`: an agent that worked 0.07 of the window's 14.63 minutes
    reported 14.55 minutes busy — round one's lie inverted, and larger."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_bounded_session(tmp)
        # answers at 09:58, blocked across the 10:00 opening, resumes at 10:09 and works one minute
        make_spanning_agent(cost.subagent_dir(session), "b1", "Trace the blocked one",
                            start="2026-08-02T09:57:00.000Z", end="2026-08-02T09:58:00.000Z",
                            woken="2026-08-02T10:09:00.000Z",
                            woke_until="2026-08-02T10:10:00.000Z")
        bound = cost.build_report(session, from_turn=0, to_turn=1)
        assert round(bound.agent_busy_seconds / 60) == 1, bound.agent_busy_seconds
        agent = cost.read_run(session, from_turn=0, to_turn=1)[1][0]
        assert round(agent.duration / 60) == 1, "it worked one of the window's ten minutes"
        assert round(agent.blocked_seconds / 60) == 9, "the other nine were the block"


def test_a_bound_does_not_merge_two_fanouts_into_one():
    """`stagger` is printed to stop a reader reaching for the launch-order lever, and a window
    clamped every running agent to one start — so waves fused and the number collapsed. Measured
    across one build's 564 usable `--from-turn` values: fan-outs merged on 86 of them, and stagger
    was wrong on 291, under-reported as far as 0.0 s against a true 27.8 s."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_bounded_session(tmp)
        agents = cost.subagent_dir(session)
        # wave one launches before the window opens, wave two four minutes later
        make_spanning_agent(agents, "w1a", "Trace one", start="2026-08-02T09:59:00.000Z",
                            end="2026-08-02T10:03:00.000Z")
        make_spanning_agent(agents, "w1b", "Trace two", start="2026-08-02T09:59:20.000Z",
                            end="2026-08-02T10:03:00.000Z")
        make_spanning_agent(agents, "w2", "Trace three", start="2026-08-02T10:06:00.000Z",
                            end="2026-08-02T10:08:00.000Z")
        bound = cost.build_report(session, from_turn=0, to_turn=1)
        assert len(bound.batches) == 2, "two launches four minutes apart are two fan-outs"
        assert round(bound.batches[0]["stagger"]) == 20, bound.batches[0]["stagger"]


def test_an_agent_spawned_after_the_bound_is_not_this_builds_agent():
    """A post-build question that fans out is the session's work, not the build's — it must leave
    the agent count and the bill alone, the way the lead's own post-build turns already do."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_bounded_session(tmp)
        make_spanning_agent(cost.subagent_dir(session), "late", "Harvest the leftovers",
                            start="2026-08-02T10:25:00.000Z", end="2026-08-02T10:27:00.000Z")
        assert cost.build_report(session).agents == 1
        after = cost.build_report(session, to_turn=1)
        assert after.agents == 0
        assert after.usage["output_tokens"] == 2 * 100, "only the lead's two build turns are billed"


def test_a_window_with_nothing_in_it_is_an_error_not_a_zero_report():
    """Silently reporting a $0 build for a mistyped bound is the failure this refuses."""
    with tempfile.TemporaryDirectory() as td:
        session = make_session(Path(td))
        try:
            cost.build_report(session, from_turn=999)
        except ValueError as exc:
            assert "no timestamped turns" in str(exc)
        else:
            raise AssertionError("an empty window must raise")


def test_cli_reports_and_exits_zero(capsys):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_session(tmp)
        make_map(tmp / "map.json", 50)
        assert cost.main([str(session), "--map", str(tmp / "map.json")]) == 0
        out = capsys.readouterr().out
        assert "BUILD" in out and "TOKENS" in out and "PER UNIT OF MAP" in out


def test_cli_json_is_machine_readable(capsys):
    with tempfile.TemporaryDirectory() as td:
        session = make_session(Path(td))
        assert cost.main([str(session), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["requests"] == 1 and "by_role" in payload


def test_cli_rejects_a_bad_cache_ttl(capsys):
    with tempfile.TemporaryDirectory() as td:
        session = make_session(Path(td))
        assert cost.main([str(session), "--cache-ttl", "1d"]) == 2
        assert "5m or 1h" in capsys.readouterr().err


def test_a_session_with_no_subagents_says_so(capsys):
    with tempfile.TemporaryDirectory() as td:
        session = make_session(Path(td))
        assert cost.main([str(session)]) == 0
        assert "LEAD ONLY" in capsys.readouterr().err


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))


def test_the_refutation_rate_is_divided_by_what_was_actually_challenged(tmp_path):
    """`claims_total` is the size of the WORKLIST; `claims_challenged` is how many a skeptic read.

    They are equal on a complete pass, which is why reading the wrong one survived: one real build's
    1.26% was right by luck. On a PARTIAL pass they are not — the other real build has 743 challenged
    of 1,385, and the rate the method tells you to read was printed as 0.4% for a true 0.8%."""
    from pathlib import Path
    from dataclasses import asdict
    from coyomap_eval.cost import read_map
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"title": "t", "goal": "g", "grounding": {
        "claims_total": 1385, "claims_challenged": 743,
        "claims_refuted": 6, "claims_unverifiable": 0}}), encoding="utf-8")
    read = read_map(Path(p))
    assert read is not None, "a map with a grounding block must read"
    facts = asdict(read)
    assert facts["claims_challenged"] == 743, facts
    assert 100 * facts["claims_refuted"] / facts["claims_challenged"] > 0.8


def test_a_map_without_the_challenged_field_falls_back_to_the_total(tmp_path):
    """Maps written before the field existed must still report a rate rather than a divide-by-zero."""
    from pathlib import Path
    from dataclasses import asdict
    from coyomap_eval.cost import read_map
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"title": "t", "goal": "g", "grounding": {
        "claims_total": 500, "claims_refuted": 5}}), encoding="utf-8")
    read = read_map(Path(p))
    assert read is not None, "a map with a grounding block must read"
    assert asdict(read)["claims_challenged"] == 500


# --- an agent is not charged for its coordinator's latency -------------------------
# The two "slowest" agents of a measured build held 4.7 and 6.9 minutes of sitting still between
# returning an answer and the follow-up arriving; the rework after each reply took about a minute.
# Ranking stragglers on the raw span measures the LEAD's round trip and calls it the agent's.


def _turn(index: int, role: str, stamp: str, *, tool_results=()):
    from coyomap_eval.transcript import Turn as T
    return T(index=index, role=role, timestamp=stamp, tool_results=tool_results)


def test_duration_excludes_the_wait_for_a_coordinator_follow_up():
    from coyomap_eval.cost import Actor
    from coyomap_eval.transcript import ToolResult
    agent = Actor(name="trace-gateway", role="trace", turns=(
        _turn(0, "assistant", "2026-08-17T09:13:00Z"),
        # an ordinary tool round trip: the user turn CARRIES a result, so it is work, not a block
        _turn(1, "user", "2026-08-17T09:14:00Z",
              tool_results=(ToolResult(tool_use_id="t", content="ok"),)),
        _turn(2, "assistant", "2026-08-17T09:15:00Z"),      # the agent's answer
        _turn(3, "user", "2026-08-17T09:20:00Z"),           # coordinator follow-up, 5 min later
        _turn(4, "assistant", "2026-08-17T09:21:00Z"),      # 1 min of rework
    ))
    assert agent.span == 8 * 60
    assert agent.blocked_seconds == 5 * 60
    assert agent.duration == 3 * 60


def test_an_agent_that_was_never_resumed_is_unchanged():
    from coyomap_eval.cost import Actor
    from coyomap_eval.transcript import ToolResult
    agent = Actor(name="skeptic-rule-1", role="verify", turns=(
        _turn(0, "assistant", "2026-08-17T09:53:00Z"),
        _turn(1, "user", "2026-08-17T09:56:00Z",
              tool_results=(ToolResult(tool_use_id="t", content="ok"),)),
        _turn(2, "assistant", "2026-08-17T09:59:00Z"),
    ))
    assert agent.blocked_seconds == 0.0
    assert agent.duration == agent.span == 6 * 60


# --- the thinking / written split, and the bill by charge type -----------------------------------
#
# Both numbers were computable from the first version of this file and neither was printed. On a
# measured pair of skeptic arms, two models produced the SAME written output (15,348 vs 18,429
# tokens) while one reasoned 4.7x longer — read as one `output` figure, the cheaper model just
# looks more expensive per agent and the reason is invisible. And on the mcpolis build, 67% of
# $240.77 was re-reading accumulated context while output was 13%, so the lever everyone reaches
# for first (a cheaper output rate) moves the smallest term.

def make_usage(output: int = 1000, thinking: int | None = None,
               cache_read: int = 100_000, cache_write: int = 2_000) -> dict[str, object]:
    u: dict[str, object] = {"input_tokens": 3, "output_tokens": output,
                            "cache_read_input_tokens": cache_read,
                            "cache_creation_input_tokens": cache_write}
    if thinking is not None:
        u["output_tokens_details"] = {"thinking_tokens": thinking}
    return u


def make_thinking_session(tmp: Path, thinking: int | None = 400) -> Path:
    records = make_assistant_records(
        "m1", [("c1", "Bash", "rg foo")], make_usage(thinking=thinking),
        {"c1": "2026-08-02T10:00:00.000Z"})
    records.append(make_result_record("c1", "2026-08-02T10:00:10.000Z"))
    return write_jsonl(tmp / "session.jsonl", records)


def test_thinking_is_read_from_the_output_details() -> None:
    with tempfile.TemporaryDirectory() as td:
        turns = [t for t in read_turns(make_thinking_session(Path(td))) if t.usage]
        assert turns[0].usage.thinking_tokens == 400
        assert turns[0].usage.written_tokens == 600


def test_a_harness_that_reports_no_detail_leaves_thinking_at_zero() -> None:
    """Every older transcript is in this shape, and it must read as 'not reported', never as an
    error and never as a guess."""
    with tempfile.TemporaryDirectory() as td:
        turns = [t for t in read_turns(make_thinking_session(Path(td), thinking=None)) if t.usage]
        assert turns[0].usage.thinking_tokens == 0
        assert turns[0].usage.written_tokens == turns[0].usage.output_tokens


def test_written_never_goes_negative() -> None:
    """`thinking_tokens` comes from a different field than `output_tokens`. A harness reporting
    one without the other would otherwise make the SPEND block wrong in a direction nobody looks."""
    assert Usage(output_tokens=10, thinking_tokens=99).written_tokens == 0


def test_thinking_is_merged_by_max_like_every_other_count() -> None:
    """The records of one response repeat its usage; summing them double-counts."""
    with tempfile.TemporaryDirectory() as td:
        records = make_assistant_records(
            "m1", [("c1", "Bash", "a"), ("c2", "Bash", "b")], make_usage(thinking=400),
            {"c1": "2026-08-02T10:00:00.000Z", "c2": "2026-08-02T10:01:00.000Z"})
        records.append(make_result_record("c2", "2026-08-02T10:01:10.000Z"))
        turns = [t for t in read_turns(write_jsonl(Path(td) / "s.jsonl", records)) if t.usage]
        assert len(turns) == 1
        assert turns[0].usage.thinking_tokens == 400, "summing the records would give 800"


def test_the_charge_split_adds_up_to_the_total() -> None:
    """One writer for the arithmetic, so the split and the total cannot drift apart."""
    u = Usage(input_tokens=1_000, output_tokens=2_000,
              cache_read_input_tokens=3_000_000, cache_creation_input_tokens=40_000)
    charges = cost.charges_of(u, "claude-opus-5", "5m")
    assert charges is not None
    assert abs(charges.total - (cost.cost_of(u, "claude-opus-5", "5m") or 0.0)) < 1e-12


def test_each_charge_is_priced_at_its_own_multiplier() -> None:
    u = Usage(output_tokens=1_000_000, cache_read_input_tokens=1_000_000,
              cache_creation_input_tokens=1_000_000)
    c = cost.charges_of(u, "claude-opus-5", "5m")
    assert c is not None
    assert c.output == 25.0                      # output rate
    assert c.cache_read == 5.0 * 0.1             # input rate x 0.1
    assert c.cache_write == 5.0 * 1.25           # input rate x 1.25 at a 5m TTL


def test_an_unpriced_model_has_no_charges() -> None:
    assert cost.charges_of(Usage(output_tokens=99), "some-other-model", "5m") is None


def test_the_report_shows_written_and_thinking_apart(capsys) -> None:
    with tempfile.TemporaryDirectory() as td:
        assert cost.main([str(make_thinking_session(Path(td)))]) == 0
        out = capsys.readouterr().out
        assert "written" in out and "thinking" in out
        assert "600" in out and "400" in out
        assert "SHARE of output" in out, "the two must not read as separate charges"


def test_the_spend_block_names_where_the_money_went(capsys) -> None:
    with tempfile.TemporaryDirectory() as td:
        assert cost.main([str(make_thinking_session(Path(td)))]) == 0
        out = capsys.readouterr().out
        assert "SPEND" in out
        assert "re-reading its own context" in out


def make_sidechain_agent_file(tmp: Path) -> Path:
    """One sub-agent's OWN transcript: every record marked `isSidechain`."""
    records = make_assistant_records(
        "m1", [("c1", "Bash", "rg foo")], make_usage(thinking=400),
        {"c1": "2026-08-02T10:00:00.000Z"})
    records.append(make_result_record("c1", "2026-08-02T10:00:10.000Z"))
    for r in records:
        r["isSidechain"] = True
    return write_jsonl(tmp / "agent-x.jsonl", records)


def test_a_subagent_transcript_is_refused_with_the_flag_that_reads_it(capsys) -> None:
    """The default filter drops every record of such a file. Refusing with a bare 'no turns' is
    what sent one reader off to hand-roll the arithmetic, and the hand roll summed the
    per-content-block records and overstated the bill by 1.7x."""
    with tempfile.TemporaryDirectory() as td:
        assert cost.main([str(make_sidechain_agent_file(Path(td)))]) == 2
        err = capsys.readouterr().err
        assert "--include-sidechains" in err
        assert "SUB-AGENT" in err


def test_the_flag_reads_that_transcript(capsys) -> None:
    with tempfile.TemporaryDirectory() as td:
        path = make_sidechain_agent_file(Path(td))
        assert cost.main([str(path), "--include-sidechains"]) == 0
        assert "TOKENS" in capsys.readouterr().out


def test_a_plain_session_is_not_told_about_the_flag(capsys) -> None:
    """Never pass it for a build session: there the sidechains ARE the sub-agents, already read
    from <session>/subagents/, so it would count them twice. The hint must not invite that."""
    with tempfile.TemporaryDirectory() as td:
        empty = write_jsonl(Path(td) / "s.jsonl", [{"type": "assistant", "message": {"id": "m"}}])
        assert cost.main([str(empty)]) == 2
        assert "--include-sidechains" not in capsys.readouterr().err


def test_the_fanout_table_reports_what_each_batch_cost(capsys) -> None:
    """`waste` answers which barrier was slow, never which fan-out was dear. On a real build the
    two disagree: batch #6 held the barrier 5.3 minutes and billed nothing, while batch #10 cost
    $50.04 — the most expensive in the build — with almost the same waste."""
    with tempfile.TemporaryDirectory() as td:
        session = make_session(Path(td))
        make_agent(cost.subagent_dir(session), "a1", "T1 trace checkout", 4.0)
        assert cost.main([str(session)]) == 0
        out = capsys.readouterr().out
        header = [ln for ln in out.splitlines() if ln.strip().startswith("#")][0]
        assert "$" in header and "think" in header
        report = cost.build_report(session)
        assert report.batches and report.batches[0]["cost"] > 0


def test_a_batch_whose_agents_have_no_billed_turns_costs_nothing() -> None:
    """It must read as zero, not as an error: a relaunched agent leaves a timed shell with no
    usage, and 19 of one build's 61 sub-agents were exactly that."""
    with tempfile.TemporaryDirectory() as td:
        batch = cost.Batch(index=0, start=0.0, end=60.0,
                           agents=(cost.Actor(name="dead", role="trace", turns=()),))
        assert batch.cost("5m") == 0.0
        assert batch.thinking_share() == 0.0


def make_straddling_session(tmp: Path) -> Path:
    """A lead of four turns, 10:00 to 10:30, with an agent that works across the middle two.

    The shape a mid-build `--from-turn` makes: the agent is dispatched at 10:05, spends before the
    bound and spends after it, so neither "keep it all" nor "drop it all" can be right."""
    records = [
        {"type": "assistant", "timestamp": f"2026-08-02T{stamp}.000Z",
         "message": {"id": f"m{i}", "model": "claude-opus-5", "usage": {"output_tokens": 100},
                     "content": [{"type": "text", "text": str(i)}]}}
        for i, stamp in enumerate(("10:00:00", "10:10:00", "10:20:00", "10:30:00"))
    ]
    session = write_jsonl(tmp / "s.jsonl", records)
    make_spanning_agent(cost.subagent_dir(session), "w1", "Harvest the backend slice",
                        start="2026-08-02T10:05:00.000Z", end="2026-08-02T10:08:00.000Z",
                        woken="2026-08-02T10:23:00.000Z", woke_until="2026-08-02T10:25:00.000Z")
    return session


def test_a_leading_bound_cuts_the_bill_and_a_trailing_bound_never_does():
    """The two edges are not symmetric, and one rule cannot be right at both.

    Past a trailing bound the build still pays: it spawned the straggler, and "dollars, except the
    ones a straggler spent after the commit" is a quantity nobody can compare across builds.
    Before a leading bound the build never owed: that spend belongs to whatever ran first. Kept
    whole at both edges, `--from-turn 500` on the reminderrepo build billed 464 calls and $61.47
    against a windowed 90 calls and $27.77 — 55% of the bill for work that finished before the
    window opened, while the clock had already dropped to match the window."""
    with tempfile.TemporaryDirectory() as td:
        session = make_straddling_session(Path(td))
        whole = cost.build_report(session)
        assert whole.requests == 7, "4 lead turns + 3 agent calls"

        trailing = cost.build_report(session, to_turn=1)
        assert trailing.requests == 5, "the agent's post-bound wake is still billed"
        assert trailing.wall_seconds / 60 == 10, "while its clock stops at the bound"

        leading = cost.build_report(session, from_turn=2)
        assert leading.requests == 3, "2 lead turns + only the agent's post-bound wake"
        assert leading.cost < trailing.cost


def make_growing_agent(dir_path: Path, name: str, description: str,
                       stamps_and_context: list[tuple[str, int]]) -> None:
    """A sub-agent whose context GROWS call by call, as a real one's does.

    `make_spanning_agent` gives every call the same usage, so a test written on it cannot tell the
    first call from the last and any assertion about base context passes whatever the code reads.
    That is the defect this whole pass keeps finding, in a test instead of in a check."""
    dir_path.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for n, (stamp, context) in enumerate(stamps_and_context):
        records.append({"type": "assistant", "isSidechain": True, "timestamp": stamp,
                        "message": {"id": f"{name}-{n}", "model": "claude-opus-5",
                                    "usage": {"input_tokens": 1, "output_tokens": 500,
                                              "cache_read_input_tokens": context - 1},
                                    "content": [{"type": "text", "text": str(n)}]}})
    write_jsonl(dir_path / f"agent-{name}.jsonl", records)
    (dir_path / f"agent-{name}.meta.json").write_text(
        json.dumps({"description": description}), encoding="utf-8")


def test_a_leading_bound_does_not_move_an_agents_base_context():
    """The fixed overhead is paid at DISPATCH, so a bound landing after it changes nothing.

    Read off the first call INSIDE the window instead, an agent already running would report its
    accumulated context as its fixed cost — the one number this property exists to isolate. Here
    the agent opens at 20,000 tokens of brief and overhead and is at 90,000 by its last call."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_bounded_session(tmp)
        make_growing_agent(cost.subagent_dir(session), "g1", "Harvest the backend slice",
                           [("2026-08-02T10:02:00.000Z", 20_000),
                            ("2026-08-02T10:14:00.000Z", 50_000),
                            ("2026-08-02T10:16:00.000Z", 90_000)])
        assert cost.build_report(session).base_context_median == 20_000
        assert cost.build_report(session, from_turn=1).base_context_median == 20_000, (
            "the brief was paid at dispatch, before the bound")


# --- the lead's context window ---------------------------------------------------------
# A lead whose context fills is replaced by a summary, and the build goes on from the summary as if
# it still held everything. Two of three measured mcpolis builds did so, at 967,939 and 968,360
# tokens, and the first one went unreported for two retros because nothing printed it.


def make_lead_response(message_id: str, stamp: str, context: int) -> dict[str, object]:
    """One lead response whose request read `context` tokens."""
    return {"type": "assistant", "timestamp": stamp,
            "message": {"id": message_id, "model": "claude-opus-5",
                        "usage": {"input_tokens": 1, "output_tokens": 10,
                                  "cache_read_input_tokens": context - 1,
                                  "cache_creation_input_tokens": 0},
                        "content": [{"type": "text", "text": "working"}]}}


def make_operator_message(stamp: str, text: str, **extra: object) -> dict[str, object]:
    return {"type": "user", "timestamp": stamp, "message": {"content": text}, **extra}


def make_boundary_record(stamp: str, pre: int, post: int, *,
                         sidechain: bool = False) -> dict[str, object]:
    """The record the harness writes when it replaces a context with a summary."""
    return {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted",
            "isSidechain": sidechain, "timestamp": stamp,
            "compactMetadata": {"trigger": "auto", "preTokens": pre, "postTokens": post}}


def make_compacted_session(tmp: Path) -> Path:
    """A lead that grows to 960,000 tokens, is compacted, and goes on from a 13,000-token summary.

    Turns: 0 operator, 1 lead (100,000), 2 operator, 3 lead (960,000), 4 the summary, 5 lead."""
    records = [
        make_operator_message("2026-10-06T22:00:00.000Z", "/coyomap build"),
        make_lead_response("m1", "2026-10-06T22:00:05.000Z", 100_000),
        make_operator_message("2026-10-06T22:30:00.000Z", "next"),
        make_lead_response("m2", "2026-10-06T22:30:05.000Z", 960_000),
        make_boundary_record("2026-10-06T23:00:00.300Z", 967_000, 13_000),
        make_operator_message("2026-10-06T23:00:00.000Z",
                              "This session is being continued from a previous conversation",
                              isCompactSummary=True),
        make_lead_response("m3", "2026-10-06T23:00:10.000Z", 20_000),
    ]
    return write_jsonl(tmp / "session.jsonl", records)


def test_the_report_names_the_leads_first_and_peak_context():
    with tempfile.TemporaryDirectory() as td:
        context = cost.build_report(make_compacted_session(Path(td))).context
        assert context.lead_first == 100_000
        assert context.lead_peak == 960_000
        assert context.lead_peak_turn == 3


def test_a_compaction_is_reported_at_the_turn_that_ran_on_the_summary():
    """The boundary record carries the tokens before and after; the turn is the first one after it
    in the file, which is the summary itself."""
    with tempfile.TemporaryDirectory() as td:
        compactions = cost.build_report(make_compacted_session(Path(td))).context.compactions
        assert compactions == (cost.Compaction(turn=4, trigger="auto", pre_tokens=967_000,
                                               post_tokens=13_000,
                                               timestamp="2026-10-06T23:00:00.300Z"),)


def test_the_text_report_leads_with_the_compaction():
    """Printed before the fan-out table, and loud: a retro reads the top of this report first."""
    with tempfile.TemporaryDirectory() as td:
        text = cost.format_report(cost.build_report(make_compacted_session(Path(td))))
        assert text.index("CONTEXT") < text.index("FAN-OUT")
        assert "COMPACTED 1 time(s)" in text
        assert "turn 4" in text and "967,000" in text


def test_a_compaction_after_the_build_bound_is_not_this_builds():
    """A session keeps going after the commit; a summary there says nothing about the build."""
    with tempfile.TemporaryDirectory() as td:
        report = cost.build_report(make_compacted_session(Path(td)), to_turn=3)
        assert report.context.compactions == ()
        assert "COMPACTED" not in cost.format_report(report)


def test_a_range_holding_only_the_compaction_still_prints_it():
    """Turn 4 is the summary alone: no lead API call, so no context size, but the compaction is in
    range and the text must say so, as `--json` does."""
    with tempfile.TemporaryDirectory() as td:
        report = cost.build_report(make_compacted_session(Path(td)), from_turn=4, to_turn=4)
        text = cost.format_report(report)
        assert report.context.compactions
        assert "COMPACTED 1 time(s)" in text and "turn 4" in text
        assert "no lead API call in this turn range" in text


def test_a_peak_near_the_compaction_point_is_flagged_even_without_one():
    """The previous build ended at 937,840 tokens with no summary; the next one compacted."""
    with tempfile.TemporaryDirectory() as td:
        session = write_jsonl(Path(td) / "session.jsonl", [
            make_operator_message("2026-10-06T22:00:00.000Z", "/coyomap build"),
            make_lead_response("m1", "2026-10-06T22:00:05.000Z", 937_840),
        ])
        text = cost.format_report(cost.build_report(session))
        assert "COMPACTED" not in text
        assert "near the point where the harness compacts" in text


def test_a_lean_lead_raises_no_flag():
    with tempfile.TemporaryDirectory() as td:
        session = write_jsonl(Path(td) / "session.jsonl", [
            make_operator_message("2026-10-06T22:00:00.000Z", "/coyomap build"),
            make_lead_response("m1", "2026-10-06T22:00:05.000Z", 400_000),
        ])
        text = cost.format_report(cost.build_report(session))
        assert "COMPACTED" not in text and "near the point" not in text


def test_a_compacted_subagent_is_counted_and_named():
    with tempfile.TemporaryDirectory() as td:
        session = make_compacted_session(Path(td))
        agents = cost.subagent_dir(session)
        make_agent(agents, "quiet", "Skeptic security-1", minutes=1.0)
        make_agent(agents, "full", "Harvest h-t5 domain model", minutes=1.0)
        with (agents / "agent-full.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(make_boundary_record("2026-08-02T10:05:30.000Z", 968_000, 9_000,
                                                     sidechain=True)) + "\n")
        assert cost.build_report(session).context.subagents_compacted == (
            "Harvest h-t5 domain model",)


def test_a_helper_run_build_reports_its_own_compaction():
    """A build that ran AS a sub-agent is profiled from that agent's own file, every record a
    sidechain. Its boundary record is a sidechain too, and still the lead's."""
    with tempfile.TemporaryDirectory() as td:
        records: list[dict[str, object]] = [
            {**make_operator_message("2026-09-29T21:00:00.000Z", "build"), "isSidechain": True},
            {**make_lead_response("m1", "2026-09-29T21:00:05.000Z", 966_062), "isSidechain": True},
            make_boundary_record("2026-09-29T22:20:20.318Z", 968_360, 18_176, sidechain=True),
            {**make_operator_message("2026-09-29T22:20:20.317Z", "continued"), "isSidechain": True,
             "isCompactSummary": True},
            {**make_lead_response("m2", "2026-09-29T22:21:00.000Z", 30_000), "isSidechain": True},
        ]
        session = write_jsonl(Path(td) / "agent-lead.jsonl", records)
        context = cost.build_report(session, include_sidechains=True).context
        assert [c.pre_tokens for c in context.compactions] == [968_360]


def test_the_retro_method_reads_the_context_block_and_ranks_a_compaction_high():
    """Both ends must point at each other: `cost` prints the block, and the retro method tells the
    reader to look at it and what a compaction is worth. A rule only one side states is the rule
    that silently stops happening."""
    method = (Path(__file__).resolve().parents[1] / "retro" / "method.md").read_text(encoding="utf-8")
    assert "CONTEXT" in method and "COMPACTED" in method
    assert "compaction of the lead" in method and "HIGH" in method


# --- nesting: a runner's time is its children's ------------------------------------


def make_nested_agent(dir_path: Path, agent_id: str, description: str, *, start: str, end: str,
                      parent: str | None = None) -> None:
    """A sub-agent file named the way the harness names it (`agent-<id>.jsonl`), whose
    `.meta.json` carries `parentAgentId` when another agent spawned it."""
    make_spanning_agent(dir_path, agent_id, description, start=start, end=end)
    meta: dict[str, object] = {"description": description}
    if parent is not None:
        meta["parentAgentId"] = parent
        meta["spawnDepth"] = 2
    (dir_path / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def make_runner_build(tmp: Path) -> Path:
    """The lead spawns one runner at 10:00 that runs until 10:30; the runner spawns three
    skeptics at 10:01 that take 3, 3 and 9 minutes. Shaped on the 2026-10-08 mcpolis build,
    where the wave-1 runner read as a 53.0-minute straggler of the lead's fan-out."""
    records = [
        {"type": "assistant", "timestamp": f"2026-08-02T{stamp}.000Z",
         "message": {"id": f"m{i}", "model": "claude-opus-5", "usage": {"output_tokens": 100},
                     "content": [{"type": "text", "text": str(i)}]}}
        for i, stamp in enumerate(("10:00:00", "10:31:00"))
    ]
    session = write_jsonl(tmp / "s.jsonl", records)
    agents = cost.subagent_dir(session)
    make_nested_agent(agents, "r1", "Fact-check wave 1 runner",
                      start="2026-08-02T10:00:00.000Z", end="2026-08-02T10:30:00.000Z")
    for name, minutes in (("k1", 3), ("k2", 3), ("k3", 9)):
        make_nested_agent(agents, name, f"skeptic {name}", parent="r1",
                          start="2026-08-02T10:01:00.000Z",
                          end=f"2026-08-02T10:{1 + minutes:02d}:00.000Z")
    return session


def test_a_runner_is_not_timed_as_a_straggler_of_the_leads_fanout():
    with tempfile.TemporaryDirectory() as td:
        report = cost.build_report(make_runner_build(Path(td)))
        assert len(report.batches) == 1, report.batches
        batch = report.batches[0]
        assert batch["agents"] == 3.0, "the runner is no row; its three skeptics are"
        assert round(cost._num(batch, "slowest") / 60) == 9, "the slowest SKEPTIC, not the runner"
        assert round(cost._num(batch, "waste") / 60) == 4, "9 minutes wall minus a 5-minute mean"
        assert batch["via"] == "Fact-check wave 1 runner"
        assert (report.runners, report.nested) == (1, 3)


def test_the_text_report_names_the_runner_and_its_pool(capsys):
    with tempfile.TemporaryDirectory() as td:
        assert cost.main([str(make_runner_build(Path(td)))]) == 0
        out = capsys.readouterr().out
        assert "1 runner(s) dispatched 3 of them" in out
        assert "Fact-check wave 1 runner" in out.split("FAN-OUT")[1].split("TOKENS")[0]


def test_children_of_a_runner_never_merge_into_the_leads_own_fanout():
    with tempfile.TemporaryDirectory() as td:
        session = make_runner_build(Path(td))
        make_nested_agent(cost.subagent_dir(session), "h1", "Harvest the adapters",
                          start="2026-08-02T10:01:30.000Z", end="2026-08-02T10:03:00.000Z")
        report = cost.build_report(session)
        assert sorted((str(b["via"]), b["agents"]) for b in report.batches) == [
            ("Fact-check wave 1 runner", 3.0), ("lead", 1.0)]


def test_an_agent_whose_parent_is_absent_is_timed_with_the_lead():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = write_jsonl(tmp / "s.jsonl", [
            {"type": "assistant", "timestamp": "2026-08-02T10:00:00.000Z",
             "message": {"id": "m", "model": "claude-opus-5", "usage": {"output_tokens": 1},
                         "content": [{"type": "text", "text": "x"}]}}])
        make_nested_agent(cost.subagent_dir(session), "k1", "skeptic k1", parent="gone",
                          start="2026-08-02T10:01:00.000Z", end="2026-08-02T10:04:00.000Z")
        report = cost.build_report(session)
        assert [b["via"] for b in report.batches] == ["lead"]
        assert report.runners == 0


# --- the model's own latency, beside the per-row time -----------------------------------


def make_reply_session(tmp: Path) -> Path:
    """A lead brief answered at 10:00:00, one tool result at 10:00:05 replied to at 10:00:12, and
    a second result at 10:00:20 replied to at 10:00:23: replies of 7 s and 3 s."""
    usage = {"output_tokens": 10}
    records: list[dict[str, object]] = []
    records += make_assistant_records("m1", [("c1", "Bash", "rg a")], usage,
                                      {"c1": "2026-08-02T10:00:00.000Z"})
    records.append(make_result_record("c1", "2026-08-02T10:00:05.000Z"))
    records += make_assistant_records("m2", [("c2", "Bash", "rg b")], usage,
                                      {"c2": "2026-08-02T10:00:12.000Z"})
    records.append(make_result_record("c2", "2026-08-02T10:00:20.000Z"))
    records += make_assistant_records("m3", [("c3", "Bash", "rg c")], usage,
                                      {"c3": "2026-08-02T10:00:23.000Z"})
    return write_jsonl(tmp / "session.jsonl", records)


def test_the_median_reply_is_read_from_tool_result_to_the_next_reply():
    with tempfile.TemporaryDirectory() as td:
        report = cost.build_report(make_reply_session(Path(td)))
        assert report.reply_seconds == {"claude-opus-5": 5.0}, "median of 7 s and 3 s"


def test_seconds_per_row_prints_the_model_latency_beside_it(capsys):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        session = make_reply_session(tmp)
        map_path = make_map(tmp / "m.json", rows=10)
        assert cost.main([str(session), "--map", str(map_path)]) == 0
        line = next(l for l in capsys.readouterr().out.splitlines() if "seconds per row" in l)
        assert "model median reply 5.0s claude-opus-5" in line
