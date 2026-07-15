# TNO0073 Stage 10 same-poststats control correction plan

记录日期：2026-07-16

状态：发现 Stage 10 首轮 runtime 的 config-equivalent Stage 7 control 存在生成 provenance/layout 混杂；规划从与 strict 完全相同的 post-stats checkpoint、当前代码生成 explicit-off 控制并重跑跨 NUMA A/B/A。

## 1. 新证据

[TNO0072](./TNO0072_stage10_fanin_pullback_strict_cross_numa_runtime_20260716.md) 使用 Stage 7 fresh rollback 作为 current-default NO0300 控制。其生成配置正确，raw activity stats 也是 canonical baseline，但进一步对比 C++ 后发现：

```text
NO0300 control op comment  _op_1268467 / _op_1268471 / ...
Stage 10 strict op comment _op_1144201 / _op_1144206 / ...
```

这些是 source-clone 后的 operation ID。控制与候选来自不同 fresh/checkpoint 生成轮次，因此 graph/source-clone ID、supernode 内 op order 或最终 code layout 可能同时漂移。首轮 cycles 差异仅为 NUMA0 `-0.0903%`、NUMA1 `+0.7464%`，小于此前已证实的 frontend/layout 敏感范围，不能把全部差异可靠归因给 84 个 strict move。

TNO0072 的原始样本、quiet gate 和“暂不启用默认”决定保持有效；但其 schedule 因果结论降级为待 same-poststats 控制复核。

## 2. Corrected control

新建 explicit-off 输出：

```text
build/xs_activity_stage10_fanin_off_samepost_20260716/grhsim/grhsim_emit
```

它与 strict 使用同一输入：

```text
build/xs_activity_stage8_dp_p050_20260715/grhsim/wolvrix_xs_post_stats.json
```

两边均由当前 `wolvrix` 代码生成；所有参数显式相同，唯一变量为：

```text
A: final_fanin_pullback_policy=off
B: final_fanin_pullback_policy=strict
```

off stats 必须恢复 canonical SHA256 `e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77`；strict 继续为 `133ad4da...`。off 完成 full emit/O3 后，先比较 generated source/object/ELF，确认差异只来自 strict schedule。

## 3. Gate 与判定

- 新 off emu 先过 fixed-ASLR 100/10k 功能门禁；
- NUMA0 和 NUMA1 分别用同一物理 core/sibling 串行 off/strict/off；
- 每次保持 atomic `idle>=99%`、gate gap `<=5s`、五事件 100% scheduled；
- 六个样本均须到达 `50001/49996/73580/0x80001312`；
- 以候选相对两侧 same-poststats off 的算术均值计算 delta。

如果 corrected 结果与 TNO0072 同方向，则升级原结论；如果方向或量级改变，以 corrected same-poststats 结果作为 Stage 10 因果裁决，并单独记录勘误，不改写 TNO0072。

## 4. 后续关系

Stage11 的 batch-stability/更大 BAE 机会诊断可以继续并行，但在 corrected control 完成前，不使用 TNO0072 的 `+0.7464%` 作为候选排序的因果证据，也不据此放宽或否决 fanin family。
