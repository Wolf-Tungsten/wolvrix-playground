#!/usr/bin/env python3
"""Phase 2 read-side select-tree coverage estimate (E1 graph).

For each lane group (name pattern, >=8 lanes), find select trees over lane read
values: kMux/kOr/kAnd trees that merge >=MIN lanes of the group. Estimate op
savings if replaced by kSliceDynamic over the merged wide register.

Inputs: /tmp/grh_op_index.pkl, /tmp/grh_users.pkl, /tmp/grh_write_ports.json,
        /tmp/grh_read_ports.json
Output: JSON + stdout summary.
"""
import pickle, json, re, sys, collections

sys.setrecursionlimit(4000000)

with open('/tmp/grh_op_index.pkl', 'rb') as f:
    opdefs, val2op = pickle.load(f)
with open('/tmp/grh_users.pkl', 'rb') as f:
    users = pickle.load(f)
wps = json.load(open('/tmp/grh_write_ports.json'))
rps = json.load(open('/tmp/grh_read_ports.json'))
reg2val = {v['reg']: v['out'] for v in rps.values()}

NUM_SEG = re.compile(r'_(\d+)(?=_|\$|$)')

def group_key(name):
    m = NUM_SEG.search(name)
    return (name[:m.start()] + '_*' + name[m.end():], int(m.group(1))) if m else None

groups = collections.defaultdict(dict)
for v in wps.values():
    gk = group_key(v['reg'])
    if gk:
        groups[gk[0]][gk[1]] = v['reg']

TREE_KINDS = {'kMux', 'kOr', 'kAnd'}
MIN_MERGE = 8
report = []
total = 0

for gk, lanes in groups.items():
    if len(lanes) < MIN_MERGE:
        continue
    lane_vals = {idx: reg2val.get(reg) for idx, reg in lanes.items()}
    lane_vals = {i: v for i, v in lane_vals.items() if v}
    if len(lane_vals) < MIN_MERGE:
        continue
    val2idx = {v: i for i, v in lane_vals.items()}

    # seed: ops directly consuming any lane read value
    seed = set()
    for v in lane_vals.values():
        for c in users.get(v, ()):
            e = opdefs.get(c)
            if e and e[0] in TREE_KINDS:
                seed.add(c)
    if not seed:
        continue
    # grow: op joins tree if TREE_KIND and has >=2 operands already in tree
    # (or >=1 for unary-ish merge of tree chains)
    in_tree = set(seed)
    changed = True
    rounds = 0
    while changed and rounds < 12:
        changed = False
        rounds += 1
        for c in list(in_tree):
            for p in users.get(c, ()):
                if p in in_tree:
                    continue
                e = opdefs.get(p)
                if not e or e[0] not in TREE_KINDS:
                    continue
                child_hits = sum(1 for o in e[1] if o in in_tree or o in val2idx)
                # operand values: ops produce values; users map is on values,
                # so p consumes c's value. Approximate child_hits via operands:
                ops_in_tree = 0
                for o in e[1]:
                    oid = val2op.get(o)
                    if oid in in_tree or o in val2idx:
                        ops_in_tree += 1
                if ops_in_tree >= 1 and e[0] == 'kOr' or ops_in_tree >= 2:
                    in_tree.add(p)
                    changed = True
    # lanes covered by the tree
    covered = set()
    for c in in_tree:
        e = opdefs.get(c)
        for o in e[1]:
            if o in val2idx:
                covered.add(val2idx[o])
    if len(covered) < MIN_MERGE:
        continue
    save = len(in_tree) - 3  # replaced by slice_dynamic + scale + wide read
    if save <= 0:
        continue
    total += save
    report.append({'group': gk, 'lanes': len(lanes), 'covered': len(covered),
                   'tree_ops': len(in_tree), 'save': save})

report.sort(key=lambda g: -g['save'])
out = sys.argv[1] if len(sys.argv) > 1 else 'topo-partition-proj/exp/dataset/lane_readside_v1_20260801.json'
json.dump({'total_save': total, 'n_groups': len(report), 'groups': report[:200]},
          open(out, 'w'), ensure_ascii=False, indent=1)
print('groups with select trees:', len(report))
print('total_save estimate:', total)
for g in report[:20]:
    print(f"{g['save']:>7} {g['covered']:>4}/{g['lanes']:<4} tree={g['tree_ops']:<6} {g['group'][-70:]}")
