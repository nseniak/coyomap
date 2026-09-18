#!/usr/bin/env python3
"""Derived: the map's DATA AREAS and how hard each feature's walks reach them.

Its own module, and not part of `features.py`, for one reason: `validate` cross-examines the
authored `owners` against these touches, and `features.py` imports `validate_model` for the rule
join — so the derivation both of them read has to sit below both. The alternative was a second
implementation inside `validate`, and two implementations of "which feature touches this data" is
exactly how a map ends up answering the same question two ways on two screens.

The split this module holds:

- WHAT A FEATURE TOUCHES is DERIVED and factual — a step side of one of its use-case walks landing
  on a saved record. It is evidence, never an answer.
- WHAT A FEATURE OWNS is AUTHORED (`Group.owners`). Every derivation of ownership was measured on
  three live maps and each guessed from what the code touches, which is not what the data is FOR:
  snapshots are first written by Page tracking, but they exist so Change detection can compare them.

Keeping the two apart is what lets `validate` REPORT their disagreement instead of hiding it.

Stdlib-only (the cli.py firewall)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from coyomap.model import ProjectModel, expanded_flow_steps, is_saved, subdomain_owners


def sorted_ids(ids: "set[str]") -> list[str]:
    """Ids in id order (`C9` before `C10`), so a rendered list never reads as shuffled."""
    def key(i: str) -> tuple[str, int, str]:
        head = i.rstrip("0123456789")
        tail = i[len(head):]
        return (head, int(tail) if tail else 0, i)
    return sorted(ids, key=key)


@dataclass(frozen=True)
class AreaTouch:
    """One (feature, data area) pair: how hard that feature's walks reach the area's saved records.

    DERIVED and factual — it says what the code TOUCHES, which is deliberately NOT the same question
    as who OWNS the area (`Group.owners`, authored). Keeping the two apart is the whole design: the
    touch count is the evidence `validate` cross-examines the authored answer with, and the evidence
    the Features page draws its reference arrows from."""
    feature: str              # CAPn
    area: str                 # SDn
    touches: int              # step sides landing on a saved record of the area
    entities: list[str]       # the saved records it reached, id order


@dataclass(frozen=True)
class DataArea:
    """One sub-domain holding SAVED records — a box in the Features page's right column.

    A sub-domain whose types are all plumbing (a request shape, an enum, a read projection) is not
    an area: there is no saved data for a feature to own, so it neither draws nor gets asked the
    ownership question. `is_saved` is that filter."""
    id: str                             # SDn
    name: str
    purpose: str = ""                   # the area's own sentence — the box reads like every other
                                        # card on the page (name, sentence, counts), and without it
                                        # the reader has to open the area to learn what it holds
    entities: list[str] = field(default_factory=list)     # the SAVED records it holds, id order
    owners: list[str] = field(default_factory=list)       # the EFFECTIVE authored owners (its own,
                                                          # else inherited); [] = nobody decided
    touched_by: list[AreaTouch] = field(default_factory=list)   # most touches first, then id order



def build_areas(m: ProjectModel, column: Sequence[str] = ()) -> list[DataArea]:
    """The data areas and who touches them — the ONE derivation both the Features page's right
    column and `validate`'s cross-examination of `owners` read.

    An area is a sub-domain holding at least one SAVED record (`is_saved`). A touch is one step side
    of one of a feature's use-case walks landing on such a record, sub-flows EXPANDED so work done
    inside a shared sequence still counts for the feature that rides it. Counting sides, not steps,
    is deliberate: a step writing one record and reading another is two facts about the data.

    Order is fixed HERE, never in the browser: an area sits at the position of the FIRST feature in
    `column` (the story order the feature pillar draws) whose walks reach it — the moment the data
    is introduced, reading the product's story top to bottom. So the right column reads in the same
    direction as the pillar beside it, and an area appears level with the feature that first needs
    it rather than with whoever happens to own it.
    Deliberately NOT ordered by the OWNER's position: ownership is authored and most maps do not
    carry it yet, so an owner-driven order would rearrange the column the day someone fills the
    field in, and would leave every undecided area in a heap at the bottom. First reference is a
    derived fact, present on every map, and it is the order a reader is already following.
    An area no walk reaches has no introduction; it goes last, in map order. `column` is optional —
    `validate` asks the same question with no screen to order, and passes nothing."""
    cap_ids = {c.id for c in m.capabilities}
    uc_cap = {u.id: u.capability for u in m.use_cases if u.capability in cap_ids}
    saved_area: dict[str, str] = {}          # saved entity -> the sub-domain holding it
    area_entities: dict[str, list[str]] = {}
    subs = {g.id: g for g in m.subdomains}
    for e in m.entities:
        if is_saved(e) and e.subdomain in subs:
            saved_area[e.id] = e.subdomain   # type: ignore[assignment]
            area_entities.setdefault(e.subdomain, []).append(e.id)  # type: ignore[arg-type]
    if not area_entities:
        return []

    counts: dict[tuple[str, str], int] = {}          # (feature, area) -> touches
    hit: dict[tuple[str, str], set[str]] = {}        # (feature, area) -> the records reached
    for f in m.flows:
        cap = uc_cap.get(f.uc)
        if not cap:
            continue
        for st in expanded_flow_steps(m, f):
            for side in (st.src, st.dst):
                area = saved_area.get(side)
                if area is None:
                    continue
                counts[(cap, area)] = counts.get((cap, area), 0) + 1
                hit.setdefault((cap, area), set()).add(side)

    owners_of = subdomain_owners(m)      # EFFECTIVE: a decision on a parent area covers its children
    pos = {c: i for i, c in enumerate(column)}
    areas = []
    for sid, ents in area_entities.items():
        owners = owners_of.get(sid, [])
        touched = sorted((AreaTouch(feature=cap, area=a, touches=n,
                                    entities=sorted_ids(hit[(cap, a)]))
                          for (cap, a), n in counts.items() if a == sid),
                         key=lambda t: (-t.touches, pos.get(t.feature, len(pos)), t.feature))
        areas.append(DataArea(id=sid, name=subs[sid].name, purpose=subs[sid].purpose,
                              entities=sorted_ids(set(ents)), owners=owners, touched_by=touched))
    sub_pos = {g.id: i for i, g in enumerate(m.subdomains)}

    def introduced(a: DataArea) -> int:
        """Where the story first reaches this area: the earliest column position among the features
        whose walks touch it. `len(pos)` — past the end — for an area no walk reaches."""
        return min((pos[t.feature] for t in a.touched_by if t.feature in pos), default=len(pos))

    return sorted(areas, key=lambda a: (introduced(a), sub_pos[a.id]))


def build_record_areas(m: ProjectModel, column: Sequence[str] = ()) -> list[DataArea]:
    """The data column for a map with NO sub-domain: one box per SAVED RECORD.

    NOT a second answer to "which feature touches this data". The touches below are counted by the
    same walk over the same steps as `build_areas`, with sub-flows expanded the same way; the only
    thing that changes is what one box stands for. Sub-domains are optional and the method tells a
    map under roughly fifteen records not to cut any, so on such a map `build_areas` returns nothing
    and the column drew nothing at all. A reader then sees an empty column and concludes the
    features touch no data, which is the opposite of what the same bundle says one click away.

    `owners` is ALWAYS empty here, and that is the honest answer rather than a missing one:
    ownership is authored on a sub-domain (`Group.owners`) and this map cut none, so every arrow
    landing on these boxes is a touch and none is an owner.

    `validate` does NOT read this. It calls `build_areas`, so the cross-examination of authored
    ownership sees exactly what it saw before."""
    saved = [e for e in m.entities if is_saved(e)]
    if not saved:
        return []
    by_id = {e.id: e for e in saved}

    cap_ids = {c.id for c in m.capabilities}
    uc_cap = {u.id: u.capability for u in m.use_cases if u.capability in cap_ids}
    counts: dict[tuple[str, str], int] = {}
    for f in m.flows:
        cap = uc_cap.get(f.uc)
        if not cap:
            continue
        for st in expanded_flow_steps(m, f):
            for side in (st.src, st.dst):
                if side in by_id:
                    counts[(cap, side)] = counts.get((cap, side), 0) + 1

    pos = {c: i for i, c in enumerate(column)}
    ent_pos = {e.id: i for i, e in enumerate(saved)}
    out = []
    for e in saved:
        touched = sorted((AreaTouch(feature=cap, area=eid, touches=n, entities=[eid])
                          for (cap, eid), n in counts.items() if eid == e.id),
                         key=lambda t: (-t.touches, pos.get(t.feature, len(pos)), t.feature))
        out.append(DataArea(id=e.id, name=e.name or e.id, purpose=e.meaning or "",
                            entities=[e.id], owners=[], touched_by=touched))

    def introduced(a: DataArea) -> int:
        return min((pos[t.feature] for t in a.touched_by if t.feature in pos), default=len(pos))

    return sorted(out, key=lambda a: (introduced(a), ent_pos[a.id]))
