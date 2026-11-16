#!/usr/bin/env python3
"""Replay one frozen CV32E40P graph to validate one structural lowering."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from cv32e40p_compare import (ROOT, CXX, CFLAGS, environment, run, identity, save,
                             check_build_identity, sample, signature, summarize_named)

BACKENDS = ('grhsim_baseline', 'grhsim_indexed')


def backend_names(manifest):
    return tuple(manifest.get('backend_pair', BACKENDS))


def build(out, baseline, tools, jobs, reference=None, lowering="indexed_concat_slice"):
    if not platform.node().startswith('node030'): raise ValueError('build on node030')
    check_build_identity(baseline)
    reference_model = baseline / 'grhsim'
    reference_manifest = None
    if reference is not None:
        parent = check_identity(reference)
        reference_model = reference / backend_names(parent)[1]
        reference_manifest = identity(reference / 'build.json')
    elif lowering != 'indexed_concat_slice':
        raise ValueError('this lowering requires the preceding frozen reference')
    backends = ('grhsim_baseline', 'grhsim_indexed' if lowering == 'indexed_concat_slice' else 'grhsim_packed_slices')
    out.mkdir(parents=True, exist_ok=False)
    for name in ('firmware', 'verification.json'):
        (out / name).symlink_to(baseline / name)
    (out / backends[0]).mkdir()
    shutil.copy2(reference_model / 'emu', out / backends[0] / 'emu')
    patch = subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'diff', '--binary'])
    (out / 'wolvrix.patch').write_bytes(patch)
    frozen = out / 'native-frozen'; frozen.mkdir()
    for path in (tools / 'cv32e40p_emit', tools / 'grhsim32/wolvrix/libwolvrix-lib.so'):
        shutil.copy2(path, frozen / path.name)
    env = environment(); env['LD_LIBRARY_PATH'] = str(frozen)
    # The opt-out must reproduce every original compute/state source. The new
    # unused runtime template alone may differ; do not rebuild the old binary.
    env_off = dict(env)
    env_off['WOLVRIX_GRHSIM_' + lowering.upper()] = '0'
    if lowering == 'indexed_concat_slice':
        env['WOLVRIX_GRHSIM_PACKED_SCALAR_SLICES'] = '0'
        env_off['WOLVRIX_GRHSIM_PACKED_SCALAR_SLICES'] = '0'
    run([frozen / 'cv32e40p_emit', baseline / 'graph.json', out / 'off-source', 'off'],
        out / 'logs/off-emit.log', env=env_off)
    original = {p.name: identity(p)['sha256'] for p in reference_model.glob('*.cpp')}
    disabled = {p.name: identity(p)['sha256'] for p in (out / 'off-source').glob('*.cpp')}
    if original != disabled: raise ValueError('opt-out differs from frozen baseline C++')
    model = out / backends[1]
    run([frozen / 'cv32e40p_emit', baseline / 'graph.json', model, 'off'], out / 'logs/emit.log', env=env)
    if identity(model / 'normalized.json')['sha256'] != identity(baseline / 'grhsim/normalized.json')['sha256']:
        raise ValueError('scheduled graph changed')
    run(['make', '-C', model, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)],
        out / 'logs/compile.log')
    harness = baseline / 'inputs/fixture/harness.cpp'
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', model, harness, model / 'libgrhsim_Cv32Bench.a',
         '-o', model / 'emu'], out / 'logs/link.log')
    matches = []; slice_groups = []
    for p in sorted(model.glob('*_sched_*.cpp')):
        for match in re.finditer(r'const auto grhsim_concat_word_(\d+) =', p.read_text()):
            matches.append(dict(file=p.name, value_id=int(match[1])))
        slice_groups.extend(dict(file=p.name, first_value=int(m[1])) for m in re.finditer(r'const auto grhsim_slice_changes_(\d+) =', p.read_text()))
    save(out / 'build.json', dict(baseline=str(baseline), graph=identity(baseline / 'graph.json'),
        baseline_manifest=identity(baseline / 'build.json'), reference_model=str(reference_model),
        reference_manifest=reference_manifest, backend_pair=backends, lowering=lowering, cxx=identity(CXX), flags=CFLAGS,
        wolvrix_head=subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'rev-parse', 'HEAD'], text=True).strip(),
        patch=identity(out / 'wolvrix.patch'), native=[identity(p) for p in sorted(frozen.iterdir())],
        harness=identity(harness), driver=identity(__file__), binaries={b: identity(out / b / 'emu') for b in backends},
        off_source_equal=True, scheduled_graph_equal=True, indexed_concats=matches, packed_slice_groups=slice_groups))


def check_identity(out):
    manifest = json.loads((out / 'build.json').read_text())
    check_build_identity(Path(manifest['baseline']))
    for entry in [manifest['graph'], manifest['patch'], manifest['harness'], manifest['cxx'],
                  *manifest['binaries'].values(), *manifest['native'], *manifest.get('additional_inputs', [])]:
        if identity(entry['path']) != entry: raise ValueError('frozen input changed: ' + entry['path'])
    if manifest.get('reference_manifest'):
        entry = manifest['reference_manifest']
        if identity(entry['path']) != entry: raise ValueError('reference build changed')
    if (out / 'verilator-reference.json').exists():
        entries = json.loads((out / 'verilator-reference.json').read_text())
        for entry in entries.values():
            if identity(entry['path']) != entry: raise ValueError('Verilator reference changed')
    return manifest


def measured_backends(out, manifest):
    names = backend_names(manifest)
    if not (out / 'verilator-reference.json').exists(): return names
    references = json.loads((out / 'verilator-reference.json').read_text())
    return (*names, *references)


def attach_verilator(out):
    manifest = check_identity(out)
    references = {}
    for backend in ('verilator', 'verilator-original'):
        target = out / backend
        target.mkdir(exist_ok=False)
        shutil.copy2(Path(manifest['baseline']) / backend / 'emu', target / 'emu')
        references[backend] = identity(target / 'emu')
    save(out / 'verilator-reference.json', references)


def verify(out):
    backends = measured_backends(out, check_identity(out))
    prior = json.loads((out / 'verification.json').read_text())
    rows = {}
    for workload in ('smoke', 'coremark'):
        rows[workload] = {}
        expected = prior['workloads'][workload]['grhsim']
        for backend in backends:
            row = sample(out, backend, workload, 'verify-' + workload, trace=True)
            if signature(row) != signature(expected) or row['trace']['sha256'] != expected['trace']['sha256']:
                raise ValueError('functional/trace difference: ' + backend)
            rows[workload][backend] = row
    save(out / 'functional.json', dict(status='pass', build=identity(out / 'build.json'), workloads=rows))


def measure(out):
    manifest = check_identity(out)
    backends = measured_backends(out, manifest)
    gate = json.loads((out / 'functional.json').read_text())
    if gate['status'] != 'pass' or gate['build'] != identity(out / 'build.json'):
        raise ValueError('functional gate does not match build')
    warmups = {b: sample(out, b, 'coremark', 'warmup') for b in backends}
    save(out / 'measurement-policy.json', dict(pairs=8, repetitions=1, warmups=warmups,
        cpu=96, numa=1, aslr=False, max_pair_attempts=2, bootstrap_seed=20261114,
        ratio=f'{backends[1]} / {backends[0]}', selection='single structural implementation; no candidate search', backends=backends,
        ordering='forward/reverse round; same round supplies each paired ratio'))
    rows = []
    for i in range(8):
        order = backends if i % 2 == 0 else backends[::-1]
        for attempt in range(2):
            row = dict(pair=i, attempt=attempt, order=order)
            try:
                for backend in order:
                    row[backend] = sample(out, backend, 'coremark', f'pair{i:02d}-attempt{attempt}')
                break
            except ValueError as error:
                if 'placement rejected:' not in str(error) or attempt: raise
        rows.append(row); save(out / 'pairs.json', rows)
        print(f'pair {i+1}/8: {backends[1]}/{backends[0]} wall={row[backends[1]]["wall_s"]/row[backends[0]]["wall_s"]:.4f}', flush=True)
    save(out / 'summary.json', summarize_named(rows, backends[1], backends[0]))
    for reference in ('verilator', 'verilator-original'):
        if reference in backends:
            save(out / f'{reference}-summary.json', summarize_named(rows, backends[1], reference))
    with (out / 'pairs.csv').open('w') as stream:
        writer = csv.writer(stream)
        writer.writerow(['pair', 'order', *[f'{b}_{m}' for m in ('wall_s', 'sim_s', 'init_s') for b in backends]])
        for row in rows: writer.writerow([row['pair'], '>'.join(row['order']), *[row[b][m] for m in ('wall_s', 'sim_s', 'init_s') for b in backends]])


def profile(out):
    backends = backend_names(check_identity(out))
    for backend in backends:
        sample(out, backend, 'coremark', 'perf-stat', perf=['stat', '-x,', '-o', out / f'{backend}-stat.csv',
            '-e', 'cycles:u,instructions:u,branches:u,branch-misses:u'])
        sample(out, backend, 'coremark', 'perf-record', perf=['record', '-o', out / f'{backend}-perf.data',
            '-e', 'cycles:u', '-F', '199', '--call-graph', 'dwarf,8192'])
        run(['perf', 'report', '--stdio', '--no-children', '-i', out / f'{backend}-perf.data'],
            out / f'{backend}-perf.txt')


def report(out):
    manifest = check_identity(out)
    backends = backend_names(manifest)
    data = json.loads((out / 'summary.json').read_text())
    gate = json.loads((out / 'functional.json').read_text())
    data['build'] = manifest
    if (out / 'structure.json').exists():
        data['structure'] = json.loads((out / 'structure.json').read_text())
    for reference in ('verilator', 'verilator-original'):
        if (out / f'{reference}-summary.json').exists():
            data['versus_' + reference.replace('-', '_')] = json.loads((out / f'{reference}-summary.json').read_text())
    data['functional'] = dict(status=gate['status'], **signature(gate['workloads']['coremark'][backends[1]]),
        trace_sha256=gate['workloads']['coremark'][backends[1]]['trace']['sha256'])
    data['cycles_per_second'] = {b: data['functional']['cycles'] / data['sim_s'][b + '_mean'] for b in backends}
    data['wall_reduction_percent'] = 100 * (1 - data['wall_s']['ratio_mean'])
    data['wall_reduction_ci95_percent'] = [100 * (1 - x) for x in reversed(data['wall_s']['ratio_ci95'])]
    data['diagnostics'] = {}
    for backend in backends:
        counters = {}
        path = out / f'{backend}-stat.csv'
        if path.exists():
            for fields in csv.reader(path.open()):
                if len(fields) >= 5 and fields[2].endswith(':u'):
                    counters[fields[2]] = dict(count=float(fields[0]), running_percent=float(fields[4]),
                        per_guest_cycle=float(fields[0]) / data['functional']['cycles'])
        path = out / f'{backend}-perf.txt'
        hotspots = []
        if path.exists():
            for percent, symbol in re.findall(r'^\s*([\d.]+)%\s+\S+\s+\S+\s+\[.\] (.+)$', path.read_text(), re.M):
                hotspots.append(dict(percent=float(percent), symbol=symbol))
        data['diagnostics'][backend] = dict(counters=counters, hotspots=hotspots)
    baseline_sources = Path(manifest.get('reference_model', str(Path(manifest['baseline']) / 'grhsim')))
    before = {p.name: p for p in baseline_sources.glob('*.cpp')}
    after = {p.name: p for p in (out / backends[1]).glob('*.cpp')}
    data['changed_cpp'] = [dict(file=name, before_bytes=before[name].stat().st_size if name in before else None,
                               after_bytes=after[name].stat().st_size if name in after else None)
        for name in sorted(before.keys() | after.keys())
        if name not in before or name not in after or before[name].read_bytes() != after[name].read_bytes()]
    data['build_wall_s'] = {p.stem.removesuffix('.result'): json.loads(p.read_text())['wall_s']
                          for p in sorted((out / 'logs').glob('*.result.json'))}
    rows = json.loads((out / 'pairs.json').read_text())
    checked_backends = measured_backends(out, manifest)
    data['measurement_checks'] = dict(samples=len(rows) * len(checked_backends),
        retries=sum(r['attempt'] for r in rows),
        placement_errors=sum(len(r[b]['placement_errors']) for r in rows for b in checked_backends),
        sibling_idle_percent=[r[b]['cpu_idle_percent']['288'] for r in rows for b in checked_backends])
    save(out / 'report.json', data)
    print(json.dumps({k: data[k] for k in ('pairs', 'ratio_definition', 'wall_s', 'wall_reduction_percent')}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['build', 'attach-verilator', 'verify', 'measure', 'profile', 'report'])
    parser.add_argument('--output', type=Path, default=ROOT / 'build/cv32e40p/indexed-concat-v1')
    parser.add_argument('--baseline', type=Path, default=ROOT / 'build/cv32e40p/run2')
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--jobs', type=int, default=16)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--lowering', choices=['indexed_concat_slice', 'packed_scalar_slices'], default='indexed_concat_slice')
    args = parser.parse_args(); out = args.output.resolve()
    if args.stage == 'build': build(out, args.baseline.resolve(), args.tools.resolve(), args.jobs,
                                    args.reference.resolve() if args.reference else None, args.lowering)
    elif args.stage == 'attach-verilator': attach_verilator(out)
    else: globals()[args.stage](out)


if __name__ == '__main__':
    main()
