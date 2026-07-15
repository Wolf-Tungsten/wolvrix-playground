# TNO0067 Stage 9 fanin probe full regression gate

日期：2026-07-16

状态：Stage 9 off/probe 完整 rebuild 与全量 CTest 闭合；默认 off 的 emitter/ingest 路径无新增失败，probe 阶段可提交。

## 1. 完整 rebuild

新增 `ActivityScheduleOptions` 字段后执行：

```text
cmake --build wolvrix/build -j8
```

全部 library、CLI、emitter、transform 与 ingest test executable 重编/重链成功，exit `0`。这避免只重建 focused target 时旧测试可执行文件持有过时 options 布局。

## 2. 全量 CTest

```text
ctest --test-dir wolvrix/build --output-on-failure
46/48 PASS
total=388.02s
```

Stage 9 直接相关和共享路径：

- `transform-activity-schedule` PASS，`0.03s`；
- `emit-grhsim-cpp` PASS，`293.80s`；
- `emit-grhsim-cpp-memory-fill` PASS，`4.92s`；
- aggregate-port-slice、其余 ingest/transform/emitter 用例均 PASS。

仅两项既有失败，签名与 Stage 8 相同：

```text
transform-comb-lane-pack:
Expected one packed kAnd for storage frontier rewrite

transform-repcut:
expected repcut partition static feature export
```

没有新增 failure。结合 [TNO0066](./TNO0066_stage9_fanin_probe_implementation_and_simtop_result_20260716.md) 的 default/off/probe raw identity、focused exactness 和 production probe，本阶段 correctness gate 闭合。

## 3. 提交与下一步

按子模块优先提交 Stage 9 probe 实现与 tests；父仓库随后提交 pointer、XS config plumbing、TNO0065..TNO0067 与 README。strict pullback 单独进入下一阶段，不混入 probe commit。
