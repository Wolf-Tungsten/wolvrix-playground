# Week 1 方向隔离与赛马记录

会话后缀：`c9a4c84b`。三方向均从 baseline.md 的入口 `0567b6c7d0261ddd1834daffa8f15327c7f5810a` 与 wolvrix `cba9c32240f3cd06c5b675968b56046e5b76f818` 建立，未从旧 r_2/r_3 成果续接。

|方向|入口分支/目录|wolvrix 分支/目录|起点核查|产物隔离|
|---|---|---|---|---|
|1|`vrt/grhsim-ir-st-opt/c9a4c84b/week_1/r_1`; `/home/gaoruihao/wksp/wolvrix-playground/ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/r_1`|同名分支；目录下 `wolvrix/` 独立 worktree|入口 HEAD=`0567b6c7d0261ddd1834daffa8f15327c7f5810a`；技术 HEAD=`cba9c32240f3cd06c5b675968b56046e5b76f818`；clean|`ptmp/` 及 `build/` 仅本目录|
|2|同上 r_2|同上 r_2|同两 SHA；clean|仅 r_2|
|3|同上 r_3|同上 r_3|同两 SHA；clean|仅 r_3|

实际建立方式为 `git worktree add -b ...`；三个入口 worktree 与三个 wolvrix worktree 均已存在并可复核，未清理/复用旧 worktree。XiangShan、gsim 及递归依赖保持共享只读，基线提交与输入指纹见 baseline.md；若任何依赖需修改，必须先交 PI 追加共同基线，不能只升级一个方向。工程师必须在每步记录 `git status --short`、HEAD、父 gitlink、生成物绝对路径和日志来源。

候选提交栏：方向 1/2/3 均为“尚无候选（0/6 工程调用）”。方向内只能续接本方向提交；禁止 merge、cherry-pick、copy 其他方向实现或生成物。所有研究档案仍写入 `/home/gaoruihao/wksp/wolvrix-playground/vrt/grhsim-ir-st-opt`。

复核证据：`ptmp/vrt-grhsim-ir-st-opt-c9a4c84b/week_1/evidence/isolation-verified.tsv`（489 行，SHA-256 `6149d82c9e892b1fe92ce0682b5f37cabf5500c51fcbd4f35037d90044a343db`）逐方向核对递归仓库 HEAD/tree/status；入口和 wolvrix worktree 创建命令及输出保存在同目录 `evidence/isolate.log`。隔离阶段无失败命令、无残留构建/仿真进程；未运行优化、构建或目标测试。
