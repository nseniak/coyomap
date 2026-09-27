"""The Architecture picture's merged texts: ONE sentence for a line that several stories take.

WHY THEY EXIST. The picture merges a feature's stories into one flow over the product's boxes, so a
line between two boxes carries one step sentence per story that takes it. On mcpolis's All picture,
62 of 113 lines carried two or more, and 106 sentences sat behind "+N more": a reader saw two of a
line's actions and had to open a fold for the rest. One sentence that covers them all reads in about
the time one sentence does, and each story's own sentence stays one click away under it.

WHO WRITES THEM, AND WHO CHECKS. An agent writes them at the end of a build or an update (the
`line-texts` contract), and a FRESH agent reads each one beside the sentences it stands for
(`line-texts-check`). Nothing else can check them: a skeptic checks a claim against its code line,
and a merged text has no code line, only the sentences it restates. So a merged text is right when it
says what its sentences say, no more and no less. A trial on 96 lines found 4 wrong: 2 gave an action
an object its sentence did not name, 2 dropped a sentence from a long line. `choose` keeps a text only
when the check passed it AND it passes `text_faults`, the rules no reader is needed for.

WHERE THEY LIVE. `.coyomap/line-texts.json`, `{key: text}`, beside the map and committed with it.
The key is the line's distinct sentences, sorted and hashed:
  * a line with the same sentences on two pictures shares one text;
  * a line whose sentences change gets a new key, so a text is never shown beside sentences it was
    not written for: the stale one is simply never looked up, and `choose` drops it.
NOT a field of the map model. The text restates the model's own sentences, the way a view does; as a
field it would put presentation text into every update's diff, and every gate that reads the model
would have to learn to ignore it.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from coyomap import prose

FILE_NAME = "line-texts.json"

#: Hex digits of the key. The map with the most lines today has 96 that need a text, so twelve
#: digits leave no collision worth guarding.
KEY_DIGITS = 12

#: The check's verdict word for a text it passed (`line-texts-check`). Anything else keeps nothing.
VERDICT_OK = "ok"

#: A dash inside a merged text: the em dash, the en dash, and a hyphen standing alone between words.
_DASHES: tuple[str, ...] = ("—", "–", " - ")
_THEN = re.compile(r"\bthen\b", re.IGNORECASE)


def wants_text(sentences: Iterable[str]) -> bool:
    """True for a line that carries two or more DIFFERENT sentences: the lines a merged text is for.
    A line every story says the same way already reads as one sentence."""
    return len({s for s in sentences if s}) > 1


def line_key(sentences: Iterable[str]) -> str:
    """The key a line's merged text is stored under: its distinct sentences, sorted, then hashed."""
    joined = "\n".join(sorted({s for s in sentences if s}))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:KEY_DIGITS]


def text_for(texts: Mapping[str, str], sentences: Iterable[str]) -> str:
    """The merged text a line shows, or "" when it has none or needs none."""
    said = list(sentences)
    return texts.get(line_key(said), "") if wants_text(said) else ""


def load(folder: Path) -> dict[str, str]:
    """The kept texts beside a map: `{}` when the file is absent. A file that is not a JSON object
    of strings raises ValueError, naming the file: a half-written file must not read as "no texts",
    or `choose` would write the half back as the whole."""
    path = folder / FILE_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not JSON: {exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                             for k, v in data.items()):
        raise ValueError(f"{path} must be one JSON object of key to text")
    return dict(data)


def save(folder: Path, texts: Mapping[str, str]) -> Path:
    """Write the kept texts beside the map, sorted by key so a rewrite changes only what changed."""
    path = folder / FILE_NAME
    path.write_text(json.dumps(dict(sorted(texts.items())), indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def text_faults(text: str, sentences: Iterable[str]) -> list[str]:
    """What is wrong with one merged text by the rules no reader is needed for, one phrase each.

    A word or a mark the line's own sentences already carry is not held against the text: "then"
    inside one story's sentence is that story's own order, and a code-shaped name a sentence uses is
    the map's word for it, not the writer's slip. The word limit and the opening pointer are
    `prose`'s, so this check and the readability check can never disagree on what they count."""
    body = text.strip()
    if not body:
        return ["no text"]
    said = " ".join(sentences)
    faults: list[str] = []
    if len(prose.sentences(body)) > 1:
        faults.append("more than one sentence")
    words = prose.word_count(body)
    if words > prose.SENTENCE_WORD_LIMIT:
        faults.append(f"{words} words, over {prose.SENTENCE_WORD_LIMIT}")
    if any(d in body and d not in said for d in _DASHES):
        faults.append("a dash")
    if ";" in body and ";" not in said:
        faults.append("a semicolon")
    if _THEN.search(body) and not _THEN.search(said):
        faults.append('"then" between stories, which are alternatives: join them with "or"')
    pointer = prose.opens_with_bare_pointer(body)
    if pointer:
        faults.append(f'opens with "{pointer}"')
    code = [t for t in prose.code_tokens(body) if t not in said]
    if code:
        faults.append("code-shaped words its sentences do not use: " + ", ".join(code[:3]))
    return faults


@dataclass(frozen=True)
class Line:
    """One line of an Architecture picture that needs a merged text: its key, its two boxes by name,
    and its distinct sentences. `from` and `to` are what the agents read, so that is the JSON."""

    key: str
    src: str
    dst: str
    sentences: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {"key": self.key, "from": self.src, "to": self.dst, "sentences": list(self.sentences)}


def read_lines(path: Path) -> list[Line]:
    """The lines file `pending` wrote, read back."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must be a JSON list of lines")
    out: list[Line] = []
    for row in data:
        if not isinstance(row, dict) or not isinstance(row.get("key"), str):
            raise ValueError(f"{path}: every line needs a key")
        out.append(Line(key=row["key"], src=str(row.get("from") or ""), dst=str(row.get("to") or ""),
                        sentences=tuple(str(s) for s in row.get("sentences") or [])))
    return out


def read_texts(path: Path) -> dict[str, str]:
    """A writer's output: one JSON object of key to merged text."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be one JSON object of key to text")
    return {str(k): str(v) for k, v in data.items()}


def read_verdicts(path: Path) -> dict[str, dict[str, object]]:
    """A checker's output: `{key: {"verdict", "says_more", "leaves_out"}}`. A row that is not an
    object is kept as an empty one, which carries no `ok` and so keeps nothing."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be one JSON object of key to verdict")
    return {str(k): (dict(v) if isinstance(v, dict) else {}) for k, v in data.items()}


def lint(lines: Iterable[Line], texts: Mapping[str, str]) -> dict[str, list[str]]:
    """Every fault in a writer's output, by key: a line with no text, a text for no line, and each
    text's `text_faults`. Empty when the output is clean."""
    by_key = {ln.key: ln for ln in lines}
    faults: dict[str, list[str]] = {}
    for key, ln in by_key.items():
        if key not in texts:
            faults[key] = ["no text for this line"]
            continue
        found = text_faults(texts[key], ln.sentences)
        if found:
            faults[key] = found
    for key in texts:
        if key not in by_key:
            faults[key] = ["no line has this key"]
    return faults


def _reasons(row: Mapping[str, object]) -> list[str]:
    """What a checker said against a text, as one phrase per point."""
    out: list[str] = []
    for label, field_name in (("says more", "says_more"), ("leaves out", "leaves_out")):
        items = row.get(field_name)
        for item in items if isinstance(items, list) else []:
            out.append(f"{label}: {item}")
    return out or ["rejected"]


@dataclass
class Choice:
    """What `choose` kept, and why it kept nothing for the rest."""

    kept: dict[str, str] = field(default_factory=dict)          # every text the file will hold
    new: list[str] = field(default_factory=list)                # keys kept from this run's writer
    rejected: dict[str, list[str]] = field(default_factory=dict)   # key -> the check's reasons
    faulty: dict[str, list[str]] = field(default_factory=dict)     # key -> the rules it breaks
    unchecked: list[str] = field(default_factory=list)          # a text with no verdict at all
    unknown: list[str] = field(default_factory=list)            # a text for a line no picture draws
    dropped: list[str] = field(default_factory=list)            # an old text whose line is gone


def choose(lines: Iterable[Line], old: Mapping[str, str], texts: Mapping[str, str],
           verdicts: Mapping[str, Mapping[str, object]]) -> Choice:
    """The texts to keep beside the map, from the ones kept before and one writer's run.

    `lines` is EVERY line the pictures draw that wants a text, not only the pending ones: an old
    text is kept only while its line is still drawn, so the file never grows texts nobody can see.
    A new text is kept when the check said `ok` AND it has no `text_faults`, and it replaces an old
    one for the same key."""
    by_key = {ln.key: ln for ln in lines}
    out = Choice()
    for key, text in old.items():
        if key in by_key:
            out.kept[key] = text
        else:
            out.dropped.append(key)
    for key, text in texts.items():
        ln = by_key.get(key)
        if ln is None:
            out.unknown.append(key)
            continue
        faults = text_faults(text, ln.sentences)
        if faults:
            out.faulty[key] = faults
            continue
        row = verdicts.get(key)
        if row is None:
            out.unchecked.append(key)
            continue
        if str(row.get("verdict") or "").strip().lower() != VERDICT_OK:
            out.rejected[key] = _reasons(row)
            continue
        out.kept[key] = text.strip()
        out.new.append(key)
    return out
