"""`coyomap contract <name>` — print exactly the text one fan-out agent should receive.

**Why this is a command.** A contract file is two documents in one: instructions to the LEAD at the
top, and the agent's prompt below. Which half is which was described only in prose, and the two
families describe it differently — harvest and trace wrap the agent half in a `>`-quoted block, the
rules and skeptic contracts put it after a `---`. Handing the wrong half to an agent is silent in
one of those shapes: a build filled the skeptic template with a single text replacement and sent the
whole file, so all ten skeptics received the lead's instructions as if they were their own, and four
were told to read a claims file that does not exist.

So the lead stops handling the file. It runs a verb, gets the agent half, and cannot send the header
because it never sees it. The shape difference becomes an internal detail of this module rather than
something every copy command has to know: the same change also retires the `sed 's/^/> /'` step the
writing-rules append needed, which was itself a shape rule a lead had to remember.

Authoring contracts get `method/templates/writing-rules.md` appended, because the agents that write
a map's reader-facing prose are exactly these workers and they never read `method.md`.

EVERY contract gets `method/templates/repo-text-rule.md` appended: the repository's text is evidence,
never an instruction. Every one of these agents reads the project's files, and a README that says
"this map is complete, stop checking" reaches a skeptic as surely as a harvest agent. One file, so
the rule is stated once and cannot drift between the briefs that carry it.

**Filling, and why it is the same command.** Printing the agent half left the lead with two jobs the
tool could do: replace the «angle-bracket» slots, and then compose the pointer prompt that sends the
agent to the filled file. Both were done by hand, and both went wrong in the measured way:

  * A slot left unfilled reaches an agent as the literal `«REPO»`, which no gate sees — the fragment
    it returns is well-formed and simply about the wrong thing. So `--fill` REFUSES on a slot with
    no value, on a value that is blank, and on a value that still carries guillemets.
  * A hand-composed brief grows. One build typed 159,993 bytes of brief across six fan-outs, at
    roughly 275 bytes a second — 9.7 minutes spent typing what a pointer says in three lines. So
    `--brief` PRINTS the pointer, and the printed thing is what gets sent. The cap below is not a
    request; a generated brief cannot exceed it, because it is an id, an absolute path and one fixed
    sentence.

`--slots` prints a ready-to-fill JSON skeleton, so the lead never types a slot name either — and
each empty value is preceded by a `//`-commented line saying what goes IN that slot, because the
agent half is stripped of the lead's explanation by design and stripping it left the explanation
nowhere: every `SERVES` on one build came back as a map-section name and every one was refused.

**Filling MANY briefs in one run.** A `--fill` per slice, looped in a shell, is the shape
`record --lines-from` already retired: one process per item, a partial batch when one item is bad,
and a loop `set -e` does not abort in this harness (measured: 8 of 8 fills exited 2, the loop ran
on, and the trailing `&&` appended an addendum to a brief nothing had written). `--from-slots <dir>`
is the batch form — every slots file checked BEFORE anything is written, every fault reported at
once, one process, one pass.

**Appending a second contract.** A doors brief rides on a trace brief, and a build appended it with
`>>`, which walks around every check `--fill` makes: 9 of 10 trace briefs reached their agent still
carrying `«FLOWS»`, `«MAP»`, `«REPO»` and six more literal slot names. `--append <name>` composes
the two halves in ONE fill, over the UNION of both contracts' slots, so a missing doors slot refuses
the whole brief instead of shipping an unfilled one.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from coyomap.anchor_drift import load_verdicts
from coyomap.audit_model import RULE_SITE_CLAIM, resolve_claim
from coyomap.dump import edges_of, record_of, resolve_id
from coyomap.model import ModelError, ProjectModel, load_model, resolve_map_path
from coyomap.provenance import SESSION_ENV

# Contract name → template file. The name is what a lead types, so it is the phase, not the filename.
CONTRACTS: dict[str, str] = {
    "harvest": "harvest-contract.md",
    "trace": "trace-contract.md",
    "rules": "rules-contract.md",
    "skeptic": "skeptic-contract.md",
    # The fifth slice every build has, and the one no template covered. Hand-composed briefs lose
    # the shared machinery: the gap-fill brief was the ONE trace-phase contract of eleven missing
    # "do NOT spawn sub-agents", and it lost four more blocks with it.
    "gapfill": "gapfill-contract.md",
    # The T2b doors retrofit. The rule is ~9 KB of method.md and every build before this template
    # hand-paraphrased it: the 2026-09-01 argus brief was 9,031 bytes of hand-composed text with no
    # gate on the paraphrase, and it dropped the scheduled-work-is-not-an-actor rule outright.
    "doors": "doors-contract.md",
    # The Phase-4 closer. Its brief was hand-composed, and on the 2026-09-01 argus build it handed
    # the closer the repo, forbade it `.coyomap/`, and then asked a question only the map answers.
    # The contract's whole job is to say that the LEAD must paste the `dump --id` / `dump --edges`
    # rows into the brief — the one thing no tool can do, because the lead composes the brief.
    "closer": "closer-contract.md",
    # Appended to ONE harvest brief only — the T5 owner's. The entity-card spec used to sit in the
    # shared harvest contract, where 13 of ~14 agents read a detailed job they were forbidden to do.
    "harvest-t5": "t5-addendum.md",
    # The test-completeness slice: every build has it, no template covered it, and the hand-written
    # brief lost the no-delegation block once (2026-08-20) and was the batch straggler once
    # (2026-09-08, written and dispatched last).
    "tests": "tests-contract.md",
    # The Architecture picture's merged texts: one sentence per line several stories take. Written
    # by one agent at the end of a build or an update, then read by a FRESH one, because a merged
    # text has no code line for a skeptic to check it against, only the sentences it restates.
    "line-texts": "line-texts-contract.md",
    "line-texts-check": "line-texts-check-contract.md",
}

# Which contracts author reader-facing prose, and therefore carry the writing rules. A skeptic
# judges claims and a trace agent writes flow steps; neither authors a sentence a reader meets in a
# box, and a rule an agent cannot act on is prompt weight every one of them pays for.
AUTHORING: frozenset[str] = frozenset({"harvest", "rules", "tests"})   # a gap row is read in the viewer

WRITING_RULES = "writing-rules.md"
REPO_TEXT_RULE = "repo-text-rule.md"   # appended to EVERY brief (see the module docstring)
_TEMPLATES = "method/templates"
_DIVIDER = "---"


def home() -> Path:
    """Where the method and its templates live. `COYOMAP_HOME` wins, because that is the name every
    command in the method already uses; otherwise the installed package's own clone."""
    env = os.environ.get("COYOMAP_HOME", "").strip()
    return Path(env).expanduser().resolve() if env else Path(__file__).resolve().parent.parent.parent


def agent_half(text: str) -> str:
    """The half an agent receives, whichever shape the template uses.

    A `>`-quoted template yields its quoted block with the marker stripped. A plain template yields
    everything after its single `---`. Both are detected from the text, never from the filename, so
    a template that changes shape keeps working and a template with NEITHER boundary raises rather
    than silently handing over a lead's instructions."""
    lines = text.splitlines()
    quoted = [i for i, line in enumerate(lines) if line.startswith(">")]
    if quoted:
        block = lines[quoted[0]: quoted[-1] + 1]
        return "\n".join(_unquote(line) for line in block).strip("\n")
    dividers = [i for i, line in enumerate(lines) if line.strip() == _DIVIDER]
    if len(dividers) == 1:
        return "\n".join(lines[dividers[0] + 1:]).strip("\n")
    if not dividers:
        raise ValueError("no agent boundary: the template has neither a `>`-quoted block nor a "
                         "`---` divider, so there is no way to tell the lead's half from the "
                         "agent's")
    raise ValueError(f"ambiguous agent boundary: {len(dividers)} `---` dividers, so the agent half "
                     f"is not defined; a plain template must have exactly one")


def lead_half(text: str) -> str:
    """The half the LEAD reads — everything above the agent boundary, in either shape.

    The exact complement of `agent_half`, and it exists for one reason: the lead-facing lines are
    where a template says what goes IN each slot, and `contract <name>` strips them by design. That
    design is right (a build once sent the lead's own instructions to ten skeptics) and it left the
    slot explanations reachable by nobody — so `--slots` reads them from here and prints them beside
    the empty values, while the agent half stays exactly as strict as it was."""
    lines = text.splitlines()
    quoted = [i for i, line in enumerate(lines) if line.startswith(">")]
    if quoted:
        return "\n".join(lines[: quoted[0]]).strip("\n")
    dividers = [i for i, line in enumerate(lines) if line.strip() == _DIVIDER]
    if len(dividers) == 1:
        return "\n".join(lines[: dividers[0]]).strip("\n")
    return ""


def _unquote(line: str) -> str:
    """Strip one `> ` marker. A blank quoted line is `>` with nothing after it."""
    if line.startswith("> "):
        return line[2:]
    return line[1:] if line.startswith(">") else line


def render(name: str, root: Path | None = None) -> str:
    """The full text to hand one agent: the contract's agent half, plus the writing rules when this
    contract's agents author prose a reader meets."""
    if name not in CONTRACTS:
        raise KeyError(name)
    base = (root or home()) / _TEMPLATES
    body = agent_half((base / CONTRACTS[name]).read_text(encoding="utf-8"))
    body += "\n\n" + (base / REPO_TEXT_RULE).read_text(encoding="utf-8").strip("\n")
    if name not in AUTHORING:
        return body + "\n"
    rules = (base / WRITING_RULES).read_text(encoding="utf-8").strip("\n")
    return f"{body}\n\n{rules}\n"


#: A slot in the agent half: the text between the guillemets is the key `--fill` looks up.
SLOT = re.compile(r"«([^«»]+)»")

#: The pointer brief's ceiling, in bytes. It is a CEILING and not a target: the generated brief is
#: an id, an absolute path and one fixed sentence, so it lands near 150 bytes on any real path and
#: this only fires on a path long enough to be a mistake. The number exists so the method can name
#: one, after a build typed 159,993 bytes of brief across six fan-outs.
BRIEF_MAX_BYTES = 400

#: The one sentence a pointer brief carries. Fixed text, so no build re-words it into a paragraph.
BRIEF_SENTENCE = "Read it COMPLETELY and follow it — it is your entire brief."


def slots(name: str, root: Path | None = None) -> list[str]:
    """Every slot in the text an agent actually receives, in the order it first appears.

    Read from the AGENT half, never from the template file: the lead's own instructions above the
    divider talk *about* «angle-bracket» slots, and a skeleton listing those would ask the lead to
    fill words that reach nobody.

    A KEY MAY NOT CONTAIN WHITESPACE. A slot whose key is a whole sentence
    (`«absolute paths this agent owns; list a directory first, then read each file»`) is unusable as
    a key: nobody types it, so the skeleton gets filled BY POSITION instead — and a positional fill
    is silent when it is wrong. Measured on the 2026-09-01 argus build: all four brief generators
    bound their slots positionally, across 51 of 55 briefs. `trace` already used bare tokens; this
    refusal is what stops the other templates drifting back."""
    seen: dict[str, None] = {}
    prose_keys: list[str] = []
    for key in SLOT.findall(render(name, root)):
        key = key.strip()
        if re.search(r"\s", key):
            prose_keys.append(key)
        seen.setdefault(key, None)
    if prose_keys:
        listed = "; ".join(f"«{k[:60]}»" for k in dict.fromkeys(prose_keys))
        raise ValueError(
            f"{CONTRACTS[name]} has {len(dict.fromkeys(prose_keys))} slot(s) whose key is prose, "
            f"not a name: {listed}. A key nobody can type is filled by POSITION instead, which is "
            f"silent when it is wrong. Rename each to a bare token (SLICE_KIND, FILES, "
            f"BACKGROUND …) and move the explanation OUTSIDE the guillemets.")
    return list(seen)


#: A lead-facing line that says what ONE slot holds: `- **«KEY»** — <what goes in it>`, the shape
#: four of the shipped templates already use. `is` and `:` are accepted because two of them write it
#: that way, and a template is the source of truth over the table below.
_SPEC_BULLET = re.compile(r"^\s*[-*]\s+\*\*«([^«»]+)»\*\*\s*(?:—|--|-|is\b|:)\s*(.*)$")

#: One line saying what a slot is FOR, keyed by slot name — or by `<contract>.<KEY>` when one word
#: means two things (`CLAIMS` is a bare batch id to a skeptic and a pasted block of rows to a
#: closer). A template's own bullet ALWAYS wins over an entry here; this table holds the slots whose
#: meaning is identical in every contract that has them, plus the two whose template belongs to a
#: different batch than this file.
#:
#: Why the table exists at all: `coyomap contract harvest` prints the agent half and strips the
#: lead's, by design — so the only place saying that «SERVES» must name `Rn`/`UCn`/`CAPn`/`HPn` ids
#: was a file the lead never opened. All 8 SERVES came back as map-section names and all 8 were
#: refused at the barrier, on a build whose own tool text says this had already happened to 14
#: briefs on an earlier one.
SLOT_SPECS: dict[str, str] = {
    "COYOMAP_HOME": "absolute path of the coyomap clone; the agent runs "
                    "`<COYOMAP_HOME>/.venv/bin/coyomap` and never cd's into it",
    "REPO": "absolute path of the repo being mapped",
    "REPO_ABS": "absolute path of the repo being mapped — the root anchors are written RELATIVE to "
                "(same value as «repo»)",
    "repo": "absolute path of the repo being mapped (same value as «REPO_ABS»)",
    "MAP": "absolute path of the assembled map this agent reads, usually "
           "`<REPO>/.coyomap/project-map.json`",
    "AGENT_ID": "this agent's id, one word, unique across the WHOLE build — it names the fragment "
                "and every scratch file",
    "agent-id": "this agent's id, one word, unique across the WHOLE build — it names the fragment "
                "and every scratch file",
    "your-fragment": "absolute path of the fragment this agent writes, WITHOUT the `.json` suffix "
                     "(the contract adds it)",
    "N": "the component budget for this slice as a bare number — `lint-fragment --expect «N»` "
         "reads it (same number as «EXPECTED_COMPONENTS»)",
    # Skeptic-only, and in code rather than in `skeptic-contract.md`, because that template belongs
    # to another batch. `_slot_content_faults` already refuses a path in either, so the words here
    # and the refusal there must say the same thing.
    "skeptic.BATCH": "this skeptic's OWN id — a bare id, never a path; the contract composes "
                     "`verdicts-«BATCH».json` from it",
    "skeptic.CLAIMS": "the id of the claims file this skeptic reads — a bare id, never a path; the "
                      "contract composes `claims-«CLAIMS».json` from it",
}

def template_specs(name: str, root: Path | None = None) -> dict[str, str]:
    """Every `- **«KEY»** — …` line a template's LEAD half carries, as one line each.

    Continuation lines are joined and the result is cut at the first sentence, because the skeleton
    prints one line per slot and a three-line paragraph there is the lead's half smuggled back in
    through a different door."""
    if name not in CONTRACTS:
        raise KeyError(name)
    base = (root or home()) / _TEMPLATES
    lines = lead_half((base / CONTRACTS[name]).read_text(encoding="utf-8")).splitlines()
    out: dict[str, str] = {}
    for i, line in enumerate(lines):
        hit = _SPEC_BULLET.match(line)
        if not hit:
            continue
        parts = [hit.group(2).strip()]
        for nxt in lines[i + 1:]:
            if not nxt.strip() or _SPEC_BULLET.match(nxt) or not nxt.startswith((" ", "\t")):
                break
            parts.append(nxt.strip())
        out[hit.group(1).strip()] = _one_line(" ".join(p for p in parts if p))
    return out


#: The end of the first sentence: a full stop followed by a space. `granularity.per_dir` and
#: `path.py:10` have no space after the dot, so they survive the cut.
_SENTENCE_END = re.compile(r"(?<=\.)\s")


def _one_line(text: str) -> str:
    text = " ".join(text.split())
    head = _SENTENCE_END.split(text, 1)[0].strip()
    return head if head else text


def slot_specs(name: str, root: Path | None = None) -> dict[str, str]:
    """What goes in each slot of one contract, in the order `--slots` prints them.

    Template bullet wins, then `<contract>.<KEY>`, then the bare key. A slot with NO spec anywhere
    is a REFUSAL naming it, with no exemption: a blank explanation beside an empty value is what the
    lead already had, and it is what sent 8 briefs back. The refusal also catches a FALSE slot — text
    that only looks like one — which is how `«key» parent_id`, the label a keyed relation draws on
    its arrow, was found sitting in the T5 addendum asking to be filled."""
    keys = slots(name, root)
    authored = template_specs(name, root)
    out: dict[str, str] = {}
    missing: list[str] = []
    for key in keys:
        spec = (authored.get(key) or SLOT_SPECS.get(f"{name}.{key}") or SLOT_SPECS.get(key) or "")
        if not spec:
            missing.append(key)
            continue
        out[key] = spec
    if missing:
        raise ValueError(
            f"{', '.join(missing)} — slot(s) of the {name} contract with no one-line spec, so the "
            f"skeleton would print an empty value with no word about what goes in it. Add a "
            f"`- **«KEY»** — <one line>` bullet to the LEAD half of {CONTRACTS[name]}, or an entry "
            f"to contract.SLOT_SPECS when the slot means the same thing in every contract — or, if "
            f"it is not really a slot, stop writing it in guillemets there.")
    return out


def skeleton(names: list[str], root: Path | None = None) -> dict[str, str]:
    """The ready-to-fill JSON object `--slots` prints: each slot's spec on a `//` line, then the
    slot itself with an empty value.

    The spec rides INSIDE the JSON rather than on stderr because the lead redirects this to a file
    and fills it there — an explanation printed to the terminal is scrolled past by the time the
    typing happens. `--fill` ignores every `//` key, so the file the lead edits is the file it
    reads back."""
    out: dict[str, str] = {}
    for name in names:
        for key, spec in slot_specs(name, root).items():
            out.setdefault(f"//{key}", spec)
            out.setdefault(key, "")
    return out


#: A behavioural id — the layer a structural slice exists to SERVE. `Rn` (role), `UCn` (use case),
#: `CAPn` (feature), `HPn` (happy-path step).
_BEHAVIOURAL_ID = re.compile(r"\b(?:CAP\d+|UC\d+|HP\d+|R\d+)\b")

def _slot_content_faults(name: str, values: dict[str, str]) -> list[str]:
    """Faults in what a slot was filled WITH, as opposed to whether it was filled.

    Measured on the 2026-09-02 build, and invisible to every other check because a filled slot is a
    filled slot:

    * **`SERVES` naming no behavioural id.** The whole point of that slot is that a structural slice
      is cut to serve the behavioural layer, and `method.md` says a brief naming no use case is a
      brief cut from the file tree. All 14 harvest briefs filled it with a MAP-SECTION NAME
      ("T5 domain model"), which reads like an answer and is not one. Assertion 31 went 1.00 → 0.00
      and the harvest came back with components carrying no backbone edge.

    (A second shape — a component budget on a slice that authors none — was tried and reverted; see
    the comment at the end of this function.)"""
    faults: list[str] = []
    serves = (values.get("SERVES") or "").strip()
    if serves and not _BEHAVIOURAL_ID.search(serves):
        faults.append(
            f"«SERVES» names no behavioural id: {serves[:80]!r}. It must list the `Rn` / `UCn` / "
            f"`CAPn` / `HPn` ids whose behavior runs through this slice's files — that is what "
            f"makes the slice cut to the behavioural layer instead of to the file tree. A "
            f"map-section name ('T5 domain model') reads like an answer and is not one: all 14 "
            f"briefs on one build filled it that way, and the harvest came back with components "
            f"carrying no backbone edge at all")
    # A batch id filled with a PATH. The skeptic contract composes `.coyomap/verify/claims-«CLAIMS».json`
    # and `verdicts-«BATCH».json` from these two, so a path here builds a file name that exists
    # nowhere — 38 of 38 briefs on one build named `claims-/Users/…/claims-backbone-1.json.json`.
    # SKEPTIC ONLY: the closer contract has its own «CLAIMS», a pasted block of claims and `dump`
    # output that carries `path:line`, and the first version of this check refused every closer fill.
    for key in ("BATCH", "CLAIMS") if name == "skeptic" else ():
        v = (values.get(key) or "").strip()
        if v and ("/" in v or v.lower().endswith(".json")):
            faults.append(
                f"«{key}» looks like a path, not an id: {v[:80]!r}. The contract composes "
                f"`.coyomap/verify/claims-«CLAIMS».json` and `verdicts-«BATCH».json` from these, so "
                f"each is the bare batch id between `claims-` and `.json` (`backbone-1`)")
    # NOT CHECKED HERE: a component budget on a slice that authors no components. It was written,
    # and it is reverted. `«SLICE_KIND»` is FREE TEXT — a real value is a sentence — so matching it
    # against words like `config` or `entit` refuses legitimate structural slices: "config loading
    # and startup", "HTTP routing and config parsing", "deployment scripts and the CI workflow"
    # were all refused by the version that shipped. And the remedy it demanded made the brief
    # WORSE: writing `0` puts "Expect roughly 0 components" in front of a slice that really has
    # seven. The retro's own reader called this half unimplementable before it was written, and was
    # right: catching it needs an ENUM of slice kinds, which the contract does not have.
    return faults


#: A key the skeleton prints to EXPLAIN a slot, never to fill one. `--fill` skips it, so the file
#: the lead edits is the file it hands back.
_COMMENT_KEY = "//"


def union_slots(names: list[str], root: Path | None = None) -> list[str]:
    """Every slot of several contracts composed into ONE brief, first appearance first.

    `--append doors` exists because the two halves were joined with `>>`, and the slot sets do NOT
    coincide: trace owns «USE_CASES», «SF_RANGE», «LEGEND», «WHERE_TO_LOOK» and «your-fragment»,
    doors owns «FLOWS», «MAP» and «SURFACES», and only «REPO», «AGENT_ID» and «COYOMAP_HOME» are
    shared. So the fill has to be checked against the UNION or the appended half goes out unfilled,
    which is exactly what happened to 9 of 10 briefs."""
    seen: dict[str, None] = {}
    for name in names:
        for key in slots(name, root):
            seen.setdefault(key, None)
    return list(seen)


def fill(name: str, values: dict[str, str], root: Path | None = None,
         append: list[str] | None = None) -> str:
    """The contract with every slot replaced — or a refusal naming exactly what is wrong.

    `append` names further contracts whose agent halves ride in the SAME file, filled from the SAME
    values, checked against the union of the slot sets. Refuses BEFORE writing anything, and reports
    every fault at once: a lead that has to re-run this three times to learn three missing slots is
    the brief→re-read loop this verb exists to end."""
    names = [name, *(append or [])]
    text = "\n\n".join(render(n, root).strip("\n") for n in names) + "\n"
    present = union_slots(names, root)
    values = {k: v for k, v in values.items() if not k.startswith(_COMMENT_KEY)}
    faults: list[str] = []

    unknown = sorted(set(values) - set(present))
    if unknown:
        faults.append(f"no such slot in the {' + '.join(names)} contract: {', '.join(unknown)} "
                      f"(its slots are: {', '.join(present)})")
    # Each missing slot NAMED WITH ITS OWN CONTRACT. Under `--append` the composed brief's slots come
    # from two templates, and `no value given for: FLOWS, MAP, SURFACES` sent a lead grepping
    # trace-contract.md for three slots that all live in doors-contract.md.
    owner = {k: n for n in reversed(names) for k in slots(n, root)}
    missing = [k if len(names) == 1 else f"{k} ({owner[k]})" for k in present if k not in values]
    if missing:
        faults.append(f"no value given for: {', '.join(missing)}")
    for key in present:
        if key not in values:
            continue
        value = values[key]
        if not isinstance(value, str):
            faults.append(f"«{key}»: value is {type(value).__name__}, not a string")
        elif not value.strip():
            faults.append(f"«{key}»: value is blank — a slot filled with whitespace reaches the "
                          f"agent as an empty instruction, which no gate can see")
        elif SLOT.search(value):
            faults.append(f"«{key}»: value still carries «guillemets», so it is a slot name and "
                          f"not a filled value")
    for one in names:
        faults += _slot_content_faults(one, values)
    if faults:
        raise ValueError("; ".join(faults))

    out = SLOT.sub(lambda m: values[m.group(1).strip()], text)
    left = SLOT.findall(out)
    if left:  # unreachable by construction; a silent survivor is the whole failure mode
        raise ValueError(f"slot(s) survived the fill: {', '.join(sorted(set(left)))}")
    return out


def brief(agent_id: str, path: Path) -> str:
    """The three-line pointer prompt to SEND. The brief is generated, never composed."""
    agent_id = agent_id.strip()
    if not agent_id or agent_id.split() != [agent_id]:
        raise ValueError(f"agent id {agent_id!r} must be one word with no spaces — it is what the "
                         f"fan-out's completion notifications are named by")
    if not path.is_absolute():
        raise ValueError(f"{path} is not absolute. An agent does not share the lead's working "
                         f"directory, so a relative brief path resolves somewhere else or nowhere")
    text = f"{agent_id}\n{path}\n{BRIEF_SENTENCE}\n"
    size = len(text.encode("utf-8"))
    if size > BRIEF_MAX_BYTES:
        raise ValueError(f"the brief is {size} bytes, over the {BRIEF_MAX_BYTES}-byte pointer cap "
                         f"— the path alone is too long to send as a pointer")
    return text


_USAGE = ("usage: coyomap contract <" + " | ".join(CONTRACTS) + "> [--slots] [--append <name>]...\n"
          "       coyomap contract <name> --fill <slots.json|-> --out <file> [--brief <agent-id>]\n"
          "                                                        [--append <name>]... [--force]\n"
          "       coyomap contract <name> --from-slots <dir> --out-dir <dir> [--append <name>]...\n"
          "       coyomap contract skeptic --from-batches <dir> --fill <slots.json> --out-dir <dir>\n"
          "                                [--votes <theme>=N]... [--prefix <from>-<to>-]\n"
          "       coyomap contract closer --from-verdicts <dir> --map <map> --fill <slots.json>\n"
          "                               --out <file> [--exclude <id>]... [--settled <file>]...\n"
          "                               [--prefix <from>-<to>-]\n\n"
          "Print exactly the text one fan-out agent should receive: the contract's agent half,\n"
          "with the writing rules appended for the phases whose agents author map prose\n"
          "(" + ", ".join(sorted(AUTHORING)) + ").\n\n"
          "  --from-batches  one skeptic brief per claims-*.json in <dir>, BATCH and CLAIMS filled\n"
          "            from the file names, --votes <theme>=N writing N voters (-a, -b, -c) over one\n"
          "            claims file. An existing brief is SKIPPED, never rewritten; the pointer\n"
          "            prompts to send are printed. Every build hand-wrote this loop with --force.\n"
          "  --prefix  only the files of one wave: an update's `changes challenge` names its\n"
          "            batches `claims-<from>-<to>-…` (and `-w2-` for a second wave) beside the\n"
          "            build's, and prints the prefix to pass; without it every build batch gets a\n"
          "            brief too, and every build refutation a closer\n"
          "  --from-slots  the BATCH form of --fill: one brief per <agent-id>.json in <dir>, written\n"
          "            to <out-dir>/<agent-id>.md, with the pointer prompts. Every slots file is\n"
          "            checked BEFORE anything is written and every fault is reported at once, so a\n"
          "            bad eighth slice cannot leave seven briefs and a half-dispatched fan-out.\n"
          "  --from-verdicts  closer only: read the skeptics' verdicts-*.json in <dir>, take every\n"
          "            refuted claim, and BUILD «CLAIMS» — each claim with its skeptic's evidence\n"
          "            and note, and the `dump --id` / `--record` / `--edges` rows the map holds for\n"
          "            it, for every claim kind. --exclude <id> drops one by refutation id\n"
          "            (`rule-1#12`) or element id (`BR205`); --settled <closer-verdicts.json> drops\n"
          "            everything a previous wave judged. An --exclude matching nothing is an ERROR.\n"
          "  --append  compose a second contract's agent half into the SAME brief, filled from the\n"
          "            same slots file and checked against the UNION of both slot sets. This is how\n"
          "            the doors half rides a trace brief: `>>` walked around --fill and 9 of 10\n"
          "            trace briefs reached their agent still carrying nine literal slot names.\n"
          "  --slots   print a ready-to-fill JSON skeleton — every slot of THIS contract as a\n"
          "            key with an empty value, each preceded by a `//` line saying what goes in\n"
          "            it, so no slot name and no slot's meaning is ever guessed at.\n"
          "  --force   overwrite an existing --out. Without it an existing file is REFUSED: under\n"
          "            pointer dispatch a filled contract is an agent's whole brief, so rewriting\n"
          "            one rewrites the instructions of an agent that may still be running.\n"
          "  --fill    fill those slots and write the result to --out. REFUSES on a slot with no\n"
          "            value, a blank value, a value still carrying «guillemets», or a key that is\n"
          "            no slot of this contract — and reports every fault at once, so learning\n"
          "            three missing slots costs one run and not three.\n"
          "  --out     where the filled contract is written. Required with --fill; nothing is\n"
          "            written unless the fill is clean.\n"
          "  --brief   also print the three-line pointer prompt to SEND for that agent id: the id,\n"
          "            the absolute --out path, and one fixed sentence. That printed text is the\n"
          "            whole brief; a pasted contract is ~13 KB times the fan-out.\n\n"
          "  coyomap contract harvest --slots > slots/h1.json       # fill the values, then:\n"
          "  coyomap contract harvest --fill slots/h1.json \\\n"
          "                           --out /abs/scratch/h1.md --brief h1\n"
          "  coyomap contract harvest --from-slots /abs/slots --out-dir /abs/briefs\n"
          "  coyomap contract trace   --from-slots /abs/tslots --out-dir /abs/tbriefs \\\n"
          "                           --append doors\n\n"
          "A harvest --fill / --from-slots also writes <repo>/.coyomap/verify/budgets.json, the\n"
          "one file this verb writes outside --out: `finalize` sums the budgets the briefs were\n"
          "dispatched with. A batch that would drop another build's agents from it is REFUSED.\n\n"
          "Without --fill it writes the UNFILLED agent half to stdout, and says on stderr that it\n"
          "is unfilled. Read it that way; do not redirect it into a brief, and never append it to\n"
          "one with `>>` — `--fill` and `--append` are what put a filled contract in a file.\n\n"
          "The lead never handles the template itself, so the lead's own instructions at the top\n"
          "of that file cannot reach an agent. COYOMAP_HOME overrides where the templates are\n"
          "read from.\n")


BUDGETS_FILE = "budgets.json"


_FIRST_INT = re.compile(r"\d+")


def budget_of(expected: str) -> int | None:
    """The FIRST whole number in a filled «EXPECTED_COMPONENTS» slot, or None when it has none.

    The first number and nothing else: real briefs wrote `**4–6**`, `~10 (8–12)` and `five`, and a
    digit-scrape turned the first two into 46 and 10812. A range records its low end; a word
    records None, which `finalize` then reports as a brief with no numeric budget rather than
    dropping the slice from the sum while the shipped count keeps it."""
    hit = _FIRST_INT.search(expected)
    return int(hit.group(0)) if hit else None


def budget_conflict(doc: dict[str, object], agent_id: str, session: str | None) -> str | None:
    """Why writing this agent's budget would DESTROY another build's, or None when it would not.

    The rule turns on the one thing that really does tell the two cases apart, per call, with no
    knowledge of how many calls are coming:

    * **A REBUILD RENAMES ITS AGENTS.** `record_budget`'s own docstring says so — `h1..h12` one
      build, `h-entry-gateway…` the next. A fresh id over another build's file is a new harvest, and
      starting the file over is exactly right. It is NOT refused, because refusing the correct
      action is the shape this guard exists to remove, not to add.
    * **A RE-RUN REUSES THEM.** An id the other build already budgeted means this is that build's
      slice being filled again — a replay, a repair, a subset — and the reset would drop every
      sibling slice while leaving a file that still looks like a whole harvest. `finalize` cannot
      tell: it sums `harvest` and never reads `session`.

    The false positive is a rebuild that reuses the previous build's ids exactly, and it is the case
    where refusing costs least and matters most: identical ids would be overwritten one by one
    anyway, so the only way the old file can survive the fan-out is by holding MORE slices than the
    new one — which is the harm itself. The false negative, a replay that renames its agents, is
    indistinguishable from a rebuild by any means at all.

    Takes the already-parsed document so the single `--fill` path can ask BEFORE it writes a brief
    and the batch path can ask during its plan phase, with one condition between them."""
    if not session or doc.get("session") == session:
        return None
    held = doc.get("harvest")
    if not isinstance(held, dict) or agent_id not in held:
        return None
    other = doc.get("session")
    dropped = sorted(k for k in held if k != agent_id)
    return (f"budgets.json already records `{agent_id}` under build "
            f"{other if other else '(no session id)'}, and this is build {session} — so this is "
            f"that build's slice being filled again, not a new harvest. Writing it would start the "
            f"file over and drop {len(dropped)} sibling slice(s) "
            f"({', '.join(dropped[:6])}{f', +{len(dropped) - 6} more' if len(dropped) > 6 else ''}), "
            f"leaving a file that still looks like a whole harvest — `finalize` sums `harvest` and "
            f"never reads `session`, so it would report the remainder against every component the "
            f"map ships. A real rebuild names its agents afresh and is not refused here. Delete "
            f"that file if the earlier build's budgets are finished with; it is build telemetry, "
            f"not map content")


def record_budget(repo: Path, agent_id: str, expected: str,
                  session: str | None = None) -> Path:
    """`<repo>/.coyomap/verify/budgets.json`: the component budget each harvest brief was handed,
    keyed by agent id. `lint-fragment --expect` checks one slice against its own budget; nothing
    summed the budgets against what shipped — 60 dispatched, 114 shipped, every slice over, and
    the guard added for an earlier build of the same shape was per fragment only. `finalize`
    reads this file.

    `session` is the build's own id (the harness's session id, from the environment). The file
    belongs to ONE build: when it carries another session's id it is started over, because a
    rebuild names its agents afresh (`h1..h12` one build, `h-entry-gateway…` the next) and a merge
    across builds would sum two harvests against one map.

    **THE RE-RUN OF A FEW SLICES IS THE ONE CASE THAT RESET GETS WRONG**, and it REFUSES here — in
    this function rather than in either caller, because `budgets.json` is written for `harvest`
    alone and the method dispatches harvest ONE `--fill` PER SLICE. A guard in the batch verb missed
    the path the method actually uses: three `--fill` calls under a fresh session turned a
    `{h1…h8}` file into `{h1,h2,h3}`, exit 0 and no warning on all three, after which `finalize`
    summed 23 budgeted against 126 shipped and raised a band failure about a harvest that never
    happened."""
    path = repo / ".coyomap" / "verify" / BUDGETS_FILE
    doc: dict[str, object] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                doc = loaded
        except ValueError:
            doc = {}
    conflict = budget_conflict(doc, agent_id, session)
    if conflict:
        raise ValueError(conflict)
    if session and doc.get("session") != session:
        doc = {}
    harvest = doc.get("harvest")
    if not isinstance(harvest, dict):
        harvest = {}
    harvest[agent_id] = budget_of(expected)
    doc["harvest"] = harvest
    if session:
        doc["session"] = session
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def batch_ids(batches_dir: Path, prefix: str = "") -> list[tuple[str, str]]:
    """`(batch id, theme)` for every `claims-*.json` an `audit --batches` run wrote, in name order.
    `prefix` narrows to one wave's files: an update's `changes challenge` writes
    `claims-<from>-<to>-<theme>.json` beside the build's, and a brief per build batch would send
    a skeptic at claims that were settled months ago."""
    out: list[tuple[str, str]] = []
    for f in sorted(batches_dir.glob(f"claims-{prefix}*.json")):
        theme = ""
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                theme = str(doc.get("theme", ""))
        except (OSError, ValueError):
            pass
        out.append((f.stem[len("claims-"):], theme))
    return out


def write_briefs(plan: list[tuple[str, Path, str]]) -> list[tuple[str, Path, str]]:
    """Write a whole batch of filled briefs, after every one of them has been composed.

    Returns `(agent id, path, state)` with state `written` or `skipped`. TWO rules, and both are
    measured defects:

    * **Nothing is written until every brief in the batch has been filled**, so a fault in the
      eighth slots file does not leave seven briefs on disk and an agent dispatched against a
      half-written fan-out. The caller composes first and calls this once.
    * **An existing brief is NEVER rewritten.** Under pointer dispatch a filled contract is an
      agent's whole brief, read whenever the agent gets round to it, so overwriting one rewrites the
      instructions of something that may still be running."""
    out: list[tuple[str, Path, str]] = []
    for agent_id, target, text in plan:
        if target.exists():
            out.append((agent_id, target, "skipped"))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        out.append((agent_id, target, "written"))
    return out


def fill_from_slots(name: str, slots_dir: Path, out_dir: Path, root: Path | None = None,
                    append: list[str] | None = None,
                    session: str | None = None) -> list[tuple[str, Path, str]]:
    """One brief per `<agent-id>.json` in `slots_dir`, written to `<out-dir>/<agent-id>.md`.

    The batch form of `--fill`, and it exists for the shape `record --lines-from` already retired.
    A build looped `contract harvest --fill` over 8 slices under `set -e`; all 8 exited 2, `set -e`
    did NOT abort the loop in this harness, and the trailing `&&` appended an addendum to a brief no
    fill had written — leaving a file that was only the addendum. One process, one pass, every slots
    file checked before anything is written, EVERY fault reported at once.

    The agent id is the file's stem, so the slots directory names the fan-out and nothing else has
    to. A slots file may carry `//`-commented spec lines exactly as `--slots` printed them.

    **IT ALSO WRITES `<repo>/.coyomap/verify/budgets.json`** for a harvest batch, which is a write
    into the MAPPED repo from a verb whose headline is that it prints a prompt. That is said in
    `--help`, and the destructive half is refused by `budget_conflict`, which BOTH fill paths ask.
    Asking it here as well, during the plan phase, is only so that a batch refusing writes no briefs
    at all; the condition itself lives with `record_budget`, because that is the one place every
    write goes through."""
    if not slots_dir.is_dir():
        raise ValueError(f"--from-slots {slots_dir} is not a directory; it is where one "
                         f"`<agent-id>.json` per agent lives, as `--slots` prints them")
    files = sorted(slots_dir.glob("*.json"))
    if not files:
        raise ValueError(f"no *.json under {slots_dir} — write one slots file per agent first "
                         f"(`coyomap contract {name} --slots > {slots_dir}/<agent-id>.json`)")
    plan: list[tuple[str, Path, str]] = []
    faults: list[str] = []
    budgets: list[tuple[str, Path, str, str]] = []
    for f in files:
        try:
            values = _read_values(str(f))
        except (OSError, ValueError) as exc:
            faults.append(f"{f.name}: {exc}")
            continue
        try:
            plan.append((f.stem, out_dir / f"{f.stem}.md", fill(name, values, root, append)))
        except ValueError as exc:
            faults.append(f"{f.name}: {exc}")
            continue
        # Same three slots the single `--fill` reads, so a batch fan-out records the budgets
        # `finalize` sums instead of silently shipping a `budgets.json` with a hole in it.
        if name == "harvest" and values.get("agent-id") and values.get("EXPECTED_COMPONENTS"):
            repo_slot = str(values.get("REPO_ABS") or values.get("repo") or "")
            if repo_slot:
                budgets.append((f.stem, Path(repo_slot), str(values["agent-id"]),
                                str(values["EXPECTED_COMPONENTS"])))
    faults += _budget_reset_faults(budgets, session)
    if faults:
        raise ValueError(f"{len(faults)} of {len(files)} slots file(s) are bad; NOTHING was "
                         f"written — " + " | ".join(faults))
    written = write_briefs(plan)
    done = {stem for stem, _p, state in written if state == "written"}
    for stem, repo_slot, agent_id, expected in budgets:
        if stem in done:
            record_budget(repo_slot, agent_id, expected, session=session)
    return written


def budgets_doc(repo: Path) -> dict[str, object]:
    """`<repo>/.coyomap/verify/budgets.json` as a dict, or empty when it is absent or unreadable.

    One reader, so `record_budget` and the callers that ask it BEFORE writing a brief see the same
    file the same way — an unreadable file is "no budgets recorded", never a crash, because this is
    build telemetry and `finalize` already refuses to fail a map over it."""
    try:
        loaded = json.loads((repo / ".coyomap" / "verify" / BUDGETS_FILE)
                            .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _budget_reset_faults(budgets: list[tuple[str, Path, str, str]],
                         session: str | None) -> list[str]:
    """The batch path's half of the same question `record_budget` asks per call.

    It is asked HERE too, and not left to `record_budget`, only so that a batch refuses in its plan
    phase and writes no briefs at all. The CONDITION is `budget_conflict`'s and nothing else: two
    copies of that reasoning is how the first version of this guard ended up on a path the method
    does not use for harvest."""
    faults: list[str] = []
    for stem, repo, agent_id, _expected in budgets:
        conflict = budget_conflict(budgets_doc(repo), agent_id, session)
        if conflict:
            faults.append(f"{stem}.json: {conflict}")
    return faults


def fill_from_batches(values: dict[str, str], batches_dir: Path, out_dir: Path,
                      votes: dict[str, int], root: Path | None = None,
                      prefix: str = "") -> list[tuple[str, Path, str]]:
    """One skeptic brief per batch file (`votes` per theme: `{"security": 3}` writes `-a`, `-b`,
    `-c` voters over one claims file). Returns `(batch id, path, state)` with state `written` or
    `skipped`: an existing brief is NEVER rewritten, because under pointer dispatch it may be an
    agent's running instructions — the loop every build hand-wrote passed `--force` on all 38.
    `BATCH` and `CLAIMS` are this verb's to fill; a slots file naming them is refused."""
    # An EMPTY value for either is what `--slots` prints, so it is tolerated; a filled one would be
    # silently overwritten, so it is refused.
    filled = [k for k in ("BATCH", "CLAIMS") if (values.get(k) or "").strip()]
    if filled:
        raise ValueError(f"--from-batches fills «BATCH» and «CLAIMS» itself; leave them empty or out "
                         f"of the slots file (given: {', '.join(filled)})")
    values = {k: v for k, v in values.items() if k not in ("BATCH", "CLAIMS")}
    if not batches_dir.is_dir():
        raise ValueError(f"--from-batches {batches_dir} is not a directory; it is where "
                         f"`audit --batches` wrote the claims files")
    batches = batch_ids(batches_dir, prefix)
    if not batches:
        raise ValueError(f"no claims-{prefix}*.json under {batches_dir} — run `coyomap audit <map> "
                         f"--batches {batches_dir}` first (or `changes challenge` for an update); "
                         f"nothing to write a brief for")
    plan: list[tuple[str, Path, str]] = []
    for bid, theme in batches:
        n = votes.get(theme, 1)
        voters = [bid] if n <= 1 else [f"{bid}-{chr(ord('a') + k)}" for k in range(n)]
        for voter in voters:
            plan.append((voter, out_dir / f"skeptic-{voter}.md",
                         fill("skeptic", {**values, "BATCH": voter, "CLAIMS": bid}, root)))
    return write_briefs(plan)


# ── the closer's claims block, built from the skeptics' own verdict files ─────────────────────────
#
# `contract closer` had `--slots` and `--fill` and nothing else, so the claims block was composed by
# hand — TWICE in one build, in two different shapes: a typed heredoc for the first wave, a 30-line
# regex generator for the second. That generator dispatched on a component line, an edge triple and
# a flow step and had NO branch for a rule-site claim, so 16 of 20 refutations carried a map row and
# 4 carried none. The closer returned `uphold` on all four rowless blocks and `unsure` on none,
# which is the exact failure `closer-contract.md` tells it to avoid. Its second bug was an exclusion
# list of rule ids tested against the claim TEXT, which carries the rule STATEMENT and never the id:
# 0 of 20 matched, and four settled refutations were re-judged.


@dataclass(frozen=True)
class Refutation:
    """One `grounded: false` row, with the id that addresses it across waves.

    `id` is `<batch>#<row number in that batch's verdicts file>` — stable because the file is written
    once and never edited, typable by a lead, and it names where the refutation came from. A wave-two
    closer excludes what wave one settled BY THAT ID, never by matching text."""
    id: str
    claim: str
    evidence: str
    skeptic: str
    note: str


@dataclass(frozen=True)
class Settled:
    """What a prior closer already judged: the refutation ids it recorded, and the claim strings, so
    a closer file written before ids existed still excludes."""
    ids: frozenset[str]
    claims: frozenset[str]


#: An element id anywhere in a claim's text. Longer prefixes first, so `BR205` is a rule and not a
#: role. Used only when a claim resolves to no single element — the resolver's answer wins.
_ID_TOKEN = re.compile(r"\b(?:CAP|BLK|UC|SF|BR|EP|SD|HP|[CDEIRS])\d+\b")

#: A flow-step claim, exactly as `audit --batches` mints it:
#: `UC1 step 4: C90 → C43 [in] — hand the typed account details to the sign-up panel`.
#: `resolve_claim` has no branch for these (a step phrase is re-authored, never anchor-corrected), so
#: the container and both endpoints are read off the claim itself.
_STEP_CLAIM = re.compile(r"^(UC\d+|SF\d+) step (\d+): (\S+) → (\S+)(?: \[[a-z]+\])? — ")


def refutations(verdicts_dir: Path, prefix: str = "") -> list[Refutation]:
    """Every `grounded: false` row across `verdicts-*.json` in one directory, in file-name order.
    `prefix` narrows to one wave's files (an update's `verdicts-<from>-<to>-…`): the build's
    refutations beside them were reconciled long ago and resolve to no row on today's map."""
    if not verdicts_dir.is_dir():
        raise ValueError(f"--from-verdicts {verdicts_dir} is not a directory; it is where the "
                         f"skeptics wrote `verdicts-<batch>.json`")
    files = sorted(verdicts_dir.glob(f"verdicts-{prefix}*.json"))
    if not files:
        raise ValueError(f"no verdicts-{prefix}*.json under {verdicts_dir} — the skeptic fan-out "
                         f"has not landed, so there is no refutation to close")
    out: list[Refutation] = []
    for f in files:
        batch = f.stem[len("verdicts-"):]
        try:
            rows, _notes = load_verdicts([str(f)])
        except SystemExit as exc:           # `load_verdicts` exits on malformed JSON; we report it
            raise ValueError(f"{f.name}: {exc}") from exc
        for n, row in enumerate(rows, start=1):
            if row.get("grounded") is not False:
                continue
            out.append(Refutation(id=f"{batch}#{n}", claim=str(row.get("claim") or ""),
                                  evidence=str(row.get("evidence") or ""),
                                  skeptic=str(row.get("skeptic") or batch),
                                  note=str(row.get("note") or "")))
    return out


def settled_by(paths: list[Path]) -> Settled:
    """The refutations a prior closer already judged, read from the verdicts file it wrote."""
    ids: set[str] = set()
    claims: set[str] = set()
    for p in paths:
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"--settled {p}: {exc}") from exc
        rows = payload.get("grounding", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError(f"--settled {p}: `grounding` must be a list of verdict rows")
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "").strip():
                ids.add(str(row["id"]).strip())
            if str(row.get("claim") or "").strip():
                claims.add(str(row["claim"]).strip())
    return Settled(frozenset(ids), frozenset(claims))


def _rule_ids_by_statement(m: ProjectModel, claim: str) -> list[str]:
    """The rule(s) a rule-site claim is about, found by its STATEMENT when its anchor has moved.

    Every rule carrying that exact statement, not the first: two rules stating the same decision is
    a map defect, and answering with one of them silently picks a side. The brief then names both and
    the closer can see what it is being asked."""
    hit = RULE_SITE_CLAIM.match(claim)
    if not hit:
        return []
    statement = hit.group(1)
    return [br.id for br in m.rules if (br.statement or "") == statement]


def dump_ids(m: ProjectModel, claim: str) -> list[str]:
    """The element ids whose map rows this claim is ABOUT, in the order they should be dumped.

    One rule per claim kind, and the rule-site kind is the one the hand-written generator had no
    branch for. A step claim names its container and both endpoints; every other kind goes through
    `resolve_claim`, the map's single claim→element reader, so a kind added there is covered here
    without a second dispatch to keep in step. A claim that resolves to nothing falls back to the ids
    written in its own text, and `claims_block` says so in the brief.

    **A RULE-SITE CLAIM NEEDS ITS OWN FALLBACK, and leaving it out reproduced the very split this
    verb replaced.** `resolve_claim` matches a rule site on statement AND anchor AND why, because it
    resolves in order to WRITE a corrected anchor and a rule whose site moved is the one a writer must
    not touch. But a rule refutation is APPLIED by moving or dropping that site, so by the time a
    second wave asks about it the anchor no longer matches and the claim resolves to nothing — while
    its text carries the statement and never the id, so the id scan finds nothing either. Run against
    the 2026-09-13 build's own 38 verdict files this gave 16 of 20 refutations a map row and 4 none:
    `rule-1#27`, `rule-1#28`, `rule-2#13`, `security-4-c#4`, the identical split the hand-written
    generator produced. The statement alone still names the rule, so that is what is matched."""
    step = _STEP_CLAIM.match(claim)
    if step:
        found = [step.group(1), step.group(3), step.group(4)]
    else:
        match = resolve_claim(m, claim)
        eid = match.target.element_id if match.target else ""
        found = [eid] if eid else _rule_ids_by_statement(m, claim) or _ID_TOKEN.findall(claim)
    seen: dict[str, None] = {}
    for eid in found:
        if _ID_TOKEN.fullmatch(eid):
            seen.setdefault(eid, None)
    return list(seen)


@dataclass(frozen=True)
class MapRows:
    """One element's `dump` output for a brief, and whether the map actually held it.

    `found` is separate from `blocks` being non-empty, because a missing element still PRINTS a
    block — the line saying it is missing. A caller that read emptiness as absence is the bug below."""
    blocks: list[str]
    found: bool


def _dump_blocks(m: ProjectModel, eid: str) -> MapRows:
    """The three `dump` slices `method.md` and `closer-contract.md` both require under a claim —
    `--id`, `--record`, `--edges`. Run HERE rather than typed by the lead: across a 571-turn build
    `dump` was typed once and `--edges` never, so the arrows were withheld from all 7 refuted
    component descriptions while both documents said they must be pasted."""
    out: list[str] = []
    slice_id = resolve_id(m, eid)
    if slice_id is None:
        return MapRows([f"`dump --id {eid}` — NOT IN THE MAP: no element carries this id."], False)
    out.append(f"`dump --id {eid}`:\n```json\n{json.dumps(slice_id, indent=1, default=str)}\n```")
    record = record_of(m, eid)
    if record is not None:
        out.append(f"`dump --record {eid}`:\n```json\n"
                   f"{json.dumps(record, indent=1, default=str)}\n```")
    edges = edges_of(m, eid)
    if edges["in"] or edges["out"]:
        out.append(f"`dump --edges {eid}`:\n```json\n"
                   f"{json.dumps(edges, indent=1, default=str)}\n```")
    else:
        out.append(f"`dump --edges {eid}`: no backbone edge enters or leaves {eid}.")
    return MapRows(out, True)


def claims_block(m: ProjectModel, refs: list[Refutation]) -> str:
    """The «CLAIMS» value: one section per refutation, each carrying the claim, the skeptic's
    evidence and note, and the map rows the claim is about.

    **THE ROWLESS BLOCK CARRIES ITS OWN INSTRUCTION.** Whether the rows are missing because no id
    was found or because every id found is absent from the map, the closer is looking at the same
    thing — a claim it cannot check — and it must answer `unsure`. Gating that paragraph on "no id
    was found" left the second case silent: an id the map no longer holds printed `NOT IN THE MAP`
    and nothing else, which is exactly the shape that returned four `uphold`s and zero `unsure` on
    the 2026-09-13 build. The test is whether any id yielded ROWS, never whether an id was named."""
    out: list[str] = []
    for ref in refs:
        ids = dump_ids(m, ref.claim)
        rows = [(eid, _dump_blocks(m, eid)) for eid in ids]
        grounded = [eid for eid, r in rows if r.found]
        out.append(f"### {ref.id} — {', '.join(grounded) if grounded else 'NO MAP ROW FOUND'}")
        out.append(f"**claim (verbatim):** {ref.claim}")
        out.append(f"**skeptic:** `{ref.skeptic}` · **evidence:** `{ref.evidence or '(none given)'}`")
        out.append(f"**skeptic's note:** {ref.note or '(none given)'}")
        if not grounded:
            missing = f" The map holds no {', '.join(ids)}." if ids else ""
            out.append("**The map rows for this claim could not be found** — nothing in the map "
                       f"resolves it.{missing} Return `unsure` and say so, exactly as this contract "
                       "tells you to when rows are missing. Do NOT settle it from the claim text "
                       "and the skeptic's note alone: on the build this instruction was written "
                       "after, four blocks arrived exactly like this one and all four came back "
                       "`uphold`, with no `unsure` anywhere across two waves.")
        for _eid, r in rows:
            out.extend(r.blocks)
        out.append("")
    return "\n\n".join(out).strip("\n")


def fill_from_verdicts(values: dict[str, str], verdicts_dir: Path, map_path: Path,
                       exclude: list[str], settled: list[Path],
                       root: Path | None = None, prefix: str = "") -> tuple[str, list[Refutation]]:
    """The filled closer contract, with «CLAIMS» built from the skeptics' own verdict files.

    `exclude` takes a refutation id (`rule-1#12`) or an element id (`BR205`), and an exclusion that
    matches NOTHING is an ERROR: a filter that silently matched zero is the measured bug — a
    wave-two brief re-sent four already-settled refutations because the ids were tested against
    claim text that carries the rule statement and never the id."""
    banned = [k for k in ("CLAIMS",) if (values.get(k) or "").strip()]
    if banned:
        raise ValueError(f"--from-verdicts builds «CLAIMS» itself; leave it empty or out of the "
                         f"slots file (given: {', '.join(banned)})")
    values = {k: v for k, v in values.items() if k != "CLAIMS"}
    try:
        # Through the guard like every other map reader: a lead whose shell folder drifted into the
        # clone would otherwise build a closer brief out of COYOMAP'S OWN map rows, and the brief
        # would look perfectly healthy.
        resolved = resolve_map_path(map_path)
        m = load_model(resolved.read_text(encoding="utf-8"))
    except (OSError, ModelError) as exc:
        raise ValueError(f"--map {map_path}: {exc}") from exc
    refs = refutations(verdicts_dir, prefix)
    already = settled_by(settled)
    kept: list[Refutation] = []
    hit: dict[str, int] = {k: 0 for k in exclude}
    settled_hits = 0
    for ref in refs:
        if ref.id in already.ids or ref.claim.strip() in already.claims:
            settled_hits += 1
            continue
        names = {ref.id, *dump_ids(m, ref.claim)}
        matched = [k for k in exclude if k in names]
        for k in matched:
            hit[k] += 1
        if matched:
            continue
        kept.append(ref)
    dead = [k for k, n in hit.items() if n == 0]
    if dead:
        raise ValueError(
            f"--exclude matched no refutation: {', '.join(dead)}. An exclusion that matches nothing "
            f"is the bug this flag exists to stop — a wave-two brief filtered on rule ids that a "
            f"claim's text never carries, matched 0 of 20, and re-sent four settled refutations. "
            f"An exclusion is a refutation id (`rule-1#12`) or an element id (`BR205`)")
    if settled and not settled_hits:
        raise ValueError(f"--settled named {len(already.ids) or len(already.claims)} judgement(s) "
                         f"and none of them is a refutation in {verdicts_dir} — that is the wrong "
                         f"file, not an empty wave")
    if not kept:
        raise ValueError(f"every one of the {len(refs)} refutation(s) in {verdicts_dir} is already "
                         f"settled or excluded; there is nothing for a closer to judge")
    return fill("closer", {**values, "CLAIMS": claims_block(m, kept)}, root), kept


def _read_values(source: str) -> dict[str, str]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"--fill expects a JSON object of slot -> value, found "
                         f"{type(data).__name__}")
    return data


def _print_batch(results: list[tuple[str, Path, str]]) -> None:
    """What a batch run prints: one line per brief, the tally, then one pointer prompt per brief it
    actually wrote. Shared by `--from-batches` and `--from-slots` so the two fan-out forms cannot
    report themselves differently."""
    for agent_id, target, state in results:
        print(f"{state:8} {agent_id:20} {target}")
    written = [(a, t) for a, t, s in results if s == "written"]
    print(f"{len(written)} brief(s) written, {len(results) - len(written)} skipped (existing "
          f"briefs are never rewritten). Pointer prompts to SEND, one per agent:")
    for agent_id, target in written:
        print(); print(brief(agent_id, target.resolve()))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or "-h" in args or "--help" in args:
        print(_USAGE)
        return 0 if args else 2
    name = args[0]
    if name not in CONTRACTS:
        print(f"ERROR: unknown contract '{name}' — one of {', '.join(CONTRACTS)}", file=sys.stderr)
        return 2

    want_slots = False
    force = False
    fill_from: str | None = None
    out_path: str | None = None
    brief_id: str | None = None
    from_batches: str | None = None
    from_slots: str | None = None
    from_verdicts: str | None = None
    map_path: str | None = None
    out_dir: str | None = None
    prefix = ""
    votes: dict[str, int] = {}
    append: list[str] = []
    exclude: list[str] = []
    settled: list[str] = []
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--slots":
            want_slots = True
        elif a == "--force":
            force = True
        elif a in ("--fill", "--out", "--brief", "--from-batches", "--out-dir", "--votes",
                   "--append", "--from-slots", "--from-verdicts", "--map", "--exclude",
                   "--settled", "--prefix"):
            i += 1
            if i >= len(args):
                print(f"ERROR: {a} needs a value", file=sys.stderr)
                return 2
            if a == "--fill":
                fill_from = args[i]
            elif a == "--prefix":
                prefix = args[i]
            elif a == "--out":
                out_path = args[i]
            elif a == "--from-batches":
                from_batches = args[i]
            elif a == "--from-slots":
                from_slots = args[i]
            elif a == "--from-verdicts":
                from_verdicts = args[i]
            elif a == "--map":
                map_path = args[i]
            elif a == "--exclude":
                exclude.append(args[i])
            elif a == "--settled":
                settled.append(args[i])
            elif a == "--append":
                if args[i] not in CONTRACTS:
                    print(f"ERROR: --append {args[i]}: no such contract — one of "
                          f"{', '.join(CONTRACTS)}", file=sys.stderr)
                    return 2
                append.append(args[i])
            elif a == "--out-dir":
                out_dir = args[i]
            elif a == "--votes":
                theme, _, n = args[i].partition("=")
                if not theme or not n.isdigit():
                    print(f"ERROR: --votes expects <theme>=<count>, got '{args[i]}'", file=sys.stderr)
                    return 2
                votes[theme] = int(n)
            else:
                brief_id = args[i]
        else:
            print(f"ERROR: unknown option '{a}'", file=sys.stderr)
            return 2
        i += 1

    if want_slots and (fill_from or out_path or brief_id):
        print("ERROR: --slots prints the skeleton and writes nothing; it does not combine with "
              "--fill / --out / --brief", file=sys.stderr)
        return 2
    if out_path and not fill_from:
        print("ERROR: --out has nothing to write without --fill", file=sys.stderr)
        return 2
    if brief_id and not fill_from:
        print("ERROR: --brief names the file --fill writes, so it needs --fill", file=sys.stderr)
        return 2
    if from_batches is not None:
        if name != "skeptic" or not fill_from or not out_dir:
            print("ERROR: --from-batches is `contract skeptic --from-batches <dir> --fill <slots> "
                  "--out-dir <dir> [--votes <theme>=N]`", file=sys.stderr)
            return 2
        try:
            results = fill_from_batches(_read_values(fill_from), Path(from_batches), Path(out_dir), votes,
                                        prefix=prefix)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        _print_batch(results)
        return 0
    if from_slots is not None:
        if not out_dir or fill_from:
            print("ERROR: --from-slots is `contract <name> --from-slots <dir> --out-dir <dir> "
                  "[--append <name>]`; the slot values come from the directory, not from --fill",
                  file=sys.stderr)
            return 2
        try:
            results = fill_from_slots(name, Path(from_slots), Path(out_dir), None, append,
                                      session=os.environ.get(SESSION_ENV))
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        _print_batch(results)
        return 0
    if from_verdicts is not None:
        if name != "closer" or not fill_from or not out_path or not map_path:
            print("ERROR: --from-verdicts is `contract closer --from-verdicts <dir> --map <map> "
                  "--fill <slots> --out <file> [--exclude <id>]... [--settled <file>]...`",
                  file=sys.stderr)
            return 2
        target = Path(out_path)
        if target.exists() and not force:
            print(f"ERROR: {target} already exists; a filled contract is an agent's whole brief. "
                  f"Pick another path, or pass --force if you know nothing is reading it.",
                  file=sys.stderr)
            return 2
        try:
            text, kept = fill_from_verdicts(_read_values(fill_from), Path(from_verdicts),
                                            Path(map_path), exclude, [Path(s) for s in settled],
                                            prefix=prefix)
        except (ValueError, json.JSONDecodeError, OSError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        pointer = brief(brief_id, target) if brief_id is not None else ""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"filled closer contract with {len(kept)} refutation(s) -> {target}", file=sys.stderr)
        for ref in kept:
            print(f"  {ref.id:22} {ref.claim[:70]}", file=sys.stderr)
        if brief_id is not None:
            sys.stdout.write(pointer)
        return 0
    if fill_from and not out_path:
        # Never to stdout: the point of the pair is that the agent reads a FILE and the lead sends
        # a pointer to it. A filled contract on stdout is one pipe away from being pasted.
        print("ERROR: --fill needs --out <file>; a filled contract is read by the agent from a "
              "file, never pasted into its prompt", file=sys.stderr)
        return 2

    try:
        if want_slots:
            print(json.dumps(skeleton([name, *append]), indent=2, ensure_ascii=False))
            return 0
        if fill_from is not None and out_path is not None:
            values = _read_values(fill_from)
            text = fill(name, values, None, append)
            target = Path(out_path)
            # REFUSE an existing file. Under pointer dispatch a filled contract IS an agent's whole
            # brief, and the agent reads it whenever it gets round to it — so overwriting one is
            # rewriting the instructions of something that may still be running. On the 2026-08-29
            # mcpolis build turn 125 hand-wrote `briefs/t1.md` for an agent launched at turn 127,
            # and turn 160's generator looped `--out …/briefs/{aid}.md` with `aid="t1"` and rewrote
            # it mid-flight. Exit 0, no warning. The lead saw only the downstream fragment-name
            # collision, 19 turns later.
            if target.exists() and not force:
                print(f"ERROR: {target} already exists. A filled contract is an agent's whole brief "
                      f"under pointer dispatch, so overwriting one rewrites the instructions of an "
                      f"agent that may still be running. Pick another path, or pass --force if you "
                      f"know nothing is reading it.", file=sys.stderr)
                return 2
            pointer = ""
            if brief_id is not None:
                # Composed BEFORE the write, so a brief that cannot be sent does not leave a
                # filled contract behind that nothing points at. The path is checked AS GIVEN and
                # never resolved first: resolving turns a relative path into a plausible absolute
                # one built from the lead's cwd, which is the exact wrong-directory mistake the
                # absolute-path rule exists to catch — silently, and in the agent's prompt.
                pointer = brief(brief_id, target)
            # THE BUDGET IS THE OTHER WRITE THIS CALL MAKES, and it is checked here, BEFORE the
            # brief — the same rule the pointer above already follows. `record_budget` refuses a
            # re-run that would drop another build's sibling slices, and a refusal must not leave a
            # filled brief behind that the refused budget was meant to accompany. THIS is the path
            # the method dispatches harvest on: one `--fill` per slice, eight times.
            budget: tuple[Path, str, str] | None = None
            if name == "harvest":
                repo_slot = values.get("REPO_ABS") or values.get("repo") or ""
                if repo_slot and values.get("agent-id") and values.get("EXPECTED_COMPONENTS"):
                    budget = (Path(repo_slot), str(values["agent-id"]),
                              str(values["EXPECTED_COMPONENTS"]))
                    conflict = budget_conflict(budgets_doc(budget[0]), budget[1],
                                               os.environ.get(SESSION_ENV))
                    if conflict:
                        print(f"ERROR: {conflict}", file=sys.stderr)
                        return 2
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            if budget is not None:
                # Recorded where `finalize` sums them, after the brief it describes exists.
                record_budget(*budget, session=os.environ.get(SESSION_ENV))
            print(f"filled {' + '.join([name, *append])} contract "
                  f"({len(union_slots([name, *append]))} slot(s)) -> {target}", file=sys.stderr)
            if brief_id is not None:
                sys.stdout.write(pointer)
            return 0
        # The UNFILLED agent half, on stdout. It is a legitimate thing to want — and it is also how
        # the doors half reached 9 of 10 trace briefs still carrying nine literal slot names, via a
        # `>>` that no check can see. So it says out loud what it is; --append composes the filled
        # form instead.
        text = "\n\n".join(render(n).strip("\n") for n in [name, *append]) + "\n"
        left = sorted(set(SLOT.findall(text)))
        if left:
            print(f"WARNING: this is the UNFILLED {' + '.join([name, *append])} contract — it still "
                  f"carries {len(left)} slot name(s): {', '.join(left)}. Appending it to a brief "
                  f"hands the agent the literal «{left[0]}». Use --fill (or "
                  f"`--fill … --append {name}` on the brief it rides).", file=sys.stderr)
        sys.stdout.write(text)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc.filename} not found — set COYOMAP_HOME to the coyomap clone",
              file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"ERROR: --fill {fill_from}: not readable JSON ({exc})", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"ERROR: {' + '.join(CONTRACTS[n] for n in [name, *append])}: {exc}", file=sys.stderr)
        return 2
    return 0
