#!/usr/bin/env python3
"""The harvest contract's field names, checked against the model a fragment is loaded into.

Run either way (needs an editable install: `make deps`):
    python3 tests/test_contract_schema.py
    pytest tests/test_contract_schema.py

**Why this exists.** The harvest contract hands every harvest agent a table of field names "so you
do not have to go and find them". On the 2026-10-08 mcpolis build that table still named
`entry_point` (a component field removed weeks before), gave `depends_on` with no type and gave
`activation` with none of its two values. 6 of 14 harvest agents failed `lint-fragment` on
`entry_point`, 4 on a list `depends_on` and 3 on a prose `activation`. Nothing compared the table
with the model, so the table drifted the moment the model moved.

The model here is `generate_schema()`, which is generated from the same dataclasses
`lint-fragment` loads a fragment into (`assemble.load_fragment` → `_build(…, ProjectModel)`), and
whose enums are the ones the model's checks refuse. So a field this file accepts is a field the
linter accepts.
"""
from __future__ import annotations

import re
from pathlib import Path

from coyomap.json_schema import generate_schema

REPO = Path(__file__).resolve().parent.parent
HARVEST = REPO / "method" / "templates" / "harvest-contract.md"

#: Fields the contract tells a harvest agent NOT to author. Naming one in the field table says the
#: opposite in the same file: the 2026-10-08 table listed `subsystem` and `runs_in` while the
#: paragraph below it forbade both.
_LEAD_ASSIGNED = ("runs_in", "subsystem", "subdomain", "bucket", "block")

#: One row of the field table: `> | \`components\` | **id**, … |`.
_TABLE_ROW = re.compile(r"^>\s*\|\s*`(\w+)`\s*\|(.*)\|\s*$")


def make_schema() -> dict:
    return generate_schema()


def make_contract_text() -> str:
    return HARVEST.read_text(encoding="utf-8")


def _split_top_level(cell: str) -> list[str]:
    """Split a cell on the commas that are not inside a `( … )` note."""
    parts: list[str] = []
    depth, cur = 0, ""
    for ch in cell:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def table_fields(text: str) -> dict[str, list[tuple[str, str]]]:
    """Every array the field table names → its `(field, note)` pairs, the note being the text in
    the brackets after the field (empty when there is none)."""
    out: dict[str, list[tuple[str, str]]] = {}
    for line in text.splitlines():
        hit = _TABLE_ROW.match(line)
        if not hit or hit.group(1) == "array":
            continue
        pairs: list[tuple[str, str]] = []
        for part in _split_top_level(hit.group(2)):
            name = re.match(r"\**`?([a-z_]+)`?\**", part)
            assert name, f"{hit.group(1)}: cannot read a field name in {part!r}"
            note = part[name.end():].strip()
            pairs.append((name.group(1), note[1:-1] if note.startswith("(") else note))
        out[hit.group(1)] = pairs
    return out


def _def_of(schema: dict, array: str) -> dict:
    items = schema["properties"][array]["items"]
    return schema["$defs"][items["$ref"].split("/")[-1]]


def _resolve(schema: dict, path: list[str]) -> dict | None:
    """The property a dotted `a[].b[].c` path names, or None. A head that is not a top-level array
    (`evidence[].file`) is looked up as an array property of any definition."""
    head, rest = path[0], path[1:]
    if head in schema["properties"]:
        prop = schema["properties"][head]
    else:
        prop = next((d["properties"][head] for d in schema["$defs"].values()
                     if head in d.get("properties", {})), None)
        if prop is None:
            return None
    for name in rest:
        items = prop.get("items", {})
        if "$ref" not in items:
            return None
        prop = schema["$defs"][items["$ref"].split("/")[-1]].get("properties", {}).get(name)
        if prop is None:
            return None
    return prop


def test_the_table_names_every_harvest_array() -> None:
    fields = table_fields(make_contract_text())
    assert set(fields) == {"components", "entry_points", "deps", "observability", "config",
                           "deployment", "run_commands"}


def test_every_field_the_table_names_is_a_field_of_its_array() -> None:
    schema = make_schema()
    unknown = [f"{array}.{name}" for array, pairs in table_fields(make_contract_text()).items()
               for name, _note in pairs if name not in _def_of(schema, array)["properties"]]
    assert unknown == [], f"the harvest contract's table names fields the model has not got: {unknown}"


def test_every_closed_field_in_the_table_names_all_its_values() -> None:
    """A field whose model is an enum carries its values in the table, so an agent never has to
    guess them: `activation` came back as prose from 3 of 14 agents."""
    schema = make_schema()
    missing: list[str] = []
    for array, pairs in table_fields(make_contract_text()).items():
        props = _def_of(schema, array)["properties"]
        for name, note in pairs:
            for value in props[name].get("enum") or []:
                if value and f"`{value}`" not in note:
                    missing.append(f"{array}.{name}: `{value}`")
    assert missing == [], f"closed fields whose values the table does not name: {missing}"


def test_every_list_field_says_list_and_every_text_field_says_text() -> None:
    """A list field says `list` in its note. A text field that does say what it is says `text`,
    never `list`: `depends_on` came back as a list from 4 of 14 agents while the model holds one
    line of text."""
    schema = make_schema()
    wrong: list[str] = []
    for array, pairs in table_fields(make_contract_text()).items():
        props = _def_of(schema, array)["properties"]
        for name, note in pairs:
            types = props[name].get("type")
            types = types if isinstance(types, list) else [types]
            says_list = re.search(r"\blist\b", note) and not re.search(r"\bnever a list\b", note)
            if "array" in types and not says_list:
                wrong.append(f"{array}.{name} is a list, and its note does not say so")
            if "array" not in types and says_list:
                wrong.append(f"{array}.{name} is text, and its note says list")
    assert wrong == [], wrong
    depends_on = dict(table_fields(make_contract_text())["components"]).get("depends_on")
    assert depends_on is None or "text" in depends_on


def test_the_table_names_no_field_the_contract_forbids() -> None:
    text = make_contract_text()
    forbidden_paragraph = text[text.index("Fields you must NOT author"):]
    for name in _LEAD_ASSIGNED:
        assert f"`{name}`" in forbidden_paragraph[:2000], f"`{name}` left the forbidden list"
    named = {name for pairs in table_fields(text).values() for name, _ in pairs}
    assert named.isdisjoint(_LEAD_ASSIGNED), named & set(_LEAD_ASSIGNED)


def test_every_array_field_path_the_contract_names_exists() -> None:
    """The anchor list names fields as `components[].source`; it carried `components[].entry_point`
    after the field was removed."""
    schema = make_schema()
    paths = re.findall(r"`(\w+(?:\[\]\.\w+)+)`", make_contract_text())
    assert paths, "the contract names no `array[].field` path at all"
    gone = sorted({p for p in paths if _resolve(schema, p.split("[].")) is None})
    assert gone == [], f"the harvest contract names fields the model has not got: {gone}"


def test_a_table_naming_a_removed_field_is_caught() -> None:
    """The check itself, against the 2026-10-08 row."""
    old = ("> | `components` | **id**, **name**, **purpose**, **source**, kind, confidence, "
           "subsystem, entry_point, files, depends_on |\n")
    pairs = table_fields(old)["components"]
    props = _def_of(make_schema(), "components")["properties"]
    assert [n for n, _ in pairs if n not in props] == ["entry_point"]
    assert {"subsystem"} == {n for n, _ in pairs} & set(_LEAD_ASSIGNED)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
