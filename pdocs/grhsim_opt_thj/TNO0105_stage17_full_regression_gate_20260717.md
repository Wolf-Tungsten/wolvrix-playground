# TNO0105 Stage 17 full regression gate

记录日期：2026-07-17

状态：Stage 17 targeted-direct 完整回归完成。full build PASS，串行 CTest `46/48`；失败集合仍只有历史 `transform-comb-lane-pack` 与 `transform-repcut`，没有新增失败。focused emitter/memory-fill、activity-schedule、Python/native binding 和 XS sparse-option 测试全部通过。实现与静态/功能结果见 [TNO0103](./TNO0103_stage17_targeted_direct_implementation_static_and_functional_gate_20260717.md)，严格 N0 runtime 与默认决策见 [TNO0104](./TNO0104_stage17_targeted_direct_n0_strict_runtime_and_default_decision_20260717.md)。

## 1. 完整 build

所有命令均先执行：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
```

随后运行：

```bash
cmake --build wolvrix/build -j2
```

结果为 PASS，耗时 `7.41s`。日志：

```text
build/logs/xs/stage17_full_regression_20260717/build_all_j2.log
```

源码 mtime 均早于对应 build/binary，确认回归覆盖当前 Stage 17 源码，而不是陈旧产物。

## 2. 串行 CTest

为避免 emitter 长测并发造成额外内存压力，使用串行口径：

```bash
ctest --test-dir wolvrix/build -j1 --output-on-failure
```

结果：

```text
46/48 PASS
total time = 387.77s
```

两个失败为：

| test | 失败摘要 | 判定 |
| --- | --- | --- |
| `transform-comb-lane-pack` | `Expected one packed kAnd...` | Stage 11..16 已存在 |
| `transform-repcut` | `expected repcut partition static feature export` | Stage 11..16 已存在 |

activity-schedule 与 `emit-grhsim-cpp` 长测均通过；后者耗时 `293.83s`。失败集合、错误文本和数量均未扩大，因此 Stage 17 没有新增完整回归失败。完整日志：

```text
build/logs/xs/stage17_full_regression_20260717/ctest_serial_j1.log
```

## 3. Focused gate

在完整 CTest 后又单独重跑与本轮改动直接相关的 focused gate：

| gate | 结果 | 耗时 |
| --- | --- | ---: |
| active-mask focused emitter + memory-fill | `2/2 PASS` | `297.71s`（`292.93s + 4.77s`） |
| activity-schedule | `1/1 PASS` | `0.15s` |
| pybind emitter options | `7/7 PASS` | `0.08s` |
| XS GrhSIM options | `10/10 PASS` | `0.12s` |
| Python syntax compile | PASS | `0.08s` |

对应日志：

```text
build/logs/xs/stage17_full_regression_20260717/focused_emit_grhsim_cpp.log
build/logs/xs/stage17_full_regression_20260717/focused_activity_schedule.log
build/logs/xs/stage17_full_regression_20260717/focused_pybind_options.log
build/logs/xs/stage17_full_regression_20260717/focused_xs_options.log
build/logs/xs/stage17_full_regression_20260717/py_compile.log
```

focused emitter 覆盖 native default/explicit-off/probe identity、`targeted-direct` serial/parallel/environment identity、selected mask 与 write-count 对账、31-entry direct/32-entry table 边界以及非法 policy。Python/XS gate 同时确认 C++ 是唯一默认源：未设置 XS 高层环境变量时不注入 attribute，只有显式实验值才形成 sparse override。

## 4. 阶段结论

Stage 17 的实现、production source、O3、100/10k/50k 功能、严格 N0 50k 与完整回归均已闭合。代码本身可以作为默认关闭的实验入口保留，但 N0 cycles 合并仅 `-0.031601%`，ABBA/BAAB 方向反转，不能支持默认启用。因此最终状态保持：

```text
C++ activeMaskGapPackPolicy default = off
XS implicit override                = none
explicit experiment                = targeted-direct
```

N1 仍应在外部负载消失后按相同 page-local whole-node gate 补测，但它不阻止当前“中性、保持 off”的阶段结论与提交。
