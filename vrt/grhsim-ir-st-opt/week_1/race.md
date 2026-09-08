# Week 1 三方向隔离记录

## 结论与冻结引用

三个方向已从同一 `baseline.md` 建立全新隔离，未使用已有 `c9a4c84b`、`ptmp/grhsim-ir-st-opt`、根 `build/xs/grhsim-ir` 或 `build/tes` 现场。冻结基线 SHA-256：`b70c5fdfa81c7f2ecae06cdb4d249fcdcf9f0d1abda9dbae9e645bf95dd22ca8`。基线条目为 B0-B5，递归清单哈希为 `38b1c6a8b242b0f876b879b8ae4947990f7af1bbd7c0225f4819c9d24672ced4`。

方向间禁止 merge、cherry-pick、rebase、复制源码、生成模型、对象、emu、日志或缓存。共同只读输入仅限 `baseline.md` 已列的 RTL、difftest generated-src、workload、NEMU 和工具环境。公共修复须交项目经理安排 PI 变更共同基线，不能只注入一个方向。

## 方向位置与候选字段

| 方向 | 根 worktree / 分支 | B5 `wolvrix` worktree / 分支 | 只读依赖 | 当前候选 |
| --- | --- | --- | --- | --- |
| 方向 1 | `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-ea895152/week_1/r_1`；`vrt/grhsim-ir-st-opt/ea895152/week_1/r_1` | `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-ea895152/week_1/r_1/wolvrix`；同名 B5 分支 | B1-B4 及其递归依赖共 162 个仓库均为独立 detached shared clone | 根 `3a8558a1618e978c32fc8d3d70c26268879af41d`；B5 `cba9c32240f3cd06c5b675968b56046e5b76f818`；最终候选待工程提交 |
| 方向 2 | `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-ea895152/week_1/r_2`；`vrt/grhsim-ir-st-opt/ea895152/week_1/r_2` | `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-ea895152/week_1/r_2/wolvrix`；同名 B5 分支 | 同方向 1，物理目录独立 | 根 `3a8558a1618e978c32fc8d3d70c26268879af41d`；B5 `cba9c32240f3cd06c5b675968b56046e5b76f818`；最终候选待工程提交 |
| 方向 3 | `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-ea895152/week_1/r_3`；`vrt/grhsim-ir-st-opt/ea895152/week_1/r_3` | `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-ea895152/week_1/r_3/wolvrix`；同名 B5 分支 | 同方向 1，物理目录独立 | 根 `3a8558a1618e978c32fc8d3d70c26268879af41d`；B5 `cba9c32240f3cd06c5b675968b56046e5b76f818`；最终候选待工程提交 |

每次 ENGINEER 开工/完工必须把下列字段追加到本方向 `ra_<i>/steps/step_<k>_{task,result,review}.md`，不得修改本文件：根 HEAD/tree/branch/status、B5 HEAD/tree/branch/status、B0 的 B5 gitlink、163 项清单哈希、所有 modified/untracked 文件、生成物绝对路径与来源、运行命令/退出码、最终候选 commit。根候选只有在 Makefile/script 或 B5 gitlink确需改变时才提交；B5 实现必须提交。

## 污染核查

核定后每方向结果相同：

| 核查 | 方向 1 | 方向 2 | 方向 3 |
| --- | --- | --- | --- |
| 根 `status --porcelain=v2 --branch` | B0 commit、独立分支、无差异 | 同 | 同 |
| B5 `status --porcelain=v2 --branch` | B5 commit、独立分支、无差异 | 同 | 同 |
| `submodule status --recursive | wc -l` | 163 | 163 | 163 |
| `submodule ... path/HEAD | sha256sum` | `38b1c6a8b242b0f876b879b8ae4947990f7af1bbd7c0225f4819c9d24672ced4` | 同 | 同 |
| `submodule status ... /^[-+U]/` | 空 | 空 | 空 |
| 方向内 `build`、`ptmp`、`.runner` | 均不存在 | 均不存在 | 均不存在 |

以上命令退出码均为 0。输出目录预留为各根的 `ptmp/week_1/{baseline,steps,final}/` 与各 B5 的 `build/`，第一次使用时创建；`.runner` 禁止出现。

## 建立记录

1. 路径和根/B5 分支存在性预检：目标目录不存在，6 个新分支均不存在；相关 `test` 退出码 0，`show-ref --verify --quiet` 退出码均为 1，证明可新建。
2. 三次 `git worktree add -b <方向分支> <方向路径> 3a8558a1618e978c32fc8d3d70c26268879af41d` 退出码 0；三次 `git -C wolvrix worktree add -b <方向分支> <B5路径> cba9c32240f3cd06c5b675968b56046e5b76f818` 退出码 0。
3. 旧只读证据 `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/evidence/repos.tsv` 与当前现场分别标准化为 `path<TAB>HEAD` 后，SHA-256 均为 `38b1c6a8b242b0f876b879b8ae4947990f7af1bbd7c0225f4819c9d24672ced4`、条目均为 163，退出码 0；因此只使用其清单顺序，从当前干净仓库对象库建立新的 shared clone，不使用旧 worktree 内容。
4. 首次递归 clone 命令因 shell 局部变量 `d` 未定义立即停止，三个进程退出码 1，未创建首项依赖；根/B5 worktree保持干净。修正为显式绝对目标路径后，三个方向各完成 162 个非 B5 顶层仓库的 detached checkout，退出码 0。
5. `git submodule init` 与递归注册三方向退出码 0；最终 163/163、无偏移、无 dirty 状态，核查退出码 0。

## 目标引用与周末集成

- 预定集成引用：B0 `grh/grhsim-ir`，规划前技术 HEAD `3a8558a1618e978c32fc8d3d70c26268879af41d`；B5 `grh/grhsim-ir`，规划前 HEAD `cba9c32240f3cd06c5b675968b56046e5b76f818`。本周档案提交只改变 B0 的 `vrt/grhsim-ir-st-opt`，不改变技术起点。
- 周末 PI 按 `pi_plan.md` 选择一个或零个精确候选。项目经理随后安排 Agent 把该方向的 B5 commit及必要 B0 gitlink/根改动集成到当时目标引用；禁止拼接多个方向。
- 集成前复核目标漂移，集成后重跑完整正确性、单线程 50k 和编译门槛。冲突修复或目标变化导致候选 tree 改变时，原测量失效，须重新验收。
