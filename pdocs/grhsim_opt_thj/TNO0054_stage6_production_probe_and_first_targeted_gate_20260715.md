# TNO0054 Stage 6 production probe and first targeted gate

日期：2026-07-15

## 1. 有效实验环境

承接 [TNO0053](./TNO0053_stage6_targeted_pure_event_pack_implementation_20260715.md)，本轮在当前仓库默认 NO0300、ASLR 关闭的基线上执行 SimTop production probe/targeted。每个有效 shell 都先执行 `source env.sh`，再运行生成或检查命令。此前一次仅设置 `WOLF_ENV_SOURCED=1`、没有实际 source 的部分 probe 已中断并删除产物与日志，不进入本文任何结论。

两组均从 current-default pre-reg-to-mem checkpoint 恢复，并保持 activity-schedule policy 为默认关闭；共同只增加：

```text
WOLVRIX_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS=1
WOLVRIX_XS_GRHSIM_PURE_EVENT_COMPUTE_WORD_BYPASS=1
WOLVRIX_XS_GRHSIM_PURE_EVENT_COMPUTE_WORD_PROFILE=0
```

probe/targeted 分别设置 `pure_event_word_pack_policy=probe|targeted`，moved 与 changed-word 预算分别为 `5000 ppm`、`20000 ppm`。

## 2. Production probe

正确环境下的 probe 完整生成通过，exit `0`。activity-schedule 结构与 current-default 基线精确一致：

```text
supernodes                 63726
compute / commit           63241 / 485
DAG edges                  528622
boundary values            1000463
boundary activation edges  1983923
graph ops / values         7204108 / 6833009
stats SHA256               e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
baseline cmp               identical
```

planner 的 production 机会量与离线审计精确复现：

```text
baseline / candidate pure words  107 / 171
added / lost pure words           64 / 0
moved supernodes                  256 / 63241 = 4048 ppm
moved event supernodes            128
changed compute active words      127 / 7932 = 16011 ppm
max active-ID displacement        648
Kahn levels / frozen batches      97 / 117
validation_passed                 true
applied                           false
```

probe source 即当前 threshold-2 hybrid control。marker 核对为 `107` pure words、`22` eligible batches、`20` sparse volatile words、`14` sparse batches；117 个 schedule C++ 共 `1,331,063,668` bytes、`13,383,537` lines。

## 3. 首次 targeted hard gate

targeted 的 activity schedule 再次复现相同结构，但 emitter 在采用 candidate、释放 baseline model、完整重建 active-ID 派生结构后被 frozen-batch validator 拦截：

```text
error frozen batch rebuild changed batch metadata: batch=74 (SimTop)
```

因此本轮没有可编译的 targeted source，也没有运行 SimTop。当前 validator 把 index、phase、op count 与 estimated lines 合并为一条粗粒度错误，尚不能凭这条消息放宽门禁。

只读代码审查指出 batch 74 是 commit batch；commit write 的 `estimatedLines` 会根据 reader compute active IDs 估算 activation mask/chunk/table 行数，targeted 重排 compute active IDs 后该 cost proxy 可能合理变化。它只参与初始 batch 划分，不是仿真语义，但仍需先用增强诊断取得精确 baseline/rebuilt 差值，并继续严格检查 index、phase、op count、membership、active-word slots、commit order 与 rebuilt active-ID vectors。

## 4. 当前决策

probe 机会量和全部前置硬门禁通过，值得继续。下一步先增强 metadata 差异诊断并复现 batch 74；只有证明变化仅限于 `estimatedLines` cost proxy，才把该字段改为记录 rebuilt 值而非 identity hard gate。其他结构与语义门禁不放宽，policy 继续默认 `off`。
