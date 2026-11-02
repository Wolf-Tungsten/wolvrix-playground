#!/usr/bin/env python3
"""Broad source inventory and Chinese evidence report for simulation patterns.

Lexical discovery is deliberately separate from elaboration proof and timing.
Unclassified files and candidates without experiments remain visible.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import csv
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

from chisel_pattern_bench import ROOT, identity, save
from chisel_pattern_catalog import catalog, STRUCTURAL_CASES
from chisel_pattern_findings import review
from chisel_pattern_crc_control import summarize_control
from chisel_pattern_results import summarize

DEFAULT_BUILD=ROOT/'build/xs/grhsim32_fresh_rtl_20261028'


def scala_code(text):
    """Erase comments / strings while preserving offsets and line numbers.

    Nested Scala block comments and triple strings are supported. String
    interpolation is not analyzed (conservative inventory, not a Scala parser).
    """
    out=list(text);i=0;n=len(text)
    def erase(a,b):
        for k in range(a,b):
            if out[k]!='\n':out[k]=' '
    while i<n:
        start=i
        if text.startswith('//',i):
            i=text.find('\n',i)
            if i<0:i=n
        elif text.startswith('/*',i):
            depth=1;i+=2
            while i<n and depth:
                if text.startswith('/*',i):depth+=1;i+=2
                elif text.startswith('*/',i):depth-=1;i+=2
                else:i+=1
        elif text.startswith('"""',i):
            end=text.find('"""',i+3);i=n if end<0 else end+3
        elif text[i]=='"':
            i+=1
            while i<n:
                if text[i]=='\\':i+=2
                elif text[i]=='"':i+=1;break
                else:i+=1
        else:i+=1;continue
        erase(start,min(i,n))
    return ''.join(out)


def source_group(path):
    if path.startswith('chisel-7.3.0/'):return 'Chisel 7.3.0'
    tail=path.removeprefix('testcase/xiangshan/').split('/')[0]
    return 'XiangShan 主设计' if tail=='src' else tail


def source_rows(out,jar):
    paths=subprocess.check_output(['rg','--files','testcase/xiangshan','-g','*.scala',
        '-g','!**/out/**','-g','!**/build/**','-g','!**/target/**','-g','!**/src/test/**',
        '-g','!**/test/**','-g','!**/tests/**'],cwd=ROOT,text=True).splitlines()
    for name in sorted(set(paths)):
        p=ROOT/name;yield name,p,p.read_text(errors='replace')
    with zipfile.ZipFile(jar) as z:
        for name in sorted(z.namelist()):
            if name.endswith('.scala'):
                data=z.read(name);p=out/'sources/chisel-7.3.0'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
                yield 'chisel-7.3.0/'+name,p,data.decode()


def survey(out,jar):
    specs=catalog();symbols=defaultdict(set)
    for p in specs:
        for s in p['symbols']:symbols[s].add(p['id'])
    inventory=[];matches=defaultdict(list);by_group=defaultdict(Counter)
    token_re=re.compile(r'\b[A-Za-z_$][\w$]*\b')
    declarations=re.compile(r'\b(class|object|trait)\s+([A-Za-z_$][\w$]*)')
    hardware_re=re.compile(r'\b(?:Reg|RegInit|Wire|WireInit|IO|Input|Output|Mux|Module|RawModule|Mem|SyncReadMem|UInt|SInt|Bool)\b|\.(?:U|B)\b')
    for name,path,text in source_rows(out,jar):
        code=scala_code(text);group=source_group(name);lines=code.splitlines()
        decls=[dict(kind=m[1],name=m[2],line=code.count('\n',0,m.start())+1) for m in declarations.finditer(code)]
        evidence=[];hits=Counter()
        for line_no,line in enumerate(lines,1):
            tokens=Counter(token_re.findall(line))
            for token,count in tokens.items():
                for pid in symbols.get(token,[]):
                    hits[pid]+=count
                    matches[pid].append(dict(file=name,path=str(path),line=line_no,symbol=token,count=count))
            if len(evidence)<5 and hardware_re.search(line):evidence.append(dict(line=line_no,text=line.strip()[:220]))
        role='hardware_or_hardware_type' if evidence else 'elaboration_or_unclassified'
        # Intentionally no automatic "unused" or "instantiated" conclusion.
        row=dict(file=name,path=str(path),sha256=identity(path)['sha256'],group=group,
                 lines=len(lines),role=role,role_basis='lexical evidence only',hardware_evidence=evidence,
                 declarations=decls,pattern_hits=dict(hits),disposition='pattern_indexed' if hits else 'unclassified_visible')
        inventory.append(row);by_group[group].update(files=1,lines=len(lines),declarations=len(decls),
                                                     indexed=int(bool(hits)),unclassified=int(not hits))
    save(out/'inventory.json',dict(schema_version=1,source_jar=identity(jar),groups=dict(by_group),files=inventory,
        qualification='词法扫描覆盖；不是全文件人工审阅，也不是 elaboration 调用图。未分类项保留。'))
    for p in specs:
        p['lexical_hits']=matches[p['id']]
        p['source_files']=len({r['file'] for r in matches[p['id']]})
        p['source_seed_locations']=[dict(file=f['file'],path=f['path']) for f in inventory if Path(f['file']).name in p['source_seeds']]
        p['unresolved_source_seeds']=[n for n in p['source_seeds']
            if not any(Path(f['file']).name==n for f in inventory)]
        seed_names={f['file'] for f in p['source_seed_locations']}
        p['source_anchors']=[r for r in p['lexical_hits'] if r['file'] in seed_names][:16]
        p['usage_qualification']='源码命中与独立实例分别记录；未自动断言当前整机配置已实例化此 utility'
    save(out/'catalog.json',dict(schema_version=2,patterns=specs))
    with (out/'coverage.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['源码','库','行数','声明数','词法角色','命中模式','处置'])
        for r in inventory:w.writerow([r['file'],r['group'],r['lines'],len(r['declarations']),r['role'],','.join(r['pattern_hits']),r['disposition']])
    return inventory,specs


def generated_evidence(out,build):
    package=build/'initial/package';report=build/'critical-path-dynamic-all32_20261029_v2'
    rows=[]
    for p in sorted(package.glob('*_sched_*.cpp')):
        text=p.read_text();match=re.search(r'Gpart_(\d+)_model_sched_(\d+)',p.name)
        if not match:continue
        row=dict(file=str(p),part=int(match[1]),batch=int(match[2]),bytes=p.stat().st_size,
                 lines=text.count('\n'),sha256=hashlib.sha256(text.encode()).hexdigest(),
                 phase='commit' if '::eval_commit_batch_' in text else 'compute',
                 if_count=len(re.findall(r'\bif\s*\(',text)),
                 memory_write_helpers=len(re.findall(r'\bgrhsim_assign_words(?:_\d+)?\(',text)),
                 activation_mentions=text.count('supernode_active_curr_'),dirty_mentions=text.count('producer_dirty_words_'),
                 scalar_slots=text.count('_slots_['),popcount_mentions=text.count('__builtin_popcount'))
        rows.append(row)
    dynamic=json.loads((report/'dynamic_top1.json').read_text())
    timed={}
    for r in dynamic['rows']:
        if r.get('status')!='measured' or not r.get('batch_key'):continue
        timed.setdefault(r['batch_key'],[]).append({k:r.get(k) for k in
            ['part','clock','scope','batch_key','ns','calls','share','sampled_steps','repeat_top_agreement','modules']})
    for r in rows:r['dynamic_top1_associations']=timed.get(f"{r['part']}:{r['phase']}:{r['batch']}",[])
    save(out/'generated_inventory.json',dict(files=rows,bytes=sum(r['bytes'] for r in rows),
        configuration=identity(build/'configuration.json'),dynamic_top1=identity(report/'dynamic_top1.json'),
        qualification='静态源代码统计和 batch 级关联；不分摊成 utility/信号耗时'))
    with (out/'generated_inventory.csv').open('w') as f:
        keys=['part','phase','batch','bytes','lines','if_count','memory_write_helpers','activation_mentions','dirty_mentions','scalar_slots','popcount_mentions','file']
        w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');w.writeheader();w.writerows(rows)
    return rows


def operation_evidence(out,build):
    """The native CSV includes locations; JSONL operation maps contain span IDs."""
    report=build/'critical-path-dynamic-all32_20261029_v2'
    package=build/'initial/package'
    needles={'MSHRCtl.sv','MSHRCtl_1.sv','VecRotate.sv','AgeDetector.sv','AgeDetector_1.sv',
             'CompressUnit.sv','LogPerfEndpoint.sv','MSHRBuffer.sv','MSHRBuffer_1.sv','Sbuffer.sv','Directory_Anon.sv'}
    counts=defaultdict(Counter);examples=defaultdict(list);selected=0;seen=0
    paths=sorted((report/'static').glob('*.sources.csv'))
    if len(paths)!=32:raise ValueError('expected the frozen 32-part native source exports')
    for path in paths:
        with path.open() as f:
            for r in csv.DictReader(f):
                seen+=1;filename=Path(r['file']).name
                if filename not in needles or not r['batch']:continue
                part=int(r['part'].removeprefix('inst_part_'));key=filename,f"{part}:{r['phase']}:{r['batch']}"
                counts[key][r['op_kind']]+=1;selected+=1
                # Keep arithmetic-root examples for MSHR count as well as first locations.
                preferred=filename.startswith('MSHRCtl') and 2070<=int(r['line'] or 0)<=2102 and r['op_kind']=='kAdd'
                if len(examples[key])<3 or (preferred and len(examples[key])<10):
                    r['cpp_file']=str(package/f"grhsim_Gpart_{part}_model_sched_{r['batch']}.cpp")
                    examples[key].append(r)
        print('SOURCE',path.stem,seen,flush=True)
    save(out/'operation_evidence.json',dict(scanned_rows=seen,selected_rows=selected,
        groups=[dict(file=k[0],batch=k[1],operations=dict(v),examples=examples[k]) for k,v in counts.items()],
        note='只保存列明 RTL 文件的结构线索；零命中不表示功能不存在'))


def link(path,label,line=None):
    href=str(path)+(f':{line}' if line else '')
    return f'[{label}](<{href}>)'


def report(out,bench,frozen_dir=None,crc_dir=None):
    inv=json.loads((out/'inventory.json').read_text());cat=json.loads((out/'catalog.json').read_text())
    measurements=summarize(bench)
    for p in cat['patterns']:
        p.update(review(p['id']))
    for m in measurements.values():
        for r in m['summary']:
            if 'kernel_delta_percent' in r:r['slice_delta_percent']=r['kernel_delta_percent']
    lines=['# Chisel／Verilog 仿真表达模式调查','',
           '本报告区分库源码覆盖、真实生成代码、独立参数实例微基准和整机热点关联。硬件 PPA 未测量；局部微基准不代表整机收益。','',
           '## 覆盖与证据口径','',
           f"扫描 {len(inv['files'])} 个 Scala 文件，形成 {len(cat['patterns'])} 项开放候选；未分类文件保留在 coverage.csv 和 inventory.json。",'',
           '| 源码组 | 文件 | 声明 | 未命中目录模式的文件 |','|---|---:|---:|---:|']
    for name,r in sorted(inv['groups'].items()):lines.append(f"| {name} | {r['files']} | {r['declarations']} | {r['unclassified']} |")
    lines+=['','源码扫描为词法证据，不证明 utility 被当前设计实例化。独立 wrapper 直接使用真实库的条目与结构缩小例子在案例说明中区分。',
            '','## 微基准结果','',
            '每个实例有两组种子、五种输入分布，每组至少 100,000 个正确性向量／周期；小输入空间另做穷举。每种分布完成 8 对 AB/BA。状态例子同时比较时钟沿前后输出。',
            '实验使用与当前分区后相同的 memory-write-coalesce、reg-to-mem（VerilatorV1 profitability）规则；独立模块不复现 32 分区拓扑。',
            '完整 eval 包含输入变化检测、调度、物化与输出更新；组合体保留发射的算式和 slot 操作，去掉批次派发，以相同调用 ABI 与软件 helper 比较。',
            '状态实例的软件模型按每拍输入输出比较，内部表示可不同；其差值包含整个独立组件调度开销。',
            '','| 实例 | 分布 | 完整 eval ns | 组合体 ns | 软件 ns | 软件/组合体变化 | 校验数 |','|---|---|---:|---:|---:|---:|---:|']
    for name,m in sorted(measurements.items()):
        for r in m['summary']:
            kernel=f"{r['compute_slice_ns']:.2f}" if 'compute_slice_ns' in r else '—'
            delta=f"{r['slice_delta_percent']:+.1f}%" if 'slice_delta_percent' in r else '状态组件单列'
            native=r.get('slice_software_ns',r['software_ns'])
            lines.append(f"| {name} | {r['distribution']} | {r['generated_ns']:.2f} | {kernel} | {native:.2f} | {delta} | {m['verified_vectors']} |")
    lines+=['','负百分比表示该微基准的软件表达更快；正百分比保留为退化。hold99 表示约 99% 输入保持，组合体强制重算与 activity 跳过具有不同口径。',
            '','## 模式目录与案例卡片','']
    for p in cat['patterns']:
        tested=[n for n in p['benchmark_cases'] if n in measurements]
        lines += [f"### {p['id']}：{p['title']}",'',
                  f"- 当前处置：{p['disposition']}。",f"- 硬件结构目的：{p['hardware_intent']}（未测 PPA）。",
                  f"- 源码线索：{p['source_files']} 个文件有词法命中；"+('代表实例已测：'+', '.join(tested) if tested else '尚未证明独立残留成本，保留为结构候选。'),
                  f"- 成本假设：{p['suspected_cost']}。",f"- 替代表达：{p['software_alternative']}。",f"- 等价边界：{p['semantic_boundary']}。",
                  f"- 已有优化与实证：{p['reviewed_evidence']}",f"- 后续条件：{p['next_step']}"]
        seeds=p['source_seed_locations']
        for r in seeds[:5]:lines.append('- 源码：'+link(r['path'],r['file']))
        for r in p.get('source_anchors',[])[:4]:
            lines.append('- 符号定位：'+link(r['path'],f"{r['symbol']} / {Path(r['file']).name}:{r['line']}",r['line']))
        if p.get('unresolved_source_seeds'):
            lines.append('- 未找到的预设文件名（不表示功能不存在）：'+', '.join(p['unresolved_source_seeds']))
        for n in tested:
            case=bench/'cases'/n
            lines.append('- 实例边界：'+STRUCTURAL_CASES.get(n,'直接调用固定版本真实库；参数与包装见 PatternStudy.scala。'))
            lines.append('- 实验证据：'+ ' · '.join([link(case/'rtl/Pattern.sv',n+' RTL'),link(case/'graph.json','frontend GRH'),link(case/'model/normalized.json','归一化 GRH'),
                link(case/'model','C++'),link(case/'assembly.txt','机器码'),link(case/'measurement.json','原始计时')]))
        lines.append('')
    generated=out/'generated_inventory.json'
    if generated.exists():
        g=json.loads(generated.read_text());lines+=['## 冻结香山生成包反向扫描','',
            f"扫描 {len(g['files'])} 个 schedule C++ 文件，共 {g['bytes']:,} 字节。所有统计保存在 generated_inventory.csv。",'',
            '| 分区 | 阶段 | batch | C++ 字节 | if | memory write helper | active 引用 |','|---|---|---:|---:|---:|---:|---:|']
        for r in sorted(g['files'],key=lambda r:-r['bytes'])[:20]:
            lines.append(f"| {r['part']} | {r['phase']} | {r['batch']} | {r['bytes']} | {r['if_count']} | {r['memory_write_helpers']} | {r['activation_mentions']} |")
        lines+=['','文件大小、分支数量和动态 batch 关联是筛查线索，不能证明某一 utility 单独消耗了该 batch 时间。','']
    compact=[]
    for p in cat['patterns']:
        compact.append({k:v for k,v in p.items() if k!='lexical_hits'})
    frozen_data=None
    if frozen_dir:
        frozen_dir=Path(frozen_dir).resolve()
        manifest=json.loads((frozen_dir/'manifest.json').read_text())
        for key in ['source','rtl','generated','binary','measurement']:
            if identity(manifest[key]['path'])['sha256']!=manifest[key]['sha256']:
                raise ValueError('changed frozen-example input: '+key)
        frozen_data=json.loads((frozen_dir/'measurement.json').read_text())
        import statistics
        extra=['','## 实际香山的分散槽位计数','',
            '原样抽取 p0 / compute batch 116 / group 928 的三个计数表达式，保留 18 个原始 bool slot 位置。',
            '穷举 262,144 种输入，另测两组各 100,000 个随机输入。预打包版本不包含打包成本，只是下界。','',
            '| 随机输入候选 | 原表达式 ns | 候选 ns |','|---|---:|---:|']
        for name in ['direct_sum','gather_popcount','packed_lower_bound']:
            rs=[r for r in frozen_data['samples'] if r['variant']==name and r['distribution']=='random']
            extra.append(f"| {name} | {statistics.median(r['tree_ns'] for r in rs):.3f} | {statistics.median(r['candidate_ns'] for r in rs):.3f} |")
        lines+=extra
    crc_data=None
    if crc_dir:
        crc_dir=Path(crc_dir).resolve()
        manifest=json.loads((crc_dir/'manifest.json').read_text())
        for record in [manifest['binary'],manifest['measurement'],*manifest['source_inputs'],*manifest['generated']]:
            if identity(record['path'])['sha256']!=record['sha256']:
                raise ValueError('changed CRC control input: '+record['path'])
        control=json.loads((crc_dir/'measurement.json').read_text())
        crc_data=dict(summary=summarize_control(control),path=str(crc_dir),verified_vectors=control['verified_vectors'])
        lines+=['','## CRC 共同调用循环复核：原结论的限制','',
            '原独立实验两个 CRC 例子的生成计算体源码相同，但其基线时间不同。新增同一 binary、共同间接调用循环的对照，保留原生成体，比较位串行与查表。',
            '新实验另检查 1,000,000 个向量，五种分布各 8 对 AB/BA。查表不再优于生成体；当前不推荐据原百分比直接改写 CRC。根因尚未归因到具体微架构事件。','',
            '| 分布 | 候选 | 生成体 ns | 软件 ns | 配对变化 |','|---|---|---:|---:|---:|']
        for r in crc_data['summary']:
            lines.append(f"| {r['distribution']} | {r['variant']} | {r['generated_ns']:.3f} | {r['candidate_ns']:.3f} | {r['delta_percent']:+.1f}% |")
        lines+=['',link(crc_dir/'manifest.json','共同调用实验身份')+' · '+link(crc_dir/'assembly.txt','机器码')+' · '+link(crc_dir/'measurement.json','逐对计时'),'']
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    save(out/'report.json',dict(schema_version=2,coverage={k:v for k,v in inv.items() if k!='files'},
                              patterns=cat['patterns'],benchmarks=measurements,frozen=frozen_data,crc_control=crc_data))
    with (out/'findings.csv').open('w') as f:
        fields=['id','title','disposition','hardware_intent','reviewed_evidence','next_step','semantic_boundary']
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(cat['patterns'])
    payload=dict(groups=inv['groups'],source_files=len(inv['files']),patterns=compact,cases=measurements,
        scopes=STRUCTURAL_CASES,total_verified=sum(r['verified_vectors'] for r in measurements.values()),
        frozen=frozen_data,crc_control=crc_data,
        environment=json.loads((bench/'environment.json').read_text()),
        result_csv=str(bench/'results.csv'),coverage_csv=str(out/'coverage.csv'),findings_csv=str(out/'findings.csv'))
    payload['wrapper_path']=str(ROOT/'testcase/chisel-pattern-study/PatternStudy.scala')
    payload['design_path']=str(ROOT/'wolvrix/docs/emit/chisel-semantic-simulation.md')
    template=(ROOT/'scripts/chisel_pattern_report.html').read_text()
    if template.count('__STUDY_DATA__')!=1:raise ValueError('HTML payload marker mismatch')
    (out/'report.html').write_text(template.replace('__STUDY_DATA__',json.dumps(payload,ensure_ascii=False).replace('<','\\u003c')))
    save(out/'report_inputs.json',dict(
        sources=[identity(ROOT/'scripts'/name) for name in ['chisel_pattern_study.py','chisel_pattern_catalog.py',
            'chisel_pattern_findings.py','chisel_pattern_results.py','chisel_pattern_crc_control.py','chisel_pattern_report.html']],
        inputs=[identity(out/name) for name in ['inventory.json','catalog.json']]+[identity(bench/'validated_results.json')],
        frozen_manifest=identity(Path(frozen_dir)/'manifest.json') if frozen_dir else None,
        crc_manifest=identity(Path(crc_dir)/'manifest.json') if crc_dir else None))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['survey','generated','operations','report','all'])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--bench',type=Path,required=True)
    p.add_argument('--frozen',type=Path,help='Optional explicitly selected frozen-count experiment')
    p.add_argument('--crc-control',type=Path,help='Optional common-call-loop CRC follow-up')
    p.add_argument('--build',type=Path,default=DEFAULT_BUILD)
    p.add_argument('--chisel-sources',type=Path,default=Path('/nfs/home/tanghaojin/.cache/coursier/v1/https/repo1.maven.org/maven2/org/chipsalliance/chisel_2.13/7.3.0/chisel_2.13-7.3.0-sources.jar'))
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if args.command in ['survey','all']:
        inv,cat=survey(out,args.chisel_sources);print('SCANNED',len(inv),'files',len(cat),'patterns',flush=True)
    if args.command in ['generated','all']:
        rows=generated_evidence(out,args.build.resolve());print('GENERATED',len(rows),flush=True)
    if args.command in ['operations','all']:operation_evidence(out,args.build.resolve())
    if args.command in ['report','all']:report(out,args.bench.resolve(),args.frozen,args.crc_control);print('REPORT',out/'report.md',flush=True)


if __name__=='__main__':main()
