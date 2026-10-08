# The harvest contract's field table names only fields the model has, with their types and values

Change (2026-10-08, round 2, retro finding mcpolis-2026-10-08-#6): the field table in the harvest
contract no longer names `entry_point` (removed from the model), `subsystem` or `runs_in` (both
assigned by the lead, and forbidden a few lines below the table). Each closed field names its
values in the table (`activation`: `self` or `external`; `confidence`; `deps[].kind`), each list
field says it is a list, and `depends_on` says it is one line of text, never a list. The anchor
list no longer names `components[].entry_point`. A new test reads the table and every
`array[].field` path in the contract and checks each against the schema generated from the
dataclasses `lint-fragment` loads a fragment into ·
method/templates/harvest-contract.md, tests/test_contract_schema.py.

## Checks

1. expect: 0 harvest `lint-fragment` runs fail on `entry_point` (6 of 14 harvest agents did on
   2026-10-08).
   regression sign: any harvest lint line naming `entry_point` on a component.
2. expect: 0 harvest lint failures on a list `depends_on` (4 of 14 on 2026-10-08) and 0 on a
   prose `activation` (3 of 14).
   regression sign: either failure in any harvest agent's transcript.
3. expect: 0 harvest fragments carry `runs_in` or `subsystem` (the lint advisory "carry
   `runs_in`" does not fire on a harvest fragment).
   regression sign: that advisory on a harvest slice, or the lead dropping `subsystem` values a
   harvest fragment wrote.
