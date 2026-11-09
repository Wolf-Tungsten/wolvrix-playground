#!/usr/bin/env python3
"""Independent integer/SoftFloat reference and cycle-exact multiply checks."""
import argparse
import ctypes
import json
from pathlib import Path
import random
import shutil
import struct

from chisel_pattern_bench import run, save, identity
from multiply_behavior_study import ROOT, CXX, KINDS

MASK64 = (1 << 64) - 1
SEEDS = (1, 42, 20261105)


def signed(x, width):
    x &= (1 << width) - 1
    return x - (1 << width) if x >> (width - 1) else x


def softfloat(out, source):
    ref=out/'reference'; ref.mkdir(exist_ok=True)
    if not (ref/'source').exists():
        shutil.copytree(source/'source',ref/'source')
        build=ref/'build'; build.mkdir()
        for f in ('Makefile','platform.h'): shutil.copy2(source/'build/Linux-x86_64-GCC'/f,build/f)
        save(ref/'source-identity.json',[identity(p) for p in sorted((ref/'source').rglob('*')) if p.is_file()])
    build=ref/'build'
    command='gcc -c -fPIC -Werror-implicit-function-declaration -DSOFTFLOAT_FAST_INT64 -DSOFTFLOAT_ROUND_ODD -DINLINE_LEVEL=5 -DSOFTFLOAT_FAST_DIV32TO16 -DSOFTFLOAT_FAST_DIV64TO32 -I. -I../source/RISCV -I../source/include -O2 -o $@'
    if not (build/'softfloat.a').exists():
        run(['make','-C',build,'-j12','SOURCE_DIR=../source','SPECIALIZE_TYPE=RISCV','COMPILE_C='+command],ref/'build.log')
    wrapper=ROOT/'testcase/chisel-intrinsic/MultiplySoftFloat.c'
    signature=dict(wrapper=identity(wrapper),library=identity(build/'softfloat.a'))
    stamp=ref/'oracle-identity.json'
    if not stamp.exists() or json.loads(stamp.read_text())!=signature:
        run(['gcc','-shared','-fPIC','-O2','-DSOFTFLOAT_FAST_INT64','-I'+str(ref/'source/include'),
            wrapper,build/'softfloat.a','-o',ref/'oracle.so'],ref/'link.log')
        save(stamp,signature)
    lib=ctypes.CDLL(str(ref/'oracle.so')); f=lib.multiply_reference
    f.argtypes=[ctypes.c_uint,ctypes.c_uint64,ctypes.c_uint64,ctypes.c_uint64,
                ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_uint32)]
    f.restype=ctypes.c_uint64
    return f


def fp_element(oracle, width, a, b, c, op, rm, widen=False):
    src_width=width//2 if widen else width
    if op>=5: a,c=c,a
    if op in (2,4,6,8): a ^= 1 << (src_width-1)
    if op in (2,3,6,7): c ^= 1 << (width-1)
    flags=ctypes.c_uint32()
    result=oracle(width,a,b,c,int(op!=0),rm,int(widen),ctypes.byref(flags))
    return result,flags.value


def expected(kind, d, oracle):
    a,b,c=d['a'],d['b'],d['c']
    if kind=='int-mul':
        op=d['op']; a=a&127 if op==12 else a
        if op in (0,4,12): result=a*b
        elif op==1: result=(signed(a,64)*signed(b,64)) >> 64
        elif op==2: result=(signed(a,64)*b) >> 64
        else: result=(a*b) >> 64
        if op in (4,12): result=signed(result,32)
        return result&MASK64,0
    if kind=='vec-int-mul':
        width=8<<d['format']; mask=(1<<width)-1; lanes=64//width
        results=[]; saturation=0
        for lane in range(lanes):
            x=(a>>(lane*width))&mask; y=(b>>(lane*width))&mask
            x=signed(x,width) if d['signedA'] else x
            y=signed(y,width) if d['signedB'] else y
            product=x*y
            if d['fixed']:
                sat=x==y==-(1<<(width-1))
                if sat:
                    value=(1<<(width-1))-1
                    saturation |= ((1<<(width//8))-1) << (lane*width//8)
                else:
                    shift=width-1; high=product>>shift; guard=(product>>(shift-1))&1
                    sticky=bool(product&((1<<(shift-1))-1)); lsb=high&1
                    inc=(guard,guard and (sticky or lsb),False,not lsb and (guard or sticky))[d['rm']]
                    value=high+int(inc)
            else:
                if d['macc']:
                    if d['widen']:
                        old=(c>>((lane%(lanes//2))*2*width))&((1<<(2*width))-1)
                    else: old=(c>>(lane*width))&mask
                    product=old-product if d['sub'] else old+product
                value=product>>width if d['high'] else product
            results.append(value)
        if d['widen']:
            half=lanes//2; results=results[d['uop']*half:(d['uop']+1)*half]; width*=2
        return sum((v&((1<<width)-1))<<(i*width) for i,v in enumerate(results))&MASK64,saturation
    width=8<<d['format']; count=1 if kind=='fp-mul' else 64//width
    result=flags=0
    qnan={16:0x7e00,32:0x7fc00000,64:0x7ff8000000000000}
    for lane in range(count):
        if d['widen']:
            src_width=width//2; offset=(d['uop']*(64//width)+lane)*src_width
        else: src_width=width; offset=lane*width
        x=(a>>offset)&((1<<src_width)-1); y=(b>>offset)&((1<<src_width)-1)
        z=(c>>(lane*width))&((1<<width)-1)
        if d['canonical']&1: x=qnan[src_width]
        if d['canonical']&2: y=qnan[src_width]
        if d['canonical']&4: z=qnan[width]
        v,f=fp_element(oracle,width,x,y,z,d['op'],d['rm'],d['widen'])
        result |= v<<(lane*width); flags |= f<<(lane*5)
    if kind=='fp-mul' and width<64: result |= MASK64 ^ ((1<<width)-1)
    return result,flags


def fp_values(width):
    exp,frac={16:(5,10),32:(8,23),64:(11,52)}[width]
    inf=((1<<exp)-1)<<frac; one=((1<<(exp-1))-1)<<frac
    return [0,1,1<<frac,(1<<frac)-1,one,one+1,one-1,inf-1,inf,inf+1,
            inf|(1<<(frac-1)),1<<(width-1),(1<<(width-1))|one,(1<<(width-1))|inf]


def vectors(kind, oracle):
    records=[]; coverage={}
    for seed in SEEDS:
        rng=random.Random(seed)
        for cycle in range(10000):
            d=dict(a=rng.getrandbits(64),b=rng.getrandbits(64),c=rng.getrandbits(64),op=0,format=0,rm=0,
                signedA=0,signedB=0,signedC=0,high=0,macc=0,sub=0,widen=0,fixed=0,uop=rng.randrange(2),canonical=0)
            if kind=='int-mul':
                d['op']=(0,1,2,3,4,12)[cycle%6]
                special=(0,1,MASK64,1<<63,(1<<63)-1,1<<31,(1<<32)-1)
                if cycle<294: d['a']=special[(cycle//6)%7]; d['b']=special[(cycle//42)%7]
            elif kind=='vec-int-mul':
                d['format']=cycle%4; w=8<<d['format']; mode=(cycle//4)%6
                d.update(signedA=rng.randrange(2),signedB=rng.randrange(2),signedC=rng.randrange(2))
                d['high']=int(mode==1); d['widen']=int(mode in (2,4) and w<64)
                d['macc']=int(mode in (3,4)); d['sub']=int(mode==3 and rng.randrange(2))
                if mode==5:d.update(fixed=1,signedA=1,signedB=1,rm=(cycle//24)%4)
                if cycle<384:
                    values=(0,1,(1<<w)-1,1<<(w-1),(1<<(w-1))-1)
                    x=values[(cycle//4)%5]; y=values[(cycle//20)%5]
                    d['a']=sum(x<<(i*w) for i in range(64//w));d['b']=sum(y<<(i*w) for i in range(64//w))
            else:
                d['format']=cycle%3+1; w=8<<d['format']
                d['op']=(cycle//3)%(5 if kind=='fp-mul' else 9);d['rm']=(cycle//27)%5
                d['widen']=int(kind=='vec-fp-mul' and w>16 and d['op']<5 and cycle%7==0)
                if cycle<1800 or cycle%5==0:
                    sw=w//2 if d['widen'] else w
                    for idx,key in enumerate(('a','b','c')):
                        width=w if key=='c' else sw; vals=fp_values(width)
                        d[key]=sum(vals[(cycle//3+idx*7+lane*3)%len(vals)]<<(lane*width) for lane in range(64//width))
                if kind=='fp-mul' and w<64 and cycle%37==0:
                    d['canonical']=rng.randrange(4 if d['op']==0 else 8)
            result,flags=expected(kind,d,oracle)
            control=d['op']|(d['format']<<5)|(d['rm']<<7)
            for key,bit in [('signedA',10),('signedB',11),('signedC',12),('high',13),('macc',14),('sub',15),('widen',16),('fixed',17),('uop',18),('canonical',19)]:
                control |= d[key]<<bit
            reset=cycle<4 or 5000<=cycle<5004
            # Use a period independent of the 3-format and 7-cycle widening
            # patterns so bubbles cannot remove a format/rounding-mode case.
            valid=not reset and not 8000<=cycle<8100 and cycle%17!=0
            records.append((d['a'],d['b'],d['c'],control,int(valid),int(reset),result,flags))
            key=f"fmt={d['format']},op={d['op']},rm={d['rm']},wide={d['widen']},fixed={d['fixed']}"
            coverage[key]=coverage.get(key,0)+int(valid)
    if not all(coverage.values()):
        raise ValueError('control schedule omitted an operation/format case')
    return records,coverage


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study',type=Path,required=True)
    p.add_argument('--softfloat-source',type=Path,default=Path('/nfs/home/tanghaojin/NEMU/resource/softfloat/repo'))
    p.add_argument('--kinds',nargs='+',choices=KINDS,default=list(KINDS))
    args=p.parse_args();out=args.study.resolve();oracle=softfloat(out,args.softfloat_source)
    results=[]
    for kind in args.kinds:
        dest=out/kind;dest.mkdir(exist_ok=True)
        rows,coverage=vectors(kind,oracle);data=dest/'vectors.bin'
        with data.open('wb') as f:
            for row in rows:f.write(struct.pack('<8Q',*row))
        save(dest/'vectors.json',dict(identity=identity(data),seeds=SEEDS,coverage=coverage,
            fields=['a','b','c','control','valid','reset','result','flags'],reference='Python arbitrary-precision integer / RISC-V SoftFloat'))
        for label in 'AB':
            model=dest/label/'model';latency=3 if 'fp' in kind else 2
            run([CXX,'-std=c++20','-O3','-march=native','-DMODEL_LATENCY='+str(latency),'-I'+str(model),
                 ROOT/'testcase/chisel-intrinsic/MultiplyBehaviorCheck.cpp',model/'libgrhsim_MultiplyFixture.a',
                 '-o',model/'check'],dest/label/'check-compile.log')
            run([model/'check',data],dest/label/'check.log')
            result=json.loads((dest/label/'check.log').read_text());result.update(kind=kind,variant=label)
            results.append(result);save(out/'checks-partial.json',results)
            print('PASS',kind,label,flush=True)
        assert results[-1]['hash']==results[-2]['hash']
    save(out/'check-summary.json',results)


if __name__=='__main__':main()
