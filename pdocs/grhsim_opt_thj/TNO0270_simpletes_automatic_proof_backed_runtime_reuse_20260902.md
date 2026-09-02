# TNO0270: SimpleTES automatic proof-backed runtime reuse

日期：2026-09-02

状态：`IMPLEMENTED; TESTED; NO 50K RUN`

## 1. 问题与结论

此前 GrhSIM evaluator 在一次候选已经完成 clone、emit、function gate 和 ELF build
之后，如果 `GRHSIM_INFRA_RETRIES` 次 runtime 尝试仍返回
`Retryable evaluation infrastructure outcome`，SimpleTES 的下一次 outer retry 会再次
进入普通 evaluator，重新 clone 并完整编译候选。这样浪费了已经通过归因与功能门禁的
生成物。

本次把“已证明生成物只重跑 runtime”接入为自动路径：普通 evaluator 只有在完整 attempt
原子提交成功后，才通过返回值携带严格类型的 `runtime_reuse_ready=1`；engine 随后的同一
候选 retry 才切换到独立的 `retry_runtime.py`。该 entry point 只复用现有 control/candidate
ELF、image、NEMU 和 proof，重新执行 placement、fixed-ASLR、NUMA/PMU、ABBA+BAAB 与
稳定性门禁。新的候选、没有完整提交的失败、以及 proof 校验失败都不会绕过普通构建或
静默回退。

这次没有运行 SimTop 50k，因此 walltime 的绝对值、相对变化和端到端性能收益均为
`N/A`；本记录只确认 retry 行为和安全边界，不能把编译时间节省当作 SimTop 性能提升。

## 2. 实现

- `SimpleTES/simpletes/evaluator.py` 增加可选的 `retry_evaluator_path` 和显式
  `use_retry_evaluator`。路径必须是 regular file，retry entry 必须与普通 entry 不同；
  直接路径覆盖也必须显式声明 retry mode。engine 在普通路径不传新增关键字，保留
  旧式自定义 worker 的调用兼容性；只有实际切到 retry-only 时才传入 `True`。
- `EngineConfig`、CLI `--retry-evaluator`、checkpoint 非敏感配置快照和 engine retry loop
  传递该配置。状态只在一个候选的当前 `_evaluate_code` 生命周期内存在；fresh candidate
  总是从普通 evaluator 开始。进入 retry-only mode 后不会回退到重编译路径。
- GrhSIM launcher 固定传入
  `datasets/grhsim/simtop_50k/retry_runtime.py`。普通 evaluator 在
  `complete.json` 严格提交点之后才返回 transport-only marker；marker 不写入 immutable
  `evaluation.json`/`complete.json`。
- `retry_runtime.py` 导出与 worker 兼容的 `evaluate(program_path)`，调用
  `prepare_reused_artifacts` 与 `acquire_existing_slot`。它验证 candidate patch/options、
  parent/wolvrix pins、generated/build/toolchain fingerprint、`env.sh`、control/candidate
  artifact SHA-256、immutable attempt 和 slot lock；任何验证失败均 fail-closed，绝不 clone、
  emit、build 或隐式 fallback。
- 同一 slot 可能保留旧 evaluator schema 的历史 attempt。已知旧版本会被跳过，当前或未知
  版本仍严格校验，避免历史记录阻断当前 proof-matching attempt。
- launcher 的 evaluator concurrency 仍为 `1`；这是共享 `slot-0` 复用协议的必要前提。
  build/preparation/publish 阶段的 infrastructure error 没有可证明的完整生成物，不会发布
  marker，后续按普通路径重试。

## 3. 验证

代码位于 SimpleTES commit `8e25747b62d85031d350717846e67d2df85f8ee7`
（message: `bench: reuse proven artifacts on infrastructure retries`）。本次验证的绝对结果：

| 检查 | 结果 |
| --- | ---: |
| artifact-reuse/engine/worker/GrhSIM focused tests | `138 passed` |
| SimpleTES full pytest | `322 passed, 24 warnings` |
| Python `py_compile`（相关 9 个入口/模块） | `PASS` |
| `git diff --check` | `PASS` |
| launcher offline `--dry-run` 含独立 retry entry | `PASS` |
| SimTop 50k walltime | `N/A`（本阶段未运行） |

测试覆盖了 marker 只在 immutable commit 后出现、严格类型校验、普通/复用 entry 选择、
同路径拒绝、proof/SHA/lock 校验、旧 schema 忽略、alias 中断保护，以及“进入 retry-only
后不回退重编译”。当前 parent 工作树的 RepCut 改动和 `wolvrix` 子模块未由本任务修改；
parent HEAD 快照为 `f650d5d7e79a9a4c9083984379c534173f2edfa0`，子模块指针为
`054c6a7c09b007a12eb36fdb49fcb659a1bfc590`。

## 4. 运行影响

已有 SimpleTES 进程不会热加载 Python 源码；本修改从下一次新启动或 resume 生效。本次未
停止或重启任何正在进行的 auto research。`GRHSIM_INFRA_RETRIES=99` 的默认值及显式环境
覆盖规则沿用 [TNO0267](./TNO0267_simpletes_quiet_ccd_retry_default_20260901.md)。
