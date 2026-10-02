REPO := $(CURDIR)

# Repo-local virtualenv that coyomap owns. Deps install HERE, never into the user's
# active/system Python — no pollution, no PEP-668 "externally-managed" block. The CLI is
# installed editable, so the repo stays the source of truth (docs/tools evolve without reinstall).
VENV := $(REPO)/.venv
PY := $(VENV)/bin/python
MIN_PY := 3.10

# Skills homes to install into — one per agent family, chosen to cover Claude
# Code, Codex, and Cursor while keeping duplicate discovery to a minimum:
#   ~/.claude/skills  -> Claude Code (Cursor also reads this for compatibility)
#   ~/.agents/skills  -> the cross-agent standard, read natively by Codex AND Cursor
# Cursor needs no dir of its own (it reads both of the above); we skip
# ~/.codex/skills and ~/.cursor/skills on purpose, since .agents already covers
# Codex and Cursor and extra copies would just show up as duplicate skills.
SKILLS_DIRS := $(HOME)/.claude/skills $(HOME)/.agents/skills

.PHONY: install install-eval install-retro install-dev \
        uninstall uninstall-eval uninstall-retro uninstall-dev \
        deps dev venv clean start dev-start gates land break-check

# Port for the local map server (the file browser + code viewer backend).
PORT ?= 8765

# Create the repo-local venv. Requires Python $(MIN_PY)+ (the pre-index's tree-sitter deps
# declare requires-python >=3.10); fail fast with a clear message instead of a cryptic error.
venv:
	@command -v python3 >/dev/null 2>&1 || { \
		echo "ERROR: python3 not found. coyomap requires Python $(MIN_PY)+ (see README 'Requirements')."; exit 1; }
	@python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' || { \
		echo "ERROR: Python $(MIN_PY)+ required; found $$(python3 --version 2>&1). See README 'Requirements'."; exit 1; }
	@test -d "$(VENV)" || python3 -m venv "$(VENV)"

# Install the coyomap CLI editable into the venv, WITH the pre-index extra (tree-sitter for
# polyglot symbol/import extraction). The core gate (validate + render) stays dependency-free;
# tree-sitter is a scoped exception confined to `coyomap preindex` (see internal/docs/design-notes.md).
# Run `make deps` alone to refresh after editing pyproject deps.
deps: venv
	$(PY) -m pip install -e '$(REPO)[preindex]'

# Contributor setup: same as `deps` plus the test/type-check tooling (pytest, pyright) in the venv.
dev: venv
	$(PY) -m pip install -e '$(REPO)[preindex,dev]'

# The gates: the FULL test run and the type checker, in that order, on the whole suite.
#
# NO PATH AT ALL. `pytest` bare collects `testpaths` from pyproject.toml, which is `tests` AND
# `eval/tests`. Naming `tests` here was the same silent narrowing this comment warns about, one
# level up: it skipped all 602 eval tests, and a change that broke four of them passed the gates
# clean. A path narrows collection without saying so — `pytest tests/test_viewer_js.py` reports a
# clean run while skipping every other tier — so the bare command is the only one that means "the
# gates passed", and it cannot drift from `testpaths` again. Type errors are reported after the
# tests rather than short-circuiting, so one run tells you everything that is wrong.
# `-n auto` runs the suite across every core. It is not a tuning knob: 80% of the run was the 126
# browser tests, serial on a 14-core machine. Measured 2026-09-13 on the whole suite — 1 process
# 412s, 8 processes 131s, `auto` 57s, all 3412 passing at every width. Nothing shares state across
# processes (every server binds port 0, every test writes to its own temp dir), which is what makes
# the split safe rather than merely fast. Drop to `-n0` to read an interleaved failure in order.
gates:
	@$(PY) -m pytest -q -n auto; t=$$?; \
	echo ""; \
	$(PY) -m pyright tools/coyomap; p=$$?; \
	echo ""; \
	if [ $$t -ne 0 ] || [ $$p -ne 0 ]; then echo "GATES FAILED (pytest=$$t pyright=$$p)"; exit 1; fi; \
	echo "GATES PASSED"

# Land the worktree branch on main: merge main INTO the branch, run the gates on the result,
# fast-forward main FROM the main checkout (ref, index and files together), and go again if main
# moved meanwhile. Stops on a conflict for you to resolve here. Run from inside the worktree.
# Stdlib only, so it needs no venv of its own; the gates it runs use the main checkout's.
land:
	python3 tools/land.py

# Which tests notice a broken behaviour? Each break in BREAKS (a JSON file, see
# tools/break_check.py) is made in a scratch copy, one at a time, and the viewer's tests run on
# it: `make break-check BREAKS=breaks.json`. The checkout itself is never touched. Stdlib only,
# like land; the tests it runs use the main checkout's venv. Exit 1 when some break went unnoticed.
break-check:
	python3 tools/break_check.py --breaks $(BREAKS)

# Install the coyomap skill globally for all agents (macOS/Linux). Also builds the venv and
# installs the CLI (via `deps`) so a one-time `make install` covers everything.
# Copies SKILL.md into each skills home with this repo's absolute path baked in
# (replacing __COYOMAP_HOME__), so the skill points straight here with no runtime
# lookup. The method docs and tools are still read live from this repo, so they
# keep evolving without reinstalling. Re-run install only if you move the repo or
# edit SKILL.md itself.
install: deps
	@for dir in $(SKILLS_DIRS); do \
		rm -rf "$$dir/coyomap"; \
		mkdir -p "$$dir/coyomap"; \
		sed 's|__COYOMAP_HOME__|$(REPO)|g' skill/coyomap/SKILL.md > "$$dir/coyomap/SKILL.md"; \
		echo "Installed coyomap skill -> $$dir/coyomap (home: $(REPO))"; \
	done

# Install the coyomap-eval skill globally — SEPARATE from `install`, since the eval (method-quality
# regression) is opt-in. Same COYOMAP_HOME substitution, so the skill points back at this clone for the
# eval bundle under eval/ (method.md, thresholds.json, rubric.md) and the CLI. Depends on `deps`
# so the venv/CLI exist.
install-eval: deps
	@for dir in $(SKILLS_DIRS); do \
		rm -rf "$$dir/coyomap-eval"; \
		mkdir -p "$$dir/coyomap-eval"; \
		sed 's|__COYOMAP_HOME__|$(REPO)|g' eval/SKILL.md > "$$dir/coyomap-eval/SKILL.md"; \
		echo "Installed coyomap-eval skill -> $$dir/coyomap-eval (home: $(REPO))"; \
	done

# Install the coyomap-retro skill globally — SEPARATE again, and opt-in. The retro reviews a build
# that has ALREADY finished (its map + its chat transcript) and reports bugs / friction / method
# gaps; it builds nothing and changes nothing. Same COYOMAP_HOME substitution so it reads its recipe
# (eval/retro/method.md) and the method it audits from this clone.
install-retro: deps
	@for dir in $(SKILLS_DIRS); do \
		rm -rf "$$dir/coyomap-retro"; \
		mkdir -p "$$dir/coyomap-retro"; \
		sed 's|__COYOMAP_HOME__|$(REPO)|g' eval/retro/SKILL.md > "$$dir/coyomap-retro/SKILL.md"; \
		echo "Installed coyomap-retro skill -> $$dir/coyomap-retro (home: $(REPO))"; \
	done

# Both DEVELOPER skills at once. They are opt-in and always wanted together: eval answers "did my
# change make the maps worse?" and retro answers "what did that run reveal?" — two halves of the
# same feedback loop, and neither is meant for a user of coyomap. `install` (the user skill) is
# deliberately NOT included: installing the developer surface should never be a side effect of
# setting up the tool.
install-dev: install-eval install-retro
	@echo "Installed the developer skills (coyomap-eval + coyomap-retro). The user skill is \`make install\`."

uninstall-dev: uninstall-eval uninstall-retro
	@echo "Uninstalled the developer skills."

uninstall:
	@for dir in $(SKILLS_DIRS); do \
		rm -rf "$$dir/coyomap"; \
		echo "Uninstalled coyomap skill from $$dir/coyomap"; \
	done

uninstall-retro:
	@for dir in $(SKILLS_DIRS); do \
		rm -rf "$$dir/coyomap-retro"; \
		echo "Uninstalled coyomap-retro skill from $$dir/coyomap-retro"; \
	done

uninstall-eval:
	@for dir in $(SKILLS_DIRS); do \
		rm -rf "$$dir/coyomap-eval"; \
		echo "Uninstalled coyomap-eval skill from $$dir/coyomap-eval"; \
	done

# Start the local map server so the viewer's file browser + code viewer work (files read from git
# at each map's commit). Opens the landing page — add a project by browsing to its folder, or open a
# recent one. No disk scan; choices are remembered in ~/.coyomap/serve-recents.json. Ctrl-C to stop.
start: deps
	$(VENV)/bin/coyomap serve --port $(PORT) --open

# Same server, for someone working ON the viewer: an edit reaches the screen with nothing pressed.
# Two halves, and both are needed. `--dev` gives the map page a live reload, which covers
# viewer.js/css/html (served from disk per request, so an edit is live at once). The supervisor
# covers the Python, which the running process cannot pick up because the view bundle is built
# in-process: it restarts the server on a .py edit, and the page waits for the fresh process before
# reloading. NOT part of `start`: a person reading a map must not get a page that reloads under them.
# This repo is served too, so its own map is one click from the landing page.
dev-start: deps
	$(PY) tools/devserve.py $(REPO) $(PORT)

# Remove the repo-local venv (run `make install` again to rebuild it).
clean:
	rm -rf "$(VENV)"
	@echo "Removed $(VENV)"
