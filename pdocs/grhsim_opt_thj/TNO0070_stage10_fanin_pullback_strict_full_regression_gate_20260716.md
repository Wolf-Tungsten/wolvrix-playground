# TNO0070 Stage 10 fanin pullback strict full regression gate

记录日期：2026-07-16

状态：Stage 10 strict 实现完成全量 build 与 CTest；结果为 `46/48`，没有新增失败。结构阶段满足提交门槛。

## 1. 执行口径

所有命令均先加载仓库 `env.sh`。在 strict 实现和 focused tests 已通过后执行：

```text
cmake --build wolvrix/build -j8
ctest --test-dir wolvrix/build --output-on-failure -j8
```

完整 build PASS，包括 `wolvrix-lib`、所有 emit/transform/ingest 测试目标。

## 2. CTest 结果

```text
total       48
passed      46
failed       2
real time  292.90 s
```

Stage 10 直接相关与高风险路径均通过：

```text
transform-activity-schedule  PASS
emit-grhsim-cpp              PASS (292.89 s)
emit-grhsim-cpp-memory-fill  PASS
ingest-stmt-lowerer          PASS
ingest-memory-port-lowerer   PASS
```

仅保留两个已在 [TNO0067](./TNO0067_stage9_fanin_probe_full_regression_gate_20260716.md) 登记的既有失败：

```text
transform-comb-lane-pack  Expected one packed kAnd for storage frontier rewrite
transform-repcut          expected repcut partition static feature export
```

两项失败与本阶段只修改 activity schedule strict apply/rebuild 和对应测试的范围无关，错误文本也与 Stage 9 完整回归相同。因此结论为 `46/48, no new failure`。

## 3. 决定

strict focused、production exact structure 和 full regression 三层门禁均闭合。按计划提交 `wolvrix` 子模块实现/测试，再提交父仓库 submodule pointer、TNO0068..TNO0070 与 README；后续 full emit/O3、功能和跨 NUMA 50k 另立文档。
