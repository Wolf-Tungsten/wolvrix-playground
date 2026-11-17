#!/usr/bin/env python3
"""Eight direct pairs of pre-CV32 and the frozen connected shared candidate."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import sys
import time

from cv32e40p_compare import ROOT,run
from grhsim_single_baseline import identity,save,clean_environment
from grhsim_single_compare import build_modes
from xiangshan_cv32_compare import XS,verify_identity
from xiangshan_cv32_ablation_measure import measurement_lock

MODELS={
    'baseline': ROOT/'build/xs/cv32-transfer-20261116-v3/before',
    'candidate': ROOT/'build/xs/shared-connected-20261116-v1/candidate',
}
EXPECTED={
    'baseline': '638c464fe763f24001e5950b885321f6fbd8fab42e1c7996dfe8d6e4f9b02b22',
    'candidate': 'da1356413cb0b45a73a31f3c39bc0481912148b88a03e0c1a16cec1962a299eb',
}
HELPERS=('grhsim_single_compare.py','grhsim_single_baseline.py','grhsim_numa.py',
         'grhsim_difftrace.py','simulation_model_modes.py','xiangshan_cv32_ablation_measure.py')

def read(path):return json.loads(Path(path).read_text())

def prepare(out):
    out.mkdir(parents=True,exist_ok=False);snapshot=out/'snapshot';snapshot.mkdir()
    inputs=[];models={};configs={};schema=[]
    for label,folder in MODELS.items():
        binary=read(folder/'binary.json');assert binary['sha256']==EXPECTED[label]
        verify_identity(binary)
        config=read(folder/'configuration.json');configs[label]=config
        assert config['runtime_difftest']=='on' and all(v=='on' for v in build_modes(config,'on').values())
        assert not any(config.get(k,False) for k in ('pgo','bolt','diagnostic_instrumentation','emit_runtime_profile'))
        sources=read(folder/'model-sources.json')
        expected_files={Path(row['path']).resolve() for row in sources}
        actual_files={p.resolve() for p in (folder/'model').iterdir() if p.suffix in ('.cpp','.hpp') or p.name=='Makefile'}
        assert expected_files==actual_files
        for row in sources:verify_identity(row)
        header=identity(folder/'chisel-home/build/generated-src/difftest-state.h');schema.append(header['sha256'])
        models[label]=dict(directory=str(folder),binary=binary,configuration=config,schema=header)
        inputs += sources+[binary,header]+[identity(folder/n) for n in ('binary.json','configuration.json','model-sources.json')]
        (out/label).symlink_to(folder,target_is_directory=True)
    common=('config','guest_cores','sim_primitives','sim_models','behavior_state_lowering','behavior_compute_lowering',
            'model_flags','harness_flags','storage_ref_aliases','compiler','shared_input','pipeline')
    for key in common:assert configs['baseline'].get(key)==configs['candidate'].get(key),key
    assert len(set(schema))==1
    assert configs['baseline']['wolvrix_revision'].startswith('74d80cf')
    assert not configs['baseline']['retained_cv32_features']
    assert configs['candidate']['event_regions_shared_connected']
    for key,path in [('image',XS/'ready-to-run/coremark-2-iteration.bin'),('nemu',XS/'ready-to-run/riscv64-nemu-interpreter-so')]:
        observed=identity(path)
        assert all(all(c[key][k]==observed[k] for k in ('bytes','sha256')) for c in configs.values())
        inputs.append(observed)
    inputs += [configs['baseline']['compiler'],configs['baseline']['shared_input']]
    for row in inputs[-2:]:verify_identity(row)
    policy=dict(baseline='Wolvrix 74d80cf, before CV32 optimization series',
        candidate='Exact frozen TNO0044 connected/equal-activation shared candidate; includes retained CV32 rules and common correctness repairs',
        pairs=8,cycles=100000,cpu=96,numa=1,aslr=False,threads=1,smoke_cycles=10000,
        verification_seeds=[0,1],warmups_per_variant=1,order='AB/BA alternating, A=pre-CV32, B=latest candidate',
        primary_metric='External process walltime; host time reported alongside',runtime_difftest='on',performance_trace=False,
        bootstrap_seed=20261102,bootstrap_resamples=10000,max_sample_attempts=1,
        idle_admission='Same skip-external-idle-admission as prior XiangShan measurements; CPU/thread/NUMA/ASLR checks mandatory',
        scope='Same DefaultConfig, frozen input graph and CoreMark first 100k cycles. Not full CoreMark completion.',
        reuse='Reuse exact frozen model source and ELF; no regeneration or recompile.',
        feedback='No performance-driven revisions, added pairs, sample deletion, or runtime input to generation.')
    save(out/'policy.json',policy);save(out/'models.json',models)
    inputs += [identity(out/n) for n in ('policy.json','models.json')]
    for name in (*HELPERS,Path(__file__).name):
        p=ROOT/'scripts'/name;shutil.copy2(p,snapshot/name);inputs += [identity(p),identity(snapshot/name)]
    save(out/'inputs.json',list({r['path']:r for r in inputs}.values()))
    print('Frozen pre-CV32 and latest ELF; eight direct pairs declared',flush=True)

def check(out):
    for row in read(out/'inputs.json'):verify_identity(row)
    for label,model in read(out/'models.json').items():
        assert (out/label).resolve()==Path(model['directory']).resolve()
        assert model['binary']['sha256']==EXPECTED[label]
        actual={p.resolve() for p in (out/label/'model').iterdir() if p.suffix in ('.cpp','.hpp') or p.name=='Makefile'}
        declared={Path(r['path']).resolve() for r in read(out/label/'model-sources.json')}
        assert actual==declared

def measure(out):
    assert platform.node().startswith('node030')
    with measurement_lock():
        check(out)
        if (out/'paired').exists():raise FileExistsError('Formal measurement already started; preserve all records')
        command=[sys.executable,ROOT/'scripts/grhsim_single_compare.py','--baseline',out/'baseline','--candidate',out/'candidate',
            '--output',out/'paired','--cycles','100000','--pairs','8','--runtime-difftest','on',
            '--image',XS/'ready-to-run/coremark-2-iteration.bin','--nemu',XS/'ready-to-run/riscv64-nemu-interpreter-so','--skip-idle-check']
        env=clean_environment();env['PYTHONPATH']=str(ROOT/'scripts')
        started=time.time()
        save(out/'run-window.json',dict(host=platform.node(),started=started,status='running',cpu=96))
        try:run(command,out/'measurement.log',env=env)
        except Exception as error:
            save(out/'run-window.json',dict(host=platform.node(),started=started,finished=time.time(),status='failed',error=str(error)));raise
        check(out);summary=read(out/'paired/summary.json')
        assert summary['pairs']==8 and len(summary['samples'])==8
        save(out/'report.json',dict(status='pass',external_wall=summary['external_wall'],
            host_time={k:v for k,v in summary.items() if k.startswith(('delta_','baseline_','candidate_'))},
            models=identity(out/'models.json'),policy=identity(out/'policy.json'),inputs=identity(out/'inputs.json'),summary=identity(out/'paired/summary.json')))
        save(out/'run-window.json',dict(host=platform.node(),started=started,finished=time.time(),status='pass',cpu=96))
        print(json.dumps(summary['external_wall'],indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('prepare','check','measure'));p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();{'prepare':prepare,'check':check,'measure':measure}[a.stage](a.output.resolve())
