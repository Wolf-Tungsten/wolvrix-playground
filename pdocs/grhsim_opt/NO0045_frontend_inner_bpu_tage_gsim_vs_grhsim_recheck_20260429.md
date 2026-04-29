# NO0045 `frontend inner_bpu$tage` 在 GSim / GrhSIM 中是否“被完全删除”的复核

## 1. 结论

不是。

`gsim` 并没有把 `frontend.inner_bpu$tage` 完全删除。直接对 `SimTop_0TopoSort.json` 与 `SimTop_0RemoveDeadNodes0_regsrc_survivors.json` 做精确集合对比后：

- `TopoSort` 时该前缀下共有 `1725` 个 `NODE_REG_SRC`
- `RemoveDeadNodes0` 之后还剩 `1197`
- 本轮 `RemoveDeadNodes0` 只删除了其中 `528`

对应 `grhsim keepDeclaredSymbols=false` 的同前缀 `kRegister` 数量是 `35666`，因此真实结论是：

- `grhsim` 明显比 `gsim` 多保留了大量 `tage` 相关寄存器
- 但这不等于 `gsim` “把 `tage` 完全删光了”

## 2. 直接计数

### 2.1 GSim `TopoSort`

前缀：

- `cpu$l_soc$core_with_l2$core$frontend$inner$bpu$tage$`

计数：

- `NODE_REG_SRC = 1725`

主要子家族：

| 子家族 | 数量 |
| --- | ---: |
| `tables` | `1208` |
| `t2_readResp` | `64` |
| `t2_branches` | `64` |
| `t1_branches` | `64` |
| `s2_readResp` | `64` |
| `s1_readResp_r` | `64` |
| `t2_meta` | `48` |
| `t1_meta` | `48` |
| `t1_foldedHist` | `16` |
| `s1_foldedHist` | `16` |

### 2.2 GSim `RemoveDeadNodes0` 后存活

同前缀计数：

- `NODE_REG_SRC = 1197`

主要子家族：

| 子家族 | 数量 |
| --- | ---: |
| `tables` | `760` |
| `t2_readResp` | `64` |
| `s2_readResp` | `64` |
| `s1_readResp_r` | `64` |
| `t2_meta` | `40` |
| `t2_branches` | `40` |
| `t1_meta` | `40` |
| `t1_branches` | `40` |
| `t1_foldedHist` | `8` |
| `s1_foldedHist` | `8` |

### 2.3 GSim 被 `RemoveDeadNodes0` 删掉的部分

集合差：

- `1725 - 1197 = 528`

主要被删子家族：

| 子家族 | 数量 |
| --- | ---: |
| `tables` | `448` |
| `t2_branches` | `24` |
| `t1_branches` | `24` |
| `s1_foldedHist` | `8` |
| `t2_meta` | `8` |
| `t1_foldedHist` | `8` |
| `t1_meta` | `8` |

因此，`gsim` 在 `tage` 这一路是“删了一部分”，不是“删干净了”。

## 3. GrhSIM `keepDeclaredSymbols=false` 对照

前缀：

- `cpu$l_soc$core_with_l2$core$frontend$inner_bpu$tage$`

计数：

- `kRegister = 35666`

其中绝大多数来自 `tables` 家族：

| 子家族 | 数量 |
| --- | ---: |
| `tables` | `35088` |
| `useAltOnNaVec` | `128` |

也就是说，这个 case 的巨大差值主体并不是“`gsim` 把整个 `tage` 前缀删没了”，而是：

- `gsim` 只保留了 `1197`
- `grhsim keep=false` 仍保留了 `35666`
- 主差值集中在 `tables`

## 4. 为什么 `residual_submodule_summary.tsv` 看起来像 `0 -> 34845`

`build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_submodule_summary.tsv` 中有一行：

| top_module | sub_bucket | gsim_count | grh_count | net_gap |
| --- | --- | ---: | ---: | ---: |
| `cpu$l_soc$core_with_l2$core$frontend` | `inner_bpu$tage` | `0` | `34845` | `34845` |

这行**不能**直接解释为“`gsim` 的 `tage` 一个都没活下来”，原因有两个。

### 4.1 这张表只统计 residual

它不是总量表，而是：

- 先扣掉 `exactNormalized1to1`
- 再扣掉 `aggregateGsimFieldToGrhBaseNto1`
- 再扣掉 `prefixRefine1to1`
- 再扣掉 `prefixExpand1toN`
- 最后只对剩下的 residual 做分桶

对 `tage` 而言，`prefixExpand` 已经提前吃掉了一部分 `gsim` 存活项。直接看：

- `prefix_expand_groups.tsv` 里有 `66` 个 `tage` 组
- 这 `66` 个 `gsim` 组键对应 `528` 个 `grhsim` 展开键

所以 residual 表天然不是“总 surviving 数”的视角。

### 4.2 这张表的 `gsim / grhsim` 子模块命名口径不统一

`gsim` 用的是：

- `inner$bpu$tage`

`grhsim` 用的是：

- `inner_bpu$tage`

在 residual summary 的二级分桶阶段，这两个口径没有被完全统一，因此 `inner_bpu$tage 0 -> 34845` 这行本身就带有命名偏差，不能拿来判断“`gsim` 总量是否为 0”。

直接扫描 residual 原始 key 文件可以看到：

- `residual_gsim_keys.txt` 中，规范化后以 `cpu_l_soc_core_with_l2_core_frontend_inner_bpu_tage_` 开头的 `gsim` residual key 仍有 `838`
- `residual_grh_keys.txt` 中，对应 `grhsim` residual key 有 `34845`

所以更准确的说法是：

- residual summary 这张表在 `tage` 上会低估 `gsim` 一侧
- 判断“是否完全删除”必须回到原始 `TopoSort / RemoveDeadNodes0` 集合直接数

## 5. 本案例应采用的正确表述

正确表述应为：

- `gsim` 在 `frontend.inner_bpu$tage` 上，`RemoveDeadNodes0` 前有 `1725` 个 `NODE_REG_SRC`
- `RemoveDeadNodes0` 后还存活 `1197` 个，删除了 `528` 个
- `grhsim keepDeclaredSymbols=false` 同前缀下有 `35666` 个 `kRegister`
- 因而 `grhsim` 确实多保留了大量 `tage` 寄存器，但不能说 `gsim` 把这一路“完全删除”

## 6. 相关输入文件

- `build/xs/ir_compare/SimTop_0TopoSort.json`
- `build/xs/ir_compare/SimTop_0RemoveDeadNodes0_regsrc_survivors.json`
- `build/xs/grhsim_compare/keepfalse/wolvrix_xs_post_kregister_symbols.txt`
- `build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/prefix_expand_groups.tsv`
- `build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_submodule_summary.tsv`
- `build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_gsim_keys.txt`
- `build/xs/ir_compare/removeDeadNodes0_vs_grhsim_keepfalse_full/residual_grh_keys.txt`
