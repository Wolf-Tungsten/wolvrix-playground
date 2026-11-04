#!/usr/bin/env python3
"""Verify CSR-only lowering preserves the original graph and all non-CSR code."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from grhsim_single_baseline import identity, save


def checksum(path):
    return identity(path)['sha256']


def helper(text, symbol):
    start = text.index('#ifndef WOLVRIX_' + symbol + chr(10))
    stats = text.index('// decode-stats ' + symbol, start)
    end = text.index('#endif', stats) + len('#endif') + 1
    return text[start:end]


def collect(source, tuned, output):
    source, tuned, output = map(lambda p: Path(p).resolve(), (source, tuned, output))
    roots = dict(B=source/'B', C=tuned/'C', E=output/'E')
    symbol = 'grhsim_decode_c3c4a7e06178ebc9'
    headers = {n: (p/'model/grhsim_SimTop_runtime.hpp').read_text() for n, p in roots.items()}
    original, combined, ablated = (helper(headers[n], symbol) for n in 'BCE')
    cpp = {n: {p.name: checksum(p) for p in (root/'model').glob('*.cpp')} for n, root in roots.items()}
    graph = {n: identity(roots[n]/'pre_reg_to_mem.json') for n in 'BE'}
    changed_cpp = [name for name in sorted(cpp['B'].keys() | cpp['E'].keys())
                   if cpp['B'].get(name) != cpp['E'].get(name)]
    model_headers = {}
    for name in ('grhsim_SimTop.hpp', 'activity_schedule_supernode_stats.json'):
        if all((roots[n]/'model'/name).is_file() for n in 'BE'):
            model_headers[name] = {n: checksum(roots[n]/'model'/name) for n in 'BE'}
    gates = dict(graph_identical=graph['B']['sha256'] == graph['E']['sha256'],
                 all_cpp_identical=not changed_cpp,
                 csr_helper_matches_combined=ablated == combined,
                 runtime_header_only_csr_changed=headers['B'].replace(original, combined) == headers['E'],
                 storage_and_schedule_identical=all(r['B'] == r['E'] for r in model_headers.values()))
    binaries = {}
    for name, root in roots.items():
        binary = root/'emu/grhsim-compile/emu'
        sections = subprocess.check_output(['size', '-A', str(binary)], text=True)
        binaries[name] = dict(identity=identity(binary), sections={
            line.split()[0]: int(line.split()[1]) for line in sections.splitlines() if line.startswith('.')})
    details = dict(gates=gates, graph=graph, changed_cpp=changed_cpp,
                   compared_cpp_files=len(cpp['E']), storage_and_schedule=model_headers, binaries=binaries,
                   scope='B and E share the original graph, scheduling, storage layout and all emitted C++ bodies. Only the CSR helper lowering changes.')
    save(output/'ablation_structure.json', details)
    print(json.dumps(gates), flush=True)
    if not all(gates.values()):
        raise ValueError('ablation structure differs beyond the CSR helper; inspect ablation_structure.json')
    return details


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--tuned', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    collect(args.source, args.tuned, args.output)
