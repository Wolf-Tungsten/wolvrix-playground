# NO0040 GSim 被删 `REG_SRC` 在 GrhSIM Post-Stats 中的存活检查（2026-04-28）

> 归档编号：`NO0040`。目录顺序见 [`README.md`](./README.md)。

这份记录承接 [`NO0039`](./NO0039_gsim_removed_regsrc_in_removeDeadNodes0_classification_20260428.md)。

目标不是再分析 `128745` 个被删 `NODE_REG_SRC` 的来源，而是回答一个更窄的问题：

- 在 `NO0039` 提到的几类代表性寄存器里，那些在 `gsim RemoveDeadNodes0` 中被删掉的状态，在当前 `grhsim` 的 `build/xs/grhsim/wolvrix_xs_post_stats.json` 里是否还作为 `kRegister` 存活？

先给结论：

- `core.backend`、`core.memBlock(exceptionVec)`、`l2top.inner`、`core.frontend(foldedHist / respReg)` 这些代表类，在 `grhsim` post-stats 里明显还活着。
- 有几类我目前在 `grhsim` 的 `kRegister` 声明里完全搜不到：
  - `core.memBlock srcLoadDependency`
  - `core.frontend randomData_lfsr`
  - `l3cacheOpt bypass_mask`
  - `l3cacheOpt bypass_wdata_lfsr`
- `l3cacheOpt c_mask_latch / bc_mask_latch` 属于“部分还活着”：`gsim` 删除的是少量高位切片，而 `grhsim` 里还能搜到同家族寄存器。

## 1. 数据来源

`gsim` 侧输入：

- 被 `RemoveDeadNodes0` 删除的 `REG_SRC` 总名单：
  - [`../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0.txt`](../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0.txt)

`grhsim` 侧输入：

- post-stats 原始文件：
  - [`../../build/xs/grhsim/wolvrix_xs_post_stats.json`](../../build/xs/grhsim/wolvrix_xs_post_stats.json)

为避免反复扫描 `3.3G` 的原始 JSON，我先抽取了其中全部 `kRegister` 声明 symbol：

- [`../../build/xs/grhsim/wolvrix_xs_post_kregister_symbols.txt`](../../build/xs/grhsim/wolvrix_xs_post_kregister_symbols.txt)

数量：

- `grhsim post-stats kRegister count = 311336`

此外还抽取了全部 `regSymbol` 引用集合做交叉校验，结果数量同样是 `311336`：

- [`../../build/xs/grhsim/wolvrix_xs_post_kregsymbol_readwrite.txt`](../../build/xs/grhsim/wolvrix_xs_post_kregsymbol_readwrite.txt)

代表样本检查表：

- [`../../build/xs/ir_compare/removed_regsrc_vs_grhsim_representative_checks.tsv`](../../build/xs/ir_compare/removed_regsrc_vs_grhsim_representative_checks.tsv)

## 2. 匹配方法

这次我没有直接做“全量 128745 对 311336”的逐条精确对齐，而是对 `NO0039` 里最有代表性的家族做三层匹配：

1. `exact_alive`
   `gsim` 删除样本名在 `grhsim kRegister sym` 中 raw exact 存在。
2. `normalized_alive`
   允许一层温和归一化后 exact 命中：
   - `$$ -> $`
   - `$ -> _`
3. `fuzzy_alive`
   在同一大模块前缀下，用代表 family token 做模糊匹配，例如：
   - `core.backend.*fuType`
   - `core.memBlock.*exceptionVec`
   - `l2top.inner.*alias`

如果三层都没有命中，则记为：

- `not_found`

这里要特别强调：

- `not_found` 只表示“我没有在 `grhsim post-stats` 的 `kRegister` 声明集合里找到这类寄存器”。
- 它不自动等价于“语义完全消失”。
- 可能的原因还包括：
  - 在 `grhsim` 中被聚合进别的更粗状态名
  - 不再作为 `kRegister` 出现，而是变成 memory / 其它 stateful form
  - 名字变化超出了这次 fuzzy 规则

## 3. 代表类检查总表

| Group | Family | Status | `gsim` Removed Count | `grhsim` Alive Count | 结论 |
| --- | --- | --- | ---: | ---: | --- |
| `core.backend` | `fuType` | `fuzzy_alive` | `13211` | `3486` | 明显仍存活 |
| `core.backend` | `loadDependency` | `fuzzy_alive` | `2367` | `1917` | 明显仍存活 |
| `core.backend` | `v0Wen/vecWen/vlWen` | `fuzzy_alive` | `3212` | `1900` | 明显仍存活 |
| `core.memBlock` | `exceptionVec` | `normalized_alive` | `2631` | `4459` | 名字归一化后可直接对上 |
| `core.memBlock` | `forwardData/forwardMask` | `fuzzy_alive` | `3048` | `48` | 仍存活，但数量远小于 `gsim` 删除量 |
| `core.memBlock` | `srcLoadDependency` | `not_found` | `1752` | `0` | 当前未找到对应 `kRegister` |
| `l2top.inner` | `alias` | `fuzzy_alive` | `792` | `456` | 明显仍存活 |
| `l2top.inner` | `dirty/dataErr/tagErr` | `fuzzy_alive` | `1804` | `664` | 明显仍存活 |
| `l2top.inner` | `prefetch/state` | `fuzzy_alive` | `1848` | `2528` | 明显仍存活 |
| `core.frontend` | `foldedHist` | `fuzzy_alive` | `444` | `2276` | 明显仍存活 |
| `core.frontend` | `randomData_lfsr` | `not_found` | `376` | `0` | 当前未找到对应 `kRegister` |
| `core.frontend` | `respReg/rdataReg` | `normalized_alive` | `360` | `360` | 名字归一化后直接一一对应 |
| `l3cacheOpt` | `bypass_mask` | `not_found` | `752` | `0` | 当前未找到对应 `kRegister` |
| `l3cacheOpt` | `bypass_wdata_lfsr` | `not_found` | `476` | `0` | 当前未找到对应 `kRegister` |
| `l3cacheOpt` | `c_mask_latch` | `fuzzy_alive` | `12` | `60` | 同家族仍存活 |
| `l3cacheOpt` | `bc_mask_latch` | `fuzzy_alive` | `8` | `56` | 同家族仍存活 |

## 4. 代表样本细看

### 4.1 `core.backend / fuType`：`gsim` 删了，但 `grhsim` 明显还保留很多

`gsim` 删除样本：

- `cpu$l_soc$core_with_l2$core$backend$inner$vecRegion$issueQueueVLSU1_VlduVstu$entries$othersEntriesComp_11$entryReg$$status$$fuType_35`

`grhsim` 命中样例：

- `cpu$l_soc$core_with_l2$core$backend$inner_ctrlBlock$enqRob_req_0_bits_r_fuType`

结论：

- 没有 raw exact 命中。
- 但在 `core.backend` 下，`fuType` 家族仍有 `3486` 个 `kRegister`。
- 这说明“`gsim` 第一轮就能裁掉的大量 `fuType` 读端状态”，在 `grhsim` post-stats 里仍然显著存在。

### 4.2 `core.memBlock / exceptionVec`：可归一化后一一命中

`gsim` 删除样本：

- `cpu$l_soc$core_with_l2$core$memBlock$inner$VlSplitConnectLdu_1$data$$uop$$exceptionVec_21`

`grhsim` 归一化 exact 命中：

- `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_21`

结论：

- 这类不是“同家族还在”，而是“同一状态在 `grhsim` 里基本还活着，只是层级分隔从 `$$` 变成了 `_`”。
- 这说明 `exceptionVec` 是当前最强的“`gsim` 已删、`grhsim` 仍保留”证据之一。

### 4.3 `core.memBlock / srcLoadDependency`：当前没搜到

`gsim` 删除样本：

- `cpu$l_soc$core_with_l2$core$memBlock$inner$VlSplitConnectLdu_1$data$$uop$$srcLoadDependency_3_2`

结果：

- raw exact：无
- normalized exact：无
- fuzzy family：`0`

结论：

- 在 `grhsim post-stats` 的 `kRegister` 声明里，我当前搜不到这类状态。
- 这类更像是已经被 `grhsim` 改写掉、聚合掉，或根本不再作为独立 `kRegister` 保留。

### 4.4 `l2top.inner / alias`：仍明显存活

`gsim` 删除样本：

- `cpu$l_soc$core_with_l2$l2top$inner$l2cache$slices_3$sinkC$taskBuf$$snpHitReleaseMeta$$alias`

`grhsim` 命中样例：

- `cpu$l_soc$core_with_l2$l2top$inner_l2cache$slices_0$reqArb$mshr_task_s1_bits_alias`

结论：

- `alias` 在 `gsim` 第一轮 dead-node 删除里被删了不少；
- 但 `grhsim` 当前 `kRegister` 里仍有 `456` 个同家族状态。

### 4.5 `core.frontend / foldedHist`：仍明显存活

`gsim` 删除样本：

- `cpu$l_soc$core_with_l2$core$frontend$inner$bpu$tage$t1_foldedHist$$forIdx_7`

`grhsim` 命中样例：

- `cpu$l_soc$core_with_l2$core$frontend$inner_bpu$s2_phrMeta_predFoldedHist_hist_31_foldedHist`

结论：

- `foldedHist` 家族在 `grhsim` 里保留得很明显，`kRegister` 数量甚至达到 `2276`。

### 4.6 `core.frontend / respReg`：归一化后直接一一对应

`gsim` 删除样本：

- `cpu$l_soc$core_with_l2$core$frontend$inner$icache$metaArray$banks_1$tagArray$array_0_1_0$respReg`

`grhsim` 归一化 exact 命中：

- `cpu$l_soc$core_with_l2$core$frontend$inner_icache$metaArray$banks_1$tagArray$array_0_1_0$respReg`

结论：

- 这类状态与 `exceptionVec` 类似，说明不是简单“同类还在”，而是“同一项状态在 `grhsim` 中仍是活的 register，只是层级拼接方式略变”。

### 4.7 `core.frontend / randomData_lfsr`：当前没搜到

`gsim` 删除样本：

- `cpu$l_soc$core_with_l2$core$frontend$inner$icache$metaArray$banks_1$tagArray$array_0_1_0$randomData_lfsr_1`

结果：

- fuzzy family：`0`

结论：

- 这类在 `grhsim` 当前 `kRegister` 里没有直接证据。

### 4.8 `l3cacheOpt / bypass_mask` 与 `bypass_wdata_lfsr`：当前没搜到

`gsim` 删除样本：

- `cpu$l_soc$l3cacheOpt$slices_3$directory$selfDir$tagArray$bypass_mask_waddr_reg`
- `cpu$l_soc$l3cacheOpt$slices_3$directory$selfDir$tagArray$bypass_wdata_lfsr_9`

结果：

- `bypass_mask` family：`0`
- `bypass_wdata_lfsr` family：`0`

结论：

- 这是另一组强信号：`gsim` 已删掉的 L3 bypass 辅助状态，在当前 `grhsim kRegister` 里也看不到。

### 4.9 `l3cacheOpt / c_mask_latch`、`bc_mask_latch`：同家族部分仍活

`gsim` 删除样本：

- `cpu$l_soc$l3cacheOpt$slices_3$c_mask_latch_15`
- `cpu$l_soc$l3cacheOpt$slices_3$bc_mask_latch_15`

`grhsim` 命中样例：

- `cpu$l_soc$l3cacheOpt$slices_0$c_mask_latch_0`
- `cpu$l_soc$l3cacheOpt$slices_0$bc_mask_latch_0`

结论：

- `gsim` 删除的是少量高位 / 局部实例；
- `grhsim` 里同家族寄存器仍然很多：
  - `c_mask_latch = 60`
  - `bc_mask_latch = 56`

这更像是“部分实例被 `gsim` 裁掉，但该类状态在 `grhsim` 里总体仍活着”。

## 5. 汇总结论

从这批代表类看，当前 `grhsim post-stats` 相对 `gsim RemoveDeadNodes0` 的关系可以粗分成三类：

### 5.1 `gsim` 删了，但 `grhsim` 里明显还活着

代表：

- `core.backend fuType`
- `core.backend loadDependency`
- `core.backend v0Wen/vecWen/vlWen`
- `core.memBlock exceptionVec`
- `l2top.inner alias`
- `l2top.inner dirty/dataErr/tagErr`
- `l2top.inner prefetch/state`
- `core.frontend foldedHist`
- `core.frontend respReg/rdataReg`

这类最值得后续继续追，因为它们直接说明：

- `gsim` 早期 dead-node 剪掉的某些状态，在 `grhsim` 当前设计里并没有同步消失。

### 5.2 `gsim` 删了，`grhsim` 里也基本看不到

代表：

- `core.memBlock srcLoadDependency`
- `core.frontend randomData_lfsr`
- `l3cacheOpt bypass_mask`
- `l3cacheOpt bypass_wdata_lfsr`

这类说明：

- 并不是所有 `gsim` 删除状态都会在 `grhsim` 残留。
- 当前 `grhsim` 至少已经没有无脑保留所有这类内部状态。

### 5.3 `gsim` 删了部分实例，但 `grhsim` 同家族仍然存活

代表：

- `l3cacheOpt c_mask_latch`
- `l3cacheOpt bc_mask_latch`

这类说明：

- 差异可能不在“这个家族有没有”，而在“哪些 slice / 哪些位 / 哪些实例仍然活着”。

## 6. 下一步建议

如果后续要把这件事继续做深，我建议优先按下面顺序推进：

1. 先追 `normalized_alive` 的两类：
   - `core.memBlock exceptionVec`
   - `core.frontend respReg/rdataReg`
   
   这两类最容易做成严格一一对照，能直接定位：
   - `gsim` 为什么删了
   - `grhsim` 为什么还留着

2. 再追 `fuzzy_alive` 但数量很大的后端类：
   - `fuType`
   - `loadDependency`
   - `v0Wen/vecWen/vlWen`

3. 最后再追 `not_found` 类，确认它们是：
   - 真没了
   - 被聚合了
   - 还是换了一套完全不同的 state 命名

当前这一步已经足够说明一个重要事实：

- `gsim RemoveDeadNodes0` 裁掉的一批代表性寄存器里，确实有不少在当前 `grhsim post-stats` 中仍然作为 `kRegister` 存活。
