# T5 addendum (Phase 1) — the domain-model owner's half

**Appended to ONE harvest brief only: the T5 owner's.** Compose it INTO that brief with
`coyomap contract harvest --fill <that agent's slots> --out <brief> --append harvest-t5`. Never with
`>>`: an append the tool cannot see walks around every check `--fill` makes, and a build that did it
under a loop `set -e` did not abort left a 1,217-byte brief that was only this addendum. Its one
slot, «COYOMAP_HOME», is the harvest contract's too, so the same slots file fills both halves.

It moved out of the shared harvest contract on 2026-08-27: 13 of ~14 harvest agents were reading a
detailed spec of a job they must not do, and a described-but-forbidden job is a known confusion
source — the main contract keeps only the one sentence forbidding it.

> You are ALSO the T5 DOMAIN-MODEL owner — exactly one agent in this fan-out owns T5, and it is
> you. Everything in your harvest brief above still applies; this addendum is the domain slice's
> own spec.
>
> Your fragment also carries the **`entities` array — per-entity objects, never a flat table**
> (`id`, `name`, `store`, `meaning`, `source`, `fields`, `relations` — the semantic spec is
> [domain-cards.md](«COYOMAP_HOME»/method/domain-cards.md)), with **a `relations` item wherever two
> entities relate** — the entities + their `E↔E` relations are the whole point of the slice. In
> each `store`, write `container`, `mode` and `notes` and leave `dep` null: the dependency ids
> come from a slice running beside you, and the lead sets `dep` at synthesis. Each
> entity is a **real named type** (class / dataclass / enum) whose `source` anchors its
> **definition** — do NOT synthesize an entity for an unnamed concept. **`name` is the READER's
> word for the thing, never the class's spelling** (`source` already carries that): one build named
> 52 of 59 entities after their classes, where 0 of 126 components were. Type embedded fields by
> their entity (`auth:E7`) so relations carry the field name. For a **field-less** relation a store
> realizes by keying (no FK on the row — e.g. a per-parent store keyed by `parent_id`), set the
> relation's **`keyed_by`** (`"keyed_by": ["parent_id"]`, a LIST) so the arrow shows that key
> instead of a bare line — see [domain-cards.md](«COYOMAP_HOME»/method/domain-cards.md), which
> defines the label the viewer draws. Mark plumbing types you
> deliberately did NOT model in `non_entity_types` (name + why).
