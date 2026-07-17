# TNO0090 Stage 14 native hybrid default adoption plan

记录日期：2026-07-17

状态：计划。基于 [TNO0087](./TNO0087_page_local_stage7_stage8_corrected_runtime_20260716.md) 的 correct page-local 双 node 结果，重新打开 Stage 7 hybrid 默认采用：N0/N1 cycles 分别为 `-4.237162%/-4.352957%`，instructions、frontend 与 backend 也在两边一致改善。现有数据只覆盖 `direct_single_writer_state_reads + pure_event_compute_word_bypass` 的组合，不能分别归因到任一单项，因此本阶段将两项成对迁为 C++ native defaults；XS 脚本只保留显式高/低层 override，不再独立指定默认。实现、source identity、显式回滚、build/tests 与 fresh NO0300 50k 均待执行。

## 1. 采用依据与归因边界

[TNO0060](./TNO0060_stage7_cross_socket_runtime_and_default_decision_20260715.md) 曾因 N0/N1 cycles 方向反转而拒绝 hybrid。随后 [TNO0085](./TNO0085_numa_file_page_locality_diagnosis_and_protocol_20260716.md) 证明旧协议直接使用 NFS inode，`numactl --membind` 不能迁移 file-backed executable pages；该反转混入了远端 page cache，不是可靠的候选代码结论。

TNO0087 在双 node 独立 `/dev/shm` inode、镜像 physical core、运行中 page placement、全 CCD monitor、五项 PMU、scheduler 与功能终点都通过的条件下得到：

| node | cycles | instructions | frontend empty | frontend `cmask>=6` | backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: |
| N0 | `-4.237162%` | `-4.835541%` | `-4.179816%` | `-4.254670%` | `-5.528546%` |
| N1 | `-4.352957%` | `-4.835541%` | `-4.412364%` | `-4.573177%` | `-4.575128%` |

两个 node 的 cycles 收益高度一致，且大于 control spread 与 1% 采用线；该结果足以重新评估默认采用。但历史实验没有 `direct-only`、`bypass-only`、`direct+bypass` 的完整 factorial 对照，因此只能把约 `4.3%` 收益归因给 hybrid 组合，不能宣称其中任一单项单独贡献相同收益。本阶段必须成对启用、成对回滚和成对裁决；单项默认值拆分需要另立实验。

## 2. 唯一 native 默认源

Stage 7 旧实现把 XS 默认写在 `scripts/wolvrix_xs_grhsim.py`，并把 direct 的解析结果写回 `WOLVRIX_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS`。这样会使直接调用 C++ emitter、Python binding 与 XS 脚本具有不同默认，也会让脚本进程中的低层环境值同时承担“用户输入”和“内部传递”两种含义。

Stage 14 计划改为：

1. C++ `grhsim_cpp` emitter 将 `direct_single_writer_state_reads` 和 `pure_event_compute_word_bypass` 的 native fallback default 同时设为 `true`；这是两项配置唯一的默认来源。
2. Python/native binding 为两项都保留 `bool | None` 语义：显式 `true/false` 写入 emitter attribute，`None` 不写 attribute，由 C++ 解析 native default 或低层环境 override。
3. XS 对每项按“XS 高层变量、既有低层变量、未设置”解析为 `true/false/None`；两层都缺失时必须传 `None`，不能在脚本中补 `true`，也不能把解析值写回低层环境。
4. 高层和低层显式 `0/1` 继续可覆盖 native default，日志必须区分 explicit override 与 `None/native-default`，避免只凭最终布尔值误判配置来源。
5. `pure_event_compute_word_profile` 继续默认 `false`，`pure_event_word_pack_policy` 继续默认 `off`；Stage 6 targeted packing 不随 hybrid 默认迁移。

该分层保证任何 emitter 调用方在没有显式 override 时得到同一个 native default，同时保留 XS 高层变量和 `WOLVRIX_GRHSIM_*` 低层变量作为受控实验入口。

## 3. 实现与 focused gate

实现预计覆盖 C++ emitter 默认解析、Python/native 参数透传、XS tri-state 配置和对应测试。完成前必须闭合：

- C++ 无 attribute、无环境变量时，两项实际解析为 `true/true`；
- C++ 显式 attribute `false/false` 优先于 native default；
- 低层环境 `0/0` 仍能回滚，显式 attribute 或 XS 高层值优先级不退化；
- Python `None` 不注入 attribute，显式 `False` 必须注入，而不能因假值判断被遗漏；
- XS 高层、低层、均未设置三种路径分别得到显式值、显式值和 `None`，且不污染当前进程的低层环境；
- default 与 explicit-on 生成的 focused source byte-exact；
- explicit-off 与原 NO0300 focused source byte-exact。

所有 focused 测试当前均为待补。若 direct 仍只能通过环境变量而不能通过 binding 显式传递，则配置分层尚未闭合，不能进入 production gate。

## 4. Fresh production identity 与回滚

从同一个 current canonical checkpoint 生成三套独立目录：

```text
native default       direct/bypass 均不显式设置
explicit-on          direct=true, bypass=true
explicit-off NO0300  direct=false, bypass=false
```

计划门禁为：

1. native default 与 explicit-on 的 activity-schedule stats、154 个 generated C++/headers 和 normalized emit stats byte-exact；两者都应复现 Stage 7 hybrid 的 direct-read 与 threshold-2 bypass source 形状。
2. explicit-off 的 activity-schedule stats 保持 canonical NO0300 SHA，生成源码在去除仅含 op/value ID 的诊断注释后回滚到 NO0300；若当前 canonical checkpoint 已消除注释编号差异，则直接要求 raw byte identity。
3. 三套生成均不出现 word-pack planner/applied marker，profile 保持关闭，packing policy 保持 `off`。
4. 默认与显式开启若 source 不同，先定位配置透传或非确定性来源，不进入 runtime；显式关闭若不能回滚，也不得采用 native default。

上述 production identity 当前均待执行。

## 增量更新 2026-07-17：walltime headline protocol 勘误

Stage 14 的最终采用判断改以 host walltime 为 headline；cycles/instructions/frontend/backend 只作解释。后续 runner 必须输出并校验 `walltime_ms` 与 `walltime_ok`，并将 `Host time spent` 原行和样本顺序归档。TNO0087 corrected page-local 的 wall headline 为 N0/N1 `-4.124340%/-4.399014%`，相应 cycles 仅作辅助，不再作为采用依据。

## 5. Build、回归与 fresh 50k

identity 闭合后，native default、explicit-on 和 explicit-off NO0300 至少完成所需的 fresh O3/link；default 与 explicit-off 分别通过 fixed-ASLR 100/10k/50k 功能门禁。50k 终点必须为：

```text
guest/cycleCnt/instrCnt/PC = 50001/49996/73580/0x80001312
```

子模块完整 build 与 CTest 也必须执行；只允许保留已知的 `transform-comb-lane-pack` 和 `transform-repcut` 失败，任何新增失败都先修复。build、focused/full tests 与功能结果当前均待补。

默认采用的 fresh runtime 以 explicit-off NO0300 为 control、native default hybrid 为 candidate。正式样本必须沿用 TNO0085 的 node-local 独立 inode、镜像核、`taskset + numactl --physcpubind/--membind`、`setarch x86_64 -R`、运行中 `numa_maps`、PMU、scheduler 和功能门禁，并执行 [TNO0089](./TNO0089_page_local_stage12_stage13_interim_runtime_and_strict_numa_protocol_20260717.md) 的整 node 30 秒 gate、运行期整 node monitor 与平衡 AB/BA 重复。机器不满足严格 quiet gate 时等待或整组重跑，不降级为只监控 CCD。只有 fresh 双 node 结果继续显示稳定正收益，才完成默认晋升；该 50k 结果当前待补。

## 6. 本阶段不晋升的选项

- Stage 8 p050 在 corrected N0/N1 cycles 为 `-0.089541%/+0.079792%`，判中性，`plain_dp_segment_penalty_ppm` 不修改。
- Stage 8 p200 在 corrected N0/N1 cycles 为 `+0.422334%/+0.343269%`，两边均温和回退，不修改默认。
- Stage 10 strict fanin pullback 的 corrected page-local 证据未形成稳定双 node 收益，继续显式 opt-in。
- Stage 12/13 commit merge cap 的严格复测尚未形成足以晋升的最终证据，commit guard cap 继续保持现值。
- pure-event word packing、profile 及其他 Stage 7+ 实验选项均不随 hybrid 自动开启。

因此 Stage 14 只处理 `direct_single_writer_state_reads + pure_event_compute_word_bypass` 这一对已有实现；不把 NUMA 勘误扩大为其他候选的默认变更。

## 7. 提交边界

本阶段预计同时修改 `wolvrix` 子模块中的 native emitter/binding/tests、父仓 XS 脚本与 TNO 文档。完成实现、identity、build/tests、功能和 fresh 50k 后，先提交子模块，再由父仓以 Stage 14 整体粒度提交 submodule pointer、脚本和文档；生成目录与 perf 日志不提交。
