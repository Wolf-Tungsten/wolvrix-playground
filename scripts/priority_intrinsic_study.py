#!/usr/bin/env python3
"""Paired, real Chisel/Verilator/GrhSIM tests of the priority utility family."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
from grhsim_numa import runtime_plan, inspect_locality, locality_errors
from grhsim_single_baseline import clean_environment, cpu_counters, idle_percent
import subprocess
from chisel_pattern_bench import identity, save, run, mill_classpath

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'testcase/chisel-intrinsic'
WIDTHS = [1,2,3,4,7,8,9,15,16,17,31,32,33,63,64,65,127,128,129,255,256,257,511,512,1024]
CXX = '/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++'
FIRTOOL = Path.home()/'.cache/llvm-firtool/1.135.0/bin/firtool'
TOOLS = ROOT/'build/grhsim32-tools/bin'

def scala(out):
    compiler=mill_classpath('scalaCompilerClasspath'); runtime=mill_classpath('test/runClasspath')
    plugin=next(p for p in mill_classpath('scalacPluginClasspath') if 'chisel-plugin' in p)
    sources=[ROOT/'testcase/xiangshan/utility/src/main/scala/utility'/p for p in
             ['Compatibility.scala','SimulationPrimitives.scala','ParallelMux.scala','PriorityMuxDefault.scala']]
    sources.extend([FIXTURE/'EncoderStudy.scala',FIXTURE/'EncoderContract.scala'])
    classes=out/'classes';classes.mkdir(exist_ok=True)
    run(['java','-Xmx4g','-cp',':'.join(compiler),'scala.tools.nsc.Main','-classpath',':'.join(runtime),
         '-Xplugin:'+plugin,'-d',classes,*sources],out/'scala.log')
    save(out/'sources.json',[identity(p) for p in sources]+[identity(__file__),identity(FIXTURE/'encoder_bench.cpp')])
    save(out/'tools.json',[identity(p) for p in [CXX,FIRTOOL,TOOLS/'grhsim32_frontend',TOOLS/'grhsim32_pattern_emit']])
    save(out/'jars.json',[identity(p) for p in dict.fromkeys([*compiler,plugin,*runtime]) if p.endswith('.jar')])
    save(out/'classpath.json',runtime)
    return runtime

def compute_method(model,top):
    """Copy exact generated group bodies into a diagnostic member, retaining SSA/slots."""
    eval_text=(model/f'grhsim_{top}_eval.cpp').read_text()
    order=list(dict.fromkeys(re.findall(r'\beval_compute_batch_(\d+)\(\);',eval_text)))
    bodies=[]; evidence=[]
    for batch in order:
        p=model/f'grhsim_{top}_sched_{batch}.cpp'
        for group in re.split(r'(?=// Supernode \d+:)',p.read_text())[1:]:
            m=re.search(r'activeWordFlags\s*=.*?;\s*\{',group,re.S)
            if not m: raise ValueError('unknown generated group body')
            begin=m.end();end=begin;depth=1
            while depth and end<len(group):
                depth+=(group[end]=='{')-(group[end]=='}');end+=1
            if depth:raise ValueError('unbalanced group body')
            body=group[begin:end-1];bodies.append(body)
            import hashlib
            evidence.append(dict(file=p.name,sha256=hashlib.sha256(body.encode()).hexdigest()))
    if not bodies:raise ValueError('no compute bodies')
    header=model/f'grhsim_{top}.hpp'
    save(model/'original_header.json',identity(header))
    header.write_text(header.read_text().replace('public:', 'public:\n    void research_compute();',1))
    (model/'research_compute.cpp').write_text(f'#include "grhsim_{top}.hpp"\nvoid GrhSIM_{top}::research_compute() {{\n'+
        '\n'.join('{std::uint8_t activeWordFlags=0;'+b+'}' for b in bodies)+'\nrefresh_outputs();\n}\n')
    save(model/'compute_evidence.json',evidence)

def contracts(out,runtime):
    case=out/'contracts';case.mkdir(exist_ok=False)
    run(['java','-Xmx4g','-cp',str(out/'classes')+':'+':'.join(runtime),
         'study.intrinsics.EncoderContractMain',case,FIRTOOL],case/'scala.log')
    objects=[]
    for variant in ['A','B']:
        top='Conditional'+variant;folder=case/variant;folder.mkdir()
        run([TOOLS/'grhsim32_frontend',folder/'graph.json',top,case/(top+'.sv')],folder/'frontend.log')
        run([TOOLS/'grhsim32_pattern_emit',folder/'graph.json',top,folder/'model','raw'],folder/'emit.log')
        graph=json.loads((folder/'graph.json').read_text())
        kinds=[o['kind'] for g in graph['graphs'] for o in g['ops']]
        if variant=='B' and ('kCountTrailingZeros' not in kinds or 'kDpicCall' in kinds):
            raise ValueError('conditional wrapper did not lower to pure CTZ')
        wrapper=folder/'wrapper.cpp'
        wrapper.write_text(f'''#include "grhsim_{top}.hpp"
extern "C" unsigned conditional_{variant}(unsigned x,bool enable) {{
 static GrhSIM_{top} m; m.x=x; m.enable=enable; m.eval(); return m.y;
}}
''')
        for i,source in enumerate([wrapper,*sorted((folder/'model').glob('*.cpp'))]):
            obj=folder/f'{i}.o';objects.append(obj)
            run([CXX,'-std=c++20','-O3','-march=native','-I',folder/'model','-c',source,'-o',obj],folder/f'compile-{i}.log')
    source=case/'check.cpp'
    source.write_text('''#include <cassert>
extern "C" unsigned conditional_A(unsigned,bool),conditional_B(unsigned,bool);
int main(){for(unsigned repeat=0;repeat<2;++repeat)for(unsigned x=0;x<256;++x)
for(unsigned enable=0;enable<2;++enable){unsigned expected=7;
if(!enable)expected=5;else if(x){expected=0;while(!(x&(1U<<expected)))++expected;}
assert(conditional_A(x,enable)==expected);assert(conditional_B(x,enable)==expected);}}
''')
    run([CXX,'-std=c++20','-O3',source,*objects,'-o',case/'check'],case/'link.log')
    run([case/'check'],case/'check.log')
    save(case/'result.json',dict(pass_=True,vectors=1024,scope='conditional utility call, repeated eval, zero, all 8-bit values; empty and unknown-width rejection; elaboration scope reset'))

def build_case(out,width,layout,runtime):
    case=out/f'w{width}-{layout}';case.mkdir(exist_ok=False)
    run(['java','-Xmx4g','-cp',str(out/'classes')+':'+':'.join(runtime),'study.intrinsics.EncoderStudyMain',
         width,layout,case,FIRTOOL],case/'scala.log')
    calls=json.loads((case/'B/calls.json').read_text())['calls']
    if any(x['layout']=='distributed' and x['intrinsic'] for x in calls):
        raise ValueError(f'{case.name}: distributed input selected intrinsic')
    if layout == 'packed' and not any(x['layout']=='packed' and x['intrinsic'] for x in calls):
        raise ValueError(f'{case.name}: packed input did not select intrinsic')
    if layout == 'lanes' and any(x['intrinsic'] for x in calls):
        raise ValueError(f'{case.name}: Vec[Bool] layout still selected an intrinsic')
    words=(width+63)//64
    (case/'abi.hpp').write_text(f'''#pragma once
#include <array>
#include <cstdint>
constexpr unsigned Width={width}, Words={words};
struct Input {{ std::array<uint64_t,Words> x{{}}; uint32_t fallback=0; uint8_t unused=0; }};
struct Output {{ uint32_t index,parallel,flagged,valid,fallback; bool operator==(const Output&) const = default; }};
extern "C" Output run_a(const Input&,bool);
extern "C" Output run_b(const Input&,bool);
extern "C" Output run_v(const Input&);
''')
    cpp=[]
    for variant in ['A','B']:
        folder=case/variant;top='Encoder'+variant;model=folder/'model'
        run([TOOLS/'grhsim32_frontend',folder/'graph.json',top,folder/(top+'.sv')],folder/'frontend.log')
        run([TOOLS/'grhsim32_pattern_emit',folder/'graph.json',top,model,'raw'],folder/'emit.log')
        compute_method(model,top)
        if layout=='lanes':assign='\n'.join(f'm.bits_{i}=bool((x.x[{i//64}]>>{i%64})&1);' for i in range(width))
        elif width<=64:assign='m.x=x.x[0];'
        else:assign='m.x=x.x;'
        wrapper=folder/'wrapper.cpp'
        wrapper.write_text(f'''#include "abi.hpp"
#include "grhsim_{top}.hpp"
extern "C" Output run_{variant.lower()}(const Input& x,bool compute) {{
 static GrhSIM_{top} m;
 {assign}
 m.default_0=x.fallback; m.unused=x.unused;
 if(compute)m.research_compute();else m.eval();
 return {{m.index,m.parallel,m.flagged,m.valid,m.fallback}};
}}
''')
        # Separate translation units keep each model's generated runtime private.
        for index,p in enumerate([wrapper,*sorted(model.glob('*.cpp'))]):
            obj=folder/f'{index}.o';cpp.append(obj)
            run([CXX,'-std=c++20','-O3','-march=native','-pthread','-I',case,'-I',model,'-c',p,'-o',obj],folder/f'compile-{index}.log')
    vdir=case/'verilator'
    run(['verilator','--cc','--prefix','VReference','--top-module','EncoderA','--Mdir',vdir,
         '-Wno-fatal','--build','-j','2','-CFLAGS','-O3 -march=native',case/'A/EncoderA.sv'],case/'verilator.log')
    ver_root=Path(re.search(r'VERILATOR_ROOT\s*=\s*(\S+)',subprocess.check_output(['verilator','-V'],text=True))[1])
    if layout=='lanes':assign='\n'.join(f'm.bits_{i}=bool((x.x[{i//64}]>>{i%64})&1);' for i in range(width))
    elif width<=64:assign='m.x=x.x[0];'
    else:assign='\n'.join(f'm.x[{i}]=uint32_t(x.x[{i//2}]>>{32*(i%2)});' for i in range((width+31)//32))
    (case/'reference.cpp').write_text(f'''#include "abi.hpp"
#include "VReference.h"
extern "C" Output run_v(const Input& x) {{
 static VerilatedContext context; static VReference m(&context);
 {assign}
 m.default_0=x.fallback; m.unused=x.unused; m.eval();
 return {{m.index,m.parallel,m.flagged,m.valid,m.fallback}};
}}
''')
    run([CXX,'-std=c++20','-O3','-march=native','-pthread','-I',case,'-I',vdir,'-I',ver_root/'include',
         '-I',ver_root/'include/vltstd',FIXTURE/'encoder_bench.cpp',case/'reference.cpp',*cpp,
         vdir/'VReference__ALL.a',ver_root/'include/verilated.cpp',ver_root/'include/verilated_threads.cpp',
         '-o',case/'bench'],case/'link.log')
    run(['nm','-S','--size-sort','--demangle',case/'bench'],case/'symbols.txt')
    run(['objdump','-d','--demangle',case/'bench'],case/'assembly.txt')
    save(case/'build.json',dict(width=width,layout=layout,binary=identity(case/'bench'),
         files=[identity(p) for p in sorted(case.rglob('*')) if p.suffix in ('.sv','.hpp','.cpp','.json')]))
    print('built',case.name,flush=True)

def measure(out,width,layout):
    case=out/f'w{width}-{layout}';before=identity(case/'bench')
    env=clean_environment()
    runtime=case/'measurement-runtime'
    plan=runtime_plan(case/'bench',None,None,runtime,96,1,env)
    save(case/'runtime-plan.json',plan)
    run(['taskset','-c','96','numactl','--membind=1',sys.executable,ROOT/'scripts/grhsim_numa.py',case/'runtime-plan.json'],
        case/'prefault.log',env)
    plan=json.loads((runtime/'manifest.json').read_text());binary=runtime/'bin/emu'
    env['LD_LIBRARY_PATH']=str(runtime/'lib')
    os.sched_setaffinity(0,{0})
    siblings={96,288}
    for attempt in range(60):
        start=cpu_counters(siblings);time.sleep(3)
        if min(idle_percent(start,cpu_counters(siblings)).values())>=98:break
    else:raise RuntimeError('CPU96/288 busy before microbenchmark')
    begin=cpu_counters(siblings);snapshots=[];errors=[]
    command=['taskset','-c','96','numactl','--membind=1','setarch',os.uname().machine,'-R',str(binary)]
    save(case/'measurement.command.json',dict(command=command,driver=identity(__file__)))
    with (case/'measurement.json').open('w') as output,(case/'measurement.stderr').open('w') as err:
        proc=subprocess.Popen(command,stdout=output,stderr=err,env=env,cwd=binary.parent)
        while proc.poll() is None:
            try:
                folder=Path('/proc')/str(proc.pid)
                if (folder/'exe').resolve()==binary.resolve():
                    maps=(folder/'maps').read_text();numa=(folder/'numa_maps').read_text()
                    record=inspect_locality(maps,numa,plan)
                    errors.extend(locality_errors(record,1))
                    tasks=list((folder/'task').iterdir())
                    if len(tasks)!=1:errors.append(dict(threads=len(tasks)))
                    for task in tasks:
                        status=dict(l.split(':',1) for l in (task/'status').read_text().splitlines() if ':' in l)
                        if status['Cpus_allowed_list'].strip()!='96':errors.append(dict(affinity=status['Cpus_allowed_list']))
                    snaps=case/'numa-snapshots';snaps.mkdir(exist_ok=True)
                    (snaps/f'{len(snapshots):04d}.maps').write_text(maps)
                    (snaps/f'{len(snapshots):04d}.numa_maps').write_text(numa)
                    snapshots.append(record)
            except (FileNotFoundError,ProcessLookupError):pass
            time.sleep(.5)
    sibling=idle_percent(begin,cpu_counters(siblings))[288]
    if not snapshots or sibling<98:errors.append(dict(snapshots=len(snapshots),sibling_idle=sibling))
    seen={path for row in snapshots for path in row['seen_files']}
    if not {e['destination'] for e in plan['files']}.issubset(seen):errors.append(dict(missing_mappings=True))
    save(case/'locality.json',dict(pass_=not errors,errors=errors,snapshots=snapshots,sibling_idle=sibling))
    if proc.returncode or errors:raise RuntimeError(f'{case.name}: validation/placement failed; raw samples retained')
    assert before==identity(case/'bench')
    assert before['sha256']==identity(binary)['sha256']
    for entry in plan['files']:
        assert identity(entry['destination'])==entry['copy']
    data=json.loads((case/'measurement.json').read_text())
    result=[]
    for mode in ['random','sparse','dense','toggle1','hold99']:
        for compute in [False,True]:
            rows=[r for r in data['samples'] if r['distribution']==mode and r['compute']==compute]
            assert len(rows)==8 and [r['pair'] for r in rows]==list(range(8))
            result.append(dict(distribution=mode,compute=compute,pairs=8,
                a_ns=statistics.median(r['a_ns'] for r in rows),b_ns=statistics.median(r['b_ns'] for r in rows),
                delta_percent=statistics.median(100*(r['b_ns']/r['a_ns']-1) for r in rows)))
    save(case/'summary.json',dict(width=width,layout=layout,verified=data['verified'],rows=result,binary=before))
    print('measured',case.name,flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['build','run','all']);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--widths',nargs='+',type=int,default=WIDTHS)
    p.add_argument('--layouts',nargs='+',choices=['packed','lanes'],default=['packed','lanes'])
    p.add_argument('--jobs',type=int,default=4)
    p.add_argument('--coverage',type=Path,help='include every width observed in XiangShan elaboration')
    args=p.parse_args()
    if args.coverage:
        args.widths=sorted(set(args.widths)|{r['width'] for r in json.loads(args.coverage.read_text())['calls']})
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    matrix=dict(widths=args.widths,layouts=args.layouts,coverage=identity(args.coverage) if args.coverage else None)
    if (out/'matrix.json').exists() and json.loads((out/'matrix.json').read_text())!=matrix:
        raise ValueError('requested matrix differs from frozen build matrix')
    save(out/'matrix.json',matrix)
    if args.command in ['build','all']:
        runtime=scala(out)
        contracts(out,runtime)
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures=[pool.submit(build_case,out,w,l,runtime) for w in args.widths for l in args.layouts]
            for f in futures:f.result()
    if args.command in ['run','all']:
        import platform
        if not platform.node().startswith('node030'):raise ValueError('CPU96 measurements require node030')
        for w in args.widths:
            for l in args.layouts:measure(out,w,l)
        rows=[]
        for w in args.widths:
            for l in args.layouts:
                case=out/f'w{w}-{l}'
                summary=json.loads((case/'summary.json').read_text())
                for row in summary['rows']:
                    rows.append(dict(width=w,layout=l,**row))
        save(out/'matrix-summary.json',dict(matrix=json.loads((out/'matrix.json').read_text()),
            cases=len(args.widths)*len(args.layouts),rows=rows,
            verified_vectors=sum(json.loads((out/f'w{w}-{l}'/'summary.json').read_text())['verified']
                                 for w in args.widths for l in args.layouts),
            scope='Median of eight AB/BA pairs for each distribution and full/compute path; all rows retained'))
        with (out/'matrix-summary.csv').open('w',newline='') as f:
            import csv
            fields=['width','layout','distribution','compute','pairs','a_ns','b_ns','delta_percent']
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)

if __name__=='__main__':main()
