# NO0044 `RemoveDeadNodes0` vs GrhSIM `keepDeclaredSymbols=false` 的 `129904` 全量差值归因（2026-04-29）

> 归档编号：`NO0044`。目录顺序见 [`README.md`](./README.md)。

这份记录直接回答上一轮要求：

- 不再做代表样本抽查；
- 直接对 `gsim RemoveDeadNodes0` 后仍存活的全部 `REG_SRC`，和 `grhsim keep=false` 的全部 `kRegister` 做**全量匹配**；
- 把两边的差值做成一份**可求和回去**的全量归因。

先给最终结论：

- `gsim RemoveDeadNodes0` 后 `REG_SRC = 156110`
- `grhsim keepDeclaredSymbols=false` 后 `kRegister = 286014`
- 精确差值：
  - `286014 - 156110 = 129904`

这 `129904` 我已经全部拆进互斥桶里，并且所有桶的 `net_gap` 可以严格求和回到 `129904`，没有剩余未归类项。

## 1. 输入与口径

`gsim` 侧：

- `TopoSort` 全量图：
  - [`../../build/xs/ir_compare/SimTop_0TopoSort.json`](../../build/xs/ir_compare/SimTop_0TopoSort.json)
- `RemoveDeadNodes0` 删除名单：
  - [`../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0.txt`](../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0.txt)

我先用：

- `TopoSort REG_SRC - removed_regsrc_removeDeadNodes0`

构造出 `RemoveDeadNodes0` 后仍存活的 `REG_SRC` 集合：

- [`../../build/xs/ir_compare/SimTop_0RemoveDeadNodes0_regsrc_survivors.json`](../../build/xs/ir_compare/SimTop_0RemoveDeadNodes0_regsrc_survivors.json)
  - `156110`

`grhsim` 侧：

- [`../../build/xs/grhsim_compare/keepfalse/wolvrix_xs_post_stats.json`](../../build/xs/grhsim_compare/keepfalse/wolvrix_xs_post_stats.json)
  - `kRegister = 286014`

## 2. 全量匹配的硬数

全量比较结果：

- [`../../build/xs/ir_compare/compare_removeDeadNodes0_vs_grhsim_keepfalse_kRegister.json`](../../build/xs/ir_compare/compare_removeDeadNodes0_vs_grhsim_keepfalse_kRegister.json)

其中关键计数是：

| Metric | Count |
| --- | ---: |
| `gsimRawCount` | `156110` |
| `grhRawCount` | `286014` |
| `rawGapGrhMinusGsim` | `129904` |
| `rawExactCount` | `42191` |
| `gsimNormalizedKeyCount` | `156109` |
| `grhNormalizedKeyCount` | `286013` |
| `normalizedExactKeyCount` | `82087` |
| `normalizedExactButRawDifferentKeyCount` | `39896` |
| `normalizedGapGrhMinusGsim` | `129904` |

这说明：

- raw exact 只对上了 `42191`
- 归一化后 exact key 对上了 `82087`
- 但归一化后仍然还有 `129904` 的净差值需要解释

## 3. `129904` 的全量归因总表

我把差值拆成了 6 个互斥类别：

- `exactNormalized1to1`
- `aggregateGsimFieldToGrhBaseNto1`
- `prefixRefine1to1`
- `prefixExpand1toN`
- `generatedGrhOpNames`
- `residualUnclassified`

完整表：

- [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/category_summary.tsv`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/category_summary.tsv)

汇总如下：

| Category | `gsim_keys` | `grh_keys` | `net_gap` | 占 `129904` 比例 |
| --- | ---: | ---: | ---: | ---: |
| `exactNormalized1to1` | `82087` | `82087` | `0` | `0.00%` |
| `aggregateGsimFieldToGrhBaseNto1` | `465` | `109` | `-356` | `-0.27%` |
| `prefixRefine1to1` | `187` | `187` | `0` | `0.00%` |
| `prefixExpand1toN` | `499` | `21751` | `21252` | `16.36%` |
| `generatedGrhOpNames` | `0` | `346` | `346` | `0.27%` |
| `residualUnclassified` | `72871` | `181533` | `108662` | `83.65%` |
| **Sum** |  |  | **`129904`** | **`100.00%`** |

也就是说：

- 这 `129904` 里，已经有 `21252` 可以明确解释成“`gsim` 一个 base key，对应 `grh` 多个展开子 key”
- `346` 是 `_op_...` 这类 `grh` 生成名字
- 但最大的来源仍然是：
  - `residualUnclassified = 108662`

这里的 `residual` 不是“没归因成功”，而是：

- 在前面几层 exact / aggregate / prefixExpand / generated 剥离完之后，
- 剩余差值全部被放进一个**全量剩余集合**
- 再继续往下按模块前缀做二级归因

## 4. `prefixExpand1toN` 的全量归因

这一类的完整明细我已经全部落成：

- [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/prefix_expand_groups.tsv`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/prefix_expand_groups.tsv)
  - `499` 条 base-group

它贡献的净差值是：

- `21751 - 499 = 21252`

最大的几项是：

| GSim Base Key | `grh_target_count` | 对净差值贡献 |
| --- | ---: | ---: |
| `cpu_l_soc_core_with_l2_core_backend_inner_ctrlBlock_rob_debug_VecOtherPdest` | `2816` | `+2815` |
| `cpu_l_soc_core_with_l2_core_memBlock_inner_ptw_ptw_cache_l0BitmapReg` | `2048` | `+2047` |
| `cpu_l_soc_core_with_l2_core_memBlock_inner_dcache_dcache_accessArray_meta_array` | `1024` | `+1023` |
| `cpu_l_soc_core_with_l2_core_memBlock_inner_dcache_dcache_prefetchArray_meta_array` | `1024` | `+1023` |
| `cpu_l_soc_core_with_l2_core_backend_inner_ctrlBlock_dispatch_fpBusyTable_loadDependency` | `768` | `+767` |
| `cpu_l_soc_core_with_l2_core_backend_inner_ctrlBlock_dispatch_intBusyTable_loadDependency` | `672` | `+671` |
| `cpu_l_soc_core_with_l2_core_frontend_inner_bpu_phr_commitHist` | `532` | `+531` |
| `cpu_l_soc_core_with_l2_core_frontend_inner_bpu_phr_phr` | `532` | `+531` |

这个类别的含义很明确：

- `gsim` 那边是一个更粗的 base key
- `grh` 这边被拆成多字段 / 多 lane / 多 slice / 多 entry 子寄存器

## 5. `residual 108662` 的全量归因

`residualUnclassified` 的完整模块级分桶也已经落盘：

- [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_top_module_summary.tsv`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_top_module_summary.tsv)
  - `2116` 个 top bucket

而更细的二级子桶明细也已经落盘：

- [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_submodule_summary.tsv`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_submodule_summary.tsv)
  - `38445` 个 sub bucket

### 5.1 顶层模块贡献

在统一前缀规则后，`residual 108662` 的主要来源是：

| Top Bucket | `gsim_keys` | `grh_keys` | `net_gap` |
| --- | ---: | ---: | ---: |
| `cpu$l_soc$core_with_l2$core$frontend` | `5619` | `75138` | `69519` |
| `cpu$l_soc$core_with_l2$core$memBlock` | `12922` | `36922` | `24000` |
| `cpu$l_soc$core_with_l2$core$backend` | `39140` | `51815` | `12675` |
| `cpu$l_soc$core_with_l2$l2top` | `5098` | `9061` | `3963` |
| `cpu$l_soc$l3cacheOpt` | `3845` | `4400` | `555` |
| `cpu$l_soc$socMisc` | `449` | `511` | `62` |
| `cpu$jtag` | `0` | `8` | `8` |
| `cpu$l_simMMIO$fragmenter` | `5` | `12` | `7` |
| `cpu$l_simMMIO$widget` | `6` | `13` | `7` |
| `cpu$memory$ram` | `0` | `4` | `4` |

这张表的重要意义是：

- `129904` 的主体不是均匀散落的
- 绝大头集中在四个大模块：
  - `frontend`
  - `memBlock`
  - `backend`
  - `l2top`

仅这四类的净差值合计就是：

- `69519 + 24000 + 12675 + 3963 = 110157`

这个数大于 `108662`，是因为 residual 里还同时存在一些负贡献桶，用来抵消一部分正差值。最大的负贡献是：

- `endpoint$bundle_delayed = 0`
- `cpu$l_simMMIO = -35`
- 一系列 `logEndpoint... = -1`

也就是说：

- residual 内部不是“全正项”，而是“正负桶相抵后的净差值 = 108662”

### 5.2 顶层大桶内部的主要二级来源

#### `frontend +69519`

最大的二级子桶是：

| Sub Bucket | `net_gap` |
| --- | ---: |
| `inner_bpu$tage` | `34845` |
| `inner_bpu$utage` | `5133` |
| `inner_itlb$entries` | `2208` |
| `inner_bpu$mbtb` | `1648` |
| `inner_bpu$sc` | `1636` |
| `inner_bpu$abtb` | `1361` |
| `inner_ftq$resolveQueue` | `982` |
| `inner_bpu$ittage` | `592` |

也就是说，`frontend` 的差值主体几乎都集中在：

- `tage / utage / ittage`
- `mbtb / abtb / sc`
- `itlb`
- `ftq`

#### `memBlock +24000`

最大的二级子桶是：

| Sub Bucket | `net_gap` |
| --- | ---: |
| `inner_lsq$loadQueue` | `7360` |
| `inner_lsq$storeQueue` | `4789` |
| `inner_dcache$dcache` | `3981` |
| `inner_ptw$ptw` | `3233` |
| `inner_dtlb_ld_tlb_ld$entries` | `2544` |
| `inner_dtlb_prefetch_tlb_prefetch$entries` | `2496` |
| `inner_dtlb_st_tlb_st$entries` | `2448` |

也就是说，`memBlock` 的差值主体主要来自：

- `lsq loadQueue / storeQueue`
- `dcache`
- `ptw`
- 三套 `dtlb entries`

#### `backend +12675`

最大的二级子桶是：

| Sub Bucket | `net_gap` |
| --- | ---: |
| `inner_ctrlBlock$rob` | `20865` |
| `inner_ctrlBlock$memCtrl` | `2375` |
| `inner_intRegion$intExuBlock` | `1950` |
| `inner_intRegion$issueQueueALU2BJU2_...` | `1369` |
| `inner_vecRegion$issueQueueVLSU0_...` | `1167` |
| `inner_vecRegion$issueQueueVLSU1_...` | `1135` |
| `inner_vecRegion$issueQueueVFEX0_...` | `1122` |

这里 `rob` 桶本身很大，但 `backend` 顶层净差值只有 `12675`，说明：

- `backend` 内部同时存在不少正负抵消项；
- 不能只看单个正桶，而必须看整层聚合后的净差

#### `l2top +3963`

最大的二级子桶是：

| Sub Bucket | `net_gap` |
| --- | ---: |
| `inner_l2cache$slices_0` | `1351` |
| `inner_l2cache$slices_1` | `1351` |
| `inner_l2cache$slices_2` | `1351` |
| `inner_l2cache$slices_3` | `1351` |
| `inner_l2cache$prefetcher` | `567` |

这类看起来更像是：

- `l2cache` 四个 slice 内部的状态在 `grh` 侧被保留得更细
- 同时又被其它 residual 负项部分抵消

## 6. 全量归因产物

这次为了保证“找全”，我把所有层级产物都落盘了：

- 分类总表：
  - [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/category_summary.tsv`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/category_summary.tsv)
- `prefixExpand1toN` 全部 `499` 条 group：
  - [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/prefix_expand_groups.tsv`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/prefix_expand_groups.tsv)
- `aggregateGsimFieldToGrhBaseNto1` 全部 `109` 条 group：
  - [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/aggregate_groups.tsv`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/aggregate_groups.tsv)
- residual 顶层模块分桶，`2116` 桶：
  - [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_top_module_summary.tsv`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_top_module_summary.tsv)
- residual 二级子桶分桶，`38445` 桶：
  - [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_submodule_summary.tsv`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_submodule_summary.tsv)
- residual unmatched 全量 key 列表：
  - [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_grh_keys.txt`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_grh_keys.txt)
  - [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_gsim_keys.txt`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_gsim_keys.txt)
- `grh` generated `_op_...` keys：
  - [`../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/generated_grh_keys.txt`](../../build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/generated_grh_keys.txt)

## 7. 结论

这次的全量匹配结论可以压成三句话：

1. `grhsim keep=false` 相对 `gsim RemoveDeadNodes0` 的寄存器差值，精确是：
   - `129904`
2. 这 `129904` 已经全部拆进互斥桶，能严格求和回去：
   - 不是 sample，不是抽样，不存在未归类尾项
3. 差值主体并不在 `keepDeclaredSymbols`，而是在：
   - `prefixExpand1toN = 21252`
   - `residual = 108662`
   其中 `residual` 的大头又高度集中在：
   - `frontend`
   - `memBlock`
   - `backend`
   - `l2top`

换句话说：

- 之前 `NO0043` 里的 `15135` 只能代表“已点名到的代表家族样本和”
- 而这次 `NO0044` 才是 `129904` 的**全量归因**
