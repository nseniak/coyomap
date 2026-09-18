"""Countable readability checks for the map's reader-facing prose.

The map's plain-language fields are read ONE BOX AT A TIME, out of any surrounding paragraph, by
someone who does not read code. Five properties of such a sentence can be COUNTED, which is why they
belong here rather than in the method prompt: how long it is, whether it leans on an em dash instead
of naming the link, whether it names CODE instead of the product, whether it opens with a pointer
word that has nothing to point at once the field is read alone, and whether it leans on a split it
never names ("in either kind" with no kind named anywhere in the box).

Everything fuzzy — is this jargon, is this a metaphor, is this sentence actually clear — stays in the
method prompt and in the audit. This module never judges meaning. It counts shapes, so a finding is
reproducible and is never an opinion, and a build can be handed the same rule twice and get the same
answer. Findings are ADVISORY: a map is not wrong for holding a 24-word sentence, it is just harder
to read than it needs to be.

Backticked spans are stripped before scanning, the same exemption a code block gets in prose: a field
that quotes a literal is quoting, not naming code in plain text.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from coyomap import records
from coyomap.model import ProjectModel
from coyomap.reporting import clip, shown

SENTENCE_WORD_LIMIT = 20   # one idea per sentence; longer is a split, not a style opinion
EXAMPLES_PER_KIND = 3      # how many offending fields a summary line names before it counts the rest

# The goal is the one field a reader meets as a TEXT rather than a box, and the method gives it a
# shape (method.md, "T0 Goal"): two to four short paragraphs, a blank line between them, one to
# three sentences each, under 180 words in all. Counted here for the reason sentence length is: a
# paragraph count is a shape, and a limit the tool never counts is a wish. The 2026-09-11 live maps
# were one paragraph of 108 to 167 words each, and 7 of their 22 sentences were over the limit —
# the goal was the one reader-facing field `iter_prose_fields` did not walk.
GOAL_PARAGRAPHS = (2, 4)        # fewest and most paragraphs
GOAL_PARAGRAPH_SENTENCES = 3    # most sentences in one paragraph
GOAL_WORD_LIMIT = 180           # most words in all, over every paragraph

# The goal DESCRIBES, it does not sell (method.md, "T0 Goal"): the need is welcome, a pitch is
# not. Most of that is a judgement and stays in the method prompt; this is the countable sliver —
# words that almost never belong in a plain description of what a product does. Deliberately short
# and whole-word, for the same reason `_CODE_PATTERNS` is narrow: a noisy check is one nobody
# leaves switched on.
# Only words with NO plain literal use: "leading" (to), "unique" (id), "trusted" (device), "unlock"
# (a lock, a game level) and bare "blazing" (a fire) were in the first list and tripped on honest
# descriptions, so they are out (review of 2026-09-11).
_PITCH_WORDS = ("seamless", "seamlessly", "effortless", "effortlessly", "frictionless",
                "hassle-free", "powerful", "robust", "simply", "easily", "instantly",
                "cutting-edge", "state-of-the-art", "best-in-class", "world-class",
                "industry-leading", "revolutionary", "game-changing", "blazing-fast", "blazingly",
                "lightning-fast", "delightful", "magical", "supercharge", "supercharges",
                "empower", "empowers")
_PITCH = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(w) for w in _PITCH_WORDS), re.IGNORECASE)
# The goal is written in the third person, naming people by role (method.md, "T0 Goal"): a
# second-person goal talks to a reader who may not be the user. "us" is left out on purpose — it
# is also a country.
_SECOND_PERSON = re.compile(r"\b(?:you|your|yours|we|our|ours)\b", re.IGNORECASE)
# THE MAP IS A SNAPSHOT (method/change-impact.md, "What an entry says"): a sentence in it describes
# the product as it is, as if it had always been so; the story of a change — what it was before,
# what it now does instead — is the log's. The words below narrate a change, so they are judged
# only where a change is being written: the new words an update log puts into the map. Map-wide
# they would mostly be false alarms (the product's own "right now", "a new server", "no longer in
# the settings"), which is why "new", "used to" and plain "before" are not here, and "right now" is
# let through.
_HISTORY = re.compile(r"(?<!right )\bnow\b|\bno longer\b|\bany ?more\b|\bpreviously\b|\bformerly\b"
                      r"|\buntil now\b|\bfrom now on\b|\bsince the\b|\bbefore,|^before\b|\bthe old\b",
                      re.IGNORECASE)

_BACKTICKED = re.compile(r"`[^`]*`")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t\r]*\n")   # a blank line (CRLF too); a single newline is a wrap
_EM_DASH = "—"

# A token that is CODE rather than product language. Deliberately narrow — a shape nobody writes by
# accident — because a noisy readability check is one nobody leaves switched on.
_CODE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("file path", re.compile(r"\b[\w./-]*\w\.(?:py|ts|tsx|js|jsx|go|rb|java|kt|rs|php|cs|sql|sh|"
                             r"yaml|yml|toml|ini|cfg|json)\b")),
    ("function call", re.compile(r"\b\w+\(\s*\)")),
    ("command flag", re.compile(r"(?<![\w-])--[a-z][\w-]*")),
    ("snake_case name", re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")),
)

# ONE MORE SHAPE, and only when the text being scanned is a NAME. A humped word — `GroupContact`,
# `createUserSchema` — is how a class is spelled, and a name is where a map picks one up: on the
# 2026-09-13 live maps 52 of 59, 50 of 53 and 96 of 100 record names were the class's own spelling
# while 0 of 126, 0 of 43 and 0 of 114 component names were. The same map's `meaning` sentence beside
# each was good plain language, so the writer knew what the thing was and named it after the class.
#
# NOT in `_CODE_PATTERNS`, so a SENTENCE is never scanned for it: prose legitimately writes
# PostgreSQL, NestJS and Day.js, and a readability counter that fires on a vendor's own spelling is
# the noisy check nobody leaves switched on.
#
# The hump must be followed by lower-case letters, which is what keeps an all-caps acronym out:
# `PostgreSQL`, `NestJS`, `RxJS`, `MongoDB`, `FastAPI`, `LocationIQ`, `AnyIO` and `PyJWT` do not
# match, and the six that do (`PyMongo`, `BeautifulSoup`, `WhatsApp`, `TanStack`, `GitHub`,
# `jsDelivr`) are all dependency names, which the caller exempts by construction.
_NAME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = _CODE_PATTERNS + (
    ("humped name", re.compile(r"\b[A-Za-z][a-z0-9]*(?:[A-Z][a-z0-9]+)+\b")),
)

# A field that opens with one of these reads as a fragment once it is shown alone in a box.
_BARE_POINTERS = ("It", "This", "That", "These", "Those", "They")
_OPENS_BARE = re.compile(r"^(%s)\b" % "|".join(_BARE_POINTERS))

# The checkable subset of writing rule 4 ("every reference resolves inside the same box") beyond the
# opening pointer: a determiner that announces ALTERNATIVES ("either", "both", "such", "the other")
# followed by a CATEGORY noun — a word naming the split instead of its sides ("in either kind") —
# plus the bare pair words "the latter" / "the former". Such a phrase is fine when the box names the
# sides; the sides being named is what `unresolved_references` checks for.
_CATEGORY_NOUNS = ("kind", "kinds", "mode", "modes", "way", "ways", "transport", "transports",
                   "form", "forms", "variant", "variants", "shape", "shapes")
_INDIRECT_REF = re.compile(
    r"\b(?:(?:either|both|such|the\s+other)\s+(?:%s)|the\s+latter|the\s+former)\b"
    % "|".join(_CATEGORY_NOUNS), re.IGNORECASE)
# "at least two concrete alternatives, named": approximated by an A-or-B / A-and-B join. Crude on
# purpose (see `sentences`) — a POS tagger would make two runs disagree.
_ENUM_JOIN = re.compile(r"\b(?:or|and)\b", re.IGNORECASE)
_TRAILING_OR = re.compile(r"\bor\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?]")
# A list item's marker, at the start of a line of a freeform note: a bullet or a number.
_LIST_ITEM = re.compile(r"^(?:[-*•]|\d+[.)])\s+")


def strip_literals(text: str) -> str:
    """Remove backticked spans. They are quotations of a literal, not plain-language prose."""
    return _BACKTICKED.sub(" ", text)


def sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation followed by whitespace. Crude on purpose: a smarter
    splitter would need an abbreviation list, and every entry in such a list is a judgement call
    this module exists to avoid."""
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def word_count(sentence: str) -> int:
    return len(sentence.split())


def paragraphs(text: str) -> list[str]:
    """Split on blank lines. The viewer draws the same split, so what this counts is what a reader
    sees as a paragraph."""
    return [p.strip() for p in _PARAGRAPH_SPLIT.split(text.strip()) if p.strip()]


def long_sentences(text: str, limit: int = SENTENCE_WORD_LIMIT) -> list[str]:
    return [s for s in sentences(strip_literals(text)) if word_count(s) > limit]


def em_dash_count(text: str) -> int:
    return strip_literals(text).count(_EM_DASH)


def code_tokens(text: str,
                patterns: tuple[tuple[str, re.Pattern[str]], ...] = _CODE_PATTERNS) -> list[str]:
    """Every code-shaped token in the field, deduplicated, longest form only.

    One token often matches two patterns — `cancel_order()` is both a call and a snake_case name —
    and reporting both reads as two problems where the writer has one word to fix.

    `patterns` is what a caller scanning something OTHER than a sentence swaps: `name_tokens` below
    passes the name table, which adds the humped word. One detector, two vocabularies — a second
    identifier detector is how two checks end up disagreeing about what code looks like."""
    scanned = strip_literals(text)
    found: list[str] = []
    for _label, pattern in patterns:
        for match in pattern.findall(scanned):
            if match not in found:
                found.append(match)
    return [t for t in found if not any(t != other and t in other for other in found)]


def name_tokens(name: str, known: Iterable[str] = ()) -> list[str]:
    """The code-shaped tokens in an element NAME — `code_tokens` with the name vocabulary, minus the
    words this map has already told us are a product's real name.

    `known` is the PRODUCT-NAME list the caller reads off the map (today the dependencies' own
    names, split into words): a component called "MongoDB stores" is naming a vendor's product, not
    a class, and the map is the thing that knows which words those are. A word is cleared only when
    it matches one of them exactly, so `MongoClient` is still a class name on a map that depends on
    MongoDB."""
    vendor = {w for w in known if w}
    return [t for t in code_tokens(name or "", _NAME_PATTERNS) if t not in vendor]


def opens_with_bare_pointer(text: str) -> str:
    """The pointer word a field opens with, or "" — a field starting "It reads the queue" is a
    fragment of a paragraph the reader will never see."""
    match = _OPENS_BARE.match(strip_literals(text).strip())
    return match.group(1) if match else ""


def unresolved_references(text: str, terms: Iterable[str] = ()) -> list[str]:
    """Referring expressions whose alternatives the box never names — "in either kind" where no
    sentence of the field says which kinds. Returns the offending phrases, in order.

    A phrase is let through when the box plausibly names the sides: an A-or-B / A-and-B join in an
    EARLIER SENTENCE of the field (rule 4 says a reference resolves to something named earlier —
    and the same sentence's own "and" is usually its clause structure, "Opens and holds …, in
    either transport", not an enumeration of the sides), two of the map's glossary terms anywhere
    before the reference, or an "or" later in the same sentence (the "either kind: remote or
    hosted" shape, where the enumeration trails the reference). All three outs are approximations;
    the finding stays an advisory because of exactly that."""
    scanned = strip_literals(text)
    lowered = scanned.lower()
    hits: list[str] = []
    for match in _INDIRECT_REF.finditer(scanned):
        prior = scanned[:match.start()]
        last_end = None
        for e in _SENTENCE_END.finditer(prior):
            last_end = e
        earlier_sentences = prior[:last_end.end()] if last_end else ""
        if _ENUM_JOIN.search(earlier_sentences):
            continue
        named = [t for t in terms if t and t.lower() in lowered[:match.start()]]
        if len(named) >= 2:
            continue
        rest = scanned[match.end():]
        end = _SENTENCE_END.search(rest)
        if _TRAILING_OR.search(rest[:end.start()] if end else rest):
            continue
        hits.append(re.sub(r"\s+", " ", match.group(0)))
    return hits


class Finding:
    """One readability observation about one field. `kind` groups findings for reporting so a map
    with 200 long sentences produces one counted line, never 200."""

    __slots__ = ("kind", "where", "detail")

    def __init__(self, kind: str, where: str, detail: str) -> None:
        self.kind = kind
        self.where = where
        self.detail = detail

    def __repr__(self) -> str:            # pragma: no cover - debugging aid
        return f"Finding({self.kind!r}, {self.where!r}, {self.detail!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Finding):
            return NotImplemented
        return (self.kind, self.where, self.detail) == (other.kind, other.where, other.detail)


def field_findings(where: str, text: str, limit: int = SENTENCE_WORD_LIMIT,
                   terms: Iterable[str] = ()) -> list[Finding]:
    """Every countable readability finding for one prose field. `where` names the field to a reader
    of the report ("C3 purpose"), never a code location. `terms` = the map's glossary terms, one of
    the ways an "either kind" phrase can count as resolved (see `unresolved_references`)."""
    body = (text or "").strip()
    if not body:
        return []
    found: list[Finding] = []
    for sentence in long_sentences(body, limit):
        found.append(Finding("long sentence", where,
                             f"{word_count(sentence)} words: \"{clip(sentence)}\""))
    dashes = em_dash_count(body)
    if dashes:
        found.append(Finding("em dash", where,
                             f"{dashes} em dash{'es' if dashes > 1 else ''}: \"{clip(body)}\""))
    tokens = code_tokens(body)
    if tokens:
        found.append(Finding("code name", where, f"names {shown(tokens, 3)}"))
    pointer = opens_with_bare_pointer(body)
    if pointer:
        found.append(Finding("bare pointer", where, f"opens with \"{pointer}\""))
    for phrase in unresolved_references(body, terms):
        found.append(Finding("unresolved reference", where, f"\"{phrase}\" in \"{clip(body)}\""))
    return found


def goal_shape_findings(goal: str) -> list[Finding]:
    """The goal's SHAPE, which no per-sentence check can see: how many paragraphs, how many
    sentences each, how many words in all. One finding kind, so the summary stays one line; each
    detail names the number that broke the rule. An empty goal is a completeness problem elsewhere,
    not a shape."""
    body = strip_literals(goal or "").strip()
    if not body:
        return []
    found: list[Finding] = []
    paras = paragraphs(body)
    low, high = GOAL_PARAGRAPHS
    one_block = len(paras) < low
    if one_block:
        found.append(Finding("goal shape", "goal",
                             f"one paragraph of {len(sentences(body))} sentences; the rule is {low} to "
                             f"{high} paragraphs"))
    elif len(paras) > high:
        found.append(Finding("goal shape", "goal",
                             f"{len(paras)} paragraphs; the rule is {low} to {high}"))
    # One block IS the finding; counting its sentences too would say it twice. The word cap still
    # runs: a 201-word block used to report only the block, and the length surfaced one run later.
    for n, para in enumerate(paras if not one_block else [], 1):
        count = len(sentences(para))
        if count > GOAL_PARAGRAPH_SENTENCES:
            found.append(Finding("goal shape", "goal",
                                 f"paragraph {n} has {count} sentences; the rule is 1 to "
                                 f"{GOAL_PARAGRAPH_SENTENCES}"))
    words = word_count(body)
    if words >= GOAL_WORD_LIMIT:   # "under 180", as the method says it
        found.append(Finding("goal shape", "goal",
                             f"{words} words in all; the rule is under {GOAL_WORD_LIMIT}"))
    return found


def pitch_words(text: str) -> list[str]:
    """The marketing words a text uses, in order, as written. Whole words only: "simplicity" is
    not "simply", and a backticked literal is a quotation."""
    return [m.group(0) for m in _PITCH.finditer(strip_literals(text))]


def goal_pitch_findings(goal: str) -> list[Finding]:
    """One finding when the goal reaches for the words of a pitch. The judgement half — a claim the
    map cannot back, a promise about outcomes — stays with the method prompt and the audit."""
    words = pitch_words(goal or "")
    if not words:
        return []
    return [Finding("pitch word", "goal", f"says {shown(words, 3)}")]


def second_person_words(text: str) -> list[str]:
    return [m.group(0) for m in _SECOND_PERSON.finditer(strip_literals(text))]


def history_words(text: str) -> list[str]:
    """The words a text uses to narrate a change, in order, as written. Whole words, outside
    backticks; "right now" is the product's own present and passes."""
    return [m.group(0) for m in _HISTORY.finditer(strip_literals(text))]


def history_findings(where: str, text: str) -> list[Finding]:
    """One finding when a sentence written INTO the map tells its history. Judged only on the words
    an update writes, never on the map as a whole (see `_HISTORY`)."""
    words = history_words(text or "")
    if not words:
        return []
    return [Finding("history word", where, f"says {shown(words, 3)}: \"{clip((text or '').strip())}\"")]


def goal_person_findings(goal: str) -> list[Finding]:
    """One finding when the goal talks to "you" or speaks as "we" instead of naming the roles."""
    words = second_person_words(goal or "")
    if not words:
        return []
    return [Finding("second person", "goal", f"says {shown(words, 3)}")]


def scan(fields: Iterable[tuple[str, str]], limit: int = SENTENCE_WORD_LIMIT,
         terms: Iterable[str] = ()) -> list[Finding]:
    """Run every field through `field_findings`, preserving order."""
    term_list = tuple(terms)
    out: list[Finding] = []
    for where, text in fields:
        out.extend(field_findings(where, text, limit, terms=term_list))
    return out


# The fix each finding kind asks for, in the reader's words. One place, so the report and the method
# never drift apart.
_REMEDY = {
    "long sentence": f"split it — one idea per sentence, at most {SENTENCE_WORD_LIMIT} words",
    "em dash": "replace it with the word that says the link: because, but, so, for example",
    "code name": "say what it does in product words; the code link already carries the path",
    "bare pointer": "name the thing — a box is read alone, with no paragraph before it",
    "unresolved reference": "name the alternatives in the same box — \"either kind\" must say "
                            "which kinds, with the names or the glossary words",
    # The counts in words, as the method says them; test_prose pins them to GOAL_PARAGRAPHS and
    # GOAL_PARAGRAPH_SENTENCES so the two cannot drift apart.
    "goal shape": f"two to four short paragraphs, a blank line between them, one to three "
                  f"sentences each, under {GOAL_WORD_LIMIT} words in all",
    "pitch word": "the goal describes, it does not sell — say what the product does and for whom, "
                  "in plain words, and drop the word",
    "second person": "third person, naming the people by role — the reader of the map is not "
                     "always the user",
    "history word": "the map is a snapshot — say what the product does as if it had always been so; "
                    "what it did before, and that it changed, is the log entry's sentence",
}


def summarize(findings: Iterable[Finding], examples: int = EXAMPLES_PER_KIND) -> list[str]:
    """One advisory line per finding kind: the count first, then a few examples.

    The count leads because a report that prints every offending field pushes the readable lines off
    the screen — the same failure the dropped-by-name note had before it was capped. Truncation goes
    through `reporting.shown` so whole-list mode and `--json` see the full set."""
    grouped: dict[str, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.kind, []).append(finding)
    lines: list[str] = []
    for kind in _REMEDY:
        hits = grouped.get(kind)
        if not hits:
            continue
        examples_text = shown([f"{f.where} ({f.detail})" for f in hits], examples, sep="; ",
                              unit="field(s)")
        article = "an" if kind[0] in "aeiou" else "a"
        lines.append(f"{len(hits)} prose field{'s' if len(hits) > 1 else ''} with {article} {kind} "
                     f"— {_REMEDY[kind]}. {examples_text}")
    return lines


def _note_blocks(body: str) -> list[str]:
    """A freeform note cut into the blocks a reader sees: a blank line ends one, a list item starts
    one, and a wrapped line continues the block above. Each block is one field, so a ten-item list
    with no full stops is ten short fields and not one 150-word "sentence" — the artifact the line
    walk removed from the registered headings, which the adversarial review found this path would
    have brought back — while a paragraph wrapped over three lines stays one paragraph."""
    blocks: list[list[str]] = []
    open_block = False
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            open_block = False
            continue
        item = _LIST_ITEM.match(line)
        if item or not open_block:
            blocks.append([line[item.end():] if item else line])
            open_block = True
        else:
            blocks[-1].append(line)
    return ["\n".join(block) for block in blocks]


def advisory_lines(model: ProjectModel) -> list[str]:
    """The readability report for one map, as the advisory lines `validate` and `lint-fragment`
    print: every prose field through `field_findings`, then the goal's shape. ONE function for both
    callers, so a check added here reaches the fragment lint and the assembled-map validation
    together — they used to build the same expression by hand, and a check added to one would have
    been missing from the other."""
    terms = [g.term for g in model.glossary]
    return summarize(scan(iter_prose_fields(model), terms=terms) + goal_shape_findings(model.goal)
                     + goal_pitch_findings(model.goal) + goal_person_findings(model.goal))


def iter_prose_fields(model: ProjectModel, *, wide: bool = True) -> Iterator[tuple[str, str]]:
    """Every reader-facing prose field in a map, as (where, text).

    Reader-facing means: a person reads this sentence in the viewer. Titles, ids, anchors, code
    links and closed-vocabulary cells are excluded — they are labels or machine values, and a word
    limit on a label is meaningless. So is the key of a recorded line: a section under a registered
    extras heading is walked one line at a time and only the line's why (`records.why_of`), because
    a `path:line` key is a file path by design and a template's `complete —` is not an em dash."""
    # The goal first: it is the one text a reader meets before any box, and until 2026-09-11 the one
    # reader-facing field this walk skipped (see GOAL_PARAGRAPHS). In the narrow surface too — one
    # field costs the fan-out nothing, and it is the anchor.
    yield "goal", model.goal
    for component in model.components:
        yield f"{component.id} purpose", component.purpose
    for group in (*model.capabilities, *model.subsystems, *model.subdomains, *model.blocks):
        yield f"{group.id} purpose", group.purpose
    # ONE ENTRY PER HALF, since the map holds two fields. The sentence checks were always per
    # sentence, so the words they see are unchanged; what the split adds is a second opening, so a
    # bare "It" or "This" at the head of an OUTCOME is now caught where it used to hide behind the
    # trigger in front of it.
    for uc in model.use_cases:
        yield f"{uc.id} trigger", uc.trigger
        yield f"{uc.id} outcome", uc.outcome
    for rule in model.rules:
        yield f"{rule.id} statement", rule.statement
        yield f"{rule.id} risk", rule.risk
    for dep in model.deps:
        yield f"{dep.id} used for", dep.used_for
    for role in model.roles:
        yield f"{role.id} wants", role.wants
    for step in model.happy_path:
        yield f"{step.id} why", step.why or ""
    for row in model.glossary:
        yield f"glossary '{row.term}'", row.meaning
    # Two more on the narrow surface since 2026-09-11, when a sweep of the schema against this walk
    # handed over seven string fields it never yielded. A stake is the label on an actor→feature arrow of
    # the Features page — the most-seen product sentence there is, and at most fifteen per live
    # map; the tests note is one field, the honesty line that leads the Tests tab. Together they
    # moved no live map's batch count (10, 9 and 13 batches at a cap of 40, before and after).
    for cap in model.capabilities:
        for stake in cap.stakes:
            yield f"{cap.id} stake for {stake.actor}", stake.stake
    yield "tests note", model.tests_note
    if not wide:
        # The BATCH surface stays narrow. Both consumers read this one function, and they do not
        # cost the same: the deterministic long-sentence gate is free, while every batch is
        # dispatched to a reading agent. Widening both took one real map from 13 prose batches to
        # 41 — a 3.2x fan-out cost increase, on by default, for a tier that was never budgeted.
        # `behaviour` was made opt-in for exactly that reason; this is the same decision.
        return
    # THE SIX ARRAYS THIS WALK WAS BLIND TO. Both consumers read this one function — the reading
    # fan-out and the deterministic long-sentence gate — so a field it does not yield is a field
    # NOTHING checks. On the 2026-08-29 mcpolis map that was 1,171 fields against the 477 it did
    # yield, and running the deterministic counters over the missing ones found 28 findings the gate
    # had never seen, 21 of them over-long sentences.
    #
    # Every one is a sentence a person reads in the viewer, which is the test this docstring states:
    # a step phrase IS the walk a reader follows, an entry point's trigger IS how the reader learns
    # what starts it, and an entity's meaning IS the record explained.
    for ep in model.entry_points:
        yield f"{ep.id} trigger", ep.trigger
    for entity in model.entities:
        yield f"{entity.id} meaning", entity.meaning
    for flow in model.flows:
        yield f"{flow.uc} flow title", flow.title
        for step in flow.steps:
            yield f"{flow.uc} step {step.n} phrase", step.phrase
            yield f"{flow.uc} step {step.n} note", step.note
    for sf in model.subflows:
        yield f"{sf.id} name", sf.name
        for step in sf.steps:
            yield f"{sf.id} step {step.n} phrase", step.phrase
            yield f"{sf.id} step {step.n} note", step.note
    for iface in model.interfaces:
        yield f"{iface.id} what", iface.what
    # THREE MORE FROM THE 2026-09-11 SCHEMA SWEEP, each drawn by the viewer as text a reader meets:
    # a test row's gap is the "Gap / risk" column of the Tests tab, a store note is the sentence
    # beside a record's storage on the Storage tab and in its info pane, and an extras section is a
    # card on the System tab — the notes about the code first, the map's own build record folded
    # below them. Wide only: the three live maps hold up to 54 gaps, 53 store notes and 57 recorded
    # lines each, which is a batch or two of fan-out apiece for drill-down text. Running the
    # counters over the seven candidate fields, whole, found 65 long sentences the gate had never
    # seen: 62 in the five walked here, 44 of those in the extras. Two string fields the sweep
    # turned up are NOT here because the viewer never draws them: a dependency's `alternative`
    # reaches only the committed markdown table, and its `not_an_interface` is read by `validate`
    # alone. THAT SWEEP WAS NOT THE WHOLE SCHEMA. Free text the viewer draws and this walk still
    # does not yield, found by the adversarial review of this change: an edge's `why`, a rule
    # site's `why`, an evidence item's `why`, a non-record type's `why`, a relation's `how`, a
    # role's `drives`. On 2026-09-12 Nitsan judged them not worth checking: the check is style
    # only, blind to everything but the sentence, and those fields are drill-down text. Do not
    # propose them again without a new reason.
    #
    # A section under a heading the registry knows is walked ONE RECORDED LINE AT A TIME, and only
    # the line's why: the record grammar owns the split, so a `path:line` key is never counted as a
    # code name and a template's own `complete —` never as an em dash — scanning whole bodies did
    # both on every live map. A section under an unknown heading is freeform notes and is walked
    # one BLOCK at a time (`_note_blocks`): a paragraph wrapped over several lines is read as
    # sentences, not as fragments, and a list is one field per item.
    for row in model.tests:
        # Named by its targets, and by its label when it has one: four rows on a live map assess the
        # same one component and differ only in their labels.
        targets = shown(row.targets, 3) or "no target"
        label = f" '{row.label.strip()}'" if row.label.strip() else ""
        yield f"tests row {targets}{label} gap", row.gap
    for entity in model.entities:
        if entity.store is not None:
            yield f"{entity.id} store notes", entity.store.notes
    for section in model.extras:
        if records.spec_of(section.heading) is None:
            for n, block in enumerate(_note_blocks(section.body), 1):
                yield f"note '{section.heading}' block {n}", block
            continue
        kind = "record" if records.is_maintenance(section.heading) else "note"
        for n, line in enumerate(records.body_lines(section.body), 1):
            yield f"{kind} '{section.heading}' line {n}", records.why_of(section.heading, line)


# ── the half a counter cannot judge ───────────────────────────────────────────────────────────────
#
# Rules 5 and 6 of the writing rules are judgements, not counts: does the reader know this word, and
# did a short sentence buy its shortness by dropping the specific. Nothing here calls a model. The
# tool emits BATCHES, a cheap fan-out reads them, and the lead folds what comes back into the audit
# report — the same division the grounding worklist uses, and for the same reason: a deterministic
# tool that quietly depended on a model would make two runs of `audit` disagree.

READ_PROMPT_VERSION = "v1"   # bump on any change to the RULES below; a batch records the version


def build_read_prompt() -> str:
    """What a reading agent is told. Deliberately narrow: it judges the two rules a counter cannot,
    and it is told NOT to repeat the four that are already counted, because a fan-out that re-reports
    long sentences would bury its own findings under the count the lead already has."""
    return (
        "You are reading the plain-language text of a codebase map. A reader meets each field ALONE, "
        "inside one box, with no paragraph around it, and does not read code.\n\n"
        "Judge ONLY these two things:\n"
        "  1. UNKNOWN WORD — a term the reader has not met and the field does not explain. Product "
        "words and words already in the map's Glossary are fine; jargon, an internal codename, or an "
        "unexplained abbreviation is not.\n"
        "  2. LOST PRECISION — the sentence is short and plain but says nothing specific. \"The "
        "system checks the user\" is the shape: grammatical, readable, and it names no decision, no "
        "data and no actor. This is the worse failure, because it looks correct.\n\n"
        "Do NOT report sentence length, em dashes, code names or an opening \"It\" — those are "
        "counted deterministically and the lead already has the numbers.\n"
        "Be conservative. Report a field only when you can say WHICH word is unknown, or WHAT the "
        "sentence should have said. If in doubt, pass the field.\n\n"
        "For each field you flag, return its `where` exactly as given, one of `unknown word` or "
        "`lost precision`, and one short line naming the word or the missing specific."
    )


def batch_fields(fields: Iterable[tuple[str, str]], cap: int) -> list[list[tuple[str, str]]]:
    """Split the non-empty prose fields into chunks of at most `cap`, in map order.

    Empty fields are dropped here rather than at the reader: a batch padded with blanks spends a
    fan-out's attention on nothing, and the count printed to the lead would not be the work done."""
    if cap < 1:
        raise ValueError("cap must be >= 1")
    live = [(where, text) for where, text in fields if text.strip()]
    return [live[i:i + cap] for i in range(0, len(live), cap)]
