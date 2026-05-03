# NO0064 Linearize XS GrhSIM Checkpoint Flow

## 1. 背景

早期 `scripts/wolvrix_xs_grhsim.py` 会在 `merge-reg` 前额外写出一份 `after_flatten_simplify.json`，用于单独 replay 和调试 `merge-reg`。随着当前寄存器合并路径收敛到 `merge-reg` 默认线性流程，这个中间恢复点已经不再是主流程需要的 checkpoint。

## 2. 调整

删除 `merge-reg` 专用恢复点：

- 移除 `WOLVRIX_XS_GRHSIM_PRE_MERGE_REG_JSON` 环境变量入口。
- 移除 `write_pre_merge_reg_json` 写出逻辑。
- 移除为了识别 “`simplify` 后面是否是 `merge-reg`” 而保留的 `pass_index` / `next_pass_name` 分支。

当前 `scripts/wolvrix_xs_grhsim.py` 只保留 `activity-schedule` 前的 checkpoint：

```text
WOLVRIX_XS_GRHSIM_POST_STATS_JSON
WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON
```

流程变为线性：

```text
read_sv
  -> xmr-resolve
  -> memory-read-retime
  -> multidriven-guard
  -> blackbox-guard
  -> latch-transparent-read
  -> hier-flatten
  -> comb-lane-pack
  -> comb-loop-elim
  -> simplify
  -> merge-reg
  -> simplify
  -> memory-init-check
  -> stats
  -> write post-stats json
  -> activity-schedule
  -> emit grhsim cpp
```

## 3. 验证

语法检查：

```bash
python3 -m py_compile scripts/wolvrix_xs_grhsim.py
```

残留检查：

```bash
rg 'PRE_MERGE_REG|pre_merge_reg|write_pre_merge_reg|next_pass_name|pass_index' scripts/wolvrix_xs_grhsim.py
```

结果：无匹配。
