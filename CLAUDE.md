# coyomap

## Design philosophy

What coyomap is FOR. This shapes design decisions about the map and the viewer, and
it outranks any local argument about a single screen or a single field.

- **Use cases and business rules are the two ways in, and they are PEERS.** Not a
  main screen and a detail screen. The reader understands the product starting from
  these two.
- **They are what makes the pieces mean something.** Components, records and
  interfaces on their own are an inventory. A use case or a rule ties them into a
  picture of what the product actually does.
- **The critical pieces are surfaced, not buried.** A reader gets the product's
  functionality AND the edge of its architecture without having to drill down.
- **Today "critical" means interfaces and records.** That list is NOT settled. What
  is worth surfacing will change as we use coyomap on real projects, so treat the
  list as this year's answer rather than a principle.
- **Everything else is drill-down.** A reader who wants more implementation detail
  goes and gets it.

**This is OURS. It must NEVER be written into `method.md` or `method/`.** A
map-building agent reads "use cases are the spine" as permission to delete whatever
no use case reaches. That failure has already happened once, and was reverted. The
same ban covers the related rule that we prefer information DERIVED from the use case
walks over a new authored field: it guides us when we extend the model, and it
attacks existing fields on every rebuild if the method ever states it.

**Known gap, agreed and not scheduled.** The viewer does not match this yet. It has
12 views in 4 groups, and several that should be drill-down destinations are
top-level tabs. We will restructure at some point, not now.

## Glossary

The words we use when talking about this project. Use these; don't drift back to
the code's names.

**The product**

- **map** — the whole picture coyomap produces for a project: the diagrams, the
  plain-language text on every box, and the code links. Lives in `.coyomap/`.
- **baseline** — the map as currently accepted, pinned to a commit. What a
  change is compared against.
- **snapshot** — what the map is: it describes the product as it stands at its
  pin, as if it had always been so. The story of a change, and what was before
  it, lives only in the log. A box's own words never say "now", "no longer" or
  "since the …"; `changes lint` warns when an update writes them in.
- **build** — analyzing a project from scratch and producing a new map. Throws
  away hand edits.
- **viewer** — the browser page that shows a map. Served live, never committed.
- **view** (a tab in the viewer) — one screen answering one question. Today:
  Overview, Features, Happy Path, Interfaces, Rules, Data, Glossary, Subsystems,
  Storage, Dependencies, Tests, Deployment, System, Updates.
- **group** — the three tabs above the views: Product, Under the hood, Change
  log. A group is a set of tabs, never a page you can be on. Data (the entities)
  and Glossary moved under Product on 2026-09-08, Storage under the hood, and the
  two groups they made up went. Change log arrived on 2026-09-18: time is neither
  a product view nor a machine view.
- **updates** — the Change log's one view: one row per run of `coyomap update`,
  newest first; the map's other committed versions (rebuilds, repairs, renames,
  uncommitted edits) sit folded under them with the map's own diff for each
  step. An **update's page** tells the log by feature: a section per feature it
  touches, in the Features page's order, each entry told in full under it with
  that feature's boxes as pills; then the product boxes no feature claims, then
  the machine boxes under the hood; then the waivers, the notes, and the diff
  from the version before the update to the version it made, folded. **Mark on
  the map** badges every box a version touches on every screen and puts the
  choice in the address; it replaced the Compare… button and its picker.
- **owner** (of a data area) — the feature the area's data exists FOR: the one
  that creates its records and runs their lifecycle. Authored, never derived.
- **owner with no evidence** — the map says an area exists for a feature, but no
  flow of that feature ever touches the area's records. A defect. Distinct
  from *ungrounded*, which is only ever about a missing code link.
- **saved record** — a record the product KEEPS: a row of its own, or one carried
  inside another record's row. Not everything the map names is one. A read shape
  built to answer one question, a request object, a list of fixed words: those are
  named so the map can talk about them, and the product keeps none of them. Across
  the two live maps, 142 named things and 46 saved records.
- **unstoried** — a saved record or an interface that no flow reaches. The
  map keeps it, or meets the world through it, and cannot say what for. A defect,
  and the same one twice: those two are the map's whole outside, and neither means
  anything until a story says what it is for. A record inside another one counts as
  storied when the one holding it is.
- **interface** — one place where the product meets something that is not the
  product. It sends data or events that the product itself does not consume, or
  it receives data or events the product itself did not generate. Excluded: data
  the product writes only to read back (its own database, cache, queue); code and
  build artifacts that become the product; the pipeline that builds and tests it.
  An outside reader *the map records* beats the read-back exclusion. Two things
  are deliberately NOT criteria: who runs the machine, and whether the far side
  does something "business". The word also means a code declaration in a
  TypeScript or Java project, so a map of one shows both meanings.
- **kind** (of an interface) — what kind of thing an interface IS, in one word: a
  screen, a command line, an API, files, a handoff. There are eleven of these
  words. Kind is not PURPOSE: a payment service and a crash reporter are both
  an API, and what tells them apart is the dependency's own purpose word.
  The word *shape* was used for this and is retired: it appeared nowhere in the
  map, so every sentence had to say "the shape field, called kind".
  ALWAYS SAY WHAT IT IS THE KIND OF. Four different things carry a kind and the
  vocabularies do not overlap: an interface's (11 words, above), a way in's (11
  words, the mechanism: `mcp-tool`, `http-route`), an actor's (human or software),
  a dependency's (its context group). A bare "kind" names none of them.
- **who is on the far side** — the people the map can show standing at an interface.
  Never written by hand: it is worked out from the flows. An interface with nobody
  on it is a normal answer, because the product itself is what reaches most of
  the outside services.
- **our interface / their interface** — **ours** = we design it (our command
  line, our web pages). **theirs** = someone else does (a payment processor, a
  sign-in provider). The test: if the far side vanished tomorrow, would this
  thing's design change? The word *surface* was used for this and is
  retired: two words for one idea, and the screens said one while the glossary
  said the other. *Surface* survives only in its security sense, as in attack
  surface, which is a different word.
- **a box does not repeat its picture** — the rule for what a box shows. A box
  always offers every tag it has; the PICTURE it is drawn on may drop one, and
  only one it draws itself. Two conditions, both needed: the fact is in the SAME
  picture, and the drawing JOINS it to this box (a wire, a lane, a column
  position). Being present somewhere on the page is not enough. The short form:
  the same picture draws it, and says it is this box's. A picture may never ADD
  a tag no other picture has, so a box stays one thing everywhere and each
  removal is a stated reason on one screen.
  Why the rule exists: on the Features page the actors are a whole column joined
  by wires, so naming them again on the feature card says it twice.
- **item pill** — a small tag naming one particular thing, anywhere on any
  screen: a feature, an actor, a record, a component, a door, a decision area.
  It wears that kind's own mark and colour, and clicking it opens the thing it
  names. Not a *type pill*, which says what KIND a thing is rather than which
  one. Replaces **chip**, which was the same tag drawn a second way and never
  clickable: the two had drifted into looking alike while behaving differently,
  so a reader could not tell which one they were pointing at.
  On the dashed box of a shared sub-flow the pills are still what stops
  collapsing the flow from burying the product's edge and its saved data, and
  there they are one per person, door or record inside it.
- **way in** — one address, command or tool an interface is made of. An
  interface groups many; coyomap's own command line is 32 ways in.
- **named / run / loose** — the three ways a way in can be covered by the use
  cases, as the validator's coverage line counts them. **Named**: a use case
  lists the way in as where it starts; authored, never derived. **Run**: a flow
  step sits at the way in's own code line, within 3 lines; derived from the
  flows, and the strongest evidence the map has that a use case really goes
  through the way in. **Loose**: nobody names it and no step sits on it, but a
  flow touches the component that owns it, so the check counts it as covered on
  a rule alone. A way in that is none of the three is **unclaimed**, and the
  validator warns about those per component. On 2026-09-10 coyomap's own map
  read 8 named, 25 run, 62 loose, 2 unclaimed of 97 ways in.
- **far side** — who or what is on the other side of an interface.
- **client** — what a person reaches an interface THROUGH: a browser for a web
  page, a terminal for a command line, an AI agent for an MCP address. Never an
  actor, because it wants nothing of its own; the person is the actor and the
  client carries them. Mostly implied by the interface's kind and left unsaid —
  the viewer names one only where it can do something the person did not ask for,
  which today is 2 of the 13 kinds.
- **pipe** — something on the path to a far side that is not itself an interface: a
  reverse proxy, a log shipper, the library that calls a service. Name the far
  side, never the pipe.
- **what crosses** — what goes through an interface, read off the flow
  steps drawn at it. Each of those steps says which way the data went: **in** the
  product received it, **out** it sent it, **both** one exchange ran each way.
  There is no hand-written list any more. The field that held one was removed once
  the step could carry the direction, which was the only thing it said that a step
  could not. A **door** says no direction, because the product is not at either end
  of it: a person opening someone else's console moves nothing of ours.
- **user-facing / operator-facing** — who an interface serves. Written by hand, not
  worked out: the actor field that looks like it answers this asks a different
  question, and marks a bought payment service *internal* while its interface is
  user-facing.
- **door** — a crossing between an actor and the product, at an interface, in one
  flow. Narrower: an interface is a place, a door is one crossing.
  A door works BOTH ways. A flow arrives through one, and hands its result back
  through one, and the way out is drawn even when it is the same interface the
  flow came in by. EVERY crossing takes a door, not only the two ends: an
  exchange in the middle of a flow goes through one too. Two actors reaching the same goal
  through different doors are two use cases, and a gate blocks the map otherwise.
- **change impact** — the report saying what a code change does to the map.
- **accept** — folding a change-impact report into the baseline.
- **readability check** — the validator's advisory count over every sentence a reader
  meets in the viewer: over 20 words, an em dash, a code-shaped word, an opening "It"
  or "This", a split the box never names. Style only, never accuracy: it sees the
  sentence alone, as the reader does, and rewrites nothing. A recorded line counts by
  its reason, never by its key. The audit's paid reading agents judge two more things,
  an unknown word and a sentence that says nothing specific, on a smaller set of
  fields.
- **Coyote Effect** — the situation coyomap exists for: your agent wrote a lot
  of code, it runs, and you have lost track of what is under your feet.

**The viewer's screens** (see the Notion page "feature-driven map spec" for the
design principles these come from)

- **card** — one element, shown as its name, a pill saying what type it is, and
  one sentence. One design, used everywhere an element appears.
- **type pill** — the word on a card saying what kind of thing it is. Clicking
  it shows that element in context.
- **card list** — cards stacked down the page, to be read. **card grid** —
  cards across then down, to be chosen between. **grouped card list** — a card
  list cut into sections by a heading, where the cut is not a level (People and
  Software on Actors).
- **page hero** — the block at the top of a page about one element: its pills,
  the sentence saying what it is, one line of context. It does NOT carry the
  name; the breadcrumb does.
- **element details page** — everything the map holds about one element,
  reached by clicking its card. The info pane shows only the card.
- **home view** — the one view that draws a given element type. One function
  answers "which view shows this thing".
- **drill in** — click a card. A container opens its contents; anything else
  opens its own details.
- **show in context** — click the type pill. On a diagram, select and centre
  the box. On a card list, scroll to the card and briefly ring it.
- **view question** — the one sentence a view answers. It belongs to the view,
  not to any page, so it leads the content and never changes as you drill.
- **group tab row** — the strip of group tabs: Product, Under the hood, Change
  log. The first strip under the title bar.
- **view tab row** — the strip of view tabs, under the group tab row. With
  Product open it holds Overview, Features, Happy Path, Interfaces, Rules, Data,
  Glossary.
- **the trail** — the group tab row, the view tab row and the breadcrumb, read
  as one path. Where you are is the last item in it, and nothing else names it.
  The breadcrumb's last item is the page's title, so no page draws its own
  heading, and on a page about one element it carries that element's pills.
- **source column** — the file browser and the code viewer, on the right. It is
  optional on every screen. The **source rail**, a strip on the right edge,
  opens it; the × in its header closes it.
- **product overview** — the product description, the whole of the Overview tab: two to
  four short paragraphs, in the third person, that describe and do not sell. The tab a
  reader lands on from the root page.
- **shareable link** — a viewer address that names one screen, not just the map:
  which tab, how far you drilled, and what is selected. Copy it and someone else
  opens the same screen; reload and you keep your place. The browser's own Back
  and Forward walk it, and the viewer has no Back button of its own.
- **objective** — the labelled sentence at the top of a feature's page or an
  actor's page, saying what that feature or that actor is for.
- **timeline** — the picture on a feature's page and on an actor's page: one
  line of boxes, read left to right, in the order the happy path takes.
- **box** (on a timeline) — one block of the timeline. On a feature's page each
  box is one actor. On an actor's page each box is one feature. A second
  meaning of *box*: on a view it is one drawn thing (see above).
- **station** — a dot on the timeline's line, carrying the title of one happy
  path step.
- **side stop** — a circle under the timeline's line: something this feature or
  this actor can do that the happy path never reaches.
- **lane** — one of the timeline's two bands. The happy path is the upper lane,
  everything else is the lower one.
- **gutter** — the strip on the left of the timeline that names the two lanes.
- **Interfaces** (a view) — the tab under Product, after Happy Path. It answers
  "where does this product meet the outside world?" with two sections, We define
  and We use. Each card opens that interface's own page.
- **what it reaches out to** — the block on a feature's page listing the
  interfaces that feature calls out to. It reads *not stated* on most features,
  because a feature is linked to a service only when a step of its own flow is
  drawn at that service.

**How coyomap is delivered**

- **the method** — `method.md` and the files under `method/`: the instructions
  the coding agent follows to build a map. The product's real logic lives here,
  not in code.
- **the skill** — what `make install` puts into the agent so `/coyomap` works.
- **the tools** — the small programs the agent calls while building (indexing,
  code sizing, validation).

**Working on coyomap**

- **eval** — scoring two maps of the same project to tell whether a change to
  the method made map quality better or worse.
- **retro** — reading a finished build and its chat to find what went wrong in
  the process.
- **gates** — the automatic checks a change must pass before it counts as done:
  the full test run and the type checker. Green gates only prove nothing broke;
  they never prove a change to the method is an improvement.
- **test tier** — which set of tests a change requires; picked from what was
  touched. A path given to the test command silently skips whole tiers.
- **verdict** — how an eval run rates the new map against the baseline:
  **PASS** (as good), **DRIFT** (a measurement moved further than allowed —
  needs a human look, not automatically bad), **REGRESSED** (a hard check got
  worse — blocking).

The word **gate** is also used inside the product, with a different meaning:
there it is a check a *map* must pass. Failing one is a defect in the map, not
in the code.
