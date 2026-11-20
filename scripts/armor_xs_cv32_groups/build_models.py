"""Rebuild from the TNO0017 checkpoint with just the three XS group overrides varied."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
import filecmp
import resource
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/armor-xs-cv32-groups-v1'
sys.path.insert(0, str(ROOT / 'scripts'))
from grhsim_single_baseline import Baseline, clean_environment, identity, save
from xiangshan_cv32_ablation_measure import read, verify

DEFAULT = ROOT / 'build/armor-expression-default-v1/default'
FROZEN = ROOT.parent / 'wolvrix-playground-new-xiangshan/build/xs/parent-default-single-20261114-v1'
TOOLS = ROOT / 'build/armor-dispatch-v1/tools'
CHECKPOINT = ROOT / 'build/armor-acc-default-v1/xs/model/wolvrix_xs_pre_reg_to_mem.json'
SWITCHES = {'events': 'EVENT_REGIONS', 'mux': 'CONDITIONAL_MUX', 'views': 'COVERED_STATE_VIEWS'}
VARIANTS = {'full': set(SWITCHES), 'events': {'events'}, 'mux': {'mux'}, 'views': {'views'}, 'base': set()}

def build(name):
    dest = OUT / name
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / 'binary.json').is_file():
        verify(read(dest / 'binary.json'))
        return
    model = dest / 'model'
    cmd = ['/usr/bin/python3', str(ROOT / 'scripts/wolvrix_xs_grhsim.py'), str(FROZEN / 'input.f'),
           'SimTop', str(model), '', str(FROZEN / 'read_args.txt'), 'info']
    settings = {'WOLVRIX_XS_GRHSIM_' + switch: str(int(k in VARIANTS[name])) for k, switch in SWITCHES.items()}
    env = dict(clean_environment(), LC_ALL='C', PYTHONPATH=str(TOOLS / 'python'), LD_LIBRARY_PATH=str(TOOLS),
               NOOP_HOME=str(ROOT.parent / 'wolvrix-playground-new-xiangshan/testcase/xiangshan'),
               WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON='1', WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON=str(CHECKPOINT),
               **settings)
    save(dest / 'emit-settings.json', dict(command=cmd, environment={k:v for k,v in env.items() if k.startswith(('WOLVRIX', 'PYTHONPATH','LD_LIBRARY'))}))
    print('emit', name, flush=True)
    with (dest / 'emit.log').open('w') as log:
        subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    if name == 'base':
        def sources(directory):
            return {f.name for f in directory.iterdir() if f.suffix in ('.cpp','.hpp') or f.name == 'Makefile'}
        original = DEFAULT / 'model'
        files = sources(original)
        if sources(model) != files:
            raise ValueError('control source inventory changed')
        for f in sorted(files):
            if not filecmp.cmp(model/f, original/f, shallow=False):
                raise ValueError('control differs: ' + f)
        frozen = read(DEFAULT / 'binary.json')
        verify(frozen)
        save(dest / 'control.json', dict(files=len(files), identical_including_makefile=True, original=str(DEFAULT)))
        save(dest / 'binary.json', frozen)
    else:
        print('compile', name, flush=True)
        shutil.copytree(DEFAULT / 'chisel-home', dest / 'chisel-home', dirs_exist_ok=True)
        previous = read(DEFAULT / 'logs/compile.command.json')['command']
        xs = Path(previous[2]).parent
        args = argparse.Namespace(output=dest, xs_source=xs, compiler=next(v[4:] for v in previous if v.startswith('CXX=')),
                                  tools_dir=TOOLS, sim_primitives='none', jobs=24)
        Baseline(args).compile()
    print('ready', name, flush=True)

if __name__ == '__main__':
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(build, n): n for n in (sys.argv[1:] or VARIANTS)}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print('failed', futures[future], exc, file=sys.stderr, flush=True)
        if any(future.exception() is not None for future in futures):
            sys.exit(1)
