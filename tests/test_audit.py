#!/usr/bin/env python3
"""Tests for `coyomap audit` — the adversarial pass (L1 self-contradiction + L2 worklist).

The scenario maps are authored directly as JSON model documents — the format the audit
actually reads — so these tests exercise the LIVE pipeline (model audit), not the retired markdown
audit.

Stdlib-only — no pytest required. Run either way (needs an editable install: `make deps`):
    python3 tests/test_audit.py        # built-in runner (prints pass/fail)
    pytest tests/test_audit.py         # if pytest is installed
"""
from __future__ import annotations

import itertools
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from coyomap import audit_model
from coyomap.model import (
    BusinessRule,
    ExtraSection,
    Group,
    HappyStep,
    Role,
    RuleSite,
    Component,
    Dep,
    Edge,
    Entity,
    EntryPoint,
    Flow,
    FlowStep,
    MessagingRow,
    ProjectModel,
    SecurityRow,
    StateMachine,
    StateTransition,
    Store,
    SubFlow,
    UseCase,
    load_model,
)

AUDIT = [sys.executable, "-m", "coyomap.audit_model"]


def audit_md(json_text: str) -> list[audit_model.Finding]:
    """The L1 findings for a scenario map: load the model document, audit it."""
    return audit_model.audit_model(load_model(json_text))


def l2(json_text: str) -> list[audit_model.WorkItem]:
    """The L2 worklist for a scenario map, through the same model-loading path."""
    return audit_model.l2_worklist_model(load_model(json_text))


# --- builders (JSON model documents) -----------------------------------

def make_all_theme_model() -> ProjectModel:
    """A model exercising EVERY worklist tier, so the order assertion is not vacuous on a fixture that
    emits one theme (the earlier version's fixture emitted only `ownership`)."""
    m = ProjectModel(title="T", goal="G")
    m.use_cases = [UseCase(id="UC1", name="Do it")]
    m.components = [Component(id="C1", name="A", purpose="p"),
                    Component(id="C2", name="B", purpose="p")]
    m.deps = [Dep(id="D1", name="Postgres", kind="datastore", type="SQL")]
    m.entities = [Entity(id="E1", name="Order", source="src/o.py:1",
                         store=Store(dep="D1", container="orders", mode="row")),
                  Entity(id="E2", name="Audit", source="src/x.py:1")]
    m.security = [SecurityRow(surface="API auth", who="signed-in", source="src/auth.py:9",
                              risk="a hole")]
    m.edges = [
        Edge(src="C1", verb="enforces", dst="C2", why="gate", where="src/a.py:5"),   # security
        Edge(src="C1", verb="uses", dst="D1", why="query", where="src/a.py:7"),      # dep-usage
        Edge(src="C1", verb="persists", dst="E1", why="store", where="src/a.py:9"),  # ownership
        Edge(src="C1", verb="calls", dst="C2", why="helper", where="src/a.py:11"),   # backbone
    ]
    m.messaging = [MessagingRow(name="jobs", broker="D1", publishers=["C1"], consumers=["C2"],
                                source="src/q.py:1")]                               # messaging
    m.components[1].states = StateMachine(states=["new", "done"], source="src/b.py:20")  # lifecycle
    m.entry_points = [EntryPoint(kind="job", trigger="nightly sweep", component="C1",
                                 source="src/a.py:30", cadence="every 24h",
                                 cadence_source="src/a.py:31")]                     # cadence
    m.blocks = [Group(id="BLK1", name="Access", purpose="who may act")]
    m.rules = [BusinessRule(id="BR1", name="Owner-only cancellation", statement="Only an owner may cancel.", block="BLK1",
                            sites=[RuleSite(where="src/a.py:13",
                                            why="rejects a non-owner")]),          # rule
               # An ACCESS rule, so the order pin is not vacuous on the security tier. Without one,
               # every rule in this fixture was `access=False`, the tier under test emitted nothing
               # security-themed, and a change routing access sites to `security` in the WRONG place
               # (interleaving security · rule · security) still passed.
               BusinessRule(id="BR2", name="Sign-in required to read",
                            statement="Only a signed-in user may read a ticket.",
                            block="BLK1", access=True, risk="anyone could read any ticket",
                            sites=[RuleSite(where="src/auth/gate.py:22",
                                            why="rejects an anonymous caller")])]  # security
    return m

def make_precedence_map(bad: bool = True, create_verb: str = "persists") -> str:
    """Two use cases over one entity E1: UC1 READS the order, UC2 CREATES it (`create_verb`).
    `bad=True` orders the Happy Path read-then-create (the read-before-create shape); `bad=False`
    orders it create-then-read (clean). `create_verb` lets a test use a MUTATION verb (`writes`) to
    prove an update is NOT mistaken for a create. No `why:` lines, so the why-less check is a no-op."""
    gp = (
        """[
    {
      "id": "HP1",
      "uc": "UC1",
      "why": null
    },
    {
      "id": "HP2",
      "uc": "UC2",
      "why": null
    }
  ]""" if bad else
        """[
    {
      "id": "HP1",
      "uc": "UC2",
      "why": null
    },
    {
      "id": "HP2",
      "uc": "UC1",
      "why": null
    }
  ]"""
    )
    return f"""{{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [
    {{
      "id": "UC1",
      "name": "View order",
      "actors": [],
      "trigger": "opens", "outcome": "sees"
    }},
    {{
      "id": "UC2",
      "name": "Create order",
      "actors": [],
      "trigger": "submits", "outcome": "stored"
    }}
  ],
  "happy_path": {gp},
  "subsystems": [],
  "components": [
    {{
      "id": "C1",
      "name": "Viewer",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "E1",
      "source": null,
      "confidence": "",
      "extra": {{}}
    }},
    {{
      "id": "C2",
      "name": "Creator",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "E1",
      "source": null,
      "confidence": "",
      "extra": {{}}
    }}
  ],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {{
      "id": "E1",
      "name": "Order",
      "store": {{"notes": "orders"}},
      "meaning": "a customer order",
      "subdomain": null,
      "source": "order.py:1",
      "fields": [],
      "relations": []
    }}
  ],
  "non_entity_types": [],
  "flows": [
    {{
      "uc": "UC1",
      "title": "View order",
      "steps": [
        {{
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "views the order",
          "note": ""
        }}
      ]
    }},
    {{
      "uc": "UC2",
      "title": "Create order",
      "steps": [
        {{
          "n": 1,
          "src": "Adam",
          "dst": "C2",
          "phrase": "creates the order",
          "note": ""
        }}
      ]
    }}
  ],
  "edges": [
    {{
      "src": "C1",
      "verb": "reads",
      "dst": "E1",
      "why": "show it",
      "where": "f#L1"
    }},
    {{
      "src": "C2",
      "verb": "{create_verb}",
      "dst": "E1",
      "why": "store it",
      "where": "f#L2"
    }}
  ],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}}"""


def make_actor_mismatch_map(flow_actor: str = "Zoe") -> str:
    """UC1's declared actor is Andy (R1); its flow opens with `flow_actor`. A mismatch when flow_actor
    isn't Andy — the two layers disagree on who drives the use case (both sides are role ids now)."""
    roles = [("R1", "Andy")]
    open_id = "R1"
    if flow_actor != "Andy":
        roles.append(("R2", flow_actor))
        open_id = "R2"
    roles_json = ", ".join(
        f'{{"id": "{i}", "name": "{n}", "kind": "human", "wants": "", "drives": "UC1"}}'
        for i, n in roles)
    return f"""{{
  "format": "coyomap-map", "title": "", "goal": "",
  "commit": null, "committed": null, "built": null,
  "roles": [{roles_json}],
  "glossary": [],
  "use_cases": [{{"id": "UC1", "name": "View order", "actors": ["R1"], "trigger": "opens", "outcome": "sees"}}],
  "happy_path": [{{"id": "HP1", "uc": "UC1", "why": null}}],
  "subsystems": [],
  "components": [{{"id": "C1", "name": "Viewer", "subsystem": null, "purpose": "x", "depends_on": "", "source": null, "confidence": "", "extra": {{}}}}],
  "deps": [], "run_commands": [], "entry_points": [], "subdomains": [], "entities": [],
  "non_entity_types": [],
  "flows": [{{"uc": "UC1", "title": "View order", "steps": [
    {{"n": 1, "src": "{open_id}", "dst": "C1", "phrase": "views the order", "note": ""}}]}}],
  "edges": [], "deployment": [], "observability": [], "security": [], "config": [],
  "tests_note": "", "tests": [], "extras": []
}}"""


def make_shared_read_map() -> str:
    """Three use cases whose flows all read E1 (via a component that reads it); E1 is never written on
    the path. Exercises per-entity dedup: exactly ONE read-never-created advisory, not three."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "A",
      "actors": [],
      "trigger": "a", "outcome": "b"
    },
    {
      "id": "UC2",
      "name": "B",
      "actors": [],
      "trigger": "a", "outcome": "b"
    },
    {
      "id": "UC3",
      "name": "C",
      "actors": [],
      "trigger": "a", "outcome": "b"
    }
  ],
  "happy_path": [
    {
      "id": "HP1",
      "uc": "UC1",
      "why": null
    },
    {
      "id": "HP2",
      "uc": "UC2",
      "why": null
    },
    {
      "id": "HP3",
      "uc": "UC3",
      "why": null
    }
  ],
  "subsystems": [],
  "components": [
    {
      "id": "C1",
      "name": "A",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "E1",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "B",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "E1",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C3",
      "name": "C",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "E1",
      "source": null,
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "User",
      "store": {"notes": "users"},
      "meaning": "a user",
      "subdomain": null,
      "source": "u.py:1",
      "fields": [],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [
    {
      "uc": "UC1",
      "title": "A",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "reads the user",
          "note": ""
        }
      ]
    },
    {
      "uc": "UC2",
      "title": "B",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C2",
          "phrase": "reads the user",
          "note": ""
        }
      ]
    },
    {
      "uc": "UC3",
      "title": "C",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C3",
          "phrase": "reads the user",
          "note": ""
        }
      ]
    }
  ],
  "edges": [
    {
      "src": "C1",
      "verb": "reads",
      "dst": "E1",
      "why": "x",
      "where": "f#L1"
    },
    {
      "src": "C2",
      "verb": "reads",
      "dst": "E1",
      "why": "x",
      "where": "f#L2"
    },
    {
      "src": "C3",
      "verb": "reads",
      "dst": "E1",
      "why": "x",
      "where": "f#L3"
    }
  ],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_cc_routed_read_map() -> str:
    """The mcpolis bug shape, but the precondition read is routed through a `C→C` dependency: UC1's
    flow names only C1; C1 reads C3 (C→C); C3 reads E1 (C→E, but C3 is NOT in the flow). E1 is created
    at HP2. Audit CANNOT see the read (only C→E edges of flow-named components count) — a documented
    false negative that pins the limitation."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "Sign in",
      "actors": [],
      "trigger": "a", "outcome": "b"
    },
    {
      "id": "UC2",
      "name": "Create org",
      "actors": [],
      "trigger": "a", "outcome": "b"
    }
  ],
  "happy_path": [
    {
      "id": "HP1",
      "uc": "UC1",
      "why": null
    },
    {
      "id": "HP2",
      "uc": "UC2",
      "why": null
    }
  ],
  "subsystems": [],
  "components": [
    {
      "id": "C1",
      "name": "SignIn",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "C3",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "OrgSvc",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "E1",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C3",
      "name": "MemberStore",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "E1",
      "source": null,
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "Organization",
      "store": {"notes": "orgs"},
      "meaning": "tenant",
      "subdomain": null,
      "source": "o.py:1",
      "fields": [],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [
    {
      "uc": "UC1",
      "title": "Sign in",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "signs in",
          "note": ""
        }
      ]
    },
    {
      "uc": "UC2",
      "title": "Create org",
      "steps": [
        {
          "n": 1,
          "src": "Adam",
          "dst": "C2",
          "phrase": "creates org",
          "note": ""
        }
      ]
    }
  ],
  "edges": [
    {
      "src": "C1",
      "verb": "reads",
      "dst": "C3",
      "why": "resolve membership",
      "where": "f#L1"
    },
    {
      "src": "C3",
      "verb": "reads",
      "dst": "E1",
      "why": "membership→org",
      "where": "f#L2"
    },
    {
      "src": "C2",
      "verb": "persists",
      "dst": "E1",
      "why": "create org",
      "where": "f#L3"
    }
  ],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_backward_whyref_map() -> str:
    """HP1's `why:` cites HP2, which comes after it (a backward reference)."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "A",
      "actors": [],
      "trigger": "a", "outcome": "b"
    },
    {
      "id": "UC2",
      "name": "B",
      "actors": [],
      "trigger": "a", "outcome": "b"
    }
  ],
  "happy_path": [
    {
      "id": "HP1",
      "uc": "UC1",
      "why": "needs the thing from HP2"
    },
    {
      "id": "HP2",
      "uc": "UC2",
      "why": "follows HP1"
    }
  ],
  "subsystems": [],
  "components": [
    {
      "id": "C1",
      "name": "A",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "",
      "source": null,
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [],
  "non_entity_types": [],
  "flows": [
    {
      "uc": "UC1",
      "title": "A",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "does a",
          "note": ""
        }
      ]
    },
    {
      "uc": "UC2",
      "title": "B",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "does b",
          "note": ""
        }
      ]
    }
  ],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_read_never_created_map() -> str:
    """A single step reads E9, which no step ever creates (an external/config entity) — advisory."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "Load config",
      "actors": [],
      "trigger": "a", "outcome": "b"
    }
  ],
  "happy_path": [
    {
      "id": "HP1",
      "uc": "UC1",
      "why": null
    }
  ],
  "subsystems": [],
  "components": [
    {
      "id": "C1",
      "name": "Loader",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "E9",
      "source": null,
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E9",
      "name": "AppConfig",
      "store": {"notes": "config"},
      "meaning": "config",
      "subdomain": null,
      "source": "c.py:1",
      "fields": [],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [
    {
      "uc": "UC1",
      "title": "Load config",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "loads config",
          "note": ""
        }
      ]
    }
  ],
  "edges": [
    {
      "src": "C1",
      "verb": "reads",
      "dst": "E9",
      "why": "config",
      "where": "f#L1"
    }
  ],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_whyless_map() -> str:
    """HP1 has a `why:`, HP2 does not — a non-initial step missing its precondition (warning)."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "A",
      "actors": [],
      "trigger": "a", "outcome": "b"
    },
    {
      "id": "UC2",
      "name": "B",
      "actors": [],
      "trigger": "a", "outcome": "b"
    }
  ],
  "happy_path": [
    {
      "id": "HP1",
      "uc": "UC1",
      "why": "the start"
    },
    {
      "id": "HP2",
      "uc": "UC2",
      "why": null
    }
  ],
  "subsystems": [],
  "components": [
    {
      "id": "C1",
      "name": "A",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "",
      "source": null,
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [],
  "non_entity_types": [],
  "flows": [
    {
      "uc": "UC1",
      "title": "A",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "does a",
          "note": ""
        }
      ]
    },
    {
      "uc": "UC2",
      "title": "B",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "does b",
          "note": ""
        }
      ]
    }
  ],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_l2_map() -> str:
    """A Security & auth entry plus an `enforces` edge — the two L2-worklist sources."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "Call",
      "actors": [],
      "trigger": "a", "outcome": "b"
    }
  ],
  "happy_path": [],
  "subsystems": [],
  "components": [
    {
      "id": "C1",
      "name": "Gate",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "C2",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "Policy",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "",
      "source": null,
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [],
  "non_entity_types": [],
  "flows": [],
  "edges": [
    {
      "src": "C1",
      "verb": "enforces",
      "dst": "C2",
      "why": "policy",
      "where": "gate.py#L5"
    }
  ],
  "deployment": [],
  "observability": [],
  "security": [
    {
      "surface": "/api",
      "who": "admins",
      "source": "[require_admin](auth.py#L10)",
      "risk": "escalation"
    }
  ],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_l2_dep_map() -> str:
    """The whole broadened worklist on one map: an `enforces` edge (security, ranks first); a `C→D`
    `emits` into an EXPLICIT `datastore` and a `writes` into an UNTAGGED dep (both ground); a `uses`
    into an EXPLICIT `library` (skip — a false 'uses <lib>' is benign); a `C→E` `persists` (ownership);
    and a plain `C→C` `calls` (remaining). The `emits`-into-a-log-dep row is the audit→Elastic
    false-edge class."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "Call",
      "actors": [],
      "trigger": "a", "outcome": "b"
    }
  ],
  "happy_path": [],
  "subsystems": [],
  "components": [],
  "deps": [
    {
      "id": "D1",
      "name": "Elastic Cloud",
      "kind": "datastore",
      "type": "search",
      "used_for": "",
      "where_configured": "",
      "confidence": "",
      "deployment_linked": false,
      "extra": {
        "Purpose": "log storage"
      }
    },
    {
      "id": "D2",
      "name": "logging",
      "kind": "library",
      "type": "stdlib",
      "used_for": "",
      "where_configured": "",
      "confidence": "",
      "deployment_linked": false,
      "extra": {
        "Purpose": "app logs"
      }
    },
    {
      "id": "D3",
      "name": "Mystery",
      "kind": null,
      "type": "?",
      "used_for": "",
      "where_configured": "",
      "confidence": "",
      "deployment_linked": false,
      "extra": {
        "Purpose": "unknown"
      }
    }
  ],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [],
  "non_entity_types": [],
  "flows": [],
  "edges": [
    {
      "src": "C1",
      "verb": "enforces",
      "dst": "C2",
      "why": "policy",
      "where": "gate.py#L5"
    },
    {
      "src": "C1",
      "verb": "emits",
      "dst": "D1",
      "why": "ship logs",
      "where": "audit_repo.py#L8"
    },
    {
      "src": "C1",
      "verb": "uses",
      "dst": "D2",
      "why": "log lines",
      "where": "mod.py#L3"
    },
    {
      "src": "C1",
      "verb": "writes",
      "dst": "D3",
      "why": "dump",
      "where": "x.py#L1"
    },
    {
      "src": "C1",
      "verb": "persists",
      "dst": "E1",
      "why": "store",
      "where": "repo.py#L2"
    },
    {
      "src": "C1",
      "verb": "calls",
      "dst": "C3",
      "why": "rpc",
      "where": "client.py#L4"
    }
  ],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_duplicated_edge_map() -> str:
    """`make_l2_dep_map` with its C→D `emits` row DUPLICATED — the G4 dedupe shape (a repeated edge
    row must not become two skeptic tasks)."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "Call",
      "actors": [],
      "trigger": "a", "outcome": "b"
    }
  ],
  "happy_path": [],
  "subsystems": [],
  "components": [],
  "deps": [
    {
      "id": "D1",
      "name": "Elastic Cloud",
      "kind": "datastore",
      "type": "search",
      "used_for": "",
      "where_configured": "",
      "confidence": "",
      "deployment_linked": false,
      "extra": {
        "Purpose": "log storage"
      }
    },
    {
      "id": "D2",
      "name": "logging",
      "kind": "library",
      "type": "stdlib",
      "used_for": "",
      "where_configured": "",
      "confidence": "",
      "deployment_linked": false,
      "extra": {
        "Purpose": "app logs"
      }
    },
    {
      "id": "D3",
      "name": "Mystery",
      "kind": null,
      "type": "?",
      "used_for": "",
      "where_configured": "",
      "confidence": "",
      "deployment_linked": false,
      "extra": {
        "Purpose": "unknown"
      }
    }
  ],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [],
  "non_entity_types": [],
  "flows": [],
  "edges": [
    {
      "src": "C1",
      "verb": "enforces",
      "dst": "C2",
      "why": "policy",
      "where": "gate.py#L5"
    },
    {
      "src": "C1",
      "verb": "emits",
      "dst": "D1",
      "why": "ship logs",
      "where": "audit_repo.py#L8"
    },
    {
      "src": "C1",
      "verb": "uses",
      "dst": "D2",
      "why": "log lines",
      "where": "mod.py#L3"
    },
    {
      "src": "C1",
      "verb": "writes",
      "dst": "D3",
      "why": "dump",
      "where": "x.py#L1"
    },
    {
      "src": "C1",
      "verb": "persists",
      "dst": "E1",
      "why": "store",
      "where": "repo.py#L2"
    },
    {
      "src": "C1",
      "verb": "calls",
      "dst": "C3",
      "why": "rpc",
      "where": "client.py#L4"
    },
    {
      "src": "C1",
      "verb": "emits",
      "dst": "D1",
      "why": "ship logs",
      "where": "audit_repo.py#L8"
    }
  ],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_described_map() -> str:
    """Named components with file anchors, a named dep, and an entity card with SOURCE — so worklist
    claims can carry self-describing From/To detail (G1)."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [],
  "happy_path": [],
  "subsystems": [],
  "components": [
    {
      "id": "C1",
      "name": "AuthGate",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "",
      "source": "src/auth/gate.py:10",
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "PolicyStore",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "",
      "source": "src/policy.py:5",
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [
    {
      "id": "D1",
      "name": "Elastic",
      "kind": "datastore",
      "type": "search",
      "used_for": "",
      "where_configured": "",
      "confidence": "",
      "deployment_linked": false,
      "extra": {
        "Purpose": "logs"
      }
    }
  ],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "Order",
      "store": {"notes": "orders"},
      "meaning": "m",
      "subdomain": null,
      "source": "src/order.py:1",
      "fields": [
        {
          "name": "id",
          "type": "int",
          "markers": []
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [
    {
      "src": "C1",
      "verb": "enforces",
      "dst": "C2",
      "why": "policy",
      "where": "gate.py#L5"
    },
    {
      "src": "C1",
      "verb": "emits",
      "dst": "D1",
      "why": "logs",
      "where": "gate.py#L8"
    },
    {
      "src": "C2",
      "verb": "persists",
      "dst": "E1",
      "why": "store",
      "where": "policy.py#L9"
    }
  ],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def run_audit(json_text: str) -> tuple[int, str]:
    """Drive the audit CLI on the scenario map, written to a JSON model file."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(json_text)
        path = f.name
    r = subprocess.run([*AUDIT, path], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _checks(json_text: str) -> dict[str, str]:
    """{check_name: severity} for the L1 findings on a map (direct engine call, no subprocess)."""
    return {f.check: f.severity for f in audit_md(json_text)}


# --- L1: read-before-create (advisory — lossy attribution, must not block) -------
def test_read_before_create_is_advisory() -> None:
    """It surfaces the read-then-create ordering, but as an ADVISORY — the component-granularity
    attribution has real false positives (the audit review), so it must never block a build."""
    checks = _checks(make_precedence_map(bad=True))
    assert checks.get("read-before-create") == "ADVISORY", checks


def test_read_before_create_does_not_block_the_cli() -> None:
    code, out = run_audit(make_precedence_map(bad=True))
    assert code == 0, out
    assert "read-before-create" in out and "AUDIT PASSED" in out, out


def test_correct_order_has_no_finding() -> None:
    """Regression guard: a create-then-read Happy Path is clean — no false positive."""
    assert audit_md(make_precedence_map(bad=False)) == []


def test_write_modeled_create_surfaces_read_before_create() -> None:
    """Finding F1 (2nd review): `writes` is create-OR-update ambiguous and the method uses it for
    creates (the live mcpolis map models 'create the admin membership' as a `writes` edge). A read
    before a later `writes` must still surface the ordering as read-before-create (advisory) — the
    signal must NOT be lost as read-never-created just because the verb was `writes` not `persists`."""
    checks = _checks(make_precedence_map(bad=True, create_verb="writes"))
    assert checks.get("read-before-create") == "ADVISORY", checks
    assert "read-never-created" not in checks, checks


def test_read_never_created_is_deduped_per_entity() -> None:
    """Finding F4 (2nd review): a shared entity read by many steps yields ONE advisory, not one per
    step (which scales to dozens on a real map with common User/Org/Config entities)."""
    dupes = [f for f in audit_md(make_shared_read_map())
             if f.check == "read-never-created"]
    assert len(dupes) == 1, dupes


def test_clean_map_passes_the_cli() -> None:
    code, out = run_audit(make_precedence_map(bad=False))
    assert code == 0, out
    assert "AUDIT PASSED" in out, out


def test_audit_json_output_is_machine_readable() -> None:
    # --json emits {findings, worklist} — the Phase-4 skeptic-batching payload (no regex-parsing
    # the human report). Same exit-code semantics as the text mode.
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(make_precedence_map(bad=False))
        path = f.name
    r = subprocess.run([*AUDIT, path, "--json"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert set(payload) == {"findings", "worklist", "themes", "theme_counts"}
    # `themes` is the ordered (most-dangerous-first) vocabulary and `theme_counts` the per-theme
    # sizes: what a Phase-4 batcher groups on, so it never has to string-match the prose.
    assert payload["themes"][0] == "security"
    assert set(payload["theme_counts"]) <= set(payload["themes"])
    assert sum(payload["theme_counts"].values()) == len(payload["worklist"])
    assert all({"claim", "anchor", "detail", "why_risky"} <= set(w) for w in payload["worklist"])
    assert all({"check", "severity", "location", "message"} <= set(fi) for fi in payload["findings"])


def test_cc_routed_read_is_a_known_gap() -> None:
    """Finding 5: a precondition read routed through a `C→C` dependency is invisible to the C→E-only
    attribution — a documented false negative. Pin it so the limitation is explicit."""
    assert "read-before-create" not in _checks(make_cc_routed_read_map())


# --- L1: actor-attribution (advisory, guarded against the confirmed false positives) --
def test_actor_attribution_mismatch_is_advisory() -> None:
    assert _checks(make_actor_mismatch_map("Zoe")).get("actor-attribution") == "ADVISORY"


def test_actor_attribution_matches_when_actors_agree() -> None:
    """No finding when the flow opens with the use case's declared actor."""
    assert "actor-attribution" not in _checks(make_actor_mismatch_map("Andy"))


def test_backward_why_ref_is_still_blocking() -> None:
    """The why-ref checks have no false positives, so they stay blocking contradictions."""
    checks = _checks(make_backward_whyref_map())
    assert checks.get("backward-why-ref") == "CONTRADICTION", checks
    code, out = run_audit(make_backward_whyref_map())
    assert code == 1 and "AUDIT FAILED" in out, out


def test_read_never_created_is_advisory_not_blocking() -> None:
    checks = _checks(make_read_never_created_map())
    assert checks.get("read-never-created") == "ADVISORY", checks
    code, _ = run_audit(make_read_never_created_map())
    assert code == 0, "an advisory alone must not block"


def make_dependency_phrasing_model(step_phrase: str, edge_why: str) -> audit_model.ProjectModel:
    from coyomap.model import Edge, Flow, FlowStep, ProjectModel
    return ProjectModel(
        flows=[Flow(uc="UC1", title="t", steps=[FlowStep(n=1, src="C1", dst="C2", phrase=step_phrase)])],
        edges=[Edge(src="C1", verb="uses", dst="C2", why=edge_why)])


def test_dependency_phrasing_flags_step_and_edge() -> None:
    # "A needs B to …" reads as static wiring, not a runtime action — advisory on step text and edge Why.
    m = make_dependency_phrasing_model("the page needs the client to POST", "requires the store to save")
    findings = audit_model.check_dependency_phrasing(m)
    assert {f.location for f in findings} == {"UC1 flow step 1", "edge C1 → C2"}
    assert all(f.severity == "ADVISORY" for f in findings)


def test_dependency_phrasing_allows_actions() -> None:
    # A proper action phrasing raises nothing (and "used to" is intentionally not flagged).
    m = make_dependency_phrasing_model("POSTs the new upstream through the client", "used to save the order")
    assert audit_model.check_dependency_phrasing(m) == []


def test_hp_whyref_ignores_word_with_embedded_hp() -> None:
    # An HP<n> EMBEDDED in a longer word ("PHP7", "BHP2") must NOT read as a Happy-Path cross-reference.
    # The missing word boundary used to make the audit BLOCK (dangling/backward why-ref) on prose like this.
    # (A standalone "HP15" is still ref-shaped and correctly matches — that residual needs typed refs.)
    from coyomap.model import HappyStep, ProjectModel
    m = ProjectModel(happy_path=[
        HappyStep(id="HP1", uc="UC1"),
        HappyStep(id="HP2", uc="UC2", why="runs on PHP7 runtime (not BHP2)"),
    ])
    assert audit_model.happy_path_steps(m)[1].why_refs == []


def test_hp_whyref_reads_whole_token() -> None:
    from coyomap.model import HappyStep, ProjectModel
    m = ProjectModel(happy_path=[
        HappyStep(id="HP1", uc="UC1"),
        HappyStep(id="HP2", uc="UC2", why="needs the org from HP1"),
    ])
    assert audit_model.happy_path_steps(m)[1].why_refs == [1]


def test_slash_role_name_yields_no_actor_mismatch() -> None:
    # A role NAME containing "/" ("Host LLM / MCP client") is now referenced by its id, so the old
    # string-splitting can't misfire: the use case's actor id and the flow's opening actor id are the
    # same role, so no advisory. (Role ids make the "/"-split bug structurally impossible.)
    from coyomap.model import Flow, FlowStep, ProjectModel, Role, UseCase
    m = ProjectModel(
        roles=[Role(id="R1", name="Host LLM / MCP client", kind="service")],
        use_cases=[UseCase(id="UC1", name="x", actors=["R1"])],
        flows=[Flow(uc="UC1", title="t", steps=[FlowStep(n=1, src="R1", dst="C1", phrase="acts")])],
    )
    assert audit_model.check_actor_attribution(m) == []


def test_whyless_nonfirst_step_is_advisory_so_it_can_be_recorded() -> None:
    """ADVISORY, not WARNING. `_apply_audit_exceptions` suppresses ADVISORY only, so at WARNING this
    was the one substantive check no operator could answer — and a live build answered it by deleting
    a happy-path step and inventing two preconditions that are false against the code."""
    checks = _checks(make_whyless_map())
    assert checks.get("why-less-step") == "ADVISORY", checks


def test_whyless_step_names_the_line_that_records_it() -> None:
    """The old message offered "confirm it is a valid entry point" and named no mechanism for it."""
    found = [f for f in audit_md(make_whyless_map()) if f.check == "why-less-step"]
    assert found, "expected a why-less-step finding"
    assert "record 'why-less-step HP2:" in found[0].message, found[0].message
    assert audit_model.AUDIT_EXCEPTIONS_HEADING in found[0].message, found[0].message


def test_a_recorded_line_silences_a_whyless_step() -> None:
    """The whole point of ADVISORY: the escape the message names actually works. This is the
    regression the 2026-08-20 argus build paid for in map content."""
    m = load_model(make_whyless_map())
    before = [f for f in audit_model.audit_model(m) if f.check == "why-less-step"]
    assert before, "expected a why-less-step finding to record against"
    m.extras = [ExtraSection(heading=audit_model.AUDIT_EXCEPTIONS_HEADING,
                             body="why-less-step HP2: a real starting point of the walk.")]
    after = [f for f in audit_model.audit_model(m) if f.check == "why-less-step"]
    assert not after, [f.location for f in after]


# --- L2 worklist ----------------------------------------------------------------
def test_l2_worklist_lists_security_surfaces_and_enforces_edges() -> None:
    items = l2(make_l2_map())
    claims = " ".join(w.claim for w in items)
    assert "Auth surface" in claims, claims
    assert "enforces" in claims, claims
    anchors = [w.anchor for w in items]
    assert "auth.py#L10" in anchors and "gate.py#L5" in anchors, anchors


def test_l2_worklist_grounds_external_dep_edges() -> None:
    """A `C→D` edge into an external dep is grounded regardless of verb — the system-boundary
    data-flow claim (`emits` into a `datastore`), carrying its call site."""
    items = l2(make_l2_dep_map())
    claims = [w.claim for w in items]
    assert "C1 emits D1" in claims, claims
    assert "audit_repo.py#L8" in [w.anchor for w in items], items


def test_l2_worklist_skips_explicit_library_deps() -> None:
    """A `C→D` edge into a dep EXPLICITLY tagged `library` is skipped — a false 'uses <lib>' is benign
    and that bucket is the high-count one the Context view folds away."""
    claims = " ".join(w.claim for w in l2(make_l2_dep_map()))
    assert "D2" not in claims, claims


def test_l2_worklist_grounds_untagged_dep_by_default() -> None:
    """Fail-safe: ONLY an explicit fold-tag skips a dep. D3 has no `Kind` cell (inference would call it
    'library'), yet its incoming edge is still grounded — an unrecognised external system must not slip
    through, which is exactly how the audit→Elastic edge survived."""
    claims = [w.claim for w in l2(make_l2_dep_map())]
    assert "C1 writes D3" in claims, claims


def test_l2_worklist_ranks_security_before_dep_edges() -> None:
    """Security (`enforces`) claims outrank external-dep data-flow claims in the worklist order."""
    claims = [w.claim for w in l2(make_l2_dep_map())]
    assert claims.index("C1 enforces C2") < claims.index("C1 emits D1"), claims


def test_l2_worklist_grounds_entity_ownership_edges() -> None:
    """A `C→E` ownership edge is grounded — a wrong persists/writes/reads mis-wires the
    subsystem→subdomain bridge."""
    claims = [w.claim for w in l2(make_l2_dep_map())]
    assert "C1 persists E1" in claims, claims


def test_l2_worklist_grounds_remaining_component_edges() -> None:
    """The broadened worklist grounds the WHOLE backbone — a plain `C→C` `calls` edge is on it too."""
    claims = [w.claim for w in l2(make_l2_dep_map())]
    assert "C1 calls C3" in claims, claims


def test_l2_worklist_ranks_backbone_tiers() -> None:
    """Ranking holds across every tier: security < external-dep < entity-ownership < remaining."""
    claims = [w.claim for w in l2(make_l2_dep_map())]
    order = [claims.index(c) for c in
             ("C1 enforces C2", "C1 emits D1", "C1 persists E1", "C1 calls C3")]
    assert order == sorted(order), claims


def test_l2_worklist_dedupes_by_claim() -> None:
    """G4: a duplicated edge row yields exactly ONE worklist claim — the first occurrence, its anchor
    kept — so the skeptic fan-out count is deterministic (no downstream ad-hoc collapse)."""
    items = [w for w in l2(make_duplicated_edge_map())
             if w.claim == "C1 emits D1"]
    assert len(items) == 1, items
    assert items[0].anchor == "audit_repo.py#L8", items


def test_l2_worklist_claims_are_self_describing() -> None:
    """G1: each edge item's `detail` carries both endpoints' names + source files, so a fresh-context
    skeptic given only the item can locate the code with NO map file. The short claim (`C1 enforces
    C2`) stays the stable key."""
    items = {w.claim: w for w in l2(make_described_map())}
    d = items["C1 enforces C2"].detail
    assert d is not None, items
    assert "C1 = AuthGate" in d and "src/auth/gate.py:10" in d, d  # #L10 normalized to :10
    assert "C2 = PolicyStore" in d and "src/policy.py:5" in d, d  # #L5 normalized to :5
    e = items["C2 persists E1"].detail
    assert e is not None and "E1 = Order" in e and "src/order.py:1" in e, e  # #L1 normalized to :1
    dep = items["C1 emits D1"].detail
    assert dep is not None and "D1 = Elastic" in dep, dep


def test_l2_worklist_detail_reaches_the_cli_output() -> None:
    """The self-describing detail is printed (a `who:` line), so an agent driving the CLI — not the
    Python API — can hand a skeptic a claim it can resolve without the map."""
    code, out = run_audit(make_described_map())
    assert code == 0, out
    assert "who: From: C1 = AuthGate (src/auth/gate.py:10)" in out, out  # #L10 normalized to :10


def test_l2_worklist_risk_prose_collapsed_by_default() -> None:
    # A3: the near-identical per-claim `risk:` rationale is hidden by default (behind --verbose); the
    # anchor + `who:` endpoint detail a skeptic actually needs is always kept (see the detail test above).
    worklist = audit_model.l2_worklist_model(audit_model.load_model(make_l2_map()))
    assert worklist
    assert "risk:" not in audit_model._format([], worklist, verbose=False)
    assert "risk:" in audit_model._format([], worklist, verbose=True)


def test_touch_sets_see_subflow_content() -> None:
    # C1 (the writer) appears ONLY inside SF1's steps; the referencing flow's use case must still
    # be attributed the write — sub-flow content is never audit-invisible.
    m = ProjectModel(title="t")
    m.use_cases = [UseCase(id="UC1", name="Do")]
    m.components = [Component(id="C1", name="Writer"), Component(id="C2", name="Front")]
    m.entities = [Entity(id="E1", name="Thing")]
    m.edges = [Edge(src="C1", verb="persists", dst="E1", where="a.py:1")]
    m.subflows = [SubFlow(id="SF1", name="Persist",
                          steps=[FlowStep(n=1, src="C1", dst="E1", phrase="writes", where="a.py:1")])]
    m.flows = [Flow(uc="UC1", title="Do",
                    steps=[FlowStep(n=1, src="C2", dst="E1", subflow="SF1")])]
    writes, _reads = audit_model._touch_sets(m)
    assert "E1" in writes["UC1"]


# --- L2 structured-store tier (WS-A1) -------------------------------------------
def test_l2_worklist_carries_structured_store_claims() -> None:
    # "En is stored in Dn container 'x'" is a skeptic-refutable claim; anchored at the entity's
    # own source. A store with no dep (notes-only / transient) emits no item.
    m = ProjectModel(title="T", goal="g")
    m.deps = [Dep(id="D1", name="MongoDB", kind="datastore", type="document db")]
    m.entities = [
        Entity(id="E1", name="Guild", source="src/g.py:9",
               store=Store(dep="D1", container="guilds", mode="collection")),
        Entity(id="E2", name="Event", store=Store(notes="transient")),
    ]
    items = [it for it in audit_model.l2_worklist_model(m) if "is stored in" in it.claim]
    assert len(items) == 1
    assert "E1" in items[0].claim and "D1 container 'guilds'" in items[0].claim
    assert items[0].anchor == "src/g.py:9"


# --- L2 messaging tier (WS-A5) --------------------------------------------------
def test_l2_worklist_carries_messaging_claims() -> None:
    m = ProjectModel(title="T", goal="g")
    m.components = [Component(id="C1", name="Worker", purpose="works"),
                    Component(id="C2", name="Consumer", purpose="consumes")]
    m.deps = [Dep(id="D1", name="Redis", kind="messaging", type="queue broker")]
    m.messaging = [MessagingRow(name="JOB_QUEUE", kind="job-queue", broker="D1",
                                publishers=["C1"], consumers=["C2"],
                                source="src/queues.py:3")]
    items = [it for it in audit_model.l2_worklist_model(m) if "Channel" in it.claim]
    assert len(items) == 1
    assert "'JOB_QUEUE' on D1" in items[0].claim and "C1" in items[0].claim
    assert items[0].anchor == "src/queues.py:3"


# --- L2 state-machine tier (WS-A3) ----------------------------------------------
def test_l2_worklist_carries_state_machine_claims() -> None:
    m = ProjectModel(title="T", goal="g")
    m.components = [Component(id="C1", name="Manager", purpose="manages",
                              states=StateMachine(states=["idle", "live"],
                                                  transitions=[StateTransition(src="idle",
                                                                               dst="live")],
                                                  source="src/mgr.py:7"))]
    items = [it for it in audit_model.l2_worklist_model(m) if "states" in it.claim]
    assert len(items) == 1
    assert "C1" in items[0].claim and "idle" in items[0].claim
    assert items[0].anchor == "src/mgr.py:7"


# --- L2 cadence tier (WS-A2) ----------------------------------------------------
def test_l2_worklist_carries_anchored_cadence_claims() -> None:
    # a recorded schedule is a drift-prone claim about WHEN code runs — each cadence joins the
    # skeptic worklist, anchored at the DECLARING line (cadence_source), else the EP's own source.
    m = ProjectModel(title="T", goal="g")
    m.entry_points = [
        EntryPoint(kind="poller", trigger="poll twitch", source="src/p.py:1",
                   cadence="every 30s", cadence_source="src/beat.py:12"),
        EntryPoint(kind="http-route", trigger="GET /x", source="src/r.py:1"),  # no cadence → no item
    ]
    items = audit_model.l2_worklist_model(m)
    cadence_items = [it for it in items if "cadence" in it.claim]
    assert len(cadence_items) == 1
    assert "every 30s" in cadence_items[0].claim
    assert cadence_items[0].anchor == "src/beat.py:12"


# --- built-in runner ------------------------------------------------------------
def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())


# --------------------------------------------------------------------------------------
# `why:` may cite a USE CASE, not only a walk position (B4)
# --------------------------------------------------------------------------------------

def make_walk(*rows: tuple[str, str, str | None]) -> ProjectModel:
    """rows = (hp_id, uc_id, why) in walk order, with the matching use cases declared."""
    from coyomap.model import HappyStep, ProjectModel, UseCase
    ucs = sorted({uc for _, uc, _ in rows})
    return ProjectModel(
        use_cases=[UseCase(id=u, name=u, trigger="t", outcome="") for u in ucs],
        happy_path=[HappyStep(id=hp, uc=uc, why=why)
                    for hp, uc, why in rows],
    )


def test_uc_why_ref_pointing_backward_is_accepted():
    m = make_walk(("HP1", "UC1", None), ("HP2", "UC2", "needs the org from UC1"))
    assert [f for f in audit_model.check_why_refs(m) if f.severity == audit_model.CONTRADICTION] == []


def test_uc_why_ref_pointing_forward_is_advisory_not_blocking():
    # ADVISORY on purpose: a `UCn` in prose is not necessarily a prerequisite citation ("the same
    # guard UC3 uses"), so blocking here would fail a build on a sentence. `HPn` stays blocking —
    # a position citation can only ever mean one thing.
    m = make_walk(("HP1", "UC1", "needs UC2"), ("HP2", "UC2", None))
    found = audit_model.check_why_refs(m)
    assert [(f.check, f.severity) for f in found] == [("forward-uc-why-ref", audit_model.ADVISORY)]


def test_uc_why_ref_to_an_unknown_use_case_dangles():
    m = make_walk(("HP1", "UC1", None), ("HP2", "UC2", "needs UC99"))
    assert [f.check for f in audit_model.check_why_refs(m)] == ["dangling-why-ref"]


def test_uc_why_ref_to_an_offspine_use_case_is_advisory_not_blocking():
    from coyomap.model import UseCase
    m = make_walk(("HP1", "UC1", None), ("HP2", "UC2", "needs UC3"))
    m.use_cases.append(UseCase(id="UC3", name="off-spine", trigger="t", outcome=""))
    found = audit_model.check_why_refs(m)
    assert [(f.check, f.severity) for f in found] == [("offspine-why-ref", audit_model.ADVISORY)]


def test_positional_why_ref_silently_retargets_when_the_walk_is_renumbered():
    """`HPn` names a POSITION, so a walk edit can point an unchanged `why:` at a different step.

    A live build inserted a missing first act late in the run; the renumbering that followed left an
    `HP16` citing `HP19` — a forward reference, and a BLOCKING audit failure found after the final
    assemble. The narrower, always-silent half is shown here: after renumbering, the SAME `why:`
    text resolves to a different step than its author meant, and no check can notice because the
    reference is still well-formed and still backward. A `UCn` citation names the prerequisite
    itself, so neither failure mode can reach it.
    """
    from coyomap.model import HappyStep, ProjectModel, UseCase

    def walk(rows: list[tuple[str, str, str | None]]) -> ProjectModel:
        return ProjectModel(
            use_cases=[UseCase(id=u, name=u, trigger="t", outcome="")
                       for u in ("UC1", "UC2", "UC9")],
            happy_path=[HappyStep(id=hp, uc=uc, why=why) for hp, uc, why in rows])

    before = walk([("HP1", "UC1", None), ("HP2", "UC2", "needs the org from HP1")])
    after = walk([("HP1", "UC9", None),                       # inserted first act
                  ("HP2", "UC1", None),                       # was HP1
                  ("HP3", "UC2", "needs the org from HP1")])  # citation untouched
    # well-formed and backward in BOTH walks — the audit cannot see the breakage...
    assert audit_model.check_why_refs(before) == []
    assert audit_model.check_why_refs(after) == []
    # ...yet the cited step is no longer the one that creates the org.
    uc_cited = lambda m: {st.hp_id: st.uc for st in audit_model.happy_path_steps(m)}["HP1"]
    assert uc_cited(before) == "UC1" and uc_cited(after) == "UC9"

    # The same prerequisite cited as a use case resolves to the org step in both walks.
    by_uc = walk([("HP1", "UC9", None), ("HP2", "UC1", None),
                  ("HP3", "UC2", "needs the org from UC1")])
    assert audit_model.check_why_refs(by_uc) == []
    assert audit_model.happy_path_steps(by_uc)[2].why_uc_refs == ["UC1"]


def test_an_access_rule_site_is_a_security_claim_not_a_rule_claim():
    """The T7 fold made an auth surface a business rule with `access: true`, but the worklist kept
    theming every rule site `rule`. With `m.security` empty by design, that left the theme the audit
    orders FIRST permanently empty, so Phase 4's "most dangerous first" was ordering, not risk — on
    one real build the three-skeptic majority went to a batch holding 6 access claims of 40 while two
    40/40 batches got one skeptic each."""
    m = make_all_theme_model()
    items = audit_model.l2_worklist_model(m)
    by_theme = {}
    for it in items:
        by_theme.setdefault(it.theme, []).append(it)
    access_claims = [i.claim for i in by_theme.get("security", [])]
    assert any("signed-in user" in c for c in access_claims), \
        "an `access: true` rule site must be a SECURITY claim"
    assert all("signed-in user" not in i.claim for i in by_theme.get("rule", [])), \
        "an access rule site must not ALSO be emitted as a plain rule claim"
    assert any("owner may cancel" in i.claim for i in by_theme.get("rule", [])), \
        "a non-access rule site must still be a `rule` claim"


def test_access_and_rule_tiers_do_not_interleave():
    """Access sites are `security`-themed, so they must be extended BEFORE the `rule` tier. Appending
    them where they are built interleaves security · rule · security and silently breaks the
    declared-order == emission-order contract — on the two real maps that mistake produces 24 and 22
    alternating groups instead of one of each."""
    import itertools
    m = make_all_theme_model()
    themes = [i.theme for i in audit_model.l2_worklist_model(m)]
    groups = [t for t, _ in itertools.groupby(themes)]
    assert len(groups) == len(set(themes)), f"themes are not contiguous: {groups}"


def _roles_map(relations: list[dict]) -> str:
    return json.dumps({
        "format": "coyomap-map", "title": "T", "goal": "g",
        "roles": [{"id": "R1", "name": "Organization admin", "kind": "human",
                   "relations": relations},
                  {"id": "R2", "name": "Team member", "kind": "human"},
                  {"id": "R3", "name": "Headless agent", "kind": "software"}]})


def test_a_role_INCLUSION_is_challenged_as_a_security_claim():
    """It was the one element class asserting who-may-do-what while carrying no claim at all. The
    viewer draws it to a reader as a plain sentence — "may also do everything a Team member may do" —
    and `audit` held no theme for it, so a fabricated `R3 includes R1` (a headless agent may do
    everything an admin may do) left the worklist byte-identical. On the map that surfaced this the
    one authored inclusion was not true of the code: the admin flag gates only the dashboard routes,
    and the three functions deciding what a caller actually reaches never consult it."""
    items = [i for i in l2(_roles_map([{"kind": "includes", "role": "R2"}]))
             if "may do everything" in i.claim]
    assert len(items) == 1
    assert items[0].theme == "security"
    assert "Organization admin" in items[0].claim and "Team member" in items[0].claim
    assert "privilege claim" in items[0].why_risky


def test_an_UNANCHORED_inclusion_says_so_in_the_claim_rather_than_passing_quietly():
    """`RoleRelation` had nowhere to put a code anchor — `at` is pinned to a use-case id — so an
    inclusion was structurally ungroundable. The item now carries the grant line, or says there is
    none, in its `detail` — never in the CLAIM, because a claim's text is its identity and votes
    pair to it by that text. A rule-site claim does embed its anchor, and the same change that added
    this had to add `_rules_voted_under_any_anchor` to stop one anchor correction orphaning every
    vote a rule had. Anchoring an inclusion is the ordinary next step after a skeptic reads it."""
    unanchored = [i for i in l2(_roles_map([{"kind": "includes", "role": "R2"}]))
                  if "may do everything" in i.claim][0]
    assert "anchors this to NO line" in (unanchored.detail or "")
    assert unanchored.anchor is None
    anchored = [i for i in l2(_roles_map([{"kind": "includes", "role": "R2",
                                           "source": "src/policy.py:12"}]))
                if "may do everything" in i.claim][0]
    assert "granted at src/policy.py:12" in (anchored.detail or "")
    # the CLAIM is identical either way, on purpose: the anchor is not part of its identity, so
    # anchoring an inclusion a skeptic already voted on does not orphan that vote
    assert anchored.claim == unanchored.claim


def test_a_BECOMES_relation_mints_no_privilege_claim():
    """`becomes` is one person changing hat at a use case, not one role reaching another's
    permissions. Challenging it as a privilege claim would ask a skeptic to verify a sentence the
    map never made."""
    assert not [i for i in l2(_roles_map([{"kind": "becomes", "role": "R2", "at": "UC1"}]))
                if "may do everything" in i.claim]


def test_themes_are_closed_and_match_the_worklist_order():
    """The pin an earlier comment CLAIMED existed and did not.

    Two contracts, both previously false: (a) `_THEMES` is closed — a claim built with an unlisted
    theme must fail here, and a bogus theme on 5 of the 8 sites left the whole suite green; (b) the
    declared order IS the emission order, and `backbone` (194 of 398 claims on a live map, the lowest
    risk) was emitted 4th of 8 while sitting 8th in the list, so a consumer batching in worklist order
    spent its first batches on generic edges. Read from this module's own source, so a new claim kind
    joins the test automatically."""
    src = Path(str(audit_model.__file__)).read_text(encoding="utf-8")
    emitted = set(re.findall(r'theme="([a-z-]+)"', src))
    declared = set(audit_model._THEMES)
    assert emitted <= declared, f"theme(s) emitted but not declared in _THEMES: {emitted - declared}"
    assert len(audit_model._THEMES) == len(set(audit_model._THEMES))
    # (b) declared order == emission order, on a model exercising every tier
    m = make_all_theme_model()
    seen = [k for k, _ in itertools.groupby(w.theme for w in audit_model.l2_worklist_model(m))]
    assert seen == [t for t in audit_model._THEMES if t in seen], (
        f"worklist order {seen} contradicts _THEMES {audit_model._THEMES}")
    assert "backbone" in seen and seen[-1] == "backbone", "the largest, lowest-risk tier must be last"


def make_advisory_map() -> ProjectModel:
    """A map with one `read-never-created` advisory: HP1 reads E1, nothing writes it."""
    m = ProjectModel(title="T", goal="G")
    m.roles = [Role(id="R1", name="A", kind="human", wants="x", drives="UC1")]
    m.use_cases = [UseCase(id="UC1", name="Read it", actors=["R1"])]
    m.happy_path = [HappyStep(id="HP1", uc="UC1")]
    m.components = [Component(id="C1", name="A", purpose="p")]
    m.entities = [Entity(id="E1", name="Thing", source="a.py:1")]
    m.edges = [Edge(src="C1", verb="reads", dst="E1", why="w", where="a.py:2")]
    m.flows = [Flow(uc="UC1", title="Read it",
                    steps=[FlowStep(n=1, src="R1", dst="C1", phrase="asks"),
                           FlowStep(n=2, src="C1", dst="E1", phrase="reads the thing")])]
    return m


def test_an_audit_advisory_can_be_recorded_and_the_suppression_is_reported():
    """Until this existed, `audit` read NO extras heading at all — every advisory family was
    permanently unanswerable, so a finding an operator had judged acceptable re-fired forever and got
    waved through. A live map carried two `read-never-created` advisories through its whole build.

    The suppression is never silent: that is the `runs-in` lesson, where one recorded literal removed
    findings with no trace and a justification written about one thing swallowed unrelated ones."""
    m = make_advisory_map()
    before = audit_model.audit_model(m)
    assert any(f.check == "read-never-created" for f in before), before
    m.extras = [ExtraSection(heading=audit_model.AUDIT_EXCEPTIONS_HEADING,
                             body="read-never-created HP1: external config data, written off-path.")]
    after = audit_model.audit_model(m)
    assert not any(f.check == "read-never-created" for f in after)
    note = [f for f in after if f.check == "recorded-exceptions"]
    assert len(note) == 1 and "read-never-created HP1" in note[0].message


def test_one_audit_record_may_answer_several_ids_of_the_SAME_check():
    """Multi-key, with the check name still scoping every id on the line — the family escape the
    method forbids stays impossible, because the check is named once and applies to the whole list."""
    m = make_advisory_map()
    assert any(f.check == "read-never-created" for f in audit_model.audit_model(m))
    m.extras = [ExtraSection(heading=audit_model.AUDIT_EXCEPTIONS_HEADING,
                             body="read-never-created HP1, HP9: external config data, written off-path.")]
    assert not any(f.check == "read-never-created" for f in audit_model.audit_model(m))
    assert ("read-never-created", "HP9") in audit_model.audit_exceptions(m)


def test_an_audit_record_that_lost_its_check_name_silences_nothing():
    """`HP1: <why>` parses perfectly as an id list and scopes itself to NO check — so it must not
    silence one. It is reported instead (`validate`'s malformed-record advisory)."""
    m = make_advisory_map()
    m.extras = [ExtraSection(heading=audit_model.AUDIT_EXCEPTIONS_HEADING,
                             body="HP1, HP9: external config data, written off-path.")]
    assert audit_model.audit_exceptions(m) == set()
    assert any(f.check == "read-never-created" for f in audit_model.audit_model(m))


def test_a_recorded_line_silences_one_pair_never_a_family():
    """The `runs-in` over-suppression bug, designed out: two findings of the SAME check on different
    ids, one recorded, and the other must survive."""
    m = make_advisory_map()
    # A SECOND component, not just a second entity: reads are attributed at component granularity, so
    # two flows through one component both land on the first HP step and the ids would not differ.
    m.use_cases.append(UseCase(id="UC2", name="Read again", actors=["R1"]))
    m.happy_path.append(HappyStep(id="HP2", uc="UC2"))
    m.components.append(Component(id="C2", name="B", purpose="p"))
    m.entities.append(Entity(id="E2", name="Other", source="b.py:1"))
    m.edges.append(Edge(src="C2", verb="reads", dst="E2", why="w", where="b.py:2"))
    m.flows.append(Flow(uc="UC2", title="Read again",
                        steps=[FlowStep(n=1, src="R1", dst="C2", phrase="asks"),
                               FlowStep(n=2, src="C2", dst="E2", phrase="reads the other")]))
    assert len([f for f in audit_model.audit_model(m) if f.check == "read-never-created"]) == 2
    m.extras = [ExtraSection(heading=audit_model.AUDIT_EXCEPTIONS_HEADING,
                             body="read-never-created HP1: deliberate.")]
    left = [f for f in audit_model.audit_model(m) if f.check == "read-never-created"]
    assert len(left) == 1 and left[0].location.startswith("HP2"), left


def test_a_recorded_line_that_matches_nothing_is_reported():
    """A line that silences nothing reads as a decision the operator never had to make — a stale id, a
    fixed advisory, or a misspelled check name."""
    m = make_advisory_map()
    m.extras = [ExtraSection(heading=audit_model.AUDIT_EXCEPTIONS_HEADING,
                             body="read-never-created HP99: stale.")]
    notes = [f for f in audit_model.audit_model(m) if f.check == "recorded-exceptions"]
    assert any("matched no finding" in f.message and "HP99" in f.message for f in notes), notes


def test_a_contradiction_can_never_be_recorded_away():
    """CONTRADICTIONS are self-inconsistencies in the map, not judgement calls. Only ADVISORY findings
    are suppressible; a blocking finding with an escape hatch would be no gate at all."""
    m = make_advisory_map()
    m.happy_path[0].why = "after HP9"          # a dangling `why:` ref — CONTRADICTION
    blocking = [f for f in audit_model.audit_model(m) if f.severity == audit_model.CONTRADICTION]
    assert blocking, "expected a contradiction to record against"
    eid = blocking[0].location.split()[0].strip("()")
    m.extras = [ExtraSection(heading=audit_model.AUDIT_EXCEPTIONS_HEADING,
                             body=f"{blocking[0].check} {eid}: try to wave this through.")]
    still = [f for f in audit_model.audit_model(m) if f.severity == audit_model.CONTRADICTION]
    assert len(still) == len(blocking), "a contradiction was suppressed"


def test_a_line_with_no_why_is_not_a_recorded_decision():
    """An id alone is a dismissal, not a decision — the record must carry the reasoning."""
    m = make_advisory_map()
    m.extras = [ExtraSection(heading=audit_model.AUDIT_EXCEPTIONS_HEADING,
                             body="read-never-created HP1")]
    assert any(f.check == "read-never-created" for f in audit_model.audit_model(m))


def test_theme_batches_carry_the_anchor_the_hand_script_dropped():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _theme_batches_carry_the_anchor(td)


def _theme_batches_carry_the_anchor(tmp_path: str) -> None:
    """`--batches` exists because the hand-rolled batcher wrote `f.write(c['claim'])` and nothing
    else, so 360 of 408 dispatched claims reached the skeptics as a bare `C140 calls C78` — while
    the prompt promised them the claim would end with its `path:line` anchor in square brackets.
    The tool held an anchor for 400 of 404 items the whole time."""
    from coyomap.audit_model import BATCH_SCHEMA, l2_worklist_model, write_theme_batches

    own_map = Path(__file__).resolve().parents[1] / ".coyomap" / "project-map.json"
    m = load_model(own_map.read_text(encoding="utf-8"))
    worklist = l2_worklist_model(m)
    written = write_theme_batches(worklist, Path(tmp_path), cap=40)
    assert written, "coyomap's own map must produce at least one theme batch"
    total = anchored = 0
    for name, n in written:
        payload = json.loads((Path(tmp_path) / name).read_text(encoding="utf-8"))
        assert payload["schema"] == BATCH_SCHEMA, "the artifact is versioned from day one"
        assert len(payload["claims"]) == n <= 40
        for c in payload["claims"]:
            total += 1
            assert set(c) == {"claim", "anchor", "detail", "why_risky"}
            anchored += bool(c["anchor"])
    assert total == len(worklist), "every worklist claim lands in exactly one batch"
    assert anchored > total * 0.9, (
        f"only {anchored}/{total} dispatched claims carry an anchor — the defect this removes")


def test_a_renamed_use_case_that_left_its_flow_title_behind_is_flagged():
    """The other half of a late rename. A live map had two use cases repointed and renamed near the
    end of a build without re-tracing: `actor-attribution` fired on the actor half and was recorded,
    while the stale flow title went unnoticed by anything. Measured before writing: across three
    live maps name and title agree 39/40, 26/27 and everywhere else, and both exceptions were
    exactly this defect."""
    from coyomap.audit_model import check_flow_title
    m = ProjectModel(title="t", goal="g")
    m.use_cases = [UseCase(id="UC1", name="Rebuild the company knowledge graph", actors=["R1"])]
    m.flows = [Flow(uc="UC1", title="Build the knowledge graph from connected sources", steps=[])]
    assert [f for f in check_flow_title(m) if f.check == "flow-title"]
    m.flows[0].title = "Rebuild the company knowledge graph"
    assert not check_flow_title(m), "an agreeing title must not fire"


def test_a_flow_title_record_does_not_silence_a_different_check_on_the_same_use_case():
    """A record adjudicates one (check, id) PAIR, never a whole family. Reading every UC id under
    'Audit exceptions' — rather than the pairs — let an unrelated `actor-attribution` record
    silence this check on the same use case, which hid the very case it was written for."""
    from coyomap.audit_model import audit_exceptions
    m = ProjectModel(title="t", goal="g")
    m.extras = [ExtraSection(heading="Audit exceptions",
                             body="actor-attribution UC1: the scheduler opens it, deliberate.")]
    pairs = audit_exceptions(m)
    assert ("actor-attribution", "UC1") in pairs
    assert ("flow-title", "UC1") not in pairs


def make_prose_map() -> ProjectModel:
    """A map with exactly four reader-facing prose fields, one of them blank — the goal counts
    since 2026-09-11, when it joined the prose walk."""
    m = ProjectModel(title="Demo", goal="A demo.")
    m.components = [Component(id="C1", name="Checkout", purpose="Books an order."),
                    Component(id="C2", name="Ledger", purpose="")]
    m.rules = [BusinessRule(id="BR1", name="Owner-only", statement="Only the owner may cancel.",
                            risk="A stranger could cancel an order.")]
    return m


def test_prose_batches_carry_every_non_empty_field_and_the_rules() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        written = audit_model.write_prose_batches(make_prose_map(), out, cap=10)
        assert written == [("prose-1.json", 4)]     # C2's empty purpose is dropped
        payload = json.loads((out / "prose-1.json").read_text())
        assert payload["schema"] == audit_model.PROSE_BATCH_SCHEMA
        assert [f["where"] for f in payload["fields"]] == ["goal", "C1 purpose", "BR1 statement", "BR1 risk"]
        assert "UNKNOWN WORD" in payload["instructions"]


def test_a_second_run_at_a_smaller_cap_leaves_no_stale_prose_batch() -> None:
    """The claim batches paid for this once: two runs at different caps left the smaller run's extra
    files behind and a glob dispatched 23 duplicates while the tool printed the honest total."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        audit_model.write_prose_batches(make_prose_map(), out, cap=1)
        assert len(list(out.glob("prose-*.json"))) == 4
        audit_model.write_prose_batches(make_prose_map(), out, cap=10)
        assert [p.name for p in sorted(out.glob("prose-*.json"))] == ["prose-1.json"]


def test_json_findings_carry_where_as_well_as_location(capsys):
    """The text report prints `where: …`; `--json` emitted only `location`.

    A build read the human output, reached for `--json`, wrote `f.get("where", "")`, matched
    nothing, printed an empty result, and spent the next turn re-doing the same extraction by
    grepping the text report. Both keys ship now: renaming `location` alone would break anything
    already reading it.
    """
    from coyomap import audit_model
    m = make_precedence_map(bad=True)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "map.json"
        p.write_text(m, encoding="utf-8")
        audit_model.main([str(p), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"], "the fixture must produce at least one finding"
    for f in payload["findings"]:
        assert f["where"] == f["location"], f


def test_a_components_own_description_is_a_grounding_claim():
    """The map's prose was checked by nobody, and a false sentence shipped because of it.

    `validate` counts sentence length; `audit` compares records; the skeptics read structural
    claims. A live map shipped `C36`'s description saying a sign-in guard "refuses to be built at
    all when the service runs for many organizations", beside its own rule `BR21` saying that guard
    "cannot fire" — which was true: the one caller passes a flag that cancels the check. The rule
    had been challenged and corrected. The sentence next to it was in no worklist, no prose batch
    that anyone dispatched, and no gate.
    """
    from coyomap import audit_model
    from coyomap.model import load_model
    m = load_model(json.dumps({
        "format": "coyomap-map", "title": "T", "goal": "g", "commit": "abc1234",
        "components": [
            {"id": "C1", "name": "Sign-in providers", "purpose": "Signs a person in. The picker "
             "refuses to be built when the service runs for many organizations.",
             "source": "auth/provider.py:60", "files": ["auth/provider.py", "auth/stub.py"]},
            {"id": "C2", "name": "No prose", "purpose": "", "source": "b.py:1"},
        ],
    }))
    items = audit_model.l2_worklist_model(m)
    desc = [i for i in items if i.theme == "description"]
    assert len(desc) == 1, "a component with an empty purpose claims nothing"
    it = desc[0]
    assert it.claim == audit_model.description_claim(
        "C1", "Sign-in providers", m.components[0].purpose.strip())
    assert "refuses to be built" in it.claim, "the WHOLE description is the claim, not a summary"
    assert it.anchor == "auth/provider.py:60"
    assert it.drift_eligible is False, (
        "the anchor is the declaration site, not an acting line, so a skeptic's different line is "
        "not drift to correct")
    assert it.detail and "auth/stub.py" in it.detail, (
        "a fresh-context skeptic needs the files to check the description against")


def test_description_claims_sort_above_the_backbone_tier():
    """A backbone edge is anchor-checked by `validate` and nudged by `anchor-drift`. A description
    is read by no gate at all, so it is the more dangerous of the two to leave unchallenged."""
    from coyomap import audit_model
    themes = list(audit_model._THEMES)
    assert themes.index("description") < themes.index("backbone")


# --- a theme cut into batches ------------------------------------------------------
# `--cap 40` walked greedily, so a 42-claim theme became 40 + 2 — twice on one build. Two whole
# fresh-context skeptics were provisioned for two claims each while their siblings carried 40, and
# one of the 40s was the slowest agent in its barrier. The cap is a ceiling on how much context one
# skeptic holds; it was never a target to fill before starting the next one.

def test_a_theme_splits_into_even_batches_not_a_full_one_and_a_stub() -> None:
    from coyomap.audit_model import _even_chunks
    assert [len(c) for c in _even_chunks(list(range(42)), 40)] == [21, 21]
    assert [len(c) for c in _even_chunks(list(range(41)), 40)] == [21, 20]


def test_the_cap_is_still_a_ceiling() -> None:
    from coyomap.audit_model import _even_chunks
    for n in (1, 40, 41, 81, 120, 199):
        chunks = _even_chunks(list(range(n)), 40)
        assert all(len(c) <= 40 for c in chunks), (n, [len(c) for c in chunks])
        assert sum(len(c) for c in chunks) == n


def test_the_split_uses_the_fewest_batches_that_respect_the_cap() -> None:
    """Balancing must not buy evenness with an extra agent — each batch costs a whole context."""
    from coyomap.audit_model import _even_chunks
    assert len(_even_chunks(list(range(42)), 40)) == 2
    assert len(_even_chunks(list(range(98)), 40)) == 3
    assert len(_even_chunks(list(range(120)), 40)) == 3


def test_a_theme_under_the_cap_is_one_batch_and_order_is_kept() -> None:
    """The worklist is ranked most-dangerous-first within a theme; a shuffle spends the ranking."""
    from coyomap.audit_model import _even_chunks
    items = list(range(31))
    assert _even_chunks(items, 40) == [items]
    assert [x for c in _even_chunks(list(range(42)), 40) for x in c] == list(range(42))


# --- an interface claim is anchored where the SURFACE says, not where its dep is configured ---
# `validate` blocks a `theirs` surface until it carries evidence, so the author reads the call
# sites and answers. `audit` then sent the skeptic somewhere else: the owning dep's
# `where_configured` came first in the anchor order. On the 2026-08-29 mcpolis build the author had
# rejected one candidate line by name as too weak and the claim went out anchored two lines from
# it; 4 of 6 interface claims carried an anchor the surface does not name.

def _interface_model(*, evidence_file: str | None, source: str = "",
                     dep_configured: str = "src/settings.py:9"):
    from coyomap.model import Dep, EvidenceItem, Interface, ProjectModel
    m = ProjectModel(title="D", goal="g")
    m.deps = [Dep(id="D1", name="Their service", kind="service",
                  where_configured=dep_configured, interfaces=["I7"])]
    m.interfaces = [Interface(
        id="I7", name="Their service", what="What crosses.", side="theirs", facing="user",
        source=source,
        evidence=([EvidenceItem(file=evidence_file, why="forms the outgoing call")]
                  if evidence_file else []))]
    return m


def _interface_claims(m):
    from coyomap.audit_model import l2_worklist_model
    return [i for i in l2_worklist_model(m) if i.theme == "interface"]


def test_an_interface_claim_is_anchored_on_the_surfaces_own_evidence():
    items = _interface_claims(_interface_model(evidence_file="src/router.py:414"))
    assert len(items) == 1, items
    assert (items[0].anchor or "").startswith("src/router.py:414"), items[0].anchor


def test_the_dep_configuration_line_is_the_fallback_not_the_first_choice():
    """With no evidence and no source, the dep's line is better than nothing."""
    items = _interface_claims(_interface_model(evidence_file=None))
    assert len(items) == 1, items
    assert (items[0].anchor or "").startswith("src/settings.py:9"), items[0].anchor


def test_the_surfaces_own_source_still_beats_the_dep_line():
    items = _interface_claims(_interface_model(evidence_file=None, source="src/iface.py:3"))
    assert (items[0].anchor or "").startswith("src/iface.py:3"), items[0].anchor


def test_the_far_side_of_a_claim_is_the_dependency_standing_on_the_surface():
    """`party_ref` named the far side a SECOND time, and the dep already points up at the surface.
    The claim now reads the dependency's own name, so the two can no longer disagree."""
    items = _interface_claims(_interface_model(evidence_file="src/router.py:414"))
    assert "with Their service" in items[0].claim, items[0].claim


# --- the behavioural half, which no claim has ever covered -------------------------------------
# Measured on the 2026-08-29 mcpolis map: 0 of 702 worklist claims named a use case, a flow, a flow
# step or a sub-flow, because `m.flows` is read in `audit_model` only by L1 checks. That map carried
# 42 flow titles and 517 step phrases and no skeptic could be sent at any of them.

def _flow_model():
    from coyomap.model import Flow, FlowStep, ProjectModel
    m = ProjectModel(title="D", goal="g")
    m.flows = [Flow(uc="UC1", title="Sign in", steps=[
        FlowStep(n=1, src="R1", dst="C1", phrase="opens the sign-in page", where="src/ui.py:12"),
        FlowStep(n=2, src="C1", dst="C2", phrase="", where="src/a.py:3")])]
    return m


def test_the_behavioural_tier_is_off_by_default():
    """Every other caller of `l2_worklist_model` is pinned to the default surface — the grounding
    record's digest, its supersession arithmetic, and `profile`'s `l2_claims`."""
    from coyomap.audit_model import l2_worklist_model
    assert not [w for w in l2_worklist_model(_flow_model()) if w.theme == "behaviour"]


def test_with_behavioural_mints_a_claim_per_phrased_step():
    from coyomap.audit_model import l2_worklist_model
    items = [w for w in l2_worklist_model(_flow_model(), behavioural=True)
             if w.theme == "behaviour"]
    assert len(items) == 1, items          # the empty phrase is not a claim
    assert "opens the sign-in page" in items[0].claim, items[0].claim
    assert (items[0].anchor or "").startswith("src/ui.py:12"), items[0].anchor


def test_a_behaviour_claim_is_report_only():
    """Like `interface`: a phrase that misdescribes what happens is re-authored, not nudged onto
    another line. A writable theme with no writer is how `cadence` and `lifecycle` each spent months
    having their confirmed drifts re-typed by hand."""
    from coyomap.audit_model import l2_worklist_model
    items = [w for w in l2_worklist_model(_flow_model(), behavioural=True)
             if w.theme == "behaviour"]
    assert all(not w.drift_eligible for w in items), items


# --- the behavioural tier covers the WHOLE behavioural layer (retro 2026-09-02, mcpolis 1 and 2) --
# 1,049 map rows were outside the worklist by construction. The step loop existed; the use case's
# own sentence and what crosses a surface did not — and a refuted PRIVACY fact shipped in the
# second, because no skeptic could be sent at it.

def _behavioural_map():
    from coyomap.model import (Flow, FlowStep, Interface, ProjectModel, UseCase)
    m = ProjectModel(title="t", goal="g")
    m.use_cases = [UseCase(id="UC1", name="Rename a page",
                           trigger="owner submits a new name", outcome="the page is renamed")]
    # What crosses the dashboard is a STEP now, not a sentence on the surface. The step arm of the
    # worklist already challenges it, at its own call site.
    m.flows = [Flow(uc="UC1", title="Rename a page",
                    steps=[FlowStep(n=1, src="R1", dst="C1", phrase="submits the new name",
                                    where="web/pages.py:12"),
                           FlowStep(n=2, src="C1", dst="I1", direction="out",
                                    phrase="shows the page's title and its owner",
                                    where="web/app.py:44")])]
    m.interfaces = [Interface(id="I1", name="Dashboard", side="ours", source="web/app.py:1")]
    return m


def _claims(behavioural: bool) -> list[str]:
    from coyomap.audit_model import l2_worklist_model
    return [w.claim for w in l2_worklist_model(_behavioural_map(), behavioural=behavioural)]


def test_who_is_on_the_far_side_is_a_CLAIM_anchored_at_the_evidence_that_made_it():
    """A DERIVED fact used to reach no skeptic at all. Measured on the shipped mcpolis map before
    this existed: 1 of 1667 worklist claims mentioned a derived far side, while four surfaces each
    stated who stands at them with nothing challenging it.

    THE ANCHOR IS THE EVIDENCE, which is what made this look unfixable — a derived fact comes from a
    JOIN and has no line of its own, but each arm of the join does. Here the role is put at the
    surface by the DOOR its flow draws there (`R1 → I1`); the door carries no line of its own, so
    the anchor is the source of the way in that use case drives."""
    from coyomap.audit_model import l2_worklist_model
    from coyomap.model import EntryPoint, Flow, FlowStep, Interface, ProjectModel, Role, UseCase
    m = ProjectModel(title="t", goal="g")
    m.roles = [Role(id="R1", name="Admin", kind="human", audience="user", wants="in")]
    m.use_cases = [UseCase(id="UC1", name="Do it", actors=["R1"], entry_points=["EP1"],
                           trigger="asks", outcome="gets")]
    m.flows = [Flow(uc="UC1", title="Do it", steps=[FlowStep(n=1, src="R1", dst="I1", phrase="opens it")])]
    m.entry_points = [EntryPoint(id="EP1", kind="http-route", trigger="GET /x", activation="external",
                                 source="src/routes.py:12", component="C1")]
    m.interfaces = [Interface(id="I1", name="Console", what="Where an admin works.", side="ours",
                              facing="user", kind="screen", source="src/app.py:1", ways_in=["EP1"])]
    got = [w for w in l2_worklist_model(m, behavioural=False) if "far side" in w.claim]
    assert len(got) == 1, [w.claim for w in got]
    w = got[0]
    assert w.claim == "I1 'Console': R1 'Admin' is on its far side"
    assert w.anchor == "src/routes.py:12", w.anchor      # the way in, NOT the surface's own source
    assert "derived" in (w.detail or "") and "UC1" in (w.detail or "")
    # The anchor points at EVIDENCE, never at a line where "being on the far side" happens, so a
    # skeptic reading a different line is not drift to correct.
    assert w.drift_eligible is False


def test_a_far_side_with_nothing_to_anchor_is_reported_UNANCHORED_not_dropped():
    """mcpolis's "Visitor's mail program" is the live case: a `theirs` surface with no ways in and no
    dependency, so there is genuinely no line. Dropping it would put the claim back where it started,
    which is unchallenged."""
    from coyomap.audit_model import l2_worklist_model
    from coyomap.model import (EvidenceItem, Flow, FlowStep, Interface, ProjectModel, Role, UseCase)
    m = ProjectModel(title="t", goal="g")
    m.roles = [Role(id="R1", name="Reader", kind="human", audience="user", wants="the page")]
    m.use_cases = [UseCase(id="UC1", name="Open it", actors=["R1"], trigger="a", outcome="b")]
    m.flows = [Flow(uc="UC1", title="Open it",
                    steps=[FlowStep(n=1, src="C1", dst="I1", phrase="hands them over",
                                    where="src/v.py:3"),
                           FlowStep(n=2, src="I1", dst="R1", phrase="opens in their own app")])]
    m.interfaces = [Interface(id="I1", name="Their mail app", what="Their own program.",
                              side="theirs", facing="user", kind="handoff",
                              evidence=[EvidenceItem(file="src/v.py:3", why="the link")])]
    got = [w for w in l2_worklist_model(m, behavioural=False) if "far side" in w.claim]
    assert len(got) == 1, [w.claim for w in got]
    assert got[0].anchor is None, got[0].anchor
    assert "nothing anchorable" in (got[0].detail or "")


def test_a_far_side_claim_names_the_way_in_THAT_ROLE_drives_not_the_first_one():
    """Taking the surface's first way in put a dev-stub sign-in line under "who is on the far side of
    the Dashboard" — a real file, and not the one that puts that person there."""
    from coyomap.audit_model import l2_worklist_model
    from coyomap.model import EntryPoint, Flow, FlowStep, Interface, ProjectModel, Role, UseCase
    m = ProjectModel(title="t", goal="g")
    m.roles = [Role(id="R1", name="Admin", kind="human", audience="user", wants="in")]
    m.use_cases = [UseCase(id="UC1", name="Do it", actors=["R1"], entry_points=["EP2"],
                           trigger="a", outcome="b")]
    m.flows = [Flow(uc="UC1", title="Do it", steps=[FlowStep(n=1, src="R1", dst="I1", phrase="opens it")])]
    m.entry_points = [
        EntryPoint(id="EP1", kind="http-route", trigger="a stub", activation="external",
                   source="src/dev_stub.py:1", component="C1"),
        EntryPoint(id="EP2", kind="http-route", trigger="the real one", activation="external",
                   source="src/admin.py:44", component="C1")]
    m.interfaces = [Interface(id="I1", name="Console", what="Where an admin works.", side="ours",
                              facing="user", kind="screen", ways_in=["EP1", "EP2"])]
    got = [w for w in l2_worklist_model(m, behavioural=False) if "far side" in w.claim]
    assert got[0].anchor == "src/admin.py:44", got[0].anchor


def test_a_SUB_FLOW_step_phrase_is_challenged_too_and_exactly_once():
    """The hole an adversarial review found: the step loop read `f.steps`, so a phrase living inside
    a shared sub-use case reached readers — in the flow picture and at an interface — with no skeptic on it.
    195 phrases across the three live maps (coyomap 59, argus 65, mcpolis 71).

    ONCE, under its OWN container id, however many walks run it. Expanding instead would raise one
    claim per referencing walk and send several skeptics at one line."""
    from coyomap.audit_model import l2_worklist_model
    from coyomap.model import Flow, FlowStep, SubFlow
    m = _behavioural_map()
    m.subflows = [SubFlow(id="SF1", name="Check the token",
                          steps=[FlowStep(n=1, src="C1", dst="C2", phrase="checks the token",
                                          where="web/auth.py:9")])]
    # TWO walks run it, so the "exactly once" half of this test is not vacuous.
    for uc in ("UC1", "UC2"):
        m.flows.append(Flow(uc=uc, title="runs it",
                            steps=[FlowStep(n=9, src="C1", dst="C2", phrase="", subflow="SF1")]))
    claims = [w.claim for w in l2_worklist_model(m, behavioural=True)]
    got = [c for c in claims if "checks the token" in c]
    assert got == ["SF1 step 1: C1 → C2 — checks the token"], claims


def test_a_use_cases_own_sentence_becomes_a_claim():
    """The headline of the behavioural layer — the one line a reader takes away — had no claim."""
    assert any("UC1 Rename a page: owner submits a new name" in c for c in _claims(True))


def test_what_crosses_a_surface_becomes_a_claim():
    """It is a STEP claim now. `interfaces[].carries[]` was removed, and the sentence it held about
    the outside edge has to be a walk step, which the step arm already challenges at a call site.
    That is what closed the hole this file's header describes, rather than a second arm.

    THE WHOLE CLAIM IS ASSERTED, not a phrase substring. A bare-phrase assertion passed with the
    interface arm deleted entirely, under this very name — an adversarial review found it. The
    surface id and the DIRECTION are the parts a skeptic needs, and the direction is the one fact
    that justified removing the field, so it is the last thing that may go missing here."""
    assert any("UC1 step 2: C1 → I1 [out] — shows the page's title and its owner" == c
               for c in _claims(True)), _claims(True)


def test_neither_appears_at_the_default_tier():
    """The default surface is what three commands compare across builds; widening it silently
    would move numbers nobody changed."""
    text = " ".join(_claims(False))
    assert "UC1 Rename a page:" not in text, "the use case's own sentence is opt-in"
    assert "shows the page's title" not in text, "and so is every step phrase"


def test_a_behavioural_worklist_is_recognised_from_its_own_themes():
    """The live surface must be recomputed at the PINNED tier. Computing it at the default while
    the pin was behavioural reported every behaviour claim as superseded — 489 on one map — and
    made the digest describe a surface nobody pinned."""
    import json
    import tempfile
    from pathlib import Path
    from coyomap.audit_model import l2_worklist_model
    from coyomap.grounding import worklist_is_behavioural
    with tempfile.TemporaryDirectory() as td:
        for behavioural, expect in ((True, True), (False, False)):
            p = Path(td) / f"wl-{behavioural}.json"
            items = [{"claim": w.claim, "theme": w.theme}
                     for w in l2_worklist_model(_behavioural_map(), behavioural=behavioural)]
            p.write_text(json.dumps({"worklist": items}), encoding="utf-8")
            assert worklist_is_behavioural(p) is expect, (behavioural, items)


# --- the note must say what the code does ---------------------------------------------
# `audit --with-behavioural` printed the limit its own comment two lines above calls gone: "keep
# the record on the default worklist until the record path follows this flag". A build reads the
# message, never the comment. So the record path was fixed and every build kept obeying the old
# instruction — three consecutive retros filed "claims naming a use case, flow, HP step or
# capability: 0 of 935" as landed but ineffective, because the thing that landed was still telling
# operators not to use it. Measured on the mcpolis map the day this was found: with the record
# following the pinned tier, 0 of 854 behaviour claims are superseded; at the default tier, 854.


def test_the_behavioural_note_does_not_repeat_a_limit_that_is_gone(capsys):
    from coyomap import audit_model
    from coyomap.grounding import worklist_is_behavioural

    # A flow with a phrased step is all the behavioural tier needs: the claim it emits is that
    # phrase, checked at the step's own call site.
    m = ProjectModel(title="T", goal="G")
    m.components = [Component(id="C1", name="Door", purpose="lets a caller in", source="a.py:1")]
    m.use_cases = [UseCase(id="UC1", name="Come in")]
    m.flows = [Flow(uc="UC1", title="Come in",
                    steps=[FlowStep(n=1, src="C1", dst="C1", phrase="open the door",
                                    where="a.py:1")])]
    wide = audit_model.l2_worklist_model(m, behavioural=True)
    assert any(w.theme == "behaviour" for w in wide), (
        "the behavioural tier emits no behaviour claim, so the note under test is moot")

    # The record path recognises a pinned behavioural worklist, which is the fact the old note
    # denied. Pin one the way a build does and ask the function the record path consults.
    with tempfile.TemporaryDirectory() as td:
        pinned = Path(td) / "worklist.json"
        pinned.write_text(json.dumps({"worklist": [{"claim": w.claim, "theme": w.theme}
                                                   for w in wide]}), encoding="utf-8")
        assert worklist_is_behavioural(pinned) is True

    source = (Path(audit_model.__file__)).read_text(encoding="utf-8")
    at = source.index('print("NOTE: `--with-behavioural`')
    note = source[at:at + 1200]
    assert "widens the worklist AND the grounding record" in note, (
        "the note no longer says the record follows the flag")
    for stale in ("NOT the grounding record",
                  "keep the record on the default worklist",
                  "until the record path follows this flag"):
        assert stale not in note, (
            f"the note tells operators {stale!r}, which the record path stopped doing. That "
            f"sentence is why three builds left the behavioural half of their map unwarranted")


def test_small_themes_share_one_batch_and_security_never_does(tmp_path) -> None:
    """`--cap 40` bounded the top; nothing bounded the bottom, and two 1-claim themes each cost a
    whole fresh-context skeptic. Themes under the floor share `claims-small.json`; the security
    theme never shares, because its batches are three-voted by name."""
    import json as _json
    from coyomap.audit_model import SMALL_BATCH, WorkItem, write_theme_batches
    def item(theme: str, n: int) -> WorkItem:
        return WorkItem(claim=f"{theme} claim {n}", anchor="a.py:1", why_risky="r", theme=theme)
    wl = [item("security", 1), item("lifecycle", 1), item("messaging", 1)] + [item("backbone", i) for i in range(8)]
    written = dict(write_theme_batches(wl, tmp_path, cap=40, floor=5))
    assert written == {"claims-security.json": 1, "claims-backbone.json": 8, SMALL_BATCH: 2}, written
    small = _json.loads((tmp_path / SMALL_BATCH).read_text(encoding="utf-8"))
    assert small["theme"] == "mixed" and small["themes"] == ["messaging", "lifecycle"], "most-dangerous-first"
    assert {c["theme"] for c in small["claims"]} == {"lifecycle", "messaging"}
    assert dict(write_theme_batches(wl, tmp_path, cap=40)) == {
        "claims-security.json": 1, "claims-lifecycle.json": 1, "claims-messaging.json": 1,
        "claims-backbone.json": 8}, "no floor: one file per theme, as before"


def test_prose_batches_are_minted_only_on_request_and_stale_ones_go(capsys) -> None:
    """Four builds in a row minted the prose batches and dispatched none; one deleted 13 files it
    had just written. `--batches` writes none unless `--with-prose` is passed, and clears any left
    from an earlier run, so a stale batch cannot trip finalize's unread-prose check."""
    from coyomap import audit_model
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "map.json"
        p.write_text(make_precedence_map(bad=False), encoding="utf-8")
        out = Path(td) / "verify"
        out.mkdir()
        (out / "prose-9.json").write_text("{}", encoding="utf-8")
        assert audit_model.main([str(p), "--batches", str(out)]) == 0
        assert list(out.glob("prose-*.json")) == [], "no prose batch without --with-prose"
        assert list(out.glob("claims-*.json")), "the claims batches are still written"
        assert audit_model.main([str(p), "--batches", str(out), "--with-prose"]) == 0
        assert list(out.glob("prose-*.json")), "asked for, so written"
    capsys.readouterr()


def test_the_shared_small_batch_is_cut_at_the_cap_and_a_floor_above_the_cap_is_refused(tmp_path) -> None:
    """Each merged theme is under the floor; their sum is not. Eleven 4-claim themes are 44 claims,
    over the default cap of 40, so the shared batch is chunked like any theme."""
    from coyomap.audit_model import WorkItem, write_theme_batches
    from coyomap.audit_model import _THEMES
    themes = [t for t in _THEMES if t != "security"]      # the 11 mergeable themes, real names
    assert len(themes) == 11, themes
    wl = [WorkItem(claim=f"{t} {i}", anchor="a.py:1", why_risky="r", theme=t)
          for t in themes for i in range(4)]
    written = write_theme_batches(wl, tmp_path, cap=10, floor=5)
    names = [n for n, _ in written]
    assert all(n.startswith("claims-small-") for n in names) and len(names) == 5, written
    assert sum(k for _, k in written) == 44 and max(k for _, k in written) <= 10, written
    import pytest as _pytest
    with _pytest.raises(ValueError, match="above --cap"):
        write_theme_batches(wl, tmp_path, cap=10, floor=20)
