#!/usr/bin/env python3
"""Serial, frozen three-model XiangShan ablation measurement on CPU96."""
import argparse
from contextlib import contextmanager
import csv
import fcntl
import json
import os
from pathlib import Path
import platform
import resource
import time

from grhsim_single_baseline import Baseline, ROOT, XS, cpus, identity, save
from grhsim_difftrace import build_comparator, compare_traces, validate_trace_coverage
from grhsim_single_compare import build_modes, summarize

VARIANTS = ('full', 'no_shared', 'no_cones')
CYCLES = 100000
ROUNDS = 8
LOCK = ROOT / 'build/xs/xiangshan-cpu96-measure.lock'


def read(path):
    return json.loads(Path(path).read_text())


def verify(record):
    if identity(record['path']) != record:
        raise ValueError('frozen file changed: ' + record['path'])


def order_for_round(index):
    return VARIANTS if index % 2 == 0 else VARIANTS[::-1]


def signature(row):
    # Include termination and DiffTest mode as well as architectural progress.
    return {key: row[key] for key in ('pc', 'instr_count', 'cycle_count',
        'guest_cycles', 'stop_reason', 'workload_output', 'runtime_difftest')}


def summaries(rounds):
    if len(rounds) != ROUNDS:
        raise ValueError('summary requires all eight predeclared rounds')
    result = {}
    for name in VARIANTS[1:]:
        result[name] = {}
        for metric in ('host_ms', 'external_wall_s'):
            scale = 1000 if metric == 'external_wall_s' else 1
            rows = []
            for row in rounds:
                values = {side: row[variant][metric] * scale
                          for side, variant in (('A', 'full'), ('B', name))}
                if any(not 0 < value < float('inf') for value in values.values()):
                    raise ValueError('nonpositive or nonfinite time')
                rows.append({side: dict(host_ms=value) for side, value in values.items()})
            result[name][metric] = dict(summarize(rows), baseline='full', candidate=name,
                                       metric=metric, ratio='candidate/full')
    return result


@contextmanager
def measurement_lock(path=LOCK):
    """Fail promptly if another cooperating measurement owns CPU96."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            stream.seek(0)
            raise RuntimeError('CPU96 measurement lock is held: ' + stream.read().strip()) from error
        try:
            stream.seek(0); stream.truncate()
            json.dump(dict(pid=os.getpid(), host=platform.node(), acquired=time.time()), stream)
            stream.flush()
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def freeze(source, image, nemu):
    files = [identity(source/'policy.json'), identity(image), identity(nemu)]
    nested_inputs = source/'inputs.json'
    if nested_inputs.exists():
        files.append(identity(nested_inputs))
        entries = read(nested_inputs)
        if not isinstance(entries, list):
            raise ValueError('inputs.json must contain a list of frozen file identities')
        for record in entries:
            verify(record)
            files.append(record)
    models = {}
    common = None
    for name in VARIANTS:
        model = (source/name).resolve()
        settings_path = model/'configuration.json'
        binary_path = model/'binary.json'
        sources_path = model/'model-sources.json'
        settings = read(settings_path)
        binary = read(binary_path); verify(binary)
        if Path(binary['path']).resolve() != (model/'emu/grhsim-compile/emu').resolve():
            raise ValueError(name + ': binary manifest points outside expected model path')
        modes = build_modes(settings, settings.get('runtime_difftest', 'on'))
        if settings.get('runtime_difftest') != 'on' or any(mode != 'on' for mode in modes.values()):
            raise ValueError(name + ': full RTL/model/compile/runtime DiffTest required')
        comparable = {key: settings.get(key) for key in ('config', 'guest_cores',
            'sim_primitives', 'sim_models', 'behavior_state_lowering', 'behavior_compute_lowering',
            'model_flags', 'harness_flags', 'storage_ref_aliases')}
        if common is None: common = comparable
        elif comparable != common: raise ValueError(name + ': non-ablation build settings differ')
        source_records = read(sources_path)
        for record in source_records: verify(record)
        declared = {Path(record['path']).resolve() for record in source_records}
        actual = {p.resolve() for p in (model/'model').iterdir()
                  if p.suffix in ('.cpp', '.hpp') or p.name == 'Makefile'}
        if actual != declared:
            raise ValueError(name + ': model source manifest does not cover exact source set')
        header = identity(model/'chisel-home/build/generated-src/difftest-state.h')
        files += [identity(settings_path), identity(binary_path), identity(sources_path), binary, header]
        files += source_records
        for key, actual_input in (('image', image), ('nemu', nemu)):
            if key in settings:
                expected = settings[key]
                observed = identity(actual_input)
                if expected is None or any(expected[k] != observed[k] for k in ('bytes', 'sha256')):
                    raise ValueError(name + ': workload/reference differs from build')
        models[name] = dict(directory=str(model), configuration=settings, binary=binary, schema=header)
    if len({model['schema']['sha256'] for model in models.values()}) != 1:
        raise ValueError('generated DiffTest schemas differ')
    for name in ('xiangshan_cv32_ablation_measure.py', 'grhsim_single_baseline.py',
                 'grhsim_single_compare.py', 'grhsim_difftrace.py', 'grhsim_numa.py',
                 'simulation_model_modes.py'):
        files.append(identity(ROOT/'scripts'/name))
    unique = {record['path']: record for record in files}
    return dict(models=models, files=list(unique.values()), source=str(source),
        image=identity(image), nemu=identity(nemu), common_build_settings=common)


def check_frozen(manifest):
    for record in manifest['files']: verify(record)


def run_protocol(out, runners, prepared, comparator, manifest):
    """All simulator starts go through this sequential loop; no workers."""
    def sample(name, label, cycles=CYCLES, seed=0, extra=()):
        return runners[name].run_sample(prepared[name], label, cycles, seed, extra)

    smoke = {name: sample(name, 'smoke', 10000) for name in VARIANTS}
    if any(signature(row) != signature(smoke['full']) for row in smoke.values()):
        raise ValueError('smoke signatures differ')
    save(out/'smoke.json', smoke)
    references = {}; traces = {}
    for seed in (0, 1):
        rows = {name: sample(name, f'verify-s{seed}', seed=seed,
                    extra=['--dump-difftrace', f'./trace_s{seed}']) for name in VARIANTS}
        if any(signature(row) != signature(rows['full']) for row in rows.values()):
            raise ValueError('trace run signatures differ')
        references[seed] = rows
        paths = {name: prepared[name]['binary'].parent/f'trace_s{seed}' for name in VARIANTS}
        traces[seed] = {}
        for name in VARIANTS[1:]:
            path = out/f'trace-{name}-s{seed}.json'
            record = compare_traces(comparator, paths['full'], paths[name], path)
            record['coverage'] = [validate_trace_coverage(record, rows[v]) for v in ('full', name)]
            save(path, record); traces[seed][name] = record
    check_frozen(manifest)
    save(out/'functional.json', dict(status='pass', smoke=smoke, traces=traces,
        verification_runs=references, scope='10k smoke and two 100k-cycle CoreMark windows; not full workload completion'))
    warmups = {name: sample(name, 'warmup') for name in VARIANTS}
    expected = signature(references[0]['full'])
    if any(signature(row) != expected for row in warmups.values()):
        raise ValueError('warmup signature differs from verified seed 0')
    save(out/'warmups.json', warmups)
    rounds = []
    for index in range(ROUNDS):
        row = dict(round=index, order=list(order_for_round(index)))
        for name in row['order']:
            value = sample(name, f'round{index:02d}')
            if signature(value) != expected:
                raise ValueError(name + ': formal signature differs from verified seed 0')
            row[name] = value
        rounds.append(row); save(out/'rounds.json', rounds)
        print(f'round {index + 1}/{ROUNDS} complete', flush=True)
    check_frozen(manifest)
    summary = dict(status='pass', comparisons=summaries(rounds), rounds=rounds,
        functional_signature=expected, trace_checks=traces,
        scope='Same-round paired comparisons against full; Host time includes harness and NEMU.',
        manifest=identity(out/'manifest.json'), policy=identity(out/'measurement-policy.json'))
    save(out/'summary.json', summary)
    with (out/'samples.csv').open('w') as stream:
        writer = csv.writer(stream)
        writer.writerow(['round', 'order', 'variant', 'host_s', 'external_wall_s'])
        for row in rounds:
            for name in row['order']:
                writer.writerow([row['round'], '>'.join(row['order']), name,
                                 row[name]['host_ms']/1000, row[name]['external_wall_s']])
    print(json.dumps(summary['comparisons'], indent=2), flush=True)
    return summary


def measure(source, out, image, nemu):
    if not platform.node().startswith('node030'):
        raise ValueError('measure on node030')
    source, out = Path(source).resolve(), Path(out).resolve()
    # Hold the lock across setup, functional runs, warmup, and formal samples.
    with measurement_lock():
        manifest = freeze(source, image, nemu)
        out.mkdir(parents=True, exist_ok=False)
        try:
            save(out/'manifest.json', manifest)
            save(out/'measurement-policy.json', dict(variants=VARIANTS, cycles=CYCLES,
                rounds=ROUNDS, smoke_cycles=10000, verification_seeds=[0, 1],
                order=[order_for_round(i) for i in range(ROUNDS)], warmups_per_variant=1,
                bootstrap_seed=20261102, bootstrap_resamples=10000, cpu=96, numa=1,
                threads=1, aslr=False, runtime_difftest='on', performance_trace=False,
                lock=str(LOCK), max_sample_attempts=1, skip_external_idle_admission=True,
                checks='Mandatory affinity/thread/NUMA and functional gates; all formal samples retained.',
                feedback='No generation, thresholds, candidate selection or additional rounds from measurements.'))
            os.sched_setaffinity(0, cpus(Path('/sys/devices/system/cpu/online').read_text()))
            resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
            comparator = build_comparator(manifest['models']['full']['schema']['path'], out/'trace-comparator')
            runners = {}; prepared = {}
            for name in VARIANTS:
                model = manifest['models'][name]; settings = model['configuration']
                config = argparse.Namespace(output=out/name, binary=Path(model['binary']['path']),
                    image=Path(image), nemu=Path(nemu),
                    compiler='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++', tools_dir=None,
                    sim_primitives=settings.get('sim_primitives', 'none'),
                    sim_models=settings.get('sim_models', 'hardware'),
                    behavior_state_lowering=settings.get('behavior_state_lowering', 'ordinary'),
                    behavior_compute_lowering=settings.get('behavior_compute_lowering', 'ordinary'),
                    rtl_difftest='on', model_difftest='on', compile_difftest='on', runtime_difftest='on',
                    simulator='grhsim', xs_config=settings.get('config', 'DefaultConfig'),
                    skip_idle_check=True, cpu=96, jobs=1, cycles=CYCLES, repeats=ROUNDS)
                runners[name] = Baseline(config)
                prepared[name] = runners[name].prepare_measurement()
            runtime_sources = {}
            for name in VARIANTS:
                for record in prepared[name]['plan']['files']:
                    original = record['source']; verify(original)
                    runtime_sources[original['path']] = original
            known = {record['path'] for record in manifest['files']}
            manifest['files'] += [record for path, record in runtime_sources.items() if path not in known]
            save(out/'manifest.json', manifest)
            check_frozen(manifest)
            return run_protocol(out, runners, prepared, comparator, manifest)
        except Exception as error:
            save(out/'failure.json', dict(error=str(error), type=type(error).__name__, time=time.time(),
                 note='No retry or additional candidate; partial raw records retained.'))
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image', type=Path, default=XS/'ready-to-run/coremark-2-iteration.bin')
    parser.add_argument('--nemu', type=Path, default=XS/'ready-to-run/riscv64-nemu-interpreter-so')
    args = parser.parse_args()
    measure(args.source, args.output, args.image.resolve(), args.nemu.resolve())
