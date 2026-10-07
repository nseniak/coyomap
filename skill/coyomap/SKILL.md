---
name: coyomap
description: >
  Everything about a coyomap project map — a top-down, drillable map of a codebase (behavioral
  layer first, then the structural machine), committed next to the code as a model and served as an
  interactive C4 diagram by `coyomap serve`. Use this skill whenever the user wants to build one
  ("map this repo", "with the coyomap method"), analyze the change impact of a diff against an
  existing map, accept a change-impact report into the baseline, or work with a map that already
  exists: look one thing up in it, open it, link to it ("show me the use case about X in the map",
  "where is Y in the map"), or export it as a static site to share with people who have neither the
  repo nor coyomap ("share the map", "send the map to the team", "publish the map"). The modes and
  their commands live in the clone, never here. Triggers on "coyomap", "project map", "codebase map",
  "change impact", "accept the map", "in the map", "share the map", "export the map".
---

# coyomap

**Continuing from a summary?** If your context was summarized while you worked, do this before any
other step: run `__COYOMAP_HOME__/.venv/bin/coyomap state show --repo <the repo you are mapping>`,
re-read the method section it names, and read the `--help` of the next coyomap command before you
run it. A summary keeps the gist and drops the flags; the build-state file keeps both.

coyomap is a method (prompts) + tools for a drillable map of a codebase.

**The repo is the source of truth — this skill is only a pointer into it, and is deliberately
thin.** Anything written HERE is a copy baked into `~/.claude/skills/` at `make install` time, and
goes stale the moment the repo moves on: the coyomap skill told agents for weeks to read a method
doc that had been renamed. So this file carries only what is needed to FIND the repo. Everything
else lives there and is read live.

- **`COYOMAP_HOME` = `__COYOMAP_HOME__`** — the coyomap clone. Every method doc, template and tool
  lives here; read and run them with that absolute prefix.
- **The repo you are mapping** — your current working directory, a *different*
  path. Only `.coyomap/` paths belong to it.

Read `__COYOMAP_HOME__/method/dispatch.md` and follow it end to end. It is the entry point, and it names every
other doc, tool and precondition — work from it, not from memory, and do not expect this file to
list them.
