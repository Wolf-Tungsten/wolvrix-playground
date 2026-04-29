# NO0039 GSim `RemoveDeadNodes0` 删除 `NODE_REG_SRC` 分类记录（2026-04-28）

> 归档编号：`NO0039`。目录顺序见 [`README.md`](./README.md)。

这份记录专门回答一个问题：

- `RemoveDeadNodes0` 里被删掉的 `128745` 个 `NODE_REG_SRC`，到底是什么，集中在哪些模块，名字上呈现出什么类型分布。

先给结论：

- 这 `128745` 个被删 `NODE_REG_SRC` 已经从 `TopoSort` 和 `RemoveDeadNodes0` 的图 dump 中精确提取出来。
- 它们高度集中在 `core.backend` 和 `core.memBlock`，两者合计 `108442` 个，占 `84.23%`。
- 如果再加上 `l2top.inner` 和 `core.frontend`，前四大类合计 `125220` 个，占 `97.26%`。
- 这些被删寄存器里，真正长得像“工具显式生成 helper reg”的只占小头：
  - 含 `REG$$` 的 `9477` 个，占 `7.36%`
  - 含 `latch` 的 `183` 个，占 `0.14%`
  - 其余 `119085` 个，占 `92.50%`，本质上是有明确微结构语义名字的状态寄存器

## 1. 数据来源与提取方法

输入数据：

- `TopoSort` 全图 dump：
  - [`../../build/xs/ir_compare/SimTop_0TopoSort.json`](../../build/xs/ir_compare/SimTop_0TopoSort.json)
- 第一轮 dead-node 删除后的图 dump：
  - [`../../build/xs/ir_compare/first_dead/SimTop_0RemoveDeadNodes.json`](../../build/xs/ir_compare/first_dead/SimTop_0RemoveDeadNodes.json)

提取口径：

1. 从 `TopoSort` dump 中读取全部 `type == NODE_REG_SRC` 的节点名。
2. 从 `RemoveDeadNodes0` dump 中读取全部仍然存在的 `type == NODE_REG_SRC` 的节点名。
3. 做集合差：`TopoSort - RemoveDeadNodes0`。

得到精确名单：

- [`../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0.txt`](../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0.txt)

附带 summary：

- group 汇总：
  - [`../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0_group_summary.tsv`](../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0_group_summary.tsv)
- family 汇总：
  - [`../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0_family_summary.tsv`](../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0_family_summary.tsv)
- group 样例：
  - [`../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0_group_samples.tsv`](../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0_group_samples.tsv)

数量核对：

- `TopoSort` 时 `NODE_REG_SRC = 284855`
- `RemoveDeadNodes0` 后 `NODE_REG_SRC = 156110`
- 差值正好是 `128745`

这与上一份阶段变化记录 [`NO0038`](./NO0038_gsim_init_to_graphpartition_stage_changes_20260428.md) 完全一致。

## 2. 分类说明

这次分类不是按“静态猜测这个寄存器为什么死掉”来做，而是按两个维度做稳定归类：

1. 模块层级分类：
   按节点名的层级前缀，把删除的 `REG_SRC` 归到 `backend / memBlock / frontend / l2top / l3cache / socMisc ...`。
2. 名字家族分类：
   取最后一个 `$` token，并去掉末尾的 `_数字` lane 后缀，例如：
   - `fuType_3 -> fuType`
   - `srcLoadDependency_0 -> srcLoadDependency`
   - `REG_1_0_7 -> REG_1_0`

这保证了分类是可复现的，也便于后续继续扩展到 `REG_DST` 或其它 node type。

## 3. 一级分类：按模块层级

| 分类 | 数量 | 占比 |
| --- | ---: | ---: |
| `core.backend` | `61531` | `47.79%` |
| `core.memBlock` | `46911` | `36.44%` |
| `l2top.inner` | `11903` | `9.25%` |
| `core.frontend` | `4875` | `3.79%` |
| `l3cacheOpt` | `2885` | `2.24%` |
| `socMisc` | `309` | `0.24%` |
| `endpoint.delayer` | `198` | `0.15%` |
| `simMMIO` | `120` | `0.09%` |
| `memXbar` | `10` | `0.01%` |
| `other` | `3` | `0.00%` |

几个最重要的汇总：

- `core.backend + core.memBlock = 108442`，占 `84.23%`
- 前四类 `backend + memBlock + l2top.inner + frontend = 125220`，占 `97.26%`
- 加上 `l3cacheOpt` 后，前五类合计 `128105`，占 `99.50%`

这说明第一轮 `RemoveDeadNodes` 删除的 `REG_SRC`，几乎全部都来自核心内部流水线、访存块和片上 cache 层次；外围模块只占极小尾巴。

## 4. 二级分类：按名字形态

按名字形态粗分：

| 分类 | 数量 | 占比 | 说明 |
| --- | ---: | ---: | --- |
| `named_microarch_state` | `119085` | `92.50%` | 有明确业务语义的微结构状态名 |
| `explicit_REG_dollar_dollar` | `9477` | `7.36%` | 含 `REG$$`，典型 split/flatten 后的显式字段寄存器 |
| `latch_named` | `183` | `0.14%` | 名字含 `latch` |

这里最值得注意的是：

- 被删掉的并不主要是编译器辅助生成的“无语义 helper reg”。
- 相反，绝大多数都是具有明确名字的微结构状态寄存器，只是它们在 `RemoveDeadNodes0` 的“从输出 / special / external 回溯可达性”口径下已经不再可观察，因此整条状态链被剪掉。

## 5. 三级分类：全局 top family

下面是删得最多的名字家族：

| Family | 数量 | 占比 |
| --- | ---: | ---: |
| `fuType` | `13345` | `10.37%` |
| `exceptionVec` | `2263` | `1.76%` |
| `loadDependency` | `2079` | `1.61%` |
| `value` | `1907` | `1.48%` |
| `srcType` | `1729` | `1.34%` |
| `valid` | `1549` | `1.20%` |
| `uopIdx` | `1472` | `1.14%` |
| `REG` | `1471` | `1.14%` |
| `psrc` | `1440` | `1.12%` |
| `srcState` | `1408` | `1.09%` |
| `seqNum` | `1288` | `1.00%` |
| `pdest` | `1276` | `0.99%` |
| `runahead_checkpoint_id` | `1270` | `0.99%` |
| `eliminatedMove` | `1270` | `0.99%` |
| `srcLoadDependency_1` | `1266` | `0.98%` |
| `srcLoadDependency_0` | `1266` | `0.98%` |
| `flag` | `1256` | `0.98%` |
| `v0Wen` | `1204` | `0.94%` |
| `vecWen` | `1201` | `0.93%` |
| `vlWen` | `1197` | `0.93%` |

这个分布有两个很明显的特征：

1. 后端 issue/rename/vector 相关状态很多。
2. memBlock 相关的异常、forward、依赖跟踪状态也很多。

所以这批被删寄存器，不像是“几个孤立 debug 寄存器”或“少量 helper signals”，而是大面积的、但最终对 observable outputs 无贡献的流水线内部状态。

## 6. 各大模块内部的主类型

### 6.1 `core.backend`：后端流水线状态为主

总量：`61531`

top family：

- `fuType = 13202`
- `loadDependency = 2079`
- `srcType = 1245`
- `pdest = 1169`
- `uopIdx = 1147`
- `seqNum = 1058`
- `valid = 1056`
- `value = 1054`
- `v0Wen = 1057`
- `vecWen = 1054`
- `vlWen = 1050`
- `fpWen = 1047`
- `rfWen = 1046`
- `pdestVl = 1029`
- `psrc = 956`
- `srcState = 924`

代表样例：

- `cpu$l_soc$core_with_l2$core$backend$inner$vecExcpMod$sWaitRab_idxRangeVec$$until_7`
- `cpu$l_soc$core_with_l2$core$backend$inner$...`

直观上，这一类主要是：

- 后端 uop 元数据
- 各类 rename / dispatch / issue 状态
- vector/fp 写回使能与附属字段

### 6.2 `core.memBlock`：访存块异常 / forward / 依赖状态

总量：`46911`

top family：

- `exceptionVec = 1983`
- `forwardData = 1092`
- `forwardMask = 1092`
- `flag = 722`
- `mask = 673`
- `value = 672`
- `addr = 623`
- `psrc = 484`
- `srcState = 484`
- `srcType = 484`
- `cause = 455`
- `atomic = 437`
- `srcLoadDependency_3/2/1/0 = 354 x 4`

代表样例：

- `cpu$l_soc$core_with_l2$core$memBlock$inner$REG_3$$value_48`
- `cpu$l_soc$core_with_l2$core$memBlock$inner$VlSplitConnectLdu_1$data$$uop$$regCacheIdx_1`

这表明第一轮 dead-node 删除里，访存通路内部很多“异常/依赖/forward”寄存器都被整体裁掉。

### 6.3 `l2top.inner`：L2 cache 元数据与 probe/预取状态

总量：`11903`

top family：

- `alias = 680`
- `dirty = 620`
- `dataErr = 592`
- `tagErr = 592`
- `accessed = 480`
- `prefetchSrc = 480`
- `prefetch = 480`
- `clients = 480`
- `state = 480`

代表样例：

- `cpu$l_soc$core_with_l2$l2top$inner$l2cache$slices_3$prbq$prbq_older_arr_4`
- `cpu$l_soc$core_with_l2$l2top$inner$l2cache$slices_3$prbq$prbq_bits_reg$$corrupt_4`

这类更像是 cache metadata / queue state / coherence 辅助状态。

### 6.4 `core.frontend`：ITLB / 响应缓存 / 随机化状态

总量：`4875`

top family：

- `foldedHist = 428`
- `randomData_lfsr = 376`
- `valid = 189`
- `value = 181`
- `selectOHReg = 180`
- `respReg = 180`
- `rdataReg = 180`
- `conflictRaddrS1 = 180`
- `conflictEarlyS1 = 180`

代表样例：

- `cpu$l_soc$core_with_l2$core$frontend$inner$itlb$ptw_resp_bits_reg$$s1$$pteidx_7`

这部分主要是前端 TLB / resp / predictor 相关状态。

### 6.5 `l3cacheOpt`：数量不大，但类型很集中

总量：`2885`

top family：

- `bypass_wdata_lfsr = 476`
- `bypass_mask_waddr_reg = 188`
- `bypass_mask_raddr_reg = 188`
- `bypass_mask_need_check = 188`
- `bypass_mask_bypass_REG = 188`
- `isHit = 112`
- `sourceId = 96`
- `set = 95`
- `mask = 92`

代表样例：

- `cpu$l_soc$l3cacheOpt$slices_3$c_mask_latch_15`
- `cpu$l_soc$l3cacheOpt$slices_3$bc_mask_latch_15`

这说明 L3 这边被删掉的寄存器，更多是 bypass/mask/lfsr 这类局部辅助状态，而不是大规模主流水线状态。

## 7. 这些删除意味着什么

结合 [`reference/gsim/src/deadNodes.cpp`](../../reference/gsim/src/deadNodes.cpp)，`RemoveDeadNodes0` 的保留根主要是：

- output
- special node
- external node
- 以及从这些根反向可达的依赖链

因此这 `128745` 个被删 `REG_SRC` 的本质含义不是：

- “它们一定是无意义垃圾寄存器”

而是：

- 在 `TopoSort` 之后的这张图上，它们对应的状态读端已经不再影响可观察输出或必须保留的 side effect
- 所以整条寄存器读链在第一轮 dead-node 删除中被批量裁掉

从统计结果看，这种裁剪最主要发生在：

- core backend
- memBlock
- L2/L3 cache 元数据和局部队列状态

也就是“内部状态很多，但真正能流到最终输出的比例没有那么高”的区域。

## 8. 最终结论

这 `128745` 个被 `RemoveDeadNodes0` 删除的 `NODE_REG_SRC`，可以概括成一句话：

- 它们主要不是少量工具生成的 helper reg，而是大批核心内部、访存块和 cache 层次中，已经失去外部可观察性的微结构状态寄存器读端。

最关键的三个数字：

- `84.23%` 来自 `core.backend + core.memBlock`
- `97.26%` 来自前四大类：`backend + memBlock + l2top.inner + frontend`
- `92.50%` 是有明确微结构语义名字的状态，而不是显式 `REG$$` helper

如果后续要继续深挖，我建议下一步不要再从“全量 128745”看，而是挑一个最大的删减热点继续向下拆：

1. `core.backend / fuType + loadDependency + srcType + valid/value`
2. `core.memBlock / exceptionVec + forwardData/Mask + srcLoadDependency_*`
3. `l2top.inner / alias + dirty + dataErr/tagErr + prefetch/state`

这样能更快回答“这些状态为什么在 GSim 图里早期就变成不可观察”，也更利于对照 `grhsim` 当前保留了哪些不必要状态。
