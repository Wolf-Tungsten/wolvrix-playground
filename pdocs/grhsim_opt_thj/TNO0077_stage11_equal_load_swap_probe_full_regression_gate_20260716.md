# TNO0077 Stage 11 equal-load swap probe full regression gate

日期：2026-07-16

状态：Stage 11 完整 rebuild 与全量 CTest 闭合；默认 off、probe 和共享 emitter/ingest 路径无新增失败，阶段可以提交。

## 1. 完整 rebuild

资源上界修复和 editable binding 重装后执行：

```text
cmake --build wolvrix/build -j8
```

全部 library、CLI、emitter、transform 与 ingest test executable 重编/重链成功，exit `0`。

## 2. 全量 CTest

```text
ctest --test-dir wolvrix/build --output-on-failure
46/48 PASS
total=388.73s
```

Stage 11 直接相关和共享长路径：

- `transform-activity-schedule` PASS，`0.03s`；
- `emit-grhsim-cpp` PASS，`292.42s`；
- `emit-grhsim-cpp-memory-fill` PASS，`4.88s`；
- aggregate-port-slice、其余 ingest/transform/emitter 用例均 PASS。

仅两项既有失败，签名与 Stage 9/10 相同：

```text
transform-comb-lane-pack:
Expected one packed kAnd for storage frontier rewrite

transform-repcut:
expected repcut partition static feature export
```

没有新增 failure。结合 [TNO0076](./TNO0076_stage11_equal_load_swap_probe_implementation_and_production_result_20260716.md) 的 no-mutation raw identity、production 完整漏斗和双轮一致性，Stage 11 correctness gate 闭合。

## 3. 提交与后续

按子模块优先提交 Stage 11 probe 实现、tests 与公共 activity-schedule 文档；父仓库随后提交 submodule pointer、TNO0075..TNO0077 与 README。由于 exact eligible 为 `0`，本阶段不创建 strict、full CPP 或 SimTop 50k 候选。

验证日志：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage11_equal_swap_probe_full_build_20260716.log
build/logs/xs/xs_wolf_grhsim_build_activity_stage11_equal_swap_probe_ctest_20260716.log
```
