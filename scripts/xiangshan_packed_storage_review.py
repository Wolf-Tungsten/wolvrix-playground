#!/usr/bin/env python3
"""Independently audit all samples in a frozen three-round storage comparison."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from grhsim_single_compare import summarize


def read(path):
    return json.loads(Path(path).read_text())


def signature(row):
    return {key: row[key] for key in ('pc', 'instr_count', 'cycle_count', 'guest_cycles',
        'stop_reason', 'runtime_difftest', 'workload_output')}


def audit(source):
    root = source / 'measurement'
    manifest = read(root / 'manifest.json')
    policy = read(root / 'measurement-policy.json')
    declared = read(source / 'policy.json')
    variants = declared['variants']
    assert variants in (['full', 'candidate', 'no_shared'], ['full', 'fixed', 'layout', 'scope', 'no_shared'])
    assert policy['variants'] == declared['variants'] == variants
    assert policy['rounds'] == declared['pairs'] == 3
    assert policy['cpu'] == 96 and policy['numa'] == 1 and not policy['aslr']
    assert policy['threads'] == policy['max_sample_attempts'] == 1
    identities = {}
    def identity(path):
        path = Path(path).resolve()
        if path not in identities:
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            identities[path] = dict(path=str(path), bytes=path.stat().st_size, sha256=digest.hexdigest())
        return identities[path]
    def verify(record):
        assert identity(record['path']) == record, record['path']
    for record in manifest['files']:
        verify(record)
    build = read(source / 'build.json')
    verify(build['inputs'])
    for record in build['files']:
        verify(record)
    if 'binaries' in build:
        for name in variants:
            assert manifest['models'][name]['binary'] == build['binaries'][name]
    else:
        assert manifest['models']['candidate']['binary'] == build['candidate']
        assert manifest['models']['full']['binary'] == build['baseline']
    rounds = read(root / 'rounds.json')
    assert len(rounds) == 3
    expected = signature(rounds[0]['full'])
    samples = []
    for i, row in enumerate(rounds):
        assert row['round'] == i and row['order'] == (variants if i % 2 == 0 else variants[::-1])
        for name in row['order']:
            assert row[name] == read(root / name / 'runs' / f'round{i:02d}.json')
            assert signature(row[name]) == expected
            samples.append((name, f'round{i:02d}', row[name]))
    for name in variants:
        for label in ('smoke', 'verify-s0', 'verify-s1', 'warmup'):
            row = read(root / name / 'runs' / (label + '.json'))
            assert signature(row) == signature(read(root / 'full/runs' / (label + '.json')))
            if label == 'warmup':
                assert signature(row) == expected
            samples.append((name, label, row))
        assert len(list((root / name / 'runs').glob('round*.command.json'))) == 3
    trace_records = {}
    for seed in (0, 1):
        for name in variants[1:]:
            trace = read(root / f'trace-{name}-s{seed}.json')
            assert trace['pass_'] and trace['records'] == 99999
            assert all(c['pass_'] for c in trace['coverage'])
            for chunk in trace['chunks']:
                verify(chunk['a']); verify(chunk['b'])
            trace_records[f'{name}-s{seed}'] = trace['records']
    monitors = localities = staged = 0
    for name in variants:
        folder = root / name / 'runs'
        plan = read(folder / 'runtime_plan.json')
        prepared = read(folder / 'runtime/manifest.json')
        assert plan['cpu'] == 96 and plan['node'] == 1 and prepared['status'] == 'pass'
        for entry in prepared['files']:
            observed = identity(entry['destination'])
            assert observed == entry['copy'] and observed['sha256'] == entry['source']['sha256']
            staged += 1
    for name, label, row in samples:
        folder = root / name / 'runs'
        assert row['cpu'] == 96 and row['numa_node'] == 1 and row['max_threads'] == 1
        assert row['locality_pass'] and row['runtime_difftest'] == 'on'
        assert row['binary_sha256'] == manifest['models'][name]['binary']['sha256']
        command = read(folder / (label + '.command.json'))
        assert command[:8] == ['taskset', '-c', '96', 'numactl', '--membind=1', 'setarch', 'x86_64', '-R']
        assert int((folder / (label + '.personality')).read_text(), 16) & 0x40000
        monitoring = read(folder / (label + '.monitor.json'))
        assert monitoring
        for snap in monitoring:
            assert snap['threads'] == len(snap['tasks']) == 1
            assert all(t['processor'] == 96 and t['affinity'] == '96' for t in snap['tasks'])
        monitors += len(monitoring)
        plan = read(folder / 'runtime_plan.json')
        owned = {entry['destination'] for entry in plan['files']}
        records = read(folder / (label + '.locality.json'))
        assert len(records) == row['locality_samples'] and records
        for index, record in enumerate(records):
            assert not record['unknown_executable']
            assert all(n == '1' or c == 0 for g in record['groups'].values() for n, c in g['pages'].items())
            prefix = folder / (label + '.numa') / f'{index:04d}'
            mappings = {}
            for line in prefix.with_suffix('.maps').read_text().splitlines():
                fields = line.split(maxsplit=5)
                mappings[int(fields[0].split('-')[0], 16)] = (fields[1], fields[5] if len(fields) == 6 else '')
            for line in prefix.with_suffix('.numa_maps').read_text().splitlines():
                address = int(line.split()[0], 16)
                if address not in mappings:
                    continue
                permissions, path = mappings[address]
                if path in owned or not path or path in ('[heap]', '[stack]') or path.startswith('[anon'):
                    assert all(n == '1' or int(c) == 0 for n, c in re.findall(r'\bN(\d+)=(\d+)', line)), line
                elif 'x' in permissions and path.startswith('/'):
                    assert path == plan['interpreter']['path'], path
            localities += 1
    comparisons = {}
    report = read(source / 'report.json')['comparisons']
    pairs = [('full', name, name) for name in variants[1:]]
    pairs += ([(before, after, after + '_vs_' + before) for before, after in
               (('fixed', 'layout'), ('fixed', 'scope'), ('no_shared', 'layout'), ('no_shared', 'scope'))]
              if 'fixed' in variants else [('no_shared', 'candidate', 'candidate_vs_no_shared')])
    for before, after, key in pairs:
        comparisons[key] = {}
        for metric in ('host_ms', 'external_wall_s'):
            scale = 1000 if metric == 'external_wall_s' else 1
            values = [{side: dict(host_ms=row[name][metric] * scale)
                       for side, name in (('A', before), ('B', after))} for row in rounds]
            observed = summarize(values)
            assert all(report[key][metric][k] == v for k, v in observed.items())
            comparisons[key][metric] = observed
    assert not (root / 'failure.json').exists()
    result = dict(status='pass', formal_samples=3 * len(variants), audited_runs=len(samples),
        thread_cpu_snapshots=monitors, raw_numa_snapshots=localities, staged_files=staged,
        traces=trace_records, comparisons=comparisons,
        sibling_cpu288_idle_percent_range=[min(r[n]['sibling_idle']['288'] for r in rounds for n in variants),
                                          max(r[n]['sibling_idle']['288'] for r in rounds for n in variants)],
        inputs=[identity(root / n) for n in ('manifest.json', 'measurement-policy.json', 'rounds.json')],
        script=identity(Path(__file__).resolve()),
        limits='Three fixed rounds; intervals describe this small sample, not general performance across workloads.')
    destination = source / 'independent-review'
    destination.mkdir(exist_ok=True)
    (destination / 'review.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'formal_samples', 'audited_runs', 'thread_cpu_snapshots',
                                          'raw_numa_snapshots', 'sibling_cpu288_idle_percent_range')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    audit(args.source.resolve())
