#!/usr/bin/env python3
"""Run independent multi-constraint solves and select the feasible minimum km1."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import fcntl
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from repcut_grhsim_ingest import identity
from repcut_grhsim_isolated_initial import restore_labels


def save(path: Path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def cpu_list(value: str) -> list[int]:
    result = set()
    for part in value.strip().split(','):
        bounds = list(map(int, part.split('-')))
        result.update(range(bounds[0], bounds[-1] + 1))
    return sorted(result)


def cpu_groups(cpus: list[int], runs: int, siblings: list[list[int]]) -> list[list[int]]:
    if not 1 <= runs <= len(cpus):
        raise ValueError('each solve requires at least one CPU')
    inventory = set(cpus)
    units = {tuple(sorted(set(group) & inventory)) for group in siblings}
    units.discard(())
    flattened = [cpu for group in units for cpu in group]
    if len(flattened) != len(set(flattened)) or set(flattened) != inventory:
        raise ValueError('CPU sibling inventory overlaps or has missing CPUs')
    if len(units) < runs:
        raise ValueError('not enough independent physical cores for concurrent solves')
    result = [[] for _ in range(runs)]
    for group in sorted(units, key=lambda unit: (-len(unit), unit)):
        dest = min(range(runs), key=lambda index: (len(result[index]), index))
        result[dest].extend(group)
    return [sorted(group) for group in result]


def parse_audit(path: Path) -> dict:
    lines = path.read_text().splitlines()
    fields = {}
    for line in lines:
        if '=' in line:
            key, value = line.split('=', 1)
            fields[key] = int(value)
    axis = next(index for index, line in enumerate(lines) if line.startswith('axis,total,'))
    parts = next(index for index, line in enumerate(lines) if line.startswith('part,atoms,'))
    fields['axes'] = [{key: value if key == 'axis' else int(value) for key, value in row.items()}
                      for row in csv.DictReader(lines[axis:parts])]
    fields['parts'] = [{key: int(value) for key, value in row.items()}
                       for row in csv.DictReader(lines[parts:])]
    return fields


def check_capacity(audit: dict, epsilon: Fraction) -> list[dict]:
    checks = []
    for row in audit['axes']:
        average_ceil = (row['total'] + audit['k'] - 1) // audit['k']
        capacity = int(average_ceil * (1 + epsilon))
        checks.append(dict(axis=row['axis'], maximum=row['max'], capacity=capacity,
                           feasible=row['max'] <= capacity))
    return checks


def select_best(results: list[dict]) -> dict:
    feasible = [row for row in results if row['status'] == 'pass' and row['capacity_feasible']]
    if not feasible:
        raise ValueError('no feasible solve; all individual logs are preserved')
    return min(feasible, key=lambda row: (row['full_km1'], row['seed']))


def graph_header(path: Path) -> tuple[int, int, int, int]:
    with path.open() as stream:
        result = tuple(map(int, stream.readline().split()))
    if len(result) != 4 or result[2:] != (11, 6):
        raise ValueError('expected a weighted six-dimensional hMetis graph')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('graph', 'reduced-graph', 'isolation-record', 'solver', 'solver-config', 'audit-probe', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--runs', type=int, default=8)
    parser.add_argument('--first-seed', type=int, default=0)
    parser.add_argument('--epsilon', type=Fraction, default=Fraction(5, 100))
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / '.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cpus = cpu_list(Path('/sys/devices/system/cpu/online').read_text())
    for task in Path('/proc/self/task').iterdir():
        os.sched_setaffinity(int(task.name), cpus)
    siblings = [cpu_list(Path(f'/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list').read_text())
                for cpu in cpus]
    groups = cpu_groups(cpus, args.runs, siblings)
    isolation = json.loads(args.isolation_record.read_text())
    full_header, reduced_header = graph_header(args.graph), graph_header(args.reduced_graph)
    if (full_header[1] != isolation['nodes'] or reduced_header[1] != isolation['remaining_nodes']
            or full_header[1] - len(isolation['isolated']) != reduced_header[1]
            or isolation['partitions'] <= len(isolation['isolated'])):
        raise ValueError('isolation and graph node inventories disagree')
    artifacts = {name: identity(getattr(args, name)) for name in
                 ('graph', 'reduced_graph', 'isolation_record', 'solver', 'solver_config', 'audit_probe')}
    for key, record_key in [('graph', 'graph'), ('reduced_graph', 'reduced_graph')]:
        if artifacts[key]['sha256'] != isolation[record_key]['sha256']:
            raise ValueError('graph hash differs from automatic isolation record')
    policy = dict(schema='grhsim-solver-portfolio-v1', artifacts=artifacts, runs=args.runs,
                  seeds=list(range(args.first_seed, args.first_seed + args.runs)), cpu_groups=groups,
                  epsilon=str(args.epsilon), partitions=isolation['partitions'],
                  selection='minimum full-HGR km1 among capacity-feasible fresh solves; seed breaks ties')
    policy_path = args.output / 'policy.json'
    if policy_path.exists() and json.loads(policy_path.read_text()) != policy:
        raise ValueError('portfolio configuration changed; use a new output directory')
    save(policy_path, policy)
    started = time.monotonic()

    def solve(index):
        seed = args.first_seed + index
        cpuset = groups[index]
        dest = args.output / f'seed{seed:02d}'
        dest.mkdir(exist_ok=True)
        record_path = dest / 'result.json'
        if record_path.exists():
            cached = json.loads(record_path.read_text())
            if cached['status'] == 'pass' and identity(Path(cached['assignment']['path'])) == cached['assignment']:
                return cached
            raise ValueError('incomplete or changed solve; preserve it and use a new output directory')
        begin = time.monotonic()
        reduced_k = isolation['partitions'] - len(isolation['isolated'])
        command = ['taskset', '-c', ','.join(map(str, cpuset)), str(args.solver.resolve()),
                   '-h', str(args.reduced_graph.resolve()), '-k', str(reduced_k),
                   '-e', str(float(args.epsilon)), '-o', 'km1', '-p', str(args.solver_config.resolve()),
                   '-t', str(len(cpuset)), '--seed', str(seed), '--verbose', '1',
                   '--write-partition-file', '1', '--partition-output-folder', str(dest)]
        result = dict(status='running', seed=seed, cpus=cpuset, threads=len(cpuset), command=command)
        save(record_path, result)
        print('START', seed, 'threads', len(cpuset), flush=True)
        try:
            with (dest / 'solver.log').open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            result['solver_elapsed_s'] = time.monotonic() - begin
            outputs = list(dest.glob('*.KaHyPar'))
            if len(outputs) != 1:
                raise ValueError('expected exactly one partition output')
            local = list(map(int, outputs[0].read_text().split()))
            labels = restore_labels(local, isolation['nodes'], isolation['isolated'], isolation['partitions'])
            assignment = dest / 'assignment.part32'
            assignment.write_text(''.join(f'{part}\n' for part in labels))
            audits = {}
            for name, graph, path in [('reduced', args.reduced_graph, outputs[0]),
                                      ('full', args.graph, assignment)]:
                audit_path = dest / (name + '.audit.txt')
                with (dest / (name + '.audit.log')).open('w') as log:
                    subprocess.run(['taskset', '-c', ','.join(map(str, cpuset)),
                                    str(args.audit_probe.resolve()), str(graph.resolve()), str(path), str(audit_path)],
                                   stdout=log, stderr=subprocess.STDOUT, check=True)
                audits[name] = parse_audit(audit_path)
            log = (dest / 'solver.log').read_text()
            reported = re.findall(r'^\s*km1\s*=\s*(\d+)\s*\(primary', log, re.M)
            if not reported or int(reported[-1]) != audits['reduced']['km1_cut']:
                raise ValueError('independent reduced km1 disagrees with solver')
            checks = check_capacity(audits['reduced'], args.epsilon)
            if len(checks) != 6 or not all(row['feasible'] for row in checks):
                raise ValueError('six-dimensional capacity check failed')
            if audits['reduced']['k'] != reduced_k or audits['full']['k'] != isolation['partitions']:
                raise ValueError('audited partition inventory mismatch')
            result.update(status='pass', capacity_feasible=True, capacity_checks=checks,
                          reduced_km1=audits['reduced']['km1_cut'], full_km1=audits['full']['km1_cut'],
                          assignment=identity(assignment), elapsed_s=time.monotonic() - begin)
        except Exception as error:
            result.update(status='failed', capacity_feasible=False, error=str(error),
                          elapsed_s=time.monotonic() - begin)
        save(record_path, result)
        print('DONE', seed, result['status'], result.get('full_km1'), flush=True)
        return result

    results = []
    with ThreadPoolExecutor(max_workers=args.runs) as pool:
        futures = [pool.submit(solve, index) for index in range(args.runs)]
        for future in as_completed(futures):
            results.append(future.result())
    for name, before in artifacts.items():
        if identity(getattr(args, name)) != before:
            raise ValueError('input artifact changed during solve: ' + name)
    best = select_best(results)
    selected = args.output / 'best_assignment.part32'
    shutil.copy2(best['assignment']['path'], selected)
    save(args.output / 'selection.json', dict(status='pass', selected_seed=best['seed'],
        full_km1=best['full_km1'], reduced_km1=best['reduced_km1'], assignment=identity(selected),
        elapsed_s=time.monotonic() - started, all_runs_passed=all(row['status'] == 'pass' for row in results),
        runs=sorted(results, key=lambda row: row['seed']), scope='static km1 selection; no walltime claim'))
    print('SELECTED', best['seed'], 'full_km1', best['full_km1'], 'assignment', selected, flush=True)


if __name__ == '__main__':
    main()
