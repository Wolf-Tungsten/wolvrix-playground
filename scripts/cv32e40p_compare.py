#!/usr/bin/env python3
"""Frozen CV32E40P/CoreMark comparison; all ratios are GrhSIM / Verilator."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

from grhsim_numa import inspect_locality, locality_errors, runtime_plan
from grhsim_single_baseline import clean_environment, cpu_counters, idle_percent, identity, save

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'testcase/cv32e40p-bench'
CV_SHA = 'b353438ff469c030c89f6804f3b24a2852880e8b'
SW_SHA = 'fc3a7a3ea9d793ffe5cf0772f87d939b4bcde50c'
WOLVRIX_SHA = '74d80cf'
CXX = Path('/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++')
GCC = Path('/nfs/home/tanghaojin/riscv-baremetal-2/bin/riscv64-unknown-elf-gcc')
CFLAGS = ['-std=c++20', '-O3', '-march=native', '-DNDEBUG', '-gline-tables-only']
PREFIX = ['taskset', '-c', '96', 'numactl', '--membind=1', 'setarch', 'x86_64', '-R']
BACKENDS = ('verilator', 'grhsim')


def environment():
    return {k: v for k, v in clean_environment().items() if not k.startswith(('GRHSIM_', 'VERILATOR_'))}


def run(cmd, log, *, cwd=ROOT, env=None):
    cmd = list(map(str, cmd)); log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    save(log.with_suffix('.command.json'), dict(argv=cmd, cwd=str(cwd)))
    start = time.monotonic()
    with log.open('w') as stream:
        result = subprocess.run(cmd, cwd=cwd, env=env or environment(), stdout=stream, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - start
    save(log.with_suffix('.result.json'), dict(returncode=result.returncode, wall_s=elapsed))
    if result.returncode:
        raise RuntimeError(f'{log}: command failed ({result.returncode})\n{log.read_text(errors="replace")[-4000:]}')
    return elapsed


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        with urllib.request.urlopen(url, timeout=60) as response: dest.write_bytes(response.read())


def prepare_tools(tools):
    """Fetch small portable helpers on the network host before remote builds."""
    sv2v = tools / 'sv2v'
    if not sv2v.exists():
        archive = tools / 'sv2v-Linux-v0.0.13.zip'
        download('https://github.com/zachjs/sv2v/releases/download/v0.0.13/sv2v-Linux.zip', archive)
        with zipfile.ZipFile(archive) as z:
            name = next(n for n in z.namelist() if n.endswith('/sv2v') or n == 'sv2v')
            sv2v.write_bytes(z.read(name)); sv2v.chmod(0o755)
    yosys = tools / 'yosys-package/usr/bin/yosys'
    if not yosys.exists():
        archive = tools / 'yosys-package/yosys.deb'
        download('https://archive.ubuntu.com/ubuntu/pool/universe/y/yosys/yosys_0.33-5build2_amd64.deb', archive)
        if identity(archive)['sha256'] != '94247f2157ec6ce63c6638326e419975d911ace5356b3dc276d1d8b36659efbd':
            raise ValueError('Yosys package hash mismatch')
        run(['dpkg-deb', '-x', archive, archive.parent], tools / 'yosys-unpack.log')


def prepare(out):
    source = out / 'inputs/cv32e40p'
    if not source.exists():
        archive = out / 'inputs/cv32e40p.tar.gz'
        download(f'https://codeload.github.com/openhwfoundation/cv32e40p/tar.gz/{CV_SHA}', archive)
        with tarfile.open(archive) as tar:
            tar.extractall(out / 'inputs', filter='data')
        (out / f'inputs/cv32e40p-{CV_SHA}').rename(source)
    software = out / 'inputs/coremark'; software.mkdir(parents=True, exist_ok=True)
    for name in ('core_list_join.c', 'core_main.c', 'core_matrix.c', 'core_state.c', 'core_util.c',
                 'core_portme.c', 'core_portme.h', 'coremark.h', 'LICENSE.md', 'test.yaml'):
        download(f'https://raw.githubusercontent.com/openhwgroup/core-v-verif/{SW_SHA}/cv32e40p/tests/programs/custom/coremark/{name}', software / name)
    fixture = out / 'inputs/fixture'
    if fixture.exists():
        for path in FIXTURE.iterdir():
            if path.is_file() and identity(path)['sha256'] != identity(fixture / path.name)['sha256']:
                raise ValueError('fixture changed; use a new output directory')
    else:
        shutil.copytree(FIXTURE, fixture)
    inputs = [identity(p) for p in sorted((out / 'inputs').rglob('*')) if p.is_file()]
    save(out / 'inputs.json', dict(cv32e40p=CV_SHA, core_v_verif=SW_SHA, files=inputs))
    common = ['-O3', '-march=rv32im', '-mabi=ilp32', '-ffreestanding', '-fno-builtin',
              '-fno-stack-protector', '-nostdlib', '-static', '-falign-functions=16',
              '-funroll-all-loops', '-falign-jumps=4', '-finline-functions',
              '-DPERFORMANCE_RUN=1', '-DITERATIONS=10', '-DMEM_METHOD=MEM_STATIC',
              '-DHAS_FLOAT=0', '-DTOTAL_DATA_SIZE=2000', '-DFLAGS_STR="RV32IM O3 frozen CV32 bench"',
              '-I', software, '-T', fixture / 'link.ld', fixture / 'start.S', fixture / 'runtime.c']
    for name in ('smoke', 'coremark'):
        dest = out / 'firmware' / name; dest.mkdir(parents=True, exist_ok=True)
        files = [fixture / 'smoke.c'] if name == 'smoke' else sorted(software.glob('*.c'))
        run([GCC, *common, *files, '-o', dest / 'program.elf'], out / f'logs/firmware-{name}.log')
        run([str(GCC).replace('gcc', 'objcopy'), '-O', 'binary', dest / 'program.elf', dest / 'program.bin'],
            out / f'logs/objcopy-{name}.log')
        data = bytes(0x180) + (dest / 'program.bin').read_bytes()
        if len(data) > 4 * 1024 * 1024: raise ValueError('firmware exceeds RAM')
        # Shared host loader writes the image through RTL ports while reset is held.
        # RAM has the same explicit zero initializer in both backends.
        image = dest / 'workload.bin'
        image.write_bytes(data + bytes((-len(data)) % 4))
        save(dest / 'identity.json', dict(elf=identity(dest / 'program.elf'), image=identity(image)))


def rtl_files(out):
    source = out / 'inputs/cv32e40p'
    paths = []
    for line in (source / 'cv32e40p_manifest.flist').read_text().splitlines():
        line = line.strip()
        if not line.startswith('${DESIGN_RTL_DIR}'): continue
        path = Path(line.replace('${DESIGN_RTL_DIR}', str(source / 'rtl'))).resolve()
        if path.name in ('cv32e40p_tb_wrapper.sv', 'cv32e40p_tracer_pkg.sv'): continue
        paths.append(path)
    return [*paths, out / 'inputs/fixture/Cv32Bench.sv']


def build(out, tools, jobs, diagnostic=False):
    if not platform.node().startswith('node030'): raise ValueError('build on node030 for -march=native')
    sha = subprocess.check_output(['git', '-C', ROOT / 'wolvrix', 'rev-parse', 'HEAD'], text=True).strip()
    if not sha.startswith(WOLVRIX_SHA): raise ValueError('unexpected Wolvrix revision')
    files = rtl_files(out); source = out / 'inputs/cv32e40p'
    includes = ['-I' + str(source / 'rtl/include'), '-I' + str(source / 'bhv'), '-I' + str(source / 'bhv/include')]
    fixture = out / 'inputs/fixture'
    if not (tools / 'cv32e40p_emit').is_file():
        run(['cmake', '-S', FIXTURE, '-B', tools, '-DCMAKE_BUILD_TYPE=Release'], out / 'logs/tools-configure.log')
        run(['cmake', '--build', tools, '--target', 'grhsim32_frontend', 'cv32e40p_emit', '-j', jobs], out / 'logs/tools-build.log')
    graph = out / 'graph.json'
    prepare_tools(tools)
    sv2v = tools / 'sv2v'
    normalized = out / 'Cv32Bench.v'
    if not normalized.exists():
        raw = out / 'sv2v-core.v'
        run([sv2v, '+RTS', '-N4', '-RTS', '--top=cv32e40p_top', '--write=' + str(raw),
             *includes, *files[:-1]], out / 'logs/sv2v.log')
        yosys = tools / 'yosys-package/usr/bin/yosys'
        lowered = out / 'proc-core.v'
        script = out / 'normalize.ys'
        script.write_text(f'read_verilog {raw}\nchparam -set COREV_PULP 0 -set COREV_CLUSTER 0 -set FPU 0 -set ZFINX 0 -set NUM_MHPMCOUNTERS 1 cv32e40p_top\nhierarchy -top cv32e40p_top\nproc\npmuxtree\nflatten\nopt -full\nsplitnets\nopt_clean\nwrite_verilog -noattr {lowered}\n')
        run([yosys, '-s', script], out / 'logs/yosys.log')
        # Yosys has already specialized the top; its emitted module has no parameters.
        wrapper, count = re.subn(r'cv32e40p_top\s*#\(.*?\) core', 'cv32e40p_top core', files[-1].read_text(), flags=re.S)
        if count != 1: raise ValueError('unexpected core wrapper')
        normalized.write_text(lowered.read_text() + '\n' + wrapper)
        save(out / 'normalization.json', dict(raw=identity(raw), proc_rtl=identity(lowered),
             script=identity(script), yosys=identity(yosys), sv2v=identity(sv2v), output=identity(normalized)))
    if not graph.exists():
        run([tools / 'bin/grhsim32_frontend', graph, 'Cv32Bench', normalized], out / 'logs/frontend.log')
    variant = 'diagnostic' if diagnostic else 'grhsim'
    model = out / variant
    run([tools / 'cv32e40p_emit', graph, model, 'eval' if diagnostic else 'off'], out / f'logs/{variant}-emit.log')
    run(['make', '-C', model, '-j', jobs, 'CXX=' + str(CXX), 'CXXFLAGS=' + ' '.join(CFLAGS)], out / f'logs/{variant}-compile.log')
    run([CXX, *CFLAGS, '-DCV32_GRHSIM', '-I', model, fixture / 'harness.cpp', model / 'libgrhsim_Cv32Bench.a',
         '-o', out / variant / 'emu'], out / f'logs/{variant}-link.log')
    if diagnostic: return
    for name, sources in [('verilator', [normalized]), ('verilator-original', [*includes, *files])]:
        run(['verilator', '--cc', '--exe', '--build', '-j', jobs, '--threads', '1', '-O3',
             '--top-module', 'Cv32Bench', '--Mdir', out / name, '-Wno-fatal', *sources,
             fixture / 'harness.cpp', '-CFLAGS', ' '.join(CFLAGS), '-o', 'emu',
             '-MAKEFLAGS', 'CXX=' + str(CXX), '-MAKEFLAGS', 'LINK=' + str(CXX),
             '-MAKEFLAGS', 'OPT_FAST=-O3', '-MAKEFLAGS', 'OPT_SLOW=-O3'], out / f'logs/{name}-build.log')
    manifest = dict(wolvrix=sha, cv32e40p=CV_SHA, core_v_verif=SW_SHA, flags=CFLAGS,
                    cxx=identity(CXX), gcc=identity(GCC), driver=identity(__file__),
                    verilator_version=subprocess.check_output(['verilator', '--version'], text=True).strip(),
                    tools=[identity(tools / 'cv32e40p_emit'), identity(tools / 'bin/grhsim32_frontend'),
                           identity(tools / 'grhsim32/wolvrix/libwolvrix-lib.so')],
                    rtl=[identity(p) for p in files], normalization=dict(tool=identity(sv2v), rtl=identity(normalized)),
                    frontend_source=identity(ROOT / 'tools/grhsim32/frontend.cpp'),
                    binaries={b: identity(out / b / 'emu') for b in (*BACKENDS, 'verilator-original')})
    save(out / 'build.json', manifest)
    copies = out / 'native-frozen'; copies.mkdir(exist_ok=True)
    records = []
    for entry in manifest['tools']:
        target = copies / Path(entry['path']).name
        shutil.copy2(entry['path'], target)
        records.append(dict(original=entry, copy=str(target)))
    save(out / 'native-input-copies.json', records)


def check_build_identity(out):
    manifest = json.loads((out / 'build.json').read_text())
    for entry in [*manifest['binaries'].values(), *manifest['rtl'],
                  manifest['normalization']['rtl'], manifest['cxx'], manifest['gcc']]:
        if identity(entry['path']) != entry: raise ValueError('frozen build input changed: ' + entry['path'])
    copies = {r['original']['path']: r for r in json.loads((out / 'native-input-copies.json').read_text())}
    for entry in manifest['tools']:
        frozen = copies[entry['path']]
        if frozen['original'] != entry: raise ValueError('tool identity changed')
        actual = identity(frozen['copy'])
        if any(actual[k] != entry[k] for k in ('sha256', 'bytes')): raise ValueError('frozen tool changed')
    for workload in ('smoke', 'coremark'):
        firmware = json.loads((out / 'firmware' / workload / 'identity.json').read_text())
        for entry in firmware.values():
            if identity(entry['path']) != entry: raise ValueError('firmware changed: ' + entry['path'])


def parse_result(text):
    matches = re.findall(r'^CV32_RESULT (.+)$', text, re.M)
    if len(matches) != 1: raise ValueError('missing or duplicate result')
    record = json.loads(matches[0]); record['uart'] = bytes.fromhex(record['uart_hex']).decode('ascii')
    if record['exit_code'] or record['cycles'] <= 0 or record['sim_s'] <= 0: raise ValueError('invalid execution')
    return record


def validate_workload(row, workload):
    if row['exit_code'] != 0: raise ValueError('nonzero guest exit')
    text = row['uart']
    if workload == 'smoke':
        if text != 'SMOKE PASS\n': raise ValueError('smoke mismatch')
    else:
        expected = {'seedcrc': 'e9f5', 'crclist': 'e714', 'crcmatrix': '1fd7', 'crcstate': '8e3a'}
        for key, value in expected.items():
            if not re.search(rf'{key}\s*:\s*0x{value}\b', text, re.I): raise ValueError(f'bad {key}: {text}')
        if not re.search(r'Iterations\s*:\s*10\b', text): raise ValueError('wrong iterations')
        if 'Correct operation validated' not in text or 'ERROR' in text or 'Errors detected' in text:
            raise ValueError('CoreMark validation failed: ' + text)


def signature(row):
    return {key: row[key] for key in ('cycles', 'exit_code', 'uart')}


def sample(out, backend, workload, label, repeats=1, trace=False, perf=None, diag_env=None):
    if not platform.node().startswith('node030'): raise ValueError('measurements require node030')
    dest = out / 'runs' / label / backend
    dest.mkdir(parents=True, exist_ok=False)
    env = environment()
    plan = runtime_plan(out / backend / 'emu', None, out / 'firmware' / workload / 'workload.bin',
                        dest / 'runtime', 96, 1, env)
    save(dest / 'runtime-plan.json', plan)
    run([*PREFIX, sys.executable, ROOT / 'scripts/grhsim_numa.py', dest / 'runtime-plan.json'], dest / 'prepare.log', env=env)
    runtime = dest / 'runtime'
    env['LD_LIBRARY_PATH'] = str(runtime / 'lib')
    if diag_env: env.update(diag_env)
    command = [*PREFIX, runtime / 'bin/emu', '--repeats', repeats, '--audit', dest / 'audit']
    if trace: command += ['--trace', dest / 'bus.bin']
    if perf: command = ['perf', *perf, '--', *command]
    before = cpu_counters({96, 288})
    wall = run(command, dest / 'run.log', cwd=runtime, env=env)
    after = cpu_counters({96, 288})
    row = parse_result((dest / 'run.log').read_text())
    row.update(wall_s=wall, cpu_idle_percent=idle_percent(before, after), backend=backend,
               binary=identity(out / backend / 'emu'), image=identity(out / 'firmware' / workload / 'workload.bin'))
    errors = []
    audits = {}
    for stage in ('start', 'end'):
        prefix = dest / f'audit.{stage}'
        placement = json.loads(Path(str(prefix) + '.placement.json').read_text())
        if placement != dict(threads=1, cpu=96, affinity_count=1, aslr_disabled=True): errors.append(placement)
        local = inspect_locality(Path(str(prefix) + '.maps').read_text(), Path(str(prefix) + '.numa_maps').read_text(), plan)
        errors.extend(locality_errors(local, 1)); audits[stage] = dict(placement=placement, locality=local)
    row['audit'] = audits; row['placement_errors'] = errors
    if trace: row['trace'] = identity(dest / 'bus.bin')
    save(dest / 'result.json', row)
    validate_workload(row, workload)
    verification = out / 'verification.json'
    if verification.exists():
        expected = json.loads(verification.read_text())['workloads'][workload]['verilator']
        if signature(row) != signature(expected): raise ValueError('sample signature differs from verification')
    if errors:
        save(dest / 'rejected.json', dict(reason='placement', errors=errors))
        raise ValueError('placement rejected: ' + str(dest))
    return row


def verify(out):
    check_build_identity(out)
    checks = {}
    for workload in ('smoke', 'coremark'):
        rows = {b: sample(out, b, workload, 'verify-' + workload, trace=True) for b in (*BACKENDS, 'verilator-original')}
        for row in rows.values():
            if row['trace']['bytes'] != row['cycles'] * 36: raise ValueError('incomplete bus trace')
        if signature(rows['grhsim']) != signature(rows['verilator']): raise ValueError('functional signature mismatch')
        if rows['grhsim']['trace']['sha256'] != rows['verilator']['trace']['sha256']:
            raise ValueError('bus trace mismatch; inspect first differing 36-byte cycle record')
        if signature(rows['verilator-original']) != signature(rows['verilator']) or \
                rows['verilator-original']['trace']['sha256'] != rows['verilator']['trace']['sha256']:
            raise ValueError('normalization changed execution')
        checks[workload] = rows
    save(out / 'verification.json', dict(status='pass', workloads=checks, build=identity(out / 'build.json')))


def summarize_named(rows, numerator, denominator):
    summary = dict(pairs=len(rows), ratio_definition=f'{numerator} / {denominator}; greater than one means {numerator} slower')
    for metric in ('wall_s', 'sim_s', 'init_s'):
        ratios = [r[numerator][metric] / r[denominator][metric] for r in rows]
        rng = random.Random(20261114)
        boot = sorted(statistics.mean(rng.choices(ratios, k=len(ratios))) for _ in range(10000))
        summary[metric] = dict(ratio_mean=statistics.mean(ratios), ratio_median=statistics.median(ratios),
                              ratio_ci95=[boot[249], boot[9749]], ratios=ratios,
                              **{b + '_mean': statistics.mean(r[b][metric] for r in rows) for b in (denominator, numerator)})
    return summary


def summarize(rows):
    summary = summarize_named(rows, 'grhsim', 'verilator')
    summary['diagnosis_required'] = summary['wall_s']['ratio_ci95'][0] > 1.20
    return summary


def measure(out):
    check_build_identity(out)
    verified = json.loads((out / 'verification.json').read_text())
    if verified['status'] != 'pass' or verified['build'] != identity(out / 'build.json'):
        raise ValueError('verification does not match build')
    warmups = {b: sample(out, b, 'coremark', 'warmup') for b in BACKENDS}
    repetitions = max(1, math.ceil(1.0 / (warmups['verilator']['sim_s'] + warmups['verilator']['init_s'])))
    save(out / 'measurement-policy.json', dict(pairs=8, repetitions=repetitions, warmups=warmups,
         cpu=96, numa=1, aslr=False, bootstrap_seed=20261114, max_pair_attempts=2))
    rows = []
    for i in range(8):
        order = BACKENDS if i % 2 == 0 else BACKENDS[::-1]
        for attempt in range(2):
            row = dict(pair=i, attempt=attempt, order=order)
            try:
                for b in order:
                    row[b] = sample(out, b, 'coremark', f'pair{i:02d}-attempt{attempt}', repetitions)
                    if signature(row[b]) != signature(verified['workloads']['coremark'][b]):
                        raise ValueError('measured workload signature changed')
                break
            except ValueError as error:
                if 'placement rejected:' not in str(error) or attempt: raise
        rows.append(row); save(out / 'pairs.json', rows)
        print(f'pair {i+1}/8: GrhSIM/Verilator wall={row["grhsim"]["wall_s"]/row["verilator"]["wall_s"]:.3f}', flush=True)
    save(out / 'summary.json', summarize(rows))
    with (out / 'pairs.csv').open('w') as stream:
        writer = csv.writer(stream); writer.writerow(['pair', 'order', 'verilator_wall_s', 'grhsim_wall_s', 'verilator_sim_s', 'grhsim_sim_s'])
        for r in rows: writer.writerow([r['pair'], '>'.join(r['order']), *[r[b][m] for m in ('wall_s', 'sim_s') for b in BACKENDS]])


def profile(out, tools, jobs):
    check_build_identity(out)
    if not json.loads((out / 'summary.json').read_text())['diagnosis_required']: return
    for b in BACKENDS:
        stat = out / f'{b}-perf-stat.csv'
        sample(out, b, 'coremark', 'perf-stat', perf=['stat', '-x,', '-o', stat,
               '-e', 'cycles:u,instructions:u,branches:u,branch-misses:u'])
        data = out / f'{b}-perf.data'
        sample(out, b, 'coremark', 'perf-record', perf=['record', '-o', data, '-e', 'cycles:u', '-F', '199', '--call-graph', 'dwarf,8192'])
        run(['perf', 'report', '--stdio', '--no-children', '-i', data], out / f'{b}-perf-report.txt')
    build(out, tools, jobs, diagnostic=True)
    sample(out, 'diagnostic', 'coremark', 'diagnostic', diag_env={'GRHSIM_TRACE_EVAL_EVERY': '10000'})
    run(['cmake', '--build', tools, '--target', 'cv32e40p_map', '-j', jobs], out / 'logs/map-build.log')
    run([tools / 'cv32e40p_map', out / 'graph.json', out / 'sources.csv'], out / 'logs/map.log')
    save(out / 'mapping-identity.json', dict(tool=identity(tools / 'cv32e40p_map'), graph=identity(out / 'graph.json'),
         source=identity(FIXTURE / 'map.cpp'), output=identity(out / 'sources.csv')))


def normalization_control(out):
    """One diagnostic experiment; not another candidate selection or paired CI."""
    check_build_identity(out)
    if not json.loads((out / 'summary.json').read_text())['diagnosis_required']: return
    policy = dict(hypothesis='Common RTL normalization increases Verilator runtime relative to original SV',
                  expected='Original RTL is faster; functional signature stays identical',
                  order=['verilator-original', 'verilator', 'verilator-original'],
                  fixed_workload='CoreMark 10 iterations', scope='Diagnostic ABA only, no confidence interval')
    path = out / 'normalization-control-policy.json'
    if path.exists(): raise ValueError('control already started; retain the prior evidence')
    save(path, policy)
    expected = json.loads((out / 'verification.json').read_text())['workloads']['coremark']['verilator']
    rows = []
    for i, backend in enumerate(policy['order']):
        row = sample(out, backend, 'coremark', f'normalization-control-{i}')
        if signature(row) != signature(expected): raise ValueError('control signature changed')
        rows.append(row)
    save(out / 'normalization-control.json', dict(policy=policy, samples=rows,
         normalized_over_original_wall=rows[1]['wall_s'] / statistics.mean([rows[0]['wall_s'], rows[2]['wall_s']]),
         normalized_over_original_sim=rows[1]['sim_s'] / statistics.mean([rows[0]['sim_s'], rows[2]['sim_s']])))


def report(out):
    check_build_identity(out)
    data = json.loads((out / 'summary.json').read_text())
    data['build'] = json.loads((out / 'build.json').read_text())
    data['generated'] = {b: dict(cpp_bytes=sum(p.stat().st_size for p in (out / b).glob('*.cpp')),
                                binary=identity(out / b / 'emu')) for b in (*BACKENDS, 'verilator-original')}
    verify = json.loads((out / 'verification.json').read_text())
    cycles = verify['workloads']['coremark']['grhsim']['cycles']
    data['functional'] = dict(status=verify['status'], coremark=signature(verify['workloads']['coremark']['grhsim']),
        trace_sha256=verify['workloads']['coremark']['grhsim']['trace']['sha256'])
    data['cycles_per_second'] = {b: cycles / data['sim_s'][b + '_mean'] for b in BACKENDS}
    data['build_wall_s'] = {p.stem.removesuffix('.result'): json.loads(p.read_text())['wall_s']
                            for p in (out / 'logs').glob('*.result.json')}
    if (out / 'normalization-control.json').exists():
        control = json.loads((out / 'normalization-control.json').read_text())
        original = [control['samples'][i] for i in (0, 2)]
        control['grhsim_over_original_wall_indicative'] = data['wall_s']['grhsim_mean'] / statistics.mean(r['wall_s'] for r in original)
        control['grhsim_over_original_sim_indicative'] = data['sim_s']['grhsim_mean'] / statistics.mean(r['sim_s'] for r in original)
        data['normalization_control'] = control
    diagnostics = {}
    for b in BACKENDS:
        path = out / f'{b}-perf-stat.csv'
        if path.exists():
            counters = {}
            for fields in csv.reader(path.open()):
                if len(fields) >= 5 and fields[2].endswith(':u'):
                    counters[fields[2]] = dict(count=float(fields[0]), running_percent=float(fields[4]),
                                              per_guest_cycle=float(fields[0]) / cycles)
            diagnostics[b] = dict(counters=counters)
        path = out / f'{b}-perf-report.txt'
        if path.exists():
            matches = re.findall(r'^\s*([\d.]+)%\s+\S+\s+\S+\s+\[.\] (.+)$', path.read_text(), re.M)
            diagnostics[b]['hotspots'] = [dict(percent=float(p), symbol=s) for p, s in matches]
    path = out / 'runs/diagnostic/diagnostic/run.log'
    if path.exists():
        counters = json.loads(re.search(r'^CV32_PERF (.+)$', path.read_text(), re.M)[1])
        diagnostics['grhsim_eval'] = dict(counts=counters,
            per_guest_cycle={k: v / cycles for k, v in counters.items()},
            caveat='Counters include image loading and reset; not performance samples.')
    if (out / 'sources.csv').exists():
        rows = list(csv.DictReader((out / 'sources.csv').open()))
        graph = json.loads((out / 'grhsim/normalized.json').read_text())['graphs'][0]
        ops = {op['sym']: op for op in graph['ops']}; vals = {v['sym']: v for v in graph['vals']}
        sources = {r['op_symbol']: r for r in rows}
        wide_reads = []
        for op in graph['ops']:
            if op['kind'] != 'kConcat' or len(op['out']) != 1: continue
            val = vals[op['out'][0]]
            if val['w'] < 1024: continue
            users = [ops[u['op']] for u in val['users']]
            if not users or any(u['kind'] != 'kSliceDynamic' for u in users): continue
            wide_reads.append(dict(width=val['w'], operands=len(op['in']), symbol=op['sym'], value=val['sym'],
                source=sources.get(op['sym']), users=users,
                named_input_examples=[v for v in op['in'] if 'register_file' in v][:4]))
        diagnostics['wide_concat_dynamic_reads'] = wide_reads
        diagnostics['batch_shapes'] = {str(b): dict(ops=sum(r['batch'] == str(b) for r in rows),
            kinds=dict(Counter(r['op_kind'] for r in rows if r['batch'] == str(b)))) for b in range(24)}
        diagnostics['mapping'] = identity(out / 'sources.csv')
    data['diagnostics'] = diagnostics
    save(out / 'report.json', data)
    print(json.dumps({k: data[k] for k in ('pairs', 'ratio_definition', 'wall_s', 'sim_s', 'diagnosis_required')}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'build', 'verify', 'measure', 'profile', 'control', 'report', 'all'])
    parser.add_argument('--output', type=Path, default=ROOT / 'build/cv32e40p/run2')
    parser.add_argument('--tools', type=Path, default=ROOT / 'build/cv32e40p/tools')
    parser.add_argument('--jobs', type=int, default=16)
    args = parser.parse_args(); out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    stages = dict(prepare=lambda: (prepare_tools(args.tools.resolve()), prepare(out)), build=lambda: build(out, args.tools.resolve(), args.jobs),
                  verify=lambda: verify(out), measure=lambda: measure(out),
                  profile=lambda: profile(out, args.tools.resolve(), args.jobs),
                  control=lambda: normalization_control(out), report=lambda: report(out))
    for stage in (stages if args.stage == 'all' else [args.stage]):
        print(f'STAGE {stage}', flush=True); stages[stage]()


if __name__ == '__main__':
    main()
