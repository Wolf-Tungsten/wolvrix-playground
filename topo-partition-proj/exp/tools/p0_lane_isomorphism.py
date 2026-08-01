#!/usr/bin/env python3
"""R-B lane re-vectorization coverage estimate v4 (fast two-phase hashing).

Phase 1: global integer hash per op (lane-absolute register reads are leaves with
  group+idx identity; constants abstracted). Computed once, O(N).
Phase 2: per-group per-lane signature over the lane's private cone only
  (boundary: nodes with global user count > 1 contribute their global hash).
  Register reads inside the private cone resolve lane-relative via ctx.

Inputs: /tmp/grh_op_index.pkl, /tmp/grh_write_ports.json, /tmp/grh_users.pkl
Output: JSON report (arg1, default .../lane_iso_v4_20260801.json) + stdout summary
"""
import pickle, json, re, sys, collections

sys.setrecursionlimit(4000000)

PKL = '/tmp/grh_op_index.pkl'
WPS = '/tmp/grh_write_ports.json'
USERS = '/tmp/grh_users.pkl'
OUT = sys.argv[1] if len(sys.argv) > 1 else 'topo-partition-proj/exp/dataset/lane_iso_v4_20260801.json'

with open(PKL, 'rb') as f:
    opdefs, val2op = pickle.load(f)
wps = json.load(open(WPS))
with open(USERS, 'rb') as f:
    users = pickle.load(f)

def entry(v):
    if v in opdefs:
        return opdefs[v]
    oid = val2op.get(v)
    if oid and oid in opdefs:
        return opdefs[oid]
    return None

NUM_SEG = re.compile(r'_(\d+)(?=_|\$|$)')

def group_key(name):
    m = NUM_SEG.search(name)
    if not m:
        return None
    return name[:m.start()] + '_*' + name[m.end():], int(m.group(1))

groups = collections.defaultdict(dict)
for wp in wps.values():
    gk = group_key(wp['reg'])
    if gk:
        groups[gk[0]][gk[1]] = wp['reg']
reg_lane = {}
for gk, lanes in groups.items():
    if len(lanes) >= 4:
        for idx, reg in lanes.items():
            reg_lane[reg] = (gk, idx)

MASK = (1 << 61) - 1

def mix(*args):
    h = 0x345678
    for a in args:
        h = ((h * 1000003) ^ (a & MASK)) & MASK
    return h

def str_hash(s):
    h = 0
    for ch in s:
        h = (h * 131 + ord(ch)) & MASK
    return h

# ---------- phase 1: global hashes ----------
KIND_H = {}
def kind_h(k):
    v = KIND_H.get(k)
    if v is None:
        v = KIND_H[k] = str_hash(k)
    return v

ghash_memo = {}

def ghash(v):
    h = ghash_memo.get(v)
    if h is not None:
        return h
    e = entry(v)
    if e is None:
        h = mix(11, str_hash(v))
    else:
        kind, ops, attrs = e
        if kind == 'kConstant':
            h = 7
        elif not ops:
            reg = None
            if kind == 'kRegisterReadPort' and attrs:
                reg = attrs[0]
            elif kind in ('kRegister', 'kLatch'):
                reg = v
            if reg is not None:
                gl = reg_lane.get(reg)
                if gl:
                    h = mix(21, str_hash(gl[0]), gl[1])
                else:
                    h = mix(22, str_hash(reg))
            else:
                h = mix(23, kind_h(kind), str_hash(attrs[0]) if attrs else 0)
        else:
            h = mix(31, kind_h(kind), *[ghash(o) for o in ops])
    ghash_memo[v] = h
    return h

print('phase 1: global hashing...', file=sys.stderr)
all_ops = list(opdefs.keys())
for i, sym in enumerate(all_ops):
    ghash(sym)
    if i % 500000 == 499999:
        print(f'  {i+1}/{len(all_ops)}', file=sys.stderr)

# ---------- phase 2: per-lane signature over private cone ----------

def lane_sig(root, gk, idx):
    """iterative hash over private cone; boundary at users>1 (use global hash)."""
    memo = {}

    def h(v):
        if v in memo:
            return memo[v]
        e = entry(v)
        if e is None:
            r = mix(11, str_hash(v))
        elif v != root and len(users.get(v, ())) > 1:
            r = mix(41, ghash(v))  # shared boundary leaf
        else:
            kind, ops, attrs = e
            if kind == 'kConstant':
                r = 7
            elif not ops:
                reg = None
                if kind == 'kRegisterReadPort' and attrs:
                    reg = attrs[0]
                elif kind in ('kRegister', 'kLatch'):
                    reg = v
                if reg is not None:
                    gl = reg_lane.get(reg)
                    if gl and gl[0] == gk and gl[1] == idx:
                        r = 51  # lane-self read
                    elif gl:
                        r = mix(52, str_hash(gl[0]), gl[1] - idx)
                    else:
                        r = mix(22, str_hash(reg))
                else:
                    r = mix(23, kind_h(kind), str_hash(attrs[0]) if attrs else 0)
            else:
                r = mix(31, kind_h(kind), *[h(o) for o in ops])
        memo[v] = r
        return r
    return h(root)

def priv_cone(root):
    seen = set()
    stack = [root]
    while stack:
        v = stack.pop()
        if v in seen:
            continue
        seen.add(v)
        e = entry(v)
        if e is None:
            continue
        if v != root and len(users.get(v, ())) > 1:
            continue
        stack.extend(e[1])
    return seen

byreg = {v['reg']: (k, v['in']) for k, v in wps.items()}
MIN_LANES = 8
report = []
tot = 0.0

print('phase 2: per-group signatures...', file=sys.stderr)
for gk, lanes in groups.items():
    n = len(lanes)
    if n < MIN_LANES:
        continue
    idxs = sorted(lanes)
    sig2lanes = collections.defaultdict(list)
    for idx in idxs:
        got = byreg.get(lanes[idx])
        if not got:
            continue
        _, ins = got
        if len(ins) < 2:
            continue
        s = (lane_sig(ins[0], gk, idx), lane_sig(ins[1], gk, idx))
        sig2lanes[s].append(idx)
    if not sig2lanes:
        continue
    main_sig, main_lanes = max(sig2lanes.items(), key=lambda kv: len(kv[1]))
    merged = len(main_lanes)
    if merged < MIN_LANES:
        continue
    sizes = []
    for idx in main_lanes:
        _, ins = byreg[lanes[idx]]
        sizes.append(len(priv_cone(ins[0]) | priv_cone(ins[1])))
    avg_priv = sum(sizes) / len(sizes)
    if avg_priv > 5000:
        continue
    save = (merged - 1) * avg_priv
    tot += save
    report.append({'group': gk, 'lanes': n, 'merged': merged,
                   'sigs': len(sig2lanes), 'avg_priv': round(avg_priv, 1),
                   'save': round(save)})

report.sort(key=lambda g: -g['save'])
json.dump({'total_save': round(tot), 'n_groups': len(report), 'groups': report[:300]},
          open(OUT, 'w'), ensure_ascii=False, indent=1)
print('groups:', len(report))
print('total_save (private-cone):', round(tot))
for g in report[:25]:
    print(f"{g['save']:>8} {g['merged']:>4}/{g['lanes']:<4} sigs={g['sigs']:<3} priv={g['avg_priv']:<7} {g['group'][-75:]}")
