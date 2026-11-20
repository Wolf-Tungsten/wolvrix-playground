"""Build and time the frozen CV32E40P benchmark through the CV and XS single-model drivers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import platform
import resource
import shutil
import sys

from armor_mask_layout_measure import ARCHIVE, LOCK
from cv32e40p_compare import CXX, ROOT, environment, identity, run, sample, save, summarize_named
from grhsim_elf_section_identity import sections
from xiangshan_cv32_ablation_measure import measurement_lock, read, verify


OUT = ROOT / 'build/armor-cv32-xs-defaults-v1'
PREVIOUS = ROOT / 'build/armor-expression-default-v1'
TOOLS = ROOT / 'build/armor-dispatch-v1/tools'
RUN2 = ARCHIVE / 'build/cv32e40p/run2'
FROZEN = ARCHIVE / 'build/cv32e40p/indexed-snapshot-v3'
FLAGS = ['-std=c++20', '-O3', '-march=native']
MODES = ('cv-off', 'cv-on', 'xs-off', 'xs-default')
# Four balanced orders, then their reverses. Each variant occupies each position twice.
ORDERS = [tuple(MODES[(i + j) % 4] for j in (0, 1, 3, 2)) for i in range(4)]
ORDERS += [order[::-1] for order in ORDERS]


def build_variant(name):
    dest = OUT / name
    model = dest / 'model'
    model.mkdir(parents=True)
    env = environment()
    if name.startswith('cv-'):
        frozen_model = PREVIOUS / name / 'model'
        for source in frozen_model.iterdir():
            if source.suffix in ('.cpp', '.hpp') or source.name == 'Makefile':
                shutil.copy2(source, model / source.name)
    else:
        env.update(PYTHONPATH=str(TOOLS / 'python'), LD_LIBRARY_PATH=str(TOOLS))
        if name == 'xs-off':
            env.update(WOLVRIX_GRHSIM_LOGIC_EAGER_OPERAND_CHARS='0', WOLVRIX_GRHSIM_KEEP_X86_MEMORY_CMOV='0')
        run([sys.executable, ROOT/'scripts/wolvrix_xs_grhsim.py', OUT/'input.f', 'Cv32Bench',
             model, '', '', 'info'], dest/'emit.log', env=env)
    run(['make', '-C', model, '-j8', 'CXX='+str(CXX), 'CXXFLAGS='+' '.join(FLAGS)], dest/'compile.log')
    cmov = '-x86-cmov-converter-force-mem-operand=false' in (dest/'compile.log').read_text()
    if cmov != (name in ('cv-on', 'xs-default')):
        raise ValueError(f'{name}: unexpected model compiler flags')
    run([CXX, *FLAGS, '-DCV32_GRHSIM', '-I', model, RUN2/'inputs/fixture/harness.cpp',
         model/'libgrhsim_Cv32Bench.a', '-o', dest/'emu'], dest/'link.log')
    shapes = sections(dest/'emu')
    save(dest/'build.json', dict(binary=identity(dest/'emu'), sections=shapes, cmov=cmov,
                                 schedule_files=len(list(model.glob('*_sched_*.cpp')))))
    print('built', name, flush=True)


def build():
    OUT.mkdir(parents=True, exist_ok=False)
    rtl = read(RUN2/'build.json')['normalization']['rtl']
    verify(rtl)
    (OUT/'input.f').write_text(rtl['path'] + '\n')
    (OUT/'firmware').symlink_to(FROZEN/'firmware')
    (OUT/'verification.json').symlink_to(FROZEN/'verification.json')
    save(OUT/'policy.json', dict(rtl=rtl, harness=identity(RUN2/'inputs/fixture/harness.cpp'),
         coremark=identity(OUT/'firmware/coremark/workload.bin'), compiler=identity(CXX), flags=FLAGS,
         driver=identity(ROOT/'scripts/wolvrix_xs_grhsim.py'), wolvrix=identity(TOOLS/'libwolvrix-lib.so'),
         cv_source_dirs=[str(PREVIOUS/name/'model') for name in MODES[:2]],
         cpu=96, numa=1, warmups=1, orders=ORDERS, lock=str(LOCK)))
    resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    with ThreadPoolExecutor(max_workers=len(MODES)) as pool:
        list(pool.map(build_variant, MODES))


def measure():
    expected = read(OUT/'verification.json')['workloads']
    records = {name: read(OUT/name/'build.json')['binary'] for name in MODES}
    for record in records.values():
        verify(record)
    with measurement_lock(LOCK, wait=True):
        checked = {}
        for name in MODES:
            checked[name] = {}
            for workload in ('smoke', 'coremark'):
                row = sample(OUT, name, workload, 'verify-'+workload, trace=True)
                trace = expected[workload]['verilator']['trace']
                if row['trace']['bytes'] != 36 * row['cycles'] or row['trace']['sha256'] != trace['sha256']:
                    raise ValueError(f'{name}: {workload} bus trace differs from Verilator')
                checked[name][workload] = dict(cycles=row['cycles'], trace=row['trace'])
            print('trace verified', name, flush=True)
        save(OUT/'traces.json', checked)
        for name in MODES:
            sample(OUT, name, 'coremark', 'warmup')
        rounds = []
        for index, order in enumerate(ORDERS, 1):
            row = {name: sample(OUT, name, 'coremark', f'round-{index}') for name in order}
            rounds.append(row)
            save(OUT/'rounds.json', rounds)
            print('round', index, {name: round(row[name]['wall_s'], 3) for name in order}, flush=True)
    for record in records.values():
        verify(record)
    comparisons = [('xs-default', 'cv-off'), ('xs-default', 'xs-off'), ('xs-off', 'cv-off'),
                   ('cv-on', 'cv-off'), ('xs-default', 'cv-on')]
    save(OUT/'summary.json', {a+'/'+b: summarize_named(rounds, a, b) for a, b in comparisons})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('build', 'measure'))
    args = parser.parse_args()
    if not platform.node().startswith('node030'):
        parser.error('build and measure on node030 for -march=native and the CPU96 timing protocol')
    (build if args.stage == 'build' else measure)()
