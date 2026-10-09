#!/usr/bin/env python3
"""`coyomap changes merge` — one log out of the drafts parallel helpers wrote: placeholders numbered,
entries renumbered, waivers joined, a field two drafts edit differently listed. Explicit make_*
builders, no fixtures/classes."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from coyomap import changelog
from coyomap.changes_merge import merge
from coyomap.changelog import lint, load_log

from test_mapdiff import make_rule
from test_changelog import make_doc


def make_draft(entries: list[dict[str, Any]], waived: list[dict[str, str]] | None = None,
               notes: str = "") -> dict[str, Any]:
    return {"format": "coyomap-changes", "version": 1, "from_commit": "aaaaaaa", "to_commit": "bbbbbbb",
            "date": "2026-10-09", "entries": entries, "waived": waived or [], "notes": notes}


def make_draft_entry(eid: str, elements: list[str], **kw: Any) -> dict[str, Any]:
    return {"id": eid, "headline": kw.pop("headline", "A team keeps its last admin"),
            "sentence": kw.pop("sentence", "Removing the last admin is refused."),
            "elements": elements, "edits": kw.pop("edits", []), "added": kw.pop("added", []),
            "removed": kw.pop("removed", []), "evidence": [], "confidence": "verified"}


def make_new_rule(rid: str, statement: str) -> dict[str, Any]:
    return {"kind": "rules", "row": dict(make_rule(rid, statement, where="a.py:2"), name=statement)}


RISK = {"id": "BR1", "key": "risk", "was": "a team is left open", "now": "a team is locked"}


def test_placeholders_get_the_next_free_numbers_everywhere_and_the_log_lints():
    """mcpolis 2026-10-09: six helpers, reserved id ranges by hand, new ids renumbered by hand."""
    doc = make_doc()
    a = make_draft([make_draft_entry("e1", ["BR?a1", "BR1"], added=[make_new_rule("BR?a1", "The last admin stays")],
                                     edits=[RISK])], notes="helper a: commits 1-10")
    b = make_draft([make_draft_entry("e1", ["BR?b1", "BR?a1"], added=[make_new_rule("BR?b1", "A seat cap holds")],
                                     headline="Seats are capped", sentence="A fourth seat is refused."),
                    make_draft_entry("e2", ["BR1"], edits=[RISK])],
                   waived=[{"id": "C1", "why": "a rename"}], notes="helper b: commits 11-31")
    m = merge([("a.json", a), ("b.json", b)], doc)
    assert m.numbered == {"BR?a1": "BR2", "BR?b1": "BR3"}
    assert [e["id"] for e in m.log["entries"]] == ["e1", "e2", "e3"]
    assert m.log["entries"][1]["elements"] == ["BR3", "BR2"], "a draft names another draft's box by its placeholder"
    assert m.log["entries"][2]["edits"] == [] and m.clashes == [] and len(m.joined) == 1, "the same edit twice is kept once"
    assert "?" not in json.dumps(m.log)
    assert m.log["notes"] == "helper a: commits 1-10\n\nhelper b: commits 11-31"
    problems = lint(load_log(json.dumps(m.log)), doc)
    assert problems.ok, problems.errors


def test_one_field_edited_two_ways_is_a_clash_the_lead_resolves():
    doc = make_doc()
    a = make_draft([make_draft_entry("e1", ["BR1"], edits=[RISK])])
    b = make_draft([make_draft_entry("e1", ["BR1"], edits=[dict(RISK, now="a team is frozen")])])
    m = merge([("a.json", a), ("b.json", b)], doc)
    assert m.clashes == ["BR1.risk is edited by a.json (e1) and by b.json (e2) with different words: keep one, "
                         "or write one edit that says both"]
    assert not lint(load_log(json.dumps(m.log)), doc).ok, "lint refuses the pair too"


def test_drafts_that_cannot_be_one_log_are_refused():
    doc = make_doc()
    rule = make_draft([make_draft_entry("e1", ["BR?a1"], added=[make_new_rule("BR?a1", "x")])])
    with pytest.raises(ValueError, match="added by both a.json and b.json"):
        merge([("a.json", rule), ("b.json", rule)], doc)
    with pytest.raises(ValueError, match="BR\\?z9 named but added by no draft"):
        merge([("a.json", make_draft([make_draft_entry("e1", ["BR?z9"])]))], doc)
    later = dict(make_draft([]), to_commit="ccccccc")
    with pytest.raises(ValueError, match="covers aaaaaaa..ccccccc"):
        merge([("a.json", make_draft([])), ("b.json", later)], doc)


def test_the_command_writes_the_log_and_exits_1_on_a_clash():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "map.json").write_text(json.dumps(make_doc()), encoding="utf-8")
        (root / "a.json").write_text(json.dumps(make_draft([make_draft_entry("e1", ["BR1"], edits=[RISK])])), encoding="utf-8")
        (root / "b.json").write_text(json.dumps(make_draft([make_draft_entry("e1", ["BR1"], edits=[dict(RISK, now="x y")])])),
                                     encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = changelog.main(["merge", str(root / "a.json"), str(root / "b.json"),
                                   "--map", str(root / "map.json"), "--out", str(root / "log.json")])
        merged = json.loads((root / "log.json").read_text(encoding="utf-8"))
    assert code == 1 and "1 clash(es)" in out.getvalue() and "CLASH: BR1.risk" in out.getvalue()
    assert len(merged["entries"]) == 2


def test_a_flow_names_its_use_case_and_an_id_a_draft_writes_is_not_given_again():
    """Review findings: a use case and its flow in two drafts were refused as one placeholder added
    twice; a placeholder took the number a draft had written itself; `SAML?relay` in a sentence was
    read as a placeholder."""
    doc = make_doc()
    uc = {"kind": "use_cases", "row": {"id": "UC?c1", "name": "Sign in by SAML", "actors": ["R1"]}}
    flow = {"kind": "flows", "row": {"uc": "UC?c1", "title": "Sign in by SAML", "steps": []}}
    c = make_draft([make_draft_entry("e1", ["UC?c1"], added=[uc],
                                     sentence="A person signs in at /sso/SAML?relay=home.")])
    d = make_draft([make_draft_entry("e1", ["UC?c1"], added=[flow])])
    m = merge([("c.json", c), ("d.json", d)], doc)
    assert m.numbered == {"UC?c1": "UC2"} and m.log["entries"][1]["added"][0]["row"]["uc"] == "UC2"
    assert "/sso/SAML?relay=home" in m.log["entries"][0]["sentence"]
    a = make_draft([make_draft_entry("e1", ["BR2"], added=[make_new_rule("BR2", "Written by number")])])
    b = make_draft([make_draft_entry("e1", ["BR?b1"], added=[make_new_rule("BR?b1", "By placeholder")])])
    assert merge([("a.json", a), ("b.json", b)], doc).numbered == {"BR?b1": "BR3"}
