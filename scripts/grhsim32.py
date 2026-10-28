#!/usr/bin/env python3
"""Clean, portable Verilog -> 32-way GrhSIM -> automatic refinement -> emu.

Only source files, the checked-in configuration and normal tool dependencies
are inputs. No historical build product or intermediate verifier is used.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
from fractions import Fraction
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import statistics
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
NATIVE = ROOT / 'tools/grhsim32'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def read(path):
    return json.loads(path.read_text())


def compiler():
    return shutil.which(os.environ.get('CXX', '')) or shutil.which('clang++') or shutil.which('g++')


def cpu_list(value):
    result = set()
    for entry in value.split(','):
        limits = list(map(int, entry.split('-')))
        result.update(range(limits[0], limits[-1] + 1))
    return sorted(result)


def enable_generation_cpus():
    """Use online CPUs allowed by the kernel, including SSH-excluded siblings."""
    try:
        online = cpu_list(Path('/sys/devices/system/cpu/online').read_text().strip())
        os.sched_setaffinity(0, online)
    except OSError:
        pass  # A scheduler/cgroup may forbid broadening this process's mask.


def runtime_cpus(allowed):
    """Prefer one NUMA domain, one sibling per physical core, then fill."""
    choices = []
    nodes = sorted(Path('/sys/devices/system/node').glob('node[0-9]*/cpulist'))
    groups = [sorted(set(cpu_list(p.read_text().strip())) & set(allowed)) for p in nodes]
    groups += [list(allowed)]
    for group in groups:
        selected, cores = [], set()
        for cpu in group:
            topology = Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
            try:
                key = ((topology / 'physical_package_id').read_text(), (topology / 'core_id').read_text())
            except OSError:
                key = cpu
            if key not in cores:
                selected.append(cpu)
                cores.add(key)
        selected += [cpu for cpu in group if cpu not in selected]
        if len(selected) >= 32:
            choices.append(selected[:32])
    if not choices:
        raise ValueError('the 32-thread flow needs at least 32 available logical CPUs')
    return choices[0]


def solver_groups(cpus, runs=8):
    groups = [[] for _ in range(runs)]
    units = {}
    for cpu in cpus:
        path = Path(f'/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list')
        siblings = tuple(sorted(set(cpu_list(path.read_text().strip())) & set(cpus))) if path.exists() else (cpu,)
        units[siblings] = siblings
    for unit in sorted(units.values()):
        groups[min(range(runs), key=lambda i: (len(groups[i]), i))].extend(unit)
    return [group or [cpus[i % len(cpus)]] for i, group in enumerate(groups)]


def align_object(path, objcopy):
    data = path.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('64-bit little-endian ELF model objects are required')
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count, strings = struct.unpack_from('<HHH', data, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * size) for i in range(count)]
    table = sections[strings]
    names = data[table[4]:table[4] + table[5]]
    command = [objcopy]
    for section in sections:
        if section[2] & 4 and section[5] and section[8] < 64:
            end = names.index(b'\0', section[0])
            command += ['--set-section-alignment', names[section[0]:end].decode() + '=64']
    if len(command) > 1:
        subprocess.run([*command, str(path)], check=True, stdout=subprocess.DEVNULL)


class Pipeline:
    def __init__(self, args):
        self.args = args
        self.config = read(args.config)
        self.out = args.output.resolve()
        self.jobs = args.jobs or len(os.sched_getaffinity(0))
        self.cpus = sorted(os.sched_getaffinity(0))
        self.runtime = cpu_list(args.runtime_cpus) if args.runtime_cpus else runtime_cpus(self.cpus)
        if len(self.runtime) != 32:
            raise ValueError('runtime CPUs must name 32 distinct CPUs')
        self.cxx = compiler()
        self.cc = shutil.which(os.environ.get('CC', '')) or shutil.which('clang') or shutil.which('gcc')
        self.host_cxx = shutil.which('g++') or self.cxx
        self.host_cc = shutil.which('gcc') or self.cc
        self.ar = shutil.which('llvm-ar') or shutil.which('ar')
        self.objcopy = shutil.which('llvm-objcopy') or shutil.which('objcopy')
        if not all((self.cxx, self.cc, self.ar, self.objcopy)):
            raise ValueError('a C/C++20 compiler, ar and objcopy must be installed')
        self.build = ROOT / 'build/grhsim32-tools'
        self.bin = self.build / 'bin'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('WOLVRIX_GRHSIM_', 'WOLVRIX_REPCUT_', 'WOLVRIX_REPLAY_', 'WOLVRIX_ACTIVITY_',
                                         'XS_REPCUT_', 'WOLVI_REPCUT_', 'EMU_', 'REPCUT_CODEPAGE_'))
                    and k not in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'MAKEFLAGS', 'MFLAGS')}
        self.env.update(self.config['options'])
        self.env['LC_ALL'] = 'C'
        self.env['NOOP_HOME'] = str(ROOT / 'testcase/xiangshan')

    def run_command(self, command, log, env=None, cwd=ROOT):
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('w') as stream:
            result = subprocess.run(list(map(str, command)), cwd=cwd, env=env or self.env,
                                    stdout=stream, stderr=subprocess.STDOUT, check=False)
            if result.returncode:
                raise RuntimeError(f'command exited {result.returncode}; log: {log}')

    def stage(self, name):
        print('[grhsim32] ' + name, flush=True)
        save(self.out / 'progress.json', dict(stage=name, time=time.time()))

    def dependencies(self):
        for name in ('wolvrix', 'testcase/xiangshan'):
            if not (ROOT / name / 'CMakeLists.txt').exists() and not (ROOT / name / 'Makefile').exists():
                self.run_command(['git', 'submodule', 'update', '--init', '--recursive', name],
                                 self.out / 'logs' / (name.replace('/', '-') + '-submodule.log'))
        dependencies = (('wolvrix', 'external/slang', 'CMakeLists.txt'),
                        ('wolvrix', 'external/libfst', 'src/fstapi.c'),
                        ('testcase/xiangshan', 'difftest', 'grhsim.mk'),
                        ('testcase/xiangshan', 'ready-to-run', 'coremark-2-iteration.bin'))
        for parent, name, marker in dependencies:
            if not (ROOT / parent / name / marker).exists():
                self.run_command(['git', '-C', ROOT / parent, 'submodule', 'update', '--init', '--recursive', name],
                                 self.out / 'logs' / (name.replace('/', '-') + '-submodule.log'))
        self.stage('build native tools from source')
        self.run_command(['cmake', '-S', NATIVE, '-B', self.build, '-DCMAKE_BUILD_TYPE=Release',
                          f'-DCMAKE_C_COMPILER={self.host_cc}', f'-DCMAKE_CXX_COMPILER={self.host_cxx}'],
                         self.out / 'logs/tools-configure.log')
        self.run_command(['cmake', '--build', self.build, '--target', 'grhsim32_tools', '-j', self.jobs],
                         self.out / 'logs/tools-build.log')
        self.stage('build multi-constraint solver from pinned source')
        source = ROOT / 'build/grhsim32-deps/mt-kahypar'
        if not (source / '.git').exists():
            source.mkdir(parents=True, exist_ok=True)
            self.run_command(['git', 'init', source], self.out / 'logs/solver-init.log')
            self.run_command(['git', '-C', source, 'remote', 'add', 'origin', self.config['solver']['repository']],
                             self.out / 'logs/solver-remote.log')
        if not (source / 'CMakeLists.txt').exists():
            self.run_command(['git', '-C', source, 'fetch', '--depth=1', self.config['solver']['repository'],
                              self.config['solver']['revision']],
                             self.out / 'logs/solver-fetch.log')
            self.run_command(['git', '-C', source, 'checkout', '--detach', 'FETCH_HEAD'],
                             self.out / 'logs/solver-checkout.log')
        patch_marker = source / '.grhsim32-fallback-applied'
        if not patch_marker.exists():
            self.run_command(['git', '-C', source, 'apply', NATIVE / 'mt-kahypar-fallback.patch'],
                             self.out / 'logs/solver-patch.log')
            patch_marker.touch()
        solver_build = source.parent / 'solver-build-host'
        self.run_command(['cmake', '-S', source, '-B', solver_build, '--preset=default',
                          '-DKAHYPAR_DOWNLOAD_TBB=ON', '-DKAHYPAR_DOWNLOAD_BOOST=OFF',
                          '-DKAHYPAR_DISABLE_HWLOC=ON', '-DLLD_BIN=OFF', f'-DCMAKE_CXX_COMPILER={self.host_cxx}',
                          f'-DCMAKE_C_COMPILER={self.host_cc}'], self.out / 'logs/solver-configure.log')
        self.run_command(['cmake', '--build', solver_build, '--target', 'MtKaHyPar', '-j', self.jobs],
                         self.out / 'logs/solver-build.log')
        self.solver = solver_build / 'mt-kahypar/application/MtKaHyPar'
        self.solver_config = source / 'config/default_preset.ini'

    def inputs(self):
        self.stage('prepare Verilog inputs')
        self.generated = self.args.generated.resolve()
        rtl = self.args.rtl.resolve() if self.args.rtl else None
        if self.args.filelist:
            files = [Path(line).resolve() for line in self.args.filelist.read_text().splitlines()
                     if line.strip() and not line.lstrip().startswith('//')]
            if rtl is None and files:
                rtl = files[0].parent
        else:
            if rtl is None:
                self.run_command(['make', '-C', ROOT / 'testcase/xiangshan', 'sim-verilog',
                                  f'BUILD_DIR={self.out / "rtl"}', 'NUM_CORES=1', 'RTL_SUFFIX=sv'],
                                 self.out / 'logs/rtl.log')
                rtl = self.out / 'rtl/rtl'
                if not (self.generated / 'DifftestMacros.svh').exists():
                    self.generated = self.out / 'rtl/generated-src'
            common = ROOT / 'testcase/xiangshan/difftest/src/test/vsrc/common'
            files = sorted({p for folder in (rtl, common) for p in folder.rglob('*') if p.suffix in ('.sv', '.v')})
        if not files:
            raise ValueError('no Verilog sources found')
        filelist = self.out / 'input.f'
        filelist.write_text(''.join(str(p) + '\n' for p in files))
        extra = shlex.split(self.args.read_args.read_text()) if self.args.read_args else [
            '-I', str(rtl), '-I', str(self.generated),
            '-I', str(ROOT / 'testcase/xiangshan/difftest/src/test/vsrc/common'), '-D', 'DIFFTEST']
        self.stage('read and lower Verilog')
        self.run_command([self.bin / 'grhsim32_frontend', self.out / 'raw.json', self.config['top'],
                          '-f', filelist, *extra], self.out / 'logs/frontend.log')
        self.stage('convert configured memories')
        memory = self.out / 'memory.txt'
        memory.write_text(''.join(name + '\n' for name in self.config['memory']['targets']))
        self.run_command([self.bin / 'grhsim32_partition', 'memory', self.out / 'raw.json',
                          self.out / 'memory.json', memory, self.config['memory']['row_limit']],
                         self.out / 'logs/memory.log')

    def solve(self):
        from repcut_grhsim_isolated_initial import read_weights, reduce_graph, select_oversized, restore_labels
        self.stage('extract fresh six-axis graph from current RTL')
        folder = self.out / 'initial_graph'
        self.run_command([self.bin / 'grhsim32_initial_graph', self.out / 'memory.json', folder, 'clock'],
                         self.out / 'logs/initial-graph.log')
        graph = folder / 'initial.hgr'
        _, weights = read_weights(graph)
        isolated = select_oversized(weights, 32, Fraction(str(self.config['epsilon'])))
        reduced = folder / 'reduced.hgr'
        isolation = reduce_graph(graph, reduced, isolated)
        del weights
        self.stage('solve eight independent initial assignments')
        groups = solver_groups(self.cpus, self.config['solver_runs'])

        def one(seed):
            dest = self.out / 'solves' / f'seed{seed}'
            dest.mkdir(parents=True)
            command = ['taskset', '-c', ','.join(map(str, groups[seed])), self.solver,
                       '-h', reduced, '-k', str(32 - len(isolated)), '-e', self.config['epsilon'],
                       '-o', 'km1', '-p', self.solver_config, '-t', len(groups[seed]), '--seed', seed,
                       '--verbose', '1', '--write-partition-file', '1', '--partition-output-folder', dest]
            try:
                self.run_command(command, dest / 'solver.log')
                emitted = next(dest.glob('*.KaHyPar'))
                labels = restore_labels(list(map(int, emitted.read_text().split())), isolation['nodes'], isolated, 32)
                assignment = dest / 'assignment.txt'
                assignment.write_text(''.join(f'{p}\n' for p in labels))
                return dict(seed=seed, assignment=str(assignment), status='pass')
            except (RuntimeError, StopIteration, ValueError) as error:
                return dict(seed=seed, status='failed', error=str(error))

        with ThreadPoolExecutor(max_workers=len(groups)) as pool:
            results = list(pool.map(one, range(len(groups))))
        viable = [row for row in results if row['status'] == 'pass']
        if not viable:
            save(self.out / 'solves/result.json', results)
            raise RuntimeError('all solver attempts failed; see solves/seed*/solver.log')
        score = subprocess.check_output([str(self.bin / 'grhsim32_score'), str(graph), str(len(isolated)),
                                        *(row['assignment'] for row in viable)], text=True)
        for line in score.splitlines():
            index, value, feasible = map(int, line.split())
            viable[index]['km1'] = value
            viable[index]['capacity_feasible'] = bool(feasible)
        feasible = [row for row in viable if row['capacity_feasible']]
        if not feasible:
            save(self.out / 'solves/result.json', results)
            raise RuntimeError('none of the eight solves met the six-dimensional capacity constraint')
        selected = min(feasible, key=lambda row: (row['km1'], row['seed']))
        save(self.out / 'selection.json', dict(selected=selected, attempts=results, isolated=isolated))
        return Path(selected['assignment'])

    def emit(self, stage, labels):
        self.stage('replay and generate ' + stage.name)
        stage.mkdir()
        shutil.copyfile(labels, stage / 'assignment.txt')
        self.run_command([self.bin / 'grhsim32_partition', 'replay', self.out / 'memory.json', stage, 32,
                          stage / 'assignment.txt'], stage / 'replay.log')
        self.run_command([self.bin / 'grhsim32_replay', stage / 'partitioned.json', stage / 'assignment.txt',
                          stage / 'emit-work', stage / 'unused.json', stage / 'package'], stage / 'emit.log',
                         dict(self.env, WOLVRIX_REPLAY_EMIT_ONLY='1'))
        self.compile(stage)

    def harness(self, stage):
        archive = stage / 'package/libgrhsim_SimTop.a'
        command = ['make', f'-j{self.jobs}', '-C', ROOT / 'testcase/xiangshan/difftest', 'emu-grhsim',
                   f'CC={self.cc}', f'CXX={self.cxx}', f'BUILD_DIR={stage / "harness"}',
                   f'GEN_CSRC_DIR={self.generated}', f'GEN_VSRC_DIR={self.generated}',
                   'NUM_CORES=1', 'WITH_CHISELDB=0', 'WITH_CONSTANTIN=0', 'EMU_THREADS=0', 'EMU_RANDOMIZE=0',
                   'GRHSIM=1', f'GRHSIM_MODEL_DIR={stage / "package"}', f'GRHSIM_MODEL_LIB={archive}',
                   'GRHSIM_COMPILER_FLAGS=', 'GRHSIM_MODEL_CXXFLAGS=-std=c++20 -O3 -march=native',
                   'EMU_OPTIMIZE=-O3', 'WOLVRIX_GRHSIM_WAVEFORM=0',
                   'GRHSIM_LDFLAGS=$(SIM_LDFLAGS) -ldl $(PGO_LDFLAGS) -pthread', '-o', archive]
        self.run_command(command, stage / 'harness.log')
        return stage / 'harness/grhsim-compile/emu'

    def compile(self, stage):
        self.stage('compile ' + stage.name)
        package, objects = stage / 'package', stage / 'objects'
        objects.mkdir()
        names = re.search(r'^SRCS :=(.*)$', (package / 'Makefile').read_text(), re.M)[1].split()

        def one(name):
            obj = objects / Path(name).with_suffix('.o')
            self.run_command([self.cxx, '-std=c++20', '-O3', '-march=native', '-pthread',
                              '-I', package, '-c', package / name, '-o', obj], obj.with_suffix('.log'))
            align_object(obj, self.objcopy)
            return obj

        with ThreadPoolExecutor(max_workers=self.jobs) as pool:
            compiled = list(pool.map(one, names))
        response = stage / 'objects.rsp'
        response.write_text(''.join('"' + str(obj) + '"\n' for obj in compiled))
        self.run_command([self.ar, 'rcs', package / 'libgrhsim_SimTop.a', '@' + str(response)], stage / 'archive.log')
        self.harness(stage)

    def simulate(self, stage, folder, name, cycles=100000, trace=None):
        folder.mkdir(parents=True, exist_ok=True)
        binary = stage / 'harness/grhsim-compile/emu'
        preload = str(self.build / 'libgrhsim32_collapse_retry.so') + ':' + str(self.build / 'libgrhsim32_codepage.so')
        command = ['env', 'LD_PRELOAD=' + preload, 'REPCUT_CODEPAGE_MODE=' + self.args.codepages,
                   str(binary), '-i', str(self.args.image.resolve()), '--diff', str(self.args.nemu.resolve()),
                   '-b', '0', '-e', '0', '-C', str(cycles)]
        if self.aslr_off:
            command = ['setarch', platform.machine(), '-R', *command]
        if self.numa is not None and shutil.which('numactl'):
            command = ['numactl', f'--preferred={self.numa}', *command]
        command = ['taskset', '-c', ','.join(map(str, self.runtime)), *command]
        env = dict(self.env, XS_EMU_THREADS='32', XS_REPCUT_STEP_TIMING='1',
                   WOLVI_REPCUT_TIMING_JSONL=str(folder / (name + '.timing.jsonl')),
                   WOLVI_GRHSIM_CODE_HUGEPAGE='0')
        if trace:
            env['REPCUT_CYCLE_TRACE_FILE'] = str(trace)
        begin = time.monotonic()
        self.run_command(command, folder / (name + '.log'), env)
        elapsed = time.monotonic() - begin
        text = (folder / (name + '.log')).read_text()
        if cycles > 100 and 'Difftest enabled' not in text:
            raise RuntimeError(name + ': difftest did not start')
        if re.search(r'ABORT|HIT BAD TRAP|mismatch|Assertion.*failed', text):
            raise RuntimeError(name + ': functional failure')
        if 'EXCEEDING CYCLE/INSTR LIMIT' not in text:
            raise RuntimeError(name + ': requested cycle limit not reached')
        parts = [json.loads(line) for line in (folder / (name + '.timing.jsonl')).read_text().splitlines() if line]
        host = re.search(r'Host time spent: (\d+)ms', text)
        config = re.search(r'^\[runtime-config\] (\{.*\})$', text, re.M)
        if not config or json.loads(config[1])['lanes'] != 32:
            raise RuntimeError(name + ': expected 32 lanes')
        page = re.search(r'\[codepage\] PASS mode=(\w+) bytes=(\d+) anon_huge=(\d+) regions=(\d+)', text)
        return dict(name=name, elapsed_s=elapsed, host_s=int(host[1]) / 1000,
                    functional='pass', runtime=json.loads(config[1]),
                    codepages=(dict(mode=page[1], bytes=int(page[2]), huge_bytes=int(page[3]), regions=int(page[4]))
                               if page else None), parts=parts)

    def measure(self, stage, folder, repeats=8):
        self.stage('final functional and walltime runs: ' + stage.name)
        self.simulate(stage, folder, 'smoke', 100)
        runs = [self.simulate(stage, folder, f'run{i + 1:02d}') for i in range(repeats)]
        save(folder / 'summary.json', dict(runs=runs, walltime_median_s=statistics.median(r['elapsed_s'] for r in runs),
                                         host_median_s=statistics.median(r['host_s'] for r in runs)))
        return runs

    def trace(self, initial):
        from repcut_cycle_instrument import instrument, SUFFIXES
        self.stage('profile completed initial emu for automatic migration')
        stage = self.out / 'trace'
        package = stage / 'package'
        package.mkdir(parents=True)
        source = initial / 'package'
        for path in source.iterdir():
            if path.name != 'libgrhsim_SimTop.a':
                (package / path.name).symlink_to(path)
        archive = package / 'libgrhsim_SimTop.a'
        shutil.copyfile(source / archive.name, archive)
        objects = []
        for suffix in SUFFIXES:
            name = 'wolvi_repcut_grhsim_sim_' + suffix
            cpp = stage / (name + '.cpp')
            cpp.write_text(instrument((source / (name + '.cpp')).read_text(), suffix))
            obj = stage / (name + '.o')
            self.run_command([self.cxx, '-std=c++20', '-O3', '-march=native', '-pthread',
                              '-I', package, '-I', SCRIPTS, '-c', cpp, '-o', obj], stage / (name + '.log'))
            align_object(obj, self.objcopy)
            objects.append(obj)
        self.run_command([self.ar, 'r', archive, *objects], stage / 'archive.log')
        self.harness(stage)
        paths = []
        for i in range(2):
            path = stage / f'run{i}.trace.bin'
            self.simulate(stage, stage / 'runs', f'run{i}', trace=path)
            paths.append(path)
        self.run_command([sys.executable, SCRIPTS / 'repcut_grhsim_critical_profile.py',
                          '--no-input-checks', '--output', stage / 'profile.json',
                          *sum((['--trace', path] for path in paths), [])],
                         stage / 'profile.log')
        return paths

    def search(self, initial, measured):
        from repcut_grhsim_local_search_rank import select_migration
        import csv
        traces = self.trace(initial)
        context = self.out / 'context'
        self.run_command([self.bin / 'grhsim32_context', self.out / 'memory.json', context, 'clock'],
                         self.out / 'logs/context.log')
        folder = self.out / 'migration'
        folder.mkdir()
        parts = folder / 'parts.csv'
        rows = []
        for i, run in enumerate(measured):
            for part in run['parts']:
                if part.get('record_type') == 'part_timing':
                    rows.append(dict(pair=i + 1, variant='candidate', **part))
        with parts.open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        proposals = folder / 'proposals'
        self.run_command([sys.executable, SCRIPTS / 'repcut_grhsim_piece_candidates.py',
                          '--model', context / 'source_model.txtdata', '--features', context / 'atom_backend_features.csv',
                          '--assignment', initial / 'assignment.txt', '--critical-profile', self.out / 'trace/profile.json',
                          '--source-count', 3, '--top', 8, '--targets', 3, '--no-input-checks',
                          '--output', proposals], folder / 'propose.log')
        if not read(proposals / 'selection.json')['candidates']:
            save(folder / 'result.json', dict(accepted=False, reason='no proposals'))
            return initial
        self.run_command([sys.executable, SCRIPTS / 'repcut_grhsim_piece_splits.py', 'evaluate',
                          '--model', context / 'source_model.txtdata', '--baseline', initial / 'assignment.txt',
                          '--selection', proposals / 'selection.json', '--evaluator', self.bin / 'grhsim32_assignment_eval',
                          '--output', folder / 'evaluation'], folder / 'evaluate.log')
        budget = folder / 'budget.json'
        save(budget, dict(rules=[dict(feature=f, scope=s, max_change_percent=0)
                                for f in ('send_calls', 'send_bytes', 'receive_calls', 'receive_bytes')
                                for s in ('sum', 'peak')]))
        command = [sys.executable, SCRIPTS / 'repcut_grhsim_local_search_rank.py',
                   '--report', folder / 'evaluation/report.json', '--parts', parts,
                   '--profile-variant', 'candidate', '--activity-model', 'source-envelope',
                   '--budget', budget, '--no-input-checks', '--output', folder / 'ranking.json']
        for path in traces:
            command += ['--critical-trace', path]
        self.run_command(command, folder / 'rank.log')
        selected = select_migration(read(folder / 'ranking.json'))
        if selected is None:
            save(folder / 'result.json', dict(accepted=False, reason='no improving proposal within communication budget'))
            return initial
        candidate = self.out / 'candidate'
        try:
            self.emit(candidate, proposals / (selected['name'] + '.assignment'))
            accepted = all(self.compare(initial, candidate, folder / f'ab_ba{round}') for round in (1, 2))
        except (RuntimeError, subprocess.SubprocessError) as error:
            save(folder / 'result.json', dict(accepted=False, selected=selected,
                                             reason='candidate build or final runtime failed', error=str(error)))
            return initial
        save(folder / 'result.json', dict(accepted=accepted, selected=selected))
        return candidate if accepted else initial

    def compare(self, baseline, candidate, folder):
        self.stage('fresh AB/BA comparison: ' + folder.name)
        rows = []
        for pair in range(8):
            order = [('baseline', baseline), ('candidate', candidate)]
            if pair % 2:
                order.reverse()
            result = {}
            for name, stage in order:
                result[name] = self.simulate(stage, folder, f'pair{pair + 1:02d}-{name}')
            rows.append(dict(pair=pair + 1, **result))
        deltas = [100 * (row['candidate']['elapsed_s'] / row['baseline']['elapsed_s'] - 1) for row in rows]
        wins = sum(d < 0 for d in deltas)
        median = statistics.median(deltas)
        save(folder / 'summary.json', dict(pairs=rows, paired_walltime_delta_pct=median, candidate_wins=wins))
        return median < 0 and wins >= 6

    def configure_runtime(self):
        self.aslr_off = shutil.which('setarch') is not None and subprocess.run(
            ['setarch', platform.machine(), '-R', 'true'], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL).returncode == 0
        self.numa = None
        for path in Path('/sys/devices/system/node').glob('node[0-9]*/cpulist'):
            if set(self.runtime) <= set(cpu_list(path.read_text().strip())):
                self.numa = int(path.parent.name[4:]); break

    def run_existing(self):
        result = read(self.out / 'result.json')
        self.configure_runtime()
        stage = self.out / result['retained']
        folder = self.out / ('rerun-' + time.strftime('%Y%m%d-%H%M%S'))
        self.measure(stage, folder, self.config['pairs'])
        summary = read(folder / 'summary.json')
        print(json.dumps(dict(status='pass', report=str(folder / 'summary.json'),
                              walltime_median_s=summary['walltime_median_s'],
                              host_median_s=summary['host_median_s']), indent=2))

    def run(self):
        (ROOT / 'build').mkdir(exist_ok=True)
        self.lock = (ROOT / 'build/.grhsim32.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('another GrhSIM32 build is running') from error
        if self.out.exists():
            if not self.args.clean:
                raise ValueError(f'{self.out} exists; use --clean to generate afresh')
            if ROOT / 'build' not in self.out.parents or self.out == self.build:
                raise ValueError('clean output must be a directory under this repository build/')
            # Rename first: an NFS log reader can temporarily keep .nfs files
            # open. The new design directory must start empty regardless.
            previous = self.out.with_name(self.out.name + '.previous-' + str(time.time_ns()))
            self.out.rename(previous)
            shutil.rmtree(previous, ignore_errors=True)
        self.out.mkdir(parents=True)
        save(self.out / 'configuration.json', dict(config=self.config, compiler=self.cxx, jobs=self.jobs,
                                                  runtime_cpus=self.runtime, codepages=self.args.codepages))
        self.configure_runtime()
        self.dependencies()
        self.inputs()
        labels = self.solve()
        initial = self.out / 'initial'
        self.emit(initial, labels)
        measured = self.measure(initial, initial / 'runs', self.config['pairs'])
        retained = self.search(initial, measured)
        if retained != initial:
            self.measure(retained, retained / 'runs', self.config['pairs'])
        self.publish(retained)

    def publish(self, retained):
        binary = retained / 'harness/grhsim-compile/emu'
        for name in ('emu.bin', 'package', 'emu'):
            path = self.out / name
            if path.is_symlink():
                path.unlink()
        (self.out / 'emu.bin').symlink_to(binary)
        preload = str(self.build / 'libgrhsim32_collapse_retry.so') + ':' + str(self.build / 'libgrhsim32_codepage.so')
        launch = ['taskset', '-c', ','.join(map(str, self.runtime))]
        if self.numa is not None and shutil.which('numactl'):
            launch += ['numactl', f'--preferred={self.numa}']
        if self.aslr_off:
            launch += ['setarch', platform.machine(), '-R']
        launch += ['env', 'LD_PRELOAD=' + preload, 'REPCUT_CODEPAGE_MODE=' + self.args.codepages,
                   str(binary), '-i', str(self.args.image.resolve()), '--diff', str(self.args.nemu.resolve()),
                   '-C', str(self.config['cycles']), '-b', '0', '-e', '0']
        launcher = self.out / 'emu'
        launcher.write_text('#!/bin/sh\nexport XS_EMU_THREADS=32 XS_REPCUT_STEP_TIMING=1\n'
                            'export WOLVI_GRHSIM_CODE_HUGEPAGE=0\n' +
                            '\nexec ' + shlex.join(launch) + ' "$@"\n')
        launcher.chmod(0o755)
        (self.out / 'package').symlink_to(retained / 'package', target_is_directory=True)
        save(self.out / 'result.json', dict(status='pass', retained=retained.name,
                                          selected_seed=read(self.out / 'selection.json')['selected']['seed'],
                                          emu=str(self.out / 'emu'), runtime_cpus=self.runtime,
                                          aslr_disabled=self.aslr_off, numa_node=self.numa,
                                          timings=read(retained / 'runs/summary.json'),
                                          migration=read(self.out / 'migration/result.json')))
        self.stage('complete: ' + str(self.out / 'emu'))
        result = read(self.out / 'result.json')
        print(json.dumps(dict(selected_seed=result['selected_seed'], retained=retained.name,
                              walltime_median_s=result['timings']['walltime_median_s'],
                              migration_accepted=result['migration']['accepted'],
                              report=str(self.out / 'result.json')), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/grhsim32.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/xs/grhsim32')
    parser.add_argument('--rtl', type=Path,
                        help='explicit existing RTL input; otherwise generate RTL in this build output')
    parser.add_argument('--generated', type=Path, default=ROOT / 'testcase/xiangshan/build/generated-src')
    parser.add_argument('--filelist', type=Path)
    parser.add_argument('--read-args', type=Path)
    parser.add_argument('--image', type=Path, default=ROOT / 'testcase/xiangshan/ready-to-run/coremark-2-iteration.bin')
    parser.add_argument('--nemu', type=Path, default=ROOT / 'testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so')
    parser.add_argument('--jobs', type=int)
    parser.add_argument('--runtime-cpus')
    parser.add_argument('--codepages', choices=('auto', 'thp', 'small', 'file'), default='auto')
    parser.add_argument('--clean', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='show stages and resolved machine settings only')
    parser.add_argument('--run-only', action='store_true', help='measure the emu produced by the last clean build')
    args = parser.parse_args()
    if not args.run_only:
        enable_generation_cpus()
    pipeline = Pipeline(args)
    if args.dry_run:
        print(json.dumps(dict(stages=['native-tools', 'solver-source', 'verilog', 'mem-to-reg', 'fresh-six-axis-HGR',
                                     '8-solves-min-km1', 'replay', 'full-preset-emit', 'compile',
                                     'final-functional-walltime', 'automatic-migration', 'final-emu'],
                              output=str(pipeline.out), compiler=pipeline.cxx, jobs=pipeline.jobs,
                              runtime_cpus=pipeline.runtime, config=pipeline.config), indent=2))
        return
    if args.run_only:
        pipeline.run_existing()
    else:
        pipeline.run()


if __name__ == '__main__':
    main()
