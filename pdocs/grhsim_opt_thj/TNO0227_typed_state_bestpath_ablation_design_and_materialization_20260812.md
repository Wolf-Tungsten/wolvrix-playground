# TNO0227：typed persistent-state 最优路径消融设计与物化

日期：2026-08-12

## 1. 目的与当前边界

[TNO0226](./TNO0226_simpletes_principled_trbs_64valid_completion_20260812.md) 的最终 best
`297a70325057463d96eb062bf71234cc` 在原则化 TRBS 空 control 上取得
`48,074.00 -> 43,300.00 ms`（减少 `4,774.00 ms/9.930524%`）。本阶段按用户指示在
`node032` 上做最优路径的直接消融；在看到 fresh 50k 结果前不修改 Wolvrix 默认，也不启动
SimpleTES。

基线固定为当前研究 pin，而不是用户工作树里的 dirty submodule 状态：

| identity | value |
| --- | --- |
| parent | `52ba7d9edcd713cd0ee3d8a605f1d4aa31b3c730` |
| Wolvrix | `d3ed9dea975bddf01185dde5c548a69241a09de9` |
| source | `lib/emit/grhsim_cpp.cpp` |
| baseline source SHA-256 | `7102ba7fde4dd72e4dc7419f1553b61d555482c49f79984c591d78e85b5239a8` |

headline 只使用 SimTop 50k 的 `Host time spent` walltime；PMU、ELF 和生成代码只作解释与审计。

## 2. 消融分层

本轮采用搜索中已经实际出现、并且可以在同一 pinned baseline 上独立复现的三个累计阶段：

```text
B（当前默认）
  -> S8：field-sensitive typed persistent state，bool state 仍为 byte
  -> SB：上述 state layout + native bool persistent state
  -> SBV（最终 best）：上述两项 + materialized kBool value bucket 使用 bool
```

这样相邻 direct pair 分别回答 state layout、persistent-state native bool、materialized-value native
bool 的边际贡献；另做 `B -> SBV` endpoint 校验总收益。百分比不作可加性假设，因为生成代码布局和
编译器优化存在交互。

| arm | 来源 | candidate digest | patch SHA-256 | materialized source SHA-256 |
| --- | --- | --- | --- | --- |
| `S8` / `typed_state_byte` | checkpoint gen60，node `31d650d391b3490cbdb8024748c3f4b0` | `f53f844e0de9672626bea88c8ba789bd8ed3b4de1ca0992cd115e17e1364f707` | `41fde3c5a653d40a0b6ce87dee299810f551fdedac562fed1d9ed523ff70a10f` | `0de502d84e47bc458e2c3e368dfd41480db934bf2b0acde988ff79d79bf61384` |
| `SB` / `typed_state_native_bool` | checkpoint gen68，node `2525589049e448db9633df499dd04fd1` | `a189837d04c72cd545072b61b491ee4d6a8dd09974110e2547f461f23ad6cf87` | `364421e26eb32559f07e0f5bb1327e6872c5f3bb7efd5110808ad3fd0e036da0` | `26ff41171b4308bbe2f0b70b97cb3551e366c0b7fc28c961f830a5524b42a168` |
| `SBV` / `full_native_bool_values` | checkpoint gen72，node `297a70325057463d96eb062bf71234cc` | `439a769a676c2bc815423273a2aec5be9b6b250cb656984e6380c8c5062422c2` | `d7ec315534865641cd3a3cc2f76ca70cbf77c3c6191ce0688135ca3016a45325` | `88f031189b1b240c2d1f567a60d2c001d9835318094a40abf080ff25002ee164` |

三份输入都为 `default-path`、零 option、只改上述一个 emitter 文件，并通过
SimpleTES `validate-only`。候选文档与 materialization 输出位于
`build/grhsim_typed_state_ablation_20260812/candidates_v1/`；该目录属于实验 artifact，不是
Wolvrix 源码落地。

## 3. 构建与 runtime 协议

baseline 和三个 candidate 在 node032 的隔离 evaluator repo 中 fresh emit/O3 link；三个 candidate
build 使用三个并行 worker、每 worker `GRHSIM_BUILD_JOBS=4`，先全部完成 focused、fixed-ASLR
100/10k 功能 gate 和 artifact identity gate，再开始 walltime。baseline snapshot 与 candidate
snapshot 的 `image`/`nemu` 必须保持 control identity；每次命令先 source
`wolvrix-playground-gsim-calibrate-5/env.sh`。

node032 当时有少量 CI emu 任务，但 whole-CCD quiet gate 会排除正在使用的 CCD；不会凭 load average
手工选择 CPU。正式运行使用 `setarch x86_64 -R`、NUMA first-touch、affinity、PMU 和功能审计。

每个 direct pair 只创建一个 runtime placement：ABBA 先选通过 quiet gate 的 CCD，BAAB 复用同一 CPU、
SMT sibling、whole CCD、NUMA node 和 helper CPU。每组接受四个 control 与四个 candidate sample；
若基础设施污染则整轮作废重试。按时间顺序取第一个完整且 ABBA/BAAB improvement gap `<0.25 pp` 的轮次，
不在多轮中挑收益最大的结果。

预注册 pairs：

```text
B  -> S8
S8 -> SB
SB -> SBV
B  -> SBV
```

每组均记录绝对 walltime、减少的毫秒数、相对百分比、ABBA/BAAB、spread、placement、PMU、
fixed-ASLR/NUMA/affinity/function 审计和所有被作废的 retry。当前设计阶段不预报性能结果。

## 4. 后续裁决

只有相邻 pair 两个 order 同向且在既定噪声线之上，才把该阶段列为可信正向；弱于噪声线的结果记为
中性/弱信号，任何 order 回退都不能因 pooled 平均值为正而保留。最终仍以 `B -> SBV` endpoint 的
端到端 walltime 为总收益口径。消融完成后另建结果文档，不覆盖本设计记录。
