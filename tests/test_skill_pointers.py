"""The installed SKILL.md files are COPIES. Whatever they say must be true forever, or reinstalled.

`make install*` renders each `SKILL.md` into `~/.claude/skills/` with the clone path baked in, and
nothing re-runs it when the repo moves on. So every sentence in a SKILL.md is a claim frozen at
install time. Three of them had already gone stale in the tree:

  * `skill/coyomap/SKILL.md` told agents to read `method/schema-v1.md`, renamed in e14be77 — an
    installed skill pointing at a file that does not exist;
  * `eval/retro/SKILL.md` described previous maps as `.coyomap/.old-ignore*/`, renamed in 6e4bfed;
  * `eval/SKILL.md` was missing the "developer, not user" framing the repo had added.

The fix is structural, not vigilance: a SKILL.md carries only what is needed to FIND the repo, and
everything that can change lives in the repo and is read live. These tests hold that shape.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

#: (skill file, the ONE entry doc it is allowed to name).
SKILLS: dict[str, str] = {
    "skill/coyomap/SKILL.md": "method/dispatch.md",
    "eval/SKILL.md": "eval/method.md",
    "eval/retro/SKILL.md": "eval/retro/method.md",
}

#: A repo-relative doc/config path mentioned in prose.
_REPO_PATH = re.compile(r"\b((?:method|eval|tools|skill)/[\w./-]+\.(?:md|json|py))\b")


def make_body(rel: str) -> str:
    """A skill's prose, with the YAML frontmatter removed.

    The frontmatter is exempt on purpose: `description` is the routing surface an agent matches on,
    so it cannot move into the repo. It is also the one part whose staleness is visible — a wrong
    description shows up as the skill not firing, whereas a wrong body path fails silently, deep in
    a build."""
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    _head, sep, body = text.partition("\n---\n")
    assert sep, f"{rel}: no YAML frontmatter"
    return body


def test_every_skill_names_only_its_own_entry_doc():
    """The drift that actually bit: a SKILL.md enumerating method docs it does not own.

    `skill/coyomap/SKILL.md` listed `method/model.md` as an example of what the docs would ask for,
    and an earlier rename left the installed copy pointing at `method/schema-v1.md`. A pointer that
    names exactly one destination cannot rot that way — and the destination is checked to exist."""
    offenders: list[str] = []
    for rel, entry in SKILLS.items():
        mentioned = {m.group(1) for m in _REPO_PATH.finditer(make_body(rel))}
        assert (REPO_ROOT / entry).is_file(), f"{rel} points at {entry}, which does not exist"
        extra = sorted(mentioned - {entry})
        if extra:
            offenders.append(f"{rel} names {extra} besides its entry doc {entry}")
    assert not offenders, (
        "a SKILL.md is a COPY baked into ~/.claude/skills at install time; every repo path it names "
        "is a claim that rots silently when the repo moves on. Name only the entry doc and let it "
        "name the rest:\n  " + "\n  ".join(offenders))


def test_every_skill_body_stays_thin():
    """Length is the proxy for "how much frozen claim is in here". These are pointers; a body that
    grows is a body that has started duplicating the method doc — which is exactly how all three
    drifted."""
    fat = [f"{rel}: {len(make_body(rel).splitlines())} lines"
           for rel in SKILLS
           if len(make_body(rel).splitlines()) > 25]
    assert not fat, ("SKILL.md bodies must stay pointers, not summaries (>25 lines): "
                     + ", ".join(fat))


def test_every_skill_tells_the_agent_to_read_its_entry_doc():
    """The one instruction a pointer must carry."""
    for rel, entry in SKILLS.items():
        body = make_body(rel)
        assert f"__COYOMAP_HOME__/{entry}" in body, (
            f"{rel} must tell the agent to read __COYOMAP_HOME__/{entry}")


def test_every_skill_resolves_paths_against_the_clone():
    """Without this the agent looks for method docs inside the repo it is mapping, where they are
    not. Both directories have to be named, or the substitution means nothing."""
    for rel in SKILLS:
        assert "__COYOMAP_HOME__" in make_body(rel), f"{rel} never names COYOMAP_HOME"


def test_the_install_targets_cover_every_skill():
    """A skill with no install target is one nobody can get, and a target naming a file that moved
    installs nothing. Both are silent."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    for rel in SKILLS:
        assert rel in makefile, f"{rel} is not referenced by any Makefile install target"


def test_the_coyomap_skill_opens_with_what_to_do_after_a_summary():
    """A summary replaces the lead's context mid-build, and the harness re-adds only the start of a
    skill. So the first paragraph under the title is the one that must send the lead to the build
    state, and to each command's `--help`, before its next step: the summary keeps the gist and
    drops the flags."""
    body = make_body("skill/coyomap/SKILL.md")
    paragraphs = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
    assert paragraphs[0] == "# coyomap", paragraphs[0]
    first = paragraphs[1]
    for needed in ("summary", "coyomap state show", "--help"):
        assert needed in first, f"the skill's first paragraph does not name {needed!r}: {first}"
