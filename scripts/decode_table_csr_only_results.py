#!/usr/bin/env python3
"""Report the inverse ablation: restore CSR lowering, disable uniform-table folding."""
import argparse
import json
from pathlib import Path

from grhsim_single_baseline import identity, save


def generate(output):
    output = Path(output).resolve()
    summary = json.loads((output/'comparison/summary.json').read_text())
    structure = json.loads((output/'ablation_structure.json').read_text())
    if len(summary['samples']) != 8 or len(summary['trace_checks']) != 4 or not all(structure['gates'].values()):
        raise ValueError('incomplete experiment or structural gate')
    for trace in summary['trace_checks']:
        if not trace['pass_'] or trace['records'] != 100000:
            raise ValueError('functional trace mismatch')
    for row in summary['samples']:
        for name in 'BCE':
            r = row[name]
            if not r['locality_pass'] or r['cpu'] != 96 or r['max_threads'] != 1 or r['diagnostic']:
                raise ValueError('invalid measurement')
            if r['runtime_difftest'] != 'on' or r['numa_node'] != 1:
                raise ValueError('unexpected measurement configuration')
            if any(float(v) < 98 for cpu, v in r['sibling_idle'].items() if str(cpu) != '96'):
                raise ValueError('SMT sibling busy')
    labels = dict(B='旧 intrinsic，两项后续优化均无', C='常量表提前折叠＋CSR 优化',
                  E='仅 CSR 优化；动态恒定表提前折叠关闭')
    result = dict(variants=labels, whole=summary, structure=structure, driver=identity(__file__))
    for name in ('object_text_comparison.json', 'csr_machinecode.json'):
        if (output/name).exists():
            result[name.removesuffix('.json')] = json.loads((output/name).read_text())
    save(output/'results.json', result)
    ec, eb = summary['pairwise']['E_vs_C'], summary['pairwise']['E_vs_B']
    text = ['# 恢复 CSR、关闭恒定表提前折叠：复测结果', '',
            f"关闭恒定表提前折叠后，E/C配对均值为 {ec['delta_percent_mean']:+.3f}%，"
            f"{ec['candidate_faster_pairs']}/8组更快；E/B均值为 {eb['delta_percent_mean']:+.3f}%，"
            f"{eb['candidate_faster_pairs']}/8组更快。", '',
            '本轮E相对C稳定恢复性能，而E相对旧B的配对区间跨零，不能宣称CSR单独产生明确整机加速。'
            '当前源码保持CSR开启、动态恒定表提前折叠关闭。', '', '## 版本定义', '']
    text += [f'- {name}：{label}。' for name, label in labels.items()]
    text += ['', '只关闭新增的动态输入恒定表识别，普通常量输入求值、其他常量传播、CSE/DCE均保留。'
             'Chisel调用、冻结RTL、编译选项和替换范围不变。当前源码为E状态，默认开关仍为none。', '',
             '## 整机结果', '',
             'Wolvrix专用单模型单线程，node030 CPU96、NUMA node1，CPU288空闲检查。'
             'TLConfig/CoreMark、Clang23.1.2、默认SLP，四层DiffTest开启。各版独立smoke/预热后，'
             '按预定顺序各八次C100000；正式运行无诊断和轨迹，不并行构建。', '',
             '| 比较 | 基线平均秒 | 候选平均秒 | 配对均值变化 | 配对中位变化 | 95%配对区间 | 候选更快 |',
             '|---|---:|---:|---:|---:|---|---:|']
    for name, r in summary['pairwise'].items():
        ci = r['delta_percent_ci95']
        text.append(f"| {name} | {r['baseline_s_mean']:.3f} | {r['candidate_s_mean']:.3f} | "
                    f"{r['delta_percent_mean']:+.3f}% | {r['delta_percent_median']:+.3f}% | "
                    f"[{ci[0]:+.3f}%, {ci[1]:+.3f}%] | {r['candidate_faster_pairs']}/8 |")
    text += ['', '负值表示候选更快。区间是固定种子的配对bootstrap，不排除系统性环境因素。'
             '所有样本保留，不按速度删样。每轮外部walltime及运行中页面/线程证据另存于runs目录。', '',
             '第6轮B完成后，C/E耗时同时下降至约95秒，第7轮也处在较快区间。'
             '亲和性、NUMA和sibling检查均通过，原因未单独测定；时间漂移可能影响配对幅度，'
             '尤其E/B均值，不将全部差异归为代码收益，也不删除这两轮。', '',
             '| 轮次 | 顺序 | B秒 | C秒 | E秒 | E/B−1 | E/C−1 |',
             '|---:|---|---:|---:|---:|---:|---:|']
    for r in summary['samples']:
        b, c, e = (r[v]['host_ms']/1000 for v in 'BCE')
        text.append(f"| {r['pair']} | {''.join(r['order'])} | {b:.3f} | {c:.3f} | {e:.3f} | "
                    f"{100*(e/b-1):+.3f}% | {100*(e/c-1):+.3f}% |")
    text += ['', '## 结构与正确性', '',
             f"B/E的前置GRH、全部{structure['compared_cpp_files']}个生成C++文件、状态存储声明和调度统计完全一致。"
             'runtime header只有CSR helper变化，E的helper与C完全相同。E/B是原布局上CSR发射的单项比较；'
             'E/C则包含恒定表提前折叠及其后端形态变化。', '',
             '129个对象中128个.text相同，仅CSR所在sched_17.o增加4字节；完整ELF.text增加16字节。'
             'B/E译码操作均为62个，C为61个；禁用恒定表提前折叠确实恢复了旧图和调度布局。', '',
             '真实fixture中，恒零表E恢复B的动态依赖和机器码，CSR E保持C的机器码。'
             '两组固定输入复验和native decode-table/CTZ通过；普通常量输入折叠仍正常。'
             '完整E两组各100,000条有效DiffTest记录分别与B/C比较，四项通过，覆盖数量、顺序、有效状态和周期字段。', '',
             '复用原轨迹前核验binary、NEMU、负载、schema及依赖库身份。B/C在本轮重新计时，未使用历史均值当分母。', '',
             '## 解释边界与产物', '',
             '不能将E/C差异直接归为少算一次表：恒定表消除会改变调度和布局。'
             'E/B仅改变CSR helper的生成选择，但C++编译后的寄存器分配和代码布局仍可能变化。'
             '本轮没有重新测全部24张局部表，也没有新增调用筛选策略。', '',
             '`comparison/triads.csv`、`comparison/summary.json`保存全部样本；'
             '`ablation_structure.json`保存结构检查和二进制身份；'
             '`results.json`为完整结果。构建/测量入口为`scripts/decode_table_csr_only.py`，'
             '证据检查入口为`decode_table_csr_only_evidence.py`。', '']
    (output/'report.md').write_text(chr(10).join(text))
    print(json.dumps(summary['pairwise']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    generate(parser.parse_args().output)
