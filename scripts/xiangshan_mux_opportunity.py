#!/usr/bin/env python3
"""Prepare a compact, unscheduled GRH for mux demand analysis.

Only reads the frozen graph. No simulator generation, partitioning or RTL edits.
The companion C++ program consumes graph.bin; all identifiers remain traceable
to byte offsets in the input JSON. Constants/state/effects are eager boundaries.
"""
from array import array
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import time

PURE = set(('Add Sub Mul Div Mod Eq Ne CaseEq CaseNe WildcardEq WildcardNe '
            'Lt Le Gt Ge And Or Xor Xnor Not LogicAnd LogicOr LogicNot '
            'ReduceAnd CountTrailingZeros CountOnes DecodeTable GrayDecode '
            'ReduceOr ReduceXor ReduceNor ReduceNand ReduceXnor Shl LShr AShr '
            'Mux Assign Concat Replicate SliceStatic SliceDynamic SliceArray').split())
PURE = {'k' + name for name in PURE}
WIRING = {'kAssign', 'kConcat', 'kReplicate', 'kSliceStatic'}
# flags: pure=1, mandatory=2, mux=4, scalar/single-result=8, wiring=16.


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def const_truth(op):
    if op['kind'] != 'kConstant':
        return -1
    value = op.get('attrs', {}).get('constValue', {}).get('v', '')
    match = re.fullmatch(r"(\d+)'([sS]?)([bBoOdDhH])([0-9a-fA-F_]+)", value)
    if not match:
        return -1
    base = {'b': 2, 'o': 8, 'd': 10, 'h': 16}[match[3].lower()]
    return int(bool(int(match[4].replace('_', ''), base) & ((1 << int(match[1])) - 1)))


def prepare(source, output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    names = {}
    defs = array('I', [0])
    widths = array('I', [0])
    logical = bytearray([0])
    public = bytearray([0])
    inputs = bytearray([0])
    offsets = array('Q', [0, 0])
    operands = array('I')
    flags = array('I', [2])
    op_widths = array('I', [0])
    selectors = array('I', [0])
    truths = array('b', [-1])
    locations = array('Q', [0])
    kinds = ['<external-input>']
    kind_lookup = {kinds[0]: 0}
    kind_ids = array('I', [0])
    counts = Counter()
    graph_names = []
    section = None
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        while True:
            position = stream.tell()
            line = stream.readline()
            if not line:
                break
            digest.update(line)
            s = line.strip().rstrip(b',')
            if s.startswith(b'"symbol":'):
                graph_names.append(json.loads(b'{' + s + b'}')['symbol'])
            if s in (b'"vals": [', b'"ops": ['):
                section = 'vals' if s == b'"vals": [' else 'ops'
                continue
            if section and s == b']':
                section = None
                continue
            if not section:
                continue
            if not s.startswith(b'{"sym":'):
                raise ValueError(f'Unsupported row at {position}')
            row = json.loads(s)
            if section == 'vals':
                name = row['sym']
                if name in names:
                    raise ValueError('Multiple graphs/duplicate value: ' + name)
                names[name] = len(defs)
                defs.append(0)
                widths.append(max(0, row.get('w', 0)))
                logical.append(row.get('type') == 'logic')
                public.append(bool(row.get('out') or row.get('inout')))
                inputs.append(bool(row.get('in') or row.get('inout')))
                continue
            oid = len(flags)
            ins = [names[v] for v in row.get('in', [])]
            outs = [names[v] for v in row.get('out', [])]
            kind = row['kind']
            if kind not in kind_lookup:
                kind_lookup[kind] = len(kinds)
                kinds.append(kind)
            is_pure = kind in PURE and not row.get('attrs', {}).get('hasSideEffects', {}).get('v', False)
            is_pure &= bool(outs) and all(logical[v] for v in ins + outs)
            root = not is_pure or any(public[v] for v in outs)
            scalar = len(outs) == 1 and all(logical[v] and 0 < widths[v] <= 64 for v in ins + outs)
            mux = is_pure and kind == 'kMux' and len(ins) == 3 and len(outs) == 1
            flags.append(int(is_pure) | (2 * root) | (4 * mux) | (8 * scalar) | (16 * (kind in WIRING)))
            op_widths.append(max((widths[v] for v in ins + outs), default=0))
            selectors.append(ins[0] if mux else 0)
            truths.append(const_truth(row))
            locations.append(position)
            kind_ids.append(kind_lookup[kind])
            operands.extend(ins)
            offsets.append(len(operands))
            for v in outs:
                if defs[v]:
                    raise ValueError('Multiple definitions: ' + row['sym'])
                defs[v] = oid
            counts[kind] += 1
            if oid % 500000 == 0:
                print(f'loaded {oid:,} ops; elapsed {time.monotonic()-started:.1f}s', flush=True)
    if graph_names != ['SimTop']:
        raise ValueError('Expected one unpartitioned SimTop: ' + repr(graph_names))
    unresolved = [name for name, v in names.items() if not defs[v] and not inputs[v]]
    preds = array('I', (defs[v] for v in operands))
    used_unresolved = set(operands) & {names[name] for name in unresolved}
    used_unresolved_names = [name for name in unresolved if names[name] in used_unresolved]
    selector_truth = array('b', (truths[defs[v]] if v else -1 for v in selectors))
    n = len(flags)
    assert len(offsets) == n + 1
    with (output / 'graph.bin').open('wb') as stream:
        stream.write(b'MUXGRH01')
        stream.write(struct.pack('<QQQ', n, len(preds), len(defs)))
        for data in (offsets, preds, flags, op_widths, selectors, selector_truth, kind_ids, locations):
            data.tofile(stream)
    save(output / 'input.json', dict(
        source=dict(path=str(source.resolve()), bytes=source.stat().st_size, sha256=digest.hexdigest()),
        graph_names=graph_names, ops=n-1, values=len(defs)-1, operand_occurrences=len(preds),
        kinds=kinds, kind_counts=counts, pure_kinds=sorted(PURE), wiring_kinds=sorted(WIRING),
        unresolved_noninput_count=len(unresolved), used_unresolved_noninput=used_unresolved_names,
        elapsed_s=time.monotonic()-started,
        semantics='All non-pure operations and public outputs are mandatory roots. Constants and state/memory reads are not counted as pure arithmetic. State commit edges are not followed back into state reads.'))
    print(f'prepared {n-1:,} ops, {len(preds):,} operand occurrences', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.graph.resolve(), args.output.resolve())
