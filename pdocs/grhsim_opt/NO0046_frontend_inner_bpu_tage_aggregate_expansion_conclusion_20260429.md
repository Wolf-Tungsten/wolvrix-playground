# NO0046 `frontend.inner_bpu$tage` 中 GrhSIM 多出寄存器的主体原因：数组/存储展开

## 1. 结论

对 `frontend.inner_bpu$tage` 这一路，当前已经可以下一个较强结论：

- `grhsim keepDeclaredSymbols=false` 相对 `gsim RemoveDeadNodes0` 多出来的寄存器，**主体原因不是“额外保留了更多独立语义状态”**
- 主体原因是：`gsim` 中若干被汇聚表示的数组/存储相关状态，在 `grhsim` 中被按更细粒度展开

更准确地说：

- 一部分差值来自 `1:1` 命名重排，例如 `readResp / branches / meta / foldedHist / writeReq`
- 更大的主体差值来自 `1:N` 聚合展开，尤其是 `tables_*` 下的 write-buffer / usefulCtrs / memory-like array state

因此，对 `frontend.inner_bpu$tage` 这组寄存器，当前可以判断：

- `grhsim` 多出来的寄存器，绝大多数本质上是**数组展开 / 存储细粒度建模**导致的数量膨胀

## 2. 复核路径

### 2.1 原始规模

此前已经确认：

- `gsim TopoSort` 下该前缀 `NODE_REG_SRC = 1725`
- `gsim RemoveDeadNodes0` 后 surviving `NODE_REG_SRC = 1197`
- `grhsim keep=false` 同前缀 `kRegister = 35666`

参见 [`NO0045`](./NO0045_frontend_inner_bpu_tage_gsim_vs_grhsim_recheck_20260429.md)。

### 2.2 第一层 refine：`1:1` 命名重排

后续对 `tage` 两侧名字做了几轮 canonicalization，把下列类型的“同语义不同排布”回收到 overlap：

- `readResp`
- `foldedHist`
- `t1/t2_branches`
- `t1/t2_meta`
- `tables_* writeReq`

做到 `v3` 后：

- overlap 提升到 `770`
- `gsim-only` 降到 `427`
- `grhsim-only` 降到 `34896`

对应汇总文件：

- `build/xs/ir_compare/tage_extracts/diff_refined_v3/frontend_inner_bpu_tage_diff_refined_summary.tsv`

这一步已经证明：

- `tage` 里有一批“看似只在 `grhsim` 存活”的名字，实际上只是命名顺序不同

### 2.3 第二层 refine：`1:N` 聚合展开

再往下看 `v3` 的 residual，可以发现剩余大头已经不再像 `1:1` 命名重排，而更像：

- `gsim` 一侧是一个聚合键
- `grhsim` 一侧是若干展开后的细粒度成员

因此又补了一层 aggregate match，把这些从 `only` 视角里单独剥出来。

## 3. 当前最关键的 aggregate 结果

`v4 aggregate` 的汇总为：

| Metric | Count |
| --- | ---: |
| `matched_group_count` | `235` |
| `matched_gsim_rows` | `235` |
| `matched_grhsim_rows` | `34704` |
| `residual_gsim_rows` | `192` |
| `residual_grhsim_rows` | `192` |

也就是说：

- 仅 `235` 个 `gsim` 聚合键，就能解释 `34704` 个 `grhsim` 展开键

这已经足以说明：

- `tage` 差值主体是**聚合数组/存储状态的展开**

对应文件：

- `build/xs/ir_compare/tage_extracts/diff_refined_v4_aggregate/frontend_inner_bpu_tage_aggregate_summary.tsv`

## 4. 代表性证据

### 4.1 `tage_entry_write_buffer`：`1 -> 8`

例如：

- `gsim`
  - `cpu_l_soc_core_with_l2_core_frontend_inner_bpu_tage_tables_0_tage_entry_write_buffer_bank0_entries_entry_tag`
- `grhsim`
  - `cpu_l_soc_core_with_l2_core_frontend_inner_bpu_tage_tables_0_tage_entry_write_buffer_bank0_entries_0_0_entry_tag`
  - `...entries_0_1_entry_tag`
  - `...entries_0_2_entry_tag`
  - `...entries_0_3_entry_tag`
  - `...entries_1_0_entry_tag`
  - `...entries_1_1_entry_tag`
  - `...entries_1_2_entry_tag`
  - `...entries_1_3_entry_tag`

这组现在已经被归入 aggregate match：

- group summary:
  - `tables_0_tage_entry_write_buffer_bank0_entries_*_*_entry_tag`
  - `1 -> 8`

对应文件：

- `build/xs/ir_compare/tage_extracts/diff_refined_v4_aggregate/frontend_inner_bpu_tage_aggregate_matched_groups.tsv`
- `build/xs/ir_compare/tage_extracts/diff_refined_v4_aggregate/frontend_inner_bpu_tage_aggregate_matched_members.tsv`

### 4.2 `tables_i.usefulCtrs`：`1 -> 4096`

更重的例子是：

- `gsim`
  - `cpu_l_soc_core_with_l2_core_frontend_inner_bpu_tage_tables_0_usefulCtrs_value`
- `grhsim`
  - `cpu_l_soc_core_with_l2_core_frontend_inner_bpu_tage_tables_0_usefulCtrs_0_0_0_value`
  - ...
  - 共 `4096` 个展开键

当前八张表都是同样模式：

- `tables_0_usefulCtrs_*_*_*_value : 1 -> 4096`
- `tables_1_usefulCtrs_*_*_*_value : 1 -> 4096`
- ...
- `tables_7_usefulCtrs_*_*_*_value : 1 -> 4096`

这就是最直接的证据，说明 `grhsim` 在 `tage tables` 上采用了明显更细的状态建模粒度。

### 4.3 `writeReq`：先是 `1:1` 重排，不是“真 only”

例如：

- `gsim`
  - `...tables_0_writeReq_entries_tag_0`
- `grhsim`
  - `...tables_0_writeReq_entries_0_tag`

这类已经在 `v3` 中被回收到 `1:1` overlap，而不是 residual。

说明这里的问题也主要不是“新增状态”，而是建模/命名排布不同。

## 5. 对“多出来寄存器”的正确解释

因此，对 `frontend.inner_bpu$tage` 中 `grhsim` 多出来的寄存器，当前建议采用下面的表述：

- 主体并不是 `grhsim` 比 `gsim` 多保留了大量新的独立控制状态
- 主体是 `gsim` 的汇聚数组/存储状态，在 `grhsim` 中被按 entry / bank / way / index 等更细粒度展开
- 尤其是 `tables_*` 下的：
  - `usefulCtrs`
  - `tage_entry_write_buffer`
  - 一部分 `sram/array_ext/RW0_*`

也就是说，这里的数量差异主要反映的是：

- **建模粒度差异**
- 而不是单纯的 dead-node 删除策略差异

## 6. 保留项

当前还不能把话说成“100% 全部如此”，因为在 `v4 aggregate` 之后仍有：

- `residual_gsim_rows = 192`
- `residual_grhsim_rows = 192`

所以更严谨的最终说法应为：

- `frontend.inner_bpu$tage` 中 `grhsim` 多出来寄存器的**主体原因**已经可以判定为数组/存储展开
- 剩余 `192 / 192` 的 residual 还需要继续逐项核实

## 7. 相关文件

- `build/xs/ir_compare/tage_extracts/diff_refined_v3/frontend_inner_bpu_tage_diff_refined_summary.tsv`
- `build/xs/ir_compare/tage_extracts/diff_refined_v3/frontend_inner_bpu_tage_recovered_by_canonicalization_432.tsv`
- `build/xs/ir_compare/tage_extracts/diff_refined_v4_aggregate/frontend_inner_bpu_tage_aggregate_summary.tsv`
- `build/xs/ir_compare/tage_extracts/diff_refined_v4_aggregate/frontend_inner_bpu_tage_aggregate_matched_groups.tsv`
- `build/xs/ir_compare/tage_extracts/diff_refined_v4_aggregate/frontend_inner_bpu_tage_aggregate_matched_members.tsv`
- `build/xs/ir_compare/tage_extracts/diff_refined_v4_aggregate/frontend_inner_bpu_tage_gsim_residual_after_aggregate_192.tsv`
- `build/xs/ir_compare/tage_extracts/diff_refined_v4_aggregate/frontend_inner_bpu_tage_grhsim_residual_after_aggregate_192.tsv`
