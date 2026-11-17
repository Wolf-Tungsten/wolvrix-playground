"""Advise eviction of closed F32 artifact pages without deleting file contents."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import time


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'ptmp/firrtl-ingest/F32'


def release_files(paths, *, sync=False, minimum_bytes=8 * 1024**2):
    result = {'operation': 'POSIX_FADV_DONTNEED', 'sync': sync, 'files': [], 'bytes': 0, 'errors': []}
    for path in paths:
        path = Path(path).absolute()
        if not path.is_relative_to(WORK) or path.resolve() != path:
            raise ValueError('cache advice requires nonsymlink F32 artifact paths')
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size < minimum_bytes:
            continue
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                if sync:
                    os.fdatasync(descriptor)
                os.posix_fadvise(descriptor, 0, 0, os.POSIX_FADV_DONTNEED)
            finally:
                os.close(descriptor)
            result['files'].append({'path': str(path), 'bytes': info.st_size})
            result['bytes'] += info.st_size
        except OSError as error:
            result['errors'].append({'path': str(path), 'error': str(error)})
    return result


def memory():
    return {'meminfo': Path('/proc/meminfo').read_text(),
            'pressure': Path('/proc/pressure/memory').read_text()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, action='append', required=True,
                        help='closed capture directory under ptmp/firrtl-ingest/F32')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.absolute()
    if not args.output.is_relative_to(WORK) or args.output.resolve() != args.output:
        parser.error('report must be a nonsymlink F32 artifact path')
    files = []
    for directory in args.root:
        directory = directory.absolute()
        if not directory.is_relative_to(WORK) or directory.resolve() != directory:
            parser.error('capture directory must be under F32 with no symlink components')
        summary = json.loads((directory / 'summary.json').read_text())
        if summary.get('status') not in ('completed', 'failed'):
            parser.error('refusing cache advice on a running capture')
        guard = json.loads((directory / 'guard.json').read_text())
        if guard.get('status') not in ('completed', 'failed'):
            parser.error('capture guard has not finalized')
        files.extend(path for path in directory.rglob('*') if not path.is_symlink())
    before, started = memory(), time.time_ns()
    result = release_files(files)
    result.update(before=before, after=memory(), started_at_ns=started, finished_at_ns=time.time_ns())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'files_advised': len(result['files']), 'bytes': result['bytes'], 'errors': result['errors']}))


if __name__ == '__main__':
    main()
