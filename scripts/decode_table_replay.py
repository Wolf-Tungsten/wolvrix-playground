#!/usr/bin/env python3
"""Replay every raw table in one elaboration manifest, retaining exact reuse evidence."""
import argparse
import hashlib
import json
from pathlib import Path

from decode_table_study import build_scala, build_case, verify_case, parse
from grhsim_single_baseline import identity, save


def replay(manifest, output, reuse):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    raw = json.loads(manifest.read_text())
    known = {}
    for root in reuse:
        for path in sorted(Path(root).resolve().rglob('table.txt')):
            verification = path.parent/'verification.json'
            if not verification.exists():
                continue
            checks = json.loads(verification.read_text())
            if {(c['variant'], c['seed']) for c in checks if c['status'] == 'pass'} != {
                    (v,s) for v in ['A','B','verilator'] for s in [20261103,20261104]}:
                continue
            known[path.read_text().strip()] = path.parent
    classpath = None
    cases = []
    save(output/'input_identity.json', dict(manifest=identity(manifest), driver=identity(__file__)))
    for index, (key, payload) in enumerate(raw['decode_tables'].items()):
        if hashlib.sha256(payload.encode()).hexdigest() != key:
            raise ValueError('payload identity differs from manifest')
        sites = [r for r in raw['calls'] if r['table_id'] == key]
        name = f"{index:02d}_{sites[0]['module_class'].split('.')[-1]}"
        (output/(name+'.table')).write_text(payload+'\n')
        case = known.get(payload)
        reused = case is not None
        if not reused:
            if classpath is None:
                classpath = build_scala(output)
            case = output/name
            print('BUILD', name, flush=True)
            build_case(case, payload, classpath, espresso=True)
            verify_case(case)
        table = parse(payload)
        cases.append(dict(name=name, table_id=key, case=str(case), reused=reused,
            input_width=table['n'], output_width=table['m'], fields=table['fields'], mode=table['mode'],
            rows=len(table['rows']), sites=sites, verification=identity(case/'verification.json'),
            identity=identity(case/'identity.json')))
        save(output/'cases.json', cases)
        print('VERIFIED', name, 'reused' if reused else 'new', flush=True)
    return cases


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--reuse', type=Path, action='append', default=[])
    args = p.parse_args()
    replay(args.manifest, args.output, args.reuse)
