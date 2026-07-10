# NO0243 Posedge full-pass probe for GrhSIM high phase

记录日期：2026-07-09

关联：[`NO0230`](./NO0230_grhsim_eval_trace_round_structure_20260709.md)、[`NO0232`](./NO0232_vtypebuffer_edge_semantics_probe_20260709.md)、[`NO0233`](./NO0233_vtypebuffer_phase_counters_gsim_alignment_20260709.md)、[`NO0238`](./NO0238_dynamic_fire_compare_20260709.md)、[`NO0241`](./NO0241_input_fullpass_codegen_p0_20260709.md)、[`NO0242`](./NO0242_input_fullpass_small_matrix_20260709.md)

## 1. 背景

`NO0242` 显示 `input_fullpass_specialization` 主要降低 input-low / data-input settle，FTQ/Tage/VtypeBuffer 的 low phase 下降约 `24%~27%`；但 high phase 基本没有收益，甚至在单次 phase run 中略升。

本轮继续对照 GSIM 与 GrhSIM 的 high path，目标不是直接改 emitter，而是在 generated C++ 上做一个上界 probe，判断 clock-edge commit/post-commit settle 是否也可以用 full-pass 思路回收 active/change propagation 成本。

## 2. GSIM / GrhSIM high path 代码对照

VtypeBuffer bench 语义：

```cpp
// GSIM: 每 vector 一次 step
drive_gsim(dut, in);
dut.set_clock(1);
dut.step();
sample_gsim(dut);

// GrhSIM: data settle 后 sample，再 posedge 推进 state
drive_grhsim(dut, in);
dut.clock = false;
dut.eval();
sample_grhsim(dut);
dut.clock = true;
dut.eval();
```

因此 GrhSIM 的 high eval 不是输出采样前的组合 settle，而是 posedge commit + commit 后为下一 vector 准备的 state-driven settle。

GSIM `step()` 形态非常薄：

```cpp
void SXsReal075RobVtypebufferLarge::step() {
  resetAll();
  subStep0();
  subStep1();
  cycles ++;
}
```

静态反汇编计数（`objdump -d -C`，只作 code-shape proxy）：

| side | symbol | instr | stack ops | mem ops | branches |
| --- | --- | ---: | ---: | ---: | ---: |
| GSIM | `subStep0()` | `7939` | `245` | `2518` | `1124` |
| GSIM | `subStep1()` | `2817` | `8` | `802` | `321` |
| GrhSIM | `eval_compute_batch_0()` | `2765` | `261` | `936` | `208` |
| GrhSIM | `eval_compute_batch_1()` | `1747` | `200` | `699` | `86` |
| GrhSIM | `eval_compute_batch_2()` | `2385` | `197` | `1027` | `669` |
| GrhSIM | `eval_compute_batch_3()` | `4382` | `927` | `2112` | `152` |
| GrhSIM | `eval_commit_batch_4()` | `1483` | `0` | `760` | `163` |

GrhSIM normal compute batch 静态 instr 合计约 `11279`，和 GSIM `subStep0+subStep1=10756` 同量级；但 high eval 动态上通常是 fixed-point 两轮：

1. 第一轮：clock posedge 只让 commit batch 真实工作，compute batches 先空扫；
2. commit 写 state 后设置 `commit_activated_readers_` 和 `supernode_active_curr_`；
3. 第二轮：compute batches 再按被激活 reader 工作；event 已清，commit batch 再空扫。

因此 high 的问题更像是 GrhSIM 的 fixed-point 双轮/dispatch/activation propagation，而不是单个 compute batch 静态体积突然比 GSIM 大很多。

commit batch 文本计数也说明当前框架成本不小：

| item in `eval_commit_batch_4()` | count |
| --- | ---: |
| `kRegisterWritePort` | `113` |
| `grhsim_value_storage_ref(...)` | `113` |
| `grhsim_state_scalar_4_slot_*` occurrences | `452` |
| `commit_activated_readers_ = true` | `113` |
| `supernode_active_curr_` / `grhsim_or_active_*` writes | `211` |

## 3. generated C++ probe

产物：

```text
tmp/no0243_posedge_fullpass_probe_20260709/XsReal075RobVtypebufferLarge/
```

基于 `NO0242` 的 `on` model 复制一份，只手工 patch `grhsim_XsReal075RobVtypebufferLarge_eval.cpp`：

- 仅当 `!initial_eval`、event edge 是 `posedge`、且所有 data/reset input 都等于 previous input 时触发；
- 不改 low/input fast path；
- high fast path 逻辑为：
  1. 清空 active；
  2. 保留 `event_edge_slots_[0]=posedge`，调用一次 `eval_commit_batch_4()`；
  3. 如果 commit 确实改变 state，则调用 `eval_compute_batch_0_fullpass()` 到 `eval_compute_batch_3_fullpass()`；
  4. 不再执行第二次 commit batch，不再依赖 commit-activated compute propagation；
  5. 清 event/active，刷新 outputs，更新 previous-input baseline。

这只是上界实验，不是 production semantics。它假设 posedge-only eval 前已经有一次 low/data settle，把 commit RHS 所需 value 算好；data 与 clock 同 eval、reset、initial eval 全部保守排除。

## 4. correctness

验证：

| check | result |
| --- | --- |
| `--verify 4096` + 20k bench | pass |
| paired 200k run checksum | baseline/probe final checksum 均为 `0xa6ff99241ea2cc48` |
| `--verify 200000` | pass |

`--verify 200000` 命令在 load average `16.46, 17.01, 34.68` 下通过，说明 VtypeBuffer 这个 workload 的 200k 窗口内逐 vector 对齐。

## 5. paired runtime

按用户提醒，probe 没有单独看优化版，而是在当前负载下相邻 rerun baseline-on 与 probe。

机器负载：`24.94, 18.44, 35.70` 到 `23.35, 18.22, 35.54`，宿主 `384` 核。

Raw `200000 --repeat 3 --model grhsim`：

| model | min ms | median ms | checksum |
| --- | ---: | ---: | --- |
| baseline on (`NO0242` on) | `370.309` | `370.318` | `0xa6ff99241ea2cc48` |
| posedge probe | `309.097` | `309.760` | `0xa6ff99241ea2cc48` |

按 min 计：`370.309ms -> 309.097ms`，delta `-16.53%`。

Phase `200000 --repeat 1 --grhsim-phase-profile`：

| model | measured ms | low ms | high ms | low ns/vector | high ns/vector |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline on | `381.867` | `153.307` | `218.707` | `766.5` | `1093.5` |
| posedge probe | `328.252` | `135.975` | `182.360` | `679.9` | `911.8` |

Delta：

| metric | delta |
| --- | ---: |
| measured | `-14.04%` |
| low | `-11.31%` |
| high | `-16.62%` |

low 也下降，说明单次 phase 中仍可能混入 code layout / branch predictor / measurement noise；不能把 raw `-16.53%` 全部归因到 high path。但是 high phase 本身从 `218.707ms` 降到 `182.360ms`，足以说明 posedge commit/post-commit fixed-point 框架存在可回收空间。

## 6. 结论

本 probe 支持下一步把 high phase 纳入 full-pass specialization：

- `input_fullpass_specialization` 已证明 data-input settle 可以跳过 compute propagation；
- `posedge_fullpass` probe 进一步证明，posedge-only eval 可以跳过“commit 激活 reader 后再按 active propagation settle”的一部分成本；
- VtypeBuffer 上界收益约为 GrhSIM 总 runtime `-16.5%`，high phase `-16.6%`。

但仍不应直接默认开启：

1. 当前只验证了 VtypeBuffer；FTQ/Tage 还未 patch 复测；
2. 需要在 emitter 中正确识别 posedge-only / data+clock 同 eval / reset / multi-clock event；
3. 需要决定 commit 后是否总是 fullpass compute，还是仅当 `commit_activated_readers_` 为 true 时 fullpass；
4. 需要避免代码布局造成的误判，后续至少要做 paired baseline rerun。

建议下一步：把这个 generated patch 泛化到 FTQ/Tage 两个 case 做临时 probe；若均 correctness pass 且 high phase 明确下降，再实现默认关闭的 `posedge_fullpass_specialization` emitter 开关。
