# NO0191 xs-components GrhSIM / GSIM runtime cost regression

记录日期：2026-06-13

数据源：`testcase/xs-components/build/no0190_runtime_profile_20260613/raw`

回归脚本：`testcase/xs-components/scripts/regress_runtime_cost_model.py`

输出目录：`testcase/xs-components/build/no0190_runtime_profile_20260613/model`

## 1. 回归模型

按需求中的主公式分别对 gsim / grhsim 做无截距 OLS：

```text
T = c_comp * sum(f_i * n_comp_i)
  + c_src  * sum(f_i * n_src_i)
  + c_sink * sum(f_i * n_sink_i)
  + c_succ * sum(f_i * a_succ_i)
  + c_exam * n_supernode
```

- 每个 case 是一个样本，共 100 个样本。
- `T` 使用 `timings.tsv` 中对应 sim 的 `*_ms`，单位 ms。
- op 类特征使用 static/fire TSV join 后的整轮累计值。
- `n_supernode` 使用 static TSV 行数；本批数据里它等于 distinct `supernode_id` 数。
- op 项系数报告为 `ps/op`；`c_exam` 报告为 `us/supernode`（整轮 100002 vectors 的每 supernode 静态项）。
- 置信区间与 t 值使用 OLS 同方差近似；本批 bench `repeat=1`，未包含运行噪声重复采样。

`n_const` 不在主公式中。脚本同时输出 `with_const` 对照模型，用于判断主模型是否漏掉常量项；本次 `n_const` 对拟合几乎无增益。

## 2. 主结果

### 2.1 GSIM

| 系数 | 估计值 | 95% CI | t | 备注 |
| --- | ---: | ---: | ---: | --- |
| `c_comp` | **68.17 ps/op** | [61.93, 74.41] ps/op | 21.69 | 稳定、显著 |
| `c_src` | **-613.44 ps/op** | [-786.35, -440.53] ps/op | -7.04 | 负值，不具物理成本含义 |
| `c_sink` | **1921.82 ps/op** | [12.99, 3830.65] ps/op | 2.00 | 边界显著，区间很宽 |
| `c_succ` | **1175.75 ps/op** | [-418.19, 2769.69] ps/op | 1.46 | 不显著 |
| `c_exam` | **307.42 us/supernode** | [-144.79, 759.63] us/supernode | 1.35 | 不显著 |

拟合指标：

| 指标 | 值 |
| --- | ---: |
| R2 / adjusted R2 | 0.808976 / 0.800933 |
| RMSE / MAE | 2.995 ms / 1.535 ms |
| MAPE | 18.62% |
| LOOCV R2 / RMSE | -0.415489 / 8.153 ms |
| condition number | 2307.0 |

结论：GSIM 主模型的训练 R2 尚可，但泛化置信度低。`c_comp` 可较可信地解释主要线性趋势；`c_src/c_sink/c_succ/c_exam` 由于覆盖不足和强共线性，不能解释为独立物理成本。尤其 `c_src` 为显著负值，说明当前五项线性模型在 GSIM 数据上发生了补偿性拟合。

### 2.2 GrhSIM

| 系数 | 估计值 | 95% CI | t | 备注 |
| --- | ---: | ---: | ---: | --- |
| `c_comp` | **56.43 ps/op** | [15.90, 96.97] ps/op | 2.76 | 正值、显著但区间偏宽 |
| `c_src` | **1583.16 ps/op** | [1103.81, 2062.52] ps/op | 6.56 | 稳定、显著 |
| `c_sink` | **-1153.70 ps/op** | [-1813.73, -493.68] ps/op | -3.47 | 负值，不具物理成本含义 |
| `c_succ` | **1165.84 ps/op** | [833.49, 1498.18] ps/op | 6.96 | 稳定、显著 |
| `c_exam` | **-196.93 us/supernode** | [-664.52, 270.67] us/supernode | -0.84 | 不显著 |

拟合指标：

| 指标 | 值 |
| --- | ---: |
| R2 / adjusted R2 | 0.928249 / 0.925228 |
| RMSE / MAE | 9.867 ms / 6.281 ms |
| MAPE | 60.31% |
| LOOCV R2 / RMSE | 0.780194 / 17.269 ms |
| condition number | 423.0 |

结论：GrhSIM 主模型的训练与 LOOCV R2 都明显好于 GSIM，说明这组结构特征对 GrhSIM 总体趋势有解释力。可信度较高的项是 `c_src` 与 `c_succ`；`c_comp` 中等可信；`c_sink` 和 `c_exam` 不能作为物理成本解释，因为 `c_sink` 被拟合成负值、`c_exam` 不显著。

## 3. 置信度诊断

### 3.1 特征覆盖不足

| sim | term | 非零样本数 / 100 |
| --- | --- | ---: |
| gsim | comp | 100 |
| gsim | src | 7 |
| gsim | sink | 7 |
| gsim | succ | 7 |
| gsim | exam | 100 |
| grhsim | comp | 100 |
| grhsim | src | 7 |
| grhsim | sink | 7 |
| grhsim | succ | 100 |
| grhsim | exam | 100 |

只有 7 个 case 含 `src/sink`，这不足以可靠地区分 `c_src` 与 `c_sink`。GSIM 的 `a_succ` 也只有这 7 个 case 非零，所以 `c_succ` 同样不可稳定识别。

### 3.2 共线性

GSIM 的关键相关系数：

| pair | corr |
| --- | ---: |
| src-sink | 0.936 |
| src-succ | 0.928 |
| sink-succ | 0.942 |
| succ-exam | 0.891 |

GSIM VIF：`src=10.1`、`sink=45.0`、`succ=97.8`、`exam=22.1`。这解释了负 `c_src` 和宽置信区间。

GrhSIM 的关键相关系数：

| pair | corr |
| --- | ---: |
| src-succ | 0.831 |
| sink-succ | 0.850 |
| comp-succ | 0.792 |
| comp-exam | 0.784 |

GrhSIM VIF：`succ=11.9`，其余约 3.6-4.1。共线性仍明显，但弱于 GSIM。

### 3.3 非负约束对照

若要求所有成本系数非负，并枚举选择最优非负子模型：

| sim | active terms | R2 | RMSE | 结果 |
| --- | --- | ---: | ---: | --- |
| gsim | comp, succ, exam | 0.709040 | 3.696 ms | `src/sink` 被压到 0，训练 R2 明显下降 |
| grhsim | comp, src, succ | 0.918847 | 10.493 ms | `sink/exam` 被压到 0，R2 仅小幅下降 |

这说明主模型中的负系数不是数值误差，而是当前数据与公式下的补偿性拟合。GrhSIM 中 `sink` 的独立贡献尤其未被当前样本分布可靠识别。

### 3.4 `n_const` 对照

加入 `n_const` 后：

| sim | R2 main | R2 with_const | LOOCV R2 main | LOOCV R2 with_const |
| --- | ---: | ---: | ---: | ---: |
| gsim | 0.808976 | 0.811412 | -0.415489 | -0.441582 |
| grhsim | 0.928249 | 0.928319 | 0.780194 | 0.717169 |

`n_const` 对训练 R2 只有极小提升，并使 LOOCV 变差；当前数据不支持为常量项稳定拟合独立成本。

### 3.5 verify mismatch 敏感性

剔除 7 个 `failed_then_collected_with_verify0` case 后，结论基本不变：

| sim | n | R2 | LOOCV R2 | RMSE |
| --- | ---: | ---: | ---: | ---: |
| gsim pass-only | 93 | 0.813744 | -0.343814 | 3.065 ms |
| grhsim pass-only | 93 | 0.930726 | 0.786569 | 10.032 ms |

因此本次置信度问题主要来自特征覆盖和共线性，而不是 verify mismatch case。

## 4. 残差热点

GSIM 主模型最大残差：

| case | actual | pred | resid |
| --- | ---: | ---: | ---: |
| XsLoadQueueRawLarge | 32.692 | 16.409 | 16.283 |
| XsRobBankScanLarge | 36.216 | 49.403 | -13.187 |
| XsWbArbiterLarge | 24.866 | 15.155 | 9.711 |
| XsPlruBankedXLarge | 24.332 | 14.630 | 9.702 |
| XsIcacheReplacerLarge | 11.601 | 18.822 | -7.221 |

GrhSIM 主模型最大残差：

| case | actual | pred | resid |
| --- | ---: | ---: | ---: |
| XsPrefetchStrideLarge | 20.859 | 64.930 | -44.071 |
| XsIcacheReplRegsCatLarge | 187.305 | 145.930 | 41.375 |
| XsIcacheReplRegsDiscreteLarge | 177.034 | 145.930 | 31.104 |
| XsPlruLarge | 66.470 | 41.760 | 24.710 |
| XsLoadQueueRawLarge | 12.222 | 35.115 | -22.893 |

## 5. 总体判断

当前主模型可以作为第一版趋势模型，但不能把所有 `c_*` 都当成已可靠识别的微观单位成本。

- GSIM：低置信。`c_comp` 可信；其余项由于 7/100 覆盖和强共线性，不可信。LOOCV R2 为负，说明泛化能力很弱。
- GrhSIM：中等置信。`c_src`、`c_succ` 可信度较高，`c_comp` 中等；`c_sink`、`c_exam` 不可信。
- 两侧都显示 `c_exam` 不显著，支持 NO0190 中 `N*A_exam` 不是主因的判断。
- 当前数据不足以独立估计 `c_src` 与 `c_sink`，需要增加更多带状态读写、且 `src/sink/succ/exam` 解耦的 case，或把模型改成更少参数的分层/约束模型。

## 6. 复现命令

```bash
python3 testcase/xs-components/scripts/regress_runtime_cost_model.py \
  --raw-dir testcase/xs-components/build/no0190_runtime_profile_20260613/raw \
  --out-dir testcase/xs-components/build/no0190_runtime_profile_20260613/model

python3 testcase/xs-components/scripts/regress_runtime_cost_model.py \
  --raw-dir testcase/xs-components/build/no0190_runtime_profile_20260613/raw \
  --out-dir testcase/xs-components/build/no0190_runtime_profile_20260613/model_pass_only \
  --pass-only
```

主要产物：

- `case_features.tsv`：每个 case 的聚合特征。
- `coefficients.tsv`：主模型与 `with_const` 对照模型的系数、标准误、t 值、95% CI。
- `residuals.tsv`：逐 case 残差。
- `summary.json`：机器可读完整诊断，包括 LOOCV、VIF、相关矩阵、非负子模型。
- `summary.md`：自动生成的简版摘要。
