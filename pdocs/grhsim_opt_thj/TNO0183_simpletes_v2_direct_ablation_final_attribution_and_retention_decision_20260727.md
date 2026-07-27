# TNO0183 SimpleTES v2 direct ablation final attribution and retention decision

## 1. 阶段结论

[TNO0181](./TNO0181_simpletes_v2_cumulative_ablation_design_and_launch_20260727.md)
预注册的固定顺序顶层边际链 `B -> R -> RW -> RWF -> RWFA` 已完成。
[TNO0182](./TNO0182_simpletes_v2_r_result_and_rw_quiet_gate_exhaustion_20260727.md)
给出的 `B -> R` 正式结果继续有效；本阶段通过相邻臂 runtime-only 配对补齐 `W/F/A`，并用
`B -> RW` 做累计闭环。

最终 50k `Host time spent` walltime 结论为：

- `R`：`61505.75 -> 57466.50 ms`，绝对减少 `4039.25 ms`，改善 `6.567272%`；
- `W`：`57031.25 -> 55965.00 ms`，绝对减少 `1066.25 ms`，改善 `1.869589%`；
- `F`：表面为 `55321.50 -> 55233.25 ms`，绝对减少 `88.25 ms`、改善
  `0.159522%`，但 `ABBA` 正向、`BAAB` 反向，正式状态为
  `valid_direction_inconsistent`，判为 noise/neutral；
- `A`：`55485.00 -> 54050.50 ms`，绝对减少 `1434.50 ms`，改善 `2.585383%`；
- `R+W` 累计闭环：`60513.50 -> 55394.00 ms`，绝对减少 `5119.50 ms`，改善
  `8.460096%`。

因此本轮顶层消融把 v2 continuation 的有效来源定位为 `R`、`W` 和 `A`，`F` 没有可靠端到端收益。
`R/W` 已满足性能上的保留和默认候选门槛，`F` 应停止、不落地为默认。`A` 的直接收益很强，但当前只在
`RWF -> RWFA` 上证明；剔除 `F` 后的实际目标是 `RWA`，在补齐 `RW -> RWA` direct 和
`B -> RWA` endpoint 前，不把 `A` 直接宣告为最终默认。

这不是对 [TNO0173](./TNO0173_gen20_gen24_fresh_cold_guard_hint_ablation_result_20260724.md)
中旧 gen24 约 `18%` 的重新分摊。旧收益已由 register singleton cold hint 单变量解释并在
[TNO0176](./TNO0176_gen24_four_arm_function_formal_walltime_and_default_decision_20260725.md)
独立落地；本记录分析的是在该 current-default 之上的后续 v2 continuation refinement。

## 2. 机制、依赖与固定身份

| 符号 | 唯一新增机制 | 静态覆盖 | 依赖与本轮结论 |
| --- | --- | ---: | --- |
| `R` | exact-event register cold-layout refinement：singleton threshold `1024 -> 256`、`>=2048` register-write admission、`<=2048` group cap、known-nonzero 排除 | `20` cold runs、`46655` cold guards | 一个有意组合的 register policy；正式正向，保留 |
| `W` | 已由 `R` 选中的 run 内 singleton `MemoryWritePort` guard cold hint | `3704` sites | 不参与 admission，依赖 `R`；正式正向，随 `R` 保留 |
| `F` | 独立的 `>=128` singleton `MemoryFillPort` admission tier | `212` fills | 语义 admission 独立；方向不一致，停止 |
| `A` | exact-event `SystemTask + xs_assert_v2` 相邻 pair 的 assertion outer guard | `6308` pairs / `1842` supernodes | 与 commit 侧 `R/W/F` 源码逻辑独立；在含 `F` 条件下正式正向，待 `RWA` 补臂 |

`R` build 中的 `commit_supernodes=468`、`cold_runs=20`、`cold_guards=46655` 是不同对象的计数，
不能把 `20/468` 当成命中率；`selected=1` 表示 policy 被选中，不表示只有一个 run。

本轮固定：

- parent performance baseline：`fbe4e1cbbfcf45b52960545377020cb761c3ab25`；
- Wolvrix：`8f6ba14397b0c3d00cb909153af1c6464f4f1ed9`；
- SimpleTES：`3decc511e874e66f38d2bc41af845b03c156af28`；
- env SHA-256：`3922f9802d73b8422895b0628c0c948c1172e9a1cdfa1b94ece3fa3eadaa9e7a`；
- evaluator SHA-256：`d5a98c4dad44d8e5854efc5dfc5da9ac4d8f139eb9e8d76e50c57fd286eefc70`；
- runtime SHA-256：`fd3bb81b7295f90aed63ef6a829277563be4093ea26f76be22d6927f36f93f97`；
- direct runner SHA-256：`80590177516d0ef8dbdf5df26c3dc208b86c397a9e08c6a62210be01ea1c7666`；
- build-config fingerprint：`920b5c7f1e32e61e7ad363145521736e9a10a68d0e0d112ce7b4406f00e820b3`；
- toolchain fingerprint：`3139fef644317380a048f6d32551a70f2e960fe73558188951636856f4617038`。

四臂全部是 `default-path`、零 enable option、只修改 `lib/emit/grhsim_cpp.cpp`。arm 输入身份为：

| arm | fresh digest | emu SHA-256 | 11-file manifest SHA-256 | proof SHA-256 |
| --- | --- | --- | --- | --- |
| `R` | `df753aaf6c711a04df132375ec398bce534c7fb6ab96217a8dbb2c955dfdd049` | `fb0f34d6945dbd2c10eb43e08b347457c207ec47a2ede0e39b493ab90e644852` | `72ad865ab9e7856ed9ce60b9053d492c2977fcd323f81220693f43f732c7a3ca` | `d9a6a361be4f9896f8a72a1cdb2bbe1215de9ee53d2727044ae3fe33569b1feb` |
| `RW` | `591133ddd3439962cf8c45ce6fb3ee14cf5430b6270d6d21035c5c61ba8f8bd3` | `d1b39cc221f924e7197c496d9008e02f0114a618477b48980e11e93940c33bcc` | `60ea31a664a0aa3b1cdb2fcf5370e7b47ea5a3a5a9c7b291627bd3f84bdefc72` | `a6de83e7427f7d60981149e1d0aebbd2b0aa468e837aaee3ed37dad966b9b291` |
| `RWF` | `c1d2e073fde65c5e291d08324bc13f21d7f3ad0422442080b8a8eb6129b768bd` | `7e83b091228b5d9ca3a8af13f24d8770da6118dfac17fefa3fb141f22276dea9` | `edbaeecc621ee349baf2d74db776c19447e7f781555b625821572d6eee8cc853` | `63a0f961318ecf3e9d73b26224135b24cd6b666a0ddf6f880aad412e88ea8895` |
| `RWFA` | `676ee3646b6d54f9e0127750ecd9b2b32f1aed4b79cad3589925e8caa2f3d892` | `0c6986ef3dd4c6723a5bd13ccbb39f206f828276db035f5628b4fd555055bd8e` | `9b8faca1f1fb073f83ad87e5bdfb6283d120c48d705e1833c3dd59d12ebe0a74` | `334fdfc53fb54310436bb990ac7600e8cc38fe5742bd24d9bfa9d62bb0ad7402` |

## 3. 正式协议与可信度门禁

direct runner 只复用已经通过 fresh build、focused、100-cycle、10k-cycle 和 proof 固化的二进制，
每个相邻 pair 在进入 runtime 前后都重验 arm snapshot。正式协议保持：

1. SimTop `50000` cycles，headline 只取日志中唯一的 `Host time spent` walltime；
2. 先 `ABBA`，仅在有效且正向时 promotion 到独立 `BAAB`；
3. 每个 order 为 control/candidate 各 `2` 个样本，pooled headline 为 `4+4` 个样本；
4. 动态选择完整 CCD，3 秒 whole-CCD gate 要求 `count=16`、mean idle `>=98%`、minimum
   idle `>=95%`、target+sibling `>=98%`；
5. 单物理核、SMT peer monitor、NUMA first-touch、PMU scheduling、context switch、功能签名和唯一
   walltime 都是硬门禁；
6. 地址随机化必须关闭，accepted process personality 必须为 `00040000`；
7. retryable group 整体丢弃，不能把未完成样本拼入 headline；direct runner 与 SimpleTES evaluator
   共用 trusted slot 排他锁。

`R/W/F/A` 四个正式 pair 合计 `32` 个 accepted 样本；补充 `B -> RW` 再增加 `8` 个。全部 accepted
样本满足 personality `00040000`、CPU migration `0`、PMU events/task-clock `100%` scheduled、功能、
affinity、pre/continuous monitor、NUMA binary/NEMU local ratio `1.0`。每个 emu log 恰有一个 walltime，
与 function audit、accepted attempt/runtime/result JSON 逐样本相等。

## 4. R/W/F/A 顶层边际结果

### 4.1 order 与 pooled walltime

`C` 为较早 arm control，`K` 为新增当前机制后的 candidate；括号内是 accepted 顺序。

| 机制 / pair | order | accepted walltime / ms | C mean / ms | K mean / ms | C-K / ms | 改善 | C / K spread |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `R`, `B -> R` | `ABBA` | `C61722,K57644,K57614,C61842` | `61782.00` | `57629.00` | `4153.00` | `6.722023%` | `120/30 ms` |
|  | `BAAB` | `K57466,C61225,C61234,K57142` | `61229.50` | `57304.00` | `3925.50` | `6.411125%` | `9/324 ms` |
|  | pooled | 4 C + 4 K | `61505.75` | `57466.50` | `4039.25` | `6.567272%` | `617/502 ms` |
| `W`, `R -> RW` | `ABBA` | `C57345,K56544,K56162,C57102` | `57223.50` | `56353.00` | `870.50` | `1.521228%` | `243/382 ms` |
|  | `BAAB` | `K55737,C56774,C56904,K55417` | `56839.00` | `55577.00` | `1262.00` | `2.220306%` | `130/320 ms` |
|  | pooled | 4 C + 4 K | `57031.25` | `55965.00` | `1066.25` | `1.869589%` | `571/1127 ms` |
| `F`, `RW -> RWF` | `ABBA` | `C55502,K55311,K55164,C55342` | `55422.00` | `55237.50` | `184.50` | `0.332900%` | `160/147 ms` |
|  | `BAAB` | `K55291,C55284,C55158,K55167` | `55221.00` | `55229.00` | `-8.00` | `-0.014487%` | `126/124 ms` |
|  | pooled | 4 C + 4 K | `55321.50` | `55233.25` | `88.25` | `0.159522%` | `344/147 ms` |
| `A`, `RWF -> RWFA` | `ABBA` | `C55277,K53916,K54077,C55349` | `55313.00` | `53996.50` | `1316.50` | `2.380091%` | `72/161 ms` |
|  | `BAAB` | `K54114,C55561,C55753,K54095` | `55657.00` | `54104.50` | `1552.50` | `2.789407%` | `192/19 ms` |
|  | pooled | 4 C + 4 K | `55485.00` | `54050.50` | `1434.50` | `2.585383%` | `476/198 ms` |

pooled control spread 分别为 `R 617 ms / 1.003158%`、`W 571 ms / 1.001205%`、
`F 344 ms / 0.621820%`、`A 476 ms / 0.857890%`。`W` 和 `A` 的两个 order 都正向，且收益高于
预注册的 `max(1%, control spread)` 信任线。`F` 不仅 pooled `0.159522%` 低于信任线，反序还轻微
回退，因此不能把表面减少 `88.25 ms` 写成确定收益。pooled candidate spread 分别为
`R 502 ms / 0.873552%`、`W 1127 ms / 2.013759%`、`F 147 ms / 0.266144%`、
`A 198 ms / 0.366324%`；W 的 candidate 跨 order spread 较大，因此其结论还同时依赖双 order 正向和
`B -> RW` 累计闭环，不把单个 pooled 数值孤立使用。

### 4.2 placement 与 accepted attempt

| pair | ABBA accepted attempt / CPU / CCD | BAAB accepted attempt / CPU / CCD |
| --- | --- | --- |
| `R -> RW` | `3` / CPU `108` / node1 `104-111,296-303` | `3` / CPU `74` / node0 `72-79,264-271` |
| `RW -> RWF` | `4` / CPU `120` / node1 `120-127,312-319` | `2` / CPU `168` / node1 `168-175,360-367` |
| `RWF -> RWFA` | `2` / CPU `42` / node0 `40-47,232-239` | `2` / CPU `121` / node1 `120-127,312-319` |

W 丢弃 `4` 个 retryable group，正式 F retry 批次丢弃 `4` 个，A 丢弃 `2` 个。失败原因均为完整
CCD/pre-gate 外部负载、运行期 peer contamination 或 PMU/context-switch gate；没有 candidate 功能失败，
也没有把 discarded raw 样本混入上述均值。

### 4.3 F 的首批 exhaustion 与正式补测

首批 `direct_f_20260727_1558` 的有效 ABBA 为
`55765.00 -> 55594.00 ms`，减少 `171.00 ms / 0.306644%`，与正式重测 ABBA 的
`0.332900%` 接近；但其 BAAB `9/9` 均为 retryable infrastructure，最终状态为
`baab_retry_exhausted`，aggregate walltime 为 `null`，不能回退使用单独 ABBA。

正式 `direct_f_retry_20260727_1625` 从头重跑完整 pair，最终得到上表轻微反向的 BAAB，状态为
`valid_direction_inconsistent`、`direction_consistent_positive=false`、`combined_score=1.0`。首批 BAAB
与正式 retry 中已产生但被 gate 丢弃的 raw walltime 均保留在 run artifact 中，仅用于基础设施审计，
不参与任何性能统计。

## 5. B -> RW 累计闭环

| order | accepted walltime / ms | B mean / ms | RW mean / ms | 绝对减少 / ms | 改善 | B / RW spread |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `ABBA` | `B60590,RW55395,RW55337,B60541` | `60565.50` | `55366.00` | `5199.50` | `8.584920%` | `49/58 ms` |
| `BAAB` | `RW55095,B60360,B60563,RW55749` | `60461.50` | `55422.00` | `5039.50` | `8.335056%` | `203/654 ms` |
| pooled | 4 B + 4 RW | `60513.50` | `55394.00` | `5119.50` | `8.460096%` | `230/654 ms` |

ABBA/BAAB 分别固定在 CPU `88`、node0 `88-95,280-287` 和 CPU `136`、node1
`136-143,328-335`；accepted attempt 为 `8/1`。其余 `7` 个 ABBA attempt 全部按基础设施失败丢弃。

由独立 `R` 与 direct `W` 的 stage reduction 做机械乘法，预测 `B -> RW` 为 `8.314080%`；实测
`8.460096%`，相差 `0.146015` percentage point。不同 pair 位于不同 CCD 和时间窗，这只能作为
triangulation，说明没有观察到负交互，不能把差额精确归因为新的协同机制。实测 `B -> RW` 是
`R+W` 当前唯一权威 cumulative endpoint。

## 6. PMU 归因

下表是 8 个 accepted 样本的 pooled mean，变化方向为 candidate 相对 control：

| pair | cycles | instructions | frontend no-ops | frontend cmask >= 6 | backend stalls | task-clock |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `B -> R` | `-6.687843%` | `+0.034669%` | `-7.435799%` | `-7.191032%` | `-2.019149%` | `-6.569549%` |
| `R -> RW` | `-1.966156%` | `+0.000600%` | `-2.111833%` | `-2.278799%` | `-1.396844%` | `-1.840141%` |
| `RW -> RWF` | `-0.169251%` | `-0.000099%` | `-0.320756%` | `-0.353420%` | `+1.148817%` | `-0.161797%` |
| `RWF -> RWFA` | `-2.596270%` | `-0.012590%` | `-3.484004%` | `-4.794347%` | `+0.032192%` | `-2.587217%` |
| `B -> RW` | `-8.456737%` | `+0.035177%` | `-9.420347%` | `-9.329538%` | `-2.116631%` | `-8.440922%` |

W 的 pooled cycles 绝对均值为 `208039139925.50 -> 203948766678.00`，instructions 为
`162389776407.75 -> 162390751255.25`；A 的 cycles 为
`202779822096.25 -> 197515109538.75`，instructions 为
`162390591858.25 -> 162370146175.75`。两者 host retired instructions 基本不变，而 cycles、
task-clock 与 frontend no-dispatch 明显下降，符合 cold-layout/outer-guard 的前端机制，不像少执行了
功能路径。F 则没有稳定 walltime 方向，backend stalls 还增加 `1.148817%`，不支持默认采用。

## 7. 百分比组合的边界

不同 stage 的百分比有不同 control 分母，不能直接相加。若只做数学推导，把四个 pooled stage
reduction 机械链乘：

```text
1 - (1 - pR)(1 - pW)(1 - pF)(1 - pA) = 10.826991%
```

朴素相加得到 `11.181767` percentage points，比链乘多 `0.354776` point。但 `10.826991%` 仍不是
实测 `B -> RWFA`：四个 pair 来自不同 session/CCD，旧 serial `B -> RWFA` 又因 quiet gate 没有
accepted headline。进一步地，F 已被判为 noise/neutral，而 A 仅在含 F 的 control 上测过；所以也不能
把 `B -> RW 8.460096%` 与 A 的 `2.585383%` 机械组合后宣称为最终 `RWA` 性能。

本轮回答的是预注册固定顺序的顶层来源：R、W、A 有信号，F 没有。最终落地集合的权威 endpoint
必须由新的 `RWA` artifact 实测。

## 8. artifact 完整性与可继续性

正式 artifact 位于 ignored 目录：

`build/grhsim_simpletes_v2_ablation_20260727/direct_runs/`。

| run | 顶层 result SHA-256 | files / bytes | 排序后全树 checksum-stream SHA-256 |
| --- | --- | ---: | --- |
| `direct_w_20260727_1545` | `5a4549ae7f68a80cedc0c15127f539cfca1c2045b00c4fcd2c465bf77f334f70` | `112 / 2489728` | `f2f6e34474626b76b3eb37c3b8205a3d43a7e5d160360540267280a56e2c052b` |
| `direct_f_20260727_1558` | `befcafd223db94700428ceecbaa057619074c3f91b31d88b666fd663ca1f4438` | `140 / 1750110` | `697a4a7a5029883b4fcdd3c106cda8a1a179ba574da348fe039d9a33d7ffefd2` |
| `direct_f_retry_20260727_1625` | `00b2e248d638c3b2e9a496a59b70fb3efba8735020afc0e479e481fcb3942c6a` | `96 / 2122809` | `697c3c20552d0753f512fce33e27e6c1f33cb263eb6cde68813e5fc40725a9d3` |
| `direct_a_20260727_1643` | `370a1bd9a64e66f284bf93bb7eee8dd9e66cdc879d2fc867646d85418dbd4424` | `92 / 2353814` | `78336b8b0860aae9b0d5cd1c085f7a63d20033bac355c7bc92a1e9bbcdcf2da7` |
| `cumulative_rw_20260727_1702` | `93fd5c2e4148a34f4a1a3131a0ccb5c1ec22fb2be69e54a44664e37e86d60fed` | `143 / 2283620` | `1fff2dd8310ec7f21e7993e9a1128486627cdfeccce7edea677b45e052b53e35` |

全树摘要的重算算法是在各 run 根目录内对按 NUL 排序的全部 regular file 执行 `sha256sum`，再对完整
`sha256 + relative path` stream 求 SHA-256。本表把只读重算值持久化在 tracked 文档中，弥补 direct
runner 当时没有单独输出 raw checksum manifest 的缺口；它不是 runner 自认证字段，复核时仍应同时
检查 result、attempt JSON 与 arm hard pins。

accepted raw 的独立 checksum-stream 只纳入 result 中 8 个 accepted sample 各自引用的
audit/emu-log/monitor/perf-CSV 四件套，路径使用 run-root-relative `pairs/...` 且没有前导 `./`，仍按
`sha256 + relative path` 排序后重算；摘要为：

- W：`ce77e2b87e003ab48a94444cd05c6a98542537106803e71a358850971bbe638e`；
- F 正式 retry：`631fb02b3539ac281a4b7399a741a15737cfdcee47899fae2b66a1c9b4492079`；
- A：`54e5d577997aeaa22df7a67b0e4cd77124d18c499c79f31872f46bcd7c086c70`；
- `B -> RW`：`c9ced4e79bb8bb66941ff212d9f11445c8d0843c2131f32bb51243f4b780ac59`。

R 的 immutable evaluation SHA-256 为
`9d6c188f72402cc1f208711c106de9fe824dab16805ac1c1672b01b3a8c7e6aa`，raw runtime manifest
SHA-256 仍为 `4051297e3579f14367b08cc434f43132cb1440d44514463b2293abf5c3693914`。

审计确认 result、pair result、accepted attempt、runtime result、metrics 与 raw walltime 逐层一致；
所有已生成的 arm pre/post checksum 日志通过。性能结束后又执行了两次无 emu validate-only：默认
`R -> RW / RW -> RWF / RWF -> RWFA` 与显式 `B -> RW` 均返回
`validation_complete`。runner SHA 保持不变，trusted slot 已释放，Wolvrix 与 SimpleTES 都没有新增
tracked 修改，因此后续 SimpleTES 探索仍可在原 schema-v2 pin 上正常继续。

## 9. 保留、停止与下一步

| 机制 | 本轮决定 | 下一动作 |
| --- | --- | --- |
| `R` | 保留 | 作为 register-policy bundle 进入 landing；若还要解释 bundle 内部，再另立二级消融，不阻塞本轮顶层结论 |
| `W` | 保留，依赖 `R` | 与 `R` 组成 `RW`；`B -> RW 8.460096%` 已完成 endpoint 闭环 |
| `F` | 停止，不默认 | 不放入目标落地组合；保留 artifact 供历史审计 |
| `A` | 保留为候选，暂不直接默认 | 从 `RWFA` 机械去掉 F，构造 fresh `RWA`；先做 build/focused/100/10k，再跑 `RW -> RWA` direct |

若下一阶段只落 `R/W`，本轮 `B -> RW` 已给出正式 endpoint；仍需在落地后的真实源码上重做
focused/full regression、CTest、100/10k 与 final 50k 回归。若把 `A` 一并放入最终默认组合，则在修改
Wolvrix 默认前还必须完成 `B -> RWA` 的 fresh fixed-ASLR SimTop 50k endpoint；只有这个 walltime
端到端仍正向，才把 R/W/A 在通用 C++/Python 流程中默认，而不是为 SimTop 单独开开关。当前文档只
完成消融归因与保留建议，没有把 checkpoint patch 写入 Wolvrix，也没有启动新的 auto research 实例。
