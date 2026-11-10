# TNO0002 difftest merge 与 GrhSIM 适配

## 范围与固定输入

遵循已批准的总计划；父仓、workload 和 before 版本身份见 [TNO0001](./TNO0001_identity_and_baseline_20261110.md)。difftest 从 `origin/grh/dev-grhsim` 的 `f3a65afb` 建立 `thj/kunminghu-v3-grhsim-port-20261110`，真实合并 XiangShan 上游使用的 `ecdf41e225a93699b9a1141ec4d0fc1ff485b890`。适配范围为 Makefile/emu.mk/grhsim.mk、emu runtime、Simulator 接口和 GrhSIM 后端。Scala 与 checker 采用固定上游版本，不携带行为模型实验。

适配先在独立 worktree `build/difftest-kunminghu-v3-port-20261110` 进行；正在运行的 before 构建仍使用原 difftest checkout。

## API 核对与设计

勘误：计划中的 `single_cycle/reset_cycle` 属于更后的 difftest；固定目标 `ecdf41e225…` 实际仍使用 `set_clock/set_reset/step`。保留与该 commit 一致的 API，在 reset 与 single_cycle 的两次 eval 位置接入 GRHSIM，保持上游 Verilator accelerator clock 分支。

保留默认关闭的 runtime profile、phase timing、waveform 和 `CONFIG_NO_DIFFTEST` 编译接口；完整功能与 walltime 运行均启用 DiffTest/NEMU。上游 checker 和 Scala 不作算法改动。针对 upstream Makefile 的模型依赖、额外链接对象及可选库做编译适配。

## 执行阶段与验证口径

1. 记录冲突，合并 runtime 与构建入口。`git diff --check`、`git diff --name-only --diff-filter=U`，无未解决冲突和空白错误后进入构建。
2. 在 parent 中执行 `python3 scripts/grhsim_single_baseline.py build --xs-config DefaultConfig --output build/xs/kunminghu-v3-grhsim-merge-20261110/after/single`，并使用 RepCut `--performance` 入口构建 after。
3. 两种 emulator 分别执行 `-i testcase/xiangshan/ready-to-run/coremark-2-iteration.bin --diff testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so -b 0 -e 0 -C 10000` 与 `-C 100000`；完整命令、placement 和环境由实验 runner 记录。PASS 要求 DiffTest enabled、达到周期上限、无 mismatch/ABORT/assertion。随后进行批准的 8 对 AB/BA。

最终验收以本次用户明确批准的 CoreMark 100,000 周期和配对性能为准；不将 difftest 通用 workflow 中的 Linux 长测当作本次额外验收条件。

## 进度

| 阶段 | 状态 | 验证 |
| --- | --- | --- |
| 固定 target 与独立 worktree | 已完成 | ecdf41e225 的 gitlink/API 已核对 |
| 真实 merge | 冲突解决中 | 冲突列表已保存 |
| focused 编译 | 待开始 | — |
| 全图功能/性能 | 待开始 | — |

### 2026-11-10 初始 merge

冲突：`gsim.mk`、`verilator.mk`、`diffstate.cpp`、`difftest.cpp`、`emu.cpp`、`emu.h`、`gsim.h`。原始日志与完整文件列表保存于 `build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/difftest-merge.log` 和 `difftest-conflicts.json`。

### 2026-11-10 适配 commit 与编译边界

difftest merge commit：`b58c89454408426c716d90f42676c796d7f96954`。保留 `emu-grhsim`、两次 eval 的时钟语义、默认关闭的 runtime profile/phase timing、waveform 及 no-DiffTest completion 标记；去掉已删除的 partitioned-Verilator selector。grhsim.mk 显式使用 pthread，并保留 `SIM_EXTRA_OBJS` 依赖但避免 CUDA 对象重复链接。

GrhSIM 和 emu 源文件对冻结 native 模型的 syntax check 通过，含 CONFIG_NO_DIFFTEST。NO_DIFF=1 的 make dry-run 中 30 个 C++ 命令均带禁用宏，无 checker 编译和 NEMU 链接。

试用 before 的旧 generated-src 链接全部新 checker 失败：DifftestStoreEvent 缺少 highData/offset/eew/vecNeedSplit/wLine 等上游新增字段。该结果确认前后 schema 不能混用；未修改 checker 或旧头文件。完整编译验证必须等待 after RTL 产生匹配的 generated-src。失败日志保留在 `logs/difftest-focused.log`。

XiangShan 真实 merge 在独立 worktree 形成 `9d1f24cea2726642bfe04be545f7046f845735ed`，parent 为 `77ed568fc` 与 `41ab74e7d`。最终 tree 与上游仅 difftest gitlink 不同；40 个冲突原始清单已归档。before RepCut 完成前不切换原 source checkout。
