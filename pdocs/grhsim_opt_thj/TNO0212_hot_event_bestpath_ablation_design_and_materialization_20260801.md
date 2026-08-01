# TNO0212 Hot-event best-path ablation design and materialization

## 1. 目标与边界

[TNO0211](./TNO0211_simpletes_post_four_gpt_max_research_completion_20260801.md) 记录的最终
gen28 在 landed four-positive current-default 上取得 `51,376.50→47,473.50 ms`、
`7.596858%` 的搜索内最佳结果。本阶段按用户指示先做直接消融，再实现原则化 gate；此时不修改
Wolvrix 默认、不启动新的 SimpleTES research，也不提前给出落地源码 SHA。

基线继续固定为：

| 项目 | identity |
| --- | --- |
| parent executable pin | `de37459cdd210794fa5d7423e6f32c145cf71261` |
| Wolvrix pin | `fd12d83f5150cc98540ed3e8f2af3b79f8054da0` |
| control generated fingerprint | `d36378e381f03a28723109b14d5dee636e204d141c4992df5675657c6e390cc4` |
| control ELF | `90,873,536 B`，SHA-256 `ba8cd1458a9e31f966b6e63d454173d9338a3d2f68515d3238ff002da2328d21` |

性能 headline 只使用 fixed-ASLR、空闲 CCD 的 SimTop 50k `Host time spent` walltime。

## 2. 为什么同时做两组消融

真实搜索路径为 `baseline→gen3→gen12→gen16→gen28`，但 gen12/gen16/gen28 不只是简单追加一行：
hot enum 曾经从 typed array 移到对象 padding，最终又回到 typed slot 0，并新增 decoded bool。因此仅比较
历史节点会把“表示替换”和“新增机制”混在一起。

本轮同时预注册：

1. **exact search-path**：复现实际 checkpoint 的累计节点，回答搜索每一步带来了多少端到端变化；
2. **final mechanical decomposition**：从 gen28 机械移除 snapshot 或 decoded-bool+snapshot，回答最终
   实现中 remap、decode、snapshot 的直接边际。

所有比较都是相邻 arm 的 direct pair，不把每个 arm 单独放到 baseline 后机械相加。

## 3. 物化 arms

| arm | 来源/含义 | candidate digest | patch SHA-256 |
| --- | --- | --- | --- |
| `B` | landed four-positive native control | control | empty |
| `T` / `typed_gen3` | exact gen3：typed direct event array | `e82119004ac5b505...` | `3dc37a9c395977d5ac9f99a0ed11ddf6010d2b2678667dad32038179637a851e` |
| `H` / `hot_scalar_gen12` | exact gen12：选择最热 event，并放入 near scalar enum | `fc0c47fb7a8bf6e2...` | `9dd628e579c9cf0a68b04abac52051386af282b3a54b62c2c87b7a795443cc1e` |
| `HS` / `enum_snapshot_gen16` | exact gen16：限制为 input event，增加 enum batch snapshot | `9fcbd65c6439face...` | `034725003876832fbef34b969e493fbb0451690c1148050bd1f034b6b75ac77e` |
| `TR` / `typed_hot_remap` | gen28 机械去掉 decoded bool 与 snapshot，只保留 typed storage + hot remap | `f15122a6cf5d36c0...` | `4920ee230a971a3131fb11f0c9638eca08befc6d285dc98c42711911c7d01e9b` |
| `TRB` / `decoded_bool_no_snapshot` | gen28 只机械去掉两个 batch-local snapshot | `8830cb19b85e43df...` | `294ae105fd0ddca78b5d8c0207edaec46f3577ed3a5f18bfecd02072613bff4c` |
| `TRBS` / `final_gen28` | exact final gen28 | `c4f36143dfd56ab7...` | `2dff58bce8cd6f9079037d194fa921866e0fe21a2e39b3102976e51695824f83` |

custom arm 只从 exact gen28 源码做删除式机械变换，不引入 benchmark、option、信号名、固定 ValueId 或
生成文件改动。六个 candidate 都只有 `lib/emit/grhsim_cpp.cpp` 一个文件、`default-path`、零 option，
均通过 `git apply --check` 和 SimpleTES schema-v2 `validate-only`。

materialization report 位于：

`build/grhsim_hot_event_ablation_20260801/candidates_v1/materialization_report.json`

其 SHA-256 为 PENDING，待阶段结果归档时连同 build/runtime artifact 一起固定。

## 4. 预注册 direct pairs

| 组别 | pair | 主要解释 |
| --- | --- | --- |
| search path | `B→T` | typed direct storage |
| search path | `T→H` | dominant event + near scalar enum |
| search path | `H→HS` | input-only restriction + enum batch snapshot；SimTop 最热项本来就是 input clock |
| search path | `HS→TRBS` | scalar enum 表示切换到 typed slot 0 + decoded bool，并保留 snapshot |
| final decomposition | `T→TR` | 最终形态中的 hot-event selection/remap 到 typed slot 0 |
| final decomposition | `TR→TRB` | decoded object bool，不含 batch snapshot |
| final decomposition | `TRB→TRBS` | 只增加 batch-local non-volatile snapshot |
| endpoint | `B→TRBS` | fresh 总端点，校验相邻消融与历史约 `7.58%` 总收益一致 |

相邻 marginal 可能有交互，不承诺可线性相加；endpoint 是总收益的最终闭环。

## 5. Build 与 runtime 协议

六个 candidate 使用隔离 repo 并行 fresh emit/O3 link，最多 `4` 个 build worker、每个 `4` jobs。每个
arm 必须通过 trusted emitter focused、fixed-ASLR 100/10k 功能 gate，且 image/NEMU、build config、
toolchain 与共享 control 身份一致。final ELF 不重复为每个 pair 构建。

每个正式 pair 只创建一个 runtime placement：

1. ABBA 选择 whole-CCD quiet gate 通过的 CPU/CCD；
2. BAAB 必须复用同一 CPU、SMT sibling、CCD、NUMA node 和 helper CPU；
3. 每个样本执行 `setarch x86_64 -R`、pre/continuous quiet、affinity、NUMA、五项 PMU 和功能审计；
4. 任一 order 污染时整轮八样本作废，不拼接半轮；
5. 按时间顺序选择第一个完整且 ABBA/BAAB 改善率 gap `<0.25 pp` 的 pair，不从多轮中挑收益最大者。

绝对 walltime、相对变化、两个 order、spread 与 PMU 都必须记录。当前 parallel build 正在运行，尚无
本轮 fresh binary 或性能结论。

## 6. 后续原则化 gate

消融结束后，旧 `eventEdgeSlotCount >= 256` 将替换为不依赖名字、slot ID 或裸模型规模的静态机会模型。
预定方向是按每个 input event 的 exact-posedge use 和覆盖 supernode 计算保守复用收益，选择净复用机会
最大的 event，并且只有预计省下的重复 predicate work 超过一次分类/清理固定成本时启用。具体公式、
SimTop 绝对计数、旧/新生成身份和 50k 对比将在独立后续 TNO 中记录，不在实现前预报结果。
