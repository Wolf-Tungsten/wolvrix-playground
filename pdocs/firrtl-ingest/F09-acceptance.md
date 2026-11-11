# F09 验收：op 软提示、simplify 透明性与统一 nonsink 分图

日期：2026-10-31。分支：playground / wolvrix 均为 `grh/firrtl-ingest`。
前置实现：playground `d7d414a`、wolvrix `5f31043`（F08）。设计见
[F09-plan.md](F09-plan.md)，正式属性合约见
[node-attributes.md](../../wolvrix/docs/ingest/node-attributes.md)，分图配置见
[grhsim-transforms.md](../../wolvrix/docs/transform/grhsim-transforms.md#execution-node-construction)。
Wolvrix F09 实现提交：`7e51d14`。playground 的同阶段提交包含流程接线、
本验收与子模块指针。

后续决定：有 FIRRTL 提示按提示、无提示按 MFFC 形成统一 node；
supernode 按 node 数量分组，不感知内部 op 数/work。F09.6 设计见
[F09-plan.md](F09-plan.md)，现已实施，验收见
[F09.6-acceptance.md](F09.6-acceptance.md)，已取代“单 node 超 work 预算豁免”
的规划。本页保留 `7e51d14` 的旧行为和测量，不能用于验收新两层分图。

F09.0–F09.5 已实现并通过本阶段验证。**node 是 op 上可丢失、可重叠的
关联提示，不能阻碍 simplify，也不规定不可分执行区域。** 本验收不包含
香山整机混合输入差分或正式性能提升结论；这两项分别属于 F10/F11，F00
的完整依赖/基线清单仍须补齐。

## 1. 逐项结果

| 子阶段 | 实际实现 | 验证证据 |
| --- | --- | --- |
| F09.0 撤除屏障 | schema 2 / soft-node-v2；普通 CSE 去除 source scope；inline/root 工具只保留实际 owner 约束；移除 mux/write 的 annotated 拒绝；不创建根载体 | firrtl-cse-scope、firrtl-node-attributes、firrtl-node-pipeline；标注/去标注规范化结构一致及独立行为记分板 |
| F09.1 有界索引 | 当前 nonsink ops 的 members 构成允许相交、非凸、无根及不完整的集合；不传递 union，不使用 origins 分组 | grhsim-firrtl-nodes 的部分/完整/零覆盖、重叠、非凸与预算回归；真实 RenameTable 根全失仍消费成员 |
| F09.2 共同分图 | off 保留属性但不影响决定；prefer/auto 排等权 coarsen 链接和同成本 DP 候选；通过真实 quotient 无环、effects、预算检查 | 同 checkpoint 的 off 与无提示基线 owner 一致；存在提示改变同成本 owner 的专项；独立 oracle 与 SinkSchedule |
| F09.3 独立成本 | legacy 保留共同成本；bytes 绕过 greedy coarsening，在拓扑 leaf 区间加入 payload bytes 与 firing×work 代理 | off/prefer × legacy/bytes 独立开关；RenameTable 六组及冻结 Queue2 调用计数，无改善项如实记录 |
| F09.4 owner / clone | 可选 leaf fusion；单轮 bounded clone；支持常量计入 work；要求输入已到达目的 SN，不增加激活来源；后续 simplify/sink 重新建依赖 | leaf/SN 预算、拒绝 clone、正向可获益 clone、实际 owner 与行为回归；混合及状态/effects 编译执行 |
| F09.5 配置/验收 | Make/Python/XS/reemit 参数与版本化 checkpoint；snapshot 报告、幂等重放及 generation identity | Python 4 项、全阶段恢复及 10 个 SV 编译模型；旧配置拒绝；全量 79/79、HDLBits001、真实模块报告 |

## 2. simplify 与属性迁移

`firrtl.node.members/roots/rootResults/origins` 仍使用普通 op attrs。不同
source node 或 SV 的等价 primitive op 可以共享，代表 op 合并直接关联。
重写只传播实际参与者的有界信息，不扩张上游来源闭包；根只能按准确
result mapping 维护，否则删除。DCE 依真实消费者执行，inventory 不保活。
`redirectRoots` 不增加 op/value；`rootCarrier` 恒为 false，`cseScope` 为空。

每 op 的 members、roots、origins 分别上限 64；超限清除可选 attrs 并累计
`firrtl.nodeHintDegraded`，不拒绝功能变换。缺失/重复根、部分/非凸集合和
phase copy 正常合法；schema、字段类型、canonical key、配对数组及 result
序号损坏仍报错。真实类型、声明、phase、效果和实际执行 owner 的限制仍在。

专项不仅检查行为，还把相同初始计算图复制为带标注/仅移除 node 非功能
信息两份，执行普通与生产流水，移除诊断信息后比较规范化计算结构。
`firrtl-node-pipeline` 的完整 JSON 结构对照通过。覆盖跨 node/SV CSE、
内联/重关联、输入/常量折叠、无额外载体、DCE、数组、packing、masked-OR、
mux/write normalization、phase/sink 和实际 owner。

控制普通 primitive CSE。只分析仍能证明的单根完整候选，已共享、无根、
不完整或关联依赖重叠的候选跳过，不能让合法 op DAG 失败。策略为
`gsim-soft-v2`，配置为 `v2/<mode>/5/256/1`；普通优化无需为了候选保留根。

旧 schema 1 / `source-node-v1` / `gsim-v1` checkpoint 要求重新 ingest。
旧八字段已完成 nonsink 配置要求从 nonsink-sink-split 重启，不静默改变
既有优化历史。F02/F08 验收继续保留历史口径，不作为当前策略证明。

## 3. 分图及报告口径

- `firrtl-nodes=off|prefer|auto` 只控制提示消费者；默认 off，auto 有提示时
  使用 prefer 策略，无提示时退回共同 op 基线。
- 临时 leaf/cluster key 集合最多 256 个 canonical keys，稳定截取。
  它不证明区域完整，也不把相交集合做传递 must-link。
- `cost-model=legacy|bytes` 默认 legacy；bytes 的目标为
  `sum(rate*payloadBytes) + penalty + sum(rate)*intervalWork`。没有根据
  源语言或 node 名猜活动率；该静态代理不等于实测重复求值。
- `fuse-leaves=0|1` 默认 0，只在同 SN 内按 leaf 拓扑顺序及公共 cap 融合。
  clone 包括支持常量在内都遵守 leaf/SN cap；单个不可分超限 op 是唯一例外。
- `grhsim.nonsinkHintStats` / report 是 nonsink partition + clone 后、后续
  simplify 前的 snapshot。`hint-score` 合计已接受 coarsen 的共享关联分数
  和选中 segment 的 common-member 分数，不是命中的 node 数，也不证明
  相比 off 实际改变了决定。拒绝的循环 coarsen 批次不累计。
- `hint-index-references` 是初始 leaf/key 对数，`hint-index-truncated` 是初始
  插入溢出事件数，不是唯一丢失 key 数，不含后来 cluster 合并的截取。
  `mixed-groups` 指多关联组，不是跨语言计数。边界 census 含 sink/event/output。
- `hint-analysis-us` 从索引构建计时至分图/报告完成，不是孤立属性开销。
  幂等运行可重放相同 snapshot；生成身份包含配置与统计。

新配置：

```text
v2/maxNodeWork/maxSupernodeWork/segmentPenalty/semanticNodes/cloneShared/cloneMaxFanout/maxClones/cloneLossyCompare/firrtlNodes/costModel/fuseLeaves/op-hints-v1
```

## 4. 回归命令与结果

全部通过项目 Makefile，`WOLF_ENV_SOURCED=1`，日志根为
`ptmp/firrtl-ingest/F09/`。示例从 playground 根目录运行；`PYTHON` 使用已有
`.venv/bin/python`，Python 安装通过 `make py_install`。系统 Python 首次安装
因缺 pip 失败，切换已有 venv 后完成，未将失败尝试记为通过。

| Make 入口 | 结果 | 日志 |
| --- | --- | --- |
| `test_grhsim_firrtl_nodes` | hints/cost/owner/fusion、预算拒绝与正向 clone；新增非凸及幂等报告回归通过 | `partition-final.log` |
| `test_wolvrix` | 79/79，通过；最终全量 5.67 s | `all-tests-final.log` |
| `test_grhsim_flow PYTHON=$PWD/.venv/bin/python` | py_install 后 4 项通过；纯 SV 所有 5 checkpoint × 两种函数预算，共 10 个模型编译执行 | `flow-tests.log`；最终复跑 `flow-final.log` |
| `test_firrtl_target test_ingest_mixed test_firrtl_comb test_firrtl_state test_firrtl_memory test_firrtl_effects` | 全部生成并编译执行；mixed 含 FIRRTL→SV→FIRRTL 与 SV→FIRRTL、hint/bytes/fused 变体 | `compiled-tests.log` |
| `test_firrtl_target` | 冻结 Queue2 的五组及 SRAM/JTAG/ClockGate 通过，打印诊断调用计数 | `target-final.log` |
| `run_hdlbits_grhsim DUT=001` | 普通 SV 经共同分图及 GrhSIM 编译执行通过 | `hdlbits.log` |
| `inspect_firrtl_partitions` 六组 | 真实层次分图、预算及最终 SinkSchedule 验证通过 | `inspect-{off,prefer,bytes-off,bytes-prefer,fused,clone}.log` |

复跑例子：

```sh
WOLF_ENV_SOURCED=1 make --no-print-directory test_grhsim_firrtl_nodes test_wolvrix
WOLF_ENV_SOURCED=1 make --no-print-directory test_grhsim_flow SKIP_PY_INSTALL=1 \
  PYTHON=$PWD/.venv/bin/python \
  GRHSIM_FLOW_TEST_WORK=$PWD/ptmp/firrtl-ingest/F09/flow \
  TMPDIR=$PWD/ptmp/firrtl-ingest/F09/tmp \
  CCACHE_DIR=$PWD/ptmp/firrtl-ingest/F09/ccache
WOLF_ENV_SOURCED=1 make --no-print-directory inspect_firrtl_partitions \
  FIRRTL_PARTITION_HINTS=prefer FIRRTL_PARTITION_COST=legacy \
  FIRRTL_PARTITION_FUSE=0 FIRRTL_PARTITION_CLONE=0
```

## 5. 真实 RenameTable 消融

输入为冻结 `ptmp/xs/rtl/rtl/SimTop.fir`，SHA256：

```text
cc46aae1a379d9e62132b76b0702685ba67761c87815067f770b0743d7dc754a
```

模块 RenameTable，整体 CSE 参数固定 gsim，其余默认工作预算。六组的
`*.txt.split.json` 完全相同，SHA256：

```text
c4b7eabe7f25e3bc5f5c1a55acb805daa6da06037e4466b4b4fad7385f68b259
```

所有配置均保留相同 attrs 后切开关，未用删 attrs 伪装 off。每组在分图后
继续执行 simplify、partition-sink，并验证 SinkSchedule；未运行整机。
普通 simplify 后根全部消失，2230 个 inventory source identities 中仍有
2071 个 member fragment identities；roots 缺失只报告，不失败、不补 carrier。
独立整体分析因此没有物理合并，成员仍可被分图使用。

各组共同 nonsink：639 ops、work 1308，提示覆盖 270 ops/work，多成员
170 ops、1060 个关联 key，初始索引 2435 refs、溢出事件 0。最大 leaf/SN
work 均为 128、单 op 超限 0。以下是分图 snapshot，不是 emit 后物理内存。

| hints / cost / 可选项 | leaf | SN | persistent bytes | consumer bytes | split hints | hint score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| off / legacy | 378 | 13 | 2768 | 5044 | 420 | 0 |
| prefer / legacy | 378 | 13 | 2768 | 5071 | 416 | 962 |
| off / bytes | 378 | 109 | 2771 | 6152 | 596 | 0 |
| prefer / bytes | 378 | 109 | 2771 | 6152 | 595 | 417 |
| prefer / legacy / fused | 13 | 13 | 2768 | 5071 | 416 | 962 |
| prefer / legacy / clone | 378 | 13 | 2768 | 5071 | 416 | 962 |

clone 组复制 0 ops、额外 work 0，9 个目的候选因收益/输入可达性代理拒绝。
专项小图另有成功 clone：32-bit NOT，复制 1 op、额外 work 1、无新增激活
来源，独立行为对照通过；不能用这个小图证明实际模块一定能获益。

| 配置 | nonsink pass μs | 进程 wall s | 进程 max RSS KiB |
| --- | ---: | ---: | ---: |
| off / legacy | 49843 | 4.82 | 2002964 |
| prefer / legacy | 55068 | 4.71 | 2002592 |
| off / bytes | 50893 | 5.02 | 2003076 |
| prefer / bytes | 70830 | 4.74 | 2002596 |
| prefer / legacy / fused | 54540 | 4.70 | 2002420 |
| prefer / legacy / clone | 55201 | 4.82 | 2002948 |

这是单次编译器诊断样本，RSS 包含大输入 mmap/解析/IR/序列化，不能归因
于提示索引，也不能用 wall 的小幅波动声称加速。最终 JSON 的 node metadata
序列化增量均为 1604343 bytes；此 census 的去标注副本只用于容量测量，
不能恢复执行。原始报告为 `RenameTable-<hints>-<cost>-f<fuse>-c<clone>.txt`。

提示在共同图上确实可用，但 prefer/legacy 的 consumer bytes 比 off 多
27，bytes 试验增加 SN 和边界代理。提示集合较完整不是性能成功指标。

## 6. 冻结 Queue2 执行计数与边界

Queue2 的相同输入序列每 epoch 750 eval，共 3 个 epoch，所有模式均通过
相同独立队列 scoreboard；诊断计数已开启，未作吞吐计时。

| 模式 | rounds / epoch | compute / epoch | commit / epoch | writes / epoch |
| --- | ---: | ---: | ---: | ---: |
| off / legacy | 916 | 356 | 1287 | 1287 |
| prefer / legacy | 916 | 356 | 1287 | 1287 |
| prefer / bytes | 916 | 551 | 1287 | 1287 |
| prefer / legacy / fused | 916 | 356 | 1287 | 1287 |
| prefer / legacy / clone | 916 | 356 | 1287 | 1287 |

bytes 的 compute 调用上升；三轮相同，不是随机误差或等价证明不足而省略。
F09 证明优化透明性、提示消费与可审计性，没有证明 XiangShan 仿真提速。
默认仍为 off / legacy / unfused；F10 继续整机混合绑定和差分，F11 再做
关闭计数的吞吐、构建 wall/RSS、多次样本与默认策略决策。
