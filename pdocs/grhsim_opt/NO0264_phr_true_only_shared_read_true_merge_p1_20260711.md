# NO0264 PHR true-only shared-read true-merge P1

日期：2026-07-11

## 目标

承接 [NO0262](./NO0262_multi_write_true_merge_plan_20260710.md) 与
[NO0263](./NO0263_priority_consolidated_write_true_merge_p0_20260710.md)，让 PHR 这类“完整
register storage 有多个 circular/shared read view”的结构进入 strict true merge，同时不放宽
默认 reg-to-mem intent 的 single-user 规则。

## 实现

`reg_to_mem` 新增独立的 true-only storage discovery：

- 从纯 `kRegisterReadPort` concat 中恢复完整 storage row order；
- 接受同一完整布局的重复 circular concat，或 register read 还有其他纯读取用户的布局；
- 重叠候选按 element count 从大到小认领，失败候选不写 intent attrs；
- true merge 前要求每个 storage register 的所有 read port 都能完整替换；
- 每一行只生成一个 constant-address `kMemoryReadPort`，并把该行所有旧 read result 重绑定到
  新 read result。

write-side matcher 在 P0 基础上补齐：

- 多个 prioritized consolidated-write family；
- 多 reset term 的精确集合匹配与 fill guard OR 重建；
- mux fallback data 形成额外 write family；
- 非 2 次幂 memory depth 的显式 `addr < row_count` guard。

同地址 priority 仍由 `!(higher_addr == current_addr)` 显式表达，不依赖 commit operation 顺序。

## Synthetic gate

新增测试覆盖 shared read、重复 circular view、多 write family、多 reset term、fallback family、
3-row domain guard，以及失败候选不污染 intent attrs。emitter 执行 harness 继续覆盖同地址 priority
与不同地址并行更新。

最终验证均先执行 `source env.sh`：

```text
cmake --build wolvrix/build -j64
ctest --test-dir wolvrix/build --output-on-failure -R '^(transform-reg-to-mem|emit-grhsim-cpp)$'
```

结果：

| test | result | time |
| --- | --- | ---: |
| `transform-reg-to-mem` | PASS | `0.03s` |
| `emit-grhsim-cpp` | PASS | `151.12s` |

日志：

```text
build/logs/xs/no0264_wolvrix_build_p1_final_20260711.log
build/logs/xs/no0264_ctest_p1_final_20260711.log
```

## SimTop PHR 结构 gate

fresh emit 复用与 NO0258 相同的 pre-reg-to-mem JSON，调度参数保持
`compute=108, commit=4096, target_batches=64`。

PHR 主组 `762/3094`：

| metric | value |
| --- | ---: |
| anchors / rows / width | `6 / 532 / 1` |
| regular write families | `41` |
| reset family | `1` |
| replaced scalar reads | `532` |
| emitted memory write ports | `41` |
| erased regular/reset writes | `21812 / 532` |
| erased registers | `532` |

相邻的另一个 532-row PHR storage 组 `763/3094` 也完成 true merge，包含 2 个 regular write
family 与 1 个 reset family。全 SimTop 共 `479` 个 true group、`327` 个 intent group；
reg-to-mem pass 用时 `17.287s`。

对比 P1 前 NO0258 生成模型：

| metric | P1 前 | P1 | delta |
| --- | ---: | ---: | ---: |
| total supernodes | `72368` | `71067` | `-1301` |
| compute supernodes | `71871` | `70570` | `-1301` |
| compute-node ops | `6429337` | `6294022` | `-135315` |
| boundary values | `1321994` | `1269052` | `-52942` |
| boundary activation edges | `2446334` | `2367056` | `-79278` |
| compute-compute value pairs | `2095811` | `2018559` | `-77252` |
| source clones | `2047021` | `2047126` | `+105` |

`sched_54.cpp` 从 `32152460` bytes 缩到 `18390958` bytes。该变化直接对应
[NO0260](./NO0260_phr_multi_write_scalarization_gap_20260710.md) 定位的 PHR 展开热点，而不是
通过调整 partition 参数掩盖它。

产物与日志：

```text
build/xs_grhsim_no0264_phr_multi_reader_row_activation_20260711/grhsim
build/logs/xs/xs_wolf_grhsim_build_no0264_phr_multi_reader_row_activation_20260711.log
build/logs/xs/xs_wolf_grhsim_compile_no0264_phr_multi_reader_row_activation_20260711.log
```

## SimTop runtime gate

fresh executable 的 10k 与 50k difftest 都通过：

| run | Guest cycles | instrCnt | cycleCnt | mismatch / ABORT |
| --- | ---: | ---: | ---: | ---: |
| 10k | `10001` | `458` | `9996` | `0 / 0` |
| 50k | `50001` | `73580` | `49996` | `0 / 0` |

日志：

```text
build/logs/xs/xs_wolf_grhsim_no0264_phr_multi_reader_row_activation_10k_20260711.log
build/logs/xs/xs_wolf_grhsim_no0264_phr_multi_reader_row_activation_50k_20260711.log
```

## 结论

P1 已把目标 PHR scalar state 与 write mux 展开恢复为真实 memory/read/write/fill，并通过完整
SimTop 功能 gate。它显著缩小生成代码和 compute 图；row-aware reader activation 及最终性能
结论分别记录在 [NO0265](./NO0265_memory_row_reader_activation_ab_20260711.md) 与
[NO0266](./NO0266_phr_true_merge_p1_simtop_50k_gate_20260711.md)。
