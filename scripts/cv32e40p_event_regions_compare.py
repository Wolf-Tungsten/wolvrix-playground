#!/usr/bin/env python3
"""One frozen event-region schedule experiment, with normalized-RTL Verilator."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from cv32e40p_compare import (ROOT, CXX, CFLAGS, environment, identity, run, sample,
                             save, signature, summarize_named)

BASE = ROOT / 'build/cv32e40p/shared-equality-validated'
MODEL = BASE / 'grhsim_shared_equality'
BACKENDS = ('grhsim_baseline', 'grhsim_event_regions', 'verilator')


def read(path):
    return json.loads(path.read_text())


def source_inventory(folder):
    return {p.name: identity(p) for p in sorted(folder.iterdir()) if p.suffix in ('.cpp', '.hpp')}


def shapes(folder):
    code = '\n'.join(p.read_text() for p in sorted(folder.glob('*_sched_*.cpp')))
    header = (folder / 'grhsim_Cv32Bench.hpp').read_text()
    checks = re.findall(r'const bool grhsim_changed_(\d+) =', code)
    return dict(scheduler_bytes=len(code.encode()), scalar_check_sites=len(checks),
        checked_values=len(set(checks)), compute_functions=len(re.findall(r'void .*::eval_compute_batch_', code)),
        supernodes=len(re.findall(r'// Supernode \d+:', code)),
        value_slots={kind: int(n) for n, kind in re.findall(r'std::array<[^\n]+?, (\d+)> value_(\w+)_slots_', header)})


def check(out):
    manifest = read(out / 'build.json')
    for entry in manifest['frozen_inputs']:
        if identity(entry['path']) != entry:
            raise ValueError('frozen input changed: ' + entry['path'])
    for entry in manifest['binaries'].values():
        if identity(entry['path']) != entry:
            raise ValueError('binary changed: ' + entry['path'])
    return manifest


def build(out, tools, jobs):
    if not platform.node().startswith('node030'):
        raise ValueError('build on node030 for -march=native')
    if out.exists():
        raise FileExistsError('use a new output directory')
    base = read(BASE / 'build.json')
    if identity(MODEL / 'emu') != base['binaries']['grhsim_shared_equality']:
        raise ValueError('baseline binary changed')
    if identity(base['graph']['path']) != base['graph']:
        raise ValueError('frozen input graph changed')
    out.mkdir(parents=True)
    (out / 'firmware').symlink_to(BASE / 'firmware', target_is_directory=True)
    (out / 'verification.json').symlink_to(BASE / 'verification.json')
    (out / 'native-frozen').mkdir()
    native = []
    for src in (tools / 'cv32e40p_emit', tools / 'grhsim32/wolvrix/libwolvrix-lib.so'):
        dest = out / 'native-frozen' / src.name
        shutil.copy2(src, dest)
        native.append(identity(dest))
    patch = out / 'wolvrix.patch'
    patch.write_bytes(subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'diff', '--binary']))
    env = environment()
    env['LD_LIBRARY_PATH'] = str(out / 'native-frozen')
    env['WOLVRIX_GRHSIM_SHARED_EQUALITY_DECODE'] = '1'
    env['CV32_EVENT_REGIONS'] = '0'
    run([out / 'native-frozen/cv32e40p_emit', base['graph']['path'], out / 'off-source', 'off'],
        out / 'logs/off-emit.log', env=env)
    before, off = source_inventory(MODEL), source_inventory(out / 'off-source')
    shape = lambda rows: {k: (v['bytes'], v['sha256']) for k, v in rows.items()}
    if shape(before) != shape(off):
        save(out / 'source-mismatch.json', dict(baseline=before, off=off))
        raise ValueError('new tool feature-off does not reproduce the frozen baseline source')
    candidate = out / BACKENDS[1]
    env['CV32_EVENT_REGIONS'] = '1'
    run([out / 'native-frozen/cv32e40p_emit', base['graph']['path'], candidate, 'off'],
        out / 'logs/region-emit.log', env=env)
    if identity(candidate / 'normalized.json')['sha256'] != identity(MODEL / 'normalized.json')['sha256']:
        raise ValueError('region scheduling changed the frozen graph')
    if not re.search(r'event-regions: regions=[1-9]', (out / 'logs/region-emit.log').read_text()):
        raise ValueError('no event region formed')
    run(['make', '-C', candidate, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)],
        out / 'logs/compile.log')
    harness = Path(base['harness']['path'])
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', candidate, harness,
         candidate / 'libgrhsim_Cv32Bench.a', '-o', candidate / 'emu'], out / 'logs/link.log')
    for backend, src in ((BACKENDS[0], MODEL / 'emu'), ('verilator', ROOT / 'build/cv32e40p/run2/verilator/emu')):
        (out / backend).mkdir()
        shutil.copy2(src, out / backend / 'emu')
    native_sources = [ROOT / 'testcase/cv32e40p-bench/emit.cpp',
        ROOT / 'wolvrix/lib/transform/activity_schedule.cpp', ROOT / 'wolvrix/include/transform/activity_schedule.hpp']
    snapshot = out / 'source-snapshot'
    snapshot.mkdir()
    saved_sources = []
    for src in [*native_sources, Path(__file__).resolve()]:
        dst = snapshot / src.name
        shutil.copy2(src, dst)
        saved_sources.append(dict(source_at_build=identity(src), snapshot=identity(dst)))
    save(snapshot / 'manifest.json', saved_sources)
    save(out / 'structure.json', dict(baseline=shapes(MODEL), candidate=shapes(candidate),
        off_source_identical=True, scheduled_graph_identical=True,
        emitted_sources=list(source_inventory(candidate).values())))
    save(out / 'build.json', dict(feature='event_regions', backend_pair=BACKENDS[:2],
        frozen_inputs=[identity(BASE / 'build.json'), identity(Path(base['graph']['path'])),
            identity(harness), identity(CXX), identity(patch), identity(out / 'verification.json'),
            identity(out / 'structure.json'), identity(snapshot / 'manifest.json'),
            *[s['snapshot'] for s in saved_sources], *native],
        binaries={backend: identity(out / backend / 'emu') for backend in BACKENDS},
        flags=CFLAGS, scope='normalized RTL only; one structural policy, no parameter search'))
    print(json.dumps(read(out / 'structure.json') | {'emitted_sources': 'see structure.json'}, indent=2))


def verify(out):
    manifest = check(out)
    backends = (*manifest['backend_pair'], 'verilator')
    rows = {}
    for workload in ('smoke', 'coremark'):
        rows[workload] = {b: sample(out, b, workload, 'verify-' + workload, trace=True) for b in backends}
        reference = rows[workload]['verilator']
        for b, row in rows[workload].items():
            if signature(row) != signature(reference) or row['trace']['sha256'] != reference['trace']['sha256']:
                raise ValueError('functional or bus trace mismatch: ' + b)
            if row['trace']['bytes'] != row['cycles'] * 36:
                raise ValueError('incomplete trace: ' + b)
    save(out / 'functional.json', dict(status='pass', build=identity(out / 'build.json'), workloads=rows))
    print('all three backends passed smoke and CoreMark full trace')


def measure(out):
    manifest = check(out)
    backends = (*manifest['backend_pair'], 'verilator')
    functional = read(out / 'functional.json')
    if functional['build'] != identity(out / 'build.json') or functional['status'] != 'pass':
        raise ValueError('functional gate does not match build')
    warmups = {b: sample(out, b, 'coremark', 'warmup') for b in backends}
    save(out / 'measurement-policy.json', dict(pairs=8, repetitions=1, cpu=96, numa=1, aslr=False,
        warmups=warmups, ordering='ABC/CBA alternating', max_pair_attempts=2, bootstrap_seed=20261114,
        selection=manifest['feature'] + ': one static policy; no alternative candidates'))
    rows = []
    for index in range(8):
        order = backends if index % 2 == 0 else backends[::-1]
        for attempt in range(2):
            row = dict(pair=index, attempt=attempt, order=order)
            try:
                for b in order:
                    row[b] = sample(out, b, 'coremark', f'pair{index:02d}-attempt{attempt}')
                    if signature(row[b]) != signature(functional['workloads']['coremark'][b]):
                        raise ValueError('workload signature changed: ' + b)
                break
            except ValueError as error:
                if 'placement rejected:' not in str(error) or attempt:
                    raise
        rows.append(row)
        save(out / 'pairs.json', rows)
        print(f'round {index + 1}/8: {backends[1]}/{backends[0]}={row[backends[1]]["wall_s"]/row[backends[0]]["wall_s"]:.5f}, '
              f'{backends[1]}/verilator={row[backends[1]]["wall_s"]/row["verilator"]["wall_s"]:.5f}', flush=True)
    summaries = {denominator: summarize_named(rows, backends[1], denominator)
                 for denominator in (backends[0], 'verilator')}
    save(out / 'summary.json', summaries)
    with (out / 'pairs.csv').open('w') as stream:
        writer = csv.writer(stream)
        writer.writerow(['pair', 'order', *[f'{b}_{m}' for b in backends for m in ('wall_s', 'sim_s', 'init_s')]])
        for row in rows:
            writer.writerow([row['pair'], '>'.join(row['order']),
                             *[row[b][m] for b in backends for m in ('wall_s', 'sim_s', 'init_s')]])
    save(out / 'report.json', dict(build=manifest, summaries=summaries, structure=read(out / 'structure.json'),
        functional=identity(out / 'functional.json'), measurement_policy=identity(out / 'measurement-policy.json')))
    print(json.dumps(summaries, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('build', 'verify', 'measure'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--jobs', type=int, default=12)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.stage == 'build': build(out, args.tools.resolve(), args.jobs)
    elif args.stage == 'verify': verify(out)
    else: measure(out)
