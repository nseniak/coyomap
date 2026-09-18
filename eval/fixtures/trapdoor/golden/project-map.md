# trapdoor — Codebase Analysis

<!-- GENERATED VIEW — do not edit. The source of truth is project-map.json; regenerate this
     file with `coyomap render project-map.json project-map.md`. -->

> Built with the **coyomap** method. Behavioral layer first (Goal → Glossary → Roles →
> Use cases → Happy Path), then the structural machine (Components → Entry points /
> Model / Deps → Flows + Edges), joined at **use case ↔ flow**.
> The committed source of truth is `project-map.json` (JSON); this file is a generated
> view. IDs, cross-references, and confidence tags are validated by
> `coyomap validate project-map.json`.
> **Commit:** `fixture` · **Committed:** `2026-07-29` · **Built:** `2026-07-29 15:00`

---

## T0 — Goal (the anchor)

trapdoor is a synthetic ticketing service that exists to be MAPPED WRONG. Every directory in it plants a defect class that four real coyomap builds produced, so a regression suite can assert what the map tooling says about a real tree rather than about a toy in-memory object. Support agents move tickets through a declared lifecycle, reporters comment on them, and a background worker rolls resolved tickets up; that product story is only realistic enough to hang the traps on.

---

## Glossary — the ubiquitous language

| Term | Meaning | Defined / used in |
|---|---|---|
| **Tenant** | the customer account a ticket belongs to; every read and write is scoped to one | [gate.py](src/auth/gate.py:32) |
| **Lifecycle** | the five declared ticket states and the transitions between them | [states.py](src/lifecycle/states.py:14) |
| **Channel** | a named pub/sub topic the publisher writes and (sometimes) a consumer drains | [publisher.py](src/messaging/publisher.py:29) |
| **Trap** | a defect deliberately planted in this tree, declared in traps.yaml, asserted by one regression layer | [traps.yaml](traps.yaml:1) |

---

## Roles (actors)

`Audience` says WHICH SIDE this actor is on: `internal` = the side of the company that ships the product,
`user` = everyone else. On a program it is whose machine it is, so a bought service is `internal`.
Every capability's audience is derived from it.

| Role | Kind | Audience | What they want | Use cases they drive |
|---|---|---|---|---|
| **Reporter** | human |  | to add context to a ticket they raised and see what happened to it | UC2, UC4 |
| **Support agent** | human |  | to work a tenant's queue: find tickets, read them, and move them along the lifecycle | UC1, UC2, UC3, UC5 |

---

## Use cases

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC1** | Browse a tenant's tickets | Support agent | An agent asks for a tenant's queue, optionally filtered by state | they get the list of tickets they are allowed to see, each with its state and comment count. |
| **UC2** | Read one ticket | Support agent | Someone opens a ticket by id | they see its title, state, assignee and its comment thread, or a 404 when the ticket belongs to another tenant. |
| **UC3** | Move a ticket along its lifecycle | Support agent | An agent posts a target state | the transition is checked against the declared table, the ticket is stored in its new state, re-indexed, and a state-change event is published. |
| **UC4** | Comment on a ticket | Reporter | A reporter posts text on a ticket they may write | the comment is appended to the ticket document and the thread comes back one longer. |
| **UC5** | Take an advisory lock | Support agent | An operator claims a named lock before a bulk job | the lock row records the holder, so a second claim can see who holds it. |

---

## Happy Path — the spine (an ordered walk through the use cases)

The happy-path ordering of use cases. Each step IS a use case (its `*(UCn)*` tag
names it); the step's detail lives in that use case's T6 flow. An optional `why:`
line records the prerequisite that fixes the step's position.

**HP1 — Browse a tenant's tickets** *(UC1)*
**HP2 — Read one ticket** *(UC2)*
why: needs a ticket id from the queue listed in HP1
**HP3 — Comment on a ticket** *(UC4)*
why: the ticket opened in HP2 is the one being commented on
**HP4 — Move a ticket along its lifecycle** *(UC3)*
why: the comment thread from HP3 is what the agent read before deciding

---

## Subsystems (S) — the container altitude

| ID | Subsystem | Purpose | Parent | Tech | Source | Conf. |
|---|---|---|---|---|---|---|
| **S1** | Ticket workflow | Everything that answers a ticket request end to end: the HTTP handlers, the application service that orchestrates them, and the repository that is the system of record. This is where traps O1 and O2 live: the handlers look like they own the datastore and do not. |  | Python ([Dockerfile.api](Dockerfile.api:4)) | src/api/ | verified |
| **S2** | Eventing | The asynchronous half: the publisher that names three channels, the one consumer that drains a channel, and the plugin family that reacts. Traps M1-M4 are all here. |  |  | src/messaging/ | verified |
| **S3** | Notification plugins | Eight identically-shaped plugin directories, each listening on one channel and forwarding a shaped payload to the analytics sink. A homogeneous family: it reads as a list, not as eight decisions. | S2 |  | src/plugins/ | verified |
| **S4** | Platform runtime | The cross-cutting machinery every request and every worker pass runs through: authorisation, the lifecycle table, escalation policy, the worker template and its one concrete worker, the client factory, and the two process entry points. |  |  | src/auth/ | inferred |
| **S5** | Shared validation | A flat toolkit of value validators. Past both leaf caps with no subdirectory to recurse into, so it is split into two cohesive components rather than folded into one box (trap G2). |  |  | src/flatpack/ | verified |
| **S6** | Web UI | The browser half: a file-per-component presentational tree plus its hyperscript runtime. The FILE cap binds here, so the code-derived expectation E lands far above the honest altitude (trap G1). |  | TypeScript ([package.json](web/package.json:2)) | web/src/ | verified |

---

## T1 — Components

| ID | Component | Subsystem | Purpose | Depends on | Conf. | Runs in |
|---|---|---|---|---|---|---|
| **C1** | Ticket read handlers | S1 | The read side of the HTTP surface: fetch one ticket, list a tenant's queue, list a thread. Every handler authorises, then forwards to the ticket service and renders the result. It owns no collection and issues no store call of its own. |  | verified | api, standalone |
| **C2** | Ticket write handlers | S1 | The mutating HTTP surface: transition a ticket, append a comment, claim a lock. It calls .save() through the service, which is exactly why it reads like the system of record without being one. |  | verified | api, standalone |
| **C3** | Ticket service | S1 | Application logic for the ticket lifecycle: tenant-scoped fetch, listing, transition-and-announce, comment append, and lock acquisition. The component that really holds the repository and the publisher. |  | verified | api, worker, standalone |
| **C4** | Ticket repository | S1 | The system of record for tickets, comments and attachments. It issues every document-store call in the fixture: the ticket upsert, the secondary search-index write, and the advisory lock rows. |  | verified | api, worker, standalone |
| **C5** | Authorisation gate | S4 | Decides whether a principal may read or write a tenant's tickets. The write check composes scope, tenant and lifecycle state into one predicate and raises far below its own header. |  | verified | api, standalone |
| **C6** | Lifecycle table | S4 | The declared ticket states and the transition table between them, plus the guard that refuses an illegal move. The one lifecycle in this tree that a states machine may cite. |  | verified | api, worker, standalone |
| **C7** | Escalation policy | S4 | Counts breaches against a retry budget and decides whether to page. Its docstring describes a five-phase lifecycle that no code implements. |  | verified | worker |
| **C8** | Event publisher | S2 | Publishes three named channels through an injected transport. Because the transport is a seam, this component names no broker library anywhere in its own code. |  | verified | api, worker, standalone |
| **C9** | Comment consumer | S2 | The only consumer in the tree: a continuous loop that drains the comment channel and fans each message out to registered handlers. |  | verified | worker |
| **C10** | Worker template | S4 | The abstract template method every background worker follows: prepare, do the subclass work, record. It is never deployed on its own. |  | verified |  |
| **C11** | Report worker | S4 | The one concrete worker: sweeps each tenant's tickets on a cron schedule and produces a resolved-ticket rollup. |  | verified | worker |
| **C12** | Client factory | S4 | Reads configuration and hands back configured analytics and error-sink handles. Constructing a client opens no socket and sends nothing. |  | verified | api, worker, standalone |
| **C13** | Retry policy | S4 | Exponential backoff with a ceiling, plus the retry header it produces. Imports two types it never uses. |  | verified | api, worker, standalone |
| **C14** | HTTP process entry | S4 | The api unit's process entry point: a minimal route table whose six registrations are the whole external HTTP surface. |  | verified | api, standalone |
| **C15** | Worker process entry | S4 | The worker unit's process entry point: builds the consumer, reads the cron schedule and supervises worker passes. Self-activated only. |  | verified | worker |
| **C16** | Slack plugin | S3 | Reacts to the Slack notification channel and forwards a shaped payload to the analytics sink. |  | verified | worker |
| **C17** | Teams plugin | S3 | Reacts to the Microsoft Teams notification channel and forwards a shaped payload to the analytics sink. |  | verified | worker |
| **C18** | Audit plugin | S3 | Reacts to the ticket state-change channel, under the hyphenated spelling of the same channel name the publisher declares with dots. |  | verified | worker |
| **C19** | Email digest plugin | S3 | Reacts to the email notification channel and forwards a shaped payload to the analytics sink. |  | verified | worker |
| **C20** | Outbound webhook plugin | S3 | Reacts to the webhook notification channel and forwards a shaped payload to the analytics sink. |  | verified | worker |
| **C21** | Pager rota plugin | S3 | Reacts to the pager notification channel and forwards a shaped payload to the analytics sink. |  | verified | worker |
| **C22** | Metrics rollup plugin | S3 | Reacts to the metrics notification channel and forwards a shaped payload to the analytics sink. |  | verified | worker |
| **C23** | Cold archive plugin | S3 | Reacts to the archive notification channel and forwards a shaped payload to the analytics sink. |  | verified | worker |
| **C24** | Scalar validators | S5 | Validation and normalisation for quantitative value types: currency amounts, durations, percentages and version strings. One of the two cohesive groups the oversized flat folder splits into. |  | verified | api, worker, standalone |
| **C25** | Text validators | S5 | Validation and normalisation for textual value types: email addresses, host names, identifiers, markdown, phone numbers, postcodes, timezones and urls. The second group the flat folder splits into. |  | verified | api, worker, standalone |
| **C26** | Generated wire types | S4 | Machine-emitted message classes carrying an @generated banner. Heavy by weight, one box by judgement: the whole directory is regenerated from a schema and holds no decision a reader needs. |  | verified | api, worker, standalone |
| **C27** | Ticket UI components | S6 | Fourteen tiny presentational components — one file each — rendering the ticket list, a ticket row, the comment thread and the surrounding chrome. |  | verified | web-dev |
| **C28** | Web runtime | S6 | The minimal hyperscript helper every UI component builds its tree with. |  | verified | web-dev |

---

## T2 — External dependencies

| ID | Name | Kind | Bucket | Type | Used for | Where configured | Conf. | Deployment-linked |
|---|---|---|---|---|---|---|---|---|
| **D1** | MongoDB | datastore | Data & storage | document database | Stores the ticket documents, their embedded comment threads, and the advisory lock rows. The system of record for everything the product remembers. | [config.default.env](config.default.env:16) | verified |  |
| **D2** | Redis | messaging | Messaging & delivery | pub/sub broker | Carries the three named channels the publisher writes and the one the consumer drains. | [config.default.env](config.default.env:20) | verified |  |
| **D3** | OpenSearch | datastore | Data & storage | search index | Holds a denormalised copy of each ticket's title, body and tenant so the queue can be searched. Shares its name with the compose service that runs it. | [config.default.env](config.default.env:24) | verified |  |
| **D4** | Analytics SaaS | service | Observability | hosted product-analytics service | Receives one event per plugin reaction. The client is built centrally and used by the eight plugins. | [config.default.env](config.default.env:28) | verified |  |
| **D5** | Error reporting SaaS | service | Observability | hosted error tracker | Receives unhandled exceptions. Its client is constructed by the factory and, in this fixture, wired to nothing else. | [config.default.env](config.default.env:30) | inferred | yes |

---

## T3 — How to run / build / test

| Action | Command | Source |
|---|---|---|
| Run the whole stack for local development | docker compose --profile dev up | docker-compose.yml:16 |
| Run the single-container variant | docker compose --profile standalone up | docker-compose.yml:52 |
| Build the frontend bundle baked into the standalone image | npm run build | web/package.json:5 |

---

## T4 — Entry points

| Kind | Trigger | Code entity | Component | Cadence |
|---|---|---|---|---|
| http-route | GET /tickets/{id} — an agent opens one ticket | [http.py](src/entrypoints/http.py:37) | C1 |  |
| http-route | GET /tickets — an agent lists a tenant's queue | [http.py](src/entrypoints/http.py:38) | C1 |  |
| http-route | GET /tickets/{id}/comments — an agent reads a thread | [http.py](src/entrypoints/http.py:39) | C1 |  |
| http-route | POST /tickets/{id}/transition — an agent moves a ticket | [http.py](src/entrypoints/http.py:40) | C2 |  |
| http-route | POST /tickets/{id}/comments — a reporter appends a comment | [http.py](src/entrypoints/http.py:41) | C2 |  |
| http-route | POST /locks/{key} — an operator claims an advisory lock | [http.py](src/entrypoints/http.py:42) | C2 |  |
| event-consumer | the comment channel delivers a message to the continuous drain loop | [consumer.py](src/messaging/consumer.py:33) | C9 | continuous ([consumer.py](src/messaging/consumer.py:36)) |
| job | the supervisor fires the report rollup on its cron schedule | [report_worker.py](src/base/report_worker.py:18) | C11 | */15 * * * * ([report_worker.py](src/base/report_worker.py:13)) |

---

## Subdomains (SD) — bounded contexts of the domain model

| ID | Subdomain | Purpose | Parent | Source | Conf. |
|---|---|---|---|---|---|
| **SD1** | Ticket thread | The ticket and everything embedded in it — the comment thread and the attachments hanging off each comment. |  | src/domain/models.py:21 | verified |
| **SD2** | Operational records | Rows the product writes for its own operation rather than for a user: the audit trail and the advisory locks. |  | src/domain/models.py:66 | verified |

---

## T5 — Domain model (domain cards)

**E1 — Ticket** *(D1.tickets — collection; one document per ticket, with the comment thread embedded)*
SUBDOMAIN: SD1
MEANING: A unit of work raised by a reporter and worked by an assignee, carrying its position in the declared lifecycle.
FIELDS: id:str · tenant:str · title:str · state:TicketState · reporter:str · assignee:str · comments:E2
RELATIONS: contains 1→* E2
STATES: TRIAGE → ACCEPTED · TRIAGE → ARCHIVED · ACCEPTED → IN_PROGRESS · ACCEPTED → ARCHIVED · IN_PROGRESS → RESOLVED · RESOLVED → ARCHIVED — [states.py](src/lifecycle/states.py:14)
SOURCE: [models.py](src/domain/models.py:21)

**E2 — Comment** *(D1.tickets — embedded; rides its parent ticket document)*
SUBDOMAIN: SD1
MEANING: A note appended to a ticket. Embedded in its ticket document rather than stored as its own row.
FIELDS: id:str · ticket_id:str · author:str · text:str · attachments:E3
RELATIONS: contains 1→* E3
SOURCE: [models.py](src/domain/models.py:41)

**E3 — Attachment** *(D1.tickets — embedded; rides the comment that rides the ticket)*
SUBDOMAIN: SD1
MEANING: A file hung off a comment. Only the pointer is stored here; the bytes live in object storage.
FIELDS: id:str · comment_id:str · filename:str · object_key:str
SOURCE: [models.py](src/domain/models.py:50)

**E4 — AuditEntry** *(D1.audit_entries — collection; appended through the generic plugin bus, so no component carries a write edge to it)*
SUBDOMAIN: SD2
MEANING: An immutable record of one ticket state change. TRAP P1: nothing in this fixture persists it, so it lands in the no-owning-component advisory, which offers no recordable escape.
FIELDS: id:str · ticket_id:str FK→E1 · actor:str · from_state:str · to_state:str
RELATIONS: references *→1 E1
SOURCE: [models.py](src/domain/models.py:60)

**E5 — LockDoc** *(D1.locks — collection; infra-only; named by no use case narrative)*
SUBDOMAIN: SD2
MEANING: An advisory lock row recording who holds a named lock and until when.
FIELDS: key:str · holder:str
SOURCE: [models.py](src/domain/models.py:78)

---

## Non-entity types (plumbing, deliberately unmodelled)

| Type | Source | Why |
|---|---|---|
| Principal | src/auth/gate.py:18 | the request-scoped caller identity, not a stored concept the map describes |
| WorkerResult | src/base/worker_base.py:16 | the return shape of one worker pass, never persisted |
| ClientConfig | src/clients/analytics_factory.py:16 | connection settings read from the environment, not a domain concept |
| Escalation | src/lifecycle/escalation.py:29 | in-memory breach counting; nothing stores it |

---

## T6 — Use-case flows

**UC1 — Browse a tenant's tickets**
1. Support agent → C1 : asks for the tenant's queue, optionally filtered by state
2. C1 → C5 : checks the caller may read this tenant @ [passthrough_controller.py](src/api/passthrough_controller.py:36)
3. C1 → C3 : asks the service for the tenant's tickets @ [passthrough_controller.py](src/api/passthrough_controller.py:37)
4. C3 → C4 : loads each candidate ticket document @ [ticket_service.py](src/services/ticket_service.py:34)
5. C3 → E1 : reads each Ticket to filter the list by state @ [ticket_service.py](src/services/ticket_service.py:36)
6. C1 → Support agent : returns the rendered queue

**UC2 — Read one ticket**
1. Support agent → C1 : opens a ticket by id
2. C1 → C5 : checks the caller may read this tenant @ [passthrough_controller.py](src/api/passthrough_controller.py:29)
3. C1 → C3 : asks the service for the ticket @ [passthrough_controller.py](src/api/passthrough_controller.py:30)
4. C3 → C4 : loads the ticket document by id @ [ticket_service.py](src/services/ticket_service.py:24)
5. C3 → E1 : reads the Ticket and rejects it when the tenant does not match @ [ticket_service.py](src/services/ticket_service.py:25)
6. C1 → Support agent : returns the ticket with its comment thread

**UC3 — Move a ticket along its lifecycle**
1. Support agent → C2 : posts the target state for a ticket
2. C2 → C3 : fetches the ticket the transition applies to @ [record_controller.py](src/api/record_controller.py:26)
3. C2 → C5 : checks the caller may write in the ticket's current state @ [record_controller.py](src/api/record_controller.py:30)
4. C3 → C6 : checks the move against the declared transition table @ [ticket_service.py](src/services/ticket_service.py:43)
5. C3 → E1 : writes the Ticket in its new state @ [ticket_service.py](src/services/ticket_service.py:44)
6. C4 → D1 : upserts the ticket document @ [ticket_repo.py](src/store/ticket_repo.py:46)
7. C4 → D3 : re-indexes the ticket's searchable fields @ [ticket_repo.py](src/store/ticket_repo.py:50)
8. C3 → C8 : announces the state change on its channel @ [ticket_service.py](src/services/ticket_service.py:46)
9. C8 → D2 : sends the state-change body to the broker @ [publisher.py](src/messaging/publisher.py:41)
10. C2 → Support agent : returns the ticket's new state

**UC4 — Comment on a ticket**
1. Reporter → C2 : posts comment text on a ticket
2. C2 → C3 : fetches the ticket being commented on @ [record_controller.py](src/api/record_controller.py:35)
3. C2 → C5 : checks the reporter may write in this state @ [record_controller.py](src/api/record_controller.py:38)
4. C3 → E2 : appends the new Comment to the ticket's thread @ [ticket_service.py](src/services/ticket_service.py:50)
5. C4 → D1 : upserts the ticket document carrying the new comment @ [ticket_repo.py](src/store/ticket_repo.py:46)
6. C2 → Reporter : returns the new thread length

**UC5 — Take an advisory lock**
1. Support agent → C2 : claims a named lock before a bulk job
2. C2 → C5 : checks the caller may write in this tenant @ [record_controller.py](src/api/record_controller.py:51)
3. C2 → C3 : asks the service to take the lock @ [record_controller.py](src/api/record_controller.py:52)
4. C3 → E5 : writes the LockDoc recording the holder @ [ticket_service.py](src/services/ticket_service.py:56)
5. C4 → D1 : upserts the lock row @ [ticket_repo.py](src/store/ticket_repo.py:58)
6. C2 → Support agent : returns the key and its holder

---

## Operational dimensions — the standard core four

### Deployment & topology

| Unit | Runs on | Exposed as | Config source |
|---|---|---|---|
| api | A Python 3.11 container built from Dockerfile.api, started with the http entry module. | HTTP on port 8080 | config.default.env, injected by the compose env_file directive |
| worker | The same Dockerfile.api image, started with the worker entry module instead. | No listener — self-activated work only | config.default.env, injected by the compose env_file directive |
| web-dev | A node:20-alpine container running the Vite dev server. This is the ONLY environment in which the frontend is a live process; elsewhere it is a bundle baked into another image. | HTTP on port 5173 | web/package.json scripts |
| standalone | A single container built from Dockerfile.standalone, serving both the API and the baked frontend bundle. | HTTP on port 80 | config.default.env, copied into the image |

### Observability

| Signal | Where emitted | Where viewed | Alerts |
|---|---|---|---|
| Analytics events, one per plugin reaction | Each plugin handler queues an event on the analytics client the factory built; the queue is in-process and flushed by the client. | The hosted analytics product configured by ANALYTICS_URL. | None configured in this fixture. |
| Unhandled exceptions | The error client the factory constructs. In this fixture nothing installs it as a handler, so nothing is actually reported — a deliberate gap. | The hosted error tracker configured by ERRORS_URL. | None configured in this fixture. |

### Security & auth

Legacy `security[]` rows: this map predates the fold and has not been rebuilt.

| Decision | Enforced at | Risk note |
|---|---|---|
| *(legacy row)* Ticket write routes (transition, comment, lock) — Any caller the router reaches, carrying a principal with scopes and a tenant. | [src/auth/gate.py:62](src/auth/gate.py:62) | The check composes scope, tenant and lifecycle state and raises about thirty lines below its own header. Anchoring it at the header is trap A1: the header cannot act, so a header anchor claims enforcement at a line that never enforces. |
| *(legacy row)* Ticket read routes — Any caller the router reaches; the only gate is the tenant comparison. | [src/auth/gate.py:72](src/auth/gate.py:72) | Tenant-only. No scope is required to read, so any authenticated principal of a tenant sees every ticket in it. |

### Config & environments

| Key | Purpose | Default | Per-env / secret? |
|---|---|---|---|
| PRIMARY_URI | Document-store connection string. | mongodb://primary:27017/trapdoor | Per environment; credentials are injected by the platform, never stored in the file. |
| BROKER_URL | Broker connection string for the pub/sub channels. | redis://broker:6379/0 | Per environment. |
| SEARCH_URL | Search-index endpoint the repository re-indexes into. | http://search:9200 | Present in the cloud profile only. |
| ANALYTICS_TOKEN | Credential for the hosted analytics service. | __injected_at_deploy__ | SECRET — the committed file carries a placeholder; the real value is injected at deploy time. |
| ESCALATION_GRACE_SECONDS | How long an escalation waits before it may page. | 900 | Same everywhere. |

---

## Relationships — backbone edge list

| From | Verb | To | Why | Where (example) |
|---|---|---|---|---|
| C14 | routes-to | C1 | mounts the three read routes on the read handlers | [http.py](src/entrypoints/http.py:37) |
| C14 | routes-to | C2 | mounts the three mutating routes on the write handlers | [http.py](src/entrypoints/http.py:40) |
| C1 | uses | C3 | forwards every read to the ticket service and renders what comes back | [passthrough_controller.py](src/api/passthrough_controller.py:30) |
| C2 | uses | C3 | forwards every mutation to the ticket service | [record_controller.py](src/api/record_controller.py:30) |
| C1 | enforces | C5 | authorises each read against the caller's tenant before touching the service | [passthrough_controller.py](src/api/passthrough_controller.py:29) |
| C2 | enforces | C5 | authorises each mutation against scope, tenant and lifecycle state | [record_controller.py](src/api/record_controller.py:30) |
| C3 | uses | C4 | loads and stores every ticket, comment and lock through the repository | [ticket_service.py](src/services/ticket_service.py:24) |
| C3 | uses | C6 | checks each requested move against the declared transition table | [ticket_service.py](src/services/ticket_service.py:43) |
| C3 | uses | C8 | announces state changes on the event channel after a successful transition | [ticket_service.py](src/services/ticket_service.py:46) |
| C3 | reads | E1 | filters tickets by tenant and state before returning them | [ticket_service.py](src/services/ticket_service.py:25) |
| C3 | writes | E2 | appends new comments to a ticket's thread | [ticket_service.py](src/services/ticket_service.py:50) |
| C3 | writes | E5 | records the holder of a claimed advisory lock | [ticket_service.py](src/services/ticket_service.py:56) |
| C4 | persists | E1 | upserts the ticket document, which is the system of record for the ticket | [ticket_repo.py](src/store/ticket_repo.py:46) |
| C4 | persists | E2 | writes the embedded comment thread as part of the ticket document | [ticket_repo.py](src/store/ticket_repo.py:46) |
| C4 | persists | E3 | writes the embedded attachment pointers as part of the ticket document | [ticket_repo.py](src/store/ticket_repo.py:46) |
| C4 | persists | E5 | upserts the advisory lock rows | [ticket_repo.py](src/store/ticket_repo.py:58) |
| C4 | writes | D1 | upserts ticket and lock documents into the document store | [ticket_repo.py](src/store/ticket_repo.py:46) |
| C4 | writes | D3 | re-indexes each ticket's searchable fields into the search index | [ticket_repo.py](src/store/ticket_repo.py:50) |
| C8 | emits | D2 | publishes the three named channels through the injected transport | [publisher.py](src/messaging/publisher.py:41) |
| C9 | listens-to | D2 | drains the comment channel in a continuous loop | [consumer.py](src/messaging/consumer.py:32) |
| C11 | extends | C10 | implements the template's work step as a resolved-ticket rollup | [report_worker.py](src/base/report_worker.py:15) |
| C11 | uses | C4 | loads each tenant's tickets to build the rollup | [report_worker.py](src/base/report_worker.py:31) |
| C11 | reads | E1 | counts resolved tickets per tenant | [report_worker.py](src/base/report_worker.py:36) |
| C15 | uses | C9 | builds the consumer the worker process drains its channel with | [worker.py](src/entrypoints/worker.py:15) |
| C15 | uses | C11 | supervises the report worker's passes and stops the consumer when it fails repeatedly | [worker.py](src/entrypoints/worker.py:27) |
| C7 | uses | C11 | the rollup pass consults the breach budget before paging |  |
| C16 | emits | D4 | queues one analytics event per Slack reaction | [handler.py](src/plugins/p01/handler.py:30) |
| C17 | emits | D4 | queues one analytics event per Teams reaction | [handler.py](src/plugins/p02/handler.py:30) |
| C18 | emits | D4 | queues one analytics event per audit reaction | [handler.py](src/plugins/p03/handler.py:30) |
| C19 | emits | D4 | queues one analytics event per email-digest reaction | [handler.py](src/plugins/p04/handler.py:30) |
| C20 | emits | D4 | queues one analytics event per webhook reaction | [handler.py](src/plugins/p05/handler.py:30) |
| C21 | emits | D4 | queues one analytics event per pager reaction | [handler.py](src/plugins/p06/handler.py:30) |
| C22 | emits | D4 | queues one analytics event per metrics reaction | [handler.py](src/plugins/p07/handler.py:30) |
| C23 | emits | D4 | queues one analytics event per archive reaction | [handler.py](src/plugins/p08/handler.py:30) |
| C16 | uses | C12 | takes the configured analytics handle the factory built | [handler.py](src/plugins/p01/handler.py:21) |
| C9 | uses | C16 | fans each drained message out to the registered plugin handlers | [consumer.py](src/messaging/consumer.py:32) |
| C1 | uses | C27 | the browser tree renders the queue and thread payloads these handlers return |  |
| C27 | uses | C28 | builds every element through the hyperscript helper | [TicketRow.tsx](web/src/components/TicketRow.tsx:18) |
| C13 | uses | C12 | the backoff header rides the client calls the factory configures |  |
| C24 | uses | C25 | quantitative validators reuse the shared trimming and length rules the text validators declare first |  |
| C3 | uses | C24 | normalises the state and tenant strings a request carries before storing them |  |
| C4 | uses | C26 | maps ticket documents through the generated wire types on the way in and out |  |

---

## Messaging — channels & queues (the async catalog; participation is claimed by edges)

| Name | Kind | Broker | Publishers | Consumers | Payload | Source |
|---|---|---|---|---|---|---|
| **ticket.state.changed** | topic | D2 | C8 |  |  | [publisher.py](src/messaging/publisher.py:29) |
| **ticket.comment.added** | topic | D2 | C8 | C9 |  | [publisher.py](src/messaging/publisher.py:30) |
| **escalation.paged** | topic | D2 | C8 |  |  | [publisher.py](src/messaging/publisher.py:31) |

---

## Test completeness — gaps against the map

> **Tests run for this table?** The suite was NOT run to build this table — the fixture ships no test suite of its own, by design: what exercises this tree is the coyomap regression suite in tests/, not tests inside the fixture. Every row below is inferred from that outside suite, and the gaps are the deliverable.

| Target | Tested? | Test(s) | Gap / risk | Confidence |
|---|---|---|---|---|
| Authorisation gate — the composed write predicate (Authorisation gate) | no |  | Nothing exercises the scope/tenant/state composition. Its value to the regression suite is as an ANCHOR trap, not as behaviour under test. | inferred |
| Ticket repository — the upsert that makes it the system of record (Ticket repository) | partial | [test_trapdoor_tools.py](tests/test_trapdoor_tools.py) — feeds the repository's write anchor and the entity's definition line into anchor-drift as an 'is stored in' claim (trap A3) | The repository's own behaviour is never run; only the map's claims about it are checked. | inferred |
| Publisher and consumer — channel naming and the drain loop (Event publisher, Comment consumer) | no |  | No test drives a message end to end. The messaging traps are asserted against the map and the tree, not against a running broker. | inferred |
| The transition use case end to end (Move a ticket along its lifecycle) | no |  | No integration test walks route to store to channel. | inferred |

---

## Grounding — how much of this map was challenged

**42 of 42 claim(s) challenged** by fresh-context skeptics — 42 confirmed, 0 refuted, 0 unverifiable. That is the PINNED worklist: the claim surface the skeptics were handed.

> No `live_claims_digest`: nothing can confirm this record describes the map as it now stands.

Every backbone edge in this map was authored directly against the fixture's own source, which is 1.5 kLOC of hand-written code the author of the map also wrote. That makes the grounding complete but NOT independent — there was no fresh-context skeptic pass, and this map has not been through Phase 4. Treat the number as a statement about coverage, not about adversarial confidence.

---

## Coverage exceptions

- src/generated/: machine-emitted wire types regenerated from a schema; ~900 LOC folded into one component on purpose (trap G3). Reading it line by line buys nothing a reader needs.
- src/flatpack/: split into two cohesive components rather than one box (trap G2), so its individual files are deliberately not one-component-each.

---

## Entry-point coverage

- http-route: complete — walked the six router.add registrations in build_router (src/entrypoints/http.py:34).
- event-consumer: complete — the fixture has exactly one consumer, CommentConsumer.run_forever.
- job: complete — the fixture has exactly one scheduled worker, ReportWorker on the SCHEDULE constant.

---

## Map maintenance records — the build's own adjudication log

These sections answer this tool's own checks: each line records an element and why a finding about it was judged correct as it stands. They say nothing about the system being mapped.

### Happy Path coverage

- UC5: taking an advisory lock is an operator action before a bulk job, not part of the product story the spine tells. It keeps its own flow and stays off the walk.

### Balance exceptions

- granularity: 28 components against a code-derived expectation of ~23 (band 13-33) — inside the band, recorded here only because the FILE cap binds on web/src/components (median file 24 LOC), which is trap G1 and would otherwise read as an unexplained agreement.
- entity-flows: not recorded — the flows DO touch entities, deliberately, so this token stays absent as the control.


---

*Generated with coyomap from `project-map.json` — the committed source of truth. Do not edit this file; regenerate it with `coyomap render`.*
