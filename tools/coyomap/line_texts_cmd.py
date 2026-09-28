"""`coyomap line-texts` — the four steps around the Architecture picture's merged texts.

The texts themselves, and why each rule exists, are `line_texts`'s; this module only reads the map,
asks the viewer's own generator which lines it draws, and runs one step. The lines come from
`gen_arch_views`, the function that draws the pictures, so the lines an agent writes for are the
lines a reader sees, key for key.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from coyomap import line_texts, subverb_help
from coyomap.impact_git import load_map_extents
from coyomap.line_texts import Line
from coyomap.model import ModelError, load_model, resolve_map_path
from coyomap.viewer.build_graph import GraphDict
from coyomap.viewer.gen_viewer import gen_arch_views, has_grouping
from coyomap.views import model_to_graph

USAGE = """usage: coyomap line-texts <verb> [options]

One merged sentence for each line of the Architecture pictures that several stories take. method.md
runs these at the end of a build (the closing sequence, step 5b) and change-impact.md at step 7 of
an update.

  pending [--map <map>] --out <file> [--all]
      Every line the pictures draw with two or more different sentences and no merged text yet, as
      a JSON list of {key, from, to, sentences}, plus `drawn_as` when the line joins other boxes on
      another picture. The file the `line-texts` agent reads. An empty list means there is nothing
      to write: skip both agents. --all lists the lines that have a text too.
  lint --lines <file> <texts>
      The writer's own check before it returns: one text per line in <file>, none extra, and each
      one inside the rules no reader is needed for (one sentence, at most 20 words, no dash, no
      semicolon, no "then" between stories, no opening "It" or "This", no code-shaped word its
      sentences do not use). Exit 1 on any fault.
  check-input --lines <file> --texts <texts> --out <file>
      The file the `line-texts-check` agent reads: each line's sentences beside its merged text. A
      text lint faults is left out, and named: it cannot be kept anyway.
  record --texts <texts> --verdicts <verdicts> [--map <map>]
      Keep every text the check passed and lint does not fault, in line-texts.json beside the map.
      A text whose line the pictures no longer draw is dropped from the file. A line with no kept
      text shows its stories' own sentences, as before. A key <texts> names ends with this run's
      outcome, whatever was kept for it before.

  To re-check the kept texts (the check's rules changed): `pending --all --out <lines>`, then
  `check-input --lines <lines> --texts <map folder>/line-texts.json --out <file>`, a fresh checker,
  and `record --texts <map folder>/line-texts.json --verdicts <its verdicts>`.

  --map   the map (default: .coyomap/project-map.json)
"""


def _map_graph(map_arg: str | None) -> tuple[Path, GraphDict]:
    """The map's folder, and the graph the viewer draws from it, built the way `serve` builds it."""
    resolved = resolve_map_path(map_arg or ".coyomap/project-map.json")
    model = load_model(resolved.read_text(encoding="utf-8"))
    return resolved.parent, model_to_graph(model, load_map_extents(resolved))


def drawn_lines(graph: GraphDict) -> list[Line]:
    """Every line any Architecture picture draws that wants a merged text, once per key, in the
    order the pictures are drawn. A map without subsystems draws no Architecture picture at all."""
    if not has_grouping(graph):
        return []
    return lines_of_pictures(gen_arch_views(graph)[1])


def lines_of_pictures(texts: dict[str, dict[str, Any]]) -> list[Line]:
    """The lines of the pictures' texts (`gen_arch_views`), once per key, with every pair of boxes
    each key is drawn between."""
    first: dict[str, Line] = {}
    ends: dict[str, dict[tuple[str, str], None]] = {}
    for picture in texts.values():
        for entry in picture.get("lines") or []:
            said = [str(x.get("text") or "") for x in entry.get("sentences") or []]
            if not line_texts.wants_text(said):
                continue
            key = line_texts.line_key(said)
            pair = (str(entry.get("src") or ""), str(entry.get("dst") or ""))
            ends.setdefault(key, {})[pair] = None
            if key not in first:
                first[key] = Line(key=key, src=pair[0], dst=pair[1],
                                  sentences=tuple(dict.fromkeys(s for s in said if s)))
    return [replace(ln, drawn_as=tuple(ends[ln.key])) for ln in first.values()]


def _write_json(path: str, data: object) -> None:
    Path(path).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_pending(args: argparse.Namespace) -> int:
    folder, graph = _map_graph(args.map)
    lines = drawn_lines(graph)
    have = {} if args.all else line_texts.load(folder)
    pending = [ln for ln in lines if ln.key not in have]
    _write_json(args.out, [ln.to_json() for ln in pending])
    if not pending:
        print(f"line-texts: nothing to write: all {len(lines)} lines with two or more sentences "
              f"have a merged text -> {args.out} (an empty list; skip both agents)")
    else:
        print(f"line-texts: {len(pending)} of {len(lines)} lines with two or more sentences need a "
              f"merged text -> {args.out}")
    return 0


def _print_faults(faults: dict[str, list[str]]) -> None:
    for key, found in faults.items():
        print(f"  {key}: {'; '.join(found)}")


def cmd_lint(args: argparse.Namespace) -> int:
    lines = line_texts.read_lines(Path(args.lines))
    faults = line_texts.lint(lines, line_texts.read_texts(Path(args.texts)))
    if not faults:
        print(f"line-texts lint: clean, {len(lines)} texts")
        return 0
    print(f"line-texts lint: {len(faults)} of {len(lines)} lines have a fault. Fix each and run "
          f"this again:")
    _print_faults(faults)
    return 1


def cmd_check_input(args: argparse.Namespace) -> int:
    lines = line_texts.read_lines(Path(args.lines))
    texts = line_texts.read_texts(Path(args.texts))
    faults = line_texts.lint(lines, texts)
    rows = [{**ln.to_json(), "merged": texts[ln.key].strip()} for ln in lines
            if ln.key in texts and ln.key not in faults]
    _write_json(args.out, rows)
    print(f"line-texts: {len(rows)} texts to check -> {args.out}")
    if faults:
        print(f"  left out, because lint faults them ({len(faults)}); they cannot be kept:")
        _print_faults(faults)
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    folder, graph = _map_graph(args.map)
    lines = drawn_lines(graph)
    old = line_texts.load(folder)
    choice = line_texts.choose(lines, old, line_texts.read_texts(Path(args.texts)),
                               line_texts.read_verdicts(Path(args.verdicts)))
    # No file, and nothing to put in one: a map whose pictures draw no line several stories take
    # gets no empty file beside it.
    exists = (folder / line_texts.FILE_NAME).exists()
    path = line_texts.save(folder, choice.kept) if (choice.kept or exists) else None
    print(f"line-texts: kept {len(choice.new)} new texts -> {path or 'no file written'}. "
          f"{len(choice.kept)} of "
          f"{len(lines)} lines with two or more sentences have one; the other "
          f"{len(lines) - len(choice.kept)} show their stories' own sentences.")
    if choice.rejected:
        print(f"  rejected by the check ({len(choice.rejected)}):")
        _print_faults(choice.rejected)
    if choice.faulty:
        print(f"  faulted by lint ({len(choice.faulty)}):")
        _print_faults(choice.faulty)
    if choice.unchecked:
        print(f"  no verdict, so not kept ({len(choice.unchecked)}): {', '.join(choice.unchecked)}")
    if choice.unknown:
        print(f"  for no line the pictures draw ({len(choice.unknown)}): {', '.join(choice.unknown)}")
    if choice.dropped:
        print(f"  dropped, because their line is no longer drawn: {len(choice.dropped)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coyomap line-texts", add_help=False)
    sub = parser.add_subparsers(dest="verb")

    pending = sub.add_parser("pending", add_help=False)
    pending.add_argument("--map", default=None)
    pending.add_argument("--out", required=True)
    pending.add_argument("--all", action="store_true")
    pending.set_defaults(func=cmd_pending)

    lint = sub.add_parser("lint", add_help=False)
    lint.add_argument("--lines", required=True)
    lint.add_argument("texts")
    lint.set_defaults(func=cmd_lint)

    check = sub.add_parser("check-input", add_help=False)
    check.add_argument("--lines", required=True)
    check.add_argument("--texts", required=True)
    check.add_argument("--out", required=True)
    check.set_defaults(func=cmd_check_input)

    record = sub.add_parser("record", add_help=False)
    record.add_argument("--map", default=None)
    record.add_argument("--texts", required=True)
    record.add_argument("--verdicts", required=True)
    record.set_defaults(func=cmd_record)
    return parser


VERBS = ("pending", "lint", "check-input", "record")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if args else 2
    if args[0] not in VERBS:
        print(f"coyomap line-texts: unknown verb '{args[0]}'\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    helped = subverb_help.handle(USAGE, args[0], args[1:])
    if helped is not None:
        return helped
    parsed = build_parser().parse_args(args)
    try:
        return int(parsed.func(parsed))
    except (OSError, ValueError, ModelError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
