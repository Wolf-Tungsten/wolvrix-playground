#!/usr/bin/env python3
"""Reproducible, opt-in Chisel utility -> GrhSIM vs software experiments.

Builds only independent artifact directories. Uses the pinned XiangShan Mill
classpath, but recompiles the utility sources exercised by the wrappers.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'testcase/chisel-pattern-study'
CASES = ['popcount16','popcount64','popcount_threshold','ones_recursive','priority64',
         'oh_to_uint16','mux1h8','priority_mux8','select4','rotate8','barrel8','reverse64',
         'prefix_dense','prefix_ripple','xor_fold','parity64','ecc32','crc16','gray_decode32',
         'decode_table','cam8','sort4','csa64','table16','masked_write64','lfsr64','queue8','age8','wire64','native_add64',
         'crc16_table','sort4_network','priority16','popcount32','ones_recursive16','mux1h4','decode16',
         'table64','queue8_flow','cam8_state','gated_reg64','plain_reg64']
CASES += ['table64_indexed','bit_extract64','bit_deposit16','histogram8','guarded_div32']
STATEFUL = set(CASES[23:28]+CASES[37:43]+['histogram8'])
DISTRIBUTIONS = ['random','sparse','dense','toggle1','hold99']
ORIGINALS = ['utility/src/main/scala/utility/ParallelMux.scala',
             'utility/src/main/scala/utility/BitUtils.scala',
             'utility/src/main/scala/utility/ECC.scala',
             'utility/src/main/scala/utility/LFSR64.scala',
             'utility/src/main/scala/utility/IndexableCAMTemplate.scala',
             'utility/src/main/scala/utility/ClockGatedReg.scala',
             'utility/src/main/scala/utility/UIntUtils.scala',
             'src/main/scala/utils/VecRotate.scala',
             'rocket-chip/src/main/scala/util/PrefixSum.scala',
             'rocket-chip/src/main/scala/util/BarrelShifter.scala',
             'rocket-chip/src/main/scala/util/CRC.scala']


def identity(p):
    p = Path(p).resolve()
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
    return dict(path=str(p),sha256=h.hexdigest(),bytes=p.stat().st_size)


def save(p, obj):
    p = Path(p);p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')


def run(cmd, log, env=None):
    cmd = [str(x) for x in cmd]
    save(Path(str(log)+'.command.json'), cmd)
    with Path(log).open('w') as f:
        result = subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,env=env)
    if result.returncode:
        raise RuntimeError(f'command failed ({result.returncode}): {log}\n'+Path(log).read_text()[-3500:])


def mill_classpath(name):
    p = ROOT/'testcase/xiangshan/out/xiangshan'/f'{name}.json'
    if not p.exists(): raise ValueError(f'Missing {p}; run the pinned XiangShan Mill build first')
    return [x.split(':',3)[3] for x in json.loads(p.read_text())['value']]


def scala_build(out):
    compiler = mill_classpath('scalaCompilerClasspath')
    runtime = mill_classpath('test/runClasspath')
    plugin = next(x for x in mill_classpath('scalacPluginClasspath') if 'chisel-plugin' in x)
    sources = [FIXTURE/'PatternStudy.scala',*[ROOT/'testcase/xiangshan'/p for p in ORIGINALS]]
    signature = dict(sources=[identity(p) for p in sources],
                     jars=[identity(p) for p in dict.fromkeys([*compiler,plugin,*runtime]) if p.endswith('.jar')])
    classes = out/'classes';stamp = out/'scala_manifest.json'
    if stamp.exists() and json.loads(stamp.read_text()) == signature and classes.exists():
        return runtime
    classes.mkdir(exist_ok=True)
    run(['java','-Xmx4g','-cp',':'.join(compiler),'scala.tools.nsc.Main','-classpath',':'.join(runtime),
         '-Xplugin:'+plugin,'-language:reflectiveCalls','-d',classes,*sources],out/'scala.log')
    save(stamp,signature);save(out/'classpath.json',runtime)
    return runtime


def extract_compute(model):
    """Keep emitted group bodies byte-for-byte; remove only dispatch wrappers.

    Used only for combinational fixtures. All group bodies must be recognized,
    and the harness checks extracted outputs against normal eval for every input.
    """
    eval_text=(model/'grhsim_Pattern_eval.cpp').read_text()
    order=list(dict.fromkeys(re.findall(r'\beval_compute_batch_(\d+)\(\);',eval_text)))
    bodies=[];records=[]
    for batch in order:
        path=model/f'grhsim_Pattern_sched_{batch}.cpp'
        if not path.exists(): return dict(available=False,reason='unrecognized batch file layout')
        text=path.read_text();groups=re.split(r'(?=// Supernode \d+:)',text)[1:]
        for group in groups:
            match=re.search(r'activeWordFlags\s*=.*?;\s*\{',group,re.S)
            if not match:return dict(available=False,reason='unrecognized group dispatch')
            begin=match.end();depth=1;end=begin
            # Generated bodies contain no brace-bearing string literals in these fixtures.
            while end<len(group) and depth:
                depth+=(group[end]=='{')-(group[end]=='}');end+=1
            if depth:return dict(available=False,reason='unbalanced generated group')
            body=group[begin:end-1]
            if re.search(r'"[^"\n]*[{}][^"\n]*"',body):
                return dict(available=False,reason='string literals require a richer parser')
            bodies.append(body);records.append(dict(file=path.name,sha256=hashlib.sha256(body.encode()).hexdigest()))
    if not bodies:return dict(available=False,reason='no recognized compute groups')
    header=model/'grhsim_Pattern.hpp'
    content=header.read_text()
    if 'Output research_compute' not in content:
        header.write_text(content.replace('class GrhSIM_Pattern', 'struct Input;\nstruct Output;\nclass GrhSIM_Pattern',1)
                         .replace('public:', 'public:\n    __attribute__((noinline)) Output research_compute(const Input& input);',1))
    refresh=(model/'grhsim_Pattern_eval.cpp').read_text()
    # Output copies are inline here, to compare kernels with the same call ABI.
    match=re.search(r'void GrhSIM_Pattern::refresh_outputs\(\)\s*\{(.*?)\n\}',refresh,re.S)
    if not match:
        for p in model.glob('*.cpp'):
            match=re.search(r'void GrhSIM_Pattern::refresh_outputs\(\)\s*\{(.*?)\n\}',p.read_text(),re.S)
            if match:break
    if not match:raise ValueError('unrecognized output refresh')
    output_body=re.sub(r'\bio_([yz])\b',r'result.\1',match[1])
    (model/'research_compute.cpp').write_text('#include "bench_types.hpp"\n#include "grhsim_Pattern.hpp"\n'
        'Output GrhSIM_Pattern::research_compute(const Input& input) {\n'
        'const auto io_a=input.a,io_b=input.b,io_c=input.c,io_d=input.d;\n'
        'const auto io_sel=input.sel;\n'+ '\n'.join('{std::uint8_t activeWordFlags=0;'+b+'}' for b in bodies)+
        '\nOutput result;\n'+output_body+'\nreturn result;\n}\n')
    return dict(available=True,groups=records,meaning='all emitted combinational group bodies, dispatch removed; includes slots and output materialization')


def build_case(name,out,runtime,cxx,config,force,normalization):
    case=out/'cases'/name;case.mkdir(parents=True,exist_ok=True)
    signature=dict(scala_manifest=identity(out/'scala_manifest.json'),fixture=identity(FIXTURE/'bench.cpp'),abi=identity(FIXTURE/'bench_types.hpp'),
                   driver=identity(__file__),config=config,compiler=cxx,host=platform.node(),normalization=normalization,
                   tools=[identity(ROOT/'build/grhsim32-tools/bin'/n) for n in ['grhsim32_frontend','grhsim32_pattern_emit']])
    manifest=case/'build.json'
    if not force and manifest.exists() and json.loads(manifest.read_text()).get('signature')==signature and (case/'bench').exists():
        return name
    run(['java','-Xmx4g','-cp',str(out/'classes')+':'+':'.join(runtime),'PatternStudyMain',name,case/'rtl'],case/'elaborate.log')
    env={k:v for k,v in os.environ.items() if not k.startswith('WOLVRIX_GRHSIM_')};env.update(config['options'])
    run([ROOT/'build/grhsim32-tools/bin/grhsim32_frontend',case/'graph.json','Pattern',case/'rtl/Pattern.sv'],case/'frontend.log',env)
    run([ROOT/'build/grhsim32-tools/bin/grhsim32_pattern_emit',case/'graph.json','Pattern',case/'model',normalization],case/'emit.log',env)
    model=case/'model'
    # The emitter cleans its own output directory; research sources are regenerated below.
    slice_info=extract_compute(model) if name not in STATEFUL else dict(available=False,reason='stateful fixture')
    save(case/'compute_slice.json',slice_info)
    cpp=sorted(model.glob('*.cpp'))
    cmd=[cxx,'-std=c++20','-O3','-march=native','-pthread','-I',model,'-I',FIXTURE,
         '-DPATTERN_KIND='+str(CASES.index(name)),'-DHAS_COMPUTE_SLICE='+str(int(slice_info['available'])),
         FIXTURE/'bench.cpp',*cpp,'-o',case/'bench']
    run(cmd,case/'compile.log')
    run(['nm','-S','--size-sort','--demangle',case/'bench'],case/'symbols.txt')
    run(['objdump','-d','--demangle',case/'bench'],case/'assembly.txt')
    save(manifest,dict(signature=signature,command=[str(x) for x in cmd],slice=slice_info,
        inputs=[identity(case/'rtl/Pattern.sv'),identity(case/'graph.json')],
        generated=[identity(p) for p in sorted(model.glob('*')) if p.is_file()],binary=identity(case/'bench')))
    return name


def benchmark_case(name,out,cpu,loops):
    case=out/'cases'/name
    run(['taskset','-c',str(cpu),case/'bench',str(loops)],case/'measurement.json')
    d=json.loads((case/'measurement.json').read_text())
    summary=[]
    for mode in DISTRIBUTIONS:
        rows=[r for r in d['samples'] if r['distribution']==mode]
        if len(rows)!=8 or [r['pair'] for r in rows]!=list(range(8)):raise ValueError('missing paired samples')
        a=[r['generated_ns'] for r in rows];b=[r['software_ns'] for r in rows]
        delta=[100*(y/x-1) for x,y in zip(a,b)]
        row=dict(distribution=mode,generated_ns=statistics.median(a),software_ns=statistics.median(b),
                 delta_percent=statistics.median(delta),delta_min=min(delta),delta_max=max(delta),pairs=8)
        if 'compute_slice_ns' in rows[0]:
            row['compute_slice_ns']=statistics.median(r['compute_slice_ns'] for r in rows)
            row['slice_software_ns']=statistics.median(r['slice_software_ns'] for r in rows)
            row['slice_delta_percent']=statistics.median(100*(r['slice_software_ns']/r['compute_slice_ns']-1) for r in rows)
            row['slice_delta_min']=min(100*(r['slice_software_ns']/r['compute_slice_ns']-1) for r in rows)
            row['slice_delta_max']=max(100*(r['slice_software_ns']/r['compute_slice_ns']-1) for r in rows)
        summary.append(row)
    save(case/'summary.json',dict(case=name,kind=CASES.index(name),verified_vectors=d['verified_vectors'],
        pre_and_post_edge_checked=d['pre_and_post_edge_checked'],
        summary=summary,measurement=identity(case/'measurement.json'),build=identity(case/'build.json')))
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['build','run','all'])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cases',nargs='+',choices=CASES,default=CASES)
    p.add_argument('--jobs',type=int,default=4)
    p.add_argument('--cpu',type=int,default=96)
    p.add_argument('--loops',type=int,default=8)
    p.add_argument('--force',action='store_true')
    p.add_argument('--normalization',choices=['raw','postpartition'],default='postpartition')
    p.add_argument('--compiler',default=None)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    frozen=ROOT/'build/xs/grhsim32_fresh_rtl_20261028/configuration.json'
    cfg=json.loads(frozen.read_text());cxx=args.compiler or cfg['compiler']
    save(out/'environment.json',dict(host=platform.node(),cpu=args.cpu,loops=args.loops,
        compiler=subprocess.check_output([cxx,'--version'],text=True),cpuinfo=Path('/proc/cpuinfo').read_text().split('\n\n')[0],
        configuration=identity(frozen),generator_options=cfg['config']['options'],normalization=args.normalization))
    errors=[]
    if args.command in ['build','all']:
        runtime=scala_build(out)
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            fs={pool.submit(build_case,n,out,runtime,cxx,cfg['config'],args.force,args.normalization):n for n in args.cases}
            for f in as_completed(fs):
                try: print('BUILT',f.result(),flush=True)
                except Exception as e:errors.append(dict(case=fs[f],stage='build',error=str(e)));print('FAIL',fs[f],str(e),flush=True)
    # All timing is serial, after all compilation has finished.
    if args.command in ['run','all']:
        for n in args.cases:
            if any(e['case']==n for e in errors):continue
            try: print('MEASURED',n,benchmark_case(n,out,args.cpu,args.loops),flush=True)
            except Exception as e:errors.append(dict(case=n,stage='run',error=str(e)));print('FAIL',n,str(e),flush=True)
    save(out/'errors.json',errors)
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
