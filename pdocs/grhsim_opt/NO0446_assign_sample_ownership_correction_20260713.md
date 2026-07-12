# NO0446 Assign sample ownership correction

日期：2026-07-13

## 1. Failed strict gate

按 [NO0445](./NO0445_assign_boundary_forwarding_audit_plan_20260713.md) 首次把 395 个 `kAssign` profile rows 连接到
NO0357 generated blocks。静态侧 73,644 个 assign comments 全部解析，但 sample gate 失败：

```text
sample rows                 395
batch mismatches              0
source/block mismatches      53
ownership mismatches         53
exit                          1
```

失败产物：

```text
build/logs/xs_perf/no0445/validation_failures.tsv
```

这次运行没有产出可接受的 assign 分类结果，不能把其余 342 rows 直接当作最终有效集合。

## 2. Root cause

NO0403 的机器归因器按源码行顺序维护 `current_operation`，遇到 `// op _op_N [kind]` 时更新，但进入新的
`// Supernode N` 时没有清空。于是新 supernode 在第一条 op comment 之前发射的代码会继承前一 supernode 最后一个 op：

| False inherited source role | Samples |
| --- | ---: |
| New-supernode `activeWordFlags` dispatch | 22 |
| New-supernode typed-local/concat/packed-index prelude | 31 |
| Total | 53 |

例如 `sched_1.cpp:197794-197801` 是 `_op_11031295 [kAssign]` 的实际 value block；新 supernode 从 197810 开始，
197813 的 active-word clear 仍被 NO0403 标成 `_op_11031295`，直到 197815 出现下一条 op comment。batch/source 文件本身
完全一致，错误只在 operation-kind ownership。

另一个必须同时修正的问题是：一个 supernode 最后一条 op 的 value block 之后，可能还有 deferred
`grhsim_any_changed_* -> supernode_active_curr_` tail。旧映射同样把 tail 全归给最后一个 op，但这些 activation 是多个
results 的共享聚合效果，不能作为最后一个 `kAssign` 的独占 forwarding 上界。

## 3. Corrected ownership model

重跑不再使用“当前 comment 一直延续到下一 comment”的规则，而是按 generated value scope 分类：

1. `exact_assign_body`：从 assign 的 `// value` 后独立 `{` 到同缩进 `}`，只有这里的 RHS、compare、accumulate 和
   writeback 可归给该 assign；
2. `shared_supernode_tail`：最后一个 op body 结束后、下一 supernode marker 前的 deferred activation，只算 framework；
3. `next_supernode_dispatch`：marker 后的 active-word gate/clear，改归 dispatch；
4. `next_supernode_prelude`：第一条 op comment 前的 typed locals/concat/slice prelude，只算共享 payload，不归前一 assign。

同时按 batch+line 重新读取实际源码，要求 395/395 source text 一致。只有 `exact_assign_body` rows 进入 NO0445 的
source/effect forwarding 上界；其他三类保留在总样本核算中，但不得触发 67 samples/direct 1% 的 assign 实现门槛。

## 4. Next gate

修正分析器后重新输出 395 rows 的 ownership status 和 corrected operation summary。若 exact-body 的同一
direct-slot/state source class 达到 67 samples，才进入 NO0445 Phase B；否则按预声明停止，不用旧 395-sample 总数推进实现。
