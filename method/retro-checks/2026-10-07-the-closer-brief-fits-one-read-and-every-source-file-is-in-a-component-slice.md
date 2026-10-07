# The closer's brief fits one Read, and every source file is in a slice that writes components

Change (2026-10-07, retro findings mcpolis-2026-10-07-4 and -7): `contract closer --from-verdicts`
prints each `dump` block once (a later claim about the same element names the claim it is printed
under) and, when the brief is over 40,000 characters, puts the claims in part files beside `--out`,
each at most 40,000 characters, which the brief at `--out` lists for its ONE closer to read whole;
`contract harvest --from-slots` also names every source file the component expectation E is counted
from that no slice with a component budget above 0 holds, count first and one file per line, and
the script warning prints in the same layout · tools/coyomap/contract.py,
method/templates/closer-contract.md, method.md.
Baseline: the closer brief was one file of 142,697 characters with 20 repeated `dump` blocks, and
the harvest run warned about 6 scripts while 41 source files sat in no slice that writes components.

Escalation: if item 1 fails, re-run the closer on a brief it can read whole before accepting the
map: its appeals may have been judged without their map rows.

## Checks

1. expect: every `closer*.md` file of each closer run in the build's scratchpad (the brief and its
   parts) is at most 40,000 characters, no fenced `dump` block appears twice across one run's files,
   and the closer's transcript Reads the brief and every part it lists with 0 truncation notices.
   regression sign: a closer brief file over 40,000 characters, a `read_truncation_notice` on a
   `closer*.md` in a closer's transcript, a listed part the closer never opened, or more than one
   closer dispatched for one wave because its brief was split.

2. expect: every PRODUCT source file that the `contract harvest --from-slots` run cutting the
   harvest named under "source file(s) are in no slice that writes components" was in a slice with
   a component budget above 0 when the harvest was dispatched. A product source file is code the
   product runs: a route, a service, an adapter, a domain model, a page. A tool's own config file
   (`eslint.config.js`, `vite.config.ts`: a `*.config.*` file at a package root that sets up a
   linter, a bundler, a test runner or a formatter) may stay named and unslotted: the warning
   never stops a brief, and no component is made of such a file. The 2026-10-07 mcpolis slot files,
   with the infrastructure slice in, name 1 file, `frontend/eslint.config.js`, and no product
   source file; without that slice they name 38, 37 of them product source files.
   regression sign: the harvest went out with a product source file the warning named still in no
   slice that writes components, or a harvest agent was added after the fan-out for product source
   files the warning had named. A tool's config file named in the warning is not a regression.
