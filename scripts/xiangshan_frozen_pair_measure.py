#!/usr/bin/env python3
"""Measure a frozen XS experiment without importing modules from its snapshot."""
import argparse,importlib,os,sys,shutil,json
from pathlib import Path
from cv32e40p_compare import ROOT,run,identity,save
from grhsim_single_baseline import clean_environment
from xiangshan_cv32_ablation_measure import measurement_lock

def measure(out,driver):
    module=importlib.import_module(driver)
    with measurement_lock():
        module.check(out)
        runtime=out/'runtime-driver';runtime.mkdir(exist_ok=False)
        source=out/'snapshot/grhsim_single_compare_three_pairs.py'
        runner=runtime/'grhsim_single_compare_three_pairs.py';shutil.copy2(source,runner)
        assert identity(source)['sha256']==identity(runner)['sha256']
        save(runtime/'correction.json',dict(reason='Snapshot siblings shadowed repository modules and gave Baseline an incorrect ROOT. Execute the exact same runner from a separate directory; use frozen current repository helper modules.',
            runner=identity(runner),original=identity(source),driver=identity(Path(__file__)),experiment_driver=identity(ROOT/'scripts'/(driver+'.py')),
            generation_unchanged=True,policy=identity(out/'policy.json')))
        env=clean_environment();env['PYTHONPATH']=str(ROOT/'scripts')
        cmd=[sys.executable,runner,'--baseline',out/'baseline','--candidate',out/'candidate','--output',out/'paired',
            '--cycles','100000','--pairs','3','--runtime-difftest','on','--image',module.XS/'ready-to-run/coremark-2-iteration.bin',
            '--nemu',module.XS/'ready-to-run/riscv64-nemu-interpreter-so','--skip-idle-check']
        run(cmd,out/'measurement-corrected.log',env=env)
        module.check(out)
        summary=json.loads((out/'paired/summary.json').read_text())
        save(out/'report.json',dict(build=identity(out/'build.json'),policy=identity(out/'policy.json'),structure=identity(out/'structure.json'),
            summary=identity(out/'paired/summary.json'),external_wall=summary['external_wall'],trace_checks=summary['trace_checks'],runner_correction=identity(runtime/'correction.json')))
        print(json.dumps(summary['external_wall'],indent=2),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--driver',required=True)
    args=p.parse_args();measure(args.output.resolve(),args.driver)
