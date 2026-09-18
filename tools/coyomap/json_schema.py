#!/usr/bin/env python3
"""Generate a JSON Schema for `project-map.json`, straight from the model dataclasses.

Documentation and IDE-autocomplete use ONLY — this is NOT wired into `coyomap validate`. Reason:
the existing structural loader (`model._build`/`_check`) already gives path-specific errors a
generic JSON-Schema validator library can't match ("$.components[3].purpose: expected a string,
got int" vs. a typical library's "is not of type 'string'"), and most of the REAL validation here
is semantic — ID references resolve, no hierarchy cycles, anchor formats — which JSON Schema
cannot express at all. So a schema-based validator would need `validate_model.py` to run anyway,
adding a second validation mechanism without removing the first. As pure documentation, though, it
is genuinely useful (IDE autocomplete while hand-inspecting a fragment, an interoperable artifact
for non-Python tooling) — and since it is GENERATED from the dataclasses, it cannot drift out of
sync the way a hand-maintained schema file would.

Regenerate after any model.py change:
    python -m coyomap.json_schema > method/project-map.schema.json
Stdlib-only.
"""
from __future__ import annotations

import json
import types
from dataclasses import MISSING, fields as dc_fields, is_dataclass
from typing import Union, get_args, get_origin, get_type_hints

from coyomap import grammar
from coyomap.model import FORMAT, ID_SHAPE, ProjectModel
from coyomap.anchors import FILE_ANCHOR as _ANCHOR_LINE, FILE_LINE_ANCHOR

_PRIMITIVE = {str: "string", int: "integer", bool: "boolean"}

_ANCHOR_DESC = ("bare `path:line` anchor: a repo-relative file path, optionally followed by "
                "`:line` or `:line-line` — never a markdown link (its label would just be the "
                "basename, fully derivable from the path, so it is never authored).")
_DIR_OR_FILE_DESC = ("either a bare file `path:line` anchor (see `evidence[].file`'s description) "
                      "or a bare directory ref ending in `/`.")
_EXTRA_DESC = ("freeform authored columns — any JSON value, agent-chosen keys. The ONE place with "
               "no fixed meaning: a key `coyomap validate` gives an enforced shape to, or that the "
               "method documents as a convention, graduates to a real field instead and is then "
               "rejected here under its old spelling (this is how `files`/`evidence`/`package`/"
               "`alternative` were promoted).")

# (dataclass name, field name) -> schema overrides, merged onto the structurally-inferred type.
# `description` explains WHY a constraint exists, not just what it is; `pattern`/`enum`/`const`
# encode the constraint itself where one is actually enforced (by `coyomap validate` or the loader).
FIELD_META: dict[tuple[str, str], dict] = {
    ("Role", "kind"): {"description": "human | service | ai-agent, free text (not a closed "
                            "vocabulary). `ai-agent` is a program driven by a language model, "
                            "acting for somebody, and is ALWAYS outside the product — only "
                            "`service` with an `internal` audience is the product's own scheduled "
                            "work."},
    ("Role", "audience"): {"enum": ["", *grammar.ROLE_AUDIENCE], "description": "WHICH SIDE of the "
                            "product this actor sits on. `internal` = the side of the company that "
                            "ships it; `user` = everyone else, including someone who has not bought "
                            "it yet. Same question of a person and of a program, answered from "
                            "different evidence: a PERSON is `internal` when they work for that "
                            "company; a PROGRAM is judged by WHOSE MACHINE IT IS, never by whose "
                            "work it happens to be doing — the customer set it up (`user`), or the "
                            "company runs it OR PAYS A VENDOR to run it (`internal`). A payment "
                            "provider, an email sender or any other bought service is `internal`: "
                            "no customer configured it. The map's ONE authored answer to 'who is "
                            "this for' — a capability's audience is DERIVED from the roles driving "
                            "its use cases, never authored, so the two can never contradict. "
                            "Orthogonal to `kind`."},
    ("Role", "drives"): {"description": "the use cases this role drives — free text, ids inside."},
    ("Role", "relations"): {"description": "optional links to other roles, for when one human "
                             "typically holds several of the map's roles. Roles are permission hats "
                             "the code recognizes; without a relation the viewer draws one person as "
                             "several strangers. Empty/absent = no relation stated."},
    ("RoleRelation", "kind"): {"enum": ["becomes", "includes"], "description": "`becomes` = this "
                                "role turns into `role` at the use case `at` (the transition is a "
                                "real, mapped action — e.g. the prospect becomes the admin at 'sign "
                                "in and name the organization'). `includes` = this role may do "
                                "everything `role` may do (the admin includes the member)."},
    ("RoleRelation", "role"): {"pattern": r"^R\d+$", "description": "the other role — must be a "
                                "defined Role id."},
    ("RoleRelation", "at"): {"pattern": r"^UC\d+$", "description": "becomes only: the use case "
                              "where the hat changes — must be a defined use-case id."},
    ("RoleRelation", "source"): {"description": "`includes` only: the `path:line` that GRANTS the "
                              "inclusion — the check that lets this role do what the other may do. "
                              "An `includes` is an access claim and the viewer draws it as one, so "
                              "it carries evidence like every other access claim. Null is allowed "
                              "and says nobody has anchored it; `audit` then challenges it as an "
                              "unanchored access claim rather than passing it in silence."},
    ("GlossaryRow", "source"): {"description": _DIR_OR_FILE_DESC + " The term's canonical code home "
                               "(where it is defined); null when the concept has no single code home "
                               "(a pure product-level term)."},
    ("GlossaryRow", "aliases"): {"description": "extra surface forms the viewer also links to this "
                               "term's definition. Real alternative names only, unambiguous in this "
                               "project's prose — never a bare generic English word, and never a "
                               "plural/possessive/case/hyphen variant (the viewer folds those "
                               "automatically). See the Glossary deliverable in method.md."},
    ("GlossaryRow", "no_autolink"): {"description": "true = the term's own name is excluded from "
                               "automatic in-prose linking; it links only via its aliases (or not "
                               "at all). For a term whose name is an ordinary English word that "
                               "would over-link."},
    ("HappyStep", "id"): {"pattern": r"^HP\d+$", "description": "this step's position in the "
                           "happy path."},
    ("HappyStep", "uc"): {"pattern": r"^UC\d+$", "description": "the use case this step realizes."},
    ("HappyStep", "why"): {"description": "the prerequisite that fixes this step's position — "
                             "why it can't come earlier in the happy path."},
    ("Group", "id"): {"pattern": ID_SHAPE.pattern, "description": "`S<n>` in subsystems[], "
                       "`SD<n>` in subdomains[], `CAP<n>` in capabilities[], `BLK<n>` in blocks[] "
                       "— same dataclass, four id forests."},
    ("Group", "parent"): {"pattern": ID_SHAPE.pattern, "description": "the enclosing group's id, "
                           "in the SAME forest (an S parents an S, an SD an SD, a CAP a CAP, a BLK "
                           "a BLK), or null for top-level."},
    ("Group", "happy_path"): {"enum": ["", *grammar.CAP_HAPPY_PATH], "description": "CAPABILITY-ONLY: "
                               "must the happy path reach this capability? `expected` = yes, at "
                               "least one of its use cases; `excluded` = no, and one 'Happy Path "
                               "coverage' record says why. Deliberately NOT derived from happy_path[] "
                               "— a value that always agreed with the happy path could never disagree with "
                               "it, and the disagreement IS the check. Says nothing about audience. "
                               "`validate` blocks it on a subsystem or a subdomain."},
    ("Group", "stakes"): {"description": "CAPABILITY-ONLY: one entry per driving actor, saying "
                           "what THAT actor comes to this capability to do. The Features diagram "
                           "labels each actor→feature arrow with the actor's stake; a capability's "
                           "purpose alone is written from one chair and hides the other roles. "
                           "`validate` blocks it on the other forests, and advises when a derived "
                           "driving actor has no entry."},
    ("Stake", "actor"): {"pattern": r"^R\d+$", "description": "the driving role this stake belongs "
                          "to — must be a defined Role id."},
    ("Stake", "stake"): {"description": "a short verb phrase with the actor as the implied subject "
                          "('mounts, configures and runs the servers'). Must read correctly after "
                          "the actor's name; writing rules apply (one idea, plain words, no code, "
                          "no step numbers)."},
    ("Group", "story"): {"description": "CAPABILITY-ONLY, and only worth authoring on a feature the "
                          "happy path never reaches: where that feature sits in the ONE story column the "
                          "viewer draws. The happy path reads unbroken and the off-happy-path features form a "
                          "block after it, so `after` ORDERS that block (the block is already after "
                          "every happy-path feature) while `before` is the one placement that keeps a "
                          "feature among the happy path — author it on a lead-in like a marketing page, "
                          "which belongs BEFORE the first step. Absent = the viewer guesses from "
                          "the feature's actors' last happy-path step, which orders the block sensibly "
                          "for trailing features (ops, a chat variant of work already walked) and "
                          "never rescues a lead-in. `validate` blocks it on the other forests."},
    ("StoryAnchor", "place"): {"enum": ["before", "after"], "description": "exactly `before` or "
                                "`after` (lowercase) — the derivation and `validate` compare "
                                "strictly."},
    ("StoryAnchor", "feature"): {"pattern": r"^CAP\d+$", "description": "the feature this one reads "
                                  "beside — must be a defined capability id, never the capability "
                                  "itself."},
    ("Group", "owners"): {"items": {"pattern": r"^CAP\d+$"}, "description": "SUB-DOMAIN-ONLY: "
                           "which FEATURE this data area exists for — the one that creates its "
                           "records and runs their lifecycle. AUTHORED, never derived: every "
                           "derivation was measured on three live maps and each guessed from what "
                           "the code TOUCHES, which is not what the data is FOR (snapshots are "
                           "first written by page tracking, but they exist so change detection can "
                           "compare them). One id = that feature owns the area; several = "
                           "deliberately shared among exactly those; field ABSENT = the decision "
                           "has not been made, and an advisory asks for it. `[]` is a shape error, "
                           "not an answer. NEVER author one to complete a diagram: an owner the "
                           "area's records are never reached by is reported as an owner with no evidence. "
                           "`validate` blocks it on a subsystem, a capability or a block, and "
                           "cross-examines the list against the derived touches."},
    ("Group", "specified_under"): {"items": {"pattern": r"^CAP\d+$"}, "description": "BLOCK-ONLY: "
                           "the FEATURE(s) a person writing the product's spec would put these rules "
                           "under. TWO STANDPOINTS, and this field is the first: SPEC (under which "
                           "feature would these rules be WRITTEN) versus ENFORCEMENT (in which "
                           "feature's code are they APPLIED). They differ on most areas — mcpolis's "
                           "'Who may call which tool' is specified under Access control and enforced "
                           "inside the gateway; its 'Plan caps' is applied across six features and "
                           "specified under a plans feature that product has not shipped, so the "
                           "field is absent there. The ENFORCEMENT answer is already derivable (a "
                           "rule's call sites resolve to components, and its steps join to use cases "
                           "and so to features), which is what settles it: nothing in the code says "
                           "where a rule would be WRITTEN IN A SPEC, and that judgement is the one a "
                           "person has to make. AUTHORED, like `owners` one field up, and for the "
                           "same measured reason — every derivation was tried on three live maps and "
                           "every one failed (the derived top feature holds 52% and 61% of an area's "
                           "links at the median; 8 of 32 areas win on under half). NOT `owners`, "
                           "which is about DATA. The Rules page groups by it, and inherits the story "
                           "column's order for free. One id; several if it genuinely spans them; "
                           "ABSENT = not decided, and an advisory asks. `[]` is a shape error. "
                           "`validate` blocks it on the other three forests and cross-examines it "
                           "against the features the area's rules reach."},
    ("Group", "source"): {"description": _DIR_OR_FILE_DESC + " The group's home directory (or a "
                           "representative file)."},
    ("Entity", "owners"): {"items": {"pattern": r"^CAP\d+$"}, "description": "OVERRIDE of the "
                            "sub-domain's `owners`, for the one record whose owning feature differs "
                            "from its area's — an audit entry sits in the Audit trail area but is "
                            "written by the gateway. Author it ONLY where it differs from what "
                            "would be inherited; an override equal to the inherited answer is "
                            "reported as redundant. Absent = inherit, walking up `subdomain` then "
                            "`parent`. Same vocabulary and same rules as `subdomains[].owners`."},
    ("UseCase", "id"): {"pattern": r"^UC\d+$"},
    # TWO FIELDS, one sentence each. They were one cell called `trigger_outcome`, which read as "the
    # trigger's outcome" — one thing — while it always held two, and every reader had to find the
    # seam by guessing at a full stop.
    ("UseCase", "trigger"): {"description": "what STARTS this use case, in one plain sentence."},
    ("UseCase", "outcome"): {"description": "what the actor COMES AWAY WITH, in one plain sentence. "
                                            "The pair is the use case's outside face; its flow is "
                                            "the inside one. Never join the two into one cell."},
    ("UseCase", "capability"): {"pattern": r"^CAP\d+$", "description": "the capability this use "
                                "case belongs to, or null. Assigned at synthesis via `reconcile` "
                                "(a `CAP<n>` does not exist when the behavioral fragment is written)."},
    ("UseCase", "entry_points"): {"items": {"pattern": r"^EP\d+$"}, "description": "the TRIGGER "
                                   "arm of entry-point claiming: the front door(s) an actor hits to "
                                   "START this use case. Empty is legitimate — the surface may sit "
                                   "inside a coarse T4 row a sibling already names."},
    ("EntryPoint", "id"): {"pattern": r"^EP\d+$", "description": "MINTED BY `assemble` from content "
                            "(source + trigger + owner + kind), never authored — leave it out of a "
                            "fragment. Change-impact keeps its own content key (`ep:{source}`), "
                            "which is stable across rebuilds where a minted number is not."},
    ("Role", "id"): {"pattern": r"^R\d+$", "description": "a role is a first-class element (`R<n>`), "
                     "referenced by id — a use case's `actors` and a flow's actor steps carry role ids."},
    ("EvidenceItem", "file"): {"pattern": _ANCHOR_LINE.pattern, "description": _ANCHOR_DESC},
    ("EvidenceItem", "why"): {"description": "why this citation supports the claim — what a "
                               "skeptic re-reading `file` should find true."},
    ("Component", "id"): {"pattern": r"^C\d+$"},
    ("Component", "subsystem"): {"pattern": r"^S\d+$", "description": "the owning subsystem's "
                                  "id, or null if ungrouped."},
    ("Component", "entry_point"): {"pattern": _ANCHOR_LINE.pattern,
                                    "description": _ANCHOR_DESC + " Where the component is "
                                    "TRIGGERED — distinct from `source` (where it LIVES)."},
    ("Component", "source"): {"description": _DIR_OR_FILE_DESC + " Where the component LIVES."},
    ("Component", "files"): {"description": "repo-relative file paths this component owns, as a "
                              "plain list — not a count, not a comma-joined string."},
    ("Component", "extra"): {"description": _EXTRA_DESC},
    # Enumerated because the dispatch template asks for exactly these two words while the field
    # accepted any string, so a harvest agent could return high/medium/low and `lint-fragment`
    # passed it clean. method.md also listed `confidence` among the STRAY keys to omit while the
    # same template required it — both halves of that contradiction are fixed together.
    ("Group", "confidence"): {"enum": [*grammar.CONFIDENCE_VALUES, ""],
                             "description": "verified = read in the code; inferred = deduced. '' = unstated."},
    ("Component", "confidence"): {"enum": [*grammar.CONFIDENCE_VALUES, ""],
                             "description": "verified = read in the code; inferred = deduced. '' = unstated."},
    ("Dep", "confidence"): {"enum": [*grammar.CONFIDENCE_VALUES, ""],
                             "description": "verified = read in the code; inferred = deduced. '' = unstated."},
    ("TestRow", "confidence"): {"enum": [*grammar.CONFIDENCE_VALUES, ""],
                             "description": "verified = read in the code; inferred = deduced. '' = unstated."},

    ("Dep", "id"): {"pattern": r"^D\d+$"},
    ("Dep", "kind"): {"enum": [*grammar.DEP_KINDS, None], "description": "closed Context "
                       "vocabulary; null → inferred from `type`."},
    ("Dep", "bucket"): {"description": "PURPOSE bucket (seeded-open) grouping the dep within its "
                        "diagram — external systems in Context, in-process code in the Libraries "
                        f"drill. Prefer a seed ({', '.join(grammar.DEP_BUCKET_SEEDS_EXTERNAL)} for "
                        f"external systems; {', '.join(grammar.DEP_BUCKET_SEEDS_LIBRARY)} for "
                        "libraries); mint a new one only when none fits. Empty → inferred from "
                        "`type` + `used_for`."},
    ("Dep", "where_configured"): {"pattern": _ANCHOR_LINE.pattern, "description": _ANCHOR_DESC},
    ("Dep", "package"): {"description": 'one string: "<name> <version> (<where declared>)".'},
    ("Dep", "alternative"): {"description": "the fallback used instead of this dep, and under "
                              "what circumstance."},
    ("Dep", "extra"): {"description": _EXTRA_DESC},
    ("Dep", "interfaces"): {"items": {"type": "string", "pattern": r"^I\d+$"},
                            "description": "the interfaces this dep belongs to, on EITHER side of "
                            "each: the dep may BE the surface (an error tracker) or sit on its FAR "
                            "SIDE (a coding agent that calls our skill). A list, because one outside "
                            "system really does sit on several surfaces. `side` is authored on the "
                            "interface, never inferred from this."},
    ("Dep", "not_an_interface"): {"description": "why this dep is no interface at all — REQUIRED on "
                            "a datastore/messaging/service/platform dep that names no interface. "
                            "Without it there is no way to tell 'deliberately not one' from 'nobody "
                            "looked', which is the trap a search service sets: a search over the "
                            "product's own records is not an interface, a search over the open web "
                            "is, and the call site looks identical."},
    ("Interface", "id"): {"pattern": r"^I\d+$"},
    ("Interface", "name"): {"description": "the surface in PRODUCT words ('Customer dashboard'), "
                            "never a code word ('http-route')."},
    ("Interface", "what"): {"description": "one sentence: what this surface is for."},
    ("Interface", "side"): {"enum": [*grammar.INTERFACE_SIDES], "description": "whose DESIGN the "
                            "surface is: if the far side vanished tomorrow, would the shape of this "
                            "thing change? Our command line keeps its shape; our call to a payment "
                            "processor does not."},
    ("Interface", "facing"): {"enum": [*grammar.INTERFACE_FACINGS, ""], "description": "who it "
                            "serves. AUTHORED — `Role.audience` answers a different question (which "
                            "side of the COMPANY an actor sits on) and marks a bought payment "
                            "service 'internal' while its interface is user-facing."},
    ("Interface", "kind"): {"description": "WHAT THIS SURFACE IS, seeded-open: "
                            + "/".join(grammar.INTERFACE_KIND_SEEDS)
                            + ". WHAT IT IS, never WHAT IT IS FOR — a payment processor and a crash reporter "
                            "are both `api`, and `Dep.bucket` already says which is which in a "
                            "richer vocabulary. A kind that answers 'what is it for' is "
                            "mis-modelled. Prefer a seed; mint only when none fits, and reuse the "
                            "exact spelling on rebuild."},
    ("Interface", "ways_in"): {"items": {"type": "string", "pattern": r"^EP\d+$"},
                            "description": "the entry points this surface is made of. Assigned "
                            "through `reconcile` (`ways_in`), never hand-written into a fragment: "
                            "`EPn` ids are minted by `assemble` from content. Empty is legitimate — "
                            "a `theirs` surface has none, and neither do the files a product writes "
                            "or the settings an operator sets."},
    ("Interface", "source"): {"pattern": _ANCHOR_LINE.pattern, "description": "the one line that "
                            "declares the SURFACE — the router, the command table, the file writer. "
                            "Advisory, never required: a settings surface is declared in no single "
                            "place."},
    ("Interface", "confidence"): {"enum": [*grammar.CONFIDENCE_VALUES, ""], "description":
                            "verified = read in the code; inferred = deduced. '' = unstated."},
    ("EntryPoint", "source"): {"pattern": _ANCHOR_LINE.pattern, "description": _ANCHOR_DESC},
    ("EntryPoint", "component"): {"pattern": r"^C\d+$", "description": "the owning component's id."},
    ("EntryPoint", "kind"): {"description": "what the entry point IS — a SEEDED-OPEN vocabulary "
                              "(never blocking): prefer a seed "
                              f"({', '.join(grammar.ENTRY_POINT_KINDS)}); mint a project-specific "
                              "kind only when none fits, and reuse the exact spelling on rebuild "
                              "(validate folds known drift like 'http'→'http-route' and nudges the "
                              "rest)."},
    ("EntryPoint", "cadence"): {"description": "WHEN a self-activated entry point runs: a cron "
                                 "expression ('0 3 * * *'), an interval ('every 30s'), 'on-boot', "
                                 "or 'continuous'. Meaningful only when the effective activation "
                                 "is 'self' (a cadence on an external EP draws an advisory)."},
    ("EntryPoint", "cadence_source"): {"pattern": _ANCHOR_LINE.pattern,
                                        "description": "bare path:line anchor to the line "
                                        "DECLARING the schedule (beat/cron config, compose, the "
                                        "loop's sleep) — often a different line than `source`; '' "
                                        "on a set cadence = inferred (advisory)."},
    ("Group", "tech"): {"description": "SUBSYSTEM-ONLY: one honest stack label ('Python/FastAPI', "
                         "'Go', 'Elixir') read off the manifests — not a stack essay. validate "
                         "blocks it on a subdomain (a bounded context has no stack)."},
    ("Group", "tech_source"): {"pattern": _ANCHOR_LINE.pattern,
                                "description": "optional bare path:line anchor to the manifest "
                                "line proving the tech label (go.mod, package.json, "
                                "pyproject.toml)."},
    ("EntryPoint", "activation"): {"enum": [*grammar.ACTIVATIONS, ""], "description": "who starts it: "
                                    "'self' (timer/loop/boot/signal/queue consumer — runs with no "
                                    "caller) or 'external' (route/CLI/callback/webhook); '' → inferred "
                                    "from `kind`."},
    ("EntityField", "markers"): {"description": "annotation tokens, not free text: PK / FK→En / "
                                  "unique / ? / []."},
    ("EntityRelation", "verb"): {"description": "contains / has / isA (structural, canonical) or "
                                  "a free association verb."},
    ("EntityRelation", "target"): {"pattern": r"^E\d+$"},
    ("EntityRelation", "keyed_by"): {"description": "storage key name(s) the store uses to relate the "
                                      "two — a lookup/partition key it imposes, NOT a field on EITHER "
                                      "entity's row. Use ONLY when no field backs the link; if a field "
                                      "carries the id (marked FK or a plain same-named column) that is "
                                      "a (reverse) foreign key, not a key. Drawn on the arrow with the "
                                      "«key» marker."},
    ("MessagingRow", "name"): {"description": "unique channel/queue/topic name — the row's key "
                                "(name-keyed like a deployment unit; nothing points at a channel)."},
    ("MessagingRow", "kind"): {"description": "seeded-open: queue / topic / stream / pubsub / "
                                "job-queue; mint a project-specific kind when none fits."},
    ("MessagingRow", "broker"): {"pattern": r"^D\d+$", "description": "the messaging/datastore dep "
                                  "carrying the channel; '' = in-process."},
    ("MessagingRow", "payload"): {"pattern": r"^E\d+$", "description": "the entity a message "
                                   "carries; '' = untyped/none."},
    ("MessagingRow", "source"): {"pattern": _ANCHOR_LINE.pattern,
                                  "description": "bare path:line anchor to where the channel NAME "
                                  "is declared."},
    ("StateMachine", "states"): {"description": "the declared state names — non-empty, unique; "
                                  "never synthesized (record only a lifecycle the code implements "
                                  "in an enum / status constants / dispatch table)."},
    ("StateMachine", "source"): {"pattern": _ANCHOR_LINE.pattern,
                                  "description": "bare path:line anchor to the line DECLARING the "
                                  "states; '' = inferred (advisory)."},
    ("StateTransition", "on"): {"description": "the trigger label ('connect ok', 'refresh "
                                 "failed'); optional."},
    ("Store", "dep"): {"pattern": r"^D\d+$", "description": "the physical datastore/messaging dep "
                        "holding this entity (a D-id); null for a store with no dep (in-memory, "
                        "in-code registry)."},
    ("Store", "mode"): {"enum": [*grammar.STORE_MODES, ""],
                         "description": "how the entity relates to its store — closed vocabulary, "
                         "exact match: collection (own compartment) / embedded (PERSISTED inside "
                         "a SAVED parent's row — a shape merely nested inside another in-memory "
                         "object is NOT embedded, it takes its holder's own mode) / projection (a "
                         "read view over rows another entity owns) / transient "
                         "/ cache / in-code / enum; '' = unstated."},
    ("Store", "container"): {"description": "the compartment inside the dep: collection / table / "
                              "key prefix / bucket / file name."},
    ("Store", "notes"): {"description": "what the shape can't say: TTL, cache tiers, compression."},
    ("Entity", "id"): {"pattern": r"^E\d+$"},
    ("Entity", "subdomain"): {"pattern": r"^SD\d+$", "description": "the owning subdomain's id, "
                               "or null if ungrouped."},
    ("Entity", "source"): {"description": _DIR_OR_FILE_DESC + " Must anchor the entity's actual "
                            "type DEFINITION (the `class X`/`@dataclass` line), never a use site."},
    ("FlowStep", "src"): {"description": "an element id, or a Role display name (an actor step)."},
    ("FlowStep", "dst"): {"description": "same shape as `src`."},
    ("FlowStep", "where"): {"pattern": _ANCHOR_LINE.pattern, "description": _ANCHOR_DESC + " THE "
                             "location: this step's own call site — a step is exactly one interaction, "
                             "so its anchor is precise (unlike an edge's `where`, an example). Required "
                             "on element↔element steps unless `no_call_site`."},
    ("FlowStep", "no_call_site"): {"description": "explicit opt-out (mirrors Edge.no_call_site): this "
                                    "step has no single call site — `where` may be null."},
    ("FlowStep", "direction"): {"enum": [*grammar.STEP_DIRECTIONS, ""], "description":
                            "WHICH WAY THE DATA MOVES, read from the PRODUCT's own code: in = it "
                            "arrives, out = it leaves, both = one exchange runs each way. Owed "
                            "where the map's OWN CODE touches a SURFACE (in = the product receives, "
                            "out = it sends) or a RECORD (in = a read, out = a write); EMPTY on "
                            "every other step, INCLUDING A DOOR — a role standing at a surface is a "
                            "human action with no product end. It is the map's only statement "
                            "of direction: the arrows between a component and a record say both "
                            "read and write on half the record steps, and no arrow reaches a "
                            "surface at all."},
    ("FlowStep", "subflow"): {"pattern": r"^SF\d+$", "description": "a REFERENCE step: 'runs SFn "
                               "here'. src/dst stay authored (the run's entry/exit endpoints); "
                               "`phrase` may be empty (defaults to the sub-flow's name); the step "
                               "carries no `where`/`no_call_site` of its own. One level only — a "
                               "sub-flow's step may not itself reference a sub-flow."},
    ("Flow", "uc"): {"pattern": r"^UC\d+$"},
    ("SubFlow", "id"): {"pattern": r"^SF\d+$"},
    ("SubFlow", "name"): {"description": "what the shared sequence does — a single verb phrase, "
                           "like a use-case name."},
    ("Edge", "where"): {"pattern": _ANCHOR_LINE.pattern, "description": _ANCHOR_DESC + " A verified "
                         "EXAMPLE call site — one line in `src`'s code where it invokes `dst`, possibly "
                         "one of many (a witness grounding the edge, not a catalog of its traffic)."},
    ("Edge", "why"): {"description": "the relationship's rationale — distinct from either "
                       "endpoint's own `purpose`."},
    ("RunRow", "source"): {"pattern": _ANCHOR_LINE.pattern, "description": _ANCHOR_DESC
                            + " Where the run command is defined — the script, Makefile target, or "
                            "config line the action runs."},
    ("SecurityRow", "source"): {"pattern": _ANCHOR_LINE.pattern, "description": _ANCHOR_DESC
                                 + " The auth check in code (the enforcement site)."},
    ("NonEntityType", "source"): {"description": _DIR_OR_FILE_DESC
                                   + " Where the deliberately-unmodelled type is defined."},
    ("VariantTag", "env"): {"description": "the environment this deployment unit runs in — must name a "
                             "`environments` entry."},
    ("VariantTag", "source"): {"pattern": _ANCHOR_LINE.pattern, "description": _ANCHOR_DESC
                                + " The manifest line that PLACES the unit in this environment (the "
                                "compose `profiles:` line, the overlay/values file, the stage). Empty "
                                "string = INFERRED (no manifest witness): `validate` surfaces it as an "
                                "advisory, never blocks; a CITED source that doesn't resolve IS a hard "
                                "block under `--check-sources`."},
    ("BusinessRule", "id"): {"pattern": r"^BR\d+$"},
    ("BusinessRule", "name"): {"description": "the SHORT title — a few words a reader scans, the way "
                                "a use case has a name beside its trigger\u2192outcome sentence "
                                "(\"Owner-only cancellation\"). Not a shortened statement: name the "
                                "DECISION, then state it in full in `statement`."},
    ("BusinessRule", "statement"): {"description": "ONE product decision, in product language and "
                                     "naming no component — the sharp test is 'could a product "
                                     "person have decided otherwise?'. Two claims joined by 'and' "
                                     "are two rules."},
    ("BusinessRule", "block"): {"pattern": r"^BLK\d+$", "description": "the decision area this rule "
                                 "belongs to, or null. Assigned at synthesis via `reconcile` (a "
                                 "`BLK<n>` does not exist when the rule is authored), exactly as "
                                 "`use_cases[].capability` is."},
    ("BusinessRule", "access"): {"description": "this rule governs WHO MAY DO WHAT — the security "
                                  "marker. The security surface table and the eval's auth coverage "
                                  "read it."},
    ("BusinessRule", "risk"): {"description": "what is AT STAKE if this decision is wrong or "
                                "absent — a judgement, not a derivation. Distinct from a site's "
                                "`why` (what that LINE does): a risk note says what the decision's "
                                "limit costs. Rendered in the security surface table for an "
                                "`access` rule."},
    ("BusinessRule", "confidence"): {"enum": [*grammar.CONFIDENCE_VALUES, ""],
                             "description": "verified = read in the code; inferred = deduced. '' = unstated."},
    ("BusinessRule", "sites"): {"description": "every place the decision is ENFORCED. The rule's "
                                 "components, its use-case steps and whether it has been swept are "
                                 "DERIVED from these — there is no authored field for any of them."},
    ("RuleSite", "where"): {"pattern": FILE_LINE_ANCHOR.pattern, "description": _ANCHOR_DESC
                             + " The OPERATIVE line — the one that acts. A definition header, an "
                             "import, a comment or a blank line is a shape error, not a site, and "
                             "the `:line` is REQUIRED: without it the operative-line check is "
                             "skipped and the claim cannot be falsified. null (with "
                             "`no_call_site`) = enforced by construction, no single line."},
    ("RuleSite", "why"): {"description": "what this line does FOR the rule ('rejects a non-owner "
                           "caller') — reconstructible from the line itself, with no clause added."},
    ("RuleSite", "no_call_site"): {"description": "explicit opt-out (mirrors Edge.no_call_site): "
                                    "this rule is enforced by construction (a type, a schema "
                                    "constraint, a config-wired guard) — `where` may be empty."},
    ("ProjectModel", "format"): {"const": FORMAT},
    ("ProjectModel", "commit"): {"description": "short commit sha the map was built at."},
    ("ProjectModel", "committed"): {"description": "YYYY-MM-DD."},
    ("ProjectModel", "tool_commit"): {
        "description": "short commit sha of the COYOMAP build that produced this map — not the "
                       "analysed repo's. Two maps are only comparable against the tools that made "
                       "them; absent on maps built before this was stamped."},
    ("ProjectModel", "tool_committed"): {"description": "YYYY-MM-DD."},
    ("ProjectModel", "built"): {"description": "YYYY-MM-DD HH:MM."},
}


#: Fields the schema REQUIRES even though the dataclass gives them a default. The two normally
#: coincide — a field with no default is required — but they answer different questions: the default
#: says "can an already-written map still be loaded", the schema says "must new authored content
#: carry this". `BusinessRule.name` needs both answers: a fragment without it is invalid, while a map
#: written before the field existed must still open so the viewer can render it and `validate` can
#: report it. Without this split, adding a required field to the model means old maps cannot be read
#: at all — not even to be told what is missing.
_ALSO_REQUIRED = {("BusinessRule", "name")}


def _schema_for(hint: object, defs: dict[str, dict]) -> dict:
    """A JSON-Schema fragment for one type hint — mirrors `model._check`'s type dispatch (str, int,
    bool, X|None, list[T], dict[str,V], nested dataclass), but DESCRIBES a shape instead of
    validating a value."""
    origin = get_origin(hint)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(hint) if a is not type(None)]
        nullable = len(args) < len(get_args(hint))
        inner = _schema_for(args[0], defs)
        if nullable and "type" in inner:
            t = inner["type"]
            inner = {**inner, "type": [*t, "null"] if isinstance(t, list) else [t, "null"]}
        return inner
    if hint in _PRIMITIVE:
        return {"type": _PRIMITIVE[hint]}
    if origin is list:
        (item_hint,) = get_args(hint)
        return {"type": "array", "items": _schema_for(item_hint, defs)}
    if origin is dict:
        _key_hint, val_hint = get_args(hint)
        if val_hint is object:
            return {"type": "object"}  # `extra`: any JSON value per key — see FIELD_META
        return {"type": "object", "additionalProperties": _schema_for(val_hint, defs)}
    if is_dataclass(hint):
        _ensure_def(hint, defs)  # type: ignore[arg-type]
        return {"$ref": f"#/$defs/{hint.__name__}"}  # type: ignore[union-attr]
    raise TypeError(f"unsupported type in schema generation: {hint!r}")


def _ensure_def(cls: type, defs: dict[str, dict]) -> None:
    """Populate `defs[cls.__name__]` once, recursing into every field's type. The placeholder
    assignment before recursing guards a (currently nonexistent, but cheap to guard) self-reference
    from looping forever."""
    if cls.__name__ in defs:
        return
    defs[cls.__name__] = {}
    hints = get_type_hints(cls)
    props: dict[str, dict] = {}
    required: list[str] = []
    for f in dc_fields(cls):
        prop = _schema_for(hints[f.name], defs)
        meta = FIELD_META.get((cls.__name__, f.name), {})
        prop = {**prop, **{k: v for k, v in meta.items() if k != "description"}}
        if "description" in meta:
            prop["description"] = meta["description"]
        props[f.name] = prop
        if ((f.default is MISSING and f.default_factory is MISSING)  # type: ignore[misc]
                or (cls.__name__, f.name) in _ALSO_REQUIRED):
            required.append(f.name)
    defs[cls.__name__] = {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


def generate_schema() -> dict:
    """The whole schema: `ProjectModel`'s shape inlined at the top level, every nested dataclass
    (`Component`, `Dep`, `EvidenceItem`, `Entity`, …) as a reusable `$defs` entry."""
    defs: dict[str, dict] = {}
    _ensure_def(ProjectModel, defs)
    root = defs.pop("ProjectModel")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://coyomap.dev/schemas/project-map.schema.json",
        "title": "coyomap project map",
        "description": "Auto-generated from tools/coyomap/model.py — documentation and IDE-"
                        "autocomplete use only; NOT used by `coyomap validate` (see this module's "
                        "docstring, and method/model.md, for why). Regenerate with "
                        "`python -m coyomap.json_schema > method/project-map.schema.json`.",
        **root,
        "$defs": defs,
    }


def main() -> int:
    print(json.dumps(generate_schema(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
