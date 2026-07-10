# NO0244 Posedge full-pass probe FTQ/Tage matrix

记录日期：2026-07-09

关联：[`NO0242`](./NO0242_input_fullpass_small_matrix_20260709.md)、[`NO0243`](./NO0243_posedge_fullpass_probe_20260709.md)

## 1. 目的

`NO0243` 只在 `XsReal075RobVtypebufferLarge` 上手工验证了 posedge-only full-pass probe。为了避免基于单 case 推动 emitter，本轮把同一 generated C++ patch 机械泛化到：

- `XsReal053FtqFtqLarge`
- `XsReal043TageTageLarge`

并汇总 `VtypeBuffer + FTQ + Tage` 三个状态/aggregate 大 case 的 paired 结果。

## 2. probe 口径

产物：

```text
tmp/no0243_posedge_fullpass_probe_20260709/
```

patch 仍只作用于 generated C++，不改仓库源码：

- 从 `NO0242` 的 `on` model 复制；
- 删除复制目录中的 stale `.pch/.o/.a` 后重建，避免 PCH 记录旧绝对路径；
- 在 `eval()` 中新增 `posedge_fullpass_candidate`：`!initial_eval`、event 是 `posedge`、全部 data/reset input 都等于 previous input；
- fast path：`commit batch` 调一次，如果 state changed，再依次调用所有 `eval_compute_batch_*_fullpass()`，然后清 event/active、refresh outputs、更新 previous-input baseline。

解析到的 batch 形态：

| case | fullpass compute batches | commit batch |
| --- | ---: | --- |
| `XsReal053FtqFtqLarge` | `0..5` | `6` |
| `XsReal043TageTageLarge` | `0..4` | `5` |
| `XsReal075RobVtypebufferLarge` | `0..3` | `4` |

## 3. correctness

| case | 20k smoke | `--verify 200000` | checksum |
| --- | --- | --- | --- |
| `XsReal053FtqFtqLarge` | pass | pass | `0xbaee70347535d277` |
| `XsReal043TageTageLarge` | pass | pass | `0x3c264532fbc1f4d3` |
| `XsReal075RobVtypebufferLarge` | pass | pass | `0xa6ff99241ea2cc48` |

说明：`checksum` 为 paired 200k raw run 的最终 checksum，baseline-on 与 probe 一致。

## 4. machine load 与 paired 方法

FTQ/Tage paired run 的 load 很低：

| case | run 附近 load average |
| --- | --- |
| `XsReal053FtqFtqLarge` | `4.78, 10.11, 27.24` 到 `4.72, 10.01, 27.11` |
| `XsReal043TageTageLarge` | `4.72, 10.01, 27.11` 到 `4.50, 9.87, 26.98` |

VtypeBuffer 的 paired load 已记录在 `NO0243`：约 `24.94, 18.44, 35.70` 到 `23.35, 18.22, 35.54`。

所有 runtime 都相邻 rerun baseline-on 与 probe，避免只看优化版。

## 5. raw runtime

`--vectors 200000 --verify 4096 --repeat 3 --model grhsim`，按 min 计：

| case | baseline-on min ms | posedge probe min ms | delta | baseline median ms | probe median ms | delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `XsReal053FtqFtqLarge` | `475.645` | `435.132` | `-8.52%` | `476.758` | `435.311` | `-8.69%` |
| `XsReal043TageTageLarge` | `394.128` | `357.462` | `-9.30%` | `394.219` | `357.572` | `-9.30%` |
| `XsReal075RobVtypebufferLarge` | `370.309` | `309.097` | `-16.53%` | `370.318` | `309.760` | `-16.35%` |

## 6. phase profile

`--vectors 200000 --verify 4096 --repeat 1 --model grhsim --grhsim-phase-profile`：

| case | baseline measured ms | probe measured ms | delta | baseline low ms | probe low ms | delta | baseline high ms | probe high ms | delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `XsReal053FtqFtqLarge` | `485.818` | `450.645` | `-7.24%` | `189.945` | `183.844` | `-3.21%` | `286.006` | `256.935` | `-10.16%` |
| `XsReal043TageTageLarge` | `405.878` | `370.462` | `-8.73%` | `156.838` | `148.731` | `-5.17%` | `239.186` | `211.898` | `-11.41%` |
| `XsReal075RobVtypebufferLarge` | `381.867` | `328.252` | `-14.04%` | `153.307` | `135.975` | `-11.31%` | `218.707` | `182.360` | `-16.62%` |

结论：

- 三个大 case 的 high phase 全部明显下降，幅度 `-10.16%` 到 `-16.62%`；
- low phase 也有 `-3%` 到 `-11%` 的下降，说明 generated patch 仍会受到 code layout / branch predictor / measurement 影响，不能把 total raw gain 全部算给 high path；
- 但 high phase 同向下降且 `verify=200000` 全通过，足以说明 posedge-only fast path 不是 VtypeBuffer 单点偶然。

## 7. 对 root-cause 的更新

当前对 GrhSIM 慢点的分解更清楚了：

1. input/data settle：`input_fullpass_specialization` 已经证明 active/change propagation 是主要可回收成本之一；
2. posedge high settle：commit 后用 active propagation 触发第二轮 compute，也存在可回收成本；
3. 剩余差距：即使 fullpass 后，GrhSIM 仍慢于 GSIM，继续指向 `value_*_slots_`/`state_logic_storage_` 间接、宽字临时、supernode 内 register pressure 与代码布局。

这解释了为什么单纯调 partition/topo 很难有决定性收益：在这些小 case 中，compute fire 数不是主矛盾，always-active 场景下仍保留的事件/active/change 框架才是第一层额外开销。

## 8. 下一步建议

现在可以进入 emitter 实现阶段，但必须默认关闭：

- 新增 `posedge_fullpass_specialization` 或扩展现有 `input_fullpass_specialization` 为更明确的 full-pass specialization 选项；
- 只在 posedge-only、无 data/reset 变化、非 initial eval 时触发；
- commit batch 调用后，若 `commit_activated_readers_` 为 true，则运行 fullpass compute batches；
- 多 clock / negedge / reset / data+clock 同 eval 先保守 fallback；
- gate：BigComb、Nfmapped、FTQ、Tage、VtypeBuffer `verify>=200000` + paired 200k raw/phase；再考虑更长窗口和完整 XiangShan 小 gate。
