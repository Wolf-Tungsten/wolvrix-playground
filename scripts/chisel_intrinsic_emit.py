#!/usr/bin/env python3
"""Emit and inspect a switchable IntrinsicExpr example; stop at SystemVerilog."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'testcase/chisel-intrinsic/PriorityEncoderIntrinsic.scala'


def identity(path):
    path = Path(path).resolve()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=h.hexdigest())


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def classpath(name):
    path = ROOT / 'testcase/xiangshan/out/xiangshan' / (name + '.json')
    return [entry.split(':', 3)[3] for entry in json.loads(path.read_text())['value']]


def execute(command, directory, label):
    command = list(map(str, command))
    save(directory / (label + '.command.json'), command)
    env = {k: v for k, v in os.environ.items() if k not in ('CHISEL_FIRTOOL_PATH', 'FIRTOOL')}
    with (directory / (label + '.log')).open('w') as stream:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['both', 'rtl', 'intrinsic'], default='both')
    parser.add_argument('--probe-custom-name', action='store_true', help='also record whether an unregistered intrinsic emits')
    parser.add_argument('--firtool', type=Path,
                        default=Path.home() / '.cache/llvm-firtool/1.135.0/bin/firtool')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    classes = out / 'classes'
    classes.mkdir()
    compiler = classpath('scalaCompilerClasspath')
    runtime = classpath('test/runClasspath')
    plugin = next(p for p in classpath('scalacPluginClasspath') if 'chisel-plugin' in p)
    manifest = dict(scope='Scala elaboration and SystemVerilog emission only',
                    host=platform.node(), source=identity(SOURCE), driver=identity(__file__),
                    firtool=identity(args.firtool),
                    firtool_version=subprocess.check_output([args.firtool, '--version'], text=True),
                    scala_compiler_classpath=compiler, runtime_classpath=runtime,
                    jars=[identity(p) for p in dict.fromkeys([*compiler, plugin, *runtime]) if p.endswith('.jar')])
    save(out / 'manifest.json', manifest)
    command = ['java', '-Xmx4g', '-cp', ':'.join(compiler), 'scala.tools.nsc.Main',
               '-classpath', ':'.join(runtime), '-Xplugin:' + plugin, '-d', classes, SOURCE]
    if execute(command, out, 'compile'):
        raise RuntimeError('Scala compilation failed; see ' + str(out / 'compile.log'))
    modes = ['rtl', 'intrinsic'] if args.mode == 'both' else [args.mode]
    if args.probe_custom_name:
        modes.append('custom-name-probe')
    rows = []
    for mode in modes:
        folder = out / mode
        folder.mkdir()
        command = ['java', '-Xmx4g', '-cp', str(classes) + ':' + ':'.join(runtime),
                   'study.intrinsics.PriorityEncoderIntrinsicMain',
                   'false' if mode == 'rtl' else 'true', folder, args.firtool,
                   'custom' if mode == 'custom-name-probe' else 'dpi']
        code = execute(command, folder, 'emit')
        row = dict(mode=mode, returncode=code, status='emitted' if code == 0 else 'emit_failed')
        fir = folder / 'PriorityEncoder64.fir'
        sv = folder / 'PriorityEncoder64.sv'
        if fir.exists():
            row['chirrtl'] = identity(fir)
        if sv.exists():
            text = sv.read_text()
            row.update(verilog=identity(sv), lines=len(text.splitlines()),
                       dpi_import='import "DPI-C"' in text, conditional_operators=text.count('?'))
        if code:
            log = (folder / 'emit.log').read_text()
            row['error_tail'] = log[-4000:]
        rows.append(row)
        print(mode, row['status'], flush=True)
    summary = dict(scope='Emission only; no GRH, C++ model, simulation, equivalence or performance run',
                   cases=rows, semantics='64-bit LSB-first priority index; input zero returns 64; result width 7')
    primary = [r for r in rows if r['mode'] != 'custom-name-probe']
    summary['primary_emission_pass'] = all(r['returncode'] == 0 for r in primary)
    if args.mode == 'both' and summary['primary_emission_pass']:
        rtl = (out / 'rtl/PriorityEncoder64.sv').read_text()
        intrinsic = (out / 'intrinsic/PriorityEncoder64.sv').read_text()
        def ports(text):
            header = re.search(r'module PriorityEncoder64\s*\((.*?)\);', text, re.S)
            if not header:
                raise ValueError('top module ports not found')
            return re.sub(r'\s+', ' ', re.sub(r'//[^\n]*', '', header[1])).strip()
        summary['identical_top_ports'] = ports(rtl) == ports(intrinsic)
        if not summary['identical_top_ports']:
            raise ValueError('normal and intrinsic top ports differ')
        if 'import "DPI-C"' in rtl or 'import "DPI-C"' not in intrinsic:
            raise ValueError('unexpected emitted route')
        (out / 'verilog.diff').write_text(''.join(difflib.unified_diff(
            rtl.splitlines(keepends=True), intrinsic.splitlines(keepends=True),
            fromfile='rtl/PriorityEncoder64.sv', tofile='intrinsic/PriorityEncoder64.sv')))
    save(out / 'summary.json', summary)
    if not summary['primary_emission_pass']:
        raise RuntimeError('a requested emission failed; see summary.json')


if __name__ == '__main__':
    main()
