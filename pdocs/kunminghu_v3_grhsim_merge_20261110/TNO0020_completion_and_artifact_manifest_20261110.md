# TNO0020 合并完成与最终归档

## 最终源码

父仓继续使用 `thj/gsim-calibrate-2`。XiangShan 在 `thj/kunminghu-v3-grhsim-merge-20261110` 上形成真实 no-ff merge `9d1f24cea2726642bfe04be545f7046f845735ed`，两个 parent 分别是原提交 `77ed568fcb70eba6d06195ffaa57a87929dcda6d` 和冻结的 `origin/kunminghu-v3` `41ab74e7db544787bd607280967b98eb44fa634f`。

| 仓库 | 最终实现 commit | 说明 |
| --- | --- | --- |
| XiangShan | `defb18e13c2e3a0e272b43b2eaccd1d4b16de9c0` | merge 后固定 difftest 适配；相对上游只差该 gitlink |
| difftest | `b17a43ad24ae2d137f263d667787d3968505b771` | 合并上游 `ecdf41e225`，保留 GrhSIM/RepCut；修复冻结 REF 的 flash ABI 兼容 |
| Wolvrix | `3a749d2a519d77a9e974c026db41601f36e99560` | GrhSIM wrapper 的无驱动二态信号兼容；Verilator 行为不变 |
| 父仓 harness | `2a65a62`，及其祖先 `f2563c5`、`7246fcb`、`7f76b39` | 版本独立 schema、配对 runner、严格 NUMA、运行期线程检查 |

最后的文档提交及完整分支/SHA/工作树状态见 [final-verification.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/final-verification.json)。未推送远端。

XiangShan 主 Scala、DefaultConfig、Makefile、build.mill 和新子模块布局均采用上游；行为模型与旧架构补丁没有保留。具体 merge 冲突和 gitlink 迁移见 [TNO0002](./TNO0002_difftest_merge_port_20261110.md)、[TNO0010](./TNO0010_merge_checkout_completion_20261110.md)。旧的干净子模块工作目录已归档，原始 git objects 保留。

## 验证完成范围

- before/after native tools、Chisel/RTL、native 与 RepCut C++ 构建完成；四种组合的 10k smoke 和 100k 完整 DiffTest 均通过。
- native 每侧两组 100k trace 通过。跨版本允许 schema 和同周期指令进度变化，各侧分别通过 NEMU；同版本 native/RepCut 的 PC、指令数、周期数和 UART 签名相同。
- 单核 8 对、32 线程主实验 8 对、32 线程确认实验 8 对全部完成，只有通过功能和 placement/locality 检查的完整系列进入结果。
- Python `test_grhsim*.py` 共 **84 项通过**；Python 编译检查通过。
- GrhSIM、Verilator RepCut focused emitter 测试通过；无驱动信号的 scalar/wide、alias、重新初始化、serial/parallel 和 unsupported-driven-operation 覆盖通过。
- before 重新生成的 **15,754 个 C++/header 字节一致**，Makefile 和 7,814 个 C++ 编译顺序一致，冻结的 before binary 可继续使用。
- 7 个 canonical Make target 的 `make -n` 检查通过；最终 `git diff --check`、递归子模块状态、文档相对链接检查见最终校验记录。

验证证据：[84 项测试](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/grhsim-python-tests-runtime-phase.log)、[GrhSIM emitter](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/undriven-grhsim-test.log)、[Verilator emitter](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/undriven-verilator-test.log)、[canonical Make](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/canonical-make-postmerge.log)。归档阶段未重复已通过的测试。

## 性能结论

单核 8/8 合并后更慢，Host time 配对平均 **+30.766%**，95% CI **[+29.968%, +31.781%]**，详见 [TNO0015](./TNO0015_native_paired_walltime_20261110.md)。

32 线程主实验平均 **+32.179%**，但中途绝对耗时明显下降；同 binary、同参数的 8 对复测平均 **+2.904%**，95% CI **[−1.458%, +8.379%]**。没有确认稳定的 32 线程退化幅度，两轮分开记录，详见 [TNO0018](./TNO0018_repcut_primary_paired_walltime_20261110.md) 和 [TNO0019](./TNO0019_repcut_confirmation_20261110.md)。

这是整版 DefaultConfig 的差异：before 使用 TL、1 MiB L2/16 MiB L3；after 使用 CHI、2 MiB L2/32 MiB OpenLLC，且微架构和 observer 结构也变化。100k 周期内提交指令数不同，不能把这些结果解释成同等工作量或后端独立优化的效果。公共默认流程和性能开关均未因结果改变。

## 产物清单

统一入口：[artifact README](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/README.md)、[机器可读总报告](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/report.json)、[model manifest 索引](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/model-manifests/index.json)。

| 模型 | 被哈希的 source/header/archive/config 文件数 | binary bytes |
| --- | ---: | ---: |
| before native | 136 | 79,340,032 |
| after native | 143 | 104,473,224 |
| before RepCut retained | 15,820 | 101,037,232 |
| after RepCut retained | 18,864 | 118,894,296 |

各 manifest 包含文件路径、长度和 SHA256，并关联原始 RTL manifest、DiffTest generated manifest、configuration、最终 binary。RepCut 另含 assignment、partitioned graph、selection 和 migration 身份。

大体积原始文件保留在 `build/xs/kunminghu-v3-grhsim-merge-20261110/`，artifact 下的相对 `builds` symlink 指向该目录。搬迁归档时必须同时保存该目标目录；不能只复制小型 artifact 索引。原始命令、日志、CSV/JSON、失败门记录和源代码补丁均可通过统一索引追溯。

重新构建使用 [TNO0009 的独立 after 配置](./TNO0009_reproduction_and_paired_runbook_20261110.md)，正式配对使用严格 `membind=0` 的 runner。公共 memory 配置没有被实验覆盖；上游已删除的两个 TL FIFO 不能映射到语义不同的新设备总线 FIFO。
