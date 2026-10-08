#!/usr/bin/env python3
"""`coyomap record` — append a recorded exception under an extras heading.

Every advisory family in this tool names an extras heading an operator may write a `<id>: <why>`
line under, and there was no command to write one. So every record was a bespoke string append:

    python3 - <<'PY'
    d = json.load(open('.coyomap/build-fragments/behavioral.json'))
    for x in d['extras']:
        if x['heading'] == 'Balance exceptions':
            x['body'] += "\\nUC5: the two clauses are one goal, ..."
    json.dump(d, open(...,'w'), indent=2)
    PY

One live build did that SIX times against one file. Nothing checked the heading was one the tools
actually read, nothing checked the line's shape, nothing de-duplicated, and nothing protected the
body from the stale-paragraph problem — that build wrote a fourteen-component paragraph, then had to
find-and-replace its own text two turns later with a fragile `body.find(...)` + `assert`.

    coyomap record --map .coyomap/build-fragments/extras.json --heading "Balance exceptions" \\
                   --line "UC5: the two clauses are one goal — <why>" [--replace <prefix>]
    coyomap record --map .coyomap/build-fragments/extras.json --heading "Sweep debt" \\
                   --remove "<prefix>"

Under "Access baseline exceptions" each recorded path is echoed with the lines that held access in
the previous map (the newest `dev-rebuilds/NNNN/` map beside this one, or `--access-baseline
<file>`), and never with that map's text, because the why must say what the code at those lines does.

Under a heading keyed on FREE TEXT that only `validate` reads ('Sweep debt', 'Condition
exceptions', 'Skipped screen exceptions', 'Accepted duplications'), each new line is tried on the
assembled map beside the fragment, and one that on its own changes nothing `validate` reports is
refused: no key grammar can say such a line is malformed, and `a.py:1, b.py:2: <why>` silences
nothing because the reader matches the whole key.

`--remove` REPEATS too, and every prefix must match, or nothing is removed.

`--line` REPEATS, and `--lines-from <file|->` reads one per line (blank lines and `#` comments
skipped). One process, one write. Reading only the first `--line` is why a build with 57 records to
make spawned 57 processes — twenty of them re-typing long prose after the first attempt failed — for
what are independent appends under one heading:

    coyomap record --map .coyomap/build-fragments/extras.json --heading "Entry-point coverage" \\
                   --line "http-route: partial — <why>" \\
                   --line "ui-route: complete — <why>"
    coyomap record --map .coyomap/build-fragments/extras.json --heading "Entry-point coverage" \\
                   --lines-from coverage.txt
    coyomap record --headings

A line whose why holds a sentence over 20 words is refused, and the sentence is named: the viewer
shows the why, and the readability check counts it.

Every line is shape-checked BEFORE anything is written, so a bad one in a batch of twenty leaves the
fragment untouched rather than holding half a batch. `--replace` corrects one record, so it refuses
to combine with a batch. To correct several, remove them in one call (`--remove` repeats), then
write the new lines in a second (`--lines-from`).

One reason may answer SEVERAL elements — write them as one comma-separated list rather than the
same sentence once per id (live maps grew 66 lines holding 15 distinct reasons that way):

    coyomap record --map .coyomap/build-fragments/extras.json --heading "Unclaimed surfaces" \\
                   --line "C101, C148, C186: an operator surface in our own back office"

BUT ONLY WHERE THE HEADING HAS A KEY GRAMMAR. Some headings key on free text — a `path:line` anchor,
a bucket name, a whole quoted claim — and their readers match the WHOLE line, so a comma list under
one of those silences nothing and this command cannot tell you, because there is no grammar to check
it against. `coyomap record --headings` prints which is which. Two live rounds of repair came from
following the advice above under `Sweep debt`: one line naming five anchors cleared none of them,
and the fix was five lines, one anchor each.

Writes the file `--map` names, and only that: a positional argument is refused, as is an unknown
option. Ignored, `record <fragment> --heading … --line …` wrote the DEFAULT, the assembled map, and
exited 0. Name the FRAGMENT, so the next `assemble` carries the record through; writing the
assembled map instead is the edit the next assemble discards, so it is refused while the
`build-fragments/` folder beside the map holds any fragment, and the refusal names the
`build-fragments/extras.json` to record into (seeded by that call when it is missing). A map with no
fragments beside it is written as asked. Once nothing will assemble the map again (the build is
over, and an update changes the map directly), `--no-reassemble` writes it anyway.

Stdlib-only (the cli.py firewall).
"""
from __future__ import annotations

import dataclasses
import re
import shlex
import sys
from pathlib import Path

from coyomap import buildstate, prose, records
from coyomap.access_surface import baseline_beside, load_claims, where_lines
from coyomap.anchor_drift import DRIFT_EXCEPTIONS_HEADING
from coyomap.assemble import dump_preserving, load_map_or_fragment
from coyomap.finalize import ACCESS_BASELINE_EXCEPTIONS_HEADING
from coyomap.model import ExtraSection, ProjectModel, load_model_path
from coyomap.reporting import clip
from coyomap.subverb_args import undecodable
from coyomap.validate_model import validate_model

#: `__doc__` is `str | None` to a type checker, and this is the only `USAGE` in the package that is
#: not a literal — so it was the only one a test could not assert on without an error. The module
#: has a docstring; the `or ""` states that rather than making every reader prove it.
USAGE = __doc__ or ""

#: The headings the tools actually read, and which of them are the map's own build record — one
#: registry, in `records`, shared with the readers and with the views that decide where a section
#: renders. Recording under anything else is a note to nobody: the check that was supposed to be
#: silenced keeps firing, and the operator believes it was handled.
KNOWN_HEADINGS = records.KNOWN_HEADINGS

#: The flags `record` reads that take a value. Everything else on the command line is REFUSED, never
#: dropped: `_arg` reads flags by name, so a fragment given as a positional (`record extras.json
#: --heading …`) was skipped, `--map` fell back to the assembled map, the line was written there with
#: exit 0, and the next `assemble` discarded it (the 2026-10-07 mcpolis build, turn 758).
_VALUE_FLAGS: tuple[str, ...] = ("--map", "--heading", "--line", "--lines-from", "--replace",
                                 "--remove", "--access-baseline")
#: The two that repeat. `_all_args` reads every occurrence, and a value only when it is not a flag.
_REPEATED_FLAGS: tuple[str, ...] = ("--line", "--remove")
#: The flags that take no value.
_BARE_FLAGS: tuple[str, ...] = ("--headings", "--no-reassemble", "-h", "--help")

#: The flags whose value is a record's own text. The fragment holds the text, so the build state
#: keeps the start of each, enough to say which line it was, and never a second copy of it.
_TEXT_FLAGS: tuple[str, ...] = ("--line", "--remove", "--replace")
_TEXT_KEPT = 40

#: How to correct SEVERAL records, which `--replace` cannot do. Both of its batch refusals stated the
#: rule and stopped there, and a build found this way out by trying.
_REPLACE_BATCH_WAY_OUT = ("To correct several records, remove them in one call (`--remove "
                          "\"<prefix>\"` repeats, all or nothing), then write the new lines in a "
                          "second (`--lines-from <file>`, or one `--line` each).")


def _resolve_heading(heading: str) -> tuple[str, str | None]:
    """`(canonical heading, complaint)`. Matching is the same case/space-tolerant rule the readers
    use, so a record written here is a record they will find."""
    want = heading.strip().lower()
    for known in KNOWN_HEADINGS:
        if known.strip().lower() == want:
            return known, None
    return heading.strip(), (
        f"'{heading}' is not a heading any check reads, so a line under it silences nothing. "
        f"Known: {', '.join(KNOWN_HEADINGS)}")


def append_line(m: ProjectModel, heading: str, line: str,
                replace_prefix: str = "") -> tuple[bool, str]:
    """Append (or replace) one recorded line. Returns `(changed, message)`.

    `replace_prefix` rewrites the existing line that starts with it — the supported way to correct a
    record whose facts moved, instead of a hand-rolled `body.find()` + slice."""
    line = line.strip()
    section = next((x for x in m.extras if x.heading.strip().lower() == heading.strip().lower()),
                   None)
    if section is None:
        section = ExtraSection(heading=heading, body="")
        m.extras.append(section)
    lines = [ln for ln in section.body.splitlines()]
    if replace_prefix:
        hit = next((i for i, ln in enumerate(lines)
                    if ln.strip().lstrip("-* ").startswith(replace_prefix)), None)
        if hit is None:
            return False, (f"no existing line under '{heading}' starts with "
                           f"'{replace_prefix}' — nothing replaced")
        old = lines[hit]
        lines[hit] = line
        section.body = "\n".join(lines).strip() + "\n"
        return True, f"replaced under '{heading}':\n  - {old.strip()}\n  + {line}"
    if any(ln.strip() == line for ln in lines):
        return False, f"already recorded under '{heading}' — nothing to do"
    lines.append(line)
    section.body = "\n".join(ln for ln in lines if ln.strip()).strip() + "\n"
    return True, f"recorded under '{heading}': {line}"


def remove_line(m: ProjectModel, heading: str, prefix: str) -> tuple[bool, str]:
    """Delete the recorded line under `heading` that starts with `prefix`.

    A record can go STALE: one build recorded a sweep-debt line, then ten turns later wrote a
    business rule covering the same anchor, so the record now silenced a step the map claims. There
    was `--replace` and no way to remove, so the deletion went out as a `python3 - <<'PY'` splice of
    `extras.json` — the hand-rolled JSON append this command exists to end, wearing the other
    direction. Removing the whole section when its last line goes is deliberate: an empty heading
    still reads as "an exception was recorded here"."""
    section = next((x for x in m.extras if x.heading.strip().lower() == heading.strip().lower()),
                   None)
    if section is None:
        return False, f"no '{heading}' heading — nothing removed"
    lines = section.body.splitlines()
    hit = next((i for i, ln in enumerate(lines)
                if ln.strip().lstrip("-* ").startswith(prefix)), None)
    if hit is None:
        return False, (f"no existing line under '{heading}' starts with '{prefix}' "
                       f"— nothing removed")
    gone = lines.pop(hit)
    kept = [ln for ln in lines if ln.strip()]
    if kept:
        section.body = "\n".join(kept).strip() + "\n"
    else:
        m.extras.remove(section)
        return True, (f"removed under '{heading}': {gone.strip()}\n"
                      f"  (that was its last line, so the heading is gone too)")
    return True, f"removed under '{heading}': {gone.strip()}"


#: The headings whose new lines are tried against what `validate` reports. Derived from the registry:
#: keyed on FREE TEXT, so no key grammar can call a line malformed (the 2026-09-30 mcpolis build
#: stored 6 comma-listed 'Sweep debt' lines, exit 0, that silenced nothing), and MAINTENANCE, so a
#: line exists to answer a finding. A note ('Entry-point coverage', 'Bucket vocabulary') answers
#: none, so silencing nothing is no defect there. 'Drift exceptions' is left out by name: its
#: reader is `anchor-drift`, which `validate` never runs, and which names its own unmatched lines.
LIVE_CHECKED: frozenset[str] = frozenset(
    h.heading for h in records.HEADINGS
    if h.maintenance and h.key is None and h.heading != DRIFT_EXCEPTIONS_HEADING)

#: A `path:line` anchor, to say "one line per anchor" when a refused key holds several.
_ANCHOR = re.compile(r"[\w./-]+:\d+")


def assembled_beside(path: Path, present: frozenset[str] | None) -> Path | None:
    """The assembled map `path` feeds: the map itself, or `.coyomap/project-map.json` beside the
    `build-fragments/` folder that holds a fragment. None when there is none to try a line on."""
    if present is None:
        return path
    if path.parent.name == "build-fragments":
        found = path.parent.parent / "project-map.json"
        return found if found.is_file() else None
    return None


def fragments_beside(assembled: Path) -> Path | None:
    """The folder the next `assemble` rebuilds the map at `assembled` from: `build-fragments/` in the
    map's own folder, the reverse of `assembled_beside`, once it holds any fragment (`*.json`). None
    when it holds none, as for a map edited directly with no fragments.

    ANY fragment, not the extras one. Nothing creates `extras.json` before the first record, so a
    refusal keyed on it let `record` write the assembled map between the first assemble and the
    first record, exit 0, and lose the line at the next assemble (the review of the 2026-10-07
    fixes)."""
    folder = assembled.parent / "build-fragments"
    return folder if folder.is_dir() and any(folder.glob("*.json")) else None


def inert_lines(assembled: ProjectModel, map_path: Path, heading: str, lines: list[str],
                replace_prefix: str = "") -> list[str]:
    """The new lines that, ON ITS OWN, each change nothing `validate` reports on `assembled`.

    A line is tried alone against the map without it, never against the batch, so two lines that
    answer the same finding are both kept. `--replace` drops the line it replaces first, so the new
    wording is tried the same way. Both `validate` answers are compared whole, problems and
    advisories, exactly as `_records_disclosure` compares them to say what the records silenced."""
    base = dataclasses.replace(assembled,
                               extras=[dataclasses.replace(x) for x in assembled.extras])
    if replace_prefix:
        remove_line(base, heading, replace_prefix)
    before = _findings(base, map_path)
    inert: list[str] = []
    for ln in lines:
        trial = dataclasses.replace(base, extras=[dataclasses.replace(x) for x in base.extras])
        append_line(trial, heading, ln)
        if _findings(trial, map_path) == before:
            inert.append(ln)
    return inert


def _findings(m: ProjectModel, map_path: Path) -> list[str]:
    """What `validate` reports on `m`, problems and advisories tagged in one list, its readability
    report aside. That report reads every recorded line's reason, so a line with an em dash or a
    25-word why changed the output by its own words and was kept though it silenced nothing: the
    review got four such lines past this check on the real map."""
    problems, warnings = validate_model(m, map_path, disclose_records=False, model_is_edited=True)
    readability = set(prose.advisory_lines(m))
    return ([f"problem: {p}" for p in problems]
            + [f"advisory: {w}" for w in warnings if w not in readability])


def _inert_reason(line: str, heading: str, map_path: Path) -> str:
    key = line.split(": ", 1)[0]
    anchors = _ANCHOR.findall(key)
    many = (f" Its key names {len(anchors)} anchors, and the reader matches a key WHOLE: write "
            f"one line per anchor." if len(anchors) > 1 else "")
    return (f"'{line}' changes nothing `validate` reports on {map_path}, so under '{heading}' it "
            f"would silence nothing.{many} The key must be exactly what a finding names. If the "
            f"fragments changed since the last assemble, assemble first and record again.")


def echo_access_claims(path: Path, recorded: list[str], baseline: Path | None) -> None:
    """For each path just recorded under 'Access baseline exceptions', the lines that held access
    there in the previous map, and never what that map said about them.

    Said at the moment of writing, which is where the 2026-09-30 mcpolis build went wrong: 11
    reasons were written from the NEW map without opening one file. The old claim's TEXT is not
    echoed: a build records these after its last fact-check wave, and on the 2026-10-08 mcpolis
    build old text printed there became three new rules no skeptic read (`AccessClaim`)."""
    base_path = baseline or baseline_beside(path)
    if base_path is None:
        print("note: no archived map beside this one, so the lines each path held cannot be shown; "
              "pass --access-baseline <the previous map> to see them")
        return
    try:
        base = load_claims(base_path)
    except Exception as exc:                       # noqa: BLE001 — any unreadable baseline is one case
        print(f"note: {base_path} could not be read ({exc}), so the lines each path held cannot "
              f"be shown")
        return
    where = f"{base_path.parent.name}/{base_path.name}"
    for ln in recorded:
        for key in records.line_keys(ACCESS_BASELINE_EXCEPTIONS_HEADING, ln):
            claims = base.get(key)
            if claims:
                print(f"  {where_lines(key, claims)} held access in {where}. The why must say what "
                      f"the code at those lines does now: open them before you keep this line.")
            else:
                print(f"  {key} held no access claim in {where}, so this line excuses nothing "
                      f"there.")


def _arg(argv: list[str], flag: str, default: str = "") -> str:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def _all_args(argv: list[str], flag: str) -> list[str]:
    """EVERY value given to `flag`, in order — not just the first.

    `_arg` reads one, and this command takes one record per process as a result: a build that had 57
    lines to record spawned 57 processes, twenty of them re-typing long prose after a failed first
    attempt. The lines are independent appends under one heading, so there was never a reason for
    them to be separate runs."""
    out: list[str] = []
    for i, a in enumerate(argv):
        if a == flag and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            out.append(argv[i + 1])
    return out


def _argument_errors(argv: list[str]) -> list[str]:
    """Every argument `_arg` and `_all_args` would drop without a word: a positional, an unknown
    option, a flag with no value, and a one-value flag given twice (`_arg` reads the first).

    Walked the way those two read the line, so a token is a flag's value here exactly when it is
    one there. The positional is the case that cost a record: `--map` fell back to its default, the
    assembled map, and the line went there instead of the fragment the caller had named."""
    errors: list[str] = []
    counts: dict[str, int] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in _VALUE_FLAGS:
            counts[a] = counts.get(a, 0) + 1
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            if nxt is None or (a in _REPEATED_FLAGS and nxt.startswith("--")):
                errors.append(f"{a} needs a value")
                i += 1
                continue
            i += 2
            continue
        if a.startswith("-") and a != "-" and a not in _BARE_FLAGS:
            errors.append(f"unknown option '{a}'. Known: {', '.join(_VALUE_FLAGS)}, "
                          f"--headings, --no-reassemble")
        elif a not in _BARE_FLAGS:
            # Named for the file it most likely is: what turn 758 passed was the fragment to write.
            hint = (f" To write {a}, pass `--map {a}`." if a.endswith(".json")
                    else " A value with spaces needs quotes.")
            errors.append(f"'{a}' is a positional argument, and `record` takes none: it writes only "
                          f"the file --map names, which defaults to the assembled map.{hint}")
        i += 1
    errors += [f"{flag} is given {n} times; it takes one value"
               for flag, n in counts.items() if n > 1 and flag not in _REPEATED_FLAGS]
    return errors


def _undecodable_refused(values: list[str]) -> bool:
    """One error for each value holding a byte that is not UTF-8; True when there was any."""
    for value in values:
        print(f"ERROR: {value!r} holds a byte that is not UTF-8, which no fragment can hold. Type it "
              f"again in UTF-8; nothing was written.", file=sys.stderr)
    return bool(values)


def state_text(argv: list[str], written: Path, heading: str, change: str) -> str:
    """The build-state line of one write: what changed, under which heading, in which file (`written`,
    relative to the repo), and the command as typed, with each record's text cut to its first
    `_TEXT_KEPT` characters. Quoted by `shlex`, so the command reads back as the same words.

    The FILE is the point. A lead whose context was replaced by a summary recorded into the
    assembled map instead of the fragment, because the summary had kept the command's gist and
    dropped its `--map`; this line is where that flag survives."""
    words = ["coyomap", "record"]
    cut_next = False
    for arg in argv:
        words.append(clip(arg, _TEXT_KEPT - 1) if cut_next else arg)
        cut_next = arg in _TEXT_FLAGS
    return f'{change} under "{heading}" → {written} · {shlex.join(words)}'


def _write_event(argv: list[str], path: Path, heading: str, change: str) -> None:
    """One `record` line in the build state of the repo `path` belongs to, if it has one open."""
    repo = buildstate.repo_of(path)
    if repo is not None:
        written = path.resolve().relative_to(repo)
        buildstate.append(repo, "record", state_text(argv, written, heading, change))


def _print_headings() -> int:
    """Which headings read a comma list, and which key on free text.

    `--help` recommends merging one reason onto one line, which is right for the families with a key
    grammar and destroys the record on the families without one. That distinction lived only in a
    module comment, so a build followed the advice under `Sweep debt`, silenced 0 of 5 anchors, and
    spent two rounds finding out."""
    from coyomap import records
    specs = [(h, records.spec_of(h)) for h in records.KNOWN_HEADINGS]
    listed = [h for h, sp in specs if sp is not None and sp.key]
    free = [h for h, sp in specs if sp is None or not sp.key]
    print("Headings whose lines take a COMMA LIST of keys — one reason may answer several:")
    for h in listed:
        print(f"  {h}")
    print("\nHeadings keyed on FREE TEXT — one record per line, because the reader matches the")
    print("whole key and a comma list matches nothing:")
    for h in free:
        print(f"  {h}")
    return 0


def _load_target(path: Path) -> tuple[ProjectModel, frozenset[str] | None] | None:
    """The map or fragment at `path` and its own key set (None for an assembled map), or None once
    the reason it cannot be read is printed."""
    try:
        return load_map_or_fragment(path)
    except Exception as exc:                      # noqa: BLE001 — any unreadable target is one case
        print(f"ERROR: {exc}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or "-h" in argv or "--help" in argv:
        print(USAGE)
        return 0
    # Every argument is read or refused, before anything else (see `_argument_errors`).
    bad_args = _argument_errors(argv)
    if bad_args:
        for err in bad_args:
            print(f"ERROR: {err}", file=sys.stderr)
        return 2
    if "--headings" in argv:
        return _print_headings()
    map_path = _arg(argv, "--map", ".coyomap/project-map.json")
    heading = _arg(argv, "--heading")
    lines = _all_args(argv, "--line")
    from_file = _arg(argv, "--lines-from")
    replace = _arg(argv, "--replace")
    # EVERY `--remove`, not the first: `--remove A --remove B` removed A, kept B, and said nothing.
    removes = _all_args(argv, "--remove")
    remove = removes[0] if removes else ""
    baseline_arg = _arg(argv, "--access-baseline")
    no_reassemble = "--no-reassemble" in argv
    # The TARGET is checked before the payload. A build ran 21 well-formed `record` calls in one turn
    # and every one failed with `cannot read … extras.json — no such file`, because no fan-out agent
    # owns creating that fragment; the build worked around it with `echo '{"extras": []}' >`, which is
    # the hand-rolled write this command exists to replace. Probing the failure with a malformed line
    # reported the ARGUMENT complaint first and hid the real cause entirely.
    path = Path(map_path)
    seed_extras = False
    loaded: tuple[ProjectModel, frozenset[str] | None] | None = None
    # The fragments the assembled map at `path` is rebuilt from; None for a fragment, or for a map
    # with none beside it. The refusal below and the closing `wrote` line both read this one answer.
    fragments: Path | None = None
    if path.exists():
        loaded = _load_target(path)
        if loaded is None:
            return 2
        # THE ASSEMBLED MAP, WHILE ITS FRAGMENTS ARE BESIDE IT, is refused: the next `assemble`
        # rebuilds the map from them and drops the line. Writing it anyway with a warning on the
        # LAST line of the output was how a record was lost: the lead read that output through
        # `tail -2`, the exit was 0, and `ship`'s own assemble discarded the line two steps later.
        fragments = fragments_beside(path) if loaded[1] is None else None
        if fragments is not None and not no_reassemble:
            extras = fragments / "extras.json"
            seeds = "" if extras.is_file() else " (it does not exist yet, and that call seeds it)"
            print(f"ERROR: {path} is the ASSEMBLED map, and its build fragments sit beside it in "
                  f"{fragments}: the next `assemble` rebuilds the map from them and drops this "
                  f"edit. Record into the extras fragment: `--map {extras}`{seeds}. Only if "
                  f"nothing will assemble this map again (the build is over, and an update changes "
                  f"the map directly) pass --no-reassemble to write the map anyway.",
                  file=sys.stderr)
            return 2
        # A FRAGMENT WITH NO `extras` KEY cannot carry a record: `dump_preserving` writes back only
        # the keys the fragment had, so the line was printed as "recorded", the file as "wrote", and
        # the line was gone. Refused before anything changes.
        if not remove and loaded[1] is not None and "extras" not in loaded[1]:
            print(f"ERROR: {path} has no `extras` section, so a line written here would be dropped "
                  f"when the fragment is saved. Record into the fragment that owns the extras (an "
                  f"`extras.json` in the same folder is seeded when it is missing).", file=sys.stderr)
            return 2
    else:
        # Seeded, not blindly created: only an `extras.json` inside an existing directory, which is
        # the one file a build is told to record into and the one nothing else creates. Any other
        # missing path is a typo, and silently creating it would hide the typo — the direction that
        # costs an operator an hour.
        if path.name == "extras.json" and path.parent.is_dir() and not remove:
            # Deferred until the arguments are known good: seeding here left a stray
            # `{"extras": []}` fragment behind every time a call exited 2 on a malformed --line.
            seed_extras = True
        else:
            print(f"ERROR: cannot read {path} — no such file. (An `extras.json` in an existing "
                  f"directory is seeded automatically; any other path must exist.)", file=sys.stderr)
            return 2
    if from_file:
        if replace:
            # --replace corrects ONE record by prefix; a file of lines has no single target, and
            # guessing which one it meant is the kind of silent mis-write this command exists to
            # prevent.
            print(f"ERROR: --replace corrects one record and --lines-from carries many. "
                  f"{_REPLACE_BATCH_WAY_OUT}", file=sys.stderr)
            return 2
        src = Path("/dev/stdin") if from_file == "-" else Path(from_file)
        try:
            text = sys.stdin.read() if from_file == "-" else src.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"ERROR: cannot read --lines-from {from_file}: {exc}", file=sys.stderr)
            return 2
        # Blank lines and `#` comments dropped, so the file a lead pastes together can be annotated.
        lines += [ln.strip() for ln in text.splitlines()
                  if ln.strip() and not ln.lstrip().startswith("#")]
    # A BYTE THE SHELL COULD NOT DECODE, in text bound for the fragment, is refused before anything
    # is written: the fragment's write opens the file, which empties it, and only then fails to
    # encode the line. One such `--line` emptied a fragment, every record it held with it, and
    # ended in a traceback.
    if _undecodable_refused([t for t in (heading, *lines, *removes, replace)
                             if t and undecodable(t)]):
        return 2
    if remove:
        if lines or from_file or replace:
            print("ERROR: --remove deletes records and takes no --line / --lines-from / "
                  "--replace — do the removal in its own call.", file=sys.stderr)
            return 2
        if not heading:
            print("ERROR: --remove needs --heading", file=sys.stderr)
            return 2
    elif not heading or not lines:
        print("ERROR: --heading and at least one --line (or --lines-from) are required",
              file=sys.stderr)
        return 2
    if replace and len(lines) > 1:
        print(f"ERROR: --replace corrects one record; {len(lines)} --line values were given. "
              f"{_REPLACE_BATCH_WAY_OUT}", file=sys.stderr)
        return 2
    # A key with no why is a dismissal, not a record — the rule every escape family already states.
    # Checked for EVERY line before anything is written: a partial append would leave the fragment
    # holding some of a batch, and the caller cannot tell which without re-reading it.
    for bad in [] if remove else [ln for ln in lines
                                 if ":" not in ln or not ln.split(":", 1)[1].strip()]:
        print(f"ERROR: a record is `<id or claim>: <why>` — '{bad}' states no why. A key alone is "
              f"a dismissal, and the point of recording is that the reason survives.", file=sys.stderr)
        return 2
    canonical, complaint = _resolve_heading(heading)
    if complaint:
        print(f"ERROR: {complaint}", file=sys.stderr)
        return 2
    # A WHY WITH A SENTENCE OVER THE WORD LIMIT is refused, every line checked before anything is
    # written. The viewer shows the why, and the readability check counts it: on the 2026-10-08
    # mcpolis map 20 of the 34 long sentences were recorded lines, and this command had let every
    # one of them in. The same splitter and counter as that check (`records.why_of`, then
    # `prose.long_sentences`), so a line accepted here is never a long sentence there.
    long_whys = [] if remove else [(ln, s) for ln in lines
                                   for s in prose.long_sentences(records.why_of(canonical, ln))]
    if long_whys:
        for ln, sentence in long_whys:
            print(f"ERROR: a sentence of {prose.word_count(sentence)} words, over the "
                  f"{prose.SENTENCE_WORD_LIMIT}-word limit, in the why of '{clip(ln, 60)}': "
                  f"\"{sentence}\"", file=sys.stderr)
        print(f"REFUSED: split each sentence above into shorter ones (one idea per sentence). "
              f"None of the {len(lines)} line(s) was written.", file=sys.stderr)
        return 2
    if seed_extras:
        path.write_text('{\n  "extras": []\n}\n', encoding="utf-8")
        print(f"note: seeded {path} — nothing else creates the extras fragment, and a record had "
              f"nowhere to go.")
        loaded = _load_target(path)
    if loaded is None:
        return 2
    m, present = loaded
    any_changed = False
    appended: list[str] = []
    # What each line did, printed only once the write is certain. Printed as it happened, a refused
    # batch read "recorded under …" above "REFUSED … Nothing was written".
    said: list[str] = []
    if remove:
        # All or nothing, like a batch of `--line`: the removals run on the model in memory, and a
        # prefix that matches nothing stops the write before any of them lands on disk.
        for prefix in removes:
            changed, message = remove_line(m, canonical, prefix)
            if not changed:
                print(message)
                print(f"REFUSED: '{prefix}' matched no line under '{canonical}', so none of the "
                      f"{len(removes)} removal(s) was written.", file=sys.stderr)
                return 1
            said.append(message)
            any_changed = True
    else:
        for ln in lines:
            changed, message = append_line(m, canonical, ln, replace)
            said.append(message)
            any_changed = any_changed or changed
            if changed:
                appended.append(ln)
    if not any_changed:
        print("\n".join(said))
        return 1 if replace else 0
    # SHAPE-CHECK BEFORE WRITING: a line that keys to nothing silences nothing, silently.
    #
    # This command checked the heading and that the line carried a `:` with a why, and stopped
    # there. A live build wrote `read-before-create HP2, read-before-create HP3, …` — the check
    # name repeated inside the comma list, where the family's grammar is the name ONCE then bare
    # ids — and the line keyed zero ids. Unrecorded advisories went 1 to 9, and three extra
    # `finalize` + `render` rounds were spent finding the shape by trial. `malformed_records`
    # already knows every family's key vocabulary and was already used by the validator; asking it
    # here turns those three rounds into one refusal.
    # Only the lines THIS call added. A fragment may already carry a record written before the
    # check existed, and refusing to write a good line because an old one is malformed would make
    # the command unusable on exactly the maps that need it most.
    added = {ln.strip() for ln in lines}
    bad = [b for b in records.malformed_records(m, canonical) if b.strip() in added]
    if bad and not remove:
        for b in bad:
            print(f"ERROR: {b}", file=sys.stderr)
        print(f"REFUSED: the line(s) above adjudicate nothing under '{canonical}', so recording "
              f"them would silence no finding while reading as though it had. Nothing was "
              f"written.", file=sys.stderr)
        return 1
    # A FREE-TEXT KEY IS TRIED, NOT PARSED. No grammar can tell `a.py:1, b.py:2` from one anchor,
    # so each new line goes onto the assembled map beside the fragment and `validate` says whether
    # it silences anything. Skipped, and said, when no assembled map can be found or read.
    if appended and canonical in LIVE_CHECKED:
        target = assembled_beside(path, present)
        if target is None:
            print(f"note: no assembled map beside {path}, so the line(s) under '{canonical}' were "
                  f"not tried against what `validate` reports")
        else:
            try:
                inert = inert_lines(load_model_path(target), target, canonical, appended, replace)
            except Exception as exc:              # noqa: BLE001 — any unreadable map is one case
                print(f"note: {target} could not be checked ({exc}), so the line(s) under "
                      f"'{canonical}' were not tried against what `validate` reports")
                inert = []
            if inert:
                for ln in inert:
                    print(f"ERROR: {_inert_reason(ln, canonical, target)}", file=sys.stderr)
                print(f"REFUSED: {len(inert)} of {len(appended)} line(s) would silence nothing. "
                      f"Nothing was written.", file=sys.stderr)
                return 1
    # ONE write for the whole batch. Writing per line would leave the file half-updated if a later
    # line failed, and would rewrite the fragment N times for N records.
    print("\n".join(said))
    path.write_text(dump_preserving(m, present), encoding="utf-8")
    _write_event(argv, path, canonical, f"-{len(removes)}" if remove else f"+{len(appended)}")
    if fragments is None:
        # A fragment, or a map with no fragments to rebuild it from: the edit is where it lands.
        print(f"wrote {path}")
    else:
        # Only `--no-reassemble` gets here: without it, the assembled map was refused above.
        print(f"wrote {path} — the assembled map, as --no-reassemble asks: an `assemble` from "
              f"{fragments} would drop this edit.")
    if canonical == ACCESS_BASELINE_EXCEPTIONS_HEADING and not remove:
        echo_access_claims(path, lines, Path(baseline_arg) if baseline_arg else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
