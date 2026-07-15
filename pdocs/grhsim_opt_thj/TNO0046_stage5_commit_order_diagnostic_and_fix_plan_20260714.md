# TNO0046 Stage 5 commit-order diagnostic and fix plan

记录日期：2026-07-14

状态：增强诊断复现 Stage 5 strict硬失败，已证明是相同commit partition内的vector order漂移，不是sink/input集合或分组改变；计划在strict candidate rewrite中验证并复用baseline commit partition/order，保留exact validator。

## 1. Diagnostic2 证据

同一checkpoint与strict配置复跑，首个mismatch：

```text
commit node = 216
ops_equal = false
inputs_equal = false
op sizes = 1850 / 1850
input sizes = 2720 / 2720
op_set_equal = true
input_set_equal = true
```

全局与normalized partition：

```text
global_sink_op_set_equal = true
global sink counts = 218994 / 218994
global_input_value_set_equal = true
global input counts = 256377 / 256377
normalized_op_partition_equal = true
normalized_input_partition_equal = true
```

首差：

```text
op    pos=1637 baseline=2849284 candidate=2841816
input pos=2304 baseline=2792543 candidate=2788282
```

两侧前八项sample也完全相同。由此确认：sink op/input没有新增、删除或跨commit node迁移；clone/use rewrite改变refreeze后的op topo tie-break，使同一commit node内部顺序后段发生变化。

diagnostic2仍按硬门禁exit `1`，wall `4:59.07`，peak RSS `28,320,592 KiB`，无stats/full build。

## 2. 为什么不直接放宽为set equality

commit op顺序可能涉及ordered write或其他side-effect语义。即使两个topo顺序都合法，本阶段目标是隔离compute activity变化，不应顺带接受commit code/layout重排。因此不把validator从exact equality降为set equality。

更稳妥的方式是在strict candidate compute rewrite中复用baseline commit partition和vector order；这样最终schedule保持commit侧完全不变，只比较compute clone带来的结构/runtime差异。

## 3. Fixed-partition seed 契约

`buildComputeNodeRewrite` 增加仅strict candidate使用的可选baseline commit seed。使用前必须验证：

- copied commit op全部仍valid且class为Sink；
- copied sink op全集精确覆盖candidate `ActivityOpData`中的全部Sink，无重复/缺失；
- 按copied `commit.ops`顺序从当前graph operands重建unique input vector，与copied `inputValues` exact相同；
- commit cap/event配置仍与baseline一致。

验证后复制baseline commit nodes/order和相关commit stats，再按该固定root顺序运行后续compute builder。default/probe/Stage3 local-owner调用不传seed，行为不变。

candidate rebuild完成后，原exact commit validator继续逐node比较ops/input vectors；任何真实sink/operand变化仍会失败。

## 4. 原始产物

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage5_common_owner_strict_diag2_20260714.log
```

修复实现与focused测试通过后，必须第三次重跑同一SimTop strict structure gate；未通过前不进入full build/50k。
