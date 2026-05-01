# Scalar-Memory-Pack 与 GSim GraphPartition 剩余寄存器差值对照

## 1. 目的

回答一个更直接的问题：

- 当前 `scalar-memory-pack` 已经能合并多少；
- 和 `gsim` 使用 FIRRTL 跑到 `graphPartition` 之后的 `NODE_REG_SRC` 相比，还剩多少“打散寄存器”没有被收回；
- 这些剩余的主体原因是什么。

这里不用 `grhsim post-stats`，而直接对照：

- `gsim`：`build/xs/ir_compare/SimTop_0graphPartition.json`
- `grh pre-pack`：`build/xs/scalar_memory_pack_probe_flatten_simplify_20260429/after_flatten_simplify.json`
- `grh post-pack`：`build/xs/scalar_memory_pack_probe_flatten_simplify_20260429/after_flatten_simplify_plus_scalar_memory_pack.json`

对照脚本沿用：

- [`scripts/compare_register_name_sets.py`](../../scripts/compare_register_name_sets.py)

输出结果：

- `build/xs/ir_compare/compare_graphpartition_vs_flatten_simplify_kRegister.json`
- `build/xs/ir_compare/compare_graphpartition_vs_scalar_memory_pack_kRegister.json`

## 2. 总量结论

### 2.1 `scalar-memory-pack` 自身合并量

当前 pass 在干净 `after_flatten_simplify.json` 上实际成功改写：

- `606` 个 cluster
- `66,900` 个 scalar register members

对应日志口径：

- `candidate_clusters=606`
- `candidate_members=66900`
- `rewritten_clusters=606`
- `rewritten_members=66900`

### 2.2 与 `gsim graphPartition` 对照后的剩余 gap

| 口径 | `gsim` raw | `grh` raw | raw gap (`grh-gsim`) |
| --- | ---: | ---: | ---: |
| pre-pack | `148,954` | `285,668` | `136,714` |
| post-pack | `148,954` | `226,180` | `77,226` |

所以，这一轮 `scalar-memory-pack` 相对 `gsim` 实际缩小了：

- `59,488` 个寄存器差值

也就是说：

- 当前还比 `gsim graphPartition` 多 `77,226` 个 `kRegister`

## 3. 这 `77,226` 里面，哪些是明确的“还在数组展开”

`compare_register_name_sets.py` 的分类结果表明，post-pack 之后仍有一大块是非常明确的 `1:N` 展开：

| 类别 | `gsim keys` | `grh keys` | net gap |
| --- | ---: | ---: | ---: |
| `exactNormalized1to1` | `80,813` | `80,813` | `0` |
| `aggregateGsimFieldToGrhBaseNto1` | `399` | `109` | `-290` |
| `prefixExpand1toN` | `493` | `21,448` | `20,955` |
| `residualUnclassified` | `67,071` | `123,632` | `56,561` |

因此可以先下一个保守结论：

- 在剩余 `77,226` 差值里，
- 至少有 `20,955` 是已经被名字归一化明确识别出来的“`gsim` 1 个聚合状态，对应 `grh` 多个打散寄存器”。

这部分已经不是猜测，而是直接由 `prefixExpand1toN` 分类给出的。

## 4. 明确还没收回的大组

`prefixExpand1toN` 最大的剩余组如下：

| `gsim` base | `grh` child count |
| --- | ---: |
| `cpu_l_soc_core_with_l2_core_backend_inner_ctrlBlock_rob_debug_VecOtherPdest` | `2816` |
| `cpu_l_soc_core_with_l2_core_memBlock_inner_ptw_ptw_cache_l0BitmapReg` | `2048` |
| `cpu_l_soc_core_with_l2_core_memBlock_inner_dcache_dcache_accessArray_meta_array` | `1024` |
| `cpu_l_soc_core_with_l2_core_memBlock_inner_dcache_dcache_prefetchArray_meta_array` | `1024` |
| `cpu_l_soc_core_with_l2_core_backend_inner_ctrlBlock_dispatch_fpBusyTable_loadDependency` | `768` |
| `cpu_l_soc_core_with_l2_core_backend_inner_ctrlBlock_dispatch_intBusyTable_loadDependency` | `672` |
| `cpu_l_soc_core_with_l2_core_frontend_inner_bpu_phr_commitHist` | `532` |
| `cpu_l_soc_core_with_l2_core_frontend_inner_bpu_phr_phr` | `532` |
| `cpu_l_soc_core_with_l2_core_backend_inner_ctrlBlock_rob_debug_exuData` | `352` |
| `cpu_l_soc_core_with_l2_core_backend_inner_ctrlBlock_rob_debug_lsIssued` | `352` |

这批都说明：

- `gsim/FIRRTL` 已经把它们作为一个聚合状态来看；
- 当前 `scalar-memory-pack` 还没有把它们收回。

## 5. `residualUnclassified` 也不是“小尾巴”

剩余未分类差值还有：

- `56,561`

这部分并不意味着“不是数组展开”，更大的可能是：

- 它们仍然是聚合状态，只是当前名字归一化规则还没把它们和 `gsim` 一一扣上。

对 `residualUnclassified.grh` 做 wildcard 汇总后，最大的模式包括：

| count | residual pattern |
| ---: | --- |
| `2048` | `cpu_l_soc_core_with_l*_core_frontend_inner_ftq_perfQueue_*_isCfi_*` |
| `1368` | `cpu_l_soc_core_with_l*_core_memBlock_inner_lsq_loadQueue_loadQueueReplay_uop_*_exceptionVec_*` |
| `1344` | `cpu_l_soc_core_with_l*_core_memBlock_inner_lsq_storeQueue_uop_*_exceptionVec_*` |
| `1024` | `cpu_l_soc_core_with_l*_l2top_inner_busPMU_*_latencyRecord_*_valid` |
| `1024` | `cpu_l_soc_core_with_l*_l2top_inner_busPMU_*_latencyRecord_*_timeStamp` |
| `1024` | `cpu_l_soc_core_with_l*_core_frontend_inner_bpu_abtb_takenCounter_*_*_*_value` |
| `1024` | `cpu_l_soc_core_with_l*_l2top_inner_busPMU_*_latencyRecord_*_reqType` |
| `1024` | `cpu_l_soc_core_with_l*_core_backend_inner_ctrlBlock_memCtrl_ssit_data_array_dataBanks_*_data_*_strict` |
| `1024` | `cpu_l_soc_core_with_l*_core_backend_inner_ctrlBlock_memCtrl_ssit_data_array_dataBanks_*_data_*_ssid` |
| `896` | `cpu_l_soc_core_with_l*_core_memBlock_inner_lsq_storeQueue_dataModule_data*_*_data_*_valid` |
| `896` | `cpu_l_soc_core_with_l*_core_memBlock_inner_lsq_storeQueue_dataModule_data*_*_data_*_data` |
| `512` | `cpu_l_soc_core_with_l*_core_frontend_inner_bpu_utage_MicroTageTable_*_entries_*_tag` |
| `512` | `cpu_l_soc_core_with_l*_core_frontend_inner_bpu_utage_MicroTageTable_*_entries_*_valid` |
| `512` | `cpu_l_soc_core_with_l*_core_frontend_inner_bpu_utage_MicroTageTable_*_entries_*_takenCtr_value` |
| `384` | `cpu_l_soc_core_with_l*_core_frontend_inner_itlb_entries_page_itlb_storage_fa_entries_*_ppn_low_*` |

这说明剩余主体并不是零散边角，而是整组整组的：

- `exceptionVec`
- `latencyRecord`
- `takenCounter`
- `ssit data banks`
- `storeQueue dataModule`
- `uTage / itlb / dtlb` 一类表项

## 6. 原因分析

### 6.1 不是所有 `gsim` 聚合状态都属于“memory-like 动态访问”

当前 `scalar-memory-pack` 识别的是一类比较窄的结构：

- 读侧接近 `register-read -> concat -> slice(dynamic/static)`
- 写侧接近 `point update`
- 可选 `fill/reset`

但 `gsim/FIRRTL` 里能保持聚合的状态远不止这一类，还包括：

- `Vec[Bool]` / `Vec[UInt]` 这类纯静态数组
- packed record / bundle 数组
- ROB / FTQ / replay / queue / debug table 一类槽位状态
- page table / tlb entry / predictor table 的字段化聚合

这些即使在 `gsim` 那边仍然是一个“聚合状态”，也未必满足当前 pass 的 memory-like 访问模式。

### 6.2 很多剩余组是“按槽位并行访问”，不是“单地址读写”

例如：

- `ROB entries`
- `FTQ perfQueue`
- `exceptionVec`
- `PHR`
- `loadDependency`

它们的典型访问方式往往是：

- 多个槽位并行读
- 多个字段分别参与组合逻辑
- 写入也未必是单地址 point update

这类状态和 `kMemoryReadPort / kMemoryWritePort / kMemoryFillPort` 的抽象不完全同构。

### 6.3 还有一批确实像 memory，但写侧/读侧形态超出了当前 matcher

从当前 pass 的 reject-summary 看，后续真正和 matcher 能力直接相关的大头包括：

- `register read has non-concat users`：`34,386` members
- `concat leaves do not map to distinct register symbols`：`54,501` members
- `cluster has row-varying bulk branch not representable as kMemoryFillPort`：`1,188` members
- `mixed write top-level mux selects on a non-address member-local branch`：`1,496` members

这几类说明当前 matcher 仍然偏保守：

- 有的簇读口不只服务一个 `concat`
- 有的簇名字/叶子对应关系不够规整
- 有的 bulk write 不是“全行写同一个值”
- 有的 mixed write 里混入了 member-local 条件

这批继续扩 matcher 还有空间，但已经不是 `usefulCtrs` 那种最规整、最好吃的形态。

### 6.4 还有一部分差值只是名字体系不一致

`residual` 里也混着一些：

- `gsim` 用 `__field`
- `grh` 用 `_field`
- `gsim` 暴露 `MPORT__ADDR`
- `grh` 暴露 `mem_ext__R0_addr_d0`

这部分会放大 `residualUnclassified`，但它们不应全部被算成“新的未合并状态”。

## 7. 结论

截至当前版本，可以把结论压成三句话：

1. `scalar-memory-pack` 已经成功收回 `66,900` 个 scalar registers，并把相对 `gsim graphPartition` 的 raw gap 从 `136,714` 压到 `77,226`，净缩小 `59,488`。
2. 在剩余 gap 里，至少有 `20,955` 已被明确识别为 `gsim 1 : grh N` 的数组展开残留；这部分是真正还没收回的聚合状态。
3. 剩下的 `56,561` 大头也仍然主要是聚合数组/槽位状态，但多数已超出当前 `scalar-memory-pack` 的“memory-like 动态读写 + fill”目标范围，后续如果要继续逼近 `gsim/FIRRTL`，需要的不只是继续扩 memory-pack，而是新增一类更泛化的 `vec/record slot repack` 能力。

## 8. 直接产物

- 对照结果：
  - [`build/xs/ir_compare/compare_graphpartition_vs_flatten_simplify_kRegister.json`](../../build/xs/ir_compare/compare_graphpartition_vs_flatten_simplify_kRegister.json)
  - [`build/xs/ir_compare/compare_graphpartition_vs_scalar_memory_pack_kRegister.json`](../../build/xs/ir_compare/compare_graphpartition_vs_scalar_memory_pack_kRegister.json)
- 输入：
  - [`build/xs/ir_compare/SimTop_0graphPartition.json`](../../build/xs/ir_compare/SimTop_0graphPartition.json)
  - [`build/xs/scalar_memory_pack_probe_flatten_simplify_20260429/after_flatten_simplify.json`](../../build/xs/scalar_memory_pack_probe_flatten_simplify_20260429/after_flatten_simplify.json)
  - [`build/xs/scalar_memory_pack_probe_flatten_simplify_20260429/after_flatten_simplify_plus_scalar_memory_pack.json`](../../build/xs/scalar_memory_pack_probe_flatten_simplify_20260429/after_flatten_simplify_plus_scalar_memory_pack.json)
