"""Build the four TNO0021 simulators from frozen XiangShan generated C++, and train Clang PGO."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import resource
import shutil
import subprocess
import time

from armor_dispatch_diag import LLVM
from armor_mask_layout_measure import FIRMWARE
from grhsim_single_baseline import ROOT, clean_environment, identity, parse_run, save
from xiangshan_cv32_ablation_measure import read, signature, verify

OUT = ROOT / 'build/armor-xs-pgo-v1'
ARCHIVE = ROOT.parent / 'wolvrix-playground-new-xiangshan'
GSIM = OUT / 'gsim-source'
GSIM_GATEWAY = ARCHIVE / 'build/xs/kunminghu-v3-clang23-retest-20261111/builds/gsim/after/generated-src'
FIR = ARCHIVE / 'build/xs/parent-default-single-20261114-v1/rtl/rtl/SimTop.fir'
GENERATOR = ARCHIVE / 'reference/gsim/build/gsim/gsim'
GRHSIM = ROOT / 'build/armor-expression-default-v1/default'
XS = FIRMWARE.parent
IMAGE = FIRMWARE / 'coremark-2-iteration.bin'
NEMU = FIRMWARE / 'riscv64-nemu-interpreter-so'
ENGINES = ('grhsim', 'gsim')
JOBS = 24
MODEL_FLAGS = '-std=c++20 -O3 -march=native'


def execute(cmd, label, folder, env=None, cwd=ROOT):
    folder.mkdir(exist_ok=True, parents=True)
    cmd = list(map(str, cmd))
    save(folder/(label+'.command.json'), dict(argv=cmd, cwd=str(cwd)))
    start = time.monotonic()
    with (folder/(label+'.log')).open('w') as log:
        value = subprocess.run(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    save(folder/(label+'.result.json'), dict(returncode=value.returncode, elapsed_s=time.monotonic()-start))
    value.check_returncode()


def header(engine):
    generated = GRHSIM/'chisel-home/build/generated-src' if engine == 'grhsim' else GSIM_GATEWAY
    return generated/'difftest-state.h'


def generate_gsim():
    model = GSIM/'model'
    model.mkdir(parents=True,exist_ok=True)
    if not (GSIM/'complete').exists():
        cmd = [GENERATOR, '--supernode-max-size=15', '--cpp-max-size-KB=8192',
               '--sep-mod=__DOT__', '--sep-aggr=__DOT__', '--dir', model, FIR]
        execute(cmd, 'generate', GSIM)
        if not (model/'SimTop0.cpp').is_file():
            raise ValueError('GSIM did not emit SimTop')
        (GSIM/'complete').touch()


def workspace(engine, mode):
    return OUT/engine/('ordinary' if mode == 'off' else 'profiled')


def build(engine, mode):
    dest = OUT/engine/mode
    if (dest/'binary.json').exists():
        verify(read(dest/'binary.json'))
        return
    work = workspace(engine, mode)
    grh = engine == 'grhsim'
    model = work/'model' if grh else work/'gsim-compile/model'
    source = GRHSIM/'model' if grh else GSIM/'model'
    model.mkdir(exist_ok=True, parents=True)
    for path in sorted(source.iterdir()):
        if path.name == 'Makefile' or path.suffix in ('.h','.hpp','.cpp'):
            link = model/path.name
            if not link.exists():
                link.symlink_to(path)
            if link.resolve() != path.resolve():
                raise ValueError(f'unexpected frozen source {link}')
    binary = work/(engine+'-compile')/'emu'
    prof = OUT/engine/'profile'
    prof.mkdir(exist_ok=True, parents=True)
    if mode == 'use':
        verify(read(prof/'merged.json'))
        # Clang local-function profile names can contain their source path.
        # Reuse the training source paths, while forcing every object to be rebuilt.
        for pattern in ('*.o','*.a','*.pch'):
            for obj in model.glob(pattern):
                obj.unlink()
        for obj in (binary.parent/'other').glob('*.o'):
            obj.unlink()
        binary.unlink(missing_ok=True)
    instr = '-fprofile-generate' if mode == 'generate' else (
        '-fprofile-use='+str(prof/'merged.profdata') if mode == 'use' else '')
    cflags = instr
    if mode == 'generate':
        # Same training policy in both engines. Clang 23 miscompiles an instrumented
        # GrhSIM path with SLP enabled (TNO0016); both measured binaries retain SLP.
        cflags += ' -fno-slp-vectorize'
    common = ['make','-j'+str(JOBS),'-C',XS/'difftest',engine+'-build-emu',
              'BUILD_DIR='+str(work),'NUM_CORES=1','EMU_THREADS=0','EMU_RANDOMIZE=0',
              'WITH_CHISELDB=0','WITH_CONSTANTIN=0','NO_DIFF=0','EMU_TRACE=',
              'PGO_WORKLOAD=','PGO_BOLT=0','EMU_OPTIMIZE=-O3 -march=native',
              'PGO_CFLAGS='+cflags,'PGO_LDFLAGS='+instr,'CXX='+str(LLVM/'clang++'),
              'CC='+str(LLVM/'clang'),'AR='+str(LLVM/'llvm-ar'),
              'GEN_CSRC_DIR='+str(header(engine).parent),'GEN_VSRC_DIR='+str(header(engine).parent)]
    if grh:
        common.extend(['GRHSIM=1','WOLVRIX_GRHSIM_WAVEFORM=0','WOLVRIX_GRHSIM_PERF=0',
                       'GRHSIM_MODEL_DIR='+str(model),'GRHSIM_MODEL_BUILD_JOBS='+str(JOBS),
                       'GRHSIM_MODEL_CXXFLAGS='+(MODEL_FLAGS+' '+cflags).strip()])
    else:
        common.extend(['GSIM=1','GSIM_CXX='+str(LLVM/'clang++'),'GSIM_BIN=/usr/bin/false',
                       '-o',model/'SimTop0.cpp'])
    env = dict(clean_environment(), LC_ALL='C', NOOP_HOME=str(XS))
    print('compiling',engine,mode,flush=True)
    execute([*common,'-n'],'commands',dest,env)
    execute(common,'compile',dest,env)
    shutil.copy2(binary,dest/'emu')
    save(dest/'binary.json',identity(dest/'emu'))
    print('built',engine,mode,flush=True)


def run_window(engine, mode, task, image, cpu, trace=True):
    record = read(OUT/engine/mode/'binary.json')
    verify(record)
    folder = OUT/engine/mode/task
    folder.mkdir(exist_ok=True, parents=True)
    env = dict(clean_environment(), LC_ALL='C', EMU_PROGRESS_EVERY_CYCLES='0')
    if mode == 'generate':
        env['LLVM_PROFILE_FILE'] = str(folder/'run-%p.profraw')
    cmd = ['taskset','-c',str(cpu),'numactl','--membind=1','setarch','x86_64','-R',
           record['path'],'-i',image,'--diff',NEMU,'-b','0','-e','0','-s','0','-C','100000']
    if trace:
        cmd += ['--dump-difftrace','./trace']
    execute(cmd,'run',folder,env,folder)
    row = parse_run((folder/'run.log').read_text(),100000)
    save(folder/'endpoint.json',signature(row))
    return row


def train(engine):
    build(engine,'generate')
    prof = OUT/engine/'profile'
    if not (prof/'merged.json').exists():
        training = OUT/engine/'generate/training'
        if list(training.glob('*.profraw')):
            raise ValueError(f'unmerged training data already exists in {prof}')
        cpu = 148 if engine == 'grhsim' else 164
        row = run_window(engine,'generate','training',IMAGE,cpu,trace=False)
        raws = list(training.glob('run-*.profraw'))
        if len(raws) != 1:
            raise ValueError('expected one training profile')
        execute([LLVM/'llvm-profdata','merge',raws[0],'-o',prof/'merged.profdata'],'merge',prof)
        execute([LLVM/'llvm-profdata','show',prof/'merged.profdata'],'show',prof)
        save(prof/'raw.json',identity(raws[0]))
        save(prof/'merged.json',identity(prof/'merged.profdata'))
        print('trained',engine,signature(row),flush=True)
    build(engine,'use')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('jobs',nargs='*',help='grhsim-off, grhsim-pgo, gsim-off, gsim-pgo (default: all)')
    args=parser.parse_args()
    resource.setrlimit(resource.RLIMIT_STACK,(resource.RLIM_INFINITY,resource.RLIM_INFINITY))
    cases=args.jobs or [e+'-'+m for e in ENGINES for m in ('off','pgo')]
    if any(case.startswith('gsim-') for case in cases):
        generate_gsim()
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[]
        for case in cases:
            engine, action=case.split('-')
            if engine not in ENGINES or action not in ('off','pgo'):
                parser.error('unknown case '+case)
            jobs.append(pool.submit(train,engine) if action=='pgo' else pool.submit(build,engine,'off'))
        for future in jobs:
            future.result()
