# NO0193 xs real100 5s comp-only regression

记录日期：2026-06-13

数据源：`testcase/xs-components/build/no0193_runtime_profile_real100_4m_20260613/model_combined_5s/case_features.tsv`

回归输出：`testcase/xs-components/build/no0193_runtime_profile_real100_4m_20260613/model_comp_only`

## 1. 模型

由于 NO0192 中 `comp/src/sink/succ/exam` 高度共线，本次只保留 runtime weighted `n_comp`：

```text
T = beta_comp * sum(f_i * n_comp_i)
```

同时额外跑一个带截距的诊断模型：

```text
T = alpha + beta_comp * sum(f_i * n_comp_i)
```

主结论优先看无截距模型，因为它和原 cost model 一样约束 0 个 comp-op 时仿真时间应接近 0。带截距模型只用于判断是否存在固定开销、非线性或未建模结构差异。

注意：这里的 `sum(f_i * n_comp_i)` 是按各 simulator 自己的 runtime profile 聚合出来的量。GSIM 与 GrhSIM 的 `comp` 数值不能直接视为完全相同语义的硬件操作数，斜率对比更适合解释为“各自 profile 下每个 counted comp-op 的经验成本”。

## 2. 结果

| sim | model | slope | intercept | R2 | LOOCV R2 | MAPE |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| GSIM | no-intercept | 586.396 ps/op | 0 ms | 0.931628 | 0.930183 | 7.497% |
| GSIM | intercept | 678.981 ps/op | -1631.891 ms | 0.950489 | 0.948700 | 5.959% |
| GrhSIM | no-intercept | 467.978 ps/op | 0 ms | 0.924270 | 0.922692 | 5.379% |
| GrhSIM | intercept | 468.705 ps/op | -20.991 ms | 0.924272 | 0.921207 | 5.370% |

`n_comp` 与 runtime 的 Pearson 相关：

| sim | corr(runtime, comp) |
| --- | ---: |
| GSIM | 0.974930 |
| GrhSIM | 0.961391 |

## 3. GSIM vs GrhSIM

无截距主模型下：

- GSIM slope = 586.396 ps/op。
- GrhSIM slope = 467.978 ps/op。
- 按各自 counted comp-op 计，GSIM 的单位时间约为 GrhSIM 的 1.253 倍；等价地，GrhSIM 每 counted comp-op 约低 20.2%。

但 GrhSIM 的 runtime weighted `comp` 本身明显更大：

| metric | value |
| --- | ---: |
| mean GSIM comp | 165.156 * 1e8 |
| mean GrhSIM comp | 275.093 * 1e8 |
| mean GrhSIM/GSIM comp ratio | 1.680995 |
| median GrhSIM/GSIM comp ratio | 1.697237 |
| mean GrhSIM/GSIM runtime ratio | 1.384199 |
| median GrhSIM/GSIM runtime ratio | 1.361951 |

因此，当前 real100 数据中 GrhSIM 整体更慢，主要不是因为“每个 counted comp-op 更贵”，而是因为 GrhSIM profile 下累计 counted comp-op 更多。这个结论仍需受 profile 语义差异约束。

## 4. 解读

- `n_comp` 单变量已经是有效规模代理：GSIM LOOCV R2 为 0.930，GrhSIM LOOCV R2 为 0.923。
- 去掉共线变量后，系数符号稳定且物理解释更干净，不再出现 NO0192 多变量 OLS 中的负系数问题。
- GSIM 带截距模型拟合显著变好，但截距为 -1.63s，不适合做物理成本解释；它更像是在吸收曲率或其他与规模相关的未建模项。
- GrhSIM 截距接近 0，带不带截距结果几乎一致，说明当前 `n_comp` 对 GrhSIM runtime 的线性解释更直接。

## 5. 结论

如果目标是对比趋势和规模效应，当前应采用无截距 `n_comp` 单变量模型：

```text
GSIM:   T_ms ~= 58.640 * comp_1e8
GrhSIM: T_ms ~= 46.798 * comp_1e8
```

其中 `comp_1e8 = sum(f_i * n_comp_i) / 1e8`。这个模型适合作为跨 case 的 runtime 预测和归一化对比基线；若要解释具体优化收益，应同时报告 `comp` 总量变化和 slope，而不是只看 runtime。
