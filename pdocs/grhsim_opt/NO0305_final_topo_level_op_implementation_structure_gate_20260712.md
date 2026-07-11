# NO0305 Final-topo level-op implementation and strict structure gate

日期：2026-07-12

## 1. 实现

承接 [NO0304](./NO0304_final_topo_stable_tiebreak_plan_20260712.md)，activity-schedule 新增可回退的
`finalTopoPolicy`：

- `level-id` 保持原行为，在完整 Kahn layer 内按临时 supernode ID 排序；
- `level-op` 保持完全相同的 layer，只在层内按 supernode 的最小 `OperationId.index` 排序，再以
  supernode ID 打破相同 key。

默认仍为 `level-id`。pass pipeline、Python binding 和 XiangShan 脚本分别支持
`-final-topo-policy`、`final_topo_policy` 与：

```text
WOLVRIX_XS_GRHSIM_FINAL_TOPO_POLICY=level-op
```

单测在同一 graph 上分别运行两种 policy，并要求 supernode/op map、DAG、value fanout、supernode kind、
compute-node map 与 summary stats 完全一致；另外重建每个 Kahn layer，逐层验证 `level-op` 的最小 op ID
顺序。

## 2. 严格 baseline 开关

为了用当前二进制从同一 pre-reg-to-mem checkpoint 重建 NO0286 lowering，reg-to-mem 增加独立的
`enableDecodedWriteStorage` 开关。默认保持启用，关闭时只禁止 write-only decoded storage discovery，
不影响其他 true-merge group。XiangShan 环境变量为：

```text
WOLVRIX_XS_GRHSIM_REG_TO_MEM_DECODED_WRITE_STORAGE=0
```

synthetic gate 证明关闭后原设计仍保留 4 个 register、4 个 read port 和 4 个 write port，不产生 memory。

## 3. 配置口径勘验

从固定 checkpoint：

```text
build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
```

恢复时先后拦截了两种不完整配置：

| 配置 | 结果 | 判定 |
| --- | --- | --- |
| 仅 `ordered_writes=0` | decoded-write group 仍进入 explicit-conflict lowering，恢复为 NO0290 一类约 918 万 op 图 | 无效基线，终止生成 |
| 仅 `decoded_write_storage=0` | `7,191,761` graph ops、`67,881` supernodes | 既有 true-merge group 仍可使用 ordered lowering，不是 NO0286 |
| 两项同时为 `0` | 下表全部结构计数与 NO0286 一致 | 严格基线通过 |

因此“关闭 ordered-write 优化”的准确口径必须同时关闭 discovery 和 lowering，不能只根据单一环境变量
命名推断。两次不完整配置不进入后续 overlap、功能或 runtime 结论。

## 4. SimTop 同图门禁

严格配置为：

```text
WOLVRIX_XS_GRHSIM_FINAL_TOPO_POLICY=level-op
WOLVRIX_XS_GRHSIM_REG_TO_MEM_DECODED_WRITE_STORAGE=0
WOLVRIX_XS_GRHSIM_REG_TO_MEM_ORDERED_WRITES=0
```

`level-op` 结果与保留的 NO0286 `level-id` 结构逐项一致：

| Metric | NO0286 `level-id` | strict `level-op` |
| --- | ---: | ---: |
| graph ops | `7,196,059` | `7,196,059` |
| eligible ops | `6,982,222` | `6,982,222` |
| source clones | `2,044,602` | `2,044,602` |
| compute / commit supernodes | `67,449 / 485` | `67,449 / 485` |
| DAG edges | `638,649` | `638,649` |
| boundary values | `1,162,161` | `1,162,161` |
| boundary activation edges | `2,261,833` | `2,261,833` |
| compute-compute / compute-commit pairs | `2,003,556 / 258,277` | `2,003,556 / 258,277` |
| commit ops max | `42,937` | `42,937` |

这证明 policy 没有修改 partition、supernode membership、DAG 或 activation，只改变最终编号与其派生布局。
fresh C++ emit 正常结束，总耗时约 `305.6 s`，其中 C++ emit 约 `61.2 s`。

## 5. 回归

```text
cmake --build wolvrix/build -j32
ctest --test-dir wolvrix/build \
  -R '^(transform-reg-to-mem|transform-activity-schedule|transform-pass-manager)$' \
  --output-on-failure
python3 -m py_compile scripts/wolvrix_xs_grhsim.py wolvrix/app/pybind/wolvrix/__init__.py
```

构建通过，三项定向 CTest `3/3` 通过，Python 语法检查通过。

## 6. 产物与下一步

```text
build/xs_grhsim_no0305_level_op_strict_no0286_20260712/grhsim/grhsim_emit
build/logs/xs/xs_wolf_grhsim_build_no0305_level_op_strict_no0286_emit_20260712.log
```

下一步从同一 checkpoint 生成 ordered-write enabled 的 `level-op`，将 strict/ordered 的共同 op batch overlap
与 NO0303 的 `level-id` overlap 对照。只有 overlap 证明确有改善后，才编译 ordered `level-op` emu 并进入
10k/50k 功能与固定 CPU runtime gate。
