# NO0515 Sparse-batch pure-event predicate implementation gate

日期：2026-07-13

## 1. Implementation

承接 [NO0514](./NO0514_sparse_batch_pure_event_predicate_implementation_plan_20260713.md)，子仓库提交
`0c37785`（`perf: stabilize sparse pure event word codegen`）已实现无 batch-id 的 threshold-2 输出策略：

- 只在既有、默认关闭的 `pure_event_compute_word_bypass=1` 路径统计当前 batch 的 eligible pure-event words；
- eligible count 为 `1..2` 时，每个 wrapper 共享一个 `const volatile bool grhsim_pure_event_word_hit_*`；
- eligible count 大于 `2` 时继续直接使用 exact event equality，不增加 temporary；
- split helper word 继续按 `word.helperChunks.empty()` 排除，profile-only/default/bypass=0 的输出语义不变；
- profile+bypass 在 sparse batch 中由 counter 与 wrapper 读取同一个 volatile hit，dense batch 仍读取原 `const bool` hit。

阈值是 emitter 内部常量，只依赖当前 `ScheduleBatch` 的 production eligibility 判定，不引用 SimTop batch 编号、active-word
编号或离线 object 统计。

## 2. Synthetic boundary closure

测试夹具新增强制同批次的 1/2/3-word 边界，生成物独立复核结果为：

| fixture | eligible wrappers | volatile hits | direct outer predicates |
| --- | ---: | ---: | ---: |
| `sparse_one` | 1 | 1 | 0 |
| `sparse_two` | 2 | 2 | 0 |
| `dense_three` | 3 | 0 | 3 |

现有 homogeneous/profile+bypass hit/miss harness、default/explicit-zero byte identity，以及 multi-event、once-only、commit、
fullpass、full-active-word-consume 等负向门禁继续由同一测试覆盖。

## 3. Regression results

在仓库环境中执行：

```text
source env.sh && cmake --build wolvrix/build --target emit-grhsim-cpp -j8
source env.sh && ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp$' --output-on-failure
source env.sh && cmake --build wolvrix/build --target emit-grhsim-cpp-memory-fill -j8
source env.sh && ctest --test-dir wolvrix/build -R '^emit-grhsim-cpp-memory-fill$' --output-on-failure
```

结果：

- `emit-grhsim-cpp`: PASS，`278.30s`；
- `emit-grhsim-cpp-memory-fill`: PASS，`5.61s`；
- `git diff --check`: PASS。

## 4. Gate decision

实现与 synthetic boundary gate 通过，可以进入 fresh SimTop source gate。下一阶段必须从相同 checkpoint/config 重新 emit，确认
production source 精确得到 `14` 个 sparse batches、`20` 个 volatile words、`87` 个 direct wrappers，并保持 schedule/direct-read
identity；本文不把 synthetic 结果外推为 SimTop build、功能或 runtime 结论。
