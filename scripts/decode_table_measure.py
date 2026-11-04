#!/usr/bin/env python3
"""CPU96 paired local measurements with private libraries and NUMA audits."""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time

from decode_table_study import ROOT, parse, vectors, write_vectors
from grhsim_numa import runtime_plan, inspect_locality, locality_errors
from grhsim_single_baseline import clean_environment, cpus, cpu_counters, idle_percent, identity, save


def prepare(case, output):
    if not platform.node().startswith('node030'):
        raise ValueError('measure on node030')
    siblings = cpus(Path('/sys/devices/system/cpu/cpu96/topology/thread_siblings_list').read_text())
    nodes = [int(p.parent.name[4:]) for p in Path('/sys/devices/system/node').glob('node*/cpulist')
             if 96 in cpus(p.read_text())]
    if len(nodes) != 1:
        raise ValueError('ambiguous CPU96 NUMA node')
    monitor = min(c for c in cpus(Path('/sys/devices/system/cpu/online').read_text()) if c not in siblings)
    os.sched_setaffinity(0, {monitor})
    output.mkdir(parents=True, exist_ok=False)
    env = clean_environment()
    plan = runtime_plan(case/'A/bench', case/'B/bench', None, output/'runtime', 96, nodes[0], env)
    save(output/'runtime_plan.json', plan)
    prefix = ['taskset', '-c', '96', 'numactl', f'--membind={nodes[0]}']
    subprocess.run([*prefix, sys.executable, ROOT/'scripts/grhsim_numa.py', output/'runtime_plan.json'],
                   check=True, env=env, stdout=(output/'prefault.log').open('w'))
    plan = json.loads((output/'runtime/manifest.json').read_text())
    env['LD_LIBRARY_PATH'] = str(output/'runtime/lib')
    context = dict(plan=plan, prefix=[*prefix, 'setarch', platform.machine(), '-R'], env=env,
                   binaries=dict(A=output/'runtime/bin/emu', B=output/'runtime/ref/nemu.so'),
                   node=nodes[0], siblings=siblings)
    save(output/'environment.json', dict(host=platform.node(), cpu=96, monitor_cpu=monitor,
        siblings=sorted(siblings), node=nodes[0], source=identity(case/'identity.json'),
        driver=identity(__file__), kernel='Extracted generated compute bodies and port I/O',
        full='Normal eval including activity and change detection',
        clock='std::chrono::steady_clock inside the loop harness; inputs loaded before timing'))
    preflight = []
    for _ in range(60):
        before = cpu_counters(siblings);time.sleep(3)
        idle = idle_percent(before, cpu_counters(siblings));preflight.append(idle)
        if min(idle.values()) >= 98:
            break
    else:
        save(output/'preflight.json', preflight)
        raise RuntimeError('CPU96 or sibling busy; no alternate CPU')
    save(output/'preflight.json', preflight)
    return context


def sample(context, variant, mode, inputs, iterations, log):
    binary = context['binaries'][variant]
    command = [*context['prefix'], binary, mode, inputs, str(iterations)]
    observations = [];errors = [];seen = set();ready = False
    before = cpu_counters(context['siblings'])
    start = time.monotonic()
    with log.with_suffix('.stdout').open('w') as stdout, log.with_suffix('.stderr').open('w') as stderr:
        process = subprocess.Popen(command, env=context['env'], stdout=stdout, stderr=stderr)
        while process.poll() is None:
            try:
                proc = Path('/proc')/str(process.pid)
                if (proc/'exe').resolve() == binary.resolve():
                    tasks = list((proc/'task').iterdir())
                    status = dict(line.split(':', 1) for line in (proc/'status').read_text().splitlines() if ':' in line)
                    if status['Cpus_allowed_list'].strip() != '96' or len(tasks) != 1:
                        errors.append('not one thread on CPU96')
                    record = inspect_locality((proc/'maps').read_text(), (proc/'numa_maps').read_text(), context['plan'])
                    errors.extend(locality_errors(record, context['node']))
                    seen.update(record['seen_files'])
                    record['time_s'] = time.monotonic()-start
                    observations.append(record);ready = True
            except (FileNotFoundError, ProcessLookupError):
                pass
            time.sleep(.05 if ready else .005)
        code = process.wait()
    required = {str(binary)} | {r['destination'] for r in context['plan']['files'] if r['role'] == 'library'}
    if not required.issubset(seen):
        errors.append(dict(missing_mappings=sorted(required-seen)))
    if not any(r['groups'].get('anonymous', {}).get('pages', {}).get(str(context['node']), 0) for r in observations):
        errors.append('no anonymous pages observed')
    idle = idle_percent(before, cpu_counters(context['siblings']))
    if any(v < 98 for c,v in idle.items() if c != 96):
        errors.append(dict(sibling_busy=idle))
    save(log.with_suffix('.audit.json'), dict(command=list(map(str, command)), exit_code=code,
        observations=observations, errors=errors, sibling_idle=idle, external_wall_s=time.monotonic()-start))
    if code or errors:
        raise RuntimeError(f'local sample rejected; evidence retained at {log}: {code}, {errors}')
    return dict(**json.loads(log.with_suffix('.stdout').read_text()), locality_pass=True,
                audit=str(log.with_suffix('.audit.json')))


def measure(case, output, committed=None, target_ms=150, pair_attempts=1):
    case, output = Path(case).resolve(), Path(output).resolve()
    table = parse((case/'table.txt').read_text())
    context = prepare(case, output);rows=[]
    start_idle = cpu_counters(context['siblings'])
    inputs = {}
    for distribution in ['random', 'matched', 'dense', 'toggle1', 'hold99']:
        path = output/(distribution+'.bin')
        write_vectors(path, table, vectors(table, distribution))
        inputs[distribution] = path
    if table['n'] == 32:
        # These are nonmatching table inputs, not a claim about all ISA legality.
        rng = random.Random(20261105)
        missing = []
        for _ in range(1000000):
            x = rng.getrandbits(32)
            if not any(x & row[0] == row[1] for row in table['rows']):
                missing.append(x)
                if len(missing) == 100000:
                    break
        save(output/'unmatched-search.json', dict(found=len(missing), attempts=_+1))
        if missing:
            path = output/'unmatched.bin'
            write_vectors(path, table, missing);inputs['unmatched'] = path
    if committed is not None:
        from decode_table_trace_inputs import instruction_vectors
        path = output/'committed.bin'
        instruction_vectors(case/'table.txt', committed, path);inputs['committed'] = path
        # The captured sequence is new verification data, not just benchmark input.
        for variant, exe in [('A', case/'A/bench'), ('B', case/'B/bench'),
                             ('verilator', case/'verilator/obj/VDecodeTableStudy')]:
            with (output/f'committed-verify-{variant}.log').open('w') as stream:
                subprocess.run([exe, 'verify', path], check=True, stdout=stream, stderr=subprocess.STDOUT)
    for distribution, path in inputs.items():
        for mode in ['kernel', 'full']:
            # Long enough to inspect runtime pages; calibration is not a formal pair.
            record_bytes = 8*((table['n']+63)//64+2*((table['m']+63)//64))
            period = path.stat().st_size//record_bytes
            count = period if target_ms == 150 else max(period, (10000000//period)*period)
            # Each variant runs integral repetitions of the identical input period.
            # Calibrate independently so a very slow circuit does not force the
            # fast software decoder's target duration on both implementations.
            warm = {v: json.loads(subprocess.check_output([*context['prefix'], context['binaries'][v],
                mode, path, str(count)], env=context['env'], text=True)) for v in ('A', 'B')}
            target_ns = int(target_ms*1000000)
            limit = 100000000 if target_ms == 150 else 1000000000
            iterations = {v:max(period, min(limit//period, math.ceil(target_ns/
                          max(.01,warm[v]['ns'])/period))*period) for v in ('A','B')}
            save(output/f'{distribution}-{mode}-calibration.json', dict(samples=warm, iterations=iterations,
                input_period=period, target_ns=target_ns, warm_iterations=count))
            for pair in range(8):
                order = ['A', 'B'] if pair%2 == 0 else ['B', 'A']
                for attempt in range(pair_attempts):
                    row = dict(distribution=distribution, mode=mode, pair=pair, order=''.join(order), iterations=iterations, attempt=attempt)
                    suffix = '' if attempt == 0 else f'-retry{attempt}'
                    try:
                        for variant in order:
                            log = output/f'{distribution}-{mode}-{pair}-{variant}{suffix}'
                            row[variant] = sample(context, variant, mode, path, iterations[variant], log)
                    except RuntimeError:
                        audit = json.loads(log.with_suffix('.audit.json').read_text())
                        # Retry a whole pair only for measured sibling activity
                        # or an unobserved short-lived mapping, never by speed.
                        allowed = {'sibling_busy', 'missing_mappings'}
                        errors = audit['errors']
                        if audit['exit_code'] or not errors or any(
                            not isinstance(e, dict) or not set(e).issubset(allowed) for e in errors
                        ) or attempt + 1 == pair_attempts:
                            raise
                        save(output/f'{distribution}-{mode}-{pair}{suffix}.rejected-pair.json',
                             dict(partial_pair=row, failed_audit=str(log.with_suffix('.audit.json')),
                                  rule='environment only; entire pair repeated with identical input and iteration count'))
                        before = cpu_counters(context['siblings']);time.sleep(3)
                        idle = idle_percent(before, cpu_counters(context['siblings']))
                        if min(idle.values()) < 98:
                            time.sleep(3)
                        continue
                    break
                row['delta_percent'] = 100*(row['B']['ns']/row['A']['ns']-1)
                rows.append(row);save(output/'pairs.json', rows)
            print(f'{case.name} {distribution} {mode}: 8 pairs complete', flush=True)
    idle = idle_percent(start_idle, cpu_counters(context['siblings']))
    save(output/'sibling_idle.json', idle)
    if any(v < 98 for c, v in idle.items() if c != 96):
        raise RuntimeError('sibling busy; all raw samples retained, case not accepted')
    for entry in context['plan']['files']:
        if identity(entry['destination']) != entry['copy']:
            raise ValueError('runtime file changed during measurement')
    summary = []
    for dist in inputs:
        for mode in ['kernel', 'full']:
            selected = [r for r in rows if r['distribution'] == dist and r['mode'] == mode]
            summary.append(dict(distribution=dist, mode=mode, pairs=len(selected),
                A_ns_median=statistics.median(r['A']['ns'] for r in selected),
                B_ns_median=statistics.median(r['B']['ns'] for r in selected),
                delta_percent_mean=statistics.mean(r['delta_percent'] for r in selected),
                delta_percent_median=statistics.median(r['delta_percent'] for r in selected),
                B_faster_pairs=sum(r['delta_percent'] < 0 for r in selected)))
    save(output/'summary.json', dict(status='pass', measurements=summary, sibling_idle=idle,
        input_identity={k:identity(v) for k,v in inputs.items()}))
    with (output/'pairs.csv').open('w') as stream:
        w = csv.writer(stream);w.writerow(['distribution','mode','pair','order','A_iterations','B_iterations','A_ns','B_ns','delta_percent'])
        for r in rows:
            w.writerow([r['distribution'],r['mode'],r['pair'],r['order'],r['iterations']['A'],r['iterations']['B'],r['A']['ns'],r['B']['ns'],r['delta_percent']])
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--committed', type=Path)
    p.add_argument('--target-ms', type=float, default=150)
    p.add_argument('--pair-attempts', type=int, default=1)
    args = p.parse_args()
    if args.target_ms <= 0 or args.pair_attempts < 1:
        p.error('target-ms and pair-attempts must be positive')
    measure(args.case, args.output, args.committed, args.target_ms, args.pair_attempts)
