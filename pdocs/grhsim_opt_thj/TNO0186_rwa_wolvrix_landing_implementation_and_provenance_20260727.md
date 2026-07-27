# TNO0186 RWA Wolvrix landing implementation and provenance

## 1. 阶段状态

[TNO0184](./TNO0184_simpletes_v2_rwa_materialization_and_fresh_gate_20260727.md) 已从历史
`RW/RWF/RWFA` candidate 机械构造无 `F` 的 `RWA`，
[TNO0185](./TNO0185_simpletes_v2_f_repeat_and_rwa_endpoint_decision_20260727.md) 又以 fresh 50k endpoint
确认最终 landing 候选收敛为 `R/W/A`、排除 `F`。本阶段开始把该候选落入实际 Wolvrix 通用默认源码，
不增加 SimTop 专用路径。

当前实现快照已经完成三项阶段门禁：

| 项目 | 当前状态 | 当前证据边界 |
| --- | --- | --- |
| 生产源码落地与身份复核 | `PASS` | 实际应用后的目标源码 SHA-256 与历史 RWA 物化结果一致 |
| 独立代码审计 | `PASS` | 已独立核对实现边界为 `R/W/A`，且未带入 `F` |
| fresh build 目标编译 | `PASS` | fresh build 的目标编译已成功 |
| focused regression | `PENDING` | 尚无最终 focused 数量或日志身份 |
| full regression | `PENDING` | 尚无完整 CTest / Python / XS 最终结果 |
| production SimTop gate | `PENDING` | 尚无本次真实默认 production 生成与 100/10k 最终记录 |
| formal 50k performance | `PENDING` | 尚无落地源码的 ABBA/BAAB 最终 walltime 裁决 |
| commit hashes | `PENDING` | 尚未形成 Wolvrix、parent 或 SimpleTES 的本阶段提交身份 |

因此本文记录的是**正在进行中的 implementation/provenance checkpoint**，不是最终功能回归、性能采用或
提交闭包。上述 `PASS` 不能替代仍为 `PENDING` 的门禁。

## 2. 源码与 patch provenance

本次落地涉及的三个身份必须分开解释：

| 对象 | SHA-256 | 含义 |
| --- | --- | --- |
| 落地前基线 `grhsim_cpp.cpp` | `376fed1c3a1a297abd496ad8a87dc705a2fd9e279e70873a15e060098a5aaf2c` | 实际改动前的生产源码身份 |
| 历史存储的 baseline-to-RWA patch | `2e2969508e3975490f501707724a80e3d4d76a62320bd27f7279f3f1341f14c0` | TNO0184 已物化、保存并验证的候选 patch 内容身份 |
| 本次实际应用后的生产源码 | `3739547b0c88676a0c0a4ee9c544f60df01754e2d13a18b81e821d11a6c45e84` | patch 真正应用到当前目标文件后重新计算得到的源码身份 |

后两个哈希在开始本次落地前已经可作为历史候选的 patch 身份和预期物化身份，但当时不表示生产 worktree
已经修改。现在 patch 已实际应用，重新计算得到的生产源码 SHA-256 为 `3739547b...`，与历史物化结果一致；
这是落地后的身份复核，而不是用预期值代替实际检查。

当前尚无可报告的本阶段 commit 身份：

- Wolvrix landing commit SHA：`PENDING`；
- parent Wolvrix gitlink snapshot commit SHA：`PENDING`；
- SimpleTES repin / continuation commit SHA：`PENDING`；
- parent 后续文档 commit SHA：`PENDING`。

这些值只能在对应提交实际产生后记录，不能从 patch 或文件 SHA-256 推导。

## 3. R/W/A 实现边界

本次生产源码只落地 `R/W/A`：

- `R`：降低 cold guard admission 门槛到 `256`；register-write group 最多支持 `2048` 项，并保留
  `2048` 个 eligible writes 的另一条 admission 条件；静态已知非零 guard 不进入该路径。
- `W`：只在 `R` 已 admission 的 run 内提示 singleton `MemoryWritePort`；memory write 自身不参与
  admission，共享 memory group 不按 singleton 处理。
- `A`：在满足严格结构和副作用约束时，为相邻的 `SystemTask` 与 `xs_assert_v2` DPIC 合并 outer guard；
  DPIC 内部仍保留自己的条件复核。
- `F`：memory-fill tier 明确排除，不随本次 patch 落地，也不作为 `R` 或 `W` 的 admission 输入。

控制边界保持通用默认语义：

- `R/W` 继续由既有 `commit_exact_event_policy=targeted-cold-layout` 控制，显式 `off` 关闭二者；
- `A` 与 `R/W` 独立，不借用该开关，也不新增 SimTop 专用开关；
- `active_mask_gap_pack_policy=targeted-direct` 继续默认关闭；
- Python `None` 与 XS 未设置 override 时继续继承 C++ 默认，不改变公共 API。

## 4. 已完成审计与编译门禁

独立代码审计结果为 `PASS`。当前可确认的范围是：实际生产 diff 对应上述 `R/W/A` 边界，`F` 保持排除，
没有把历史 materialization 的哈希误写成提前完成的落地或提交身份。审计不产生 commit SHA，也不代表
focused、full regression 或 production runtime 已通过。

fresh build 的目标编译结果为 `PASS`。这证明当前落地源码至少完成了 fresh 编译门禁；最终 focused 数量、
完整测试通过数、已知失败绝对耗时、production 生成 fingerprint、100/10k 功能签名与 50k walltime 仍未
形成，因此全部保持 `PENDING`。

## 5. 待闭合项目

后续记录必须以实际产物补齐以下项目，不得预填结果：

1. `PENDING — focused`：补齐 `R/W` admission 边界、memory-write 正负例与独立 assertion outer-guard
   focused CTest，并记录绝对通过数和日志身份。
2. `PENDING — full`：完成 fresh Release/Ninja 完整 CTest、Python option unittest、XS sparse-option
   unittest、legacy targeted-direct focused 与 `git diff --check`。
3. `PENDING — production`：用普通 `options={}` fresh 生成 SimTop，核对默认来源、generated fingerprint、
   100/10k 功能签名及 fixed-ASLR personality。
4. `PENDING — perf`：对实际 landing 默认执行独立 ABBA 与 BAAB 50k `Host time spent` 门禁，记录逐样本
   绝对值、spread、CCD/CPU/NUMA 与所有重试。
5. `PENDING — commits`：在相应功能、性能与 repin 阶段实际提交后，再记录 Wolvrix、parent 与 SimpleTES
   commit SHA；当前不得推测。

按照本目录 append-only 规则，focused/full、正式性能和 SimpleTES repin/canary 的后续结果应由新的
`TNOxxxx` 阶段记录承载；本文保留为落地实施中的 provenance checkpoint。

## 6. 增量更新 2026-07-27：fresh regression 与 executable snapshot

第 1、2、4、5 节的 `PENDING` 是初始 implementation checkpoint 当时的状态。本次增量不删除或覆盖该
历史上下文，只闭合已经实际产生证据的 focused/full regression 与部分 commit 身份；尚未执行的
SimpleTES production/canary 和正式性能仍为 `PENDING`。

### 6.1 提交身份

本阶段已经实际形成两个提交身份：

- Wolvrix RWA landing commit：`16a9f493687a21a5428f1e1327a69834ea60c9f5`；
- parent executable snapshot commit：`d31118bea0feb563ad09476e1419f0f15aaf574f`。

parent snapshot 固定上述 Wolvrix gitlink，作为后续 SimpleTES 可 pin 的 executable 身份。仍未形成的提交
继续明确为：

- SimpleTES repin / continuation commit SHA：`PENDING`；
- parent 后续文档 commit SHA：`PENDING`。

### 6.2 Fresh build、focused 与 full regression

fresh Release/Ninja 构建完成全部 `94` steps，结果为 `PASS`。本轮 fresh wheel SHA-256 为：

`9f0309607b27f3f8c4da54d779a635944dd6a3361634adb961c74a7abb940330`。

实际回归结果如下：

| gate | 绝对结果 | 状态 |
| --- | --- | --- |
| fresh Release/Ninja | `94` steps | `PASS` |
| focused commit-exact-event | `18.99 s` | `PASS` |
| focused assertion outer-guard | `8.55 s` | `PASS` |
| full CTest | `50/52`，总耗时 `291.31 s` | `PASS`，仅保留两项历史 expected failures |
| pybind option unittest | `22/22` | `PASS` |
| XS sparse-option unittest | `32/32` | `PASS` |

full CTest 中唯二未通过项是历史 expected failures：

- `transform-comb-lane-pack`；
- `transform-repcut`。

它们不是本次 RWA landing 新增失败；除此之外没有新的 full-regression failure。由此，第 1 节中的
`focused regression=PENDING` 与 `full regression=PENDING` 已在本增量中闭合为 `PASS`。

### 6.3 Infra discovery 与产品失败边界

最初一次检查误用了 stale binding/cache，不能代表 fresh wheel 的产品结果，因此该次运行被识别为
infrastructure discovery 并丢弃；随后使用上述 fresh wheel 重新执行并取得正式结果。另有一次 XS 调用使用
错误路径，同样属于调用路径的 infrastructure discovery；修正路径后的正式结果为 `32/32 PASS`。

这两项都不计为 Wolvrix 产品失败，也不进入 full CTest 的 `50/52` 统计。产品回归口径只采用 fresh、路径
正确且身份可核对的结果。

### 6.4 继续保持 PENDING 的项目

本增量没有提前填写尚未执行的后续结果：

- SimpleTES repin、production SimTop 默认生成、100/10k、continuation canary：`PENDING`；
- 落地后正式 50k ABBA/BAAB 性能回归与 default 裁决：`PENDING`；
- SimpleTES 与后续 parent 文档 commit SHA：`PENDING`。

这些项目必须由后续实际产物和独立阶段文档闭合；不得用本节的编译/回归 `PASS` 或历史 RWA endpoint
替代。

## 7. 增量更新 2026-07-27：后续闭合索引

第 5 节及 6.4 节的 `PENDING` 保留为当时的历史状态；后续实际执行结果已由独立阶段文档闭合：

- SimpleTES repin、普通 `options={}` production build、100/10k、native control canary 与 continuation
  边界：见
  [TNO0187](./TNO0187_rwa_landing_simpletes_repin_and_native_control_canary_20260727.md)，结果 `PASS`，
  SimpleTES commit 为 `b0c7754651c84cd4de5e02aa01bad67fa2c0ae4a`；
- 实际 B→native-RWA final ABBA/BAAB 50k、artifact 完整性和最终默认裁决：见
  [TNO0188](./TNO0188_rwa_landing_native_50k_performance_and_default_decision_20260727.md)，pooled
  walltime 为 `60,881.50 -> 54,088.00 ms`，减少 `6,793.50 ms / 11.158562%`，结果 `PASS`。

因此原 checkpoint 中的 production/perf/SimpleTES commits 三类待办均已实际闭合。后续 parent 文档提交
只承载记录，不改变 `d31118b...` executable snapshot，也不要求把 SimpleTES 的可执行 pin 改到 docs-only commit。
