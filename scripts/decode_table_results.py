#!/usr/bin/env python3
"""Render Chinese case cards and paired results from a completed decode study."""
import argparse
import csv
import json
from pathlib import Path
import re
import random
import statistics
import subprocess

from grhsim_single_baseline import save


def code_size(case):
    result={}
    for variant in ('A','B'):
        output=subprocess.check_output(['size','-A',str(Path(case)/variant/'bench')],text=True)
        sections={name:int(n) for name,n in re.findall(r'^(\.\S+)\s+(\d+)\s+\d+',output,re.M)}
        result[variant]={name:sections.get(name,0) for name in ('.text','.rodata','.data','.bss')}
    return result


def purpose(name):
    if name.endswith('_Ifu'):
        return '把普通与压缩指令归类为非分支、条件分支、直接或间接跳转；RAS 动作仍由外部原逻辑计算。'
    if name.endswith('_RobImp'):
        return '将退休数量编码还原为退休半字数量或指令数量；两张表用途不同，已消除的表单独记录。'
    if name.endswith('_DecodeUnit'):
        return '将 32 位指令映射为源类型、功能单元、操作类型、写回／流水线控制、微操作拆分和立即数选择等 14 个字段。'
    if name.endswith('_indexedLSUopTable'):
        return '根据 EMUL、LMUL 和实例固化的 uopIdx，计算向量索引访存的两个寄存器偏移。'
    if 'LSNumOfUopTable' in name:
        return '根据向量组倍率与分段数，得到本指令的微操作数量；超出源码表规定范围时保留其确定性零值。'
    if name.endswith('_CompressUnit'):
        return '这是 Rename 的 ROB 压缩分组控制表，生成 needRob、instrSize 和 masks；不是 RISC-V 压缩指令扩展器。'
    if name.endswith('_Rename'):
        return '将当前指令组大小和非压缩指令数量编码，供 ROB 的退休信息使用。'
    if name.endswith('_PrivilegePermitModule'):
        return '根据虚拟化状态、当前权限和 CSR 地址权限位，检查常规 CSR 访问权限。'
    if 'Fli' in name:
        return '浮点立即数常量表；不同精度对应不同常量编码。'
    if name.endswith('_VIAluDecoder'):
        return '向量整数执行单元的操作与类型控制译码。'
    return '整数／浮点／向量转换指令的局部操作控制译码；精确输入位和表项见捕获载荷及源码。'


def generate(build, local, comparison='comparison-v1'):
    build, local = Path(build).resolve(), Path(local).resolve()
    whole = json.loads((build/comparison/'summary.json').read_text())
    coverage = json.loads((build/'coverage.json').read_text())
    chain = {r['table_id']:r for r in json.loads((build/'source_chain.json').read_text())}
    cases = json.loads((local/'cases.json').read_text())
    if whole['pairs'] != 8 or len(cases) != len(coverage['tables']):
        raise ValueError('incomplete required measurements')
    rows=[];cards=[]
    distributions=dict(random='随机',matched='表项命中',dense='密集置位',toggle1='单比特变化',
                       hold99='99% 保持',unmatched='表项未命中',committed='真实有效提交槽')
    for c in cases:
        table = chain[c['table_id']]
        directory = Path(c['output'])
        summary = json.loads((directory/'summary.json').read_text())
        if summary['status'] != 'pass':
            raise ValueError('case environment did not pass')
        samples = json.loads((directory/'pairs.json').read_text())
        for r in summary['measurements']:
            if r['pairs'] != 8:
                raise ValueError('missing case pairs')
            selected=[x for x in samples if x['distribution']==r['distribution'] and x['mode']==r['mode']]
            if len(selected)!=8 or [x['order'] for x in selected]!=['AB','BA']*4:
                raise ValueError('wrong case pair order')
            rng=random.Random(20261103)
            deltas=[x['delta_percent'] for x in selected]
            boot=sorted(statistics.mean(rng.choices(deltas,k=8)) for _ in range(10000))
            r['delta_percent_ci95']=[boot[249],boot[9749]]
            rows.append(dict(table_id=c['table_id'],name=c['name'],**r))
        cards.append(dict(**c,structure=table,purpose=purpose(c['name']),code_size=code_size(c['case']),measurements=summary['measurements'],
                          verification=json.loads((Path(c['case'])/'verification.json').read_text())))
    save(build/'results.json',dict(whole=whole,cases=cards,local_scope='Standalone replay of captured real tables',
        conventions='Negative B/A-1 means faster; local timings do not establish whole-model attribution'))
    fields=['name','table_id','distribution','mode','pairs','A_ns_median','B_ns_median',
            'delta_percent_mean','delta_percent_median','delta_percent_ci95','B_faster_pairs']
    with (build/'local_results.csv').open('w') as f:
        w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)
    ci=whole['delta_percent_ci95']
    text=['# 香山译码表 intrinsic：实证结果','',
        f"整机 8 对 AB/BA 的配对变化均值为 **{whole['delta_percent_mean']:+.3f}%**（B/A−1，负值表示 B 更快），"
        f"95% 配对 bootstrap 区间为 [{ci[0]:+.3f}%, {ci[1]:+.3f}%]。"
        f"B 在 {whole['candidate_faster_pairs']}/8 对中更快。",
        f"A 平均 {whole['baseline_s_mean']:.3f} 秒，B 平均 {whole['candidate_s_mean']:.3f} 秒；主指标为 Host time spent。",
        '', '## 条件与覆盖','',
        'TLConfig、CoreMark 2 iteration、专用单模型单线程、node030 CPU96、NUMA node1，'
        'Clang 23.1.2 默认 SLP。两侧四层 DiffTest 均开启。预热后正式 -C 100000，诊断和轨迹关闭，测量期间没有本实验的构建。',
        '', '106 次源码 elaboration 调用，70 次选择原语，36 次 PreDecode 调用因 WireInit 推迟位宽推导保留原实现。'
        '24 张不同表全部局部验证／测量；整机优化后保留 23 张表、62 个纯组合操作。'
        '第三方内部调用未替换，未实例化接口、回退和原始源码扫描见 coverage.json。',
        '', '两组种子各 100,000 条有效 DiffTest 记录逐条一致。小输入表穷举，较大表两组各至少 100,000 个向量，并加入逐行命中和边界样本。'
        '验证 care_mask 来自原表，不由 A/B 输出差异推导。二态有限样本验证不等同于形式证明。',
        '', '局部 A/B 是捕获原始表后独立生成的模型；kernel 包括计算主体与端口读写，full 包括 eval 调度及变化检测。'
        '因此局部 ns 和整机秒数不可相加归因。实际提交槽分布保留顺序，但不恢复融合指令中未记录的其他指令，也不覆盖推测译码输入。',
        '', '## 全部整机样本','',
        '| 配对 | 顺序 | A / 秒 | B / 秒 | B/A−1 |','|---:|---|---:|---:|---:|']
    for p in whole['samples']:
        a,b=p['A']['host_ms']/1000,p['B']['host_ms']/1000
        text.append(f"| {p['pair']} | {''.join(p['order'])} | {a:.3f} | {b:.3f} | {100*(b/a-1):+.3f}% |")
    text += ['', '## 逐表案例','']
    for card in cards:
        s=card['structure'];cg=s.get('codegen',{})
        text += [f"### {card['name']}", '',
            card['purpose'], '',
            f"输入 {s['input_width']} 位，输出 {s['output_width']} 位，{s['rows']} 行；"
            f"elaboration {s['instances']} 次，完整 GRH 保留 {s['flat_operation_count']} 个操作。",
            f"模式：{'首项优先' if s['mode']=='P' else '匹配约束合并'}；字段宽度：`{s['fields']}`。",
            f"后端：{('LUT' if cg.get('dense') else '共同 mask 分层匹配') if cg else '整机已消除'}；"
            f"结构统计：`{cg}`。",'', 'Chisel 来源：','']
        for site in sorted({(x['source'],x['module_class']) for x in s['sites']}):
            text.append(f'- `{site[1]}`：`{site[0]}`')
        text += ['',f"完整 RTL／GRH／C++ 行映射：`source_chain.json` 中 `{s['table_id']}`。",
            f"局部 ELF 段字节（含验证与计时 harness）：`{card['code_size']}`。",
            f"局部 SV／GRH／C++／汇编和验证输入：`{card['case']}`。",
            f"全部配对样本和运行中 NUMA 证据：`{card['output']}`。",'',
            '| 分布 | 范围 | A 中位 ns | B 中位 ns | 配对变化中位数 | B 更快对数 |',
            '|---|---|---:|---:|---:|---:|']
        for r in card['measurements']:
            text.append(f"| {distributions[r['distribution']]} | {r['mode']} | {r['A_ns_median']:.3f} | {r['B_ns_median']:.3f} | {r['delta_percent_median']:+.2f}% | {r['B_faster_pairs']}/8 |")
        text.append('')
    text += ['## 复现与证据','',
        '```bash', 'python3 scripts/grhsim_decode_table_study.py build --output build/xs/decode_table_new --jobs 32',
        'python3 scripts/grhsim_decode_table_study.py measure --output build/xs/decode_table_new',
        'python3 scripts/decode_table_replay.py --manifest build/xs/decode_table_new/B/chisel-home/build/simulation_primitives.json --output wolvrix/build/artifacts/decode_table_new',
        'python3 scripts/decode_table_measure.py --case <案例目录> --output <新测量目录>', '```','',
        '整机构建／测量与局部测量入口在 node030 执行，局部构建可使用同 CPU 特征的构建机。'
        '正式测量应串行，固定 CPU96。实际命令、源码和工具身份、全部成功样本及失败尝试均保留在对应目录。','']
    (build/'report.md').write_text('\n'.join(text))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,required=True);p.add_argument('--local',type=Path,required=True)
    p.add_argument('--comparison',default='comparison-v1')
    args=p.parse_args();generate(args.build,args.local,args.comparison)
