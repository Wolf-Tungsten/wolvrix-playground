# NO0101: Commit Scalar Table 诊断字段验证

Date: 2026-05-21

## 背景

`NO0100` 新增了默认关闭的 per-entry commit scalar activation table 候选。进入 XiangShan fresh emit 前，需要先确认诊断字段能在真实 emitter 路径输出，后续才能用结构命中数据决定是否值得 build/runtime。

## 命令

```sh
WOLVRIX_GRHSIM_DIAG_COMMIT_SCALAR_TABLE=1 wolvrix/build/bin/emit-grhsim-cpp 2>&1 | rg "commit-scalar-table|per_entry|Failed|emit_grhsim_cpp"
```

## 结果

诊断字段已输出新增列：

- `table_runs`
- `table_writes`
- `per_entry_runs`
- `per_entry_writes`
- `per_entry_activation_entries`

小测试集中出现了命中新路径的样本：

```text
[grhsim-cpp] commit-scalar-table candidates=124 accepted=124 ... table_runs=1 table_writes=4 per_entry_runs=1 per_entry_writes=4 per_entry_activation_entries=4
```

## 结论

诊断输出可用于下一步 XiangShan fresh emit 的结构验收。下一步不应直接 build/runtime；应先 fresh emit with diagnostics，并检查：

- 总 `per_entry_writes` 是否足够大；
- hot `sched_990/951/977` 中 `PerEntryActivations` 是否命中；
- inline `Commit writes update visible state directly` 是否明显减少；
- 生成代码规模是否没有异常膨胀。

只有这些结构指标通过后，再进入 XiangShan build + difftest runtime。
