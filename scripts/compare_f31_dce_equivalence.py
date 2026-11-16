"""Compare actual post-DCE IR and public graphs from two raw FIRRTL runs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time

from benchmark_xs_firrtl_ingest import checked
from semantic_node_exchange import compact, verify_snapshot


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def public_fingerprint(database):
    # The key includes every typed/unresolved endpoint and reason, but excludes
    # exchange-local connection IDs. Node IDs and full identity remain exact.
    result = {}
    with sqlite3.connect(database) as db:
        for name, query in (
                ('nodes', 'SELECT id,body FROM current_nodes ORDER BY id'),
                ('connections', 'SELECT key FROM current_connections ORDER BY key')):
            digest = hashlib.sha256()
            count = 0
            for record in db.execute(query):
                digest.update(compact(list(record)).encode('utf-8') + b'\n')
                count += 1
            result[name] = {'sha256': digest.hexdigest(), 'count': count}
    return result


def capture_actual_state(session, output, stage, *, top=None):
    """Export actual IR/public graph independently of the observer cache."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    ir = output / 'actual-ir.json'
    checked(session.store_json(design='design.main', output=str(ir), mode='pretty-compact',
                               emit_source_locations=False), 'store actual DCE circuit')
    public = output / 'public'
    public.mkdir()
    session.semantic_snapshot(design='design.main', output=str(public), top=top, stage=stage)
    with tempfile.TemporaryDirectory(prefix='actual-public-check-', dir=output) as work:
        database = Path(work) / 'public.sqlite'
        verification = verify_snapshot(public, database)
        if (not verification['complete'] or
                verification['snapshot']['nodes'].get('nodeInventoryComplete') is not True):
            raise ValueError('actual public graph snapshot is incomplete')
        signature = public_fingerprint(database)
    files = [ir, public / 'nodes.tsv', public / 'connections.tsv']
    return {'signature': {'ir_sha256': digest_file(ir), **signature},
            'artifacts': [{'path': str(path.resolve()), 'sha256': digest_file(path)} for path in files],
            'public_verification': verification, 'wall_s': time.monotonic() - started}


def checked_capture(value):
    if not isinstance(value, dict) or value.get('public_verification', {}).get('complete') is not True:
        raise ValueError('missing independent actual graph verification')
    artifacts = value.get('artifacts')
    if not isinstance(artifacts, list) or len(artifacts) != 3:
        raise ValueError('missing actual IR/public graph artifacts')
    if {Path(item['path']).name for item in artifacts} != {'actual-ir.json', 'nodes.tsv', 'connections.tsv'}:
        raise ValueError('unexpected actual-state artifact inventory')
    for item in artifacts:
        if digest_file(item['path']) != item['sha256']:
            raise ValueError('actual-state artifact changed: ' + item['path'])
    paths = {Path(item['path']).name: Path(item['path']) for item in artifacts}
    if paths['nodes.tsv'].parent != paths['connections.tsv'].parent:
        raise ValueError('actual public inventory files are from different snapshots')
    with tempfile.TemporaryDirectory(prefix='equivalence-check-', dir=paths['nodes.tsv'].parent.parent) as work:
        database = Path(work) / 'actual.sqlite'
        verification = verify_snapshot(paths['nodes.tsv'].parent, database)
        if verification['snapshot']['nodes'].get('nodeInventoryComplete') is not True:
            raise ValueError('actual public Node inventory is incomplete')
        actual = public_fingerprint(database)
    if any(digest_file(item['path']) != item['sha256'] for item in artifacts):
        raise ValueError('actual-state artifact changed while verifying')
    signature = value['signature']
    ir = next(item for item in artifacts if Path(item['path']).name == 'actual-ir.json')
    if signature['ir_sha256'] != ir['sha256']:
        raise ValueError('IR signature is not bound to the actual circuit artifact')
    if any(signature.get(key) != actual[key] for key in actual):
        raise ValueError('public graph signature differs from actual inventory')
    return signature


def compare(off, on):
    samples = []
    for path, mode in ((off, 'no-trace'), (on, 'trace')):
        sample = json.loads(Path(path).read_text())
        if (sample.get('schema') != 'wolvrix.f31.dce-benchmark.v1' or sample.get('status') != 'passed' or
                sample.get('engine') != 'grh' or sample.get('mode') != mode or
                sample.get('source') != 'raw-firrtl' or sample.get('verify') is not True):
            raise ValueError('equivalence needs completed raw FIRRTL correctness runs in both trace modes')
        dce = sample['dce']
        first = checked_capture(dce['actual_after'])
        repeated = checked_capture(dce['actual_repeated'])
        if first != repeated or dce['repeated_dce_history'].get('changed') is not False:
            raise ValueError('actual circuit/public graph changed on second DCE')
        samples.append((sample, first))
    left, right = (entry[0] for entry in samples)
    for field in ('input_sha256', 'manifest_sha256', 'configuration', 'package_identity',
                  'sources', 'dependencies'):
        if left[field] != right[field]:
            raise ValueError('equivalence run identities differ: ' + field)
    if samples[0][1] != samples[1][1]:
        raise ValueError('trace changed actual post-DCE IR or public Node graph')
    return {'schema': 'wolvrix.f31.dce-equivalence.v1', 'complete': True, 'passed': True,
            'input_sha256': left['input_sha256'], 'signature': samples[0][1],
            'scope': 'actual serialized IR without source locations; full Node identities and typed public connection keys; second-DCE equality',
            'samples': [{'path': str(Path(path).resolve()), 'sha256': digest_file(path)} for path in (off, on)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-trace', type=Path, required=True)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.no_trace, args.trace)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(compact(report))


if __name__ == '__main__':
    main()
