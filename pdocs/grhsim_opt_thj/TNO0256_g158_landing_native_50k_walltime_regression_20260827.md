# TNO0256：g158 native landing SimTop 50k walltime 回归

日期：2026-08-27

## 1. 阶段结论

冻结的 g158 已落入 Wolvrix 通用 GrhSIM emitter，并在默认生成路径生效。基于
同一 RTL、输入、编译参数和 toolchain 的 fresh immutable 快照，node030 上完成
固定 CCD 的 ABBA+BAAB SimTop 50k 回归。正式 headline 只取 host walltime：

| 版本 | pooled walltime | 绝对变化 | 相对变化 |
| --- | ---: | ---: | ---: |
| baseline | `43,702.00 ms` | - | - |
| g158 landed | `42,959.00 ms` | `-743.00 ms` | `+1.700151%` |

ABBA 为 `43,575.50 -> 42,885.50 ms`（`+1.583459%`），BAAB 为
`43,828.50 -> 43,032.50 ms`（`+1.816170%`）；order gap 为
`0.232711 percentage points`，严格小于预注册的 `0.25 pp`，且两个 order
方向一致。因此 g158 KEEP，并维持为 Wolvrix 默认选项。该结果是端到端
walltime 收益，不是只看生成文件大小或单独 PMU 事件的推断。

## 2. 版本和产物身份

| 项目 | baseline | g158 landed |
| --- | --- | --- |
| parent executable snapshot | `42c43ef6742be64c79c2bd3bb8c3de092f93ac16` | `6e2436e37286264e9f03f114d14d81bae4ed313b` |
| Wolvrix | `cedf61048d3b8873702e6db1120a386ecbf474f5` | `054c6a7c09b007a12eb36fdb49fcb659a1bfc590` |
| generated fingerprint | `8e45aad743534def83267cfd8f97148e16c0fc4c286d51f635751324203aabe9` | `0931d22011907b96bb3f3019da23eec6a6df0689b503c7766f54262c22a55da6` |
| `emu` bytes | `83,705,968` | `83,517,552` |
| `emu` SHA-256 | `4d2fb3e07820637432c958d8ea7c221cf78827b7a51b02e3d38c674eb3a05b8b` | `d087bcf7e5203c0f4aa9fd4e906521365b2ab3db07cd6ccb377eb73a5135d6b7` |

两边的 generation input fingerprint 均为
`1e00edec4bd3d6dc449a4970e35399a0a14ac7f484b728885b0f49cf8546c5d2`，冻结 RTL
fingerprint 均为
`bcbc10f8f0f0c7dbd466ba5b1e4c2c70913097a2d12c5572ede55deed4643738`。构建和
产物的完整 provenance 位于
`build/grhsim_g158_landing_20260827/{build_summary.json,input_identity.json,snapshots/}`；
fresh build/function gate 详见 TNO0255。

## 3. 测试协议和环境

- 主机：`node030.bosccluster.com`，AMD EPYC 9684X 96-Core Processor，384
  logical CPUs，2 NUMA nodes；kernel `6.8.0-111-generic`。
- 选中的固定 placement：CCD `node1:128-135,320-327`，target CPU `129`，
  sibling `321`，helper CPU `0`，NUMA node `1`。ABBA 和 BAAB 复用完全相同
  的 CCD/target/sibling/helper。
- 每个 order 为四个样本（两份 control、两份 candidate），顺序为 ABBA 和
  BAAB；使用同一 pair lock、NUMA first-touch、affinity、PMU 和功能审计。
- 系统 ASLR 观测值为 `2`，每个 workload 命令均通过
  `setarch x86_64 -R`；八个正式样本的 process personality 均为
  `00040000`。八个样本的 continuous whole-CCD、NUMA、PMU、affinity 和
  functional gates 全部通过。

正式样本的绝对 walltime 如下：

| order | control 样本（ms） | candidate 样本（ms） | order mean 变化 |
| --- | --- | --- | ---: |
| ABBA | `43,519`, `43,632` | `42,874`, `42,897` | `+1.583459%` |
| BAAB | `43,898`, `43,759` | `42,909`, `43,156` | `+1.816170%` |

选中 pair 的合并 control mean 为 `43,702.00 ms`，candidate mean 为
`42,959.00 ms`。结果和全部审计日志保存在
`build/grhsim_g158_landing_20260827/runtime_node030_dynamic_v1/`；选中结果的
JSON SHA-256 为 `b29c133a6355d5f72e6acba72c363689c10772ed961396abecfa762ea88f9cec`，
summary SHA-256 为
`6114af0831c0bfaa80f353055823659138d22107a806b26ee361069de5d0f07f`。

## 4. 重试和采纳规则

runner 严格采用“第一个完整、同 CCD、order gap `<0.25 pp` 的 pair”规则。
前面三组完整 pair 均保留在 summary，但不冒充正式结果：

| round | control -> candidate pooled (ms) | 变化 | gap | 判定 |
| ---: | ---: | ---: | ---: | --- |
| 1 | `42,982.00 -> 42,550.25` | `+1.004490%` | `2.601897 pp` | 拒绝，方向不一致 |
| 2 | `43,422.00 -> 42,865.75` | `+1.281033%` | `1.481381 pp` | 拒绝 |
| 3 | `42,531.75 -> 42,221.50` | `+0.729455%` | `1.307829 pp` | 拒绝 |
| 4 | `43,702.00 -> 42,959.00` | `+1.700151%` | `0.232711 pp` | 采纳 |

另有 6 次 ABBA 在 workload 期间触发 external-load contamination（例如
mean idle 低于 `98%`、min idle 低于 `95%` 或 sibling 低于 `98%`），均没有
产生 workload 样本，按 retryable infrastructure 处理，未进入均值。该处理
确保节点负载不会被错误归因给 g158。

## 5. PMU 和功能交叉检查

选中 pair 的八个样本均通过功能输出、terminal PC、guest cycle、ASLR、NUMA
local-page、perf scheduling、context-switch 和 CPU migration 审计。合并 PMU
均值（candidate 相对 control）为：cycles `-1.552235%`、instructions
`-0.317681%`、frontend no-ops `-1.017119%`、cmask frontend no-ops
`-1.303777%`、backend stalls `-10.784625%`。这些是支持 walltime 结果的
诊断信号，最终保留门禁仍以端到端 walltime 为准。

实现本身只改变 `state_logic_storage_t` 的物理声明顺序：基于最终 schedule 的
普通 state 引用 demand、phase/supernode signature、demand class 和 scalar
physical group 排序；不改变字段名/type/index、schedule、guard、event 或
materialized value，不读取 SimTop/benchmark 名称，也不依赖 `targeted-direct`。

## 6. SimpleTES 后续可用性

SimpleTES 已在独立提交
`d1b689608751faf757ffd7c3eafc322f5d4e37eb` 将 bench pin 到 parent
`6e2436e`/Wolvrix `054c6a7`，并保留 g158 seed/instruction。bench focused
测试为 `82 passed`，`evaluator.py --validate-only` 和 `launcher.py --dry-run`
均通过；旧 pin 会 fail-close。本阶段没有启动新的 research，因此后续
SimpleTES 可以从这个默认 landed baseline 继续探索。

## 7. 可复核入口

- [TNO0254：实现阶段](./TNO0254_g158_wolvrix_landing_implementation_checkpoint_20260827.md)
- [TNO0255：fresh build/function regression](./TNO0255_g158_fresh_build_and_function_regression_20260827.md)
- `build/grhsim_g158_landing_20260827/runtime_node030_dynamic_v1/summary.json`
- `build/grhsim_g158_landing_20260827/runtime_node030_dynamic_v1/round-4/result.json`

