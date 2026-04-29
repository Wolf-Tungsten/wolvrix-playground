# NO0043 GSim 被删 `REG_SRC` 在 GrhSIM `keepDeclaredSymbols=false` Post-Stats 中的存活检查（2026-04-29）

> 归档编号：`NO0043`。目录顺序见 [`README.md`](./README.md)。

这份记录直接承接两篇前文：

- [`NO0040`](./NO0040_gsim_removed_regsrc_vs_grhsim_post_stats_survival_20260428.md)
  - 基于默认 `grhsim post-stats` 的代表类对照
- [`NO0042`](./NO0042_grhsim_keep_declared_symbols_ab_compare_20260428.md)
  - 证明 `WOLVRIX_XS_GRHSIM_SIMPLIFY_KEEP_DECLARED_SYMBOLS=0` 开关真实生效

这次要回答的是更进一步的问题：

- `NO0040` 的结论里，有多少是被 `keepDeclaredSymbols=true` 放大的？
- 如果改用 `keepDeclaredSymbols=false` 的 `grhsim post-stats`，相对 `gsim RemoveDeadNodes0`，`grhsim` 还会多保留哪些代表类寄存器？

先给结论：

- `NO0040` 确实是默认 `keepDeclaredSymbols=true` 口径；把这个保护关掉后，代表类里有一批状态会明显收缩，甚至直接消失。
- 其中最典型的“原先主要靠 symbol 保活”的一类是：
  - `core.frontend respReg/rdataReg`
    - `keeptrue = 360`
    - `keepfalse = 0`
- 但还有几类在 `keep=false` 下仍然明显大量存活，说明它们不是单纯靠 declared symbol 保护，而是还有更深层的保留原因：
  - `core.memBlock exceptionVec`
  - `core.frontend foldedHist`
  - `core.backend loadDependency`
  - `core.backend v0Wen/vecWen/vlWen`
  - `l2top.inner prefetch/state`
  - `core.backend fuType`

其中最强的两个信号是：

- `exceptionVec`
  - 代表样本 `exceptionVec_21` 本人已经在 `keep=false` 下消失
  - 但整个 `exceptionVec` 家族仍有 `4395` 个 `kRegister`
- `foldedHist`
  - `keeptrue = 2276`
  - `keepfalse = 2276`
  - 基本完全不受 `keepDeclaredSymbols` 开关影响

## 1. 数据来源

`gsim` 侧输入不变：

- [`../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0.txt`](../../build/xs/ir_compare/removed_regsrc_removeDeadNodes0.txt)

`grhsim keep=false` 侧输入改为：

- [`../../build/xs/grhsim_compare/keepfalse/wolvrix_xs_post_stats.json`](../../build/xs/grhsim_compare/keepfalse/wolvrix_xs_post_stats.json)

为避免反复扫描原始 JSON，这次同样先抽取 `kRegister` 声明集合：

- [`../../build/xs/grhsim_compare/keepfalse/wolvrix_xs_post_kregister_symbols.txt`](../../build/xs/grhsim_compare/keepfalse/wolvrix_xs_post_kregister_symbols.txt)
  - `286014`
- [`../../build/xs/grhsim_compare/keepfalse/wolvrix_xs_post_kregsymbol_readwrite.txt`](../../build/xs/grhsim_compare/keepfalse/wolvrix_xs_post_kregsymbol_readwrite.txt)
  - `286014`

新的代表样本对照表：

- [`../../build/xs/ir_compare/removed_regsrc_vs_grhsim_keepfalse_representative_checks.tsv`](../../build/xs/ir_compare/removed_regsrc_vs_grhsim_keepfalse_representative_checks.tsv)

这个新表直接复用了 `NO0040` 的同一批代表家族与同一套 regex，只是把 `grhsim` 侧集合换成了 `keep=false` 的 `kRegister` symbols。

## 2. 方法说明

方法与 `NO0040` 保持一致：

1. `exact_alive`
   - `gsim` 删除样本名 raw exact 出现在 `grhsim kRegister` 集合中
2. `normalized_alive`
   - 对 `gsim` 名字做温和归一化后 exact 命中
   - 规则仍是：
     - `$$ -> $`
     - `$ -> _`
3. `fuzzy_alive`
   - 代表样本本人没了，但同一模块前缀下的同家族 regex 仍命中
4. `not_found`
   - 在 `keep=false` 的 `kRegister` 集合中完全搜不到

这次我额外把 `keeptrue` 与 `keepfalse` 并排放在一张表里，用来区分：

- 哪些是关掉 declared-symbol 保护后就没了
- 哪些虽然缩了，但仍明显多保留
- 哪些几乎不受这个开关影响

## 3. 代表类对照总表

| Group | Family | `gsim` Removed | `keeptrue` Alive | `keepfalse` Alive | Delta | `keepfalse` Status | 结论 |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `core.backend` | `fuType` | `13211` | `3486` | `1726` | `-1760` | `fuzzy_alive` | 缩了一半，但仍明显存活 |
| `core.backend` | `loadDependency` | `2367` | `1917` | `1917` | `0` | `fuzzy_alive` | 基本不受影响，仍大量存活 |
| `core.backend` | `v0Wen/vecWen/vlWen` | `3212` | `1900` | `1896` | `-4` | `fuzzy_alive` | 几乎不受影响 |
| `core.memBlock` | `exceptionVec` | `2631` | `4459` | `4395` | `-64` | `fuzzy_alive` | 样本本人可被清掉，但家族总体仍大量保留 |
| `core.memBlock` | `forwardData/forwardMask` | `3048` | `48` | `48` | `0` | `fuzzy_alive` | 仅少量保留，且不受影响 |
| `core.memBlock` | `srcLoadDependency` | `1752` | `0` | `0` | `0` | `not_found` | 两边都搜不到 |
| `l2top.inner` | `alias` | `792` | `456` | `356` | `-100` | `fuzzy_alive` | 有收缩，但仍明显存活 |
| `l2top.inner` | `dirty/dataErr/tagErr` | `1804` | `664` | `268` | `-396` | `fuzzy_alive` | 收缩较明显，但仍保留不少 |
| `l2top.inner` | `prefetch/state` | `1848` | `2528` | `2137` | `-391` | `fuzzy_alive` | 收缩后仍比 `gsim` 删除量更大 |
| `core.frontend` | `foldedHist` | `444` | `2276` | `2276` | `0` | `fuzzy_alive` | 完全不受影响，仍是强保留信号 |
| `core.frontend` | `randomData_lfsr` | `376` | `0` | `0` | `0` | `not_found` | 两边都搜不到 |
| `core.frontend` | `respReg/rdataReg` | `360` | `360` | `0` | `-360` | `not_found` | 典型 declared-symbol 保活项，关掉后直接消失 |
| `l3cacheOpt` | `bypass_mask` | `752` | `0` | `0` | `0` | `not_found` | 两边都搜不到 |
| `l3cacheOpt` | `bypass_wdata_lfsr` | `476` | `0` | `0` | `0` | `not_found` | 两边都搜不到 |
| `l3cacheOpt` | `c_mask_latch` | `12` | `60` | `60` | `0` | `fuzzy_alive` | 不受影响，仍明显多保留 |
| `l3cacheOpt` | `bc_mask_latch` | `8` | `56` | `56` | `0` | `fuzzy_alive` | 不受影响，仍明显多保留 |

## 4. 哪些是 `keep=true` 放大的

### 4.1 `respReg/rdataReg`：最典型的“关掉 symbol 保护后直接没了”

这是这轮对照里最干净的 case。

`NO0040` 中它的状态是：

- `normalized_alive`
- `keeptrue_alive_count = 360`

但在 `keep=false` 下：

- `keepfalse_alive_count = 0`
- status 直接变成 `not_found`

代表样本：

- `cpu$l_soc$core_with_l2$core$frontend$inner$icache$metaArray$banks_1$tagArray$array_0_1_0$respReg`

在 `keep=true` 中仍能看到完整 register/read/write 链：

- [`../../build/xs/grhsim_compare/keeptrue/wolvrix_xs_post_stats.json`](../../build/xs/grhsim_compare/keeptrue/wolvrix_xs_post_stats.json)
  - `37053`：symbol
  - `6454044`：`kRegister`
  - `6454045`：`kRegisterReadPort`
  - `6454138`：`kRegisterWritePort`

而在 `keep=false` 中 raw exact 已经完全搜不到。

这说明：

- `respReg/rdataReg` 是本轮最强的 declared-symbol 保活证据之一。

### 4.2 `fuType`、`alias`、`dirty/dataErr/tagErr`、`prefetch/state`

这几类不是“完全靠 symbol 活着”，但 `keep=true` 明显放大了它们的保留规模：

- `fuType`
  - `3486 -> 1726`
- `alias`
  - `456 -> 356`
- `dirty/dataErr/tagErr`
  - `664 -> 268`
- `prefetch/state`
  - `2528 -> 2137`

也就是说：

- declared-symbol 保护对这些家族有实质影响；
- 但即使关掉之后，它们仍然没有被 `grhsim` 清到接近 `gsim` 的程度。

## 5. 哪些即使 `keep=false` 仍明显多保留

### 5.1 `exceptionVec`：样本本人可删，但家族总体几乎没动

这是当前最值得注意的一类。

`NO0042` 已经证明：

- 代表样本
  - `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_21`
- 在 `keep=true` 下存在
- 在 `keep=false` 下已经消失

也就是说：

- 这个具体 `bit 21` 之前活着，确实主要是 declared-symbol 保护。

但如果看整个家族计数：

- `keeptrue = 4459`
- `keepfalse = 4395`
- 只减少了 `64`

这说明：

- `exceptionVec` 家族里确实有一批“纯 symbol 保活”的成员；
- 但相对于整个家族规模，这批只是少数；
- `grhsim` 对 `exceptionVec` 的大头保留原因，并不能简单归结为 `keepDeclaredSymbols=true`。

换句话说：

- `exceptionVec_21` 这个代表样本已经被解释了；
- 但 `exceptionVec` 家族整体为什么还保留 `4395` 个 `kRegister`，仍然是后续需要继续拆解的问题。

### 5.2 `foldedHist`：完全不受 `keepDeclaredSymbols` 影响

这是另一类强信号：

- `keeptrue = 2276`
- `keepfalse = 2276`
- `delta = 0`

而 `gsim` 这类代表样本的删除量只有：

- `444`

所以 `foldedHist` 的结论非常明确：

- 它不是 declared-symbol 保护造成的假阳性；
- 在当前 `grhsim` IR 里，这类状态就是整体被大规模保留下来了。

### 5.3 `loadDependency` 与 `v0Wen/vecWen/vlWen`

这两类在 `keep=false` 下也几乎没动：

- `loadDependency`
  - `1917 -> 1917`
- `v0Wen/vecWen/vlWen`
  - `1900 -> 1896`

这意味着：

- 这两类和 `foldedHist` 一样，保留原因基本不在 declared-symbol 保护层；
- 它们更像是 `grhsim` 当前图中真实还连着、或至少在 pass 语义下仍被判定为 live 的状态。

### 5.4 `l3cacheOpt c_mask_latch / bc_mask_latch`

这两类本来在 `NO0040` 中就很特殊：

- `gsim` 删除量本身很小
  - `12`
  - `8`
- `grhsim` 家族存活数反而明显更大
  - `60`
  - `56`

而这次 `keep=false` 下它们仍然完全不动：

- `60 -> 60`
- `56 -> 56`

所以这两类也不属于 declared-symbol 偏差，而是结构层面的真实差异。

## 6. 当前最值得继续追的“`grhsim` 多保留”家族

如果只看 `keep=false` 后仍然明显多保留、而且规模足够大的家族，我会优先盯下面几类：

1. `core.memBlock exceptionVec`
   - `keepfalse = 4395`
   - 而且代表样本 `bit 21` 已经证明“纯 symbol 保活”只能解释很小一部分
2. `core.frontend foldedHist`
   - `keepfalse = 2276`
   - 对 `keepDeclaredSymbols` 完全不敏感
3. `l2top.inner prefetch/state`
   - `keepfalse = 2137`
   - 仍高于 `gsim` 删除量 `1848`
4. `core.backend loadDependency`
   - `keepfalse = 1917`
   - `keep=true/false` 完全不变
5. `core.backend v0Wen/vecWen/vlWen`
   - `keepfalse = 1896`
   - 几乎完全不变
6. `core.backend fuType`
   - `keepfalse = 1726`
   - 虽然减半，但体量仍然大

### 6.1 当前已定位到的代表家族存活量：`15135`

如果把本页 `keepfalse_alive_count > 0` 的代表家族逐行相加，当前已经明确点名定位到的存活量是：

- `15135`

这里要特别强调：

- 这个 `15135` 不是 `grhsim keep=false` 相对 `gsim` 全量多保留寄存器的完整分类结果；
- 它只是当前这批“代表家族”在 `keep=false` 下仍存活的数量之和；
- 相对全局 `grhsim keep=false kRegister = 286014`，它只覆盖其中一部分；
- 相对你前面给出的 `gsim ~156k` 口径下的约 `130k` 差值，它也只是目前已经被明确点名的一部分。

分布如下：

| Rank | Group | Family | `keepfalse` Alive |
| --- | --- | --- | ---: |
| 1 | `core.memBlock` | `exceptionVec` | `4395` |
| 2 | `core.frontend` | `foldedHist` | `2276` |
| 3 | `l2top.inner` | `prefetch/state` | `2137` |
| 4 | `core.backend` | `loadDependency` | `1917` |
| 5 | `core.backend` | `v0Wen/vecWen/vlWen` | `1896` |
| 6 | `core.backend` | `fuType` | `1726` |
| 7 | `l2top.inner` | `alias` | `356` |
| 8 | `l2top.inner` | `dirty/dataErr/tagErr` | `268` |
| 9 | `l3cacheOpt` | `c_mask_latch` | `60` |
| 10 | `l3cacheOpt` | `bc_mask_latch` | `56` |
| 11 | `core.memBlock` | `forwardData/forwardMask` | `48` |
| Sum |  |  | `15135` |

从这张表也能直接看到：

- 前 `6` 类就占了 `14747 / 15135 = 97.4%`；
- 当前代表类里的“多保留主体”高度集中在：
  - `exceptionVec`
  - `foldedHist`
  - `prefetch/state`
  - `loadDependency`
  - `v0Wen/vecWen/vlWen`
  - `fuType`

## 7. 结论

把 `NO0040` 的默认 `keep=true` 口径换成 `keep=false` 之后，结论可以分成两半：

### 7.1 之前一部分“`grhsim` 还活着”的信号，确实是 symbol 保护放大的

最典型的就是：

- `core.frontend respReg/rdataReg`

这类在 `keep=false` 后可以直接消失。

### 7.2 但 `grhsim` 相对 `gsim` 的“多保留”问题并没有因此消失

因为还有多类家族在 `keep=false` 下仍明显存活，甚至几乎完全不受影响：

- `exceptionVec`
- `foldedHist`
- `loadDependency`
- `v0Wen/vecWen/vlWen`
- `prefetch/state`
- `c_mask_latch / bc_mask_latch`

所以当前最准确的说法是：

- `keepDeclaredSymbols=true` 解释了 `grhsim` 过保留问题中的一部分，但不是主因全貌；
- 关掉它之后，`grhsim` 仍然明显比 `gsim RemoveDeadNodes0` 保留了更多代表类寄存器；
- 其中最值得继续追的是那些在 `keep=false` 下仍大规模存活的家族，而不是已经随着 symbol 保护一起消失的那一批。
