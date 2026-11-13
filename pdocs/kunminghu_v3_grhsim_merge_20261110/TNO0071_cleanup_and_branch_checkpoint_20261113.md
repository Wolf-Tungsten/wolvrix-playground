# TNO0071：代码整理与新分支检查点

日期：2026-11-13（America/Los_Angeles）。本次按用户要求整理自 kunminghu-v3 merge 以来的代码、测试和文档，并将相关代码仓库统一切到新分支。性能实验没有重跑；本篇不增加 walltime 结论。

## 仓库与分支

以下四个仓库均已切到 `thj/kunminghu-v3-grhsim-cleanup-20261113`。XiangShan 和 difftest 本轮没有代码修改，仍创建并切换新分支，不制造空提交。旧分支保留在原来的提交。

| 仓库 | 切换前分支 | 新分支起点 | 本轮内容 |
| --- | --- | --- | --- |
| 父仓 | `thj/gsim-calibrate-2` | `c1c3d7661e1bc29b95c1faf5b407c13effc53e1f` | parser 修正、preset、测试、Wolvrix gitlink、实验记录 |
| `wolvrix` | `thj/kunminghu-v3-grhsim-compat-20261110` | `3a749d2a519d77a9e974c026db41601f36e99560` | 通用 concat reduction emitter、测试、功能文档 |
| `testcase/xiangshan` | `thj/kunminghu-v3-grhsim-merge-20261110` | `defb18e13c2e3a0e272b43b2eaccd1d4b16de9c0` | 仅创建并切换新分支 |
| `testcase/xiangshan/difftest` | `thj/kunminghu-v3-grhsim-port-20261110` | `b17a43ad24ae2d137f263d667787d3968505b771` | 仅创建并切换新分支 |

`reference/gsim` 及其他上游依赖在该阶段没有本地代码改动，保持原有冻结 revision。大体积生成 C++、binary、profile 和分区实验产物继续留在 `build/`，不加入源代码提交。

## 整理范围

- Wolvrix 保留已验证的共享 Boolean 输入掩码、宽 concat 归约融合、短条件公共因子成本门。三项都有独立开关、用途/稳定性回退、对应 focused CTest 与 [功能文档](../../wolvrix/docs/emit/grhsim-short-reduction-masks.md)。本次没有新增优化规则或修改分区算法。
- [标准 preset](../../config/grhsim32.json) 显式记录已批准默认开启的三个选项；[pipeline 测试](../../scripts/test_grhsim32.py) 校验这些默认值。
- `[codepage-retry]` 是 host 诊断，不属于 workload 输出。整理时发现未提交的 parser 改动还把 `[CYCLE_LIMIT]` 过滤错误地限制在行首，导致四项既有 UART 测试失败。现已恢复其原有行内清理语义，并单独过滤行首 retry 诊断。
- retry 测试移入 [baseline 日志测试](../../scripts/test_grhsim_single_baseline.py)，覆盖 banner 前诊断、body 内诊断、分段 UART 和行内 cycle 消息组合。对应修复提交为 `f2adc72`。
- TNO0035–TNO0070 既有记录和 README 索引一并归档，保留历史结论；本篇记录新的执行边界。

## 手动 swap 与运行后选择的边界

用户已要求暂时不要进行手动选择或运行后的选择。自该要求起停止此类实验，不再按 profile 手选 piece/目标分区，也不根据候选实测 walltime 更新 retained assignment。

[TNO0069](./TNO0069_repcut_local_partition_rebalance_20261113.md) 和 [TNO0070](./TNO0070_repcut_part18_to_22_candidate_20261113.md) 中的候选只保留为历史实验。旧文中继续 boundary swap 或按测量更新 retained 的建议不再作为当前执行依据。此次提交不把候选 assignment、生成模型或二进制接入默认流程；既有自动流程代码没有在本轮重新执行或改动。

## 已完成验证

- Python：`PYTHONPATH=scripts python3 -m unittest test_grhsim_single_baseline test_grhsim_single_compare test_grhsim32_pair_compare test_grhsim32`，58 项通过。
- 独立构建目录 `/tmp/wolvrix-cleanup-build`：关闭可选 LIBFST、MT-KaHyPar 和 Python package 后，`emit-grhsim-cpp` 及依赖库构建成功。完整 focused CTest 的结果另在本篇追加。

本次没有重新生成完整 XiangShan、运行完整 DiffTest 或启动性能对测；此前全芯片验收和原始产物仍按各篇记录单独保留。

## 代码提交与检查证据

| 仓库 | 提交 | 内容 |
| --- | --- | --- |
| 父仓 | `f2adc72` | retry 诊断过滤与分段 UART 回归修正 |
| Wolvrix | `2e1d37ebbc6d11fccb65583115354b53b1aa3ae6` | 三项通用 concat 归约优化、边界测试、功能文档 |
| 父仓 | `b326e9cd71c8d9d61f988748e6b5512268a4927a` | 已验证选项的 preset、默认值断言和 Wolvrix gitlink |

四个仓库的旧分支均保持原 SHA，新分支以旧 HEAD 为祖先；父仓的两个直接 gitlink 和 XiangShan 的 difftest gitlink 均与实际子仓 HEAD 一致。证据见 [代码检查点](../../build/artifacts/kunminghu-v3-cleanup-20261113/code-checkpoint.json)。

RepCut 的普通/performance build 和 run-only 四个 canonical target 的 `make -n` 均成功，只有 performance target 带 `--performance`，只有 run target 带 `--run-only`；见 [target 检查](../../build/artifacts/kunminghu-v3-cleanup-20261113/canonical-targets.json)。这只是入口检查，没有执行模型生成或测量。

## 验证收尾

独立 emitter 构建以及以下四项 CTest 均通过：

- `emit-grhsim-cpp-scalar-concat-reduction-masks`
- `emit-grhsim-cpp-short-concat-reduction-masks`
- `emit-grhsim-cpp-wide-concat-reduction`
- `emit-grhsim-cpp-scalar-concat-reduction`（原有父规则回归）

测试包含显式开启、关闭、父规则关闭、默认策略、不同谓词/输入规模边界和固定随机种子的重复 eval。生成 harness 使用 Clang 23.1.2，在 O0/O3 下启用 ASan/UBSan。emitter 自身由系统 GNU C++ 13.3.0 构建，二者没有混记为同一编译器。

58 项 Python 测试、修改过的 Python 文件编译检查和四个 canonical Make target 检查均通过。新增 37 篇 TNO 的编号、标题和 README 索引匹配，Markdown 链接检查通过；代码和文档均通过 `git diff --check`。

验证产物：

- [验证摘要](../../build/artifacts/kunminghu-v3-cleanup-20261113/verification.json)
- [三项新规则 CTest 日志](../../build/artifacts/kunminghu-v3-cleanup-20261113/ctest-reduction-optimizations.log)
- [父规则回归日志](../../build/artifacts/kunminghu-v3-cleanup-20261113/ctest-parent-regression.log)
- [验证工具链](../../build/artifacts/kunminghu-v3-cleanup-20261113/verification-environment.json)
- [链接检查](../../build/artifacts/kunminghu-v3-cleanup-20261113/document-check.json)
