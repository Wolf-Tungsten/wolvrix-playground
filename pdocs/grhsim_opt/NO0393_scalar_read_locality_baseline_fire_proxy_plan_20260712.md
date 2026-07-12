# NO0393 Scalar read-locality baseline-fire proxy plan

日期：2026-07-12

## 1. 口径修正

[NO0392](./NO0392_simtop_scalar_read_locality_fresh_emit_gate_20260712.md) 已证明 direct model 与 NO0357 generated code
逐字节一致，且 schedule/supernode ID 与 NO0300 相同。但 ID 相同不等于 runtime fire count 相同：direct state-read
已把 37,672 个 source heads 从 activation frontier 移除，并直接激活 consumer heads，因此 NO0311 的 NO0300 fire
只能作为可连接的 baseline proxy，不能冒充 direct runtime 真值。

本轮先做零额外仿真的 proxy join，用于定位候选集中在哪些 batch/supernode/value；不据此决定实现 typed local cache。

## 2. Join 与输出

输入：

```text
static:
  build/xs_grhsim_no0392_scalar_read_locality_20260712/grhsim/grhsim_emit/
  grhsim_materialized_scalar_read_locality.tsv
baseline fire proxy:
  build/logs/xs_perf/no0311/no0300_grhsim_supernode_fire.tsv
```

按 `(supernode_id, phase=compute)` 连接。必须验证 63,241 个 compute fire keys 唯一，static 表中的每个 supernode 都
命中。对每行计算：

```text
weighted_touches = operand_touches * baseline_fire
weighted_saved_proxy = loads_saved_per_fire * baseline_fire
```

输出全模型、touch threshold `2/3/4/8`、每 batch、compute1、compute62、top supernodes 和 top canonical values；全模型
覆盖率分母固定为所有 `candidate=0/1` 行的 weighted touches。

## 3. Decision

若 baseline proxy 的 weighted saved/all scalar touches 低于 `10%`，且 compute1/62 也无集中候选，则本方向可直接
否定。否则必须 fresh emit/build `direct + emit_runtime_profile` model，完成 50k 功能运行并用 direct fire 重算；只有
direct-fire 结果和 top candidate 反汇编共同通过，才进入 codegen 实现。

本篇只声明 proxy 分析计划，尚未生成 join 结果。
