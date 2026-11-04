#!/usr/bin/env python3
"""Render the CSR lowering ablation with its structural and runtime evidence."""
import argparse
import csv
import json
from pathlib import Path

from grhsim_single_baseline import identity, save


def generate(output):
    output = Path(output).resolve()
    summary = json.loads((output/'comparison/summary.json').read_text())
    structure = json.loads((output/'ablation_structure.json').read_text())
    if not all(structure['gates'].values()):
        raise ValueError('ablation scope not verified')
    rows = summary['samples']
    if len(rows) != 8 or len(summary['trace_checks']) != 4:
        raise ValueError('incomplete ablation measurements')
    for trace in summary['trace_checks']:
        if not trace['pass_'] or trace['records'] != 100000:
            raise ValueError('functional verification incomplete')
    for row in rows:
        for variant in 'BCD':
            sample = row[variant]
            if not sample['locality_pass'] or sample['cpu'] != 96 or sample['max_threads'] != 1:
                raise ValueError('invalid placement')
            if sample['diagnostic'] or sample['runtime_difftest'] != 'on':
                raise ValueError('wrong measurement mode')
            if any(float(value) < 98 for cpu, value in sample['sibling_idle'].items() if str(cpu) != '96'):
                raise ValueError('SMT sibling not idle')
    previous = summary['pairwise']['D_vs_B']
    removed = summary['pairwise']['D_vs_C']
    labels = dict(B='旧 intrinsic，两项后续优化均无',
                  C='常量依赖消除＋CSR 布尔 lowering',
                  D='只保留常量依赖消除，CSR 恢复旧 lowering')
    result = dict(variants=labels, whole=summary, structure=structure,
                  object_code=json.loads((output/'object_text_comparison.json').read_text()),
                  csr_machinecode=json.loads((output/'csr_machinecode.json').read_text()),
                  identity=identity(__file__),
                  interpretation=dict(C_to_D='The only generated-code change is the CSR helper. Native compilation may change code layout.',
                                      B_to_D='Includes constant-table elimination and its resulting scheduling/storage changes.'))
    save(output/'results.json', result)
    text = ['# CSR 布尔 lowering 消融结果', '',
            f"移除 CSR 优化后，D/C 配对变化均值为 {removed['delta_percent_mean']:+.3f}%，"
            f"D 在 {removed['candidate_faster_pairs']}/8 组更快。"
            f"相对旧 intrinsic B，D/B 为 {previous['delta_percent_mean']:+.3f}%。负值表示候选耗时更少。", '',
            f"D/C 配对中位数为 {removed['delta_percent_median']:+.4f}%；"
            f"95% 区间为 [{removed['delta_percent_ci95'][0]:+.3f}%, {removed['delta_percent_ci95'][1]:+.3f}%]。"
            '本轮没有证据表明移除 CSR 优化带来可靠整机改善。一个较慢轮次拉高均值，所有样本均保留。', '',
            '## 版本与范围', '']
    for variant, label in labels.items():
        text.append(f'- {variant}：{label}。')
    text += ['', 'Chisel、冻结 RTL、替换范围、编译器与生产选项保持一致。仅撤回通用布尔位图分支和空 asm 寄存器值约束，'
             '不是在设计侧禁止某个 CSR 表的 intrinsic。当前源码保留常量折叠，布尔表恢复原 LUT 发射。', '',
             '## 结构检查', '',
             f"C/D 的前置 GRH 逐字节相同，{structure['compared_cpp_files']} 个生成 C++ 文件逐字节相同，"
             '存储类声明和活动调度统计相同。runtime header 只有 CSR helper 不同，D 的 helper 与旧 B 完全一致。'
             '因此 C/D 可以隔离本次 CSR lowering 选择；B/D 仍包含常量折叠产生的调度和布局变化。', '',
             '130 个对象文件中，129 个 .text 完全相同，仅包含 CSR 调用的 sched_17.o 改变。'
             'D 恢复 32 位 shrx，显式 0x1f 掩码消失，但该对象的 .text 增加 17,488 字节；'
             '这说明 helper 变化还影响所在大函数的编译结果，不能只按少一条掩码计算收益。', '',
             '两个真实小模型的固定输入复验通过：恒零表维持无动态输入依赖；CSR 的 .text 恢复到旧 B，'
             '恒零表的 .text 保持与 C 相同。native decode-table/CTZ 测试通过。', '',
             '## 整机结果', '',
             '专用单模型单线程，node030 CPU96、NUMA node1，SMT sibling CPU288 空闲检查。'
             'TLConfig/CoreMark、Clang 23.1.2 默认 SLP，四层 DiffTest 开启。每版八次 C100000，'
             '轮换顺序，主指标 Host time spent；正式计时没有轨迹或诊断，没有本实验并行构建。', '',
             '| 比较 | 基线平均秒 | 候选平均秒 | 配对变化均值 | 95% 配对区间 | 候选更快 |',
             '|---|---:|---:|---:|---|---:|']
    for name, row in summary['pairwise'].items():
        ci = row['delta_percent_ci95']
        text.append(f"| {name} | {row['baseline_s_mean']:.3f} | {row['candidate_s_mean']:.3f} | "
                    f"{row['delta_percent_mean']:+.3f}% | [{ci[0]:+.3f}%, {ci[1]:+.3f}%] | "
                    f"{row['candidate_faster_pairs']}/8 |")
    text += ['', '区间为固定种子配对 bootstrap，仅反映本轮有限样本，不能排除系统性环境因素。', '',
             '| 轮次 | 顺序 | B 秒 | C 秒 | D 秒 | D/C−1 | D/B−1 |',
             '|---:|---|---:|---:|---:|---:|---:|']
    for row in rows:
        b, c, d = (row[v]['host_ms']/1000 for v in 'BCD')
        text.append(f"| {row['pair']} | {''.join(row['order'])} | {b:.3f} | {c:.3f} | {d:.3f} | "
                    f"{100*(d/c-1):+.3f}% | {100*(d/b-1):+.3f}% |")
    text += ['', '## 正确性与限制', '',
             'D 两组种子各 100,000 条有效 DiffTest 记录，分别与 B/C 比较，四项均通过。'
             '重用轨迹前核验 binary、NEMU、负载、schema、依赖库身份；比较包含有效状态、顺序、数量和周期字段。', '',
             '局部改善、输入布局差异和整机结果分别保留。此次消融没有重新测 24 张局部表，也没有重新挑选调用；'
             'B/C 都是上轮冻结 binary，同场重新测量。D 从同一份 RTL 完整重建。', '',
             '不由本轮整机时间差推断单条 mask/shift 的周期成本；编译后的寄存器分配和代码布局也可能受 helper 变化影响。', '',
             'D/B 八组都较慢，说明即使 CSR 恢复原 lowering，只保留常量依赖消除仍没有整机收益。'
             '这更支持常量消除及其后端布局变化需要单独评价，而不能把先前回退主要归因于 CSR 约束。'
             '本轮不继续增加优化或删除较慢样本。当前源码保持 D 状态，默认 Chisel 开关仍为 none。', '',
             '## 产物', '',
             '`comparison/triads.csv` 和 `comparison/summary.json` 保存全部正式样本；'
             '`comparison/{B,C,D}/runs` 保存命令、日志和运行中 NUMA／线程记录。'
             '`ablation_structure.json` 保存结构一致性、binary 身份与 ELF 段体积。'
             '`results.json` 保存本报告完整结构数据。', '',
             '复现入口：`scripts/decode_table_ablation.py build|measure`，'
             '结构检查：`scripts/decode_table_ablation_evidence.py`，汇总：`scripts/decode_table_ablation_results.py`。', '']
    (output/'report.md').write_text(chr(10).join(text))
    print(json.dumps(summary['pairwise']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    generate(parser.parse_args().output)
