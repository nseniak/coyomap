# <Project> — Codebase Analysis

> Built with the **coyomap** method. Behavioral layer first (Goal → Glossary → Roles →
> Use cases → Happy Path), then the structural machine (Components → Entry points /
> Model / Deps → Flows + Edges), joined at **use case ↔ flow**.
> Every row is drillable: name a row and it expands to a lower table or a `file:line`.
> **Schema v1** (ID-based): every element has a stable ID (`UC`/`C`/`D`/`E`/`HP`);
> cross-references use IDs; validated by `coyomap validate`.
> Confidence: **verified** (you read the code and traced it) vs **inferred** (taken from a name, a
> path or a convention). It records what the AUTHOR knew and nothing writes it. Whether the
> grounding skeptics confirmed a row is a different question, answered by
> `coyomap grounding by-element` from the votes and never stored here.
> **Commit:** `<sha>` · **Committed:** `<commit-date>` · **Built:** `<YYYY-MM-DD HH:MM>`

---

## T0 — Goal (the anchor)

<Two to four short paragraphs, a blank line between them, one to three sentences each, under
180 words in all: what the project is, what it does and for whom, and why anyone wants it.>

---

## Glossary — the ubiquitous language

| Term | Meaning | Defined / used in |
|---|---|---|
| **<Term>** | <meaning> | [file](path:1) |

---

## Roles (actors)

<!-- Primary actors only — the parties who INITIATE use cases. External systems the project calls
     out to (IdPs, sandboxes, upstream services, third-party APIs) go in T2, not here. -->

| Role | Kind | Audience | What they want | Use cases they drive |
|---|---|---|---|---|
| **<Role>** | human | user | <goal> | UC1 |

---

## Use cases

<!-- One use case = ONE actor goal (one trigger, one outcome; single-verb-phrase name). Drafted
     from the docs, then FRONT-DOOR-VERIFIED against the real entry surface (the registered
     routes / MCP tools / CLI commands — the T4 harvest), BOTH directions: a use case whose trigger
     has no entry point behind it is stale docs; an externally-triggered entry point no use case
     claims is a missing use case or a dead surface. `validate` backstops the second direction
     (advisory): an external T4 row whose component appears in no T6 flow warns until a use case
     claims it or the component is recorded as a deliberate ops/debug/infra surface under an
     "Unclaimed surfaces" extras heading (`Cn: <why>`, line-leading). -->

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|
| **UC1** | <use case> | <actor> | <trigger → outcome> |
| **UC2** | <use case> | <actor> | <trigger → outcome> |
| **UC3** | <use case> | <actor> | <trigger → outcome> |

---

## Happy Path — the spine (an ordered run through the use cases)

The happy-path ORDERING of use cases across all main functionality and every actor. Each step IS a
use case — its `*(UCn)*` tag is required; `HPn` is just its position in the happy path. The step carries no
STORY / mechanics / Touches: those live once in the use case's T6 flow below, and drilling a step
opens it. A step has no text of its own: its heading is its use case's name, repeated. An optional
`why:` line records the prerequisite that fixes this step's position. The
driving actor is the use case's own Actor (no separate `Actor:` line). Refer to actors by their
Roles-table names, never invented nicknames.
Coverage: the happy path hits all main functionality + all actors. What one linear happy path can't reach is
RECORDED, not forced in: each off-spine use case (`UCn: <why>`) and each role deliberately without
a spine position (`Rn: <why>`) gets a line-leading entry under a "Happy Path coverage" extras
heading — `validate` warns on the unrecorded ones.

**HP1 — <use case name>** *(UC1)*
**HP2 — <use case name>** *(UC2)*
why: needs the result of HP1
**HP3 — <use case name>** *(UC3)*

<!-- The use-case↔element traceability and the backward "Used in UC" view are DERIVED from the T6
     flows below (the flow steps name the elements) — not authored here. -->

---

## Subsystems (S) — the container altitude

<!-- Optional; recommended above ~15 components. Components grouped into subsystems, optionally
     NESTED — a subsystem's `Parent` is another `S` (S3/S4 below nest under S2). The viewer drills
     nested levels recursively, so a big area goes finer IN THIS MAP — never a second map file. Go
     deeper by nesting, or by promoting a leaf component into a subsystem (see method.md "Drilling
     deeper"). Membership is carried on each child (T1 `Subsystem` column / this `Parent` cell);
     members + inter-subsystem edges are derived. Omit this whole section on small maps — ungrouped
     are valid.
     To SUBDIVIDE one subsystem into several sub-parts (S2 → S3, S4 below), mint a NEW NUMERIC id for
     each part and set its `Parent` to the big one. NEVER an outline suffix like `S2a` / `S2b`: a
     letter-suffixed id is not a valid schema id (IDs are a prefix + digits only), so it matches
     nothing — its definition and every membership pointing at it are SILENTLY dropped, leaving an
     empty box. Numeric-id + `Parent` also lets you re-parent with a one-cell edit, no rename. -->

| ID | Subsystem | Purpose | Parent | Source | Conf. |
|---|---|---|---|---|---|
| **S1** | <subsystem> | <one-line purpose> |  | path/ | inferred |
| **S2** | <large subsystem, subdivided below> | <one-line purpose> |  | path2/ | inferred |
| **S3** | <sub-part of S2> | <one-line purpose> | S2 | path2/a/ | inferred |
| **S4** | <another sub-part of S2> | <one-line purpose> | S2 | path2/b/ | inferred |

---

## T1 — Components

| ID | Component | Subsystem | Purpose | Entry point | Depends on |
|---|---|---|---|---|---|
| **C1** | <component> | S1 | <purpose> | [file](path:1) | C2 |
| **C2** | <component> | S1 | <purpose> | [file](path:1) |  |
| **C3** | <component in S2's sub-part S3> | S3 | <purpose> | [file](path2/a:1) |  |
| **C4** | <component in S2's sub-part S4> | S4 | <purpose> | [file](path2/b:1) |  |

### T1 backbone — component dependency edges (the diagram source)

<!-- `Why` = why From needs To (a SUMMARY of the whole relationship, never one call's story — terse;
     carries what the verb omits). `Where` = a verified EXAMPLE call site: one `file:line` in FROM's
     code where it invokes To (the most representative if several), NOT To's definition. It is a
     witness grounding the edge (validation / drift / impact), not the interaction's location — the
     viewer never opens it; per-step `where` in T6 owns drill-to-code. -->

| From | Verb | To | Why | Where (example) |
|---|---|---|---|---|
| C1 | uses | C2 | <why C1 needs C2 — terse summary> | [file](path:1) |

---

## T2 — External dependencies

<!-- `Kind` (optional) is a CLOSED vocabulary that drives the Context view: external SYSTEMS the
     project talks to across a boundary — datastore / messaging / service / platform — are drawn at
     Context by name; in-process code — framework / library — folds into one collapsed "Libraries"
     box. `Type` stays the free-text human label. When `Kind` is omitted it is inferred from `Type`. -->

| ID | Name | Kind | Type | Used for | Where configured | Conf. |
|---|---|---|---|---|---|---|
| **D1** | <dep> | datastore | <type> | <used for> | <config> | verified |

---

## T3 — How to run / build / test

| Action | Command | Source |
|---|---|---|
| <action> | `<command>` | [file](path) |

---

## T4 — Entry points

<!-- Every way the system is entered, in TWO passes — do BOTH:
     (1) externally triggered — HTTP route, CLI, exported fn, callback, webhook (someone outside asks);
     (2) SELF-STARTING (activation=self, no user) — cron/scheduled job, while-True/interval loop,
         asyncio.create_task / background worker / thread, queue or stream consumer (.consume/.subscribe/
         poll), boot/startup hook (on_event('startup'), lifespan, atexit), OS signal handler.
     Do pass (2) EXPLICITLY: a long-running service with zero self-starting entry points is a red flag —
     assert why none exist rather than leaving the list front-doors-only. Set `activation` on each row
     (self|external — EXACTLY those words, `validate` blocks anything else); if you leave it blank the
     viewer infers it from `kind`, so use a kind label like "Background loop" / "Boot task" / "Signal"
     that reads as self-starting.
     This table is the front-door verification input: every EXTERNAL row must end up claimed by a use
     case (its component in some T6 flow) or recorded as a deliberate ops/debug/infra surface under an
     "Unclaimed surfaces" extras heading (`Cn: <why>`) — `validate` warns on the rest once flows exist. -->

| Kind | Trigger | Code entity | Component | Activation |
|---|---|---|---|---|
| <kind> | <trigger> | [entity](path:1) | C1 | self / external |

---

## T2b — Interfaces (the product's outside edge)

<!-- An INTERFACE is a surface through which the product SENDS data or events not consumed by the
     product itself, or RECEIVES data or events not generated by the product itself. Excluded: data
     the product produces only to read back (its own database, cache, queue); code and build
     artifacts that BECOME the product (packages, container images, CDN scripts); the pipeline that
     builds and tests it. An outside consumer THE MAP RECORDS beats the read-back exclusion (a store
     a person browses on their own IS a surface). Name the far side, never the pipe that reaches it:
     a log shipper and a reverse proxy are pipes; the log store and the dashboard are the surfaces.
     Mark the SERVICE, never the library that calls it.

     ONE row per SURFACE, never per address or per command. Split when the AUDIENCES differ — a
     customer dashboard and an admin console behind the same routes are two surfaces. An HTTP
     address that only serves the product's own front end belongs to that front end's surface.

     `Side` = whose DESIGN it is: if the far side vanished tomorrow, would its shape change?
     `Facing` = who it serves, user or operator. `Ways in` are `EPn` ids, assigned through
     `reconcile` (`ways_in`), never hand-written here: those ids are minted at assembly.

     `Kind` = what SHAPE the surface is, one word, authored with the row. Seeded-open, eleven seeds:
       ours   — screen · mobile-app · desktop-app · command-line · file · settings
       theirs — hosted-screen · content · handoff
       either — api · agent-tools
     SHAPE, NEVER PURPOSE: a payment processor and a crash reporter are both `api`, and the
     dependency's `Bucket` already says which is which. A kind answering "what is it FOR" means the
     row is mis-modelled. The side grouping is guidance, not a rule. Prefer a seed; mint only when
     none fits, and reuse the exact spelling on rebuild. The tiebreak for a surface that is both a
     place people act and a service we call: the kind names where the PEOPLE are, but only when the
     product's own flow takes them there — a sign-in redirect is `hosted-screen`, a code link we
     hand over is `handoff`, a crash reporter an operator opens on their own is `api`.

     There is no `Actors` column and no `actors` field: WHO is on the far side is DERIVED from the
     flows, gated on the kind. Never write it by hand.

     There is no `Far side` column either. The dependencies standing on a surface are derived from
     each dep's own list — do not name a `Dn` here. Anything you would have written in words about
     who is out there goes in `What it is`, the row's own sentence.
     `Source` is the ONE line declaring the whole surface (the router, the command table, the file
     writer) — optional; a settings surface is declared in no single place.

     Every T2 dep in the external group (datastore / messaging / service / platform) must either
     name one or more surfaces or say why it is none. Without the reason there is no way to tell a deliberate
     exclusion from nobody having looked. -->

| ID | Name | Side | Kind | Facing | What it is | Source | Conf. |
|---|---|---|---|---|---|---|---|
| **I1** | <surface, in product words> | ours | screen | user | <one sentence> | [file](path:1) | verified |

<!-- NO "what crosses" BLOCK. What crosses a surface is the flow steps drawn at it (T6), and each
     of those says which way it went — see `direction` under Use-case flows below. There is no
     per-surface direction to author, and a map that supplies one is rejected outright.

     EVERY INTERFACE OWES A USE CASE. Once this table exists, read down it and ask of each row which
     use case crosses it. A surface serving a PERSON or an OPERATOR that no story reaches is a
     missing story, not a missing field. Record `In: <why no story crosses it>` under an
     "Interface exceptions" extras heading only for a surface nobody ever reads. -->

---

## Subdomains (SD) — bounded contexts of the domain model

<!-- Optional; recommended above ~15 entities. T5 entities grouped into subdomains (bounded contexts /
     aggregates), optionally nested. Membership is carried on each card (a `SUBDOMAIN:` line); members,
     the inter-subdomain (SD→SD) arrows, and the subsystem→subdomain (S→SD) bridge are all DERIVED. Omit
     this whole section on small models — ungrouped entities are valid. Cluster entities the same way
     components cluster into Subsystems: directory (the card's SOURCE) first, then relation cohesion. -->

| ID | Subdomain | Purpose | Parent | Source | Conf. |
|---|---|---|---|---|---|
| **SD1** | <subdomain> | <one-line purpose> |  | path/ | inferred |
| **SD2** | <nested subdomain> | <one-line purpose> | SD1 | path/sub/ | inferred |

---

## T5 — Domain model (domain cards)

<!-- Each entity is a CARD (a block), not a table row — same micro-format as the Happy Path. The
     heading defines the E id; FIELDS = attributes, RELATIONS = typed E→E edges (authored on the
     source side only, never in the backbone edge list). Renders as a Mermaid classDiagram.
     An optional `SUBDOMAIN:` line assigns the entity to one subdomain (SD) — the domain-model analog of
     a component's `Subsystem` cell. Full spec: method/domain-cards.md. Separators are `·`, never raw `|`.
     Cardinality is always a PAIR `sc→dc` (both sides or neither) — each side `1` / `*` / `0..1` / `1..*`;
     the `has 1→0..1 E3` item below shows an optional side. A lone token (`contains 0..1 E2`) is invalid. -->

**E1 — <Entity>** *(<stored where>)*
SUBDOMAIN: SD1
MEANING: <one-line meaning>
FIELDS: <name>:<type> PK · <name>:<type> · <name>:<type>
RELATIONS: contains 1→* E2 <display> · has 1→0..1 E3 <display>
SOURCE: [file](path:1)

**E2 — <Entity>** *(<stored where>)*
SUBDOMAIN: SD1
MEANING: <one-line meaning>
FIELDS: <name>:<type> · <name>:<type>
SOURCE: [file](path:1)

**E3 — <Entity>** *(<stored where>)*
SUBDOMAIN: SD2
MEANING: <one-line meaning, lives in the nested subdomain SD2>
FIELDS: <name>:<type>
SOURCE: [file](path/sub:1)

---

## T6 — Use-case flows

<!-- The INSIDE view of each use case (its outside view is the use case's trigger and outcome). ONE BLOCK PER USE CASE:
     a `**UCn — title**` heading + numbered step lines. A step is `from → to`, where each endpoint is
     an element ID (C/D/E) or a Role name. EVERY step carries a short authored phrase after `: ` —
     never lean on the backbone edge's label (one pair appears in several steps meaning different
     things). Each element↔element step also carries ITS OWN call site after ` @ ` — the `path:line`
     of the operative statement in the step's `from` code (THE location; you just read it to write
     the phrase). Steps with genuinely no single site set `no_call_site` instead; actor steps
     (`<Role> → C…`) need no anchor. Add flow-specific context after `· `. Renders as a Mermaid
     flowchart + a numbered narrative, and is the drill-down of the matching Happy Path step.
     Separators inside a line are `·`, never raw `|`.
     A step may go BACKWARD too: a `to` that is an earlier participant renders right-to-left. Record
     the meaningful returns — the response the actor sees, an error/fallback, a callback/event — as
     authored steps (step 5 below). Don't echo every call with a return.
     DIRECTION (required where your code meets a surface or a record): every step whose one end is
     an `In` or an `En` and whose other end is your own code says which way the data moved, read
     from THE PRODUCT: `in` it arrives, `out` it leaves, `both` one exchange runs each way. At a
     record `in` is a read and `out` a write. A PULL is `in` even though the arrow points outward
     (`C32 → I8 : fetches the markup` — the data comes back); never read it off the arrow. EMPTY on
     every other step, a DOOR included (`R1 → I3` is a human action with no product end), and
     `validate` blocks a door that carries one.
     EVERY SAVED RECORD OWES A USE CASE, the same way every interface does. A record this codebase
     KEEPS (a row of its own, or one carried inside a parent's row) that no flow step reaches leaves
     the map unable to say what it is for. A record INSIDE another one counts as reached when its
     holder is, so an embedded piece needs no step of its own. A read shape, a request object or a
     set of constants is not a saved record and owes nothing. `validate` reports the unstoried ones;
     the escape is `<En>: <why>` under a "Balance exceptions" extras heading.
     ENTITY STEPS (required): author each flow's 1-2 CENTRAL entity touches as C→E steps — the
     read/write that IS the scenario's outcome or decision (SF1 step 1 below is the shape:
     `C2 → E1 : upserts the <Entity> row @ repo.py:88`). The entity "Used in UC" view and diff
     impact derive from steps only; `validate` warns when no flow touches any entity. Every
     entity step rides an existing C→E backbone edge (validate warns otherwise). Fine-grain
     config reads stay edges — don't tag every entity a component ever touches. -->

**UC1 — <flow title>**
1. <Role> → C1 : <what the actor does>
2. C1 → C2 : <what this call does> @ path/to/caller.py:42
3. C2 → E1 ⟨runs SF1 — <shared sequence name>⟩
4. C1 → <Role> : <the response the actor sees — a backward step, drawn right-to-left>

<!-- SUB-FLOWS (T6b): machinery shared by ≥2 flows is defined ONCE and referenced (step 3 above and
     step 2 below both run SF1). A reference step names the sub-flow (`⟨runs SFn — name⟩`); its
     endpoints are the run's entry/exit; it carries NO @ anchor of its own (the sub-flow's steps
     carry theirs). One level only — a sub-flow never references a sub-flow. The step band is
     3–15 AUTHORED steps per flow (a reference counts as 1); a justified long flow records its UC id
     under a "Balance exceptions" extras heading. -->

**UC2 — <another flow that shares machinery with UC1>**
1. <Role> → C1 : <what the actor does>
2. C2 → E1 ⟨runs SF1 — <shared sequence name>⟩

**SF1 — <shared sequence name>**
1. C2 → E1 : <what is read/written> @ path/to/repo.py:88 · <optional note>
2. C2 → D1 : <what is sent> @ path/to/client.py:17

---

## T7 — Business logic (the decisions this product makes)

<!-- ONE DECISION PER RULE, in product language, naming no component. The sharp test is "could a
     product person have decided otherwise?" — "own connection first, else oldest shared" passes;
     "if the list is empty, return early" does not. Two claims joined by "and" are two rules.

     EVERYTHING UNDER A RULE IS DERIVED. The component on each site line, the use-case steps, the
     entities and whether the rule has been swept are all computed from the site anchors — there is
     no field to write for any of them, on purpose: an authored "I searched the whole repo" is
     unfalsifiable. A site anchors the OPERATIVE line (the one that acts), never a definition
     header, and never a line chosen because it happens to light up a use-case step.

     In the JSON source a rule is { "id": "BRn", "name", "statement", "block": "BLKn", "access": bool,
     "sites": [ { "where": "path:line", "why", "no_call_site": bool } ] }; `block` is assigned by
     the LEAD after the rule fan-out, via `coyomap reconcile` — never in a fragment (a `BLK` id is
     minted at synthesis, before the rules exist, so a re-synthesis that renumbers blocks must not
     silently re-point every rule). Blocks are `blocks[]`, a Group forest. -->

One decision per rule, with every place it is enforced. The component on each site line and the
use-case steps under it are DERIVED from the site anchors — no field carries them.

### <Block name> *(BLK1)*

<what this area of the product decides>

**BR1 — <the short title>** — <the decision, in product language>  *(access)*  *(verified)*
- [path/to/file.py:88](path/to/file.py:88) — <Component name> (C4) · <what this line does for the rule>
- [path/to/other.py:12](path/to/other.py:12) — <Component name> (C7), <Other name> (C9) · <enforced again>
- enforced at: <Use case name> (UC2) step 4 · <Use case name> (UC5) → SF3 step 2

**BR2 — <the short title>** — <a decision the code enforces by construction>
- *no call site* — enforced by construction · <the type / schema constraint / config-wired guard>

<!-- The site line's component list, the `enforced at:` line and the sweep state are all RENDERED
     FROM the anchors, so the shapes above are outputs, not things to write:
       · a file several components claim lists EVERY one of them, never the first;
       · a site in a file no component claims renders `*unverified — no component claims this file*`;
       · `(access)` marks a rule that governs who may do what; `(verified|inferred)` is `confidence`;
       · `→ SFn step k` means the step was authored in a sub-flow — `n` is unique per container,
         so the container is half a step's address. -->

---

## Operational dimensions — the standard core four

### Deployment & topology

| Unit | Runs on | Exposed as | Config source |
|---|---|---|---|
| <unit> | <host/runtime> | <port/route> | [file](path) |

### Observability

| Signal | Where emitted | Where viewed | Alerts |
|---|---|---|---|
| <signal> | [file](path:1) | <dashboard/log> | <alert or —> |

### Security & auth

<!-- Trust boundaries are often inferred — flag them. -->

| Surface | Who can reach | Auth check | Risk note |
|---|---|---|---|
| <surface> | <caller> | [check](path:1) | <risk> |

### Config & environments

<!-- Secrets: name where they live, never the value. -->

| Key | Purpose | Default | Per-env / secret? |
|---|---|---|---|
| <KEY> | <purpose> | <default> | <env / secret> |

---

## Relationships — backbone edge list

| From | Verb | To | Why | Where |
|---|---|---|---|---|
| <source> | <verb> | <target> | <why source needs target — terse> | [file](path:1) |

---

## Test completeness — gaps against the map

> **Tests run for this table?** <yes, with coverage — rows verified / no, read-only — all rows inferred>

<!-- Measure against the MAP, not line %. Walk the inventory (use cases / T4 entry
     points / failure modes / invariants / state transitions / critical branches) and ask "is
     there a test that exercises it?". Lead with untested critical paths (money / auth / data-loss
     / irreversible). Run the suite with a coverage tool (running beats reading); confidence
     ladder: reading tests = inferred, running with coverage = verified, surviving mutation =
     strongest. Output the risk-ranked gap table, NOT a single percentage. -->

| Target | Tested? | Test(s) | Gap / risk | Confidence |
|---|---|---|---|---|
| <label> (<Element name>) | yes / partial / no | [dir/](backend/tests/unit/) — <what it covers> | <gap or risk> | inferred / verified |

<!-- In the JSON source a row is { "targets": ["UC1","C4"], "label", "tested", "tests": [ {file, why} ], "gap", "confidence" }:
     `targets` names element IDs explicitly (the viewer resolves them to names + locate-links, no prose parsing);
     each `tests[].file` is a bare anchor (a `path:line` or a `path/` test dir), rendered as a clickable code link. -->


---

*Generated with coyomap. This file documents the GENERATED markdown view's shape — the committed source is `.coyomap/project-map.json` (see method/model.md); do not fill this template by hand.*
