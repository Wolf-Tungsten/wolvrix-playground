# TNO0369：新 RTL seed 7 与恢复版的直接 AB/BA

日期：2026-10-28。承接 [TNO0368 完整新流程结果](./TNO0368_grhsim_fresh_rtl_full_flow_result_20261028.md)。

## 对照与配置

用户要求将本轮新默认路线与恢复版直接比较。baseline 为此前保留的 `restored_historical_preset_current_emitter_20261026/harness/grhsim-compile/emu`，SHA-256 为 `0b5364eb70513c84f9705f9a84613b3cb81bbcc44e8c766ade8997cab05f5fdc`；与 [TNO0359](./TNO0359_grhsim_seed1_original_flags_restored_runtime_20261028.md) 使用的原始恢复版锚点相同。candidate 为本轮 fresh RTL、八份初解择优后的 seed 7 原始选项 ELF，SHA-256 为 `5ae949fed820d47f3287b27cff87338f1b9110f247d69a77259bcb25c0458d1d`。

两边都保留 SLP，模型为原始 O3/native 编译。ELF `.comment` 均包含 Clang **23.1.2**、LLVM revision `85ac560262434c9ccfc0c183ec22d4138ed647fb`。不重新编译或更改两边分配。

所有运行固定 node030 CPU96–127、C=100000、32 lanes、all-spin、preferred NUMA1、ASLR off。双方使用相同代码 THP preload 和进程内 collapse retry。正式运行前的 compute 入口对齐检查为 baseline 7,240/7,240、candidate 7,272/7,272，全部 64 字节对齐。

使用现有 `repcut_formal_zero_thp_compare.py`，连续执行两轮独立 8 对 AB/BA。每轮双方分别先做 C100 smoke，随后交错测量；保留所有功能成功样本，不删除慢样本或筛除离群值。两边二进制、workload image、NEMU 在各轮前后身份不变。

## Walltime 结果

| 测试 | 恢复版中位数 | 新 seed 7 中位数 | 逐对变化中位数 | 新线胜出 |
| --- | ---: | ---: | ---: | ---: |
| 第一轮 8 对 | 11.715 s | 12.860 s | +9.833% | 0/8 |
| 第二轮 8 对 | 11.815 s | 12.880 s | +9.203% | 0/8 |
| 合计 16 对 | **11.765 s** | **12.860 s** | **+9.538%** | **0/16** |

百分比按每一对的 candidate/baseline − 1 计算，再取中位数；不是两列中位数的比值。两轮中每一对都回退，合计最小/最大变化为 +7.414% / +11.111%。两轮所有 36 次运行（32 次长测、4 次 C100）均通过功能、签名、实际线程配置与完整 THP 检查。两边每次覆盖均为 85,983,232 / 85,983,232 B。

## 阶段计时

| 指标，16 对合计 | 恢复版中位数 | 新 seed 7 中位数 | 逐对变化中位数 |
| --- | ---: | ---: | ---: |
| Host | 11.6605 s | 12.7675 s | +9.600% |
| global eval | 46.2725 µs | 51.1145 µs | +10.391% |
| global update | 7.7770 µs | 8.3470 µs | +7.411% |
| max-part eval | 29.7910 µs | 41.7955 µs | +40.836% |
| sum-part eval | 675.9065 µs | 700.1895 µs | +3.608% |
| sum-part update-push | 87.1500 µs | 86.8500 µs | −0.311% |

新线的主要差距在 eval：最长分区平均 eval 的增幅显著大于各分区总和增幅，说明平均负载集中程度更高。`max-part eval` 是单次运行各分区平均值的最大值，不是逐 step 最大值的均值，不能直接当作 barrier 等待的精确归因。

逐分区平均 eval 中位数，新线首位为 p27（41.7955 µs）和 p5（39.2835 µs）；恢复版平均 eval 前几位约为 29–30 µs。不同 assignment 的相同分区编号不代表相同逻辑，不以相同编号跨版本比较某一逻辑锥的成本。

## 结论与产物

新默认路线已经能从当前源码完成全流程，但在本 workload 的直接对照中仍慢于恢复版约 **9.54%**。恢复版继续作为性能锚点；本次未更改默认流程或手工增加迁移。差距属于两条完整路线的实际差距，尚不能单独归因于某个 solver 权重、初解标签或历史迁移。

数据位于 `build/xs/grhsim32_fresh_rtl_20261028/against_restored_20261028/`：

- `commands.json`、`run.sh`：两轮完整命令与执行入口。
- `r1/summary.json`、`r2/summary.json`：每轮结果。
- `r1/manifest.json`、`r2/manifest.json`：实际命令、签名、线程配置与输入身份。
- 各轮 `measurement_policy.json`、`thp_verification.json`：NUMA、对齐和代码页覆盖。
- `combined_summary.json`：16 对合并统计。

本次仅执行比较和追加记录，未改变二进制或生成配置。
