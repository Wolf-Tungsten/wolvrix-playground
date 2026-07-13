# TNO0013 Scalar-read locality machine gate

记录日期：2026-07-13

来源范围：`NO0389..NO0402`，原始记录见 [NO0389](../grhsim_opt/NO0389_materialized_scalar_read_locality_diagnostic_plan_20260712.md) 至 [NO0402](../grhsim_opt/NO0402_production_scalar_load_realization_gate_20260712.md)。

状态：source/dynamic 上界显著，但 O3 已消除大部分重复 load；typed-local 实现按门槛停止。

## 1. Source-level signal

fresh direct-state schedule 的 locality TSV 有 1,773,611 rows，其中 377,895 为 repeated scalar-read candidates。静态理论 saved/all touches 为 `35.38%`。

必须注意：direct frontier 改变后，schedule ID 相同不代表 fire 相同。为此重新构建 profile-enabled direct emu并跑 50k：

```text
63,726 static/fire keys 全匹配
compute fire 相对 baseline -2.047%
commit fire 不变
```

用 direct 自身 fire 加权后，saved/all scalar touches 仍为 `32.823%`；compute62 为 `41.883%`，compute1 为 0。source gate 明显超过 10%。

## 2. Machine-code realization

66 个 production compute objects 仅增加 line table 重编，`.text` SHA 66/66 完全相同。随后按基本块双侧规则将 slot displacement memory operands 映射回 supernode。

结果：

```text
dynamic machine redundant / source upper  9.573%
machine redundant / direct compute instructions 0.688%
含 ambiguous + non-candidate 的压力上界      0.840%
```

Clang 的 CSE、寄存器分配与 caller fusion 已消掉约九成 source-level repeated touches。

## 3. 工程结论

本阶段最重要的经验是不能用 generated C++ 触碰次数直接预测性能：

- source weighted 上界 `32.8%`；
- 真实可删 machine instructions 仅 `0.688%`；
- 没有达到 direct compute 1% 的预声明门槛。

因此不实现 typed-local copy，也不继续围绕 scalar repeated reads 做 emitter 复杂化。主线回到 compute1 的通用 payload、changed/activation 与 dispatch 归因。

## 4. 规则审计与关键数据

记录类型：typed-local 候选的 source-to-machine 可实现性 gate。单一议题边界是“generated C++ 中重复 scalar reads 在 production O3 机器码里还剩多少可删工作”。本篇没有候选 runtime A/B/A；用 host walltime 推导提速会违反本 gate 的证据边界。

Direct runtime-profile 50k 达到 guest/cycleCnt/instr/PC=`50001/49996/73580/0x80001312`，`63,726` static/fire keys 全匹配。该插桩 run 只用于 fire 加权，不使用 host time：

| Level | Count / ratio |
| --- | ---: |
| Locality TSV rows | 1,773,611 |
| Source candidates | 377,895 |
| Source weighted saved/all touches | `32.823%` |
| Audited dynamic machine redundant | 962,028,206 |
| Machine / source-saved | `9.573%` |
| Machine / direct compute instructions | `0.688%` |
| 极端保守压力上界 / direct compute | `0.840%` |

66/66 line-table O3 objects 的 `.text` SHA 与 production 完全相同，说明统计映射没有改变执行代码。`311,381/377,895` candidates 在机器码中只剩 0 或 1 次目标访存，是 source 上界坍缩的直接原因。详见 [NO0399](../grhsim_opt/NO0399_direct_scalar_locality_runtime_profile_50k_gate_20260712.md)、[NO0400](../grhsim_opt/NO0400_direct_scalar_read_locality_dynamic_gate_20260712.md) 与 [NO0402](../grhsim_opt/NO0402_production_scalar_load_realization_gate_20260712.md)。
