# The coyomap method

How an AI coding agent builds and maintains a top-down, drillable map of a codebase.
Deliver this fixed set of sections, rendered as tables in the generated view. Every row is
drillable: name a row and it expands to a lower table or jumps to code with clickable
`file:line` links.

Two linked families:
- **Behavioral** (why/who/what): Goal → Glossary → Roles → Use cases (grouped into Capabilities) → Happy Path.
- **Structural** (the machine): Components → Entry points / Model / Deps → Flows + Edges.

They join at **use case ↔ flow**.

See also: [dispatch](method/dispatch.md) · [the map model](method/model.md) · [domain cards](method/domain-cards.md) · [change-impact](method/change-impact.md) · [diagrams](method/diagrams.md).

**The stored map is a structured JSON model** (`.coyomap/project-map.json`, [the map model](method/model.md));
the markdown map and the HTML diagram are **generated views** committed next to it. Build agents
return structured rows; `coyomap assemble` writes the model — nobody hand-authors the stored file.

The method is `method.md` and the `method/` docs (plus the `tools/coyomap/` package). The coyomap repo's
**`internal/`** folder (design rationale, working notes) is **not** part of the method — ignore it
when reading the clone; never treat it as instructions to follow or as input to a map.

---

## Behavioral layer — lead with this (what & why, before any code)

- **T0 Goal** — two to four short paragraphs, a blank line between them, one to three
  sentences each, under 180 words in all; whichever cap comes first ends the text, and the
  caps are ceilings, not targets. Together, in any order, the paragraphs cover what the
  project is, what it does and for whom, and why anyone wants it: a tool says the problem it
  solves, a game says the fun, a library says what it saves its user. It DESCRIBES, it does
  not sell: the need or the pain point is welcome, said plainly in the words of the person who
  has it (the README and docs are its usual source; where they are silent, infer it, as the
  confidence-by-layer rule below allows), but no claim about the product's qualities or
  outcomes that the code and the docs cannot back, no superlative, no "seamless", "powerful",
  "simply". Free form inside those limits: no table, no headings, no fixed order of parts
  (the first example below opens with a problem, the second with the game itself). Third
  person, naming the people by role, because the reader of the map is not always the user;
  where the docs only say *you*, name the role the product implies. When the repository's
  name and the product's name differ, use the one its users see. The
  [writing rules](method/templates/writing-rules.md) apply to every sentence (20 words at
  most, no em dash, and two clauses joined by "and" are two sentences); the product's own
  name is a product word even when it is also a command, and so is a public address it lives
  at. `validate` counts the shape, a short list of pitch words and any second-person word.
  The goal is the map's anchor: every later section is read against it. Two examples, a tool
  and a game:

  > A team that uses AI assistants ends up with many tool servers. Each person wires every
  > server into every client by hand. Nobody records what was called.
  >
  > MCP Hero puts a team's tool servers behind one address. An admin mounts each server once.
  > Roles written by the admin say which tools each person may use.
  >
  > A teammate points one AI client at that address, signs in, and sees only the tools their
  > role allows. Every call is recorded. MCP Hero runs self-hosted for one team, or as the
  > hosted service at mcphero.io for many.

  > Ricochet is a two-player puzzle game played in a browser. Each player fires one ball a
  > turn. The walls bend its path.
  >
  > A round lasts three minutes. The player who lights more tiles when the clock stops wins.
  > A rematch starts with one click.
  >
  > Ricochet is built for two people at one keyboard. The game needs no account and no install.

- **Glossary** (default deliverable): `Term | Meaning | Defined/used in`. The ubiquitous
  language, produced up front and used to name things consistently across all tables
  (prevents the name-drift parallel mode otherwise risks).

  The viewer turns every glossary term it finds in the map's prose into an in-place
  definition, so a reader meets the meaning where the word is used. Plural, possessive,
  case and hyphen-vs-space variants are matched automatically. Two optional fields tune
  this per term:
  - **`aliases`** — real alternative names of the concept that this project's prose also
    uses, so they get linked too (e.g. `"upstream"` for the term "Upstream MCP" — only if
    in this project's prose "upstream" always means that). The rule: an alias must be
    unambiguous IN THIS PROJECT'S PROSE. Never add an alias that is an ordinary English
    word with other meanings in the map's own text — "tool", "value", "file", "variable",
    "link" alone are the canonical bad examples; they would link every unrelated use and
    turn prose into noise. Prefer multiword aliases. Never add a plural, possessive or
    case variant as an alias — the viewer folds those on its own. When in doubt, omit
    the alias.
  - **`no_autolink: true`** — the term's own name is excluded from automatic linking (it
    links only via its aliases, or not at all). For a term whose name is a generic word:
    a glossary term "Tool" would otherwise link every sentence that says "tool", so it
    sets `no_autolink` and links nothing, or links only via a specific alias like
    "catalog tool".
- **Roles (actors)**: `Role | Kind | Audience | What they want | Use cases they drive`. Each role is a first-class
  element with an **id `Rn`** — use cases and flows reference actors BY THAT ID, never by name. List ONLY the
  **primary actors** — the parties who *initiate* a use case and drive the system. Do **not** list
  external systems the project itself calls out to (IdPs, sandboxes, upstream services, third-party
  APIs): they are not actors here. They belong in **T2 external dependencies** + the edge list, and
  the context diagram draws them as *outbound* arrows (the system uses them), never inbound.
  **THE PEOPLE WHO RUN THE PRODUCT ARE ACTORS TOO, and they get use cases.** An operator has goals —
  keeping the service healthy, diagnosing a fault, unsticking a customer — and those goals cross real
  surfaces: a log store they search, a crash service they read, an operator console, an operational
  command. Both live maps already carry the person ("Service operator", "Superadmin") and both state
  a want that covers work no use case was ever written for. Look for them deliberately; do not stop
  at the people who BUY the product.
  **THE PEOPLE WHO WRITE THE CODE ARE NOT.** Running the test suite, type-checking, building,
  regenerating an icon, preparing a release, starting the product on a laptop: none of these is a use
  case. This is the same line the interface rule already draws, where the pipeline that builds and
  tests the product is not an interface.
  **TWO TESTS, and a candidate must pass BOTH.**
      1. **It crosses an interface of its own.** Key rotation with its own settings surface earns a
         use case; key rotation buried in a general command line does not earn a separate one. This
         caps how many operator use cases exist by the number of operator-facing SURFACES, not by
         the number of commands.
      2. **It acts on the RUNNING SERVICE that customers use.** Not on the build, the tests, the
         docs or a release.
  Test 1 alone is not enough, and one live surface proves it: mcpolis's command line is ONE interface
  with 36 ways in, 17 of them labelled "Operator" — and 5 of those 17 are exporting code, re-taking
  screenshots, running the suites before a release and publishing images. The label lies about half
  the time; test 2 is what sorts it. Under both, that command line yields about two use cases
  (keeping the backend running, upgrading stored data on the live service), not seventeen.
  **Kind**
  (required, every role states one) = `human`, `service` or `ai-agent`. A `service` actor is an
  **autonomous external initiator with its own goal** — a scheduled job (time as the actor), a
  worker/poller that reaches out on its own, or an external system that calls IN (an inbound webhook
  sender, an API client). It is NOT a system the project depends on (that is a T2 dep, drawn
  outbound).
  **`ai-agent` is a program driven by a language model that acts on its OWN, with nobody watching** —
  an unattended agent holding a service token, a scheduled agent. It exists because `service` was
  covering two things that behave differently: a customer's autonomous agent and the product's own
  cron job wore the same pill.
  **AN ATTENDED AI AGENT IS A PIPE, NOT AN ACTOR. The actor is the PERSON.** When somebody asks their
  assistant to do a thing, the goal is the person's; the assistant carries it, exactly as a browser
  carries a click. Name the person, and let the assistant appear in the steps. The fact that they
  arrive through an AI protocol is already carried by the interface's `kind` (`mcp`, `agent-tools`),
  which is what that field is for.
  This is not a preference: it is the same rule as *name the far side, never the pipe*, and the same
  rule the human-plus-service advisory already applies to a use case's actor list. A map got it
  wrong — argus authored 15 use cases at its MCP interface with the assistant as the actor and the
  page owner nowhere, while the same person's dashboard use cases named the page owner. One map, two
  answers, for one person doing one thing.
  **AN `ai-agent` IS ALWAYS OUTSIDE THE PRODUCT.** Only `service` with an `internal` audience
  means the product's own scheduled work — a timer, a boot hook — which owes no doors and stands on
  no surface. A customer's assistant is never that, so it keeps its doors. This is the whole reason
  it is a third word rather than a flavour of `service`.
  **Audience** (required, every role states one) = `user` or `internal` — see the Audience rule under
  Capabilities. It is the map's only authored answer to "who is this for", and every capability's
  audience derives from it, so a role left untagged makes its capabilities unanswerable.
  **Crucially, a `service` actor is NOT internal machinery that merely receives or relays a human's
  (or another party's) action inward** — a gateway, a shard / gateway connection, an event
  dispatcher / router, a message consumer that just forwards. That machinery is a **component in the
  flow**, never an actor: the party who *acted* (the member who chatted, the admin who clicked) is the
  actor, and "the event arrives via the shard" is a flow STEP. "It drives event handling" does not
  make something an actor — an actor has the GOAL, not the delivery job. When the docs don't say,
  infer from naming and mark it inferred.
  - **Role relations** (`relations`, optional): when one human typically holds several of the map's
    roles, record the link. Roles are permission hats the code recognizes; without a relation the
    viewer draws one person as several strangers (real case: the prospect who signs in IS the
    future admin). Two kinds: `{ "kind": "becomes", "role": "Rn", "at": "UCn" }` — this role turns
    into another at a specific use case, and the transition MUST be a real, mapped action (the
    prospect becomes the admin at "sign in and name the organization"); and
    `{ "kind": "includes", "role": "Rn" }` — this role may do everything the named role may do (the
    admin includes the member). Record `includes` in ONE direction only (the wider hat names the
    narrower one), and never invent a `becomes` the code gives no transition for: no transition use
    case, no relation. `validate` checks that `role` and `at` resolve to defined ids and that a
    `becomes` names its `at` — nothing more; whether the `at` use case lists both roles is your
    judgement, not a rule.
- **Use cases**: `Use case | Actor | Trigger | Outcome`, where **Actor is the party the use case is
  FOR** — the one whose goal it fulfills (`actors: ["Rn", …]`). Rank by importance — the headline
  features and intended workflows in the project's docs are usually the primary use cases (see
  *Read the project's own docs* under Cross-cutting rules). **A TOOL IS NOT A
  GOAL: never mint one use case per tool address.** Write what the PERSON wants; the tools they pass
  through are steps. This is the failure that follows from naming the tool caller as the actor, and
  it is measurable: argus put 15 use cases on 21 MCP tool addresses, roughly one each, and they read
  like the tool list they are — "Store page text an assistant supplies", "Plan the next summary",
  "Check what the account is allowed, through the assistant". Nobody WANTS to plan the next summary;
  it is machinery run while doing something a person asked for. That product's real goals are four
  or five: track a page, see what changed, browse the history, retune it, stop.
  The tell is a trigger with no subject: "Names a page and its address" is a parameter list, and
  "a page owner asks their assistant to watch a page" is a trigger.
  **Prefer exactly ONE actor per use case.**
  List more than one id ONLY when they are *interchangeable initiators of the same goal* (an admin OR
  a moderator can run the same action) — which means **ONE opening**: the flow starts at the same
  step whichever of them ran it, so only one of them ever appears as a step `src`.
  **One goal reached through DIFFERENT front doors is TWO use cases** — whether that is two parties
  or ONE party arriving two ways. An owner on a screen and that same owner through their assistant on
  an MCP tool are not one use case: they enter at different steps, and one flow cannot tell two
  openings on one number line without lying about the order. (This said "two parties" and gave the
  assistant as the second one, which contradicts the pipe rule above: the assistant is not a party.
  The doors differ; the person is the same.)
  **A SCREEN AND THE ADDRESS THAT SCREEN CALLS ARE ONE DOOR, NOT TWO.** A person arrives at the
  screen; the address is what their action fires once they are already inside. Name both on the same
  use case — the screen is where they stand, the address is what happens — and split only when there
  are two places a person can ARRIVE from, such as a screen and an assistant's tool.
  **Why this clause exists.** The sentence above was widened from "two parties" to "one party
  arriving two ways", and the next build read an admin's screen plus the address behind it as one
  party arriving twice. It did not split them: it kept the screen and dropped the address, and said
  so — "I gave one use case two front doors on two different surfaces, so I'll drop it." Measured
  across those two builds, naming collapsed in exactly the two action-level kinds and nowhere else:
  backend addresses named by a use case went 38 of 114 to **2 of 118**, assistant tools 6 of 43 to
  **1 of 43**, while screens held at 20 of 39 and 21 of 36. A rule meant to produce MORE use cases
  produced fewer (50 to 43) and cost the map 40 of its named front doors.
  Split them into one use case per door, name the door in each use case's name ("… in the dashboard"
  / "… through the tool"), give each its own `entry_points`, and factor the shared middle into a
  **sub-flow** both flows reference — the machinery is written once, and each flow stays one honest
  run that ends by handing the outcome back to ITS actor. `validate` BLOCKS a use case whose own flow
  is driven by two of its actors. **Never pair a human with the machinery that serves them** —
  a member chatting is one actor (the member); the shard that delivers the message, the worker that
  reacts, the dispatcher that routes it are flow components, not co-actors. A human + a `service`
  role on the same use case is the classic tell that the service is really the delivery mechanism.
  - **One use case = ONE actor goal: one trigger, one outcome.** The test: after it runs, the actor
    can say "I did X" with a single X. The **name is a single verb phrase** — a name joining two
    verbs with "and" ("Sign in **and** create an organization") is the split signal (`validate`
    warns, advisory): if the halves have their own triggers and outcomes, they are two use cases;
    the Happy Path expresses their ordering. A fused use case also bloats its T6 flow past the
    step band (below), and its name is what every Happy Path step realizing it is labelled with.
  - **Front-door verification — cross-check the list against the REAL entry surface.** The
    behavioral draft comes from README/design docs, and docs lie in both directions: a use case
    authored for a capability that no longer exists (stale docs), and a real user-facing surface no
    use case mentions (both happened on live maps). So before finalizing the use-case list, the lead
    enumerates the **registered** routes / MCP tools / CLI commands / callbacks (grep the
    registrations; in parallel mode the T4 harvest IS this enumeration — do the cross-check right
    after synthesis, when T4 first exists) and checks **both directions**: (1) a use case whose
    trigger has **no entry point behind it** → drop it or mark it stale-docs; (2) an
    **externally-triggered entry point no use case claims** → a missing use case or a dead surface —
    add the use case, or adjudicate it as ops/debug/infra. **Claiming has TWO arms, because one
    cannot carry it.** A use case relates to the entry surface in two different ways: its
    **trigger** is the front door an actor hits to start it (authored as `entry_points` on the use
    case, via the synthesis `reconcile` — see *Build order*), while its **traversal** is every
    surface the scenario merely passes through (derived from the flow's component reach). The
    derived arm stays PRIMARY and the authored one refines it. Making the authored link the only
    test inverts on real maps: on coyomap's own map ~16 of 61 entry points are not triggers of
    anything a person does (fetches the browser makes *after* the reader clicked, plus middleware)
    and every one would report as a missing use case; on a map whose harvest recorded route *groups*
    — one row for a whole SPA — a dozen use cases would have to name zero surfaces, which rule (1)
    reads as "stale docs, drop it". So **a use case naming no surface is legitimate**, never a
    finding — **PER use case, never wholesale**: a map where NO use case names ANY surface has
    skipped the authored arm entirely, and rule (2) then cannot fire per-surface (real case: a
    rebuild shipped 0 trigger links across 319 entry points, and six behaviours silently lost
    their use case — a sandbox-file upload route and an hourly health-check job among them, both
    still live in the code). `validate` warns on that degenerate case; the rare map where it is a
    real decision records `trigger-arm: <why>` under the **"Entry-point coverage"** extras
    heading. And for EVERY way in of a surface we define — routes, screens, MCP tools, commands,
    agent tools: every kind but `middleware`, which is a pipe nobody arrives through — walk the
    harvested list per surface at synthesis: each one is named by some use case's `entry_points`,
    recorded as unclaimed, or becomes the use case it is evidence for — blanket per-kind prose is
    a harvest-coverage statement, not an adjudication. The list used to be three kinds
    (`http-route`, `ui-route`, `mcp-tool`), so a product whose whole front door is a command line
    walked nothing: coyomap's own map came out with 11 use cases for 97 ways in, 51 of them
    commands, and no check said so.
    Entry-point granularity is *reported*, not regulated. The mechanical backstop:
    `validate` warns (advisory) on every T4 entry point neither arm reaches; a deliberate
    ops/debug/infra surface is recorded as `Cn: <why>` under an **"Unclaimed surfaces"** extras
    heading, which silences that component durably. On a large repo the wall can be dozens of
    surfaces — `coyomap validate --emit-unclaimed` prints a ready-to-paste block of every current
    one (each as `Cn (name): <why>` with its triggers) so you adjudicate them in one pass instead of
    hand-typing the list (a fresh monorepo build left ~125 of these unaddressed because recording
    them by hand was too costly). **The walk itself is checked once per surface.** The
    per-component advisory cannot see a skipped walk: one flow through a component marks every way
    in it owns as covered, and on a live map that was 87 of 97 with the check reading 2 unclaimed.
    So `validate` also warns ONCE PER SURFACE, listing its **storyless** ways in — named by no use
    case and run by no flow step (a step anchored at the way in's own `source` line, which a
    surface step carries by the rule under *Doors*). Adjudicate each: it becomes the use case it is
    evidence for, or `EPn: <why>` under the same **"Unclaimed surfaces"** heading (a whole surface:
    `In: <why>`; a component line still covers its ways in); `--emit-unclaimed` prints them per
    surface, ready to paste. A `middleware` row is never listed, nor a way in recorded under
    "Interface exceptions". Measured the day the check landed: 13 / 67 / 64 storyless ways in on
    the three live maps, of which the per-component advisory had reported 0 / 13 / 2.
    **What a record is for, and what a use case is for.** A record is for a dead surface, a
    dev-only or test-only surface, or a fetch with no goal of its own (a picker filling itself, a
    feature-flag read every page makes). A check somebody runs ON PURPOSE — a smoke-test page an
    operator opens, a command that verifies something — is a goal and gets a use case; a handshake
    a story passes through (a sign-in discovery route, a registration address) belongs to THAT
    story's use case, named there, never recorded. A read-only way in is named by the use case
    whose goal it serves (the list a person reads before changing something is part of the change),
    unless the read answers a question of its own — an admin asking how the team's servers are
    doing, an operator looking over every organization — which is its own use case, exactly as its
    dashboard twin already is. An older record saying a COMPONENT is "not a goal" decides nothing
    about a way in: each way in is adjudicated on its own. Measured on the first partial run of
    this walk: 44 of 48 ways in landed as expected, and the four that did not were a smoke-test
    page and a three-route sign-in handshake, both recorded because a component record already
    said "not a goal". **Self-activated entry points (crons, workers, consumers, startup
    hooks) are NOT exempt.** A scheduled job is an actor with a goal by the Roles rule above, so
    exempting them would hide a whole background capability with no signal at all. They are claimed
    like anything else. Be honest about the other half, though: a cron or a boot hook often has **no
    actor to claim it**, and then the answer is the recorded line, not an invented use case. The
    point is that it becomes a decision instead of a silence. A use case with **no T6 flow at all**
    also warns once tracing has begun — the phantom-capability signal.

### Capabilities — the grouping over use cases

Components group into **product areas** (subsystems) and entities into **subdomains**. Use cases
group into **capabilities** — the same shape, a third forest. Without them the use-case list is the
one content family with no structure at all, and no screen answers *"what does this product do?"*.

- **A capability is a group of use cases that serve one goal of the product** — `Organizations &
  teams`, `Upstream MCPs`, `Tool access via gateway`. Aim for the same 5±2 the diagrams use: five
  boxes is a product description, twenty is a list.
- **Each capability carries a `happy_path`: `expected` | `excluded`.** Must the happy path reach at least
  one of its use cases? `expected` = yes. `excluded` = no, and one record says why. This is what
  turns Happy-Path membership into a rule (see the Coverage rule below) instead of a written
  justification per off-spine use case.
- **A capability the happy path never reaches states its `story` anchor:**
  `{ "place": "before"|"after", "feature": "CAPn" }` — the feature this one reads beside. WHY: the
  viewer draws ONE story column, the happy path unbroken and the off-happy-path features in a block after it,
  and a feature with no flow step has no derived position in it. So `after` ORDERS that trailing
  block — the block already sits after every happy-path feature — while `before` is the one placement
  that keeps a feature among the happy path, because the end of the column is not before anything. Author
  `before` on a lead-in (a marketing / onboarding feature belongs BEFORE the first step); author
  `after` on a trailing or variant feature, so it follows the work it extends instead of landing
  last. Without an anchor the viewer guesses from the feature's actors' last flow step, which
  orders the block sensibly for trailing features and never rescues a lead-in. Anchor to the
  feature it genuinely reads beside in the product's story; never invent an anchor for a feature
  the happy path already reaches (its position is derived), and never author anchors that form a cycle
  (A after B, B after A) — a cycle cannot resolve, and the viewer then drops one member's anchor.
  `validate` blocks the field on the other forests, checks `place` is exactly `before`/`after`,
  and that `feature` names a defined capability other than this one — nothing more.
- **Each capability carries a `stakes[]` line per driving actor.** For every actor that drives at
  least one of the capability's use cases, write one stake: a short verb phrase with the actor as
  the implied subject ("mounts, configures and runs the servers"), saying what THAT actor comes to
  this feature to do. It must read correctly after the actor's name, and the writing rules apply —
  one idea, plain words, no code, no step numbers. WHY: the viewer draws actor→feature arrows and
  labels each with the actor's stake; a feature description alone is written from one chair and
  hides the other roles (real case: "Upstream MCPs" reads admin-only, while the member signs into
  upstreams there). `validate` blocks a stake whose actor is not a defined role, and advises when a
  derived driving actor has no stake; a capability whose fallback labels are genuinely right is
  recordable as `CAPn: <why>` under a **"Stake exceptions"** extras heading.
- **It says NOTHING about who the capability is for.** That is a second, independent question, and
  it is answered once on the ROLE (`audience`, below) and derived up. A capability may be internal work
  that the happy path shows on purpose — the story has to meet the operator and the upkeep job somewhere —
  and it needs no per-step excuse for that.
- **Deliberately not derived from the happy path.** A value that always agreed with `happy_path[]` could
  never disagree with it, and the disagreement IS the check: "you wrote that the happy path must reach
  this, and it never does" is the gap the forward direction exists to find. An EMPTY value means
  nobody decided, and warns; it never reads as `excluded`. (This is why the field is a word pair and
  not a boolean: `false` cannot tell "undecided" from "deliberately off".)
- **`validate` BLOCKS `happy_path` on a subsystem or a subdomain** — only a capability is on the
  happy path at all, and a happy-path expectation over code is exactly the parallel, contradictable axis the
  `tech`-on-a-subdomain rule already refuses.

### Audience — who a capability is for, authored once on the role

Every ROLE carries an **`audience`: `user` | `internal`**. It says WHICH SIDE of the product this
actor sits on. `internal` = the side of the company that ships it. `user` = everyone else, including
someone who has not bought it yet.

- **A capability's audience is DERIVED from it**, never authored: the roles driving its use cases
  vote. Nothing on the capability to contradict its own actors. A capability may honestly carry
  BOTH words — the derivation is a set, not a third value — and the views show one pill per word.
- **Only HUMAN roles vote.** A machine actor is the product doing work on someone's behalf, and one
  scheduler routinely fires a customer's work *and* the company's own upkeep. Machine roles are the
  fallback when a capability's use cases name no human at all.
- **The same question, answered from different evidence.** A PERSON is `internal` when they work
  for the company that ships the product. A PROGRAM is judged by **whose machine it is**, never by
  whose work it happens to be doing: the customer set it up (`user`), or the company runs it OR PAYS
  A VENDOR to run it (`internal`). A payment provider, an email sender or any other bought service is
  `internal`, because no customer configured it. Before this said so, two sentences disagreed and a
  vendor fell through the gap: Mio Coworker's Stripe webhook was authored `user`, on the reading that
  it is not an employee. Because a machine never votes, that imprecision could not reach a capability,
  but it was wrong on the Actors screen.
- **One word, on a person and on a program alike.** The word was `staff` until a count showed it
  naming the wrong thing: across the reference maps it printed in 12 places and only 4 were people.
  The views had grown a second form, `staff-owned`, just to make it usable on a machine. `internal`
  needs no second form, so the card and the actor's own page say the same word.
- **A capability driven by both sides warns.** It is a SIGNAL, not a rule, with three causes: the
  goal is really two goals (the usual one — two people on opposite sides of the company rarely share
  one, so **re-read the capability's goal first**); an actor is wrong (check that each use case names
  who really initiates it); or the surface genuinely serves both, like a support desk. Only the third
  is legitimate: record `CAPn: <why>` under an **"Audience exceptions"** heading.
- **One audience is NOT a grouping rule.** Several actors in one capability is ordinary — 10 of 27
  capabilities on the reference maps have more than one, and every one of them is unanimous. Several
  GOALS is the defect. Requiring one audience would force a wrong split on a shared surface.
- **Orthogonal to `kind`.** A customer's own bot is `service` + `user`; an upkeep job is `service` +
  `internal`. Neither derives the other.
- **Authored on the role because the role is the stable element.** Across 21 rebuilds of one repo the
  capability set churned every build while the same four roles appeared in nearly every one and never
  changed side.
- **Assign it once, at synthesis**, as `reconcile` set directives (`{"ids": ["UC1"], "capability":
  "CAP1"}`) — the same pass that assigns `subsystem` / `subdomain` / `runs_in`.
- **Do not confuse a capability with a product area.** A capability groups *use cases* (behavioral);
  a product area groups *components* (structural). A product area usually mirrors a capability —
  that is the point of the top-cut guidance — but neither derives the other.

### Happy Path — the spine (an ordered run through the use cases)

The Happy Path is one end-to-end happy-path **ordering of use cases** that traverses **all** main
functionality and involves **all** relevant actors; edge cases excluded. A use case on its own has
no fixed position — use cases relate by **preconditions**, a partial order / DAG ("an org must exist
before a user can join it"), and several orderings can satisfy it. The Happy Path is the **one
concrete run** through that DAG that tells a coherent story. Placed right after Roles/Use cases as
the spine; built after harvest + at least one full trace.

- **Each step IS a use case.** A step is a `**HPn — <use case name>** *(UCn)*` heading whose `*(UCn)*`
  tag (**required**) names the use case it realizes; `HPn` is just its position in the happy path. **A
  step has no text of its own**: its heading IS its use case's name, and the JSON record carries only
  `id`, `uc` and `why`. It used to carry a `title` as well, and the two texts drifted on every map
  ("Admin reviews the audit log" over "View and filter the audit log"); one goal is now worded once,
  and what a step adds over its use case is its POSITION and its `why:`. The step's
  *detail* — the sequence of actions and the components/deps/entities involved — is **not** written
  here; it lives once in that use case's **T6 flow** (below). Drilling a step opens its flow. A use
  case may appear at several positions (each a distinct `HPn`); the use case is still defined once.
- **Order = the chosen run; an optional `why:` line records the prerequisite** ("needs the org from
  HP1"). That is the only narrative the Happy Path itself carries — the actions and mechanics belong
  to the use case's flow, not restated here.
- **Two actors reaching one goal, or one goal at two moments, are not one step with a different
  label.** With no title to absorb the difference, the split must be real: two actors through
  different doors are two use cases (the door rule), and a use case at two positions is the same
  use case twice, told apart by `HPn` and by each step's `why:`. A post-condition ("the organization
  exists") is never a step at all — the outcome belongs to the use case's `Trigger → Outcome`, and
  state chaining belongs to dependent steps' `why:` lines.
- **Preconditions: implicit vs explicit.** *Implicit* = environment state no happy-path actor produces by
  using the product (the service is running, the database exists) — never a step, never mentioned.
  *Explicit* = something a happy-path actor actually does with the product's surfaces (a first-run
  sign-in) — it must live somewhere findable: an on-spine step, an off-spine use case, or the
  depending use case's trigger; when the happy path's FIRST step depends on it, say so in that step's
  `why:` so the spine-as-a-list reading isn't left assuming state nobody established.
- **Actor = the use case's actor.** Because a step is exactly one use case, its driving role is that
  use case's `Actor` — there is no separate `Actor:` line. A cross-actor handoff is simply the next
  step being a use case with a different actor.
- **Refer to actors by their role id** (`R2`, resolved to the Roles-table name in the views) — never
  invented persona nicknames, which anchor to nothing and can read as real data.
- **Coverage rule — asked at CAPABILITY altitude.** Pick the happy path hitting all main functionality +
  all actors; if one linear happy path can't reach everything, the use cases left off still have their own
  T6 flow, just not a spine position. Membership follows the capability's `happy_path`, in **both**
  directions, and `validate` warns (advisory) on each:
  - **forward** — a capability marked **`expected`** that no spine step reaches. About five checks on
    a real map, each a genuine gap. Fix it, or record `CAPn/spine: <why>`.
  - **converse** — a spine step whose use case sits in an **`excluded`** capability: either the
    expectation is wrong or the step does not belong on the main happy path. Record `HPn: <why>` to keep
    it. This is the direction a one-way check cannot produce, and it is what catches a happy path quietly
    padded with side work.
  - an **`excluded` capability that HOLDS off-spine use cases** needs ONE record — `CAPn: <why>`, not
    a line per use case. Without it, flipping a capability expected→excluded would silence its whole
    membership with no trace anywhere, and the field would have become an unrecorded escape.
  - a capability with **NO `happy_path` at all** warns on its own: the rule cannot ask the question.
  - **`audience` is not read here.** An `internal` capability sits on the happy path whenever the story needs
    it there, and that costs no record.
  - a **role none of whose use cases has a spine position** (the "involves all relevant actors" half)
    is unchanged: an ops-only role kept off the happy path is legitimate, but it is a decision — record
    `Rn: <why>` under the same heading.

  Every record goes under a **"Happy Path coverage"** extras heading, and ids are read from
  **line-leading** tokens only (`UC7: …`, `- R4: …`), so explanatory prose naming other ids never
  silences them by accident.

  **What this deliberately gives up**: an individual core use case falling off the happy path no longer
  warns, because its capability still passes. Those use cases are COUNTED instead
  (`off_spine_in_expected_capabilities`), so the trade stays visible rather than becoming a silent loss.
  The old rule demanded a written record for each one, and a record that costs more to write than to
  skip is a record that gets skipped. **A map with no capabilities keeps the old per-use-case rule**
  — `UCn: <why>` for each off-spine use case — so the check is additive rather than a cliff.

### Bidirectional traceability (use case ↔ elements) — standard

Connect each use case to the T1/T2/T5 elements its **flow** touches, **and** the converse, so the
reader can drill down (use case → elements) and step back (element → use cases). ONE source — the
**T6 flow steps** — both views derived; don't store links twice (they drift). A flow step's
endpoints (a component, dep, or entity) ARE the touches — **entities included, so a flow AUTHORS its
central entity touches as steps** (the entity-steps rule under T6): an entity's `Used in UC` view
exists only because flow steps name it. Deriving it **transitively** instead (flow touches a
component → tag every entity that component's edges touch) is rejected: an edge is an *aggregate* of
the component's whole behavior while a step is one scenario's interaction, so transitive tags smear.
Every step carries its **own** short action text describing what happens at that point in the
scenario — the same pair of elements can be used by several steps that mean different things, so a
shared pair-level edge label can't describe each one; the step describes itself.

Deliver as:
1. forward view = the use case's **T6 flow**, whose ordered steps name the elements it touches;
2. backward view = **derived, not authored** — the tooling shows, on each element, the use cases
   whose flow steps through it (`Used in UC`); T5 entities included (no extra column on the cards).

Give every use case, every T1/T2 row, and every T5 **card** a stable ID/anchor (the card heading +
its `SOURCE` link) so both link directions are clickable. Each touch inherits its flow's confidence.

One use case has two faces: **outside** — what the actor does and sees, carried by the use case's
`Trigger → Outcome` cell — and **inside = T6 flow** (the ordered interactions among
components/deps/entities), drawn as a flow map and read as a numbered narrative.

---

## Structural layer

### Level 0 (one screen, whole project)
- **Subsystems (S)** *(optional; recommended above ~15 components)*: `ID | Subsystem | Purpose |
  Parent | Source | Conf.` — the Container altitude: components grouped into subsystems, optionally
  nested (a subsystem's `Parent` is another `S`). Membership is carried on the child (a `Subsystem`
  column on T1); the member list and the inter-subsystem edges are *derived*, never authored. Present
  this first on large maps; drill into T1. **Nesting renders as recursive drill**: each subsystem's card
  shows only its *immediate* children (sub-subsystems as drillable boxes), so a large area drills down
  level by level inside the one map — there is no depth limit (deep chains only warn). Group the **top
  levels by product area** (what the system does), not by tech tier, and keep every card's fan-out near
  the **5±2 target** — see *Diagram balance — the fan-out rule* under Cross-cutting rules.
  Give each subsystem a **`tech`** label — ONE honest stack name ("Python/FastAPI", "Go", "Elixir")
  read off the manifests, with `tech_source` anchoring the manifest line (go.mod, package.json) —
  from the manifests, not a stack essay. Subsystem-only (`validate` blocks it on subdomains).
- **T1 Components**: `Component | Subsystem | Purpose | Entry point | Depends on` (the `Subsystem`
  cell is the component's one parent `S`, or empty = ungrouped).
- **T2 External dependencies**: `Name | Kind | Bucket | Type | Used for | Where configured`. Two
  independent axes describe each dep:
  - **Kind** (optional, CLOSED vocabulary) = *where it lives* — decides shown-vs-folded. External
    **systems** the project talks to across a boundary (`datastore` / `messaging` / `service`, incl.
    IdP/auth, payments, observability SaaS / `platform`) are drawn at Context by name; in-process code
    (`framework` / `library`) folds into one collapsed "Libraries" box. Omitted → inferred from `Type`.
  - **Bucket** (SEEDED-OPEN) = *what it's for* — the PURPOSE that GROUPS the dep into a labelled
    cluster. Externals cluster in the Context view; folded libraries cluster inside the Libraries
    drill (two separate diagrams — the cap of ~8 buckets is checked per-diagram). Reuse a seed's exact
    spelling when one fits, and on a rebuild reuse the bucket names already in the committed map. The
    seed list is a **floor, not a ceiling** — mint a bucket whenever a group of services shares a real
    purpose the seeds don't name. Seeds — external:
    `Data & storage` · `Identity & access` · `Observability` · `Messaging & delivery` · `AI & ML` ·
    `Infrastructure & runtime` · `Integrations` (catch-all); libraries: `Web framework / server` ·
    `Frontend / UI` · `Data drivers` · `Service SDKs` · `Validation / models` · `Logging` ·
    `Crypto / security`. Omitted → inferred from `Type` + `Used for`. Name a purpose, not a vendor
    ("Payments", not "Stripe"). **`Integrations` is the catch-all, not a home for everything external**
    — it means "no specific purpose." When several external services DO share a purpose, split them
    into their own bucket (`Payments`, `Social`, `Blockchain`, `Content` …) rather than letting them
    pile into `Integrations`; `validate` flags a bloated catch-all. Minting an external purpose bucket
    is expected and encouraged (external purposes are open-ended); for **libraries** the vocabulary is
    close to closed, so there a minted bucket is more likely a seed synonym worth folding. An
    integration-heavy product legitimately spans more than the ~8-bucket cap — that advisory is soft.
  - `Type` stays the free-text human label; `Used for` doubles as the short caption drawn under each
    box in the diagram (its first clause), so keep its opening words tight.
- **T3 How to run/build/test**: `Action | Command | Source` — `Source` is a bare `path:line` anchor to
  where the command is defined (the script / Makefile target / config line), not a doc pointer.

### Level 1 (one Level-0 row expanded)
- **T4 Entry points**: `Kind | Trigger | Code entity | Component | Activation` (activation = self|external, blank → inferred from kind).
  `Kind` is a **seeded-open vocabulary** — reuse a seed when one fits (external: `http-route`,
  `ui-route`, `cli`, `webhook`, `mcp-tool`, `middleware`; self: `job`, `poller`, `event-consumer`,
  `startup-hook`, `signal-handler`), mint a project-specific kind only when none does, and reuse the
  exact spelling on rebuild (`validate` folds known drift like `http`→`http-route` and nudges the
  rest). **State per-kind completeness honestly**: for each kind you record, say whether the
  inventory is complete or a sample — one line per kind under an **"Entry-point coverage"** extras
  heading, `<kind>: complete|sampled|partial — <how it was enumerated>` (e.g. `http-route: complete
  — walked FastAPI app.routes`). An unstated kind draws one aggregated `validate` advisory.
  **A command is an entry point ONLY when it acts on the DEPLOYED product — otherwise it is a T3
  row and only a T3 row.** What the command acts on decides, and nothing else: not its name, not
  what it is for. The deployed product means the live site, a live account at a provider the product
  runs on, the stored data, an instance somebody else depends on; **reading it counts**, since an
  operator who prints production data crossed the same door as one who changes it. A copy the
  command owns is not: a stack it starts and stops itself, a test database, a build output, the
  source, a fake server a test launches. **Being a test exempts nothing** — a release smoke test that
  signs into the live site IS an entry point, and a suite that starts its own stack is not. **When
  both sides fire, ask what was there BEFORE the command ran**: a thing the command creates and can
  destroy is a copy it owns, however publicly that copy can be reached, and a thing already there
  and still there afterwards is the deployed product. Three cuts settle the rest: a command that
  CALLS one of the product's own addresses is not a NEW entry point (the address is, and the slice
  holding it records it); a wrapper and the command it wraps are ONE entry point, recorded at the
  command that acts; what a container declares for ITSELF (its own argv, a healthcheck, a sidecar)
  is not a command anybody types and gets no row in either table, while **a command a PERSON runs is
  a command wherever it is written down**, a comment inside the compose file included.
  **Moving it is a WRITE, not a decision** — deciding a command is not an entry point is half the
  work, and the other half is its T3 row, written in the same edit. A harvesting agent states the
  count in its reply and names the commands it moved, because a row that was never written leaves no
  trace and no gate can see it. Measured on the first build under this rule: **11 of the 36 command
  files the previous map carried as entry points landed in NEITHER table**, the backend lint command
  among them, which the map now records nowhere at all.

  This is the rule T2b already states — "the pipeline that builds and tests the product is not a
  product interface" — moved to the step that MINTS the rows, because a row that is never harvested
  cannot be grouped onto a surface afterwards. Measured on a live map: its "Command line" surface
  held 36 ways in, 32 of them the build and test pipeline, 31 of those reached by no use case, and
  15 already carrying a T3 row that cited the same `path:line`. The surface read as a product edge,
  and the use-case advisory fired 31 times on rows that were never product behaviour. **Every clause
  above the evidence paragraph is a row a reader actually got wrong**: two fresh agents ran the
  first draft over two repos, and the draft's unconditional "a test is never an entry point" fought
  its own "what it acts on decides" on a smoke test against production. Both agents named that pair
  unprompted, and between them reported 16 places the wording did not decide.
  For every **self-activated** entry point, also record its `cadence` — WHEN it runs (a cron expr,
  `every 30s`, `on-boot`, `continuous`) — with `cadence_source` anchoring the line that declares
  the schedule (the beat/cron config or the loop's sleep, often not the entry point's own line).
  While harvesting queue consumers, also fill the **`messaging` catalog** — one row per named
  channel/queue/topic (name, broker dep, publisher/consumer components, payload entity, the line
  declaring the channel name); each participant still needs its real `C→broker` edge (the rows
  catalog, the edges claim — see [the map model](method/model.md)).
- **T2b Interfaces** *(the product's outside edge)*: `Name | Side | Kind | Facing | What it is |
  Far side | Source`. Author this AFTER T2 and T4 both exist, since it groups their rows. There is
  no "what crosses" block: what crosses a surface is the flow steps drawn at it, and each of those
  says which way it went. An **interface** is a surface through which the product SENDS data or events
  **not consumed by the product itself**, or RECEIVES data or events **not generated by the product
  itself**. Four lines close the gaps: (1) data the product produces only to read back is EXCLUDED
  (its own database, cache, queue); (2) code and build artifacts that BECOME the product are not
  data crossing a surface (installed packages, container images, scripts fetched from a CDN);
  (3) the pipeline that builds and tests the product is not a product interface; (4) an outside
  consumer **the map records** beats the read-back exclusion — a store a person browses on their own
  IS a surface, a store only the product reads back is not. **Name the far side, never the pipe**: a
  log shipper and a reverse proxy are pipes, the log store and the dashboard are the surfaces; mark
  the SERVICE, never the library that calls it.
  **The route that serves the built app, and the catch-all that serves its shell, belong to the web
  surface they serve.** A browser fetching the shell IS the product meeting a person, so those two
  rows go on the screen surface the person ends up looking at, exactly like the addresses that
  surface's pages call. They were treated as plumbing that could belong nowhere, which left the
  "every way in belongs to a surface" advisory firing on both live maps with no fix that would ever
  satisfy it: a check nobody can clear is a check people stop reading.
  Deliberately NOT a criterion: **who runs the machine**. A self-hosted database and a hosted one are
  the same thing to a reader; what separates a database from a log store is whether the product ever
  reads the data back.
  **One row per SURFACE**, never per address or per command, and **split when the AUDIENCES differ**
  — a customer dashboard and an admin console behind the same routes are two surfaces. An HTTP
  address that only serves the product's own front end belongs to that front end's surface; a
  separate API surface exists only when someone outside is expected to call it directly.
  `Side` is whose DESIGN it is (`ours`/`theirs`): if the far side vanished tomorrow, would this
  thing's design change? `Facing` is who it serves (`user`/`operator`) and is AUTHORED — the actor
  `audience` field answers a different question and marks a bought payment service `internal` while
  its interface is user-facing.
  **`Kind` is WHAT THE SURFACE IS** — authored with the row, one word, from these eleven seeds:

  | Seed | The picture | Covers | Side |
  |---|---|---|---|
  | `screen` | a browser window | our web UI, a marketing site — anything served to a browser | ours |
  | `mobile-app` | a phone | an app a person installs on a phone | ours |
  | `desktop-app` | a window with a title bar | an app a person installs on a machine | ours |
  | `command-line` | a prompt | commands typed in a terminal | ours |
  | `file` | a document | files we write that something else opens | ours |
  | `settings` | a gear | the values a person or an operator sets | ours |
  | `message` | an envelope | a message we send outward to a person: email, SMS, push | ours |
  | `hosted-screen` | a window someone else owns | a sign-in, a chat platform, a vendor console the product's own flow sends a person to | theirs |
  | `content` | a page | data we read that we did not write: the open web, a repo, a transcript | theirs |
  | `handoff` | an arrow out | we hand the PERSON to another program: a link, their editor | theirs |
  | `api` | a plug | one program calling another over a network, either direction, webhooks included | either |
  | `agent-tools` | a wrench | tools an AI agent calls, ours or theirs, whatever protocol carries them | either |
  | `mcp` | a wrench with a plug | an MCP address, ours or theirs | either |

  **THE MOST SPECIFIC SEED THAT FITS WINS, and `api` is the fallback.** `api` is a SUPERSET of
  several of the others: every `agent-tools` surface is also one program calling another over a
  network, and so is much of `content`. Nothing in the list used to say which to pick when both fit,
  so the vaguer word tended to win — never flagged as wrong, and never the better answer. It cost a
  real row: mcpolis's "Upstream
  MCP servers" — the servers its gateway asks for their tools and forwards each call to — is `api`,
  where `agent-tools` says the same thing and more. So the gateway wore a wrench and the servers it
  calls wore a plug, on one screen, for one protocol. Reach for `api` only when nothing more
  specific describes the surface.

  **WHAT IT IS, never WHAT IT IS FOR.** A payment processor and a crash reporter are both `api`; which is which
  is already authored one table over, on the dependency's `bucket`, in a richer vocabulary. A kind
  that answers "what is it FOR" means the row has been mis-modelled — `validate` nudges rather than
  blocks, and you adjudicate. On the `theirs` side almost every surface IS the same kind of thing (an
  HTTPS call to a vendor), so expect several rows to share `api` and let `bucket` tell them apart.
  The `Side` column above is GUIDANCE, not a rule: a product can host a screen someone else designed
  and publish an API someone else's spec defines.
  **Seeded-open**, like an entry point's kind: prefer a seed, mint only when none fits (there is
  deliberately no seed for CI, hardware, telephony or a browser extension), and reuse the exact
  spelling on rebuild or the eval reads one surface as two. Do NOT derive it from the ways in —
  measured, that gives one clean answer on 4 of coyomap's 11 surfaces and 1 of mcpolis's 12, and
  NOTHING on a `theirs` surface, which has no ways in by definition. A real surface is several
  mechanisms: a dashboard is `ui-route` + `http-route` + `event-consumer`, and those three together
  ARE a web UI.
  **The tiebreak**, for a surface that is both a place people act and a service we call: *the kind
  names where the PEOPLE are, but only when the product's own flow takes them there.* A chat
  platform the product lives in, a sign-in redirect and a hosted checkout are `hosted-screen`; a code
  link we hand over is `handoff`; a crash reporter an operator opens on their own is `api`.
  **A vendor console is the case this decides, so read it twice.** "A vendor console" sits in the
  `hosted-screen` row above AND under this tiebreak, and the two point opposite ways: the row says
  the console IS a window someone else owns, the tiebreak says it is `api` unless our flow takes the
  person there. THE TIEBREAK WINS. Crash reporters, analytics and log stores are `api` — staff open
  them on their own — and they become `hosted-screen` only where the product itself links a person
  in. Measured: this one question decides 3 of mcpolis's 16 rows and 3 of argus's 12, and two
  independent readers of this page called the pair a contradiction before it was written down.

  **`message` IS THE ONE SEED WHERE THE PRODUCT GOES TO THE PERSON.** Every other `ours` seed is a
  place someone comes TO the product; this is the one that leaves, and the person reads it somewhere
  we do not own — an inbox, a phone. Use it when the far end of the wire is a person: a sign-in link
  mailed to an admin, a text message, a push. Do NOT use it for a message we send to a SYSTEM (that
  is `api`), and do not reach for `api` here because the SMTP or push provider is a service we call:
  `api` names the pipe, and this names the surface. Two independent readers made exactly that
  mistake on mcpolis's "Outgoing email" before this seed existed, and both said why in the same
  words. `notification` was the other candidate and was rejected: it says WHY, and a password reset
  and a marketing blast are both notifications and are not the same kind of thing.

  **`mcp` IS THE ONE PROTOCOL NAME IN THIS LIST, and it is deliberate.** Every other seed says what
  a surface IS; this one says which protocol it speaks, which is normally the ways in's job
  (`mcp-tool` already lives there). It earns a seed because reading it off the ways in CANNOT work
  on a surface someone else defines — one has no ways in by definition — so a derived label put MCP
  on the three servers mcpolis publishes and stayed silent on the one it calls. And because
  `mcp-tool` is the fourth-biggest way-in kind across the live maps (63, behind only `http-route`,
  `cli` and `ui-route`). Use it wherever the surface really speaks MCP, on either side; use
  `agent-tools` for agent-facing tools carried some other way, such as a skill file an agent reads.
  **DO NOT MINT A SECOND PROTOCOL SEED BY POINTING AT THIS ONE.** If another protocol ever earns a
  word it will be on its own evidence — measured, and underivable from the ways in — not because
  this one is here.

  **`content` versus `api`: it is the FAR SIDE that decides, not the data.** Both bring back things
  we did not write, so the data cannot separate them. `content` is MATERIAL we read, with no service
  on the far side to have a contract with: the open web, a repo, someone else's transcript, source
  files on disk. `api` is a NAMED SERVICE we call. Measured across the three live maps and it splits
  every row cleanly — `content` on the open web, project source files and a coding agent's
  transcript; `api` on Scrapfly, Sentry, Mixpanel, Elastic and E2B. The hard case proves the rule:
  a paid service that FETCHES WEB PAGES for us is `api`, because we call Scrapfly, even though what
  comes back is exactly the material `content` describes.

  **`settings` versus `screen`.** `screen` covers anything served to a browser, which swallows
  `settings` whenever the values live in a web page — so `settings` is for values set OUTSIDE a
  browser: a config file, environment variables, a flag file an operator edits. Values a person
  types into a page of ours are `screen`.
  **`actors` is DERIVED and is NOT a field — never author it.** Who is on the far side falls out of
  the flows, from TWO sources, and the first is the strongest. **(1) The DOORS**: any role standing
  at a step next to the surface, `Rn → In` or `In → Rn`, either side, on ANY surface and with no kind
  gate — a written step is the map's own statement, not an inference. **(2)** A `theirs` surface also
  takes the roles whose stories reach it, but ONLY when the kind is `hosted-screen` or `handoff`.
  A use case's `entry_points` play no part — they say which surface a flow must open at, and the
  flow's door is what puts the person there. A surface
  neither of the two reaches derives NOBODY, and that is usually the correct answer, because the
  product itself is what reaches most outside services — but do not read it as permission to skip a
  door. If a surface hands something OUT and derives nobody, the missing thing is a story, and
  `validate` says so. Writing it by hand was measured and is worse: one build authored a single role
  on a dashboard whose flows show three.
  An actor here means a role OUTSIDE the product. A role that is `kind: service` AND
  `audience: internal` is the product's own scheduled work and never stands on a far side. **`ways_in`** are `EPn` ids and travel through `reconcile` like a use
  case's, never hand-written into a fragment. `source` is the ONE line declaring the whole surface
  (the router, the command table, the file writer) and is optional: a settings surface is declared in
  no single place. Every EXTERNALLY-activated entry point belongs to exactly one surface, except the
  plumbing kinds (`middleware`, the built-asset route, the catch-all); every T2 dep in the external
  group must either name one or more surfaces (`deps[].interfaces` is a LIST — one outside
  system can sit on several) or say **why it is none** — without the reason there is no way to
  tell a deliberate exclusion from nobody having looked, and that is the trap a search service sets
  (over the product's own records it is not an interface, over the open web it is, and the two call
  sites are identical). Record a deliberate exception as `In: <why>` or `EPn: <why>` under an
  **"Interface exceptions"** extras heading.
  **Doors — put the surface IN the story.** A story crosses between an ACTOR and the product at two
  moments, and BOTH of them go through a door. **"Actor" means any `Rn` that is OUTSIDE the
  product** — a person, or a program somebody else runs (a customer's headless agent, a partner's
  bot). **The product's OWN scheduled work is not an actor for this rule**, even though the map
  draws it as one: a role that is `kind: service` AND `audience: internal` is a timer, a boot hook or
  a signal handler inside the process. It is not an actor ANYWHERE in the rule: a flow it starts
  takes no arrival door, a step handing back to it is not a hand-off, and it never stands on the far
  side of a surface. Read those two fields; do not read the role's name. BOTH are required — an
  internal HUMAN role is an operator or a staff admin, who very much comes in through a door. This was got wrong on the first real trial,
  because a role called "Upkeep job" is named in one breath as an actor and in the next as a timer.
  Measured on mcpolis: 7 of its 42 flows are started by that one role, which is the whole difference
  between the 42 flows that mechanically open at a role and the 35 that owe a door.
  **EVERY crossing, not only the two ends.** A step with an actor at one end and the product at the
  other is a crossing, wherever it sits in the story, and `Rn → Cn` / `Cn → Rn` is never the finished
  shape. The three places it happens:
  **(1) The ARRIVAL.** The flow's FIRST step names the surface the actor comes in by: `R1 → I3`, then
  `I3 → C12`.
  **(2) The FINAL HAND-OFF.** When the flow's LAST step delivers to an actor, it goes out the same
  way: `C43 → I3`, then `I3 → R1`. **Draw the out-door even when it is the SAME surface the story
  arrived by**, or the picture shows an outside edge with one side missing, and the surface reports
  only one direction while traffic really runs both ways.
  **(3) EVERY EXCHANGE IN BETWEEN.** A preview at step 4, a question answered at step 6: each one
  goes through its door too, exactly like the two ends.
  An "endpoints only" rule was tried first and REJECTED once it could be measured on a doored map.
  It drew one person on both sides of one wall: mcpolis's invite story routed the admin through the
  dashboard at its two ends and straight past the dashboard in the middle, for the SAME person and
  the SAME component. Measured on that map, the strict rule costs 36 more steps, about 6%, and it
  adds NO new box to any picture, because all 36 crossings sit in a story that already draws the
  door they route through. It also draws FEWER arrows: 525 across the 42 stories become 522, since
  the direct person-to-component lines fold into door arrows that were on the page already. **Do not
  reintroduce an endpoints-only rule.** The readability argument for it runs backwards.
  **WHICH surface — look it up, do not guess.** The arrival surface is the one whose `ways_in` hold
  the use case's `entry_points`; that link is already authored. If those entry points sit on MORE
  than one surface, stop: two doors onto one goal is the split this method already asks for under
  *Use cases*, not a flow with two openings.
  **The hand-off surface is the SAME one only when the story ends where it began.** It is a DIFFERENT
  surface whenever the last step ends somewhere else, and there are three shapes of that, not one:
  the result is delivered without a screen (a mail, a written file); the last step's component lives
  behind another surface (the story is set up on the dashboard and answered at the gateway); or the
  last step reaches a DIFFERENT ACTOR from the one who opened it (an admin sets a rule, and the
  member's assistant is the one refused). In all three the hand-off surface is where THAT actor
  stands, never where the story started. Read the last step, not the first. All three came up on the
  first real trial and none was covered — a literal reading would have drawn a gateway refusal on a
  dashboard screen. A use case
  with no ways in has no authored answer: pick the surface whose own sentence describes where the
  actor stands, and if none does, the map is missing a surface — add NO door, and SAY SO IN THE
  REPORT YOU HAND BACK, naming the flow, the step and what the person is really standing at. There is
  no field for it and you must not invent one; the report is where a missing surface gets decided. An
  invented door is worse than a missing one, because the next reader cannot tell it was invented.
  Nothing OUTSIDE the step list changes: a door is a step, and everything the map says about that
  surface's traffic is read back off its steps.
  **WHAT the two new steps say, and which phrase goes where.** Every step carries a phrase and the
  doors are no exception, so renumber the whole list and write both — in the STORY'S own words, never
  by copying an example off this page. **A phrase belongs to whoever ACTS in it**, so which of the
  two steps keeps the old phrase is decided by the old step's DIRECTION, never by where it sits in
  the story. Both rules below apply to a MID-STORY crossing exactly as they do to the two ends.
  **INBOUND (`Rn → Cn`) — the old phrase is a HUMAN action, so it MOVES to the new actor step.** The old
  `R2 → C121` "types the colleague's email and clicks Add" becomes `R2 → I2` carrying that same
  phrase, and the rewritten `I2 → C121` is given a FRESH phrase in the surface's own voice ("sends
  the new member and the role they were given"). Leaving the human phrase on the surface step is the
  mistake this paragraph exists to stop: it makes the map say *the dashboard clicks Add*, and it
  makes the two steps say one thing twice. Measured on the first real trial: 11 of 11 arrivals came
  back with a screen doing a person's action.
  **OUTBOUND (`Cn → Rn`) — the old phrase is already the product's action, so it STAYS.** The old
  `C121 → R2` "puts the join address on the clipboard" becomes `C121 → I2` with its phrase intact,
  and the NEW `I2 → R2` is written fresh, saying what the surface puts in front of them.
  **An ANCHOR never sits on a step you create against an actor.** On an INBOUND crossing the old
  step's anchor is usually the clicked widget, and that line describes the person, not the surface:
  DISCARD it and give the rewritten `In → Cn` step the route line instead. On an OUTBOUND crossing
  the old anchor is the delivery line and it stays on `Cn → In`. An anchor that was ALREADY sitting
  on an actor step before you started is a different thing and harmless — leave that one. (Two
  sentences here once said "leave it" and "the actor step takes no anchor at all", and a worker
  called choosing between them a coin flip.) A NOTE travels with the PHRASE IT
  ANNOTATES, which on an inbound crossing means it moves out to the actor step with that phrase: a note saying
  "the bin only appears for an admin" explains a gesture, and on the surface step it annotates a
  sentence that no longer mentions the bin.
  **A phrase that is half a GESTURE and half a PAYLOAD splits between the two steps**, and most are.
  "clicks sign in with Google, carrying the organization's short name" is a person clicking and a
  request travelling. The gesture goes on the actor step, the payload becomes the surface step's own
  sentence. Do not move the whole thing and then hunt for something else to say.
  **When the phrase is ALL payload and the split leaves the surface step nothing new**, say what the
  surface GUARANTEES or CHECKS about what it carries — that the file is read as text, that the token
  is presented as a bearer, that the request is stamped with the team. **If it genuinely guarantees
  nothing, say that it passes the request on, and stop.** Do NOT invent a guarantee to satisfy this
  paragraph: a sentence that sounds like a check and is not one makes the map untrue, and no check
  anywhere can catch it. Measured on the retrofit: an inbound crossing whose human phrase is an act of ATTENTION
  ("opens", "picks", "confirms") separates cleanly on its own; one whose human phrase is a HANDOVER
  needs this clause, and that was 4 of 7 in one batch.
  **The rewritten step now needs a CODE ANCHOR, and often did not before.** A step touching an actor
  is a human action and needs none; `In → Cn` and `Cn → In` are element-to-element and `validate`
  BLOCKS without a `where` or a `no_call_site`. So the rewritten step keeps the anchor it had, and
  where it had none you must supply one: the line where the surface reaches that component (the
  route handler, the command's own function, the screen's own handler), or `no_call_site` when the
  wiring is genuinely event-driven or config-wired.
  **USE THE WAY IN'S OWN `source` LINE.** A surface is made of ways in, each one already carrying the
  line where the outside reaches the code — a route, a mount, a tool handler, a command. Pick the way
  in this step comes through and take its `source`. That is the whole rule, and it works on every
  shape: a web page's way in IS its route line, a gateway's is its tool handler, a command line's is
  its command. Take the way in THIS STEP comes through, not the use case's own entry point, when a
  story moves between two of them.
  **This BEATS "the step keeps the anchor it had" when the two disagree**, and they disagree often:
  the old step's anchor is usually the CLICKED WIDGET, because the old step was the person clicking.
  That line describes the ACTOR step, which takes no anchor at all, so keeping it on the surface step
  anchors the step to a place it does not happen. Three workers hit this and resolved it three ways,
  leaving one map with two conventions for one shape.
  Found the long way round: a worker doing a gateway, where no page and no route exists, went and
  read the surface's ways in to get its line — and that is the general rule the page-shaped wording
  had been hiding all along.
  **Going the other way (`Cn → In`), anchor the line where the component DELIVERS to the surface** —
  the return, the render, the write — not the route. The NEW step against the actor needs neither.
  Measured before this clause existed: of the steps this rule rewrites, 41 across the two live maps
  carried no anchor, and every one of them would have become a blocking problem.
  **An actor reaching a DEPENDENCY or a stored RECORD is a crossing too** — `R1 → D7`, `R1 → E3` —
  and it takes the same treatment: name the surface the dep stands on, or the surface the person is
  at, and keep the actor. A person never touches a dependency or a record with nothing in between;
  if no surface fits, the map is missing one, so say so and add no door.
  **A MID-STORY crossing takes its door like any other**, and it takes the surface the actor is
  standing at RIGHT THEN. That is not a judgement call — TRACK IT. Read down the steps and keep one
  fact in your head: where is the person standing now? They start where the story opened. They stay
  there until a step MOVES them (a redirect out to a sign-in provider, a link handed over, a mail
  sent). Then they are at that new surface until something moves them back. Every crossing uses
  wherever they are at that step.
  **The `ways_in` lookup answers the story's ARRIVAL and nothing else.** Do NOT reach for it in the
  middle of a story: the map may well author the RETURN address of a sign-in round trip as a way in
  of your own dashboard, and following that link would say the person picked their account on your
  screen. They did not.
  **A trip out and back is ONE two-way door, at the surface they went to.** They leave through it,
  and they come back through it: `C50 → I8` then `I8 → R3` going out, `R3 → I8` then `I8 → C84`
  coming back. Our own callback address is the PIPE on that return leg, and naming a pipe is what
  this whole rule exists to stop. Two workers split on exactly this and each could defend it from the
  page, which is why it is now written down.
  **Name the surface the actor is really at, even when it puts a NEW box on the picture.** A
  redirect out to a sign-in provider is that provider's screen, not the address that issued the
  redirect. Measured on the doored map, the strict rule adds no new box in almost every case — but
  that is a RESULT, never a target, and a worker who picked the already-drawn box to protect the
  number chose the wrong surface. If no surface in the map fits the place the person is really
  standing, say so and add NO door: the map is missing a surface, and a wrong door hides that.
  **A flow whose LAST step is the actor acting AGAIN (`Rn → Cn`) still takes a door** — an inbound
  one, `Rn → In` then `In → Cn` — because it is a crossing like any other. It has no hand-off, and
  that is a smell worth reading twice: the story stops mid-conversation, so ask whether it is traced
  to its outcome or hands over to another use case.
  **Name the surface, never the thing standing on it — and a dep and an actor differ here.** A step
  reaching an outside SERVICE names the surface ANYWHERE in the flow, and the dep is then derived
  rather than drawn: `C12 → D7` becomes `C12 → I7`. A step reaching an ACTOR names the surface
  anywhere too, and there the actor is KEPT: `C43 → R1` becomes `C43 → I3 → R1`. The asymmetry
  is deliberate — a dep is a pipe the surface replaces, an actor is somebody the surface stands in
  front of. Without either, a reader sees the PIPE and not the door: a flow that draws `web browser`
  as its only outside box is naming the thing this method tells you never to name.
  **A door is not only a way IN, and the direction is read off the INSIDE end** — never off whose
  surface it is. `Cn → In` and `In → Rn` are the product reaching OUT; `Rn → In` and `In → Cn` are
  the story coming IN. The two are commonly both present on one surface (a request and its answer),
  and neither maps to `side`: the files a product writes are OUR surface written OUT through, and a
  chat platform is SOMEONE ELSE'S surface stories arrive IN from.
  A step with a surface at EITHER end does NOT count toward the 3-15 step band — it is structure, not
  detail. (A sub-flow reference is the model's other structural exemption; that one counts as 1, a
  door counts as 0.) So doors LOWER a flow's counted length by ONE PER CROSSING — every rewritten
  step stops counting, and a story with four crossings loses four. (This once read "by up to 2",
  which was the arithmetic of the withdrawn endpoints-only rule and would have sent an author to pad
  a flow that was fine.) A flow near the ≥3 floor can therefore drop under it purely by being doored,
  and the answer is that the flow was too short, never that the doors were wrong. Measured when the
  strict rule landed: the shortest counted length on either live map is 5, against a floor of 3, so
  nothing falls under today. **A MIGRATED dependency step stops counting too** — it is not an actor
  crossing, but it now has a surface at one end, so a story that migrates two pipes loses two more
  from its counted length on top of its crossings.
  An existing `Cn → Dn` step on a dep that stands on ANY surface MIGRATES to that surface, `ours` as
  much as `theirs`; the dep is then derived. **RE-VOICE that step's phrase when it names the vendor.**
  It almost always does — it was written about the dep — and leaving it makes the map name the pipe
  in words while the step names the surface in ids, which is the same defect one sentence apart.
  "hands the message to the Workspace mail service" becomes "hands the message to the mail that goes
  out to members". (This once read "a `theirs` surface", which the checker
  never agreed with and which is wrong on its face: the mail service standing on our own
  outgoing-email surface is exactly the step that gives that surface its story.) The BACKBONE EDGE
  LIST does not migrate with the step: an edge runs between code and a dependency, a surface is never
  an edge endpoint, and a story naming the surface beside an edge naming the dep is the correct end
  state, not a contradiction.
  **WHAT CROSSES A SURFACE IS ITS WALK STEPS, and there is no field for it.** `carries[]` was
  removed: it stated in a sentence per direction what goes in and out, and every part of it was
  either unsaid elsewhere for one reason only, or already said. Measured on the two live maps before
  the removal — on the surfaces with the richest flows, 66% of a row's words were already in the
  steps and 4 rows were word-for-word copies of a single step; its record list held 68 references of
  which 2 were a real independent stored record, the rest being wire shapes, embedded parts and
  computed views; and one of its genuinely-new facts ("shown exactly once") was a claim nothing in
  the map backed, which is exactly what an unanchored sentence attracts.
  **The ONE thing it said that a step could not is WHICH WAY THE DATA GOES, and that now rides the
  step** — see `direction` under T6 below. Do not reintroduce a per-surface direction: an interface's
  directions are the SET its steps carry, and a second authored copy is a second thing to disagree
  with.
  **EVERY INTERFACE OWES A USE CASE — SWEEP BACK ONCE THIS TABLE EXISTS.** This is the one pass that
  runs the OTHER WAY. Use cases are written before interfaces, because this table groups the T2 and
  T4 rows; nothing has ever fed a surface discovered here back into the use case list. That ordering
  is why argus's paid page-reading service is in no story at all, while two neighbouring steps of the
  story that needs it mention paid reading in prose.
  So when this table is done, read down it and ask of each row: **which use case crosses this?**
      - a surface a story already reaches -> nothing to do
      - a surface serving a PERSON that no story reaches -> the story is missing. Write it, or draw
        the step where it belongs — the call, fetch or hand-off goes at THIS surface, not at the one
        a cheaper path through the same code reaches.
      - a surface serving an OPERATOR that no story reaches -> the same answer. It owes a use case
        too; see the operator rules under Roles. Its own "What it is" sentence usually names the
        person and what they do with it.
      - a surface genuinely nobody ever reads -> record `In: <why no story crosses it>` under an
        **"Interface exceptions"** extras heading.
  `validate` reports every unstoried surface, so this sweep is checkable rather than a good
  intention. A surface no story reaches leaves the map unable to say what crosses it or when.
  **AND THE SWEEP RUNS BOTH WAYS.** Reading down the table finds a surface no story reaches. It
  cannot find the opposite — a story that needed a surface nobody wrote — because that row is not in
  the table to be read. A tracing agent is the only thing that ever sees it, and it says so in its
  report: *"no authored surface fits that, so I added no door there and the story stops."* Answer
  every one of those lines:

      for each flow report that says no surface fitted:
          mint the surface, and send that flow back to close through it
          OR record `UCn: <why this story's person stands at no surface>`
             under a **"Missing surfaces"** extras heading
      a report answered by neither is a row this build loses silently

  The same shape, one gate later: `validate` reports a **walk jump** when a step starts at a box
  no earlier step of that story reached. The default reading is a missing step, and the fix is to
  write it. A story that deliberately opens a second thread (a job the first half set going)
  records `UCn: <why this begins a new thread>` under a **"Walk jumps"** extras heading, and the
  check skips that use case.

  **This has happened, and the two builds differ only in the answer.** On 2026-09-02 a tracing agent
  reported that a marketing story ends by handing the visitor to their own mail program and that no
  surface fitted; the lead minted the row 13 minutes later and sent the agent back to close the
  story through it. On 2026-09-06 the same report arrived, the lead called it "a second wording
  correction", rewrote the use case's outcome sentence, and wrote no row. The map's only `handoff`
  surface is gone, its code is unchanged, and the story's own outcome still reads "their own mail
  program opens" while no box in the map is one. Eight other flow reports landed in the four minutes
  after that one.
- **T5 Domain model** *(domain cards)*: one **card** per entity, not a table row — a block
  `**En — Name**` + `MEANING` / `FIELDS` / `RELATIONS` / `SOURCE` (a block with a defining heading,
  like the Happy Path and T6 flows). Renders as a Mermaid `classDiagram` (boxes with attributes + typed, cardinal relations).
  Each entity is a **real named type** whose `SOURCE` anchors its definition (don't synthesize
  unnamed concepts), and its NAME is the reader's word for it, never the class's spelling — one
  build named 52 of 59 entities after their classes. Entity↔entity relations are authored on the
  source card only, never in the backbone edge list. Full spec: [domain cards](method/domain-cards.md).
- **Subdomains (SD)** *(optional; recommended above ~15 entities)*: `ID | Subdomain | Purpose | Parent |
  Source | Conf.` — the domain analog of Subsystems: T5 entities grouped into bounded contexts,
  optionally nested. Membership is carried on each card (a `SUBDOMAIN:` line holding one `SD`); the
  member list, the inter-subdomain arrows, and the subsystem→subdomain bridge are *derived*. The Domain
  diagram then leads with a Subdomains overview and drills into one subdomain's classDiagram.
  - **Each subdomain holding SAVED records names its `owners`** — the feature(s) it exists FOR.
    Ask one question per area: *which feature is the reason this data exists — who creates its
    records and runs their lifecycle?* One clear answer → `"owners": ["CAPn"]`. Several genuine
    ones → list them all, and the split / dominance advisories then challenge the list. No clear
    answer → leave the field out and record `SDn: <why>` under a **"Data owner exceptions"** extras
    heading. **Never author an owner to make a diagram complete**: an owner whose feature's flows
    reach none of the area's records is reported as AN OWNER WITH NO EVIDENCE, which is worse than an empty column.
    A "saved record" is an entity whose `store.mode` is `collection` or `embedded`; an area of pure
    plumbing (request shapes, enums, read projections) is not asked the question at all.
    - **DECIDE IT AFTER THE TRACE, NOT AT SYNTHESIS** — the flows have to exist first. The
      question is which feature the data exists FOR, and the only evidence that bears on it is
      which features' flows reach the area's records. At synthesis that evidence does not exist
      yet: the areas and the features are written, the flows are not. Deciding there is deciding
      blind, and `validate` cannot help either — run it at that moment and every owner comes back
      ungrounded, because no flow reaches anything yet.
      MEASURED, on the mcpolis build of 2026-08-26: decided at synthesis, 8 areas took 8 single
      owners, one feature took 5 of them, one owner was reached by no flow at all and needed a
      recorded exception to get through. The SAME map and the SAME instruction, decided after the
      trace, changed exactly those two answers — the owner with no evidence became the one that
      really writes the records, the over-claimed area became an honest three-way share — and
      needed NO recorded exception. Six of the eight answers were identical, so the cost of
      waiting is two decisions' worth of nothing.
      Author it in the same after-the-trace pass that writes the rules, and run `validate` there:
      the split / dominance / grounding challenges all work from that point on, and answering one
      is cheap while the flows are in front of you.
    - **WRITE IT ON THE SUBDOMAIN ROW ITSELF.** A sub-domain is a `Group`, and `reconcile` has no
      directive that can reach one: its `set` fields all target a component, entity, use case, dep
      or rule. So edit the area's own row in the fragment that declares it — the `CAPn` ids exist
      by then, minted back at synthesis.
    - **The one record whose owning feature differs from its area's** carries `owners` on the ENTITY
      instead — an audit entry sits in the Audit trail area but is written by the gateway. That one
      DOES go through reconcile (`{"ids": ["E51"], "owners": ["CAP4"]}`), for the same reason
      `capability` does: the entity was authored in the T5 harvest, before any `CAPn` existed. An
      override is checked as hard as an area: one that repeats what the area already says is
      reported as redundant, and one naming a feature whose flows never touch that record is
      reported as ungrounded. It belongs only on a SAVED record; on anything else `validate` blocks
      it.
    - **WHY AUTHORED, and why no derivation replaces it.** Code says what a feature TOUCHES; it
      cannot say what the data is FOR, and every derivation was measured on three live maps and
      failed the same way. First-touch-in-story-order hands "Snapshots and change" to Page tracking,
      not to Change detection — the snapshot is first written by the tracker and exists so the
      change detector can compare it. Touch counts hand an area to whichever feature has the most
      sign-in plumbing. Majority vote per area split 5 of one map's 8 areas, several on 1-1 ties
      decided the wrong way. So the map states the judgement and the tools cross-examine it: the
      touches are shown as evidence beside it, and the ONE disagreement never reported is "the owner
      is not the first feature to touch the area" — that disagreement is the field's reason to
      exist.
- **T6 Use-case flows** *(the inside view of each use case — a block, not a table)*: one block per
  use case, `**UCn — <title>**` + **numbered step lines**. Each step is an ordered interaction
  `from → to`: **every step** — element↔element and actor steps alike — carries a short authored phrase
  saying what happens at that point, as an action in the IMPERATIVE ("POST the new upstream", "return
  the verified email"), never the third person, which is what the arrow shows. The viewer titles the
  step with the phrase ALONE, with no subject in front of it, and a use case's name and a shared sub-flow's
  name are written the same way — one form for every action the map states. Don't lean on the backbone edge for it: the same
  element pair can appear in several steps that do different things, and one shared edge label can't
  describe each; the step describes itself. A phrase is **pure action** — a condition or qualifier
  ("when the baseline needs a paid read…") goes in the `· note`, not the phrase (the
  dependency-phrasing audit trips on condition-shaped phrases). An optional
  `· <note>` adds flow-specific context.
  - **Where auth (or any shared ceremony) belongs**: include it as STEPS only where it is the
    MECHANISM of this use case's outcome (a member joins *by* completing the invite-link OAuth
    callback — remove those steps and the story breaks); where it is merely a prerequisite state
    (an admin must be signed in before creating the org), it is the use case's **trigger**, not
    steps. One machinery, two roles — mechanism in one flow, precondition in another — is correct,
    not an inconsistency. Renders as a Mermaid `flowchart` — one box per touched element (the actor
  included), one arrow per ordered pair, labelled with the step numbers riding it — **and** as a numbered
  narrative beside it. Drilling a Happy Path step opens its use case's flow here. The viewer also draws
  the same steps as a **leaf-only map** (a box per touched element, no container frames) for the
  "what does this use case touch?" reading — a second *rendering* of the one step list, never a second
  authored thing ([diagrams](method/diagrams.md)).
  - **Every element↔element step carries its own `where` — THE location.** A step is exactly ONE
    interaction, so it anchors its own call site: the `path:line` in the step's `from` code where this
    step's action fires (the same "anchor the operative statement" rule as an edge `Where`). Unlike an
    edge's `Where` (an *example* among possibly many sites — see the edge rules below), a step's
    `where` is precise: the viewer drills the step to exactly this line, and the diff-impact engine
    hits the step (→ its use case → the Happy Path) directly when the line changes. You already read
    this call site to write the step's phrase — record it. **Required** on element↔element steps
    (`validate` blocks; `lint-fragment` catches it in the authoring agent's own turn); a step with
    genuinely no single site (event-driven / config-wired) sets **`no_call_site: true`** instead.
    Actor steps (a Role endpoint — a human action) need none, though a `where` is welcome when the
    handler line is clear. Step numbers `n` must be unique within a flow (`validate` blocks) — they
    identify the step for impact and navigation.
  - **`direction` — WHICH WAY THE DATA MOVES. Owed by every step where the map's own code touches a
    SURFACE or a RECORD, empty on every other step — INCLUDING A DOOR.** A door is a role standing
    at a surface, which is a human action with no product end: argus's operator opens the log
    store's own console and nothing of ours moves. Same exemption an actor step already has from
    `where`. Read it from the PRODUCT'S OWN CODE, never from the arrow:
    `in` the data arrives at it, `out` the data leaves it, `both` one exchange runs each way.
      - at a RECORD: `in` is a read, `out` is a write.
      - at a SURFACE: `in` is what the product receives, `out` is what it sends.
    **Anchor it on the product, not on the arrow.** `In → Cn` is the surface handing inward what
    it received, so that is `in` however the arrow points.
    **`both` is for one exchange, and it is not a cop-out.** A code traded for a verified email, an
    upsert that returns the stored row. Splitting such a step in two only lengthens the flow to
    record something the step already knows.
    **DO NOT READ IT OFF THE ARROW'S POLARITY, ever.** A PULL points outward while its data comes
    back. Doing that flipped argus's "Tracked web pages" from `in` to `out` on a page the product
    fetches, and it is why this is authored rather than derived.
    **This is the map's ONLY statement of direction**, and it replaced `interfaces[].carries[]`.
    Nothing else holds it: the `C→E` arrows say BOTH read and write on 83 of the 170 record steps
    across the live maps, and no arrow reaches a surface at all.
  - **EVERY SAVED RECORD OWES A USE CASE, the same way every interface does.** A record this
    codebase KEEPS — `store.mode` of `collection` or `embedded` — that no flow step reaches leaves
    the map unable to say what it is FOR: it draws a box on the Data tab whose owner nothing backs,
    which is the "owner with no evidence" defect arrived at from the other side.
    **A record INSIDE another one counts as reached when its holder is**, so an embedded piece needs
    no step of its own. That is what makes the rule affordable rather than a demand for a step per
    field: on one live map it is the difference between 17 of 35 saved records reached and 28 of 35,
    and it hid nothing — the 7 it left were records with no holder and no story, and each of those
    turned out to be a real gap.
    **NOT every entity.** A read shape over rows something else owns, a request object built for one
    call, a set of constants: the codebase saves none of them, and demanding a story for those would
    bury every real gap under the 96 of 142 named things that owe nothing.
    `validate` reports the unstoried ones. The escape is `<En>: <why no story keeps it>` under a
    **"Balance exceptions"** extras heading, for a record only a migration writes.
    **AND THE STORIES MUST NOT CONTRADICT THE ARROWS.** An arrow saying `C31 writes E18` is the map
    stating that the code writes that record. If no flow step ever writes it, the map disagrees with
    itself, and it is the ARROW that is the evidence. `validate` reports each one; draw the missing
    touch as a `Cn → En` step carrying that direction, in the flow where it happens. Measured on the
    live maps: 2 of 46 saved records, both argus's, each with a `writes` arrow and only ever read in
    a story. A record whose only arrow is a `reads` is correctly silent — someone else writes it.
  - **Entity steps — author the flow's CENTRAL entity touches (1–2 per flow).** The entities whose
    read/write IS the scenario's outcome or decision appear as their own steps — `C5 → E2 : upserts
    the Membership document @ repo.py:155` — not only as backbone edges: the entity `Used in UC`
    view and line-level diff impact derive from steps, so a flow that narrates only components
    leaves the whole domain model untraceable while every gate stays green (`validate` warns when NO
    flow touches any entity; a map whose flows legitimately touch none records the literal
    `entity-flows` under `Balance exceptions`). *Central* means the join flow's Membership upsert or
    the tool-call flow's RoleSettings decision + AuditEntry append — NOT every config read along the
    way (those stay edges; tagging them all is the transitive smear again, hand-authored). Each
    entity step **rides an existing `C→E` backbone edge** (the edge is the aggregate claim, the step
    this scenario's instance). Author that edge in your slice with the right verb (`reads` /
    `writes` / `persists` — the ownership verbs are what the domain `persists/writes` view reads).
    As a safety net, `assemble` now **derives the C→E edge from any entity step that has none**
    (verb inferred from the phrase, ambiguous → `reads`), so at scale a forgotten edge self-heals
    instead of leaving the entity ownerless — but an inferred verb is coarser than the one you know,
    so still trace it. It carries the ordinary element↔element `where` (the operative read/write
    line in the `from` side's code), and obeys the same false-reads rule as `C→E` edges (the entity
    TYPE at the site, not a string extracted from it). A shared sub-flow is the leverage point: one
    entity step there serves every referencing flow. Entity steps are ordinary authored steps — they
    count toward the 3–15 band; a flow already at the band edge extracts a sub-flow or records its
    exception rather than dropping the entity touch.
  - **Steps can go *backward*, not just forward.** A flow isn't only the request chain — record the
    return-direction interactions where they carry meaning: the **response the actor sees** (the use
    case's outcome), an **error / fallback** path, a **callback or event** the callee fires back. A step
    whose `to` is an earlier participant renders as a **right-to-left** arrow automatically (lifelines
    are placed in first-appearance order). These are **authored steps** (a return is not a backbone
    edge), so write them like an actor step — `C5 → C2 : returns the member list`, `System → Member :
    shows the org`. Don't echo *every* call with a return — only the ones that say something.
  - **Named sub-flows (`SFn`) — machinery shared by ≥2 flows is defined ONCE.** When the same step
    sequence rides several flows (an event fan-out, a persistence pipeline), extract it into a
    sub-flow — `**SFn — <name>**` + ordinary step lines under all the ordinary rules (phrase,
    `where` anchors, unique `n`) — and reference it from each flow with a step whose `subflow`
    names it: `k. C1 → C2 ⟨run SF1 — <name>⟩` (src/dst are the run's entry/exit endpoints; the
    phrase may be omitted — it defaults to the sub-flow's name; the reference carries NO `where` of
    its own). One level only — a sub-flow's step may not reference another sub-flow (`validate`
    blocks). A sub-flow with fewer than 2 reference STEPS across the map is pointless indirection
    (`validate` warns — it counts reference steps, so two references inside one flow do not warn). The payoff is CONSISTENCY: without it, each flow retells the shared machinery at
    whatever depth its author picked — the viewer draws the reference as ONE dashed box named after
    the sub-flow, opening onto the sub-flow's own screen, and the diff-impact engine reaches every
    referencing use case from a changed sub-flow line.
  - **The step band: 3–15 steps per flow** (advisory; a sub-flow reference counts as **1** — the
    reward for extracting). Over 15 means one of four things, in the order to try them: **split a
    fused goal** (two use cases were stapled together), **compress step altitude** (protocol
    round-trips narrated at wire grain — fold "401 → metadata → retry" into one meaningful step),
    **extract a sub-flow** (shared machinery inlined), or — when the length is genuinely earned
    (a chatty auth handshake that IS the story) — **record the exception**: the flow's UC/SF id
    under a `Balance exceptions` extras heading, with one line of why. Under 3: check the flow is
    traced to its outcome. `validate` also flags **literal duplication** (a run of ≥4 steps
    identical in endpoints AND grounding appearing in ≥2 flows; runs through an actor step are
    exempt — a sub-flow can't contain them) — extract a sub-flow, or, when investigation shows the
    overlap is deliberate, **record the adjudication**: `UCa & UCb: <why>` under an
    **"Accepted duplications"** extras heading, which silences that pair (a justification that
    lives only in the build transcript re-fires at every future validate). The *same machinery
    retold at different depths* can't be caught mechanically — that is a Phase-4 grounding item
    (below).

### Operational dimensions — standard core four
- **Deployment & topology**: `Unit | Runs on | Exposed as | Config source`. These are NOT tabled on the System tab — that page is for facts no diagram holds. Each row's facts live on the box that represents it in the Deployment view: its **process box** for a unit that hosts code (or an untraced one), and the **dependency box** standing in for it when the unit is infrastructure hosting no code. `variants` shows there too, as an **Environments** row with its grounding anchors. **Link the code to the
  runtime with `runs_in`** — on each component, the deployment `Unit` name(s) whose process executes
  it (a component may run in several: the C4 *instance* relation, one static box → many processes). It
  powers the **Deployment view** (`coyomap serve` → Deployment tab): processes and infra as nodes,
  their self-started threads on drill, and derived `runs` edges to the subsystems each process
  executes. It also carries the view's **process topology**, composed from `runs_in` two ways:
  **asynchronously**, via the async catalog (a channel's `publishers`/`consumers` are components, each
  naming its host unit) → an arrow per channel one unit publishes and another consumes; and
  **synchronously**, via the backbone edges (a component→component edge whose ends run in DIFFERENT
  units is one process calling another) → an arrow per crossing call. Both matter: a message-driven
  system is all channels, an ordinary client/server app is all calls, and deriving only one leaves the
  other kind of project with an empty diagram. One arrow per ordered pair either way, on the overview
  and on both units' cards, selectable to list what it stands for with each declaring line. The overview's
  infrastructure lane is likewise **placement, not a catalog**: it shows only the brokers/stores/services
  used by **2+ processes** — the coupling points — each with a real arrow per user, selectable to list
  the components inside that process that reach it, with their verb, reason and call site. Infra a single
  process touches stays on that process's card; the full inventory is the Dependencies view's job (and
  the Data view's, for stores), so repeating it here would only restate them less completely.
  That lane's sub-bands read **"Used as a message bus / data store / service"** because they group by
  the VERB the code reaches the dependency with, not by what the dependency is. So two deps of the same
  `kind` can sit in different bands — a live map put Mixpanel (`kind: service`, reached by `emits`) in
  the bus band and Sentry (`kind: service`, reached by `calls`) in the service band. That is the useful
  question here ("how does the code talk to this?", which no other view answers), so the grouping stands
  and the LABEL says which question it is answering. Do not re-word an edge verb to move a box between
  bands: the verb records what the call site does, and the band follows it.
  Selecting an **environment** never removes a box: units the environment excludes are **dimmed in
  place and made inert**, so "not deployed there" is visible instead of being a silent absence, and the
  layout does not move when you switch. (One diagram serves every environment; the `variants` tags ride
  on the boxes and the viewer fades the rest.)
  The overview draws **runtime things only** — processes and the infrastructure coupling them. There is
  no subsystems lane: subsystems are code structure, the Subsystems view already draws all of them with
  their real relationships, and a lane here could only restate the subset whose components happen to
  carry `runs_in`. The code→process placement is answered in the **info pane** instead: selecting a
  subsystem or a component shows **Runs in** — the units that run it, each a link opening that
  process's card — and each unit's own card still draws what it runs. The row is absent when nothing
  records running that code, which is the visible sign that its `runs_in` tagging is missing.
  **Derive `runs_in` by READING THE DEPLOY MANIFESTS — never formula-fill by id range.** Open
  the docker-compose services, the Dockerfiles + their `CMD`/`ENTRYPOINT`, k8s/Helm, the `Procfile`, and
  the launch entrypoints (`manage.py`, `main`, the worker bootstraps): for each unit, tag the
  component(s) whose process loads it, and tag each background-loop entry point with its precise host.
  Grounding: **verified** for a satellite that owns its dir/image (obvious from the Dockerfile/dir),
  **inferred** for a shared monolith (which sub-command/loader pulls the component in) — mark it inferred
  where the manifest is ambiguous; empty = untraced. For a background loop whose component runs in >1
  unit, set the loop's own `EntryPoint.runs_in` for a precise host. A deployment `Unit` is **ONE
  process**: keep the name atomic (no `mongo / redis` compound rows) and give each its own row. Infra the
  app merely *talks to* (mongo/redis/nginx) is a **dependency**, not a `deployment[]` process box — the
  Deployment view draws a unit as a process only when a component or entry point `runs_in` it, so an
  infra-only unit renders as a dead empty box. **A unit only the test suite starts is not a
  deployment unit**: its code is outside the map's scope, so no component can ever `runs_in` it and
  the row is BORN as that dead empty box (a live build shipped an "OAuth test MCP server" unit from
  the e2e harness's compose file, and it failed the linkage gate as the map's one regression).
  Deploy manifests used only by tests belong out of the deployment table entirely. `validate` blocks a `runs_in` that names no real unit (and
  a duplicate unit name), advises on a self-started entry point left with no host (it would be "Unplaced"
  in the view), and now **flags a formula-filled `runs_in`** (one unit blanketing every component while
  other units host nothing and no entry point is placed), a **non-atomic unit name**, an **unlinked unit**
  (hosts nothing, matches no dependency), and an **ambiguous thread host** (a loop whose component runs in
  >1 unit but which sets no `runs_in`). `runs` edges are **derived, never authored** in the edge list.
  - **Environments (deployment variants).** Many projects deploy the same code in several
    **variants** — dev / staging / prod, or genuinely different shapes (a single-container
    `standalone` vs a multi-service `cloud` split). This axis is usually declared in the source:
    docker-compose `profiles:`, k8s/Kustomize overlays, Helm values files, Terraform
    envs/workspaces, `.env.<name>` suffixes, serverless/Procfile stages. **Capture it, don't flatten
    it** — folding the variants away as "over-modeling" loses real information. List the variant
    names in the top-level **`environments`** array, and tag each `deployment[].unit` with the
    **`variants`** it belongs to (empty = **ungated / shared**, appears in every environment). Each
    variant tag is an object **`{env, source}`**: `env` names the environment, and `source` is a
    bare `path:line` anchor to the manifest line that places the unit there. Keep the unit name the
    process identity (`backend`), not the env (`backend (cloud/prod)`) — the env lives in
    `variants`. A component's environment is **derived** from the variants of the units it
    `runs_in`. **The tags GATE the Deployment view's process→process arrows**, so leaving them off
    is not free: two units that share no environment can never be running at the same time, and an
    arrow between them is false however the derivation reached it. An untagged unit stays ungated
    and pairs with everything, which is the right default for a map with no variant axis and the
    wrong one for a map that has one and skipped it. Two grounding rules keep the tags honest:
    1. **Ground each `variants` tag in the explicit profile axis; cite it, never invent one.** The
       compose `profiles:` (or overlays / values files / stages) ARE the authoritative "what runs where"
       list — so put the exact line you read in the tag's **`source`** (e.g. `docker-compose.yml:96`).
       `validate --check-sources` verifies that line exists, so a fabricated anchor is a hard block. A
       tag you genuinely cannot anchor is **inferred**: record it with an empty `source` and `validate`
       surfaces it as an advisory — do NOT dress an inference as a fact. A process that appears in **no**
       profile is an ad-hoc / local-dev launcher (started by a `start.sh`, a Makefile target, a `README`
       step) — tag it **`dev`** (or leave it untagged), never a real deploy variant it has no manifest
       basis for.
    2. **A built / static asset served by another process is NOT its own deployment process there.** A
       Dockerfile that does `npm run build` (or any `build`) then `COPY …/dist …` bakes an artifact
       INTO an existing unit — the artifact is *served by* that unit, not *run as* a separate process.
       So do not give it its own unit/variant in that environment; place it only where it actually runs
       as a live process (e.g. the frontend is a Vite dev server in `dev`, but a static bundle baked
       into `standalone` and `nginx` for `cloud` — so it is a separate unit in `dev` alone).

    `validate` blocks a `variants` tag whose `env` names no declared `environments` entry, blocks a
    cited `source` that doesn't resolve on disk (under `--check-sources`), and advises both when
    `environments` are declared but no unit is tagged and when a tag is inferred (no `source`). **If the
    project has no meaningful variant axis (a single deploy), leave both empty** — the Deployment view
    then behaves exactly as before.
    *(Deferred, not modelled yet: per-environment config/secret differences, env-specific
    scaling/replicas, and a cross-environment comparison view.)*
- **Observability**: `Signal | Where emitted | Where viewed | Alerts`.
- **Security & auth**: **an auth surface IS a business rule** — write it in T7 with `access: true`,
  its enforcement line as a site, and what is at stake as its `risk`. The Security & auth table is a
  DERIVED VIEW of those rules; there is no separate `security[]` to author. **BREAKING, and there is
  no migration tool**: a map built before this carries `security[]` rows, and the table still
  renders them beside the rules so nothing disappears — but a map gains the decision layer only by
  being REBUILT. The site anchor must point at the line that ENFORCES — the
  `if`/`raise`/`require_*`/decorator call — **never its docstring, comment, or `def` header** (the
  same operative-line rule as an edge `Where`, below). It is an L2 grounding claim, so
  `--check-sources` verifies the file/line exists. **STATE THE GRANULARITY, and record it.** One row
  per surface FAMILY ("the dashboard API's session auth") and one row per endpoint-and-condition
  ("`/mcp/{slug}` with a service token for another org", "replay of a logged-out session cookie")
  are both defensible — and they differ by 5x in row count on the same codebase. Pick one, say which
  under a `Security granularity` line in your reply, and record it in the map:
  `security-granularity: <family | endpoint-and-condition> — <why>` under a 'Balance exceptions'
  extras heading. (The T7 rule for "fusion is preferred to splitting" pulls the same way: one
  decision enforced at several endpoints is ONE `access` rule with several sites.) Nothing else in
  the pipeline can see this choice: `--check-sources` only proves each row's anchor resolves, and
  `audit` turns each row into exactly one claim, so no gate can tell a 19-row access surface from a
  103-row one. A large change in what the map says about access control has to be a decision
  somebody wrote down, not a drift nobody noticed.
- **Config & environments**: `Key | Purpose | Default | Per-env / secret?` (secrets =
  where they live, never values).
- On-demand extras: state machines/lifecycles, event/message catalog, error/failure
  modes, change hotspots (git churn), permissions matrix (Role × use case).

### Business logic — what the product DECIDES (T7)
**This is the one genuine content gap the other tiers do not cover.** Entities say what the product
stores, flows say what it does in what order, lifecycles say what states it moves through,
components and edges say how it is built. None of them says what it **decides** — and the decision
is exactly what a reader means by "the interesting, product-specific part". A reader who asks "what
is special about this application?" gets no answer from a well-formed map without it.

A **rule** is ONE decision, in product language, naming no component: *"only the order's owner may
cancel it"*, *"own connection first, else oldest shared"*. It carries a short `name` beside that
sentence ("Owner-only cancellation") — the title every list, breadcrumb and cross-link reads, exactly
as a use case has a name beside its trigger→outcome. A **block** groups rules the way a
capability groups use cases — an area a product person would argue about. Rules are written after
the trace, one agent per block (see *After the trace*), because sweeping a rule's enforcement sites
needs the flows.

**Each block names its `specified_under`** — the feature(s) a person writing the product's spec
would put these rules under. Written ON THE BLOCK at synthesis, like a sub-domain's `owners` and for
the same reason: the areas are authored in the same pass that mints the features, so the answer never
has to travel through `reconcile` the way a rule's `block` does. Ask *under which feature would these
rules be written?* One clear answer → `"specified_under": ["CAPn"]`. Several genuine ones → list them
all. No answer → leave the field out and record `BLKn: <why>` under a **"Decision area exceptions"**
extras heading; an advisory asks either way. `[]` is a shape error, not an answer.

**TWO STANDPOINTS, AND THIS FIELD IS THE FIRST ONE.** They give different answers on most areas, so
the question has to be settled in one place, and this is it:

    SPEC         under which feature would these rules be WRITTEN
    ENFORCEMENT  in which feature's code are they APPLIED

mcpolis's "Who may call which tool" is **specified under Access control** — the feature whose whole
job is deciding who may reach which tools — and **enforced** inside the gateway. Its "Plan caps" is
applied across six features (teammates, servers, roles, machine sizes, argument checks, history) and
specified under a plans feature that product has not shipped, so the field is absent there and the
absence is recorded.

**THE ENFORCEMENT ANSWER IS ALREADY DERIVABLE, and that is what settles it.** A rule carries its own
call sites; sites resolve to components; steps join to use cases and so to features. Spending the one
authored field on that would buy a worse copy of something the map already computes. Nothing in the
code says where a rule would be WRITTEN IN A SPEC — that judgement is the thing only a person can
make, and it is the reason this field is authored rather than derived.

AUTHORED, and this one was measured before it was written. Every derivation was tried on three live
maps and every one failed: the feature a rule's steps land on is a plurality, not a home (52% and
61% of an area's links at the median, 8 of 32 areas winning on under half, one on 23% against a
runner-up at 20%); entities reach only 10% of walked steps and leave 3 of 11 areas with nothing;
actors collapse to two groups of nine and two; components fan out past 100 per map; and the happy
path ties four areas at one station. The viewer GROUPS the Rules page by this field, and because
features are already ordered by the story column, the groups arrive in the product's own order with
no second field to author.

`validate` blocks `specified_under` on a subsystem, a capability and a sub-domain (one dataclass, four
forests), blocks an id that names no capability, a repeat, and an empty list; and it cross-examines
the answer against the features the area's rules actually reach — reporting a governed feature no
rule of the area reaches, never a disagreement about WHICH feature leads, since that disagreement is
the reason the field is authored.


Each rule carries `sites`: every place the decision is actually ENFORCED, anchored at the
**operative line** — the one that acts, never a definition header and never a line chosen because
it happens to join a flow step. A decision enforced by construction (a type, a schema constraint, a
config-wired guard) says so with `no_call_site` and no anchor.

**Everything else is derived.** Which components enforce a rule, which use-case steps it lands on,
which entities it touches and whether the sweep that produced it finished are all COMPUTED from the
site anchors — there is no field for any of them, and none may be added. Hand-assigned data rendered
as if it were derived looks correct on screen, which is exactly why it is refused. An authored "I
searched the whole repo" is unfalsifiable, so sweep state comes from a canary instead — anchored
flow steps that read like a decision no rule covers (`validate` lists them; the `Sweep debt` extras
heading records the ones that are not decisions). **The canary is a floor, not a proof**: it reads
the wording of anchored steps with a heuristic vocabulary, so an empty worklist means "nothing
obvious was left", never "the sweep was exhaustive".

**This section is shown in the viewer** (`coyomap serve` → Business logic tab) and in the markdown
view as `## T7 — Business logic`, with each site rendered as *line — component*. A file several
components claim shows EVERY one of them; a site in a file no component claims renders as
**unverified**, which is a real state, not a rendering bug.

### Test completeness — measure against the MAP, not line %
**This table is shown in the viewer**: the `coyomap serve` Tests tab renders the honesty note + the
gap table (`Target · Tested? · Test(s) · Gap/risk · Confidence`) — so an empty table is a visible gap.
**Be honest about whether you ran it.** A gap table built by *reading* tests is **inferred**; only
running the suite with coverage makes it **verified**. If you don't run it (the suite is slow or
costs money — e.g. paid integration tests), state that above the table and mark every row inferred;
never present a read-only table as if it were measured.
Coverage % tells which lines ran, not which behaviors are tested. Start from the
inventory (use cases, T4 entry points, failure modes, invariants, state
transitions, critical-path branches) and ask "is there a test that exercises it?" —
gaps are the deliverable.
- Map tests → targets as `test — covers → element`; gap = element with no incoming
  "covers" edge. Each row names its `targets` as explicit element IDs (e.g. `["UC1","C4"]`, not
  prose) and cites the exercising suites in `tests` as `{file, why}` — `file` a bare `path:line`
  or `path/` anchor the viewer turns into a code link.
- Run the suite with a coverage tool for real line+branch data — running beats reading.
- Cross them: coverage says which lines ran, the map says which matter; flag critical
  targets (money/auth/data-loss/irreversible) with low branch coverage first.
- Output: a risk-ranked gap table — `Target | Tested? | Test(s) | Gap/risk | Confidence`
  — NOT a single percentage. Lead with untested critical paths.
- Completeness ≠ test quality (a test can cover a line and assert nothing). Gold
  standard = mutation testing — expensive, offer as an opt-in deep cut on critical paths.
- Confidence ladder: reading tests = inferred; running with coverage = verified;
  surviving mutation = strongest.

### Level 2 (on demand, reached by drilling)
T8 Component internals · T9 Config/env vars · T10 Data schema. Nothing in the tooling produces these
— they are on-demand drill tiers, not rendered map sections like T7.

### Relationships (always included)
- Backbone = a project-wide edge list: `From | Verb | To | Why | Where`. Uniform
  `source — verb — target` so the reader drills from either end. Verb vocabulary:
  uses, calls, reads, writes, emits, listens-to, routes-to, enforces, persists, encrypts,
  extends, implements.
- **Verbs may PRIORITIZE, never GATE.** A verb is an authored word — no deterministic check verifies
  it against the code. So a verb may set *attention* (the audit ranks its L2 worklist by verb —
  security verbs like `enforces`/`encrypts` first) but must never decide *truth*: no gate may branch
  pass/fail on a verb, no claim may be dropped from grounding because its verb sounds benign, and a
  rendered fact derived from a verb is **inferred**, never asserted. The one verb-derived viewer fact
  is the class-diagram **inheritance** arrow (`isA`): the viewer renders the authored verb plainly, so
  it reads like any asserted edge — if it matters, ground the underlying edge (L2), don't trust the
  verb. (The subsystem→subdomain bridge is **not** verb-derived — it shows a count of underlying C→E
  edges, like the container arrows.)
- **The edge list spans C↔C, C↔D, *and* C→E — components / deps / entities ONLY, never an actor.**
  It is not only component↔component: a component's
  link to the domain model is a backbone edge `C — persists/writes/reads → E` (its repository
  `persists` the entity; a service/controller `reads` it — **direct** use only, never a transitive
  edge). Author these alongside the component edges — they power the component↔class cross-links and
  the subsystem→subdomain bridge. (Only E↔E relations stay off the backbone — those live on the
  domain cards.) **An actor (`Rn`) is NEVER a backbone endpoint** — a person/service driving the
  system is expressed as a T6 flow **step** (`R1 → C5`), not an edge; a trace agent that emits an
  `Rn → C` edge is a prompt defect, and `assemble` strips it and warns (fix the trace prompt, don't
  rely on the strip).
- **A C→D edge names the ROLE with a role-revealing verb — never a bare `uses`.** State HOW the
  component uses the dependency: `publishes`/`emits` for a **message bus**, `reads`/`writes`/`persists`/
  `queries` for a **data store** (a query IS a read), `calls` for a **service**. The dep's role is then
  **derived** from the union of its incoming C→D verbs (a witnessed fact — each verb has a `Where` — not
  a stored field), so a dependency used two ways (Redis as **bus + store**) is captured by having
  **both** edges with their real verbs, and its role reads "bus · store". `validate`/`lint-fragment`
  raise a **non-blocking advisory** on a roleless C→D verb (`uses`/`connects`/…) so you pick a real one;
  it never blocks and never fires off the dep boundary (a C↔C / C→E `uses` is fine).
- **C→E is additive — it must NOT thin the component graph.** Trace `C↔C` and `C↔D` **first**; add
  `C→E` after, never instead. Completeness: **every external dep (T2) needs ≥1 incoming component
  edge** — a dep with no edge is an *un-traced* `C→D`, not an unused dependency — and a component
  graph with far fewer edges than components is under-traced. The component edge list is the primary
  trace output; the validator nudges on orphan deps (a thin-trace symptom).
- **Trace the routing spine (frontend / any router).** A routing or app-shell component MUST emit a
  `routes-to` edge to each page/view component it mounts — the route table is real structure, not
  "wiring" to skip. Page components are **traced destinations, not dead-ends** (they still make their
  own outgoing calls to API clients / hooks). A frontend whose pages have zero incoming edges is
  under-traced, not leaf-clean.
- **`Why` = a short phrase: what `From` does to/with `To`** — an **action**, not a dependency remark
  (e.g. "verify service tokens", "cache refreshed OAuth tokens"). Write "POSTs the new upstream through
  the REST client", never "the page needs the REST client to POST" — a "needs / requires / depends on"
  framing describes a static wiring fact, not the runtime action, and reads wrong on the diagram. The
  edge list is the **canonical home for relationship rationale** — the verb gives the category, `Why`
  gives the purpose the verb can't carry (especially the catch-all `uses`). Prefer a sharper verb first;
  let `Why` say what the verb omits. Keep it a terse phrase, not a sentence, so it stays cheap to
  re-verify. This `Why` powers the **component/architecture diagram** arrows; T6 flow steps carry their
  **own** action text (above) and do not reuse it.
- **`Where` = a verified EXAMPLE call site: one `file:line` in `From`'s code where it invokes `To`**
  — not `To`'s definition. An edge `A — verb → B` is *evidenced* by a line in **A** where A uses B, so
  `Where` points there. The edge is an **aggregate** of possibly many interaction sites, so its
  `Where` is a **witness grounding the claim, not a catalog of the traffic** — and it is therefore
  A location, never THE location: the viewer deliberately does not show or open it (per-step `where`
  in T6 owns drill-to-code), while validation, anchor drift, and diff impact still use it. Write the
  edge's `Why` the same way: a **summary of the whole relationship** ("writes org, membership and
  settings documents"), never one call's story — one example's rationale on a shared arrow reads as
  wrong for every other step riding it. **Anchor the exact operative statement** — the write / call /
  enforce line itself — **not the enclosing `def` or the surrounding assignment**; anchoring at the
  function header instead of the operative line is the common drift the Phase-4 anchor-drift check
  flags. When the relationship fires at several sites, pick the **primary / most representative** one
  (one `Where` per edge; do NOT emit the same `(From, verb, To)` from several trace slices with
  different anchors — `assemble` collapses same-call-site duplicates and `validate` flags
  conflicting-anchor ones). Format it as a bare `path:line` anchor (never a markdown link — see
  [the map model](method/model.md)'s Anchor formats).
  **`Where` is required** — a missing one is a blocking `validate` error, because an unwitnessed edge
  is an ungrounded claim. The one exception: a relationship with **no single call site**
  (event-driven, shared-state, or config/DI-wired coupling, where `From` never directly calls `To`) —
  set **`no_call_site: true`** on the edge to make the absence a conscious choice, not a silent gap.
- Convenience = the T6 flow steps, which retell the most-used slice of the edge list in reading order.

---

## Cross-cutting rules

**Write every reader-facing field to be read ALONE.** The six rules live in ONE file,
[method/templates/writing-rules.md](method/templates/writing-rules.md), because the agents who
author that prose are fan-out workers who never read this document: they get a contract, so the
rules have to travel inside the contract. Every authoring contract is assembled by appending that
one file, never by restating it — a second copy is a second thing to keep in step, and the copy
that drifts is always the one nobody re-read.

`validate` counts four of the six and reports them as advisories. Jargon, metaphor and whether a
sentence actually reads clearly are judgements that stay in the prompt: a regex guessing at them
would be the noisy check nobody leaves switched on.

**A blocked command is a STOP, not a puzzle.** When a shell or safety guard refuses a command, say
so and ask — never rewrite the command so the guard stops matching: not by assembling a blocked
filename out of string literals, not by splitting a blocked path across a `+`. A bypass may well be
harmless and the block a false positive — which is exactly why it is worth stating: the reasoning
that produces a harmless bypass is the same reasoning that produces a harmful one, and the guard
exists because that judgement is not the agent's to make. If a guard is wrong, saying so IS the
deliverable. Reaching for a different TOOL and reporting that you did is fine; disguising the same
command is not.

**Two shell hazards this method's own commands keep hitting.** Both are invisible until the output
is wrong rather than absent.

  * **NEVER `cd` into the coyomap clone. Not once, not in any command.** The `cd` persists across
    `;`, across `&&`, **and across separate Bash calls for the rest of the session** — that last one
    is what makes this expensive, and the sentence used to omit it. A later
    `python3 -c "…open('.coyomap/project-map.json')…"`, in a command that mentions no clone at all,
    then reads *coyomap's own self-map*: a wrong answer that looks like a right one, carrying
    coyomap's vocabulary rather than the mapped project's. `git status` in the analyzed repo shows
    nothing, because nothing happened there.
    It has now cost two consecutive builds. One read a gate result about the wrong product; the next
    went further and EDITED the clone's committed map plus a working file, and had to repair both.
    Address BOTH repos by absolute path, always, and run the CLI by its absolute path with no `cd`.
    **Say this to every sub-agent you dispatch, in its brief.** The rule lived only here, in the
    lead's guide, and on the 2026-09-02 build **8 of 75 sub-agents stepped into the clone, 33 times**
    — none of them had ever read this line. The shipped contracts carry it now; a brief you compose
    by hand must too.
    `coyomap` refuses to read the clone's own `.coyomap/` unless `COYOMAP_SELF_MAP=1` is set, which
    catches the verbs — but a bare `python3` heredoc is not a coyomap verb, so the rule still has to
    be obeyed rather than relied on.
  * **This environment is zsh, and zsh does not word-split an unquoted expansion.** Building a
    repeated flag as a string — `VD="$VD --verdicts $f"` — arrives as ONE argument and the command
    refuses it. Use a bash array: `VD=(); VD+=(--verdicts "$f")`. This holds for every repeatable
    flag, `--keep` and `--verdicts` included.

**Emit every independent tool call in ONE message.** Two calls are independent when neither one's
ARGUMENTS come from the other's result: reading three files, running `validate` and `audit`, four
`fix row` edits to four different ids, a `grep` and a `sed -n` over the same tree. Batch those. Only
a call whose arguments you cannot write until you have seen the previous result earns a turn of its
own.

The bill is counted in TURNS, not in calls: every turn re-sends the whole conversation, so two
independent reads in two messages cost twice the context of the same two reads in one. Measured on a
small build, **99% of its tool turns carried exactly one call**, across 526 turns. Batching what was
already independent is worth about **a fifth of the lead's own spend**, on a small map and on a
large one alike, and it changes nothing about what gets read — the same calls, in fewer envelopes.
(The fan-out rule below, *"one batch" means one MESSAGE*, is this same rule applied to agent
dispatch; it is stated there as well because a batch of agents must also be atomic, not merely
cheap.)

**The two ways a batch goes wrong.** **One: a batch that is not actually independent** — a `fix row`
whose `--id` you were going to read out of the `audit` output in the same message. That is not a
batch, it is a guess. **Two: batching a WRITE with a READ of what it writes** — `assemble` beside
`validate`, `fix row` beside `dump`. The read then races the write and which state it sees is not
yours to control. Reads batch with reads; writes to DIFFERENT targets batch with each other; a read
of what a write just changed waits for the next message.

**Reach for the verb before the heredoc.** Every row below replaces a `python3 - <<'PY'` block, and
each verb exists because a hand script got the same job wrong once. Measured: 12 of one build's 28
hand-written scripts had a verb already, and the scorecard assertion watching this fell 1.00 → 0.57.

**And the verb you have not heard of is the one you will hand-roll.** A later build ran
`record --remove`, `record --replace`, `record --lines-from` and `fix row --set-why` **zero times
between them**, while six of its heredocs did exactly those four jobs — including one that spliced
`extras.json` by string match twelve turns after using `fix row` correctly on the same component.
All four shipped, tested, in the tool commit that build pinned. Read this table at the barrier, not
from memory:

| you are about to hand-write | run instead |
|---|---|
| a walk over `build-fragments/*.json` counting rows | `coyomap dump --counts` (it reads a FRAGMENT too) |
| a listing of ids / names / sources | `coyomap dump --legend`, `--id`, `--record`, `--edges`, `--members` |
| a tally of `true`/`false` across the verdict files | `coyomap grounding report` — the hand tally cannot tell a tie from a stated `unverifiable` |
| an append into an extras heading | `coyomap record --heading … --line …` |
| **deleting or correcting a recorded line** | `coyomap record --remove "<prefix>"` / `--replace "<prefix>"` — a python splice of `extras.json` takes the heading with it when the line is the last one |
| **a batch of recorded lines** | `coyomap record --lines-from <file\|->` — one process, one write, every line shape-checked before any of them lands |
| **which headings may carry a comma list of ids** | `coyomap record --headings` — five of them key on free text and silence NOTHING when merged; the merged form is right only for the other six |
| a rewrite of a rule's / entity's / **a flow step's** own TEXT | `coyomap fix row --fragments .coyomap/build-fragments --id <ID> --set-<field> <text>` — it edits the OWNING FRAGMENT, so the edit survives re-assembly. It reaches ANY row with an id, `happy_path` steps included: `--set-why`, `--set-confidence`, `--set-risk` all work |
| **TWO OR MORE row rewrites** | `coyomap fix rows --fragments .coyomap/build-fragments --edits <file\|->` — a JSON list of `{"id"\|"edge", "set", "set_json"}`. One process, one write, all-or-nothing, every fault reported at once. One build spent twelve consecutive turns on 37 single `fix row` calls plus 8 identical hand edits |
| **an arrow's VERB** | `coyomap fix rows` with `{"edge": "C12:emits:C30", "set": {"verb": "queues"}}` — writing `verb` MOVES the edge, because an edge's identity is its triple, so a move onto a triple that already exists is refused as the merge it is |
| a corrected anchor | `coyomap fix apply-drift --to-reconcile` |
| a duplicate edge or relation resolved | `coyomap fix dedup-edge` / `dedup-relation --to-reconcile` |
| a before/after comparison of two maps | `coyomap diff <old> <new>` |
| **which boxes a code change touches** | `coyomap impact --map <map> [--base <ref>] [--target <ref>] [--json]` — the map's code links projected on the diff, never a hand-walk of the files |
| **code links whose lines only shifted** | `coyomap reanchor --map <map> [--to <ref>] --write` — git's line mapping; a hand-written appendix of 242 moves was the measured case |
| **the change log of an update** | `coyomap changes lint / render / apply / check` — see `method/change-impact.md`; `apply` is the one writer, `check` the gate |

A hand script over `project-map.json` is also how a build ends up reading a field the schema
renamed, and how it ends up editing the ASSEMBLED map — which the next `assemble` rebuilds from the
fragments, discarding the edit without a word.

**Read the project's own docs.** Before drafting the behavioral layer, read what the project says
about itself — `README`, `docs/`, `CONTRIBUTING`, a `CHANGELOG`, package/manifest descriptions, and
any architecture or design notes. These are the primary source for the parts the code does not spell
out: the **Goal**, the **Roles**, and which **Use cases** matter most — the headline features and
intended workflows a maintainer documents are usually the primary use cases, so rank by them. Treat
docs as **intent, not ground truth**: they go stale and oversell, so anything you take from them
stays **inferred** until the code confirms it, and when docs and code disagree, the code wins (note
the drift). Where the docs are silent, infer from naming/structure and mark inferred — don't assert a
confidently-wrong purpose.

**Confidence by layer.** Structure (components, entry points, data) reads reliably from
source — mostly **verified**. Goal/Roles/intent often are NOT in the code (they live in
README/docs/the maintainer's head) — infer from naming/structure, mark **inferred**, and
ask rather than assert a confidently-wrong purpose. A use case's `Trigger → Outcome` sits in
between: the trigger traces from code, but the "user sees" register sometimes needs the running
app, not just code.

**Build order (internal) ≠ present order.** Build bottom-up so each table's inputs exist
first: T3 → harvest T4, T2, T5 (a full sweep — also the completeness checklist that
catches side doors: after the front-door routes/CLI/callbacks, do a **second pass for
self-starting entry points** — anything that runs with no caller: scheduled/cron jobs,
`while True`/interval loops, `asyncio.create_task`/background workers/threads, queue & stream
**consumers** (`.consume`/`.subscribe`/poll), boot/**startup** hooks (`on_event('startup')`,
lifespan, `atexit`), and OS **signal** handlers. Tag each entry point `activation` (self|external);
a long-running service with **zero** self-starting entry points is a red flag — assert why, don't
leave the list front-doors-only) → synthesize T1 → **cluster components into Subsystems** (large maps —
two axes, one per altitude: the **top 1–2 levels group by product area** — what the system *does*, read
from use-case / Happy-Path affinity, so the first screen describes the product; a tech-tier-only root
(`Backend` / `Frontend`, or by-language) is an anti-pattern — that axis belongs in a group's name or a
lower tier, not the top cut. **Leaf grouping stays directory-first**, then dependency/behavioral
cohesion; minimize inter-group edges *at the leaf/sibling level only* — a product-area top level
legitimately has many cross-group edges, so never judge the top cut by edge counts; mark
directory-derived = verified, cohesion-derived = inferred — a cross-directory product-area group has no
single directory home, so it simply **omits `source`**, never fabricates one) → **cluster entities into Subdomains**
(large domain models: the same recipe on the entity graph — by `SOURCE` directory first, then
`RELATIONS` cohesion) → **group T2 + T4 into T2b interfaces** (the surfaces only — their inputs
T2 and T4 both exist by here, and the trace is their CONSUMER, so they must precede it) →
trace T6 + edge list, **dooring each flow as it is written** (**including the `C→E` edges**: which
component persists/writes/reads each entity) → **re-balance the grouping against the traced edges** (the
grouping was cut edge-blind — run `coyomap balance`, fix or justify each finding; Phase 3.5 in
parallel mode) → **measure test completeness against the finished inventory**
(the last structural step — it reads the assembled nodes + flows: use cases, T4 entry points, T5
entities, critical-path branches) → **the `Cn → Dn` MIGRATION half of T2b** (the surfaces
themselves were authored before the trace, four steps up) —
the LEAD's job. **AUTHOR THE SURFACES BEFORE THE TRACE, and do the migration after it.** T2b used to
sit entirely at the end, on the reasoning that it needs the TRACED FLOWS for its consumer. Only half
of it does. Authoring a surface needs T2 and T4 and nothing else, and both exist well before the
trace; it is the `Cn → Dn` MIGRATION that needs flows to migrate. Leaving the whole section to the
end meant every flow was traced door-blind and then rewritten: measured on the 2026-09-01 argus
build, **30 of 31 flows owed an opening and 96 steps owed a door**, and a whole extra four-agent
fan-out was spent putting them in — after the agents that wrote those steps were gone. With the
surfaces authored first, the trace fan-out is handed the `In` rows and doors its own steps as it
writes them, which is the phase that knows what each step is actually doing.
So: author the outside-edge rows here, `ways_in` and `deps[].interfaces` travel
through `reconcile` (their `EPn`/`In` ids are minted at assembly, exactly like a use case's
`entry_points`), and every external-group dep is decided one way or the other.
**Author `kind` with the row**, in the same pass, from the eleven seeds — it is a fact about the
surface you have just named, not a later tidy-up, and nothing derives it. Who is on the far side is
DERIVED from the flows and must never be written by hand.
**Every flow AND every sub-flow does ALL FOUR halves of the doors rule** — shared machinery is swept
under its own id, and one undoored step there is drawn in every story that rides it. **Halves 1–3
belong to the TRACE, written with the steps; half 4 is the lead's, after the trace.** A trace agent
that has the `In` rows doors its own arrival, its own hand-off and its own mid-story crossings while
it still knows what each step does — compose the doors half INTO its trace brief with
`coyomap contract trace --from-slots <slots-dir> --out-dir <briefs-dir> --append doors`.
Half 4 stays with the lead because a `Cn → Dn` step can only migrate to a surface once the flows
exist. When a build reaches this point with flows already traced door-blind — a rebuild of an older
map, or a trace that skipped it — retrofit them here, which is what this step used to be.
Skipping it is the failure the gates below now catch: (1) OPEN each flow at its door, `Rn → In` then
`In → Cn`, for every use case whose ways in belong to a surface; (2) CLOSE each flow whose last step
delivers to an actor, `Cn → In` then `In → Rn`, and draw that out-door even when it is the same
surface the flow opened at; (3) DOOR EVERY OTHER CROSSING TOO — a preview, a question, an answer in
the middle of the story crosses exactly like the two ends, and `Rn → Cn` / `Cn → Rn` is never the
finished shape anywhere in a flow; (4) MIGRATE each `Cn → Dn` step whose dep stands on a surface to
`Cn → In`. A build
that authors the surfaces and stops leaves a map that can SAY what its outside edge is while no story
ever goes through a door — measured on the first real build to author the section: 12 surfaces, 517
steps, zero doors, 5 migrations owed, and every one of its 42 flows owing both an opening and, for 27
of them, a closing.
**Schedule a section by its CONSUMERS as well as its inputs.** T2b was first placed by its inputs
alone, and its consumer — the flows — was written before it and never revisited. Moving it to the
END fixed that and created the mirror of it: the section now sat behind its own consumer, so every
flow was traced without it and rewritten afterwards. The rule is not "early" or "late" but SPLIT AT
THE CONSUMER — the half the flows consume goes before them, the half that consumes the flows goes
after. **No fan-out worker authors this** — a harvest agent sees one slice and cannot
group a surface, and the first build after T2b shipped proved it: the dependency agent correctly
refused, wrote a note saying the field was the lead's, and the lead never came back because no step
in this order sent it. Nodes (T4/T5/T2)
before the edges/flows that connect them. **Present** top-down (T1–T3 first). The "Depends on"
columns and relationship rows harden last (they need tracing) — keep them inferred until
traced. Drilling can correct an inferred upper row; upper tables get more accurate as the
reader drills.

**Pre-index (structural input).** LAUNCH it whenever you like — backgrounding it before the
behavioral draft is strictly better use of the wait. What must not happen before the draft exists is
READING it: GR1 guards the judgement, not the subprocess, and a build that read the rule as a ban on
launching serialised itself for no gain.

On a non-trivial repo, don't choose altitude from a *count* ("65 plugins, too many")
or from maintainer diagrams alone — that is how a heavy area silently collapses into one box.
First draft the behavioral layer (Goal → Glossary → Roles → Use cases → Happy-Path skeleton),
**then** run the pre-index and let it *size and locate* while you keep *naming and judging*:

```
.venv/bin/coyomap preindex --root <repo>       # writes .coyomap/preindex.json (committed with the map)
```

It returns, for the whole tree: a **weight map** (LOC + file count + git churn per directory), a
**symbol index** (`class/func → file:line + kind`, with an `ambiguous` list when a name is defined
in several places), and — when you pass `--pairs` a `{component: [paths]}` map — a lower-bound
**import-edge advisory** between components you have *already named*. Use it like this:

- **Weight is a hint to where to look, never a decision.** A directory carrying a large share of
  the tree's mass *and* split into many sibling sub-units (e.g. `plugins/` with dozens of
  subdirs) is a **drill candidate** — promote it to a subsystem and map its units, don't fold it
  into one component. But a heavy *generated* dir still collapses, and a tiny *auth gate* still
  gets promoted — the number sets attention, your judgement sets altitude.
- **Reconcile every item; never paste it in.** The pre-index is input you accept / reject /
  abstract with a reason — it is not rows for the map. The behavioral layer and the subsystem
  names stay yours.
- **Treat what it could not parse as UNKNOWN, not empty.** Its `coverage` block reports the files
  it skipped and the languages without symbol data (symbols are deep for Python; other languages
  need the tree-sitter pack). An unparsed region is a region you still owe a read.

**Code the map is not meant to describe — `.coyomap/.ignore`.** A repo may commit code that is
genuinely outside the product: a fixture tree built to exercise the tooling, a vendored copy git
tracks, a scratch area. `.gitignore` cannot say it (the files are meant to be committed), so the repo
declares it once next to the map, in gitignore-like patterns:

Write it to `.coyomap/.ignore`. **A `#` opens a comment only at the START of a line** — the same rule
gitignore uses — so a comment goes on its own line above the pattern it explains. `pattern  # why` is
ONE literal pattern containing spaces; it can never match a real path, and `validate` reports the
line as unusable and drops it (write `\#` if you need a literal `#` in a pattern):

```
# the trap fixture — a wildcard-free pattern covers everything beneath it
trapdoor/
# * stays inside one segment; ** spans segments
generated/**
# ! negates; the LAST matching line wins
!generated/hand_written.py
```

Everything that measures the tree honours it — the weight tree, the component expectation E, and
`validate --check-coverage`. **Do not confuse it with a `Coverage exceptions` heading.** They answer
different questions and are not interchangeable:

| | says | use when |
|---|---|---|
| `Coverage exceptions` (extras) | *mapped, deliberately coarse — stop warning* | a real part of the product folded into one box |
| `.coyomap/.ignore` | *not part of the analysed tree at all* | code the map is not meant to describe |

**Read the disclosure it prints; do not write patterns to quiet a warning.** Every coverage check
here re-measures the repo independently of the pre-index (GR4) precisely so a map cannot look
complete just because generation said so. An ignore file is the ONE input both sides read, so an
over-broad pattern hides a real gap from the very check that exists to find gaps — the
"advisory waved through" failure, one level down. That is why `preindex --report` names the patterns
and `validate` always emits an advisory saying how many files went and on what rules. When you did
not author the file, reconcile that advisory like any other: confirm the patterns still describe code
the map is not meant to cover.

**Component granularity — the leaf rule (what "one component" means).** One component ≈ one
module-/folder-/deployable-sized unit — roughly a directory of **≤ ~10 source files / ≤ ~3 kLOC**
with one purpose. At each source folder decide: **component-shaped → stop** (it is a leaf; its
internal files and subdirs stay abstracted — GR6) vs **subsystem-shaped → recurse** (promote it to a
subsystem and map its units). An oversized *flat* folder (no subdirs) splits into its cohesive file
groups instead of becoming one box. Nesting is the **output** of those decisions — how deep you group
leaves into subsystems is free; what this rule pins is the **leaf decision only**. The pre-index
computes the matching **expected component count E** deterministically from the code tree (same caps;
vendored/generated, docs/config and test trees excluded), whole-repo and per-slice, with a generous
**±40% band** — the `granularity` block in `preindex.json`. E derives from the code alone, so it is
advice you reconcile like any pre-index signal (GR2): landing far **under** the band means you folded
subsystem-shaped dirs into single components — make them subsystems and recurse; far **over** means
you split module-sized units too fine. `validate --check-coverage` and the eval **re-compute E from
the tree independently** (GR4) and nudge when the map's component count leaves the band — the nudge
is advisory; a justified exception stays a judgement call.

**Diagram balance — the fan-out rule (what "one readable screen" means).** The leaf rule sizes the
*boxes*; this rule sizes the *screens*. Every rendered diagram shows a node's **immediate children**
(the root shows the top-level subsystems; a subsystem card shows its child subsystems + member
components), so each screen should carry **5±2 boxes** — advisory band **[3, 9]**. The arithmetic
follows: N leaves at fan-out F need ≈ log_F(N) grouping levels (122 components at F≈5 want ~3
levels, not 2). Two named anti-patterns: the **sparse tech-tier root** (a 2-box `Backend`/`Frontend`
top screen tells the reader the tech stack, not the product — sparseness is an anti-pattern *at the
root only*; a mid-tree 2-child subsystem is normal) and the **single-child subsystem** (a wrapper
level pulling no weight — inline it or grow it). One exemption: a **homogeneous family** — a dense
screen of same-kind siblings (11 repositories, 14 plugins) sharing a directory or a name suffix —
reads fine as a list up to ~15. `coyomap validate` warns (always-on, advisory) outside [3, 12];
`coyomap balance` shows the full per-diagram picture (including the 10–12 soft tier), the
inter-subsystem edge matrix, and deterministic split proposals for over-dense screens — proposals
are **starting points for judgment, not ready-to-apply** (on list-shaped or star-shaped screens it
says so instead of proposing noise). A durably justified exception is recorded in the model's
`extras` under the heading **"Balance exceptions"** and silences the matching advisory — the heading
accepts four id families, each scoping one advisory: a diagram id (`root`, `S7`, …) silences its
fan-out warning; a `UCn`/`SFn` id silences that flow's **granularity family** — both the step-count
band (over AND under) and the fused-goal name smell, which are two readings of one question about
one element; a `Cn` id silences its promote-to-subsystem altitude nudge; the literal
**`granularity`** silences the component-count-vs-E advisory (record it with the why when the
altitude decision is conscious); the literal **`entity-flows`** silences the no-entity-in-any-flow
canary; the `runs_in` placement family has FIVE scoped literals, one per finding group —
**`runs-in/quality`** (unit naming, formula-filled `runs_in`, unlinked units, ambiguous thread
hosts, variant tagging), **`runs-in/unlinked`** (units enumerated but nothing links code to them —
code that truly runs as one unit), **`runs-in/unplaced`** (most components unplaced across the
enumerated units), **`runs-in/entry-hosts`** (self-started entry points left 'Unplaced') and
**`runs-in/messaging`** (a channel no participant's `runs_in` can place). A BARE **`runs-in`**
silences nothing and says so — a family-wide literal switches off five findings on the strength of a
justification about one; the literal **`isolated`** silences the components-wired-to-nothing canary
(see below); the literal **`channel-ends`** silences the one-sided-channel advisory (a channel whose
far end genuinely lives outside the mapped repo); the literal **`channel-payload`** silences the
no-channel-names-a-payload canary (channels that really are untyped); the literal
**`entity-relations`** silences the isolated-entities advisory (a domain whose cards legitimately
relate to nothing — an event log, a settings bag). Never reword prose to dodge a heuristic — record
the exception instead.

Every literal is read **line-leading**, followed by a separator (`:`, `(`, an em/en dash, or a
spaced ` - `) or nothing else on the line — `channel-ends: the consumers are all third-party` — so
a sentence that merely uses the word never silences anything, and a compound that only *starts*
with a literal (`store-front redesign: …`) is not a record either. Element **ids** (`S7`, `UC5`,
`C18`, `root`) are not words, so those still read anywhere in the body: `SF40, SF41: <why>` records
both. And every literal is scoped to its own advisory: recording `isolated` (components) does not quiet `entity-relations`
(entity cards), and `messaging` (no nameable channels at all) does not quiet `channel-payload`
(nameable channels carrying no domain type).

**One escape is still deliberately family-wide, and it reports what it swallowed.** A `UCn`/`SFn` id
covers both granularity signals for its element — one decision, recorded once — so `validate` prints
a line naming the **count** and the **groups** it suppressed: `1 granularity advisory/advisories
suppressed by recorded flow/sub-flow id(s): SF20 (the fused-goal name smell)`. The `runs_in` family
is NOT a second one: its five scoped literals each silence exactly their own group and are reported
the same way (`1 deployment advisory/advisories suppressed by recorded scoped exception(s) …
(`runs-in/quality`)`). Scoping them was the fix for exactly the risk this paragraph describes — the
recorded *why* is usually about a single finding, and a family-wide literal silences the rest. The
line fires on the FIRST suppression, not only on the second — a silence you cannot see is
indistinguishable from having no findings. Neither line can itself be silenced. Read it: if the why
you wrote covered only one of the listed groups, re-read the rest by validating a copy with the
record removed.

**Wire what the prose claims.** `validate` emits one aggregated advisory for components carrying
**no backbone edge and no `messaging` role** — code the model shows connected to nothing. Every view
walks edges and channels (the subsystem arrows, the change-impact ripple, the Deployment view's
process→process topology), so such a component is drawn isolated *however well its `Purpose`
describes what it talks to*: a `Purpose` saying a component "pushes their events to the same broker"
still draws no arrow, because prose is not an edge. Fix it by authoring the edge or adding the
component as a channel publisher/consumer — **never** by having a view infer topology from prose.
Record the literal `isolated` for code that genuinely stands alone. The contract that keeps balance
safe: **balance never gates and only ever re-groups** — grouping is a free, view-only choice
(membership on the child, member lists derived), while the **leaf decision is grounded by E and out
of bounds for balance tooling**: no balance finding may merge or split components to hit a number.

**The hand-off — `coyomap preindex --report`; don't reverse-engineer the JSON.** The build run prints
a one-line summary to **stderr** (heaviest top-level dirs, totals, the GR1/GR2 reminders), but that
summary carries only the top-5 dirs and the whole-repo E — while the harvest plan needs the **weight
tree** and the **per-slice E**, which live only inside the JSON. So there is a read command:

```
.venv/bin/coyomap preindex --report --root <repo> [--depth N] [--top N | --dirs a,b,c]   # weight tree + per-dir E + coverage
```

Use it instead of hand-parsing — it reads the file and writes nothing. `preindex --help` is a real
help flag. **`--dirs` prints E for exactly the directories you name**, which is what a harvest plan
asks: the small slices it chose are never in the top-N ranking, and six turns of one build rebuilt
those counts with `git ls-files | awk | uniq -c`.

**Reconcile E with what it is BOUND BY.** The report says whether the file-count ceiling or the LOC
ceiling produced E, plus the median file size. This matters: on a file-per-UI-component frontend the
FILE cap fires long before the LOC cap, so E counts many tiny files as unit-sized mass and lands
well above the honest altitude. Builds routinely disagree with E by 2–4×, and this report is how you
see why. When you build outside the band deliberately, record the literal `granularity` under a
`Balance exceptions` extras heading with the reason — that is a judgement, and it belongs in the
map, not the transcript.

The JSON shape, so you don't have to guess its keys:

```
{ "tool", "root",                       # provenance
  "weight":   { "path", "loc", "file_count", "churn", "lang", "langs",
                "children": [ …same node shape, sorted by loc desc… ] },   # the nested directory tree
  "symbols":  { "by_name": { "<name>": [ { "file", "line", "kind" } … ] }, "ambiguous": [ … ] },
  "imports":  { "mode", "semantics", "pairs": [ … ] },  # ALWAYS present; `pairs` is filled only
                                         # when --pairs {component:[paths]} was given (else empty,
                                         # with a `note` saying so)
  "granularity": { "expected_components", "band": [lo, hi], "bound_by", "median_file_loc",
                   "per_dir": { "<dir>": E … }, "file_cap", "loc_cap" },   # the leaf anchor (rule above)
  "coverage": { "files_counted", "git_available", "tree_sitter_available",
                "languages_seen_without_extractor", "note", … } }          # what it could/couldn't parse
```

This concretises finding **G1** in
[internal/docs/scaling-to-large-codebases.md](internal/docs/scaling-to-large-codebases.md); the
guardrails above are **GR1/GR2/GR3/GR5** there. The validator's `--check-coverage` (below) is the
verification half — it re-measures the tree independently and never reads this JSON (**GR4**).

**Parallel mode covers HARVESTING ONLY (large repos; serial is simpler and just as accurate on small
ones). Verification is NOT part of it — see "After the trace — every build" below, which a serial
build owes in full.** The build order maps to a fan-out workflow: **parallel harvest → barrier
synthesis → parallel trace.**

> **Scope warning.** Phases 3.5 / test completeness / 4 are NOT part of this section, and a serial
> build owes every one of them. Skip them and the map is built and checked by ONE context — the
> precise blind spot Phase 4 exists to break. Serial mode is exempt from *fanning out the harvest*,
> never from *verifying the result*.

- Phase 1 Harvest (fan out, one agent each): T4 entry points, T2 deps, T5 model, T3
  run/build, T0/Roles reader. Parallel harvest also improves completeness. **Launch the whole
  harvest as one concurrent batch** (all agents in a single fan-out), not in waves — the slices are
  disjoint and use pre-allocated ID ranges, so no agent needs another's output first, and they
  return compact rows (not file dumps) so reading them together is cheap.
  - **"One batch" means one MESSAGE: emit all N agent calls as N tool calls in a SINGLE assistant
    turn.** One message keeps the batch atomic: the slices are dispatched from one decision, so a
    late edit cannot reach half of them. The same rule applies to every fan-out below, not just
    harvest. **What it does NOT buy is speed.** Dispatch latency is the model EMITTING the prompt
    text, at roughly 230-320 bytes/s, so it scales with prompt BYTES and not with agent count.
    **So dispatch every contract by POINTER, never by paste — in every fan-out below (harvest,
    trace, rules, skeptics, gap-fill).** A pasted trace contract is ~13 KB times the fan-out, an
    hour of dispatch typing on a large build, where a pointer is three lines; a pasted copy can also
    drift mid-batch while the file cannot. A build has already run its whole harvest on pointer
    briefs, and the L3 scorecard reads a pointer brief correctly (assertion 31 scores the FILE it
    names).

    **Both halves are a command, so neither is typed.** Do not compose a brief and do not edit slots
    by hand:

    ```
    coyomap contract <phase> --slots > <scratch>/slots.json    # every slot, empty; fill the VALUES
    coyomap contract <phase> --fill <scratch>/slots.json \
                             --out <ABSOLUTE scratch path>/<agent-id>.md --brief <agent-id>
    # Re-running for the SAME agent id is REFUSED: a filled contract is that agent's whole
    # brief, so overwriting one rewrites the instructions of something that may still be
    # reading it. Add --force only when you know nothing is.
    ```

    `--fill` REFUSES a slot with no value, a blank value, a value still carrying «guillemets», and a
    key that is no slot of that contract — and it reports every fault in ONE run, so learning three
    missing slots costs one run and not three. It writes nothing when it refuses. An unfilled slot
    is the failure that made this a verb: `«REPO»` reaches the agent as literal text, no gate can
    see it, and the fragment that comes back is well-formed and about the wrong thing.

    `--brief` prints the three lines you SEND — the agent id, the absolute path, one fixed
    sentence. **That printed text is the whole brief.** It is capped at 400 bytes and cannot exceed
    it by construction; the cap has a number because one build typed **159,993 bytes** of brief
    across six fan-outs, at roughly 275 bytes a second — 9.7 minutes spent typing. `--brief`
    refuses a relative `--out` path rather than resolving it: an agent does not share your working
    directory, and a resolved path is the wrong-directory mistake made silently inside a prompt.
  - **Pre-size the slices from the pre-index so no slice becomes the critical path.** The whole
    phase ends when the SLOWEST agent does, so one oversized slice stalls the barrier for everybody.
    The pre-index already counts files/symbols per area — aim for roughly EQUAL estimated work per
    slice, and specifically split the entry-points harvest **by router / surface** on a
    large route surface (per-kind coverage statements merge cleanly; the coverage sweep catches seam
    misses, so splitting costs no completeness).
  - **Resilience: write a DRAFT fragment early, finalize at the end.** An agent that dies mid-run
    (API outage, machine sleep) loses ALL its reading if the fragment only exists at the end. Write
    incremental progress to `<id>.draft.json` and RENAME to `<id>.json` only when complete — the
    draft suffix keeps a half-written file out of the assemble glob (a partial fragment must never
    assemble). Write it as `<id>.draft.json`, NOT `<your-path>.draft.json` — the fragment path
    already ends in `.json`, and a doubled suffix reads as a draft FOREVER: `assemble` skips any
    path ending `.draft.json`, so a fragment left with that name never assembles at all. The RENAME
    is what makes the work land.

    **The rename is the lint's exit, not a separate step: `coyomap lint-fragment --finalize
    <id>.draft.json`.** It renames to `<id>.json` only on a CLEAN lint, refuses a target that
    already exists, and lands all of a batch or none of it. Done by hand the loop was write → lint →
    fix → lint → rename, with nothing connecting the last two, so a rename could follow a lint that
    had failed. A half-landed batch is the quiet failure: a map missing one slice, with every gate
    green.

    The lead probes stalled agents early (a couple of minutes of no
    progress, not a late `ls` sweep) and resumes a dead agent via SendMessage with its draft as the
    continuation point, or relaunches.
  - **Reconcile your slice expectations with E BEFORE launching.** Hand each agent its slice's E
    from the pre-index `granularity.per_dir` — never your own gut numbers. If you deliberately
    deviate (a file-per-class repo where per-dir E under-counts), SUM your slice expectations first:
    when the total sits outside the whole-repo band, record the decision NOW — one line under a
    `Balance exceptions` extras heading containing the literal `granularity` plus the why — not as a
    post-hoc shrug when validate warns. (That recorded token also silences the E advisory, so an
    overridden-but-unrecorded expectation is a drift waved through at every validate.) **Check each
    slice against ITS E, not only the sum.** The recorded-decision rule above fires on the
    whole-repo total, so one slice can run 3× over while the sum stays in band and nothing says a
    word. Where a slice's budget deviates from its E, that is the moment to say why — per slice, not
    per repo.
  - **Never delete draft fragments with a glob while any agent is still running.** `rm -f
    build-fragments/*.draft.json` mid-fan-out destroys the crash-resilience artifact of every agent
    that has not finished. Delete a draft by NAME, after its final fragment exists.
  - **Waiting for the batch (every fan-out phase):** after launching, **wait on the agents'
    completion notifications** — do NOT poll the filesystem with `ls` (a not-ready file reads as an
    error and burns turns). If you must block on a condition, use the **`Monitor` tool with an
    until-condition** — **not** a `sleep` / `until … sleep …` loop, foreground OR backgrounded. A
    backgrounded waiter is no exemption: `until ls …; sleep 45` breaks the `ls` ban whichever way it
    is launched. **`ListAgents` counts too**: polling it to count running agents is cheap, but it is
    the same shape — the barrier already tells you when it closes, and a turn spent asking is a
    turn. (`Monitor` is a deferred tool — run `ToolSearch select:Monitor` once to load its schema
    before the first call, or that first call fails with an `InputValidationError`.) Hand every
    agent an **absolute** fragment output path (`<repo-root>/.coyomap/build-fragments/<id>.json`) so
    it can never land in a subdirectory; `assemble` warns about any fragment left in
    `build-fragments/` that you did not pass in. **The wait itself is a TEXT turn — emit no tool
    call at all.** A keep-alive `echo .` yields the turn no better than ending on text, and it costs
    a full round trip each time; measured waste has run to **22 % of a build's tool calls**. L3
    assertion 10 counts any no-op turn, not just an `ls`. **One barrier means ONE `Monitor`**: stop
    the previous one before starting another, or its events interleave with the new one's and with
    the agents' own completion notifications — three streams for one wait. And the `Monitor`
    **command itself must not be an `ls` poll**: wrapping `for i in $(seq 1 240) … sleep 20` in
    `Monitor` satisfies "use the Monitor tool" in letter while reproducing the exact poll this
    paragraph bans.
    **What the text turn should CARRY.** Emitting no tool call is the rule; saying nothing useful is
    not the point of it. When a returning agent hands you something actionable — a refutation, a
    contradiction between two slices, a lint failure it could not fix — the acknowledgement turn is
    where you write down what you will do with it, and the NEXT turn that has work available is
    where you do it. On one build the lead named a refuted edge at the barrier and did not open the
    file for eighteen turns; every verdict file it needed was already on disk. Verify a refutation
    when it arrives, not when the barrier closes.
  - **Shared state goes in the CONTRACT, never in a per-slice option.** Anything every agent in a
    fan-out must know — the id legend, the sub-flow catalogue, the "do not re-author these edges"
    list — belongs in the copied contract that all of them read. A build whose slice generator made
    the shared-machinery block an opt-in argument passed it to 12 of 14 slices and omitted it from
    two, one of them the slice its own comment called the heaviest in the build. That cost a repair
    round on one slice; **the other was never repaired and its omission shipped into the map.** A
    block that is optional per slice is a block that will be missing from one.
  - **Dispatch the known-longest slice FIRST, in every fan-out.** Launch order is the one lever you
    have over when the barrier closes: a straggler dispatched last holds it for its whole runtime.
    T5 and the entry-points slice are the reliably heaviest in Phase 1; in Phase 3 it is whichever use
    case owns the most sub-flows and the widest "where to look" list. Send those first, the small
    ones last. (L3 assertion 16 watches this.)

    **Order by expected MINUTES, not by item count.** They are not the same number: per-item cost
    varies enough that the batch with the most items is often not the longest. Where a per-item cost
    is known to vary — state-machine and lifecycle work is the reliably expensive kind — weight by
    that, not by rows. Treat it as a tie-breaker rather than a formula.

    **And size the fan-out to the harness's concurrency cap** (~20 agents in one batch, measured).
    Agents over the cap are REJECTED and have to be re-sent, and a bumped slice then closes the
    barrier long after its siblings — a tail that is delay, not work. Merge to fit the cap, or plan
    a deliberate second wave.

    **Order by MEASURED minutes when there are any: `coyomap timings order --phase <phase>`.** The
    paragraph above asks you to guess which slice is longest, and a guess is what it stays until
    somebody writes the answer down. At each barrier, record what the batch actually took —
    `coyomap timings record --phase <phase> --from-agents --slice "<name>" …`, which reads each
    slice's minutes off its own agent transcript so nothing is hand-timed (name each slice as its
    pointer prompt was sent) — and the NEXT build orders from that instead of from
    T5-and-entry-points folklore. `order` prints longest-first and
    says plainly when it has no record yet, so a first build is not blocked waiting for one. It is a
    second-build lever, which is why the recording half is not optional.

    **What launch order is actually worth: SECONDS, not minutes.** This paragraph once priced it at
    "up to 7.7 minutes", and that number was the STRAGGLER's runtime, not the cost of dispatching it
    late. Measured on the 2026-09-01 argus build, the whole dispatch stagger — the gap between the
    first and last agent of one batch starting — is **12.6 s for 9 agents, 20.7 s for 13, 34.8 s for
    19**. That is the entire ceiling on what reordering can win, because every agent in a batch is
    launched in one message and they all run at once; ordering changes who starts 12 seconds sooner,
    not who finishes first. Straggler waste over the same build was **17.5 minutes** — eighty times
    the stagger — and reordering cannot touch a second of it, because the slowest slice holds the
    barrier whenever it is launched.

    **So the lever is slice SIZING, not slice ORDER.** A slice that takes twice as long as its
    siblings is the whole cost; cut it smaller, or merge the small ones, and the barrier closes
    earlier. Keep recording the minutes — that is what tells you WHICH slice to resize — and keep
    ordering longest-first, since it is free. Just do not spend judgement on the order: `cost` now
    prints the stagger beside the straggler waste, so the two are read together.

  - **Never fan out to ONE agent.** A fan-out of one has every cost of a helper and none of the
    parallelism: the lead writes a brief, waits at a barrier, and reads a fragment, to get work it
    could have finished in the turns it spent waiting. On the large build the test-completeness
    table went out as a single agent and held the barrier for **7.4 minutes**. When a phase comes
    down to one slice, the lead does it. When it comes down to two small ones, that is the signal to
    MERGE them and still do it in the lead — not to send one agent. The rule is about the count at
    DISPATCH, not about the phase: a phase whose slices merge down to one has stopped being a
    fan-out, and calling it one does not make it parallel.
  - **Exactly one agent owns T5, in every fan-out mode — non-optional.** The T5 model is a single
    whole-domain slice: one dedicated agent reads the domain/model layer across the repo and returns
    **per-entity cards with FIELDS *and* RELATIONS** (the `E↔E` class diagram). **The owner's brief
    is the filled harvest contract PLUS the T5 addendum** — add `--append harvest-t5` to that one
    agent's fill, never a `>>` (which shipped the T5 brief with `«COYOMAP_HOME»` unfilled on the
    2026-09-13 build); the addendum reaches the owner ALONE, and the shared contract carries only the
    sentence forbidding everyone else, so 13 agents no longer read the spec of a job they must not
    do. This holds even when
    the rest of the harvest is sliced **by directory or by subsystem** for a large repo: the
    directory/subsystem-sliced agents return their **components / entry-points only** (Phase 1 returns
    nodes; edges are Phase 3) and must **not** absorb (or split up) the T5 slice, and no slice may
    silently drop it. Skipping the
    dedicated T5 owner is the thin-domain regression — the entity graph then gets backfilled late as
    an afterthought and comes out sparse. **Anti-pattern:** do **not** collapse T5 into an "entities
    touched" list or a bag of `C→E` edges — those record which component uses an entity, not how the
    entities relate; the `E↔E` RELATIONS are the domain backbone and only the T5 owner authors them.
    (`--check-coverage` independently flags a sparse / under-harvested domain model — see below.)
    - **The T5 owner needs the deps legend to fill `store.dep` — sequence or inject it.** The
      structured store's `dep` is a D-id, and a T5 agent launched in parallel with the deps harvest
      has no D-id universe — it then ships `dep: null` on every entity, silently disabling the
      persistence-coverage rule. Either run the T2 deps slice first and inject its
      datastore/messaging ids into the T5 prompt (`D1=MongoDB, D2=Redis…`), or have synthesis
      BACKFILL `store.dep` from the assembled deps (a `--reconcile` set). The "container but no dep"
      validate advisory is the backstop, not the plan.
    - **Author `states` where the code implements a lifecycle** — an entity with a status
      enum/constants (a subscription's states) gets a `states` machine on its card; a component
      whose purpose lists phases ("5-phase: disabled/deferred/connecting/live/failed") gets one on
      the component. A lifecycle left in purpose prose is unqueryable and rots first. **But author
      it ONLY from a declared state list, and cite THAT line.** A `states` machine is the one claim
      with no per-state anchor, so it is the easiest thing in the map to invent — and the most
      invented, in two recurring shapes: states lifted from docstring PROSE, and a start state
      bolted onto an otherwise-real enum. The `source` must point at the **enum / constants /
      dispatch block that declares the states**, never a docstring or a class header, and every
      state name must be a name that block actually contains. `validate --check-sources` now reports
      state names missing from the cited file — if you cannot cite a declaration, the lifecycle is
      prose, so don't author it.
    - **Large domain models (many entities) — shard the RELATIONS pass, never skip it.** One agent
      can read ~40 entities and author a complete `E↔E` graph; on a 150–200-entity domain it will
      under-author relations and the graph comes out sparse. **The symptom shows up far below that
      threshold, so measure it instead of guessing.** Count the isolated entities after the T5
      fragment lands; if the share is material, shard the relations pass or re-ping the slice, and
      if you carry it, record the count and the why. When the entity count is high, the single T5
      owner still owns the slice but MAY fan the relations pass out **by subdomain** (each sub-agent
      relates the entities within one subdomain + names cross-subdomain targets), then merges. The
      invariant is coverage, not headcount: every entity gets its relations authored. `validate
      --check-coverage`'s isolated-entity count is the check (it is threshold-gated — silent below 5
      entities, below 3 isolated, or at/under 20% isolated — and the plain `validate` never prints
      it).
- Phase 2 Synthesize (barrier, one agent): T1 clusters/dedups all harvest outputs, and (large maps)
  assigns Subsystems — a global graph cut, so it stays at the non-delegated barrier. **Synthesis is
  the final-ID authority.** **Only the dedup/renumber step is the hard barrier — overlap the rest.**
  No trace launches before dedup completes (a trace referencing an id that dedup then renumbers is
  the dangling-ref class this barrier exists to prevent — do not trade that for minutes). But dedup
  itself is fast; the SLOW synthesis work carries no id risk and should run concurrently once dedup
  is done: fan out any remaining **deployment/ops backfill** WHILE the lead authors the reconcile
  assignments (subsystem/subdomain/runs_in/bucket). Authoring first leaves every agent idle for as
  long as the authoring takes, and the backfill then runs serially after the traces. (The
  **test-completeness agent is NOT part of this step**: its inventory includes the failure paths the
  flows narrate, so it launches the moment the traced map is assembled — Phase 3 below says when —
  and before the T7 rules and the Phase 4 skeptics, never after them.) **Treat this as a launch
  STEP, not advice** — it is step 1 of synthesis, before you author a single rule:

  ```
  1. dispatch the deployment/ops backfill agents                          <- FIRST, if you dispatch
  2. THEN author the reconcile assignments while they run
  3. THEN author the T2b SURFACES, before any trace launches
  ```

  **Step 1 says FIRST, not ALWAYS, and the two rules do not fight.** *Never fan out to ONE agent*
  above is about WHETHER to dispatch; this is about WHEN, once you have decided to. So: if the
  backfill work comes down to one slice, the lead does it and there is no step 1 — that is the other
  rule, unchanged. If it is two or more slices, they go out BEFORE you start authoring, because
  authoring first leaves them idle for as long as the authoring takes. The two sentences read as
  competing absolutes for as long as one said "always"; only the ordering half was ever meant.

  Dispatch those agents before you start authoring.

  **Step 3 is the outside edge, and it belongs HERE, not at the end.** Group T2 + T4 into the `In`
  rows, author each surface's `kind` with the row, and let `ways_in` / `deps[].interfaces` travel
  through `reconcile` like a use case's `entry_points` — their ids are minted at assembly. Only the
  `Cn → Dn` MIGRATION waits for the trace, because it needs flows to migrate. The reason is the
  consumer: the trace agents door their own steps, and they cannot do that against surfaces that do
  not exist yet. Left to the end, this section was written behind its own consumer and every flow
  was traced door-blind — measured on the 2026-09-01 argus build, **30 of 31 flows owed an opening
  and 96 steps owed a door**, and a whole extra four-agent wave went on the retrofit, after the
  agents that wrote those steps were gone. Compose the doors half into each trace brief with
  `--append doors`, and fill its `«SURFACES»` with the `In` rows and their `ways_in`. **Never append
  a contract with `>>`**: the two slot sets do not coincide, `>>` walks around every check `--fill`
  makes, and 9 of 10 trace briefs on the 2026-09-13 build reached their agent carrying nine literal
  slot names each — every one of those agents then ran a `lint-fragment --repo «REPO»` that could
  not run.

  **Run every sub-flow name you PRESCRIBE past the naming heuristic before you dispatch it.** A slice
  brief that hands agents `SF20 — Validate and store the token` freezes a fused-goal name into a
  shared id contract: the sub-agents hit the lint warning, correctly refuse to rename (renaming
  breaks the contract), report it in prose, and the same four warnings resurface at the lead's
  `validate` and end up written as exceptions. The lead pays for its own naming twice. Name them the
  way you would name a use case — one goal, no "and" — or expect to record them.

  **Put the gap-fill slice in the SAME batch as the Phase-3 trace fan-out.** Slicing the trace by
  use case structurally guarantees that components off every traced flow get no edges, so the
  gap-fill is predictable, not a surprise: discovering the edgeless set only after the trace agents
  finish costs a serial dispatch, plus rework of anything written too early. Seed that slice from
  the post-synthesis edgeless set, and get its brief from `coyomap contract gapfill` — never by
  mutating a trace slice's filled slots. Harvest agents may use per-slice *provisional* ids; synthesis
  assigns the final canonical ids here. This is the safe place to renumber: Phase 1 produced only
  nodes (no edges yet — those are Phase 3), so the only intra-slice references to fix up are
  `entry_point.component`, `entity.subdomain`, and the `E↔E` `relation.target` / `FK→En` markers.
  Because collisions are resolved before any edge is traced, a range overlap between two harvest
  agents can never reach the backbone; `assemble`'s duplicate-id error remains the loud backstop if
  a stray collision slips through. **Right after synthesis, run `coyomap validate
  --check-coverage`** — add **`--json`** whenever you need the FULL finding lists: the human report
  elides long id lists (`C1, C12, … +8 more`) and clips trigger prose, and `--json` emits every list
  whole, so recovering a hidden id never needs a throwaway script. Its unreferenced-files list is
  the mechanical harvest-completeness sweep (a source file no component claims = a slice-seam gap);
  an improvised spot-script covering one directory misses whatever it does not walk. **This is also
  the front-door verification moment** (the cross-check rule under *Use cases*): T4 now exists, so
  reconcile the drafted use-case list against the harvested **external** entry surface in both
  directions — a use case with no entry point behind its trigger (stale docs), an
  externally-triggered entry point no drafted use case claims (missing use case or dead surface) —
  BEFORE the trace fan-out, so Phase 3 traces the corrected list, not the draft. (The entry-surface
  advisory itself stays quiet until flows exist; during Phase 3 it fires on every not-yet-traced
  surface and **drains as traces land** — a mid-trace wall of these warnings is expected, not a
  defect. Only what survives the full trace is a finding.) **Mint the BLOCKS here too** (`blocks[]`,
  the T7 decision grouping) — same moment and same reason as `CAP`: the post-trace rule fan-out is
  one agent per block, so the blocks and their id ranges have to exist before it starts. Cut them
  from what the product DECIDES, not from what the code is shaped like: an area a product person
  would argue about ("who may cancel an order", "how a plan limit is applied"), 8-12 of them on a
  map this size. A block is a `Group` like a capability, so it carries `name` + `purpose` (the "what
  this area decides" line), and `source` only if the area has one honest home directory — a block
  groups DECISIONS, not code, so the viewer never treats that anchor as a file's owner. `happy_path`
  and `tech` are blocked on it, as they are on a subdomain. Leave `rules[]` empty: it is written after
  the trace, when the flows exist to sweep. **Also assign each component's `subsystem`, each
  entity's `subdomain`, each use case's `capability` and its trigger `entry_points`, each
  component's `runs_in`, and any dep `bucket` fixes here — as a `--reconcile` file, NOT a
  hand-script.** Synthesis owns the finalized ids and has just seen the harvested `deployment[]`
  units, so this is where the grouping and the code↔process link the Deployment view needs get wired
  — no later phase does it, so if synthesis skips it the view ships empty. **The two behavioral
  assignments have no other home.** `CAPn` is minted at synthesis, and `EPn` does not exist until
  `assemble` mints it from the harvested T4 rows — so neither can be written in the behavioral
  fragment, which was authored before either existed. Reconcile is the only mechanism, and it is
  also what makes them survive: a re-assemble re-applies them, where a hand-patch of the built map
  is discarded by the next one. These live in a declarative **`.coyomap/reconcile.json`** (kept
  OUTSIDE `build-fragments/` so the fragment glob does not sweep it) — **generate it with `coyomap
  reconcile`, below; hand-author it only on a map small enough to type.** The shape it produces:
  ```json
  { "set": [ {"ids": ["C1","C2"], "subsystem": "S3"},
             {"ids": ["C40","C41"], "runs_in": ["worker"]},
             {"ids": ["E7"], "subdomain": "SD2"},
             {"ids": ["D5"], "bucket": "Data & storage"} ] }
  ```
  `coyomap assemble <fragments…> --out .coyomap --reconcile .coyomap/reconcile.json` applies it AFTER
  the fragment merge, every time — so a re-assemble never loses the assignments (a bespoke Python patch
  edits the assembled map, which the *next* assemble discards). **`--reconcile` is part of the standard
  build assemble from here on**; an assemble without it silently reverts every assignment (assemble
  prints a note if a `reconcile.json` is present but unpassed). Derive `runs_in` by reading the deploy
  manifests, never a component-id-range formula (see *Deployment & topology*); `validate` warns when
  `deployment[]` units exist but no component sets `runs_in`, and flags a formula-filled `runs_in`.
  Keep fragment argument order stable and author the reconcile ids against the assembled ids (dedup
  survivors are first-occurrence-in-argument-order, so reordering fragments can shift surviving ids).
  - **A dedup decision belongs here too.** `coyomap fix dedup-edge --map .coyomap/project-map.json
    --repo . --accept-suggested --to-reconcile .coyomap/reconcile.json` writes its choices as
    `keep_edges` instead of editing the assembled map. **`--to-reconcile` needs a decision** —
    `--accept-suggested`, or explicit `--keep` tokens after reading the listing (run it without
    `--to-reconcile` to see that listing first). On its own it is refused. Editing the map does not
    survive: the next assemble restores every duplicate the fix removed. A map that cannot be
    rebuilt from its fragments has quietly stopped being generated.
  - **Generate the file — `coyomap reconcile`.** Count IDS, not rules: a file of 25 rules can carry
    187 hand-typed ids, and "25 rules" reads as small. There is deliberately NO hand-authoring
    threshold: a size threshold is what a build reads as permission. The file wants explicit id
    LISTS, and on any real map that is hundreds of ids nobody types correctly. Write RULES against
    the fact you actually know — the source path — and let the tool resolve them into ids. **Point
    it at the FRAGMENTS**: you are mid-build, so the map does not exist yet, and it does not need to
    — `reconcile` merges the fragments through the SAME code path `assemble` does, so it sees the same
    ids and the `(id, source)` pairs the rules match are the same either way. **`EPn` is the one id
    family the tooling mints rather than an agent authoring it, and it is order-independent but NOT
    add-stable**: harvesting a new surface that sorts before an existing one shifts every number after
    it, which re-points a use case at a different front door while the id still resolves. You do not
    have to remember this: `reconcile` WITNESSES each entry point with the anchor it had when the file
    was written — `{"id": "EP1", "source": "orders.py:9"}` — and `assemble` refuses a file whose
    witness no longer matches, naming both anchors. A bare `"EP1"` is still legal and buys no
    protection, so let the tool write the file.
    ```
    .venv/bin/coyomap reconcile --rules rules.json --fragments .coyomap/build-fragments/*.json \
                                --out .coyomap/reconcile.json [--dry-run]
    ```
    (`--map .coyomap/project-map.json` instead, when re-assigning on a map that is already built.
    Mid-build, `--map` is a trap: the reconcile file is an INPUT to `assemble`, and `assemble` is
    what writes the map, so demanding a map first is a circle with no way in. If the command says
    the map is not found, you wanted `--fragments`.)
    ```json
    { "rules": [ {"source_glob": "mee6/plugins/*",     "subsystem": "S12"},
                 {"source_glob": "gateway/**",         "runs_in": ["gateway"]},
                 {"ids": ["E7","E8"],                  "subdomain": "SD2"},
                 {"ids": ["UC1"],                      "entry_points": ["EP3"]} ] }
    ```
    It reports **every rule that matched nothing** instead of silently emitting an empty assignment
    — which is the whole point: a hand-rolled generator reports the assignments it *emitted*, and
    nothing checks those ids against the map. Output is an ordinary reconcile file, so `assemble
    --reconcile` stays the one code path that writes. Later rules win on the same (element, field),
    so a broad rule can be followed by a narrow override.
- Phase 3 Trace (fan out, one agent per use case; large maps may instead fan out one agent per
  subsystem — bounded context — then a non-delegated reconcile traces the cross-subsystem seams).
  **Trace EVERY use case. The target is 100 %.** An untraced use case is indistinguishable from a
  phantom one — the map gives you the same silence for "we ran out of time" and "this feature does
  not exist", and those need opposite responses. Do not reach for a coverage rule that redefines the
  shortfall as correct. Closing a large trace gap costs real tokens — on the order of a tenth of a
  build — and it is still cheaper than a map that cannot say which silence it means. Nor are the
  leftovers cheap: they are usually the CRUD variants, but a variant with no traced sibling is new
  ground, and each trace is its own agent context, so nothing is carried over. Where budget
  genuinely runs out, the shortfall is **reported as debt** (`use_cases_untraced`). **There is
  deliberately NO "recorded as deliberately untraced" escape** — the no-T6-flow advisory is one of
  the few with no way to record it away, because an untraced use case is a claim with nothing behind
  it and the two honest remedies are both cheap: trace it, or drop it. Where a trace would truly
  duplicate a sibling, check whether the two are really ONE use case (the one-actor-one-goal test)
  rather than leaving one untraced. Each trace agent produces its use case's **T6 flow** (the
  ordered `from → to` steps — **including the flow's central entity touches as `C→E` steps**, the
  entity-steps rule under T6) and also records the **`C→E` edges** for the components in its slice —
  the entities they persist/write/read by **direct** use. Steps and edges carry different halves of
  entity usage: the edges are the structural aggregate (every entity a component touches, in any
  scenario); the steps are the behavioral instance (THE entity this scenario is about, at its exact
  line) — the `Used in UC` view and line-level diff impact derive from the steps, so edges alone
  leave the domain model untraceable. This is *additional*: the `C↔C`/`C↔D` edges remain the primary
  output and must stay complete (every dep wired, the component graph not sparse). **Size the trace
  fan-out so no agent becomes the straggler**: heaviness is predictable up front (a slice's use-case
  count × its entry-point/component counts), so an agent carrying too many use cases holds the
  barrier for everybody. Split a heavy slice into two agents at LAUNCH, **always at use-case
  boundaries — never split one use case's flow across agents** (a flow traced by two contexts loses
  coherence; per-agent SF ranges + cross-fragment `--ids build-fragments/` handle any shared
  sub-flow between them).
  **The copyable contract is
  [method/templates/trace-contract.md](method/templates/trace-contract.md)** — hand every trace agent
  a POINTER to its filled copy (the pointer-dispatch rule in Phase 1). **The verb fills it; you
  never edit a contract by hand:** `coyomap contract trace --slots > <slots-dir>/<agent-id>.json`
  per agent — the skeleton says what goes in each slot beside it — then ONE
  `coyomap contract trace --from-slots <slots-dir> --out-dir <briefs-dir> --append doors`, which
  checks every slots file before it writes any brief. A `Read` followed by a `Write` is one keystroke
  from a rewrite, and the verb prints only the agent's half, so the lead-facing header cannot travel
  with it. This was the largest fan-out
  with no contract of its own, and the rules fan-out shows what that costs: composed from memory, it
  told eleven agents to author a field they must never author, which lint treats as blocking.
  Trace-prompt discipline — the LEAD's half only. The agent's half (entity steps, the sub-flow
  shape, sibling sub-flow references, the entity-TYPE rule for `reads`, return-direction steps, the
  three overclaim shapes, the catalog-row rules) lives in the contract itself — read it there, and
  never restate it in a prompt: a restated copy is the one that drifts. What the contract cannot
  know is per-slice, and that is yours:
  - **Prescribe likely sub-flows in the briefs.** The lead can usually see from the use-case list
    which machinery is shared ("UC10 and UC13 walk the same tool-call path — EXTRACT it as a
    sub-flow") — say so explicitly; the duplication detector is the safety net, not the plan. **Do
    NOT blanket-ban sub-flows** ("no subflows" in every trace prompt) — that contradicts this rule
    and forgoes the cross-flow consistency sub-flows buy. Ban them for a genuinely independent flow,
    never as a global default; where machinery repeats across ≥2 flows, prescribe the `SFn`.
  - **Assign each trace agent an `SFn` id range** (SF1–9, SF10–19, …), exactly like the per-agent
    component id ranges, so parallel extractions never collide.
  - **Fill «LEGEND» with a FILE PATH** (`--ids path/to/legend`), never inline contents — a
    whole-map legend overflows the shell arg limit. The legend should list the full id universe
    **including `UC`/`SF`/`HP` ids** (or just pass the assembled `project-map.json`), so a trace
    fragment's flow `uc` values resolve; `lint-fragment` tolerates a legend that omits a whole
    namespace (it can't adjudicate one it doesn't cover), so a reduced element-only legend no longer
    false-flags `uc` — but a complete legend still catches an invented one.
  - **NAME THE OWNER of every `messaging` catalog row in the slice briefs.** Several agents each
    told to record the same channel row will each comply, in their own spelling, and `assemble`
    then hard-fails on the conflict; a fragment that lints clean on its own proves nothing here,
    because a cross-fragment conflict is invisible per fragment by construction. One fragment owns
    each catalog row; the others reference it.

### After the trace — EVERY build (serial included)

The four steps below are **not** parallel-mode-only. They run on every build; parallel mode only
changes how many agents do the work (a serial build still FANS OUT for the T7 rules and for Phase 4
— fresh context is the point, not concurrency). See the scope warning at the top of parallel mode.

- Phase 3.5 Re-balance reconcile (lead, not delegated — runs ONCE, after the trace). The grouping was
  cut at Phase 2 **before any edge existed**, so re-check it now against the real graph: run
  `coyomap balance` and reconcile each finding — apply a Drilling-deeper operation (nest / promote /
  flatten) via a Direct map change, or record a one-line justification under the model's
  `extras` "Balance exceptions" heading. The **sparse-root fix is judgment-only** (no proposal
  machinery exists for it — the product-area-first guidance drives it); the split proposals are
  starting points, not facts. Exit criterion: `coyomap validate` emits no balance warning that is
  neither fixed nor justified. This step is not part of the per-write validate → audit → render
  invariant; maintenance re-surfaces imbalance for free through validate's always-on warnings.
  `finalize` now runs `balance` itself as an INFORMATIONAL leg and records what it found, so a
  skipped Phase 3.5 and a passed one no longer read the same in the report. That leg is a trace,
  not a substitute: it never gates, and it does not reconcile a finding for you.
- **T7 Business logic (fan out, one agent per block — after the trace, it needs the flows to sweep
  against).** The map has a home for DATA (entities), SEQUENCE (flows), STATES (lifecycles) and
  STRUCTURE (components, edges) — and none for the DECISION the code makes, which is exactly the
  part a reader calls "product-specific". Each agent gets ONE block (its `name` + `purpose`), the
  map, and its own `BR` id range (BR1–19, BR20–39, … — one contiguous range per agent, exactly like
  the trace fan-out's `SFn` ranges, because two agents minting `BR7` is a hard `assemble` failure).

  **One block per agent is the rule, and bundling is allowed only when you say what it costs.** A
  build gave four of its five rule agents two or three blocks each (R2 got BLK4+BLK5, R4 got
  BLK6+BLK11+BLK10) and its `BR` ranges stayed contiguous, so nothing failed. What it spent is the
  property the fan-out exists for: fresh context PER BLOCK. An agent holding three blocks reads the
  third through whatever the first two left in its window, which is the same reason Phase 4 uses
  fresh-context skeptics rather than one skeptic with a long list. Bundle when the block count
  exceeds the harness's agent cap, or when two blocks are genuinely one decision area; record the
  bundling and its reason under `Balance exceptions` so the next build can tell a deliberate
  bundle from a lost one.
  **Show the rule SHAPE in the prompt** — a nested `sites[]` is more novel than anything the trace
  agents write, and the sub-flow fan-out learned this the expensive way:

  ```json
  { "rules": [ { "id": "BR1",
                 "name": "<the SHORT title — a few words a reader scans>",
                 "statement": "<ONE decision, product language, naming no component>",
                 "access": false,
                 "risk": "<what is AT STAKE if this decision is wrong or absent>",
                 "confidence": "inferred",
                 "sites": [ { "where": "path/to/file.py:88",
                              "why": "<what this line does FOR the rule>",
                              "no_call_site": false } ] } ] }
  ```

  **`name` is the rule's TITLE** — a few words ("Owner-only cancellation"), the way a use case has a
  name beside its trigger→outcome sentence. It is REQUIRED and schema-enforced: without it a list of
  rules is a wall of prose with nothing to skim, and every breadcrumb truncates one mid-word. Name
  the DECISION, then state it in full in `statement` — a `name` that is just the statement cut short
  is not a title. `access` is `true` when the rule governs WHO MAY DO WHAT; `confidence` is
  `verified` (read in the code) or `inferred` (deduced). **`risk` is REQUIRED on an `access` rule**
  — it is the one thing a `security[]` row carried that a statement, a site and a `why` between them
  cannot say: not what the line does, but what its LIMIT costs. The Security & auth table renders it
  as its own column, and **`lint-fragment` FAILS on an `access` rule that leaves it empty** — as an
  advisory it changed nothing. Those seven keys are the WHOLE authored surface — the full field
  semantics are in `method/model.md`. **`block` is NOT in the fragment** (see below). The agent
  writes `«repo»/.coyomap/build-fragments/«agent-id».json` itself and returns that path plus a
  one-line inventory, under the same rule as every other fragment (never inline it). **`access`
  matters beyond display**: it is what makes a rule part of the auth surface the eval gates on, and
  what the security table folds onto — a rule about who may do what and `access: false` is a
  silently missing security row.

  **One rule = one decision.** Several sites only when it is the SAME claim enforced in several
  places. Two claims joined by "and" are two rules.

  **The sharp test: could a product person have decided otherwise?** "Own connection first, else
  oldest shared" passes. "If the list is empty, return early" does not — that is a mechanical
  detail, and filling the layer with them is how the decision view stops being worth opening.

  **Nothing unsupported.** A rule must be reconstructible from the lines its sites point at, with no
  clause added. The failure shape is a sentence that reads true, sitting under a real anchor that
  shows only half of it. If the second half is real, anchor it too; if you cannot find it, cut the
  clause.

  **Sweeping a rule's sites.** Start from the code the BLOCK is about, not from the rule (a rule's
  components are derived FROM its sites, so "the anchors in the rule's components" is a circle).
  Take the components that own that area with `coyomap dump` (`--members` for a subsystem's members,
  `--record` for one element's stored record — a component's `files`, a use case's flow steps —
  `--edges` for a node's backbone edges), and read the anchors the map ALREADY holds in them: the
  flow-step `where`s, the edge `where`s, the security sources. That is a median ~11 candidates per
  rule on a real map. Read code only where none of them fit. Anchor the TRUE OPERATIVE LINE
  even when a different line would join a flow step: **the step link is a readout, never a target.**
  A site chosen because it lights up a use-case-step row is a false claim about where the decision
  is made, and it is invisible on screen — the row looks better, which is the whole danger.
  `validate` refuses a site that names a whole file, and flags one that points at a definition
  header, an import, a comment or a blank line.

  **A site with no single line is `no_call_site: true` and no `where`** — enforced by construction
  (a type, a schema constraint, a config-wired guard). It is a declared absence, not a gap, and it
  is the honest answer when there is no line to point at. Do not invent one.

  **Fusion is preferred to splitting. Synthetic, not granular.** Report rules-per-block when you are
  done. A block whose rules are nearly all single-site is the signature of a flow-step list wearing
  rule clothing — fuse it. The shape to hold is roughly 10 blocks and ~55 rules on a map of this
  size: near 5 rules per block. A drift toward one rule per anchor is a FAILURE even when every rule
  is verified, because the reader is back to reading the flows.

  **`block` is assigned via `reconcile`, never in the fragment** — `BLK` ids are minted at synthesis
  and a re-synthesis that renumbers them must not silently re-point every rule (the same reason
  `capability` and `entry_points` go through reconcile).

  **Everything else about a rule is DERIVED and there is no field to write it in:** which components
  enforce it, which use-case steps it lands on, which entities it touches, and whether it has been
  swept. Do not describe them in prose either — the views compute them, and a prose copy is a second
  answer that will disagree. If you find yourself wanting a field for one of them, stop: that is the
  design being wrong, not the map.

  Exit criterion: `coyomap lint-fragment` clean per fragment, then at the lead's `validate` the
  **sweep worklist** — anchored flow steps that read like a decision no rule covers — is empty or
  fully recorded under the `Sweep debt` extras heading (`coyomap record --map
  .coyomap/build-fragments/extras.json --heading "Sweep debt" --line "<the step's anchor>: <why>"`
  — name the FRAGMENT, or the next assemble discards the record). **`--line` REPEATS, and
  `--lines-from <file|->` reads a batch** — one process, one write, and every line shape-checked
  before anything is written. Every `record` example in this file used to show exactly one `--line`
  and `--lines-from` appeared nowhere, so a build spawned **40 processes for 40 lines**. `record`
  also SEEDS the extras fragment when the path does not exist yet and prints a note saying so, so
  never `echo '{"extras": []}' >` it first: that is a truncating redirect one later run away from
  wiping a populated file.

  **A step is covered two ways, and the second one is why you never anchor a decoy.** By ANCHOR: a
  site lands on the step's line, or inside the same function. Or STRUCTURALLY: a rule is enforced in
  a component the step NAMES. The second exists because a step's `where` is the CALLER's line
  (`C1 → C2 : checks the owner` anchors where C1 calls C2) while the decision lives inside C2 — a
  different file, where no anchor link can ever exist. Without it, "the worklist is empty" would be
  unreachable by honest anchoring and the only route to a clean `validate` would be a decoy site on
  the step's own line. Anchor the operative line; the worklist will clear.

  **What the worklist proves, and what it does not.** It catches decision-shaped code nothing
  claims. It does NOT prove the sweep was exhaustive: it reads the wording of ANCHORED steps only,
  its vocabulary is a heuristic with known-incomplete recall, and one rule in a component clears
  every decision-sounding step naming that component. Treat an empty worklist as "nothing obvious
  was left", not as "done".
- Test completeness (one agent, dispatched the moment the traced map is assembled — it needs the
  finished inventory AND the flows, whose failure paths are part of its inventory — and BEFORE the
  T7 rules and the Phase 4 skeptics, so it is never the build's straggler).
  **Get its brief with the verb:** `coyomap contract tests --slots`, fill, `--fill … --out … --brief
  <id>`, and send the pointer — the hand-written brief lost the no-delegation block on one build and
  was the batch straggler on another, written and dispatched last.
  Walk the assembled map (use cases, T4 entry points, T5 entities, failure modes, critical-path
  branches) and for each ask "is there a test that exercises it?", emitting the risk-ranked gap table
  `tests[]` + `tests_note` (the **Test completeness** section above carries the full recipe — don't
  duplicate it). **Read-only by default:** build the table by *reading* tests, mark every row
  **inferred**, and set `tests_note` to state the suite was not run. Running the suite with coverage
  (upgrading rows to **verified**) is the opt-in upgrade described in that section — never run an
  unknown suite by default. The table is always produced; it must never ship empty.
- Phase 4 Adversarial verify (fan out, **fresh context**). After the map validates and `coyomap
  audit` runs (fix any blocking `why:`-ref contradiction; reconcile the read-before-create / actor
  advisories — **fix each, or record it under an `Audit exceptions` extras heading** as
  `<check-name> <Id>: <why>`, e.g. `read-never-created HP12: the token is written off-path by the
  OAuth provider; the Happy Path starts after sign-in`. A recorded line silences exactly one
  `(check, id)` pair — never a family — and `audit` REPORTS what it silenced, plus any line that
  matched nothing), take the audit's **L2 grounding worklist** and disprove it against the code.
  **What the budget buys, decided once (2026-09-09): the behaviour theme on every build; the prose
  surface only when the operator asks.** `--with-behavioural` is passed every build. The read
  fan-out below runs only on instruction: `audit --batches` writes no `prose-N.json` unless
  `--with-prose` is passed, so a build never mints batches it must then delete.

  **With `--with-prose`, the same command also cuts the READ fan-out.** Beside the claims files it writes `prose-N.json`,
  every reader-facing prose field in the map, each batch carrying the instructions with it. Dispatch
  those to a CHEAP model (Haiku is enough; the whole map is roughly 35k tokens, about eight cents)
  and fold what comes back into the audit report as advice. That fan-out judges exactly two of the
  six writing rules — is there a word the reader will not know, and did a short sentence buy its
  shortness by dropping the specific — because the other four are already counted by `validate` and
  the lead has those numbers. **It never gates anything, and two runs may differ**: a model reading
  prose is not the deterministic check the rest of this step is, and a finding that says "this box
  is hard to read" is worth having without being worth blocking on.
  **Each reader writes `verdicts-prose-<N>.json` beside its batch.** The name matters, and it is the
  only thing that records the fan-out happened: `finalize` reads the pair, and says so when batches
  sit there with no verdicts next to them. Four builds in a row wrote batches and dispatched none —
  one of them 459 prose fields across 12 batches, read by nobody — and nothing could tell that from
  a build that dispatched them all, because the batches look identical either way. A build that
  never passes `--with-prose` has no batch files to delete; one that minted them and then decides
  not to dispatch must delete them, because leaving them says a review happened.

  **Write the per-theme batches with the tool, not a hand script:** `coyomap audit <map> --batches
  .coyomap/verify --cap 40` emits one claims file per theme, most-dangerous-first, each claim
  carrying its `anchor` and `detail`; themes with fewer than 5 claims share `claims-small.json`
  (`theme: mixed`), because a 1-claim batch still costs a whole skeptic — the security theme never
  shares. A hand-rolled batcher drops the anchor, and the claims then
  reach the skeptics as a bare `C140 calls C78` while the prompt promised them a `path:line`. (read
  it with `coyomap audit --json` — the machine-readable `{findings, worklist, themes, theme_counts}`
  payload built for this batching step; never regex-parse the human report; the same rule covers the
  model itself — look an id up with **`coyomap dump`** (`--id` resolves kind/name/source/members,
  `--record` the full stored record, `--edges` a node's in/out backbone edges, `--members` a group's
  members — a subsystem, subdomain, capability or block) rather than hand-parsing
  `project-map.json`, which is how a build ends up with a throwaway script that reads a field the
  schema renamed. **`dump` also reads a build FRAGMENT**, so use it during Phases 1-3 too instead of
  scripting over `build-fragments/*.json`. **To see what an edit actually did, keep the map you are
  about to replace and run `coyomap diff <old-map> <new-map>`** — rows added, dropped and changed,
  with the fields that moved. It is the only row-level before/after signal there is: the assemble
  digest is one line, and a count gate cannot see a row moving between two arrays. Its scope is two
  assembles of the SAME work — before and after a `fix`, or one round of edits — never two
  independent builds, which agree on neither numbering nor wording.) **Batch on the payload's own
  `theme`** — every worklist item carries one from a closed, most-dangerous-first set (`security`,
  `rule`, `dep-usage`, `ownership`, `persistence`, `messaging`, `interface`, `lifecycle`, `cadence`,
  `description`,
  `backbone`, `behaviour`)
  — and `behaviour` covers flow titles and step phrases, the flow a reader follows, added by
  `audit --with-behavioural`. **RUN IT.** It is not the default flag, so pass it, and record
  `behavioural: <why not>` under an **"Entry-point coverage"** extras heading if you deliberately
  skip it. `grounding.note` says either way.
  **Why this is now an instruction rather than a suggestion.** It read "turn it on when the budget
  is there" for three consecutive builds and **no build ever turned it on**, so the behavioural half
  of every shipped map carries zero claims: 899 rows on the 2026-09-07 mcpolis map — every use case
  name, every story title, every step phrase, every happy-path step. Three retros filed that as
  "landed but ineffective" without finding the cause, which was not budget at all: the flag's own
  NOTE told every build the record could not hold the result, and kept saying so after that was
  fixed. A soft suggestion produced nothing in three builds, and it was answering a message that was
  wrong.
  **The cost, measured rather than feared.** The worklist roughly doubles — 933 claims to 1787 on
  that map, of which 854 are this theme. The readers that check them cost $69 of a $341 build, so
  the flag adds about a fifth to the bill, not double. Weigh that against the half of the map a
  reader actually reads being the half nobody has ever checked.
  and **`security` holds every `access: true` rule site** as well as the `enforces`/`encrypts`
  edges, so the batch that sorts first really is the access-control batch — send the multi-skeptic
  majority vote there. (A rule site that is NOT an access rule carries `rule`.) `theme_counts` gives
  you each group's size, so the batches fall out of the data instead of being guessed. **Batch by
  theme/risk, don't spawn one sub-agent per claim** — the worklist routinely has 100+ items; group
  the claims into themed skeptics (e.g. security/auth, money, core data-flow, inferred dep-usage),
  one fresh-context skeptic per batch — hand each one a POINTER to its filled copy of
  [method/templates/skeptic-contract.md](method/templates/skeptic-contract.md), the copyable
  contract (the pointer-dispatch rule in Phase 1), rather than composing one from this section.
  **Get every brief with the verb, never by reading and retyping:** `coyomap contract skeptic
  --slots` prints the slot skeleton (leave «BATCH» and «CLAIMS» empty), and `coyomap contract
  skeptic --from-batches .coyomap/verify --fill <slots.json> --out-dir <scratch>/briefs --votes
  security=3` writes one brief per claims file, filling «BATCH» and «CLAIMS» from the file names,
  the voters as `security-1-a/b/c` over `claims-security-1.json`; it skips any brief that already
  exists and prints the pointer prompts to send. Every build so far hand-wrote that loop, with
  `--force` on every brief, and the instruction on its own does not stop this: a `Read` followed by
  a `Write` is one keystroke away from a rewrite, and a verb is not. The verb also prints only the
  agent's half: a build once filled this template with
  one text replacement and sent the WHOLE file, so all ten skeptics read the lead's instructions as
  their own and four were told to open a claims file that does not exist. **The WHOLE `security` theme — every batch of it — gets N skeptics + a majority
  vote, with N ODD and N ≥ 3.** The scope is the theme, never a hand-picked "riskiest" subset: a
  build left to cut its own subset triple-voted 80 of the security theme's 123 claims and
  single-voted the other 43, and 8 of its 10 applied refutations then came from
  single-vote batches. Before spending the budget, weigh what the vote actually bought on that run:
  across 160 redundant rows the three skeptics disagreed on the verdict ZERO times and on the
  evidence anchor once. Unanimity is a real result — it is the only evidence that the
  highest-risk claims are not one agent's blind spot — but it is not discovery, and if the budget
  is tight a second single-vote batch elsewhere finds more.
  **Record the disagreement count every build, in `grounding.note`** — "the three security voters
  disagreed on N verdicts and M evidence anchors across R redundant rows". It costs a sentence and it
  is the only number that can ever settle whether the vote is worth its four agents. Three builds
  have now three-voted an access theme: 160 redundant rows / 0 verdict disagreements / 1 anchor
  disagreement, then 40 claims / 0 / 0, then 100 redundant rows / 0 / 0 — and on the last one all 150
  rows returned an `evidence` string identical to the anchor the claim already carried. That is
  replication, not redundancy (the notes were independently written; none of the 50 triples had two
  identical ones), and it is worth knowing — but it is now three data points saying the same thing,
  and the next decision about this rule should be made on the number rather than on the memory of
  one build. Two skeptics cannot form a majority, and a tie broken by the lead reading
  the code is the build-context blind spot the fresh-context rule exists to break, reintroduced at
  the last step. Give each row a `skeptic` id so two independent agreements are never mistaken for
  one vote counted twice. And note what a tie IS: `grounding write` files it under `unverifiable`,
  which is right for the count and wrong for the reader, so run **`coyomap grounding report`** to
  see ties listed apart from the claims a skeptic actually called unverifiable.
- **Re-verify every REFUTATION against the code before applying it.** A refutation rewrites the map;
  a false one corrupts it silently and no gate can tell the difference. The majority vote is a
  filter, not a verdict: on a live build three of one batch's adverse findings were FALSE, the
  highest-risk claim among them, and all three were caught by the lead's own initiative rather than
  by any step written here. This is that step, and it runs in FRESH CONTEXT too: dispatch ONE
  **closer** agent with only the refuted claims — each with its skeptic's `evidence` and `note` —
  and the repo; never the build reasoning, and never the confirming rows. It opens each
  refutation's file and returns **uphold / reject** per refutation with the line it read.
  **Build the brief with `coyomap contract closer --from-verdicts <verify-dir> --map <map>`; do not
  compose it from this paragraph and do not hand-build the claims block.** A refuted claim is a claim
  about a MAP ROW, and that verb pastes each claim's own `dump --id`, `--record` and `--edges` output
  under it, for every claim kind. Hand-building it is how one build sent 4 of 20 refutations with no
  map row at all — and the closer answered `uphold` on all four instead of the `unsure` its contract
  asks for. A SECOND wave excludes what the first settled with `--settled <the first closer's
  verdicts file>` or `--exclude <id>`; an `--exclude` that matches nothing is an error, because the
  hand-written filter that matched 0 of 20 re-sent four settled refutations. **Dispatch once, when
  the wave closes.** The closer is denied
  `.coyomap/` on purpose — seeing the map whole would hand it the build's reasoning back — so a row
  you leave out is a row it cannot get. A brief that forbade `.coyomap/` and then asked a map-only
  question got a wrong answer, blocked the ship gate, and cost 5 turns to undo. WHY not
  the lead's own read by default: the lead re-reading the code is the build-context blind spot the
  fresh-context rule exists to break, reintroduced at the very step that decides what the map ends
  up saying (the same reason a lead tie-break is refused below). The lead applies the upheld ones
  through the destination table below and rejects the rest. Rejecting a refutation is a normal
  outcome — say so in `grounding.note`. **The closer writes its verdicts to
  `.coyomap/verify/closer-<agent-id>.json`**, beside the skeptics' own, in the same row shape: its
  answer is what decides the map, and on one build 22 of 24 such judgements survived only as a
  sentence in a chat nobody can reopen.
- **Do NOT pre-gather a skeptic's evidence. It was tried, measured, and it cost more.** The
  reasoning was good: 52-62% of a skeptic's bill is re-reading its own accumulated context, so hand
  it what it was going to fetch. `coyomap context` builds exactly that bundle. On a controlled A/B
  over the same planted batches — two skeptics with the bundle, two without — the bundle arm read
  **1.47x more context** and cost **1.34x more**, at **identical recall** (both arms 20/20).
  The reason is not a bug in the bundle, and it cannot be tuned away: a bundle a skeptic is told to
  treat as a starting point gets read IN ADDITION to the repo, not instead of it. Remove that
  instruction and the bundle becomes the evidence, which is the fabricated-confirmation failure the
  contract forbids by name. The saving and the safety are the same instruction, pulling opposite
  ways. **What the same numbers DO point at:** cost tracks a skeptic's response count almost
  linearly. That looked like a lever and **it is not one**: splitting the same 67 claims from two
  batches into four cost **1.69x MORE** ($6.29 to $10.62), at identical recall. Response count
  DOUBLED rather than halving, because each extra skeptic re-pays a fixed start — its system
  prompt, its tool schemas, its contract — and then re-reads the same shared files its sibling is
  reading. The response count follows how hard the CLAIMS are, not how many of them there are: two
  skeptics given 16 and 17 claims from one batch spent 27 and 83 responses on them. Cost tracking
  response count was a correlation, and the cause runs the other way.
- **Cap each batch at ~40 claims** and split an oversized theme into two skeptics rather than one
  long-running one — an oversized batch becomes the phase's critical path, and more, smaller
  skeptics also mean fresher context per claim, so this trades nothing away. **When the worklist
  exceeds what you can ground, TRIAGE ON THE RECORD — never silently.** The worklist is already
  ranked most-dangerous-first, so working it top-down is the right call; what is not optional is
  saying how far you got: at a typical refutation rate an unchallenged remainder of a thousand
  claims plausibly holds a hundred wrong ones, and a number reported only in chat evaporates. Record
  it in the model's **`grounding`** object: `claims_total` (the worklist size), `claims_challenged`
  (how many got a verdict), then the SPLIT of those verdicts — `claims_confirmed` / `claims_refuted`
  / `claims_unverifiable` — plus a `note` saying which claims were prioritized. **How a partial pass
  is recorded: `--partial`.** `grounding write` refuses a worklist claim with no verdict, because
  "we stopped at the top slice" and "a batch of skeptics died on the way home" look identical from
  inside the tool. `--partial` is you saying which one it was — pass it with the FULL pinned
  worklist and the verdicts you have:

  ```
  .venv/bin/coyomap grounding write --worklist .coyomap/verify/worklist.json \
    --verdicts .coyomap/verify/*.json --partial \
    --note '319 of 1,608 challenged: ranked top-down, stopped at the theme budget' --out …
  ```

  **Pass the note with `--note-file <path>`, not inline, on any re-run.** The record is re-measured
  after every late fix, and each re-run had to re-supply the whole note: one build retyped ~1,900
  characters three times through the shell, mutating it between pastes, and a note carrying a quote
  or a backtick would not have survived at all. `--keep-note` reuses the note already in `--out`
  when nothing about it changed.

  **Then quote the `NOTE FACTS` block `write` prints, rather than remembering a number.** It states
  the verdict rows, the distinct skeptic labels, the confirmed / refuted / unverifiable / tied
  split, and how many superseded claims had been CONFIRMED — each one a settled verdict the build
  overrode. A note is free prose in a permanent record and in the commit message, and nothing
  checks it: one said "Eighteen fresh-context skeptics" about a build that dispatched 17 and
  produced 20 labels, and "Four superseded claims had been CONFIRMED" where the true count was 11,
  leaving seven overrides undisclosed. Both numbers were on screen when the note was written.

  **`coyomap grounding report` lists what `write` only counts.** Its `ADDED SINCE THE PIN` section
  names the claims the shipped map carries that the pinned worklist never held, and
  `REFUTED BUT NOT SUPERSEDED` names refuted claims the map still carries verbatim — the count
  appears on the report's first line AND its last, so neither a `head` nor a `tail` can lose it.
  Read both before writing the note: a build that read neither shipped two refuted claims and
  hand-diffed the post-pin set in python to find what the section would have listed.

  `claims_total` keeps the full 1,608 and `claims_challenged` says 319, so the unchallenged
  remainder is visible in the record itself rather than in prose. The `--note` is required (the
  counts say how many, never why those), and passing `--partial` on a pass that turns out to be
  complete is refused too. **Never shrink the `--worklist` file to what you challenged** to get past
  the refusal: that makes `claims_total` the reduced size, and a 319-of-1,608 pass ships looking
  like a complete pass over a small map. Record the split even when it is boring: without it
  "challenged" is the only number, and a reader cannot tell how many claims actually HELD UP —
  `total 399, grounded 399, refuted 3` reads as "399 held up AND 3 were refuted out of 399".
  `validate` BLOCKS on counts that do not add up
  (`confirmed + refuted + unverifiable == challenged`). `claims_unverifiable` is for the honest third
  outcome —
  the code could not settle the claim either way — and folding it into either of the others is what
  makes the record lie. `validate` warns when coverage is thin, and warns when a map with a real
  claim surface carries no `grounding` record at all: an unchallenged map and a fully-verified one
  otherwise look identical in every view and pass every gate the same way. **GATE — run the free pass BEFORE you dispatch a single
  skeptic, not after the barrier:** `coyomap validate --check-sources` (and `coyomap anchor-drift
  --map …` with NO `--verdicts`) flags every call-site anchor pointing at a line that cannot act — a `def` header, an
  import, a comment. That is deterministic, needs no skeptics, and on live maps it reproduced what
  the skeptics found by reading; spend the skeptics on what it cannot decide. Stated as prose in
  this paragraph it was read as advice and skipped: one build ran `anchor-drift` exactly once, at
  the very end and WITH `--verdicts`, and paid three separate skeptics to report drifted anchors by
  hand. It is a gate with an order, not a suggestion.
  **SAY WHAT THE SHAPE-ONLY PASS DOES NOT COVER, when you report it.** It reads the LINE KIND at
  each anchor: a `def` header, an import, a comment, a blank. It cannot tell whether the operative
  line it points at is the RIGHT one — that is what a skeptic reading the code decides. So a clean
  shape-only result means "no anchor points at a line that cannot act", and it does not mean "no
  drifted anchors". A build reported the narrow result as the general one; the verdict-based pass
  it ran later found 11. Keep the split WITHIN
  a theme (related claims still travel together). Each is told to *disprove* the claim, and to use
  the THREE-WAY verdict honestly: **refuted when the code contradicts the claim; `unverifiable` when
  the code cannot settle it either way**. Do not tell a skeptic to "default to refuted on doubt" —
  that sentence and the `unverifiable` bucket are the same instruction pulling opposite ways, and
  the bucket is what loses: a third verdict nobody can reach is a record that cannot be honest. This
  is the *breaking* twin of the parallel *build*, aimed at falsification. **Fresh context is the
  whole point** — a verifier that sees the build reasoning inherits its blind spots. Each skeptic
  also reports the ONE `file:line` where the operation **actually** happens (the true call site); a
  drifted anchor does NOT refute a true relationship (grounding truth is separate). Collect the
  skeptics' output as the **verdicts file** `anchor-drift` consumes: `{"grounding": [{"claim": <the
  worklist claim string>, "grounded": true|false|"unverifiable", "evidence": "path:line"}]}` — one
  row per claim (or per vote when N skeptics run), `claim` matching the worklist text verbatim so
  the tool can pair it, `evidence` the true call site.

  **LINT the verdicts as they land, at the barrier — `coyomap grounding lint`.** It is the one
  mechanical check on the pass and it goes unrun because nothing named it: on one build it appeared
  zero times in the transcript, zero times in this file, and zero times in the skill, while the lead
  hand-wrote half of it twice. **Run it after EVERY wave, over every verdicts file so far** — never
  once on wave 1: the 2026-09-08 build linted 6 of its 38 files, and 56 of 1,180 rows cited evidence
  the lint would have caught. `--agent-transcripts` now defaults to this session's own directory, so
  the citation check runs without the flag.

  ```
  coyomap grounding lint --verdicts .coyomap/verify/verdicts-a.json \
                         --verdicts .coyomap/verify/verdicts-b.json … \
                         --expect security-1,security-2,rule-1,…      # every batch you dispatched
                         --agent-transcripts <dir>    # optional: defaults to this session's subagents/
  ```

  **`--expect` NAMES THE BATCHES, and it is the half that makes this a barrier.** Without it the
  command lints the files that HAPPEN TO EXIST and cannot see a batch that produced none, so a
  fan-out with one skeptic still writing lints clean: a build read `VERDICTS OK — 18 file(s)
  well-formed` while a nineteenth was seconds from landing, then ran `anchor-drift`,
  `fix apply-drift`, `assemble` and `grounding report` against the incomplete set and redid all
  four. A missing file is the one failure nobody spots by eye, because nothing is there. List the
  batch ids you dispatched; the command refuses until every one has a file.

  Note the shape: **`--verdicts` REPEATS, one flag per file** — it does not take a list, so a bare
  glob after one flag is an error. Run it the moment the barrier closes, not at `grounding write`:
  `write` refuses the same malformed shapes at the END of the build, where the skeptic that produced
  them is a hundred turns gone. `--agent-transcripts` adds the check no shape test can make — whether
  a note claiming a read is backed by the agent's own transcript. **Write the record with `coyomap
  grounding write`, never a hand tally:**

  ```
  # CAPTURE the worklist BEFORE any refutation is applied, and keep the file — the record is
  # written last, by which point a fresh audit no longer matches the verdicts.
  .venv/bin/coyomap audit .coyomap/project-map.json --json > .coyomap/verify/worklist.json
  # …skeptics run, refutations get applied, THEN:
  .venv/bin/coyomap grounding write --worklist .coyomap/verify/worklist.json \
      $(for f in .coyomap/verify/verdicts-*.json; do printf ' --verdicts %s' "$f"; done) \
      --out .coyomap/build-fragments/grounding.json
  ```

  It derives all four counts and REFUSES two things a hand tally cannot see: a verdict whose claim
  is not in the pinned worklist (the snapshot is wrong), and a worklist claim with no verdict at all
  (the pass did not challenge everything). Pin the worklist — re-deriving it after the refutations
  land makes `claims_challenged` exceed `claims_total`, which `validate` blocks on. **`grounding
  write` runs after the final reconcile edit, and is followed by ONE assemble that carries the
  record into the map.** Write it with `--map`, pointed at the assembled map, so the record states
  how the shipped claim surface differs from the pinned worklist. Both assembles are the SAME
  command, `--reconcile` included — dropping that flag silently discards every subsystem, `runs_in`
  and `drop_edges` assignment and changes the claim count, and `assemble` only prints a note about
  it:

  ```
  # 1. reconcile the refutations INTO THE FRAGMENTS, then:
  .venv/bin/coyomap assemble .coyomap/build-fragments/*.json --out .coyomap \
      --reconcile .coyomap/reconcile.json
  # 2. the record, measured against the map it describes:
  .venv/bin/coyomap grounding write --worklist .coyomap/verify/worklist.json \
      --map .coyomap/project-map.json \
      $(for f in .coyomap/verify/verdicts-*.json; do printf ' --verdicts %s' "$f"; done) \
      --out .coyomap/build-fragments/grounding.json
  # 3. the SAME assemble again, to carry the record in:
  .venv/bin/coyomap assemble .coyomap/build-fragments/*.json --out .coyomap \
      --reconcile .coyomap/reconcile.json
  ```

  Step 3 is safe because `assemble` is idempotent on claims, so it cannot invalidate what step 2
  measured.

  **Then READ what the record only counts — `coyomap grounding report --map`, same arguments.**
  `write` reduces the pass to four numbers plus a digest; `report` prints WHICH claims were
  superseded, refuted, tied, unverifiable or unvoted. Read it before writing `grounding.note`, and
  check two things the counts cannot show:

  - **a SUPERSEDED claim that was CONFIRMED** — the build rewrote something the skeptics had
    settled. That is a decision, not a fix; say so in the note.
  - **a REFUTED claim that is NOT superseded** — the reconcile changed something the claim's text
    does not name, so neither `claims_superseded` nor the digest can witness it (correcting one
    transition of a state machine leaves the claim string identical). Check that one by hand against
    the map, because nothing else will — `report` names it for you.

  The assumption that "superseded" and "refuted" are the same set is false in BOTH directions, and
  the counts alone cannot tell you which way a given build differs.

  **`claims_total` stays PINNED, and the pin is not a bug to fix.** Reconciling a refutation
  REWRITES the claim, which orphans its verdict, so a record written first describes a worklist that
  no longer exists. No gate can catch that by arithmetic: `validate`'s checks (challenged/superseded
  within total, the confirmed+refuted+unverifiable split, no negatives) are all self-consistent
  against a stale pin. `finalize` raises an advisory when the pin and the live worklist disagree,
  and L3 assertions 13 and 14 watch the ordering and the number. `--verdicts` is REPEATABLE: pass
  the per-batch files, do not hand-merge. **Then run `coyomap anchor-drift --map … --verdicts …`** —
  a deterministic check that flags any CONFIRMED claim whose stored `where` drifts from the line the
  skeptics found; reconcile each by **fixing the map's `where`** (the check flags, you apply — the
  LLM only observed the line). **Apply the drift fixes with the tool, never a hand script:**
  `coyomap anchor-drift … --json` emits the corrected anchors and `coyomap fix apply-drift --map …
  --verdicts …` writes them, matching each on the full `(src, verb, dst)` triple — an endpoints-only
  key swaps a paired `persists`/`reads` edge. `apply-drift` rewrites a drifted **rule SITE** anchor
  the same way, so a skeptic's corrected auth-check line lands with the tool, not a hand
  re-serialize. (It also still rewrites a legacy `security[].source`. **`fix security-row` and `fix
  dedup-security` act on `security[]` only**, which the T7 fold leaves empty — on a map built with
  the current method they print "no security rows" and exit 0, so a rule's TEXT is fixed in its
  fragment — with `fix row`, which is the verb for exactly that.) To drop a **refuted** edge as a terminal post-assemble fix, `coyomap
  fix drop-edge` removes it and reports (or, with `--repoint`/`--drop-steps`, heals) the flow steps
  that rode it; **`--to-reconcile <file>` records the drop as a `drop_edges` directive instead of
  editing the map**, which is what makes it survive the next assemble. Reconcile every refutation
  and every drift (fix the map, or justify and record why); this reconcile is **not delegated**.

  **EVERY skeptic outcome has a destination, and the one without a tool is the one that gets lost.**
  A batch comes back with four kinds of answer, not two. Name the destination for each before you
  start reconciling, or the ones with no verb attached evaporate into the notification prose:

  | what came back | where it goes |
  | --- | --- |
  | refuted, an edge | `coyomap fix drop-edge` (or `--repoint`), **with `--to-reconcile <file>`** — without it the next assemble re-derives the edge from the fragments |
  | refuted, an anchor moved | `coyomap fix apply-drift`, **with `--to-reconcile <file>`** — without it the next assemble discards the corrected anchor |
  | refuted, an ACCESS rule's TEXT is wrong ("that line guards nothing, the real gate is X") | `coyomap fix row --id <Rn> --set-<field> <text>` — reaches the rule's `statement`, `why` and `risk`, and edits the OWNING T7 fragment, so it survives every re-assemble; never hand-edit the fragment |
  | refuted, an access rule's SITE is wrong (the enforcement line moved) | `coyomap fix apply-drift` — a rule site is a claim-shaped, drift-eligible anchor like any other |
  | two fragments harvested one auth check | fuse them in the fragment: one decision enforced in several places is ONE `access` rule with several sites |
  | **true, but your note / list / transition is wrong** | fix the fragment with `coyomap fix row` (the same verb as the ACCESS-text row above), or `coyomap record` the decision — it is NOT a refutation and no counter will miss it |
  | unverifiable | the `unverifiable` verdict, and a line in `grounding.note` |

  The *true, but your note / list / transition is wrong* row is the one that disappears, because
  "confirmed" gets treated as "nothing to do". The verdict counts cannot witness it: the claim stays
  CONFIRMED and the record reads clean.

  **Never hand-script a security-row edit.** `fix security-row` selects EXACTLY (by claim, by
  surface, by anchor) and refuses on 0 or >1 matches. A loose hand-rolled selector overwrites the
  wrong row, and the damage surfaces assembles later, if at all. Two rows sharing an anchor is legal
  and is not duplication — `dedup-security` keys on the surface for exactly that reason.

  **The vote is advisory; your re-read decides.** When N skeptics split and you open the file
  yourself, what you find outranks the majority — a 1-of-3 minority refutation is correct to apply
  when the dissenter turns out to be right. Say so in `grounding.note` (`report` will flag it as a
  CONFIRMED claim you overrode). This is not a licence to overrule a vote you merely dislike: the
  re-read wins because it is evidence, so it only wins when you actually did it. The closer agent's
  uphold/reject IS this re-read for refutations; overruling the closer takes a read of your own,
  recorded the same way. Two
  **behavioral-consistency items** ride the same fresh-context pass (judgment calls no mechanical
  gate can make): (1) for each Happy Path step, **is the use case its `uc` tag names really what
  happens at that position**, and does its `why:` state a prerequisite rather than the step's own
  outcome? (the "signs in; the organization exists" class: an outcome written where a step goes — a
  step is a use case at a position, never a post-condition); (2) do two flows **retell the same machinery at
  different depths** (one spells a pipeline out in 13 steps, another compresses the same run to 3)?
  — the mechanical duplication detector only catches *identical* runs, so depth-inconsistent
  retellings are found here; fix by extracting a sub-flow or aligning the depths. Re-validate →
  re-audit → render after fixes.
  - **Ordering — ONE sequence, and `coyomap ship` RUNS it.** The list below is the reference for
    what happens; the way to execute steps 2–12 is the verb, which stops at the first failing step
    and names every step that did not run:

    ```
    .venv/bin/coyomap ship <repo>                       # PREPARE: steps 2-5, then stop — read the
                                                        #   report it ends on, write the note
    .venv/bin/coyomap ship <repo> --note-file <path> \
        [--partial] [--access-baseline <old-map>]       # FINISH: through step 12
    ```

    It derives every path from `<repo>/.coyomap/` (map, fragments, reconcile.json, the pinned
    `verify/worklist.json`, `verify/verdicts-*.json`) and refuses, naming the missing input, rather
    than running a shorter sequence — so a skipped step can never read as a clean one. Steps 0, 1
    and 13 stay yours: the collection-time verdicts lint, the refutation reconcile, and the commit.
    Run the steps by hand only when ship refuses and the refusal is genuinely wrong for this build.
    Where an older note disagrees with the list below, the list wins.

    **THE LIST BELOW IS A REFERENCE, NOT A SCRIPT — do not copy its lines.** It is written without
    runnable commands on purpose. When the steps were spelled out as pasteable lines directly under
    this paragraph, that is what a build reached for: the 2026-09-02 build announced "now the ship
    sequence" and then hand-typed the thirteen steps over 57 turns, and `ship` ran zero times. It
    was not avoiding the verb; the verb was named once, six hundred lines above where it was needed,
    while the pieces were pasteable right here. The steps still have to be documented — a reader has
    to know what runs, and steps 0, 1 and 13 are genuinely yours — so they are described rather than
    supplied.

    ```
    0.  YOURS — lint the verdicts at COLLECTION, not here (`grounding lint`, with
        `--agent-transcripts`).
    1.  YOURS — every structural / fragment change, including the refutation reconcile.
    2.  anchor-drift against the verdicts: what drifted.
    3.  apply-drift `--to-reconcile`: RECORDS it; the map is not edited.
    4.  the last STRUCTURAL assemble; applies set_anchors.
    5.  grounding report: WHICH claims were refuted / tied / unvoted — the reconcile worklist, and
        what `grounding.note` is written from.
    6.  grounding write, measured against the map it describes.
    7.  assemble again, carrying the RECORD in. Idempotent, and not optional — skip it and the
        grounding record never reaches the map.
    8.  provenance stamp, which STAMPS and fills `built` in one run. Never hand-write that minute.
    9.  assemble + render again, so the filled header reaches the map.
    10. lint the header fragment — the one a hand authored.
    11. validate `--check-sources`, then audit, then render.
    12. finalize with the verdicts AND `--emit-gate-block`, in ONE run.
    12b. YOURS — if this build ran an EXPERIMENT the backlog asked for, write its answer somewhere
        durable BEFORE the commit: `COYOMAP_HOME/eval/retro/backlog.md`, or the map's own extras. A
        scratchpad is not a destination: on one build the experiment ran, answered its question with
        real numbers, and the 53-line write-up was left in a temp folder, one sweep from gone, while
        the backlog row still read unanswered. That question had been parked three times before
        somebody finally ran it.
   13. commit the map, the .md, the pre-index and provenance
    ```

    **Steps 5, 8, 9 and 12 are here because the list without them cost real builds.** `grounding
    report` used to live only in prose 74 lines above, so a build that followed this block literally
    wrote the record, then read `report`, then wrote the record AGAIN with the note — one wasted
    invocation every time, because `report` reads the worklist, the map and the verdicts and never
    consumes the record. `provenance stamp` and the header backfill were prescribed 160 lines away
    while this block called itself the single sequence, so the third `assemble` they force appeared
    to contradict step 4's "last STRUCTURAL assemble" (it does not: the header carries no claim, and
    `finalize` re-reads the shipped bytes). And `finalize` was run twice on one build — once with
    `--verdicts`, once with `--emit-gate-block` — where the second run overwrote the report and
    dropped its verdict-based anchor-drift leg, including the "challenged N of M" coverage line. The
    flags combine; run it once.

    **Step 8 stamps AND fills the header in one run, because the step it replaces was an
    instruction to hand-write a map file** — copy the stamped minute across into `header.json` yourself. It read as
    a two-line edit and it is one, which is exactly why no build treated it as a defect: one wrote
    the `built` string with a
    `python3 - <<'PY'` heredoc AFTER `grounding write`, making that heredoc the last fragment write
    of the build and scoring L3 assertion 13 zero. The flag that does it had shipped the day before
    and was named nowhere a build reads — not here, not in `provenance stamp --help`'s prose, only
    in a usage grammar line. Do not hand-write `built`; there is no case left for it.

    Steps 3 and 4 are the change. `fix` edits the ASSEMBLED map, and the source of truth is the
    fragments, so a later `assemble` silently discards every `fix` edit. `--to-reconcile` makes the
    correction durable instead, so the drift fix no longer has to be last and the grounding record
    can be measured against the map that ships. Use bare `fix apply-drift` (no `--to-reconcile`)
    only for a genuinely terminal touch-up after step 6, and re-run `grounding write` if you do. If
    Phase 4 surfaces a change that must live in a fragment, edit the fragment, re-assemble, and
    re-run the grounding reconcile after (never the other way round). Keep the **verdicts file OUT
    of `build-fragments/`** (e.g. under `.coyomap/verify/`) so a `*.json` glob into `assemble` can't
    pick it up — `assemble` now skips a stray verdicts file with a note, but keeping it out of the
    fragment dir is the clean habit.
  - **Where each reconcile lives — reconcile file vs `fix` verbs.** Build-time drop/dedup (a
    cross-agent duplicate edge, a refuted edge you decide during synthesis/trace) belongs in the
    **`--reconcile` file** (`drop_edges`) or the fragments, so a re-assemble re-applies it — do NOT
    reach for a bare `fix drop-edge` there, its edit is discarded by the next assemble ( `fix
    drop-edge --to-reconcile <file>` writes the same drop as a `drop_edges` directive, which is
    not). The `fix` verbs are the **post-assemble anchor-drift** tool only (`apply-drift` for
    drifted edge/security anchors, `drop-edge` for a refuted edge found in Phase 4 after the final
    assemble). One rule: assignment and drop that must survive a rebuild → reconcile file; a
    terminal anchor fix after the last assemble → `fix`. `--reconcile drop_edges` runs after the
    entity-edge derivation and heals the riding flow steps exactly like `fix drop-edge`, so a
    dropped `C→E` edge is not silently re-derived. `set_anchors` is the third directive and the one
    that makes an anchor correction survive a rebuild — `fix apply-drift --to-reconcile` writes it,
    keyed by the claim, and `assemble --reconcile` applies it through the same writer. The directive
    shape (also in `assemble --help`):
    ```json
    { "set_anchors": [ {"claim": "C21 persists E33", "corrected": "backend/store.py:88"} ],
      "drop_edges": [ {"src": "C21", "verb": "persists", "dst": "E33"},
                      {"src": "C7",  "verb": "calls",    "dst": "C9", "drop_steps": true},
                      {"src": "C4",  "verb": "reads",    "dst": "E2", "repoint": "E5"} ] }
    ```
    Each entry defaults to REPORTING the flow steps that rode the edge; `drop_steps` removes them,
    `repoint` re-points them. **A report-only `C→E` drop leaves the step, and the next assemble
    re-derives the edge from it** — so heal it, or the drop does not stick. `assemble` prints the
    unhealed count in its final digest line for exactly this reason. Zero matches warns, never fails,
    so a directive that outlives its edge does not rot the build.
  - **A duplicated domain relation BLOCKS validate — resolve it with `coyomap fix dedup-relation`.**
    The same `E→E` relation declared on both entity cards (or twice on one) is a hard validate error,
    not an advisory, so the build cannot finish until you pick a survivor. Run it with no `--drop` to
    LIST each duplicate with the token that resolves it, then re-run naming the occurrence to remove:
    ```
    .venv/bin/coyomap fix dedup-relation --map .coyomap/project-map.json
    .venv/bin/coyomap fix dedup-relation --map .coyomap/project-map.json --drop <En:verb:Em>
    ```
    Same ordering rule as the other `fix` verbs: it edits the assembled map, so run it AFTER the last
    assemble, or fix the duplicate in the fragment and re-assemble instead.
- Guardrails: all agents share the same schema + edge-verb vocabulary; Phase 1 produces
  the canonical node inventory FIRST (nodes before edges, agents reference nodes and
  never invent them); every agent keeps inferred-vs-verified labels + returns `file:line`;
  agents return rows (structured output), not file dumps. The final reconcile (dedup
  names, verify cross-agent edges against code) is not delegated — and the lead may **not**
  author a `C→D` edge (or any edge into an external dependency) the trace agents did not
  report: every backbone edge must trace to a delegated agent's finding or be grounded
  against the code, never invented at synthesis to satisfy the "every dep needs an incoming
  edge" nudge (the audit→Elastic false-edge class — a benign-verb edge no gate re-checks).

**Harvest-prompt template (Phase 1).** The copyable contract is
[method/templates/harvest-contract.md](method/templates/harvest-contract.md) — hand every harvest
agent a POINTER to its filled copy (the pointer-dispatch rule above), changing only the file list
and the background blurb. **Get it with the verb, never by copying the file:** `coyomap
contract harvest --slots` prints the slot skeleton, and `coyomap contract harvest --fill
<slots.json> --out <scratch>/briefs/<agent-id>.md --brief <agent-id>` writes the brief and prints
the pointer to send, one call per slice. The `--fill` is what records the brief's
«EXPECTED_COMPONENTS» in `.coyomap/verify/budgets.json` (a hand-filled copy records nothing), and
`finalize` sums those budgets against what shipped (the `component budget` leg, held to the same
±40 % band each slice is held to): 60 budgeted and 114 shipped is a sentence at assemble time, not
a `Balance exceptions` record 450 turns later.
The verb prints the agent's half and appends the writing rules, so you never handle the template
and the lead-facing header at its top cannot reach an agent. A harvest agent authors every
component `purpose` in the map, the largest block of reader-facing prose there is. Do not `Read` it and `Write` your own — that is one
keystroke from a rewrite, and a retyped contract drifts from the tool it describes, silently
dropping rules (the anchor rules for `edges[].where`, `subsystems[].source` and `tests[].file` are
the ones that have gone missing) from the contract every agent is handed.

**Business-rule contract (Phase 3).** The copyable contract is
[method/templates/rules-contract.md](method/templates/rules-contract.md). Get it the same way —
`coyomap contract rules --slots > <slots-dir>/<agent-id>.json` per agent, then one
`coyomap contract rules --from-slots <slots-dir> --out-dir <briefs-dir>` — and for the same reason. A rule agent authors every `statement` and every `risk`, the two fields a
reader meets when asking what the product decides. This template exists because one build had none:
the lead composed the rules contract from prose and told all eleven rule agents to put a `block`
field on every rule, which `lint-fragment` treats as BLOCKING. The failure fired in 13 of that
build's 71 agent transcripts and every one of the eleven fragments had to be repaired. `block` is
the lead's to assign, through `reconcile`, after the fan-out — an agent states its block id in its
REPLY and never in its fragment.

**Completeness check before the barrier (lead, not delegated).** Before the Phase 2 synthesis, the
lead confirms **every prescribed slice came back with its sections** — in particular that the T5 owner
returned per-entity cards *with* RELATIONS, and that each agent that wrote `(none found)` is genuinely
empty rather than under-delivered. For T4, confirm the **self-starting second pass ran**: a
long-running service whose entry points are all routes/mounts/CLI has likely skipped its background
loops — re-ping with the self-starting checklist stated. Re-ping any agent that dropped or thinned its sections; a missing
section caught here is cheap, one discovered after synthesis is a re-trace. **An agent that returns
prose instead of a written fragment file (it delegated, or answered in its reply) has produced
NOTHING usable — re-launch that slice immediately, do not wait on it or try to salvage the reply;
the written fragment is the only output that counts.** The same "every prescribed
table came back" rule reaches past the barrier to the **test-completeness table**: after the Phase 3
trace's test-completeness step, confirm `tests[]` came back non-empty before finalizing (an empty
`tests[]` is a dropped section — the step always produces a gap table — not a project with zero
targets); re-run that step, exactly as a missing harvest section is re-pinged here.

**Expected yield per slice — judge each return against its E (under-delivery guidance).** A
well-formed return can still be an under-delivered one: a slice that comes back with far fewer
components than its size suggests has *abstracted where it should have harvested*. The expectation is
already computed: the pre-index's `granularity.per_dir` carries each slice's **E** (the leaf rule
above), and the harvest prompt hands it to the agent. **Before** reading the returns, note each
slice's E; a return far under its E's ±40% band is under-delivered even though every row validates.
Re-ping such a slice **with the expectation stated** ("this slice's code-derived expectation is ~E
components; return its real units or say per unit why it folds") — a size-blind re-ping just gets the
same answer back. E is an attention threshold, not a gate (a heavy *generated* dir still legitimately
folds — the pre-index guardrail applies); a cheap deterministic backstop exists after the fact in
`validate --check-coverage`, which re-computes E for the whole map and flags folded sibling subdirs
and never-referenced dirs.

**Output files — model + generated views.** Build writes a **new** baseline and overwrites any
existing `.coyomap/` map, so you should only be here for a first map or a user-confirmed rebuild —
[dispatch](method/dispatch.md) routes an existing baseline to Analyze, not Build. The committed
source of truth is `.coyomap/project-map.json` ([the map model](method/model.md)),
written by `coyomap assemble` together with its generated markdown view, `.coyomap/project-map.md`
(readable diffs). Both are committed — and so is the structural pre-index `.coyomap/preindex.json`
when the build produced one: the viewer's symbol search reads it, pinned to the map's commit, so it
must ship with the map (it is generated at that commit, so its `file:line` anchors match). The
interactive C4 diagram is not a committed file: it is served live by `coyomap serve` (built on
demand from the model), and `coyomap export` writes that same viewer out as a folder of plain files
for anyone to host — how a map is shared with people who have neither the repo nor coyomap. Record
the commit the map was built
at in the model's `commit`/`committed`/`built` fields (the baseline pin — see the pin gate below).

**Baseline pin — require committed code, or record it dirty.** The pin must mean "the map describes
*exactly* this commit". The map you just read reflects the **working tree**, so if the code has
uncommitted changes, HEAD alone is a misleading pin (and a later `git diff <pin>..<now>` would miss
the edits already baked into the map). So before recording the pin, check the analyzed repo for
uncommitted **code** — coyomap's own files under `.coyomap/` (map / markdown view / report) don't count, they
are always in flux and the workflow commits them:

```
git -C <repo> status --porcelain -- . ':(exclude).coyomap'   # empty = code is committed
```

- **Code committed** (empty output) → record the pin from HEAD:
  `git -C <repo> rev-parse --short HEAD` (the sha) and
  `git -C <repo> show -s --format=%cs HEAD` (its commit date, `YYYY-MM-DD`).
- **Uncommitted code** → first LOOK at the diff. When it is **trivial** — comments and/or whitespace
  only, no code lines (`git -C <repo> diff -w --ignore-blank-lines -- . ':(exclude).coyomap'` empty,
  and any untracked files are non-source) — do NOT block: proceed automatically as **B** below and
  note the pin choice + the trivial diff in your report. Otherwise STOP and give the user a choice,
  then **loop**:
  - **A (recommended)** — **the user** commits (or stashes) the code first, so the baseline
    corresponds to a real commit; then you re-check and record the pin as above. Never commit or
    stash their working tree yourself — this step is a question, not a mandate.
  - **B** — proceed without committing, but record that the code was dirty: pin the sha with a
    `-dirty` suffix (`<short-sha>-dirty`), date = HEAD's commit date.

  Re-run the check after each round; only continue when the code is committed (A), the user
  explicitly chose B, **or** the auto-B trivial-diff rule above applied.

  **Asked once, not twice.** [dispatch](method/dispatch.md) Step 0 puts this same A/B question to the
  user BEFORE the build starts, off the `coyomap scope` briefing. If it was answered there, honour
  that answer and record the pin — re-asking at the end, after the user already decided and waited
  out a whole build, is the annoyance this gate is supposed to prevent.

Write the pin into the model's **`commit`** / **`committed`** / **`built`** fields (sha · commit
date · build time — the header fragment carries them; the generated views render them as the map's
header line).

**`built` is stamped LAST and copied BACKWARDS — never guessed early and reused.** The header
fragment is authored during Assemble and the stamp belongs after the map is written and validated,
so on a real build they are an HOUR apart. Capture the minute early and reuse it, and both the
header and `provenance.json` carry the wrong minute permanently — and `coyomap-eval retro-precheck`
reads exactly that field to decide whether a build has finished.

So: write `header.json` with `built` **empty**, and fill it from the stamp at the end.

**Stamp the conversation (provenance).** After the map is written and validated, record which
conversation built it — run (paths under the coyomap clone, like `.venv/bin/coyomap`):

```
.venv/bin/coyomap provenance stamp <repo> --mode build \
    --update-header <repo>/.coyomap/build-fragments/header.json   # NO --built-at: real clock
# --update-header writes the stamped minute into `built` for you. Then re-run `assemble` and
# `render` so the filled header reaches the map.
```

**Do not hand-write that minute.** The flag above is the whole step. Without it a build reads
`built_at=…` off stdout and edits `header.json` by hand, which is a map write in the middle of the
closing sequence — one build did it with a `python3` heredoc placed after `grounding write`, so the
last write of the whole build was a hand-script.

Pass `--built-at` only when you are deliberately restating a time you did not just measure (an
`accept` pass re-stamping an earlier build). On a build it is the flag that makes the map lie.

It reads this session's id from `$CLAUDE_CODE_SESSION_ID` and writes `<repo>/.coyomap/provenance.json`
(committed — session id + build time), so a later `.venv/bin/python tools/map_backup.py backup <repo>`
can bundle the map **and** the exact transcript deterministically. Run it in the **main** build
session, not a delegated sub-agent, so the id recorded is the driver conversation's. **Commit
`provenance.json`** with the map + diagram.

**Assemble the model from the agents' fragments — never hand-author the stored file.** Each agent
wrote its JSON fragment to the scratch dir (`.coyomap/build-fragments/<agent>.json` — the harvest
prompt's output rule); `coyomap assemble` itself writes a `.coyomap/.gitignore` entry ignoring
`build-fragments/`, so the scratch dir never dirties the tree (you may still delete it after a
successful assemble — the model is the record). Write one small `header.json` fragment yourself
(`title`, `goal`, the pin fields — as **top-level keys**, NOT wrapped in a `header` object), and
**lint it too before assembling** (`coyomap lint-fragment .coyomap/build-fragments/header.json`): the
header is the one hand-authored fragment that otherwise skips the self-check every sub-agent runs, so a
stray key here is the one thing that still fails `assemble`. Then run:

```
.venv/bin/coyomap assemble .coyomap/build-fragments/*.json --out .coyomap
```

It validates every fragment against the schema (a malformed fragment fails ALONE, with its file and
JSON path named — re-request that one agent's rows), refuses duplicate IDs across fragments, and
writes the canonical `project-map.json` plus the generated markdown view (no HTML file — the
interactive diagram is served on demand, never written). In serial (non-parallel) mode the same rule
holds at smaller scale: author your rows as one or a few fragments and let `assemble` serialize —
the stored JSON is always tool-written, so its validity is guaranteed by the serializer, not by you.
(The old markdown template,
[`method/templates/project-map.template.md`](method/templates/project-map.template.md), now only
documents the generated view's shape — it is no longer filled in by hand.) Run the validator —
`.venv/bin/coyomap validate .coyomap/project-map.json --check-sources --check-coverage`
([tools/coyomap/validate_model.py](tools/coyomap/validate_model.py)) — after each assemble/patch and
fix the model (via fragments / field edits + re-assemble or re-render) until it passes
(`--check-sources` reads each entity's `source` to reject synthesized entities — names with no real
named type; `--check-coverage` re-walks the repo and WARNS — non-blocking — when many sibling source
subdirs are folded into one box or a significant directory is never referenced, the map-fidelity
gaps the ID checks can't see). **At a deliberately coarse (whole-repo overview) altitude these
coverage warnings are expected, and a recorded exception silences them per-directory:** list the
consciously-folded repo-relative dirs, one per line, under a **"Coverage exceptions"** extras
heading (`plugins/: representative at coarse altitude`). A recorded dir silences the folded-subdir /
unreferenced-dir / no-entity-card warnings **and** the per-component "unclaimed surface" warning for
anything at or under it — one `plugins/` line replaces a per-plugin record for every unit beneath
it. It is **boundary-scoped**: a real gap in an *unlisted* dir still warns, and `plugins/` never
silences a `plugins-legacy/` sibling. (The component-count-vs-E advisory has its own token — the
literal `granularity` under "Balance exceptions".) **Then run the adversarial pass** —
`.venv/bin/coyomap audit .coyomap/project-map.json`
([tools/coyomap/audit_model.py](tools/coyomap/audit_model.py)). Where validate asks *is the map
well-formed*, audit asks *is it self-contradictory*: it makes the map's two layers — the narrative
Happy Path (step order, actors) and the mechanism (T6 flows + the backbone edge list) — refute each
other, deterministically, with no code. The map is **over-determined** (each precondition is encoded
twice — once as narrative order, once as which entity a flow reads vs writes), so the two copies
check each other. Audit **blocks (exit 1) only on a hard contradiction** — a *`why:` reference that
points forward or at a nonexistent step* (unambiguous, no false positives) — which you fix like a
validator error. Its ordering/actor checks are **ADVISORY, not blocking**, on purpose:
*read-before-create* (a Happy-Path step reads an entity a later step first
`writes`/`persists`/`creates` — `writes` is create-or-update ambiguous, so this is a pointer, not a
verdict) and *actor-attribution* (the Use-cases table and the flow disagree on who drives a use
case) are derived from lossy component-granularity attribution, so they have real false positives (a
shared component leaks its reads) and false negatives (a read routed through a `C→C` dependency is
invisible — only `C→E` edges count). Treat them as strong "look here" pointers to reconcile, not
facts; *read-never-created* (a read with no create — often external/config data) is advisory too.
The known bug that motivated audit (a sign-in step ordered before the org it needs) surfaces here as
an *advisory* — audit points, you or L2 decide. Audit also prints an **L2 grounding worklist**: the
"actually-does" claims no deterministic check can settle — the **whole backbone edge list**, ranked
most-dangerous first so a large list is worked top-down: security surfaces + `enforces` / `encrypts`
edges, then every `C→D` external-dependency edge (any verb — the audit→Elastic system-boundary
class), then every `C→E` ownership edge, then the remaining element↔element edges (an edge into a
dep explicitly tagged `framework`/`library` is skipped — a false "uses <lib>" is benign). Ground
each by spawning a **fresh-context skeptic** (Phase 4 below) that sees only the finished map + the
code — never your build reasoning — and tries to *disprove* the claim; **reconcile every finding —
advisory or blocking — (fix the map, or justify and note why)** before rendering. So the invariant
after every write is **validate --check-sources → audit → render** (`--check-sources` is not
optional — it is the deterministic backstop that a nonexistent-file anchor / wrong repo-root prefix
can never slip through).

**Run `coyomap finalize` as the pre-commit read.** It runs that sequence plus the SHAPE-ONLY
anchor-drift pass in one command, and writes every finding to `.coyomap/finalize-report.{json,md}`
with whole lists. The verdict-based drift pass runs only when you hand it `--verdicts`; without
that flag the leg simply does not run and nothing in the report says so, so a run without it is
not the full pre-commit read:

```
.venv/bin/coyomap finalize .coyomap/project-map.json --repo <repo> [--verdicts <file>]...
```

It adds no check of its own. What it adds is a record and an answer:

- **the report is a FILE.** A file survives `> /dev/null`, `| tail -12`, and a summary written from
  memory; a piped gate does not. **This binds the MID-BUILD gate runs too, not only this pre-commit
  one.** Reading each gate through `| tail -40` / `| head -14` costs serial rounds — one `validate`
  run per warning family, each with its own patch turn, where one whole read produces one batch of
  fixes. **When the human report is too wide to read whole, the whole report is `validate --json`**
  — a `cut -c1-200` is a clip, not a read, and one build clipped 8 of its 9 validate runs that way.
  **And never re-check a warning with a filter narrower than the run that surfaced it**: a
  grep whose pattern no longer matches the wording makes the finding vanish from view, and it then
  ships unrecorded and unfixed. Narrowing the view is what a waved-through advisory looks like from
  the inside. (L3 assertion 15 watches this.) **A COUNT is the narrowest view of all, and it is not
  a read.** A count cannot say WHICH warnings are open, and an identical count before and after a
  change reads as "nothing changed" when checking exactly that was the point. (L3 assertion 26
  watches this, for `validate`, `audit` AND `finalize`.) **`audit` gets the same treatment as
  `validate`.** Printing `len(worklist)` and the theme table out of `audit --json` while never
  reading its `findings` key is the same move: piping a gate into a length is piping it into a grep.
  **`grep -v` on a gate's output is the same move in disguise:** filtering a family out of your own
  view is not reconciling it. If a family is noise, record an exception; never delete it from the
  report you are reading. When a message says a recorded exception silenced more than it names, the
  re-read is **`coyomap validate <map> --ignore-exceptions`** — not a hand-edited copy of the map.
- **it says whether every check actually ran.** Run the three commands by hand and a skipped one
  looks exactly like a clean one. A leg that should have run and did not makes the verdict
  `INCOMPLETE`, which exits non-zero — "the gate did not run" must never read as "the gate passed".

**Read the report file, and quote finalize's verdict line when you report the gates — in the COMMIT
MESSAGE too, not only in chat.** Its stdout can be piped away: in a shell pipeline the exit status
is the last command's, so `finalize | grep …` returns grep's `0` — and so does `finalize | tail -3`.
An honest verdict in chat and a clean-sounding commit message are not the same deliverable, and the
commit is the only record a future reader sees. `finalize --emit-gate-block <file>` writes the block
to paste, so the durable record is generated rather than remembered.

**Then actually commit.** The build is not over at `finalize`. Stopping there leaves `.coyomap/`
untracked, so a map that cost hours and hundreds of dollars exists only in one working tree — and
the whole argument for generating the gate block is that the commit is the durable half. `finalize`
prints the exact `git add -f` line to use; run it, and commit the pre-index and provenance with the
map.

**COMMIT THE WARRANT TOO — `verify/` and `build-fragments/`.** The map is a set of claims; the
reason to believe them is the pinned worklist, the claims batches and every skeptic's verdict file,
plus the fragments each agent authored. `grounding.note` cites the verdict rows BY COUNT as that
reason. Ship the counts without the rows and a fresh clone has the conclusion and can check no part
of it — which is what happened on the 2026-09-02 mcpolis build: 71 verify files and 47 fragments,
force-added by nothing, in a repo whose `.gitignore` ignores `.coyomap/`. The `git add -f` line
`finalize` prints now names both directories. They are also what makes the NEXT build's
change-analysis and the eval's archive possible; regenerating them costs another full build.

**`finalize` also reads the advisory disposition** — each advisory as fixed / recorded / carried,
against what the map's extras actually record. Read that table rather than the raw list.

**ADVISORIES is not a pass** — fix each one, or record it under the extras heading its message
names. **Where a verb exists, use it.** `validate`'s "the '<verb>' edge is declared N times with
differing call sites" has one: **`coyomap fix dedup-edge --map … --repo …`** lists every conflicting
triple with its competing anchors and suggests the likeliest true site, and `--keep
<src:verb:dst:path:line>` drops the rest. **Some advisories deliberately name no heading.**
`tests/test_method_contract.py`'s `KNOWN_NO_ESCAPE` is that list, each entry with its own reason,
and the reasons are not one kind: some are mechanical and local ("contradictory row; drop one
field"), some say the record already exists ("the minted name IS the record"), and some are
deliberately un-escapable because a suppressed count staying visible IS the feature. So the honest
answer differs per entry — fix it, or carry it and say which. **Never call one "recorded"**: an
advisory whose stock remedy would inject a misattribution (a `C→broker` edge whose publisher's own
source holds zero references to the broker, because it is reached through an event-stream adapter),
or whose remedy is "rename on rebuild", has no home and no correct stock answer. Anchor drift is the
exception that is a judgement call: the skeptics can report a line from a sibling file while the
stored anchor is right, so it has its own escape — record ``anchor-drift `<the claim, verbatim>`:
<why>`` under a **`Drift exceptions`** extras heading. The key is the WHOLE claim in backticks, not
its leading id: keying on the id would let one line silence every drift finding rooted at that
component, which is the family escape the `Audit exceptions` rule above forbids in so many words.
`anchor-drift` prints the exact key to copy; it reports any recorded line that matched nothing, AND
any line that opens with `anchor-drift` but does not parse — an unparsed line yields no key, and a
line that silences nothing looks exactly like no line at all. **A bucket the seed list does not have
has its own escape: `Bucket vocabulary`.** A project whose real vocabulary needs a bucket the
library seeds never named (an MCP gateway genuinely has an "MCP protocol" bucket) would otherwise be
told to rename it on every rebuild, forever — advice that pulls against itself, because reusing the
previous map's spelling for stability is what earns the warning. Record ``coyomap record --map
.coyomap/build-fragments/extras.json --heading "Bucket vocabulary" --line "MCP protocol: <why this
project needs it>"`` — **name the FRAGMENT**, not the assembled map: `--map` defaults to
`.coyomap/project-map.json`, and `record --help` calls that "the edit the next assemble discards". A
record written into the map is a decision that silently un-records itself. and the nudge stops for
that bucket only; a summary line still reports what the record silenced. **A decision-sounding step
that is NOT a business rule has its own escape: `Sweep debt`.** Once a map carries business rules,
`validate` lists every anchored flow step whose wording reads like a decision that no rule claims —
the sweep worklist, and the only thing that says whether the sweep finished. There is deliberately
no `swept` field to set: a boolean asserting "I searched the whole repo" is unfalsifiable, and
hand-assigned data rendered as derived is what makes a screen confidently wrong. So the list shrinks
two ways only — write the rule, or say why the step is not one. Record ``coyomap record --heading
"Sweep debt" --line "<the step's anchor>: <why this is plumbing, not a decision>"`` under the
**"Sweep debt"** extras heading — **name the FRAGMENT** (`--map
.coyomap/build-fragments/extras.json`), not the assembled map, for the reason the bucket paragraph
above gives. The key is whatever the advisory prints: the step's own `path:line` for a
decision-sounding step, and a `BRn` for the other finding this heading answers — a rule whose sites
land in files no component claims, which renders with no component and cannot be verified. Both work
because this heading is read by the generic `key: why` reader, not the id-keyed one (which matches
no `BR` token at all — a `BRn` line under a heading THAT reader serves would silence nothing,
silently). Every suppression is REPORTED, and it moves a derived number: a recorded step counts as
swept. **OPEN THE FILE before recording one.** The escape is for "the skeptics read a sibling file
and the stored anchor is right" — a claim about what is at a `path:line`, which you cannot know
without looking. Reasoning about what an anchor "is defined to point at" is not looking. (L3
assertion 17 watches this.) Write the record with **`coyomap record --heading "Drift exceptions"
--line "…"`** rather than a hand-rolled append: it checks the heading is one a check actually reads,
refuses a key with no why, and `--replace <prefix>` is how you correct a record whose facts moved.
`finalize` exits non-zero for what validate and audit already block on, and for `INCOMPLETE`;
unapplied anchor drift is reported and never gates, because a `lifecycle` claim still has no writer
and a gate with no remedy is a false failure. (`cadence` DID have no writer and now does — `fix
apply-drift` rewrites an entry point's `cadence_source` alongside an edge `where` and a
`security[].source`.) It is a convenience wrapper and a durable record, not a gate that can force
anything. **Then render the markdown view** — once the map validates and the adversarial pass has no
blocking contradiction (advisories reconciled), regenerate the committed markdown view next to the
model (assemble already wrote it; re-run after any patch):

```
.venv/bin/coyomap render .coyomap/project-map.json .coyomap/project-map.md
```

It is a *rendering* of the model (no second source; never hand-edit it — `validate` flags a stale
view) — commit it alongside the model so the two stay in step. The interactive diagram is not a file:
it is served live from the model by `coyomap serve`. **Finish by reporting the artifacts as links** —
the model (`.coyomap/project-map.json`) and the markdown view (`.coyomap/project-map.md`), as relative
paths. **Then give the reader the URL to open the interactive map in a browser through the
coyomap map server** — that is where the diagram, file browser, and code viewer light up (data + source
served from git at the map's commit). Rendering just registered this project with the server, so it shows up there as a
card. Tell the reader: if the server isn't already running, start it once from the coyomap clone —
`make start` (or `.venv/bin/coyomap serve`) — then open `http://127.0.0.1:8765/coyomap/<repo-folder-name>/`
(the `<repo-folder-name>` is the mapped repo's folder name), or the landing page
`http://127.0.0.1:8765/` and click this project. (Paths like `.venv/bin/coyomap` are relative to the
coyomap clone, like the validator above.) For the address of ONE element — a use case the reader asked
about, a rule — `.venv/bin/coyomap url <ID> --repo <repo>` prints it, port included.

**Maintaining the map.** When code changes after a baseline exists, follow
[change-impact](method/change-impact.md): report the impact against the map (modified /
added / deleted), then accept: patch the MODEL (`.coyomap/project-map.json` — surgical field
edits), bump the baseline pin, re-stamp provenance
(`.venv/bin/python tools/map_backup.py stamp <repo> --mode accept --built-at '<YYYY-MM-DD HH:MM>'`,
which appends this session), **re-run validate → audit** (a patch can introduce a fresh
self-contradiction — e.g. a re-ordered Happy Path step now reads before it creates), **re-render
the markdown view** (`coyomap render … project-map.md`, so it tracks the patched model; the diagram
is served live) and, when the map has a pre-index, **regenerate it at the new pin**
(`coyomap preindex --root <repo>`, so the viewer's symbol search stays aligned with the re-pinned
map), keep the change log under `.coyomap/changes/<from>-<to>.json` with its rendered
`.md` beside it, and commit the model + markdown view + pre-index + `provenance.json` + log with the code.

**Drilling deeper (refine altitude in place — never a second map file).** When a subsystem is too big
to detail at its altitude (e.g. a `plugins` area holding dozens of feature units), go finer **inside the
one map**, three ways:
- **Nest** — add child subsystems (their `Parent` is the bigger `S`) and move the members onto them.
- **Flatten** — dissolve a level that isn't pulling its weight (a single-child wrapper, a group the
  balance check flags as redundant): reparent its children onto its own parent and delete the group
  row. Pure regrouping — no edge moves, since a subsystem is never an edge endpoint.
- **Promote a leaf component into a subsystem** — when a component turns out to *be* a group (its
  Purpose enumerates many sub-units; the validator nudges this), retire the component, add a subsystem in
  its place, and add its real units as components under it. **Re-trace its edges**: the old component's
  aggregate edges (`C — verb → X`) must be re-pointed to the specific new components — a subsystem can't
  be an edge endpoint, so the validator's "every reference resolves" check fails on any leftover edge
  to the retired id, which forces (and guards) the re-trace.

All three are ordinary single-map edits; the viewer then drills the new level automatically. **Altitude may
be uneven** — refine only where you need detail; an area you haven't drilled stays a single box. This
**supersedes child maps** (a second `.coyomap/<area>/project-map.md`): a separate file is a separate ID
space, so links can't cross it and Analyze/Accept won't track it — see [dispatch](method/dispatch.md).

**How to apply.** Lead with the behavioral layer (T0 Goal → Glossary → Roles → Use cases →
Happy Path); on a non-trivial repo run the **pre-index** next (never before the behavioral
draft — GR1), then build structural Level 0 (T1–T3) using its weight map to set altitude;
generate the rest on demand as the reader drills. Always attach `file:line` (the pre-index's
symbol index gives correct ones). Label every entry point and every relationship as
verified vs inferred — that is where wrong guesses hide.
