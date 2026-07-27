# TNO0185 SimpleTES v2 F repeat and RWA endpoint decision

## 1. 阶段结论

本阶段按 [TNO0183](./TNO0183_simpletes_v2_direct_ablation_final_attribution_and_retention_decision_20260727.md)
的未闭项补测 `F`，并对
[TNO0184](./TNO0184_simpletes_v2_rwa_materialization_and_fresh_gate_20260727.md) 构造的无 F `RWA`
执行 fresh baseline endpoint。最终 50k `Host time spent` walltime 为：

- `RW -> RWF` 复测：`55381.75 -> 55248.75 ms`，绝对减少 `133.00 ms`，表面改善
  `0.240151%`；两种 order 本次虽同向，但仍远低于 `1%` 信任线；
- `B -> RWA`：`60583.50 -> 53992.75 ms`，绝对减少 `6590.75 ms`，改善
  `10.878787%`；ABBA 与 BAAB 均稳定正向，所有正式门禁通过。

前次 F 正式实验只有 `0.159522%` 且双 order 反向；本次复测仍只有 `0.240151%`。因此结论不是数学意义
上的“恰好零”，而是 **F 没有可依赖、足以保留或默认开启的端到端收益**，继续停止。另一方面，先前
`RWF -> RWFA` 已证明 A 的 direct 信号，静态审计又证明 A 与 F 独立；现在无 F `B -> RWA`
endpoint 达到 `10.878787%`，因此最终 landing/default 候选集合收敛为 `R/W/A`，明确排除 `F`。

本阶段没有把 checkpoint patch 写入实际 Wolvrix 默认；落地后仍须在真实默认源码上重做功能/full regression
和 final 50k 回归。

## 2. 正式协议与固定身份

两个实验都使用 SimTop `50000` cycles，headline 只取每份 emu log 中唯一的 `Host time spent`：

1. 先跑独立 `ABBA`，有效且正向才 promotion 到 fresh `BAAB`；
2. 每个 order 为 control/candidate 各 `2` 个样本，pooled 为 `4+4`；
3. 动态选完整空闲 CCD，whole-CCD、target、SMT sibling、连续 monitor 均为硬门禁；
4. `taskset`、NUMA first-touch、binary/NEMU residency、PMU scheduling、context switch、功能签名和唯一
   walltime 均须通过；
5. accepted process personality 必须为 `00040000`，即 `ADDR_NO_RANDOMIZE` 已生效；
6. retryable group 整体丢弃，不能把半组或 gate 失败的 raw 样本拼入 headline。

`RW/RWF` 复用 TNO0183 固定的 candidate/proof/emu；`RWA` 使用 TNO0184 的 fresh digest
`600ee91247376203f2162cfcad099e05c629382bb94b4600264cecaf6c5658a3`。两类测试的 parent
`fbe4e1cbbfcf45b52960545377020cb761c3ab25`、Wolvrix
`8f6ba14397b0c3d00cb909153af1c6464f4f1ed9`、build-config/toolchain/env 身份相同。RWA 仍是通用
`default-path`、零 option，不是 SimTop 专用开关。

## 3. RW -> RWF 复测

### 3.1 attempt、样本与 walltime

| order / attempt | 状态 | CPU / CCD | 说明 |
| --- | --- | --- | --- |
| `ABBA / 1` | accepted | CPU `136` / node1 `136-143,328-335` | 四个样本全部通过 |
| `BAAB / 1` | retryable 丢弃 | CPU `137` / 同一 node1 CCD | fixed-CCD pre-gate 最低 idle `93.33%` |
| `BAAB / 2` | retryable 丢弃 | CPU `39` / node0 `32-39,224-231` | fixed-CCD pre-gate 最低 idle `3.33%` |
| `BAAB / 3` | accepted | CPU `152` / node1 `152-159,344-351` | 四个样本全部通过 |

`C=RW`，`K=RWF`：

| 汇总 | accepted 顺序 / ms | RW mean / ms | RWF mean / ms | C-K / ms | 改善 | RW / RWF range |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `ABBA` | `C55331,K55540,K55115,C55484` | `55407.50` | `55327.50` | `80.00` | `0.144385%` | `55331-55484 / 55115-55540` |
| `BAAB` | `K55168,C55312,C55400,K55172` | `55356.00` | `55170.00` | `186.00` | `0.336007%` | `55312-55400 / 55168-55172` |
| pooled | 4 C + 4 K | `55381.75` | `55248.75` | `133.00` | `0.240151%` | `55312-55484 / 55115-55540` |

pooled control spread 为 `172 ms / 0.310572%`，candidate spread 为 `425 ms / 0.769248%`。
`0.240151% < max(1%, control spread)=1%`，即使状态字段因本轮双 order 同向而成为
`valid_direction_consistent_positive`，也不能越过预注册保留线。

### 3.2 与前次 F 结果交叉验证

| 实验 | ABBA | BAAB | pooled |
| --- | ---: | ---: | ---: |
| TNO0183 前次正式 | `+0.332900%` | `-0.014487%` | `55321.50 -> 55233.25 ms`，`+0.159522%` |
| 本次复测 | `+0.144385%` | `+0.336007%` | `55381.75 -> 55248.75 ms`，`+0.240151%` |

若仅做补充性、非预注册的两轮 16 样本等权合并，绝对均值为
`55351.625 -> 55241.000 ms`，减少 `110.625 ms / 0.199859%`。两轮共同把 F 的量级稳定在约
`0.2%`、与样本波动同量级；复测确认的是“几乎没有可靠收益”，而不是把第二轮的正方向误写成晋升证据。

### 3.3 F repeat PMU

| 指标 | RW | RWF | RWF 相对 RW |
| --- | ---: | ---: | ---: |
| cycles | `202551950625.75` | `202103373114.75` | `-0.221463%` |
| instructions | `162390750526.75` | `162390589864.25` | `-0.000099%` |
| frontend no-ops | `909314350875.25` | `906537768072.75` | `-0.305349%` |
| frontend cmask >= 6 | `118549403286.00` | `118179040192.50` | `-0.312412%` |
| backend stalls | `74626766520.75` | `74652151444.75` | `+0.034016%` |
| task-clock / ms | `55360.4775` | `55240.0500` | `-0.217533%` |

instructions 基本不变，cycles/frontend 的轻微变化与 walltime 同量级，backend stalls 还微增，没有形成足以
支持 F 默认的机器证据。

## 4. B -> RWA fresh endpoint

### 4.1 order 与 pooled walltime

`B` 是 evaluator 固定 current-default control，`K=RWA`：

| 汇总 | accepted 顺序 / ms | B mean / ms | RWA mean / ms | B-K / ms | 改善 | B / RWA range |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `ABBA` | `B60471,K53869,K53855,B60531` | `60501.00` | `53862.00` | `6639.00` | `10.973372%` | `60471-60531 / 53855-53869` |
| `BAAB` | `K54143,B60602,B60730,K54104` | `60666.00` | `54123.50` | `6542.50` | `10.784459%` | `60602-60730 / 54104-54143` |
| pooled | 4 B + 4 K | `60583.50` | `53992.75` | `6590.75` | `10.878787%` | `60471-60730 / 53855-54143` |

pooled B spread 为 `259 ms / 0.427509%`，RWA spread 为 `288 ms / 0.5334%`。两个 order 的收益都约
`10.8%`，远高于 `max(1%, control spread)=1%`；combined score 为 `1.122067314593163`，validity=`1`。

ABBA 固定 `node0:32-39,224-231`、CPU `32` / sibling `224`；BAAB 固定
`node0:48-55,240-247`、CPU `48` / sibling `240`。两组 admission gate 的 mean/min idle 分别为
`99.729375%/99.0%` 和 `99.916875%/99.33%`。8/8 accepted 样本均满足：

- affinity 精确、CPU migration `0`；
- personality `00040000`，地址随机化关闭；
- binary 与 NEMU NUMA local ratio `1.0`；
- 五个 PMU event 和 task-clock `100%` scheduled，CPU utilized `0.999`；
- context switch 约 `11.8/s` 且两臂相当；
- pre/continuous monitor、功能签名、guest cycle、terminal PC、唯一 walltime 全部 PASS。

### 4.2 B -> RWA PMU

| 指标 | B | RWA | RWA 相对 B |
| --- | ---: | ---: | ---: |
| cycles | `221489879034.00` | `197398655417.25` | `-10.876896%` |
| instructions | `162333684648.25` | `162370498207.75` | `+0.022678%` |
| frontend no-ops | `1005020638799.25` | `877065323496.50` | `-12.731611%` |
| frontend cmask >= 6 | `130974327577.00` | `112897774519.25` | `-13.801600%` |
| backend stalls | `76147691230.75` | `75278816475.50` | `-1.141039%` |
| derived IPC | `0.7329169412` | `0.8225511864` | `+12.229796%` |

guest 功能不变且 host retired instructions 仅 `+0.022678%`，walltime/cycles 同步下降约 `10.88%`、
frontend no-dispatch 下降约 `12.7%..13.8%`，继续支持 R/W/A 的代码布局和 outer-guard 前端机制，而不是
删除模拟工作。

## 5. 归因边界与最终决定

TNO0183 的独立 `B -> RW` endpoint 为 `8.460096%`，本次 `B -> RWA` 为 `10.878787%`。跨 session
直接相减为 `2.418691` percentage points，只能作 triangulation，不能精确标为 A 的同 session 边际。
将 `B -> RW` 与先前 direct A 的 `2.585383%` 做机械链乘，预测 endpoint 为 `10.826753%`，与本次
实测只差 `0.052034` point；这说明没有观察到明显负交互，但仍不替代同 session `RW -> RWA`。

综合证据链是：

1. TNO0183 的 `RWF -> RWFA` direct A 为 `2.585383%`，双 order 正向；
2. TNO0184 的两条机械路径和 symbol audit 证明 A 不依赖 F；
3. 本次无 F `B -> RWA` fresh endpoint 为 `10.878787%`，双 order 正向且远过信任线；
4. F 两次正式实验都只有约 `0.2%`，没有保留价值。

| 机制 | 最终消融决定 | landing/default 含义 |
| --- | --- | --- |
| `R` | 保留 | 进入最终组合 |
| `W` | 保留，依赖 R | 随 R 进入最终组合 |
| `F` | 停止 | 不落地、不开默认 |
| `A` | 保留 | 以无 F 的 `RWA` 进入最终 landing/default 候选 |

这里的“default 候选”指后续在 Wolvrix 通用 C++/Python 流程中落地并默认，而不是为 SimTop 单独加开关；
实际源码落地后的 final 50k walltime 仍是最后裁决。

## 6. Artifact 完整性与可继续性

F repeat artifact：

- 目录：`build/grhsim_simpletes_v2_ablation_20260727/direct_runs/direct_f_repeat_20260727_1920/`；
- `result.json` SHA-256：`cab094af48c9675ac5a69c1708f98a978781b7f8c2939a93fd9267e4f58ab748`；
- 合计 `72` files / `1918635 B`；
- 排序后全树 checksum-stream SHA-256：
  `feebe75f0d702dea627dc80ed8252bc6202d90670f5b465ae2e74634a403fe88`。

RWA fresh evaluator artifact 已固化到：

`build/grhsim_simpletes_v2_ablation_20260727/cumulative_results/rwa/`。

- evaluation SHA-256：`f66d10f6198693babcbac2e031e61b7e0de2cbcedd6b3099b3dad532dfde7f2c`；
- runtime result SHA-256：`291b9e310711ed8b552224c8633b1c57964d1c5d36141e8056d243c82c532cd3`；
- 16-entry main manifest SHA-256：`3de59cee03bca8b67ba96b6ac13cdfab3c58691dde9c703e4639ad730757b653`；
- 32-entry accepted raw runtime manifest SHA-256：
  `4e249e887de68e7965944f0ebafffbcfd2a1aa4e22179c35f9f55da0e5d1bb2f`；
- 合计 `50` files / `94986522 B`，全树 checksum-stream SHA-256：
  `de67cf8b9645aad461af3ad202af63534cb5e2a0e7a0391e630579be56a11569`。

两个 manifest 均通过 `sha256sum --check --strict`。immutable attempt ID 为
`01785155051622601312-1061615-b968ecd027164a9b8f1ec173205d7bde`，其 evaluation/runtime 与顶层副本
逐字节一致。

性能结束后，更新后的 artifact-only runner SHA-256 为
`2f68d215599f40d9d2d9c0d77c06efa9ed65eb9c9ecffd5b08f6613f9ef0f1e2`，显式
`b-to-rwa` 和 `rw-to-rwa` 两次无 emu validate-only 都返回 `validation_complete`。SimpleTES commit
`ef6e70c` 的完整测试为 `140 passed`，evaluator/runtime/env hash 未变，trusted slot 和 direct runner lock
均已释放；本阶段没有启动新的 auto research。后续可从现有 v2 checkpoint 正常继续探索，也可以直接复用
hard-pinned RWA snapshot 做新的显式消融。
