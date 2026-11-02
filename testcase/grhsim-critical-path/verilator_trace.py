#!/usr/bin/env python3
"""Real Verilator adapter for the small rewrite fixture (not a XiangShan oracle)."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--rtl', type=Path, required=True)
    p.add_argument('--stimulus', type=Path, required=True)
    p.add_argument('--trace', type=Path, required=True)
    a = p.parse_args()
    verilator = shutil.which('verilator')
    if not verilator:
        raise RuntimeError('Verilator is required for the integration test')
    version = subprocess.check_output([verilator, '--version'], text=True).strip()
    harness = Path(__file__).with_name('rewrite_fixture.cpp')
    digest = hashlib.sha256(a.rtl.read_bytes() + harness.read_bytes() + version.encode()).hexdigest()[:20]
    folder = ROOT / 'wolvrix/build/artifacts/grhsim-critical-path' / ('verilator-' + digest)
    binary = folder / 'Vrewrite_fixture'
    if not binary.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / 'build.log').open('w') as log:
            subprocess.run([verilator, '--cc', '--exe', '--build', '-j', '4', '-Wno-fatal',
                '--top-module', 'rewrite_fixture', '--Mdir', str(folder), str(a.rtl.resolve()),
                str(harness)], stdout=log, stderr=subprocess.STDOUT, check=True)
    header = dict(schema_version=1, stimulus_sha256=hashlib.sha256(a.stimulus.read_bytes()).hexdigest(),
                  observables=['outputs.y', 'state.q'], backend=version)
    with a.trace.open('w') as out:
        out.write(json.dumps(header) + '\n'); out.flush()
        subprocess.run([str(binary), str(a.stimulus.resolve())], stdout=out, check=True)


if __name__ == '__main__':
    main()
