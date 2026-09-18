# MCP Hero (mcpolis) — Codebase Analysis

<!-- GENERATED VIEW — do not edit. The source of truth is project-map.json; regenerate this
     file with `coyomap render project-map.json project-map.md`. -->

> Built with the **coyomap** method. Behavioral layer first (Goal → Glossary → Roles →
> Use cases → Happy Path), then the structural machine (Components → Entry points /
> Model / Deps → Flows + Edges), joined at **use case ↔ flow**.
> The committed source of truth is `project-map.json` (JSON); this file is a generated
> view. IDs, cross-references, and confidence tags are validated by
> `coyomap validate project-map.json`.
> **Commit:** `d787e06` · **Committed:** `2026-06-24` · **Built:** `2026-07-01`

---

## T0 — Goal (the anchor)

MCP Hero (codename `mcpolis`) is a self-hostable **gateway for Model Context Protocol (MCP)
servers**. Normally every person wires each MCP server into each AI client separately, with no
shared way to control access or audit calls. MCP Hero mounts many upstream MCP servers behind a
single URL and adds the missing team layer: role-based access control down to individual tools,
per-user OAuth to upstreams (encrypted tokens), hosted execution of `command:`-style stdio MCPs in
isolated sandboxes, an audit log of every tool call, and revocable service tokens for headless
agents. It runs either as a zero-config single-tenant **standalone** instance (file-backed) or as a
multi-tenant **cloud** SaaS (MongoDB + Redis + E2B; what powers mcphero.io). The audience is teams
who want a curated, governed set of MCP tools shared across their AI assistants.

---

## Glossary — the ubiquitous language

| Term | Meaning | Defined / used in |
|---|---|---|
| **MCP Hero** | User-facing brand for the gateway product | [README.md](README.md:10) |
| **mcpolis** | Internal codename for every technical artifact (modules, DBs, env vars) | [CLAUDE.md](CLAUDE.md) |
| **Organization (org)** | A tenant — the top-level isolation boundary everything is scoped to | [organization_repository.py](backend/src/mcpolis/domain/ports/organization_repository.py:41) |
| **Upstream MCP** | A backend MCP server added to the gateway whose tools are proxied | [upstream.py](backend/src/mcpolis/domain/model/upstream.py:84) |
| **Remote HTTP MCP** | Upstream reached at a URL (streamable-http transport) | [upstream.py](backend/src/mcpolis/domain/model/upstream.py:79) |
| **Hosted stdio MCP** | `command:`-style upstream the gateway runs in a sandbox | [upstream.py](backend/src/mcpolis/domain/model/upstream.py:45) |
| **Gateway** | The single MCP endpoint exposed to clients at `/mcp` or `/mcp/<slug>` | [gateway_controller.py](backend/src/mcpolis/entrypoints/controllers/gateway_controller.py:281) |
| **Tool** | An action an upstream exposes; surfaced through the gateway with a prefixed name | [upstream.py](backend/src/mcpolis/domain/model/upstream.py:161) |
| **Tool category** | readOnly / destructive / other annotation buckets used for role toggles | [policy_engine.py](backend/src/mcpolis/domain/services/policy_engine.py:61) |
| **Role** | Named permission set deciding which MCPs and tools a member may use | [settings.py](backend/src/mcpolis/domain/model/settings.py:47) |
| **Policy / argument check** | Per-tool regex allow/forbid rule on argument values, enforced before forwarding | [settings.py](backend/src/mcpolis/domain/model/settings.py:8) |
| **Auth mode** | How an upstream authenticates: service-account, admin OAuth, or per-user OAuth | [policy.py](backend/src/mcpolis/domain/model/policy.py:8) |
| **Per-user OAuth** | Each member signs in to the upstream as themselves; tokens stored encrypted | [connection_store.py](backend/src/mcpolis/adapters/repositories/connection_store.py:9) |
| **Service token** | Revocable `svct_` bearer bound to one org and one role, for headless agents | [service_token.py](backend/src/mcpolis/domain/model/service_token.py:35) |
| **Sandbox** | Isolated environment that runs a stdio MCP command | [sandbox_service.py](backend/src/mcpolis/domain/services/sandbox_service.py:277) |
| **E2B** | Hosted sandbox provider (production default) for stdio MCPs | [service.py](backend/src/mcpolis/adapters/sandbox_e2b/service.py:123) |
| **Template variable / password** | Per-MCP `${NAME}` value (plain or secret) substituted at launch | [template_var.py](backend/src/mcpolis/domain/model/template_var.py:66) |
| **Sandbox file** | Per-MCP uploaded credential file written into the sandbox at session start | [sandbox_file.py](backend/src/mcpolis/domain/model/sandbox_file.py:73) |
| **Admin MCP** | A second MCP at `/admin-mcp` for managing MCP Hero itself conversationally | [admin_mcp_controller.py](backend/src/mcpolis/entrypoints/controllers/admin_mcp_controller.py:99) |
| **Superadmin / operator** | Email-allowlisted operator with cross-org support access | [superadmin_controller.py](backend/src/mcpolis/entrypoints/controllers/superadmin_controller.py:19) |
| **Standalone vs cloud** | Single-org file-backed mode vs multi-org Mongo/Redis SaaS | [config.py](backend/src/mcpolis/entrypoints/config.py:15) |
| **Plan / subscription** | Per-org seat + feature limits (FREE vs TEAM) | [plan_policy.py](backend/src/mcpolis/domain/services/plan_policy.py:34) |
| **Audit entry** | A logged gateway action: who, what tool, policy decision, outcome, latency | [audit.py](backend/src/mcpolis/domain/model/audit.py:8) |
| **Slug** | URL-safe org name forming the gateway path `/mcp/<slug>` | [org_context.py](backend/src/mcpolis/entrypoints/middleware/org_context.py:84) |

---

## Roles (actors)

`Audience` says WHICH SIDE this actor is on: `internal` = the side of the company that ships the product,
`user` = everyone else. On a program it is whose machine it is, so a bought service is `internal`.
Every capability's audience is derived from it.

| Role | Kind | Audience | What they want | Use cases they drive |
|---|---|---|---|---|
| **Org creator** | human | user | Sign up and create an organization to govern their team's MCPs | UC1 |
| **Org admin** | human | user | Add/configure upstreams, define roles and per-tool access, manage the team, mint tokens, read audit | UC2, UC3, UC4, UC5, UC6, UC9, UC10, UC13, UC14, UC15, UC16, UC18, UC19, UC20, UC21, UC22, UC24, UC25 |
| **Team member** | human | user | Connect their AI client through the gateway and call the tools their role allows | UC7, UC8, UC12 |
| **Headless agent** | service | user | Connect without a browser sign-in and call tools under a least-privilege role | UC11 |
| **Superadmin** | human | internal | Step into orgs for support, end sessions, clear stuck connections without seeing secrets | UC23 |

---

## Capabilities — what this product does

The use-case grouping. `Audience` is DERIVED from the roles driving its use cases, so nothing on a capability can contradict its own actors.

| ID | Capability | Audience | Purpose | Parent |
|---|---|---|---|---|
| **CAP1** | Organizations & teams | user | Creating an org, growing the team around it, and winding it down. |  |
| **CAP2** | Upstream MCPs | user | Adding upstream MCP servers, authorizing them, and keeping their config current. |  |
| **CAP3** | Access control | user | Who may call which tools: roles, per-tool rules, and the tokens that carry them. |  |
| **CAP4** | Tool access via gateway | user | The runtime path a client takes to list and call tools through the gateway. |  |
| **CAP5** | Secrets & variables | user | Template variables, passwords and sandbox credential files behind upstream config. |  |
| **CAP6** | Audit & oversight | user | Reading back what happened in an org. |  |
| **CAP7** | Admin surfaces & ops | user, internal | Alternative management channels and operator support paths. |  |

---

## Use cases

### Organizations & teams *(CAP1)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC1** | Sign up and create an organization | Org creator | Google sign-in first time | name the org, land on Upstream MCPs |
| **UC13** | Invite a team member | Org admin | Add Google email, pick role, share invite link | member joins on sign-in |
| **UC14** | Change a member's role | Org admin | Edit member, pick new role | access updates on next request |
| **UC15** | Remove a team member | Org admin | Remove member | tokens revoked, per-user sessions dropped |
| **UC25** | Delete an organization | Org admin | Delete org | org and all its scoped data purged |

### Upstream MCPs *(CAP2)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC2** | Add a remote HTTP upstream MCP | Org admin | Paste URL, pick auth mode | upstream added, tools discovered |
| **UC3** | Add a hosted stdio upstream MCP | Org admin | Paste command JSON, fill variables, size sandbox | upstream added |
| **UC4** | Connect or start an upstream | Org admin | Click Connect / Start / Authenticate | live session, tools light up |
| **UC8** | Per-user OAuth to an upstream | Team member | Click Authenticate, consent in popup | personal upstream tokens stored encrypted |
| **UC9** | Shared / admin OAuth to an upstream | Org admin | Sign in once on team's behalf | every member's call goes out as admin |
| **UC20** | Import multiple MCPs at once | Org admin | Paste mcpServers JSON, pick entries | upstreams created in one go |
| **UC24** | Edit or remove an upstream | Org admin | Edit config or delete | config/variables/files/tools removed, dirty banner on edit |

### Access control *(CAP3)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC5** | Configure roles and per-MCP access | Org admin | Create role, toggle MCP enabled per role | role scoped to chosen MCPs |
| **UC6** | Configure per-tool access and argument checks | Org admin | Set 3-state tool toggles and regex allow/forbid | tool calls constrained |
| **UC10** | Mint a service token | Org admin | New token, pick name and role | `svct_` value shown once, JSON snippet given |
| **UC16** | Revoke or rotate a service token | Org admin | Revoke / create-new-then-revoke | agent's next request fails |

### Tool access via gateway *(CAP4)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC7** | Connect human AI client via Google OAuth | Team member | Point client at gateway URL, sign in | role's tools usable |
| **UC11** | Headless agent calls tools via service token | Headless agent | Send Bearer `svct_` to org gateway URL | tools at token's role, no sign-in |
| **UC12** | List and call tools through the gateway | Team member | Ask client to list/call tools | prefixed upstream tools returned and forwarded |

### Secrets & variables *(CAP5)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC18** | Manage template variables and passwords | Org admin | Add NAME values, toggle Treat-as-password | secrets encrypted and redacted |
| **UC19** | Manage sandbox credential files | Org admin | Upload file, set target path | file written into sandbox at session start |
| **UC21** | Extract an inline secret into a variable | Org admin | Paste JSON with raw token | dialog offers extraction, config rewritten to NAME |

### Audit & oversight *(CAP6)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC17** | View and filter the audit log | Org admin | Open Audit, set filters | matching entries, live SSE tail |

### Admin surfaces & ops *(CAP7)*

| ID | Use case | Actor | Trigger | Outcome |
|---|---|---|---|---|
| **UC22** | Manage MCP Hero via the Admin MCP | Org admin | Connect AI client to `/admin-mcp` | conversational management tools usable |
| **UC23** | Operator steps into an org for support | Superadmin | Enter org, end sessions or clear stuck connection | recorded, no secrets seen |


---

## Happy Path — the spine (an ordered walk through the use cases)

The happy-path ordering of use cases. Each step IS a use case (its `*(UCn)*` tag
names it); the step's detail lives in that use case's T6 flow. An optional `why:`
line records the prerequisite that fixes the step's position.

**HP1 — Sign up and create an organization** *(UC1)*
**HP2 — Add a remote HTTP upstream MCP** *(UC2)*
why: needs the org from HP1
**HP3 — Add a hosted stdio upstream MCP** *(UC3)*
why: same org as HP2
**HP4 — Connect or start an upstream** *(UC4)*
why: an upstream must exist (HP2/HP3) before it can connect
**HP5 — Configure roles and per-MCP access** *(UC5)*
why: needs discovered upstreams (HP4) to scope access to
**HP6 — Configure per-tool access and argument checks** *(UC6)*
why: refines the role from HP5
**HP7 — Invite a team member** *(UC13)*
why: needs a role (HP5) to assign
**HP8 — Connect human AI client via Google OAuth** *(UC7)*
why: the member must be invited (HP7) to authenticate into the org
**HP9 — Per-user OAuth to an upstream** *(UC8)*
why: needs a gateway session (HP8) and a per-user-OAuth upstream (HP2)
**HP10 — List and call tools through the gateway** *(UC12)*
why: needs the connected session (HP8) and allowed tools (HP6)
**HP11 — Mint a service token** *(UC10)*
why: needs a least-privilege role (HP5)
**HP12 — Headless agent calls tools via service token** *(UC11)*
why: needs the minted token (HP11)
**HP13 — View and filter the audit log** *(UC17)*
why: tool calls (HP10/HP12) must have happened to audit
**HP14 — Delete an organization** *(UC25)*
why: terminal — purges everything created above

---

## Subsystems (S) — the container altitude

| ID | Subsystem | Purpose | Parent | Source | Conf. |
|---|---|---|---|---|---|
| **S1** | App bootstrap & runtime wiring | Build the app, pick storage, assemble per-org runtimes, drain on shutdown |  | backend/src/mcpolis/entrypoints/ | inferred |
| **S2** | Gateway (MCP protocol surface) | Serve MCP clients at `/mcp`: list/call tools, route to upstreams, push changes |  | backend/src/mcpolis/entrypoints/controllers/gateway_controller.py | inferred |
| **S3** | Management MCP (admin & superadmin) | Conversational management of the gateway and of the whole instance |  | backend/src/mcpolis/entrypoints/controllers/ | verified |
| **S4** | Dashboard REST API | The `/api/*` surface the React dashboard calls |  | backend/src/mcpolis/entrypoints/routes/ | verified |
| **S5** | Identity & access | Authenticate clients/admins, mint/verify tokens, enforce roles & plans |  | backend/src/mcpolis/adapters/auth/ | inferred |
| **S13** | Gateway auth & service tokens | Bearer auth for `/mcp`: Google-backed OAuth + `svct_` service tokens | S5 | backend/src/mcpolis/adapters/auth/service_token_verifier.py | inferred |
| **S14** | Policy, roles & plans | Role→tool authorization, settings resolution, plan-limit gates, secret scan | S5 | backend/src/mcpolis/domain/services/policy_engine.py | inferred |
| **S15** | Dashboard sign-in & sessions | Browser Google login, session cookies, org-context resolution, revocation | S5 | backend/src/mcpolis/entrypoints/routes/dashboard_auth.py | inferred |
| **S6** | Org & tenancy | Org/membership CRUD, creation seeding, deletion cascade |  | backend/src/mcpolis/domain/services/org_service.py | inferred |
| **S7** | Upstream management | Define, persist, connect, and keep healthy the proxied upstream MCPs |  | backend/src/mcpolis/adapters/upstream_clients/ | inferred |
| **S16** | Upstream config & catalog | Persist upstream defs + options, load/merge mcp.json, cache discovered tools | S7 | backend/src/mcpolis/domain/services/upstream_config_service.py | inferred |
| **S17** | Upstream connections & clients | Long-lived MCP sessions: HTTP + stdio clients, the connection manager | S7 | backend/src/mcpolis/adapters/upstream_clients/client_manager.py | verified |
| **S18** | Upstream OAuth lifecycle | Token refresh, liveness probing, re-auth health email | S7 | backend/src/mcpolis/domain/services/oauth_refresh.py | inferred |
| **S8** | Sandbox execution (stdio MCPs) | Run stdio MCPs in E2B / local sandboxes; files, variables, reconcile |  | backend/src/mcpolis/adapters/sandbox_e2b/ | verified |
| **S9** | Persistence & storage | The cross-cutting storage machinery: Mongo client, field encryption, audit, migrations |  | backend/src/mcpolis/adapters/repositories/ | inferred |
| **S10** | Realtime & infra adapters | Pub/sub event stream, rate limiter, distributed lock |  | backend/src/mcpolis/adapters/ | inferred |
| **S11** | Observability & email | Structured logs, Sentry, Mixpanel, transactional email |  | backend/src/mcpolis/adapters/observability/ | verified |
| **S12** | Dashboard SPA (frontend) | The React admin + marketing + docs single-page app |  | frontend/src/ | verified |
| **S19** | Admin dashboard | Upstreams, roles/access, team, tokens, audit, gateway, variables, files | S12 | frontend/src/pages/admin/ | verified |
| **S20** | User & onboarding surfaces | End-user connect / my-tools, join & signup, per-MCP OAuth popup | S12 | frontend/src/pages/user/ | verified |
| **S21** | Marketing & docs | Public landing/pricing/legal pages + the docs renderer | S12 | frontend/src/pages/marketing/ | verified |
| **S22** | Superadmin console | Cross-org operator dashboard | S12 | frontend/src/pages/superadmin/ | verified |
| **S23** | Shared SPA infrastructure | Router, API client, query hooks, auth context, UI kit, SSE | S12 | frontend/src/api/ | verified |

---

## T1 — Components

| ID | Component | Subsystem | Purpose | Depends on |
|---|---|---|---|---|
| **C1** | App factory / wiring spine | S1 | Builds the FastAPI app, mounts every sub-app, runs lifespan background loops | C8 C21 C2 C3 |
| **C2** | Gateway MCP app builder | S2 | Wraps `/mcp` with bearer auth + org-pin + slug-aware metadata middleware | C72 C5 C12 C111 |
| **C3** | Admin MCP app builder | S3 | Wraps `/admin-mcp/{slug}` with per-org admin-role gate | C72 C6 C23 |
| **C4** | Superadmin MCP app builder | S3 | Wraps `/admin-mcp/system` with email-allowlist gate (cloud only) | C72 C7 |
| **C5** | Gateway controller (MCP server) | S2 | Low-level MCP server: list/call tools, list/read resources, prompts | C21 C24 C25 C45 |
| **C6** | Admin MCP controller | S3 | ~40 admin tools: upstream CRUD/connect, users, roles, audit | C21 C26 C22 C33 |
| **C7** | Superadmin MCP controller | S3 | 4 cross-org tools: list/get org, system status, delete org | C22 C55 |
| **C8** | Storage factory | S1 | Picks file (standalone) vs Mongo/Redis (cloud) repos; builds StorageBundle | C49 C108 C109 C107 |
| **C9** | Lifecycle / drain coordinator | S1 | Graceful SIGTERM drain; drives `/healthz` 503 while draining |  |
| **C10** | Slug-aware OAuth helpers | S2 | Per-request protected-resource metadata + `WWW-Authenticate` from org slug |  |
| **C11** | Org-context middleware | S15 | Resolves `/mcp/{slug}` → org_id, rewrites path, anti-enumeration 401 | C55 C21 |
| **C12** | Service-token org-pin middleware | S13 | Pins `svct_` bearers to their org; slug mismatch 401s, fails closed |  |
| **C13** | Rate-limit middleware (built, unwired) | S14 | Per-category limiter returning 429; present but not installed today | C109 |
| **C14** | Dashboard REST API router | S4 | Composes 14 per-concern `/api/*` routers (upstreams, roles, users, audit…) | C21 C26 C22 C41 |
| **C15** | Dashboard auth (session cookie) | S15 | Browser login/logout/callback; HMAC session cookie; require_admin | C101 C110 |
| **C16** | Gateway Google OAuth callback | S13 | Public callback completing the gateway bearer Google flow | C72 |
| **C17** | Org signup / public routes | S4 | `/api/orgs` create/list/switch/info/delete + one public invite read | C22 |
| **C18** | Upstream OAuth callback | S13 | Public callback completing per-MCP upstream OAuth via signed state | C100 C27 |
| **C19** | Sandbox / debug / superadmin REST routers | S4 | Sandbox caps, observability smoke (404-masked), client-errors, superadmin API | C37 C62 |
| **C20** | Demo MCP server (dev) | S2 | Bundled "kitchen sink" FastMCP at `/dev/mcp-demo` with 5 widget kinds |  |
| **C21** | OrgRuntimeManager | S1 | Per-org runtime lifecycle: build/cache policy_engine, registry, clients, router | C23 C24 C25 C64 |
| **C22** | OrgService | S6 | Org/membership CRUD, creation seeding, org-deletion cascade | C55 C54 C57 C62 |
| **C23** | PolicyEngine | S14 | Role→tool authorization, argument checks, is_admin | C42 C54 |
| **C24** | ToolRegistry | S2 | Per-upstream tool/resource/prompt discovery + cache; prefixed wire tools | C64 C61 |
| **C25** | ToolRouter | S2 | Route a gateway call to the right upstream session with heal+retry+audit | C23 C64 C62 C104 |
| **C26** | UpstreamConfigService | S16 | Upstream CRUD with side effects; secret-scan on save; cascade purge | C53 C40 C64 C24 |
| **C27** | UpstreamConnectionService | S17 | OAuth connect/reconnect/heal of live upstream sessions | C64 C47 C28 C100 |
| **C28** | OAuthRefresh | S18 | Background near-expiry token refresh; delete + notify on invalid_grant | C47 C107 C103 |
| **C29** | OAuthLiveness | S18 | Periodic `list_tools` probe of live sessions; feed dead ones to reconnect | C64 C27 |
| **C30** | UpstreamHealthCheck | S18 | Send signed re-auth email for tokens flagged invalid_grant | C47 C103 |
| **C31** | UpstreamRuntimeHash | S16 | SHA-256 fingerprint of runtime inputs → dashboard "dirty / restart" banner |  |
| **C32** | OAuthAppResolver | S13 | Match an upstream URL host to configured instance OAuth app credentials | C52 |
| **C33** | PlanGates | S14 | Assert plan limits (seats, upstreams, roles); raise 402 + analytics event | C34 C104 |
| **C34** | PlanPolicy | S14 | Source of truth for per-plan limits + PlanLimitExceeded |  |
| **C35** | PolicyNotifier | S2 | Debounced push of `tools/list_changed` to affected gateway sessions | C111 C24 |
| **C36** | SandboxService (boundary) | S8 | The Protocol every stdio sandbox backend implements + shared value types |  |
| **C37** | SandboxResolver | S8 | Decide which sandbox provider an org's stdio session uses |  |
| **C38** | SandboxReconciler (policy) | S8 | Reconcile live vs persisted sandboxes; orphan-kill + snapshot GC policy |  |
| **C39** | SandboxPath | S8 | Confine a materialize-file path to the sandbox home (reject traversal) |  |
| **C40** | SecretScanner | S14 | Heuristic raw-credential detection in upstream env/headers at save time |  |
| **C41** | ServiceTokenService | S13 | Service-token lifecycle: mint / list / revoke / verify | C57 |
| **C42** | SettingsResolver | S14 | Resolve effective MCP/tool access for a user or role, failing closed | C54 |
| **C43** | StdoutFraming | S8 | Bounded newline-framing of a sandboxed MCP's stdout into JSON-RPC lines |  |
| **C44** | SystemVariables / TemplateVarSubstitution | S8 | `${NAME}` substitution into command/args/env/url/headers at launch | C58 |
| **C45** | UriWrapping / UrlSafety | S2 | Wrap/unwrap upstream resource & widget URIs; SSRF deny-list on URLs |  |
| **C46** | ConnectionStore port + OAuthToken | S17 | Abstract port for stored upstream tokens + connection state; OAuthToken type |  |
| **C47** | Connection repository (file + mongo) | S17 | Stored-token store; mongo encrypts access/refresh tokens | C46 C49 |
| **C48** | Field encryption (AES-256-GCM) | S9 | HKDF-derive key; encrypt/decrypt field values with `enc:v1:` prefix |  |
| **C49** | Mongo client + OrgScopedCollection | S9 | The sole class touching a raw collection; injects org_id, transparent crypto | C48 |
| **C50** | mcp.json store | S16 | Read/write upstreams in standard mcpServers JSON (file, single-org) |  |
| **C51** | Upstream-config loader / merger | S16 | Merge mcp.json + options into UpstreamDefinitions; flatten import blobs | C52 |
| **C52** | OAuth-apps loader | S16 | Load instance OAuth app credentials from env JSON or file |  |
| **C53** | Upstream-config repository (file + mongo) | S16 | Persist UpstreamDefinitions; mongo encrypts config/options blobs | C49 |
| **C54** | Config / policy repository (file + mongo) | S14 | Persist roles, users, options (one settings doc per org) | C49 |
| **C55** | Organization repository (file + mongo) | S6 | Persist orgs + memberships; mongo enforces unique slug | C49 |
| **C56** | OAuth-state repository (file + mongo) | S13 | Persist gateway OAuth provider state (clients, tokens) per org | C49 |
| **C57** | Service-token repository (file + mongo) | S13 | Persist `svct_` registry (sha256 hash + org/label/role) | C49 |
| **C58** | Template-var repository (file + mongo) | S8 | Persist per-MCP variables/secrets; mongo encrypts the value | C49 |
| **C59** | Sandbox-file repository (file + mongo) | S8 | Persist per-MCP uploaded files; mongo encrypts contents | C49 |
| **C60** | Sandbox-persistence repository (inmem + mongo) | S8 | Track current sandbox / paused-snapshot ref per (org,upstream) | C49 |
| **C61** | Tool-catalog repository (file + mongo) | S16 | Persist discovered tool catalog so the UI survives restarts | C49 |
| **C62** | Audit repository (file + mongo) | S9 | Append-only audit log + search; mongo TTL by retention days | C49 |
| **C63** | One-shot Mongo migrations | S9 | Irreversible at-rest migrations (encrypt upstreams; normalize sandbox refs) | C49 |
| **C64** | UpstreamClientManager | S17 | Owns all long-lived MCP sessions; state machine, stall-heal, idle sweep | C65 C66 C67 C44 |
| **C65** | HTTP upstream MCP client | S17 | One streamable-http MCP connection over an SSRF-safe transport | C67 C45 |
| **C66** | stdio upstream MCP client | S17 | One stdio MCP session over the SandboxService boundary | C36 C43 |
| **C67** | Connection-task base + SSRF transport + log buffers | S17 | Shared task lifecycle; re-validating httpx transport; redacting stderr buffers | C45 |
| **C68** | E2B sandbox service | S8 | Prod SandboxService over E2B: session/pause/resume, volumes, docker daemon | C36 C70 C60 |
| **C69** | E2B sandbox reconciler | S8 | Startup sweep killing orphan sandboxes / GC unknown snapshots | C60 C38 |
| **C70** | E2B template grid | S8 | The 24-template grid (node/python/docker × 8 CPU/RAM) + capabilities |  |
| **C71** | Local-subprocess sandbox service | S8 | Dev-only no-isolation SandboxService spawning a host subprocess | C36 |
| **C72** | Gateway OAuth provider + service-token verifier | S13 | Issue gateway bearers via Google; route `svct_` to the token verifier | C41 C56 |
| **C73** | SPA root + router | S23 | Route table, QueryClient, AuthContext; DefaultRedirect resolves `/app` per role | C74 C76 |
| **C74** | API client / fetch layer | S23 | `apiFetch` with cookie auth + X-Org-Slug; ApiError/PlanLimitError typing | C14 C15 C17 |
| **C75** | React-query resource hooks | S23 | `useUpstreams` / `useFeatures` / `useOrgSlug` org-scoped caches | C74 |
| **C76** | Auth / session context | S23 | Loads `/api/auth/me`, holds user, wires Sentry + analytics, 401 handler | C74 C99 |
| **C77** | Upstreams page | S19 | Add HTTP/stdio MCP, sandbox sizing, import, live status via SSE | C75 C98 C97 |
| **C78** | Upstream detail page + LogViewer | S19 | Single-MCP edit; inline log stream over SSE; variables & files managers | C74 C84 C85 |
| **C79** | Roles & Access page | S19 | Per-role MCP access, 3-state tool toggles, category defaults, argument checks | C80 C74 |
| **C80** | McpAccessTable + ToolAccessSection | S19 | Shared access table reused by Access + User pages | C92 |
| **C81** | Users / Team page | S19 | List/add members, assign role, invite link, remove; per-user detail | C74 C80 C93 |
| **C82** | Service Tokens page | S19 | Mint/revoke `svct_` tokens scoped to one org+role; value shown once | C74 C93 |
| **C83** | Audit log page | S19 | Filterable audit table with live SSE tail | C74 C97 |
| **C84** | Template Variables manager | S19 | Per-MCP variable/password editor with write-time redaction | C74 |
| **C85** | Sandbox files manager | S19 | Per-MCP file editor; system-variable hints | C74 |
| **C86** | Org switcher / org context | S23 | Header dropdown switching active org; slug drives scoped queries | C74 |
| **C87** | Gateway connection-info page | S19 | Shows `/mcp` URL + config snippet, connected users, admin disconnect | C74 |
| **C88** | Marketing site + MarketingLayout | S21 | Public landing/pricing/legal pages under a buyer-shaped shell | C73 |
| **C89** | Docs page (markdown renderer) | S21 | `/docs/:slug` renders user docs with a curated sidebar + hash anchors | C73 |
| **C90** | Join / Signup / OAuth flow | S20 | Invite landing, org-creation signup, per-MCP OAuth popup | C74 |
| **C91** | User dashboard (Connect + My Tools) | S20 | End-user gateway setup + per-MCP connect/disconnect | C74 C97 |
| **C92** | Shared UI kit | S23 | base-ui/tailwind primitives: button, table, toggles, id-input |  |
| **C93** | Shared dialogs + badges | S23 | Confirm/Import/Promo/Secret/Upgrade dialogs; status/role badges; dirty banner | C92 |
| **C94** | Dashboard shell (layout + sidebar) | S23 | Auth-gated layout + role-aware sidebar nav | C76 C86 |
| **C95** | Admin MCP page | S19 | Read-only listing of the `/admin-mcp` tool catalog | C74 |
| **C96** | Superadmin dashboard | S22 | Cross-org browse + soft actions, gated by SuperadminGuard | C74 |
| **C97** | EventSource / SSE hook | S23 | `useEventSource` to `/api/events` backing live status / audit / connect | C14 |
| **C98** | Upstream action + config widgets | S19 | Action buttons, capacity pills, sandbox select, JSON editor, tool table | C74 |
| **C99** | Cross-cutting libs (analytics/sentry/errors) | S23 | Mixpanel, Sentry, client-error reporter, plan-limit upgrade opener, i18n | D8 D7 |
| **C100** | Pending-auth coordinator | S13 | Coordinate the upstream OAuth callback dance via signed HMAC state | C27 |
| **C101** | Dashboard Google OAuth provider + dev stub | S15 | Sign admins into the dashboard via Google (httpx); dev email-picker stub | D4 |
| **C102** | MCP SDK token-storage adapter | S13 | Implement the mcp SDK TokenStorage port over ConnectionStore | C46 |
| **C103** | Email sender (smtp + stub) | S11 | Outbound mail via aiosmtplib; stub records without sending | D6 |
| **C104** | Analytics client (Mixpanel) | S11 | Fire-and-forget product analytics with hashed emails | D8 |
| **C105** | Sentry setup | S11 | Init Sentry with user/org enrichment + header scrubbing | D7 |
| **C106** | Structlog setup + redact processor | S11 | Configure one JSON log stream; mask secret-shaped keys | D20 |
| **C107** | Distributed lock (mongo + noop) | S10 | Cross-process lock for cloud token refresh; noop for standalone | D1 |
| **C108** | Event stream (inprocess + redis) | S10 | SSE pub/sub: asyncio queues (standalone) vs Redis channels (cloud) | D2 |
| **C109** | Rate limiter (inprocess + redis) | S10 | Sliding-window limiter: deque vs Redis ZSET+Lua; fails open | D2 |
| **C110** | Session revocation (inprocess + redis) | S15 | Logged-out-cookie deny-list keyed by jti; fails open | D2 |
| **C111** | Gateway session registry | S2 | In-process map of gateway session_id → (org,user) |  |

---

## T2 — External dependencies

| ID | Name | Kind | Bucket | Type | Used for | Where configured | Conf. |
|---|---|---|---|---|---|---|---|
| **D1** | MongoDB | datastore | Data & storage | document DB (motor) | Cloud persistence for all repos + distributed lock | [config.py](backend/src/mcpolis/entrypoints/config.py:89) | verified |
| **D2** | Redis | messaging | Data & storage | in-memory store (coredis) | Pub/sub event stream, rate limiting, session revocation | [config.py](backend/src/mcpolis/entrypoints/config.py:91) | verified |
| **D3** | E2B sandboxes | platform | Infrastructure & runtime | hosted sandbox | Isolated execution of stdio MCP servers | [config.py](backend/src/mcpolis/entrypoints/config.py:207) | verified |
| **D4** | Google OAuth IdP | service | Identity & access | identity provider | Gateway client + dashboard admin sign-in | [config.py](backend/src/mcpolis/entrypoints/config.py:28) | verified |
| **D5** | Upstream MCP servers | service | Integrations | proxied MCPs | The servers whose tools the gateway aggregates | [client_manager.py](backend/src/mcpolis/adapters/upstream_clients/client_manager.py:103) | verified |
| **D6** | SMTP / Google Workspace | service | Messaging & delivery | mail submission | Re-auth + transactional email | [config.py](backend/src/mcpolis/entrypoints/config.py:148) | verified |
| **D7** | Sentry | service | Observability | error monitoring | Backend + frontend exception capture | [config.py](backend/src/mcpolis/entrypoints/config.py:117) | verified |
| **D8** | Mixpanel | service | Observability | product analytics | Fire-and-forget event tracking | [config.py](backend/src/mcpolis/entrypoints/config.py:123) | verified |
| **D9** | Elastic Cloud Serverless | platform | Observability | log store | Log storage + Kibana dashboards | [vector.toml](compose/vector/vector.toml:248) | verified |
| **D10** | Vector | platform | Observability | log forwarder | Sidecar shipping structlog JSON to Elastic | [docker-compose.yml](docker-compose.yml:192) | verified |
| **D11** | Docker / docker-compose | platform | Infrastructure & runtime | container runtime | Build + orchestrate the stack (dev/standalone/cloud/test) | [docker-compose.yml](docker-compose.yml:1) | verified |
| **D12** | nginx | platform | Infrastructure & runtime | reverse proxy | SPA serving + sticky API/MCP routing | [nginx.conf](docker/nginx.conf:1) | verified |
| **D13** | FastAPI / Starlette / uvicorn | framework | Web framework / server | web framework | Backend HTTP/ASGI server | [pyproject.toml](backend/pyproject.toml:14) | verified |
| **D14** | MCP Python SDK (`mcp`) | library | Service SDKs | protocol SDK | MCP client (upstreams) + server (gateway) | [pyproject.toml](backend/pyproject.toml:21) | verified |
| **D15** | pydantic / pydantic-settings | library | Validation / models | models + settings | Domain models + env-var Settings | [pyproject.toml](backend/pyproject.toml:12) | verified |
| **D16** | cryptography | library | Crypto / security | crypto primitives | AES-256-GCM token encryption | [pyproject.toml](backend/pyproject.toml:22) | verified |
| **D17** | motor | library | Data drivers | async Mongo driver | Cloud storage driver | [pyproject.toml](backend/pyproject.toml:36) | verified |
| **D18** | coredis | library | Data drivers | async Redis client | Pub/sub + rate-limit + revocation | [pyproject.toml](backend/pyproject.toml:44) | verified |
| **D19** | e2b SDK | library | Service SDKs | sandbox client | Lazy-imported E2B API client | [pyproject.toml](backend/pyproject.toml:51) | verified |
| **D20** | structlog | library | Logging | structured logging | Event-keyed JSON log records | [pyproject.toml](backend/pyproject.toml:27) | verified |
| **D21** | aiosmtplib | library | Service SDKs | async SMTP | Email adapter transport | [pyproject.toml](backend/pyproject.toml:55) | verified |
| **D22** | React / Vite / Tailwind / react-query / react-router | framework | Frontend / UI | SPA stack | The dashboard frontend | [package.json](frontend/package.json:16) | verified |

---

## T3 — How to run / build / test

| Action | Command | Source |
|---|---|---|
| Start standalone (from source) | `bash start.sh standalone` | start.sh |
| Start cloud (default) | `bash start.sh` | start.sh |
| Stop (`--all` also stops mongo+redis) | `bash stop.sh` | stop.sh |
| Restart (forwards flags) | `bash restart.sh` | restart.sh |
| Backend unit tests | `bash backend/run-unit-tests.sh` | backend/run-unit-tests.sh |
| Frontend unit tests | `bash frontend/run-unit-tests.sh` | frontend/run-unit-tests.sh |
| E2E (Playwright) | `bash tests/run-e2e-tests.sh` | tests/run-e2e-tests.sh |
| Integration (E2B real SDK) | `bash backend/run-integration-tests.sh` | backend/run-integration-tests.sh |
| Pyright type check | `bash backend/run-pyright.sh src/ tests/` | backend/run-pyright.sh |
| Ruff lint | `cd backend && poetry run ruff check .` | backend/pyproject.toml:90 |
| Docker standalone | `docker compose --profile standalone up --build` | docker-compose.yml:80 |
| Docker cloud (scalable) | `docker compose --profile cloud up --build` | docker-compose.yml:113 |
| Build E2B template grid | `cd runner/e2b-templates && make build` | runner/e2b-templates/build_grid.py:139 |
| Run all 3 suites concurrently | `make test-all` | Makefile:16 |

---

## T4 — Entry points

| Kind | Trigger | Code entity | Component |
|---|---|---|---|
| Process boot | `uvicorn.run(create_app(settings))` | [app.py](backend/src/mcpolis/entrypoints/app.py:2246) | C1 |
| Mounted ASGI | `/mcp` — gateway MCP (bearer) | [app.py](backend/src/mcpolis/entrypoints/app.py:2068) | C2 |
| Mounted ASGI | `/admin-mcp/{slug}` — admin MCP (per-org admin) | [app.py](backend/src/mcpolis/entrypoints/app.py:2100) | C3 |
| Mounted ASGI | `/admin-mcp/system` — superadmin MCP (allowlist) | [app.py](backend/src/mcpolis/entrypoints/app.py:2093) | C4 |
| Mounted ASGI | `/dev/mcp-demo` — demo MCP | [app.py](backend/src/mcpolis/entrypoints/app.py:2114) | C20 |
| MCP method | list/call tools, list/read resources, prompts | [gateway_controller.py](backend/src/mcpolis/entrypoints/controllers/gateway_controller.py:399) | C5 |
| MCP tool surface | ~40 admin tools | [admin_mcp_controller.py](backend/src/mcpolis/entrypoints/controllers/admin_mcp_controller.py:231) | C6 |
| HTTP route group | Dashboard REST `/api/admin/*`, `/api/user/*`, `/api/config/*`, `/api/events` | [dashboard_api.py](backend/src/mcpolis/entrypoints/routes/dashboard_api.py:73) | C14 |
| HTTP route group | Dashboard auth `/api/auth/*` (session cookie) | [dashboard_auth.py](backend/src/mcpolis/entrypoints/routes/dashboard_auth.py:217) | C15 |
| HTTP route group | Org routes `/api/orgs/*` (+ `/{slug}/public`) | [org_routes.py](backend/src/mcpolis/entrypoints/routes/org_routes.py:82) | C17 |
| HTTP route | Gateway Google OAuth callback | [google_callback.py](backend/src/mcpolis/entrypoints/routes/google_callback.py:56) | C16 |
| HTTP route | Upstream OAuth callback | [upstream_oauth_callback.py](backend/src/mcpolis/entrypoints/routes/upstream_oauth_callback.py:182) | C18 |
| HTTP route | Liveness `/health` / `/healthz` (503 draining) | [app.py](backend/src/mcpolis/entrypoints/app.py:1727) | C9 |
| Background loop | Connect all org runtimes + seed demo at boot | [app.py](backend/src/mcpolis/entrypoints/app.py:1129) | C1 |
| Background loop | Periodic upstream OAuth token refresh | [app.py](backend/src/mcpolis/entrypoints/app.py:1284) | C28 |
| Background loop | Hourly OAuth liveness probe | [app.py](backend/src/mcpolis/entrypoints/app.py:1379) | C29 |
| Background loop | Hourly re-auth health-email sweep | [app.py](backend/src/mcpolis/entrypoints/app.py:1342) | C30 |
| Background loop | Per-org policy-event listener | [app.py](backend/src/mcpolis/entrypoints/app.py:1209) | C35 |
| Boot task | E2B orphan-sandbox reconcile before traffic | [app.py](backend/src/mcpolis/entrypoints/app.py:807) | C69 |
| Signal | SIGTERM → graceful drain | [app.py](backend/src/mcpolis/entrypoints/app.py:1517) | C9 |
| SPA route | `/`, `/docs/:slug`, `/orgs/:slug/admin/*`, `/superadmin/*` | [App.tsx](frontend/src/App.tsx:136) | C73 |

---

## Subdomains (SD) — bounded contexts of the domain model

| ID | Subdomain | Purpose | Parent | Source | Conf. |
|---|---|---|---|---|---|
| **SD1** | Tenancy & access policy | Orgs, memberships, plans, roles, and the per-tool access rules |  | backend/src/mcpolis/domain/model/settings.py | verified |
| **SD2** | Upstream & transport | Upstream definitions, transports, and their auth configuration |  | backend/src/mcpolis/domain/model/upstream.py | verified |
| **SD3** | Credentials & secrets | Service tokens, stored OAuth tokens, variables, sandbox files |  | backend/src/mcpolis/domain/model/service_token.py | verified |
| **SD4** | Tool catalog | The discovered tools/resources/prompts cached per upstream |  | backend/src/mcpolis/domain/ports/tool_catalog_repository.py | verified |
| **SD5** | Audit & events | The append-only audit log and the realtime event bus |  | backend/src/mcpolis/domain/model/audit.py | verified |

---

## T5 — Domain model (domain cards)

**E1 — Organization** *(Mongo `organizations` / file `config/`)*
SUBDOMAIN: SD1
MEANING: A tenant — the top-level isolation boundary everything is scoped to.
FIELDS: id:string PK · slug:string unique · display_name:string · created_at:datetime · created_by_email:string ? · subscription:E2
RELATIONS: contains 1→1 E2 Subscription · scopes 1→* E10 UpstreamDefinition {org-scoped by org_id; no field on the definition}
SOURCE: [organization_repository.py](backend/src/mcpolis/domain/ports/organization_repository.py:15)

**E2 — Subscription** *(embedded in Organization)*
SUBDOMAIN: SD1
MEANING: The org's billing plan, held separately so future billing fields don't bloat Organization.
FIELDS: plan:E12
RELATIONS: contains 1→1 E12 PlanName
SOURCE: [subscription.py](backend/src/mcpolis/domain/model/subscription.py:19)

**E12 — PlanName** *(enum, embedded)*
SUBDOMAIN: SD1
MEANING: Enumerated plan tier.
FIELDS: free:string · team:string
SOURCE: [subscription.py](backend/src/mcpolis/domain/model/subscription.py:14)

**E3 — Membership** *(Mongo `memberships` / file)*
SUBDOMAIN: SD1
MEANING: A human user's seat in one org, carrying their role name.
FIELDS: org_id:string FK→E1 · email:string · role:string FK→E5 · created_at:datetime
RELATIONS: belongsTo *→1 E1 Organization · assignedRole *→1 E5 RoleDefinition
SOURCE: [organization_repository.py](backend/src/mcpolis/domain/ports/organization_repository.py:32)

**E4 — SettingsConfig** *(Mongo `settings` per-org / `config/settings.json`)*
SUBDOMAIN: SD1
MEANING: The per-org policy config root — upstream options, roles, and user→role assignments.
FIELDS: upstreams:E13 [] · roles:E5 [] · users:E6 []
RELATIONS: contains 1→* E13 UpstreamOptions · contains 1→* E5 RoleDefinition · contains 1→* E6 UserDefinition
SOURCE: [settings.py](backend/src/mcpolis/domain/model/settings.py:77)

**E5 — RoleDefinition** *(embedded in SettingsConfig.roles)*
SUBDOMAIN: SD1
MEANING: A named role: admin/default flags plus its access settings.
FIELDS: is_admin:bool · is_default:bool · settings:E7
RELATIONS: contains 1→1 E7 RoleSettings
SOURCE: [settings.py](backend/src/mcpolis/domain/model/settings.py:47)

**E6 — UserDefinition** *(embedded in SettingsConfig.users)*
SUBDOMAIN: SD1
MEANING: A user's role assignment inside the policy config.
FIELDS: role:string FK→E5
RELATIONS: assignedRole *→1 E5 RoleDefinition
SOURCE: [settings.py](backend/src/mcpolis/domain/model/settings.py:53)

**E7 — RoleSettings** *(embedded in RoleDefinition)*
SUBDOMAIN: SD1
MEANING: The access controls attached to a role: which MCPs and tools it may use.
FIELDS: mcp_access:E8 · tool_access:E9 [] · default_arguments:json · argument_constraints:E11 []
RELATIONS: contains 1→1 E8 McpAccessConfig · contains 1→* E9 ToolAccessConfig · contains 1→* E11 ArgumentConstraint
SOURCE: [settings.py](backend/src/mcpolis/domain/model/settings.py:34)

**E8 — McpAccessConfig** *(embedded in RoleSettings)*
SUBDOMAIN: SD1
MEANING: Auto-enable flag plus a per-MCP allow/deny map.
FIELDS: auto_enable_new:bool · mcps:json
SOURCE: [settings.py](backend/src/mcpolis/domain/model/settings.py:13)

**E9 — ToolAccessConfig** *(embedded in RoleSettings.tool_access)*
SUBDOMAIN: SD1
MEANING: Per-upstream tool allow/deny: category defaults, per-tool overrides, fallback.
FIELDS: fallback_enabled:bool ? · category_defaults:json · tools:json
SOURCE: [settings.py](backend/src/mcpolis/domain/model/settings.py:20)

**E11 — ArgumentConstraint** *(embedded in RoleSettings.argument_constraints)*
SUBDOMAIN: SD1
MEANING: A regex allow/forbid rule on a tool argument.
FIELDS: pattern:string · mode:string
SOURCE: [settings.py](backend/src/mcpolis/domain/model/settings.py:8)

**E13 — UpstreamOptions** *(embedded in SettingsConfig.upstreams)*
SUBDOMAIN: SD1
MEANING: Per-upstream display/auth options in the policy config (parallel to the runtime def).
FIELDS: display_name:string · auth_mode:string · client_id:string ? · client_secret:string ? · scopes:string [] · default_arguments:json
SOURCE: [settings.py](backend/src/mcpolis/domain/model/settings.py:57)

**E10 — UpstreamDefinition** *(Mongo `upstreams` / `mcp.json`, per-org)*
SUBDOMAIN: SD2
MEANING: A registered backend MCP server — transport choice, its config, and auth.
FIELDS: id:string PK · display_name:string · transport:E15 · stdio:E18 ? · http:E19 ? · auth:E20 · default_arguments:json
RELATIONS: contains 0..1→1 E18 StdioTransportConfig · contains 0..1→1 E19 HttpTransportConfig · contains 1→1 E20 UpstreamAuthConfig · isOfType *→1 E15 TransportType {transport field}
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:84)

**E15 — TransportType** *(enum, embedded)*
SUBDOMAIN: SD2
MEANING: How the gateway talks to an upstream: stdio sandbox or streamable HTTP.
FIELDS: stdio:string · streamable_http:string
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:11)

**E18 — StdioTransportConfig** *(embedded in UpstreamDefinition)*
SUBDOMAIN: SD2
MEANING: Launch config for a sandboxed stdio MCP: command, args, env, sandbox sizing.
FIELDS: command:string · args:string [] · env:json · cpu_vcpus:float · memory_mb:int · disk_gb:int · pids_limit:int ? · tmpfs_mb:int ? · persistent_disk_enabled:bool
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:45)

**E19 — HttpTransportConfig** *(embedded in UpstreamDefinition)*
SUBDOMAIN: SD2
MEANING: Connection config for a remote HTTP MCP: URL and static headers.
FIELDS: url:string · headers:json
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:79)

**E20 — UpstreamAuthConfig** *(embedded in UpstreamDefinition)*
SUBDOMAIN: SD2
MEANING: How the upstream authenticates: service-account token or OAuth (admin / per-user).
FIELDS: mode:E21 · token:string ? · client_id:string ? · client_secret:string ? · scopes:string [] · matched_domain:string ?
RELATIONS: usesMode *→1 E21 AuthMode {mode field}
SOURCE: [policy.py](backend/src/mcpolis/domain/model/policy.py:14)

**E21 — AuthMode** *(enum, embedded)*
SUBDOMAIN: SD2
MEANING: The upstream auth strategy.
FIELDS: service_account:string · admin_oauth:string · per_user_oauth:string
SOURCE: [policy.py](backend/src/mcpolis/domain/model/policy.py:8)

**E25 — OAuthAppEntry** *(`oauth_apps.json`, keyed by domain)*
SUBDOMAIN: SD2
MEANING: Pre-registered OAuth client credentials for an upstream domain.
FIELDS: client_id:string · client_secret:string
SOURCE: [settings.py](backend/src/mcpolis/domain/model/settings.py:68)

**E33 — UpstreamSelfDescription** *(in-memory, captured at connect)*
SUBDOMAIN: SD2
MEANING: Free-form text an upstream advertises at initialize, folded into the gateway's own initialize.
FIELDS: name:string · version:string · instructions:string ? · description:string ? · website_url:string ? · capabilities_extensions:json
RELATIONS: describes *→1 E10 UpstreamDefinition {keyed by upstream id at connect time}
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:111)

**E34 — ServerInfo** *(in-memory, from InitializeResult)*
SUBDOMAIN: SD2
MEANING: An upstream's reported server name/version/title.
FIELDS: name:string · version:string · title:string ?
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:105)

**E16 — ServiceTokenRecord** *(Mongo `service_tokens` / file registry)*
SUBDOMAIN: SD3
MEANING: A headless bearer credential pinned to one org and role; only the sha256 hash is stored.
FIELDS: token_hash:string PK · org_id:string FK→E1 · label:string · role_name:string FK→E5 · created_by:string · created_at:datetime · last_used_at:datetime ?
RELATIONS: pinnedTo *→1 E1 Organization · grantsRole *→1 E5 RoleDefinition
SOURCE: [service_token.py](backend/src/mcpolis/domain/model/service_token.py:35)

**E17 — OAuthToken** *(ConnectionStore — Mongo per-org / file)*
SUBDOMAIN: SD3
MEANING: A stored OAuth credential for an upstream (admin or per-user) with refresh bookkeeping.
FIELDS: access_token:string · refresh_token:string ? · expires_at:datetime ? · scopes:string [] · refresh_token_created_at:datetime ? · updated_at:datetime ?
RELATIONS: authorizes *→1 E10 UpstreamDefinition {keyed by (org,upstream,user) in the connection store}
SOURCE: [connection_store.py](backend/src/mcpolis/adapters/repositories/connection_store.py:9)

**E22 — TemplateVarSummary** *(TemplateVarRepository — Mongo encrypted / file)*
SUBDOMAIN: SD3
MEANING: A per-MCP `${NAME}` variable (secret or plain) substituted into upstream config at launch.
FIELDS: name:string PK · is_secret:bool · value:string ? · last_four:string ? · created_at:datetime · updated_at:datetime
RELATIONS: substitutedInto *→1 E10 UpstreamDefinition {keyed by (org,upstream)}
SOURCE: [template_var.py](backend/src/mcpolis/domain/model/template_var.py:66)

**E23 — SandboxFile** *(Mongo encrypted / file, keyed by org+upstream)*
SUBDOMAIN: SD3
MEANING: A per-MCP uploaded credential/config file the launcher writes into the sandbox before exec.
FIELDS: name:string PK · display_name:string · contents:string · target_path:string · sha256:string · size_bytes:int · created_at:datetime · updated_at:datetime
RELATIONS: writtenInto *→1 E10 UpstreamDefinition {keyed by (org,upstream)} · summarizedBy 1→1 E24 SandboxFileSummary {the metadata-only dashboard view, contents stripped}
SOURCE: [sandbox_file.py](backend/src/mcpolis/domain/model/sandbox_file.py:73)

**E24 — SandboxFileSummary** *(view DTO — never persisted with contents)*
SUBDOMAIN: SD3
MEANING: Metadata-only view of a SandboxFile (no contents) for the dashboard.
FIELDS: name:string · display_name:string · target_path:string · sha256:string · size_bytes:int · created_at:datetime · updated_at:datetime
SOURCE: [sandbox_file.py](backend/src/mcpolis/domain/model/sandbox_file.py:146)

**E26 — ToolCatalogSnapshot** *(ToolCatalogRepository — Mongo / file)*
SUBDOMAIN: SD4
MEANING: Cached per-upstream catalog of tools/resources/prompts so the admin UI renders without a reconnect.
FIELDS: tools:E27 [] · resources:E28 [] · resource_templates:E29 [] · prompts:E30 []
RELATIONS: snapshotOf *→1 E10 UpstreamDefinition {keyed by (org,upstream)} · contains 1→* E27 DiscoveredTool · contains 1→* E28 DiscoveredResource · contains 1→* E29 DiscoveredResourceTemplate · contains 1→* E30 DiscoveredPrompt
SOURCE: [tool_catalog_repository.py](backend/src/mcpolis/domain/ports/tool_catalog_repository.py:15)

**E27 — DiscoveredTool** *(embedded in ToolCatalogSnapshot.tools)*
SUBDOMAIN: SD4
MEANING: One tool advertised by an upstream, with its prefixed gateway name and schema.
FIELDS: upstream_id:string FK→E10 · original_name:string · prefixed_name:string · description:string ? · input_schema:json · title:string ? · output_schema:json ? · annotations:E31 ? · meta:json ?
RELATIONS: contains 0..1→1 E31 ToolAnnotations
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:161)

**E31 — ToolAnnotations** *(embedded in DiscoveredTool)*
SUBDOMAIN: SD4
MEANING: MCP behavior hints (readOnly/destructive/idempotent/openWorld) used in policy matching.
FIELDS: title:string ? · readOnlyHint:bool ? · destructiveHint:bool ? · idempotentHint:bool ? · openWorldHint:bool ?
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:140)

**E28 — DiscoveredResource** *(embedded in ToolCatalogSnapshot.resources)*
SUBDOMAIN: SD4
MEANING: One resource advertised by an upstream.
FIELDS: upstream_id:string FK→E10 · original_uri:string · name:string · title:string ? · description:string ? · mime_type:string ? · meta:json ?
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:179)

**E29 — DiscoveredResourceTemplate** *(embedded in ToolCatalogSnapshot.resource_templates)*
SUBDOMAIN: SD4
MEANING: One RFC 6570 resource template advertised by an upstream.
FIELDS: upstream_id:string FK→E10 · original_uri_template:string · name:string · title:string ? · description:string ? · mime_type:string ? · meta:json ?
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:197)

**E30 — DiscoveredPrompt** *(embedded in ToolCatalogSnapshot.prompts)*
SUBDOMAIN: SD4
MEANING: One prompt template advertised by an upstream, with its arguments.
FIELDS: upstream_id:string FK→E10 · original_name:string · prefixed_name:string · title:string ? · description:string ? · arguments:E32 [] · meta:json ?
RELATIONS: contains 1→* E32 PromptArgument
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:221)

**E32 — PromptArgument** *(embedded in DiscoveredPrompt.arguments)*
SUBDOMAIN: SD4
MEANING: One declared argument of a discovered prompt.
FIELDS: name:string · description:string ? · required:bool ?
SOURCE: [upstream.py](backend/src/mcpolis/domain/model/upstream.py:215)

**E35 — AuditEntry** *(Mongo `audit` / file audit log, per-org)*
SUBDOMAIN: SD5
MEANING: One audited gateway action — what tool was called and whether policy allowed it (never argument values).
FIELDS: timestamp:string · action:string · org_id:string FK→E1 · user_id:string · upstream_id:string FK→E10 · auth_mode:string · auth_identity:string · tool:string · policy_decision:string · policy_rule:string ? · response_status:string · latency_ms:float ? · session_id:string ? · outcome:string ? · error_message:string ? · client_type:string ?
RELATIONS: records *→1 E1 Organization {org_id field} · records *→1 E10 UpstreamDefinition {upstream_id field}
SOURCE: [audit.py](backend/src/mcpolis/domain/model/audit.py:8)

**E36 — Event** *(in-memory realtime bus; not persisted)*
SUBDOMAIN: SD5
MEANING: A typed message on the realtime bus, targeted at one user email or broadcast.
FIELDS: type:string · user_email:string ? · payload:json · timestamp:float
SOURCE: [events.py](backend/src/mcpolis/domain/model/events.py:9)

---

## T6 — Use-case flows

**UC1 — Sign up & create the organization**
1. Org creator → C15 : signs in with Google in the browser
2. C15 → C101 : steps to C101 (fixture backfill)
3. C101 → D4 : steps to D4 (fixture backfill)
4. C15 → C73 : redirects the signed-in creator to the app
5. Org creator → C17 : posts the new org name and slug
6. C17 → C22 : steps to C22 (fixture backfill)
7. C22 → C33 : checks seat/org plan limits
8. C22 → C55 : steps to C55 (fixture backfill)
9. C55 → C49 : steps to C49 (fixture backfill)
10. C22 → C54 : steps to C54 (fixture backfill) · seeds default admin + user roles and the creator as admin
11. C17 → Org creator : returns the created org, lands on Upstream MCPs

**UC2 — Add a remote HTTP upstream MCP**
1. Org admin → C77 : pastes the upstream URL and picks an auth mode
2. C77 → C74 : steps to C74 (fixture backfill)
3. C74 → C14 : steps to C14 (fixture backfill)
4. C14 → C26 : steps to C26 (fixture backfill)
5. C26 → C40 : steps to C40 (fixture backfill) · scans the config for raw secrets
6. C26 → C53 : steps to C53 (fixture backfill)
7. C53 → C49 : steps to C49 (fixture backfill)
8. C14 → Org admin : shows the upstream added, ready to connect

**UC3 — Add a hosted stdio upstream MCP**
1. Org admin → C77 : pastes command JSON, fills variables, sizes the sandbox
2. C77 → C74 : steps to C74 (fixture backfill)
3. C74 → C14 : steps to C14 (fixture backfill)
4. C14 → C33 : checks the stdio-upstream plan limit
5. C14 → C26 : steps to C26 (fixture backfill)
6. C26 → C53 : steps to C53 (fixture backfill)
7. C14 → C84 : steps to C84 (fixture backfill) · admin saves the `${NAME}` variables and passwords
8. C84 → C58 : steps to C58 (fixture backfill)
9. C58 → C49 : steps to C49 (fixture backfill) · encrypts secret values at rest

**UC4 — Connect / start the upstreams**
1. Org admin → C98 : clicks Connect / Start
2. C98 → C74 : steps to C74 (fixture backfill)
3. C74 → C14 : steps to C14 (fixture backfill)
4. C14 → C26 : steps to C26 (fixture backfill)
5. C26 → C64 : steps to C64 (fixture backfill)
6. C64 → C65 : steps to C65 (fixture backfill) · HTTP upstream opens a streamable-http session
7. C64 → C66 : steps to C66 (fixture backfill) · stdio upstream launches in a sandbox
8. C66 → C68 : steps to C68 (fixture backfill)
9. C68 → D3 : steps to D3 (fixture backfill)
10. C26 → C24 : steps to C24 (fixture backfill) · refresh and cache the discovered tools
11. C24 → C61 : steps to C61 (fixture backfill)
12. C14 → Org admin : tools light up, live status via SSE

**UC5 — Configure roles & per-MCP access**
1. Org admin → C79 : creates a role and toggles which MCPs it can use
2. C79 → C74 : steps to C74 (fixture backfill)
3. C74 → C14 : steps to C14 (fixture backfill)
4. C14 → C33 : checks the custom-role plan limit
5. C14 → C54 : steps to C54 (fixture backfill)
6. C54 → C49 : steps to C49 (fixture backfill)
7. C14 → C108 : steps to C108 (fixture backfill) · publishes a policy_changed event
8. C108 → C35 : steps to C35 (fixture backfill)
9. C35 → C111 : pushes tools/list_changed to affected sessions

**UC6 — Configure per-tool access & argument checks**
1. Org admin → C79 : sets 3-state tool toggles and regex allow/forbid rules
2. C79 → C80 : steps to C80 (fixture backfill)
3. C80 → C74 : steps to C74 (fixture backfill)
4. C74 → C14 : steps to C14 (fixture backfill)
5. C14 → C54 : steps to C54 (fixture backfill)
6. C14 → C108 : steps to C108 (fixture backfill)
7. C108 → C35 : steps to C35 (fixture backfill)
8. C35 → C24 : steps to C24 (fixture backfill) · refreshes the changed upstream before notifying

**UC13 — Invite a team member**
1. Org admin → C81 : adds a Google email and picks a role
2. C81 → C74 : steps to C74 (fixture backfill)
3. C74 → C14 : steps to C14 (fixture backfill)
4. C14 → C33 : checks seat capacity
5. C14 → C22 : steps to C22 (fixture backfill)
6. C22 → C55 : steps to C55 (fixture backfill)
7. C14 → Org admin : returns a shareable invite link

**UC7 — Member connects their AI client via Google OAuth**
1. Team member → C2 : points their MCP client at the gateway URL
2. C2 → C11 : steps to C11 (fixture backfill) · resolves the org slug from the path
3. C2 → C72 : steps to C72 (fixture backfill)
4. C72 → D4 : steps to D4 (fixture backfill) · completes the Google sign-in
5. C16 → C72 : steps to C72 (fixture backfill) · the Google callback finishes the bearer issue
6. C72 → C56 : steps to C56 (fixture backfill)
7. C2 → C111 : steps to C111 (fixture backfill) · registers the session under (org, user)
8. C2 → Team member : the role's tools are now available in the client

**UC8 — Member authenticates per-user OAuth to an upstream**
1. Team member → C91 : clicks Authenticate on a per-user-OAuth upstream
2. C91 → C74 : steps to C74 (fixture backfill)
3. C74 → C14 : steps to C14 (fixture backfill)
4. C14 → C27 : steps to C27 (fixture backfill)
5. C27 → C100 : steps to C100 (fixture backfill) · starts a signed pending-auth flow
6. C27 → C64 : steps to C64 (fixture backfill) · opens the upstream OAuth authorize URL
7. C18 → C100 : steps to C100 (fixture backfill) · the upstream callback completes the flow
8. C100 → C27 : steps to C27 (fixture backfill)
9. C27 → C47 : steps to C47 (fixture backfill) · stores the per-user token (encrypted in cloud)
10. C47 → C49 : steps to C49 (fixture backfill)
11. C27 → Team member : the upstream's tools become callable as themselves

**UC12 — Member lists & calls tools through the gateway**
1. Team member → C5 : asks the client to list and call a tool
2. C5 → C21 : steps to C21 (fixture backfill)
3. C5 → C23 : steps to C23 (fixture backfill) · filters tools to the member's role
4. C5 → C24 : steps to C24 (fixture backfill) · returns the prefixed wire tools
5. C5 → C25 : forwards the chosen tool call
6. C25 → C23 : steps to C23 (fixture backfill) · re-checks the call against tool + argument policy
7. C25 → C64 : steps to C64 (fixture backfill)
8. C64 → C65 : steps to C65 (fixture backfill) · dispatches to the upstream session
9. C25 → C62 : steps to C62 (fixture backfill) · audits the call decision and outcome
10. C25 → Team member : returns the tool result

**UC10 — Admin mints a service token**
1. Org admin → C82 : names a token and picks a least-privilege role
2. C82 → C74 : steps to C74 (fixture backfill)
3. C74 → C14 : steps to C14 (fixture backfill)
4. C14 → C41 : steps to C41 (fixture backfill)
5. C41 → C57 : steps to C57 (fixture backfill)
6. C57 → C49 : steps to C49 (fixture backfill)
7. C14 → Org admin : returns the raw `svct_` value once, with a config snippet

**UC11 — Headless agent calls tools via the service token**
1. Headless agent → C2 : sends `Authorization: Bearer svct_…` to the org gateway URL
2. C2 → C72 : steps to C72 (fixture backfill)
3. C72 → C41 : steps to C41 (fixture backfill) · verifies the token and resolves its org + role scopes
4. C2 → C12 : steps to C12 (fixture backfill) · pins the request to the token's org
5. C2 → C5 : steps to C5 (fixture backfill)
6. C5 → C23 : steps to C23 (fixture backfill) · authorizes tools at the token's boundary role
7. C5 → C25 : steps to C25 (fixture backfill)
8. C25 → C64 : steps to C64 (fixture backfill) · dispatches to the upstream
9. C25 → C62 : steps to C62 (fixture backfill) · audits under the `svc:` identity
10. C25 → Headless agent : returns the tool result, no sign-in needed

**UC17 — Admin reviews the audit log**
1. Org admin → C83 : opens Audit and sets user/MCP/tool filters
2. C83 → C74 : steps to C74 (fixture backfill)
3. C74 → C14 : steps to C14 (fixture backfill)
4. C14 → C62 : steps to C62 (fixture backfill)
5. C62 → C49 : steps to C49 (fixture backfill)
6. C83 → C97 : steps to C97 (fixture backfill) · subscribes to the live audit tail
7. C97 → C14 : steps to C14 (fixture backfill)
8. C14 → C108 : steps to C108 (fixture backfill) · streams new entries over SSE
9. C14 → Org admin : returns matching entries plus the live tail

**UC22 — Manage MCP Hero via the Admin MCP**
1. Org admin → C3 : connects their AI client to `/admin-mcp/{slug}`
2. C3 → C72 : steps to C72 (fixture backfill) · Google bearer auth (service tokens rejected here)
3. C3 → C23 : steps to C23 (fixture backfill) · checks the user is an admin in this org
4. C3 → C6 : steps to C6 (fixture backfill)
5. C6 → C26 : steps to C26 (fixture backfill) · runs an upstream/user/role management tool
6. C6 → C22 : steps to C22 (fixture backfill)
7. C6 → Org admin : returns the management result conversationally

**UC25 — Admin deletes the organization**
1. Org admin → C17 : confirms deleting the org
2. C17 → C22 : steps to C22 (fixture backfill)
3. C22 → C55 : steps to C55 (fixture backfill) · removes the org and memberships
4. C22 → C54 : steps to C54 (fixture backfill) · purges policy config
5. C22 → C53 : steps to C53 (fixture backfill) · purges upstream definitions
6. C22 → C47 : steps to C47 (fixture backfill) · purges stored tokens
7. C22 → C57 : steps to C57 (fixture backfill) · purges service tokens
8. C22 → C62 : steps to C62 (fixture backfill) · purges the audit log
9. C22 → Org admin : confirms the org and all scoped data are gone

---

## Operational dimensions — the standard core four

### Deployment & topology

| Unit | Runs on | Exposed as | Config source |
|---|---|---|---|
| nginx | container (cloud) | host `:80` (dropped under proxied overlay) | docker-compose.yml#L155 |
| backend (uvicorn, scale to N) | container (cloud) | internal `:8080` behind nginx; `/health` check | docker-compose.yml#L113 |
| standalone backend (serves SPA) | container / host | host `:8080`, file-backed volumes | docker-compose.yml#L80 |
| MongoDB | container (dev+cloud) | `127.0.0.1:27017` | docker-compose.yml#L33 |
| Redis | container (dev+cloud) | `127.0.0.1:6379` | docker-compose.yml#L43 |
| Vector sidecar | container (cloud) | metrics `127.0.0.1:9598` | docker-compose.yml#L192 |
| frontend | Vite `:5173` (dev) / prerendered static via nginx (prod) | dev `:5173` | start.sh |
| E2B sandboxes | remote (E2B hosted) | SDK API, 24-template grid | backend/src/mcpolis/entrypoints/config.py#L207 |

### Observability

| Signal | Where emitted | Where viewed | Alerts |
|---|---|---|---|
| structlog JSON events | backend/src/mcpolis/adapters/observability/structlog_setup.py#L74 | stdout → Vector → Elastic / Kibana | Vector throttle 5000/min/event |
| uvicorn access logs | reshaped in Vector | Elastic (`http.access.<status>`) | low-cardinality bucketing |
| Sentry errors | backend/src/mcpolis/adapters/observability/sentry_setup.py#L162 | Sentry (DSN-gated) | traces_sample_rate |
| Mixpanel analytics | backend/src/mcpolis/adapters/observability/analytics_client.py#L48 | Mixpanel (token-gated) | — |
| Health endpoints | backend/src/mcpolis/entrypoints/app.py#L1727 | nginx `/healthz`; compose healthcheck | LB checks `/healthz` |

### Security & auth

Legacy `security[]` rows: this map predates the fold and has not been rebuilt.

| Decision | Enforced at | Risk note |
|---|---|---|
| *(legacy row)* `/mcp` gateway — Google bearer OR `svct_` service token | [backend/src/mcpolis/entrypoints/app.py:353](backend/src/mcpolis/entrypoints/app.py:353) | Composite verifier routes svct_→registry, else→OAuth |
| *(legacy row)* `/mcp` org scoping — user/token scoped to one org | [backend/src/mcpolis/entrypoints/middleware/org_context.py:267](backend/src/mcpolis/entrypoints/middleware/org_context.py:267) | cross-org isolation via the slug→org contextvar |
| *(legacy row)* service-token org pin — `svct_` holder, one pinned org | [backend/src/mcpolis/entrypoints/middleware/service_token_pin.py:39](backend/src/mcpolis/entrypoints/middleware/service_token_pin.py:39) | slug mismatch 401s; fails closed if scope missing |
| *(legacy row)* `/admin-mcp/{slug}` — OAuth user who is admin in that org | [backend/src/mcpolis/entrypoints/app.py:521](backend/src/mcpolis/entrypoints/app.py:521) | per-org gate; service tokens structurally rejected |
| *(legacy row)* `/admin-mcp/system` — email in superadmin allowlist | [backend/src/mcpolis/entrypoints/app.py:668](backend/src/mcpolis/entrypoints/app.py:668) | cloud-only; allowlist is the sole gate |
| *(legacy row)* dashboard `/api/*` — signed-in user (cookie); admin via require_admin | [backend/src/mcpolis/entrypoints/routes/dashboard_auth.py:284](backend/src/mcpolis/entrypoints/routes/dashboard_auth.py:284) | HMAC cookie, 7-day TTL, optional jti revocation |
| *(legacy row)* org anti-enumeration — unknown slug → 401 (not 404) | [backend/src/mcpolis/entrypoints/routes/org_routes.py:100](backend/src/mcpolis/entrypoints/routes/org_routes.py:100) | one exception: `/{slug}/public` invite read |
| *(legacy row)* upstream OAuth callback — public, HMAC-signed state | [backend/src/mcpolis/entrypoints/routes/upstream_oauth_callback.py:107](backend/src/mcpolis/entrypoints/routes/upstream_oauth_callback.py:107) | integrity rests on the signed state |
| *(legacy row)* upstream URL fetch — gateway → upstream | [backend/src/mcpolis/domain/services/url_safety.py:152](backend/src/mcpolis/domain/services/url_safety.py:152) | SSRF deny-list (loopback/RFC1918/IMDS) |
| *(legacy row)* rate limiting (unwired) — n/a | [backend/src/mcpolis/entrypoints/app.py:1630](backend/src/mcpolis/entrypoints/app.py:1630) | middleware built but not installed today |

### Config & environments

| Key | Purpose | Default | Per-env / secret? |
|---|---|---|---|
| MODE | standalone (file) vs cloud (Mongo/Redis, multi-org) | `standalone` | per-env |
| OAUTH_PROVIDER | dashboard auth: `google` / `dev_stub` (cloud forces google) | `dev_stub` | per-env |
| SANDBOX_PROVIDER | stdio backend: `e2b` / `local-subprocess` (empty=auto) | `""` | per-env |
| SERVER_URL | advertised dashboard base URL (OAuth callback) | `http://localhost:8000` | per-env |
| GATEWAY_URL | public gateway base URL (falls back to SERVER_URL) | `""` | per-env |
| SESSION_SECRET | dashboard session signing key | `""` | secret |
| ENCRYPTION_KEY | AES-256-GCM token encryption (cloud) | `""` | secret |
| GOOGLE_CLIENT_ID | Google OAuth client id | `""` | per-env |
| GOOGLE_CLIENT_SECRET | Google OAuth client secret | `""` | secret |
| E2B_API_KEY | E2B SDK auth (required when sandbox=e2b in cloud) | `""` | secret |
| MONGO_URI / MONGO_DB_NAME | cloud Mongo connection / db | `""` / `mcpolis` | secret |
| REDIS_URL | cloud Redis connection | `""` | per-env |
| ALLOW_STDIO_MCP | enable stdio MCP servers | `True` (cloud→False) | per-env |
| SUPERADMIN_EMAILS | instance superadmin allowlist | `""` | per-env |
| SMTP_HOST/PORT/USERNAME/FROM | email transport (empty host → stub) | port `587` | per-env |
| SMTP_PASSWORD | SMTP / app password | `""` | secret |
| SENTRY_DSN | error reporting (empty disables) | `""` | per-env |
| MIXPANEL_TOKEN | analytics (empty disables; EU host) | `""` | secret |
| ELASTIC_ENDPOINT / ELASTIC_API_KEY | Vector→Elastic forwarding | n/a | secret |
| E2B_IDLE_PAUSE_SECONDS | E2B idle-pause cost knob | `60` | per-env |
| AUDIT_RETENTION_DAYS | audit log TTL floor | `365` | per-env |
| DRAIN_TIMEOUT | SIGTERM graceful drain seconds | `30.0` | per-env |

---

## Relationships — backbone edge list

| From | Verb | To | Why | Where (example) |
|---|---|---|---|---|
| C1 | uses | C8 | build the per-mode storage bundle | [app.py](backend/src/mcpolis/entrypoints/app.py:934) |
| C1 | uses | C21 | assemble per-org runtimes | [app.py](backend/src/mcpolis/entrypoints/app.py:957) |
| C1 | uses | C2 | mount the gateway MCP app | [app.py](backend/src/mcpolis/entrypoints/app.py:1091) |
| C1 | uses | C3 | mount the admin MCP app | [app.py](backend/src/mcpolis/entrypoints/app.py:1121) |
| C1 | uses | C9 | wire graceful drain | [app.py](backend/src/mcpolis/entrypoints/app.py:972) |
| C1 | uses | C105 | init Sentry before app construction | [app.py](backend/src/mcpolis/entrypoints/app.py:904) |
| C1 | uses | C104 | register the analytics singleton | [app.py](backend/src/mcpolis/entrypoints/app.py:909) |
| C1 | uses | C106 | configure the JSON log stream | [app.py](backend/src/mcpolis/entrypoints/app.py:42) |
| C1 | uses | D13 | build the FastAPI / Starlette app | [app.py](backend/src/mcpolis/entrypoints/app.py:13) |
| C1 | uses | D15 | typed env-var Settings | [app.py](backend/src/mcpolis/entrypoints/app.py:895) |
| C2 | enforces | C72 | bearer auth on the gateway | [app.py](backend/src/mcpolis/entrypoints/app.py:353) |
| C2 | routes-to | C5 | dispatch to the MCP server | [app.py](backend/src/mcpolis/entrypoints/app.py:341) |
| C2 | uses | C12 | pin service tokens to their org | [app.py](backend/src/mcpolis/entrypoints/app.py:366) |
| C2 | uses | C10 | slug-aware protected-resource metadata | [app.py](backend/src/mcpolis/entrypoints/app.py:411) |
| C2 | uses | C111 | register the gateway session | [app.py](backend/src/mcpolis/entrypoints/app.py:343) |
| C3 | enforces | C72 | bearer auth on the admin MCP | [app.py](backend/src/mcpolis/entrypoints/app.py:472) |
| C3 | enforces | C23 | per-org admin-role gate | [app.py](backend/src/mcpolis/entrypoints/app.py:554) |
| C3 | routes-to | C6 | dispatch to the admin tools | [app.py](backend/src/mcpolis/entrypoints/app.py:1119) |
| C4 | enforces | C72 | bearer auth on the superadmin MCP | [app.py](backend/src/mcpolis/entrypoints/app.py:625) |
| C4 | routes-to | C7 | dispatch to the superadmin tools | [app.py](backend/src/mcpolis/entrypoints/app.py:602) |
| C5 | uses | C21 | get the request's org runtime | [gateway_controller.py](backend/src/mcpolis/entrypoints/controllers/gateway_controller.py:535) |
| C5 | enforces | C23 | filter tools to the caller's role | [gateway_controller.py](backend/src/mcpolis/entrypoints/controllers/gateway_controller.py:412) |
| C5 | uses | C24 | render prefixed wire tools | [gateway_controller.py](backend/src/mcpolis/entrypoints/controllers/gateway_controller.py:537) |
| C5 | routes-to | C25 | dispatch a tool call | [gateway_controller.py](backend/src/mcpolis/entrypoints/controllers/gateway_controller.py:412) |
| C5 | uses | C45 | wrap/unwrap resource & widget URIs | [gateway_controller.py](backend/src/mcpolis/entrypoints/controllers/gateway_controller.py:446) |
| C5 | reads | E27 | list the discovered tools | [gateway_controller.py](backend/src/mcpolis/entrypoints/controllers/gateway_controller.py:537) |
| C6 | uses | C26 | run upstream-management tools | [admin_mcp_controller.py](backend/src/mcpolis/entrypoints/controllers/admin_mcp_controller.py:231) |
| C6 | uses | C22 | run user/org tools | [admin_mcp_controller.py](backend/src/mcpolis/entrypoints/controllers/admin_mcp_controller.py:99) |
| C6 | uses | C33 | enforce plan limits in admin tools | [admin_mcp_controller.py](backend/src/mcpolis/entrypoints/controllers/admin_mcp_controller.py:99) |
| C7 | uses | C55 | list/get/delete orgs cross-tenant | [superadmin_controller.py](backend/src/mcpolis/entrypoints/controllers/superadmin_controller.py:36) |
| C7 | uses | C22 | delete an org with cascade | [superadmin_controller.py](backend/src/mcpolis/entrypoints/controllers/superadmin_controller.py:107) |
| C8 | uses | C49 | build the Mongo client (cloud) | [storage_factory.py](backend/src/mcpolis/entrypoints/storage_factory.py:253) |
| C8 | uses | C108 | build the event stream | [storage_factory.py](backend/src/mcpolis/entrypoints/storage_factory.py:180) |
| C8 | uses | C109 | build the rate limiter | [storage_factory.py](backend/src/mcpolis/entrypoints/storage_factory.py:180) |
| C8 | uses | C107 | build the distributed lock | [storage_factory.py](backend/src/mcpolis/entrypoints/storage_factory.py:180) |
| C11 | uses | C55 | resolve the slug to an org | [org_context.py](backend/src/mcpolis/entrypoints/middleware/org_context.py:84) |
| C13 | uses | C109 | per-category limit check | [rate_limit_middleware.py](backend/src/mcpolis/entrypoints/middleware/rate_limit_middleware.py:123) |
| C14 | uses | C21 | per-org admin operations | [dashboard_api.py](backend/src/mcpolis/entrypoints/routes/dashboard_api.py:73) |
| C14 | uses | C26 | upstream CRUD from the dashboard | [dashboard_api.py](backend/src/mcpolis/entrypoints/routes/dashboard_api.py:73) |
| C14 | uses | C22 | org/member operations | [dashboard_api.py](backend/src/mcpolis/entrypoints/routes/dashboard_api.py:73) |
| C14 | uses | C41 | service-token operations | [dashboard_api.py](backend/src/mcpolis/entrypoints/routes/dashboard_api.py:73) |
| C14 | uses | C62 | serve the audit log | [dashboard_api.py](backend/src/mcpolis/entrypoints/routes/dashboard_api.py:73) |
| C14 | enforces | C15 | require_admin on admin routes | [dashboard_auth.py](backend/src/mcpolis/entrypoints/routes/dashboard_auth.py:284) |
| C14 | listens-to | C108 | stream events over SSE | [dashboard_api.py](backend/src/mcpolis/entrypoints/routes/dashboard_api.py:73) |
| C15 | uses | C101 | complete the browser Google login | [dashboard_auth.py](backend/src/mcpolis/entrypoints/routes/dashboard_auth.py:217) |
| C15 | uses | C110 | revoke the cookie on logout | [dashboard_auth.py](backend/src/mcpolis/entrypoints/routes/dashboard_auth.py:217) |
| C16 | calls | C72 | finish the gateway bearer issue | [google_callback.py](backend/src/mcpolis/entrypoints/routes/google_callback.py:56) |
| C17 | uses | C22 | create/list/switch/delete orgs | [org_routes.py](backend/src/mcpolis/entrypoints/routes/org_routes.py:82) |
| C18 | uses | C100 | complete the upstream OAuth flow | [upstream_oauth_callback.py](backend/src/mcpolis/entrypoints/routes/upstream_oauth_callback.py:182) |
| C19 | uses | C37 | report sandbox capabilities | [sandbox_routes.py](backend/src/mcpolis/entrypoints/routes/sandbox_routes.py:80) |
| C21 | uses | C23 | build the org's policy engine | [org_runtime.py](backend/src/mcpolis/domain/services/org_runtime.py:100) |
| C21 | uses | C24 | build the org's tool registry | [org_runtime.py](backend/src/mcpolis/domain/services/org_runtime.py:100) |
| C21 | uses | C25 | build the org's tool router | [org_runtime.py](backend/src/mcpolis/domain/services/org_runtime.py:100) |
| C21 | uses | C64 | build the org's client manager | [org_runtime.py](backend/src/mcpolis/domain/services/org_runtime.py:100) |
| C22 | writes | C55 | persist orgs + memberships | [org_service.py](backend/src/mcpolis/domain/services/org_service.py:113) |
| C22 | uses | C54 | seed + purge policy config | [org_service.py](backend/src/mcpolis/domain/services/org_service.py:113) |
| C22 | uses | C57 | purge service tokens on delete | [org_service.py](backend/src/mcpolis/domain/services/org_service.py:113) |
| C22 | uses | C47 | purge stored tokens on delete | [org_service.py](backend/src/mcpolis/domain/services/org_service.py:113) |
| C22 | uses | C62 | purge the audit log on delete | [org_service.py](backend/src/mcpolis/domain/services/org_service.py:113) |
| C22 | persists | E1 | own the Organization record | [org_service.py](backend/src/mcpolis/domain/services/org_service.py:113) |
| C22 | persists | E3 | own the Membership record | [org_service.py](backend/src/mcpolis/domain/services/org_service.py:113) |
| C23 | uses | C42 | resolve effective settings | [policy_engine.py](backend/src/mcpolis/domain/services/policy_engine.py:61) |
| C23 | reads | E5 | authorize against the role | [policy_engine.py](backend/src/mcpolis/domain/services/policy_engine.py:61) |
| C24 | uses | C64 | discover tools over a session | [tool_registry.py](backend/src/mcpolis/domain/services/tool_registry.py:103) |
| C24 | writes | C61 | cache the discovered catalog | [tool_registry.py](backend/src/mcpolis/domain/services/tool_registry.py:103) |
| C24 | persists | E26 | own the ToolCatalogSnapshot | [tool_registry.py](backend/src/mcpolis/domain/services/tool_registry.py:103) |
| C25 | enforces | C23 | check tool + argument policy | [tool_router.py](backend/src/mcpolis/domain/services/tool_router.py:256) |
| C25 | routes-to | C64 | dispatch to the upstream session | [tool_router.py](backend/src/mcpolis/domain/services/tool_router.py:256) |
| C25 | writes | C62 | audit each call decision | [tool_router.py](backend/src/mcpolis/domain/services/tool_router.py:256) |
| C25 | emits | C104 | track tool-call analytics | [tool_router.py](backend/src/mcpolis/domain/services/tool_router.py:256) |
| C25 | reads | E10 | resolve the target upstream | [tool_router.py](backend/src/mcpolis/domain/services/tool_router.py:256) |
| C26 | writes | C53 | persist upstream definitions | [upstream_config_service.py](backend/src/mcpolis/domain/services/upstream_config_service.py:28) |
| C26 | uses | C40 | secret-scan the config on save | [upstream_config_service.py](backend/src/mcpolis/domain/services/upstream_config_service.py:28) |
| C26 | uses | C64 | register/connect the upstream | [upstream_config_service.py](backend/src/mcpolis/domain/services/upstream_config_service.py:28) |
| C26 | uses | C24 | refresh tools after a change | [upstream_config_service.py](backend/src/mcpolis/domain/services/upstream_config_service.py:28) |
| C26 | persists | E10 | own the UpstreamDefinition | [upstream_config_service.py](backend/src/mcpolis/domain/services/upstream_config_service.py:28) |
| C27 | uses | C64 | acquire/heal a live session | [upstream_connection_service.py](backend/src/mcpolis/domain/services/upstream_connection_service.py:735) |
| C27 | writes | C47 | store the per-user token | [upstream_connection_service.py](backend/src/mcpolis/domain/services/upstream_connection_service.py:735) |
| C27 | uses | C100 | run the pending-auth dance | [upstream_connection_service.py](backend/src/mcpolis/domain/services/upstream_connection_service.py:735) |
| C28 | uses | C47 | read/refresh stored tokens | [oauth_refresh.py](backend/src/mcpolis/domain/services/oauth_refresh.py:105) |
| C28 | uses | C107 | serialize refresh across backends | [oauth_refresh.py](backend/src/mcpolis/domain/services/oauth_refresh.py:105) |
| C28 | uses | C103 | notify on invalid_grant | [oauth_refresh.py](backend/src/mcpolis/domain/services/oauth_refresh.py:105) |
| C29 | uses | C64 | probe live sessions | [oauth_liveness.py](backend/src/mcpolis/domain/services/oauth_liveness.py:76) |
| C29 | uses | C27 | reconnect dead sessions | [oauth_liveness.py](backend/src/mcpolis/domain/services/oauth_liveness.py:76) |
| C30 | uses | C47 | scan tokens for invalid_grant | [upstream_health_check.py](backend/src/mcpolis/domain/services/upstream_health_check.py:173) |
| C30 | uses | C103 | send the re-auth email | [upstream_health_check.py](backend/src/mcpolis/domain/services/upstream_health_check.py:173) |
| C32 | uses | C52 | match a host to an OAuth app | [oauth_app_resolver.py](backend/src/mcpolis/domain/services/oauth_app_resolver.py:9) |
| C33 | uses | C34 | read the plan's limits | [plan_gates.py](backend/src/mcpolis/domain/services/plan_gates.py:93) |
| C33 | emits | C104 | track plan_limit_hit | [plan_gates.py](backend/src/mcpolis/domain/services/plan_gates.py:93) |
| C35 | uses | C111 | target affected sessions | [policy_notifier.py](backend/src/mcpolis/domain/services/policy_notifier.py:43) |
| C35 | uses | C24 | refresh the changed upstream | [policy_notifier.py](backend/src/mcpolis/domain/services/policy_notifier.py:43) |
| C40 | reads | E10 | scan env/headers for secrets | [secret_scanner.py](backend/src/mcpolis/domain/services/secret_scanner.py:119) |
| C41 | writes | C57 | mint/revoke service tokens | [service_token_service.py](backend/src/mcpolis/domain/services/service_token_service.py:42) |
| C41 | persists | E16 | own the ServiceTokenRecord | [service_token_service.py](backend/src/mcpolis/domain/services/service_token_service.py:42) |
| C42 | reads | C54 | load the org's settings config | [settings_resolver.py](backend/src/mcpolis/domain/services/settings_resolver.py:33) |
| C42 | reads | E4 | resolve access from settings | [settings_resolver.py](backend/src/mcpolis/domain/services/settings_resolver.py:33) |
| C44 | reads | C58 | load variable values to substitute | [template_var_substitution.py](backend/src/mcpolis/domain/services/template_var_substitution.py:64) |
| C44 | reads | E22 | substitute `${NAME}` values | [template_var_substitution.py](backend/src/mcpolis/domain/services/template_var_substitution.py:64) |
| C47 | uses | C49 | Mongo-backed token store (cloud) | [mongo_connection_repository.py](backend/src/mcpolis/adapters/repositories/mongo_connection_repository.py:112) |
| C47 | persists | E17 | own the stored OAuthToken | [connection_store.py](backend/src/mcpolis/adapters/repositories/connection_store.py:27) |
| C49 | uses | D1 | drive MongoDB via motor | [mongo_client.py](backend/src/mcpolis/adapters/repositories/mongo_client.py:19) |
| C49 | uses | D17 | the async motor driver | [mongo_client.py](backend/src/mcpolis/adapters/repositories/mongo_client.py:19) |
| C49 | encrypts | C48 | transparently crypt fields | [mongo_client.py](backend/src/mcpolis/adapters/repositories/mongo_client.py:149) |
| C48 | uses | D16 | AES-256-GCM via cryptography | [encryption.py](backend/src/mcpolis/adapters/repositories/encryption.py:54) |
| C51 | uses | C52 | resolve upstream OAuth apps | [upstream_config_loader.py](backend/src/mcpolis/adapters/repositories/upstream_config_loader.py:169) |
| C53 | uses | C49 | Mongo-backed upstream store | [mongo_upstream_config_repository.py](backend/src/mcpolis/adapters/repositories/mongo_upstream_config_repository.py:32) |
| C54 | uses | C49 | Mongo-backed config store | [mongo_config_repository.py](backend/src/mcpolis/adapters/repositories/mongo_config_repository.py:26) |
| C54 | persists | E4 | own the SettingsConfig | [file_config_store.py](backend/src/mcpolis/adapters/repositories/file_config_store.py:20) |
| C55 | uses | C49 | Mongo-backed org store | [mongo_organization_repository.py](backend/src/mcpolis/adapters/repositories/mongo_organization_repository.py:18) |
| C56 | uses | C49 | Mongo-backed oauth-state store | [mongo_oauth_state_repository.py](backend/src/mcpolis/adapters/repositories/mongo_oauth_state_repository.py:57) |
| C57 | uses | C49 | Mongo-backed token registry | [mongo_service_token_repository.py](backend/src/mcpolis/adapters/repositories/mongo_service_token_repository.py:49) |
| C58 | uses | C49 | Mongo-backed variable store | [mongo_template_var_repository.py](backend/src/mcpolis/adapters/repositories/mongo_template_var_repository.py:52) |
| C58 | persists | E22 | own the TemplateVarSummary | [file_template_var_repository.py](backend/src/mcpolis/adapters/repositories/file_template_var_repository.py:45) |
| C59 | uses | C49 | Mongo-backed file store | [mongo_sandbox_file_repository.py](backend/src/mcpolis/adapters/repositories/mongo_sandbox_file_repository.py:61) |
| C59 | persists | E23 | own the SandboxFile | [file_sandbox_file_repository.py](backend/src/mcpolis/adapters/repositories/file_sandbox_file_repository.py:53) |
| C60 | uses | C49 | Mongo-backed sandbox refs | [mongo_sandbox_persistence_repository.py](backend/src/mcpolis/adapters/repositories/mongo_sandbox_persistence_repository.py:46) |
| C61 | uses | C49 | Mongo-backed catalog store | [mongo_tool_catalog_repository.py](backend/src/mcpolis/adapters/repositories/mongo_tool_catalog_repository.py:14) |
| C62 | uses | C49 | Mongo-backed audit store | [mongo_audit_repository.py](backend/src/mcpolis/adapters/repositories/mongo_audit_repository.py:18) |
| C62 | persists | E35 | own the AuditEntry | [file_audit_repository.py](backend/src/mcpolis/adapters/repositories/file_audit_repository.py:22) |
| C63 | uses | C49 | migrate Mongo data at rest | [upstreams_encrypt_phase_a.py](backend/src/mcpolis/adapters/repositories/migrations/upstreams_encrypt_phase_a.py:211) |
| C64 | uses | C65 | drive HTTP upstream sessions | [client_manager.py](backend/src/mcpolis/adapters/upstream_clients/client_manager.py:103) |
| C64 | uses | C66 | drive stdio upstream sessions | [client_manager.py](backend/src/mcpolis/adapters/upstream_clients/client_manager.py:103) |
| C64 | uses | C67 | shared task lifecycle | [client_manager.py](backend/src/mcpolis/adapters/upstream_clients/client_manager.py:103) |
| C64 | uses | C44 | substitute variables at launch | [client_manager.py](backend/src/mcpolis/adapters/upstream_clients/client_manager.py:103) |
| C64 | reads | C59 | materialize sandbox files | [client_manager.py](backend/src/mcpolis/adapters/upstream_clients/client_manager.py:103) |
| C65 | uses | C67 | SSRF-safe httpx transport | [http_adapter.py](backend/src/mcpolis/adapters/upstream_clients/http_adapter.py:36) |
| C65 | uses | D14 | MCP client over streamable-http | [http_adapter.py](backend/src/mcpolis/adapters/upstream_clients/http_adapter.py:8) |
| C65 | calls | D5 | connect to the upstream MCP | [http_adapter.py](backend/src/mcpolis/adapters/upstream_clients/http_adapter.py:91) |
| C65 | enforces | C45 | validate the upstream URL | [http_adapter.py](backend/src/mcpolis/adapters/upstream_clients/http_adapter.py:87) |
| C66 | uses | C36 | open a stdio session in a sandbox | [stdio_adapter.py](backend/src/mcpolis/adapters/upstream_clients/stdio_adapter.py:178) |
| C66 | uses | C43 | frame the sandboxed stdout | [stdio_adapter.py](backend/src/mcpolis/adapters/upstream_clients/stdio_adapter.py:329) |
| C66 | uses | D14 | MCP ClientSession over stdio | [stdio_adapter.py](backend/src/mcpolis/adapters/upstream_clients/stdio_adapter.py:9) |
| C68 | implements | C36 | E2B SandboxService backend | [service.py](backend/src/mcpolis/adapters/sandbox_e2b/service.py:123) |
| C68 | uses | C70 | pick the right E2B template | [service.py](backend/src/mcpolis/adapters/sandbox_e2b/service.py:123) |
| C68 | writes | C60 | persist the sandbox ref | [service.py](backend/src/mcpolis/adapters/sandbox_e2b/service.py:123) |
| C68 | uses | C39 | confine materialized file paths | [service.py](backend/src/mcpolis/adapters/sandbox_e2b/service.py:123) |
| C68 | calls | D3 | run the stdio MCP in E2B | [real_client.py](backend/src/mcpolis/adapters/sandbox_e2b/real_client.py:62) |
| C68 | uses | D19 | the E2B Python SDK | [real_client.py](backend/src/mcpolis/adapters/sandbox_e2b/real_client.py:62) |
| C69 | uses | C60 | reconcile persisted refs | [reconciler.py](backend/src/mcpolis/adapters/sandbox_e2b/reconciler.py:34) |
| C69 | uses | C38 | apply the GC / kill policy | [reconciler.py](backend/src/mcpolis/adapters/sandbox_e2b/reconciler.py:34) |
| C71 | implements | C36 | local-subprocess SandboxService | [local_subprocess.py](backend/src/mcpolis/adapters/sandbox_services/local_subprocess.py:64) |
| C72 | uses | C41 | verify svct_ bearers | [service_token_verifier.py](backend/src/mcpolis/adapters/auth/service_token_verifier.py:29) |
| C72 | writes | C56 | persist gateway OAuth state | [mcp_gateway_oauth_provider.py](backend/src/mcpolis/adapters/auth/mcp_gateway_oauth_provider.py:76) |
| C72 | calls | D4 | delegate identity to Google | [mcp_gateway_oauth_provider.py](backend/src/mcpolis/adapters/auth/mcp_gateway_oauth_provider.py:296) |
| C100 | uses | C27 | complete the connect flow | [pending_auth.py](backend/src/mcpolis/adapters/auth/pending_auth.py:169) |
| C101 | calls | D4 | dashboard Google sign-in | [google_oauth_provider.py](backend/src/mcpolis/adapters/auth/google_oauth_provider.py:84) |
| C102 | uses | C46 | token storage over ConnectionStore | [mcp_token_storage.py](backend/src/mcpolis/adapters/auth/mcp_token_storage.py:23) |
| C103 | calls | D6 | submit mail over SMTP | [smtp_email_sender.py](backend/src/mcpolis/adapters/email/smtp_email_sender.py:46) |
| C103 | uses | D21 | async SMTP transport | [smtp_email_sender.py](backend/src/mcpolis/adapters/email/smtp_email_sender.py:26) |
| C104 | calls | D8 | send Mixpanel events | [analytics_client.py](backend/src/mcpolis/adapters/observability/analytics_client.py:48) |
| C105 | uses | D7 | init the Sentry SDK | [sentry_setup.py](backend/src/mcpolis/adapters/observability/sentry_setup.py:162) |
| C106 | uses | D20 | configure structlog | [structlog_setup.py](backend/src/mcpolis/adapters/observability/structlog_setup.py:74) |
| C107 | uses | D1 | Mongo TTL lock collection | [distributed_lock_mongo.py](backend/src/mcpolis/adapters/distributed_lock_mongo.py:25) |
| C108 | uses | D2 | Redis pub/sub channels | [event_stream_redis.py](backend/src/mcpolis/adapters/event_stream_redis.py:67) |
| C108 | uses | D18 | the async coredis client | [event_stream_redis.py](backend/src/mcpolis/adapters/event_stream_redis.py:27) |
| C109 | uses | D2 | Redis ZSET sliding window | [rate_limiter_redis.py](backend/src/mcpolis/adapters/rate_limiter_redis.py:82) |
| C110 | uses | D2 | Redis jti deny-list | [session_revocation_redis.py](backend/src/mcpolis/adapters/session_revocation_redis.py:31) |
| C74 | calls | C14 | dashboard REST calls | [client.ts](frontend/src/api/client.ts:70) |
| C74 | calls | C15 | auth/session calls | [auth.ts](frontend/src/api/auth.ts:4) |
| C74 | calls | C17 | org create/switch/delete | [orgs.ts](frontend/src/api/orgs.ts:9) |
| C73 | uses | C74 | the shared fetch client | [App.tsx](frontend/src/App.tsx:127) |
| C73 | uses | C76 | the auth/session context | [App.tsx](frontend/src/App.tsx:127) |
| C97 | listens-to | C14 | subscribe to the SSE stream | [useEventSource.ts](frontend/src/hooks/useEventSource.ts:21) |
| C75 | uses | C74 | react-query resource fetches | [useUpstreams.ts](frontend/src/hooks/useUpstreams.ts:6) |
| C77 | uses | C75 | live upstream list + status | [UpstreamsPage.tsx](frontend/src/pages/admin/UpstreamsPage.tsx:1) |
| C99 | uses | D7 | Sentry React error capture | [sentry.ts](frontend/src/lib/sentry.ts:1) |
| C99 | uses | D8 | Mixpanel browser analytics | [analytics.ts](frontend/src/lib/analytics.ts:1) |
| C88 | uses | D22 | render via React + router | [MarketingLayout.tsx](frontend/src/components/layout/MarketingLayout.tsx:1) |

---

## Test completeness — gaps against the map

> **Tests run for this table?** No — read-only against the test layout and CLAUDE.md; all rows

| Target | Tested? | Test(s) | Gap / risk | Confidence |
|---|---|---|---|---|
| service-token auth + org pin (Headless agent calls tools via service token) | yes | [backend/tests/unit/](backend/tests/unit/) — service_token / pin suites | role-surface + fail-closed pinning are pinned by unit tests | inferred |
| gateway tool call + policy (Connect human AI client via Google OAuth, List and call tools through the gateway) | yes | [backend/tests/unit/](backend/tests/unit/) — policy_engine, tool_router | per-org `is_admin` isolation gate has a named test | inferred |
| org-deletion cascade (Delete an organization) | yes | [backend/tests/unit/](backend/tests/unit/) — org_service | drift guard asserts every org-scoped repo is purged | inferred |
| stdio sandbox (E2B) (Add a hosted stdio upstream MCP, Connect or start an upstream) | partial | [backend/tests/integration/](backend/tests/integration/) — paid, gated | real-SDK path only runs when `E2B_API_KEY` is set | inferred |
| per-user OAuth refresh/liveness (Per-user OAuth to an upstream) | partial | [backend/tests/unit/](backend/tests/unit/) — oauth_refresh | stall/reattach edge cases are flaky per project notes | inferred |
| Full-stack journeys (Sign up and create an organization, Add a remote HTTP upstream MCP, View and filter the audit log) | yes | [tests/e2e/](tests/e2e/) — Playwright | covered end-to-end via the dashboard | inferred |
| SSRF deny-list (UriWrapping / UrlSafety) | yes | [backend/tests/unit/](backend/tests/unit/) — url_safety | DNS-resolved IP checks present | inferred |
| field encryption at rest (Field encryption (AES-256-GCM), Mongo client + OrgScopedCollection) | partial | [backend/tests/unit/](backend/tests/unit/) — field-crypto suite | key-rotation invalidation path under-exercised | inferred |

---

*Generated with coyomap from `project-map.json` — the committed source of truth. Do not edit this file; regenerate it with `coyomap render`.*
