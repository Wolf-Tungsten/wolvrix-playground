#!/usr/bin/env python3
"""Pair two frozen performance-mode RepCut builds using the production runtime setup."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import threading
import time

from grhsim32 import Pipeline, ROOT, cpu_list, enable_generation_cpus, read, save
from grhsim_numa import inspect_locality, locality_errors, runtime_plan
from grhsim_single_baseline import identity, parse_run
from grhsim_single_compare import pair_order, summarize


def validate_builds(configs, results):
    for name in ('A', 'B'):
        if configs[name].get('performance') is not True or results[name].get('performance') is not True:
            raise ValueError(name + ': a completed --performance build is required')
        if results[name].get('status') != 'pass':
            raise ValueError(name + ': build has not passed its functional gate')
        if not results[name].get('aslr_disabled') or results[name].get('numa_node') is None:
            raise ValueError(name + ': ASLR/NUMA placement was not enabled')
        if len(set(configs[name]['runtime_cpus'])) != 32:
            raise ValueError(name + ': expected 32 distinct CPUs')
        if configs[name]['runtime_cpus'] != results[name]['runtime_cpus']:
            raise ValueError(name + ': build/result CPU sets differ')
    for key in ('runtime_cpus', 'codepages'):
        if configs['A'][key] != configs['B'][key]:
            raise ValueError('before/after runtime configuration differs: ' + key)
    if results['A']['numa_node'] != results['B']['numa_node']:
        raise ValueError('before/after NUMA node differs')


def validate_runtime(config, cpus):
    if config.get('lanes') != 32 or config.get('thread_pinning') != 'enabled':
        raise ValueError('expected 32 pinned RepCut lanes')
    if config.get('worker_cpus') != cpus or config.get('part_cpus') != cpus:
        raise ValueError('runtime CPUs differ from frozen configuration')


def validate_thread_placement(samples, cpus, expected_threads):
    if expected_threads != len(cpus):
        raise ValueError('runtime thread count differs from the CPU set')
    full = [sample for sample in samples if len(sample['tasks']) == expected_threads]
    if not full:
        raise ValueError('no complete runtime thread placement observed')
    # Ignore construction and teardown transients. Do not depend on stdout
    # flushing the DiffTest banner before checking actual /proc affinity.
    ready = [sample for sample in full if sample['elapsed_s'] >= 1] or full[-1:]
    for sample in ready:
        masks = [task['cpus'] for task in sample['tasks']]
        if any(len(mask) != 1 for mask in masks) or sorted(mask[0] for mask in masks) != sorted(cpus):
            raise ValueError('runtime threads are not pinned one per configured CPU')


def bind_runtime_memory(command, node):
    preferred = f'--preferred={node}'
    bound = f'--membind={node}'
    if sum(arg in (preferred,bound) for arg in command) != 1:
        raise ValueError('expected one explicit runtime NUMA policy for the configured node')
    return [bound if arg == preferred else arg for arg in command]


def signature(row):
    return {key: row[key] for key in
            ('pc', 'instr_count', 'cycle_count', 'guest_cycles', 'stop_reason', 'workload_output')}


class Runner:
    def __init__(self, build, directory, config, result, image, nemu):
        self.directory = directory
        directory.mkdir(parents=True)
        save(directory / 'config.json', config['config'])
        args = argparse.Namespace(config=directory / 'config.json', output=build,
                                  xs_config=config.get('xs_config', 'DefaultConfig'), jobs=1,
                                  performance=True, runtime_cpus=','.join(map(str, config['runtime_cpus'])),
                                  image=image, nemu=nemu, codepages=config['codepages'])
        self.pipeline = Pipeline(args)
        self.pipeline.configure_runtime()
        self.node = result['numa_node']
        if not self.pipeline.aslr_off or self.pipeline.numa != self.node:
            raise ValueError('runtime placement no longer matches the build')
        self.original = identity(build / result['retained'] / 'harness/grhsim-compile/emu')
        plan = runtime_plan(self.original['path'], nemu, image, directory / 'runtime',
                            self.pipeline.runtime[0], self.node, self.pipeline.env)
        preloads = self.pipeline._runtime_env()['LD_PRELOAD'].split(':')
        for path in preloads:
            plan['files'].append(dict(role='library', source=identity(path),
                                      destination=str(directory / 'runtime/lib' / Path(path).name)))
        save(directory / 'runtime_plan.json', plan)
        self.pipeline.run_command(['taskset', '-c', str(self.pipeline.runtime[0]), 'numactl',
                                   f'--membind={self.node}', sys.executable, ROOT / 'scripts/grhsim_numa.py',
                                   directory / 'runtime_plan.json'], directory / 'prefault.log')
        self.plan = read(directory / 'runtime/manifest.json')
        self.binary = directory / 'runtime/bin/emu'
        self.pipeline.args.image = directory / 'runtime/image/workload.bin'
        self.pipeline.args.nemu = directory / 'runtime/ref/nemu.so'
        self.pipeline.env['LD_LIBRARY_PATH'] = str(directory / 'runtime/lib')
        self.preload = ':'.join(str(directory / 'runtime/lib' / Path(path).name) for path in preloads)
        self.frozen = identity(self.binary)

    def run(self, name, cycles):
        prefix = self.directory / name
        command, env = self.pipeline._runtime_command(self.binary, cycles,
                                                       timing_path=prefix.with_suffix('.timing.jsonl'))
        # The paired locality gate requires all model/state pages on this
        # node. A preferred policy may allocate remotely under pressure.
        command = bind_runtime_memory(command, self.node)
        command = ['LD_PRELOAD=' + self.preload if str(arg).startswith('LD_PRELOAD=') else str(arg)
                   for arg in command]
        command += ['-s', '0']
        recorded_env = {key: value for key, value in env.items()
                        if key.startswith(('WOLVI_', 'WOLVRIX_', 'XS_', 'EMU_', 'REPCUT_'))
                        or key in ('LC_ALL', 'NOOP_HOME', 'LD_LIBRARY_PATH')}
        save(prefix.with_suffix('.command.json'), dict(command=command, env=recorded_env))
        samples, errors, observed = [], [], set()
        start = time.monotonic()
        with prefix.with_suffix('.log').open('w') as log:
            process = subprocess.Popen(command, cwd=self.binary.parent, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            done = threading.Event()
            completion = {}

            def wait():
                completion['code'] = process.wait()
                completion['wall_s'] = time.monotonic() - start
                done.set()

            watcher = threading.Thread(target=wait)
            watcher.start()
            while not done.is_set():
                try:
                    proc = Path('/proc') / str(process.pid)
                    text = prefix.with_suffix('.log').read_text()
                    if (proc / 'exe').resolve() == self.binary and '[runtime-config]' in text:
                        maps = (proc / 'maps').read_text()
                        numa = (proc / 'numa_maps').read_text()
                        record = inspect_locality(maps, numa, self.plan)
                        record['elapsed_s'] = time.monotonic() - start
                        local_errors = locality_errors(record, self.node)
                        if local_errors and not prefix.with_suffix('.nonlocal.numa_maps').exists():
                            prefix.with_suffix('.nonlocal.maps').write_text(maps)
                            prefix.with_suffix('.nonlocal.numa_maps').write_text(numa)
                            save(prefix.with_suffix('.nonlocal.json'),dict(elapsed_s=record['elapsed_s'],errors=local_errors))
                        errors.extend(local_errors)
                        tasks = []
                        for task in (proc / 'task').iterdir():
                            status = (task / 'status').read_text()
                            mask = re.search(r'^Cpus_allowed_list:\s*(.*)$', status, re.M)[1]
                            allowed = cpu_list(mask)
                            tasks.append(dict(tid=int(task.name),cpus=allowed))
                            if not set(allowed) <= set(self.pipeline.runtime):
                                errors.append(dict(affinity=allowed))
                        record['tasks'] = tasks
                        observed.add(len(tasks))
                        if not samples:
                            prefix.with_suffix('.maps').write_text(maps)
                            prefix.with_suffix('.numa_maps').write_text(numa)
                            personality = int((proc / 'personality').read_text(), 16)
                            if not personality & 0x40000:
                                errors.append(dict(aslr_not_disabled=True))
                        samples.append(record)
                except (FileNotFoundError, ProcessLookupError):
                    pass
                done.wait(1 if samples else .1)
            watcher.join()
        save(prefix.with_suffix('.locality.json'), dict(samples=samples, errors=errors))
        if completion['code']:
            raise ValueError(f'{name}: emulator exited {completion["code"]}')
        log = prefix.with_suffix('.log').read_text()
        row = parse_run(log, cycles)
        configs = re.findall(r'^\[runtime-config\] (\{.*\})$', log, re.M)
        if len(configs) != 1:
            raise ValueError('missing or ambiguous runtime-config')
        runtime = json.loads(configs[0])
        validate_runtime(runtime, self.pipeline.runtime)
        expected_threads = 1 + runtime['background_workers']
        if expected_threads not in observed or max(observed, default=0) > expected_threads:
            errors.append(dict(thread_counts=sorted(observed), expected=expected_threads))
        try:
            validate_thread_placement(samples, self.pipeline.runtime, expected_threads)
        except ValueError as error:
            errors.append(dict(thread_placement=str(error)))
        pages = re.findall(r'\[codepage\] PASS mode=(\w+) bytes=(\d+) anon_huge=(\d+) regions=(\d+)', log)
        if len(pages) != 1:
            errors.append(dict(codepage_pass_missing=True))
        if not samples or not any(sample['groups'].get('anonymous', {}).get('pages', {}).get(str(self.node), 0)
                                  for sample in samples):
            errors.append(dict(no_local_anonymous_state=True))
        seen = {path for sample in samples for path in sample['seen_files']}
        required = {entry['destination'] for entry in self.plan['files'] if entry['role'] in ('binary','library')}
        if not required <= seen:
            errors.append(dict(missing_runtime_mappings=sorted(required-seen)))
        if errors:
            save(prefix.with_suffix('.rejected.json'), dict(errors=errors))
            raise ValueError(name + ': placement/locality/codepage gate failed')
        if identity(self.binary) != self.frozen:
            raise ValueError('frozen binary changed')
        for entry in self.plan['files']:
            if identity(entry['destination']) != entry['copy']:
                raise ValueError('runtime dependency changed: ' + entry['destination'])
        row.update(name=name, external_wall_s=completion['wall_s'], runtime=runtime,
                   codepages=pages[0], locality_pass=True, thread_counts=sorted(observed),
                   numa_policy='bind', numa_node=self.node,
                   binary_sha256=self.frozen['sha256'])
        save(prefix.with_suffix('.json'), row)
        print(json.dumps(dict(name=name,host_ms=row['host_ms'],wall_s=row['external_wall_s'])), flush=True)
        return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', required=True, type=Path)
    p.add_argument('--candidate', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--image', required=True, type=Path)
    p.add_argument('--nemu', required=True, type=Path)
    p.add_argument('--pairs', type=int, default=8)
    p.add_argument('--cycles', type=int, default=100000)
    args = p.parse_args()
    if not platform.node().startswith('node030') or args.pairs < 8 or args.cycles < 100000:
        p.error('requires node030, at least 8 pairs and 100000 cycles')
    enable_generation_cpus()
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    builds = dict(A=args.baseline.resolve(), B=args.candidate.resolve())
    configs = {key: read(path / 'configuration.json') for key, path in builds.items()}
    results = {key: read(path / 'result.json') for key, path in builds.items()}
    validate_builds(configs, results)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'manifest.json', dict(builds={key: str(path) for key, path in builds.items()},
                                    configurations=configs, results=results, image=identity(args.image),
                                    nemu=identity(args.nemu), driver=identity(__file__),
                                    pipeline=identity(ROOT / 'scripts/grhsim32.py'),
                                    numa_policy='bind',
                                    pairs=args.pairs, cycles=args.cycles, order=pair_order(args.pairs)))
    runners = {key: Runner(path, out / key, configs[key], results[key], args.image, args.nemu)
               for key, path in builds.items()}
    monitor = next(cpu for cpu in sorted(os.sched_getaffinity(0)) if cpu not in configs['A']['runtime_cpus'])
    os.sched_setaffinity(0, {monitor})
    signatures = {}
    for key, runner in runners.items():
        runner.run('smoke', 10000)
        signatures[key] = signature(runner.run('verify', args.cycles))
        if signature(runner.run('warmup', args.cycles)) != signatures[key]:
            raise ValueError(key + ': warmup signature differs from verification')
    save(out / 'functional.json', dict(pass_=True, variants=signatures,
         differences={key: [signatures['A'][key], signatures['B'][key]] for key in signatures['A']
                      if signatures['A'][key] != signatures['B'][key]},
         scope='Each revision independently passes full NEMU; fixed-cycle progress may differ across microarchitectures'))
    rows = []
    runtime = None
    for index, order in enumerate(pair_order(args.pairs)):
        row = dict(pair=index, order=order)
        for key in order:
            sample = runners[key].run(f'pair{index:02d}', args.cycles)
            if signature(sample) != signatures[key]:
                raise ValueError(key + ': functional signature changed within a revision')
            if runtime is None:
                runtime = sample['runtime']
            if sample['runtime'] != runtime:
                raise ValueError('runtime configuration changed across paired runs')
            row[key] = sample
        rows.append(row)
        save(out / 'pairs.json', rows)
    external = [{key: dict(host_ms=row[key]['external_wall_s'] * 1000) for key in ('A', 'B')} for row in rows]
    save(out / 'summary.json', dict(host=summarize(rows), external_wall=summarize(external),
                                    signatures=signatures, runtime=runtime))
    with (out / 'pairs.csv').open('w') as stream:
        writer = csv.writer(stream)
        writer.writerow(['pair','order','before_host_s','after_host_s','before_wall_s','after_wall_s','delta_percent'])
        for row in rows:
            a, b = row['A'], row['B']
            writer.writerow([row['pair'], ''.join(row['order']), a['host_ms']/1000, b['host_ms']/1000,
                             a['external_wall_s'], b['external_wall_s'], 100*(b['host_ms']/a['host_ms']-1)])
    print(json.dumps(read(out / 'summary.json'), indent=2))


if __name__ == '__main__':
    main()
