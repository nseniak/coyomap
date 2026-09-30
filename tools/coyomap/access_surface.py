"""`coyomap access-surface` — the map's auth surface as FILES, for a later build to be measured against.

A rebuild is deliberately blind to its predecessor, and that is right: the independence is the whole
point of a from-scratch build. But it means a security claim can DISAPPEAR between two maps of
unchanged code and nothing in the build notices. On the 2026-08-20 argus pair the access-rule
STATEMENT count held at 21 -> 21 while the enforcement lines went 60 -> 48, and one file lost its
coverage outright: `adapters/auth_google.py`, whose lines verify the Google ID token's signature,
issuer and audience. The previous map claimed it as an access rule. The new map's 61 rules do not
mention a signature, an issuer or an audience anywhere.

`coyomap-eval compare` prints that as a NOTE. Two things make the note too late: it is a
developer-only command, and it runs at retro time against a baseline the build may not read — so on
the run that lost the claim, the note was printed, parked as "a reading job", and only re-read three
retrospectives later.

This writes the surface as data, so `coyomap finalize --access-baseline <file>` can put it in front
of the build's own gate — AFTER the map is written, where reading it cannot contaminate the rebuild,
and BEFORE the commit, which is the last moment anybody looks.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from coyomap.model import ProjectModel, access_rules

SCHEMA = "coyomap-access-surface/v1"


@dataclass(frozen=True)
class AccessClaim:
    """One thing a map said ONE file does for access: the rule, its statement, and the site.

    The access-baseline leg used to name a lost file and nothing else. On the 2026-09-30 mcpolis
    build it named 17, the lead opened none of them, and recorded 11 reasons taken from the NEW map:
    5 of the 11 answered a different claim than the one that was lost, and 4 old rules left the map
    altogether, team scoping of every stored record among them. A path is not a question anybody can
    answer; the claim it held is."""
    rule: str
    statement: str
    where: str = ""
    why: str = ""

    def site(self) -> str:
        """`line 42: filters every query by the team id`, or whichever half is known."""
        line = self.where.rsplit(":", 1)[1] if ":" in self.where else ""
        return ": ".join(x for x in (f"line {line}" if line else "", self.why) if x)


def held(claims: list[AccessClaim]) -> str:
    """What one file held, rule by rule, each statement once:
    `BR61 "Every stored record carries its team" (line 42: filters by the team id; line 50: …)`."""
    by_rule: dict[str, list[AccessClaim]] = {}
    for c in claims:
        by_rule.setdefault(c.rule, []).append(c)
    parts: list[str] = []
    for rule, cs in by_rule.items():
        statement = next((c.statement for c in cs if c.statement), "")
        sites = "; ".join(x for x in (c.site() for c in cs) if x)
        parts.append((f'{rule} "{statement}"' if statement else rule)
                     + (f" ({sites})" if sites else ""))
    return " and ".join(parts)


def access_files(m: ProjectModel) -> dict[str, list[str]]:
    """`{repo-relative file: [rule ids that anchor a site in it]}` — the wording-free half.

    FILES, not statements and not lines. Statements are LLM prose and drift between builds with no
    change in meaning; a line moves when the code above it moves. A file that held enforcement in
    one map and is claimed by no access rule in the next is the one signal that survives both."""
    out: dict[str, list[str]] = {}
    for rule in access_rules(m):
        for site in rule.sites:
            where = (site.where or "").strip()
            if not where:
                continue
            path = where.rsplit(":", 1)[0] if ":" in where else where
            path = path.strip()
            if path:
                out.setdefault(path, [])
                if rule.id not in out[path]:
                    out[path].append(rule.id)
    return {k: sorted(v) for k, v in sorted(out.items())}


def access_claims(m: ProjectModel) -> dict[str, list[AccessClaim]]:
    """`{repo-relative file: [every access claim a site in it makes]}` — the worded half, kept
    beside `access_files` so a lost file can be shown with what it held."""
    out: dict[str, list[AccessClaim]] = {}
    for rule in access_rules(m):
        for site in rule.sites:
            where = (site.where or "").strip()
            path = (where.rsplit(":", 1)[0] if ":" in where else where).strip()
            if path:
                out.setdefault(path, []).append(
                    AccessClaim(rule=rule.id, statement=rule.statement.strip(), where=where,
                                why=site.why.strip()))
    return {k: v for k, v in sorted(out.items())}


def surface_doc(m: ProjectModel) -> dict[str, object]:
    rules = access_rules(m)
    return {"schema": SCHEMA,
            "commit": m.commit or "",
            "access_rules": len(rules),
            "files": access_files(m),
            "claims": {f: [asdict(c) for c in cs] for f, cs in access_claims(m).items()}}


def write_surface(m: ProjectModel, path: Path) -> dict[str, object]:
    doc = surface_doc(m)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def load_surface(path: Path) -> dict[str, list[str]]:
    """`{file: [rule ids]}` from a surface file, or from a whole MAP — both are accepted.

    Accepting a map matters: every archive already holds one, and requiring the operator to
    pre-convert it is the friction that leaves a check unrun."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: not a JSON object")
    if doc.get("schema") == SCHEMA:
        files = doc.get("files")
        return {k: list(v) for k, v in files.items()} if isinstance(files, dict) else {}
    from coyomap.assemble import load_map_or_fragment
    m, _present = load_map_or_fragment(path)
    return access_files(m)


def load_claims(path: Path) -> dict[str, list[AccessClaim]]:
    """`{file: [AccessClaim]}` from a surface file or a whole map, the way `load_surface` reads it.

    A surface file written before the claims were kept carries rule ids only, so each claim comes
    back with its id and no statement rather than not at all."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, dict) and doc.get("schema") == SCHEMA:
        claims = doc.get("claims")
        if isinstance(claims, dict):
            return {str(f): [AccessClaim(**{k: str(c.get(k) or "") for k in
                                            ("rule", "statement", "where", "why")})
                             for c in cs if isinstance(c, dict)]
                    for f, cs in claims.items() if isinstance(cs, list)}
        return {f: [AccessClaim(rule=r, statement="") for r in rules]
                for f, rules in load_surface(path).items()}
    from coyomap.assemble import load_map_or_fragment
    m, _present = load_map_or_fragment(path)
    return access_claims(m)


def lost_files(baseline: Mapping[str, object], m: ProjectModel) -> list[str]:
    """Files the baseline claimed as access enforcement that no access rule in `m` names."""
    now = set(access_files(m))
    return sorted(f for f in baseline if f not in now)


def newest_archived_map(out: Path) -> Path | None:
    """The map the last `coyomap-eval archive` filed under `dev-rebuilds/NNNN/`, or None.

    The archive is the coyomap developer's convention (a user of coyomap never has it), and its
    numbers are zero-padded, so text order is recency. `finalize --access-baseline` exists for
    exactly this map — files that held ACCESS enforcement there and are named by no rule now — and
    the 2026-09-08 mcpolis build never ran it, because nothing in the closing sequence asked:
    19 of 60 such files went unnamed while the hard gate beside them failed."""
    maps = sorted(p for p in (out / "dev-rebuilds").glob("*/project-map.json") if p.parent.name.isdigit())
    return maps[-1] if maps else None


def baseline_beside(map_path: Path) -> Path | None:
    """The newest archived map for the map OR fragment at `map_path`, or None.

    `record` is handed a fragment (`.coyomap/build-fragments/extras.json`) as often as the map, so
    the `.coyomap` folder is its parent or its grandparent."""
    p = map_path.resolve()
    for out in (p.parent, p.parent.parent):
        if (out / "dev-rebuilds").is_dir():
            return newest_archived_map(out)
    return None
