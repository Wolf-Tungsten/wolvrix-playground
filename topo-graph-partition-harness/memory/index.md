# topo-graph-partition-harness Memory

Use `search_tree.md` as the index for all algorithm-attempt nodes.

Expected sections in `search_tree.md`:

- `Active Frontier`: the single live execution plus any completed `keep` nodes that are still valid parents.
- `Parked Candidates`: deferred child hypotheses that are not activated yet.
- `Closed Nodes`: rejected or exhausted nodes with their continuation decision recorded.
- `Family Ledger`: one-row summary per algorithm family so frontier exhaustion is visible.
