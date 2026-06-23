# NO0205: reg-to-mem single-user 正确模式固化

日期：2026-06-23

## 结论

当前 XiangShan GrhSIM `reg-to-mem` 的正确默认模式是：

```text
WOLVRIX_XS_GRHSIM_REG_TO_MEM_INTENT 默认开启
anchor discovery 保持单 user 约束
groupAnchors 保持当前 exact-layout grouping + 保守 conflict 过滤
```

不要把共享 `concat` / 共享 `register read` 的组合放进 intent anchor discovery。2026-06-22 的 XiangShan CoreMark 50k 复测显示，恢复单 user 约束后可以跑满 50k cycle limit，未出现 difftest mismatch。

## 默认开关

标准 XiangShan GrhSIM Makefile 流程会调用：

```text
scripts/wolvrix_xs_grhsim.py
```

该脚本当前使用：

```python
reg_to_mem_intent = env_flag("WOLVRIX_XS_GRHSIM_REG_TO_MEM_INTENT", default=True)
```

因此不传额外参数时，`reg-to-mem` intent 默认开启。只有显式设置：

```text
WOLVRIX_XS_GRHSIM_REG_TO_MEM_INTENT=0
```

才会关闭 intent。

## Anchor Discovery 约束

正确模式下，intent anchor 仍然只接受干净的单用户读侧形态：

```text
kRegisterReadPort* -> kConcat -> kSliceArray
```

或可规范化的 dynamic slice：

```text
kRegisterReadPort* -> kConcat -> kSliceDynamic(start = index * sliceWidth)
```

关键约束：

- `concat` 必须是 packed value 的 defining op。
- `concat` result 只能被当前 slice 使用。
- 每个 `register read` result 只能被当前 concat 使用。
- concat operands 必须全部是带 `regSymbol` 的 `kRegisterReadPort`。
- 每个 read value 的 width 必须等于 slice element width。
- 同一 concat 内 read value signedness 必须一致。

也就是 `matchCommonConcatAnchor()` 中的两类 `hasOnlyUser()` 检查是正确性约束，不应为扩大 intent 覆盖率而移除。

## groupAnchors 当前语义

通过 anchor discovery 后，`groupAnchors()` 的当前处理可以保留：

1. 先按 exact layout 分组。

```text
layoutKey = elementWidth + elementCount + register row order
```

只有宽度、行数、寄存器顺序完全一致的 anchors 会合成同一个 `GroupCandidate`。

2. 再处理 storage family。

如果不同 group 之间是连续 subset/superset row layout，且没有共享 read op，当前实现允许它们共享一个 `storageGroup`。这类 group 只保留 intent annotation，不参与 true rewrite。

3. 冲突组保守丢弃。

如果不同 group 共享 register，但不能证明是安全的 storage family，就标为 conflict 并过滤，不打 intent attrs。

4. true merge 只允许无 overlap / 无 shared storage 的 group。

当前 true merge gating 是：

```text
enableTrueMerge && !group.sharesStorage && !group.overlapsOtherCandidate
```

因此 subset/superset view 不会被 rewrite 成 memory，只会作为 intent view 交给 schedule/emit。

## 这次问题的根因判断

导致失败的关键不是 `groupAnchors()` 在干净输入下必然错误，而是此前扩展 anchor group 约束时，放宽了 anchor discovery，把共享中间值也送入后续 grouping：

- 一个 concat result 被多个 slice 使用。
- 一个 register read result 同时喂 concat 和额外普通 user。
- 多个 view 通过共享 read/concat 竞争同一批 register attrs。

这会显著放大候选集合，并让后续 intent attrs / storage family 归属出现覆盖或误归属风险。恢复单 user 后，XiangShan 本次 run 中 conflict group 归零。

## 2026-06-22 验证记录

使用标准 Makefile 流程，不手拼 emu 命令：

```text
make xs_wolf_grhsim_emu RUN_ID=codex_grhsim_singleuser_coremark50k_20260622 XS_SIM_MAX_CYCLE=50000
make run_xs_wolf_grhsim_emu RUN_ID=codex_grhsim_singleuser_coremark50k_20260622 XS_SIM_MAX_CYCLE=50000
```

本次没有依赖额外开启参数；显式传过 `WOLVRIX_XS_GRHSIM_REG_TO_MEM_INTENT=1` 的结果等价于当前默认开启口径。

关键 build log：

```text
build/logs/xs/xs_wolf_grhsim_build_codex_grhsim_singleuser_coremark50k_20260622.log
```

关键 run log：

```text
build/logs/xs/xs_wolf_grhsim_codex_grhsim_singleuser_coremark50k_20260622.log
```

`reg-to-mem` profile：

```text
reg_to_mem_intent=True
candidate_groups=760 groups=760 conflict_groups=0
true_groups=409 true_skipped=351 intent_groups=351
```

CoreMark 50k 结果：

```text
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73580, cycleCnt = 49996, IPC = 1.471718
```

日志中未发现 `ABORT` / `MISMATCH` / `FAIL`。

## 回归要求

后续修改 `reg-to-mem` intent discovery 或 `groupAnchors()` 时，至少保持以下门槛：

- 默认 Makefile 流程中 `reg_to_mem_intent=True`。
- shared concat 不应成为 intent anchor。
- read result 有 extra user 时不应成为 intent anchor。
- shared read subset/sibling view 不应留下 intent attrs。
- XiangShan CoreMark 50k 标准 Makefile 流程跑到 cycle limit，不能出现 difftest mismatch。
- `ctest --test-dir wolvrix/build --output-on-failure -R reg-to-mem` 通过。

## 与 NO0203 的关系

`NO0203` 中“宽松 intent discovery”方向已被本次验证修正：它可以作为未来实验方向，但不能作为当前正确默认模式。当前正确模式以本文为准，即先用单 user discovery 保证候选干净，再让 `groupAnchors()` 在干净候选上做 grouping / conflict 处理。
