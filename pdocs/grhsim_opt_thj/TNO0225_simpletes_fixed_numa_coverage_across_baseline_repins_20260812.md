# TNO0225：SimpleTES 固定 NUMA coverage，支持后续 baseline repin

日期：2026-08-12

## 1. 问题与修复结论

[TNO0224](./TNO0224_simpletes_relative_numa_gate_hot_recovery_20260807.md) 的修复已经消除了“不同大小的
candidate 共享同一个绝对 `20,000` 页门槛”的误判，但它仍把 coverage 的分母取自**本次 evaluation 的 control
ELF**。这在研究过程中是一个潜在的状态性 bug：如果下一轮把最新 best 重新 pin 成 baseline，control 的 ELF
footprint 也会变化，门槛就会随 baseline 漂移。

本次已在 SimpleTES `869a11a` 中修正。runtime 现在使用固定的 benchmark-protocol coverage：

```text
C = 20,000 / 22,260 = 0.8984725965858041
minimum_pages(binary) = min(B, ceil(C * B))
```

其中 `B` 是当前 binary 去重后的 ELF `PT_LOAD` file-backed pages。`22,260` 是原始 SimTop-50k control ELF
的协议校准 footprint；它只用于定义无量纲门槛，不再从当前 control 重新推导。当前 control 仍会被记录为
audit breadcrumb，损坏或缺失的 artifact 仍 fail-closed，但它不会影响 candidate 的最低页数计算。

因此，下一轮可以正常把最新 best 设为新的 control；control binary 应该随 baseline 一起改变，但 NUMA warm-up
门槛不会因为这次 repin 而被重新校准。

## 2. 旧行为为何会在 repin 后再次失败

旧实现等价于：

```text
R = current_control_PT_LOAD_pages
M_ref = min(20,000, R)
M_variant = ceil(M_ref * B / R)
```

当 `R=22,260` 时，这正好得到 TNO0224 采用的 `89.847260%` coverage。可是若 latest best 变成 control，
例如本轮最终 best 的 ELF 为 `B=20,401` 且实际 resident/local pages 为 `18,965`，旧代码会得到：

```text
R = B = 20,401
M_ref = 20,000
M_variant = 20,000
```

即使页面 `100%` 位于目标 NUMA node，也会因为 `18,965 < 20,000` 被判定为 retryable infrastructure。中间的
c333（`21,314` 个 PT_LOAD pages、`19,877` 个本地 resident pages）也会遇到同样问题。这个失败与页面是否远端、
是否充分触达无关，而是 control 变化导致绝对门槛重新升高。

固定 coverage 后，两个例子的最低页数分别是：

| binary PT_LOAD pages | 固定最低 coverage | minimum resident pages | 已观测 resident/local | 结果 |
| ---: | ---: | ---: | ---: | --- |
| `22,260`（原 control） | `89.847260%` | `20,000` | `20,825/20,825` | PASS |
| `21,314`（c333） | `89.847260%` | `19,151` | `19,877/19,877` | PASS |
| `20,401`（本轮 best） | `89.847260%` | `18,330` | `18,965/18,965` | PASS |

`local_ratio >= 0.999`、NEMU 至少 `100` 页且本地率至少 `0.95`、fixed-ASLR、whole-CCD quiet、PMU 和功能
门禁均保持不变；这不是放宽 NUMA 正确性检查。

## 3. 代码落点

- `SimpleTES/datasets/grhsim/simtop_50k/runtime.py`
  - 新增 `DEFAULT_REFERENCE_LOADABLE_FILE_PAGES`、`DEFAULT_MIN_BINARY_COVERAGE`；
  - 新增无 control 参数的 `minimum_pages_for_coverage()`；
  - `_binary_page_policy()` 改为 fixed protocol coverage，control 只作诊断记录；
  - `min_binary_pages` 保留用于旧配置兼容和诊断；若旧调用方只提供该字段，则以固定 `22,260` 协议 footprint
    换算 coverage，实际 gate 仍使用 `min_binary_coverage`；
  - reference ELF 解析失败仍会抛出并 fail-closed。
- `SimpleTES/tests/test_grhsim_runtime.py`
  - 覆盖 c333 与最终 best 的真实 footprint 数值；
  - 覆盖旧 control→新 best control repin 前后 threshold 完全相同；
  - 覆盖非法 coverage 配置拒绝。

实现先在 detached worktree 中完成，再同步到 live `SimpleTES/main`；当前 live HEAD 为：

```text
869a11a fix: keep NUMA coverage stable across baseline repins
```

没有运行中的 SimpleTES launcher/evaluator 需要热替换；后续启动或恢复时会加载该 runtime。Wolvrix 子模块没有被
本修复改动，工作树中原有的 `m wolvrix` 保持不变。

## 4. 回归结果

所有命令均在 source `wolvrix-playground-gsim-calibrate-5/env.sh` 后执行：

| 验证 | 结果 |
| --- | --- |
| `py_compile`（runtime 与测试） | PASS |
| GrhSIM runtime + bench focused | `115 passed` |
| SimpleTES full pytest | `263 passed`，`25` warnings（既有 pytest/plugin 与 `datetime.utcnow()` deprecation） |
| `git diff --check` | PASS |
| fixed helper `22,260 -> 20,000` | PASS |
| fixed helper `21,314 -> 19,151` | PASS |
| fixed helper `20,401 -> 18,330` | PASS |
| repin invariance（旧 control `22,260` / 新 control `20,401`） | PASS，candidate threshold 都为 `18,330` |
| legacy `min_binary_pages=19,000` override | PASS，固定协议换算后 `20,401` 页 threshold 为 `17,414` |
| 非法 coverage（`<=0`、`>1`、NaN、Inf） | PASS，均 fail-closed |

该改动只影响 runtime admission gate，不改变 Wolvrix 生成代码、SimTop workload 或性能结果，因此不需要另造一轮
50k 性能数字来裁决它；它的验收标准是避免真实候选被错误 retry，同时保留所有 placement/功能门禁。
