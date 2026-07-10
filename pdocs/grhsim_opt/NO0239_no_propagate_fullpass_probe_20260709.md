# NO0239：No-propagate full-pass probe 验证 GrhSIM active/change 框架成本

日期：2026-07-09

## 1. 背景

[NO0238](./NO0238_dynamic_fire_compare_20260709.md) 显示 `VtypeBuffer` GrhSIM `input_low` 阶段中 `38` 个 compute supernode 几乎每个 vector 全部 fire；也就是说它已经接近 full compute pass，但仍保留大量：

- `grhsim_changed_*` changed-check；
- `grhsim_any_changed_*` fanout update；
- `supernode_active_curr_ |= ...` / `activeWordFlags |= ...` active propagation。

本轮做一个临时、语义不完整的上界 probe：**在生成物拷贝中删除 compute->compute active propagation，并新增一个只用于 input-low 诊断的 full-pass 方法**，看机器码和 low-only runtime 是否明显下降。

## 2. 实验口径

负载：`XsReal075RobVtypebufferLarge`。

临时目录：

```text
tmp/no0239_no_propagate_fullpass_probe_20260709
```

执行前使用：

```bash
source env.sh
set -euo pipefail
```

重要限制：

- 本实验只 patch 临时拷贝的生成 C++；没有修改仓库源码；
- patch 后的模型**不保证完整 GrhSIM eval 语义**；
- 它只用于验证 `input_low` full-pass 下 active/change propagation 的成本上界；
- low-only runner 不执行 high/commit 推进状态，因此不是完整仿真 benchmark。

## 3. patch 内容

在 compute schedule 文件 `sched_0..3.cpp` 中删除 active propagation 语句：

| file | stripped active propagation statements |
|---|---:|
| `sched_0.cpp` | `41` |
| `sched_1.cpp` | `33` |
| `sched_2.cpp` | `41` |
| `sched_3.cpp` | `22` |
| total | `137` |

典型被删除形态：

```cpp
supernode_active_curr_[w] |= ...;
activeWordFlags |= ...;
grhsim_or_active_u16/u32(...);
```

新增诊断方法：

```cpp
void GrhSIM_XsReal075RobVtypebufferLarge::eval_probe_input_low_fullpass()
```

该方法先设置所有 compute active bits：

```cpp
supernode_active_curr_[0] = 255;
supernode_active_curr_[1] = 255;
supernode_active_curr_[2] = 255;
supernode_active_curr_[3] = 255;
supernode_active_curr_[4] = 63; // compute bits only, excluding commit bit
```

然后顺序调用 `eval_compute_batch_0..3()`，最后 `refresh_outputs()`。

由于 active propagation 的使用点被删掉，Clang 可以进一步 DCE 掉大量 `grhsim_any_changed_*` update 和部分 changed-check。

## 4. low-only runtime A/B

runner 口径：

- `make_vectors(200000)`，实际 `200002` vectors；
- baseline：每个 vector `drive_grhsim()` + `clock=false` + normal `eval()`；不执行 high；
- probe：每个 vector `drive_grhsim()` + `eval_probe_input_low_fullpass()`；不执行 high；
- repeat 5，取 min；
- 两者 cumulative checksum 相同：`0x8eaf220b7bd8c5de`。

结果：

| mode | min ms | median ms | checksum |
|---|---:|---:|---|
| baseline low-only | `203.141` | `203.267` | `0x8eaf220b7bd8c5de` |
| no-propagate fullpass probe | `131.593` | `131.734` | `0x8eaf220b7bd8c5de` |

相对 baseline：`-35.22%`。

这说明在 input-low/full-pass 场景下，compute->compute active/change propagation 的成本非常真实，不只是源码表面现象。

## 5. compute batch 静态机器码 A/B

`eval_compute_batch_0..3` 汇编统计：

| batch | baseline bytes | patched bytes | bytes delta | baseline instr | patched instr | instr delta | baseline stack | patched stack | baseline mem | patched mem |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `0` | `11905` | `5546` | `-6359` | `2757` | `1222` | `-1535` | `220` | `16` | `935` | `438` |
| `1` | `7887` | `4590` | `-3297` | `1738` | `985` | `-753` | `122` | `24` | `699` | `384` |
| `2` | `11072` | `8179` | `-2893` | `2392` | `1749` | `-643` | `190` | `112` | `1027` | `825` |
| `3` | `21723` | `19197` | `-2526` | `4352` | `3834` | `-518` | `788` | `680` | `2111` | `1840` |
| total | `52587` | `37512` | `-15075` | `11239` | `7790` | `-3449` | `1320` | `832` | `4772` | `3487` |

总计：

- symbol bytes：`-28.67%`；
- static instructions：`-30.69%`；
- stack operands：`-36.97%`；
- memory operands：`-26.93%`。

机器码变化与 runtime `-35.22%` 同向，说明优化掉的不是无关源码，而是 hot path 上真实执行的指令。

## 6. 和 GSIM 差距的含义

本 probe 后，low-only GrhSIM 从约 `203ms` 降到 `132ms`。对照 [NO0234](./NO0234_vtypebuffer_phase_specific_gsim_delta_20260709.md) 中 GSIM `subStep1` input-only `~53ms`，即使删除 compute propagation 后仍约 `2.5x`。

因此当前差距可拆成两层：

1. **第一层：active/change propagation 框架成本**  
   NO0239 证明该层可贡献约三分之一的 input-low 时间；
2. **第二层：剩余 slot/ref 和 supernode 内代码形态成本**  
   patched 后 compute0-3 仍有 `7790` 条静态指令，而 GSIM `subStep1()` 约 `2788` 条（见 NO0237），仍约 `2.8x`。

也就是说，“去掉 always-active 下的 compute propagation”是必要但不充分的优化。

## 7. 下一步建议

可工程化方向不是直接保留本 probe，而是做语义受控的 phase-specialized codegen：

1. **input-change full-pass specialization**：当直接输入变化导致 compute DAG 近似全量 active 时，走 topological full-pass 版本；
2. **只 suppress compute-target propagation**：full-pass 中 downstream compute 已确定会执行，可以跳过 compute->compute `any_changed`/active OR；但 commit/output/high phase 需要的变化仍要保留；
3. **保留正常 event-driven path**：clock-high、稀疏变化、小负载仍使用原 path，避免破坏稀疏场景；
4. **继续压 slot/ref**：即使 no-propagate 后仍显著慢于 GSIM，需要进一步减少 `value_*_slots_` / storage-ref load-store 和大 supernode 内 live range。

本轮实验把 NO0238 的归因向前推进了一步：**GrhSIM 的 always-active input-low 场景确实可以通过删除 compute active/change propagation 获得大幅收益，但剩余瓶颈仍在 slot/ref 代码形态。**
