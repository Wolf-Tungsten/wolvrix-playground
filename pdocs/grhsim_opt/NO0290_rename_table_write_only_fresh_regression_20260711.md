# NO0290 RenameTable write-only fresh functional and structure regression

日期：2026-07-11

## 1. 目标

在 [NO0289](./NO0289_rename_table_write_only_true_merge_20260711.md) 的 pre-sched 结构 gate 之后，从同一 pre-reg-to-mem JSON 完成 fresh emit/compile，并检查：

- SimTop 10k/50k NEMU difftest 功能；
- generated C++、emu text 和 activity-schedule 规模；
- 当前 write-only true-merge 是否值得进入固定 CPU runtime gate。

对照基线为保留的 [NO0286](./NO0286_commit_state_change_unlikely_codegen_20260711.md) emu。

## 2. Fresh build

fresh build 成功，三个 decoded-write group 再次全部重写：

```text
decoded_write_groups=3
matched_rows=95
true_groups=835
reg-to-mem=148.957 s
activity-schedule=178.229 s
write_grhsim_cpp=71.202 s
emit total=443.889 s
```

目标 memory state 出现在 generated header 中：

```text
std::array<std::uint8_t, 32> ...fpRat_difftest_table...
std::array<std::uint8_t, 32> ...intRat_difftest_table...
std::array<std::uint8_t, 32> ...vecRat_difftest_table...
```

emu 最终成功链接。

## 3. Functional gate

两次功能测试都先执行 `source env.sh`，使用 CoreMark 2 iterations 与 NEMU difftest，并显式运行到 cycle limit：

| gate | Guest cycle spent | instrCnt | cycleCnt | terminal PC | result |
| --- | ---: | ---: | ---: | --- | --- |
| 10k | `10001` | `458` | `9996` | `0x800027c6` | PASS |
| 50k | `50001` | `73580` | `49996` | `0x80001312` | PASS |

两次均没有 mismatch 或 abort，因此 row offset、packed reset 和写冲突逻辑在当前覆盖区间内功能正确。

## 4. Fresh structure regression

尽管 scalar state 已恢复为三组 memory，当前 lowering 的总体结构明显膨胀：

| metric | NO0286 baseline | NO0290 fresh | delta |
| --- | ---: | ---: | ---: |
| generated C++ bytes | `1,488,642,375` | `1,686,685,146` | `+198,042,771` (`+13.30%`) |
| emu `.text` bytes | `97,049,715` | `114,083,082` | `+17,033,367` (`+17.55%`) |
| supernodes | `67,934` | `82,809` | `+14,875` (`+21.90%`) |
| compute supernodes | `67,449` | `82,324` | `+14,875` |
| DAG edges | `638,649` | `664,523` | `+25,874` (`+4.05%`) |
| boundary activation edges | `2,261,833` | `2,850,858` | `+589,025` (`+26.04%`) |
| compute-compute value pairs | `2,003,556` | `2,589,598` | `+586,042` (`+29.25%`) |
| graph ops | `7,196,059` | `9,186,156` | `+1,990,097` (`+27.66%`) |

commit supernodes 仍为 `485`，但三个 memory 共生成 `511 + 511 + 520 = 1542` 个 write ports。每个端口的 priority collision 通过显式地址冲突 guard 保证，低优先级端口会重建所有更高优先级 writer 的 `enable && higher_addr == current_addr` 排除条件。writer 数达到约 520 时，该表达接近二次增长；它消除了逐 row decode，却引入了更大的 pairwise conflict network。

这解释了为何 state 形态更接近 GSim，但 generated C++ 和调度图反而显著变大。GSim 的局部 next array 通过有序 indexed writes 实现同地址覆盖，不展开这套 pairwise conflict guard；两边目前仍未达到等价 lowering 形态。

## 5. Runtime 处理

未固定 CPU 的 50k 功能测试 Host time 为 `126.401 s`，只作为结构回退的预警，不与此前不同时间、不同宿主条件的数据直接比较。由于 fresh 静态门禁已经出现 `+17.55%` text 和 `+21.90%` supernodes 的明确回退，本阶段不消耗三次约两分钟的 old/new/old 测试来决定是否保留该实现。

当前结论是：功能机制成立，但现有 explicit-conflict lowering 不能作为 SimTop 性能优化保留。必须先消除 conflict network 膨胀，再进入固定 CPU runtime gate。

## 6. 产物

```text
build/xs_grhsim_no0289_write_only_true_merge_fresh_20260711/grhsim
build/logs/xs/xs_wolf_grhsim_build_no0289_write_only_true_merge_fresh_20260711.log
build/logs/xs_perf/no0289/write_only_true_merge_fresh_build_20260711.log
build/logs/xs_perf/no0289/write_only_true_merge_functional_10k_20260711.log
build/logs/xs_perf/no0289/write_only_true_merge_functional_50k_20260711.log
```

## 7. 下一步

1. 统计三组 memory 的 conflict 总数、最大 priority 深度和对应新增 operations，完成精确归因。
2. 对照 GSim `SimTop278.cpp/SimTop279.cpp` 的写入顺序，定义不依赖普通 operation 顺序的显式 ordered-write contract。
3. 优先评估一个能表达同 event 下有序 indexed writes 的 batch IR/emitter 形态，使计算量从 pairwise conflict 降回 writer 线性规模。
4. 新形态必须继续通过同地址 collision、不同地址并行写、reset、10k/50k difftest 和静态规模 gate，之后才运行固定 CPU old/new/old。
