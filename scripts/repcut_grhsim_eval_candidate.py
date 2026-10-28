#!/usr/bin/env python3
"""Build an eval-only candidate while preserving a reference archive order.

All generated headers and non-eval sources must match the compiled source
package. Existing object payloads are reused; only changed model eval sources
are compiled. Archive order is verified independently of payload identity.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from repcut_cycle_trace import LLVM, align_object, archive_hashes, link_harness
from repcut_cost_model_compare import identity
from repcut_formal_zero_thp_compare import audit_compute_alignment


def members(archive: Path) -> list[str]:
    return subprocess.check_output([str(LLVM / 'llvm-ar'), 't', str(archive)],
                                   text=True).splitlines()


def build(source: Path, generated: Path, reference: Path, output: Path, jobs: int) -> dict:
    source, generated, reference = (p.resolve(strict=True) for p in
                                    (source, generated, reference))
    output = output.resolve()
    source_archive = source / 'libgrhsim_SimTop.a'
    source_identity, reference_identity = identity(source_archive), identity(reference)
    source_members, order = members(source_archive), members(reference)
    if len(set(order)) != len(order) or set(order) != set(source_members):
        raise ValueError('archive member names differ or contain duplicates')
    code_names = lambda p: {x.name for x in p.iterdir()
                            if x.suffix in ('.h', '.hpp', '.cpp')}
    names = code_names(source)
    if names != code_names(generated):
        raise ValueError('generated source/header file set differs')
    changed = []
    digests = {}
    for name in sorted(names):
        old, new = (source / name).read_bytes(), (generated / name).read_bytes()
        digests[name] = hashlib.sha256(new).hexdigest()
        if old != new:
            if not name.endswith('_model_eval.cpp'):
                raise ValueError(f'non-eval source/header differs: {name}')
            changed.append(name)
    output.mkdir(parents=True, exist_ok=False)
    package = output / 'package'
    package.mkdir()
    for item in generated.iterdir():
        if item.suffix in ('.h', '.hpp', '.cpp', '.mk') or item.name == 'Makefile':
            (package / item.name).symlink_to(item)
    archive = package / source_archive.name
    started = time.monotonic()
    before_hashes = archive_hashes(source_archive)
    with tempfile.TemporaryDirectory(prefix='repcut-eval-', dir=output) as temporary:
        objects = Path(temporary)
        subprocess.run([str(LLVM / 'llvm-ar'), 'x', str(source_archive)],
                       cwd=objects, check=True)

        def compile_one(name: str) -> str:
            obj = objects / (Path(name).stem + '.o')
            with (output / (name + '.log')).open('w') as log:
                subprocess.run([str(LLVM / 'clang++'), '-std=c++20', '-O3',
                                '-march=native', '-pthread', '-I', str(package),
                                '-c', str(generated / name), '-o', str(obj)],
                               stdout=log, stderr=subprocess.STDOUT, check=True)
            align_object(obj)
            return obj.name

        with ThreadPoolExecutor(max_workers=jobs) as pool:
            replaced = list(pool.map(compile_one, changed))
        subprocess.run([str(LLVM / 'llvm-ar'), 'rcs', str(archive), *order],
                       cwd=objects, check=True)
    if members(archive) != order:
        raise ValueError('archive order changed')
    after_hashes = archive_hashes(archive)
    changed_payloads = sorted(k for k in order if before_hashes[k] != after_hashes[k])
    if changed_payloads != sorted(replaced):
        raise ValueError(f'unexpected object payload changes: {changed_payloads}')
    binary = link_harness(output, package, archive)
    if identity(source_archive) != source_identity or identity(reference) != reference_identity:
        raise ValueError('source/reference archive changed during build')
    result = {'source_archive': source_identity, 'order_reference': reference_identity,
              'generated_package': str(generated), 'changed_eval_sources': changed,
              'changed_object_payloads': changed_payloads, 'member_count': len(order),
              'member_order_sha256': hashlib.sha256('\n'.join(order).encode()).hexdigest(),
              'source_sha256': digests, 'archive': identity(archive),
              'binary': identity(binary), 'alignment': audit_compute_alignment(binary, 64),
              'build_elapsed_s': time.monotonic() - started, 'status': 'pass'}
    (output / 'build.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'member_count', 'changed_eval_sources',
                                           'binary', 'build_elapsed_s')}, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-package', required=True, type=Path)
    parser.add_argument('--generated-package', type=Path)
    parser.add_argument('--order-reference', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--jobs', default=8, type=int)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    build(args.source_package, args.generated_package or args.source_package,
          args.order_reference, args.output, args.jobs)
