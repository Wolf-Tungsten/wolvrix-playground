#!/usr/bin/env python3
"""Cluster-level join: gsim coarsen clusters vs AM coarsen clusters (NO0018).

All artifacts must come from the same gsim run (node ids are run-local).
- gsim cluster per node: block_assignment_coarsen.jsonl (instr->block),
  translated through instruction_graph.jsonl (id -> gsim_id).
- AM cluster per node: am_cluster jsonl ({"atom","cluster","gsim_node"}).
"""
import argparse, json, collections, statistics

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gsim-graph', required=True)
    ap.add_argument('--gsim-coarsen', required=True)
    ap.add_argument('--am-cluster', required=True)
    args = ap.parse_args()

    id2gsim = {}
    with open(args.gsim_graph) as f:
        for line in f:
            r = json.loads(line)
            if r.get('record') == 'node':
                id2gsim[r['id']] = r['gsim_id']

    am_cluster = {}   # gsim_node -> AM cluster id
    with open(args.am_cluster) as f:
        for line in f:
            r = json.loads(line)
            n = r['gsim_node']
            if n >= 0:
                am_cluster[n] = r['cluster']

    g_clusters = collections.defaultdict(list)  # gsim cluster -> [gsim_node]
    with open(args.gsim_coarsen) as f:
        for line in f:
            r = json.loads(line)
            if r.get('record') == 'assign':
                g_clusters[r['block']].append(id2gsim[r['instr']])

    # Restrict both sides to nodes that exist in AM compute space.
    # Per gsim cluster: how many AM clusters do its compute members land in?
    g_nest = 0
    g_scatter_hist = collections.Counter()
    g_sizes = []
    g_pure_content = 0  # clusters whose compute members all map and nest
    per_gsim = []
    for c, mem in g_clusters.items():
        comp = [n for n in mem if n in am_cluster]
        if not comp:
            continue
        ams = collections.Counter(am_cluster[n] for n in comp)
        spread = len(ams)
        g_sizes.append(len(comp))
        g_scatter_hist[spread] += 1
        if spread == 1:
            g_nest += 1
        per_gsim.append((c, len(comp), spread, max(ams.values()) / len(comp)))
    total = len(per_gsim)
    print(f"gsim compute-bearing clusters: {total}")
    print(f"  nested in exactly 1 AM cluster: {g_nest} ({100*g_nest/total:.2f}%)")
    print(f"  scatter hist (AM clusters touched -> count): "
          f"{dict(sorted(g_scatter_hist.items())[:10])}")
    print(f"  compute-member size: mean={statistics.mean(g_sizes):.2f}")

    # Reverse: per AM cluster, how many gsim clusters do its nodes come from?
    a_members = collections.defaultdict(list)
    for n, c in am_cluster.items():
        a_members[c].append(n)
    node2g = {}
    for c, mem in g_clusters.items():
        for n in mem:
            node2g[n] = c
    a_pure = 0
    a_scatter_hist = collections.Counter()
    a_sizes = []
    for c, mem in a_members.items():
        gs = collections.Counter(node2g.get(n, -1) for n in mem)
        a_sizes.append(len(mem))
        a_scatter_hist[len(gs)] += 1
        if len(gs) == 1:
            a_pure += 1
    atotal = len(a_members)
    print(f"AM clusters (owned atoms only): {atotal}")
    print(f"  single-gsim-cluster: {a_pure} ({100*a_pure/atotal:.2f}%)")
    print(f"  scatter hist: {dict(sorted(a_scatter_hist.items())[:10])}")
    print(f"  size mean={statistics.mean(a_sizes):.2f}")

    # Worst offenders: largest gsim clusters that shatter across AM clusters.
    per_gsim.sort(key=lambda r: -r[2])
    print("top shattered gsim clusters (cluster, compute_members, am_spread, dominant):")
    for c, m, s, d in per_gsim[:10]:
        print(f"  gcluster={c} members={m} am_clusters={s} dominant={d:.2f}")

if __name__ == '__main__':
    main()
