#!/usr/bin/env python3
"""L3 corpus run — the scorecard against eight REAL build transcripts. OPT-IN, never a gate.

Run either way (needs an editable install: `make deps`):
    COYOMAP_L3_CORPUS=1 python3 eval/tests/test_process_corpus.py
    COYOMAP_L3_CORPUS=1 pytest eval/tests/test_process_corpus.py

**Why opt-in.** These transcripts live in `~/.claude/projects/`, outside the repo. They will not
exist on another machine or in CI, so the default suite never depends on them.
`test_process_scorecard.py` carries the deterministic logic tests that DO run everywhere.

**BUT OPT-IN IS NOT THE SAME AS ABSENT, and reading them as one made this a gate that could not
fail.** Every test asked one question — "can I run?" — and answered "no" the same way whether the
flag was unset or the files were gone. By 2026-09-13 all nine transcripts had evaporated from
`~/.claude/projects/`, and `COYOMAP_L3_CORPUS=1 pytest` printed nine dots and exited 0 while
measuring nothing at all. That silence covered a real detector repair: five assertions of the
reminderrepo build were being fixed and this file could not have noticed a regression in any of
them. The rule now encoded: **an opt-in check that was ASKED FOR and could not run is not a pass**
— with the flag set and a transcript missing, the tests FAIL and name the missing files.

One member of the corpus cannot evaporate: `eval/fixtures/transcript/build.jsonl` is committed, so
`test_the_committed_fixture_transcript_still_scores_the_same` runs everywhere, with no flag, in the
default suite. It is small, but it is the only part of this file that is not a promise.

**Why it exists anyway.** The detectors in `process_scorecard.py` were calibrated against these
eight files, and four separate false positives were found and fixed that way — a heredoc that
mentioned `coyomap anchor-drift` without running it, a `git add` that named `preindex.json` without
parsing it, a binary aliased to `$CX` that hid every invocation behind it, and a `reconcile.json`
produced by a generator script rather than a redirect. A synthetic test cannot find those, because
the author of the synthetic test is the author of the bug. What this file pins is that the numbers
those fixes produced do not silently change.

The corpus is 4 post-change builds (2026-07-29) and the 4 baseline builds of the same repos from
the night before. The comparison between them is the first real answer to 'did the method changes
land'.

**Still not a gate.** Even here, a moved number is a finding to look at, not a failure: these are
LLM builds and they vary. The assertions below pin only the facts that are structural — a value
that could not move without either the transcript or the detector changing.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from coyomap_eval.process_scorecard import Scorecard, diff, score_transcript

#: Set this to run the corpus. Absent, every corpus test skips; SET, a missing transcript FAILS.
ENV_FLAG = "COYOMAP_L3_CORPUS"

PROJECTS = Path.home() / ".claude" / "projects"

#: The one transcript that is COMMITTED, and so the only one that cannot evaporate. Shaped like a
#: real build: a `preindex --report`, a fragment write, a three-agent fan-out emitted as ONE
#: message, and two gate reads.
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "transcript" / "build.jsonl"


@dataclass(frozen=True)
class Build:
    """One transcript in the corpus."""

    #: WHICH RUN this transcript came from, not which side of a boundary it sits on. The field was
    #: called `era` and documented as holding one of two values — `"base"` (the night before the
    #: 2026-07 method changes) and `"post"` (after them). That framing was true while the corpus was
    #: a before/after pair and stopped being true the moment a third date landed: the 2026-08-02
    #: build is neither, it is simply later. A corpus that grows by one build per retrospective
    #: wants a run identifier, so dated values (`"0802"`) are the norm from here and the two
    #: original names are kept for what they are — the labels that pair of runs already carries.
    run: str
    repo: str
    relative: str

    @property
    def path(self) -> Path:
        return PROJECTS / self.relative

    @property
    def label(self) -> str:
        return f"{self.run}/{self.repo}"


CORPUS: tuple[Build, ...] = (
    Build("post", "coyomap", "-Users-nitsanseniak-Projects-coyomap/"
                             "36b1b143-b7a4-4a04-89f5-40a9bf932746.jsonl"),
    Build("post", "argus", "-Users-nitsanseniak-Projects-argus/"
                           "07a8f4e9-54b6-4afb-b6c8-48ec987d3770.jsonl"),
    Build("post", "mcpolis", "-Users-nitsanseniak-mee6-repos-mcpolis/"
                             "fbc095e4-9edf-4935-af33-86dac6a6efdd.jsonl"),
    Build("post", "mee6", "-Users-nitsanseniak-mee6-repos-mee6/"
                          "a2d36839-9b29-4f58-b756-f2c501539063.jsonl"),
    Build("base", "coyomap", "-Users-nitsanseniak-Projects-coyomap/"
                             "25ff248b-c035-4499-a4ae-ff67f3d91142.jsonl"),
    Build("base", "argus", "-Users-nitsanseniak-Projects-argus/"
                           "01331ac9-0678-485d-8469-111aa21ea049.jsonl"),
    Build("base", "mcpolis", "-Users-nitsanseniak-mee6-repos-mcpolis/"
                             "24905cb7-69ab-4af9-afd8-84625554dfe3.jsonl"),
    Build("base", "mee6", "-Users-nitsanseniak-mee6-repos-mee6/"
                          "23e4e486-86cb-44b5-984c-988f634fbbd3.jsonl"),
    # The 2026-08-02 mcpolis build, added because an adversarial review of that day's detector
    # repairs found three of them producing ZERO delta across the eight transcripts above: no build
    # in the original corpus invokes `coyomap grounding` at all (assertion 13 scores 0/0 on every
    # one), none redirects a gate to a file and reads it back with the Read tool (assertions 9 and
    # 23's new path), and none runs `audit --batches` or `fix dedup-edge --to-reconcile`. The rule
    # "measure a repaired detector against the corpus BOTH ways" was being satisfied vacuously.
    # This build exercises all four, and is the negative case for assertion 10 — 0 idle polls
    # against the 36 the other eight carry between them.
    Build("0802", "mcpolis", "-Users-nitsanseniak-mee6-repos-mcpolis/"
                             "e2f11ef1-2ef5-4117-bad1-61235a661a97.jsonl"),
)


# --- builders -------------------------------------------------------------------------

def corpus_was_asked_for() -> bool:
    """Did the caller ASK for the corpus run? A separate question from whether it can happen.

    PRESENCE, not truthiness. `bool(os.environ.get(...))` opened a second silent door: an unset
    shell variable expands to the empty string, so `COYOMAP_L3_CORPUS="$MAYBE" pytest` read as
    "nobody asked" and passed over an empty corpus, while `=0` read as "asked". Naming the variable
    at all is asking; to turn the corpus off, UNSET it, and the failure message says so."""
    return ENV_FLAG in os.environ


def missing_from_the_corpus() -> list[str]:
    """The labels of every corpus transcript that is not on this machine."""
    return [b.label for b in CORPUS if not b.path.is_file()]


def make_cards() -> dict[str, Scorecard]:
    """Every transcript scored, keyed by label. The one place the corpus is read."""
    return {b.label: score_transcript(b.path, label=b.label) for b in CORPUS}


def observed_of(cards: dict[str, Scorecard], label: str, aid: int) -> tuple[int, int]:
    a = cards[label].by_id()[aid]
    return a.observed, a.of


def run(cards: dict[str, Scorecard], name: str) -> list[Scorecard]:
    """Every scorecard from one RUN of the corpus, by its label prefix."""
    return [c for label, c in cards.items() if label.startswith(name + "/")]


def _require_corpus() -> None:
    """Let this corpus test run — or SKIP it, or FAIL it. It never returns quietly.

    Returning a bool was still wrong, and the fix for it is the same idea one level down. The old
    `_skip()` printed one line for two different facts; `_skip_or_fail()` separated them but the
    un-asked case still `return`ed, so pytest recorded a PASSING test. `pytest -rs` reported zero
    skips and the run said "11 passed" while nine of the eleven measured nothing — the same green
    dot over the same silence, one layer in.

    * flag unset — nobody asked. `pytest.skip`, so the run reports `s` and never a dot.
    * flag SET, transcripts gone — asked for and could not happen. A FAILURE that names the missing
      files, so the next reader re-pins `CORPUS` instead of re-discovering this."""
    if not corpus_was_asked_for():
        pytest.skip(f"the corpus was not asked for — set {ENV_FLAG}=1 to run it")
    missing = missing_from_the_corpus()
    if missing:
        raise AssertionError(
            f"{ENV_FLAG} is set, so the corpus run was ASKED FOR, and {len(missing)} of "
            f"{len(CORPUS)} transcript(s) are not on this machine:\n  "
            + "\n  ".join(missing)
            + f"\nThey live under {PROJECTS}, outside the repo, so they evaporate — all nine did. "
              f"Re-pin CORPUS to transcripts that exist, or UNSET {ENV_FLAG} (setting it to '' or "
              f"'0' still counts as asking). A check that was asked for and could not run must "
              f"never read as a pass.")


# --- the committed member: always on, no flag, no machine to depend on -----------------

#: What `build.jsonl` scores today, as `{assertion id: (observed, of)}`. Only assertions with a
#: real opportunity in it are listed; a `0/1` is as load-bearing as a `1/1`, because a detector
#: that starts crediting work this transcript never did is the same bug as one that stops crediting
#: work it did.
FIXTURE_SCORES: dict[int, tuple[int, int]] = {
    1: (1, 1),    # preindex --report used
    2: (1, 1),    # preindex.json never hand-parsed
    3: (1, 1),    # the three-agent fan-out is ONE message
    4: (0, 1),    # no shape-only anchor-drift run
    5: (0, 1),    # no Phase-4 skeptics
    6: (0, 1),    # no grounding record
    10: (1, 1),   # no idle turn at the barrier
    22: (0, 1),   # the fragment write follows the fan-out
    26: (2, 2),   # neither gate read as a bare count
    27: (1, 1),   # nothing hand-scripted the model
    29: (1, 1),   # no previous map read
    31: (1, 1),   # the brief cites the draft
    41: (1, 1),   # the lead was never compacted
}


def test_the_committed_fixture_transcript_still_scores_the_same():
    """The one corpus member that cannot evaporate — so the one that actually gates.

    Every other transcript here lives outside the repo and all nine of the originals are already
    gone. This one is committed, runs with no flag on any machine, and covers thirteen assertions in
    BOTH directions. It is small, so it cannot replace the real corpus; what it can do is stop this
    file from being nine green dots that measured nothing."""
    assert FIXTURE.is_file(), f"the committed fixture transcript is missing: {FIXTURE}"
    card = score_transcript(FIXTURE, label="fixture")
    assert card.grouping_consistent, "a message id carried two different usage blocks"
    scored = {a.id: (a.observed, a.of) for a in card.assertions if a.of}
    gained = {k: v for k, v in scored.items() if k not in FIXTURE_SCORES}
    lost = {k: v for k, v in FIXTURE_SCORES.items() if k not in scored}
    moved = {k: (FIXTURE_SCORES[k], v) for k, v in scored.items()
             if k in FIXTURE_SCORES and FIXTURE_SCORES[k] != v}
    assert scored == FIXTURE_SCORES, (
        f"the committed fixture's scorecard moved.\n  gained (id: now): {gained}\n"
        f"  lost (id: was): {lost}\n  moved (id: (was, now)): {moved}")


def test_a_corpus_that_was_asked_for_and_is_absent_never_reads_as_a_pass():
    """The gate on the gate.

    `_require_corpus` answers two questions, and every version that blurred them ended in a green
    dot over an empty corpus. All THREE outcomes are pinned here, by pointing `CORPUS` at a
    transcript that cannot exist — no branch depends on what this machine happens to hold.

    The empty-string case is its own row because it is how an unset shell variable expands:
    `COYOMAP_L3_CORPUS="$MAYBE" pytest` must fail, not pass."""
    global CORPUS
    kept, kept_flag = CORPUS, os.environ.get(ENV_FLAG)
    CORPUS = (Build("gone", "nowhere", "no-such-project/no-such-transcript.jsonl"),)
    try:
        os.environ.pop(ENV_FLAG, None)
        skipped = ""
        try:
            _require_corpus()
        except pytest.skip.Exception as e:
            skipped = str(e)
        assert "not asked for" in skipped, (
            f"un-asked must SKIP, so the run reports `s` and never a passing dot: {skipped!r}")
        for value in ("1", "", "0"):
            os.environ[ENV_FLAG] = value
            raised = ""
            try:
                _require_corpus()
            except AssertionError as e:
                raised = str(e)
            assert "gone/nowhere" in raised, (
                f"{ENV_FLAG}={value!r} names the variable, so the corpus was asked for and is "
                f"absent — it must fail loudly: {raised!r}")
            assert "asked for and could not run" in raised, raised
    finally:
        CORPUS = kept
        os.environ.pop(ENV_FLAG, None)
        if kept_flag is not None:
            os.environ[ENV_FLAG] = kept_flag


# --- the grouping assumption ----------------------------------------------------------

def test_every_transcript_groups_consistently():
    """The whole fan-out measurement rests on 'one message id == one API response'. Across all
    eight real transcripts no message id ever carried two different usage blocks. If this fails, a
    harness format change has invalidated assertion 3 and the number must not be trusted."""
    _require_corpus()
    for label, card in make_cards().items():
        assert card.grouping_consistent, f"{label}: a message id carried two different usage blocks"


# --- the five answers established from these exact files ------------------------------

def test_the_preindex_read_command_was_adopted_after_the_method_change():
    """Assertion 1. All four POST-change builds ran `preindex --report`; none of the four baselines
    did. This is the cleanest adoption signal in the corpus."""
    _require_corpus()
    cards = make_cards()
    for c in run(cards, "post"):
        assert c.by_id()[1].observed >= 1, f"{c.label}: no `preindex --report`"
    for c in run(cards, "base"):
        assert c.by_id()[1].observed == 0, f"{c.label}: baseline should predate the read command"


def test_hand_parsing_the_preindex_stopped_after_the_method_change():
    """Assertion 2. The baselines parsed `preindex.json` themselves — every single touch. The
    post-change builds did not hand-parse it once."""
    _require_corpus()
    cards = make_cards()
    for c in run(cards, "post"):
        a = c.by_id()[2]
        assert a.observed == a.of, f"{c.label}: {a.of - a.observed} hand-parse(s) remain"
    for c in run(cards, "base"):
        a = c.by_id()[2]
        assert a.of > 0 and a.observed == 0, f"{c.label}: baseline should be all hand-parses"


def test_the_reconcile_command_went_from_never_used_to_used():
    """Assertion 7 — the headline class-2 defect, and the one this corpus can now show being fixed.

    Seven of the original eight builds produced a `reconcile.json` and ZERO produced it with
    `coyomap reconcile`; every one wrote it by hand or generated it with a script. That held across
    ten builds and is why the "~30 assignments" escape was deleted from method.md.

    The `0802` build is the first to reach for the command — twice, at turns 147 and 149. This test
    now pins BOTH halves, because a regression in either direction is the interesting event: the
    historical builds must keep reading 0 (the reader still sees what it saw), and at least one
    build must be using it (the fix stays reached)."""
    _require_corpus()
    cards = make_cards()
    produced = used = 0
    for label, c in cards.items():
        a = c.by_id()[7]
        if label.startswith("0802/"):
            assert a.observed > 0, f"{label}: the command stopped being reached — regression"
        else:
            assert a.observed == 0, f"{label}: a historical build cannot have used it — reader bug"
        used += a.observed
        produced += a.of
    assert produced >= 7, f"only {produced} reconcile.json production(s) seen across the corpus"
    assert used >= 1, "no build in the corpus reaches `coyomap reconcile`"


def test_grounding_was_recorded_after_the_change_and_never_before():
    """Assertion 6. All four post-change builds recorded a `grounding` object; not one baseline
    did — including the baseline coyomap build, which had none at all."""
    _require_corpus()
    cards = make_cards()
    for c in run(cards, "post"):
        assert c.by_id()[6].observed >= 1, f"{c.label}: no grounding record"
    for c in run(cards, "base"):
        assert c.by_id()[6].observed == 0, f"{c.label}: baseline recorded grounding unexpectedly"


def test_the_shape_only_anchor_drift_pass_was_reached_by_three_of_four_post_builds():
    """Assertion 4. Three of the four post-change builds ran `anchor-drift` with no `--verdicts`;
    mee6 did not. No baseline ran it at all — every baseline invocation passed `--verdicts`.

    This is one of the two numbers where the brief's expectation and the transcripts disagree: the
    brief said one of four. Each of the three is a real invocation, verified command by command —
    `.venv/bin/coyomap anchor-drift --map .coyomap/project-map.json` with no verdicts flag."""
    _require_corpus()
    cards = make_cards()
    reached = [c.label for c in run(cards, "post") if c.by_id()[4].observed >= 1]
    assert len(reached) == 3, f"expected three post-change builds, got {reached}"
    assert all(c.by_id()[4].observed == 0 for c in run(cards, "base"))


def test_fan_outs_are_batched_in_seven_of_eight_builds():
    """Assertion 3 — THE HEADLINE, and the number that contradicts the brief outright.

    The expectation handed to this work was ZERO batched fan-outs across all eight transcripts:
    every fan-out one agent per turn. That is not what the files say. Seven of the eight builds
    contain at least one assistant message carrying two or more `Agent` calls; the eighth
    (base/coyomap) launched no agents at all, so it has no fan-out to batch.

    The prior measurement almost certainly counted JSONL RECORDS as turns. This harness writes one
    content block per record and stamps each with the time the tool EXECUTED, so a message that
    emitted ten `Agent` calls appears as ten records minutes apart with the results interleaved —
    which reads exactly like one agent per turn. What settles it: those records share one
    `message.id`, one `requestId` and one identical `usage` block, and there is exactly ONE
    `thinking` block among all ten. A model does not emit ten tool-calling responses of which nine
    contain no reasoning."""
    _require_corpus()
    cards = make_cards()
    batched = {label: c.by_id()[3].observed for label, c in cards.items()}
    assert batched["base/coyomap"] == 0 and cards["base/coyomap"].by_id()[3].of == 0, (
        "base/coyomap is the serial build — no agents at all, so assertion 3 is n/a, not 0")
    others = {k: v for k, v in batched.items() if k != "base/coyomap"}
    assert all(v >= 1 for v in others.values()), f"expected batching everywhere else: {others}"


# --- the diff, which is what the scorecard is for -------------------------------------

def test_the_post_change_era_did_not_regress_on_the_adoption_assertions():
    """The four assertions the method change was ABOUT — 1, 2, 4, 6 — all move up, per repo, with
    no regression. This is the diff mode doing the job it exists for."""
    _require_corpus()
    cards = make_cards()
    for repo in ("coyomap", "argus", "mcpolis", "mee6"):
        rows = {d.id: d for d in diff(cards[f"base/{repo}"], cards[f"post/{repo}"])}
        for aid in (1, 2, 6):
            assert rows[aid].direction in ("up", "flat", "new"), (
                f"{repo}: assertion {aid} moved {rows[aid].direction} "
                f"({rows[aid].before_counts} -> {rows[aid].after_counts})")


def test_the_corpus_prints_its_table():
    """Not an assertion — the corpus run's actual output. Kept as a test so `pytest -s` prints it
    and a reader gets the numbers without a separate script."""
    _require_corpus()
    cards = make_cards()
    header = f"{'build':<15}{'turns':>6}" + "".join(f"{'A' + str(i):>9}" for i in range(1, 11))
    print("\n" + header)
    print("-" * len(header))
    for b in CORPUS:
        c = cards[b.label]
        print(f"{b.label:<15}{c.turns:>6}"
              + "".join(f"{str(a.observed) + '/' + str(a.of):>9}" for a in c.assertions))


def _main() -> int:
    """Script mode. It counts SKIPS separately, for the reason the whole file is about: a run that
    measured nothing must not print the same line as a run that measured everything."""
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = skipped = 0
    for fn in fns:
        try:
            fn()
        except pytest.skip.Exception as exc:
            skipped += 1
            print(f"SKIP {fn.__name__}  {exc}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}\n  {str(exc)[:500]}\n")
    print(f"{len(fns) - failed - skipped} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
