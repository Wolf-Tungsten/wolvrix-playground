# SimpleTES extended best-path ablation materialization and launch

## 1. 阶段结论

针对 extended post-RWA 搜索最终 best，已经从 exact checkpoint
`db_state_235014` 机械恢复六个 zero-option `default-path` 累计输入，并进一步构造最终
`gen150` 加六个严格 `final-minus-one` arm；七份 candidate 全部通过 SimpleTES
`validate-only`。所有 arm 都只修改
`wolvrix/lib/emit/grhsim_cpp.cpp`，基线固定为当前仓库已经默认落地的 RWA：parent
`d31118bea0feb563ad09476e1419f0f15aaf574f`、Wolvrix
`16a9f493687a21a5428f1e1327a69834ea60c9f5`。

搜索 DAG 的 `parent_ids` 包含 inspiration/merge 关系，不能直接当作单变量性能链。本轮因此把每个
checkpoint full patch 分别应用到同一 pinned baseline，比较 materialized source，得到如下语义顺序：

```text
RWA baseline
  -> standalone assertion/SystemTask cold hints
  -> wide helper always_inline
  -> constant MemoryRead proof + redundant zero elimination
  -> shift/index OOB cold hints
  -> residual dynamic MemoryRead OOB cold hints
  -> targeted physical zero-tail
```

五个机制可从 final source 直接 reverse-apply。常量 MemoryRead 与后续 residual MemoryRead 修改同一段
emitter；该 arm 因此在移除常量 row proof/redundant-zero 的同时，把后续 residual-OOB `unlikely`
重基到恢复后的结构，并证明删除后再加入仍逐字节恢复 final。

最初启动的一次 `B→gen5` 累计臂在澄清消融口径后人工停止；停止时仍处于生成阶段，没有产出 ELF、
功能结果或 50k sample，不进入结论。七个正式 leave-one-out arm 已于 `2026-07-31` 在互相隔离的
candidate repo 中以 `7` 路、每路 `4` build jobs 并行启动。首次 parallel clone 预检发现普通
evaluator helper 会在每个 Git 命令前 source shared control `env.sh`，导致七路同时刷新
`control/.venv`；该轮在 emit 前立即停止。修正版 clone 使用 worker-private no-op Git 环境，完整 clone
后才 source 各自 candidate `env.sh`；进程审计确认 v4 七路只访问各自 `.venv`。每臂仍执行
`xs_diff_clean`、fresh
emit/O3 link、focused 与 100/10k gate；并行构建全部结束前不启动任何 walltime 测量。本文只记录
物化、协议和 launch，不提前写性能或默认保留结论。

## 2. 输入 checkpoint 与历史总收益

输入状态为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
k3_rwa_grounded_fresh_20260728_032742/2026-07-28/
instance-7291c6c2/db_state_235014
```

最终 gen 150 节点为 `232ee362871c4adcb5bf559bd931296d`，搜索内同批绝对 walltime 为
control `52,628.50 ms`、candidate `50,420.25 ms`，减少
`2,208.25 ms/4.195920%`。这个数字是完整候选相对 RWA 的历史总收益，不是其中任一机制的独立
边际值，也不是本轮消融结果。

六个原始节点如下；历史 walltime 仅用于定位输入，不能跨 session 相减来归因：

| gen | node | 历史 control→candidate / ms | 历史总收益 |
| ---: | --- | ---: | ---: |
| `5` | `7ef38547928347349e4b388a24d0ded1` | `53,831.50→53,266.50` | `565.00 ms/1.049571%` |
| `14` | `b227fe4eafaf46189a9d82c7da280db0` | `54,304.75→53,367.25` | `937.50 ms/1.726368%` |
| `18` | `baea6aedba6e4f1b8e669e30840c712b` | `53,599.50→51,791.75` | `1,807.75 ms/3.372699%` |
| `29` | `f6ab710e65034a3db2bdd9a097242af2` | `53,742.50→51,534.50` | `2,208.00 ms/4.108480%` |
| `68` | `915bd45c9ab84ddcb1b39fdd4a385426` | `54,745.25→52,488.00` | `2,257.25 ms/4.123189%` |
| `150` | `232ee362871c4adcb5bf559bd931296d` | `52,628.50→50,420.25` | `2,208.25 ms/4.195920%` |

## 3. Exact cumulative 输入身份

物化使用 production bench 自带的 `materialize_ablation.py --gen-id`。每份输出只在
hypothesis/evidence 中追加 fresh-replication provenance，源码 patch 与 enable options 保持 exact；
随后使用 evaluator parser/patch validator 独立复核 mode、option 和唯一文件范围。

| arm | fresh candidate digest | patch SHA-256 | candidate 文档 SHA-256 |
| --- | --- | --- | --- |
| gen 5 cold assertion | `39414f197852e15823b2b2c8883913cdb20ed7bd15d75dd52d5de4b5c996ff23` | `5322c7e34e044e057a2b568ae4472451eebafedc35cc61f86d74fc6b0dcde316` | `2dd78f770c2c7cce0fde7ebefeea13d22e9f951bf21a181a49b62b2ef51fdff2` |
| gen 14 inline helpers | `ccd70137a5819a76a2194b94da11a7d0b2e2c194ba90fd9b7f91d07b829f3c8b` | `ade8ebd700fa48684bed2f714f432a57914c8937de59c6ff60052e993ebb51b5` | `af99d9b138bf315efb03084b87b34ac248a0cf56a9e958e0ff60cd5d796b6129` |
| gen 18 constant MemoryRead | `1d2014148f2b62c1e5b4299bab7726f05b39836a71f52a68000edd73aae93125` | `253589953394891a88ed20fbf8a48a500bf70629ab0d926fa9bace58054866ec` | `83d31eb324daf1b89d67156d07a90d0f84a6a8e02a7f14ed7558f9a6990d01be` |
| gen 29 shift/index | `caf8435170202ea65250c306e73b1c1cf8da2c680db5fd5b0bb289bf09a15fbe` | `6311c22786ebd5a1bc7547cec3e123a8a8d7e9e5e3b8a488ece68d07d4e1dd99` | `f0a4b4e3ebf7d33b8a32a5dded1298171631da32691805aa48256826698cfceb` |
| gen 68 residual MemoryRead | `726d3f2c787125d927d1838713ef4aea8867a66ff3b0950df91f1ebf72336f0e` | `641afa44dca727d9b0f6b8d16344c23bdd7ac9432016f91fd13f309da1a69809` | `e2368d334f4de3411a8a8b68c7ac569f39f696ce94b0048ec57f8610ce72ab7e` |
| gen 150 physical zero-tail | `1afdcb97fc009d6a3e656792eeb6f66751952cc2ac6506051cf050348d95efbb` | `5bfbaf57104d75a2efc5c132269a3190e3c6323db4c00c0155f3b371e972bfa3` | `235c0c2f3839a8cf5a025da3486741592c7f935de4a43deef14b486996bb33af` |

所有 arm 的 `candidate_mode=default-path`、`enable_options={}`，没有借用 SimTop-only option。

## 4. 机械相邻差分

Pinned RWA baseline 的 `grhsim_cpp.cpp` SHA-256 为
`3739547b0c88676a0c0a4ee9c544f60df01754e2d13a18b81e821d11a6c45e84`。把每份 full patch
应用到该 baseline 后，得到以下源码身份和相邻机械差分：

| step | materialized source SHA-256 | 相邻 diff | 唯一新增语义 |
| --- | --- | ---: | --- |
| `B→gen5` | `32ddf1cc4e155434dcb1a419103dfbe7dfb4f89bdeb433cf968d34b5874a1ee1` | `+15/-11`, `2` hunks | standalone SystemTask 与 standalone `xs_assert_v2` 冷分支 `unlikely` |
| `gen5→gen14` | `a4a4439796b872f5bb1c3f26fdc84a33f020d70e7baffa9052c44bf6ad25038e` | `+25/-18`, `18` hunks | 小/宽值 runtime helper `GRHSIM_ALWAYS_INLINE` |
| `gen14→gen18` | `dcfc4af0ee087ab29f5ef894a29da0e3246d0c9e4af7bfd61fd17eaf0fb455f8` | `+49/-59`, `3` hunks | 常量 MemoryRead row 证明并消除 always-in-range 临时清零 |
| `gen18→gen29` | `a42690f9f85300a7f8311e07874329a8f02ae0e7aa870af5474e2f3729fdfb82` | `+5/-5`, `4` hunks | shift/index 越界冷分支 `unlikely` |
| `gen29→gen68` | `55c4d5ffab3cdd51b949a404784141c638e829867da664dd46aaf83be4027862` | `+6/-6`, `4` hunks | 剩余动态 MemoryRead 越界冷分支 `unlikely` |
| `gen68→gen150` | `e4cd8e0c23d4c15d17e999b12f2ccf4d3fe2585a0cb66615be87bb7903b97756` | `+32/-7`, `10` hunks | targeted small-memory physical zero-tail |

相邻差分均由完整 materialized source 求得，不依赖搜索节点之间可能非线性的 `parent_ids`。

## 5. Strict final-minus-one materialization

最终 `gen150` source SHA-256 为
`e4cd8e0c23d4c15d17e999b12f2ccf4d3fe2585a0cb66615be87bb7903b97756`。每个消融 arm 都从这份
final source 只删除上一节定义的一段语义增量，其余机制保持存在；再把同一增量加入消融 source，必须
逐字节恢复 final。

| 删除机制 | minus-one digest | minus-one source SHA-256 | 删除方法 | 删除增量 SHA-256 |
| --- | --- | --- | --- | --- |
| cold assertion/SystemTask | `9bbe43f2f8966b8af8422010c30cffcd2fccae74cdf0003177ba5e2a780a947c` | `bf615beda90247696fa62b8e09a81522c71d22fe76df243a6fe6d9df0b34030f` | direct reverse | `7dbe4d90ce1cb49c589b8b28f885986b8eb744cc9999a8ac8a0285014cec8047` |
| inline helpers | `e4776c540c324a387d44ea57ba01ee864596afd9357040ad766cf6e548dd2229` | `d8b4f057942320eebc84dff645aa9903571f5313c23acd7e67eaed97f773e47b` | direct reverse | `4170111c058cef28cb46385b8aef67e4b770becc229262799f21f905591b1345` |
| constant MemoryRead | `cdb4f017a7b1289aaf14b2f2c618bd9af76dccd8eff8a55b927c9df8c35ba083` | `4070e9dfd70214341f8f1eeb77c943ca199d506fd141e1e16776f5a4f0809f57` | dependency-aware residual-hint rebase | `1894640b2c2ae27787f16fdf17680c3d1a94ec654037cf7eebf4a27847e1acfb` |
| shift/index OOB | `6e6571d8fc37bdcd7791def553e3ec910b1a5a44e351e798b8cab0e6c0ec9770` | `269898d47847eb5b46ce7881850cb049c62482ceb17215e1552a0c35cd3f4197` | direct reverse | `0e9af5156b47f21d049067576400f1663715f750189f13366436c88d00b45811` |
| residual MemoryRead OOB | `e48e6706a4d72e5c08b40e5407059e99a6890841dbda10a93641203734069632` | `4d6310f01a3316daf29958b9441a1f6c56b1774f3156b4cff98b29e2eba8f97e` | direct reverse | `c3f939daeea2958be0c59782212067d2180d23d70c4be37040be09f998602b49` |
| physical zero-tail | `ec4d0d1deec2e66c75116b343058e1f7e41c99bdd81583ccce28ba74e3115934` | `55c4d5ffab3cdd51b949a404784141c638e829867da664dd46aaf83be4027862` | direct reverse | `28e067794a5350970a18005e8a537252e99021a0bc1426d03aeba808785eb548` |

六项的 remove/re-add closure 均为 `true`；final 与所有 minus-one 仍是 default-path、零 option、唯一源文件。

## 6. Parallel fresh build 与正式消融协议

每个 arm 执行：

1. 七个互相隔离的 pinned clone，`xs_diff_clean` 后按仓库默认生成配置 fresh emit/O3 link；
2. trusted Wolvrix focused tests；
3. fixed-ASLR 100-cycle 与 10k-cycle SimTop 功能门禁；
4. 固化 candidate proof、generated/build-config/toolchain fingerprint、ELF/image/NEMU SHA-256；
5. 只在上述门禁通过后进入 50k walltime。

机器有 `1.0 TiB` RAM、`384` 个逻辑 CPU；launch 时 available memory 为 `934 GiB`。七臂的顶层
make/`XS_VM_BUILD_JOBS` 各为 `4`；generated-model 子 make 按现有默认使用 `-j64`。各臂不共享可写
repo/build 目录，只共享只读 pinned control 身份与 generation inputs。性能阶段必须等所有并行
build/gate 进程退出后再串行开始。

正式消融以 final 为统一 candidate，使用六个 leave-one-out direct pair：

```text
(final−cold_assert)       ↔ final
(final−inline_helpers)    ↔ final
(final−constant_memread)  ↔ final
(final−shift_index)       ↔ final
(final−residual_memread)  ↔ final
(final−physical_zero_tail)↔ final
```

每个 pair 从同一轮 fresh artifact snapshot 直接成对运行 `ABBA + BAAB`，共四个 control 和四个
candidate accepted sample。runtime 动态选择通过 whole-CCD quiet gate 的 CPU，固定 CPU/CCD、NUMA
first-touch，使用 `setarch x86_64 -R` 关闭 ASLR，并审计 process affinity、personality、PMU、NUMA、
功能签名与唯一 `Host time spent`。headline 只取 50k walltime 算术均值；同时记录绝对 ms、相对百分比、
两个 order 方向、spread 和 PMU。即使 ABBA 表面负向，本轮也继续 BAAB，以避免对消融归因做单边筛选。

每组把 `final−X` 作为 control、final 作为 candidate；正的 `(control−candidate)/control` 才表示 X 在最终
上下文中有收益。final ELF 在六组间复用，不为每组重复 build。结果分类在看到正式 walltime 前固定为：
两个 order 都正向且 pooled 改善不低于 `max(1%, pooled control spread / control mean)`，才记为可信正向；
双 order 正向但低于该线只记为弱信号；任一 order 反向记为方向不一致/noise，不能据 pooled 表面正值归因。

## 7. 保留边界

本阶段不修改 Wolvrix 默认源码，不启动新的 auto research，也不根据搜索内历史 score 决定保留。
只有 fresh final-minus-one pair 的端到端 50k walltime 给出稳定正向信号，才把对应机制列为后续 landing/default
候选；近噪声、双 order 反向或回退的机制不因 PMU 或静态计数好看而保留。

## 8. 增量勘误：跨 order 的 CCD 身份

本页第 6 节所述 launch 协议在首版 `run_pair.py` 实现中只保证单个 ABBA 或 BAAB 组内固定 CPU/CCD，
没有保证两个 order 共用同一个 `GrhSimRuntime` placement。首个 cold assertion pair 的 ABBA 实际使用
node1 CCD `152-159,344-351`、CPU `152/344`，BAAB 则使用 node0 CCD
`64-71,256-263`、CPU `64/256`。该轮 pooled walltime 为
`52,119.25→51,475.75 ms`，表面减少 `643.50 ms/1.234669%`，但跨 CCD 的绝对性能与缓存状态
不可比，因此只保留为诊断数据，不进入正式消融。

同一旧 runner 的 inline pair 碰巧两种 order 都落在 node0 CCD `56-63,248-255`，测得
`52,096.25→51,630.25 ms`、减少 `466.00 ms/0.894498%`；但实现并没有跨 order identity
断言，也一并由后续正式协议取代。旧运行在 constant MemoryRead 尚未形成完整结果时停止。

修正版 `run_pair_sameccd.py` 对每个完整 pair 只创建一个 runtime；ABBA 选定 placement 后，BAAB
必须复用完全相同的 CPU、SMT sibling、whole CCD、NUMA node 和 helper CPU。若 BAAB 污染，则同一尝试
中已经有效的 ABBA 也整体作废，重新执行完整八样本 pair。正式结果、追加的 order-gap 一致性筛选和
保留结论见 [TNO0205](./TNO0205_simpletes_extended_bestpath_direct_ablation_result_20260731.md)。
