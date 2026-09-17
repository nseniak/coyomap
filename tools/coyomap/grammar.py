#!/usr/bin/env python3
"""Shared token/grammar helpers used across the coyomap pipeline: the id vocabulary, the dependency
Kind classifier, the markdown table-splitting grammar (used by the change-impact report parser in
`viewer/build_graph.py`), and the domain-relation vocabulary (`views.py` derives graph edges and
flow steps straight from the model, reusing this vocabulary rather than a second one). Stdlib-only.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# IDs by prefix. Multi-letter prefixes (UC, HP, SD, SF, BLK, BR) must precede the single-letter ones
# (so `SD1` never reads as `S` + stray text).
# Multi-letter prefixes lead: `CAP3` would otherwise fall through every alternative (`C\d+` fails on
# the "A"), and `EP1` likewise. Same first-match rule as model.ID_SHAPE. This must stay in LOCKSTEP
# with ID_SHAPE: `remap_element_ids` rewrites `[[ID]]` prose refs through this token, so a prefix
# known to the model and unknown here is silently dropped on every merge.
#: `R\d+` was MISSING although `ID_ARRAYS` maps `"roles": "R"`, so `[[R1]]` prose refs were dropped
#: on every merge — the exact failure this comment warns about, sitting in the regex it warns about.
ID_TOKEN = re.compile(r"\b(?:CAP\d+|EP\d+|UC\d+|HP\d+|SD\d+|SF\d+|BLK\d+|BR\d+|C\d+|D\d+|E\d+|I\d+|R\d+|S\d+)\b")

# Grouping: membership is ONE parent pointer carried on the child.
# Nesting depth is ADVISORY, not capped: the viewer renders arbitrary depth, and the cycle check (not a
# depth limit) is what guarantees the membership walk terminates. The validator only *warns* when a
# chain is deeper than this, as a gentle "is each level pulling its weight?" nudge.
DEEP_NEST_WARN = 5  # warn (non-blocking) when a membership chain is deeper than this many parent hops

# External-dependency Kind — a closed vocabulary that drives how the C4 Context view treats a dep.
# The first four are EXTERNAL SYSTEMS the project talks to across a boundary (drawn at Context, by
# name); framework + library are in-process code deps that FOLD into one collapsed "Libraries" box.
# Authored in an OPTIONAL T2 `Kind` column; when absent, classify_dep() infers it from `Type`.
CONFIDENCE_VALUES: tuple[str, ...] = ("verified", "inferred")

DEP_KINDS = ("datastore", "messaging", "service", "platform", "framework", "library")
DEP_KINDS_FOLDED = ("framework", "library")                          # in-process — fold into "Libraries"
# The EXTERNAL (system) dep kinds — everything the project talks to across a boundary. A deployment
# unit that hosts no code but name-matches one of these is that dep's own box, not a real process.
DEP_KINDS_SYSTEM = tuple(k for k in DEP_KINDS if k not in DEP_KINDS_FOLDED)  # datastore/messaging/service/platform


# A deployment `Unit` is ONE process; these separators signal two+ units crammed into one row (a
# non-atomic name). Shared by the atomic-name check and the dep-match guard below.
UNIT_NAME_SEPARATORS = (" / ", ",", " & ")


def is_atomic_unit_name(name: str) -> bool:
    """A unit name denotes exactly one process (no separator crammed two together)."""
    return not any(sep in name for sep in UNIT_NAME_SEPARATORS)


def _norm_alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def unit_name_matches_dep(unit_name: str, dep_name: str) -> bool:
    """True when a deployment-unit name and a dependency name denote the SAME infra: case-insensitive
    containment of the alphanumeric-normalized names, either direction (`"mongo"`↔`"MongoDB"` matches).
    A NON-ATOMIC unit name (a `"mongo-test / redis-test"` compound) denotes no single dep and matches
    NOTHING — it is left to flag as untraced (and as a non-atomic name), never silently treated as
    infra. This guard is load-bearing: without it the compound normalizes to one blob that DOES contain
    a short dep token like `"redis"`, wrongly suppressing the real gap the check exists to surface."""
    if not is_atomic_unit_name(unit_name):
        return False
    u = _norm_alnum(unit_name)
    d = _norm_alnum(dep_name)
    if not u or not d:
        return False
    return u in d or d in u

# Keyword signatures for the heuristic fallback, in PRIORITY order (first hit wins). Distinctive
# categories precede broad ones so a multi-signal Type lands right: "AWS SQS" -> messaging (not
# platform), "AWS S3 object storage" -> datastore (not platform). Matched case-insensitively as
# substrings of the `Type` text. framework vs library need not be precise — both fold at Context.
_DEP_KIND_SIGNATURES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("messaging", ("queue", "broker", "message", "pub/sub", "pubsub", "pub-sub", "kafka", "rabbitmq",
                   "rabbit", "amqp", "sqs", "sns", "nats", "event bus", "event stream", "kinesis",
                   "mqtt", "celery")),
    ("datastore", ("database", "datastore", "data store", "sql", "postgres", "mysql", "mariadb",
                   "sqlite", "mongo", "redis", "cache", "memcache", "elasticsearch", "opensearch",
                   "search index", "object storage", "blob storage", "bucket", "dynamodb",
                   "cassandra", "warehouse", "bigquery", "snowflake", "neo4j", "key-value",
                   "kv store", "vector store", "vector db")),
    ("service", ("api", "saas", "third-party", "third party", "external service", "webhook", "idp",
                 "identity provider", "oauth", "openid", "sso", "auth provider", "auth0", "okta",
                 "payment", "stripe", "billing", "email", "smtp", "sendgrid", "mailgun", "sms",
                 "twilio", "llm", "openai", "anthropic", "observability", "monitoring", "telemetry",
                 "metrics", "tracing", "sentry", "datadog", "analytics", "geocoding")),
    ("platform", ("cloud", "aws", "gcp", "azure", "kubernetes", "k8s", "docker", "container",
                  "cdn", "secrets manager", "vault", "infrastructure", "serverless",
                  "load balancer", "reverse proxy", "nginx", "terraform", "runtime")),
    ("framework", ("framework", "orm", "fastapi", "flask", "django", "express", "react", "vue",
                   "angular", "svelte", "spring", "rails", "laravel", "sqlalchemy", "prisma",
                   "next.js", "nextjs")),
)


def classify_dep(kind_cell: str, type_cell: str) -> str:
    """The dep's Kind (one of DEP_KINDS): an explicit, valid `Kind` cell wins; else infer from the
    free-text `Type`. Falls back to 'library' (folds into the Context 'Libraries' box) when nothing
    matches, so an un-tagged, unrecognised dep declutters rather than crowding Context. The authored
    `Kind` column is the accurate path; this heuristic is the fallback when it's absent."""
    explicit = (kind_cell or "").strip().lower()
    if explicit in DEP_KINDS:
        return explicit
    t = (type_cell or "").lower()
    for kind, needles in _DEP_KIND_SIGNATURES:
        if any(needle in t for needle in needles):
            return kind
    return "library"


# ── Dependency PURPOSE bucket — the seeded-open grouping axis ─────────────────────────────────────
# Unlike DEP_KINDS (a CLOSED, structural axis: how you talk to the dep + whether it folds), a bucket
# is a PURPOSE axis (what the dep does for the product) and is SEEDED-OPEN: the analysis reuses a seed
# when one fits and may MINT a new bucket when none does. `Kind` still decides shown-vs-folded; the
# bucket only GROUPS deps WITHIN each of the two diagrams — external systems in the Context view,
# in-process code in the Libraries drill — so the two seed lists lean external vs. code respectively.
DEP_BUCKET_SEEDS_EXTERNAL = (
    "Data & storage", "Identity & access", "Observability", "Messaging & delivery",
    "AI & ML", "Infrastructure & runtime", "Integrations",
)
DEP_BUCKET_SEEDS_LIBRARY = (
    "Web framework / server", "Frontend / UI", "Data drivers", "Service SDKs",
    "Validation / models", "Logging", "Crypto / security",
)
DEP_BUCKET_SEEDS = DEP_BUCKET_SEEDS_EXTERNAL + DEP_BUCKET_SEEDS_LIBRARY
# The catch-all each diagram falls back to when no seed fits (external's is itself a seed, drawn last).
DEP_BUCKET_CATCHALL_EXTERNAL = "Integrations"
DEP_BUCKET_CATCHALL_LIBRARY = "Other"
# Per-DIAGRAM cap (checked separately for externals vs libraries — they are two diagrams): a nudge to
# keep the grouping legible instead of proliferating one-item buckets.
DEP_BUCKET_CAP = 8
# When the CATCH-ALL bucket ('Integrations' / 'Other') alone holds more than this many deps, it has
# stopped meaning "no specific purpose" and become a dumping ground — the mirror of DEP_BUCKET_CAP
# (that guards against too-many buckets; this against one bucket swallowing everything). A large
# catch-all means real sub-purposes (Payments, Social, …) are hiding and should be split out.
DEP_BUCKET_CATCHALL_SPLIT_AT = 6
# A Context (external) bucket with THIS MANY OR MORE members collapses into a single drillable count
# box instead of an inline cluster — so an integration-heavy product doesn't render every name at the
# top altitude. Set just above the largest bucket a small map produces (mcpolis peaks at 4), so small
# maps stay fully expanded and only genuinely large buckets fold.
DEP_BUCKET_FOLD_AT = 5

# The external catch-all is already a seed; the LIBRARY catch-all is not, so add it explicitly —
# otherwise a mis-cased "other" would escape folding and render a duplicate look-alike catch-all cluster.
_BUCKET_CANON = {b.lower(): b for b in (*DEP_BUCKET_SEEDS, DEP_BUCKET_CATCHALL_LIBRARY)}


def canonical_bucket(name: str) -> str:
    """Fold a bucket to its seed's canonical spelling when it matches one case-insensitively (kills
    the case / trailing-whitespace drift deterministically); a minted (non-seed) bucket is returned
    trimmed, exactly as authored. The single normalizer every reader routes through."""
    s = (name or "").strip()
    return _BUCKET_CANON.get(s.lower(), s)


# Keyword signatures for the heuristic used ONLY when a dep carries no authored bucket — priority
# order, first hit wins, matched against the `type` + `used_for` text. The authored `Bucket` is the
# accurate path; this just keeps an un-tagged dep grouped somewhere sane instead of all-catch-all.
_BUCKET_SIGNATURES_EXTERNAL: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Identity & access", ("oauth", "openid", "sso", "idp", "identity", "auth provider", "auth0",
                           "okta", "secrets manager", "vault", "keycloak")),
    ("Observability", ("observability", "monitoring", "telemetry", "metrics", "tracing", "sentry",
                       "datadog", "analytics", "mixpanel", "apm", "log store", "log forward",
                       "feature flag", "unleash", "statsd")),
    ("Messaging & delivery", ("email", "smtp", "sendgrid", "mailgun", "mailchimp", "mailjet", "sms",
                              "twilio", "push notification", "notification")),
    ("AI & ML", ("llm", "openai", "anthropic", "claude", "inference", "speech", "text-to-speech",
                 "tts", "image generation", "embedding", " ml ", "machine learning")),
    ("Data & storage", ("database", "datastore", "data store", "sql", "postgres", "mysql", "mongo",
                        "redis", "cache", "object storage", "blob storage", "warehouse",
                        "elasticsearch", "dynamodb", "s3", "key-value", "vector db")),
    ("Infrastructure & runtime", ("docker", "container", "kubernetes", "k8s", "nginx",
                                  "reverse proxy", "cdn", "sandbox", "load balancer", "serverless",
                                  "cloud runtime")),
)
_BUCKET_SIGNATURES_LIBRARY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Frontend / UI", ("react", "vue", "angular", "svelte", "vite", "tailwind", "frontend",
                       " ui ", "spa", "router", "css")),
    ("Data drivers", ("driver", "motor", "pymongo", "sqlalchemy", "orm", "coredis", "redis client",
                      "prisma", "database driver", "asyncpg")),
    ("Web framework / server", ("framework", "fastapi", "flask", "django", "express", "starlette",
                                "uvicorn", "asgi", "wsgi", "rails", "spring", "gunicorn")),
    ("Validation / models", ("pydantic", "validation", "serialization", "marshmallow", "schema")),
    ("Logging", ("structlog", "logging", "logger")),
    ("Crypto / security", ("crypto", "cryptograph", "encryption", "jwt", "hashing", "security")),
    ("Service SDKs", ("sdk", "api client", "protocol", "client library")),
)


def classify_bucket(is_library: bool, type_cell: str, used_for: str) -> str:
    """The dep's purpose bucket when none is authored: infer from `type` + `used_for`, falling back
    to the diagram's catch-all. `is_library` picks the code seeds vs. the external seeds so a folded
    dep never lands in an external bucket (and vice-versa)."""
    hay = f" {type_cell} {used_for} ".lower()
    sigs = _BUCKET_SIGNATURES_LIBRARY if is_library else _BUCKET_SIGNATURES_EXTERNAL
    for bucket, needles in sigs:
        if any(n in hay for n in needles):
            return bucket
    return DEP_BUCKET_CATCHALL_LIBRARY if is_library else DEP_BUCKET_CATCHALL_EXTERNAL


def resolve_bucket(is_library: bool, authored: str, type_cell: str, used_for: str) -> str:
    """The dep's FINAL bucket: the authored one (canonicalized) or the heuristic fallback. The single
    resolver both the markdown/panel view and the diagram grouping call, so a dep's shown bucket and
    the cluster it groups into never disagree."""
    if (authored or "").strip():
        return canonical_bucket(authored)
    return classify_bucket(is_library, type_cell, used_for)


def order_buckets(names: Iterable[str], is_library: bool) -> list[str]:
    """The buckets present, in the DETERMINISTIC diagram order: seeds first (in seed order), then
    minted buckets alphabetically, then the catch-all last. Canonicalizes + de-dups on the way in."""
    seeds = DEP_BUCKET_SEEDS_LIBRARY if is_library else DEP_BUCKET_SEEDS_EXTERNAL
    catchall = DEP_BUCKET_CATCHALL_LIBRARY if is_library else DEP_BUCKET_CATCHALL_EXTERNAL
    present = list(dict.fromkeys(canonical_bucket(n) for n in names if (n or "").strip()))
    seed_order = [b for b in seeds if b in present and b != catchall]
    minted = sorted(b for b in present if b not in seeds and b != catchall)
    tail = [catchall] if catchall in present else []
    return seed_order + minted + tail


# An entry point's ACTIVATION — a closed vocabulary describing WHO starts it. "self" = the system
# starts it with no outside caller (a scheduled/cron job, a while-True or interval loop, a
# background worker/thread, a queue/stream consumer, a boot/startup hook, an OS signal handler);
# "external" = something outside asks (an HTTP route, a CLI invocation, a callback, a webhook).
# Authored in an OPTIONAL T4 `activation` column; when absent, classify_activation() infers it from
# `kind`. Lets a reader answer "what runs with no user?" at a glance.
ACTIVATIONS = ("self", "external")

# A ROLE's AUDIENCE — a closed vocabulary, authored on the role. WHICH SIDE of the product this actor
# sits on: "internal" = the side of the company that ships it; "user" = everyone else, including
# someone who has not bought it yet. This is the ONE authored answer to "who is this for" in the whole
# map: a capability's audience is DERIVED from it (`capability_audience`), never authored, so the two
# can never contradict.
#
# The side is asked the same way of a person and of a program, but answered from different evidence:
#   * a PERSON  — do they work for the company that ships the product?
#   * a PROGRAM — whose machine is it? The customer set it up -> `user`; the company runs it, or pays
#                 a vendor to run it -> `internal`. NOT whose work it happens to be doing.
#
# The word was `staff` until a count showed it naming the wrong thing: across the reference maps it
# printed in 12 places and only 4 of them were people. A scheduler is not staff, and neither is a
# payment provider the company pays, so the viewer had grown a second form (`staff-owned`) just to
# make the word usable on a machine. One word that fits every actor beats two that fit half each.
#: WHAT AN ACTOR IS. Three values, and the third was added on 2026-09-03 because `service` was
#: covering two things that behave differently: the product's own timer, and a customer's AI
#: assistant. Across the three live maps 4 roles were `service` and 3 of them were AI agents —
#: coyomap's "Coding agent", argus's "Assistant", mcpolis's "Headless agent" — wearing the same pill
#: as mcpolis's "Upkeep job", which is a cron inside the product.
#:
#: THE RULE EVERY READER USES: anything not `human` is a MACHINE (`is_machine_role`), and only
#: `service` + `audience: internal` is INSIDE the product (`outside_actor_ids`). An `ai-agent` is
#: therefore always outside, always a machine, and never the product's own scheduled work — which is
#: the whole reason it is not spelled `service`.
#:
#: Free text at the model layer, like `Role.kind` has always been: `validate` nudges an unknown
#: spelling and never blocks, so a map may still say `bot` or `agent`.
ROLE_KINDS = ("human", "service", "ai-agent")
ROLE_AUDIENCE = ("user", "internal")


def is_machine_role(kind: str) -> bool:
    """Is this actor a program rather than a person?

    ONE PREDICATE, and it reads `!= human` rather than `== service` deliberately. Three places used
    to string-compare against `service` and each would have silently reclassified an `ai-agent`
    as a person the day that value appeared: the audience vote (which one used `startswith("s")`),
    the person-at-a-machine-surface nudge, and the human-plus-service use-case advisory. An
    adversarial review has already broken this file once over two copies of "who is an actor" that
    disagreed, so the third value arrives with one function instead of three edits.

    An unlabelled role counts as a PERSON, which is the safe direction: the checks that read this
    exist to raise a question a person answers, and a nudge too many is recoverable where a nudge
    too few is the silence they were added to close."""
    return (kind or "").strip().lower() not in ("", "human")

# ── Interfaces (T2b) — the product's outside edge ────────────────────────────────────────────────
# An INTERFACE is a surface through which the product sends data/events NOT consumed by the product
# itself, or receives data/events NOT generated by the product itself. Excluded: data the product
# produces only to read back (its own database, cache, queue); code and build artifacts that BECOME
# the product; the pipeline that builds and tests it. An outside consumer THE MAP RECORDS beats the
# read-back exclusion. Name the far side, never the pipe that reaches it.
INTERFACE_SIDES = ("ours", "theirs")      # whose design the surface is: if the far side vanished,
                                          # would the design of this thing change?
INTERFACE_FACINGS = ("user", "operator")  # who it serves. AUTHORED, never derived from
                                          # `Role.audience`: that answers a different question (which
                                          # side of the COMPANY an actor sits on) and marks a bought
                                          # payment service `internal` while its interface is
                                          # user-facing. Measured: only 8 of the 69 interfaces across
                                          # the four live maps have roles to derive from at all.
# ── WHICH WAY THE DATA MOVES, on one walk step ───────────────────────────────────────────────────
# Read from the point of view of the PRODUCT'S OWN CODE at that step, never from the arrow: `in` is
# data arriving at it, `out` is data leaving it. That single reading covers both places the map
# needs an answer, and covers them the same way:
#
#   at a RECORD   `in` = the product reads it        `out` = the product writes it
#   at a SURFACE  `in` = the product receives        `out` = the product sends
#
# Anchoring it on the ARROW instead was tried and breaks on a PULL: `Cn → In` "fetches the markup"
# points outward while the data comes back, which is `in`.
#
# A DOOR OWES NOTHING. A role standing at a surface is a human action with no product end — argus's
# operator opens the log store's own console and nothing of ours moves — so the field stays empty
# there, the same exemption an actor step has from `where`. Forcing an answer on a door is what put
# the word "receives" in front of a step whose own phrase said "sends each finished record out".
#
# `both` is one exchange whose data runs both ways — a code traded for a verified email, an upsert
# that returns the stored row. It exists because the alternative is splitting such a step in two,
# which lengthens every walk that contains one to record a fact the step already knows. argus's
# assistant sign-in has one (step 14: it sends the code and checks the answer's signature).
#
# THIS FIELD REPLACED `interfaces[].carries[]`, whose only underivable fact was direction. Do not
# reintroduce a per-surface direction: an interface's directions are the SET its steps carry, and a
# second authored copy is a second thing to disagree with.
STEP_DIRECTIONS = ("in", "out", "both")

# ── Interface KIND — WHAT a surface IS, seeded-open (mirror of the entry-point kind axis) ────────
# `kind` says WHAT IT IS. `Dep.bucket` says WHAT IT IS FOR. A payment processor and a crash reporter
# are both `api`, and what tells them apart is already authored one table over, in a richer set of
# words. A
# kind that answers "what is it FOR" is the sign this field has been mis-modelled — `validate` nudges
# on the purpose-shaped spellings below rather than blocking, because the author adjudicates.
#
# The vocabulary is the size of an ICON SET, not of a product taxonomy: the field exists so the
# viewer can DRAW a surface. A 20-seed draft was cut to 11 in two passes. The second cut removed
# `store`, `compute` and `message` after an adversarial review measured all 7 of mcpolis's `theirs`
# surfaces mapping 1:1 from `Dep.bucket` to the kind — those three were `bucket` under another name,
# and `grammar` already seeds "Observability", "Infrastructure & runtime", "Messaging & delivery".
# On the `theirs` side almost every surface IS the same kind of thing (an HTTPS call to a vendor) and
# what differs is purpose, so this vocabulary should say little there: the log store, the analytics
# service and the crash reporter all take `api`.
#
# DRIFT is the other reason to keep it small: a seeded-open vocabulary is what the eval compares
# across builds, and with 20 seeds two builds of one repo argue `api` vs `api-call` vs `webhook-in`
# forever.
#
# This is a LEVEL above `ENTRY_POINT_KINDS`, never a duplicate of it: a way in's kind names the
# MECHANISM (an HTTP address, a tool, a command); this names the SURFACE (a web UI, a CLI, an API).
# `ui-route` + `http-route` together ARE a web UI, and nothing else in the model says so. Deriving
# this from the ways in was measured and fails: one clean answer on 4 of coyomap's 11 surfaces and 1
# of mcpolis's 12, and NOTHING at all on any `theirs` surface, which has no ways in by definition.
INTERFACE_KIND_SEEDS_OURS = (
    "screen",         # a browser window: our web UI, a marketing site — anything served to a browser
    "mobile-app",     # a phone: an app a person installs on a phone
    "desktop-app",    # a window with a title bar: an app a person installs on a machine
    "command-line",   # a prompt: commands typed in a terminal
    "file",           # a document: files we write that something else opens
    "settings",       # a gear: the values a person or an operator sets
    #: THE WIRE FACES A MACHINE AND A PERSON IS AT THE FAR END OF IT. Every other `ours` seed is a
    #: place someone comes TO the product; this is the one where the product goes to them, and they
    #: read it somewhere we do not own (an inbox, a phone). Added because it is the ONLY row in the
    #: 2026-09-03 partial run where the vocabulary actively misled a careful reader: two independent
    #: agents, on two runs, authored mcpolis's "Outgoing email" as `api`, and both gave the same
    #: reason — `api` names the SMTP pipe, not the surface, and nothing else fit.
    #: NOT `notification`, which says WHY. A password reset and a marketing blast are both
    #: notifications and are not the same kind of thing; `kind` says what a surface IS.
    "message",        # an envelope: a message we send outward to a person — email, SMS, push
)
INTERFACE_KIND_SEEDS_THEIRS = (
    "hosted-screen",  # a window someone else owns: a sign-in, a vendor console, a chat platform
    "content",        # a page: data we read that we did not write — the open web, a repo, a transcript
    "handoff",        # an arrow out: we hand the PERSON to another program — a link, their editor
)
INTERFACE_KIND_SEEDS_EITHER = (
    "api",            # a plug: one program calling another over a network, either direction,
                      # webhooks included
    "agent-tools",    # a wrench: tools an AI agent calls, ours or theirs — the shape, whatever
                      # protocol carries it
    #: THE ONE PROTOCOL NAME IN THIS LIST, and it is here on purpose after being argued down twice.
    #: Every other seed says what a surface IS; `mcp` says which protocol it speaks, which is a
    #: different axis and is normally the ways in's job (`entry_points[].kind` already holds
    #: `mcp-tool`). Two things overruled that:
    #:   * READING IT OFF THE WAYS IN CANNOT WORK on a surface someone else defines, which has no
    #:     ways in by definition. mcpolis's "Upstream MCP servers" is exactly that, so a derived
    #:     label would have said MCP on the three servers we publish and stayed silent on the one we
    #:     call — the same seam, moved.
    #:   * `mcp-tool` is the FOURTH-BIGGEST way-in kind across the live maps (63, behind only
    #:     `http-route`, `cli` and `ui-route`). A word this common in the code earns one on screen.
    #: THE GUARD IS THE TIE-BREAK, not this comment: most specific wins, so `mcp` beats `agent-tools`
    #: beats `api`. DO NOT mint a second protocol seed by pointing at this one. If a second protocol
    #: ever earns a word the same way — measured, and underivable from the ways in — that is a
    #: decision to take on its own evidence, not a precedent already set.
    "mcp",            # a wrench with a plug: an MCP address, ours or theirs
)
# The side grouping is GUIDANCE for the author and for the viewer's legend — `validate` must NOT
# enforce it. A product can host a screen someone else designed, and can publish an API someone
# else's spec defines.
INTERFACE_KIND_SEEDS = (
    INTERFACE_KIND_SEEDS_OURS + INTERFACE_KIND_SEEDS_THEIRS + INTERFACE_KIND_SEEDS_EITHER
)

# The two kinds that MEAN a person goes to the far side themselves. This is what gates the derived
# `actors` on a `theirs` surface: "whose story reaches it" is not "who goes there" — a member's story
# reaches an upstream MCP server, but the PRODUCT calls it, and putting three human roles on the far
# side of a server is what an ungated join actually produced. Every other `theirs` kind derives NO
# actor, and none is the correct answer.
INTERFACE_KINDS_A_PERSON_GOES_TO = ("hosted-screen", "handoff")

# The other end of the same question, and it answers a DIFFERENT one — do not merge the two tuples.
# Above: which `theirs` kinds let the map INFER that a person goes there. Here: which kinds say
# NOBODY STANDS THERE AT ALL, so a walk that draws a person at one is worth a second look. Both
# kinds are one program talking to another: `api` is a call over a network, `content` is data we
# read that we did not write. Every other seed can legitimately have a person at it, `agent-tools`
# included, because a headless agent is a role in its own right.
#
# This is a NUDGE, never a gate, and it names TWO possible causes because either can be the wrong
# one: the door may be on the wrong surface, or the surface may be wearing the wrong kind. It exists
# because the door checks verify a door EXISTS and can never tell a RIGHT door from a WRONG one —
# measured by repointing every door on a 42-story map onto the crash reporter, which raised 2
# advisories and ZERO blocking problems.
INTERFACE_KINDS_NOBODY_STANDS_AT = ("api", "content")

#: THE KINDS A PERSON REACHES THROUGH A CLIENT WORTH DRAWING. The viewer hangs a small mark off a
#: person standing at one of these, so the thing between them and the wire is not invisible.
#:
#: THE TEST IS AGENCY: draw the client when it can do something the person did not ask for. A browser
#: renders what we sent; a terminal runs what was typed; a mail app shows what arrived — none of them
#: decides anything, and drawing them would be noise on every row. An AI agent chooses which tools to
#: call and with what, so it is the one client whose presence changes what the reader should expect.
#: That test, not this list, is what a future kind is measured against — 2 of the 13 pass it today.
#:
#: NEVER FOR A MACHINE ACTOR. An unattended agent reaches an MCP address alone; hanging a client off
#: it would draw an agent behind an agent.
INTERFACE_KINDS_REACHED_THROUGH_A_CLIENT = ("mcp", "agent-tools")

# The tiebreak, for the surfaces that are BOTH a place people act and a service we call:
# **the kind names where the PEOPLE are — but only when the product's own flow takes them there.**
# Slack for a product that lives in it, a sign-in redirect and a hosted checkout are `hosted-screen`;
# a code link we hand over is `handoff`; a crash reporter an operator opens on their own is `api`.

# Exact-string fold (matched on the trimmed, lowercased kind): observed drift spellings -> the seed.
# Only UNAMBIGUOUS synonyms fold — the same rule `ENTRY_POINT_KIND_ALIASES` records. A draft broke it
# three times and four entries were removed for it: `website` -> `screen` sat beside `web` ->
# `content`, sending two spellings of one word to opposite seeds; `sdk` cannot tell an SDK we publish
# from one we consume; `skill` -> `file` was wrong outright. Those spellings stay MINTED and draw the
# aggregated synonym nudge, where the author adjudicates.
# The last group folds the three CUT seeds: they were purpose words, and their kind is `api`.
INTERFACE_KIND_ALIASES = {
    "web-ui": "screen", "webui": "screen", "ui": "screen", "marketing-site": "screen",
    "cli": "command-line",
    "installed-app": "desktop-app",
    "agent-skill": "file", "file-output": "file",
    "data-source": "content",
    "chat-app": "hosted-screen", "hosted-ui": "hosted-screen",
    "link-handoff": "handoff",
    "rest-api": "api", "webhook": "api", "api-call": "api",
    "store": "api", "data-sink": "api", "logs": "api", "compute": "api",
    #: THESE THREE USED TO FOLD INTO `api`, AND THAT FOLD WAS THE BUG. `message` is a seed now, so a
    #: map that spells a person-facing message `email` or `message-out` lands on it instead of being
    #: told its surface is one program calling another. The old fold is exactly the mistake two
    #: independent readers made on mcpolis's "Outgoing email" in the 2026-09-03 partial run: `api`
    #: names the SMTP pipe, not the surface.
    "message-out": "message", "email": "message", "sms": "message", "push": "message",
    "notification": "message",
}

_INTERFACE_KIND_CANON = {k: k for k in INTERFACE_KIND_SEEDS} | INTERFACE_KIND_ALIASES

# PURPOSE-shaped spellings: a kind that answers "what is it FOR". Not folded and never blocked — the
# nudge points at `Dep.bucket`, which already holds this axis in a richer vocabulary (13 buckets on
# one live map). Kept separate from the alias table on purpose: an alias silently reroutes, and none
# of these has one right destination.
INTERFACE_KIND_PURPOSE_WORDS = (
    "payment", "analytics", "identity", "observability", "search", "storage",
)


def canonical_interface_kind(kind: str) -> str:
    """Fold an interface kind to its canonical seed spelling when it matches a seed (case drift) or a
    known alias (`cli` -> `command-line`); a minted (non-seed) kind is returned trimmed, exactly as
    authored. The single normalizer every reader routes through — the Interfaces view's grouping, the
    viewer's icon lookup, the eval profile — so no two consumers can split the same kind."""
    s = (kind or "").strip()
    return _INTERFACE_KIND_CANON.get(s.lower(), s)

# A CAPABILITY's HAPPY_PATH expectation — a closed vocabulary, authored on the capability (never on a
# subsystem or a subdomain, which `validate` blocks). "expected" = the walk must reach at least one
# of its use cases; "excluded" = the walk correctly skips all of them, and one record says why. Both
# values name an INTENTION, on the same scale, so neither can be read as a fact about the walk. It is what
# turns Happy-Path membership into a rule instead of a written justification per off-spine use case.
#
# It replaced a THREE-value `label` (core | supporting | platform) that carried this question and the
# audience question in one word. Two of its three values had no definition anywhere and no branch in
# this codebase ever distinguished them, so the audience half was unenforced and drifted: the same
# feature was `platform` in one rebuild and `supporting` in the next. Splitting the two questions
# also gave the missing 2x2 cell a name — internal work the walk shows on purpose — which is what six
# per-step records on the live maps existed only to excuse.
#
# Deliberately NOT derived from the walk. A field that always agrees with `happy_path[]` could never
# disagree with it, and the disagreement IS the check: "you wrote that this belongs on the walk, and
# the walk never reaches it" is the gap the forward direction exists to find.
CAP_HAPPY_PATH = ("expected", "excluded")

# Keyword signatures for a SELF-starting entry point, matched case-insensitively as substrings of
# the free-text `kind`. Deliberately excludes "webhook" (an external caller invokes it).
_SELF_START_SIGNATURES = ("background", "loop", "cron", "schedul", "timer", "tick", "interval",
                          "poll", "boot", "startup", "start-up", "on_event", "lifespan", "signal",
                          "sigterm", "sighup", "atexit", "shutdown", "daemon", "worker", "consumer",
                          "subscrib", "queue", "listener", "watch")


# ── Entity STORE mode — how an entity relates to its physical store ───────────────────────────────
# CLOSED, exact-match (the `activation` discipline, not the seeded-open bucket one): the mode drives
# grouping in the persistence views, and the six values partition the observed population of three
# real maps completely — a new mode is a method change, not a per-map minting.
#   collection = its own compartment (collection/table/bucket/file) in a dep
#   embedded   = persisted INSIDE a parent entity's row/document
#   transient  = in-memory / event object / API projection — never persisted
#   cache      = lives only in a cache tier (a projection of another source of truth)
#   in-code    = a module-level registry/constants (persisted in the source itself)
#   enum       = a closed value set (often a bitfield); its "store" is the type definition
#   projection = a READ shape over rows another entity owns (a row type a query module returns, a
#                view assembled in code). The data is durable; this type is not what stores it.
STORE_MODES = ("collection", "embedded", "transient", "cache", "in-code", "enum", "projection")

# The modes that SAY, in the model, that nothing in this codebase writes this entity: it lives in a
# parent's row, in the source, or only for the length of a call. They adjudicate the "entity with no
# owning component" advisory on their own — the mode IS the answer, and it is a validated value that
# renders next to the element on the Data tab, where a prose exception line sat in a footnote on
# another tab that nobody read. Live maps wrote that line 67 times on one map, in 11 spellings of the
# same five sentences; every one of them was restating a mode the model can hold.
# `cache` and `collection` are NOT here: something writes a cache, and something writes a collection.
STORE_MODES_UNOWNED = ("embedded", "in-code", "enum", "transient", "projection")

# The modes that mean THIS CODEBASE SAVES A RECORD of the entity — a row of its own in a store, or a
# record carried inside its parent's row. The one derived signal about ownership that measured
# RELIABLE on all three live maps: it separates real records from plumbing and value shapes, so the
# Features page's data areas are areas of SAVED DATA and not of every named type. It is the
# eligibility filter for the `owners` question, never an answer to it — which feature a saved record
# exists FOR is authored (see `Group.owners`).
STORE_MODES_SAVED = ("collection", "embedded")


# ── Entry-point KIND — the seeded-open naming axis (mirror of the dep PURPOSE bucket) ─────────────
# Unlike `activation` (CLOSED: who starts it), `kind` names WHAT the entry point is, and stays
# SEEDED-OPEN: reuse a seed when one fits, mint a project-specific kind (`gateway-loop`,
# `generator-loop`) when none does. What the seeds + alias fold kill is SPELLING drift of the common
# kinds — real maps grew `http` vs `http-route` and `event` vs `event-consumer` for the same thing,
# which splits the System-tab grouping and any per-kind coverage statement. Never blocking: `validate`
# only nudges an alias spelling toward its canonical form and asks (once per kind) whether a minted
# kind is a synonym of a seed.
ENTRY_POINT_KINDS_EXTERNAL = ("http-route", "ui-route", "cli", "webhook", "mcp-tool", "middleware")
ENTRY_POINT_KINDS_SELF = ("job", "poller", "event-consumer", "startup-hook", "signal-handler")
ENTRY_POINT_KINDS = ENTRY_POINT_KINDS_EXTERNAL + ENTRY_POINT_KINDS_SELF

# Exact-string fold (matched on the trimmed, lowercased kind): observed drift spellings -> the seed.
# NOT substring matching — `ui-route` must never fold into `http-route` via its `route` tail. Only
# UNAMBIGUOUS synonyms fold; a spelling that could mean something else stays minted and gets the
# synonym nudge instead of a silent reroute. Adversarial-review finding #3 removed four entries
# that violated this rule across ecosystems: `event` (a UI/webhook event handler is NOT a queue
# consumer — and the fold silently flipped its activation to self), `route` (client-side routes:
# `spa route` folds to ui-route, proving route-spellings span two seeds), `command` (Discord slash
# commands, CQRS command handlers), `endpoint` (gRPC/WebSocket endpoints). Those spellings now
# stay minted and draw the synonym nudge — the author adjudicates, never the fold.
ENTRY_POINT_KIND_ALIASES = {
    "http": "http-route", "http route": "http-route", "api-route": "http-route",
    "spa route": "ui-route", "spa-route": "ui-route",
    "consumer": "event-consumer", "queue-consumer": "event-consumer",
    "cron": "job", "cron-job": "job", "scheduled-job": "job", "timer": "job",
    "lifespan-hook": "startup-hook", "boot-hook": "startup-hook", "startup": "startup-hook",
    "boot task": "startup-hook", "process boot": "startup-hook",
    "signal": "signal-handler",
    "mcp tool": "mcp-tool", "mcp tool surface": "mcp-tool",
}

# One lookup for both folds: a seed's own spelling (case drift) and the alias spellings.
_ENTRY_KIND_CANON = {k: k for k in ENTRY_POINT_KINDS} | ENTRY_POINT_KIND_ALIASES

# A seed kind's activation is FIXED by what the kind means — `job` IS self-started even though the
# word matches no `_SELF_START_SIGNATURES` needle (the substring heuristic misfiles it as external).
KIND_ACTIVATION = (
    {k: "external" for k in ENTRY_POINT_KINDS_EXTERNAL} | {k: "self" for k in ENTRY_POINT_KINDS_SELF}
)


def canonical_entry_kind(kind: str) -> str:
    """Fold an entry-point kind to its canonical seed spelling when it matches a seed (case drift) or
    a known alias (`http` -> `http-route`); a minted (non-seed) kind is returned trimmed, exactly as
    authored. The single normalizer every reader routes through — the System-tab grouping, the
    per-kind coverage contract, the eval profile — so no two consumers can split the same kind."""
    s = (kind or "").strip()
    return _ENTRY_KIND_CANON.get(s.lower(), s)


def classify_activation(kind: str) -> str:
    """The entry point's activation (one of ACTIVATIONS): "self" if it starts itself
    (timer/loop/boot/signal/queue consumer), else "external" (route/CLI/callback/webhook — something
    outside asks). A kind that folds to a SEED gets that seed's fixed activation (`job` is self-run
    even though no keyword needle says so); otherwise a heuristic over the free-text `kind`. The
    authored `activation` column is the accurate path and this is the fallback when it's absent.
    Unrecognised → "external" (the common case, and the safe default)."""
    canonical = canonical_entry_kind(kind)
    if canonical in KIND_ACTIVATION:
        return KIND_ACTIVATION[canonical]
    k = (kind or "").lower()
    return "self" if any(s in k for s in _SELF_START_SIGNATURES) else "external"


def effective_activation(activation: str, kind: str) -> str:
    """The activation a consumer should act on: the authored value when it is a member of the closed
    vocabulary (EXACT match — `validate` blocks anything else, because a near-miss like "External" or
    "mounted" is truthy and would otherwise silently reroute the entry point through the kind
    heuristic), else `classify_activation(kind)`. The one rule shared by the viewer, the entry-surface
    coverage advisory, and the eval profile — so they can never classify the same row differently."""
    return activation if activation in ACTIVATIONS else classify_activation(kind)


def strip_fences(text: str) -> str:
    """Blank out fenced code blocks (``` or ~~~), keeping the line COUNT so reported line numbers
    stay accurate. A verbatim example inside a code fence (a Mermaid diagram, a shell snippet) is
    not live content and must not be parsed as a table."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append("")  # blank the fence marker line too
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")  # a column separator: a `|` NOT preceded by a backslash


def split_cells(row: str) -> list[str]:
    r"""Stripped cells of a markdown table row. An escaped pipe (``\|`` — the schema's sanctioned way
    to put a literal pipe inside a cell) is NOT a column separator: the row is split only on UNescaped
    pipes, and each cell's ``\|`` is then restored to a literal ``|``."""
    core = row.strip()
    core = core[1:] if core.startswith("|") else core      # drop the one leading table delimiter…
    core = core[:-1] if core.endswith("|") else core        # …and the one trailing delimiter
    return [c.replace(r"\|", "|").strip() for c in _UNESCAPED_PIPE.split(core)]


def is_separator_row(line: str) -> bool:
    r"""A markdown table separator row like ``|---|:--:|`` — dashes / colons / pipes / spaces only,
    with at least one dash."""
    return "-" in line and bool(re.fullmatch(r"[\s|:\-]+", line.strip()))


def iter_pipe_runs(lines: list[str]) -> list[tuple[int, list[str]]]:
    """Each maximal run of ``|``-prefixed lines as ``(start_index, block_lines)`` (0-based start).

    This is the table grouping the markdown readers share: a markdown table is a contiguous run of ``|``-lines, so ANY non-pipe line inside it (a
    blank line, stray prose, an HTML comment) breaks the run into two. Run on fence-free text
    (``strip_fences``) so a ``|`` row inside a code fence is never grouped as a table."""
    out: list[tuple[int, list[str]]] = []
    i, n = 0, len(lines)
    while i < n:
        if not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        start = i
        block: list[str] = []
        while i < n and lines[i].lstrip().startswith("|"):
            block.append(lines[i])
            i += 1
        out.append((start, block))
    return out


# ── Domain-relation vocabulary ────────────────────────────────────────────────────────────────────
# `views.py` derives every domain-relation edge and its arrow-backing straight from the
# model (`Entity.relations`, `EntityField.markers`) — this vocabulary (verb -> relationship kind,
# the canonical-vs-alias verb map, and the FK-marker/backing-resolution helpers) is what it reuses,
# so there is still ONE place that decides what a relation verb means.

# Each structural kind has ONE canonical verb (association is free-form — any other verb).
CANONICAL_VERB = {"composition": "contains", "aggregation": "has", "inheritance": "isA"}
# verb -> classDiagram relationship kind; verbs outside the map render as plain associations.
REL_KIND = {
    "contains": "composition", "owns": "composition", "composedof": "composition",
    "has": "aggregation", "aggregates": "aggregation",
    "isa": "inheritance", "extends": "inheritance",
}
# non-canonical structural verb -> the canonical verb to use instead (drives the validator hint).
REL_ALIAS = {v: CANONICAL_VERB[k] for v, k in REL_KIND.items() if v != CANONICAL_VERB[k].lower()}

# The CLOSED cardinality vocabulary — one side of a relation's `sc→dc` pair. `method/domain-cards.md`
# has always published exactly these four and called them a validation rule; nothing enforced it, so
# `many→ONE` or `0..n` passed and reached the class diagram, where a reader cannot tell an author's
# private notation from the map's. Closed on purpose: an open set makes two maps incomparable.
CARDINALITIES: frozenset[str] = frozenset({"1", "*", "0..1", "1..*"})

# ── Backbone edge verb → ROLE ──────────────────────────────────────────────────────────────────────
# The verb families that decide what a backbone edge MEANS — the ONE place backbone-verb meaning is
# decided (like REL_KIND / CANONICAL_VERB above for entity relations). `assemble._infer_ce_verb` reads
# the persist/write/emit/encrypt families to derive a C→E edge's verb; `edge_role` reads all of them
# (plus the read + call families) to derive a dependency's ROLE from its incoming C→D verbs. Moving
# them here keeps the fix landing once — a new verb is added in a single place, never copied.
#
# The persist/write/emit/encrypt families keep the EXACT membership they had in assemble.py so the C→E
# derivation cannot regress; the read + call families are additions for the role classification.
PERSIST_VERBS = frozenset("persist persists store stores stored upsert upserts save saves saved "
                          "insert inserts inserted".split())
WRITE_VERBS = frozenset("write writes wrote update updates updated create creates created delete "
                        "deletes deleted remove removes removed append appends set sets put puts "
                        "record records add adds modify modifies increment decrement".split())
EMIT_VERBS = frozenset("emit emits emitted publish publishes dispatch dispatches broadcast "
                       "broadcasts enqueue enqueues".split())
# The CONSUMING side of a bus — `listens-to`/`subscribes`/`consumes` a broker. A separate family
# (NOT added to EMIT_VERBS, whose membership is frozen for the C→E derivation above): consumed only
# by `edge_role`, so a consumer edge reveals the messaging role instead of drawing the roleless
# nudge (three live rebuilds justified-not-fixed exactly this — `C4 listens-to D8` is role-revealing).
LISTEN_VERBS = frozenset("listen listens listens-to listened subscribe subscribes subscribed "
                         "consume consumes consumed dequeue dequeues polls-from".split())
ENCRYPT_VERBS = frozenset("encrypt encrypts encrypted decrypt decrypts".split())
# A READ of a data store — `queries`/`fetches` map here, NOT to service: "queries the database" /
# "fetches the record" are the standard way to describe a store read, so a `queries` edge on a SQL dep
# derives 'datastore'. (`_infer_ce_verb` still DEFAULTS ambiguous phrases to `reads`; this set only
# drives `edge_role`, so it never changes that derivation.)
READ_VERBS = frozenset("read reads queries query fetch fetches get gets load loads lookup lookups "
                       "select selects scan scans".split())
def edge_direction(verb: str) -> str:
    """A `C→E` arrow's verb as a `direction`, in the STEP's vocabulary — `in` a read, `out` a write,
    `""` when the verb reveals neither.

    THE ONE PLACE THE TWO VOCABULARIES MEET. An arrow says what a component does to a record across
    a whole codebase; a step says which way the data moved in one story. Asking whether they AGREE
    is the check this exists for, and it needs one mapping, not a fourth verb list beside the three
    frozen sets above — `PERSIST_VERBS`, `WRITE_VERBS` and `READ_VERBS` already carry the membership,
    and the C→E derivation depends on theirs being frozen.

    A GENERIC verb answers "": `uses`/`accesses` reveal no direction, and guessing one from them is
    how a roleless edge would start making claims it cannot back."""
    v = (verb or "").strip().lower()
    if v in READ_VERBS:
        return "in"
    if v in PERSIST_VERBS or v in WRITE_VERBS:
        return "out"
    return ""


# An unambiguous SERVICE call — reserved for genuine call verbs (NOT queries/fetches, which are reads).
CALL_VERBS = frozenset("call calls called request requests requested invoke invokes invoked".split())
# Generic / ROLELESS verbs — a C→D edge using one names no role (the thing the WS2 nudge flags).
# `edge_role` maps every one of these (and any unrecognized verb) to None.
GENERIC_VERBS = frozenset("uses use used integrates integrate integrated connects connect connected "
                          "accesses access accessed talks talk".split())


def edge_role(verb: str) -> str | None:
    """The ROLE a backbone edge's verb reveals: 'datastore' (persist/write/read families — a query IS a
    read), 'messaging' (emit + listen families — publishing AND consuming a bus both reveal it),
    'service' (call family ONLY), 'security' (encrypt family), or None
    for a generic/roleless verb (`uses`/`connects`/…) or any unrecognized verb — the None case is what
    the C→D role nudge flags. A dependency's role SET is the union of its incoming C→D edges' roles
    (`dep_roles`), so a dual-role dep (Redis as bus + store) is captured by its two real verbs, not a
    stored field."""
    v = (verb or "").strip().lower()
    if v in PERSIST_VERBS or v in WRITE_VERBS or v in READ_VERBS:
        return "datastore"
    if v in EMIT_VERBS or v in LISTEN_VERBS:
        return "messaging"
    if v in CALL_VERBS:
        return "service"
    if v in ENCRYPT_VERBS:
        return "security"
    return None


def dep_roles(verbs: Iterable[str]) -> set[str]:
    """The role SET a dependency plays, DERIVED from the verbs of its incoming C→D edges: each verb's
    `edge_role`, minus the roleless None. `[publishes, writes]` → `{messaging, datastore}` ('bus ·
    store'); no C→D edges → empty set (renders no role tag). Purely derived, so it can never drift from
    the edges (no parallel stored field)."""
    return {r for r in (edge_role(v) for v in verbs) if r is not None}


# A field's `FK→Ex` / `FK->Ex` marker, captured as a whole id token (so `FK→E1` never matches `E11`).
FK_MARKER = re.compile(r"FK(?:→|->)(E\d+)")


def fk_targets(markers: Iterable[str] | str) -> set[str]:
    """Entity ids a field points at via an `FK→Ex` / `FK->Ex` marker — matched as a whole id token
    (so `FK→E1` never matches `E11`). Accepts a marker list (``EntityField.markers``) or a
    space-joined string."""
    text = markers if isinstance(markers, str) else " ".join(markers)
    return set(FK_MARKER.findall(text))


def resolve_backing(
    src: str, dst: str,
    src_fields: list[tuple[str, str, set[str]]],
    dst_fields: list[tuple[str, str, set[str]]],
) -> tuple[list[str], str | None]:
    """Which REAL field(s) implement a domain relation `src --> dst`, and on which side. Each field is
    a `(name, type, fk_targets)` triple. Forward (the field lives on the source / arrow-tail) wins over
    reverse, mirroring how the relation is authored on the source card:
      - SOURCE fields typed by the target (`subscription:E15`) or marked `FK→dst` -> (names, 'src');
      - else TARGET fields marked `FK→src` (the back-reference) -> (names, 'dst');
      - else ([], None) — no field backs it (indirect / key-composition; carry a `{how}` note).
    ALL qualifying fields on the winning side are returned, in declaration order — a composite key
    (e.g. Snapshot's (user_id, page_id) both `FK→TrackedPage`) yields both, so the label shows the
    whole key instead of arbitrarily keeping just the first field. The canvas label and the panel's
    "Implemented by" line both derive from this one resolution."""
    fwd = [name for name, typ, fks in src_fields if typ == dst or dst in fks]
    if fwd:
        return fwd, "src"
    rev = [name for name, _typ, fks in dst_fields if src in fks]
    if rev:
        return rev, "dst"
    return [], None


# ── T6 use-case flows ─────────────────────────────────────────────────────────────────────────────
# `views.py` builds a Flow/FlowStep per use case straight from the model's `Flow`/`FlowStep`
# records (not from a markdown parse); `is_step_id` classifies each endpoint (an element ID vs a Role
# display name) so the viewer knows whether a step is a backbone reference or an actor interaction.
_STEP_ENDPOINT_ID = re.compile(r"^(?:UC\d+|SD\d+|C\d+|D\d+|E\d+|I\d+|S\d+)$")

#: An INTERFACE step — the door a story comes in by, or the far side it reaches out to.
#: `R1 → I3 → C12` reads "a person, through the dashboard, into the code". These steps are
#: structure, not detail, so the step-count band does not count them: without that, one added
#: step per flow puts 33 of the 150 flows across the four live maps over the band.
_INTERFACE_ID = re.compile(r"^I\d+$")


def is_interface_id(token: str) -> bool:
    return bool(_INTERFACE_ID.match((token or "").strip()))


def is_step_id(token: str) -> bool:
    """True if `token` is a BACKBONE element ID (C/D/E/UC/S/SD); False -> an actor step (a role).
    Deliberately does NOT match a role id `R\\d+`: `_flow_opening_actor` finds the actor step by
    `not is_step_id(src)`, so teaching this `R` would skip every actor step and silently blank the
    actor-attribution check. A role id is classified by `is_role_id`, separately."""
    return bool(_STEP_ENDPOINT_ID.match(token.strip()))


_ROLE_ID = re.compile(r"^R\d+$")


def is_role_id(token: str) -> bool:
    """True if `token` is a Role id (`R1`, `R2`, …) — the id an actor step / use-case actor references."""
    return bool(_ROLE_ID.match(token.strip()))


@dataclass
class FlowStep:
    n: int               # the step number as written
    src: str             # an element ID (C/D/E/…) or a Role display name
    dst: str             # same
    src_is_id: bool      # True -> src is an element ID; False -> a Role name (actor step)
    dst_is_id: bool
    phrase: str = ""     # authored inline phrase (after ": ") — e.g. the actor's action
    note: str = ""       # flow-specific note (after "· ")
    where: str | None = None  # THE location: the step's own call site (`path:line`), if authored
    subflow: str | None = None  # a reference step: "runs SFn here" (see model.FlowStep.subflow)
    ok: bool = True      # False -> the line could not be split into `from → to`


@dataclass
class Flow:
    uc: str              # the use case this flow realizes (its UC id, DEFINED in the Use-cases table)
    title: str
    steps: list[FlowStep]
    line_no: int
