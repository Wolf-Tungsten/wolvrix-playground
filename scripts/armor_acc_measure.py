"""Verify and time XiangShan models built with the accumulate-sink pass against the frozen baseline.

`full` is the frozen baseline when the regenerated control graph reproduces its
sources, otherwise the rebuilt control model. Candidates are named on the command line.
"""
import argparse
import platform
import resource
import subprocess
import time
from pathlib import Path

from armor_acc_compare import BASE_XS, OUT
from armor_mask_layout_compare import DEFAULT as OLD
from armor_mask_layout_measure import FIRMWARE, LOCK
from cv32e40p_compare import identity, save
from grhsim_difftrace import compare_traces, validate_trace_coverage
from grhsim_single_baseline import Baseline, parse_run
import xiangshan_cv32_ablation_measure as xs_protocol
from xiangshan_cv32_ablation_measure import measurement_lock, read, verify

KEYS = {'control': 'K', 'drop': 'D', 'bank': 'B', 'group': 'G', 'both': 'BG'}
REFERENCE = OLD.parent / 'measurement/xs'


def baseline_dir():
    control = OUT / 'K/xs'
    if read(control / 'sources.json')['unchanged']:
        return BASE_XS
    if not (control / 'binary.json').exists():
        raise ValueError('control sources differ from the frozen baseline; build K first')
    return control


def round_orders(variants):
    if set(variants) == {'full', 'group', 'bank', 'both'} and len(variants) == 4:
        # Balance position and within-round predecessor over each four rounds.
        return [[variants[(i + j) % 4] for j in (0, 1, 3, 2)] for i in range(8)]
    return [list(variants if i % 2 == 0 else variants[::-1]) for i in range(8)]


def manifest(names, tag):
    source = OUT / f'xs-inputs-{tag}'
    source.mkdir(exist_ok=True)
    targets = [('full', baseline_dir()), *((name, OUT / KEYS[name] / 'xs') for name in names)]
    for name, target in targets:
        if not (source / name).exists():
            (source / name).symlink_to(target, target_is_directory=True)
    save(source / 'policy.json', dict(variants=['full', *names], baseline=str(baseline_dir()),
        control=identity(OUT / 'K/xs/sources.json'),
        runs='eight paired rounds on node030 CPU96 NUMA1, single thread, ASLR off, shared lock',
        order=round_orders(('full', *names))))
    save(source / 'inputs.json', [identity(OUT / KEYS[name] / 'xs/sources.json') for name in names])
    xs_protocol.VARIANTS = ('full', *names)
    return xs_protocol.freeze(source, FIRMWARE / 'coremark-2-iteration.bin', FIRMWARE / 'riscv64-nemu-interpreter-so')


def runners(dest, frozen, names):
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    compiler = Path(read(OUT.parent / 'armor-followup-v1/frozen/inputs.json')['compiler']['path']).with_name('clang++')
    result = {}
    for name in names:
        model = frozen['models'][name]
        args = argparse.Namespace(output=dest / name, binary=Path(model['binary']['path']),
            image=Path(frozen['image']['path']), nemu=Path(frozen['nemu']['path']), compiler=compiler,
            cpu=96, cycles=100000, jobs=1, repeats=1, sim_primitives='none', tools_dir=None, skip_idle_check=True)
        runner = Baseline(args)
        result[name] = (runner, runner.prepare_measurement())
    return result


def verify_xs(names, tag):
    frozen = manifest(names, tag)
    dest = OUT / f'functional-{tag}'
    checked = list(names) + ([] if baseline_dir() == BASE_XS else ['full'])
    with measurement_lock(OUT.parent / 'armor-post-mask-analysis-v1/node029-semantic.lock'):
        dest.mkdir()
        save(dest / 'manifest.json', frozen)
        setups = runners(dest, frozen, checked)
        results = {}
        for label, cycles, seed in [('smoke', 10000, 0), ('verify-s0', 100000, 0), ('verify-s1', 100000, 1)]:
            old = read(REFERENCE / 'full/runs' / (label + '.json'))
            for name, (runner, setup) in setups.items():
                extra = [] if label == 'smoke' else ['--dump-difftrace', f'./trace_s{seed}']
                run = runner.run_sample(setup, label, cycles, seed, extra)
                assert xs_protocol.signature(run) == xs_protocol.signature(old), (label, name)
                result = dict(run=run)
                if extra:
                    schema = frozen['models'][name]['schema']
                    comparator = dest / 'trace-comparator/compare'
                    if not comparator.exists():
                        comparator = xs_protocol.build_comparator(schema['path'], dest / 'trace-comparator')
                    trace = compare_traces(comparator, REFERENCE / f'full/runs/runtime/bin/trace_s{seed}',
                                           setup['binary'].parent / f'trace_s{seed}', dest / f'{name}-s{seed}.json')
                    trace['coverage'] = [validate_trace_coverage(trace, x) for x in (old, run)]
                    assert trace['pass_'] and trace['records'] == 99999 and all(x['pass_'] for x in trace['coverage'])
                    save(dest / f'{name}-s{seed}.json', trace)
                    result['trace'] = identity(dest / f'{name}-s{seed}.json')
                results[f'{label}-{name}'] = result
                print('XS functional', label, name, flush=True)
        xs_protocol.check_frozen(frozen)
        save(dest / 'verified.json', dict(status='pass', host=platform.node(), runs=results,
            current={n: frozen['models'][n]['binary'] for n in checked},
            scope='Released models compared to the frozen baseline trace, same inputs and endpoint. Diagnostic timing unused.'))


def perfdump_xs(names, tag):
    """DiffTest does not see the performance counters, so compare their dumps.

    `final` dumps once at the end; `periodic` also dumps and clears every 30000
    cycles, which exercises the clear path. Every printed line must match;
    the order of the lines is recorded but not required to match.
    """
    frozen = manifest(names, tag)
    dest = OUT / f'perfdump-{tag}'
    variants = ('full', *names)
    with measurement_lock(OUT.parent / 'armor-post-mask-analysis-v1/node029-semantic.lock'):
        dest.mkdir()
        save(dest / 'manifest.json', frozen)
        setups = runners(dest, frozen, variants)
        results = {}
        old = read(REFERENCE / 'full/runs/verify-s0.json')
        for label, extra in [('final', ['--force-dump-result']), ('periodic', ['--force-dump-result', '-D', '30000'])]:
            dumps = {}
            for name, (runner, setup) in setups.items():
                # Run the prepared command directly: counter names such as
                # `ras_top_mismatch` would trip the log checks of run_sample,
                # so the dump lines are split off before the log is checked.
                command = list(setup['base'])
                command[-1] = '0'
                command += ['-C', '100000', *extra]
                log = setup['directory'] / ('perfdump-' + label + '.log')
                with log.open('w') as stream:
                    code = subprocess.run(command, cwd=setup['binary'].parent, env=setup['runtime'],
                                          stdout=stream, stderr=subprocess.STDOUT).returncode
                text = log.read_text(errors='replace').splitlines()
                lines = [line for line in text if line.startswith('[PERF ]')]
                run = parse_run('\n'.join(line for line in text if not line.startswith('[PERF ]')) + '\n', 100000)
                if code != 0 or xs_protocol.signature(run) != xs_protocol.signature(old):
                    raise ValueError(('unexpected endpoint', label, name, code))
                target = dest / f'{name}-{label}.perf.txt'
                target.write_text('\n'.join(lines) + '\n')
                dumps[name] = lines
                results[f'{label}-{name}'] = dict(run=run, lines=len(lines), dump=identity(target),
                    nonzero=sum(1 for line in lines if not line.rstrip().endswith(', 0')))
                print('XS perf dump', label, name, len(lines), flush=True)
            for name in names:
                # Tasks run in schedule order, which differs between models and
                # is not the RTL statement order in the control model either.
                # So every printed line must match, in any order.
                same = sorted(dumps[name]) == sorted(dumps['full'])
                results[f'{label}-{name}'].update(identical_lines=same, same_order=dumps[name] == dumps['full'])
                if not same or len(dumps['full']) < 30000:
                    save(dest / 'failed.json', results)
                    raise AssertionError((label, name, len(dumps['full']), len(dumps[name])))
        xs_protocol.check_frozen(frozen)
        save(dest / 'verified.json', dict(status='pass', host=platform.node(), runs=results,
            scope='Performance counter dumps of the candidates contain exactly the lines of the control model.'))


def measure_xs(names, tag):
    while not (OUT / f'functional-{tag}/verified.json').exists():
        time.sleep(10)
    frozen = manifest(names, tag)
    gate = read(OUT / f'functional-{tag}/verified.json')
    if any(gate['current'][n] != frozen['models'][n]['binary'] for n in gate['current']):
        raise ValueError('functional binary identity changed')
    variants = ('full', *names)
    orders = round_orders(variants)
    with measurement_lock(LOCK, wait=True):
        dest = OUT / f'measurement-{tag}'
        dest.mkdir(parents=True)
        save(dest / 'manifest.json', frozen)
        save(dest / 'measurement-policy.json', dict(order=orders, rounds=8, lock=str(LOCK),
            placement='node030 CPU96 NUMA1, single thread, ASLR off',
            functional=identity(OUT / f'functional-{tag}/verified.json')))
        setups = runners(dest, frozen, variants)
        expected = xs_protocol.signature(gate['runs'][f'verify-s0-{names[0]}']['run'])

        def sample(name, label):
            runner, prep = setups[name]
            row = runner.run_sample(prep, label, 100000, 0, [])
            if xs_protocol.signature(row) != expected:
                raise ValueError('unexpected timed endpoint')
            return row
        save(dest / 'warmups.json', {name: sample(name, 'warmup') for name in variants})
        rounds = []
        for i, order in enumerate(orders):
            row = dict(round=i, order=order)
            for name in order:
                row[name] = sample(name, f'round{i:02d}')
            rounds.append(row)
            save(dest / 'rounds.json', rounds)
            print('XS round', i + 1, 'of 8', flush=True)
        xs_protocol.check_frozen(frozen)
        save(dest / 'summary.json', dict(comparisons=xs_protocol.summaries(rounds), functional_signature=expected, rounds=rounds))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('verify', 'perfdump', 'measure'))
    parser.add_argument('tag')
    parser.add_argument('names', nargs='+', choices=tuple(KEYS))
    args = parser.parse_args()
    expected_host = 'node030' if args.stage == 'measure' else 'node029'
    if not platform.node().startswith(expected_host):
        parser.error('required host ' + expected_host)
    while True:
        try:
            dict(verify=verify_xs, perfdump=perfdump_xs, measure=measure_xs)[args.stage](args.names, args.tag)
            break
        except RuntimeError as exc:
            if not str(exc).startswith('CPU96 measurement lock is held:'):
                raise
            print('Waiting for the shared measurement lock.', flush=True)
            time.sleep(30)
