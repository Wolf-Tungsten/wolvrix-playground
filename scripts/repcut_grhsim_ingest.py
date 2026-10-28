#!/usr/bin/env python3
"""Create a fresh flat GRH from an explicit Verilog file list, with provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import socket
import time
from pathlib import Path


def identity(path: Path) -> dict:
    path = path.resolve(strict=True)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f'input changed while hashing: {path}')
    return dict(path=str(path), size_bytes=after.st_size, sha256=digest.hexdigest())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--filelist', type=Path, required=True)
    parser.add_argument('--read-args', type=Path, required=True)
    parser.add_argument('--top', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--all-cpus', action='store_true',
                        help='explicitly use every online CPU, overriding inherited affinity')
    args = parser.parse_args()
    if args.all_cpus:
        online = set()
        for item in Path('/sys/devices/system/cpu/online').read_text().strip().split(','):
            limits = list(map(int, item.split('-')))
            online.update(range(limits[0], limits[-1] + 1))
        for task in Path('/proc/self/task').iterdir():
            os.sched_setaffinity(int(task.name), online)
        if os.sched_getaffinity(0) != online:
            raise RuntimeError('could not enable all online CPUs')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    record = dict(status='running', top=args.top, passes=[], host=socket.gethostname(),
                  cpu_affinity=sorted(os.sched_getaffinity(0)))

    def save() -> None:
        record['current_cpu_affinity'] = sorted(os.sched_getaffinity(0))
        (output / 'run.json').write_text(json.dumps(record, indent=2) + '\n')

    try:
        # This entry takes a plain absolute file list. Reject hidden option or
        # nested-list dependencies rather than recording incomplete provenance.
        rtl = []
        for line in args.filelist.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            path = Path(line)
            if not path.is_absolute() or not path.is_file():
                raise ValueError(f'expected an absolute Verilog source path: {line}')
            rtl.append(path)
        if not rtl:
            raise ValueError('empty Verilog file list')
        extra = shlex.split(args.read_args.read_text())
        headers = set()
        for i, token in enumerate(extra):
            if token == '-I':
                directory = Path(extra[i + 1]).resolve(strict=True)
                headers.update(directory.glob('*.vh'))
                headers.update(directory.glob('*.svh'))
        record.update(filelist=identity(args.filelist), read_args=identity(args.read_args),
                      rtl_inputs=[identity(p) for p in rtl],
                      headers=[identity(p) for p in sorted(headers)],
                      driver=identity(Path(__file__)))
        import wolvrix

        libraries = sorted({Path(line.split()[-1])
                            for line in Path('/proc/self/maps').read_text().splitlines()
                            if line.split()[-1].endswith('/libwolvrix-lib.so')})
        if len(libraries) != 1:
            raise RuntimeError(f'expected one Wolvrix library, found {libraries}')
        record['library'] = identity(libraries[0])
        save()
        with wolvrix.Session() as session:
            session.log_level = 'info'
            phase = time.monotonic()
            diagnostics = session.read_sv(None, out_design='design.main',
                                          slang_args=['-f', str(args.filelist.resolve()),
                                                      '--top', args.top, *extra])
            if any(d.get('kind') == 'error' for d in diagnostics):
                raise RuntimeError(f'Verilog ingestion failed: {diagnostics}')
            record['read_sv_s'] = time.monotonic() - phase
            save()
            pipeline = [('xmr-resolve', {}), ('memory-read-retime', {}),
                        ('multidriven-guard', {}), ('blackbox-guard', {}),
                        ('latch-transparent-read', {}), ('hier-flatten', {}),
                        ('comb-lane-pack', {'enable_declared_roots': False}),
                        ('comb-loop-elim', {}), ('simplify', {'semantics': '2state'}),
                        ('memory-init-check', {})]
            for name, options in pipeline:
                print(f'PASS_BEGIN {name}', flush=True)
                phase = time.monotonic()
                diagnostics = session.run_pass(name, design='design.main', **options)
                if any(d.get('kind') == 'error' for d in diagnostics):
                    raise RuntimeError(f'{name} failed: {diagnostics}')
                record['passes'].append(dict(name=name, options=options,
                                              elapsed_s=time.monotonic() - phase))
                save()
            target = output / 'raw.json'
            session.store_json(design='design.main', output=str(target), top=[args.top])
        for entry in [record['filelist'], record['read_args'], record['library'],
                      *record['rtl_inputs'], *record['headers']]:
            if identity(Path(entry['path'])) != entry:
                raise RuntimeError(f'input changed during ingestion: {entry["path"]}')
        record.update(status='pass', output=identity(target))
    except Exception as error:
        record.update(status='error', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        record['elapsed_s'] = time.monotonic() - started
        save()
    print(json.dumps(dict(status=record['status'], output=record['output'],
                          elapsed_s=record['elapsed_s'])), flush=True)


if __name__ == '__main__':
    main()
