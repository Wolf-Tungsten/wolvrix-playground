# NO0032 GrhSIM Single Value Storage State-Anchor 50k Snapshot（2026-04-27）

> 归档编号：`NO0032`。目录顺序见 [`README.md`](./README.md)。

这份记录固化 `NO0031` 落地后的当前可用版本：`register/latch state` 已并入 `value_logic_storage_`，同时保留“`state` 布局稳定、`value` 按关联 `state anchor` 重排”的策略，用 XiangShan `coremark 50k` 结果确认这一版的运行收益。

本轮结论先写在前面：

- `single value storage` 路线已经可以稳定运行 `coremark 50k`
- 当前保留的布局策略是：`state` 保持稳定布局，`value` 只按 `max state anchor + first read sequence` 重排
- 本轮 `50k` 结果为 **`86.19 cycles/s`**
- 相比本周前两轮单数组实验：
  - 相比 `single storage` 初版的 `77.18 cycles/s`，提升约 **`10.46%`**
  - 相比 `refalias cleanup` 后的 `75.08 cycles/s`，提升约 **`12.89%`**
- 但相对旧基线 [`NO0011`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md) 的 `89.17 cycles/s`，当前仍慢约 **`3.34%`**

## 数据来源

- 本轮 `emu` build 日志：
  - `build/logs/xs/xs_wolf_grhsim_build_20260427_155449.log`
- 本轮 `50k` 运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260427_50k_layout_anchor.log`
- 本轮布局观察对应的生成文件：
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_53.cpp`
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_931.cpp`
- 对比日志：
  - `build/logs/xs/xs_wolf_grhsim_20260427_single_storage_50k.log`
  - `build/logs/xs/xs_wolf_grhsim_20260427_refalias_50k.log`

## 1. 当前实现口径

当前版本的关键点如下：

- `state_reg_*` / `state_latch_*` 已删除，非 memory state 与 logic value 共用 `value_logic_storage_`
- batch 内重复的 `grhsim_value_*_ref(...)` 已收敛为局部 alias，减少源码与 LLVM IR 膨胀
- 最终保留的 layout 策略不是“按纯读顺序排 value”，也不是“把 state/value 一起按首次访问混排”
- 当前策略是：
  - `state` 保持 emit 阶段建立好的稳定布局
  - `value` 根据其关联到的 `max state anchor` 排序
  - 同 anchor 内再按 `first read sequence` 和 `totalReads` 排序

这条策略对应的目标不是追求绝对最小 gap，而是避免：

- `sched_53` 这类大批次被“首次访问顺序”推到很远的 value 尾部
- `sched_931` 这类局部热点重新被宽范围 value 打散

## 2. 执行命令

本轮先重建最新 `grhsim emu`：

```bash
make -j4 xs_wolf_grhsim_emu
```

然后单独运行 `50k`：

```bash
make run_xs_wolf_grhsim_emu \
  XS_SIM_MAX_CYCLE=50000 \
  RUN_ID=20260427_50k_layout_anchor
```

## 3. 50k 结果

运行日志末尾关键结果如下：

| 指标 | 数值 |
| --- | ---: |
| `instrCnt` | `73580` |
| `cycleCnt` | `49996` |
| `guest cycle spent` | `50001` |
| `IPC` | `1.471718` |
| `Host time spent` | `580054 ms` |
| `host simulation speed` | **`86.191975 cycles/s`** |

其中：

```text
cycles_per_s = 49996 / 580.054s = 86.191975
```

本轮功能口径正常：

- 正常推进到 `50000-cycle` 上限
- 无 diff mismatch
- 无 crash
- 与前几轮同样停在 `EXCEEDING CYCLE/INSTR LIMIT`

## 4. 与本周两轮单数组实验对比

### 4.1 对比 `single storage` 初版

初版结果来自：

- `build/logs/xs/xs_wolf_grhsim_20260427_single_storage_50k.log`

对应数据：

| 版本 | Host time | cycles/s |
| --- | ---: | ---: |
| `single storage` 初版 | `647809 ms` | `77.18` |
| 当前 `state-anchor` 版本 | `580054 ms` | `86.19` |

变化：

- `Host time` 缩短 `67755 ms`
- `cycles/s` 提升约 **`10.46%`**

### 4.2 对比 `refalias cleanup` 后版本

对比结果来自：

- `build/logs/xs/xs_wolf_grhsim_20260427_refalias_50k.log`

对应数据：

| 版本 | Host time | cycles/s |
| --- | ---: | ---: |
| `refalias cleanup` | `665912 ms` | `75.08` |
| 当前 `state-anchor` 版本 | `580054 ms` | `86.19` |

变化：

- `Host time` 缩短 `85858 ms`
- `cycles/s` 提升约 **`12.89%`**

### 4.3 对比旧基线 `NO0011`

旧基线 [`NO0011`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md)：

| 版本 | Host time | cycles/s |
| --- | ---: | ---: |
| `NO0011` baseline | `560738 ms` | `89.17` |
| 当前 `state-anchor` 版本 | `580054 ms` | `86.19` |

变化：

- `Host time` 仍多 `19316 ms`
- `cycles/s` 仍低约 **`3.34%`**

因此，这次优化已经把单数组路线从 `75 ~ 77 cycles/s` 拉回到了 `86+ cycles/s`，但还没有超过 `NO0011` 的旧高点。

## 5. 当前布局快照

本轮最关键的两个观测 batch：

### 5.1 `sched_53`

- `state` offset：`1430456 .. 1481136`
- `value` offset：`2466576 .. 2519936`
- 中位 gap 约：`1037680 bytes`

生成代码开头可见访问形态：

- `grhsim_state_slot_1430456`
- `grhsim_value_slot_2466576`

它仍不是完全相邻，但已经明显好于失败实验里出现的：

- `value 4566008 .. 4619368`
- `value 7367624 .. 7420984`

### 5.2 `sched_931`

- `state` offset：`1257636 .. 1269432`
- `value` offset：`1527440 .. 1814808`
- 中位 gap 约：`277014 bytes`

这说明当前策略至少把一部分“局部热点批次”重新拉回了接近对应 state 区域的位置，而没有继续漂到几 MB 外。

## 6. 失败路线记录

为了避免后续重复走回头路，这里顺手记下两条本轮已经验证为负收益的路线：

- `value` 按 `firstBatch / pure read order` 排序
  - `sched_53` 会被推到 `7.3MB+` 的远端区域
  - 运行侧明显回退
- `state` 和 `value` 一起按“首次访问”混排
  - 长生命周期热 state 会被整体前移
  - 当前批次首次出现的 value 反而继续远离对应 state
  - `sched_53` 同样会恶化到 `7.3MB+`

因此当前文档记录的 `state-anchor` 策略，不是拍脑袋选的，而是和上述失败实验比较后保留下来的局部最优版本。

## 7. 结论

当前 `single value storage` 路线已经得到一份可复现的 `50k` 性能快照：

- 功能正确
- 运行速度为 **`86.19 cycles/s`**
- 明显优于本周前两轮单数组实验
- 当前最合理的布局策略是：
  - **保持 `state` 布局稳定**
  - **只重排 `value`**
  - **以 `max state anchor` 为主键**

如果后续继续优化，这份文档应作为单数组路线的新对照点，而不是再回退到 `75 ~ 77 cycles/s` 的早期版本重新比较。
