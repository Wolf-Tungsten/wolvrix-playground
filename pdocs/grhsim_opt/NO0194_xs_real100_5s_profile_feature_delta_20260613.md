# NO0194 xs real100 5s profile feature delta

记录日期：2026-06-13

数据源：

- runtime-weighted 汇总：`testcase/xs-components/build/no0193_runtime_profile_real100_4m_20260613/model_combined_5s/case_features.tsv`
- raw static profile：`testcase/xs-components/build/no0193_runtime_profile_real100_4m_20260613/raw/*/{gsim,grhsim}_supernode_static.tsv`

本文不做 runtime 回归，只比较 GSIM 与 GrhSIM 在 `n_*` profile 变量上的差异。

## 1. 口径

对比使用 100 个 `XsReal*Large` case，逐 case 成对比较 GrhSIM / GSIM。

两类指标分开看：

- static total：直接汇总每个 simulator 的 `*_supernode_static.tsv`，不乘 fire count。
- runtime-weighted total：使用 `case_features.tsv` 中的 `sum(f_i * n_*_i)`，表示实际仿真过程中被 fire 权重放大的工作量。

`exam` / `distinct_supernodes` 是 supernode 数口径，不是 `n_*` op 总量。

## 2. Runtime-weighted 总量

`case_features.tsv` 中的 `comp/src/sink/const/succ` 已经是 `sum(f_i * n_*_i)`。

| var | GSIM mean | GrhSIM mean | mean ratio | median ratio | min ratio | max ratio | GrhSIM > GSIM |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `comp` | 1.65156e10 | 2.75093e10 | 1.680995 | 1.697237 | 1.505038 | 1.844811 | 100/100 |
| `src` | 3.20938e9 | 3.65764e9 | 1.140890 | 1.134914 | 1.056723 | 1.220166 | 100/100 |
| `sink` | 5.18281e8 | 1.57335e9 | 3.035892 | 3.033605 | 3.011227 | 3.061299 | 100/100 |
| `const` | 1.42559e9 | 1.67183e9 | 1.176610 | 1.185074 | 1.126109 | 1.224673 | 100/100 |
| `succ` | 2.45225e9 | 8.50992e9 | 3.499181 | 3.424564 | 3.122538 | 4.069262 | 100/100 |
| `exam` | 378.3 | 43.79 | 0.117279 | 0.115405 | 0.100410 | 0.147766 | 0/100 |
| `distinct_supernodes` | 378.3 | 43.79 | 0.117279 | 0.115405 | 0.100410 | 0.147766 | 0/100 |

直接观察：

- GrhSIM 的 runtime-weighted `comp` 是 GSIM 的约 1.68x。
- GrhSIM 的 runtime-weighted `sink` 是 GSIM 的约 3.04x。
- GrhSIM 的 runtime-weighted `succ` 是 GSIM 的约 3.50x。
- GrhSIM 的 supernode 数只有 GSIM 的约 11.7%。

## 3. 按 `comp` 归一化的 runtime-weighted 结构

| sim | `src/comp` | `sink/comp` | `const/comp` | `succ/comp` |
| --- | ---: | ---: | ---: | ---: |
| GSIM | 0.194086 | 0.031278 | 0.086121 | 0.148293 |
| GrhSIM | 0.131905 | 0.056563 | 0.060367 | 0.307864 |

相对 GSIM，GrhSIM 的 runtime-weighted 结构更偏向 `sink` 和 `succ`：

- `src/comp` 更低，约为 GSIM 的 0.68x。
- `sink/comp` 更高，约为 GSIM 的 1.81x。
- `const/comp` 更低，约为 GSIM 的 0.70x。
- `succ/comp` 更高，约为 GSIM 的 2.08x。

这说明 GrhSIM 的额外 runtime-weighted 工作量不只是 `comp` 整体放大，而是更集中在 sink/store-like 工作和 successor activity 检查上。

## 4. Static 总量

不乘 fire count，只看静态 supernode profile：

| metric | GSIM mean | GrhSIM mean | mean ratio | median ratio | min ratio | max ratio | GrhSIM > GSIM |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| supernodes | 378.3 | 43.79 | 0.117279 | 0.115405 | 0.100410 | 0.147766 | 0/100 |
| `n_comp` total | 4152.71 | 3748.96 | 0.910444 | 0.909472 | 0.825131 | 1.007392 | 1/100 |
| `n_src` total | 807.0 | 460.07 | 0.570989 | 0.571349 | 0.527621 | 0.612579 | 0/100 |
| `n_sink` total | 131.08 | 131.08 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 0/100 |
| `n_const` total | 357.96 | 239.02 | 0.669794 | 0.670370 | 0.642857 | 0.725389 | 0/100 |
| `a_succ` total | 614.56 | 1118.85 | 1.840904 | 1.801718 | 1.659375 | 2.179420 | 100/100 |

这里的重点是：静态 `n_comp` 总量并不是 GrhSIM 更大。GrhSIM 静态 `n_comp` 只有 GSIM 的约 91%，`n_src` 只有约 57%，`n_const` 只有约 67%；但 `a_succ` 静态总量已经是 GSIM 的约 1.84x。

`n_sink` 静态总量完全相同，说明 sink 数量本身没有增加；runtime-weighted `sink` 变成 3.04x，来自这些 sink 被放入了更高 fire 权重的 coarse supernode。

## 5. Per-supernode 静态均值

因为 GrhSIM 的 supernode 数显著更少，需要看每个 supernode 的平均重量：

| metric | GSIM per-node | GrhSIM per-node | mean ratio | median ratio | min ratio | max ratio | GrhSIM > GSIM |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `n_comp` | 10.990450 | 85.438365 | 7.800841 | 7.836536 | 6.417001 | 9.087541 | 100/100 |
| `n_src` | 2.135087 | 10.415124 | 4.892298 | 4.950033 | 4.145590 | 5.276678 | 100/100 |
| `n_sink` | 0.346061 | 2.957545 | 8.587859 | 8.665238 | 6.767442 | 9.959184 | 100/100 |
| `n_const` | 0.944506 | 5.414961 | 5.754111 | 5.854363 | 4.385134 | 6.901946 | 100/100 |
| `a_succ` | 1.622725 | 25.454811 | 15.810685 | 15.380253 | 12.312459 | 20.247510 | 100/100 |

GrhSIM 是典型的 coarse supernode 形态：

- supernode 数约为 GSIM 的 11.7%。
- 每个 supernode 的 `n_comp` 约为 GSIM 的 7.8x。
- 每个 supernode 的 `a_succ` 约为 GSIM 的 15.8x。

也就是说，GrhSIM 静态上把更多工作压进更少的 supernode 中，尤其显著增加了每个 supernode 的 successor activity 检查规模。

## 6. 结论

单看 `n_*` profile，GrhSIM 和 GSIM 的主要差异不是简单的“GrhSIM 静态 op 更多”。

更准确的描述是：

- 静态上，GrhSIM supernode 更少、更粗；总 `n_comp` 还略少，总 `n_src` / `n_const` 也更少。
- 静态上，GrhSIM 的 `a_succ` 已经明显更大，说明图连接和 activity 检查结构更重。
- runtime-weighted 后，GrhSIM 的 `comp`、`sink`、`succ` 都显著大于 GSIM，分别约为 1.68x、3.04x、3.50x。
- `n_sink` 静态总量相同但 runtime-weighted 放大到 3.04x，说明 sink 被集中到更高频 fire 的 coarse supernode 中。
- 当前最值得优化的 profile 方向不是单纯减少静态 `n_comp`，而是降低 coarse supernode 的 high-frequency weighted `sink` 与 `succ` 压力，或避免把 sink / successor 检查绑定到过高频的 compute supernode 上。
