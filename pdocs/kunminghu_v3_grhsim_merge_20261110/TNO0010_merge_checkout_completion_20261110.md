# TNO0010 合并 checkout 与子模块落地

## 当前提交

主仓保持 `thj/gsim-calibrate-2`。XiangShan 位于 `thj/kunminghu-v3-grhsim-merge-20261110`：

- 原 commit：`77ed568fcb70eba6d06195ffaa57a87929dcda6d`。
- 固定上游：`41ab74e7db544787bd607280967b98eb44fa634f`。
- 真正的 merge commit：`9d1f24cea2726642bfe04be545f7046f845735ed`，两个 parent 正是上述原 commit 与上游 commit。
- 当前 HEAD：`defb18e13c2e3a0e272b43b2eaccd1d4b16de9c0`，仅在 merge 后更新 flash 兼容适配的 difftest gitlink。
- difftest 本地分支：`thj/kunminghu-v3-grhsim-port-20261110`，HEAD `b17a43ad24ae2d137f263d667787d3968505b771`，包含对上游 `ecdf41e225a93699b9a1141ec4d0fc1ff485b890` 的真实合并。

相对固定上游，XiangShan 的 tree 只更改 `difftest` gitlink。Scala、SimTop、DefaultConfig、Makefile、build.mill、Utility 及其他硬件子模块均采用上游版本，未留下行为模型、PopCount/decode intrinsic 或旧架构补丁。

## 子模块状态

before RepCut 完整流程结束后，主 checkout 执行了 `submodule sync` 和 `submodule update --init --recursive`，随后将 difftest 切到本地适配分支。XiangShan、difftest、Wolvrix 及递归子模块工作树均干净。

| 子模块 | 固定 commit |
| --- | --- |
| ChiselAIA | `c8be865e4fa60d40831ff29e0a30d4269f5ff5b9` |
| ChiselIOPMP | `cc1113c30a2469e27a233795a4e5705c43c84726` |
| OpenIOMMU | `92ed152eeb74caeacbd04a02446f8e4aae780fe5` |
| XSCache | `a041f0750e8aa2a831298977e3fac3fbdde7c93b` |
| difftest | `b17a43ad24ae2d137f263d667787d3968505b771` |
| ready-to-run | `4cf9983569432035d41956c65e6a58724b5954be` |
| rocket-chip | `a2df1a42399cfe2b343eeb5293796268dc2bc211` |
| utility | `eb8e12b00a33e4716e7778175f6dd45b7a3a9ede` |
| yunsuan | `267ff736e7acd8e0fe8d13710581e4902a8a8a6c` |

旧 `coupledL2/huancun/openLLC` 目录经确认无本地修改后移至 artifact 中的 `retired-submodule-worktrees/`，不再污染当前源码布局；对应历史 commit、原目录和 git 指针记录在 relocation.json，源码仍可恢复。

## 证据和检查

[identity-after.json](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/identity-after.json) 保存分支、完整 SHA、merge parents、工作树状态，以及相对上游的精确 patch。[source-after](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/source-after/) 保存递归子模块状态。合并冲突清单保留于初始 artifact 的 `xiangshan-conflicts.json` 和 `difftest-conflicts.json`。

主仓、XiangShan、difftest 的 `git diff --check` 通过；7 个 canonical RepCut Make target 的 `make -n` 在子模块更新后再次通过，见 [canonical-make-postmerge.log](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/logs/canonical-make-postmerge.log)。

native 功能门见 [TNO0008](./TNO0008_native_trace_and_structure_gate_20261110.md)。本阶段 after RepCut 仍在生成分区；正式性能结果另文归档。所有提交均仅保存在本地。
