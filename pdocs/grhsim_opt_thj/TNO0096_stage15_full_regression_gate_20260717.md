# TNO0096 Stage 15 full regression gate

记录日期：2026-07-17

状态：Stage 15 final sibling fusion no-mutation probe 完成完整 rebuild 与串行 CTest。`cmake --build` PASS，CTest `46/48`；`emit-grhsim-cpp` 长测、`transform-activity-schedule` 和 memory-fill 均通过，仅保留与 Stage 11..14 相同的 comb-lane-pack/repcut 两项既有失败，没有新增回归。

## 1. 完整 rebuild

在仓库环境中执行：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
cmake --build wolvrix/build -j2
```

完整 build 到达 `100%` 并正常退出。core library、CLI 及全部 emit/transform/ingest test executable 均成功编译或重链；Stage 15 直接修改的 activity-schedule transform target 正常生成。

## 2. 串行 CTest

执行：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
ctest --test-dir wolvrix/build --output-on-failure
```

结果：

```text
total                 48
passed                46
failed                 2
pass rate             96%
total real time       389.20 sec
```

Stage 15 直接路径及共享长路径：

| Test | Result | Time |
| --- | --- | ---: |
| `emit-grhsim-cpp` | PASS | `294.25 sec` |
| `transform-activity-schedule` | PASS | `0.14 sec` |
| `emit-grhsim-cpp-memory-fill` | PASS | `4.90 sec` |

其余 ingest、基础 GRH/store/emit 与 transform suites 均通过。

## 3. 既有失败集合

仅失败：

```text
transform-comb-lane-pack
Expected one packed kAnd for storage frontier rewrite

transform-repcut
expected repcut partition static feature export
```

[TNO0077](./TNO0077_stage11_equal_load_swap_probe_full_regression_gate_20260716.md)、[TNO0082](./TNO0082_stage12_commit_guard_merge_cap_full_regression_gate_20260716.md)、[TNO0088](./TNO0088_stage13_full_regression_gate_20260716.md) 与 [TNO0091](./TNO0091_stage14_native_hybrid_default_implementation_and_fresh_gates_20260717.md) 均记录了相同的两个 test、相同诊断文本和 `46/48` 结果。Stage 15 没有扩大失败集合，判定为 `no new failure`。

## 4. Stage 15 闭环

[TNO0095](./TNO0095_stage15_sibling_fusion_probe_implementation_and_production_result_20260717.md) 已闭合 default/probe/Stage14 raw stats identity、focused/Python/XS tests、独立 review 与 production `7,234 -> 7 -> 0` 漏斗；本文补齐其待完成的 full build/CTest。

综合结果：

- C++ default、CLI/Python/XS sparse plumbing 没有破坏共享 transform/emitter 路径；
- state/event/input/unclassified conservative classifier、nearest-pair heap 和 active-ID 日志没有引入测试回归；
- no-mutation probe 的提交前 correctness/build/regression gate 已全部闭合；
- production `exact_eligible=selected=0`、放宽门槛收益上界 `<0.0011%` 的停止决定不变，不创建 strict、CPP/O3 或 SimTop candidate。

CTest 细节保存在构建树的 `wolvrix/build/Testing/Temporary/LastTest.log`；该生成 artifact 不纳入提交。
