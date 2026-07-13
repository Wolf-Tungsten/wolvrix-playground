# NO0278 OR-decoded priority true-merge

日期：2026-07-11

## 1. 目标

[NO0277](./NO0277_edge_padded_true_merge_post_profile_20260711.md) 将下一目标定位到 DCache
`prefetchArray.meta_array[row][lane]`：同 FIR 的 GSim 保留 `uint8_t [256][4]`，而 GrhSIM
仍展开为 `4 x 256` 个 scalar register。reg-to-mem 已发现四个 256-row group，但旧 matcher
在 `priority_guard unmatched` 拒绝。

本轮目标是识别该 guard 的真实语义，做保守的通用 matcher 扩展，并完成 synthetic、SimTop
结构和 10k/50k 功能 gate。

## 2. Guard 语义

对 group 900 的 row 0 做临时深度诊断后，目标 mux branch guard 为：

```text
!reset &&
!(higher_enable && higher_addr == row) &&
((writer0_enable && writer0_addr == row) ||
 (writer1_enable && writer1_addr == row) ||
 (writer2_enable && writer2_addr == row))
```

旧 matcher 只接受一组 top-level AND 中的单个行地址等式，因此无法穿过 OR。目标 branch 的
data 是同一个常量；OR 的每个 leaf 只是同一 data 的不同写地址/enable source。

临时诊断输出保存在：

```text
build/logs/xs_perf/no0278/dcache_guard_stop_after_diag_20260711.log
build/logs/xs_perf/no0278/dcache_guard_deep_stop_after_diag_20260711.log
build/logs/xs_perf/no0278/dcache_guard_data_stop_after_diag_20260711.log
```

诊断 helper 在形成结论后已移除，未进入最终实现。

## 3. 实现

`wolvrix/lib/transform/reg_to_mem.cpp` 将原 priority matcher core 抽为
`matchPriorityGuardTerms()`，并新增 `matchPriorityGuardAlternatives()`：

1. 先走原 direct matcher，旧路径语义不变；
2. direct 失败时，top-level AND 必须恰好包含一个可展开 OR；
3. OR leaf 最多 32 个，每个 leaf 必须独立匹配完整的 `addr == row` family；
4. 任一 leaf 不匹配时整个 group fail closed；
5. 仅在该受限 OR 路径中，允许 `!(enable && addr == row)` 这种无窄 selector 的复合冲突；
6. 一个 mux branch 展开为多个 `RegularWriteFamily`，branch data、mask、event 和优先级冲突均保留。

同一个原 register write 会出现在多个展开 family 的 bookkeeping 中；最终 rewrite 的
`selectedWriteOps` 和 `eraseOpOnce()` 都按 `OperationId` 去重，因此只删除一次原 write。

## 4. Synthetic gate

`wolvrix/tests/transform/test_reg_to_mem_pass.cpp` 新增 4-row、3-writer case，覆盖：

- 三个 OR-decoded `enable && addr == row` alternatives；
- group-wide reset fill；
- `!(high_enable && high_addr == row)` 高优先级冲突；
- 转换后恰好一个 memory、三个 memory write、一个 fill；
- 三个 address family 完整，且每个写 guard 都保留 high-enable/high-addr 依赖。

相关测试结果：

```text
emit-grhsim-cpp       PASS, 144.04s
transform-reg-to-mem PASS,   0.03s
full CTest            46/48, 与既有基线一致
```

全量 CTest 用时 238.31s，失败项仍仅为 `transform-comb-lane-pack` 和 `transform-repcut`；
本轮没有新增失败项。完整日志为：

```text
build/logs/xs_perf/no0278/full_ctest_20260711.log
```

## 5. SimTop stop-after 结果

使用 `source env.sh`，从同一份 pre-reg-to-mem JSON 恢复。最终转换统计稳定复现：

| metric | NO0274 old | NO0278 new | delta |
| --- | ---: | ---: | ---: |
| true groups | `825` | `832` | `+7` |
| edge-padded true groups | `171` | `174` | `+3` |
| edge skipped | `3490` | `3483` | `-7` |

新增 7 组均可与同 FIR GSim 中保留的数组对应：

- DCache `prefetchArray.meta_array`: 4 个 lane group，每组 256 rows；
- LLPTW `entries[*].req_info_vpn`: 6 rows；
- LLPTW `entries[*].req_info_s2xlate`: 6 rows；
- LLPTW `entries[*].req_info_source`: 6 rows。

DCache group 900 由旧 `priority_guard unmatched` 变为 `write_families=4, reset=1, ports=4`。
ABTB group 2900 仍被拒绝，说明扩展没有泛化到其他不满足约束的 OR 形态。

stop-after 日志：

```text
build/logs/xs_perf/no0278/or_decoded_stop_after_20260711.log
```

## 6. Fresh generated structure

fresh build：

```text
build/xs_grhsim_no0278_or_decoded_fresh_20260711/grhsim
```

生成头文件中出现四个 `std::array<uint8_t, 256>` DCache state，以及三个深度为 6 的
LLPTW state。DCache 调度代码生成 16 个 `kMemoryWritePort`，同时存在 indexed read 和 fill；
旧 header 不含这些 memory state。

| metric | NO0274 old | NO0278 new | delta |
| --- | ---: | ---: | ---: |
| generated C++ bytes | `1492206672` | `1487326148` | `-4880524` (`-0.33%`) |
| emu `.text` bytes | `103250046` | `103032693` | `-217353` (`-0.21%`) |
| supernodes | `68237` | `67934` | `-303` |
| DAG edges | `639249` | `638649` | `-600` |
| boundary activation edges | `2263684` | `2261833` | `-1851` |
| compute-commit value pairs | `260188` | `258277` | `-1911` |
| state-read activation edges | `85560` | `84996` | `-564` |
| memory-read activation edges | `47021` | `47829` | `+808` |

结构变化符合 scalar state/read 转为 indexed memory 的预期；compute-compute pairs 仅增加 60，
commit supernodes 保持 485。

## 7. SimTop 功能 gate

fresh emu 使用 CoreMark、NEMU difftest，均显式执行到 cycle limit：

| gate | Guest cycle spent | instrCnt | cycleCnt | terminal PC | result |
| --- | ---: | ---: | ---: | --- | --- |
| 10k | `10001` | `458` | `9996` | `0x800027c6` | PASS |
| 50k | `50001` | `73580` | `49996` | `0x80001312` | PASS |

两次均无 mismatch/abort。未固定 CPU 的 Host time 只用于确认运行完成，不进入性能结论。

```text
build/logs/xs_perf/no0278/or_decoded_fresh_build_20260711.log
build/logs/xs_perf/no0278/or_decoded_fresh_functional_10k_20260711.log
build/logs/xs_perf/no0278/or_decoded_fresh_functional_50k_20260711.log
```

## 8. 结论

OR-decoded priority matcher 的 synthetic、结构和 SimTop 10k/50k gate 均通过。DCache 和 LLPTW
新增数组与 GSim 结构一致，且未放宽到 ABTB。性能结论独立记录在
[NO0279](./NO0279_or_decoded_true_merge_simtop_50k_gate_20260711.md)。
