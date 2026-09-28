#!/usr/bin/env python3
"""The ONE reader for recorded-exception lines, and the registry of the headings they live under.

Every advisory family in this tool lets an operator durably justify a finding by writing a
`<key>: <why>` line under a named extras heading. Before this module there were FOUR parsers for
that one line shape — one for the balance family, one for the audit family, one for coverage
directories, and one general id reader — each with its own regex and its own scar tissue. Three of
the four carry a comment describing a real incident where the regex mis-read a key and silently
over-suppressed (a truncated directory name silencing every sibling; a substring match adjudicating
a different finding; a greedy key swallowing ninety characters of prose). The parsers were separate
for no reason other than history, and each fix had to be re-derived four times.

So: ONE line reader here, and each family supplies the KEY VOCABULARY its own check honours. A key
pattern can never satisfy another family's lookup, which is the property the separate parsers were
protecting; sharing the LINE shape is what makes a fix land once.

MULTI-KEY. A record may name several keys for one reason:

    C101, C148, C186: an operator surface in our own back office, not a customer capability

One reason, three keys — instead of the same sentence written out three times, which is what the
live maps actually grew: one carried 66 recorded lines that hold 15 distinct reasons, the same
sentence up to seventeen times in a row. The keys are parsed as a comma-separated list where EVERY token must match the
family's key pattern; if any token does not, the line records NOTHING and is reported as malformed
rather than silently recording the subset it could read. A partially-read record is the dangerous
direction: the operator believes the finding is adjudicated while the check goes on firing.

Stdlib-only (the cli.py firewall).
"""
from __future__ import annotations

import re

from coyomap.model import ProjectModel

# ── the line reader ──────────────────────────────────────────────────────────────────────────────
#: What a recorded line may open with before its first key: a list bullet, bold markers.
_LEAD = r"^\s*(?:[-*]\s+)?\**\s*"

#: Separator between the key list and the why. The BARE hyphen is excluded and a SPACED one accepted,
#: because a hyphen is legal inside a key (`third-party/`, `CAP4/off-spine`) and a key pattern that
#: greedily consumes it must not then be cut short by it. `SEP_ID` adds the bare hyphen back for
#: id keys, whose pattern ends at a digit or a `/scope` word and so can never absorb a trailing one.
SEP = r"(?:\s*[:(—–]|\s+-\s)"
SEP_ID = r"(?:\s*[:(—–-]|\s+-\s)"

#: The element-id key vocabulary. `CAP` and `EP` lead the alternation for the usual first-match
#: reason (`CAP3` also starts with "C", `EP1` with "E") — without that, a recorded `CAP3: <why>` line
#: matched the `C` branch, failed on "AP3", and silently adjudicated nothing. A token MAY carry a
#: `/scope` suffix (`CAP4/spine`) when one id is the subject of two different checks.
ID_KEY = r"(?:CAP|EP|UC|HP|R|C|E|I)\d+(?:/[a-z-]+)?"

#: A repo-relative directory key, as the coverage family writes it: `mee6/plugins/: <why>`.
DIR_KEY = r"[\w./-]+"

#: What every token of a MULTI-key directory list must additionally look like. `DIR_KEY` alone
#: matches any bare word, and a list of them turns an ordinary sentence into an adjudication:
#: `Everything, tests/: walked - no exceptions` recorded `Everything` AND `tests`, silencing the
#: coverage warning for a real directory in a line that DENIES an exception. A single token keeps the
#: permissive form (the long-standing `docs - kept deliberately coarse` still records); the moment
#: there are several, each must carry a `/` or a `.` and so look like a path.
DIR_KEY_STRICT = r"[\w./-]*[./][\w./-]*"

#: Any element id, for a family that adjudicates findings across the WHOLE id vocabulary (the audit
#: families key on whatever id their finding's location names — `BR7`, `SF12`, `HP1`).
ANY_ID_KEY = r"[A-Z]+\d+"

#: The 'Naming exceptions' vocabulary: `ANY_ID_KEY` plus the `/scope` suffix every id-keyed family
#: uses when ONE id is the subject of two different checks. This heading adjudicates two questions
#: about one label — the leading article, and a name spelled like code — and with the bare id alone
#: the second had no key of its own: answering "yes, it really is called *The Gateway*" would also
#: have silenced "this name is a class name" on that element, which is the family escape the method
#: forbids. Its own constant rather than widening `ANY_ID_KEY`, for the reason `OWNER_KEY` states:
#: widening the shared one lets the audit family read a scope it honours no check for.
NAMING_KEY = ANY_ID_KEY + r"(?:/[a-z-]+)?"

# The 'Data owner exceptions' vocabulary: a data AREA (`SDn`) or the one saved record whose override
# is being adjudicated (`En`). Its own key rather than `ID_KEY`, which has no `SD` — widening the
# shared one would quietly let every other family adjudicate a sub-domain it has no check for.
OWNER_KEY = r"(?:SD|E)\d+"

#: The 'Decision area exceptions' vocabulary: a decision AREA (`BLKn`) and nothing else — `specified_under`
#: sits on no other element, so widening this to the shared `ID_KEY` would let the family adjudicate
#: ids it has no check for. Same reasoning as `OWNER_KEY` two lines up.
SPECIFIED_UNDER_KEY = r"BLK\d+"

#: The 'Balance exceptions' vocabulary: `ID_KEY` plus the three ids the granularity family actually
#: adjudicates. `UCn`/`HPn` come from `ID_KEY` (the flow-length band and the fused-goal name smell);
#: `SFn` is the single-reference sub-flow, `BLKn` the thin block, `BRn` the rule in no block. All
#: three were being read by the free-text `records_key` prefix test instead, which works on one key
#: per line and DROPS every key on a merged `SF3, SF9: <why>` line — the exact form
#: `recorded_line_warnings` tells the operator to write. So a record written on the tool's own
#: advice silently stopped adjudicating, with nothing saying so.
#: `BLK` precedes `BR` in the alternation for the usual first-match reason (`BLK1` also starts
#: "B"); its own key rather than widening `ID_KEY`, for the reason `OWNER_KEY` states.
BALANCE_KEY = r"(?:CAP|EP|UC|HP|BLK|BR|SF|R|C|E|I)\d+(?:/[a-z-]+)?"

#: The 'Interface exceptions' vocabulary: `ID_KEY` plus `SF`. The doors family adjudicates a
#: SUB-FLOW as well as a use case, because shared machinery can carry a step that names a pipe and
#: the edit goes on the sub-flow, under its own id. Its own key rather than widening `ID_KEY`, for
#: the reason stated one comment up: a shared key lets every other family adjudicate a sub-flow it
#: has no check for.
#: …plus the bare word `interfaces`, which is not an id at all. The "no interfaces authored" line
#: names it as its escape, and with an id-shaped key alone that escape was UNREACHABLE: the author
#: wrote the record, was told nothing, and the advisory fired forever.
IFACE_KEY = r"(?:CAP|EP|UC|HP|SF|R|C|E|I)\d+(?:/[a-z-]+)?|interfaces"

#: The lead-in of an Audit-exceptions record: the CHECK NAME, which scopes every id on the line.
AUDIT_LEAD = r"(?:[a-z][a-z-]+)\s+"


# ── the heading registry ─────────────────────────────────────────────────────────────────────────
class HeadingSpec:
    """One machine-read extras heading: where its sections render, and how its lines are keyed.

    `maintenance` marks a heading whose lines exist to ANSWER A CHECK — the map's own build record.
    The rest are notes about the CODE. The flag drives where a section renders (the System tab leads
    with notes and folds the build record away at the bottom); it changes nothing about what any
    check reads, so a heading can be reclassified without touching a single rule.

    `key` is the vocabulary a COMMA LIST may use under this heading, or None when the family has no
    list grammar at all (a free-text key, a quoted claim, a kind-plus-contract-word). That None is
    load-bearing: the repeated-reason advisory used to tell EVERY family to merge its records onto
    one line, and on the seven families that cannot read a bare list, following that instruction
    destroyed the record silently — the tool causing the exact failure this module exists to prevent.
    `scopes` is the CLOSED set of `/scope` words this heading's checks actually honour, when the
    heading declares one. A scoped key is how one id answers one of several checks sharing a heading
    (`UC4/doors`, `E2/embedded`) — but the pattern that reads it accepts any word, so `C1/article`
    parses into a perfectly valid key, silences nothing, and looks answered. Declaring the set is
    what lets `validate` say so by name. EMPTY MEANS UNCHECKED, and that is the safe default twice
    over: a family whose scopes are not yet enumerated keeps working exactly as before, and the two
    PATH-keyed headings must never be read this way at all — a `src/app/` key is a directory, not an
    id with a scope, and reading its slash as one would report every coverage record as inert.

    `lead` is what precedes the list (only the audit family has one: its check name).
    `value` is the VALUE WORD a family's template puts between the key and the why, as a regex
    alternation — `<kind>: complete — <how>` under "Entry-point coverage", `security-granularity:
    family — <why>` under "Balance exceptions". It is grammar, like the key: `why_of` drops it so the
    readability walk counts the writing and not the template.
    """

    def __init__(self, heading: str, maintenance: bool, key: str | None = None,
                 seps: str = SEP_ID, lead: str = "", strict_multi: str = "",
                 merged_form: str = "", value: str = "",
                 scopes: tuple[str, ...] = ()) -> None:
        self.heading = heading
        self.maintenance = maintenance
        self.key = key
        self.seps = seps
        self.lead = lead
        self.strict_multi = strict_multi
        self.merged_form = merged_form or "<id>, <id>, <id>: <why>"
        self.value = value
        self.scopes = scopes


HEADINGS: tuple[HeadingSpec, ...] = (
    # Ids ride an anywhere-in-body scan here, so a list reads; the three LITERAL escapes
    # (`granularity`, `cadence`, `store`) are line-leading words and never merge.
    HeadingSpec("Balance exceptions", True, BALANCE_KEY, value=r"family|endpoint-and-condition"),
    HeadingSpec("Audit exceptions", True, ANY_ID_KEY, r"(?:\s*[:—-])", lead=AUDIT_LEAD,
                merged_form="<check-name> <id>, <id>: <why>"),
    HeadingSpec("Drift exceptions", True),          # key = a whole quoted claim
    HeadingSpec("Accepted duplications", True),     # key = free text
    HeadingSpec("Unclaimed surfaces", True, ID_KEY),
    HeadingSpec("Happy Path coverage", True, ID_KEY),
    HeadingSpec("Audience exceptions", True, ID_KEY),
    HeadingSpec("Stake exceptions", True, ID_KEY),
    HeadingSpec("Persistence exceptions", True, ID_KEY),
    # A walk that leaves its person with nothing handed back. Keyed on the USE CASE, because
    # the answer is about that one story: either its way out is missing, or the surface
    # its person ends at was never written.
    HeadingSpec("Missing surfaces", True, ID_KEY),
    # A walk step that starts where no earlier step has been. Keyed on the USE CASE, like
    # "Missing surfaces": the answer is about that one story — the jump is a second thread it
    # opens on purpose, not a step nobody wrote. The advisory named this heading from the day
    # it was written and nothing registered it, so `record` refused the exact line the advisory
    # asked for and the finding shipped as carried with no escape.
    HeadingSpec("Walk jumps", True, ID_KEY),
    # NOT "Ownership exceptions": "Persistence exceptions" one line up already adjudicates
    # ownership in the OTHER sense (which COMPONENT writes an entity), on `En` keys too, so
    # two `En`-keyed headings would both have been called ownership and neither would have
    # said which question it answers. This one is about which FEATURE the data exists for.
    HeadingSpec("Data owner exceptions", True, OWNER_KEY),
    # The DECISION-AREA twin of the line above, and a separate heading on purpose: silencing "this
    # area governs nothing decided" answers a different question from "this data belongs to nobody",
    # and one heading for both would hide the second under the first. Keyed `BLKn` only — the family
    # adjudicates an AREA's answer, and nothing else carries `specified_under`.
    HeadingSpec("Decision area exceptions", True, SPECIFIED_UNDER_KEY),
    # Keyed by `ID_KEY`, which carries both shapes this family adjudicates: an `In` (this surface's
    # facing / evidence / reach is deliberately as it stands) and an `EPn` (this way in deliberately
    # belongs to no surface). One heading, because an operator deciding "that is fine" is making the
    # same kind of decision in both cases.
    HeadingSpec("Interface exceptions", True, IFACE_KEY),
    # The one heading whose scope vocabulary is enumerated, because it is the one with a scope that
    # an operator would plausibly invent: the bare `In` answers the leading article, so somebody
    # answering the OTHER question here reaches for `In/article` — which parses, silences nothing,
    # and reads as answered. The others are listed in `validate`'s follow-up, not guessed at here.
    HeadingSpec("Naming exceptions", True, NAMING_KEY, scopes=("code-name", "topic")),
    # A component that is only test code, kept as a component on purpose: `<Cn>: <why>`.
    HeadingSpec("Test code exceptions", True, ID_KEY),
    # A `pipe` that holds a rule site or a way in, kept a pipe on purpose: `<Cn>: <why>`.
    HeadingSpec("Kind exceptions", True, ID_KEY),
    # Keyed by a repo PATH, not an id — the thing being adjudicated is a file that used to hold an
    # access rule and no longer does. It had been pointed at "Audit exceptions", whose key
    # vocabulary is `[A-Z]+\d+`: a path can never be a key there, so twenty records written on one
    # live build were unreadable the moment they were saved, and nothing read them anyway.
    HeadingSpec("Access baseline exceptions", True, DIR_KEY, SEP, strict_multi=DIR_KEY_STRICT,
                merged_form="<path>, <path>: <why>"),
    HeadingSpec("Sweep debt", True),                # key = a `path:line` anchor (free text)
    # A step where a rule decides whose note deliberately says no condition: keyed by the step's
    # own `path:line`, like 'Sweep debt', because that anchor is what names one step of one walk.
    HeadingSpec("Condition exceptions", True),      # key = a `path:line` anchor (free text)
    # Notes: machine-read too, but what they SAY is about the code, not about the map's own checks.
    HeadingSpec("Entry-point coverage", False,      # key = a kind + a contract word
                value=r"complete|sampled|partial"),
    HeadingSpec("Coverage exceptions", False, DIR_KEY, SEP, strict_multi=DIR_KEY_STRICT,
                merged_form="<dir>/, <dir>/: <why>"),
    HeadingSpec("Bucket vocabulary", False),        # key = a bucket name (free text)
)

KNOWN_HEADINGS: tuple[str, ...] = tuple(h.heading for h in HEADINGS)

_BY_HEADING = {h.heading.lower(): h for h in HEADINGS}


def spec_of(heading: str) -> HeadingSpec | None:
    """The registry entry for a heading (case/space-tolerant, like every reader here)."""
    return _BY_HEADING.get(heading.strip().lower())


def is_maintenance(heading: str) -> bool:
    """Is this section the map's build record (rather than a note about the code)?

    An UNKNOWN heading is a note: a freeform section an author wrote by hand is exactly the content
    the notes half exists for, and defaulting the other way would hide it."""
    spec = spec_of(heading)
    return spec is not None and spec.maintenance


def _line_re(key: str, seps: str, lead: str = "") -> re.Pattern[str]:
    """A recorded line: lead-in, one or more keys, a separator, and a non-empty why.

    Each key may carry BOLD markers of its own (`- **C1**, **C2**: <why>`). The single-key bold form
    was always supported and is pinned by a test, so an author writes the bold list next — and it
    used to read as nothing, silently.

    The why is required (a non-space after the separator): a key alone is a dismissal, not a record —
    the rule every escape family already states, now enforced in the one place they share."""
    tok = r"\**(?:" + key + r")\**"
    return re.compile(_LEAD + lead + r"(?P<keys>" + tok + r"(?:\s*,\s*" + tok + r")*)" + seps
                      + r"\s*(?P<why>\S.*)")


#: A line that OPENS like a record — a lead-in and something that starts like this family's key —
#: but does not parse as one. Reported, never skipped: a silently-dropped exception is
#: indistinguishable from one that matched nothing, which is how three separate parser bugs hid.
def _attempt_re(key: str, lead: str = "") -> re.Pattern[str]:
    return re.compile(_LEAD + lead + r"\**(?:" + key + r")\**\s*[,:]")


def extras_bodies(m: ProjectModel, heading: str) -> list[str]:
    """The bodies of every extras section under a heading (case-insensitive, whitespace-tolerant) —
    the one heading matcher every escape family shares, so matching can never drift between them."""
    want = heading.strip().lower()
    return [x.body for x in m.extras if x.heading.strip().lower() == want]


def body_lines(body: str) -> list[str]:
    """The non-empty lines of one section body, stripped of list bullets — the line every reader
    here works on, and the unit the readability walk scans a section in."""
    return [ln.strip().lstrip("-*").strip() for ln in body.splitlines() if ln.strip()]


def lines(m: ProjectModel, heading: str) -> list[str]:
    """The non-empty recorded lines under a heading, stripped of list bullets."""
    return [ln for body in extras_bodies(m, heading) for ln in body_lines(body)]


#: A registered family with no key grammar still writes `<key>: <why>` — a bucket name, a
#: `path:line`, a whole quoted claim. Its why starts after the first colon that is followed by
#: whitespace, so a `path:line` key keeps its own colon. A quoted span that opens at a word start
#: is stepped over whole, in any of the three quote styles the drift reader accepts (see
#: `anchor_drift._DRIFT_RECORD`), because a quoted claim may hold a colon of its own; an apostrophe
#: inside a word opens nothing.
_QUOTED = r"(?<!\S)(?P<q>[`\"'])(?:(?!(?P=q)).)*(?P=q)"
_QUOTED_SPAN = re.compile(_QUOTED)
_GENERIC_WHY = re.compile(r"^(?P<key>(?:" + _QUOTED + r"|[^`:]|:(?!\s))+):\s+(?P<why>\S.*)$")
#: A free-text key is SHORT and carries no sentence. The longest on a live map is four words
#: ("Testing & type checking"); a prose line that merely holds a colon — "The operator sees two
#: things here: the queue depth and the last error" — is not a record, and splitting it there would
#: hide the words before the colon from the counters (the adversarial review's finding).
_GENERIC_KEY_WORDS = 5
_NOT_A_KEY = re.compile(r"[—–]|[.!?](?:\s|$)")
#: What may follow a family's value word: the template's dash (`complete — <how>`, or the spaced
#: hyphen the literal-escape reader also accepts), or the end of the line. Not a colon or a paren:
#: `C3: Family: the plan is billed once` and `partial (see below) is the honest word` open with a
#: real word, and a tail that took `:` or `(` ate it.
_VALUE_TAIL = r"(?:\s*[—–]|\s+-(?=\s)|\s*$)\s*"


def _looks_like_key(key: str) -> bool:
    """Would a writer following `<key>: <why>` have written this before the colon? Quoted spans count
    as one token, so a whole quoted claim is still a key."""
    bare = _QUOTED_SPAN.sub(" ", key)
    return not _NOT_A_KEY.search(bare) and len(bare.split()) <= _GENERIC_KEY_WORDS


def why_of(heading: str, line: str) -> str:
    """The PROSE of one recorded line: what follows its key — and, under a heading whose template
    puts a value word between the key and the why, what follows that word too.

    For the readability counters, which must count the writing and never the grammar: a `path:line`
    key is a file path by design, and the em dash after `complete` is the template's own separator,
    so scanning whole lines flagged every well-formed record on the live maps (22 template dashes
    and 20 path keys across three maps) — the noisy check nobody leaves switched on. A line under a
    heading the registry does not know is returned whole, bullets aside: that is a note somebody
    wrote by hand, with no key to strip. Under a known heading a line that is no record of its
    family still splits at a `key: ` shape when what stands before the colon looks like a key
    (`_looks_like_key`), and is otherwise returned whole — under-counting a key's few words is the
    cheap mistake, hiding a sentence is the dear one."""
    text = line.strip().lstrip("-*").strip()
    spec = spec_of(heading)
    if spec is None:
        return text
    why = ""
    if spec.key is not None:
        hit = _line_re(spec.key, spec.seps, spec.lead).match(text)
        if hit:
            why = hit.group("why")
    if not why:
        generic = _GENERIC_WHY.match(text)
        why = generic.group("why") if generic and _looks_like_key(generic.group("key")) else text
    if spec.value:
        why = re.sub(r"^(?:%s)%s" % (spec.value, _VALUE_TAIL), "", why, flags=re.IGNORECASE)
    return why.strip()


def keys_on_line(line: str, key: str = ID_KEY, seps: str = SEP_ID, lead: str = "",
                 strict_multi: str = "") -> list[str]:
    """The keys this line records, in written order — `[]` when it is not a record of this family.

    Every token in the leading comma list must match `key`; a list where one does not records
    nothing (see the module note on partial reads). When `strict_multi` is set, a list of SEVERAL
    tokens must additionally satisfy it — the directory family's guard against an ordinary sentence
    reading as an adjudication."""
    hit = _line_re(key, seps, lead).match(line)
    if not hit:
        return []
    keys = [tok.strip().strip("*").strip() for tok in hit.group("keys").split(",")]
    keys = [k for k in keys if k]
    if len(keys) > 1 and strict_multi:
        strict = re.compile(r"\A(?:" + strict_multi + r")\Z")
        if not all(strict.match(k) for k in keys):
            return []
    return keys


def _spec_args(heading: str, key: str | None, seps: str | None) -> tuple[str, str, str, str] | None:
    """`(key, seps, lead, strict_multi)` for a heading — the registry's grammar unless the caller
    overrides it. `None` when this family has no comma-list grammar at all."""
    spec = spec_of(heading)
    if key is not None:
        return key, (seps or SEP_ID), (spec.lead if spec else ""), (spec.strict_multi if spec else "")
    if spec is None or spec.key is None:
        return None
    return spec.key, spec.seps, spec.lead, spec.strict_multi


def malformed_records(m: ProjectModel, heading: str) -> list[str]:
    """Lines under `heading` that TRY to be a record of this family and adjudicate nothing.

    Two shapes, both silent before: a comma list holding a token that is not a key, and a key with
    no why (`C7:`), which every family calls a dismissal rather than a record. Reported, never
    skipped — a silently-dropped exception is indistinguishable from one that matched nothing, which
    is how three separate parser bugs in this codebase hid.

    Driven by the REGISTRY, so each family is tested with its own key vocabulary. Testing every
    heading with the id pattern (the first version here) both missed real malformed directory
    records and, worse, cleared an Audit-exceptions line that had lost its check name: `HP1, HP2:
    <why>` parses perfectly as an id list, records nothing at all through the audit reader, and was
    therefore reported as fine."""
    args = _spec_args(heading, None, None)
    if args is None:
        return []
    key, seps, lead, strict = args
    attempt = _attempt_re(key, lead)
    # A family whose list is PREFIXED (only the audit one, by its check name) has a second silent
    # shape: the list without the prefix. `HP1, HP2: <why>` parses perfectly as an id list, scopes
    # itself to no check, and adjudicates nothing — and an id-pattern test calls it well formed.
    orphan = _attempt_re(key) if lead else None
    out = []
    for ln in lines(m, heading):
        if keys_on_line(ln, key, seps, lead, strict):
            continue
        if attempt.match(ln) or (orphan is not None and orphan.match(ln)):
            out.append(ln)
    return out


def recorded_keys(m: ProjectModel, heading: str, key: str | None = None,
                  seps: str | None = None) -> set[str]:
    """Every key adjudicated under `heading`, read from line-leading tokens only.

    Deliberately stricter than an anywhere-in-body id scan: these bodies carry multi-paragraph prose
    that names OTHER keys mid-sentence — a key mentioned in an explanation, or a prose sentence
    merely STARTING with one and running on with no separator ("C9 handles this"), must not silently
    pre-exempt that element."""
    args = _spec_args(heading, key, seps)
    if args is None:
        return set()
    k, sp, lead, strict = args
    out: set[str] = set()
    for ln in lines(m, heading):
        out.update(keys_on_line(ln, k, sp, lead, strict))
    return out


def scope_of(key: str) -> str:
    """The `/scope` word of a recorded key, or "" when it carries none."""
    return key.partition("/")[2]


def inert_scoped_keys(m: ProjectModel, heading: str) -> list[str]:
    """Keys under `heading` whose `/scope` word no check there honours — recorded, well formed,
    and silencing nothing.

    Only for a heading that DECLARES its scope vocabulary; a heading that does not is left alone,
    because the failure this catches is cheap and the failure of guessing the set is not: one
    missing word would report a working record as dead, and an operator who deletes it on that
    advice loses a real adjudication."""
    spec = spec_of(heading)
    if spec is None or not spec.scopes:
        return []
    return sorted(k for k in recorded_keys(m, heading)
                  if (s := scope_of(k)) and s not in spec.scopes)


def records_key(recorded: list[str], key: str) -> bool:
    """Is `key` one of the keys of one of these recorded lines?

    For families whose key is FREE TEXT (a `path:line`, a bucket name, a URL-shaped auth surface),
    where no pattern can tell a key from its why. Prefix-and-colon, never a substring, and never
    `split(':')[0]`. A substring test let one adjudication silence a DIFFERENT finding (recording
    `Admin pages (/orgs/:slug/admin/**)` suppressed an un-adjudicated duplicate of `Admin pages`,
    the shorter being a substring of the longer line). Splitting on the first colon breaks the
    opposite way, on every key that CONTAINS one — and a URL-shaped auth surface usually does.

    SINGLE-KEY on purpose, unlike the id and directory families. Multi-key needs a pattern that can
    tell where one key ends and the next begins, and free text has none: a `path:line` key holds the
    very character the why is separated by, so `a.py:1, b.py:2: <why>` cannot be split without
    guessing. These families never grew the repetition multi-key exists to kill anyway — their keys
    are one-per-finding by nature — so the ambiguity would buy nothing and could only over-suppress."""
    k = key.strip()
    return any(ln.startswith(f"{k}:") for ln in recorded)
