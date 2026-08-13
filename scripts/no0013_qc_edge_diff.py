#!/usr/bin/env python3
"""NO0013 QC-E: atom-level edge-set diff between two AM instruction-graph jsonl exports.

QC gate for the "atom connectivity invariant" hard constraint:
  - every atom-level edge present before must be present after (no deletions);
  - no new atom-level edges may appear (no insertions);
  - edge-carried data volume (sum of def_use widths per atom pair) may shrink
    and is reported as an informational metric.

Edge classes:
  - data edges: def_use records, keyed (src_atom, dst_atom);
  - order edges: order records, keyed (src_atom, dst_atom), diffed separately.

Usage: no0013_qc_edge_diff.py <before.jsonl> <after.jsonl> [--json OUT]
Exit code 0 iff both edge-class sets are identical; 1 otherwise.
"""
import json
import re
import sys
from array import array

NODE_RE = re.compile(r'^\{"record":"node","id":(\d+),.*?"atom":(\d+),')
EDGE_RE = re.compile(
    r'^\{"record":"edge","kind":"(def_use|order|external_read)",'
    r'"src":(\d+),"dst":(\d+)(?:,"var":\d+,"width":(\d+))?\}')


def load(path):
    node_atom = array('i')  # node id -> atom id (node ids are dense from 0)
    data_edges = {}         # (src_atom, dst_atom) -> total width
    order_edges = set()
    nodes = 0
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            m = NODE_RE.match(line)
            if m:
                nid, atom = int(m.group(1)), int(m.group(2))
                if nid != len(node_atom):
                    raise SystemExit(f'{path}: node ids not dense at {nid}')
                node_atom.append(atom)
                nodes += 1
                continue
            e = EDGE_RE.match(line)
            if e:
                kind = e.group(1)
                if kind == 'external_read':
                    continue
                src, dst = int(e.group(2)), int(e.group(3))
                width = int(e.group(4)) if e.group(4) else 0
                sa, da = node_atom[src], node_atom[dst]
                if kind == 'def_use':
                    key = (sa, da)
                    data_edges[key] = data_edges.get(key, 0) + width
                else:
                    order_edges.add((sa, da))
    return {'nodes': nodes, 'data': data_edges, 'order': order_edges}


def main():
    before_path, after_path = sys.argv[1], sys.argv[2]
    json_out = sys.argv[sys.argv.index('--json') + 1] if '--json' in sys.argv else None
    before = load(before_path)
    after = load(after_path)

    report = {'before_nodes': before['nodes'], 'after_nodes': after['nodes']}
    ok = True
    for cls, b, a in (('data', set(before['data']), set(after['data'])),
                      ('order', before['order'], after['order'])):
        only_before = b - a
        only_after = a - b
        report[f'{cls}_edges_before'] = len(b)
        report[f'{cls}_edges_after'] = len(a)
        report[f'{cls}_edges_only_before'] = len(only_before)
        report[f'{cls}_edges_only_after'] = len(only_after)
        if only_before or only_after:
            ok = False
            report[f'{cls}_sample_only_before'] = sorted(only_before)[:10]
            report[f'{cls}_sample_only_after'] = sorted(only_after)[:10]

    # informational: data volume delta on surviving edges
    shrunk = grew = 0
    width_before = width_after = 0
    for key in set(before['data']) & set(after['data']):
        wb, wa = before['data'][key], after['data'][key]
        width_before += wb
        width_after += wa
        if wa < wb:
            shrunk += 1
        elif wa > wb:
            grew += 1
    report['data_width_total_before'] = width_before
    report['data_width_total_after'] = width_after
    report['data_edges_width_shrunk'] = shrunk
    report['data_edges_width_grew'] = grew
    report['qc_e_pass'] = ok

    text = json.dumps(report, indent=2)
    print(text)
    if json_out:
        with open(json_out, 'w', encoding='utf-8') as fh:
            fh.write(text + '\n')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
