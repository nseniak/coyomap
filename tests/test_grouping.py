#!/usr/bin/env python3
"""Tests for the grouping/rendering pipeline: the graph builder (build_graph), the view
derivation (views.model_to_graph), the Mermaid card generators + view bundle (gen_viewer), and the
served generic frontend (viewer.html / viewer.js).

Stdlib-only — no pytest required. Run either way (needs an editable install: `make deps`):
    python3 tests/test_grouping.py        # built-in runner (prints pass/fail)
    pytest tests/test_grouping.py         # if pytest is installed
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path
from typing import cast

from coyomap import grammar
from coyomap.model import (Dep, EntityRelation, ProjectModel, Role, UseCase, all_elements,
                           load_model)
from coyomap.model import TestRow as GapRow  # aliased: a bare `TestRow` trips pytest class collection
from coyomap.viewer import build_graph, gen_viewer
from coyomap.views import _relation_item, and_list, model_to_graph

VIEWER_DIR = Path(gen_viewer.__file__).resolve().parent  # the served shell + viewer.js/css live here


def bundle_of(json_text: str) -> gen_viewer.ViewBundle:
    """The view bundle a served map exposes at /api/view — the data the generic frontend fetches. The
    render→HTML file is gone; the diagrams/flows/config now live here (build_view_bundle), so the tests
    that used to grep the baked HTML assert on this bundle (and on the static shell for page chrome)."""
    return gen_viewer.build_view_bundle(parse_map(json_text), VIEWER_DIR)


def make_grouped_map(layout: str = "proper") -> str:
    """A two-subsystem grouped map. layout='proper' has an ID + Component(name) column;
    layout='agent' drops them (id in col 0, Subsystem at index 1) — the regression case."""
    if layout == "agent":
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
  "subsystems": [
    {
      "id": "S1",
      "name": "Edge",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    },
    {
      "id": "S2",
      "name": "Core",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    }
  ],
  "components": [
    {
      "id": "C1",
      "name": "C1",
      "subsystem": "S1",
      "purpose": "x",
      "depends_on": "C2",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "C2",
      "subsystem": "S2",
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
      "verb": "uses",
      "dst": "C2",
      "why": "reach engine",
      "where": "f"
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
  "subsystems": [
    {
      "id": "S1",
      "name": "Edge",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    },
    {
      "id": "S2",
      "name": "Core",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    }
  ],
  "components": [
    {
      "id": "C1",
      "name": "Front door",
      "subsystem": "S1",
      "purpose": "x",
      "depends_on": "C2",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "Engine",
      "subsystem": "S2",
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
      "verb": "uses",
      "dst": "C2",
      "why": "reach engine",
      "where": "f"
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


def make_card_map() -> str:
    """A grouped map exercising the card generators: S1 has two components wired internally
    (C1->C3), both cross into S2's component C2, and C2 touches a dep D1. Lets the tests assert
    a subsystem card keeps internal wiring + deps, while an edge card keeps ONLY the cross edges."""
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
  "subsystems": [
    {
      "id": "S1",
      "name": "Edge",
      "purpose": "front",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    },
    {
      "id": "S2",
      "name": "Core",
      "purpose": "brains",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    }
  ],
  "components": [
    {
      "id": "C1",
      "name": "Front door",
      "subsystem": "S1",
      "purpose": "x",
      "depends_on": "C2",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C3",
      "name": "Router",
      "subsystem": "S1",
      "purpose": "x",
      "depends_on": "C2",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "Engine",
      "subsystem": "S2",
      "purpose": "x",
      "depends_on": "D1",
      "source": null,
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [
    {
      "id": "D1",
      "name": "Cache",
      "kind": null,
      "type": "",
      "used_for": "",
      "where_configured": "",
      "confidence": "",
      "deployment_linked": false,
      "extra": {
        "Anchor": "f",
        "Purpose": "speed"
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
      "verb": "calls",
      "dst": "C2",
      "why": "reach engine",
      "where": "f"
    },
    {
      "src": "C1",
      "verb": "routes",
      "dst": "C3",
      "why": "dispatch",
      "where": "f"
    },
    {
      "src": "C3",
      "verb": "calls",
      "dst": "C2",
      "why": "reach engine",
      "where": "f"
    },
    {
      "src": "C2",
      "verb": "reads",
      "dst": "D1",
      "why": "cache",
      "where": "f"
    }
  ],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": [
    {
      "heading": "Dependencies",
      "body": ""
    }
  ]
}"""


def make_nested_subsystem_map() -> str:
    """S1 (top) nests S2; S3 is a top-level sibling. C1 is a DIRECT member of S1, C2 a grandchild
    (member of S2), C3 lives in S3. Edges: C1->C2 (member -> child-subsystem box), C2->C3 (grandchild
    -> sibling subsystem). Exercises level-relative drill: S1's card must show S2 as a drillable box
    (not S2's components flattened in), and the C2->C3 crossing must resolve to the S3 box at S1's
    altitude."""
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
  "subsystems": [
    {
      "id": "S1",
      "name": "Platform",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    },
    {
      "id": "S2",
      "name": "Inner",
      "purpose": "x",
      "parent": "S1",
      "source": "a/",
      "confidence": "V"
    },
    {
      "id": "S3",
      "name": "Other",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    }
  ],
  "components": [
    {
      "id": "C1",
      "name": "Gate",
      "subsystem": "S1",
      "purpose": "x",
      "depends_on": "C2",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "Worker",
      "subsystem": "S2",
      "purpose": "x",
      "depends_on": "C3",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C3",
      "name": "Sink",
      "subsystem": "S3",
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
      "verb": "calls",
      "dst": "C2",
      "why": "dispatch",
      "where": "f"
    },
    {
      "src": "C2",
      "verb": "calls",
      "dst": "C3",
      "why": "forward",
      "where": "f"
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


def make_ungrouped_map() -> str:
    """No S table; prose mentions AWS S3/S4 (must not be treated as references)."""
    return """{
  "format": "coyomap-map",
  "title": "X",
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
      "name": "App",
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
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_fenced_node_map() -> str:
    """A real C1 plus a fenced example mentioning C9 — the parser must not graph C9."""
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
  "subsystems": [
    {
      "id": "S1",
      "name": "A",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    }
  ],
  "components": [
    {
      "id": "C1",
      "name": "Real",
      "subsystem": "S1",
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
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": [
    {
      "heading": "S",
      "body": ""
    },
    {
      "heading": "Example",
      "body": ""
    }
  ]
}"""


_CARDS_EMBEDDED_ENTITY_TYPE = (
    "**E1 — Order** *(s)*\nMEANING: m\nFIELDS: mode:E2 · id:int\nSOURCE: [f](f#L1)\n\n"
    "**E2 — AuthMode**\nMEANING: m\nFIELDS: x:int\nSOURCE: [f](f#L2)\n"
)


_CARDS_COLLECTION_MARKER = (
    "**E1 — Snapshot** *(s)*\nMEANING: m\n"
    "FIELDS: refresh_tokens:E2[] · expires_at:int ? · id:int PK\n"
    "RELATIONS: contains 1→* E2 StoredRefreshToken\nSOURCE: [f](f#L1)\n\n"
    "**E2 — StoredRefreshToken**\nMEANING: m\nFIELDS: token:string\nSOURCE: [f](f#L2)\n"
)


_CARDS_RELATION_LABELS = (
    "**E1 — Org** *(s)*\nMEANING: m\nFIELDS: id:string PK · subscription:E3\n"
    "RELATIONS: has 1→* E2 Membership · contains 1→1 E3 Subscription\nSOURCE: [f](f#L1)\n\n"
    "**E2 — Membership**\nMEANING: m\nFIELDS: org_id:string FK→E1 · email:string\nSOURCE: [f](f#L2)\n\n"
    "**E3 — Subscription**\nMEANING: m\nFIELDS: tier:string\nSOURCE: [f](f#L3)\n"
)


_CARDS_UNGROUNDED_VERB = (
    "**E1 — A** *(s)*\nMEANING: m\nFIELDS: id:int\n"
    "RELATIONS: authorizes *→1 E2\nSOURCE: [f](f#L1)\n\n"
    "**E2 — B**\nMEANING: m\nFIELDS: x:int\nSOURCE: [f](f#L2)\n"
)


_CARDS_FORWARD_FK = (
    "**E1 — Membership** *(s)*\nMEANING: m\nFIELDS: email:string · role:string FK→E2\n"
    "RELATIONS: assignedRole *→1 E2 RoleDefinition\nSOURCE: [f](f#L1)\n\n"
    "**E2 — RoleDefinition**\nMEANING: m\nFIELDS: name:string\nSOURCE: [f](f#L2)\n"
)


_CARDS_BACKING_HOW = (
    "**E1 — Org** *(s)*\nMEANING: m\nFIELDS: id:string PK\n"
    "RELATIONS: contains 1→* E2 Membership · tracks *→1 E3 Token {keyed by (org, upstream)}\n"
    "SOURCE: [f](f#L1)\n\n"
    "**E2 — Membership**\nMEANING: m\nFIELDS: org_id:string FK→E1\nSOURCE: [f](f#L2)\n\n"
    "**E3 — Token**\nMEANING: m\nFIELDS: value:string\nSOURCE: [f](f#L3)\n"
)


def make_domain_map(cards: str | None = None) -> str:
    """A minimal valid map whose T5 is domain CARDS. `cards` overrides the default two-entity body
    (Order contains LineItem; LineItem uses a bullet-list FIELDS)."""
    if cards is None:
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
      "name": "Search",
      "actors": [],
      "trigger_outcome": "types -> list"
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "Order",
      "store": {"notes": "orders collection"},
      "meaning": "a purchase",
      "subdomain": null,
      "source": "order.py:12",
      "fields": [
        {
          "name": "id",
          "type": "ObjectId",
          "markers": [
            "PK"
          ]
        },
        {
          "name": "status",
          "type": "string",
          "markers": []
        }
      ],
      "relations": [
        {
          "verb": "contains",
          "target": "E2",
          "src_card": "1",
          "dst_card": "*",
          "display": "LineItem",
          "how": null
        }
      ]
    },
    {
      "id": "E2",
      "name": "LineItem",
      "store": null,
      "meaning": "a line",
      "subdomain": null,
      "source": "order.py:58",
      "fields": [
        {
          "name": "sku",
          "type": "string",
          "markers": []
        },
        {
          "name": "qty",
          "type": "int",
          "markers": []
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
    if cards == _CARDS_EMBEDDED_ENTITY_TYPE:
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
      "name": "Search",
      "actors": [],
      "trigger_outcome": "types -> list"
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "Order",
      "store": {"notes": "s"},
      "meaning": "m",
      "subdomain": null,
      "source": "f:1",
      "fields": [
        {
          "name": "mode",
          "type": "E2",
          "markers": []
        },
        {
          "name": "id",
          "type": "int",
          "markers": []
        }
      ],
      "relations": []
    },
    {
      "id": "E2",
      "name": "AuthMode",
      "store": null,
      "meaning": "m",
      "subdomain": null,
      "source": "f:2",
      "fields": [
        {
          "name": "x",
          "type": "int",
          "markers": []
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
    if cards == _CARDS_COLLECTION_MARKER:
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
      "name": "Search",
      "actors": [],
      "trigger_outcome": "types -> list"
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "Snapshot",
      "store": {"notes": "s"},
      "meaning": "m",
      "subdomain": null,
      "source": "f:1",
      "fields": [
        {
          "name": "refresh_tokens",
          "type": "E2",
          "markers": [
            "[]"
          ]
        },
        {
          "name": "expires_at",
          "type": "int",
          "markers": [
            "?"
          ]
        },
        {
          "name": "id",
          "type": "int",
          "markers": [
            "PK"
          ]
        }
      ],
      "relations": [
        {
          "verb": "contains",
          "target": "E2",
          "src_card": "1",
          "dst_card": "*",
          "display": "StoredRefreshToken",
          "how": null
        }
      ]
    },
    {
      "id": "E2",
      "name": "StoredRefreshToken",
      "store": null,
      "meaning": "m",
      "subdomain": null,
      "source": "f:2",
      "fields": [
        {
          "name": "token",
          "type": "string",
          "markers": []
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
    if cards == _CARDS_RELATION_LABELS:
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
      "name": "Search",
      "actors": [],
      "trigger_outcome": "types -> list"
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "Org",
      "store": {"notes": "s"},
      "meaning": "m",
      "subdomain": null,
      "source": "f:1",
      "fields": [
        {
          "name": "id",
          "type": "string",
          "markers": [
            "PK"
          ]
        },
        {
          "name": "subscription",
          "type": "E3",
          "markers": []
        }
      ],
      "relations": [
        {
          "verb": "has",
          "target": "E2",
          "src_card": "1",
          "dst_card": "*",
          "display": "Membership",
          "how": null
        },
        {
          "verb": "contains",
          "target": "E3",
          "src_card": "1",
          "dst_card": "1",
          "display": "Subscription",
          "how": null
        }
      ]
    },
    {
      "id": "E2",
      "name": "Membership",
      "store": null,
      "meaning": "m",
      "subdomain": null,
      "source": "f:2",
      "fields": [
        {
          "name": "org_id",
          "type": "string",
          "markers": [
            "FK→E1"
          ]
        },
        {
          "name": "email",
          "type": "string",
          "markers": []
        }
      ],
      "relations": []
    },
    {
      "id": "E3",
      "name": "Subscription",
      "store": null,
      "meaning": "m",
      "subdomain": null,
      "source": "f:3",
      "fields": [
        {
          "name": "tier",
          "type": "string",
          "markers": []
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
    if cards == _CARDS_UNGROUNDED_VERB:
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
      "name": "Search",
      "actors": [],
      "trigger_outcome": "types -> list"
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "A",
      "store": {"notes": "s"},
      "meaning": "m",
      "subdomain": null,
      "source": "f:1",
      "fields": [
        {
          "name": "id",
          "type": "int",
          "markers": []
        }
      ],
      "relations": [
        {
          "verb": "authorizes",
          "target": "E2",
          "src_card": "*",
          "dst_card": "1",
          "display": "",
          "how": null
        }
      ]
    },
    {
      "id": "E2",
      "name": "B",
      "store": null,
      "meaning": "m",
      "subdomain": null,
      "source": "f:2",
      "fields": [
        {
          "name": "x",
          "type": "int",
          "markers": []
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
    if cards == _CARDS_FORWARD_FK:
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
      "name": "Search",
      "actors": [],
      "trigger_outcome": "types -> list"
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "Membership",
      "store": {"notes": "s"},
      "meaning": "m",
      "subdomain": null,
      "source": "f:1",
      "fields": [
        {
          "name": "email",
          "type": "string",
          "markers": []
        },
        {
          "name": "role",
          "type": "string",
          "markers": [
            "FK→E2"
          ]
        }
      ],
      "relations": [
        {
          "verb": "assignedRole",
          "target": "E2",
          "src_card": "*",
          "dst_card": "1",
          "display": "RoleDefinition",
          "how": null
        }
      ]
    },
    {
      "id": "E2",
      "name": "RoleDefinition",
      "store": null,
      "meaning": "m",
      "subdomain": null,
      "source": "f:2",
      "fields": [
        {
          "name": "name",
          "type": "string",
          "markers": []
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
    if cards == _CARDS_BACKING_HOW:
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
      "name": "Search",
      "actors": [],
      "trigger_outcome": "types -> list"
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "Org",
      "store": {"notes": "s"},
      "meaning": "m",
      "subdomain": null,
      "source": "f:1",
      "fields": [
        {
          "name": "id",
          "type": "string",
          "markers": [
            "PK"
          ]
        }
      ],
      "relations": [
        {
          "verb": "contains",
          "target": "E2",
          "src_card": "1",
          "dst_card": "*",
          "display": "Membership",
          "how": null
        },
        {
          "verb": "tracks",
          "target": "E3",
          "src_card": "*",
          "dst_card": "1",
          "display": "Token",
          "how": "keyed by (org, upstream)"
        }
      ]
    },
    {
      "id": "E2",
      "name": "Membership",
      "store": null,
      "meaning": "m",
      "subdomain": null,
      "source": "f:2",
      "fields": [
        {
          "name": "org_id",
          "type": "string",
          "markers": [
            "FK→E1"
          ]
        }
      ],
      "relations": []
    },
    {
      "id": "E3",
      "name": "Token",
      "store": null,
      "meaning": "m",
      "subdomain": null,
      "source": "f:3",
      "fields": [
        {
          "name": "value",
          "type": "string",
          "markers": []
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
    raise ValueError("make_domain_map: unrecognised `cards` fixture")


def make_gp_map() -> str:
    """A two-step Happy Path (HP1=UC1 actor Andy, HP2=UC2 actor Adam) + the two use-case T6 flows.
    Exercises the GP overview sequence (actors from the UCs) and each use case's flow sequence."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [
    {"id": "R1", "name": "Andy", "kind": "", "wants": "", "drives": "UC1"},
    {"id": "R2", "name": "Adam", "kind": "", "wants": "", "drives": "UC2"}
  ],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "Submit",
      "actors": ["R1"],
      "trigger_outcome": "submits -> stored"
    },
    {
      "id": "UC2",
      "name": "Approve",
      "actors": ["R2"],
      "trigger_outcome": "approves -> done"
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
      "why": "needs the order from HP1"
    }
  ],
  "subsystems": [],
  "components": [
    {
      "id": "C1",
      "name": "Gateway",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "C2",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "Engine",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "D1",
      "source": null,
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [
    {
      "id": "D1",
      "name": "Cache",
      "kind": null,
      "type": "store",
      "used_for": "speed",
      "where_configured": "env",
      "confidence": "V",
      "deployment_linked": false,
      "extra": {}
    }
  ],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [],
  "non_entity_types": [],
  "flows": [
    {
      "uc": "UC1",
      "title": "Submit order",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "submits the order",
          "note": ""
        },
        {
          "n": 2,
          "src": "C1",
          "dst": "C2",
          "phrase": "",
          "note": ""
        }
      ]
    },
    {
      "uc": "UC2",
      "title": "Approve order",
      "steps": [
        {
          "n": 1,
          "src": "Adam",
          "dst": "C2",
          "phrase": "approves the order",
          "note": ""
        },
        {
          "n": 2,
          "src": "C2",
          "dst": "D1",
          "phrase": "",
          "note": ""
        }
      ]
    }
  ],
  "edges": [
    {
      "src": "C1",
      "verb": "calls",
      "dst": "C2",
      "why": "reach engine",
      "where": "f"
    },
    {
      "src": "C2",
      "verb": "reads",
      "dst": "D1",
      "why": "cache",
      "where": "f"
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


def make_gp_role_actor_map(flow_actor: str = "Org admin") -> str:
    """A Happy Path step whose use case's actor matches a defined Role, so hp_actors can join the
    lifeline to the Roles table (wants + kind). The T6 flow opens with an actor step; every kept test
    uses the default Role-matching actor (the undefined-actor variant only served the retired
    validator test)."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [
    {
      "id": "R1",
      "name": "Org admin",
      "kind": "human",
      "wants": "manage",
      "drives": "UC22"
    }
  ],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC22",
      "name": "Create org",
      "actors": ["R1"],
      "trigger_outcome": "a -> b"
    }
  ],
  "happy_path": [
    {
      "id": "HP1",
      "uc": "UC22",
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
      "uc": "UC22",
      "title": "Create org",
      "steps": [
        {
          "n": 1,
          "src": "R1",
          "dst": "C1",
          "phrase": "creates the org",
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


def parse_map(json_text: str) -> build_graph.GraphDict:
    """Graph from the scenario map (a JSON model document), through the LIVE pipeline:
    load_model → model_to_graph."""
    return model_to_graph(load_model(json_text))


def test_parser_proper_layout_names_and_parents() -> None:
    g = parse_map(make_grouped_map("proper"))
    comps = {k: v for k, v in g["nodes"].items() if v["kind"] == "component"}
    assert comps["C1"]["name"] == "Front door"
    assert comps["C1"]["parent"] == "S1" and comps["C2"]["parent"] == "S2"


def test_parser_agent_layout_reads_membership_and_falls_back_name() -> None:
    g = parse_map(make_grouped_map("agent"))  # no name col, Subsystem at index 1
    comps = {k: v for k, v in g["nodes"].items() if v["kind"] == "component"}
    assert comps["C1"]["parent"] == "S1"   # membership still read (the bug we fixed)
    assert comps["C1"]["name"] == "C1"     # falls back to id, never the subsystem "S1"


def test_parser_subsystem_nodes_and_edges() -> None:
    g = parse_map(make_grouped_map("agent"))
    assert {k for k, v in g["nodes"].items() if v["kind"] == "subsystem"} == {"S1", "S2"}
    assert any(e["src"] == "C1" and e["dst"] == "C2" for e in g["edges"])


def test_default_subsystem_injected_when_ungrouped() -> None:
    # A map with components but no Subsystem table gets ONE synthetic subsystem named after the project,
    # with every component reparented under it — so the component-level view always sits under a
    # subsystem (the flat Components map is no longer the only home for components).
    g = parse_map(make_ungrouped_map())  # title 'X', one component C1, no S table
    subs = {k: v for k, v in g["nodes"].items() if v["kind"] == "subsystem"}
    assert set(subs) == {build_graph.DEFAULT_SUBSYSTEM_ID}
    assert subs[build_graph.DEFAULT_SUBSYSTEM_ID]["name"] == "X"
    assert g["nodes"]["C1"]["parent"] == build_graph.DEFAULT_SUBSYSTEM_ID
    assert gen_viewer.has_grouping(g) is True


def test_no_default_subsystem_when_already_grouped() -> None:
    # A map that already groups its components is left untouched — no S0, the real subsystems stand.
    g = parse_map(make_grouped_map("proper"))
    assert build_graph.DEFAULT_SUBSYSTEM_ID not in g["nodes"]
    assert {k for k, v in g["nodes"].items() if v["kind"] == "subsystem"} == {"S1", "S2"}


def test_no_default_subsystem_for_pure_domain_map() -> None:
    # No components -> nothing to group -> no synthetic subsystem (a pure domain map stays ungrouped).
    g = parse_map(make_domain_map())
    assert build_graph.DEFAULT_SUBSYSTEM_ID not in g["nodes"]
    assert not any(v["kind"] == "subsystem" for v in g["nodes"].values())


def test_subsystem_card_keeps_internal_wiring_and_deps() -> None:
    # Q1=B: a subsystem card shows the subsystem's own components, their internal edges, and the
    # deps they touch — but never a sibling subsystem's component.
    by_sub = gen_viewer.subsystem_component_mermaids(parse_map(make_card_map()))
    s1 = by_sub["S1"]
    assert "subgraph S1[" in s1                         # the subsystem reads as a labelled frame
    assert "C1" in s1 and "C3" in s1                    # both S1 components present
    assert "C1 -->|\"routes\"| C3" in s1                    # internal wiring kept
    assert f'S2["<span class=cyslot data-k=subsystem data-v=compact data-id=S2></span>"]:::cy-S2' in s1  # the neighbour S2 drawn as a collapsed item box
    assert "class S2 itembox" in s1                     # …whose node draws no shape: the item box is the box
    assert 'C1["<span class=cyslot data-k=component data-v=tight data-id=C1></span>"]:::cy-C1' in s1  # a member is a tight item box
    assert s1.startswith("%%{init") and "\nflowchart TB\n" in s1   # no node padding: arrows stop on the boxes
    assert "C1 --> S2" in s1 and "C3 --> S2" in s1  # cross arrows: component -> neighbour box, labelled by edge count
    assert "C2" not in s1                               # the sibling's component itself is NOT drawn
    s2 = by_sub["S2"]
    assert "subgraph S2[" in s2
    assert "C2" in s2 and "D1" in s2                    # Q1=B keeps the dep the component touches
    assert "C2 -->|\"reads\"| D1" in s2                     # ...with its component->dep edge (ground-level, real verb)
    assert f'S1["<span class=cyslot data-k=subsystem data-v=compact data-id=S1></span>"]:::cy-S1' in s2  # the neighbour S1 box, an item box
    assert 'D1["<span class=cyslot data-k=dep data-v=tight data-id=D1></span>"]:::cy-D1' in s2  # the dep too
    assert "classDef itembox fill:none,stroke:none" in s2 and "classDef dep" not in s2
    assert "S1 -->|×2| C2" in s2                        # inbound cross arrow, ×2 folded (C1->C2 + C3->C2)


def test_edge_card_has_both_subsystems_with_cross_and_inner_edges() -> None:
    # Q2=A: an edge card frames BOTH subsystems with ALL their components, draws the A->B
    # component edges AND each subsystem's own internal wiring — but no deps, no other-subsystem
    # edges, and only the A->B direction of the crossing.
    g = parse_map(make_card_map())
    cards = gen_viewer.edge_card_mermaids(g)
    assert set(cards) == {"S1>S2"}                      # only the direction that actually crosses
    card = cards["S1>S2"]
    assert "subgraph S1[" in card and "subgraph S2[" in card
    assert "C1" in card and "C3" in card and "C2" in card   # all components of both (Q2=A)
    assert "C1 -->|\"calls\"| C2" in card and "C3 -->|\"calls\"| C2" in card  # the cross edges
    assert "C1 -->|\"routes\"| C3" in card                  # S1's inner link now kept
    assert "D1" not in card                             # no deps in an edge card


def test_nested_subsystem_has_card_at_every_level() -> None:
    # A card is generated for the NESTED subsystem S2, not only top-level ones — so ⌘-clicking the S2
    # box inside S1's card has a card to open.
    by_sub = gen_viewer.subsystem_component_mermaids(parse_map(make_nested_subsystem_map()))
    assert {"S1", "S2", "S3"} <= set(by_sub)


def test_nested_parent_card_shows_child_subsystem_box_not_flattened() -> None:
    # S1's card shows its DIRECT member C1 and its child subsystem S2 as a drillable box — and does NOT
    # flatten S2's grandchild component C2 into the card (that lives one level down, on S2's card).
    by_sub = gen_viewer.subsystem_component_mermaids(parse_map(make_nested_subsystem_map()))
    s1 = by_sub["S1"]
    assert "subgraph S1[" in s1
    assert "C1" in s1                       # direct member
    assert f'S2["<span class=cyslot data-k=subsystem data-v=compact data-id=S2></span>"]:::cy-S2' in s1  # child subsystem as a (drillable) collapsed item box
    assert "class S2 itembox" in s1
    assert "C2" not in s1                   # grandchild NOT flattened into the parent card
    assert "C1 --> S2" in s1             # member -> child-subsystem box (aggregated, count-labelled, drills in)


def test_nested_crossing_resolves_at_card_level() -> None:
    # C2 (in S2) -> C3 (in S3): on S1's card this reads as the child box S2 -> the sibling box S3,
    # resolved at S1's altitude (not flattened to top). On S2's own card the grandchild's external link
    # to S3 is drawn directly.
    by_sub = gen_viewer.subsystem_component_mermaids(parse_map(make_nested_subsystem_map()))
    s1 = by_sub["S1"]
    assert "S2 --> S3" in s1
    assert 'S3["<span class=cyslot data-k=subsystem data-v=compact data-id=S3></span>"]:::cy-S3' in s1  # the sibling neighbour box, an item box
    s2 = by_sub["S2"]
    assert "C2" in s2 and "C2 --> S3" in s2


def test_container_overview_shows_only_top_level_subsystems() -> None:
    # The Subsystems overview draws only top-level groups (S1, S3); the nested S2 is reachable by
    # drilling S1, not as a top-level box. The nested C2->C3 edge aggregates to the top S1->S3 arrow.
    cont = gen_viewer.gen_container_mermaid(parse_map(make_nested_subsystem_map()))
    assert f'S1["<span class=cyslot data-k=subsystem data-v=compact data-id=S1></span>"]:::cy-S1' in cont and 'S3["' in cont   # item-box slots, as the Data overview
    assert 'S2["' not in cont
    assert cont.startswith("%%{init") and "class S1 itembox" in cont and "classDef itembox fill:none,stroke:none" in cont
    assert "S1 --> S3" in cont


def test_nested_edge_cards_for_disjoint_pairs_only() -> None:
    # The parent->child crossing (C1->C2, the S1>S2 overlap) is NOT an edge card — it's navigated.
    # The disjoint crossing C2->C3 gets a card at every level it is drawn: S2>S3 (nested card) and
    # S1>S3 (overview / S1 card), each framing two non-overlapping subsystems.
    cards = gen_viewer.edge_card_mermaids(parse_map(make_nested_subsystem_map()))
    assert "S1>S2" not in cards
    assert {"S2>S3", "S1>S3"} <= set(cards)
    s2s3 = cards["S2>S3"]
    assert "subgraph S2[" in s2s3 and "subgraph S3[" in s2s3
    assert "C2 -->|\"calls\"| C3" in s2s3            # a direct-member crossing stays labelled (ground-level, real verb)
    assert "S2 --> C3" in cards["S1>S3"]      # a crossing reaching into child S2 is an aggregated box arrow, count-labelled


def test_nested_container_edges_keyed_per_level() -> None:
    ce = gen_viewer.gen_container_edges(parse_map(make_nested_subsystem_map()))
    assert {"S2>S3", "S1>S3"} <= set(ce)
    assert {(r["src"], r["dst"]) for r in ce["S2>S3"]} == {("C2", "C3")}


def make_nested_bridge_map() -> str:
    """A nested subsystem (S2<-S1) and nested subdomain (SD2<-SD1) joined by a C->E owns edge — so a
    bridge arrow can be drawn on a NESTED subsystem card AND a nested subdomain card (review finding #1)."""
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
  "subsystems": [
    {
      "id": "S1",
      "name": "Outer",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    },
    {
      "id": "S2",
      "name": "Inner",
      "purpose": "x",
      "parent": "S1",
      "source": "a/",
      "confidence": "V"
    }
  ],
  "components": [
    {
      "id": "C1",
      "name": "Repo",
      "subsystem": "S2",
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
  "subdomains": [
    {
      "id": "SD1",
      "name": "DomOuter",
      "purpose": "x",
      "parent": null,
      "source": "f:1",
      "confidence": "inferred"
    },
    {
      "id": "SD2",
      "name": "DomInner",
      "purpose": "x",
      "parent": "SD1",
      "source": "f:1",
      "confidence": "inferred"
    }
  ],
  "entities": [
    {
      "id": "E1",
      "name": "Order",
      "store": {"notes": "orders"},
      "meaning": "x",
      "subdomain": "SD2",
      "source": "f:1",
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
      "verb": "persists",
      "dst": "E1",
      "why": "store",
      "where": "f"
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


def test_nested_bridge_cards_keyed_per_level() -> None:
    # The JS requests a bridge card for whatever S/SD boxes a card draws: S2>SD1 from the nested
    # subsystem card (top-subdomain box) and S1>SD2 from the nested subdomain card (top-subsystem box).
    # Every (subsystem-ancestor, subdomain-ancestor) pair must be generated so no drill misses its key.
    keys = set(gen_viewer.bridge_card_mermaids(parse_map(make_nested_bridge_map())))
    assert {"S1>SD1", "S2>SD1", "S1>SD2", "S2>SD2"} <= keys


def test_container_edges_list_crossing_component_edges() -> None:
    # Each inter-subsystem arrow 'A>B' carries the underlying component->component edges (endpoints,
    # names, verb, why) so the viewer lists their meanings in the arrow's hover tooltip.
    ce = gen_viewer.gen_container_edges(parse_map(make_card_map()))
    assert set(ce) == {"S1>S2"}                          # only the crossing direction
    rows = ce["S1>S2"]
    assert {(r["src"], r["dst"]) for r in rows} == {("C1", "C2"), ("C3", "C2")}
    assert {r["srcName"] for r in rows} == {"Front door", "Router"}
    assert all(r["verb"] == "calls" and r["why"] == "reach engine" for r in rows)


def test_bundle_carries_edge_card_data() -> None:
    # The served bundle must carry the edge-card diagrams AND the per-arrow component-edge lists so the
    # client opens on click / previews on hover.
    b = bundle_of(make_card_map())
    assert "S1>S2" in b["containerEdges"] and "S1>S2" in b["mermaidEdgeCard"]


def test_parser_ignores_fenced_nodes() -> None:
    # The graph parser must also skip fenced examples — no phantom C9 node from the example.
    g = parse_map(make_fenced_node_map())
    assert "C1" in g["nodes"] and "C9" not in g["nodes"], list(g["nodes"])


def test_shell_pins_libs_and_bundle_carries_node_names() -> None:
    # Chrome lives in the served shell (pinned+SRI CDN libs, inline favicon); the map data lives in the
    # bundle (node names the client renders).
    shell = (VIEWER_DIR / "viewer.html").read_text(encoding="utf-8")
    assert 'integrity="sha384-' in shell and 'rel="icon"' in shell
    b = bundle_of(make_grouped_map("proper"))
    names = {n.get("name") for n in b["graph"]["nodes"].values()}
    assert "Front door" in names


def test_bundle_has_nested_drill_data() -> None:
    # A nested map's bundle carries an edge card for each DISJOINT cross-pair at every level (S2>S3
    # nested, S1>S3 overview) and omits the overlapping parent-child pair (S1>S2, which navigates).
    keys = set(bundle_of(make_nested_subsystem_map())["mermaidEdgeCard"])
    assert "S2>S3" in keys and "S1>S3" in keys and "S1>S2" not in keys


def test_shell_has_no_components_tab_but_js_keeps_generators() -> None:
    # The flat Components map is no longer a tab; its generators stay in the frontend so it can be restored.
    shell = (VIEWER_DIR / "viewer.html").read_text(encoding="utf-8")
    js = (VIEWER_DIR / "viewer.js").read_text(encoding="utf-8")
    assert 'data-view="component"' not in shell        # the Components tab button is gone
    assert 'data-view="container"' in shell            # Subsystems remains
    assert "MERMAID_BASE" in js and "bindComponent" in js  # generators kept dormant (restorable)


def test_glued_collection_relation_is_labelled() -> None:
    """An entity-typed collection field written glued (`tokens:E28[]`) must still BACK its relation,
    so the composition arrow renders its real field name as the label (not blank)."""
    cards = """{
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "Snapshot",
      "store": {"notes": "s"},
      "meaning": "m",
      "subdomain": null,
      "source": "f:1",
      "fields": [
        {
          "name": "clients",
          "type": "json",
          "markers": []
        },
        {
          "name": "access_tokens",
          "type": "E28",
          "markers": [
            "[]"
          ]
        }
      ],
      "relations": [
        {
          "verb": "contains",
          "target": "E28",
          "src_card": "1",
          "dst_card": "*",
          "display": "StoredAccessToken",
          "how": null
        }
      ]
    },
    {
      "id": "E28",
      "name": "StoredAccessToken",
      "store": null,
      "meaning": "m",
      "subdomain": null,
      "source": "f:2",
      "fields": [
        {
          "name": "token",
          "type": "string",
          "markers": [
            "PK"
          ]
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
    g = parse_map(cards)
    rel = [e for e in g["edges"] if e["src"] == "E1" and e["dst"] == "E28"][0]
    assert rel["fk_fields"] == ["access_tokens"] and rel["fk_side"] == "src"


def test_parser_domain_cards_nodes_attrs_edges() -> None:
    g = parse_map(make_domain_map())
    e1 = g["nodes"]["E1"]
    assert e1["kind"] == "entity" and e1["name"] == "Order"
    assert cast("dict[str, str]", e1["fields"])["Stored"] == "orders collection"
    attrs1 = cast("list[dict[str, str]]", e1["attrs"])
    assert any(a["name"] == "id" and a["type"] == "ObjectId" and a["markers"] == "PK" for a in attrs1)
    attrs2 = cast("list[dict[str, str]]", g["nodes"]["E2"]["attrs"])
    assert {a["name"] for a in attrs2} == {"sku", "qty"}   # bullet-list FIELDS
    rel = [e for e in g["edges"] if e["src"] == "E1" and e["dst"] == "E2"]
    assert rel and rel[0]["verb"] == "contains" and rel[0]["kind"] == "composition"
    assert rel[0]["src_card"] == "1" and rel[0]["dst_card"] == "*"


def test_gen_domain_mermaid_classdiagram() -> None:
    mm = gen_viewer.gen_domain_mermaid(parse_map(make_domain_map()))
    assert mm.startswith("classDiagram")
    assert 'class E1["Order"]' in mm
    assert "ObjectId id" in mm                          # attribute rendered in the box
    assert 'E1 "1" *-- "*" E2' in mm                    # composition arrow + cardinality
    assert ": contains" not in mm                       # redundant structural verb is not drawn as a label


def test_gen_domain_mermaid_resolves_embedded_entity_type() -> None:
    # a field typed by an entity id (`mode:E2`) renders with the entity's NAME, not the raw id.
    mm = gen_viewer.gen_domain_mermaid(parse_map(make_domain_map(_CARDS_EMBEDDED_ENTITY_TYPE)))
    assert "AuthMode mode" in mm and "E2 mode" not in mm


def _box_member_lines(mm: str, eid: str) -> list[str]:
    """The member lines a class box draws, in order — the list `entity_field_links` indexes into."""
    out: list[str] = []
    inside = False
    for line in mm.splitlines():
        if line.strip().startswith(f'class {eid}["'):
            inside = line.rstrip().endswith("{")
        elif inside:
            if line.strip() == "}":
                break
            out.append(line.strip())
    return out


def test_entity_field_links_points_at_the_typing_entity() -> None:
    # a field typed by an entity (`mode:E2`) is offered to the viewer as a link on the TYPE word.
    links = gen_viewer.entity_field_links(parse_map(make_domain_map(_CARDS_EMBEDDED_ENTITY_TYPE)))
    assert links == {"E1": [{"i": 0, "type": "AuthMode", "target": "E2"}]}   # `id:int` is not a link


def test_entity_field_links_carries_the_collection_shape() -> None:
    # the `[]` shape rides on the type, so the link covers exactly the drawn type text.
    links = gen_viewer.entity_field_links(parse_map(make_domain_map(_CARDS_COLLECTION_MARKER)))
    assert links["E1"] == [{"i": 0, "type": "StoredRefreshToken[]", "target": "E2"}]


def test_entity_field_links_indexes_match_the_drawn_box() -> None:
    # the viewer finds a link's member by INDEX in the box, so every index must land on a line that
    # actually starts with that link's type — otherwise a link would sit on the wrong field.
    graph = parse_map(make_domain_map(_CARDS_COLLECTION_MARKER))
    mm = gen_viewer.gen_domain_mermaid(graph)
    links = gen_viewer.entity_field_links(graph)
    assert links
    for eid, rows in links.items():
        members = _box_member_lines(mm, eid)
        for row in rows:
            assert members[int(row["i"])].startswith(str(row["type"]) + " ")


def test_gen_domain_mermaid_shows_collection_marker_in_box() -> None:
    # a `[]` (collection) marker is part of the type SHAPE, so it renders in the box member —
    # `StoredRefreshToken[] refresh_tokens`, not a single-valued-looking `StoredRefreshToken …`.
    # `?`/PK/FK stay out of the box (annotations, panel-only).
    mm = gen_viewer.gen_domain_mermaid(parse_map(make_domain_map(_CARDS_COLLECTION_MARKER)))
    assert "StoredRefreshToken[] refresh_tokens" in mm   # collection shown in the box
    assert "int expires_at" in mm and "int? " not in mm  # nullable marker stays out of the box
    assert "int id" in mm                                # PK stays out of the box


def test_gen_domain_mermaid_relation_labels() -> None:
    # forward field -> plain name; reverse FK (FK→E1) -> "↩ field"; the redundant verb is dropped.
    mm = gen_viewer.gen_domain_mermaid(parse_map(make_domain_map(_CARDS_RELATION_LABELS)))
    assert ": subscription" in mm     # forward: E1.subscription typed E3
    assert ": ↩ org_id" in mm          # reverse: E2.org_id FK→E1
    assert ": has" not in mm           # the redundant aggregation verb is not drawn


def test_gen_domain_mermaid_drops_ungrounded_verb() -> None:
    # an association not backed by any field gets NO label — the verb is interpretive, not grounded.
    mm = gen_viewer.gen_domain_mermaid(parse_map(make_domain_map(_CARDS_UNGROUNDED_VERB)))
    assert "authorizes" not in mm     # ungrounded association verb is not drawn as a label


def test_gen_domain_mermaid_forward_fk_label() -> None:
    # A foreign key on the SOURCE (`role:string FK→E2`) labels the arrow with the field name — the
    # symmetric counterpart of the reverse `↩` case, so a marked FK is represented whichever side
    # authored the relation (the asymmetry that left all but one mcpolis FK arrow blank is gone).
    mm = gen_viewer.gen_domain_mermaid(parse_map(make_domain_map(_CARDS_FORWARD_FK)))
    assert ": role" in mm                  # forward FK -> the plain field name
    assert "↩" not in mm                   # not a back-reference (the field is on the source/tail)
    assert ": assignedRole" not in mm      # the verb itself is never drawn as the label


def test_fk_targets_token_exact() -> None:
    # `FK→E1` must resolve to exactly {E1} — never match inside `E11` (the substring bug class).
    assert grammar.fk_targets("FK→E1") == {"E1"}
    assert grammar.fk_targets(["?", "FK->E5"]) == {"E5"}      # ascii arrow + nullable marker
    assert "E1" not in grammar.fk_targets("FK→E11")


def test_resolve_backing_composite_key_keeps_all_fields() -> None:
    # A composite foreign key — Snapshot's (user_id, page_id) both `FK→TrackedPage` — must resolve to
    # BOTH backing fields, not arbitrarily just the first, so the label shows the whole key.
    snapshot = [("user_id", "string", {"E1"}), ("page_id", "string", {"E1"}),
                ("snapshot_id", "string", set())]
    trackedpage = [("user_id", "string", set()), ("page_id", "string", set())]
    fields, side = grammar.resolve_backing("E2", "E1", snapshot, trackedpage)
    assert fields == ["user_id", "page_id"] and side == "src"


def test_relation_label_composite_key_joins_fields() -> None:
    # The canvas arrow label lists every backing field of a composite key, comma-joined.
    assert gen_viewer._relation_label({"fk_fields": ["user_id", "page_id"], "fk_side": "src"}) \
        == "user_id, page_id"
    # Reverse (FK on the head) keeps the back-reference marker in front of the joined list.
    assert gen_viewer._relation_label({"fk_fields": ["user_id", "page_id"], "fk_side": "dst"}) \
        == "↩ user_id, page_id"


def test_relation_label_keyed_by_marks_storage_key() -> None:
    # A field-less relation with a storage key draws the «key» marker + name(s), distinct from an FK.
    assert gen_viewer._relation_label({"keyed_by": ["upstream_id"]}) == "«key» upstream_id"
    # composite key: comma-joined after the marker.
    assert gen_viewer._relation_label({"keyed_by": ["org_id", "upstream_id"]}) \
        == "«key» org_id, upstream_id"
    # a real backing FK WINS over keyed_by (they are mutually exclusive; the field label takes over).
    assert gen_viewer._relation_label(
        {"fk_fields": ["parent_id"], "fk_side": "src", "keyed_by": ["upstream_id"]}) == "parent_id"
    assert gen_viewer._relation_label({}) == ""            # neither -> blank


def test_relation_item_markdown_shows_keyed_by_with_marker() -> None:
    # The markdown RELATIONS view mirrors the canvas: «key» + comma-joined names, before the {how}.
    r = EntityRelation(verb="attachedTo", target="E2", src_card="*", dst_card="1",
                       keyed_by=["upstream_id"], how="admin scope")
    item = _relation_item(r)
    assert "«key» upstream_id" in item
    assert item.index("«key»") < item.index("{admin scope}")   # key before the prose note


def test_parser_domain_edge_carries_backing_and_how() -> None:
    # The resolved backing (fk_fields/fk_side) and the authored {how} note ride the serialized edge,
    # so the canvas label and the panel's "Implemented by" line come from one resolution.
    g = parse_map(make_domain_map(_CARDS_BACKING_HOW))
    e12 = next(e for e in g["edges"] if e["src"] == "E1" and e["dst"] == "E2")
    assert e12["fk_fields"] == ["org_id"] and e12["fk_side"] == "dst"   # reverse FK on the target
    e13 = next(e for e in g["edges"] if e["src"] == "E1" and e["dst"] == "E3")
    assert e13["fk_fields"] == [] and e13["how"] == "keyed by (org, upstream)"  # indirect -> how-note


def test_class_diagram_inheritance_arrow_labelled_isa() -> None:
    # Verb principle: the inheritance triangle trusts the authored `isA` verb (never code-verified) —
    # a derivation, not an asserted fact (verbs prioritize, never gate) — rendered as the bare verb.
    md = """{
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [],
  "entities": [
    {
      "id": "E1",
      "name": "Base",
      "store": {"notes": "s"},
      "meaning": "m",
      "subdomain": null,
      "source": "f:1",
      "fields": [
        {
          "name": "id",
          "type": "int",
          "markers": []
        }
      ],
      "relations": []
    },
    {
      "id": "E2",
      "name": "Child",
      "store": {"notes": "s"},
      "meaning": "m",
      "subdomain": null,
      "source": "f:2",
      "fields": [
        {
          "name": "id",
          "type": "int",
          "markers": []
        }
      ],
      "relations": [
        {
          "verb": "isA",
          "target": "E1",
          "src_card": null,
          "dst_card": null,
          "display": "",
          "how": null
        }
      ]
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
    mm = gen_viewer.gen_domain_mermaid(parse_map(md))
    assert "E2 --|> E1 : isA" in mm, mm


def make_context_map(cards: str | None = None, contexts: str | None = None) -> str:
    """A domain map with a Subdomains (SD) table + `SUBDOMAIN:` lines on the cards. Default: two contexts
    (SD1 Ordering, SD2 Catalog); E1/E2 live in SD1, E4 in SD2; E1 contains E2 (intra-context) and
    refersTo E4 (the one CROSS-context relation), so the tests exercise membership + a crossing edge."""
    if cards is not None and contexts is not None:
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
      "name": "Search",
      "actors": [],
      "trigger_outcome": "types -> list"
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [
    {
      "id": "SD1",
      "name": "Ordering",
      "purpose": "x",
      "parent": null,
      "source": "[order.py](order.py#L1)",
      "confidence": "inferred"
    },
    {
      "id": "SD2",
      "name": "Inner",
      "purpose": "x",
      "parent": "SD1",
      "source": "[order.py](order.py#L1)",
      "confidence": "inferred"
    },
    {
      "id": "SD3",
      "name": "Catalog",
      "purpose": "x",
      "parent": null,
      "source": "[product.py](product.py#L1)",
      "confidence": "inferred"
    }
  ],
  "entities": [
    {
      "id": "E1",
      "name": "Order",
      "store": {"notes": "orders"},
      "meaning": "a purchase",
      "subdomain": "SD1",
      "source": "order.py:12",
      "fields": [
        {
          "name": "id",
          "type": "ObjectId",
          "markers": [
            "PK"
          ]
        }
      ],
      "relations": [
        {
          "verb": "contains",
          "target": "E2",
          "src_card": "1",
          "dst_card": "*",
          "display": "LineItem",
          "how": null
        }
      ]
    },
    {
      "id": "E2",
      "name": "LineItem",
      "store": null,
      "meaning": "a line",
      "subdomain": "SD2",
      "source": "order.py:58",
      "fields": [
        {
          "name": "sku",
          "type": "string",
          "markers": []
        },
        {
          "name": "prod",
          "type": "E3",
          "markers": []
        }
      ],
      "relations": [
        {
          "verb": "refersTo",
          "target": "E3",
          "src_card": "*",
          "dst_card": "1",
          "display": "Product",
          "how": null
        }
      ]
    },
    {
      "id": "E3",
      "name": "Product",
      "store": null,
      "meaning": "a product",
      "subdomain": "SD3",
      "source": "product.py:9",
      "fields": [
        {
          "name": "name",
          "type": "string",
          "markers": []
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
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
      "name": "Search",
      "actors": [],
      "trigger_outcome": "types -> list"
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [
    {
      "id": "SD1",
      "name": "Ordering",
      "purpose": "purchase lifecycle",
      "parent": null,
      "source": "[order.py](order.py#L1)",
      "confidence": "inferred"
    },
    {
      "id": "SD2",
      "name": "Catalog",
      "purpose": "products",
      "parent": null,
      "source": "[product.py](product.py#L1)",
      "confidence": "inferred"
    }
  ],
  "entities": [
    {
      "id": "E1",
      "name": "Order",
      "store": {"notes": "orders"},
      "meaning": "a purchase",
      "subdomain": "SD1",
      "source": "order.py:12",
      "fields": [
        {
          "name": "id",
          "type": "ObjectId",
          "markers": [
            "PK"
          ]
        },
        {
          "name": "product",
          "type": "E4",
          "markers": []
        }
      ],
      "relations": [
        {
          "verb": "contains",
          "target": "E2",
          "src_card": "1",
          "dst_card": "*",
          "display": "LineItem",
          "how": null
        },
        {
          "verb": "refersTo",
          "target": "E4",
          "src_card": "*",
          "dst_card": "1",
          "display": "Product",
          "how": null
        }
      ]
    },
    {
      "id": "E2",
      "name": "LineItem",
      "store": null,
      "meaning": "a line",
      "subdomain": "SD1",
      "source": "order.py:58",
      "fields": [
        {
          "name": "sku",
          "type": "string",
          "markers": []
        }
      ],
      "relations": []
    },
    {
      "id": "E4",
      "name": "Product",
      "store": null,
      "meaning": "a product",
      "subdomain": "SD2",
      "source": "product.py:9",
      "fields": [
        {
          "name": "name",
          "type": "string",
          "markers": []
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_nested_subdomain_map() -> str:
    """SD1 (top) nests SD2; SD3 is a top-level sibling. E1 is a DIRECT entity of SD1, E2 a grandchild
    (in SD2), E3 in SD3. E1 contains E2 (direct entity -> child-subdomain box), E2 refersTo E3
    (grandchild -> sibling subdomain). The domain mirror of make_nested_subsystem_map."""
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
      "name": "Search",
      "actors": [],
      "trigger_outcome": "types -> list"
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [
    {
      "id": "SD1",
      "name": "Ordering",
      "purpose": "x",
      "parent": null,
      "source": "[order.py](order.py#L1)",
      "confidence": "inferred"
    },
    {
      "id": "SD2",
      "name": "Inner",
      "purpose": "x",
      "parent": "SD1",
      "source": "[order.py](order.py#L1)",
      "confidence": "inferred"
    },
    {
      "id": "SD3",
      "name": "Catalog",
      "purpose": "x",
      "parent": null,
      "source": "[product.py](product.py#L1)",
      "confidence": "inferred"
    }
  ],
  "entities": [
    {
      "id": "E1",
      "name": "Order",
      "store": {"notes": "orders"},
      "meaning": "a purchase",
      "subdomain": "SD1",
      "source": "order.py:12",
      "fields": [
        {
          "name": "id",
          "type": "ObjectId",
          "markers": [
            "PK"
          ]
        }
      ],
      "relations": [
        {
          "verb": "contains",
          "target": "E2",
          "src_card": "1",
          "dst_card": "*",
          "display": "LineItem",
          "how": null
        }
      ]
    },
    {
      "id": "E2",
      "name": "LineItem",
      "store": null,
      "meaning": "a line",
      "subdomain": "SD2",
      "source": "order.py:58",
      "fields": [
        {
          "name": "sku",
          "type": "string",
          "markers": []
        },
        {
          "name": "prod",
          "type": "E3",
          "markers": []
        }
      ],
      "relations": [
        {
          "verb": "refersTo",
          "target": "E3",
          "src_card": "*",
          "dst_card": "1",
          "display": "Product",
          "how": null
        }
      ]
    },
    {
      "id": "E3",
      "name": "Product",
      "store": null,
      "meaning": "a product",
      "subdomain": "SD3",
      "source": "product.py:9",
      "fields": [
        {
          "name": "name",
          "type": "string",
          "markers": []
        }
      ],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def test_nested_subdomain_has_card_at_every_level() -> None:
    by_sd = gen_viewer.domain_subdomain_mermaids(parse_map(make_nested_subdomain_map()))
    assert {"SD1", "SD2", "SD3"} <= set(by_sd)   # a card for the NESTED subdomain SD2, not only top-level


def test_nested_subdomain_card_shows_child_box_not_flattened() -> None:
    by_sd = gen_viewer.domain_subdomain_mermaids(parse_map(make_nested_subdomain_map()))
    sd1 = by_sd["SD1"]
    assert "namespace SD1[" in sd1
    assert "E1" in sd1                    # direct entity
    assert "class SD2[" in sd1           # child subdomain as a (drillable) collapsed box
    assert "E2" not in sd1               # grandchild entity NOT flattened into the parent card
    assert "E1 --> SD2" in sd1       # direct entity -> child-subdomain box (aggregated, count-labelled)


def test_nested_subdomain_crossing_resolves_at_card_level() -> None:
    by_sd = gen_viewer.domain_subdomain_mermaids(parse_map(make_nested_subdomain_map()))
    sd1 = by_sd["SD1"]
    assert "SD2 --> SD3" in sd1       # E2(in SD2) -> E3(in SD3) shows as child-box -> sibling box (count-labelled)
    sd2 = by_sd["SD2"]
    assert "E2" in sd2 and "E2 --> SD3" in sd2


def test_domain_overview_shows_only_top_level_subdomains() -> None:
    cont = gen_viewer.gen_domain_container_mermaid(parse_map(make_nested_subdomain_map()))
    assert 'SD1["' in cont and 'SD3["' in cont
    assert 'SD2["' not in cont
    assert "SD1 --> SD3" in cont       # nested E2->E3 aggregates to the top SD1->SD3 arrow


def test_nested_domain_edge_cards_for_disjoint_pairs_only() -> None:
    # E1->E2 is parent->child (SD1>SD2 overlap) -> navigated, no card. E2->E3 is disjoint and gets a
    # card at every level it is drawn: SD2>SD3 (nested) and SD1>SD3 (overview / SD1 card).
    cards = gen_viewer.domain_edge_card_mermaids(parse_map(make_nested_subdomain_map()))
    assert "SD1>SD2" not in cards
    assert {"SD2>SD3", "SD1>SD3"} <= set(cards)
    ce = gen_viewer.gen_domain_container_edges(parse_map(make_nested_subdomain_map()))
    assert {"SD2>SD3", "SD1>SD3"} <= set(ce)
    assert {(r["src"], r["dst"]) for r in ce["SD2>SD3"]} == {("E2", "E3")}


def test_parser_entity_gets_context_parent_and_context_nodes() -> None:
    g = parse_map(make_context_map())
    assert g["nodes"]["E1"]["parent"] == "SD1" and g["nodes"]["E4"]["parent"] == "SD2"
    ctx = {k: v for k, v in g["nodes"].items() if v["kind"] == "subdomain"}
    assert set(ctx) == {"SD1", "SD2"} and ctx["SD1"]["name"] == "Ordering"


def test_parser_entity_without_context_has_no_parent() -> None:
    # An ungrouped domain model (no Subdomains table, no CONTEXT line) leaves entities parent-less.
    assert parse_map(make_domain_map())["nodes"]["E1"]["parent"] is None


def make_bridge_map() -> str:
    """Subsystems S1/S2 + context SD1 with entity E1; C1 (S1) persists E1, C2 (S2) reads E1. Exercises
    the S→SD bridge: the owning subsystem's card shows an `owns` arrow, the reader's a `reads` arrow."""
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
  "subsystems": [
    {
      "id": "S1",
      "name": "Edge",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    },
    {
      "id": "S2",
      "name": "Core",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    }
  ],
  "components": [
    {
      "id": "C1",
      "name": "Writer",
      "subsystem": "S1",
      "purpose": "x",
      "depends_on": "",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "Reader",
      "subsystem": "S2",
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
  "subdomains": [
    {
      "id": "SD1",
      "name": "Ordering",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    }
  ],
  "entities": [
    {
      "id": "E1",
      "name": "Order",
      "store": {"notes": "orders"},
      "meaning": "m",
      "subdomain": "SD1",
      "source": "f:1",
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
      "verb": "persists",
      "dst": "E1",
      "why": "store",
      "where": "f"
    },
    {
      "src": "C2",
      "verb": "reads",
      "dst": "E1",
      "why": "load",
      "where": "f"
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


def test_has_subdomains() -> None:
    assert gen_viewer.has_subdomains(parse_map(make_context_map())) is True
    assert gen_viewer.has_subdomains(parse_map(make_domain_map())) is False   # domain model, but ungrouped


def test_gen_domain_container_mermaid_boxes_and_crossing_arrow() -> None:
    # The bounded-contexts overview: one ITEM-BOX slot per context (the viewer fills it; the entity
    # count rides in the box's band), with a SDa->SDb arrow DERIVED from a crossing E->E relation
    # (E1 in SD1 refersTo E4 in SD2), labelled by count.
    mm = gen_viewer.gen_domain_container_mermaid(parse_map(make_context_map()))
    assert mm.startswith("%%{init") and "\nflowchart TB\n" in mm   # no node padding: arrows stop on the boxes
    assert 'SD1["<span class=cyslot data-k=subdomain data-v=compact data-id=SD1></span>"]:::cy-SD1' in mm
    assert 'SD2["<span class=cyslot data-k=subdomain data-v=compact data-id=SD2></span>"]:::cy-SD2' in mm
    assert "class SD1 itembox" in mm and "classDef itembox fill:none,stroke:none" in mm  # the slot node draws no shape of its own
    assert "SD1 --> SD2" in mm                                       # the one crossing relation


def test_gen_domain_container_edges_list_crossing_relations() -> None:
    ce = gen_viewer.gen_domain_container_edges(parse_map(make_context_map()))
    assert set(ce) == {"SD1>SD2"}                                       # only the crossing direction
    rows = ce["SD1>SD2"]
    assert {(r["src"], r["dst"]) for r in rows} == {("E1", "E4")}
    assert rows[0]["srcName"] == "Order" and rows[0]["dstName"] == "Product" and rows[0]["verb"] == "refersTo"


def test_gen_domain_subdomain_card_frames_members_collapses_neighbour_subdomains() -> None:
    # The neighbourhood card: the focal subdomain framed as a `namespace` holding its own entities FULL,
    # every OTHER subdomain it relates to drawn as ONE collapsed box (not its individual entities), and a
    # cross arrow per (focal entity, neighbour subdomain) pair — the entity analog of the subsystem card.
    cards = gen_viewer.domain_subdomain_mermaids(parse_map(make_context_map()))
    assert set(cards) == {"SD1", "SD2"}
    cx1 = cards["SD1"]
    assert cx1.startswith("classDiagram")
    assert 'namespace SD1["Ordering"] {' in cx1                     # focal subdomain is a labelled frame
    assert 'class E1["Order"] {' in cx1 and "ObjectId id" in cx1        # member entity, FULL box
    assert 'class E2["LineItem"] {' in cx1                              # the other member, full
    assert 'class SD2["<span class=cyslot data-k=subdomain data-v=compact data-id=SD2></span>"]' in cx1  # neighbour drawn as ONE collapsed subdomain box (an item box)
    assert "style SD2 fill:none,stroke:none" in cx1                     # …whose class draws no shape: the item box is the box
    assert 'class E4["Product"]' not in cx1                             # the neighbour's entity is NOT drawn (collapsed to SD)
    assert 'E1 "1" *-- "*" E2' in cx1                                   # intra-subdomain composition, full
    assert "E1 --> SD2" in cx1                                      # cross arrow to the collapsed neighbour box (count-labelled)
    assert ": product" not in cx1                                       # the crossing is aggregated (count), not a labelled relation here
    # in SD2's card the roles flip: E4 is the framed member, SD1 the collapsed neighbour, arrow inbound
    cx2 = cards["SD2"]
    assert 'namespace SD2["Catalog"] {' in cx2
    assert 'class E4["Product"] {' in cx2 and 'class E1["Order"] {' not in cx2
    assert 'class SD1["<span class=cyslot data-k=subdomain data-v=compact data-id=SD1></span>"]' in cx2
    assert "SD1 --> E4" in cx2                                          # inbound cross arrow from the neighbour (count-labelled)


def test_gen_domain_edge_card_two_namespaces_with_the_crossing_entities() -> None:
    # The subdomain edge card: BOTH subdomains framed as namespaces, holding the entities the crossing
    # relations touch, with those relations drawn IN FULL (kind + backing-field label) — the entity analog
    # of the subsystem edge card. Keyed by the crossing direction only.
    #
    # E2 (LineItem) is at neither end of the E1 → E4 crossing, so the card does not draw it, and SD1's
    # inner E1 *-- E2 wiring goes with the box it points at. The card answers "what does this arrow stand
    # for", and E2 was no part of that answer.
    g = parse_map(make_context_map())
    cards = gen_viewer.domain_edge_card_mermaids(g)
    assert set(cards) == {"SD1>SD2"}                                   # only the crossing direction (E1 → E4)
    card = cards["SD1>SD2"]
    assert card.startswith("classDiagram")
    assert 'namespace SD1["Ordering"] {' in card and 'namespace SD2["Catalog"] {' in card
    assert 'class E1["Order"] {' in card and 'class E4["Product"] {' in card   # the crossing's two ends
    assert 'E1 "*" --> "1" E4 : product' in card                       # the crossing relation, drawn in full
    assert 'class E2["LineItem"] {' not in card                        # at neither end -> not drawn
    assert 'E1 "1" *-- "*" E2' not in card                             # …and neither is the wiring to it
    # The subdomain's OWN card still draws every entity: there the frame is the subject, not the arrow.
    assert 'class E2["LineItem"] {' in gen_viewer.domain_subdomain_mermaids(g)["SD1"]


def test_subsystem_card_bridges_to_contexts_show_edge_count() -> None:
    by_sub = gen_viewer.subsystem_component_mermaids(parse_map(make_bridge_map()))
    s1 = by_sub["S1"]
    # The subsystem->subdomain bridge is a SYNTHESIZED arrow: it collapses a component's C→E edges into
    # its subdomain box, labelled by the COUNT of those edges (like the container arrows), never a verb.
    assert f'SD1["<span class=cyslot data-k=subdomain data-v=compact data-id=SD1></span>"]:::cy-SD1' in s1 and "C1 --> SD1" in s1   # C1 has 1 edge into SD1; the box is an item box
    s2 = by_sub["S2"]
    assert f'SD1["<span class=cyslot data-k=subdomain data-v=compact data-id=SD1></span>"]:::cy-SD1' in s2 and "C2 --> SD1" in s2   # C2 has 1 edge into SD1


def test_an_entity_diagram_draws_entities_and_subdomains_only() -> None:
    # An entity diagram draws entities and the subdomains that hold them, and nothing else. The subdomain
    # card and the entity-pair page each used to add a collapsed box for every subsystem whose components
    # touch one of those entities, which put two kinds of thing on one canvas: a reader could not tell
    # whether an arrow meant "this entity relates to that one" or "this code writes that entity".
    #
    # The fact is not lost. The subsystem card draws the same bridge from the structural side, and the
    # subsystem × subdomain page is about nothing else.
    g = parse_map(make_bridge_map())
    sd1 = gen_viewer.domain_subdomain_mermaids(g)["SD1"]
    assert 'namespace SD1[' in sd1 and 'class E1["Order"] {' in sd1     # its entities, still
    assert 'class S1["Edge"]' not in sd1 and 'class S2["Core"]' not in sd1
    assert "S1 --> E1" not in sd1 and "S2 --> E1" not in sd1
    assert gen_viewer.SUBSYSTEM_STYLE not in sd1                       # no amber box on an entity canvas
    # …and the structural side still carries it: the subsystem card draws the subdomain it writes into.
    assert f'SD1["<span class=cyslot data-k=subdomain data-v=compact data-id=SD1></span>"]' in gen_viewer.subsystem_component_mermaids(g)["S1"]


def test_subdomain_card_has_no_subsystem_box_without_bridges() -> None:
    # Regression mirror: a pure domain map (no C->E edges, no subsystems) draws no subsystem box / amber
    # styling in the subdomain card. (Neighbour SUBDOMAIN boxes are still drawn, as item boxes.)
    sd1 = gen_viewer.domain_subdomain_mermaids(parse_map(make_context_map()))["SD1"]
    assert "class S1" not in sd1
    assert gen_viewer.SUBSYSTEM_STYLE not in sd1                # no amber (subsystem) styling
    assert f"style SD2 {gen_viewer.ITEM_SLOT_STYLE}" in sd1     # neighbour subdomain IS drawn, as a shapeless slot the item box fills


def test_subsystem_card_has_no_context_box_without_bridges() -> None:
    # Regression: a map with no C->E edges draws no subdomain box / classDef in the subsystem card.
    s1 = gen_viewer.subsystem_component_mermaids(parse_map(make_card_map()))["S1"]
    assert "subdomain" not in s1


def test_bundle_carries_context_data() -> None:
    # The bundle carries the contexts overview + per-context cards, with hasSubdomains on so the Domain
    # view leads with the overview.
    b = bundle_of(make_context_map())
    assert b["hasSubdomains"] is True
    assert "data-id=SD1" in b["mermaidDomainContainer"]     # the bounded-contexts overview (item-box slots)
    assert "SD1>SD2" in b["mermaidDomainEdgeCard"]          # the subdomain edge-card (keyed by crossing pair)


def test_bundle_no_context_data_when_ungrouped() -> None:
    # A domain map with no Subdomains table: hasSubdomains is false and the flat classDiagram still ships.
    b = bundle_of(make_domain_map())
    assert b["hasSubdomains"] is False and b["mermaidDomain"]


def _two_context_map(cards_extra: str = "") -> str:
    """SD1 (Ordering, has E1) + SD2 (Catalog, EMPTY — no card assigned to it). `cards_extra` is unused
    by the surviving (kept) callers, which all take the default — a defined-but-empty SD2."""
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
      "name": "Search",
      "actors": [],
      "trigger_outcome": "types -> list"
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
  "components": [],
  "deps": [],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [
    {
      "id": "SD1",
      "name": "Ordering",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    },
    {
      "id": "SD2",
      "name": "Catalog",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    }
  ],
  "entities": [
    {
      "id": "E1",
      "name": "Order",
      "store": {"notes": "s"},
      "meaning": "m",
      "subdomain": "SD1",
      "source": "f:1",
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
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def test_gen_domain_subdomain_card_empty_context_is_valid_mermaid() -> None:
    # A defined-but-empty context must still produce a VALID classDiagram — a body-less `classDiagram`
    # crashes Mermaid on drill (the F1 regression). It carries a self-explaining placeholder instead.
    card = gen_viewer.gen_domain_subdomain_card(parse_map(_two_context_map()), "SD2")
    assert card.startswith("classDiagram") and card.strip() != "classDiagram"   # has a body
    assert "no entities" in card and "Catalog" in card
    # the placeholder id carries no prefix+digits, so the viewer's id bridge skips it (not clickable)
    assert "EmptySubdomain" in card


def make_both_groupings_map() -> str:
    """A map with BOTH groupings + the cross-altitude edges that triggered the leak: S1{C1}, S2{C2};
    SD1{E1,E2}, SD2{E3}; a C1->C2 component edge (S→S crossing), C1 persists E1 + C2 persists E3
    (C→E bridge edges), and E1 refersTo E3 (an E→E relation crossing SD1→SD2). The Subsystems overview
    must show ONLY S→S and never a SD box; the Domain overview ONLY SD→SD and never an S box."""
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
  "subsystems": [
    {
      "id": "S1",
      "name": "Edge",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    },
    {
      "id": "S2",
      "name": "Core",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    }
  ],
  "components": [
    {
      "id": "C1",
      "name": "Front",
      "subsystem": "S1",
      "purpose": "x",
      "depends_on": "C2",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "Core",
      "subsystem": "S2",
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
  "subdomains": [
    {
      "id": "SD1",
      "name": "Ordering",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    },
    {
      "id": "SD2",
      "name": "Catalog",
      "purpose": "x",
      "parent": null,
      "source": "a/",
      "confidence": "V"
    }
  ],
  "entities": [
    {
      "id": "E1",
      "name": "Order",
      "store": {"notes": "s"},
      "meaning": "m",
      "subdomain": "SD1",
      "source": "f:1",
      "fields": [
        {
          "name": "id",
          "type": "int",
          "markers": []
        },
        {
          "name": "product",
          "type": "E3",
          "markers": []
        }
      ],
      "relations": [
        {
          "verb": "contains",
          "target": "E2",
          "src_card": "1",
          "dst_card": "*",
          "display": "Line",
          "how": null
        },
        {
          "verb": "refersTo",
          "target": "E3",
          "src_card": "*",
          "dst_card": "1",
          "display": "Product",
          "how": null
        }
      ]
    },
    {
      "id": "E2",
      "name": "Line",
      "store": null,
      "meaning": "m",
      "subdomain": "SD1",
      "source": "f:2",
      "fields": [
        {
          "name": "x",
          "type": "int",
          "markers": []
        }
      ],
      "relations": []
    },
    {
      "id": "E3",
      "name": "Product",
      "store": null,
      "meaning": "m",
      "subdomain": "SD2",
      "source": "f:3",
      "fields": [
        {
          "name": "y",
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
      "verb": "calls",
      "dst": "C2",
      "why": "reach core",
      "where": "f"
    },
    {
      "src": "C1",
      "verb": "persists",
      "dst": "E1",
      "why": "store order",
      "where": "f"
    },
    {
      "src": "C2",
      "verb": "persists",
      "dst": "E3",
      "why": "store product",
      "where": "f"
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


def test_container_overview_excludes_contexts() -> None:
    # The bug class: with C→E / E→E edges present, the Subsystems overview must NOT pick up entity
    # endpoints (whose top group is a CONTEXT) and invent S→SD / SD→SD arrows that draw bare SD boxes.
    g = parse_map(make_both_groupings_map())
    mm = gen_viewer.gen_container_mermaid(g)
    assert "SD" not in mm                                  # no subdomain box / arrow leaks in
    assert "S1 --> S2" in mm                            # the real S→S crossing (C1->C2), count 1 (not inflated by C→E)
    # the Domain overview is the mirror: contexts only, no subsystem leak
    dmm = gen_viewer.gen_domain_container_mermaid(g)
    assert "SD1 --> SD2" in dmm and "S1" not in dmm and "S2" not in dmm  # SD→SD present, no subsystem box leaks in


def test_container_edges_exclude_contexts() -> None:
    ce = gen_viewer.gen_container_edges(parse_map(make_both_groupings_map()))
    assert set(ce) == {"S1>S2"}                            # only the real subsystem pair, no S>SD keys


def test_edge_cards_exclude_contexts() -> None:
    cards = gen_viewer.edge_card_mermaids(parse_map(make_both_groupings_map()))
    assert set(cards) == {"S1>S2"}                         # no spurious S>SD edge card


def test_the_entity_pair_page_draws_no_subsystem_boxes() -> None:
    # The same rule on the entity-pair page — see test_an_entity_diagram_draws_entities_and_subdomains_only.
    card = gen_viewer.domain_edge_card_mermaids(parse_map(make_both_groupings_map()))["SD1>SD2"]
    assert 'namespace SD1[' in card and 'namespace SD2[' in card
    assert 'class S1["Edge"]' not in card and 'class S2["Core"]' not in card
    assert "S1 --> E1" not in card and "S2 --> E3" not in card
    assert gen_viewer.SUBSYSTEM_STYLE not in card


def test_bridge_card_pairs_subsystem_and_subdomain() -> None:
    # The bridge card frames a subsystem and a subdomain side by side, with the component→entity edges
    # between them — the structure↔domain analog of the edge cards. Keyed 'S>SD'.
    cards = gen_viewer.bridge_card_mermaids(parse_map(make_both_groupings_map()))
    assert "S1>SD1" in cards and "S2>SD2" in cards
    card = cards["S1>SD1"]
    assert card.startswith("classDiagram")
    assert 'namespace S1["Edge"] {' in card and 'class C1["Front"]' in card    # subsystem frame + its component box
    assert 'namespace SD1[' in card and 'class E1["Order"] {' in card          # subdomain frame + entity (full, attrs)
    assert "C1 --> E1" in card and "C1 --> E1 :" not in card                   # direct C→E link: one concrete edge -> unlabelled, no count
    assert "style C1 fill:" in card                                            # component box styled (indigo)


def test_parser_hp_captures_uc_and_why() -> None:
    g = parse_map(make_gp_map())
    steps = {s["id"]: s for s in g["happy_path"]}
    assert steps["HP1"]["uc"] == "UC1" and steps["HP2"]["uc"] == "UC2"
    assert steps["HP1"]["why"] == "" and steps["HP2"]["why"] == "needs the order from HP1"
    assert "touches" not in steps["HP1"]  # the step no longer carries its own touches/story


def test_parser_captures_use_case_flows() -> None:
    g = parse_map(make_gp_map())
    flows = {cast(str, f["uc"]): f for f in g["flows"]}
    assert set(flows) == {"UC1", "UC2"}
    s1 = cast("list[dict[str, object]]", flows["UC1"]["steps"])
    assert s1[0]["src"] == "Andy" and not s1[0]["src_is_id"] and s1[0]["phrase"] == "submits the order"
    assert s1[1]["src"] == "C1" and s1[1]["dst"] == "C2" and s1[1]["src_is_id"] and s1[1]["dst_is_id"]
    assert all(st["ok"] for st in s1)


def test_hp_actors_are_one_per_distinct_driver_in_walk_order() -> None:
    # The walk's people, derived from each step's use case: one entry per DISTINCT actor, in the
    # order the walk first reaches them, each joined to the steps it drives. The Happy Path board
    # reads exactly this to know whose name stands in each break of its line.
    actors = gen_viewer.hp_actors(parse_map(make_gp_map()))
    assert [a["name"] for a in actors] == ["Andy", "Adam"]
    assert [a["aid"] for a in actors] == ["HPA0", "HPA1"]
    assert actors[0]["steps"] == [{"id": "HP1"}]
    assert actors[1]["steps"] == [{"id": "HP2"}]


def test_hp_actor_fallback_without_uc() -> None:
    # A GP step with no `*(UCn)*` tag falls back to a generic 'Actor' lifeline (no crash).
    md = """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [],
  "glossary": [],
  "use_cases": [],
  "happy_path": [
    {
      "id": "HP1",
      "uc": null,
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
  "flows": [],
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
    actors = gen_viewer.hp_actors(parse_map(md))
    assert [a["name"] for a in actors] == ["Actor"] and actors[0]["stepIdx"] == [0]


def test_hp_actors_links_roles_and_steps() -> None:
    # hp_actors mirrors the diagram's participant order/ids and joins each actor to its Roles-table
    # entry (wants + kind) and the steps it drives (stepIdx = the message positions to highlight).
    g = parse_map(make_gp_role_actor_map())
    actors = gen_viewer.hp_actors(g)
    assert len(actors) == 1
    a = actors[0]
    assert a["aid"] == "HPA0" and a["name"] == "Org admin"
    assert a["kind"] == "human" and a["wants"] == "manage"   # joined from the Roles table by name
    assert a["stepIdx"] == [0]
    assert a["steps"] == [{"id": "HP1"}]


def test_hp_actors_follow_first_appearance_order() -> None:
    # HP-actor ids follow first-appearance order across the steps, and stepIdx points at each actor's
    # messages. (Under role-ids an actor always resolves to its role, so the old "no matching Roles row"
    # variant is unexpressible — a use-case actor is a role id that must resolve.)
    actors = gen_viewer.hp_actors(parse_map(make_gp_map()))
    by_name = {a["name"]: a for a in actors}
    assert by_name["Andy"]["aid"] == "HPA0" and by_name["Adam"]["aid"] == "HPA1"
    assert by_name["Andy"]["stepIdx"] == [0] and by_name["Adam"]["stepIdx"] == [1]


def test_parser_hp_captures_first_uc_of_multi_tag() -> None:
    # A step tagged with several UCs (`*(UC1, UC2)*`) or trailing text (`*(UC3 follow-on)*`) must
    # resolve to its FIRST UC — not fall back to a generic 'Actor' lifeline (the multi-UC regression).
    md = """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [
    {"id": "R1", "name": "Org admin", "kind": "human", "wants": "", "drives": "UC1"},
    {"id": "R2", "name": "End user", "kind": "human", "wants": "", "drives": "UC3"}
  ],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "Sign in",
      "actors": ["R1"],
      "trigger_outcome": "a -> b"
    },
    {
      "id": "UC2",
      "name": "Create",
      "actors": ["R1"],
      "trigger_outcome": "a -> b"
    },
    {
      "id": "UC3",
      "name": "Renew",
      "actors": ["R2"],
      "trigger_outcome": "a -> b"
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
  "edges": [],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""
    g = parse_map(md)
    steps = {s["id"]: s for s in g["happy_path"]}
    assert steps["HP1"]["uc"] == "UC1"           # first id of the multi-UC tag
    assert steps["HP2"]["uc"] == "UC3"           # trailing text after the id is ignored
    names = [a["name"] for a in gen_viewer.hp_actors(g)]
    assert names == ["Org admin", "End user"]    # real actors, not the generic fallback


def test_hp_actor_is_use_case_actor() -> None:
    # A step IS one use case, so its driving actors are that use case's own — no separate signal.
    g = parse_map(make_gp_role_actor_map())
    assert gen_viewer._hp_actors(g, g["happy_path"][0]) == ["Org admin"]


def make_gp_two_actor_map() -> str:
    """A Happy Path whose first step realizes a use case with TWO INTERCHANGEABLE actors (either party
    can start it — the method's one legitimate multi-actor case), and whose second step is driven by
    the second of them alone. The shape that used to produce a lifeline for a person who does not
    exist, named "Org admin, Moderator"."""
    m = json.loads(make_gp_role_actor_map())
    m["roles"].append({"id": "R2", "name": "Moderator", "kind": "human",
                       "wants": "moderate", "drives": "UC22, UC23"})
    m["use_cases"][0]["actors"] = ["R1", "R2"]
    m["use_cases"].append({"id": "UC23", "name": "Ban a user", "actors": ["R2"],
                           "trigger_outcome": "a -> b"})
    m["happy_path"].append({"id": "HP2", "uc": "UC23", "why": None})
    return json.dumps(m)


def test_and_list_reads_as_plural() -> None:
    # A comma join reads as ONE long name; the conjunction is what makes two actors look like two.
    assert and_list([]) == ""
    assert and_list(["A"]) == "A"
    assert and_list(["A", "B"]) == "A and B"
    assert and_list(["A", "B", "C"]) == "A, B, and C"


def test_use_case_node_carries_actor_list_and_readable_field() -> None:
    # BOTH forms reach the frontend: the list (so a view can tell two actors from one), and the
    # readable rendering of that same list (so every view spells the conjunction identically).
    uc = cast("dict[str, object]", parse_map(make_gp_two_actor_map())["nodes"]["UC22"])
    assert uc["actors"] == ["Org admin", "Moderator"]
    assert cast("dict[str, str]", uc["fields"])["Actor"] == "Org admin and Moderator"


def test_interchangeable_actors_are_two_people_not_one_joined_name() -> None:
    # Both are real people of the walk, and the JOINED name is never one of them — that string is the
    # shape that used to draw a lifeline for somebody who does not exist. The Happy Path board stands
    # both of them in the same break of its line, reading "Org admin or Moderator".
    actors = gen_viewer.hp_actors(parse_map(make_gp_two_actor_map()))
    names = [a["name"] for a in actors]
    assert names == ["Org admin", "Moderator"]
    assert "Org admin, Moderator" not in names and "Org admin and Moderator" not in names


def test_both_interchangeable_actors_drive_the_shared_step() -> None:
    # The alternative initiator drives that step too: selecting it must light the step, and its card
    # must list it. It also resolves to a real Role, so its kind/wants come through.
    by_aid = {a["aid"]: a for a in gen_viewer.hp_actors(parse_map(make_gp_two_actor_map()))}
    assert by_aid["HPA0"]["stepIdx"] == [0]
    assert by_aid["HPA1"]["stepIdx"] == [0, 1]
    assert by_aid["HPA1"]["kind"] == "human" and by_aid["HPA1"]["wants"] == "moderate"


def test_flow_map_from_use_case() -> None:
    # A use case's walk renders as ONE picture: a box per touched element (the actor included) and an
    # arrow per ordered pair, labelled with the step numbers riding it.
    mm = gen_viewer.flow_maps(parse_map(make_gp_map()))
    s1 = mm["UC1"]
    assert s1.startswith("%%{init: {'flowchart': {'padding': 2}}}%%\nflowchart LR")
    # Each box is an empty SLOT naming its element and the variant this picture wants; the viewer
    # builds the box itself, so no name reaches the drawing's source.
    assert "data-k=role data-v=figure data-id=Andy" in s1        # the actor's box
    assert "data-k=component data-v=tight data-id=C1" in s1 \
        and "data-k=component data-v=tight data-id=C2" in s1
    assert 'FA0 -->|"1"| C1' in s1 and 'C1 -->|"2"| C2' in s1
    assert 'C2 -->|"2"| D1' in mm["UC2"]


def test_flow_element_step_phrase_wins_on_arrow() -> None:
    # An element↔element step carries its OWN action text now; the arrow shows that phrase, not the
    # shared backbone edge's label (a pair used by several steps can't be described by one edge label).
    md = make_gp_map().replace(
        '"src": "C1",\n          "dst": "C2",\n          "phrase": "",',
        '"src": "C1",\n          "dst": "C2",\n          "phrase": "hands the order to the engine",')
    step2 = next(s for s in gen_viewer.flow_narratives(parse_map(md))["UC1"] if s["n"] == 2)
    assert step2["verb"] == "hands the order to the engine" and step2["why"] == ""


def test_flow_narrative_backstop_derives_from_edge() -> None:
    # Legacy backstop only: a phrase-less element step falls back to the backbone edge (verb + why).
    narr = gen_viewer.flow_narratives(parse_map(make_gp_map()))["UC1"]
    step2 = next(s for s in narr if s["n"] == 2)
    assert step2["srcId"] == "C1" and step2["dstId"] == "C2"
    assert step2["verb"] == "calls" and step2["why"] == "reach engine"


def test_flow_narrative_backstop_prefers_why_over_verb() -> None:
    # Backstop for a phrase-less step: the card shows the edge's descriptive Why, never the terse verb —
    # for a sharp verb (reads) just as for the catch-all (uses). The step's own phrase is the normal path.
    step2 = next(s for s in gen_viewer.flow_narratives(parse_map(make_gp_map()))["UC2"] if s["n"] == 2)
    assert step2["why"] == "cache"            # sharp verb 'reads' -> still the Why beside it
    assert step2["verb"] == "reads"


def test_bundle_carries_gp_data() -> None:
    # The walk itself and its people, so the client can draw the Happy Path board, plus the flow
    # diagram behind each of its steps. The board is HTML built in the browser, so the bundle ships
    # no drawing of the walk — only the facts it is drawn from.
    b = bundle_of(make_gp_map())
    assert [s["uc"] for s in b["graph"]["happy_path"]] == ["UC1", "UC2"]
    assert all("title" not in s for s in b["graph"]["happy_path"]), "a step has no text of its own"
    assert [a["name"] for a in b["hpActors"]] == ["Andy", "Adam"]
    assert "flowchart LR" in " ".join(b["flowsMap"].values())


def test_bundle_carries_one_drawing_per_walk() -> None:
    # ONE picture per walk. A sequence diagram shipped beside it and was removed: two renderings of one
    # walk meant every rule written twice and kept in step, and the map answers strictly more.
    b = bundle_of(make_gp_map())
    assert "flowsMm" not in b
    assert set(b["flowsMap"]) == set(b["flowsNarr"])
    assert b["flowsMap"]["UC1"].startswith("%%{init: {'flowchart': {'padding': 2}}}%%\nflowchart LR")
    assert 'FA0 -->|"1"| C1' in b["flowsMap"]["UC1"]


def make_dep_kinds_map(kind_d1: str = "datastore", with_kind: bool = True) -> str:
    """A map whose T2 exercises dep Kinds: D1 is explicit (param), the rest inferred from Type. D3
    (library) + D4 (framework) are the in-process deps that fold into the Context 'Libraries' box; the
    others are external systems drawn by name. Every kept test uses the default explicit-D1 +
    Kind-column shape (the invalid-Kind and Kind-column-optional variants only served the retired
    validator tests)."""
    return """{
  "format": "coyomap-map",
  "title": "",
  "goal": "",
  "commit": null,
  "committed": null,
  "built": null,
  "roles": [
    {
      "id": "R1",
      "name": "User",
      "kind": "human",
      "wants": "use it",
      "drives": "UC1"
    }
  ],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "Use",
      "actors": ["R1"],
      "trigger_outcome": "a -> b"
    }
  ],
  "happy_path": [],
  "subsystems": [],
  "components": [
    {
      "id": "C1",
      "name": "App",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "D1",
      "source": null,
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [
    {
      "id": "D1",
      "name": "PostgreSQL",
      "kind": "datastore",
      "type": "Relational database",
      "used_for": "store",
      "where_configured": "env",
      "confidence": "V",
      "deployment_linked": false,
      "extra": {}
    },
    {
      "id": "D2",
      "name": "RabbitMQ",
      "kind": null,
      "type": "Message broker",
      "used_for": "queue",
      "where_configured": "env",
      "confidence": "V",
      "deployment_linked": false,
      "extra": {}
    },
    {
      "id": "D3",
      "name": "pydantic",
      "kind": null,
      "type": "Validation library",
      "used_for": "validate",
      "where_configured": "dep",
      "confidence": "V",
      "deployment_linked": false,
      "extra": {}
    },
    {
      "id": "D4",
      "name": "React",
      "kind": null,
      "type": "UI framework",
      "used_for": "ui",
      "where_configured": "dep",
      "confidence": "V",
      "deployment_linked": false,
      "extra": {}
    },
    {
      "id": "D5",
      "name": "Stripe",
      "kind": null,
      "type": "Payments API (SaaS)",
      "used_for": "billing",
      "where_configured": "env",
      "confidence": "V",
      "deployment_linked": false,
      "extra": {}
    },
    {
      "id": "D7",
      "name": "Docker",
      "kind": null,
      "type": "Container runtime",
      "used_for": "packaging",
      "where_configured": "dockerfile",
      "confidence": "V",
      "deployment_linked": false,
      "extra": {}
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
      "verb": "uses",
      "dst": "D1",
      "why": "x",
      "where": "f"
    },
    {
      "src": "C1",
      "verb": "uses",
      "dst": "D2",
      "why": "x",
      "where": "f"
    },
    {
      "src": "C1",
      "verb": "uses",
      "dst": "D3",
      "why": "x",
      "where": "f"
    },
    {
      "src": "C1",
      "verb": "uses",
      "dst": "D4",
      "why": "x",
      "where": "f"
    },
    {
      "src": "C1",
      "verb": "uses",
      "dst": "D5",
      "why": "x",
      "where": "f"
    },
    {
      "src": "C1",
      "verb": "uses",
      "dst": "D7",
      "why": "x",
      "where": "f"
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


def test_classify_dep_explicit_wins() -> None:
    # A valid explicit Kind cell overrides whatever the Type text would infer (case/space-insensitive).
    assert grammar.classify_dep("platform", "Relational database") == "platform"
    assert grammar.classify_dep("  Service  ", "a plain library") == "service"


def test_classify_dep_heuristic_per_kind() -> None:
    assert grammar.classify_dep("", "Relational database") == "datastore"
    assert grammar.classify_dep("", "Redis cache") == "datastore"
    assert grammar.classify_dep("", "Message broker") == "messaging"
    assert grammar.classify_dep("", "AWS SQS") == "messaging"          # distinctive beats platform 'aws'
    assert grammar.classify_dep("", "Payments API (SaaS)") == "service"
    assert grammar.classify_dep("", "Observability SaaS") == "service"
    assert grammar.classify_dep("", "Container runtime") == "platform"
    assert grammar.classify_dep("", "UI framework") == "framework"


def test_classify_dep_falls_back_to_library() -> None:
    # An unrecognised Type — and an INVALID explicit Kind — both fall back to 'library' (folds at Context).
    assert grammar.classify_dep("", "some helper utility") == "library"
    assert grammar.classify_dep("db", "totally unknown thing") == "library"


def test_parser_sets_dep_kind() -> None:
    g = parse_map(make_dep_kinds_map())
    deps = {k: v for k, v in g["nodes"].items() if v["kind"] == "dep"}
    assert deps["D1"]["dep_kind"] == "datastore"   # explicit
    assert deps["D2"]["dep_kind"] == "messaging"   # inferred
    assert deps["D3"]["dep_kind"] == "library"     # inferred -> folds
    assert deps["D4"]["dep_kind"] == "framework"   # inferred -> folds


def test_folded_libs_are_in_process_kinds_only() -> None:
    libs = gen_viewer.folded_libs(parse_map(make_dep_kinds_map()))
    assert {d["id"] for d in libs} == {"D3", "D4"}             # framework + library only
    assert {d["name"] for d in libs} == {"pydantic", "React"}


def test_context_folds_libraries_shows_systems_by_name() -> None:
    # The Context view draws external SYSTEMS by name and collapses framework/library into one box.
    mm = gen_viewer.gen_context_mermaid(parse_map(make_dep_kinds_map()))
    for ext in ("PostgreSQL", "RabbitMQ", "Stripe", "Docker"):
        assert ext in mm, ext                                 # external systems shown by name
    assert "Libraries (2)" in mm                              # the two in-process deps fold into one box
    assert "pydantic" not in mm and "React" not in mm         # ...and are NOT drawn individually
    assert "SYS -->|bundles| LIBS" in mm                      # the System bundles the fold box


def test_libs_drill_lists_folded_deps() -> None:
    mm = gen_viewer.gen_libs_mermaid(parse_map(make_dep_kinds_map()))
    assert "pydantic" in mm and "React" in mm                 # the drill-down lists every folded dep
    assert "PostgreSQL" not in mm                             # external systems are not in the Libraries view


def test_context_no_libraries_box_when_none_folded() -> None:
    # All-external deps: no fold box drawn, and the Libraries drill diagram is empty (never reached).
    md = make_dep_kinds_map().replace("Validation library", "Search index").replace("UI framework", "Object storage")
    g = parse_map(md)
    assert gen_viewer.folded_libs(g) == []
    assert "Libraries" not in gen_viewer.gen_context_mermaid(g)
    assert gen_viewer.gen_libs_mermaid(g) == ""


def test_bundle_carries_libs_fold_data() -> None:
    # The bundle carries the Libraries drill diagram + the folded-dep list, so the client can
    # preview/drill the Context fold box.
    b = bundle_of(make_dep_kinds_map())
    folded_names = [x.get("name", "") for x in b["foldedLibs"]]
    assert "pydantic" in b["mermaidLibs"] or "pydantic" in folded_names
    assert "Libraries (2)" in b["mermaidContext"]   # the fold box label in the Context diagram


# ── dependency PURPOSE buckets (seeded-open grouping axis) ────────────────────────────────────────

def test_canonical_bucket_folds_case_to_seed_spelling() -> None:
    assert grammar.canonical_bucket("  observability ") == "Observability"   # case + whitespace drift
    assert grammar.canonical_bucket("DATA & STORAGE") == "Data & storage"
    assert grammar.canonical_bucket("other") == "Other"                      # library catch-all folds too
    assert grammar.canonical_bucket("Custom Thing") == "Custom Thing"        # minted stays as authored


def test_classify_bucket_heuristic_external_vs_library() -> None:
    assert grammar.classify_bucket(False, "error monitoring", "exception capture") == "Observability"
    assert grammar.classify_bucket(False, "identity provider", "sign-in") == "Identity & access"
    assert grammar.classify_bucket(False, "unknown widget", "does a thing") == "Integrations"  # catch-all
    assert grammar.classify_bucket(True, "async Mongo driver", "storage") == "Data drivers"
    assert grammar.classify_bucket(True, "UI framework", "dashboard") == "Frontend / UI"
    assert grammar.classify_bucket(True, "misc helper", "utility") == "Other"                  # catch-all


def test_order_buckets_seeds_first_then_minted_then_catchall() -> None:
    # Seeds in seed order, minted alphabetically, the catch-all last — deterministic diagram order.
    got = grammar.order_buckets(["Integrations", "Zeta custom", "Observability", "Alpha custom",
                                 "Data & storage"], is_library=False)
    assert got == ["Data & storage", "Observability", "Alpha custom", "Zeta custom", "Integrations"]


def _bucket_model() -> ProjectModel:
    m = ProjectModel(title="Shop", format="coyomap-map")
    m.deps = [
        Dep(id="D1", name="Postgres", kind="datastore", type="Relational DB",
            used_for="Primary store, orders", bucket="Data & storage"),
        Dep(id="D2", name="Sentry", kind="service", type="error monitoring",
            used_for="Exception capture", bucket="Observability"),
        Dep(id="D3", name="Datadog", kind="service", type="metrics",
            used_for="Metrics", bucket="observability"),          # case drift -> folds into Observability
        Dep(id="D4", name="pydantic", kind="library", type="Validation library",
            used_for="Models", bucket="Validation / models"),
        Dep(id="D5", name="React", kind="framework", type="UI framework",
            used_for="Dashboard UI", bucket="Frontend / UI"),
    ]
    return m


def test_context_groups_externals_into_bucket_clusters() -> None:
    mm = gen_viewer.gen_context_mermaid(model_to_graph(_bucket_model()))
    assert 'subgraph CYBK0["Data & storage"]' in mm         # first seed present -> first cluster
    assert '["Observability"]' in mm and mm.count('["Observability"]') == 1  # D3 case-drift folds in, not a 2nd cluster
    assert "-->|\"uses\"|" not in mm                             # the repeated 'uses' label is gone
    assert "SYS --> D1" in mm                                # System still points at each dep (unlabelled)
    assert "Postgres<br/>Primary store" in mm               # name + caption from the 'Used for' lead
    assert "pydantic" not in mm and "React" not in mm       # in-process libs fold, not shown at Context


def test_libs_drill_groups_libraries_into_bucket_clusters() -> None:
    mm = gen_viewer.gen_libs_mermaid(model_to_graph(_bucket_model()))
    assert '["Validation / models"]' in mm and '["Frontend / UI"]' in mm
    assert "D4" in mm and "D5" in mm
    assert "Postgres" not in mm                              # external systems are not in the Libraries drill


def _fold_model() -> ProjectModel:
    """A map with one BIG external bucket (Observability, 5 deps → folds) and one small one
    (Data & storage, 2 deps → stays inline)."""
    m = ProjectModel(title="Big", format="coyomap-map")
    obs = [Dep(id=f"D{i}", name=f"Mon{i}", kind="service", type="monitoring",
               used_for=f"metric {i}", bucket="Observability") for i in range(1, 6)]
    data = [Dep(id="D6", name="Postgres", kind="datastore", type="SQL", used_for="store",
                bucket="Data & storage"),
            Dep(id="D7", name="Redis", kind="datastore", type="cache", used_for="cache",
                bucket="Data & storage")]
    m.deps = obs + data
    return m


def test_context_folds_all_buckets_when_any_is_large() -> None:
    # All-or-nothing: because Observability reaches the threshold, EVERY external bucket collapses into a
    # count box (uniform look) — even the small Data & storage one — and none stay inline.
    mm = gen_viewer.gen_context_mermaid(model_to_graph(_fold_model()))
    assert "Observability (5)" in mm and "Data & storage (2)" in mm  # both are count boxes
    assert "class BKF0 bucketfold" in mm and "class BKF1 bucketfold" in mm
    assert "subgraph CYBK" not in mm                        # ...no inline clusters at all
    assert "📂" not in mm and "📚" not in mm                # no folder / book icons on the containers
    assert "Mon1" not in mm and "Postgres" not in mm        # folded members are not drawn at the top altitude


def test_folded_bucket_drill_lists_only_its_members() -> None:
    g = model_to_graph(_fold_model())
    drills = gen_viewer.mermaid_by_bucketfold(g)
    assert set(drills) == {"BKF0", "BKF1"}                   # both external buckets fold, each with a drill
    obs = next(fb["id"] for fb in gen_viewer.folded_context_buckets(g) if fb["name"] == "Observability")
    d = drills[obs]
    assert "Mon1" in d and "Mon5" in d and '["Observability"]' in d
    assert "Postgres" not in d                               # only this bucket's members


def test_small_map_has_no_folds() -> None:
    g = model_to_graph(_bucket_model())                      # largest bucket = 2, under DEP_BUCKET_FOLD_AT
    assert gen_viewer.folded_context_buckets(g) == []
    mm = gen_viewer.gen_context_mermaid(g)
    assert "class BKF" not in mm and "subgraph CYBK" in mm   # nothing folds → inline clusters, no count boxes


def _library_fold_model() -> ProjectModel:
    """A map whose FOLDED libraries include a big purpose bucket (Data drivers, 5) → the Libraries drill
    folds all its buckets into drillable count boxes too."""
    m = ProjectModel(title="Libs", format="coyomap-map")
    drivers = [Dep(id=f"D{i}", name=f"drv{i}", kind="library", type="db driver",
                   used_for="io", bucket="Data drivers") for i in range(1, 6)]
    ui = [Dep(id="D6", name="React", kind="framework", type="ui", used_for="ui", bucket="Frontend / UI"),
          Dep(id="D7", name="Vite", kind="framework", type="build", used_for="build", bucket="Frontend / UI")]
    m.deps = drivers + ui
    return m


def test_library_buckets_fold_partially_in_libraries_drill() -> None:
    # Libraries are EXCLUDED from the Context view's all-or-nothing rule: the drill folds ONLY the big
    # bucket (Data drivers, 5) and leaves the small one (Frontend / UI, 2) inline — a one/two-library
    # bucket never becomes a pointless count box.
    g = model_to_graph(_library_fold_model())
    libs_mm = gen_viewer.gen_libs_mermaid(g)
    assert "Data drivers (5)" in libs_mm                     # big library bucket → drillable count box
    assert '["Frontend / UI"]' in libs_mm                    # small one STAYS an inline cluster
    assert "Frontend / UI (2)" not in libs_mm                # ...not a count box
    lib_folds = gen_viewer.folded_library_buckets(g)
    assert {fb["name"] for fb in lib_folds} == {"Data drivers"}
    roster = {r["name"]: r for r in gen_viewer.folded_buckets_roster(g)}
    assert roster["Data drivers"]["parent"] == "libs"        # a library bucket drills out of the Libraries view
    drills = gen_viewer.mermaid_by_bucketfold(g)
    drivers_id = lib_folds[0]["id"]
    assert "drv1" in drills[drivers_id]                       # the library-bucket drill lists its members


def test_context_stays_all_or_nothing() -> None:
    # The external Context buckets keep all-or-nothing: the small Data & storage (2) folds too because
    # Observability (5) crosses the threshold — the exclusion is libraries-only.
    g = model_to_graph(_fold_model())
    assert {fb["name"] for fb in gen_viewer.folded_context_buckets(g)} == {"Observability", "Data & storage"}


def test_folded_bucket_roster_synthetic_node_and_edge() -> None:
    g = model_to_graph(_fold_model())
    roster = {r["name"]: r for r in gen_viewer.folded_buckets_roster(g)}
    assert roster["Observability"]["count"] == 5 and roster["Observability"]["parent"] == "context"
    assert {m["id"] for m in roster["Observability"]["members"]} == {"D1", "D2", "D3", "D4", "D5"}
    pg: dict = {"nodes": {}}
    gen_viewer.add_context_nodes(pg, g)
    assert pg["nodes"]["BKF0"]["kind"] == "bucketfold"       # synthetic panel node so the click bridge resolves it
    assert "SYS>BKF0" in gen_viewer.gen_context_edges(g)     # the SYS→box arrow is a registered context edge


def test_a_view_only_node_id_can_never_answer_to_a_model_element_id() -> None:
    """The Context view's actor nodes were `R0, R1, …` — the model's own role id space, off by one.
    Anything that looked a model role id up in the viewer's node map got the NEXT role: a recorded
    line about the site visitor `R3` rendered as the name of the MCP client application.

    Pinned as an INVARIANT over every synthetic node, not just the actors: a view-only id must not
    be readable as a model id. `ACT<n>` also carries no underscore on purpose — mermaid names a link
    `L_<src>_<dst>_<n>`, and `R_0` (the first fix attempted) made `L_R_0_SYS_0` unparseable, silently
    unbinding the actor arrows."""
    m = ProjectModel(title="Tiny", goal="g")
    m.roles = [Role(id="R1", name="Tracker", kind="human", wants="x", drives="UC1"),
               Role(id="R2", name="Superadmin", kind="human", wants="y", drives="UC2"),
               Role(id="R3", name="Site visitor", kind="human", wants="z", drives="UC3")]
    m.use_cases = [UseCase(id="UC1", name="Track")]
    g = model_to_graph(m)
    pg: dict = {"nodes": {}}
    gen_viewer.add_context_nodes(pg, g)
    model_ids = set(all_elements(m))
    for nid in pg["nodes"]:
        assert nid not in model_ids, f"view-only node {nid} shadows a model element"
        assert not grammar.ID_TOKEN.fullmatch(nid), f"view-only node {nid} reads as a model id"
        assert not re.fullmatch(r"R\d+", nid), f"view-only node {nid} reads as a role id"
    assert [n["name"] for n in pg["nodes"].values() if n["kind"] == "human"] == [
        "Tracker", "Superadmin", "Site visitor"]
    # the actor ids the diagram and the edge cards agree on, and mermaid can split
    assert "ACT0>SYS" in gen_viewer.gen_context_edges(g)
    assert "_" not in "".join(k for k in pg["nodes"] if k.startswith("ACT"))


def test_bundle_meta_carries_built_and_pin_and_tests() -> None:
    # The header meta line states the build stamp and the commit pin, and the graph ships each tests[]
    # row with its targets resolved server-side (the Tests tab renders names + locate-links, no parsing).
    m = ProjectModel(title="Tiny", built="2026-01-02 03:04", format="coyomap-map",
                     commit="abc1234", committed="2026-01-01")
    m.use_cases = [UseCase(id="UC1", name="Login")]
    m.tests = [GapRow(targets=["UC1"], tested="yes")]
    b = gen_viewer.build_view_bundle(model_to_graph(m), VIEWER_DIR)
    assert "built 2026-01-02 03:04" in b["meta"]
    # The pin reads `commit <sha> <when>` — no "from" between them. `when` is the commit's real
    # date+time when git can resolve the sha, else the stored date (this fake sha resolves nowhere).
    assert "<code>abc1234</code> 2026-01-01" in b["meta"]
    # The `format` literal is the same on every map, so it is not in the header. The header DOES
    # name the repo folder, and a worktree named `coyomap-map-…` carries the literal by accident:
    # checked with that name blanked, so the assertion is about the format field and nothing else.
    repo_name = Path(VIEWER_DIR).resolve().parents[2].name
    assert "coyomap-map" not in b["meta"].replace(repo_name, "")
    assert b["graph"]["tests"][0]["targets"][0] == {"id": "UC1", "name": "Login", "node": "UC1"}


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception as e:  # noqa: BLE001 — test runner reports every failure
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
