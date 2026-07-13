# NO0486 Active-word event-mask object probe gate

日期：2026-07-13

## 1. Scope gate

按 [NO0485](./NO0485_active_word_event_mask_object_probe_plan_20260713.md) 在 6 个 generated 副本中插入 133 个 active-word
event mask filters，覆盖 855 event-pure nodes/151 samples。133/133 audit keys 唯一，6/6 baseline/candidate 编译无诊断；baseline
`.text` 等于 production，production source/object SHA 前后不变。

## 2. Whole-object result

| metric | baseline | candidate | delta | delta % |
|---|---:|---:|---:|---:|
| `.text` bytes | 6,118,218 | 6,121,801 | +3,583 | +0.059% |
| instructions | 1,289,373 | 1,290,288 | +915 | +0.071% |
| memory-form | 540,491 | 540,763 | +272 | +0.050% |
| jumps | 40,539 | 40,660 | +121 | +0.298% |
| calls | 7,236 | 7,236 | 0 | 0.000% |

6/6 objects 的所有核心静态指标都增加：instructions 分别为 batch 58/21/35/41/24/30 的
`+185/+216/+184/+110/+131/+89`；jumps 为 `+18/+11/+44/+19/+16/+13`。

## 3. Explanation and decision

filter 在 edge-false 时能清 event-pure bits，因此不会执行目标 payload；但 word 内原有 entry tests 仍保留。posedge 路径新增
mask test + edge test，mixed word 即使 edge-false 也继续经过所有 entry tests。该形态没有像 NO0482 那样用 outer CFG 直接越过
entry/payload，静态成本因此跨 6 个对象一致增加。

违反 NO0485 的全部静态 gate，不进入 debug proof、emitter 或 runtime。

仍可独立审计 pure-event words：107 words/856 nodes/4,230 producers/125 samples/direct `1.873%`。代表 6 批次中有
78 words/624 nodes/3,127 producers/92 samples/direct `1.378%`。这些 words 的 8 个 entry bits 全属于同一 event key，可在
underlying clear 后用一个 word-level `if (event-hit) { original dispatch } else { activeWordFlags = 0; }` 同时跳过 entry tests 与
payload；不得把本次 mixed-word bit filter 扩展到生产代码。
