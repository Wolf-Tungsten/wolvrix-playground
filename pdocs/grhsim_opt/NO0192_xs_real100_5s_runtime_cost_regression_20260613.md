# NO0192 xs real100 5s runtime cost regression

记录日期：2026-06-13

数据源：`testcase/xs-components/build/no0193_runtime_profile_real100_4m_20260613/raw_combined_5s`

回归输出：`testcase/xs-components/build/no0193_runtime_profile_real100_4m_20260613/model_combined_5s`

## 1. 模型

主模型仍沿用 NO0190/NO0191 的 per-case 无截距 OLS：

```text
T = c_comp * sum(f_i * n_comp_i)
  + c_src  * sum(f_i * n_src_i)
  + c_sink * sum(f_i * n_sink_i)
  + c_succ * sum(f_i * a_succ_i)
  + c_exam * n_supernode
```

- `T` 为 `timings.tsv` 中对应 simulator 的 wall time，单位 ms。
- `f_i` 来自 runtime fire TSV；`n_*` / `a_succ` 来自 static TSV。
- op 项系数显示为 ps/op；`c_exam` 显示为 us/supernode。
- 数据为主 4M-vector raw，加 `XsReal030PrefetchBertiLarge` 的 4.2M-vector patch，保证 GSIM/GrhSIM 每个样本均 >= 5s。

## 2. 数据质量

- cases: 100
- verify: 100 pass
- GSIM timing range after patch: 5017.652 ms to 16019.762 ms
- GrhSIM timing range after patch: 6897.650 ms to 20153.629 ms
- 所有 200 个 simulator profile 的 weighted `n_src` / `n_sink` 非零，fire row 无缺失。
- `comp/src/sink/succ/exam/const` 在 GSIM 和 GrhSIM 中均为 100/100 非零。

## 3. GSIM 主模型

| metric | value |
| --- | ---: |
| R2 / adjusted R2 | 0.951530 / 0.949489 |
| RMSE / MAE | 656.563 ms / 531.021 ms |
| MAPE | 6.033% |
| LOOCV R2 / RMSE | 0.946726 / 688.326 ms |
| condition number | 5739.9 |

| term | coef | t | 95% CI scaled |
| --- | ---: | ---: | ---: |
| `comp` | 406.194 ps/op | 3.048 | [14.1685, 67.0703] |
| `src` | -5333.581 ps/op | -3.375 | [-847.048, -219.668] |
| `sink` | 28976.383 ps/op | 3.252 | [1129.13, 4666.15] |
| `succ` | 2973.448 ps/op | 5.259 | [185.111, 409.579] |
| `exam` | -5954.467 us/supernode | -1.407 | [-14.3566, 2.44767] |

Top residuals:

| case | actual ms | pred ms | resid ms |
| --- | ---: | ---: | ---: |
| `XsReal028PrefetchL1PrefetchcomponentLarge` | 11941.036 | 10285.894 | 1655.142 |
| `XsReal067DatapathWbarbiterLarge` | 8868.178 | 10428.878 | -1560.700 |
| `XsReal029PipelineStoreunitLarge` | 13129.071 | 11573.982 | 1555.089 |
| `XsReal037Tl2TlMainpipeLarge` | 9084.534 | 10428.407 | -1343.873 |
| `XsReal062MmuBitmapcheckLarge` | 9091.571 | 10427.077 | -1335.506 |
| `XsReal007FuCsrLarge` | 9133.871 | 10428.854 | -1294.983 |
| `XsReal019BackendCtrlblockLarge` | 15334.129 | 14111.921 | 1222.208 |
| `XsReal063LsqueueLoadqueuerawLarge` | 13002.672 | 11805.281 | 1197.391 |

## 4. GRHSIM 主模型

| metric | value |
| --- | ---: |
| R2 / adjusted R2 | 0.935787 / 0.933083 |
| RMSE / MAE | 762.384 ms / 636.923 ms |
| MAPE | 5.002% |
| LOOCV R2 / RMSE | 0.929086 / 801.172 ms |
| condition number | 1221.0 |

| term | coef | t | 95% CI scaled |
| --- | ---: | ---: | ---: |
| `comp` | -292.977 ps/op | -1.455 | [-69.2578, 10.6625] |
| `src` | 3561.023 ps/op | 3.316 | [142.921, 569.284] |
| `sink` | -7703.990 ps/op | -2.596 | [-1359.47, -181.33] |
| `succ` | 1734.427 ps/op | 3.450 | [73.6423, 273.243] |
| `exam` | 119889.943 us/supernode | 1.840 | [-9.42067, 249.201] |

Top residuals:

| case | actual ms | pred ms | resid ms |
| --- | ---: | ---: | ---: |
| `XsReal089LsqueueStorequeuedataLarge` | 20153.629 | 17902.808 | 2250.821 |
| `XsReal082Tl2ChiMmiobridgeLarge` | 17497.643 | 15550.432 | 1947.211 |
| `XsReal032IssueEntriesLarge` | 13200.325 | 11521.997 | 1678.328 |
| `XsReal041ScScLarge` | 11429.906 | 9917.799 | 1512.107 |
| `XsReal085MainpipeWritebackqueueLarge` | 10357.694 | 8849.321 | 1508.373 |
| `XsReal097FuSrt16DividerLarge` | 12861.907 | 11507.406 | 1354.501 |
| `XsReal071IcacheIcachemainpipeLarge` | 11369.706 | 10161.784 | 1207.922 |
| `XsReal059VectorVmergebufferLarge` | 15552.371 | 16711.595 | -1159.224 |

## 5. 对照与诊断

### 4.1 `n_const` 对照

| sim | model | R2 | LOOCV R2 | RMSE ms | MAPE |
| --- | --- | ---: | ---: | ---: | ---: |
| gsim | main | 0.951530 | 0.946726 | 656.563 | 6.033% |
| gsim | with_const | 0.955081 | 0.949688 | 632.051 | 5.842% |
| grhsim | main | 0.935787 | 0.929086 | 762.384 | 5.002% |
| grhsim | with_const | 0.947730 | 0.940842 | 687.840 | 4.604% |

### 4.2 非负子模型

| sim | active terms | R2 | RMSE ms | MAPE |
| --- | --- | ---: | ---: | ---: |
| gsim | comp, sink, succ | 0.945683 | 695.031 | 6.412% |
| grhsim | src, succ, exam | 0.931224 | 789.005 | 4.998% |

### 4.3 共线性

- GSIM VIF: `comp`=74.6, `exam`=44.9, `sink`=570.1, `src`=655.5, `succ`=33.2
- GrhSIM VIF: `comp`=309.8, `exam`=64.9, `sink`=459.1, `src`=193.2, `succ`=181.2
- 最大相关性：GSIM `src/sink` corr=0.9989；GrhSIM `comp/sink` corr=0.9948。

## 6. 结论

- 新 5s 数据显著提升了统计稳定性：GSIM LOOCV R2 从旧数据的负值提升到 0.947，GrhSIM LOOCV R2 为 0.929。
- 模型已经可以作为趋势预测模型使用，MAPE 约 5-6%。
- 但 OLS 系数仍不能全部解释为独立物理成本：GSIM `c_src` 为负，GrhSIM `c_comp/c_sink` 为负。原因不再是特征覆盖为零，而是特征高度共线。
- 若目标是物理可解释的单位成本，应优先使用非负/约束模型或减少参数；当前无约束 OLS 更适合作预测/排序，不适合直接指导每项微成本归因。
