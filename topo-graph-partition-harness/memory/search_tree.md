# Search Tree

## Status Vocabulary

- `in-progress`: the one node currently being executed.
- `keep`: a completed node whose idea remains extendable.
- `parked`: a not-yet-executed child hypothesis recorded for later activation.
- `reject`: a completed node contradicted by evidence.
- `exhausted`: a completed node or family with no actionable next child.

## Active Frontier

| id | parent | family | search_move | hypothesis | status | next_action | experiment |
| --- | --- | --- | --- | --- | --- | --- | --- |

## Parked Candidates

| parent | family | search_move | candidate_hypothesis | activate_when | source_experiment |
| --- | --- | --- | --- | --- | --- |

## Closed Nodes

| id | parent | family | outcome | reason | continuation | experiment |
| --- | --- | --- | --- | --- | --- | --- |

## Family Ledger

| family | latest_node | state | note |
| --- | --- | --- | --- |
