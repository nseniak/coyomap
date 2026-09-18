#!/usr/bin/env python3
"""Typed, streaming reader for a Claude Code build transcript (`~/.claude/projects/<slug>/*.jsonl`).

The L3 process scorecard asks whether the BUILD AGENT behaved as `method.md` says. Nothing but the
transcript can answer that, so this module turns the raw JSONL into a small typed sequence and the
assertions become ordinary counting.

## The one thing that is easy to get wrong

**A JSONL record is NOT a turn.** This harness writes each content block of one assistant message as
its own record, and stamps each with the time that block *executed* — so a single API response that
emitted ten `tool_use` blocks appears as ten records, spread over minutes, with the tool results
interleaved between them. Counting records as turns therefore reports "one tool call per turn" for a
message that made ten calls at once, which is exactly the measurement the fan-out rule turns on.

The reliable turn key is the API message identity. Every record of one response repeats:

    message.id            the API's own message id
    requestId             the harness's request id
    message.usage         identical token counts (one response, one usage block)
    message.stop_reason

`message.id` is the primary key here; `_usage_signature` is carried so a caller can assert the
grouping held (across the eight real build transcripts this reader was validated on, zero message
ids ever carried two different usage blocks). The corroborating evidence that settles it: a run of
ten `tool_use` records sharing one message id has exactly ONE `thinking` block among them. A model
does not emit ten tool-calling responses of which nine contain no reasoning.

## What a Turn carries

`Turn(index, role, tool_calls)` is the shape the L3 design specifies. Two additions, both earned:

  * `tool_results` on user turns — assertion 9 has to read what `coyomap validate` PRINTED, which
    lives in the tool result, not in the call.
  * `line` / `message_id` / `is_sidechain` — so evidence can point a reader at the exact record.
    `isSidechain: true` marks a sub-agent's own turns; the lead's fan-out behaviour is what L3
    measures, so callers filter those out by default (`read_turns(..., include_sidechains=False)`).
  * `usage` / `model` — what the response was billed for, and by which model. The grouping is
    what makes these safe to add: the same `usage` block is repeated on every record of one
    message, so a per-record sum inflates output tokens ~8x. `coyomap-eval cost` reads them.

Streaming: the corpus files are 2–3 MB each and a scorecard run reads eight of them. `iter_turns`
never holds more than one message group in memory.

Stdlib only (`json`), frozen dataclasses — `coyomap_eval` carries no runtime dependencies.
"""
from __future__ import annotations

import re
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

#: Roles a Turn can carry. Records of any other `type` (queue-operation, system, attachment,
#: file-history-*, custom-title …) are harness bookkeeping and never become turns.
ASSISTANT = "assistant"
USER = "user"


@dataclass(frozen=True)
class ToolCall:
    """One `tool_use` block: the tool's name, the arguments the agent passed it, and the id its
    `tool_result` will quote — which is how a caller reads what a command PRINTED (assertion 9
    needs `coyomap validate`'s output, not just the fact that it ran). Pairing by id rather than by
    order matters here: results arrive out of order when sub-agents run asynchronously."""

    name: str
    input: Mapping[str, object] = field(default_factory=dict)
    id: str = ""
    #: When this block EXECUTED — not when its message was answered. The harness stamps each
    #: content block separately, and a Turn carries the first one's time, so ten calls in one
    #: response all share the Turn's timestamp while executing minutes apart. Anything timing a
    #: call against its result must read this, or it measures the generation in between: the first
    #: cut of the cost report put tool execution at 34% of agent time when the true figure is 4%.
    timestamp: str = ""

    @property
    def command(self) -> str:
        """The shell command, for a Bash call — `""` for every other tool. Most L3 assertions ask
        'did the agent run X', and this is where X lives."""
        value = self.input.get("command")
        return value if isinstance(value, str) else ""

    def text(self) -> str:
        """The whole input serialised, for assertions that must look anywhere in the arguments (a
        `grounding` object written through `Write`, a heredoc inside a Bash command)."""
        try:
            return json.dumps(self.input, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(self.input)


@dataclass(frozen=True)
class ToolResult:
    """One `tool_result` block, flattened to text. The harness stores result content either as a
    plain string or as a list of `{type: text, text: …}` blocks; both arrive here as one string."""

    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Usage:
    """The token counts one API response was billed for.

    Carried per TURN, never per record, and that is the whole point: the harness writes each
    content block of one response as its own record and repeats the identical `usage` on every one
    of them, so summing over records multiplies a response's tokens by its block count. On the
    build transcripts this reader was written for that inflates output tokens by roughly 8x.

    `context` is what the request actually re-read: cached tokens plus any written fresh. Growth
    in this number turn over turn IS the cost of a long agent — every turn pays for the whole
    conversation so far."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    #: The reasoning share of `output_tokens`, NOT a separate charge — it is billed at the output
    #: rate and is already inside that number. Kept because the two halves answer different
    #: questions and the totals hide it: on one measured pair, two models wrote the SAME verdicts
    #: (70,435 vs 69,883 written tokens) while one reasoned 3.8x longer (61,849 vs 235,099). Read
    #: as one output figure, the cheaper model simply looks more expensive per agent and the
    #: reason is invisible. Zero when the harness does not report the detail.
    thinking_tokens: int = 0

    @property
    def context(self) -> int:
        """Total prompt the model read this turn — cached + written + fresh."""
        return (self.input_tokens + self.cache_read_input_tokens
                + self.cache_creation_input_tokens)

    @property
    def written_tokens(self) -> int:
        """Output that is not reasoning: the verdicts, the prose, the tool commands.

        Clamped at zero rather than trusted: `thinking_tokens` comes from a different field than
        `output_tokens`, and a harness that reported one without the other would otherwise make
        this negative and the SPEND block wrong in a direction nobody checks."""
        return max(0, self.output_tokens - self.thinking_tokens)

    def __bool__(self) -> bool:
        return bool(self.input_tokens or self.output_tokens
                    or self.cache_read_input_tokens or self.cache_creation_input_tokens)


def _usage_of(message: Mapping[str, object]) -> Usage:
    raw = message.get("usage")
    if not isinstance(raw, dict):
        return Usage()

    def n(key: str) -> int:
        value = raw.get(key)
        return value if isinstance(value, int) else 0

    detail = raw.get("output_tokens_details")
    thinking = 0
    if isinstance(detail, dict):
        value = detail.get("thinking_tokens")
        thinking = value if isinstance(value, int) else 0
    return Usage(input_tokens=n("input_tokens"), output_tokens=n("output_tokens"),
                 cache_read_input_tokens=n("cache_read_input_tokens"),
                 cache_creation_input_tokens=n("cache_creation_input_tokens"),
                 thinking_tokens=thinking)


def _merge_usage(a: Usage, b: Usage) -> Usage:
    """Field-wise max across the records of one message.

    Max rather than sum: the records repeat one response's counts, so summing double-counts. Max
    rather than first-wins: a streamed response can be written before its final `output_tokens`
    is known, and the later record carries the complete figure."""
    return Usage(input_tokens=max(a.input_tokens, b.input_tokens),
                 output_tokens=max(a.output_tokens, b.output_tokens),
                 cache_read_input_tokens=max(a.cache_read_input_tokens,
                                             b.cache_read_input_tokens),
                 cache_creation_input_tokens=max(a.cache_creation_input_tokens,
                                                 b.cache_creation_input_tokens),
                 thinking_tokens=max(a.thinking_tokens, b.thinking_tokens))


@dataclass(frozen=True)
class Turn:
    """One API message — an assistant response, or the user/tool-result message answering it.

    `index` is the 0-based ordinal among the turns this reader yielded, which is what the L3
    evidence records point at. `line` is the 0-based JSONL line of the turn's FIRST record, for
    when a reader wants to go and look at the file."""

    index: int
    role: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    message_id: str = ""
    line: int = -1
    is_sidechain: bool = False
    timestamp: str = ""
    #: Tokens billed for this turn, and the model that billed them. Empty on user turns — only an
    #: assistant response has a usage block. `coyomap-eval cost` sums these; nothing else may sum
    #: usage off raw records (see `Usage`).
    usage: Usage = Usage()
    model: str = ""
    #: (visible characters, signature bytes) summed over this turn's `thinking` blocks. A block can
    #: carry a multi-KB signature and an EMPTY body — the reasoning is redacted at write time. The
    #: reader used to drop those blocks entirely, so a retrospective could not tell "the agent did
    #: not reason here" from "the reasoning is withheld", and three of its findings had to be
    #: downgraded from certain to likely for want of that distinction.
    thinking_chars: int = 0
    thinking_signature_bytes: int = 0
    #: The assistant's VISIBLE prose for this turn, `text` blocks joined. Empty on user turns.
    #:
    #: Earned by a retrospective that could not audit a whole class of method rule. `method.md` and
    #: `dispatch.md` prescribe several steps that produce no tool call at all — show `scope`'s
    #: output verbatim as the first message, announce the build mode, warn before overwriting a
    #: baseline, and "the wait at a barrier is a TEXT turn". None of it was visible here, so the
    #: reviewer went and hand-parsed the raw JSONL — the exact fallback `--full-output` was added
    #: to prevent for sub-agent returns.
    text: str = ""

    def calls_named(self, *names: str) -> tuple[ToolCall, ...]:
        wanted = frozenset(names)
        return tuple(c for c in self.tool_calls if c.name in wanted)

    @property
    def agent_calls(self) -> tuple[ToolCall, ...]:
        """Sub-agent launches. The tool is `Agent` in this harness; `Task` is the older spelling and
        is accepted so an archived transcript still measures."""
        return self.calls_named("Agent", "Task")


def _flatten_result_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _usage_signature(message: Mapping[str, object]) -> str:
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return ""
    try:
        return json.dumps(usage, sort_keys=True)
    except (TypeError, ValueError):
        return ""


@dataclass
class _Group:
    """Accumulator for the records that make up one API message."""

    key: str
    role: str
    line: int
    is_sidechain: bool
    timestamp: str
    usage: str
    calls: list[ToolCall] = field(default_factory=list)
    results: list[ToolResult] = field(default_factory=list)
    usage_conflicts: int = 0
    thinking_chars: int = 0
    thinking_signature_bytes: int = 0
    text_parts: list[str] = field(default_factory=list)
    #: `usage` above is the SIGNATURE (a json string, used to detect a grouping violation);
    #: `tokens` is the parsed count the cost report sums.
    tokens: Usage = Usage()
    model: str = ""


def iter_turns(path: Path | str, *, include_sidechains: bool = False) -> Iterator[Turn]:
    """Stream the transcript as Turns, grouping every record of one API message into one Turn.

    **The grouping must survive interleaving.** The records of one assistant message are NOT
    consecutive in the file: each `tool_use` block is followed by the `tool_result` that answered
    it, and the next `tool_use` block of the SAME message comes after that. So a group is held open
    across intervening user records and closed only when a NEW assistant `message.id` appears (a new
    API response means the previous one finished) or at EOF.

    Merging only consecutive records was this reader's first bug, and it produced exactly the wrong
    answer for the assertion that matters most: a message with ten `Agent` calls came out as ten
    one-call turns. If you change this function, re-check assertion 3 against a known transcript.

    Order: an assistant Turn is emitted before the user Turns that answered it, which is the logical
    order the assertions reason about (assertion 10 attributes polling to the preceding fan-out;
    assertion 9 pairs validate calls with their results). Only one assistant group and its pending
    user turns are ever held, so the read stays streaming — the corpus files are 2-3 MB each.

    A malformed line is SKIPPED, not fatal. These files are appended to live and a truncated last
    line is ordinary; refusing to read a 3 MB transcript because of it would make the scorecard
    unrunnable exactly when a run was interrupted."""
    index = 0
    group: _Group | None = None
    pending: list[_Group] = []          # user turns that arrived while `group` was open

    def emit(g: _Group) -> Turn:
        nonlocal index
        turn = Turn(index=index, role=g.role, tool_calls=tuple(g.calls),
                    tool_results=tuple(g.results), message_id=g.key, line=g.line,
                    is_sidechain=g.is_sidechain, timestamp=g.timestamp,
                    thinking_chars=g.thinking_chars,
                    thinking_signature_bytes=g.thinking_signature_bytes,
                    text="\n".join(g.text_parts).strip(),
                    usage=g.tokens, model=g.model)
        index += 1
        return turn

    def flush() -> Iterator[Turn]:
        nonlocal group, pending
        if group is not None and (include_sidechains or not group.is_sidechain):
            yield emit(group)
        group = None
        for p in pending:
            if include_sidechains or not p.is_sidechain:
                yield emit(p)
        pending = []

    with Path(path).open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            kind = record.get("type")
            if kind not in (ASSISTANT, USER):
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            # A TYPED MESSAGE ARRIVES AS A PLAIN STRING, not a list of blocks, and dropping it threw
            # away the only records that are the operator talking. On the 2026-09-06 mcpolis build
            # 77 user records carried a string: the `/coyomap build` that started the build, 75
            # task-notifications, and the one word the operator typed to unblock it. The scorecard's
            # "did anyone notice" assertion read 0 operator lines on a session that had one, and
            # nothing said the reader had not looked.
            blocks: Sequence[object] = (
                content if isinstance(content, list)
                else [{"type": "text", "text": content}] if isinstance(content, str) and content
                else [])

            record_ts = record.get("timestamp")
            record_ts = record_ts if isinstance(record_ts, str) else ""
            calls: list[ToolCall] = []
            results: list[ToolResult] = []
            think_chars = think_sig = 0
            texts: list[str] = []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use":
                    name = block.get("name")
                    args = block.get("input")
                    uid = block.get("id")
                    calls.append(ToolCall(name=name if isinstance(name, str) else "",
                                          input=args if isinstance(args, dict) else {},
                                          id=uid if isinstance(uid, str) else "",
                                          timestamp=record_ts))
                elif btype == "text":
                    body = block.get("text")
                    if isinstance(body, str) and body.strip():
                        texts.append(body)
                elif btype in ("thinking", "redacted_thinking"):
                    body = block.get("thinking")
                    sig = block.get("signature") or block.get("data")
                    think_chars += len(body) if isinstance(body, str) else 0
                    think_sig += len(sig) if isinstance(sig, str) else 0
                elif btype == "tool_result":
                    tid = block.get("tool_use_id")
                    results.append(ToolResult(
                        tool_use_id=tid if isinstance(tid, str) else "",
                        content=_flatten_result_content(block.get("content")),
                        is_error=bool(block.get("is_error"))))

            sidechain = bool(record.get("isSidechain"))
            ts = record.get("timestamp")
            timestamp = ts if isinstance(ts, str) else ""
            mid = message.get("id")

            if kind == USER:
                # `text_parts` was dropped here, so a USER turn reached the reader carrying tool
                # RESULTS and nothing the operator said. Combined with the ASSISTANT filter in
                # `format_turns`, that made the operator structurally unreadable: measured on one
                # 642-turn build, 358 USER turns parsed and 0 carried text. A retrospective asked
                # "who noticed the missing section" and no mode of this reader could answer, while
                # its own ground rules forbid the raw-JSONL fallback.
                #
                # A tool_result block is not the operator talking, and `_message_texts` already
                # keeps those out of `texts` — so this carries the human's words only.
                pending.append(_Group(key=f"@{lineno}", role=USER, line=lineno,
                                      is_sidechain=sidechain, timestamp=timestamp, usage="",
                                      results=results, thinking_chars=think_chars,
                                      thinking_signature_bytes=think_sig,
                                      text_parts=texts))
                continue

            key = mid if isinstance(mid, str) and mid else f"@{lineno}"
            model = message.get("model")
            model = model if isinstance(model, str) else ""
            if group is not None and group.key == key:
                sig = _usage_signature(message)
                if sig and group.usage and sig != group.usage:
                    group.usage_conflicts += 1
                group.calls.extend(calls)
                group.results.extend(results)
                group.thinking_chars += think_chars
                group.thinking_signature_bytes += think_sig
                group.text_parts.extend(texts)
                # MERGED, never summed — every record of this message repeats the same counts.
                group.tokens = _merge_usage(group.tokens, _usage_of(message))
                group.model = group.model or model
                continue

            yield from flush()
            group = _Group(key=key, role=ASSISTANT, line=lineno, is_sidechain=sidechain,
                           timestamp=timestamp, usage=_usage_signature(message),
                           calls=calls, results=results, thinking_chars=think_chars,
                           thinking_signature_bytes=think_sig, text_parts=texts,
                           tokens=_usage_of(message), model=model)

    yield from flush()


def read_turns(path: Path | str, *, include_sidechains: bool = False) -> tuple[Turn, ...]:
    """Every Turn, materialised. Convenience for the assertions, which make several passes."""
    return tuple(iter_turns(path, include_sidechains=include_sidechains))


def grouping_is_consistent(path: Path | str) -> bool:
    """Did any `message.id` carry two different `usage` blocks?

    The turn grouping rests on 'one message id == one API response'. This re-reads the file and
    checks that assumption directly, so a harness format change surfaces as a false grouping
    assumption rather than as a silently wrong fan-out number."""
    seen: dict[str, str] = {}
    with Path(path).open(encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("type") != ASSISTANT:
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            mid = message.get("id")
            sig = _usage_signature(message)
            if not isinstance(mid, str) or not sig:
                continue
            if mid in seen and seen[mid] != sig:
                return False
            seen[mid] = sig
    return True


def bash_commands(turns: Sequence[Turn]) -> tuple[tuple[int, str], ...]:
    """(turn index, command) for every Bash call, in order. The workhorse for assertions 1, 2, 4,
    7, 8 and 10, all of which ask 'what did the agent run'."""
    return tuple((t.index, c.command) for t in turns for c in t.calls_named("Bash") if c.command)


#: The canonical `coyomap` / `coyomap-eval` subcommands. An ALLOWLIST, because builds alias the
#: binary (`CX=…/coyomap; $CX audit …`) and a pattern loose enough to catch `$CX audit` is also
#: loose enough to read `$SP files` or `--map x` as subcommands — the first cut of this reported
#: `files`, `loc`, `map` and `runs`.
_COYOMAP_SUBCOMMANDS = frozenset({
    "anchor-drift", "archive", "arrows", "assemble", "audit", "balance", "bless", "changes", "claims",
    "compare", "impact", "reanchor",
    "contract", "cost", "diff", "dump", "field-score", "finalize", "fix", "grounding", "hash", "judge",
    "ledger", "lint-fragment", "live-numbers",
    "mutate", "preindex",
    "process", "protocol", "provenance", "reconcile", "record", "render", "retro-precheck", "walk-score",
    "context", "export", "run", "score", "scope", "serve", "url", "ship", "timings", "transcript",
    "validate",
})

#: Sub-verbs worth reporting separately: `grounding write` and `grounding report` are different
#: acts, and so are the `fix` verbs. Anything else is reported at subcommand granularity.
#:
#: This list must hold EVERY verb the three multi-verb subcommands dispatch on — `fix`, `grounding`
#: and `provenance` — and it did not. `row`, `security-row`, `dedup-security`, `lint`, `stamp` and
#: `show` were missing, so `coyomap fix row` was tabled as a bare `fix` and `provenance stamp` as
#: `provenance`. On a live build that hid SIX `fix row` calls behind one `fix 1` row, and a
#: retrospective reading this index — which the retro method tells it to trust — published "no
#: `fix row` invocation in the whole build". Same bug class as the alias-blind subcommand list
#: above, at the next level down.
#:
#: `test_subverbs_cover_every_dispatched_verb` reads the three dispatch tables and fails when a new
#: verb ships without landing here, which is the half a comment cannot enforce.
_COYOMAP_SUBVERBS = frozenset({
    # fix
    "apply-drift", "drop-edge", "dedup-relation", "dedup-edge", "security-row", "dedup-security",
    "row", "rows",
    # grounding
    "write", "report", "lint",
    # provenance
    "stamp", "show",
})

#: `coyomap <subcommand>` anywhere in a shell command, including behind `;`, `&&` or a `$CX` alias.
#: The one-line index truncates at 100 characters, so a subcommand chained after another was
#: INVISIBLE there — and a retrospective concluded from the index that `grounding write` "never ran"
#: in a build that ran it at turn 489, chained behind an `assemble`. The finding was published, then
#: withdrawn. Counting from the full command text is the fix; the index stays short on purpose.
#:
#: The alias branch accepts an OPTIONAL pair of quotes around the expansion. `"$CY" record …` is the
#: careful spelling — a build reached for it precisely because the unquoted form had just been
#: word-split by zsh — and it did not match, so 42 successful `record` calls were invisible while
#: the ONE invocation the table did report was the earlier one that FAILED. A retrospective read
#: `record 1` off that table and concluded the command had barely been used.
#:
#: The separator between binary and subcommand is `[ \t]`, NEVER `\s`. With `\s+` the alias branch
#: matched ACROSS A NEWLINE: `echo "$PWD"\ncoyomap validate m.json` read as alias `$PWD` + subcommand
#: `coyomap`, which is not in the allowlist, and `finditer` then resumed PAST the real invocation —
#: so an ordinary two-line command silently lost its coyomap call.
#: Groups are NAMED. They were positional, and `summarise_call` read `group(1)`/`group(2)` as
#: (subcommand, verb) from 60 lines away; adding the binary branch shifted both and the index
#: silently stopped naming the subcommands it truncates — the very regression that annotation was
#: added to prevent. Two tests caught it; a name cannot shift.
_COYOMAP_CMD = re.compile(
    r"""(?:(?P<bin>coyo(?:map|dex)(?:-eval)?)|["']?(?P<alias>\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)["']?)"""
    r"[ \t]+(?!-)(?P<sub>[a-z][a-z0-9-]*)(?:[ \t]+(?P<verb>[a-z][a-z0-9-]*))?")


def _label(m: "re.Match[str]") -> str | None:
    """`subcommand [verb]` for a match, or None when the subcommand is not one of ours."""
    sub, verb = m.group("sub"), m.group("verb")
    if sub not in _COYOMAP_SUBCOMMANDS:
        return None
    return f"{sub} {verb}" if verb in _COYOMAP_SUBVERBS else sub

#: `--help` / `-h` as a standalone word. Applied to ONE shell segment (see `_segments`), never to
#: "the rest of the line": scanning forward from the match let ANY later program's flag delete a real
#: invocation — `coyomap dump m.json > f.json && du -h f.json` scored zero `dump` runs, and so did
#: every `&& df -h`, `&& sort -h` and `&& python build.py --help`. That is the same silent
#: under-count this whole scan was rewritten to end, re-created by the fix for it.
_HELP_ONLY = re.compile(r"(?:^|\s)(?:--help|-h)(?:\s|$)")

#: `CY=/path/to/.venv/bin/coyomap` / `CX="…/coyomap-eval"` — a shell alias for one of the two CLIs.
#:
#: The value may end at whitespace OR at any shell metacharacter. Requiring whitespace missed the
#: most natural one-liner, `CY=…/coyomap-eval; $CY score a b`, so a `coyomap-eval` run was booked to
#: the `coyomap` table — the exact mis-attribution the binary split exists to end.
#:
#: This DOES also match `COYOMAP_HOME=/p/coyomap`, which names a directory rather than the binary.
#: That is harmless and `test_a_directory_env_var_produces_no_invocation` pins why: a directory is
#: used as `$COYOMAP_HOME/method.md`, with no space between the variable and what follows, so it
#: never satisfies `_COYOMAP_CMD`.
_ALIAS_ASSIGN = re.compile(
    r"""\b([A-Za-z_][A-Za-z0-9_]*)=["']?\S*?/(coyo(?:map|dex)(?:-eval)?)["']?(?=[\s;&|)]|$)""")


def _mask(text: str) -> list[bool]:
    """Per-character: is this ORDINARY shell syntax — outside quotes and outside a comment?

    ONE scanner, because there were two and they disagreed by construction. `_heredoc_tags` reset
    its quote state per line while `_segments` ran over the whole text, so a single unbalanced quote
    — `# don't do this` at the top of a command — swallowed every later newline and separator into
    one segment, and a later program's `-h` again deleted a real invocation. That is the round-one
    defect returning through a different door, and six real commands across the transcript corpus
    are one `sort -h` away from it.

    Quote DELIMITERS count as ordinary; only their CONTENT does not. `"$CY" record` must still be
    found, while `echo "…coyomap reconcile…"` must not.

    Comments are handled here rather than anywhere else, and that is what actually fixes the case
    above: `#` outside quotes, at the start of a word, comments out the rest of the LINE — so the
    apostrophe in `don't` never enters quote state at all. It also closes `# use << EOF to redirect`,
    which used to open a phantom heredoc and blank everything below it.

    UNBALANCED quotes fall back to "no quoting at all" (comments still apply). An unterminated quote
    is broken input; letting it mask the rest of the command turns one typo into a silent, total
    under-count, and over-counting a fragment of prose is the cheaper error."""
    for ignore_quotes in (False, True):
        out: list[bool] = []
        quote = ""
        comment = False
        i, n = 0, len(text)
        balanced = True
        while i < n:
            c = text[i]
            if c == "\n":
                comment = False
                quote = quote if not ignore_quotes else ""
                out.append(True)
                i += 1
                continue
            if comment:
                out.append(False)
                i += 1
                continue
            if quote:
                if c == "\\" and quote == '"' and i + 1 < n:
                    out.extend((False, False))
                    i += 2
                    continue
                out.append(c == quote)          # the closing delimiter is ordinary again
                if c == quote:
                    quote = ""
                i += 1
                continue
            if c == "\\" and i + 1 < n:
                out.extend((True, False))
                i += 2
                continue
            if c in "'\"" and not ignore_quotes:
                quote = c
                out.append(True)                # the opening delimiter is ordinary
                i += 1
                continue
            if c == "#" and (i == 0 or text[i - 1] in " \t\n;&|("):
                comment = True
                out.append(False)
                i += 1
                continue
            out.append(True)
            i += 1
        balanced = not quote
        if balanced or ignore_quotes:
            return out
    return out                                   # unreachable; the loop's second pass always returns


#: A heredoc tag may hold anything a filename may — `<<'PY-END'`, `<<"EOF.1"`. Reading it as
#: `[A-Za-z0-9_]+` truncated the tag, so the terminator was never recognised and the body blanked
#: every invocation below it: a valid heredoc silently deleted the rest of the command.
_TAG_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.+"


def _heredoc_opens(line: str, mask: Sequence[bool]) -> list[tuple[str, bool]]:
    """Every heredoc this line opens, as `(terminator, leading tabs allowed)`, in order.

    `<<-` is the only form whose terminator may be indented, and only by TABS. Accepting an indented
    terminator for a plain `<<TAG` ended the body early and read the rest of it as shell — inventing
    invocations, which is what heredoc stripping exists to prevent.

    Quote- and comment-awareness comes from the shared mask; `<<<` is a here-STRING with no body."""
    opens: list[tuple[str, bool]] = []
    i, n = 0, len(line)
    while i < n:
        if not (mask[i] and line.startswith("<<", i)):
            i += 1
            continue
        if line.startswith("<<<", i):
            i += 3
            continue
        j = i + 2
        dashed = j < n and line[j] == "-"
        if dashed:
            j += 1
        while j < n and line[j] in " \t":
            j += 1
        if j < n and line[j] in "'\"":
            quote = line[j]
            k = line.find(quote, j + 1)
            if k > j:
                opens.append((line[j + 1:k], dashed))
                i = k + 1
                continue
            i = j + 1
            continue
        k = j
        while k < n and line[k] in _TAG_CHARS:
            k += 1
        if k > j:
            opens.append((line[j:k], dashed))
            i = k
            continue
        i = j + 1
    return opens


def _strip_heredocs(cmd: str) -> str:
    """`cmd` with every heredoc BODY blanked out, terminators and all else kept.

    A build writes plenty of coyomap-shaped text into one — contract templates, notes, generated
    docs — and a live `cat > rules-contract.md <<'EOF'` body made `dump` and `lint-fragment` appear
    as invocations at a turn that ran neither.

    Several heredocs queue in the order they were opened. An UNterminated heredoc (a truncated
    command) blanks to the end — the safe direction there: dropping data can only cost a finding,
    while keeping it invents one."""
    mask = _mask(cmd)
    out: list[str] = []
    queue: list[tuple[str, bool]] = []
    pos = 0
    for line in cmd.splitlines():
        line_mask = mask[pos:pos + len(line)]
        pos += len(line) + 1
        if queue:
            tag, dashed = queue[0]
            ends = (line.lstrip("\t") if dashed else line) == tag
            out.append(line if ends else "")
            if ends:
                queue.pop(0)
            continue
        out.append(line)
        queue.extend(_heredoc_opens(line, line_mask))
    return "\n".join(out)


#: A shell segment boundary OUTSIDE quotes. `;;` is `case`; `|&` is bash's pipe-with-stderr.
_SEGMENT_SEPARATORS = ("&&", "||", ";;", "|&", ";", "|", "&", "\n")


def _segments(text: str) -> list[tuple[str, list[bool]]]:
    """`text` split into shell segments — one command each — with each segment's mask.

    The unit a `--help` belongs to is the SEGMENT it sits in, not the line and not "up to the next
    coyomap call". Getting that wrong is what let `&& du -h` erase a real invocation."""
    mask = _mask(text)
    out: list[tuple[str, list[bool]]] = []
    start = 0
    i, n = 0, len(text)
    while i < n:
        hit = ""
        if mask[i]:
            hit = next((s for s in _SEGMENT_SEPARATORS if text.startswith(s, i)
                        and all(mask[i:i + len(s)])), "")
        if hit:
            out.append((text[start:i], mask[start:i]))
            i += len(hit)
            start = i
            continue
        i += 1
    out.append((text[start:], mask[start:]))
    return [(t, m) for t, m in out if t.strip()]


#: A quoted span, for blanking before a `--help` test: `record --line "see --help for details"` is
#: an argument that happens to mention the flag, not a help run.
_QUOTED_SPAN = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")


#: A transcript is history. One written before 2026-09-13 calls the tool `coyodex`, its name at the
#: time, and nothing can rename it. So the scan reads both spellings and books both to the `coyomap`
#: tables; without this every pre-rename build transcript scored 0/0 on every process assertion.
def _canonical_binary(name: str) -> str:
    """`coyodex` / `coyodex-eval`, as an old transcript reads, as the CLI is called now."""
    return "coyomap" + name[len("coyodex"):] if name.startswith("coyodex") else name


def _alias_binaries(cmd: str) -> dict[str, str]:
    """`{VAR: "coyomap" | "coyomap-eval"}` for every alias assigned in this command."""
    return {m.group(1): _canonical_binary(m.group(2)) for m in _ALIAS_ASSIGN.finditer(cmd)}


def _binary_of(token: str, aliases: Mapping[str, str]) -> str:
    """Which CLI `token` invokes — the literal name, the resolved alias, or the `coyomap` fallback."""
    bare = token.strip("\"'")
    if bare.endswith(("coyomap-eval", "coyodex-eval")):
        return "coyomap-eval"
    if bare.endswith(("coyomap", "coyodex")):
        return "coyomap"
    var = bare.lstrip("$").strip("{}")
    return aliases.get(var, "coyomap")


@dataclass(frozen=True)
class Invocation:
    """One coyomap CLI call found in a Bash command."""

    turn: int
    name: str               #: `subcommand` or `subcommand verb`
    binary: str             #: "coyomap" | "coyomap-eval"
    alias_resolved: bool    #: False when `binary` is the fallback guess rather than a reading


def _iter_invocations(turns: "Sequence[Turn]") -> "Iterator[Invocation]":
    """Every coyomap invocation in these turns, ONE scan.

    Both `coyomap_subcommands` and `unresolved_aliases` read this, and so does the index annotation
    in `summarise_call`. They used to scan separately and disagree: the alias footer applied no
    `--help` filter, and the index applied nothing at all — so it named `dump` and `lint-fragment`
    at turns whose only mention of them was a heredoc contract-template body, pointing the reader
    at a `--commands` table that denied them.

    Order matters and is the fix for a whole class of bug. Heredoc bodies go first (they are data,
    not commands), THEN the text is split into segments, and only then is each segment matched. An
    earlier cut matched against the stripped text but read the `--help` tail out of the ORIGINAL, so
    every character the stripping removed shifted that read earlier and the two fixes silently
    mis-composed."""
    for idx, cmd in bash_commands(turns):
        for inv in _invocations_in(cmd):
            yield replace(inv, turn=idx)


#: `name() {` / `function name {` — a shell function definition, whose body is a TEMPLATE that runs
#: once per call, not once per definition.
_FUNC_DEF = re.compile(r"(?:function[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*\([ \t]*\)[ \t]*\{")


def _extract_functions(text: str) -> "tuple[str, dict[str, str]]":
    """`(text with the definitions removed, {name: body})`, brace-matched outside quotes.

    A build that has 6 near-identical edits to make writes the invocation ONCE in a function and
    calls it 6 times. Scanning the raw text counts the DEFINITION — one — and misses every call, so
    `coyomap fix row` run six times at one turn was tabled as a single `fix`, and a retrospective
    reading this index concluded the verb never ran. Removing the definition before segmenting and
    replaying its body per call is what makes the count the number of RUNS.

    Only definitions are lifted here; whether a body holds a coyomap call is decided by the caller,
    so a helper that wraps `grep` costs nothing and expands to nothing."""
    mask = _mask(text)
    bodies: dict[str, str] = {}
    spans: list[tuple[int, int]] = []
    for m in _FUNC_DEF.finditer(text):
        if not mask[m.start()]:
            continue
        depth, i, n = 1, m.end(), len(text)
        while i < n and depth:
            if mask[i]:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
            i += 1
        if depth:                      # unbalanced — leave the text alone rather than guess
            continue
        bodies[m.group(1)] = text[m.end():i - 1]
        spans.append((m.start(), i))
    for lo, hi in reversed(spans):     # reversed so earlier offsets stay valid
        text = text[:lo] + " " + text[hi:]
    return text, bodies


def _invocations_in(cmd: str) -> "list[Invocation]":
    """Every coyomap invocation in ONE shell command. `turn` is 0; callers stamp it."""
    stripped = _strip_heredocs(cmd).replace("\\\n", " ")
    # The alias map comes from the STRIPPED text: a `COY=…/coyomap` line inside a contract template
    # written into a heredoc is documentation, and treating it as an assignment made an outer `$COY`
    # look resolved when it was still a guess — under-reporting the footer's own uncertainty.
    aliases = _alias_binaries(stripped)
    # Aliases are read BEFORE the definitions are lifted: `CX=…/coyomap` sits outside the function
    # that uses `$CX`, and a body scanned without it resolves to the fallback binary.
    stripped, functions = _extract_functions(stripped)
    expansions = {name: _scan_segments(body, aliases) for name, body in functions.items()}
    expansions = {name: invs for name, invs in expansions.items() if invs}
    out: list[Invocation] = []
    for segment, _mask_unused in _segments(stripped):
        first = segment.strip().split(None, 1)[0] if segment.strip() else ""
        if first in expansions:
            out.extend(expansions[first])
            continue
        out.extend(_scan_segments(segment, aliases))
    return out


def _scan_segments(text: str, aliases: "Mapping[str, str]") -> "list[Invocation]":
    """Every coyomap invocation in `text`, segment by segment. `turn` is 0; callers stamp it."""
    out: list[Invocation] = []
    for segment, mask in _segments(text):
        pos = 0
        while pos < len(segment):
            m = _COYOMAP_CMD.search(segment, pos)
            if m is None:
                break
            # Advance by ONE on a non-match, never past the match: `$WRAPPER coyomap audit m.json`
            # matched the alias branch with `coyomap` as the subcommand, which is not in the
            # allowlist, and skipping to `m.end()` stepped over the real binary behind it.
            label = _label(m)
            if label is None or not mask[m.start()]:
                pos = m.start() + 1
                continue
            nxt = _COYOMAP_CMD.search(segment, m.end())
            tail = segment[m.end():nxt.start() if nxt else len(segment)]
            if _HELP_ONLY.search(_QUOTED_SPAN.sub(" ", tail)):
                pos = m.end()
                continue
            token = m.group("bin") or m.group("alias") or ""
            out.append(Invocation(
                turn=0,
                name=label,
                binary=_binary_of(token, aliases),
                alias_resolved=bool(m.group("bin"))
                or token.lstrip("$").strip("{}\"'") in aliases))
            pos = m.end()
    return out


def unresolved_aliases(turns: "Sequence[Turn]") -> int:
    """How many COUNTED invocations went through an alias this reader could not resolve.

    The fallback in `_binary_of` is a guess, and a guess that is never surfaced is indistinguishable
    from a measurement. The `--commands` footer prints this so a reader knows how much of the
    coyomap table rests on it."""
    return sum(1 for inv in _iter_invocations(turns) if not inv.alias_resolved)


def coyomap_subcommands(turns: "Sequence[Turn]", *,
                        binary: str | None = None) -> "list[tuple[int, str]]":
    """(turn index, `subcommand [verb]`) for every coyomap invocation found ANYWHERE in a Bash
    command — not only at its head. See `_COYOMAP_CMD` for why that distinction cost a real
    finding, and `_COYOMAP_SUBCOMMANDS` for why it is an allowlist.

    Heredoc bodies are excluded and `--help` runs are not counted: both make the table claim work
    that did not happen. See `_iter_invocations` for the ordering the two together demand.

    `binary` filters by which CLI was invoked — `"coyomap"` or `"coyomap-eval"`. The two share this
    allowlist because they share subcommand names (`score`, `compare`, `archive`, `process`), so a
    table headed "coyomap invocation(s)" was counting `coyomap-eval archive` runs as build work. An
    ALIASED invocation resolves from the `VAR=…` assignment in the SAME command, which is where
    builds put it — each Bash call is a fresh shell. An alias that still cannot be resolved falls to
    `coyomap`: a build runs that binary and rarely the other, and `unresolved_aliases()` reports how
    much of the table rests on the fallback."""
    return [(inv.turn, inv.name) for inv in _iter_invocations(turns)
            if binary is None or inv.binary == binary]


def summarise_call(call: ToolCall, width: int = 100) -> str:
    """One line describing a tool call — the command for Bash, the description for an Agent, the
    path for a file tool, the first field otherwise."""
    if call.name == "Bash":
        text = " ".join(call.command.split())
    elif call.name in ("Agent", "Task"):
        desc = call.input.get("description")
        text = desc if isinstance(desc, str) else ""
    else:
        target = call.input.get("file_path") or call.input.get("path") or call.input.get("pattern")
        text = target if isinstance(target, str) else ""
    if not text:
        text = " ".join(call.text().split())
    if len(text) <= width:
        return text
    # Say WHAT the truncation hid, when what it hid is a coyomap subcommand. The index is short on
    # purpose, but a reader treats it as the list of what ran: a retrospective read this index,
    # concluded `grounding write` never ran, and published that about a build which ran it at turn
    # 489 chained behind an `assemble`. The finding was withdrawn. `--commands` was the answer and
    # nothing in the index pointed at it, so the index now names the subcommands it is cutting off.
    # Ask the SHARED scan, not a bare regex over the truncated tail. Scanning the tail counted
    # heredoc bodies and `--help` lookups, so the index named runs the `--commands` table denied —
    # and this annotation exists because a retro trusted the index. Naming something the table will
    # not confirm is the same failure pointing the other way.
    visible = {i.name for i in _invocations_in(text[:width])}
    hidden: list[str] = []
    for inv in _invocations_in(call.command):
        if inv.name not in visible and inv.name not in hidden:
            hidden.append(inv.name)
    if hidden:
        return f"{text[:width]} …+{', '.join(hidden)} (use --commands)"
    return text[:width]


#: How many lines of a tool call's COMMAND `--full` prints before truncating. `--full-output` lifts
#: it, exactly as it lifts the result cap. It used to be a bare `[:40]` slice with no marker and no
#: flag, so a reader could not tell a 40-line command from a 373-line one.
COMMAND_LINES = 40


#: Text a USER-role record carries that the OPERATOR did not type. A Claude Code transcript files
#: skill bodies, `<system-reminder>` blocks, slash-command expansions and IDE notices under the same
#: role as the human's own messages. Labelling those `(operator)` is the failure mode the whole
#: change is exposed to: the question it exists to answer is "who noticed this", and machine text
#: rendered as a person is a worse answer than no answer. Measured on one real session: of 22
#: text-carrying USER turns, 20 were human, 1 a skill body and 1 an `<ide_opened_file>` notice.
#: `<command-name>` and `<command-message>` are NOT here. They mark a slash-command WRAPPER, which
#: carries the operator's own words inside it — so they are recognised by an ANCHORED match in
#: `operator_text`, not by a substring test. As substring markers they hid every message that merely
#: quoted the tag, including a real operator's, and rendered the quotation as if it were the command.
_HARNESS_TEXT = (
    "<system-reminder", "<local-command-",
    # EVERY CLASS BELOW ARRIVES AS A PLAIN STRING, so all of them became visible at once when the
    # reader started accepting one — and each would render as the operator speaking, which the
    # docstring below calls a worse answer than no answer. Counted on this machine's 1,938
    # transcripts: 242 security-review prompts, 178 image placeholders, 75 task notifications on one
    # build alone, 16 cross-session messages, and two continuation summaries of 19,846 and 21,094
    # characters on a single session. An adversarial reader found them by diffing the old reader
    # against the new one on real transcripts, which is the only way this was ever going to surface.
    #
    # LONG MARKERS ON PURPOSE. These are substring-matched over the first 400 characters, so a short
    # one eats real operator text: "Skill /" would swallow a person writing "use the Skill /debrief".
    # Each marker here is long enough that a person would have to quote the harness to trip it.
    "<task-notification",
    # A skill re-announcing itself mid-message: "Skill /debrief is already loaded above;
    # instructions unchanged". It does not START the record, so head-anchoring cannot reach
    # it, and the phrase is specific enough that a person would have to quote the harness.
    "is already loaded above; instructions unchanged",
    "<ide_", "Base directory for this skill:", "Caveat: The messages below were generated",
)


#: A slash-command record: the harness WRAPS what the operator typed rather than replacing it. The
#: words are in `<command-args>` (and `<command-name>` says which command), so dropping the whole
#: record throws away the operator's own message. On the 2026-09-02 mcpolis transcript that is how
#: `--full` rendered **0 of 74** operator records: every one of them was a slash command.
_SLASH_COMMAND = re.compile(r"<command-name>\s*(?P<name>[^<]*?)\s*</command-name>", re.S)
_COMMAND_ARGS = re.compile(r"<command-args>(?P<args>.*?)</command-args>", re.S)
_COMMAND_MESSAGE = re.compile(r"\A<command-message>.*?</command-message>\s*", re.S)


#: Machine text that arrives as a PLAIN STRING and is matched at the HEAD, not anywhere in the
#: message. The tuple above is substring-matched, and the docstring below says why that is
#: dangerous: it "hid every message that merely quoted the tag, including a real operator's". These
#: markers were added after string content started reaching the reader at all, and a reviewer showed
#: that as substrings they ate plausible operator sentences — "Review this change for security
#: vulnerabilities before I commit it", "the reader still shows [Request interrupted by user] as if
#: I typed it". Anchored at the head, and long enough to carry the harness's own punctuation, a
#: person has to reproduce the machine's opening word for word to be hidden.
#:
#: `[Request interrupted by user` is deliberately ABSENT. It arrives as a list-content block, not a
#: string, so it was already visible before this change and hiding it would be a new removal rather
#: than a repair — 57 records across 30 sessions, and the fact that a person interrupted is
#: something a retro wants to see.
_HARNESS_HEAD = (
    "Review this change for security vulnerabilities. Changed files",
    "[Image: original ",
    "Another Claude session sent a message: <cross-session-message",
    "This session is being continued from a previous conversation",
    "(Re-invocation of /",
    "You check Claude's final message to one specific user",
)


def operator_text(text: str) -> str:
    """What the OPERATOR actually typed in this record, or "" when they typed nothing.

    Three shapes. Plain words are themselves. A slash-command wrapper is unwrapped to
    `/<name> <args>` — the words the operator typed, which is exactly what a reader auditing "who
    noticed this" needs. Anything else the harness files under the user role (a skill body, a
    `<system-reminder>`, an IDE notice) is machine text and stays hidden: rendering that as a person
    is a worse answer than no answer."""
    head = text.lstrip()
    # THE HARNESS FILTER RUNS FIRST. Searching for the wrapper before it meant any body that merely
    # MENTIONED `<command-name>` was rendered as an operator saying `/that-command`: a
    # `<system-reminder>` quoting one, a skill body describing one, and — worst — a real operator
    # message that quotes the tag, whose actual words were then thrown away. The docstring's own
    # rule is that machine text rendered as a person is worse than no answer, and the test that was
    # meant to hold it only used bodies with no wrapper in them.
    if any(marker in head[:400] for marker in _HARNESS_TEXT):
        return ""
    if head.startswith(_HARNESS_HEAD):
        return ""
    # ANCHORED AT THE HEAD, not searched. A slash-command record opens with the wrapper (optionally
    # after a `<command-message>` block); a wrapper found deeper in a body is a quotation.
    name = _SLASH_COMMAND.match(_COMMAND_MESSAGE.sub("", head).lstrip())
    if name is not None:
        args = _COMMAND_ARGS.search(head)
        body = (args.group("args").strip() if args else "")
        # LSTRIP THE SLASH THE TAG MAY ALREADY CARRY. Claude Code 2.1.263 writes
        # `<command-name>/coyomap</command-name>`; an earlier version wrote the bare word, which is
        # what this line was built for. Prepending unconditionally rendered the command that started
        # the 2026-09-06 mcpolis build as `//coyomap build`.
        return f"/{name.group('name').lstrip('/')}" + (f" {body}" if body else "")
    return text


def format_turns(turns: Sequence[Turn], *, full: bool = False, results: dict[str, str] | None = None,
                 width: int = 100, result_chars: int = 600, result_lines: int = 20) -> str:
    """Render turns as readable text.

    Two densities, for two readers. The compact form is an INDEX — one line per tool call — so a
    lead can see the whole run at a glance and pick the range worth reading. `full` adds the entire
    command and a slice of what it printed, which is what a sub-agent needs to judge one phase.

    This exists because a retrospective has to READ the transcript, and a 3 MB JSONL is not
    readable: opening one whole is both useless and expensive."""
    lines: list[str] = []
    unlimited = result_chars < 0
    for turn in turns:
        if turn.role != ASSISTANT:
            # A USER turn with words is the OPERATOR, and it is the one thing this reader could
            # never show. It appears only in `--full` (the index is one line per tool call) and
            # only when it carries text, so a bare tool-result turn stays invisible as before.
            spoken = operator_text(turn.text)
            if full and spoken.strip():
                said = spoken.splitlines()
                kept = said if unlimited else said[:result_lines]
                lines.append(f"[{turn.index:>4}] (operator) " + "\n        . ".join(kept))
                if len(said) > len(kept):
                    lines.append(f"        . … {len(said) - len(kept)} more line(s) "
                                 f"(--full-output for all of it)")
                lines.append("")
            continue
        # A turn with no tool call is invisible in the INDEX by design — the index is one line per
        # call. In `full` it must not be, because a whole class of method rule produces exactly that
        # shape: "show `scope`'s output verbatim as your first message", "announce the mode", warn
        # before overwriting a baseline, "the wait at a barrier is a TEXT turn". A retrospective
        # trying to audit those found nothing and fell back to hand-parsing the raw JSONL.
        if not turn.tool_calls and not (full and turn.text):
            continue
        if full and turn.text:
            said = turn.text.splitlines()
            kept = said if unlimited else said[:result_lines]
            lines.append(f"[{turn.index:>4}] (said) " + "\n        . ".join(kept))
            if len(said) > len(kept):
                lines.append(f"        . … {len(said) - len(kept)} more line(s) "
                             f"(--full-output for all of it)")
            if not turn.tool_calls:
                lines.append("")
                continue
        if full and turn.thinking_signature_bytes and not turn.thinking_chars:
            # SAY that reasoning existed and was withheld. Dropping the block silently made
            # "the agent did not consider X" indistinguishable from "the agent's reasoning is
            # redacted", and a retrospective had to downgrade three findings for want of the
            # difference.
            lines.append(f"[{turn.index:>4}] (thinking redacted — "
                         f"{turn.thinking_signature_bytes} signature byte(s), no visible text)")
        for call in turn.tool_calls:
            head = f"[{turn.index:>4}] {call.name:<14}"
            if full:
                body = call.command if call.name == "Bash" else call.text()
                lines.append(f"{head} {summarise_call(call, width)}")
                if body and body != summarise_call(call, width):
                    # The COMMAND cap. It was a bare `[:40]` with no marker and no way to lift it,
                    # while the RESULT path below printed a truncation line and honoured
                    # `--full-output`. `--full`'s own help says "include the whole command", and 9
                    # of one build's 197 tool-call bodies were longer than the cap — the worst lost
                    # 333 of its 373 lines, silently. A retrospective hunting hand-written
                    # substitutes for tool calls is exactly the reader this blinded.
                    cmd_lines = body.splitlines()
                    cmd_kept = cmd_lines if unlimited else cmd_lines[:COMMAND_LINES]
                    lines.append("        | " + "\n        | ".join(cmd_kept))
                    if len(cmd_lines) > len(cmd_kept):
                        lines.append(f"        | … {len(cmd_lines) - len(cmd_kept)} more line(s) "
                                     f"(--full-output for all of it)")
                out = (results or {}).get(call.id, "")
                if out:
                    snippet = out if unlimited else out[:result_chars]
                    body_lines = snippet.splitlines()
                    shown = body_lines if unlimited else body_lines[:result_lines]
                    lines.append("        > " + "\n        > ".join(shown))
                    if not unlimited and len(out) > len(snippet):
                        lines.append(f"        > … {len(out) - len(snippet)} more char(s) "
                                     f"(--result-chars N, or --full-output for all of it)")
                    elif not unlimited and len(body_lines) > len(shown):
                        lines.append(f"        > … {len(body_lines) - len(shown)} more line(s) "
                                     f"(--full-output for all of it)")
                lines.append("")
            else:
                lines.append(f"{head} {summarise_call(call, width)}")
    return "\n".join(lines)


def results_by_tool_use_id(turns: Sequence[Turn]) -> dict[str, str]:
    """`tool_use_id -> result text` across the whole transcript.

    Pairing by id, never by order: sub-agents run asynchronously in this harness, so a result can
    arrive several turns after the one that followed its call. Order-pairing silently attributes
    one command's output to another."""
    out: dict[str, str] = {}
    for turn in turns:
        for result in turn.tool_results:
            if result.tool_use_id:
                out[result.tool_use_id] = result.content
    return out


def errored_tool_use_ids(turns: Sequence[Turn]) -> set[str]:
    """The ids of calls whose result the harness flagged as an error.

    `is_error` was parsed, carried on `ToolResult`, and then thrown away by every consumer — so an
    assertion asking "did this command run" could not tell a completed run from one that exited 2 on
    an unknown flag, and reached for stdout text instead. Exit status is the cheaper and far more
    robust answer: of the seven paths on which `coyomap finalize` returns before doing its work, six
    exit non-zero and the seventh is `--help`."""
    return {r.tool_use_id for t in turns for r in t.tool_results if r.is_error and r.tool_use_id}


# --- CLI -------------------------------------------------------------------------------

USAGE = """usage: coyomap-eval transcript <transcript.jsonl> [--from N] [--to N]
                                 [--tool NAME] [--grep PATTERN] [--stats] [--commands]
                                 [--full] [--full-output] [--result-chars N]

READ a build transcript in slices — the retrospective's eye on what the agent actually did.
A 3 MB JSONL cannot be opened whole, so this prints an INDEX by default (one line per tool
call, with its turn number) and the FULL text of a range with --full.

  --from/--to   turn range (inclusive), as printed in the index
  --tool NAME   only turns using that tool (Bash, Agent, Write, …)
  --grep PAT    only tool calls whose text matches (case-insensitive substring)
  --full        include the whole command and a slice of what it printed
  --full-output --full with NO truncation of tool results (implies --full). Use it when the
                answer lives in the output — sub-agent returns and long listings are clipped at
                600 chars otherwise, which sent one reviewer back to parsing the raw JSONL.
  --result-chars N  raise (or lower) that per-result cap instead of removing it
  --stats       tool counts and fan-out sizes instead of a listing
  --commands    every `coyomap` subcommand run, with turn numbers and a total per subcommand —
                found ANYWHERE in a command, so one chained behind `;` or `&&` is not missed
                (the one-line index truncates, and that once produced a false "never ran")

`--from`/`--to` apply to EVERY mode, including --commands and --stats. They used to be accepted
and silently ignored by those two, so a reviewer reading one slice was handed whole-transcript
numbers with nothing saying so.
A turn whose reasoning is REDACTED (a signature with no visible text) is marked in --full, so
"did not reason here" and "reasoning withheld" stay distinguishable."""


def _stats(turns: Sequence[Turn]) -> str:
    from collections import Counter
    tools: Counter[str] = Counter()
    fanouts: list[tuple[int, int]] = []
    for turn in turns:
        for call in turn.tool_calls:
            tools[call.name] += 1
        if turn.agent_calls:
            fanouts.append((turn.index, len(turn.agent_calls)))
    lines = [f"{len(turns)} turn(s); {sum(tools.values())} tool call(s)", "", "TOOLS"]
    lines += [f"  {n:>5}  {name}" for name, n in tools.most_common()]
    lines += ["", f"FAN-OUTS ({len(fanouts)} turn(s) launching agents)"]
    lines += [f"  turn {idx:>4}: {n} agent(s)" for idx, n in fanouts]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    def opt(flag: str) -> str | None:
        return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None

    consumed = {opt(f) for f in ("--from", "--to", "--tool", "--grep", "--result-chars")}
    positional = [a for a in args if not a.startswith("--") and a not in consumed]
    if not positional:
        print("ERROR: give a transcript path\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    src = Path(positional[0])
    if not src.is_file():
        print(f"ERROR: no transcript at {src}", file=sys.stderr)
        return 2

    turns = read_turns(src)
    # PARSE AND APPLY THE RANGE FIRST. `--commands` and `--stats` used to run on the whole file
    # while accepting `--from`/`--to` and silently discarding them, so a sliced reviewer — told to
    # say "not in my range" rather than "the build skipped it" — was handed whole-transcript data
    # with nothing saying so. That is the exact failure the sliced-review protocol exists to
    # prevent, in the tool the protocol runs on.
    try:
        lo = int(opt("--from") or 0)
        hi = int(opt("--to") or 10**9)
    except ValueError:
        print("ERROR: --from and --to take an integer", file=sys.stderr)
        return 2
    ranged = tuple(t for t in turns if lo <= t.index <= hi)
    scope = "" if (lo == 0 and hi == 10**9) else f" in turns {lo}-{hi}"
    if scope and not ranged:
        print(f"no turns{scope} (the transcript holds {len(turns)} turn(s), indices 0-"
              f"{turns[-1].index if turns else 0})")
        return 0
    if "--commands" in args:
        from collections import Counter

        def table(found: list[tuple[int, str]], heading: str) -> None:
            counts = Counter(name for _i, name in found)
            by_name: dict[str, list[int]] = {}
            for i, name in found:
                by_name.setdefault(name, []).append(i)
            print(f"{heading}: {len(found)} invocation(s) across {len(counts)} subcommand(s)"
                  f"{scope}\n")
            print(f"{'subcommand':28} {'runs':>5}  turns")
            for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
                turns_s = ", ".join(str(t) for t in by_name[name][:12])
                if len(by_name[name]) > 12:
                    turns_s += f", … +{len(by_name[name]) - 12} more"
                print(f"  {name:26} {n:>5}  {turns_s}")

        # SPLIT BY BINARY. The two CLIs share subcommand names (`score`, `compare`, `archive`,
        # `process`), and one table headed "coyomap invocation(s)" reported a build's three
        # `coyomap-eval archive` calls as build work. A retro reading that over-counts the build.
        table(coyomap_subcommands(ranged, binary="coyomap"), "coyomap")
        evals = coyomap_subcommands(ranged, binary="coyomap-eval")
        # Only when present: on a build transcript this section is empty, and an empty table
        # reads as a gap rather than as "the build did not run the eval tool, which is correct".
        if evals:
            print()
            table(evals, "coyomap-eval")
        unresolved = unresolved_aliases(ranged)
        print("\n(`--help` runs are not counted, and heredoc bodies are not scanned — both make "
              "the table\n claim work that did not happen.)")
        # The OTHER direction, and the one that made a retrospective publish something false. This
        # scans TYPED SHELL TEXT: a subcommand another verb runs in-process is invisible, so
        # `coyomap ship` shows as one row while it runs eleven steps. One report said "`grounding
        # report` ran 0 times in the whole build" off this table, about a build that ran it at turn
        # 460 inside `ship`.
        print("(this reads TYPED shell text: a subcommand another verb runs internally is invisible"
              "\n here — `coyomap ship` is one row and runs eleven steps — so a zero in this table"
              "\n means 'never typed', never 'never ran'.)")
        if unresolved:
            print(f"({unresolved} invocation(s) went through an alias with no `VAR=…/coyomap` "
                  f"assignment in the\n same command, and are counted as `coyomap`.)")
        return 0
    if "--stats" in args:
        if scope:
            print(f"(turns {lo}-{hi} only)")
        print(_stats(ranged))
        return 0
    tool, pattern = opt("--tool"), (opt("--grep") or "").lower()
    # Filter the CALLS, not just the turns: one turn can carry a dozen calls, and keeping all of
    # them because one matched is not what `--grep` promises. A turn left with no matching call
    # drops out entirely.
    try:
        result_chars = -1 if "--full-output" in args else int(opt("--result-chars") or 600)
    except ValueError:
        print("ERROR: --result-chars takes an integer", file=sys.stderr)
        return 2
    full = "--full" in args or "--full-output" in args
    picked: list[Turn] = []
    for t in ranged:
        calls = t.tool_calls
        if tool:
            calls = tuple(c for c in calls if c.name == tool)
        if pattern:
            calls = tuple(c for c in calls if pattern in c.text().lower())
        if calls:
            picked.append(replace(t, tool_calls=calls))
        elif full and t.text and not tool and not pattern:
            # An UNFILTERED --full read is "everything in this range", and assistant prose is part
            # of it. A --tool/--grep read is a question about tool calls, so a text-only turn is not
            # an answer to it and stays out.
            picked.append(replace(t, tool_calls=()))
    if not picked and (tool or pattern):
        # The empty-RANGE case says so; a filter that matches nothing used to print one blank line,
        # which reads exactly like "the range is empty" and exactly like a crash.
        print(f"no tool call matches {'--tool ' + tool if tool else ''}"
              f"{' and ' if tool and pattern else ''}"
              f"{'--grep ' + repr(pattern) if pattern else ''}"
              f"{scope or ' in this transcript'}")
        return 0
    print(format_turns(picked, full=full, result_chars=result_chars,
                       results=results_by_tool_use_id(turns) if full else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
