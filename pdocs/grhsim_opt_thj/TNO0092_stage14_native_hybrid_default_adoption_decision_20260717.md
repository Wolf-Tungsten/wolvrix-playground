# TNO0092 Stage 14 native hybrid default adoption decision

记录日期：2026-07-17

状态：采用。基于 [TNO0087](./TNO0087_page_local_stage7_stage8_corrected_runtime_20260716.md) 的 correct page-local 双 node 约 `4.3%` cycles 收益，以及 [TNO0091](./TNO0091_stage14_native_hybrid_default_implementation_and_fresh_gates_20260717.md) 闭合的 fresh source、功能和机器码 identity，正式采用 `direct_single_writer_state_reads + pure_event_compute_word_bypass` 作为 C++ native defaults。fresh strict ABBA/BAAB 因外部 cirunner 负载尚待确认，但它不再阻塞本次采用；XS 保留显式 `0/0` 回滚，其他 Stage 7+ 候选均不随之晋升。

## 1. 采用对象与边界

本次只成对采用：

```text
direct_single_writer_state_reads = true
pure_event_compute_word_bypass   = true
```

两项的唯一默认源位于 C++ emitter。XS 与 Python 只传显式 override；未指定时传 `None`，由 C++ native fallback 决定。activity schedule 本身仍是当前 canonical NO0300 配置，fixed-ASLR 仍是 SimTop 50k 的性能口径；pure-event profile 和 word packing 继续关闭。

历史 runtime 没有完整的 direct-only/bypass-only factorial 数据，因此约 `4.3%` 收益只归因于 hybrid 组合，不拆分宣称任一单项独立贡献。默认开关、显式回滚和后续裁决也必须继续把两项视为一对。

## 2. Correct page-local 性能依据

TNO0087 使用 N0/N1 独立 `/dev/shm` inode、镜像 physical core、正确的 `taskset + numactl --physcpubind/--membind`、fixed-ASLR、运行中 page placement、全 CCD monitor、PMU、scheduler 与功能终点，得到：

| node | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: |
| N0 | `-4.237162%` | `-4.835541%` | `-4.179816%` | `-4.254670%` | `-5.528546%` |
| N1 | `-4.352957%` | `-4.835541%` | `-4.412364%` | `-4.573177%` | `-4.575128%` |

两个 node 的 cycles 方向和幅度高度一致，instructions 与前后端事件也同步改善。该收益明显大于 1% 采用线和当轮 control spread，且旧 NUMA 方向反转已由 NFS file-page locality 根因解释并通过 node-local inode 消除。因此 Stage 7 hybrid 具有稳定、跨 node 的正向证据。

## 3. Fresh 默认与历史被测机器码等价

Stage 14 fresh native-default source 去除纯 op/value 诊断注释后与历史 Stage 7 hybrid `154/154` byte-exact，fresh explicit-off 与 same-post NO0300 raw `154/154` byte-exact。进一步的 ELF 审计得到：

- Stage 14 default 与 Stage 7 measured hybrid 的 `.text/.data/.eh_frame` SHA 分别完全相同；
- Stage 14 off 与 Stage 10 same-post NO0300 的 `.text/.data/.eh_frame` SHA 也分别完全相同；
- 每对完整 ELF 仅有 `6` 个 `.rodata` 字节不同，全部是编译日期/时间字符串。

因此本次默认来源从 XS 移入 C++ 没有改变被测机器码，也没有引入新的 codegen/link-layout 变量。TNO0087 的性能结果可直接对应 Stage 14 native default，而 explicit-off 是可追溯的 NO0300 control。

## 4. Fresh strict runtime 为确认项而非采用阻塞项

按 [TNO0089](./TNO0089_page_local_stage12_stage13_interim_runtime_and_strict_numa_protocol_20260717.md) 升级后的整 node 30 秒 gate 尝试启动 fresh strict ABBA/BAAB 时，N0/N1 mean idle 只有 `88.517%/85.964%`；外部 cirunner 任务占用整机资源，脚本在运行 emu 前正确拒绝，没有形成可用 perf 样本。

该严格复测仍应在机器满足门槛时补齐，但不作为本次采用的阻塞条件，原因是：

1. TNO0087 的 14 个样本已通过当时完整的 page-local、双 node、持续 CCD、PMU、scheduler 与功能门禁，hybrid 信号约 `4.3%` 且两边一致；
2. 升级整 node 协议的直接触发点是 cap 候选的约 `0%..2%` 小信号与 control 漂移，而 hybrid 收益明显更大，并有全套事件同向支撑；
3. fresh ELF 的可执行机器码与 TNO0087 被测 ELF 完全相同，待补实验是在更严格环境中确认既有结果，不是在验证一份新的实现。

后续 quiet window 出现时仍按 node-local inode、整 node pre/run monitor、平衡 ABBA/BAAB 和全部功能/PMU/scheduler gate 补测并另立文档。若该结果与现有双 node 证据实质冲突，再通过增量勘误重新评估默认，而不是用当前受污染 wall time 推翻或强化结论。

## 5. 默认入口与显式回滚

无相关环境或 attribute 时，所有 C++/Python/XS 调用路径都落到 native `true/true`。XS 高层实验入口仍可显式回滚：

```bash
WOLVRIX_XS_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS=0
WOLVRIX_XS_GRHSIM_PURE_EVENT_COMPUTE_WORD_BYPASS=0
```

既有低层 `WOLVRIX_GRHSIM_*` 变量也继续可用；XS 高层值优先于低层值。脚本不写回低层环境，日志分别显示 `cpp-default` 或显式 `True/False`，因此默认来源与用户 override 可区分。

explicit-off 已通过 source raw identity、ELF section identity 和 fixed-ASLR 100/10k/50k 功能门禁。若下游需要历史 NO0300 行为，应成对设置 `0/0`，不建议只关闭其中一项后仍称为 NO0300 control。

## 6. 其他选项不晋升

- Stage 8 p050 corrected cycles 为 N0 `-0.089541%`、N1 `+0.079792%`，判中性，`plain_dp_segment_penalty_ppm` 保持现值。
- Stage 8 p200 corrected cycles 为 N0 `+0.422334%`、N1 `+0.343269%`，两边均温和回退，不采用。
- Stage 10 strict fanin pullback 没有形成稳定的双 node 正向证据，继续显式 opt-in。
- Stage 12/13 commit merge cap 的严格双 node、平衡顺序结果尚未闭合，且已有样本受 socket 级 control 漂移影响；默认 cap 不修改。
- pure-event word packing/profile、Stage 1..6 与其他实验开关均不随 hybrid 默认迁移。

NUMA/file-page 勘误只重新打开了有明确 corrected 收益的 hybrid，不构成批量开启此前所有关闭选项的理由。

## 7. 最终决定

Stage 14 完成以下默认迁移：C++ native fallback 为 `true/true`，Python/XS tri-state 只负责 override，显式 `0/0` 保留 NO0300 回滚。采用依据是双 node page-local 约 `4.3%` 的已验证收益和 fresh 历史机器码完全等价；当前外部负载只延后更严格协议的确认样本，不延后代码采用。

本阶段提交应以实现、测试、XS 配置分层、TNO0090..TNO0092 和 submodule pointer 为一个整体；先提交 `wolvrix` 子模块，再提交父仓，生成目录与 perf 日志不纳入版本控制。
