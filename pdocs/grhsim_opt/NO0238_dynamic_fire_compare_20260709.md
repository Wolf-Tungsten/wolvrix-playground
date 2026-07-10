# NO0238：VtypeBuffer GrhSIM/GSIM dynamic fire 对比

日期：2026-07-09

## 1. 背景

承接：

- [NO0234](./NO0234_vtypebuffer_phase_specific_gsim_delta_20260709.md)：确认 `VtypeBuffer` GrhSIM `input-low` 相比 GSIM `subStep1()` runtime `3.72x`、instructions `4.57x`；
- [NO0237](./NO0237_asm_spill_and_supernode_size_ab_20260709.md)：确认 GrhSIM input-low compute0-3 静态机器码指令约为 GSIM `subStep1()` 的 `4.02x`，简单调 supernode size 不是突破口。

本轮目标是回答一个更直接的问题：**同一批输入下，GrhSIM 和 GSIM 的 active 节点到底动态 fire 了多少？GrhSIM 慢是因为 fire 次数多，还是因为每次 fire 的块更重、且框架开销更大？**

## 2. 实验口径

负载：`XsReal075RobVtypebufferLarge`。

基线生成物：

```text
testcase/xs-components/build/no0228_model_select_perf_20260709/raw_bench/XsReal075RobVtypebufferLarge
```

临时实验目录：

```text
tmp/no0238_supernode_fire_profile_20260709
```

执行前按用户提醒使用：

```bash
source env.sh
set -euo pipefail
```

注意：本轮只 patch 临时拷贝的生成 C++，没有修改仓库源码。

`make_vectors(200000)` 实际产生 `200002` 个输入向量（前面有 2 个 seed vectors）。本文中的 per-vector 以 `200002` 为分母。

## 3. GrhSIM phase-specific supernode fire

插桩方式：在临时 GrhSIM 生成物中，对每个 supernode 分支：

```cpp
if (unlikely(activeWordFlags & UINT8_C(mask))) {
    ++grhsim_probe_fire_counts[supernode_id];
    ...
}
```

并单独跑：

1. `input_low`：每个 vector 只统计 `drive + clock=false eval()`；`clock=true eval()` 只用于推进状态，不计数；
2. `clock_high`：每个 vector 只统计 `clock=true eval()`；前面的 `clock=false eval()` 不计数。

### 3.1 input-low

摘要：

```text
[GRHSIM_PROBE_SUMMARY] phase=input_low vectors=200002 eval_calls=200002 rounds=200001 compute_batch_calls=200001,200001,200001,200001 commit_batch_calls=200001 active_word_nonzero=200001,200001,200001,200001,200001
```

关键现象：

- compute supernode `0..37` 全部 fire `200001` 次；
- 也就是 `38` 个 compute supernode 几乎每个 vector 都 fire；
- input-low 基本没有事件驱动剪枝，表现为一次 full compute pass。

### 3.2 clock-high

摘要：

```text
[GRHSIM_PROBE_SUMMARY] phase=clock_high vectors=200002 eval_calls=200002 rounds=400003 compute_batch_calls=400003,400003,400003,400003 commit_batch_calls=400003 active_word_nonzero=200001,200001,200001,200001,200001
```

关键现象：

- commit supernode `38` fire `200002` 次；
- 多数 compute supernode 也接近每 vector fire；
- 少数 compute supernode 较低频，例如：
  - `19`：`11691`，约 `5.85%`；
  - `21`：`12900`，约 `6.45%`；
  - `22`：`13187`，约 `6.59%`；
  - `23`：`13159`，约 `6.58%`；
  - `29`：`150256`，约 `75.13%`。

这和此前 high phase 常见两轮一致：posedge commit 每次发生，commit 后又激活大部分 compute。

## 4. GrhSIM supernode 静态规模 × 动态 fire

把 fire count 和生成源码块做粗略合并（`src_lines × fire` 只是定位用 proxy，不作为机器指令精确值）。

### 4.1 input-low top supernodes

| supernode | batch | lines | ops | slot refs | wide slots | storage refs | low fire | high fire |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `3` | `0` | `1349` | `116` | `231` | `0` | `0` | `200001` | `0` |
| `24` | `3` | `663` | `65` | `218` | `2` | `7` | `200001` | `200001` |
| `1` | `0` | `653` | `67` | `134` | `0` | `0` | `200001` | `0` |
| `28` | `3` | `524` | `61` | `180` | `1` | `12` | `200001` | `200001` |
| `12` | `1` | `441` | `76` | `110` | `0` | `36` | `200001` | `200001` |
| `33` | `3` | `341` | `20` | `106` | `8` | `0` | `200001` | `200001` |
| `27` | `3` | `336` | `32` | `114` | `1` | `0` | `200001` | `200001` |
| `17` | `2` | `306` | `47` | `92` | `0` | `1` | `200001` | `200001` |

### 4.2 changed/active 框架动态工作量

按源码计数 proxy，200002 vectors 下：

| phase | changed checks | any_changed updates | active-or updates | slot-ref work | src line work |
|---|---:|---:|---:|---:|---:|
| GrhSIM `input_low` | `122400612` | `234201171` | `27400137` | `624403122` | `1987409937` |
| GrhSIM `clock_high` | `75435521` | `108784925` | `60337099` | `507213094` | `1731926859` |

这里最值得注意的是：`input_low` 已经近似 full compute pass，但仍然执行了大量 changed-check 和 downstream active propagation 维护。

## 5. GSIM `subStep1()` dynamic node fire

同样在临时 GSIM 生成物中插桩 `subStep1()`：

```cpp
if (unlikely(oldFlag & 0x...)) { // id=N
    ++gsim_probe_node_fire[N];
    ...
}
```

跑法对齐 [NO0234](./NO0234_vtypebuffer_phase_specific_gsim_delta_20260709.md) 的 `gsim-sub1-input-only` 口径：reset 后每个 vector `drive_gsim()`，然后只调用 `subStep1()`。

摘要：

```text
[GSIM_PROBE_SUMMARY] phase=substep1_input_only vectors=200002 substep1_calls=200002 active_word_nonzero=..., word26..33=200002, word34=99642, ...
```

动态节点：

- `subStep1()` 内有 `66` 个 node 分支，本轮全部至少 fire 过一次；
- 其中一部分每 vector fire，另一部分约 `0.5x` 或 `0.75x` per vector；
- total fire 为 `9073562`。

Top 源码工作量 proxy：

| GSIM node | lines | ifs | assigns | old vars | active sets | fire | per vector |
|---:|---:|---:|---:|---:|---:|---:|---:|
| `270` | `699` | `3` | `182` | `6` | `0` | `200002` | `1.000` |
| `230` | `75` | `3` | `24` | `2` | `2` | `200002` | `1.000` |
| `238` | `75` | `3` | `24` | `2` | `2` | `200002` | `1.000` |
| `210` | `74` | `3` | `23` | `2` | `1` | `200002` | `1.000` |
| `214` | `74` | `3` | `23` | `2` | `1` | `200002` | `1.000` |
| `216` | `74` | `3` | `23` | `2` | `1` | `200002` | `1.000` |
| `220` | `74` | `3` | `23` | `2` | `1` | `200002` | `1.000` |
| `224` | `74` | `3` | `23` | `2` | `1` | `200002` | `1.000` |

Aggregate proxy：

| item | value |
|---|---:|
| GSIM `subStep1()` nodes | `66` |
| total fire | `9073562` |
| src line work | `719473869` |
| assign work | `235351905` |
| active set work | `12138080` |
| old-var work | `25208493` |

## 6. GrhSIM input-low vs GSIM subStep1 汇总

| metric | GrhSIM `input_low` | GSIM `subStep1()` | GrhSIM / GSIM |
|---|---:|---:|---:|
| active blocks/nodes | `38` supernodes | `66` nodes | - |
| total fire | `7600038` | `9073562` | `0.84x` |
| src line work proxy | `1987409937` | `719473869` | `2.76x` |
| framework active updates proxy | `261601308` (`any_changed + active-or`) | `12138080` (`active set`) | `21.55x` |

解读：

1. GrhSIM 慢不是因为动态 fire 次数更多；事实上 GrhSIM `input_low` 的 block fire 总数比 GSIM `subStep1()` node fire 少；
2. 但 GrhSIM 的 block 粒度更大，每个 supernode 内部保留大量 slot refs、changed-check、`any_changed` fanout 和 active propagation；
3. 在当前随机输入流下，GrhSIM `input_low` 已经退化成 full compute pass，event-driven changed propagation 基本不能剪枝，却仍然付出了维护成本；
4. 这可以解释 [NO0234](./NO0234_vtypebuffer_phase_specific_gsim_delta_20260709.md) 中 GrhSIM `input_low` retired instructions `4.57x` 于 GSIM：动态 fire 数不是主因，**每次 fire 的代码形态和 active/change 框架成本才是主因**。

## 7. 对后续优化的启发

下一步不应继续只调 partition size。更有希望的是做 phase/codegen specialization：

1. **input-change full-pass fast path**：当直接输入变化使 compute DAG 基本全量 active 时，生成 topological full-pass 版本，避免 compute->compute changed propagation；
2. **只保留必要 changed-check**：full-pass 内 downstream compute 已经会执行，很多 `any_changed_*` 和 `supernode_active_curr_ |= ...` 对 compute target 是冗余的；仍需谨慎保留 output/commit/high phase 所需的 state/visible value 更新；
3. **把 GrhSIM 大 supernode 内部 scalar/local 化**：即使 full-pass，当前 `slot_ref` work 也明显偏高，需要减少 `value_*_slots_` / storage-ref 往返；
4. **用 dynamic fire + src/asm gate 做 A/B**：后续 patch 只有在降低 `src_line_work` proxy、hot symbol 静态指令、stack operands 或 perf instructions 时才值得保留。

本轮结论更具体地把“GrhSIM 比 GSIM 多了什么”定位到：**近似 always-active 时仍保留的 changed/active propagation 框架 + 更大的 supernode 内 slot/ref 代码体积**。
