# TNO0053 Stage 6 targeted pure-event pack implementation

日期：2026-07-15

## 1. 实现范围

承接 [TNO0052](./TNO0052_stage6_targeted_pure_event_active_word_pack_plan_20260715.md)，本轮完成默认关闭的 emitter-local pure-event active-word packing：

```text
pure_event_word_pack_policy = off | probe | targeted
pure_event_word_pack_max_moved_supernode_ppm = 5000
pure_event_word_pack_max_changed_word_ppm = 20000
```

`off` 不要求 activity-schedule DAG，且保持旧 `grhsim_emit_stats.json` 字节形态。`probe` 构造并验证 candidate，但不修改发射 source；`targeted` 还要求 `pure_event_compute_word_bypass=true`，否则直接报错。

配置已贯通 C++ emitter、native pybind、Python wrapper 和 `scripts/wolvrix_xs_grhsim.py`。XS 高层 `WOLVRIX_XS_GRHSIM_*` 优先，同时兼容既有低层 `WOLVRIX_GRHSIM_*` pure-event 环境变量；显式空 policy 归一为 `off`，避免 Python/C++ 语义不一致。

## 2. Planner 与 two-pass rebuild

planner 使用 activity-schedule final DAG 重建 Kahn levels，并在 baseline compute/commit batches 上冻结 batch/word slots。只有完整 8-slot、全 compute、同 Kahn level、同 baseline batch 的 word 可参与；commit、partial、cross-level、cross-batch 与已有 production-eligible pure word 保持锁定。

选择和回填与 NO0526 的 targeted 算法一致：

1. exact event expression 分桶；
2. 按当前同-key 节点最多、word index、event key 稳定选择目标 word；
3. 优先保留目标位置中原有同-key 节点，仅回填缺口；
4. key 数量不能整除 8 时，余数节点留给 residual positions，不能要求 remaining nodes 与 target holes 等长；
5. profile sample 不参与决策。

candidate 通过 permutation、全 DAG edge、level/batch movement、commit、existing-pure coverage 和两项 PPM 预算后，`targeted` 才更新 emitter-local topo。旧 baseline model 随即释放，再从空 model 完整执行 `buildModel`；boundary/input/state heads、direct-state frontier 与 memory-row masks 因而全部由新 active IDs 重新生成。

第二遍按第一遍 frozen batch membership 重建 words、op count 与 estimated lines，不重新运行贪心 batch 边界选择。逐 batch 验证 phase、member set、active-word set、op count、estimated lines 和 commit order；最终再用 rebuilt model 的真实 `eligiblePureEventComputeWordExpr` 精确复核 pure-word coverage。

## 3. Stats 与错误合同

非 `off` 模式在 `grhsim_emit_stats.json` 新增 `pure_event_word_pack` 对象，记录 policy/applied/validation、baseline/candidate/added/lost pure words、moved supernodes、changed words、PPM、max displacement、Kahn levels、batch count 和预算。stderr 同时输出一行 compact summary。

非法 policy、缺 DAG、targeted 未开 bypass、malformed numeric、PPM 大于 `1000000`、moved/changed 预算超限均为显式错误，不静默退回默认值，也不部分采用 candidate。

## 4. Focused gates

新增 focused fixtures 覆盖：

- default 与 explicit `off` source/stats 字节一致；
- `probe` source 与 `off` 一致，仅 stats 增加 candidate；
- `targeted` source 增加 bypass words，重复 emit source/stats 完全一致；
- 16-task alternating events：pure words `0 -> 2`、moved supernodes `8`；
- 20-task alternating events（每个 key `10` 个节点）：pure words `0 -> 2`、moved `8`，验证余数不丢失；
- off/targeted 两套 harness 输出一致；
- 两项零预算拒绝、非法 policy、缺 DAG、targeted 无 bypass、numeric malformed/overflow 全部命中预期 diagnostic。

验证结果：

```text
cmake --build wolvrix/build --target emit-grhsim-cpp -j8   PASS
wolvrix/build/bin/emit-grhsim-cpp                          PASS (exit 0)
python py_compile                                           PASS
editable wheel rebuild/install                              PASS
Python wrapper validation                                   PASS
native kwargs parse                                         PASS
git diff --check                                            PASS
```

独立只读 review 未发现新的阻断问题。

## 5. 当前决策

实现和小图 correctness gate 完成，policy 仍默认 `off`。下一步在 current-default NO0300 SimTop graph 上运行 production probe/targeted，首先核对 `107 -> 171`、moved `256`、changed words `127` 是否复现，再决定是否进入 O3 build 与 fixed-ASLR 50k。
