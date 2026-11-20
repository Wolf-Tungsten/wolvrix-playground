"""Recheck the released default and time it against the matched scalar build."""
from pathlib import Path
import platform
import re
import subprocess
import sys

from armor_mask_layout_measure import LOCK
from grhsim_single_baseline import ROOT, identity, save
from grhsim_single_compare import pair_order
from xiangshan_cv32_ablation_measure import measurement_lock, read, verify
from xiangshan_packed_storage_compare import source_inventory, source_shape


PREVIOUS = ROOT / 'build/armor-acc-default-v1'
OUT = PREVIOUS / 'perf-regression'


def recheck_default():
    released = PREVIOUS / 'xs-final'
    fresh = OUT / 'default-reemit'
    files = source_inventory(fresh / 'model')
    old = source_inventory(released / 'model')
    expected = read(PREVIOUS / 'xs-source-comparison.json')['resumed_sources']
    if {Path(row['path']).name: row['sha256'] for row in old} != expected:
        raise ValueError('released sources differ from the previous validated snapshot')
    equal = source_shape(files) == source_shape(old)
    if not equal:
        subprocess.run([sys.executable, ROOT / 'scripts/armor_acc_default_verify.py', fresh.relative_to(PREVIOUS)], check=True)
    selected = released if equal else fresh
    record = read(selected / 'verify/result.json')
    verify(record['binary'])
    save(OUT / 'default-identity.json', dict(directory=str(selected), binary=record['binary'],
        matches_release=equal, count=len(files), files=files))


def emit_options(log):
    with log.open() as stream:
        line = next(s for s in stream if s.startswith('[wolvrix-xs-grhsim] activity-schedule max_'))
    return dict(part.split('=', 1) for part in line.split() if '=' in part)


def code_shape(model):
    header = (model / 'grhsim_SimTop.hpp').read_text()
    bank = re.findall(r'std::array<std::uint64_t, (\d+)> state_reg_to_mem_grhsim_accumulate_bank_', header)
    groups = 0
    for source in model.glob('*.cpp'):
        groups += source.read_bytes().count(b'// Same-reader scalar commit group:')
    return dict(bank_slots=sum(map(int, bank)), commit_groups=groups)


def measure():
    if platform.node().split('.')[0] != 'node030':
        raise ValueError('walltime runs belong on node030')
    selected = read(OUT / 'default-identity.json')
    dirs = {'A': OUT / 'off', 'B': Path(selected['directory'])}
    verify(selected['binary'])
    off_opts, on_opts = (emit_options(OUT / name) for name in ('off-emit.log', 'default-emit.log'))
    assert off_opts['accumulate_bank'] == 'False' and on_opts['accumulate_bank'] == 'True'
    ignore = {'accumulate_bank', 'post_stats_json', 'pre_reg_to_mem_json'}
    common_options = {k:v for k,v in off_opts.items() if k not in ignore}
    assert common_options == {k:v for k,v in on_opts.items() if k not in ignore}
    opts, endpoints, inputs, commands, shapes = {}, {}, {}, {}, {}
    for name, folder in dirs.items():
        proof = read(folder / 'verify/result.json')
        assert proof['status'] == 'pass' and proof['trace']['records'] == 99999 and proof['counter_lines'] == 35063
        verify(proof['binary'])
        opts[name] = identity(folder / 'verify/result.json')
        endpoints[name] = proof['signature']
        inputs[name] = read(folder / 'verify/default/runs/input_identity.json')
        assert inputs[name]['binary'] == proof['binary']
        commands[name] = [v.replace(str(folder), '{MODEL}') for v in read(folder / 'compile.command.json')['argv']]
        shapes[name] = code_shape(folder / 'model')
    assert shapes == {'A': dict(bank_slots=0, commit_groups=0), 'B': dict(bank_slots=32454, commit_groups=0)}
    assert endpoints['A'] == endpoints['B'] and commands['A'] == commands['B']
    for key in ('image', 'nemu'):
        assert inputs['A'][key] == inputs['B'][key]
        verify(inputs['A'][key])
    args = [sys.executable, '-u', ROOT/'scripts/grhsim_single_compare.py', '--baseline', dirs['A'],
            '--candidate', dirs['B'], '--output', OUT/'timing', '--pairs', '8', '--cycles', '100000',
            '--candidate-sim-primitives', 'none', '--image', inputs['A']['image']['path'],
            '--nemu', inputs['A']['nemu']['path'], '--skip-idle-check']
    anchor = None
    if not selected['matches_release']:
        released = PREVIOUS/'xs-final'
        original = read(released/'verify/result.json')
        verify(original['binary'])
        assert original['status'] == 'pass' and original['signature'] == endpoints['A']
        expected = read(PREVIOUS/'xs-source-comparison.json')['resumed_sources']
        changed = [Path(f['path']).name for f in selected['files'] if expected.get(Path(f['path']).name) != f['sha256']]
        anchor = dict(binary=original['binary'], changed_files=changed, samples=['anchor-before','anchor-after'])
        args.extend(['--historical', released])
    save(OUT/'policy.json', dict(labels={'A':'explicit off','B':'production default'}, host=platform.node(),
        cpu=96, numa_node=1, simulator_threads=1, lock=str(LOCK), rounds=pair_order(8),
        cycles=100000, timed_seed=0, warmups_per_model=1, primary_metric='external_wall_s',
        paired_percent='100 * (default/off - 1)', bootstrap_resamples=10000, bootstrap_seed=20261102,
        inputs=inputs, verification=opts, shapes=shapes, signature=endpoints['A'], previous_default=anchor,
        common_emit=common_options, common_compile=commands['A'], command=list(map(str,args))))
    print('Matched models verified. Waiting for the shared CPU96 lock.', flush=True)
    with measurement_lock(LOCK, wait=True):
        subprocess.run(args, cwd=ROOT, check=True)


if __name__ == '__main__':
    {'check-default':recheck_default, 'measure':measure}[sys.argv[1]]()
