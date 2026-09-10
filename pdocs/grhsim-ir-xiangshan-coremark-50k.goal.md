# Goal: 优化 GrhSIM-IR 单线程 XiangShan CoreMark 50k

## 目标与范围

通过多个完整节点积累可组合的性能改进，逐步逼近约 **40 s**，不要求单个方案一步达标。整个 goal 完成须同时满足：50k 行为等价、单线程仿真性能提升大于5%、完整 SV→C++ 生成和 C++ 编译各 `<1800 s`、至少一次独立复跑，以及完整归档已提交。

允许修改 GrhSIM-IR 语义、op、emit、分区、调度及等价子图/状态访问优化。禁止修改冻结的 GRH IR、GRH 上已有 pass、XiangShan 和测试源码；禁止多线程仿真及模块名称匹配优化。方案必须由语义、依赖、位宽、读写属性等通用特征触发。

优先探索能大幅减少主要成本的创新机制，如共享重复状态/事件历史、消除重复求值、跨子图融合、专用 op 或执行机制重构。每个假设须说明新意、瓶颈证据、覆盖面、预期收益范围或上界及可证伪标准。不能长期围绕边角 helper 或同一参数微调；局部调整应服务于核心方案。允许有证据的失败，不以创新为由放宽正确性和时间门槛。

## 节点与阶段

**每次 `/goal` 完成一个节点：围绕一个核心优化假设，从提出推进到实验验证和最终判定，统一提交后停止。** 阶段是节点内部状态，不是独立的 `/goal` 或提交点：

| 阶段 | 必要工作 |
|---|---|
| `IDEA` | 提出假设、创新机制、局部收益目标和验证标准 |
| `BASELINE` | 核对输入，建立或复用对照，确定资源配置、计时边界和止损线 |
| `IMPLEMENTED` | 实现方案，记录语义约束和版本差异，通过聚焦测试 |
| `VALIDATED` | 完成全流程门槛、50k 等价检查、性能测量和必要独立复跑 |
| `ACCEPTED` | 局部收益有可复现证据，正确性和生成/编译门槛通过 |
| `REJECTED` | 假设被否定、收益不足或验证失败，记录理由及未执行阶段 |

- 各阶段在同一报告中及时记录计划、方法、结果和决策，留在工作区供观察；不预填结果，不作阶段提交。
- 基线测量、工具准备、实现和测试均在当前节点内完成，不能拆成多次 `/goal` 代替方案验证。
- `ACCEPTED` 只表示节点局部接受，不要求已达到 40 s；噪声范围内的差异不能当作已证明收益。
- 证据足以否定假设时可提前 `REJECTED`。同一假设的精化重试建议最多 2 次；改变核心机制属于新节点。
- 自动续行、工具调用和上下文切换只延续当前节点。节点完成后，须由用户再次启动 `/goal` 才能开始下一节点。
- 用户中断或外部阻塞时保留工作区和阶段记录，恢复后继续同一节点；不得把中断当作节点完成或提前提交。

## 执行与验证

所有构建、安装、生成、测试和仿真均通过 Makefile 目标；缺少目标时先补充，禁止手拼底层命令。常用目标为 `xs_wolf_grhsim_ir`、`xs_wolf_grhsim_ir_build_emu`、`run_xs_wolf_grhsim_ir_emu`，以当前 Makefile 为准。

每个节点有唯一 ID，每次实验有唯一 `RUN_ID`。日志和临时产物放在 `ptmp/`，不写 `/tmp`。仿真固定 CPU 并显式设置 `XS_EMU_THREADS=1`；编译按可用 CPU 数并行。

| 区间 | 计时边界与门槛 |
|---|---|
| SV→C++ 生成 | Make 启动至完整目标 C++ 和 Makefile 生成完成，墙钟 `<1800 s`；恢复已有 IR 的时间不能替代完整 SV 路线 |
| C++ 编译 | 编译目标启动至 emu 可执行文件完成，墙钟 `<1800 s` |
| 仿真 | 仅 emu 执行区间；记录 Host/墙钟时间、cycle 上限、退出状态及等价性 |

启动前安装截止机制：生成或编译达到 1800 s 时立即终止该步骤及子进程，记 `TIMEOUT_KILLED` 并隔离未完成产物。仿真达到预选可比较基线的 **1.5 倍**时立即终止进程树，记 `REGRESSION_KILLED`。基线有多次测量时，须在运行前选定比较值。触发上述限制后拒绝并收尾当前节点，不再继续性能实验。

退出非零、崩溃、断言失败、difftest mismatch 或输入不一致均记 `INVALID`；运行中确认失败即终止。失败或部分结果只能用于原因分析，不能作为性能收益证据。

比较须保持机器、输入、CPU 绑定、cycle 范围和 waveform/trace 设置一致。配置未变时复用已归档 gsim 测量，不重复运行；配置变化时重建相应基线，代码变化时建立相应 GrhSIM-IR 对照。约 40 s 是目标，不是实测值；采样/插桩时间不得混入未插桩性能基线。

## 文档与 Git 归档

每个节点维护一份 `pdocs/` 报告，逐阶段更新以下信息，节点结束时补齐索引：

- 假设与机制：创新点、瓶颈证据、局部目标、改动范围及语义约束。
- 复现方法：基线 commit、工作区实验版本差异、输入身份、完整 Make 命令/参数/环境、资源、计时边界、重复次数和止损线。
- 结果与分析：各次时间、退出状态、等价性、变化比例及计算口径；相关代码规模/热点数据、噪声、限制和重试差异。
- 最终判定：`ACCEPTED` 或 `REJECTED` 的依据、未执行阶段、保留实现的最终 commit、后续方向及报告链接。

报告须自包含，将临时产物中的证据整理入正文，不能用“详见日志”、路径或哈希代替分析。正式引用只能指向已跟踪或随节点一起提交的文件；节点内可引用待归档的新文件。不得提交生成代码、日志、profile、波形和二进制，也不得强制添加生成目录。

**仅节点完成时集中暂存、检查并提交代码、测试、报告和索引，每个有改动的仓库原则上一次提交。** 涉及子模块时先提交子模块，再提交根仓库指针与档案。中间版本用基线及差异记录，不为取得 commit 而提前提交。

用户启动 `/goal` 已授权正常暂存和节点最终提交。复用已有 Git 授权，不按阶段、文件或仓库反复询问；环境确需额外权限时，完成全部准备后在节点收尾集中处理，不绕过权限限制。

每完成 3 个节点，在收尾时更新当前最佳、已排除方向和剩余主要差距，检查是否陷入低收益微调。整体累计验收门为：M0 固定基线；M1 热点证据及至少 3 个独立方向；M2 小规模等价和生成/编译门槛；M3 完整 50k 验证；M4 最终性能、独立复跑及归档全部达标。只有 M4 完成才能关闭整个 goal。

## 当前基线与搜索依据

截至 2026-09-10，最终性能目标未完成。固定配置：

- XiangShan：`4a6e3da8bfb1140d24eaa6c9e0d058fd981b35a6`；top `SimTop`，DIFFTEST/NEMU。
- 输入：`testcase/xiangshan/ready-to-run/coremark-2-iteration.bin`；SHA-256 `c764afb8bfd69542620a4794b858867dd1e455efaac56c28eb477f1732f83e8e`。
- 50,000 cycles、CPU 2、`XS_EMU_THREADS=1`，waveform/commit/RAM trace 关闭；主机 32 CPU。
- 最低实测均值：scalar staging `7b3432b29f87cae70dfba6f929078a2632d6b066`，两次 **284.075 / 275.822 s**，均值 **279.9485 s**；相对前一基线低 1.6686%，但范围重叠，收益未排除噪声。止损线 **419.92275 s**。
- 该版本完整生成 **605.75 s**、32-job 编译 **471.77 s**，flat GRH 与冻结基线逐字节一致；两次 NEMU PASS，73,580 instructions、cycleCnt 49,996、末端 PC `0x80001312`、guest cycles 50,001。
- gsim 参照 **20.640 s**，NEMU PASS；其计数为 73,584 instructions、cycleCnt 49,998、PC `0x8000131e`，后端计数边界差异见 M0 报告。

诊断版本 `93d55ae` 的 eval 时间：compute **56.18%**、commit **38.75%**、publication **5.04%**。函数采样中 `cpu_write_scalar<bool>` 占 **6.22%**；compute 热点分散于 3,367 个 task，前十仅占总样本 **2.55%**；整个 evaluator 占 **3.05%** 且包含内联 publication，不能全归因于 dispatch。应从通用语义和重复工作寻找覆盖面大的机制，事件历史采样/扫描值得分析；这些诊断不构成优化收益。

## 报告索引

保留历史结果；旧报告中按阶段拆分执行或提交的做法不再适用。后续按完整节点登记。

| 报告 | 状态 / 关键结论 |
|---|---|
| [M0 baseline](grhsim-ir-m0-baseline-20260910.md) | 基线：gsim 20.640 s；原始 IR 304.197 s |
| [frame-init](grhsim-ir-candidate-frame-init-20260910.md) | REJECTED：305.17 s，移除清零无收益 |
| [activity-guard](grhsim-ir-candidate-activity-guard-20260910.md) | 前一基线：均值 284.699 s |
| [batch-packing](grhsim-ir-candidate-batch-packing-20260910.md) | REJECTED / INCOMPLETE：编译未完成，无性能结论 |
| [ready-queue](grhsim-ir-candidate-ready-queue-20260910.md) | REJECTED / INVALID：cycle 0 RTL assertion，0 instructions |
| [ready-dispatch](grhsim-ir-candidate-ready-dispatch-20260910.md) | REJECTED / REGRESSION：737.862 s，对拍通过但显著变慢 |
| [activity-mask-pack](grhsim-ir-candidate-activity-mask-pack-20260910.md) | REJECTED：仅减少 0.1179477% 静态 guard 检查项，无运行收益证据 |
| [scalar-stage-elision](grhsim-ir-candidate-scalar-stage-elision-20260910.md) | VALIDATED / 最低均值：279.9485 s，仍有噪声限制 |
| [phase-profile](grhsim-ir-phase-profile-20260910.md) | 诊断：off/on 287.162/292.350 s，均对拍通过；完整生成/编译 606.29/477.30 s |
| [task-hotspots](grhsim-ir-task-hotspots-20260910.md) | 诊断：283.389 s，56,397 样本，对拍通过；未实施优化 |
