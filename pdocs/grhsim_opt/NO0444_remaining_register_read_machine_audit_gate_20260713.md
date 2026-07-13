# NO0444 Remaining register-read machine audit gate

日期：2026-07-13

## 1. Scope and profile-count correction

本轮按 [NO0443](./NO0443_remaining_register_read_machine_audit_plan_20260713.md) 只复用 NO0403 的 latest direct fixed-period
profile、NO0357 generated source 和 NO0352 locality TSV；没有重新编译，也没有重跑仿真或 perf。

NO0443 开头把两个正交分类写成了包含关系，需要在结果口径中勘正：`920` 是 operation kind 为
`kRegisterReadPort` 的 samples；`544` 是全部 operation kinds 上被 NO0403 机器归因为 `operand_or_state_read` 的 samples，
不是 920 个 read samples 的子集。两者真实交集为 `190`。920 个 read samples 的机器归因实际为：

| Machine mechanism | Samples | Direct total share |
| --- | ---: | ---: |
| `payload_compute` | 585 | 8.764% |
| `operand_or_state_read` | 190 | 2.846% |
| `runtime_helper` | 144 | 2.157% |
| `entry_active_scan` | 1 | 0.015% |

这说明 read comment 只标识 IR operation，不能把采样指令整体解释为一条独立状态搬运。

## 2. Locality join validity

分析器先拒绝了两个不稳定连接：NO0352 locality 的内部 `op_id` 与 generated comment 的 `_op_N` 不是同一编号空间；
`batch + supernode + state` 也会被 NO0357 direct emit 的重新分 batch 打破。最终连接键使用跨两版保持稳定的
`supernode + state symbol + group-local occurrence order`，并把计数不同的 key 整组排除。

| Gate | Result |
| --- | ---: |
| Generated register-read comments | 920,942 |
| Locality register-read rows | 924,022 |
| Sequence keys | 645,393 |
| Count-different keys | 3,080 |
| Sampled unique `_op_N` symbols joined | 823 / 823 |
| Sample rows joined | 920 / 920 |
| Sampled keys affected by count difference | 0 |
| Recorded source-line mismatches | 0 |
| Parsed register-write comments | 211,641 |
| Unique written states | 211,641 |

因此本轮没有用错 batch 归属，也没有靠模糊 state-name matching 补齐样本。重复采到同一 IP/op 的行仍按 profile sample
保留，所以 920 sample rows 对应 823 个 unique read operation symbols。

## 3. Generated-code shapes

| Source shape | Samples | Direct total share | Compute share |
| --- | ---: | ---: | ---: |
| State ref directly in consumer expression | 629 | 9.423% | 11.252% |
| Fused or instruction ownership ambiguous | 276 | 4.135% | 4.937% |
| Independent scalar slot materialization | 15 | 0.225% | 0.268% |
| Independent wide slot materialization | 0 | 0% | 0% |

629 个 inline samples 的头部机器指令是 `setne/lea/mov/cmov/movzx/and/cmp/or/test`，宽度以 1-bit 和 64-bit 为主；
它们是状态值直接参与比较、地址、算术或 mux 的 consumer payload。276 个 fused samples 不能证明采样指令属于独立 read
copy，也不能作为可删上界。

真正独立写 `value_{bool,u8,u16,u32,u64}_slots_ = state_ref` 的只有 15 samples，且全部为 scalar、
`tracked_change=0`、`boundary_fanout=0`。即使假设 15 个采样指令全部可删除，上界也只有 direct `0.225%`，远低于
预声明的 67 samples/direct `1%` 门槛。其余 eligibility 归因为 `not_materialized=894`、`not_scalar=10` 和
`protection_or_emitter_only=1`，不存在被某一个可安全放宽条件遮住的大 materialized read class。

## 4. Same-FIR GSim comparison

GrhSIM 的第一大 sampled state 是 ROB `timer`，共 147 samples。same-FIR GSim 在 `SimTop276.cpp:2545,2598-2604`
直接用同一状态做 commit-latency 减法；`SimTop257.cpp:24708-24730` 计算并更新 `timer$NEXT`，而
`SimTop78.cpp:13916-13945` 仍有 `$old` snapshot、persistent commit 和 changed compare。

第二个代表性状态 `delayedNotFlushedWriteBackNums_delayed_bits_r_16` 有 17 个 GrhSIM samples；GSim 在
`SimTop281.cpp:15554` 等位置直接把它选入 ROB writeback-count payload，并在 `SimTop329.cpp:13272-13275` 更新 NEXT、
比较 old value 和传播 active flag。精确位置已记录在：

```text
build/logs/xs_perf/no0443/gsim_read_crosscheck.txt
```

两组头部证据都表明 inline state load 是两边共同的仿真工作。GSim 的 typed member 形态更利于编译器形成紧凑 payload，
但不能靠删除 GrhSIM 的状态读取来消除。

## 5. Decision

remaining register-read 方向停止，不扩展 NO0357 direct-state forwarding：唯一独立 slot materialization class 只有
15 samples/direct `0.225%`，没有通过结构收益门槛；inline/fused 的 905 samples 是必要 payload 或无法证明可独立删除。
本轮不修改 emitter，也不做低上界 O3 probe。

下一步回到 latest direct operation profile，排除已经审计完的 register read、mux、full-width logic 与 change/dispatch
framework 后，重新筛选仍有至少 direct `1%` 上界的 GrhSIM-specific materialization class。

产物：

```text
build/logs/xs_perf/no0443/analyze_remaining_register_reads.py
build/logs/xs_perf/no0443/register_read_sample_rows.tsv
build/logs/xs_perf/no0443/{shape,exclusion,state_family}_summary.tsv
build/logs/xs_perf/no0443/{mechanism_shape,memory_role,shape_exclusion}_summary.tsv
build/logs/xs_perf/no0443/analysis_summary.txt
build/logs/xs_perf/no0443/gsim_read_crosscheck.txt
```
