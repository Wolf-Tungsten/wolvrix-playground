# NO0242 Input full-pass specialization small-load matrix

记录日期：2026-07-09

关联：[`NO0222`](./NO0222_small_load_codegen_perf_runbook_20260709.md)、[`NO0238`](./NO0238_dynamic_fire_compare_20260709.md)、[`NO0239`](./NO0239_no_propagate_fullpass_probe_20260709.md)、[`NO0240`](./NO0240_input_fullpass_specialization_plan_20260709.md)、[`NO0241`](./NO0241_input_fullpass_codegen_p0_20260709.md)

## 1. 目的

承接 `NO0241` 的 `input_fullpass_specialization` P0 codegen 原型，补齐小负载矩阵 gate：

- `BigComb`：pure-comb guard，确认 full-pass fast path 不会让 compute-only case 回退；
- `XsReal100BackendNfmappedelemidxSmall`：小型组合/packed case guard；
- `XsReal053FtqFtqLarge`、`XsReal043TageTageLarge`、`XsReal075RobVtypebufferLarge`：此前 GrhSIM 明显慢于 GSIM 的状态/aggregate case。

本轮特别按用户提醒处理机器负载：测试期间 `load average` 不低，但宿主为 `384` 核；所有关键 runtime 都采用相邻的 `off`（原始 GrhSIM 生成物）/`on`（打开 input full-pass）paired 对照，而不是只跑优化版。

## 2. 产物与口径

产物：

```text
tmp/no0242_input_fullpass_matrix_20260709/
tmp/no0242_input_fullpass_bigcomb_20260709/
testcase/xs-components/build/no0242_input_fullpass_matrix_20260709/
testcase/big-comb/build/no0242_input_fullpass_bigcomb_20260709/
```

环境口径：

```bash
source env.sh
```

xs-components：

- 基于 `NO0222` raw bench 的 FIR/SV/GSIM artifacts 重新 emit GrhSIM；
- `off` 为当前默认 `input_fullpass_specialization=0`；
- `on` 为 `--input-fullpass-specialization`；
- `--vectors 200000 --verify 4096 --repeat 3 --model grhsim`；
- phase profile 用 `--repeat 1 --grhsim-phase-profile`。

BigComb：

- 两个独立 build dir，分别用 `GRHSIM_INPUT_FULLPASS_SPECIALIZATION=0/1`；
- `BENCH_VECTORS=1000000 BENCH_VERIFY=4096`；
- bench 程序同场输出 GSIM 与 GrhSIM timing，可作为机器负载漂移的辅助参照。

## 3. 机器负载记录

xs-components 矩阵运行时的 load 片段：

| case | run 附近 load average |
| --- | --- |
| `XsReal100BackendNfmappedelemidxSmall` | `77.56, 80.55, 56.24` |
| `XsReal053FtqFtqLarge` | `84.40, 81.92, 56.81` |
| `XsReal043TageTageLarge` | `80.34, 81.14, 56.96` |
| `XsReal075RobVtypebufferLarge` | `78.28, 80.67, 57.07` |

BigComb paired run 的 load 从 `66.48, 73.35, 60.04` 降到 `14.35, 50.99, 58.22`。因此 BigComb 结果同时参考同场 GSIM：GSIM `18058.024ms -> 18283.377ms`（`+1.25%`），说明 on/off run 间频率/负载差异不足以解释 GrhSIM 的 `-25.05%` 变化。

## 4. xs-components correctness + runtime

所有 case 的 `off/on` 均 `--verify 4096` 通过，checksum 一致。

| case | vectors(logged) | off min ms | on min ms | delta | off median ms | on median ms | delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `XsReal100BackendNfmappedelemidxSmall` | `200002` | `8.142` | `7.787` | `-4.36%` | `8.148` | `7.831` | `-3.89%` |
| `XsReal053FtqFtqLarge` | `200002` | `531.896` | `481.421` | `-9.49%` | `532.390` | `482.944` | `-9.29%` |
| `XsReal043TageTageLarge` | `200002` | `456.279` | `400.564` | `-12.21%` | `456.703` | `400.639` | `-12.28%` |
| `XsReal075RobVtypebufferLarge` | `200002` | `409.407` | `377.688` | `-7.75%` | `409.709` | `378.171` | `-7.70%` |

解释：

- `NfmappedElemidxSmall` 本来就很小，收益只有 `~4%`，可视为 guard pass；
- FTQ/Tage/VtypeBuffer 三个慢 case 均有 `7.75%~12.21%` 的 raw runtime 收益；
- 这比 `NO0241` 中 VtypeBuffer 单点 `-13.81%` 小一些，原因之一是本轮使用 `NO0222` raw bench base，而 `NO0241` 使用 `NO0228` 单模型 P0 产物；绝对值不直接混用，趋势一致。

## 5. xs-components phase profile

| case | off measured ms | on measured ms | delta | off low ms | on low ms | delta | off high ms | on high ms | delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `XsReal100BackendNfmappedelemidxSmall` | `25.376` | `25.130` | `-0.97%` | `9.906` | `9.724` | `-1.84%` | `5.382` | `5.372` | `-0.19%` |
| `XsReal053FtqFtqLarge` | `542.237` | `495.364` | `-8.64%` | `257.560` | `193.662` | `-24.81%` | `274.601` | `291.615` | `+6.20%` |
| `XsReal043TageTageLarge` | `469.495` | `418.069` | `-10.95%` | `220.974` | `161.421` | `-26.95%` | `238.468` | `246.578` | `+3.40%` |
| `XsReal075RobVtypebufferLarge` | `420.835` | `389.415` | `-7.47%` | `206.908` | `156.613` | `-24.31%` | `203.807` | `222.745` | `+9.29%` |

关键结论：

1. P0 fast path 的收益高度集中在 input-low / data-input settle 阶段：三个大 case 的 low phase 均下降约 `24%~27%`。
2. high phase 基本没有收益，且 FTQ/Tage/VtypeBuffer 在 phase-profile 单次 run 中上升 `3%~9%`。这可能包含噪声和 code layout 影响，但方向上说明当前 P0 没有解决 clock-edge commit/post-commit settle 的主要成本。
3. 这与 `NO0232`/`NO0233` 的判断一致：low 并非“下降沿顺序工作”，而是输入变化后的组合 settle；high 才是 posedge commit + commit-activated compute。

## 6. BigComb guard

BigComb pure-comb paired run：

| mode | verify | GSIM ms | GrhSIM ms | GrhSIM/GSIM | checksum |
| --- | --- | ---: | ---: | ---: | --- |
| off | pass | `18058.024` | `17384.569` | `0.963x` | `0x92cd1159a6bbfc47` |
| on | pass | `18283.377` | `13029.180` | `0.713x` | `0x92cd1159a6bbfc47` |

按 GrhSIM 自身 off/on：`17384.569ms -> 13029.180ms`，delta `-25.05%`。

BigComb 没有 commit supernode，fast path 几乎等价于“输入变了就全量 compute 一遍，并跳过 compute->compute active/change propagation”。这说明：

- pure-comb guard 不但没有回退，反而明显受益；
- `NO0239` no-propagate probe 观察到的 active/change 框架成本并非 VtypeBuffer 特例，在大组合 DAG 中同样真实存在；
- 对只有 data-input settle 的场景，full-pass specialization 方向比继续调 partition 更直接。

## 7. 当前结论

本轮矩阵支持把 `input_fullpass_specialization` 继续作为候选优化推进，但还不建议默认开启：

- correctness：当前 `BigComb + 4 个 xs-components` 均通过；
- performance：除极小 case 外均有明确收益；
- root-cause：P0 主要消掉 input-driven compute path 中的 active/change propagation，解释了 low phase `~25%` 降幅；
- 未解决：clock-edge high phase 仍走原始 event/commit/fixed-point active 框架，是剩余 GrhSIM/GSIM gap 的下一 ROI。

下一步建议：

1. 对照 GSIM 的 clocked step 代码，拆 GrhSIM high phase 中 `commit -> state changed -> compute` 的额外代码形态；
2. 评估一个默认关闭的 `posedge full-pass/post-commit full-pass` 原型：只在 event guard 明确、无 data input 同时变化的 high eval 上跳过 commit-activated compute propagation；
3. 在实现前先用 VtypeBuffer/FTQ/Tage 的临时 generated C++ patch 做 correctness + high-only timing 上界，避免直接在 emitter 中扩大语义风险。
