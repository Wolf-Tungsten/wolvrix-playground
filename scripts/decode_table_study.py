#!/usr/bin/env python3
"""Replay raw XiangShan tables, verify cared bits, and benchmark emitted models."""
from __future__ import annotations
import argparse
import csv
import json
import os
from pathlib import Path
import random
import re
import statistics
import struct
import subprocess
import time

from chisel_pattern_bench import ROOT, mill_classpath, run, save, identity

FIRTOOL = Path.home()/'.cache/llvm-firtool/1.135.0/bin/firtool'
CXX = '/nfs/home/tanghaojin/LLVM-23.1.2-Linux-X64/bin/clang++'
TOOLS = ROOT/'build/grhsim32-tools/bin'


def parse(payload):
    p=payload.strip().split('|')
    assert p[0]=='WDT1' and len(p)==8
    return dict(mode=p[1],n=int(p[2]),m=int(p[3]),fields=list(map(int,p[4].split(','))),
        default=int(p[5],16),care=int(p[6],16),
        rows=[tuple(int(v,16) for v in r.split(',')) for r in p[7].split(';') if r])


def reference(table,x):
    """Independent integer interpreter: retain original order and bit constraints."""
    matches=[r for r in table['rows'] if x&r[0]==r[1]]
    if not matches:return table['default']&table['care'],table['care']
    if table['mode']=='P':return matches[0][2]&matches[0][3],matches[0][3]
    value=care=0
    for _,_,v,c in matches:
        if (value^v)&care&c:raise ValueError('conflicting truth-table constraints')
        value|=v&c;care|=c
    return value,care


def build_scala(out):
    compiler=mill_classpath('scalaCompilerClasspath');runtime=mill_classpath('test/runClasspath')
    plugin=next(x for x in mill_classpath('scalacPluginClasspath') if 'chisel-plugin' in x)
    u=ROOT/'testcase/xiangshan/utility/src/main/scala/utility'
    sources=[u/n for n in ['Compatibility.scala','SimulationPrimitives.scala','DecodeTable.scala']]
    sources+=[ROOT/'testcase/chisel-intrinsic/DecodeTableStudy.scala']
    classes=out/'classes';classes.mkdir(parents=True,exist_ok=True)
    run(['java','-Xmx4g','-cp',':'.join(compiler),'scala.tools.nsc.Main','-classpath',':'.join(runtime),
         '-Xplugin:'+plugin,'-d',classes,*sources],out/'scala.log')
    save(out/'scala_inputs.json',[identity(p) for p in sources])
    return [str(classes),*runtime]


def extract_kernel(model):
    name='grhsim_DecodeTableStudy';cls='GrhSIM_DecodeTableStudy'
    order=list(dict.fromkeys(re.findall(r'\beval_compute_batch_(\d+)\(\);',(model/f'{name}_eval.cpp').read_text())))
    bodies=[]
    for batch in order:
        source=(model/f'{name}_sched_{batch}.cpp').read_text()
        for group in re.split(r'(?=// Supernode \d+:)',source)[1:]:
            m=re.search(r'activeWordFlags\s*=.*?;\s*\{',group,re.S)
            if not m:raise ValueError('unsupported generated group structure')
            start=end=m.end();depth=1
            while end<len(group) and depth:
                depth+=(group[end]=='{')-(group[end]=='}');end+=1
            if depth:raise ValueError('unbalanced generated group')
            bodies.append(group[start:end-1])
    if not bodies:raise ValueError('no generated compute bodies')
    header=model/f'{name}.hpp';text=header.read_text()
    header.write_text(text.replace('public:\n','public:\n    void research_compute();\n',1))
    path=model/'research_kernel.cpp'
    path.write_text(f'#include "{name}.hpp"\nvoid {cls}::research_compute() {{\nstd::uint8_t activeWordFlags=0;\n'+ '\n'.join('{\n'+body+'\n}' for body in bodies)+'\nrefresh_outputs();\n}\n')


def harness(table,verilator=False):
    n,m=table['n'],table['m'];iw=(n+63)//64;ow=(m+63)//64
    return f'''#include <array>
#include <type_traits>
#include <fstream>
#include <vector>
#include <chrono>
#include <iostream>
#include <cstdint>
#include <cstdlib>
#include "{'VDecodeTableStudy.h' if verilator else 'grhsim_DecodeTableStudy.hpp'}"
using Model={'VDecodeTableStudy' if verilator else 'GrhSIM_DecodeTableStudy'};
struct Vector {{ std::array<uint64_t,{iw}> input; std::array<uint64_t,{ow}> expected,care; }};
template<class T> void set(T& target,const std::array<uint64_t,{iw}>& x) {{
 if constexpr(std::is_integral_v<T>) target=x[0];
 else for(size_t i=0;i<({n}+sizeof(target[0])*8-1)/(sizeof(target[0])*8);++i) {{
   constexpr size_t bits=sizeof(target[0])*8;target[i]=x[i*bits/64]>>(i*bits%64);
 }}
}}
template<class T> std::array<uint64_t,{ow}> get(const T& source) {{
 std::array<uint64_t,{ow}> out{{}};
 if constexpr(std::is_integral_v<T>) out[0]=source;
 else for(size_t i=0;i<({m}+sizeof(source[0])*8-1)/(sizeof(source[0])*8);++i) {{
   constexpr size_t bits=sizeof(source[0])*8;out[i*bits/64]|=uint64_t(source[i])<<(i*bits%64);
 }}
 return out;
}}
int main(int argc,char** argv) {{
 if(argc<3)return 2;
 std::ifstream file(argv[2],std::ios::binary);std::vector<Vector> vectors;
 Vector v;while(file.read(reinterpret_cast<char*>(&v),sizeof(v)))vectors.push_back(v);
 if(vectors.empty() || !file.eof())return 3;
 Model model;
 if(std::string(argv[1])=="verify") {{
  for(size_t i=0;i<vectors.size();++i) {{const auto& v=vectors[i];set(model.in,v.input);model.eval();
   auto actual=get(model.out);
   for(size_t w=0;w<actual.size();++w)if((actual[w]^v.expected[w])&v.care[w]){{std::cerr<<"mismatch "<<i<<" word "<<w<<"\\n";return 1;}}
   {' ' if verilator else 'model.research_compute(); auto kernel=get(model.out); if(kernel!=actual){std::cerr<<"kernel differs "<<i<<"\\n";return 1;}'}
  }}
  std::cout<<"{{\\"vectors\\":"<<vectors.size()<<",\\"status\\":\\"pass\\"}}\\n";return 0;
 }}
 size_t iterations=std::stoull(argv[3]);uint64_t checksum=0;size_t pos=0;
 bool kernel=std::string(argv[1])=="kernel";
 auto start=std::chrono::steady_clock::now();
 for(size_t i=0;i<iterations;++i){{set(model.in,vectors[pos].input);
 {'model.eval();' if verilator else 'if(kernel)model.research_compute();else model.eval();'}
 auto out=get(model.out);for(auto word:out)checksum+=word;
 if(++pos==vectors.size())pos=0;
 }}
 double ns=std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/iterations;
 std::cout<<"{{\\"ns\\":"<<ns<<",\\"checksum\\":"<<checksum<<"}}\\n";
}}
'''


def vectors(table,kind,seed=20261103,count=100000):
    rng=random.Random(seed);mask=(1<<table['n'])-1
    if kind=='verify':
        if table['n']<=16:yield from range(1<<table['n']);return
        yield 0;yield mask
        for bit in range(table['n']):yield 1<<bit
        for r in table['rows']:
            for _ in range(4):yield (rng.getrandbits(table['n'])&~r[0])|r[1]
    last=0
    for i in range(count):
        if kind=='hold99' and i%100:pass
        elif kind=='toggle1':last^=1<<rng.randrange(table['n'])
        elif kind=='matched' and table['rows']:
            r=rng.choice(table['rows']);last=(rng.getrandbits(table['n'])&~r[0])|r[1]
        elif kind=='dense':last=mask^(1<<rng.randrange(table['n']))
        else:last=rng.getrandbits(table['n'])
        yield last


def write_vectors(path,table,values):
    iw=(table['n']+63)//64;ow=(table['m']+63)//64
    record=struct.Struct('<'+'Q'*(iw+2*ow));count=0
    with path.open('wb') as f:
        for x in values:
            v,c=reference(table,x)
            f.write(record.pack(*[(a>>(64*w))&((1<<64)-1) for a,size in [(x,iw),(v,ow),(c,ow)] for w in range(size)]));count+=1
    return count


def build_case(out,payload,classpath,espresso):
    out.mkdir(parents=True,exist_ok=True);(out/'table.txt').write_text(payload+'\n');table=parse(payload)
    env=os.environ.copy();env['PATH']=str(ROOT/'testcase/xiangshan/src/main/resources')+':'+env['PATH']
    run(['java','-Xmx8g','-cp',':'.join(classpath),'study.intrinsics.DecodeTableStudyMain',out/'table.txt',out,FIRTOOL,
         'espresso' if espresso else 'qmc'],out/'scala_emit.log',env)
    raw=json.loads((out/'B/calls.json').read_text())
    if payload not in raw['decode_tables'].values() or not any(c['intrinsic'] for c in raw['calls']):
        raise ValueError('fixture did not preserve the exact table or select the intrinsic')
    for variant in ['A','B']:
        p=out/variant;sv=p/'DecodeTableStudy.sv';model=p/'model'
        run([TOOLS/'grhsim32_frontend',p/'graph.json','DecodeTableStudy',sv],p/'frontend.log')
        run([TOOLS/'grhsim32_pattern_emit',p/'graph.json','DecodeTableStudy',model],p/'emit.log')
        graph=json.loads((p/'graph.json').read_text())
        ops=[op for g in graph['graphs'] for op in g['ops']]
        semantic=[op for op in ops if op['kind']=='kDecodeTable']
        if len(semantic)!=(1 if variant=='B' else 0):
            raise ValueError('unexpected intrinsic count in fixture graph')
        if semantic and (len(semantic[0]['in'])!=1 or semantic[0]['attrs']['decode.table']['v']!=payload):
            raise ValueError('fixture semantic operation differs from captured raw table')
        (p/'harness.cpp').write_text(harness(table));extract_kernel(model)
        run([CXX,'-std=c++20','-O3','-march=native','-I',model,p/'harness.cpp',*sorted(model.glob('*.cpp')),'-o',p/'bench'],p/'compile.log')
        run(['nm','-S','--size-sort',p/'bench'],p/'symbols.log')
        run(['objdump','-d',p/'bench'],p/'assembly.log')
    p=out/'verilator';p.mkdir(exist_ok=True);(p/'harness.cpp').write_text(harness(table,True))
    run(['verilator','--cc','--exe','--build','-j','8','-Wno-fatal','--top-module','DecodeTableStudy',
         '--Mdir',p/'obj',out/'A/DecodeTableStudy.sv',p/'harness.cpp','-CFLAGS','-O3 -std=c++20'],p/'compile.log')
    save(out/'identity.json',dict(table=identity(out/'table.txt'),binaries=[identity(out/'A/bench'),identity(out/'B/bench')]))


def verify_case(out):
    table=parse((out/'table.txt').read_text());checks=[]
    for seed in [20261103,20261104]:
        path=out/f'vectors-{seed}.bin'
        count=write_vectors(path,table,vectors(table,'verify',seed))
        for variant,exe in [('A',out/'A/bench'),('B',out/'B/bench'),('verilator',out/'verilator/obj/VDecodeTableStudy')]:
            run([exe,'verify',path],out/f'verify-{variant}-{seed}.log')
            checks.append(dict(variant=variant,seed=seed,vectors=count,status='pass'))
    save(out/'verification.json',checks)


def measure_case(out):
    if not os.uname().nodename.startswith('node030'):raise ValueError('measure on node030')
    os.sched_setaffinity(0,{96});table=parse((out/'table.txt').read_text());results=[]
    for distribution in ['random','matched','dense','toggle1','hold99']:
        inputs=out/f'{distribution}.bin';write_vectors(inputs,table,vectors(table,distribution))
        for mode in ['kernel','full']:
            def sample(variant,iterations):
                return json.loads(subprocess.check_output([str(out/variant/'bench'),mode,str(inputs),str(iterations)],text=True))
            a=sample('A',100000);b=sample('B',100000)
            iterations=max(100000,min(100000000,int(100000000/max(0.01,min(a['ns'],b['ns'])))))
            for pair in range(8):
                order=['A','B'] if pair%2==0 else ['B','A']
                row=dict(distribution=distribution,mode=mode,pair=pair,order=''.join(order),iterations=iterations)
                for variant in order:row[variant]=sample(variant,iterations)
                row['delta_percent']=100*(row['B']['ns']/row['A']['ns']-1);results.append(row)
                save(out/'pairs.json',results)
    with (out/'pairs.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['distribution','mode','pair','order','A_ns','B_ns','delta_percent'])
        for r in results:w.writerow([r['distribution'],r['mode'],r['pair'],r['order'],r['A']['ns'],r['B']['ns'],r['delta_percent']])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['build','verify','measure','all']);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--payload',type=Path);p.add_argument('--espresso',action='store_true');args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if args.command in ('build','all'):
        if not args.payload:p.error('--payload required for build')
        classpath=build_scala(out);build_case(out,args.payload.read_text().strip(),classpath,args.espresso)
    if args.command in ('verify','all'):verify_case(out)
    if args.command in ('measure','all'):measure_case(out)


if __name__=='__main__':main()
