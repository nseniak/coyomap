# coyomap — Codebase Analysis

<!-- GENERATED VIEW — do not edit. The source of truth is project-map.json; regenerate this
     file with `coyomap render project-map.json project-map.md`. -->

> Built with the **coyomap** method. Behavioral layer first (Goal → Glossary → Roles →
> Use cases → Happy Path), then the structural machine (Components → Entry points /
> Model / Deps → Flows + Edges), joined at **use case ↔ flow**.
> The committed source of truth is `project-map.json` (JSON); this file is a generated
> view. IDs, cross-references, and confidence tags are validated by
> `coyomap validate project-map.json`.
> **Commit:** `76ca734` · **Committed:** `2026-09-09` · **Built:** `2026-09-09 02:02`

---

## T0 — Goal (the anchor)

coyomap maps a codebase its owner no longer holds in their head. A coding agent can write more code than anyone follows. The code runs fine until the day somebody needs to understand it.

coyomap reads the project and writes a map. The map says what the product does, who it is for, and what it is made of. Every box on it carries a plain sentence and a link into the code.

A person browses the map in a drillable viewer, and opens code only where they need it. The map is stored beside the code and pinned to one commit. A later change can be measured against that pin.

---

## Glossary — the ubiquitous language

| Term | Meaning | Defined / used in |
|---|---|---|
| **map** | The whole picture coyomap produces for one project: the diagrams, the plain sentence on every box, and the code links. | [model.md](method/model.md:3) |
| **baseline** | The map as currently accepted, pinned to one commit. A later code change is measured against it. | [method/](method/) |
| **build** | Analysing a project from scratch and writing a new map. It throws away hand edits to the old one. | [method/](method/) |
| **viewer** | The browser page that shows a map. It is served live and never stored as a file. | [tools/coyomap/viewer/](tools/coyomap/viewer/) |
| **view** | One tab in the viewer. Each answers a single question about the project. | [tools/coyomap/viewer/](tools/coyomap/viewer/) |
| **box** | One thing drawn on a view. An arrow between two boxes is a relation. | [views.py](tools/coyomap/views.py) |
| **code link** | The file and line a box points at. A box without one is ungrounded, which counts as a defect. | [anchors.py](tools/coyomap/anchors.py) |
| **use case** | One goal one party has, with the thing that starts it and the result it ends in. | [model.md](method/model.md:95) |
| **feature** | A group of use cases that serve one goal of the product. | [model.md](method/model.md:77) |
| **happy path** | One end to end run through the use cases that tells the product's story, with nothing going wrong. | [model.md](method/model.md:98) |
| **flow** | The numbered steps of one use case. Each step says who or what acts, on what. | [model.md](method/model.md:157) |
| **shared sub-flow** | A run of steps that several flows all run. It is written once and referred to by each of them. | [model.md](method/model.md:162) |
| **interface** | One place the product meets something that is not the product. | [model.md](method/model.md:458) |
| **way in** | One address, command or tool an interface is made of. | [model.md](method/model.md:115) |
| **door** | One crossing between a person and the product, at an interface, inside one flow. | [method/](method/) |
| **component** | One module sized piece of the code, drawn as a single box. | [model.md](method/model.md:103) |
| **subsystem** | A group of components, and of smaller subsystems under it. | [model.md](method/model.md:100) |
| **entity** | One real named type the code defines, with its fields and its links to other types. | [domain-cards.md](method/domain-cards.md:1) |
| **business rule** | One decision the product makes, written in product words, plus every place it is enforced. | [model.md](method/model.md:180) |
| **change impact** | The report saying what a code change does to the map. | [change-impact.md](method/change-impact.md) |
| **accept** | Folding a change impact report into the baseline and re-pinning it. | [change-impact.md](method/change-impact.md) |
| **the method** | The instructions a coding agent follows to build a map. Most of this product's real logic lives there, not in code. | [method.md](method.md:1) |
| **the skill** | The small file that lets a coding agent find this project and start following the instructions. | [SKILL.md](skill/coyomap/SKILL.md:1) |
| **fragment** | One worker's structured rows, written to a file and later merged into the map. | [assemble.py](tools/coyomap/assemble.py) |
| **gate** | An automatic check a map must pass. Failing one is a defect in the map. | [finalize.py](tools/coyomap/finalize.py) |
| **advisory** | A check that reports rather than blocks. It is answered by a fix or by a recorded reason. | [validate_model.py](tools/coyomap/validate_model.py) |
| **claim** | One statement the map makes about the code, which a fresh reader can try to disprove. | [audit_model.py](tools/coyomap/audit_model.py) |
| **skeptic** | A fresh reader given a batch of claims and the code, told to disprove each one. | [skeptic-contract.md](method/templates/skeptic-contract.md) |
| **verdict** | One skeptic's answer on one claim: it held up, the code contradicts it, or the code cannot settle it. | [grounding.py](tools/coyomap/grounding.py) |
| **grounding record** | The count of how many claims were challenged and how they came out, stored in the map. | [model.md](method/model.md:203) |
| **pre-index** | A measurement of the code tree, taken before the map is drawn. It says how heavy each folder is and where each name is defined. | [preindex.py](tools/coyomap/preindex.py) |
| **eval** | Scoring two maps of one project to say whether a change to the instructions helped or hurt. | [method.md](eval/method.md:1) |
| **retro** | Reading a finished build and its chat to find what went wrong in the run. | [method.md](eval/retro/method.md:1) |
| **Coyote Effect** | The situation this product exists for. Your agent wrote a lot of code, it runs, and you no longer know what is under your feet. | [README.md](README.md:19) |

---

## Roles (actors)

`Audience` says WHICH SIDE this actor is on: `internal` = the side of the company that ships the product,
`user` = everyone else. On a program it is whose machine it is, so a bought service is `internal`.
Every capability's audience is derived from it.

| Role | Kind | Audience | What they want | Use cases they drive |
|---|---|---|---|---|
| **Map owner** | human | user | a trustworthy map of their own project, and a cheap way to keep it in step with the code | UC1, UC2, UC3, UC4, UC7, UC8, UC9 |
| **Map reader** | human | user | to understand what a system does, top down, without reading all of its code | UC5, UC6 |
| **Method author** | human | internal | to know whether a change to the instructions made the maps better or worse | UC10, UC11 |

---

## Capabilities — what this product does

The use-case grouping. `Audience` is DERIVED from the roles driving its use cases, so nothing on a capability can contradict its own actors.

| ID | Capability | Audience | Purpose | Parent |
|---|---|---|---|---|
| **CAP1** | Mapping a project | user | Turns a codebase nobody can hold in their head into a map that is grounded in the code. |  |
| **CAP2** | Keeping a map current | user | Says what a code change did to the map, and folds the answer back into the baseline. |  |
| **CAP3** | Reading a map | user | Puts the map in front of a person, drillable, with the code one click away. |  |
| **CAP4** | Setting coyomap up | user | Puts the command into a coding agent and builds the tools that command drives. |  |
| **CAP5** | Improving the method | internal | Measures whether a change to the instructions made the maps better or worse. |  |

---

## Use cases

### Mapping a project *(CAP1)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC2** | Build a project's first map | Map owner | A person asks their coding agent for a map of a project that has none. | A map of that project exists, pinned to the commit it describes. |
| **UC3** | Leave code off the map | Map owner | A person names committed code the map is not meant to describe. | Later maps leave that code out, and every count the tools print says so. |

### Keeping a map current *(CAP2)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC7** | See what a code change did to the map | Map owner | The code has moved on since the map was pinned. | A report names the parts of the map the change touched. |
| **UC8** | Fold a change report into the baseline | Map owner | A person agrees the change report is right. | The map is edited to match, re-pinned, and checked again. |
| **UC9** | Change the map by asking | Map owner | A person asks in plain language for a part of the map to move, split or be renamed. | The map is edited in place and passes its checks. |

### Reading a map *(CAP3)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC4** | Serve the maps on this machine | Map owner | A person starts the local map server. | Every project they have mapped is listed on one page in their browser. |
| **UC5** | Explore a project's map | Map reader | A person opens a project's map. | They see what the product does and drill from one feature down to a single box. |
| **UC6** | Open the code behind a box | Map reader | A reader picks the code link on a box. | The file opens beside the map at that line. One more press hands it to their editor or the code host. |

### Setting coyomap up *(CAP4)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC1** | Install coyomap into a coding agent | Map owner | Someone who has cloned this project asks to install it. | Their coding agent gains a new command, and the tools it drives are built and ready. |

### Improving the method *(CAP5)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC10** | Score whether the method got better | Method author | Someone changed the instructions and wants to know the cost. | Two maps of one project are scored and compared, with a verdict. |
| **UC11** | Review a finished build | Method author | A build has finished and its chat is on disk. | A report names the friction, the bugs and the gaps that run revealed. |


---

## Happy Path — the spine (an ordered walk through the use cases)

The happy-path ordering of use cases. Each step IS a use case (its `*(UCn)*` tag
names it); the step's detail lives in that use case's T6 flow. An optional `why:`
line records the prerequisite that fixes the step's position.

**HP1 — Install coyomap into a coding agent** *(UC1)*
**HP2 — Build a project's first map** *(UC2)*
why: needs the command installed at HP1
**HP3 — Serve the maps on this machine** *(UC4)*
why: needs a built map to serve, from HP2
**HP4 — Explore a project's map** *(UC5)*
why: needs the server running from HP3
**HP5 — Open the code behind a box** *(UC6)*
why: needs a box on screen, reached at HP4
**HP6 — See what a code change did to the map** *(UC7)*
why: needs the pinned baseline written at HP2
**HP7 — Fold a change report into the baseline** *(UC8)*
why: needs the change report produced at HP6

---

## Subsystems (S) — the container altitude

| ID | Subsystem | Purpose | Parent | Tech | Source | Conf. |
|---|---|---|---|---|---|---|
| **S1** | Method | Holds the instructions a coding agent follows to build, check and ship a map. Most of this product's logic lives here, not in code. |  |  | method.md:1 | verified |
| **S10** | Map content instructions | Says what a map must contain, one section at a time. It runs from the product story down to the code. | S1 |  | method.md:26 | inferred |
| **S11** | Build process instructions | Says how a build runs. Which mode to enter, how to split the work, how to verify it, how to close. | S1 |  | method.md:1330 | inferred |
| **S12** | Specs and worker briefs | The stored shape of a map, the briefs handed to fan-out workers, and the checks that keep the instructions honest. | S1 |  | method/ | inferred |
| **S13** | Delivery and documentation | How a coding agent finds this product, and what a person reads before using or changing it. | S1 |  | skill/ | inferred |
| **S2** | Map data and checks | Defines what a map is and merges each worker's rows into one. Refuses a map that is not well formed. |  | Python ([pyproject.toml](pyproject.toml:9)) | tools/coyomap/model.py:1 | verified |
| **S20** | Map data | The typed shape of a map, its shared words, and the merge that turns many workers' rows into one map. | S2 |  | tools/coyomap/model.py:1 | verified |
| **S21** | Map checks | Five families of check that ask whether a map is well formed, from its shape to its stored data. | S2 |  | tools/coyomap/validate_model.py:1 | verified |
| **S3** | Build and upkeep commands | The commands a coding agent runs during a build. Sizing, grouping, challenging the claims, closing, and measuring a later code change. |  | Python ([pyproject.toml](pyproject.toml:9)) | tools/coyomap/cli.py:1 | inferred |
| **S30** | Command surface | What a person types, and what the briefing says before any work starts. Also what the run records about itself. | S3 |  | tools/coyomap/cli.py:1 | inferred |
| **S31** | Build steps | Sizing the code and leaving parts of it out. Assigning every element to its group, and measuring how crowded each screen is. | S3 |  | tools/coyomap/preindex.py:1 | inferred |
| **S32** | Verification and close | Turns the map against itself and records how its claims held up. Applies the fixes, then runs the closing sequence. | S3 |  | tools/coyomap/audit_model.py:1 | inferred |
| **S4** | Map viewer | Turns a stored map into pictures and serves them beside the project's own code. Draws the page a person reads. |  |  | tools/coyomap/viewer/ | verified |
| **S40** | View data | Builds every diagram and every page's facts from the stored map, on demand. | S4 | Python ([pyproject.toml](pyproject.toml:9)) | tools/coyomap/views.py:1 | verified |
| **S41** | Map server | Serves the viewer page, the map data and the project's own files, on this machine only. | S4 | Python ([pyproject.toml](pyproject.toml:9)) | tools/coyomap/viewer/serve.py:1 | verified |
| **S42** | Page frame | Loads a map into the browser and holds the tabs and the trail. Keeps the address in step with the screen. | S4 | JavaScript ([pyproject.toml](pyproject.toml:56)) | tools/coyomap/viewer/viewer.js:1 | inferred |
| **S43** | Diagrams and cards | Draws the boxes, answers a click, explains the selected thing, and shows the code behind it. | S4 | JavaScript ([pyproject.toml](pyproject.toml:56)) | tools/coyomap/viewer/viewer.js:1265 | inferred |
| **S44** | View pages | The screens themselves: what the product does, what it stores, what it decides, and what a change touched. | S4 | JavaScript ([pyproject.toml](pyproject.toml:56)) | tools/coyomap/viewer/viewer.js:10089 | inferred |
| **S5** | Method quality | Answers the two questions a person changing the instructions has. Did the maps get worse, and what did that run reveal? |  | Python ([pyproject.toml](pyproject.toml:48)) | eval/ | verified |
| **S50** | Map scoring | Measures one map and compares it against an accepted one. Also tests whether the challengers catch a planted falsehood. | S5 |  | eval/tools/coyomap_eval/profile.py:1 | verified |
| **S51** | Build review | Reads what a build actually did and what it cost, and refuses to review a run that has not finished. | S5 |  | eval/tools/coyomap_eval/transcript.py:1 | verified |
| **S52** | Eval upkeep | Files an old map out of the way, and bundles a map with the chat that made it. Keeps the numbers written in the code honest. | S5 |  | eval/tools/coyomap_eval/archive.py:1 | verified |

---

## T1 — Components

| ID | Component | Subsystem | Purpose | Depends on | Conf. | Files | Runs in |
|---|---|---|---|---|---|---|---|
| **C1** | Map model | S20 | Defines every kind of thing a map can hold. Reads a map file back and refuses one whose shape is wrong. |  | verified | tools/coyomap/model.py | coyomap command line |
| **C2** | Shared map grammar | S20 | Holds the shared words and formats every other part of the map reads. |  | verified | tools/coyomap/grammar.py · tools/coyomap/anchors.py · tools/coyomap/records.py · tools/coyomap/pathmatch.py · tools/coyomap/pysrc.py | coyomap command line |
| **C3** | Map schema document | S20 | Writes a machine-readable description of the map file, for editors and other tools to read. |  | verified | tools/coyomap/json_schema.py | coyomap command line |
| **C4** | Map assembly | S20 | Merges the pieces each build agent returned into one map. Refuses two pieces that name the same thing twice. |  | verified | tools/coyomap/assemble.py | coyomap command line |
| **C5** | Fragment self-check | S20 | Checks one agent's piece of the map before it is handed in. The agent that made a mistake is the one that fixes it. |  | verified | tools/coyomap/lint_fragment.py | coyomap command line |
| **C6** | Shape checks | S21 | Checks that every name in the map points at something real. Also checks that each code link is well formed and really exists. |  | verified | tools/coyomap/validate_model.py · tools/coyomap/validate_analysis.py | coyomap command line |
| **C7** | Story checks | S21 | Checks the use cases, their flows and the happy path against each other. Reports the parts of the code no story covers. |  | inferred | tools/coyomap/validate_model.py | coyomap command line |
| **C8** | Rule checks | S21 | Checks that each business rule names real code lines. Also writes down which files the map says guard access. |  | verified | tools/coyomap/validate_model.py · tools/coyomap/access_surface.py | coyomap command line |
| **C9** | Wiring checks | S21 | Checks how the product connects: its interfaces, its ways in, the services it calls and the processes it runs in. |  | inferred | tools/coyomap/validate_model.py | coyomap command line |
| **C10** | Data checks | S21 | Checks the saved records, their stores, who owns each data area, and how much of the map was verified. |  | inferred | tools/coyomap/validate_model.py · tools/coyomap/areas.py | coyomap command line |
| **C100** | Eval command line | S52 | Routes each typed eval sub-command to the checker that answers it. Loads that checker only when it is asked for. | Every other checker in this tool, each opened at the moment its sub-command is typed. | verified | eval/tools/coyomap_eval/cli.py · eval/tools/coyomap_eval/__init__.py | coyomap-eval command line |
| **C101** | Map profile | S50 | Reduces one built map to the numbers two builds can be compared on. Two maps of one project never share wording, so counts are what survives. | The main tool's own map reader and its two checkers, so a map is never measured through a second reading of it. | verified | eval/tools/coyomap_eval/profile.py · eval/tools/coyomap_eval/legacy_map.py | coyomap-eval command line |
| **C102** | Baseline comparison | S50 | Judges a fresh map against the accepted one. Returns one word: as good, drifted, or worse. | The numbers a map profile produces, and the judged scores, when both sides carry them. | verified | eval/tools/coyomap_eval/compare.py | coyomap-eval command line |
| **C103** | Judge report | S50 | Folds many skeptics' verdicts and many judges' marks into one quality report. Never talks to a model itself, so the arithmetic can be tested alone. | The main tool's list of risky statements, which it samples rather than re-derives. | verified | eval/tools/coyomap_eval/judge.py | coyomap-eval command line |
| **C104** | Eval run | S50 | Runs one scoring pass end to end and files everything it produced. Can then promote that run to be the accepted baseline. | The map profile, the baseline comparison and the judge report, plus the main tool's renderer for the archived views. | verified | eval/tools/coyomap_eval/run.py | coyomap-eval command line |
| **C105** | Lost arrows | S50 | Finds the relations a rebuild dropped. Re-reads each dropped relation's recorded line to say whether the code still does it. | The code history, to refuse the check when the two maps describe different code. | verified | eval/tools/coyomap_eval/arrows.py | coyomap-eval command line |
| **C106** | Rebuild archive | S52 | Moves a project's current map aside so the next build starts from nothing. Moves, never deletes: the old map is what the new one is compared against. | Nothing but the file system under the mapped project. | verified | eval/tools/coyomap_eval/archive.py | coyomap-eval command line |
| **C107** | Transcript reader | S51 | Turns a build's raw chat log into one record per model answer. The log stores one answer as many rows, so counting rows gets every later number wrong. | The coding agent's own chat logs on disk. | inferred | eval/tools/coyomap_eval/transcript.py | coyomap-eval command line |
| **C108** | Build cost | S51 | Reports what one build spent in time and tokens. Divides both by how much map the build produced. Two builds of different sizes then read side by side. | The transcript reader, for the lead's log and every helper's log beside it. | verified | eval/tools/coyomap_eval/cost.py | coyomap-eval command line |
| **C109** | Process scorecard | S51 | Scores whether the build agent behaved as the method says, one checked rule at a time. Reports numbers, never a pass or a fail. | The transcript reader for what the agent did, the build cost report for how long each helper really ran, and the finished map for the rules whose subject is the map. | inferred | eval/tools/coyomap_eval/process_scorecard.py | coyomap-eval command line |
| **C110** | Retro precheck | S51 | Refuses a retrospective while the build it would read is still running. A build stamps who made it near the end, so mid-run the stamp still names the previous build. | The mapped project's map folder, and the coding agent's chat logs for other live sessions. | verified | eval/tools/coyomap_eval/retro_precheck.py | coyomap-eval command line |
| **C111** | Ledger check | S51 | Asks the code history whether a retrospective's finished items really shipped. An item still marked open, whose named change is already merged, gets proposed again for nothing. | The code history of the clone holding the changes a ledger row names. | verified | eval/tools/coyomap_eval/ledger.py | coyomap-eval command line |
| **C112** | Live number ledger | S52 | Re-measures the counts the tools state about a map that keeps changing. Each sentence is written once in the code and once here. Nothing then has to guess which sum produced the number. | The main tool's own measuring functions, called rather than copied, plus the live maps they read. | verified | eval/tools/coyomap_eval/live_numbers.py | coyomap-eval command line |
| **C113** | Skeptic recall test | S50 | Plants claims that are false by construction and keeps the answer key. Counts how many of them the skeptics caught, which is a number that means something on its own. | The source tree, so a moved line lands somewhere real instead of past the end of the file. | verified | eval/tools/coyomap_eval/mutate.py | coyomap-eval command line |
| **C45** | Code survey | S31 | Measures how big a project's code is before the map is drawn. |  | verified | tools/coyomap/preindex.py · tools/coyomap/preindex_lib.py | coyomap command line |
| **C46** | Ignore list | S31 | Lets a project declare which of its own code the map must leave out. |  | verified | tools/coyomap/ignorefile.py | coyomap command line |
| **C47** | Assignment rules | S31 | Records where every mapped thing belongs, so a rebuild keeps the decision. |  | verified | tools/coyomap/reconcile.py · tools/coyomap/reconcile_build.py | coyomap command line |
| **C48** | Diagram balance | S31 | Reports how crowded each screen of the map is. |  | verified | tools/coyomap/balance.py · tools/coyomap/balance_lib.py | coyomap command line |
| **C49** | Change impact | S3 | Works out which parts of the map a code change touches. |  | verified | tools/coyomap/impact_lib.py · tools/coyomap/impact_ripple.py · tools/coyomap/impact_git.py | coyomap command line |
| **C50** | Map and transcript backup | S52 | Bundles a finished map with the conversation that produced it. |  | verified | tools/map_backup.py | coyomap command line |
| **C51** | Live reload supervisor | S41 | Restarts the map server when someone editing the viewer changes its code. |  | verified | tools/devserve.py |  |
| **C120** | Product description instructions | S10 | Tells the mapping agent to describe the product before reading code. It orders the goal, the shared words, the people and their goals. The one successful run through those goals comes last. |  | verified | method.md | coyomap skill |
| **C121** | Code inventory instructions | S10 | Says how to list what the product is made of, area by area. Every box gets a plain sentence, a code link and a confidence label. Outside services and the ways in are listed the same way. |  | verified | method.md | coyomap skill |
| **C122** | Outside edge instructions | S10 | Says how to name every place the product meets the outside world. Each place gets one word for what it is, and a side saying whose design it is. It also says how a story crosses one, in both directions. |  | verified | method.md | coyomap skill |
| **C123** | Data and step instructions | S10 | Says how to write the records the product keeps and the steps of each goal. A step names who acts, on what, and which way the data moves. Machinery shared by several goals is written once and referenced. |  | verified | method.md | coyomap skill |
| **C124** | Operations and decision instructions | S10 | Says how to record what runs, what is watched, what is configured and what the product decides. A decision is only worth recording when a product person could have chosen otherwise. Test coverage is measured against the map, never against line counts. |  | verified | method.md | coyomap skill |
| **C125** | Cross-cutting build instructions | S11 | Holds the rules that apply to every part of a build. It says how to write text a reader meets alone, with no page around it. It also sets the order of work, the tools to reach for, and how big one box may be. |  | verified | method.md | coyomap skill |
| **C126** | Fan-out phase instructions | S11 | Plans the parallel work of a build in three phases. Many agents gather the pieces, one agent merges them, then many agents trace the goals. It says how to size each slice, brief it and wait for the batch. |  | verified | method.md | coyomap skill |
| **C127** | Verification phase instructions | S11 | Plans what happens once every goal has been traced. Fresh agents try to disprove each claim the map makes, against the code. Two more passes write what the product decides and measure what the tests cover. |  | verified | method.md | coyomap skill |
| **C128** | Closing sequence instructions | S11 | Runs the closing steps that turn a finished map into a committed one. Corrections land, the record of what was checked is written, then the gates run. It ends by telling the reader where to open the map. |  | verified | method.md | coyomap skill |
| **C129** | Map model spec | S12 | States every field a map may hold and the exact shape of each. Names, code links and closed word lists are all fixed here. It also says how each part of the map is drawn on screen. |  | inferred | method/model.md · method/domain-cards.md · method/diagrams.md · method/project-map.schema.json | coyomap skill |
| **C130** | Mode dispatch instructions | S11 | Decides which job to do when someone calls coyomap on a project. Build a first map, report a code change, or fold a report in. It briefs the person on what will be read before anything starts. |  | verified | method/dispatch.md | coyomap skill |
| **C131** | Change impact instructions | S11 | Says how to report what a code change does to an existing map. The report carries the exact new text for every box it touches. Folding the report in is then mechanical, with no fresh reading of code. |  | verified | method/change-impact.md | coyomap skill |
| **C132** | Fan-out worker contracts | S12 | Holds the briefs handed word for word to the agents a build fans out to. One brief per job, from gathering the pieces to disproving the finished claims. The two briefs whose agents write map prose also carry the shared writing rules. |  | verified | method/templates/harvest-contract.md · method/templates/t5-addendum.md · method/templates/trace-contract.md · method/templates/doors-contract.md · method/templates/rules-contract.md · method/templates/skeptic-contract.md · method/templates/closer-contract.md · method/templates/gapfill-contract.md · method/templates/writing-rules.md · method/templates/project-map.template.md | coyomap skill |
| **C133** | Method regression checks | S12 | Holds one written promise per change to the method or the tools. Each file says what the next build should do differently, and what a backfire would look like. A review of a finished build runs every check the change range added. |  | inferred | method/retro-checks/README.md | coyomap skill |
| **C134** | Build skill pointer | S13 | Points a coding agent at this repository so the map commands work. Kept deliberately thin, because a copy is installed into the agent and goes stale. It names the clone path and the one document to read. |  | verified | skill/coyomap/SKILL.md | coyomap skill |
| **C135** | Map quality eval instructions | S13 | Says how to score two maps of the same code and tell which one is better. A map is scored on counts, well-formedness, coverage and a model's judgement. Both maps must describe the same code, or the comparison means nothing. |  | verified | eval/SKILL.md · eval/method.md · eval/rubric.md · eval/README.md · eval/blind-build.md | coyomap-eval skill |
| **C136** | Build retrospective instructions | S13 | Says how to review one finished build from its map and its chat. The review reports what the run revealed about the tools and the method. It changes nothing, and a standing backlog carries every proposal forward. |  | inferred | eval/retro/SKILL.md · eval/retro/method.md · eval/retro/backlog.md | coyomap-retro skill |
| **C137** | Public documentation | S13 | Explains to a newcomer what coyomap is, why it exists and how to install it. A longer page walks through how a map gets built, phase by phase. Both are read on the web by a person, never by a mapping agent. |  | inferred | README.md · docs/how-coyomap-works.html |  |
| **C138** | Contributor guide | S13 | Says how to work on coyomap itself, for a person and for an agent alike. It names what each folder is for and which tests a given change needs. It also holds the design philosophy and the words this project uses. |  | verified | CONTRIBUTING.md · CLAUDE.md · .github/PULL_REQUEST_TEMPLATE.md · .github/ISSUE_TEMPLATE/bug_report.yml · .github/ISSUE_TEMPLATE/idea.yml · .github/ISSUE_TEMPLATE/config.yml |  |
| **C139** | Method rationale record | S13 | Keeps the story of the build that made each method rule necessary. Storing those stories here keeps them out of the text every build agent reads. A test checks that each entry still quotes a rule that exists. |  | inferred | internal/docs/method-rationale.md |  |
| **C20** | Command line | S30 | Routes each typed coyomap command to the tool that runs it. The same layer decides how much of a long finding list a reader sees. |  | verified | tools/coyomap/cli.py · tools/coyomap/subverb_help.py · tools/coyomap/reporting.py | coyomap command line |
| **C21** | Map checks | S32 | Reads a finished map and reports where it contradicts itself. The same family flags a code link pointing at a line that cannot act. |  | inferred | tools/coyomap/audit_model.py · tools/coyomap/anchor_drift.py · tools/coyomap/prose.py | coyomap command line |
| **C22** | Grounding record | S32 | Turns the skeptics' verdict files into the map's honesty record. The four counts a gate blocks on are derived, never hand-tallied. |  | inferred | tools/coyomap/grounding.py | coyomap command line |
| **C23** | Map editor | S32 | Applies one mechanical correction to a stored map in place. An edit matching no row, or more than one, is refused rather than guessed. |  | inferred | tools/coyomap/fix.py · tools/coyomap/record.py | coyomap command line |
| **C24** | Map reader | S30 | Reads a map and never changes it. Three answers: one element's stored record, what two maps differ on, and the evidence behind a claim. |  | verified | tools/coyomap/dump.py · tools/coyomap/mapdiff.py · tools/coyomap/context.py | coyomap command line |
| **C25** | Build closer | S32 | Runs a build's closing steps in order and stops at the first failure. The last step writes one pre-commit verdict to a file. |  | inferred | tools/coyomap/ship.py · tools/coyomap/finalize.py | coyomap command line |
| **C26** | Build briefing | S30 | Says which files a build will read and which commit its map will name. A second command prints the exact brief each helper agent is sent. |  | verified | tools/coyomap/scope.py · tools/coyomap/contract.py | coyomap command line |
| **C27** | Build log | S30 | Records which session built a map, and when. Beside that it records how long each slice of the build took. |  | verified | tools/coyomap/provenance.py · tools/coyomap/timings.py | coyomap command line |
| **C80** | Map rendering | S40 | Turns a stored map into the readable file kept beside the code. Also builds the boxes and arrows the browser draws. |  | verified | tools/coyomap/views.py · tools/coyomap/viewer/render.py | coyomap command line, Map server |
| **C81** | Feature facts | S40 | Works out what each feature owns: its people, its decisions, its records and the doors reaching it. |  | verified | tools/coyomap/features.py | coyomap command line, Map server |
| **C82** | Diagram builder | S40 | Draws every diagram, timeline and flow of one map, ready for the browser page to show. |  | verified | tools/coyomap/viewer/gen_viewer.py | coyomap command line, Map server |
| **C83** | Map server | S41 | Serves every map on this machine at a local web address. Reads a project's own code from its version history. |  | verified | tools/coyomap/viewer/serve.py · tools/coyomap/viewer/diffmap.py | Map server |
| **C84** | File browser | S41 | Lists a project's folders and files, marking each one by how far the map covers it. |  | verified | tools/coyomap/viewer/filetree.py | Map server |
| **C85** | Remembered projects | S41 | Keeps the list of project folders a person has opened, so each map is one click away next time. |  | verified | tools/coyomap/viewer/recents.py | Map server |
| **C60** | Map loader | S42 | Loads the whole map from the server when the page opens, before any screen is drawn. Glossary words in the text then become definitions you can read in place. |  | verified |  | Map server |
| **C61** | Element cards | S43 | Draws one card for anything on the map: its name, a tag saying its type, one sentence. Clicking a card opens that thing. |  | verified |  | Map server |
| **C62** | Diagram canvas | S43 | Draws a view's picture from the drawing the map recorded. Selecting a box lights it and everything it touches, and dims the rest. |  | verified |  | Map server |
| **C63** | Diagram clicks | S43 | Decides what a click does on each drawn box and arrow, view by view. Holding a key drills into a box instead of selecting it. |  | verified |  | Map server |
| **C64** | Info pane | S43 | Shows what you selected: a card floating over the picture, or a drawer along the bottom. What the pane holds changes with the kind of thing selected. |  | verified | tools/coyomap/viewer/viewer.js · tools/coyomap/viewer/info-pane.md | Map server |
| **C65** | Trail and screen address | S42 | Keeps the tabs, the trail and the browser address in step with the screen on show. Copying that address gives someone else the same screen. |  | verified |  | Map server |
| **C66** | Product pages | S44 | Draws the pages that say what the product is for and what it does. Covers the overview, the features, the happy path, actor pages and the glossary. |  | verified |  | Map server |
| **C67** | Storage, tests and system pages | S44 | Draws the tables for where data is kept, how far the tests reach, and the operational lists. |  | inferred |  | Map server |
| **C68** | Rules and interfaces pages | S44 | Draws the decisions the product makes and the places it meets the outside world. Each rule and each interface has a page of its own. |  | verified |  | Map server |
| **C69** | Source column | S43 | Shows the mapped project's files, and the source of the one you open, at the map's commit. Selecting a box on a picture opens its file here. |  | verified |  | Map server |
| **C70** | Viewer shell | S42 | Holds the page frame: the title bar, the tab rows, the panes and the settings dialog. Also wires the keyboard and the first-run guide. |  | verified | tools/coyomap/viewer/viewer.html · tools/coyomap/viewer/viewer.js | Map server |
| **C71** | Map search | S42 | Finds anything in the map by name as you type: elements, files, folders, glossary words. Picking a result opens it where it lives. |  | verified |  | Map server |
| **C72** | Impact explorer | S44 | Projects a code change onto the map and marks what that change touches, plus what ripples out from it. Hidden from the title bar for now. |  | verified |  | Map server |
| **C73** | Viewer styles | S42 | Holds every colour, size and layout rule the viewer page draws itself with. One stylesheet covers every view. |  | inferred | tools/coyomap/viewer/viewer.css | Map server |

---

## T2 — External dependencies

| ID | Name | Kind | Bucket | Type | Used for | Where configured | Conf. | Package | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| **D90** | Git | platform | Source and history | version control program | Lists a project's files, and reads any file exactly as it stood at the map's pinned commit. | [impact_git.py](tools/coyomap/impact_git.py:50) | verified | git (external program, no declared version) | [preindex_lib.py](tools/coyomap/preindex_lib.py:190) — Asks git for the tracked and untracked files, so ignored output never enters the map. · [serve.py](tools/coyomap/viewer/serve.py:317) — Reads a file's contents at the map's commit, so the code viewer shows the mapped version. · [provenance.py](tools/coyomap/provenance.py:125) — Reads the commit a map is pinned to when a build is stamped. · [ledger.py](eval/tools/coyomap_eval/ledger.py:87) — Checks whether a recorded commit is an ancestor of the current one. |
| **D91** | Local file system | platform | Infrastructure & runtime | operating system storage | Holds every project's map folder, the tool's own environment, and the remembered list of projects. | [assemble.py](tools/coyomap/assemble.py:978) | verified |  | [assemble.py](tools/coyomap/assemble.py:978) — Writes the finished map beside the project's code. · [recents.py](tools/coyomap/viewer/recents.py:44) — Saves the list of projects the server offers on its landing page. |
| **D92** | Web browser | platform | Infrastructure & runtime | desktop browser | Opens and draws the map viewer page for a person on this machine. | [serve.py](tools/coyomap/viewer/serve.py:895) | verified |  | [serve.py](tools/coyomap/viewer/serve.py:895) — Opens the server's landing page in the person's browser when asked to. · [Makefile](Makefile:135) — The start target launches the server and opens the page. |
| **D93** | Code editor | platform | Code navigation | desktop editor | Receives a file and a line from the map, so a person opens that exact spot in their editor. | [viewer.js](tools/coyomap/viewer/viewer.js:14925) | verified |  | [viewer.js](tools/coyomap/viewer/viewer.js:14798) — Lists the editors the viewer can hand a file to, each with its own address form. · [viewer.js](tools/coyomap/viewer/viewer.js:14925) — Hands the chosen editor the file and line, which the operating system opens. |
| **D94** | GitHub | service | Code navigation | code host | Shows a mapped file on the web, pinned to the commit the map was built at. | [viewer.js](tools/coyomap/viewer/viewer.js:14928) | verified |  | [viewer.js](tools/coyomap/viewer/viewer.js:14903) — Builds the web address of a mapped file at the map's commit. · [viewer.js](tools/coyomap/viewer/viewer.js:14928) — Opens that address in a new tab when no editor is chosen. · [config.yml](.github/ISSUE_TEMPLATE/config.yml:4) — Bug and idea reports, and private security reports, are filed on the code host. |
| **D95** | Coding agent | platform | AI & ML | AI coding assistant | Runs the installed skill that drives a map build, and names the conversation a build is stamped with. | [Makefile](Makefile:17) | verified |  | [Makefile](Makefile:74) — Copies the skill into each agent's skills folder with this clone's path filled in. · [provenance.py](tools/coyomap/provenance.py:209) — Reads the conversation identifier the agent publishes, so a map records which chat produced it. · [retro_precheck.py](eval/tools/coyomap_eval/retro_precheck.py:278) — Reads the same conversation identifier before a build review is allowed to start. |
| **D96** | jsDelivr | service | Infrastructure & runtime | content delivery network | Serves the two drawing libraries the viewer page loads in the browser. | [viewer.html](tools/coyomap/viewer/viewer.html:16) | verified |  | [viewer.html](tools/coyomap/viewer/viewer.html:19) — The page loads the diagram library from this host, pinned to a version and a checksum. |
| **D97** | Mermaid | library | Frontend / UI | diagram renderer | Draws every diagram on the viewer page from the text the tool generates. | [viewer.html](tools/coyomap/viewer/viewer.html:19) | verified | mermaid 11.15.0 | [viewer.html](tools/coyomap/viewer/viewer.html:19) — Loaded as one self-contained bundle so the checksum covers the whole library. · [gen_viewer.py](tools/coyomap/viewer/gen_viewer.py:217) — Generates the diagram text this library turns into a picture. |
| **D98** | svg-pan-zoom | library | Frontend / UI | diagram interaction | Lets a person pan and zoom a drawn diagram in the viewer. | [viewer.html](tools/coyomap/viewer/viewer.html:16) | verified | svg-pan-zoom 3.6.1 | [viewer.html](tools/coyomap/viewer/viewer.html:16) — Loaded from the delivery network, pinned to a version and a checksum. |
| **D99** | tree-sitter | library | Source parsing | source parser | Reads symbols and imports out of source files in many languages during the first pass. | [pyproject.toml](pyproject.toml:19) | verified | tree-sitter >=0.21 | [preindex_lib.py](tools/coyomap/preindex_lib.py:388) — Builds a parser for one language, and gives up quietly when the library is absent. · [pyproject.toml](pyproject.toml:18) — Declared as an optional extra, so the core of the tool stays free of outside packages. |
| **D100** | tree-sitter language pack | library | Source parsing | parser grammars | Supplies the per-language grammars the source parser needs. | [pyproject.toml](pyproject.toml:20) | verified | tree-sitter-language-pack >=0.2 | [preindex_lib.py](tools/coyomap/preindex_lib.py:373) — Tries to load the pack, and records why it failed when it is missing. · [preindex_lib.py](tools/coyomap/preindex_lib.py:389) — Fetches one language's grammar for the parser. |
| **D101** | pytest | library | Testing & type checking | test runner | Runs the whole test suite, which is the first half of the checks a change must pass. | [pyproject.toml](pyproject.toml:25) | verified | pytest >=8 | [Makefile](Makefile:56) — The checks target runs the suite with no folder named, so no tests are silently skipped. · [pyproject.toml](pyproject.toml:40) — Declares the two test folders that a bare run collects. |
| **D102** | pyright | library | Testing & type checking | type checker | Checks the tool's Python types, which is the second half of the checks a change must pass. | [pyproject.toml](pyproject.toml:26) | verified | pyright >=1.1 | [Makefile](Makefile:58) — The checks target runs the type checker after the tests, so one run reports everything. · [pyrightconfig.json](pyrightconfig.json:2) — Tells the type checker where the two source folders live. |
| **D103** | Playwright | library | Testing & type checking | browser automation | Drives a real browser for the one test file that can see a viewer bug on screen. | [pyproject.toml](pyproject.toml:31) | inferred | playwright >=1.40 | [pyproject.toml](pyproject.toml:28) — Declared as optional at run time, so the on-screen viewer test skips itself when the browser is missing. |
| **D104** | setuptools | library | Build & packaging | package builder | Builds and installs the tool from the repo, including the viewer files that ship with it. | [pyproject.toml](pyproject.toml:2) | inferred | setuptools >=64 | [pyproject.toml](pyproject.toml:48) — Maps the two source folders onto the two installed packages. · [pyproject.toml](pyproject.toml:56) — Ships the viewer page, its styles and its script inside the installed package. |
| **D105** | Coding agent chat logs | platform | AI & ML | agent harness | Reads what the coding agent actually did during a build. Three of the checks here have no other source for that. |  | verified |  | [retro_precheck.py](eval/tools/coyomap_eval/retro_precheck.py:59) — Finds the folder holding every chat log for the mapped project, to spot a build still writing. · [cost.py](eval/tools/coyomap_eval/cost.py:264) — Finds each helper agent's own log beside the main one, which is most of a build's spend. |
| **D160** | highlight.js | library | Frontend / UI | syntax colouring | Colours the source code shown in the viewer's code pane. | [viewer.js](tools/coyomap/viewer/viewer.js:14097) | verified | highlight.js 11.9.0 | [viewer.js](tools/coyomap/viewer/viewer.js:14097) — Loaded only once a file is opened, with a checksum the browser checks. |
| **D161** | cdnjs | service | Infrastructure & runtime | content delivery network | Serves the code-colouring library the viewer page loads when a file is opened. | [viewer.js](tools/coyomap/viewer/viewer.js:14083) | verified |  | [viewer.js](tools/coyomap/viewer/viewer.js:14083) — Names the host the colouring library and its stylesheet are fetched from. |

---

## T2b — Interfaces (the product's outside edge)

| ID | Name | Side | Kind | Facing | Crosses | What it is | Actors | Ways in | Deps | Source | Conf. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **I1** | Command line | ours | command-line | user | in, out | Every command a person or their coding agent types to build, check, edit or ship a map. | R1 | 38 |  | [cli.py](tools/coyomap/cli.py:139) |  |
| **I2** | Method quality command line | ours | command-line | operator | in, out | A second command line for whoever changes the instructions. It scores maps and reads finished builds. | R3 | 17 |  | [cli.py](eval/tools/coyomap_eval/cli.py:69) |  |
| **I3** | Map viewer | ours | screen | user | in, out | The browser page that shows a map, and every address that page fetches its data and its source from. | R1, R2 | 39 |  | [serve.py](tools/coyomap/viewer/serve.py:869) |  |
| **I4** | Build skill | ours | agent-tools | user | in, out | The file a coding agent reads when a person types the slash command. It points the agent at the instructions. | R1 | 1 | D95 | [SKILL.md](skill/coyomap/SKILL.md:27) |  |
| **I5** | Developer skills | ours | agent-tools | operator | in, out | Two more files a coding agent reads. One scores a map's quality, the other reviews a finished build. | R3 | 2 | D95 | [SKILL.md](eval/SKILL.md:1) |  |
| **I6** | Map folder | ours | file | user | in, out | What a project commits beside its code: the stored map, its readable view, the code survey and the build stamp. | R1 |  | D91 | [assemble.py](tools/coyomap/assemble.py:978) |  |
| **I7** | Settings | ours | settings | operator | in | Values set outside a browser: the ignore list beside a map, and the environment variables the tools read. | R1 |  | D91 |  |  |
| **I8** | Project source | theirs | content | user | in | The mapped project's own files and history, read as they stood at the commit the map is pinned to. |  |  | D90 | [impact_git.py](tools/coyomap/impact_git.py:50) |  |
| **I9** | Code editor | theirs | handoff | user | out | A reader's own editor, opened at the exact file and line a map box points at. | R2 |  | D93 | [viewer.js](tools/coyomap/viewer/viewer.js:14925) |  |
| **I10** | Code host | theirs | handoff | user | out | A web page showing a mapped file at the pinned commit, for a reader without the project on their machine. | R2 |  | D94 | [viewer.js](tools/coyomap/viewer/viewer.js:14928) |  |
| **I11** | Coding agent chat logs | theirs | content | operator | in | The conversation files a coding agent leaves behind, read to say what a finished build did and what it cost. |  |  | D105 | [map_backup.py](tools/map_backup.py:130) |  |
| **I12** | Score and review reports | ours | file | operator | out | The folder each scoring run and each build review writes into, for the person who changed the instructions to read. | R3 |  |  | [run.py](eval/tools/coyomap_eval/run.py:1) |  |

---

## T3 — How to run / build / test

| Action | Command | Source |
|---|---|---|
| Regenerate the map's schema document | python -m coyomap.json_schema > method/project-map.schema.json | tools/coyomap/json_schema.py:16 |
| Create the folder-local Python environment, refusing an older Python | make venv | Makefile:33 |
| Install the tool from this repo, with the many-language source reader | make deps | Makefile:40 |
| Install the tool plus the test and type-check tooling, for a contributor | make dev | Makefile:44 |
| Run the full test suite and the type checker, which is what a change must pass | make gates | Makefile:56 |
| Install the map-building skill into the coding agents on this machine | make install | Makefile:74 |
| Install the map-quality eval skill, which is for the developer of coyomap | make install-eval | Makefile:86 |
| Install the build-review skill, which is for the developer of coyomap | make install-retro | Makefile:98 |
| Install both developer skills at once | make install-dev | Makefile:108 |
| Remove the map-building skill from the coding agents on this machine | make uninstall | Makefile:115 |
| Remove the map-quality eval skill | make uninstall-eval | Makefile:127 |
| Remove the build-review skill | make uninstall-retro | Makefile:121 |
| Remove both developer skills at once | make uninstall-dev | Makefile:111 |
| Start the map server and open its landing page in a browser | make start | Makefile:135 |
| Start the map server with live reload, for someone working on the viewer | make dev-start | Makefile:145 |
| Delete the folder-local Python environment | make clean | Makefile:149 |
| Download the browser the one on-screen viewer test drives | .venv/bin/python -m playwright install chromium | pyproject.toml:30 |
| Run the main test folder before opening a change for review | .venv/bin/pytest tests | .github/PULL_REQUEST_TEMPLATE.md:24 |
| Check the tool's Python types before opening a change for review | .venv/bin/pyright tools | .github/PULL_REQUEST_TEMPLATE.md:25 |
| start the map server for someone working on the viewer | make dev-start | Makefile:145 |
| Regenerate the map schema file after the model changes | python -m coyomap.json_schema > method/project-map.schema.json | method/model.md:210 |
| Replay saved build transcripts through the process checks | COYOMAP_L3_CORPUS=1 .venv/bin/pytest eval/tests/test_process_corpus.py -q -s | CONTRIBUTING.md:165 |

---

## T4 — Entry points

| Kind | Trigger | Code entity | Component | Cadence |
|---|---|---|---|---|
| agent-tools | A person types `/coyomap-retro`, and their agent reads this file to find the review recipe. | [SKILL.md](eval/retro/SKILL.md:28) | C136 |  |
| agent-tools | A person types `/coyomap-eval`, and their agent reads this file to find the scoring recipe. | [SKILL.md](eval/SKILL.md:28) | C135 |  |
| cli | A developer moves a project's map aside so the next build starts from nothing. | [cli.py](eval/tools/coyomap_eval/cli.py:102) | C100 |  |
| cli | A developer checks a retrospective's finished rows against the code history. | [cli.py](eval/tools/coyomap_eval/cli.py:105) | C100 |  |
| cli | A developer re-measures the counts the tools state about a live map. | [cli.py](eval/tools/coyomap_eval/cli.py:108) | C100 |  |
| cli | A developer asks whether the build a retrospective would read has finished. | [cli.py](eval/tools/coyomap_eval/cli.py:111) | C100 |  |
| cli | A developer reads a build's chat log in slices. | [cli.py](eval/tools/coyomap_eval/cli.py:114) | C100 |  |
| cli | A developer asks what one build spent in time and tokens. | [cli.py](eval/tools/coyomap_eval/cli.py:117) | C100 |  |
| cli | A developer plants false claims, then scores how many the doubters caught. | [cli.py](eval/tools/coyomap_eval/cli.py:120) | C100 |  |
| cli | A developer asks for one built map's quality numbers. | [cli.py](eval/tools/coyomap_eval/cli.py:72) | C100 |  |
| cli | A developer scores a fresh map, compares it with the accepted one, and files the result. | [cli.py](eval/tools/coyomap_eval/cli.py:75) | C100 |  |
| cli | A developer freezes a map file's fingerprint before scoring it. | [cli.py](eval/tools/coyomap_eval/cli.py:78) | C100 |  |
| cli | A developer lists the risky statements a doubter should check against the code. | [cli.py](eval/tools/coyomap_eval/cli.py:81) | C100 |  |
| cli | A developer folds the doubters' votes and the scorers' marks into one report. | [cli.py](eval/tools/coyomap_eval/cli.py:84) | C100 |  |
| cli | A developer checks whether stored scores were made under today's judging rules. | [cli.py](eval/tools/coyomap_eval/cli.py:87) | C100 |  |
| cli | A developer promotes one scored run to be the new accepted baseline. | [cli.py](eval/tools/coyomap_eval/cli.py:90) | C100 |  |
| cli | A developer asks which relations a rebuild dropped while the code still makes them. | [cli.py](eval/tools/coyomap_eval/cli.py:93) | C100 |  |
| cli | A developer applies the regression checks to two maps' number sheets. | [cli.py](eval/tools/coyomap_eval/cli.py:96) | C100 |  |
| cli | A developer scores how the build agent behaved during one build. | [cli.py](eval/tools/coyomap_eval/cli.py:99) | C100 |  |
| agent-tools | A person types `/coyomap`, and their coding agent reads this file to find the method. | [SKILL.md](skill/coyomap/SKILL.md:27) | C134 |  |
| cli | An operator runs `coyomap anchor-drift` to find code links that point at the wrong line. | [anchor_drift.py](tools/coyomap/anchor_drift.py:409) | C21 |  |
| cli | An operator runs `coyomap preindex` to build the structural pre-index a map build starts from. | [cli.py](tools/coyomap/cli.py:153) | C20 |  |
| cli | An operator runs `coyomap validate` to check that a map is well formed. | [cli.py](tools/coyomap/cli.py:156) | C20 |  |
| cli | An operator runs `coyomap audit` to find where a map contradicts itself. | [cli.py](tools/coyomap/cli.py:159) | C20 |  |
| cli | An operator runs `coyomap render` to write the map's committed markdown view. | [cli.py](tools/coyomap/cli.py:165) | C20 |  |
| cli | An operator runs `coyomap serve` to open the viewer for a map in a browser. | [cli.py](tools/coyomap/cli.py:168) | C20 |  |
| cli | An operator runs `coyomap assemble` to merge the build agents' fragments into one map. | [cli.py](tools/coyomap/cli.py:171) | C20 |  |
| cli | An operator runs `coyomap balance` to see which diagrams hold too many boxes. | [cli.py](tools/coyomap/cli.py:183) | C20 |  |
| cli | An operator runs `coyomap reconcile` to expand the path rules into an explicit assignment file. | [cli.py](tools/coyomap/cli.py:186) | C20 |  |
| cli | A build agent runs `coyomap lint-fragment` to self-check one fragment before returning it. | [cli.py](tools/coyomap/cli.py:189) | C20 |  |
| cli | An operator runs `coyomap finalize` to get one pre-commit verdict over every check. | [cli.py](tools/coyomap/cli.py:195) | C20 |  |
| cli | A skeptic runs `coyomap context` to get one claims batch with its evidence already beside it. | [context.py](tools/coyomap/context.py:200) | C24 |  |
| cli | An operator runs `coyomap contract` to print the exact brief one helper agent should receive. | [contract.py](tools/coyomap/contract.py:405) | C26 |  |
| cli | An operator runs `coyomap dump` to read the map, or one element's stored record, as data. | [dump.py](tools/coyomap/dump.py:303) | C24 |  |
| cli | An operator runs `coyomap fix apply-drift` to write each corrected code link back into the map. | [fix.py](tools/coyomap/fix.py:1820) | C23 |  |
| cli | An operator runs `coyomap fix dedup-relation` to drop one of two records of the same data link. | [fix.py](tools/coyomap/fix.py:1820) | C23 |  |
| cli | An operator runs `coyomap fix drop-edge` to remove an arrow the skeptics refuted. | [fix.py](tools/coyomap/fix.py:1820) | C23 |  |
| cli | An operator runs `coyomap fix dedup-edge` to keep one code link where an arrow was recorded twice. | [fix.py](tools/coyomap/fix.py:1821) | C23 |  |
| cli | An operator runs `coyomap fix rows` to apply many wording corrections in one all-or-nothing write. | [fix.py](tools/coyomap/fix.py:1821) | C23 |  |
| cli | An operator runs `coyomap fix security-row` to rewrite a refuted guard's wording and code link. | [fix.py](tools/coyomap/fix.py:1821) | C23 |  |
| cli | An operator runs `coyomap fix dedup-security` to drop a guard an older map recorded twice. | [fix.py](tools/coyomap/fix.py:1822) | C23 |  |
| cli | An operator runs `coyomap fix row` to rewrite one row's wording in the fragment that authored it. | [fix.py](tools/coyomap/fix.py:1822) | C23 |  |
| cli | An operator runs `coyomap grounding lint` to check the skeptics' verdict files are well formed. | [grounding.py](tools/coyomap/grounding.py:1514) | C22 |  |
| cli | An operator runs `coyomap grounding refutations` to fail a map still holding a claim the skeptics refuted. | [grounding.py](tools/coyomap/grounding.py:1563) | C22 |  |
| cli | An operator runs `coyomap grounding by-element` to see what the review pass decided about each element. | [grounding.py](tools/coyomap/grounding.py:1682) | C22 |  |
| cli | An operator runs `coyomap grounding report` to see which claims were refuted, tied or unvoted. | [grounding.py](tools/coyomap/grounding.py:1690) | C22 |  |
| cli | An operator runs `coyomap grounding write` to build the map's honesty record from the verdicts. | [grounding.py](tools/coyomap/grounding.py:1704) | C22 |  |
| cli | An operator runs `coyomap diff` to see which rows two maps of the same work differ on. | [mapdiff.py](tools/coyomap/mapdiff.py:254) | C24 |  |
| cli | An operator runs `coyomap provenance show` to list the sessions that built this map. | [provenance.py](tools/coyomap/provenance.py:308) | C27 |  |
| cli | An operator runs `coyomap provenance stamp` to record which session built this map, and when. | [provenance.py](tools/coyomap/provenance.py:327) | C27 |  |
| cli | An operator runs `coyomap record` to note one advisory they judged acceptable. | [record.py](tools/coyomap/record.py:318) | C23 |  |
| cli | An operator runs `coyomap scope` to see which files a build will read before it starts. | [scope.py](tools/coyomap/scope.py:172) | C26 |  |
| cli | An operator runs `coyomap ship` to run a build's whole closing sequence as one step. | [ship.py](tools/coyomap/ship.py:439) | C25 |  |
| cli | An operator runs `coyomap timings record` to write down what each fan-out slice took. | [timings.py](tools/coyomap/timings.py:439) | C27 |  |
| cli | An operator runs `coyomap timings order` to see one phase's slices, longest first. | [timings.py](tools/coyomap/timings.py:449) | C27 |  |
| cli | An operator runs `coyomap timings show` to see every phase that has a timing record. | [timings.py](tools/coyomap/timings.py:456) | C27 |  |
| poller | A map page opened in developer mode asks the server every second whether the viewer's files changed. | [serve.py](tools/coyomap/viewer/serve.py:225) | C83 | every 1s ([serve.py](tools/coyomap/viewer/serve.py:222)) |
| ui-route | Opening the server's home address lists every project folder opened before, each one openable or removable. | [serve.py](tools/coyomap/viewer/serve.py:640) | C83 |  |
| http-route | Asking `/api/recents` re-reads the remembered folders and says which of their maps can be opened. | [serve.py](tools/coyomap/viewer/serve.py:677) | C83 |  |
| http-route | Asking `/api/browse` lists the folders inside one folder, marking each folder that holds a map. | [serve.py](tools/coyomap/viewer/serve.py:688) | C83 |  |
| http-route | Posting to `/api/open` remembers a folder and starts serving the map inside it. | [serve.py](tools/coyomap/viewer/serve.py:700) | C83 |  |
| http-route | Posting to `/api/forget` drops a folder from the remembered list and stops serving its map. | [serve.py](tools/coyomap/viewer/serve.py:708) | C83 |  |
| http-route | Posting to `/api/reorder` saves a new order for the remembered project folders. | [serve.py](tools/coyomap/viewer/serve.py:717) | C83 |  |
| ui-route | Opening a project's own address returns the browser page that draws that project's map. | [serve.py](tools/coyomap/viewer/serve.py:730) | C83 |  |
| http-route | Asking `/api/dev-reload` says whether the viewer's own files changed, so a map page can reload itself. | [serve.py](tools/coyomap/viewer/serve.py:744) | C83 |  |
| http-route | Asking `/api/health` says the server is answering and names the commit this map is pinned to. | [serve.py](tools/coyomap/viewer/serve.py:746) | C83 |  |
| http-route | Asking `/api/view` returns every diagram, flow and colour the page needs for one map. | [serve.py](tools/coyomap/viewer/serve.py:752) | C83 |  |
| http-route | Asking `/api/rawmap` returns the stored map exactly as its file holds it, byte for byte. | [serve.py](tools/coyomap/viewer/serve.py:763) | C83 |  |
| http-route | Asking `/api/tree` returns the project's folders and files, each marked by how far the map covers it. | [serve.py](tools/coyomap/viewer/serve.py:769) | C83 |  |
| http-route | Asking `/api/symbols` returns every function and class name found in the project at the map's commit. | [serve.py](tools/coyomap/viewer/serve.py:775) | C83 |  |
| http-route | Asking `/api/src` returns one file's text, read at the map's commit or at another one named in the request. | [serve.py](tools/coyomap/viewer/serve.py:797) | C83 |  |
| http-route | Asking `/api/impact` says what a code change between two commits does to the map. | [serve.py](tools/coyomap/viewer/serve.py:807) | C83 |  |
| http-route | Asking `/api/impactcommits` lists the commits before and after the one this map is pinned to. | [serve.py](tools/coyomap/viewer/serve.py:815) | C83 |  |
| http-route | Asking `/api/impactsrcdiff` returns one file's line-by-line changes between two commits. | [serve.py](tools/coyomap/viewer/serve.py:822) | C83 |  |
| http-route | Asking `/static` returns the shared script or stylesheet every map page is drawn with. | [serve.py](tools/coyomap/viewer/serve.py:851) | C83 |  |
| startup-hook | Starting the server reads the remembered folders and loads every map still found there. | [serve.py](tools/coyomap/viewer/serve.py:883) | C83 | on-boot ([serve.py](tools/coyomap/viewer/serve.py:885)) |
| ui-route | Opening `#v=overview` shows the sentences saying what the product is for. | [viewer.html](tools/coyomap/viewer/viewer.html:117) | C70 |  |
| ui-route | Opening `#v=features` lists everything the product does, one card per feature. | [viewer.html](tools/coyomap/viewer/viewer.html:118) | C70 |  |
| ui-route | Opening `#v=hp` shows the product's one successful run, end to end. | [viewer.html](tools/coyomap/viewer/viewer.html:119) | C70 |  |
| ui-route | Opening `#v=interfaces` shows every place the product meets the outside world. | [viewer.html](tools/coyomap/viewer/viewer.html:120) | C70 |  |
| ui-route | Opening `#v=rules` shows the decisions the product makes, grouped by area. | [viewer.html](tools/coyomap/viewer/viewer.html:126) | C70 |  |
| ui-route | Opening `#v=domain` shows the things the product knows about. | [viewer.html](tools/coyomap/viewer/viewer.html:127) | C70 |  |
| ui-route | Opening `#v=glossary` shows the product's own words and what each one means. | [viewer.html](tools/coyomap/viewer/viewer.html:128) | C70 |  |
| ui-route | Opening `#v=container` draws the subsystems the code is arranged into. | [viewer.html](tools/coyomap/viewer/viewer.html:133) | C70 |  |
| ui-route | Opening `#v=data` shows where the product's data physically lives. | [viewer.html](tools/coyomap/viewer/viewer.html:134) | C70 |  |
| ui-route | Opening `#v=context` draws what the product depends on outside itself. | [viewer.html](tools/coyomap/viewer/viewer.html:135) | C70 |  |
| ui-route | Opening `#v=tests` shows how much of the product the tests reach. | [viewer.html](tools/coyomap/viewer/viewer.html:136) | C70 |  |
| ui-route | Opening `#v=deployment` draws the processes that run and what each one holds. | [viewer.html](tools/coyomap/viewer/viewer.html:138) | C70 |  |
| ui-route | Opening `#v=system` shows the operational tables: commands, settings and ways in. | [viewer.html](tools/coyomap/viewer/viewer.html:139) | C70 |  |
| ui-route | Opening an interface's address shows who is on the far side and what crosses. | [viewer.js](tools/coyomap/viewer/viewer.js:12679) | C60 |  |
| ui-route | Opening an element's address shows everything the map holds about that one thing. | [viewer.js](tools/coyomap/viewer/viewer.js:13011) | C60 |  |
| ui-route | Opening a feature's address shows that feature's page and its use cases. | [viewer.js](tools/coyomap/viewer/viewer.js:13016) | C60 |  |
| ui-route | Opening an actor's address shows what that person or program does, in order. | [viewer.js](tools/coyomap/viewer/viewer.js:13042) | C60 |  |
| ui-route | Opening a collection's address lists that collection's rows in full. | [viewer.js](tools/coyomap/viewer/viewer.js:13059) | C60 |  |
| ui-route | Opening a rule's address shows that decision and where the code makes it. | [viewer.js](tools/coyomap/viewer/viewer.js:13083) | C60 |  |
| ui-route | Opening a subsystem's address draws that subsystem and its neighbours. | [viewer.js](tools/coyomap/viewer/viewer.js:6492) | C60 |  |
| ui-route | Opening a use case's address draws that use case's numbered steps. | [viewer.js](tools/coyomap/viewer/viewer.js:6503) | C60 |  |
| poller | The viewer's code changed on disk, so the map server restarts. | [devserve.py](tools/devserve.py:97) | C51 | every 1s ([devserve.py](tools/devserve.py:91)) |
| cli | A build records which conversation produced this map. | [map_backup.py](tools/map_backup.py:452) | C50 |  |
| cli | An operator archives a project's map with the conversation that built it. | [map_backup.py](tools/map_backup.py:478) | C50 |  |

---

## Subdomains (SD) — bounded contexts of the domain model

| ID | Subdomain | Purpose | Parent | Source | Conf. |
|---|---|---|---|---|---|
| **SD1** | Map content | Everything a map says about the project it describes. |  | tools/coyomap/model.py:761 | inferred |
| **SD10** | Product story | Who the product is for, what they want from it, and the ordered steps each goal takes. | SD1 | tools/coyomap/model.py:68 | inferred |
| **SD11** | Code inventory | The pieces the product is built from, what it pulls in from outside, and how they are wired. | SD1 | tools/coyomap/model.py:262 | inferred |
| **SD12** | Stored data | The types the product keeps, where each one lives, and the states it moves through. | SD1 | tools/coyomap/model.py:431 | inferred |
| **SD13** | Outside edge and decisions | Where the product meets the world, and the decisions it enforces at those places. | SD1 | tools/coyomap/model.py:221 | inferred |
| **SD14** | Operations | How the product is run, watched, configured and tested. | SD1 | tools/coyomap/model.py:552 | inferred |
| **SD2** | Map file | The stored map itself, the workers' rows it is merged from, and the record of how its claims held up. |  | tools/coyomap/model.py:761 | verified |
| **SD3** | Build directives | The declared edits a build applies every time the map is rebuilt from its rows. |  | tools/coyomap/reconcile.py:215 | verified |
| **SD4** | Code survey shapes | What the measuring pass finds in a code tree before any map is drawn. |  | tools/coyomap/preindex_lib.py:156 | verified |
| **SD5** | Viewer shapes | The drawn form of a map: boxes, arrows and pages, built fresh for each screen. |  | tools/coyomap/viewer/build_graph.py:116 | verified |

---

## T5 — Domain model (domain cards)

**E1 — Project map** *(D91.project-map.json — collection; written in a fixed key order so the same map always produces the same bytes)*
SUBDOMAIN: SD2
MEANING: Everything the map knows about one project, kept in one committed file.
FIELDS: format:string · title:string · goal:string · commit:string ? · roles:E2 [] · glossary:E4 [] · capabilities:E9 [] · subsystems:E9 [] · subdomains:E9 [] · blocks:E9 [] · use_cases:E5 [] · happy_path:E6 [] · components:E12 [] · deps:E13 [] · interfaces:E11 [] · run_commands:E14 [] · entry_points:E15 [] · entities:E22 [] · non_entity_types:E23 [] · flows:E25 [] · subflows:E26 [] · edges:E27 [] · messaging:E18 [] · deployment:E29 [] · environments:string [] · observability:E30 [] · security:E31 [] · config:E32 [] · tests:E33 [] · rules:E35 [] · extras:E36 [] · grounding:E37 ?
RELATIONS: contains 1→* E2 · contains 1→* E4 · contains 1→* E5 · contains 1→* E6 · contains 1→* E9 · contains 1→* E11 · contains 1→* E12 · contains 1→* E13 · contains 1→* E14 · contains 1→* E15 · contains 1→* E18 · contains 1→* E22 · contains 1→* E23 · contains 1→* E25 · contains 1→* E26 · contains 1→* E27 · contains 1→* E29 · contains 1→* E30 · contains 1→* E31 · contains 1→* E32 · contains 1→* E33 · contains 1→* E35 · contains 1→* E36 · contains 1→0..1 E37
SOURCE: [model.py](tools/coyomap/model.py:761)

**E2 — Actor** *(project-map.json — embedded)*
SUBDOMAIN: SD10
MEANING: A person or program the product recognizes, with what they want from it.
FIELDS: id:string PK · name:string · kind:string · audience:string · wants:string · drives:string · relations:E3 []
RELATIONS: contains 1→* E3
SOURCE: [model.py](tools/coyomap/model.py:68)

**E3 — Actor link** *(project-map.json — embedded)*
SUBDOMAIN: SD10
MEANING: One stated tie between two actors, such as one becoming another.
FIELDS: kind:string · role:string FK→E2 · at:string FK→E5 ? · source:string ?
RELATIONS: changesAt *→0..1 E5
SOURCE: [model.py](tools/coyomap/model.py:43)

**E4 — Glossary term** *(project-map.json — embedded)*
SUBDOMAIN: SD10
MEANING: One product word and its plain meaning, with the place in the code it names.
FIELDS: term:string PK · meaning:string · source:string ? · aliases:string [] · no_autolink:bool
SOURCE: [model.py](tools/coyomap/model.py:92)

**E5 — Use case** *(project-map.json — embedded)*
SUBDOMAIN: SD10
MEANING: One goal an actor comes to the product for, with what starts it and what results.
FIELDS: id:string PK · name:string · actors:string FK→E2 [] · trigger:string · outcome:string · capability:string FK→E9 ? · entry_points:string FK→E15 []
RELATIONS: drivenBy *→* E2 · groupedBy *→0..1 E9 · startsAt *→* E15
SOURCE: [model.py](tools/coyomap/model.py:109)

**E6 — Happy path step** *(project-map.json — embedded)*
SUBDOMAIN: SD10
MEANING: One position in the product's single successful run, naming the use case it plays.
FIELDS: id:string PK · uc:string FK→E5 ? · why:string ?
RELATIONS: realizes *→1 E5
SOURCE: [model.py](tools/coyomap/model.py:130)

**E7 — Stake** *(project-map.json — embedded)*
SUBDOMAIN: SD10
MEANING: What one actor comes to a feature to do, in a short phrase.
FIELDS: actor:string FK→E2 · stake:string
RELATIONS: heldBy *→1 E2
SOURCE: [model.py](tools/coyomap/model.py:139)

**E8 — Story anchor** *(project-map.json — embedded)*
SUBDOMAIN: SD10
MEANING: Where a feature the successful run never reaches sits beside the features it does.
FIELDS: place:string · feature:string
SOURCE: [model.py](tools/coyomap/model.py:149)

**E9 — Group** *(project-map.json — embedded)*
SUBDOMAIN: SD11
MEANING: One box grouping other elements: a feature, a subsystem, a data area or a decision area.
FIELDS: id:string PK · name:string · purpose:string · parent:string FK→E9 ? · happy_path:string · stakes:E7 [] · story:E8 ? · owners:string [] · source:string ? · confidence:string · tech:string · tech_source:string
RELATIONS: has 0..1→* E9 · contains 1→* E7 · contains 1→0..1 E8
SOURCE: [model.py](tools/coyomap/model.py:166)

**E10 — Evidence** *(project-map.json — embedded)*
SUBDOMAIN: SD11
MEANING: One citation backing a claim the map makes, with the line to re-read.
FIELDS: file:string · why:string
SOURCE: [model.py](tools/coyomap/model.py:213)

**E11 — Interface** *(project-map.json — embedded)*
SUBDOMAIN: SD13
MEANING: One place the product meets something outside itself.
FIELDS: id:string PK · name:string · what:string · side:string · facing:string · kind:E67 · ways_in:string FK→E15 [] · source:string · confidence:string · evidence:E10 []
RELATIONS: contains 1→* E10 · madeOf 1→* E15 · has *→0..1 E67
SOURCE: [model.py](tools/coyomap/model.py:221)

**E12 — Component** *(project-map.json — embedded)*
SUBDOMAIN: SD11
MEANING: One module-sized piece of the product, with the files it owns.
FIELDS: id:string PK · name:string · purpose:string · subsystem:string FK→E9 ? · entry_point:string ? · source:string ? · confidence:string · files:string [] · runs_in:string FK→E29 [] · evidence:E10 [] · states:E20 ?
RELATIONS: contains 1→* E10 · contains 1→0..1 E20 · groupedBy *→0..1 E9 · runsIn *→* E29
SOURCE: [model.py](tools/coyomap/model.py:262)

**E13 — Dependency** *(project-map.json — embedded)*
SUBDOMAIN: SD11
MEANING: One outside system or library the product uses.
FIELDS: id:string PK · name:string · kind:string ? · type:string · used_for:string · bucket:string · where_configured:string · deployment_linked:bool · package:string · alternative:string · interfaces:string FK→E11 [] · not_an_interface:string · evidence:E10 []
RELATIONS: contains 1→* E10 · standsOn *→* E11
SOURCE: [model.py](tools/coyomap/model.py:287)

**E14 — Run command** *(project-map.json — embedded)*
SUBDOMAIN: SD14
MEANING: One command a person types to work on the product.
FIELDS: action:string · command:string · source:string
SOURCE: [model.py](tools/coyomap/model.py:318)

**E15 — Way in** *(project-map.json — embedded)*
SUBDOMAIN: SD11
MEANING: One address, command or tool that starts work inside the product.
FIELDS: id:string PK · kind:E68 · trigger:string · source:string · component:string FK→E12 · activation:string · runs_in:string [] · cadence:string · cadence_source:string
RELATIONS: ownedBy *→1 E12 · has *→0..1 E68
SOURCE: [model.py](tools/coyomap/model.py:326)

**E16 — Record field** *(project-map.json — embedded)*
SUBDOMAIN: SD12
MEANING: One attribute of a saved record, with its type and its key markers.
FIELDS: name:string · type:string · markers:string []
SOURCE: [model.py](tools/coyomap/model.py:356)

**E17 — Record relation** *(project-map.json — embedded)*
SUBDOMAIN: SD12
MEANING: One typed link from a saved record to another, with how many sit at each end.
FIELDS: verb:string · target:string · src_card:string ? · dst_card:string ? · display:string · how:string ? · keyed_by:string []
SOURCE: [model.py](tools/coyomap/model.py:363)

**E18 — Channel** *(project-map.json — embedded)*
SUBDOMAIN: SD12
MEANING: One queue or topic the product sends messages on, with who puts and who takes.
FIELDS: name:string PK · kind:string · broker:string FK→E13 · publishers:string FK→E12 [] · consumers:string [] · payload:string FK→E22 · source:string
RELATIONS: carriedBy *→0..1 E13 · carries *→0..1 E22 · movedBy *→* E12
SOURCE: [model.py](tools/coyomap/model.py:379)

**E19 — State change** *(project-map.json — embedded)*
SUBDOMAIN: SD12
MEANING: One move from one state to another, with the trigger that causes the move.
FIELDS: src:string · dst:string · on:string
SOURCE: [model.py](tools/coyomap/model.py:395)

**E20 — Lifecycle** *(project-map.json — embedded)*
SUBDOMAIN: SD12
MEANING: The states a record or a component moves through, and the moves between them.
FIELDS: states:string [] · transitions:E19 [] · source:string
RELATIONS: contains 1→* E19
SOURCE: [model.py](tools/coyomap/model.py:402)

**E21 — Store** *(project-map.json — embedded)*
SUBDOMAIN: SD12
MEANING: Where a record physically lives: which store, which compartment, and how it sits there.
FIELDS: dep:string FK→E13 ? · container:string · mode:E66 · notes:string
RELATIONS: heldBy *→0..1 E13 · has *→0..1 E66
SOURCE: [model.py](tools/coyomap/model.py:415)

**E22 — Record** *(project-map.json — embedded)*
SUBDOMAIN: SD12
MEANING: One named thing the product works with, and what the product keeps of it.
FIELDS: id:string PK · name:string · meaning:string · subdomain:string FK→E9 ? · source:string ? · store:E21 ? · fields:E16 [] · relations:E17 [] · states:E20 ? · owners:string []
RELATIONS: contains 1→* E16 · contains 1→* E17 · contains 1→0..1 E21 · contains 1→0..1 E20 · groupedBy *→0..1 E9
SOURCE: [model.py](tools/coyomap/model.py:431)

**E23 — Skipped type** *(project-map.json — embedded)*
SUBDOMAIN: SD11
MEANING: A named type in the product left out of the record model on purpose.
FIELDS: name:string PK · source:string ? · why:string
SOURCE: [model.py](tools/coyomap/model.py:453)

**E24 — Flow step** *(project-map.json — embedded)*
SUBDOMAIN: SD10
MEANING: One step of a use case, saying who acts on what, and which way data moves.
FIELDS: n:int · src:string · dst:string · phrase:string · note:string · where:string ? · no_call_site:bool · direction:E69 · subflow:string ?
RELATIONS: has *→0..1 E69
SOURCE: [model.py](tools/coyomap/model.py:463)

**E25 — Flow** *(project-map.json — embedded)*
SUBDOMAIN: SD10
MEANING: The numbered steps of one use case, in the order they happen.
FIELDS: uc:string FK→E5 · title:string · steps:E24 []
RELATIONS: contains 1→* E24 · realizes 1→1 E5
SOURCE: [model.py](tools/coyomap/model.py:507)

**E26 — Shared sub-flow** *(project-map.json — embedded)*
SUBDOMAIN: SD10
MEANING: A run of steps several use cases share, written once.
FIELDS: id:string PK · name:string · steps:E24 []
RELATIONS: contains 1→* E24
SOURCE: [model.py](tools/coyomap/model.py:514)

**E27 — Edge** *(project-map.json — embedded)*
SUBDOMAIN: SD11
MEANING: One relation between two boxes on the map, with the line where it happens.
FIELDS: src:string · verb:string · dst:string · why:string ? · where:string ? · no_call_site:bool
RELATIONS: links *→* E12 {each end names a component, a dependency or a record by its id, so no single field points at one kind}
SOURCE: [model.py](tools/coyomap/model.py:527)

**E28 — Environment tag** *(project-map.json — embedded)*
SUBDOMAIN: SD14
MEANING: One environment a deployment unit runs in, with the manifest line placing it.
FIELDS: env:string · source:string
SOURCE: [model.py](tools/coyomap/model.py:539)

**E29 — Deployment unit** *(project-map.json — embedded)*
SUBDOMAIN: SD14
MEANING: One process or container the product ships as, and what it runs on.
FIELDS: unit:string PK · runs_on:string · exposed_as:string · config_source:string · variants:E28 []
RELATIONS: contains 1→* E28
SOURCE: [model.py](tools/coyomap/model.py:552)

**E30 — Signal** *(project-map.json — embedded)*
SUBDOMAIN: SD14
MEANING: One thing the product reports about itself, where it goes and who watches.
FIELDS: signal:string PK · where_emitted:string · where_viewed:string · alerts:string
SOURCE: [model.py](tools/coyomap/model.py:567)

**E31 — Security surface** *(project-map.json — embedded; older maps only; a new map states the same fact as a business rule marked as an access decision)*
SUBDOMAIN: SD13
MEANING: One guarded place, who may reach it, and what is at stake. Kept only for older maps.
FIELDS: surface:string PK · who:string · source:string · risk:string
SOURCE: [model.py](tools/coyomap/model.py:575)

**E32 — Setting** *(project-map.json — embedded)*
SUBDOMAIN: SD14
MEANING: One setting the product reads, what it is for, and its default.
FIELDS: key:string PK · purpose:string · default:string · per_env:string
SOURCE: [model.py](tools/coyomap/model.py:584)

**E33 — Test row** *(project-map.json — embedded)*
SUBDOMAIN: SD14
MEANING: How well one part of the product is tested, and what the gap is.
FIELDS: targets:string [] · tested:string · label:string · tests:E10 [] · gap:string · confidence:string
RELATIONS: contains 1→* E10 · assesses *→* E12 {the assessed list holds ids of any kind, so no single field points at one kind}
SOURCE: [model.py](tools/coyomap/model.py:592)

**E34 — Rule site** *(project-map.json — embedded)*
SUBDOMAIN: SD13
MEANING: One line where a business rule is actually enforced.
FIELDS: where:string ? · why:string · no_call_site:bool
SOURCE: [model.py](tools/coyomap/model.py:605)

**E35 — Business rule** *(project-map.json — embedded)*
SUBDOMAIN: SD13
MEANING: One decision the product makes, in product words, with every place it is enforced.
FIELDS: id:string PK · statement:string · name:string · block:string FK→E9 ? · sites:E34 [] · access:bool · risk:string · confidence:string
RELATIONS: contains 1→* E34 · groupedBy *→0..1 E9
SOURCE: [model.py](tools/coyomap/model.py:623)

**E36 — Extra section** *(project-map.json — embedded)*
SUBDOMAIN: SD2
MEANING: One authored section of notes kept with the map, under its own heading.
FIELDS: heading:string PK FK→E54 · body:string
RELATIONS: matches *→0..1 E54
SOURCE: [model.py](tools/coyomap/model.py:673)

**E37 — Grounding record** *(project-map.json — embedded)*
SUBDOMAIN: SD2
MEANING: How much of the map's claim surface skeptics challenged, and how the votes fell.
FIELDS: claims_total:int · claims_challenged:int · claims_confirmed:int · claims_refuted:int · claims_unverifiable:int · claims_superseded:int · claims_added_since:int · live_claims_digest:string · claims_live_challenged:int · note:string
SOURCE: [model.py](tools/coyomap/model.py:680)

**E38 — Use case reach** *(worked out from the flows on demand — projection)*
SUBDOMAIN: SD10
MEANING: The interfaces one use case reaches, worked out from its steps.
FIELDS: interfaces:E11 [] · via_subflow_only:string []
RELATIONS: names *→* E11 · answersFor *→1 E5 «key» uc
SOURCE: [model.py](tools/coyomap/model.py:864)

**E39 — Graph** *(built for the browser on request — projection)*
SUBDOMAIN: SD5
MEANING: Everything the viewer needs to draw one map, built fresh on every request.
FIELDS: title:string ? · nodes:E40 [] · edges:E41 [] · happy_path:E42 [] · flows:E48 [] · tests:E44 [] · extras:E45 [] · data_view:json · rules_view:json · record_parents:json
RELATIONS: contains 1→* E40 · contains 1→* E41 · contains 1→* E42 · contains 1→* E44 · contains 1→* E45 · contains 1→* E48 · builtFrom 1→1 E1 {built in full from the whole map each time the viewer asks, and never saved}
SOURCE: [build_graph.py](tools/coyomap/viewer/build_graph.py:116)

**E40 — Graph box** *(built for the browser on request — projection)*
SUBDOMAIN: SD5
MEANING: One thing drawn on a view, with its name, its code link and its tags.
FIELDS: id:string PK · kind:string · name:string · file:string ? · line:int ? · fields:json · parent:string ? · attrs:json [] · files:string [] · store:json ? · states_lines:string []
SOURCE: [build_graph.py](tools/coyomap/viewer/build_graph.py:29)

**E41 — Graph arrow** *(built for the browser on request — projection)*
SUBDOMAIN: SD5
MEANING: One arrow drawn between two boxes, with its label and how many sit at each end.
FIELDS: src:string · verb:string · dst:string · why:string ? · where:string ? · kind:string ? · src_card:string ? · dst_card:string ? · how:string ? · fk_fields:string [] · keyed_by:string []
SOURCE: [build_graph.py](tools/coyomap/viewer/build_graph.py:73)

**E42 — Graph walk step** *(built for the browser on request — projection)*
SUBDOMAIN: SD5
MEANING: One position in the successful run as the viewer receives it.
FIELDS: id:string PK · uc:string ? · why:string
SOURCE: [build_graph.py](tools/coyomap/viewer/build_graph.py:92)

**E43 — Test target** *(built for the browser on request — projection)*
SUBDOMAIN: SD5
MEANING: One element a test row assesses, resolved to a name the reader sees.
FIELDS: id:string PK · name:string · node:string ?
SOURCE: [build_graph.py](tools/coyomap/viewer/build_graph.py:101)

**E44 — Test row view** *(built for the browser on request — projection)*
SUBDOMAIN: SD5
MEANING: One coverage row as the viewer receives it, with its assessed elements resolved.
FIELDS: targets:E43 [] · label:string · tested:string · tests:json [] · gap:string · confidence:string
RELATIONS: contains 1→* E43
SOURCE: [build_graph.py](tools/coyomap/viewer/build_graph.py:107)

**E45 — Extra section view** *(built for the browser on request — projection)*
SUBDOMAIN: SD5
MEANING: One authored section as the viewer receives it, with the elements it names resolved.
FIELDS: heading:string PK · body:string · maintenance:bool · refs:E43
RELATIONS: has 1→* E43
SOURCE: [build_graph.py](tools/coyomap/viewer/build_graph.py:182)

**E46 — Change impact report** *(read back from the written report — projection)*
SUBDOMAIN: SD5
MEANING: What a code change does to the map, read back from the written report.
FIELDS: base:string ? · new:string ? · changes:E47 [] · new_edges:json []
RELATIONS: contains 1→* E47
SOURCE: [build_graph.py](tools/coyomap/viewer/build_graph.py:198)

**E47 — Change impact entry** *(read back from the written report — projection)*
SUBDOMAIN: SD5
MEANING: One element the change touched, and what happened to it.
FIELDS: id:string PK · change:string · name:string ? · kind:string ? · note:string
SOURCE: [build_graph.py](tools/coyomap/viewer/build_graph.py:190)

**E48 — Viewer flow** *(built for the browser on request — projection)*
SUBDOMAIN: SD5
MEANING: One use case's steps as the viewer receives them.
FIELDS: uc:string · title:string · steps:E49 [] · line_no:int
RELATIONS: contains 1→* E49
SOURCE: [grammar.py](tools/coyomap/grammar.py:860)

**E49 — Viewer flow step** *(built for the browser on request — projection)*
SUBDOMAIN: SD5
MEANING: One step as the viewer receives it, with each end marked as an element or a person.
FIELDS: n:int · src:string · dst:string · src_is_id:bool · dst_is_id:bool · phrase:string · note:string · where:string ? · subflow:string ? · ok:bool
SOURCE: [grammar.py](tools/coyomap/grammar.py:846)

**E50 — File walk result** *(one scan of the project — transient)*
SUBDOMAIN: SD4
MEANING: The source files a scan counted, and what it skipped and why.
FIELDS: files:string [] · root:string · used_git:bool · skipped_excluded:int · skipped_ignored:int · ignore_hits:int []
SOURCE: [preindex_lib.py](tools/coyomap/preindex_lib.py:156)

**E51 — Code symbol** *(one scan of the project — transient; copied into the scan's own output file as plain rows, never kept as this shape)*
SUBDOMAIN: SD4
MEANING: One class or function found in the source, with where it is defined.
FIELDS: name:string · kind:string · file:string · line:int · end:int ?
SOURCE: [preindex_lib.py](tools/coyomap/preindex_lib.py:312)

**E52 — Import reference** *(one scan of the project — transient; copied into the scan's own output file as plain rows, never kept as this shape)*
SUBDOMAIN: SD4
MEANING: One import line found in the source, naming what it pulls in.
FIELDS: file:string · line:int · module:string
SOURCE: [preindex_lib.py](tools/coyomap/preindex_lib.py:321)

**E53 — Directory expectation** *(one scan of the project — transient)*
SUBDOMAIN: SD4
MEANING: How many components one folder should hold, given its size.
FIELDS: path:string PK · files:int · loc:int · expected:int · children:E53 []
RELATIONS: contains 1→* E53
SOURCE: [preindex_lib.py](tools/coyomap/preindex_lib.py:533)

**E54 — Notes heading spec** *(a fixed list written in the source — in-code)*
SUBDOMAIN: SD2
MEANING: One recognized notes heading, and how the lines under it are read.
FIELDS: heading:string PK · maintenance:bool · key:string ? · seps:string · lead:string · strict_multi:string · merged_form:string
SOURCE: [records.py](tools/coyomap/records.py:99)

**E55 — Map profile** *(D91.profile.json — collection; written beside the map being scored, in a folder git never tracks)*
SUBDOMAIN: SD4
MEANING: The measurable quality signals of one built map, kept so two maps can be compared.
FIELDS: use_cases:int · components:int · entities:int · edges:int · validate_problems:int · validate_warnings:int · contradictions:int · interfaces:int ? · rules:int ? · auth_surfaces:string [] · use_case_names:string [] · entity_names:string [] · commit:string ?
RELATIONS: scores 1→1 E1 {measured from one built map at score time, and the map itself carries no pointer back}
SOURCE: [profile.py](eval/tools/coyomap_eval/profile.py:39)

**E56 — Reconcile file** *(D91.reconcile.json — collection; committed beside the map, and replayed on every rebuild)*
SUBDOMAIN: SD3
MEANING: The decisions a build records so the next rebuild does not lose them.
FIELDS: sets:E57 [] · drop_edges:E58 [] · keep_edges:E59 [] · set_anchors:E60 [] · drop_relations:E61 []
RELATIONS: contains 1→* E57 · contains 1→* E58 · contains 1→* E59 · contains 1→* E60 · contains 1→* E61
SOURCE: [reconcile.py](tools/coyomap/reconcile.py:215)

**E57 — Set directive** *(reconcile.json — embedded)*
SUBDOMAIN: SD3
MEANING: An instruction filling in one field on the elements it names.
FIELDS: ids:string [] · subsystem:string FK→E9 ? · subdomain:string ? · capability:string ? · block:string ? · owners:string [] · ways_in:string [] · interfaces:string [] · entry_point_witness:json
RELATIONS: assignsTo *→* E9
SOURCE: [reconcile.py](tools/coyomap/reconcile.py:126)

**E58 — Drop-edge directive** *(reconcile.json — embedded)*
SUBDOMAIN: SD3
MEANING: An instruction removing one relation between two boxes.
FIELDS: src:string · verb:string · dst:string · drop_steps:bool · repoint:string ?
RELATIONS: removes *→1 E27 {names the relation by its two ends and its word, because a relation carries no id of its own}
SOURCE: [reconcile.py](tools/coyomap/reconcile.py:157)

**E59 — Keep-edge directive** *(reconcile.json — embedded)*
SUBDOMAIN: SD3
MEANING: An instruction saying which line survives when one relation is declared twice.
FIELDS: src:string · verb:string · dst:string · where:string
RELATIONS: keeps *→1 E27 {names the relation by its two ends and its word, because a relation carries no id of its own}
SOURCE: [reconcile.py](tools/coyomap/reconcile.py:166)

**E60 — Anchor directive** *(reconcile.json — embedded)*
SUBDOMAIN: SD3
MEANING: A corrected code link, kept so every rebuild re-applies the correction.
FIELDS: claim:string PK · corrected:string
SOURCE: [reconcile.py](tools/coyomap/reconcile.py:182)

**E61 — Drop-relation directive** *(reconcile.json — embedded)*
SUBDOMAIN: SD3
MEANING: An instruction removing one link declared on a record.
FIELDS: entity:string · verb:string · target:string
RELATIONS: removes *→1 E17 {names the record card, the word and the far record, because a link carries no id of its own}
SOURCE: [reconcile.py](tools/coyomap/reconcile.py:196)

**E62 — Element check** *(worked out again whenever it is asked for — projection)*
SUBDOMAIN: SD2
MEANING: One element beside what the skeptics did to the claims it makes.
FIELDS: element_id:string PK · kind:string · label:string · stated:string · confirmed:int · refuted:int · unverifiable:int · unvoted:int
RELATIONS: expands *→1 E37 {worked out again from the pinned claim list and the saved votes, so it can never drift from them}
SOURCE: [grounding.py](tools/coyomap/grounding.py:677)

**E63 — Surviving refutation** *(worked out again whenever it is asked for — projection)*
SUBDOMAIN: SD2
MEANING: A claim skeptics refuted that the shipped map still makes, word for word.
FIELDS: claim:string PK · element_id:string · kind:string · label:string · refuted_by:int · note:string
RELATIONS: survivesIn *→1 E1 {found by matching the saved votes against the shipped map, which stores no pointer back}
SOURCE: [grounding.py](tools/coyomap/grounding.py:899)

**E64 — Verdict lint result** *(one check run — transient)*
SUBDOMAIN: SD2
MEANING: What a shape check of the skeptics' saved votes found.
FIELDS: problems:string [] · notes:string []
SOURCE: [grounding.py](tools/coyomap/grounding.py:1075)

**E65 — Fragment load** *(one assembly run — transient)*
SUBDOMAIN: SD2
MEANING: What reading a set of harvest files produced, including the files that failed.
FIELDS: parts:E1 [] · notes:string [] · errors:string []
RELATIONS: carries 1→* E1
SOURCE: [assemble.py](tools/coyomap/assemble.py:226)

**E66 — Store mode** *(a fixed list of seven words — enum)*
SUBDOMAIN: SD12
MEANING: The closed list of ways a record can relate to the place that holds it.
FIELDS: value:string PK
SOURCE: [grammar.py](tools/coyomap/grammar.py:517)

**E67 — Interface kind** *(a fixed list of eleven words — enum; new words may be minted for one project, so the list is a seed rather than a wall)*
SUBDOMAIN: SD13
MEANING: The closed list of words saying what kind of thing an interface is.
FIELDS: value:string PK
SOURCE: [grammar.py](tools/coyomap/grammar.py:391)

**E68 — Way-in kind** *(a fixed list of eleven words — enum; new words may be minted for one project, so the list is a seed rather than a wall)*
SUBDOMAIN: SD11
MEANING: The closed list of words saying by what mechanism a way in is reached.
FIELDS: value:string PK
SOURCE: [grammar.py](tools/coyomap/grammar.py:547)

**E69 — Step direction** *(a fixed list of three words — enum)*
SUBDOMAIN: SD10
MEANING: The three words saying which way data moves in one step.
FIELDS: value:string PK
SOURCE: [grammar.py](tools/coyomap/grammar.py:318)

---

## Non-entity types (plumbing, deliberately unmodelled)

| Type | Source | Why |
|---|---|---|
| ModelError | tools/coyomap/model.py:36 | An error raised when a map file has the wrong shape. It carries no product data. |
| WrongMapError | tools/coyomap/model.py:1385 | An error raised when the tool is pointed at its own map instead of the project's. Not product data. |
| ReconcileError | tools/coyomap/reconcile.py:53 | An error raised when a recorded decision cannot be applied. It carries no product data. |
| IgnoreSpec | tools/coyomap/ignorefile.py:63 | The patterns saying which files a scan skips. Build input, not something the map keeps. |
| Extents | tools/coyomap/impact_git.py:200 | A shorthand name for plain lists of line ranges. There is no named record behind it. |

---

## T6 — Use-case flows

**UC2 — Build a project's first map**
1. Map owner → I4 : ask the coding agent for a map of this project
2. I4 → C134 : point the agent at the coyomap clone and the one document to read @ [SKILL.md](skill/coyomap/SKILL.md:27)
3. C134 → C130 : ⟨runs SF1 — Choose the build mode⟩
4. C130 → C126 : read the method end to end and plan the build as waves of helper agents @ [dispatch.md](method/dispatch.md:83)
5. C126 → C45 : size each helper's slice from a survey of the project's code @ [method.md](method.md:1769)
6. C45 → I8 : count the files, lines and symbols of the project's own code @ [preindex.py](tools/coyomap/preindex.py:557)
7. C126 → C26 : fill each helper's brief from the shared contract @ [method.md](method.md:1750) · a slot left empty is refused, so no helper is briefed on the wrong thing
8. C126 → C5 : make each helper self-check its own piece before handing it in @ [method.md](method.md:1784)
9. C126 → C47 : turn the path rules into one assignment for every mapped thing @ [method.md](method.md:2049)
10. C47 → E56 : record where every mapped thing belongs before the merge @ [reconcile_build.py](tools/coyomap/reconcile_build.py:480)
11. C126 → C4 : merge every returned piece into one map @ [method.md](method.md:2033)
12. C4 → E65 : gather every piece the helpers wrote, and name the ones that failed @ [assemble.py](tools/coyomap/assemble.py:298)
13. C4 → E1 : write the merged map into the project's map folder @ [assemble.py](tools/coyomap/assemble.py:978)
14. C126 → C127 : hand the finished map to fresh agents that try to disprove it @ [method.md](method.md:2149)
15. C127 → C128 : hand the corrected map to the closing sequence @ [method.md](method.md:2650)
16. C128 → C25 : run the closing steps in order and stop at the first failure @ [method.md](method.md:2656)
17. C25 → C22 : turn the skeptics' votes into the map's honesty record @ [ship.py](tools/coyomap/ship.py:320)
18. C22 → E37 : write how much of the map was challenged and how the votes fell @ [grounding.py](tools/coyomap/grounding.py:1749)
19. C25 → C27 : stamp which session built the map, and when @ [ship.py](tools/coyomap/ship.py:323)
20. C25 → I6 : ⟨runs SF2 — Run the gates and write the map⟩
21. C128 → I4 : name the finished map's files and the address that opens it @ [method.md](method.md:3104)
22. I4 → Map owner : hand back the finished map and the checks it passed

**UC7 — See what a code change did to the map**
1. Map owner → I4 : ask what the newer code did to the map
2. I4 → C134 : point the coding agent at the method in the coyomap clone @ [SKILL.md](skill/coyomap/SKILL.md:27)
3. C134 → C130 : ⟨runs SF1 — Choose the build mode⟩
4. C130 → C131 : read the change-impact instructions and follow them @ [dispatch.md](method/dispatch.md:167)
5. C131 → E1 : read the commit the map is pinned to @ [change-impact.md](method/change-impact.md:41)
6. C131 → I8 : diff the pinned commit against the working tree, untracked files included @ [change-impact.md](method/change-impact.md:57)
7. C131 → I8 : read the changed code and classify each change as modified, added or deleted @ [change-impact.md](method/change-impact.md:63)
8. C131 → E1 : follow the map's arrows out to every element the change reaches @ [change-impact.md](method/change-impact.md:64)
9. C131 → E46 : write the report, carrying the exact new text of every element it touches @ [change-impact.md](method/change-impact.md:84)
10. C131 → I6 : leave the report on disk beside the map @ [change-impact.md](method/change-impact.md:13) · uncommitted until the person accepts it
11. I6 → Map owner : name every part of the map the change touched, and what each should now say

**UC8 — Fold a change report into the baseline**
1. Map owner → I4 : agree the report is right and ask to fold it into the map
2. I4 → C134 : point the coding agent at the method in the coyomap clone @ [SKILL.md](skill/coyomap/SKILL.md:27)
3. C134 → C130 : ⟨runs SF1 — Choose the build mode⟩
4. C130 → C131 : read the accept steps and follow them @ [dispatch.md](method/dispatch.md:170)
5. C131 → E46 : read back the new text the report already carries for every element it touches @ [change-impact.md](method/change-impact.md:80) · accept re-reads no code and infers nothing
6. C131 → C23 : apply each was-to-now block to the stored map @ [change-impact.md](method/change-impact.md:123)
7. C23 → E1 : write the corrected rows back into the stored map @ [fix.py](tools/coyomap/fix.py:119)
8. C131 → C27 : stamp this accept session and re-pin the map to the code commit @ [change-impact.md](method/change-impact.md:125)
9. C27 → I8 : read the commit the code now stands at @ [provenance.py](tools/coyomap/provenance.py:217)
10. C131 → I4 : ask whether to commit the code first, or pin the map as dirty @ [change-impact.md](method/change-impact.md:129) · only when the code is uncommitted
11. I4 → Map owner : put the two choices in front of the person
12. Map owner → I4 : commit the code, then say to go on
13. I4 → C131 : carry the answer back to the accept steps @ [SKILL.md](skill/coyomap/SKILL.md:27)
14. C27 → I6 : write the build stamp beside the map @ [provenance.py](tools/coyomap/provenance.py:232)
15. C131 → C45 : rebuild the code survey at the new pin @ [change-impact.md](method/change-impact.md:133) · only when the map already has one
16. C45 → I8 : list the project's tracked and untracked files @ [preindex_lib.py](tools/coyomap/preindex_lib.py:190)
17. C45 → I6 : write the code survey beside the map @ [preindex.py](tools/coyomap/preindex.py:604)
18. C131 → C6 : ⟨runs SF2 — Run the gates and write the map⟩
19. C131 → I6 : commit the map, its readable view, the code survey and the report together @ [change-impact.md](method/change-impact.md:138)
20. C131 → I4 : hand back the address that opens this project's map @ [change-impact.md](method/change-impact.md:140)
21. I4 → Map owner : give the person the address of the re-pinned map

**UC3 — Leave code off the map**
1. Map owner → I7 : write one ignore pattern per line beside the map · The file is committed with the code. A .gitignore cannot say 'tracked, yet not part of what the map describes'.
2. I7 → C46 : hand over the pattern lines in the order they were written @ [ignorefile.py](tools/coyomap/ignorefile.py:195) · The last rule that matches a path is the one that decides it. So a `!` line carves an exception out of a broad ignore. A line whose `#` sits mid-line is one literal pattern, and is reported as unusable.
3. Map owner → I1 : ask for the briefing that says what will be read
4. I1 → C26 : carry the request to describe the tree, and nothing else @ [scope.py](tools/coyomap/scope.py:172)
5. C26 → C45 : walk the project's files, the same walk the survey and the checks use @ [scope.py](tools/coyomap/scope.py:74)
6. C45 → C46 : ask which rule decides each file the walk found @ [preindex_lib.py](tools/coyomap/preindex_lib.py:242)
7. C45 → E50 : record which files stayed and how many each rule took out @ [preindex_lib.py](tools/coyomap/preindex_lib.py:249) · The tally is kept on the walk, not on the parsed file. So one project's counts can never be reported for another.
8. C26 → C46 : ask what each pattern took out, for the briefing @ [scope.py](tools/coyomap/scope.py:131)
9. C26 → I1 : print the file count and every pattern beside what it took out @ [scope.py](tools/coyomap/scope.py:132)
10. I1 → Map owner : show the narrowed tree before any code is read
11. C45 → I6 : write the per-pattern counts into the code survey beside the map @ [preindex.py](tools/coyomap/preindex.py:604)
12. Map owner → I1 : ask for the map's own checks to run
13. I1 → C6 : carry the check request, whether the cheap pass or the full one @ [cli.py](tools/coyomap/cli.py:156)
14. C6 → C45 : walk the tree again instead of trusting the code survey @ [validate_analysis.py](tools/coyomap/validate_analysis.py:324) · Each coverage check re-measures the repo on its own. The ignore file is the one input both sides read, so it is always disclosed.
15. C6 → C46 : ask what each pattern decided on that second walk @ [validate_analysis.py](tools/coyomap/validate_analysis.py:328)
16. C6 → I1 : name every pattern that decided nothing on this tree @ [validate_analysis.py](tools/coyomap/validate_analysis.py:337) · A pattern that took nothing out is a typo, or a tree that moved. Left unsaid it reads as coverage the author never got.
17. I1 → Map owner : show what the map was told to leave out, on every check run

**UC9 — Change the map by asking**
1. Map owner → I4 : ask in plain language to move, split or rename part of the map
2. I4 → C134 : point the agent at the clone and at the one document that decides the mode @ [SKILL.md](skill/coyomap/SKILL.md:27)
3. C134 → C26 : ⟨runs SF1 — Choose the build mode⟩
4. Map owner → I1 : run the map commands the method names
5. I1 → C24 : carry the request to read one element's stored record @ [dump.py](tools/coyomap/dump.py:322)
6. C24 → E1 : read the stored record of the element the person named @ [dump.py](tools/coyomap/dump.py:138)
7. I1 → C48 : carry the request for a proposed split of one crowded screen @ [cli.py](tools/coyomap/cli.py:183)
8. C48 → I1 : print a proposed grouping for a screen that holds too many boxes @ [balance.py](tools/coyomap/balance.py:281)
9. I1 → Map owner : show the split as a starting point, never as ready to apply
10. I1 → C23 : carry one addressed row rewrite, refusing an address that matches none or many @ [fix.py](tools/coyomap/fix.py:1961)
11. C23 → C4 : merge the harvest pieces first, so an edit that would mint or retire an id is refused @ [fix.py](tools/coyomap/fix.py:1436) · Rows are merged by their own text. Rewriting that text can split one row in two, or collapse two into one.
12. C23 → E1 : rewrite the named rows in the piece that authored them @ [fix.py](tools/coyomap/fix.py:1668) · One write for the whole batch. A later bad edit never leaves the file half changed.
13. C23 → C47 : repoint every use case step that rode an arrow the change removed @ [fix.py](tools/coyomap/fix.py:480)
14. C23 → E36 : note under its own heading the warning the person judged acceptable @ [record.py](tools/coyomap/record.py:101)
15. C23 → I1 : name every field that changed, old value then new @ [fix.py](tools/coyomap/fix.py:1674)
16. I1 → Map owner : show what changed before the checks run
17. C23 → C6 : ⟨runs SF2 — Run the gates and write the map⟩

**UC10 — Score whether the method got better**
1. Method author → I5 : ask for a score on the change to the instructions
2. I5 → C135 : hand the agent the scoring recipe to follow @ [SKILL.md](eval/SKILL.md:28)
3. Method author → I2 : type the eval commands the recipe names, over the two maps
4. I2 → C100 : route each typed sub-command to the checker that answers it @ [cli.py](eval/tools/coyomap_eval/cli.py:65)
5. C100 → C101 : reduce each map to the numbers two builds can be compared on @ [cli.py](eval/tools/coyomap_eval/cli.py:72)
6. C101 → E1 : read the built map and count what it holds @ [profile.py](eval/tools/coyomap_eval/profile.py:595)
7. C100 → C104 : hand over the doubters' votes and the scorers' marks @ [cli.py](eval/tools/coyomap_eval/cli.py:84)
8. C104 → C103 : fold the votes and the marks into one quality report @ [run.py](eval/tools/coyomap_eval/run.py:394) · a doubter who could not check the code counts as a failure, never as a refusal
9. C100 → C105 : list the relations the rebuild dropped while the code still makes them @ [cli.py](eval/tools/coyomap_eval/cli.py:93)
10. C100 → C104 : run one scoring pass over the frozen candidate map @ [cli.py](eval/tools/coyomap_eval/cli.py:75) · refused when the map no longer matches the fingerprint taken at freeze time
11. C104 → E55 : read the accepted map's stored numbers @ [run.py](eval/tools/coyomap_eval/run.py:78)
12. C104 → C102 : check the fresh map's numbers against the accepted one's @ [run.py](eval/tools/coyomap_eval/run.py:67)
13. C102 → C104 : return the verdict: as good, drifted, or worse @ [compare.py](eval/tools/coyomap_eval/compare.py:518)
14. C104 → E55 : file the fresh map's numbers with the run @ [run.py](eval/tools/coyomap_eval/run.py:166)
15. C104 → I2 : print the verdict with the gates and bands that moved @ [run.py](eval/tools/coyomap_eval/run.py:274)
16. I2 → Method author : show the verdict and where the run was filed

**UC11 — Review a finished build**
1. Method author → I5 : ask for a review of the build that just finished
2. I5 → C136 : point the reviewer at the review recipe and its preconditions @ [SKILL.md](eval/retro/SKILL.md:28)
3. C136 → C110 : refuse the review while anything is still writing the map @ [method.md](eval/retro/method.md:62)
4. C110 → E1 : parse the stored map to catch one a build is still writing @ [retro_precheck.py](eval/tools/coyomap_eval/retro_precheck.py:185)
5. C110 → I11 : look for another chat still being appended to @ [retro_precheck.py](eval/tools/coyomap_eval/retro_precheck.py:216)
6. C136 → C111 : ask the code history whether the last review's finished rows really shipped @ [method.md](eval/retro/method.md:221)
7. C136 → C107 : cut the build's chat into one turn per model answer @ [method.md](eval/retro/method.md:421)
8. C107 → I11 : read the build's own chat file @ [transcript.py](eval/tools/coyomap_eval/transcript.py:328)
9. C136 → C108 : price the build in minutes and tokens per row of map @ [method.md](eval/retro/method.md:444)
10. C108 → I11 : read every helper's chat file beside the lead's @ [cost.py](eval/tools/coyomap_eval/cost.py:272)
11. C136 → C109 : score the run against the method's checked rules @ [method.md](eval/retro/method.md:419)
12. C109 → C107 : take the run's turns from the reader that groups them @ [process_scorecard.py](eval/tools/coyomap_eval/process_scorecard.py:3335)
13. C109 → E1 : load the finished map for the checks whose subject is the map @ [process_scorecard.py](eval/tools/coyomap_eval/process_scorecard.py:1851)
14. C109 → I12 : write the run's score sheet into the reports folder @ [process_scorecard.py](eval/tools/coyomap_eval/process_scorecard.py:3592)
15. I12 → Method author : leave the score sheet where the method author reads it
16. C136 → C107 : print one slice of the chat for each fresh reader @ [method.md](eval/retro/method.md:562)
17. C136 → I5 : hand over the findings, the proposals and what could not be checked @ [method.md](eval/retro/method.md:814)
18. I5 → Method author : put the finished review in front of the method author

**UC1 — Install coyomap into a coding agent**
1. Map owner → I1 : run `make install` in the cloned coyomap folder
2. I1 → C20 : create the folder-local Python environment and install the map tool into it @ [Makefile](Makefile:40) · installing the skill depends on this step, so one command covers both
3. I1 → C134 : copy the skill pointer into every coding agent's skills folder, with this clone's path written into it @ [Makefile](Makefile:74)
4. C134 → I4 : point the coding agent at the method's entry document inside this clone @ [SKILL.md](skill/coyomap/SKILL.md:27)
5. I4 → Map owner : give the person's coding agent a `/coyomap` command it can run

**UC4 — Serve the maps on this machine**
1. Map owner → I1 : run `coyomap serve` to put every mapped project on one page
2. I1 → C20 : hand the typed command, its port and its options to the tool @ [cli.py](tools/coyomap/cli.py:139)
3. C20 → C83 : start the local map server on the requested port @ [cli.py](tools/coyomap/cli.py:168)
4. C83 → C85 : read the project folders remembered from earlier sessions @ [serve.py](tools/coyomap/viewer/serve.py:883) · no disk scan; the served set is exactly the remembered list
5. C83 → E1 : read each remembered folder's map for its title, goal and pinned commit @ [serve.py](tools/coyomap/viewer/serve.py:123)
6. C83 → I1 : report how many projects are being served and the address to open @ [serve.py](tools/coyomap/viewer/serve.py:889)
7. I1 → Map owner : show the address the maps are served at, and how to stop the server
8. C83 → I3 : open the landing page in the person's browser @ [serve.py](tools/coyomap/viewer/serve.py:895) · only when `--open` was asked for
9. I3 → C83 : carry the landing page's request for the remembered projects @ [serve.py](tools/coyomap/viewer/serve.py:642)
10. C83 → C85 : re-read the remembered folders, so a project mapped since startup appears without a restart @ [serve.py](tools/coyomap/viewer/serve.py:675)
11. C83 → I3 : return one card per remembered project, saying which of their maps can be opened @ [serve.py](tools/coyomap/viewer/serve.py:677)
12. I3 → Map owner : list every mapped project on one page, each one openable or removable

**UC5 — Explore a project's map**
1. Map reader → C62 : ⟨runs SF20 — Open a project's map in the browser⟩
2. Map reader → I3 : pick the Features tab
3. I3 → C70 : pass the chosen tab to the page frame @ [viewer.html](tools/coyomap/viewer/viewer.html:118)
4. C70 → C65 : record the new screen and write its address @ [viewer.js](tools/coyomap/viewer/viewer.js:5116)
5. C65 → C66 : draw one card per feature, in the story column @ [viewer.js](tools/coyomap/viewer/viewer.js:13006)
6. C66 → C61 : build one card for each feature @ [viewer.js](tools/coyomap/viewer/viewer.js:10919)
7. C61 → E40 : read each box's name, its type and its one sentence @ [viewer.js](tools/coyomap/viewer/viewer.js:1265)
8. C66 → I3 : put the feature cards on the page @ [viewer.js](tools/coyomap/viewer/viewer.js:10934)
9. I3 → Map reader : show what the product does, feature by feature
10. Map reader → I3 : click one feature's card
11. I3 → C61 : pass the feature's address to the cards @ [viewer.js](tools/coyomap/viewer/viewer.js:13016)
12. C61 → C65 : open that feature's own page @ [viewer.js](tools/coyomap/viewer/viewer.js:1401)
13. C65 → C66 : list the feature's use cases and the people who drive them @ [viewer.js](tools/coyomap/viewer/viewer.js:8719)
14. Map reader → I3 : drill from one use case into its numbered steps
15. I3 → C62 : pass the use case's address to the canvas @ [viewer.js](tools/coyomap/viewer/viewer.js:6503)
16. C62 → I3 : draw the use case's flow, one box per thing it touches @ [viewer.js](tools/coyomap/viewer/viewer.js:13104)
17. I3 → Map reader : show every step of that feature, in order
18. Map reader → I3 : click one box on the picture
19. I3 → C63 : pass the box click to the click rules @ [viewer.js](tools/coyomap/viewer/viewer.js:5895)
20. C63 → C64 : show that box's card in the info pane @ [viewer.js](tools/coyomap/viewer/viewer.js:4158)
21. C64 → I3 : put the box's card beside the picture @ [viewer.js](tools/coyomap/viewer/viewer.js:2881)
22. I3 → Map reader : show one box's name, type, sentence and code link

**UC6 — Open the code behind a box**
1. Map reader → C62 : ⟨runs SF20 — Open a project's map in the browser⟩
2. Map reader → I3 : open one box's own page
3. I3 → C60 : pass the element's address to the page @ [viewer.js](tools/coyomap/viewer/viewer.js:13011)
4. C60 → E40 : read that box's name, file and line @ [viewer.js](tools/coyomap/viewer/viewer.js:2818)
5. C60 → I3 : render the box's page with its code link @ [viewer.js](tools/coyomap/viewer/viewer.js:2837)
6. I3 → Map reader : show everything the map holds about that one box
7. Map reader → I3 : pick the code link on the box
8. I3 → C69 : pass the picked code link to the source column @ [viewer.js](tools/coyomap/viewer/viewer.js:223)
9. C69 → C83 : fetch that file's text at the map's own commit @ [viewer.js](tools/coyomap/viewer/viewer.js:14537)
10. C83 → C69 : return the file exactly as the pinned commit holds it @ [serve.py](tools/coyomap/viewer/serve.py:797)
11. C69 → I3 : show the file, scrolled to the box's line @ [viewer.js](tools/coyomap/viewer/viewer.js:14396)
12. I3 → Map reader : show the code behind the box, beside the map
13. Map reader → I3 : press the open button on the file's header
14. I3 → C69 : pass the open request to the source column @ [viewer.js](tools/coyomap/viewer/viewer.js:13930)
15. C69 → I9 : open the file at that line in the reader's own editor @ [viewer.js](tools/coyomap/viewer/viewer.js:14925)
16. I9 → Map reader : put the reader in their editor, at the mapped line
17. C69 → I10 : open the file on the code host at the pinned commit @ [viewer.js](tools/coyomap/viewer/viewer.js:14928) · the fallback path: the reader chose the code host, or no editor link could be built
18. I10 → Map reader : show the file on the web, pinned to the map's commit

---

## T6b — Sub-flows (shared step sequences, referenced by the flows above)

**SF1 — Choose the build mode**
1. C134 → C130 : read the dispatcher end to end @ [SKILL.md](skill/coyomap/SKILL.md:27)
2. C130 → C20 : run every coyomap command from the clone's own command line @ [dispatch.md](method/dispatch.md:4)
3. C20 → C26 : print the build briefing before anything else runs @ [cli.py](tools/coyomap/cli.py:180)
4. C26 → I8 : read the project's own files to see what the build will cover @ [scope.py](tools/coyomap/scope.py:74)
5. C26 → C46 : drop every path the project's own ignore list names @ [scope.py](tools/coyomap/scope.py:131) · a pattern that removed nothing is reported as such
6. C26 → I1 : print what will be read and what the map will be pinned to @ [scope.py](tools/coyomap/scope.py:172)
7. I1 → Map owner : show the person the briefing before any work starts
8. C130 → I6 : look for a map already in the project's map folder @ [dispatch.md](method/dispatch.md:75)

**SF2 — Run the gates and write the map**
1. C20 → C6 : run every name, link, story and record check over the map @ [cli.py](tools/coyomap/cli.py:156)
2. C6 → E1 : read the stored map back and refuse one whose shape is wrong @ [validate_model.py](tools/coyomap/validate_model.py:6585)
3. C6 → I8 : open every cited file and line to prove the code links exist @ [validate_model.py](tools/coyomap/validate_model.py:6265)
4. C20 → C21 : make the map's stories and its arrows refute each other @ [cli.py](tools/coyomap/cli.py:159)
5. C20 → C80 : render the map's readable view @ [cli.py](tools/coyomap/cli.py:165)
6. C80 → I6 : write the readable view beside the stored map @ [render.py](tools/coyomap/viewer/render.py:53)

**SF20 — Open a project's map in the browser**
1. Map reader → I3 : open the map server's home address
2. I3 → C83 : pass the browser's request to the map server @ [serve.py](tools/coyomap/viewer/serve.py:640)
3. C83 → C85 : re-read the project folders this machine remembers @ [serve.py](tools/coyomap/viewer/serve.py:675)
4. C83 → I3 : list every remembered project with its title and its commit @ [serve.py](tools/coyomap/viewer/serve.py:677)
5. I3 → Map reader : show one card per remembered project
6. Map reader → I3 : pick a project card
7. I3 → C83 : pass the chosen project's address to the server @ [serve.py](tools/coyomap/viewer/serve.py:730)
8. C83 → C70 : send back the page frame every map is drawn with @ [serve.py](tools/coyomap/viewer/serve.py:730)
9. C70 → C60 : start the script that loads the map @ [viewer.html](tools/coyomap/viewer/viewer.html:359)
10. C60 → C83 : ask the server for this map's whole drawing data @ [viewer.js](tools/coyomap/viewer/viewer.js:172)
11. C83 → E1 : read the stored project map @ [serve.py](tools/coyomap/viewer/serve.py:509)
12. C83 → C80 : turn the stored map into the graph the browser draws @ [serve.py](tools/coyomap/viewer/serve.py:511)
13. C80 → E39 : assemble the graph, one box per element @ [views.py](tools/coyomap/views.py:1282)
14. C83 → C82 : pre-render every diagram, timeline and flow of this map @ [serve.py](tools/coyomap/viewer/serve.py:516)
15. C83 → C60 : return the finished drawing data @ [serve.py](tools/coyomap/viewer/serve.py:752)
16. C60 → C62 : draw the screen the address names @ [viewer.js](tools/coyomap/viewer/viewer.js:15892)
17. C62 → I3 : put the drawn map on the page @ [viewer.js](tools/coyomap/viewer/viewer.js:13104)
18. I3 → Map reader : show the reader the product's map

---

## T7 — Business logic (the decisions this product makes)

One decision per rule, with every place it is enforced. The component on each site line and the
use-case steps under it are DERIVED from the site anchors — no field carries them.

### What gets mapped *(BLK1)*

Decides which of a project's files a map describes, and how coarsely.

**BR1 — Version control decides the code** — A map covers the files a project's version control accounts for, including new files it does not already skip.  *(verified)*
- [tools/coyomap/preindex_lib.py:198](tools/coyomap/preindex_lib.py:198) — Code survey (C45) · Asks version control for the files it already tracks.
- [tools/coyomap/preindex_lib.py:201](tools/coyomap/preindex_lib.py:201) — Code survey (C45) · Adds files the author created but never registered, minus what version control skips.
- [tools/coyomap/preindex_lib.py:222](tools/coyomap/preindex_lib.py:222) — Code survey (C45) · The file list for a project starts from version control, not from the folder tree.

**BR2 — Build output is not the product** — Packaged output, copied-in libraries and lock files never count as a project's own code.  *(verified)*
- [tools/coyomap/preindex_lib.py:148](tools/coyomap/preindex_lib.py:148) — Code survey (C45) · Drops every file sitting under a known build, package or vendor folder.
- [tools/coyomap/preindex_lib.py:150](tools/coyomap/preindex_lib.py:150) — Code survey (C45) · Drops the lock files a package manager writes for itself.
- [tools/coyomap/preindex_lib.py:257](tools/coyomap/preindex_lib.py:257) — Code survey (C45) · Keeps the same folders out when the project has no version control at all.

**BR3 — A project may leave out its own code** — A project can list committed code that its map must leave out.  *(verified)*
- [tools/coyomap/ignorefile.py:88](tools/coyomap/ignorefile.py:88) — Ignore list (C46) · Keeps the last pattern that matched, so a later line can put a file back.
- [tools/coyomap/ignorefile.py:95](tools/coyomap/ignorefile.py:95) — Ignore list (C46) · Answers whether a file is left out, from the pattern that decided it.
- [tools/coyomap/preindex_lib.py:245](tools/coyomap/preindex_lib.py:245) — Code survey (C45) · Removes the file from the set a build will read.

**BR4 — Leaving code out is never silent** — Every run reports what a project's own skip list removed, one pattern at a time.  *(verified)*
- [tools/coyomap/validate_model.py:6288](tools/coyomap/validate_model.py:6288) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Says the tree was narrowed on every check, not only the thorough one.
- [tools/coyomap/scope.py:133](tools/coyomap/scope.py:133) — Build briefing (C26) · Prints one line per pattern in the briefing a person reads before a build.
- [tools/coyomap/ignorefile.py:129](tools/coyomap/ignorefile.py:129) — Ignore list (C46) · Builds the line saying how many files each pattern removed.
- [tools/coyomap/validate_analysis.py:336](tools/coyomap/validate_analysis.py:336) — Shape checks (C6) · Names the patterns that removed nothing, which read as coverage the author never got.

**BR5 — One box is a folder-sized unit** — One box covers about one folder of code, at most ten files or three thousand lines.  *(verified)*
- [tools/coyomap/preindex_lib.py:599](tools/coyomap/preindex_lib.py:599) — Code survey (C45) · A folder inside both limits becomes one box and is not opened further.
- [tools/coyomap/preindex_lib.py:615](tools/coyomap/preindex_lib.py:615) — Code survey (C45) · One oversized folder holding no subfolders splits into several boxes.
- [method.md:1591](method.md:1591) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · States the size one box should cover, in the instructions a build follows.

**BR6 — Coarseness advises, never blocks** — Findings about how coarsely a map is drawn are advice, because deliberate abstraction is allowed.  *(verified)*
- [tools/coyomap/validate_model.py:6299](tools/coyomap/validate_model.py:6299) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Files a folded-away module as advice rather than as a failure.
- [tools/coyomap/validate_model.py:6308](tools/coyomap/validate_model.py:6308) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Files the box-count nudge as advice rather than as a failure.
- [tools/coyomap/validate_model.py:6680](tools/coyomap/validate_model.py:6680) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · The run fails on real errors only, so advice never stops it.

**BR7 — A recorded coarse decision stops the advice** — A map can record a deliberate coarse decision, and the advice about that decision then stops.  *(verified)*
- [tools/coyomap/validate_model.py:6293](tools/coyomap/validate_model.py:6293) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Reads the folders a map records as deliberately drawn coarsely.
- [tools/coyomap/validate_analysis.py:171](tools/coyomap/validate_analysis.py:171) — Shape checks (C6) · Skips a folder that sits at or under one the map recorded.
- [tools/coyomap/validate_model.py:6307](tools/coyomap/validate_model.py:6307) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Skips the box-count nudge when the map records that altitude decision.

**BR8 — A previous map is never an input** — The map a build replaces is never an input to the new one.  *(inferred)*
- [method/dispatch.md:135](method/dispatch.md:135) — Mode dispatch instructions (C130) · Tells a build not to open the map it is replacing.
- [tools/coyomap/scope.py:116](tools/coyomap/scope.py:116) — Build briefing (C26) · Warns before a build when a stray map sits among the files to be read.
- [tools/coyomap/preindex_lib.py:108](tools/coyomap/preindex_lib.py:108) — Code survey (C45) · Keeps the folder holding a map out of the files a build reads.

### What counts as a way in *(BLK2)*

Decides whether a command or an address is a door into the product, or something the product owns.

**BR20 — Acts on the live product** — A command is a way in only when it acts on the running product or its stored data.  *(verified)*
- [method.md:466](method.md:466) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · States the only test that decides a command: what the command acts on, not its name and not its purpose.
- [method/templates/harvest-contract.md:95](method/templates/harvest-contract.md:95) — Fan-out worker contracts (C132) · Hands the same test to the agent that mints the way-in rows. A table shows what counts on each side.

**BR21 — Moved out, still written down** — A command judged not to be a way in must still be recorded as a run or build command.  *(inferred)*
- [method.md:482](method.md:482) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · Says the decision is only half the work. The other half is writing the command into the run-and-build list.
- [method/templates/harvest-contract.md:125](method/templates/harvest-contract.md:125) — Fan-out worker contracts (C132) · Makes the mover count and name every command it took out, so the second half becomes visible in the reply.

**BR22 — One way in at the acting command** — A way in is recorded once, at the thing that does the acting, and never again at whatever calls it.  *(inferred)*
- [method/templates/harvest-contract.md:115](method/templates/harvest-contract.md:115) — Fan-out worker contracts (C132) · Says a command calling one of the product's own addresses adds no new way in. The address already is one.
- [method/templates/harvest-contract.md:117](method/templates/harvest-contract.md:117) — Fan-out worker contracts (C132) · Says a wrapper and the command it wraps are one way in, recorded at the command that acts.
- [method.md:477](method.md:477) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · States both cuts in the method itself, so the rule survives outside the worker brief.

**BR23 — Self-started work is not a way in** — A timer, a boot hook or a queue reader is work the product does to itself, not a way in.  *(verified)*
- [tools/coyomap/validate_model.py:2594](tools/coyomap/validate_model.py:2594) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Rejects an interface that claims a self-started way in, and says the work is the product acting on itself.
- [tools/coyomap/validate_model.py:770](tools/coyomap/validate_model.py:770) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Keeps only the outside-driven ways in, so every outside-edge check reads the same shorter list.
- [tools/coyomap/grammar.py:575](tools/coyomap/grammar.py:575) — Shared map grammar (C2) · Fixes, per kind of way in, which ones are self-started and which ones somebody outside asks for.

**BR24 — Unknown kind counts as outside-driven** — A way in of a kind nobody recognises is treated as one somebody outside asks for.  *(verified)*
- [tools/coyomap/grammar.py:599](tools/coyomap/grammar.py:599) — Shared map grammar (C2) · Answers outside-driven whenever no self-starting word matches the kind of the way in.

**BR25 — One way in, exactly one interface** — Every way in that somebody outside asks for belongs to exactly one interface, or its absence is recorded.  *(verified)*
- [method.md:641](method.md:641) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · States the one-interface rule and the recorded line that excuses a deliberate exception.
- [tools/coyomap/validate_model.py:2598](tools/coyomap/validate_model.py:2598) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Blocks a way in that more than one interface claims, and blocks one interface listing it twice.
- [tools/coyomap/validate_model.py:2764](tools/coyomap/validate_model.py:2764) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Collects the ways in that no interface claims and that no recorded line excuses.

**BR26 — Shared request handling is not a way in** — Work every request passes through on its way in is not itself a way in, so it joins no interface.  *(verified)*
- [tools/coyomap/validate_model.py:2486](tools/coyomap/validate_model.py:2486) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Names shared request handling as the one kind excused from belonging to an interface.
- [tools/coyomap/validate_model.py:2500](tools/coyomap/validate_model.py:2500) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Drops that kind before every check that asks which interface a way in belongs to.

**BR27 — Every way in owes a story** — A way in that no story reaches is reported, including the ones the product starts for itself.  *(verified)*
- [method.md:212](method.md:212) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · States that self-started ways in are not exempt, because a scheduled job is an actor with a goal.
- [tools/coyomap/validate_model.py:2142](tools/coyomap/validate_model.py:2142) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Reports the outside-driven ways in that no story reaches, grouped by the part of the product that owns them.
- [tools/coyomap/validate_model.py:2149](tools/coyomap/validate_model.py:2149) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Reports the self-started ways in that no story reaches, in the same grouped shape.

### What counts as an outside surface *(BLK3)*

Decides where the product ends, what kind of thing each edge is, and who stands on the far side.

**BR40 — Read-back is not a crossing** — Data the product writes only to read back crosses no interface, unless the map records an outside reader.  *(verified)*
- [method.md:511](method.md:511) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · Keeps the product's own database, cache and queue off the outside edge.
- [method.md:515](method.md:515) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · Lets a reader the map records overturn that exclusion, so a store a person browses counts again.
- [method/model.md:460](method/model.md:460) — Map model spec (C129) · Repeats the same exclusion on the page that fixes every field a map may hold.

**BR41 — Name the far side, never the pipe** — A step names the service on the far side, never the proxy or the library that carries the call.  *(verified)*
- [method.md:516](method.md:516) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · Names a reverse proxy and a log shipper as carriers, and the log store as the real edge.
- [tools/coyomap/validate_model.py:2840](tools/coyomap/validate_model.py:2840) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Flags a story step that stops at a carrier standing in front of an interface.
- [tools/coyomap/validate_model.py:2851](tools/coyomap/validate_model.py:2851) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Flags the same shortcut inside shared steps, where one carrier is drawn in every story running them.

**BR42 — Every outside system is decided** — Each outside system names the interfaces it stands on, or records why it is none, never both.  *(verified)*
- [tools/coyomap/validate_model.py:2744](tools/coyomap/validate_model.py:2744) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Stops a map where an outside system neither claims an interface nor gives a reason.
- [tools/coyomap/validate_model.py:2531](tools/coyomap/validate_model.py:2531) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Stops a system that claims an interface and also gives a reason for having none.
- [method/model.md:530](method/model.md:530) — Map model spec (C129) · Demands the reason on every outside system that names no interface.

**BR43 — Kind says what an interface is** — An interface is labelled by what it is, never by what it is for.  *(verified)*
- [tools/coyomap/validate_model.py:2630](tools/coyomap/validate_model.py:2630) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Flags a label that answers what the interface is for, such as payments or analytics.
- [tools/coyomap/lint_fragment.py:244](tools/coyomap/lint_fragment.py:244) — Fragment self-check (C5) · Catches the same purpose label while one part of the map is still being written.
- [method.md:564](method.md:564) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · States that a payment service and a crash reporter are the same kind of thing.

**BR44 — Far side comes from the stories** — Who stands on the far side of an interface is read from the flows, never written by hand.  *(verified)*
- [tools/coyomap/validate_model.py:1248](tools/coyomap/validate_model.py:1248) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Takes each person standing at a step next to an interface as its far side.
- [method/model.md:487](method/model.md:487) — Map model spec (C129) · States that the far side has no field of its own.
- [method.md:625](method.md:625) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · Forbids writing the far side by hand, and names the two ways it is worked out.

**BR45 — Every crossing takes a door** — A person meets the product through an interface at every step, not only the first and the last.  *(verified)*
- [tools/coyomap/validate_model.py:2947](tools/coyomap/validate_model.py:2947) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Calls a step a crossing when a person is at one end, code at the other, and no interface between.
- [tools/coyomap/validate_model.py:2837](tools/coyomap/validate_model.py:2837) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Reports every such step of a story, so a crossing in the middle is heard about too.
- [method.md:661](method.md:661) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · States that a crossing in the middle of a story owes a door like the two ends.

**BR46 — Own scheduled work is not an outsider** — Work the product schedules for itself is never an outsider, so it crosses no interface.  *(verified)*
- [tools/coyomap/validate_model.py:918](tools/coyomap/validate_model.py:918) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Drops a role that is both a machine and internal from the list of outsiders.
- [method.md:652](method.md:652) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · States that the product's own scheduled work is not an actor for the door rule.

### When a map is well formed *(BLK4)*

Decides which findings stop a build, which only advise, and what a written reason may silence.

**BR60 — Advisory never blocks** — An advisory never stops a build; only a gate does.  *(verified)*
- [tools/coyomap/validate_model.py:6657](tools/coyomap/validate_model.py:6657) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · fails a build on gate findings alone, however many advisories were printed
- [tools/coyomap/lint_fragment.py:654](tools/coyomap/lint_fragment.py:654) — Fragment self-check (C5) · passes one fragment, counting its advisories, when no gate finding was found
- [method.md:1604](method.md:1604) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · states that the component count check advises, and that a justified exception stays a judgement call

**BR61 — Clean is the narrowest verdict** — A build is clean only when every gate ran and no advisory is left open.  *(verified)*
- [tools/coyomap/finalize.py:693](tools/coyomap/finalize.py:693) — Build closer (C25) · calls a build incomplete when a gate that should have run did not
- [tools/coyomap/finalize.py:695](tools/coyomap/finalize.py:695) — Build closer (C25) · calls a build advisory when only advisories were found, which is not clean
- [tools/coyomap/finalize.py:1286](tools/coyomap/finalize.py:1286) — Build closer (C25) · exits with failure on an incomplete build, so a skipped gate cannot read as a pass
- [tools/coyomap/ship.py:353](tools/coyomap/ship.py:353) — Build closer (C25) · stops the closing sequence at the first failing step, and names the steps that never ran

**BR62 — Silence by recorded reason** — An advisory the operator decides to live with is silenced only by a reason recorded in the map.  *(inferred)*
- [method.md:1620](method.md:1620) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · says a durably justified exception is recorded in the map and silences its own advisory
- [method.md:1640](method.md:1640) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · forbids rewording the map to dodge an advisory, and asks for a recorded reason instead
- [tools/coyomap/records.py:324](tools/coyomap/records.py:324) — Shared map grammar (C2) · matches a finding against the recorded reasons, so only a recorded one is passed over

**BR63 — Recorded reasons must name a finding** — A recorded reason is refused unless it names a finding the checks really read.  *(verified)*
- [tools/coyomap/record.py:268](tools/coyomap/record.py:268) — Map editor (C23) · refuses a reason filed under a heading no check ever reads
- [tools/coyomap/record.py:309](tools/coyomap/record.py:309) — Map editor (C23) · refuses a reason that answers no finding, and writes nothing at all
- [tools/coyomap/records.py:243](tools/coyomap/records.py:243) — Shared map grammar (C2) · reads nothing from a reason listing several things when one of them is not a finding

**BR64 — Every silence is announced** — Every advisory a recorded reason silenced is still counted out loud in the build's report.  *(verified)*
- [tools/coyomap/validate_model.py:720](tools/coyomap/validate_model.py:720) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · adds a line saying how many advisories the recorded reasons silenced, and on which elements
- [tools/coyomap/validate_analysis.py:329](tools/coyomap/validate_analysis.py:329) — Shape checks (C6) · names on every build the code a written exclusion removed from every check
- [tools/coyomap/records.py:286](tools/coyomap/records.py:286) — Shared map grammar (C2) · reports a reason that failed to parse instead of dropping it in silence
- [tools/coyomap/anchor_drift.py:199](tools/coyomap/anchor_drift.py:199) — Map checks (C21) · collects a line that tries to be a reason and answers nothing, so the build reports it
- [tests/test_method_contract.py:671](tests/test_method_contract.py:671) — *unverified — no component claims this file* · keeps the announcement of a silence out of reach of any recorded reason

**BR65 — Some findings carry no excuse** — A finding whose only honest answer is a fix cannot be silenced by a recorded reason.  *(inferred)*
- [tests/test_method_contract.py:531](tests/test_method_contract.py:531) — *unverified — no component claims this file* · holds the findings no recorded reason may silence, each beside the reason it cannot
- [method.md:2093](method.md:2093) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · refuses any way to record a use case as deliberately left untold
- [tools/coyomap/anchor_drift.py:437](tools/coyomap/anchor_drift.py:437) — Map checks (C21) · tells an operator that a recorded reason cannot answer a finding about a code link's shape

**BR66 — Every advisory says where to answer it** — An advisory must say where the operator records the reason for living with it.  *(verified)*
- [tests/test_method_contract.py:716](tests/test_method_contract.py:716) — *unverified — no component claims this file* · fails when an advisory leaves the reader nowhere to record the decision
- [tools/coyomap/validate_model.py:6676](tools/coyomap/validate_model.py:6676) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · prints beside the advisories the command that records a reason the checks will find

### How a claim is grounded *(BLK5)*

Decides what counts as a claim being challenged, and what a partial pass is allowed to record.

**BR80 — Majority settles a claim** — A claim is settled only when most reviewers gave the same answer. A split with no majority stays unsettled.  *(verified)*
- [tools/coyomap/grounding.py:105](tools/coyomap/grounding.py:105) — Grounding record (C22) · calls a claim confirmed only when more than half the votes on it say so
- [tools/coyomap/grounding.py:107](tools/coyomap/grounding.py:107) — Grounding record (C22) · calls a claim disproved only when more than half the votes on it say so
- [tools/coyomap/grounding.py:121](tools/coyomap/grounding.py:121) — Grounding record (C22) · sends a split with no majority to the unsettled outcome instead of crediting either side

**BR81 — Three answers, nothing else** — A reviewer answers holds up, disproved, or cannot tell. Any other word is refused rather than counted.  *(verified)*
- [tools/coyomap/grounding.py:422](tools/coyomap/grounding.py:422) — Grounding record (C22) · refuses to build the honesty record when a vote carries a word outside the three
- [tools/coyomap/grounding.py:1119](tools/coyomap/grounding.py:1119) — Grounding record (C22) · fails the early check on the vote files for the same unknown word, while the reviewer is still nearby
- [method.md:2496](method.md:2496) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · tells every reviewer to answer cannot tell when the code settles nothing, so the third answer stays reachable

**BR82 — Vote makes a challenge** — A claim counts as challenged only when a reviewer voted on it.  *(verified)*
- [tools/coyomap/grounding.py:469](tools/coyomap/grounding.py:469) — Grounding record (C22) · counts the challenged claims as the captured list minus every claim that drew no vote
- [method.md:2432](method.md:2432) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · defines the challenged number as how many claims got a verdict, not how many were sent out

**BR83 — Stopping early must be declared** — A pass that leaves claims unvoted is refused unless someone declares that stopping early was deliberate. The declaration must say which claims were prioritized.  *(verified)*
- [tools/coyomap/grounding.py:446](tools/coyomap/grounding.py:446) — Grounding record (C22) · refuses the honesty record when a captured claim has no vote and nobody declared the stop
- [tools/coyomap/grounding.py:457](tools/coyomap/grounding.py:457) — Grounding record (C22) · refuses a declared partial pass that does not say what it prioritized
- [method.md:2435](method.md:2435) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · states the refusal, because a planned stop and a dead batch of reviewers look identical from inside the tool
- [method.md:2468](method.md:2468) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · requires the written reason, because the counts say how many claims were checked and never why those ones

**BR84 — Full surface stays in the record** — A pass that checked only part of the map still records the size of the whole claim surface.  *(verified)*
- [tools/coyomap/grounding.py:468](tools/coyomap/grounding.py:468) — Grounding record (C22) · sets the total from the whole captured list, whatever share of it drew votes
- [method.md:2470](method.md:2470) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · forbids cutting the captured list down to what was checked as a way past the refusal

**BR85 — Judged against the list reviewers saw** — A vote about a claim missing from the list captured for the reviewers is refused.  *(verified)*
- [tools/coyomap/grounding.py:428](tools/coyomap/grounding.py:428) — Grounding record (C22) · refuses the record when a vote names a claim the captured list never held
- [method.md:2548](method.md:2548) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · requires capturing the list before any correction lands, so the two sides still describe one moment

**BR86 — Disproved claim may not ship** — A build stops when the map still carries a claim its reviewers disproved, word for word.  *(inferred)*
- [tools/coyomap/grounding.py:1591](tools/coyomap/grounding.py:1591) — Grounding record (C22) · fails the check when a disproved claim still matches a row of the finished map
- [tools/coyomap/finalize.py:416](tools/coyomap/finalize.py:416) — Build closer (C25) · turns each surviving disproved claim into a blocking finding of the closing report

**BR87 — Cited but never opened** — A file cited as evidence that the reviewer's own record never names fails the check. A file it only saw printed by a search is flagged, not failed.  *(verified)*
- [tools/coyomap/grounding.py:1417](tools/coyomap/grounding.py:1417) — Grounding record (C22) · fails the check for a cited file that appears nowhere in the reviewer's own turn record
- [tools/coyomap/grounding.py:1425](tools/coyomap/grounding.py:1425) — Grounding record (C22) · reports a file the reviewer only saw printed as worth a second look, without failing it

### Which line an anchor may point at *(BLK6)*

Decides which line stands as evidence for a claim, and when a stored one has drifted.

**BR100 — Acting line, not the header** — A code link claiming an action must name the acting line, never a definition, an import or a comment.  *(verified)*
- [tools/coyomap/anchors.py:131](tools/coyomap/anchors.py:131) — Shared map grammar (C2) · Refuses every line shape that can never act.
- [tools/coyomap/validate_model.py:5957](tools/coyomap/validate_model.py:5957) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Reports each stored link sitting on a line that cannot act.
- [method.md:1314](method.md:1314) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · Tells the map builder to link the write, call or enforce line itself.

**BR101 — One line, or a stated absence** — A decision's evidence is exactly one numbered line, or a note saying no single line enforces the decision.  *(verified)*
- [tools/coyomap/validate_model.py:1686](tools/coyomap/validate_model.py:1686) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Refuses evidence that names no line and does not declare the absence.
- [tools/coyomap/validate_model.py:1689](tools/coyomap/validate_model.py:1689) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Refuses evidence that names a line and also declares there is none.
- [tools/coyomap/validate_model.py:1692](tools/coyomap/validate_model.py:1692) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Refuses evidence naming only a file, with no line number.
- [tools/coyomap/validate_model.py:5579](tools/coyomap/validate_model.py:5579) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Repeats the same refusal when the whole map is checked, not one piece.
- [method/model.md:570](method/model.md:570) — Map model spec (C129) · States that a decision's link is the one link whose line number is required.

**BR102 — Two kinds of code link** — Only a link claiming an action fires there is checked against the line. A link showing where a thing is defined is not.  *(verified)*
- [tools/coyomap/validate_model.py:5907](tools/coyomap/validate_model.py:5907) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Skips a relation the definition heading itself declares, like one type extending another.
- [tools/coyomap/validate_model.py:5924](tools/coyomap/validate_model.py:5924) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Includes a decision's own line, the strongest claim in the map that a line acts.
- [tools/coyomap/validate_model.py:5945](tools/coyomap/validate_model.py:5945) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Skips a link into a written document, where no line acts.

**BR103 — Wrong link, warning only** — A code link on the wrong line is only a warning, because the claim it carries can still be true.  *(verified)*
- [tools/coyomap/validate_model.py:6269](tools/coyomap/validate_model.py:6269) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Files each wrongly placed link under warnings, never under failures.
- [tools/coyomap/lint_fragment.py:626](tools/coyomap/lint_fragment.py:626) — Fragment self-check (C5) · Shows the same finding to the map builder as advice, so the check still passes.

**BR104 — Split verdict confirms nothing** — A stored link is judged out of date only when most reviewers agreed the claim it carries is true.  *(verified)*
- [tools/coyomap/anchor_drift.py:90](tools/coyomap/anchor_drift.py:90) — Map checks (C21) · Skips a claim whose votes are tied or missing.
- [method.md:2383](method.md:2383) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · States that two reviewers cannot form a majority.

**BR105 — Links that are never moved** — A claim whose code link deliberately points at a declaration is never moved onto the line a reviewer read.  *(verified)*
- [tools/coyomap/anchor_drift.py:86](tools/coyomap/anchor_drift.py:86) — Map checks (C21) · Skips the comparison for a claim marked as report only.
- [tools/coyomap/audit_model.py:1213](tools/coyomap/audit_model.py:1213) — Map checks (C21) · Marks a claim about where records are kept as report only.
- [tools/coyomap/audit_model.py:472](tools/coyomap/audit_model.py:472) — Map checks (C21) · Refuses to write a correction for a kind of claim that has no movable link.

**BR106 — Corrections stay in the parts' own code** — A corrected code link is refused when it lands in a file that neither end of the relation claims.  *(verified)*
- [tools/coyomap/audit_model.py:431](tools/coyomap/audit_model.py:431) — Map checks (C21) · Refuses the correction and names the two parts whose files were checked.
- [tools/coyomap/fix.py:251](tools/coyomap/fix.py:251) — Map editor (C23) · Runs the refusal before any correction is written into the map.
- [tools/coyomap/reconcile.py:678](tools/coyomap/reconcile.py:678) — Assignment rules (C47) · Runs the same refusal when a recorded correction is replayed later.

**BR107 — One written excuse, one claim** — A person may excuse one code link a check called out. The note must quote the whole claim, then give the reason.  *(verified)*
- [tools/coyomap/anchor_drift.py:195](tools/coyomap/anchor_drift.py:195) — Map checks (C21) · Accepts a written excuse only in the form that quotes a claim and gives a reason.
- [tools/coyomap/anchor_drift.py:229](tools/coyomap/anchor_drift.py:229) — Map checks (C21) · Drops exactly the one finding whose claim the note quotes.

### How elements are grouped *(BLK7)*

Decides how many boxes a screen may hold, and what regrouping is allowed to change.

**BR120 — Five boxes a screen** — Every screen of the map should hold between three and nine boxes. Five is the number it aims for.  *(verified)*
- [method.md:1609](method.md:1609) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · states the target of five boxes a screen and the readable range of three to nine
- [tools/coyomap/balance_lib.py:613](tools/coyomap/balance_lib.py:613) — Diagram balance (C48) · counts a screen as reading well only when its box count falls inside that range
- [tools/coyomap/balance.py:67](tools/coyomap/balance.py:67) — Diagram balance (C48) · marks a screen holding ten boxes or more as past the readable range

**BR121 — Same-kind lists read dense** — A screen whose boxes are all the same kind reads as a list, so fifteen boxes are fine there.  *(verified)*
- [method.md:1614](method.md:1614) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · grants the one exemption, for a screen of same-kind neighbours sharing a folder or a name ending
- [tools/coyomap/balance_lib.py:309](tools/coyomap/balance_lib.py:309) — Diagram balance (C48) · holds back the crowded-screen advice for such a screen until it passes fifteen boxes
- [tools/coyomap/balance.py:66](tools/coyomap/balance.py:66) — Diagram balance (C48) · labels the same screen exempt in the report instead of crowded

**BR122 — Thin screens count only at the top** — Only the first screen is faulted for holding too few boxes. A screen deeper down may be small.  *(verified)*
- [method.md:1612](method.md:1612) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · says too few boxes is a fault at the first screen only, and normal deeper down
- [tools/coyomap/balance_lib.py:290](tools/coyomap/balance_lib.py:290) — Diagram balance (C48) · raises the too-few-boxes advice for the first screen and for no other
- [tools/coyomap/balance.py:147](tools/coyomap/balance.py:147) — Diagram balance (C48) · names the thin deeper screens in the report while saying they are not a fault

**BR123 — One-child levels earn nothing** — A group holding exactly one thing is reported, because that level costs a click and adds no meaning.  *(verified)*
- [method.md:1613](method.md:1613) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · names a group with one member as a level pulling no weight, to be removed or grown
- [tools/coyomap/balance_lib.py:303](tools/coyomap/balance_lib.py:303) — Diagram balance (C48) · reports a group whose single member is one box rather than another group
- [tools/coyomap/validate_model.py:6317](tools/coyomap/validate_model.py:6317) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · reports a group whose single member is another group of the same kind

**BR124 — Crowding advises, never blocks** — A crowded or thin screen is only ever advice. It never refuses a map or stops a build.  *(verified)*
- [method.md:1673](method.md:1673) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · states that screen density never refuses a map, because grouping is a free choice about the picture
- [tools/coyomap/validate_model.py:6328](tools/coyomap/validate_model.py:6328) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · files every screen-density finding as advice rather than as a fault that refuses the map
- [tools/coyomap/finalize.py:587](tools/coyomap/finalize.py:587) — Build closer (C25) · records the density findings in the closing report without moving its verdict

**BR125 — Regrouping never resizes boxes** — Regrouping may only move boxes between groups. It may never merge or split the boxes themselves.  *(inferred)*
- [method.md:1675](method.md:1675) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · forbids any density finding from merging or splitting boxes to reach a number
- [tools/coyomap/balance.py:107](tools/coyomap/balance.py:107) — Diagram balance (C48) · writes a split suggestion as a change of which group a box sits in, and nothing else
- [tools/coyomap/balance.py:109](tools/coyomap/balance.py:109) — Diagram balance (C48) · tells the reader applying a suggestion to add no member the suggestion did not list

**BR126 — Groups carry no arrows** — A group is never one end of an arrow, so moving a box into another group moves no arrow.  *(verified)*
- [method.md:3134](method.md:3134) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · says dissolving a level moves no arrow, because a group is never an end of one
- [tools/coyomap/validate_model.py:5283](tools/coyomap/validate_model.py:5283) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · refuses a map holding any arrow that starts or ends at a group

**BR127 — Grouping starts above fifteen boxes** — Grouping is worth doing only once a map passes about fifteen boxes. A smaller map stays flat.  *(inferred)*
- [method.md:414](method.md:414) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · makes groups optional, and recommends them only above about fifteen boxes
- [tools/coyomap/balance_lib.py:280](tools/coyomap/balance_lib.py:280) — Diagram balance (C48) · asks for groups only once an ungrouped map passes that count

### What a screen may show *(BLK8)*

Decides which view a thing belongs to, and which facts a picture may leave off a box.

**BR140 — One home screen per thing** — Every thing the map records belongs to exactly one screen.  *(verified)*
- [tools/coyomap/viewer/viewer.js:13472](tools/coyomap/viewer/viewer.js:13472) — Info pane (C64), Viewer shell (C70) · Picks, for each kind of thing, the single screen that draws it.
- [tools/coyomap/viewer/viewer.js:7647](tools/coyomap/viewer/viewer.js:7647) — Info pane (C64), Viewer shell (C70) · Reads that same choice to decide which tab a thing's own page sits under.
- [tools/coyomap/viewer/viewer.js:7651](tools/coyomap/viewer/viewer.js:7651) — Info pane (C64), Viewer shell (C70) · Sends a page about one thing to the tab that thing lives under.
- [method/diagrams.md:54](method/diagrams.md:54) — Map model spec (C129) · Tells the map builder that a link to a thing lands on that thing's home screen.

**BR141 — Ordinary case wears no label** — A label that would be true of nearly every card is left off.  *(verified)*
- [tools/coyomap/viewer/viewer.js:8219](tools/coyomap/viewer/viewer.js:8219) — Info pane (C64), Viewer shell (C70) · Leaves off the word saying who a feature serves when the answer is the ordinary one.
- [tools/coyomap/viewer/viewer.js:721](tools/coyomap/viewer/viewer.js:721) — Info pane (C64), Viewer shell (C70) · Gives a person on the customer's side no word saying whose side they are on.

**BR142 — Nothing said twice on one screen** — A screen leaves off a fact it already shows beside the same thing.  *(verified)*
- [tools/coyomap/viewer/viewer.js:730](tools/coyomap/viewer/viewer.js:730) — Info pane (C64), Viewer shell (C70) · Drops a card's sentence when the sentence only repeats the card's own name.
- [tools/coyomap/viewer/viewer.js:6915](tools/coyomap/viewer/viewer.js:6915) — Info pane (C64), Viewer shell (C70) · Drops the feature line when the path above the page already names that feature.
- [tools/coyomap/viewer/viewer.js:8345](tools/coyomap/viewer/viewer.js:8345) — Info pane (C64), Viewer shell (C70) · Skips a group heading that would only repeat the section heading above it.

**BR143 — Colour and mark replace the type word** — A box drops the type word wherever its colour and mark already say what kind of thing it is.  *(verified)*
- [tools/coyomap/viewer/viewer.js:987](tools/coyomap/viewer/viewer.js:987) — Info pane (C64), Viewer shell (C70) · Prints the type word only for the box sizes that ask for it, and for every interface.
- [tools/coyomap/viewer/gen_viewer.py:3057](tools/coyomap/viewer/gen_viewer.py:3057) — Diagram builder (C82) · Asks for the small box on a flow picture, which carries no type word.
- [method/diagrams.md:56](method/diagrams.md:56) — Map model spec (C129) · Tells the map builder to colour each box on a flow picture by its kind.

**BR144 — Empty screen is not offered** — A screen is offered only when the map holds something to draw on it.  *(verified)*
- [tools/coyomap/viewer/viewer.js:15584](tools/coyomap/viewer/viewer.js:15584) — Info pane (C64), Viewer shell (C70) · Hides the decisions tab on a map that states no decision.
- [tools/coyomap/viewer/viewer.js:15585](tools/coyomap/viewer/viewer.js:15585) — Info pane (C64), Viewer shell (C70) · Hides the interfaces tab on a map that records no interface.
- [tools/coyomap/viewer/viewer.js:15595](tools/coyomap/viewer/viewer.js:15595) — Info pane (C64), Viewer shell (C70) · Drops a whole group of tabs once every tab inside it has been hidden.
- [tools/coyomap/viewer/gen_viewer.py:3417](tools/coyomap/viewer/gen_viewer.py:3417) — Diagram builder (C82) · Works out from the map whether there is any interface for a tab to show.

**BR145 — A gap is stated, never blank** — Where the map records nothing, the screen says so instead of leaving empty space.  *(inferred)*
- [tools/coyomap/viewer/viewer.js:8541](tools/coyomap/viewer/viewer.js:8541) — Info pane (C64), Viewer shell (C70) · Says a feature reaches no outside service, rather than showing an empty block.
- [tools/coyomap/viewer/viewer.js:12874](tools/coyomap/viewer/viewer.js:12874) — Info pane (C64), Viewer shell (C70) · Says no flow step reaches this decision, rather than showing an empty block.
- [tools/coyomap/viewer/viewer.js:12757](tools/coyomap/viewer/viewer.js:12757) — Info pane (C64), Viewer shell (C70) · Says no flow comes through this interface, so no feature can be named here.

**BR146 — A relation line never points at code** — A line between two things offers no code link, because the place it names is only one example.  *(verified)*
- [tools/coyomap/viewer/viewer.js:3052](tools/coyomap/viewer/viewer.js:3052) — Info pane (C64), Viewer shell (C70) · Builds a relation row as plain text, with no link to a line of code.
- [tools/coyomap/viewer/viewer.js:2957](tools/coyomap/viewer/viewer.js:2957) — Info pane (C64), Viewer shell (C70) · Clears the file browser's highlighted row, so an earlier pick cannot read as this line's place.
- [tools/coyomap/viewer/viewer.js:14163](tools/coyomap/viewer/viewer.js:14163) — Info pane (C64), Viewer shell (C70) · Marks a line of code from a flow step's own place, never from a relation line.

**BR147 — A flow picture draws only that flow** — A picture of one flow draws only the connections that flow itself makes.  *(verified)*
- [tools/coyomap/viewer/gen_viewer.py:3081](tools/coyomap/viewer/gen_viewer.py:3081) — Diagram builder (C82) · Builds each arrow from the flow's own steps, grouped by the pair of things they join.
- [method/diagrams.md:58](method/diagrams.md:58) — Map model spec (C129) · Tells the map builder that the arrows are the flow's steps, never the general connection list.

### What a build may read and write *(BLK9)*

Decides which files a build may open, and where a change has to be written to survive.

**BR160 — Mapping coyomap needs saying so** — A run refuses to read or overwrite coyomap's own map unless the operator declares coyomap is the project being mapped.  *(access)*  *(verified)*
- [tools/coyomap/model.py:1443](tools/coyomap/model.py:1443) — Map model (C1) · Refuses to read a map stored inside coyomap's own copy unless the run declared that coyomap is the project.
- [tools/coyomap/model.py:1408](tools/coyomap/model.py:1408) — Map model (C1) · Refuses the same target for a write, so a stray build cannot overwrite the accepted map of coyomap.
- [method.md:1369](method.md:1369) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · Tells the build the refusal exists, and warns that a hand written script is not covered by the refusal.

**BR161 — Git decides what is read** — Only files git accounts for are analysed, so ignored and generated trees stay out of the map.  *(verified)*
- [tools/coyomap/preindex_lib.py:198](tools/coyomap/preindex_lib.py:198) — Code survey (C45) · Takes the starting file list from everything git tracks in the project.
- [tools/coyomap/preindex_lib.py:201](tools/coyomap/preindex_lib.py:201) — Code survey (C45) · Adds files someone created but never added yet, and leaves every ignored path to git.
- [tools/coyomap/preindex_lib.py:148](tools/coyomap/preindex_lib.py:148) — Code survey (C45) · Drops dependency folders, build output and caches by name, whether or not git is there to ask.

**BR162 — Every exclusion is announced** — A project's own exclusion patterns are named on every run, each beside the number of files it removed.  *(verified)*
- [tools/coyomap/validate_model.py:6288](tools/coyomap/validate_model.py:6288) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Names the patterns on every check run, including the cheap pass a lead runs most often.
- [tools/coyomap/ignorefile.py:133](tools/coyomap/ignorefile.py:133) — Ignore list (C46) · Collects each pattern that removed nothing, so a typo cannot read as coverage the map never got.
- [tools/coyomap/scope.py:131](tools/coyomap/scope.py:131) — Build briefing (C26) · Puts the same per pattern account in the briefing, printed before a build reads any code.
- enforced at: Build a project's first map (UC2) → SF1 step 5 · Leave code off the map (UC3) step 8 · See what a code change did to the map (UC7) → SF1 step 5 · Fold a change report into the baseline (UC8) → SF1 step 5 · Change the map by asking (UC9) → SF1 step 5

**BR163 — Previous map stays closed** — A build never opens the map it is replacing, so the new map cannot quietly copy the old one.  *(verified)*
- [method/dispatch.md:135](method/dispatch.md:135) — Mode dispatch instructions (C130) · Bans opening the map being replaced, including the one version history still holds and one already filed away.
- [tools/coyomap/scope.py:116](tools/coyomap/scope.py:116) — Build briefing (C26) · Warns when a copy of a map sits among the files that are about to be read as code.

**BR164 — Rebuild only when asked** — A map is built again from scratch only when the person asks, because a rebuild discards the accepted map.  *(inferred)*
- [method/dispatch.md:187](method/dispatch.md:187) — Mode dispatch instructions (C130) · Sends an existing map to a change report, and makes a fresh build need a spoken request and a confirmation.
- [method.md:2831](method.md:2831) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · Says a build writes a new map over any existing one, so nothing of the older map is kept.

**BR165 — Corrections live at the source** — A correction only lasts where the build reads from, because every file the build produces is written again from scratch.  *(verified)*
- [tools/coyomap/fix.py:136](tools/coyomap/fix.py:136) — Map editor (C23) · Warns that a correction made to the finished map disappears the next time the pieces are merged.
- [tools/coyomap/fix.py:470](tools/coyomap/fix.py:470) — Map editor (C23) · Refuses a removal aimed at one piece, because the pieces beside that one cannot be seen from there.
- [tools/coyomap/assemble.py:922](tools/coyomap/assemble.py:922) — Map assembly (C4) · Applies the recorded assignments after every merge, which is what makes those assignments last.
- [method.md:2742](method.md:2742) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · States the split: what must survive a rebuild goes in the assignment file, never in the finished map.
- [tools/coyomap/validate_model.py:6134](tools/coyomap/validate_model.py:6134) — Shape checks (C6), Story checks (C7), Rule checks (C8), Wiring checks (C9), Data checks (C10) · Compares the committed readable copy with a freshly generated one, and reports any difference.
- [method/dispatch.md:194](method/dispatch.md:194) — Mode dispatch instructions (C130) · States that the readable copy is generated from the map and never edited by hand.

**BR166 — Accepted warnings get written down** — A warning the person decides to accept is silenced only by a note written under a heading the checks read.  *(verified)*
- [tools/coyomap/record.py:85](tools/coyomap/record.py:85) — Map editor (C23) · Refuses a heading no check reads, because a note filed under such a heading silences nothing.
- [tools/coyomap/finalize.py:635](tools/coyomap/finalize.py:635) — Build closer (C25) · Drops each file named by a recorded note out of the advisory the finish check would otherwise raise.
- [method/dispatch.md:110](method/dispatch.md:110) — Mode dispatch instructions (C130) · Names the heading the finish check reads, after twenty notes were filed where nothing could find them.

**BR167 — Uncommitted code marks the pin** — A map names the version of the code it describes. That name is marked when the code on disk was never committed.  *(verified)*
- [tools/coyomap/provenance.py:191](tools/coyomap/provenance.py:191) — Build log (C27) · appends the mark to the version name when anything is uncommitted
- [tools/coyomap/provenance.py:164](tools/coyomap/provenance.py:164) — Build log (C27) · asks version control what is uncommitted, ignoring the map's own folder
- [method/change-impact.md:129](method/change-impact.md:129) — Change impact instructions (C131) · tells the agent to offer the choice, and to mark the pin only if the person declines to commit
- enforced at: Fold a change report into the baseline (UC8) step 10

### Who may reach a served map *(BLK10)*

Decides which requests the local map server answers, and which files it will hand back.

**BR180 — Local machine only** — A served map is reachable only from the machine that runs the server.  *(access)*  *(verified)*
- [tools/coyomap/viewer/serve.py:885](tools/coyomap/viewer/serve.py:885) — Map server (C83) · Opens the listening address on this machine alone, so a connection from another machine never arrives.
- [tools/coyomap/viewer/serve.py:634](tools/coyomap/viewer/serve.py:634) — Map server (C83) · Refuses a page request whose address names any host other than this machine.
- [tools/coyomap/viewer/serve.py:655](tools/coyomap/viewer/serve.py:655) — Map server (C83) · Refuses the same way for a request that changes the remembered project list.

**BR181 — Deliberately added projects only** — A project folder is served only when it was deliberately added, never because the server found it.  *(access)*  *(inferred)*
- [tools/coyomap/viewer/serve.py:883](tools/coyomap/viewer/serve.py:883) — Map server (C83) · Builds the served set from the remembered folder list alone, with no search of the disk.
- [tools/coyomap/viewer/serve.py:697](tools/coyomap/viewer/serve.py:697) — Map server (C83) · Refuses to add a folder that holds no coyomap data folder inside it.
- [tools/coyomap/viewer/serve.py:878](tools/coyomap/viewer/serve.py:878) — Map server (C83) · Applies the same check to a folder named when the server is started.
- [tools/coyomap/viewer/serve.py:658](tools/coyomap/viewer/serve.py:658) — Map server (C83) · Refuses a change to the remembered list unless the request came from this server's own start page.
- enforced at: Serve the maps on this machine (UC4) step 4

**BR182 — No path leaves the project** — A request for a file can only ever reach inside the mapped project's own folder.  *(access)*  *(verified)*
- [tools/coyomap/viewer/serve.py:778](tools/coyomap/viewer/serve.py:778) — Map server (C83) · Rejects a file request whose path is absolute or climbs above the project folder.
- [tools/coyomap/viewer/serve.py:380](tools/coyomap/viewer/serve.py:380) — Map server (C83) · Rejects a working copy read that escapes the project or names the version history folder.
- [tools/coyomap/viewer/serve.py:387](tools/coyomap/viewer/serve.py:387) — Map server (C83) · Refuses a file whose real location, after following a shortcut, sits outside the project folder.
- [tools/coyomap/viewer/serve.py:849](tools/coyomap/viewer/serve.py:849) — Map server (C83) · Hands back a shared page asset only when the requested name is one of the two allowed names.

**BR183 — Ignored files stay hidden** — A file that version history deliberately ignores is never handed back to the browser.  *(access)*  *(verified)*
- [tools/coyomap/viewer/serve.py:391](tools/coyomap/viewer/serve.py:391) — Map server (C83) · Allows a working copy read when version history already tracks the file.
- [tools/coyomap/viewer/serve.py:393](tools/coyomap/viewer/serve.py:393) — Map server (C83) · Allows an untracked file only when no ignore rule covers it.

**BR184 — Frozen at the map's commit** — Code shown beside the map is the version the map was built from, not whatever sits on disk now.  *(verified)*
- [tools/coyomap/viewer/serve.py:782](tools/coyomap/viewer/serve.py:782) — Map server (C83) · Answers a file request at the map's own commit unless the address asks for another version.
- [tools/coyomap/viewer/serve.py:491](tools/coyomap/viewer/serve.py:491) — Map server (C83) · Builds the file list from version history at the map's commit rather than from the folder on disk.
- [method.md:3108](method.md:3108) — Product description instructions (C120), Code inventory instructions (C121), Outside edge instructions (C122), Data and step instructions (C123), Operations and decision instructions (C124), Cross-cutting build instructions (C125), Fan-out phase instructions (C126), Verification phase instructions (C127), Closing sequence instructions (C128) · The instructions tell the reader that data and source both come from history at the map's commit.

**BR185 — Plain version names only** — A version name arriving in a web address is refused unless it reads as an ordinary commit name.  *(access)*  *(verified)*
- [tools/coyomap/viewer/serve.py:790](tools/coyomap/viewer/serve.py:790) — Map server (C83) · Refuses a requested version that is not a plain commit identifier.
- [tools/coyomap/viewer/serve.py:301](tools/coyomap/viewer/serve.py:301) — Map server (C83) · Skips the history read entirely when the map's own recorded commit is not plain.
- [tools/coyomap/impact_git.py:60](tools/coyomap/impact_git.py:60) — Change impact (C49) · Refuses a version name from a web address that does not read as an ordinary one.

**BR186 — Fingerprint-checked outside code** — Code fetched from the public internet runs in the viewer only when its fingerprint matches the expected one.  *(access)*  *(inferred)*
- [tools/coyomap/viewer/viewer.html:17](tools/coyomap/viewer/viewer.html:17) — Viewer shell (C70) · Pins the expected fingerprint of the picture panning library.
- [tools/coyomap/viewer/viewer.html:20](tools/coyomap/viewer/viewer.html:20) — Viewer shell (C70) · Pins the expected fingerprint of the diagram drawing library.
- [tools/coyomap/viewer/viewer.js:14094](tools/coyomap/viewer/viewer.js:14094) — Info pane (C64), Viewer shell (C70) · Pins the expected fingerprint of the styling that colours source code.
- [tools/coyomap/viewer/viewer.js:14097](tools/coyomap/viewer/viewer.js:14097) — Info pane (C64), Viewer shell (C70) · Pins the expected fingerprint of the code colouring library itself.

**BR187 — Known editors only** — A source link may open only through an address belonging to a known code editor.  *(access)*  *(verified)*
- [tools/coyomap/viewer/viewer.js:14880](tools/coyomap/viewer/viewer.js:14880) — Info pane (C64), Viewer shell (C70) · Offers no link when the built address is not one a known editor answers.
- [tools/coyomap/viewer/viewer.js:15011](tools/coyomap/viewer/viewer.js:15011) — Info pane (C64), Viewer shell (C70) · Refuses to save a hand-typed link pattern whose address is not a known editor one.

### When two maps may be compared *(BLK11)*

Decides whether two scores are comparable at all, and how far a measurement may move.

**BR200 — Same code on both sides** — Two maps are scored against each other only when both describe the same code. A run over changed code refuses.  *(verified)*
- [eval/method.md:176](eval/method.md:176) — Map quality eval instructions (C135) · orders the run to stop as soon as any same-code check fails
- [eval/method.md:48](eval/method.md:48) — Map quality eval instructions (C135) · states that a score across two different states of the code is not a verdict on the instructions
- [eval/tools/coyomap_eval/arrows.py:258](eval/tools/coyomap_eval/arrows.py:258) — Lost arrows (C105) · blocks the dropped-relation check when source files moved between the two maps

**BR201 — Uncommitted code voids a map** — A map built over uncommitted code can never be scored, and nobody may waive that refusal.  *(inferred)*
- [eval/method.md:90](eval/method.md:90) — Map quality eval instructions (C135) · orders an outright refusal when a map's recorded commit says the code was uncommitted
- [eval/method.md:97](eval/method.md:97) — Map quality eval instructions (C135) · says this one refusal cannot be overridden, unlike every other same-code check

**BR202 — One judging setup for both maps** — Two quality scores compare only when one judging setup produced both, so a changed setup forces a fresh judging.  *(verified)*
- [eval/tools/coyomap_eval/compare.py:485](eval/tools/coyomap_eval/compare.py:485) — Baseline comparison (C102) · flags the comparison when the two sides were judged under different setups
- [eval/tools/coyomap_eval/run.py:455](eval/tools/coyomap_eval/run.py:455) — Eval run (C104) · tells the caller to judge again when the stored scores came from another setup
- [eval/tools/coyomap_eval/run.py:451](eval/tools/coyomap_eval/run.py:451) — Eval run (C104) · treats stored scores that record no setup at all as unusable
- [eval/method.md:283](eval/method.md:283) — Map quality eval instructions (C135) · pins every doubter and every scorer to one named model

**BR203 — Growth never counts against a map** — A map that grew is never marked down for growing, because only lost content breaches an allowance.  *(verified)*
- [eval/tools/coyomap_eval/compare.py:201](eval/tools/coyomap_eval/compare.py:201) — Baseline comparison (C102) · lets a count rise freely and breaches only on a fall past the allowance
- [eval/tools/coyomap_eval/compare.py:224](eval/tools/coyomap_eval/compare.py:224) — Baseline comparison (C102) · scores a quality measure on its drop alone, never on its rise

**BR204 — Lost check blocks, drifted number asks** — Losing a check the accepted map passed blocks the run. A number that moved too far only asks for a human look.  *(verified)*
- [eval/tools/coyomap_eval/compare.py:511](eval/tools/coyomap_eval/compare.py:511) — Baseline comparison (C102) · one failed check makes the whole verdict a block
- [eval/tools/coyomap_eval/compare.py:513](eval/tools/coyomap_eval/compare.py:513) — Baseline comparison (C102) · a number outside its allowance makes the verdict a look rather than a block

**BR205 — Code sets the right number of boxes** — How many boxes a map should hold is worked out from the code, never from the accepted map.  *(verified)*
- [eval/tools/coyomap_eval/compare.py:458](eval/tools/coyomap_eval/compare.py:458) — Baseline comparison (C102) · checks the fresh map's box count, and only that one, against what the code expects
- [eval/tools/coyomap_eval/profile.py:357](eval/tools/coyomap_eval/profile.py:357) — Map profile (C101) · works the expected box count out of the code tree at scoring time

**BR206 — Missing side refuses, never passes** — A run that cannot get one of the two sides refuses to report, instead of reporting that nothing got worse.  *(verified)*
- [eval/tools/coyomap_eval/run.py:242](eval/tools/coyomap_eval/run.py:242) — Eval run (C104) · stops when the accepted map's folder is missing, rather than scoring one map alone
- [eval/tools/coyomap_eval/run.py:247](eval/tools/coyomap_eval/run.py:247) — Eval run (C104) · stops when that folder holds no stored numbers to compare against
- [eval/tools/coyomap_eval/compare.py:491](eval/tools/coyomap_eval/compare.py:491) — Baseline comparison (C102) · marks the comparison drifted when only one of the two maps carries quality scores

**BR207 — Frozen map, or no score** — A map edited after it was frozen cannot be scored, so the run stops on any later change to it.  *(verified)*
- [eval/tools/coyomap_eval/run.py:219](eval/tools/coyomap_eval/run.py:219) — Eval run (C104) · stops the run when the map no longer matches the fingerprint taken at freeze time
- [eval/tools/coyomap_eval/run.py:212](eval/tools/coyomap_eval/run.py:212) — Eval run (C104) · stops when the freeze fingerprint was asked for but arrived empty, rather than skipping the check
- [eval/method.md:41](eval/method.md:41) — Map quality eval instructions (C135) · states that editing either map during a run voids the run

---

## Operational dimensions — the standard core four

### Deployment & topology

| Unit | Runs on | Exposed as | Config source |
|---|---|---|---|
| coyomap command line | the person's own machine, inside a folder-local Python environment the repo owns | a command typed in a terminal, and called by the coding agent | Installed in editable mode from this repo by the dependency target in the Makefile, so the repo stays the source of truth. Requires Python 3.10 or newer. |
| Map server | the person's own machine, listening only on the loopback address | a local web address on port 8765 | Started by the start target in the Makefile, which passes the port from a make variable. A second target starts the same server with live reload for someone working on the viewer. |
| coyomap skill | two skills folders in the person's home directory, one per agent family | a slash command inside the coding agent | Copied by the install target into the Claude and cross-agent skills folders, with this clone's absolute path filled in. The method files stay read from the repo, so they evolve without reinstalling. |
| coyomap-eval skill | the same two skills folders in the person's home directory | a separate slash command, for the developer of coyomap only | Installed by its own target, deliberately not by the plain install target, so the developer surface is never a side effect of setting up the tool. |
| coyomap-retro skill | the same two skills folders in the person's home directory | a separate slash command, for the developer of coyomap only | Installed by its own target, or together with the eval skill by the developer target. It reads its recipe from this clone. |
| coyomap-eval command line | the person's own machine, in the same folder-local Python environment the main command line uses | a second command typed in a terminal, for whoever changes the instructions | Declared as its own console command in pyproject.toml:46, from a package that lives beside the main one and depends on it. |

### Observability

| Signal | Where emitted | Where viewed | Alerts |
|---|---|---|---|
| Stale-code warning on the server's console | Printed to the terminal running the map server, at most once every two seconds, when the tool's own code has changed since the server started. | The terminal the person started the server in. | Nothing is configured; nobody is notified. |
| Web request log | Nothing is emitted. The server's own per-request log line is deliberately switched off. | Nowhere. | Nothing is configured. |
| A view that could not be drawn | the viewer page, when a view cannot be drawn: the failure is written to the browser's developer console and a short notice replaces the picture | the reader's own browser developer console; nothing is sent off the machine | No alerts are configured; the viewer sends nothing anywhere. |

### Security & auth

Derived from the business rules marked `access` (T7) — the decision IS the surface.

| Decision | Enforced at | Risk note |
|---|---|---|
| **BR180** — Local machine only | [tools/coyomap/viewer/serve.py:885](tools/coyomap/viewer/serve.py:885) · [tools/coyomap/viewer/serve.py:634](tools/coyomap/viewer/serve.py:634) · [tools/coyomap/viewer/serve.py:655](tools/coyomap/viewer/serve.py:655) | A map opens every line of a project's source, so a reachable server would let strangers read private code. |
| **BR181** — Deliberately added projects only | [tools/coyomap/viewer/serve.py:883](tools/coyomap/viewer/serve.py:883) · [tools/coyomap/viewer/serve.py:697](tools/coyomap/viewer/serve.py:697) · [tools/coyomap/viewer/serve.py:878](tools/coyomap/viewer/serve.py:878) · [tools/coyomap/viewer/serve.py:658](tools/coyomap/viewer/serve.py:658) | One careless start could otherwise put every repository on the machine in front of the browser. |
| **BR182** — No path leaves the project | [tools/coyomap/viewer/serve.py:778](tools/coyomap/viewer/serve.py:778) · [tools/coyomap/viewer/serve.py:380](tools/coyomap/viewer/serve.py:380) · [tools/coyomap/viewer/serve.py:387](tools/coyomap/viewer/serve.py:387) · [tools/coyomap/viewer/serve.py:849](tools/coyomap/viewer/serve.py:849) | Any page open in the browser could otherwise read private files anywhere on the machine. |
| **BR183** — Ignored files stay hidden | [tools/coyomap/viewer/serve.py:391](tools/coyomap/viewer/serve.py:391) · [tools/coyomap/viewer/serve.py:393](tools/coyomap/viewer/serve.py:393) | A local settings file holding passwords is kept out of version history, and would otherwise be readable in the map. |
| **BR185** — Plain version names only | [tools/coyomap/viewer/serve.py:790](tools/coyomap/viewer/serve.py:790) · [tools/coyomap/viewer/serve.py:301](tools/coyomap/viewer/serve.py:301) · [tools/coyomap/impact_git.py:60](tools/coyomap/impact_git.py:60) | A crafted name could otherwise be taken as an instruction and make the history reader do something else. |
| **BR186** — Fingerprint-checked outside code | [tools/coyomap/viewer/viewer.html:17](tools/coyomap/viewer/viewer.html:17) · [tools/coyomap/viewer/viewer.html:20](tools/coyomap/viewer/viewer.html:20) · [tools/coyomap/viewer/viewer.js:14094](tools/coyomap/viewer/viewer.js:14094) · [tools/coyomap/viewer/viewer.js:14097](tools/coyomap/viewer/viewer.js:14097) | A tampered drawing or highlighting library would run inside a page that already shows every line of the project's source. |
| **BR187** — Known editors only | [tools/coyomap/viewer/viewer.js:14880](tools/coyomap/viewer/viewer.js:14880) · [tools/coyomap/viewer/viewer.js:15011](tools/coyomap/viewer/viewer.js:15011) | A hand-typed link pattern could otherwise run script in the page or send the reader somewhere unexpected. |
| **BR160** — Mapping coyomap needs saying so | [tools/coyomap/model.py:1443](tools/coyomap/model.py:1443) · [tools/coyomap/model.py:1408](tools/coyomap/model.py:1408) · [method.md:1369](method.md:1369) | A shell standing in the wrong folder reads a healthy result about the wrong product, or overwrites the accepted map. |

### Config & environments

| Key | Purpose | Default | Per-env / secret? |
|---|---|---|---|
| COYOMAP_SELF_MAP | Says this run really is mapping coyomap itself, so reading or writing the tool's own map is allowed. | unset, which makes the tool refuse to touch its own map | Not set per environment. One shell session sets it for that session only. |
| COYOMAP_SELF_MAP | Allows a run to read or write coyomap's own map, which is refused by default. | not set, so the clone's own map is protected | Set by hand for one session, only when mapping coyomap itself. |
| COYOMAP_HOME | Names the clone whose method files and templates a run should read. | the installed package's own clone | Same on every machine unless a person points at a second clone. |
| COYOMAP_NO_SERVE_REGISTER | Stops a finished build from adding its project to the server's remembered list. | not set, so every build registers its project | Set by the method-quality eval so its runs do not pollute the list. |
| CLAUDE_CODE_SESSION_ID | Names the conversation a map build is stamped with. | published by the coding agent, not set by hand | Same everywhere; a build review refuses to run without it. |
| PORT | Port the local map server listens on. | 8765 | Same on every machine unless a person overrides it when starting the server. |
| PYTHONPATH | Points a child process at this checkout's tools instead of another checkout's. | unset, which falls back to the installed package | Rewritten to an absolute path at test start, so a second checkout is never tested by mistake. |
| COYOMAP_HOME | Names the code clone whose history a ledger check reads. | The clone the command is itself running from. |  |
| CLAUDE_CODE_SESSION_ID | Names the chat asking for a retrospective, so it refuses to read the build it is inside. | Nothing is set, and that one guard then stays quiet. |  |
| COYOMAP_SELF_MAP | Lets a tool open this project's own map, which is refused otherwise. | Turned on for the length of one map load, then put back as it was. |  |
| CLAUDE_CODE_SESSION_ID | Names the conversation the archive records as the one that built this map. | the id the coding agent sets for the running conversation |  |
| COYOMAP_HOME | Says which folder the method and its agent brief templates are read from. | the installed package's own folder |  |
| CLAUDE_CODE_SESSION_ID | Names the session that gets stamped as the builder of this map. | nothing, so stamping refuses until a session name is passed by hand |  |
| COYOMAP_NO_SERVE_REGISTER | Stops a finished build from adding its project to the remembered list. | Not set, so every build registers its project. | Nothing is set per environment. The map-quality scoring run sets it so its throwaway maps never appear. |
| coyomap.editor | Which editor a code link opens in. | nothing stored, so the reader is asked once before the first open |  |
| coyomap.customUri | A reader's own address form for opening a file, when their editor is not offered. | nothing stored |  |
| coyomap.srcRoot | Folder on this machine holding the mapped code, so a code link can point at it. | the folder the map was built from |  |
| coyomap.ghRepo | Web address of the repository a file opens at, pinned to the map's commit. | the repository the map was built from, when the map records one |  |
| coyomap.panelShape | Whether a selected box shows as a drawer along the bottom or a floating card. | floating card |  |
| coyomap.codeOpen | Whether the source column is open when the map is reopened. | closed |  |
| coyomap.searchOpen | Whether the search sidebar is open when the map is reopened. | closed |  |
| coyomap.coachSeen | Whether the first-run guide has already been shown to this reader. | not shown yet, so the guide opens on the first visit |  |

---

## Relationships — backbone edge list

| From | Verb | To | Why | Where (example) |
|---|---|---|---|---|
| C3 | reads | C1 | walks the map model's own field definitions to derive the published schema | [json_schema.py](tools/coyomap/json_schema.py:505) |
| C3 | reads | C2 | publishes the closed word lists the shared grammar owns, so the two cannot drift apart | [json_schema.py](tools/coyomap/json_schema.py:206) |
| C20 | calls | C24 | dispatches the read-only map subcommands | [cli.py](tools/coyomap/cli.py:177) |
| C24 | calls | C4 | loads an assembled map or a single build fragment through the assembler's loader | [dump.py](tools/coyomap/dump.py:298) |
| C24 | reads | C1 | parses the map into the model before answering anything about it | [context.py](tools/coyomap/context.py:196) |
| C46 | calls | C2 | matches each declared pattern against a repo-relative path with the shared path matcher | [ignorefile.py](tools/coyomap/ignorefile.py:87) |
| C45 | calls | C46 | loads the project's ignore list before walking its files | [preindex_lib.py](tools/coyomap/preindex_lib.py:227) |
| C26 | calls | C46 | reports which ignore patterns the briefing's walk actually hit | [scope.py](tools/coyomap/scope.py:131) |
| C84 | calls | C46 | marks the folders and files the project told the map to leave out | [filetree.py](tools/coyomap/viewer/filetree.py:260) |
| C6 | calls | C46 | loads the ignore list so a shape check knows which code was left out on purpose | [validate_analysis.py](tools/coyomap/validate_analysis.py:321) |
| C48 | reads | C1 | walks the map's group trees to count what each screen has to draw | [balance_lib.py](tools/coyomap/balance_lib.py:156) |
| C48 | calls | C2 | reads the map's recorded crowding exceptions through the shared record reader | [balance_lib.py](tools/coyomap/balance_lib.py:238) |
| C20 | calls | C48 | dispatches the crowding report | [cli.py](tools/coyomap/cli.py:183) |
| C25 | calls | C48 | runs the crowding report as one of the closing checks | [finalize.py](tools/coyomap/finalize.py:125) |
| C101 | calls | C48 | takes the crowding summary numbers for a map's score sheet | [profile.py](eval/tools/coyomap_eval/profile.py:383) |
| C71 | reads | E39 | indexes every named box, field and glossary word out of the drawn graph | [viewer.js](tools/coyomap/viewer/viewer.js:15114) |
| C71 | calls | C62 | opens a picked result where it lives, by selecting its box | [viewer.js](tools/coyomap/viewer/viewer.js:15120) |
| C71 | calls | C83 | asks the server for the project's code symbols, so a name in the code is findable too | [viewer.js](tools/coyomap/viewer/viewer.js:15224) |
| C72 | calls | C83 | asks the server to project a chosen commit range onto the map | [viewer.js](tools/coyomap/viewer/viewer.js:15794) |
| C72 | calls | C62 | routes a clicked impact row to the box it names | [viewer.js](tools/coyomap/viewer/viewer.js:15716) |
| C70 | loads | C73 | the viewer page pulls in the one stylesheet every view is drawn with | [viewer.html](tools/coyomap/viewer/viewer.html:12) |
| C83 | serves | C73 | sends the stylesheet to the browser on request, read from disk every time | [serve.py](tools/coyomap/viewer/serve.py:851) |
| C83 | calls | C84 | builds the file tree the viewed project's browser shows | [serve.py](tools/coyomap/viewer/serve.py:492) |
| C84 | calls | C45 | walks the project's files through the survey's own walker, so the browser shows the same set the map analyzed | [filetree.py](tools/coyomap/viewer/filetree.py:253) |
| C84 | reads | E39 | reads the drawn graph to mark each file with the boxes that point at it | [filetree.py](tools/coyomap/viewer/filetree.py:107) |
| C121 | cites | C122 | reuses the outside-edge section's rule instead of restating what is not a product interface | [method.md](method.md:489) |
| C125 | cites | C122 | places the outside-edge task in the build order, after the inventory it groups | [method.md](method.md:1465) |
| C125 | cites | C123 | places the flow-and-record task in the build order, with its edges written as each flow is | [method.md](method.md:1467) |
| C125 | cites | C132 | appends the shared writing rules to every worker contract it prints | [method.md](method.md:1333) |
| C123 | cites | C129 | sends the reader to the model spec for a record card's full shape | [method.md](method.md:884) |
| C124 | cites | C129 | sends the reader to the model spec for the accepted code-link formats | [method.md](method.md:1321) |
| C121 | cites | C129 | sends the reader to the model spec for what an arrow claims and what a catalog only lists | [method.md](method.md:505) |
| C127 | cites | C129 | sends the reader to the model spec for a field's exact meaning instead of restating it | [method.md](method.md:2205) |
| C128 | cites | C129 | names the model spec as what the stored map is judged against when a build closes | [method.md](method.md:2834) |
| C126 | cites | C132 | hands every trace agent the copyable contract kept with the templates, rather than prose composed per build | [method.md](method.md:2113) |
| C128 | cites | C132 | hands every harvest agent its copyable contract at the closing sequence | [method.md](method.md:2781) |
| C138 | cites | C132 | warns a contributor that a template's every sentence is copied into 12-20 sub-agent prompts per build | [CONTRIBUTING.md](CONTRIBUTING.md:48) |
| C136 | cites | C133 | lists the promises committed since the previous build, so the retrospective runs each one | [method.md](eval/retro/method.md:281) |
| C135 | cites | C100 | drives the whole scoring run through the eval command line rather than describing the arithmetic | [method.md](eval/method.md:215) |
| C138 | cites | C137 | names the public documentation and says what belongs in it | [CONTRIBUTING.md](CONTRIBUTING.md:40) |
| C137 | cites | C120 | tells a reader on an unsupported agent to hand the method's own instructions to it | [README.md](README.md:117) |
| C138 | cites | C139 | sends the story behind a rule to the rationale record, keeping it out of the text every build reads | [CONTRIBUTING.md](CONTRIBUTING.md:59) |
| C139 | cites | C120 | every entry quotes a phrase that must still appear in the method, so a rule cannot be reworded out from under its evidence | [method-rationale.md](internal/docs/method-rationale.md:32) |
| C20 | calls | C5 | dispatches the self-check a helper runs on its own piece of the map | [cli.py](tools/coyomap/cli.py:189) |
| C25 | calls | C5 | self-checks the one hand-written piece of the map as a closing step | [ship.py](tools/coyomap/ship.py:326) |
| C5 | calls | C4 | parses a piece through the merger's own reader, so the two never read it differently | [lint_fragment.py](tools/coyomap/lint_fragment.py:590) |
| C5 | calls | C6 | opens every file and line the piece cites, to prove each code link exists | [lint_fragment.py](tools/coyomap/lint_fragment.py:198) |
| C5 | calls | C7 | checks the piece's flows for step numbering, an actor on each step and an anchor | [lint_fragment.py](tools/coyomap/lint_fragment.py:161) |
| C5 | calls | C8 | checks that each business rule in the piece states a decision and names code lines | [lint_fragment.py](tools/coyomap/lint_fragment.py:180) |
| C5 | calls | C9 | checks each message channel in the piece for a broker, participants and the record it carries | [lint_fragment.py](tools/coyomap/lint_fragment.py:153) |
| C5 | calls | C10 | checks that each record in the piece names a real store and an allowed storage mode | [lint_fragment.py](tools/coyomap/lint_fragment.py:149) |
| C5 | calls | C27 | asks which of the project's files are uncommitted, so the piece's recorded commit can be flagged | [lint_fragment.py](tools/coyomap/lint_fragment.py:280) |
| C80 | calls | C7 | takes every flow step that carries a code link, before joining rules to steps | [views.py](tools/coyomap/views.py:1003) |
| C81 | calls | C7 | takes every flow step that carries a code link, before working out what each feature owns | [features.py](tools/coyomap/features.py:467) |
| C112 | calls | C7 | re-counts the saved records whose arrows claim a direction no flow step ever shows | [live_numbers.py](eval/tools/coyomap_eval/live_numbers.py:192) |
| C7 | reads | C1 | walks the map's flows to catch a use case told twice | [validate_model.py](tools/coyomap/validate_model.py:404) |
| C80 | calls | C8 | asks which flow steps enforce a rule, to draw the rule beside them | [views.py](tools/coyomap/views.py:1024) |
| C81 | calls | C8 | asks which flow steps enforce a rule, to give that rule to the right feature | [features.py](tools/coyomap/features.py:469) |
| C21 | calls | C8 | resolves which components own a rule's code line, through the rule family's one join | [audit_model.py](tools/coyomap/audit_model.py:1055) |
| C8 | calls | C49 | asks which function encloses a rule's line, so a rule and a step there count as one place | [validate_model.py](tools/coyomap/validate_model.py:1453) |
| C80 | calls | C9 | asks which way data crosses each interface, from the flow steps drawn at it | [views.py](tools/coyomap/views.py:1175) |
| C81 | calls | C9 | asks which way data crosses each interface a feature reaches | [features.py](tools/coyomap/features.py:554) |
| C21 | calls | C9 | asks which way data crosses each interface someone else designs, to word the finding about it | [audit_model.py](tools/coyomap/audit_model.py:1243) |
| C9 | calls | C48 | reads the recorded exceptions that silence a channel advisory, through the one reader for them | [validate_model.py](tools/coyomap/validate_model.py:3640) |
| C80 | calls | C10 | asks which writes into a store no saved record explains, for the storage page's coverage strip | [views.py](tools/coyomap/views.py:952) |
| C10 | calls | C21 | counts how many claims the map offers, to say what share of them was challenged | [validate_model.py](tools/coyomap/validate_model.py:3928) |
| C20 | calls | C21 | dispatches the pass that makes a finished map contradict itself | [cli.py](tools/coyomap/cli.py:159) |
| C22 | calls | C21 | takes the ranked list of claims a map offers, before recording how the votes on them fell | [grounding.py](tools/coyomap/grounding.py:1585) |
| C47 | calls | C21 | applies the recorded anchor corrections through the one function that rewrites a code link | [reconcile.py](tools/coyomap/reconcile.py:680) |
| C103 | calls | C21 | takes the ranked list of claims a map offers, to hand the top of it to the doubters | [judge.py](eval/tools/coyomap_eval/judge.py:234) |
| C20 | calls | C27 | dispatches the stamp that records which session built a map, and when | [cli.py](tools/coyomap/cli.py:213) |
| C26 | calls | C27 | asks which of the project's files are uncommitted, so the briefing names the pin it will use | [scope.py](tools/coyomap/scope.py:68) |
| C50 | calls | C27 | stamps the map through the same code the command line runs, so one shape is written | [map_backup.py](tools/map_backup.py:293) |
| C110 | reads | C27 | reads the build log to learn which session made the map a review would read | [retro_precheck.py](eval/tools/coyomap_eval/retro_precheck.py:179) |
| C27 | queries | D90 | asks the code history for the commit a map is pinned to | [provenance.py](tools/coyomap/provenance.py:125) |
| C27 | reads | D95 | reads the conversation name the agent publishes, so a map records which chat built it | [provenance.py](tools/coyomap/provenance.py:209) |
| C27 | writes | D91 | writes the build log beside the map, as a file the project commits | [provenance.py](tools/coyomap/provenance.py:232) |
| C83 | calls | C49 | works out which parts of the map a code change touches, for the browser page to show | [serve.py](tools/coyomap/viewer/serve.py:476) |
| C82 | calls | C49 | reads how far each mapped code link stretches, before deriving what every feature owns | [gen_viewer.py](tools/coyomap/viewer/gen_viewer.py:3345) |
| C49 | queries | D90 | runs read-only history commands to compare the project's code at two commits | [impact_git.py](tools/coyomap/impact_git.py:50) |
| C50 | writes | D91 | copies the whole map folder into a dated archive folder on disk | [map_backup.py](tools/map_backup.py:391) |
| C47 | writes | E56 | expands the build's path rules into an explicit list of assignments beside the map | [reconcile_build.py](tools/coyomap/reconcile_build.py:480) |
| C62 | calls | C63 | wires each drawn box and arrow to what a click does, once the picture exists | [viewer.js](tools/coyomap/viewer/viewer.js:13113) |
| C63 | calls | C64 | shows the picked box in the info pane instead of drilling into it | [viewer.js](tools/coyomap/viewer/viewer.js:5349) |
| C63 | calls | C65 | opens the screen a held key drills to, so the address follows the move | [viewer.js](tools/coyomap/viewer/viewer.js:5348) |
| C64 | calls | C61 | draws the selected thing as the same card every list shows | [viewer.js](tools/coyomap/viewer/viewer.js:2881) |
| C64 | calls | C69 | highlights the selected thing's file in the file browser beside the picture | [viewer.js](tools/coyomap/viewer/viewer.js:2891) |
| C62 | calls | C65 | redraws the tabs, the trail and the address for the screen just rendered | [viewer.js](tools/coyomap/viewer/viewer.js:13242) |
| C62 | calls | C66 | draws the happy path when that is the screen asked for | [viewer.js](tools/coyomap/viewer/viewer.js:13024) |
| C62 | calls | C67 | draws the storage screen when that is the screen asked for | [viewer.js](tools/coyomap/viewer/viewer.js:13068) |
| C62 | calls | C68 | draws the decision areas when that is the screen asked for | [viewer.js](tools/coyomap/viewer/viewer.js:13077) |
| C65 | calls | C62 | draws the screen the address now names | [viewer.js](tools/coyomap/viewer/viewer.js:5307) |
| C66 | calls | C61 | draws each feature as the same card every list shows | [viewer.js](tools/coyomap/viewer/viewer.js:10919) |
| C67 | calls | C61 | draws the operational lists as the same cards every other screen shows | [viewer.js](tools/coyomap/viewer/viewer.js:11720) |
| C67 | calls | C65 | opens one store's screen when a reader picks a record out of the table | [viewer.js](tools/coyomap/viewer/viewer.js:11535) |
| C68 | calls | C61 | draws each decision area as the same card every list shows | [viewer.js](tools/coyomap/viewer/viewer.js:12810) |
| C68 | calls | C65 | opens one decision area's screen when a reader picks its card | [viewer.js](tools/coyomap/viewer/viewer.js:12894) |
| C69 | calls | C83 | asks the server for the project's file list at the commit the map is pinned to | [viewer.js](tools/coyomap/viewer/viewer.js:13892) |
| C69 | requests | D161 | fetches the code-colouring library the first time a file is opened | [viewer.js](tools/coyomap/viewer/viewer.js:14100) |
| C82 | calls | C81 | works out what each feature owns, and folds the answer into the browser page's data | [gen_viewer.py](tools/coyomap/viewer/gen_viewer.py:3348) |
| C83 | calls | C82 | builds every diagram, timeline and flow of one map for the browser page | [serve.py](tools/coyomap/viewer/serve.py:516) |
| C112 | calls | C82 | re-counts the records whose lifecycle line a drawn box would actually show | [live_numbers.py](eval/tools/coyomap_eval/live_numbers.py:293) |
| C83 | calls | D92 | opens the map's address in the person's browser once the server is listening | [serve.py](tools/coyomap/viewer/serve.py:895) |
| C70 | calls | D93 | hands the chosen editor a file and a line, which the machine then opens | [viewer.js](tools/coyomap/viewer/viewer.js:14925) |
| C70 | requests | D94 | opens the file on the code host in a new tab, pinned to the map's commit | [viewer.js](tools/coyomap/viewer/viewer.js:14928) |
| C70 | requests | D96 | fetches the drawing library at a pinned version, and checks it against a stored fingerprint | [viewer.html](tools/coyomap/viewer/viewer.html:19) |
| C105 | queries | D90 | asks the code history which files changed between the two commits the maps pin | [arrows.py](eval/tools/coyomap_eval/arrows.py:184) |
| C113 | reads | D91 | reads a cited file to pick a real line that is not the one enforcing the rule | [mutate.py](eval/tools/coyomap_eval/mutate.py:112) |
| C4 | writes | E65 | builds the read of every fragment file, including the ones that failed | [assemble.py](tools/coyomap/assemble.py:298) |
| C4 | persists | E1 | writes the merged map and its readable view into the project's map folder | [assemble.py](tools/coyomap/assemble.py:978) |
| C4 | calls | C47 | applies the recorded subsystem, subdomain and anchor assignments after the merge | [assemble.py](tools/coyomap/assemble.py:939) |
| C22 | persists | E37 | writes the challenged, confirmed, refuted and unverifiable counts derived from the verdict files | [grounding.py](tools/coyomap/grounding.py:1749) |
| C6 | reads | E1 | loads the stored map before every check it runs | [validate_model.py](tools/coyomap/validate_model.py:6585) |
| C80 | reads | E1 | loads the stored map to render its readable view | [render.py](tools/coyomap/viewer/render.py:48) |
| C131 | reads | E1 | reads the pinned commit, and the map rows a code change reaches | [change-impact.md](method/change-impact.md:51) |
| C131 | writes | E46 | writes the change report, one entry per element the change touched | [change-impact.md](method/change-impact.md:13) |
| C131 | reads | E46 | reads the report's was-to-now blocks back when it is accepted | [change-impact.md](method/change-impact.md:80) |
| C23 | writes | E1 | writes every accepted correction back into the stored map | [fix.py](tools/coyomap/fix.py:119) |
| C23 | calls | C4 | writes an edited map back through the one canonical serializer | [fix.py](tools/coyomap/fix.py:119) |
| C45 | writes | E50 | builds the walk result saying which files stayed and what each ignore rule decided | [preindex_lib.py](tools/coyomap/preindex_lib.py:249) |
| C24 | reads | E1 | reads one element's stored record out of the map | [dump.py](tools/coyomap/dump.py:138) |
| C23 | writes | E36 | appends a recorded exception under its extras heading | [record.py](tools/coyomap/record.py:101) |
| C100 | calls | C101 | routes the score command to the map profiler | [cli.py](eval/tools/coyomap_eval/cli.py:72) |
| C100 | calls | C104 | routes the run, hash, claims, judge and bless commands to the run orchestrator | [cli.py](eval/tools/coyomap_eval/cli.py:75) |
| C100 | calls | C102 | routes the compare command to the baseline comparison | [cli.py](eval/tools/coyomap_eval/cli.py:96) |
| C100 | calls | C105 | routes the arrows command to the lost-relation check | [cli.py](eval/tools/coyomap_eval/cli.py:93) |
| C100 | calls | C106 | routes the archive command to the map mover | [cli.py](eval/tools/coyomap_eval/cli.py:102) |
| C100 | calls | C112 | routes the live-numbers command to the number ledger | [cli.py](eval/tools/coyomap_eval/cli.py:108) |
| C100 | calls | C113 | routes the mutate command to the planted-falsehood test | [cli.py](eval/tools/coyomap_eval/cli.py:120) |
| C104 | calls | C101 | profiles the map the run is scoring | [run.py](eval/tools/coyomap_eval/run.py:60) |
| C104 | calls | C102 | compares the fresh map's numbers with the accepted one's and takes the verdict | [run.py](eval/tools/coyomap_eval/run.py:67) |
| C104 | calls | C103 | folds the collected votes and marks into one quality report | [run.py](eval/tools/coyomap_eval/run.py:394) |
| C101 | reads | E1 | reads a built map and counts what it holds | [profile.py](eval/tools/coyomap_eval/profile.py:595) |
| C103 | reads | E1 | reads the map for the risky claims a doubter must check | [judge.py](eval/tools/coyomap_eval/judge.py:234) |
| C105 | reads | E1 | reads both maps to match their relations by source file | [arrows.py](eval/tools/coyomap_eval/arrows.py:251) |
| C112 | reads | E1 | reads the live maps the tools' sentences state numbers about | [live_numbers.py](eval/tools/coyomap_eval/live_numbers.py:498) |
| C106 | moves | E1 | moves the built map into the rebuild archive so the next build starts from nothing | [archive.py](eval/tools/coyomap_eval/archive.py:110) |
| C104 | reads | E55 | reads the accepted map's stored numbers to compare against | [run.py](eval/tools/coyomap_eval/run.py:78) |
| C104 | writes | E55 | writes the scored map's numbers into the run folder | [run.py](eval/tools/coyomap_eval/run.py:166) |
| C102 | reads | E55 | reads two stored number sheets to band them | [compare.py](eval/tools/coyomap_eval/compare.py:247) |
| C110 | reads | E1 | parses the stored map to refuse a review of one still being written | [retro_precheck.py](eval/tools/coyomap_eval/retro_precheck.py:185) |
| C109 | reads | E1 | loads the finished map for the checks whose subject is the map | [process_scorecard.py](eval/tools/coyomap_eval/process_scorecard.py:1851) |
| C107 | reads | D105 | reads a build's chat file and groups its records into one turn per model answer | [transcript.py](eval/tools/coyomap_eval/transcript.py:328) |
| C108 | reads | D105 | reads every helper's chat file beside the lead's to price the whole build | [cost.py](eval/tools/coyomap_eval/cost.py:272) |
| C110 | reads | D105 | reads other sessions' chat files to see whether a build is still running | [retro_precheck.py](eval/tools/coyomap_eval/retro_precheck.py:216) |
| C111 | queries | D90 | asks the code history whether the commit a finished row names is merged | [ledger.py](eval/tools/coyomap_eval/ledger.py:87) |
| C109 | calls | C107 | takes the run's turns from the reader that groups them | [process_scorecard.py](eval/tools/coyomap_eval/process_scorecard.py:3335) |
| C108 | calls | C107 | takes each actor's turns from the reader that groups them | [cost.py](eval/tools/coyomap_eval/cost.py:283) |
| C20 | starts | C83 | runs the local map server when the `serve` command is typed | [cli.py](tools/coyomap/cli.py:168) |
| C83 | reads | C85 | reads the remembered project folders it serves | [serve.py](tools/coyomap/viewer/serve.py:883) |
| C83 | updates | C85 | adds a folder the person opens, drops one they remove and saves a new order | [serve.py](tools/coyomap/viewer/serve.py:700) |
| C85 | persists | D91 | keeps the remembered project folders in a file under the home folder, re-read before every change | [recents.py](tools/coyomap/viewer/recents.py:44) |
| C51 | starts | C83 | runs the map server in its own process group and restarts it when the tool's Python changes | [devserve.py](tools/devserve.py:55) |
| C134 | points at | C130 | sends the coding agent to the method's entry document inside the clone it was installed from | [SKILL.md](skill/coyomap/SKILL.md:27) |
| C83 | reads | E1 | reads the stored project map on every request it serves for that project | [serve.py](tools/coyomap/viewer/serve.py:509) |
| C80 | writes | E39 | builds the whole graph the browser draws from the stored map | [views.py](tools/coyomap/views.py:1282) |
| C61 | reads | E40 | reads a box's name, type and sentence to draw its card | [viewer.js](tools/coyomap/viewer/viewer.js:724) |
| C60 | reads | E40 | reads a box's name, file and line for its details page | [viewer.js](tools/coyomap/viewer/viewer.js:2818) |

---

## Test completeness — gaps against the map

> **Tests run for this table?** The table was built by reading the two test suites, never by running them. No coverage numbers were measured.

| Target | Tested? | Test(s) | Gap / risk | Confidence |
|---|---|---|---|---|
| Refusing to overwrite coyomap's own map (Map assembly) | no |  | Nothing exercises the refusal that protects the coyomap clone's own map. A build started in the wrong folder could overwrite it. | inferred |
| Refusing to read coyomap's own map by mistake (Command line, Map reader, Map checks) | yes | [test_method_contract.py](tests/test_method_contract.py:1600) — Every map reader among the build commands passes through the refusal. · [test_method_contract.py](tests/test_method_contract.py:1626) — The refusal prints one plain line, never a crash dump. · [test_method_contract.py](tests/test_method_contract.py:1651) — Someone mapping coyomap itself can still switch the refusal off. | Three commands are driven for real. The rest are covered only by a scan of the source text. | inferred |
| Turning away a request that names another machine (Map server) | partial | [test_serve.py](tests/test_serve.py:93) — The name check accepts this machine and refuses every other name. | No test sends a real request carrying a foreign name. A wiring slip in the map server would go unnoticed. | inferred |
| Guard on requests that change the project list (Map server, Remembered projects) | no |  | No test ever sends a change request to the map server. A web page you visit could edit your project list. | inferred |
| Adding, dropping and reordering remembered projects (Remembered projects) | partial | [test_serve.py](tests/test_serve.py:145) — The remembered project list adds, removes, de-duplicates and survives a restart. · [test_serve.py](tests/test_serve.py:197) — A new order for the remembered projects is saved and read back. | The three network addresses that drive those changes are never called. Only the storage under them is tested. | inferred |
| Listing any folder on this machine (Map server) | partial | [test_serve.py](tests/test_serve.py:258) — Folder listing marks each folder that already holds a map. | The address the browser calls is never exercised. Nothing checks the answer for a folder that does not exist. | inferred |
| Health answer naming the pinned commit (Map server) | no |  | No test asks the map server whether it is answering. A break there shows only as a page that never loads. | inferred |
| Serving one file's text at the pinned commit (Map server) | yes | [test_impact_serve.py](tests/test_impact_serve.py:89) — One file's text is served at the pinned commit and at another commit. · [test_impact_serve.py](tests/test_impact_serve.py:70) — Ignored files, the version-control folder and paths that climb out are refused. · [test_serve.py](tests/test_serve.py:104) — A path that climbs above the project folder is rejected. | No test feeds a file big enough to hit the size limit. A limit that stopped working shows only as a stalled page. | inferred |
| Closing sequence that ships a build (Build closer) | partial | [test_ship.py](tests/test_ship.py:101) — The closing sequence lists its steps in the order the method sets. · [test_ship.py](tests/test_ship.py:168) — A failing step stops the run and names the steps left undone. | Every step runs against a stand-in, never the real command. A change inside one command can still break the sequence. | inferred |
| One pre-commit verdict over every check (Map checks) | yes | [test_finalize.py](tests/test_finalize.py:78) — A clean map succeeds and writes both of its reports. · [test_finalize.py](tests/test_finalize.py:86) — A blocking problem fails the run and is recorded as blocking. · [test_finalize.py](tests/test_finalize.py:97) — A check that never ran can never be reported as clean. · [test_finalize.py](tests/test_finalize.py:326) — A faked count of challenged claims is caught by recomputing it. | The suite feeds hand-built maps. No test runs the verdict over a map a real build just produced. | inferred |
| Honesty record of what the doubters challenged (Grounding record) | yes | [test_grounding.py](tests/test_grounding.py:35) — Verdict files are checked for shape, folded into votes and written back. · [test_element_checks.py](tests/test_element_checks.py:71) — Each element gets the review outcome the votes actually support. | Nothing checks the record against a full real build's verdict files. | inferred |
| Editing map rows in one all-or-nothing write (Map editor) | yes | [test_fix.py](tests/test_fix.py:924) — Two corrections landing on one row are both refused, so nothing half-lands. · [test_fix.py](tests/test_fix.py:394) — A conflicting duplicate is reported and no change is written. · [test_fix.py](tests/test_fix.py:1110) — An edit that would split a merged row is refused. | No test interrupts a write midway. A crash during the write is not covered. | inferred |
| Merging the build agents' fragments into one map (Map assembly, Fragment self-check) | yes | [test_assembly_fixture.py](tests/test_assembly_fixture.py:82) — Merging the stored fragments gives the same bytes every time. · [test_assembly_fixture.py](tests/test_assembly_fixture.py:141) — Every stored fragment passes the self-check a build agent runs. · [test_assemble.py](tests/test_assemble.py:27) — Conflicts, duplicates and missing pieces across fragments are resolved or reported. · [test_lint_fragment.py](tests/test_lint_fragment.py:25) — A fragment with invented ids or bad wording is refused before merging. | The stored fragment set is one project's. A shape only another project produces would not be met. | inferred |
| Checks a map must pass to be well formed (Shape checks, Story checks, Rule checks, Wiring checks, Data checks) | yes | [test_validate_model.py](tests/test_validate_model.py:116) — Four hundred cases cover shape, story, rule, wiring and data checks. · [test_audit.py](tests/test_audit.py:1358) — Places where a map contradicts itself are found and reported. · [test_trapdoor_tools.py](tests/test_trapdoor_tools.py:108) — Deliberately broken maps are caught rather than passed. | A check that is too loose still passes its own test. Only the trap maps push back on that. | inferred |
| Survey of the code a build starts from (Code survey) | partial | [test_preindex.py](tests/test_preindex.py:86) — The survey walks the files, names the symbols and counts the sizes. · [test_granularity.py](tests/test_granularity.py:60) — Directory expectations and size bands come out at the right grain. · [test_source_walk_git.py](tests/test_source_walk_git.py:78) — Only files version control tracks are walked. | The survey reads fifteen languages. Tests feed only Python and JavaScript, so thirteen parsers are unproven. | inferred |
| Leaving named code off the map (Ignore list) | yes | [test_ignorefile.py](tests/test_ignorefile.py:65) — Ignored paths drop out of the survey, the file tree and the counts. | No test runs a whole build with an ignore list and checks the printed counts. | inferred |
| Assigning code to groups and balancing the diagrams (Assignment rules, Diagram balance) | yes | [test_reconcile_build.py](tests/test_reconcile_build.py:51) — Path rules expand into an explicit assignment for every file. · [test_balance.py](tests/test_balance.py:76) — Diagrams holding too many boxes are named with a suggested split. | Balance is judged on small hand-built maps. Nothing checks the advice on a map the size of a real project. | inferred |
| Map data shape, shared words and schema (Map model, Shared map grammar, Map schema document) | yes | [test_model.py](tests/test_model.py:65) — Every part of a map loads, saves and round-trips without loss. · [test_grammar_roles.py](tests/test_grammar_roles.py:15) — The fixed word lists stay closed and agree with the model. · [test_json_schema.py](tests/test_json_schema.py:21) — The published schema still matches the data shape it describes. · [test_records.py](tests/test_records.py:30) — Notes headings are read into the sections a map stores. | The schema check compares shapes. Nothing validates a real map file against the schema itself. | inferred |
| Briefing that tells a build what to read (Build briefing) | yes | [test_scope.py](tests/test_scope.py:33) — The list of files a build will read is produced before it starts. · [test_contract.py](tests/test_contract.py:42) — Each helper agent's brief is printed complete and with the right ids. | No test proves a brief a helper agent receives is one it can actually follow. | inferred |
| Build log of sessions and slice timings (Build log) | yes | [test_provenance.py](tests/test_provenance.py:28) — The session that built a map is stamped and listed back. · [test_timings.py](tests/test_timings.py:41) — What each build slice took is recorded and sorted longest first. | Nothing checks the log after a real build. Only hand-written entries are read back. | inferred |
| Report of what a code change did to the map (Change impact) | yes | [test_impact.py](tests/test_impact.py:124) — A change between two commits is matched to the map parts it touches. · [test_impact_ripple.py](tests/test_impact_ripple.py:96) — A hit on one box spreads to the boxes and steps that depend on it. · [test_impact_ripple.py](tests/test_impact_ripple.py:236) — The report also comes back correctly over the network. | Repositories in the tests are tiny. A change touching hundreds of files is never tried. | inferred |
| Every command surviving a realistic map (Command line) | yes | [test_cli_sweep.py](tests/test_cli_sweep.py:237) — A new command cannot ship without joining the sweep that runs it. · [test_cli_sweep.py](tests/test_cli_sweep.py:258) — Every command runs against a real map without crashing. · [test_cli_contract.py](tests/test_cli_contract.py:99) — Every command refuses an option it does not know. · [test_cli_sweep.py](tests/test_cli_sweep.py:298) — No command hangs waiting for a person to type. | The map server is the one command left out, because starting it blocks. Its behaviour is checked elsewhere. | inferred |
| Restarting the map server when the viewer changes (Live reload supervisor) | no |  | Nothing tests the watcher that restarts the map server. A silent failure leaves developers looking at stale screens. | inferred |
| Archiving a map with the conversation that built it (Map and transcript backup) | no |  | Nothing tests the backup that moves a map and its chat aside. A bug there loses work with no warning. | inferred |
| File tree marked by how far the map covers it (File browser) | yes | [test_filetree.py](tests/test_filetree.py:54) — Folders and files come back marked by how much of the map reaches them. | The tree is built from small fixtures. A repository with deep nesting is not tried. | inferred |
| Turning a map into diagrams and cards (Diagram builder, Map rendering, Feature facts) | yes | [test_convert_and_views.py](tests/test_convert_and_views.py:86) — Each view's diagram and text are produced from the stored map. · [test_grouping.py](tests/test_grouping.py:1534) — Boxes land in the right groups and lanes on every picture. · [test_gen_deployment.py](tests/test_gen_deployment.py:26) — Processes, queues and the arrows between them are drawn correctly. · [test_features.py](tests/test_features.py:91) — Each feature's facts are gathered from the flows that reach it. | The pictures are checked as data, not as drawings. A layout that overlaps still passes. | inferred |
| Screen addresses and the trail back (Map loader, Trail and screen address) | partial | [test_viewer_browser.py](tests/test_viewer_browser.py:126) — A reload comes back to the exact screen you were on. · [test_viewer_browser.py](tests/test_viewer_browser.py:140) — Going back walks the real screens you visited. · [test_viewer_browser.py](tests/test_viewer_browser.py:173) — A broken or stale link still draws a page with a trail. | Eight kinds of address open a screen. Only the feature, actor and use case ones are opened in a browser. | inferred |
| Feature, happy path and actor pages (Product pages) | yes | [test_viewer_browser.py](tests/test_viewer_browser.py:199) — The happy path draws one line, broken where the person changes. · [test_viewer_browser.py](tests/test_viewer_browser.py:312) — Feature boxes are equal height and the line bridges the gaps. · [test_viewer_browser.py](tests/test_viewer_browser.py:2550) — An actor's board says where each use case happens. | Coverage is measured on one stored map. A product with very many features is not drawn in a test. | inferred |
| Interfaces and rules pages (Rules and interfaces pages) | partial | [test_viewer_browser.py](tests/test_viewer_browser.py:585) — Each interface card says what kind of thing it is. · [test_viewer_browser.py](tests/test_viewer_browser.py:705) — Every interface draws one plain line to the product. · [test_viewer_js.py](tests/test_viewer_js.py:482) — One shared section index builds every card page, the rules page included. | Interfaces are checked in a real browser. The rules page is only read as text, so nothing proves it draws. | inferred |
| Storage, tests and system pages (Storage, tests and system pages) | partial | [test_data_view.py](tests/test_data_view.py:105) — Each stored record's box carries where it lives and how it changes. · [test_convert_and_views.py](tests/test_convert_and_views.py:208) — Coverage rows reach the browser with their targets resolved to names. · [test_viewer_js.py](tests/test_viewer_js.py:2581) — The system page is built as cards over one shared builder. | No test opens the storage page or the coverage page in a browser. Both are checked only as data. | inferred |
| Code column beside the map (Source column) | partial | [test_viewer_browser.py](tests/test_viewer_browser.py:2324) — Opening a use case opens the code column once, then leaves it alone. · [test_viewer_browser.py](tests/test_viewer_browser.py:2424) — Opening the code column narrows the picture instead of breaking it. | Nothing tests the code text itself, its colouring, or the side-by-side view of a change. | inferred |
| Search across everything the map holds (Map search) | partial | [test_viewer_js.py](tests/test_viewer_js.py:952) — A feature found by search lands on its own card. · [test_viewer_js.py](tests/test_viewer_js.py:4553) — A search result can be pinned in the picture it belongs to. | Search is exercised outside a browser. Nothing proves the box opens, filters and closes on screen. | inferred |
| Screen for exploring a change report (Impact explorer) | no |  | Nothing tests the screen that shows what a code change did. Its data is checked, its screen is not. | inferred |
| Cards, canvas and clicking a box (Element cards, Diagram canvas, Diagram clicks, Info pane) | yes | [test_viewer_browser.py](tests/test_viewer_browser.py:2344) — A selected box gets a card joined to it by a line. · [test_viewer_browser.py](tests/test_viewer_browser.py:2361) — A box name opens the thing and its frame selects the box. · [test_viewer_browser.py](tests/test_viewer_browser.py:1015) — The inspector answers with the record the map actually stores. · [test_viewer_browser.py](tests/test_viewer_browser.py:2100) — A drawing squeezed to nothing recovers instead of staying broken. | The written rule for what a card may show is never checked against the code that draws it. | inferred |
| Viewer look in both light and dark (Viewer styles) | partial | [test_viewer_browser.py](tests/test_viewer_browser.py:372) — A board that scrolls sideways shades the edge where more content sits. · [test_viewer_browser.py](tests/test_viewer_browser.py:1164) — A pinned section bar casts its shadow only once it is stuck. | Only a handful of styling rules are measured on screen. Colour and dark mode are never checked. | inferred |
| Reader settings kept in the browser (Viewer shell) | no |  | Eight saved settings decide how source links open and how panels sit. No test reads or writes any of them. | inferred |
| Opening the code behind a box in your own editor (Open the code behind a box, Source column) | no |  | Nothing tests the editor link, the code host link, or the check that refuses an unsafe link. A bad link opens whatever it names. | inferred |
| Installing coyomap into a coding agent (Install coyomap into a coding agent, Build skill pointer) | partial | [test_skill_pointers.py](tests/test_skill_pointers.py:93) — The install steps cover every skill the project offers. · [test_skill_pointers.py](tests/test_skill_pointers.py:48) — Each skill points only at its own entry document. | Only the install text is read. Nothing performs an install and then checks the command works. | inferred |
| Building a project's first map, end to end (Build a project's first map) | partial | [test_assembly_fixture.py](tests/test_assembly_fixture.py:131) — Every check reads a freshly merged map without crashing. · [test_cli_sweep.py](tests/test_cli_sweep.py:258) — Each build command runs against a realistic map. | No test drives a whole build from source code to a finished map. The agent's part cannot run in the suite. | inferred |
| Folding a change into the map and re-checking it (Fold a change report into the baseline, Change the map by asking) | partial | [test_fix.py](tests/test_fix.py:50) — Corrections land on the right rows or are refused with a reason. · [test_mapdiff.py](tests/test_mapdiff.py:51) — Two maps of the same work are compared row by row. | Single edits are covered. Nothing walks the whole path from a change report to an accepted map. | inferred |
| Scoring a map and comparing it with the accepted one (Map profile, Baseline comparison) | yes | [test_profile.py](eval/tests/test_profile.py:682) — Every measurement taken from a map is computed and checked. · [test_compare.py](eval/tests/test_compare.py:60) — The verdict follows the bands, and a worse hard check blocks. · [test_profile_rules.py](eval/tests/test_profile_rules.py:82) — Rule counts and rule sites are measured and banded. · [test_model_pipeline.py](eval/tests/test_model_pipeline.py:90) — Scoring, comparing and judging run together on one map. | The bands come from stored settings. No test proves today's bands are the right width. | inferred |
| Judging a run and testing the doubters (Judge report, Eval run, Skeptic recall test) | yes | [test_judge.py](eval/tests/test_judge.py:328) — Marks and votes fold into one report with a stated verdict. · [test_run.py](eval/tests/test_run.py:108) — A scoring run produces its files and files them in the right place. · [test_mutate.py](eval/tests/test_mutate.py:30) — Planted false claims are produced and the catches are counted. | The judging inputs are hand-built. Nothing scores a run made by a real agent. | inferred |
| Finding relations a rebuild dropped (Lost arrows) | yes | [test_arrows.py](eval/tests/test_arrows.py:59) — Arrows the old map had and the new one lost are listed. | Loss is judged between two stored maps. Nothing checks the finding against the code itself. | inferred |
| Moving a map aside before a rebuild (Rebuild archive) | yes | [test_archive.py](eval/tests/test_archive.py:98) — The whole map moves and nothing is deleted. · [test_archive.py](eval/tests/test_archive.py:168) — A move that fails partway puts everything back. · [test_archive.py](eval/tests/test_archive.py:159) — A rehearsal run writes nothing at all. | Nothing tests two of these moves running at the same time on one project. | inferred |
| Reading a build's chat and scoring how it went (Transcript reader, Build cost, Process scorecard, Retro precheck, Ledger check, Live number ledger) | yes | [test_transcript.py](eval/tests/test_transcript.py:36) — A build's chat log is read in slices, with its commands and results. · [test_cost.py](eval/tests/test_cost.py:92) — Time and tokens for one build are counted and divided correctly. · [test_process_scorecard.py](eval/tests/test_process_scorecard.py:94) — Two hundred and fifty cases score how the build agent behaved. · [test_retro_precheck.py](eval/tests/test_retro_precheck.py:64) — A build that has not finished is reported instead of reviewed. · [test_ledger.py](eval/tests/test_ledger.py:53) — A review's finished rows are checked against the code history. · [test_live_numbers.py](eval/tests/test_live_numbers.py:36) — Numbers the tools state about a live map are re-measured. | One small stored chat stands in for a real build. Shapes only a long build produces are untried. | inferred |
| Every method-quality command surviving real inputs (Eval command line) | yes | [test_eval_cli_sweep.py](eval/tests/test_eval_cli_sweep.py:149) — A new command cannot ship without joining the sweep that runs it. · [test_eval_cli_sweep.py](eval/tests/test_eval_cli_sweep.py:161) — Every command runs against a real map and a real chat log. · [test_eval_cli_sweep.py](eval/tests/test_eval_cli_sweep.py:171) — The sweep leaves the stored inputs exactly as it found them. | The sweep only checks a command runs. What each command answers is checked elsewhere. | inferred |
| Instructions saying what a map must contain (Product description instructions, Code inventory instructions, Outside edge instructions, Data and step instructions, Operations and decision instructions) | partial | [test_method_contract.py](tests/test_method_contract.py:444) — The instructions stay consistent with the commands they tell an agent to run. · [test_prose.py](tests/test_prose.py:43) — Long sentences, code names and dashes in map text are counted. | The checks read structure and names. No test proves an agent following the instructions produces a good map. | inferred |
| Instructions saying how a build runs (Cross-cutting build instructions, Fan-out phase instructions, Verification phase instructions, Closing sequence instructions, Mode dispatch instructions, Change impact instructions) | partial | [test_method_contract.py](tests/test_method_contract.py:444) — Each phase names commands that exist and flags they accept. · [test_contract.py](tests/test_contract.py:42) — Each helper agent's brief is printed with the right ids and rules. | Only what the instructions say is checked. Whether a build actually follows them is measured by hand later. | inferred |
| Model spec, worker briefs and regression checks (Map model spec, Fan-out worker contracts, Method regression checks) | yes | [test_method_contract.py](tests/test_method_contract.py:444) — The written model spec agrees with the data shape the tools load. · [test_contract.py](tests/test_contract.py:42) — Every worker brief is complete and names only real ids. · [test_retro_checks.py](tests/test_retro_checks.py:33) — Each armed regression check is dated and can be settled. | The regression checks are read for shape only. Nothing runs them against a finished build. | inferred |
| Skill files that point an agent at the method (Build skill pointer, Map quality eval instructions, Build retrospective instructions) | partial | [test_skill_pointers.py](tests/test_skill_pointers.py:48) — Each skill names only its own entry document. · [test_skill_pointers.py](tests/test_skill_pointers.py:78) — Each skill tells the agent to read that document first. · [test_skill_pointers.py](tests/test_skill_pointers.py:86) — Each skill resolves its paths against the installed clone. | The wording is checked. Nothing proves an agent given one of these files reaches the method. | inferred |
| Public documents and the record of why (Public documentation, Contributor guide, Method rationale record) | partial | [test_method_rationale.py](tests/test_method_rationale.py:128) — Every reason entry parses and still points at a line that exists. · [test_method_rationale.py](tests/test_method_rationale.py:233) — The record names no private project. · [test_business_rules.py](tests/test_business_rules.py:1945) — The public readme lists things in the order the tools use. | Almost nothing checks the public readme or the contributor guide. Both can go stale without failing. | inferred |
| Coverage rows this table is made of (Test row, Test target, Test row view) | partial | [test_convert_and_views.py](tests/test_convert_and_views.py:208) — Coverage rows reach the browser with their targets resolved to names. · [test_lint_fragment.py](tests/test_lint_fragment.py:25) — A coverage row naming an invented id is refused. | Nothing checks that a coverage row's cited files exist. A stale citation ships quietly. | inferred |
| Drawing libraries fetched from the internet (jsDelivr, cdnjs, Mermaid, svg-pan-zoom) | partial | [test_viewer_js.py](tests/test_viewer_js.py:1377) — Panning and zooming a picture is measured after the picture is painted. | Four libraries load from two outside services. No test covers a machine with no internet, where the viewer goes blank. | inferred |
| Guarded places the map must not lose (Security surface, Grounding record) | yes | [test_access_surface.py](tests/test_access_surface.py:39) — A file that lost its only access decision is named. · [test_finalize.py](tests/test_finalize.py:424) — The closing verdict states the guarded places it found. · [test_finalize.py](tests/test_finalize.py:666) — An access decision nobody voted on is called out. | Loss is measured against a stored earlier map. A guard missing from both maps stays invisible. | inferred |

---

## Grounding — how much of this map was challenged

**728 of 728 claim(s) challenged** by fresh-context skeptics — 719 confirmed, 9 refuted, 0 unverifiable. That is the PINNED worklist: the claim surface the skeptics were handed.

> Of the claims THIS map carries, **708 of 719 have a verdict**. The other 11 were minted after the worklist was pinned, so no skeptic saw them.

Against the shipped map: **20 superseded** (pinned claims the reconcile rewrote or removed) and **11 added** since the worklist was pinned. `coyomap grounding report --map` lists which.

Twenty-five fresh-context skeptics challenged every claim in the pinned worklist, in two waves, with the behavioural theme turned on. This pass has 790 verdict rows over 728 distinct claims, 54 of them repeat rows from re-voting, and 25 distinct skeptic labels. Confirmed 719, refuted 9, unverifiable 0, tied 0. Ten cheap readers judged the map's 371 reader-facing sentences separately; 19 were flagged and 4 were rewritten, the rest being one reader's taste rather than a defect.

THE THREE-VOTER RECORD BROKE. The whole access theme got three independent voters. Across 27 multi-voted claims they disagreed on 2 verdicts and on 4 evidence anchors. Four earlier builds recorded no verdict disagreement at all, so that run of unanimity ends here, on the first build under the revised skeptic brief. The dissenter was right: it followed every call site of the version-name guard and ran it, and showed that no web address reaches the two lines the map cited, while the other two voters confirmed those lines without following the callers. This is the experiment the retro backlog parked as its open question 6, and the answer is that the vote does buy something.

ELEVEN REFUTATIONS WERE RAISED AND ALL ELEVEN WENT TO AN INDEPENDENT CLOSER, denied the map and denied this build's reasoning. It upheld ten and could not settle the eleventh, because that claim is a derived fact and its brief carried only the surface's own row, not the story steps behind it. I settled that one myself by reading the build file: installing the developer skills is a separate opt-in target whose own comment says it is never part of setting the tool up, so the install story wrongly stood the map owner at the developer surface. I removed those six steps. That is my read, not the closer's.

TWENTY CLAIMS WERE SUPERSEDED AND ELEVEN OF THEM HAD BEEN CONFIRMED — each a settled verdict this build overrode. Two are the access sites at the version-name guard, confirmed 2 to 1 and dropped anyway on the closer's uphold, with the line the closer showed does guard a web address added in their place. The other nine are sentences and steps I rewrote from advice the skeptics gave inside a confirming verdict, which is the outcome that otherwise disappears because the verdict itself reads clean.

WHAT WAS NOT RE-CHALLENGED: 11 claims were added since the pin, so no skeptic has read them. Each is a correction to a sentence or to an anchor, grounded in a line the closer or a skeptic read and quoted, and none of them adds a new relationship to the map.

ONE MEASUREMENT ON THE EVIDENCE ITSELF. The verdict lint reports 70 rows across 16 files where the file a skeptic cites appears in its own transcript only as printed text, never as a file it opened. That is not proof of anything, since a range read through a shell command looks identical, but it is the shape a fabricating pass would have, and it is recorded here rather than left unsaid.

Two confirmed claims had drifted anchors; both were corrected through the reconcile file, so the fix survives a rebuild.

---

## Bucket vocabulary

Source and history: The product reads a project's own files and past versions. No seed names that purpose, and folding it into the catch-all would hide the one outside thing every build depends on.
Code navigation: Two outside things exist only so a reader can open a mapped line somewhere else. That is a purpose, not a catch-all.
Source parsing: Reading names out of source in many languages. The library seeds name no parsing purpose at all.
Testing & type checking: The two gates a change must pass. No seed covers them, and calling them tooling would say nothing.
Build & packaging: Installing the product from its own repo. No seed covers packaging.

---

## Entry-point coverage

cli: complete — walked the whole command table in the dispatcher, and each command's own argument parser, for both command lines.
http-route: complete — walked every branch of the map server's request handler.
ui-route: complete — walked the tab buttons in the page shell and every drill address the page dispatches.
agent-tools: complete — the three installed skill files, one per slash command.
startup-hook: complete — the map server's own boot work.
poller: complete — the two repeat loops found by reading the server and the live-reload supervisor.
cli naming: Nine of the eleven stories arrive through a slash command or a screen, and the commands they run are steps inside those stories. Only the two a person types directly are named as a front door.
http-route naming: Every web address here is fetched by the viewer page after the reader has already arrived. The page is the door, and the stories name that.

---

## Coverage exceptions

conftest.py: The one loose file at the repo root wires the test run. This map deliberately leaves the test suites out of its boxes and answers them on the Tests screen instead.

---

## Map maintenance records — the build's own adjudication log

These sections answer this tool's own checks: each line records an element and why a finding about it was judged correct as it stands. They say nothing about the system being mapped.

### Balance exceptions

granularity: 79 boxes against a code-derived 26. Most of the gap is prose. This product keeps about 11,700 lines of its logic in instruction files, and the expectation counts code only. The rest is two single files. A 6,700-line checker and a 3,150-line instruction document were each cut into their named parts, rather than left as one box nobody can point inside.
runs-in/entry-hosts: The one unplaced thread is the live-reload watcher a contributor starts by hand. It is not a delivered process, so no deployment unit hosts it.
UC1: Installing is all crossings. Every action of it is declared in the build file, which no component owns, so there is no honest step of the product's own machinery in between.
SF2: The name was prescribed by the lead as a shared id that three other stories reference by name. Renaming it would break those references. It is one goal, the closing run of the gates.
UC2: Building a map is genuinely the longest story this product tells, and it already hands two runs of shared machinery to their own sub-flows. Compressing it further would hide the phases a reader most wants to see.
security-granularity: family — one rule per surface family, not one per address and condition. This product has no accounts and no roles, so its eight access rules are guards on what a build may open and what the local server hands back.

### Happy Path coverage

R3: The method author is the person who changes coyomap itself. Their work acts on maps that already exist, so it sits beside the product's story rather than inside it.
CAP5: Improving the method is the developer's own loop. A person mapping their project never runs it, so the happy path deliberately does not reach it.

### Interface exceptions

I8: The files read are the mapped project's own, which this product never wrote. The call site cannot show that, because it opens a path like any other.
I9: An address is built and handed over, and nothing comes back. No call site can show what crosses when only the person does.
I10: Same shape as the editor. A link is built and handed to the reader, so the crossing happens in their browser, not at our line.
I11: The chat files are written by the coding agent, not by this product. A read of a path cannot show whose file it is.
UC1/doors: Each door is anchored where the install acts, in the build file. The command line has no way in of its own for a build target, so no way in carries the line.

### Unclaimed surfaces

C50: Bundling a map with the conversation that made it is the developer's own upkeep. No story a person mapping their project would tell reaches it.
C51: The watcher restarts the map server when a contributor edits the viewer. It serves nobody outside the product, so no actor can claim it.

### Data owner exceptions

SD10, SD11, SD12, SD13, SD14: Every record in these areas is kept inside the map file, which has its own area. The build's story touches the map file itself, so the evidence sits one level up rather than on each record.

### Sweep debt

tools/coyomap/viewer/viewer.js:14928: The step hands a link to the reader. The decision behind it is which version of the code that link points at, and a rule already claims that.
skill/coyomap/SKILL.md:27: The step points the agent at one document. It carries no choice: the pointer is the same on every build.
eval/retro/method.md:62: This IS a decision, and no block covers it. The decision grouping has no area for reviewing a finished build, so the sweep is honestly in debt here.

### Audit exceptions

read-never-created HP4: The drawn boxes are built fresh from the map each time a screen opens. Nothing stores them, so no step can create them.

### Access baseline exceptions

method/dispatch.md: I read both lines. They tell a build not to reopen the map it is replacing, and not to pull a deleted one back out of version control. That protects the map's independence, not permission, so it is a decision this map keeps without calling it access control.


---

*Generated with coyomap from `project-map.json` — the committed source of truth. Do not edit this file; regenerate it with `coyomap render`.*
