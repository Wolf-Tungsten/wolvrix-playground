"""topo-partition-proj Phase 0 harness.

Modules:
- graph:    instruction-graph JSONL loader (numpy arrays + npz cache) and the
            canonical topological order;
- scorer:   score an arbitrary block assignment (cost + health metrics),
            same semantics as exp/tools/reconcile_baseline.py;
- sampler:  region sampling (topo windows + BFS regions, halo, holdout);
- searcher: segment DP (width-weighted cost) + simulated-annealing skeleton;
- gnn_bench: CPU gather/SpMM benchmark for the compile-time inference budget.
"""
