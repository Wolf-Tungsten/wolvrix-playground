"""Five position-balanced rounds at 100,000 cycles with the single-model CPU96 protocol."""
import argparse
from pathlib import Path
import platform
import resource
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/armor-xs-cv32-groups-v1'
sys.path.insert(0, str(ROOT/'scripts'))
from armor_dispatch_diag import DEFAULT, LLVM
from armor_mask_layout_measure import LOCK
from grhsim_single_baseline import Baseline, identity, save
from grhsim_single_compare import summarize
from xiangshan_cv32_ablation_measure import measurement_lock, read, signature, verify

names = ['base','full','events','mux','views']
# Rotating these indices makes every model occupy every position once.
orders = [[names[i] for i in row] for row in [
    [0,1,4,2,3], [1,2,0,3,4], [2,3,1,4,0], [3,4,2,0,1], [4,0,3,1,2]]]
dest = OUT / 'timing'
inputs = read(DEFAULT / 'verify/default/runs/input_identity.json')
for key in ('image','nemu'):
    verify(inputs[key])
params = dict(cpu=96, cycles=100000, jobs=1, repeats=len(orders), sim_primitives='none', tools_dir=None,
              compiler=LLVM / 'clang++', image=Path(inputs['image']['path']), nemu=Path(inputs['nemu']['path']),
              skip_idle_check=True)

def measure():
    assert platform.node().split('.')[0] == 'node030'
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    dest.mkdir(exist_ok=False)
    expected = read(OUT/'correctness/base/result.json')['signature']
    setups = {}
    for n in names:
        b = read(OUT/n/'binary.json')
        check = read(OUT/'correctness'/n/'result.json')
        verify(b)
        if check['binary'] != b or check['signature'] != expected:
            raise ValueError('verification differs: ' + n)
        runner = Baseline(argparse.Namespace(output=dest/n, binary=Path(b['path']), **params))
        setups[n] = (runner, runner.prepare_measurement())
    save(dest/'policy.json',dict(cycles=100000, warmups=1, orders=orders, host=platform.node(), cpu=96,
         numa=1, aslr=False, inputs=inputs, metric='external_wall_s', lock=str(LOCK)))
    def sample(n, label):
        runner, setup = setups[n]
        value = runner.run_sample(setup, label, 100000, 0, [])
        if signature(value) != expected:
            raise ValueError('signature differs for ' + n)
        return value
    save(dest/'warmup.json', {n:sample(n,'warmup') for n in names})
    rows = []
    for i, order in enumerate(orders, 1):
        row = {'round':i,'order':order}
        rows.append(row)
        for n in order:
            row[n] = sample(n, f'round{i}')
            save(dest/'rounds.json',rows)
            print('measured', i, n, round(row[n]['external_wall_s'],3), flush=True)
    summary={}
    for n in names[1:]:
        pairs = [{s:{'host_ms':1000*r[k]['external_wall_s']} for s,k in [('A','base'),('B',n)]} for r in rows]
        summary[n] = summarize(pairs)
    save(dest/'summary.json',summary)

if __name__ == '__main__':
    with measurement_lock(LOCK,wait=True):
        measure()
