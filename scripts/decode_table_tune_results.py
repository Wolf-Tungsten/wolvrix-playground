#!/usr/bin/env python3
"""Summarize the frozen hardware / previous intrinsic / tuned intrinsic study."""
import argparse
import csv
import json
from pathlib import Path
import random
import re
import statistics

from grhsim_single_baseline import identity, save


def interval(deltas):
    rng = random.Random(20261103)
    samples = sorted(statistics.mean(rng.choices(deltas, k=len(deltas)))
                     for _ in range(10000))
    return [samples[249], samples[9749]]


def generate(build, source, structure):
    build, source = Path(build).resolve(), Path(source).resolve()
    whole = json.loads((build/'comparison/summary.json').read_text())
    if len(whole['samples']) != 8 or len(whole['trace_checks']) != 4:
        raise ValueError('incomplete whole-model comparison')
    for check in whole['trace_checks']:
        if not check['pass_'] or check['records'] != 100000:
            raise ValueError('incomplete functional trace comparison')
    model = json.loads((build/'structure.json').read_text())
    original_tables = {r['table_id']: r for r in json.loads((source/'source_chain.json').read_text())}
    symbols = {r['cpp_symbol']: r for r in model['tables']}
    for row in symbols.values():
        row['cpp'] = []
        row.update({key: original_tables[row['table_id']][key]
                    for key in ('mode', 'input_width', 'output_width', 'fields', 'rows', 'instances', 'selected')})
    for path in sorted((build/'C/model').glob('*')):
        if path.suffix not in ('.cpp', '.hpp'):
            continue
        with path.open() as stream:
            for number, line in enumerate(stream, 1):
                if 'grhsim_decode_' not in line:
                    continue
                for symbol in set(re.findall(r'\b(grhsim_decode_[0-9a-f]+)\(', line)):
                    symbols[symbol]['cpp'].append(dict(file=str(path), line=number,
                        kind='definition' if path.suffix == '.hpp' else 'call'))
                match = re.search(r'// decode-stats (\w+) (.*)', line)
                if match:
                    symbols[match[1]]['codegen'] = {
                        key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match[2])}
    save(build/'source_chain.json', model['tables'])
    catalog = json.loads((build/'local-measure/cases.json').read_text())
    prior = {r['name']: r for r in json.loads((source/'local-measure-v1/cases.json').read_text())}
    code = {r['name']: r for r in json.loads(Path(structure).read_text())}
    if len(catalog) != 24 or set(prior) != {r['name'] for r in catalog}:
        raise ValueError('local table coverage changed')
    rows, cards = [], []
    for case in catalog:
        directory = Path(case['output'])
        summary = json.loads((directory/'summary.json').read_text())
        raw = json.loads((directory/'pairs.json').read_text())
        if summary['status'] != 'pass':
            raise ValueError('local environment rejected')
        measurements = []
        for row in summary['measurements']:
            selected = [r for r in raw if (r['distribution'], r['mode']) ==
                        (row['distribution'], row['mode'])]
            if len(selected) != 8 or [r['order'] for r in selected] != ['AB', 'BA'] * 4:
                raise ValueError('missing local samples or wrong order')
            if any(not r[v]['locality_pass'] for r in selected for v in ('A', 'B')):
                raise ValueError('locality check failed')
            delta = [r['delta_percent'] for r in selected]
            renamed = dict(name=case['name'], table_id=case['table_id'],
                           distribution=row['distribution'], mode=row['mode'], pairs=8,
                           previous_intrinsic_ns_median=row['A_ns_median'],
                           tuned_intrinsic_ns_median=row['B_ns_median'],
                           delta_percent_mean=statistics.mean(delta),
                           delta_percent_median=statistics.median(delta),
                           delta_percent_ci95=interval(delta),
                           tuned_faster_pairs=sum(x < 0 for x in delta))
            measurements.append(renamed)
            rows.append(renamed)
        historical = json.loads((Path(prior[case['name']]['output'])/'summary.json').read_text())
        cards.append(dict(**case, structure=code[case['name']], measurements=measurements,
                          target_ms=json.loads((directory/'random-kernel-calibration.json').read_text())['target_ns']/1000000,
                          historical_hardware_vs_previous_intrinsic=historical['measurements'],
                          verification=json.loads((Path(case['case'])/'verification.json').read_text())))
    result = dict(whole=whole, cases=cards, model_structure=model,
                  full_model_csr=json.loads((build/'csr_full_model_codegen.json').read_text()),
                  binary_structure=json.loads((build/'binary_structure.json').read_text()),
                  local_protocol=json.loads((build/'local-measure/protocol_update.json').read_text()),
                  rejected_local_pairs=[str(p) for p in sorted((build/'local-measure').glob('*/*.rejected-pair.json'))],
                  rejected_local_attempts=[str(p) for p in sorted((build/'local-measure').glob('*/rejected-attempt.json'))],
                  local_pairs=sum(r['pairs'] for r in rows),
                  labels=dict(whole=dict(A='original hardware RTL', B='previous intrinsic', C='tuned intrinsic'),
                              local=dict(A='previous intrinsic', B='tuned intrinsic')),
                  identities=dict(driver=identity(__file__), structure=identity(structure)),
                  limits='Historical local hardware figures are context only, not simultaneous pairs. '
                         'Local ns cannot be added to infer whole-model seconds; fixed workload and two-state semantics.')
    save(build/'results.json', result)
    fields = list(rows[0])
    with (build/'local_results.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)
    text = ['# 译码表后端调整：复测结果', '',
            f"调整版相对上一版 intrinsic 的整机配对变化为 {whole['pairwise']['C_vs_B']['delta_percent_mean']:+.3f}%，"
            f"{whole['pairwise']['C_vs_B']['candidate_faster_pairs']}/8 组更快；负值才表示改善。"
            '本轮局部机制修复与整机收益必须分别评价。', '',
            '调整包括：在 GRH 中消除确定为常量的表及其输入依赖；将一个机器字可容纳的'
            '布尔表直接生成为位图，并避免 Clang/x86 的窄输入读取扩大。'
            '未修改 Chisel 调用、替换范围或生产编译选项。', '',
            '## 同场整机测量', '',
            'A=原硬件 RTL，B=上一版 intrinsic，C=调整版。专用单模型单线程，node030 CPU96，'
            'NUMA node1，TLConfig/CoreMark，四层 DiffTest 开启，默认 SLP。'
            '每版 8 次 C100000，轮换顺序；主指标 Host time spent，正式运行不带诊断或轨迹。', '',
            '| 对比 | 基线平均秒 | 候选平均秒 | 配对变化均值 | 95% 配对区间 | 候选更快 |',
            '|---|---:|---:|---:|---|---:|']
    for key, row in whole['pairwise'].items():
        ci = row['delta_percent_ci95']
        text.append(f"| {key} | {row['baseline_s_mean']:.3f} | {row['candidate_s_mean']:.3f} | "
                    f"{row['delta_percent_mean']:+.3f}% | [{ci[0]:+.3f}%, {ci[1]:+.3f}%] | "
                    f"{row['candidate_faster_pairs']}/8 |")
    text += ['', '负值表示候选更快。区间采用固定种子的配对 bootstrap，不能排除系统性环境影响。'
             '所有样本、外部 walltime、文件页与匿名页归属、亲和性和 SMT sibling 记录均保留。', '',
             '| 轮次 | 顺序 | A 秒 | B 秒 | C 秒 | C/B−1 |',
             '|---:|---|---:|---:|---:|---:|']
    for row in whole['samples']:
        a, b, c = (row[v]['host_ms']/1000 for v in 'ABC')
        text.append(f"| {row['pair']} | {''.join(row['order'])} | {a:.3f} | {b:.3f} | {c:.3f} | {100*(c/b-1):+.3f}% |")
    text += ['', '## 功能与结构', '',
             '24 张表复用原始捕获 RTL 和验证输入；每张表两组固定输入全部通过。'
             '调整版整机用两个种子各 100,000 条有效 DiffTest 记录，分别与已核验身份的原硬件和旧 intrinsic 轨迹比较，四项全部通过。', '',
             f"整机化简后的表操作由 {model['prior_operations']} 个降为 {model['operations']} 个，"
             f"不同表由 {model['prior_unique']} 张降为 {model['unique']} 张。"
             '被消除的是恒零索引表；Chisel 选择范围保持不变。`source_chain.json` 保存本轮 GRH/C++ 及原始 Chisel 调用对应关系。', '',
             f"局部模型中 {sum(c['structure']['text_identical'] for c in cards)}/24 个 ELF 的 .text 与上一版逐字节相同。"
             '两张改变的是恒零 indexedLSUopTable 与 CSR 权限表；全部 24 张仍做局部复测。', '',
             '## 两个已确认退化点', '',
             '下表对照旧 intrinsic 与调整版，包含正常 eval 的输入读取、结果写回、活动调度及变化检测。'
             '原硬件局部数据只在 JSON 中保留作历史背景，不把跨轮结果当作配对比较。', '',
             '| 表 | 分布 | 旧版 ns | 调整版 ns | 配对变化均值 | 更快对数 |',
             '|---|---|---:|---:|---:|---:|']
    for row in rows:
        if row['name'] not in ('03_indexedLSUopTable', '16_PrivilegePermitModule') or row['mode'] != 'full':
            continue
        text.append(f"| {row['name']} | {row['distribution']} | {row['previous_intrinsic_ns_median']:.3f} | "
                    f"{row['tuned_intrinsic_ns_median']:.3f} | {row['delta_percent_mean']:+.2f}% | "
                    f"{row['tuned_faster_pairs']}/8 |")
    text += ['', '## 局部与整机差异', '',
             '独立 CSR 模型的输入 byte 与输出及 eval 标志相邻，旧版扩宽读取与窄写重叠；'
             '调整版 movzbl 消除了这一形态。完整香山中，同一表输入由三个状态片段在寄存器中打包，'
             '旧版已使用常量位图与 32 位 shrx。新约束在完整模型里带来显式 0x1f 掩码和 64 位 shrx。', '',
             '常量表消除还会改变活动分组、字段偏移与代码布局。因此局部改善不等于整机进一步加速，'
             '也不能仅凭这段汇编把整机时间差归因给某条指令。完整代码证据在 csr_full_model_codegen.json。', '',
             '## 全部局部结果', '',
             f"总计 {result['local_pairs']} 对，保留无收益与退化。kernel 包含计算主体和端口读写，"
             'full 还包含正常 eval。两者均不是整机 walltime。', '',
             '前两张已完成表采用原 150 ms 目标时长；其余案例改为 300 ms，并延长校准，'
             '以应对短样本中 sibling 活动或页面观察不足的拒绝。环境标准不变，明确的环境拒绝才整对重跑，'
             '失败和部分配对全部保留，不按速度重试。各表的目标时长及输入周期记录在校准文件中。', '',
             '代码段相同的案例也存在百分之几差异，例如 CompressUnit 多个分布约下降 4%。'
             '本轮没有证据将这种差异归因于两处 lowering 改动，因此不把它记为新增优化收益；'
             '短微基准还受到放置、运行状态和测量变化影响，全部结果仍原样保留。', '',
             '| 表 | 范围 | 分布 | 旧版 ns | 调整版 ns | 配对变化均值 | 更快对数 |',
             '|---|---|---|---:|---:|---:|---:|']
    for row in rows:
        text.append(f"| {row['name']} | {row['mode']} | {row['distribution']} | "
                    f"{row['previous_intrinsic_ns_median']:.3f} | {row['tuned_intrinsic_ns_median']:.3f} | "
                    f"{row['delta_percent_mean']:+.2f}% | {row['tuned_faster_pairs']}/8 |")
    text += ['', '## 复现与原始证据', '',
             '`experiment.json` 固定原 RTL、工具与源码身份；`comparison/summary.json`、'
             '`comparison/triads.csv` 保存整机对照。`local-measure/*/pairs.json`、'
             '`*.audit.json` 保存每次局部测量和 NUMA 检查。`results.json` 与 `local_results.csv` 是完整汇总。', '',
             '```bash',
             'python3 scripts/decode_table_tune.py build --source <上一轮完整目录> --output <新目录> --jobs 32',
             'python3 scripts/decode_table_tune.py measure --source <上一轮完整目录> --output <新目录>',
             'python3 scripts/decode_table_tune_local.py --cases <原24表cases.json> --output <新案例目录>',
             'python3 scripts/decode_table_measure.py --case <新案例目录/表名> --output <新局部测量目录>',
             '```', '',
             '所有正式计时串行在 node030 CPU96 执行，构建先完成。历史原 RTL 与旧 intrinsic binary '
             '冻结；新版本从同一份经哈希验证的 Chisel 生成 RTL 重新导入、变换和编译。', '']
    (build/'report.md').write_text('\n'.join(text))
    print(json.dumps(dict(whole=whole['pairwise'], local_pairs=result['local_pairs']), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--structure', type=Path, required=True)
    args = parser.parse_args()
    generate(args.build, args.source, args.structure)
