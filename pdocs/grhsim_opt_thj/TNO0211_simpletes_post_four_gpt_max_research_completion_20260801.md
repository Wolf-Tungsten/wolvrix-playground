# TNO0211 SimpleTES post-four GPT max research completion

## 1. 结论

[TNO0209](./TNO0209_simpletes_post_four_gpt_max_fresh_launch_20260731.md) 启动的
post-four fresh auto research 已于 `2026-08-01 11:12:14 +08:00` 正常结束。instance
`73ee9786` 达到 `32/32` generated valid 上限后，由 scheduler 正常停止；旧 launcher/main
PID 已不存在，当前没有该实例的 generation/evaluation worker。

本轮最重要的新结果是 dominant input-event edge 表示优化。当前最佳 gen28 的正式 SimTop 50k
`Host time spent` 为：

| 指标 | control | candidate | 变化 |
| --- | ---: | ---: | ---: |
| walltime | `51,376.50 ms` | `47,473.50 ms` | 减少 `3,903.00 ms`，改善 `7.596858%` |
| SimpleTES combined score | - | `1.082214287971184` | control/candidate 比值，不应写成 walltime 改善 `8.2214%` |

该结果来自关闭地址随机化、空闲 CCD、同一 order 内固定同一 CCD 的 ABBA + BAAB 共 8 个
accepted 样本；两个 order 的改善率只差 `0.008800` 个百分点。功能、PMU、affinity、ASLR、
NUMA locality 审计全部通过。

但是，这仍是 SimpleTES checkpoint 中的研究候选，不是已经落地的 Wolvrix 代码。本阶段没有修改
Wolvrix 默认、没有提取落地 patch，也没有启动下一轮 research。后续仍需按默认 C++/Python 生成路径
完成直接消融、落地回归和 fresh 50k 复现后，才能决定通用默认。

## 2. 结束台账与固定身份

最终 checkpoint：

`SimpleTES/checkpoints/grhsim_simtop_50k/four_positive_gpt56sol_max_fresh_20260731_122641_retry1/2026-07-31/instance-73ee9786/db_state_111214`

从正式 main 启动到最终 checkpoint 约 `22 h 41 min`。最终状态为：

| 项目 | 数值 |
| --- | ---: |
| generation attempts | `44` |
| completed evaluations | `37` |
| initial control nodes | `1` |
| generated valid candidates | `32/32` |
| generated invalid candidates | `4` |
| generation failures | `5` |
| shutdown-time generation cancellations | `2` |
| evaluation failures / rejects | `0 / 0` |
| best node | `f3d4487061434246b8b8eb367f9bfe9b` |
| best gen | `28` |

`37` 个完成 evaluation 的节点正好是 `1` 个 initial control、`32` 个 valid candidate 和 `4` 个
apply-invalid candidate。最后两个 generation cancellation 发生在 valid 上限已经达到、scheduler
停止剩余 worker 时，不是异常丢失的 evaluation。

| 固定项 | 值 |
| --- | --- |
| model / effort | `gpt-5.6-sol / max` |
| config / auth | `~/.codex/config.thj.toml` / `~/.codex/auth.thj.json` |
| proposal / valid budget | `64 / 32` |
| generation / evaluation workers | `4 / 1` |
| parent pin | `de37459cdd210794fa5d7423e6f32c145cf71261` |
| Wolvrix pin | `fd12d83f5150cc98540ed3e8f2af3b79f8054da0` |
| control generated fingerprint | `d36378e381f03a28723109b14d5dee636e204d141c4992df5675657c6e390cc4` |

最终关键文件 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `metadata.json` | `98e063925bdeb2e74fbfabae2505cbc46a2b265cb082e288ae1e7d1d524d7271` |
| `nodes.json` | `1da28ae2fce6b144f5c7b5ac5c019c91ec5f26c5158cdb12ab62dc99d8f3df0a` |
| `failure.json` | `c6b246056a856064135d567593aa20d77707e80332bd6a9c084021e90d4e23d9` |
| `best_program.txt` | `1d1cb27744a5a6e1eb0fc09556adc24c7d64e02846683912f03808501fc31613` |
| `config.json` | `b2d6988a3129223d4baab164577d161a97074b423d99a67be6a84a70402e7a4b` |

## 3. 最佳候选的正式 50k 结果

### 3.1 双 order 绝对数值

| order | CPU / NUMA | control 样本 | candidate 样本 | control mean | candidate mean | 减少 | 改善 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| ABBA | `40 / node0` | `51,385 / 51,467 ms` | `47,586 / 47,457 ms` | `51,426.00 ms` | `47,521.50 ms` | `3,904.50 ms` | `7.592463%` |
| BAAB | `136 / node1` | `51,337 / 51,317 ms` | `47,455 / 47,396 ms` | `51,327.00 ms` | `47,425.50 ms` | `3,901.50 ms` | `7.601262%` |
| pooled | 两组各自固定 CCD | 4 samples | 4 samples | `51,376.50 ms` | `47,473.50 ms` | `3,903.00 ms` | `7.596858%` |

ABBA control spread 为 `82 ms`，BAAB control spread 为 `20 ms`，全局 control range 为
`150 ms / 0.291962%`；candidate 全局 range 为 `190 ms`。两个 order 都正向，order gap
`0.008800 pp`，显著低于此前约定的 `0.25 pp` 复测线。

8 个样本均满足：

- 同一 order 内固定同一 CCD/CPU，目标 CPU 与 SMT sibling 通过 quiet gate；
- `personality=00040000`，确认关闭地址随机化；
- affinity、resolved executable、功能 signature、guest cycle、terminal PC 全部通过；
- 五项 PMU 与 task-clock audit 通过，无 CPU migration；
- binary 与 NEMU 的 NUMA local ratio 均满足 gate，其中 binary 为 `1.0`。

本轮全部 `33` 个 valid 节点（含 initial control）共接受 `220` 个 50k 样本，即 `110` 个 control
和 `110` 个 candidate；这些 accepted 样本的功能、PMU、affinity、ASLR、NUMA 审计失败数全部为
`0`，覆盖 NUMA node 0/1 与 18 个测量 CPU。

### 3.2 候选身份

| 项目 | 值 |
| --- | --- |
| candidate mode | `default-path` |
| modified files | `1`，仅 `lib/emit/grhsim_cpp.cpp` |
| enable options | `[]`，数量 `0` |
| candidate digest | `c4f36143dfd56ab7ac493a5e1ea587acf55db4234887661779dee5829c7585a0` |
| candidate generated fingerprint | `9eeec63950179e4d...` |
| exact patch SHA-256 | `2dff58bce8cd6f9079037d194fa921866e0fe21a2e39b3102976e51695824f83` |
| attempt ID | `01785530346633300608-734917-1400e0ebec4e4884b80b67e5e01b7381` |
| candidate proof ID | `dd4343a176794eebb161adf283d9fe53` |
| candidate proof SHA-256 | `071b37b220eb7a9cfb88585c18873eb7685c2aa7e241ecb5cc157dd0ea148204` |

control ELF 为 `90,873,536 B`、SHA-256 `ba8cd145...`；candidate ELF 为 `91,094,720 B`、
SHA-256 `319fce71...`。candidate 增加 `221,184 B / 0.243398%`，因此结果不是由缩小 binary
取得。

## 4. 新优化机制

最佳候选针对 event-edge 表示和 dominant input event，核心机制为：

1. 仅对 event-edge slot 数不少于 `256` 的大模型启用候选路径；把已知 slot 的存储从 byte arena +
   `reinterpret_cast` pointer 改成有类型的 `std::array<grhsim_event_edge_kind, N>`。
2. 在 emitter 中统计 event operand 使用次数，选择最常用的 input event，并把它稳定映射到 slot 0。
3. 保留 slot 0 的完整 enum 供 negedge/general 检查和连续 event 扫描使用，同时在已有对象 alignment
   padding 中增加 `hot_event_posedge_` bool，在每次 input event 分类时一次性解码。
4. 只把该 hot event 的 exact-posedge leaf 替换为 bool；negedge、无指定 edge 和其他 event 继续使用
   完整 enum，未改变操作、guard、SystemTask/DPIC 或调度顺序。
5. 每个 schedule/fullpass batch 入口再取得 non-volatile const local snapshot，使编译器可以跨可能 alias
   simulator object 的 SystemTask/DPIC call 保留该 predicate，而不反复读取对象成员。
6. round clear 与 init 同时清 enum/bool；候选假设小于阈值的模型保持生成结果不变，这一点落地时仍需
   用 focused identity 回归正式验证。

候选引用的静态证据显示，归档 SimTop 生成代码共有 `15,217` 个静态 event slot 引用；schedule 中
有 `14,803` 个，其中 slot 0 占 `13,804 / 93.251368%`，又由 `13,803` 个 posedge 与 `1` 个
negedge 组成。对 landed control ELF 的 symbol-bounded disassembly 找到 `13,769` 次 event-pointer
member load，其中 `13,646 / 99.106689%` 位于 compute batch。优化因此瞄准的是一个高度集中的
重复 predicate/alias dependency，而不是泛化改变所有 event 语义。

## 5. 最优路线如何形成

| 节点 | 增量机制 | control → candidate | walltime 改善 |
| --- | --- | --- | ---: |
| gen3 | typed direct event array，消除已知 slot 的 pointer-backed 表示 | `51,763.25 → 50,308.75 ms` | `2.809909%` |
| gen12 | 统计并提升最热 input event，将 dominant event 放到 near storage/index 0 | `51,553.50 → 48,363.50 ms` | `6.187747%` |
| gen16 | 增加 batch-local non-volatile enum snapshot | `51,514.25 → 47,688.75 ms` | `7.426101%` |
| gen20 | 与 gen16 完全相同的 patch/生成代码复测 | `51,556.00 → 47,810.50 ms` | `7.264916%` |
| gen24 | 改为 hot-posedge decoded object bool + batch-local snapshot | `51,443.00 → 47,549.50 ms` | `7.568571%` |
| gen28 | 与 gen24 完全相同的 patch/生成代码复测，成为最终 best | `51,376.50 → 47,473.50 ms` | `7.596858%` |

gen16/gen20 的 patch SHA-256 都是 `034725003876...`，生成指纹都为 `a1b723ea471445e6...`；合并
8+8 个同源码端点样本后为 `51,535.125 → 47,749.625 ms`，改善 `7.345476%`。

gen24/gen28 的 patch SHA-256 都是 `2dff58bce8cd...`，生成指纹都为 `9eeec63950179e4d...`；合并
两轮同源码端点后为 `51,409.750 → 47,511.500 ms`，减少 `3,898.250 ms`，改善
`7.582706%`。这提供了不同时间、CPU/CCD 采样下的 exact-source repeat 证据。

继续复杂化没有超过 best：

- gen31 将 bool 移到 eval-local 并通过 batch ABI 传递，只剩 `4.457291%`；
- gen34 在 best 路径外再加 hot-event-only outer guard，只剩 `6.147810%`；
- gen38 的进一步 eval-local 变体 patch 无法应用。

因此当前证据支持保留“typed storage + dominant event + decoded object bool + batch-local snapshot”这一
形态，不支持额外 ABI threading 或 outer guard。

## 6. PMU 归因

最佳候选 4 control + 4 candidate 样本的算术均值为：

| 指标 | control | candidate | 相对变化 |
| --- | ---: | ---: | ---: |
| walltime | `51,376.50 ms` | `47,473.50 ms` | `-7.596858%` |
| cycles | `188,524,347,183.75` | `174,203,733,021.00` | `-7.596162%` |
| instructions | `158,921,964,204.75` | `160,552,013,602.50` | `+1.025692%` |
| frontend no-op slots | `827,034,713,037.50` | `754,569,189,026.25` | `-8.762090%` |
| frontend cmask6 | `105,028,361,049.50` | `95,598,983,607.00` | `-8.977934%` |
| backend stalls | `75,759,748,235.50` | `78,068,527,853.00` | `+3.047502%` |
| IPC | `0.842978` | `0.921634` | `+9.330623%` |

walltime 与 cycles 几乎同比下降，frontend starvation 指标下降约 `8.8%..9.0%`，但 retired
instructions 反而增加 `1.026%`，ELF 也增加 `0.243%`。因此当前最合理的解释是 predicate
表示、对象 alias dependency 与代码布局改善了前端供给/执行效率，而不是简单减少动态指令数量。
这也意味着落地验证不能用 source/ELF/instruction shrink 替代最终 walltime。

## 7. 全部探索路线

32 个 valid generated candidate 的 walltime 改善范围为 `-0.567051%..+7.596858%`，中位数为
`+0.013515%`；`16` 个为正、`16` 个非正，`8` 个达到 `1%`，`6` 个达到 `5%`。按候选机制对
全部 36 个已 evaluation patch 分类：

| 分支 | 总数 | valid / invalid | valid 正收益 | `>=1%` | 最好结果 |
| --- | ---: | ---: | ---: | ---: | ---: |
| event-edge / dominant predicate | `9` | `8 / 1` | `8` | `8` | `7.596858%` |
| exact-event lockstep commit activation | `24` | `21 / 3` | `7` | `0` | `0.886688%` |
| 其他 compute hint/helper | `3` | `3 / 0` | `1` | `0` | `0.038392%` |

所有达到 `1%` 的 candidate 都属于 event-edge 路线，说明本轮真正可复现的搜索进展高度集中，而不是
很多小 patch 的偶然叠加。

lockstep 路线仍有一个值得单独保留的次级线索：gen2 在现有 lockstep group 中将每个 state 的 reader
active ID 合并后一次 emit，pooled 为 `50,948.00 → 50,496.25 ms`，改善 `451.75 ms /
0.886688%`。但其 ABBA/BAAB 分别为 `1.035043% / 0.733667%`，order gap
`0.301376 pp`，超过既定 `0.25 pp` 复测线；gen10 又表现出更强 order 不对称。因此它目前只能作为
后续 quiet fresh 复测和“叠加到 best 后再测”的候选，不能据此落地或默认开启。其他 profitability
gate、large-group-only、strided/helper 变体均接近零或回退。

initial same-code control canary 本身为 `51,833.00 → 51,747.00 ms`，表观改善 `0.165917%`，也说明
本轮大量 `0.0x%` 结果只能按噪声处理。

## 8. 失败与有效性边界

5 次 generation failure 均是 `CodexExecError`：gen7/8/9 为 remote compact，gen11/23 先出现
reconnect/stream 诊断后最终以 remote compact 退出。它们均发生在当前 main 启动时加载的旧代码中，
因此 [TNO0210](./TNO0210_simpletes_codex_remote_compact_and_reconnect_session_continuation_20260731.md)
后来提交的 exact-thread transient continuation 没有被热加载；该修复会从下一次启动生效。此次没有
capacity 类 generation failure。

4 个 invalid candidate 均在候选 patch 应用阶段被 fail-close：一个 `corrupt patch at line 105`、一个
`patch fragment without header at line 13`，另两个分别在 `grhsim_cpp.cpp:20248` 和 `:22524`
无法 apply。它们没有进入 build/runtime，不能算功能或性能回退。正式 evaluator 的 function failure、
50k reject 和 evaluation failure 均为 `0`。

## 9. 保留结论与下一阶段入口

本轮结束后的保留边界为：

- **优先落地候选**：gen28 的 exact patch，SHA-256 `2dff58bce8cd...`；它有两个完全相同源码端点和
  稳定双 order 的约 `7.58%` 证据。
- **需要直接消融**：按 typed array、dominant event/index、batch snapshot、decoded bool 分层构建，
  直接从 current native baseline 做 final-minus-one/累加端点，避免只凭搜索路径推断单项贡献。
- **需要 fresh landing regression**：应用 patch 后再计算实际落地源码/patch SHA；完成 Wolvrix focused、
  pybind/XS、通用默认路径、small-model identity、SimTop 100/10k 功能及同 CCD fixed-ASLR
  ABBA+BAAB 50k walltime。不能在实际应用前预报落地源码 SHA。
- **次级待测**：gen2 lockstep union 先在 quiet CCD 重复到 order gap `<0.25 pp`，再测其叠加到 event
  best 的边际收益；当前不与 best 一并落地。
- **停止项**：gen31 ABI threading、gen34 outer guard 以及其进一步变体。

若最佳 patch 后续落地为新的 Wolvrix 通用默认，SimpleTES bench 需要把 control 重新 pin 到新的 parent /
Wolvrix executable snapshot，并以空 patch canary 证明 landed default 身份；之后才能在新 baseline 上继续
探索。现有 checkpoint、best program 和完整 LLM/evaluator artifact 均已保留，SimpleTES
`6517bfc...` 的 transient continuation 修复也会在下一次启动生效，因此本轮结束没有破坏后续继续研究的
入口。
