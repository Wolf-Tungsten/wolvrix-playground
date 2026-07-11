# NO0282 Same-FIR instructions profile and compute8 timer fanout

日期：2026-07-11

## 1. 目标与 profile 口径

[NO0281](./NO0281_same_fir_gsim_grhsim_frontend_counter_compare_20260711.md) 将当前 GrhSIM
相对 GSim 的 excess cycles 中约 `82.43%` 算术归因到额外 host instructions。本轮用固定
period `instructions:u` profile 定位这些动态指令。

- workload：same-FIR SimTop CoreMark、NEMU difftest、`-C 50000`；
- CPU：CPU138；
- event：`instructions:u`，period `25000000`；
- call graph：DWARF stack `8192`；
- 所有命令前执行 `source env.sh`。

两边均完成 50001 guest cycles，lost sample 为 0：

| simulator | samples | approximate event count | profile Host time |
| --- | ---: | ---: | ---: |
| GSim | `3201` | `80025000000` | `31165ms` |
| GrhSIM NO0278 | `7617` | `190425000000` | `82861ms` |

sample/event-count 比例为 `2.379x`，与独立 perf stat 的 host instructions `2.378x` 一致。

## 2. Instructions 分布

精确 symbol sample 聚合中各有一个 unresolved sample：

| simulator/category | samples | all-profile share |
| --- | ---: | ---: |
| GSim `subStep*` | `3177` | `99.25%` |
| GSim `step` | `4` | `0.12%` |
| GSim other resolved | `19` | `0.59%` |
| GrhSIM compute batches | `6651` | `87.32%` |
| GrhSIM commit batches | `754` | `9.90%` |
| GrhSIM eval | `20` | `0.26%` |
| GrhSIM row-reader helper | `1` | `0.01%` |
| GrhSIM other resolved | `190` | `2.49%` |

按固定 period 估算，GrhSIM compute 约执行 `166.275B` instructions，单独就比 GSim 全部
`subStep*` 的约 `79.425B` 多 `86.85B`。compute+commit 覆盖 GrhSIM instructions 的
`97.22%`，说明额外动态工作主要在 generated schedule body，而不是 emulator harness。

## 3. 与 cycles profile 联合观察

[NO0280](./NO0280_or_decoded_true_merge_cycles_post_profile_20260711.md) 的同 period
`cycles:u` profile 中，compute/commit 分别为 `8033/3941` samples。由于两个 event period
相同，可以形成阶段级 CPI proxy：

| category | cycles samples | instructions samples | CPI proxy | IPC proxy |
| --- | ---: | ---: | ---: | ---: |
| compute | `8033` | `6651` | `1.208` | `0.828` |
| commit | `3941` | `754` | `5.227` | `0.191` |

因此两个优化问题必须分开处理：

- compute 执行了绝大多数额外 instructions；
- commit instructions 不多，但单指令 cycles 很高，是 NO0281 中 backend stall density 偏高的主要嫌疑。

当前先处理动态工作主体 compute。

## 4. 最大 instruction hotspot

GrhSIM 最大单热点为：

```text
eval_compute_batch_8() = 403 samples = 5.29% of all host instructions
```

generated source 为：

```text
build/xs_grhsim_no0278_or_decoded_fresh_20260711/grhsim/grhsim_emit/grhsim_SimTop_sched_8.cpp
```

主要静态规模：

| metric | value |
| --- | ---: |
| source lines / bytes | `350129 / 34153438` |
| function `.text` bytes | `0x14ccff` |
| `kRegisterReadPort` comments | `60908` |
| emitted scalar changed predicates | `26062` |
| `kDiv` comments | `1035` |

`kRegisterReadPort` 按 state 前缀分类：

| state prefix | read comments | share |
| --- | ---: | ---: |
| top-level `timer` | `29686` | `48.74%` |
| `logEndpoint$*` | `19895` | `32.66%` |
| `cpu$*` | `10611` | `17.42%` |
| `endpoint$*` | `676` | `1.11%` |

同一 `timer` read 在同 supernode 内已复用 changed predicate，但每个 cloned read result 仍写入
独立 `value_u64_slots_`，并分别累计 changed/fanout effects。

## 5. Instruction sample 到 state-read 映射

将 annotate 中的 `%rdi` displacement 按 `value_u64_slots_` layout 映射回 source output slot。
`403` samples 中 `400` 个得到近邻归因：

| mapped category | samples | all batch8 samples |
| --- | ---: | ---: |
| top-level `timer` reads | `156` | `38.71%` |
| `logEndpoint$*` reads | `145` | `35.98%` |
| `kDiv` | `13` | `3.23%` |
| other u64 operations | `86` | `21.34%` |

`timer + logEndpoint` 合计 `301` samples，占 batch8 的 `74.69%`。该映射按相邻 output access
归因，不把单条指令百分比视为精确 source line cost；但静态计数和动态大类共同证明该热点
主体是统计/日志状态 fanout，而不是单个 division。

## 6. 与 GSim 生成结构的直接差异

GSim 也保留相同的 `timer`、`logEndpoint$*` 状态和日志语义，但 generated `subStep*` 中直接
引用类成员，例如：

```cpp
gprintf("...", 64, timer, ...);
```

GrhSIM 则先为大量 cloned `kRegisterReadPort` materialize 独立 value slot：

```cpp
value_u64_slots_[slot_n] = grhsim_value_storage_ref<std::uint64_t>(state_logic_storage_, 0);
```

随后 consumer 再读取这些 slots。两边不是 workload 或日志功能不同，而是同一 FIR state
read/fanout 的 codegen 表达不同。

## 7. 结论与下一步

1. 当前 GSim/GrhSIM 额外 host instructions 的主体在 GrhSIM compute schedule。
2. 最大热点 compute8 的约四分之三 samples 落在 `timer` 和 `logEndpoint` state-read fanout。
3. NO0258 已消除重复 changed comparison，但保留的近三万次 timer slot materialization 仍是
   直接动态成本；因此不能继续只优化 predicate。
4. 下一步审查 activity-schedule source clone 与 emitter value resolution，设计受限于同 state、
   同 phase、同 supernode 的 canonical read value；必须保留所有 consumer activation/fanout，
   并先用 synthetic execution test 证明跨 consumer 读值与 changed propagation 正确。
5. 该方向是 value-result consolidation，不重新启用此前证明不利的 per-supernode C++
   storage-ref alias。

## 8. 产物

```text
build/logs/xs_perf/no0281/gsim_cpu138_50k_instructions.data
build/logs/xs_perf/no0281/grhsim_no0278_cpu138_50k_instructions.data
build/logs/xs_perf/no0281/gsim_cpu138_50k_instructions_exact_symbols.report
build/logs/xs_perf/no0281/grhsim_no0278_cpu138_50k_instructions_exact_symbols.report
build/logs/xs_perf/no0281/grhsim_compute8_instructions_annotate_samples.report
build/logs/xs_perf/no0281/grhsim_compute8_u64_slot_ops.tsv
build/logs/xs_perf/no0281/grhsim_compute8_instructions_u64_slot_counts.tsv
```
