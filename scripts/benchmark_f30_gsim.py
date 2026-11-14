"""Capture a GSIM reference from raw FIRRTL through SplitArray, without trace."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import subprocess
import time

from benchmark_f29_pass_trace import sha256, write_json_atomic
from snapshot_f30_package import snapshot_source

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'wolvrix.f30.gsim-benchmark.v1'
TIMER_LABELS = {
    '{strbuf = readFile(InputFileName, size, mapSize)}': 'readFile',
    '{globalRoot= parseFIR(strbuf)}': 'parseFIR',
    'Init': 'Init', '{g->splitArray()}': 'splitArray'}
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def parse_timers(content):
    timers = {}
    for line in ANSI.sub('', content).splitlines():
        match = re.fullmatch(r'(.+?) = ([0-9]+) ms', line.strip())
        if match is None or match[1] not in TIMER_LABELS:
            continue
        name = TIMER_LABELS[match[1]]
        if name in timers:
            raise ValueError('duplicate GSIM timer: ' + name)
        timers[name] = int(match[2]) / 1000.0
    if set(timers) != set(TIMER_LABELS.values()):
        raise ValueError('missing GSIM timers: ' + ','.join(sorted(set(TIMER_LABELS.values()) - timers.keys())))
    return timers


def freeze_native(binary, source_root, output):
    binary, source_root = Path(binary).resolve(), Path(source_root).resolve()
    frozen = output / 'native'
    frozen.mkdir()
    original_hash = sha256(binary)
    copied = frozen / 'gsim'
    shutil.copy2(binary, copied)
    if sha256(copied) != original_hash:
        raise ValueError('GSIM binary changed while freezing')
    revision, source = snapshot_source(source_root, frozen / 'source.tar.gz')
    patch = frozen / 'source.patch'
    patch.write_bytes(subprocess.check_output(['git', '-C', str(source_root), 'diff', '--binary', 'HEAD']))
    libraries = []
    linked = subprocess.run(['ldd', str(copied)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (frozen / 'ldd.log').write_text(linked.stdout, encoding='utf-8')
    for line in linked.stdout.splitlines():
        match = re.search(r'(?:=>\s+)?(/[^\s]+)\s+\(', line)
        if match:
            path = Path(match[1]).resolve()
            if path.is_file():
                libraries.append({'path': str(path), 'sha256': sha256(path)})
    config = []
    for name in ('Makefile', 'mk/toolchain.mk'):
        path = source_root / name
        if path.is_file():
            config.append({'path': name, 'sha256': sha256(path)})
    identity = {'schema': 'wolvrix.f30.gsim-native.v1', 'original_binary': str(binary),
        'binary': str(copied), 'sha256': original_hash, 'source_revision': revision, 'source': source,
        'source_patch': {'path': str(patch), 'sha256': sha256(patch)},
        'build_configuration_files': config, 'libraries': sorted(libraries, key=lambda item: item['path']),
        'source_binding': 'frozen binary and current source contents; no rebuild or retroactive build provenance claim'}
    identity_path = frozen / 'identity.json'
    write_json_atomic(identity_path, identity)
    return identity, identity_path


def benchmark(binary, source_root, firrtl, output):
    output, firrtl = Path(output).resolve(), Path(firrtl).resolve()
    if not output.is_relative_to(ROOT / 'ptmp'):
        raise ValueError('output must be under repository ptmp/')
    output.mkdir(parents=True, exist_ok=True)
    summary = output / 'summary.json'
    if summary.exists():
        raise ValueError('refusing to overwrite an existing GSIM sample')
    report = {'schema': SCHEMA, 'status': 'running', 'mode': 'no-trace',
        'trace': False, 'stop_after_stage': 'SplitArray', 'input': str(firrtl),
        'input_sha256': sha256(firrtl), 'input_bytes': firrtl.stat().st_size,
        'cpu_affinity': sorted(os.sched_getaffinity(0)),
        'configuration': {'machine': list(platform.uname()),
            'cpu_model': next((line.partition(':')[2].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                               if line.startswith('model name')), platform.machine()),
            'thread_environment': {key: os.environ.get(key) for key in
                ('OMP_NUM_THREADS', 'OMP_PROC_BIND', 'TBB_NUM_THREADS', 'WOLVRIX_THREADS')},
            'loader_environment': {key: os.environ.get(key) for key in ('LD_LIBRARY_PATH', 'LD_PRELOAD')},
            'instrumentation': {'trace': False, 'dump': False, 'source': 'raw-firrtl'}},
        'scope': 'GSIM raw FIRRTL only; GRH manifest SV helper cost remains on the GRH side',
        'resource_scope': 'monotonic supervisor wall includes start-summary/log setup and child execution through exit; native timers use integer milliseconds',
        'maxrss_scope': 'cumulative RUSAGE_CHILDREN high-water mark for this invocation, including source-freeze git/ldd subprocesses'}
    write_json_atomic(summary, report)
    try:
        identity, identity_path = freeze_native(binary, source_root, output)
        report.update(native=identity, identity_file=str(identity_path), identity_sha256=sha256(identity_path),
                      native_identity_verified=True)
        model = output / 'model'
        model.mkdir()
        command = [identity['binary'], '--dir', str(model), '--stop-after-stage=SplitArray', str(firrtl)]
        report['command'] = command
        write_json_atomic(summary, report)
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.monotonic()
        report['started_at_ns'] = time.time_ns()
        write_json_atomic(summary, report)
        with (output / 'gsim.log').open('w', encoding='utf-8') as log:
            process = subprocess.run(command, cwd=source_root, stdout=log, stderr=subprocess.STDOUT)
        report.update(finished_at_ns=time.time_ns(), wall_s=time.monotonic() - started,
                      returncode=process.returncode)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        report.update(user_s=after.ru_utime - before.ru_utime, system_s=after.ru_stime - before.ru_stime,
                      maxrss_kib=after.ru_maxrss)
        log_path = output / 'gsim.log'
        report.update(log=str(log_path), log_sha256=sha256(log_path))
        if process.returncode != 0:
            raise ValueError('GSIM subprocess failed: ' + str(process.returncode))
        report['timers'] = parse_timers(log_path.read_text(encoding='utf-8'))
        report['metrics'] = {'prefix': sum(report['timers'][name] for name in ('readFile', 'parseFIR', 'Init')),
                             'comb-split.total': report['timers']['splitArray']}
        report['metrics']['prefix+transform'] = sum(report['metrics'].values())
        if report['wall_s'] < report['metrics']['prefix+transform']:
            raise ValueError('GSIM native stage timers exceed the whole process boundary')
        if sha256(firrtl) != report['input_sha256'] or sha256(Path(identity['binary'])) != identity['sha256']:
            raise ValueError('GSIM input or frozen binary changed during the sample')
        report.update(status='passed', input_unchanged=True, binary_unchanged=True)
    except BaseException as error:
        report.update(status='failed', error=repr(error))
        write_json_atomic(summary, report)
        raise
    write_json_atomic(summary, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT / 'reference/gsim')
    parser.add_argument('--firrtl', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.binary, args.source_root.resolve(), args.firrtl, args.output), indent=2), flush=True)


if __name__ == '__main__':
    main()
