#!/usr/bin/env python3
"""Tests for `coyomap score` — the deterministic MapProfile (the eval's reusable heart).

Fixtures are JSON model documents (generated once from the retired md test notation
at the Phase-3 boundary — see git history for the original markdown shorthand).

Stdlib-only — no pytest required. Run either way (needs an editable install: `make deps`):
    python3 tests/test_profile.py        # built-in runner (prints pass/fail)
    pytest tests/test_profile.py         # if pytest is installed
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from coyomap.model import ModelError
from coyomap_eval.profile import MapProfile, build_profile

SCORE = [sys.executable, "-m", "coyomap_eval.cli", "score"]


# --- fixtures (JSON model documents) -----------------------------------
def make_counts_map() -> str:
    """A map with KNOWN element counts, so the profile's structural numbers are exact:
    UC 2 · S 1 · SD 1 · C 3 · D 1 · E 2 · edges 3 · GP 3 · flows 2 · auth-surfaces 2."""
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
      "name": "View order",
      "actors": [],
      "trigger": "opens", "outcome": "sees"
    },
    {
      "id": "UC2",
      "name": "Create order",
      "actors": [],
      "trigger": "submits", "outcome": "stored"
    }
  ],
  "happy_path": [
    {
      "id": "HP1",
      "uc": "UC2",
      "why": null
    },
    {
      "id": "HP2",
      "uc": "UC1",
      "why": null
    },
    {
      "id": "HP3",
      "uc": "UC1",
      "why": null
    }
  ],
  "subsystems": [
    {
      "id": "S1",
      "name": "Ordering",
      "purpose": "",
      "parent": null,
      "source": null,
      "confidence": ""
    }
  ],
  "components": [
    {
      "id": "C1",
      "name": "Viewer",
      "subsystem": "S1",
      "purpose": "show",
      "depends_on": "E1",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "Creator",
      "subsystem": "S1",
      "purpose": "make",
      "depends_on": "E1",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C3",
      "name": "Logger",
      "subsystem": null,
      "purpose": "log",
      "depends_on": "D1",
      "source": null,
      "confidence": "",
      "extra": {}
    }
  ],
  "deps": [
    {
      "id": "D1",
      "name": "Datadog",
      "kind": "service",
      "type": "observability",
      "used_for": "",
      "where_configured": "",
      "confidence": "",
      "deployment_linked": false,
      "extra": {}
    }
  ],
  "run_commands": [],
  "entry_points": [],
  "subdomains": [
    {
      "id": "SD1",
      "name": "Orders",
      "purpose": "",
      "parent": null,
      "source": null,
      "confidence": ""
    }
  ],
  "entities": [
    {
      "id": "E1",
      "name": "Order",
      "store": {"notes": "orders"},
      "meaning": "a customer order",
      "subdomain": "SD1",
      "source": "order.py:1",
      "fields": [],
      "relations": []
    },
    {
      "id": "E2",
      "name": "Line",
      "store": {"notes": "lines"},
      "meaning": "a line item",
      "subdomain": "SD1",
      "source": "line.py:1",
      "fields": [],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [
    {
      "uc": "UC1",
      "title": "View order",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "views the order",
          "note": ""
        }
      ]
    },
    {
      "uc": "UC2",
      "title": "Create order",
      "steps": [
        {
          "n": 1,
          "src": "Adam",
          "dst": "C2",
          "phrase": "creates the order",
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
      "why": "show it",
      "where": "f#L1"
    },
    {
      "src": "C2",
      "verb": "persists",
      "dst": "E1",
      "why": "store it",
      "where": "f#L2"
    },
    {
      "src": "C3",
      "verb": "reads",
      "dst": "E2",
      "why": "log it",
      "where": "f#L3"
    }
  ],
  "deployment": [],
  "observability": [],
  "security": [
    {
      "surface": "/api/orders",
      "who": "admins",
      "source": "[require_admin](auth.py#L10)",
      "risk": "escalation"
    },
    {
      "surface": "/api/lines",
      "who": "members",
      "source": "[require_login](auth.py#L20)",
      "risk": "leak"
    }
  ],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_roles_then_usecases_map() -> str:
    """A Roles table — whose `Use cases they drive` header ALSO starts with 'use case' — sits BEFORE
    the Use-cases table. This is the layout that made `_use_case_names` return [] (review Finding 1):
    iter_tables emits the Roles table first, so a `startswith('use case')`-only predicate read it."""
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
      "name": "Andy",
      "kind": "human",
      "wants": "",
      "drives": "views orders"
    },
    {
      "id": "R2",
      "name": "Adam",
      "kind": "human",
      "wants": "",
      "drives": "creates orders"
    }
  ],
  "glossary": [],
  "use_cases": [
    {
      "id": "UC1",
      "name": "View order",
      "actors": ["R1"],
      "trigger": "opens", "outcome": "sees"
    },
    {
      "id": "UC2",
      "name": "Create order",
      "actors": ["R2"],
      "trigger": "submits", "outcome": "stored"
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
      "name": "Viewer",
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
      "title": "View order",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "views",
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


def make_broken_map() -> str:
    """An EDGE pointing at an undefined component C9 — a blocking validation problem
    (validate_ok is False).

    The reference used to be `depends_on: "C9"`, which is free-text summary prose and no reference at
    all: what actually failed this map was a malformed `entry_point` anchor ("f", not `path:line`), a
    field that no longer exists. So the fixture asserted the right thing for the wrong reason, and the
    docstring named a problem the map did not have. The edge below is the real one."""
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
      "name": "View",
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
      "name": "Viewer",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "C9",
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
      "title": "View",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "views",
          "note": ""
        }
      ]
    }
  ],
  "edges": [{"src": "C1", "verb": "calls", "dst": "C9", "why": "a dangling reference",
             "where": "src/v.py:2"}],
  "deployment": [],
  "observability": [],
  "security": [],
  "config": [],
  "tests_note": "",
  "tests": [],
  "extras": []
}"""


def make_backward_whyref_map() -> str:
    """HP1's `why:` cites HP2, which comes after it — a backward reference (audit CONTRADICTION)."""
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


def make_read_before_create_map() -> str:
    """UC1 reads the order before UC2 writes it on the Happy Path — an audit ADVISORY (the
    component-granularity attribution is lossy, so this ordering signal never blocks)."""
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
      "name": "View order",
      "actors": [],
      "trigger": "opens", "outcome": "sees"
    },
    {
      "id": "UC2",
      "name": "Create order",
      "actors": [],
      "trigger": "submits", "outcome": "stored"
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
      "name": "Viewer",
      "subsystem": null,
      "purpose": "x",
      "depends_on": "E1",
      "source": null,
      "confidence": "",
      "extra": {}
    },
    {
      "id": "C2",
      "name": "Creator",
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
      "name": "Order",
      "store": {"notes": "orders"},
      "meaning": "a customer order",
      "subdomain": null,
      "source": "order.py:1",
      "fields": [],
      "relations": []
    }
  ],
  "non_entity_types": [],
  "flows": [
    {
      "uc": "UC1",
      "title": "View order",
      "steps": [
        {
          "n": 1,
          "src": "Andy",
          "dst": "C1",
          "phrase": "views the order",
          "note": ""
        }
      ]
    },
    {
      "uc": "UC2",
      "title": "Create order",
      "steps": [
        {
          "n": 1,
          "src": "Adam",
          "dst": "C2",
          "phrase": "creates the order",
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
      "why": "show it",
      "where": "f#L1"
    },
    {
      "src": "C2",
      "verb": "persists",
      "dst": "E1",
      "why": "store it",
      "where": "f#L2"
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


def make_single_use_case_map() -> str:
    """A single use case, no components — used where the profile must show density as None."""
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
      "name": "View",
      "actors": [],
      "trigger": "a", "outcome": "b"
    }
  ],
  "happy_path": [],
  "subsystems": [],
  "components": [],
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


def run_score(map_text: str, *extra: str) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(map_text)
        path = f.name
    r = subprocess.run([*SCORE, path, *extra], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# --- structure counts (the deterministic core) ----------------------------------
def test_structure_counts_are_exact() -> None:
    p = build_profile(make_counts_map())
    assert (p.use_cases, p.subsystems, p.subdomains, p.components, p.deps, p.entities) == (2, 1, 1, 3, 1, 2), p
    assert (p.edges, p.hp_steps, p.flows, p.security_surfaces) == (3, 3, 2, 2), p


def test_flow_granularity_fields() -> None:
    # authored step counts — a sub-flow reference counts as 1; band = FLOW_STEPS_HI (15)
    p = build_profile(make_counts_map())
    assert p.subflows == 0
    assert p.max_flow_len == 1 and p.flows_over_band_pct == 0.0, p


def test_old_baseline_without_granularity_fields_loads() -> None:
    # a profile written before the fields existed loads with None defaults (from_json filters)
    p = build_profile(make_counts_map())
    d = json.loads(p.to_json())
    for k in ("subflows", "max_flow_len", "flows_over_band_pct"):
        d.pop(k)
    old = MapProfile.from_json(json.dumps(d))
    assert old.subflows is None and old.max_flow_len is None and old.flows_over_band_pct is None


def test_completeness_fields_on_the_counts_map() -> None:
    p = build_profile(make_counts_map())
    assert p.entry_points == 0 and p.external_entry_points == 0, p
    assert p.unclaimed_entry_points is None  # no entry points → the signal is not computable
    assert p.off_spine_ucs == 0, p  # UC1 and UC2 both hold HP positions


def test_unclaimed_entry_points_counts_raw_pre_escape() -> None:
    # An external EP owned by C3 (in no flow) counts as unclaimed even when the map records the
    # 'Unclaimed surfaces' escape — the escape silences the validate WARNING, but the profile
    # keeps the raw drift signal (same convention as flows_over_band_pct vs 'Balance exceptions').
    d = json.loads(make_counts_map())
    d["entry_points"] = [
        {"kind": "http", "trigger": "GET /orders", "source": "src/x.py:1",
         "component": "C1", "activation": "external"},          # C1 is in a flow → claimed
        {"kind": "http", "trigger": "GET /debug", "source": "src/x.py:2",
         "component": "C3", "activation": "external"},          # C3 is in no flow → unclaimed
        {"kind": "cron", "trigger": "nightly sweep", "source": "src/x.py:3",
         "component": "C3", "activation": "self"},              # self-activated → exempt
        {"kind": "http", "trigger": "GET /mount", "source": "src/x.py:4",
         "component": "C3", "activation": "mounted"},           # invalid → kind says external
    ]
    d["extras"] = [{"heading": "Unclaimed surfaces", "body": "C3: ops surface, deliberate."}]
    p = build_profile(json.dumps(d))
    assert p.entry_points == 4 and p.external_entry_points == 3, p
    assert p.unclaimed_entry_points == 2, p


def test_stepped_and_named_entry_points_read_the_way_in_grain() -> None:
    # The unclaimed count is component-grain: one flow through C1 claims every way in C1 owns. Two
    # report-only fields split that claim by evidence — a way in some flow step is anchored ON
    # (within 3 lines of its `source`) is RUN; a way in a use case NAMES is the authored arm. Both
    # raw, and both None when the signal is not computable (no entry points).
    d = json.loads(make_counts_map())
    d["flows"][0]["steps"][0]["where"] = "src/x.py:1"         # the UC1 step, anchored
    d["entry_points"] = [
        {"id": "EP1", "kind": "http", "trigger": "GET /orders", "source": "src/x.py:3",
         "component": "C1", "activation": "external"},        # 2 lines from that step → run
        {"id": "EP2", "kind": "http", "trigger": "GET /orders/{id}", "source": "src/x.py:9",
         "component": "C1", "activation": "external"},        # C1 is in a flow, no step near
    ]
    d["use_cases"][0]["entry_points"] = ["EP2"]
    p = build_profile(json.dumps(d))
    assert p.external_entry_points == 2 and p.unclaimed_entry_points == 0, p
    assert p.stepped_entry_points == 1 and p.named_entry_points == 1, p
    assert p.storyless_entry_points == 0, p          # EP1 run, EP2 named: nothing storyless
    p0 = build_profile(make_counts_map())
    assert p0.stepped_entry_points is None and p0.named_entry_points is None, p0
    assert p0.storyless_entry_points is None, p0


def test_off_spine_ucs_is_none_without_a_happy_path() -> None:
    d = json.loads(make_counts_map())
    d["happy_path"] = []
    p = build_profile(json.dumps(d))
    assert p.off_spine_ucs is None, p


def test_entities_in_flows_zero_when_flows_never_touch_them() -> None:
    # the fixture has entities + flows but no E-endpoint step: traced-and-zero, NOT None
    # (the canary deliberately adds one validate warning on this shape — report-only here)
    p = build_profile(make_counts_map())
    assert p.entities_in_flows == 0 and p.entities_in_flows_pct == 0.0, p


def test_entities_in_flows_counts_expanded_step_endpoints() -> None:
    # one direct entity step + one reachable ONLY through a sub-flow reference — the count walks
    # expanded steps, so both entities register (2 of 2)
    d = json.loads(make_counts_map())
    d["flows"][0]["steps"].append({"n": 2, "src": "C1", "dst": "E1",
                                   "phrase": "persists the order", "where": "src/a.py:9"})
    d["subflows"] = [{"id": "SF1", "name": "Line persist",
                      "steps": [{"n": 1, "src": "C2", "dst": "E2",
                                 "phrase": "writes the line", "where": "src/b.py:3"}]}]
    d["flows"][1]["steps"].append({"n": 2, "src": "C2", "dst": "C2", "subflow": "SF1"})
    p = build_profile(json.dumps(d))
    assert p.entities_in_flows == 2 and p.entities_in_flows_pct == 100.0, p


def test_entities_in_flows_is_none_without_entities_or_flows() -> None:
    d = json.loads(make_counts_map())
    d["flows"] = []
    p = build_profile(json.dumps(d))
    assert p.entities_in_flows is None and p.entities_in_flows_pct is None, p
    d = json.loads(make_counts_map())
    d["entities"] = []
    p = build_profile(json.dumps(d))
    assert p.entities_in_flows is None and p.entities_in_flows_pct is None, p


def test_old_baseline_without_completeness_fields_loads() -> None:
    p = build_profile(make_counts_map())
    d = json.loads(p.to_json())
    for k in ("entry_points", "external_entry_points", "unclaimed_entry_points", "off_spine_ucs",
              "entities_in_flows", "entities_in_flows_pct",
              "stepped_entry_points", "named_entry_points", "storyless_entry_points"):
        d.pop(k)
    old = MapProfile.from_json(json.dumps(d))
    assert old.entry_points is None and old.unclaimed_entry_points is None
    assert old.stepped_entry_points is None and old.named_entry_points is None
    assert old.storyless_entry_points is None
    assert old.external_entry_points is None and old.off_spine_ucs is None
    assert old.entities_in_flows is None and old.entities_in_flows_pct is None


def test_concept_name_sets_are_captured() -> None:
    p = build_profile(make_counts_map())
    assert p.auth_surfaces == ["/api/orders", "/api/lines"], p.auth_surfaces
    assert p.use_case_names == ["View order", "Create order"], p.use_case_names
    assert p.entity_names == ["Order", "Line"], p.entity_names


def test_use_case_names_survive_a_roles_table_before_them() -> None:
    """Regression guard (review Finding 1, model edition): a Roles table before the Use-cases table
    must not shadow the use-case NAMES — the model stores them first-class, so they always survive."""
    p = build_profile(make_roles_then_usecases_map())
    assert p.use_case_names == ["View order", "Create order"], p.use_case_names


# --- well-formedness (reuses validate_model) ------------------------------------
def test_broken_map_is_not_validate_ok() -> None:
    p = build_profile(make_broken_map())
    assert p.validate_ok is False and p.validate_problems > 0, p


def test_markdown_map_is_refused() -> None:
    """A non-model document raises ModelError (a normal JSON parse failure), never a silent
    zero-profile."""
    try:
        build_profile("## Use cases\n| **UC1** | View | Andy | a -> b |\n")
        raise AssertionError("expected ModelError")
    except ModelError as e:
        assert "not valid JSON" in str(e)


# --- self-consistency (reuses audit) --------------------------------------------
def test_backward_why_ref_shows_up_as_a_contradiction() -> None:
    p = build_profile(make_backward_whyref_map())
    assert p.contradictions == 1, p


def test_read_before_create_shows_up_as_an_advisory() -> None:
    """The current audit rates a read-then-write ordering ADVISORY, not blocking — the profile counts
    it under `advisories`, leaving `contradictions` clean."""
    p = build_profile(make_read_before_create_map())
    assert p.audit_advisories >= 1 and p.contradictions == 0, p


def test_l2_claims_counts_security_surfaces() -> None:
    """Each Security & auth row is an L2 claim to ground — the counts_map has two surfaces."""
    p = build_profile(make_counts_map())
    assert p.l2_claims >= 2, p


# --- density (P1) ----------------------------------------------------------------
def test_edges_per_component_is_the_density_ratio() -> None:
    p = build_profile(make_counts_map())  # 3 edges / 3 components
    assert p.edges_per_component == 1.0, p


def test_density_is_none_when_there_are_no_components() -> None:
    p = build_profile(make_single_use_case_map())
    assert p.edges_per_component is None, p


# --- coverage (needs the repo) --------------------------------------------------
def test_coverage_is_none_without_repo_and_int_with_repo() -> None:
    p_no = build_profile(make_counts_map())
    assert p_no.coverage_flags is None, p_no
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "order.py").write_text("x = 1\n", encoding="utf-8")
        (Path(d) / "line.py").write_text("y = 2\n", encoding="utf-8")
        p_yes = build_profile(make_counts_map(), repo_root=Path(d))
    assert isinstance(p_yes.coverage_flags, int), p_yes


# --- granularity (the code-derived expectation E, needs the repo) ----------------
def test_granularity_expected_is_none_without_repo_and_e_with_repo() -> None:
    p_no = build_profile(make_counts_map())
    assert p_no.granularity_expected is None, p_no
    with tempfile.TemporaryDirectory() as d:
        # a subsystem-shaped tree with a known E: 6 small plugin dirs + a small core dir → 7
        for i in range(6):
            sub = Path(d) / "plugins" / f"p{i}"
            sub.mkdir(parents=True)
            for j in range(3):
                (sub / f"f{j}.py").write_text("x\n" * 100, encoding="utf-8")
        core = Path(d) / "core"
        core.mkdir()
        (core / "a.py").write_text("x\n" * 60, encoding="utf-8")
        p_yes = build_profile(make_counts_map(), repo_root=Path(d))
    assert p_yes.granularity_expected == 7, p_yes.granularity_expected


def test_granularity_expected_is_none_on_a_tree_with_no_source() -> None:
    """A repo with no component-forming source anchors nothing — None, not a fake 0/1 gate."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "README.md").write_text("docs only\n" * 50, encoding="utf-8")
        p = build_profile(make_counts_map(), repo_root=Path(d))
    assert p.granularity_expected is None, p.granularity_expected


# --- serialization round-trip ---------------------------------------------------
def test_profile_json_round_trips() -> None:
    p = build_profile(make_counts_map())
    assert MapProfile.from_json(p.to_json()) == p


# --- CLI ------------------------------------------------------------------------
def test_score_cli_prints_profile_and_exits_zero() -> None:
    code, out = run_score(make_counts_map())
    assert code == 0, out
    assert "Map profile" in out and "structure" in out, out


def test_score_cli_json_is_parseable() -> None:
    code, out = run_score(make_counts_map(), "--json")
    assert code == 0, out
    assert MapProfile.from_json(out).use_cases == 2, out


def test_score_cli_missing_file_errors() -> None:
    r = subprocess.run([*SCORE, "/no/such/map.md"], capture_output=True, text=True)
    assert r.returncode == 1 and "not found" in (r.stdout + r.stderr)


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


def test_a_pre_rename_profile_is_refused_with_an_explanation():
    """`advisories` counted AUDIT advisories only, while sitting beside `validate_warnings` — on a
    map `finalize` called "12 advisory" it read 0, and a retrospective quoted it as "no advisories".
    The rename has no alias by decision, so an old baseline must fail legibly rather than either
    loading as 0 or dying on a bare TypeError."""
    import json
    import pytest
    from coyomap_eval.profile import MapProfile
    old = {"advisories": 3, "components": 10, "contradictions": 0}
    with pytest.raises(ValueError) as e:
        MapProfile.from_json(json.dumps(old))
    assert "audit_advisories" in str(e.value) and "re-bless" in str(e.value)


def make_replicated_shapes_map() -> str:
    """Three deployment units hosting the IDENTICAL component set — a monolith in three shapes —
    plus one unit hosting nothing, and one component placed nowhere."""
    return json.dumps({
        "format": "coyomap-map", "title": "", "goal": "", "commit": None, "committed": None,
        "built": None, "roles": [], "glossary": [], "use_cases": [], "happy_path": [],
        "subsystems": [], "deps": [], "entry_points": [], "subdomains": [], "entities": [],
        "flows": [], "subflows": [], "edges": [], "messaging": [], "environments": [],
        "observability": [], "security": [], "config": [], "tests": [], "extras": [],
        "components": [
            {"id": "C1", "name": "Api", "purpose": "p", "source": "a.py:1",
             "runs_in": ["backend", "standalone", "e2e shard"]},
            {"id": "C2", "name": "Svc", "purpose": "p", "source": "b.py:1",
             "runs_in": ["backend", "standalone", "e2e shard"]},
            {"id": "C3", "name": "Web", "purpose": "p", "source": "c.tsx:1"},
        ],
        "deployment": [{"unit": "backend"}, {"unit": "standalone"}, {"unit": "e2e shard"},
                       {"unit": "nginx"}],
    })


def test_distinct_hosted_sets_sees_through_replicated_deployment_shapes():
    """`deployment_units_linked` counts three here and reads as good coverage. It is ONE placement
    decision wearing three names, and a fourth shape would raise the number again without placing a
    single new component."""
    p = build_profile(make_replicated_shapes_map())
    assert p.deployment_units == 4
    assert p.deployment_units_linked == 3
    assert p.deployment_distinct_hosted_sets == 1, "three shapes of one process are one set"


def test_distinct_hosted_sets_counts_genuinely_different_placements():
    doc = json.loads(make_replicated_shapes_map())
    doc["components"][2]["runs_in"] = ["nginx"]
    p = build_profile(json.dumps(doc))
    assert p.deployment_units_linked == 4
    assert p.deployment_distinct_hosted_sets == 2, "the monolith set, and nginx's own"


def test_distinct_hosted_sets_counts_entry_point_placement_too():
    """`deployment_units_linked` counts a unit named by a component OR an entry point's `runs_in`,
    and the two numbers are read side by side. Counting only components made a map that places its
    frontend via entry points score `linked > 0` with `distinct_sets == 0` — which passed the gate
    vacuously and suppressed the note explaining the gap."""
    doc = json.loads(make_replicated_shapes_map())
    doc["entry_points"] = [{"kind": "ui-route", "trigger": "/", "source": "c.tsx:9",
                            "component": "C3", "runs_in": ["nginx"]}]
    p = build_profile(json.dumps(doc))
    assert p.deployment_units_linked == 4, "nginx is linked through the entry point"
    assert p.deployment_distinct_hosted_sets == 2, "the monolith set, and nginx's entry point"


def make_auth_sites_map() -> str:
    """An access surface addressed by LOCATION: two access rules, one with two sites and one whose
    single site is `no_call_site` (enforced by construction, so it has no line to compare), plus a
    legacy `security[]` row carrying its own anchor. A NON-access rule's site must not appear."""
    return """{
  "format": "coyomap-map",
  "title": "", "goal": "", "commit": null, "committed": null, "built": null,
  "roles": [], "glossary": [], "use_cases": [], "subsystems": [], "subdomains": [],
  "components": [], "deps": [], "entities": [], "edges": [], "happy_path": [], "flows": [],
  "entry_points": [], "run_commands": [], "deployment": [], "observability": [],
  "config": [], "tests": [], "extras": [], "capabilities": [], "blocks": [],
  "security": [
    {"surface": "legacy row", "who": "admin", "source": "legacy/gate.py:7", "risk": "r"}
  ],
  "rules": [
    {"id": "BR1", "name": "Owner-only cancellation", "statement": "only the owner may cancel",
     "access": true, "risk": "anyone cancels", "confidence": "verified",
     "sites": [{"where": "orders/api.py:40", "why": "checks the owner"},
               {"where": "orders/service.py:88", "why": "re-checks on the write path"}]},
    {"id": "BR2", "name": "Schema-enforced tenancy", "statement": "every row carries its org",
     "access": true, "risk": "cross-tenant read", "confidence": "verified",
     "sites": [{"why": "enforced by the schema", "no_call_site": true}]},
    {"id": "BR3", "name": "Empty list returns early", "statement": "an empty list returns early",
     "access": false, "confidence": "verified",
     "sites": [{"where": "orders/api.py:12", "why": "not an access decision"}]}
  ]
}"""


def test_auth_sites_collects_every_anchored_access_location() -> None:
    """Both storages, deduped and sorted. The legacy row's own anchor counts: a map built before the
    security-to-rules fold keeps its surface there, and the comparison must not read that as zero."""
    p = build_profile(make_auth_sites_map())
    assert p.auth_sites == ["legacy/gate.py:7", "orders/api.py:40", "orders/service.py:88"]


def test_auth_sites_excludes_a_site_with_no_line_to_compare() -> None:
    """`no_call_site` is a declared absence, not a gap — it has no location, so it cannot take part
    in a location comparison. It still counts as a SURFACE, which is what `auth_surfaces` holds."""
    p = build_profile(make_auth_sites_map())
    assert not any("schema" in a for a in p.auth_sites or [])
    assert len(p.auth_surfaces) == 3          # two access rules + the legacy row


def test_auth_sites_ignores_a_non_access_rule() -> None:
    """A rule that does not govern who-may-do-what is not part of the auth surface, however well
    anchored. `orders/api.py:12` belongs to BR3 and must not appear."""
    p = build_profile(make_auth_sites_map())
    assert "orders/api.py:12" not in (p.auth_sites or [])


def test_old_baseline_without_auth_sites_loads_as_none() -> None:
    """A profile blessed before the field must still load, and must read None rather than [] — the
    comparison distinguishes "no data" from "no sites", and [] would read as agreement."""
    p = build_profile(make_counts_map())
    text = p.to_json().replace('"auth_sites"', '"retired_field"')
    assert MapProfile.from_json(text).auth_sites is None


# --- the door counts -----------------------------------------------------------------------------
# Both had ZERO coverage until an adversarial review said so, and a mutation dropping half the
# actor definition passed the whole suite because of it.

def _door_map(steps: str, roles: str) -> str:
    return ("""{"format": "coyomap-map", "title": "D", "goal": "g",
  "roles": [%s],
  "use_cases": [{"id": "UC1", "name": "Do it", "actors": ["R1"]}],
  "happy_path": [{"id": "HP1", "uc": "UC1"}],
  "components": [{"id": "C1", "name": "Viewer", "purpose": "shows"}],
  "interfaces": [{"id": "I1", "name": "CLI", "what": "How a person runs it.", "side": "ours",
                  "kind": "command-line", "facing": "user", "source": "src/v.py:1"}],
  "flows": [{"uc": "UC1", "title": "Do it", "steps": [%s]}]}""" % (roles, steps))


PERSON = '{"id": "R1", "name": "Andy", "kind": "human", "audience": "user", "wants": "x"}'
TIMER = '{"id": "R1", "name": "Upkeep job", "kind": "service", "audience": "internal", "wants": "x"}'
OPERATOR = '{"id": "R1", "name": "Operator", "kind": "human", "audience": "internal", "wants": "x"}'
BARE = '{"n": 1, "src": "R1", "dst": "C1", "phrase": "asks"}'
#: A door carries NO `direction` — a role at a surface is a human action with no product end. The
#: step INTO the code does, and it is `in`: the surface hands inward what it received.
DOORED = ('{"n": 1, "src": "R1", "dst": "I1", "phrase": "opens it"},'
          '{"n": 2, "src": "I1", "dst": "C1", "phrase": "asks", "where": "src/v.py:3",'
          ' "direction": "in"}')


def test_an_undoored_crossing_is_counted_and_a_doored_one_is_not():
    assert build_profile(_door_map(BARE, PERSON)).crossings_without_a_door == 1
    p = build_profile(_door_map(DOORED, PERSON))
    assert p.crossings_without_a_door == 0
    assert p.interface_doors == 2


def test_the_products_OWN_timer_owes_no_door_but_an_internal_HUMAN_does():
    """The eval must use the validator's OWN definition of an actor. Three copies of it existed once
    and two disagreed; a mutation dropping the `service` half hid 46 of 140 findings on one map."""
    assert build_profile(_door_map(BARE, TIMER)).crossings_without_a_door == 0
    assert build_profile(_door_map(BARE, OPERATOR)).crossings_without_a_door == 1


def test_both_door_counts_read_SUB_FLOWS_as_well_as_flows():
    """`interface_doors` counted flows only while `crossings_without_a_door` counted both, and the
    retro tells a reader to read the pair together. A map doored entirely inside shared machinery
    scored 0 and 0, which that page reads as "authored and never put into a story"."""
    doc = json.loads(_door_map(BARE, PERSON))
    doc["flows"][0]["steps"] = [{"n": 1, "src": "C1", "dst": "C1", "phrase": "runs it",
                                 "subflow": "SF1"}]
    doc["subflows"] = [{"id": "SF1", "name": "Ask", "steps": [
        {"n": 1, "src": "R1", "dst": "I1", "phrase": "opens it"},
        {"n": 2, "src": "I1", "dst": "C1", "phrase": "asks", "where": "src/v.py:3"}]}]
    p = build_profile(json.dumps(doc))
    assert p.interface_doors == 2, "the doors live in the sub-flow and must still be counted"
    assert p.crossings_without_a_door == 0


def _recorded_door_map(steps: str, roles: str, record: str) -> str:
    """`_door_map` plus an 'Interface exceptions' extras heading carrying one recorded line — the
    adjudication `validate` honours for the doors gate."""
    doc = json.loads(_door_map(steps, roles))
    doc["extras"] = [{"heading": "Interface exceptions", "body": record}]
    return json.dumps(doc)


def test_a_recorded_crossing_still_counts_RAW_and_is_no_longer_UNADJUDICATED():
    """`validate` honours a `UCn/doors: <why>` record and the profile did not, so a map `validate`
    reported 0 owed on came back reading 1 — and Step 1c of the retro method treats "above 0" as a
    defect with no adjudicated state to land in. Both numbers now travel: the raw count is the drift
    signal (an adjudication must not erase the trend), the owed count is what the operator owes."""
    p = build_profile(_recorded_door_map(
        BARE, PERSON, "UC1/doors: the operator stands at the code host, pushing a branch"))
    assert p.crossings_without_a_door == 1, "the crossing is still there to be counted"
    assert p.crossings_without_a_door_unadjudicated == 0, "and it has been answered for"


def test_an_unanswered_crossing_stays_unadjudicated_and_another_record_does_not_answer_it():
    """The escape must be SCOPED. A record about another story, or about another gate of this one,
    leaves the crossing owed — an escape that silences more than it names is the failure the whole
    `UCn/<scope>` token shape exists to prevent."""
    bare = build_profile(_door_map(BARE, PERSON))
    assert (bare.crossings_without_a_door, bare.crossings_without_a_door_unadjudicated) == (1, 1)
    for record in ("UC9/doors: another story entirely", "UC1/migration: a different gate"):
        p = build_profile(_recorded_door_map(BARE, PERSON, record))
        assert p.crossings_without_a_door_unadjudicated == 1, record


def test_a_bare_use_case_record_answers_the_crossing_too():
    """`validate`'s own rule: a bare `UCn` excuses the whole retrofit family, the scoped form one
    gate. The profile reads the same two tokens, so the two instruments cannot disagree."""
    p = build_profile(_recorded_door_map(BARE, PERSON, "UC1: the whole story is excused"))
    assert (p.crossings_without_a_door, p.crossings_without_a_door_unadjudicated) == (1, 0)


def test_a_profile_written_before_the_unadjudicated_count_reads_none_not_zero():
    """0 is the CLEAN value here, so a missing field must not read as "nothing owed" — the same rule
    `deployment_orphan_units` states, and for the same reason."""
    p = build_profile(_door_map(BARE, PERSON))
    text = p.to_json().replace('"crossings_without_a_door_unadjudicated"', '"retired_field"')
    assert MapProfile.from_json(text).crossings_without_a_door_unadjudicated is None


def test_a_step_naming_an_UNDEFINED_surface_is_not_counted_as_a_door():
    """The eval read the id SHAPE while the validator read the DEFINED ids, so a dangling `I99` was
    doored for one instrument and undoored for the other."""
    doc = json.loads(_door_map('{"n": 1, "src": "R1", "dst": "I99", "phrase": "opens it"}', PERSON))
    p = build_profile(json.dumps(doc))
    assert p.interface_doors == 0, "an undefined surface is a dangling reference, not a door"
    assert p.crossings_without_a_door == 1


def test_the_profile_places_each_access_site_in_its_function_from_the_preindex_beside_the_map() -> None:
    """The pre-index committed beside a map carries every definition's extent; with the map's PATH
    the profile names the function holding each enforcement line, and a line with no extent keeps
    its `path:line` spelling. Without the path the field is None, never an empty list."""
    import json as _json
    import tempfile
    from pathlib import Path as _P
    from coyomap.model import FORMAT
    from coyomap_eval.profile import build_profile
    doc = {"format": FORMAT, "title": "t", "goal": "g",
           "components": [{"id": "C1", "name": "A", "purpose": "a", "source": "a.py:1"}],
           "rules": [{"id": "BR1", "statement": "Only admins delete", "block": "BLK1", "access": True,
                      "risk": "r", "sites": [{"where": "a.py:12", "why": "the check"},
                                              {"where": "z.py:3", "why": "no extent here"}]}],
           "interfaces": [{"id": "I1", "name": "Dashboard", "kind": "web-ui"},
                          {"id": "I2", "name": "Mail", "kind": "handoff"}]}
    with tempfile.TemporaryDirectory() as td:
        mp = _P(td) / "project-map.json"
        mp.write_text(_json.dumps(doc), encoding="utf-8")
        (_P(td) / "preindex.json").write_text(_json.dumps(
            {"symbols": {"extents": {"a.py": [[10, 20, "delete_team", "def"]]}}}), encoding="utf-8")
        p = build_profile(mp.read_text(encoding="utf-8"), map_path=mp)
        assert p.auth_functions == ["a.py::delete_team", "z.py"], p.auth_functions   # a site outside every function keys on its FILE
        assert p.interface_kinds and p.interface_kinds.get("handoff") == 1, p.interface_kinds
        assert build_profile(mp.read_text(encoding="utf-8")).auth_functions is None
