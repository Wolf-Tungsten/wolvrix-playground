# TNO0101 Stage 16 full regression gate

记录日期：2026-07-17

状态：Stage 16 emitter-local active-mask gap-pack no-mutation probe 完成 full build 与串行 CTest。full build PASS，CTest `46/48`、总 real time `387.10s`；`emit-grhsim-cpp` 长测、memory-fill、activity-schedule 和全部 ingest tests 均通过。仅保留与 [TNO0096](./TNO0096_stage15_full_regression_gate_20260717.md) 相同的 comb-lane-pack/repcut 两项既有失败及相同诊断文本，没有新增回归。

## 1. Full build

所有命令先加载仓库环境。执行：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
cmake --build wolvrix/build -j2
```

full build 正常完成并返回 PASS。core library、CLI 以及 emit/transform/ingest test executables 均成功编译或重链；Stage 16 直接修改的 `emit-grhsim-cpp` target 正常生成。

## 2. 串行 CTest

执行：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
ctest --test-dir wolvrix/build --output-on-failure
```

结果为：

```text
total                 48
passed                46
failed                 2
pass rate             96%
total real time       387.10 sec
```

Stage 16 直接路径和高风险共享路径均通过：

| Test | Result | Time |
| --- | --- | ---: |
| `emit-grhsim-cpp` | PASS | `293.06 sec` |
| `emit-grhsim-cpp-memory-fill` | PASS | `4.84 sec` |
| `transform-activity-schedule` | PASS | `0.14 sec` |

全部 ingest tests 通过，包括 symbol/type、statement lowering、write-back、memory-port lowering 与 graph-assembly 系列。其余基础 GRH/store/emit 和未列出的 transform suites 除第 3 节两项已知失败外均通过。

## 3. 既有失败集合

仅失败：

```text
transform-comb-lane-pack
Expected one packed kAnd for storage frontier rewrite

transform-repcut
expected repcut partition static feature export
```

两个 test 名和诊断文本均与 [TNO0096](./TNO0096_stage15_full_regression_gate_20260717.md) 及其列出的 Stage 11..14 历史结果完全一致；通过数仍为 `46/48`，失败集合没有扩大。Stage 16 只新增 default-off probe/planner/validator 与 sparse option plumbing，没有修改 comb-lane-pack 或 repcut，因此本轮判定为 `no new failure`。

## 4. Stage 16 闭环

[TNO0100](./TNO0100_stage16_active_mask_gap_probe_implementation_and_production_result_20260717.md) 已闭合以下门禁：

- C++ native default `off` 与 attribute/low-env/default 优先级；
- Python `None` 省略、XS sparse override 与配置 source 日志；
- planner/独立 validator/self-test、parallel-safe aggregation 与 focused tests；
- default、explicit-off、probe 的 157-file/155-source byte identity；
- production non-table `653,299 -> 623,294` 与 table gap-only `19,942 -> 17,530` 的分类结果。

本文补齐 full build/CTest 后，Stage 16 no-mutation probe 的实现、production identity 与提交前 regression gate 均已闭合。完整回归不会改变 TNO0100 的性能边界：probe 没有生成 candidate source，所以本阶段不运行无差异 O3/SimTop；下一阶段仍只先实现 non-table direct targeted encoding，table 在 runtime category evidence 前保持不变。

失败列表由构建树生成在：

```text
wolvrix/build/Testing/Temporary/LastTestsFailed.log
```

该 build artifact 不纳入提交。

## 5. 增量更新 2026-07-17：CTest 后 focused 环境路径确认

在上述 full CTest 完成后，仅对 `tests/emit/test_emit_grhsim_cpp.cpp` 增加一条 low-level environment path 的 focused 覆盖；没有修改 `lib/`、binding、XS 脚本或任何 production lowering。新增 run 明确执行：

```text
WOLVRIX_GRHSIM_ACTIVE_MASK_GAP_PACK_POLICY=probe
emitter attribute                               absent
emit parallelism                               2
```

它从环境解析 `probe` 并走完完整 emitter path。测试将该 run 同显式 attribute `probe` 的 serial (`parallelism=1`) 与 parallel (`parallelism=4`) 两条 control 比较，结果为：

- 三者全部 generated artifacts byte-exact；
- 三者完整 probe 日志只归一化非确定的 `elapsed_us` 数值后 byte-exact；
- low-level environment path 没有改变 session state，也没有把 probe 日志写入 artifact；
- 环境变量在 run 后清理，不污染后续非法环境值与其它 emitter tests。

增量完成后重新执行：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
cmake --build wolvrix/build --target emit-grhsim-cpp -j2
WOLVRIX_TEST_ACTIVE_MASK_GAP_PACK=1 wolvrix/build/bin/emit-grhsim-cpp
git -C wolvrix diff --check
git diff --check
```

target rebuild 与 focused executable 均 PASS，子模块和父仓两层 `diff --check` 均 PASS。这补齐了 [TNO0100](./TNO0100_stage16_active_mask_gap_probe_implementation_and_production_result_20260717.md) 所述 `attribute > low env > C++ default` 中 low-env `probe` 的真实完整 emitter 入口，而不仅是 option parser/plumbing 单测。

本次是 test-only 增量，不改变已经由本轮 `46/48` CTest 覆盖的 library/production binary。新增行为又由对应 focused executable 精确命中，因此没有为这一条测试断言重复运行 `387.10s` 的全量 CTest；第 2、3 节的 full-regression 结果与 `no new failure` 结论保持不变。

## 6. 勘误 2026-07-17：full build 与 CTest 的实际命令

第 1 节命令块把 full build 并行度误写为 `-j2`，第 2 节命令块漏写了串行 CTest 的 `-j1`。保留原文作为最初记录，本轮实际执行命令应以以下勘误为准：

```bash
source /nfs/home/tanghaojin/wolvrix-playground-gsim-calibrate-2/env.sh
cmake --build wolvrix/build -j4
ctest --test-dir wolvrix/build --output-on-failure -j1
```

因此本文所称“串行 CTest”确实由显式 `-j1` 保证；`46/48`、`387.10s`、三个关键测试时长和既有失败集合均来自这条实际命令，不受命令文本勘误影响。第 5 节 CTest 后的 focused target rebuild 则确实使用 `--target emit-grhsim-cpp -j2`，无需修正。
