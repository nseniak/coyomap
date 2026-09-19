<div align="center">

<img src="assets/running-off-the-cliff.png" alt="Wile E. Coyote running off the cliff, drawn as ASCII art: teal characters on black, the cliff edge in orange on the left" width="640">

# coyomap: agentic coding without running off the cliff

A map of your project, from features down to the code

</div>

## Why coyomap?

When coding agents generate most of your code, you can lose track of your project's features
and implementation. Everything runs fine until the day you look down and see there is nothing under
your feet. This is the Coyote Effect.

coyomap helps you avoid the Coyote Effect: you keep visibility into the project and find your way
around it as it grows.

## What is coyomap?

coyomap analyzes your project and builds an interactive map of its features, in plain language,
linked to the underlying architecture and code. Use it to understand what your project does and
how it is implemented, top-down, without reading all the code. Drill into the code only where and
when you actually need to.

It is also a shared picture of the project for your non-developer teammates. Hand it to them as a
link: coyomap writes the map out as a plain website you can host anywhere, and a reader needs no
repo and nothing installed.

## What coyomap shows

The viewer shows your project in three views: *Product*, *Under the hood* and *Update log*.

**Product** shows the project's functionality: who uses it, its features and use cases, the happy
path, the rules it enforces, and the data it keeps.

<img src="assets/viewer-product.png" alt="The coyomap viewer on a project's Features page: the people who use the product on the left, its features in happy-path order in the middle, and the data each feature owns on the right. No code on screen." width="80%">

**Under the hood** shows how the project is built and run: its components and their dependencies,
where data is stored, how it is deployed.

<img src="assets/viewer-hood.png" alt="The coyomap viewer on a project's Components page: the map of one subsystem with one component selected and explained in a sentence, and that component's source code open on the right at the line the map points to." width="80%">

**Update log** shows how the product changed, one entry per update of the map (`/coyomap update`), newest first.
An update's page tells its story by feature, in plain words: what the product now does differently,
which boxes it touched, the evidence, with the map's own diff for that step underneath.

You can start from a feature and drill down: the interfaces and data it touches, the components that do the
work, and the code behind each.

## Why not just ask my agent to explain the code?

You can ask your agent to analyze the code, generate summaries and draw diagrams. However, coyomap
differs in two ways:

- coyomap builds an explorable, hierarchical map: every box has a plain-language note, links to
  related elements, and links into the architecture and code. The map is saved with the project, so
  everyone sees the same one.
- An AI agent can miss things or make things up. So coyomap reads the code with the help of an
  index, makes every claim point at a real file and line, checks the map for gaps and
  contradictions, and has fresh agents try to prove each claim wrong before the map is written.

## How to use

coyomap runs as a skill on Claude Code, Codex and Cursor. Any other agent that can read this
repo works too: ask it to read `method.md` and follow it.

### Install once

```
git clone https://github.com/nseniak/coyomap.git
cd coyomap
make install
```

Needs Python 3.10+. Run `make install` again after every `git pull`.

### Map your project

```
cd ~/my-project
claude
/coyomap
```

It tells you what it is about to read before it starts, and hands you a link to the map when it
is done. The map lands in `.coyomap/` — commit it with your code.

The first build is the agent's biggest job: up to an hour, once per project. Everything after it
is cheap.

### Keep it in step

```
# after the code changed
/coyomap update

# ask for a change to the map itself
/coyomap rename the "API" subsystem to "Public API"
```

### Share it

```
cd coyomap && .venv/bin/coyomap export ~/my-project --out ./site
```

A folder of plain files: the viewer, the map, and your code. Put it on GitHub Pages or any web
host and send the link. Nothing runs on the server. It is a snapshot, so export again after the
map changes.

## Which files are analyzed

coyomap takes every file in your project, except two sets: what your `.gitignore` excludes, and what
`.coyomap/.ignore` excludes. git decides the first one, so all the usual rules hold, including a
`.gitignore` inside a subfolder. `.coyomap/.ignore` uses the same syntax, and is for the other case:
code that *is* committed, but that you don't want on the map — a vendored copy, checked-in build
output, a fixture tree. The build reports what each pattern removed, so an exclusion never goes
unnoticed.

## Status

coyomap is **work in progress**, in daily use. The stored map format still moves: a newer coyomap
may not read an older map, and a rebuild is the fix, so treat a map as replaceable. A rebuild is a
fresh start: it does not re-apply the changes you asked for by hand. Map quality
depends on the coding agent and model: read it, and correct it.

Feedback and bug reports are welcome, please [open an issue](../../issues).
