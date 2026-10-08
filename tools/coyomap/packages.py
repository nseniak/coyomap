"""The packages a repo declares at the top level, and the ones no dependency of the map names.

**Why this exists.** On the 2026-10-08 mcpolis rebuild the map went from 29 dependencies to 19.
Nobody was asked to list the libraries, the operations slice listed services and merged two
frameworks into one row, and React Router, Tailwind, TanStack Query, Pydantic and HTTPX were gone.
`validate` said nothing, because nothing compared the map with the files that declare what the
product is built on. This module is that comparison; `validate --check-coverage` prints it and the
eval profile counts it.

**What counts as declared.** Only the packages a product file names directly, and only the ones
the product runs with:

  * `package.json`: `dependencies` (never `devDependencies`, `peerDependencies` or
    `optionalDependencies`), but not a `workspace:`, `file:` or `link:` version, which points at
    another folder of the same repo;
  * `pyproject.toml`: `[project] dependencies` and `[tool.poetry.dependencies]` but `python`
    (never an optional extra, a poetry dependency marked `optional = true` or given a `path`,
    a dependency group or a dev group);
  * `go.mod`: every `require` but those marked `// indirect` and those a `replace` points at a
    local `./` or `../` folder.

A package file under a test, docs or internal folder (`NON_PRODUCT_DIRS`) is not read: an e2e
suite's `package.json` declares the test tools, not the product.

**What counts as named.** A dependency names a package when its `package` field or its name
carries it, as a word, case and `-`/`_`/`.` ignored. The method asks for one dependency per
package; this check stays lenient and lets a merged one ("React and Vite") name both `react` and
`vite`, because its job is to find a package no row names, not to police the rows. A scoped npm package
(`@sentry/react`) is also named by its scope (`Sentry`), and a Go module path by its last part,
without a major-version suffix (`github.com/foo/bar/v2` by `bar`, `gopkg.in/yaml.v3` by `yaml`).

Stdlib-only (the cli.py firewall).
"""
from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from coyomap.model import Dep
from coyomap.preindex_lib import NON_PRODUCT_DIRS, iter_source_files

#: The package files read, by file name.
PACKAGE_FILES: tuple[str, ...] = ("package.json", "pyproject.toml", "go.mod")

_WORD = re.compile(r"[@a-z0-9][a-z0-9._/@-]*")
_PEP508_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_GO_REQUIRE = re.compile(r"^\s*(?:require\s+)?([^\s()]+)\s+v\S+(.*)$")
_GO_REPLACE = re.compile(r"^\s*(?:replace\s+)?([^\s()]+)(?:\s+v\S+)?\s*=>\s*(\S+)")
#: A Go major-version suffix: `/v2` at the end of a module path, `.v3` on a gopkg.in path.
_GO_MAJOR = re.compile(r"(?:/v\d+|\.v\d+)$")


@dataclass(frozen=True)
class DeclaredPackage:
    """One top-level package, and the repo-relative file that declares it."""

    name: str
    file: str


def _norm(word: str) -> str:
    return re.sub(r"[-_.]+", "-", word.strip().lower())


def _squash(word: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", word.lower())


#: npm version prefixes that point inside the repo: a workspace sibling or a local folder.
_NPM_LOCAL = ("workspace:", "file:", "link:")


def _npm(text: str) -> list[str]:
    doc = json.loads(text)
    deps = doc.get("dependencies") if isinstance(doc, dict) else None
    if not isinstance(deps, dict):
        return []
    return sorted(n for n, v in deps.items()
                  if not (isinstance(v, str) and v.strip().startswith(_NPM_LOCAL)))


def _python(text: str) -> list[str]:
    doc = tomllib.loads(text)
    names: list[str] = []
    project = doc.get("project")
    if isinstance(project, dict) and isinstance(project.get("dependencies"), list):
        for spec in project["dependencies"]:
            hit = _PEP508_NAME.match(spec) if isinstance(spec, str) else None
            if hit:
                names.append(hit.group(1))
    tool = doc.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    deps = poetry.get("dependencies") if isinstance(poetry, dict) else None
    if isinstance(deps, dict):
        names.extend(n for n, v in deps.items() if n.lower() != "python" and not (
            isinstance(v, dict) and ("path" in v or v.get("optional") is True)))
    return sorted(dict.fromkeys(names))


def _go(text: str) -> list[str]:
    names: list[str] = []
    local: set[str] = set()
    block = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in ("require (", "replace ("):
            block = stripped.split()[0]
            continue
        if block and stripped.startswith(")"):
            block = ""
            continue
        if block == "replace" or stripped.startswith("replace "):
            hit = _GO_REPLACE.match(stripped)
            if hit and hit.group(2).startswith(("./", "../")):
                local.add(hit.group(1))
            continue
        if not (block == "require" or stripped.startswith("require ")):
            continue
        hit = _GO_REQUIRE.match(stripped)
        if hit and "// indirect" not in hit.group(2):
            names.append(hit.group(1))
    return sorted(n for n in dict.fromkeys(names) if n not in local)


_READERS = {"package.json": _npm, "pyproject.toml": _python, "go.mod": _go}


def read_package_file(path: Path) -> list[str]:
    """The top-level product packages one package file declares; `[]` for a file that cannot be
    read or parsed, which says nothing rather than failing a validate."""
    reader = _READERS.get(path.name)
    if reader is None:
        return []
    try:
        return reader(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return []


def declared_packages(root: Path) -> list[DeclaredPackage]:
    """Every top-level package the repo's product package files declare, in file then name order."""
    root = root.resolve()
    out: list[DeclaredPackage] = []
    for f in sorted(iter_source_files(root).files):
        rel = f.relative_to(root)
        if f.name not in PACKAGE_FILES or any(p in NON_PRODUCT_DIRS for p in rel.parts[:-1]):
            continue
        out.extend(DeclaredPackage(name=n, file=rel.as_posix()) for n in read_package_file(f))
    return out


def _named_by(deps: Iterable[Dep]) -> set[str]:
    """Every word the dependencies' names and `package` fields carry, in both compared forms."""
    words: set[str] = set()
    for d in deps:
        for text in (d.name, d.package):
            for w in _WORD.findall((text or "").lower()):
                words.update((_norm(w), _squash(w)))
        words.add(_squash(d.name or ""))
    words.discard("")
    return words


def _forms(name: str) -> set[str]:
    """The words that name `name`: itself, its npm scope, the last part of a Go module path without
    its major-version suffix."""
    low = name.lower()
    forms = {_norm(low), _squash(low)}
    if low.startswith("@") and "/" in low:
        scope = low[1:].split("/", 1)[0]
        forms.update((_norm(scope), _squash(scope)))
    elif "/" in low:
        last = _GO_MAJOR.sub("", low.rstrip("/")).rsplit("/", 1)[-1]
        forms.update((_norm(last), _squash(last)))
    forms.discard("")
    return forms


def unnamed_packages(deps: Iterable[Dep], declared: Iterable[DeclaredPackage]
                     ) -> list[DeclaredPackage]:
    """The declared packages no dependency names."""
    named = _named_by(deps)
    return [p for p in declared if not (_forms(p.name) & named)]
