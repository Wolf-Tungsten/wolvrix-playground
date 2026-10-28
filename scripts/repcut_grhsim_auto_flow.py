#!/usr/bin/env python3
"""Reproduce a GrhSIM experiment from RTL with structural, automatic choices.

Memory selection is structural by default. A verified historical transform
record may fix this stage for a controlled experiment. Source/destination
partition IDs and old assignments are never accepted for the new solution.
Generation uses all online CPUs; the formal runner owns runtime affinity.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from repcut_grhsim_ingest import identity

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
LLVM = Path('/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin')
LIBRARY = ROOT / 'wolvrix/build/replay-current/libwolvrix-lib.so'
RETRY = ROOT / 'build/xs_native_verilator_scaling_20261012/setup_tools/collapse_retry.so'
GENERATED = ROOT / 'build/asc_counter_print_20260915/candidate_v4/noop/build/generated-src'


def read(path: Path):
    return json.loads(path.read_text())


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Concurrent generation/analysis stages share progress.json. Each writer
    # needs its own temporary file; a common .new path races at rename.
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent,
                                     prefix=path.name + '.', suffix='.new', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(json.dumps(value, indent=2) + '\n')
            stream.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def all_cpus() -> list[int]:
    cpus = set()
    for entry in Path('/sys/devices/system/cpu/online').read_text().strip().split(','):
        bounds = list(map(int, entry.split('-')))
        cpus.update(range(bounds[0], bounds[-1] + 1))
    for task in Path('/proc/self/task').iterdir():
        os.sched_setaffinity(int(task.name), cpus)
    if os.sched_getaffinity(0) != cpus:
        raise RuntimeError('failed to enable all online CPUs')
    return sorted(cpus)


def clean_env(options: dict, library: Path) -> dict:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('WOLVRIX_GRHSIM_', 'WOLVRIX_ACTIVITY_', 'WOLVRIX_REPLAY_',
                                  'WOLVI_REPCUT_', 'XS_REPCUT_', 'EMU_'))
           and key not in ('LD_PRELOAD', 'LD_LIBRARY_PATH')}
    env.update(options)
    env.update(LD_LIBRARY_PATH=str(library.parent), LC_ALL='C')
    return env


def execute(command, log: Path, env=None) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w') as stream:
        result = subprocess.run(list(map(str, command)), cwd=ROOT, env=env,
                                stdout=stream, stderr=subprocess.STDOUT, check=False)
        if result.returncode:
            stream.write(f'\nDRIVER_SUBPROCESS_EXIT_CODE={result.returncode}\n')
            stream.flush()
            result.check_returncode()


def completed(path: Path) -> bool:
    return path.is_file() and read(path).get('status') == 'pass'


def compiler_compatibility(directory: Path, compiler: Path) -> list[str]:
    """Use the emitter's compatibility rules, including in direct builds."""
    header = ROOT / 'wolvrix/lib/emit/grhsim_compiler_compat.hpp'
    fixture = ROOT / 'wolvrix/tests/emit/data/grhsim_clang_change_reduction.cpp'
    flags = ['-std=c++20', '-O3', '-march=native']
    key = dict(compiler=identity(compiler), compatibility_header=identity(header),
               fixture=identity(fixture), flags=flags)
    marker = directory / 'result.json'
    if completed(marker):
        record = read(marker)
        if record['key'] != key:
            raise ValueError('compiler compatibility inputs changed during the run')
        return record['flags']
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / 'emit_rules.cpp'
    source.write_text('#include <iostream>\n#include "grhsim_compiler_compat.hpp"\n'
                      'int main() { wolvrix::lib::emit::emitGrhSimCompilerCompatibilityMakefile(std::cout); }\n')
    emitter = directory / 'emit_rules'
    execute(['g++', '-std=c++20', '-I', header.parent, source, '-o', emitter], directory / 'build.log')
    rules = subprocess.check_output([str(emitter)], text=True)
    rules += "\n.PHONY: flags\nflags:\n\t@printf '%s\\n' '$(GRHSIM_COMPILER_FLAGS)'\n"
    makefile = directory / 'Makefile'
    makefile.write_text(rules)
    selected = shlex.split(subprocess.check_output(
        ['make', '--no-print-directory', '-f', str(makefile), 'flags',
         f'CXX={compiler}', 'CXXFLAGS=' + ' '.join(flags)], text=True))
    obj, probe = directory / 'model.o', directory / 'probe'
    execute([compiler, *flags, *selected, '-c', fixture, '-o', obj], directory / 'model.log')
    execute([compiler, '-std=c++20', '-O0', '-DGRHSIM_REDUCTION_MAIN', fixture, obj, '-o', probe],
            directory / 'main.log')
    execute([probe], directory / 'probe.log')
    save(marker, dict(status='pass', key=key, flags=selected,
                      validation='262144 old/new index transitions; change flag equals changed outputs'))
    return selected


def install_compiler_rules(package: Path, checked_rules: Path) -> None:
    """Keep standalone make builds safe when using an older frozen emitter."""
    rules = checked_rules.read_text().split('\n.PHONY: flags\n', 1)[0]
    makefile = package / 'Makefile'
    text = makefile.read_text()
    marker = '# Compatibility rules validated by the automatic flow.\n'
    original = text.split(marker, 1)[0]
    updated = original + marker + rules + '\n'
    if updated != text:
        makefile.write_text(updated)


def performance_pass(summary: dict) -> bool:
    wall = summary['metrics']['elapsed_s']
    return wall['paired_delta_median_pct'] < 0 and wall['candidate_wins'] >= 6


def select_migration(ranking: dict) -> dict | None:
    candidates = ranking['improving_frontier']
    if not candidates:
        return None
    return min(candidates, key=lambda row: (
        row['predicted_mean_step_max_eval_us'],
        row['candidate_non_endpoint_impact_count'],
        row['candidate_send_bytes_max_part_increase'],
        row['candidate_receive_bytes_max_part_increase'], row['name']))


def reference_memories(path: Path) -> list[str]:
    record = read(path)
    names = record.get('target_memories')
    if (record.get('status') != 'pass' or not isinstance(names, list) or not names
            or any(not isinstance(name, str) or not name or any(c in name for c in '\r\n\t')
                   for name in names) or len(set(names)) != len(names)):
        raise ValueError('a successful historical mem-to-reg record with unique targets is required')
    return names


class Flow:
    def __init__(self, args):
        self.args = args
        self.out = args.output.resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.lock = (self.out / '.pipeline.lock').open('a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('another driver already owns this output directory') from error
        self.cpus = all_cpus()
        self.jobs = len(self.cpus)
        if socket.gethostname().split('.')[0] != 'node030':
            raise ValueError('run this native-build and benchmark flow on node030')
        preset = read(args.preset)
        if preset.get('status') != 'pass' or not preset.get('options'):
            raise ValueError('a verified complete emission preset is required')
        self.options = preset['options']
        self.reference = args.reference.resolve(strict=True)
        self.tools = self.out / 'tools'
        self.library = self.tools / LIBRARY.name
        self.env = clean_env(self.options, self.library)
        self.config = dict(schema='grhsim-auto-flow-v1', status='configured',
                           filelist=identity(args.filelist), read_args=identity(args.read_args),
                           preset=identity(args.preset), options=self.options,
                           top=args.top, partitions=32, cycles=100000,
                           generation_cpus=self.cpus, compile_jobs=self.jobs,
                           runtime_host='node030', runtime_cpus='96-127',
                           memory_row_limit=32, memory_top_single_cuts=10,
                           memory_top_pair_cuts=10, memory_combine_two=True,
                           memory_max_copy_growth=0.05,
                           migration_source_count=3, migration_top_pieces=8,
                           migration_destinations_per_piece=3,
                           max_replayed_candidates=1,
                           acceptance='both independent 8-pair rounds have negative paired walltime median and at least 6/8 wins',
                           reference_binary=identity(self.reference / 'harness/grhsim-compile/emu'),
                           input_assignments=[], supplied_memory_names=[],
                           supplied_partition_sources=[], supplied_partition_destinations=[])
        if args.memory_reference_run is not None:
            self.config.update(memory_selection_mode='historical controlled stage',
                               memory_reference_run=identity(args.memory_reference_run),
                               supplied_memory_names=reference_memories(args.memory_reference_run),
                               memory_row_limit=2, memory_strict_init=False)
        if args.ingest_record is not None:
            self.config['reused_ingest_record'] = identity(args.ingest_record)
        config_path = self.out / 'automatic_policy.json'
        if config_path.exists() and read(config_path) != self.config:
            raise ValueError('automatic policy changed during a run')
        save(config_path, self.config)

    def progress(self, stage: str, **details):
        save(self.out / 'progress.json', dict(stage=stage, pid=os.getpid(),
                                             host=socket.gethostname(), timestamp=time.time(), **details))
        print(stage, json.dumps(details), flush=True)

    def prepare(self):
        marker = self.tools / 'build.json'
        if completed(marker):
            for entry in read(marker)['artifacts']:
                if identity(Path(entry['path'])) != entry:
                    raise ValueError('frozen tool changed')
            return
        self.progress('build_tools', cpu_count=self.jobs)
        self.tools.mkdir(exist_ok=True)
        shutil.copy2(LIBRARY, self.library)
        names = {'memory_structure': 'repcut_memory_structure.cpp',
                 'partition': 'repcut_grhsim_partition.cpp',
                 'assignment_eval': 'repcut_grhsim_assignment_eval.cpp',
                 'context_probe': 'repcut_grhsim_context_probe.cpp',
                 'execution_plan': 'repcut_grhsim_work_features.cpp',
                 'replay': 'repcut_grhsim_replay.cpp'}

        def one(item):
            name, filename = item
            includes = ['wolvrix/include', 'wolvrix/external/slang/include',
                        'wolvrix/external/slang/external',
                        'wolvrix/build/replay-current/external/slang/source',
                        '/nfs/home/tanghaojin/usr/local/include']
            command = ['g++', '-std=c++20', '-O2', '-Wno-subobject-linkage']
            for include in includes:
                command += ['-I', include]
            command += [SCRIPTS / filename]
            if name in ('context_probe', 'assignment_eval'):
                # The research assignment model grows independently of the
                # frozen emitter library. Compile its implementation with its
                # current header instead of crossing that unstable C++ ABI.
                command += [ROOT / 'wolvrix/lib/transform/repcut_assignment_model.cpp']
            command += ['-L', self.tools,
                        '-Wl,-rpath,' + str(self.tools), '-lwolvrix-lib',
                        '-o', self.tools / name]
            execute(command, self.tools / (name + '.log'))
            return identity(self.tools / name)

        with ThreadPoolExecutor(max_workers=min(len(names), self.jobs)) as pool:
            artifacts = list(pool.map(one, names.items()))
        sources = [SCRIPTS / filename for filename in names.values()]
        sources += list(SCRIPTS.glob('repcut_grhsim_*extract.hpp'))
        sources += list(SCRIPTS.glob('repcut_grhsim_context_*.hpp'))
        sources += [ROOT / 'wolvrix/lib/transform/repcut.cpp']
        sources += [ROOT / 'wolvrix/lib/transform/repcut_assignment_model.cpp',
                    ROOT / 'wolvrix/include/transform/repcut_assignment_model.hpp']
        sources += [SCRIPTS / 'repcut_grhsim_execution_plan.cpp']
        save(marker, dict(status='pass', artifacts=[identity(self.library), *artifacts],
                          sources=[identity(source) for source in sources]))

    def ingest(self):
        if self.args.ingest_record is not None:
            record = read(self.args.ingest_record)
            if (record.get('status') != 'pass' or record.get('top') != self.args.top
                    or record['filelist'] != self.config['filelist']
                    or record['read_args'] != self.config['read_args']):
                raise ValueError('reused ingestion does not match requested RTL')
            for entry in [record['filelist'], record['read_args'], *record['rtl_inputs'],
                          *record['headers'], record['output']]:
                if identity(Path(entry['path'])) != entry:
                    raise ValueError('reused Verilog ingestion input or output changed')
            save(self.out / 'ingest_reuse.json', dict(status='pass',
                 source_record=identity(self.args.ingest_record), output=record['output'],
                 verified_rtl_files=len(record['rtl_inputs']),
                 reason='reuse identical pre-mem-to-reg graph to control upstream variation'))
            return Path(record['output']['path'])
        folder = self.out / 'ingest'
        if not completed(folder / 'run.json'):
            if folder.exists():
                raise ValueError('ingest is incomplete; inspect its running process or failure before resuming')
            self.progress('ingest_verilog')
            execute([ROOT / '.venv/bin/python', SCRIPTS / 'repcut_grhsim_ingest.py',
                     '--filelist', self.args.filelist, '--read-args', self.args.read_args,
                     '--top', self.args.top, '--all-cpus', '--output', folder], self.out / 'ingest.log')
        record = read(folder / 'run.json')
        for key in ('filelist', 'read_args'):
            if record[key] != self.config[key]:
                raise ValueError('ingest provenance does not match requested RTL')
        if identity(folder / 'raw.json') != record['output']:
            raise ValueError('fresh raw graph changed')
        return folder / 'raw.json'

    def memory(self, raw: Path) -> Path:
        folder = self.out / 'memory'
        marker = folder / 'result.json'
        if completed(marker):
            record = read(marker)
            if identity(raw) != record['input'] or identity(Path(record['output']['path'])) != record['output']:
                raise ValueError('memory stage identity changed')
            return Path(record['output']['path'])
        self.progress('capture_memory_structure')
        folder.mkdir(exist_ok=True)
        if self.args.memory_reference_run is not None:
            choice = folder / 'choice'
            choice.mkdir(exist_ok=True)
            names = reference_memories(self.args.memory_reference_run)
            save(choice / 'selection.json', dict(status='pass',
                 method='user-requested historical mem-to-reg control',
                 selected_memories=names, selected=dict(cut_memories=names),
                 reference_record=identity(self.args.memory_reference_run),
                 row_limit=2, strict_init=False, automatic_memory_selection=False,
                 automatic_migration=True))
            (choice / 'selected.txt').write_text(''.join(name + '\n' for name in names))
            self.progress('apply_historical_mem_to_reg', targets=len(names), row_limit=2)
            transformed = folder / 'mem_to_reg.json'
            execute([self.tools / 'partition', 'memory', raw, transformed,
                     choice / 'selected.txt', '2'], folder / 'transform.log', self.env)
            save(marker, dict(status='pass', input=identity(raw), output=identity(transformed),
                 selection=identity(choice / 'selection.json')))
            return transformed
        capture = folder / 'capture'
        if not completed(capture / 'run.json'):
            execute([self.tools / 'memory_structure', 'capture', raw, capture],
                    folder / 'capture.log', self.env)
            save(capture / 'run.json', dict(status='pass', input=identity(raw),
                 baseline_gate=dict(passed=True, scope='actual RepCut ASC extraction; connectivity is revalidated by separator analysis')))
        audit, requests = folder / 'separators.json', folder / 'cone_requests.tsv'
        if not audit.exists():
            self.progress('enumerate_memory_separators')
            execute([sys.executable, SCRIPTS / 'repcut_memory_separators.py',
                     '--capture-run', capture, '--output', audit, '--refinement-output', requests,
                     '--row-limit', '32', '--top-cuts', '10', '--combine-two'],
                    folder / 'separators.log', self.env)
        metrics = folder / 'metrics'
        if not completed(metrics / 'complete.json'):
            self.progress('measure_memory_cones', proposals=len(read(audit)['refinement_candidates']))
            execute([self.tools / 'memory_structure', 'metrics', raw, metrics, requests],
                    folder / 'metrics.log', self.env)
            save(metrics / 'complete.json', dict(status='pass', input=identity(raw),
                 requests=identity(requests), output=identity(metrics / 'metrics.json')))
        choice = folder / 'choice'
        if not completed(choice / 'selection.json'):
            execute([sys.executable, SCRIPTS / 'repcut_memory_choose.py', '--audit', audit,
                     '--metrics', metrics / 'metrics.json', '--max-copy-growth', '0.05',
                     '--output', choice], folder / 'choice.log', self.env)
        self.progress('apply_structural_mem_to_reg', selection=read(choice / 'selection.json')['selected'])
        transformed = folder / 'mem_to_reg.json'
        execute([self.tools / 'partition', 'memory', raw, transformed, choice / 'selected.txt', '32'],
                folder / 'transform.log', self.env)
        save(marker, dict(status='pass', input=identity(raw), output=identity(transformed),
                          selection=identity(choice / 'selection.json')))
        return transformed

    def partition(self, raw: Path, dest: Path, assignment: Path | None = None) -> Path:
        marker = dest / 'partition.json'
        if completed(marker):
            record = read(marker)
            if (record['input'] != identity(raw) or record['output'] != identity(dest / 'partitioned.json')
                    or record['assignment'] != identity(dest / 'assignment.txt')):
                raise ValueError('partition provenance changed')
            return dest / 'partitioned.json'
        self.progress('partition' if assignment is None else 'replay_automatic_move', output=str(dest))
        dest.mkdir(exist_ok=True)
        command = [self.tools / 'partition', 'partition' if assignment is None else 'replay',
                   raw, dest, '32', str(self.jobs) if assignment is None else assignment]
        execute(command, dest / 'partition.log', self.env)
        assignments = list((dest / 'work').glob('*.closure-aware.part32'))
        if len(assignments) != 1:
            raise ValueError('expected one final 32-part assignment')
        labels = list(map(int, assignments[0].read_text().split()))
        if set(labels) != set(range(32)):
            raise ValueError('incomplete partition set')
        if assignment is not None and labels != list(map(int, assignment.read_text().split())):
            raise ValueError('replayed assignment changed')
        shutil.copy2(assignments[0], dest / 'assignment.txt')
        save(marker, dict(status='pass', input=identity(raw), output=identity(dest / 'partitioned.json'),
                          assignment=identity(dest / 'assignment.txt'), atom_count=len(labels),
                          origin='fresh solver' if assignment is None else identity(assignment),
                          reg_to_mem_profitability='verilator-v1', library=identity(self.library)))
        return dest / 'partitioned.json'

    def context(self, raw: Path):
        folder = self.out / 'context'
        marker = folder / 'identity.json'
        if completed(marker):
            if read(marker)['input'] != identity(raw):
                raise ValueError('source context belongs to another graph')
            return
        self.progress('source_context')
        folder.mkdir(exist_ok=True)
        execute([self.tools / 'context_probe', raw, folder, 'clock'], folder / 'probe.log', self.env)
        save(marker, dict(status='pass', input=identity(raw), library=identity(self.library),
                          options=self.options, outputs=[identity(folder / name) for name in
                          ('source_model.txtdata', 'contexts.txtdata', 'atom_backend_features.csv')]))

    def emit(self, dest: Path):
        marker = dest / 'emit.json'
        if completed(marker):
            record = read(marker)
            if (record['options'] != self.options or record['library'] != identity(self.library)
                    or record['input'] != identity(dest / 'partitioned.json')):
                raise ValueError('emitter configuration changed')
            return
        self.progress('emit_full_preset', output=str(dest))
        raw = dest / 'partitioned.json'
        env = dict(self.env, WOLVRIX_REPLAY_EMIT_ONLY='1')
        execute([self.tools / 'replay', raw, dest / 'assignment.txt', dest / 'emit_work',
                 dest / 'unused.json', dest / 'package'], dest / 'emit.log', env)
        save(marker, dict(status='pass', input=identity(raw), library=identity(self.library),
                          options=self.options, replay=identity(self.tools / 'replay')))

    def plan(self, dest: Path):
        if completed(dest / 'plan/identity.json'):
            return
        self.progress('execution_plan', output=str(dest))
        execute([sys.executable, SCRIPTS / 'repcut_grhsim_plan_gate.py', 'analyze',
                 '--emit-record', dest / 'emit.json', '--probe', self.tools / 'execution_plan',
                 '--clock', 'clock', '--output', dest / 'plan'], dest / 'plan.log', self.env)

    def build(self, dest: Path):
        from repcut_cycle_trace import align_object
        from repcut_formal_zero_thp_compare import audit_compute_alignment
        compatibility = compiler_compatibility(self.out / 'compiler_compatibility', LLVM / 'clang++')
        marker = dest / 'build.json'
        if completed(marker):
            record = read(marker)
            if record['binary'] != identity(dest / 'harness/grhsim-compile/emu'):
                raise ValueError('compiled binary changed')
            if record.get('compiler_flags') != compatibility:
                raise ValueError('build predates compiler compatibility validation; preserve it before rebuilding')
            return
        self.progress('compile', output=str(dest), jobs=self.jobs, cpus=self.cpus)
        started = time.monotonic()
        package, objects = dest / 'package', dest / 'objects'
        install_compiler_rules(package, self.out / 'compiler_compatibility/Makefile')
        objects.mkdir(exist_ok=True)
        names = re.search(r'^SRCS :=(.*)$', (package / 'Makefile').read_text(), re.M)[1].split()
        if len(set(names)) != len(names) or set(names) != {p.name for p in package.glob('*.cpp')}:
            raise ValueError('Makefile source inventory mismatch')

        def one(name):
            source, obj = package / name, objects / (name[:-4] + '.o')
            command = [LLVM / 'clang++', '-std=c++20', '-O3', '-march=native', *compatibility, '-pthread',
                       '-I', package, '-c', source, '-o', obj]
            key = dict(source=identity(source), command=list(map(str, command)))
            cache = obj.with_suffix('.json')
            if obj.exists() and cache.exists() and read(cache) == key:
                return obj
            execute(command, obj.with_suffix('.log'))
            align_object(obj)
            save(cache, key)
            return obj

        compiled = []
        with ThreadPoolExecutor(max_workers=self.jobs) as pool:
            for count, obj in enumerate(pool.map(one, names), 1):
                compiled.append(obj)
                if count % 500 == 0:
                    print('COMPILED', count, '/', len(names), flush=True)
        archive = package / 'libgrhsim_SimTop.a'
        # Preserve the generated Makefile order; replacing members in a sorted
        # archive would change layout and contaminate the comparison.
        response = dest / 'objects.rsp'
        response.write_text(''.join(f'"{obj}"\n' for obj in compiled))
        temporary = archive.with_suffix('.new.a')
        if temporary.exists():
            temporary.unlink()
        execute([LLVM / 'llvm-ar', 'rcs', temporary, '@' + str(response)], dest / 'archive.log')
        temporary.replace(archive)
        harness = dest / 'harness'
        command = ['make', f'-j{self.jobs}', '-C', ROOT / 'testcase/xiangshan/difftest', 'emu-grhsim',
                   f'CC={LLVM / "clang"}', f'CXX={LLVM / "clang++"}', f'BUILD_DIR={harness}',
                   f'GEN_CSRC_DIR={GENERATED}', f'GEN_VSRC_DIR={GENERATED}', 'NUM_CORES=1',
                   'WITH_CHISELDB=0', 'WITH_CONSTANTIN=0', 'EMU_THREADS=0', 'EMU_RANDOMIZE=0',
                   'GRHSIM=1', f'GRHSIM_MODEL_DIR={package}', f'GRHSIM_MODEL_LIB={archive}',
                   f'GRHSIM_MODEL_BUILD_JOBS={self.jobs}',
                   'GRHSIM_MODEL_CXXFLAGS=-std=c++20 -O3 -march=native ' + ' '.join(compatibility), 'EMU_OPTIMIZE=-O3',
                   'WOLVRIX_GRHSIM_WAVEFORM=0',
                   'GRHSIM_LDFLAGS=$(SIM_LDFLAGS) -ldl $(PGO_LDFLAGS) -pthread', '-o', archive]
        binary = harness / 'grhsim-compile/emu'
        # make -o deliberately skips model rebuilding; force relinking after
        # replacing the archive even when an older harness is already present.
        binary.unlink(missing_ok=True)
        execute(command, dest / 'harness.log')
        alignment = audit_compute_alignment(binary, 64)
        if not (dest / 'emu').exists():
            (dest / 'emu').symlink_to(binary)
        save(marker, dict(status='pass', binary=identity(binary), archive=identity(archive),
                          archive_order=names, objects=len(names), alignment=alignment,
                          compiler=identity(LLVM / 'clang++'), compile_jobs=self.jobs,
                          compiler_flags=compatibility,
                          compiler_compatibility=identity(self.out / 'compiler_compatibility/result.json'),
                          cpu_affinity=sorted(os.sched_getaffinity(0)),
                          elapsed_s=time.monotonic() - started,
                          harness_command=list(map(str, command))))

    def compare(self, baseline: Path, candidate: Path, output: Path):
        if completed(output / 'manifest.json') and completed(output / 'thp_verification.json'):
            return read(output / 'summary.json')
        self.progress('formal_ab_ba', baseline=str(baseline), candidate=str(candidate), output=str(output))
        execute([sys.executable, SCRIPTS / 'repcut_formal_zero_thp_compare.py',
                 '--baseline-binary', baseline / 'harness/grhsim-compile/emu',
                 '--candidate-binary', candidate / 'harness/grhsim-compile/emu',
                 '--baseline-package', baseline / 'package', '--candidate-package', candidate / 'package',
                 '--output', output, '--pairs', '8', '--cycles', '100000',
                 '--numa-policy', 'preferred', '--collapse-retry', RETRY,
                 '--require-compute-alignment', '64'], output.with_suffix('.log'))
        return read(output / 'summary.json')

    def trace(self, source: Path) -> list[Path]:
        folder = self.out / 'trace_initial'
        if not (folder / 'build.json').is_file():
            self.progress('build_cycle_trace')
            execute([sys.executable, SCRIPTS / 'repcut_cycle_trace.py', 'build',
                     '--baseline-source', source, '--candidate-source', source, '--output', folder],
                    folder.with_suffix('.build.log'))
        if not completed(folder / 'runs/manifest.json'):
            self.progress('diagnostic_cycle_trace')
            execute([sys.executable, SCRIPTS / 'repcut_cycle_trace.py', 'run',
                     '--baseline-source', source, '--candidate-source', source, '--output', folder,
                     '--cycles', '100000', '--pairs', '2', '--numa-policy', 'preferred',
                     '--retry-preload', RETRY], folder.with_suffix('.run.log'),
                    dict(self.env, WOLVI_GRHSIM_CODE_HUGEPAGE='0'))
        traces = sorted((folder / 'runs').glob('pair*.trace.bin'))
        if len(traces) != 4 or not completed(folder / 'runs/codepage_verification.json'):
            raise ValueError('incomplete cycle trace collection')
        if not completed(folder / 'profile.json'):
            command = [sys.executable, SCRIPTS / 'repcut_grhsim_critical_profile.py',
                       '--output', folder / 'profile.json']
            for path in traces:
                command += ['--trace', path]
            execute(command, folder / 'profile.log')
        return traces

    def search(self, raw: Path, initial: Path) -> Path:
        folder = self.out / 'automatic_migration'
        marker = folder / 'result.json'
        if completed(marker):
            return Path(read(marker)['retained'])
        folder.mkdir(exist_ok=True)
        traces = self.trace(initial)
        self.progress('automatic_migration_proposals')
        context = self.out / 'context'
        proposals = folder / 'proposals'
        if not (proposals / 'selection.json').is_file():
            execute([sys.executable, SCRIPTS / 'repcut_grhsim_piece_candidates.py',
                     '--model', context / 'source_model.txtdata',
                     '--features', context / 'atom_backend_features.csv',
                     '--assignment', initial / 'assignment.txt',
                     '--critical-profile', self.out / 'trace_initial/profile.json',
                     '--source-count', '3', '--top', '8', '--targets', '3',
                     '--output', proposals], folder / 'proposals.log')
        proposed = read(proposals / 'selection.json')
        if not proposed['candidates']:
            save(marker, dict(status='pass', retained=str(initial), reason='no automatic proposals'))
            return initial
        evaluation = folder / 'evaluation'
        if not completed(evaluation / 'report.json'):
            execute([sys.executable, SCRIPTS / 'repcut_grhsim_piece_splits.py', 'evaluate',
                     '--model', context / 'source_model.txtdata', '--baseline', initial / 'assignment.txt',
                     '--selection', proposals / 'selection.json', '--evaluator', self.tools / 'assignment_eval',
                     '--output', evaluation], folder / 'evaluation.log', self.env)
        budget = folder / 'budget.json'
        save(budget, dict(rules=[dict(feature=feature, scope=scope, max_change_percent=0)
                                for feature in ('send_calls', 'send_bytes', 'receive_calls', 'receive_bytes')
                                for scope in ('peak', 'sum')]))
        rank_path = folder / 'ranking.json'
        if not completed(rank_path):
            command = [sys.executable, SCRIPTS / 'repcut_grhsim_local_search_rank.py',
                       '--report', evaluation / 'report.json',
                       '--parts', self.out / 'reference_vs_initial/parts.csv',
                       '--profile-variant', 'candidate', '--activity-model', 'source-envelope',
                       '--budget', budget, '--output', rank_path]
            for path in traces:
                command += ['--critical-trace', path]
            execute(command, folder / 'ranking.log')
        selected = select_migration(read(rank_path))
        save(folder / 'selected.json', dict(status='pass', selected=selected,
             selection_rule='minimum predicted step maximum among the improving Pareto frontier; then impact scope and local communication increments',
             manual_source_or_destination=False))
        if selected is None:
            save(marker, dict(status='pass', retained=str(initial), reason='no improving candidate within structural budget'))
            return initial
        assignment = proposals / (selected['name'] + '.assignment')
        candidate = self.out / 'automatic_candidate'
        self.partition(raw, candidate, assignment)
        self.emit(candidate)
        with ThreadPoolExecutor(max_workers=1) as pool:
            plan = pool.submit(self.plan, candidate)
            try:
                self.build(candidate)
            finally:
                plan.result()
        if not (candidate / 'plan_comparison.json').is_file():
            execute([sys.executable, SCRIPTS / 'repcut_grhsim_plan_gate.py', 'compare',
                     '--baseline', initial / 'plan', '--candidate', candidate / 'plan',
                     '--phase-risk', '--output', candidate / 'plan_comparison.json'],
                    candidate / 'plan_comparison.log')
        # Phase-risk is an explanatory ledger; it has not been calibrated as
        # a safe rejection rule. Functional and ordinary timing gates decide.
        first = self.compare(initial, candidate, candidate / 'ab_ba_r1')
        accepted = performance_pass(first)
        if accepted:
            second = self.compare(initial, candidate, candidate / 'ab_ba_r2')
            accepted = performance_pass(second)
        retained = candidate if accepted else initial
        save(marker, dict(status='pass', retained=str(retained), accepted=accepted,
                          selected=selected, rounds=2 if (candidate / 'ab_ba_r2/summary.json').exists() else 1,
                          acceptance=self.config['acceptance']))
        return retained

    def run(self):
        self.prepare()
        raw = self.memory(self.ingest())
        initial = self.out / 'initial'
        self.partition(raw, initial)
        # Independent source-context analysis may overlap generation, but it
        # must be finished before any timing samples are collected.
        with ThreadPoolExecutor(max_workers=2) as pool:
            context = pool.submit(self.context, raw)
            try:
                self.emit(initial)
                plan = pool.submit(self.plan, initial)
                # The plan reads only the immutable partitioned GRH; building
                # the emitted C++ is independent. Both finish before timing.
                self.build(initial)
                plan.result()
            finally:
                # Do not discard a background analysis failure if emission or
                # plan validation also failed.
                context.result()
        self.compare(self.reference, initial, self.out / 'reference_vs_initial')
        self.progress('initial_complete', output=str(initial))
        retained = self.search(raw, initial)
        final = (self.compare(self.reference, retained, self.out / 'reference_vs_retained')
                 if retained != initial else read(self.out / 'reference_vs_initial/summary.json'))
        save(self.out / 'result.json', dict(status='pass', retained=str(retained),
              binary=identity(retained / 'harness/grhsim-compile/emu'),
              memory_selection=read(self.out / 'memory/choice/selection.json'),
              migration=read(self.out / 'automatic_migration/result.json'),
              reference_comparison=final['metrics'], policy=identity(self.out / 'automatic_policy.json'),
              origin=('verified Verilog ingestion; historical memory stage fixed; migration automatic'
                      if self.args.memory_reference_run is not None else
                      'fresh Verilog ingestion; all selection choices made by tools'),
              historical_reference_remains_available=True))
        self.progress('complete', retained=str(retained), walltime=final['metrics']['elapsed_s'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--filelist', type=Path, required=True)
    parser.add_argument('--read-args', type=Path, required=True)
    parser.add_argument('--top', default='SimTop')
    parser.add_argument('--preset', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--memory-reference-run', type=Path,
                        help='controlled experiment: use targets from a successful historical mem-to-reg run')
    parser.add_argument('--ingest-record', type=Path,
                        help='reuse an ingestion after revalidating every RTL/header and raw graph identity')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    flow = Flow(args)
    try:
        flow.run()
    except Exception as error:
        flow.progress('failed', error=f'{type(error).__name__}: {error}')
        raise


if __name__ == '__main__':
    main()
