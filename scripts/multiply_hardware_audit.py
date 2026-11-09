#!/usr/bin/env python3
"""Compare default hardware RTL against the original YunSuan source revision."""
import argparse
from pathlib import Path
import re
import subprocess
from chisel_pattern_bench import mill_classpath,run,save,identity
from multiply_behavior_study import ROOT,XS,FIRTOOL,KINDS


def canonical(path):
    text=Path(path).read_text()
    text=re.sub(r'/\*.*?\*/','',text,flags=re.S)
    text=re.sub(r'//[^\n]*','',text)
    return ''.join(text.split())


def main():
    p=argparse.ArgumentParser();p.add_argument('--study',type=Path,required=True)
    args=p.parse_args();study=args.study.resolve();out=study/'original-hardware';out.mkdir(exist_ok=True)
    ys=XS/'yunsuan';files=[]
    for rel in ('scalar/Mul.scala','vector/vectorIMAC/VIMac64b.scala','fpu/FloatFMA.scala','vector/VectorFloatFMA.scala'):
        dest=out/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(subprocess.check_output(['git','-C',ys,'show','HEAD:src/main/scala/yunsuan/'+rel]));files.append(dest)
    fixture=(ROOT/'testcase/chisel-intrinsic/MultiplyBehaviorStudy.scala').read_text()
    fixture=fixture.replace('new yunsuan.scalar.Mul(64, behavior)','new yunsuan.scalar.Mul(64)')
    for cls in ('yunsuan.vector.mac.VIMac64b','yunsuan.fpu.FloatFMA','yunsuan.vector.VectorFloatFMA'):
        fixture=fixture.replace('new '+cls+'(behavior)','new '+cls+'()')
    source=out/'MultiplyBehaviorStudy.scala';source.write_text(fixture);files.append(source)
    compiler=mill_classpath('scalaCompilerClasspath');runtime=mill_classpath('test/runClasspath')
    plugin=next(x for x in mill_classpath('scalacPluginClasspath') if 'chisel-plugin' in x)
    classes=out/'classes';classes.mkdir(exist_ok=True)
    run(['java','-Xmx8g','-cp',':'.join(compiler),'scala.tools.nsc.Main','-classpath',':'.join(runtime),
        '-Xplugin:'+plugin,'-language:reflectiveCalls','-d',classes,*files],out/'scala.log')
    results=[]
    for kind in KINDS:
        dest=out/kind;dest.mkdir(exist_ok=True)
        run(['java','-Xmx12g','-cp',str(classes)+':'+':'.join(runtime),'study.multiply.MultiplyBehaviorStudyMain',
            dest,FIRTOOL,kind,'hardware'],dest/'elaborate.log')
        original=dest/'MultiplyFixture.sv';current=study/kind/'A/rtl/MultiplyFixture.sv'
        same=canonical(original)==canonical(current)
        results.append(dict(kind=kind,identical_except_comments_whitespace=same,original=identity(original),current=identity(current)))
    save(out/'summary.json',results)
    if not all(r['identical_except_comments_whitespace'] for r in results):
        raise ValueError('default RTL changed; inspect original-hardware/summary.json')
    print('PASS default hardware RTL matches original sources')


if __name__=='__main__':main()
