# TNO0088 Stage 13 full regression gate

记录日期：2026-07-16

状态：Stage 13 canonical commit locality group/order 与 emitter 防御修复完成完整 rebuild 和串行 CTest。`cmake --build` PASS，CTest `46/48`；activity-schedule 和 GrhSIM emitter 长测均通过，仅保留与 Stage 11/12 完全相同的两个既有失败，没有新增回归。

## 1. 完整 rebuild

所有命令先加载仓库环境，执行：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
cmake --build wolvrix/build -j2
```

完整 build exit `0`，到达 `100%`。核心 library、CLI、全部 emit/transform/ingest test executable 均完成编译或重链；Stage 13 直接相关的 `emit-grhsim-cpp` 与 `transform-activity-schedule` target 均成功生成。

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
total real time       389.56 sec
```

Stage 13 直接修改与高风险共享路径：

| Test | Result | Time |
| --- | --- | ---: |
| `emit-grhsim-cpp` | PASS | `294.93 sec` |
| `transform-activity-schedule` | PASS | `0.13 sec` |
| `emit-grhsim-cpp-memory-fill` | PASS | `4.87 sec` |

全部 ingest、基础 GRH/store/emit 及其余 transform suites 通过。

## 3. 既有失败对照

仅失败：

```text
transform-comb-lane-pack
Expected one packed kAnd for storage frontier rewrite

transform-repcut
expected repcut partition static feature export
```

[TNO0077](./TNO0077_stage11_equal_load_swap_probe_full_regression_gate_20260716.md) 和 [TNO0082](./TNO0082_stage12_commit_guard_merge_cap_full_regression_gate_20260716.md) 已记录相同的两个 test、相同诊断文本和 `46/48` 结果。Stage 13 没有修改 comb-lane-pack 或 repcut 行为，失败集合也没有扩大，因此判定为 `no new failure`。

## 4. 阶段结论

结合 [TNO0086](./TNO0086_stage13_canonical_commit_order_full_gate_20260716.md) 的 focused tests、default source identity、四档 production slot gate、O3 和功能门禁，本轮完整回归进一步确认：

- canonical commit locality group/order 没有破坏 transform 共享路径；
- malformed/high-group metadata 的 legacy fallback 没有破坏 emitter 长路径；
- Stage 13 correctness/build/regression 门禁均已闭合；
- page-local 50k runtime 仍按独立记录裁决，本次 CTest 不产生性能结论。

完整日志：

```text
build/logs/xs/stage13_full_build_20260716.log
build/logs/xs/stage13_full_ctest_20260716.log
```
