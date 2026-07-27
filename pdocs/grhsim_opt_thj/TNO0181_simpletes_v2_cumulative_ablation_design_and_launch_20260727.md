# TNO0181 SimpleTES v2 cumulative ablation design and launch

## 1. 目标与状态

[TNO0180](./TNO0180_simpletes_v2_provider_schema_fix_and_long_research_launch_20260725.md)
启动的 schema-v2 long research 已正常达到 `32/32` 个有效候选。其最终最佳候选由四层机制累计组成：

- `R`：exact-event register cold-layout refinement；
- `W`：在 `R` 已选中的 run 内为 singleton `MemoryWritePort` guard 增加 cold hint；
- `F`：独立的 singleton `MemoryFillPort` cold-hint admission tier；
- `A`：共享 condition 与 exact event 的相邻 `SystemTask + xs_assert_v2` assertion pair 外层 guard。

本阶段不直接把不同时间窗口中的历史 score 相减，而是机械恢复同一最终 checkpoint 中的累计 patch，
重新执行 fresh build、功能门禁和 fixed-ASLR SimTop 50k 配对 walltime。实验已于
`2026-07-27 12:20:29 +0800` 串行启动；本文只归档设计与 launch，不提前写入性能结论或默认决定。

## 2. 固定基线与来源

- parent baseline：`fbe4e1cbbfcf45b52960545377020cb761c3ab25`；
- Wolvrix baseline：`8f6ba14397b0c3d00cb909153af1c6464f4f1ed9`；
- candidate mode：全部为 `default-path`；
- enable options：全部为空；
- patch 文件：全部只修改 `wolvrix/lib/emit/grhsim_cpp.cpp`；
- 权威 checkpoint：
  `SimpleTES/checkpoints/grhsim_simtop_50k/continuation_v2_20260725_090855/2026-07-25/instance-ccad5879/db_state_032443/nodes.json`。

候选由已有 `materialize_ablation.py` 机械提取；脚本只改 hypothesis/evidence 标签以形成 fresh digest，
patch 和 enable options 保持 checkpoint 原值。对应 materializer focused test 为 `1/1 PASS`，四臂
`--validate-only` 均确认 schema 合法、`default-path`、零 option、单文件 patch。

## 3. 累计消融矩阵

每个 candidate 都由 trusted evaluator 自动与相同 current-default baseline `B` 配对，因此实际矩阵为
`B/R`、`B/RW`、`B/RWF`、`B/RWFA`。边际贡献按同一轮 fresh 结果中的累计 effect 差计算，不直接比较
不同组的 candidate 绝对 walltime。

| arm | checkpoint | 原 node | fresh digest | 唯一新增机制 |
| --- | ---: | --- | --- | --- |
| `R` | gen 7 | `65e51ec2...` | `df753aaf6c711a04...` | register selector/group cold-layout refinement |
| `RW` | gen 16 | `98349663...` | `591133ddd3439962...` | `W`：已选 run 内 singleton memory-write hint |
| `RWF` | gen 22 | `9b8e8a7f...` | `c1d2e073fde65c5e...` | `F`：`>=128` singleton memory-fill 独立 tier |
| `RWFA` | gen 40 | `215a21e2...` | `676ee3646b6d54f9...` | `A`：assertion side-effect pair 外层 guard |

依赖边界如下：

- `W` 不参与 run admission，依赖 `R` 选出的 cold run，因此不定义无 `R` 的 `W-only` arm；
- `F` 具有独立 admission，语义上不依赖 `R/W`，但累计源码复用 `R` 的 known-nonzero helper；
- `A` 与 commit 侧的 `R/W/F` 独立；gen 40 的 commit hunks 与 gen 22 内容相同，只新增 assertion
  compute-path hunks；
- `R` 本身是有意的 register-policy 组合，包含 `1024 -> 256` singleton threshold、
  `>=2048` eligible-write admission、`<=2048` group cap 和 known-nonzero 排除。本轮先裁决顶层
  `R/W/F/A`；若需解释 `R` 内部，再另立二级消融。

## 4. 正式测试协议

四臂严格串行，禁止候选构建或 emu 互相并发。复用 SimpleTES schema-v2 evaluator 的既有 control
cache，但每次都重新验证 parent/Wolvrix pin、生成输入 fingerprint、control artifact 和 toolchain；候选
仍执行 fresh clone、apply、emit 和 O3 build。

每臂自动执行：

1. focused tests；
2. fixed-ASLR 100/10k 功能门禁；
3. 动态选择完整空闲 CCD；
4. 单一物理核、SMT sibling、NUMA first-touch、PMU 与运行期 peer monitor 审计；
5. `ABBA` SimTop 50k；只有 ABBA walltime 正向时才 promotion 到独立 `BAAB`；
6. pooled headline 只使用日志中唯一的 `Host time spent`，同时记录绝对 ms 与相对变化。

运行参数为 `GRHSIM_BUILD_JOBS=4`、`GRHSIM_INFRA_RETRIES=8`。retryable quiet-CCD failure 不计为
候选失败，也不混入 accepted samples。每个正式样本必须核对 `personality=00040000`，即 ASLR 已关闭。

## 5. 裁决规则与补测条件

- 顶层结果同时报告各 arm 相对 baseline 的绝对/相对收益，以及固定顺序下 `R`、`W`、`F`、`A`
  的边际百分点；
- 跨组 candidate 的绝对时间不直接作因果比较，必须使用各自 paired control 归一化；
- 对两个独立累计 arm 的 effect 差，初筛门槛取
  `max(1%, 前臂 paired-control spread%, 后臂 paired-control spread%)`；低于该值时暂判 noise-scale，
  不据此默认采用。若随后完成相邻两臂直接配对，则改用 direct-pair control arm 的 pooled spread；
- 特别地，历史 `F` 边际约为 `0.5 pp`。若 fresh 累计结果仍落在噪声附近，将补 `RW/RWF`
  邻臂直接配对或独立重复，而不把小差值写成确定收益；
- 本 launch 不修改 Wolvrix 代码或默认值。最终结果、保留/停止结论和落地建议另写后续 TNO。
