#!/usr/bin/env python3
"""Run CRC alternatives against one unchanged generated kernel in one binary."""
import argparse
import json
import math
from pathlib import Path
import platform
import shutil
import statistics

from chisel_pattern_bench import ROOT, FIXTURE, identity, run, save


def summarize_control(data):
    if data['verified_vectors'] != 1000000 or len(data['samples']) != 80:
        raise ValueError('incomplete CRC control')
    summary = []
    for variant in ['serial', 'lookup']:
        for dist in ['random', 'sparse', 'dense', 'toggle1', 'hold99']:
            rows = [r for r in data['samples'] if r['variant'] == variant and r['distribution'] == dist]
            if [r['pair'] for r in rows] != list(range(8)):
                raise ValueError('missing or duplicate CRC pairs')
            for r in rows:
                if r['order'] != ('AB' if r['pair'] % 2 == 0 else 'BA'):
                    raise ValueError('incorrect CRC order')
                for key in ['candidate_ns', 'generated_ns']:
                    if not math.isfinite(r[key]) or r[key] <= 0:
                        raise ValueError('invalid CRC timing')
            ratios = [100 * (r['candidate_ns'] / r['generated_ns'] - 1) for r in rows]
            summary.append(dict(variant=variant, distribution=dist, pairs=8,
                                generated_ns=statistics.median(r['generated_ns'] for r in rows),
                                candidate_ns=statistics.median(r['candidate_ns'] for r in rows),
                                delta_percent=statistics.median(ratios),
                                delta_min=min(ratios), delta_max=max(ratios)))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cpu', type=int, default=96)
    parser.add_argument('--compiler', default='/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++')
    args = parser.parse_args()
    case = args.case.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    original = json.loads((case / 'build.json').read_text())
    for record in original['generated']:
        if identity(record['path'])['sha256'] != record['sha256']:
            raise ValueError('original generated kernel changed')
    shutil.copytree(case / 'model', out / 'model')
    for name in ['crc_variants.cpp', 'bench_types.hpp']:
        shutil.copy2(FIXTURE / name, out / name)
    command = [args.compiler, '-std=c++20', '-O3', '-march=native', '-pthread',
               '-I', out, '-I', out / 'model', out / 'crc_variants.cpp',
               *sorted((out / 'model').glob('*.cpp')), '-o', out / 'bench']
    run(command, out / 'compile.log')
    run(['objdump', '-d', '--demangle', out / 'bench'], out / 'assembly.txt')
    run(['nm', '-S', '--size-sort', '--demangle', out / 'bench'], out / 'symbols.txt')
    run(['taskset', '-c', str(args.cpu), out / 'bench'], out / 'measurement.json')
    data = json.loads((out / 'measurement.json').read_text())
    summary = summarize_control(data)
    save(out / 'summary.json', summary)
    save(out / 'manifest.json', dict(host=platform.node(), cpu=args.cpu, original_build=identity(case / 'build.json'),
        source_inputs=[identity(out / n) for n in ['crc_variants.cpp', 'bench_types.hpp']],
        generated=[identity(p) for p in sorted((out / 'model').glob('*')) if p.is_file()],
        binary=identity(out / 'bench'), measurement=identity(out / 'measurement.json'),
        command=[str(c) for c in command], qualification='One binary, shared indirect-call loop; kernel control, not whole-system timing'))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
