# NO0449 Global scope source-line correction

日期：2026-07-13

## 1. Preflight correction

[NO0448](./NO0448_global_compute_scope_attribution_plan_20260713.md) 要求 5,590/5,590 compute rows 逐 batch/line 重读
generated source，并要求每个 recorded `_op_N` 可定位。检查固定输入 TSV 后确认这个 gate 对 source-less inline frames 写得过严：

| Existing row form | Samples |
| --- | ---: |
| Has generated source line | 4,833 |
| No generated line, resolved runtime inline frame | 562 |
| No generated line, unresolved | 195 |
| Total | 5,590 |

757 个 source-less rows 的既有 `operation_id/operation_kind` 全为空，因此不存在可供定位的 recorded `_op_N`。NO0404 的
5,395 resolved 正好等于 4,833 generated-line rows 加 562 runtime-only rows；195 unresolved 口径不变。

## 2. Corrected validity gate

NO0448 后续执行修正为：

1. 4,833/4,833 generated-line rows 必须逐 batch/line 与实际 source text 一致；
2. 其中 non-empty recorded `_op_N` 必须能在同一 source 找到，empty operation label 不强行补 kind；
3. 562 runtime-only rows 独立标 `runtime_frame_only`，继续使用既有 helper name/line；
4. 195 rows 保持 `unresolved`；
5. 全部 5,590 samples 仍进入 corrected summary，direct/compute 百分比的分母不变。

source-less 两类不得按相邻 generated comment 猜 operation kind，也不能触发 exact-operation 1% gate。这个修正只改变 NO0448
的输入有效性条件，不改变 scope ownership 模型和下一候选门槛。
