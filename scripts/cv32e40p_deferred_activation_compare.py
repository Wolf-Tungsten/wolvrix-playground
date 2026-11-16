#!/usr/bin/env python3
"""Test one GrhSIM-only deferred activation reduction on the frozen CV32E40P model."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from cv32e40p_compare import CFLAGS, CXX, ROOT, environment, identity, run, sample, save, signature, summarize_named

BASE = ROOT / 'build/cv32e40p/shared-equality-validated'
BACKENDS = ('grhsim_baseline', 'grhsim_shared_deferred')
FEATURE_ENV = 'WOLVRIX_GRHSIM_SHARED_DEFERRED_ACTIVATION'


def read_json(path: Path):
    return json.loads(path.read_text())


def source_inventory(directory: Path):
    return {path.name: identity(path) for path in sorted(directory.glob('*.cpp'))}


def same_file_contents(lhs: Path, rhs: Path):
    left, right = identity(lhs), identity(rhs)
    return left['bytes'] == right['bytes'] and left['sha256'] == right['sha256']


def content_inventory(inventory):
    return {name: (entry['bytes'], entry['sha256']) for name, entry in inventory.items()}


def source_shape(directory: Path):
    declarations = 0
    occurrences = 0
    source_bytes = 0
    for path in sorted(directory.glob('*.cpp')):
        text = path.read_text()
        source_bytes += path.stat().st_size
        declarations += len(re.findall(r'\b(?:const\s+)?bool\s+grhsim_shared_change_\w+', text))
        occurrences += text.count('grhsim_shared_change_')
    return dict(cpp_files=len(list(directory.glob('*.cpp'))), source_bytes=source_bytes,
                shared_change_declarations=declarations, shared_change_references=occurrences)


def build(out: Path, jobs: int):
    if not platform.node().startswith('node030'):
        raise ValueError('build on node030 so -march=native matches the frozen binary')
    if out.exists():
        raise FileExistsError('output directory must be new: ' + str(out))
    base = read_json(BASE / 'build.json')
    base_model_name = base['backend_pair'][1]
    base_model = BASE / base_model_name
    baseline_binary = base_model / 'emu'
    if identity(baseline_binary) != base['binaries'][base_model_name]:
        raise ValueError('frozen GrhSIM binary identity mismatch')
    if identity(Path(base['graph']['path'])) != base['graph']:
        raise ValueError('frozen graph identity mismatch')

    out.mkdir(parents=True)
    (out / 'logs').mkdir()
    (out / 'firmware').symlink_to(BASE / 'firmware', target_is_directory=True)
    (out / 'verification.json').symlink_to(BASE / 'verification.json')
    (out / BACKENDS[0]).mkdir()
    shutil.copy2(baseline_binary, out / BACKENDS[0] / 'emu')

    frozen = out / 'native-frozen'
    frozen.mkdir()
    frozen_inputs = []
    for entry in base['native']:
        source = Path(entry['path'])
        if identity(source) != entry:
            raise ValueError('frozen native input changed: ' + str(source))
        target = frozen / source.name
        shutil.copy2(source, target)
        frozen_inputs.append(identity(target))

    graph = Path(base['graph']['path'])
    baseline_sources = source_inventory(base_model)
    env = environment()
    env['LD_LIBRARY_PATH'] = str(frozen)
    env['WOLVRIX_GRHSIM_SHARED_EQUALITY_DECODE'] = '1'
    off_env = dict(env)
    off_env[FEATURE_ENV] = '0'
    on_env = dict(env)
    on_env[FEATURE_ENV] = '1'

    off_source = out / 'off-source'
    run([frozen / 'cv32e40p_emit', graph, off_source, 'off'], out / 'logs/off-emit.log', env=off_env)
    off_sources = source_inventory(off_source)
    if content_inventory(off_sources) != content_inventory(baseline_sources):
        raise ValueError('feature-off emitter does not reproduce the frozen baseline C++')
    if not same_file_contents(off_source / 'normalized.json', base_model / 'normalized.json'):
        raise ValueError('feature-off normalized graph differs from the baseline')

    candidate = out / BACKENDS[1]
    run([frozen / 'cv32e40p_emit', graph, candidate, 'off'], out / 'logs/candidate-emit.log', env=on_env)
    if not same_file_contents(candidate / 'normalized.json', base_model / 'normalized.json'):
        raise ValueError('candidate changed the normalized graph')
    candidate_sources = source_inventory(candidate)
    changed_files = sorted(name for name in baseline_sources
                           if candidate_sources.get(name, {}).get('sha256') != baseline_sources[name]['sha256'])
    if not changed_files or set(candidate_sources) != set(baseline_sources):
        raise ValueError('shared deferred activation produced no bounded C++ source change')
    if not same_file_contents(candidate / 'grhsim_Cv32Bench.hpp', base_model / 'grhsim_Cv32Bench.hpp'):
        raise ValueError('candidate changed model storage/header layout')

    run(['make', '-C', candidate, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)],
        out / 'logs/compile.log')
    harness = Path(base['harness']['path'])
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', candidate, harness,
         candidate / 'libgrhsim_Cv32Bench.a', '-o', candidate / 'emu'], out / 'logs/link.log')

    structure = dict(feature='shared_deferred_activation', changed_cpp_files=changed_files,
        baseline_source_shape=source_shape(base_model), candidate_source_shape=source_shape(candidate),
        baseline_sources=list(baseline_sources.values()), candidate_sources=list(candidate_sources.values()),
        normalized_graph_equal=True, model_header_equal=True)
    save(out / 'structure.json', structure)
    save(out / 'build.json', dict(
        feature='shared_deferred_activation', feature_env=FEATURE_ENV,
        baseline_manifest=identity(BASE / 'build.json'), baseline_model=str(base_model),
        graph=base['graph'], reference_manifest=base['reference_manifest'],
        cxx=identity(CXX), flags=CFLAGS, wolvrix_head=base['wolvrix_head'],
        frozen_patch=base['patch'], frozen_native=frozen_inputs,
        harness=identity(harness), driver=identity(Path(__file__).resolve()),
        baseline_binary=identity(out / BACKENDS[0] / 'emu'), candidate_binary=identity(candidate / 'emu'),
        structure=identity(out / 'structure.json'), additional_inputs=[identity(BASE / 'verification.json')],
        backend_pair=BACKENDS, off_source_equal=True, normalized_graph_equal=True,
        model_header_equal=True))
    print(json.dumps(dict(changed_cpp_files=changed_files,
                          baseline=structure['baseline_source_shape'],
                          candidate=structure['candidate_source_shape'],
                          binaries={b: identity(out / b / 'emu') for b in BACKENDS}), indent=2))


def check_identity(out: Path, include_driver=True):
    manifest = read_json(out / 'build.json')
    entries = [manifest[key] for key in ('baseline_manifest', 'graph', 'reference_manifest', 'cxx', 'harness',
                                         'baseline_binary', 'candidate_binary', 'structure')]
    entries.extend(manifest['frozen_native'])
    entries.extend(manifest['additional_inputs'])
    entries.append(manifest['frozen_patch'])
    if include_driver:
        entries.append(manifest['driver'])
    for key in entries:
        if identity(Path(key['path'])) != key:
            raise ValueError('frozen input changed: ' + key['path'])
    if identity(BASE / 'build.json') != manifest['baseline_manifest']:
        raise ValueError('baseline manifest changed')
    return manifest


def checkpoint(out: Path):
    manifest = check_identity(out, include_driver=False)
    manifest['driver'] = identity(Path(__file__).resolve())
    save(out / 'build.json', manifest)
    check_identity(out)
    print('build manifest checkpointed to current runner source')


def verify(out: Path):
    manifest = check_identity(out)
    rows = {}
    for workload in ('smoke', 'coremark'):
        rows[workload] = {}
        for backend in BACKENDS:
            rows[workload][backend] = sample(out, backend, workload, 'verify-' + workload, trace=True)
        baseline = rows[workload][BACKENDS[0]]
        candidate = rows[workload][BACKENDS[1]]
        if signature(candidate) != signature(baseline) or candidate['trace']['sha256'] != baseline['trace']['sha256']:
            raise ValueError('feature changed workload signature or complete bus trace: ' + workload)
    save(out / 'functional.json', dict(status='pass', build=identity(out / 'build.json'), workloads=rows))
    print('functional and trace gate passed for smoke and CoreMark')


def measure(out: Path):
    manifest = check_identity(out)
    functional = read_json(out / 'functional.json')
    if functional['status'] != 'pass' or functional['build'] != identity(out / 'build.json'):
        raise ValueError('functional gate does not match build')
    warmups = {backend: sample(out, backend, 'coremark', 'warmup') for backend in BACKENDS}
    policy = dict(pairs=8, repetitions=1, warmups=warmups, cpu=96, numa=1, aslr=False,
        bootstrap_seed=20261114, max_pair_attempts=2, ratio=f'{BACKENDS[1]} / {BACKENDS[0]}',
        selection='one predeclared structural feature; no candidate search',
        ordering='alternating baseline/candidate and candidate/baseline')
    save(out / 'measurement-policy.json', policy)
    rows = []
    for index in range(8):
        order = BACKENDS if index % 2 == 0 else BACKENDS[::-1]
        for attempt in range(2):
            row = dict(pair=index, attempt=attempt, order=order)
            try:
                for backend in order:
                    row[backend] = sample(out, backend, 'coremark', f'pair{index:02d}-attempt{attempt}')
                break
            except ValueError as error:
                if 'placement rejected:' not in str(error) or attempt:
                    raise
        for backend in BACKENDS:
            if signature(row[backend]) != signature(functional['workloads']['coremark'][backend]):
                raise ValueError('paired workload signature changed: ' + backend)
        rows.append(row)
        save(out / 'pairs.json', rows)
        ratio = row[BACKENDS[1]]['wall_s'] / row[BACKENDS[0]]['wall_s']
        print(f'pair {index + 1}/8: candidate/baseline wall={ratio:.5f}', flush=True)
    summary = summarize_named(rows, BACKENDS[1], BACKENDS[0])
    save(out / 'summary.json', summary)
    with (out / 'pairs.csv').open('w') as stream:
        writer = csv.writer(stream)
        writer.writerow(['pair', 'order', *[f'{backend}_{metric}' for metric in ('wall_s', 'sim_s', 'init_s') for backend in BACKENDS]])
        for row in rows:
            writer.writerow([row['pair'], '>'.join(row['order']),
                *[row[backend][metric] for metric in ('wall_s', 'sim_s', 'init_s') for backend in BACKENDS]])
    save(out / 'report.json', dict(build=manifest, functional=identity(out / 'functional.json'),
        measurement_policy=identity(out / 'measurement-policy.json'), summary=summary,
        structure=read_json(out / 'structure.json')))
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('build', 'checkpoint', 'verify', 'measure'))
    parser.add_argument('--output', type=Path, default=ROOT / 'build/cv32e40p/shared-deferred-activation-v1')
    parser.add_argument('--jobs', type=int, default=16)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.stage == 'build': build(out, args.jobs)
    elif args.stage == 'checkpoint': checkpoint(out)
    elif args.stage == 'verify': verify(out)
    else: measure(out)


if __name__ == '__main__':
    main()
