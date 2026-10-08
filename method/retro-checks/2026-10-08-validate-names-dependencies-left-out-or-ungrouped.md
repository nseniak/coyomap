# Validate names the dependencies a map leaves out or leaves ungrouped

Change (2026-10-08, round 2, backlog row 49, tool half): `validate` warns when a dependency has no
authored `bucket` (always on), and, with `--check-coverage`, when a top-level package the repo's
package files declare is named by no dependency. Read: `package.json` `dependencies`,
`pyproject.toml` `[project] dependencies` and `[tool.poetry.dependencies]` (not `python`), `go.mod`
requires not marked indirect; nothing under a tests, docs or internal folder. A dependency names a
package by its `package` field or its name, case and `-_.` ignored, so a merged dependency counts
for every package it lists; a scoped npm package is also named by its scope, a Go module by its
last part. Both are advisories with no recorded escape: the answer is one bucket, or one package
name in a `package` field. The eval profile counts both (`deps_without_bucket`,
`packages_without_dep`, the second only with `--repo`), and `coyomap-eval compare` prints them as
notes, never as a gate · tools/coyomap/packages.py (new), tools/coyomap/validate_model.py,
eval/tools/coyomap_eval/profile.py, eval/tools/coyomap_eval/compare.py,
tests/test_validate_model.py, tests/test_method_contract.py, eval/tests/test_profile.py,
eval/tests/test_compare.py.
On the 2026-10-08 mcpolis map: 19 of 19 dependencies have no bucket, and 21 of the 36 top-level
packages declared in `backend/pyproject.toml` and `frontend/package.json` are named by no
dependency (among them pydantic, react-router, @tanstack/react-query, @tailwindcss/typography).

Escalation: a build whose `packages_without_dep` rose against the previous build's, on the same
package files, lost libraries from the map: run the eval before accepting it.

## Checks

1. expect: the build's final `validate --check-sources --check-coverage` prints no "have no
   authored bucket" line (every dependency carries a bucket).
   regression sign: the line fires on the shipped map, which means the reconcile pass that sets
   buckets was skipped again.

2. expect: the build's final validate prints no "named by no dependency" line, or one whose
   packages each appear in the closing report with a reason they are left out.
   regression sign: the profile's `packages_without_dep` above the previous build's on the same
   package files.

3. expect: `coyomap-eval compare` against the previous build shows a "declared packages no dep
   names" note only when the candidate count is above 0, and its two numbers equal the two
   profiles' `packages_without_dep`.
   regression sign: a candidate profile with `packages_without_dep` null although it was scored
   with `--repo`.

Review fix (2026-10-08, independent review of round 2, findings 6a and 7): the "named by no
dependency" advice asks for one dependency per package, its `package` field naming that one
package; it told the lead that one dependency may list several. The package check no longer counts
packages of the same repo (an npm `workspace:`, `file:` or `link:` version, a poetry `path`
dependency, a Go module a `replace` points at a `./` or `../` folder) or a poetry dependency marked
`optional = true`, and names a Go module without its major-version suffix
(`github.com/foo/bar/v2` by `bar`, `gopkg.in/yaml.v3` by `yaml`) · tools/coyomap/packages.py,
tools/coyomap/validate_model.py, tests/test_validate_model.py, tests/test_method_contract.py.
On the mcpolis repo and its map the list is unchanged: 36 declared, the same 21 named by no
dependency (mcpolis has none of those declaration kinds).

4. expect: on a monorepo with workspace or local-path packages, the "named by no dependency" line
   names none of them.
   regression sign: a sibling folder's package (`@acme/shared`, a `path` dependency) in the line.
