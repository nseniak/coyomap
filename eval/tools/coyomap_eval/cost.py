#!/usr/bin/env python3
"""`coyomap-eval cost` — what one build SPENT: wall time, tokens, and both per unit of map.

The L3 scorecard asks whether the agent behaved as the method says; this asks what that behaviour
cost. It reads the same build transcript plus the sub-agent transcripts beside it, and reports the
handful of numbers that decide whether a tooling change actually paid:

  time    build wall, active time (idle excluded), fan-out batches, straggler waste, lead-only time
  tokens  per role — lead / harvest / trace / verify — output, cache reads, cache writes, cost
  unit    with `--map`: rows produced, and cost + seconds PER ROW

## Why per-row is the headline and absolute minutes are not

Across four mcpolis builds the map grew 1,195 -> 1,564 rows while the method was being changed
under it. Absolute wall time moved 61-71 min and cost $189-$207, so a build that got *cheaper per
unit of work* read as "slower and more expensive". Anything comparing two builds has to divide by
what they produced, or it measures the map's growth and calls it a regression.

## Why idle time is excluded

A transcript spans the whole session, not the build: a lead that asks the operator a question and
waits 40 minutes records a 130-minute session for a 68-minute build. A gap longer than
`--idle-gap` seconds with NO sub-agent running is operator wait, not work, and is subtracted from
`active`. Gaps with agents running are the lead correctly waiting on its fan-out and stay in.

## What this is not

Not a gate. It emits no verdict and fails nothing — a build costs what it costs. The quality
question is `coyomap-eval run` / `compare`; the two are read together, which is why `--map` also
prints the grounding counts (claims challenged / refuted / unverifiable) next to the spend. A
change that halves the bill and doubles refutations is not an improvement, and one report should
make that visible.

Prices are LIST prices, per model, from the table below — a subscription bills differently. They
are here so two builds are comparable in one unit, not to predict an invoice.

Stdlib only, like the rest of `coyomap_eval`.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from coyomap_eval.compare import Spend
from coyomap_eval.transcript import ToolCall, Turn, Usage, read_turns

#: $ per million tokens (input, output) at list price. Cache reads bill at 0.1x input and cache
#: writes at 1.25x (5-minute TTL) or 2x (1-hour TTL, `--cache-ttl 1h`).
#: A model absent here is reported by name with its tokens and NO cost, rather than silently
#: priced as something else — a wrong number is worse than a missing one.
MODEL_RATES: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = {"5m": 1.25, "1h": 2.0}

#: A lead whose context reaches this is one large fan-out away from being replaced by a summary.
#: Both compactions measured on real builds fired at 967,939 and 968,360 tokens, on a 1M window, and
#: a build that ended at 937,840 with no summary was followed by one that compacted. The harness's
#: own threshold is not written anywhere a reader can see, so this is the measured one.
CONTEXT_NEAR_LIMIT = 900_000

#: Roles are GUESSED from the agent's own description, because nothing in the harness records the
#: phase an agent belonged to. Order matters: "trace" before "harvest" so "Trace the harvest gaps"
#: lands as a trace. A description matching nothing is reported as `other`, never forced into a
#: bucket — a silently mis-bucketed agent moves a whole phase's number.
ROLE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("verify", r"skeptic|refute|verif|adversar"),
    ("trace", r"\btrace\b|flow"),
    ("test/gap", r"\btest|gap|fill\b|complete"),
    ("harvest", r"harvest|structural|dependenc|domain model|surface|owner|ops:|bootstrap|adapter"),
)

ROLE_ORDER = ("lead", "harvest", "trace", "verify", "test/gap", "other")


def classify(description: str) -> str:
    text = description.lower()
    for role, pattern in ROLE_PATTERNS:
        if re.search(pattern, text):
            return role
    return "other"


def _seconds(stamp: str) -> float | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


@dataclass(frozen=True)
class Actor:
    """One participant in the build: the lead, or one sub-agent."""

    name: str
    role: str
    turns: tuple[Turn, ...]
    #: The build's own stretch of clock, set by `read_run` when `--from-turn`/`--to-turn` bound the
    #: run. Every TIME this actor reports is measured inside it; every TOKEN it reports is not.
    #: `None` on an unbounded run, where every record is the build's by definition.
    #:
    #: THE TWO EDGES ARE NOT SYMMETRIC, and each half was decided on its own evidence.
    #:
    #: TRAILING EDGE (`--to-turn`): the bill is kept WHOLE. Everything the build spawned, the build
    #: pays for, however late the last call lands. The argument is not the size of the difference
    #: ($1.05 on the build this was measured from): it is that a reader comparing two builds'
    #: dollars must be comparing the same quantity, and "dollars, except the ones a straggler spent
    #: after the commit" is a quantity nobody can reason about. The clock still stops at the bound,
    #: because a flag named `--to-turn` is a statement about the clock.
    #:
    #: LEADING EDGE (`--from-turn`, and only when the operator passed one — see `bill_from`):
    #: the bill is CUT at the bound. Spend that finished before the
    #: window opened was not this build's to begin with, so keeping it whole is not conservatism,
    #: it is attributing another run's invoice to this one. Measured on the reminderrepo build at
    #: `--from-turn 500`: charging every call gave the SAME $352.10 as the unbounded run, to the
    #: cent, while the clock had fallen from 71.6 to 37.7 wall minutes — a bill that ignores its
    #: own window entirely. The documented use of `--from-turn` (skip an archive step BEFORE the
    #: build) never straddles an agent, so that use is unaffected either way; what this fixes is
    #: the undocumented one, a bound landing mid-build.
    #:
    #: WHY NOT ONE RULE FOR BOTH. Cutting the trailing edge would drop spend the build caused;
    #: keeping the leading edge whole adds spend the build did not cause. Neither edge's answer
    #: makes the other's mistake, so there is no single rule that is right twice.
    #:
    #: An agent that did ANY of its work inside the window is this build's agent: its clock is
    #: clipped to the window and its bill runs from the window's opening to its own last call. One
    #: whose work lies entirely outside is dropped whole, time and tokens together
    #: (`bounded_agents`): it belongs to whatever the session did before the build began or after it
    #: finished. Work in the window, never "started inside it" — `bounded_agents` says what that
    #: mistake cost.
    window: tuple[float, float] | None = None
    #: Where this actor's BILL starts, when the operator asked for a leading bound. `None` leaves
    #: the bill whole, which is right for every run nobody bounded at the front.
    #:
    #: SEPARATE FROM `window` ON PURPOSE, because the two lows mean different things. A `--to-turn`
    #: run has `from_turn` 0 and still gets a window, whose low is just where the LEAD happened to
    #: start — not a boundary anybody stated. Billing from it deletes the calls of an agent that
    #: began moments before the lead's first turn: on one measured transcript, an agent starting
    #: 1 second early lost a call it plainly made for this build. The clock still clips there, and
    #: should, because the build's time cannot start before the build did.
    bill_from: float | None = None
    #: The harness's id for this sub-agent (its file is `agent-<id>.jsonl`). Empty for the lead.
    agent_id: str = ""
    #: The id of the agent that SPAWNED this one, from `parentAgentId` in its `.meta.json`. Empty
    #: when the lead spawned it. A sub-agent can start sub-agents of its own: the 2026-10-08
    #: mcpolis build ran each fact-check wave as one runner agent that dispatched 76 and 5
    #: skeptics. Read flat, the wave-1 runner was a "53.0-minute straggler" and 45.0 of the
    #: build's 118.0 straggler minutes were it supervising its own pool, while its skeptics showed
    #: up as five more fan-outs of the lead. See `runner_ids` and `batches`.
    parent_id: str = ""

    @property
    def timed_turns(self) -> tuple[Turn, ...]:
        """The turns whose CLOCK belongs to the build — all of them when the run is unbounded.

        `--to-turn` bounds the lead by turn index, and a sub-agent has no index in that numbering,
        so its span ran on to its last record whatever the bound said. An agent that started a
        background command is woken again when the command completes, which can be long after the
        build committed: on one measured build that put an agent's last record 12.9 minutes past
        the commit, and the fan-out table charged the whole 14.6-minute gap as straggler waste —
        22.3 minutes of it, on a build whose lead ran 42.0 minutes end to end. Bounding the agent
        by the same window as the lead is what makes the two numbers describe one build.

        THE BILL IS BOUNDED ONLY AT THE LEADING EDGE — `requests` applies the window's low bound
        and never its high one. Past the trailing bound the build still pays; before the leading
        bound it never owed. See `window` for why one rule cannot be right at both edges."""
        if self.window is None:
            return self.turns
        low, high = self.window
        return tuple(t for t in self.turns
                     if (s := _seconds(t.timestamp)) is None or low <= s <= high)

    @property
    def _raw_stamps(self) -> tuple[float, ...]:
        """Every stamp the actor carries, window or no window — the raw material `work_spans`
        starts from, and what `launched_at` reads."""
        return tuple(s for s in (_seconds(t.timestamp) for t in self.turns) if s is not None)

    @property
    def stamps(self) -> tuple[float, ...]:
        return tuple(s for s in (_seconds(t.timestamp) for t in self.timed_turns) if s is not None)

    @property
    def work_spans(self) -> list[tuple[float, float]]:
        """THE one definition of when this actor was WORKING. Everything timed reads it.

        Its whole span, minus the stretches it sat blocked on its coordinator, intersected with the
        build's window. Three readings of that one question used to exist side by side — a raw
        first-to-last span, a blocked-corrected duration, and a window-filtered turn list — and they
        disagreed in both directions on real transcripts: one agent reported 0 minutes of the 4.56 it
        worked, and another reported 14.55 busy minutes of a window it worked 4 seconds of. Both
        were arithmetic between two of the three readings.

        THE WINDOW IS APPLIED LAST, to the working stretches, and that is what makes the two edges
        come out right without either being special-cased. An actor still working when the window
        opened has its stretch clipped and so starts at the bound; one that was BLOCKED across the
        opening has no stretch there at all and starts at its resume; one that answered before the
        window closed ends at that answer, not at the bound, so a straggler's post-commit wake is
        cut. The old code needed an explicit clamp and an explicit refusal to clamp for that, and
        the clamp invented busy time on 305 of one build's 565 possible `--from-turn` values."""
        stamps = self._raw_stamps
        if not stamps:
            return []
        spans = _subtract((min(stamps), max(stamps)), _union(self._blocked_spans))
        if self.window is None:
            return spans
        low, high = self.window
        return [(s, e) for s, e in ((max(s, low), min(e, high)) for s, e in spans) if e > s]

    @property
    def launched_at(self) -> float | None:
        """This actor's FIRST record, window or no window — when the lead dispatched it.

        Batch clustering and `stagger` read this, never `start`. A window clips `start`, so every
        actor already running when it opened shares one start and the waves merge into each other:
        one bounded run reported 4 fan-outs against 5 real, and a dispatch stagger of 179.8 s
        against a true 81.7 s — on the very number that is printed to stop a reader reaching for
        the launch-order lever. When an actor was LAUNCHED is a fact about the transcript, and no
        bound on the report changes it."""
        return min(self._raw_stamps, default=None)

    @property
    def start(self) -> float | None:
        """Where this actor's work begins inside the window."""
        spans = self.work_spans
        return spans[0][0] if spans else None

    @property
    def end(self) -> float | None:
        """Where its work ends inside the window."""
        spans = self.work_spans
        return spans[-1][1] if spans else None

    @property
    def duration(self) -> float:
        """Time actually spent working, blocked stretches removed and the window applied.

        A sub-agent that returns its answer and is then sent a follow-up keeps one transcript, so
        its raw span includes the round trip it had no part in. On a measured build the two
        "slowest" agents of the run — 18.9 min and 15.6 min — held 4.7 and 6.9 minutes of exactly
        that, and the rework after each reply took about a minute: the second agent's headline
        number was more idle than work. Ranking stragglers on the raw span, or charging a batch's
        `waste` with it, measures the LEAD's latency and calls it the agent's."""
        return sum(e - s for s, e in self.work_spans)

    @property
    def span(self) -> float:
        """First working moment to last, blocked time included. What a naive file read reports."""
        s, e = self.start, self.end
        return (e - s) if (s is not None and e is not None) else 0.0

    @property
    def _blocked_spans(self) -> list[tuple[float, float]]:
        """Stretches between this actor finishing an answer and its coordinator's next message.

        Keyed on the RESUME, never on gap length alone: a slow tool call also leaves a gap, and
        subtracting those would understate real work. The boundary is an assistant turn followed by
        a user turn that is not a tool result — which is what a coordinator follow-up looks like,
        and what an ordinary tool round trip never does.

        READ FROM `self.turns`, NEVER `self.timed_turns`. A window filter drops the PAIR whenever
        one of its two turns falls outside, so a blocked stretch straddling the bound vanishes and
        the whole gap is then billed as work. Measured on a real build at `--from-turn 525
        --to-turn 570`: an agent that worked 0.07 of the window's 14.63 minutes reported 14.55
        minutes busy. The window is applied to the RESULT, in `work_spans`, which is the only place
        it can be applied without losing the stretch that crosses the edge."""
        out: list[tuple[float, float]] = []
        previous: "Turn | None" = None
        for turn in self.turns:
            if (previous is not None and previous.role == "assistant" and turn.role == "user"
                    and not turn.tool_results):
                a, b = _seconds(previous.timestamp), _seconds(turn.timestamp)
                if a is not None and b is not None and b > a:
                    out.append((a, b))
            previous = turn
        return out

    @property
    def blocked_seconds(self) -> float:
        """How much of the window this actor spent blocked on its coordinator."""
        spans = _union(self._blocked_spans)
        if self.window is None:
            return sum(e - s for s, e in spans)
        low, high = self.window
        return sum(max(0.0, min(e, high) - max(s, low)) for s, e in spans)

    @property
    def _all_requests(self) -> tuple[Turn, ...]:
        """Every API call this actor ever made, window or no window."""
        return tuple(t for t in self.turns if t.usage)

    @property
    def requests(self) -> tuple[Turn, ...]:
        """The API calls this BUILD is billed for — one per assistant turn carrying a usage block.

        Cut at the window's LOW bound and never at its high one; `window` carries the evidence for
        the asymmetry. A call the clock cannot place is kept, as in `timed_turns`: an unplaceable
        stamp is a gap in the transcript, and dropping the call would silently shrink the bill."""
        if self.bill_from is None:
            return self._all_requests
        return tuple(t for t in self._all_requests
                     if (s := _seconds(t.timestamp)) is None or s >= self.bill_from)

    def totals(self) -> Usage:
        out = Usage()
        for t in self.requests:
            u = t.usage
            out = Usage(out.input_tokens + u.input_tokens,
                        out.output_tokens + u.output_tokens,
                        out.cache_read_input_tokens + u.cache_read_input_tokens,
                        out.cache_creation_input_tokens + u.cache_creation_input_tokens,
                        out.thinking_tokens + u.thinking_tokens)
        return out

    @property
    def base_context(self) -> int:
        """The context of this actor's FIRST request — its fixed per-turn overhead (system prompt,
        tool schemas, connected servers) plus its own brief. Paid again on every later turn, so a
        rise here multiplies across the whole run.

        READ FROM `_all_requests`, so a leading bound does not change it. The overhead is paid at
        DISPATCH; the first call after a mid-build bound already carries everything the agent had
        accumulated, and reading that one would report an agent's accumulated context as its fixed
        cost — the single number this property exists to isolate."""
        first = self._all_requests
        return first[0].usage.context if first else 0


@dataclass(frozen=True)
class Charges:
    """One turn's bill, split by what was actually charged for.

    The split existed inside `cost_of` from the first line it was written and was added up and
    thrown away. It is the answer to the only question a cost report is asked twice: where does
    the money go. Measured on eight skeptic agents, output was 12-18% of the bill and re-reading
    their own accumulated context was 52-62% — so the lever everyone reaches for first (a cheaper
    model's output rate) moves the smallest term."""
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    input: float = 0.0

    @property
    def total(self) -> float:
        return self.output + self.cache_read + self.cache_write + self.input

    def __add__(self, other: "Charges") -> "Charges":
        return Charges(self.output + other.output, self.cache_read + other.cache_read,
                       self.cache_write + other.cache_write, self.input + other.input)


def charges_of(usage: Usage, model: str, cache_ttl: str) -> Charges | None:
    """What one turn cost, per charge type. `None` when the model has no list price."""
    rates = MODEL_RATES.get(model)
    if rates is None:
        return None
    price_in, price_out = rates
    write = CACHE_WRITE_MULTIPLIER[cache_ttl]
    return Charges(output=usage.output_tokens * price_out / 1e6,
                   cache_read=usage.cache_read_input_tokens * price_in
                   * CACHE_READ_MULTIPLIER / 1e6,
                   cache_write=usage.cache_creation_input_tokens * price_in * write / 1e6,
                   input=usage.input_tokens * price_in / 1e6)


def cost_of(usage: Usage, model: str, cache_ttl: str) -> float | None:
    """The turn's total. One writer for the arithmetic, so the split and the total cannot drift."""
    charges = charges_of(usage, model, cache_ttl)
    return None if charges is None else charges.total


def actor_cost(actor: Actor, cache_ttl: str) -> tuple[float, set[str]]:
    """Cost summed PER TURN, because a run can mix models (a cheaper verify agent is exactly the
    experiment this command exists to measure). Returns the total and the models that had no rate."""
    total = 0.0
    unpriced: set[str] = set()
    for turn in actor.requests:
        c = cost_of(turn.usage, turn.model, cache_ttl)
        if c is None:
            unpriced.add(turn.model or "(unknown)")
        else:
            total += c
    return total, unpriced


def actor_charges(actor: Actor, cache_ttl: str) -> Charges:
    """The same sum as `actor_cost`, kept split. An unpriced model contributes nothing here, the
    way it contributes nothing to the total — it is reported by name instead."""
    out = Charges()
    for turn in actor.requests:
        c = charges_of(turn.usage, turn.model, cache_ttl)
        if c is not None:
            out = out + c
    return out


# --- reading a run ---------------------------------------------------------------------


def subagent_dir(session: Path) -> Path:
    """Sub-agent transcripts live in `<session-dir>/<session-id>/subagents/`, beside the session
    JSONL — NOT inside it. A build's sub-agents are 90% of its spend, so a reader that only opens
    the session file reports the lead's 20% and calls it the build."""
    return session.parent / session.stem / "subagents"


def read_agents(session: Path) -> list[Actor]:
    directory = subagent_dir(session)
    if not directory.is_dir():
        return []
    agents: list[Actor] = []
    for path in sorted(directory.glob("agent-*.jsonl")):
        meta_path = path.with_suffix(".meta.json")
        description = ""
        parent = ""
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(meta, dict):
                    value = meta.get("description")
                    description = value if isinstance(value, str) else ""
                    owner = meta.get("parentAgentId")
                    parent = owner if isinstance(owner, str) else ""
            except ValueError:
                description = ""
        turns = read_turns(path, include_sidechains=True)
        if not turns:
            continue
        agents.append(Actor(name=description or path.stem,
                            role=classify(description), turns=turns,
                            agent_id=path.stem.removeprefix("agent-"), parent_id=parent))
    return agents


def runner_ids(agents: Sequence[Actor]) -> set[str]:
    """The agents that spawned other agents of this build: RUNNERS, whose time is supervision.

    A runner's span is the span of its slowest child plus its own dispatch and collection, so
    timing it as one more worker charges its whole pool's wait as one straggler. Only a parent that
    is itself one of `agents` counts; a child whose parent is missing (a bound dropped it) is
    timed with the lead's own fan-outs."""
    present = {a.agent_id for a in agents if a.agent_id}
    return {a.parent_id for a in agents if a.parent_id and a.parent_id in present}


def bounded_agents(agents: Sequence[Actor], window: tuple[float, float],
                   *, bill_from: float | None = None) -> list[Actor]:
    """The agents this BOUNDED build ran, each timed inside the same window as the lead.

    An agent is this build's when its records OVERLAP the window at all. It then keeps every turn
    and reports its time inside the window — see `Actor.timed_turns` for why the bound cuts the
    clock and not the bill. Only an agent lying ENTIRELY outside is dropped, time and tokens
    together: it belongs to whatever the session did before the build began or after it finished.

    DID IT WORK HERE, never "did it start here". Keying the test on the first stamp deleted a whole
    trace agent — 41 API calls, $4.49 — when `--from-turn` moved by one lead
    turn across 1.49 seconds of clock: the agent had begun 1.49 seconds before the new bound and
    then did the rest of its 4.56-minute span inside it. The report went on to say the lead was
    alone for 6.2 -> 7.4 minutes of a 28.3-minute build, which is time it was demonstrably waiting
    on that agent.

    The test is `work_spans` being non-empty, so it needs no interval arithmetic of its own and
    cannot drift from the clock: an actor is this build's exactly when the build's window holds
    some of its work. One with no timestamps at all is kept — it has tokens to report and no clock
    to place."""
    return [w for a in agents
            if (w := replace(a, window=window, bill_from=bill_from)).start is not None
            or a.launched_at is None]


def read_run(session: Path, *, from_turn: int = 0, to_turn: int | None = None,
             include_sidechains: bool = False) -> tuple[Actor, list[Actor]]:
    """The lead and its sub-agents, bounded to the build.

    A session is not a build: it can archive the previous map first, and it usually keeps
    answering questions after the map lands. `from_turn` / `to_turn` cut those off, so time and
    tokens describe the same stretch. Without them one 68-minute build reads as a 130-minute
    session — the idle exclusion recovers most of that, but only explicit bounds drop the
    post-build conversation, which is real work and real tokens that simply are not the build.

    THE BOUND REACHES THE SUB-AGENTS TOO. Turn indices number the lead's own messages and no
    sub-agent has one, so a bound that only filtered `lead_turns` left every agent free to run its
    span to its last record — and the wall, the fan-out table and the straggler waste were all read
    off those spans. `bounded_agents` closes that."""
    lead = read_lead(session, from_turn=from_turn, to_turn=to_turn,
                     include_sidechains=include_sidechains)
    window = build_window(lead, from_turn=from_turn, to_turn=to_turn)
    agents = read_agents(session)
    if window is None:
        return lead, agents
    return lead, bounded_agents(agents, window,
                                bill_from=window[0] if from_turn > 0 else None)


def read_lead(session: Path, *, from_turn: int = 0, to_turn: int | None = None,
              include_sidechains: bool = False) -> Actor:
    """The lead's own turns, cut to `[from_turn, to_turn]`."""
    upper = to_turn if to_turn is not None else 10 ** 9
    return Actor(name="lead", role="lead",
                 turns=tuple(t for t in read_turns(session, include_sidechains=include_sidechains)
                             if from_turn <= t.index <= upper))


@dataclass(frozen=True)
class Compaction:
    """One time the harness replaced a context with a summary of it."""

    #: The first turn that ran on the summary (the summary itself, when the reader yields it).
    turn: int
    #: `auto` when the window filled, `manual` when someone typed /compact.
    trigger: str
    pre_tokens: int
    post_tokens: int
    timestamp: str


@dataclass(frozen=True)
class ContextFacts:
    """The lead's own context window over the build."""

    lead_first: int = 0
    lead_peak: int = 0
    lead_peak_turn: int = -1
    compactions: tuple[Compaction, ...] = ()
    #: The sub-agents whose own window filled, by their description.
    subagents_compacted: tuple[str, ...] = ()


def read_compactions(path: Path, *,
                     include_sidechains: bool = False) -> list[tuple[int, Compaction]]:
    """Every time the harness replaced this transcript's context with a summary, with the 0-based
    JSONL line of its record (`turn` is left at -1 for the caller to place).

    Read off the `compact_boundary` records the harness writes, never off the summary's wording:
    the record carries the tokens before and after and the trigger. A sidechain record belongs to a
    sub-agent unless the caller is reading a sub-agent's own file, exactly as `read_turns` decides."""
    found: list[tuple[int, Compaction]] = []
    with path.open(encoding="utf-8") as fh:
        for line, raw in enumerate(fh):
            if "compact_boundary" not in raw:
                continue
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("subtype") != "compact_boundary":
                continue
            if record.get("isSidechain") and not include_sidechains:
                continue
            meta = record.get("compactMetadata")
            meta = meta if isinstance(meta, dict) else {}
            found.append((line, Compaction(turn=-1, trigger=str(meta.get("trigger") or ""),
                                           pre_tokens=int(meta.get("preTokens") or 0),
                                           post_tokens=int(meta.get("postTokens") or 0),
                                           timestamp=str(record.get("timestamp") or ""))))
    return found


def compactions_in(path: Path, turns: Sequence[Turn], *, from_turn: int = 0,
                   to_turn: int | None = None,
                   include_sidechains: bool = False) -> tuple[Compaction, ...]:
    """The compactions of one transcript, each placed at the first turn after its record (the
    summary itself, which `read_turns` yields as a turn), and kept only when that turn lies inside
    the bound. `turns` must come from the same file, read with the same sidechain filter. ONE
    placement shared by `cost` and the L3 scorecard, so the two never name different turns."""
    upper = to_turn if to_turn is not None else 10 ** 9
    placed: list[Compaction] = []
    for line, boundary in read_compactions(path, include_sidechains=include_sidechains):
        after = next((t.index for t in turns if t.line > line), None)
        if after is not None and from_turn <= after <= upper:
            placed.append(replace(boundary, turn=after))
    return tuple(placed)


def _agent_description(path: Path) -> str:
    """A sub-agent's own job description from the `.meta.json` beside it, else its file name."""
    meta_path = path.with_suffix(".meta.json")
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            return path.stem
        if isinstance(meta, dict) and isinstance(meta.get("description"), str):
            return meta["description"]
    return path.stem


def context_facts(session: Path, lead: Actor, *, from_turn: int = 0, to_turn: int | None = None,
                  include_sidechains: bool = False) -> ContextFacts:
    """The lead's own context window: where it started, where it peaked, and every summary.

    A compaction replaces everything the lead has read with a summary of it, and the build goes on
    as if it still held the rules and decisions the summary dropped. Nothing else in this report can
    see one, which is why two compacted builds went unreported.

    A compaction counts for THIS build when the turn that ran on the summary lies inside the turn
    bound: a session keeps talking after the commit, and a summary there says nothing about the
    build."""
    turns = read_turns(session, include_sidechains=include_sidechains)
    compactions = compactions_in(session, turns, from_turn=from_turn, to_turn=to_turn,
                                 include_sidechains=include_sidechains)
    calls = lead.requests
    peak = max(calls, key=lambda t: t.usage.context, default=None)
    directory = subagent_dir(session)
    compacted = (tuple(_agent_description(p) for p in sorted(directory.glob("agent-*.jsonl"))
                       if read_compactions(p, include_sidechains=True))
                 if directory.is_dir() else ())
    return ContextFacts(lead_first=calls[0].usage.context if calls else 0,
                        lead_peak=peak.usage.context if peak is not None else 0,
                        lead_peak_turn=peak.index if peak is not None else -1,
                        compactions=compactions, subagents_compacted=compacted)


def build_window(lead: Actor, *, from_turn: int = 0,
                 to_turn: int | None = None) -> tuple[float, float] | None:
    """The stretch of clock a turn bound picks out, or `None` when the run is unbounded.

    PUBLIC so that every command reading one build agrees on where it starts and stops. `cost` and
    `process` are told by `eval/retro/method.md` to take the same `--to-turn`, and a second
    derivation in the other command is how they come to mean different things — which they did:
    the same flag bounded one report and not the other, so a retro compared a bounded wall against
    unbounded agent durations. A caller outside this module builds its Actors with
    `Actor(..., window=build_window(read_lead(...), to_turn=...))` and cannot drift from `cost`."""
    if from_turn <= 0 and to_turn is None:
        return None
    return (lead.start, lead.end) if lead.start is not None and lead.end is not None else None


# --- timeline --------------------------------------------------------------------------


def _union(intervals: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(i for i in intervals if i[1] > i[0]):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


@dataclass(frozen=True)
class Batch:
    """One fan-out: the agents spawned close together, and what waiting for the slowest one cost.

    `waste` is the batch's wall MINUS its mean agent duration — the time the fast agents spent
    finished and idle. It is the single number a slice-balancing change has to move."""

    index: int
    start: float
    end: float
    agents: tuple[Actor, ...]
    #: Who dispatched this fan-out: "lead", or the runner agent's name.
    via: str = "lead"

    @property
    def wall(self) -> float:
        """How long the barrier held, measured on WORK — the basis `mean` is already measured on.

        `waste = wall - mean`, so the two have to be measured the same way, and they were not:
        `mean` subtracts the stretches an agent sat blocked on its coordinator while this read the
        raw first-to-last span. `Actor.duration` has said in writing since the day it was written
        that charging a batch's waste with blocked time "measures the LEAD's latency and calls it
        the agent's" — the arithmetic here did it anyway.

        What that cost, on the DEFAULT unbounded run of one real build: 14.86 phantom minutes in a
        single fan-out and 22.35 minutes of straggler waste for a true 7.49. Bounding the run with
        `--to-turn` happened to hide it, because that build's blocked stretch fell outside the
        window — so the report was only correct when the operator passed a flag. Measuring on work
        makes the unbounded run agree with the bounded one instead: 22.35 -> 7.49, and every
        bounded number unchanged.

        Each agent occupies `duration` seconds of work from where it starts, so the barrier ends
        when the last of them finishes."""
        if not self.agents:
            return self.end - self.start
        return max(((a.start or self.start) - self.start) + a.duration for a in self.agents)

    @property
    def durations(self) -> list[float]:
        return sorted((a.duration for a in self.agents), reverse=True)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.durations) if self.agents else 0.0

    @property
    def waste(self) -> float:
        return max(0.0, self.wall - self.mean)

    @property
    def stagger(self) -> float:
        """The gap between the FIRST and LAST agent of this batch starting.

        The entire ceiling on what launch ORDER can win. `method.md` priced "dispatch the longest
        slice first" at "up to 7.7 minutes" — which was the straggler's RUNTIME, not the cost of
        launching it late. Every agent in a batch goes out in one message and they all run at once,
        so ordering changes who starts a few seconds sooner and nothing else. Measured on the
        2026-09-01 argus build: 12.6 s for 9 agents, 20.7 s for 13, 34.8 s for 19 — against 17.5
        minutes of straggler waste over the same build, which reordering cannot touch at all.

        Printed BESIDE `waste` on purpose. Apart, each number invites the wrong reading; together
        they say plainly that the lever is slice SIZING, not slice order.

        Reads `launched_at`, never `start`: a bounded run clips `start` to the window's opening, so
        every agent already running shares one start and this collapses. See `Actor.launched_at`."""
        starts = [s for s in (a.launched_at for a in self.agents) if s is not None]
        return max(starts) - min(starts) if starts else 0.0

    def cost(self, cache_ttl: str) -> float:
        """What this fan-out billed. The table above it reported only TIME, so a batch could be
        the most expensive in the build and read as unremarkable — `waste` answers "which barrier
        was slow", never "which fan-out was dear"."""
        return sum(actor_charges(a, cache_ttl).total for a in self.agents)

    def thinking_share(self) -> float:
        """Reasoning as a fraction of this batch's output. Beside `waste` it separates two
        different stragglers: a batch slow because one slice was oversized, and a batch slow
        because its agents reasoned their way through it."""
        out = sum(a.totals().output_tokens for a in self.agents)
        think = sum(a.totals().thinking_tokens for a in self.agents)
        return think / out if out else 0.0


def batches(agents: Sequence[Actor], gap: float = 120.0) -> list[Batch]:
    """Cluster agents into fan-outs: a LAUNCH more than `gap` after the previous one begins a new
    batch. The lead spawns one agent per message, so a batch's own launches are minutes apart —
    hence a gap this wide.

    Clustered on `launched_at`, never on the window-clipped `start`. Clipped starts are equal for
    every agent already running when the window opened, so consecutive waves fused: one bounded run
    reported 4 fan-outs where the transcript holds 5. An agent with no working time inside the
    window is left out — it has no row to contribute.

    CLUSTERED PER PARENT, AND A RUNNER IS NO ROW. Siblings are clustered with siblings: the lead's
    own agents form the lead's fan-outs, and a runner's children form fan-outs `via` that runner.
    The runner itself is left out, because it is not a worker: its span is its slowest child's plus
    its own dispatch and collection. Timing it as one more agent of the lead's batch made the
    wave-1 runner of the 2026-10-08 mcpolis build a 53.0-minute straggler, 45.0 minutes of "waste"
    that was its own pool's wait, already charged to the pool's fan-outs."""
    runners = runner_ids(agents)
    names = {a.agent_id: a.name for a in agents if a.agent_id}
    groups: dict[str, list[Actor]] = {}
    for agent in agents:
        if agent.agent_id in runners or agent.launched_at is None or agent.start is None:
            continue
        parent = agent.parent_id if agent.parent_id in runners else ""
        groups.setdefault(parent, []).append(agent)
    clusters: list[tuple[str, list[Actor]]] = []
    for parent, members in groups.items():
        current: list[Actor] = []
        for agent in sorted(members, key=lambda a: a.launched_at or 0.0):
            if current and (agent.launched_at or 0.0) - (current[-1].launched_at or 0.0) > gap:
                clusters.append((parent, current))
                current = []
            current.append(agent)
        if current:
            clusters.append((parent, current))
    clusters.sort(key=lambda c: min(a.launched_at or 0.0 for a in c[1]))
    return [_batch(i, members, names.get(parent, parent) if parent else "lead")
            for i, (parent, members) in enumerate(clusters)]


def _batch(index: int, agents: list[Actor], via: str = "lead") -> Batch:
    return Batch(index=index, start=min(a.start or 0.0 for a in agents),
                 end=max(a.end or 0.0 for a in agents), agents=tuple(agents), via=via)


def reply_latencies(actor: Actor) -> list[tuple[str, float]]:
    """(model, seconds) from each tool result to the reply that answers it: the MODEL's latency.

    Seconds per row moves with this as much as with the method: the 2026-10-08 mcpolis build read
    3.00 -> 7.09 s per row against the build before it, and its median reply took 6.7 s against
    2.5 s. A reader comparing two builds' per-row time has to see this number beside it, or a
    slower model reads as a worse method. Only a reply to a tool result counts: a reply to a brief
    or a follow-up includes the time the coordinator took to write it."""
    out: list[tuple[str, float]] = []
    turns = actor.timed_turns
    for previous, turn in zip(turns, turns[1:]):
        if previous.role != "user" or not previous.tool_results or turn.role != "assistant":
            continue
        a, b = _seconds(previous.timestamp), _seconds(turn.timestamp)
        if a is not None and b is not None and b >= a:
            out.append((turn.model or "(unknown)", b - a))
    return out


def median_reply_seconds(actors: Sequence[Actor]) -> dict[str, float]:
    """The median reply latency per model, over every actor of the build."""
    by_model: dict[str, list[float]] = {}
    for actor in actors:
        for model, seconds in reply_latencies(actor):
            by_model.setdefault(model, []).append(seconds)
    return {m: statistics.median(v) for m, v in sorted(by_model.items())}


def _subtract(span: tuple[float, float],
              busy: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """`span` minus every interval in `busy` (which must be sorted and merged)."""
    start, end = span
    free: list[tuple[float, float]] = []
    cursor = start
    for begin, finish in busy:
        if finish <= cursor:
            continue
        if begin >= end:
            break
        if begin > cursor:
            free.append((cursor, min(begin, end)))
        cursor = max(cursor, finish)
        if cursor >= end:
            break
    if cursor < end:
        free.append((cursor, end))
    return free


def idle_gaps(lead: Actor, agents: Sequence[Actor], threshold: float) -> list[tuple[float, float]]:
    """Stretches where the lead was silent for longer than `threshold` AND no agent was running.

    That conjunction is the whole definition. A long silence with agents running is the lead
    waiting on its own fan-out — real build time. A long silence with nothing running is a human
    who walked away, and counting it made one 68-minute build read as 130 minutes.

    The agent windows are SUBTRACTED from each silence rather than used to veto it, so a 40-minute
    silence in which one agent ran for two minutes yields 38 idle minutes, not zero. Vetoing was
    the first cut, and it also managed to call a silence idle when an agent covered it exactly."""
    busy = _union((a.start, a.end) for a in agents if a.start is not None and a.end is not None)
    stamps = lead.stamps
    gaps: list[tuple[float, float]] = []
    for previous, following in zip(stamps, stamps[1:]):
        if following - previous <= threshold:
            continue
        for free in _subtract((previous, following), busy):
            if free[1] - free[0] > threshold:
                gaps.append(free)
    return gaps


# --- the map it produced ---------------------------------------------------------------


@dataclass(frozen=True)
class MapFacts:
    """What the build produced, for the per-unit divisor, and how well it held up.

    Read straight from the JSON rather than through `load_model`: a map that fails validation still
    cost what it cost, and a measurement command that refuses to measure a broken build is useless
    exactly when the question is 'what did that failure cost us'."""

    rows: int
    sections: int
    claims_total: int = 0
    #: How many of `claims_total` a skeptic actually read. Falls back to `claims_total` for a map
    #: written before the field existed.
    claims_challenged: int = 0
    claims_refuted: int = 0
    claims_unverifiable: int = 0


def read_map(path: Path) -> MapFacts | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    lists = {k: v for k, v in data.items() if isinstance(v, list)}
    grounding = data.get("grounding")
    grounding = grounding if isinstance(grounding, dict) else {}

    def n(key: str) -> int:
        value = grounding.get(key)
        return value if isinstance(value, int) else 0

    # `claims_total` is the SIZE OF THE WORKLIST; `claims_challenged` is how many a skeptic actually
    # read. On a complete pass they are equal, which is why reading the wrong one went unnoticed —
    # on a PARTIAL pass they are not, and the refutation rate the method tells you to read was
    # divided by the wrong denominator: one real build printed 6/1385 = 0.4% for a rate that is
    # 6/743 = 0.8%.
    return MapFacts(rows=sum(len(v) for v in lists.values()), sections=len(lists),
                    claims_total=n("claims_total"),
                    claims_challenged=n("claims_challenged") or n("claims_total"),
                    claims_refuted=n("claims_refuted"),
                    claims_unverifiable=n("claims_unverifiable"))


# --- the report ------------------------------------------------------------------------


@dataclass
class Report:
    session: str
    wall_seconds: float
    idle_seconds: float
    agent_busy_seconds: float
    lead_only_seconds: float
    agents: int
    requests: int
    usage: dict[str, int]
    cost: float
    unpriced_models: list[str]
    models: dict[str, int]
    by_role: dict[str, dict[str, float]]
    batches: list[dict[str, float | str]]
    base_context_median: int
    context_per_turn: dict[str, int]
    tool_seconds: float
    spawn_prompt_tokens: int
    #: The bill by charge type — what the money bought, not who spent it.
    charges: dict[str, float] = field(default_factory=dict)
    #: The lead's own window: first and peak context, every compaction, compacted sub-agents.
    context: ContextFacts = field(default_factory=ContextFacts)
    map: dict[str, int] = field(default_factory=dict)
    per_row: dict[str, float] = field(default_factory=dict)
    #: Sub-agents that dispatched agents of their own, and how many agents they dispatched.
    runners: int = 0
    nested: int = 0
    #: Median seconds from a tool result to the reply, per model (`reply_latencies`).
    reply_seconds: dict[str, float] = field(default_factory=dict)


def _tool_seconds(agents: Sequence[Actor]) -> float:
    """Wall time inside sub-agents spent waiting on a tool, as opposed to generating.

    Pairs each call to its result by id and unions the intervals per agent, so parallel calls in
    one message are not counted twice. On these builds it lands at 4-7%: the fan-out is bound by
    token generation, not by grep.

    The call side reads `ToolCall.timestamp` — the block's OWN execution time — never the Turn's.
    A Turn carries the first record's stamp, so timing ten calls of one response from it measures
    the generation between them and reports ~34%."""
    total = 0.0
    for agent in agents:
        started: dict[str, float] = {}
        spans: list[tuple[float, float]] = []
        for turn in agent.timed_turns:
            for call in turn.tool_calls:
                stamp = _seconds(call.timestamp) or _seconds(turn.timestamp)
                if stamp is not None:
                    started[call.id] = stamp
            done = _seconds(turn.timestamp)
            if done is None:
                continue
            for result in turn.tool_results:
                begin = started.pop(result.tool_use_id, None)
                if begin is not None and done > begin:
                    spans.append((begin, done))
        total += sum(e - s for s, e in _union(spans))
    return total


def _spawn_tokens(lead: Actor) -> int:
    """Tokens the lead generated writing agent briefs. Serial, on the critical path, and the thing
    a slice spec on disk replaces."""
    total = 0
    for turn in lead.turns:
        for call in turn.agent_calls:
            total += len(call.text()) // 4
    return total


def build_report(session: Path, *, map_path: Path | None = None, from_turn: int = 0,
                 to_turn: int | None = None, idle_threshold: float = 180.0,
                 cache_ttl: str = "5m", include_sidechains: bool = False) -> Report:
    lead, agents = read_run(session, from_turn=from_turn, to_turn=to_turn,
                            include_sidechains=include_sidechains)
    everyone: list[Actor] = [lead, *agents]
    stamps = [s for actor in everyone for s in actor.stamps]
    if not stamps:
        # A file whose every record is `isSidechain` is a SUB-AGENT's own transcript, and the
        # default filter drops all of it. Refusing with a bare "no turns" sent one reader off to
        # hand-roll the arithmetic, and the hand roll summed the per-content-block records — which
        # repeat one response's cache figures — and overstated the bill by 1.7x. So the refusal
        # names the flag rather than leaving it to be found.
        # Only when the default filter dropped EVERYTHING and the sidechain filter would not.
        # Testing "would sidechains yield turns" alone is not enough: a plain session whose turns
        # simply carry no timestamp also passes that, and would be told to use a flag that cannot
        # help it — and, on a real build, would double-count the sub-agents.
        hint = ""
        if (not include_sidechains and not read_turns(session)
                and read_turns(session, include_sidechains=True)):
            hint = ("\n       Every record in it is a sidechain, so this is one SUB-AGENT's own "
                    "transcript.\n       Re-run with --include-sidechains to profile it.")
        raise ValueError(f"no timestamped turns in {session}{hint}")
    wall = max(stamps) - min(stamps)
    idle = sum(b - a for a, b in idle_gaps(lead, agents, idle_threshold))
    # The union of what the agents were WORKING on, not of their first-to-last spans. A span
    # swallows the stretches an agent sat blocked on the lead, and this figure is printed as a
    # share of active time right beside "lead alone" — so blocked time read as agent work AND was
    # subtracted from the lead's own. On the default unbounded run of one real build that put
    # `agents busy` at 44.88 minutes against a true 30.02, all of the difference one sleeping agent.
    busy = sum(e - s for s, e in _union(span for a in agents for span in a.work_spans))

    usage = Usage()
    cost = 0.0
    charges = Charges()
    unpriced: set[str] = set()
    models: Counter[str] = Counter()
    by_role: dict[str, dict[str, float]] = {}
    for actor in everyone:
        totals = actor.totals()
        actor_total, actor_unpriced = actor_cost(actor, cache_ttl)
        unpriced |= actor_unpriced
        cost += actor_total
        usage = Usage(usage.input_tokens + totals.input_tokens,
                      usage.output_tokens + totals.output_tokens,
                      usage.cache_read_input_tokens + totals.cache_read_input_tokens,
                      usage.cache_creation_input_tokens + totals.cache_creation_input_tokens,
                      usage.thinking_tokens + totals.thinking_tokens)
        for turn in actor.requests:
            models[turn.model or "(unknown)"] += 1
        charges = charges + actor_charges(actor, cache_ttl)
        bucket = by_role.setdefault(actor.role, {"agents": 0.0, "requests": 0.0, "output": 0.0,
                                                 "thinking": 0.0, "cache_read": 0.0,
                                                 "cache_write": 0.0, "cost": 0.0, "seconds": 0.0})
        bucket["agents"] += 1
        bucket["requests"] += len(actor.requests)
        bucket["output"] += totals.output_tokens
        bucket["thinking"] += totals.thinking_tokens
        bucket["cache_read"] += totals.cache_read_input_tokens
        bucket["cache_write"] += totals.cache_creation_input_tokens
        bucket["cost"] += actor_total
        bucket["seconds"] += actor.duration

    bases = sorted(a.base_context for a in agents if a.base_context)
    requests = sum(len(a.requests) for a in everyone)
    runners = runner_ids(agents)
    report = Report(
        session=session.stem,
        wall_seconds=wall,
        idle_seconds=idle,
        agent_busy_seconds=busy,
        lead_only_seconds=max(0.0, wall - idle - busy),
        agents=len(agents),
        requests=requests,
        usage=asdict(usage),
        cost=cost,
        charges={"output": charges.output, "cache_read": charges.cache_read,
                 "cache_write": charges.cache_write, "input": charges.input},
        unpriced_models=sorted(unpriced),
        models=dict(models),
        by_role=by_role,
        batches=[{"index": float(b.index), "start": b.start - min(stamps), "wall": b.wall,
                  "agents": float(len(b.agents)), "slowest": b.durations[0] if b.agents else 0.0,
                  "median": statistics.median(b.durations) if b.agents else 0.0,
                  "mean": b.mean, "waste": b.waste, "stagger": b.stagger,
                  "cost": b.cost(cache_ttl),
                  "thinking_share": b.thinking_share(), "via": b.via}
                 for b in batches(agents)],
        base_context_median=int(statistics.median(bases)) if bases else 0,
        context_per_turn={
            "lead": (lead.totals().cache_read_input_tokens // len(lead.requests)
                     if lead.requests else 0),
            "subagents": (sum(a.totals().cache_read_input_tokens for a in agents)
                          // max(sum(len(a.requests) for a in agents), 1)),
        },
        tool_seconds=_tool_seconds(agents),
        spawn_prompt_tokens=_spawn_tokens(lead),
        context=context_facts(session, lead, from_turn=from_turn, to_turn=to_turn,
                              include_sidechains=include_sidechains),
        runners=len(runners),
        nested=sum(1 for a in agents if a.parent_id in runners),
        reply_seconds=median_reply_seconds(everyone),
    )
    if map_path is not None:
        facts = read_map(map_path)
        if facts is not None:
            report.map = asdict(facts)
            active = wall - idle
            report.per_row = {
                "cost": cost / facts.rows if facts.rows else 0.0,
                "seconds": active / facts.rows if facts.rows else 0.0,
            }
    return report


# --- rendering -------------------------------------------------------------------------


def _m(seconds: float) -> str:
    return f"{seconds / 60:.1f}m"


def _num(row: dict[str, float | str], key: str) -> float:
    value = row.get(key, 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _reply_text(report: Report) -> str:
    """'6.7s claude-opus-5-5', one per model, or '' when no reply could be timed."""
    return ", ".join(f"{s:.1f}s {m}" for m, s in report.reply_seconds.items())


def _context_lines(report: Report) -> list[str]:
    """The CONTEXT block, printed right under the header because it is the one number in this report
    that can mean the build forgot its own instructions. Each compaction gets its own short line, so
    a `head` or a `cut` keeps it."""
    c = report.context
    # A range can hold a compaction and no lead API call (`--from-turn 746 --to-turn 747`: the
    # summary turn alone). Hiding the block then hid the compaction while `--json` carried it.
    if not (c.lead_peak or c.compactions or c.subagents_compacted):
        return []
    size = (f"  first turn {c.lead_first:,} tokens · peak {c.lead_peak:,} at turn {c.lead_peak_turn}"
            if c.lead_peak else "  no lead API call in this turn range, so no context size to show")
    out = ["", "CONTEXT (the lead's own window)", size]
    if c.compactions:
        out.append(f"  !! COMPACTED {len(c.compactions)} time(s) during the build: the lead went on"
                   f" from a summary, and a retro reports this as a HIGH finding")
        out.extend(f"     turn {e.turn} ({e.trigger}): {e.pre_tokens:,} -> {e.post_tokens:,} tokens"
                   for e in c.compactions)
    elif c.lead_peak >= CONTEXT_NEAR_LIMIT:
        out.append("  !  peak near the point where the harness compacts (~968,000 tokens on the"
                   " measured builds); the next larger build will not fit")
    if c.subagents_compacted:
        out.append(f"  sub-agents compacted: {len(c.subagents_compacted)} — "
                   + ", ".join(c.subagents_compacted))
    return out


def format_report(report: Report) -> str:
    lines: list[str] = []
    active = report.wall_seconds - report.idle_seconds
    lines.append(f"BUILD {report.session}")
    lines.append(f"  wall {_m(report.wall_seconds)}   active {_m(active)}"
                 f"   (idle excluded: {_m(report.idle_seconds)})")
    lines.append(f"  agents busy {_m(report.agent_busy_seconds)}"
                 f" ({100 * report.agent_busy_seconds / max(active, 1):.0f}% of active)"
                 f"   lead alone {_m(report.lead_only_seconds)}")
    nesting = (f" ({report.runners} runner(s) dispatched {report.nested} of them)"
               if report.runners else "")
    lines.append(f"  {report.agents} sub-agent(s){nesting}, {report.requests} API call(s)")

    lines.extend(_context_lines(report))

    lines.append("")
    lines.append("FAN-OUT")
    lines.append(f"  {'#':>2} {'start':>7} {'wall':>7} {'n':>3} {'slowest':>8} {'median':>7}"
                 f" {'mean':>7} {'waste':>7} {'stagger':>8} {'$':>7} {'think':>6}  via")
    for b in report.batches:
        share = _num(b, "thinking_share")
        lines.append(f"  {int(_num(b, 'index')):>2} {_m(_num(b, 'start')):>7}"
                     f" {_m(_num(b, 'wall')):>7} {int(_num(b, 'agents')):>3}"
                     f" {_m(_num(b, 'slowest')):>8} {_m(_num(b, 'median')):>7}"
                     f" {_m(_num(b, 'mean')):>7} {_m(_num(b, 'waste')):>7}"
                     f" {_num(b, 'stagger'):>7.1f}s {_num(b, 'cost'):>7.2f}"
                     f" {(f'{100 * share:.0f}%' if share else '-'):>6}  {b.get('via', 'lead')}")
    waste = sum(_num(b, "waste") for b in report.batches)
    stagger = sum(_num(b, "stagger") for b in report.batches)
    # THE TWO NUMBERS TOGETHER, always. `waste` alone reads as "reorder the dispatch", and
    # `method.md` priced that at 7.7 minutes for years on exactly that reading. `stagger` is the
    # whole ceiling on what reordering can win — every agent in a batch launches in one message —
    # and it is measured in SECONDS. Apart, each invites the wrong lever; together they say the
    # lever is slice SIZING.
    lines.append(f"  straggler waste {_m(waste)}"
                 f" ({100 * waste / max(active, 1):.0f}% of active time)"
                 f"   ·   dispatch stagger {stagger:.1f}s total"
                 f" — the whole ceiling on what LAUNCH ORDER can win; the waste above is a slice"
                 f" SIZING problem")

    lines.append("")
    lines.append("TOKENS")
    lines.append(f"  {'role':<10} {'n':>3} {'calls':>6} {'written':>10} {'thinking':>10}"
                 f" {'cache read':>13} {'cache write':>12} {'$':>8}")
    for role in ROLE_ORDER:
        b = report.by_role.get(role)
        if not b:
            continue
        think = int(b.get("thinking", 0))
        lines.append(f"  {role:<10} {int(b['agents']):>3} {int(b['requests']):>6}"
                     f" {int(b['output']) - think:>10,} {think:>10,}"
                     f" {int(b['cache_read']):>13,}"
                     f" {int(b['cache_write']):>12,} {b['cost']:>8.2f}")
    u = report.usage
    think_total = u.get("thinking_tokens", 0)
    lines.append(f"  {'TOTAL':<10} {'':>3} {report.requests:>6}"
                 f" {u['output_tokens'] - think_total:>10,} {think_total:>10,}"
                 f" {u['cache_read_input_tokens']:>13,}"
                 f" {u['cache_creation_input_tokens']:>12,} {report.cost:>8.2f}")
    # `thinking` is part of `written`'s charge, not beside it: both bill at the output rate. The
    # columns separate them because a model that reasons 3.8x longer for the SAME written answer
    # is the whole finding, and one `output` column hides it.
    if think_total:
        lines.append(f"  thinking is a SHARE of output, billed at the output rate —"
                     f" {100 * think_total / max(u['output_tokens'], 1):.0f}% of it here")
    if report.unpriced_models:
        lines.append(f"  ! no list price for {', '.join(report.unpriced_models)} —"
                     f" their tokens are counted, their cost is NOT in the total")
    if len(report.models) > 1:
        lines.append("  models: " + ", ".join(f"{m} x{n}" for m, n in
                                              sorted(report.models.items(), key=lambda kv: (-kv[1], kv[0]))))

    lines.append("")
    spend = report.charges
    if spend and report.cost > 0:
        lines.append("SPEND")
        rows = (("re-reading its own context", spend.get("cache_read", 0.0)),
                ("cache writes", spend.get("cache_write", 0.0)),
                ("output", spend.get("output", 0.0)),
                ("fresh input", spend.get("input", 0.0)))
        for label, amount in rows:
            if amount <= 0:
                continue
            lines.append(f"  {label:<30} {amount:>8.2f} {100 * amount / report.cost:>4.0f}%")
        lines.append("  what the money bought, not who spent it. A cheaper model moves the OUTPUT"
                     " row only.")
        lines.append("")

    lines.append("STRUCTURE")
    lines.append(f"  fixed base context per agent turn   {report.base_context_median:>12,}")
    lines.append(f"  avg cache read per turn — lead      {report.context_per_turn['lead']:>12,}")
    lines.append(f"  avg cache read per turn — agents    {report.context_per_turn['subagents']:>12,}")
    lines.append(f"  tool execution inside agents        {_m(report.tool_seconds):>12}"
                 f"  ({100 * report.tool_seconds / max(sum(b['seconds'] for r, b in report.by_role.items() if r != 'lead'), 1):.0f}% of agent time)")
    lines.append(f"  lead tokens spent writing briefs    {report.spawn_prompt_tokens:>12,}")
    if report.reply_seconds:
        lines.append(f"  model median reply, tool result to next reply: {_reply_text(report)}")

    if report.map:
        lines.append("")
        lines.append("PER UNIT OF MAP")
        m = report.map
        lines.append(f"  rows produced                       {m['rows']:>12,}"
                     f"  (in {m['sections']} sections)")
        lines.append(f"  cost per row                        {report.per_row['cost']:>12.4f}")
        reply = _reply_text(report)
        lines.append(f"  seconds per row                     {report.per_row['seconds']:>12.2f}"
                     + (f"  (model median reply {reply})" if reply else ""))
        challenged = m.get("claims_challenged") or m["claims_total"]
        if challenged:
            rate = 100 * m["claims_refuted"] / challenged
            partial = ("" if challenged == m["claims_total"]
                       else f" of {m['claims_total']:,} on the worklist")
            lines.append(f"  claims challenged / refuted         "
                         f"{challenged:>7,} / {m['claims_refuted']:<4}"
                         f"  ({rate:.1f}% refuted, {m['claims_unverifiable']} unverifiable"
                         f"{partial})")
    return "\n".join(lines)


# --- CLI -------------------------------------------------------------------------------

USAGE = """usage: coyomap-eval cost <transcript.jsonl> [--map project-map.json] [--json]
                             [--from-turn N] [--to-turn N] [--idle-gap SECONDS]
                             [--cache-ttl 5m|1h] [--include-sidechains]

What a build SPENT: wall time, tokens, and both per row of map produced. Reads the session
transcript AND the sub-agent transcripts beside it (`<session>/subagents/`), which are ~80% of
the spend — a reader that opens only the session file measures the lead and misses the build.

  --map PATH     the map the build produced; adds rows, cost-per-row, seconds-per-row, and the
                 grounding counts. WITHOUT it the report cannot be compared against another
                 build: absolute minutes and dollars track how big the map got, not how well
                 the tooling did.
  --from-turn N  ignore the lead's turns before N, for a session that did something else first
                 (an archive step, an unrelated question) before the build began.
  --to-turn N    and after N — a session usually keeps answering questions once the map has
                 landed. Turn numbers come from `coyomap-eval transcript`.
                 Either bound also stops the SUB-AGENTS' clock at the same moment the lead's
                 stops, so an agent woken by a background command after the build committed no
                 longer stretches the wall or the straggler waste. Their TOKENS are untouched:
                 the build paid for every call it spawned, whenever the call landed.
  --idle-gap S   a lead silence longer than S seconds with NO agent running is operator wait and
                 is excluded from `active` (default 180).
  --cache-ttl    cache-write price multiplier: 1.25x at 5m (default), 2x at 1h.
  --include-sidechains
                 read a file whose records are all `isSidechain` — ONE sub-agent's own
                 transcript, which the default filter drops entirely. Never pass it for a
                 build session: there the sidechains are the sub-agents, and they are already
                 read from <session>/subagents/, so it would count them twice.
  --json         the whole report as JSON, for tracking builds over time.
  --spend-out P  also write what the build cost PER ROW to P (needs --map): the spend.json that
                 `coyomap-eval run --spend` compares with the baseline's, as a rise-only band.

A sub-agent that dispatched agents of its own (a fact-check wave runner) gets no fan-out row: its
agents form rows of their own, named in the `via` column. `seconds per row` carries the model's
median reply time beside it: a slower model raises the one with the other.

Not a gate: it emits no verdict. Read it beside `coyomap-eval compare` — a change that halves
the bill and doubles the refutation rate is not an improvement."""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    def opt(flag: str) -> str | None:
        if flag not in args:
            return None
        i = args.index(flag) + 1
        return args[i] if i < len(args) else None

    consumed = {opt(f) for f in ("--map", "--from-turn", "--to-turn", "--idle-gap", "--cache-ttl",
                                 "--spend-out")}
    positional = [a for a in args if not a.startswith("--") and a not in consumed]
    if not positional:
        print("ERROR: give a transcript path\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    session = Path(positional[0])
    if not session.is_file():
        print(f"ERROR: no transcript at {session}", file=sys.stderr)
        return 2

    map_arg = opt("--map")
    map_path = Path(map_arg) if map_arg else None
    if map_path is not None and not map_path.is_file():
        print(f"ERROR: no map at {map_path}", file=sys.stderr)
        return 2
    cache_ttl = opt("--cache-ttl") or "5m"
    if cache_ttl not in CACHE_WRITE_MULTIPLIER:
        print("ERROR: --cache-ttl takes 5m or 1h", file=sys.stderr)
        return 2
    try:
        from_turn = int(opt("--from-turn") or 0)
        to_raw = opt("--to-turn")
        to_turn = int(to_raw) if to_raw is not None else None
        idle_gap = float(opt("--idle-gap") or 180.0)
    except ValueError:
        print("ERROR: --from-turn/--to-turn take an integer and --idle-gap a number",
              file=sys.stderr)
        return 2

    try:
        report = build_report(session, map_path=map_path, from_turn=from_turn, to_turn=to_turn,
                              idle_threshold=idle_gap, cache_ttl=cache_ttl,
                              include_sidechains="--include-sidechains" in args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if (spend_out := opt("--spend-out")) is not None:
        spend = Spend.from_cost(int(report.map.get("rows", 0)), report.per_row, report.unpriced_models)
        if spend is None:
            print("ERROR: --spend-out needs --map: what a build cost per row is divided by its rows",
                  file=sys.stderr)
            return 2
        Path(spend_out).write_text(spend.to_json() + "\n", encoding="utf-8")
    if "--json" in args:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
        return 0
    print(format_report(report))
    if not subagent_dir(session).is_dir():
        print("\nNOTE: no sub-agent transcripts beside this session — the numbers above are the"
              "\n      LEAD ONLY. On a fan-out build that is about a fifth of the real spend.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
