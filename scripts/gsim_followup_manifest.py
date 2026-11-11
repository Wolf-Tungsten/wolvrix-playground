#!/usr/bin/env python3
"""Write a compact identity manifest for the GSIM/GrhSIM follow-up."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT/'build/artifacts/kunminghu-v3-gsim-followup-20261111'
BUILD = ROOT/'build/xs/kunminghu-v3-gsim-followup-20261111'

def identity(path):
    path = Path(path).resolve()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=h.hexdigest())

def git(path, *args):
    return subprocess.check_output(['git','-C',str(path),*args], text=True).strip()

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-model',choices=('before','after'),action='append',default=[])
    args=parser.parse_args()
    source_before=ROOT/'testcase/xiangshan/build/xs/kunminghu-v3-gsim-followup-20261111/source-before'
    source_after=ROOT/'build/xiangshan-kunminghu-v3-port-20261110'
    gsim=ROOT/'reference/gsim/build/gsim/gsim'
    inputs=ROOT/'build/artifacts/kunminghu-v3-gsim-followup-20261111/inputs'
    record=dict(recorded_utc=datetime.now(timezone.utc).isoformat(),
        sources={
            'root':git(ROOT,'rev-parse','HEAD'),
            'before_xiangshan':git(source_before,'rev-parse','HEAD'),
            'after_xiangshan':git(source_after,'rev-parse','HEAD'),
            'before_difftest':git(source_before/'difftest','rev-parse','HEAD'),
            'after_difftest':git(source_after/'difftest','rev-parse','HEAD'),
            'gsim':git(ROOT/'reference/gsim','rev-parse','HEAD'),
            'wolvrix':git(ROOT/'wolvrix','rev-parse','HEAD')},
        toolchain={'gsim':identity(gsim) if gsim.exists() else None,
                   'gsim_source':git(ROOT/'reference/gsim','show','-s','--format=%H%n%s'),
                   'clang':subprocess.check_output(['/usr/bin/clang++','--version'],text=True).splitlines()[0]},
        inputs={name:identity(inputs/name) for name in ('coremark-2-iteration.bin','riscv64-nemu-interpreter-so')
                if (inputs/name).exists()},
        build_root=str(BUILD),artifact_root=str(ART))
    save(ART/'identity.json',record)
    for side in args.archive_model:
        source=source_before if side=='before' else source_after
        output=BUILD/'gsim'/side
        model=output/'gsim-compile/model'
        generated=source/'build/generated-src'
        binary=output/'gsim-compile/emu'
        if not binary.is_file():raise ValueError(side+': binary has not been built')
        files=sorted(path for path in model.rglob('*')
                     if path.is_file() and path.suffix in ('.cpp','.h','.hpp','.json'))
        generated_files=sorted(path for path in generated.rglob('*') if path.is_file())
        manifest=dict(side=side,source=git(source,'rev-parse','HEAD'),
            difftest=git(source/'difftest','rev-parse','HEAD'),
            recursive_submodules=git(source,'submodule','status','--recursive'),
            source_status=git(source,'status','--short'),
            gsim_source=record['sources']['gsim'],gsim_binary=record['toolchain']['gsim'],
            compiler=record['toolchain']['clang'],binary=identity(binary),
            chirrtl=identity(output/'rtl/SimTop.fir'),
            model_files=[identity(path) for path in files],
            difftest_generated_files=[identity(path) for path in generated_files],
            generation_log=identity(output/'gsim-compile/gsim-gen-cpp.log'),
            build_options=dict(config='DefaultConfig',gsim=1,optimization='-O3',
                pgo=False,bolt=False,waveform=False,randomize=False,
                chiseldb=False,constantin=False,supernode_max_size=15,cpp_max_size_kb=8192))
        save(ART/'model-manifests'/('gsim-'+side+'.json'),manifest)
    print(json.dumps(record,indent=2))

if __name__ == '__main__':
    main()
